from __future__ import annotations

import random
from dataclasses import replace

import pytest

from research_decision_engine.belief_models import MatchedEffectObservation
from research_decision_engine.benchmarks.broader_runner import (
    replay_decisions,
    validated_calibration_history_selections,
)
from research_decision_engine.benchmarks.broader_worlds import GROUP_IDS
from tests.taskc_calibration_harness import (
    artifact5_bytes,
    calibrated_deployment_runs,
    calibrated_run,
    replace_deployment_run,
    unrelated_effect,
)


def _interleaved_history(case_id: str) -> tuple[MatchedEffectObservation, ...]:
    run = calibrated_run()
    target_group = GROUP_IDS[0]
    if case_id == "earlier":
        extra = unrelated_effect(
            run,
            case_id=case_id,
            comparison_group_id="group-outside-frozen",
            available_sequence=0,
        )
        return (extra, *run.effect_history)
    if case_id == "interleaved":
        extra = unrelated_effect(
            run,
            case_id=case_id,
            comparison_group_id="group-outside-frozen",
            available_sequence=0,
        )
        return (*run.effect_history[:4], extra, *run.effect_history[4:])
    if case_id == "later":
        extra = unrelated_effect(
            run,
            case_id=case_id,
            comparison_group_id="group-outside-frozen",
            available_sequence=0,
        )
        return (*run.effect_history, extra)
    if case_id == "other-group":
        extra = unrelated_effect(
            run,
            case_id=case_id,
            comparison_group_id=GROUP_IDS[1],
            available_sequence=1,
        )
        return (*run.effect_history[:7], extra, *run.effect_history[7:])
    if case_id == "current":
        extra = unrelated_effect(
            run,
            case_id=case_id,
            comparison_group_id=target_group,
            available_sequence=1,
        )
        return (*run.effect_history[:2], extra, *run.effect_history[2:])
    if case_id == "future":
        extra = unrelated_effect(
            run,
            case_id=case_id,
            comparison_group_id=target_group,
            available_sequence=2,
        )
        return (*run.effect_history, extra)
    raise AssertionError(f"Unknown interleaving case: {case_id}")


@pytest.mark.taskc_calibration_interleaving
@pytest.mark.parametrize(
    "case_id",
    ("earlier", "interleaved", "later", "other-group", "current", "future"),
)
def test_unrelated_history_cannot_change_any_calibration_consumer(case_id: str) -> None:
    run = calibrated_run()
    deployment = calibrated_deployment_runs()
    baseline_selections = validated_calibration_history_selections(run)
    baseline_replay = replay_decisions(run)
    baseline_artifact = artifact5_bytes(deployment)
    assert run.calibration is not None
    baseline_provenance = tuple(
        estimate.provenance_sha256 for estimate in run.calibration.estimates
    )

    interleaved = replace(run, effect_history=_interleaved_history(case_id))
    interleaved_deployment = replace_deployment_run(deployment, interleaved)

    assert validated_calibration_history_selections(interleaved) == baseline_selections
    assert tuple(
        item.selection_identity for item in validated_calibration_history_selections(interleaved)
    ) == tuple(item.selection_identity for item in baseline_selections)
    assert replay_decisions(interleaved) == baseline_replay
    assert interleaved.calibration is not None
    assert (
        tuple(estimate.provenance_sha256 for estimate in interleaved.calibration.estimates)
        == baseline_provenance
    )
    assert artifact5_bytes(interleaved_deployment) == baseline_artifact


@pytest.mark.taskc_calibration_interleaving
@pytest.mark.parametrize("ordering", ("reversed", "shuffled"))
def test_storage_order_does_not_change_statistics_replay_provenance_or_artifact5(
    ordering: str,
) -> None:
    run = calibrated_run()
    deployment = calibrated_deployment_runs()
    history = list(run.effect_history)
    if ordering == "reversed":
        history.reverse()
    else:
        random.Random(31073).shuffle(history)
    reordered = replace(run, effect_history=tuple(history))

    baseline = validated_calibration_history_selections(run)
    selected = validated_calibration_history_selections(reordered)
    assert tuple(item.effect_values for item in selected) == tuple(
        item.effect_values for item in baseline
    )
    assert tuple(item.sample_mean for item in selected) == tuple(
        item.sample_mean for item in baseline
    )
    assert tuple(item.sample_standard_deviation for item in selected) == tuple(
        item.sample_standard_deviation for item in baseline
    )
    assert tuple(item.estimated_sigma for item in selected) == tuple(
        item.estimated_sigma for item in baseline
    )
    assert tuple(item.selection_identity for item in selected) == tuple(
        item.selection_identity for item in baseline
    )
    assert replay_decisions(reordered) == replay_decisions(run)
    assert reordered.calibration is not None
    assert run.calibration is not None
    assert tuple(item.provenance_sha256 for item in reordered.calibration.estimates) == tuple(
        item.provenance_sha256 for item in run.calibration.estimates
    )
    assert artifact5_bytes(replace_deployment_run(deployment, reordered)) == artifact5_bytes(
        deployment
    )
