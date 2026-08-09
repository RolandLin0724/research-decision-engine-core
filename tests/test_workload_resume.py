from __future__ import annotations

from pathlib import Path

import pytest

from research_decision_engine import (
    CandidateSpec,
    NormalizedObservation,
    PythonFunctionAdapter,
    RunSpec,
    run_workload_experiment,
    run_workload_trace,
)
from research_decision_engine.run_bundle import RunBundleValidationError
from research_decision_engine.runner import resume_workload_trace
from research_decision_engine.storage import SCHEMA_VERSION, ExperimentStore


def _run_spec(*, objective_name: str = "resume-score", policy_seed: int = 1729) -> RunSpec:
    return RunSpec(
        candidates=[
            CandidateSpec(f"candidate-{index}", {"work_units": index}) for index in range(8)
        ],
        policy_id="random",
        policy_config={},
        policy_seed=policy_seed,
        experiment_count_budget=8,
        adapter_id="resume-test-adapter",
        adapter_version="1",
        objective_name=objective_name,
        objective_direction="maximize",
    )


def _adapter(calls: list[str]) -> PythonFunctionAdapter:
    def evaluate(candidate: CandidateSpec) -> NormalizedObservation:
        calls.append(candidate.candidate_id)
        work_units = candidate.parameters["work_units"]
        assert type(work_units) is int
        return NormalizedObservation(float(work_units), cost=0.25)

    return PythonFunctionAdapter(
        evaluate,
        adapter_id="resume-test-adapter",
        adapter_version="1",
    )


def _persist_prefix(
    database: Path,
    *,
    run_spec: RunSpec,
    adapter: PythonFunctionAdapter,
) -> tuple[str, ...]:
    with ExperimentStore(database) as store:
        store.init_schema()
        for _ in range(4):
            run_workload_experiment(store, run_spec=run_spec, adapter=adapter)
        return tuple(
            record.candidate.candidate_id
            for record in store.list_workload_experiments(run_spec.fingerprint())
        )


def test_resume_reopens_four_step_prefix_and_completes_exact_eight_step_trace(
    tmp_path: Path,
) -> None:
    database = tmp_path / "resume.sqlite3"
    run_spec = _run_spec()
    fingerprint = run_spec.fingerprint()
    calls: list[str] = []
    adapter = _adapter(calls)

    prefix_ids = _persist_prefix(database, run_spec=run_spec, adapter=adapter)
    assert len(prefix_ids) == len(calls) == 4

    with ExperimentStore(database) as reopened:
        reopened.init_schema()
        assert reopened.schema_version() == SCHEMA_VERSION == 6
        trace = resume_workload_trace(
            reopened,
            run_spec=run_spec,
            adapter=adapter,
            expected_run_spec_fingerprint=fingerprint,
        )
        history = reopened.list_workload_experiments(fingerprint)

    selected_ids = tuple(step.selected_candidate_id for step in trace.steps)
    assert trace.stop_reason == "experiment_budget_exhausted"
    assert len(trace.steps) == len(history) == len(calls) == 8
    assert selected_ids == tuple(record.candidate.candidate_id for record in history)
    assert selected_ids[:4] == prefix_ids
    assert tuple(calls) == selected_ids
    assert [step.step_index for step in trace.steps] == list(range(8))
    assert [step.cumulative_cost for step in trace.steps] == [
        0.25,
        0.5,
        0.75,
        1.0,
        1.25,
        1.5,
        1.75,
        2.0,
    ]
    assert all(step.belief_lineage == () for step in trace.steps)


def test_resume_rejects_mismatched_fingerprint_before_adapter_execution(
    tmp_path: Path,
) -> None:
    database = tmp_path / "mismatch.sqlite3"
    opening_spec = _run_spec()
    opening_fingerprint = opening_spec.fingerprint()
    calls: list[str] = []
    adapter = _adapter(calls)
    prefix_ids = _persist_prefix(database, run_spec=opening_spec, adapter=adapter)
    call_count = len(calls)
    mismatched_spec = _run_spec(objective_name="different-score")

    with ExperimentStore(database) as reopened:
        reopened.init_schema()
        with pytest.raises(ValueError, match="does not match the expected resume identity"):
            resume_workload_trace(
                reopened,
                run_spec=mismatched_spec,
                adapter=adapter,
                expected_run_spec_fingerprint=opening_fingerprint,
            )
        assert (
            tuple(
                record.candidate.candidate_id
                for record in reopened.list_workload_experiments(opening_fingerprint)
            )
            == prefix_ids
        )
        assert reopened.list_workload_experiments(mismatched_spec.fingerprint()) == []

    assert len(calls) == call_count == 4


def test_resume_rejects_empty_or_tampered_prefix_before_adapter_execution(
    tmp_path: Path,
) -> None:
    empty_database = tmp_path / "empty.sqlite3"
    run_spec = _run_spec()
    calls: list[str] = []
    adapter = _adapter(calls)
    with ExperimentStore(empty_database) as empty:
        empty.init_schema()
        with pytest.raises(RuntimeError, match="requires an existing exact RunSpec history"):
            resume_workload_trace(
                empty,
                run_spec=run_spec,
                adapter=adapter,
                expected_run_spec_fingerprint=run_spec.fingerprint(),
            )
    assert calls == []

    tampered_database = tmp_path / "tampered.sqlite3"
    _persist_prefix(tampered_database, run_spec=run_spec, adapter=adapter)
    call_count = len(calls)
    with ExperimentStore(tampered_database) as tampered:
        tampered.init_schema()
        tampered._connection().execute(
            "UPDATE workload_experiments SET policy_id = 'tampered' WHERE id = 1"
        )
        tampered._connection().commit()
        with pytest.raises(
            RunBundleValidationError,
            match="Completed record is inconsistent with its RunSpec",
        ):
            resume_workload_trace(
                tampered,
                run_spec=run_spec,
                adapter=adapter,
                expected_run_spec_fingerprint=run_spec.fingerprint(),
            )
    assert len(calls) == call_count == 4


def test_existing_trace_capture_still_requires_empty_history(tmp_path: Path) -> None:
    database = tmp_path / "existing-semantics.sqlite3"
    run_spec = _run_spec()
    calls: list[str] = []
    adapter = _adapter(calls)
    with ExperimentStore(database) as store:
        store.init_schema()
        run_workload_experiment(store, run_spec=run_spec, adapter=adapter)
        with pytest.raises(RuntimeError, match="requires an empty RunSpec history"):
            run_workload_trace(store, run_spec=run_spec, adapter=adapter)
    assert len(calls) == 1
