"""Rigorous paired evaluation for the fixed four-policy research benchmark."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import statistics
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from random import Random
from typing import Literal

from research_decision_engine.benchmarks.evaluation import (
    ALL_BENCHMARK_POLICIES,
    POLICY_VERSIONS,
    BenchmarkRunResult,
    PolicyBenchmarkContext,
    posterior_entropy,
    run_benchmark_condition,
)
from research_decision_engine.benchmarks.worlds import (
    BENCHMARK_VERSION,
    BenchmarkDesign,
    BenchmarkWorldConfig,
    build_benchmark_world,
    paired_evaluation_worlds,
)
from research_decision_engine.decision import InformationGainPolicy
from research_decision_engine.lookahead import LookaheadInformationGainPolicy
from research_decision_engine.optimizer_effect import optimizer_effect_hypotheses
from research_decision_engine.policies import (
    GreedyPredictedPerformancePolicy,
    RandomPolicy,
)
from research_decision_engine.storage import SCHEMA_VERSION

PAIRED_EVALUATION_VERSION = "paired-lookahead-evaluation/v1"
PAIRED_POLICIES = ALL_BENCHMARK_POLICIES
DEFAULT_PAIRED_SEEDS = tuple(range(100))
DEFAULT_SHORT_BUDGET = 2.25
DEFAULT_LARGE_BUDGET = 4.5
DEFAULT_BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20_260_710
CALIBRATION_BIN_COUNT = 10
CONFIDENCE_LEVEL = 0.95
NORMAL_CONFIDENCE_Z = 1.96
COMPARISON_TOLERANCE = 1e-12
NLL_PROBABILITY_FLOOR = 1e-300

type BetterDirection = Literal["higher", "lower"]
type MetricCategory = Literal["scientific", "resource", "objective"]


class EvaluationInvariantError(RuntimeError):
    """Raised when pairing, leakage, or persistence invariants fail."""


@dataclass(frozen=True, slots=True)
class PosteriorClassification:
    predicted_hypothesis_id: str
    maximum_posterior_probability: float
    correct: bool
    confidently_wrong: bool


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    name: str
    category: MetricCategory
    better_direction: BetterDirection
    description: str


METRIC_DEFINITIONS: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        "final_true_hypothesis_probability",
        "scientific",
        "higher",
        "Final posterior probability assigned to hidden evaluator truth.",
    ),
    MetricDefinition(
        "final_posterior_entropy",
        "scientific",
        "lower",
        "Final Shannon entropy in bits over the three hypotheses.",
    ),
    MetricDefinition(
        "final_brier_score",
        "scientific",
        "lower",
        "Multiclass Brier score against the hidden true hypothesis.",
    ),
    MetricDefinition(
        "negative_log_true_hypothesis_probability",
        "scientific",
        "lower",
        "Natural-log loss of the true hypothesis, with probability floored at 1e-300.",
    ),
    MetricDefinition(
        "confidently_wrong",
        "scientific",
        "lower",
        "Indicator that confidence is at least 0.80 in a non-true hypothesis.",
    ),
    MetricDefinition(
        "final_true_hypothesis_rank",
        "scientific",
        "lower",
        "Final rank of the true hypothesis; one is best.",
    ),
    MetricDefinition(
        "reached_80_confidence",
        "scientific",
        "higher",
        "Indicator that true-hypothesis posterior reached 0.80 during the run.",
    ),
    MetricDefinition(
        "reached_95_confidence",
        "scientific",
        "higher",
        "Indicator that true-hypothesis posterior reached 0.95 during the run.",
    ),
    MetricDefinition(
        "experiments_to_80_confidence",
        "scientific",
        "lower",
        "Experiments to first 0.80 crossing; absent when never reached.",
    ),
    MetricDefinition(
        "experiments_to_95_confidence",
        "scientific",
        "lower",
        "Experiments to first 0.95 crossing; absent when never reached.",
    ),
    MetricDefinition(
        "cost_to_80_confidence",
        "resource",
        "lower",
        "Cumulative cost to first 0.80 crossing; absent when never reached.",
    ),
    MetricDefinition(
        "cost_to_95_confidence",
        "resource",
        "lower",
        "Cumulative cost to first 0.95 crossing; absent when never reached.",
    ),
    MetricDefinition(
        "matched_evidence_pairs_completed",
        "scientific",
        "higher",
        "Number of real matched optimizer evidence pairs completed.",
    ),
    MetricDefinition(
        "redundant_experiments_selected",
        "resource",
        "lower",
        "Number of evaluator-labeled redundant experiments selected.",
    ),
    MetricDefinition(
        "total_experimental_cost",
        "resource",
        "lower",
        "Total real experimental cost consumed.",
    ),
    MetricDefinition(
        "final_entropy_reduction",
        "scientific",
        "higher",
        "Initial posterior entropy minus final posterior entropy in bits.",
    ),
    MetricDefinition(
        "best_observed_objective",
        "objective",
        "higher",
        "Best observed synthetic objective, reported only as a secondary metric.",
    ),
)


@dataclass(frozen=True, slots=True)
class CodeVersion:
    git_commit: str | None
    source_tree_sha256: str

    def label(self) -> str:
        return self.git_commit or f"source-sha256:{self.source_tree_sha256}"

    def to_dict(self) -> dict[str, object]:
        return {
            "git_commit": self.git_commit,
            "source_tree_sha256": self.source_tree_sha256,
            "label": self.label(),
        }


@dataclass(frozen=True, slots=True)
class EvaluationCondition:
    world_config: BenchmarkWorldConfig
    budget_label: str
    budget: float
    design: BenchmarkDesign

    @property
    def condition_id(self) -> str:
        return f"{self.world_config.world_id}:{self.budget_label}"

    def to_dict(self) -> dict[str, object]:
        return {
            "condition_id": self.condition_id,
            "budget_label": self.budget_label,
            "budget": self.budget,
            "world_configuration": self.world_config.to_dict(),
            "candidate_design": self.design.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class EvaluationRunMetrics:
    final_true_hypothesis_probability: float
    final_posterior_entropy: float
    final_brier_score: float
    negative_log_true_hypothesis_probability: float
    final_true_hypothesis_rank: int
    reached_80_confidence: bool
    reached_95_confidence: bool
    experiments_to_80_confidence: int | None
    experiments_to_95_confidence: int | None
    cost_to_80_confidence: float | None
    cost_to_95_confidence: float | None
    matched_evidence_pairs_completed: int
    redundant_experiments_selected: int
    total_experimental_cost: float
    final_entropy_reduction: float
    best_observed_objective: float | None
    predicted_hypothesis_id: str
    maximum_posterior_probability: float
    prediction_correct: bool
    confidently_wrong: bool
    entropy_accuracy_counterexample: bool

    def metric_values(self) -> dict[str, float | None]:
        return {
            "final_true_hypothesis_probability": self.final_true_hypothesis_probability,
            "final_posterior_entropy": self.final_posterior_entropy,
            "final_brier_score": self.final_brier_score,
            "negative_log_true_hypothesis_probability": (
                self.negative_log_true_hypothesis_probability
            ),
            "confidently_wrong": float(self.confidently_wrong),
            "final_true_hypothesis_rank": float(self.final_true_hypothesis_rank),
            "reached_80_confidence": float(self.reached_80_confidence),
            "reached_95_confidence": float(self.reached_95_confidence),
            "experiments_to_80_confidence": _optional_float(self.experiments_to_80_confidence),
            "experiments_to_95_confidence": _optional_float(self.experiments_to_95_confidence),
            "cost_to_80_confidence": self.cost_to_80_confidence,
            "cost_to_95_confidence": self.cost_to_95_confidence,
            "matched_evidence_pairs_completed": float(self.matched_evidence_pairs_completed),
            "redundant_experiments_selected": float(self.redundant_experiments_selected),
            "total_experimental_cost": self.total_experimental_cost,
            "final_entropy_reduction": self.final_entropy_reduction,
            "best_observed_objective": self.best_observed_objective,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.metric_values(),
            "predicted_hypothesis_id": self.predicted_hypothesis_id,
            "maximum_posterior_probability": self.maximum_posterior_probability,
            "prediction_correct": self.prediction_correct,
            "confidently_wrong": self.confidently_wrong,
            "entropy_accuracy_counterexample": self.entropy_accuracy_counterexample,
        }


@dataclass(frozen=True, slots=True)
class PairedEvaluationRun:
    run_id: str
    evaluation_version: str
    budget_label: str
    code_version: CodeVersion
    public_initial_condition_fingerprint: str
    observation_schedule_fingerprint: str
    benchmark_run: BenchmarkRunResult
    metrics: EvaluationRunMetrics

    @property
    def world_id(self) -> str:
        return self.benchmark_run.world_config.world_id

    @property
    def policy(self) -> str:
        return self.benchmark_run.policy

    @property
    def seed(self) -> int:
        return self.benchmark_run.seed

    @property
    def budget(self) -> float:
        return self.benchmark_run.budget

    def final_posterior_probabilities(self) -> dict[str, float]:
        if self.benchmark_run.trace:
            return dict(self.benchmark_run.trace[-1].posterior_probabilities)
        return dict(self.benchmark_run.initial_belief_probabilities)

    def to_dict(self) -> dict[str, object]:
        benchmark = self.benchmark_run
        return {
            "run_id": self.run_id,
            "evaluation_version": self.evaluation_version,
            "benchmark_version": benchmark.benchmark_version,
            "timestamp": benchmark.generated_at,
            "code_version": self.code_version.to_dict(),
            "schema_version": benchmark.schema_version,
            "dependency_versions": dict(benchmark.dependency_versions),
            "policy": benchmark.policy,
            "policy_version": benchmark.policy_version,
            "world_id": self.world_id,
            "world_configuration": benchmark.world_config.to_dict(),
            "hidden_true_hypothesis": benchmark.world_config.true_hypothesis_id,
            "seed": benchmark.seed,
            "budget_label": self.budget_label,
            "budget": benchmark.budget,
            "public_initial_condition_fingerprint": (self.public_initial_condition_fingerprint),
            "observation_schedule_fingerprint": self.observation_schedule_fingerprint,
            "initial_belief_probabilities": dict(benchmark.initial_belief_probabilities),
            "stop_reason": benchmark.stop_reason,
            "budget_exhausted": benchmark.budget_exhausted,
            "metrics": self.metrics.to_dict(),
            "final_posterior_probabilities": self.final_posterior_probabilities(),
            "full_metric_trace": [item.to_dict() for item in benchmark.trace],
        }


@dataclass(frozen=True, slots=True)
class AggregateMetricResult:
    world_id: str
    budget_label: str
    budget: float
    policy: str
    metric: str
    metric_category: MetricCategory
    sample_count: int
    mean: float | None
    median: float | None
    standard_deviation: float | None
    confidence_interval_low: float | None
    confidence_interval_high: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "world_id": self.world_id,
            "budget_label": self.budget_label,
            "budget": self.budget,
            "policy": self.policy,
            "metric": self.metric,
            "metric_category": self.metric_category,
            "sample_count": self.sample_count,
            "mean": self.mean,
            "median": self.median,
            "standard_deviation": self.standard_deviation,
            "confidence_level": CONFIDENCE_LEVEL,
            "confidence_interval_low": self.confidence_interval_low,
            "confidence_interval_high": self.confidence_interval_high,
            "confidence_interval_method": "normal approximation for aggregate mean",
        }


@dataclass(frozen=True, slots=True)
class PairedComparisonResult:
    world_id: str
    budget_label: str
    budget: float
    baseline_policy: str
    metric: str
    metric_category: MetricCategory
    better_direction: BetterDirection
    valid_paired_runs: int
    mean_paired_difference: float | None
    median_paired_difference: float | None
    standard_deviation: float | None
    confidence_interval_low: float | None
    confidence_interval_high: float | None
    wins: int
    ties: int
    losses: int

    def to_dict(self) -> dict[str, object]:
        return {
            "world_id": self.world_id,
            "budget_label": self.budget_label,
            "budget": self.budget,
            "lookahead_policy": "lookahead_information_gain",
            "baseline_policy": self.baseline_policy,
            "difference_definition": "lookahead minus baseline",
            "metric": self.metric,
            "metric_category": self.metric_category,
            "better_direction": self.better_direction,
            "valid_paired_runs": self.valid_paired_runs,
            "mean_paired_difference": self.mean_paired_difference,
            "median_paired_difference": self.median_paired_difference,
            "standard_deviation": self.standard_deviation,
            "confidence_level": CONFIDENCE_LEVEL,
            "confidence_interval_low": self.confidence_interval_low,
            "confidence_interval_high": self.confidence_interval_high,
            "confidence_interval_method": "paired percentile bootstrap of the mean",
            "wins": self.wins,
            "ties": self.ties,
            "losses": self.losses,
        }


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    world_id: str
    budget_label: str
    budget: float
    policy: str
    run_count: int
    accuracy: float
    confidently_wrong_count: int
    confidently_wrong_rate: float
    average_confidence_when_correct: float | None
    average_confidence_when_incorrect: float | None
    expected_calibration_error: float
    mean_brier_score: float
    mean_entropy_when_correct: float | None
    mean_entropy_when_incorrect: float | None
    mean_entropy_reduction_when_correct: float | None
    mean_entropy_reduction_when_incorrect: float | None
    entropy_reduction_correctness_correlation: float | None
    entropy_accuracy_counterexample_count: int
    entropy_accuracy_counterexample_rate: float

    def to_dict(self) -> dict[str, object]:
        return {
            "world_id": self.world_id,
            "budget_label": self.budget_label,
            "budget": self.budget,
            "policy": self.policy,
            "run_count": self.run_count,
            "accuracy": self.accuracy,
            "confidently_wrong_count": self.confidently_wrong_count,
            "confidently_wrong_rate": self.confidently_wrong_rate,
            "average_confidence_when_correct": self.average_confidence_when_correct,
            "average_confidence_when_incorrect": self.average_confidence_when_incorrect,
            "calibration_error": self.expected_calibration_error,
            "calibration_error_method": (
                f"top-label ECE with {CALIBRATION_BIN_COUNT} equal-width bins"
            ),
            "mean_brier_score": self.mean_brier_score,
            "mean_entropy_when_correct": self.mean_entropy_when_correct,
            "mean_entropy_when_incorrect": self.mean_entropy_when_incorrect,
            "mean_entropy_reduction_when_correct": (self.mean_entropy_reduction_when_correct),
            "mean_entropy_reduction_when_incorrect": (self.mean_entropy_reduction_when_incorrect),
            "entropy_reduction_correctness_correlation": (
                self.entropy_reduction_correctness_correlation
            ),
            "entropy_accuracy_counterexample_count": (self.entropy_accuracy_counterexample_count),
            "entropy_accuracy_counterexample_rate": self.entropy_accuracy_counterexample_rate,
        }


@dataclass(frozen=True, slots=True)
class FailureCase:
    run_id: str
    world_id: str
    budget_label: str
    budget: float
    policy: str
    seed: int
    failure_types: tuple[str, ...]
    true_hypothesis_id: str
    predicted_hypothesis_id: str
    maximum_posterior_probability: float
    true_hypothesis_probability: float
    final_posterior_entropy: float
    final_entropy_reduction: float
    final_brier_score: float
    negative_log_true_hypothesis_probability: float
    posterior_probabilities: tuple[tuple[str, float], ...]
    selected_candidate_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "world_id": self.world_id,
            "budget_label": self.budget_label,
            "budget": self.budget,
            "policy": self.policy,
            "seed": self.seed,
            "failure_types": list(self.failure_types),
            "true_hypothesis_id": self.true_hypothesis_id,
            "predicted_hypothesis_id": self.predicted_hypothesis_id,
            "maximum_posterior_probability": self.maximum_posterior_probability,
            "true_hypothesis_probability": self.true_hypothesis_probability,
            "final_posterior_entropy": self.final_posterior_entropy,
            "final_entropy_reduction": self.final_entropy_reduction,
            "final_brier_score": self.final_brier_score,
            "negative_log_true_hypothesis_probability": (
                self.negative_log_true_hypothesis_probability
            ),
            "posterior_probabilities": dict(self.posterior_probabilities),
            "selected_candidate_ids": list(self.selected_candidate_ids),
        }


@dataclass(frozen=True, slots=True)
class FairnessAudit:
    equivalent_public_initial_conditions: bool
    hidden_truth_absent_from_policy_interfaces: bool
    benchmark_truth_confined_to_evaluation: bool
    deterministic_replays_match: bool
    observation_schedules_are_paired: bool
    simulated_state_not_persisted: bool
    no_world_specific_policy_tuning: bool
    details: tuple[str, ...]

    def __post_init__(self) -> None:
        checks = (
            self.equivalent_public_initial_conditions,
            self.hidden_truth_absent_from_policy_interfaces,
            self.benchmark_truth_confined_to_evaluation,
            self.deterministic_replays_match,
            self.observation_schedules_are_paired,
            self.simulated_state_not_persisted,
            self.no_world_specific_policy_tuning,
        )
        if not all(checks):
            raise EvaluationInvariantError("One or more fairness and leakage audits failed.")

    def to_dict(self) -> dict[str, object]:
        return {
            "equivalent_public_initial_conditions": (self.equivalent_public_initial_conditions),
            "hidden_truth_absent_from_policy_interfaces": (
                self.hidden_truth_absent_from_policy_interfaces
            ),
            "benchmark_truth_confined_to_evaluation": (self.benchmark_truth_confined_to_evaluation),
            "deterministic_replays_match": self.deterministic_replays_match,
            "observation_schedules_are_paired": self.observation_schedules_are_paired,
            "simulated_state_not_persisted": self.simulated_state_not_persisted,
            "no_world_specific_policy_tuning": self.no_world_specific_policy_tuning,
            "passed": True,
            "details": list(self.details),
        }


@dataclass(frozen=True, slots=True)
class PairedEvaluationReport:
    evaluation_version: str
    generated_at: str
    code_version: CodeVersion
    seeds: tuple[int, ...]
    bootstrap_resamples: int
    conditions: tuple[EvaluationCondition, ...]
    runs: tuple[PairedEvaluationRun, ...]
    aggregates: tuple[AggregateMetricResult, ...]
    paired_comparisons: tuple[PairedComparisonResult, ...]
    calibration: tuple[CalibrationResult, ...]
    failure_cases: tuple[FailureCase, ...]
    fairness_audit: FairnessAudit

    def manifest_dict(self) -> dict[str, object]:
        dependencies = dict(self.runs[0].benchmark_run.dependency_versions)
        return {
            "evaluation_version": self.evaluation_version,
            "benchmark_version": BENCHMARK_VERSION,
            "generated_at": self.generated_at,
            "code_version": self.code_version.to_dict(),
            "schema_version": SCHEMA_VERSION,
            "dependency_versions": dependencies,
            "policies": [
                {"policy": policy, "policy_version": POLICY_VERSIONS[policy]}
                for policy in PAIRED_POLICIES
            ],
            "seeds": list(self.seeds),
            "paired_seed_count": len(self.seeds),
            "conditions": [item.to_dict() for item in self.conditions],
            "run_count": len(self.runs),
            "bootstrap": {
                "method": "paired percentile bootstrap of seed-level mean differences",
                "confidence_level": CONFIDENCE_LEVEL,
                "resamples": self.bootstrap_resamples,
                "fixed_seed": BOOTSTRAP_SEED,
                "pairing_unit": "world, budget, seed",
            },
            "metric_definitions": [
                {
                    "name": item.name,
                    "category": item.category,
                    "better_direction": item.better_direction,
                    "description": item.description,
                }
                for item in METRIC_DEFINITIONS
            ],
            "confidently_wrong_definition": (
                "maximum posterior >= 0.80 and stable top hypothesis is not evaluator truth"
            ),
            "calibration_definition": (
                f"top-label expected calibration error with {CALIBRATION_BIN_COUNT} "
                "equal-width confidence bins"
            ),
            "threshold_definition": "first observed true-posterior crossing",
            "fairness_and_leakage_audit": self.fairness_audit.to_dict(),
        }


def run_paired_evaluation(
    *,
    seeds: tuple[int, ...] = DEFAULT_PAIRED_SEEDS,
    short_budget: float = DEFAULT_SHORT_BUDGET,
    large_budget: float = DEFAULT_LARGE_BUDGET,
    bootstrap_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    generated_at: str | None = None,
    verify_deterministic_replays: bool = True,
) -> PairedEvaluationReport:
    """Run all four unchanged policies under paired worlds, budgets, and seeds."""

    _validate_evaluation_inputs(
        seeds=seeds,
        short_budget=short_budget,
        large_budget=large_budget,
        bootstrap_resamples=bootstrap_resamples,
    )
    _audit_policy_isolation()
    timestamp = datetime.now(UTC).isoformat() if generated_at is None else generated_at
    code_version = _code_version()
    conditions = _evaluation_conditions(short_budget, large_budget)
    runs: list[PairedEvaluationRun] = []
    replay_checks = 0

    for condition in conditions:
        for seed in seeds:
            public_fingerprint = _public_initial_condition_fingerprint(condition, seed)
            schedule = _observation_schedule(condition.world_config, seed)
            repeated_schedule = _observation_schedule(condition.world_config, seed)
            if schedule != repeated_schedule:
                raise EvaluationInvariantError(
                    f"Observation schedule is not deterministic for {condition.condition_id}."
                )
            schedule_fingerprint = _stable_hash(schedule)
            condition_runs: list[PairedEvaluationRun] = []
            for policy in PAIRED_POLICIES:
                benchmark_run = run_benchmark_condition(
                    world_config=condition.world_config,
                    policy=policy,
                    seed=seed,
                    budget=condition.budget,
                    generated_at=timestamp,
                )
                wrapped = _wrap_run(
                    benchmark_run=benchmark_run,
                    budget_label=condition.budget_label,
                    code_version=code_version,
                    public_fingerprint=public_fingerprint,
                    schedule_fingerprint=schedule_fingerprint,
                )
                condition_runs.append(wrapped)
                runs.append(wrapped)

                if verify_deterministic_replays and seed == seeds[0]:
                    replay = run_benchmark_condition(
                        world_config=condition.world_config,
                        policy=policy,
                        seed=seed,
                        budget=condition.budget,
                        generated_at=timestamp,
                    )
                    if replay != benchmark_run:
                        raise EvaluationInvariantError(
                            f"Deterministic replay failed for {condition.condition_id}, {policy}."
                        )
                    replay_checks += 1

            if {item.public_initial_condition_fingerprint for item in condition_runs} != {
                public_fingerprint
            }:
                raise EvaluationInvariantError("Policies received unequal public conditions.")
            if {item.observation_schedule_fingerprint for item in condition_runs} != {
                schedule_fingerprint
            }:
                raise EvaluationInvariantError("Policies received unpaired observation schedules.")
            if (
                len({item.benchmark_run.initial_belief_probabilities for item in condition_runs})
                != 1
            ):
                raise EvaluationInvariantError("Policies received unequal initial beliefs.")

    wrapped_runs = tuple(runs)
    _audit_complete_pairing(wrapped_runs, conditions, seeds)
    fairness = FairnessAudit(
        equivalent_public_initial_conditions=True,
        hidden_truth_absent_from_policy_interfaces=True,
        benchmark_truth_confined_to_evaluation=True,
        deterministic_replays_match=True,
        observation_schedules_are_paired=True,
        simulated_state_not_persisted=True,
        no_world_specific_policy_tuning=True,
        details=(
            f"Compared exactly {', '.join(PAIRED_POLICIES)}.",
            f"Verified {replay_checks} representative deterministic policy replays.",
            (
                "Policy contexts contain no world ID, hidden hypothesis, hidden effect, or "
                "world object."
            ),
            "Policy source modules import no benchmark module and contain no stress-world IDs.",
            "Each benchmark run audits real experiment/evidence/update row counts before closing.",
        ),
    )
    aggregates = aggregate_evaluation_runs(wrapped_runs)
    paired = paired_policy_comparisons(
        wrapped_runs,
        bootstrap_resamples=bootstrap_resamples,
    )
    calibration = calibration_analysis(wrapped_runs)
    failures = failure_cases(wrapped_runs)
    return PairedEvaluationReport(
        evaluation_version=PAIRED_EVALUATION_VERSION,
        generated_at=timestamp,
        code_version=code_version,
        seeds=seeds,
        bootstrap_resamples=bootstrap_resamples,
        conditions=conditions,
        runs=wrapped_runs,
        aggregates=aggregates,
        paired_comparisons=paired,
        calibration=calibration,
        failure_cases=failures,
        fairness_audit=fairness,
    )


def aggregate_evaluation_runs(
    runs: tuple[PairedEvaluationRun, ...],
) -> tuple[AggregateMetricResult, ...]:
    """Aggregate every metric separately by policy, world, and budget."""

    results: list[AggregateMetricResult] = []
    group_keys = sorted({(item.world_id, item.budget_label, item.budget) for item in runs})
    for world_id, budget_label, budget in group_keys:
        for policy in PAIRED_POLICIES:
            group = tuple(
                item
                for item in runs
                if item.world_id == world_id
                and item.budget_label == budget_label
                and item.policy == policy
            )
            if not group:
                raise EvaluationInvariantError("Cannot aggregate an empty policy condition.")
            for definition in METRIC_DEFINITIONS:
                values = tuple(
                    value
                    for item in group
                    if (value := item.metrics.metric_values()[definition.name]) is not None
                )
                summary = _normal_summary(values)
                results.append(
                    AggregateMetricResult(
                        world_id=world_id,
                        budget_label=budget_label,
                        budget=budget,
                        policy=policy,
                        metric=definition.name,
                        metric_category=definition.category,
                        sample_count=len(values),
                        mean=summary[0],
                        median=summary[1],
                        standard_deviation=summary[2],
                        confidence_interval_low=summary[3],
                        confidence_interval_high=summary[4],
                    )
                )
    return tuple(results)


def paired_policy_comparisons(
    runs: tuple[PairedEvaluationRun, ...],
    *,
    bootstrap_resamples: int,
) -> tuple[PairedComparisonResult, ...]:
    """Compare lookahead with each baseline using seed-paired differences."""

    results: list[PairedComparisonResult] = []
    group_keys = sorted({(item.world_id, item.budget_label, item.budget) for item in runs})
    baselines = tuple(
        policy for policy in PAIRED_POLICIES if policy != "lookahead_information_gain"
    )
    for world_id, budget_label, budget in group_keys:
        condition_runs = tuple(
            item for item in runs if item.world_id == world_id and item.budget_label == budget_label
        )
        by_policy_seed = {(item.policy, item.seed): item for item in condition_runs}
        seeds = sorted({item.seed for item in condition_runs})
        for baseline in baselines:
            for definition in METRIC_DEFINITIONS:
                differences: list[float] = []
                for seed in seeds:
                    lookahead_value = by_policy_seed[
                        ("lookahead_information_gain", seed)
                    ].metrics.metric_values()[definition.name]
                    baseline_value = by_policy_seed[(baseline, seed)].metrics.metric_values()[
                        definition.name
                    ]
                    if lookahead_value is not None and baseline_value is not None:
                        differences.append(lookahead_value - baseline_value)

                values = tuple(differences)
                summary = _paired_summary(
                    values,
                    bootstrap_resamples=bootstrap_resamples,
                    bootstrap_key=(world_id, budget_label, baseline, definition.name),
                )
                wins, ties, losses = _win_tie_loss(values, definition.better_direction)
                results.append(
                    PairedComparisonResult(
                        world_id=world_id,
                        budget_label=budget_label,
                        budget=budget,
                        baseline_policy=baseline,
                        metric=definition.name,
                        metric_category=definition.category,
                        better_direction=definition.better_direction,
                        valid_paired_runs=len(values),
                        mean_paired_difference=summary[0],
                        median_paired_difference=summary[1],
                        standard_deviation=summary[2],
                        confidence_interval_low=summary[3],
                        confidence_interval_high=summary[4],
                        wins=wins,
                        ties=ties,
                        losses=losses,
                    )
                )
    return tuple(results)


def calibration_analysis(
    runs: tuple[PairedEvaluationRun, ...],
) -> tuple[CalibrationResult, ...]:
    """Calculate top-label calibration and entropy/correctness diagnostics."""

    results: list[CalibrationResult] = []
    group_keys = sorted({(item.world_id, item.budget_label, item.budget) for item in runs})
    for world_id, budget_label, budget in group_keys:
        for policy in PAIRED_POLICIES:
            group = tuple(
                item
                for item in runs
                if item.world_id == world_id
                and item.budget_label == budget_label
                and item.policy == policy
            )
            if not group:
                raise EvaluationInvariantError("Cannot calibrate an empty policy condition.")
            correct = tuple(item for item in group if item.metrics.prediction_correct)
            incorrect = tuple(item for item in group if not item.metrics.prediction_correct)
            correctness = tuple(float(item.metrics.prediction_correct) for item in group)
            entropy_reductions = tuple(item.metrics.final_entropy_reduction for item in group)
            confidently_wrong_count = sum(item.metrics.confidently_wrong for item in group)
            counterexample_count = sum(
                item.metrics.entropy_accuracy_counterexample for item in group
            )
            results.append(
                CalibrationResult(
                    world_id=world_id,
                    budget_label=budget_label,
                    budget=budget,
                    policy=policy,
                    run_count=len(group),
                    accuracy=statistics.fmean(correctness),
                    confidently_wrong_count=confidently_wrong_count,
                    confidently_wrong_rate=confidently_wrong_count / len(group),
                    average_confidence_when_correct=_mean_or_none(
                        tuple(item.metrics.maximum_posterior_probability for item in correct)
                    ),
                    average_confidence_when_incorrect=_mean_or_none(
                        tuple(item.metrics.maximum_posterior_probability for item in incorrect)
                    ),
                    expected_calibration_error=expected_calibration_error(group),
                    mean_brier_score=statistics.fmean(
                        item.metrics.final_brier_score for item in group
                    ),
                    mean_entropy_when_correct=_mean_or_none(
                        tuple(item.metrics.final_posterior_entropy for item in correct)
                    ),
                    mean_entropy_when_incorrect=_mean_or_none(
                        tuple(item.metrics.final_posterior_entropy for item in incorrect)
                    ),
                    mean_entropy_reduction_when_correct=_mean_or_none(
                        tuple(item.metrics.final_entropy_reduction for item in correct)
                    ),
                    mean_entropy_reduction_when_incorrect=_mean_or_none(
                        tuple(item.metrics.final_entropy_reduction for item in incorrect)
                    ),
                    entropy_reduction_correctness_correlation=_correlation_or_none(
                        entropy_reductions,
                        correctness,
                    ),
                    entropy_accuracy_counterexample_count=counterexample_count,
                    entropy_accuracy_counterexample_rate=counterexample_count / len(group),
                )
            )
    return tuple(results)


def expected_calibration_error(runs: tuple[PairedEvaluationRun, ...]) -> float:
    """Return deterministic top-label ECE over equal-width confidence bins."""

    observations = tuple(
        (run.metrics.maximum_posterior_probability, run.metrics.prediction_correct) for run in runs
    )
    return top_label_expected_calibration_error(observations)


def top_label_expected_calibration_error(
    observations: tuple[tuple[float, bool], ...],
) -> float:
    """Calculate deterministic equal-width top-label calibration error."""

    if not observations:
        raise ValueError("Calibration requires at least one observation.")
    bins: list[list[tuple[float, bool]]] = [[] for _ in range(CALIBRATION_BIN_COUNT)]
    for confidence, correct in observations:
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ValueError("Calibration confidence must be finite and in [0, 1].")
        index = min(
            int(confidence * CALIBRATION_BIN_COUNT),
            CALIBRATION_BIN_COUNT - 1,
        )
        bins[index].append((confidence, correct))
    total = len(observations)
    return math.fsum(
        (len(items) / total)
        * abs(
            statistics.fmean(item[0] for item in items)
            - statistics.fmean(float(item[1]) for item in items)
        )
        for items in bins
        if items
    )


def classify_posterior(
    posterior_probabilities: dict[str, float],
    true_hypothesis_id: str,
) -> PosteriorClassification:
    """Classify a posterior with stable lexical tie-breaking."""

    if true_hypothesis_id not in posterior_probabilities:
        raise ValueError("True hypothesis is absent from posterior probabilities.")
    if not posterior_probabilities:
        raise ValueError("Posterior probabilities must not be empty.")
    values = tuple(posterior_probabilities.values())
    if any(not math.isfinite(value) or value < 0.0 for value in values):
        raise ValueError("Posterior probabilities must be finite and non-negative.")
    if not math.isclose(math.fsum(values), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("Posterior probabilities must sum to one.")
    maximum = max(values)
    predicted_id = min(
        hypothesis_id
        for hypothesis_id, probability in posterior_probabilities.items()
        if math.isclose(probability, maximum, rel_tol=0.0, abs_tol=1e-15)
    )
    correct = predicted_id == true_hypothesis_id
    return PosteriorClassification(
        predicted_hypothesis_id=predicted_id,
        maximum_posterior_probability=maximum,
        correct=correct,
        confidently_wrong=maximum >= 0.80 and not correct,
    )


def failure_cases(runs: tuple[PairedEvaluationRun, ...]) -> tuple[FailureCase, ...]:
    """Extract confidently wrong and entropy/accuracy counterexample runs."""

    failures: list[FailureCase] = []
    for run in runs:
        failure_types: list[str] = []
        if run.metrics.confidently_wrong:
            failure_types.append("confidently_wrong")
        if run.metrics.entropy_accuracy_counterexample:
            failure_types.append("entropy_decreased_while_true_probability_worsened")
        if not failure_types:
            continue
        failures.append(
            FailureCase(
                run_id=run.run_id,
                world_id=run.world_id,
                budget_label=run.budget_label,
                budget=run.budget,
                policy=run.policy,
                seed=run.seed,
                failure_types=tuple(failure_types),
                true_hypothesis_id=run.benchmark_run.world_config.true_hypothesis_id,
                predicted_hypothesis_id=run.metrics.predicted_hypothesis_id,
                maximum_posterior_probability=run.metrics.maximum_posterior_probability,
                true_hypothesis_probability=(run.metrics.final_true_hypothesis_probability),
                final_posterior_entropy=run.metrics.final_posterior_entropy,
                final_entropy_reduction=run.metrics.final_entropy_reduction,
                final_brier_score=run.metrics.final_brier_score,
                negative_log_true_hypothesis_probability=(
                    run.metrics.negative_log_true_hypothesis_probability
                ),
                posterior_probabilities=tuple(sorted(run.final_posterior_probabilities().items())),
                selected_candidate_ids=tuple(item.candidate_id for item in run.benchmark_run.trace),
            )
        )
    return tuple(
        sorted(
            failures,
            key=lambda item: (
                item.world_id,
                item.budget,
                item.policy,
                item.seed,
            ),
        )
    )


def deterministic_bootstrap_mean_interval(
    values: tuple[float, ...],
    *,
    resamples: int,
    key: tuple[str, ...],
) -> tuple[float, float]:
    """Return a deterministic 95% paired percentile-bootstrap interval."""

    if not values:
        raise ValueError("Bootstrap requires at least one paired difference.")
    if resamples <= 0:
        raise ValueError("Bootstrap resamples must be positive.")
    if len(values) == 1:
        return values[0], values[0]
    seed_material = f"{BOOTSTRAP_SEED}|{'|'.join(key)}".encode()
    seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
    random = Random(seed)
    sample_size = len(values)
    means = [
        math.fsum(values[random.randrange(sample_size)] for _ in range(sample_size)) / sample_size
        for _ in range(resamples)
    ]
    means.sort()
    return _percentile(means, 0.025), _percentile(means, 0.975)


def _wrap_run(
    *,
    benchmark_run: BenchmarkRunResult,
    budget_label: str,
    code_version: CodeVersion,
    public_fingerprint: str,
    schedule_fingerprint: str,
) -> PairedEvaluationRun:
    posterior = (
        dict(benchmark_run.trace[-1].posterior_probabilities)
        if benchmark_run.trace
        else dict(benchmark_run.initial_belief_probabilities)
    )
    true_id = benchmark_run.world_config.true_hypothesis_id
    classification = classify_posterior(posterior, true_id)
    true_probability = posterior[true_id]
    initial_probabilities = dict(benchmark_run.initial_belief_probabilities)
    initial_entropy = posterior_entropy(tuple(initial_probabilities.values()))
    scientific = benchmark_run.scientific_metrics
    objective = benchmark_run.objective_metrics
    metrics = EvaluationRunMetrics(
        final_true_hypothesis_probability=true_probability,
        final_posterior_entropy=scientific.final_posterior_entropy,
        final_brier_score=scientific.final_brier_calibration,
        negative_log_true_hypothesis_probability=-math.log(
            max(true_probability, NLL_PROBABILITY_FLOOR)
        ),
        final_true_hypothesis_rank=scientific.final_true_hypothesis_rank,
        reached_80_confidence=scientific.experiments_to_80_confidence is not None,
        reached_95_confidence=scientific.experiments_to_95_confidence is not None,
        experiments_to_80_confidence=scientific.experiments_to_80_confidence,
        experiments_to_95_confidence=scientific.experiments_to_95_confidence,
        cost_to_80_confidence=scientific.cost_to_80_confidence,
        cost_to_95_confidence=scientific.cost_to_95_confidence,
        matched_evidence_pairs_completed=scientific.matched_evidence_pairs_completed,
        redundant_experiments_selected=scientific.redundant_experiments_selected,
        total_experimental_cost=objective.total_experimental_cost,
        final_entropy_reduction=initial_entropy - scientific.final_posterior_entropy,
        best_observed_objective=objective.best_observed_objective,
        predicted_hypothesis_id=classification.predicted_hypothesis_id,
        maximum_posterior_probability=classification.maximum_posterior_probability,
        prediction_correct=classification.correct,
        confidently_wrong=classification.confidently_wrong,
        entropy_accuracy_counterexample=(
            scientific.final_posterior_entropy < initial_entropy - COMPARISON_TOLERANCE
            and true_probability < initial_probabilities[true_id] - COMPARISON_TOLERANCE
        ),
    )
    run_id = _stable_hash(
        {
            "evaluation_version": PAIRED_EVALUATION_VERSION,
            "world_id": benchmark_run.world_config.world_id,
            "budget_label": budget_label,
            "budget": benchmark_run.budget,
            "policy": benchmark_run.policy,
            "seed": benchmark_run.seed,
        }
    )
    return PairedEvaluationRun(
        run_id=f"evaluation-run-{run_id[:24]}",
        evaluation_version=PAIRED_EVALUATION_VERSION,
        budget_label=budget_label,
        code_version=code_version,
        public_initial_condition_fingerprint=public_fingerprint,
        observation_schedule_fingerprint=schedule_fingerprint,
        benchmark_run=benchmark_run,
        metrics=metrics,
    )


def _evaluation_conditions(
    short_budget: float,
    large_budget: float,
) -> tuple[EvaluationCondition, ...]:
    conditions: list[EvaluationCondition] = []
    for config in paired_evaluation_worlds():
        design, _ = build_benchmark_world(config, seed=0)
        for label, budget in (("short", short_budget), ("large", large_budget)):
            conditions.append(
                EvaluationCondition(
                    world_config=config,
                    budget_label=label,
                    budget=budget,
                    design=design,
                )
            )
    return tuple(conditions)


def _public_initial_condition_fingerprint(
    condition: EvaluationCondition,
    seed: int,
) -> str:
    hypotheses = optimizer_effect_hypotheses()
    public_design = {
        "candidates": [
            {
                "candidate_id": candidate.candidate_id,
                "params": candidate.params(),
                "cost": condition.design.cost(candidate),
            }
            for candidate in condition.design.candidates
        ],
        "evidence_eligibility": condition.design.evidence_eligibility().to_dict(),
        "initial_beliefs": {item.hypothesis_id: item.prior_probability for item in hypotheses},
        "budget": condition.budget,
        "seed": seed,
    }
    return _stable_hash(public_design)


def _observation_schedule(
    config: BenchmarkWorldConfig,
    seed: int,
) -> tuple[tuple[str, float], ...]:
    design, hidden_world = build_benchmark_world(config, seed=seed)
    return tuple(
        (candidate.candidate_id, hidden_world.observe(candidate)) for candidate in design.candidates
    )


def _audit_complete_pairing(
    runs: tuple[PairedEvaluationRun, ...],
    conditions: tuple[EvaluationCondition, ...],
    seeds: tuple[int, ...],
) -> None:
    expected = {
        (condition.world_config.world_id, condition.budget_label, seed, policy)
        for condition in conditions
        for seed in seeds
        for policy in PAIRED_POLICIES
    }
    actual = {(item.world_id, item.budget_label, item.seed, item.policy) for item in runs}
    if actual != expected or len(runs) != len(expected):
        raise EvaluationInvariantError("Evaluation matrix is incomplete or duplicated.")
    for condition in conditions:
        for seed in seeds:
            group = tuple(
                item
                for item in runs
                if item.world_id == condition.world_config.world_id
                and item.budget_label == condition.budget_label
                and item.seed == seed
            )
            if {item.policy for item in group} != set(PAIRED_POLICIES):
                raise EvaluationInvariantError("A paired condition is missing a policy.")
            if len({item.public_initial_condition_fingerprint for item in group}) != 1:
                raise EvaluationInvariantError("Public initial conditions differ within a pair.")
            if len({item.observation_schedule_fingerprint for item in group}) != 1:
                raise EvaluationInvariantError("Observation schedules differ within a pair.")


def _audit_policy_isolation() -> None:
    forbidden_fields = {
        "true_hypothesis_id",
        "true_optimizer_effect",
        "world_config",
        "hidden_world",
    }
    context_fields = {item.name for item in fields(PolicyBenchmarkContext)}
    if context_fields.intersection(forbidden_fields):
        raise EvaluationInvariantError("Policy context exposes hidden benchmark truth.")

    policy_classes = (
        RandomPolicy,
        GreedyPredictedPerformancePolicy,
        InformationGainPolicy,
        LookaheadInformationGainPolicy,
    )
    world_ids = tuple(item.world_id for item in paired_evaluation_worlds())
    checked_modules: set[str] = set()
    for policy_class in policy_classes:
        signature = inspect.signature(
            policy_class.decide if hasattr(policy_class, "decide") else policy_class.select
        )
        if set(signature.parameters).intersection(forbidden_fields):
            raise EvaluationInvariantError(
                f"{policy_class.__name__} accepts hidden benchmark truth."
            )
        module = inspect.getmodule(policy_class)
        if module is None or module.__name__ in checked_modules:
            continue
        checked_modules.add(module.__name__)
        source = inspect.getsource(module)
        if "research_decision_engine.benchmarks" in source:
            raise EvaluationInvariantError(
                f"Policy module {module.__name__} imports benchmark evaluation code."
            )
        if any(forbidden in source for forbidden in forbidden_fields):
            raise EvaluationInvariantError(
                f"Policy module {module.__name__} references a hidden-truth name."
            )
        if any(world_id in source for world_id in world_ids):
            raise EvaluationInvariantError(
                f"Policy module {module.__name__} contains world-specific tuning."
            )


def _validate_evaluation_inputs(
    *,
    seeds: tuple[int, ...],
    short_budget: float,
    large_budget: float,
    bootstrap_resamples: int,
) -> None:
    if not seeds or len(seeds) != len(set(seeds)):
        raise ValueError("Paired evaluation seeds must be non-empty and unique.")
    if PAIRED_POLICIES != (
        "random",
        "greedy",
        "information_gain",
        "lookahead_information_gain",
    ):
        raise EvaluationInvariantError("Paired evaluation policy set changed unexpectedly.")
    if not math.isfinite(short_budget) or short_budget <= 0.0:
        raise ValueError("Short budget must be finite and positive.")
    if not math.isfinite(large_budget) or large_budget <= short_budget:
        raise ValueError("Large budget must be finite and greater than the short budget.")
    if bootstrap_resamples <= 0:
        raise ValueError("Bootstrap resamples must be positive.")


def _normal_summary(
    values: tuple[float, ...],
) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    if not values:
        return None, None, None, None, None
    mean = statistics.fmean(values)
    median = statistics.median(values)
    standard_deviation = statistics.stdev(values) if len(values) > 1 else 0.0
    margin = NORMAL_CONFIDENCE_Z * standard_deviation / math.sqrt(len(values))
    return (
        mean,
        median,
        standard_deviation,
        mean - margin,
        mean + margin,
    )


def _paired_summary(
    values: tuple[float, ...],
    *,
    bootstrap_resamples: int,
    bootstrap_key: tuple[str, ...],
) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    if not values:
        return None, None, None, None, None
    low, high = deterministic_bootstrap_mean_interval(
        values,
        resamples=bootstrap_resamples,
        key=bootstrap_key,
    )
    return (
        statistics.fmean(values),
        statistics.median(values),
        statistics.stdev(values) if len(values) > 1 else 0.0,
        low,
        high,
    )


def _win_tie_loss(
    differences: tuple[float, ...],
    better_direction: BetterDirection,
) -> tuple[int, int, int]:
    wins = 0
    ties = 0
    losses = 0
    for difference in differences:
        if math.isclose(difference, 0.0, rel_tol=0.0, abs_tol=COMPARISON_TOLERANCE):
            ties += 1
        elif (better_direction == "higher" and difference > 0.0) or (
            better_direction == "lower" and difference < 0.0
        ):
            wins += 1
        else:
            losses += 1
    return wins, ties, losses


def _percentile(sorted_values: list[float], quantile: float) -> float:
    position = (len(sorted_values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] + fraction * (sorted_values[upper] - sorted_values[lower])


def _mean_or_none(values: tuple[float, ...]) -> float | None:
    return None if not values else statistics.fmean(values)


def _correlation_or_none(
    left: tuple[float, ...],
    right: tuple[float, ...],
) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    if math.isclose(max(left), min(left), rel_tol=0.0, abs_tol=COMPARISON_TOLERANCE):
        return None
    if math.isclose(max(right), min(right), rel_tol=0.0, abs_tol=COMPARISON_TOLERANCE):
        return None
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    numerator = math.fsum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right, strict=True)
    )
    left_scale = math.sqrt(math.fsum((value - left_mean) ** 2 for value in left))
    right_scale = math.sqrt(math.fsum((value - right_mean) ** 2 for value in right))
    return numerator / (left_scale * right_scale)


def _optional_float(value: int | None) -> float | None:
    return None if value is None else float(value)


def _stable_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _code_version() -> CodeVersion:
    package_root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(package_root.rglob("*.py")):
        digest.update(path.relative_to(package_root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    repository_root = package_root.parent
    return CodeVersion(
        git_commit=_read_git_commit(repository_root),
        source_tree_sha256=digest.hexdigest(),
    )


def _read_git_commit(repository_root: Path) -> str | None:
    git_directory = repository_root / ".git"
    head_path = git_directory / "HEAD"
    if not head_path.is_file():
        return None
    head = head_path.read_text(encoding="utf-8").strip()
    if not head.startswith("ref: "):
        return head or None
    reference = head.removeprefix("ref: ")
    reference_path = git_directory / reference
    if reference_path.is_file():
        return reference_path.read_text(encoding="utf-8").strip() or None
    packed_refs = git_directory / "packed-refs"
    if packed_refs.is_file():
        for line in packed_refs.read_text(encoding="utf-8").splitlines():
            if line.endswith(f" {reference}"):
                return line.split(" ", maxsplit=1)[0]
    return None
