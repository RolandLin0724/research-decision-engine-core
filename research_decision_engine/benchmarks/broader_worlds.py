"""Frozen public candidate catalog and synthetic world definitions."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Final, Literal

from research_decision_engine.evidence_eligibility import (
    ControlledFingerprint,
    OptimizerEvidenceEligibilityContract,
    PublicExperimentDesign,
)
from research_decision_engine.optimizer_effect import (
    ADAM_ADVANTAGE_ID,
    NO_ADVANTAGE_ID,
    SGD_ADVANTAGE_ID,
)
from research_decision_engine.types import Candidate

type CandidateRole = Literal["optimizer_arm", "setup", "irrelevant", "redundant"]

GROUP_IDS: Final = ("group-00", "group-01", "group-02")
BUDGETS: Final = (
    ("budget-2.25", 2.25),
    ("budget-4.50", 4.50),
    ("budget-6.75", 6.75),
)
MIDPOINTS: Final = {"group-00": 0.55, "group-01": 0.60, "group-02": 0.65}


@dataclass(frozen=True, slots=True)
class CandidateDefinition:
    """One frozen public candidate row."""

    candidate: Candidate
    family: str
    comparison_group_id: str
    controlled_variables: ControlledFingerprint
    intervention_variable: str
    intervention_arm: str
    replication_id: str
    role: CandidateRole

    @property
    def candidate_id(self) -> str:
        return self.candidate.candidate_id

    def public_design(self) -> PublicExperimentDesign:
        return PublicExperimentDesign(
            candidate_id=self.candidate_id,
            experiment_family=self.family,
            comparison_group_id=self.comparison_group_id,
            controlled_variables=self.controlled_variables,
            intervention_variable=self.intervention_variable,
            intervention_arm=self.intervention_arm,
        )


@dataclass(frozen=True, slots=True)
class PublicWorldDefinition:
    """Truth-free world structure supplied to runners and policies."""

    world_id: str
    block: str
    cost_catalog_id: str
    depth: int
    candidate_ids: tuple[str, ...]
    initial_feasible_candidate_ids: tuple[str, ...]
    setup_candidate_ids: tuple[str, ...]
    comparison_group_ids: tuple[str, ...] = GROUP_IDS
    budget_ids: tuple[str, ...] = tuple(item[0] for item in BUDGETS)


@dataclass(frozen=True, slots=True)
class HiddenWorldParameters:
    """Evaluator-only parameters, never accepted by a policy-facing function."""

    scientific_hypothesis_id: str
    effect_size: float
    group_sigmas: tuple[tuple[str, float], ...]

    def sigma_for(self, group_id: str) -> float:
        return dict(self.group_sigmas)[group_id]


@dataclass(frozen=True, slots=True)
class BenchmarkWorld:
    """Evaluator pairing of public structure and hidden outcome parameters."""

    public: PublicWorldDefinition
    hidden: HiddenWorldParameters


@dataclass(frozen=True, slots=True)
class PublicFeasibilityState:
    """Immutable public real-state adapter for depth-two and depth-three worlds."""

    world: PublicWorldDefinition
    completed_candidate_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(set(self.completed_candidate_ids)) != len(self.completed_candidate_ids):
            raise ValueError("Completed public candidate IDs must be unique.")
        if not set(self.completed_candidate_ids).issubset(self.world.candidate_ids):
            raise ValueError("Public state references a candidate outside its world.")

    def publicly_feasible_candidate_ids(self) -> tuple[str, ...]:
        completed = set(self.completed_candidate_ids)
        feasible = set(self.world.initial_feasible_candidate_ids)
        if self.world.depth == 3:
            for setup_id in self.world.setup_candidate_ids:
                if setup_id not in completed:
                    continue
                group_index = setup_id[1:3]
                feasible.update((f"g{group_index}-adam-r1", f"g{group_index}-sgd-r1"))
        return tuple(
            candidate_id
            for candidate_id in self.world.candidate_ids
            if candidate_id in feasible and candidate_id not in completed
        )

    def complete(self, candidate_id: str) -> PublicFeasibilityState:
        if candidate_id not in self.publicly_feasible_candidate_ids():
            raise ValueError(f"Candidate {candidate_id} is not publicly feasible.")
        return PublicFeasibilityState(
            world=self.world,
            completed_candidate_ids=(*self.completed_candidate_ids, candidate_id),
        )


def _controls(
    learning_rate: float, model_width: int, regularization: float
) -> ControlledFingerprint:
    return (
        ("learning_rate", learning_rate),
        ("model_width", model_width),
        ("regularization", regularization),
    )


CONTROL_FINGERPRINTS: Final = {
    "cf-g00": _controls(0.001, 64, 0.0),
    "cf-g01": _controls(0.003, 128, 0.01),
    "cf-g02": _controls(0.01, 256, 0.05),
    "cf-objective-only": _controls(0.02, 32, 0.10),
}


def _candidate_definition(
    candidate_id: str,
    *,
    family: str,
    comparison_group_id: str,
    fingerprint_id: str,
    intervention_variable: str,
    intervention_arm: str,
    replication_id: str,
    role: CandidateRole,
) -> CandidateDefinition:
    controls = CONTROL_FINGERPRINTS[fingerprint_id]
    values = dict(controls)
    return CandidateDefinition(
        candidate=Candidate(
            candidate_id=candidate_id,
            learning_rate=float(values["learning_rate"]),
            regularization=float(values["regularization"]),
            model_width=int(values["model_width"]),
            optimizer=intervention_arm,
        ),
        family=family,
        comparison_group_id=comparison_group_id,
        controlled_variables=controls,
        intervention_variable=intervention_variable,
        intervention_arm=intervention_arm,
        replication_id=replication_id,
        role=role,
    )


CANDIDATE_CATALOG: Final = (
    _candidate_definition(
        "g00-adam-r1",
        family="optimizer-effect",
        comparison_group_id="group-00",
        fingerprint_id="cf-g00",
        intervention_variable="optimizer",
        intervention_arm="adam",
        replication_id="decision-group-00-r0001",
        role="optimizer_arm",
    ),
    _candidate_definition(
        "g00-sgd-r1",
        family="optimizer-effect",
        comparison_group_id="group-00",
        fingerprint_id="cf-g00",
        intervention_variable="optimizer",
        intervention_arm="sgd",
        replication_id="decision-group-00-r0001",
        role="optimizer_arm",
    ),
    _candidate_definition(
        "g01-adam-r1",
        family="optimizer-effect",
        comparison_group_id="group-01",
        fingerprint_id="cf-g01",
        intervention_variable="optimizer",
        intervention_arm="adam",
        replication_id="decision-group-01-r0001",
        role="optimizer_arm",
    ),
    _candidate_definition(
        "g01-sgd-r1",
        family="optimizer-effect",
        comparison_group_id="group-01",
        fingerprint_id="cf-g01",
        intervention_variable="optimizer",
        intervention_arm="sgd",
        replication_id="decision-group-01-r0001",
        role="optimizer_arm",
    ),
    _candidate_definition(
        "g02-adam-r1",
        family="optimizer-effect",
        comparison_group_id="group-02",
        fingerprint_id="cf-g02",
        intervention_variable="optimizer",
        intervention_arm="adam",
        replication_id="decision-group-02-r0001",
        role="optimizer_arm",
    ),
    _candidate_definition(
        "g02-sgd-r1",
        family="optimizer-effect",
        comparison_group_id="group-02",
        fingerprint_id="cf-g02",
        intervention_variable="optimizer",
        intervention_arm="sgd",
        replication_id="decision-group-02-r0001",
        role="optimizer_arm",
    ),
    _candidate_definition(
        "g00-setup-r1",
        family="optimizer-setup",
        comparison_group_id="setup-group-00",
        fingerprint_id="cf-g00",
        intervention_variable="setup",
        intervention_arm="enable",
        replication_id="setup-group-00-r0001",
        role="setup",
    ),
    _candidate_definition(
        "g01-setup-r1",
        family="optimizer-setup",
        comparison_group_id="setup-group-01",
        fingerprint_id="cf-g01",
        intervention_variable="setup",
        intervention_arm="enable",
        replication_id="setup-group-01-r0001",
        role="setup",
    ),
    _candidate_definition(
        "g02-setup-r1",
        family="optimizer-setup",
        comparison_group_id="setup-group-02",
        fingerprint_id="cf-g02",
        intervention_variable="setup",
        intervention_arm="enable",
        replication_id="setup-group-02-r0001",
        role="setup",
    ),
    _candidate_definition(
        "irrelevant-objective-r1",
        family="objective-only",
        comparison_group_id="objective-only-00",
        fingerprint_id="cf-objective-only",
        intervention_variable="none",
        intervention_arm="irrelevant",
        replication_id="irrelevant-r0001",
        role="irrelevant",
    ),
    _candidate_definition(
        "redundant-objective-r1",
        family="objective-only",
        comparison_group_id="objective-only-00",
        fingerprint_id="cf-objective-only",
        intervention_variable="none",
        intervention_arm="redundant",
        replication_id="redundant-r0001",
        role="redundant",
    ),
)

CANDIDATES_BY_ID: Final = {item.candidate_id: item for item in CANDIDATE_CATALOG}
OPTIMIZER_CANDIDATE_IDS: Final = tuple(
    item.candidate_id for item in CANDIDATE_CATALOG if item.role == "optimizer_arm"
)
DECISION_ORACLE_CANDIDATE_IDS: Final = (
    *OPTIMIZER_CANDIDATE_IDS,
    "irrelevant-objective-r1",
    "redundant-objective-r1",
)
SETUP_CANDIDATE_IDS: Final = tuple(
    item.candidate_id for item in CANDIDATE_CATALOG if item.role == "setup"
)
OBJECTIVE_CANDIDATE_IDS: Final = (
    "irrelevant-objective-r1",
    "redundant-objective-r1",
)

COST_CATALOGS: Final = {
    "cost-symmetric/v1": {
        "g00-adam-r1": 1.0,
        "g00-sgd-r1": 1.0,
        "g01-adam-r1": 1.0,
        "g01-sgd-r1": 1.0,
        "g02-adam-r1": 1.0,
        "g02-sgd-r1": 1.0,
        **{candidate_id: 0.25 for candidate_id in SETUP_CANDIDATE_IDS},
        "irrelevant-objective-r1": 0.5,
        "redundant-objective-r1": 0.75,
    },
    "cost-a/v1": {
        "g00-adam-r1": 0.5,
        "g00-sgd-r1": 1.0,
        "g01-adam-r1": 1.0,
        "g01-sgd-r1": 1.0,
        "g02-adam-r1": 1.25,
        "g02-sgd-r1": 1.75,
        **{candidate_id: 0.25 for candidate_id in SETUP_CANDIDATE_IDS},
        "irrelevant-objective-r1": 0.5,
        "redundant-objective-r1": 0.75,
    },
    "cost-b/v1": {
        "g00-adam-r1": 1.75,
        "g00-sgd-r1": 1.25,
        "g01-adam-r1": 1.0,
        "g01-sgd-r1": 1.0,
        "g02-adam-r1": 1.0,
        "g02-sgd-r1": 0.5,
        **{candidate_id: 0.25 for candidate_id in SETUP_CANDIDATE_IDS},
        "irrelevant-objective-r1": 0.5,
        "redundant-objective-r1": 0.75,
    },
}


def _world(
    world_id: str,
    block: str,
    truth: str,
    effect: float,
    sigmas: tuple[float, float, float],
    cost_catalog_id: str = "cost-symmetric/v1",
    depth: int = 2,
) -> BenchmarkWorld:
    candidate_ids = (
        (*SETUP_CANDIDATE_IDS, *OPTIMIZER_CANDIDATE_IDS, *OBJECTIVE_CANDIDATE_IDS)
        if depth == 3
        else (*OPTIMIZER_CANDIDATE_IDS, *OBJECTIVE_CANDIDATE_IDS)
    )
    initial = (*SETUP_CANDIDATE_IDS, *OBJECTIVE_CANDIDATE_IDS) if depth == 3 else candidate_ids
    return BenchmarkWorld(
        public=PublicWorldDefinition(
            world_id=world_id,
            block=block,
            cost_catalog_id=cost_catalog_id,
            depth=depth,
            candidate_ids=tuple(candidate_ids),
            initial_feasible_candidate_ids=tuple(initial),
            setup_candidate_ids=SETUP_CANDIDATE_IDS if depth == 3 else (),
        ),
        hidden=HiddenWorldParameters(
            scientific_hypothesis_id=truth,
            effect_size=effect,
            group_sigmas=tuple(zip(GROUP_IDS, sigmas, strict=True)),
        ),
    )


WORLDS: Final = (
    _world("h_adam_low", "homogeneous", ADAM_ADVANTAGE_ID, 0.12, (0.02, 0.02, 0.02)),
    _world("h_null_low", "homogeneous", NO_ADVANTAGE_ID, 0.0, (0.02, 0.02, 0.02)),
    _world("h_sgd_low", "homogeneous", SGD_ADVANTAGE_ID, 0.12, (0.02, 0.02, 0.02)),
    _world("h_adam_high", "homogeneous", ADAM_ADVANTAGE_ID, 0.12, (0.20, 0.20, 0.20)),
    _world("h_null_high", "homogeneous", NO_ADVANTAGE_ID, 0.0, (0.20, 0.20, 0.20)),
    _world("h_sgd_high", "homogeneous", SGD_ADVANTAGE_ID, 0.12, (0.20, 0.20, 0.20)),
    _world("w_adam_medium", "weak_effect", ADAM_ADVANTAGE_ID, 0.04, (0.05, 0.05, 0.05)),
    _world("w_sgd_medium", "weak_effect", SGD_ADVANTAGE_ID, 0.04, (0.05, 0.05, 0.05)),
    _world("g_adam_lmh", "heterogeneous_noise", ADAM_ADVANTAGE_ID, 0.12, (0.02, 0.10, 0.20)),
    _world("g_null_lmh", "heterogeneous_noise", NO_ADVANTAGE_ID, 0.0, (0.02, 0.10, 0.20)),
    _world("g_sgd_lmh", "heterogeneous_noise", SGD_ADVANTAGE_ID, 0.12, (0.02, 0.10, 0.20)),
    _world("g_adam_hml", "heterogeneous_noise", ADAM_ADVANTAGE_ID, 0.12, (0.20, 0.10, 0.02)),
    _world("g_null_hml", "heterogeneous_noise", NO_ADVANTAGE_ID, 0.0, (0.20, 0.10, 0.02)),
    _world("g_sgd_hml", "heterogeneous_noise", SGD_ADVANTAGE_ID, 0.12, (0.20, 0.10, 0.02)),
    _world("c_adam_a", "asymmetric_cost", ADAM_ADVANTAGE_ID, 0.12, (0.05, 0.05, 0.05), "cost-a/v1"),
    _world("c_sgd_a", "asymmetric_cost", SGD_ADVANTAGE_ID, 0.12, (0.05, 0.05, 0.05), "cost-a/v1"),
    _world("c_adam_b", "asymmetric_cost", ADAM_ADVANTAGE_ID, 0.12, (0.05, 0.05, 0.05), "cost-b/v1"),
    _world("c_sgd_b", "asymmetric_cost", SGD_ADVANTAGE_ID, 0.12, (0.05, 0.05, 0.05), "cost-b/v1"),
    _world("d2_adam", "delay", ADAM_ADVANTAGE_ID, 0.12, (0.05, 0.05, 0.05)),
    _world("d2_null", "delay", NO_ADVANTAGE_ID, 0.0, (0.05, 0.05, 0.05)),
    _world("d2_sgd", "delay", SGD_ADVANTAGE_ID, 0.12, (0.05, 0.05, 0.05)),
    _world("d3_adam", "delay", ADAM_ADVANTAGE_ID, 0.12, (0.05, 0.05, 0.05), depth=3),
    _world("d3_null", "delay", NO_ADVANTAGE_ID, 0.0, (0.05, 0.05, 0.05), depth=3),
    _world("d3_sgd", "delay", SGD_ADVANTAGE_ID, 0.12, (0.05, 0.05, 0.05), depth=3),
)

WORLDS_BY_ID: Final = {item.public.world_id: item for item in WORLDS}


def evidence_eligibility_contract() -> OptimizerEvidenceEligibilityContract:
    return OptimizerEvidenceEligibilityContract.from_candidates(
        (item.candidate for item in CANDIDATE_CATALOG),
        public_designs=(item.public_design() for item in CANDIDATE_CATALOG),
    )


def candidate_costs(world: PublicWorldDefinition) -> dict[str, float]:
    return dict(COST_CATALOGS[world.cost_catalog_id])


def hidden_arm_mean(world: BenchmarkWorld, candidate_id: str) -> float:
    definition = CANDIDATES_BY_ID[candidate_id]
    if definition.role in {"irrelevant", "redundant"}:
        return 0.60
    midpoint = MIDPOINTS[definition.comparison_group_id]
    effect = world.hidden.effect_size
    arm = definition.intervention_arm
    truth = world.hidden.scientific_hypothesis_id
    if truth == NO_ADVANTAGE_ID:
        return midpoint
    direction = 1.0 if truth == ADAM_ADVANTAGE_ID else -1.0
    arm_sign = 1.0 if arm == "adam" else -1.0
    return midpoint + direction * arm_sign * effect / 2.0


def hidden_observation_sigma(world: BenchmarkWorld, candidate_id: str) -> float:
    definition = CANDIDATES_BY_ID[candidate_id]
    if definition.role in {"irrelevant", "redundant"}:
        return statistics.median(dict(world.hidden.group_sigmas).values())
    return world.hidden.sigma_for(definition.comparison_group_id)


def validate_worlds() -> None:
    if len(WORLDS) != 24 or len(WORLDS_BY_ID) != 24:
        raise ValueError("The frozen world registry must contain 24 unique worlds.")
    truth_counts = {
        hypothesis_id: sum(
            world.hidden.scientific_hypothesis_id == hypothesis_id for world in WORLDS
        )
        for hypothesis_id in (ADAM_ADVANTAGE_ID, NO_ADVANTAGE_ID, SGD_ADVANTAGE_ID)
    }
    if truth_counts != {ADAM_ADVANTAGE_ID: 9, NO_ADVANTAGE_ID: 6, SGD_ADVANTAGE_ID: 9}:
        raise ValueError("Frozen truth margins changed.")
    for world in WORLDS:
        costs = candidate_costs(world.public)
        cheapest_path = min(
            costs[f"g{index:02d}-adam-r1"] + costs[f"g{index:02d}-sgd-r1"] for index in range(3)
        )
        if world.public.depth == 3:
            cheapest_path += 0.25
        if cheapest_path > BUDGETS[0][1]:
            raise ValueError(f"World {world.public.world_id} has no smallest-budget evidence path.")
