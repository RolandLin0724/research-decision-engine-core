"""Versioned artifacts and reports for the frozen closed-loop evaluation."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import sqlite3
import statistics
from collections.abc import Iterable
from pathlib import Path
from typing import cast

from research_decision_engine import __version__
from research_decision_engine.belief_models import (
    CALIBRATED_SIGMA_MODEL_ID,
    FIXED_SIGMA,
    FIXED_SIGMA_MODEL_ID,
    MINIMUM_PRIOR_EFFECTS,
    SIGMA_FLOOR,
    VARIANCE_FLOOR,
    belief_models,
)
from research_decision_engine.benchmarks.closed_loop_evaluation import (
    CLOSED_LOOP_BOOTSTRAP_RESAMPLES,
    CLOSED_LOOP_EVALUATION_VERSION,
    CONFIDENTLY_WRONG_THRESHOLD,
    FROZEN_DESIGN_SHA256,
    FROZEN_SOURCE_SHA256,
    PRIMARY_ARMS,
    ClosedLoopEvaluationResult,
    ClosedLoopEvaluationRun,
    DecisionDivergence,
)
from research_decision_engine.benchmarks.evaluation import POLICY_VERSIONS
from research_decision_engine.benchmarks.worlds import paired_evaluation_worlds
from research_decision_engine.calibration import (
    CALIBRATION_EFFECT_COUNT,
    CALIBRATION_PREFIX_VERSION,
    CALIBRATION_REPLICATION_VERSION,
)
from research_decision_engine.closed_loop import (
    CANDIDATE_GROUP_ADAPTER_VERSION,
    CLOSED_LOOP_ARM_RUNNER_VERSION,
    SELECTED_ONLY_ORACLE_VERSION,
)
from research_decision_engine.decision import (
    INFORMATION_GAIN_METHOD_VERSION,
    OUTCOME_GRID_MAX,
    OUTCOME_GRID_MIN,
    OUTCOME_GRID_STEP,
    discretized_gaussian_evidence_outcomes,
)
from research_decision_engine.lookahead import LOOKAHEAD_UTILITY_VERSION
from research_decision_engine.storage import SCHEMA_VERSION

CLOSED_LOOP_OUTPUT_SCHEMA_VERSION = "closed-loop-evaluation-artifacts/v1"

OUTPUT_FILENAMES = (
    "protocol_snapshot.json",
    "run_manifest.json",
    "potential_outcome_commitments.jsonl",
    "potential_outcomes.jsonl",
    "calibration_prefixes.jsonl",
    "per_run_results.jsonl",
    "per_run_results.csv",
    "decision_traces.jsonl",
    "evidence_belief_traces.jsonl",
    "divergence_events.jsonl",
    "divergence_events.csv",
    "aggregate_results.csv",
    "paired_closed_loop_comparisons.csv",
    "calibration_results.csv",
    "threshold_results.csv",
    "adequacy_diagnostics.csv",
    "cost_accounting.csv",
    "failure_cases.jsonl",
    "ACCEPTANCE_GATES.json",
    "CLOSED_LOOP_EVALUATION_REPORT.md",
)


def write_closed_loop_outputs(
    result: ClosedLoopEvaluationResult,
    output_directory: Path,
) -> dict[str, Path]:
    """Write every predeclared artifact without overwriting prior evaluations."""

    output_directory.mkdir(parents=True, exist_ok=True)
    existing = tuple(name for name in OUTPUT_FILENAMES if (output_directory / name).exists())
    if existing:
        raise FileExistsError(
            "Refusing to overwrite closed-loop evaluation artifacts: " + ", ".join(existing)
        )
    paths = {name: output_directory / name for name in OUTPUT_FILENAMES}
    threshold_rows = _threshold_rows(result.runs)
    adequacy_rows = _adequacy_rows(result.runs)
    cost_rows = _cost_rows(result)
    failure_cases = _failure_cases(result)

    _write_json(paths["protocol_snapshot.json"], _protocol_snapshot(result))
    _write_jsonl(
        paths["potential_outcome_commitments.jsonl"],
        (
            {
                **bundle.commitment.to_dict(),
                "calibration_prefix_id": bundle.calibration_prefix_id,
                "calibration_prefix_sha256": bundle.calibration_prefix_sha256,
            }
            for bundle in result.potential_outcomes
        ),
    )
    _write_jsonl(
        paths["potential_outcomes.jsonl"],
        (
            {
                "record_visibility": "evaluator_only",
                "world_id": bundle.world_id,
                "evaluation_seed": bundle.evaluation_seed,
                "commitment_id": bundle.commitment.commitment_id,
                **outcome.to_evaluator_dict(),
            }
            for bundle in result.potential_outcomes
            for outcome in bundle.outcomes
        ),
    )
    _write_jsonl(
        paths["calibration_prefixes.jsonl"],
        (
            {
                **prefix.to_dict(),
                "record_role": "calibration_only",
                "scientific_belief_updates": 0,
            }
            for prefix in result.prefixes
        ),
    )
    _write_jsonl(paths["per_run_results.jsonl"], (item.to_dict() for item in result.runs))
    _write_csv(paths["per_run_results.csv"], _per_run_rows(result.runs))
    _write_jsonl(paths["decision_traces.jsonl"], _decision_trace_rows(result.runs))
    _write_jsonl(
        paths["evidence_belief_traces.jsonl"],
        _evidence_belief_rows(result.runs),
    )
    _write_jsonl(
        paths["divergence_events.jsonl"],
        (item.to_dict() for item in result.divergences),
    )
    _write_csv(
        paths["divergence_events.csv"],
        tuple(item.to_dict() for item in result.divergences),
    )
    _write_csv(paths["aggregate_results.csv"], result.aggregate_rows)
    _write_csv(paths["paired_closed_loop_comparisons.csv"], result.paired_rows)
    _write_csv(paths["calibration_results.csv"], result.calibration_rows)
    _write_csv(paths["threshold_results.csv"], threshold_rows)
    _write_csv(paths["adequacy_diagnostics.csv"], adequacy_rows)
    _write_csv(paths["cost_accounting.csv"], cost_rows)
    _write_jsonl(paths["failure_cases.jsonl"], failure_cases)
    _write_json(paths["ACCEPTANCE_GATES.json"], result.acceptance)
    paths["CLOSED_LOOP_EVALUATION_REPORT.md"].write_text(
        render_closed_loop_report(result),
        encoding="utf-8",
    )

    output_hashes = {
        name: _sha256(path) for name, path in paths.items() if name != "run_manifest.json"
    }
    _write_json(paths["run_manifest.json"], _manifest(result, output_hashes))
    _validate_written_artifacts(result, paths, output_hashes)
    return paths


def render_closed_loop_terminal_summary(
    result: ClosedLoopEvaluationResult,
    paths: dict[str, Path],
) -> str:
    failed = tuple(item for item in _performance_gates(result) if not cast(bool, item["passed"]))
    return "\n".join(
        (
            "Closed-loop belief-control evaluation complete",
            f"runs: {len(result.runs)}",
            f"paired controller comparisons: {len(result.runs) // 2}",
            f"hard audits passed: {result.audits.all_passed()}",
            f"verdict: {result.acceptance['verdict']}",
            f"failed performance inequalities: {len(failed)} / {len(_performance_gates(result))}",
            f"artifacts: {paths['run_manifest.json'].parent}",
        )
    )


def _protocol_snapshot(result: ClosedLoopEvaluationResult) -> dict[str, object]:
    return {
        "output_schema_version": CLOSED_LOOP_OUTPUT_SCHEMA_VERSION,
        "evaluation_version": CLOSED_LOOP_EVALUATION_VERSION,
        "generated_at": result.generated_at,
        "full_frozen_matrix": result.full_frozen_matrix,
        "primary_arms": [
            {
                "arm_id": item.arm_id,
                "belief_model_id": item.belief_model_id,
                "policy": item.policy,
                "policy_version": item.policy_version,
            }
            for item in PRIMARY_ARMS
        ],
        "policy_versions": {
            policy: POLICY_VERSIONS[policy]
            for policy in ("information_gain", "lookahead_information_gain")
        },
        "models": [
            {"model_id": item.model_id, "model_version": item.model_version}
            for item in belief_models()
        ],
        "adapter_version": CANDIDATE_GROUP_ADAPTER_VERSION,
        "arm_runner_version": CLOSED_LOOP_ARM_RUNNER_VERSION,
        "oracle_version": SELECTED_ONLY_ORACLE_VERSION,
        "information_gain_method": INFORMATION_GAIN_METHOD_VERSION,
        "lookahead_utility": LOOKAHEAD_UTILITY_VERSION,
        "lookahead_horizon": 2,
        "fixed_sigma": FIXED_SIGMA,
        "calibrated_sigma_rule": "max(sample stdev with ddof=1, sigma_floor)",
        "minimum_prior_effects": MINIMUM_PRIOR_EFFECTS,
        "sigma_floor": SIGMA_FLOOR,
        "variance_floor": VARIANCE_FLOOR,
        "calibration_effects_per_group": CALIBRATION_EFFECT_COUNT,
        "calibration_prefix_version": CALIBRATION_PREFIX_VERSION,
        "calibration_replication_version": CALIBRATION_REPLICATION_VERSION,
        "calibration_updates_scientific_beliefs": False,
        "outcome_grid": {
            "minimum": OUTCOME_GRID_MIN,
            "maximum": OUTCOME_GRID_MAX,
            "step": OUTCOME_GRID_STEP,
            "unbounded_tail_bins": 2,
        },
        "confidently_wrong_threshold": CONFIDENTLY_WRONG_THRESHOLD,
        "seeds": list(result.seeds),
        "budgets": dict(result.budgets),
        "bootstrap": {
            "resamples": result.bootstrap_resamples,
            "frozen_full_resamples": CLOSED_LOOP_BOOTSTRAP_RESAMPLES,
            "confidence_level": 0.95,
            "method": "deterministic paired seed-blocked percentile bootstrap",
        },
        "worlds": {
            "record_visibility": "evaluator_only",
            "configurations": [item.to_dict() for item in paired_evaluation_worlds()],
        },
        "source_sha256": FROZEN_SOURCE_SHA256,
        "design_sha256": FROZEN_DESIGN_SHA256,
        "acceptance_inequalities": result.acceptance["performance_gates"],
        "hidden_truth_access": "evaluator only after each arm trajectory is complete",
        "counterfactual_access": "selected candidates only until post-run evaluator release",
    }


def _manifest(
    result: ClosedLoopEvaluationResult,
    output_hashes: dict[str, str],
) -> dict[str, object]:
    return {
        "output_schema_version": CLOSED_LOOP_OUTPUT_SCHEMA_VERSION,
        "evaluation_version": result.evaluation_version,
        "generated_at": result.generated_at,
        "dependency_versions": {
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "research_decision_engine": __version__,
        },
        "sqlite_schema_version": SCHEMA_VERSION,
        "source_tree_sha256": _source_tree_hash(),
        "seeds": list(result.seeds),
        "budgets": dict(result.budgets),
        "run_count": len(result.runs),
        "expected_full_run_count": 3200,
        "full_frozen_matrix": result.full_frozen_matrix,
        "prefix_count": len(result.prefixes),
        "potential_outcome_commitment_count": len(result.potential_outcomes),
        "divergence_record_count": len(result.divergences),
        "paired_comparison_row_count": len(result.paired_rows),
        "acceptance_gate_count": len(_performance_gates(result)),
        "audits": result.audits.to_dict(),
        "verdict": result.acceptance["verdict"],
        "historical_artifact_sha256_before_evaluation": dict(result.historical_artifact_hashes),
        "output_sha256": output_hashes,
    }


def _per_run_rows(
    runs: tuple[ClosedLoopEvaluationRun, ...],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "run_id": run.run_id,
            "world_id": run.world_id,
            "seed": run.seed,
            "budget_label": run.budget_label,
            "budget": run.budget,
            "arm_id": run.arm.arm_id,
            "belief_model_id": run.belief_model_id,
            "belief_model_version": run.arm_run.spec.belief_model_version,
            "lineage_id": run.arm_run.lineage.lineage_id,
            "policy": run.policy,
            "policy_version": run.arm.policy_version,
            "commitment_id": run.commitment_id,
            "calibration_prefix_id": run.arm_run.spec.calibration_prefix_id,
            "stop_reason": run.arm_run.stop_reason,
            "selected_candidate_ids": json.dumps(
                [item.candidate.candidate_id for item in run.arm_run.experiments]
            ),
            "final_posterior_probabilities": json.dumps(
                run.arm_run.final_posterior(), sort_keys=True
            ),
            "evaluator_only_hidden_true_hypothesis": (run.world_config.true_hypothesis_id),
            **run.metrics.to_dict(),
        }
        for run in runs
    )


def _decision_trace_rows(
    runs: tuple[ClosedLoopEvaluationRun, ...],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "record_visibility": "truth_free_operational_trace",
            "run_id": run.run_id,
            "world_id": run.world_id,
            "evaluation_seed": run.seed,
            "budget_label": run.budget_label,
            "arm_id": run.arm.arm_id,
            **decision.to_dict(),
        }
        for run in runs
        for decision in run.arm_run.decisions
    )


def _evidence_belief_rows(
    runs: tuple[ClosedLoopEvaluationRun, ...],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "record_visibility": "truth_free_operational_trace",
            "run_id": run.run_id,
            "world_id": run.world_id,
            "evaluation_seed": run.seed,
            "budget_label": run.budget_label,
            "arm_id": run.arm.arm_id,
            "belief_model_id": run.belief_model_id,
            "lineage_id": run.arm_run.lineage.lineage_id,
            "initial_posterior_probabilities": dict(run.arm_run.initial_posterior_probabilities),
            "experiments": [item.to_dict() for item in run.arm_run.experiments],
            "evidence": [item.to_dict() for item in run.arm_run.evidence],
            "model_updates": [item.to_dict() for item in run.arm_run.model_updates],
            "adequacy_diagnostics": [item.to_dict() for item in run.arm_run.diagnostics],
            "matched_effect_history": [item.to_dict() for item in run.arm_run.effect_history],
            "posterior_trace": [item.to_dict() for item in run.arm_run.trace],
            "final_posterior_probabilities": run.arm_run.final_posterior(),
        }
        for run in runs
    )


def _threshold_rows(
    runs: tuple[ClosedLoopEvaluationRun, ...],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "record_visibility": "evaluator_only_metric",
            "run_id": run.run_id,
            "world_id": run.world_id,
            "seed": run.seed,
            "budget_label": run.budget_label,
            "arm_id": run.arm.arm_id,
            "belief_model_id": run.belief_model_id,
            "policy": run.policy,
            "hidden_true_hypothesis": run.world_config.true_hypothesis_id,
            "reached_sustained_80_confidence": (run.metrics.reached_sustained_80_confidence),
            "experiments_to_sustained_80_confidence": (
                run.metrics.experiments_to_sustained_80_confidence
            ),
            "decision_cost_to_sustained_80_confidence": (
                run.metrics.decision_cost_to_sustained_80_confidence
            ),
            "total_cost_to_sustained_80_confidence": (
                run.metrics.total_cost_to_sustained_80_confidence
            ),
            "confidence_80_reversals": run.metrics.confidence_80_reversals,
            "reached_sustained_95_confidence": (run.metrics.reached_sustained_95_confidence),
            "experiments_to_sustained_95_confidence": (
                run.metrics.experiments_to_sustained_95_confidence
            ),
            "decision_cost_to_sustained_95_confidence": (
                run.metrics.decision_cost_to_sustained_95_confidence
            ),
            "total_cost_to_sustained_95_confidence": (
                run.metrics.total_cost_to_sustained_95_confidence
            ),
            "confidence_95_reversals": run.metrics.confidence_95_reversals,
            "first_commitment_step": run.metrics.first_commitment_step,
            "first_commitment_decision_cost": (run.metrics.first_commitment_decision_cost),
            "ended_uncommitted": run.metrics.ended_uncommitted,
        }
        for run in runs
    )


def _adequacy_rows(
    runs: tuple[ClosedLoopEvaluationRun, ...],
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for run in runs:
        update_by_diagnostic = {
            item.diagnostic.diagnostic_id: item for item in run.arm_run.model_updates
        }
        evidence_step = {
            evidence_id: trace.step
            for trace in run.arm_run.trace
            for evidence_id in trace.new_evidence_ids
        }
        for diagnostic in run.arm_run.diagnostics:
            update = update_by_diagnostic[diagnostic.diagnostic_id]
            step = evidence_step[diagnostic.evidence_id]
            decision = run.arm_run.decisions[step - 1]
            snapshot = next(
                item
                for item in decision.prediction_snapshots
                if item.comparison_group_id == diagnostic.comparison_group_id
            )
            distribution = discretized_gaussian_evidence_outcomes(
                snapshot.hypotheses,
                update.state_before.state.posterior_probabilities,
            )
            planned_branch = next(
                branch
                for branch in distribution.branches
                if _branch_contains(
                    branch.lower_bound,
                    branch.upper_bound,
                    update.evidence.observed_comparison,
                )
            )
            intervals = {item.probability: item for item in diagnostic.central_intervals}
            rows.append(
                {
                    "record_visibility": "truth_free_operational_diagnostic",
                    "run_id": run.run_id,
                    "world_id": run.world_id,
                    "seed": run.seed,
                    "budget_label": run.budget_label,
                    "arm_id": run.arm.arm_id,
                    "belief_model_id": run.belief_model_id,
                    "policy": run.policy,
                    "lineage_id": run.arm_run.lineage.lineage_id,
                    "step": step,
                    "diagnostic_id": diagnostic.diagnostic_id,
                    "evidence_id": diagnostic.evidence_id,
                    "comparison_group_id": diagnostic.comparison_group_id,
                    "predecision_prediction_snapshot_id": snapshot.snapshot_id,
                    "predecision_group_sigma": snapshot.estimated_sigma,
                    "planned_evidence_bin_id": planned_branch.branch_id,
                    "planned_evidence_bin_probability": (planned_branch.predictive_probability),
                    "observed_matched_effect": update.evidence.observed_comparison,
                    "sigma_estimate_id": diagnostic.sigma_estimate_id,
                    "sigma_status": update.sigma_estimate.status,
                    "sigma_source_count": update.sigma_estimate.sample_count,
                    "sigma_source_effect_ids": json.dumps(update.sigma_estimate.source_effect_ids),
                    "estimated_sigma": update.sigma_estimate.estimated_sigma,
                    "posterior_predictive_tail_probability": (
                        diagnostic.posterior_predictive_tail_probability
                    ),
                    "standardized_residual": diagnostic.standardized_residual,
                    "predictive_log_likelihood": (diagnostic.predictive_log_likelihood),
                    "coverage_50": intervals[0.50].contains_observation,
                    "coverage_80": intervals[0.80].contains_observation,
                    "coverage_95": intervals[0.95].contains_observation,
                    "tail_alarm": diagnostic.tail_alarm,
                    "residual_outlier": diagnostic.residual_outlier,
                    "repeated_residual_alarm": diagnostic.repeated_residual_alarm,
                    "diagnostics_disagree": diagnostic.diagnostics_disagree,
                    "adequacy_state": diagnostic.adequacy_state,
                    "diagnostic_version": diagnostic.diagnostic_version,
                }
            )
    return tuple(rows)


def _branch_contains(lower: float | None, upper: float | None, value: float) -> bool:
    return (lower is None or value >= lower) and (upper is None or value < upper)


def _cost_rows(result: ClosedLoopEvaluationResult) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for run in result.runs:
        rows.append(
            {
                "row_type": "attributed_run_cost",
                "run_id": run.run_id,
                "world_id": run.world_id,
                "seed": run.seed,
                "budget_label": run.budget_label,
                "arm_id": run.arm.arm_id,
                "belief_model_id": run.belief_model_id,
                "policy": run.policy,
                "calibration_prefix_id": run.arm_run.spec.calibration_prefix_id,
                "calibration_cost": run.metrics.calibration_cost,
                "decision_cost": run.metrics.decision_cost,
                "required_total_cost": run.metrics.required_total_cost,
                "decision_budget": run.budget,
                "decision_budget_respected": (run.metrics.decision_cost <= run.budget + 1e-12),
                "ledgers_reconcile": math.isclose(
                    run.metrics.calibration_cost + run.metrics.decision_cost,
                    run.metrics.required_total_cost,
                    rel_tol=0.0,
                    abs_tol=1e-9,
                ),
            }
        )
    for prefix in result.prefixes:
        rows.append(
            {
                "row_type": "deduplicated_physical_calibration_prefix",
                "run_id": "",
                "world_id": prefix.world_id,
                "seed": prefix.evaluation_seed,
                "budget_label": "shared",
                "arm_id": "shared_calibrated_arms",
                "belief_model_id": CALIBRATED_SIGMA_MODEL_ID,
                "policy": "shared",
                "calibration_prefix_id": prefix.prefix_id,
                "calibration_cost": prefix.calibration_cost,
                "decision_cost": 0.0,
                "required_total_cost": prefix.calibration_cost,
                "decision_budget": "",
                "decision_budget_respected": True,
                "ledgers_reconcile": True,
            }
        )
    rows.append(
        {
            "row_type": "suite_physical_cost_summary",
            "run_id": "",
            "world_id": "all",
            "seed": "all",
            "budget_label": "all",
            "arm_id": "all",
            "belief_model_id": "all",
            "policy": "all",
            "calibration_prefix_id": "deduplicated",
            "calibration_cost": math.fsum(item.calibration_cost for item in result.prefixes),
            "decision_cost": math.fsum(item.metrics.decision_cost for item in result.runs),
            "required_total_cost": math.fsum(item.calibration_cost for item in result.prefixes)
            + math.fsum(item.metrics.decision_cost for item in result.runs),
            "decision_budget": "not_applicable",
            "decision_budget_respected": True,
            "ledgers_reconcile": True,
        }
    )
    return tuple(rows)


def _failure_cases(result: ClosedLoopEvaluationResult) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for run in result.runs:
        if run.metrics.confidently_wrong:
            rows.append(
                {
                    "failure_type": "confidently_wrong",
                    "record_visibility": "evaluator_only_metric",
                    "run_id": run.run_id,
                    "world_id": run.world_id,
                    "seed": run.seed,
                    "budget_label": run.budget_label,
                    "arm_id": run.arm.arm_id,
                    "belief_model_id": run.belief_model_id,
                    "policy": run.policy,
                    "hidden_true_hypothesis": run.world_config.true_hypothesis_id,
                    "predicted_hypothesis_id": run.metrics.predicted_hypothesis_id,
                    "maximum_posterior_probability": (run.metrics.maximum_posterior_probability),
                    "true_hypothesis_probability": (run.metrics.final_true_hypothesis_probability),
                    "nll": run.metrics.negative_log_true_hypothesis_probability,
                    "brier": run.metrics.final_brier_score,
                    "selected_candidate_ids": [
                        item.candidate.candidate_id for item in run.arm_run.experiments
                    ],
                }
            )
        for diagnostic in run.arm_run.diagnostics:
            if diagnostic.adequacy_state == "appears_misspecified":
                rows.append(
                    {
                        "failure_type": "planner_model_mismatch_alarm",
                        "record_visibility": "truth_free_operational_diagnostic",
                        "run_id": run.run_id,
                        "world_id": run.world_id,
                        "seed": run.seed,
                        "budget_label": run.budget_label,
                        "arm_id": run.arm.arm_id,
                        "belief_model_id": run.belief_model_id,
                        "policy": run.policy,
                        "diagnostic_id": diagnostic.diagnostic_id,
                        "evidence_id": diagnostic.evidence_id,
                        "tail_probability": (diagnostic.posterior_predictive_tail_probability),
                        "standardized_residual": diagnostic.standardized_residual,
                    }
                )
    for item in result.divergences:
        if item.correctness_effect == "hurt" or item.calibrated_excessively_conservative:
            rows.append(
                {
                    "failure_type": (
                        "calibrated_divergence_hurt"
                        if item.correctness_effect == "hurt"
                        else "excessive_caution"
                    ),
                    **item.to_dict(),
                }
            )
    for gate in _performance_gates(result):
        if not cast(bool, gate["passed"]):
            rows.append(
                {
                    "failure_type": "acceptance_gate_failure",
                    **gate,
                }
            )
    return tuple(rows)


def render_closed_loop_report(result: ClosedLoopEvaluationResult) -> str:
    """Render the predeclared protocol and measured results without spin."""

    gates = _performance_gates(result)
    failed = tuple(item for item in gates if not cast(bool, item["passed"]))
    lines = [
        "# Closed-Loop Belief-Control Evaluation Report",
        "",
        f"Evaluation version: `{result.evaluation_version}`  ",
        f"Generated: `{result.generated_at}`  ",
        f"Primary runs: `{len(result.runs)}`  ",
        f"Seeds: `{len(result.seeds)}`  ",
        f"Verdict: **`{result.acceptance['verdict']}`**",
        "",
        "## Closed-Loop Protocol",
        "",
        "Each of the four primary arms owned an isolated belief lineage, experiment history, "
        "evidence stream, decision trace, and cost ledger. At every real step, that arm's "
        "posterior and public history drove the unchanged information-gain or two-step "
        "lookahead policy. Only the selected candidate was revealed by the committed oracle; "
        "the resulting real evidence then updated that same arm before replanning.",
        "",
        "Calibrated arms used five calibration-only matched effects per public comparison "
        "group. Those effects estimated sigma and never updated the uniform scientific prior. "
        "Fixed arms used `sigma = 0.05` and could not inspect calibration records. Calibration, "
        "decision, and required total costs were kept separate.",
        "",
        "## Results By World, Budget, And Policy",
        "",
        "Means use all declared seeds. Lower is better for NLL, Brier, confidently wrong, and "
        "entropy; higher is better for true-hypothesis probability.",
        "",
        (
            "| World | Budget | Policy | Model | True p | NLL | Brier | CW | Entropy | "
            "Decision cost | Calibration cost | Total cost | Best objective |"
        ),
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for world in paired_evaluation_worlds():
        for budget_label in ("short", "large"):
            for policy in ("information_gain", "lookahead_information_gain"):
                for model_id in (FIXED_SIGMA_MODEL_ID, CALIBRATED_SIGMA_MODEL_ID):
                    group = tuple(
                        item
                        for item in result.runs
                        if item.world_id == world.world_id
                        and item.budget_label == budget_label
                        and item.policy == policy
                        and item.belief_model_id == model_id
                    )
                    lines.append(
                        f"| {world.world_id} | {budget_label} | {policy} | {model_id} | "
                        f"{_mean(group, 'final_true_hypothesis_probability'):.4f} | "
                        f"{_mean(group, 'negative_log_true_hypothesis_probability'):.4f} | "
                        f"{_mean(group, 'final_brier_score'):.4f} | "
                        f"{_mean(group, 'confidently_wrong'):.4f} | "
                        f"{_mean(group, 'final_posterior_entropy'):.4f} | "
                        f"{_mean(group, 'decision_cost'):.4f} | "
                        f"{_mean(group, 'calibration_cost'):.4f} | "
                        f"{_mean(group, 'required_total_cost'):.4f} | "
                        f"{_mean(group, 'best_observed_objective'):.4f} |"
                    )
    lines.extend(_divergence_report(result.divergences))
    lines.extend(
        [
            "",
            "## Acceptance Gates",
            "",
            f"All hard audits passed: **{result.audits.all_passed()}**. "
            f"Performance inequalities passed: **{len(gates) - len(failed)}/{len(gates)}**.",
            "",
            "| Gate | Metric | Fixed | Calibrated | Delta | Paired 95% CI | Requirement | Result |",
            "|---|---|---:|---:|---:|---:|---|---|",
        ]
    )
    for gate in gates:
        lines.append(
            f"| {gate['gate_id']} | {gate['metric']} | "
            f"{_format_number(gate['fixed_value'])} | "
            f"{_format_number(gate['calibrated_value'])} | "
            f"{_format_number(gate['paired_difference'])} | "
            f"[{_format_number(gate['paired_95_ci_low'])}, "
            f"{_format_number(gate['paired_95_ci_high'])}] | "
            f"{gate['evaluated_statistic']} {gate['operator']} "
            f"{_format_number(gate['required_threshold'])} | "
            f"{'PASS' if gate['passed'] else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            "Every paired interval, including optional paired-success threshold costs, is in "
            "`paired_closed_loop_comparisons.csv`. No significance claim is inferred from a "
            "small smoke matrix.",
            "",
            "## Costs",
            "",
            _cost_summary(result),
            "",
            "## Negative Results And Limitations",
            "",
            _negative_summary(result, failed),
            "",
            "The benchmark remains synthetic, uses only three optimizer-effect hypotheses, "
            "estimates one Gaussian sigma per public group from five calibration effects, and "
            "plans for at most two experiments. Common randomness preserves run-level pairing "
            "after divergence but does not make divergent evidence streams item-wise paired. "
            "Best objective is secondary and does not enter acceptance.",
            "",
            "## Exactly One Next Milestone",
            "",
            _next_milestone(result),
            "",
        ]
    )
    return "\n".join(lines)


def _divergence_report(
    divergences: tuple[DecisionDivergence, ...],
) -> list[str]:
    diverged = tuple(item for item in divergences if item.first_divergence_step is not None)
    helped = sum(item.correctness_effect == "helped" for item in diverged)
    hurt = sum(item.correctness_effect == "hurt" for item in diverged)
    mixed = sum(item.correctness_effect == "mixed" for item in diverged)
    tied = sum(item.correctness_effect == "tied" for item in diverged)
    first = next(
        (
            item
            for item in diverged
            if item.world_id == "adverse_noisy_observations"
            and item.policy == "lookahead_information_gain"
        ),
        diverged[0] if diverged else None,
    )
    lines = [
        "",
        "## Decision Divergence",
        "",
        f"Fixed and calibrated trajectories diverged in `{len(diverged)}` of "
        f"`{len(divergences)}` paired runs. Among divergent pairs, calibrated control helped "
        f"both proper scores in `{helped}`, hurt both in `{hurt}`, was mixed in `{mixed}`, and "
        f"tied in `{tied}`.",
    ]
    if first is None:
        lines.append("No trajectory divergence occurred in this run matrix.")
        return lines
    lines.extend(
        [
            "",
            "One deterministic divergence example:",
            "",
            f"- Condition: `{first.world_id}`, `{first.budget_label}`, `{first.policy}`, seed "
            f"`{first.seed}`.",
            f"- First divergence step: `{first.first_divergence_step}`; fixed selected "
            f"`{first.fixed_selected_candidate}` at score "
            f"`{_format_number(first.fixed_decision_score)}`, calibrated selected "
            f"`{first.calibrated_selected_candidate}` at score "
            f"`{_format_number(first.calibrated_decision_score)}`.",
            f"- Beliefs immediately before divergence: fixed "
            f"`{dict(first.fixed_belief_before_divergence or ())}`, calibrated "
            f"`{dict(first.calibrated_belief_before_divergence or ())}`.",
            f"- Final consequence: `{first.correctness_effect}`; calibrated-minus-fixed NLL "
            f"`{first.nll_difference:.6f}`, Brier `{first.brier_difference:.6f}`, and decision "
            f"cost `{first.decision_cost_difference:.6f}`.",
        ]
    )
    return lines


def _mean(runs: tuple[ClosedLoopEvaluationRun, ...], metric: str) -> float:
    values = tuple(
        value for run in runs if (value := run.metrics.numeric_values()[metric]) is not None
    )
    if not values:
        return math.nan
    return statistics.fmean(values)


def _cost_summary(result: ClosedLoopEvaluationResult) -> str:
    attributed_calibration = math.fsum(item.metrics.calibration_cost for item in result.runs)
    decision = math.fsum(item.metrics.decision_cost for item in result.runs)
    physical_calibration = math.fsum(item.calibration_cost for item in result.prefixes)
    required = math.fsum(item.metrics.required_total_cost for item in result.runs)
    return (
        f"Run-attributed calibration cost was `{attributed_calibration:.2f}`, real decision "
        f"cost was `{decision:.2f}`, and run-attributed required total cost was "
        f"`{required:.2f}`. Deduplicated physical calibration-prefix cost was "
        f"`{physical_calibration:.2f}`. Calibration never reduced a decision budget."
    )


def _negative_summary(
    result: ClosedLoopEvaluationResult,
    failed: tuple[dict[str, object], ...],
) -> str:
    hurt = sum(item.correctness_effect == "hurt" for item in result.divergences)
    caution = sum(item.calibrated_excessively_conservative for item in result.divergences)
    wrong_fixed = sum(
        item.metrics.confidently_wrong
        for item in result.runs
        if item.belief_model_id == FIXED_SIGMA_MODEL_ID
    )
    wrong_calibrated = sum(
        item.metrics.confidently_wrong
        for item in result.runs
        if item.belief_model_id == CALIBRATED_SIGMA_MODEL_ID
    )
    if failed:
        gate_text = ", ".join(f"`{item['gate_id']}`" for item in failed)
        verdict_text = f"Failed predeclared inequalities: {gate_text}."
    else:
        verdict_text = "No predeclared performance inequality failed."
    return (
        f"{verdict_text} Calibrated control hurt both proper scores in `{hurt}` paired runs "
        f"and triggered the excessive-caution diagnostic in `{caution}`. Confidently wrong "
        f"runs were fixed=`{wrong_fixed}` and calibrated=`{wrong_calibrated}`. These failures "
        "are retained rather than repaired or filtered."
    )


def _next_milestone(result: ClosedLoopEvaluationResult) -> str:
    verdict = result.acceptance["verdict"]
    if verdict == "scientifically_improved_but_not_end_to_end_efficient":
        return (
            "Run one frozen calibration-prefix sufficiency study that varies only the number "
            "of replicated matched effects and measures whether closed-loop proper-score gains "
            "survive lower standalone calibration cost."
        )
    if verdict == "calibrated_closed_loop_control_accepted":
        return (
            "Run one frozen external-validity benchmark with prespecified heterogeneous public "
            "comparison-group noise while keeping both accepted controllers unchanged."
        )
    return (
        "Run one frozen divergence-mechanism audit focused on the measured failed gate cells, "
        "replaying their committed outcomes without changing models, policies, or thresholds."
    )


def _performance_gates(
    result: ClosedLoopEvaluationResult,
) -> tuple[dict[str, object], ...]:
    return cast(tuple[dict[str, object], ...], result.acceptance["performance_gates"])


def _format_number(value: object) -> str:
    if value is None:
        return "n/a"
    return f"{cast(float, value):.6f}"


def _validate_written_artifacts(
    result: ClosedLoopEvaluationResult,
    paths: dict[str, Path],
    output_hashes: dict[str, str],
) -> None:
    if set(paths) != set(OUTPUT_FILENAMES) or any(not path.is_file() for path in paths.values()):
        raise RuntimeError("Closed-loop output artifact set is incomplete.")
    manifest = json.loads(paths["run_manifest.json"].read_text(encoding="utf-8"))
    if manifest["output_sha256"] != output_hashes:
        raise RuntimeError("Closed-loop manifest output hashes do not reconcile.")
    if any(_sha256(paths[name]) != digest for name, digest in output_hashes.items()):
        raise RuntimeError("A closed-loop output changed after hashing.")
    if _jsonl_count(paths["per_run_results.jsonl"]) != len(result.runs):
        raise RuntimeError("Per-run JSONL row count does not match the primary matrix.")
    if _jsonl_count(paths["divergence_events.jsonl"]) != len(result.divergences):
        raise RuntimeError("Divergence JSONL row count is incomplete.")
    if _jsonl_count(paths["potential_outcome_commitments.jsonl"]) != len(result.potential_outcomes):
        raise RuntimeError("Potential-outcome commitment rows are incomplete.")
    for name in (
        "per_run_results.csv",
        "divergence_events.csv",
        "aggregate_results.csv",
        "paired_closed_loop_comparisons.csv",
        "calibration_results.csv",
        "threshold_results.csv",
        "adequacy_diagnostics.csv",
        "cost_accounting.csv",
    ):
        with paths[name].open(encoding="utf-8", newline="") as handle:
            tuple(csv.DictReader(handle))
    gates = json.loads(paths["ACCEPTANCE_GATES.json"].read_text(encoding="utf-8"))
    if gates["verdict"] != result.acceptance["verdict"]:
        raise RuntimeError("Acceptance-gate artifact does not match evaluator verdict.")


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _write_csv(path: Path, rows: tuple[dict[str, object], ...]) -> None:
    normalized = tuple(_csv_safe_row(item) for item in rows)
    fieldnames: list[str] = []
    for row in normalized:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        if not fieldnames:
            return
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(normalized)


def _csv_safe_row(row: dict[str, object]) -> dict[str, object]:
    return {
        key: (
            json.dumps(value, sort_keys=True, separators=(",", ":"))
            if isinstance(value, (dict, list, tuple))
            else value
        )
        for key, value in row.items()
    }


def _jsonl_count(path: Path) -> int:
    with path.open(encoding="utf-8") as handle:
        return sum(bool(line.strip()) for line in handle)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_tree_hash() -> str:
    package_root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(package_root.rglob("*.py")):
        digest.update(path.relative_to(package_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
