"""Deterministic builders and validators for RDE Core v1 canonical fixtures."""

from __future__ import annotations

import hashlib
import json
import random
import re
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from research_decision_engine import (
    CandidateSpec,
    CompletedWorkloadExperiment,
    CompletedWorkloadRunTrace,
    CompletedWorkloadRunTraceV2,
    CompletedWorkloadRunTraceV3,
    FiniteTableEvidenceModel,
    NormalizedObservation,
    PriorGreedyPolicy,
    RunBundleStep,
    RunSpec,
    RunSpecV2,
    RunSpecV3,
    export_run_bundle,
    export_run_bundle_v2,
    export_run_bundle_v3,
)
from research_decision_engine import run_bundle as run_bundle_module
from research_decision_engine import run_bundle_v2 as run_bundle_v2_module
from research_decision_engine import run_bundle_v3 as run_bundle_v3_module
from research_decision_engine.core_contract import (
    build_public_api_manifest,
    canonical_json_bytes,
)
from research_decision_engine.run_bundle_v2 import _run_bundle_step_v2_from_completion
from research_decision_engine.run_bundle_v3 import (
    _run_bundle_step_v3_from_completion,
    _selection_for_v3,
)
from research_decision_engine.storage import ExperimentStore

FIXTURE_DIRECTORY = "core-fixtures-v1"
FIXTURE_MANIFEST_RESOURCE = "fixture-manifest.json"
FIXTURE_MANIFEST_SCHEMA = "rde-core-canonical-fixture-manifest/v1"
FIXTURE_ENTRY_KEYS = frozenset({"path", "semantic_role", "schema", "byte_count", "sha256"})

_FIXED_PRODUCER = {
    "package_name": "research-decision-engine",
    "package_version": "0.1.0",
    "python_implementation": "CPython",
    "python_version": "3.12.0",
}


class CoreFixtureError(ValueError):
    """A packaged Core fixture is missing, malformed, or noncanonical."""


def _canonical_without_lf(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _fixed_producer_payload() -> dict[str, object]:
    return dict(_FIXED_PRODUCER)


@contextmanager
def _fixed_bundle_producers() -> Iterator[None]:
    original_v1 = run_bundle_module._producer_payload
    original_v2 = run_bundle_v2_module._producer_payload
    original_v3 = run_bundle_v3_module._producer_payload
    run_bundle_module._producer_payload = _fixed_producer_payload
    run_bundle_v2_module._producer_payload = _fixed_producer_payload
    run_bundle_v3_module._producer_payload = _fixed_producer_payload
    try:
        yield
    finally:
        run_bundle_module._producer_payload = original_v1
        run_bundle_v2_module._producer_payload = original_v2
        run_bundle_v3_module._producer_payload = original_v3


def _candidates() -> tuple[CandidateSpec, ...]:
    return (
        CandidateSpec("candidate-a", {"group": "alpha", "rank": 1}),
        CandidateSpec("candidate-b", {"group": "beta", "rank": 2}),
        CandidateSpec("candidate-c", {"group": "gamma", "rank": 3}),
    )


def _evidence_model() -> FiniteTableEvidenceModel:
    return FiniteTableEvidenceModel(
        hypothesis_ids=("left", "right"),
        prior_weight_by_hypothesis={"left": 1, "right": 1},
        observation_metric="score",
        outcome_ids=("low", "high"),
        outcome_thresholds=(0.5,),
        likelihood_row_total=10,
        likelihood_weight_by_candidate_id={
            "candidate-a": {
                "left": {"low": 9, "high": 1},
                "right": {"low": 1, "high": 9},
            },
            "candidate-b": {
                "left": {"low": 8, "high": 2},
                "right": {"low": 2, "high": 8},
            },
            "candidate-c": {
                "left": {"low": 5, "high": 5},
                "right": {"low": 5, "high": 5},
            },
        },
    )


def _run_spec_v1() -> RunSpec:
    return RunSpec(
        candidates=_candidates(),
        policy_id="random",
        policy_config={},
        policy_seed=17,
        experiment_count_budget=2,
        cost_budget=2.0,
        adapter_id="fixture-adapter",
        adapter_version="1",
        objective_name="score",
        objective_direction="maximize",
        tie_break="candidate-order",
    )


def _run_spec_v2() -> RunSpecV2:
    return RunSpecV2(
        candidates=_candidates(),
        policy_id="greedy_prior",
        policy_config={
            "utility_by_candidate_id": {
                "candidate-a": 3,
                "candidate-b": 9,
                "candidate-c": 6,
            },
            "tie_break": "runspec_candidate_order",
        },
        policy_seed=None,
        experiment_count_budget=2,
        cost_budget=2.0,
        adapter_id="fixture-adapter",
        adapter_version="1",
        objective_name="score",
        objective_direction="maximize",
    )


def _run_spec_v3() -> RunSpecV3:
    return RunSpecV3(
        candidates=_candidates(),
        policy_id="information_gain_table",
        policy_config={
            "evidence_model": _evidence_model().to_payload(),
            "tie_break": "runspec_candidate_order",
        },
        policy_seed=None,
        experiment_count_budget=2,
        cost_budget=2.0,
        adapter_id="fixture-adapter",
        adapter_version="1",
        objective_name="score",
        objective_direction="maximize",
    )


def _trace_v1(spec: RunSpec) -> CompletedWorkloadRunTrace:
    completed_ids: list[str] = []
    steps: list[RunBundleStep] = []
    cumulative_cost = 0.0
    for index, objective in enumerate((0.2, 0.8)):
        available = [
            candidate
            for candidate in spec.candidates
            if candidate.candidate_id not in completed_ids
        ]
        candidate = random.Random(spec.policy_seed).choice(available)
        available_ids = [item.candidate_id for item in available]
        cumulative_cost += 0.5
        steps.append(
            RunBundleStep(
                step_index=index,
                selected_candidate_id=candidate.candidate_id,
                decision={
                    "policy_config": {},
                    "policy_id": "random",
                    "policy_seed": spec.policy_seed,
                    "selected_candidate_id": candidate.candidate_id,
                },
                rationale={
                    "available_candidate_ids": available_ids,
                    "completed_candidate_ids": list(completed_ids),
                    "selection_rule": "random-choice-over-remaining-candidates/v1",
                },
                observation={
                    "candidate_id": candidate.candidate_id,
                    "objective_value": objective,
                    "cost": 0.5,
                },
                belief_lineage=[],
                cumulative_cost=cumulative_cost,
            )
        )
        completed_ids.append(candidate.candidate_id)
    return CompletedWorkloadRunTrace(
        run_spec=spec,
        steps=steps,
        stop_reason="experiment_budget_exhausted",
    )


def _trace_v2(spec: RunSpecV2) -> CompletedWorkloadRunTraceV2:
    completed_ids: list[str] = []
    steps = []
    cumulative_cost = 0.0
    policy = PriorGreedyPolicy(spec)
    for index, objective in enumerate((0.2, 0.8)):
        candidate = policy.select(set(completed_ids))
        record = CompletedWorkloadExperiment(
            run_spec_fingerprint=spec.fingerprint(),
            candidate=candidate,
            policy_id=spec.policy_id,
            observation=NormalizedObservation(objective, 0.5),
            created_at=f"2000-01-01T00:00:0{index}+00:00",
        )
        step = _run_bundle_step_v2_from_completion(
            run_spec=spec,
            record=record,
            completed_candidate_ids=completed_ids,
            cumulative_cost=cumulative_cost,
        )
        steps.append(step)
        completed_ids.append(candidate.candidate_id)
        cumulative_cost = step.cumulative_cost
    return CompletedWorkloadRunTraceV2(
        run_spec=spec,
        steps=steps,
        stop_reason="experiment_budget_exhausted",
    )


def _trace_v3(spec: RunSpecV3) -> CompletedWorkloadRunTraceV3:
    history: list[CompletedWorkloadExperiment] = []
    steps = []
    cumulative_cost = 0.0
    for index, objective in enumerate((0.2, 0.8)):
        selection = _selection_for_v3(spec, history)
        record = CompletedWorkloadExperiment(
            run_spec_fingerprint=spec.fingerprint(),
            candidate=selection.candidate,
            policy_id=spec.policy_id,
            observation=NormalizedObservation(objective, 0.5),
            created_at=f"2000-01-01T00:00:0{index}+00:00",
        )
        step = _run_bundle_step_v3_from_completion(
            run_spec=spec,
            record=record,
            completed_history=history,
            cumulative_cost=cumulative_cost,
        )
        history.append(record)
        steps.append(step)
        cumulative_cost = step.cumulative_cost
    return CompletedWorkloadRunTraceV3(
        run_spec=spec,
        steps=steps,
        stop_reason="experiment_budget_exhausted",
    )


def _normalize_sql(value: object) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).split()).rstrip(";")


def _logical_sqlite_schema(connection: sqlite3.Connection, version: int) -> bytes:
    objects = []
    rows = connection.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_schema
        WHERE type IN ('table', 'index', 'trigger', 'view')
          AND substr(name, 1, 7) != 'sqlite_'
        ORDER BY type, name, tbl_name
        """
    ).fetchall()
    for object_type, name, table_name, sql in rows:
        entry: dict[str, object] = {
            "type": str(object_type),
            "name": str(name),
            "table_name": str(table_name),
            "sql": _normalize_sql(sql),
        }
        if object_type == "table":
            quoted = '"' + str(name).replace('"', '""') + '"'
            entry["columns"] = [
                {
                    "cid": int(row[0]),
                    "name": str(row[1]),
                    "type": str(row[2]),
                    "not_null": bool(row[3]),
                    "default": row[4],
                    "primary_key": int(row[5]),
                }
                for row in connection.execute(f"PRAGMA table_info({quoted})").fetchall()
            ]
            indexes = []
            for index_row in connection.execute(f"PRAGMA index_list({quoted})").fetchall():
                index_name = str(index_row[1])
                quoted_index = '"' + index_name.replace('"', '""') + '"'
                indexes.append(
                    {
                        "name": index_name,
                        "unique": bool(index_row[2]),
                        "origin": str(index_row[3]),
                        "partial": bool(index_row[4]),
                        "columns": [
                            str(index_info[2])
                            for index_info in connection.execute(
                                f"PRAGMA index_info({quoted_index})"
                            ).fetchall()
                        ],
                    }
                )
            entry["indexes"] = sorted(indexes, key=lambda item: cast(str, item["name"]))
            entry["foreign_keys"] = [
                {
                    "id": int(row[0]),
                    "seq": int(row[1]),
                    "table": str(row[2]),
                    "from": str(row[3]),
                    "to": None if row[4] is None else str(row[4]),
                    "on_update": str(row[5]),
                    "on_delete": str(row[6]),
                    "match": str(row[7]),
                }
                for row in connection.execute(f"PRAGMA foreign_key_list({quoted})").fetchall()
            ]
        objects.append(entry)
    return canonical_json_bytes(
        {
            "schema": f"rde-core-sqlite-logical-schema/v{version}",
            "user_version": version,
            "objects": objects,
        }
    )


def _sqlite_schema_fixtures() -> dict[str, bytes]:
    fixtures: dict[str, bytes] = {}
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    store = ExperimentStore(Path(":memory:"))
    store.connection = connection
    try:
        for source_version in range(0, 6):
            store._migrate_one_step(connection, source_version, source_version + 1)
            fixtures[f"sqlite-schema-v{source_version + 1}.json"] = _logical_sqlite_schema(
                connection, source_version + 1
            )
    finally:
        connection.close()
        store.connection = None
    return fixtures


def _read_bundle_files(root: Path, version: int) -> dict[str, bytes]:
    directory = root / f"v{version}"
    return {
        f"run-bundle-v{version}/{path.name}": path.read_bytes()
        for path in sorted(directory.iterdir(), key=lambda item: item.name)
        if path.is_file()
    }


def build_expected_fixture_files() -> dict[str, bytes]:
    """Generate every semantic fixture except final node IDs and the hash manifest."""

    spec_v1 = _run_spec_v1()
    spec_v2 = _run_spec_v2()
    spec_v3 = _run_spec_v3()
    trace_v1 = _trace_v1(spec_v1)
    trace_v2 = _trace_v2(spec_v2)
    trace_v3 = _trace_v3(spec_v3)
    files: dict[str, bytes] = {
        "public-api-manifest.json": canonical_json_bytes(build_public_api_manifest()),
        "run-spec-v1.json": spec_v1.to_canonical_bytes(),
        "run-spec-v2.json": spec_v2.to_canonical_bytes(),
        "run-spec-v3.json": spec_v3.to_canonical_bytes(),
        "evidence-model-v1.json": canonical_json_bytes(_evidence_model().to_payload()),
        "evidence-model-fingerprint-v1.json": canonical_json_bytes(
            {
                "schema": "rde-core-finite-table-evidence-model-fingerprint/v1",
                "sha256": _evidence_model().fingerprint(),
            }
        ),
        "decisions-rationales-v1.json": canonical_json_bytes(
            {
                "schema": "rde-core-representative-decisions-rationales/v1",
                "v1": [
                    {"decision": dict(step.decision), "rationale": dict(step.rationale)}
                    for step in trace_v1.steps
                ],
                "v2": [
                    {"decision": dict(step.decision), "rationale": dict(step.rationale)}
                    for step in trace_v2.steps
                ],
                "v3": [
                    {"decision": dict(step.decision), "rationale": dict(step.rationale)}
                    for step in trace_v3.steps
                ],
            }
        ),
        "belief-lineage-v3.json": canonical_json_bytes(
            {
                "schema": "rde-core-information-gain-belief-lineage/v1",
                "steps": [
                    [dict(entry) for entry in step.belief_lineage] for step in trace_v3.steps
                ],
            }
        ),
    }
    with TemporaryDirectory(prefix="rde-core-fixture-build-") as temporary:
        root = Path(temporary)
        with _fixed_bundle_producers():
            verification_v1 = export_run_bundle(root / "v1", trace=trace_v1)
            verification_v2 = export_run_bundle_v2(root / "v2", trace=trace_v2)
            verification_v3 = export_run_bundle_v3(root / "v3", trace=trace_v3)
        files.update(_read_bundle_files(root, 1))
        files.update(_read_bundle_files(root, 2))
        files.update(_read_bundle_files(root, 3))
        files["replay-terminal-summaries-v1.json"] = canonical_json_bytes(
            {
                "schema": "rde-core-replay-terminal-summaries/v1",
                "v1": dict(verification_v1.bundle.terminal_summary),
                "v2": dict(verification_v2.bundle.terminal_summary),
                "v3": dict(verification_v3.bundle.terminal_summary),
            }
        )
    files.update(_sqlite_schema_fixtures())
    return dict(sorted(files.items()))


def fixture_semantics(path: str) -> tuple[str, str]:
    """Return the frozen semantic role and schema label for one fixture path."""

    if path == "public-api-manifest.json":
        return "public_api_manifest", "rde-core-public-api-manifest/v1"
    if path.startswith("run-spec-v"):
        version = path.removeprefix("run-spec-v").removesuffix(".json")
        return f"run_spec_v{version}_canonical_bytes", f"rde-core-run-spec/v{version}"
    if path.startswith("run-bundle-v"):
        version = path.split("/", 1)[0].removeprefix("run-bundle-v")
        return f"run_bundle_v{version}_member", f"rde-core-run-bundle/v{version}"
    if path.startswith("sqlite-schema-v"):
        version = path.removeprefix("sqlite-schema-v").removesuffix(".json")
        return f"sqlite_v{version}_logical_schema", f"rde-core-sqlite-logical-schema/v{version}"
    roles = {
        "evidence-model-v1.json": (
            "finite_table_evidence_model",
            "rde-core-finite-table-evidence-model/v1",
        ),
        "evidence-model-fingerprint-v1.json": (
            "evidence_model_fingerprint",
            "rde-core-finite-table-evidence-model-fingerprint/v1",
        ),
        "decisions-rationales-v1.json": (
            "representative_decisions_and_rationales",
            "rde-core-representative-decisions-rationales/v1",
        ),
        "belief-lineage-v3.json": (
            "information_gain_belief_lineage",
            "rde-core-information-gain-belief-lineage/v1",
        ),
        "replay-terminal-summaries-v1.json": (
            "replay_terminal_summaries",
            "rde-core-replay-terminal-summaries/v1",
        ),
        "core-test-nodeids.txt": (
            "cross_platform_core_test_node_stream",
            "rde-core-pytest-node-stream/v1",
        ),
        "core-opening-nodeids.txt": (
            "opening_core_test_node_stream",
            "rde-core-pytest-opening-node-stream/v1",
        ),
    }
    try:
        return roles[path]
    except KeyError as error:
        raise CoreFixtureError(f"Unknown fixture path {path!r}.") from error


def build_fixture_manifest(files: Mapping[str, bytes]) -> dict[str, object]:
    entries = []
    for path, raw in sorted(files.items()):
        semantic_role, schema = fixture_semantics(path)
        entries.append(
            {
                "path": path,
                "semantic_role": semantic_role,
                "schema": schema,
                "byte_count": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return {"schema_version": FIXTURE_MANIFEST_SCHEMA, "fixtures": entries}


def _strict_json(raw: bytes, context: str) -> object:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise CoreFixtureError(f"{context} has a forbidden BOM.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CoreFixtureError(f"{context} is not UTF-8.") from error

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise CoreFixtureError(f"{context} contains duplicate key {key!r}.")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise CoreFixtureError(f"{context} contains nonfinite value {value}.")

    try:
        return json.loads(
            text,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except json.JSONDecodeError as error:
        raise CoreFixtureError(f"{context} is not strict JSON.") from error


def load_fixture_manifest() -> dict[str, object]:
    root = resources.files("research_decision_engine").joinpath(FIXTURE_DIRECTORY)
    raw = root.joinpath(FIXTURE_MANIFEST_RESOURCE).read_bytes()
    value = _strict_json(raw, "fixture manifest")
    if not isinstance(value, dict) or set(value) != {"schema_version", "fixtures"}:
        raise CoreFixtureError("Fixture manifest top-level fields are invalid.")
    if value["schema_version"] != FIXTURE_MANIFEST_SCHEMA:
        raise CoreFixtureError("Fixture manifest schema is unsupported.")
    if raw != canonical_json_bytes(value):
        raise CoreFixtureError("Fixture manifest is not canonical JSON.")
    fixtures = value["fixtures"]
    if not isinstance(fixtures, list):
        raise CoreFixtureError("Fixture manifest entries must be an array.")
    paths: list[str] = []
    for index, entry in enumerate(fixtures):
        if not isinstance(entry, dict) or set(entry) != FIXTURE_ENTRY_KEYS:
            raise CoreFixtureError(f"Fixture entry {index} fields are invalid.")
        path = entry["path"]
        if type(path) is not str or not path or "\\" in path or ".." in path.split("/"):
            raise CoreFixtureError(f"Fixture entry {index} path is invalid.")
        paths.append(path)
        if type(entry["semantic_role"]) is not str or not entry["semantic_role"]:
            raise CoreFixtureError(f"Fixture entry {index} semantic role is invalid.")
        if type(entry["schema"]) is not str or not entry["schema"]:
            raise CoreFixtureError(f"Fixture entry {index} schema is invalid.")
        expected_role, expected_schema = fixture_semantics(path)
        if (entry["semantic_role"], entry["schema"]) != (expected_role, expected_schema):
            raise CoreFixtureError(f"Fixture entry {index} semantics are invalid.")
        if type(entry["byte_count"]) is not int or entry["byte_count"] < 0:
            raise CoreFixtureError(f"Fixture entry {index} byte count is invalid.")
        if type(entry["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise CoreFixtureError(f"Fixture entry {index} digest is invalid.")
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise CoreFixtureError("Fixture paths must be unique and sorted.")
    return cast(dict[str, object], value)


def _assert_fixture_hygiene(path: str, raw: bytes) -> None:
    if b"\r" in raw or raw.startswith(b"\xef\xbb\xbf"):
        raise CoreFixtureError(f"Fixture {path} contains CR or BOM bytes.")
    text = raw.decode("utf-8")
    forbidden_patterns = (
        r"[A-Za-z]:[\\/]",
        r"/(?:home|Users|tmp)/",
        r"(?:hostname|process_id|pid|current_time)\s*[=:]",
    )
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in forbidden_patterns):
        raise CoreFixtureError(f"Fixture {path} contains an environment-bearing value.")


def _resource_file_paths(root: Traversable, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for child in root.iterdir():
        relative = f"{prefix}/{child.name}" if prefix else child.name
        if child.is_file():
            paths.add(relative)
        elif child.is_dir():
            paths.update(_resource_file_paths(child, relative))
    return paths


def verify_packaged_fixtures() -> dict[str, object]:
    """Verify hashes, hygiene, canonical generators, bundles, and schema fixtures."""

    manifest = load_fixture_manifest()
    root = resources.files("research_decision_engine").joinpath(FIXTURE_DIRECTORY)
    entries = cast(list[dict[str, object]], manifest["fixtures"])
    packaged: dict[str, bytes] = {}
    for entry in entries:
        path = cast(str, entry["path"])
        raw = root.joinpath(*path.split("/")).read_bytes()
        _assert_fixture_hygiene(path, raw)
        if len(raw) != entry["byte_count"]:
            raise CoreFixtureError(f"Fixture {path} byte count differs from its manifest.")
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise CoreFixtureError(f"Fixture {path} digest differs from its manifest.")
        packaged[path] = raw
    expected = build_expected_fixture_files()
    expected_paths = set(expected) | {
        "core-opening-nodeids.txt",
        "core-test-nodeids.txt",
    }
    if set(packaged) != expected_paths:
        raise CoreFixtureError("Packaged fixture membership is not exact.")
    if _resource_file_paths(root) != expected_paths | {FIXTURE_MANIFEST_RESOURCE}:
        raise CoreFixtureError("Physical packaged fixture membership is not exact.")
    for path, raw in expected.items():
        if packaged.get(path) != raw:
            raise CoreFixtureError(f"Fixture {path} differs from deterministic generation.")
    return manifest
