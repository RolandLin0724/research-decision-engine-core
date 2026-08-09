from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from research_decision_engine.adapters import PythonFunctionAdapter
from research_decision_engine.information_gain_table import FiniteTableEvidenceModel
from research_decision_engine.run_spec import CandidateSpec, NormalizedObservation
from research_decision_engine.run_spec_v3 import RunSpecV3
from research_decision_engine.runner import (
    resume_workload_trace_v3,
    run_workload_experiment_v3,
)
from research_decision_engine.storage import SCHEMA_VERSION, ExperimentStore


def _candidates() -> list[CandidateSpec]:
    return [CandidateSpec(f"candidate-{index}", {"work_units": index}) for index in range(8)]


def _model(candidates: list[CandidateSpec]) -> FiniteTableEvidenceModel:
    return FiniteTableEvidenceModel(
        hypothesis_ids=("left", "right"),
        prior_weight_by_hypothesis={"left": 1, "right": 1},
        observation_metric="quality",
        outcome_ids=("low", "high"),
        outcome_thresholds=(0.5,),
        likelihood_row_total=10,
        likelihood_weight_by_candidate_id={
            candidate.candidate_id: {
                "left": {"low": 9, "high": 1},
                "right": {"low": 1, "high": 9},
            }
            for candidate in candidates
        },
    )


def _spec(policy_id: str, *, candidates: list[CandidateSpec] | None = None) -> RunSpecV3:
    actual_candidates = _candidates() if candidates is None else candidates
    if policy_id == "random":
        config: dict[str, object] = {}
        seed: int | None = 20260804
    elif policy_id == "greedy_prior":
        config = {
            "utility_by_candidate_id": {
                candidate.candidate_id: index for index, candidate in enumerate(actual_candidates)
            },
            "tie_break": "runspec_candidate_order",
        }
        seed = None
    else:
        config = {
            "evidence_model": _model(actual_candidates).to_payload(),
            "tie_break": "runspec_candidate_order",
        }
        seed = None
    return RunSpecV3(
        candidates=actual_candidates,
        policy_id=policy_id,
        policy_config=config,
        policy_seed=seed,
        experiment_count_budget=8,
        adapter_id="v3-resume-adapter",
        adapter_version="1",
        objective_name="quality",
        objective_direction="maximize",
    )


def _adapter(calls: list[str]) -> PythonFunctionAdapter:
    def evaluate(candidate: CandidateSpec) -> NormalizedObservation:
        calls.append(candidate.candidate_id)
        work_units = candidate.parameters["work_units"]
        assert type(work_units) is int
        return NormalizedObservation(float(work_units % 2), cost=0.25)

    return PythonFunctionAdapter(
        evaluate,
        adapter_id="v3-resume-adapter",
        adapter_version="1",
    )


@pytest.mark.parametrize("policy_id", ["random", "greedy_prior", "information_gain_table"])
def test_v3_resume_reconstructs_four_steps_then_completes(tmp_path: Path, policy_id: str) -> None:
    database = tmp_path / f"{policy_id}.sqlite3"
    run_spec = _spec(policy_id)
    fingerprint = run_spec.fingerprint()
    calls: list[str] = []
    adapter = _adapter(calls)

    with ExperimentStore(database) as store:
        store.init_schema()
        for _ in range(4):
            run_workload_experiment_v3(store, run_spec=run_spec, adapter=adapter)
        prefix = tuple(
            record.candidate.candidate_id for record in store.list_workload_experiments(fingerprint)
        )

    evidence_fingerprint = (
        run_spec.evidence_model.fingerprint() if run_spec.evidence_model is not None else None
    )
    with ExperimentStore(database) as reopened:
        assert reopened.schema_version() == SCHEMA_VERSION == 6
        trace = resume_workload_trace_v3(
            reopened,
            run_spec=run_spec,
            adapter=adapter,
            expected_run_spec_fingerprint=fingerprint,
            expected_evidence_model_fingerprint=evidence_fingerprint,
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
    expected_lineage_count = 1 if policy_id == "information_gain_table" else 0
    assert all(len(step.belief_lineage) == expected_lineage_count for step in trace.steps)
    if policy_id == "greedy_prior":
        assert selected == tuple(f"candidate-{index}" for index in reversed(range(8)))


def test_v3_resume_identity_mismatches_fail_before_adapter_execution(tmp_path: Path) -> None:
    database = tmp_path / "mismatch.sqlite3"
    opening = _spec("information_gain_table")
    fingerprint = opening.fingerprint()
    model = opening.evidence_model
    assert model is not None
    calls: list[str] = []
    adapter = _adapter(calls)
    with ExperimentStore(database) as store:
        store.init_schema()
        for _ in range(4):
            run_workload_experiment_v3(store, run_spec=opening, adapter=adapter)
    call_count = len(calls)

    with ExperimentStore(database) as reopened:
        with pytest.raises(ValueError, match="Evidence-model fingerprint"):
            resume_workload_trace_v3(
                reopened,
                run_spec=opening,
                adapter=adapter,
                expected_run_spec_fingerprint=fingerprint,
                expected_evidence_model_fingerprint="0" * 64,
            )
        changed = _spec("information_gain_table", candidates=list(reversed(_candidates())))
        with pytest.raises(ValueError, match="RunSpec fingerprint"):
            resume_workload_trace_v3(
                reopened,
                run_spec=changed,
                adapter=adapter,
                expected_run_spec_fingerprint=fingerprint,
                expected_evidence_model_fingerprint=model.fingerprint(),
            )

    assert len(calls) == call_count == 4


@pytest.mark.parametrize("field", ["hypothesis_order", "prior", "threshold", "likelihood"])
def test_v3_resume_rejects_each_evidence_model_identity_change_before_adapter(
    field: str,
    tmp_path: Path,
) -> None:
    database = tmp_path / f"{field}.sqlite3"
    opening = _spec("information_gain_table")
    opening_fingerprint = opening.fingerprint()
    opening_model = opening.evidence_model
    assert opening_model is not None
    calls: list[str] = []
    adapter = _adapter(calls)
    with ExperimentStore(database) as store:
        store.init_schema()
        run_workload_experiment_v3(store, run_spec=opening, adapter=adapter)
    call_count = len(calls)

    config = deepcopy(dict(opening.policy_config))
    model_payload = config["evidence_model"]
    assert type(model_payload) is dict
    if field == "hypothesis_order":
        model_payload["hypothesis_ids"] = ["right", "left"]
    elif field == "prior":
        priors = model_payload["prior_weight_by_hypothesis"]
        assert type(priors) is dict
        priors["left"] = 2
    elif field == "threshold":
        model_payload["outcome_thresholds"] = [0.4]
    else:
        likelihoods = model_payload["likelihood_weight_by_candidate_id"]
        assert type(likelihoods) is dict
        candidate = likelihoods["candidate-0"]
        assert type(candidate) is dict
        hypothesis = candidate["left"]
        assert type(hypothesis) is dict
        hypothesis["low"], hypothesis["high"] = 8, 2
    changed = RunSpecV3(
        candidates=opening.candidates,
        policy_id=opening.policy_id,
        policy_config=config,
        policy_seed=opening.policy_seed,
        experiment_count_budget=opening.experiment_count_budget,
        cost_budget=opening.cost_budget,
        adapter_id=opening.adapter_id,
        adapter_version=opening.adapter_version,
        objective_name=opening.objective_name,
        objective_direction=opening.objective_direction,
    )
    assert changed.evidence_model is not None
    assert changed.evidence_model.fingerprint() != opening_model.fingerprint()

    with (
        ExperimentStore(database) as reopened,
        pytest.raises(ValueError, match="RunSpec fingerprint"),
    ):
        resume_workload_trace_v3(
            reopened,
            run_spec=changed,
            adapter=adapter,
            expected_run_spec_fingerprint=opening_fingerprint,
            expected_evidence_model_fingerprint=opening_model.fingerprint(),
        )
    assert len(calls) == call_count == 1
