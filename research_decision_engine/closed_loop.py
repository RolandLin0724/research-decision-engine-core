"""Truth-free closed-loop integration for the frozen belief-aware policies."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from research_decision_engine.belief_models import (
    CALIBRATED_SIGMA_MODEL_ID,
    FIXED_SIGMA,
    FIXED_SIGMA_MODEL_ID,
    MINIMUM_PRIOR_EFFECTS,
    SIGMA_FLOOR,
    BeliefModelLineage,
    GaussianBeliefModel,
    MatchedEffectObservation,
    ModelAdequacyDiagnostic,
    ModelBeliefUpdate,
    initial_model_lineage,
)
from research_decision_engine.decision import (
    INFORMATION_GAIN_METHOD_VERSION,
    INFORMATION_GAIN_POLICY,
    INFORMATION_GAIN_POLICY_VERSION,
    POSITIVE_INFORMATION_TOLERANCE,
    CandidateScore,
    DecisionTrace,
    EvidenceOutcomeBranch,
    InformationGainEstimate,
    discretized_gaussian_evidence_outcomes,
    expected_information_gain,
)
from research_decision_engine.evidence_eligibility import (
    EligibilityEffect,
    EvidenceEligibilityAssessment,
    OptimizerEvidenceEligibilityContract,
)
from research_decision_engine.lookahead import (
    LOOKAHEAD_INFORMATION_GAIN_POLICY,
    LOOKAHEAD_INFORMATION_GAIN_POLICY_VERSION,
    LOOKAHEAD_UTILITY_VERSION,
    NO_EVIDENCE_BRANCH_ID,
    NO_EVIDENCE_BRANCH_LABEL,
    TIE_BREAKING_ORDER,
    LookaheadAlternative,
    LookaheadBranch,
    LookaheadFirstActionPlan,
    LookaheadInformationGainPolicy,
    LookaheadPlanTrace,
    LookaheadSecondAction,
)
from research_decision_engine.optimizer_effect import (
    evidence_from_matched_pair,
    optimizer_effect_hypotheses,
)
from research_decision_engine.reasoning import (
    BeliefState,
    Evidence,
    GaussianEvidencePrediction,
    Hypothesis,
    Provenance,
    ReasoningError,
)
from research_decision_engine.types import Candidate, CompletedExperiment

CANDIDATE_GROUP_ADAPTER_VERSION = "candidate-group-prediction-adapter/v1"
SELECTED_ONLY_ORACLE_VERSION = "selected-only-common-randomness/v1"
CLOSED_LOOP_ARM_RUNNER_VERSION = "isolated-closed-loop-arm-runner/v1"

type BeliefAwarePolicy = Literal["information_gain", "lookahead_information_gain"]
type PolicyDecision = DecisionTrace | LookaheadPlanTrace


@dataclass(frozen=True, slots=True)
class CandidateGroupPredictionSnapshot:
    """Model-authorized prediction inputs for one public comparison group."""

    snapshot_id: str
    belief_model_id: str
    belief_model_version: str
    lineage_id: str
    belief_state_id: str
    comparison_group_id: str
    estimated_sigma: float
    sigma_status: str
    source_effect_ids: tuple[str, ...]
    hypotheses: tuple[Hypothesis, ...]

    def __post_init__(self) -> None:
        if not math.isfinite(self.estimated_sigma) or self.estimated_sigma <= 0.0:
            raise ReasoningError("Prediction snapshot sigma must be finite and positive.")
        if tuple(item.hypothesis_id for item in self.hypotheses) != tuple(
            sorted(item.hypothesis_id for item in self.hypotheses)
        ):
            raise ReasoningError("Prediction snapshot hypotheses must be in stable order.")
        if len(self.source_effect_ids) != len(set(self.source_effect_ids)):
            raise ReasoningError("Prediction snapshot source effects must be unique.")

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "adapter_version": CANDIDATE_GROUP_ADAPTER_VERSION,
            "belief_model_id": self.belief_model_id,
            "belief_model_version": self.belief_model_version,
            "lineage_id": self.lineage_id,
            "belief_state_id": self.belief_state_id,
            "comparison_group_id": self.comparison_group_id,
            "estimated_sigma": self.estimated_sigma,
            "sigma_status": self.sigma_status,
            "source_effect_ids": list(self.source_effect_ids),
            "hypothesis_predictions": {
                item.hypothesis_id: item.prediction_model.parameters() for item in self.hypotheses
            },
        }


@dataclass(frozen=True, slots=True)
class CandidateGroupPredictionAdapter:
    """Map public candidate structure to immutable model prediction snapshots."""

    belief_model_id: str
    belief_model_version: str
    lineage_id: str
    belief_state_id: str
    evidence_eligibility: OptimizerEvidenceEligibilityContract
    snapshots: tuple[CandidateGroupPredictionSnapshot, ...]
    adapter_version: str = CANDIDATE_GROUP_ADAPTER_VERSION

    def __post_init__(self) -> None:
        group_ids = tuple(item.comparison_group_id for item in self.snapshots)
        if not self.snapshots or group_ids != tuple(sorted(set(group_ids))):
            raise ReasoningError("Prediction snapshots require unique, sorted comparison groups.")
        if any(
            item.belief_model_id != self.belief_model_id
            or item.belief_model_version != self.belief_model_version
            or item.lineage_id != self.lineage_id
            or item.belief_state_id != self.belief_state_id
            for item in self.snapshots
        ):
            raise ReasoningError("Prediction adapter cannot mix model or lineage snapshots.")

    def validate_lineage(self, lineage: BeliefModelLineage) -> None:
        if (
            lineage.belief_model_id != self.belief_model_id
            or lineage.belief_model_version != self.belief_model_version
            or lineage.lineage_id != self.lineage_id
            or lineage.current_state.state.belief_state_id != self.belief_state_id
        ):
            raise ReasoningError("Prediction adapter and belief lineage do not match.")

    def snapshot_for_candidate(
        self, candidate: Candidate
    ) -> CandidateGroupPredictionSnapshot | None:
        design = self.evidence_eligibility.design_for(candidate)
        for snapshot in self.snapshots:
            if snapshot.comparison_group_id == design.comparison_group_id:
                return snapshot
        return None

    def canonical_snapshot(self) -> CandidateGroupPredictionSnapshot:
        return self.snapshots[0]

    def to_dict(self) -> dict[str, object]:
        return {
            "adapter_version": self.adapter_version,
            "belief_model_id": self.belief_model_id,
            "belief_model_version": self.belief_model_version,
            "lineage_id": self.lineage_id,
            "belief_state_id": self.belief_state_id,
            "snapshots": [item.to_dict() for item in self.snapshots],
        }


def build_candidate_group_prediction_adapter(
    *,
    model: GaussianBeliefModel,
    lineage: BeliefModelLineage,
    effect_history: tuple[MatchedEffectObservation, ...],
    evidence_eligibility: OptimizerEvidenceEligibilityContract,
) -> CandidateGroupPredictionAdapter:
    """Freeze group-local sigmas using only effects available before this decision."""

    if (
        model.model_id != lineage.belief_model_id
        or model.model_version != lineage.belief_model_version
    ):
        raise ReasoningError("Prediction adapter cannot use a model from another lineage.")
    state = lineage.current_state.state
    cutoff_sequence = state.sequence + 1
    group_ids = tuple(
        sorted(
            {
                item.comparison_group_id
                for item in evidence_eligibility.designs
                if item.experiment_family == "optimizer-effect"
                and item.intervention_variable == "optimizer"
                and item.intervention_arm in {"adam", "sgd"}
            }
        )
    )
    snapshots: list[CandidateGroupPredictionSnapshot] = []
    for group_id in group_ids:
        eligible = tuple(
            sorted(
                (
                    item
                    for item in effect_history
                    if item.comparison_group_id == group_id
                    and item.available_sequence < cutoff_sequence
                ),
                key=lambda item: (item.available_sequence, item.effect_id),
            )
        )
        if model.model_id == FIXED_SIGMA_MODEL_ID:
            sigma = FIXED_SIGMA
            status = "fixed"
            sources: tuple[MatchedEffectObservation, ...] = ()
        elif model.model_id == CALIBRATED_SIGMA_MODEL_ID:
            sources = eligible
            if len(sources) < MINIMUM_PRIOR_EFFECTS:
                sigma = FIXED_SIGMA
                status = "baseline_fallback"
            else:
                sigma = max(
                    statistics.stdev(item.observed_effect for item in sources),
                    SIGMA_FLOOR,
                )
                status = "calibrated"
        else:
            raise ReasoningError(f"Unsupported closed-loop belief model: {model.model_id}")
        source_ids = tuple(item.effect_id for item in sources)
        snapshot_id = _stable_id(
            "prediction-snapshot",
            {
                "adapter_version": CANDIDATE_GROUP_ADAPTER_VERSION,
                "belief_model_id": model.model_id,
                "belief_state_id": state.belief_state_id,
                "comparison_group_id": group_id,
                "estimated_sigma": sigma,
                "lineage_id": lineage.lineage_id,
                "source_effect_ids": source_ids,
                "status": status,
            },
        )
        snapshots.append(
            CandidateGroupPredictionSnapshot(
                snapshot_id=snapshot_id,
                belief_model_id=model.model_id,
                belief_model_version=model.model_version,
                lineage_id=lineage.lineage_id,
                belief_state_id=state.belief_state_id,
                comparison_group_id=group_id,
                estimated_sigma=sigma,
                sigma_status=status,
                source_effect_ids=source_ids,
                hypotheses=_hypotheses_with_sigma(
                    sigma,
                    prediction_version=f"{model.model_version}/evidence-prediction",
                ),
            )
        )
    return CandidateGroupPredictionAdapter(
        belief_model_id=model.model_id,
        belief_model_version=model.model_version,
        lineage_id=lineage.lineage_id,
        belief_state_id=state.belief_state_id,
        evidence_eligibility=evidence_eligibility,
        snapshots=tuple(snapshots),
    )


def decide_information_gain_with_adapter(
    *,
    adapter: CandidateGroupPredictionAdapter,
    lineage: BeliefModelLineage,
    candidates: Sequence[Candidate],
    completed_experiments: Sequence[CompletedExperiment],
    candidate_costs: Mapping[str, float],
    max_cost: float,
    created_at: str,
) -> DecisionTrace:
    """Apply the unchanged one-step ranking with group-specific prediction inputs."""

    adapter.validate_lineage(lineage)
    if not math.isfinite(max_cost) or max_cost < 0.0:
        raise ValueError("Maximum experiment cost must be finite and non-negative.")
    belief_state = lineage.current_state.state
    estimates = {
        item.comparison_group_id: expected_information_gain(item.hypotheses, belief_state)
        for item in adapter.snapshots
    }
    canonical_estimate = expected_information_gain(
        adapter.canonical_snapshot().hypotheses,
        belief_state,
    )
    completed_ids = {item.candidate.candidate_id for item in completed_experiments}
    scores: list[CandidateScore] = []
    estimate_by_candidate: dict[str, InformationGainEstimate] = {}
    for candidate in sorted(candidates, key=lambda item: item.candidate_id):
        if candidate.candidate_id in completed_ids:
            continue
        candidate_cost = _candidate_cost(candidate, candidate_costs)
        if candidate_cost > max_cost:
            continue
        assessment = adapter.evidence_eligibility.assess_candidate(
            candidate,
            completed_experiments,
        )
        if assessment.effect in {
            "completed_candidate",
            "duplicate_arm",
            "already_completed_pair",
            "ambiguous_counterpart",
        }:
            continue
        snapshot = adapter.snapshot_for_candidate(candidate)
        estimate = (
            canonical_estimate if snapshot is None else estimates[snapshot.comparison_group_id]
        )
        estimate_by_candidate[candidate.candidate_id] = estimate
        if assessment.effect == "completes_pair":
            information_gain = estimate.expected_information_gain
            expected_entropy = estimate.expected_posterior_entropy
            if information_gain > POSITIVE_INFORMATION_TOLERANCE:
                reason = (
                    "Completes a new structurally eligible matched pair with experiment "
                    f"{assessment.counterpart_experiment_id}, "
                    "so the observed optimizer effect can update current beliefs."
                )
            else:
                reason = (
                    "Completes a new structurally eligible matched pair with experiment "
                    f"{assessment.counterpart_experiment_id}, "
                    "but the current belief state has no reducible uncertainty."
                )
            completes_pair = True
            matched_experiment_id = assessment.counterpart_experiment_id
        else:
            information_gain = 0.0
            expected_entropy = estimate.prior_entropy
            reason = assessment.reason
            completes_pair = False
            matched_experiment_id = None
        scores.append(
            CandidateScore(
                candidate=candidate,
                expected_information_gain=information_gain,
                prior_entropy=estimate.prior_entropy,
                expected_posterior_entropy=expected_entropy,
                estimated_cost=candidate_cost,
                completes_matched_pair=completes_pair,
                matched_experiment_id=matched_experiment_id,
                score_reason=reason,
            )
        )
    if not scores:
        raise ValueError("No feasible candidates remain within the experiment cost budget.")

    has_positive = any(
        item.expected_information_gain > POSITIVE_INFORMATION_TOLERANCE for item in scores
    )
    if has_positive:
        ordered = sorted(
            scores,
            key=lambda item: (
                -item.expected_information_gain,
                item.estimated_cost,
                item.candidate.candidate_id,
            ),
        )
        fallback_reason = None
    else:
        ordered = sorted(
            scores, key=lambda item: (item.estimated_cost, item.candidate.candidate_id)
        )
        if all(
            item.expected_information_gain <= POSITIVE_INFORMATION_TOLERANCE
            for item in estimates.values()
        ):
            fallback_reason = (
                "Current beliefs have no positive expected entropy reduction; selected the "
                "lowest-cost feasible candidate."
            )
        else:
            fallback_reason = (
                "No feasible candidate can complete a new matched pair; selected the "
                "lowest-cost feasible candidate."
            )
    ranked = _rank_one_step(ordered, has_positive)
    selected = ranked[0]
    selected_estimate = estimate_by_candidate[selected.candidate.candidate_id]
    rationale = _one_step_rationale(selected, max_cost, fallback_reason)
    suggestion_id = _one_step_suggestion_id(
        belief_state_id=belief_state.belief_state_id,
        max_cost=max_cost,
        ranked=ranked,
        fallback_reason=fallback_reason,
    )
    provenance = Provenance.create(
        method="belief-guided-experiment-selection",
        version=INFORMATION_GAIN_POLICY_VERSION,
        details={
            "belief_state_id": belief_state.belief_state_id,
            "candidate_count_scored": len(ranked),
            "completed_experiment_count": len(completed_experiments),
            "entropy_unit": "bits",
            "information_gain_method": INFORMATION_GAIN_METHOD_VERSION,
            "max_cost": max_cost,
            "outcome_bin_count": selected_estimate.outcome_bin_count,
            "selected_candidate_id": selected.candidate.candidate_id,
        },
    )
    return DecisionTrace(
        suggestion_id=suggestion_id,
        policy=INFORMATION_GAIN_POLICY,
        policy_version=INFORMATION_GAIN_POLICY_VERSION,
        created_at=created_at,
        belief_state_id=belief_state.belief_state_id,
        selected=selected,
        hypotheses=selected_estimate.hypotheses,
        max_cost=max_cost,
        fallback_reason=fallback_reason,
        rationale=rationale,
        ranked_candidates=ranked,
        provenance=provenance,
    )


def _rank_one_step(
    ordered: list[CandidateScore], has_positive_information: bool
) -> tuple[CandidateScore, ...]:
    selected = ordered[0]
    ranked: list[CandidateScore] = []
    for index, score in enumerate(ordered):
        if index == 0:
            reason = (
                "Selected for maximum positive expected information gain."
                if has_positive_information
                else "Selected as the lowest-cost deterministic fallback."
            )
        elif score.expected_information_gain + POSITIVE_INFORMATION_TOLERANCE < (
            selected.expected_information_gain
        ):
            reason = "Lost because it has lower expected information gain."
        elif score.estimated_cost > selected.estimated_cost:
            reason = "Lost on estimated cost after an information-gain tie."
        else:
            reason = "Lost by stable candidate-ID tie-breaking."
        ranked.append(replace(score, ranking_reason=reason))
    return tuple(ranked)


def _one_step_rationale(
    selected: CandidateScore, max_cost: float, fallback_reason: str | None
) -> str:
    if fallback_reason is not None:
        return (
            f"{fallback_reason} Selected {selected.candidate.candidate_id} at estimated cost "
            f"{selected.estimated_cost:.6f} within the {max_cost:.6f} next-experiment budget."
        )
    return (
        f"Selected {selected.candidate.candidate_id} because it completes a matched pair and "
        f"reduces expected hypothesis entropy from {selected.prior_entropy:.12f} to "
        f"{selected.expected_posterior_entropy:.12f} bits, an expected information gain of "
        f"{selected.expected_information_gain:.12f} bits. Estimated cost "
        f"{selected.estimated_cost:.6f} is within the {max_cost:.6f} budget."
    )


def _one_step_suggestion_id(
    *,
    belief_state_id: str,
    max_cost: float,
    ranked: tuple[CandidateScore, ...],
    fallback_reason: str | None,
) -> str:
    return _stable_id(
        "suggestion",
        {
            "belief_state_id": belief_state_id,
            "fallback_reason": fallback_reason,
            "max_cost": max_cost,
            "policy_version": INFORMATION_GAIN_POLICY_VERSION,
            "ranked_candidates": [
                {
                    "candidate_id": item.candidate.candidate_id,
                    "cost": item.estimated_cost,
                    "expected_information_gain": item.expected_information_gain,
                    "matched_experiment_id": item.matched_experiment_id,
                }
                for item in ranked
            ],
        },
    )


def _hypotheses_with_sigma(sigma: float, *, prediction_version: str) -> tuple[Hypothesis, ...]:
    return tuple(
        Hypothesis(
            hypothesis_id=item.hypothesis_id,
            statement=item.statement,
            prior_probability=item.prior_probability,
            prediction_model=GaussianEvidencePrediction(
                mean=item.prediction_model.parameters()["mean"],
                standard_deviation=sigma,
                model_version=prediction_version,
            ),
        )
        for item in sorted(optimizer_effect_hypotheses(), key=lambda value: value.hypothesis_id)
    )


def _candidate_cost(candidate: Candidate, candidate_costs: Mapping[str, float]) -> float:
    try:
        value = candidate_costs[candidate.candidate_id]
    except KeyError as error:
        raise ReasoningError(f"Missing public cost for {candidate.candidate_id}.") from error
    if not math.isfinite(value) or value < 0.0:
        raise ReasoningError(f"Candidate {candidate.candidate_id} has invalid public cost.")
    return value


def _stable_id(prefix: str, payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def decide_lookahead_with_adapter(
    *,
    adapter: CandidateGroupPredictionAdapter,
    lineage: BeliefModelLineage,
    candidates: Sequence[Candidate],
    completed_experiments: Sequence[CompletedExperiment],
    candidate_costs: Mapping[str, float],
    max_cost: float,
    created_at: str,
) -> LookaheadPlanTrace:
    """Apply the frozen two-step recursion with group-specific prediction snapshots."""

    adapter.validate_lineage(lineage)
    if not math.isfinite(max_cost) or max_cost < 0.0:
        raise ValueError("Lookahead budget must be finite and non-negative.")
    belief_state = lineage.current_state.state
    completed = list(completed_experiments)
    candidate_list = list(candidates)
    completed_ids = {item.candidate.candidate_id for item in completed}
    plans: list[LookaheadFirstActionPlan] = []
    for candidate in sorted(candidate_list, key=lambda item: item.candidate_id):
        if candidate.candidate_id in completed_ids:
            continue
        first_cost = _candidate_cost(candidate, candidate_costs)
        if first_cost > max_cost:
            continue
        assessment = adapter.evidence_eligibility.assess_candidate(candidate, completed)
        if assessment.effect in {
            "completed_candidate",
            "duplicate_arm",
            "already_completed_pair",
            "ambiguous_counterpart",
        }:
            continue
        plans.append(
            _plan_first_action_with_adapter(
                adapter=adapter,
                candidate=candidate,
                assessment=assessment,
                candidates=candidate_list,
                completed_experiments=completed,
                belief_state=belief_state,
                candidate_costs=candidate_costs,
                max_cost=max_cost,
            )
        )
    if not plans:
        raise ValueError("No feasible first candidates remain within the lookahead budget.")

    ordered = sorted(plans, key=_first_action_sort_key)
    ranked = _rank_first_actions(ordered)
    selected = ranked[0]
    fallback_reason = None
    if selected.expected_total_information_gain <= POSITIVE_INFORMATION_TOLERANCE:
        fallback_reason = (
            "No feasible two-step plan has positive expected entropy reduction; selected "
            "the lowest-cost feasible first candidate."
        )
    alternatives = tuple(_alternative_from_plan(item) for item in ranked[1:])
    completed_fingerprint = _completed_state_fingerprint(
        completed,
        adapter.evidence_eligibility,
    )
    candidate_fingerprint = _candidate_set_fingerprint(
        candidate_list,
        candidate_costs,
        adapter.evidence_eligibility,
    )
    plan_id = _lookahead_plan_id(
        belief_state_id=belief_state.belief_state_id,
        max_cost=max_cost,
        completed_state_fingerprint=completed_fingerprint,
        candidate_set_fingerprint=candidate_fingerprint,
        ranked=ranked,
    )
    rationale = _lookahead_rationale(selected, max_cost, fallback_reason)
    provenance = Provenance.create(
        method="two-step-receding-horizon-experiment-selection",
        version=LOOKAHEAD_INFORMATION_GAIN_POLICY_VERSION,
        details={
            "belief_state_id": belief_state.belief_state_id,
            "candidate_count_scored": len(ranked),
            "candidate_set_fingerprint": candidate_fingerprint,
            "completed_experiment_count": len(completed),
            "completed_state_fingerprint": completed_fingerprint,
            "entropy_unit": "bits",
            "evidence_eligibility_contract": "matched-optimizer-public-structure/v1",
            "information_gain_method": INFORMATION_GAIN_METHOD_VERSION,
            "lookahead_horizon": 2,
            "max_cost": max_cost,
            "selected_candidate_id": selected.candidate.candidate_id,
            "utility_version": LOOKAHEAD_UTILITY_VERSION,
        },
    )
    return LookaheadPlanTrace(
        plan_id=plan_id,
        policy=LOOKAHEAD_INFORMATION_GAIN_POLICY,
        policy_version=LOOKAHEAD_INFORMATION_GAIN_POLICY_VERSION,
        created_at=created_at,
        belief_state_id=belief_state.belief_state_id,
        current_hypothesis_probabilities=tuple(
            zip(
                belief_state.hypothesis_ids,
                belief_state.posterior_probabilities,
                strict=True,
            )
        ),
        completed_state_fingerprint=completed_fingerprint,
        candidate_set_fingerprint=candidate_fingerprint,
        max_cost=max_cost,
        selected=selected,
        alternatives=alternatives,
        tie_breaking_order=TIE_BREAKING_ORDER,
        fallback_reason=fallback_reason,
        rationale=rationale,
        provenance=provenance,
    )


def _plan_first_action_with_adapter(
    *,
    adapter: CandidateGroupPredictionAdapter,
    candidate: Candidate,
    assessment: EvidenceEligibilityAssessment,
    candidates: list[Candidate],
    completed_experiments: list[CompletedExperiment],
    belief_state: BeliefState,
    candidate_costs: Mapping[str, float],
    max_cost: float,
) -> LookaheadFirstActionPlan:
    first_cost = _candidate_cost(candidate, candidate_costs)
    simulated_first = CompletedExperiment(
        record_id=0,
        candidate=candidate,
        observed_value=0.0,
        created_at="SIMULATED-NOT-PERSISTED",
    )
    simulated_completed = [*completed_experiments, simulated_first]
    if assessment.effect == "completes_pair":
        snapshot = adapter.snapshot_for_candidate(candidate)
        if snapshot is None:
            raise ReasoningError("A matched-pair closer has no prediction snapshot.")
        first_distribution = discretized_gaussian_evidence_outcomes(
            snapshot.hypotheses,
            belief_state.posterior_probabilities,
        )
        immediate_information_gain = first_distribution.expected_information_gain
        outcome_branches = first_distribution.branches
    else:
        immediate_information_gain = 0.0
        outcome_branches = (
            EvidenceOutcomeBranch(
                branch_id=NO_EVIDENCE_BRANCH_ID,
                label=NO_EVIDENCE_BRANCH_LABEL,
                lower_bound=None,
                upper_bound=None,
                predictive_probability=1.0,
                posterior_probabilities=belief_state.posterior_probabilities,
                posterior_entropy=_entropy(belief_state.posterior_probabilities),
            ),
        )
    branches = tuple(
        _plan_branch_with_adapter(
            adapter=adapter,
            outcome=outcome,
            first_cost=first_cost,
            candidates=candidates,
            completed_experiments=simulated_completed,
            candidate_costs=candidate_costs,
            max_cost=max_cost,
        )
        for outcome in outcome_branches
    )
    if any(not item.budget_feasible for item in branches):
        raise ReasoningError("A simulated lookahead branch exceeded the hard budget.")
    expected_terminal_entropy = math.fsum(
        item.probability * item.terminal_entropy for item in branches
    )
    prior_entropy = _entropy(belief_state.posterior_probabilities)
    expected_total_information_gain = prior_entropy - expected_terminal_entropy
    if expected_total_information_gain < -POSITIVE_INFORMATION_TOLERANCE:
        raise ReasoningError("Two-step expected information gain was numerically negative.")
    expected_total_information_gain = max(0.0, expected_total_information_gain)
    expected_total_cost = math.fsum(item.probability * item.branch_total_cost for item in branches)
    return LookaheadFirstActionPlan(
        candidate=candidate,
        public_design=adapter.evidence_eligibility.design_for(candidate),
        action_effect=assessment.effect,
        first_action_cost=first_cost,
        prior_entropy=prior_entropy,
        immediate_information_gain=immediate_information_gain,
        expected_terminal_entropy=expected_terminal_entropy,
        expected_total_information_gain=expected_total_information_gain,
        expected_total_cost=expected_total_cost,
        information_gain_per_expected_cost=_information_per_cost(
            expected_total_information_gain,
            expected_total_cost,
        ),
        branches=branches,
    )


def _plan_branch_with_adapter(
    *,
    adapter: CandidateGroupPredictionAdapter,
    outcome: EvidenceOutcomeBranch,
    first_cost: float,
    candidates: list[Candidate],
    completed_experiments: list[CompletedExperiment],
    candidate_costs: Mapping[str, float],
    max_cost: float,
) -> LookaheadBranch:
    second = _best_second_action_with_adapter(
        adapter=adapter,
        candidates=candidates,
        completed_experiments=completed_experiments,
        posterior_probabilities=outcome.posterior_probabilities,
        candidate_costs=candidate_costs,
        remaining_budget=max_cost - first_cost,
    )
    terminal_entropy = max(0.0, outcome.posterior_entropy - second.expected_information_gain)
    branch_total_cost = first_cost + second.estimated_cost
    return LookaheadBranch(
        branch_id=outcome.branch_id,
        label=outcome.label,
        probability=outcome.predictive_probability,
        evidence_lower_bound=outcome.lower_bound,
        evidence_upper_bound=outcome.upper_bound,
        posterior_probabilities=tuple(
            zip(
                tuple(item.hypothesis_id for item in adapter.canonical_snapshot().hypotheses),
                outcome.posterior_probabilities,
                strict=True,
            )
        ),
        posterior_entropy=outcome.posterior_entropy,
        second_action=second,
        terminal_entropy=terminal_entropy,
        branch_total_cost=branch_total_cost,
        budget_feasible=branch_total_cost <= max_cost + POSITIVE_INFORMATION_TOLERANCE,
    )


def _best_second_action_with_adapter(
    *,
    adapter: CandidateGroupPredictionAdapter,
    candidates: list[Candidate],
    completed_experiments: list[CompletedExperiment],
    posterior_probabilities: tuple[float, ...],
    candidate_costs: Mapping[str, float],
    remaining_budget: float,
) -> LookaheadSecondAction:
    choices = [
        LookaheadSecondAction(
            candidate=None,
            action_effect="stop",
            expected_information_gain=0.0,
            estimated_cost=0.0,
            information_gain_per_cost=0.0,
            reason="STOP preserves budget because no second experiment is required.",
        )
    ]
    completed_ids = {item.candidate.candidate_id for item in completed_experiments}
    for candidate in sorted(candidates, key=lambda item: item.candidate_id):
        if candidate.candidate_id in completed_ids:
            continue
        candidate_cost = _candidate_cost(candidate, candidate_costs)
        if candidate_cost > remaining_budget + POSITIVE_INFORMATION_TOLERANCE:
            continue
        assessment = adapter.evidence_eligibility.assess_candidate(
            candidate,
            completed_experiments,
        )
        if assessment.effect != "completes_pair":
            continue
        snapshot = adapter.snapshot_for_candidate(candidate)
        if snapshot is None:
            raise ReasoningError("A simulated pair closer has no prediction snapshot.")
        distribution = discretized_gaussian_evidence_outcomes(
            snapshot.hypotheses,
            posterior_probabilities,
        )
        information_gain = distribution.expected_information_gain
        choices.append(
            LookaheadSecondAction(
                candidate=candidate,
                action_effect=assessment.effect,
                expected_information_gain=information_gain,
                estimated_cost=candidate_cost,
                information_gain_per_cost=_information_per_cost(
                    information_gain,
                    candidate_cost,
                ),
                reason=(
                    "Completes a structurally valid matched pair in this branch and produces "
                    "one possible optimizer-effect evidence update."
                ),
            )
        )
    return sorted(choices, key=_second_action_sort_key)[0]


def _first_action_sort_key(plan: LookaheadFirstActionPlan) -> tuple[float, float, float, str]:
    return (
        -plan.expected_total_information_gain,
        plan.expected_total_cost,
        -plan.information_gain_per_expected_cost,
        plan.candidate.candidate_id,
    )


def _second_action_sort_key(action: LookaheadSecondAction) -> tuple[float, float, float, str]:
    return (
        -action.expected_information_gain,
        action.estimated_cost,
        -action.information_gain_per_cost,
        action.candidate_id,
    )


def _rank_first_actions(
    ordered: list[LookaheadFirstActionPlan],
) -> tuple[LookaheadFirstActionPlan, ...]:
    selected = ordered[0]
    ranked: list[LookaheadFirstActionPlan] = []
    for index, plan in enumerate(ordered):
        if index == 0:
            reason = "Selected by the approved deterministic tie-breaking order."
        elif plan.expected_total_information_gain < selected.expected_total_information_gain:
            reason = "Lost because expected total information gain is lower."
        elif plan.expected_total_cost > selected.expected_total_cost:
            reason = "Lost because expected total cost is higher after an information-gain tie."
        elif plan.information_gain_per_expected_cost < selected.information_gain_per_expected_cost:
            reason = "Lost on information gain per expected cost after prior ties."
        else:
            reason = "Lost by stable lexicographic candidate-ID tie-breaking."
        ranked.append(replace(plan, ranking_reason=reason))
    return tuple(ranked)


def _alternative_from_plan(plan: LookaheadFirstActionPlan) -> LookaheadAlternative:
    return LookaheadAlternative(
        candidate=plan.candidate,
        action_effect=plan.action_effect,
        comparison_group_id=plan.public_design.comparison_group_id,
        immediate_information_gain=plan.immediate_information_gain,
        expected_total_information_gain=plan.expected_total_information_gain,
        expected_total_cost=plan.expected_total_cost,
        information_gain_per_expected_cost=plan.information_gain_per_expected_cost,
        ranking_reason=plan.ranking_reason,
    )


def _lookahead_rationale(
    selected: LookaheadFirstActionPlan,
    max_cost: float,
    fallback_reason: str | None,
) -> str:
    prefix = "" if fallback_reason is None else f"{fallback_reason} "
    return (
        f"{prefix}Selected {selected.candidate.candidate_id}, which "
        f"{selected.action_effect.replace('_', ' ')}, for expected two-step entropy reduction "
        f"{selected.expected_total_information_gain:.12f} bits at expected cost "
        f"{selected.expected_total_cost:.6f}. Every branch stays within the remaining budget "
        f"{max_cost:.6f}; only this first experiment is returned for execution."
    )


def _candidate_set_fingerprint(
    candidates: list[Candidate],
    candidate_costs: Mapping[str, float],
    eligibility: OptimizerEvidenceEligibilityContract,
) -> str:
    payload = [
        {
            "candidate": {"candidate_id": item.candidate_id, "params": item.params()},
            "cost": _candidate_cost(item, candidate_costs),
            "public_design": eligibility.design_for(item).to_dict(),
        }
        for item in sorted(candidates, key=lambda value: value.candidate_id)
    ]
    return _stable_id("candidate-set", payload)


def _completed_state_fingerprint(
    completed_experiments: list[CompletedExperiment],
    eligibility: OptimizerEvidenceEligibilityContract,
) -> str:
    return _stable_id(
        "completed-state",
        [
            {
                "candidate_id": item.candidate.candidate_id,
                "experiment_id": item.record_id,
                "public_design": eligibility.design_for(item.candidate).to_dict(),
            }
            for item in completed_experiments
        ],
    )


def _lookahead_plan_id(
    *,
    belief_state_id: str,
    max_cost: float,
    completed_state_fingerprint: str,
    candidate_set_fingerprint: str,
    ranked: tuple[LookaheadFirstActionPlan, ...],
) -> str:
    return _stable_id(
        "plan",
        {
            "belief_state_id": belief_state_id,
            "candidate_set_fingerprint": candidate_set_fingerprint,
            "completed_state_fingerprint": completed_state_fingerprint,
            "max_cost": max_cost,
            "policy_version": LOOKAHEAD_INFORMATION_GAIN_POLICY_VERSION,
            "ranked_first_actions": [
                {
                    "candidate_id": item.candidate.candidate_id,
                    "expected_total_information_gain": item.expected_total_information_gain,
                    "expected_total_cost": item.expected_total_cost,
                    "information_gain_per_expected_cost": (item.information_gain_per_expected_cost),
                }
                for item in ranked
            ],
        },
    )


def _information_per_cost(information_gain: float, cost: float) -> float:
    return 0.0 if cost <= 0.0 else information_gain / cost


def _entropy(probabilities: tuple[float, ...]) -> float:
    return -math.fsum(value * math.log2(value) for value in probabilities if value > 0.0)


@dataclass(frozen=True, slots=True)
class PotentialOutcome:
    """Evaluator-private committed outcome for one public candidate."""

    candidate_id: str
    observed_value: float
    key_material: str
    key_sha256: str

    def to_evaluator_dict(self) -> dict[str, object]:
        return {
            "record_visibility": "evaluator_only",
            "oracle_version": SELECTED_ONLY_ORACLE_VERSION,
            "candidate_id": self.candidate_id,
            "observed_value": self.observed_value,
            "key_material": self.key_material,
            "key_sha256": self.key_sha256,
        }


@dataclass(frozen=True, slots=True)
class PotentialOutcomeCommitment:
    world_id: str
    evaluation_seed: int
    candidate_ids: tuple[str, ...]
    canonical_table_sha256: str
    commitment_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "world_id": self.world_id,
            "evaluation_seed": self.evaluation_seed,
            "candidate_ids": list(self.candidate_ids),
            "canonical_table_sha256": self.canonical_table_sha256,
            "commitment_id": self.commitment_id,
            "oracle_version": SELECTED_ONLY_ORACLE_VERSION,
            "committed_before_arm_execution": True,
            "outcomes_revealed_to_policy": False,
        }


@dataclass(frozen=True, slots=True)
class OracleAccess:
    access_id: str
    run_id: str
    decision_trace_id: str
    candidate_id: str
    observed_value: float
    key_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "access_id": self.access_id,
            "run_id": self.run_id,
            "decision_trace_id": self.decision_trace_id,
            "candidate_id": self.candidate_id,
            "observed_value": self.observed_value,
            "key_sha256": self.key_sha256,
            "oracle_version": SELECTED_ONLY_ORACLE_VERSION,
            "selected_only": True,
        }


class SelectedOnlyObservationOracle:
    """Reveal one committed candidate only after a real decision is frozen."""

    version = SELECTED_ONLY_ORACLE_VERSION

    def __init__(
        self,
        *,
        commitment: PotentialOutcomeCommitment,
        outcomes: tuple[PotentialOutcome, ...],
    ) -> None:
        if tuple(item.candidate_id for item in outcomes) != commitment.candidate_ids:
            raise ReasoningError("Potential outcomes do not match their commitment.")
        self._commitment = commitment
        self._outcome_by_candidate = {item.candidate_id: item for item in outcomes}
        self._accesses: list[OracleAccess] = []
        self._accessed_run_candidates: set[tuple[str, str]] = set()

    @property
    def commitment_id(self) -> str:
        return self._commitment.commitment_id

    def reveal_selected(
        self,
        *,
        run_id: str,
        decision_trace_id: str,
        candidate: Candidate,
    ) -> OracleAccess:
        if not run_id.strip() or not decision_trace_id.strip():
            raise ReasoningError("Selected-only oracle requires a frozen real decision trace.")
        run_candidate = (run_id, candidate.candidate_id)
        if run_candidate in self._accessed_run_candidates:
            raise ReasoningError("A run cannot reveal the same candidate more than once.")
        try:
            outcome = self._outcome_by_candidate[candidate.candidate_id]
        except KeyError as error:
            raise ReasoningError(
                f"Selected candidate {candidate.candidate_id} is not in the commitment."
            ) from error
        access = OracleAccess(
            access_id=_stable_id(
                "oracle-access",
                {
                    "candidate_id": candidate.candidate_id,
                    "commitment_id": self._commitment.commitment_id,
                    "decision_trace_id": decision_trace_id,
                    "run_id": run_id,
                },
            ),
            run_id=run_id,
            decision_trace_id=decision_trace_id,
            candidate_id=candidate.candidate_id,
            observed_value=outcome.observed_value,
            key_sha256=outcome.key_sha256,
        )
        self._accessed_run_candidates.add(run_candidate)
        self._accesses.append(access)
        return access

    def audit_accesses(self) -> tuple[OracleAccess, ...]:
        """Return selected access records without exposing unrevealed outcomes."""

        return tuple(self._accesses)


def potential_outcome_commitment(
    *,
    world_id: str,
    evaluation_seed: int,
    outcomes: tuple[PotentialOutcome, ...],
) -> PotentialOutcomeCommitment:
    ordered = tuple(sorted(outcomes, key=lambda item: item.candidate_id))
    table_hash = hashlib.sha256(
        json.dumps(
            [
                (item.candidate_id, item.observed_value, item.key_material, item.key_sha256)
                for item in ordered
            ],
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    commitment_id = _stable_id(
        "potential-outcome-commitment",
        {
            "evaluation_seed": evaluation_seed,
            "table_sha256": table_hash,
            "version": SELECTED_ONLY_ORACLE_VERSION,
            "world_id": world_id,
        },
    )
    return PotentialOutcomeCommitment(
        world_id=world_id,
        evaluation_seed=evaluation_seed,
        candidate_ids=tuple(item.candidate_id for item in ordered),
        canonical_table_sha256=table_hash,
        commitment_id=commitment_id,
    )


@dataclass(frozen=True, slots=True)
class ClosedLoopArmSpec:
    run_id: str
    arm_id: str
    belief_model_id: str
    belief_model_version: str
    policy: BeliefAwarePolicy
    policy_version: str
    condition_key: str
    budget: float
    calibration_prefix_id: str | None
    calibration_cost: float

    def __post_init__(self) -> None:
        if self.policy not in {INFORMATION_GAIN_POLICY, LOOKAHEAD_INFORMATION_GAIN_POLICY}:
            raise ReasoningError("Closed-loop arm uses an unsupported policy.")
        if not math.isfinite(self.budget) or self.budget <= 0.0:
            raise ReasoningError("Closed-loop arm budget must be finite and positive.")
        if not math.isfinite(self.calibration_cost) or self.calibration_cost < 0.0:
            raise ReasoningError("Calibration cost must be finite and non-negative.")
        if self.belief_model_id == FIXED_SIGMA_MODEL_ID and (
            self.calibration_prefix_id is not None or self.calibration_cost != 0.0
        ):
            raise ReasoningError("Fixed-sigma arms cannot consume the calibration prefix.")


@dataclass(frozen=True, slots=True)
class ClosedLoopDecisionTrace:
    decision_trace_id: str
    run_id: str
    arm_id: str
    step: int
    belief_model_id: str
    belief_model_version: str
    lineage_id: str
    belief_state_id: str
    policy: str
    policy_version: str
    created_at: str
    remaining_budget: float
    selected_candidate_id: str
    selected_action_effect: EligibilityEffect
    selected_candidate_cost: float
    immediate_information_gain: float
    expected_total_information_gain: float
    expected_total_cost: float
    information_gain_per_expected_cost: float
    prediction_snapshots: tuple[CandidateGroupPredictionSnapshot, ...]
    policy_trace: PolicyDecision
    fixed_policy_regression_match: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "decision_trace_id": self.decision_trace_id,
            "run_id": self.run_id,
            "arm_id": self.arm_id,
            "step": self.step,
            "belief_model_id": self.belief_model_id,
            "belief_model_version": self.belief_model_version,
            "lineage_id": self.lineage_id,
            "belief_state_id": self.belief_state_id,
            "policy": self.policy,
            "policy_version": self.policy_version,
            "adapter_version": CANDIDATE_GROUP_ADAPTER_VERSION,
            "created_at": self.created_at,
            "remaining_budget": self.remaining_budget,
            "selected_candidate_id": self.selected_candidate_id,
            "selected_action_effect": self.selected_action_effect,
            "selected_candidate_cost": self.selected_candidate_cost,
            "immediate_information_gain": self.immediate_information_gain,
            "expected_total_information_gain": self.expected_total_information_gain,
            "expected_total_cost": self.expected_total_cost,
            "information_gain_per_expected_cost": self.information_gain_per_expected_cost,
            "prediction_snapshots": [item.to_dict() for item in self.prediction_snapshots],
            "policy_trace": self.policy_trace.to_dict(),
            "fixed_policy_regression_match": self.fixed_policy_regression_match,
            "observation_available_when_decided": False,
        }


@dataclass(frozen=True, slots=True)
class ClosedLoopExperiment:
    experiment_id: int
    step: int
    candidate: Candidate
    observed_value: float
    experiment_cost: float
    cumulative_decision_cost: float
    oracle_access_id: str
    decision_trace_id: str
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "experiment_id": self.experiment_id,
            "step": self.step,
            "candidate_id": self.candidate.candidate_id,
            "params": self.candidate.params(),
            "observed_value": self.observed_value,
            "experiment_cost": self.experiment_cost,
            "cumulative_decision_cost": self.cumulative_decision_cost,
            "oracle_access_id": self.oracle_access_id,
            "decision_trace_id": self.decision_trace_id,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class ClosedLoopExperimentTrace:
    step: int
    experiment_id: int
    candidate_id: str
    observed_value: float
    experiment_cost: float
    cumulative_decision_cost: float
    posterior_probabilities: tuple[tuple[str, float], ...]
    posterior_entropy: float
    new_evidence_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    matched_evidence_pairs_completed: int
    latest_sigma: float | None
    latest_sigma_status: str | None
    latest_adequacy_state: str
    best_observed_objective: float

    def to_dict(self) -> dict[str, object]:
        return {
            "step": self.step,
            "experiment_id": self.experiment_id,
            "candidate_id": self.candidate_id,
            "observed_value": self.observed_value,
            "experiment_cost": self.experiment_cost,
            "cumulative_decision_cost": self.cumulative_decision_cost,
            "posterior_probabilities": dict(self.posterior_probabilities),
            "posterior_entropy": self.posterior_entropy,
            "new_evidence_ids": list(self.new_evidence_ids),
            "evidence_ids": list(self.evidence_ids),
            "matched_evidence_pairs_completed": self.matched_evidence_pairs_completed,
            "latest_sigma": self.latest_sigma,
            "latest_sigma_status": self.latest_sigma_status,
            "latest_adequacy_state": self.latest_adequacy_state,
            "best_observed_objective": self.best_observed_objective,
        }


@dataclass(frozen=True, slots=True)
class TruthFreeClosedLoopArmRun:
    spec: ClosedLoopArmSpec
    runner_version: str
    lineage: BeliefModelLineage
    initial_posterior_probabilities: tuple[tuple[str, float], ...]
    experiments: tuple[ClosedLoopExperiment, ...]
    decisions: tuple[ClosedLoopDecisionTrace, ...]
    evidence: tuple[Evidence, ...]
    model_updates: tuple[ModelBeliefUpdate, ...]
    diagnostics: tuple[ModelAdequacyDiagnostic, ...]
    effect_history: tuple[MatchedEffectObservation, ...]
    trace: tuple[ClosedLoopExperimentTrace, ...]
    oracle_accesses: tuple[OracleAccess, ...]
    stop_reason: str
    budget_exhausted: bool

    def final_posterior(self) -> dict[str, float]:
        return self.lineage.current_state.state.posterior_map()

    def to_truth_free_dict(self) -> dict[str, object]:
        return {
            "run_id": self.spec.run_id,
            "arm_id": self.spec.arm_id,
            "runner_version": self.runner_version,
            "belief_model_id": self.spec.belief_model_id,
            "belief_model_version": self.spec.belief_model_version,
            "lineage_id": self.lineage.lineage_id,
            "policy": self.spec.policy,
            "policy_version": self.spec.policy_version,
            "condition_key": self.spec.condition_key,
            "budget": self.spec.budget,
            "calibration_prefix_id": self.spec.calibration_prefix_id,
            "calibration_cost": self.spec.calibration_cost,
            "initial_posterior_probabilities": dict(self.initial_posterior_probabilities),
            "final_posterior_probabilities": self.final_posterior(),
            "stop_reason": self.stop_reason,
            "budget_exhausted": self.budget_exhausted,
            "experiments": [item.to_dict() for item in self.experiments],
            "decision_trace_ids": [item.decision_trace_id for item in self.decisions],
            "evidence": [item.to_dict() for item in self.evidence],
            "model_update_ids": [item.model_update_id for item in self.model_updates],
            "diagnostic_ids": [item.diagnostic_id for item in self.diagnostics],
            "full_metric_trace": [item.to_dict() for item in self.trace],
            "oracle_accesses": [item.to_dict() for item in self.oracle_accesses],
        }


def run_closed_loop_arm(
    *,
    spec: ClosedLoopArmSpec,
    model: GaussianBeliefModel,
    candidates: tuple[Candidate, ...],
    candidate_costs: Mapping[str, float],
    evidence_eligibility: OptimizerEvidenceEligibilityContract,
    calibration_effects: tuple[MatchedEffectObservation, ...],
    oracle: SelectedOnlyObservationOracle,
    generated_at: str,
) -> TruthFreeClosedLoopArmRun:
    """Execute one isolated real trajectory under its own belief lineage."""

    if model.model_id != spec.belief_model_id or model.model_version != spec.belief_model_version:
        raise ReasoningError("Closed-loop arm model does not match its declared specification.")
    if model.model_id == FIXED_SIGMA_MODEL_ID and calibration_effects:
        raise ReasoningError("Fixed-sigma arms cannot read calibration effects.")
    lineage = initial_model_lineage(
        model,
        lineage_key=spec.run_id,
        created_at=f"{generated_at}#lineage:{spec.run_id}",
    )
    initial_probabilities = tuple(sorted(lineage.current_state.state.posterior_map().items()))
    completed: list[CompletedExperiment] = []
    experiments: list[ClosedLoopExperiment] = []
    decisions: list[ClosedLoopDecisionTrace] = []
    evidence_items: list[Evidence] = []
    updates: list[ModelBeliefUpdate] = []
    diagnostics: list[ModelAdequacyDiagnostic] = []
    effect_history: list[MatchedEffectObservation] = list(calibration_effects)
    applied_pairs: set[tuple[int, ...]] = set()
    trace: list[ClosedLoopExperimentTrace] = []
    cumulative_cost = 0.0
    best_observed: float | None = None
    stop_reason = "candidate_space_exhausted"
    budget_exhausted = False
    oracle_start = len(oracle.audit_accesses())

    while True:
        completed_ids = {item.candidate.candidate_id for item in completed}
        uncompleted = tuple(
            candidate for candidate in candidates if candidate.candidate_id not in completed_ids
        )
        remaining_budget = spec.budget - cumulative_cost
        feasible = tuple(
            candidate
            for candidate in uncompleted
            if _candidate_cost(candidate, candidate_costs)
            <= remaining_budget + POSITIVE_INFORMATION_TOLERANCE
        )
        if not feasible:
            budget_exhausted = bool(uncompleted)
            stop_reason = "budget_exhausted" if budget_exhausted else "candidate_space_exhausted"
            break

        adapter = build_candidate_group_prediction_adapter(
            model=model,
            lineage=lineage,
            effect_history=tuple(effect_history),
            evidence_eligibility=evidence_eligibility,
        )
        step = len(experiments) + 1
        created_at = f"{generated_at}#decision:{spec.run_id}:{step:04d}"
        policy_trace, fixed_match = _decide_arm_policy(
            spec=spec,
            adapter=adapter,
            lineage=lineage,
            candidates=feasible,
            completed_experiments=tuple(completed),
            candidate_costs=candidate_costs,
            remaining_budget=remaining_budget,
            created_at=created_at,
        )
        decision = _closed_loop_decision_trace(
            spec=spec,
            step=step,
            adapter=adapter,
            lineage=lineage,
            policy_trace=policy_trace,
            candidate_costs=candidate_costs,
            remaining_budget=remaining_budget,
            created_at=created_at,
            fixed_policy_regression_match=fixed_match,
        )
        selected = _selected_candidate(policy_trace)
        if selected.candidate_id not in {item.candidate_id for item in feasible}:
            raise ReasoningError("Closed-loop policy selected an infeasible experiment.")
        access = oracle.reveal_selected(
            run_id=spec.run_id,
            decision_trace_id=decision.decision_trace_id,
            candidate=selected,
        )
        experiment_cost = _candidate_cost(selected, candidate_costs)
        cumulative_cost = round(cumulative_cost + experiment_cost, 12)
        if cumulative_cost > spec.budget + POSITIVE_INFORMATION_TOLERANCE:
            raise ReasoningError("Real closed-loop experiment exceeded the hard decision budget.")
        experiment_id = _experiment_id(spec.run_id, step)
        experiment_created_at = f"{generated_at}#experiment:{spec.run_id}:{step:04d}"
        completed_item = CompletedExperiment(
            record_id=experiment_id,
            candidate=selected,
            observed_value=access.observed_value,
            created_at=experiment_created_at,
        )
        completed.append(completed_item)
        best_observed = (
            access.observed_value
            if best_observed is None
            else max(best_observed, access.observed_value)
        )
        experiment = ClosedLoopExperiment(
            experiment_id=experiment_id,
            step=step,
            candidate=selected,
            observed_value=access.observed_value,
            experiment_cost=experiment_cost,
            cumulative_decision_cost=cumulative_cost,
            oracle_access_id=access.access_id,
            decision_trace_id=decision.decision_trace_id,
            created_at=experiment_created_at,
        )
        experiments.append(experiment)
        decisions.append(decision)

        new_evidence_ids: list[str] = []
        latest_sigma: float | None = None
        latest_sigma_status: str | None = None
        for pair in evidence_eligibility.valid_unapplied_pairs(
            completed,
            applied_source_pairs=frozenset(applied_pairs),
        ):
            evidence = evidence_from_matched_pair(pair, evidence_eligibility)
            lineage, update, current_effect = model.update(
                lineage=lineage,
                evidence=evidence,
                effect_history=tuple(effect_history),
                diagnostic_history=tuple(diagnostics),
            )
            evidence_items.append(evidence)
            updates.append(update)
            diagnostics.append(update.diagnostic)
            effect_history.append(current_effect)
            applied_pairs.add(pair.source_experiment_ids)
            new_evidence_ids.append(evidence.evidence_id)
            latest_sigma = update.sigma_estimate.estimated_sigma
            latest_sigma_status = update.sigma_estimate.status
        posterior = lineage.current_state.state.posterior_map()
        trace.append(
            ClosedLoopExperimentTrace(
                step=step,
                experiment_id=experiment_id,
                candidate_id=selected.candidate_id,
                observed_value=access.observed_value,
                experiment_cost=experiment_cost,
                cumulative_decision_cost=cumulative_cost,
                posterior_probabilities=tuple(sorted(posterior.items())),
                posterior_entropy=_entropy(tuple(posterior.values())),
                new_evidence_ids=tuple(new_evidence_ids),
                evidence_ids=lineage.current_state.state.evidence_ids,
                matched_evidence_pairs_completed=len(updates),
                latest_sigma=latest_sigma,
                latest_sigma_status=latest_sigma_status,
                latest_adequacy_state=(
                    diagnostics[-1].adequacy_state if diagnostics else "uncertain"
                ),
                best_observed_objective=best_observed,
            )
        )

    accesses = oracle.audit_accesses()[oracle_start:]
    if len(accesses) != len(experiments):
        raise ReasoningError("Selected-only oracle accesses do not match real experiments.")
    return TruthFreeClosedLoopArmRun(
        spec=spec,
        runner_version=CLOSED_LOOP_ARM_RUNNER_VERSION,
        lineage=lineage,
        initial_posterior_probabilities=initial_probabilities,
        experiments=tuple(experiments),
        decisions=tuple(decisions),
        evidence=tuple(evidence_items),
        model_updates=tuple(updates),
        diagnostics=tuple(diagnostics),
        effect_history=tuple(effect_history),
        trace=tuple(trace),
        oracle_accesses=accesses,
        stop_reason=stop_reason,
        budget_exhausted=budget_exhausted,
    )


def _decide_arm_policy(
    *,
    spec: ClosedLoopArmSpec,
    adapter: CandidateGroupPredictionAdapter,
    lineage: BeliefModelLineage,
    candidates: tuple[Candidate, ...],
    completed_experiments: tuple[CompletedExperiment, ...],
    candidate_costs: Mapping[str, float],
    remaining_budget: float,
    created_at: str,
) -> tuple[PolicyDecision, bool]:
    if spec.policy == INFORMATION_GAIN_POLICY:
        adapted: PolicyDecision = decide_information_gain_with_adapter(
            adapter=adapter,
            lineage=lineage,
            candidates=candidates,
            completed_experiments=completed_experiments,
            candidate_costs=candidate_costs,
            max_cost=remaining_budget,
            created_at=created_at,
        )
        if spec.belief_model_id == FIXED_SIGMA_MODEL_ID:
            from research_decision_engine.decision import InformationGainPolicy

            base_information = InformationGainPolicy().decide(
                candidates=list(candidates),
                completed_experiments=list(completed_experiments),
                hypotheses=adapter.canonical_snapshot().hypotheses,
                belief_state=lineage.current_state.state,
                cost=lambda item: _candidate_cost(item, candidate_costs),
                max_cost=remaining_budget,
                created_at=created_at,
                eligibility=adapter.evidence_eligibility,
            )
            match = adapted.to_dict() == base_information.to_dict()
            if not match:
                raise ReasoningError("Fixed information-gain adapter changed policy behavior.")
            return adapted, True
        return adapted, True
    adapted = decide_lookahead_with_adapter(
        adapter=adapter,
        lineage=lineage,
        candidates=candidates,
        completed_experiments=completed_experiments,
        candidate_costs=candidate_costs,
        max_cost=remaining_budget,
        created_at=created_at,
    )
    if spec.belief_model_id == FIXED_SIGMA_MODEL_ID:
        base_lookahead = LookaheadInformationGainPolicy().decide(
            candidates=list(candidates),
            completed_experiments=list(completed_experiments),
            hypotheses=adapter.canonical_snapshot().hypotheses,
            belief_state=lineage.current_state.state,
            eligibility=adapter.evidence_eligibility,
            cost=lambda item: _candidate_cost(item, candidate_costs),
            max_cost=remaining_budget,
            created_at=created_at,
        )
        match = adapted.to_dict() == base_lookahead.to_dict()
        if not match:
            raise ReasoningError("Fixed lookahead adapter changed policy behavior.")
        return adapted, True
    return adapted, True


def _closed_loop_decision_trace(
    *,
    spec: ClosedLoopArmSpec,
    step: int,
    adapter: CandidateGroupPredictionAdapter,
    lineage: BeliefModelLineage,
    policy_trace: PolicyDecision,
    candidate_costs: Mapping[str, float],
    remaining_budget: float,
    created_at: str,
    fixed_policy_regression_match: bool,
) -> ClosedLoopDecisionTrace:
    selected = _selected_candidate(policy_trace)
    assessment = adapter.evidence_eligibility.assess_candidate(
        selected,
        (),
    )
    if isinstance(policy_trace, DecisionTrace):
        immediate = policy_trace.selected.expected_information_gain
        total_information = immediate
        expected_cost = policy_trace.selected.estimated_cost
        ratio = _information_per_cost(total_information, expected_cost)
        selected_effect: EligibilityEffect = (
            "completes_pair" if policy_trace.selected.completes_matched_pair else assessment.effect
        )
        policy_id = policy_trace.suggestion_id
    else:
        immediate = policy_trace.selected.immediate_information_gain
        total_information = policy_trace.selected.expected_total_information_gain
        expected_cost = policy_trace.selected.expected_total_cost
        ratio = policy_trace.selected.information_gain_per_expected_cost
        selected_effect = policy_trace.selected.action_effect
        policy_id = policy_trace.plan_id
    decision_trace_id = _stable_id(
        "closed-loop-decision",
        {
            "adapter_version": adapter.adapter_version,
            "arm_id": spec.arm_id,
            "lineage_id": lineage.lineage_id,
            "policy_trace_id": policy_id,
            "run_id": spec.run_id,
            "step": step,
        },
    )
    return ClosedLoopDecisionTrace(
        decision_trace_id=decision_trace_id,
        run_id=spec.run_id,
        arm_id=spec.arm_id,
        step=step,
        belief_model_id=spec.belief_model_id,
        belief_model_version=spec.belief_model_version,
        lineage_id=lineage.lineage_id,
        belief_state_id=lineage.current_state.state.belief_state_id,
        policy=spec.policy,
        policy_version=spec.policy_version,
        created_at=created_at,
        remaining_budget=remaining_budget,
        selected_candidate_id=selected.candidate_id,
        selected_action_effect=selected_effect,
        selected_candidate_cost=_candidate_cost(selected, candidate_costs),
        immediate_information_gain=immediate,
        expected_total_information_gain=total_information,
        expected_total_cost=expected_cost,
        information_gain_per_expected_cost=ratio,
        prediction_snapshots=adapter.snapshots,
        policy_trace=policy_trace,
        fixed_policy_regression_match=fixed_policy_regression_match,
    )


def _selected_candidate(trace: PolicyDecision) -> Candidate:
    return trace.candidate


def _experiment_id(run_id: str, step: int) -> int:
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) * 100 + step
