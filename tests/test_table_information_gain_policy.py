from __future__ import annotations

import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import pytest

import research_decision_engine.information_gain_table as information_gain_table_module
from research_decision_engine.adapters import PythonFunctionAdapter
from research_decision_engine.command_adapter import CommandAdapter
from research_decision_engine.information_gain_table import (
    FiniteTableEvidenceModel,
    ImpossibleEvidenceError,
    TableInformationGainPolicy,
)
from research_decision_engine.run_spec import (
    CandidateSpec,
    CompletedWorkloadExperiment,
    NormalizedObservation,
)
from research_decision_engine.run_spec_v3 import RunSpecV3


def _spec(*, impossible_high: bool = False) -> RunSpecV3:
    candidates = [
        CandidateSpec("informative-first", {"label": "a"}),
        CandidateSpec("uninformative", {"label": "b"}),
        CandidateSpec("informative-last", {"label": "c"}),
    ]
    informative = (
        {
            "left": {"low": 10, "high": 0},
            "right": {"low": 10, "high": 0},
        }
        if impossible_high
        else {
            "left": {"low": 10, "high": 0},
            "right": {"low": 0, "high": 10},
        }
    )
    impossible = {
        "left": {"low": 10, "high": 0},
        "right": {"low": 10, "high": 0},
    }
    model = {
        "hypothesis_ids": ["left", "right"],
        "prior_weight_by_hypothesis": {"left": 1, "right": 1},
        "observation_metric": "quality",
        "outcome_ids": ["low", "high"],
        "outcome_thresholds": [0.5],
        "likelihood_row_total": 10,
        "likelihood_weight_by_candidate_id": {
            "informative-first": informative,
            "uninformative": impossible
            if impossible_high
            else {
                "left": {"low": 5, "high": 5},
                "right": {"low": 5, "high": 5},
            },
            "informative-last": impossible
            if impossible_high
            else {
                "left": {"low": 10, "high": 0},
                "right": {"low": 0, "high": 10},
            },
        },
    }
    return RunSpecV3(
        candidates=candidates,
        policy_id="information_gain_table",
        policy_config={
            "evidence_model": model,
            "tie_break": "runspec_candidate_order",
        },
        policy_seed=None,
        experiment_count_budget=3,
        adapter_id="never-called",
        adapter_version="1",
        objective_name="quality",
        objective_direction="maximize",
    )


def _completion(
    spec: RunSpecV3,
    candidate_id: str,
    value: float,
) -> CompletedWorkloadExperiment:
    candidate = next(item for item in spec.candidates if item.candidate_id == candidate_id)
    return CompletedWorkloadExperiment(
        run_spec_fingerprint=spec.fingerprint(),
        candidate=candidate,
        policy_id=spec.policy_id,
        observation=NormalizedObservation(value, cost=0.25),
        created_at=datetime.now(UTC).isoformat(),
    )


def test_policy_identity_max_eig_metadata_and_runspec_tie_break_are_exact() -> None:
    spec = _spec()
    policy = TableInformationGainPolicy(spec)
    details = policy.selection_details([])
    metadata = dict(details.selection_metadata())

    assert policy.name == "information_gain_table"
    assert policy.tie_break == "runspec_candidate_order"
    assert policy.semantic_classification == (
        "USER_DECLARED_FINITE_HYPOTHESIS_OUTCOME_LIKELIHOOD_TABLE"
    )
    assert details.candidate.candidate_id == "informative-first"
    assert details.selected_information_gain_bits == "1.000000000000000000000000000000"
    assert metadata == {
        "policy_identity": "information_gain_table",
        "selected_candidate_id": "informative-first",
        "selected_information_gain_bits": "1.000000000000000000000000000000",
        "eligible_candidate_count": 3,
        "current_belief_fingerprint": details.current_belief_fingerprint,
        "evidence_model_fingerprint": policy.evidence_model.fingerprint(),
        "tie_break": "runspec_candidate_order",
    }
    assert len(details.current_belief_fingerprint) == 64


def test_completed_observations_update_exact_belief_and_exclude_candidates() -> None:
    spec = _spec()
    policy = TableInformationGainPolicy(spec)
    first = _completion(spec, "informative-first", 1.0)
    lineage = policy.lineage_for_observation([], first)

    assert lineage.step_index == 0
    assert lineage.candidate_id == "informative-first"
    assert lineage.outcome_id == "high"
    assert lineage.weights_before == (1, 1)
    assert lineage.weights_after == (0, 1)
    assert lineage.belief_fingerprint_before != lineage.belief_fingerprint_after
    assert policy.current_belief([first]) == (
        (0, 1),
        lineage.belief_fingerprint_after,
    )

    second = policy.selection_details([first])
    assert second.candidate.candidate_id == "uninformative"
    assert second.eligible_candidate_ids == ("uninformative", "informative-last")
    assert second.selected_information_gain_bits == "0.000000000000000000000000000000"


def test_policy_never_repeats_and_uses_existing_exhaustion_behavior() -> None:
    spec = _spec()
    policy = TableInformationGainPolicy(spec)
    history: list[CompletedWorkloadExperiment] = []
    values = {"informative-first": 1.0, "uninformative": 0.0, "informative-last": 1.0}
    selected: list[str] = []
    for _ in spec.candidates:
        candidate = policy.select(history)
        selected.append(candidate.candidate_id)
        history.append(_completion(spec, candidate.candidate_id, values[candidate.candidate_id]))

    assert selected == ["informative-first", "uninformative", "informative-last"]
    with pytest.raises(ValueError, match="No available candidates"):
        policy.select(history)


def test_impossible_observation_fails_closed() -> None:
    spec = _spec(impossible_high=True)
    policy = TableInformationGainPolicy(spec)
    record = _completion(spec, "informative-first", 1.0)

    with pytest.raises(ImpossibleEvidenceError):
        policy.lineage_for_observation([], record)


def test_selection_does_not_execute_adapter_and_model_is_mutation_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _spec()
    policy = TableInformationGainPolicy(source)
    original_payload = policy.evidence_model.to_payload()

    def forbidden_evaluate(self: object, candidate: CandidateSpec) -> NormalizedObservation:
        raise AssertionError(f"adapter executed for {candidate.candidate_id}: {self!r}")

    monkeypatch.setattr(PythonFunctionAdapter, "evaluate", forbidden_evaluate)
    monkeypatch.setattr(CommandAdapter, "evaluate", forbidden_evaluate)
    monkeypatch.setattr(subprocess, "run", forbidden_evaluate)
    monkeypatch.setattr(subprocess, "Popen", forbidden_evaluate)
    assert policy.select([]).candidate_id == "informative-first"

    detached = original_payload["likelihood_weight_by_candidate_id"]
    assert type(detached) is dict
    detached["informative-first"]["left"]["low"] = 0
    assert policy.evidence_model.to_payload() != original_payload
    assert policy.evidence_model.likelihood_weight("informative-first", "left", "low") == 10


def test_selection_uses_exact_quantized_order_without_epsilon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = TableInformationGainPolicy(_spec())

    def one_quantum_difference(
        model: FiniteTableEvidenceModel,
        weights: Sequence[int],
        candidate_id: str,
    ) -> Decimal:
        del model, weights
        return (
            Decimal("0.000000000000000000000000000001")
            if candidate_id == "uninformative"
            else Decimal("0E-30")
        )

    monkeypatch.setattr(
        information_gain_table_module,
        "expected_information_gain_bits",
        one_quantum_difference,
    )

    assert policy.select([]).candidate_id == "uninformative"


def test_history_is_exact_ordered_truth_free_completed_projection() -> None:
    spec = _spec()
    policy = TableInformationGainPolicy(spec)
    first = _completion(spec, "informative-first", 1.0)
    wrong_policy = CompletedWorkloadExperiment(
        run_spec_fingerprint=first.run_spec_fingerprint,
        candidate=first.candidate,
        policy_id="random",
        observation=first.observation,
        created_at=first.created_at,
    )

    with pytest.raises(ValueError):
        policy.select([first, first])
    with pytest.raises(ValueError):
        policy.select([wrong_policy])
    assert "true" not in " ".join(policy.evidence_model.to_payload()).lower()
