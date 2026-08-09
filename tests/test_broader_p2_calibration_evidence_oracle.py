"""Stage-2F P2 Oracle/source-observation semantic contract tests."""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import inspect
import subprocess
import sys
import time
from collections import namedtuple
from dataclasses import FrozenInstanceError, fields
from typing import Any, cast, get_type_hints

import pytest

from research_decision_engine.benchmarks import broader_calibration_evidence as evidence
from research_decision_engine.benchmarks import broader_oracle as oracle
from research_decision_engine.benchmarks.broader_calibration_evidence import (
    CalibrationSourceObservationProjection,
    _decode_calibration_source_observation_projection,
    source_observation_identity,
)
from research_decision_engine.benchmarks.broader_protocol import (
    canonical_json_bytes,
    protocol_hash,
    runtime_id,
)
from tests import p2_calibration_evidence_harness as harness

# The tables are intentionally kept dense: each stable parameter ID is an
# independently attributable contract node, while one immutable module fixture
# owns the otherwise expensive 318 x 10 construction.
# fmt: off

type Bundle = harness.P2ValidBundle
type Selection = harness.SelectionEvidence
type P2Selection = harness.P2SelectionEvidence
type Predecessor = harness.OraclePredecessor
type SourceEvidence = harness.SourceObservationEvidence

_PATHS = ("calibration/3o.2.0/oracle_binding", "calibration/3o.2.1/oracle_key", "calibration/3o.3.1/outcome", "calibration/3o.4.1/source_observation")
_CODES = ("CALIBRATION_ORACLE_BINDING_MISMATCH", "CALIBRATION_ORACLE_KEY_ID_MISMATCH", "CALIBRATION_OUTCOME_DIGEST_MISMATCH", "CALIBRATION_SOURCE_OBSERVATION_ID_MISMATCH")
_FIXED_ORACLE_KEY_ID = "oracle-key:ff24f37902c59ec5b15238a3148da85a534e43f5016d417bf2669e41666dd3b5"
_FIXED_OUTCOME_DIGEST = "9693b57f4ef37ad5cf70346d3b29ccb3e3e45471bbd7701d83f4d829c28f048c"
_FIXED_RAW_KEY_DIGEST = "53a271695cc4187f215769cafeaf64b5ab613a0c0d9005fbb02a5f972fdf3cb3"
_FIXED_ID = "ad3fde45e1a22867d68f381eac353e0074f2bb0a27858781d574b506782d1c4b"
_ProjectionTuple = namedtuple("_ProjectionTuple", ("candidate_id", "comparison_group_id", "digest", "intervention_arm", "key_fields", "namespace", "oracle_key_id", "outcome_digest", "replication_id", "revealed_observation", "schema_version", "seed", "serialized_key_hex", "u", "world_id", "z"))
_COLD_MINIMAL_SCRIPT = """
from research_decision_engine.benchmarks.broader_calibration_evidence import CalibrationSourceObservationProjection, source_observation_identity
projection = CalibrationSourceObservationProjection(candidate_id="cal-00-adam-r0001", comparison_group_id="group-00", digest="53a271695cc4187f215769cafeaf64b5ab613a0c0d9005fbb02a5f972fdf3cb3", intervention_arm="adam", key_fields=("rde.broader.calibration-outcome/v1", "broader-closed-loop-replication/v1", "broader_selected_only_oracle/v1", "h_adam_low", "9000", "group-00", "adam", "calibration-00-r0001"), namespace="rde.broader.calibration-outcome/v1", oracle_key_id="oracle-key:ff24f37902c59ec5b15238a3148da85a534e43f5016d417bf2669e41666dd3b5", outcome_digest="9693b57f4ef37ad5cf70346d3b29ccb3e3e45471bbd7701d83f4d829c28f048c", replication_id="calibration-00-r0001", revealed_observation="f64:3fe33b8c27edaff3", schema_version="broader-replication-calibration-source-observation/v1", seed=9000, serialized_key_hex="5b227264652e62726f616465722e63616c6962726174696f6e2d6f7574636f6d652f7631222c2262726f616465722d636c6f7365642d6c6f6f702d7265706c69636174696f6e2f7631222c2262726f616465725f73656c65637465645f6f6e6c795f6f7261636c652f7631222c22685f6164616d5f6c6f77222c2239303030222c2267726f75702d3030222c226164616d222c2263616c6962726174696f6e2d30302d7230303031225d", u="0.32669743368457238030799771877354942262172698974609375", world_id="h_adam_low", z="-0.449050999389407436070018932447")
print(source_observation_identity(projection))
"""


class _Text(str):
    pass
class _Mapping(dict[str, object]):
    pass
class _ProjectionSubclass(CalibrationSourceObservationProjection):
    pass


class _Trap:
    calls = 0
    def __getattr__(self, name: str) -> object:
        type(self).calls += 1
        raise AssertionError(name)
    def __iter__(self) -> Any:
        type(self).calls += 1
        raise AssertionError("iter")
    def __eq__(self, other: object) -> bool:
        type(self).calls += 1
        raise AssertionError("eq")
    def __bool__(self) -> bool:
        type(self).calls += 1
        raise AssertionError("bool")


@pytest.fixture(scope="module")
def p2_bundle() -> Bundle:
    return harness.build_valid_p2_bundle()


def _h64(value: str) -> str:
    return "1" * 64 if value == "0" * 64 else "0" * 64


def _oid(value: str) -> str:
    return f"oracle-key:{_h64(value.removeprefix('oracle-key:'))}"


def _counter_trap(calls: dict[str, int], name: str) -> Any:
    def entered(*args: object, **kwargs: object) -> object:
        calls[name] += 1
        raise AssertionError(name)
    return entered


def _at[T](values: tuple[T, ...], index: int, value: T) -> tuple[T, ...]:
    return (*values[:index], value, *values[index + 1:])


def _scope(bundle: Bundle, index: int = 0) -> tuple[Selection, P2Selection, Predecessor]:
    return bundle[0][index], bundle[3][index], bundle[4][index]


def _projection(p2: P2Selection, index: int = 0) -> CalibrationSourceObservationProjection:
    return p2[harness.P2_ORDERED_SOURCE_OBSERVATIONS_INDEX][index][0]


def _unsafe(projection: CalibrationSourceObservationProjection, cls: type[CalibrationSourceObservationProjection] = CalibrationSourceObservationProjection, /, **changes: object) -> CalibrationSourceObservationProjection:
    result = object.__new__(cls)
    for field in fields(CalibrationSourceObservationProjection):
        object.__setattr__(result, field.name, changes.get(field.name, getattr(projection, field.name)))
    return result


def _with_sources(p2: P2Selection, sources: object) -> P2Selection:
    return harness.replace_p2_selection_field(p2, harness.P2_ORDERED_SOURCE_OBSERVATIONS_INDEX, sources)


def _with_projection(p2: P2Selection, index: int, projection: CalibrationSourceObservationProjection, identity: str | None = None) -> P2Selection:
    sources = p2[harness.P2_ORDERED_SOURCE_OBSERVATIONS_INDEX]
    carried = sources[index][1] if identity is None else identity
    return _with_sources(p2, harness.replace_source_evidence_at(sources, index, (projection, carried)))


def _selector(selection: Selection, **changes: object) -> Selection:
    result = harness.replace_selector_result(selection[harness.SELECTOR_RESULT_INDEX], **changes)
    return harness.with_selector_result(selection, result)


def _validate(bundle: Bundle, *, selections: tuple[Selection, ...] | None = None, p2_selections: tuple[P2Selection, ...] | None = None) -> evidence._P2ValidationOutcome:
    return evidence._validate_stage2f_p2(
        selections=bundle[0] if selections is None else selections,
        expected_execution_attestation_pairs=bundle[1],
        attested_execution_specification_ids=bundle[2],
        p2_selections=bundle[3] if p2_selections is None else p2_selections,
        expected_predecessors=bundle[4],
    )


def _p20(selection: Selection, p2: P2Selection, predecessor: Predecessor) -> evidence._PredicateFailure | None:
    return evidence._predicate_3o_2_0(selection, p2, predecessor)


def _p21(selection: Selection, p2: P2Selection) -> evidence._PredicateFailure | None:
    return evidence._predicate_3o_2_1(selection, p2)


def _p31(selection: Selection, p2: P2Selection, predecessor: Predecessor) -> evidence._PredicateFailure | None:
    return evidence._predicate_3o_3_1(selection, p2, predecessor)


def _p41(selection: Selection, p2: P2Selection, predecessor: Predecessor) -> evidence._PredicateFailure | None:
    return evidence._predicate_3o_4_1(selection, p2, predecessor)


def _counts(family: int, selection: int) -> tuple[int, ...]:
    return (*(318 for _ in range(7)), *(318 if i < family else selection + 1 if i == family else 0 for i in range(4)))


def _assert_failure(outcome: evidence._P2ValidationOutcome, family: int, selection: int = 0) -> None:
    failure, counts = outcome
    assert failure is not None
    assert failure[:3] == (_CODES[family], _PATHS[family], selection)
    role, world, seed, group = harness.CANONICAL_COORDINATES[selection]
    assert failure[3].startswith(f"selection[{selection}] {role}/{world}/{seed}/{group}: ")
    assert counts == _counts(family, selection)


def _fault(family: int, index: int, selections: tuple[Selection, ...], p2s: tuple[P2Selection, ...]) -> tuple[tuple[Selection, ...], tuple[P2Selection, ...]]:
    p2 = p2s[index]
    if family == 0:
        predecessor = p2[0]
        changed = harness.replace_oracle_predecessor_field(predecessor, 0, _h64(predecessor[0]))
        p2 = harness.replace_p2_selection_field(p2, 0, changed)
    elif family == 1:
        p = _projection(p2)
        key = (*p.key_fields[:6], p.key_fields[7], p.key_fields[6])
        p2 = _with_projection(p2, 0, harness.replace_source_observation_field(p, "key_fields", key))
    elif family == 2:
        p = harness.replace_source_observation_field(_projection(p2), "revealed_observation", "f64:0000000000000000")
        p2 = _with_projection(p2, 0, p)
    else:
        sources = p2[1]
        p2 = _with_projection(p2, 0, sources[0][0], _h64(sources[0][1]))
    return selections, harness.replace_p2_selection(p2s, index, p2)


def test_projection_surface_is_exact_frozen_slotted_and_typed(p2_bundle: Bundle) -> None:
    projection = _projection(_scope(p2_bundle)[1])
    hints = get_type_hints(CalibrationSourceObservationProjection)
    assert CalibrationSourceObservationProjection.__name__ == "CalibrationSourceObservationProjection"
    assert tuple(field.name for field in fields(CalibrationSourceObservationProjection)) == harness.SOURCE_OBSERVATION_FIELD_NAMES
    assert tuple(hints) == harness.SOURCE_OBSERVATION_FIELD_NAMES
    assert hints["key_fields"] == tuple[str, ...] and hints["seed"] is int
    assert str(hints["intervention_arm"]) == "typing.Literal['adam', 'sgd']"
    assert "rde.broader.calibration-outcome/v1" in str(hints["namespace"])
    assert "broader-replication-calibration-source-observation/v1" in str(hints["schema_version"])
    assert "__dict__" not in CalibrationSourceObservationProjection.__slots__
    with pytest.raises(FrozenInstanceError):
        projection.seed = 1  # type: ignore[misc]


def test_projection_mapping_decoder_and_identity_round_trip_exactly(p2_bundle: Bundle) -> None:
    projection = _projection(_scope(p2_bundle)[1])
    mapping = harness.source_observation_mapping(projection)
    assert type(mapping) is dict and tuple(mapping) == harness.SOURCE_OBSERVATION_FIELD_NAMES
    assert _decode_calibration_source_observation_projection(mapping) == projection
    assert source_observation_identity(projection) == harness.expected_source_observation_identity(projection)


@pytest.mark.parametrize("case", ("missing", "extra", "reordered", "mapping-subclass", "list", "hostile"), ids=("missing", "extra", "same-fields-reordered", "mapping-subclass", "list", "hostile"))
def test_decoder_rejects_nonclosed_mapping_shapes_without_coercion(case: str, p2_bundle: Bundle) -> None:
    mapping = harness.source_observation_mapping(_projection(_scope(p2_bundle)[1]))
    values: dict[str, object] = {"missing": dict(tuple(mapping.items())[:-1]), "extra": {**mapping, "extra": "x"}, "reordered": dict(reversed(tuple(mapping.items()))), "mapping-subclass": _Mapping(mapping), "list": list(mapping.items()), "hostile": _Trap()}
    _Trap.calls = 0
    with pytest.raises(ValueError):
        _decode_calibration_source_observation_projection(values[case])
    if case == "hostile":
        assert _Trap.calls == 0


@pytest.mark.parametrize("case", ("text", "nfc", "h64", "key-list", "key-item", "bool", "hex", "f64", "literals", "decimal"), ids=("text-subclass", "non-nfc", "uppercase-h64", "list-key-fields", "non-string-key-field", "bool-for-int", "uppercase-key-hex", "float-for-f64", "wrong-literals", "noncanonical-decimals"))
def test_projection_constructor_rejects_every_nonclosed_runtime_shape(case: str, p2_bundle: Bundle) -> None:
    p = _projection(_scope(p2_bundle)[1])
    bad: dict[str, tuple[tuple[str, object], ...]] = {
        "text": (("candidate_id", _Text(p.candidate_id)),), "nfc": (("world_id", "cafe\u0301"),),
        "h64": (("digest", p.digest.upper()),), "key-list": (("key_fields", list(p.key_fields)),),
        "key-item": (("key_fields", (*p.key_fields[:4], 9000, *p.key_fields[5:])),), "bool": (("seed", True),),
        "hex": (("serialized_key_hex", p.serialized_key_hex.upper()),), "f64": (("revealed_observation", 0.0),),
        "literals": (("intervention_arm", "rmsprop"), ("namespace", "rde.broader.calibration-outcome/v2"), ("schema_version", "broader-replication-calibration-source-observation/v2")),
        "decimal": (("u", "0.5"), ("z", f"-0.{30 * '0'}")),
    }
    for name, value in bad[case]:
        with pytest.raises(ValueError):
            harness.replace_source_observation_field(p, name, value)


def test_identity_boundary_rejects_subclass_proxy_mapping_and_named_tuple_hooks(p2_bundle: Bundle) -> None:
    p = _projection(_scope(p2_bundle)[1])
    subclass = _unsafe(p, _ProjectionSubclass)
    named = _ProjectionTuple(*(getattr(p, name) for name in harness.SOURCE_OBSERVATION_FIELD_NAMES))
    _Trap.calls = 0
    for hostile in (subclass, _Trap(), harness.source_observation_mapping(p), named):
        with pytest.raises(ValueError):
            source_observation_identity(cast(Any, hostile))
    assert _Trap.calls == 0


def test_source_identity_has_independent_fixed_vector_and_complete_preimage(p2_bundle: Bundle) -> None:
    p = _projection(_scope(p2_bundle)[1])
    mapping = harness.source_observation_mapping(p)
    assert tuple(mapping) == harness.SOURCE_OBSERVATION_FIELD_NAMES
    assert harness.expected_source_observation_identity(p) == source_observation_identity(p) == _FIXED_ID
    assert protocol_hash("validation_evidence_calibration_source_observation/v1", mapping) == _FIXED_ID


@pytest.mark.parametrize("name", harness.SOURCE_OBSERVATION_FIELD_NAMES, ids=harness.SOURCE_OBSERVATION_FIELD_NAMES)
def test_every_source_projection_field_is_identity_sensitive(name: str, p2_bundle: Bundle) -> None:
    p2 = _scope(p2_bundle)[1]
    p, other = _projection(p2), _projection(p2, 1)
    values: dict[str, object] = {
        "candidate_id": "cal-00-adam-r0002", "comparison_group_id": "group-01", "digest": _h64(p.digest),
        "intervention_arm": "sgd", "key_fields": (*p.key_fields[:4], "9001", *p.key_fields[5:]),
        "namespace": "rde.broader.calibration-outcome/v2", "oracle_key_id": _oid(p.oracle_key_id),
        "outcome_digest": _h64(p.outcome_digest), "replication_id": "calibration-00-r0002",
        "revealed_observation": "f64:0000000000000000", "schema_version": "broader-replication-calibration-source-observation/v2",
        "seed": p.seed + 1, "serialized_key_hex": "00", "u": other.u, "world_id": "d3_adam", "z": f"0.{30 * '0'}",
    }
    if name in {"namespace", "schema_version"}:
        with pytest.raises(ValueError):
            harness.replace_source_observation_field(p, name, values[name])
        return
    changed = harness.replace_source_observation_field(p, name, values[name])
    expected = harness.expected_source_observation_identity(changed)
    assert expected != harness.expected_source_observation_identity(p)
    assert source_observation_identity(changed) == expected


@pytest.mark.parametrize("case", ("wrong-domain", "copied", "coherent"), ids=("wrong-domain", "copied-identity", "coherent-wrong-projection"))
def test_source_identity_rejects_wrong_domain_copy_and_semantic_rebinding(case: str, p2_bundle: Bundle) -> None:
    selection, p2, predecessor = _scope(p2_bundle)
    sources = p2[1]
    p, identity = sources[0]
    if case == "wrong-domain":
        assert identity != protocol_hash("validation_evidence_calibration_source_observation/v2", harness.source_observation_mapping(p))
    elif case == "copied":
        assert not evidence._source_observation_matches(sources[1][0], identity)
    else:
        changed = harness.replace_source_observation_field(p, "digest", _h64(p.digest))
        rebound = harness.expected_source_observation_identity(changed)
        assert source_observation_identity(changed) == rebound
        failure = _p41(selection, _with_projection(p2, 0, changed, rebound), predecessor)
        assert failure is not None and "digest differs" in failure[1]


def test_canonical_bundle_has_exact_318_by_10_order_and_3180_coordinates(p2_bundle: Bundle) -> None:
    selections, p2s, predecessors = p2_bundle[0], p2_bundle[3], p2_bundle[4]
    assert len(selections) == len(p2s) == len(predecessors) == 318
    total = 0
    for index, (selection, p2) in enumerate(zip(selections, p2s, strict=True)):
        role, world, seed, group = harness.CANONICAL_COORDINATES[index]
        assert (selection[harness.ROLE_INDEX], selection[harness.WORLD_ID_INDEX], selection[harness.SEED_INDEX], selection[harness.COMPARISON_GROUP_ID_INDEX]) == (role, world, seed, group)
        sources = p2[1]
        assert len(sources) == 10
        total += len(sources)
        for observation, (projection, _) in enumerate(sources):
            pair, arm = divmod(observation, 2)
            assert projection.candidate_id == selection[harness.ORDERED_CANDIDATE_PAIRS_INDEX][pair][arm]
    assert total == 3180


@pytest.mark.parametrize("pair", range(5), ids=("pair-1", "pair-2", "pair-3", "pair-4", "pair-5"))
def test_observations_are_pair_major_then_adam_sgd(pair: int, p2_bundle: Bundle) -> None:
    selection, p2, _ = _scope(p2_bundle)
    sources = p2[1]
    adam, sgd = sources[pair * 2][0], sources[pair * 2 + 1][0]
    assert (adam.intervention_arm, sgd.intervention_arm) == ("adam", "sgd")
    assert (adam.candidate_id, sgd.candidate_id) == selection[harness.ORDERED_CANDIDATE_PAIRS_INDEX][pair]
    assert adam.replication_id == sgd.replication_id == selection[harness.ORDERED_REPLICATION_IDS_INDEX][pair]


@pytest.mark.parametrize("case", ("missing", "extra", "duplicate", "pair-order", "reverse"), ids=("missing", "extra", "duplicate", "pair-reordered", "same-set-reversed"))
def test_source_sequence_rejects_missing_extra_duplicate_and_reordered_entries(case: str, p2_bundle: Bundle) -> None:
    selection, p2, predecessor = _scope(p2_bundle)
    sources = p2[1]
    if case == "missing":
        changed: object = sources[:-1]
    elif case == "extra":
        changed = (*sources, sources[-1])
    elif case == "duplicate":
        changed = _at(sources, 1, sources[0])
    elif case == "pair-order":
        changed = (*sources[2:4], *sources[:2], *sources[4:])
    else:
        changed = tuple(reversed(sources))
    changed_p2 = _with_sources(p2, changed)
    failure = _p41(selection, changed_p2, predecessor) if case == "extra" else _p21(selection, changed_p2)
    assert failure is not None and failure[0] == _CODES[3 if case == "extra" else 1]


def test_3o_2_0_accepts_exact_immutable_oracle_predecessor_relation(p2_bundle: Bundle) -> None:
    selection, p2, predecessor = _scope(p2_bundle)
    assert p2[0] == predecessor
    assert _p20(selection, p2, predecessor) is None


@pytest.mark.parametrize("case", ("execution", "binding", "impl-ns", "impl-id", "scope", "pairs", "replications", "world"), ids=("execution", "binding", "implementation-namespace", "implementation-identity", "study-namespace-world-seed-group", "candidate-pairs", "replications", "frozen-world-identity"))
def test_3o_2_0_rejects_each_oracle_predecessor_relation(case: str, p2_bundle: Bundle) -> None:
    selection, p2, expected = _scope(p2_bundle)
    predecessor = p2[0]
    first = predecessor[8][0]
    changes: dict[str, tuple[tuple[int, object], ...]] = {
        "execution": ((0, _h64(predecessor[0])),), "binding": ((1, _h64(predecessor[1])),),
        "impl-ns": ((2, ("broader_selected_only_oracle/v2", predecessor[2][1])),),
        "impl-id": ((2, (predecessor[2][0], _h64(predecessor[2][1]))),),
        "scope": ((3, "broader-closed-loop-replication/v2"), (4, "rde.broader.calibration-outcome/v2"), (5, "d3_adam"), (6, True), (7, "group-01")),
        "pairs": ((8, ((first[1], first[0]), *predecessor[8][1:])),), "replications": ((9, tuple(reversed(predecessor[9]))),),
        "world": ((10, p2_bundle[4][12][10]),),
    }
    for field, value in changes[case]:
        changed = harness.replace_oracle_predecessor_field(predecessor, field, value)
        failure = _p20(selection, harness.replace_p2_selection_field(p2, 0, changed), expected)
        assert failure is not None and failure[0] == _CODES[0]


def test_3o_2_1_has_exact_eight_field_key_and_canonical_runtime_identity(p2_bundle: Bundle) -> None:
    selection, p2, _ = _scope(p2_bundle)
    p = _projection(p2)
    key = ("rde.broader.calibration-outcome/v1", "broader-closed-loop-replication/v1", "broader_selected_only_oracle/v1", "h_adam_low", "9000", "group-00", "adam", "calibration-00-r0001")
    expected = runtime_id("oracle-key", "oracle_key_id/v1", {"key_fields": list(key)})
    selector = selection[16]
    assert p.key_fields == key and len(key) == 8
    assert p.oracle_key_id == selector.source_oracle_key_ids[0] == selector.source_observation_identities[0][0] == expected
    assert _p21(selection, p2) is None


def test_oracle_key_id_has_independent_fixed_vector_and_complete_preimage(p2_bundle: Bundle) -> None:
    p = _projection(_scope(p2_bundle)[1])
    key_fields = ("rde.broader.calibration-outcome/v1", "broader-closed-loop-replication/v1", "broader_selected_only_oracle/v1", "h_adam_low", "9000", "group-00", "adam", "calibration-00-r0001")
    expected = runtime_id("oracle-key", "oracle_key_id/v1", {"key_fields": key_fields})
    changed = tuple(runtime_id("oracle-key", "oracle_key_id/v1", {"key_fields": _at(key_fields, index, value)}) for index, value in enumerate(("rde.broader.calibration-outcome/v2", "broader-closed-loop-replication/v2", "broader_selected_only_oracle/v2", "d3_adam", "9001", "group-01", "sgd", "calibration-00-r0002")))
    assert expected == p.oracle_key_id == _FIXED_ORACLE_KEY_ID
    assert all(value != expected for value in changed)


@pytest.mark.parametrize("case", ("candidate", "scope", "arm", "replication", "key-order", "key-list", "projection", "selector", "pair"), ids=("wrong-pair-candidate", "namespace-world-seed-group", "wrong-arm", "wrong-replication", "same-set-key-order", "list-key-container", "forged-projection-key", "copied-selector-key", "forged-selector-paired-key"))
def test_3o_2_1_rejects_association_key_shape_order_and_every_key_occurrence(case: str, p2_bundle: Bundle) -> None:
    selection, p2, predecessor = _scope(p2_bundle)
    sources, p, other = p2[1], _projection(p2), _projection(p2, 1)
    projections: tuple[CalibrationSourceObservationProjection, ...] = ()
    selections: tuple[Selection, ...] = ()
    if case == "candidate":
        projections = (harness.replace_source_observation_field(p, "key_fields", _projection(p2, 2).key_fields),)
    elif case == "scope":
        source_only = harness.replace_source_observation_field(p, "comparison_group_id", "group-01")
        assert _p21(selection, _with_projection(p2, 0, source_only)) is None
        source_failure = _p41(selection, _with_projection(p2, 0, source_only), predecessor)
        assert source_failure is not None and source_failure[0] == _CODES[3]
        projections = tuple(
            harness.replace_source_observation_field(p, "key_fields", _at(p.key_fields, index, value))
            for index, value in ((0, "rde.broader.calibration-outcome/v2"), (1, "broader-closed-loop-replication/v2"), (2, "broader_selected_only_oracle/v2"), (3, "d3_adam"), (4, "9001"), (5, "group-01"))
        )
    elif case == "arm":
        projections = (harness.replace_source_observation_field(p, "key_fields", _at(p.key_fields, 6, "sgd")),)
    elif case == "replication":
        projections = (harness.replace_source_observation_field(p, "key_fields", _at(p.key_fields, 7, "calibration-00-r0002")),)
    elif case == "key-order":
        projections = (harness.replace_source_observation_field(p, "key_fields", (*p.key_fields[:6], p.key_fields[7], p.key_fields[6])),)
    elif case == "key-list":
        projections = (_unsafe(p, key_fields=list(p.key_fields)),)
    elif case == "projection":
        projections = (harness.replace_source_observation_field(p, "oracle_key_id", other.oracle_key_id),)
    elif case == "selector":
        selector = selection[16]
        selections = (_selector(selection, source_oracle_key_ids=_at(selector.source_oracle_key_ids, 0, selector.source_oracle_key_ids[1])),)
    else:
        selector = selection[16]
        pair = selector.source_observation_identities[0]
        selections = (_selector(selection, source_observation_identities=_at(selector.source_observation_identities, 0, (other.oracle_key_id, pair[1]))),)
    for changed in projections:
        failure = _p21(selection, _with_projection(p2, 0, changed, sources[0][1]))
        assert failure is not None and failure[0] == _CODES[1]
    for changed_selection in selections:
        failure = _p21(changed_selection, p2)
        assert failure is not None and failure[0] == _CODES[1]


def test_3o_3_1_has_exact_selected_only_f64_and_outcome_digest_vector(p2_bundle: Bundle) -> None:
    selection, p2, predecessor = _scope(p2_bundle)
    p = _projection(p2)
    expected = protocol_hash("revealed_outcome/v1", {"oracle_key_id": p.oracle_key_id, "revealed_observation": p.revealed_observation})
    assert p.revealed_observation == "f64:3fe33b8c27edaff3"
    assert p.outcome_digest == _FIXED_OUTCOME_DIGEST
    assert p.outcome_digest == expected == selection[16].source_observation_identities[0][1]
    changed = (protocol_hash("revealed_outcome/v1", {"oracle_key_id": _oid(p.oracle_key_id), "revealed_observation": p.revealed_observation}), protocol_hash("revealed_outcome/v1", {"oracle_key_id": p.oracle_key_id, "revealed_observation": "f64:0000000000000000"}))
    assert all(value != expected for value in changed)
    assert _p31(selection, p2, predecessor) is None


@pytest.mark.parametrize("case", ("world", "transform", "observation", "occurrences", "coherent"), ids=("wrong-hidden-world", "wrong-key-transform", "wrong-f64-observation", "projection-selector-copied-digests", "coherent-wrong-value-rehash"))
def test_3o_3_1_rejects_wrong_reconstruction_and_every_digest_occurrence(case: str, monkeypatch: pytest.MonkeyPatch, p2_bundle: Bundle) -> None:
    selection, p2, predecessor = _scope(p2_bundle)
    p = _projection(p2)
    cases: list[tuple[Selection, P2Selection, Predecessor]] = []
    if case == "world":
        cases.append((selection, p2, harness.replace_oracle_predecessor_field(predecessor, 10, p2_bundle[4][12][10])))
    elif case == "transform":
        key = (*p.key_fields[:4], "9001", *p.key_fields[5:])
        wrong_transform = oracle.transform_key(key)
        monkeypatch.setattr(oracle, "transform_key", lambda key_fields: wrong_transform)
        cases.append((selection, p2, predecessor))
    elif case == "observation":
        cases.append((selection, _with_projection(p2, 0, harness.replace_source_observation_field(p, "revealed_observation", "f64:0000000000000000")), predecessor))
    elif case == "occurrences":
        cases.append((selection, _with_projection(p2, 0, harness.replace_source_observation_field(p, "outcome_digest", _h64(p.outcome_digest))), predecessor))
        selector = selection[16]
        pair = selector.source_observation_identities[0]
        for digest in (_h64(pair[1]), selector.source_observation_identities[1][1]):
            cases.append((_selector(selection, source_observation_identities=_at(selector.source_observation_identities, 0, (pair[0], digest))), p2, predecessor))
    else:
        value = "f64:0000000000000000"
        digest = protocol_hash("revealed_outcome/v1", {"oracle_key_id": p.oracle_key_id, "revealed_observation": value})
        changed = harness.replace_source_observation_field(p, "revealed_observation", value)
        changed = harness.replace_source_observation_field(changed, "outcome_digest", digest)
        selector = selection[16]
        pair = selector.source_observation_identities[0]
        cases.append((_selector(selection, source_observation_identities=_at(selector.source_observation_identities, 0, (pair[0], digest))), _with_projection(p2, 0, changed), predecessor))
    for changed_selection, changed_p2, changed_predecessor in cases:
        failure = _p31(changed_selection, changed_p2, changed_predecessor)
        assert failure is not None and failure[0] == _CODES[2]


@pytest.mark.parametrize("case", ("candidate", "group", "digest", "arm", "schema", "seed-value", "seed-bool", "serialized-uppercase", "serialized-malformed", "u", "world", "z"), ids=("candidate-id", "comparison-group-id", "digest", "intervention-arm", "schema-version", "seed-value", "seed-bool", "serialized-key-uppercase", "serialized-key-malformed", "u", "world-id", "z"))
def test_3o_4_owned_projection_field_fails_only_at_3o_4_1(case: str, monkeypatch: pytest.MonkeyPatch, p2_bundle: Bundle) -> None:
    selection, p2, predecessor = _scope(p2_bundle)
    p, other = _projection(p2), _projection(p2, 1)
    changes: dict[str, tuple[str, object]] = {"candidate": ("candidate_id", _projection(p2, 2).candidate_id), "group": ("comparison_group_id", "group-01"), "digest": ("digest", _h64(p.digest)), "arm": ("intervention_arm", "sgd"), "schema": ("schema_version", "broader-replication-calibration-source-observation/v2"), "seed-value": ("seed", p.seed + 1), "seed-bool": ("seed", True), "serialized-uppercase": ("serialized_key_hex", p.serialized_key_hex.upper()), "serialized-malformed": ("serialized_key_hex", "not-hex"), "u": ("u", other.u), "world": ("world_id", "d3_adam"), "z": ("z", other.z)}
    field, value = changes[case]
    changed = _unsafe(p, **{field: value})
    changed_p2 = _with_projection(p2, 0, changed)
    assert _p20(selection, changed_p2, predecessor) is None
    assert _p21(selection, changed_p2) is None
    assert _p31(selection, changed_p2, predecessor) is None
    calls = {"identity": 0, "match": 0, "p3": 0, "reader": 0, "evidence": 0}
    with monkeypatch.context() as context:
        context.setattr(evidence, "source_observation_identity", _counter_trap(calls, "identity"))
        context.setattr(evidence, "_source_observation_matches", _counter_trap(calls, "match"))
        context.setattr(evidence, "_predicate_3o_5", _counter_trap(calls, "p3"), raising=False)
        context.setattr(evidence, "Reader", _counter_trap(calls, "reader"), raising=False)
        context.setattr(evidence, "_write_evidence", _counter_trap(calls, "evidence"), raising=False)
        outcome = _validate(p2_bundle, p2_selections=harness.replace_p2_selection(p2_bundle[3], 0, changed_p2))
    _assert_failure(outcome, 3)
    assert outcome[0] is not None and f"{field} differs" in outcome[0][3]
    assert calls == {"identity": 0, "match": 0, "p3": 0, "reader": 0, "evidence": 0}


def test_3o_4_1_reconstructs_exact_key_bytes_raw_digest_u_z_projection_and_id(p2_bundle: Bundle) -> None:
    selection, p2, predecessor = _scope(p2_bundle)
    p, identity = p2[1][0]
    key_bytes = canonical_json_bytes(list(p.key_fields))
    assert p.serialized_key_hex == key_bytes.hex() and p.digest == hashlib.sha256(key_bytes).hexdigest()
    assert p.digest != protocol_hash("framed-key/v1", {"key_fields": p.key_fields})
    assert p.u == "0.32669743368457238030799771877354942262172698974609375" and p.z == "-0.449050999389407436070018932447"
    assert tuple(harness.source_observation_mapping(p)) == harness.SOURCE_OBSERVATION_FIELD_NAMES
    assert identity == harness.expected_source_observation_identity(p)
    assert _p41(selection, p2, predecessor) is None


@pytest.mark.parametrize(("changed_fields", "winner"), ((("candidate_id", "serialized_key_hex"), "candidate_id"), (("comparison_group_id", "digest"), "comparison_group_id"), (("digest", "intervention_arm"), "digest"), (("intervention_arm", "namespace"), "intervention_arm"), (("namespace", "replication_id"), "namespace"), (("replication_id", "schema_version"), "replication_id"), (("schema_version", "seed"), "schema_version"), (("seed", "serialized_key_hex"), "seed"), (("serialized_key_hex", "u"), "serialized_key_hex"), (("u", "world_id"), "u"), (("world_id", "z"), "world_id"), (("candidate_id", "namespace", "z"), "candidate_id"), (("comparison_group_id", "replication_id", "world_id"), "comparison_group_id"), (("digest", "schema_version", "u"), "digest")), ids=("candidate-id-before-serialized-key", "comparison-group-id-before-digest", "digest-before-intervention-arm", "intervention-arm-before-namespace", "namespace-before-replication-id", "replication-id-before-schema-version", "schema-version-before-seed", "seed-before-serialized-key", "serialized-key-before-u", "u-before-world-id", "world-id-before-z", "candidate-id-before-namespace-and-z", "comparison-group-id-before-replication-id-and-world-id", "digest-before-schema-version-and-u"))
def test_3o_4_1_compound_projection_fault_reports_earliest_declared_field(changed_fields: tuple[str, ...], winner: str, monkeypatch: pytest.MonkeyPatch, p2_bundle: Bundle) -> None:
    selection, p2, predecessor = _scope(p2_bundle)
    p, other = _projection(p2), _projection(p2, 1)
    bad_values: dict[str, object] = {"candidate_id": _projection(p2, 2).candidate_id, "comparison_group_id": "group-01", "digest": _h64(p.digest), "intervention_arm": "sgd", "namespace": "rde.broader.calibration-outcome/v2", "replication_id": "calibration-00-r0002", "schema_version": "broader-replication-calibration-source-observation/v2", "seed": p.seed + 1, "serialized_key_hex": "00", "u": other.u, "world_id": "d3_adam", "z": other.z}
    changed = _unsafe(p, **{field: bad_values[field] for field in changed_fields})
    changed_p2 = _with_projection(p2, 0, changed)
    assert _p21(selection, changed_p2) is None
    assert _p31(selection, changed_p2, predecessor) is None
    calls = {"identity": 0, "match": 0}
    with monkeypatch.context() as context:
        context.setattr(evidence, "source_observation_identity", _counter_trap(calls, "identity"))
        context.setattr(evidence, "_source_observation_matches", _counter_trap(calls, "match"))
        outcome = _validate(p2_bundle, p2_selections=harness.replace_p2_selection(p2_bundle[3], 0, changed_p2))
    _assert_failure(outcome, 3)
    assert outcome[0] is not None and f"{winner} differs" in outcome[0][3]
    assert calls == {"identity": 0, "match": 0}


def test_raw_key_digest_has_independent_fixed_vector_and_complete_preimage(p2_bundle: Bundle) -> None:
    p = _projection(_scope(p2_bundle)[1])
    key_fields = ("rde.broader.calibration-outcome/v1", "broader-closed-loop-replication/v1", "broader_selected_only_oracle/v1", "h_adam_low", "9000", "group-00", "adam", "calibration-00-r0001")
    canonical_key_bytes = canonical_json_bytes(list(key_fields))
    changed = tuple(hashlib.sha256(canonical_json_bytes(list(_at(key_fields, index, value)))).hexdigest() for index, value in enumerate(("rde.broader.calibration-outcome/v2", "broader-closed-loop-replication/v2", "broader_selected_only_oracle/v2", "d3_adam", "9001", "group-01", "sgd", "calibration-00-r0002")))
    expected = hashlib.sha256(canonical_key_bytes).hexdigest()
    assert expected == p.digest == _FIXED_RAW_KEY_DIGEST
    assert canonical_key_bytes.hex() == p.serialized_key_hex
    assert all(value != expected for value in changed)


@pytest.mark.parametrize("case", ("extra", "framed", "serialized", "transform", "order", "identity"), ids=("extra-projection", "raw-versus-framed-digest", "serialized-key-hex", "u-and-z", "copied-cross-selection-reordered", "identity-and-uniqueness"))
def test_3o_4_1_rejects_complete_projection_identity_order_and_uniqueness(case: str, monkeypatch: pytest.MonkeyPatch, p2_bundle: Bundle) -> None:
    selection, p2, predecessor = _scope(p2_bundle)
    sources, p = p2[1], _projection(p2)
    changed: list[P2Selection] = []
    if case == "extra":
        changed.append(_with_sources(p2, (*sources, sources[-1])))
    elif case in {"framed", "serialized"}:
        value = protocol_hash("framed-key/v1", {"key_fields": p.key_fields}) if case == "framed" else "00"
        name = "digest" if case == "framed" else "serialized_key_hex"
        projection = harness.replace_source_observation_field(p, name, value)
        changed.append(_with_projection(p2, 0, projection, harness.expected_source_observation_identity(projection)))
    elif case == "transform":
        other = _projection(p2, 1)
        for name, value in (("u", other.u), ("z", other.z)):
            projection = harness.replace_source_observation_field(p, name, value)
            changed.append(_with_projection(p2, 0, projection, harness.expected_source_observation_identity(projection)))
    elif case == "order":
        cross = p2_bundle[3][3][1][0]
        changed.extend((_with_sources(p2, _at(sources, 0, sources[1])), _with_sources(p2, _at(sources, 0, cross)), _with_sources(p2, tuple(reversed(sources)))))
    else:
        forged = _p41(selection, _with_projection(p2, 0, p, _h64(sources[0][1])), predecessor)
        assert forged is not None and forged[0] == _CODES[3]
        collision = "0" * 64
        monkeypatch.setattr(evidence, "source_observation_identity", lambda projection: collision)
        changed.append(_with_sources(p2, tuple((projection, collision) for projection, _ in sources)))
    for changed_p2 in changed:
        failure = _p41(selection, changed_p2, predecessor)
        assert failure is not None and failure[0] == _CODES[3]
        if case == "identity":
            assert "duplicated" in failure[1]


def test_full_valid_bundle_completes_all_318_selections_and_3180_observations(p2_bundle: Bundle) -> None:
    assert _validate(p2_bundle) == (None, (318,) * 11)


@pytest.mark.parametrize("_run", range(3), ids=("fresh-process-1", "fresh-process-2", "fresh-process-3"))
def test_cold_minimal_source_identity_process_meets_approved_bound(_run: int) -> None:
    started = time.perf_counter_ns()
    completed = subprocess.run([sys.executable, "-c", _COLD_MINIMAL_SCRIPT], check=False, capture_output=True, text=True, timeout=10.0)
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == _FIXED_ID
    assert elapsed_ms <= 250.000


@pytest.mark.parametrize("family", (0, 1, 2), ids=("later-3o.2.0-before-earlier-3o.2.1", "later-3o.2.1-before-earlier-3o.3.1", "later-3o.3.1-before-earlier-3o.4.1"))
def test_global_predicate_family_major_order_beats_selection_local_order(family: int, p2_bundle: Bundle) -> None:
    selections, p2s = _fault(family + 1, 0, p2_bundle[0], p2_bundle[3])
    selections, p2s = _fault(family, 1, selections, p2s)
    _assert_failure(_validate(p2_bundle, selections=selections, p2_selections=p2s), family, 1)


def test_complete_p1_failure_precedes_every_p2_fault(p2_bundle: Bundle) -> None:
    selections, p2s = p2_bundle[0], p2_bundle[3]
    first = harness.replace_selection_field(selections[0], harness.EXECUTION_SPECIFICATION_ID_INDEX, _h64(selections[0][harness.EXECUTION_SPECIFICATION_ID_INDEX]))
    selections = harness.replace_bundle_selection(selections, 0, first)
    selections, p2s = _fault(0, 0, selections, p2s)
    failure, counts = _validate(p2_bundle, selections=selections, p2_selections=p2s)
    assert failure is not None and failure[:3] == ("CALIBRATION_EXECUTION_SPECIFICATION_MISMATCH", "calibration/3o.1.0/execution_attestation_binding", 0)
    assert counts == (1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)


def test_same_p2_family_always_uses_earliest_canonical_selection(p2_bundle: Bundle) -> None:
    for family in range(4):
        selections, p2s = _fault(family, 4, p2_bundle[0], p2_bundle[3])
        selections, p2s = _fault(family, 1, selections, p2s)
        _assert_failure(_validate(p2_bundle, selections=selections, p2_selections=p2s), family, 1)


def test_observation_field_uniqueness_and_no_later_stage_stop_boundaries(monkeypatch: pytest.MonkeyPatch, p2_bundle: Bundle) -> None:
    selection, p2, predecessor = _scope(p2_bundle)
    sources = p2[1]
    changed = sources
    for index in (4, 1):
        p = changed[index][0]
        key = (*p.key_fields[:6], p.key_fields[7], p.key_fields[6])
        changed = harness.replace_source_evidence_at(changed, index, (harness.replace_source_observation_field(p, "key_fields", key), changed[index][1]))
    failure = _p21(selection, _with_sources(p2, changed))
    assert failure is not None and "source observation[1]" in failure[1]
    p = _projection(p2)
    multi = _unsafe(p, digest=_h64(p.digest), serialized_key_hex="00")
    later = {"identity": 0}
    with monkeypatch.context() as context:
        context.setattr(evidence, "_source_observation_matches", lambda *args: later.__setitem__("identity", later["identity"] + 1))
        failure = _p41(selection, _with_projection(p2, 0, multi), predecessor)
    assert failure is not None and "digest differs" in failure[1]
    assert later == {"identity": 0}
    collision = "0" * 64
    collided: tuple[SourceEvidence, ...] = tuple((projection, collision) for projection, _ in sources)
    last = harness.replace_source_observation_field(collided[-1][0], "z", sources[0][0].z)
    with monkeypatch.context() as context:
        context.setattr(evidence, "source_observation_identity", lambda projection: collision)
        relation = _p41(selection, _with_sources(p2, (*collided[:-1], (last, collision))), predecessor)
        unique = _p41(selection, _with_sources(p2, collided), predecessor)
    assert relation is not None and "z differs" in relation[1]
    assert unique is not None and "duplicated" in unique[1]
    calls = {"key": 0, "transform": 0, "mean": 0, "sigma": 0, "identity": 0}
    def trap(name: str) -> Any:
        def fail(*args: object, **kwargs: object) -> object:
            calls[name] += 1
            raise AssertionError(name)
        return fail
    _, p2s = _fault(0, 0, p2_bundle[0], p2_bundle[3])
    with monkeypatch.context() as context:
        for target, attribute, name in ((oracle, "calibration_key", "key"), (oracle, "transform_key", "transform"), (evidence, "_hidden_arm_mean", "mean"), (evidence, "_hidden_observation_sigma", "sigma"), (evidence, "_source_observation_matches", "identity")):
            context.setattr(target, attribute, trap(name))
        _assert_failure(_validate(p2_bundle, p2_selections=p2s), 0)
    assert calls == {"key": 0, "transform": 0, "mean": 0, "sigma": 0, "identity": 0}
    assert tuple(inspect.signature(evidence._validate_stage2f_p2).parameters) == ("selections", "expected_execution_attestation_pairs", "attested_execution_specification_ids", "p2_selections", "expected_predecessors")
    scientific_projection = evidence.__dict__.get("ScientificCalibrationSelectionProjection")
    assert inspect.isclass(scientific_projection)
    assert scientific_projection.__module__ == evidence.__name__
    assert scientific_projection.__qualname__ == "ScientificCalibrationSelectionProjection"
    for name in ("CalibrationSelectionProjection", "calibration_selection_id", "replay_calibration_history_selection", "_predicate_3o_5", "_predicate_3p", "ObservationAuthority", "Reader"):
        assert not hasattr(evidence, name)

# fmt: on
