from __future__ import annotations

import csv
import json
from dataclasses import fields
from pathlib import Path

import pytest

from research_decision_engine.benchmarks.evaluation import PolicyBenchmarkContext
from research_decision_engine.benchmarks.paired_evaluation import (
    PAIRED_POLICIES,
    classify_posterior,
    deterministic_bootstrap_mean_interval,
    run_paired_evaluation,
    top_label_expected_calibration_error,
)
from research_decision_engine.benchmarks.paired_reporting import (
    write_paired_evaluation_outputs,
)
from research_decision_engine.benchmarks.worlds import (
    build_benchmark_world,
    paired_evaluation_worlds,
)

GENERATED_AT = "2026-01-01T00:00:00+00:00"


@pytest.fixture(scope="module")
def paired_report():  # type: ignore[no-untyped-def]
    return run_paired_evaluation(
        seeds=(0, 1),
        bootstrap_resamples=50,
        generated_at=GENERATED_AT,
    )


def test_paired_evaluation_is_deterministic() -> None:
    left = run_paired_evaluation(
        seeds=(3,),
        bootstrap_resamples=25,
        generated_at=GENERATED_AT,
    )
    right = run_paired_evaluation(
        seeds=(3,),
        bootstrap_resamples=25,
        generated_at=GENERATED_AT,
    )

    assert left == right
    assert left.fairness_audit.deterministic_replays_match is True


def test_every_policy_receives_identical_paired_conditions(paired_report) -> None:  # type: ignore[no-untyped-def]
    assert len(paired_report.runs) == 4 * 2 * 2 * 4
    for world_id in {item.world_id for item in paired_report.runs}:
        for budget_label in {item.budget_label for item in paired_report.runs}:
            for seed in paired_report.seeds:
                group = [
                    item
                    for item in paired_report.runs
                    if item.world_id == world_id
                    and item.budget_label == budget_label
                    and item.seed == seed
                ]
                assert {item.policy for item in group} == set(PAIRED_POLICIES)
                assert len({item.public_initial_condition_fingerprint for item in group}) == 1
                assert len({item.observation_schedule_fingerprint for item in group}) == 1
                assert len({item.benchmark_run.initial_belief_probabilities for item in group}) == 1


def test_policy_context_and_runtime_audit_exclude_hidden_truth(paired_report) -> None:  # type: ignore[no-untyped-def]
    context_fields = {item.name for item in fields(PolicyBenchmarkContext)}

    assert not context_fields.intersection(
        {"true_hypothesis_id", "true_optimizer_effect", "world_config", "hidden_world"}
    )
    assert paired_report.fairness_audit.hidden_truth_absent_from_policy_interfaces is True
    assert paired_report.fairness_audit.benchmark_truth_confined_to_evaluation is True
    assert paired_report.fairness_audit.simulated_state_not_persisted is True
    assert paired_report.fairness_audit.no_world_specific_policy_tuning is True


def test_larger_budget_design_can_complete_multiple_pairs() -> None:
    configs = paired_evaluation_worlds()

    assert {item.world_id for item in configs} == {
        "delayed_information",
        "no_optimizer_advantage",
        "adverse_noisy_observations",
        "asymmetric_experiment_costs",
    }
    for config in configs:
        design, _ = build_benchmark_world(config, seed=0)
        eligible_designs = [
            item
            for item in design.evidence_eligibility().designs
            if item.experiment_family == "optimizer-effect"
        ]
        comparison_groups = {item.comparison_group_id for item in eligible_designs}
        assert len(comparison_groups) >= 2
        assert all(
            {
                item.intervention_arm
                for item in eligible_designs
                if item.comparison_group_id == group
            }
            == {"sgd", "adam"}
            for group in comparison_groups
        )


def test_bootstrap_is_reproducible() -> None:
    values = (0.1, -0.2, 0.3, 0.4)

    left = deterministic_bootstrap_mean_interval(
        values,
        resamples=1_000,
        key=("world", "short", "random", "entropy"),
    )
    right = deterministic_bootstrap_mean_interval(
        values,
        resamples=1_000,
        key=("world", "short", "random", "entropy"),
    )

    assert left == right
    assert left[0] <= sum(values) / len(values) <= left[1]


def test_confidently_wrong_classification_is_exact() -> None:
    result = classify_posterior(
        {
            "optimizer.adam-advantage": 0.90,
            "optimizer.no-consistent-advantage": 0.09,
            "optimizer.sgd-advantage": 0.01,
        },
        "optimizer.sgd-advantage",
    )

    assert result.predicted_hypothesis_id == "optimizer.adam-advantage"
    assert result.maximum_posterior_probability == 0.90
    assert result.correct is False
    assert result.confidently_wrong is True


def test_calibration_error_matches_hand_calculation() -> None:
    calibration_error = top_label_expected_calibration_error(((0.90, True), (0.80, False)))

    assert calibration_error == pytest.approx(0.45)


def test_world_level_aggregation_uses_only_matching_runs(paired_report) -> None:  # type: ignore[no-untyped-def]
    run = next(
        item
        for item in paired_report.runs
        if item.world_id == "delayed_information"
        and item.budget_label == "short"
        and item.policy == "lookahead_information_gain"
        and item.seed == 0
    )
    paired_run = next(
        item
        for item in paired_report.runs
        if item.world_id == run.world_id
        and item.budget_label == run.budget_label
        and item.policy == run.policy
        and item.seed == 1
    )
    aggregate = next(
        item
        for item in paired_report.aggregates
        if item.world_id == run.world_id
        and item.budget_label == run.budget_label
        and item.policy == run.policy
        and item.metric == "final_true_hypothesis_probability"
    )

    assert aggregate.sample_count == 2
    assert aggregate.mean == pytest.approx(
        (
            run.metrics.final_true_hypothesis_probability
            + paired_run.metrics.final_true_hypothesis_probability
        )
        / 2.0
    )


def test_jsonl_and_csv_outputs_are_valid(tmp_path: Path, paired_report) -> None:  # type: ignore[no-untyped-def]
    paths = write_paired_evaluation_outputs(paired_report, tmp_path / "paired-v1")

    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    per_run_lines = paths.per_run_jsonl.read_text(encoding="utf-8").splitlines()
    failure_lines = paths.failure_cases_jsonl.read_text(encoding="utf-8").splitlines()
    with paths.per_run_csv.open(newline="", encoding="utf-8") as handle:
        run_rows = list(csv.DictReader(handle))
    with paths.aggregates_csv.open(newline="", encoding="utf-8") as handle:
        aggregate_rows = list(csv.DictReader(handle))
    with paths.paired_comparisons_csv.open(newline="", encoding="utf-8") as handle:
        paired_rows = list(csv.DictReader(handle))
    with paths.calibration_csv.open(newline="", encoding="utf-8") as handle:
        calibration_rows = list(csv.DictReader(handle))

    assert manifest["fairness_and_leakage_audit"]["passed"] is True
    assert len(per_run_lines) == len(paired_report.runs)
    assert all(json.loads(line)["full_metric_trace"] for line in per_run_lines)
    assert len(run_rows) == len(paired_report.runs)
    assert aggregate_rows and paired_rows and calibration_rows
    assert all(json.loads(line)["failure_types"] for line in failure_lines)
    assert paths.evaluation_report.read_text(encoding="utf-8").startswith(
        "# Paired Lookahead Evaluation"
    )
