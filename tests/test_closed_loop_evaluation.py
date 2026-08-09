from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from research_decision_engine.benchmarks.closed_loop_evaluation import (
    ClosedLoopEvaluationResult,
    closed_loop_acceptance_results,
    paired_closed_loop_comparisons,
    run_closed_loop_evaluation,
)
from research_decision_engine.benchmarks.closed_loop_reporting import (
    OUTPUT_FILENAMES,
    write_closed_loop_outputs,
)

GENERATED_AT = "2026-07-10T00:00:00+00:00"


@pytest.fixture(scope="module")
def evaluation_result() -> ClosedLoopEvaluationResult:
    return run_closed_loop_evaluation(
        seeds=(0, 1),
        generated_at=GENERATED_AT,
        bootstrap_resamples=30,
    )


def test_closed_loop_runs_and_bootstrap_are_deterministic() -> None:
    left = run_closed_loop_evaluation(
        seeds=(3,),
        generated_at=GENERATED_AT,
        bootstrap_resamples=20,
        verify_representative_replays=False,
    )
    right = run_closed_loop_evaluation(
        seeds=(3,),
        generated_at=GENERATED_AT,
        bootstrap_resamples=20,
        verify_representative_replays=False,
    )

    assert left == right
    assert left.audits.all_passed()
    assert left.acceptance["verdict"] == "smoke_only"


def test_divergence_metrics_match_paired_run_consequences(
    evaluation_result: ClosedLoopEvaluationResult,
) -> None:
    for divergence in evaluation_result.divergences:
        fixed = next(
            item for item in evaluation_result.runs if item.run_id == divergence.fixed_run_id
        )
        calibrated = next(
            item for item in evaluation_result.runs if item.run_id == divergence.calibrated_run_id
        )
        assert divergence.nll_difference == pytest.approx(
            calibrated.metrics.negative_log_true_hypothesis_probability
            - fixed.metrics.negative_log_true_hypothesis_probability
        )
        assert divergence.brier_difference == pytest.approx(
            calibrated.metrics.final_brier_score - fixed.metrics.final_brier_score
        )
        assert divergence.decision_cost_difference == pytest.approx(
            calibrated.metrics.decision_cost - fixed.metrics.decision_cost
        )


def test_paired_bootstrap_and_acceptance_gates_are_exact(
    evaluation_result: ClosedLoopEvaluationResult,
) -> None:
    repeated = paired_closed_loop_comparisons(
        evaluation_result.runs,
        bootstrap_resamples=evaluation_result.bootstrap_resamples,
    )
    gates = closed_loop_acceptance_results(
        runs=evaluation_result.runs,
        paired_rows=repeated,
        audits=evaluation_result.audits,
        full_frozen_matrix=False,
    )
    performance = gates["performance_gates"]

    assert repeated == evaluation_result.paired_rows
    assert isinstance(performance, tuple)
    assert len(performance) == 97
    assert len({item["gate_id"] for item in performance}) == 97
    assert {item["gate_group"] for item in performance} == {
        "1_adverse_confidently_wrong",
        "2_adverse_proper_scores",
        "3_delayed_non_regression",
        "4_other_world_non_regression",
        "5_decision_cost_control",
        "6_adverse_conditional_efficiency",
        "7_end_to_end_efficiency",
    }
    assert all(item["fixed_value"] is not None for item in performance)
    assert all(item["calibrated_value"] is not None for item in performance)
    assert all(item["paired_95_ci_low"] is not None for item in performance)
    assert all(item["paired_95_ci_high"] is not None for item in performance)
    assert gates["verdict"] == "smoke_only"


def test_closed_loop_artifacts_are_valid_complete_and_non_overwriting(
    tmp_path: Path,
    evaluation_result: ClosedLoopEvaluationResult,
) -> None:
    output_directory = tmp_path / "closed-loop-v1"
    paths = write_closed_loop_outputs(evaluation_result, output_directory)

    assert set(paths) == set(OUTPUT_FILENAMES)
    manifest = json.loads(paths["run_manifest.json"].read_text(encoding="utf-8"))
    gates = json.loads(paths["ACCEPTANCE_GATES.json"].read_text(encoding="utf-8"))
    run_lines = paths["per_run_results.jsonl"].read_text(encoding="utf-8").splitlines()
    with paths["paired_closed_loop_comparisons.csv"].open(encoding="utf-8", newline="") as handle:
        paired_rows = tuple(csv.DictReader(handle))
    with paths["adequacy_diagnostics.csv"].open(encoding="utf-8", newline="") as handle:
        diagnostic_rows = tuple(csv.DictReader(handle))

    assert manifest["run_count"] == len(evaluation_result.runs)
    assert manifest["audits"]["hidden_truth_isolated"] is True
    assert len(run_lines) == len(evaluation_result.runs)
    assert len(gates["performance_gates"]) == 97
    assert paired_rows
    assert diagnostic_rows
    assert (
        paths["CLOSED_LOOP_EVALUATION_REPORT.md"]
        .read_text(encoding="utf-8")
        .startswith("# Closed-Loop Belief-Control Evaluation Report")
    )
    with pytest.raises(FileExistsError):
        write_closed_loop_outputs(evaluation_result, output_directory)
