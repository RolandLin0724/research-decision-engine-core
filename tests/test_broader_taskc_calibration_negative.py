from __future__ import annotations

from dataclasses import replace

import pytest

from research_decision_engine.belief_models import MatchedEffectObservation
from research_decision_engine.benchmarks.broader_calibration_history import (
    CalibrationHistorySelection,
    RunProvenanceError,
    select_calibration_history,
)
from research_decision_engine.benchmarks.broader_oracle import RevealedObservation
from research_decision_engine.benchmarks.broader_worlds import GROUP_IDS
from research_decision_engine.reasoning import Provenance

_RUN_ID = "taskc-calibration-negative/run"
_WORLD_ID = "g_adam_lmh"
_SEED = 9000
_GROUP_ID = GROUP_IDS[0]
_VALIDATION_LAYER = "calibration_history_selector"


def _baseline() -> CalibrationHistorySelection:
    return select_calibration_history(
        run_id=_RUN_ID,
        world_id=_WORLD_ID,
        seed=_SEED,
        comparison_group_id=_GROUP_ID,
    )


def _select(
    *,
    effects: tuple[MatchedEffectObservation, ...],
    observations: tuple[RevealedObservation, ...],
) -> CalibrationHistorySelection:
    return select_calibration_history(
        run_id=_RUN_ID,
        world_id=_WORLD_ID,
        seed=_SEED,
        comparison_group_id=_GROUP_ID,
        recorded_effects=effects,
        recorded_observations=observations,
    )


class _ScoringSentinel:
    def __init__(self) -> None:
        self.entered = False

    def __call__(self, selection: CalibrationHistorySelection) -> None:
        del selection
        self.entered = True


def _select_then_score(
    *,
    effects: tuple[MatchedEffectObservation, ...],
    observations: tuple[RevealedObservation, ...],
    scorer: _ScoringSentinel,
) -> CalibrationHistorySelection:
    selection = _select(effects=effects, observations=observations)
    scorer(selection)
    return selection


def _replace_effect(
    effects: tuple[MatchedEffectObservation, ...],
    changed: MatchedEffectObservation,
) -> tuple[MatchedEffectObservation, ...]:
    return (changed, *effects[1:])


def _replace_observation(
    observations: tuple[RevealedObservation, ...],
    changed: RevealedObservation,
) -> tuple[RevealedObservation, ...]:
    return (changed, *observations[1:])


def _changed_replication_provenance(
    effect: MatchedEffectObservation,
) -> MatchedEffectObservation:
    details = effect.provenance.details_dict()
    details["replication_id"] = f"{details['replication_id']}/forged"
    return replace(
        effect,
        provenance=Provenance.create(
            method=effect.provenance.method,
            version=effect.provenance.version,
            details=details,
        ),
    )


def _assert_fail_closed(error: RunProvenanceError, expected_error_code: str) -> None:
    assert error.error_code == expected_error_code
    assert error.validation_layer == _VALIDATION_LAYER
    assert error.scoring_entered is False
    assert error.scientific_output_entered is False


@pytest.mark.taskc_calibration_negative
@pytest.mark.parametrize(
    ("case", "expected_error_code"),
    (
        ("duplicate_effect_id", "CALIBRATION_DUPLICATE_EFFECT_ID"),
        ("missing_eligible_effect", "CALIBRATION_MISSING_ELIGIBLE_EFFECT"),
        ("extra_eligible_effect", "CALIBRATION_EXTRA_ELIGIBLE_EFFECT"),
        ("changed_effect_value", "CALIBRATION_EFFECT_VALUE_MISMATCH"),
        ("changed_candidate_pair", "CALIBRATION_CANDIDATE_PAIR_MISMATCH"),
        ("changed_replication", "CALIBRATION_REPLICATION_MISMATCH"),
        ("changed_group", "CALIBRATION_GROUP_MISMATCH"),
        ("same_group_ineligible_effect", "CALIBRATION_INELIGIBLE_EFFECT"),
        ("changed_chronology", "CALIBRATION_CHRONOLOGY_MISMATCH"),
        ("current_effect", "CALIBRATION_CHRONOLOGY_MISMATCH"),
        ("future_effect", "CALIBRATION_CHRONOLOGY_MISMATCH"),
    ),
)
def test_effect_history_corruption_fails_at_the_selector_boundary(
    case: str,
    expected_error_code: str,
) -> None:
    baseline = _baseline()
    effects = baseline.effects
    first = effects[0]

    if case == "duplicate_effect_id":
        corrupted = (*effects, first)
    elif case == "missing_eligible_effect":
        corrupted = effects[1:]
    elif case == "extra_eligible_effect":
        corrupted = (*effects, replace(first, effect_id=f"{first.effect_id}/extra"))
    elif case == "changed_effect_value":
        corrupted = _replace_effect(
            effects,
            replace(first, observed_effect=first.observed_effect + 1.0),
        )
    elif case == "changed_candidate_pair":
        corrupted = _replace_effect(
            effects,
            replace(first, source_ids=tuple(reversed(first.source_ids))),
        )
    elif case == "changed_replication":
        corrupted = _replace_effect(effects, _changed_replication_provenance(first))
    elif case == "changed_group":
        corrupted = _replace_effect(
            effects,
            replace(first, comparison_group_id=GROUP_IDS[1]),
        )
    elif case == "same_group_ineligible_effect":
        corrupted = _replace_effect(effects, replace(first, source_kind="decision"))
    elif case == "changed_chronology":
        corrupted = _replace_effect(effects, replace(first, available_sequence=3))
    elif case == "current_effect":
        corrupted = _replace_effect(effects, replace(first, available_sequence=1))
    else:
        assert case == "future_effect"
        corrupted = _replace_effect(effects, replace(first, available_sequence=2))

    scoring = _ScoringSentinel()
    with pytest.raises(RunProvenanceError) as captured:
        _select_then_score(
            effects=corrupted,
            observations=baseline.observations,
            scorer=scoring,
        )

    _assert_fail_closed(captured.value, expected_error_code)
    assert scoring.entered is False


@pytest.mark.taskc_calibration_negative
@pytest.mark.parametrize(
    ("case", "expected_error_code"),
    (
        ("duplicate_source_observation", "CALIBRATION_DUPLICATE_SOURCE_OBSERVATION"),
        ("extra_source_observation", "CALIBRATION_SOURCE_OBSERVATION_COUNT_MISMATCH"),
        ("changed_oracle_key", "CALIBRATION_ORACLE_IDENTITY_MISMATCH"),
        ("changed_candidate_pair", "CALIBRATION_CANDIDATE_PAIR_MISMATCH"),
        ("changed_replication", "CALIBRATION_REPLICATION_MISMATCH"),
        ("changed_group", "CALIBRATION_GROUP_MISMATCH"),
        ("changed_namespace", "CALIBRATION_NAMESPACE_MISMATCH"),
        ("changed_world", "CALIBRATION_WORLD_MISMATCH"),
        ("changed_seed", "CALIBRATION_SEED_MISMATCH"),
    ),
)
def test_source_observation_corruption_fails_at_the_selector_boundary(
    case: str,
    expected_error_code: str,
) -> None:
    baseline = _baseline()
    observations = baseline.observations
    first = observations[0]

    if case == "duplicate_source_observation":
        corrupted = (first, first, *observations[2:])
    elif case == "extra_source_observation":
        corrupted = (*observations, first)
    elif case == "changed_oracle_key":
        corrupted = _replace_observation(
            observations,
            replace(first, oracle_key_id=f"{first.oracle_key_id}/forged"),
        )
    elif case == "changed_candidate_pair":
        corrupted = _replace_observation(
            observations,
            replace(first, candidate_id=f"{first.candidate_id}/forged"),
        )
    elif case == "changed_replication":
        corrupted = _replace_observation(
            observations,
            replace(first, replication_id=f"{first.replication_id}/forged"),
        )
    elif case == "changed_group":
        corrupted = _replace_observation(
            observations,
            replace(first, comparison_group_id=GROUP_IDS[1]),
        )
    elif case == "changed_namespace":
        corrupted = _replace_observation(
            observations,
            replace(first, namespace=f"{first.namespace}/forged"),
        )
    elif case == "changed_world":
        corrupted = _replace_observation(
            observations,
            replace(first, world_id=f"{first.world_id}/forged"),
        )
    else:
        assert case == "changed_seed"
        corrupted = _replace_observation(
            observations,
            replace(first, seed=first.seed + 1),
        )

    scoring = _ScoringSentinel()
    with pytest.raises(RunProvenanceError) as captured:
        _select_then_score(
            effects=baseline.effects,
            observations=corrupted,
            scorer=scoring,
        )

    _assert_fail_closed(captured.value, expected_error_code)
    assert scoring.entered is False
