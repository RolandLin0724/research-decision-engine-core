"""Machine-readable and terminal reporting for benchmark results."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from research_decision_engine.benchmarks.evaluation import (
    AggregateResult,
    BenchmarkReport,
)

POLICY_COLUMN_WIDTH = 29


@dataclass(frozen=True, slots=True)
class BenchmarkOutputPaths:
    json_results: Path
    run_results_csv: Path
    trace_results_csv: Path
    aggregate_results_csv: Path


def write_benchmark_outputs(
    report: BenchmarkReport, output_directory: Path
) -> BenchmarkOutputPaths:
    """Write full JSON plus run, trace, and aggregate CSV files."""

    output_directory.mkdir(parents=True, exist_ok=True)
    paths = BenchmarkOutputPaths(
        json_results=output_directory / "benchmark_results.json",
        run_results_csv=output_directory / "benchmark_runs.csv",
        trace_results_csv=output_directory / "benchmark_traces.csv",
        aggregate_results_csv=output_directory / "benchmark_aggregates.csv",
    )
    paths.json_results.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_csv(paths.run_results_csv, _run_rows(report))
    _write_csv(paths.trace_results_csv, _trace_rows(report))
    _write_csv(paths.aggregate_results_csv, _aggregate_rows(report))
    return paths


def render_terminal_summary(report: BenchmarkReport, output_paths: BenchmarkOutputPaths) -> str:
    """Render a compact summary without implying statistical significance."""

    lines = [
        f"Research Decision Engine Core benchmark: {report.benchmark_version}",
        (
            f"Runs: {len(report.runs)} | worlds: {len(report.world_ids)} | "
            f"seeds: {len(report.seeds)} | cost budget: {report.budget:.3f}"
        ),
        "",
        "Scientific progress (entropy and Brier lower; true probability higher):",
        (
            f"{'policy':<{POLICY_COLUMN_WIDTH}}"
            "entropy   info/cost   true_prob    brier      pairs   redundant  reached_80"
        ),
    ]
    for aggregate in report.aggregates_by_policy:
        lines.append(
            f"{aggregate.policy:<{POLICY_COLUMN_WIDTH}}"
            f"{_mean(aggregate, 'final_posterior_entropy'):>10}"
            f"{_mean(aggregate, 'final_entropy_reduction_per_unit_cost'):>12}"
            f"{_mean(aggregate, 'final_true_hypothesis_probability'):>13}"
            f"{_mean(aggregate, 'final_brier_calibration'):>11}"
            f"{_mean(aggregate, 'matched_evidence_pairs_completed'):>9}"
            f"{_mean(aggregate, 'redundant_experiments_selected'):>12}"
            f"{aggregate.successful_80_confidence_runs:>12}/{aggregate.run_count}"
        )
    lines.extend(
        [
            "",
            "Objective optimization (best observed higher):",
            f"{'policy':<{POLICY_COLUMN_WIDTH}}best_observed   total_cost   experiments",
        ]
    )
    for aggregate in report.aggregates_by_policy:
        lines.append(
            f"{aggregate.policy:<{POLICY_COLUMN_WIDTH}}"
            f"{_mean(aggregate, 'best_observed_objective'):>15}"
            f"{_mean(aggregate, 'total_experimental_cost'):>13}"
            f"{_mean(aggregate, 'experiments_completed'):>14}"
        )
    lines.extend(
        [
            "",
            (
                "Confidence intervals are descriptive 95% normal approximations; "
                "no significance test was run."
            ),
            f"JSON: {output_paths.json_results}",
            f"Runs CSV: {output_paths.run_results_csv}",
            f"Traces CSV: {output_paths.trace_results_csv}",
            f"Aggregates CSV: {output_paths.aggregate_results_csv}",
        ]
    )
    return "\n".join(lines)


def _run_rows(report: BenchmarkReport) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for run in report.runs:
        row: dict[str, object] = {
            "benchmark_version": run.benchmark_version,
            "generated_at": run.generated_at,
            "world_id": run.world_config.world_id,
            "hidden_true_hypothesis": run.world_config.true_hypothesis_id,
            "true_optimizer_effect": run.world_config.true_optimizer_effect,
            "noise_level": run.world_config.noise_level,
            "observation_noise_std": run.world_config.observation_noise_std,
            "cost_mode": run.world_config.cost_mode,
            "candidate_variant": run.world_config.candidate_variant,
            "policy": run.policy,
            "policy_version": run.policy_version,
            "seed": run.seed,
            "budget": run.budget,
            "schema_version": run.schema_version,
            "initial_condition_fingerprint": run.initial_condition_fingerprint,
            "stop_reason": run.stop_reason,
            "budget_exhausted": run.budget_exhausted,
        }
        row.update(run.scientific_metrics.to_dict())
        row.update(run.objective_metrics.to_dict())
        rows.append(row)
    return rows


def _trace_rows(report: BenchmarkReport) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for run in report.runs:
        for item in run.trace:
            rows.append(
                {
                    "benchmark_version": run.benchmark_version,
                    "world_id": run.world_config.world_id,
                    "hidden_true_hypothesis": run.world_config.true_hypothesis_id,
                    "policy": run.policy,
                    "policy_version": run.policy_version,
                    "seed": run.seed,
                    "budget": run.budget,
                    "step": item.step,
                    "candidate_id": item.candidate_id,
                    "observed_objective": item.observed_objective,
                    "experiment_cost": item.experiment_cost,
                    "cumulative_cost": item.cumulative_cost,
                    "posterior_entropy": item.posterior_entropy,
                    "posterior_entropy_per_unit_cost": (item.posterior_entropy_per_unit_cost),
                    "entropy_reduction_per_unit_cost": (item.entropy_reduction_per_unit_cost),
                    "true_hypothesis_probability": item.true_hypothesis_probability,
                    "true_hypothesis_rank": item.true_hypothesis_rank,
                    "posterior_probabilities_json": json.dumps(
                        dict(item.posterior_probabilities), sort_keys=True
                    ),
                    "redundant_experiment": item.redundant_experiment,
                    "cumulative_redundant_experiments": (item.cumulative_redundant_experiments),
                    "new_matched_evidence": item.new_matched_evidence,
                    "matched_evidence_pairs_completed": (item.matched_evidence_pairs_completed),
                    "best_observed_objective": item.best_observed_objective,
                }
            )
    return rows


def _aggregate_rows(report: BenchmarkReport) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for aggregate in (
        *report.aggregates_by_policy_world,
        *report.aggregates_by_policy,
    ):
        for metric_name, summary in aggregate.metrics:
            rows.append(
                {
                    "scope": aggregate.scope,
                    "world_id": aggregate.world_id,
                    "policy": aggregate.policy,
                    "run_count": aggregate.run_count,
                    "successful_80_confidence_runs": (aggregate.successful_80_confidence_runs),
                    "successful_95_confidence_runs": (aggregate.successful_95_confidence_runs),
                    "budget_exhausted_runs": aggregate.budget_exhausted_runs,
                    "metric": metric_name,
                    "sample_count": summary.count,
                    "mean": summary.mean,
                    "median": summary.median,
                    "standard_deviation": summary.standard_deviation,
                    "confidence_level": 0.95,
                    "confidence_interval_low": summary.confidence_interval_low,
                    "confidence_interval_high": summary.confidence_interval_high,
                }
            )
    return rows


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"Cannot write empty benchmark CSV: {path.name}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _mean(aggregate: AggregateResult, metric_name: str) -> str:
    value = aggregate.metric(metric_name).mean
    return "n/a" if value is None else f"{value:.4f}"
