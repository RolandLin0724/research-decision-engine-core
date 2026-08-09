from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, cast

import pytest

import research_decision_engine.benchmarks.broader_returned_run as returned
from research_decision_engine.benchmarks.broader_protocol import f64
from research_decision_engine.reasoning import (
    BayesianBeliefUpdater,
    BeliefState,
    BeliefUpdate,
    Evidence,
    GaussianEvidencePrediction,
    Hypothesis,
    Provenance,
    initial_belief_state,
)
from research_decision_engine.types import Candidate, CompletedExperiment
from tests import p2_returned_run_architecture_guard as architecture

T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-01-02T00:00:00+00:00"
_NO_RESULT = object()
_OBSERVED_EFFECTS = (
    ("scientific_outputs", 0),
    ("recommendations", 0),
    ("capabilities_issued", 0),
    ("evidence_writes", 0),
    ("production_mutations", 0),
)


@dataclass(frozen=True, slots=True)
class _UnsupportedDataclass:
    value: int


class _UnsupportedEnum(Enum):
    VALUE = "value"


def _expect_failure(
    call: Callable[..., object],
    *args: object,
    category: str | None = None,
    path: str | None = None,
) -> returned.ReturnedRunProjectionError:
    effects_before = _OBSERVED_EFFECTS
    result: object = _NO_RESULT
    with pytest.raises(returned.ReturnedRunProjectionError) as captured:
        result = call(*args)
    error = captured.value
    assert result is _NO_RESULT
    assert effects_before == _OBSERVED_EFFECTS
    assert not hasattr(error, "scientific_output")
    assert not hasattr(error, "recommendation")
    assert not hasattr(error, "capability")
    assert not hasattr(error, "written_evidence")
    if category is not None:
        assert error.category == category
    if path is not None:
        assert error.path == path
    expected_failure_code = (
        returned.EXECUTION_RETURNED_SCIENTIFIC_RECORD_INVALID
        if error.category == "scientific_record_invalid"
        else None
    )
    assert error.failure_code == expected_failure_code
    return error


def _provenance(*, method: str = "handwritten") -> Provenance:
    return Provenance(
        method=method,
        version="provenance/v1",
        details=(
            ("a-null", None),
            ("b-bool", True),
            ("c-i64", -7),
            ("d-f64", -0.25),
            ("e-string", "source"),
        ),
    )


def _candidate(*, candidate_id: str = "candidate-1") -> Candidate:
    return Candidate(
        candidate_id=candidate_id,
        learning_rate=0.125,
        regularization=0.0625,
        model_width=64,
        optimizer="adam",
    )


def _experiment() -> CompletedExperiment:
    return CompletedExperiment(
        record_id=11,
        candidate=_candidate(),
        observed_value=0.75,
        created_at=T0,
    )


def _evidence(
    *,
    evidence_id: str = "evidence-1",
    source_ids: tuple[int, ...] = (11, 12),
    created_at: str = T1,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        source_experiment_ids=source_ids,
        observed_comparison=0.5,
        observed_outcome="left-better",
        provenance=_provenance(method="comparison"),
        created_at=created_at,
    )


def _hypotheses() -> tuple[Hypothesis, ...]:
    return (
        Hypothesis(
            hypothesis_id="h-a",
            statement="comparison is centered at zero",
            prior_probability=0.5,
            prediction_model=GaussianEvidencePrediction(mean=0.0, standard_deviation=1.0),
        ),
        Hypothesis(
            hypothesis_id="h-b",
            statement="comparison is centered at one",
            prior_probability=0.5,
            prediction_model=GaussianEvidencePrediction(mean=1.0, standard_deviation=1.0),
        ),
    )


def _initial_state() -> BeliefState:
    return initial_belief_state(_hypotheses(), created_at=T0)


def _valid_update() -> BeliefUpdate:
    return BayesianBeliefUpdater().update(
        hypotheses=_hypotheses(),
        belief_state=_initial_state(),
        evidence=_evidence(),
    )


@pytest.mark.parametrize(
    ("domain_value", "kind", "encoded_value"),
    [
        pytest.param(None, "null", None, id="null"),
        pytest.param(True, "bool", True, id="bool"),
        pytest.param(-(2**63), "i64", -(2**63), id="i64"),
        pytest.param(-0.25, "f64", f64(-0.25), id="f64"),
        pytest.param("value", "string", "value", id="string"),
    ],
)
def test_tagged_provenance_value_exact_round_trip(
    domain_value: object,
    kind: str,
    encoded_value: object,
) -> None:
    projection = returned.project_provenance_value(cast(Any, domain_value))

    encoded = returned.projection_as_dict(projection)
    assert encoded == {"kind": kind, "value": encoded_value}
    assert tuple(encoded) == ("kind", "value")
    assert returned.decode_provenance_value_projection(encoded) == projection
    assert (
        returned.projection_as_dict(returned.decode_provenance_value_projection(encoded)) == encoded
    )
    assert returned.provenance_value_from_projection(projection) == domain_value
    assert (
        returned.project_provenance_value(returned.provenance_value_from_projection(projection))
        == projection
    )


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"kind": "null"}, id="null-missing-value"),
        pytest.param({"kind": "null", "value": 0}, id="null-with-zero"),
        pytest.param({"kind": "null", "value": False}, id="null-with-false"),
        pytest.param({"kind": "null", "value": ""}, id="null-with-empty-string"),
        pytest.param({"kind": "null", "value": None, "extra": 0}, id="null-extra-field"),
        pytest.param({"kind": "bool", "value": None}, id="bool-with-null"),
        pytest.param({"kind": "i64", "value": None}, id="i64-with-null"),
        pytest.param({"kind": "f64", "value": None}, id="f64-with-null"),
        pytest.param({"kind": "string", "value": None}, id="string-with-null"),
    ],
)
def test_tagged_null_and_nonnull_coupling_is_mandatory(payload: dict[str, object]) -> None:
    _expect_failure(
        lambda: returned.decode_provenance_value_projection(payload),
        category="structural_projection_invalid",
    )


def test_tagged_values_reject_unapproved_tags_types_numbers_and_domain_objects() -> None:
    invalid_payloads: tuple[object, ...] = (
        {},
        {"kind": "unknown", "value": 1},
        {"kind": "i64", "value": True},
        {"kind": "bool", "value": 1},
        {"kind": "i64", "value": 2**63},
        {"kind": "i64", "value": -(2**63) - 1},
        {"kind": "f64", "value": 1.0},
        {"kind": "f64", "value": "f64:7ff0000000000000"},
        {"kind": "f64", "value": "f64:fff0000000000000"},
        {"kind": "f64", "value": "f64:7ff8000000000000"},
        {"kind": "string", "value": "e\u0301"},
        {"kind": "string", "value": "\ud800"},
    )
    for payload in invalid_payloads:
        _expect_failure(
            returned.decode_provenance_value_projection,
            payload,
            category="structural_projection_invalid",
        )

    unsupported: tuple[object, ...] = (
        [],
        (),
        {},
        b"bytes",
        object(),
        _UnsupportedEnum.VALUE,
        _UnsupportedDataclass(1),
    )
    for value in unsupported:
        _expect_failure(
            returned.project_provenance_value,
            value,
            category="structural_projection_invalid",
        )


@pytest.mark.parametrize("mode", ["empty", "all-kinds-and-mutation", "order-and-duplicates"])
def test_provenance_projection_is_ordered_strict_and_deterministic(mode: str) -> None:
    if mode == "empty":
        domain = Provenance(method="manual", version="v1", details=())
        projection = returned.project_provenance(domain)
        assert projection.details == ()
        assert (
            returned.decode_run_provenance_projection(returned.projection_as_dict(projection))
            == projection
        )
        assert returned.reconstruct_provenance(projection) == domain
        assert returned.projection_matches_domain(projection, domain)
        return

    domain = _provenance()
    projection = returned.project_provenance(domain)
    if mode == "all-kinds-and-mutation":
        assert tuple(value.kind for _, value in projection.details) == (
            "null",
            "bool",
            "i64",
            "f64",
            "string",
        )
        assert tuple(key for key, _ in projection.details) == tuple(
            key for key, _ in domain.details
        )
        assert (
            returned.project_provenance(returned.reconstruct_provenance(projection)) == projection
        )
        assert returned.project_provenance(domain) == returned.project_provenance(domain)
        changed = replace(
            projection,
            details=projection.details[:-1]
            + (("e-string", returned.ProvenanceValueProjection("string", "changed")),),
        )
        assert not returned.projection_matches_domain(changed, domain)
        assert returned.projection_matches_domain(changed, returned.reconstruct_provenance(changed))
        return

    reversed_details = replace(projection, details=tuple(reversed(projection.details)))
    duplicate_details = replace(
        projection,
        details=projection.details + ((projection.details[-1][0], projection.details[-1][1]),),
    )
    for invalid in (reversed_details, duplicate_details):
        _expect_failure(
            returned.reconstruct_provenance,
            invalid,
            category="scientific_record_invalid",
            path="provenance",
        )


def test_candidate_projection_round_trips_every_field_without_params_mapping() -> None:
    domain = _candidate()
    projection = returned.project_candidate(domain)

    assert projection == returned.RunCandidateProjection(
        candidate_id="candidate-1",
        learning_rate=f64(0.125),
        model_width=64,
        optimizer="adam",
        regularization=f64(0.0625),
    )
    assert (
        returned.decode_run_candidate_projection(returned.projection_as_dict(projection))
        == projection
    )
    assert returned.reconstruct_candidate(projection) == domain
    assert returned.projection_matches_domain(projection, domain)
    zero_domain = replace(domain, model_width=0)
    bool_projection = replace(returned.project_candidate(zero_domain), model_width=False)
    _expect_failure(
        lambda: returned.projection_matches_domain(bool_projection, zero_domain),
        category="structural_projection_invalid",
    )


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"candidate_id": "candidate-other"}, id="candidate-id"),
        pytest.param({"learning_rate": f64(0.25)}, id="learning-rate"),
        pytest.param({"model_width": 128}, id="model-width"),
        pytest.param({"optimizer": "sgd"}, id="optimizer"),
        pytest.param({"regularization": f64(0.125)}, id="regularization"),
    ],
)
def test_candidate_field_total_comparison_detects_each_mutation(
    change: dict[str, object],
) -> None:
    domain = _candidate()
    payload = returned.projection_as_dict(returned.project_candidate(domain)) | change
    mutated = returned.decode_run_candidate_projection(payload)

    assert not returned.projection_matches_domain(mutated, domain)
    assert returned.projection_matches_domain(mutated, returned.reconstruct_candidate(mutated))


@pytest.mark.parametrize("mode", ["round-trip-and-context", "field-mutations"])
def test_completed_experiment_projection_is_nested_and_context_explicit(mode: str) -> None:
    domain = _experiment()
    projection = returned.project_completed_experiment(domain)
    if mode == "round-trip-and-context":
        assert (
            returned.decode_run_completed_experiment_projection(
                returned.projection_as_dict(projection)
            )
            == projection
        )
        assert returned.reconstruct_completed_experiment(projection) == domain
        assert returned.projection_matches_domain(projection, domain)
        returned.validate_completed_experiment_relation(projection, expected_record_id=11)
        _expect_failure(
            lambda: returned.validate_completed_experiment_relation(
                projection, expected_record_id=None
            ),
            category="missing_relation_context",
        )
        _expect_failure(
            lambda: returned.validate_completed_experiment_relation(
                projection, expected_record_id=12
            ),
            category="scientific_record_invalid",
        )
        return

    changes = (
        {"candidate": returned.project_candidate(_candidate(candidate_id="candidate-cross-run"))},
        {"created_at": T1},
        {"observed_value": f64(-0.5)},
        {"record_id": 12},
    )
    for change in changes:
        mutated = replace(projection, **change)
        assert not returned.projection_matches_domain(mutated, domain)
        assert returned.projection_matches_domain(
            mutated, returned.reconstruct_completed_experiment(mutated)
        )
    malformed = replace(projection, candidate=cast(Any, object()))
    _expect_failure(
        lambda: returned.reconstruct_completed_experiment(malformed),
        category="structural_projection_invalid",
    )


@pytest.mark.parametrize("mode", ["round-trip-and-context", "mutations-and-rejections"])
def test_evidence_projection_preserves_order_provenance_and_relations(mode: str) -> None:
    domain = _evidence()
    projection = returned.project_evidence(domain)
    if mode == "round-trip-and-context":
        assert projection.source_experiment_ids == (11, 12)
        assert (
            returned.decode_run_evidence_projection(returned.projection_as_dict(projection))
            == projection
        )
        assert returned.reconstruct_evidence(projection) == domain
        assert returned.projection_matches_domain(projection, domain)
        returned.validate_evidence_relations(
            projection,
            expected_source_experiment_ids=(11, 12),
            expected_created_at=T1,
        )
        return

    for source_ids in ((12, 11), (11, 11)):
        invalid = replace(projection, source_experiment_ids=source_ids)
        _expect_failure(
            returned.reconstruct_evidence,
            invalid,
            category="scientific_record_invalid",
            path="evidence",
        )
    alternate_provenance = replace(projection.provenance, method="other-method")
    changes = (
        {"evidence_id": "evidence-other"},
        {"observed_comparison": f64(-0.5)},
        {"observed_outcome": "right-better"},
        {"provenance": alternate_provenance},
        {"source_experiment_ids": (21, 22)},
    )
    for change in changes:
        mutated = replace(projection, **change)
        assert not returned.projection_matches_domain(mutated, domain)
        assert returned.projection_matches_domain(mutated, returned.reconstruct_evidence(mutated))
    cross_reference = replace(projection, source_experiment_ids=(21, 22))
    _expect_failure(
        lambda: returned.validate_evidence_relations(
            cross_reference,
            expected_source_experiment_ids=(11, 12),
            expected_created_at=T1,
        ),
        category="scientific_record_invalid",
    )
    _expect_failure(
        lambda: returned.validate_evidence_relations(
            projection,
            expected_source_experiment_ids=None,
            expected_created_at=T1,
        ),
        category="missing_relation_context",
    )
    _expect_failure(
        lambda: returned.validate_evidence_relations(
            projection,
            expected_source_experiment_ids=(11, 12),
            expected_created_at=T0,
        ),
        category="scientific_record_invalid",
    )
    _expect_failure(
        lambda: returned.validate_evidence_relations(
            projection,
            expected_source_experiment_ids=(11, 12),
            expected_created_at=cast(Any, 0),
        ),
        category="structural_projection_invalid",
    )


@pytest.mark.parametrize("mode", ["round-trip-and-parent", "invariants-order-and-lineage"])
def test_belief_state_projection_enforces_parallel_ordered_lineage(mode: str) -> None:
    update = _valid_update()
    initial = returned.project_belief_state(update.belief_state_before)
    child = returned.project_belief_state(update.posterior_belief_state)
    if mode == "round-trip-and-parent":
        assert initial.parent_belief_state_id is None
        assert initial.sequence == 0
        assert child.parent_belief_state_id == initial.belief_state_id
        assert child.sequence == 1
        assert (
            returned.decode_run_belief_state_projection(returned.projection_as_dict(initial))
            == initial
        )
        assert returned.reconstruct_belief_state(initial) == update.belief_state_before
        assert returned.reconstruct_belief_state(child) == update.posterior_belief_state
        assert returned.projection_matches_domain(child, update.posterior_belief_state)
        returned.validate_belief_state_relation(child, expected_state=update.posterior_belief_state)
        return

    invalid = (
        replace(initial, posterior_probabilities=(f64(1.0),)),
        replace(initial, posterior_probabilities=(f64(-0.25), f64(1.25))),
        replace(
            initial,
            posterior_probabilities=("f64:7fefffffffffffff",) * 2,
        ),
        replace(initial, hypothesis_ids=tuple(reversed(initial.hypothesis_ids))),
        replace(initial, parent_belief_state_id="belief-parent"),
        replace(initial, sequence=1),
        replace(child, parent_belief_state_id=None),
    )
    for projection in invalid:
        _expect_failure(
            returned.reconstruct_belief_state,
            projection,
            category="scientific_record_invalid",
            path="belief_state",
        )

    second = BayesianBeliefUpdater().update(
        hypotheses=_hypotheses(),
        belief_state=update.posterior_belief_state,
        evidence=_evidence(evidence_id="evidence-2", source_ids=(13, 14), created_at=T1),
    )
    lineage = returned.project_belief_state(second.posterior_belief_state)
    reordered_evidence = replace(lineage, evidence_ids=tuple(reversed(lineage.evidence_ids)))
    assert returned.reconstruct_belief_state(reordered_evidence).evidence_ids == (
        "evidence-2",
        "evidence-1",
    )
    _expect_failure(
        lambda: returned.validate_belief_state_relation(
            reordered_evidence, expected_state=second.posterior_belief_state
        ),
        category="scientific_record_invalid",
    )
    changed_identity = replace(initial, belief_state_id="belief-cross-run")
    assert not returned.projection_matches_domain(changed_identity, update.belief_state_before)
    assert returned.projection_matches_domain(
        changed_identity, returned.reconstruct_belief_state(changed_identity)
    )
    changed_parent = replace(child, parent_belief_state_id="belief-cross-lineage")
    _expect_failure(
        lambda: returned.validate_belief_state_relation(
            changed_parent, expected_state=update.posterior_belief_state
        ),
        category="scientific_record_invalid",
    )
    _expect_failure(
        lambda: returned.validate_belief_state_relation(initial, expected_state=None),
        category="missing_relation_context",
    )


@pytest.mark.parametrize("mode", ["round-trip", "mutations-and-invalid-numeric"])
def test_hypothesis_likelihood_projection_enforces_numeric_invariants(mode: str) -> None:
    domain = _valid_update().likelihoods[0]
    projection = returned.project_hypothesis_likelihood(domain)
    if mode == "round-trip":
        assert (
            returned.decode_run_hypothesis_likelihood_projection(
                returned.projection_as_dict(projection)
            )
            == projection
        )
        assert returned.reconstruct_hypothesis_likelihood(projection) == domain
        assert returned.projection_matches_domain(projection, domain)
        return

    numeric_fields = (
        "likelihood",
        "posterior_probability",
        "prior_for_update",
        "unnormalized_weight",
    )
    changes = ({"hypothesis_id": "h-other"},) + tuple(
        {field: f64(0.625)} for field in numeric_fields
    )
    for change in changes:
        mutated = replace(projection, **change)
        assert not returned.projection_matches_domain(mutated, domain)
        assert returned.projection_matches_domain(
            mutated, returned.reconstruct_hypothesis_likelihood(mutated)
        )
    for nonfinite in (
        "f64:7ff0000000000000",
        "f64:fff0000000000000",
        "f64:7ff8000000000000",
    ):
        _expect_failure(
            returned.reconstruct_hypothesis_likelihood,
            replace(projection, likelihood=nonfinite),
            category="structural_projection_invalid",
        )
    for field in numeric_fields:
        invalid = replace(projection, **{field: f64(-0.125)})
        _expect_failure(
            returned.reconstruct_hypothesis_likelihood,
            invalid,
            category="scientific_record_invalid",
            path="hypothesis_likelihood",
        )


@pytest.mark.parametrize(
    "mode", ["updater-round-trip", "relations-and-arithmetic", "identities-context-and-order"]
)
def test_belief_update_projection_reuses_updater_relations_and_arithmetic(mode: str) -> None:
    domain = _valid_update()
    projection = returned.project_belief_update(domain)
    if mode == "updater-round-trip":
        assert (
            returned.decode_run_belief_update_projection(returned.projection_as_dict(projection))
            == projection
        )
        assert returned.reconstruct_belief_update(projection) == domain
        assert tuple(item.hypothesis_id for item in projection.likelihoods) == (
            "h-a",
            "h-b",
        )
        assert returned.projection_matches_domain(projection, domain)
        returned.validate_belief_update_relation(projection, expected_update=domain)
        _expect_failure(
            lambda: returned.validate_belief_update_relation(projection),
            category="missing_relation_context",
        )
        return

    if mode == "relations-and-arithmetic":
        changed_before = replace(projection.belief_state_before, belief_state_id="belief-other")
        wrong_parent = replace(
            projection.posterior_belief_state, parent_belief_state_id="belief-other"
        )
        wrong_evidence = replace(
            projection.posterior_belief_state, evidence_ids=("evidence-other",)
        )
        wrong_hypothesis = replace(projection.likelihoods[0], hypothesis_id="h-c")
        wrong_weight = replace(projection.likelihoods[0], unnormalized_weight=f64(0.625))
        wrong_likelihood_posterior = replace(
            projection.likelihoods[0], posterior_probability=f64(0.625)
        )
        wrong_posterior = replace(
            projection.posterior_belief_state,
            posterior_probabilities=(f64(0.625), f64(0.375)),
        )
        invalid = (
            replace(projection, belief_state_before=changed_before),
            replace(projection, posterior_belief_state=wrong_parent),
            replace(projection, posterior_belief_state=wrong_evidence),
            replace(projection, likelihoods=tuple(reversed(projection.likelihoods))),
            replace(projection, likelihoods=(wrong_hypothesis, projection.likelihoods[1])),
            replace(
                projection,
                normalization_constant=f64(domain.normalization_constant + 0.125),
            ),
            replace(projection, likelihoods=(wrong_weight, projection.likelihoods[1])),
            replace(
                projection,
                likelihoods=(wrong_likelihood_posterior, projection.likelihoods[1]),
            ),
            replace(projection, posterior_belief_state=wrong_posterior),
        )
        for mutated in invalid:
            _expect_failure(
                returned.reconstruct_belief_update,
                mutated,
                category="scientific_record_invalid",
            )
        return

    changed_provenance = replace(projection.provenance, method="other-update-method")
    changed_evidence = replace(projection.evidence, observed_outcome="same-inner-id-new-value")
    changed_posterior_id = replace(
        projection.posterior_belief_state, belief_state_id="belief-other"
    )
    accepted_identity_changes = (
        replace(projection, provenance=changed_provenance),
        replace(projection, update_id="update-other"),
        replace(projection, update_rule_version="bayesian-update/v2"),
        replace(projection, evidence=changed_evidence),
        replace(projection, posterior_belief_state=changed_posterior_id),
    )
    for mutated in accepted_identity_changes:
        rebuilt = returned.reconstruct_belief_update(mutated)
        assert not returned.projection_matches_domain(mutated, domain)
        assert returned.projection_matches_domain(mutated, rebuilt)
    assert accepted_identity_changes[3].update_id == projection.update_id
    assert accepted_identity_changes[3].evidence.evidence_id == projection.evidence.evidence_id

    assert returned.projection_matches_domain(projection, domain)
    assert not returned.projection_matches_domain(
        projection, replace(domain, update_id="update-cross-run")
    )
    _expect_failure(
        lambda: returned.validate_belief_update_relation(
            projection, expected_update=replace(domain, update_id="update-cross-run")
        ),
        category="scientific_record_invalid",
    )
    invalid_before = replace(
        projection.belief_state_before,
        posterior_probabilities=(f64(-0.25), f64(1.25)),
    )
    invalid_evidence = replace(projection.evidence, source_experiment_ids=(12, 11))
    doubly_invalid = replace(
        projection,
        belief_state_before=invalid_before,
        evidence=invalid_evidence,
    )
    first = _expect_failure(
        lambda: returned.reconstruct_belief_update(doubly_invalid),
        category="scientific_record_invalid",
        path="evidence",
    )
    second = _expect_failure(
        lambda: returned.reconstruct_belief_update(doubly_invalid),
        category="scientific_record_invalid",
        path="evidence",
    )
    assert str(first) == str(second)

    bad = cast(Any, [])
    bad_before = replace(
        projection,
        belief_state_before=replace(
            projection.belief_state_before, belief_state_id=bad, evidence_ids=bad
        ),
        likelihoods=bad,
    )
    bad_evidence = replace(
        projection,
        evidence=replace(projection.evidence, created_at=bad, source_experiment_ids=bad),
        likelihoods=bad,
    )
    for malformed_projection, first_path in (
        (bad_before, "belief_state.belief_state_id"),
        (bad_evidence, "evidence.created_at"),
    ):
        _expect_failure(
            returned.projection_as_dict,
            malformed_projection,
            category="structural_projection_invalid",
            path=first_path,
        )


def test_all_foundational_decoders_are_closed_strict_and_noncoercing() -> None:
    provenance = returned.project_provenance(_provenance())
    candidate = returned.project_candidate(_candidate())
    experiment = returned.project_completed_experiment(_experiment())
    evidence = returned.project_evidence(_evidence())
    belief_state = returned.project_belief_state(_initial_state())
    likelihood = returned.project_hypothesis_likelihood(_valid_update().likelihoods[0])
    update = returned.project_belief_update(_valid_update())
    projections_and_decoders: tuple[tuple[object, Callable[[object], object], str], ...] = (
        (provenance, returned.decode_run_provenance_projection, "method"),
        (candidate, returned.decode_run_candidate_projection, "candidate_id"),
        (experiment, returned.decode_run_completed_experiment_projection, "record_id"),
        (evidence, returned.decode_run_evidence_projection, "evidence_id"),
        (belief_state, returned.decode_run_belief_state_projection, "sequence"),
        (likelihood, returned.decode_run_hypothesis_likelihood_projection, "hypothesis_id"),
        (update, returned.decode_run_belief_update_projection, "update_id"),
    )
    for projection, decoder, missing_field in projections_and_decoders:
        payload = returned.projection_as_dict(projection)
        assert decoder(payload) == projection
        with_extra = dict(payload)
        with_extra["unexpected"] = None
        _expect_failure(decoder, with_extra, category="structural_projection_invalid")
        with_missing = dict(payload)
        del with_missing[missing_field]
        _expect_failure(decoder, with_missing, category="structural_projection_invalid")
        _expect_failure(decoder, tuple(payload.items()), category="structural_projection_invalid")

    raw = returned.projection_as_dict
    raw_nested_substitutions = (
        replace(
            provenance,
            details=((provenance.details[0][0], cast(Any, raw(provenance.details[0][1]))),),
        ),
        replace(experiment, candidate=cast(Any, raw(candidate))),
        replace(evidence, provenance=cast(Any, raw(provenance))),
        replace(update, belief_state_before=cast(Any, raw(update.belief_state_before))),
        replace(update, evidence=cast(Any, raw(update.evidence))),
        replace(
            update,
            likelihoods=(cast(Any, raw(update.likelihoods[0])), update.likelihoods[1]),
        ),
        replace(update, posterior_belief_state=cast(Any, raw(update.posterior_belief_state))),
        replace(update, provenance=cast(Any, raw(update.provenance))),
    )
    for malformed_projection in raw_nested_substitutions:
        _expect_failure(raw, malformed_projection, category="structural_projection_invalid")

    invalid_candidate_payloads = []
    for field, value in (
        ("model_width", True),
        ("learning_rate", 0.125),
        ("optimizer", "e\u0301"),
    ):
        payload = returned.projection_as_dict(candidate)
        payload[field] = value
        invalid_candidate_payloads.append(payload)
    for payload in invalid_candidate_payloads:
        _expect_failure(
            returned.decode_run_candidate_projection,
            payload,
            category="structural_projection_invalid",
        )

    provenance_payload = returned.projection_as_dict(provenance)
    provenance_payload["details"] = tuple(cast(Any, provenance_payload["details"]))
    _expect_failure(
        lambda: returned.decode_run_provenance_projection(provenance_payload),
        category="structural_projection_invalid",
        path="provenance.details",
    )


def test_architecture_is_handwritten_without_reflection_hashes_or_side_effect_calls() -> None:
    module_path = Path(returned.__file__ or "")
    source = module_path.read_text(encoding="utf-8")
    called_names = architecture.called_function_names(source)

    assert all(passed for _name, passed in architecture.returned_run_architecture_checks(source))
    assert architecture.returned_run_path_imports_are_authorized(source)
    assert called_names.isdisjoint(architecture.PERMANENT_FORBIDDEN_CALLS)
    assert architecture.dynamic_projection_class_assignments(source) == set()


def _replace_shape_authority_once(source: str, old: str, new: str) -> str:
    function = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef)
        and node.name == "validate_returned_run_projection_shape"
    )
    segment = ast.get_source_segment(source, function)
    assert segment is not None and segment.count(old) == 1
    return source.replace(segment, segment.replace(old, new, 1), 1)


@pytest.mark.parametrize(
    "case",
    (
        "omit-policy-trace-payload-type-check",
        "use-isinstance-for-projection-acceptance",
        "permit-mapping-coercion",
        "permit-plain-object-matching-attributes",
        "map-policy-trace-before-coupling",
        "omit-provenance-tagged-payload-check",
        "introduce-second-returned-run-topology-table",
    ),
)
def test_deep_shape_architecture_mutations_have_independent_findings(
    case: str,
) -> None:
    module_path = Path(returned.__file__ or "")
    source = module_path.read_text(encoding="utf-8")
    if case == "omit-policy-trace-payload-type-check":
        mutated = _replace_shape_authority_once(
            source,
            "            if type(raw.projection) is not RunDecisionTraceProjection:\n"
            "                _structural(\n"
            '                    f"{tag_path}.projection",\n'
            '                    "tag and projection type do not match",\n'
            "                )\n",
            "",
        )
        intended_check = "explicit-returned-run-tag-payload-coupling"
    elif case == "use-isinstance-for-projection-acceptance":
        mutated = _replace_shape_authority_once(
            source,
            "        if type(raw) is not ReturnedRunProjection:\n",
            "        if not isinstance(raw, ReturnedRunProjection):\n",
        )
        intended_check = "no-returned-run-shape-reflection-or-coercion"
    elif case == "permit-mapping-coercion":
        mutated = _replace_shape_authority_once(
            source,
            "    Policy-trace coupling and the schema version remain structural in both modes.\n"
            '    """\n\n',
            "    Policy-trace coupling and the schema version remain structural in both modes.\n"
            '    """\n\n'
            "    raw_mapping = dict(value)\n",
        )
        intended_check = "no-returned-run-shape-reflection-or-coercion"
    elif case == "permit-plain-object-matching-attributes":
        mutated = _replace_shape_authority_once(
            source,
            "        if type(raw) is not RunPolicyTraceProjection:\n",
            '        if not hasattr(raw, "projection"):\n',
        )
        intended_check = "no-returned-run-shape-reflection-or-coercion"
    elif case == "map-policy-trace-before-coupling":
        mutated = _replace_shape_authority_once(
            source,
            '        tag_path = "policy_trace" if _defer_scientific_validation else field_path\n',
            "        _policy_trace_mapping(raw)\n"
            '        tag_path = "policy_trace" if _defer_scientific_validation else field_path\n',
        )
        intended_check = "exact-returned-run-deep-shape-authority"
    elif case == "omit-provenance-tagged-payload-check":
        mutated = _replace_shape_authority_once(
            source,
            '        elif kind == "bool":\n'
            '            _boolean_value(payload, f"{field_path}.value")\n',
            '        elif kind == "bool":\n            pass\n',
        )
        intended_check = "exact-returned-run-deep-shape-authority"
    else:
        names = ", ".join(sorted(architecture.RETURNED_RUN_SHAPE_PROJECTION_TYPES))
        mutated = f"{source}\nRETURNED_RUN_TOPOLOGY = ({names},)\n"
        intended_check = "single-returned-run-deep-shape-authority"
    assert mutated != source
    checks = dict(architecture.returned_run_architecture_checks(mutated))
    assert checks[intended_check] is False


def test_architecture_has_no_scientific_import_cycle_or_execution_dependency() -> None:
    module_path = Path(returned.__file__ or "")
    source = module_path.read_text(encoding="utf-8")
    assert all(pattern not in source for pattern in architecture.forbidden_source_or_ast_patterns())
    assert "cannot retain" in source
    assert "duplicate JSON object keys" in source

    package_root = module_path.parents[1]
    for scientific_module in (
        package_root / "types.py",
        package_root / "reasoning.py",
        package_root / "belief_models.py",
    ):
        assert "broader_returned_run" not in scientific_module.read_text(encoding="utf-8")


def test_architecture_has_exact_stage_aware_projection_surface_without_leaf_identities() -> None:
    module_path = Path(returned.__file__ or "")
    source = module_path.read_text(encoding="utf-8")
    classes = architecture.top_level_class_names(source)

    assert architecture.is_exact_authorized_top_level_class_set(classes)
    assert all(pattern not in source for pattern in architecture.forbidden_source_or_ast_patterns())


def test_central_architecture_guard_is_closed_and_stage_aware() -> None:
    expected = set(architecture.AUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES)

    checks = architecture.current_stage_manifest_regression_checks()
    assert checks
    assert all(passed for _name, passed in checks)
    assert len(expected) == architecture.EXPECTED_AUTHORIZED_TOP_LEVEL_CLASS_COUNT
    assert not architecture.imports_are_authorized({"os"})
    assert not architecture.imports_are_authorized({"broader_execution"})
    assert architecture.imports_are_authorized({"broader_oracle"})
    assert not architecture.returned_run_path_imports_are_authorized(
        "from .broader_oracle import authorize_observation\n"
    )
    assert not architecture.returned_run_path_imports_are_authorized(
        "from .broader_oracle import world_authority\n"
    )
    assert architecture.returned_run_path_imports_are_authorized(
        "from .broader_calibration_selector_replay import replay_calibration_history_selection\n"
    )
    assert not architecture.returned_run_path_imports_are_authorized(
        "from .broader_calibration_selector_replay import raw_effect_sha256\n"
    )
    assert architecture.returned_run_path_imports_are_authorized(
        "from .broader_calibration_history import expected_calibration_effect\n"
    )
    assert not architecture.returned_run_path_imports_are_authorized(
        "from .broader_calibration_history import _validate_effects\n"
    )
    assert not architecture.returned_run_path_imports_are_authorized(
        "from research_decision_engine.shadow.broader_oracle import calibration_key\n"
    )
    assert not architecture.returned_run_path_imports_are_authorized(
        "from . import broader_calibration_selector_replay\n"
        "broader_calibration_selector_replay.raw_effect_sha256(effect)\n"
    )
    assert architecture.module_import_names_are_authorized(
        "from research_decision_engine.benchmarks.broader_oracle import calibration_key\n",
        "broader_oracle",
        frozenset({"calibration_key"}),
    )
    assert not architecture.PERMANENT_FORBIDDEN_CALLS.isdisjoint({"asdict"})
    assert not architecture.called_function_names("_validate_effects(())\n").isdisjoint(
        architecture.PERMANENT_FORBIDDEN_CALLS
    )
    assert not architecture.called_function_names("getattr(value, 'field')\n").isdisjoint(
        architecture.PERMANENT_FORBIDDEN_CALLS
    )
    assert "_validate_observations" in architecture.PERMANENT_FORBIDDEN_SOURCE_OR_AST_PATTERNS
    assert "ObservationAuthority" in architecture.PERMANENT_FORBIDDEN_SOURCE_OR_AST_PATTERNS
    assert "selected_only_interface" in architecture.PERMANENT_FORBIDDEN_SOURCE_OR_AST_PATTERNS
    assert (
        "result_payload_sha256" not in architecture.CURRENT_STAGE_FORBIDDEN_SOURCE_OR_AST_PATTERNS
    )
    assert "returned_result_id" in architecture.CURRENT_STAGE_FORBIDDEN_SOURCE_OR_AST_PATTERNS


def test_calibration_selector_replay_is_the_only_exact_raw_sha256_exception() -> None:
    returned_path = Path(returned.__file__ or "")
    helper_path = returned_path.with_name("broader_calibration_selector_replay.py")
    helper_source = helper_path.read_text(encoding="utf-8")
    checks = architecture.selector_replay_helper_architecture_checks(helper_source)

    assert checks
    assert all(passed for _name, passed in checks)
    assert architecture.hashlib_use_is_authorized_for_path(str(helper_path), helper_source)
    assert not architecture.hashlib_use_is_authorized_for_path(
        str(helper_path.with_name("additional_replay.py")), helper_source
    )
    assert not architecture.hashlib_use_is_authorized_for_path(
        str(helper_path), helper_source + "\nhashlib.sha256(b'additional')\n"
    )
    assert not architecture.hashlib_use_is_authorized_for_path(
        str(helper_path), helper_source.replace("hashlib.sha256(", "protocol_hash(", 1)
    )

    returned_with_hash = (
        returned_path.read_text(encoding="utf-8")
        + "\nimport hashlib\n"
        + "hashlib.sha256(b'forbidden')\n"
    )
    assert not architecture.hashlib_use_is_authorized_for_path(
        str(returned_path), returned_with_hash
    )


def test_central_architecture_expectations_are_explicit_test_owned_literals() -> None:
    helper_path = Path(architecture.__file__ or "")
    helper_source = helper_path.read_text(encoding="utf-8")
    helper_tree = ast.parse(helper_source)
    imported = architecture.imported_module_roots(helper_source)

    assert imported <= {"__future__", "ast", "hashlib", "typing"}
    assert "from research_decision_engine" not in helper_source
    assert "import research_decision_engine" not in helper_source
    assert "getmembers" not in architecture.called_function_names(helper_source)
    assert "globals" not in architecture.called_function_names(helper_source)
    assert any(
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "AUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES"
        for node in helper_tree.body
    )
