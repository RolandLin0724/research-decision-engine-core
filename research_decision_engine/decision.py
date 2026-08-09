"""Belief-guided experiment decisions for the synthetic optimizer application."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass, replace

from research_decision_engine.evidence_eligibility import (
    OptimizerEvidenceEligibilityContract,
)
from research_decision_engine.reasoning import (
    PROBABILITY_TOLERANCE,
    BeliefState,
    Hypothesis,
    Provenance,
    ReasoningError,
)
from research_decision_engine.types import Candidate, CompletedExperiment

INFORMATION_GAIN_POLICY = "information_gain"
INFORMATION_GAIN_POLICY_VERSION = "information-gain-policy/v1"
INFORMATION_GAIN_METHOD_VERSION = "discretized-gaussian-mutual-information/v1"
POSITIVE_INFORMATION_TOLERANCE = 1e-12
OUTCOME_GRID_MIN = -0.40
OUTCOME_GRID_MAX = 0.40
OUTCOME_GRID_STEP = 0.01
MIN_EXPLANATORY_OUTCOME_PROBABILITY = 1e-6


@dataclass(frozen=True, slots=True)
class HypothesisDecisionContext:
    """Belief and diagnostic outcome recorded for one competing hypothesis."""

    hypothesis_id: str
    statement: str
    posterior_probability: float
    most_favorable_outcome: float
    most_favorable_outcome_label: str
    posterior_if_observed: float

    def to_dict(self) -> dict[str, object]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "statement": self.statement,
            "posterior_probability": self.posterior_probability,
            "most_favorable_outcome": self.most_favorable_outcome,
            "most_favorable_outcome_label": self.most_favorable_outcome_label,
            "posterior_if_observed": self.posterior_if_observed,
        }


@dataclass(frozen=True, slots=True)
class InformationGainEstimate:
    """Deterministic entropy reduction for one matched-pair evidence observation."""

    prior_entropy: float
    expected_posterior_entropy: float
    expected_information_gain: float
    outcome_bin_count: int
    hypotheses: tuple[HypothesisDecisionContext, ...]


@dataclass(frozen=True, slots=True)
class EvidenceOutcomeBranch:
    """One quantized evidence outcome under a posterior predictive mixture."""

    branch_id: str
    label: str
    lower_bound: float | None
    upper_bound: float | None
    predictive_probability: float
    posterior_probabilities: tuple[float, ...]
    posterior_entropy: float

    def to_dict(self, hypothesis_ids: tuple[str, ...]) -> dict[str, object]:
        return {
            "branch_id": self.branch_id,
            "label": self.label,
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
            "predictive_probability": self.predictive_probability,
            "posterior_probabilities": dict(
                zip(hypothesis_ids, self.posterior_probabilities, strict=True)
            ),
            "posterior_entropy": self.posterior_entropy,
        }


@dataclass(frozen=True, slots=True)
class EvidenceOutcomeDistribution:
    """Complete discretized predictive distribution for one matched comparison."""

    hypothesis_ids: tuple[str, ...]
    prior_entropy: float
    expected_posterior_entropy: float
    expected_information_gain: float
    branches: tuple[EvidenceOutcomeBranch, ...]


@dataclass(frozen=True, slots=True)
class CandidateScore:
    """Information and feasibility details for one candidate experiment."""

    candidate: Candidate
    expected_information_gain: float
    prior_entropy: float
    expected_posterior_entropy: float
    estimated_cost: float
    completes_matched_pair: bool
    matched_experiment_id: int | None
    score_reason: str
    ranking_reason: str = ""

    def __post_init__(self) -> None:
        for label, value in (
            ("expected information gain", self.expected_information_gain),
            ("prior entropy", self.prior_entropy),
            ("expected posterior entropy", self.expected_posterior_entropy),
            ("estimated cost", self.estimated_cost),
        ):
            if not math.isfinite(value) or value < 0.0:
                raise ReasoningError(f"Candidate {label} must be finite and non-negative.")
        if self.completes_matched_pair != (self.matched_experiment_id is not None):
            raise ReasoningError("Matched-pair status and experiment reference are inconsistent.")
        if not self.score_reason.strip():
            raise ReasoningError("Candidate score reason must not be empty.")

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate.candidate_id,
            "params": self.candidate.params(),
            "expected_information_gain": self.expected_information_gain,
            "prior_entropy": self.prior_entropy,
            "expected_posterior_entropy": self.expected_posterior_entropy,
            "estimated_cost": self.estimated_cost,
            "completes_matched_pair": self.completes_matched_pair,
            "matched_experiment_id": self.matched_experiment_id,
            "score_reason": self.score_reason,
            "ranking_reason": self.ranking_reason,
        }


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    """A persisted, reproducible belief-guided experiment suggestion."""

    suggestion_id: str
    policy: str
    policy_version: str
    created_at: str
    belief_state_id: str
    selected: CandidateScore
    hypotheses: tuple[HypothesisDecisionContext, ...]
    max_cost: float
    fallback_reason: str | None
    rationale: str
    ranked_candidates: tuple[CandidateScore, ...]
    provenance: Provenance

    def __post_init__(self) -> None:
        if not self.suggestion_id.strip() or not self.created_at.strip():
            raise ReasoningError("Decision suggestion ID and timestamp must not be empty.")
        if self.policy != INFORMATION_GAIN_POLICY:
            raise ReasoningError("Decision trace policy does not match information_gain.")
        if not math.isfinite(self.max_cost) or self.max_cost < 0.0:
            raise ReasoningError("Decision maximum cost must be finite and non-negative.")
        if not self.ranked_candidates or self.ranked_candidates[0] != self.selected:
            raise ReasoningError("Selected candidate must rank first in the decision trace.")
        if not self.rationale.strip():
            raise ReasoningError("Decision rationale must not be empty.")

    @property
    def candidate(self) -> Candidate:
        return self.selected.candidate

    def to_dict(self) -> dict[str, object]:
        return {
            "suggestion_id": self.suggestion_id,
            "policy": self.policy,
            "policy_version": self.policy_version,
            "created_at": self.created_at,
            "belief_state_id": self.belief_state_id,
            "selected": self.selected.to_dict(),
            "hypotheses": [item.to_dict() for item in self.hypotheses],
            "max_cost": self.max_cost,
            "fallback_reason": self.fallback_reason,
            "rationale": self.rationale,
            "ranked_candidates": [item.to_dict() for item in self.ranked_candidates],
            "provenance": self.provenance.to_dict(),
        }


class InformationGainPolicy:
    """Choose the feasible experiment with greatest expected hypothesis information."""

    name = INFORMATION_GAIN_POLICY
    version = INFORMATION_GAIN_POLICY_VERSION

    def decide(
        self,
        *,
        candidates: list[Candidate],
        completed_experiments: list[CompletedExperiment],
        hypotheses: tuple[Hypothesis, ...],
        belief_state: BeliefState,
        cost: Callable[[Candidate], float],
        max_cost: float,
        created_at: str,
        eligibility: OptimizerEvidenceEligibilityContract | None = None,
    ) -> DecisionTrace:
        if not math.isfinite(max_cost) or max_cost < 0.0:
            raise ValueError("Maximum experiment cost must be finite and non-negative.")
        estimate = expected_information_gain(hypotheses, belief_state)
        completed_ids = {item.candidate.candidate_id for item in completed_experiments}
        contract = eligibility or OptimizerEvidenceEligibilityContract.from_candidates(
            [*candidates, *(item.candidate for item in completed_experiments)]
        )

        scores: list[CandidateScore] = []
        for candidate in sorted(candidates, key=lambda item: item.candidate_id):
            if candidate.candidate_id in completed_ids:
                continue
            candidate_cost = cost(candidate)
            if not math.isfinite(candidate_cost) or candidate_cost < 0.0:
                raise ValueError(f"Candidate {candidate.candidate_id} has invalid cost.")
            if candidate_cost > max_cost:
                continue
            assessment = contract.assess_candidate(candidate, completed_experiments)
            if assessment.effect in {
                "completed_candidate",
                "duplicate_arm",
                "already_completed_pair",
                "ambiguous_counterpart",
            }:
                continue
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

        has_positive_information = any(
            item.expected_information_gain > POSITIVE_INFORMATION_TOLERANCE for item in scores
        )
        if has_positive_information:
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
                scores,
                key=lambda item: (item.estimated_cost, item.candidate.candidate_id),
            )
            if estimate.expected_information_gain <= POSITIVE_INFORMATION_TOLERANCE:
                fallback_reason = (
                    "Current beliefs have no positive expected entropy reduction; selected the "
                    "lowest-cost feasible candidate."
                )
            else:
                fallback_reason = (
                    "No feasible candidate can complete a new matched pair; selected the "
                    "lowest-cost feasible candidate."
                )

        ranked = _add_ranking_reasons(ordered, has_positive_information)
        selected = ranked[0]
        rationale = _decision_rationale(selected, max_cost, fallback_reason)
        suggestion_id = _suggestion_id(
            belief_state_id=belief_state.belief_state_id,
            max_cost=max_cost,
            ranked=ranked,
            fallback_reason=fallback_reason,
        )
        provenance = Provenance.create(
            method="belief-guided-experiment-selection",
            version=self.version,
            details={
                "belief_state_id": belief_state.belief_state_id,
                "candidate_count_scored": len(ranked),
                "completed_experiment_count": len(completed_experiments),
                "entropy_unit": "bits",
                "information_gain_method": INFORMATION_GAIN_METHOD_VERSION,
                "max_cost": max_cost,
                "outcome_bin_count": estimate.outcome_bin_count,
                "selected_candidate_id": selected.candidate.candidate_id,
            },
        )
        return DecisionTrace(
            suggestion_id=suggestion_id,
            policy=self.name,
            policy_version=self.version,
            created_at=created_at,
            belief_state_id=belief_state.belief_state_id,
            selected=selected,
            hypotheses=estimate.hypotheses,
            max_cost=max_cost,
            fallback_reason=fallback_reason,
            rationale=rationale,
            ranked_candidates=ranked,
            provenance=provenance,
        )


def expected_information_gain(
    hypotheses: tuple[Hypothesis, ...], belief_state: BeliefState
) -> InformationGainEstimate:
    """Compute deterministic mutual information for one future matched comparison."""

    ordered_hypotheses = tuple(sorted(hypotheses, key=lambda item: item.hypothesis_id))
    hypothesis_ids = tuple(item.hypothesis_id for item in ordered_hypotheses)
    if hypothesis_ids != belief_state.hypothesis_ids:
        raise ReasoningError("Hypotheses do not match the belief state used for selection.")

    posterior = belief_state.posterior_probabilities
    prior_entropy = _entropy(posterior)
    first_grid_index = round(OUTCOME_GRID_MIN / OUTCOME_GRID_STEP)
    last_grid_index = round(OUTCOME_GRID_MAX / OUTCOME_GRID_STEP)
    edges = (
        -math.inf,
        *(index * OUTCOME_GRID_STEP for index in range(first_grid_index, last_grid_index + 1)),
        math.inf,
    )
    outcome_masses = tuple(
        _outcome_bin_masses(hypothesis, edges) for hypothesis in ordered_hypotheses
    )
    expected_posterior_entropy = 0.0
    best_outcomes: list[tuple[float, int] | None] = [None] * len(ordered_hypotheses)
    most_probable_bin = 0
    greatest_predictive_probability = -1.0
    for bin_index in range(len(edges) - 1):
        weighted = tuple(
            probability * masses[bin_index]
            for probability, masses in zip(posterior, outcome_masses, strict=True)
        )
        predictive_probability = math.fsum(weighted)
        if predictive_probability <= 0.0:
            continue
        posterior_for_outcome = tuple(value / predictive_probability for value in weighted)
        expected_posterior_entropy += predictive_probability * _entropy(posterior_for_outcome)
        if predictive_probability > greatest_predictive_probability:
            most_probable_bin = bin_index
            greatest_predictive_probability = predictive_probability
        if predictive_probability >= MIN_EXPLANATORY_OUTCOME_PROBABILITY:
            for hypothesis_index, probability in enumerate(posterior_for_outcome):
                current_best = best_outcomes[hypothesis_index]
                if current_best is None or probability > current_best[0]:
                    best_outcomes[hypothesis_index] = (probability, bin_index)

    information_gain = prior_entropy - expected_posterior_entropy
    if information_gain < -POSITIVE_INFORMATION_TOLERANCE:
        raise ReasoningError("Expected information gain was numerically negative.")
    information_gain = max(0.0, information_gain)
    expected_posterior_entropy = prior_entropy - information_gain
    contexts = tuple(
        _hypothesis_context_from_bin(
            hypothesis=hypothesis,
            belief_state=belief_state,
            edges=edges,
            best_outcome=_resolved_best_outcome(best_outcomes[index], most_probable_bin),
        )
        for index, hypothesis in enumerate(ordered_hypotheses)
    )
    return InformationGainEstimate(
        prior_entropy=prior_entropy,
        expected_posterior_entropy=expected_posterior_entropy,
        expected_information_gain=information_gain,
        outcome_bin_count=len(edges) - 1,
        hypotheses=contexts,
    )


def discretized_gaussian_evidence_outcomes(
    hypotheses: tuple[Hypothesis, ...],
    posterior_probabilities: tuple[float, ...],
) -> EvidenceOutcomeDistribution:
    """Enumerate normalized Gaussian evidence branches for simulated planning."""

    ordered_hypotheses = tuple(sorted(hypotheses, key=lambda item: item.hypothesis_id))
    hypothesis_ids = tuple(item.hypothesis_id for item in ordered_hypotheses)
    if len(posterior_probabilities) != len(hypothesis_ids):
        raise ReasoningError("Posterior probabilities do not match planning hypotheses.")
    if any(not math.isfinite(value) or value < 0.0 for value in posterior_probabilities):
        raise ReasoningError("Planning posterior probabilities must be finite and non-negative.")
    posterior_total = math.fsum(posterior_probabilities)
    if not math.isclose(
        posterior_total,
        1.0,
        rel_tol=0.0,
        abs_tol=PROBABILITY_TOLERANCE,
    ):
        raise ReasoningError("Planning posterior probabilities must sum to one.")

    first_grid_index = round(OUTCOME_GRID_MIN / OUTCOME_GRID_STEP)
    last_grid_index = round(OUTCOME_GRID_MAX / OUTCOME_GRID_STEP)
    edges = (
        -math.inf,
        *(index * OUTCOME_GRID_STEP for index in range(first_grid_index, last_grid_index + 1)),
        math.inf,
    )
    masses_by_hypothesis = tuple(
        _outcome_bin_masses(hypothesis, edges) for hypothesis in ordered_hypotheses
    )
    raw_predictive_probabilities = tuple(
        math.fsum(
            posterior * masses[bin_index]
            for posterior, masses in zip(
                posterior_probabilities,
                masses_by_hypothesis,
                strict=True,
            )
        )
        for bin_index in range(len(edges) - 1)
    )
    predictive_total = math.fsum(raw_predictive_probabilities)
    if not math.isfinite(predictive_total) or predictive_total <= 0.0:
        raise ReasoningError("Predictive evidence branches have invalid total probability.")

    branches: list[EvidenceOutcomeBranch] = []
    for bin_index, raw_probability in enumerate(raw_predictive_probabilities):
        if raw_probability <= 0.0:
            continue
        weighted = tuple(
            posterior * masses[bin_index]
            for posterior, masses in zip(
                posterior_probabilities,
                masses_by_hypothesis,
                strict=True,
            )
        )
        posterior_for_outcome = tuple(value / raw_probability for value in weighted)
        lower = edges[bin_index]
        upper = edges[bin_index + 1]
        branches.append(
            EvidenceOutcomeBranch(
                branch_id=f"evidence-bin-{bin_index:03d}",
                label=_outcome_bin_label(lower, upper),
                lower_bound=None if lower == -math.inf else lower,
                upper_bound=None if upper == math.inf else upper,
                predictive_probability=raw_probability / predictive_total,
                posterior_probabilities=posterior_for_outcome,
                posterior_entropy=_entropy(posterior_for_outcome),
            )
        )

    normalized_total = math.fsum(item.predictive_probability for item in branches)
    if not math.isclose(
        normalized_total,
        1.0,
        rel_tol=0.0,
        abs_tol=PROBABILITY_TOLERANCE,
    ):
        raise ReasoningError("Normalized predictive branches must sum to one.")
    prior_entropy = _entropy(posterior_probabilities)
    expected_posterior_entropy = math.fsum(
        item.predictive_probability * item.posterior_entropy for item in branches
    )
    information_gain = prior_entropy - expected_posterior_entropy
    if information_gain < -POSITIVE_INFORMATION_TOLERANCE:
        raise ReasoningError("Simulated expected information gain was numerically negative.")
    information_gain = max(0.0, information_gain)
    return EvidenceOutcomeDistribution(
        hypothesis_ids=hypothesis_ids,
        prior_entropy=prior_entropy,
        expected_posterior_entropy=prior_entropy - information_gain,
        expected_information_gain=information_gain,
        branches=tuple(branches),
    )


def _resolved_best_outcome(
    best_outcome: tuple[float, int] | None, default_bin: int
) -> tuple[float, int]:
    return (0.0, default_bin) if best_outcome is None else best_outcome


def _outcome_bin_masses(hypothesis: Hypothesis, edges: tuple[float, ...]) -> tuple[float, ...]:
    if hypothesis.prediction_model.model_type != "gaussian":
        raise ReasoningError("Information-gain policy currently requires Gaussian predictions.")
    parameters = hypothesis.prediction_model.parameters()
    mean = parameters["mean"]
    standard_deviation = parameters["standard_deviation"]
    masses = tuple(
        max(
            0.0,
            _normal_cdf(edges[index + 1], mean, standard_deviation)
            - _normal_cdf(edges[index], mean, standard_deviation),
        )
        for index in range(len(edges) - 1)
    )
    total = math.fsum(masses)
    if not math.isfinite(total) or total <= 0.0:
        raise ReasoningError("Predicted evidence distribution has invalid total probability.")
    return tuple(value / total for value in masses)


def _normal_cdf(value: float, mean: float, standard_deviation: float) -> float:
    if value == -math.inf:
        return 0.0
    if value == math.inf:
        return 1.0
    standardized = (value - mean) / (standard_deviation * math.sqrt(2.0))
    return 0.5 * (1.0 + math.erf(standardized))


def _outcome_bin_label(lower: float, upper: float) -> str:
    if lower == -math.inf:
        return f"optimizer effect below {upper:+.3f}"
    if upper == math.inf:
        return f"optimizer effect at or above {lower:+.3f}"
    return f"optimizer effect in [{lower:+.3f}, {upper:+.3f})"


def _entropy(probabilities: tuple[float, ...]) -> float:
    return -math.fsum(value * math.log2(value) for value in probabilities if value > 0.0)


def _hypothesis_context_from_bin(
    *,
    hypothesis: Hypothesis,
    belief_state: BeliefState,
    edges: tuple[float, ...],
    best_outcome: tuple[float, int],
) -> HypothesisDecisionContext:
    posterior_if_observed, bin_index = best_outcome
    lower = edges[bin_index]
    upper = edges[bin_index + 1]
    if lower == -math.inf:
        representative = upper
        label = f"optimizer effect below {upper:+.3f}"
    elif upper == math.inf:
        representative = lower
        label = f"optimizer effect at or above {lower:+.3f}"
    else:
        representative = (lower + upper) / 2.0
        label = f"optimizer effect in [{lower:+.3f}, {upper:+.3f})"
    return HypothesisDecisionContext(
        hypothesis_id=hypothesis.hypothesis_id,
        statement=hypothesis.statement,
        posterior_probability=belief_state.posterior_for(hypothesis.hypothesis_id),
        most_favorable_outcome=representative,
        most_favorable_outcome_label=label,
        posterior_if_observed=posterior_if_observed,
    )


def _add_ranking_reasons(
    ordered: list[CandidateScore], has_positive_information: bool
) -> tuple[CandidateScore, ...]:
    selected = ordered[0]
    ranked: list[CandidateScore] = []
    for index, score in enumerate(ordered):
        if index == 0:
            if has_positive_information:
                reason = "Selected for maximum positive expected information gain."
            else:
                reason = "Selected as the lowest-cost deterministic fallback."
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


def _decision_rationale(
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


def _suggestion_id(
    *,
    belief_state_id: str,
    max_cost: float,
    ranked: tuple[CandidateScore, ...],
    fallback_reason: str | None,
) -> str:
    payload = {
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
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"suggestion-{hashlib.sha256(encoded).hexdigest()[:24]}"
