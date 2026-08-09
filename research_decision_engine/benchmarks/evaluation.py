"""Fair benchmark execution, metrics, and statistical aggregation."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from research_decision_engine import __version__
from research_decision_engine.benchmarks.worlds import (
    BENCHMARK_VERSION,
    BenchmarkDesign,
    BenchmarkWorldConfig,
    CandidateCost,
    all_benchmark_world_ids,
    benchmark_worlds,
    build_benchmark_world,
)
from research_decision_engine.decision import (
    INFORMATION_GAIN_POLICY,
    INFORMATION_GAIN_POLICY_VERSION,
    InformationGainPolicy,
)
from research_decision_engine.evidence_eligibility import (
    OptimizerEvidenceEligibilityContract,
)
from research_decision_engine.lookahead import (
    LOOKAHEAD_INFORMATION_GAIN_POLICY,
    LOOKAHEAD_INFORMATION_GAIN_POLICY_VERSION,
    LookaheadInformationGainPolicy,
)
from research_decision_engine.optimizer_effect import (
    ensure_optimizer_reasoning,
    synchronize_optimizer_reasoning,
)
from research_decision_engine.policies import DecisionPolicy, build_policy
from research_decision_engine.reasoning import BeliefState, Hypothesis
from research_decision_engine.storage import SCHEMA_VERSION, ExperimentStore
from research_decision_engine.types import Candidate, CompletedExperiment, ExperimentRecord

BENCHMARK_POLICIES: tuple[str, ...] = ("random", "greedy", INFORMATION_GAIN_POLICY)
ALL_BENCHMARK_POLICIES: tuple[str, ...] = (
    *BENCHMARK_POLICIES,
    LOOKAHEAD_INFORMATION_GAIN_POLICY,
)
DEFAULT_BENCHMARK_SEEDS: tuple[int, ...] = (0, 1, 2)
DEFAULT_BENCHMARK_BUDGET = 8.0
CONFIDENCE_LEVEL = 0.95
CONFIDENCE_Z_SCORE = 1.96
BUDGET_TOLERANCE = 1e-12

POLICY_VERSIONS: dict[str, str] = {
    "random": "random-policy/v1",
    "greedy": "greedy-predicted-performance/v1",
    INFORMATION_GAIN_POLICY: INFORMATION_GAIN_POLICY_VERSION,
    LOOKAHEAD_INFORMATION_GAIN_POLICY: LOOKAHEAD_INFORMATION_GAIN_POLICY_VERSION,
}


@dataclass(frozen=True, slots=True)
class PolicyBenchmarkContext:
    """Complete policy input, intentionally excluding hidden benchmark truth."""

    feasible_candidates: tuple[Candidate, ...]
    history: tuple[ExperimentRecord, ...]
    completed_experiments: tuple[CompletedExperiment, ...]
    hypotheses: tuple[Hypothesis, ...]
    belief_state: BeliefState
    evidence_eligibility: OptimizerEvidenceEligibilityContract
    candidate_costs: tuple[CandidateCost, ...]
    remaining_budget: float
    seed: int

    def cost(self, candidate: Candidate) -> float:
        for item in self.candidate_costs:
            if item.candidate_id == candidate.candidate_id:
                return item.cost
        raise KeyError(f"Unknown policy candidate cost: {candidate.candidate_id}")


@dataclass(frozen=True, slots=True)
class ExperimentMetricTrace:
    """Scientific and objective metrics after one completed experiment."""

    step: int
    candidate_id: str
    observed_objective: float
    experiment_cost: float
    cumulative_cost: float
    posterior_entropy: float
    posterior_entropy_per_unit_cost: float
    entropy_reduction_per_unit_cost: float
    true_hypothesis_probability: float
    true_hypothesis_rank: int
    posterior_probabilities: tuple[tuple[str, float], ...]
    redundant_experiment: bool
    cumulative_redundant_experiments: int
    new_matched_evidence: bool
    matched_evidence_pairs_completed: int
    best_observed_objective: float

    def to_dict(self) -> dict[str, object]:
        return {
            "step": self.step,
            "candidate_id": self.candidate_id,
            "observed_objective": self.observed_objective,
            "experiment_cost": self.experiment_cost,
            "cumulative_cost": self.cumulative_cost,
            "scientific_progress": {
                "posterior_entropy": self.posterior_entropy,
                "posterior_entropy_per_unit_cost": self.posterior_entropy_per_unit_cost,
                "entropy_reduction_per_unit_cost": self.entropy_reduction_per_unit_cost,
                "true_hypothesis_probability": self.true_hypothesis_probability,
                "true_hypothesis_rank": self.true_hypothesis_rank,
                "posterior_probabilities": dict(self.posterior_probabilities),
                "redundant_experiment": self.redundant_experiment,
                "cumulative_redundant_experiments": self.cumulative_redundant_experiments,
                "new_matched_evidence": self.new_matched_evidence,
                "matched_evidence_pairs_completed": self.matched_evidence_pairs_completed,
            },
            "objective_optimization": {
                "best_observed_objective": self.best_observed_objective,
            },
        }


@dataclass(frozen=True, slots=True)
class ScientificProgressMetrics:
    final_posterior_entropy: float
    final_posterior_entropy_per_unit_cost: float | None
    final_entropy_reduction_per_unit_cost: float | None
    final_true_hypothesis_probability: float
    final_true_hypothesis_rank: int
    experiments_to_80_confidence: int | None
    experiments_to_95_confidence: int | None
    cost_to_80_confidence: float | None
    cost_to_95_confidence: float | None
    redundant_experiments_selected: int
    matched_evidence_pairs_completed: int
    final_brier_calibration: float

    def to_dict(self) -> dict[str, object]:
        return {
            "final_posterior_entropy": self.final_posterior_entropy,
            "final_posterior_entropy_per_unit_cost": self.final_posterior_entropy_per_unit_cost,
            "final_entropy_reduction_per_unit_cost": (self.final_entropy_reduction_per_unit_cost),
            "final_true_hypothesis_probability": self.final_true_hypothesis_probability,
            "final_true_hypothesis_rank": self.final_true_hypothesis_rank,
            "experiments_to_80_confidence": self.experiments_to_80_confidence,
            "experiments_to_95_confidence": self.experiments_to_95_confidence,
            "cost_to_80_confidence": self.cost_to_80_confidence,
            "cost_to_95_confidence": self.cost_to_95_confidence,
            "redundant_experiments_selected": self.redundant_experiments_selected,
            "matched_evidence_pairs_completed": self.matched_evidence_pairs_completed,
            "final_brier_calibration": self.final_brier_calibration,
        }


@dataclass(frozen=True, slots=True)
class ObjectiveOptimizationMetrics:
    best_observed_objective: float | None
    total_experimental_cost: float
    experiments_completed: int

    def to_dict(self) -> dict[str, object]:
        return {
            "best_observed_objective": self.best_observed_objective,
            "total_experimental_cost": self.total_experimental_cost,
            "experiments_completed": self.experiments_completed,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkRunResult:
    benchmark_version: str
    generated_at: str
    world_config: BenchmarkWorldConfig
    policy: str
    policy_version: str
    seed: int
    budget: float
    initial_condition_fingerprint: str
    initial_belief_probabilities: tuple[tuple[str, float], ...]
    dependency_versions: tuple[tuple[str, str], ...]
    schema_version: int
    stop_reason: str
    budget_exhausted: bool
    scientific_metrics: ScientificProgressMetrics
    objective_metrics: ObjectiveOptimizationMetrics
    trace: tuple[ExperimentMetricTrace, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "benchmark_version": self.benchmark_version,
            "generated_at": self.generated_at,
            "world_configuration": self.world_config.to_dict(),
            "hidden_true_hypothesis": self.world_config.true_hypothesis_id,
            "policy": self.policy,
            "policy_version": self.policy_version,
            "seed": self.seed,
            "budget": self.budget,
            "initial_condition_fingerprint": self.initial_condition_fingerprint,
            "initial_belief_probabilities": dict(self.initial_belief_probabilities),
            "dependency_versions": dict(self.dependency_versions),
            "schema_version": self.schema_version,
            "stop_reason": self.stop_reason,
            "budget_exhausted": self.budget_exhausted,
            "scientific_progress_metrics": self.scientific_metrics.to_dict(),
            "objective_optimization_metrics": self.objective_metrics.to_dict(),
            "trace": [item.to_dict() for item in self.trace],
        }


@dataclass(frozen=True, slots=True)
class StatisticalSummary:
    count: int
    mean: float | None
    median: float | None
    standard_deviation: float | None
    confidence_interval_low: float | None
    confidence_interval_high: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "count": self.count,
            "mean": self.mean,
            "median": self.median,
            "standard_deviation": self.standard_deviation,
            "confidence_level": CONFIDENCE_LEVEL,
            "confidence_interval_low": self.confidence_interval_low,
            "confidence_interval_high": self.confidence_interval_high,
            "confidence_interval_method": "normal approximation for the mean",
        }


@dataclass(frozen=True, slots=True)
class AggregateResult:
    scope: str
    world_id: str | None
    policy: str
    run_count: int
    successful_80_confidence_runs: int
    successful_95_confidence_runs: int
    budget_exhausted_runs: int
    metrics: tuple[tuple[str, StatisticalSummary], ...]

    def metric(self, name: str) -> StatisticalSummary:
        for metric_name, summary in self.metrics:
            if metric_name == name:
                return summary
        raise KeyError(name)

    def to_dict(self) -> dict[str, object]:
        return {
            "scope": self.scope,
            "world_id": self.world_id,
            "policy": self.policy,
            "run_count": self.run_count,
            "successful_80_confidence_runs": self.successful_80_confidence_runs,
            "successful_95_confidence_runs": self.successful_95_confidence_runs,
            "budget_exhausted_runs": self.budget_exhausted_runs,
            "metrics": {name: summary.to_dict() for name, summary in self.metrics},
        }


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    benchmark_version: str
    generated_at: str
    seeds: tuple[int, ...]
    budget: float
    world_ids: tuple[str, ...]
    policies: tuple[str, ...]
    dependency_versions: tuple[tuple[str, str], ...]
    schema_version: int
    runs: tuple[BenchmarkRunResult, ...]
    aggregates_by_policy_world: tuple[AggregateResult, ...]
    aggregates_by_policy: tuple[AggregateResult, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "benchmark_version": self.benchmark_version,
            "generated_at": self.generated_at,
            "seeds": list(self.seeds),
            "budget": self.budget,
            "world_ids": list(self.world_ids),
            "policies": list(self.policies),
            "dependency_versions": dict(self.dependency_versions),
            "schema_version": self.schema_version,
            "statistical_notes": {
                "standard_deviation": "sample standard deviation",
                "confidence_interval": "95% normal-approximation interval for the mean",
                "significance_testing_performed": False,
            },
            "runs": [run.to_dict() for run in self.runs],
            "aggregates_by_policy_world": [
                aggregate.to_dict() for aggregate in self.aggregates_by_policy_world
            ],
            "aggregates_by_policy": [
                aggregate.to_dict() for aggregate in self.aggregates_by_policy
            ],
        }


def run_benchmark_suite(
    *,
    world_ids: tuple[str, ...] | None = None,
    policies: tuple[str, ...] = BENCHMARK_POLICIES,
    seeds: tuple[int, ...] = DEFAULT_BENCHMARK_SEEDS,
    budget: float = DEFAULT_BENCHMARK_BUDGET,
    generated_at: str | None = None,
) -> BenchmarkReport:
    """Run selected policies on identical seeded benchmark conditions."""

    _validate_benchmark_inputs(policies=policies, seeds=seeds, budget=budget)
    timestamp = datetime.now(UTC).isoformat() if generated_at is None else generated_at
    configs = benchmark_worlds(world_ids)
    runs = tuple(
        run_benchmark_condition(
            world_config=config,
            policy=policy,
            seed=seed,
            budget=budget,
            generated_at=timestamp,
        )
        for config in configs
        for seed in seeds
        for policy in policies
    )
    by_policy_world = tuple(
        _aggregate_runs(
            tuple(
                run
                for run in runs
                if run.world_config.world_id == config.world_id and run.policy == policy
            ),
            scope="policy_world",
            world_id=config.world_id,
            policy=policy,
        )
        for config in configs
        for policy in policies
    )
    by_policy = tuple(
        _aggregate_runs(
            tuple(run for run in runs if run.policy == policy),
            scope="policy",
            world_id=None,
            policy=policy,
        )
        for policy in policies
    )
    dependencies = _dependency_versions()
    return BenchmarkReport(
        benchmark_version=BENCHMARK_VERSION,
        generated_at=timestamp,
        seeds=seeds,
        budget=budget,
        world_ids=tuple(config.world_id for config in configs),
        policies=policies,
        dependency_versions=dependencies,
        schema_version=SCHEMA_VERSION,
        runs=runs,
        aggregates_by_policy_world=by_policy_world,
        aggregates_by_policy=by_policy,
    )


def run_benchmark_condition(
    *,
    world_config: BenchmarkWorldConfig,
    policy: str,
    seed: int,
    budget: float,
    generated_at: str,
) -> BenchmarkRunResult:
    """Run one policy without exposing evaluator truth to its decision inputs."""

    _validate_benchmark_inputs(policies=(policy,), seeds=(seed,), budget=budget)
    design, hidden_world = build_benchmark_world(world_config, seed=seed)
    trace: list[ExperimentMetricTrace] = []
    cumulative_cost = 0.0
    redundant_count = 0
    best_observed: float | None = None
    stop_reason = "candidate_space_exhausted"
    budget_exhausted = False
    baseline_policy: DecisionPolicy | None = (
        build_policy(policy, seed) if policy in {"random", "greedy"} else None
    )
    information_policy = InformationGainPolicy()
    lookahead_policy = LookaheadInformationGainPolicy()
    evidence_eligibility = design.evidence_eligibility()

    with ExperimentStore(Path(":memory:")) as store:
        store.init_schema()
        initial_belief = ensure_optimizer_reasoning(store)
        initial_entropy = posterior_entropy(initial_belief.posterior_probabilities)
        initial_probabilities = tuple(sorted(initial_belief.posterior_map().items()))
        fingerprint = _initial_condition_fingerprint(
            world_config=world_config,
            design=design,
            seed=seed,
            budget=budget,
            initial_probabilities=initial_probabilities,
        )

        while True:
            history = store.list_records()
            completed_ids = {item.candidate.candidate_id for item in history}
            uncompleted = tuple(
                candidate
                for candidate in design.candidates
                if candidate.candidate_id not in completed_ids
            )
            remaining_budget = budget - cumulative_cost
            feasible = tuple(
                candidate
                for candidate in uncompleted
                if design.cost(candidate) <= remaining_budget + BUDGET_TOLERANCE
            )
            if not feasible:
                budget_exhausted = bool(uncompleted)
                stop_reason = (
                    "budget_exhausted" if budget_exhausted else "candidate_space_exhausted"
                )
                break

            belief_state = store.current_belief_state()
            if belief_state is None:
                raise RuntimeError("Benchmark belief state is not initialized.")
            context = PolicyBenchmarkContext(
                feasible_candidates=feasible,
                history=tuple(history),
                completed_experiments=tuple(store.list_completed_experiments()),
                hypotheses=tuple(store.list_hypotheses()),
                belief_state=belief_state,
                evidence_eligibility=evidence_eligibility,
                candidate_costs=design.candidate_costs,
                remaining_budget=remaining_budget,
                seed=seed,
            )
            try:
                candidate = _select_candidate(
                    policy=policy,
                    context=context,
                    baseline_policy=baseline_policy,
                    information_policy=information_policy,
                    lookahead_policy=lookahead_policy,
                    created_at=f"{generated_at}#decision-{len(trace) + 1:04d}",
                )
            except ValueError:
                stop_reason = "policy_has_no_feasible_candidate"
                break
            if candidate.candidate_id not in {item.candidate_id for item in feasible}:
                raise RuntimeError(f"Policy {policy} selected an infeasible candidate.")

            completed_candidates = tuple(item.candidate for item in history)
            redundant = design.is_evaluator_redundant(candidate, completed_candidates)
            redundant_count += int(redundant)
            observed_value = hidden_world.observe(candidate)
            experiment_cost = design.cost(candidate)
            cumulative_cost = round(cumulative_cost + experiment_cost, 12)
            best_observed = (
                observed_value if best_observed is None else max(best_observed, observed_value)
            )
            evidence_before = belief_state.sequence
            store.add_record(
                ExperimentRecord(
                    record_id=None,
                    candidate=candidate,
                    policy=policy,
                    observed_value=observed_value,
                    true_value=observed_value,
                    cost=experiment_cost,
                    created_at=f"{generated_at}#experiment-{len(trace) + 1:04d}",
                )
            )
            synchronize_optimizer_reasoning(store, eligibility=evidence_eligibility)
            updated_belief = store.current_belief_state()
            if updated_belief is None:
                raise RuntimeError("Benchmark belief update did not produce a state.")
            posterior_map = updated_belief.posterior_map()
            entropy = posterior_entropy(tuple(posterior_map.values()))
            true_probability = posterior_map[world_config.true_hypothesis_id]
            trace.append(
                ExperimentMetricTrace(
                    step=len(trace) + 1,
                    candidate_id=candidate.candidate_id,
                    observed_objective=observed_value,
                    experiment_cost=experiment_cost,
                    cumulative_cost=cumulative_cost,
                    posterior_entropy=entropy,
                    posterior_entropy_per_unit_cost=entropy / cumulative_cost,
                    entropy_reduction_per_unit_cost=((initial_entropy - entropy) / cumulative_cost),
                    true_hypothesis_probability=true_probability,
                    true_hypothesis_rank=true_hypothesis_rank(
                        posterior_map, world_config.true_hypothesis_id
                    ),
                    posterior_probabilities=tuple(sorted(posterior_map.items())),
                    redundant_experiment=redundant,
                    cumulative_redundant_experiments=redundant_count,
                    new_matched_evidence=updated_belief.sequence > evidence_before,
                    matched_evidence_pairs_completed=updated_belief.sequence,
                    best_observed_objective=best_observed,
                )
            )

        final_belief = store.current_belief_state()
        if final_belief is None:
            raise RuntimeError("Benchmark ended without a belief state.")
        scientific_metrics, objective_metrics = derive_run_metrics(
            trace=tuple(trace),
            final_belief=final_belief,
            true_hypothesis_id=world_config.true_hypothesis_id,
        )
        _assert_real_benchmark_persistence(store, trace)
        schema_version = store.schema_version()

    return BenchmarkRunResult(
        benchmark_version=BENCHMARK_VERSION,
        generated_at=generated_at,
        world_config=world_config,
        policy=policy,
        policy_version=POLICY_VERSIONS[policy],
        seed=seed,
        budget=budget,
        initial_condition_fingerprint=fingerprint,
        initial_belief_probabilities=initial_probabilities,
        dependency_versions=_dependency_versions(),
        schema_version=schema_version,
        stop_reason=stop_reason,
        budget_exhausted=budget_exhausted,
        scientific_metrics=scientific_metrics,
        objective_metrics=objective_metrics,
        trace=tuple(trace),
    )


def derive_run_metrics(
    *,
    trace: tuple[ExperimentMetricTrace, ...],
    final_belief: BeliefState,
    true_hypothesis_id: str,
) -> tuple[ScientificProgressMetrics, ObjectiveOptimizationMetrics]:
    """Derive final and threshold metrics from a complete per-experiment trace."""

    final_probabilities = final_belief.posterior_map()
    final_entropy = posterior_entropy(tuple(final_probabilities.values()))
    final_cost = trace[-1].cumulative_cost if trace else 0.0
    threshold_80 = next((item for item in trace if item.true_hypothesis_probability >= 0.80), None)
    threshold_95 = next((item for item in trace if item.true_hypothesis_probability >= 0.95), None)
    scientific = ScientificProgressMetrics(
        final_posterior_entropy=final_entropy,
        final_posterior_entropy_per_unit_cost=(
            None if final_cost == 0.0 else final_entropy / final_cost
        ),
        final_entropy_reduction_per_unit_cost=(
            None if not trace else trace[-1].entropy_reduction_per_unit_cost
        ),
        final_true_hypothesis_probability=final_probabilities[true_hypothesis_id],
        final_true_hypothesis_rank=true_hypothesis_rank(final_probabilities, true_hypothesis_id),
        experiments_to_80_confidence=None if threshold_80 is None else threshold_80.step,
        experiments_to_95_confidence=None if threshold_95 is None else threshold_95.step,
        cost_to_80_confidence=(None if threshold_80 is None else threshold_80.cumulative_cost),
        cost_to_95_confidence=(None if threshold_95 is None else threshold_95.cumulative_cost),
        redundant_experiments_selected=(
            0 if not trace else trace[-1].cumulative_redundant_experiments
        ),
        matched_evidence_pairs_completed=(
            0 if not trace else trace[-1].matched_evidence_pairs_completed
        ),
        final_brier_calibration=math.fsum(
            (probability - (1.0 if hypothesis_id == true_hypothesis_id else 0.0)) ** 2
            for hypothesis_id, probability in final_probabilities.items()
        ),
    )
    objective = ObjectiveOptimizationMetrics(
        best_observed_objective=(None if not trace else trace[-1].best_observed_objective),
        total_experimental_cost=final_cost,
        experiments_completed=len(trace),
    )
    return scientific, objective


def posterior_entropy(probabilities: tuple[float, ...]) -> float:
    return -math.fsum(value * math.log2(value) for value in probabilities if value > 0.0)


def true_hypothesis_rank(posterior_probabilities: dict[str, float], true_hypothesis_id: str) -> int:
    true_probability = posterior_probabilities[true_hypothesis_id]
    return 1 + sum(
        probability > true_probability + 1e-15
        for hypothesis_id, probability in posterior_probabilities.items()
        if hypothesis_id != true_hypothesis_id
    )


def _select_candidate(
    *,
    policy: str,
    context: PolicyBenchmarkContext,
    baseline_policy: DecisionPolicy | None,
    information_policy: InformationGainPolicy,
    lookahead_policy: LookaheadInformationGainPolicy,
    created_at: str,
) -> Candidate:
    if policy in {"random", "greedy"}:
        if baseline_policy is None:
            raise RuntimeError(f"Missing baseline policy instance for {policy}.")
        return baseline_policy.select(list(context.feasible_candidates), list(context.history))
    if policy == INFORMATION_GAIN_POLICY:
        return information_policy.decide(
            candidates=list(context.feasible_candidates),
            completed_experiments=list(context.completed_experiments),
            hypotheses=context.hypotheses,
            belief_state=context.belief_state,
            cost=context.cost,
            max_cost=context.remaining_budget,
            created_at=created_at,
            eligibility=context.evidence_eligibility,
        ).candidate
    if policy == LOOKAHEAD_INFORMATION_GAIN_POLICY:
        return lookahead_policy.decide(
            candidates=list(context.feasible_candidates),
            completed_experiments=list(context.completed_experiments),
            hypotheses=context.hypotheses,
            belief_state=context.belief_state,
            eligibility=context.evidence_eligibility,
            cost=context.cost,
            max_cost=context.remaining_budget,
            created_at=created_at,
        ).candidate
    raise ValueError(f"Unsupported benchmark policy: {policy}")


def _aggregate_runs(
    runs: tuple[BenchmarkRunResult, ...],
    *,
    scope: str,
    world_id: str | None,
    policy: str,
) -> AggregateResult:
    if not runs:
        raise ValueError("Cannot aggregate an empty benchmark run set.")
    metric_names = tuple(_numeric_run_metrics(runs[0]))
    metrics = tuple(
        (
            name,
            statistical_summary(
                tuple(
                    value for run in runs if (value := _numeric_run_metrics(run)[name]) is not None
                )
            ),
        )
        for name in metric_names
    )
    return AggregateResult(
        scope=scope,
        world_id=world_id,
        policy=policy,
        run_count=len(runs),
        successful_80_confidence_runs=sum(
            run.scientific_metrics.experiments_to_80_confidence is not None for run in runs
        ),
        successful_95_confidence_runs=sum(
            run.scientific_metrics.experiments_to_95_confidence is not None for run in runs
        ),
        budget_exhausted_runs=sum(run.budget_exhausted for run in runs),
        metrics=metrics,
    )


def statistical_summary(values: tuple[float, ...]) -> StatisticalSummary:
    if not values:
        return StatisticalSummary(
            count=0,
            mean=None,
            median=None,
            standard_deviation=None,
            confidence_interval_low=None,
            confidence_interval_high=None,
        )
    mean = statistics.fmean(values)
    median = statistics.median(values)
    standard_deviation = statistics.stdev(values) if len(values) > 1 else 0.0
    margin = CONFIDENCE_Z_SCORE * standard_deviation / math.sqrt(len(values))
    return StatisticalSummary(
        count=len(values),
        mean=mean,
        median=median,
        standard_deviation=standard_deviation,
        confidence_interval_low=mean - margin,
        confidence_interval_high=mean + margin,
    )


def _numeric_run_metrics(run: BenchmarkRunResult) -> dict[str, float | None]:
    scientific = run.scientific_metrics
    objective = run.objective_metrics
    return {
        "final_posterior_entropy": scientific.final_posterior_entropy,
        "final_posterior_entropy_per_unit_cost": (scientific.final_posterior_entropy_per_unit_cost),
        "final_entropy_reduction_per_unit_cost": (scientific.final_entropy_reduction_per_unit_cost),
        "final_true_hypothesis_probability": scientific.final_true_hypothesis_probability,
        "final_true_hypothesis_rank": float(scientific.final_true_hypothesis_rank),
        "experiments_to_80_confidence": _optional_float(scientific.experiments_to_80_confidence),
        "experiments_to_95_confidence": _optional_float(scientific.experiments_to_95_confidence),
        "cost_to_80_confidence": scientific.cost_to_80_confidence,
        "cost_to_95_confidence": scientific.cost_to_95_confidence,
        "redundant_experiments_selected": float(scientific.redundant_experiments_selected),
        "matched_evidence_pairs_completed": float(scientific.matched_evidence_pairs_completed),
        "final_brier_calibration": scientific.final_brier_calibration,
        "total_experimental_cost": objective.total_experimental_cost,
        "experiments_completed": float(objective.experiments_completed),
        "best_observed_objective": objective.best_observed_objective,
    }


def _optional_float(value: int | None) -> float | None:
    return None if value is None else float(value)


def _initial_condition_fingerprint(
    *,
    world_config: BenchmarkWorldConfig,
    design: BenchmarkDesign,
    seed: int,
    budget: float,
    initial_probabilities: tuple[tuple[str, float], ...],
) -> str:
    payload = {
        "world": world_config.to_dict(),
        "design": design.to_dict(),
        "seed": seed,
        "budget": budget,
        "initial_beliefs": dict(initial_probabilities),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _dependency_versions() -> tuple[tuple[str, str], ...]:
    return (
        ("python", platform.python_version()),
        ("research_decision_engine", __version__),
        ("sqlite", sqlite3.sqlite_version),
    )


def _validate_benchmark_inputs(
    *, policies: tuple[str, ...], seeds: tuple[int, ...], budget: float
) -> None:
    if not policies or len(policies) != len(set(policies)):
        raise ValueError("Benchmark policies must be non-empty and unique.")
    unknown_policies = set(policies).difference(ALL_BENCHMARK_POLICIES)
    if unknown_policies:
        raise ValueError(f"Unknown benchmark policies: {', '.join(sorted(unknown_policies))}")
    if not seeds or len(seeds) != len(set(seeds)):
        raise ValueError("Benchmark seeds must be non-empty and unique.")
    if not math.isfinite(budget) or budget <= 0.0:
        raise ValueError("Benchmark budget must be finite and positive.")
    if not all_benchmark_world_ids():
        raise RuntimeError("Benchmark suite has no worlds.")


def _assert_real_benchmark_persistence(
    store: ExperimentStore,
    trace: list[ExperimentMetricTrace],
) -> None:
    """Reject benchmark runs that materialize simulated planning state."""

    records = store.list_records()
    evidence = store.list_evidence()
    updates = store.list_belief_updates()
    current = store.current_belief_state()
    if current is None:
        raise RuntimeError("Benchmark persistence audit found no belief state.")
    if len(records) != len(trace):
        raise RuntimeError("Benchmark persistence audit found non-real experiment rows.")
    if len(evidence) != current.sequence or len(updates) != current.sequence:
        raise RuntimeError("Benchmark persistence audit found hypothetical reasoning rows.")
    if store.list_decision_traces() or store.list_lookahead_plan_traces():
        raise RuntimeError("Benchmark persistence audit found persisted simulated decision traces.")
    if any(item.created_at == "SIMULATED-NOT-PERSISTED" for item in records):
        raise RuntimeError("Benchmark persistence audit found a simulated experiment row.")
