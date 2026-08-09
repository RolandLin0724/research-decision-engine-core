from __future__ import annotations

import ast
import hashlib
import random
from dataclasses import FrozenInstanceError, replace
from functools import cache
from pathlib import Path

import pytest

from research_decision_engine.belief_models import EffectSourceKind, MatchedEffectObservation
from research_decision_engine.benchmarks.broader_calibration_history import (
    CALIBRATION_SELECTION_VERSION,
    CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
    CalibrationHistorySelection,
    RunProvenanceError,
    select_calibration_history,
)
from research_decision_engine.benchmarks.broader_calibration_selector_replay import (
    raw_effect_sha256,
    replay_calibration_history_selection,
)
from research_decision_engine.benchmarks.broader_oracle import RevealedObservation
from research_decision_engine.benchmarks.broader_protocol import (
    canonical_json_bytes,
    protocol_hash,
)
from research_decision_engine.benchmarks.broader_worlds import GROUP_IDS
from tests import p2_returned_run_architecture_guard as architecture

_RUN_ID = "p2-calibration-selector-replay/run"
_WORLD_ID = "h_adam_low"
_SEED = 9000
_FROZEN_EFFECT_PAYLOAD_SHA256 = (
    "712c02f7e5681358167512c7f769eea8318bab6ed70ab4b2f021c5d2be3ee664",
    "358f14eb861c6b016d2ae48afeed77c9f1279679c8c206d553b2fa7b7f53a0f9",
    "6b38ce4ce695d3b38bf298a145223227830c819babdbc897e1ae251501399c11",
    "42effc6c677f9923eac8f27d1f40abb6283969c5d6c7ecc9868983d55e839c3f",
    "f4aad6c13fa947007f35f0561fb3492341bb7752039cb367e9644f4d3d53286c",
)
_FROZEN_SELECTION_IDENTITY = "1233abf97595dbd4bc01a3de7fe5ec0fa19ff8903ed5ff24c1f31c3cdb30e7b3"
_HELPER_PATH = (
    Path(__file__).parents[1]
    / "research_decision_engine"
    / "benchmarks"
    / "broader_calibration_selector_replay.py"
)


@cache
def _baseline(
    world_id: str = _WORLD_ID,
    seed: int = _SEED,
    comparison_group_id: str = GROUP_IDS[0],
) -> CalibrationHistorySelection:
    return select_calibration_history(
        run_id=_RUN_ID,
        world_id=world_id,
        seed=seed,
        comparison_group_id=comparison_group_id,
    )


def _replay(
    selection: CalibrationHistorySelection,
    *,
    run_id: str = _RUN_ID,
    expected_observations: tuple[RevealedObservation, ...] | None = None,
    expected_effects: tuple[MatchedEffectObservation, ...] | None = None,
    recorded_observations: tuple[RevealedObservation, ...] | None = None,
    recorded_effects: tuple[MatchedEffectObservation, ...] | None = None,
    physical_cost: float | None = None,
    seed: int | None = None,
    source_sequence_cutoff: int = CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
) -> CalibrationHistorySelection:
    return replay_calibration_history_selection(
        run_id=run_id,
        world_id=selection.world_id,
        seed=selection.seed if seed is None else seed,
        comparison_group_id=selection.comparison_group_id,
        group_index=GROUP_IDS.index(selection.comparison_group_id),
        expected_observations=(
            selection.observations if expected_observations is None else expected_observations
        ),
        expected_effects=selection.effects if expected_effects is None else expected_effects,
        recorded_observations=recorded_observations,
        recorded_effects=recorded_effects,
        physical_cost=selection.physical_cost if physical_cost is None else physical_cost,
        source_sequence_cutoff=source_sequence_cutoff,
    )


def _assert_exact_selection(
    replayed: CalibrationHistorySelection,
    authoritative: CalibrationHistorySelection,
) -> None:
    assert replayed.scientific_identity() == authoritative.scientific_identity()
    assert replayed.current_observation_excluded is authoritative.current_observation_excluded
    assert replayed.current_effect_excluded is authoritative.current_effect_excluded
    assert replayed.future_history_excluded is authoritative.future_history_excluded
    assert replayed.effects == authoritative.effects
    assert replayed.observations == authoritative.observations
    assert replayed.selection_identity == authoritative.selection_identity


def _direct_selection(
    baseline: CalibrationHistorySelection,
    *,
    run_id: str = _RUN_ID,
    recorded_observations: tuple[RevealedObservation, ...] | None = None,
    recorded_effects: tuple[MatchedEffectObservation, ...] | None = None,
    source_sequence_cutoff: int = CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
) -> CalibrationHistorySelection:
    return select_calibration_history(
        run_id=run_id,
        world_id=baseline.world_id,
        seed=baseline.seed,
        comparison_group_id=baseline.comparison_group_id,
        recorded_observations=recorded_observations,
        recorded_effects=recorded_effects,
        source_sequence_cutoff=source_sequence_cutoff,
    )


def _extra_effect(
    baseline: CalibrationHistorySelection,
    *,
    suffix: str,
    comparison_group_id: str,
    available_sequence: int,
    source_kind: EffectSourceKind = "decision",
) -> MatchedEffectObservation:
    template = baseline.effects[0]
    return replace(
        template,
        effect_id=f"{template.effect_id}/{suffix}",
        comparison_group_id=comparison_group_id,
        available_sequence=available_sequence,
        source_kind=source_kind,
    )


def test_raw_effect_digest_is_exact_canonical_final_lf_sha256() -> None:
    effect = _baseline().effects[0]
    canonical = canonical_json_bytes(effect.to_dict(), final_lf=True)

    assert canonical.endswith(b"\n")
    assert raw_effect_sha256(effect) == hashlib.sha256(canonical).hexdigest()
    assert len(raw_effect_sha256(effect)) == 64
    assert raw_effect_sha256(effect) == raw_effect_sha256(effect)


def test_replay_matches_the_literal_frozen_raw_digest_and_selection_vectors() -> None:
    replayed = _replay(_baseline())

    assert replayed.source_effect_payload_sha256 == _FROZEN_EFFECT_PAYLOAD_SHA256
    assert replayed.selection_identity == _FROZEN_SELECTION_IDENTITY


@pytest.mark.parametrize(
    "case",
    (
        "effect_id",
        "comparison_group_id",
        "observed_effect",
        "available_sequence",
        "source_kind",
        "source_ids",
        "created_at",
    ),
)
def test_each_effect_field_mutation_changes_the_raw_digest(case: str) -> None:
    effect = _baseline().effects[0]
    if case == "effect_id":
        changed = replace(effect, effect_id=f"{effect.effect_id}/changed")
    elif case == "comparison_group_id":
        changed = replace(effect, comparison_group_id=GROUP_IDS[1])
    elif case == "observed_effect":
        changed = replace(effect, observed_effect=effect.observed_effect + 0.125)
    elif case == "available_sequence":
        changed = replace(effect, available_sequence=effect.available_sequence + 1)
    elif case == "source_kind":
        changed = replace(effect, source_kind="decision")
    elif case == "source_ids":
        changed = replace(effect, source_ids=tuple(reversed(effect.source_ids)))
    else:
        assert case == "created_at"
        changed = replace(effect, created_at=f"{effect.created_at}/changed")

    assert raw_effect_sha256(changed) != raw_effect_sha256(effect)


def test_ordered_nested_source_ids_are_not_set_or_mapping_normalized() -> None:
    effect = _baseline().effects[0]
    reversed_sources = replace(effect, source_ids=tuple(reversed(effect.source_ids)))

    assert set(reversed_sources.source_ids) == set(effect.source_ids)
    assert raw_effect_sha256(reversed_sources) != raw_effect_sha256(effect)


def test_final_lf_and_protocol_hash_are_not_raw_digest_substitutes() -> None:
    effect = _baseline().effects[0]
    without_final_lf = hashlib.sha256(
        canonical_json_bytes(effect.to_dict(), final_lf=False)
    ).hexdigest()
    framed = protocol_hash("effect-payload-test/v1", effect.to_dict())

    assert raw_effect_sha256(effect) != without_final_lf
    assert raw_effect_sha256(effect) != framed


@pytest.mark.parametrize(
    ("world_id", "seed", "comparison_group_id"),
    (
        ("h_adam_low", 9000, GROUP_IDS[0]),
        ("h_null_high", 9000, GROUP_IDS[1]),
        ("h_sgd_low", 9001, GROUP_IDS[2]),
        ("g_adam_lmh", 9000, GROUP_IDS[2]),
        ("g_null_hml", 9002, GROUP_IDS[0]),
        ("g_sgd_hml", 9003, GROUP_IDS[1]),
    ),
)
def test_replay_matches_selector_across_frozen_groups_worlds_and_seeds(
    world_id: str,
    seed: int,
    comparison_group_id: str,
) -> None:
    authoritative = _baseline(world_id, seed, comparison_group_id)
    replayed = _replay(authoritative)

    _assert_exact_selection(replayed, authoritative)
    assert replayed.source_effect_payload_sha256 == tuple(
        raw_effect_sha256(effect) for effect in authoritative.effects
    )


@pytest.mark.parametrize(
    "case",
    (
        "canonical",
        "reversed",
        "shuffled",
        "other_group_before_cutoff",
        "target_group_at_cutoff",
        "target_group_after_cutoff",
    ),
)
def test_recorded_history_filtering_and_order_match_the_selector(case: str) -> None:
    baseline = _baseline()
    observations = list(baseline.observations)
    effects = list(baseline.effects)
    if case == "reversed":
        observations.reverse()
        effects.reverse()
    elif case == "shuffled":
        random.Random(20260720).shuffle(observations)
        random.Random(20260721).shuffle(effects)
    elif case == "other_group_before_cutoff":
        effects.insert(
            2,
            _extra_effect(
                baseline,
                suffix=case,
                comparison_group_id=GROUP_IDS[1],
                available_sequence=0,
            ),
        )
    elif case == "target_group_at_cutoff":
        effects.append(
            _extra_effect(
                baseline,
                suffix=case,
                comparison_group_id=baseline.comparison_group_id,
                available_sequence=1,
            )
        )
    elif case == "target_group_after_cutoff":
        effects.insert(
            0,
            _extra_effect(
                baseline,
                suffix=case,
                comparison_group_id=baseline.comparison_group_id,
                available_sequence=2,
            ),
        )
    else:
        assert case == "canonical"

    recorded_observations = tuple(observations)
    recorded_effects = tuple(effects)
    authoritative = _direct_selection(
        baseline,
        recorded_observations=recorded_observations,
        recorded_effects=recorded_effects,
    )
    replayed = _replay(
        baseline,
        recorded_observations=recorded_observations,
        recorded_effects=recorded_effects,
    )

    _assert_exact_selection(replayed, authoritative)
    assert replayed.effects == baseline.effects
    assert replayed.observations == baseline.observations


def test_absent_recorded_history_selects_the_canonical_population() -> None:
    baseline = _baseline()

    _assert_exact_selection(_replay(baseline), _direct_selection(baseline))


@pytest.mark.parametrize(
    "case",
    (
        "empty_effect_history",
        "one_effect",
        "duplicate_effect_id",
        "extra_eligible_effect",
        "changed_effect_value",
        "decision_instead_of_calibration",
        "current_effect_replaces_prior",
        "empty_observation_history",
        "duplicate_observation_identity",
        "changed_observation_candidate",
    ),
)
def test_replay_and_selector_reject_history_corruption_with_the_same_error(case: str) -> None:
    baseline = _baseline()
    effects = baseline.effects
    observations = baseline.observations
    first_effect = effects[0]
    first_observation = observations[0]
    if case == "empty_effect_history":
        effects = ()
    elif case == "one_effect":
        effects = effects[:1]
    elif case == "duplicate_effect_id":
        effects = (*effects, first_effect)
    elif case == "extra_eligible_effect":
        effects = (
            *effects,
            _extra_effect(
                baseline,
                suffix=case,
                comparison_group_id=baseline.comparison_group_id,
                available_sequence=0,
                source_kind="calibration",
            ),
        )
    elif case == "changed_effect_value":
        effects = (
            replace(first_effect, observed_effect=first_effect.observed_effect + 1.0),
            *effects[1:],
        )
    elif case == "decision_instead_of_calibration":
        effects = (replace(first_effect, source_kind="decision"), *effects[1:])
    elif case == "current_effect_replaces_prior":
        effects = (replace(first_effect, available_sequence=1), *effects[1:])
    elif case == "empty_observation_history":
        observations = ()
    elif case == "duplicate_observation_identity":
        observations = (first_observation, first_observation, *observations[2:])
    else:
        assert case == "changed_observation_candidate"
        observations = (
            replace(first_observation, candidate_id=f"{first_observation.candidate_id}/changed"),
            *observations[1:],
        )

    with pytest.raises(RunProvenanceError) as direct_error:
        _direct_selection(
            baseline,
            recorded_observations=observations,
            recorded_effects=effects,
        )
    with pytest.raises(RunProvenanceError) as replay_error:
        _replay(
            baseline,
            recorded_observations=observations,
            recorded_effects=effects,
        )

    assert replay_error.value.error_code == direct_error.value.error_code
    assert replay_error.value.validation_layer == direct_error.value.validation_layer
    assert str(replay_error.value) == str(direct_error.value)
    assert replay_error.value.scoring_entered is False
    assert replay_error.value.scientific_output_entered is False


@pytest.mark.parametrize(
    ("run_id", "cutoff", "expected_code"),
    (
        ("", 1, "CALIBRATION_STUDY_BINDING_MISMATCH"),
        (" \t", 1, "CALIBRATION_STUDY_BINDING_MISMATCH"),
        (_RUN_ID, 0, "CALIBRATION_CUTOFF_MISMATCH"),
        ("", 2, "CALIBRATION_CUTOFF_MISMATCH"),
    ),
)
def test_replay_preserves_cutoff_before_run_binding_error_order(
    run_id: str,
    cutoff: int,
    expected_code: str,
) -> None:
    baseline = _baseline()

    with pytest.raises(RunProvenanceError) as direct_error:
        _direct_selection(baseline, run_id=run_id, source_sequence_cutoff=cutoff)
    with pytest.raises(RunProvenanceError) as replay_error:
        _replay(baseline, run_id=run_id, source_sequence_cutoff=cutoff)

    assert direct_error.value.error_code == expected_code
    assert replay_error.value.error_code == expected_code
    assert str(replay_error.value) == str(direct_error.value)


def test_equal_values_keep_distinct_effect_identity_and_canonical_order() -> None:
    baseline = _baseline()
    equal_effects = tuple(replace(effect, observed_effect=0.5) for effect in baseline.effects)
    replayed = _replay(
        baseline,
        expected_effects=equal_effects,
        recorded_effects=tuple(reversed(equal_effects)),
    )

    assert replayed.effect_values == (0.5,) * 5
    assert replayed.effects == equal_effects
    assert len(set(replayed.source_effect_ids)) == 5
    assert len(set(replayed.source_effect_payload_sha256)) == 5


def test_one_raw_digest_change_and_sequence_reordering_break_exact_parity() -> None:
    baseline = _baseline()
    authoritative = _replay(baseline)
    changed_effects = (
        replace(baseline.effects[0], created_at=f"{baseline.effects[0].created_at}/changed"),
        *baseline.effects[1:],
    )
    changed = _replay(baseline, expected_effects=changed_effects)
    reordered = _replay(baseline, expected_effects=tuple(reversed(baseline.effects)))

    assert changed.source_effect_payload_sha256[0] != authoritative.source_effect_payload_sha256[0]
    assert changed.selection_identity != authoritative.selection_identity
    assert reordered.source_effect_ids == tuple(reversed(authoritative.source_effect_ids))
    assert reordered.source_effect_payload_sha256 == tuple(
        reversed(authoritative.source_effect_payload_sha256)
    )
    assert reordered.selection_identity != authoritative.selection_identity


def test_selector_identity_uses_raw_digests_and_omits_physical_cost() -> None:
    baseline = _baseline()
    replayed = _replay(baseline)
    changed_cost = _replay(baseline, physical_cost=baseline.physical_cost + 1.0)
    framed_effects = tuple(
        protocol_hash("effect-payload-test/v1", effect.to_dict()) for effect in replayed.effects
    )

    assert framed_effects != replayed.source_effect_payload_sha256
    assert changed_cost.selection_identity == replayed.selection_identity
    assert changed_cost.scientific_identity() != replayed.scientific_identity()


def test_changing_one_identity_input_changes_the_selection_identity() -> None:
    baseline = _baseline()

    assert (
        _replay(baseline, seed=baseline.seed + 1).selection_identity != baseline.selection_identity
    )


def test_replayed_selection_is_the_existing_immutable_result_type() -> None:
    replayed = _replay(_baseline())

    assert type(replayed) is CalibrationHistorySelection
    with pytest.raises(FrozenInstanceError):
        replayed.sample_count = 6  # type: ignore[misc]


def test_helper_has_one_exact_raw_sha256_call_and_one_framed_identity_call() -> None:
    source = _HELPER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    raw_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "hashlib"
        and node.func.attr == "sha256"
    ]
    protocol_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "protocol_hash"
    ]

    assert all(
        passed for _name, passed in architecture.selector_replay_helper_architecture_checks(source)
    )
    assert len(raw_calls) == 1
    raw_argument = raw_calls[0].args[0]
    assert isinstance(raw_argument, ast.Call)
    assert isinstance(raw_argument.func, ast.Name)
    assert raw_argument.func.id == "canonical_json_bytes"
    assert len(raw_argument.args) == 1
    assert isinstance(raw_argument.args[0], ast.Call)
    assert isinstance(raw_argument.args[0].func, ast.Attribute)
    assert raw_argument.args[0].func.attr == "to_dict"
    assert [(item.arg, ast.literal_eval(item.value)) for item in raw_argument.keywords] == [
        ("final_lf", True)
    ]
    assert len(protocol_calls) == 1
    assert isinstance(protocol_calls[0].args[0], ast.Name)
    assert protocol_calls[0].args[0].id == "CALIBRATION_SELECTION_VERSION"
    assert isinstance(protocol_calls[0].args[1], ast.Name)
    assert protocol_calls[0].args[1].id == "identity_values"
    assert CALIBRATION_SELECTION_VERSION == "broader-calibration-history-selection/v1"


def test_helper_source_has_no_selector_capability_or_io_surface() -> None:
    source = _HELPER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "select_calibration_history(" not in source
    assert "broader_returned_run" not in source
    assert not called_names.intersection(
        {
            "authorize_observation",
            "reobserve_authorized_observation",
            "open",
            "exec",
            "eval",
            "compile",
            "getattr",
            "setattr",
            "run_arm",
            "protocol_hash_algorithm",
        }
    )
    assert not {"os", "subprocess", "socket", "sqlite3", "pathlib"}.intersection(
        {
            alias.name.split(".", maxsplit=1)[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
    )
