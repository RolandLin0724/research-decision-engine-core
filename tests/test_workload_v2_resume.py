from __future__ import annotations

from pathlib import Path

import pytest

from research_decision_engine.adapters import PythonFunctionAdapter
from research_decision_engine.run_spec import CandidateSpec, NormalizedObservation
from research_decision_engine.run_spec_v2 import RunSpecV2
from research_decision_engine.runner import (
    resume_workload_trace_v2,
    run_workload_experiment_v2,
)
from research_decision_engine.storage import SCHEMA_VERSION, ExperimentStore


def _candidates() -> list[CandidateSpec]:
    return [CandidateSpec(f"candidate-{index}", {"work_units": index}) for index in range(8)]


def _utilities() -> dict[str, int]:
    return {f"candidate-{index}": index for index in range(8)}


def _spec(
    *,
    policy_id: str = "greedy_prior",
    candidates: list[CandidateSpec] | None = None,
    utilities: dict[str, int] | None = None,
) -> RunSpecV2:
    actual_candidates = _candidates() if candidates is None else candidates
    if policy_id == "random":
        config: dict[str, object] = {}
        seed: int | None = 20260804
    else:
        config = {
            "utility_by_candidate_id": _utilities() if utilities is None else utilities,
            "tie_break": "runspec_candidate_order",
        }
        seed = None
    return RunSpecV2(
        candidates=actual_candidates,
        policy_id=policy_id,
        policy_config=config,
        policy_seed=seed,
        experiment_count_budget=8,
        adapter_id="v2-resume-adapter",
        adapter_version="1",
        objective_name="quality",
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
        adapter_id="v2-resume-adapter",
        adapter_version="1",
    )


def _persist_prefix(
    database: Path,
    *,
    run_spec: RunSpecV2,
    adapter: PythonFunctionAdapter,
) -> tuple[str, ...]:
    with ExperimentStore(database) as store:
        store.init_schema()
        for _ in range(4):
            run_workload_experiment_v2(store, run_spec=run_spec, adapter=adapter)
        return tuple(
            record.candidate.candidate_id
            for record in store.list_workload_experiments(run_spec.fingerprint())
        )


@pytest.mark.parametrize("policy_id", ["random", "greedy_prior"])
def test_v2_resume_reopens_four_steps_and_completes_exact_trace(
    tmp_path: Path, policy_id: str
) -> None:
    database = tmp_path / f"{policy_id}.sqlite3"
    run_spec = _spec(policy_id=policy_id)
    fingerprint = run_spec.fingerprint()
    calls: list[str] = []
    adapter = _adapter(calls)
    prefix = _persist_prefix(database, run_spec=run_spec, adapter=adapter)

    with ExperimentStore(database) as reopened:
        reopened.init_schema()
        assert reopened.schema_version() == SCHEMA_VERSION == 6
        trace = resume_workload_trace_v2(
            reopened,
            run_spec=run_spec,
            adapter=adapter,
            expected_run_spec_fingerprint=fingerprint,
        )
        history = reopened.list_workload_experiments(fingerprint)

    selected = tuple(step.selected_candidate_id for step in trace.steps)
    assert selected[:4] == prefix
    assert selected == tuple(record.candidate.candidate_id for record in history)
    assert tuple(calls) == selected
    assert len(selected) == len(set(selected)) == 8
    assert trace.stop_reason == "experiment_budget_exhausted"
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
    if policy_id == "greedy_prior":
        assert selected == tuple(f"candidate-{index}" for index in reversed(range(8)))


@pytest.mark.parametrize("mismatch", ["utility", "candidate_order", "policy"])
def test_v2_resume_identity_mismatches_fail_before_adapter_execution(
    tmp_path: Path, mismatch: str
) -> None:
    database = tmp_path / f"mismatch-{mismatch}.sqlite3"
    opening = _spec()
    fingerprint = opening.fingerprint()
    calls: list[str] = []
    adapter = _adapter(calls)
    prefix = _persist_prefix(database, run_spec=opening, adapter=adapter)
    call_count = len(calls)

    if mismatch == "utility":
        changed_utilities = _utilities()
        changed_utilities["candidate-0"] = 100
        changed = _spec(utilities=changed_utilities)
    elif mismatch == "candidate_order":
        changed = _spec(candidates=list(reversed(_candidates())))
    else:
        changed = _spec(policy_id="random")

    assert changed.fingerprint() != fingerprint
    with ExperimentStore(database) as reopened:
        reopened.init_schema()
        with pytest.raises(ValueError, match="does not match the expected resume identity"):
            resume_workload_trace_v2(
                reopened,
                run_spec=changed,
                adapter=adapter,
                expected_run_spec_fingerprint=fingerprint,
            )
        persisted = tuple(
            record.candidate.candidate_id
            for record in reopened.list_workload_experiments(fingerprint)
        )

    assert persisted == prefix
    assert len(calls) == call_count == 4
