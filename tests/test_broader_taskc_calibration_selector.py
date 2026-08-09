from __future__ import annotations

import random
import statistics
from dataclasses import FrozenInstanceError, replace

import pytest

from research_decision_engine.benchmarks.broader_calibration_history import (
    CALIBRATION_ELIGIBILITY_BASIS,
    CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
    select_calibration_history,
)
from research_decision_engine.benchmarks.broader_oracle import CALIBRATION_NAMESPACE
from research_decision_engine.benchmarks.broader_protocol import PROTOCOL_VERSION
from research_decision_engine.benchmarks.broader_runner import (
    validated_calibration_history_selections,
)
from research_decision_engine.benchmarks.broader_worlds import GROUP_IDS
from tests.taskc_calibration_harness import calibrated_run, selection_for_run


@pytest.mark.taskc_calibration_selector
def test_selector_returns_the_exact_frozen_five_effect_population() -> None:
    run = calibrated_run()
    selection = selection_for_run(run)
    group_index = GROUP_IDS.index(selection.comparison_group_id)
    prefix_id = (
        f"calibration-prefix/{selection.world_id}/{selection.seed}/{selection.comparison_group_id}"
    )

    assert selection.source_effect_ids == tuple(
        f"calibration-effect/{prefix_id}/calibration-{group_index:02d}-r{index:04d}"
        for index in range(1, 6)
    )
    assert selection.source_replication_ids == tuple(
        f"calibration-{group_index:02d}-r{index:04d}" for index in range(1, 6)
    )
    assert selection.source_candidate_pairs == tuple(
        (
            f"cal-{group_index:02d}-adam-r{index:04d}",
            f"cal-{group_index:02d}-sgd-r{index:04d}",
        )
        for index in range(1, 6)
    )
    assert selection.source_oracle_key_ids == tuple(
        observation.oracle_key_id for observation in selection.observations
    )
    assert selection.source_observation_identities == tuple(
        (observation.oracle_key_id, observation.outcome_digest)
        for observation in selection.observations
    )
    assert tuple(item.effect_id for item in selection.effects) == selection.source_effect_ids
    assert selection.effect_values == tuple(item.observed_effect for item in selection.effects)
    assert selection.sample_count == 5
    assert len(selection.observations) == 10
    assert selection.sample_mean == statistics.mean(selection.effect_values)
    assert selection.sample_standard_deviation == statistics.stdev(selection.effect_values)
    assert selection.ddof == 1
    assert selection.estimated_sigma == max(
        selection.sample_standard_deviation, selection.sigma_floor
    )
    assert selection.namespace == CALIBRATION_NAMESPACE
    assert selection.study_id == PROTOCOL_VERSION
    assert selection.world_id == run.world_id
    assert selection.seed == run.seed
    assert selection.target_comparison_group_id == selection.comparison_group_id
    assert selection.source_sequence_cutoff == CALIBRATION_SOURCE_SEQUENCE_CUTOFF
    assert selection.eligibility_basis == CALIBRATION_ELIGIBILITY_BASIS
    assert selection.current_observation_excluded
    assert selection.current_effect_excluded
    assert selection.future_history_excluded
    assert len(selection.selection_identity) == 64
    assert int(selection.selection_identity, 16) >= 0


@pytest.mark.taskc_calibration_selector
def test_selection_result_and_identity_are_immutable() -> None:
    selection = selection_for_run(calibrated_run())
    identity = selection.scientific_identity()

    with pytest.raises(FrozenInstanceError):
        selection.sample_count = 6  # type: ignore[misc]

    assert selection.scientific_identity() == identity
    assert selection.selection_identity == identity[-1]


@pytest.mark.taskc_calibration_selector
@pytest.mark.parametrize("ordering", ("reversed", "shuffled"))
def test_selector_canonicalizes_reversed_and_shuffled_persisted_histories(
    ordering: str,
) -> None:
    run = calibrated_run()
    baseline = validated_calibration_history_selections(run)
    history = list(run.effect_history)
    if ordering == "reversed":
        history.reverse()
    else:
        random.Random(20260715).shuffle(history)
    reordered = replace(run, effect_history=tuple(history))

    assert validated_calibration_history_selections(reordered) == baseline
    assert tuple(item.selection_identity for item in baseline) == tuple(
        item.selection_identity for item in validated_calibration_history_selections(reordered)
    )


@pytest.mark.taskc_calibration_selector
def test_shared_prefix_identity_is_independent_of_the_deploying_run() -> None:
    information_gain = selection_for_run(calibrated_run("calibrated_ig"))
    lookahead = selection_for_run(calibrated_run("calibrated_lookahead"))

    assert information_gain.selection_identity == lookahead.selection_identity
    assert information_gain.scientific_identity() == lookahead.scientific_identity()
    assert information_gain.source_oracle_key_ids == lookahead.source_oracle_key_ids
    assert information_gain.observations != lookahead.observations


@pytest.mark.taskc_calibration_selector
def test_direct_selector_matches_the_runner_authority_result() -> None:
    run = calibrated_run()
    assert run.calibration is not None
    estimate = run.calibration.estimates[0]

    direct = select_calibration_history(
        run_id=run.run_id,
        world_id=run.world_id,
        seed=run.seed,
        comparison_group_id=estimate.comparison_group_id,
        recorded_observations=tuple(reversed(estimate.observations)),
        recorded_effects=tuple(reversed(run.effect_history)),
    )

    assert direct == validated_calibration_history_selections(run)[0]
