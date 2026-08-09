from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

import pytest

from research_decision_engine import (
    CandidateSpec,
    NormalizedObservation,
    PythonFunctionAdapter,
    RunSpec,
    export_run_bundle,
    replay_run_bundle,
    run_workload_trace,
)
from research_decision_engine.command_adapter import CommandAdapter
from research_decision_engine.optimizer_effect import synchronize_optimizer_reasoning
from research_decision_engine.runner import (
    suggest_information_gain,
    suggest_lookahead_information_gain,
)
from research_decision_engine.storage import SCHEMA_VERSION, ExperimentStore
from research_decision_engine.types import ExperimentRecord
from research_decision_engine.world import DeterministicSyntheticWorld

MIGRATION_EDGES = ((1, 2), (2, 3), (3, 4), (4, 5), (5, 6))
SCHEMA_STATEMENT_COUNTS = {2: 8, 3: 3, 4: 1, 5: 17, 6: 1}

_V1_TABLES = frozenset({"experiments"})
_V2_TABLES = _V1_TABLES | {
    "belief_state_evidence",
    "belief_state_probabilities",
    "belief_states",
    "belief_update_likelihoods",
    "belief_updates",
    "evidence",
    "evidence_sources",
    "hypotheses",
}
_V3_TABLES = _V2_TABLES | {
    "decision_hypotheses",
    "decision_ranked_candidates",
    "decision_traces",
}
_V4_TABLES = _V3_TABLES | {"lookahead_plan_traces"}
_V5_TABLES = _V4_TABLES | {
    "belief_model_lineages",
    "belief_models",
    "calibration_cost_entries",
    "calibration_experiment_arms",
    "calibration_groups",
    "calibration_matched_effects",
    "calibration_prefixes",
    "calibration_replications",
    "decision_cost_entries",
    "model_adequacy_diagnostics",
    "model_belief_states",
    "model_belief_update_likelihoods",
    "model_belief_updates",
    "sigma_estimate_sources",
    "sigma_estimates",
}
_V6_TABLES = _V5_TABLES | {"workload_experiments"}

EXPECTED_TABLES = {
    1: _V1_TABLES,
    2: _V2_TABLES,
    3: _V3_TABLES,
    4: _V4_TABLES,
    5: _V5_TABLES,
    6: _V6_TABLES,
}
EXPECTED_TRIGGERS = {
    1: frozenset(),
    2: frozenset(),
    3: frozenset(),
    4: frozenset(),
    5: frozenset(
        {
            "calibration_cost_ledger_disjoint",
            "decision_cost_ledger_disjoint",
        }
    ),
    6: frozenset(
        {
            "calibration_cost_ledger_disjoint",
            "decision_cost_ledger_disjoint",
        }
    ),
}


class InjectedMigrationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FaultCase:
    name: str
    stage: str
    statement_position: str | None = None


FAULT_CASES = (
    FaultCase("after-begin-before-first-mutation", "after_begin"),
    FaultCase("before-first-mutation", "before_first"),
    FaultCase("after-first-mutation", "after_statement", "first"),
    FaultCase("after-middle-mutation", "after_statement", "middle"),
    FaultCase("after-final-schema-mutation", "after_statement", "final"),
    FaultCase("during-postcondition-validation", "postcondition"),
    FaultCase("while-setting-user-version", "before_user_version"),
    FaultCase("after-setting-user-version", "after_user_version"),
    FaultCase("while-validating-user-version", "validate_user_version"),
)


def _normalized_sql(sql: str) -> str:
    return " ".join(sql.split()).upper().rstrip(";")


def _assigned_user_version(sql: str) -> int | None:
    prefix = "PRAGMA USER_VERSION = "
    normalized = _normalized_sql(sql)
    if not normalized.startswith(prefix):
        return None
    try:
        return int(normalized.removeprefix(prefix))
    except ValueError:
        return None


def _is_schema_mutation(sql: str) -> bool:
    normalized = _normalized_sql(sql)
    return normalized.startswith(
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


class FaultConnection(sqlite3.Connection):
    def arm(
        self,
        *,
        source_version: int,
        target_version: int,
        case: FaultCase,
        schema_statement_count: int,
        fault: BaseException,
    ) -> None:
        self._fault_source_version = source_version
        self._fault_target_version = target_version
        self._fault_case = case
        self._fault = fault
        self._schema_statement_count = schema_statement_count
        self._schema_statements_seen = 0
        self._target_edge_active = False
        self._user_version_assigned = False

    def _current_user_version(self) -> int:
        row = sqlite3.Connection.execute(self, "PRAGMA user_version").fetchone()
        assert row is not None
        return int(row[0])

    def _raise_fault(self) -> NoReturn:
        raise self._fault

    def _fault_statement_ordinal(self) -> int:
        position = self._fault_case.statement_position
        if position == "first":
            return 1
        if position == "middle":
            return (self._schema_statement_count + 1) // 2
        if position == "final":
            return self._schema_statement_count
        raise AssertionError(f"Unknown statement position: {position!r}")

    def execute(
        self,
        sql: str,
        parameters: object = (),
        /,
    ) -> sqlite3.Cursor:
        if _normalized_sql(sql) == "BEGIN IMMEDIATE" and self._fault_case.stage == "after_begin":
            sqlite3.Connection.execute(self, sql, cast(Any, parameters))
            self._raise_fault()
        target_schema_statement = (
            _is_schema_mutation(sql) and self._current_user_version() == self._fault_source_version
        )
        if target_schema_statement:
            self._target_edge_active = True
            if self._fault_case.stage == "before_first" and self._schema_statements_seen == 0:
                self._raise_fault()
            cursor = sqlite3.Connection.execute(self, sql, cast(Any, parameters))
            self._schema_statements_seen += 1
            if (
                self._fault_case.stage == "after_statement"
                and self._schema_statements_seen == self._fault_statement_ordinal()
            ):
                self._raise_fault()
            return cursor

        assigned_version = _assigned_user_version(sql)
        target_version_assignment = (
            self._target_edge_active and assigned_version == self._fault_target_version
        )
        if (
            self._target_edge_active
            and not self._user_version_assigned
            and self._fault_case.stage == "postcondition"
            and "FROM SQLITE_SCHEMA" in _normalized_sql(sql)
        ):
            self._raise_fault()
        if target_version_assignment and self._fault_case.stage == "before_user_version":
            self._raise_fault()
        if (
            self._user_version_assigned
            and _normalized_sql(sql) == "PRAGMA USER_VERSION"
            and self._fault_case.stage == "validate_user_version"
        ):
            self._raise_fault()

        cursor = sqlite3.Connection.execute(self, sql, cast(Any, parameters))
        if target_version_assignment:
            self._user_version_assigned = True
            if self._fault_case.stage == "after_user_version":
                self._raise_fault()
        return cursor


class RollbackBaseExceptionConnection(FaultConnection):
    def arm_rollback_fault(self, fault: BaseException) -> None:
        self._rollback_fault = fault

    def rollback(self) -> None:
        sqlite3.Connection.rollback(self)
        raise self._rollback_fault


@contextmanager
def _open_store(
    db_path: Path,
    *,
    connection_factory: type[sqlite3.Connection] = sqlite3.Connection,
) -> Iterator[tuple[ExperimentStore, sqlite3.Connection]]:
    connection = sqlite3.connect(db_path, factory=connection_factory)
    connection.row_factory = sqlite3.Row
    sqlite3.Connection.execute(connection, "PRAGMA foreign_keys = ON")
    store = ExperimentStore(db_path)
    store.connection = connection
    try:
        yield store, connection
    finally:
        connection.close()
        store.connection = None


def _migration_method(store: ExperimentStore, target_version: int) -> object:
    return getattr(store, f"_migrate_to_v{target_version}")


def _apply_edge_without_runner(
    store: ExperimentStore,
    connection: sqlite3.Connection,
    source_version: int,
    target_version: int,
) -> None:
    assert _user_version(connection) == source_version
    connection.execute("BEGIN IMMEDIATE")
    try:
        migration = _migration_method(store, target_version)
        assert callable(migration)
        migration(connection)
        connection.execute(f"PRAGMA user_version = {target_version}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _apply_edge_without_runner_at_path(
    db_path: Path,
    source_version: int,
    target_version: int,
) -> None:
    with _open_store(db_path) as (store, connection):
        _apply_edge_without_runner(store, connection, source_version, target_version)


def _migrate_repair_chain_to_v5(store: ExperimentStore, connection: sqlite3.Connection) -> None:
    source_version = _user_version(connection)
    assert 1 <= source_version <= 5
    while source_version < 5:
        store._migrate_one_step(connection, source_version, source_version + 1)
        source_version += 1


def _build_legacy_database(db_path: Path, version: int, *, populate: bool = True) -> None:
    assert 1 <= version <= 5
    with _open_store(db_path) as (store, connection):
        for target_version in range(1, version + 1):
            _apply_edge_without_runner(
                store,
                connection,
                target_version - 1,
                target_version,
            )
        if populate:
            _populate_legacy_rows(store, version)
        _assert_exact_version_schema(connection, version)


def _populate_legacy_rows(store: ExperimentStore, version: int) -> None:
    world = DeterministicSyntheticWorld()
    for candidate in world.candidates()[:2]:
        observed_value, true_value, cost = world.evaluate(candidate)
        store.add_record(
            ExperimentRecord(
                record_id=None,
                candidate=candidate,
                policy="migration-fixture",
                observed_value=observed_value,
                true_value=true_value,
                cost=cost,
                created_at=f"fixture-{candidate.candidate_id}",
            )
        )
    if version >= 2:
        synchronize_optimizer_reasoning(store)
        assert store.list_hypotheses()
        assert store.list_evidence()
        assert store.list_belief_updates()
    if version >= 3:
        suggest_information_gain(store, max_cost=1.0)
        assert store.list_decision_traces()
    if version >= 4:
        suggest_lookahead_information_gain(store, max_cost=2.2)
        assert store.list_lookahead_plan_traces()


def _clone_database(source: Path, destination: Path) -> None:
    shutil.copyfile(source, destination)


def _user_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    assert row is not None
    return int(row[0])


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _logical_value(value: object) -> list[object]:
    if value is None:
        return ["null", None]
    if type(value) is int:
        return ["integer", str(value)]
    if type(value) is float:
        return ["real", value.hex()]
    if type(value) is str:
        return ["text", value]
    if type(value) is bytes:
        return ["blob", value.hex()]
    raise AssertionError(f"Unsupported SQLite value type: {type(value)!r}")


def _logical_row(row: sqlite3.Row | tuple[object, ...]) -> list[list[object]]:
    return [_logical_value(value) for value in tuple(row)]


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _logical_snapshot(connection: sqlite3.Connection) -> bytes:
    schema_rows = connection.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_schema
        WHERE type IN ('table', 'index', 'trigger', 'view')
          AND substr(name, 1, 7) != 'sqlite_'
        ORDER BY type, name, tbl_name
        """
    ).fetchall()
    table_names = tuple(str(row[1]) for row in schema_rows if str(row[0]) == "table")
    tables: list[dict[str, object]] = []
    for table_name in table_names:
        quoted_table = _quote_identifier(table_name)
        table_info = connection.execute(f"PRAGMA table_info({quoted_table})").fetchall()
        index_list = connection.execute(f"PRAGMA index_list({quoted_table})").fetchall()
        indexes = []
        for index_row in sorted(index_list, key=lambda row: str(row[1])):
            index_name = str(index_row[1])
            index_info = connection.execute(
                f"PRAGMA index_info({_quote_identifier(index_name)})"
            ).fetchall()
            indexes.append(
                {
                    "index_list": _logical_row(index_row),
                    "index_info": [_logical_row(row) for row in index_info],
                }
            )
        foreign_keys = connection.execute(f"PRAGMA foreign_key_list({quoted_table})").fetchall()
        rows = [
            _logical_row(row)
            for row in connection.execute(f"SELECT * FROM {quoted_table}").fetchall()
        ]
        rows.sort(key=_canonical_json_bytes)
        tables.append(
            {
                "name": table_name,
                "table_info": [_logical_row(row) for row in table_info],
                "indexes": indexes,
                "foreign_keys": [_logical_row(row) for row in foreign_keys],
                "rows": rows,
            }
        )
    return _canonical_json_bytes(
        {
            "user_version": _user_version(connection),
            "sqlite_schema": [_logical_row(row) for row in schema_rows],
            "tables": tables,
        }
    )


def _snapshot_path(db_path: Path) -> bytes:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return _logical_snapshot(connection)
    finally:
        connection.close()


def _schema_object_names(connection: sqlite3.Connection, kind: str) -> frozenset[str]:
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_schema
        WHERE type = ? AND substr(name, 1, 7) != 'sqlite_'
        ORDER BY name
        """,
        (kind,),
    ).fetchall()
    return frozenset(str(row[0]) for row in rows)


def _assert_exact_version_schema(connection: sqlite3.Connection, version: int) -> None:
    assert _user_version(connection) == version
    assert _schema_object_names(connection, "table") == EXPECTED_TABLES[version]
    assert _schema_object_names(connection, "trigger") == EXPECTED_TRIGGERS[version]
    assert _schema_object_names(connection, "index") == frozenset()
    assert _schema_object_names(connection, "view") == frozenset()


def _assert_integrity(connection: sqlite3.Connection) -> None:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()
    assert integrity is not None and tuple(integrity) == ("ok",)
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def _assert_trace_has_owned_transaction(trace: list[str], target_version: int) -> None:
    normalized = [_normalized_sql(statement) for statement in trace]
    begin_index = normalized.index("BEGIN IMMEDIATE")
    commit_index = normalized.index("COMMIT")
    schema_indices = [
        index for index, statement in enumerate(normalized) if _is_schema_mutation(statement)
    ]
    version_write_index = normalized.index(f"PRAGMA USER_VERSION = {target_version}")
    locked_version_reads = [
        index
        for index, statement in enumerate(normalized)
        if statement == "PRAGMA USER_VERSION" and begin_index < index < version_write_index
    ]
    assert schema_indices
    assert begin_index < min(schema_indices)
    assert max(schema_indices) < version_write_index < commit_index
    assert locked_version_reads
    assert not any(_is_schema_mutation(statement) for statement in normalized[: begin_index + 1])


@pytest.mark.parametrize(("source_version", "target_version"), MIGRATION_EDGES)
def test_each_edge_success_matches_exact_reference_after_reopen(
    tmp_path: Path,
    source_version: int,
    target_version: int,
) -> None:
    db_path = tmp_path / f"v{source_version}-to-v{target_version}.sqlite3"
    reference_path = tmp_path / f"reference-v{target_version}.sqlite3"
    _build_legacy_database(db_path, source_version)
    _clone_database(db_path, reference_path)
    _apply_edge_without_runner_at_path(reference_path, source_version, target_version)

    trace: list[str] = []
    with _open_store(db_path) as (store, connection):
        connection.set_trace_callback(trace.append)
        store._migrate_one_step(connection, source_version, target_version)
        connection.set_trace_callback(None)
        assert not connection.in_transaction

    assert _snapshot_path(db_path) == _snapshot_path(reference_path)
    with _open_store(db_path) as (_, reopened):
        _assert_exact_version_schema(reopened, target_version)
        _assert_integrity(reopened)
    _assert_trace_has_owned_transaction(trace, target_version)


@pytest.mark.parametrize(("source_version", "target_version"), MIGRATION_EDGES)
@pytest.mark.parametrize("case", FAULT_CASES, ids=lambda case: case.name)
def test_each_edge_fault_rolls_back_exact_snapshot_and_retries(
    tmp_path: Path,
    source_version: int,
    target_version: int,
    case: FaultCase,
) -> None:
    db_path = tmp_path / f"fault-v{source_version}-to-v{target_version}.sqlite3"
    reference_path = tmp_path / f"reference-v{target_version}.sqlite3"
    _build_legacy_database(db_path, source_version)
    opening_snapshot = _snapshot_path(db_path)
    _clone_database(db_path, reference_path)
    _apply_edge_without_runner_at_path(reference_path, source_version, target_version)
    fault = InjectedMigrationError(
        f"injected {case.name} during v{source_version}-to-v{target_version}"
    )

    with _open_store(db_path, connection_factory=FaultConnection) as (store, raw_connection):
        connection = cast(FaultConnection, raw_connection)
        connection.arm(
            source_version=source_version,
            target_version=target_version,
            case=case,
            schema_statement_count=SCHEMA_STATEMENT_COUNTS[target_version],
            fault=fault,
        )
        with pytest.raises(InjectedMigrationError) as raised:
            store._migrate_one_step(connection, source_version, target_version)
        assert raised.value is fault
        assert not connection.in_transaction

    assert _snapshot_path(db_path) == opening_snapshot
    with _open_store(db_path) as (store, retry_connection):
        _assert_exact_version_schema(retry_connection, source_version)
        store._migrate_one_step(retry_connection, source_version, target_version)

    assert _snapshot_path(db_path) == _snapshot_path(reference_path)


@pytest.mark.parametrize(("source_version", "target_version"), MIGRATION_EDGES)
def test_edge_mutators_neither_commit_nor_advance_user_version(
    tmp_path: Path,
    source_version: int,
    target_version: int,
) -> None:
    db_path = tmp_path / f"direct-v{source_version}-to-v{target_version}.sqlite3"
    _build_legacy_database(db_path, source_version)
    opening_snapshot = _snapshot_path(db_path)

    with _open_store(db_path) as (store, connection):
        connection.execute("BEGIN IMMEDIATE")
        migration = _migration_method(store, target_version)
        assert callable(migration)
        migration(connection)
        assert connection.in_transaction
        assert _user_version(connection) == source_version
        connection.rollback()

    assert _snapshot_path(db_path) == opening_snapshot


@pytest.mark.parametrize("failed_source_version", [1, 2, 3, 4])
def test_full_chain_failure_stops_at_last_commit_and_retry_reaches_v5(
    tmp_path: Path,
    failed_source_version: int,
) -> None:
    db_path = tmp_path / f"full-chain-fail-v{failed_source_version}.sqlite3"
    expected_terminal = tmp_path / f"expected-v{failed_source_version}.sqlite3"
    expected_v5 = tmp_path / "expected-v5.sqlite3"
    _build_legacy_database(db_path, 1)
    _clone_database(db_path, expected_terminal)
    _clone_database(db_path, expected_v5)
    for source_version in range(1, failed_source_version):
        _apply_edge_without_runner_at_path(
            expected_terminal,
            source_version,
            source_version + 1,
        )
    for source_version in range(1, 5):
        _apply_edge_without_runner_at_path(expected_v5, source_version, source_version + 1)

    fault = InjectedMigrationError(f"full-chain failure during v{failed_source_version}")
    with _open_store(db_path, connection_factory=FaultConnection) as (store, raw_connection):
        connection = cast(FaultConnection, raw_connection)
        connection.arm(
            source_version=failed_source_version,
            target_version=failed_source_version + 1,
            case=FaultCase("after-first-mutation", "after_statement", "first"),
            schema_statement_count=SCHEMA_STATEMENT_COUNTS[failed_source_version + 1],
            fault=fault,
        )
        with pytest.raises(InjectedMigrationError) as raised:
            _migrate_repair_chain_to_v5(store, connection)
        assert raised.value is fault
        assert not connection.in_transaction

    assert _snapshot_path(db_path) == _snapshot_path(expected_terminal)
    with _open_store(db_path) as (store, retry_connection):
        _migrate_repair_chain_to_v5(store, retry_connection)
        _assert_exact_version_schema(retry_connection, 5)
        assert len(store.list_records()) == 2
    assert _snapshot_path(db_path) == _snapshot_path(expected_v5)

    with ExperimentStore(db_path) as latest_store:
        latest_store.init_schema()
        assert latest_store.schema_version() == SCHEMA_VERSION == 6
        assert len(latest_store.list_records()) == 2


def test_full_chain_success_and_latest_reopen_are_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "full-chain-success.sqlite3"
    _build_legacy_database(db_path, 1)

    with _open_store(db_path) as (store, connection):
        _migrate_repair_chain_to_v5(store, connection)
        _assert_exact_version_schema(connection, 5)
        _assert_integrity(connection)
        assert len(store.list_records()) == 2

    with ExperimentStore(db_path) as store:
        store.init_schema()
        assert store.schema_version() == SCHEMA_VERSION == 6
        assert len(store.list_records()) == 2
    first_latest_snapshot = _snapshot_path(db_path)

    with ExperimentStore(db_path) as reopened:
        reopened.init_schema()
        _assert_exact_version_schema(reopened._connection(), 6)
        _assert_integrity(reopened._connection())
    assert _snapshot_path(db_path) == first_latest_snapshot


def test_active_caller_transaction_is_rejected_without_commit_or_mutation(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "active-transaction.sqlite3"
    _build_legacy_database(db_path, 1)
    opening_snapshot = _snapshot_path(db_path)

    with _open_store(db_path) as (store, connection):
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO experiments (
                candidate_id, policy, observed_value, true_value, cost, created_at, params_json
            ) VALUES ('uncommitted', 'test', 1.0, 1.0, 1.0, 't', '{}')
            """
        )
        assert connection.in_transaction
        with pytest.raises(RuntimeError, match="transaction"):
            store._migrate_one_step(connection, 1, 2)
        assert connection.in_transaction
        uncommitted = connection.execute(
            "SELECT COUNT(*) FROM experiments WHERE candidate_id = 'uncommitted'"
        ).fetchone()
        assert uncommitted is not None and tuple(uncommitted) == (1,)
        assert "hypotheses" not in _schema_object_names(connection, "table")
        connection.rollback()

    assert _snapshot_path(db_path) == opening_snapshot


@pytest.mark.parametrize(
    "exception_type",
    [KeyboardInterrupt, SystemExit, GeneratorExit],
    ids=["keyboard-interrupt", "system-exit", "generator-exit"],
)
def test_baseexception_is_rolled_back_and_reraised_unchanged(
    tmp_path: Path,
    exception_type: type[BaseException],
) -> None:
    db_path = tmp_path / f"baseexception-{exception_type.__name__}.sqlite3"
    _build_legacy_database(db_path, 1)
    opening_snapshot = _snapshot_path(db_path)
    fault = exception_type("injected base exception")

    with _open_store(db_path, connection_factory=FaultConnection) as (store, raw_connection):
        connection = cast(FaultConnection, raw_connection)
        connection.arm(
            source_version=1,
            target_version=2,
            case=FaultCase("after-first-mutation", "after_statement", "first"),
            schema_statement_count=SCHEMA_STATEMENT_COUNTS[2],
            fault=fault,
        )
        with pytest.raises(exception_type) as raised:
            store._migrate_one_step(connection, 1, 2)
        assert raised.value is fault
        assert not connection.in_transaction

    assert _snapshot_path(db_path) == opening_snapshot


@pytest.mark.parametrize(
    "exception_type",
    [KeyboardInterrupt, SystemExit, GeneratorExit],
    ids=["rollback-keyboard-interrupt", "rollback-system-exit", "rollback-generator-exit"],
)
def test_rollback_control_flow_baseexception_is_not_swallowed(
    tmp_path: Path,
    exception_type: type[BaseException],
) -> None:
    db_path = tmp_path / f"rollback-{exception_type.__name__}.sqlite3"
    _build_legacy_database(db_path, 1)
    opening_snapshot = _snapshot_path(db_path)
    migration_fault = InjectedMigrationError("ordinary migration failure")
    rollback_fault = exception_type("rollback control-flow failure")

    with _open_store(db_path, connection_factory=RollbackBaseExceptionConnection) as (
        store,
        raw_connection,
    ):
        connection = cast(RollbackBaseExceptionConnection, raw_connection)
        connection.arm(
            source_version=1,
            target_version=2,
            case=FaultCase("after-first-mutation", "after_statement", "first"),
            schema_statement_count=SCHEMA_STATEMENT_COUNTS[2],
            fault=migration_fault,
        )
        connection.arm_rollback_fault(rollback_fault)
        with pytest.raises(exception_type) as raised:
            store._migrate_one_step(connection, 1, 2)
        assert raised.value is rollback_fault
        assert raised.value.__context__ is migration_fault
        assert not connection.in_transaction

    assert _snapshot_path(db_path) == opening_snapshot


def test_previous_second_v2_create_denial_witness_now_rolls_back(tmp_path: Path) -> None:
    db_path = tmp_path / "previous-v1-v2-witness.sqlite3"
    _build_legacy_database(db_path, 1)
    opening_snapshot = _snapshot_path(db_path)
    create_table_calls = 0

    def deny_second_create(
        action: int,
        _argument_1: str | None,
        _argument_2: str | None,
        _database: str | None,
        _trigger: str | None,
    ) -> int:
        nonlocal create_table_calls
        if action == sqlite3.SQLITE_CREATE_TABLE:
            create_table_calls += 1
            if create_table_calls == 2:
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    with _open_store(db_path) as (store, connection):
        connection.set_authorizer(deny_second_create)
        with pytest.raises(sqlite3.DatabaseError):
            store._migrate_one_step(connection, 1, 2)
        connection.set_authorizer(None)
        assert create_table_calls == 2
        assert not connection.in_transaction

    assert _snapshot_path(db_path) == opening_snapshot
    with _open_store(db_path) as (store, connection):
        assert "hypotheses" not in _schema_object_names(connection, "table")
        assert "evidence" not in _schema_object_names(connection, "table")
        store._migrate_one_step(connection, 1, 2)
        _assert_exact_version_schema(connection, 2)


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
        if normalized.startswith(("CREATE TABLE ", "CREATE TRIGGER ")):
            os._exit(71)
        return cursor


path = Path(sys.argv[1])
connection = sqlite3.connect(path, factory=AbruptConnection)
connection.row_factory = sqlite3.Row
connection.execute("PRAGMA foreign_keys = ON")
store = ExperimentStore(path)
store.connection = connection
store._migrate_one_step(connection, int(sys.argv[2]), int(sys.argv[3]))
raise AssertionError("abrupt migration checkpoint was not reached")
"""


def test_abrupt_child_exit_rolls_back_v1_and_normal_retry_reaches_v6(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "abrupt.sqlite3"
    _build_legacy_database(db_path, 1)
    opening_snapshot = _snapshot_path(db_path)

    completed = subprocess.run(
        [sys.executable, "-B", "-c", _ABRUPT_CHILD, str(db_path), "1", "2"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 71, (completed.stdout, completed.stderr)

    assert _snapshot_path(db_path) == opening_snapshot
    with _open_store(db_path) as (store, connection):
        _assert_exact_version_schema(connection, 1)
        _assert_integrity(connection)
        _migrate_repair_chain_to_v5(store, connection)
        _assert_exact_version_schema(connection, 5)
        assert len(store.list_records()) == 2

    with ExperimentStore(db_path) as latest_store:
        latest_store.init_schema()
        assert latest_store.schema_version() == SCHEMA_VERSION == 6
        assert len(latest_store.list_records()) == 2


def test_abrupt_child_exit_rolls_back_v5_and_normal_retry_reaches_v6(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "abrupt-v5-to-v6.sqlite3"
    _build_legacy_database(db_path, 5)
    opening_snapshot = _snapshot_path(db_path)

    completed = subprocess.run(
        [sys.executable, "-B", "-c", _ABRUPT_CHILD, str(db_path), "5", "6"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 71, (completed.stdout, completed.stderr)

    assert _snapshot_path(db_path) == opening_snapshot
    with _open_store(db_path) as (_, reopened):
        _assert_exact_version_schema(reopened, 5)
        assert "workload_experiments" not in _schema_object_names(reopened, "table")
        _assert_integrity(reopened)

    with ExperimentStore(db_path) as retry_store:
        retry_store.init_schema()
        _assert_exact_version_schema(retry_store._connection(), 6)
        _assert_integrity(retry_store._connection())
        assert len(retry_store.list_records()) == 2


def test_empty_version_zero_database_initializes_and_latest_is_idempotent(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "new.sqlite3"
    with ExperimentStore(db_path) as store:
        assert store.schema_version() == 0
        store.init_schema()
        _assert_exact_version_schema(store._connection(), 6)
    latest_snapshot = _snapshot_path(db_path)

    with ExperimentStore(db_path) as reopened:
        reopened.init_schema()
        _assert_exact_version_schema(reopened._connection(), 6)
    assert _snapshot_path(db_path) == latest_snapshot


@pytest.mark.parametrize("version", [-1, SCHEMA_VERSION + 1], ids=["negative", "future"])
def test_negative_and_future_versions_are_rejected_without_mutation(
    tmp_path: Path,
    version: int,
) -> None:
    db_path = tmp_path / f"unsupported-{version}.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
    connection.execute("INSERT INTO marker VALUES ('preserve-me')")
    connection.execute(f"PRAGMA user_version = {version}")
    connection.commit()
    assert _user_version(connection) == version
    connection.close()
    opening_snapshot = _snapshot_path(db_path)

    with ExperimentStore(db_path) as store, pytest.raises(RuntimeError):
        store.init_schema()
    assert _snapshot_path(db_path) == opening_snapshot


@pytest.mark.parametrize("table_name", ["foreign_data", "sqliteXforeign_data"])
def test_nonempty_unknown_version_zero_database_is_not_recreated(
    tmp_path: Path, table_name: str
) -> None:
    db_path = tmp_path / f"unknown-zero-{table_name}.sqlite3"
    connection = sqlite3.connect(db_path)
    quoted_table = _quote_identifier(table_name)
    connection.execute(f"CREATE TABLE {quoted_table} (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute(f"INSERT INTO {quoted_table} VALUES (1, 'preserve-me')")
    connection.commit()
    assert _user_version(connection) == 0
    connection.close()
    opening_snapshot = _snapshot_path(db_path)

    with ExperimentStore(db_path) as store, pytest.raises(RuntimeError):
        store.init_schema()
    assert _snapshot_path(db_path) == opening_snapshot


@pytest.mark.parametrize(
    ("physical_version", "declared_version"),
    [(1, 2), (2, 1)],
    ids=["version-newer-than-schema", "schema-newer-than-version"],
)
def test_malformed_schema_version_pair_is_rejected_without_mutation(
    tmp_path: Path,
    physical_version: int,
    declared_version: int,
) -> None:
    db_path = tmp_path / f"malformed-v{physical_version}-as-v{declared_version}.sqlite3"
    _build_legacy_database(db_path, physical_version)
    connection = sqlite3.connect(db_path)
    connection.execute(f"PRAGMA user_version = {declared_version}")
    connection.commit()
    connection.close()
    opening_snapshot = _snapshot_path(db_path)

    with ExperimentStore(db_path) as store, pytest.raises(RuntimeError):
        store.init_schema()
    assert _snapshot_path(db_path) == opening_snapshot


@pytest.mark.parametrize(
    ("version", "table_name"),
    [
        (1, "experiments"),
        (2, "hypotheses"),
        (3, "decision_traces"),
        (4, "lookahead_plan_traces"),
        (5, "belief_models"),
    ],
)
def test_noncanonical_declared_schema_is_rejected_without_mutation(
    tmp_path: Path,
    version: int,
    table_name: str,
) -> None:
    db_path = tmp_path / f"noncanonical-v{version}.sqlite3"
    _build_legacy_database(db_path, version, populate=False)
    connection = sqlite3.connect(db_path)
    quoted_table = _quote_identifier(table_name)
    connection.execute(f"DROP TABLE {quoted_table}")
    connection.execute(f"CREATE TABLE {quoted_table} (id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()
    opening_snapshot = _snapshot_path(db_path)

    with ExperimentStore(db_path) as store, pytest.raises(RuntimeError, match="noncanonical"):
        store.init_schema()
    assert _snapshot_path(db_path) == opening_snapshot


def test_noncanonical_trigger_literal_is_rejected_without_mutation(tmp_path: Path) -> None:
    db_path = tmp_path / "noncanonical-trigger-v5.sqlite3"
    _build_legacy_database(db_path, 5, populate=False)
    connection = sqlite3.connect(db_path)
    row = connection.execute(
        """
        SELECT sql FROM sqlite_schema
        WHERE type = 'trigger' AND name = 'calibration_cost_ledger_disjoint'
        """
    ).fetchone()
    assert row is not None
    modified_sql = str(row[0]).replace(
        "source record already belongs", "source  record already belongs", 1
    )
    connection.execute("DROP TRIGGER calibration_cost_ledger_disjoint")
    connection.execute(modified_sql)
    connection.commit()
    connection.close()
    opening_snapshot = _snapshot_path(db_path)

    with ExperimentStore(db_path) as store, pytest.raises(RuntimeError, match="noncanonical"):
        store.init_schema()
    assert _snapshot_path(db_path) == opening_snapshot


def test_migrated_database_exports_and_replays_without_workload_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "migrated-export.sqlite3"
    _build_legacy_database(db_path, 1)
    spec = RunSpec(
        candidates=[
            CandidateSpec("candidate-a", {"work_units": 1}),
            CandidateSpec("candidate-b", {"work_units": 2}),
            CandidateSpec("candidate-c", {"work_units": 3}),
        ],
        policy_id="random",
        policy_config={},
        policy_seed=17,
        experiment_count_budget=2,
        cost_budget=1.0,
        adapter_id="migration-pure-cpu-score",
        adapter_version="1",
        objective_name="score",
        objective_direction="maximize",
        tie_break="candidate-order",
    )
    adapter_calls: list[str] = []

    def evaluate(candidate: CandidateSpec) -> NormalizedObservation:
        adapter_calls.append(candidate.candidate_id)
        work_units = cast(int, candidate.parameters["work_units"])
        return NormalizedObservation(float(work_units * 10), cost=0.25)

    adapter = PythonFunctionAdapter(
        evaluate,
        adapter_id=spec.adapter_id,
        adapter_version=spec.adapter_version,
    )
    with ExperimentStore(db_path) as store:
        store.init_schema()
        trace = run_workload_trace(store, run_spec=spec, adapter=adapter)
        original_history = store.list_workload_experiments(spec.fingerprint())
        assert store.schema_version() == SCHEMA_VERSION == 6
    assert len(original_history) == len(adapter_calls) == 2
    assert all(record.run_spec_fingerprint == spec.fingerprint() for record in original_history)

    bundle_directory = tmp_path / "bundle"
    verification = export_run_bundle(bundle_directory, trace=trace)
    counters = {"python": 0, "command_adapter": 0, "run": 0, "popen": 0}

    def forbidden_python(*_args: object, **_kwargs: object) -> NoReturn:
        counters["python"] += 1
        raise AssertionError("Replay executed PythonFunctionAdapter")

    def forbidden_command_adapter(*_args: object, **_kwargs: object) -> NoReturn:
        counters["command_adapter"] += 1
        raise AssertionError("Replay executed CommandAdapter")

    def forbidden_run(*_args: object, **_kwargs: object) -> NoReturn:
        counters["run"] += 1
        raise AssertionError("Replay executed subprocess.run")

    def forbidden_popen(*_args: object, **_kwargs: object) -> NoReturn:
        counters["popen"] += 1
        raise AssertionError("Replay executed subprocess.Popen")

    monkeypatch.setattr(PythonFunctionAdapter, "evaluate", forbidden_python)
    monkeypatch.setattr(CommandAdapter, "evaluate", forbidden_command_adapter)
    monkeypatch.setattr(subprocess, "run", forbidden_run)
    monkeypatch.setattr(subprocess, "Popen", forbidden_popen)

    replay_directory = tmp_path / "replay"
    replay = replay_run_bundle(bundle_directory, replay_directory)
    assert replay.equivalent is True
    assert replay.bundle_sha256 == verification.bundle_sha256
    assert replay.run_spec_sha256 == spec.fingerprint()
    assert counters == {"python": 0, "command_adapter": 0, "run": 0, "popen": 0}

    with ExperimentStore(replay_directory / "replay.sqlite3") as replay_store:
        replay_history = replay_store.list_workload_experiments(spec.fingerprint())
        _assert_integrity(replay_store._connection())
    assert [record.candidate for record in replay_history] == [
        record.candidate for record in original_history
    ]
    assert [record.observation for record in replay_history] == [
        record.observation for record in original_history
    ]
    assert [record.policy_id for record in replay_history] == [
        record.policy_id for record in original_history
    ]
    assert all(record.run_spec_fingerprint == spec.fingerprint() for record in replay_history)
