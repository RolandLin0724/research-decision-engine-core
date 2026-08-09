from __future__ import annotations

from dataclasses import replace
from itertools import islice
from typing import cast

import pytest

import research_decision_engine.benchmarks.broader_pipeline as pipeline_module
import research_decision_engine.benchmarks.broader_projection as projection_module
from research_decision_engine.benchmarks.broader_analysis import PreGateAnalysisResult
from research_decision_engine.benchmarks.broader_conformance import (
    DiagnosticConformanceFixture,
)
from research_decision_engine.benchmarks.broader_execution import ActualExecutorAttestation
from research_decision_engine.benchmarks.broader_pipeline import (
    AttestedStudyExecution,
    FrozenAnalysisOrchestrator,
    FrozenStudyOrchestrator,
    ResamplingSpec,
    pair_completed_runs,
    validate_orchestration_contracts,
)
from research_decision_engine.benchmarks.broader_projection import (
    build_prefinalization_payloads,
)
from research_decision_engine.benchmarks.broader_runner import (
    BroaderArmRun,
)
from research_decision_engine.benchmarks.broader_statistics import (
    EstimandDataset,
    PairedMetricRow,
    ResamplingEstimand,
)


def _pair_with_corrupt_calibration_observation() -> tuple[BroaderArmRun, BroaderArmRun]:
    runs = (
        FrozenStudyOrchestrator()
        .execute_specs(tuple(islice(FrozenStudyOrchestrator().iter_run_specs(), 2)))
        .results
    )
    fixed, calibrated = runs
    assert calibrated.calibration is not None
    estimate = calibrated.calibration.estimates[0]
    observation = estimate.observations[0]
    changed_observation = replace(
        observation,
        revealed_observation=observation.revealed_observation + 1.0,
    )
    changed_estimate = replace(
        estimate,
        observations=(changed_observation, *estimate.observations[1:]),
    )
    corrupted = replace(
        calibrated,
        calibration=replace(
            calibrated.calibration,
            estimates=(changed_estimate, *calibrated.calibration.estimates[1:]),
        ),
    )
    return fixed, corrupted


def test_frozen_population_and_analysis_counts_are_lazy_and_exact() -> None:
    validate_orchestration_contracts()
    study = FrozenStudyOrchestrator()
    analysis = FrozenAnalysisOrchestrator()

    assert sum(1 for _ in study.iter_run_specs()) == 36_864
    assert sum(1 for _ in study.iter_comparison_specs()) == 18_432
    assert sum(1 for _ in study.iter_calibration_specs()) == 9_216
    assert len(analysis.contrast_ids()) == 122
    assert len(set(analysis.contrast_ids())) == 122
    assert analysis.resampling_counts() == (660_000, 640_000, 1_300_000)


def test_tiny_population_uses_production_run_pair_and_resampling_executors() -> None:
    study = FrozenStudyOrchestrator()
    run_specs = tuple(islice(study.iter_run_specs(), 2))
    execution = study.execute_specs(run_specs)
    runs = execution.results

    assert len(runs) == 2
    with pytest.raises(ValueError, match="exact-issued full-study execution"):
        pair_completed_runs(execution)

    analysis = FrozenAnalysisOrchestrator()
    dataset = EstimandDataset(
        "calibrated_minus_fixed",
        "nll",
        paired_metric_rows=(PairedMetricRow("comparison", 1000, 1.0, 0.5, 0.4),),
    )
    estimand = ResamplingEstimand("calibrated_minus_fixed", dataset)
    bootstrap = analysis.execute_resampling_spec(
        ResamplingSpec("bootstrap", "BR-C001", 0), estimand=estimand
    )
    sign_flip = analysis.execute_resampling_spec(
        ResamplingSpec("sign_flip", "BR-C001", 0), estimand=estimand
    )

    assert bootstrap.contrast_id == "BR-C001"
    assert bootstrap.replicate_index == 0
    assert sign_flip.contrast_id == "BR-C001"
    assert sign_flip.replicate_index == 0


def test_pairing_rejects_corrupt_calibration_before_arm_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed, corrupted = _pair_with_corrupt_calibration_observation()
    metrics_called = False

    def forbidden_metrics(*args: object, **kwargs: object) -> None:
        nonlocal metrics_called
        del args, kwargs
        metrics_called = True
        raise AssertionError("ArmMetrics must not be constructed")

    monkeypatch.setattr(pipeline_module, "evaluate_arm", forbidden_metrics)
    constructed = AttestedStudyExecution(
        (fixed, corrupted),
        cast(ActualExecutorAttestation, object()),
        None,
        False,
    )
    with pytest.raises(ValueError, match="exact-issued full-study execution"):
        pair_completed_runs(constructed)
    assert metrics_called is False


def test_prefinalization_rejects_corrupt_calibration_before_scientific_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed, corrupted = _pair_with_corrupt_calibration_observation()
    projection_called = False

    def forbidden_projection(*args: object, **kwargs: object) -> None:
        nonlocal projection_called
        del args, kwargs
        projection_called = True
        raise AssertionError("scientific payload construction must not run")

    for name in ("_run_and_event_rows", "_calibration_rows", "_comparison_rows"):
        monkeypatch.setattr(projection_module, name, forbidden_projection)
    with pytest.raises(ValueError, match="Scientific analysis was not issued"):
        build_prefinalization_payloads(
            (fixed, corrupted),
            cast(PreGateAnalysisResult, object()),
        )
    assert projection_called is False


def test_diagnostic_conformance_fixture_exercises_the_complete_analysis_path(
    diagnostic_conformance_fixture: DiagnosticConformanceFixture,
) -> None:
    fixture = diagnostic_conformance_fixture
    analysis = fixture.analysis
    labels = {item.paired.outcome_label for item in analysis.comparisons}
    gate_statuses = {item.status for item in analysis.gates}

    assert len(fixture.runs) == 252
    assert len(analysis.comparisons) == 126
    assert fixture.early_optimizer_rejection_verified
    assert {"nondivergent", "helped", "hurt"}.issubset(labels)
    assert analysis.contrast("BR-C006").result_status == "ESTIMATED"
    assert any(
        item.contrast_id.startswith("BR-C") and item.result_status == "INCONCLUSIVE"
        for item in analysis.contrasts
    )
    assert any(item.estimate is not None for item in analysis.bootstrap_rows)
    assert any(item.statistic is not None for item in analysis.sign_flip_rows)
    assert len(analysis.holm_results) == 64
    assert {"ESTIMATED", "INCONCLUSIVE"} == {item.result_status for item in analysis.holm_results}
    assert {item.value for item in gate_statuses} == {"PASS", "FAIL", "INCONCLUSIVE"}
    assert analysis.decision.branch_id in {"BRANCH-A", "BRANCH-B", "BRANCH-C", "BRANCH-D"}
    depth_three_runs = tuple(item for item in fixture.runs if item.world_id == "d3_adam")
    assert len(depth_three_runs) == 12
    assert all(
        action.oracle_observation is None
        for run in depth_three_runs
        for action in run.actions
        if action.role == "setup"
    )
    assert any(run.evidence and run.updates for run in depth_three_runs)
    assert any(
        tuple(action.candidate_id for action in run.actions[:3])
        == ("g00-setup-r1", "g00-adam-r1", "g00-sgd-r1")
        for run in depth_three_runs
    )
