"""Artifact and terminal reporting for the robust belief evaluation."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import sqlite3
import statistics
from pathlib import Path
from typing import Any, cast

from research_decision_engine import __version__
from research_decision_engine.belief_models import (
    ADEQUACY_DIAGNOSTIC_VERSION,
    CALIBRATED_SIGMA_MODEL_ID,
    FIXED_SIGMA,
    FIXED_SIGMA_MODEL_ID,
    MINIMUM_PRIOR_EFFECTS,
    SIGMA_ESTIMATOR_VERSION,
    SIGMA_FLOOR,
    VARIANCE_FLOOR,
    belief_models,
)
from research_decision_engine.benchmarks.evaluation import POLICY_VERSIONS
from research_decision_engine.benchmarks.robust_evaluation import (
    RobustEvaluationResult,
    RobustEvaluationRun,
    acceptance_gate_results,
    aggregate_metric_rows,
    calibration_rows,
    paired_comparison_rows,
)
from research_decision_engine.benchmarks.worlds import paired_evaluation_worlds
from research_decision_engine.calibration import (
    CALIBRATION_EFFECT_COUNT,
    CALIBRATION_PREFIX_VERSION,
    CALIBRATION_REPLICATION_VERSION,
)
from research_decision_engine.storage import SCHEMA_VERSION

OUTPUT_FILENAMES = (
    "run_manifest.json",
    "per_run_results.jsonl",
    "per_run_results.csv",
    "aggregate_results.csv",
    "paired_belief_model_comparisons.csv",
    "calibration_results.csv",
    "adequacy_diagnostics.csv",
    "confidently_wrong_cases.jsonl",
    "cost_accounting.csv",
    "ACCEPTANCE_GATES.json",
    "ROBUST_BELIEF_EVALUATION_REPORT.md",
)


def write_robust_belief_outputs(
    result: RobustEvaluationResult,
    output_directory: Path,
) -> dict[str, Path]:
    """Write the complete frozen machine- and human-readable artifact set."""

    output_directory.mkdir(parents=True, exist_ok=True)
    existing = [name for name in OUTPUT_FILENAMES if (output_directory / name).exists()]
    if existing:
        raise FileExistsError(
            "Refusing to overwrite robust evaluation artifacts: " + ", ".join(existing)
        )
    paths = {name: output_directory / name for name in OUTPUT_FILENAMES}
    aggregates = aggregate_metric_rows(result.runs)
    paired = paired_comparison_rows(
        result.runs,
        bootstrap_resamples=result.bootstrap_resamples,
    )
    calibration = calibration_rows(result.runs)
    gates = acceptance_gate_results(result.runs, paired, result.audits)

    _write_jsonl(paths["per_run_results.jsonl"], (item.to_dict() for item in result.runs))
    _write_csv(paths["per_run_results.csv"], _per_run_rows(result.runs))
    _write_csv(paths["aggregate_results.csv"], aggregates)
    _write_csv(paths["paired_belief_model_comparisons.csv"], paired)
    _write_csv(paths["calibration_results.csv"], calibration)
    _write_csv(paths["adequacy_diagnostics.csv"], _diagnostic_rows(result.runs))
    _write_jsonl(
        paths["confidently_wrong_cases.jsonl"],
        (_confidently_wrong_case(item) for item in result.runs if item.metrics.confidently_wrong),
    )
    _write_csv(paths["cost_accounting.csv"], _cost_rows(result))
    _write_json(paths["ACCEPTANCE_GATES.json"], gates)
    paths["ROBUST_BELIEF_EVALUATION_REPORT.md"].write_text(
        render_robust_evaluation_report(
            result,
            calibration=calibration,
            paired=paired,
            gates=gates,
        ),
        encoding="utf-8",
    )

    hashes = {name: _sha256(path) for name, path in paths.items() if name != "run_manifest.json"}
    manifest = _manifest(result, output_hashes=hashes)
    _write_json(paths["run_manifest.json"], manifest)
    return paths


def render_robust_terminal_summary(
    result: RobustEvaluationResult,
    paths: dict[str, Path],
) -> str:
    gates = json.loads(paths["ACCEPTANCE_GATES.json"].read_text(encoding="utf-8"))
    lines = [
        "Robust belief evaluation complete",
        f"runs: {len(result.runs)} ({len(result.runs) // 2} paired decision streams)",
        f"calibration prefixes: {len(result.prefixes)}",
        f"all hard audits passed: {gates['all_hard_audits_passed']}",
        f"calibrated model accepted: {gates['calibrated_model_accepted']}",
        f"default belief model: {gates['default_belief_model']}",
        "performance gates:",
    ]
    for gate in _performance_gates(gates):
        lines.append(
            f"  {gate['gate_id']}: {'PASS' if gate['passed'] else 'FAIL'} "
            f"(delta={gate['point_estimate']:.6f}, "
            f"95% CI [{gate['paired_95_ci_low']:.6f}, {gate['paired_95_ci_high']:.6f}])"
        )
    lines.append(f"artifacts: {paths['run_manifest.json'].parent}")
    return "\n".join(lines)


def render_robust_evaluation_report(
    result: RobustEvaluationResult,
    *,
    calibration: tuple[dict[str, object], ...],
    paired: tuple[dict[str, object], ...],
    gates: dict[str, object],
) -> str:
    """Render an evidence-led report without claiming success in advance."""

    lines = [
        "# Robust Belief Evaluation Report",
        "",
        f"Evaluation version: `{result.evaluation_version}`  ",
        f"Generated: `{result.generated_at}`  ",
        f"Paired decision streams: `{len(result.runs) // 2}`  ",
        f"Belief-model runs: `{len(result.runs)}`  ",
        f"Paired seeds: `{len(result.seeds)}`",
        "",
        "## Protocol",
        "",
        "Each existing policy ran once under the unchanged fixed-sigma controller. The same "
        "real experiment and matched-evidence stream was replayed through two isolated belief "
        "lineages. The calibrated lineage was shadow-only and could not change selection. Truth "
        "was supplied only to evaluator scoring after both replays completed.",
        "",
        f"The baseline used `sigma = {FIXED_SIGMA}`. The calibrated model used the ordinary "
        f"sample standard deviation (`ddof = 1`) of at least {MINIMUM_PRIOR_EFFECTS} strictly "
        f"prior matched effects and applied `sigma_floor = {SIGMA_FLOOR}`. Calibration cost was "
        "reported separately and did not consume the frozen decision budgets.",
        "",
        "## Acceptance Gates",
        "",
        "| Gate | Delta (calibrated - fixed) | Paired 95% CI | Result |",
        "|---|---:|---:|---|",
    ]
    for gate in _performance_gates(gates):
        lines.append(
            f"| {gate['gate_id']} | {gate['point_estimate']:.6f} | "
            f"[{gate['paired_95_ci_low']:.6f}, {gate['paired_95_ci_high']:.6f}] | "
            f"{'PASS' if gate['passed'] else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            f"All hard audits passed: **{gates['all_hard_audits_passed']}**.  ",
            f"Calibrated model accepted: **{gates['calibrated_model_accepted']}**.  ",
            f"Default belief model: **`{gates['default_belief_model']}`**.",
            "",
            "## World And Budget Results",
            "",
            "Means below pool the four policies equally because each policy cell has the same "
            "seed count. ECE is top-label calibration error with ten equal-width bins.",
            "",
            (
                "| World | Budget | Model | True p | NLL | Brier | Confidently wrong | "
                "ECE | Entropy | Decision cost | Calibration cost | Total cost |"
            ),
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for world in paired_evaluation_worlds():
        for budget_label in ("short", "large"):
            for model_id in (FIXED_SIGMA_MODEL_ID, CALIBRATED_SIGMA_MODEL_ID):
                group = tuple(
                    item
                    for item in result.runs
                    if item.world_id == world.world_id
                    and item.budget_label == budget_label
                    and item.belief_model_id == model_id
                )
                ece = top_label_ece_for_runs(group)
                lines.append(
                    f"| {world.world_id} | {budget_label} | {model_id} | "
                    f"{_mean(group, 'final_true_hypothesis_probability'):.4f} | "
                    f"{_mean(group, 'negative_log_true_hypothesis_probability'):.4f} | "
                    f"{_mean(group, 'final_brier_score'):.4f} | "
                    f"{_mean(group, 'confidently_wrong'):.4f} | {ece:.4f} | "
                    f"{_mean(group, 'final_posterior_entropy'):.4f} | "
                    f"{_mean(group, 'decision_cost'):.2f} | "
                    f"{_mean(group, 'calibration_cost'):.2f} | "
                    f"{_mean(group, 'total_cost'):.2f} |"
                )
    lines.extend(
        [
            "",
            "## Diagnostics And Costs",
            "",
            _diagnostic_summary(result.runs),
            "",
            _cost_summary(result),
            "",
            "Lower entropy is treated as descriptive, not as correctness. Best observed objective "
            "and experiment trajectories are identical between models within each paired stream; "
            "only the scientific belief revision differs.",
            "",
            "## Negative Results And Limitations",
            "",
            _negative_result_summary(gates),
            "",
            "The estimate uses only five prefix effects at the first decision update, remains "
            "Gaussian, assumes one sigma per public comparison group, and is evaluated as a shadow "
            "lineage. This study therefore does not measure the closed-loop effect of calibrated "
            "beliefs on future experiment selection or establish validity outside the synthetic "
            "worlds.",
            "",
            "## Next Milestone",
            "",
            _next_milestone(gates),
            "",
        ]
    )
    return "\n".join(lines)


def top_label_ece_for_runs(runs: tuple[RobustEvaluationRun, ...]) -> float:
    from research_decision_engine.benchmarks.paired_evaluation import (
        top_label_expected_calibration_error,
    )

    return top_label_expected_calibration_error(
        tuple(
            (item.metrics.maximum_posterior_probability, item.metrics.prediction_correct)
            for item in runs
        )
    )


def _manifest(
    result: RobustEvaluationResult,
    *,
    output_hashes: dict[str, str],
) -> dict[str, object]:
    return {
        "evaluation_version": result.evaluation_version,
        "generated_at": result.generated_at,
        "benchmark_worlds": [item.to_dict() for item in paired_evaluation_worlds()],
        "hidden_truth_access": "evaluator-only after both lineage replays",
        "belief_models": [
            {"belief_model_id": item.model_id, "belief_model_version": item.model_version}
            for item in belief_models()
        ],
        "policies": [
            {"policy": policy, "policy_version": POLICY_VERSIONS[policy]}
            for policy in POLICY_VERSIONS
        ],
        "seeds": list(result.seeds),
        "budgets": dict(result.budgets),
        "bootstrap": {
            "resamples": result.bootstrap_resamples,
            "method": "deterministic paired percentile bootstrap with seed blocks",
            "confidence_level": 0.95,
        },
        "calibration_protocol": {
            "prefix_version": CALIBRATION_PREFIX_VERSION,
            "replication_version": CALIBRATION_REPLICATION_VERSION,
            "effects_per_public_comparison_group": CALIBRATION_EFFECT_COUNT,
            "prefix_scope": ["world_id", "evaluation_seed", "comparison_group_id"],
            "belief_updates_from_calibration": 0,
            "prefixes": [_prefix_manifest(item) for item in result.prefixes],
        },
        "belief_protocol": {
            "fixed_sigma": FIXED_SIGMA,
            "minimum_prior_effects": MINIMUM_PRIOR_EFFECTS,
            "sigma_floor": SIGMA_FLOOR,
            "variance_floor": VARIANCE_FLOOR,
            "estimator_version": SIGMA_ESTIMATOR_VERSION,
            "diagnostic_version": ADEQUACY_DIAGNOSTIC_VERSION,
        },
        "dependency_versions": {
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "research_decision_engine": __version__,
        },
        "schema_version": SCHEMA_VERSION,
        "run_count": len(result.runs),
        "paired_stream_count": len(result.runs) // 2,
        "audits": result.audits.to_dict(),
        "source_tree_sha256": _source_tree_hash(),
        "output_sha256": output_hashes,
    }


def _prefix_manifest(prefix: Any) -> dict[str, object]:
    return {
        "prefix_id": prefix.prefix_id,
        "world_id": prefix.world_id,
        "evaluation_seed": prefix.evaluation_seed,
        "calibration_cost": prefix.calibration_cost,
        "group_count": len(prefix.groups),
        "groups": [
            {
                "calibration_group_id": group.calibration_group_id,
                "comparison_group_id": group.comparison_group_id,
                "effect_ids": [
                    effect.calibration_effect_id
                    for effect in prefix.matched_effects
                    if effect.calibration_group_id == group.calibration_group_id
                ],
                "replication_seeds": [
                    effect.replication_seed
                    for effect in prefix.matched_effects
                    if effect.calibration_group_id == group.calibration_group_id
                ],
                "observed_matched_effects": [
                    effect.observed_effect
                    for effect in prefix.matched_effects
                    if effect.calibration_group_id == group.calibration_group_id
                ],
            }
            for group in prefix.groups
        ],
        "provenance": prefix.provenance.to_dict(),
    }


def _per_run_rows(runs: tuple[RobustEvaluationRun, ...]) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "run_id": item.run_id,
            "paired_stream_id": item.paired_stream_id,
            "belief_model_id": item.belief_model_id,
            "belief_model_version": item.belief_model_version,
            "lineage_id": item.lineage_id,
            "world_id": item.world_id,
            "policy": item.policy,
            "policy_version": item.policy_version,
            "seed": item.seed,
            "budget_label": item.budget_label,
            "budget": item.budget,
            "calibration_prefix_id": item.calibration_prefix_id,
            "observation_schedule_fingerprint": item.observation_schedule_fingerprint,
            "evidence_stream_fingerprint": item.evidence_stream_fingerprint,
            "hidden_true_hypothesis": item.hidden_true_hypothesis,
            **item.metrics.to_dict(),
            "final_posterior_probabilities": json.dumps(
                dict(item.final_posterior_probabilities), sort_keys=True
            ),
        }
        for item in runs
    )


def _diagnostic_rows(runs: tuple[RobustEvaluationRun, ...]) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    noise_by_world = {item.world_id: item.noise_level for item in paired_evaluation_worlds()}
    for run in runs:
        update_by_diagnostic = {item.diagnostic.diagnostic_id: item for item in run.model_updates}
        for diagnostic in run.diagnostics:
            update = update_by_diagnostic[diagnostic.diagnostic_id]
            interval_map = {item.probability: item for item in diagnostic.central_intervals}
            rows.append(
                {
                    "row_type": "prequential_observation",
                    "run_id": run.run_id,
                    "paired_stream_id": run.paired_stream_id,
                    "world_id": run.world_id,
                    "noise_level": noise_by_world[run.world_id],
                    "budget_label": run.budget_label,
                    "policy": run.policy,
                    "seed": run.seed,
                    "belief_model_id": run.belief_model_id,
                    "belief_model_version": run.belief_model_version,
                    "lineage_id": run.lineage_id,
                    "diagnostic_id": diagnostic.diagnostic_id,
                    "evidence_id": diagnostic.evidence_id,
                    "comparison_group_id": diagnostic.comparison_group_id,
                    "sigma_estimate_id": diagnostic.sigma_estimate_id,
                    "estimated_sigma": update.sigma_estimate.estimated_sigma,
                    "sigma_status": update.sigma_estimate.status,
                    "sigma_source_count": update.sigma_estimate.sample_count,
                    "posterior_predictive_tail_probability": (
                        diagnostic.posterior_predictive_tail_probability
                    ),
                    "standardized_residual": diagnostic.standardized_residual,
                    "predictive_log_likelihood": diagnostic.predictive_log_likelihood,
                    "residual_count": diagnostic.residual_count,
                    "rolling_residual_outlier_count": (diagnostic.rolling_residual_outlier_count),
                    "tail_alarm": diagnostic.tail_alarm,
                    "residual_outlier": diagnostic.residual_outlier,
                    "repeated_residual_alarm": diagnostic.repeated_residual_alarm,
                    "diagnostics_disagree": diagnostic.diagnostics_disagree,
                    "coverage_50": interval_map[0.50].contains_observation,
                    "coverage_80": interval_map[0.80].contains_observation,
                    "coverage_95": interval_map[0.95].contains_observation,
                    "adequacy_state": diagnostic.adequacy_state,
                    "diagnostic_version": diagnostic.diagnostic_version,
                    "provenance": json.dumps(diagnostic.provenance.to_dict(), sort_keys=True),
                }
            )
    summary_keys = sorted(
        {
            (
                run.belief_model_id,
                run.world_id,
                run.budget_label,
                run.policy,
                diagnostic.comparison_group_id,
            )
            for run in runs
            for diagnostic in run.diagnostics
        }
    )
    for model_id, world_id, budget_label, policy, comparison_group_id in summary_keys:
        diagnostics = tuple(
            diagnostic
            for run in runs
            if run.belief_model_id == model_id
            and run.world_id == world_id
            and run.budget_label == budget_label
            and run.policy == policy
            for diagnostic in run.diagnostics
            if diagnostic.comparison_group_id == comparison_group_id
        )
        summary: dict[str, object] = {
            "row_type": "coverage_summary",
            "run_id": "",
            "paired_stream_id": "",
            "world_id": world_id,
            "noise_level": noise_by_world[world_id],
            "budget_label": budget_label,
            "policy": policy,
            "seed": "",
            "belief_model_id": model_id,
            "belief_model_version": diagnostics[0].belief_model_version,
            "lineage_id": "",
            "diagnostic_id": "",
            "evidence_id": "",
            "comparison_group_id": comparison_group_id,
            "coverage_sample_count": len(diagnostics),
            "diagnostic_version": diagnostics[0].diagnostic_version,
        }
        for probability in (0.50, 0.80, 0.95):
            successes = sum(
                interval.contains_observation
                for diagnostic in diagnostics
                for interval in diagnostic.central_intervals
                if interval.probability == probability
            )
            rate = successes / len(diagnostics)
            low, high = _wilson_interval(successes, len(diagnostics))
            suffix = str(int(probability * 100))
            summary[f"coverage_{suffix}"] = rate
            summary[f"coverage_{suffix}_wilson_95_ci_low"] = low
            summary[f"coverage_{suffix}_wilson_95_ci_high"] = high
        rows.append(summary)
    return tuple(rows)


def _wilson_interval(successes: int, total: int) -> tuple[float, float]:
    if total <= 0 or not 0 <= successes <= total:
        raise ValueError("Wilson interval requires 0 <= successes <= total and total > 0.")
    z = 1.96
    proportion = successes / total
    denominator = 1.0 + z**2 / total
    center = (proportion + z**2 / (2.0 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1.0 - proportion) / total + z**2 / (4.0 * total**2))
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def _confidently_wrong_case(run: RobustEvaluationRun) -> dict[str, object]:
    return {
        "run_id": run.run_id,
        "paired_stream_id": run.paired_stream_id,
        "world_id": run.world_id,
        "budget_label": run.budget_label,
        "policy": run.policy,
        "seed": run.seed,
        "belief_model_id": run.belief_model_id,
        "true_hypothesis_id": run.hidden_true_hypothesis,
        "predicted_hypothesis_id": run.metrics.predicted_hypothesis_id,
        "maximum_posterior_probability": run.metrics.maximum_posterior_probability,
        "true_hypothesis_probability": run.metrics.final_true_hypothesis_probability,
        "negative_log_true_hypothesis_probability": (
            run.metrics.negative_log_true_hypothesis_probability
        ),
        "brier_score": run.metrics.final_brier_score,
        "posterior_probabilities": dict(run.final_posterior_probabilities),
        "selected_candidate_ids": [item.candidate_id for item in run.trace],
        "sigma_estimate_ids": list(run.sigma_estimate_ids),
    }


def _cost_rows(result: RobustEvaluationResult) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for run in result.runs:
        rows.append(
            {
                "row_type": "attributed_run_cost",
                "run_id": run.run_id,
                "calibration_prefix_id": run.calibration_prefix_id,
                "belief_model_id": run.belief_model_id,
                "world_id": run.world_id,
                "budget_label": run.budget_label,
                "policy": run.policy,
                "seed": run.seed,
                "decision_cost": run.metrics.decision_cost,
                "calibration_cost": run.metrics.calibration_cost,
                "total_cost": run.metrics.total_cost,
                "fixed_model_required_cost": run.metrics.fixed_model_required_cost,
                "calibrated_model_required_cost": (run.metrics.calibrated_model_required_cost),
            }
        )
    for prefix in result.prefixes:
        rows.append(
            {
                "row_type": "physical_calibration_prefix_cost",
                "run_id": "",
                "calibration_prefix_id": prefix.prefix_id,
                "belief_model_id": CALIBRATED_SIGMA_MODEL_ID,
                "world_id": prefix.world_id,
                "budget_label": "shared",
                "policy": "shared",
                "seed": prefix.evaluation_seed,
                "decision_cost": 0.0,
                "calibration_cost": prefix.calibration_cost,
                "total_cost": prefix.calibration_cost,
                "fixed_model_required_cost": 0.0,
                "calibrated_model_required_cost": prefix.calibration_cost,
            }
        )
    return tuple(rows)


def _mean(runs: tuple[RobustEvaluationRun, ...], metric: str) -> float:
    values = tuple(
        value for run in runs if (value := run.metrics.numeric_values()[metric]) is not None
    )
    return statistics.fmean(values)


def _diagnostic_summary(runs: tuple[RobustEvaluationRun, ...]) -> str:
    parts = []
    for model_id in (FIXED_SIGMA_MODEL_ID, CALIBRATED_SIGMA_MODEL_ID):
        diagnostics = tuple(
            diagnostic
            for run in runs
            if run.belief_model_id == model_id
            for diagnostic in run.diagnostics
        )
        counts = {
            state: sum(item.adequacy_state == state for item in diagnostics)
            for state in ("adequate", "uncertain", "appears_misspecified")
        }
        parts.append(
            f"`{model_id}` produced {len(diagnostics)} prequential diagnostics: "
            f"adequate={counts['adequate']}, uncertain={counts['uncertain']}, "
            f"appears_misspecified={counts['appears_misspecified']}."
        )
    return " ".join(parts)


def _cost_summary(result: RobustEvaluationResult) -> str:
    physical_calibration_cost = math.fsum(item.calibration_cost for item in result.prefixes)
    decision_streams: dict[str, RobustEvaluationRun] = {}
    for run in result.runs:
        decision_streams.setdefault(run.paired_stream_id, run)
    physical_decision_cost = math.fsum(
        item.metrics.decision_cost for item in decision_streams.values()
    )
    return (
        f"Across the suite, deduplicated physical calibration cost was "
        f"`{physical_calibration_cost:.2f}` and physical decision cost was "
        f"`{physical_decision_cost:.2f}`. Per-run deployment costs remain in "
        "`cost_accounting.csv`; calibration cost is never charged against the decision budget."
    )


def _negative_result_summary(gates: dict[str, object]) -> str:
    failed = [item["gate_id"] for item in _performance_gates(gates) if not item["passed"]]
    if failed:
        return (
            "The calibrated model failed these predeclared gates: "
            + ", ".join(f"`{item}`" for item in failed)
            + ". It therefore remains unaccepted regardless of favorable secondary metrics."
        )
    return (
        "No predeclared performance gate failed. This is evidence for the narrow calibrated "
        "likelihood under the frozen shadow protocol, not proof of general robustness."
    )


def _next_milestone(gates: dict[str, object]) -> str:
    if gates["calibrated_model_accepted"]:
        return (
            "Run one predeclared closed-loop evaluation in which the accepted calibrated lineage "
            "drives the existing information-gain policies, while preserving paired observations "
            "and all current policy algorithms."
        )
    return (
        "Run one predeclared replication-sufficiency evaluation that varies only the number of "
        "calibration matched effects and measures which failed acceptance gate, if any, is stable "
        "under the added calibration cost."
    )


def _performance_gates(gates: dict[str, object]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], gates["performance_gates"])


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Any) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _write_csv(path: Path, rows: tuple[dict[str, object], ...]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        if not fieldnames:
            handle.write("")
            return
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


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
