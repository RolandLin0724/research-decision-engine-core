from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

import research_decision_engine.run_bundle as run_bundle_module
from research_decision_engine import (
    CandidateSpec,
    CompletedWorkloadExperiment,
    CompletedWorkloadRunTrace,
    NormalizedObservation,
    PythonFunctionAdapter,
    RunBundleReplayError,
    RunBundleVerificationResult,
    RunSpec,
    export_run_bundle,
    replay_run_bundle,
    run_workload_trace,
    verify_run_bundle,
)
from research_decision_engine.storage import SCHEMA_VERSION, ExperimentStore


@dataclass(frozen=True, slots=True)
class RecordedBundleFixture:
    run_spec: RunSpec
    completed_run: tuple[CompletedWorkloadExperiment, ...]
    trace: CompletedWorkloadRunTrace
    bundle_directory: Path
    original_database: Path
    verification: RunBundleVerificationResult
    adapter_invocations: list[str]
    bundle_json_bytes: bytes
    sidecar_bytes: bytes


def _canonical_json_bytes(payload: object) -> bytes:
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


def _bundle_bytes(bundle_directory: Path) -> tuple[bytes, bytes]:
    return (
        (bundle_directory / "run-bundle.json").read_bytes(),
        (bundle_directory / "run-bundle.json.sha256").read_bytes(),
    )


def _assert_bundle_unchanged(recorded: RecordedBundleFixture) -> None:
    assert _bundle_bytes(recorded.bundle_directory) == (
        recorded.bundle_json_bytes,
        recorded.sidecar_bytes,
    )


def _expected_step_semantics(
    recorded: RecordedBundleFixture,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    return (
        [dict(step.decision) for step in recorded.trace.steps],
        [dict(step.rationale) for step in recorded.trace.steps],
        [dict(step.observation) for step in recorded.trace.steps],
    )


@pytest.fixture
def recorded_bundle(tmp_path: Path) -> RecordedBundleFixture:
    original_root = tmp_path / "A"
    original_root.mkdir()
    original_database = original_root / "original.sqlite3"
    adapter_invocations: list[str] = []

    run_spec = RunSpec(
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
        adapter_id="pure-cpu-score",
        adapter_version="1",
        objective_name="score",
        objective_direction="maximize",
        tie_break="candidate-order",
    )

    def pure_workload(candidate: CandidateSpec) -> NormalizedObservation:
        assert type(candidate) is CandidateSpec
        assert not hasattr(candidate, "true_value")
        assert set(candidate.parameters) == {"work_units"}
        work_units = candidate.parameters["work_units"]
        assert type(work_units) is int
        adapter_invocations.append(candidate.candidate_id)
        return NormalizedObservation(float(work_units * 10), cost=0.25)

    adapter = PythonFunctionAdapter(
        pure_workload,
        adapter_id=run_spec.adapter_id,
        adapter_version=run_spec.adapter_version,
    )
    with ExperimentStore(original_database) as store:
        store.init_schema()
        trace = run_workload_trace(store, run_spec=run_spec, adapter=adapter)
        completed_run = tuple(store.list_workload_experiments(run_spec.fingerprint()))
        assert store.schema_version() == SCHEMA_VERSION == 6
        assert store.list_workload_experiments(run_spec.fingerprint()) == list(completed_run)
        assert trace.stop_reason == "experiment_budget_exhausted"
        assert len(trace.steps) == len(completed_run) == 2

    with ExperimentStore(original_database) as reopened:
        assert reopened.schema_version() == SCHEMA_VERSION
        assert reopened.list_workload_experiments(run_spec.fingerprint()) == list(completed_run)

    bundle_directory = tmp_path / "portable-run-bundle"
    exported = export_run_bundle(
        bundle_directory,
        trace=trace,
    )
    verification = verify_run_bundle(bundle_directory)
    assert exported.bundle_sha256 == verification.bundle_sha256
    assert exported.run_spec_sha256 == verification.run_spec_sha256
    assert exported.steps_sha256 == verification.steps_sha256
    assert exported.terminal_summary_sha256 == verification.terminal_summary_sha256
    bundle_json_bytes, sidecar_bytes = _bundle_bytes(bundle_directory)

    original_database.unlink()
    assert not original_database.exists()
    del adapter
    del pure_workload

    return RecordedBundleFixture(
        run_spec=run_spec,
        completed_run=completed_run,
        trace=trace,
        bundle_directory=bundle_directory,
        original_database=original_database,
        verification=verification,
        adapter_invocations=adapter_invocations,
        bundle_json_bytes=bundle_json_bytes,
        sidecar_bytes=sidecar_bytes,
    )


def test_empty_directory_replay_is_callable_free_and_canonically_repeatable(
    recorded_bundle: RecordedBundleFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden_adapter_calls: list[str] = []

    def forbidden_evaluate(
        _adapter: PythonFunctionAdapter, candidate: CandidateSpec
    ) -> NormalizedObservation:
        forbidden_adapter_calls.append(candidate.candidate_id)
        raise AssertionError("replay must never execute PythonFunctionAdapter.evaluate")

    monkeypatch.setattr(PythonFunctionAdapter, "evaluate", forbidden_evaluate)
    invocation_count_before_replay = len(recorded_bundle.adapter_invocations)

    replay_root_b = tmp_path / "B"
    replay_root_b.mkdir()
    replay_b = replay_run_bundle(recorded_bundle.bundle_directory, replay_root_b)
    replay_root_c = tmp_path / "C"
    replay_root_c.mkdir()
    replay_c = replay_run_bundle(recorded_bundle.bundle_directory, replay_root_c)

    assert replay_b == replay_c
    assert replay_b.equivalent is True
    assert replay_b.replay_contract == "RECORDED_OBSERVATION_DECISION_REPLAY_V1"
    assert replay_b.sqlite_schema_version == SCHEMA_VERSION == 6
    assert len(recorded_bundle.adapter_invocations) == invocation_count_before_replay
    assert forbidden_adapter_calls == []
    assert not recorded_bundle.original_database.exists()
    _assert_bundle_unchanged(recorded_bundle)

    verification = recorded_bundle.verification
    bundle = verification.bundle
    selected_ids = tuple(record.candidate.candidate_id for record in recorded_bundle.completed_run)
    decisions, rationales, observations = _expected_step_semantics(recorded_bundle)
    assert tuple(step.selected_candidate_id for step in bundle.steps) == selected_ids
    assert [dict(step.decision) for step in bundle.steps] == decisions
    assert [dict(step.rationale) for step in bundle.steps] == rationales
    assert [dict(step.observation) for step in bundle.steps] == observations
    assert [step.belief_lineage for step in bundle.steps] == [(), ()]
    assert [step.cumulative_cost for step in bundle.steps] == [0.25, 0.5]

    expected_terminal_summary = {
        "completed_steps": 2,
        "selected_candidate_ids": list(selected_ids),
        "total_cost": 0.5,
        "stop_reason": "experiment_budget_exhausted",
        "final_belief_fingerprint": None,
        "decision_history_sha256": verification.steps_sha256,
    }
    assert dict(bundle.terminal_summary) == expected_terminal_summary
    assert dict(bundle.section_sha256) == {
        "run_spec": recorded_bundle.run_spec.fingerprint(),
        "steps": verification.steps_sha256,
        "terminal_summary": verification.terminal_summary_sha256,
    }
    document = cast(dict[str, object], json.loads(recorded_bundle.bundle_json_bytes))
    assert hashlib.sha256(_canonical_json_bytes(document["run_spec"])).hexdigest() == (
        verification.run_spec_sha256
    )
    assert hashlib.sha256(_canonical_json_bytes(document["steps"])).hexdigest() == (
        verification.steps_sha256
    )
    assert hashlib.sha256(_canonical_json_bytes(document["terminal_summary"])).hexdigest() == (
        verification.terminal_summary_sha256
    )
    assert replay_b.bundle_sha256 == verification.bundle_sha256
    assert replay_b.run_spec_sha256 == verification.run_spec_sha256
    assert replay_b.steps_sha256 == verification.steps_sha256
    assert replay_b.terminal_summary_sha256 == verification.terminal_summary_sha256
    assert replay_b.selected_candidate_ids == selected_ids

    replay_histories: list[list[CompletedWorkloadExperiment]] = []
    for replay_root in (replay_root_b, replay_root_c):
        replay_database = replay_root / "replay.sqlite3"
        assert replay_database.is_file()
        with ExperimentStore(replay_database) as reopened:
            assert reopened.schema_version() == SCHEMA_VERSION == 6
            history = reopened.list_workload_experiments(recorded_bundle.run_spec.fingerprint())
            integrity = reopened._connection().execute("PRAGMA integrity_check").fetchone()
            columns = {
                str(row[1])
                for row in reopened._connection().execute("PRAGMA table_info(workload_experiments)")
            }
        replay_histories.append(history)
        assert integrity is not None and str(integrity[0]) == "ok"
        assert "true_value" not in columns
        assert [record.candidate.candidate_id for record in history] == list(selected_ids)
        assert [record.observation for record in history] == [
            record.observation for record in recorded_bundle.completed_run
        ]
    assert replay_histories[0] == replay_histories[1]


def test_zero_step_bundle_replays_to_empty_schema_state(tmp_path: Path) -> None:
    run_spec = RunSpec(
        candidates=[CandidateSpec("only", {"work_units": 1})],
        policy_id="random",
        policy_config={},
        policy_seed=3,
        experiment_count_budget=1,
        adapter_id="unused",
        adapter_version="1",
        objective_name="score",
        objective_direction="maximize",
    )
    trace = CompletedWorkloadRunTrace(
        run_spec=run_spec,
        steps=(),
        stop_reason="stopped_by_caller",
    )
    bundle_directory = tmp_path / "zero-step-bundle"
    export_run_bundle(bundle_directory, trace=trace)
    destination = tmp_path / "zero-step-replay"
    destination.mkdir()

    replayed = replay_run_bundle(bundle_directory, destination)

    assert replayed.equivalent is True
    assert replayed.step_count == 0
    assert replayed.selected_candidate_ids == ()
    with ExperimentStore(destination / "replay.sqlite3") as store:
        assert store.schema_version() == SCHEMA_VERSION == 6
        assert store.list_workload_experiments(run_spec.fingerprint()) == []


def test_run_workload_trace_stops_at_cost_budget_and_requires_empty_history(
    tmp_path: Path,
) -> None:
    run_spec = RunSpec(
        candidates=[
            CandidateSpec("one", {"work_units": 1}),
            CandidateSpec("two", {"work_units": 2}),
            CandidateSpec("three", {"work_units": 3}),
        ],
        policy_id="random",
        policy_config={},
        policy_seed=7,
        experiment_count_budget=3,
        cost_budget=0.5,
        adapter_id="fixed-cost",
        adapter_version="1",
        objective_name="score",
        objective_direction="maximize",
    )
    calls = 0

    def fixed_cost(candidate: CandidateSpec) -> NormalizedObservation:
        nonlocal calls
        calls += 1
        return NormalizedObservation(float(calls), cost=0.25)

    adapter = PythonFunctionAdapter(
        fixed_cost,
        adapter_id=run_spec.adapter_id,
        adapter_version=run_spec.adapter_version,
    )
    database = tmp_path / "cost-stop.sqlite3"
    with ExperimentStore(database) as store:
        store.init_schema()
        trace = run_workload_trace(store, run_spec=run_spec, adapter=adapter)
        assert trace.stop_reason == "cost_budget_exhausted"
        assert len(trace.steps) == 2
        assert trace.steps[-1].cumulative_cost == 0.5
        with pytest.raises(RuntimeError, match="requires an empty RunSpec history"):
            run_workload_trace(store, run_spec=run_spec, adapter=adapter)

    assert calls == 2
    bundle_directory = tmp_path / "cost-stop-bundle"
    verification = export_run_bundle(bundle_directory, trace=trace)
    assert verification.bundle.terminal_summary["stop_reason"] == "cost_budget_exhausted"


def test_replay_keyboard_interrupt_removes_owned_database_and_created_root(
    recorded_bundle: RecordedBundleFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "interrupted-replay"

    def interrupt_schema(_store: ExperimentStore) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(ExperimentStore, "init_schema", interrupt_schema)
    with pytest.raises(KeyboardInterrupt):
        replay_run_bundle(recorded_bundle.bundle_directory, destination)

    assert not destination.exists()
    _assert_bundle_unchanged(recorded_bundle)


def test_replay_postpublication_verification_failure_removes_owned_final_state(
    recorded_bundle: RecordedBundleFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "postpublication-replay-failure"
    original_verify = run_bundle_module.verify_run_bundle
    verification_calls = 0

    def fail_final_verification(path: Path) -> RunBundleVerificationResult:
        nonlocal verification_calls
        verification_calls += 1
        if verification_calls == 2:
            raise RuntimeError("injected final verification failure")
        return original_verify(path)

    monkeypatch.setattr(run_bundle_module, "verify_run_bundle", fail_final_verification)
    with pytest.raises(RunBundleReplayError, match="Recorded-observation replay failed"):
        replay_run_bundle(recorded_bundle.bundle_directory, destination)

    assert verification_calls == 2
    assert not destination.exists()
    _assert_bundle_unchanged(recorded_bundle)


def test_replay_recomputes_policy_from_the_complete_truth_free_surface(
    recorded_bundle: RecordedBundleFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_factory = run_bundle_module._SUPPORTED_POLICY_FACTORIES["random"]
    policy_calls: list[tuple[tuple[str, ...], frozenset[str]]] = []

    def inspecting_factory(
        run_spec: RunSpec, completed_candidate_ids: frozenset[str]
    ) -> tuple[CandidateSpec, tuple[str, ...]]:
        assert type(run_spec) is RunSpec
        assert all(type(candidate) is CandidateSpec for candidate in run_spec.candidates)
        assert all(not hasattr(candidate, "true_value") for candidate in run_spec.candidates)
        assert all(set(candidate.parameters) == {"work_units"} for candidate in run_spec.candidates)
        assert b"true_value" not in run_spec.to_canonical_bytes()
        policy_calls.append(
            (
                tuple(candidate.candidate_id for candidate in run_spec.candidates),
                completed_candidate_ids,
            )
        )
        return original_factory(run_spec, completed_candidate_ids)

    monkeypatch.setattr(
        run_bundle_module,
        "_SUPPORTED_POLICY_FACTORIES",
        {"random": inspecting_factory},
    )
    monkeypatch.setattr(
        run_bundle_module,
        "verify_run_bundle",
        lambda _path: recorded_bundle.verification,
    )
    destination = tmp_path / "truth-free-replay"
    destination.mkdir()
    result = replay_run_bundle(recorded_bundle.bundle_directory, destination)

    all_ids = tuple(candidate.candidate_id for candidate in recorded_bundle.run_spec.candidates)
    first_selected = recorded_bundle.completed_run[0].candidate.candidate_id
    assert result.equivalent is True
    assert policy_calls == [
        (all_ids, frozenset()),
        (all_ids, frozenset({first_selected})),
    ]
    _assert_bundle_unchanged(recorded_bundle)


def test_replay_rejects_policy_selection_drift_after_recomputation(
    recorded_bundle: RecordedBundleFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded_first = recorded_bundle.completed_run[0].candidate.candidate_id
    policy_calls = 0

    def divergent_factory(
        run_spec: RunSpec, completed_candidate_ids: frozenset[str]
    ) -> tuple[CandidateSpec, tuple[str, ...]]:
        nonlocal policy_calls
        policy_calls += 1
        available = tuple(
            candidate
            for candidate in run_spec.candidates
            if candidate.candidate_id not in completed_candidate_ids
        )
        selected = next(
            candidate for candidate in available if candidate.candidate_id != recorded_first
        )
        return selected, tuple(candidate.candidate_id for candidate in available)

    monkeypatch.setattr(
        run_bundle_module,
        "_SUPPORTED_POLICY_FACTORIES",
        {"random": divergent_factory},
    )
    monkeypatch.setattr(
        run_bundle_module,
        "verify_run_bundle",
        lambda _path: recorded_bundle.verification,
    )
    destination = tmp_path / "selection-drift"
    destination.mkdir()
    with pytest.raises(RunBundleReplayError, match="Policy selection mismatch at step 0"):
        replay_run_bundle(recorded_bundle.bundle_directory, destination)

    assert policy_calls == 1
    assert list(destination.iterdir()) == []
    _assert_bundle_unchanged(recorded_bundle)


@pytest.mark.parametrize(
    ("helper_name", "expected_message"),
    [
        ("_decision_payload", "Decision payload mismatch at step 0"),
        ("_rationale_payload", "Rationale payload mismatch at step 0"),
    ],
)
def test_replay_rejects_recomputed_decision_or_rationale_drift(
    recorded_bundle: RecordedBundleFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    helper_name: str,
    expected_message: str,
) -> None:
    original_builder: Callable[..., dict[str, object]] = getattr(run_bundle_module, helper_name)

    def drifted_builder(*args: object, **kwargs: object) -> dict[str, object]:
        payload = original_builder(*args, **kwargs)
        if helper_name == "_decision_payload":
            payload["policy_seed"] = cast(int, payload["policy_seed"]) + 1
        else:
            payload["selection_rule"] = "drifted-selection-rule/v1"
        return payload

    monkeypatch.setattr(run_bundle_module, helper_name, drifted_builder)
    destination = tmp_path / f"{helper_name}-drift"
    destination.mkdir()
    with pytest.raises(RunBundleReplayError, match=expected_message):
        replay_run_bundle(recorded_bundle.bundle_directory, destination)

    assert list(destination.iterdir()) == []
    _assert_bundle_unchanged(recorded_bundle)


def test_replay_rejects_persisted_observation_mismatch(
    recorded_bundle: RecordedBundleFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_add = ExperimentStore.add_workload_experiment
    persisted_observations: list[NormalizedObservation] = []

    def persist_mismatched_observation(
        store: ExperimentStore, record: CompletedWorkloadExperiment
    ) -> CompletedWorkloadExperiment:
        mismatched = CompletedWorkloadExperiment(
            run_spec_fingerprint=record.run_spec_fingerprint,
            candidate=record.candidate,
            policy_id=record.policy_id,
            observation=NormalizedObservation(
                record.observation.objective_value + 1.0,
                record.observation.cost,
            ),
            created_at=record.created_at,
        )
        persisted_observations.append(mismatched.observation)
        return original_add(store, mismatched)

    monkeypatch.setattr(
        ExperimentStore,
        "add_workload_experiment",
        persist_mismatched_observation,
    )
    destination = tmp_path / "persistence-drift"
    destination.mkdir()
    with pytest.raises(RunBundleReplayError, match="Persistence mismatch at step 0"):
        replay_run_bundle(recorded_bundle.bundle_directory, destination)

    assert len(persisted_observations) == 1
    assert persisted_observations[0] != recorded_bundle.completed_run[0].observation
    assert list(destination.iterdir()) == []
    _assert_bundle_unchanged(recorded_bundle)


def test_replay_rejects_nonempty_destination_without_touching_it(
    recorded_bundle: RecordedBundleFixture,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "nonempty"
    destination.mkdir()
    marker = destination / "operator-owned.txt"
    marker.write_bytes(b"preserve-me\n")

    with pytest.raises(RunBundleReplayError, match="must be empty"):
        replay_run_bundle(recorded_bundle.bundle_directory, destination)

    assert marker.read_bytes() == b"preserve-me\n"
    assert sorted(path.name for path in destination.iterdir()) == ["operator-owned.txt"]
    _assert_bundle_unchanged(recorded_bundle)


def test_replay_rejects_policy_missing_from_the_finite_static_factory_map(
    recorded_bundle: RecordedBundleFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run_bundle_module, "_SUPPORTED_POLICY_FACTORIES", {})
    monkeypatch.setattr(
        run_bundle_module,
        "verify_run_bundle",
        lambda _path: recorded_bundle.verification,
    )
    destination = tmp_path / "unsupported-policy"
    destination.mkdir()

    with pytest.raises(RunBundleReplayError, match="Unsupported replay policy identity: 'random'"):
        replay_run_bundle(recorded_bundle.bundle_directory, destination)

    assert list(destination.iterdir()) == []
    _assert_bundle_unchanged(recorded_bundle)


def test_replay_never_mutates_a_foreign_final_database_replacement(
    recorded_bundle: RecordedBundleFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "foreign-final-race"
    destination.mkdir()
    foreign_database = tmp_path / "operator.sqlite3"
    with sqlite3.connect(foreign_database) as connection:
        connection.execute("PRAGMA user_version = 91")
        connection.execute("CREATE TABLE operator_sentinel (value TEXT NOT NULL)")
        connection.execute("INSERT INTO operator_sentinel VALUES ('preserve-me')")
    foreign_before = hashlib.sha256(foreign_database.read_bytes()).hexdigest()
    original_require = run_bundle_module._require_directory_identity
    require_calls = 0
    replacement_succeeded = False
    replacement_blocked = False

    def replace_after_publication(
        path: Path,
        *,
        expected_identity: tuple[int, int],
        label: str,
    ) -> None:
        nonlocal require_calls, replacement_succeeded, replacement_blocked
        original_require(
            path,
            expected_identity=expected_identity,
            label=label,
        )
        require_calls += 1
        if require_calls == 3:
            try:
                os.replace(foreign_database, destination / "replay.sqlite3")
            except OSError:
                replacement_blocked = True
            else:
                replacement_succeeded = True

    monkeypatch.setattr(
        run_bundle_module,
        "_require_directory_identity",
        replace_after_publication,
    )
    try:
        result = replay_run_bundle(recorded_bundle.bundle_directory, destination)
    except RunBundleReplayError:
        assert replacement_succeeded is True
        preserved_database = destination / "replay.sqlite3"
    else:
        assert result.equivalent is True
        assert replacement_blocked is True
        preserved_database = foreign_database

    assert replacement_succeeded is not replacement_blocked
    assert hashlib.sha256(preserved_database.read_bytes()).hexdigest() == foreign_before
    with sqlite3.connect(
        f"{preserved_database.as_uri()}?mode=ro&immutable=1", uri=True
    ) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (91,)
        assert connection.execute("SELECT value FROM operator_sentinel").fetchone() == (
            "preserve-me",
        )
        table_count = connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type = 'table'"
        ).fetchone()
        assert table_count == (1,)
    _assert_bundle_unchanged(recorded_bundle)


def test_replay_temp_replacement_cannot_yield_success(
    recorded_bundle: RecordedBundleFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "temporary-cleanup-race"
    destination.mkdir()
    original_remove = run_bundle_module._remove_owned_replay_database
    foreign_bytes = b"operator temporary replacement\n"
    injected_path: Path | None = None

    def leave_foreign_after_reported_removal(
        path: Path, *, expected_identity: tuple[int, int]
    ) -> bool:
        nonlocal injected_path
        if injected_path is None and path.name.startswith(".replay.sqlite3.tmp-"):
            path.unlink()
            path.write_bytes(foreign_bytes)
            injected_path = path
            return True
        return original_remove(path, expected_identity=expected_identity)

    monkeypatch.setattr(
        run_bundle_module,
        "_remove_owned_replay_database",
        leave_foreign_after_reported_removal,
    )
    with pytest.raises(RunBundleReplayError, match="temporary database path remained occupied"):
        replay_run_bundle(recorded_bundle.bundle_directory, destination)

    assert injected_path is not None
    assert injected_path.read_bytes() == foreign_bytes
    assert not (destination / "replay.sqlite3").exists()
    assert sorted(path.name for path in destination.iterdir()) == [injected_path.name]
    _assert_bundle_unchanged(recorded_bundle)
