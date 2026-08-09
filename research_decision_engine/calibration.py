"""Deterministic calibration-only matched optimizer replications."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from research_decision_engine.evidence_eligibility import (
    OPTIMIZER_ARMS,
    OPTIMIZER_EFFECT_FAMILY,
    OPTIMIZER_INTERVENTION,
    ControlledFingerprint,
    PublicExperimentDesign,
)
from research_decision_engine.reasoning import Provenance, ReasoningError
from research_decision_engine.types import Candidate

CALIBRATION_PREFIX_VERSION = "optimizer-effect-calibration-prefix/v1"
CALIBRATION_REPLICATION_VERSION = "matched-calibration-replication/v1"
CALIBRATION_EFFECT_VERSION = "calibration-matched-effect/v1"
CALIBRATION_NAMESPACE = "calibration"
DECISION_NAMESPACE = "decision"
CALIBRATION_EFFECT_COUNT = 5


class DuplicateCalibrationConsumptionError(ReasoningError):
    """Raised when a calibration arm or pair is consumed more than once."""


@dataclass(frozen=True, slots=True)
class CalibrationPairObservation:
    """Truth-free observations and deterministic seed keys returned by a hidden world."""

    adam_observed_value: float
    sgd_observed_value: float
    shared_key: str
    adam_noise_key: str
    sgd_noise_key: str

    def __post_init__(self) -> None:
        for observation in (self.adam_observed_value, self.sgd_observed_value):
            if not math.isfinite(observation):
                raise ReasoningError("Calibration observations must be finite.")
        for key in (self.shared_key, self.adam_noise_key, self.sgd_noise_key):
            if not key.strip():
                raise ReasoningError("Calibration random keys must not be empty.")
        if self.adam_noise_key == self.sgd_noise_key:
            raise ReasoningError("Calibration arm-noise keys must be distinct.")


class CalibrationPairObserver(Protocol):
    """Observe one calibration pair without exposing hidden world configuration."""

    def __call__(
        self,
        *,
        sgd_candidate: Candidate,
        adam_candidate: Candidate,
        replication_id: str,
        replication_seed: str,
    ) -> CalibrationPairObservation:
        """Return paired observations generated from explicit public identities."""


@dataclass(frozen=True, slots=True)
class CalibrationGroup:
    """One public comparison group with a deterministic five-effect prefix."""

    calibration_group_id: str
    world_id: str
    evaluation_seed: int
    comparison_group_id: str
    controlled_variables: ControlledFingerprint
    intervention_variable: str
    created_at: str
    provenance: Provenance

    def __post_init__(self) -> None:
        for value in (
            self.calibration_group_id,
            self.world_id,
            self.comparison_group_id,
            self.intervention_variable,
            self.created_at,
        ):
            if not value.strip():
                raise ReasoningError("Calibration group identifiers must not be empty.")

    def to_dict(self) -> dict[str, object]:
        return {
            "calibration_group_id": self.calibration_group_id,
            "world_id": self.world_id,
            "evaluation_seed": self.evaluation_seed,
            "comparison_group_id": self.comparison_group_id,
            "controlled_variables": dict(self.controlled_variables),
            "intervention_variable": self.intervention_variable,
            "created_at": self.created_at,
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class CalibrationArm:
    """One successful arm in a calibration-only matched replication."""

    calibration_arm_id: str
    calibration_group_id: str
    replication_id: str
    replication_seed: str
    candidate_id: str
    intervention_arm: str
    controlled_variables: ControlledFingerprint
    observed_value: float
    cost: float
    shared_key: str
    arm_noise_key: str
    successful: bool
    created_at: str
    provenance: Provenance

    def __post_init__(self) -> None:
        for value in (
            self.calibration_arm_id,
            self.calibration_group_id,
            self.replication_id,
            self.replication_seed,
            self.candidate_id,
            self.intervention_arm,
            self.shared_key,
            self.arm_noise_key,
            self.created_at,
        ):
            if not value.strip():
                raise ReasoningError("Calibration arm identifiers must not be empty.")
        if self.intervention_arm not in OPTIMIZER_ARMS:
            raise ReasoningError("Calibration arm must be adam or sgd.")
        if not math.isfinite(self.observed_value):
            raise ReasoningError("Calibration arm observation must be finite.")
        if not math.isfinite(self.cost) or self.cost < 0.0:
            raise ReasoningError("Calibration arm cost must be finite and non-negative.")
        if not self.successful:
            raise ReasoningError("Only successful calibration arms may be recorded.")

    def to_dict(self) -> dict[str, object]:
        return {
            "calibration_arm_id": self.calibration_arm_id,
            "calibration_group_id": self.calibration_group_id,
            "replication_id": self.replication_id,
            "replication_seed": self.replication_seed,
            "candidate_id": self.candidate_id,
            "intervention_arm": self.intervention_arm,
            "controlled_variables": dict(self.controlled_variables),
            "observed_value": self.observed_value,
            "cost": self.cost,
            "shared_key": self.shared_key,
            "arm_noise_key": self.arm_noise_key,
            "successful": self.successful,
            "created_at": self.created_at,
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class CalibrationReplication:
    """A public calibration replication containing complementary optimizer arms."""

    replication_id: str
    calibration_group_id: str
    replication_index: int
    replication_seed: str
    adam_arm_id: str
    sgd_arm_id: str
    created_at: str
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.replication_index < 0:
            raise ReasoningError("Calibration replication index must be non-negative.")
        values = (
            self.replication_id,
            self.calibration_group_id,
            self.replication_seed,
            self.adam_arm_id,
            self.sgd_arm_id,
            self.created_at,
        )
        if any(not value.strip() for value in values):
            raise ReasoningError("Calibration replication identifiers must not be empty.")
        if self.adam_arm_id == self.sgd_arm_id:
            raise ReasoningError("Calibration replication arms must be distinct.")

    def to_dict(self) -> dict[str, object]:
        return {
            "replication_id": self.replication_id,
            "calibration_group_id": self.calibration_group_id,
            "replication_index": self.replication_index,
            "replication_seed": self.replication_seed,
            "adam_arm_id": self.adam_arm_id,
            "sgd_arm_id": self.sgd_arm_id,
            "created_at": self.created_at,
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class CalibrationMatchedEffect:
    """A matched effect used for sigma estimation and never as scientific evidence."""

    calibration_effect_id: str
    calibration_group_id: str
    comparison_group_id: str
    replication_id: str
    replication_seed: str
    adam_arm_id: str
    sgd_arm_id: str
    observed_effect: float
    available_sequence: int
    created_at: str
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.available_sequence != 0:
            raise ReasoningError(
                "Calibration effects must be available before decision sequence 1."
            )
        if not math.isfinite(self.observed_effect):
            raise ReasoningError("Calibration matched effect must be finite.")
        if self.adam_arm_id == self.sgd_arm_id:
            raise ReasoningError("Calibration matched effect requires two distinct arms.")

    def to_dict(self) -> dict[str, object]:
        return {
            "calibration_effect_id": self.calibration_effect_id,
            "calibration_group_id": self.calibration_group_id,
            "comparison_group_id": self.comparison_group_id,
            "replication_id": self.replication_id,
            "replication_seed": self.replication_seed,
            "adam_arm_id": self.adam_arm_id,
            "sgd_arm_id": self.sgd_arm_id,
            "observed_effect": self.observed_effect,
            "available_sequence": self.available_sequence,
            "created_at": self.created_at,
            "provenance": self.provenance.to_dict(),
            "scientific_evidence": False,
        }


@dataclass(frozen=True, slots=True)
class CalibrationPrefix:
    """Complete calibration-only history shared across paired benchmark conditions."""

    prefix_id: str
    world_id: str
    evaluation_seed: int
    groups: tuple[CalibrationGroup, ...]
    replications: tuple[CalibrationReplication, ...]
    arms: tuple[CalibrationArm, ...]
    matched_effects: tuple[CalibrationMatchedEffect, ...]
    calibration_cost: float
    created_at: str
    provenance: Provenance

    def __post_init__(self) -> None:
        if not self.prefix_id.strip() or not self.created_at.strip():
            raise ReasoningError("Calibration prefix identifiers must not be empty.")
        if not math.isfinite(self.calibration_cost) or self.calibration_cost < 0.0:
            raise ReasoningError("Calibration prefix cost must be finite and non-negative.")
        for group in self.groups:
            group_effects = tuple(
                item
                for item in self.matched_effects
                if item.calibration_group_id == group.calibration_group_id
            )
            if len(group_effects) != CALIBRATION_EFFECT_COUNT:
                raise ReasoningError("Every calibration group must contain exactly five effects.")
            if len({item.replication_id for item in group_effects}) != CALIBRATION_EFFECT_COUNT:
                raise ReasoningError("Calibration replication IDs must be distinct.")
            if len({item.replication_seed for item in group_effects}) != CALIBRATION_EFFECT_COUNT:
                raise ReasoningError("Calibration replication seeds must be distinct.")

    def effects_for_group(self, comparison_group_id: str) -> tuple[CalibrationMatchedEffect, ...]:
        return tuple(
            item for item in self.matched_effects if item.comparison_group_id == comparison_group_id
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "prefix_id": self.prefix_id,
            "world_id": self.world_id,
            "evaluation_seed": self.evaluation_seed,
            "groups": [item.to_dict() for item in self.groups],
            "replications": [item.to_dict() for item in self.replications],
            "arms": [item.to_dict() for item in self.arms],
            "matched_effects": [item.to_dict() for item in self.matched_effects],
            "calibration_cost": self.calibration_cost,
            "created_at": self.created_at,
            "provenance": self.provenance.to_dict(),
        }


class CalibrationReplicationContract:
    """Validate and consume calibration matched pairs exactly once."""

    def __init__(self) -> None:
        self._consumed_arm_ids: set[str] = set()
        self._consumed_replication_ids: set[str] = set()

    def consume(
        self,
        *,
        group: CalibrationGroup,
        replication_id: str,
        replication_seed: str,
        adam_arm: CalibrationArm,
        sgd_arm: CalibrationArm,
        created_at: str,
    ) -> CalibrationMatchedEffect:
        if replication_id in self._consumed_replication_ids:
            raise DuplicateCalibrationConsumptionError(
                f"Calibration replication {replication_id} has already been consumed."
            )
        source_arm_ids = {adam_arm.calibration_arm_id, sgd_arm.calibration_arm_id}
        duplicate_arms = source_arm_ids.intersection(self._consumed_arm_ids)
        if duplicate_arms:
            raise DuplicateCalibrationConsumptionError(
                "Calibration arms have already been consumed: " + ", ".join(sorted(duplicate_arms))
            )
        if adam_arm.intervention_arm != "adam" or sgd_arm.intervention_arm != "sgd":
            raise ReasoningError("Calibration replication requires complementary optimizer arms.")
        for arm in (adam_arm, sgd_arm):
            if arm.calibration_group_id != group.calibration_group_id:
                raise ReasoningError("Calibration arms must belong to the same public group.")
            if arm.replication_id != replication_id or arm.replication_seed != replication_seed:
                raise ReasoningError("Calibration arms must share replication identity and seed.")
            if arm.controlled_variables != group.controlled_variables:
                raise ReasoningError("Calibration arms must have identical controlled variables.")
            if not arm.successful:
                raise ReasoningError("Calibration matched effects require successful arms.")
        if adam_arm.shared_key != sgd_arm.shared_key:
            raise ReasoningError("Calibration arms must share common stochastic-factor key.")
        if adam_arm.arm_noise_key == sgd_arm.arm_noise_key:
            raise ReasoningError("Calibration arm-specific noise keys must be independent.")

        effect_id = _stable_id(
            "calibration-effect",
            {
                "adam_arm_id": adam_arm.calibration_arm_id,
                "replication_id": replication_id,
                "sgd_arm_id": sgd_arm.calibration_arm_id,
                "version": CALIBRATION_EFFECT_VERSION,
            },
        )
        observed_effect = round(adam_arm.observed_value - sgd_arm.observed_value, 12)
        provenance = Provenance.create(
            method="calibration-matched-effect",
            version=CALIBRATION_EFFECT_VERSION,
            details={
                "adam_arm_id": adam_arm.calibration_arm_id,
                "comparison_formula": "adam_observed_value - sgd_observed_value",
                "comparison_group_id": group.comparison_group_id,
                "namespace": CALIBRATION_NAMESPACE,
                "replication_id": replication_id,
                "replication_seed": replication_seed,
                "scientific_evidence": False,
                "sgd_arm_id": sgd_arm.calibration_arm_id,
                "source_status": "completed_successfully",
            },
        )
        self._consumed_arm_ids.update(source_arm_ids)
        self._consumed_replication_ids.add(replication_id)
        return CalibrationMatchedEffect(
            calibration_effect_id=effect_id,
            calibration_group_id=group.calibration_group_id,
            comparison_group_id=group.comparison_group_id,
            replication_id=replication_id,
            replication_seed=replication_seed,
            adam_arm_id=adam_arm.calibration_arm_id,
            sgd_arm_id=sgd_arm.calibration_arm_id,
            observed_effect=observed_effect,
            available_sequence=0,
            created_at=created_at,
            provenance=provenance,
        )


def build_calibration_prefix(
    *,
    world_id: str,
    evaluation_seed: int,
    designs: tuple[PublicExperimentDesign, ...],
    candidates: Mapping[str, Candidate],
    cost: Callable[[Candidate], float],
    observe_pair: CalibrationPairObserver,
    created_at: str,
) -> CalibrationPrefix:
    """Build exactly five truth-free calibration effects for every optimizer group."""

    grouped: dict[tuple[object, ...], list[PublicExperimentDesign]] = {}
    for design in designs:
        if (
            design.experiment_family == OPTIMIZER_EFFECT_FAMILY
            and design.intervention_variable == OPTIMIZER_INTERVENTION
            and design.intervention_arm in OPTIMIZER_ARMS
        ):
            grouped.setdefault(design.comparison_key, []).append(design)
    if not grouped:
        raise ReasoningError("Calibration prefix requires at least one optimizer comparison group.")

    groups: list[CalibrationGroup] = []
    replications: list[CalibrationReplication] = []
    arms: list[CalibrationArm] = []
    effects: list[CalibrationMatchedEffect] = []
    contract = CalibrationReplicationContract()

    for group_index, comparison_key in enumerate(sorted(grouped, key=repr)):
        group_designs = grouped[comparison_key]
        by_arm = {item.intervention_arm: item for item in group_designs}
        if set(by_arm) != set(OPTIMIZER_ARMS) or len(group_designs) != 2:
            raise ReasoningError("Calibration groups require exactly one public design per arm.")
        sgd_design = by_arm["sgd"]
        adam_design = by_arm["adam"]
        if sgd_design.controlled_variables != adam_design.controlled_variables:
            raise ReasoningError("Calibration group controls must be identical.")
        group_id = _stable_id(
            "calibration-group",
            {
                "comparison_group_id": sgd_design.comparison_group_id,
                "evaluation_seed": evaluation_seed,
                "version": CALIBRATION_PREFIX_VERSION,
                "world_id": world_id,
            },
        )
        group = CalibrationGroup(
            calibration_group_id=group_id,
            world_id=world_id,
            evaluation_seed=evaluation_seed,
            comparison_group_id=sgd_design.comparison_group_id,
            controlled_variables=sgd_design.controlled_variables,
            intervention_variable=sgd_design.intervention_variable,
            created_at=f"{created_at}#calibration-group-{group_index:03d}",
            provenance=Provenance.create(
                method="calibration-group-registration",
                version=CALIBRATION_PREFIX_VERSION,
                details={
                    "comparison_group_id": sgd_design.comparison_group_id,
                    "evaluation_seed": evaluation_seed,
                    "hidden_truth_available": False,
                    "namespace": CALIBRATION_NAMESPACE,
                    "world_id": world_id,
                },
            ),
        )
        groups.append(group)

        for replication_index in range(CALIBRATION_EFFECT_COUNT):
            replication_id = (
                f"calibration:{world_id}:{evaluation_seed}:"
                f"{sgd_design.comparison_group_id}:{replication_index:02d}"
            )
            replication_seed = _stable_seed(
                world_id=world_id,
                evaluation_seed=evaluation_seed,
                comparison_group_id=sgd_design.comparison_group_id,
                replication_index=replication_index,
            )
            observation = observe_pair(
                sgd_candidate=candidates[sgd_design.candidate_id],
                adam_candidate=candidates[adam_design.candidate_id],
                replication_id=replication_id,
                replication_seed=replication_seed,
            )
            arm_created_at = f"{created_at}#calibration-{group_index:03d}-{replication_index:03d}"
            sgd_arm = _calibration_arm(
                group=group,
                design=sgd_design,
                candidate=candidates[sgd_design.candidate_id],
                replication_id=replication_id,
                replication_seed=replication_seed,
                observed_value=observation.sgd_observed_value,
                cost=cost(candidates[sgd_design.candidate_id]),
                shared_key=observation.shared_key,
                noise_key=observation.sgd_noise_key,
                created_at=arm_created_at,
            )
            adam_arm = _calibration_arm(
                group=group,
                design=adam_design,
                candidate=candidates[adam_design.candidate_id],
                replication_id=replication_id,
                replication_seed=replication_seed,
                observed_value=observation.adam_observed_value,
                cost=cost(candidates[adam_design.candidate_id]),
                shared_key=observation.shared_key,
                noise_key=observation.adam_noise_key,
                created_at=arm_created_at,
            )
            arms.extend((sgd_arm, adam_arm))
            replication = CalibrationReplication(
                replication_id=replication_id,
                calibration_group_id=group.calibration_group_id,
                replication_index=replication_index,
                replication_seed=replication_seed,
                adam_arm_id=adam_arm.calibration_arm_id,
                sgd_arm_id=sgd_arm.calibration_arm_id,
                created_at=arm_created_at,
                provenance=Provenance.create(
                    method="calibration-replication-registration",
                    version=CALIBRATION_REPLICATION_VERSION,
                    details={
                        "adam_arm_id": adam_arm.calibration_arm_id,
                        "comparison_group_id": group.comparison_group_id,
                        "namespace": CALIBRATION_NAMESPACE,
                        "replication_id": replication_id,
                        "replication_seed": replication_seed,
                        "sgd_arm_id": sgd_arm.calibration_arm_id,
                    },
                ),
            )
            replications.append(replication)
            effects.append(
                contract.consume(
                    group=group,
                    replication_id=replication_id,
                    replication_seed=replication_seed,
                    adam_arm=adam_arm,
                    sgd_arm=sgd_arm,
                    created_at=arm_created_at,
                )
            )

    calibration_cost = math.fsum(item.cost for item in arms)
    prefix_id = _stable_id(
        "calibration-prefix",
        {
            "effect_ids": [item.calibration_effect_id for item in effects],
            "evaluation_seed": evaluation_seed,
            "version": CALIBRATION_PREFIX_VERSION,
            "world_id": world_id,
        },
    )
    return CalibrationPrefix(
        prefix_id=prefix_id,
        world_id=world_id,
        evaluation_seed=evaluation_seed,
        groups=tuple(groups),
        replications=tuple(replications),
        arms=tuple(arms),
        matched_effects=tuple(effects),
        calibration_cost=calibration_cost,
        created_at=created_at,
        provenance=Provenance.create(
            method="deterministic-calibration-prefix",
            version=CALIBRATION_PREFIX_VERSION,
            details={
                "calibration_effect_count": len(effects),
                "calibration_group_count": len(groups),
                "decision_namespace": DECISION_NAMESPACE,
                "evaluation_seed": evaluation_seed,
                "hidden_truth_available": False,
                "namespace": CALIBRATION_NAMESPACE,
                "world_id": world_id,
            },
        ),
    )


def _calibration_arm(
    *,
    group: CalibrationGroup,
    design: PublicExperimentDesign,
    candidate: Candidate,
    replication_id: str,
    replication_seed: str,
    observed_value: float,
    cost: float,
    shared_key: str,
    noise_key: str,
    created_at: str,
) -> CalibrationArm:
    arm_id = _stable_id(
        "calibration-arm",
        {
            "arm": design.intervention_arm,
            "candidate_id": candidate.candidate_id,
            "replication_id": replication_id,
        },
    )
    return CalibrationArm(
        calibration_arm_id=arm_id,
        calibration_group_id=group.calibration_group_id,
        replication_id=replication_id,
        replication_seed=replication_seed,
        candidate_id=f"calibration:{candidate.candidate_id}:{replication_id}",
        intervention_arm=design.intervention_arm,
        controlled_variables=design.controlled_variables,
        observed_value=observed_value,
        cost=cost,
        shared_key=shared_key,
        arm_noise_key=noise_key,
        successful=True,
        created_at=created_at,
        provenance=Provenance.create(
            method="calibration-arm-execution",
            version=CALIBRATION_REPLICATION_VERSION,
            details={
                "arm_noise_key": noise_key,
                "base_candidate_id": candidate.candidate_id,
                "comparison_group_id": group.comparison_group_id,
                "intervention_arm": design.intervention_arm,
                "namespace": CALIBRATION_NAMESPACE,
                "replication_id": replication_id,
                "replication_seed": replication_seed,
                "shared_key": shared_key,
                "source_status": "completed_successfully",
            },
        ),
    )


def _stable_seed(
    *, world_id: str, evaluation_seed: int, comparison_group_id: str, replication_index: int
) -> str:
    payload = {
        "comparison_group_id": comparison_group_id,
        "evaluation_seed": evaluation_seed,
        "namespace": CALIBRATION_NAMESPACE,
        "replication_index": replication_index,
        "world_id": world_id,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return f"calibration-seed:{digest}"


def _stable_id(prefix: str, payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"
