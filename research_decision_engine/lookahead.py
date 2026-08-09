"""Fixed two-step receding-horizon planning for optimizer-effect evidence."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Literal, cast

from research_decision_engine.decision import (
    INFORMATION_GAIN_METHOD_VERSION,
    POSITIVE_INFORMATION_TOLERANCE,
    EvidenceOutcomeBranch,
    discretized_gaussian_evidence_outcomes,
)
from research_decision_engine.evidence_eligibility import (
    EligibilityEffect,
    EvidenceEligibilityAssessment,
    OptimizerEvidenceEligibilityContract,
    PublicExperimentDesign,
)
from research_decision_engine.reasoning import (
    PROBABILITY_TOLERANCE,
    BeliefState,
    Hypothesis,
    Provenance,
    ProvenanceValue,
    ReasoningError,
)
from research_decision_engine.types import Candidate, CompletedExperiment

LOOKAHEAD_INFORMATION_GAIN_POLICY = "lookahead_information_gain"
LOOKAHEAD_INFORMATION_GAIN_POLICY_VERSION = "lookahead-information-gain-policy/v1"
LOOKAHEAD_UTILITY_VERSION = "two-step-total-entropy-reduction/v1"
NO_EVIDENCE_BRANCH_ID = "no-evidence-yet"
NO_EVIDENCE_BRANCH_LABEL = "NO_EVIDENCE_YET"
STOP_ACTION_ID = "STOP"

type PlannedActionEffect = EligibilityEffect | Literal["stop"]

TIE_BREAKING_ORDER: tuple[str, ...] = (
    "greater expected total information gain",
    "lower expected total cost",
    "greater information gain per expected cost",
    "stable lexicographic candidate ID",
)


@dataclass(frozen=True, slots=True)
class LookaheadSecondAction:
    """Best second action selected inside one simulated first-outcome branch."""

    candidate: Candidate | None
    action_effect: PlannedActionEffect
    expected_information_gain: float
    estimated_cost: float
    information_gain_per_cost: float
    reason: str

    def __post_init__(self) -> None:
        _validate_non_negative(self.expected_information_gain, "Second-action information gain")
        _validate_non_negative(self.estimated_cost, "Second-action cost")
        _validate_non_negative(
            self.information_gain_per_cost,
            "Second-action information gain per cost",
        )
        if self.action_effect == "stop" and self.candidate is not None:
            raise ReasoningError("A STOP action cannot contain a candidate.")
        if self.action_effect != "stop" and self.candidate is None:
            raise ReasoningError("A non-STOP action must contain a candidate.")
        if not self.reason.strip():
            raise ReasoningError("Second-action reason must not be empty.")

    @property
    def candidate_id(self) -> str:
        return STOP_ACTION_ID if self.candidate is None else self.candidate.candidate_id

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate": None if self.candidate is None else _candidate_to_dict(self.candidate),
            "candidate_id": self.candidate_id,
            "action_effect": self.action_effect,
            "expected_information_gain": self.expected_information_gain,
            "estimated_cost": self.estimated_cost,
            "information_gain_per_cost": self.information_gain_per_cost,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> LookaheadSecondAction:
        candidate_value = data["candidate"]
        candidate = (
            None
            if candidate_value is None
            else _candidate_from_dict(_require_mapping(candidate_value, "second candidate"))
        )
        return cls(
            candidate=candidate,
            action_effect=cast(PlannedActionEffect, str(data["action_effect"])),
            expected_information_gain=float(cast(float, data["expected_information_gain"])),
            estimated_cost=float(cast(float, data["estimated_cost"])),
            information_gain_per_cost=float(cast(float, data["information_gain_per_cost"])),
            reason=str(data["reason"]),
        )


@dataclass(frozen=True, slots=True)
class LookaheadBranch:
    """One immutable simulated outcome after the first candidate."""

    branch_id: str
    label: str
    probability: float
    evidence_lower_bound: float | None
    evidence_upper_bound: float | None
    posterior_probabilities: tuple[tuple[str, float], ...]
    posterior_entropy: float
    second_action: LookaheadSecondAction
    terminal_entropy: float
    branch_total_cost: float
    budget_feasible: bool

    def __post_init__(self) -> None:
        if not self.branch_id.strip() or not self.label.strip():
            raise ReasoningError("Lookahead branch ID and label must not be empty.")
        if not math.isfinite(self.probability) or not 0.0 <= self.probability <= 1.0:
            raise ReasoningError("Lookahead branch probability must be finite and in [0, 1].")
        _validate_probability_pairs(self.posterior_probabilities, "Branch posterior")
        _validate_non_negative(self.posterior_entropy, "Branch posterior entropy")
        _validate_non_negative(self.terminal_entropy, "Branch terminal entropy")
        _validate_non_negative(self.branch_total_cost, "Branch total cost")
        for value in (self.evidence_lower_bound, self.evidence_upper_bound):
            if value is not None and not math.isfinite(value):
                raise ReasoningError("Finite evidence bounds or None are required.")

    def to_dict(self) -> dict[str, object]:
        return {
            "branch_id": self.branch_id,
            "label": self.label,
            "probability": self.probability,
            "evidence_lower_bound": self.evidence_lower_bound,
            "evidence_upper_bound": self.evidence_upper_bound,
            "posterior_probabilities": dict(self.posterior_probabilities),
            "posterior_entropy": self.posterior_entropy,
            "second_action": self.second_action.to_dict(),
            "terminal_entropy": self.terminal_entropy,
            "branch_total_cost": self.branch_total_cost,
            "budget_feasible": self.budget_feasible,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> LookaheadBranch:
        return cls(
            branch_id=str(data["branch_id"]),
            label=str(data["label"]),
            probability=float(cast(float, data["probability"])),
            evidence_lower_bound=_optional_float(data["evidence_lower_bound"]),
            evidence_upper_bound=_optional_float(data["evidence_upper_bound"]),
            posterior_probabilities=_probability_pairs(
                _require_mapping(data["posterior_probabilities"], "branch posterior")
            ),
            posterior_entropy=float(cast(float, data["posterior_entropy"])),
            second_action=LookaheadSecondAction.from_dict(
                _require_mapping(data["second_action"], "second action")
            ),
            terminal_entropy=float(cast(float, data["terminal_entropy"])),
            branch_total_cost=float(cast(float, data["branch_total_cost"])),
            budget_feasible=bool(data["budget_feasible"]),
        )


@dataclass(frozen=True, slots=True)
class LookaheadFirstActionPlan:
    """Complete two-step value calculation for one first candidate."""

    candidate: Candidate
    public_design: PublicExperimentDesign
    action_effect: EligibilityEffect
    first_action_cost: float
    prior_entropy: float
    immediate_information_gain: float
    expected_terminal_entropy: float
    expected_total_information_gain: float
    expected_total_cost: float
    information_gain_per_expected_cost: float
    branches: tuple[LookaheadBranch, ...]
    ranking_reason: str = ""

    def __post_init__(self) -> None:
        if self.public_design.candidate_id != self.candidate.candidate_id:
            raise ReasoningError("First-action candidate and public design do not match.")
        for label, value in (
            ("first-action cost", self.first_action_cost),
            ("prior entropy", self.prior_entropy),
            ("immediate information gain", self.immediate_information_gain),
            ("expected terminal entropy", self.expected_terminal_entropy),
            ("expected total information gain", self.expected_total_information_gain),
            ("expected total cost", self.expected_total_cost),
            ("information gain per expected cost", self.information_gain_per_expected_cost),
        ):
            _validate_non_negative(value, label)
        if not self.branches:
            raise ReasoningError("Every first-action plan must contain at least one branch.")
        probability_total = math.fsum(item.probability for item in self.branches)
        if not math.isclose(
            probability_total,
            1.0,
            rel_tol=0.0,
            abs_tol=PROBABILITY_TOLERANCE,
        ):
            raise ReasoningError("First-action branch probabilities must sum to one.")

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate": _candidate_to_dict(self.candidate),
            "public_design": self.public_design.to_dict(),
            "action_effect": self.action_effect,
            "first_action_cost": self.first_action_cost,
            "prior_entropy": self.prior_entropy,
            "immediate_information_gain": self.immediate_information_gain,
            "expected_terminal_entropy": self.expected_terminal_entropy,
            "expected_total_information_gain": self.expected_total_information_gain,
            "expected_total_cost": self.expected_total_cost,
            "information_gain_per_expected_cost": self.information_gain_per_expected_cost,
            "branches": [item.to_dict() for item in self.branches],
            "ranking_reason": self.ranking_reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> LookaheadFirstActionPlan:
        branch_values = _require_list(data["branches"], "lookahead branches")
        return cls(
            candidate=_candidate_from_dict(_require_mapping(data["candidate"], "candidate")),
            public_design=_public_design_from_dict(
                _require_mapping(data["public_design"], "public design")
            ),
            action_effect=cast(EligibilityEffect, str(data["action_effect"])),
            first_action_cost=float(cast(float, data["first_action_cost"])),
            prior_entropy=float(cast(float, data["prior_entropy"])),
            immediate_information_gain=float(cast(float, data["immediate_information_gain"])),
            expected_terminal_entropy=float(cast(float, data["expected_terminal_entropy"])),
            expected_total_information_gain=float(
                cast(float, data["expected_total_information_gain"])
            ),
            expected_total_cost=float(cast(float, data["expected_total_cost"])),
            information_gain_per_expected_cost=float(
                cast(float, data["information_gain_per_expected_cost"])
            ),
            branches=tuple(
                LookaheadBranch.from_dict(_require_mapping(item, "lookahead branch"))
                for item in branch_values
            ),
            ranking_reason=str(data["ranking_reason"]),
        )


@dataclass(frozen=True, slots=True)
class LookaheadAlternative:
    """Compact score and loss reason for a non-selected first candidate."""

    candidate: Candidate
    action_effect: EligibilityEffect
    comparison_group_id: str
    immediate_information_gain: float
    expected_total_information_gain: float
    expected_total_cost: float
    information_gain_per_expected_cost: float
    ranking_reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate": _candidate_to_dict(self.candidate),
            "action_effect": self.action_effect,
            "comparison_group_id": self.comparison_group_id,
            "immediate_information_gain": self.immediate_information_gain,
            "expected_total_information_gain": self.expected_total_information_gain,
            "expected_total_cost": self.expected_total_cost,
            "information_gain_per_expected_cost": self.information_gain_per_expected_cost,
            "ranking_reason": self.ranking_reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> LookaheadAlternative:
        return cls(
            candidate=_candidate_from_dict(_require_mapping(data["candidate"], "candidate")),
            action_effect=cast(EligibilityEffect, str(data["action_effect"])),
            comparison_group_id=str(data["comparison_group_id"]),
            immediate_information_gain=float(cast(float, data["immediate_information_gain"])),
            expected_total_information_gain=float(
                cast(float, data["expected_total_information_gain"])
            ),
            expected_total_cost=float(cast(float, data["expected_total_cost"])),
            information_gain_per_expected_cost=float(
                cast(float, data["information_gain_per_expected_cost"])
            ),
            ranking_reason=str(data["ranking_reason"]),
        )


@dataclass(frozen=True, slots=True)
class LookaheadPlanTrace:
    """Persistable trace for one real first-action lookahead decision."""

    plan_id: str
    policy: str
    policy_version: str
    created_at: str
    belief_state_id: str
    current_hypothesis_probabilities: tuple[tuple[str, float], ...]
    completed_state_fingerprint: str
    candidate_set_fingerprint: str
    max_cost: float
    selected: LookaheadFirstActionPlan
    alternatives: tuple[LookaheadAlternative, ...]
    tie_breaking_order: tuple[str, ...]
    fallback_reason: str | None
    rationale: str
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.policy != LOOKAHEAD_INFORMATION_GAIN_POLICY:
            raise ReasoningError("Plan trace policy must be lookahead_information_gain.")
        for value in (
            self.plan_id,
            self.created_at,
            self.belief_state_id,
            self.completed_state_fingerprint,
            self.candidate_set_fingerprint,
            self.rationale,
        ):
            if not value.strip():
                raise ReasoningError("Plan trace identifiers and rationale must not be empty.")
        _validate_probability_pairs(
            self.current_hypothesis_probabilities,
            "Current hypothesis",
        )
        _validate_non_negative(self.max_cost, "Plan budget")
        if self.tie_breaking_order != TIE_BREAKING_ORDER:
            raise ReasoningError("Plan trace tie-breaking order is not the approved order.")
        if any(not item.budget_feasible for item in self.selected.branches):
            raise ReasoningError("Selected plan contains a branch that exceeds the budget.")

    @property
    def candidate(self) -> Candidate:
        return self.selected.candidate

    def to_dict(self) -> dict[str, object]:
        selected = self.selected.to_dict()
        selected.pop("branches")
        return {
            "plan_id": self.plan_id,
            "policy": self.policy,
            "policy_version": self.policy_version,
            "created_at": self.created_at,
            "belief_state_id": self.belief_state_id,
            "current_hypothesis_probabilities": dict(self.current_hypothesis_probabilities),
            "completed_state_fingerprint": self.completed_state_fingerprint,
            "candidate_set_fingerprint": self.candidate_set_fingerprint,
            "max_cost": self.max_cost,
            "selected_first_experiment": selected,
            "possible_evidence_branches": [item.to_dict() for item in self.selected.branches],
            "expected_two_step_information_gain": (self.selected.expected_total_information_gain),
            "expected_total_cost": self.selected.expected_total_cost,
            "information_gain_per_expected_cost": (
                self.selected.information_gain_per_expected_cost
            ),
            "losing_first_action_alternatives": [item.to_dict() for item in self.alternatives],
            "tie_breaking_order": list(self.tie_breaking_order),
            "fallback_reason": self.fallback_reason,
            "rationale": self.rationale,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> LookaheadPlanTrace:
        alternative_values = _require_list(
            data["losing_first_action_alternatives"],
            "lookahead alternatives",
        )
        provenance_data = _require_mapping(data["provenance"], "plan provenance")
        details = _require_mapping(provenance_data["details"], "provenance details")
        selected_data = dict(_require_mapping(data["selected_first_experiment"], "selected plan"))
        selected_data["branches"] = data["possible_evidence_branches"]
        fallback_value = data["fallback_reason"]
        return cls(
            plan_id=str(data["plan_id"]),
            policy=str(data["policy"]),
            policy_version=str(data["policy_version"]),
            created_at=str(data["created_at"]),
            belief_state_id=str(data["belief_state_id"]),
            current_hypothesis_probabilities=_probability_pairs(
                _require_mapping(
                    data["current_hypothesis_probabilities"],
                    "current hypothesis probabilities",
                )
            ),
            completed_state_fingerprint=str(data["completed_state_fingerprint"]),
            candidate_set_fingerprint=str(data["candidate_set_fingerprint"]),
            max_cost=float(cast(float, data["max_cost"])),
            selected=LookaheadFirstActionPlan.from_dict(selected_data),
            alternatives=tuple(
                LookaheadAlternative.from_dict(_require_mapping(item, "lookahead alternative"))
                for item in alternative_values
            ),
            tie_breaking_order=tuple(
                str(item)
                for item in _require_list(data["tie_breaking_order"], "tie-breaking order")
            ),
            fallback_reason=None if fallback_value is None else str(fallback_value),
            rationale=str(data["rationale"]),
            provenance=Provenance.create(
                method=str(provenance_data["method"]),
                version=str(provenance_data["version"]),
                details={key: _provenance_value(value) for key, value in details.items()},
            ),
        )


class LookaheadInformationGainPolicy:
    """Choose the first action of an exact, fixed two-step information plan."""

    name = LOOKAHEAD_INFORMATION_GAIN_POLICY
    version = LOOKAHEAD_INFORMATION_GAIN_POLICY_VERSION

    def decide(
        self,
        *,
        candidates: list[Candidate],
        completed_experiments: list[CompletedExperiment],
        hypotheses: tuple[Hypothesis, ...],
        belief_state: BeliefState,
        eligibility: OptimizerEvidenceEligibilityContract,
        cost: Callable[[Candidate], float],
        max_cost: float,
        created_at: str,
    ) -> LookaheadPlanTrace:
        if not math.isfinite(max_cost) or max_cost < 0.0:
            raise ValueError("Lookahead budget must be finite and non-negative.")
        ordered_hypotheses = tuple(sorted(hypotheses, key=lambda item: item.hypothesis_id))
        if tuple(item.hypothesis_id for item in ordered_hypotheses) != belief_state.hypothesis_ids:
            raise ReasoningError("Lookahead hypotheses do not match the belief state.")

        completed_ids = {item.candidate.candidate_id for item in completed_experiments}
        candidate_costs = _validated_candidate_costs(candidates, cost)
        plans: list[LookaheadFirstActionPlan] = []
        for candidate in sorted(candidates, key=lambda item: item.candidate_id):
            if candidate.candidate_id in completed_ids:
                continue
            first_cost = candidate_costs[candidate.candidate_id]
            if first_cost > max_cost:
                continue
            assessment = eligibility.assess_candidate(candidate, completed_experiments)
            if assessment.effect in {
                "completed_candidate",
                "duplicate_arm",
                "already_completed_pair",
                "ambiguous_counterpart",
            }:
                continue
            plans.append(
                self._plan_first_action(
                    candidate=candidate,
                    assessment=assessment,
                    candidates=candidates,
                    completed_experiments=completed_experiments,
                    hypotheses=ordered_hypotheses,
                    belief_state=belief_state,
                    eligibility=eligibility,
                    candidate_costs=candidate_costs,
                    max_cost=max_cost,
                )
            )
        if not plans:
            raise ValueError("No feasible first candidates remain within the lookahead budget.")

        ordered = sorted(plans, key=_first_action_sort_key)
        ranked = _add_first_action_ranking_reasons(ordered)
        selected = ranked[0]
        fallback_reason = None
        if selected.expected_total_information_gain <= POSITIVE_INFORMATION_TOLERANCE:
            fallback_reason = (
                "No feasible two-step plan has positive expected entropy reduction; selected "
                "the lowest-cost feasible first candidate."
            )
        alternatives = tuple(_alternative_from_plan(item) for item in ranked[1:])
        completed_fingerprint = _completed_state_fingerprint(
            completed_experiments,
            eligibility,
        )
        candidate_fingerprint = _candidate_set_fingerprint(
            candidates,
            candidate_costs,
            eligibility,
        )
        plan_id = _plan_id(
            belief_state_id=belief_state.belief_state_id,
            max_cost=max_cost,
            completed_state_fingerprint=completed_fingerprint,
            candidate_set_fingerprint=candidate_fingerprint,
            ranked=ranked,
        )
        rationale = _plan_rationale(selected, max_cost, fallback_reason)
        provenance = Provenance.create(
            method="two-step-receding-horizon-experiment-selection",
            version=self.version,
            details={
                "belief_state_id": belief_state.belief_state_id,
                "candidate_count_scored": len(ranked),
                "candidate_set_fingerprint": candidate_fingerprint,
                "completed_experiment_count": len(completed_experiments),
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
            policy=self.name,
            policy_version=self.version,
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

    def _plan_first_action(
        self,
        *,
        candidate: Candidate,
        assessment: EvidenceEligibilityAssessment,
        candidates: list[Candidate],
        completed_experiments: list[CompletedExperiment],
        hypotheses: tuple[Hypothesis, ...],
        belief_state: BeliefState,
        eligibility: OptimizerEvidenceEligibilityContract,
        candidate_costs: dict[str, float],
        max_cost: float,
    ) -> LookaheadFirstActionPlan:
        first_cost = candidate_costs[candidate.candidate_id]
        simulated_first = CompletedExperiment(
            record_id=0,
            candidate=candidate,
            observed_value=0.0,
            created_at="SIMULATED-NOT-PERSISTED",
        )
        simulated_completed = [*completed_experiments, simulated_first]
        if assessment.effect == "completes_pair":
            first_distribution = discretized_gaussian_evidence_outcomes(
                hypotheses,
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
            self._plan_branch(
                outcome=outcome,
                first_cost=first_cost,
                candidates=candidates,
                completed_experiments=simulated_completed,
                hypotheses=hypotheses,
                eligibility=eligibility,
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
        expected_total_cost = math.fsum(
            item.probability * item.branch_total_cost for item in branches
        )
        ratio = _information_per_cost(expected_total_information_gain, expected_total_cost)
        return LookaheadFirstActionPlan(
            candidate=candidate,
            public_design=eligibility.design_for(candidate),
            action_effect=assessment.effect,
            first_action_cost=first_cost,
            prior_entropy=prior_entropy,
            immediate_information_gain=immediate_information_gain,
            expected_terminal_entropy=expected_terminal_entropy,
            expected_total_information_gain=expected_total_information_gain,
            expected_total_cost=expected_total_cost,
            information_gain_per_expected_cost=ratio,
            branches=branches,
        )

    def _plan_branch(
        self,
        *,
        outcome: EvidenceOutcomeBranch,
        first_cost: float,
        candidates: list[Candidate],
        completed_experiments: list[CompletedExperiment],
        hypotheses: tuple[Hypothesis, ...],
        eligibility: OptimizerEvidenceEligibilityContract,
        candidate_costs: dict[str, float],
        max_cost: float,
    ) -> LookaheadBranch:
        second = _best_second_action(
            candidates=candidates,
            completed_experiments=completed_experiments,
            hypotheses=hypotheses,
            posterior_probabilities=outcome.posterior_probabilities,
            eligibility=eligibility,
            candidate_costs=candidate_costs,
            remaining_budget=max_cost - first_cost,
        )
        terminal_entropy = max(
            0.0,
            outcome.posterior_entropy - second.expected_information_gain,
        )
        branch_total_cost = first_cost + second.estimated_cost
        return LookaheadBranch(
            branch_id=outcome.branch_id,
            label=outcome.label,
            probability=outcome.predictive_probability,
            evidence_lower_bound=outcome.lower_bound,
            evidence_upper_bound=outcome.upper_bound,
            posterior_probabilities=tuple(
                zip(
                    tuple(item.hypothesis_id for item in hypotheses),
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


def _best_second_action(
    *,
    candidates: list[Candidate],
    completed_experiments: list[CompletedExperiment],
    hypotheses: tuple[Hypothesis, ...],
    posterior_probabilities: tuple[float, ...],
    eligibility: OptimizerEvidenceEligibilityContract,
    candidate_costs: dict[str, float],
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
    distribution = discretized_gaussian_evidence_outcomes(
        hypotheses,
        posterior_probabilities,
    )
    for candidate in sorted(candidates, key=lambda item: item.candidate_id):
        if candidate.candidate_id in completed_ids:
            continue
        candidate_cost = candidate_costs[candidate.candidate_id]
        if candidate_cost > remaining_budget + POSITIVE_INFORMATION_TOLERANCE:
            continue
        assessment = eligibility.assess_candidate(candidate, completed_experiments)
        if assessment.effect != "completes_pair":
            continue
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


def _validated_candidate_costs(
    candidates: list[Candidate], cost: Callable[[Candidate], float]
) -> dict[str, float]:
    result: dict[str, float] = {}
    for candidate in candidates:
        candidate_cost = cost(candidate)
        if not math.isfinite(candidate_cost) or candidate_cost < 0.0:
            raise ValueError(f"Candidate {candidate.candidate_id} has invalid cost.")
        result[candidate.candidate_id] = candidate_cost
    return result


def _first_action_sort_key(plan: LookaheadFirstActionPlan) -> tuple[float, float, float, str]:
    return (
        -plan.expected_total_information_gain,
        plan.expected_total_cost,
        -plan.information_gain_per_expected_cost,
        plan.candidate.candidate_id,
    )


def _second_action_sort_key(
    action: LookaheadSecondAction,
) -> tuple[float, float, float, str]:
    return (
        -action.expected_information_gain,
        action.estimated_cost,
        -action.information_gain_per_cost,
        action.candidate_id,
    )


def _add_first_action_ranking_reasons(
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


def _plan_rationale(
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
    candidate_costs: dict[str, float],
    eligibility: OptimizerEvidenceEligibilityContract,
) -> str:
    payload = [
        {
            "candidate": _candidate_to_dict(candidate),
            "cost": candidate_costs[candidate.candidate_id],
            "public_design": eligibility.design_for(candidate).to_dict(),
        }
        for candidate in sorted(candidates, key=lambda item: item.candidate_id)
    ]
    return _stable_id("candidate-set", payload)


def _completed_state_fingerprint(
    completed_experiments: list[CompletedExperiment],
    eligibility: OptimizerEvidenceEligibilityContract,
) -> str:
    payload = [
        {
            "candidate_id": item.candidate.candidate_id,
            "experiment_id": item.record_id,
            "public_design": eligibility.design_for(item.candidate).to_dict(),
        }
        for item in completed_experiments
    ]
    return _stable_id("completed-state", payload)


def _plan_id(
    *,
    belief_state_id: str,
    max_cost: float,
    completed_state_fingerprint: str,
    candidate_set_fingerprint: str,
    ranked: tuple[LookaheadFirstActionPlan, ...],
) -> str:
    payload = {
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
    }
    return _stable_id("plan", payload)


def _information_per_cost(information_gain: float, cost: float) -> float:
    if cost <= 0.0:
        return 0.0
    return information_gain / cost


def _entropy(probabilities: tuple[float, ...]) -> float:
    return -math.fsum(value * math.log2(value) for value in probabilities if value > 0.0)


def _stable_id(prefix: str, payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _candidate_to_dict(candidate: Candidate) -> dict[str, object]:
    return {"candidate_id": candidate.candidate_id, "params": candidate.params()}


def _candidate_from_dict(data: Mapping[str, object]) -> Candidate:
    params = _require_mapping(data["params"], "candidate params")
    return Candidate(
        candidate_id=str(data["candidate_id"]),
        learning_rate=float(cast(float, params["learning_rate"])),
        regularization=float(cast(float, params["regularization"])),
        model_width=int(cast(int, params["model_width"])),
        optimizer=str(params["optimizer"]),
    )


def _public_design_from_dict(data: Mapping[str, object]) -> PublicExperimentDesign:
    controls = _require_mapping(data["controlled_variables"], "controlled variables")
    controlled_variables = tuple(
        sorted((str(name), _control_value(value)) for name, value in controls.items())
    )
    return PublicExperimentDesign(
        candidate_id=str(data["candidate_id"]),
        experiment_family=str(data["experiment_family"]),
        comparison_group_id=str(data["comparison_group_id"]),
        controlled_variables=controlled_variables,
        intervention_variable=str(data["intervention_variable"]),
        intervention_arm=str(data["intervention_arm"]),
    )


def _control_value(value: object) -> str | int | float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ReasoningError("Controlled-variable values must be strings or numbers.")
    return value


def _probability_pairs(data: Mapping[str, object]) -> tuple[tuple[str, float], ...]:
    return tuple(sorted((str(key), float(cast(float, value))) for key, value in data.items()))


def _validate_probability_pairs(probabilities: tuple[tuple[str, float], ...], label: str) -> None:
    hypothesis_ids = tuple(item[0] for item in probabilities)
    if not probabilities or hypothesis_ids != tuple(sorted(set(hypothesis_ids))):
        raise ReasoningError(f"{label} probabilities require unique, sorted hypothesis IDs.")
    values = tuple(item[1] for item in probabilities)
    if any(not math.isfinite(value) or value < 0.0 for value in values):
        raise ReasoningError(f"{label} probabilities must be finite and non-negative.")
    if not math.isclose(
        math.fsum(values),
        1.0,
        rel_tol=0.0,
        abs_tol=PROBABILITY_TOLERANCE,
    ):
        raise ReasoningError(f"{label} probabilities must sum to one.")


def _validate_non_negative(value: float, label: str) -> None:
    if not math.isfinite(value) or value < 0.0:
        raise ReasoningError(f"{label} must be finite and non-negative.")


def _require_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ReasoningError(f"{label} must be a JSON object.")
    return cast(dict[str, object], value)


def _require_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ReasoningError(f"{label} must be a JSON list.")
    return cast(list[object], value)


def _optional_float(value: object) -> float | None:
    return None if value is None else float(cast(float, value))


def _provenance_value(value: object) -> ProvenanceValue:
    if value is not None and not isinstance(value, (str, int, float, bool)):
        raise ReasoningError("Unsupported plan provenance value.")
    return value
