from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from research_decision_engine.decision import InformationGainPolicy, expected_information_gain
from research_decision_engine.evidence_eligibility import (
    OptimizerEvidenceEligibilityContract,
    default_public_design,
)
from research_decision_engine.lookahead import (
    LOOKAHEAD_INFORMATION_GAIN_POLICY,
    TIE_BREAKING_ORDER,
    LookaheadInformationGainPolicy,
    LookaheadPlanTrace,
)
from research_decision_engine.optimizer_effect import optimizer_effect_hypotheses
from research_decision_engine.reasoning import BeliefState, initial_belief_state
from research_decision_engine.runner import (
    run_next,
    suggest_lookahead_information_gain,
)
from research_decision_engine.storage import ExperimentStore
from research_decision_engine.types import Candidate, CompletedExperiment
from research_decision_engine.world import DeterministicSyntheticWorld

CREATED_AT = "2026-01-01T00:00:00+00:00"


def test_zero_information_opener_beats_one_step_failure() -> None:
    candidates, contract, costs = _delayed_candidates()
    hypotheses = optimizer_effect_hypotheses()
    belief = initial_belief_state(hypotheses, created_at=CREATED_AT)

    one_step = InformationGainPolicy().decide(
        candidates=list(candidates),
        completed_experiments=[],
        hypotheses=hypotheses,
        belief_state=belief,
        cost=lambda candidate: costs[candidate.candidate_id],
        max_cost=2.0,
        created_at=CREATED_AT,
        eligibility=contract,
    )
    lookahead = _decide(
        candidates=candidates,
        contract=contract,
        costs=costs,
        belief_state=belief,
        max_cost=2.0,
    )

    assert one_step.candidate.candidate_id == "aaa-decoy"
    assert one_step.selected.expected_information_gain == 0.0
    assert lookahead.policy == LOOKAHEAD_INFORMATION_GAIN_POLICY
    assert lookahead.candidate.candidate_id in {"useful-adam", "useful-sgd"}
    assert lookahead.selected.action_effect == "opens_pair"
    assert lookahead.selected.immediate_information_gain == 0.0
    assert lookahead.selected.expected_total_information_gain > 0.0
    assert lookahead.selected.branches[0].label == "NO_EVIDENCE_YET"
    assert lookahead.selected.branches[0].second_action.candidate_id in {
        "useful-adam",
        "useful-sgd",
    }
    assert (
        lookahead.selected.branches[0].second_action.candidate_id
        != lookahead.candidate.candidate_id
    )


def test_one_step_information_gain_numerics_remain_unchanged() -> None:
    hypotheses = optimizer_effect_hypotheses()
    belief = initial_belief_state(hypotheses, created_at=CREATED_AT)

    estimate = expected_information_gain(hypotheses, belief)

    assert estimate.expected_information_gain == 0.8917191217793092
    assert estimate.expected_posterior_entropy == 0.6932433789418468
    assert estimate.outcome_bin_count == 82


def test_planning_is_deterministic_and_every_branch_obeys_budget() -> None:
    candidates, contract, costs = _delayed_candidates()

    left = _decide(candidates=candidates, contract=contract, costs=costs, max_cost=2.0)
    right = _decide(candidates=candidates, contract=contract, costs=costs, max_cost=2.0)

    assert left == right
    assert all(item.budget_feasible for item in left.selected.branches)
    assert all(item.branch_total_cost <= 2.0 for item in left.selected.branches)
    assert sum(item.probability for item in left.selected.branches) == pytest.approx(1.0)
    expected_delayed = sum(
        item.probability * item.second_action.expected_information_gain
        for item in left.selected.branches
    )
    assert left.selected.expected_total_information_gain == pytest.approx(
        left.selected.immediate_information_gain + expected_delayed
    )


def test_second_actions_can_differ_across_evidence_branches() -> None:
    world = DeterministicSyntheticWorld()
    candidates = world.candidates()
    hypotheses = optimizer_effect_hypotheses()
    initial = initial_belief_state(hypotheses, created_at=CREATED_AT)
    sparse_posterior = tuple(
        0.0 if hypothesis_id == "optimizer.no-consistent-advantage" else 0.5
        for hypothesis_id in initial.hypothesis_ids
    )
    belief = BeliefState(
        belief_state_id="belief-sparse",
        hypothesis_ids=initial.hypothesis_ids,
        prior_probabilities=initial.prior_probabilities,
        posterior_probabilities=sparse_posterior,
        evidence_ids=("evidence-sparse",),
        sequence=1,
        created_at=CREATED_AT,
        parent_belief_state_id=initial.belief_state_id,
    )
    completed = [
        _completed(1, candidates[0]),
        _completed(2, candidates[6]),
    ]
    trace = LookaheadInformationGainPolicy().decide(
        candidates=candidates,
        completed_experiments=completed,
        hypotheses=hypotheses,
        belief_state=belief,
        eligibility=OptimizerEvidenceEligibilityContract.from_candidates(candidates),
        cost=world.cost,
        max_cost=2.4,
        created_at=CREATED_AT,
    )

    second_ids = {item.second_action.candidate_id for item in trace.selected.branches}
    assert trace.selected.action_effect == "completes_pair"
    assert len(trace.selected.branches) == 82
    assert second_ids == {"STOP", "cand-007"}


def test_tie_breaking_prefers_total_information_then_cost_then_id() -> None:
    expensive_adam = _candidate("a-expensive-adam", 0.001, "adam")
    expensive_sgd = _candidate("b-expensive-sgd", 0.001, "sgd")
    cheap_adam = _candidate("z-cheap-adam", 0.01, "adam")
    cheap_sgd = _candidate("zz-cheap-sgd", 0.01, "sgd")
    candidates = (expensive_adam, expensive_sgd, cheap_adam, cheap_sgd)
    costs = {
        expensive_adam.candidate_id: 1.25,
        expensive_sgd.candidate_id: 1.25,
        cheap_adam.candidate_id: 1.0,
        cheap_sgd.candidate_id: 1.0,
    }
    contract = OptimizerEvidenceEligibilityContract.from_candidates(candidates)

    trace = _decide(
        candidates=candidates,
        contract=contract,
        costs=costs,
        max_cost=2.5,
    )

    assert trace.candidate.candidate_id == "z-cheap-adam"
    assert trace.tie_breaking_order == TIE_BREAKING_ORDER
    expensive = next(
        item for item in trace.alternatives if item.candidate.candidate_id == "a-expensive-adam"
    )
    cheap_peer = next(
        item for item in trace.alternatives if item.candidate.candidate_id == "zz-cheap-sgd"
    )
    assert "expected total cost is higher" in expensive.ranking_reason
    assert "candidate-ID" in cheap_peer.ranking_reason


def test_planning_persists_only_real_trace_and_round_trips(tmp_path: Path) -> None:
    db_path = tmp_path / "plan.sqlite"

    with ExperimentStore(db_path) as store:
        store.init_schema()
        belief_before = store.current_belief_state()
        assert belief_before is None

        trace = suggest_lookahead_information_gain(store, max_cost=2.2)
        persisted = store.get_lookahead_plan_trace(trace.plan_id)

        assert persisted == trace
        assert store.list_lookahead_plan_traces() == [trace]
        assert store.list_records() == []
        assert store.list_evidence() == []
        assert store.list_belief_updates() == []
        current = store.current_belief_state()
        assert current is not None
        assert current.sequence == 0


def test_run_executes_only_first_action_then_replans_from_real_state(tmp_path: Path) -> None:
    with ExperimentStore(tmp_path / "replan.sqlite") as store:
        store.init_schema()
        first_record = run_next(
            store,
            policy_name=LOOKAHEAD_INFORMATION_GAIN_POLICY,
            seed=0,
            max_cost=2.2,
        )
        first_plan = store.latest_lookahead_plan_trace()
        assert first_plan is not None

        second_plan = suggest_lookahead_information_gain(store, max_cost=1.2)

        assert first_record.candidate.candidate_id == "cand-000"
        assert len(store.list_records()) == 1
        assert store.list_evidence() == []
        assert first_plan.selected.branches[0].second_action.candidate_id == "cand-001"
        assert second_plan.candidate.candidate_id == "cand-001"
        assert second_plan.selected.action_effect == "completes_pair"
        assert second_plan.selected.immediate_information_gain > 0.0
        assert second_plan.completed_state_fingerprint != first_plan.completed_state_fingerprint
        assert len(store.list_lookahead_plan_traces()) == 2


def test_planner_interface_contains_no_hidden_truth_inputs() -> None:
    parameters = set(inspect.signature(LookaheadInformationGainPolicy.decide).parameters)

    assert "true_hypothesis_id" not in parameters
    assert "true_optimizer_effect" not in parameters
    assert "world_config" not in parameters
    assert "hidden_world" not in parameters


def _delayed_candidates() -> tuple[
    tuple[Candidate, ...],
    OptimizerEvidenceEligibilityContract,
    dict[str, float],
]:
    decoy = _candidate("aaa-decoy", 0.03, "sgd")
    useful_sgd = _candidate("useful-sgd", 0.01, "sgd")
    useful_adam = _candidate("useful-adam", 0.01, "adam")
    candidates = (decoy, useful_sgd, useful_adam)
    contract = OptimizerEvidenceEligibilityContract.from_candidates(
        candidates,
        public_designs=(
            default_public_design(decoy, experiment_family="objective-only"),
            default_public_design(useful_sgd),
            default_public_design(useful_adam),
        ),
    )
    return candidates, contract, {"aaa-decoy": 0.5, "useful-sgd": 1.0, "useful-adam": 1.0}


def _decide(
    *,
    candidates: tuple[Candidate, ...],
    contract: OptimizerEvidenceEligibilityContract,
    costs: dict[str, float],
    belief_state: BeliefState | None = None,
    max_cost: float,
) -> LookaheadPlanTrace:
    hypotheses = optimizer_effect_hypotheses()
    belief = belief_state or initial_belief_state(hypotheses, created_at=CREATED_AT)
    return LookaheadInformationGainPolicy().decide(
        candidates=list(candidates),
        completed_experiments=[],
        hypotheses=hypotheses,
        belief_state=belief,
        eligibility=contract,
        cost=lambda candidate: costs[candidate.candidate_id],
        max_cost=max_cost,
        created_at=CREATED_AT,
    )


def _candidate(candidate_id: str, learning_rate: float, optimizer: str) -> Candidate:
    return Candidate(
        candidate_id=candidate_id,
        learning_rate=learning_rate,
        regularization=0.001,
        model_width=32,
        optimizer=optimizer,
    )


def _completed(record_id: int, candidate: Candidate) -> CompletedExperiment:
    return CompletedExperiment(
        record_id=record_id,
        candidate=candidate,
        observed_value=0.5,
        created_at=CREATED_AT,
    )
