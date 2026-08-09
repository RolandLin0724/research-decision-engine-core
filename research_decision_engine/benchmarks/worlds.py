"""Deterministic hidden worlds and public experiment designs."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Literal

from research_decision_engine.calibration import CalibrationPairObservation
from research_decision_engine.evidence_eligibility import (
    OptimizerEvidenceEligibilityContract,
    PublicExperimentDesign,
    default_public_design,
)
from research_decision_engine.optimizer_effect import (
    ADAM_ADVANTAGE_ID,
    NO_ADVANTAGE_ID,
    SGD_ADVANTAGE_ID,
)
from research_decision_engine.reasoning import ReasoningError
from research_decision_engine.types import Candidate

BENCHMARK_VERSION = "research-decision-benchmark/v2"

type NoiseLevel = Literal["low", "medium", "high"]
type CostMode = Literal["symmetric", "asymmetric"]
type CandidateVariant = Literal[
    "base",
    "irrelevant_redundant",
    "stress_delayed",
    "stress_no_advantage",
    "stress_adverse_noise",
    "stress_asymmetric",
    "paired_multi_pair",
    "paired_multi_pair_asymmetric",
]
type ControlKey = tuple[float, float, int]

BASE_CONTROLS: tuple[ControlKey, ...] = (
    (0.001, 0.0001, 32),
    (0.001, 0.001, 32),
    (0.003, 0.001, 64),
    (0.01, 0.0001, 32),
    (0.01, 0.001, 64),
    (0.03, 0.01, 32),
)
IRRELEVANT_CONTROLS: tuple[ControlKey, ...] = ((0.1, 0.01, 32),)


@dataclass(frozen=True, slots=True)
class BenchmarkWorldConfig:
    """Evaluator-visible configuration for one benchmark condition."""

    world_id: str
    true_hypothesis_id: str
    true_optimizer_effect: float
    noise_level: NoiseLevel
    observation_noise_std: float
    cost_mode: CostMode
    candidate_variant: CandidateVariant

    def __post_init__(self) -> None:
        valid_hypotheses = {ADAM_ADVANTAGE_ID, NO_ADVANTAGE_ID, SGD_ADVANTAGE_ID}
        if self.true_hypothesis_id not in valid_hypotheses:
            raise ReasoningError(f"Unknown benchmark truth: {self.true_hypothesis_id}")
        if not math.isfinite(self.true_optimizer_effect):
            raise ReasoningError("True optimizer effect must be finite.")
        if not math.isfinite(self.observation_noise_std) or self.observation_noise_std < 0.0:
            raise ReasoningError("Observation noise must be finite and non-negative.")
        if self.true_hypothesis_id == ADAM_ADVANTAGE_ID and self.true_optimizer_effect <= 0.0:
            raise ReasoningError("Adam-advantage world must have a positive true effect.")
        if self.true_hypothesis_id == SGD_ADVANTAGE_ID and self.true_optimizer_effect >= 0.0:
            raise ReasoningError("SGD-advantage world must have a negative true effect.")
        if self.true_hypothesis_id == NO_ADVANTAGE_ID and self.true_optimizer_effect != 0.0:
            raise ReasoningError("No-advantage world must have a zero true effect.")

    def to_dict(self) -> dict[str, object]:
        return {
            "world_id": self.world_id,
            "true_hypothesis_id": self.true_hypothesis_id,
            "true_optimizer_effect": self.true_optimizer_effect,
            "noise_level": self.noise_level,
            "observation_noise_std": self.observation_noise_std,
            "cost_mode": self.cost_mode,
            "candidate_variant": self.candidate_variant,
            "matched_evidence_requires_two_experiments": True,
        }


@dataclass(frozen=True, slots=True)
class CandidateCost:
    candidate_id: str
    cost: float


@dataclass(frozen=True, slots=True)
class BenchmarkDesign:
    """Truth-free candidate and cost information available to policy adapters."""

    world_id: str
    candidates: tuple[Candidate, ...]
    candidate_costs: tuple[CandidateCost, ...]
    irrelevant_candidate_ids: tuple[str, ...]
    redundant_candidate_ids: tuple[str, ...]
    public_designs: tuple[PublicExperimentDesign, ...] = ()

    def cost(self, candidate: Candidate) -> float:
        for item in self.candidate_costs:
            if item.candidate_id == candidate.candidate_id:
                return item.cost
        raise KeyError(f"Unknown benchmark candidate: {candidate.candidate_id}")

    def is_evaluator_redundant(
        self, candidate: Candidate, completed_candidates: tuple[Candidate, ...]
    ) -> bool:
        if candidate.candidate_id in self.irrelevant_candidate_ids:
            return True
        design_key = _candidate_design_key(candidate)
        if any(_candidate_design_key(item) == design_key for item in completed_candidates):
            return True
        controls = _control_key(candidate)
        completed_optimizers = {
            item.optimizer for item in completed_candidates if _control_key(item) == controls
        }
        return completed_optimizers == {"sgd", "adam"}

    def evidence_eligibility(self) -> OptimizerEvidenceEligibilityContract:
        return OptimizerEvidenceEligibilityContract.from_candidates(
            self.candidates,
            public_designs=self.public_designs,
        )

    def to_dict(self) -> dict[str, object]:
        costs = {item.candidate_id: item.cost for item in self.candidate_costs}
        return {
            "world_id": self.world_id,
            "candidate_count": len(self.candidates),
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "params": candidate.params(),
                    "cost": costs[candidate.candidate_id],
                }
                for candidate in self.candidates
            ],
            "irrelevant_candidate_ids": list(self.irrelevant_candidate_ids),
            "redundant_candidate_ids": list(self.redundant_candidate_ids),
            "public_experimental_designs": [
                item.to_dict() for item in self.evidence_eligibility().designs
            ],
        }


class _HiddenBenchmarkWorld:
    """Evaluator-only observation generator containing hidden scientific truth."""

    def __init__(self, *, config: BenchmarkWorldConfig, seed: int, design: BenchmarkDesign) -> None:
        self._config = config
        self._seed = seed
        self._design = design

    def observe(self, candidate: Candidate) -> float:
        base_value = _base_objective(candidate)
        if candidate.candidate_id in self._design.irrelevant_candidate_ids:
            optimizer_effect = 0.0
        else:
            optimizer_effect = self._config.true_optimizer_effect
        intervention = (
            optimizer_effect / 2.0 if candidate.optimizer == "adam" else -optimizer_effect / 2.0
        )
        noise = self._config.observation_noise_std * _stable_standard_normal(
            world_id=self._config.world_id,
            seed=self._seed,
            candidate=candidate,
        )
        return round(base_value + intervention + noise, 12)

    def observe_calibration_pair(
        self,
        *,
        sgd_candidate: Candidate,
        adam_candidate: Candidate,
        replication_id: str,
        replication_seed: str,
    ) -> CalibrationPairObservation:
        """Observe one replicated pair through a truth-free callable interface."""

        if _control_key(sgd_candidate) != _control_key(adam_candidate):
            raise ReasoningError("Calibration pair controls must be identical.")
        if sgd_candidate.optimizer != "sgd" or adam_candidate.optimizer != "adam":
            raise ReasoningError("Calibration pair requires complementary optimizer arms.")

        base_value = _base_objective(sgd_candidate)
        optimizer_effect = self._config.true_optimizer_effect
        shared_key = f"calibration|{self._config.world_id}|{self._seed}|{replication_seed}|shared"
        sgd_noise_key = f"calibration|{self._config.world_id}|{self._seed}|{replication_seed}|sgd"
        adam_noise_key = f"calibration|{self._config.world_id}|{self._seed}|{replication_seed}|adam"
        shared_noise = self._config.observation_noise_std * _stable_standard_normal_material(
            shared_key
        )
        sgd_noise = self._config.observation_noise_std * _stable_standard_normal_material(
            sgd_noise_key
        )
        adam_noise = self._config.observation_noise_std * _stable_standard_normal_material(
            adam_noise_key
        )
        sgd_observed = base_value - optimizer_effect / 2.0 + shared_noise + sgd_noise
        adam_observed = base_value + optimizer_effect / 2.0 + shared_noise + adam_noise
        return CalibrationPairObservation(
            adam_observed_value=round(adam_observed, 12),
            sgd_observed_value=round(sgd_observed, 12),
            shared_key=shared_key,
            adam_noise_key=adam_noise_key,
            sgd_noise_key=sgd_noise_key,
        )


def benchmark_worlds(world_ids: tuple[str, ...] | None = None) -> tuple[BenchmarkWorldConfig, ...]:
    """Return selected deterministic benchmark configurations in suite order."""

    selected = set(benchmark_world_ids() if world_ids is None else world_ids)
    unknown = selected.difference(all_benchmark_world_ids())
    if unknown:
        raise ValueError(f"Unknown benchmark worlds: {', '.join(sorted(unknown))}")
    return tuple(
        config
        for config in (*_WORLD_CONFIGS, *_LOOKAHEAD_WORLD_CONFIGS)
        if config.world_id in selected
    )


def benchmark_world_ids() -> tuple[str, ...]:
    return tuple(config.world_id for config in _WORLD_CONFIGS)


def lookahead_benchmark_world_ids() -> tuple[str, ...]:
    return tuple(config.world_id for config in _LOOKAHEAD_WORLD_CONFIGS)


def all_benchmark_world_ids() -> tuple[str, ...]:
    return (*benchmark_world_ids(), *lookahead_benchmark_world_ids())


def build_benchmark_world(
    config: BenchmarkWorldConfig, *, seed: int
) -> tuple[BenchmarkDesign, _HiddenBenchmarkWorld]:
    """Build separate public design and hidden evaluator views for one seeded world."""

    if config.candidate_variant.startswith("paired_"):
        design = _build_paired_evaluation_design(config)
        return design, _HiddenBenchmarkWorld(config=config, seed=seed, design=design)
    if config.candidate_variant.startswith("stress_"):
        design = _build_lookahead_stress_design(config)
        return design, _HiddenBenchmarkWorld(config=config, seed=seed, design=design)

    candidates: list[Candidate] = []
    irrelevant_ids: list[str] = []
    redundant_ids: list[str] = []
    controls = list(BASE_CONTROLS)
    if config.candidate_variant == "irrelevant_redundant":
        controls.extend(IRRELEVANT_CONTROLS)

    for control in controls:
        for optimizer in ("sgd", "adam"):
            candidate_id = f"cand-{len(candidates):03d}"
            candidate = _candidate(candidate_id, control, optimizer)
            candidates.append(candidate)
            if control in IRRELEVANT_CONTROLS:
                irrelevant_ids.append(candidate_id)

    if config.candidate_variant == "irrelevant_redundant":
        for optimizer in ("sgd", "adam"):
            candidate_id = f"cand-{len(candidates):03d}"
            candidates.append(_candidate(candidate_id, BASE_CONTROLS[0], optimizer))
            redundant_ids.append(candidate_id)

    costs = tuple(
        CandidateCost(candidate_id=item.candidate_id, cost=_candidate_cost(item, config.cost_mode))
        for item in candidates
    )
    design = BenchmarkDesign(
        world_id=config.world_id,
        candidates=tuple(candidates),
        candidate_costs=costs,
        irrelevant_candidate_ids=tuple(irrelevant_ids),
        redundant_candidate_ids=tuple(redundant_ids),
    )
    return design, _HiddenBenchmarkWorld(config=config, seed=seed, design=design)


def paired_evaluation_worlds() -> tuple[BenchmarkWorldConfig, ...]:
    """Return truth-equivalent stress worlds with two public matched pairs."""

    return tuple(
        BenchmarkWorldConfig(
            world_id=config.world_id,
            true_hypothesis_id=config.true_hypothesis_id,
            true_optimizer_effect=config.true_optimizer_effect,
            noise_level=config.noise_level,
            observation_noise_std=config.observation_noise_std,
            cost_mode=config.cost_mode,
            candidate_variant=(
                "paired_multi_pair_asymmetric"
                if config.world_id == "asymmetric_experiment_costs"
                else "paired_multi_pair"
            ),
        )
        for config in _LOOKAHEAD_WORLD_CONFIGS
    )


def _build_paired_evaluation_design(config: BenchmarkWorldConfig) -> BenchmarkDesign:
    candidates: tuple[Candidate, ...]
    costs: tuple[float, ...]
    if config.candidate_variant == "paired_multi_pair_asymmetric":
        candidates = (
            _candidate("aaa-trap-sgd", BASE_CONTROLS[0], "sgd"),
            _candidate("aaa-trap-adam", BASE_CONTROLS[0], "adam"),
            _candidate("pair-00-sgd", BASE_CONTROLS[3], "sgd"),
            _candidate("pair-00-adam", BASE_CONTROLS[3], "adam"),
            _candidate("pair-01-sgd", BASE_CONTROLS[5], "sgd"),
            _candidate("pair-01-adam", BASE_CONTROLS[5], "adam"),
        )
        costs = (0.25, 2.5, 1.0, 1.25, 1.0, 1.25)
        irrelevant_ids: tuple[str, ...] = ()
    else:
        decoy = _candidate("decoy-objective", IRRELEVANT_CONTROLS[0], "sgd")
        candidates = (
            decoy,
            _candidate("pair-00-sgd", BASE_CONTROLS[3], "sgd"),
            _candidate("pair-00-adam", BASE_CONTROLS[3], "adam"),
            _candidate("pair-01-sgd", BASE_CONTROLS[5], "sgd"),
            _candidate("pair-01-adam", BASE_CONTROLS[5], "adam"),
        )
        costs = (0.5, 1.0, 1.0, 1.0, 1.0)
        irrelevant_ids = (decoy.candidate_id,)

    public_designs = tuple(
        default_public_design(
            candidate,
            experiment_family=(
                "objective-only"
                if candidate.candidate_id == "decoy-objective"
                else "optimizer-effect"
            ),
        )
        for candidate in candidates
    )
    return BenchmarkDesign(
        world_id=config.world_id,
        candidates=candidates,
        candidate_costs=tuple(
            CandidateCost(candidate_id=candidate.candidate_id, cost=cost)
            for candidate, cost in zip(candidates, costs, strict=True)
        ),
        irrelevant_candidate_ids=irrelevant_ids,
        redundant_candidate_ids=(),
        public_designs=public_designs,
    )


def _build_lookahead_stress_design(config: BenchmarkWorldConfig) -> BenchmarkDesign:
    candidates: tuple[Candidate, ...]
    costs: tuple[float, ...]
    public_designs: tuple[PublicExperimentDesign, ...]
    irrelevant_ids: tuple[str, ...]
    if config.candidate_variant == "stress_asymmetric":
        candidates = (
            _candidate("trap-sgd", BASE_CONTROLS[0], "sgd"),
            _candidate("trap-adam", BASE_CONTROLS[0], "adam"),
            _candidate("useful-sgd", BASE_CONTROLS[3], "sgd"),
            _candidate("useful-adam", BASE_CONTROLS[3], "adam"),
        )
        costs = (0.25, 2.5, 1.0, 1.25)
        public_designs = tuple(default_public_design(item) for item in candidates)
        irrelevant_ids = ()
    else:
        decoy = _candidate("decoy-objective", IRRELEVANT_CONTROLS[0], "sgd")
        useful_sgd = _candidate("useful-sgd", BASE_CONTROLS[3], "sgd")
        useful_adam = _candidate("useful-adam", BASE_CONTROLS[3], "adam")
        candidates = (decoy, useful_sgd, useful_adam)
        costs = (0.5, 1.0, 1.0)
        public_designs = (
            default_public_design(decoy, experiment_family="objective-only"),
            default_public_design(useful_sgd),
            default_public_design(useful_adam),
        )
        irrelevant_ids = (decoy.candidate_id,)
    return BenchmarkDesign(
        world_id=config.world_id,
        candidates=candidates,
        candidate_costs=tuple(
            CandidateCost(candidate_id=candidate.candidate_id, cost=cost)
            for candidate, cost in zip(candidates, costs, strict=True)
        ),
        irrelevant_candidate_ids=irrelevant_ids,
        redundant_candidate_ids=(),
        public_designs=public_designs,
    )


def _candidate(candidate_id: str, controls: ControlKey, optimizer: str) -> Candidate:
    learning_rate, regularization, model_width = controls
    return Candidate(
        candidate_id=candidate_id,
        learning_rate=learning_rate,
        regularization=regularization,
        model_width=model_width,
        optimizer=optimizer,
    )


def _candidate_cost(candidate: Candidate, cost_mode: CostMode) -> float:
    base_cost = candidate.model_width / 32.0
    optimizer_factor = 1.5 if cost_mode == "asymmetric" and candidate.optimizer == "adam" else 1.0
    return round(base_cost * optimizer_factor, 6)


def _base_objective(candidate: Candidate) -> float:
    learning_rate_score = 1.0 - min(abs(math.log10(candidate.learning_rate) + 2.0) / 2.0, 1.0)
    regularization_score = 1.0 - min(abs(math.log10(candidate.regularization) + 3.0) / 2.0, 1.0)
    width_score = 1.0 - abs(candidate.model_width - 64) / 96.0
    return 0.40 + 0.25 * learning_rate_score + 0.20 * regularization_score + 0.10 * width_score


def _stable_standard_normal(*, world_id: str, seed: int, candidate: Candidate) -> float:
    material = f"{world_id}|{seed}|{_candidate_design_key(candidate)}"
    return _stable_standard_normal_material(material)


def _stable_standard_normal_material(material: str) -> float:
    encoded = material.encode()
    digest = hashlib.sha256(encoded).digest()
    denominator = float(2**64 + 1)
    first_uniform = (int.from_bytes(digest[:8], "big") + 1) / denominator
    second_uniform = (int.from_bytes(digest[8:16], "big") + 1) / denominator
    return math.sqrt(-2.0 * math.log(first_uniform)) * math.cos(2.0 * math.pi * second_uniform)


def _candidate_design_key(candidate: Candidate) -> tuple[float, float, int, str]:
    return (
        candidate.learning_rate,
        candidate.regularization,
        candidate.model_width,
        candidate.optimizer,
    )


def _control_key(candidate: Candidate) -> ControlKey:
    return (candidate.learning_rate, candidate.regularization, candidate.model_width)


_WORLD_CONFIGS: tuple[BenchmarkWorldConfig, ...] = (
    BenchmarkWorldConfig(
        world_id="adam_low_noise_symmetric",
        true_hypothesis_id=ADAM_ADVANTAGE_ID,
        true_optimizer_effect=0.12,
        noise_level="low",
        observation_noise_std=0.005,
        cost_mode="symmetric",
        candidate_variant="base",
    ),
    BenchmarkWorldConfig(
        world_id="neutral_medium_noise_asymmetric",
        true_hypothesis_id=NO_ADVANTAGE_ID,
        true_optimizer_effect=0.0,
        noise_level="medium",
        observation_noise_std=0.03,
        cost_mode="asymmetric",
        candidate_variant="irrelevant_redundant",
    ),
    BenchmarkWorldConfig(
        world_id="sgd_high_noise_symmetric",
        true_hypothesis_id=SGD_ADVANTAGE_ID,
        true_optimizer_effect=-0.12,
        noise_level="high",
        observation_noise_std=0.08,
        cost_mode="symmetric",
        candidate_variant="irrelevant_redundant",
    ),
    BenchmarkWorldConfig(
        world_id="adam_medium_noise_asymmetric",
        true_hypothesis_id=ADAM_ADVANTAGE_ID,
        true_optimizer_effect=0.20,
        noise_level="medium",
        observation_noise_std=0.03,
        cost_mode="asymmetric",
        candidate_variant="base",
    ),
)


_LOOKAHEAD_WORLD_CONFIGS: tuple[BenchmarkWorldConfig, ...] = (
    BenchmarkWorldConfig(
        world_id="delayed_information",
        true_hypothesis_id=ADAM_ADVANTAGE_ID,
        true_optimizer_effect=0.12,
        noise_level="low",
        observation_noise_std=0.005,
        cost_mode="symmetric",
        candidate_variant="stress_delayed",
    ),
    BenchmarkWorldConfig(
        world_id="no_optimizer_advantage",
        true_hypothesis_id=NO_ADVANTAGE_ID,
        true_optimizer_effect=0.0,
        noise_level="medium",
        observation_noise_std=0.03,
        cost_mode="symmetric",
        candidate_variant="stress_no_advantage",
    ),
    BenchmarkWorldConfig(
        world_id="adverse_noisy_observations",
        true_hypothesis_id=ADAM_ADVANTAGE_ID,
        true_optimizer_effect=0.12,
        noise_level="high",
        observation_noise_std=0.20,
        cost_mode="symmetric",
        candidate_variant="stress_adverse_noise",
    ),
    BenchmarkWorldConfig(
        world_id="asymmetric_experiment_costs",
        true_hypothesis_id=SGD_ADVANTAGE_ID,
        true_optimizer_effect=-0.12,
        noise_level="medium",
        observation_noise_std=0.03,
        cost_mode="asymmetric",
        candidate_variant="stress_asymmetric",
    ),
)
