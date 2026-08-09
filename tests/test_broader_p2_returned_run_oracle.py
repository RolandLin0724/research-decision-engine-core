from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from typing import Any, Literal, cast

import pytest

from research_decision_engine.benchmarks import broader_returned_run as returned
from research_decision_engine.benchmarks.broader_protocol import (
    canonical_json_bytes,
    f64,
    protocol_hash,
    runtime_id,
)
from tests import p2_returned_run_architecture_guard as architecture

type AuthorizationKind = Literal["calibration", "decision"]
type RevealedMutation = Callable[
    [returned.RunRevealedObservationProjection],
    returned.RunRevealedObservationProjection,
]

AUTHORIZATION_FIELDS = ("candidate_id", "kind", "run_id", "source_id")
REVEALED_FIELDS = (
    "authorization",
    "authorization_id",
    "candidate_id",
    "comparison_group_id",
    "digest",
    "intervention_arm",
    "key_fields",
    "namespace",
    "oracle_key_id",
    "oracle_use_id",
    "outcome_digest",
    "replication_id",
    "revealed_observation",
    "seed",
    "serialized_key_hex",
    "u",
    "world_id",
    "z",
)
_NO_RETURN = object()
_EFFECT_LEDGER = {
    "scientific_outputs": 0,
    "recommendations": 0,
    "capabilities_issued": 0,
    "evidence_writes": 0,
    "production_state_mutations": 0,
}


def _authorization(
    kind: AuthorizationKind = "decision",
) -> returned.RunObservationAuthorizationProjection:
    return returned.RunObservationAuthorizationProjection(
        candidate_id="cal-00-adam-r0001" if kind == "calibration" else "g00-adam-r1",
        kind=kind,
        run_id="run-oracle-test",
        source_id=f"{kind}/run-oracle-test/0001",
    )


def _authorization_id(projection: returned.RunObservationAuthorizationProjection) -> str:
    return runtime_id(
        "authorization",
        "authorization_id/v1",
        {
            "candidate_id": projection.candidate_id,
            "kind": projection.kind,
            "run_id": projection.run_id,
            "source_id": projection.source_id,
        },
    )


def _revealed(
    kind: AuthorizationKind = "decision",
    *,
    optional_facts: bool = True,
) -> returned.RunRevealedObservationProjection:
    authorization = _authorization(kind)
    authorization_id = _authorization_id(authorization)
    namespace = f"rde.broader.{kind}-outcome/v1"
    world_id, seed, replication_id = "world-1", 7, "replication-0001"
    comparison_group_id = "group-00" if optional_facts else None
    intervention_arm = "adam" if optional_facts else None
    key_fields: tuple[str, ...]
    if kind == "calibration":
        assert comparison_group_id is not None and intervention_arm is not None
        key_fields = (
            namespace,
            "broader-replication/v3",
            "broader-selected-only-oracle/v1",
            world_id,
            str(seed),
            comparison_group_id,
            intervention_arm,
            replication_id,
        )
    else:
        key_fields = (
            namespace,
            "broader-replication/v3",
            "broader-selected-only-oracle/v1",
            world_id,
            str(seed),
            authorization.candidate_id,
            replication_id,
        )
    oracle_key_id = runtime_id("oracle-key", "oracle_key_id/v1", {"key_fields": list(key_fields)})
    observed = f64(0.25)
    outcome_digest = protocol_hash(
        "revealed_outcome/v1",
        {"oracle_key_id": oracle_key_id, "revealed_observation": observed},
    )
    return returned.RunRevealedObservationProjection(
        authorization=authorization,
        authorization_id=authorization_id,
        candidate_id=authorization.candidate_id,
        comparison_group_id=comparison_group_id,
        digest="a" * 64,
        intervention_arm=intervention_arm,
        key_fields=key_fields,
        namespace=namespace,
        oracle_key_id=oracle_key_id,
        oracle_use_id=f"oracle-use/{authorization_id}/{oracle_key_id}",
        outcome_digest=outcome_digest,
        replication_id=replication_id,
        revealed_observation=observed,
        seed=seed,
        serialized_key_hex=canonical_json_bytes(list(key_fields)).hex(),
        u="0.50000000000000000000000000000000000000000000000000000",
        world_id=world_id,
        z="-0.250000000000000000000000000000",
    )


def _authorization_context(
    projection: returned.RunObservationAuthorizationProjection,
) -> dict[str, object]:
    return {
        "expected_candidate_id": projection.candidate_id,
        "expected_kind": projection.kind,
        "expected_run_id": projection.run_id,
        "expected_source_id": projection.source_id,
        "expected_authorization_id": _authorization_id(projection),
    }


def _revealed_context(
    projection: returned.RunRevealedObservationProjection,
) -> dict[str, object]:
    return {
        "expected_authorization": projection.authorization,
        "expected_authorization_id": projection.authorization_id,
        "expected_namespace": projection.namespace,
        "expected_world_id": projection.world_id,
        "expected_seed": projection.seed,
        "expected_candidate_id": projection.candidate_id,
        "expected_comparison_group_id": projection.comparison_group_id,
        "expected_intervention_arm": projection.intervention_arm,
        "expected_replication_id": projection.replication_id,
        "expected_key_fields": projection.key_fields,
        "expected_oracle_key_id": projection.oracle_key_id,
        "expected_outcome_digest": projection.outcome_digest,
        "expected_oracle_use_id": projection.oracle_use_id,
    }


def _validate_authorization(
    projection: returned.RunObservationAuthorizationProjection,
    context: dict[str, object],
) -> None:
    returned.validate_observation_authorization_relation(projection, **cast(Any, context))


def _validate_revealed(
    projection: returned.RunRevealedObservationProjection,
    context: dict[str, object],
) -> None:
    returned.validate_revealed_observation_relations(projection, **cast(Any, context))


def _failure(
    operation: Callable[[], object], *, category: str, path: str
) -> returned.ReturnedRunProjectionError:
    before = tuple(_EFFECT_LEDGER.items())
    result = _NO_RETURN
    with pytest.raises(returned.ReturnedRunProjectionError) as captured:
        result = operation()
    error = captured.value
    assert result is _NO_RETURN
    assert tuple(_EFFECT_LEDGER.items()) == before
    assert not any(_EFFECT_LEDGER.values())
    assert (error.category, error.path) == (category, path)
    expected_code = (
        returned.EXECUTION_RETURNED_SCIENTIFIC_RECORD_INVALID
        if category == "scientific_record_invalid"
        else None
    )
    assert error.failure_code == expected_code
    assert all(
        not hasattr(error, name)
        for name in ("scientific_output", "recommendation", "capability", "evidence_write")
    )
    return error


def _structural(operation: Callable[[], object], path: str) -> None:
    _failure(operation, category="structural_projection_invalid", path=path)


def _scientific(operation: Callable[[], object], path: str) -> None:
    _failure(operation, category="scientific_record_invalid", path=path)


def _missing(operation: Callable[[], object], path: str) -> None:
    _failure(operation, category="missing_relation_context", path=path)


def test_oracle_projection_schemas_and_encoded_field_order_are_exact() -> None:
    authorization, revealed = _authorization(), _revealed()
    assert tuple(field.name for field in fields(type(authorization))) == AUTHORIZATION_FIELDS
    assert tuple(field.name for field in fields(type(revealed))) == REVEALED_FIELDS
    assert tuple(returned.projection_as_dict(authorization)) == AUTHORIZATION_FIELDS
    assert tuple(returned.projection_as_dict(revealed)) == REVEALED_FIELDS


@pytest.mark.parametrize("kind", ["calibration", "decision"])
def test_authorization_decoder_round_trips_both_closed_kinds(kind: AuthorizationKind) -> None:
    projection = _authorization(kind)
    raw = returned.projection_as_dict(projection)
    assert returned.decode_run_observation_authorization_projection(raw) == projection
    assert (
        returned.decode_run_observation_authorization_projection(dict(reversed(raw.items())))
        == projection
    )


@pytest.mark.parametrize("field", AUTHORIZATION_FIELDS)
def test_authorization_identity_is_deterministic_and_field_total(field: str) -> None:
    projection = _authorization()
    expected = _authorization_id(projection)
    assert returned.recompute_observation_authorization_id(projection) == expected
    assert returned.recompute_observation_authorization_id(projection) == expected
    changes: dict[str, object] = {
        "candidate_id": "g00-sgd-r1",
        "kind": "calibration",
        "run_id": "run-other",
        "source_id": "decision/run-other/0001",
    }
    mutated = replace(projection, **cast(Any, {field: changes[field]}))
    assert returned.recompute_observation_authorization_id(mutated) != expected


@pytest.mark.parametrize(
    ("field", "changed", "path"),
    [
        ("expected_candidate_id", "g00-sgd-r1", "candidate_id"),
        ("expected_kind", "calibration", "kind"),
        ("expected_run_id", "run-other", "run_id"),
        ("expected_source_id", "decision/run-other/0001", "source_id"),
        ("expected_authorization_id", "authorization:other", "authorization_id"),
    ],
)
def test_authorization_context_is_exact_and_scientific(
    field: str, changed: object, path: str
) -> None:
    projection = _authorization()
    context = _authorization_context(projection)
    context[field] = changed
    _scientific(
        lambda: _validate_authorization(projection, context), f"observation_authorization.{path}"
    )


def test_authorization_missing_context_remains_distinct() -> None:
    _missing(
        lambda: returned.validate_observation_authorization_relation(_authorization()),
        "observation_authorization",
    )


@pytest.mark.parametrize("missing", AUTHORIZATION_FIELDS)
def test_authorization_decoder_rejects_missing_and_extra_fields(missing: str) -> None:
    raw = returned.projection_as_dict(_authorization())
    del raw[missing]
    _structural(
        lambda: returned.decode_run_observation_authorization_projection(raw),
        f"observation_authorization.{missing}",
    )
    extra = returned.projection_as_dict(_authorization()) | {"unexpected": None}
    _structural(
        lambda: returned.decode_run_observation_authorization_projection(extra),
        "observation_authorization",
    )


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("candidate_id", True),
        ("kind", "other"),
        ("kind", 1),
        ("run_id", "e\u0301"),
        ("source_id", []),
    ],
)
def test_authorization_decoder_rejects_types_tags_and_non_nfc(field: str, changed: object) -> None:
    raw = returned.projection_as_dict(_authorization())
    raw[field] = changed
    _structural(
        lambda: returned.decode_run_observation_authorization_projection(raw),
        f"observation_authorization.{field}",
    )


def test_projections_are_frozen_records_without_live_capability_methods() -> None:
    projection = _authorization()
    with pytest.raises(FrozenInstanceError):
        projection.run_id = "changed"  # type: ignore[misc]
    for value in (projection, _revealed()):
        for name in ("issue", "promote", "restore", "from_id", "from_mapping"):
            assert not hasattr(value, name)


@pytest.mark.parametrize("kind", ["calibration", "decision"])
def test_revealed_decoder_round_trips_both_kinds(kind: AuthorizationKind) -> None:
    projection = _revealed(kind)
    raw = returned.projection_as_dict(projection)
    assert returned.decode_run_revealed_observation_projection(raw) == projection
    assert (
        returned.decode_run_revealed_observation_projection(dict(reversed(raw.items())))
        == projection
    )
    returned.validate_revealed_observation_projection(projection)
    _validate_revealed(projection, _revealed_context(projection))


@pytest.mark.parametrize("optional_facts", [False, True])
def test_decision_optional_pair_accepts_exact_null_and_present_forms(optional_facts: bool) -> None:
    projection = _revealed(optional_facts=optional_facts)
    returned.validate_revealed_observation_projection(projection)
    _validate_revealed(projection, _revealed_context(projection))


def test_nested_authorization_decodes_before_outer_fields() -> None:
    raw = returned.projection_as_dict(_revealed())
    nested = cast(dict[str, object], raw["authorization"])
    nested["kind"] = "other"
    raw["authorization_id"] = True
    _structural(
        lambda: returned.decode_run_revealed_observation_projection(raw),
        "observation_authorization.kind",
    )


@pytest.mark.parametrize(
    ("mutation", "path"),
    [
        (lambda value: replace(value, authorization_id="authorization:other"), "authorization_id"),
        (lambda value: replace(value, candidate_id="g00-sgd-r1"), "candidate_id"),
    ],
)
def test_revealed_authorization_relations_fail_scientifically(
    mutation: RevealedMutation, path: str
) -> None:
    _scientific(
        lambda: returned.validate_revealed_observation_projection(mutation(_revealed())),
        f"revealed_observation.{path}",
    )


@pytest.mark.parametrize(
    "projection",
    [
        replace(_revealed(), intervention_arm=None),
        replace(
            _revealed("calibration"),
            comparison_group_id=None,
            intervention_arm=None,
        ),
    ],
)
def test_optional_pair_and_calibration_requirements_fail_closed(
    projection: returned.RunRevealedObservationProjection,
) -> None:
    _scientific(
        lambda: returned.validate_revealed_observation_projection(projection),
        "revealed_observation.comparison_group_id",
    )


@pytest.mark.parametrize(
    ("mutation", "path"),
    [
        (lambda value: replace(value, key_fields=value.key_fields[:-1]), "key_fields"),
        (
            lambda value: replace(
                value,
                key_fields=(
                    value.key_fields[3],
                    *value.key_fields[1:3],
                    value.key_fields[0],
                    *value.key_fields[4:],
                ),
            ),
            "key_fields.namespace",
        ),
        (
            lambda value: replace(
                value,
                key_fields=(*value.key_fields[:2], value.key_fields[1], *value.key_fields[3:]),
            ),
            "oracle_key_id",
        ),
        (lambda value: replace(value, world_id="world-2"), "key_fields.world_id"),
        (lambda value: replace(value, seed=8), "key_fields.seed"),
        (
            lambda value: replace(value, replication_id="replication-0002"),
            "key_fields.replication_id",
        ),
    ],
)
def test_key_count_order_duplicates_and_bound_facts_fail(
    mutation: RevealedMutation, path: str
) -> None:
    _scientific(
        lambda: returned.validate_revealed_observation_projection(mutation(_revealed())),
        f"revealed_observation.{path}",
    )


@pytest.mark.parametrize(
    ("mutation", "path"),
    [
        (lambda value: replace(value, oracle_key_id="oracle-key:other"), "oracle_key_id"),
        (lambda value: replace(value, outcome_digest="b" * 64), "outcome_digest"),
        (lambda value: replace(value, oracle_use_id="oracle-use/other"), "oracle_use_id"),
        (lambda value: replace(value, serialized_key_hex="00"), "serialized_key_hex"),
    ],
)
def test_key_outcome_use_and_serialized_relations_are_recomputed(
    mutation: RevealedMutation, path: str
) -> None:
    _scientific(
        lambda: returned.validate_revealed_observation_projection(mutation(_revealed())),
        f"revealed_observation.{path}",
    )


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("digest", "A" * 64),
        ("digest", "a" * 63),
        ("outcome_digest", "g" * 64),
        ("serialized_key_hex", "0"),
        ("serialized_key_hex", "AA"),
        ("serialized_key_hex", "gg"),
    ],
)
def test_revealed_decoder_enforces_h64_and_hexbytes(field: str, changed: object) -> None:
    raw = returned.projection_as_dict(_revealed())
    raw[field] = changed
    _structural(
        lambda: returned.decode_run_revealed_observation_projection(raw),
        f"revealed_observation.{field}",
    )


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("revealed_observation", "f64:7ff0000000000000"),
        ("revealed_observation", "f64:8000000000000000"),
        ("revealed_observation", 0.25),
        ("seed", True),
        ("seed", 2**63),
    ],
)
def test_revealed_decoder_enforces_finite_canonical_f64_and_exact_i64(
    field: str, changed: object
) -> None:
    raw = returned.projection_as_dict(_revealed())
    raw[field] = changed
    _structural(
        lambda: returned.decode_run_revealed_observation_projection(raw),
        f"revealed_observation.{field}",
    )


@pytest.mark.parametrize(
    ("mutation", "path"),
    [
        (lambda raw: raw.pop("authorization"), "revealed_observation.authorization"),
        (lambda raw: raw.update(unexpected=None), "revealed_observation"),
        (
            lambda raw: raw.update(key_fields=tuple(cast(list[object], raw["key_fields"]))),
            "revealed_observation.key_fields",
        ),
        (
            lambda raw: cast(list[object], raw["key_fields"]).__setitem__(0, "e\u0301"),
            "revealed_observation.key_fields[0]",
        ),
        (lambda raw: raw.update(u="e\u0301"), "revealed_observation.u"),
    ],
)
def test_revealed_decoder_is_closed_ordered_and_nfc(
    mutation: Callable[[dict[str, object]], object], path: str
) -> None:
    raw = returned.projection_as_dict(_revealed())
    mutation(raw)
    _structural(lambda: returned.decode_run_revealed_observation_projection(raw), path)


@pytest.mark.parametrize(
    ("field", "changed", "path"),
    [
        ("expected_namespace", "other.namespace/v1", "namespace"),
        ("expected_world_id", "world-2", "world_id"),
        ("expected_seed", 8, "seed"),
        ("expected_candidate_id", "g00-sgd-r1", "candidate_id"),
        ("expected_comparison_group_id", None, "comparison_group_id"),
        ("expected_intervention_arm", None, "intervention_arm"),
        ("expected_replication_id", "replication-0002", "replication_id"),
        ("expected_key_fields", ("wrong",), "key_fields"),
        ("expected_oracle_key_id", "oracle-key:other", "oracle_key_id"),
        ("expected_outcome_digest", "b" * 64, "outcome_digest"),
        ("expected_oracle_use_id", "oracle-use/other", "oracle_use_id"),
    ],
)
def test_every_outer_revealed_context_mismatch_is_scientific(
    field: str, changed: object, path: str
) -> None:
    projection = _revealed()
    context = _revealed_context(projection)
    context[field] = changed
    _scientific(lambda: _validate_revealed(projection, context), f"revealed_observation.{path}")


def test_nested_expected_authorization_precedes_outer_relations() -> None:
    original = _revealed()
    projection = replace(
        original,
        authorization=replace(original.authorization, candidate_id="g00-sgd-r1"),
    )
    context = _revealed_context(original)
    context["expected_namespace"] = "other.namespace/v1"
    _scientific(
        lambda: _validate_revealed(projection, context),
        "observation_authorization.candidate_id",
    )


@pytest.mark.parametrize(
    ("field", "path"),
    [
        ("expected_authorization", "authorization"),
        ("expected_authorization_id", "authorization_id"),
        ("expected_namespace", "namespace"),
        ("expected_world_id", "world_id"),
        ("expected_seed", "seed"),
        ("expected_candidate_id", "candidate_id"),
        ("expected_comparison_group_id", "comparison_group_id"),
        ("expected_intervention_arm", "intervention_arm"),
        ("expected_replication_id", "replication_id"),
        ("expected_key_fields", "key_fields"),
        ("expected_oracle_key_id", "oracle_key_id"),
        ("expected_outcome_digest", "outcome_digest"),
        ("expected_oracle_use_id", "oracle_use_id"),
    ],
)
def test_every_missing_revealed_context_fact_is_distinct(field: str, path: str) -> None:
    projection = _revealed(optional_facts=False)
    context = _revealed_context(projection)
    del context[field]
    _missing(lambda: _validate_revealed(projection, context), f"revealed_observation.{path}")


def test_projection_comparisons_are_validated_and_field_total() -> None:
    authorization, revealed = _authorization(), _revealed()
    assert returned.observation_authorization_projections_match(
        authorization, replace(authorization)
    )
    assert not returned.observation_authorization_projections_match(
        authorization, replace(authorization, source_id="decision/other/0001")
    )
    assert returned.revealed_observation_projections_match(revealed, replace(revealed))
    assert not returned.revealed_observation_projections_match(
        revealed, replace(revealed, digest="b" * 64)
    )
    assert not returned.revealed_observation_projections_match(revealed, replace(revealed, u="0.6"))


def test_source_retains_oracle_leaf_projections_and_no_live_authority_surface() -> None:
    module_path = Path(returned.__file__ or "")
    source = module_path.read_text(encoding="utf-8")
    classes = architecture.top_level_class_names(source)
    assert {
        "RunObservationAuthorizationProjection",
        "RunRevealedObservationProjection",
    } <= classes
    imported_roots = architecture.imported_module_roots(source)
    called_names = architecture.called_function_names(source)
    assert all(passed for _name, passed in architecture.returned_run_architecture_checks(source))
    assert architecture.imports_are_authorized(imported_roots)
    assert called_names.isdisjoint(architecture.PERMANENT_FORBIDDEN_CALLS)
    assert architecture.is_exact_authorized_top_level_class_set(classes)
    assert all(pattern not in source for pattern in architecture.forbidden_source_or_ast_patterns())
    assert architecture.dynamic_projection_class_assignments(source) == set()
    assert not architecture.is_exact_authorized_top_level_class_set(
        classes | {"RunUnexpectedStage2Projection"}
    )
