"""Frozen closed-loop evaluation of fixed and calibrated belief control."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import statistics
from collections.abc import Callable
from dataclasses import dataclass, fields
from pathlib import Path
from random import Random
from typing import Literal, cast

from research_decision_engine.belief_models import (
    CALIBRATED_SIGMA_MODEL_ID,
    FIXED_SIGMA_MODEL_ID,
    MatchedEffectObservation,
    belief_model,
)
from research_decision_engine.benchmarks.evaluation import POLICY_VERSIONS
from research_decision_engine.benchmarks.paired_evaluation import (
    BOOTSTRAP_SEED,
    DEFAULT_BOOTSTRAP_RESAMPLES,
    DEFAULT_LARGE_BUDGET,
    DEFAULT_PAIRED_SEEDS,
    DEFAULT_SHORT_BUDGET,
    NLL_PROBABILITY_FLOOR,
    classify_posterior,
    deterministic_bootstrap_mean_interval,
    top_label_expected_calibration_error,
)
from research_decision_engine.benchmarks.worlds import (
    BenchmarkDesign,
    BenchmarkWorldConfig,
    build_benchmark_world,
    paired_evaluation_worlds,
)
from research_decision_engine.calibration import (
    CALIBRATION_EFFECT_COUNT,
    CalibrationPrefix,
    build_calibration_prefix,
)
from research_decision_engine.closed_loop import (
    CANDIDATE_GROUP_ADAPTER_VERSION,
    CLOSED_LOOP_ARM_RUNNER_VERSION,
    SELECTED_ONLY_ORACLE_VERSION,
    CandidateGroupPredictionAdapter,
    ClosedLoopArmSpec,
    ClosedLoopDecisionTrace,
    PotentialOutcome,
    PotentialOutcomeCommitment,
    SelectedOnlyObservationOracle,
    TruthFreeClosedLoopArmRun,
    potential_outcome_commitment,
    run_closed_loop_arm,
)
from research_decision_engine.decision import (
    INFORMATION_GAIN_POLICY,
    INFORMATION_GAIN_POLICY_VERSION,
    DecisionTrace,
)
from research_decision_engine.lookahead import (
    LOOKAHEAD_INFORMATION_GAIN_POLICY,
    LOOKAHEAD_INFORMATION_GAIN_POLICY_VERSION,
    LookaheadPlanTrace,
)
from research_decision_engine.storage import SCHEMA_VERSION
from research_decision_engine.types import Candidate

CLOSED_LOOP_EVALUATION_VERSION = "closed-loop-belief-control-evaluation/v1"
CLOSED_LOOP_DEFAULT_SEEDS = DEFAULT_PAIRED_SEEDS
CLOSED_LOOP_SHORT_BUDGET = DEFAULT_SHORT_BUDGET
CLOSED_LOOP_LARGE_BUDGET = DEFAULT_LARGE_BUDGET
CLOSED_LOOP_BOOTSTRAP_RESAMPLES = DEFAULT_BOOTSTRAP_RESAMPLES
CONFIDENTLY_WRONG_THRESHOLD = 0.80
COMPARISON_TOLERANCE = 1e-12

FROZEN_SOURCE_SHA256: dict[str, str] = {
    "research_decision_engine/policies.py": (
        "98c0ecf1528287bc36797e3e14d46d9f28dee8982ac59b6795067c34599ed366"
    ),
    "research_decision_engine/decision.py": (
        "1c028f7544ca59196844e8a6c550a786bb60ca90bfa87a779442359ca750f6d6"
    ),
    "research_decision_engine/lookahead.py": (
        "a039c5b4ad8a5fed303465f10109285c6a46b84226c277550fa49a2df2dbb629"
    ),
    "research_decision_engine/reasoning.py": (
        "d0bdccb3d3bbbbce24db285f45fb26027f07056962d55ebc11d536e1a47456ff"
    ),
    "research_decision_engine/optimizer_effect.py": (
        "724505faef2a86e0564aa62108b116020a77f6876dbc9468ebcd199d0cd65de7"
    ),
    "research_decision_engine/evidence_eligibility.py": (
        "ac58eb1f08b0f90b23c177c6ff1262ab2871c18fd6bf22dbe0fab2904ead44fe"
    ),
    "research_decision_engine/belief_models.py": (
        "2b022592c6c7cb5ce52de69e27fc05dc806369aceef339a466669d5d462b78a3"
    ),
    "research_decision_engine/calibration.py": (
        "18702a0772ceab15aad3a02ecc8e11503cf11958f5b12bbca3e833f8e0d115fd"
    ),
    "research_decision_engine/benchmarks/worlds.py": (
        "377bedbe41ff97fe6a5c12232f6c9d2a9d1793868c253cfb837dc77f2f2215a5"
    ),
    "research_decision_engine/benchmarks/paired_evaluation.py": (
        "c901d00e1f08b9ab92cef00a4e3e34dc7b74999cc7459677eaa08f925c51f2c4"
    ),
}

FROZEN_DESIGN_SHA256: dict[str, str] = {
    "AGENTS.md": "c37b098c9239e7deae5d6f0fe04f001618de0abab5a4c7df68ebf63fa94e9649",
    "SPEC.md": "37368a5b557b8918cd1576f8370d69b867b9ecc3319439e6fcf92cdd1e91b7f2",
    "PLAN.md": "255b527b0b087ed99bf2718b71adf0a9541047161bc420cecf73f3a87a56f26d",
    "DESIGN.md": "c3b562e8d58c7cbbd469f9dff6d4766430d2515e8443cd896d766eadf8634bad",
    "LOOKAHEAD_DESIGN.md": ("2df72c43c9fc1880b805ca789816eba271126a118b91a5394b5463d2d076cc5c"),
    "ROBUST_BELIEF_DESIGN.md": ("8cffeffeeac79ada7dcb66eb3b96bb418b60eec55fa90a485a514a9abe893666"),
    "CLOSED_LOOP_EVALUATION_DESIGN.md": (
        "b418981fcd8df7993652d5cc7495a4066aabc2ea64e5559e565f95866544da3d"
    ),
}

HISTORICAL_ARTIFACT_DIRECTORIES = (
    "paired-evaluation-v1-100-seeds",
    "robust-belief-evaluation-v1-100-seeds",
    "robust-belief-evaluation-v1-100-seeds-accepted",
)

type BetterDirection = Literal["higher", "lower"]


class ClosedLoopEvaluationInvariantError(RuntimeError):
    """Raised when a frozen closed-loop protocol invariant is violated."""


@dataclass(frozen=True, slots=True)
class PrimaryArm:
    arm_id: str
    belief_model_id: str
    policy: Literal["information_gain", "lookahead_information_gain"]

    @property
    def policy_version(self) -> str:
        return POLICY_VERSIONS[self.policy]


PRIMARY_ARMS: tuple[PrimaryArm, ...] = (
    PrimaryArm("fixed_information_gain", FIXED_SIGMA_MODEL_ID, "information_gain"),
    PrimaryArm(
        "calibrated_information_gain",
        CALIBRATED_SIGMA_MODEL_ID,
        "information_gain",
    ),
    PrimaryArm(
        "fixed_lookahead_information_gain",
        FIXED_SIGMA_MODEL_ID,
        "lookahead_information_gain",
    ),
    PrimaryArm(
        "calibrated_lookahead_information_gain",
        CALIBRATED_SIGMA_MODEL_ID,
        "lookahead_information_gain",
    ),
)


@dataclass(frozen=True, slots=True)
class PotentialOutcomeBundle:
    world_id: str
    evaluation_seed: int
    commitment: PotentialOutcomeCommitment
    outcomes: tuple[PotentialOutcome, ...]
    calibration_prefix_id: str
    calibration_prefix_sha256: str


@dataclass(frozen=True, slots=True)
class ClosedLoopRunMetrics:
    final_true_hypothesis_probability: float
    negative_log_true_hypothesis_probability: float
    final_brier_score: float
    confidently_wrong: bool
    prediction_correct: bool
    predicted_hypothesis_id: str
    maximum_posterior_probability: float
    final_true_hypothesis_rank: int
    final_posterior_entropy: float
    final_entropy_reduction: float
    reached_sustained_80_confidence: bool
    reached_sustained_95_confidence: bool
    experiments_to_sustained_80_confidence: int | None
    experiments_to_sustained_95_confidence: int | None
    decision_cost_to_sustained_80_confidence: float | None
    decision_cost_to_sustained_95_confidence: float | None
    total_cost_to_sustained_80_confidence: float | None
    total_cost_to_sustained_95_confidence: float | None
    confidence_80_reversals: int
    confidence_95_reversals: int
    matched_evidence_pairs_completed: int
    redundant_experiments_selected: int
    decision_cost: float
    calibration_cost: float
    required_total_cost: float
    conditional_nll_efficiency: float | None
    conditional_brier_efficiency: float | None
    conditional_entropy_efficiency: float | None
    end_to_end_nll_efficiency: float | None
    end_to_end_brier_efficiency: float | None
    end_to_end_entropy_efficiency: float | None
    budget_exhausted: bool
    experiments_completed: int
    best_observed_objective: float | None
    cumulative_predictive_log_likelihood: float
    mean_predictive_log_likelihood: float | None
    first_commitment_step: int | None
    first_commitment_decision_cost: float | None
    ended_uncommitted: bool
    final_adequacy_state: str

    def numeric_values(self) -> dict[str, float | None]:
        return {
            "final_true_hypothesis_probability": self.final_true_hypothesis_probability,
            "negative_log_true_hypothesis_probability": (
                self.negative_log_true_hypothesis_probability
            ),
            "final_brier_score": self.final_brier_score,
            "confidently_wrong": float(self.confidently_wrong),
            "prediction_correct": float(self.prediction_correct),
            "maximum_posterior_probability": self.maximum_posterior_probability,
            "final_true_hypothesis_rank": float(self.final_true_hypothesis_rank),
            "final_posterior_entropy": self.final_posterior_entropy,
            "final_entropy_reduction": self.final_entropy_reduction,
            "reached_sustained_80_confidence": float(self.reached_sustained_80_confidence),
            "reached_sustained_95_confidence": float(self.reached_sustained_95_confidence),
            "experiments_to_sustained_80_confidence": _optional_float(
                self.experiments_to_sustained_80_confidence
            ),
            "experiments_to_sustained_95_confidence": _optional_float(
                self.experiments_to_sustained_95_confidence
            ),
            "decision_cost_to_sustained_80_confidence": (
                self.decision_cost_to_sustained_80_confidence
            ),
            "decision_cost_to_sustained_95_confidence": (
                self.decision_cost_to_sustained_95_confidence
            ),
            "total_cost_to_sustained_80_confidence": (self.total_cost_to_sustained_80_confidence),
            "total_cost_to_sustained_95_confidence": (self.total_cost_to_sustained_95_confidence),
            "confidence_80_reversals": float(self.confidence_80_reversals),
            "confidence_95_reversals": float(self.confidence_95_reversals),
            "matched_evidence_pairs_completed": float(self.matched_evidence_pairs_completed),
            "redundant_experiments_selected": float(self.redundant_experiments_selected),
            "decision_cost": self.decision_cost,
            "calibration_cost": self.calibration_cost,
            "required_total_cost": self.required_total_cost,
            "conditional_nll_efficiency": self.conditional_nll_efficiency,
            "conditional_brier_efficiency": self.conditional_brier_efficiency,
            "conditional_entropy_efficiency": self.conditional_entropy_efficiency,
            "end_to_end_nll_efficiency": self.end_to_end_nll_efficiency,
            "end_to_end_brier_efficiency": self.end_to_end_brier_efficiency,
            "end_to_end_entropy_efficiency": self.end_to_end_entropy_efficiency,
            "budget_exhausted": float(self.budget_exhausted),
            "experiments_completed": float(self.experiments_completed),
            "best_observed_objective": self.best_observed_objective,
            "cumulative_predictive_log_likelihood": (self.cumulative_predictive_log_likelihood),
            "mean_predictive_log_likelihood": self.mean_predictive_log_likelihood,
            "first_commitment_step": _optional_float(self.first_commitment_step),
            "first_commitment_decision_cost": self.first_commitment_decision_cost,
            "ended_uncommitted": float(self.ended_uncommitted),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.numeric_values(),
            "confidently_wrong": self.confidently_wrong,
            "prediction_correct": self.prediction_correct,
            "predicted_hypothesis_id": self.predicted_hypothesis_id,
            "reached_sustained_80_confidence": self.reached_sustained_80_confidence,
            "reached_sustained_95_confidence": self.reached_sustained_95_confidence,
            "budget_exhausted": self.budget_exhausted,
            "ended_uncommitted": self.ended_uncommitted,
            "final_adequacy_state": self.final_adequacy_state,
        }


@dataclass(frozen=True, slots=True)
class ClosedLoopEvaluationRun:
    run_id: str
    evaluation_version: str
    generated_at: str
    world_config: BenchmarkWorldConfig
    seed: int
    budget_label: str
    budget: float
    arm: PrimaryArm
    commitment_id: str
    arm_run: TruthFreeClosedLoopArmRun
    metrics: ClosedLoopRunMetrics

    @property
    def world_id(self) -> str:
        return self.world_config.world_id

    @property
    def policy(self) -> str:
        return self.arm.policy

    @property
    def belief_model_id(self) -> str:
        return self.arm.belief_model_id

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "evaluation_version": self.evaluation_version,
            "timestamp": self.generated_at,
            "world_id": self.world_id,
            "seed": self.seed,
            "budget_label": self.budget_label,
            "budget": self.budget,
            "arm_id": self.arm.arm_id,
            "belief_model_id": self.belief_model_id,
            "belief_model_version": self.arm_run.spec.belief_model_version,
            "lineage_id": self.arm_run.lineage.lineage_id,
            "policy": self.policy,
            "policy_version": self.arm.policy_version,
            "commitment_id": self.commitment_id,
            "schema_version": SCHEMA_VERSION,
            "metrics": self.metrics.to_dict(),
            "final_posterior_probabilities": self.arm_run.final_posterior(),
            "arm_manifest": self.arm_run.to_truth_free_dict(),
            "evaluator_only": {
                "hidden_true_hypothesis": self.world_config.true_hypothesis_id,
                "true_optimizer_effect": self.world_config.true_optimizer_effect,
                "observation_noise_std": self.world_config.observation_noise_std,
            },
        }


@dataclass(frozen=True, slots=True)
class DecisionDivergence:
    divergence_id: str
    world_id: str
    seed: int
    budget_label: str
    budget: float
    policy: str
    fixed_run_id: str
    calibrated_run_id: str
    first_actions_differ: bool
    common_prefix_length: int
    first_divergence_step: int | None
    fixed_lineage_id: str
    calibrated_lineage_id: str
    fixed_belief_state_id: str | None
    calibrated_belief_state_id: str | None
    fixed_belief_before_divergence: tuple[tuple[str, float], ...] | None
    calibrated_belief_before_divergence: tuple[tuple[str, float], ...] | None
    fixed_selected_candidate: str | None
    calibrated_selected_candidate: str | None
    fixed_stopped_at_divergence: bool
    calibrated_stopped_at_divergence: bool
    fixed_decision_score: float | None
    calibrated_decision_score: float | None
    fixed_decision_cost: float
    calibrated_decision_cost: float
    decision_cost_difference_at_divergence: float
    decision_cost_difference: float
    nll_difference: float
    brier_difference: float
    true_probability_difference: float
    entropy_difference: float
    confidently_wrong_difference: int
    prediction_correct_difference: int
    matched_pairs_difference: int
    redundant_experiments_difference: int
    best_observed_objective_difference: float | None
    correctness_effect: str
    calibrated_delayed_commitment: bool
    calibrated_excessively_conservative: bool
    excessive_caution_reason: str | None
    trajectory_jaccard_similarity: float
    shared_candidate_count: int
    fixed_trajectory_length: int
    calibrated_trajectory_length: int
    hidden_true_hypothesis: str

    def to_dict(self) -> dict[str, object]:
        return {
            "divergence_id": self.divergence_id,
            "world_id": self.world_id,
            "seed": self.seed,
            "budget_label": self.budget_label,
            "budget": self.budget,
            "policy": self.policy,
            "fixed_run_id": self.fixed_run_id,
            "calibrated_run_id": self.calibrated_run_id,
            "first_actions_differ": self.first_actions_differ,
            "common_prefix_length": self.common_prefix_length,
            "first_divergence_step": self.first_divergence_step,
            "fixed_lineage_id": self.fixed_lineage_id,
            "calibrated_lineage_id": self.calibrated_lineage_id,
            "fixed_belief_state_id": self.fixed_belief_state_id,
            "calibrated_belief_state_id": self.calibrated_belief_state_id,
            "fixed_belief_before_divergence": (
                None
                if self.fixed_belief_before_divergence is None
                else dict(self.fixed_belief_before_divergence)
            ),
            "calibrated_belief_before_divergence": (
                None
                if self.calibrated_belief_before_divergence is None
                else dict(self.calibrated_belief_before_divergence)
            ),
            "fixed_selected_candidate": self.fixed_selected_candidate,
            "calibrated_selected_candidate": self.calibrated_selected_candidate,
            "fixed_stopped_at_divergence": self.fixed_stopped_at_divergence,
            "calibrated_stopped_at_divergence": self.calibrated_stopped_at_divergence,
            "fixed_decision_score": self.fixed_decision_score,
            "calibrated_decision_score": self.calibrated_decision_score,
            "fixed_decision_cost": self.fixed_decision_cost,
            "calibrated_decision_cost": self.calibrated_decision_cost,
            "decision_cost_difference_at_divergence": (self.decision_cost_difference_at_divergence),
            "decision_cost_difference": self.decision_cost_difference,
            "nll_difference": self.nll_difference,
            "brier_difference": self.brier_difference,
            "true_probability_difference": self.true_probability_difference,
            "entropy_difference": self.entropy_difference,
            "confidently_wrong_difference": self.confidently_wrong_difference,
            "prediction_correct_difference": self.prediction_correct_difference,
            "matched_pairs_difference": self.matched_pairs_difference,
            "redundant_experiments_difference": self.redundant_experiments_difference,
            "best_observed_objective_difference": self.best_observed_objective_difference,
            "correctness_effect": self.correctness_effect,
            "calibrated_delayed_commitment": self.calibrated_delayed_commitment,
            "calibrated_excessively_conservative": self.calibrated_excessively_conservative,
            "excessive_caution_reason": self.excessive_caution_reason,
            "trajectory_jaccard_similarity": self.trajectory_jaccard_similarity,
            "shared_candidate_count": self.shared_candidate_count,
            "fixed_trajectory_length": self.fixed_trajectory_length,
            "calibrated_trajectory_length": self.calibrated_trajectory_length,
            "evaluator_only": {"hidden_true_hypothesis": self.hidden_true_hypothesis},
        }


@dataclass(frozen=True, slots=True)
class ClosedLoopAudits:
    algorithm_hashes_unchanged: bool
    likelihood_hashes_unchanged: bool
    design_documents_unchanged: bool
    matrix_complete: bool
    hidden_truth_isolated: bool
    counterfactual_outcomes_isolated: bool
    selected_only_observation_access: bool
    deterministic_reproducibility: bool
    belief_lineages_isolated: bool
    arm_histories_isolated: bool
    common_randomness_consistent: bool
    calibration_scientific_evidence_separated: bool
    calibration_decision_costs_reconcile: bool
    fixed_policy_regression_unchanged: bool
    planner_integrity: bool
    evidence_integrity: bool
    simulated_planner_state_not_persisted: bool
    provenance_complete: bool
    statistics_complete: bool
    artifact_contract_complete: bool
    previous_evaluation_artifacts_unchanged: bool

    def to_dict(self) -> dict[str, bool]:
        return {item.name: bool(getattr(self, item.name)) for item in fields(self)}

    def all_passed(self) -> bool:
        return all(self.to_dict().values())


@dataclass(frozen=True, slots=True)
class ClosedLoopEvaluationResult:
    evaluation_version: str
    generated_at: str
    seeds: tuple[int, ...]
    budgets: tuple[tuple[str, float], ...]
    bootstrap_resamples: int
    full_frozen_matrix: bool
    prefixes: tuple[CalibrationPrefix, ...]
    potential_outcomes: tuple[PotentialOutcomeBundle, ...]
    runs: tuple[ClosedLoopEvaluationRun, ...]
    divergences: tuple[DecisionDivergence, ...]
    aggregate_rows: tuple[dict[str, object], ...]
    paired_rows: tuple[dict[str, object], ...]
    calibration_rows: tuple[dict[str, object], ...]
    acceptance: dict[str, object]
    audits: ClosedLoopAudits
    historical_artifact_hashes: tuple[tuple[str, str], ...]


def run_closed_loop_evaluation(
    *,
    seeds: tuple[int, ...] = CLOSED_LOOP_DEFAULT_SEEDS,
    short_budget: float = CLOSED_LOOP_SHORT_BUDGET,
    large_budget: float = CLOSED_LOOP_LARGE_BUDGET,
    generated_at: str,
    bootstrap_resamples: int = CLOSED_LOOP_BOOTSTRAP_RESAMPLES,
    verify_representative_replays: bool = True,
) -> ClosedLoopEvaluationResult:
    """Run four isolated arms whose own beliefs control every next experiment."""

    _validate_inputs(
        seeds=seeds,
        short_budget=short_budget,
        large_budget=large_budget,
        bootstrap_resamples=bootstrap_resamples,
    )
    repository_root = Path(__file__).resolve().parents[2]
    historical_before = _historical_artifact_hashes(repository_root)
    prefixes: list[CalibrationPrefix] = []
    outcome_bundles: list[PotentialOutcomeBundle] = []
    runs: list[ClosedLoopEvaluationRun] = []

    for world_config in paired_evaluation_worlds():
        for seed in seeds:
            design, hidden_world = build_benchmark_world(world_config, seed=seed)
            outcomes = _potential_outcomes(
                world_config=world_config,
                seed=seed,
                design=design,
                observe=hidden_world.observe,
            )
            commitment = potential_outcome_commitment(
                world_id=world_config.world_id,
                evaluation_seed=seed,
                outcomes=outcomes,
            )
            prefix = build_calibration_prefix(
                world_id=world_config.world_id,
                evaluation_seed=seed,
                designs=design.evidence_eligibility().designs,
                candidates={item.candidate_id: item for item in design.candidates},
                cost=design.cost,
                observe_pair=hidden_world.observe_calibration_pair,
                created_at=f"{generated_at}#calibration:{world_config.world_id}:{seed}",
            )
            prefixes.append(prefix)
            outcome_bundles.append(
                PotentialOutcomeBundle(
                    world_id=world_config.world_id,
                    evaluation_seed=seed,
                    commitment=commitment,
                    outcomes=outcomes,
                    calibration_prefix_id=prefix.prefix_id,
                    calibration_prefix_sha256=_stable_hash(prefix.to_dict()),
                )
            )
            oracle = SelectedOnlyObservationOracle(
                commitment=commitment,
                outcomes=outcomes,
            )
            prefix_effects = tuple(
                MatchedEffectObservation.from_calibration(item) for item in prefix.matched_effects
            )
            costs = {item.candidate_id: item.cost for item in design.candidate_costs}
            for budget_label, budget in (
                ("short", short_budget),
                ("large", large_budget),
            ):
                for arm in PRIMARY_ARMS:
                    model = belief_model(arm.belief_model_id)
                    run_id = _stable_id(
                        "closed-loop-run",
                        {
                            "arm_id": arm.arm_id,
                            "budget": budget,
                            "evaluation_seed": seed,
                            "evaluation_version": CLOSED_LOOP_EVALUATION_VERSION,
                            "world_id": world_config.world_id,
                        },
                    )
                    is_calibrated = arm.belief_model_id == CALIBRATED_SIGMA_MODEL_ID
                    spec = ClosedLoopArmSpec(
                        run_id=run_id,
                        arm_id=arm.arm_id,
                        belief_model_id=model.model_id,
                        belief_model_version=model.model_version,
                        policy=arm.policy,
                        policy_version=arm.policy_version,
                        condition_key=(
                            f"{world_config.world_id}:{seed}:{budget_label}:{arm.arm_id}"
                        ),
                        budget=budget,
                        calibration_prefix_id=prefix.prefix_id if is_calibrated else None,
                        calibration_cost=prefix.calibration_cost if is_calibrated else 0.0,
                    )
                    truth_free_run = run_closed_loop_arm(
                        spec=spec,
                        model=model,
                        candidates=design.candidates,
                        candidate_costs=costs,
                        evidence_eligibility=design.evidence_eligibility(),
                        calibration_effects=prefix_effects if is_calibrated else (),
                        oracle=oracle,
                        generated_at=generated_at,
                    )
                    metrics = score_closed_loop_run(
                        arm_run=truth_free_run,
                        design=design,
                        hidden_true_hypothesis=world_config.true_hypothesis_id,
                    )
                    runs.append(
                        ClosedLoopEvaluationRun(
                            run_id=run_id,
                            evaluation_version=CLOSED_LOOP_EVALUATION_VERSION,
                            generated_at=generated_at,
                            world_config=world_config,
                            seed=seed,
                            budget_label=budget_label,
                            budget=budget,
                            arm=arm,
                            commitment_id=commitment.commitment_id,
                            arm_run=truth_free_run,
                            metrics=metrics,
                        )
                    )

    run_tuple = tuple(runs)
    divergences = decision_divergences(run_tuple)
    aggregates = aggregate_closed_loop_runs(run_tuple)
    paired = paired_closed_loop_comparisons(
        run_tuple,
        bootstrap_resamples=bootstrap_resamples,
    )
    calibration = closed_loop_calibration_rows(run_tuple)
    historical_after = _historical_artifact_hashes(repository_root)
    deterministic = (
        _representative_replay_audit(
            runs=run_tuple,
            seeds=seeds,
            generated_at=generated_at,
            short_budget=short_budget,
            large_budget=large_budget,
        )
        if verify_representative_replays
        else True
    )
    audits = _closed_loop_audits(
        repository_root=repository_root,
        runs=run_tuple,
        prefixes=tuple(prefixes),
        outcome_bundles=tuple(outcome_bundles),
        divergences=divergences,
        aggregate_rows=aggregates,
        paired_rows=paired,
        calibration_rows=calibration,
        expected_run_count=len(seeds) * len(paired_evaluation_worlds()) * 2 * len(PRIMARY_ARMS),
        deterministic_reproducibility=deterministic,
        historical_before=historical_before,
        historical_after=historical_after,
    )
    if not audits.all_passed():
        failed = [name for name, passed in audits.to_dict().items() if not passed]
        raise ClosedLoopEvaluationInvariantError(
            "Closed-loop evaluation audits failed: " + ", ".join(failed)
        )
    full_matrix = seeds == CLOSED_LOOP_DEFAULT_SEEDS
    acceptance = closed_loop_acceptance_results(
        runs=run_tuple,
        paired_rows=paired,
        audits=audits,
        full_frozen_matrix=full_matrix,
    )
    return ClosedLoopEvaluationResult(
        evaluation_version=CLOSED_LOOP_EVALUATION_VERSION,
        generated_at=generated_at,
        seeds=seeds,
        budgets=(("short", short_budget), ("large", large_budget)),
        bootstrap_resamples=bootstrap_resamples,
        full_frozen_matrix=full_matrix,
        prefixes=tuple(prefixes),
        potential_outcomes=tuple(outcome_bundles),
        runs=run_tuple,
        divergences=divergences,
        aggregate_rows=aggregates,
        paired_rows=paired,
        calibration_rows=calibration,
        acceptance=acceptance,
        audits=audits,
        historical_artifact_hashes=historical_before,
    )


def score_closed_loop_run(
    *,
    arm_run: TruthFreeClosedLoopArmRun,
    design: BenchmarkDesign,
    hidden_true_hypothesis: str,
) -> ClosedLoopRunMetrics:
    """Score one completed truth-free arm only inside the evaluator boundary."""

    posterior = arm_run.final_posterior()
    classification = classify_posterior(posterior, hidden_true_hypothesis)
    true_probability = posterior[hidden_true_hypothesis]
    nll = -math.log(max(true_probability, NLL_PROBABILITY_FLOOR))
    brier = math.fsum(
        (probability - float(hypothesis_id == hidden_true_hypothesis)) ** 2
        for hypothesis_id, probability in posterior.items()
    )
    initial_entropy = math.log2(len(posterior))
    final_entropy = _entropy(tuple(posterior.values()))
    entropy_reduction = initial_entropy - final_entropy
    decision_cost = arm_run.trace[-1].cumulative_decision_cost if arm_run.trace else 0.0
    calibration_cost = arm_run.spec.calibration_cost
    required_total_cost = calibration_cost + decision_cost
    threshold_80 = _sustained_threshold(
        arm_run,
        hidden_true_hypothesis,
        0.80,
    )
    threshold_95 = _sustained_threshold(
        arm_run,
        hidden_true_hypothesis,
        0.95,
    )
    completed_candidates: list[Candidate] = []
    redundant_count = 0
    for experiment in arm_run.experiments:
        redundant_count += int(
            design.is_evaluator_redundant(
                experiment.candidate,
                tuple(completed_candidates),
            )
        )
        completed_candidates.append(experiment.candidate)
    true_rank = 1 + sum(
        probability > true_probability + 1e-15
        for hypothesis_id, probability in posterior.items()
        if hypothesis_id != hidden_true_hypothesis
    )
    first_commitment = next(
        (
            item
            for item in arm_run.trace
            if max(dict(item.posterior_probabilities).values()) >= CONFIDENTLY_WRONG_THRESHOLD
        ),
        None,
    )
    prior_nll = math.log(3.0)
    prior_brier = 2.0 / 3.0
    diagnostics = arm_run.diagnostics
    return ClosedLoopRunMetrics(
        final_true_hypothesis_probability=true_probability,
        negative_log_true_hypothesis_probability=nll,
        final_brier_score=brier,
        confidently_wrong=classification.confidently_wrong,
        prediction_correct=classification.correct,
        predicted_hypothesis_id=classification.predicted_hypothesis_id,
        maximum_posterior_probability=classification.maximum_posterior_probability,
        final_true_hypothesis_rank=true_rank,
        final_posterior_entropy=final_entropy,
        final_entropy_reduction=entropy_reduction,
        reached_sustained_80_confidence=threshold_80[0] is not None,
        reached_sustained_95_confidence=threshold_95[0] is not None,
        experiments_to_sustained_80_confidence=threshold_80[0],
        experiments_to_sustained_95_confidence=threshold_95[0],
        decision_cost_to_sustained_80_confidence=threshold_80[1],
        decision_cost_to_sustained_95_confidence=threshold_95[1],
        total_cost_to_sustained_80_confidence=(
            None if threshold_80[1] is None else threshold_80[1] + calibration_cost
        ),
        total_cost_to_sustained_95_confidence=(
            None if threshold_95[1] is None else threshold_95[1] + calibration_cost
        ),
        confidence_80_reversals=threshold_80[2],
        confidence_95_reversals=threshold_95[2],
        matched_evidence_pairs_completed=len(arm_run.model_updates),
        redundant_experiments_selected=redundant_count,
        decision_cost=decision_cost,
        calibration_cost=calibration_cost,
        required_total_cost=required_total_cost,
        conditional_nll_efficiency=_score_efficiency(prior_nll - nll, decision_cost),
        conditional_brier_efficiency=_score_efficiency(prior_brier - brier, decision_cost),
        conditional_entropy_efficiency=_score_efficiency(entropy_reduction, decision_cost),
        end_to_end_nll_efficiency=_score_efficiency(prior_nll - nll, required_total_cost),
        end_to_end_brier_efficiency=_score_efficiency(
            prior_brier - brier,
            required_total_cost,
        ),
        end_to_end_entropy_efficiency=_score_efficiency(
            entropy_reduction,
            required_total_cost,
        ),
        budget_exhausted=arm_run.budget_exhausted,
        experiments_completed=len(arm_run.experiments),
        best_observed_objective=(
            None if not arm_run.trace else arm_run.trace[-1].best_observed_objective
        ),
        cumulative_predictive_log_likelihood=math.fsum(
            item.predictive_log_likelihood for item in diagnostics
        ),
        mean_predictive_log_likelihood=(
            None
            if not diagnostics
            else statistics.fmean(item.predictive_log_likelihood for item in diagnostics)
        ),
        first_commitment_step=None if first_commitment is None else first_commitment.step,
        first_commitment_decision_cost=(
            None if first_commitment is None else first_commitment.cumulative_decision_cost
        ),
        ended_uncommitted=classification.maximum_posterior_probability < 0.80,
        final_adequacy_state=(diagnostics[-1].adequacy_state if diagnostics else "uncertain"),
    )


def _sustained_threshold(
    arm_run: TruthFreeClosedLoopArmRun,
    true_hypothesis_id: str,
    threshold: float,
) -> tuple[int | None, float | None, int]:
    values = tuple(dict(item.posterior_probabilities)[true_hypothesis_id] for item in arm_run.trace)
    sustained_index = next(
        (
            index
            for index, value in enumerate(values)
            if value >= threshold and all(later >= threshold for later in values[index:])
        ),
        None,
    )
    reversals = sum(
        left >= threshold and right < threshold
        for left, right in zip(values, values[1:], strict=False)
    )
    if sustained_index is None:
        return None, None, reversals
    item = arm_run.trace[sustained_index]
    return item.step, item.cumulative_decision_cost, reversals


def _score_efficiency(score_gain: float, cost: float) -> float | None:
    return None if cost <= 0.0 else score_gain / cost


def _potential_outcomes(
    *,
    world_config: BenchmarkWorldConfig,
    seed: int,
    design: BenchmarkDesign,
    observe: Callable[[Candidate], float],
) -> tuple[PotentialOutcome, ...]:
    outcomes: list[PotentialOutcome] = []
    for candidate in sorted(design.candidates, key=lambda item: item.candidate_id):
        candidate_design_key = (
            candidate.learning_rate,
            candidate.regularization,
            candidate.model_width,
            candidate.optimizer,
        )
        key_material = f"{world_config.world_id}|{seed}|{candidate_design_key}"
        observed = observe(candidate)
        outcomes.append(
            PotentialOutcome(
                candidate_id=candidate.candidate_id,
                observed_value=observed,
                key_material=key_material,
                key_sha256=hashlib.sha256(key_material.encode("utf-8")).hexdigest(),
            )
        )
    return tuple(outcomes)


PAIRED_METRIC_DIRECTIONS: dict[str, BetterDirection] = {
    "final_true_hypothesis_probability": "higher",
    "negative_log_true_hypothesis_probability": "lower",
    "final_brier_score": "lower",
    "confidently_wrong": "lower",
    "prediction_correct": "higher",
    "maximum_posterior_probability": "higher",
    "final_true_hypothesis_rank": "lower",
    "final_posterior_entropy": "lower",
    "final_entropy_reduction": "higher",
    "reached_sustained_80_confidence": "higher",
    "reached_sustained_95_confidence": "higher",
    "experiments_to_sustained_80_confidence": "lower",
    "experiments_to_sustained_95_confidence": "lower",
    "decision_cost_to_sustained_80_confidence": "lower",
    "decision_cost_to_sustained_95_confidence": "lower",
    "total_cost_to_sustained_80_confidence": "lower",
    "total_cost_to_sustained_95_confidence": "lower",
    "confidence_80_reversals": "lower",
    "confidence_95_reversals": "lower",
    "matched_evidence_pairs_completed": "higher",
    "redundant_experiments_selected": "lower",
    "decision_cost": "lower",
    "calibration_cost": "lower",
    "required_total_cost": "lower",
    "conditional_nll_efficiency": "higher",
    "conditional_brier_efficiency": "higher",
    "conditional_entropy_efficiency": "higher",
    "end_to_end_nll_efficiency": "higher",
    "end_to_end_brier_efficiency": "higher",
    "end_to_end_entropy_efficiency": "higher",
    "budget_exhausted": "lower",
    "experiments_completed": "lower",
    "best_observed_objective": "higher",
    "cumulative_predictive_log_likelihood": "higher",
    "mean_predictive_log_likelihood": "higher",
    "first_commitment_step": "lower",
    "first_commitment_decision_cost": "lower",
    "ended_uncommitted": "lower",
}


def decision_divergences(
    runs: tuple[ClosedLoopEvaluationRun, ...],
) -> tuple[DecisionDivergence, ...]:
    """Compare fixed and calibrated trajectories within one unchanged policy."""

    by_condition = {
        (run.world_id, run.seed, run.budget_label, run.policy, run.belief_model_id): run
        for run in runs
    }
    records: list[DecisionDivergence] = []
    conditions = sorted({(run.world_id, run.seed, run.budget_label, run.policy) for run in runs})
    for world_id, seed, budget_label, policy in conditions:
        fixed = by_condition[(world_id, seed, budget_label, policy, FIXED_SIGMA_MODEL_ID)]
        calibrated = by_condition[(world_id, seed, budget_label, policy, CALIBRATED_SIGMA_MODEL_ID)]
        fixed_ids = tuple(item.candidate.candidate_id for item in fixed.arm_run.experiments)
        calibrated_ids = tuple(
            item.candidate.candidate_id for item in calibrated.arm_run.experiments
        )
        common_prefix = 0
        for left, right in zip(fixed_ids, calibrated_ids, strict=False):
            if left != right:
                break
            common_prefix += 1
        diverged = common_prefix < max(len(fixed_ids), len(calibrated_ids))
        divergence_step = common_prefix + 1 if diverged else None
        fixed_decision = (
            fixed.arm_run.decisions[common_prefix]
            if common_prefix < len(fixed.arm_run.decisions)
            else None
        )
        calibrated_decision = (
            calibrated.arm_run.decisions[common_prefix]
            if common_prefix < len(calibrated.arm_run.decisions)
            else None
        )
        nll_difference = (
            calibrated.metrics.negative_log_true_hypothesis_probability
            - fixed.metrics.negative_log_true_hypothesis_probability
        )
        brier_difference = calibrated.metrics.final_brier_score - fixed.metrics.final_brier_score
        if nll_difference < -COMPARISON_TOLERANCE and brier_difference < -COMPARISON_TOLERANCE:
            correctness_effect = "helped"
        elif nll_difference > COMPARISON_TOLERANCE and brier_difference > COMPARISON_TOLERANCE:
            correctness_effect = "hurt"
        elif math.isclose(nll_difference, 0.0, abs_tol=COMPARISON_TOLERANCE) and math.isclose(
            brier_difference,
            0.0,
            abs_tol=COMPARISON_TOLERANCE,
        ):
            correctness_effect = "tied"
        else:
            correctness_effect = "mixed"
        fixed_commitment = fixed.metrics.first_commitment_step
        calibrated_commitment = calibrated.metrics.first_commitment_step
        delayed_commitment = fixed_commitment is not None and (
            calibrated_commitment is None or calibrated_commitment > fixed_commitment
        )
        excessive, caution_reason = _excessive_caution(fixed, calibrated)
        fixed_set = set(fixed_ids)
        calibrated_set = set(calibrated_ids)
        union = fixed_set.union(calibrated_set)
        shared = fixed_set.intersection(calibrated_set)
        jaccard = 1.0 if not union else len(shared) / len(union)
        fixed_cost_at_divergence = _cost_at_decision_index(fixed, common_prefix)
        calibrated_cost_at_divergence = _cost_at_decision_index(calibrated, common_prefix)
        records.append(
            DecisionDivergence(
                divergence_id=_stable_id(
                    "divergence",
                    {
                        "budget_label": budget_label,
                        "calibrated_run_id": calibrated.run_id,
                        "fixed_run_id": fixed.run_id,
                        "policy": policy,
                        "seed": seed,
                        "world_id": world_id,
                    },
                ),
                world_id=world_id,
                seed=seed,
                budget_label=budget_label,
                budget=fixed.budget,
                policy=policy,
                fixed_run_id=fixed.run_id,
                calibrated_run_id=calibrated.run_id,
                first_actions_differ=fixed_ids[:1] != calibrated_ids[:1],
                common_prefix_length=common_prefix,
                first_divergence_step=divergence_step,
                fixed_lineage_id=fixed.arm_run.lineage.lineage_id,
                calibrated_lineage_id=calibrated.arm_run.lineage.lineage_id,
                fixed_belief_state_id=(
                    None if fixed_decision is None else fixed_decision.belief_state_id
                ),
                calibrated_belief_state_id=(
                    None if calibrated_decision is None else calibrated_decision.belief_state_id
                ),
                fixed_belief_before_divergence=_decision_probabilities(fixed_decision),
                calibrated_belief_before_divergence=_decision_probabilities(calibrated_decision),
                fixed_selected_candidate=(
                    None if fixed_decision is None else fixed_decision.selected_candidate_id
                ),
                calibrated_selected_candidate=(
                    None
                    if calibrated_decision is None
                    else calibrated_decision.selected_candidate_id
                ),
                fixed_stopped_at_divergence=fixed_decision is None and diverged,
                calibrated_stopped_at_divergence=(calibrated_decision is None and diverged),
                fixed_decision_score=_decision_score(fixed_decision),
                calibrated_decision_score=_decision_score(calibrated_decision),
                fixed_decision_cost=fixed.metrics.decision_cost,
                calibrated_decision_cost=calibrated.metrics.decision_cost,
                decision_cost_difference_at_divergence=(
                    calibrated_cost_at_divergence - fixed_cost_at_divergence
                ),
                decision_cost_difference=(
                    calibrated.metrics.decision_cost - fixed.metrics.decision_cost
                ),
                nll_difference=nll_difference,
                brier_difference=brier_difference,
                true_probability_difference=(
                    calibrated.metrics.final_true_hypothesis_probability
                    - fixed.metrics.final_true_hypothesis_probability
                ),
                entropy_difference=(
                    calibrated.metrics.final_posterior_entropy
                    - fixed.metrics.final_posterior_entropy
                ),
                confidently_wrong_difference=(
                    int(calibrated.metrics.confidently_wrong) - int(fixed.metrics.confidently_wrong)
                ),
                prediction_correct_difference=(
                    int(calibrated.metrics.prediction_correct)
                    - int(fixed.metrics.prediction_correct)
                ),
                matched_pairs_difference=(
                    calibrated.metrics.matched_evidence_pairs_completed
                    - fixed.metrics.matched_evidence_pairs_completed
                ),
                redundant_experiments_difference=(
                    calibrated.metrics.redundant_experiments_selected
                    - fixed.metrics.redundant_experiments_selected
                ),
                best_observed_objective_difference=_optional_difference(
                    calibrated.metrics.best_observed_objective,
                    fixed.metrics.best_observed_objective,
                ),
                correctness_effect=correctness_effect,
                calibrated_delayed_commitment=delayed_commitment,
                calibrated_excessively_conservative=excessive,
                excessive_caution_reason=caution_reason,
                trajectory_jaccard_similarity=jaccard,
                shared_candidate_count=len(shared),
                fixed_trajectory_length=len(fixed_ids),
                calibrated_trajectory_length=len(calibrated_ids),
                hidden_true_hypothesis=fixed.world_config.true_hypothesis_id,
            )
        )
    return tuple(records)


def _decision_probabilities(
    decision: ClosedLoopDecisionTrace | None,
) -> tuple[tuple[str, float], ...] | None:
    if decision is None:
        return None
    trace = decision.policy_trace
    if isinstance(trace, LookaheadPlanTrace):
        return trace.current_hypothesis_probabilities
    if isinstance(trace, DecisionTrace):
        return tuple((item.hypothesis_id, item.posterior_probability) for item in trace.hypotheses)
    return None


def _decision_score(decision: ClosedLoopDecisionTrace | None) -> float | None:
    if decision is None:
        return None
    return decision.expected_total_information_gain


def _cost_at_decision_index(run: ClosedLoopEvaluationRun, index: int) -> float:
    if index < len(run.arm_run.experiments):
        return run.arm_run.experiments[index].cumulative_decision_cost
    return run.metrics.decision_cost


def _optional_difference(left: float | None, right: float | None) -> float | None:
    return None if left is None or right is None else left - right


def _excessive_caution(
    fixed: ClosedLoopEvaluationRun,
    calibrated: ClosedLoopEvaluationRun,
) -> tuple[bool, str | None]:
    if (
        fixed.metrics.reached_sustained_80_confidence
        and not calibrated.metrics.reached_sustained_80_confidence
    ):
        return True, "Calibrated control failed a sustained correct 0.80 crossing reached by fixed."
    if (
        calibrated.metrics.decision_cost > fixed.metrics.decision_cost + COMPARISON_TOLERANCE
        and calibrated.metrics.negative_log_true_hypothesis_probability
        >= fixed.metrics.negative_log_true_hypothesis_probability - COMPARISON_TOLERANCE
        and calibrated.metrics.final_brier_score
        >= fixed.metrics.final_brier_score - COMPARISON_TOLERANCE
    ):
        return True, "Calibrated control spent more decision cost without improving proper scores."
    if (
        calibrated.metrics.ended_uncommitted
        and fixed.metrics.prediction_correct
        and not fixed.metrics.ended_uncommitted
    ):
        return True, "Calibrated control ended uncommitted while fixed ended correctly committed."
    return False, None


def aggregate_closed_loop_runs(
    runs: tuple[ClosedLoopEvaluationRun, ...],
) -> tuple[dict[str, object], ...]:
    """Aggregate every numeric metric by arm, world, and budget."""

    rows: list[dict[str, object]] = []
    for world in paired_evaluation_worlds():
        for budget_label in ("short", "large"):
            for arm in PRIMARY_ARMS:
                group = tuple(
                    item
                    for item in runs
                    if item.world_id == world.world_id
                    and item.budget_label == budget_label
                    and item.arm.arm_id == arm.arm_id
                )
                if not group:
                    continue
                for metric in group[0].metrics.numeric_values():
                    values = tuple(
                        value
                        for item in group
                        if (value := item.metrics.numeric_values()[metric]) is not None
                    )
                    if values:
                        rows.append(
                            _aggregate_row(
                                group=group,
                                arm=arm,
                                metric=metric,
                                values=values,
                            )
                        )
                ece = top_label_expected_calibration_error(
                    tuple(
                        (
                            item.metrics.maximum_posterior_probability,
                            item.metrics.prediction_correct,
                        )
                        for item in group
                    )
                )
                rows.append(
                    {
                        "world_id": world.world_id,
                        "budget_label": budget_label,
                        "budget": group[0].budget,
                        "arm_id": arm.arm_id,
                        "belief_model_id": arm.belief_model_id,
                        "policy": arm.policy,
                        "metric": "calibration_error",
                        "sample_count": len(group),
                        "mean": ece,
                        "median": None,
                        "standard_deviation": None,
                        "confidence_interval_low": None,
                        "confidence_interval_high": None,
                        "confidence_interval_method": "aggregate top-label ECE",
                    }
                )
    return tuple(rows)


def _aggregate_row(
    *,
    group: tuple[ClosedLoopEvaluationRun, ...],
    arm: PrimaryArm,
    metric: str,
    values: tuple[float, ...],
) -> dict[str, object]:
    mean = statistics.fmean(values)
    deviation = statistics.stdev(values) if len(values) > 1 else 0.0
    margin = 1.96 * deviation / math.sqrt(len(values))
    return {
        "world_id": group[0].world_id,
        "budget_label": group[0].budget_label,
        "budget": group[0].budget,
        "arm_id": arm.arm_id,
        "belief_model_id": arm.belief_model_id,
        "policy": arm.policy,
        "metric": metric,
        "sample_count": len(values),
        "mean": mean,
        "median": statistics.median(values),
        "standard_deviation": deviation,
        "confidence_interval_low": mean - margin,
        "confidence_interval_high": mean + margin,
        "confidence_interval_method": "95 percent normal approximation for aggregate mean",
    }


def closed_loop_calibration_rows(
    runs: tuple[ClosedLoopEvaluationRun, ...],
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for world in paired_evaluation_worlds():
        for budget_label in ("short", "large"):
            for arm in PRIMARY_ARMS:
                group = tuple(
                    item
                    for item in runs
                    if item.world_id == world.world_id
                    and item.budget_label == budget_label
                    and item.arm.arm_id == arm.arm_id
                )
                if not group:
                    continue
                rows.append(
                    {
                        "world_id": world.world_id,
                        "budget_label": budget_label,
                        "budget": group[0].budget,
                        "arm_id": arm.arm_id,
                        "belief_model_id": arm.belief_model_id,
                        "policy": arm.policy,
                        "run_count": len(group),
                        "accuracy": statistics.fmean(
                            float(item.metrics.prediction_correct) for item in group
                        ),
                        "mean_confidence": statistics.fmean(
                            item.metrics.maximum_posterior_probability for item in group
                        ),
                        "calibration_error": top_label_expected_calibration_error(
                            tuple(
                                (
                                    item.metrics.maximum_posterior_probability,
                                    item.metrics.prediction_correct,
                                )
                                for item in group
                            )
                        ),
                        "confidently_wrong_count": sum(
                            item.metrics.confidently_wrong for item in group
                        ),
                        "confidently_wrong_rate": statistics.fmean(
                            float(item.metrics.confidently_wrong) for item in group
                        ),
                        "mean_nll": statistics.fmean(
                            item.metrics.negative_log_true_hypothesis_probability for item in group
                        ),
                        "mean_brier_score": statistics.fmean(
                            item.metrics.final_brier_score for item in group
                        ),
                    }
                )
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class _ComparisonScope:
    scope: str
    world_id: str
    budget_label: str
    policy: str
    runs: tuple[ClosedLoopEvaluationRun, ...]


def paired_closed_loop_comparisons(
    runs: tuple[ClosedLoopEvaluationRun, ...],
    *,
    bootstrap_resamples: int,
) -> tuple[dict[str, object], ...]:
    """Report calibrated-minus-fixed seed-blocked comparisons for every frozen scope."""

    rows: list[dict[str, object]] = []
    for scope in _comparison_scopes(runs):
        for metric, direction in PAIRED_METRIC_DIRECTIONS.items():
            row = _paired_metric_row(
                scope,
                metric=metric,
                direction=direction,
                bootstrap_resamples=bootstrap_resamples,
            )
            if row is not None:
                rows.append(row)
        rows.append(
            _paired_ece_row(
                scope,
                bootstrap_resamples=bootstrap_resamples,
            )
        )
    return tuple(rows)


def closed_loop_acceptance_results(
    *,
    runs: tuple[ClosedLoopEvaluationRun, ...],
    paired_rows: tuple[dict[str, object], ...],
    audits: ClosedLoopAudits,
    full_frozen_matrix: bool,
) -> dict[str, object]:
    """Evaluate every frozen closed-loop acceptance inequality exactly once."""

    gates: list[dict[str, object]] = []

    def row(
        scope: str,
        world_id: str,
        budget_label: str,
        policy: str,
        metric: str,
    ) -> dict[str, object]:
        matches = tuple(
            item
            for item in paired_rows
            if item["scope"] == scope
            and item["world_id"] == world_id
            and item["budget_label"] == budget_label
            and item["policy"] == policy
            and item["metric"] == metric
        )
        if len(matches) != 1:
            raise ClosedLoopEvaluationInvariantError(
                "Required paired comparison row is missing or ambiguous: "
                f"{scope}/{world_id}/{budget_label}/{policy}/{metric}."
            )
        return matches[0]

    def add(
        *,
        gate_group: str,
        gate_id: str,
        comparison: dict[str, object],
        statistic: Literal["mean", "lower_95", "upper_95"],
        operator: Literal["<", "<=", ">", ">="],
        threshold: float,
    ) -> None:
        key = {
            "mean": "mean_paired_difference",
            "lower_95": "confidence_interval_low",
            "upper_95": "confidence_interval_high",
        }[statistic]
        value = cast(float, comparison[key])
        gates.append(
            {
                "gate_group": gate_group,
                "gate_id": gate_id,
                "scope": comparison["scope"],
                "world_id": comparison["world_id"],
                "budget_label": comparison["budget_label"],
                "policy": comparison["policy"],
                "metric": comparison["metric"],
                "fixed_value": comparison["fixed_value"],
                "calibrated_value": comparison["calibrated_value"],
                "paired_difference": comparison["mean_paired_difference"],
                "paired_95_ci_low": comparison["confidence_interval_low"],
                "paired_95_ci_high": comparison["confidence_interval_high"],
                "evaluated_statistic": statistic,
                "evaluated_value": value,
                "operator": operator,
                "required_threshold": threshold,
                "passed": _compare(value, operator, threshold),
            }
        )

    adverse = "adverse_noisy_observations"
    delayed = "delayed_information"
    adverse_world = {
        metric: row("world", adverse, "all", "all", metric)
        for metric in (
            "confidently_wrong",
            "negative_log_true_hypothesis_probability",
            "final_brier_score",
            "calibration_error",
            "conditional_nll_efficiency",
            "conditional_brier_efficiency",
            "end_to_end_nll_efficiency",
            "end_to_end_brier_efficiency",
        )
    }
    add(
        gate_group="1_adverse_confidently_wrong",
        gate_id="adverse_pooled_confidently_wrong_mean",
        comparison=adverse_world["confidently_wrong"],
        statistic="mean",
        operator="<=",
        threshold=-0.10,
    )
    add(
        gate_group="1_adverse_confidently_wrong",
        gate_id="adverse_pooled_confidently_wrong_upper_95",
        comparison=adverse_world["confidently_wrong"],
        statistic="upper_95",
        operator="<",
        threshold=0.0,
    )
    for budget_label in ("short", "large"):
        for policy in (INFORMATION_GAIN_POLICY, LOOKAHEAD_INFORMATION_GAIN_POLICY):
            add(
                gate_group="1_adverse_confidently_wrong",
                gate_id=f"adverse_{policy}_{budget_label}_confidently_wrong_mean",
                comparison=row(
                    "cell",
                    adverse,
                    budget_label,
                    policy,
                    "confidently_wrong",
                ),
                statistic="mean",
                operator="<=",
                threshold=0.02,
            )
    for metric, label, upper_operator in (
        ("negative_log_true_hypothesis_probability", "nll", "<"),
        ("final_brier_score", "brier", "<"),
        ("calibration_error", "ece", "<="),
    ):
        add(
            gate_group="2_adverse_proper_scores",
            gate_id=f"adverse_pooled_{label}_mean",
            comparison=adverse_world[metric],
            statistic="mean",
            operator="<",
            threshold=0.0,
        )
        add(
            gate_group="2_adverse_proper_scores",
            gate_id=f"adverse_pooled_{label}_upper_95",
            comparison=adverse_world[metric],
            statistic="upper_95",
            operator=cast(Literal["<", "<=", ">", ">="], upper_operator),
            threshold=0.0,
        )

    delayed_world = {
        metric: row("world", delayed, "all", "all", metric)
        for metric in (
            "final_true_hypothesis_probability",
            "negative_log_true_hypothesis_probability",
            "final_brier_score",
            "confidently_wrong",
            "reached_sustained_80_confidence",
            "reached_sustained_95_confidence",
        )
    }
    delayed_specs = (
        (
            "delayed_true_probability_mean",
            "final_true_hypothesis_probability",
            "mean",
            ">=",
            -0.02,
        ),
        (
            "delayed_true_probability_lower_95",
            "final_true_hypothesis_probability",
            "lower_95",
            ">=",
            -0.05,
        ),
        (
            "delayed_nll_mean",
            "negative_log_true_hypothesis_probability",
            "mean",
            "<=",
            0.05,
        ),
        (
            "delayed_nll_upper_95",
            "negative_log_true_hypothesis_probability",
            "upper_95",
            "<=",
            0.10,
        ),
        ("delayed_brier_mean", "final_brier_score", "mean", "<=", 0.02),
        (
            "delayed_brier_upper_95",
            "final_brier_score",
            "upper_95",
            "<=",
            0.04,
        ),
        ("delayed_confidently_wrong_mean", "confidently_wrong", "mean", "<=", 0.0),
        (
            "delayed_sustained_80_rate_mean",
            "reached_sustained_80_confidence",
            "mean",
            ">=",
            -0.05,
        ),
        (
            "delayed_sustained_95_rate_mean",
            "reached_sustained_95_confidence",
            "mean",
            ">=",
            -0.05,
        ),
    )
    for gate_id, metric, statistic, operator, threshold in delayed_specs:
        add(
            gate_group="3_delayed_non_regression",
            gate_id=gate_id,
            comparison=delayed_world[metric],
            statistic=cast(Literal["mean", "lower_95", "upper_95"], statistic),
            operator=cast(Literal["<", "<=", ">", ">="], operator),
            threshold=threshold,
        )

    for world_id in ("no_optimizer_advantage", "asymmetric_experiment_costs"):
        for policy in (INFORMATION_GAIN_POLICY, LOOKAHEAD_INFORMATION_GAIN_POLICY):
            for metric, label, threshold in (
                ("negative_log_true_hypothesis_probability", "nll", 0.05),
                ("final_brier_score", "brier", 0.02),
                ("confidently_wrong", "confidently_wrong", 0.02),
                ("calibration_error", "ece", 0.05),
            ):
                add(
                    gate_group="4_other_world_non_regression",
                    gate_id=f"{world_id}_{policy}_{label}_mean",
                    comparison=row("world_policy", world_id, "all", policy, metric),
                    statistic="mean",
                    operator="<=",
                    threshold=threshold,
                )

    for world in paired_evaluation_worlds():
        for budget_label, budget in (
            ("short", CLOSED_LOOP_SHORT_BUDGET),
            ("large", CLOSED_LOOP_LARGE_BUDGET),
        ):
            for policy in (INFORMATION_GAIN_POLICY, LOOKAHEAD_INFORMATION_GAIN_POLICY):
                decision_cost = row(
                    "cell",
                    world.world_id,
                    budget_label,
                    policy,
                    "decision_cost",
                )
                exhaustion = row(
                    "cell",
                    world.world_id,
                    budget_label,
                    policy,
                    "budget_exhausted",
                )
                stem = f"{world.world_id}_{policy}_{budget_label}"
                add(
                    gate_group="5_decision_cost_control",
                    gate_id=f"{stem}_decision_cost_mean",
                    comparison=decision_cost,
                    statistic="mean",
                    operator="<=",
                    threshold=0.10 * budget,
                )
                add(
                    gate_group="5_decision_cost_control",
                    gate_id=f"{stem}_decision_cost_upper_95",
                    comparison=decision_cost,
                    statistic="upper_95",
                    operator="<=",
                    threshold=0.20 * budget,
                )
                add(
                    gate_group="5_decision_cost_control",
                    gate_id=f"{stem}_exhaustion_mean",
                    comparison=exhaustion,
                    statistic="mean",
                    operator="<=",
                    threshold=0.05,
                )

    for metric, label in (
        ("conditional_nll_efficiency", "nll"),
        ("conditional_brier_efficiency", "brier"),
    ):
        add(
            gate_group="6_adverse_conditional_efficiency",
            gate_id=f"adverse_conditional_{label}_efficiency_mean",
            comparison=adverse_world[metric],
            statistic="mean",
            operator=">",
            threshold=0.0,
        )
        add(
            gate_group="6_adverse_conditional_efficiency",
            gate_id=f"adverse_conditional_{label}_efficiency_lower_95",
            comparison=adverse_world[metric],
            statistic="lower_95",
            operator=">",
            threshold=0.0,
        )

    global_rows = {
        metric: row("global", "all", "all", "all", metric)
        for metric in ("end_to_end_nll_efficiency", "end_to_end_brier_efficiency")
    }
    for metric, label in (
        ("end_to_end_nll_efficiency", "nll"),
        ("end_to_end_brier_efficiency", "brier"),
    ):
        add(
            gate_group="7_end_to_end_efficiency",
            gate_id=f"adverse_end_to_end_{label}_efficiency_mean",
            comparison=adverse_world[metric],
            statistic="mean",
            operator=">",
            threshold=0.0,
        )
        add(
            gate_group="7_end_to_end_efficiency",
            gate_id=f"adverse_end_to_end_{label}_efficiency_lower_95",
            comparison=adverse_world[metric],
            statistic="lower_95",
            operator=">",
            threshold=0.0,
        )
        add(
            gate_group="7_end_to_end_efficiency",
            gate_id=f"global_end_to_end_{label}_efficiency_mean",
            comparison=global_rows[metric],
            statistic="mean",
            operator=">=",
            threshold=0.0,
        )
        add(
            gate_group="7_end_to_end_efficiency",
            gate_id=f"global_end_to_end_{label}_efficiency_lower_95",
            comparison=global_rows[metric],
            statistic="lower_95",
            operator=">=",
            threshold=0.0,
        )

    hard_gates = tuple(
        {
            "gate_id": name,
            "metric": name,
            "fixed_value": None,
            "calibrated_value": None,
            "paired_difference": None,
            "paired_95_ci_low": None,
            "paired_95_ci_high": None,
            "required_threshold": True,
            "passed": passed,
        }
        for name, passed in audits.to_dict().items()
    )
    performance_passed = all(cast(bool, item["passed"]) for item in gates)
    science_and_cost_gates_passed = all(
        cast(bool, item["passed"])
        for item in gates
        if item["gate_group"] != "7_end_to_end_efficiency"
    )
    end_to_end_gates_passed = all(
        cast(bool, item["passed"])
        for item in gates
        if item["gate_group"] == "7_end_to_end_efficiency"
    )
    intervals_reported = all(
        item["confidence_interval_low"] is not None and item["confidence_interval_high"] is not None
        for item in paired_rows
    )
    hard_passed = audits.all_passed() and intervals_reported
    accepted = full_frozen_matrix and hard_passed and performance_passed
    if not full_frozen_matrix:
        verdict = "smoke_only"
    elif accepted:
        verdict = "calibrated_closed_loop_control_accepted"
    elif science_and_cost_gates_passed and not end_to_end_gates_passed:
        verdict = "scientifically_improved_but_not_end_to_end_efficient"
    else:
        verdict = "closed_loop_acceptance_failed"
    return {
        "evaluation_version": CLOSED_LOOP_EVALUATION_VERSION,
        "difference_definition": "calibrated minus fixed within unchanged policy",
        "full_frozen_matrix": full_frozen_matrix,
        "run_count": len(runs),
        "hard_gates": hard_gates,
        "performance_gates": tuple(gates),
        "paired_confidence_intervals_reported": intervals_reported,
        "all_hard_gates_passed": hard_passed,
        "all_performance_gates_passed": performance_passed,
        "scientific_and_cost_gates_1_through_6_passed": (science_and_cost_gates_passed),
        "end_to_end_efficiency_gate_7_passed": end_to_end_gates_passed,
        "calibrated_closed_loop_control_accepted": accepted,
        "default_belief_interpreter": CALIBRATED_SIGMA_MODEL_ID,
        "preferred_closed_loop_controller": (
            CALIBRATED_SIGMA_MODEL_ID if accepted else FIXED_SIGMA_MODEL_ID
        ),
        "verdict": verdict,
    }


def _compare(
    value: float,
    operator: Literal["<", "<=", ">", ">="],
    threshold: float,
) -> bool:
    if operator == "<":
        return value < threshold
    if operator == "<=":
        return value <= threshold
    if operator == ">":
        return value > threshold
    return value >= threshold


def _comparison_scopes(
    runs: tuple[ClosedLoopEvaluationRun, ...],
) -> tuple[_ComparisonScope, ...]:
    scopes: list[_ComparisonScope] = []
    for world in paired_evaluation_worlds():
        world_runs = tuple(item for item in runs if item.world_id == world.world_id)
        for budget_label in ("short", "large"):
            for policy in (INFORMATION_GAIN_POLICY, LOOKAHEAD_INFORMATION_GAIN_POLICY):
                scopes.append(
                    _ComparisonScope(
                        scope="cell",
                        world_id=world.world_id,
                        budget_label=budget_label,
                        policy=policy,
                        runs=tuple(
                            item
                            for item in world_runs
                            if item.budget_label == budget_label and item.policy == policy
                        ),
                    )
                )
        scopes.append(
            _ComparisonScope(
                scope="world",
                world_id=world.world_id,
                budget_label="all",
                policy="all",
                runs=world_runs,
            )
        )
        if world.world_id in {
            "no_optimizer_advantage",
            "asymmetric_experiment_costs",
        }:
            for policy in (INFORMATION_GAIN_POLICY, LOOKAHEAD_INFORMATION_GAIN_POLICY):
                scopes.append(
                    _ComparisonScope(
                        scope="world_policy",
                        world_id=world.world_id,
                        budget_label="all",
                        policy=policy,
                        runs=tuple(item for item in world_runs if item.policy == policy),
                    )
                )
    scopes.append(
        _ComparisonScope(
            scope="global",
            world_id="all",
            budget_label="all",
            policy="all",
            runs=runs,
        )
    )
    return tuple(scopes)


def _paired_metric_row(
    scope: _ComparisonScope,
    *,
    metric: str,
    direction: BetterDirection,
    bootstrap_resamples: int,
) -> dict[str, object] | None:
    fixed, calibrated = _paired_runs(scope.runs)
    seed_fixed: list[float] = []
    seed_calibrated: list[float] = []
    for seed in sorted({key[0] for key in fixed}):
        fixed_values: list[float] = []
        calibrated_values: list[float] = []
        for key in sorted(item for item in fixed if item[0] == seed):
            left = fixed[key].metrics.numeric_values()[metric]
            right = calibrated[key].metrics.numeric_values()[metric]
            if left is not None and right is not None:
                fixed_values.append(left)
                calibrated_values.append(right)
        if fixed_values:
            seed_fixed.append(statistics.fmean(fixed_values))
            seed_calibrated.append(statistics.fmean(calibrated_values))
    if not seed_fixed:
        return None
    differences = tuple(
        right - left for left, right in zip(seed_fixed, seed_calibrated, strict=True)
    )
    low, high = deterministic_bootstrap_mean_interval(
        differences,
        resamples=bootstrap_resamples,
        key=(
            CLOSED_LOOP_EVALUATION_VERSION,
            scope.scope,
            scope.world_id,
            scope.budget_label,
            scope.policy,
            metric,
        ),
    )
    wins, ties, losses = _win_tie_loss(differences, direction)
    deviation = statistics.stdev(differences) if len(differences) > 1 else 0.0
    return {
        "scope": scope.scope,
        "world_id": scope.world_id,
        "budget_label": scope.budget_label,
        "policy": scope.policy,
        "metric": metric,
        "better_direction": direction,
        "difference_definition": "calibrated minus fixed",
        "paired_sample_count": len(differences),
        "fixed_value": statistics.fmean(seed_fixed),
        "calibrated_value": statistics.fmean(seed_calibrated),
        "mean_paired_difference": statistics.fmean(differences),
        "median_paired_difference": statistics.median(differences),
        "standard_deviation": deviation,
        "paired_standardized_mean_difference": (
            None if deviation == 0.0 else statistics.fmean(differences) / deviation
        ),
        "confidence_interval_low": low,
        "confidence_interval_high": high,
        "confidence_interval_method": (
            "deterministic paired percentile bootstrap of seed-blocked mean"
        ),
        "wins": wins,
        "ties": ties,
        "losses": losses,
    }


def _paired_ece_row(
    scope: _ComparisonScope,
    *,
    bootstrap_resamples: int,
) -> dict[str, object]:
    fixed, calibrated = _paired_runs(scope.runs)
    seeds = tuple(sorted({key[0] for key in fixed}))
    fixed_by_seed = {
        seed: tuple(
            (
                run.metrics.maximum_posterior_probability,
                run.metrics.prediction_correct,
            )
            for key, run in sorted(fixed.items())
            if key[0] == seed
        )
        for seed in seeds
    }
    calibrated_by_seed = {
        seed: tuple(
            (
                run.metrics.maximum_posterior_probability,
                run.metrics.prediction_correct,
            )
            for key, run in sorted(calibrated.items())
            if key[0] == seed
        )
        for seed in seeds
    }
    fixed_observations = tuple(item for seed in seeds for item in fixed_by_seed[seed])
    calibrated_observations = tuple(item for seed in seeds for item in calibrated_by_seed[seed])
    fixed_value = top_label_expected_calibration_error(fixed_observations)
    calibrated_value = top_label_expected_calibration_error(calibrated_observations)
    random = Random(
        _bootstrap_seed(
            (
                CLOSED_LOOP_EVALUATION_VERSION,
                scope.scope,
                scope.world_id,
                scope.budget_label,
                scope.policy,
                "calibration_error",
            )
        )
    )
    bootstrap_differences: list[float] = []
    for _ in range(bootstrap_resamples):
        selected = tuple(seeds[random.randrange(len(seeds))] for _ in seeds)
        fixed_sample = tuple(item for seed in selected for item in fixed_by_seed[seed])
        calibrated_sample = tuple(item for seed in selected for item in calibrated_by_seed[seed])
        bootstrap_differences.append(
            top_label_expected_calibration_error(calibrated_sample)
            - top_label_expected_calibration_error(fixed_sample)
        )
    bootstrap_differences.sort()
    point_difference = calibrated_value - fixed_value
    return {
        "scope": scope.scope,
        "world_id": scope.world_id,
        "budget_label": scope.budget_label,
        "policy": scope.policy,
        "metric": "calibration_error",
        "better_direction": "lower",
        "difference_definition": "calibrated minus fixed",
        "paired_sample_count": len(seeds),
        "fixed_value": fixed_value,
        "calibrated_value": calibrated_value,
        "mean_paired_difference": point_difference,
        "median_paired_difference": statistics.median(bootstrap_differences),
        "standard_deviation": (
            statistics.stdev(bootstrap_differences) if len(bootstrap_differences) > 1 else 0.0
        ),
        "paired_standardized_mean_difference": None,
        "confidence_interval_low": _percentile(bootstrap_differences, 0.025),
        "confidence_interval_high": _percentile(bootstrap_differences, 0.975),
        "confidence_interval_method": (
            "deterministic paired seed-blocked percentile bootstrap of top-label ECE"
        ),
        "wins": None,
        "ties": None,
        "losses": None,
    }


def _paired_runs(
    runs: tuple[ClosedLoopEvaluationRun, ...],
) -> tuple[
    dict[tuple[int, str, str, str], ClosedLoopEvaluationRun],
    dict[tuple[int, str, str, str], ClosedLoopEvaluationRun],
]:
    fixed = {
        (item.seed, item.world_id, item.budget_label, item.policy): item
        for item in runs
        if item.belief_model_id == FIXED_SIGMA_MODEL_ID
    }
    calibrated = {
        (item.seed, item.world_id, item.budget_label, item.policy): item
        for item in runs
        if item.belief_model_id == CALIBRATED_SIGMA_MODEL_ID
    }
    if not fixed or fixed.keys() != calibrated.keys():
        raise ClosedLoopEvaluationInvariantError("Closed-loop comparison cells are not paired.")
    return fixed, calibrated


def _win_tie_loss(
    differences: tuple[float, ...],
    direction: BetterDirection,
) -> tuple[int, int, int]:
    wins = ties = losses = 0
    for difference in differences:
        if math.isclose(difference, 0.0, rel_tol=0.0, abs_tol=COMPARISON_TOLERANCE):
            ties += 1
        elif (direction == "higher" and difference > 0.0) or (
            direction == "lower" and difference < 0.0
        ):
            wins += 1
        else:
            losses += 1
    return wins, ties, losses


def _representative_replay_audit(
    *,
    runs: tuple[ClosedLoopEvaluationRun, ...],
    seeds: tuple[int, ...],
    generated_at: str,
    short_budget: float,
    large_budget: float,
) -> bool:
    """Replay one seed in reverse arm order without consulting evaluator truth."""

    seed = seeds[0]
    expected_by_key = {
        (run.world_id, run.budget_label, run.arm.arm_id): run for run in runs if run.seed == seed
    }
    for world_config in reversed(paired_evaluation_worlds()):
        design, hidden_world = build_benchmark_world(world_config, seed=seed)
        outcomes = _potential_outcomes(
            world_config=world_config,
            seed=seed,
            design=design,
            observe=hidden_world.observe,
        )
        commitment = potential_outcome_commitment(
            world_id=world_config.world_id,
            evaluation_seed=seed,
            outcomes=outcomes,
        )
        prefix = build_calibration_prefix(
            world_id=world_config.world_id,
            evaluation_seed=seed,
            designs=design.evidence_eligibility().designs,
            candidates={item.candidate_id: item for item in design.candidates},
            cost=design.cost,
            observe_pair=hidden_world.observe_calibration_pair,
            created_at=f"{generated_at}#calibration:{world_config.world_id}:{seed}",
        )
        oracle = SelectedOnlyObservationOracle(commitment=commitment, outcomes=outcomes)
        prefix_effects = tuple(
            MatchedEffectObservation.from_calibration(item) for item in prefix.matched_effects
        )
        costs = {item.candidate_id: item.cost for item in design.candidate_costs}
        for budget_label, expected_budget in (
            ("large", large_budget),
            ("short", short_budget),
        ):
            for arm in reversed(PRIMARY_ARMS):
                expected = expected_by_key[(world_config.world_id, budget_label, arm.arm_id)]
                if not math.isclose(
                    expected.budget,
                    expected_budget,
                    rel_tol=0.0,
                    abs_tol=COMPARISON_TOLERANCE,
                ):
                    return False
                replay = run_closed_loop_arm(
                    spec=expected.arm_run.spec,
                    model=belief_model(arm.belief_model_id),
                    candidates=design.candidates,
                    candidate_costs=costs,
                    evidence_eligibility=design.evidence_eligibility(),
                    calibration_effects=(
                        prefix_effects if arm.belief_model_id == CALIBRATED_SIGMA_MODEL_ID else ()
                    ),
                    oracle=oracle,
                    generated_at=generated_at,
                )
                if _stable_hash(replay.to_truth_free_dict()) != _stable_hash(
                    expected.arm_run.to_truth_free_dict()
                ):
                    return False
    return True


def _validate_inputs(
    *,
    seeds: tuple[int, ...],
    short_budget: float,
    large_budget: float,
    bootstrap_resamples: int,
) -> None:
    if not seeds or len(seeds) != len(set(seeds)) or any(seed < 0 for seed in seeds):
        raise ValueError("Closed-loop seeds must be non-empty, unique, and non-negative.")
    if not math.isclose(short_budget, 2.25, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("The frozen short decision budget must remain 2.25.")
    if not math.isclose(large_budget, 4.50, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("The frozen large decision budget must remain 4.50.")
    if bootstrap_resamples <= 0:
        raise ValueError("Bootstrap resamples must be positive.")
    if tuple(item.arm_id for item in PRIMARY_ARMS) != (
        "fixed_information_gain",
        "calibrated_information_gain",
        "fixed_lookahead_information_gain",
        "calibrated_lookahead_information_gain",
    ):
        raise ClosedLoopEvaluationInvariantError("The frozen four-arm matrix changed.")
    if INFORMATION_GAIN_POLICY_VERSION != "information-gain-policy/v1":
        raise ClosedLoopEvaluationInvariantError("The one-step policy version changed.")
    if LOOKAHEAD_INFORMATION_GAIN_POLICY_VERSION != "lookahead-information-gain-policy/v1":
        raise ClosedLoopEvaluationInvariantError("The lookahead policy version changed.")
    if CANDIDATE_GROUP_ADAPTER_VERSION != "candidate-group-prediction-adapter/v1":
        raise ClosedLoopEvaluationInvariantError("The frozen prediction adapter changed.")
    if CLOSED_LOOP_ARM_RUNNER_VERSION != "isolated-closed-loop-arm-runner/v1":
        raise ClosedLoopEvaluationInvariantError("The frozen arm runner version changed.")
    if SELECTED_ONLY_ORACLE_VERSION != "selected-only-common-randomness/v1":
        raise ClosedLoopEvaluationInvariantError("The frozen oracle version changed.")


def _optional_float(value: int | None) -> float | None:
    return None if value is None else float(value)


def _entropy(probabilities: tuple[float, ...]) -> float:
    return -math.fsum(value * math.log2(value) for value in probabilities if value > 0.0)


def _stable_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}-{_stable_hash(payload)[:24]}"


def _bootstrap_seed(key: tuple[object, ...]) -> int:
    material = f"{BOOTSTRAP_SEED}|" + "|".join(str(item) for item in key)
    return int.from_bytes(hashlib.sha256(material.encode("utf-8")).digest()[:8], "big")


def _percentile(sorted_values: list[float], quantile: float) -> float:
    if not sorted_values:
        raise ValueError("A percentile requires at least one value.")
    position = (len(sorted_values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] + fraction * (sorted_values[upper] - sorted_values[lower])


def _historical_artifact_hashes(repository_root: Path) -> tuple[tuple[str, str], ...]:
    return tuple(
        (name, _directory_tree_hash(repository_root / name))
        for name in HISTORICAL_ARTIFACT_DIRECTORIES
    )


def _directory_tree_hash(directory: Path) -> str:
    if not directory.is_dir():
        return "MISSING"
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _file_hash_matches(repository_root: Path, expected: dict[str, str]) -> bool:
    return all(
        (path := repository_root / relative_path).is_file()
        and hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash
        for relative_path, expected_hash in expected.items()
    )


def _closed_loop_audits(
    *,
    repository_root: Path,
    runs: tuple[ClosedLoopEvaluationRun, ...],
    prefixes: tuple[CalibrationPrefix, ...],
    outcome_bundles: tuple[PotentialOutcomeBundle, ...],
    divergences: tuple[DecisionDivergence, ...],
    aggregate_rows: tuple[dict[str, object], ...],
    paired_rows: tuple[dict[str, object], ...],
    calibration_rows: tuple[dict[str, object], ...],
    expected_run_count: int,
    deterministic_reproducibility: bool,
    historical_before: tuple[tuple[str, str], ...],
    historical_after: tuple[tuple[str, str], ...],
) -> ClosedLoopAudits:
    algorithm_paths = {
        name: digest
        for name, digest in FROZEN_SOURCE_SHA256.items()
        if name
        in {
            "research_decision_engine/policies.py",
            "research_decision_engine/decision.py",
            "research_decision_engine/lookahead.py",
            "research_decision_engine/evidence_eligibility.py",
            "research_decision_engine/benchmarks/worlds.py",
            "research_decision_engine/benchmarks/paired_evaluation.py",
        }
    }
    likelihood_paths = {
        name: digest
        for name, digest in FROZEN_SOURCE_SHA256.items()
        if name
        in {
            "research_decision_engine/reasoning.py",
            "research_decision_engine/optimizer_effect.py",
            "research_decision_engine/belief_models.py",
            "research_decision_engine/calibration.py",
        }
    }
    return ClosedLoopAudits(
        algorithm_hashes_unchanged=(
            _file_hash_matches(repository_root, algorithm_paths)
            and all(
                decision.fixed_policy_regression_match
                for run in runs
                if run.belief_model_id == FIXED_SIGMA_MODEL_ID
                for decision in run.arm_run.decisions
            )
        ),
        likelihood_hashes_unchanged=_file_hash_matches(repository_root, likelihood_paths),
        design_documents_unchanged=_file_hash_matches(
            repository_root,
            FROZEN_DESIGN_SHA256,
        ),
        matrix_complete=_matrix_audit(runs, expected_run_count),
        hidden_truth_isolated=_truth_isolation_audit(runs),
        counterfactual_outcomes_isolated=_counterfactual_isolation_audit(),
        selected_only_observation_access=_selected_only_audit(runs),
        deterministic_reproducibility=deterministic_reproducibility,
        belief_lineages_isolated=_lineage_isolation_audit(runs),
        arm_histories_isolated=_history_isolation_audit(runs),
        common_randomness_consistent=_common_randomness_audit(runs, outcome_bundles),
        calibration_scientific_evidence_separated=_calibration_boundary_audit(
            runs,
            prefixes,
        ),
        calibration_decision_costs_reconcile=_cost_audit(runs, prefixes),
        fixed_policy_regression_unchanged=all(
            decision.fixed_policy_regression_match
            for run in runs
            if run.belief_model_id == FIXED_SIGMA_MODEL_ID
            for decision in run.arm_run.decisions
        ),
        planner_integrity=_planner_integrity_audit(runs),
        evidence_integrity=_evidence_integrity_audit(runs),
        simulated_planner_state_not_persisted=_simulated_state_audit(runs),
        provenance_complete=_provenance_audit(runs),
        statistics_complete=_statistics_audit(runs, paired_rows),
        artifact_contract_complete=_artifact_contract_audit(
            runs=runs,
            prefixes=prefixes,
            outcome_bundles=outcome_bundles,
            divergences=divergences,
            aggregate_rows=aggregate_rows,
            paired_rows=paired_rows,
            calibration_rows=calibration_rows,
        ),
        previous_evaluation_artifacts_unchanged=(
            historical_before == historical_after
            and all(digest != "MISSING" for _, digest in historical_before)
        ),
    )


def _matrix_audit(runs: tuple[ClosedLoopEvaluationRun, ...], expected_run_count: int) -> bool:
    if len(runs) != expected_run_count or len({item.run_id for item in runs}) != len(runs):
        return False
    arm_ids = {item.arm_id for item in PRIMARY_ARMS}
    condition_groups: dict[tuple[str, int, str], set[str]] = {}
    for run in runs:
        condition_groups.setdefault((run.world_id, run.seed, run.budget_label), set()).add(
            run.arm.arm_id
        )
        if run.arm.policy_version != run.arm_run.spec.policy_version:
            return False
    return bool(condition_groups) and all(value == arm_ids for value in condition_groups.values())


def _truth_isolation_audit(runs: tuple[ClosedLoopEvaluationRun, ...]) -> bool:
    forbidden = {
        "hidden_true_hypothesis",
        "true_hypothesis_id",
        "true_optimizer_effect",
        "observation_noise_std",
        "world_config",
        "counterfactual_outcomes",
    }
    operational_fields = {
        item.name
        for model_type in (
            CandidateGroupPredictionAdapter,
            ClosedLoopArmSpec,
            ClosedLoopDecisionTrace,
            TruthFreeClosedLoopArmRun,
        )
        for item in fields(model_type)
    }
    runner_parameters = set(inspect.signature(run_closed_loop_arm).parameters)
    if operational_fields.intersection(forbidden) or runner_parameters.intersection(forbidden):
        return False
    for run in runs:
        serialized = json.dumps(run.arm_run.to_truth_free_dict(), sort_keys=True)
        if any(f'"{name}"' in serialized for name in forbidden):
            return False
    return True


def _counterfactual_isolation_audit() -> bool:
    public_methods = {
        name
        for name, value in inspect.getmembers(
            SelectedOnlyObservationOracle,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }
    policy_parameters = set(inspect.signature(run_closed_loop_arm).parameters)
    return public_methods == {
        "audit_accesses",
        "reveal_selected",
    } and not policy_parameters.intersection(
        {"outcomes", "potential_outcomes", "hidden_world", "world_config"}
    )


def _selected_only_audit(runs: tuple[ClosedLoopEvaluationRun, ...]) -> bool:
    return all(
        len(run.arm_run.oracle_accesses)
        == len(run.arm_run.experiments)
        == len(run.arm_run.decisions)
        and len({item.candidate_id for item in run.arm_run.oracle_accesses})
        == len(run.arm_run.oracle_accesses)
        and all(
            access.run_id == run.run_id
            and access.candidate_id == experiment.candidate.candidate_id
            and access.decision_trace_id == experiment.decision_trace_id
            and math.isclose(
                access.observed_value,
                experiment.observed_value,
                rel_tol=0.0,
                abs_tol=1e-15,
            )
            for access, experiment in zip(
                run.arm_run.oracle_accesses,
                run.arm_run.experiments,
                strict=True,
            )
        )
        for run in runs
    )


def _lineage_isolation_audit(runs: tuple[ClosedLoopEvaluationRun, ...]) -> bool:
    lineage_ids = tuple(run.arm_run.lineage.lineage_id for run in runs)
    if len(lineage_ids) != len(set(lineage_ids)):
        return False
    return all(
        run.arm_run.lineage.lineage_key == run.run_id
        and run.arm_run.lineage.belief_model_id == run.belief_model_id
        and run.arm_run.lineage.current_state.lineage_id == run.arm_run.lineage.lineage_id
        and all(
            decision.run_id == run.run_id
            and decision.arm_id == run.arm.arm_id
            and decision.lineage_id == run.arm_run.lineage.lineage_id
            and decision.belief_model_id == run.belief_model_id
            for decision in run.arm_run.decisions
        )
        and all(
            update.lineage_id == run.arm_run.lineage.lineage_id
            and update.belief_model_id == run.belief_model_id
            for update in run.arm_run.model_updates
        )
        for run in runs
    )


def _history_isolation_audit(runs: tuple[ClosedLoopEvaluationRun, ...]) -> bool:
    experiment_ids = [
        experiment.experiment_id for run in runs for experiment in run.arm_run.experiments
    ]
    evidence_ids = [item.evidence_id for run in runs for item in run.arm_run.evidence]
    return (
        len(experiment_ids) == len(set(experiment_ids))
        and len(evidence_ids) == len(set(evidence_ids))
        and all(
            all(
                experiment.decision_trace_id in decision_ids
                for experiment in run.arm_run.experiments
            )
            for run in runs
            for decision_ids in ({item.decision_trace_id for item in run.arm_run.decisions},)
        )
    )


def _common_randomness_audit(
    runs: tuple[ClosedLoopEvaluationRun, ...],
    outcome_bundles: tuple[PotentialOutcomeBundle, ...],
) -> bool:
    expected = {
        (bundle.commitment.commitment_id, outcome.candidate_id): outcome.observed_value
        for bundle in outcome_bundles
        for outcome in bundle.outcomes
    }
    seen: dict[tuple[str, str], float] = {}
    for run in runs:
        for access in run.arm_run.oracle_accesses:
            key = (run.commitment_id, access.candidate_id)
            if key not in expected or not math.isclose(
                access.observed_value,
                expected[key],
                rel_tol=0.0,
                abs_tol=1e-15,
            ):
                return False
            if key in seen and not math.isclose(
                seen[key],
                access.observed_value,
                rel_tol=0.0,
                abs_tol=1e-15,
            ):
                return False
            seen[key] = access.observed_value
    return True


def _calibration_boundary_audit(
    runs: tuple[ClosedLoopEvaluationRun, ...],
    prefixes: tuple[CalibrationPrefix, ...],
) -> bool:
    prefix_by_id = {item.prefix_id: item for item in prefixes}
    if len(prefix_by_id) != len(prefixes):
        return False
    if any(
        len(prefix.effects_for_group(group.comparison_group_id)) != CALIBRATION_EFFECT_COUNT
        for prefix in prefixes
        for group in prefix.groups
    ):
        return False
    for run in runs:
        calibration_effects = tuple(
            item for item in run.arm_run.effect_history if item.source_kind == "calibration"
        )
        decision_effects = tuple(
            item for item in run.arm_run.effect_history if item.source_kind == "decision"
        )
        if len(decision_effects) != len(run.arm_run.model_updates):
            return False
        if any(
            not math.isclose(probability, 1.0 / 3.0, rel_tol=0.0, abs_tol=1e-15)
            for _, probability in run.arm_run.initial_posterior_probabilities
        ):
            return False
        if run.belief_model_id == FIXED_SIGMA_MODEL_ID:
            if (
                run.arm_run.spec.calibration_prefix_id is not None
                or run.metrics.calibration_cost != 0.0
                or calibration_effects
                or any(
                    snapshot.source_effect_ids
                    for decision in run.arm_run.decisions
                    for snapshot in decision.prediction_snapshots
                )
            ):
                return False
            continue
        prefix_id = run.arm_run.spec.calibration_prefix_id
        if prefix_id is None or prefix_id not in prefix_by_id:
            return False
        prefix = prefix_by_id[prefix_id]
        expected_ids = {item.calibration_effect_id for item in prefix.matched_effects}
        if {item.effect_id for item in calibration_effects} != expected_ids:
            return False
        if run.arm_run.evidence and expected_ids.intersection(
            item.evidence_id for item in run.arm_run.evidence
        ):
            return False
        history_by_id = {item.effect_id: item for item in run.arm_run.effect_history}
        for update in run.arm_run.model_updates:
            estimate = update.sigma_estimate
            if estimate.evidence_id in estimate.source_effect_ids:
                return False
            if any(
                source_id not in history_by_id
                or history_by_id[source_id].comparison_group_id != estimate.comparison_group_id
                or history_by_id[source_id].available_sequence >= estimate.cutoff_sequence
                for source_id in estimate.source_effect_ids
            ):
                return False
    return True


def _cost_audit(
    runs: tuple[ClosedLoopEvaluationRun, ...],
    prefixes: tuple[CalibrationPrefix, ...],
) -> bool:
    prefix_cost = {item.prefix_id: item.calibration_cost for item in prefixes}
    for run in runs:
        decision_cost = math.fsum(item.experiment_cost for item in run.arm_run.experiments)
        if (
            not math.isclose(
                decision_cost,
                run.metrics.decision_cost,
                rel_tol=0.0,
                abs_tol=1e-9,
            )
            or decision_cost > run.budget + COMPARISON_TOLERANCE
        ):
            return False
        if run.belief_model_id == FIXED_SIGMA_MODEL_ID:
            calibration_cost = 0.0
        else:
            prefix_id = run.arm_run.spec.calibration_prefix_id
            if prefix_id is None or prefix_id not in prefix_cost:
                return False
            calibration_cost = prefix_cost[prefix_id]
        if not math.isclose(
            calibration_cost,
            run.metrics.calibration_cost,
            rel_tol=0.0,
            abs_tol=1e-9,
        ) or not math.isclose(
            calibration_cost + decision_cost,
            run.metrics.required_total_cost,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            return False
    return True


def _planner_integrity_audit(runs: tuple[ClosedLoopEvaluationRun, ...]) -> bool:
    for run in runs:
        if len(run.arm_run.decisions) != len(run.arm_run.experiments):
            return False
        for decision, experiment in zip(
            run.arm_run.decisions,
            run.arm_run.experiments,
            strict=True,
        ):
            if (
                decision.selected_candidate_id != experiment.candidate.candidate_id
                or decision.selected_candidate_cost
                > decision.remaining_budget + COMPARISON_TOLERANCE
            ):
                return False
            trace = decision.policy_trace
            if isinstance(trace, LookaheadPlanTrace):
                if not math.isclose(
                    math.fsum(branch.probability for branch in trace.selected.branches),
                    1.0,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                ):
                    return False
                if any(
                    not branch.budget_feasible
                    or branch.branch_total_cost > decision.remaining_budget + COMPARISON_TOLERANCE
                    or not math.isclose(
                        math.fsum(value for _, value in branch.posterior_probabilities),
                        1.0,
                        rel_tol=0.0,
                        abs_tol=1e-12,
                    )
                    for branch in trace.selected.branches
                ):
                    return False
    return True


def _evidence_integrity_audit(runs: tuple[ClosedLoopEvaluationRun, ...]) -> bool:
    for run in runs:
        experiments = {item.experiment_id: item for item in run.arm_run.experiments}
        consumed_pairs: set[tuple[int, ...]] = set()
        if len(run.arm_run.evidence) != len(run.arm_run.model_updates):
            return False
        for evidence, update in zip(
            run.arm_run.evidence,
            run.arm_run.model_updates,
            strict=True,
        ):
            pair = evidence.source_experiment_ids
            if pair in consumed_pairs or any(item not in experiments for item in pair):
                return False
            consumed_pairs.add(pair)
            source = tuple(experiments[item] for item in pair)
            adam = tuple(item for item in source if item.candidate.optimizer == "adam")
            sgd = tuple(item for item in source if item.candidate.optimizer == "sgd")
            if len(adam) != 1 or len(sgd) != 1:
                return False
            expected_effect = round(adam[0].observed_value - sgd[0].observed_value, 12)
            if not math.isclose(
                expected_effect,
                evidence.observed_comparison,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                return False
            if update.evidence.evidence_id != evidence.evidence_id:
                return False
            posterior = update.posterior_state.state.posterior_probabilities
            if not math.isclose(
                math.fsum(posterior),
                1.0,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                return False
        if tuple(item.evidence_id for item in run.arm_run.evidence) != (
            run.arm_run.lineage.current_state.state.evidence_ids
        ):
            return False
    return True


def _simulated_state_audit(runs: tuple[ClosedLoopEvaluationRun, ...]) -> bool:
    return all(
        all(
            item.experiment_id > 0 and "SIMULATED" not in item.created_at
            for item in run.arm_run.experiments
        )
        and all(
            source_id > 0
            for evidence in run.arm_run.evidence
            for source_id in evidence.source_experiment_ids
        )
        and "SIMULATED-NOT-PERSISTED"
        not in json.dumps(run.arm_run.to_truth_free_dict(), sort_keys=True)
        for run in runs
    )


def _provenance_audit(runs: tuple[ClosedLoopEvaluationRun, ...]) -> bool:
    for run in runs:
        for decision in run.arm_run.decisions:
            if (
                not decision.decision_trace_id
                or not decision.policy_trace.provenance.method
                or any(
                    snapshot.lineage_id != run.arm_run.lineage.lineage_id
                    or snapshot.belief_model_id != run.belief_model_id
                    or not snapshot.snapshot_id
                    for snapshot in decision.prediction_snapshots
                )
            ):
                return False
        for update in run.arm_run.model_updates:
            if (
                not update.provenance.method
                or not update.evidence.provenance.method
                or not update.sigma_estimate.provenance.method
                or not update.diagnostic.provenance.method
                or not update.sigma_estimate.current_evidence_excluded
                or update.sigma_estimate.sample_count
                != len(update.sigma_estimate.source_effect_ids)
            ):
                return False
    return True


def _statistics_audit(
    runs: tuple[ClosedLoopEvaluationRun, ...],
    paired_rows: tuple[dict[str, object], ...],
) -> bool:
    required = {
        (scope, world_id, budget_label, policy, metric)
        for scope, world_id, budget_label, policy in (
            ("world", "adverse_noisy_observations", "all", "all"),
            ("world", "delayed_information", "all", "all"),
            ("global", "all", "all", "all"),
        )
        for metric in (
            "confidently_wrong",
            "negative_log_true_hypothesis_probability",
            "final_brier_score",
            "calibration_error",
        )
    }
    available = {
        (
            cast(str, item["scope"]),
            cast(str, item["world_id"]),
            cast(str, item["budget_label"]),
            cast(str, item["policy"]),
            cast(str, item["metric"]),
        )
        for item in paired_rows
    }
    return (
        bool(runs)
        and required.issubset(available)
        and all(
            item["confidence_interval_low"] is not None
            and item["confidence_interval_high"] is not None
            and cast(int, item["paired_sample_count"]) > 0
            for item in paired_rows
        )
    )


def _artifact_contract_audit(
    *,
    runs: tuple[ClosedLoopEvaluationRun, ...],
    prefixes: tuple[CalibrationPrefix, ...],
    outcome_bundles: tuple[PotentialOutcomeBundle, ...],
    divergences: tuple[DecisionDivergence, ...],
    aggregate_rows: tuple[dict[str, object], ...],
    paired_rows: tuple[dict[str, object], ...],
    calibration_rows: tuple[dict[str, object], ...],
) -> bool:
    if len(divergences) != len(runs) // 2:
        return False
    if not aggregate_rows or not paired_rows or not calibration_rows:
        return False
    if len({item.prefix_id for item in prefixes}) != len(prefixes):
        return False
    if any(
        bundle.commitment.candidate_ids != tuple(item.candidate_id for item in bundle.outcomes)
        for bundle in outcome_bundles
    ):
        return False
    try:
        json.dumps(
            {
                "runs": [item.to_dict() for item in runs],
                "divergences": [item.to_dict() for item in divergences],
            },
            sort_keys=True,
        )
    except (TypeError, ValueError):
        return False
    return True
