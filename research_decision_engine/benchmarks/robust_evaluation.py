"""Frozen paired evaluation of the two Gaussian belief models."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import statistics
from dataclasses import dataclass, fields
from random import Random
from typing import cast

from research_decision_engine.belief_models import (
    CALIBRATED_SIGMA_MODEL_ID,
    FIXED_SIGMA_MODEL_ID,
    BeliefModelLineage,
    GaussianBeliefModel,
    MatchedEffectObservation,
    ModelAdequacyDiagnostic,
    ModelBeliefUpdate,
    belief_models,
    initial_model_lineage,
)
from research_decision_engine.benchmarks.evaluation import (
    ALL_BENCHMARK_POLICIES,
    POLICY_VERSIONS,
    BenchmarkRunResult,
    PolicyBenchmarkContext,
    posterior_entropy,
    run_benchmark_condition,
)
from research_decision_engine.benchmarks.paired_evaluation import (
    BOOTSTRAP_SEED,
    CALIBRATION_BIN_COUNT,
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
    build_benchmark_world,
    paired_evaluation_worlds,
)
from research_decision_engine.calibration import (
    CALIBRATION_EFFECT_COUNT,
    CalibrationArm,
    CalibrationPrefix,
    build_calibration_prefix,
)
from research_decision_engine.decision import InformationGainPolicy
from research_decision_engine.lookahead import LookaheadInformationGainPolicy
from research_decision_engine.optimizer_effect import evidence_from_matched_pair
from research_decision_engine.policies import (
    GreedyPredictedPerformancePolicy,
    RandomPolicy,
)
from research_decision_engine.storage import SCHEMA_VERSION
from research_decision_engine.types import CompletedExperiment

ROBUST_BELIEF_EVALUATION_VERSION = "robust-belief-evaluation/v1"
ROBUST_BELIEF_MODELS = (FIXED_SIGMA_MODEL_ID, CALIBRATED_SIGMA_MODEL_ID)
ROBUST_POLICIES = ALL_BENCHMARK_POLICIES
ROBUST_SHORT_BUDGET = DEFAULT_SHORT_BUDGET
ROBUST_LARGE_BUDGET = DEFAULT_LARGE_BUDGET
ROBUST_DEFAULT_SEEDS = DEFAULT_PAIRED_SEEDS
ROBUST_BOOTSTRAP_RESAMPLES = DEFAULT_BOOTSTRAP_RESAMPLES
CONFIDENTLY_WRONG_THRESHOLD = 0.80
COMPARISON_TOLERANCE = 1e-12


class RobustEvaluationInvariantError(RuntimeError):
    """Raised when the frozen paired protocol is violated."""


@dataclass(frozen=True, slots=True)
class ModelExperimentTrace:
    """Truth-free model state after one real policy-selected experiment."""

    step: int
    candidate_id: str
    observed_objective: float
    experiment_cost: float
    cumulative_decision_cost: float
    posterior_probabilities: tuple[tuple[str, float], ...]
    posterior_entropy: float
    evidence_ids: tuple[str, ...]
    new_evidence_ids: tuple[str, ...]
    latest_sigma: float | None
    latest_sigma_status: str | None
    latest_adequacy_state: str

    def to_dict(self) -> dict[str, object]:
        return {
            "step": self.step,
            "candidate_id": self.candidate_id,
            "observed_objective": self.observed_objective,
            "experiment_cost": self.experiment_cost,
            "cumulative_decision_cost": self.cumulative_decision_cost,
            "posterior_probabilities": dict(self.posterior_probabilities),
            "posterior_entropy": self.posterior_entropy,
            "evidence_ids": list(self.evidence_ids),
            "new_evidence_ids": list(self.new_evidence_ids),
            "latest_sigma": self.latest_sigma,
            "latest_sigma_status": self.latest_sigma_status,
            "latest_adequacy_state": self.latest_adequacy_state,
        }


@dataclass(frozen=True, slots=True)
class TruthFreeLineageReplay:
    """One model replay whose interface contains no evaluator truth."""

    belief_model_id: str
    belief_model_version: str
    lineage: BeliefModelLineage
    updates: tuple[ModelBeliefUpdate, ...]
    diagnostics: tuple[ModelAdequacyDiagnostic, ...]
    decision_effects: tuple[MatchedEffectObservation, ...]
    experiment_trace: tuple[ModelExperimentTrace, ...]
    evidence_stream_fingerprint: str

    def final_posterior(self) -> dict[str, float]:
        return self.lineage.current_state.state.posterior_map()


@dataclass(frozen=True, slots=True)
class RobustRunMetrics:
    """Evaluator-only scientific, calibration, cost, and objective metrics."""

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
    reached_80_confidence: bool
    reached_95_confidence: bool
    experiments_to_80_confidence: int | None
    experiments_to_95_confidence: int | None
    cost_to_80_confidence: float | None
    cost_to_95_confidence: float | None
    matched_evidence_pairs_completed: int
    redundant_experiments_selected: int
    decision_cost: float
    calibration_cost: float
    total_cost: float
    fixed_model_required_cost: float
    calibrated_model_required_cost: float
    decision_phase_efficiency: float | None
    calibrated_end_to_end_efficiency: float | None
    best_observed_objective: float | None
    cumulative_predictive_log_likelihood: float
    mean_predictive_log_likelihood: float | None
    empirical_coverage_50: float | None
    empirical_coverage_80: float | None
    empirical_coverage_95: float | None
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
            "reached_80_confidence": float(self.reached_80_confidence),
            "reached_95_confidence": float(self.reached_95_confidence),
            "experiments_to_80_confidence": _optional_float(self.experiments_to_80_confidence),
            "experiments_to_95_confidence": _optional_float(self.experiments_to_95_confidence),
            "cost_to_80_confidence": self.cost_to_80_confidence,
            "cost_to_95_confidence": self.cost_to_95_confidence,
            "matched_evidence_pairs_completed": float(self.matched_evidence_pairs_completed),
            "redundant_experiments_selected": float(self.redundant_experiments_selected),
            "decision_cost": self.decision_cost,
            "calibration_cost": self.calibration_cost,
            "total_cost": self.total_cost,
            "fixed_model_required_cost": self.fixed_model_required_cost,
            "calibrated_model_required_cost": self.calibrated_model_required_cost,
            "decision_phase_efficiency": self.decision_phase_efficiency,
            "calibrated_end_to_end_efficiency": self.calibrated_end_to_end_efficiency,
            "best_observed_objective": self.best_observed_objective,
            "cumulative_predictive_log_likelihood": (self.cumulative_predictive_log_likelihood),
            "mean_predictive_log_likelihood": self.mean_predictive_log_likelihood,
            "empirical_coverage_50": self.empirical_coverage_50,
            "empirical_coverage_80": self.empirical_coverage_80,
            "empirical_coverage_95": self.empirical_coverage_95,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.numeric_values(),
            "confidently_wrong": self.confidently_wrong,
            "prediction_correct": self.prediction_correct,
            "predicted_hypothesis_id": self.predicted_hypothesis_id,
            "final_adequacy_state": self.final_adequacy_state,
        }


@dataclass(frozen=True, slots=True)
class RobustEvaluationRun:
    """One model-scored view of a shared real decision stream."""

    run_id: str
    paired_stream_id: str
    evaluation_version: str
    belief_model_id: str
    belief_model_version: str
    lineage_id: str
    world_id: str
    policy: str
    policy_version: str
    seed: int
    budget_label: str
    budget: float
    generated_at: str
    schema_version: int
    calibration_prefix_id: str
    observation_schedule_fingerprint: str
    evidence_stream_fingerprint: str
    initial_posterior_probabilities: tuple[tuple[str, float], ...]
    final_posterior_probabilities: tuple[tuple[str, float], ...]
    metrics: RobustRunMetrics
    trace: tuple[ModelExperimentTrace, ...]
    diagnostics: tuple[ModelAdequacyDiagnostic, ...]
    model_updates: tuple[ModelBeliefUpdate, ...]
    sigma_estimate_ids: tuple[str, ...]
    hidden_true_hypothesis: str

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "paired_stream_id": self.paired_stream_id,
            "evaluation_version": self.evaluation_version,
            "belief_model_id": self.belief_model_id,
            "belief_model_version": self.belief_model_version,
            "lineage_id": self.lineage_id,
            "world_id": self.world_id,
            "policy": self.policy,
            "policy_version": self.policy_version,
            "seed": self.seed,
            "budget_label": self.budget_label,
            "budget": self.budget,
            "timestamp": self.generated_at,
            "schema_version": self.schema_version,
            "calibration_prefix_id": self.calibration_prefix_id,
            "observation_schedule_fingerprint": self.observation_schedule_fingerprint,
            "evidence_stream_fingerprint": self.evidence_stream_fingerprint,
            "initial_posterior_probabilities": dict(self.initial_posterior_probabilities),
            "final_posterior_probabilities": dict(self.final_posterior_probabilities),
            "metrics": self.metrics.to_dict(),
            "full_metric_trace": [item.to_dict() for item in self.trace],
            "diagnostic_ids": [item.diagnostic_id for item in self.diagnostics],
            "sigma_estimate_ids": list(self.sigma_estimate_ids),
            "hidden_true_hypothesis": self.hidden_true_hypothesis,
        }


@dataclass(frozen=True, slots=True)
class RobustEvaluationAudits:
    fixed_sigma_reproduces_controller: bool
    exactly_five_calibration_effects_per_group: bool
    calibration_preserves_prior: bool
    calibration_decision_namespaces_disjoint: bool
    arm_noise_keys_independent: bool
    current_and_future_evidence_excluded: bool
    identical_decision_streams_between_models: bool
    isolated_lineages: bool
    hidden_truth_absent_from_model_inputs: bool
    provenance_complete: bool
    cost_ledgers_reconcile: bool
    deterministic_prefix_replay: bool
    deterministic_lineage_replay: bool

    def all_passed(self) -> bool:
        return all(self.to_dict().values())

    def to_dict(self) -> dict[str, bool]:
        return {
            "fixed_sigma_reproduces_controller": self.fixed_sigma_reproduces_controller,
            "exactly_five_calibration_effects_per_group": (
                self.exactly_five_calibration_effects_per_group
            ),
            "calibration_preserves_prior": self.calibration_preserves_prior,
            "calibration_decision_namespaces_disjoint": (
                self.calibration_decision_namespaces_disjoint
            ),
            "arm_noise_keys_independent": self.arm_noise_keys_independent,
            "current_and_future_evidence_excluded": (self.current_and_future_evidence_excluded),
            "identical_decision_streams_between_models": (
                self.identical_decision_streams_between_models
            ),
            "isolated_lineages": self.isolated_lineages,
            "hidden_truth_absent_from_model_inputs": self.hidden_truth_absent_from_model_inputs,
            "provenance_complete": self.provenance_complete,
            "cost_ledgers_reconcile": self.cost_ledgers_reconcile,
            "deterministic_prefix_replay": self.deterministic_prefix_replay,
            "deterministic_lineage_replay": self.deterministic_lineage_replay,
        }


@dataclass(frozen=True, slots=True)
class RobustEvaluationResult:
    evaluation_version: str
    generated_at: str
    seeds: tuple[int, ...]
    budgets: tuple[tuple[str, float], ...]
    prefixes: tuple[CalibrationPrefix, ...]
    runs: tuple[RobustEvaluationRun, ...]
    audits: RobustEvaluationAudits
    bootstrap_resamples: int


def run_robust_belief_evaluation(
    *,
    seeds: tuple[int, ...] = ROBUST_DEFAULT_SEEDS,
    short_budget: float = ROBUST_SHORT_BUDGET,
    large_budget: float = ROBUST_LARGE_BUDGET,
    generated_at: str,
    bootstrap_resamples: int = ROBUST_BOOTSTRAP_RESAMPLES,
) -> RobustEvaluationResult:
    """Run one fixed policy stream and two isolated model replays per condition."""

    _validate_inputs(
        seeds=seeds,
        short_budget=short_budget,
        large_budget=large_budget,
        bootstrap_resamples=bootstrap_resamples,
    )
    prefixes: list[CalibrationPrefix] = []
    runs: list[RobustEvaluationRun] = []
    fixed_matches = True
    priors_preserved = True
    streams_match = True
    lineages_isolated = True
    sequential_exclusion = True
    lineages_deterministic = True

    for world_config in paired_evaluation_worlds():
        for seed in seeds:
            design, hidden_world = build_benchmark_world(world_config, seed=seed)
            prefix = build_calibration_prefix(
                world_id=world_config.world_id,
                evaluation_seed=seed,
                designs=design.evidence_eligibility().designs,
                candidates={item.candidate_id: item for item in design.candidates},
                cost=design.cost,
                observe_pair=hidden_world.observe_calibration_pair,
                created_at=f"{generated_at}#calibration:{world_config.world_id}:{seed}",
            )
            duplicate_prefix = build_calibration_prefix(
                world_id=world_config.world_id,
                evaluation_seed=seed,
                designs=design.evidence_eligibility().designs,
                candidates={item.candidate_id: item for item in design.candidates},
                cost=design.cost,
                observe_pair=hidden_world.observe_calibration_pair,
                created_at=f"{generated_at}#calibration:{world_config.world_id}:{seed}",
            )
            if prefix.to_dict() != duplicate_prefix.to_dict():
                raise RobustEvaluationInvariantError(
                    "Calibration prefix replay is not deterministic."
                )
            prefixes.append(prefix)

            for budget_label, budget in (
                ("short", short_budget),
                ("large", large_budget),
            ):
                for policy in ROBUST_POLICIES:
                    controller = run_benchmark_condition(
                        world_config=world_config,
                        policy=policy,
                        seed=seed,
                        budget=budget,
                        generated_at=generated_at,
                    )
                    replay_by_model: dict[str, TruthFreeLineageReplay] = {}
                    for model in belief_models():
                        replay = replay_decision_stream(
                            model=model,
                            controller=controller,
                            design=design,
                            prefix=prefix,
                            lineage_key=(f"{world_config.world_id}:{seed}:{budget_label}:{policy}"),
                        )
                        replay_by_model[model.model_id] = replay
                        repeated_replay = replay_decision_stream(
                            model=model,
                            controller=controller,
                            design=design,
                            prefix=prefix,
                            lineage_key=(f"{world_config.world_id}:{seed}:{budget_label}:{policy}"),
                        )
                        lineages_deterministic = (
                            lineages_deterministic and replay == repeated_replay
                        )
                        priors_preserved = priors_preserved and (
                            replay.updates[0].state_before.state.sequence == 0
                            if replay.updates
                            else replay.lineage.current_state.state.sequence == 0
                        )
                        sequential_exclusion = sequential_exclusion and all(
                            update.sigma_estimate.current_evidence_excluded
                            and update.evidence.evidence_id
                            not in update.sigma_estimate.source_effect_ids
                            for update in replay.updates
                        )

                    fixed_replay = replay_by_model[FIXED_SIGMA_MODEL_ID]
                    calibrated_replay = replay_by_model[CALIBRATED_SIGMA_MODEL_ID]
                    streams_match = streams_match and (
                        fixed_replay.evidence_stream_fingerprint
                        == calibrated_replay.evidence_stream_fingerprint
                    )
                    lineages_isolated = lineages_isolated and (
                        fixed_replay.lineage.lineage_id != calibrated_replay.lineage.lineage_id
                        and fixed_replay.lineage.current_state.state.belief_state_id
                        != calibrated_replay.lineage.current_state.state.belief_state_id
                    )
                    fixed_matches = fixed_matches and _fixed_replay_matches_controller(
                        fixed_replay, controller
                    )
                    paired_stream_id = _stable_id(
                        "decision-stream",
                        {
                            "budget": budget,
                            "policy": policy,
                            "seed": seed,
                            "trace": [
                                (item.candidate_id, item.observed_objective)
                                for item in controller.trace
                            ],
                            "world_id": world_config.world_id,
                        },
                    )
                    observation_fingerprint = _stable_id(
                        "observations",
                        [(item.candidate_id, item.observed_objective) for item in controller.trace],
                    )
                    # Truth enters only after both truth-free lineage replays are complete.
                    for model_id in ROBUST_BELIEF_MODELS:
                        replay = replay_by_model[model_id]
                        metrics = score_lineage_replay(
                            replay=replay,
                            controller=controller,
                            hidden_true_hypothesis=world_config.true_hypothesis_id,
                            calibration_cost=prefix.calibration_cost,
                        )
                        run_id = _stable_id(
                            "robust-run",
                            {
                                "belief_model_id": model_id,
                                "paired_stream_id": paired_stream_id,
                                "version": ROBUST_BELIEF_EVALUATION_VERSION,
                            },
                        )
                        runs.append(
                            RobustEvaluationRun(
                                run_id=run_id,
                                paired_stream_id=paired_stream_id,
                                evaluation_version=ROBUST_BELIEF_EVALUATION_VERSION,
                                belief_model_id=model_id,
                                belief_model_version=replay.belief_model_version,
                                lineage_id=replay.lineage.lineage_id,
                                world_id=world_config.world_id,
                                policy=policy,
                                policy_version=POLICY_VERSIONS[policy],
                                seed=seed,
                                budget_label=budget_label,
                                budget=budget,
                                generated_at=generated_at,
                                schema_version=SCHEMA_VERSION,
                                calibration_prefix_id=prefix.prefix_id,
                                observation_schedule_fingerprint=observation_fingerprint,
                                evidence_stream_fingerprint=(replay.evidence_stream_fingerprint),
                                initial_posterior_probabilities=tuple(
                                    sorted(replay.lineage.current_state.state.prior_map().items())
                                ),
                                final_posterior_probabilities=tuple(
                                    sorted(replay.final_posterior().items())
                                ),
                                metrics=metrics,
                                trace=replay.experiment_trace,
                                diagnostics=replay.diagnostics,
                                model_updates=replay.updates,
                                sigma_estimate_ids=tuple(
                                    item.sigma_estimate.estimate_id for item in replay.updates
                                ),
                                hidden_true_hypothesis=world_config.true_hypothesis_id,
                            )
                        )

    audits = RobustEvaluationAudits(
        fixed_sigma_reproduces_controller=fixed_matches,
        exactly_five_calibration_effects_per_group=all(
            all(
                len(prefix.effects_for_group(group.comparison_group_id)) == CALIBRATION_EFFECT_COUNT
                for group in prefix.groups
            )
            for prefix in prefixes
        ),
        calibration_preserves_prior=priors_preserved,
        calibration_decision_namespaces_disjoint=all(
            all(item.source_kind == "calibration" for item in _prefix_history(prefix))
            for prefix in prefixes
        ),
        arm_noise_keys_independent=all(
            all(adam.arm_noise_key != sgd.arm_noise_key for adam, sgd in _prefix_arm_pairs(prefix))
            for prefix in prefixes
        ),
        current_and_future_evidence_excluded=sequential_exclusion,
        identical_decision_streams_between_models=streams_match,
        isolated_lineages=lineages_isolated,
        hidden_truth_absent_from_model_inputs=_truth_isolation_audit(),
        provenance_complete=_provenance_audit(tuple(prefixes), tuple(runs)),
        cost_ledgers_reconcile=all(
            math.isclose(
                run.metrics.total_cost,
                run.metrics.calibration_cost + run.metrics.decision_cost,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            for run in runs
        ),
        deterministic_prefix_replay=True,
        deterministic_lineage_replay=lineages_deterministic,
    )
    if not audits.all_passed():
        failed = [name for name, passed in audits.to_dict().items() if not passed]
        raise RobustEvaluationInvariantError(
            "Robust evaluation audits failed: " + ", ".join(failed)
        )
    return RobustEvaluationResult(
        evaluation_version=ROBUST_BELIEF_EVALUATION_VERSION,
        generated_at=generated_at,
        seeds=seeds,
        budgets=(("short", short_budget), ("large", large_budget)),
        prefixes=tuple(prefixes),
        runs=tuple(runs),
        audits=audits,
        bootstrap_resamples=bootstrap_resamples,
    )


def replay_decision_stream(
    *,
    model: GaussianBeliefModel,
    controller: BenchmarkRunResult,
    design: BenchmarkDesign,
    prefix: CalibrationPrefix,
    lineage_key: str,
) -> TruthFreeLineageReplay:
    """Replay public experiments through one model without evaluator truth."""

    lineage = initial_model_lineage(
        model,
        lineage_key=lineage_key,
        created_at=f"{controller.generated_at}#lineage:{model.model_id}",
    )
    calibration_history = _prefix_history(prefix)
    effect_history: list[MatchedEffectObservation] = list(calibration_history)
    decision_effects: list[MatchedEffectObservation] = []
    updates: list[ModelBeliefUpdate] = []
    diagnostics: list[ModelAdequacyDiagnostic] = []
    trace: list[ModelExperimentTrace] = []
    completed: list[CompletedExperiment] = []
    applied_pairs: set[tuple[int, ...]] = set()
    eligibility = design.evidence_eligibility()
    candidates = {item.candidate_id: item for item in design.candidates}

    for controller_step in controller.trace:
        candidate = candidates[controller_step.candidate_id]
        completed.append(
            CompletedExperiment(
                record_id=controller_step.step,
                candidate=candidate,
                observed_value=controller_step.observed_objective,
                created_at=(f"{controller.generated_at}#experiment-{controller_step.step:04d}"),
            )
        )
        new_evidence_ids: list[str] = []
        latest_sigma: float | None = None
        latest_sigma_status: str | None = None
        for pair in eligibility.valid_unapplied_pairs(
            tuple(completed),
            applied_source_pairs=frozenset(applied_pairs),
        ):
            evidence = evidence_from_matched_pair(pair, eligibility)
            lineage, update, current_effect = model.update(
                lineage=lineage,
                evidence=evidence,
                effect_history=tuple(effect_history),
                diagnostic_history=tuple(diagnostics),
            )
            updates.append(update)
            diagnostics.append(update.diagnostic)
            effect_history.append(current_effect)
            decision_effects.append(current_effect)
            applied_pairs.add(pair.source_experiment_ids)
            new_evidence_ids.append(evidence.evidence_id)
            latest_sigma = update.sigma_estimate.estimated_sigma
            latest_sigma_status = update.sigma_estimate.status

        posterior = lineage.current_state.state.posterior_map()
        trace.append(
            ModelExperimentTrace(
                step=controller_step.step,
                candidate_id=controller_step.candidate_id,
                observed_objective=controller_step.observed_objective,
                experiment_cost=controller_step.experiment_cost,
                cumulative_decision_cost=controller_step.cumulative_cost,
                posterior_probabilities=tuple(sorted(posterior.items())),
                posterior_entropy=posterior_entropy(tuple(posterior.values())),
                evidence_ids=lineage.current_state.state.evidence_ids,
                new_evidence_ids=tuple(new_evidence_ids),
                latest_sigma=latest_sigma,
                latest_sigma_status=latest_sigma_status,
                latest_adequacy_state=(
                    diagnostics[-1].adequacy_state if diagnostics else "uncertain"
                ),
            )
        )
    evidence_fingerprint = _stable_id(
        "evidence-stream",
        [
            (
                update.evidence.evidence_id,
                update.evidence.source_experiment_ids,
                update.evidence.observed_comparison,
            )
            for update in updates
        ],
    )
    return TruthFreeLineageReplay(
        belief_model_id=model.model_id,
        belief_model_version=model.model_version,
        lineage=lineage,
        updates=tuple(updates),
        diagnostics=tuple(diagnostics),
        decision_effects=tuple(decision_effects),
        experiment_trace=tuple(trace),
        evidence_stream_fingerprint=evidence_fingerprint,
    )


def score_lineage_replay(
    *,
    replay: TruthFreeLineageReplay,
    controller: BenchmarkRunResult,
    hidden_true_hypothesis: str,
    calibration_cost: float,
) -> RobustRunMetrics:
    """Score a completed truth-free replay inside the evaluator boundary."""

    posterior = replay.final_posterior()
    classification = classify_posterior(posterior, hidden_true_hypothesis)
    true_probability = posterior[hidden_true_hypothesis]
    brier = math.fsum(
        (probability - float(hypothesis_id == hidden_true_hypothesis)) ** 2
        for hypothesis_id, probability in posterior.items()
    )
    true_rank = 1 + sum(
        probability > true_probability + 1e-15
        for hypothesis_id, probability in posterior.items()
        if hypothesis_id != hidden_true_hypothesis
    )
    initial_entropy = math.log2(len(posterior))
    final_entropy = posterior_entropy(tuple(posterior.values()))
    experiments_80, cost_80 = _first_threshold(
        replay.experiment_trace, hidden_true_hypothesis, 0.80
    )
    experiments_95, cost_95 = _first_threshold(
        replay.experiment_trace, hidden_true_hypothesis, 0.95
    )
    decision_cost = controller.objective_metrics.total_experimental_cost
    total_cost = calibration_cost + decision_cost
    entropy_reduction = initial_entropy - final_entropy
    diagnostics = replay.diagnostics
    return RobustRunMetrics(
        final_true_hypothesis_probability=true_probability,
        negative_log_true_hypothesis_probability=-math.log(
            max(true_probability, NLL_PROBABILITY_FLOOR)
        ),
        final_brier_score=brier,
        confidently_wrong=classification.confidently_wrong,
        prediction_correct=classification.correct,
        predicted_hypothesis_id=classification.predicted_hypothesis_id,
        maximum_posterior_probability=classification.maximum_posterior_probability,
        final_true_hypothesis_rank=true_rank,
        final_posterior_entropy=final_entropy,
        final_entropy_reduction=entropy_reduction,
        reached_80_confidence=experiments_80 is not None,
        reached_95_confidence=experiments_95 is not None,
        experiments_to_80_confidence=experiments_80,
        experiments_to_95_confidence=experiments_95,
        cost_to_80_confidence=cost_80,
        cost_to_95_confidence=cost_95,
        matched_evidence_pairs_completed=len(replay.updates),
        redundant_experiments_selected=(
            controller.scientific_metrics.redundant_experiments_selected
        ),
        decision_cost=decision_cost,
        calibration_cost=calibration_cost,
        total_cost=total_cost,
        fixed_model_required_cost=decision_cost,
        calibrated_model_required_cost=total_cost,
        decision_phase_efficiency=(
            None if decision_cost == 0.0 else entropy_reduction / decision_cost
        ),
        calibrated_end_to_end_efficiency=(
            None if total_cost == 0.0 else entropy_reduction / total_cost
        ),
        best_observed_objective=controller.objective_metrics.best_observed_objective,
        cumulative_predictive_log_likelihood=math.fsum(
            item.predictive_log_likelihood for item in diagnostics
        ),
        mean_predictive_log_likelihood=(
            None
            if not diagnostics
            else statistics.fmean(item.predictive_log_likelihood for item in diagnostics)
        ),
        empirical_coverage_50=_coverage(diagnostics, 0.50),
        empirical_coverage_80=_coverage(diagnostics, 0.80),
        empirical_coverage_95=_coverage(diagnostics, 0.95),
        final_adequacy_state=(diagnostics[-1].adequacy_state if diagnostics else "uncertain"),
    )


def aggregate_metric_rows(
    runs: tuple[RobustEvaluationRun, ...],
) -> tuple[dict[str, object], ...]:
    """Aggregate all numeric run metrics by model, world, budget, and policy."""

    rows: list[dict[str, object]] = []
    for model_id in ROBUST_BELIEF_MODELS:
        for world in paired_evaluation_worlds():
            for budget_label in ("short", "large"):
                for policy in ROBUST_POLICIES:
                    group = tuple(
                        run
                        for run in runs
                        if run.belief_model_id == model_id
                        and run.world_id == world.world_id
                        and run.budget_label == budget_label
                        and run.policy == policy
                    )
                    if not group:
                        continue
                    metric_names = tuple(group[0].metrics.numeric_values())
                    for metric_name in metric_names:
                        values = tuple(
                            value
                            for run in group
                            if (value := run.metrics.numeric_values()[metric_name]) is not None
                        )
                        if not values:
                            continue
                        mean = statistics.fmean(values)
                        standard_deviation = statistics.stdev(values) if len(values) > 1 else 0.0
                        margin = 1.96 * standard_deviation / math.sqrt(len(values))
                        rows.append(
                            {
                                "belief_model_id": model_id,
                                "world_id": world.world_id,
                                "budget_label": budget_label,
                                "policy": policy,
                                "metric": metric_name,
                                "sample_count": len(values),
                                "mean": mean,
                                "median": statistics.median(values),
                                "standard_deviation": standard_deviation,
                                "confidence_interval_low": mean - margin,
                                "confidence_interval_high": mean + margin,
                                "confidence_interval_method": (
                                    "normal approximation for aggregate mean"
                                ),
                            }
                        )
    return tuple(rows)


def calibration_rows(runs: tuple[RobustEvaluationRun, ...]) -> tuple[dict[str, object], ...]:
    """Report truth-dependent calibration by model and policy condition."""

    rows: list[dict[str, object]] = []
    for model_id in ROBUST_BELIEF_MODELS:
        for world in paired_evaluation_worlds():
            for budget_label in ("short", "large"):
                for policy in ROBUST_POLICIES:
                    group = tuple(
                        item
                        for item in runs
                        if item.belief_model_id == model_id
                        and item.world_id == world.world_id
                        and item.budget_label == budget_label
                        and item.policy == policy
                    )
                    if not group:
                        continue
                    observations = tuple(
                        (
                            item.metrics.maximum_posterior_probability,
                            item.metrics.prediction_correct,
                        )
                        for item in group
                    )
                    rows.append(
                        {
                            "belief_model_id": model_id,
                            "world_id": world.world_id,
                            "budget_label": budget_label,
                            "policy": policy,
                            "run_count": len(group),
                            "calibration_error": top_label_expected_calibration_error(observations),
                            "calibration_bin_count": CALIBRATION_BIN_COUNT,
                            "confidently_wrong_count": sum(
                                item.metrics.confidently_wrong for item in group
                            ),
                            "confidently_wrong_rate": statistics.fmean(
                                float(item.metrics.confidently_wrong) for item in group
                            ),
                            "accuracy": statistics.fmean(
                                float(item.metrics.prediction_correct) for item in group
                            ),
                            "mean_nll": statistics.fmean(
                                item.metrics.negative_log_true_hypothesis_probability
                                for item in group
                            ),
                            "mean_brier_score": statistics.fmean(
                                item.metrics.final_brier_score for item in group
                            ),
                        }
                    )
    return tuple(rows)


def paired_comparison_rows(
    runs: tuple[RobustEvaluationRun, ...],
    *,
    bootstrap_resamples: int,
) -> tuple[dict[str, object], ...]:
    """Return calibrated-minus-fixed paired differences for cells and world totals."""

    rows: list[dict[str, object]] = []
    metric_names = tuple(runs[0].metrics.numeric_values())
    for world in paired_evaluation_worlds():
        for budget_label in ("short", "large"):
            for policy in ROBUST_POLICIES:
                cell = tuple(
                    item
                    for item in runs
                    if item.world_id == world.world_id
                    and item.budget_label == budget_label
                    and item.policy == policy
                )
                rows.extend(
                    _paired_metric_rows(
                        cell,
                        world_id=world.world_id,
                        budget_label=budget_label,
                        policy=policy,
                        metric_names=metric_names,
                        bootstrap_resamples=bootstrap_resamples,
                    )
                )
                rows.append(
                    _paired_calibration_error_row(
                        cell,
                        world_id=world.world_id,
                        budget_label=budget_label,
                        policy=policy,
                        bootstrap_resamples=bootstrap_resamples,
                    )
                )
        world_runs = tuple(item for item in runs if item.world_id == world.world_id)
        rows.extend(
            _paired_metric_rows(
                world_runs,
                world_id=world.world_id,
                budget_label="all",
                policy="all",
                metric_names=metric_names,
                bootstrap_resamples=bootstrap_resamples,
                block_by_seed=True,
            )
        )
        rows.append(
            _paired_calibration_error_row(
                world_runs,
                world_id=world.world_id,
                budget_label="all",
                policy="all",
                bootstrap_resamples=bootstrap_resamples,
            )
        )
    return tuple(rows)


def acceptance_gate_results(
    runs: tuple[RobustEvaluationRun, ...],
    paired_rows: tuple[dict[str, object], ...],
    audits: RobustEvaluationAudits,
) -> dict[str, object]:
    """Evaluate the five frozen point-estimate gates and hard audits."""

    def difference(world_id: str, metric: str) -> tuple[float, float, float]:
        row = next(
            item
            for item in paired_rows
            if item["world_id"] == world_id
            and item["budget_label"] == "all"
            and item["policy"] == "all"
            and item["metric"] == metric
        )
        return (
            cast(float, row["mean_paired_difference"]),
            cast(float, row["confidence_interval_low"]),
            cast(float, row["confidence_interval_high"]),
        )

    gate_specs = (
        (
            "adverse_noise_confidently_wrong_reduction",
            "adverse_noisy_observations",
            "confidently_wrong",
            "<=",
            -0.10,
        ),
        (
            "adverse_noise_mean_nll_lower",
            "adverse_noisy_observations",
            "negative_log_true_hypothesis_probability",
            "<",
            0.0,
        ),
        (
            "adverse_noise_mean_brier_lower",
            "adverse_noisy_observations",
            "final_brier_score",
            "<",
            0.0,
        ),
        (
            "delayed_information_true_probability_non_regression",
            "delayed_information",
            "final_true_hypothesis_probability",
            ">=",
            -0.02,
        ),
        (
            "delayed_information_confidently_wrong_non_increase",
            "delayed_information",
            "confidently_wrong",
            "<=",
            0.0,
        ),
    )
    gates: list[dict[str, object]] = []
    for gate_id, world_id, metric, operator, threshold in gate_specs:
        delta, low, high = difference(world_id, metric)
        passed = (
            delta <= threshold
            if operator == "<="
            else delta < threshold
            if operator == "<"
            else delta >= threshold
        )
        gates.append(
            {
                "gate_id": gate_id,
                "world_id": world_id,
                "metric": metric,
                "difference_definition": "calibrated minus fixed",
                "operator": operator,
                "threshold": threshold,
                "point_estimate": delta,
                "paired_95_ci_low": low,
                "paired_95_ci_high": high,
                "passed": passed,
            }
        )
    performance_passed = all(bool(item["passed"]) for item in gates)
    audit_passed = audits.all_passed()
    intervals_reported = all(
        item.get("confidence_interval_low") is not None
        and item.get("confidence_interval_high") is not None
        for item in paired_rows
    )
    accepted = performance_passed and audit_passed and intervals_reported
    return {
        "evaluation_version": ROBUST_BELIEF_EVALUATION_VERSION,
        "difference_definition": "replicated_noise_calibrated_gaussian minus fixed_sigma_gaussian",
        "performance_gates": gates,
        "paired_confidence_intervals_reported": intervals_reported,
        "hard_audits": audits.to_dict(),
        "all_performance_gates_passed": performance_passed,
        "all_hard_audits_passed": audit_passed,
        "calibrated_model_accepted": accepted,
        "default_belief_model": (CALIBRATED_SIGMA_MODEL_ID if accepted else FIXED_SIGMA_MODEL_ID),
        "run_count": len(runs),
    }


def _paired_metric_rows(
    cell: tuple[RobustEvaluationRun, ...],
    *,
    world_id: str,
    budget_label: str,
    policy: str,
    metric_names: tuple[str, ...],
    bootstrap_resamples: int,
    block_by_seed: bool = False,
) -> list[dict[str, object]]:
    fixed = {
        (item.seed, item.budget_label, item.policy): item
        for item in cell
        if item.belief_model_id == FIXED_SIGMA_MODEL_ID
    }
    calibrated = {
        (item.seed, item.budget_label, item.policy): item
        for item in cell
        if item.belief_model_id == CALIBRATED_SIGMA_MODEL_ID
    }
    if fixed.keys() != calibrated.keys():
        raise RobustEvaluationInvariantError("Paired model cells are incomplete.")
    rows: list[dict[str, object]] = []
    for metric_name in metric_names:
        if block_by_seed:
            seed_differences = []
            for seed in sorted({key[0] for key in fixed}):
                values = []
                for key in sorted(item for item in fixed if item[0] == seed):
                    fixed_value = fixed[key].metrics.numeric_values()[metric_name]
                    calibrated_value = calibrated[key].metrics.numeric_values()[metric_name]
                    if fixed_value is not None and calibrated_value is not None:
                        values.append(calibrated_value - fixed_value)
                if values:
                    seed_differences.append(statistics.fmean(values))
            differences = tuple(seed_differences)
        else:
            differences = tuple(
                calibrated_value - fixed_value
                for key in sorted(fixed)
                if (fixed_value := fixed[key].metrics.numeric_values()[metric_name]) is not None
                and (calibrated_value := calibrated[key].metrics.numeric_values()[metric_name])
                is not None
            )
        if not differences:
            continue
        low, high = deterministic_bootstrap_mean_interval(
            differences,
            resamples=bootstrap_resamples,
            key=(
                ROBUST_BELIEF_EVALUATION_VERSION,
                "paired-models",
                world_id,
                budget_label,
                policy,
                metric_name,
            ),
        )
        rows.append(
            {
                "world_id": world_id,
                "budget_label": budget_label,
                "policy": policy,
                "metric": metric_name,
                "difference_definition": "calibrated minus fixed",
                "paired_sample_count": len(differences),
                "mean_paired_difference": statistics.fmean(differences),
                "median_paired_difference": statistics.median(differences),
                "standard_deviation": (
                    statistics.stdev(differences) if len(differences) > 1 else 0.0
                ),
                "confidence_interval_low": low,
                "confidence_interval_high": high,
                "confidence_interval_method": (
                    "seed-blocked deterministic paired percentile bootstrap of mean"
                    if block_by_seed
                    else "deterministic paired percentile bootstrap of mean"
                ),
            }
        )
    return rows


def _paired_calibration_error_row(
    cell: tuple[RobustEvaluationRun, ...],
    *,
    world_id: str,
    budget_label: str,
    policy: str,
    bootstrap_resamples: int,
) -> dict[str, object]:
    fixed_by_seed = _calibration_observations_by_seed(cell, FIXED_SIGMA_MODEL_ID)
    calibrated_by_seed = _calibration_observations_by_seed(cell, CALIBRATED_SIGMA_MODEL_ID)
    if fixed_by_seed.keys() != calibrated_by_seed.keys() or not fixed_by_seed:
        raise RobustEvaluationInvariantError("Calibration comparison is not paired by seed.")
    seeds = tuple(sorted(fixed_by_seed))
    fixed_observations = tuple(item for seed in seeds for item in fixed_by_seed[seed])
    calibrated_observations = tuple(item for seed in seeds for item in calibrated_by_seed[seed])
    point_difference = top_label_expected_calibration_error(
        calibrated_observations
    ) - top_label_expected_calibration_error(fixed_observations)
    seed_material = (
        f"{BOOTSTRAP_SEED}|{ROBUST_BELIEF_EVALUATION_VERSION}|paired-ece|"
        f"{world_id}|{budget_label}|{policy}"
    ).encode()
    random = Random(int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big"))
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
    return {
        "world_id": world_id,
        "budget_label": budget_label,
        "policy": policy,
        "metric": "calibration_error",
        "difference_definition": "calibrated minus fixed",
        "paired_sample_count": len(seeds),
        "mean_paired_difference": point_difference,
        "median_paired_difference": statistics.median(bootstrap_differences),
        "standard_deviation": (
            statistics.stdev(bootstrap_differences) if len(bootstrap_differences) > 1 else 0.0
        ),
        "confidence_interval_low": _percentile(bootstrap_differences, 0.025),
        "confidence_interval_high": _percentile(bootstrap_differences, 0.975),
        "confidence_interval_method": ("paired seed-blocked percentile bootstrap of top-label ECE"),
    }


def _calibration_observations_by_seed(
    cell: tuple[RobustEvaluationRun, ...], model_id: str
) -> dict[int, tuple[tuple[float, bool], ...]]:
    grouped: dict[int, list[tuple[float, bool]]] = {}
    for run in cell:
        if run.belief_model_id == model_id:
            grouped.setdefault(run.seed, []).append(
                (
                    run.metrics.maximum_posterior_probability,
                    run.metrics.prediction_correct,
                )
            )
    return {
        seed: tuple(sorted(items, key=lambda item: (item[0], item[1])))
        for seed, items in grouped.items()
    }


def _percentile(sorted_values: list[float], quantile: float) -> float:
    position = (len(sorted_values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] + fraction * (sorted_values[upper] - sorted_values[lower])


def _fixed_replay_matches_controller(
    replay: TruthFreeLineageReplay,
    controller: BenchmarkRunResult,
) -> bool:
    if len(replay.experiment_trace) != len(controller.trace):
        return False
    return all(
        left.candidate_id == right.candidate_id
        and left.observed_objective == right.observed_objective
        and all(
            math.isclose(
                dict(left.posterior_probabilities)[hypothesis_id],
                probability,
                rel_tol=0.0,
                abs_tol=1e-15,
            )
            for hypothesis_id, probability in right.posterior_probabilities
        )
        for left, right in zip(replay.experiment_trace, controller.trace, strict=True)
    )


def _first_threshold(
    trace: tuple[ModelExperimentTrace, ...],
    true_hypothesis_id: str,
    threshold: float,
) -> tuple[int | None, float | None]:
    for item in trace:
        if dict(item.posterior_probabilities)[true_hypothesis_id] >= threshold:
            return item.step, item.cumulative_decision_cost
    return None, None


def _coverage(diagnostics: tuple[ModelAdequacyDiagnostic, ...], probability: float) -> float | None:
    values = tuple(
        interval.contains_observation
        for diagnostic in diagnostics
        for interval in diagnostic.central_intervals
        if interval.probability == probability
    )
    return None if not values else statistics.fmean(float(item) for item in values)


def _prefix_history(prefix: CalibrationPrefix) -> tuple[MatchedEffectObservation, ...]:
    return tuple(MatchedEffectObservation.from_calibration(item) for item in prefix.matched_effects)


def _prefix_arm_pairs(
    prefix: CalibrationPrefix,
) -> tuple[tuple[CalibrationArm, CalibrationArm], ...]:
    by_id = {item.calibration_arm_id: item for item in prefix.arms}
    return tuple((by_id[item.adam_arm_id], by_id[item.sgd_arm_id]) for item in prefix.replications)


def _truth_isolation_audit() -> bool:
    forbidden = {
        "hidden_true_hypothesis",
        "true_hypothesis_id",
        "true_optimizer_effect",
        "observation_noise_std",
        "world_config",
    }
    context_fields = {item.name for item in fields(PolicyBenchmarkContext)}
    model_parameters = set(inspect.signature(GaussianBeliefModel.update).parameters)
    calibration_parameters = set(inspect.signature(build_calibration_prefix).parameters)
    calibration_fields = {item.name for item in fields(CalibrationPrefix)}
    if (
        context_fields.intersection(forbidden)
        or model_parameters.intersection(forbidden)
        or calibration_parameters.intersection(forbidden)
        or calibration_fields.intersection(forbidden)
    ):
        return False
    for policy_class in (
        RandomPolicy,
        GreedyPredictedPerformancePolicy,
        InformationGainPolicy,
        LookaheadInformationGainPolicy,
    ):
        decision_method = (
            policy_class.decide if hasattr(policy_class, "decide") else policy_class.select
        )
        if set(inspect.signature(decision_method).parameters).intersection(forbidden):
            return False
        module = inspect.getmodule(policy_class)
        if module is None or "research_decision_engine.benchmarks" in inspect.getsource(module):
            return False
    return True


def _provenance_audit(
    prefixes: tuple[CalibrationPrefix, ...], runs: tuple[RobustEvaluationRun, ...]
) -> bool:
    prefix_ok = all(
        all(
            item.provenance.method and item.provenance.version and item.available_sequence == 0
            for item in prefix.matched_effects
        )
        for prefix in prefixes
    )
    update_ok = all(
        all(
            update.provenance.method
            and update.sigma_estimate.provenance.method
            and update.diagnostic.provenance.method
            and update.sigma_estimate.sample_count == len(update.sigma_estimate.source_effect_ids)
            for update in run.model_updates
        )
        for run in runs
    )
    return prefix_ok and update_ok


def _validate_inputs(
    *,
    seeds: tuple[int, ...],
    short_budget: float,
    large_budget: float,
    bootstrap_resamples: int,
) -> None:
    if not seeds or len(seeds) != len(set(seeds)):
        raise ValueError("Robust evaluation seeds must be non-empty and unique.")
    if ROBUST_POLICIES != (
        "random",
        "greedy",
        "information_gain",
        "lookahead_information_gain",
    ):
        raise RobustEvaluationInvariantError("The frozen four-policy set changed.")
    if ROBUST_BELIEF_MODELS != (
        "fixed_sigma_gaussian",
        "replicated_noise_calibrated_gaussian",
    ):
        raise RobustEvaluationInvariantError("The frozen two-model set changed.")
    if not math.isclose(short_budget, 2.25, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("The frozen short budget must remain 2.25.")
    if not math.isclose(large_budget, 4.50, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("The frozen large budget must remain 4.50.")
    if bootstrap_resamples <= 0:
        raise ValueError("Bootstrap resamples must be positive.")


def _optional_float(value: int | None) -> float | None:
    return None if value is None else float(value)


def _stable_id(prefix: str, payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"
