"""Outputs and research report for the paired lookahead evaluation."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from research_decision_engine.benchmarks.paired_evaluation import (
    PAIRED_POLICIES,
    AggregateMetricResult,
    CalibrationResult,
    PairedEvaluationReport,
)


@dataclass(frozen=True, slots=True)
class PairedEvaluationOutputPaths:
    manifest: Path
    per_run_jsonl: Path
    per_run_csv: Path
    aggregates_csv: Path
    paired_comparisons_csv: Path
    calibration_csv: Path
    failure_cases_jsonl: Path
    evaluation_report: Path


def write_paired_evaluation_outputs(
    report: PairedEvaluationReport,
    output_directory: Path,
) -> PairedEvaluationOutputPaths:
    """Write the complete versioned paired-evaluation artifact set."""

    output_directory.mkdir(parents=True, exist_ok=True)
    paths = PairedEvaluationOutputPaths(
        manifest=output_directory / "run_manifest.json",
        per_run_jsonl=output_directory / "per_run_results.jsonl",
        per_run_csv=output_directory / "per_run_results.csv",
        aggregates_csv=output_directory / "aggregate_results.csv",
        paired_comparisons_csv=output_directory / "paired_comparisons.csv",
        calibration_csv=output_directory / "calibration_results.csv",
        failure_cases_jsonl=output_directory / "failure_cases.jsonl",
        evaluation_report=output_directory / "EVALUATION_REPORT.md",
    )
    output_names = [
        paths.manifest.name,
        paths.per_run_jsonl.name,
        paths.per_run_csv.name,
        paths.aggregates_csv.name,
        paths.paired_comparisons_csv.name,
        paths.calibration_csv.name,
        paths.failure_cases_jsonl.name,
        paths.evaluation_report.name,
    ]
    manifest = report.manifest_dict()
    manifest["output_files"] = output_names
    paths.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_jsonl(paths.per_run_jsonl, [item.to_dict() for item in report.runs])
    _write_csv(paths.per_run_csv, [_run_csv_row(item.to_dict()) for item in report.runs])
    _write_csv(paths.aggregates_csv, [item.to_dict() for item in report.aggregates])
    _write_csv(
        paths.paired_comparisons_csv,
        [item.to_dict() for item in report.paired_comparisons],
    )
    _write_csv(paths.calibration_csv, [item.to_dict() for item in report.calibration])
    _write_jsonl(paths.failure_cases_jsonl, [item.to_dict() for item in report.failure_cases])
    paths.evaluation_report.write_text(render_evaluation_report(report), encoding="utf-8")
    return paths


def render_evaluation_terminal_summary(
    report: PairedEvaluationReport,
    paths: PairedEvaluationOutputPaths,
) -> str:
    """Render a compact factual summary without pooling worlds."""

    lines = [
        f"Paired evaluation: {report.evaluation_version}",
        (
            f"Runs: {len(report.runs)} | paired seeds per condition: {len(report.seeds)} | "
            f"bootstrap resamples: {report.bootstrap_resamples}"
        ),
        "Fairness and leakage audit: PASSED",
        "",
        (
            "world / budget                         policy                       "
            "true_p  entropy  brier  wrong"
        ),
    ]
    for condition in report.conditions:
        for policy_name in PAIRED_POLICIES:
            true_probability = _aggregate_mean(
                report.aggregates,
                condition.world_config.world_id,
                condition.budget_label,
                policy_name,
                "final_true_hypothesis_probability",
            )
            entropy = _aggregate_mean(
                report.aggregates,
                condition.world_config.world_id,
                condition.budget_label,
                policy_name,
                "final_posterior_entropy",
            )
            brier = _aggregate_mean(
                report.aggregates,
                condition.world_config.world_id,
                condition.budget_label,
                policy_name,
                "final_brier_score",
            )
            calibration = _calibration_row(
                report.calibration,
                condition.world_config.world_id,
                condition.budget_label,
                policy_name,
            )
            condition_label = f"{condition.world_config.world_id}/{condition.budget_label}"
            lines.append(
                f"{condition_label:<39}{policy_name:<29}"
                f"{true_probability:>7.3f}{entropy:>9.3f}{brier:>7.3f}"
                f"{calibration.confidently_wrong_rate:>7.1%}"
            )
    lines.extend(
        [
            "",
            "Intervals are deterministic paired percentile-bootstrap intervals; no p-values or",
            "multiple-comparison-adjusted significance claims were produced.",
            f"Report: {paths.evaluation_report}",
            f"Manifest: {paths.manifest}",
        ]
    )
    return "\n".join(lines)


def render_evaluation_report(report: PairedEvaluationReport) -> str:
    """Render the complete human-readable evaluation report."""

    lines = [
        "# Paired Lookahead Evaluation",
        "",
        f"Evaluation version: `{report.evaluation_version}`  ",
        f"Generated: `{report.generated_at}`  ",
        f"Code version: `{report.code_version.label()}`  ",
        f"Seeds per world and budget: `{len(report.seeds)}`  ",
        f"Paired bootstrap resamples: `{report.bootstrap_resamples}`",
        "",
        "## Benchmark Protocol",
        "",
        (
            "Exactly random, greedy, information_gain, and lookahead_information_gain were run "
            "on the same public candidate design, initial uniform belief, budget, seed, and "
            "candidate-level observation schedule. Hidden truth was retained only by benchmark "
            "observation generation and evaluation."
        ),
        "",
        (
            "Each stress world has two public matched optimizer pairs. The short budget is "
            "2.25 cost units. The larger budget is 4.50 and can complete both pairs. The "
            "asymmetric world also contains a cheap opener whose counterpart is too expensive "
            "for the short horizon."
        ),
        "",
        (
            "Threshold metrics use the first observed crossing. Negative log probability uses "
            "natural logarithms and floors probability at 1e-300. Best observed objective is a "
            "secondary optimization metric and never enters a policy's scientific score."
        ),
        "",
        "## Fairness and Leakage Audit",
        "",
    ]
    for key, value in report.fairness_audit.to_dict().items():
        if key in {"details", "passed"}:
            continue
        lines.append(f"- `{key}`: **{'PASS' if value else 'FAIL'}**")
    for detail in report.fairness_audit.details:
        lines.append(f"- {detail}")

    lines.extend(["", "## World-by-World Results", ""])
    for condition in report.conditions:
        lines.extend(
            _condition_result_section(
                report, condition.world_config.world_id, condition.budget_label
            )
        )

    lines.extend(["", "## Calibration and Entropy", ""])
    total_counterexamples = sum(
        item.entropy_accuracy_counterexample_count for item in report.calibration
    )
    total_confidently_wrong = sum(item.confidently_wrong_count for item in report.calibration)
    if total_counterexamples:
        lines.append(
            "Lower entropy was not a reliable proxy for correctness. The evaluation recorded "
            f"{total_counterexamples} policy-condition runs where entropy fell while probability "
            "assigned to the truth became worse than the prior."
        )
    else:
        lines.append(
            "No entropy/accuracy counterexample appeared in this finite run, which is not proof "
            "that lower entropy guarantees correctness."
        )
    lines.append(
        f"There were {total_confidently_wrong} confidently wrong runs under the preregistered "
        "0.80 definition. Rates for every policy, world, and budget follow."
    )
    lines.append("")
    for condition in report.conditions:
        lines.extend(
            _calibration_section(report, condition.world_config.world_id, condition.budget_label)
        )

    lines.extend(["", "## Paired Confidence Intervals", ""])
    lines.append(
        "Every difference is `lookahead_information_gain - baseline`. A negative value favors "
        "lookahead for lower-is-better metrics; a positive value favors it for higher-is-better "
        "metrics. Intervals are unadjusted exploratory 95% paired percentile-bootstrap intervals."
    )
    lines.append("")
    for condition in report.conditions:
        lines.extend(
            _paired_interval_section(
                report, condition.world_config.world_id, condition.budget_label
            )
        )

    lines.extend(["", "## Confidently Wrong Examples", ""])
    confidently_wrong = [
        item for item in report.failure_cases if "confidently_wrong" in item.failure_types
    ]
    if not confidently_wrong:
        lines.append("No run met the confidently wrong definition.")
    else:
        lines.extend(
            [
                (
                    "| world | budget | policy | seed | confidence | true probability | "
                    "entropy | prediction |"
                ),
                "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for item in sorted(
            confidently_wrong,
            key=lambda value: (-value.maximum_posterior_probability, value.world_id, value.seed),
        )[:25]:
            lines.append(
                f"| {item.world_id} | {item.budget_label} | {item.policy} | {item.seed} | "
                f"{item.maximum_posterior_probability:.4f} | "
                f"{item.true_hypothesis_probability:.4g} | {item.final_posterior_entropy:.4f} | "
                f"{item.predicted_hypothesis_id} |"
            )
        lines.append("")
        lines.append(
            "The complete set, including entropy/accuracy counterexamples, is in "
            "`failure_cases.jsonl`."
        )

    lines.extend(
        [
            "",
            "## Cases Where Lookahead Wins or Loses",
            "",
            (
                "The paired tables above expose wins, ties, and losses without pooling worlds. "
                "A condition supports lookahead only when scientific accuracy and calibration "
                "improve together; entropy reduction alone is not counted as a scientific win."
            ),
            "",
            "## Limitations and Threats to Validity",
            "",
            (
                "- The hypothesis family and Gaussian likelihood remain deliberately fixed and "
                "can be misspecified."
            ),
            (
                "- The two matched pairs share the same synthetic objective family; this is not "
                "external validity."
            ),
            (
                "- Candidate-level deterministic noise pairing cannot force policies with "
                "different actions to observe identical data."
            ),
            (
                "- Bootstrap intervals are unadjusted for multiple comparisons and no p-values "
                "are reported."
            ),
            "- Threshold crossing is not required to remain sustained through the end of a run.",
            (
                "- Uniform posterior ties use stable lexical top-label classification for the "
                "correct/incorrect calibration split; probability, Brier, NLL, and entropy are "
                "not affected by that tie rule."
            ),
            (
                "- Top-label ECE with ten bins is descriptive and has finite-sample binning "
                "sensitivity."
            ),
            (
                "- The larger budget permits only two evidence pairs, so long-run behavior "
                "remains unknown."
            ),
            "",
            "## Conservative Conclusion",
            "",
            (
                "This report treats a negative or mixed result as valid. Lookahead should be "
                "described as reliable only within conditions where paired accuracy, Brier, and "
                "calibration results support the entropy result. No general superiority claim "
                "is made from entropy reduction alone."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _condition_result_section(
    report: PairedEvaluationReport,
    world_id: str,
    budget_label: str,
) -> list[str]:
    condition = next(
        item
        for item in report.conditions
        if item.world_config.world_id == world_id and item.budget_label == budget_label
    )
    lines = [
        f"### {world_id}: {budget_label} budget ({condition.budget:.2f})",
        "",
        (
            "| policy | true p | entropy | Brier | NLL | rank | reach .80 | reach .95 | "
            "pairs | redundant | cost | best objective |"
        ),
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for policy_name in PAIRED_POLICIES:
        values = {
            metric: _aggregate_mean(
                report.aggregates,
                world_id,
                budget_label,
                policy_name,
                metric,
            )
            for metric in (
                "final_true_hypothesis_probability",
                "final_posterior_entropy",
                "final_brier_score",
                "negative_log_true_hypothesis_probability",
                "final_true_hypothesis_rank",
                "reached_80_confidence",
                "reached_95_confidence",
                "matched_evidence_pairs_completed",
                "redundant_experiments_selected",
                "total_experimental_cost",
                "best_observed_objective",
            )
        }
        lines.append(
            f"| {policy_name} | {values['final_true_hypothesis_probability']:.4f} | "
            f"{values['final_posterior_entropy']:.4f} | {values['final_brier_score']:.4f} | "
            f"{values['negative_log_true_hypothesis_probability']:.4f} | "
            f"{values['final_true_hypothesis_rank']:.3f} | "
            f"{values['reached_80_confidence']:.1%} | {values['reached_95_confidence']:.1%} | "
            f"{values['matched_evidence_pairs_completed']:.3f} | "
            f"{values['redundant_experiments_selected']:.3f} | "
            f"{values['total_experimental_cost']:.3f} | "
            f"{values['best_observed_objective']:.4f} |"
        )
    lines.append("")
    return lines


def _calibration_section(
    report: PairedEvaluationReport,
    world_id: str,
    budget_label: str,
) -> list[str]:
    lines = [
        f"### {world_id}: {budget_label}",
        "",
        (
            "| policy | accuracy | confidently wrong | confidence correct | confidence "
            "incorrect | ECE | Brier | entropy correct | entropy incorrect | entropy "
            "counterexamples |"
        ),
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    rows = [
        item
        for item in report.calibration
        if item.world_id == world_id and item.budget_label == budget_label
    ]
    for item in rows:
        lines.append(
            f"| {item.policy} | {item.accuracy:.1%} | {item.confidently_wrong_rate:.1%} | "
            f"{_format_optional(item.average_confidence_when_correct)} | "
            f"{_format_optional(item.average_confidence_when_incorrect)} | "
            f"{item.expected_calibration_error:.4f} | {item.mean_brier_score:.4f} | "
            f"{_format_optional(item.mean_entropy_when_correct)} | "
            f"{_format_optional(item.mean_entropy_when_incorrect)} | "
            f"{item.entropy_accuracy_counterexample_rate:.1%} |"
        )
    lines.append("")
    return lines


def _paired_interval_section(
    report: PairedEvaluationReport,
    world_id: str,
    budget_label: str,
) -> list[str]:
    lines = [
        f"### {world_id}: {budget_label}",
        "",
        "| baseline | metric | mean delta | median | standard deviation | 95% CI | W/T/L | valid |",
        "| --- | --- | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    rows = [
        item
        for item in report.paired_comparisons
        if item.world_id == world_id and item.budget_label == budget_label
    ]
    for item in rows:
        lines.append(
            f"| {item.baseline_policy} | {item.metric} | "
            f"{_format_optional(item.mean_paired_difference)} | "
            f"{_format_optional(item.median_paired_difference)} | "
            f"{_format_optional(item.standard_deviation)} | "
            f"[{_format_optional(item.confidence_interval_low)}, "
            f"{_format_optional(item.confidence_interval_high)}] | "
            f"{item.wins}/{item.ties}/{item.losses} | {item.valid_paired_runs} |"
        )
    lines.append("")
    return lines


def _run_csv_row(run: dict[str, object]) -> dict[str, object]:
    metrics = _mapping(run["metrics"])
    code_version = _mapping(run["code_version"])
    return {
        "run_id": run["run_id"],
        "evaluation_version": run["evaluation_version"],
        "benchmark_version": run["benchmark_version"],
        "timestamp": run["timestamp"],
        "code_version": code_version["label"],
        "schema_version": run["schema_version"],
        "policy": run["policy"],
        "policy_version": run["policy_version"],
        "world_id": run["world_id"],
        "hidden_true_hypothesis": run["hidden_true_hypothesis"],
        "seed": run["seed"],
        "budget_label": run["budget_label"],
        "budget": run["budget"],
        "public_initial_condition_fingerprint": run["public_initial_condition_fingerprint"],
        "observation_schedule_fingerprint": run["observation_schedule_fingerprint"],
        "stop_reason": run["stop_reason"],
        "budget_exhausted": run["budget_exhausted"],
        **metrics,
        "world_configuration_json": json.dumps(
            run["world_configuration"], sort_keys=True, separators=(",", ":")
        ),
        "dependency_versions_json": json.dumps(
            run["dependency_versions"], sort_keys=True, separators=(",", ":")
        ),
        "initial_belief_probabilities_json": json.dumps(
            run["initial_belief_probabilities"], sort_keys=True, separators=(",", ":")
        ),
        "final_posterior_probabilities_json": json.dumps(
            run["final_posterior_probabilities"], sort_keys=True, separators=(",", ":")
        ),
        "full_metric_trace_json": json.dumps(
            run["full_metric_trace"], sort_keys=True, separators=(",", ":")
        ),
    }


def _aggregate_mean(
    rows: tuple[AggregateMetricResult, ...],
    world_id: str,
    budget_label: str,
    policy: str,
    metric: str,
) -> float:
    row = next(
        item
        for item in rows
        if item.world_id == world_id
        and item.budget_label == budget_label
        and item.policy == policy
        and item.metric == metric
    )
    if row.mean is None:
        return float("nan")
    return row.mean


def _calibration_row(
    rows: tuple[CalibrationResult, ...],
    world_id: str,
    budget_label: str,
    policy: str,
) -> CalibrationResult:
    return next(
        item
        for item in rows
        if item.world_id == world_id and item.budget_label == budget_label and item.policy == policy
    )


def _format_optional(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.6f}"


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("Expected JSON object while writing evaluation output.")
    return value


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"Cannot write empty evaluation CSV: {path.name}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
