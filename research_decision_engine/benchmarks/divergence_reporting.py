"""Artifact and report writer for the frozen divergence-mechanism audit."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import shutil
import sqlite3
import statistics
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from research_decision_engine import __version__
from research_decision_engine.benchmarks.divergence_audit import (
    AUDIT_SCHEMA_VERSION,
    AUDIT_VERSION,
    BOOTSTRAP_MASTER_SEED,
    CLASSIFICATION_RULE_VERSION,
    DOMINANCE_PREVALENCE,
    EXPECTED_DIVERGENCE_COUNT,
    FROZEN_OUTPUT_FILENAMES,
    MECHANISMS,
    NUMERICAL_TOLERANCE,
    SCORING_ADAPTER_VERSION,
    AuditedDivergenceCase,
    DivergenceAuditError,
    DivergenceAuditResult,
    JsonObject,
)


def write_divergence_outputs(
    result: DivergenceAuditResult, output_directory: Path
) -> dict[str, Path]:
    """Write exactly the ten frozen outputs without replacing prior artifacts."""

    if output_directory.exists():
        raise FileExistsError(f"Refusing to overwrite divergence audit: {output_directory}")
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{output_directory.name}-tmp-",
            dir=output_directory.parent,
        )
    )
    try:
        paths = {name: temporary / name for name in FROZEN_OUTPUT_FILENAMES}
        _write_jsonl(paths["divergence_cases.jsonl"], (item.to_dict() for item in result.cases))
        _write_csv(paths["divergence_cases.csv"], _case_rows(result.cases))
        _write_csv(paths["mechanism_summary.csv"], result.mechanism_summary_rows)
        _write_csv(paths["mechanism_by_condition.csv"], result.mechanism_condition_rows)
        _write_csv(paths["score_decomposition.csv"], result.score_rows)
        _write_csv(paths["sequence_comparison.csv"], result.sequence_rows)
        _write_csv(paths["harm_concentration.csv"], result.harm_rows)
        _write_json(paths["planner_compatibility_audit.json"], result.compatibility)
        paths["DIVERGENCE_AUDIT_REPORT.md"].write_text(
            render_divergence_report(result), encoding="utf-8"
        )
        output_hashes = {
            name: _sha256(path)
            for name, path in paths.items()
            if name != "divergence_manifest.json"
        }
        _validate_pre_manifest(result, paths, output_hashes)
        manifest = _manifest(result, output_hashes)
        _write_json(paths["divergence_manifest.json"], manifest)
        _validate_complete_output(result, paths, output_hashes)
        temporary.replace(output_directory)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {name: output_directory / name for name in FROZEN_OUTPUT_FILENAMES}


def _manifest(result: DivergenceAuditResult, output_hashes: Mapping[str, str]) -> JsonObject:
    labels = Counter(item.evaluator_only.outcome_label for item in result.cases)
    primary = Counter(item.truth_free.classification.primary_mechanism for item in result.cases)
    all_checks_passed = bool(result.audit_checks.get("all_prewrite_acceptance_checks_passed"))
    return {
        "audit_version": AUDIT_VERSION,
        "output_schema_version": AUDIT_SCHEMA_VERSION,
        "classification_rule_version": CLASSIFICATION_RULE_VERSION,
        "scoring_adapter_version": SCORING_ADAPTER_VERSION,
        "input_evaluation_version": "closed-loop-belief-control-evaluation/v1",
        "input_directory": str(result.input_directory),
        "generated_at": result.generated_at,
        "case_count": len(result.cases),
        "expected_case_count": EXPECTED_DIVERGENCE_COUNT,
        "outcome_label_counts": dict(sorted(labels.items())),
        "primary_mechanism_counts": dict(sorted(primary.items())),
        "bootstrap": {
            "method": "paired-seed-block-percentile-bootstrap",
            "resamples": result.bootstrap_resamples,
            "master_seed": BOOTSTRAP_MASTER_SEED,
            "confidence_level": 0.95,
        },
        "numerical_tolerance": NUMERICAL_TOLERANCE,
        "dominance_prevalence_threshold": DOMINANCE_PREVALENCE,
        "truth_free_staging_sha256": result.staging_sha256,
        "extracted_truth_free_sha256": result.extracted_truth_free_sha256,
        "classification_before_evaluator_join": (
            result.staging_sha256 == result.extracted_truth_free_sha256
        ),
        "access_audit": result.access_ledger,
        "planner_compatibility_status": result.compatibility["overall_status"],
        "audit_checks": result.audit_checks,
        "audit_complete": all_checks_passed,
        "recommendation": result.recommendation,
        "source_artifact_sha256": dict(result.source_artifact_hashes),
        "design_sha256": dict(result.design_hashes),
        "output_sha256": dict(sorted(output_hashes.items())),
        "artifact_parse_and_hash_audit": True,
        "dependency_versions": {
            "python": platform.python_version(),
            "research_decision_engine": __version__,
            "sqlite": sqlite3.sqlite_version,
        },
        "verdict": "PASS" if all_checks_passed else "FAIL",
    }


def _case_rows(cases: Sequence[AuditedDivergenceCase]) -> tuple[JsonObject, ...]:
    rows = []
    for item in cases:
        case = item.truth_free
        evaluator = item.evaluator_only
        decomposition = case.decomposition
        rows.append(
            {
                "case_id": case.pair.case_id,
                "divergence_id": case.pair.divergence_id,
                "world_id": case.pair.world_id,
                "seed": case.pair.seed,
                "budget_label": case.pair.budget_label,
                "budget": case.budget,
                "policy": case.pair.policy,
                "oracle_version": case.oracle_version,
                "commitment_id": case.commitment_id,
                "fixed_run_id": case.pair.fixed_run_id,
                "calibrated_run_id": case.pair.calibrated_run_id,
                "first_divergence_step": case.pair.first_divergence_step,
                "common_prefix_length": case.pair.common_prefix_length,
                "fixed_belief_state_id": case.fixed_belief_state_id,
                "calibrated_belief_state_id": case.calibrated_belief_state_id,
                "fixed_lineage_id": case.fixed_lineage_id,
                "calibrated_lineage_id": case.calibrated_lineage_id,
                "fixed_posterior": json.dumps(dict(case.fixed_posterior), sort_keys=True),
                "calibrated_posterior": json.dumps(dict(case.calibrated_posterior), sort_keys=True),
                "fixed_selected_candidate": decomposition["fixed_candidate_id"],
                "calibrated_selected_candidate": decomposition["calibrated_candidate_id"],
                "primary_mechanism": case.classification.primary_mechanism,
                "contributing_mechanisms": json.dumps(case.classification.contributing_mechanisms),
                "classification_confidence": (case.classification.classification_confidence),
                "classification_rule_version": case.classification.rule_version,
                "compatibility_passed": case.compatibility_passed,
                "set_relation": case.sequence.set_relation,
                "jaccard_similarity": case.sequence.jaccard_similarity,
                "outcome_label": evaluator.outcome_label,
                "hidden_true_hypothesis": evaluator.hidden_true_hypothesis,
                "metric_differences": json.dumps(evaluator.metric_differences, sort_keys=True),
                "truth_free_sha256": item.truth_free_sha256,
            }
        )
    return tuple(rows)


def render_divergence_report(result: DivergenceAuditResult) -> str:
    cases = result.cases
    labels = Counter(item.evaluator_only.outcome_label for item in cases)
    compatibility_passed = result.compatibility["overall_status"] == "PASS"
    verdict = "PASS" if result.audit_checks["all_prewrite_acceptance_checks_passed"] else "FAIL"
    no_stable = [
        item.truth_free.pair.case_id
        for item in cases
        if item.truth_free.classification.primary_mechanism == "NO_STABLE_MECHANISM"
    ]
    lines = [
        "# Divergence Mechanism Audit Report",
        "",
        f"Audit version: `{AUDIT_VERSION}`  ",
        f"Generated: `{result.generated_at}`  ",
        f"Verdict: `{verdict}`",
        "",
        "## Frozen Protocol",
        "",
        (
            f"The audit classified all {len(cases)} recorded divergent fixed/calibrated pairs. "
            "No policy trajectory was rerun, no observation was generated, and the selected-only "
            "oracle and unselected potential outcomes were inaccessible."
        ),
        "",
        (
            "Classification used only recorded beliefs, group-local sigmas, public candidates, "
            "costs, budgets, eligibility, scores, planner traces, and selected experiment history. "
            "The canonical Pass-A payload was hashed before evaluator labels were opened."
        ),
        "",
        "## Population Reconciliation",
        "",
        f"- Helped: {labels.get('helped', 0)}",
        f"- Hurt: {labels.get('hurt', 0)}",
        f"- Mixed: {labels.get('mixed', 0)}",
        f"- Tied: {labels.get('tied', 0)}",
        "",
        "## Primary Mechanisms",
        "",
        "| Mechanism | All | Helped | Hurt | Mixed |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for mechanism in MECHANISMS:
        lines.append(
            "| "
            + mechanism
            + " | "
            + " | ".join(
                str(
                    sum(
                        item.truth_free.classification.primary_mechanism == mechanism
                        and (scope == "all" or item.evaluator_only.outcome_label == scope)
                        for item in cases
                    )
                )
                for scope in ("all", "helped", "hurt", "mixed")
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Helped, Hurt, And Mixed Mechanisms",
            "",
            "| Outcome | Mechanism (any role) | Count | Proportion | 95% CI |",
            "| --- | --- | ---: | ---: | --- |",
        ]
    )
    for row in result.mechanism_summary_rows:
        if (
            row["summary_kind"] == "mechanism_frequency"
            and row["role"] == "any"
            and row["scope"] in {"helped", "hurt", "mixed"}
            and cast(int, row["count"]) > 0
        ):
            lines.append(
                f"| {row['scope']} | {row['mechanism']} | {row['count']} | "
                f"{_fmt(row['proportion'])} | {_ci(row)} |"
            )
    lines.extend(
        [
            "",
            "## Harm Concentration",
            "",
            "The table is conditional on the 189 divergent pairs. Concentration is descriptive, "
            "not a causal estimate.",
            "",
            "| Dimension | Stratum | Divergent | Harmed | Harm rate | Lift | "
            "Risk difference | 95% harm-rate CI |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in result.harm_rows:
        if cast(int, row["divergent_count"]) > 0:
            harm_rate_interval = _interval(
                row.get("conditional_harm_rate_ci_low"),
                row.get("conditional_harm_rate_ci_high"),
            )
            lines.append(
                f"| {row['dimension']} | {row['stratum']} | {row['divergent_count']} | "
                f"{row['harm_count']} | {_fmt(row['conditional_harm_rate'])} | "
                f"{_fmt(row['concentration_lift'])} | {_fmt(row['risk_difference'])} | "
                f"{harm_rate_interval} |"
            )
    lines.extend(
        [
            "",
            "## Four-Context And Shapley Results",
            "",
            (
                "For the fixed winner `f` and calibrated winner `c`, each context margin is "
                "`m_XY = I2_XY(c) - I2_XY(f)`. The frozen decomposition is:"
            ),
            "",
            "```text",
            "belief = 0.5 * ((m_CF - m_FF) + (m_CC - m_FC))",
            "sigma  = 0.5 * ((m_FC - m_FF) + (m_CC - m_CF))",
            "interaction = m_CC - m_CF - m_FC + m_FF",
            "```",
            "",
            f"Tolerance: `{NUMERICAL_TOLERANCE}`.",
            "",
            "| Quantity | Mean | Median | Maximum absolute value |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for key in (
        "belief_state_contribution",
        "sigma_likelihood_contribution",
        "belief_sigma_interaction",
        "reconciliation_error",
        "temporal_reconciliation_error",
    ):
        values = [float(item.truth_free.decomposition[key]) for item in cases]
        lines.append(
            f"| {key} | {_fmt(statistics.fmean(values))} | "
            f"{_fmt(statistics.median(values))} | {_fmt(max(abs(value) for value in values))} |"
        )
    lines.extend(
        [
            "",
            "## Planner-Belief Compatibility",
            "",
            f"Overall compatibility audit: `{'PASS' if compatibility_passed else 'FAIL'}`.",
            "",
        ]
    )
    for check in cast(list[JsonObject], result.compatibility["checks"]):
        lines.append(
            f"- `{check['check_id']}`: {check['status']} "
            f"({check['checked_record_count']} records, {check['failure_count']} failures, "
            f"maximum error {_fmt(check['maximum_absolute_error'])})"
        )
    lines.extend(
        [
            "",
            "No fixed-sigma planner assumption was found in a calibrated scoring path."
            if compatibility_passed
            else (
                "At least one planner-model compatibility mismatch was found; it was not repaired."
            ),
            "",
            "## Demonstrated Results And Associations",
            "",
            (
                "Winner changes under the four frozen crossed score contexts, score compression, "
                "ranking stages, and decomposition reconciliation are directly demonstrated by "
                "read-only numerical replay."
            ),
            "",
            (
                "Pair ordering, delayed commitment, same-set reordering, and budget crowd-out are "
                "structural associations in recorded selected trajectories. They do not establish "
                "what an unselected experiment would have observed or prove a causal correction."
            ),
            "",
            "## Unresolved Cases",
            "",
            (
                "No `NO_STABLE_MECHANISM` cases remain."
                if not no_stable
                else f"`NO_STABLE_MECHANISM` cases ({len(no_stable)}): " + ", ".join(no_stable)
            ),
            "",
            "## Acceptance Checks",
            "",
        ]
    )
    for name, value in result.audit_checks.items():
        if isinstance(value, bool):
            lines.append(f"- `{name}`: {'PASS' if value else 'FAIL'}")
    lines.extend(
        [
            "",
            "## All Reported Confidence Intervals",
            "",
            (
                "Every interval below is the frozen paired seed-block percentile-bootstrap 95% "
                "interval. `undefined` means the predeclared denominator was zero or fewer than "
                "50 bootstrap replicates were usable."
            ),
            "",
            "### Mechanism And Metric Intervals",
            "",
            "| Kind | Scope | Role | Mechanism | Metric | Point | 95% CI | Usable |",
            "| --- | --- | --- | --- | --- | ---: | --- | ---: |",
        ]
    )
    for row in result.mechanism_summary_rows:
        point = row["proportion"] if row["summary_kind"] == "mechanism_frequency" else row["mean"]
        lines.append(
            f"| {row['summary_kind']} | {row['scope']} | {row['role']} | "
            f"{row['mechanism']} | {row['metric'] or ''} | {_fmt(point)} | {_ci(row)} | "
            f"{row['usable_bootstrap_replicates']} |"
        )
    lines.extend(
        [
            "",
            "### Harm-Concentration Intervals",
            "",
            "| Dimension | Stratum | Metric | Point | 95% CI | Usable |",
            "| --- | --- | --- | ---: | --- | ---: |",
        ]
    )
    for row in result.harm_rows:
        for metric in (
            "harmful_case_share",
            "conditional_harm_rate",
            "concentration_lift",
            "risk_difference",
            "risk_ratio",
        ):
            lines.append(
                f"| {row['dimension']} | {row['stratum']} | {metric} | "
                f"{_fmt(row[metric])} | "
                f"{_interval(row.get(metric + '_ci_low'), row.get(metric + '_ci_high'))} | "
                f"{row['usable_bootstrap_replicates']} |"
            )
    rule = cast(JsonObject, result.audit_checks["recommendation_rule"])
    lines.extend(
        [
            "",
            "## Exactly One Next Milestone",
            "",
            f"Recommendation: **{result.recommendation}**",
            "",
            f"Frozen decision-rule record: `{json.dumps(rule, sort_keys=True)}`",
            "",
            "The recommendation is not implemented by this milestone.",
            "",
        ]
    )
    return "\n".join(lines)


def render_divergence_terminal_summary(
    result: DivergenceAuditResult, paths: Mapping[str, Path]
) -> str:
    primary = Counter(item.truth_free.classification.primary_mechanism for item in result.cases)
    labels = Counter(item.evaluator_only.outcome_label for item in result.cases)
    return "\n".join(
        (
            f"Divergence audit: {len(result.cases)} cases",
            "Outcomes: " + ", ".join(f"{key}={value}" for key, value in sorted(labels.items())),
            "Primary mechanisms: "
            + ", ".join(f"{key}={value}" for key, value in sorted(primary.items())),
            f"Planner compatibility: {result.compatibility['overall_status']}",
            f"Recommendation: {result.recommendation}",
            f"Report: {paths['DIVERGENCE_AUDIT_REPORT.md']}",
        )
    )


def _validate_pre_manifest(
    result: DivergenceAuditResult,
    paths: Mapping[str, Path],
    output_hashes: Mapping[str, str],
) -> None:
    if _jsonl_count(paths["divergence_cases.jsonl"]) != len(result.cases):
        raise DivergenceAuditError("Divergence JSONL case count is invalid.")
    for name in (
        "divergence_cases.csv",
        "mechanism_summary.csv",
        "mechanism_by_condition.csv",
        "score_decomposition.csv",
        "sequence_comparison.csv",
        "harm_concentration.csv",
    ):
        with paths[name].open(encoding="utf-8", newline="") as stream:
            tuple(csv.DictReader(stream))
    with paths["planner_compatibility_audit.json"].open(encoding="utf-8") as stream:
        json.load(stream)
    if not paths["DIVERGENCE_AUDIT_REPORT.md"].read_text(encoding="utf-8").strip():
        raise DivergenceAuditError("Divergence audit report is empty.")
    if set(output_hashes) != set(FROZEN_OUTPUT_FILENAMES).difference({"divergence_manifest.json"}):
        raise DivergenceAuditError("Output hash set does not match the frozen artifacts.")


def _validate_complete_output(
    result: DivergenceAuditResult,
    paths: Mapping[str, Path],
    output_hashes: Mapping[str, str],
) -> None:
    if set(paths) != set(FROZEN_OUTPUT_FILENAMES):
        raise DivergenceAuditError("Output path set does not match the frozen contract.")
    if {path.name for path in paths.values()} != set(FROZEN_OUTPUT_FILENAMES):
        raise DivergenceAuditError("Output directory contains an unexpected artifact name.")
    with paths["divergence_manifest.json"].open(encoding="utf-8") as stream:
        manifest = cast(JsonObject, json.load(stream))
    if manifest["case_count"] != len(result.cases):
        raise DivergenceAuditError("Manifest case count is invalid.")
    for name, expected in output_hashes.items():
        if _sha256(paths[name]) != expected:
            raise DivergenceAuditError(f"Written artifact hash changed: {name}")


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[JsonObject]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise DivergenceAuditError(f"Cannot write empty frozen CSV: {path.name}")
    fieldnames = tuple(rows[0])
    if any(tuple(row) != fieldnames for row in rows):
        raise DivergenceAuditError(f"CSV rows have inconsistent fields: {path.name}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _jsonl_count(path: Path) -> int:
    count = 0
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            json.loads(line)
            count += 1
    return count


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fmt(value: object) -> str:
    if value is None:
        return "undefined"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return f"{float(value):.6f}"
    return str(value)


def _interval(low: object, high: object) -> str:
    if low is None or high is None:
        return "undefined"
    return f"[{_fmt(low)}, {_fmt(high)}]"


def _ci(row: Mapping[str, Any]) -> str:
    return _interval(row.get("confidence_interval_low"), row.get("confidence_interval_high"))
