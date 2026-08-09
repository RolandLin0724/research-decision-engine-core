from __future__ import annotations

import ast
import statistics
from collections.abc import Callable
from dataclasses import fields, replace
from functools import partial
from pathlib import Path
from typing import Any, cast

import pytest

from research_decision_engine.belief_models import (
    CALIBRATED_SIGMA_MODEL_ID,
    CALIBRATED_SIGMA_MODEL_VERSION,
    SIGMA_FLOOR,
    MatchedEffectObservation,
)
from research_decision_engine.benchmarks import broader_returned_run as returned
from research_decision_engine.benchmarks.broader_calibration_history import (
    CALIBRATION_SIGMA_DDOF,
    CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
)
from research_decision_engine.benchmarks.broader_oracle import (
    CALIBRATION_NAMESPACE,
    RevealedObservation,
)
from research_decision_engine.benchmarks.broader_protocol import (
    canonical_json_bytes,
    f64,
    protocol_hash,
    runtime_id,
)
from research_decision_engine.benchmarks.broader_runner import (
    CalibrationDeployment,
    CalibrationGroupEstimate,
    calibration_sigma_provenance_sha256,
)
from research_decision_engine.benchmarks.broader_worlds import GROUP_IDS
from research_decision_engine.reasoning import Provenance
from tests import p2_returned_run_architecture_guard as architecture

RUN_ID = "run:calibration-projection"
WORLD_ID = "world-calibration-projection"
SEED = 1000
LINEAGE_ID = f"lineage/{RUN_ID}"

ESTIMATE_FIELDS = (
    "belief_model_id",
    "calibration_prefix_id",
    "comparison_group_id",
    "ddof",
    "effects",
    "estimated_sigma",
    "lineage_id",
    "observations",
    "physical_cost",
    "provenance_sha256",
    "raw_sample_standard_deviation",
    "sample_count",
    "sample_mean",
    "sigma_estimate_id",
    "sigma_floor",
    "source_effect_ids",
    "source_sequence_cutoff",
)
CALIBRATION_FIELDS = ("cost", "effects", "estimates", "observations")
_NO_RESULT = object()
_EFFECT_LEDGER = (
    ("scientific_outputs", 0),
    ("recommendations", 0),
    ("capabilities_issued", 0),
    ("evidence_writes", 0),
    ("production_mutations", 0),
)


def _failure(
    call: Callable[[], object],
    *,
    category: returned.ValidationCategory,
    path: str | None = None,
) -> returned.ReturnedRunProjectionError:
    before = _EFFECT_LEDGER
    result: object = _NO_RESULT
    with pytest.raises(returned.ReturnedRunProjectionError) as captured:
        result = call()
    error = captured.value
    assert result is _NO_RESULT
    assert before == _EFFECT_LEDGER
    assert error.category == category
    assert error.failure_code == (
        returned.EXECUTION_RETURNED_SCIENTIFIC_RECORD_INVALID
        if category == "scientific_record_invalid"
        else None
    )
    if path is not None:
        assert error.path == path
    assert all(
        not hasattr(error, name)
        for name in ("scientific_output", "recommendation", "capability", "evidence_write")
    )
    return error


def _authorization_id(candidate_id: str, source_id: str) -> str:
    return runtime_id(
        "authorization",
        "authorization_id/v1",
        {
            "candidate_id": candidate_id,
            "kind": "calibration",
            "run_id": RUN_ID,
            "source_id": source_id,
        },
    )


def _observation(
    *,
    group_index: int,
    replication_index: int,
    arm: str,
    value: float,
) -> RevealedObservation:
    group_id = GROUP_IDS[group_index]
    candidate_id = f"cal-{group_index:02d}-{arm}-r{replication_index:04d}"
    replication_id = f"calibration-{group_index:02d}-r{replication_index:04d}"
    prefix_id = f"calibration-prefix/{WORLD_ID}/{SEED}/{group_id}"
    source_id = f"{prefix_id}/{candidate_id}"
    authorization_id = _authorization_id(candidate_id, source_id)
    key_fields = (
        CALIBRATION_NAMESPACE,
        "broader-closed-loop-replication/v1",
        "calibration",
        WORLD_ID,
        str(SEED),
        group_id,
        arm,
        replication_id,
    )
    oracle_key_id = runtime_id(
        "oracle-key",
        "oracle_key_id/v1",
        {"key_fields": list(key_fields)},
    )
    outcome_digest = protocol_hash(
        "revealed_outcome/v1",
        {"oracle_key_id": oracle_key_id, "revealed_observation": f64(value)},
    )
    return RevealedObservation(
        oracle_key_id=oracle_key_id,
        oracle_use_id=f"oracle-use/{authorization_id}/{oracle_key_id}",
        authorization_id=authorization_id,
        namespace=CALIBRATION_NAMESPACE,
        world_id=WORLD_ID,
        seed=SEED,
        candidate_id=candidate_id,
        comparison_group_id=group_id,
        intervention_arm=arm,
        replication_id=replication_id,
        key_fields=key_fields,
        serialized_key_hex=canonical_json_bytes(list(key_fields)).hex(),
        digest=protocol_hash("calibration-test-key/v1", list(key_fields)),
        u="0.5",
        z="0.0",
        revealed_observation=value,
        outcome_digest=outcome_digest,
    )


def _estimate(group_index: int = 0) -> CalibrationGroupEstimate:
    group_id = GROUP_IDS[group_index]
    prefix_id = f"calibration-prefix/{WORLD_ID}/{SEED}/{group_id}"
    effects: list[MatchedEffectObservation] = []
    observations: list[RevealedObservation] = []
    for replication_index in range(1, 6):
        effect_value = 0.1 * replication_index + 0.01 * group_index
        adam = _observation(
            group_index=group_index,
            replication_index=replication_index,
            arm="adam",
            value=effect_value,
        )
        sgd = _observation(
            group_index=group_index,
            replication_index=replication_index,
            arm="sgd",
            value=0.0,
        )
        observations.extend((adam, sgd))
        replication_id = f"calibration-{group_index:02d}-r{replication_index:04d}"
        effects.append(
            MatchedEffectObservation(
                effect_id=f"calibration-effect/{prefix_id}/{replication_id}",
                comparison_group_id=group_id,
                observed_effect=round(adam.revealed_observation - sgd.revealed_observation, 12),
                available_sequence=0,
                source_kind="calibration",
                source_ids=(adam.candidate_id, sgd.candidate_id),
                created_at=(
                    f"2000-01-01T00:00:00.000000Z#calibration:{group_index}:{replication_index}"
                ),
                provenance=Provenance.create(
                    method="broader-replication-calibration-effect",
                    version="broader-calibration-effect/v1",
                    details={
                        "comparison_group_id": group_id,
                        "replication_id": replication_id,
                        "scientific_evidence": False,
                        "world_id": WORLD_ID,
                    },
                ),
            )
        )
    effect_tuple = tuple(effects)
    values = tuple(item.observed_effect for item in effect_tuple)
    sample_mean = statistics.mean(values)
    sample_sd = statistics.stdev(values)
    sigma_estimate_id = f"sigma-estimate/{prefix_id}"
    source_effect_ids = tuple(item.effect_id for item in effect_tuple)
    provenance_sha256 = calibration_sigma_provenance_sha256(
        sigma_estimate_id=sigma_estimate_id,
        calibration_prefix_id=prefix_id,
        comparison_group_id=group_id,
        source_effect_ids=source_effect_ids,
        source_sequence_cutoff=CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
        sample_count=len(effect_tuple),
        sample_mean=sample_mean,
        raw_sample_standard_deviation=sample_sd,
        ddof=CALIBRATION_SIGMA_DDOF,
        sigma_floor=SIGMA_FLOOR,
        estimated_sigma=max(sample_sd, SIGMA_FLOOR),
        belief_model_id=CALIBRATED_SIGMA_MODEL_ID,
        lineage_id=LINEAGE_ID,
        effects=effect_tuple,
    )
    return CalibrationGroupEstimate(
        sigma_estimate_id=sigma_estimate_id,
        calibration_prefix_id=prefix_id,
        comparison_group_id=group_id,
        source_effect_ids=source_effect_ids,
        source_sequence_cutoff=CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
        sample_count=len(effect_tuple),
        sample_mean=sample_mean,
        raw_sample_standard_deviation=sample_sd,
        ddof=CALIBRATION_SIGMA_DDOF,
        sigma_floor=SIGMA_FLOOR,
        estimated_sigma=max(sample_sd, SIGMA_FLOOR),
        belief_model_id=CALIBRATED_SIGMA_MODEL_ID,
        lineage_id=LINEAGE_ID,
        provenance_sha256=provenance_sha256,
        effects=effect_tuple,
        observations=tuple(observations),
        physical_cost=10.0 + group_index,
    )


def _calibration() -> CalibrationDeployment:
    estimates = tuple(_estimate(index) for index in range(len(GROUP_IDS)))
    return CalibrationDeployment(
        estimates=estimates,
        effects=tuple(item for estimate in estimates for item in estimate.effects),
        observations=tuple(item for estimate in estimates for item in estimate.observations),
        cost=sum(item.physical_cost for item in estimates),
    )


def _estimate_context(estimate: CalibrationGroupEstimate) -> dict[str, object]:
    return {
        "expected_estimate": estimate,
        "expected_run_id": RUN_ID,
        "expected_world_id": WORLD_ID,
        "expected_seed": SEED,
        "expected_belief_model_version": CALIBRATED_SIGMA_MODEL_VERSION,
    }


def _calibration_context(calibration: CalibrationDeployment) -> dict[str, object]:
    return {
        "expected_calibration": calibration,
        "expected_run_id": RUN_ID,
        "expected_world_id": WORLD_ID,
        "expected_seed": SEED,
        "expected_belief_model_version": CALIBRATED_SIGMA_MODEL_VERSION,
        "expected_lineage_id": LINEAGE_ID,
    }


def test_calibration_estimate_exact_schema_round_trip_and_reconstruction() -> None:
    domain = _estimate()
    projection = returned.project_calibration_estimate(domain, expected_run_id=RUN_ID)
    raw = returned.projection_as_dict(projection)

    assert tuple(field.name for field in fields(type(projection))) == ESTIMATE_FIELDS
    assert tuple(raw) == ESTIMATE_FIELDS
    assert returned.decode_run_calibration_estimate_projection(raw) == projection
    assert returned.reconstruct_calibration_estimate(projection) == domain
    assert returned.projection_matches_domain(projection, domain)
    returned.validate_calibration_estimate_relation(
        projection,
        **cast(Any, _estimate_context(domain)),
    )


def test_calibration_deployment_exact_schema_round_trip_and_reconstruction() -> None:
    domain = _calibration()
    projection = returned.project_calibration(domain, expected_run_id=RUN_ID)
    raw = returned.projection_as_dict(projection)

    assert tuple(field.name for field in fields(type(projection))) == CALIBRATION_FIELDS
    assert tuple(raw) == CALIBRATION_FIELDS
    assert returned.decode_run_calibration_projection(raw) == projection
    assert returned.reconstruct_calibration(projection) == domain
    assert returned.projection_matches_domain(projection, domain)
    returned.validate_calibration_relation(
        projection,
        **cast(Any, _calibration_context(domain)),
    )


@pytest.mark.parametrize("kind", ["estimate", "calibration"])
def test_calibration_decoders_are_closed_and_reject_mapping_substitution(kind: str) -> None:
    calibration = _calibration()
    projection: object
    decoder: Callable[[object], object]
    if kind == "estimate":
        projection = returned.project_calibration_estimate(
            calibration.estimates[0],
            expected_run_id=RUN_ID,
        )
        decoder = returned.decode_run_calibration_estimate_projection
    else:
        projection = returned.project_calibration(calibration, expected_run_id=RUN_ID)
        decoder = returned.decode_run_calibration_projection
    raw = returned.projection_as_dict(projection)
    missing = dict(raw)
    missing.pop(next(iter(raw)))
    extra = dict(raw) | {"unexpected": None}
    for payload in (missing, extra, tuple(raw.items())):
        _failure(
            partial(decoder, payload),
            category="structural_projection_invalid",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ddof", False),
        ("effects", ()),
        ("estimated_sigma", 0.1),
        ("observations", ()),
        ("physical_cost", "1.0"),
        ("provenance_sha256", "A" * 64),
        ("sample_count", True),
        ("source_effect_ids", ()),
    ],
)
def test_estimate_decoder_rejects_exact_type_substitution(field: str, value: object) -> None:
    projection = returned.project_calibration_estimate(_estimate(), expected_run_id=RUN_ID)
    raw = returned.projection_as_dict(projection)
    raw[field] = value
    _failure(
        partial(returned.decode_run_calibration_estimate_projection, raw),
        category="structural_projection_invalid",
    )


@pytest.mark.parametrize("kind", ["estimate", "calibration"])
def test_calibration_projection_requires_explicit_run_context(kind: str) -> None:
    call: Callable[[], object]
    if kind == "estimate":
        call = partial(returned.project_calibration_estimate, _estimate())
    else:
        call = partial(returned.project_calibration, _calibration())
    _failure(call, category="missing_relation_context")


@pytest.mark.parametrize("mode", ["effects", "observations", "source_effect_ids"])
def test_estimate_rejects_reordered_nested_sequences(mode: str) -> None:
    projection = returned.project_calibration_estimate(_estimate(), expected_run_id=RUN_ID)
    changed: returned.RunCalibrationEstimateProjection
    if mode == "effects":
        changed = replace(projection, effects=tuple(reversed(projection.effects)))
    elif mode == "observations":
        changed = replace(projection, observations=tuple(reversed(projection.observations)))
    else:
        changed = replace(
            projection,
            source_effect_ids=tuple(reversed(projection.source_effect_ids)),
        )
    _failure(
        partial(returned.reconstruct_calibration_estimate, changed),
        category="scientific_record_invalid",
    )


@pytest.mark.parametrize(
    "mode", ["duplicate_effect", "missing_effect", "duplicate_observation", "missing_observation"]
)
def test_estimate_rejects_duplicate_or_missing_nested_records(mode: str) -> None:
    projection = returned.project_calibration_estimate(_estimate(), expected_run_id=RUN_ID)
    if mode == "duplicate_effect":
        changed = replace(projection, effects=projection.effects[:-1] + (projection.effects[0],))
    elif mode == "missing_effect":
        changed = replace(projection, effects=projection.effects[:-1])
    elif mode == "duplicate_observation":
        changed = replace(
            projection,
            observations=projection.observations[:-1] + (projection.observations[0],),
        )
    else:
        changed = replace(projection, observations=projection.observations[:-1])
    _failure(
        partial(returned.reconstruct_calibration_estimate, changed),
        category="scientific_record_invalid",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sample_count", 4),
        ("ddof", 0),
        ("sample_mean", f64(0.0)),
        ("raw_sample_standard_deviation", f64(0.25)),
        ("estimated_sigma", f64(0.5)),
        ("sigma_floor", f64(0.1)),
        ("physical_cost", f64(-1.0)),
        ("provenance_sha256", "0" * 64),
        ("belief_model_id", "fixed_sigma_gaussian"),
        ("source_sequence_cutoff", 2),
    ],
)
def test_estimate_rejects_scientific_scalar_mismatch(field: str, value: object) -> None:
    projection = returned.project_calibration_estimate(_estimate(), expected_run_id=RUN_ID)
    changed = replace(projection, **cast(Any, {field: value}))
    _failure(
        partial(returned.reconstruct_calibration_estimate, changed),
        category="scientific_record_invalid",
    )


def test_inner_effect_failure_precedes_outer_estimate_failure() -> None:
    projection = returned.project_calibration_estimate(_estimate(), expected_run_id=RUN_ID)
    inner = replace(
        projection.effects[0],
        source_ids=(projection.effects[0].source_ids[0],) * 2,
    )
    changed = replace(projection, ddof=0, effects=(inner, *projection.effects[1:]))
    error = _failure(
        partial(returned.reconstruct_calibration_estimate, changed),
        category="scientific_record_invalid",
    )
    assert error.path.startswith("matched_effect")


@pytest.mark.parametrize(
    "missing",
    [
        "expected_estimate",
        "expected_run_id",
        "expected_world_id",
        "expected_seed",
        "expected_belief_model_version",
    ],
)
def test_estimate_relation_reports_each_missing_context(missing: str) -> None:
    domain = _estimate()
    projection = returned.project_calibration_estimate(domain, expected_run_id=RUN_ID)
    context = _estimate_context(domain)
    del context[missing]
    _failure(
        partial(
            returned.validate_calibration_estimate_relation,
            projection,
            **cast(Any, context),
        ),
        category="missing_relation_context",
    )


@pytest.mark.parametrize("mode", ["run", "world", "seed", "model_version", "physical_cost"])
def test_estimate_relation_rejects_cross_context_substitution(mode: str) -> None:
    domain = _estimate()
    projection = returned.project_calibration_estimate(domain, expected_run_id=RUN_ID)
    context = _estimate_context(domain)
    if mode == "run":
        context["expected_run_id"] = "run:other"
    elif mode == "world":
        context["expected_world_id"] = "world-other"
    elif mode == "seed":
        context["expected_seed"] = SEED + 1
    elif mode == "model_version":
        context["expected_belief_model_version"] = "calibrated-model/v2"
    else:
        context["expected_estimate"] = replace(domain, physical_cost=domain.physical_cost + 1.0)
    _failure(
        partial(
            returned.validate_calibration_estimate_relation,
            projection,
            **cast(Any, context),
        ),
        category="scientific_record_invalid",
    )


@pytest.mark.parametrize("mode", ["estimates", "effects", "observations", "cost"])
def test_deployment_rejects_reordered_or_mismatched_outer_records(mode: str) -> None:
    projection = returned.project_calibration(_calibration(), expected_run_id=RUN_ID)
    if mode == "estimates":
        changed = replace(projection, estimates=tuple(reversed(projection.estimates)))
    elif mode == "effects":
        changed = replace(projection, effects=tuple(reversed(projection.effects)))
    elif mode == "observations":
        changed = replace(projection, observations=tuple(reversed(projection.observations)))
    else:
        changed = replace(projection, cost=f64(1.0))
    _failure(
        partial(returned.reconstruct_calibration, changed),
        category="scientific_record_invalid",
    )


@pytest.mark.parametrize(
    "mode", ["duplicate_estimate", "missing_estimate", "duplicate_effect", "missing_observation"]
)
def test_deployment_rejects_duplicate_or_missing_outer_records(mode: str) -> None:
    projection = returned.project_calibration(_calibration(), expected_run_id=RUN_ID)
    if mode == "duplicate_estimate":
        changed = replace(
            projection,
            estimates=projection.estimates[:-1] + (projection.estimates[0],),
        )
    elif mode == "missing_estimate":
        changed = replace(projection, estimates=projection.estimates[:-1])
    elif mode == "duplicate_effect":
        changed = replace(
            projection,
            effects=projection.effects[:-1] + (projection.effects[0],),
        )
    else:
        changed = replace(projection, observations=projection.observations[:-1])
    _failure(
        partial(returned.reconstruct_calibration, changed),
        category="scientific_record_invalid",
    )


def test_inner_estimate_failure_precedes_outer_deployment_failure() -> None:
    projection = returned.project_calibration(_calibration(), expected_run_id=RUN_ID)
    inner = replace(projection.estimates[0], sample_count=4)
    changed = replace(projection, cost=f64(1.0), estimates=(inner, *projection.estimates[1:]))
    error = _failure(
        partial(returned.reconstruct_calibration, changed),
        category="scientific_record_invalid",
    )
    assert error.path == "calibration_estimate.sample_count"


@pytest.mark.parametrize(
    "missing",
    [
        "expected_calibration",
        "expected_run_id",
        "expected_world_id",
        "expected_seed",
        "expected_belief_model_version",
        "expected_lineage_id",
    ],
)
def test_deployment_relation_reports_each_missing_context(missing: str) -> None:
    domain = _calibration()
    projection = returned.project_calibration(domain, expected_run_id=RUN_ID)
    context = _calibration_context(domain)
    del context[missing]
    _failure(
        partial(
            returned.validate_calibration_relation,
            projection,
            **cast(Any, context),
        ),
        category="missing_relation_context",
    )


def test_deployment_relation_rejects_lineage_substitution() -> None:
    domain = _calibration()
    projection = returned.project_calibration(domain, expected_run_id=RUN_ID)
    context = _calibration_context(domain)
    context["expected_lineage_id"] = "lineage/other"
    _failure(
        partial(
            returned.validate_calibration_relation,
            projection,
            **cast(Any, context),
        ),
        category="scientific_record_invalid",
        path="calibration_estimate.lineage_id",
    )


def test_architecture_retains_the_two_calibration_projection_classes() -> None:
    module_path = Path(returned.__file__ or "")
    source = module_path.read_text(encoding="utf-8")
    classes = architecture.top_level_class_names(source)

    assert (
        len(architecture.AUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES)
        == architecture.EXPECTED_AUTHORIZED_TOP_LEVEL_CLASS_COUNT
    )
    assert architecture.is_exact_authorized_top_level_class_set(classes)
    assert {
        "RunCalibrationEstimateProjection",
        "RunCalibrationProjection",
    } <= classes
    assert not architecture.is_exact_authorized_top_level_class_set(
        classes | {"RunUnexpectedStage2Projection"}
    )


def test_architecture_keeps_all_post_returned_run_stages_unauthorized() -> None:
    expected = set(architecture.AUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES)
    assert architecture.CURRENT_STAGE_UNAUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES.isdisjoint(expected)
    assert "ReturnedRunProjection" in expected
    assert {
        "ReturnedResultProjection",
        "ExecutionInstanceProjection",
        "ExecutionIdentityProjection",
        "WorkerIdentityProjection",
        "ResultBatchProjection",
        "ExecutionCompletionProjection",
        "ReturnedResultsProjection",
        "WorkerResultOrderProjection",
        "ExecutorAttestationProjection",
    } <= architecture.CURRENT_STAGE_UNAUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES


def test_calibration_projection_source_has_no_authority_workload_or_reflection_surface() -> None:
    module_path = Path(returned.__file__ or "")
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = architecture.called_function_names(source)
    imports = architecture.imported_module_roots(source)

    assert all(passed for _name, passed in architecture.returned_run_architecture_checks(source))
    assert architecture.imports_are_authorized(imports)
    assert called.isdisjoint(architecture.PERMANENT_FORBIDDEN_CALLS)
    assert architecture.dynamic_projection_class_assignments(source) == set()
    assert all(pattern not in source for pattern in architecture.forbidden_source_or_ast_patterns())
    forbidden_attributes = {
        "issue",
        "execute",
        "persist",
        "write_evidence",
        "recommend",
        "selected_only_interface",
        "observe_selected",
    }
    assert {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}.isdisjoint(
        forbidden_attributes
    )
