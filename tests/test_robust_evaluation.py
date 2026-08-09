from __future__ import annotations

import csv
import json
from pathlib import Path

from research_decision_engine.belief_models import (
    CALIBRATED_SIGMA_MODEL_ID,
    FIXED_SIGMA_MODEL_ID,
)
from research_decision_engine.benchmarks.robust_evaluation import (
    RobustEvaluationRun,
    acceptance_gate_results,
    paired_comparison_rows,
    run_robust_belief_evaluation,
)
from research_decision_engine.benchmarks.robust_reporting import (
    OUTPUT_FILENAMES,
    write_robust_belief_outputs,
)


def test_robust_evaluation_is_deterministic_and_fairly_paired() -> None:
    first = run_robust_belief_evaluation(
        seeds=(0,),
        generated_at="2026-07-10T00:00:00+00:00",
        bootstrap_resamples=20,
    )
    second = run_robust_belief_evaluation(
        seeds=(0,),
        generated_at="2026-07-10T00:00:00+00:00",
        bootstrap_resamples=20,
    )

    assert first == second
    assert len(first.prefixes) == 4
    assert len(first.runs) == 64
    assert first.audits.all_passed()
    by_stream: dict[str, list[RobustEvaluationRun]] = {}
    for run in first.runs:
        by_stream.setdefault(run.paired_stream_id, []).append(run)
    assert len(by_stream) == 32
    for paired_runs in by_stream.values():
        fixed = next(item for item in paired_runs if item.belief_model_id == FIXED_SIGMA_MODEL_ID)
        calibrated = next(
            item for item in paired_runs if item.belief_model_id == CALIBRATED_SIGMA_MODEL_ID
        )
        assert fixed.observation_schedule_fingerprint == (
            calibrated.observation_schedule_fingerprint
        )
        assert fixed.evidence_stream_fingerprint == calibrated.evidence_stream_fingerprint
        assert [(item.candidate_id, item.observed_objective) for item in fixed.trace] == [
            (item.candidate_id, item.observed_objective) for item in calibrated.trace
        ]
        assert fixed.lineage_id != calibrated.lineage_id


def test_paired_metrics_include_all_frozen_gate_intervals() -> None:
    result = run_robust_belief_evaluation(
        seeds=(0, 1),
        generated_at="2026-07-10T00:00:00+00:00",
        bootstrap_resamples=30,
    )
    paired = paired_comparison_rows(
        result.runs,
        bootstrap_resamples=result.bootstrap_resamples,
    )
    gates = acceptance_gate_results(result.runs, paired, result.audits)
    performance_gates = gates["performance_gates"]

    assert any(item["metric"] == "calibration_error" for item in paired)
    assert all(item["confidence_interval_low"] is not None for item in paired)
    assert all(item["confidence_interval_high"] is not None for item in paired)
    assert isinstance(performance_gates, list)
    assert len(performance_gates) == 5
    assert gates["paired_confidence_intervals_reported"] is True
    assert gates["all_hard_audits_passed"] is True


def test_robust_outputs_are_valid_and_complete(tmp_path: Path) -> None:
    result = run_robust_belief_evaluation(
        seeds=(0,),
        generated_at="2026-07-10T00:00:00+00:00",
        bootstrap_resamples=20,
    )
    paths = write_robust_belief_outputs(result, tmp_path / "robust-v1")

    assert set(paths) == set(OUTPUT_FILENAMES)
    manifest = json.loads(paths["run_manifest.json"].read_text(encoding="utf-8"))
    gates = json.loads(paths["ACCEPTANCE_GATES.json"].read_text(encoding="utf-8"))
    first_run = json.loads(
        paths["per_run_results.jsonl"].read_text(encoding="utf-8").splitlines()[0]
    )
    with paths["paired_belief_model_comparisons.csv"].open(encoding="utf-8", newline="") as handle:
        comparison_rows = list(csv.DictReader(handle))
    with paths["adequacy_diagnostics.csv"].open(encoding="utf-8", newline="") as handle:
        diagnostic_rows = list(csv.DictReader(handle))

    assert manifest["run_count"] == 64
    assert manifest["audits"]["hidden_truth_absent_from_model_inputs"] is True
    assert len(gates["performance_gates"]) == 5
    assert first_run["full_metric_trace"]
    assert comparison_rows
    assert diagnostic_rows
    assert {item["belief_model_id"] for item in diagnostic_rows} == {
        FIXED_SIGMA_MODEL_ID,
        CALIBRATED_SIGMA_MODEL_ID,
    }
