from __future__ import annotations

from pathlib import Path

import pytest

from research_decision_engine.decision import (
    INFORMATION_GAIN_POLICY,
    DecisionTrace,
    InformationGainPolicy,
    expected_information_gain,
)
from research_decision_engine.optimizer_effect import optimizer_effect_hypotheses
from research_decision_engine.reasoning import BeliefState, initial_belief_state
from research_decision_engine.runner import suggest_information_gain
from research_decision_engine.storage import ExperimentStore
from research_decision_engine.types import Candidate, CompletedExperiment, ExperimentRecord
from research_decision_engine.world import DeterministicSyntheticWorld

CREATED_AT = "2026-01-01T00:00:00+00:00"


def test_information_gain_is_deterministic_and_depends_on_beliefs() -> None:
    hypotheses = optimizer_effect_hypotheses()
    uniform = initial_belief_state(hypotheses, created_at=CREATED_AT)
    certain = _certain_belief_state(uniform)

    left = expected_information_gain(hypotheses, uniform)
    right = expected_information_gain(hypotheses, uniform)
    certain_estimate = expected_information_gain(hypotheses, certain)

    assert left == right
    assert left.expected_information_gain > 0.0
    assert certain_estimate.expected_information_gain == pytest.approx(0.0, abs=1e-15)
    assert left.expected_information_gain != pytest.approx(
        certain_estimate.expected_information_gain
    )


def test_informative_candidate_beats_zero_information_and_duplicates() -> None:
    world = DeterministicSyntheticWorld()
    candidates = world.candidates()
    completed = [_completed(candidates[0], record_id=1)]
    trace = _decide(completed=completed)

    assert trace.policy == INFORMATION_GAIN_POLICY
    assert trace.candidate.candidate_id == "cand-001"
    assert trace.selected.completes_matched_pair is True
    assert trace.selected.matched_experiment_id == 1
    assert trace.selected.expected_information_gain > 0.0
    assert all(item.candidate.candidate_id != "cand-000" for item in trace.ranked_candidates)

    zero_information = next(
        item for item in trace.ranked_candidates if item.candidate.candidate_id == "cand-006"
    )
    assert zero_information.expected_information_gain == 0.0
    assert trace.ranked_candidates.index(zero_information) > 0
    assert len(trace.hypotheses) == 3
    assert {item.hypothesis_id for item in trace.hypotheses} == {
        hypothesis.hypothesis_id for hypothesis in optimizer_effect_hypotheses()
    }


def test_different_beliefs_can_change_the_suggested_experiment() -> None:
    candidates = DeterministicSyntheticWorld().candidates()
    completed = [_completed(candidates[0], record_id=1)]
    hypotheses = optimizer_effect_hypotheses()
    uniform = initial_belief_state(hypotheses, created_at=CREATED_AT)
    certain = _certain_belief_state(uniform)

    uncertain_trace = _decide(completed=completed, belief_state=uniform)
    certain_trace = _decide(completed=completed, belief_state=certain)

    assert uncertain_trace.candidate.candidate_id == "cand-001"
    assert certain_trace.candidate.candidate_id == "cand-006"
    assert certain_trace.fallback_reason is not None
    assert "no positive expected entropy reduction" in certain_trace.fallback_reason


def test_cost_budget_can_make_an_informative_candidate_infeasible() -> None:
    candidates = DeterministicSyntheticWorld().candidates()
    completed = [_completed(candidates[0], record_id=1)]

    trace = _decide(completed=completed, max_cost=1.0)

    assert trace.candidate.candidate_id == "cand-006"
    assert trace.fallback_reason is not None
    assert all(item.estimated_cost <= 1.0 for item in trace.ranked_candidates)
    assert all(item.candidate.candidate_id != "cand-001" for item in trace.ranked_candidates)


def test_completed_matched_pair_cannot_be_suggested_again() -> None:
    world = DeterministicSyntheticWorld()
    candidates = world.candidates()
    completed = [
        _completed(candidates[0], record_id=1),
        _completed(candidates[1], record_id=2),
    ]
    duplicate_design = Candidate(
        candidate_id="duplicate-design",
        learning_rate=candidates[0].learning_rate,
        regularization=candidates[0].regularization,
        model_width=candidates[0].model_width,
        optimizer=candidates[0].optimizer,
    )
    trace = InformationGainPolicy().decide(
        candidates=[*candidates, duplicate_design],
        completed_experiments=completed,
        hypotheses=optimizer_effect_hypotheses(),
        belief_state=initial_belief_state(optimizer_effect_hypotheses(), created_at=CREATED_AT),
        cost=world.cost,
        max_cost=4.8,
        created_at=CREATED_AT,
    )

    ranked_ids = {item.candidate.candidate_id for item in trace.ranked_candidates}
    assert "cand-000" not in ranked_ids
    assert "cand-001" not in ranked_ids
    assert "duplicate-design" not in ranked_ids


def test_decision_trace_is_persisted_and_traceable_to_belief_state(tmp_path: Path) -> None:
    world = DeterministicSyntheticWorld()
    db_path = tmp_path / "decision.sqlite"

    with ExperimentStore(db_path) as store:
        store.init_schema()
        _add_record(store, world.candidates()[0])
        trace = suggest_information_gain(store)
        persisted = store.get_decision_trace(trace.suggestion_id)

        assert persisted == trace
        assert store.latest_decision_trace() == trace
        assert store.list_decision_traces() == [trace]
        assert store.get_belief_state(trace.belief_state_id).belief_state_id == (
            trace.belief_state_id
        )
        assert trace.selected.matched_experiment_id == 1
        assert len(trace.ranked_candidates) >= 3
        assert trace.provenance.details_dict()["belief_state_id"] == trace.belief_state_id


def _decide(
    *,
    completed: list[CompletedExperiment],
    belief_state: BeliefState | None = None,
    max_cost: float = 4.8,
) -> DecisionTrace:
    world = DeterministicSyntheticWorld()
    hypotheses = optimizer_effect_hypotheses()
    state = belief_state or initial_belief_state(hypotheses, created_at=CREATED_AT)
    return InformationGainPolicy().decide(
        candidates=world.candidates(),
        completed_experiments=completed,
        hypotheses=hypotheses,
        belief_state=state,
        cost=world.cost,
        max_cost=max_cost,
        created_at=CREATED_AT,
    )


def _completed(candidate: Candidate, *, record_id: int) -> CompletedExperiment:
    return CompletedExperiment(
        record_id=record_id,
        candidate=candidate,
        observed_value=0.5,
        created_at=CREATED_AT,
    )


def _certain_belief_state(initial: BeliefState) -> BeliefState:
    posterior = tuple(
        1.0 if hypothesis_id == "optimizer.adam-advantage" else 0.0
        for hypothesis_id in initial.hypothesis_ids
    )
    return BeliefState(
        belief_state_id="belief-certain-adam",
        hypothesis_ids=initial.hypothesis_ids,
        prior_probabilities=initial.prior_probabilities,
        posterior_probabilities=posterior,
        evidence_ids=("synthetic-certainty",),
        sequence=1,
        created_at=CREATED_AT,
        parent_belief_state_id=initial.belief_state_id,
    )


def _add_record(store: ExperimentStore, candidate: Candidate) -> ExperimentRecord:
    observed_value, true_value, cost = DeterministicSyntheticWorld().evaluate(candidate)
    return store.add_record(
        ExperimentRecord.new(
            candidate=candidate,
            policy="test",
            observed_value=observed_value,
            true_value=true_value,
            cost=cost,
        )
    )
