"""Semantic contract tests for the bounded Stage-2F P1 prerequisite surface."""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Callable
from dataclasses import FrozenInstanceError, fields
from dataclasses import replace as dataclass_replace
from types import FrameType
from typing import Any, Literal, cast, get_type_hints

import pytest

from research_decision_engine.belief_models import MatchedEffectObservation
from research_decision_engine.benchmarks import broader_calibration_evidence as evidence
from research_decision_engine.benchmarks.broader_calibration_evidence import (
    CalibrationCandidatePairProjection,
    StrictChronologyProjection,
    _decode_calibration_candidate_pair_projection,
    _decode_strict_chronology_projection,
    calibration_candidate_pair_id,
    strict_chronology_id,
)
from research_decision_engine.benchmarks.broader_protocol import (
    canonical_json_bytes,
    f64,
    protocol_hash,
)
from research_decision_engine.benchmarks.broader_returned_run import (
    RunMatchedEffectProjection,
    decode_run_matched_effect_projection,
)
from tests.p2_calibration_evidence_harness import (
    CALIBRATION_NAMESPACE_INDEX,
    CANONICAL_COORDINATES,
    CANONICAL_SELECTION_COUNT,
    COMPARISON_GROUP_ID_INDEX,
    EFFECT_ID_INDEX,
    EFFECT_PAYLOAD_BYTES_INDEX,
    EFFECT_PAYLOAD_SHA256_INDEX,
    EFFECT_PROJECTION_INDEX,
    EXECUTION_SPECIFICATION_ID_INDEX,
    EXECUTOR_ATTESTATION_ID_INDEX,
    ORDERED_CANDIDATE_PAIR_IDS_INDEX,
    ORDERED_CANDIDATE_PAIR_PROJECTIONS_INDEX,
    ORDERED_CANDIDATE_PAIRS_INDEX,
    ORDERED_REPLICATION_IDS_INDEX,
    ORDERED_SOURCE_EFFECT_IDS_INDEX,
    ORDERED_SOURCE_EFFECTS_INDEX,
    POSITION_INDEX,
    REPLICATION_RANKS,
    REPLICATION_RANKS_INDEX,
    ROLE_INDEX,
    ROLE_PARTITIONS,
    SEED_INDEX,
    SELECTOR_RESULT_INDEX,
    STRICT_CHRONOLOGY_ID_INDEX,
    STRICT_CHRONOLOGY_INDEX,
    STUDY_OCCURRENCES_INDEX,
    WORLD_ID_INDEX,
    EffectEvidence,
    SelectionEvidence,
    candidate_pair_mapping,
    expected_candidate_pair_id,
    expected_strict_chronology_id,
    replace_bundle_selection,
    replace_effect_evidence_at,
    replace_effect_evidence_field,
    replace_selection_field,
    replace_selector_result,
    strict_chronology_mapping,
    valid_bundle,
    with_effect_evidence,
    with_selector_result,
)

_PREDICATE_PATHS = (
    "calibration/3o.1.0/execution_attestation_binding",
    "calibration/3o.1.1/pair_candidate",
    "calibration/3o.1.2/study",
    "calibration/3o.1.3/scope",
    "calibration/3o.1.4/replication",
    "calibration/3o.1.5/effect",
    "calibration/3o.1.6/chronology",
)
_PREDICATE_CODES = (
    "CALIBRATION_EXECUTION_SPECIFICATION_MISMATCH",
    "CALIBRATION_CANDIDATE_PAIR_MISMATCH",
    "CALIBRATION_STUDY_MISMATCH",
    "CALIBRATION_SCOPE_MISMATCH",
    "CALIBRATION_REPLICATION_MISMATCH",
    "CALIBRATION_SOURCE_EFFECT_ORDER_MISMATCH",
    "CALIBRATION_CHRONOLOGY_ID_MISMATCH",
)
_PAIR_FIELDS = (
    "adam_candidate_id",
    "comparison_group_id",
    "replication_id",
    "schema_version",
    "sgd_candidate_id",
    "world_id",
)
_CHRONOLOGY_FIELDS = (
    "current_effect_excluded",
    "current_observation_excluded",
    "effect_available_sequences",
    "future_history_excluded",
    "schema_version",
    "source_sequence_cutoff",
)
_EFFECT_FIELDS = (
    "available_sequence",
    "comparison_group_id",
    "created_at",
    "effect_id",
    "observed_effect",
    "provenance",
    "source_ids",
    "source_kind",
)


class _TextSubclass(str):
    pass


class _MappingSubclass(dict[str, object]):
    pass


class _CallerHookTrap:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"caller hook was invoked for {name}")


def _alternate_h64(value: str) -> str:
    alternate = "0" * 64
    return "1" * 64 if value == alternate else alternate


def _validate(
    selections: object,
    *,
    expected_pairs: object | None = None,
    attested_specification_ids: object | None = None,
) -> evidence._ValidationOutcome:
    _, valid_pairs, valid_attested_ids = valid_bundle()
    return evidence._validate_stage2f_p1(
        selections=cast(tuple[evidence._SelectionEvidence, ...], selections),
        expected_execution_attestation_pairs=cast(
            evidence._ExecutionAttestationPairs,
            valid_pairs if expected_pairs is None else expected_pairs,
        ),
        attested_execution_specification_ids=cast(
            evidence._AttestedSpecificationIds,
            valid_attested_ids
            if attested_specification_ids is None
            else attested_specification_ids,
        ),
    )


def _expected_counts(predicate_index: int, selection_index: int) -> tuple[int, ...]:
    return tuple(
        CANONICAL_SELECTION_COUNT
        if index < predicate_index
        else selection_index + 1
        if index == predicate_index
        else 0
        for index in range(7)
    )


def _assert_failure(
    outcome: evidence._ValidationOutcome,
    *,
    predicate_index: int,
    selection_index: int = 0,
    code: str | None = None,
) -> None:
    failure, counts = outcome
    assert failure is not None
    assert failure[:3] == (
        _PREDICATE_CODES[predicate_index] if code is None else code,
        _PREDICATE_PATHS[predicate_index],
        selection_index,
    )
    role, world_id, seed, comparison_group_id = CANONICAL_COORDINATES[selection_index]
    assert failure[3].startswith(
        f"selection[{selection_index}] {role}/{world_id}/{seed}/{comparison_group_id}: "
    )
    assert counts == _expected_counts(predicate_index, selection_index)


def _replace_at(values: tuple[object, ...], index: int, value: object) -> tuple[object, ...]:
    return (*values[:index], value, *values[index + 1 :])


def _assert_selection_failure(
    selection: SelectionEvidence,
    predicate_index: int,
) -> None:
    selections = valid_bundle()[0]
    _assert_failure(
        _validate(replace_bundle_selection(selections, 0, selection)),
        predicate_index=predicate_index,
    )


def _replace_selector(
    selection: SelectionEvidence,
    **changes: object,
) -> SelectionEvidence:
    selector = replace_selector_result(selection[SELECTOR_RESULT_INDEX], **changes)
    return with_selector_result(selection, selector)


def _replace_selector_effect(
    selection: SelectionEvidence,
    effect: object,
    effect_index: int = 0,
) -> SelectionEvidence:
    effects = selection[SELECTOR_RESULT_INDEX].effects
    return _replace_selector(
        selection,
        effects=_replace_at(effects, effect_index, effect),
    )


def _replace_effect_record(
    selection: SelectionEvidence,
    record: EffectEvidence,
    effect_index: int = 0,
) -> SelectionEvidence:
    records = selection[ORDERED_SOURCE_EFFECTS_INDEX]
    return with_effect_evidence(
        selection,
        replace_effect_evidence_at(records, effect_index, record),
    )


def _replace_effect_record_field(
    selection: SelectionEvidence,
    field_index: int,
    value: object,
    effect_index: int = 0,
) -> SelectionEvidence:
    record = selection[ORDERED_SOURCE_EFFECTS_INDEX][effect_index]
    return _replace_effect_record(
        selection,
        replace_effect_evidence_field(record, field_index, value),
        effect_index,
    )


def _replace_pair_sequence(
    selection: SelectionEvidence,
    pairs: object,
) -> SelectionEvidence:
    selection = replace_selection_field(selection, ORDERED_CANDIDATE_PAIRS_INDEX, pairs)
    selector = replace_selector_result(
        selection[SELECTOR_RESULT_INDEX],
        source_candidate_pairs=pairs,
    )
    return with_selector_result(selection, selector)


def _replace_replication_ids(
    selection: SelectionEvidence,
    replication_ids: object,
) -> SelectionEvidence:
    selection = replace_selection_field(
        selection,
        ORDERED_REPLICATION_IDS_INDEX,
        replication_ids,
    )
    selector = replace_selector_result(
        selection[SELECTOR_RESULT_INDEX],
        source_replication_ids=replication_ids,
    )
    return with_selector_result(selection, selector)


def _replace_effect_ids(
    selection: SelectionEvidence,
    effect_ids: object,
) -> SelectionEvidence:
    selection = replace_selection_field(
        selection,
        ORDERED_SOURCE_EFFECT_IDS_INDEX,
        effect_ids,
    )
    selector = replace_selector_result(
        selection[SELECTOR_RESULT_INDEX],
        source_effect_ids=effect_ids,
    )
    return with_selector_result(selection, selector)


def _replace_carried_effect_id(
    selection: SelectionEvidence,
    effect_index: int,
    effect_id: str,
    *,
    ordered_occurrence: bool = True,
    record_occurrence: bool = True,
    selector_occurrence: bool = True,
) -> SelectionEvidence:
    if ordered_occurrence:
        selection = replace_selection_field(
            selection,
            ORDERED_SOURCE_EFFECT_IDS_INDEX,
            _replace_at(
                selection[ORDERED_SOURCE_EFFECT_IDS_INDEX],
                effect_index,
                effect_id,
            ),
        )
    if record_occurrence:
        selection = _replace_effect_record_field(
            selection,
            EFFECT_ID_INDEX,
            effect_id,
            effect_index,
        )
    if selector_occurrence:
        selector = selection[SELECTOR_RESULT_INDEX]
        selection = _replace_selector(
            selection,
            source_effect_ids=_replace_at(
                selector.source_effect_ids,
                effect_index,
                effect_id,
            ),
        )
    return selection


def _replace_decoded_effect_id(
    selection: SelectionEvidence,
    effect_index: int,
    effect_id: str,
) -> SelectionEvidence:
    projection = selection[ORDERED_SOURCE_EFFECTS_INDEX][effect_index][EFFECT_PROJECTION_INDEX]
    return _replace_effect_record_field(
        selection,
        EFFECT_PROJECTION_INDEX,
        dataclass_replace(projection, effect_id=effect_id),
        effect_index,
    )


def _replace_decoded_effect_id_with_coherent_payload(
    selection: SelectionEvidence,
    effect_index: int,
    effect_id: str,
) -> SelectionEvidence:
    selector = selection[SELECTOR_RESULT_INDEX]
    changed_effect = dataclass_replace(selector.effects[effect_index], effect_id=effect_id)
    payload_bytes = canonical_json_bytes(changed_effect.to_dict(), final_lf=True)
    payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
    record = selection[ORDERED_SOURCE_EFFECTS_INDEX][effect_index]
    changed_record = (
        record[EFFECT_ID_INDEX],
        payload_bytes,
        payload_sha256,
        dataclass_replace(record[EFFECT_PROJECTION_INDEX], effect_id=effect_id),
    )
    selection = _replace_effect_record(selection, changed_record, effect_index)
    return _replace_selector(
        selection,
        source_effect_payload_sha256=_replace_at(
            selector.source_effect_payload_sha256,
            effect_index,
            payload_sha256,
        ),
    )


def _replace_chronology_field(
    selection: SelectionEvidence,
    field_name: str,
    value: object,
) -> SelectionEvidence:
    chronology = selection[STRICT_CHRONOLOGY_INDEX]
    return replace_selection_field(
        selection,
        STRICT_CHRONOLOGY_INDEX,
        _unsafe_chronology(chronology, field_name, value),
    )


def _replace_chronology_effect_relation(
    selection: SelectionEvidence,
) -> SelectionEvidence:
    projection = selection[ORDERED_SOURCE_EFFECTS_INDEX][0][EFFECT_PROJECTION_INDEX]
    return _replace_effect_record_field(
        selection,
        EFFECT_PROJECTION_INDEX,
        dataclass_replace(projection, available_sequence=1),
    )


def _replace_raw_provenance_value(
    effect: MatchedEffectObservation,
    key: str,
    value: object,
) -> MatchedEffectObservation:
    details = cast(
        tuple[tuple[str, str | int | float | bool | None], ...],
        tuple(
            (name, value if name == key else original)
            for name, original in effect.provenance.details
        ),
    )
    return dataclass_replace(
        effect,
        provenance=dataclass_replace(effect.provenance, details=details),
    )


def _unsafe_chronology(
    projection: StrictChronologyProjection,
    field_name: str,
    value: object,
) -> StrictChronologyProjection:
    changed = object.__new__(StrictChronologyProjection)
    for field in fields(StrictChronologyProjection):
        object.__setattr__(changed, field.name, getattr(projection, field.name))
    object.__setattr__(changed, field_name, value)
    return changed


@pytest.mark.parametrize(
    ("projection_type", "field_names", "expected_hints"),
    (
        pytest.param(
            CalibrationCandidatePairProjection,
            _PAIR_FIELDS,
            {
                "adam_candidate_id": str,
                "comparison_group_id": str,
                "replication_id": str,
                "schema_version": Literal["broader-replication-calibration-candidate-pair/v1"],
                "sgd_candidate_id": str,
                "world_id": str,
            },
            id="candidate-pair",
        ),
        pytest.param(
            StrictChronologyProjection,
            _CHRONOLOGY_FIELDS,
            {
                "current_effect_excluded": Literal[True],
                "current_observation_excluded": Literal[True],
                "effect_available_sequences": tuple[int, int, int, int, int],
                "future_history_excluded": Literal[True],
                "schema_version": Literal["broader-replication-calibration-chronology/v1"],
                "source_sequence_cutoff": Literal[1],
            },
            id="strict-chronology",
        ),
    ),
)
def test_projection_surface_is_exact_frozen_slotted_and_typed(
    projection_type: Any,
    field_names: tuple[str, ...],
    expected_hints: dict[str, object],
) -> None:
    assert tuple(field.name for field in fields(projection_type)) == field_names
    assert tuple(projection_type.__slots__) == field_names
    assert projection_type.__dataclass_params__.frozen is True
    assert get_type_hints(projection_type) == expected_hints
    instance = (
        valid_bundle()[0][0][ORDERED_CANDIDATE_PAIR_PROJECTIONS_INDEX][0]
        if projection_type is CalibrationCandidatePairProjection
        else valid_bundle()[0][0][STRICT_CHRONOLOGY_INDEX]
    )
    assert not hasattr(instance, "__dict__")
    with pytest.raises(FrozenInstanceError):
        setattr(instance, field_names[0], getattr(instance, field_names[0]))


@pytest.mark.parametrize("projection_kind", ("candidate-pair", "strict-chronology"))
def test_projection_mapping_decoder_and_identity_round_trip_exactly(
    projection_kind: str,
) -> None:
    selection = valid_bundle()[0][0]
    if projection_kind == "candidate-pair":
        projection = selection[ORDERED_CANDIDATE_PAIR_PROJECTIONS_INDEX][0]
        mapping = candidate_pair_mapping(projection)
        decoded = _decode_calibration_candidate_pair_projection(mapping)
        identity = calibration_candidate_pair_id(projection)
        assert tuple(mapping) == _PAIR_FIELDS
        assert decoded == projection
        assert identity == ("4f5fb48af3814f4af3b2b9dcf7c39856bc011511a43c864ca5ce54b9906b7f46")
        assert identity == protocol_hash(
            "validation_evidence_calibration_candidate_pair/v1",
            mapping,
        )
    else:
        chronology = selection[STRICT_CHRONOLOGY_INDEX]
        chronology_mapping = strict_chronology_mapping(chronology)
        decoded_chronology = _decode_strict_chronology_projection(chronology_mapping)
        chronology_identity = strict_chronology_id(chronology)
        assert tuple(chronology_mapping) == _CHRONOLOGY_FIELDS
        assert decoded_chronology == chronology
        assert chronology_identity == (
            "e125d753418ca2c022fcaeace0d6a26c204f9a2f99f2761796727da3d4a83c5b"
        )
        assert chronology_identity == protocol_hash(
            "validation_evidence_calibration_chronology/v1",
            chronology_mapping,
        )


@pytest.mark.parametrize(
    "projection_kind",
    ("candidate-pair", "strict-chronology"),
    ids=("test-owned-pair-vector", "test-owned-chronology-vector"),
)
def test_test_owned_expected_identity_has_an_independent_fixed_vector(
    projection_kind: str,
) -> None:
    selection = valid_bundle()[0][0]
    if projection_kind == "candidate-pair":
        projection = selection[ORDERED_CANDIDATE_PAIR_PROJECTIONS_INDEX][0]
        assert expected_candidate_pair_id(projection) == (
            "4f5fb48af3814f4af3b2b9dcf7c39856bc011511a43c864ca5ce54b9906b7f46"
        )
    else:
        chronology = selection[STRICT_CHRONOLOGY_INDEX]
        assert expected_strict_chronology_id(chronology) == (
            "e125d753418ca2c022fcaeace0d6a26c204f9a2f99f2761796727da3d4a83c5b"
        )


def test_candidate_pair_constructor_rejects_every_nonclosed_runtime_shape() -> None:
    projection = valid_bundle()[0][0][ORDERED_CANDIDATE_PAIR_PROJECTIONS_INDEX][0]
    base = candidate_pair_mapping(projection)
    invalid_changes = (
        ("adam_candidate_id", ""),
        ("adam_candidate_id", "bad candidate"),
        ("adam_candidate_id", "e\u0301"),
        ("comparison_group_id", _TextSubclass("group-00")),
        ("replication_id", 1),
        ("schema_version", "broader-replication-calibration-candidate-pair/v2"),
        ("sgd_candidate_id", True),
        ("world_id", object()),
    )
    for field_name, value in invalid_changes:
        changed = {**base, field_name: value}
        with pytest.raises((TypeError, ValueError)):
            CalibrationCandidatePairProjection(**changed)  # type: ignore[arg-type]
    missing = dict(base)
    missing.pop("world_id")
    with pytest.raises(TypeError):
        CalibrationCandidatePairProjection(**missing)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        CalibrationCandidatePairProjection(  # type: ignore[call-arg]
            **base,  # type: ignore[arg-type]
            unknown="value",
        )

    class _PairSubclass(CalibrationCandidatePairProjection):
        pass

    with pytest.raises(ValueError):
        _PairSubclass(**base)  # type: ignore[arg-type]


def test_chronology_constructor_rejects_bool_int_float_and_container_substitution() -> None:
    chronology = valid_bundle()[0][0][STRICT_CHRONOLOGY_INDEX]
    base = strict_chronology_mapping(chronology)
    invalid_changes = (
        ("current_effect_excluded", False),
        ("current_effect_excluded", 1),
        ("current_observation_excluded", False),
        ("effect_available_sequences", [0, 0, 0, 0, 0]),
        ("effect_available_sequences", (0, 0, 0, 0)),
        ("effect_available_sequences", (0, 0, True, 0, 0)),
        ("effect_available_sequences", (0, 0, 1, 0, 0)),
        ("future_history_excluded", False),
        ("schema_version", "broader-replication-calibration-chronology/v2"),
        ("source_sequence_cutoff", True),
        ("source_sequence_cutoff", 1.0),
        ("source_sequence_cutoff", 2),
    )
    for field_name, value in invalid_changes:
        changed = {**base, field_name: value}
        with pytest.raises((TypeError, ValueError)):
            StrictChronologyProjection(**changed)  # type: ignore[arg-type]

    class _ChronologySubclass(StrictChronologyProjection):
        pass

    with pytest.raises(ValueError):
        _ChronologySubclass(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize("projection_kind", ("candidate-pair", "strict-chronology"))
def test_closed_decoders_reject_missing_extra_reordered_proxy_and_substitution(
    projection_kind: str,
) -> None:
    selection = valid_bundle()[0][0]
    mapping: dict[str, object]
    decoder: Callable[[object], object]
    if projection_kind == "candidate-pair":
        pair_projection = selection[ORDERED_CANDIDATE_PAIR_PROJECTIONS_INDEX][0]
        mapping = candidate_pair_mapping(pair_projection)
        decoder = _decode_calibration_candidate_pair_projection
        substitute_field = "replication_id"
        substitute_value: object = 1
    else:
        chronology = selection[STRICT_CHRONOLOGY_INDEX]
        mapping = strict_chronology_mapping(chronology)
        decoder = _decode_strict_chronology_projection
        substitute_field = "effect_available_sequences"
        substitute_value = [0, 0, 0, 0, 0]

    missing = dict(mapping)
    missing.pop(tuple(mapping)[0])
    extra = {**mapping, "unknown": "value"}
    reordered = dict(reversed(tuple(mapping.items())))
    substituted = {**mapping, substitute_field: substitute_value}
    invalid = (missing, extra, reordered, _MappingSubclass(mapping), substituted)
    for value in invalid:
        with pytest.raises(ValueError):
            decoder(value)
    with pytest.raises(ValueError):
        decoder(tuple(mapping.items()))


@pytest.mark.parametrize("projection_kind", ("candidate-pair", "strict-chronology"))
def test_identity_boundary_rejects_wrong_exact_type_without_caller_hooks(
    projection_kind: str,
) -> None:
    identity = (
        calibration_candidate_pair_id
        if projection_kind == "candidate-pair"
        else strict_chronology_id
    )
    for invalid in (object(), {}, _CallerHookTrap()):
        with pytest.raises(ValueError):
            identity(invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize("projection_kind", ("candidate-pair", "strict-chronology"))
def test_every_projection_field_is_identity_sensitive(projection_kind: str) -> None:
    selection = valid_bundle()[0][0]
    if projection_kind == "candidate-pair":
        pair_projection = selection[ORDERED_CANDIDATE_PAIR_PROJECTIONS_INDEX][0]
        mapping = candidate_pair_mapping(pair_projection)
        domain = "validation_evidence_calibration_candidate_pair/v1"
        alternates: dict[str, object] = {
            "adam_candidate_id": "cal-00-adam-r0002",
            "comparison_group_id": "group-01",
            "replication_id": "calibration-00-r0002",
            "schema_version": "broader-replication-calibration-candidate-pair/v2",
            "sgd_candidate_id": "cal-00-sgd-r0002",
            "world_id": "h_null_high",
        }
    else:
        chronology = selection[STRICT_CHRONOLOGY_INDEX]
        mapping = strict_chronology_mapping(chronology)
        domain = "validation_evidence_calibration_chronology/v1"
        alternates = {
            "current_effect_excluded": False,
            "current_observation_excluded": False,
            "effect_available_sequences": (0, 0, 0, 0, 1),
            "future_history_excluded": False,
            "schema_version": "broader-replication-calibration-chronology/v2",
            "source_sequence_cutoff": 2,
        }
    baseline = protocol_hash(domain, mapping)
    assert tuple(alternates) == tuple(mapping)
    for field_name, value in alternates.items():
        changed = {**mapping, field_name: value}
        assert protocol_hash(domain, changed) != baseline


@pytest.mark.parametrize(
    ("role", "start", "end"),
    ROLE_PARTITIONS,
    ids=lambda value: str(value),
)
def test_canonical_role_partition_has_exact_count_and_contiguous_positions(
    role: str,
    start: int,
    end: int,
) -> None:
    selections = valid_bundle()[0]
    assert end - start in (96, 63)
    assert tuple(selection[ROLE_INDEX] for selection in selections[start:end]) == (role,) * (
        end - start
    )
    assert tuple(selection[POSITION_INDEX] for selection in selections[start:end]) == tuple(
        range(start, end)
    )


def test_canonical_coordinate_boundaries_fix_world_seed_group_and_role_order() -> None:
    expected = {
        0: ("primary_smoke", "h_adam_low", 9000, "group-00"),
        95: ("primary_smoke", "d3_adam", 9003, "group-02"),
        96: ("altered_order_replay", "h_adam_low", 9000, "group-00"),
        191: ("altered_order_replay", "d3_adam", 9003, "group-02"),
        192: ("fixture_primary", "g_sgd_hml", 1000, "group-00"),
        254: ("fixture_primary", "d3_adam", 1000, "group-02"),
        255: ("fixture_replay", "g_sgd_hml", 1000, "group-00"),
        317: ("fixture_replay", "d3_adam", 1000, "group-02"),
    }
    selections = valid_bundle()[0]
    for index, coordinate in expected.items():
        role, world_id, seed, comparison_group_id = coordinate
        selection = selections[index]
        assert (
            selection[ROLE_INDEX],
            selection[WORLD_ID_INDEX],
            selection[SEED_INDEX],
            selection[COMPARISON_GROUP_ID_INDEX],
        ) == (role, world_id, seed, comparison_group_id)


def test_all_318_selection_records_match_the_independent_canonical_coordinate_table() -> None:
    selections = valid_bundle()[0]
    assert len(selections) == CANONICAL_SELECTION_COUNT
    assert (
        tuple(
            (
                selection[ROLE_INDEX],
                selection[WORLD_ID_INDEX],
                selection[SEED_INDEX],
                selection[COMPARISON_GROUP_ID_INDEX],
            )
            for selection in selections
        )
        == CANONICAL_COORDINATES
    )


def test_minimal_valid_bundle_completes_every_predicate_for_all_318_selections() -> None:
    selections, expected_pairs, attested_ids = valid_bundle()
    assert evidence._validate_stage2f_p1(
        selections=selections,
        expected_execution_attestation_pairs=expected_pairs,
        attested_execution_specification_ids=attested_ids,
    ) == (None, (318, 318, 318, 318, 318, 318, 318))


@pytest.mark.parametrize(
    "case",
    ("missing", "extra", "duplicate", "reversed", "list-substitute"),
    ids=("missing", "extra", "duplicate", "same-set-reversed", "list-substitute"),
)
def test_bundle_rejects_noncanonical_count_duplicate_order_and_container(case: str) -> None:
    selections = valid_bundle()[0]
    expected_counts: tuple[int, ...]
    if case == "missing":
        changed: object = selections[:-1]
        expected_stage, expected_index = 3, 0
        expected_counts = (0, 0, 0, 0, 0, 0, 0)
    elif case == "extra":
        changed = (*selections, selections[-1])
        expected_stage, expected_index = 3, 0
        expected_counts = (0, 0, 0, 0, 0, 0, 0)
    elif case == "list-substitute":
        changed = list(selections)
        expected_stage, expected_index = 3, 0
        expected_counts = (0, 0, 0, 0, 0, 0, 0)
    elif case == "duplicate":
        changed = replace_bundle_selection(selections, 1, selections[0])
        expected_stage, expected_index = 3, 1
        expected_counts = _expected_counts(expected_stage, expected_index)
    else:
        changed = tuple(reversed(selections))
        expected_stage, expected_index = 3, 0
        expected_counts = _expected_counts(expected_stage, expected_index)

    failure, counts = _validate(changed)
    assert failure is not None
    assert failure[:3] == (
        "CALIBRATION_SCOPE_MISMATCH",
        _PREDICATE_PATHS[3],
        expected_index,
    )
    assert counts == expected_counts


@pytest.mark.parametrize(
    ("case", "code"),
    (
        ("specification-only", "CALIBRATION_EXECUTION_SPECIFICATION_MISMATCH"),
        ("attestation-only", "CALIBRATION_EXECUTOR_ATTESTATION_MISMATCH"),
        ("both", "CALIBRATION_EXECUTION_ATTESTATION_PAIR_MISMATCH"),
        ("attested-pair-relation", "CALIBRATION_EXECUTION_ATTESTATION_PAIR_MISMATCH"),
    ),
    ids=("specification-only", "attestation-only", "both", "pair-relation"),
)
def test_3o_1_0_execution_attestation_partition_is_mutually_exclusive(
    case: str,
    code: str,
) -> None:
    selections, _, attested_ids = valid_bundle()
    selection = selections[0]
    if case in {"specification-only", "both"}:
        selection = replace_selection_field(
            selection,
            EXECUTION_SPECIFICATION_ID_INDEX,
            _alternate_h64(selection[EXECUTION_SPECIFICATION_ID_INDEX]),
        )
    if case in {"attestation-only", "both"}:
        selection = replace_selection_field(
            selection,
            EXECUTOR_ATTESTATION_ID_INDEX,
            _alternate_h64(selection[EXECUTOR_ATTESTATION_ID_INDEX]),
        )
    changed_attested: object = attested_ids
    if case == "attested-pair-relation":
        changed_attested = (
            _alternate_h64(attested_ids[0]),
            *attested_ids[1:],
        )
    outcome = _validate(
        replace_bundle_selection(selections, 0, selection),
        attested_specification_ids=changed_attested,
    )
    _assert_failure(outcome, predicate_index=0, code=code)


@pytest.mark.parametrize(
    "case",
    (
        "count-and-container-shapes",
        "swapped-arms",
        "malformed-candidate",
        "wrong-group",
        "duplicate-pair",
        "reordered-pairs",
        "forged-projection",
        "forged-id",
    ),
    ids=(
        "count-and-container-shapes",
        "swapped-arms",
        "malformed-candidate",
        "wrong-group",
        "duplicate",
        "same-set-reordered",
        "projection",
        "identity",
    ),
)
def test_3o_1_1_rejects_pair_count_order_parser_scope_projection_and_id(case: str) -> None:
    selections = valid_bundle()[0]
    original = selections[0]
    pairs = original[ORDERED_CANDIDATE_PAIRS_INDEX]
    if case == "count-and-container-shapes":
        for invalid in (pairs[:-1], (*pairs, pairs[0]), list(pairs)):
            changed = _replace_pair_sequence(original, invalid)
            _assert_selection_failure(changed, 1)
        return
    if case == "swapped-arms":
        changed_pairs = (tuple(reversed(pairs[0])), *pairs[1:])
        changed = _replace_pair_sequence(original, changed_pairs)
    elif case == "malformed-candidate":
        changed_pairs = (("malformed", pairs[0][1]), *pairs[1:])
        changed = _replace_pair_sequence(original, changed_pairs)
    elif case == "wrong-group":
        changed_pairs = (
            ("cal-01-adam-r0001", "cal-01-sgd-r0001"),
            *pairs[1:],
        )
        changed = _replace_pair_sequence(original, changed_pairs)
    elif case == "duplicate-pair":
        changed_pairs = (pairs[0], pairs[0], *pairs[2:])
        changed = _replace_pair_sequence(original, changed_pairs)
    elif case == "reordered-pairs":
        changed_pairs = tuple(reversed(pairs))
        changed = _replace_pair_sequence(original, changed_pairs)
    elif case == "forged-projection":
        projections = original[ORDERED_CANDIDATE_PAIR_PROJECTIONS_INDEX]
        forged = dataclass_replace(projections[0], world_id="h_null_high")
        changed = replace_selection_field(
            original,
            ORDERED_CANDIDATE_PAIR_PROJECTIONS_INDEX,
            (forged, *projections[1:]),
        )
    else:
        pair_ids = original[ORDERED_CANDIDATE_PAIR_IDS_INDEX]
        changed = replace_selection_field(
            original,
            ORDERED_CANDIDATE_PAIR_IDS_INDEX,
            (_alternate_h64(pair_ids[0]), *pair_ids[1:]),
        )
    _assert_selection_failure(changed, 1)


@pytest.mark.parametrize(
    "case",
    ("malformed-occurrences", "authority", "execution", "selector", "smoke"),
)
def test_3o_1_2_rejects_each_study_occurrence_in_frozen_order(case: str) -> None:
    selections = valid_bundle()[0]
    selection = selections[0]
    studies = selection[STUDY_OCCURRENCES_INDEX]
    if case == "malformed-occurrences":
        changed = replace_selection_field(
            selection,
            STUDY_OCCURRENCES_INDEX,
            studies[:-1],
        )
    elif case == "selector":
        changed = _replace_selector(selection, study_id="e\u0301")
    else:
        occurrence_index = {"authority": 0, "execution": 1, "smoke": 2}[case]
        changed_studies = _replace_at(studies, occurrence_index, "wrong-study/v1")
        changed = replace_selection_field(
            selection,
            STUDY_OCCURRENCES_INDEX,
            changed_studies,
        )
    _assert_selection_failure(changed, 2)


@pytest.mark.parametrize(
    "case",
    (
        "namespace-occurrences",
        "group-occurrences",
        "seed",
        "world",
        "effect-group",
        "effect-world",
        "canonical-position-and-role",
    ),
    ids=(
        "namespace",
        "comparison-group",
        "seed",
        "world",
        "effect-group",
        "effect-world-provenance",
        "canonical-role-position",
    ),
)
def test_3o_1_3_rejects_every_scope_occurrence_and_canonical_position(case: str) -> None:
    selections, expected_pairs, _ = valid_bundle()
    original = selections[0]
    variants: tuple[SelectionEvidence, ...]
    if case == "namespace-occurrences":
        variants = (
            replace_selection_field(
                original,
                CALIBRATION_NAMESPACE_INDEX,
                "rde.broader.other/v1",
            ),
            _replace_selector(original, namespace="rde.broader.other/v1"),
        )
    elif case == "group-occurrences":
        variants = (
            _replace_selector(original, comparison_group_id="group-01"),
            _replace_selector(original, target_comparison_group_id="group-01"),
        )
    elif case == "seed":
        variants = (_replace_selector(original, seed=9001),)
    elif case == "world":
        variants = (_replace_selector(original, world_id="h_null_high"),)
    elif case == "effect-group":
        selector = original[SELECTOR_RESULT_INDEX]
        changed_effect = dataclass_replace(
            selector.effects[0],
            comparison_group_id="group-01",
        )
        variants = (_replace_selector_effect(original, changed_effect),)
    elif case == "effect-world":
        selector = original[SELECTOR_RESULT_INDEX]
        effects = selector.effects
        changed_effect = _replace_raw_provenance_value(
            effects[0],
            "world_id",
            "h_null_high",
        )
        variants = (_replace_selector_effect(original, changed_effect),)
    else:
        wrong_position = replace_selection_field(original, POSITION_INDEX, 1)
        wrong_role = replace_selection_field(
            replace_selection_field(
                replace_selection_field(
                    original,
                    ROLE_INDEX,
                    "altered_order_replay",
                ),
                EXECUTION_SPECIFICATION_ID_INDEX,
                expected_pairs[1][0],
            ),
            EXECUTOR_ATTESTATION_ID_INDEX,
            expected_pairs[1][1],
        )
        variants = (wrong_position, wrong_role)
    for changed in variants:
        _assert_selection_failure(changed, 3)


@pytest.mark.parametrize(
    "case",
    (
        "id-count-shapes",
        "id-duplicate",
        "id-reordered",
        "id-non-string",
        "rank-bool",
        "rank-float",
        "rank-order",
        "observation-replication",
        "selector-effect-replication",
    ),
    ids=(
        "id-count-shapes",
        "id-duplicate",
        "id-reordered",
        "id-not-integer-rank",
        "rank-bool",
        "rank-float",
        "rank-order",
        "observation",
        "selector-effect",
    ),
)
def test_3o_1_4_rejects_replication_id_rank_pair_observation_and_effect_faults(
    case: str,
) -> None:
    selections = valid_bundle()[0]
    original = selections[0]
    replication_ids = original[ORDERED_REPLICATION_IDS_INDEX]
    if case == "id-count-shapes":
        for invalid in (replication_ids[:-1], (*replication_ids, replication_ids[0])):
            changed = _replace_replication_ids(original, invalid)
            _assert_selection_failure(changed, 4)
        return
    if case == "id-duplicate":
        changed = _replace_replication_ids(
            original,
            (replication_ids[0], replication_ids[0], *replication_ids[2:]),
        )
    elif case == "id-reordered":
        changed = _replace_replication_ids(original, tuple(reversed(replication_ids)))
    elif case == "id-non-string":
        changed = _replace_replication_ids(original, (1, *replication_ids[1:]))
    elif case in {"rank-bool", "rank-float", "rank-order"}:
        ranks: object
        if case == "rank-bool":
            ranks = (True, 2, 3, 4, 5)
        elif case == "rank-float":
            ranks = (1.0, 2, 3, 4, 5)
        else:
            ranks = tuple(reversed(REPLICATION_RANKS))
        changed = replace_selection_field(original, REPLICATION_RANKS_INDEX, ranks)
    elif case == "observation-replication":
        selector = original[SELECTOR_RESULT_INDEX]
        observations = selector.observations
        observation = dataclass_replace(
            observations[0],
            replication_id="calibration-00-r0002",
        )
        changed = _replace_selector(
            original,
            observations=(observation, *observations[1:]),
        )
    else:
        selector = original[SELECTOR_RESULT_INDEX]
        effects = selector.effects
        changed_effect = _replace_raw_provenance_value(
            effects[0],
            "replication_id",
            "calibration-00-r0002",
        )
        changed = _replace_selector_effect(original, changed_effect)
    _assert_selection_failure(changed, 4)


def test_valid_effect_payloads_have_exact_field_order_lf_raw_digest_and_value() -> None:
    selection = valid_bundle()[0][0]
    selector = selection[SELECTOR_RESULT_INDEX]
    records = selection[ORDERED_SOURCE_EFFECTS_INDEX]
    assert tuple(field.name for field in fields(RunMatchedEffectProjection)) == _EFFECT_FIELDS
    for index, record in enumerate(records):
        effect_id, payload_bytes, digest, projection = record
        effect = selector.effects[index]
        assert effect_id == effect.effect_id == selector.source_effect_ids[index]
        assert payload_bytes.endswith(b"\n") and not payload_bytes.endswith(b"\n\n")
        assert payload_bytes == canonical_json_bytes(effect.to_dict(), final_lf=True)
        assert digest == hashlib.sha256(payload_bytes).hexdigest()
        assert digest == selector.source_effect_payload_sha256[index]
        assert projection.observed_effect == f64(effect.observed_effect)
        assert selector.effect_values[index] == effect.observed_effect
        assert projection.provenance.method == effect.provenance.method
        assert projection.provenance.version == effect.provenance.version


@pytest.mark.parametrize(
    "case",
    (
        "count-shapes",
        "duplicate-id",
        "reordered-ids",
        "final-lf",
        "noncanonical-bytes",
        "raw-digest",
        "projection-fields",
        "selector-effect",
        "selector-value",
    ),
    ids=(
        "five-counts",
        "duplicate-id",
        "same-set-reordered",
        "final-lf",
        "noncanonical-bytes",
        "raw-sha256",
        "eight-field-projection",
        "selector-effect",
        "effect-value",
    ),
)
def test_3o_1_5_rejects_effect_count_order_bytes_digest_projection_and_value(
    case: str,
) -> None:
    selections = valid_bundle()[0]
    original = selections[0]
    selector = original[SELECTOR_RESULT_INDEX]
    records = original[ORDERED_SOURCE_EFFECTS_INDEX]
    effect_ids = original[ORDERED_SOURCE_EFFECT_IDS_INDEX]
    if case == "count-shapes":
        variants = (
            replace_selection_field(
                original,
                ORDERED_SOURCE_EFFECT_IDS_INDEX,
                effect_ids[:-1],
            ),
            _replace_selector(original, source_effect_ids=selector.source_effect_ids[:-1]),
            _replace_selector(
                original,
                source_effect_payload_sha256=selector.source_effect_payload_sha256[:-1],
            ),
            _replace_selector(original, effect_values=selector.effect_values[:-1]),
            with_effect_evidence(original, records[:-1]),
            with_effect_evidence(original, (*records, records[0])),
        )
        for changed in variants:
            _assert_selection_failure(changed, 5)
        return
    if case == "duplicate-id":
        duplicate_ids = (effect_ids[0], effect_ids[0], *effect_ids[2:])
        changed = _replace_effect_ids(original, duplicate_ids)
        duplicate_record = replace_effect_evidence_field(
            records[1],
            EFFECT_ID_INDEX,
            effect_ids[0],
        )
        changed = _replace_effect_record(changed, duplicate_record, 1)
    elif case == "reordered-ids":
        changed = _replace_effect_ids(original, tuple(reversed(effect_ids)))
    elif case == "final-lf":
        for payload in (
            records[0][EFFECT_PAYLOAD_BYTES_INDEX][:-1],
            records[0][EFFECT_PAYLOAD_BYTES_INDEX] + b"\n",
        ):
            changed = _replace_effect_record_field(
                original,
                EFFECT_PAYLOAD_BYTES_INDEX,
                payload,
            )
            _assert_selection_failure(changed, 5)
        return
    elif case == "noncanonical-bytes":
        payload = records[0][EFFECT_PAYLOAD_BYTES_INDEX]
        changed_payload = b"{ " + payload[1:]
        record = replace_effect_evidence_field(
            replace_effect_evidence_field(
                records[0],
                EFFECT_PAYLOAD_BYTES_INDEX,
                changed_payload,
            ),
            EFFECT_PAYLOAD_SHA256_INDEX,
            hashlib.sha256(changed_payload).hexdigest(),
        )
        changed = _replace_effect_record(original, record)
    elif case == "raw-digest":
        record = replace_effect_evidence_field(
            records[0],
            EFFECT_PAYLOAD_SHA256_INDEX,
            protocol_hash(
                "incorrect-framed-raw-effect/v1",
                {"effect_id": effect_ids[0]},
            ),
        )
        changed = _replace_effect_record(original, record)
    elif case == "projection-fields":
        projection = records[0][EFFECT_PROJECTION_INDEX]
        replacements = (
            dataclass_replace(projection, available_sequence=1),
            dataclass_replace(projection, created_at=f"{projection.created_at}-wrong"),
            dataclass_replace(projection, effect_id=f"{projection.effect_id}-wrong"),
            dataclass_replace(projection, observed_effect=f64(99.0)),
            dataclass_replace(
                projection,
                provenance=dataclass_replace(
                    projection.provenance,
                    method=f"{projection.provenance.method}-wrong",
                ),
            ),
            dataclass_replace(projection, source_ids=tuple(reversed(projection.source_ids))),
            dataclass_replace(projection, source_kind="decision"),
        )
        for replacement in replacements:
            changed = _replace_effect_record_field(
                original,
                EFFECT_PROJECTION_INDEX,
                replacement,
            )
            _assert_selection_failure(changed, 5)
        return
    elif case == "selector-effect":
        effects = selector.effects
        changed_effect = dataclass_replace(
            effects[0],
            observed_effect=effects[0].observed_effect + 0.25,
        )
        changed = _replace_selector_effect(original, changed_effect)
    else:
        changed = _replace_selector(
            original,
            effect_values=(
                selector.effect_values[0] + 0.25,
                *selector.effect_values[1:],
            ),
        )
    _assert_selection_failure(changed, 5)


def test_3o_1_5_accepts_every_carried_id_bound_to_the_decoded_projection() -> None:
    selections = valid_bundle()[0]
    failure, counts = _validate(selections)
    assert failure is None
    assert counts == (318, 318, 318, 318, 318, 318, 318)
    for selection in selections:
        selector = selection[SELECTOR_RESULT_INDEX]
        for effect_index, record in enumerate(selection[ORDERED_SOURCE_EFFECTS_INDEX]):
            decoded = decode_run_matched_effect_projection(
                evidence._effect_projection_mapping(record[EFFECT_PROJECTION_INDEX])
            )
            assert (
                selection[ORDERED_SOURCE_EFFECT_IDS_INDEX][effect_index]
                == record[EFFECT_ID_INDEX]
                == selector.source_effect_ids[effect_index]
                == decoded.effect_id
            )


@pytest.mark.parametrize(
    "case",
    (
        "all-carried-foreign",
        "ordered-occurrence-foreign",
        "record-occurrence-foreign",
        "selector-occurrence-foreign",
        "two-carried-agree",
        "decoded-projection-foreign",
        "decoded-projection-coherent-rehash",
        "another-replication-carried-id",
        "another-group-carried-id",
        "same-five-ids-reordered",
        "duplicate-decoded-effect-id",
        "coherent-foreign-later-selection",
    ),
    ids=(
        "coherent-three-occurrence-foreign-id",
        "first-carried-occurrence",
        "second-carried-occurrence",
        "third-carried-occurrence",
        "two-carried-occurrences-agree",
        "decoded-effect-id-only",
        "decoded-effect-id-coherent-payload-digest",
        "cross-replication-carried-id",
        "cross-group-carried-id",
        "canonical-id-order",
        "duplicate-decoded-effect-id",
        "later-canonical-selection",
    ),
)
def test_3o_1_5_binds_each_carried_effect_id_to_the_decoded_projection(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selections = valid_bundle()[0]
    selection_index = 17 if case == "coherent-foreign-later-selection" else 0
    original = selections[selection_index]
    effect_ids = original[ORDERED_SOURCE_EFFECT_IDS_INDEX]
    foreign_id = "foreign-effect-id"
    if case in {"all-carried-foreign", "coherent-foreign-later-selection"}:
        changed = _replace_carried_effect_id(original, 0, foreign_id)
    elif case == "ordered-occurrence-foreign":
        changed = _replace_carried_effect_id(
            original,
            0,
            foreign_id,
            record_occurrence=False,
            selector_occurrence=False,
        )
    elif case == "record-occurrence-foreign":
        changed = _replace_carried_effect_id(
            original,
            0,
            foreign_id,
            ordered_occurrence=False,
            selector_occurrence=False,
        )
    elif case == "selector-occurrence-foreign":
        changed = _replace_carried_effect_id(
            original,
            0,
            foreign_id,
            ordered_occurrence=False,
            record_occurrence=False,
        )
    elif case == "two-carried-agree":
        changed = _replace_carried_effect_id(
            original,
            0,
            foreign_id,
            selector_occurrence=False,
        )
    elif case == "decoded-projection-foreign":
        changed = _replace_decoded_effect_id(original, 0, foreign_id)
    elif case == "decoded-projection-coherent-rehash":
        changed = _replace_decoded_effect_id_with_coherent_payload(
            original,
            0,
            foreign_id,
        )
    elif case == "another-replication-carried-id":
        changed = _replace_carried_effect_id(original, 0, effect_ids[1])
    elif case == "another-group-carried-id":
        other_selection = next(
            selection
            for selection in selections
            if selection[COMPARISON_GROUP_ID_INDEX] != original[COMPARISON_GROUP_ID_INDEX]
        )
        changed = _replace_carried_effect_id(
            original,
            0,
            other_selection[ORDERED_SOURCE_EFFECT_IDS_INDEX][0],
        )
    elif case == "same-five-ids-reordered":
        reordered = tuple(reversed(effect_ids))
        changed = replace_selection_field(
            original,
            ORDERED_SOURCE_EFFECT_IDS_INDEX,
            reordered,
        )
        changed = _replace_selector(changed, source_effect_ids=reordered)
        records = changed[ORDERED_SOURCE_EFFECTS_INDEX]
        changed = with_effect_evidence(
            changed,
            tuple(
                replace_effect_evidence_field(
                    record,
                    EFFECT_ID_INDEX,
                    reordered[effect_index],
                )
                for effect_index, record in enumerate(records)
            ),
        )
    else:
        changed = _replace_decoded_effect_id(original, 1, effect_ids[0])
    changed_selections = replace_bundle_selection(
        selections,
        selection_index,
        changed,
    )
    later_calls = {"chronology": 0, "identity": 0, "p2": 0, "operational": 0}

    def chronology_trap(*args: object, **kwargs: object) -> object:
        del args, kwargs
        later_calls["chronology"] += 1
        raise AssertionError("3o.1.6 must not run after a 3o.1.5 failure")

    def identity_trap(*args: object, **kwargs: object) -> str:
        del args, kwargs
        later_calls["identity"] += 1
        raise AssertionError("chronology identity must not run after a 3o.1.5 failure")

    p2_functions = {
        "_oracle_key_id",
        "_outcome_digest",
        "_selection_matches",
        "_source_observation_matches",
        "calibration_selection_id",
        "replay_calibration_history_selection",
        "selection_identity",
        "source_observation_identity",
    }
    operational_functions = {
        "authorize_observation",
        "enumerate_registry",
        "execute",
        "execute_batch",
        "finalize",
        "load",
        "observe_selected",
        "persist",
        "read",
        "read_all",
        "reobserve",
        "run",
        "run_arm",
        "run_worker",
        "write_evidence",
    }
    operational_module_markers = (
        ".broader_oracle",
        ".broader_reader",
        ".broader_validation_evidence",
        ".reader",
        ".runner",
        ".storage",
        ".workload",
    )

    def later_call_trap(frame: FrameType, event: str, argument: object) -> None:
        del argument
        if event != "call":
            return
        module_name = frame.f_globals.get("__name__")
        if type(module_name) is not str or not module_name.startswith("research_decision_engine"):
            return
        function_name = frame.f_code.co_name
        if function_name in p2_functions or function_name.startswith(
            ("_predicate_3o_2_", "_predicate_3o_3_", "_predicate_3o_4_")
        ):
            later_calls["p2"] += 1
            raise AssertionError("future validation must not run after a 3o.1.5 failure")
        if function_name in operational_functions and any(
            marker in module_name for marker in operational_module_markers
        ):
            later_calls["operational"] += 1
            raise AssertionError("operational work must not run during validation")

    monkeypatch.setattr(evidence, "_predicate_3o_1_6", chronology_trap)
    monkeypatch.setattr(evidence, "strict_chronology_id", identity_trap)
    prior_profile = sys.getprofile()
    sys.setprofile(later_call_trap)
    try:
        outcome = _validate(changed_selections)
    finally:
        sys.setprofile(prior_profile)
    _assert_failure(outcome, predicate_index=5, selection_index=selection_index)
    failure = outcome[0]
    assert failure is not None
    if case == "decoded-projection-coherent-rehash":
        assert failure[3].endswith("source effect payload bytes[0] differ")
    elif case == "duplicate-decoded-effect-id":
        assert failure[3].endswith("source effect projection[1] differs")
    elif case == "decoded-projection-foreign":
        assert failure[3].endswith("source effect projection[0] differs")
    else:
        assert "source effect ID" in failure[3]
    assert later_calls == {"chronology": 0, "identity": 0, "p2": 0, "operational": 0}


@pytest.mark.parametrize(
    ("case", "expected_detail"),
    (
        ("final-lf", "source effect payload[0] lacks exactly one final LF"),
        ("payload-bytes", "source effect payload bytes[0] differ"),
        ("raw-digest", "source effect raw digest[0] differs"),
        ("full-projection", "source effect projection[0] differs"),
        ("effect-value", "source effect ID occurrence[0] differs"),
    ),
    ids=(
        "final-lf-before-authoritative-id",
        "payload-bytes-before-authoritative-id",
        "raw-digest-before-authoritative-id",
        "full-projection-before-authoritative-id",
        "authoritative-id-before-effect-value",
    ),
)
def test_3o_1_5_preserves_frozen_precedence_for_compound_id_faults(
    case: str,
    expected_detail: str,
) -> None:
    selections = valid_bundle()[0]
    changed = _replace_carried_effect_id(
        selections[0],
        0,
        "foreign-carried-effect-id",
    )
    record = changed[ORDERED_SOURCE_EFFECTS_INDEX][0]
    selector = changed[SELECTOR_RESULT_INDEX]
    if case == "final-lf":
        changed = _replace_effect_record_field(
            changed,
            EFFECT_PAYLOAD_BYTES_INDEX,
            record[EFFECT_PAYLOAD_BYTES_INDEX][:-1],
        )
    elif case == "payload-bytes":
        changed = _replace_effect_record_field(
            changed,
            EFFECT_PAYLOAD_BYTES_INDEX,
            b"{}\n",
        )
    elif case == "raw-digest":
        foreign_digest = _alternate_h64(record[EFFECT_PAYLOAD_SHA256_INDEX])
        changed = _replace_effect_record_field(
            changed,
            EFFECT_PAYLOAD_SHA256_INDEX,
            foreign_digest,
        )
        changed = _replace_selector(
            changed,
            source_effect_payload_sha256=_replace_at(
                selector.source_effect_payload_sha256,
                0,
                foreign_digest,
            ),
        )
    elif case == "full-projection":
        changed = _replace_effect_record_field(
            changed,
            EFFECT_PROJECTION_INDEX,
            dataclass_replace(
                record[EFFECT_PROJECTION_INDEX],
                effect_id="foreign-decoded-effect-id",
            ),
        )
    else:
        changed = _replace_selector(
            changed,
            effect_values=_replace_at(
                selector.effect_values,
                0,
                selector.effect_values[0] + 0.25,
            ),
        )
    outcome = _validate(replace_bundle_selection(selections, 0, changed))
    _assert_failure(outcome, predicate_index=5)
    failure = outcome[0]
    assert failure is not None and failure[3].endswith(expected_detail)


def test_3o_1_5_coherent_id_faults_use_the_earliest_canonical_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selections = valid_bundle()[0]
    changed = replace_bundle_selection(
        selections,
        9,
        _replace_carried_effect_id(selections[9], 0, "foreign-effect-id-later"),
    )
    changed = replace_bundle_selection(
        changed,
        2,
        _replace_carried_effect_id(selections[2], 0, "foreign-effect-id-earlier"),
    )

    def chronology_trap(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("3o.1.6 must not run after a 3o.1.5 failure")

    monkeypatch.setattr(evidence, "_predicate_3o_1_6", chronology_trap)
    _assert_failure(_validate(changed), predicate_index=5, selection_index=2)


@pytest.mark.parametrize(
    "case",
    (
        "forged-id",
        "malformed-id",
        "selector-current-effect",
        "selector-current-observation",
        "selector-future-history",
        "selector-cutoff-bool",
        "selector-cutoff-float",
        "carried-fields",
    ),
    ids=(
        "forged-id",
        "malformed-id",
        "current-effect",
        "current-observation",
        "future-history",
        "cutoff-bool",
        "cutoff-float",
        "projection-fields",
    ),
)
def test_3o_1_6_rejects_chronology_fields_relation_cutoff_and_identity(case: str) -> None:
    selections = valid_bundle()[0]
    original = selections[0]
    chronology = original[STRICT_CHRONOLOGY_INDEX]
    if case == "forged-id":
        changed = replace_selection_field(
            original,
            STRICT_CHRONOLOGY_ID_INDEX,
            _alternate_h64(original[STRICT_CHRONOLOGY_ID_INDEX]),
        )
    elif case == "malformed-id":
        changed = replace_selection_field(
            original,
            STRICT_CHRONOLOGY_ID_INDEX,
            "not-h64",
        )
    elif case == "selector-current-effect":
        changed = _replace_selector(original, current_effect_excluded=False)
    elif case == "selector-current-observation":
        changed = _replace_selector(original, current_observation_excluded=False)
    elif case == "selector-future-history":
        changed = _replace_selector(original, future_history_excluded=False)
    elif case == "selector-cutoff-bool":
        changed = _replace_selector(original, source_sequence_cutoff=True)
    elif case == "selector-cutoff-float":
        changed = _replace_selector(original, source_sequence_cutoff=1.0)
    else:
        invalid_fields = (
            ("current_effect_excluded", False),
            ("current_observation_excluded", False),
            ("effect_available_sequences", (0, 0, 0, 0, 1)),
            ("future_history_excluded", False),
            ("schema_version", "broader-replication-calibration-chronology/v2"),
            ("source_sequence_cutoff", 2),
        )
        for field_name, value in invalid_fields:
            corrupted = _unsafe_chronology(chronology, field_name, value)
            changed = replace_selection_field(
                original,
                STRICT_CHRONOLOGY_INDEX,
                corrupted,
            )
            _assert_selection_failure(changed, 6)
        return
    _assert_selection_failure(changed, 6)


@pytest.mark.parametrize(
    ("case", "expected_detail", "expected_identity_calls"),
    (
        ("current-effect-plus-relation", "current effect exclusion differs", 0),
        ("current-observation-plus-relation", "current observation exclusion differs", 0),
        (
            "available-sequences-plus-relation",
            "effect available-sequence tuple differs",
            0,
        ),
        ("future-history-plus-cutoff", "future-history exclusion differs", 0),
        ("schema-plus-relation", "chronology schema differs", 0),
        ("cutoff-plus-relation", "source-sequence cutoff differs", 0),
        (
            "relation-only",
            "chronology field or source-effect relation differs",
            0,
        ),
        ("identity-only", "chronology identity differs", 1),
    ),
    ids=(
        "current-effect-field-before-effect-relation",
        "current-observation-field-before-available-relation",
        "available-field-before-cutoff-relation",
        "future-field-before-cutoff",
        "schema-field-before-source-effect-relation",
        "cutoff-field-before-effect-relation",
        "relation-after-all-fields",
        "identity-last",
    ),
)
def test_3o_1_6_enforces_declaration_fields_then_relations_then_identity(
    case: str,
    expected_detail: str,
    expected_identity_calls: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = valid_bundle()[0][0]
    if case == "current-effect-plus-relation":
        changed = _replace_chronology_field(
            _replace_chronology_effect_relation(original),
            "current_effect_excluded",
            False,
        )
    elif case == "current-observation-plus-relation":
        changed = _replace_chronology_field(
            _replace_chronology_effect_relation(original),
            "current_observation_excluded",
            False,
        )
    elif case == "available-sequences-plus-relation":
        changed = _replace_chronology_field(
            _replace_selector(original, source_sequence_cutoff=2),
            "effect_available_sequences",
            (0, 0, 0, 0, 1),
        )
    elif case == "future-history-plus-cutoff":
        changed = _replace_chronology_field(
            _replace_selector(original, source_sequence_cutoff=2),
            "future_history_excluded",
            False,
        )
    elif case == "schema-plus-relation":
        changed = _replace_chronology_field(
            _replace_chronology_effect_relation(original),
            "schema_version",
            "broader-replication-calibration-chronology/v2",
        )
    elif case == "cutoff-plus-relation":
        changed = _replace_chronology_field(
            _replace_chronology_effect_relation(original),
            "source_sequence_cutoff",
            2,
        )
    elif case == "relation-only":
        changed = _replace_chronology_effect_relation(original)
    else:
        changed = replace_selection_field(
            original,
            STRICT_CHRONOLOGY_ID_INDEX,
            _alternate_h64(original[STRICT_CHRONOLOGY_ID_INDEX]),
        )
    identity_calls = 0
    real_identity = evidence.strict_chronology_id

    def identity_spy(projection: StrictChronologyProjection) -> str:
        nonlocal identity_calls
        identity_calls += 1
        return real_identity(projection)

    monkeypatch.setattr(evidence, "strict_chronology_id", identity_spy)
    failure = evidence._predicate_3o_1_6(changed)
    assert failure == ("CALIBRATION_CHRONOLOGY_ID_MISMATCH", expected_detail)
    assert identity_calls == expected_identity_calls


@pytest.mark.parametrize(
    "chronology_fault",
    (
        "current-effect",
        "current-observation",
        "available-sequences",
        "future-history",
        "schema",
        "cutoff",
        "effect-relation",
        "identity",
    ),
    ids=(
        "effect-before-current-effect",
        "effect-before-current-observation",
        "effect-before-available-sequences",
        "effect-before-future-history",
        "effect-before-schema",
        "effect-before-cutoff",
        "effect-before-effect-relation",
        "effect-before-identity",
    ),
)
def test_3o_1_5_effect_identity_failure_beats_every_3o_1_6_fault(
    chronology_fault: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selections = valid_bundle()[0]
    changed = _replace_carried_effect_id(
        selections[0],
        0,
        "foreign-effect-id",
    )
    if chronology_fault == "current-effect":
        changed = _replace_chronology_field(changed, "current_effect_excluded", False)
    elif chronology_fault == "current-observation":
        changed = _replace_chronology_field(changed, "current_observation_excluded", False)
    elif chronology_fault == "available-sequences":
        changed = _replace_chronology_field(
            changed,
            "effect_available_sequences",
            (0, 0, 0, 0, 1),
        )
    elif chronology_fault == "future-history":
        changed = _replace_chronology_field(changed, "future_history_excluded", False)
    elif chronology_fault == "schema":
        changed = _replace_chronology_field(
            changed,
            "schema_version",
            "broader-replication-calibration-chronology/v2",
        )
    elif chronology_fault == "cutoff":
        changed = _replace_chronology_field(changed, "source_sequence_cutoff", 2)
    elif chronology_fault == "effect-relation":
        changed = _replace_chronology_effect_relation(changed)
    else:
        changed = replace_selection_field(
            changed,
            STRICT_CHRONOLOGY_ID_INDEX,
            _alternate_h64(changed[STRICT_CHRONOLOGY_ID_INDEX]),
        )

    def chronology_trap(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("3o.1.6 must not run after a 3o.1.5 failure")

    monkeypatch.setattr(evidence, "_predicate_3o_1_6", chronology_trap)
    changed_selections = replace_bundle_selection(selections, 0, changed)
    _assert_failure(_validate(changed_selections), predicate_index=5)


def test_3o_1_6_same_predicate_uses_earliest_canonical_selection() -> None:
    selections = valid_bundle()[0]
    changed = replace_bundle_selection(
        selections,
        4,
        replace_selection_field(
            selections[4],
            STRICT_CHRONOLOGY_ID_INDEX,
            _alternate_h64(selections[4][STRICT_CHRONOLOGY_ID_INDEX]),
        ),
    )
    changed = replace_bundle_selection(
        changed,
        1,
        replace_selection_field(
            selections[1],
            STRICT_CHRONOLOGY_ID_INDEX,
            _alternate_h64(selections[1][STRICT_CHRONOLOGY_ID_INDEX]),
        ),
    )
    _assert_failure(_validate(changed), predicate_index=6, selection_index=1)


def _fault_for_predicate(
    selections: tuple[SelectionEvidence, ...],
    predicate_index: int,
    selection_index: int,
) -> tuple[SelectionEvidence, ...]:
    selection = selections[selection_index]
    if predicate_index == 0:
        changed = replace_selection_field(
            selection,
            EXECUTION_SPECIFICATION_ID_INDEX,
            _alternate_h64(selection[EXECUTION_SPECIFICATION_ID_INDEX]),
        )
    elif predicate_index == 1:
        pair_ids = selection[ORDERED_CANDIDATE_PAIR_IDS_INDEX]
        changed = replace_selection_field(
            selection,
            ORDERED_CANDIDATE_PAIR_IDS_INDEX,
            (_alternate_h64(pair_ids[0]), *pair_ids[1:]),
        )
    elif predicate_index == 2:
        studies = selection[STUDY_OCCURRENCES_INDEX]
        changed = replace_selection_field(
            selection,
            STUDY_OCCURRENCES_INDEX,
            ("wrong-study/v1", *studies[1:]),
        )
    elif predicate_index == 3:
        changed = replace_selection_field(selection, POSITION_INDEX, -1)
    elif predicate_index == 4:
        changed = replace_selection_field(
            selection,
            REPLICATION_RANKS_INDEX,
            (True, 2, 3, 4, 5),
        )
    elif predicate_index == 5:
        records = selection[ORDERED_SOURCE_EFFECTS_INDEX]
        record = replace_effect_evidence_field(
            records[0],
            EFFECT_PAYLOAD_SHA256_INDEX,
            _alternate_h64(records[0][EFFECT_PAYLOAD_SHA256_INDEX]),
        )
        changed = with_effect_evidence(
            selection,
            replace_effect_evidence_at(records, 0, record),
        )
    else:
        changed = replace_selection_field(
            selection,
            STRICT_CHRONOLOGY_ID_INDEX,
            _alternate_h64(selection[STRICT_CHRONOLOGY_ID_INDEX]),
        )
    return replace_bundle_selection(selections, selection_index, changed)


@pytest.mark.parametrize(
    "earlier_predicate",
    range(6),
    ids=(
        "3o.1.0-before-3o.1.1",
        "3o.1.1-before-3o.1.2",
        "3o.1.2-before-3o.1.3",
        "3o.1.3-before-3o.1.4",
        "3o.1.4-before-3o.1.5",
        "3o.1.5-before-3o.1.6",
    ),
)
def test_predicate_family_major_later_selection_beats_later_family_earlier_selection(
    earlier_predicate: int,
) -> None:
    selections = valid_bundle()[0]
    changed = _fault_for_predicate(selections, earlier_predicate + 1, 0)
    changed = _fault_for_predicate(changed, earlier_predicate, 1)
    _assert_failure(
        _validate(changed),
        predicate_index=earlier_predicate,
        selection_index=1,
    )


def test_same_predicate_uses_earliest_canonical_selection_not_mutation_order() -> None:
    selections = valid_bundle()[0]
    changed = _fault_for_predicate(selections, 5, 4)
    changed = _fault_for_predicate(changed, 5, 1)
    _assert_failure(
        _validate(changed),
        predicate_index=5,
        selection_index=1,
    )


def test_earlier_failure_never_invokes_any_later_predicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def later_predicate_trap(*args: object, **kwargs: object) -> object:
        raise AssertionError("later P1 predicate was entered")

    for predicate_index in range(1, 7):
        monkeypatch.setattr(
            evidence,
            f"_predicate_3o_1_{predicate_index}",
            later_predicate_trap,
        )
    selections = _fault_for_predicate(valid_bundle()[0], 0, 0)
    _assert_failure(_validate(selections), predicate_index=0)
