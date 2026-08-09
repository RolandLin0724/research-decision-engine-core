from __future__ import annotations

import inspect
from dataclasses import fields

import pytest

from research_decision_engine.belief_models import (
    CALIBRATED_SIGMA_MODEL_ID,
    FIXED_SIGMA_MODEL_ID,
)
from research_decision_engine.benchmarks.closed_loop_evaluation import (
    ClosedLoopEvaluationResult,
    run_closed_loop_evaluation,
)
from research_decision_engine.closed_loop import (
    CandidateGroupPredictionAdapter,
    ClosedLoopArmSpec,
    SelectedOnlyObservationOracle,
    TruthFreeClosedLoopArmRun,
    run_closed_loop_arm,
)

GENERATED_AT = "2026-07-10T00:00:00+00:00"


@pytest.fixture(scope="module")
def closed_loop_result() -> ClosedLoopEvaluationResult:
    return run_closed_loop_evaluation(
        seeds=(0, 1),
        generated_at=GENERATED_AT,
        bootstrap_resamples=30,
    )


def test_selected_potential_outcomes_use_common_randomness(
    closed_loop_result: ClosedLoopEvaluationResult,
) -> None:
    observations: dict[tuple[str, str], set[float]] = {}
    arm_ids: dict[tuple[str, str], set[str]] = {}
    for run in closed_loop_result.runs:
        for access in run.arm_run.oracle_accesses:
            key = (run.commitment_id, access.candidate_id)
            observations.setdefault(key, set()).add(access.observed_value)
            arm_ids.setdefault(key, set()).add(run.arm.arm_id)

    shared_keys = tuple(key for key, values in arm_ids.items() if len(values) > 1)
    assert shared_keys
    assert all(len(observations[key]) == 1 for key in shared_keys)


def test_hidden_truth_and_unselected_outcomes_are_structurally_unavailable() -> None:
    forbidden = {
        "hidden_true_hypothesis",
        "true_hypothesis_id",
        "true_optimizer_effect",
        "observation_noise_std",
        "world_config",
        "potential_outcomes",
    }
    operational_fields = {
        item.name
        for model_type in (
            CandidateGroupPredictionAdapter,
            ClosedLoopArmSpec,
            TruthFreeClosedLoopArmRun,
        )
        for item in fields(model_type)
    }
    public_oracle_methods = {
        name
        for name, value in inspect.getmembers(
            SelectedOnlyObservationOracle,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }

    assert not operational_fields.intersection(forbidden)
    assert not set(inspect.signature(run_closed_loop_arm).parameters).intersection(forbidden)
    assert public_oracle_methods == {"audit_accesses", "reveal_selected"}
    assert not hasattr(SelectedOnlyObservationOracle, "lookup")
    assert not hasattr(SelectedOnlyObservationOracle, "enumerate_outcomes")


def test_arms_have_isolated_lineages_histories_and_evidence(
    closed_loop_result: ClosedLoopEvaluationResult,
) -> None:
    lineage_ids = [item.arm_run.lineage.lineage_id for item in closed_loop_result.runs]
    experiment_ids = [
        experiment.experiment_id
        for run in closed_loop_result.runs
        for experiment in run.arm_run.experiments
    ]
    evidence_ids = [
        evidence.evidence_id for run in closed_loop_result.runs for evidence in run.arm_run.evidence
    ]

    assert len(lineage_ids) == len(set(lineage_ids))
    assert len(experiment_ids) == len(set(experiment_ids))
    assert len(evidence_ids) == len(set(evidence_ids))
    assert all(
        update.lineage_id == run.arm_run.lineage.lineage_id
        for run in closed_loop_result.runs
        for update in run.arm_run.model_updates
    )


def test_calibration_does_not_update_prior_and_costs_stay_separate(
    closed_loop_result: ClosedLoopEvaluationResult,
) -> None:
    for run in closed_loop_result.runs:
        assert dict(run.arm_run.initial_posterior_probabilities) == pytest.approx(
            {
                "optimizer.adam-advantage": 1.0 / 3.0,
                "optimizer.no-consistent-advantage": 1.0 / 3.0,
                "optimizer.sgd-advantage": 1.0 / 3.0,
            }
        )
        assert run.metrics.required_total_cost == pytest.approx(
            run.metrics.calibration_cost + run.metrics.decision_cost
        )
        if run.belief_model_id == CALIBRATED_SIGMA_MODEL_ID:
            assert run.metrics.calibration_cost > 0.0
            assert (
                sum(item.source_kind == "calibration" for item in run.arm_run.effect_history) >= 5
            )
        else:
            assert run.belief_model_id == FIXED_SIGMA_MODEL_ID
            assert run.metrics.calibration_cost == 0.0
            assert not any(item.source_kind == "calibration" for item in run.arm_run.effect_history)


def test_calibrated_model_can_change_policy_trajectory(
    closed_loop_result: ClosedLoopEvaluationResult,
) -> None:
    divergence = next(
        item for item in closed_loop_result.divergences if item.first_divergence_step is not None
    )
    fixed = next(item for item in closed_loop_result.runs if item.run_id == divergence.fixed_run_id)
    calibrated = next(
        item for item in closed_loop_result.runs if item.run_id == divergence.calibrated_run_id
    )

    assert divergence.fixed_selected_candidate != divergence.calibrated_selected_candidate
    assert fixed.arm_run.decisions[0].prediction_snapshots != (
        calibrated.arm_run.decisions[0].prediction_snapshots
    )
    assert any(
        left.posterior_probabilities != right.posterior_probabilities
        for left, right in zip(
            fixed.arm_run.trace,
            calibrated.arm_run.trace,
            strict=False,
        )
    )


def test_fixed_policy_behavior_is_unchanged(
    closed_loop_result: ClosedLoopEvaluationResult,
) -> None:
    assert all(
        decision.fixed_policy_regression_match
        for run in closed_loop_result.runs
        if run.belief_model_id == FIXED_SIGMA_MODEL_ID
        for decision in run.arm_run.decisions
    )
    assert closed_loop_result.audits.fixed_policy_regression_unchanged is True


def test_only_real_selected_experiments_enter_scientific_evidence(
    closed_loop_result: ClosedLoopEvaluationResult,
) -> None:
    for run in closed_loop_result.runs:
        experiment_ids = {item.experiment_id for item in run.arm_run.experiments}
        assert len(run.arm_run.decisions) == len(run.arm_run.experiments)
        assert all(
            set(evidence.source_experiment_ids).issubset(experiment_ids)
            for evidence in run.arm_run.evidence
        )
        assert all(
            "SIMULATED" not in experiment.created_at for experiment in run.arm_run.experiments
        )
