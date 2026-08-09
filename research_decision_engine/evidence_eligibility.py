"""Public structural eligibility for matched optimizer-effect evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from research_decision_engine.reasoning import ReasoningError
from research_decision_engine.types import Candidate, CompletedExperiment

OPTIMIZER_EFFECT_FAMILY = "optimizer-effect"
OPTIMIZER_INTERVENTION = "optimizer"
OPTIMIZER_ARMS = ("adam", "sgd")

type ControlValue = str | int | float
type ControlledFingerprint = tuple[tuple[str, ControlValue], ...]
type ComparisonKey = tuple[str, str, ControlledFingerprint, str]
type EligibilityEffect = Literal[
    "opens_pair",
    "completes_pair",
    "ineligible",
    "completed_candidate",
    "duplicate_arm",
    "already_completed_pair",
    "ambiguous_counterpart",
]


@dataclass(frozen=True, slots=True)
class PublicExperimentDesign:
    """Planner-visible experiment structure with no outcome or benchmark truth."""

    candidate_id: str
    experiment_family: str
    comparison_group_id: str
    controlled_variables: ControlledFingerprint
    intervention_variable: str
    intervention_arm: str

    def __post_init__(self) -> None:
        for label, value in (
            ("candidate ID", self.candidate_id),
            ("experiment family", self.experiment_family),
            ("comparison-group ID", self.comparison_group_id),
            ("intervention variable", self.intervention_variable),
            ("intervention arm", self.intervention_arm),
        ):
            if not value.strip():
                raise ReasoningError(f"Public design {label} must not be empty.")
        names = tuple(name for name, _ in self.controlled_variables)
        if names != tuple(sorted(set(names))):
            raise ReasoningError("Controlled-variable names must be unique and sorted.")

    @property
    def comparison_key(self) -> ComparisonKey:
        return (
            self.experiment_family,
            self.comparison_group_id,
            self.controlled_variables,
            self.intervention_variable,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "experiment_family": self.experiment_family,
            "comparison_group_id": self.comparison_group_id,
            "controlled_variables": dict(self.controlled_variables),
            "intervention_variable": self.intervention_variable,
            "intervention_arm": self.intervention_arm,
        }


@dataclass(frozen=True, slots=True)
class EvidenceEligibilityAssessment:
    """Structural effect of one candidate relative to completed experiments."""

    candidate_id: str
    effect: EligibilityEffect
    evidence_eligible: bool
    comparison_group_id: str
    counterpart_candidate_id: str | None
    counterpart_experiment_id: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class MatchedExperimentPair:
    """One unapplied, structurally valid pair of successful experiments."""

    comparison_group_id: str
    sgd_experiment: CompletedExperiment
    adam_experiment: CompletedExperiment

    @property
    def source_experiment_ids(self) -> tuple[int, int]:
        first, second = sorted((self.sgd_experiment.record_id, self.adam_experiment.record_id))
        return first, second


@dataclass(frozen=True, slots=True)
class OptimizerEvidenceEligibilityContract:
    """Determine optimizer evidence eligibility from public design structure only."""

    designs: tuple[PublicExperimentDesign, ...]

    def __post_init__(self) -> None:
        candidate_ids = tuple(item.candidate_id for item in self.designs)
        if candidate_ids != tuple(sorted(set(candidate_ids))):
            raise ReasoningError("Eligibility designs must have unique, sorted candidate IDs.")

    @classmethod
    def from_candidates(
        cls,
        candidates: Iterable[Candidate],
        *,
        public_designs: Iterable[PublicExperimentDesign] = (),
    ) -> OptimizerEvidenceEligibilityContract:
        candidate_by_id = {item.candidate_id: item for item in candidates}
        overrides = {item.candidate_id: item for item in public_designs}
        unknown = set(overrides).difference(candidate_by_id)
        if unknown:
            raise ReasoningError(
                "Public designs reference unknown candidates: " + ", ".join(sorted(unknown))
            )
        designs = tuple(
            sorted(
                (
                    overrides.get(candidate_id, default_public_design(candidate))
                    for candidate_id, candidate in candidate_by_id.items()
                ),
                key=lambda item: item.candidate_id,
            )
        )
        return cls(designs=designs)

    def design_for(self, candidate: Candidate) -> PublicExperimentDesign:
        for design in self.designs:
            if design.candidate_id == candidate.candidate_id:
                return design
        raise ReasoningError(f"No public design is registered for {candidate.candidate_id}.")

    def assess_candidate(
        self,
        candidate: Candidate,
        completed_experiments: Sequence[CompletedExperiment],
    ) -> EvidenceEligibilityAssessment:
        design = self.design_for(candidate)
        if any(
            item.candidate.candidate_id == candidate.candidate_id for item in completed_experiments
        ):
            return self._assessment(
                design,
                effect="completed_candidate",
                eligible=False,
                reason="This exact candidate has already completed successfully.",
            )
        if not self._is_optimizer_effect_design(design):
            return self._assessment(
                design,
                effect="ineligible",
                eligible=False,
                reason=(
                    "The public experiment family, intervention variable, or intervention arm "
                    "is not eligible for optimizer-effect evidence."
                ),
            )

        related = [
            item
            for item in completed_experiments
            if self._same_comparison(design, self.design_for(item.candidate))
        ]
        completed_arms = {self.design_for(item.candidate).intervention_arm for item in related}
        if completed_arms == set(OPTIMIZER_ARMS):
            return self._assessment(
                design,
                effect="already_completed_pair",
                eligible=False,
                reason="This public comparison group already has both optimizer arms.",
            )

        same_arm = [
            item
            for item in related
            if self.design_for(item.candidate).intervention_arm == design.intervention_arm
        ]
        if same_arm:
            return self._assessment(
                design,
                effect="duplicate_arm",
                eligible=False,
                reason="The same intervention arm already completed in this comparison group.",
            )

        complementary_arm = "sgd" if design.intervention_arm == "adam" else "adam"
        counterparts = [
            item
            for item in related
            if self.design_for(item.candidate).intervention_arm == complementary_arm
        ]
        if len(counterparts) > 1:
            return self._assessment(
                design,
                effect="ambiguous_counterpart",
                eligible=False,
                reason="More than one completed complementary arm makes the pair ambiguous.",
            )
        if len(counterparts) == 1:
            counterpart = counterparts[0]
            return self._assessment(
                design,
                effect="completes_pair",
                eligible=True,
                counterpart_candidate_id=counterpart.candidate.candidate_id,
                counterpart_experiment_id=counterpart.record_id,
                reason=(
                    "The candidate has identical public controls and the complementary optimizer "
                    "arm, so it completes one new matched pair."
                ),
            )
        return self._assessment(
            design,
            effect="opens_pair",
            eligible=True,
            reason=(
                "The candidate is structurally eligible but no completed complementary arm "
                "exists, so it opens a matched pair."
            ),
        )

    def valid_unapplied_pairs(
        self,
        completed_experiments: Sequence[CompletedExperiment],
        *,
        applied_source_pairs: frozenset[tuple[int, ...]] = frozenset(),
    ) -> tuple[MatchedExperimentPair, ...]:
        grouped: dict[ComparisonKey, list[CompletedExperiment]] = {}
        for experiment in completed_experiments:
            design = self.design_for(experiment.candidate)
            if self._is_optimizer_effect_design(design):
                grouped.setdefault(design.comparison_key, []).append(experiment)

        pairs: list[MatchedExperimentPair] = []
        for comparison_key in sorted(grouped, key=repr):
            experiments = grouped[comparison_key]
            sgd = [
                item
                for item in experiments
                if self.design_for(item.candidate).intervention_arm == "sgd"
            ]
            adam = [
                item
                for item in experiments
                if self.design_for(item.candidate).intervention_arm == "adam"
            ]
            if len(sgd) != 1 or len(adam) != 1:
                continue
            pair = MatchedExperimentPair(
                comparison_group_id=comparison_key[1],
                sgd_experiment=sgd[0],
                adam_experiment=adam[0],
            )
            if pair.source_experiment_ids not in applied_source_pairs:
                pairs.append(pair)
        return tuple(pairs)

    def to_dict(self) -> dict[str, object]:
        return {
            "contract": "matched-optimizer-public-structure/v1",
            "designs": [item.to_dict() for item in self.designs],
        }

    def _assessment(
        self,
        design: PublicExperimentDesign,
        *,
        effect: EligibilityEffect,
        eligible: bool,
        reason: str,
        counterpart_candidate_id: str | None = None,
        counterpart_experiment_id: int | None = None,
    ) -> EvidenceEligibilityAssessment:
        return EvidenceEligibilityAssessment(
            candidate_id=design.candidate_id,
            effect=effect,
            evidence_eligible=eligible,
            comparison_group_id=design.comparison_group_id,
            counterpart_candidate_id=counterpart_candidate_id,
            counterpart_experiment_id=counterpart_experiment_id,
            reason=reason,
        )

    def _is_optimizer_effect_design(self, design: PublicExperimentDesign) -> bool:
        return (
            design.experiment_family == OPTIMIZER_EFFECT_FAMILY
            and design.intervention_variable == OPTIMIZER_INTERVENTION
            and design.intervention_arm in OPTIMIZER_ARMS
        )

    def _same_comparison(self, left: PublicExperimentDesign, right: PublicExperimentDesign) -> bool:
        return (
            self._is_optimizer_effect_design(right)
            and left.comparison_key == right.comparison_key
            and left.controlled_variables == right.controlled_variables
        )


def default_public_design(
    candidate: Candidate,
    *,
    experiment_family: str = OPTIMIZER_EFFECT_FAMILY,
    comparison_group_id: str | None = None,
) -> PublicExperimentDesign:
    """Construct the public optimizer design visible for a candidate."""

    controls: ControlledFingerprint = (
        ("learning_rate", candidate.learning_rate),
        ("model_width", candidate.model_width),
        ("regularization", candidate.regularization),
    )
    group_id = comparison_group_id or _comparison_group_id(experiment_family, controls)
    return PublicExperimentDesign(
        candidate_id=candidate.candidate_id,
        experiment_family=experiment_family,
        comparison_group_id=group_id,
        controlled_variables=controls,
        intervention_variable=OPTIMIZER_INTERVENTION,
        intervention_arm=candidate.optimizer,
    )


def _comparison_group_id(experiment_family: str, controls: ControlledFingerprint) -> str:
    payload = json.dumps(
        {"experiment_family": experiment_family, "controls": dict(controls)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"comparison-{hashlib.sha256(payload).hexdigest()[:16]}"
