from __future__ import annotations

import csv
import json
import math
from dataclasses import fields
from pathlib import Path

import pytest

from research_decision_engine.benchmarks.evaluation import (
    BENCHMARK_POLICIES,
    ExperimentMetricTrace,
    PolicyBenchmarkContext,
    derive_run_metrics,
    run_benchmark_condition,
    run_benchmark_suite,
)
from research_decision_engine.benchmarks.reporting import write_benchmark_outputs
from research_decision_engine.benchmarks.worlds import (
    benchmark_worlds,
    build_benchmark_world,
)
from research_decision_engine.optimizer_effect import ADAM_ADVANTAGE_ID, optimizer_effect_hypotheses
from research_decision_engine.reasoning import BeliefState, initial_belief_state

GENERATED_AT = "2026-01-01T00:00:00+00:00"


def test_benchmark_suite_covers_required_world_variants() -> None:
    configs = benchmark_worlds()

    assert {item.noise_level for item in configs} == {"low", "medium", "high"}
    assert {item.cost_mode for item in configs} == {"symmetric", "asymmetric"}
    assert {item.candidate_variant for item in configs} == {
        "base",
        "irrelevant_redundant",
    }
    assert len({item.true_hypothesis_id for item in configs}) == 3
    assert len({item.true_optimizer_effect for item in configs}) >= 4

    rich_config = next(item for item in configs if item.candidate_variant == "irrelevant_redundant")
    design, _ = build_benchmark_world(rich_config, seed=0)
    assert design.irrelevant_candidate_ids
    assert design.redundant_candidate_ids
    assert all(
        {
            candidate.optimizer
            for candidate in design.candidates
            if (
                candidate.learning_rate,
                candidate.regularization,
                candidate.model_width,
            )
            == controls
        }
        == {"sgd", "adam"}
        for controls in {
            (
                candidate.learning_rate,
                candidate.regularization,
                candidate.model_width,
            )
            for candidate in design.candidates
        }
    )


def test_benchmark_runs_and_noisy_observations_are_deterministic() -> None:
    config = benchmark_worlds(("sgd_high_noise_symmetric",))[0]

    left = run_benchmark_condition(
        world_config=config,
        policy="random",
        seed=7,
        budget=5.0,
        generated_at=GENERATED_AT,
    )
    right = run_benchmark_condition(
        world_config=config,
        policy="random",
        seed=7,
        budget=5.0,
        generated_at=GENERATED_AT,
    )
    different_seed = run_benchmark_condition(
        world_config=config,
        policy="random",
        seed=8,
        budget=5.0,
        generated_at=GENERATED_AT,
    )

    assert left == right
    assert [item.observed_objective for item in left.trace] != [
        item.observed_objective for item in different_seed.trace
    ]


def test_policies_receive_equivalent_initial_conditions() -> None:
    report = run_benchmark_suite(
        world_ids=("adam_low_noise_symmetric",),
        policies=BENCHMARK_POLICIES,
        seeds=(3,),
        budget=4.0,
        generated_at=GENERATED_AT,
    )

    assert len(report.runs) == 3
    assert len({run.initial_condition_fingerprint for run in report.runs}) == 1
    assert len({run.initial_belief_probabilities for run in report.runs}) == 1
    assert {run.budget for run in report.runs} == {4.0}
    assert {run.seed for run in report.runs} == {3}


def test_hidden_truth_is_absent_from_policy_context() -> None:
    context_fields = {item.name for item in fields(PolicyBenchmarkContext)}

    assert "true_hypothesis_id" not in context_fields
    assert "true_optimizer_effect" not in context_fields
    assert "world_config" not in context_fields
    assert "hidden_world" not in context_fields


def test_run_metrics_are_calculated_from_trace() -> None:
    hypotheses = optimizer_effect_hypotheses()
    initial = initial_belief_state(hypotheses, created_at=GENERATED_AT)
    posterior = tuple(
        {
            "optimizer.adam-advantage": 0.85,
            "optimizer.no-consistent-advantage": 0.10,
            "optimizer.sgd-advantage": 0.05,
        }[hypothesis_id]
        for hypothesis_id in initial.hypothesis_ids
    )
    final_belief = BeliefState(
        belief_state_id="belief-metric-fixture",
        hypothesis_ids=initial.hypothesis_ids,
        prior_probabilities=initial.prior_probabilities,
        posterior_probabilities=posterior,
        evidence_ids=("evidence-fixture",),
        sequence=1,
        created_at=GENERATED_AT,
        parent_belief_state_id=initial.belief_state_id,
    )
    trace = (
        _trace_item(step=1, cumulative_cost=1.0, true_probability=0.50),
        _trace_item(step=2, cumulative_cost=3.0, true_probability=0.85),
    )

    scientific, objective = derive_run_metrics(
        trace=trace,
        final_belief=final_belief,
        true_hypothesis_id=ADAM_ADVANTAGE_ID,
    )

    assert scientific.experiments_to_80_confidence == 2
    assert scientific.cost_to_80_confidence == 3.0
    assert scientific.experiments_to_95_confidence is None
    assert scientific.cost_to_95_confidence is None
    assert scientific.redundant_experiments_selected == 1
    assert scientific.matched_evidence_pairs_completed == 1
    assert scientific.final_true_hypothesis_rank == 1
    assert scientific.final_brier_calibration == pytest.approx(0.035)
    assert objective.total_experimental_cost == 3.0
    assert objective.experiments_completed == 2
    assert objective.best_observed_objective == 0.9


def test_entropy_confidence_json_and_csv_outputs_are_complete(tmp_path: Path) -> None:
    report = run_benchmark_suite(
        world_ids=("neutral_medium_noise_asymmetric",),
        policies=BENCHMARK_POLICIES,
        seeds=(0,),
        budget=4.0,
        generated_at=GENERATED_AT,
    )
    paths = write_benchmark_outputs(report, tmp_path / "results")

    parsed_json = json.loads(paths.json_results.read_text(encoding="utf-8"))
    with paths.run_results_csv.open(newline="", encoding="utf-8") as handle:
        run_rows = list(csv.DictReader(handle))
    with paths.trace_results_csv.open(newline="", encoding="utf-8") as handle:
        trace_rows = list(csv.DictReader(handle))
    with paths.aggregate_results_csv.open(newline="", encoding="utf-8") as handle:
        aggregate_rows = list(csv.DictReader(handle))

    assert len(parsed_json["runs"]) == 3
    assert len(run_rows) == 3
    assert trace_rows
    assert aggregate_rows
    assert all("posterior_entropy" in row for row in trace_rows)
    assert all("true_hypothesis_probability" in row for row in trace_rows)
    assert all(math.isfinite(float(row["posterior_entropy"])) for row in trace_rows)
    assert {row["scope"] for row in aggregate_rows} == {"policy", "policy_world"}


def _trace_item(
    *, step: int, cumulative_cost: float, true_probability: float
) -> ExperimentMetricTrace:
    return ExperimentMetricTrace(
        step=step,
        candidate_id=f"candidate-{step}",
        observed_objective=0.8 + step * 0.05,
        experiment_cost=1.0 if step == 1 else 2.0,
        cumulative_cost=cumulative_cost,
        posterior_entropy=1.0 / step,
        posterior_entropy_per_unit_cost=(1.0 / step) / cumulative_cost,
        entropy_reduction_per_unit_cost=(1.5 - 1.0 / step) / cumulative_cost,
        true_hypothesis_probability=true_probability,
        true_hypothesis_rank=1,
        posterior_probabilities=(
            ("optimizer.adam-advantage", true_probability),
            ("optimizer.no-consistent-advantage", 1.0 - true_probability),
            ("optimizer.sgd-advantage", 0.0),
        ),
        redundant_experiment=step == 2,
        cumulative_redundant_experiments=1 if step == 2 else 0,
        new_matched_evidence=step == 2,
        matched_evidence_pairs_completed=1 if step == 2 else 0,
        best_observed_objective=0.8 + step * 0.05,
    )
