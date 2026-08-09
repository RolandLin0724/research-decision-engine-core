# mypy: disable-error-code="arg-type"

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

import pytest

import research_decision_engine.benchmarks.broader_returned_run as returned
from research_decision_engine.belief_models import (
    CALIBRATED_SIGMA_MODEL_ID,
    FIXED_SIGMA_MODEL_ID,
    BeliefModelLineage,
    MatchedEffectObservation,
    ModelAdequacyDiagnostic,
    ModelBeliefUpdate,
    belief_model,
    initial_model_lineage,
)
from research_decision_engine.benchmarks.broader_protocol import f64
from research_decision_engine.reasoning import Evidence, Provenance
from tests import p2_returned_run_architecture_guard as architecture

T0 = "2026-01-01T00:00:00+00:00"
_NO_RESULT = object()


@dataclass(frozen=True, slots=True)
class _UpdateCase:
    lineage_after: BeliefModelLineage
    update: ModelBeliefUpdate
    current_effect: MatchedEffectObservation


@dataclass(frozen=True, slots=True)
class _Cases:
    fixed: _UpdateCase
    fallback: _UpdateCase
    calibrated: _UpdateCase
    alarm: _UpdateCase
    adequate: _UpdateCase


def _expect_failure(
    call: Callable[..., object],
    *args: object,
    category: str | None = None,
    path: str | None = None,
) -> returned.ReturnedRunProjectionError:
    result: object = _NO_RESULT
    with pytest.raises(returned.ReturnedRunProjectionError) as captured:
        result = call(*args)
    error = captured.value
    assert result is _NO_RESULT
    for name in ("scientific_output", "recommendation", "capability", "written_evidence"):
        assert not hasattr(error, name)
        assert not hasattr(returned, name)
    if category is not None:
        assert error.category == category
    if path is not None:
        assert error.path == path
    expected_code = (
        returned.EXECUTION_RETURNED_SCIENTIFIC_RECORD_INVALID
        if error.category == "scientific_record_invalid"
        else None
    )
    assert error.failure_code == expected_code
    return error


def _science(
    call: Callable[..., object],
    *args: object,
    path: str | None = None,
) -> returned.ReturnedRunProjectionError:
    return _expect_failure(
        call,
        *args,
        category="scientific_record_invalid",
        path=path,
    )


def _structure(
    call: Callable[..., object], *args: object, path: str | None = None
) -> returned.ReturnedRunProjectionError:
    return _expect_failure(call, *args, category="structural_projection_invalid", path=path)


def _context(call: Callable[[], object]) -> returned.ReturnedRunProjectionError:
    return _expect_failure(call, category="missing_relation_context")


def _evidence(
    suffix: str,
    observed: float,
    *,
    source_start: int = 1,
) -> Evidence:
    return Evidence(
        evidence_id=f"evidence-{suffix}",
        source_experiment_ids=(source_start, source_start + 1),
        observed_comparison=observed,
        observed_outcome="test-comparison",
        provenance=Provenance.create(
            method="matched-optimizer-effect",
            version="test/v1",
            details={
                "comparison_group_id": "group-a",
                "source_experiment_status": "completed_successfully",
            },
        ),
        created_at=f"time-{suffix}",
    )


def _effect(
    effect_id: str,
    observed: float,
    available_sequence: int = 0,
    *,
    source_kind: str = "calibration",
) -> MatchedEffectObservation:
    return MatchedEffectObservation(
        effect_id=effect_id,
        comparison_group_id="group-a",
        observed_effect=observed,
        available_sequence=available_sequence,
        source_kind=cast(Any, source_kind),
        source_ids=(f"{effect_id}-left", f"{effect_id}-right"),
        created_at=T0,
        provenance=Provenance.create(
            method="test-matched-effect",
            version="test/v1",
            details={"effect_id": effect_id},
        ),
    )


def _one_update(
    model_id: str,
    suffix: str,
    observed: float,
    *,
    effect_history: tuple[MatchedEffectObservation, ...] = (),
    diagnostic_history: tuple[ModelAdequacyDiagnostic, ...] = (),
    source_start: int = 1,
) -> _UpdateCase:
    model = belief_model(model_id)
    before = initial_model_lineage(model, lineage_key=f"lineage-{suffix}", created_at=T0)
    after, update, current_effect = model.update(
        lineage=before,
        evidence=_evidence(suffix, observed, source_start=source_start),
        effect_history=effect_history,
        diagnostic_history=diagnostic_history,
    )
    return _UpdateCase(after, update, current_effect)


def _sequence_case(suffix: str, observations: tuple[float, ...]) -> _UpdateCase:
    model = belief_model(FIXED_SIGMA_MODEL_ID)
    lineage = initial_model_lineage(model, lineage_key=f"lineage-{suffix}", created_at=T0)
    effects: list[MatchedEffectObservation] = []
    diagnostics: list[ModelAdequacyDiagnostic] = []
    update: ModelBeliefUpdate | None = None
    current_effect: MatchedEffectObservation | None = None
    for index, observed in enumerate(observations):
        lineage, update, current_effect = model.update(
            lineage=lineage,
            evidence=_evidence(
                f"{suffix}-{index}",
                observed,
                source_start=index * 2 + 1,
            ),
            effect_history=tuple(effects),
            diagnostic_history=tuple(diagnostics),
        )
        effects.append(current_effect)
        diagnostics.append(update.diagnostic)
    assert update is not None
    assert current_effect is not None
    return _UpdateCase(lineage, update, current_effect)


@pytest.fixture(scope="module")
def cases() -> _Cases:
    fallback_history = (
        _effect("fallback-0", 0.0),
        _effect("fallback-1", 0.2),
    )
    calibrated_history = tuple(_effect(f"calibrated-{index}", index / 10.0) for index in range(5))
    return _Cases(
        fixed=_one_update(FIXED_SIGMA_MODEL_ID, "fixed", 0.02),
        fallback=_one_update(
            CALIBRATED_SIGMA_MODEL_ID,
            "fallback",
            0.10,
            effect_history=fallback_history,
            source_start=11,
        ),
        calibrated=_one_update(
            CALIBRATED_SIGMA_MODEL_ID,
            "calibrated",
            0.10,
            effect_history=calibrated_history,
            source_start=21,
        ),
        alarm=_one_update(FIXED_SIGMA_MODEL_ID, "alarm", 0.80, source_start=31),
        adequate=_sequence_case("adequate", (0.0,) * 10),
    )


def _round_trip[D, P](
    domain: D,
    project: Callable[[D], P],
    decode: Callable[[object], P],
    reconstruct: Callable[[P], D],
) -> P:
    projection = project(domain)
    encoded = returned.projection_as_dict(projection)
    assert decode(encoded) == projection
    assert reconstruct(projection) == domain
    assert returned.projection_matches_domain(projection, domain)
    return projection


@pytest.mark.parametrize("kind", ["calibration", "decision"])
def test_matched_effect_valid_tags_round_trip_and_preserve_identity(
    cases: _Cases,
    kind: str,
) -> None:
    domain = (
        _effect("calibration-valid", -0.125)
        if kind == "calibration"
        else cases.fixed.current_effect
    )
    projection = _round_trip(
        domain,
        returned.project_matched_effect,
        returned.decode_run_matched_effect_projection,
        returned.reconstruct_matched_effect,
    )
    assert projection.source_kind == kind
    assert projection.effect_id == domain.effect_id
    assert projection.source_ids == domain.source_ids
    returned.validate_matched_effect_relation(projection, expected_effect=domain)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"available_sequence": 2}, id="available-sequence"),
        pytest.param({"comparison_group_id": "group-cross-run"}, id="comparison-group"),
        pytest.param({"created_at": "time-other"}, id="created-at"),
        pytest.param({"effect_id": "effect-other"}, id="effect-id"),
        pytest.param({"observed_effect": f64(0.25)}, id="observed-effect"),
        pytest.param({"source_kind": "decision"}, id="source-kind"),
    ],
)
def test_matched_effect_scalar_mutations_fail_field_total_relation(
    change: dict[str, object],
) -> None:
    domain = _effect("effect-original", 0.125)
    projection = returned.project_matched_effect(domain)
    mutated = replace(projection, **change)
    rebuilt = returned.reconstruct_matched_effect(mutated)
    assert returned.projection_matches_domain(mutated, rebuilt)
    _science(
        lambda: returned.validate_matched_effect_relation(mutated, expected_effect=domain),
        path="matched_effect",
    )


def test_matched_effect_source_order_is_semantic_and_duplicates_are_rejected() -> None:
    domain = _effect("ordered-effect", 0.125)
    projection = returned.project_matched_effect(domain)
    reordered = replace(projection, source_ids=tuple(reversed(projection.source_ids)))
    assert returned.reconstruct_matched_effect(reordered).source_ids == reordered.source_ids
    _science(
        lambda: returned.validate_matched_effect_relation(reordered, expected_effect=domain),
        path="matched_effect",
    )
    duplicate = replace(projection, source_ids=(projection.source_ids[0],) * 2)
    _science(returned.reconstruct_matched_effect, duplicate, path="matched_effect")


def test_matched_effect_rejects_unknown_kind_nonfinite_value_and_bool_sequence() -> None:
    projection = returned.project_matched_effect(_effect("strict-effect", 0.125))
    payload = returned.projection_as_dict(projection)
    for field, value in (
        ("source_kind", "unknown"),
        ("observed_effect", "f64:7ff0000000000000"),
        ("available_sequence", True),
    ):
        invalid = dict(payload)
        invalid[field] = value
        _structure(returned.decode_run_matched_effect_projection, invalid)


def test_matched_effect_nested_provenance_fails_before_enclosing_relation() -> None:
    projection = returned.project_matched_effect(_effect("nested-effect", 0.125))
    provenance = replace(
        projection.provenance,
        details=projection.provenance.details + (projection.provenance.details[0],),
    )
    invalid = replace(projection, effect_id="effect-outer-wrong", provenance=provenance)
    _science(returned.reconstruct_matched_effect, invalid, path="provenance")


@pytest.mark.parametrize("case_name", ["fixed", "fallback", "calibrated"])
def test_sigma_estimate_each_status_round_trips_with_exact_optional_coupling(
    cases: _Cases,
    case_name: str,
) -> None:
    case = cast(_UpdateCase, getattr(cases, case_name))
    estimate = case.update.sigma_estimate
    projection = _round_trip(
        estimate,
        returned.project_sigma_estimate,
        returned.decode_run_sigma_estimate_projection,
        returned.reconstruct_sigma_estimate,
    )
    assert projection.status == case_name if case_name == "fixed" else estimate.status
    assert projection.estimate_id == estimate.estimate_id
    assert projection.source_effect_ids == estimate.source_effect_ids
    returned.validate_sigma_estimate_relation(projection, expected_estimate=estimate)
    if case_name == "calibrated":
        for change in (
            {"evidence_id": "evidence-cross-run"},
            {"lineage_id": "lineage-cross-run"},
            {"estimator_version": "estimator/v2"},
            {"belief_model_version": "model/v2"},
        ):
            mutated = replace(projection, **change)
            returned.reconstruct_sigma_estimate(mutated)
            _science(
                lambda invalid=mutated: returned.validate_sigma_estimate_relation(
                    invalid, expected_estimate=estimate
                ),
                path="sigma_estimate",
            )


@pytest.mark.parametrize(
    "case_name,change",
    (
        ("fixed", {"sample_mean": f64(0.0)}),
        ("fixed", {"raw_sample_standard_deviation": f64(0.0)}),
        ("fallback", {"sample_mean": None}),
        ("fallback", {"raw_sample_standard_deviation": None}),
        ("fallback", {"status": "calibrated"}),
        ("calibrated", {"sample_mean": None}),
        ("calibrated", {"raw_sample_standard_deviation": None}),
    ),
)
def test_sigma_status_count_and_null_coupling_is_closed(
    cases: _Cases,
    case_name: str,
    change: dict[str, object],
) -> None:
    estimate = cast(_UpdateCase, getattr(cases, case_name)).update.sigma_estimate
    invalid = replace(returned.project_sigma_estimate(estimate), **change)
    _science(
        returned.reconstruct_sigma_estimate,
        invalid,
        path="sigma_estimate",
    )


@pytest.mark.parametrize(
    "change,path",
    (
        ({"sample_count": -1}, "sigma_estimate"),
        ({"sample_count": 3}, "sigma_estimate"),
        ({"estimated_sigma": f64(0.01)}, "sigma_estimate"),
        ({"sigma_floor": f64(0.0)}, "sigma_estimate.sigma_floor"),
        ({"variance_floor": f64(0.01)}, "sigma_estimate"),
        ({"current_evidence_excluded": False}, "sigma_estimate"),
    ),
)
def test_sigma_counts_floors_and_exclusion_invariants(
    cases: _Cases,
    change: dict[str, object],
    path: str,
) -> None:
    projection = returned.project_sigma_estimate(cases.fallback.update.sigma_estimate)
    _science(returned.reconstruct_sigma_estimate, replace(projection, **change), path=path)


def test_sigma_nonfinite_values_are_structural_not_scientific() -> None:
    estimate = returned.project_sigma_estimate
    projection = estimate(
        _one_update(FIXED_SIGMA_MODEL_ID, "strict-sigma", 0.0).update.sigma_estimate
    )
    for field in ("estimated_sigma", "sigma_floor", "variance_floor"):
        payload = returned.projection_as_dict(projection)
        payload[field] = "f64:7ff8000000000000"
        _structure(returned.decode_run_sigma_estimate_projection, payload)


def test_sigma_effect_id_order_is_preserved_and_duplicate_is_invalid(cases: _Cases) -> None:
    domain = cases.calibrated.update.sigma_estimate
    projection = returned.project_sigma_estimate(domain)
    reordered = replace(
        projection,
        source_effect_ids=tuple(reversed(projection.source_effect_ids)),
    )
    assert (
        returned.reconstruct_sigma_estimate(reordered).source_effect_ids
        == reordered.source_effect_ids
    )
    _science(
        lambda: returned.validate_sigma_estimate_relation(reordered, expected_estimate=domain),
        path="sigma_estimate",
    )
    duplicate = replace(
        projection,
        source_effect_ids=(projection.source_effect_ids[0],) * projection.sample_count,
    )
    _science(returned.reconstruct_sigma_estimate, duplicate, path="sigma_estimate")


def test_sigma_nested_provenance_and_missing_context_are_deterministic(cases: _Cases) -> None:
    projection = returned.project_sigma_estimate(cases.fallback.update.sigma_estimate)
    invalid_provenance = replace(projection.provenance, method="")
    _science(
        returned.reconstruct_sigma_estimate,
        replace(projection, provenance=invalid_provenance),
        path="provenance",
    )
    _context(lambda: returned.validate_sigma_estimate_relation(projection))


def test_model_belief_state_round_trips_nested_foundational_state(cases: _Cases) -> None:
    state = cases.fixed.update.posterior_state
    projection = _round_trip(
        state,
        returned.project_model_belief_state,
        returned.decode_run_model_belief_state_projection,
        returned.reconstruct_model_belief_state,
    )
    assert projection.state.belief_state_id == state.state.belief_state_id
    returned.validate_model_belief_state_relation(projection, expected_state=state)
    substituted = replace(
        projection,
        state=returned.project_belief_state(cases.alarm.update.posterior_state.state),
    )
    returned.reconstruct_model_belief_state(substituted)
    _science(
        lambda: returned.validate_model_belief_state_relation(substituted, expected_state=state),
        path="model_belief_state",
    )
    for change in (
        {"belief_model_id": "model-other"},
        {"belief_model_version": "model/v2"},
        {"lineage_id": "lineage-other"},
    ):
        mutated = replace(projection, **change)
        returned.reconstruct_model_belief_state(mutated)
        _science(
            lambda invalid=mutated: returned.validate_model_belief_state_relation(
                invalid, expected_state=state
            ),
            path="model_belief_state",
        )
    _context(lambda: returned.validate_model_belief_state_relation(projection))


def test_lineage_round_trips_current_state_without_mutating_it(cases: _Cases) -> None:
    lineage = cases.fixed.lineage_after
    before = lineage.current_state
    projection = _round_trip(
        lineage,
        returned.project_lineage,
        returned.decode_run_lineage_projection,
        returned.reconstruct_lineage,
    )
    returned.validate_lineage_relation(projection, expected_lineage=lineage)
    assert lineage.current_state is before
    substituted = replace(
        projection,
        current_state=returned.project_model_belief_state(
            cases.calibrated.lineage_after.current_state
        ),
    )
    _science(returned.reconstruct_lineage, substituted, path="lineage")
    for change in (
        {"belief_model_id": "model-other"},
        {"belief_model_version": "model/v2"},
        {"lineage_id": "lineage-other"},
    ):
        _science(returned.reconstruct_lineage, replace(projection, **change), path="lineage")
    for change in ({"lineage_key": "lineage-key-other"}, {"created_at": "time-other"}):
        changed = replace(projection, **change)
        returned.reconstruct_lineage(changed)
        _science(
            lambda invalid=changed: returned.validate_lineage_relation(
                invalid, expected_lineage=lineage
            ),
            path="lineage",
        )


def test_lineage_nested_state_invalidity_precedes_outer_invalidity(cases: _Cases) -> None:
    projection = returned.project_lineage(cases.fixed.lineage_after)
    invalid_state = replace(
        projection.current_state.state,
        posterior_probabilities=(f64(-0.25), f64(1.25), f64(0.0)),
    )
    invalid = replace(
        projection,
        lineage_id="lineage-outer-invalid",
        current_state=replace(projection.current_state, state=invalid_state),
    )
    first = _science(returned.reconstruct_lineage, invalid, path="belief_state")
    second = _science(returned.reconstruct_lineage, invalid, path="belief_state")
    assert str(first) == str(second)


@pytest.mark.parametrize("case_name", ["fixed", "alarm"])
def test_predictive_interval_round_trips_containing_and_noncontaining_cases(
    cases: _Cases,
    case_name: str,
) -> None:
    case = cast(_UpdateCase, getattr(cases, case_name))
    observed = case.update.evidence.observed_comparison
    interval = case.update.diagnostic.central_intervals[0]
    projection = _round_trip(
        interval,
        returned.project_predictive_interval,
        returned.decode_run_predictive_interval_projection,
        returned.reconstruct_predictive_interval,
    )
    assert projection.contains_observation == interval.contains_observation
    returned.validate_predictive_interval_relation(
        projection,
        expected_observation=observed,
    )


@pytest.mark.parametrize(
    "change,path",
    [
        pytest.param({"lower": f64(2.0), "upper": f64(1.0)}, "predictive_interval", id="bounds"),
        pytest.param({"probability": f64(0.0)}, "predictive_interval.probability", id="zero"),
        pytest.param({"probability": f64(1.0)}, "predictive_interval.probability", id="one"),
        pytest.param({"probability": f64(-0.1)}, "predictive_interval.probability", id="negative"),
    ],
)
def test_predictive_interval_bounds_and_probability_are_scientifically_closed(
    cases: _Cases,
    change: dict[str, object],
    path: str,
) -> None:
    projection = returned.project_predictive_interval(
        cases.fixed.update.diagnostic.central_intervals[0]
    )
    _science(returned.reconstruct_predictive_interval, replace(projection, **change), path=path)


def test_predictive_interval_contains_flag_requires_observation_context(cases: _Cases) -> None:
    diagnostic = cases.fixed.update.diagnostic
    projection = returned.project_predictive_interval(diagnostic.central_intervals[0])
    wrong = replace(projection, contains_observation=not projection.contains_observation)
    returned.reconstruct_predictive_interval(wrong)
    _science(
        lambda: returned.validate_predictive_interval_relation(
            wrong,
            expected_observation=cases.fixed.update.evidence.observed_comparison,
        ),
        path="predictive_interval.contains_observation",
    )
    _context(lambda: returned.validate_predictive_interval_relation(projection))


def test_predictive_interval_rejects_int_boolean_and_nonfinite_f64(cases: _Cases) -> None:
    projection = returned.project_predictive_interval(
        cases.fixed.update.diagnostic.central_intervals[0]
    )
    payload = returned.projection_as_dict(projection)
    invalid_values = (
        ("contains_observation", 1),
        ("lower", "f64:7ff0000000000000"),
        ("probability", "f64:7ff8000000000000"),
        ("upper", "f64:fff0000000000000"),
    )
    for field, value in invalid_values:
        invalid = dict(payload)
        invalid[field] = value
        _structure(returned.decode_run_predictive_interval_projection, invalid)


@pytest.mark.parametrize("case_name", ["fixed", "adequate", "alarm"])
def test_diagnostic_all_adequacy_variants_round_trip(cases: _Cases, case_name: str) -> None:
    case = cast(_UpdateCase, getattr(cases, case_name))
    diagnostic = case.update.diagnostic
    projection = _round_trip(
        diagnostic,
        returned.project_diagnostic,
        returned.decode_run_diagnostic_projection,
        returned.reconstruct_diagnostic,
    )
    expected = {
        "fixed": "uncertain",
        "adequate": "adequate",
        "alarm": "appears_misspecified",
    }[case_name]
    assert projection.adequacy_state == expected
    returned.validate_diagnostic_relation(projection, expected_diagnostic=diagnostic)
    if case_name == "fixed":
        for change in (
            {"belief_state_before_id": "belief-cross-run"},
            {"evidence_id": "evidence-cross-run"},
            {"sigma_estimate_id": "sigma-cross-run"},
            {"lineage_id": "lineage-cross-run"},
            {"belief_model_id": "model-cross-run"},
            {"diagnostic_id": "diagnostic-other"},
            {"diagnostic_version": "diagnostic/v2"},
        ):
            mutated = replace(projection, **change)
            returned.reconstruct_diagnostic(mutated)
            _science(
                lambda invalid=mutated: returned.validate_diagnostic_relation(
                    invalid, expected_diagnostic=diagnostic
                ),
                path="diagnostic",
            )


def test_diagnostic_residual_pairs_are_ordered_and_duplicate_free(cases: _Cases) -> None:
    domain = cases.fixed.update.diagnostic
    projection = returned.project_diagnostic(domain)
    reordered = replace(
        projection,
        per_hypothesis_residuals=tuple(reversed(projection.per_hypothesis_residuals)),
    )
    returned.reconstruct_diagnostic(reordered)
    _science(
        lambda: returned.validate_diagnostic_relation(reordered, expected_diagnostic=domain),
        path="diagnostic",
    )
    first = projection.per_hypothesis_residuals[0]
    duplicate = replace(projection, per_hypothesis_residuals=(first,) * 3)
    _science(
        returned.reconstruct_diagnostic,
        duplicate,
        path="diagnostic.per_hypothesis_residuals",
    )
    bad_order = replace(
        projection,
        central_intervals=tuple(reversed(projection.central_intervals)),
    )
    _science(returned.reconstruct_diagnostic, bad_order, path="diagnostic.central_intervals")


@pytest.mark.parametrize(
    "change,path",
    (
        ({"residual_count": 0}, "diagnostic"),
        ({"rolling_residual_outlier_count": 2}, "diagnostic.rolling_residual_outlier_count"),
        ({"repeated_residual_alarm": True}, "diagnostic"),
        ({"tail_alarm": True}, "diagnostic"),
        ({"residual_outlier": True}, "diagnostic"),
        ({"diagnostics_disagree": True}, "diagnostic"),
        ({"adequacy_state": "appears_misspecified"}, "diagnostic.adequacy_state"),
    ),
)
def test_diagnostic_count_alarm_and_adequacy_relations_are_exact(
    cases: _Cases,
    change: dict[str, object],
    path: str,
) -> None:
    projection = returned.project_diagnostic(cases.fixed.update.diagnostic)
    _science(returned.reconstruct_diagnostic, replace(projection, **change), path=path)


@pytest.mark.parametrize(
    "change,path",
    (
        ({"predictive_cdf": f64(1.1)}, "diagnostic"),
        ({"posterior_predictive_tail_probability": f64(1.1)}, "diagnostic"),
        ({"predictive_density": f64(0.0)}, "diagnostic"),
        ({"predictive_variance": f64(0.0)}, "diagnostic.predictive_variance"),
    ),
)
def test_diagnostic_probability_density_and_variance_ranges(
    cases: _Cases,
    change: dict[str, object],
    path: str,
) -> None:
    projection = returned.project_diagnostic(cases.fixed.update.diagnostic)
    _science(returned.reconstruct_diagnostic, replace(projection, **change), path=path)


def test_diagnostic_nested_provenance_invalidity_is_inner_first(cases: _Cases) -> None:
    projection = returned.project_diagnostic(cases.fixed.update.diagnostic)
    invalid_provenance = replace(
        projection.provenance, details=tuple(reversed(projection.provenance.details))
    )
    invalid = replace(
        projection,
        diagnostic_id="diagnostic-outer-invalid",
        provenance=invalid_provenance,
    )
    _science(returned.reconstruct_diagnostic, invalid, path="provenance")


def test_diagnostic_inner_interval_failure_precedes_outer_failure(cases: _Cases) -> None:
    projection = returned.project_diagnostic(cases.fixed.update.diagnostic)
    bad_interval = replace(projection.central_intervals[0], lower=f64(2.0), upper=f64(1.0))
    invalid = replace(
        projection,
        central_intervals=(bad_interval, *projection.central_intervals[1:]),
        residual_count=0,
    )
    first = _science(
        returned.reconstruct_diagnostic, invalid, path="diagnostic.central_intervals[0]"
    )
    second = _science(
        returned.reconstruct_diagnostic, invalid, path="diagnostic.central_intervals[0]"
    )
    assert str(first) == str(second)


def test_model_update_complete_nested_round_trip_and_validation_is_pure(cases: _Cases) -> None:
    domain = cases.calibrated.update
    lineage_after = cases.calibrated.lineage_after
    projection = _round_trip(
        domain,
        returned.project_model_update,
        returned.decode_run_model_update_projection,
        returned.reconstruct_model_update,
    )
    returned.validate_model_update_relation(projection, expected_update=domain)
    assert cases.calibrated.lineage_after == lineage_after


@pytest.mark.parametrize(
    "field",
    [
        pytest.param("state_before", id="state-before"),
        pytest.param("bayesian_update", id="bayesian-before"),
        pytest.param("evidence", id="evidence"),
        pytest.param("sigma_estimate", id="sigma"),
        pytest.param("posterior_state", id="posterior"),
        pytest.param("diagnostic", id="diagnostic"),
    ],
)
def test_model_update_rejects_each_wrong_nested_relation(
    cases: _Cases,
    field: str,
) -> None:
    projection = returned.project_model_update(cases.fixed.update)
    other = returned.project_model_update(cases.alarm.update)
    invalid = replace(projection, **{field: getattr(other, field)})
    _science(
        returned.reconstruct_model_update,
        invalid,
    )


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"belief_model_id": "model-other"}, id="model"),
        pytest.param({"belief_model_version": "model/v2"}, id="version"),
        pytest.param({"lineage_id": "lineage-other"}, id="lineage"),
    ],
)
def test_model_update_rejects_outer_model_version_and_lineage_mismatch(
    cases: _Cases,
    change: dict[str, object],
) -> None:
    projection = returned.project_model_update(cases.fixed.update)
    _science(returned.reconstruct_model_update, replace(projection, **change), path="model_update")


def test_model_update_identity_is_preserved_not_recomputed(cases: _Cases) -> None:
    domain = cases.fixed.update
    changed = replace(
        returned.project_model_update(domain),
        model_update_id="model-update-other",
    )
    rebuilt = returned.reconstruct_model_update(changed)
    assert rebuilt.model_update_id == "model-update-other"
    _science(
        lambda: returned.validate_model_update_relation(changed, expected_update=domain),
        path="model_update",
    )


def test_model_update_detects_nested_mutation_with_unchanged_outer_ids(cases: _Cases) -> None:
    domain = cases.fixed.update
    projection = returned.project_model_update(domain)
    first, *rest = projection.diagnostic.per_hypothesis_residuals
    changed_residuals = ((first[0], f64(999.0)), *rest)
    changed_diagnostic = replace(projection.diagnostic, per_hypothesis_residuals=changed_residuals)
    invalid = replace(projection, diagnostic=changed_diagnostic)
    assert invalid.model_update_id == projection.model_update_id
    assert invalid.diagnostic.diagnostic_id == projection.diagnostic.diagnostic_id
    _science(
        lambda: returned.validate_model_update_relation(invalid, expected_update=domain),
        path="model_update.diagnostic",
    )


def test_model_update_inner_failure_precedes_outer_model_failure(cases: _Cases) -> None:
    projection = returned.project_model_update(cases.fixed.update)
    invalid_state = replace(
        projection.state_before.state,
        posterior_probabilities=(f64(-0.25), f64(1.25), f64(0.0)),
    )
    invalid = replace(
        projection,
        belief_model_id="model-outer-invalid",
        state_before=replace(projection.state_before, state=invalid_state),
    )
    first = _science(returned.reconstruct_model_update, invalid, path="belief_state")
    second = _science(returned.reconstruct_model_update, invalid, path="belief_state")
    assert str(first) == str(second)


def test_model_update_cross_lineage_and_cross_run_context_substitution(cases: _Cases) -> None:
    domain = cases.fixed.update
    for other in (cases.alarm.update, cases.calibrated.update):
        substituted = returned.project_model_update(other)
        _science(
            lambda invalid=substituted: returned.validate_model_update_relation(
                invalid,
                expected_update=domain,
            ),
            path="model_update.provenance",
        )


def test_all_seven_decoders_are_closed_strict_and_ignore_mapping_insertion_order(
    cases: _Cases,
) -> None:
    diagnostic = cases.fixed.update.diagnostic
    projections: tuple[tuple[object, Callable[[object], object], str], ...] = (
        (  # noqa: SIM905
            returned.project_matched_effect(cases.fixed.current_effect),
            returned.decode_run_matched_effect_projection,
            "effect_id",
        ),
        (
            returned.project_sigma_estimate(cases.fixed.update.sigma_estimate),
            returned.decode_run_sigma_estimate_projection,
            "estimate_id",
        ),
        (
            returned.project_model_belief_state(cases.fixed.update.state_before),
            returned.decode_run_model_belief_state_projection,
            "lineage_id",
        ),
        (
            returned.project_lineage(cases.fixed.lineage_after),
            returned.decode_run_lineage_projection,
            "lineage_key",
        ),
        (
            returned.project_predictive_interval(diagnostic.central_intervals[0]),
            returned.decode_run_predictive_interval_projection,
            "probability",
        ),
        (
            returned.project_diagnostic(diagnostic),
            returned.decode_run_diagnostic_projection,
            "diagnostic_id",
        ),
        (
            returned.project_model_update(cases.fixed.update),
            returned.decode_run_model_update_projection,
            "model_update_id",
        ),
    )
    for projection, decoder, missing_field in projections:
        payload = returned.projection_as_dict(projection)
        assert decoder(payload) == projection
        reversed_mapping = dict(reversed(tuple(payload.items())))
        assert decoder(reversed_mapping) == projection
        extra = dict(payload)
        extra["unexpected"] = None
        _structure(decoder, extra)
        missing = dict(payload)
        del missing[missing_field]
        _structure(decoder, missing)
        wrong_type = dict(payload)
        wrong_type[missing_field] = True
        _structure(decoder, wrong_type)
        _structure(decoder, tuple(payload.items()))
    model_projection = returned.project_model_update(cases.fixed.update)
    model_payload = returned.projection_as_dict(model_projection)
    diagnostic_payload = cast(dict[str, object], model_payload["diagnostic"])
    model_payload["diagnostic"] = dict(reversed(tuple(diagnostic_payload.items())))
    assert returned.decode_run_model_update_projection(model_payload) == model_projection
    model_payload["belief_model_version"] = "e\u0301"
    _structure(returned.decode_run_model_update_projection, model_payload)


def test_architecture_is_pure_handwritten_and_stage_aware() -> None:
    module_path = Path(returned.__file__ or "")
    source = module_path.read_text(encoding="utf-8")
    imported_roots = architecture.imported_module_roots(source)
    called_names = architecture.called_function_names(source)
    classes = architecture.top_level_class_names(source)

    assert all(passed for _name, passed in architecture.returned_run_architecture_checks(source))
    assert architecture.imports_are_authorized(imported_roots)
    assert called_names.isdisjoint(architecture.PERMANENT_FORBIDDEN_CALLS)
    assert architecture.dynamic_projection_class_assignments(source) == set()
    assert architecture.is_exact_authorized_top_level_class_set(classes)
    assert all(pattern not in source for pattern in architecture.forbidden_source_or_ast_patterns())
    for scientific_module in (
        module_path.parents[1] / "reasoning.py",
        module_path.parents[1] / "belief_models.py",
    ):
        assert "broader_returned_run" not in scientific_module.read_text(encoding="utf-8")


def test_architecture_guard_rejects_unexpected_projection() -> None:
    hypothetical_classes = set(architecture.AUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES) | {
        "RunUnexpectedStage2Projection"
    }
    assert not architecture.is_exact_authorized_top_level_class_set(hypothetical_classes)
