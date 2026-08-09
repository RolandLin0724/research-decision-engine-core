"""Deterministic, offline RDE Core v1 release-contract checker."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import types
from collections.abc import Callable, Mapping, Sequence
from importlib import resources
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, NoReturn, cast

import research_decision_engine
from research_decision_engine import (
    CompletedWorkloadExperiment,
    NormalizedObservation,
    RunSpec,
    policy_contract_for_schema,
    supported_policy_identities,
)
from research_decision_engine import run_bundle as run_bundle_module
from research_decision_engine import run_bundle_v2 as run_bundle_v2_module
from research_decision_engine import run_bundle_v3 as run_bundle_v3_module
from research_decision_engine.belief_models import (
    MatchedEffectObservation,
    belief_models,
    initial_model_lineage,
)
from research_decision_engine.benchmarks.worlds import (
    build_benchmark_world,
    paired_evaluation_worlds,
)
from research_decision_engine.calibration import build_calibration_prefix
from research_decision_engine.core_contract import (
    PUBLIC_API_MANIFEST_SCHEMA,
    resolve_import_path,
    verify_packaged_manifest_matches_live,
)
from research_decision_engine.core_fixtures import (
    FIXTURE_DIRECTORY,
    load_fixture_manifest,
    verify_packaged_fixtures,
)
from research_decision_engine.optimizer_effect import synchronize_optimizer_reasoning
from research_decision_engine.robust_storage import RobustBeliefStore
from research_decision_engine.runner import (
    suggest_information_gain,
    suggest_lookahead_information_gain,
)
from research_decision_engine.storage import SCHEMA_VERSION, ExperimentStore
from research_decision_engine.types import ExperimentRecord
from research_decision_engine.world import DeterministicSyntheticWorld

RELEASE_CHECK_RESULT_SCHEMA = "rde-core-release-check-result/v1"
_MIGRATION_EDGES = ((1, 2), (2, 3), (3, 4), (4, 5), (5, 6))
_SCHEMA_STATEMENT_COUNTS = {2: 8, 3: 3, 4: 1, 5: 17, 6: 1}
_FAULT_CASES = (
    "after_begin",
    "before_first",
    "after_first",
    "after_middle",
    "after_final",
    "postcondition",
    "before_user_version",
    "after_user_version",
    "validate_user_version",
)
_V5_REQUIRED_NONEMPTY_TABLES = (
    "belief_model_lineages",
    "belief_models",
    "belief_state_evidence",
    "belief_state_probabilities",
    "belief_states",
    "belief_update_likelihoods",
    "belief_updates",
    "calibration_cost_entries",
    "calibration_experiment_arms",
    "calibration_groups",
    "calibration_matched_effects",
    "calibration_prefixes",
    "calibration_replications",
    "decision_cost_entries",
    "decision_hypotheses",
    "decision_ranked_candidates",
    "decision_traces",
    "evidence",
    "evidence_sources",
    "experiments",
    "hypotheses",
    "lookahead_plan_traces",
    "model_adequacy_diagnostics",
    "model_belief_states",
    "model_belief_update_likelihoods",
    "model_belief_updates",
    "sigma_estimate_sources",
    "sigma_estimates",
)
_NODE_ID_REPLACEMENTS = (
    (r"[C:\\temp\\secret.dat]", "[path-negative-windows-drive-absolute]"),
    (r"[\\temp\\secret.dat]", "[path-negative-windows-rooted]"),
    (r"[C:temp\\secret.dat]", "[path-negative-windows-drive-relative]"),
    ("[/tmp/secret.dat]", "[path-negative-posix-absolute]"),
    ("[file:///C:/temp/secret.dat]", "[path-negative-file-windows]"),
    ("[file:///tmp/secret.dat]", "[path-negative-file-posix]"),
    ("[file://server/share/secret.dat]", "[path-negative-file-unc]"),
)


class CoreReleaseCheckError(RuntimeError):
    """One deterministic Core release-contract check failed."""


class _InjectedMigrationError(RuntimeError):
    pass


def _normalized_sql(sql: str) -> str:
    return " ".join(sql.split()).upper().rstrip(";")


def _is_schema_mutation(sql: str) -> bool:
    return _normalized_sql(sql).startswith(
        (
            "ALTER TABLE ",
            "CREATE INDEX ",
            "CREATE TABLE ",
            "CREATE TRIGGER ",
            "CREATE VIEW ",
            "DROP INDEX ",
            "DROP TABLE ",
            "DROP TRIGGER ",
            "DROP VIEW ",
        )
    )


def _assigned_user_version(sql: str) -> int | None:
    match = re.fullmatch(r"PRAGMA USER_VERSION = (-?[0-9]+)", _normalized_sql(sql))
    return None if match is None else int(match.group(1))


class _FaultConnection(sqlite3.Connection):
    def arm(
        self,
        *,
        source_version: int,
        target_version: int,
        case: str,
        fault: BaseException,
    ) -> None:
        self._fault_source_version = source_version
        self._fault_target_version = target_version
        self._fault_case = case
        self._fault = fault
        self._schema_statement_count = _SCHEMA_STATEMENT_COUNTS[target_version]
        self._schema_statements_seen = 0
        self._target_edge_active = False
        self._user_version_assigned = False

    def _version(self) -> int:
        row = sqlite3.Connection.execute(self, "PRAGMA user_version").fetchone()
        if row is None:
            raise CoreReleaseCheckError("SQLite did not return user_version.")
        return int(row[0])

    def _raise_fault(self) -> NoReturn:
        raise self._fault

    def _fault_ordinal(self) -> int:
        if self._fault_case == "after_first":
            return 1
        if self._fault_case == "after_middle":
            return (self._schema_statement_count + 1) // 2
        if self._fault_case == "after_final":
            return self._schema_statement_count
        raise AssertionError(f"No mutation ordinal for {self._fault_case!r}.")

    def execute(self, sql: str, parameters: object = (), /) -> sqlite3.Cursor:
        normalized = _normalized_sql(sql)
        if normalized == "BEGIN IMMEDIATE" and self._fault_case == "after_begin":
            sqlite3.Connection.execute(self, sql, cast(Any, parameters))
            self._raise_fault()

        target_mutation = _is_schema_mutation(sql) and self._version() == self._fault_source_version
        if target_mutation:
            self._target_edge_active = True
            if self._fault_case == "before_first" and self._schema_statements_seen == 0:
                self._raise_fault()
            cursor = sqlite3.Connection.execute(self, sql, cast(Any, parameters))
            self._schema_statements_seen += 1
            if (
                self._fault_case.startswith("after_")
                and self._fault_case not in {"after_begin", "after_user_version"}
                and self._schema_statements_seen == self._fault_ordinal()
            ):
                self._raise_fault()
            return cursor

        if (
            self._target_edge_active
            and not self._user_version_assigned
            and self._fault_case == "postcondition"
            and "FROM SQLITE_SCHEMA" in normalized
        ):
            self._raise_fault()

        assigned_version = _assigned_user_version(sql)
        target_assignment = (
            self._target_edge_active and assigned_version == self._fault_target_version
        )
        if target_assignment and self._fault_case == "before_user_version":
            self._raise_fault()
        if (
            self._user_version_assigned
            and normalized == "PRAGMA USER_VERSION"
            and self._fault_case == "validate_user_version"
        ):
            self._raise_fault()

        cursor = sqlite3.Connection.execute(self, sql, cast(Any, parameters))
        if target_assignment:
            self._user_version_assigned = True
            if self._fault_case == "after_user_version":
                self._raise_fault()
        return cursor


def _open_connection(
    path: Path, factory: type[sqlite3.Connection] = sqlite3.Connection
) -> sqlite3.Connection:
    connection = sqlite3.connect(path, factory=factory)
    connection.row_factory = sqlite3.Row
    sqlite3.Connection.execute(connection, "PRAGMA foreign_keys = ON")
    return connection


def _attach_store(path: Path, connection: sqlite3.Connection) -> ExperimentStore:
    store = ExperimentStore(path)
    store.connection = connection
    return store


def _user_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    if row is None:
        raise CoreReleaseCheckError("SQLite did not return user_version.")
    return int(row[0])


def _create_legacy_database(path: Path, version: int) -> None:
    if not 1 <= version <= 6:
        raise ValueError("Legacy fixture version must be in [1, 6].")
    connection = _open_connection(path)
    store = _attach_store(path, connection)
    try:
        for source_version in range(version):
            store._migrate_one_step(connection, source_version, source_version + 1)
        _populate_legacy_database(store, version)
        if version >= 5:
            empty = [
                name
                for name in _V5_REQUIRED_NONEMPTY_TABLES
                if connection.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0] == 0
            ]
            if empty:
                raise CoreReleaseCheckError(
                    "The exact v5 compatibility fixture has empty required tables: "
                    + ", ".join(empty)
                )
    finally:
        connection.close()
        store.connection = None


def _populate_legacy_database(store: ExperimentStore, version: int) -> None:
    world = DeterministicSyntheticWorld()
    records = []
    for candidate in world.candidates()[:2]:
        observed, true_value, cost = world.evaluate(candidate)
        records.append(
            store.add_record(
                ExperimentRecord(
                    record_id=None,
                    candidate=candidate,
                    policy="release-check-policy",
                    observed_value=observed,
                    true_value=true_value,
                    cost=cost,
                    created_at=f"release-check-{candidate.candidate_id}",
                )
            )
        )
    if version >= 2:
        synchronize_optimizer_reasoning(store)
    if version >= 3:
        suggest_information_gain(store, max_cost=1.0)
    if version >= 4:
        suggest_lookahead_information_gain(store, max_cost=2.2)
    if version < 5:
        return

    config = paired_evaluation_worlds()[3]
    design, benchmark_world = build_benchmark_world(config, seed=4)
    prefix = build_calibration_prefix(
        world_id=config.world_id,
        evaluation_seed=4,
        designs=design.evidence_eligibility().designs,
        candidates={item.candidate_id: item for item in design.candidates},
        cost=design.cost,
        observe_pair=benchmark_world.observe_calibration_pair,
        created_at="release-check-t0",
    )
    robust = RobustBeliefStore(store)
    robust.add_calibration_prefix(prefix)
    evidence = store.list_evidence()[0]
    calibration_history = tuple(
        MatchedEffectObservation.from_calibration(item) for item in prefix.matched_effects
    )
    for model in belief_models():
        lineage = initial_model_lineage(
            model,
            lineage_key="release-check",
            created_at="release-check-t0",
        )
        robust.add_lineage(lineage)
        _, update, _ = model.update(
            lineage=lineage,
            evidence=evidence,
            effect_history=calibration_history,
            diagnostic_history=(),
        )
        robust.add_model_update(update, effect_history=calibration_history)
    for record in records:
        robust.add_decision_cost(run_id="release-check", record=record)


def _logical_value(value: object) -> object:
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        return {"float_hex": value.hex()}
    if type(value) is bytes:
        return {"bytes_hex": value.hex()}
    raise CoreReleaseCheckError(f"Unsupported SQLite value type {type(value).__name__}.")


def _logical_database_snapshot(path: Path) -> bytes:
    connection = _open_connection(path)
    try:
        schema = [
            [str(row[0]), str(row[1]), str(row[2]), None if row[3] is None else str(row[3])]
            for row in connection.execute(
                """
                SELECT type, name, tbl_name, sql
                FROM sqlite_schema
                WHERE type IN ('table', 'index', 'trigger', 'view')
                  AND substr(name, 1, 7) != 'sqlite_'
                ORDER BY type, name, tbl_name
                """
            ).fetchall()
        ]
        table_names = [cast(str, row[1]) for row in schema if row[0] == "table"]
        tables = []
        for table_name in table_names:
            quoted = '"' + table_name.replace('"', '""') + '"'
            rows = [
                [_logical_value(value) for value in tuple(row)]
                for row in connection.execute(f"SELECT * FROM {quoted}").fetchall()
            ]
            rows.sort(
                key=lambda value: json.dumps(
                    value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
            )
            tables.append({"name": table_name, "rows": rows})
        payload = {
            "user_version": _user_version(connection),
            "schema": schema,
            "tables": tables,
        }
        return (
            json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
    finally:
        connection.close()


def _assert_legacy_snapshot_preserved(opening: bytes, migrated: bytes) -> None:
    opening_payload = cast(dict[str, object], json.loads(opening))
    migrated_payload = cast(dict[str, object], json.loads(migrated))
    opening_schema = {
        tuple(cast(list[object], entry)) for entry in cast(list[object], opening_payload["schema"])
    }
    migrated_schema = {
        tuple(cast(list[object], entry)) for entry in cast(list[object], migrated_payload["schema"])
    }
    if not opening_schema.issubset(migrated_schema):
        raise CoreReleaseCheckError("A legacy SQLite schema object changed during migration.")
    opening_tables = {
        cast(str, entry["name"]): entry["rows"]
        for entry in cast(list[dict[str, object]], opening_payload["tables"])
    }
    migrated_tables = {
        cast(str, entry["name"]): entry["rows"]
        for entry in cast(list[dict[str, object]], migrated_payload["tables"])
    }
    if any(migrated_tables.get(name) != rows for name, rows in opening_tables.items()):
        raise CoreReleaseCheckError("Legacy SQLite rows changed during migration.")


def _exercise_runspec_persistence_after_v5_migration(path: Path) -> str:
    candidate = research_decision_engine.CandidateSpec(
        "release-check-workload",
        {"rank": 1},
    )
    run_spec = RunSpec(
        candidates=(candidate,),
        policy_id="random",
        policy_config={},
        policy_seed=17,
        experiment_count_budget=1,
        adapter_id="release-check-adapter",
        adapter_version="1",
        objective_name="score",
        objective_direction="maximize",
    )
    record = CompletedWorkloadExperiment(
        run_spec_fingerprint=run_spec.fingerprint(),
        candidate=candidate,
        policy_id="random",
        observation=NormalizedObservation(objective_value=0.75, cost=0.25),
        created_at="2026-01-01T00:00:00+00:00",
    )
    with ExperimentStore(path) as store:
        store.init_schema()
        stored = store.add_workload_experiment(record)
        if stored != record:
            raise CoreReleaseCheckError("RunSpec persistence changed its workload record.")
    with ExperimentStore(path) as reopened:
        reopened.init_schema()
        if reopened.list_workload_experiments(run_spec.fingerprint()) != [record]:
            raise CoreReleaseCheckError("RunSpec persistence did not survive close/reopen.")
    return run_spec.fingerprint()


def _assert_integrity(path: Path) -> None:
    connection = _open_connection(path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or tuple(integrity) != ("ok",):
            raise CoreReleaseCheckError("SQLite integrity_check did not return ok.")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise CoreReleaseCheckError("SQLite foreign_key_check found a violation.")
    finally:
        connection.close()


def _check_public_api() -> Mapping[str, object]:
    manifest = verify_packaged_manifest_matches_live()
    symbols = cast(list[dict[str, object]], manifest["public_symbols"])
    for entry in symbols:
        resolve_import_path(cast(str, entry["import_path"]))
    root_paths = {f"research_decision_engine.{name}" for name in research_decision_engine.__all__}
    declared_paths = {cast(str, entry["import_path"]) for entry in symbols}
    if len(root_paths) != 110 or not root_paths < declared_paths:
        raise CoreReleaseCheckError("The 110-symbol package-root surface is not preserved.")
    direct = declared_paths - root_paths
    if direct != {
        "research_decision_engine.storage.ExperimentStore",
        "research_decision_engine.storage.SCHEMA_VERSION",
    }:
        raise CoreReleaseCheckError("The deliberate SQLite-facing surface differs.")
    assurance_tokens = ("assurance", "broader", "package_l", "package_p", "p4")
    accidental = []
    for entry in symbols:
        path = cast(str, entry["import_path"])
        value = resolve_import_path(path)
        origin = cast(str, getattr(value, "__module__", type(value).__module__))
        searchable = " ".join((path, origin, cast(str, entry["signature_or_fields"]))).lower()
        if any(token in searchable for token in assurance_tokens):
            accidental.append(path)
    if accidental:
        raise CoreReleaseCheckError("An Assurance symbol entered the Core public manifest.")
    root_extras = {
        name: value
        for name, value in vars(research_decision_engine).items()
        if not name.startswith("_") and name not in research_decision_engine.__all__
    }
    if any(
        not isinstance(value, types.ModuleType)
        or not value.__name__.startswith("research_decision_engine.")
        or any(token in value.__name__.lower() for token in assurance_tokens)
        for value in root_extras.values()
    ):
        raise CoreReleaseCheckError("An accidental package-root export exists outside __all__.")
    return {
        "manifest_schema": PUBLIC_API_MANIFEST_SCHEMA,
        "public_symbol_count": len(symbols),
        "package_root_symbol_count": len(root_paths),
        "assurance_export_count": 0,
        "accidental_export_count": 0,
        "internal_root_module_count": len(root_extras),
    }


def _check_schema_and_policy_matrix() -> Mapping[str, object]:
    expected = {
        "rde-core-run-spec/v1": (
            "rde-core-run-bundle/v1",
            "RECORDED_OBSERVATION_DECISION_REPLAY_V1",
            ("random",),
        ),
        "rde-core-run-spec/v2": (
            "rde-core-run-bundle/v2",
            "RECORDED_OBSERVATION_DECISION_REPLAY_V2",
            ("random", "greedy_prior"),
        ),
        "rde-core-run-spec/v3": (
            "rde-core-run-bundle/v3",
            "RECORDED_OBSERVATION_DECISION_REPLAY_V3",
            ("random", "greedy_prior", "information_gain_table"),
        ),
    }
    for run_spec_schema, (bundle_schema, replay_contract, policies) in expected.items():
        contract = policy_contract_for_schema(run_spec_schema)
        actual = (
            contract.run_bundle_schema,
            contract.replay_contract,
            supported_policy_identities(run_spec_schema),
        )
        if actual != (bundle_schema, replay_contract, policies):
            raise CoreReleaseCheckError(f"Schema matrix differs for {run_spec_schema}.")
    if SCHEMA_VERSION != 6:
        raise CoreReleaseCheckError("SQLite latest schema is not v6.")
    return {
        "runspec_versions": ["v1", "v2", "v3"],
        "runbundle_versions": ["v1", "v2", "v3"],
        "replay_versions": ["v1", "v2", "v3"],
        "recommended_new_run_schema": "v3",
        "sqlite_latest_schema": SCHEMA_VERSION,
    }


def _check_fixtures() -> Mapping[str, object]:
    manifest = verify_packaged_fixtures()
    entries = cast(list[dict[str, object]], manifest["fixtures"])
    return {
        "fixture_count": len(entries),
        "fixture_manifest_schema": manifest["schema_version"],
        "fixture_hashes_verified": len(entries),
        "hygiene": "PASS",
    }


def _check_migration_success_matrix() -> Mapping[str, object]:
    terminal_versions: dict[str, int] = {}
    with TemporaryDirectory(prefix="rde-core-release-success-") as temporary:
        root = Path(temporary)
        for source_version in range(1, 7):
            path = root / f"v{source_version}.sqlite3"
            _create_legacy_database(path, source_version)
            opening = _logical_database_snapshot(path)
            with ExperimentStore(path) as store:
                store.init_schema()
                terminal = store.schema_version()
                records = store.list_records()
            if terminal != 6 or len(records) != 2:
                raise CoreReleaseCheckError(
                    f"Migration v{source_version}->v6 did not preserve its row."
                )
            migrated = _logical_database_snapshot(path)
            if source_version == 6:
                if migrated != opening:
                    raise CoreReleaseCheckError("Schema v6 reopen was not an exact no-op.")
            else:
                _assert_legacy_snapshot_preserved(opening, migrated)
            if source_version == 5:
                _exercise_runspec_persistence_after_v5_migration(path)
            _assert_integrity(path)
            terminal_versions[f"v{source_version}->v6"] = terminal

        new_path = root / "new.sqlite3"
        with ExperimentStore(new_path) as store:
            store.init_schema()
            if store.schema_version() != 6:
                raise CoreReleaseCheckError("A new database did not terminate at schema v6.")
    return {
        "matrix": terminal_versions,
        "new_database_schema": 6,
        "v6_reopen_noop": True,
        "v5_rows_and_runspec_persistence": "PRESERVED",
    }


def _check_migration_rollback_retry_matrix() -> Mapping[str, object]:
    cases_verified = 0
    with TemporaryDirectory(prefix="rde-core-release-fault-") as temporary:
        root = Path(temporary)
        for source_version, target_version in _MIGRATION_EDGES:
            for case in _FAULT_CASES:
                path = root / f"v{source_version}-v{target_version}-{case}.sqlite3"
                _create_legacy_database(path, source_version)
                opening = _logical_database_snapshot(path)
                connection = _open_connection(path, _FaultConnection)
                store = _attach_store(path, connection)
                fault = _InjectedMigrationError("injected release-check migration fault")
                cast(_FaultConnection, connection).arm(
                    source_version=source_version,
                    target_version=target_version,
                    case=case,
                    fault=fault,
                )
                try:
                    try:
                        store._migrate_one_step(connection, source_version, target_version)
                    except _InjectedMigrationError as error:
                        if error is not fault:
                            raise CoreReleaseCheckError(
                                "Migration fault identity changed."
                            ) from error
                    else:
                        raise CoreReleaseCheckError(
                            f"Migration fault {case} was not reached on "
                            f"{source_version}->{target_version}."
                        )
                finally:
                    connection.close()
                    store.connection = None
                if _logical_database_snapshot(path) != opening:
                    raise CoreReleaseCheckError(
                        f"Migration {source_version}->{target_version} did not roll back exactly."
                    )
                with ExperimentStore(path) as retry_store:
                    retry_store.init_schema()
                    if retry_store.schema_version() != 6 or len(retry_store.list_records()) != 2:
                        raise CoreReleaseCheckError(
                            f"Migration retry from v{source_version} did not reach exact v6."
                        )
                _assert_legacy_snapshot_preserved(opening, _logical_database_snapshot(path))
                _assert_integrity(path)
                cases_verified += 1
    return {
        "edges": [f"{source}->{target}" for source, target in _MIGRATION_EDGES],
        "fault_cases_per_edge": len(_FAULT_CASES),
        "rollback_retry_cases": cases_verified,
        "migration_model": "PER_VERSION_STEP_ATOMIC_AND_RESUMABLE",
    }


_ABRUPT_CHILD = r"""
import os
import sqlite3
import sys
from pathlib import Path
from research_decision_engine.storage import ExperimentStore

class AbruptConnection(sqlite3.Connection):
    def execute(self, sql, parameters=(), /):
        cursor = sqlite3.Connection.execute(self, sql, parameters)
        normalized = " ".join(sql.split()).upper()
        if normalized.startswith("CREATE TABLE "):
            os._exit(71)
        return cursor

path = Path(sys.argv[1])
connection = sqlite3.connect(path, factory=AbruptConnection)
connection.row_factory = sqlite3.Row
connection.execute("PRAGMA foreign_keys = ON")
store = ExperimentStore(path)
store.connection = connection
store._migrate_one_step(connection, 5, 6)
raise AssertionError("abrupt v5-to-v6 checkpoint was not reached")
"""


def _check_abrupt_v5_to_v6() -> Mapping[str, object]:
    with TemporaryDirectory(prefix="rde-core-release-abrupt-") as temporary:
        path = Path(temporary) / "abrupt.sqlite3"
        _create_legacy_database(path, 5)
        opening = _logical_database_snapshot(path)
        completed = subprocess.run(
            [sys.executable, "-B", "-c", _ABRUPT_CHILD, str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if completed.returncode != 71:
            raise CoreReleaseCheckError("Abrupt v5->v6 child did not reach its checkpoint.")
        if _logical_database_snapshot(path) != opening:
            raise CoreReleaseCheckError("Abrupt v5->v6 left a partial logical schema.")
        _assert_integrity(path)
        with ExperimentStore(path) as store:
            store.init_schema()
            if store.schema_version() != 6 or len(store.list_records()) != 2:
                raise CoreReleaseCheckError("Abrupt v5->v6 retry did not reach exact v6.")
        _assert_legacy_snapshot_preserved(opening, _logical_database_snapshot(path))
    return {"edge": "5->6", "terminal_after_interruption": 5, "retry_schema": 6}


def _check_future_schema_rejection() -> Mapping[str, object]:
    with TemporaryDirectory(prefix="rde-core-release-future-") as temporary:
        path = Path(temporary) / "future.sqlite3"
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE preserve_me (value TEXT NOT NULL)")
        connection.execute("INSERT INTO preserve_me VALUES ('unchanged')")
        connection.execute("PRAGMA user_version = 7")
        connection.commit()
        connection.close()
        opening = _logical_database_snapshot(path)
        try:
            with ExperimentStore(path) as store:
                store.init_schema()
        except RuntimeError:
            pass
        else:
            raise CoreReleaseCheckError("Future SQLite schema v7 was not rejected.")
        if _logical_database_snapshot(path) != opening:
            raise CoreReleaseCheckError("Future-schema rejection mutated the database.")
    return {"future_schema": 7, "mutation_count": 0, "result": "REJECTED"}


def _check_static_policy_factories() -> Mapping[str, object]:
    expected = {
        "v1": {"random"},
        "v2": {"random", "greedy_prior"},
        "v3": {"random", "greedy_prior", "information_gain_table"},
    }
    actual = {
        "v1": set(run_bundle_module._SUPPORTED_POLICY_FACTORIES),
        "v2": set(run_bundle_v2_module._SUPPORTED_POLICY_FACTORIES_V2),
        "v3": set(run_bundle_v3_module._SUPPORTED_POLICY_FACTORIES_V3),
    }
    if actual != expected:
        raise CoreReleaseCheckError("Replay policy factories differ from the finite static maps.")
    module_paths = (
        Path(run_bundle_module.__file__ or ""),
        Path(run_bundle_v2_module.__file__ or ""),
        Path(run_bundle_v3_module.__file__ or ""),
    )
    forbidden = ("import_module(", "entry_points(", "__import__(", "pkg_resources")
    for path in module_paths:
        source = path.read_text(encoding="utf-8")
        if any(token in source for token in forbidden):
            raise CoreReleaseCheckError("A replay module contains dynamic policy loading.")
    return {
        "dynamic_policy_loading": False,
        "factory_keys": {key: sorted(value) for key, value in actual.items()},
    }


def _resource_lines(path: str) -> tuple[str, ...]:
    raw = resources.files("research_decision_engine").joinpath(FIXTURE_DIRECTORY, path).read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise CoreReleaseCheckError(f"Node stream {path} is not canonical LF text.")
    lines = tuple(line for line in raw.decode("utf-8").splitlines() if line)
    if len(lines) != len(set(lines)):
        raise CoreReleaseCheckError(f"Node stream {path} contains duplicate nodes.")
    return lines


def _canonical_node_id(value: str) -> str:
    for source, replacement in _NODE_ID_REPLACEMENTS:
        value = value.replace(source, replacement)
    return value


def _check_core_test_membership() -> Mapping[str, object]:
    final_nodes = _resource_lines("core-test-nodeids.txt")
    opening_nodes = _resource_lines("core-opening-nodeids.txt")
    if len(opening_nodes) != 541 or not set(opening_nodes).issubset(final_nodes):
        raise CoreReleaseCheckError("An opening 541-node Core test disappeared.")
    package_root = Path(research_decision_engine.__file__ or "").resolve().parent.parent
    manifest_path = package_root / "tests" / "core_v1_pytest.txt"
    test_file_count: int | None = None
    current_collection_verified = False
    if manifest_path.is_file():
        entries = tuple(
            line.strip()
            for line in manifest_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if entries != tuple(sorted(entries)) or len(entries) != len(set(entries)):
            raise CoreReleaseCheckError("Core pytest membership must be sorted and unique.")
        if not all((package_root / entry).is_file() for entry in entries):
            raise CoreReleaseCheckError("Core pytest membership references a missing file.")
        if {node.split("::", 1)[0] for node in final_nodes} != set(entries):
            raise CoreReleaseCheckError("Canonical Core nodes differ from test-file membership.")
        completed = subprocess.run(
            [sys.executable, "-B", "-m", "pytest", "--collect-only", "-q"],
            cwd=package_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise CoreReleaseCheckError("Current Core pytest collection failed.")
        collected = tuple(
            _canonical_node_id(line) for line in completed.stdout.splitlines() if "::" in line
        )
        if collected != final_nodes:
            raise CoreReleaseCheckError("Current Core pytest nodes differ from the fixture.")
        test_file_count = len(entries)
        current_collection_verified = True
    return {
        "opening_node_count": len(opening_nodes),
        "final_node_count": len(final_nodes),
        "opening_nodes_removed": 0,
        "source_test_file_count": test_file_count,
        "current_collection_verified": current_collection_verified,
        "final_node_sha256": hashlib.sha256(("\n".join(final_nodes) + "\n").encode()).hexdigest(),
    }


def _check_required_package_data() -> Mapping[str, object]:
    manifest = load_fixture_manifest()
    entries = cast(list[dict[str, object]], manifest["fixtures"])
    required_roles = {
        "public_api_manifest",
        "run_spec_v1_canonical_bytes",
        "run_spec_v2_canonical_bytes",
        "run_spec_v3_canonical_bytes",
        "evidence_model_fingerprint",
        "representative_decisions_and_rationales",
        "information_gain_belief_lineage",
        "replay_terminal_summaries",
        "cross_platform_core_test_node_stream",
        "opening_core_test_node_stream",
    }
    roles = {cast(str, entry["semantic_role"]) for entry in entries}
    if not required_roles.issubset(roles):
        raise CoreReleaseCheckError("Required semantic package data is incomplete.")
    for version in range(1, 7):
        if f"sqlite_v{version}_logical_schema" not in roles:
            raise CoreReleaseCheckError(f"SQLite v{version} logical fixture is missing.")
    return {"required_roles": len(required_roles) + 6, "package_data": "PASS"}


CheckFunction = Callable[[], Mapping[str, object]]
DEFAULT_CHECKS: tuple[tuple[str, CheckFunction], ...] = (
    ("public_api", _check_public_api),
    ("schema_policy_matrix", _check_schema_and_policy_matrix),
    ("canonical_fixtures", _check_fixtures),
    ("migration_success_matrix", _check_migration_success_matrix),
    ("migration_rollback_retry_matrix", _check_migration_rollback_retry_matrix),
    ("abrupt_v5_to_v6", _check_abrupt_v5_to_v6),
    ("future_schema_rejection", _check_future_schema_rejection),
    ("static_policy_factories", _check_static_policy_factories),
    ("core_test_membership", _check_core_test_membership),
    ("required_package_data", _check_required_package_data),
)


def execute_release_checks(
    checks: Sequence[tuple[str, CheckFunction]] = DEFAULT_CHECKS,
    *,
    installed: bool = False,
) -> dict[str, object]:
    """Execute checks without network or user-workload calls and retain every result."""

    if installed and "site-packages" not in str(Path(__file__).resolve()).lower():
        return {
            "schema_version": RELEASE_CHECK_RESULT_SCHEMA,
            "contract_name": "RDE_CORE_PUBLIC_API_V1",
            "environment": "installed_wheel",
            "overall": "FAIL",
            "checks": [
                {
                    "name": "installed_environment",
                    "status": "FAIL",
                    "details": {"error": "checker is not running from site-packages"},
                }
            ],
        }
    results: list[dict[str, object]] = []
    for name, check in checks:
        try:
            details = dict(check())
        except Exception as error:
            results.append(
                {
                    "name": name,
                    "status": "FAIL",
                    "details": {
                        "error_type": type(error).__name__,
                        "error": str(error),
                    },
                }
            )
        else:
            results.append({"name": name, "status": "PASS", "details": details})
    overall = "PASS" if all(result["status"] == "PASS" for result in results) else "FAIL"
    return {
        "schema_version": RELEASE_CHECK_RESULT_SCHEMA,
        "contract_name": "RDE_CORE_PUBLIC_API_V1",
        "environment": "installed_wheel" if installed else "source_or_distribution",
        "overall": overall,
        "checks": results,
    }


def canonical_release_check_json(result: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            result,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _collect_nodeids(destination: Path) -> int:
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "--collect-only", "-q"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        return completed.returncode
    nodes = tuple(
        _canonical_node_id(line) for line in completed.stdout.splitlines() if "::" in line
    )
    if not nodes or len(nodes) != len(set(nodes)):
        sys.stderr.write("Core collection returned an empty or duplicate node stream.\n")
        return 1
    destination.write_bytes(("\n".join(nodes) + "\n").encode("utf-8"))
    sys.stderr.write(f"Collected {len(nodes)} canonical Core node IDs.\n")
    return 0


def _compare_nodeids(paths: Sequence[Path]) -> int:
    raw = [path.read_bytes() for path in paths]
    if any(value != raw[0] for value in raw[1:]):
        sys.stderr.write("Core node-ID streams differ.\n")
        return 1
    sys.stderr.write("Core node-ID streams are byte-identical.\n")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--installed",
        action="store_true",
        help="Require execution from a clean installed-wheel environment.",
    )
    parser.add_argument(
        "--collect-nodeids",
        type=Path,
        metavar="PATH",
        help="Collect the configured Core suite and write its canonical node stream.",
    )
    parser.add_argument(
        "--compare-nodeids",
        type=Path,
        nargs=3,
        metavar=("RUN1", "RUN2", "EXPECTED"),
        help="Require two collections and the committed cross-platform stream to match.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.collect_nodeids is not None:
        if args.installed or args.compare_nodeids is not None:
            _parser().error("--collect-nodeids cannot be combined with other modes")
        return _collect_nodeids(cast(Path, args.collect_nodeids))
    if args.compare_nodeids is not None:
        if args.installed:
            _parser().error("--compare-nodeids cannot be combined with --installed")
        return _compare_nodeids(cast(Sequence[Path], args.compare_nodeids))

    result = execute_release_checks(installed=bool(args.installed))
    for check in cast(list[dict[str, object]], result["checks"]):
        sys.stderr.write(f"{check['status']} {check['name']}\n")
    sys.stderr.write(f"RDE Core v1 release check: {result['overall']}\n")
    sys.stdout.buffer.write(canonical_release_check_json(result))
    sys.stdout.buffer.flush()
    return 0 if result["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
