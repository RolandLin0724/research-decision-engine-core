from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields, replace
from functools import partial
from typing import Any, cast

import pytest

from research_decision_engine.benchmarks import broader_returned_run as returned
from research_decision_engine.benchmarks.broader_protocol import f64
from research_decision_engine.decision import (
    INFORMATION_GAIN_POLICY,
    CandidateScore,
    DecisionTrace,
    HypothesisDecisionContext,
    InformationGainPolicy,
)
from research_decision_engine.evidence_eligibility import PublicExperimentDesign
from research_decision_engine.reasoning import Provenance
from research_decision_engine.types import Candidate

PUBLIC_DESIGN_FIELDS = (
    "candidate_id",
    "comparison_group_id",
    "controlled_variables",
    "experiment_family",
    "intervention_arm",
    "intervention_variable",
)
HYPOTHESIS_CONTEXT_FIELDS = (
    "hypothesis_id",
    "most_favorable_outcome",
    "most_favorable_outcome_label",
    "posterior_if_observed",
    "posterior_probability",
    "statement",
)
CANDIDATE_SCORE_FIELDS = (
    "candidate",
    "completes_matched_pair",
    "estimated_cost",
    "expected_information_gain",
    "expected_posterior_entropy",
    "matched_experiment_id",
    "prior_entropy",
    "ranking_reason",
    "score_reason",
)
DECISION_TRACE_FIELDS = (
    "belief_state_id",
    "created_at",
    "fallback_reason",
    "hypotheses",
    "max_cost",
    "policy",
    "policy_version",
    "provenance",
    "ranked_candidates",
    "rationale",
    "selected",
    "suggestion_id",
)
_NO_RESULT = object()
_EFFECT_LEDGER = (
    ("scientific_outputs", 0),
    ("recommendations", 0),
    ("capabilities_issued", 0),
    ("evidence_writes", 0),
    ("production_mutations", 0),
)


def _failure(
    operation: Callable[[], object],
    *,
    category: str,
    path: str | None = None,
) -> returned.ReturnedRunProjectionError:
    before = _EFFECT_LEDGER
    result: object = _NO_RESULT
    with pytest.raises(returned.ReturnedRunProjectionError) as captured:
        result = operation()
    error = captured.value
    assert result is _NO_RESULT
    assert before == _EFFECT_LEDGER
    assert error.category == category
    if path is not None:
        assert error.path == path
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


def _candidate(candidate_id: str = "candidate-a", *, optimizer: str = "adam") -> Candidate:
    return Candidate(
        candidate_id=candidate_id,
        learning_rate=0.125,
        regularization=0.0625,
        model_width=64,
        optimizer=optimizer,
    )


def _design() -> PublicExperimentDesign:
    return PublicExperimentDesign(
        candidate_id="candidate-a",
        experiment_family="optimizer-comparison",
        comparison_group_id="group-1",
        controlled_variables=(
            ("batch_size", 64),
            ("dropout", 0.125),
            ("schedule", "cosine"),
        ),
        intervention_variable="optimizer",
        intervention_arm="adam",
    )


def _hypothesis(
    hypothesis_id: str = "hypothesis-a", *, shift: float = 0.0
) -> HypothesisDecisionContext:
    return HypothesisDecisionContext(
        hypothesis_id=hypothesis_id,
        statement=f"statement for {hypothesis_id}",
        posterior_probability=0.625 - shift,
        most_favorable_outcome=0.25 + shift,
        most_favorable_outcome_label="positive",
        posterior_if_observed=0.75 - shift,
    )


def _score(
    candidate_id: str = "candidate-a",
    *,
    matched_experiment_id: int | None = None,
) -> CandidateScore:
    return CandidateScore(
        candidate=_candidate(candidate_id),
        expected_information_gain=0.25,
        prior_entropy=0.75,
        expected_posterior_entropy=0.5,
        estimated_cost=2.0,
        completes_matched_pair=matched_experiment_id is not None,
        matched_experiment_id=matched_experiment_id,
        score_reason=f"score for {candidate_id}",
        ranking_reason=f"rank for {candidate_id}",
    )


def _trace(*, fallback_reason: str | None = None) -> DecisionTrace:
    first = _score("candidate-a", matched_experiment_id=11)
    second = _score("candidate-b")
    return DecisionTrace(
        suggestion_id="suggestion-1",
        policy=INFORMATION_GAIN_POLICY,
        policy_version="information-gain/v1",
        created_at="2026-01-01T00:00:00+00:00",
        belief_state_id="belief-1",
        selected=first,
        hypotheses=(
            _hypothesis("hypothesis-a"),
            _hypothesis("hypothesis-b", shift=0.125),
        ),
        max_cost=4.0,
        fallback_reason=fallback_reason,
        rationale="candidate-a ranks first",
        ranked_candidates=(first, second),
        provenance=Provenance(
            method="information-gain",
            version="provenance/v1",
            details=(("belief_state_id", "belief-1"),),
        ),
    )


@pytest.mark.parametrize(
    ("value", "kind", "encoded"),
    [
        pytest.param(-7, "i64", -7, id="i64"),
        pytest.param(0.125, "f64", f64(0.125), id="f64"),
        pytest.param("cosine", "string", "cosine", id="string"),
    ],
)
def test_control_value_has_an_exact_closed_tagged_round_trip(
    value: int | float | str, kind: str, encoded: int | str
) -> None:
    projection = returned.project_control_value(value)
    raw = returned.projection_as_dict(projection)

    assert raw == {"kind": kind, "value": encoded}
    assert tuple(raw) == ("kind", "value")
    assert returned.decode_control_value_projection(raw) == projection
    assert returned.control_value_from_projection(projection) == value
    assert returned.project_control_value(returned.control_value_from_projection(projection)) == (
        projection
    )


@pytest.mark.parametrize(
    ("payload", "path"),
    [
        pytest.param({"kind": "i64"}, "control_value.value", id="missing"),
        pytest.param({"kind": "i64", "value": 1, "extra": None}, "control_value", id="extra"),
        pytest.param({"kind": "bool", "value": True}, "control_value.kind", id="tag"),
        pytest.param({"kind": "i64", "value": True}, "control_value.value", id="bool-i64"),
        pytest.param({"kind": "i64", "value": 2**63}, "control_value.value", id="i64-range"),
        pytest.param({"kind": "f64", "value": 0.125}, "control_value.value", id="raw-float"),
        pytest.param(
            {"kind": "f64", "value": "f64:7ff0000000000000"},
            "control_value.value",
            id="nonfinite-f64",
        ),
        pytest.param(
            {"kind": "string", "value": "e\u0301"},
            "control_value.value",
            id="non-nfc",
        ),
    ],
)
def test_control_value_decoder_rejects_wrong_tags_types_and_encodings(
    payload: dict[str, object], path: str
) -> None:
    _failure(
        lambda: returned.decode_control_value_projection(payload),
        category="structural_projection_invalid",
        path=path,
    )


def test_control_value_projector_rejects_bool_and_unapproved_domain_types() -> None:
    unsupported: tuple[object, ...] = (True, None, [], {}, b"bytes")
    for value in unsupported:
        _failure(
            partial(returned.project_control_value, cast(Any, value)),
            category="structural_projection_invalid",
            path="control_value",
        )


def test_public_design_round_trips_all_control_branches_in_contract_order() -> None:
    domain = _design()
    projection = returned.project_public_experiment_design(domain)
    raw = returned.projection_as_dict(projection)

    assert tuple(field.name for field in fields(type(projection))) == PUBLIC_DESIGN_FIELDS
    assert tuple(raw) == PUBLIC_DESIGN_FIELDS
    assert raw["controlled_variables"] == [
        ["batch_size", {"kind": "i64", "value": 64}],
        ["dropout", {"kind": "f64", "value": f64(0.125)}],
        ["schedule", {"kind": "string", "value": "cosine"}],
    ]
    assert returned.decode_run_public_experiment_design_projection(raw) == projection
    assert returned.reconstruct_public_experiment_design(projection) == domain
    assert returned.projection_matches_domain(projection, domain)


@pytest.mark.parametrize("mode", ["closed", "list-shapes", "nested-tags-and-nfc"])
def test_public_design_decoder_is_closed_and_requires_ordered_json_pairs(mode: str) -> None:
    projection = returned.project_public_experiment_design(_design())
    if mode == "closed":
        missing = returned.projection_as_dict(projection)
        del missing["candidate_id"]
        _failure(
            lambda: returned.decode_run_public_experiment_design_projection(missing),
            category="structural_projection_invalid",
            path="public_experiment_design.candidate_id",
        )
        extra = returned.projection_as_dict(projection) | {"unexpected": None}
        _failure(
            lambda: returned.decode_run_public_experiment_design_projection(extra),
            category="structural_projection_invalid",
            path="public_experiment_design",
        )
        return

    raw = returned.projection_as_dict(projection)
    controlled = cast(list[object], raw["controlled_variables"])
    if mode == "list-shapes":
        raw["controlled_variables"] = tuple(controlled)
        _failure(
            lambda: returned.decode_run_public_experiment_design_projection(raw),
            category="structural_projection_invalid",
            path="public_experiment_design.controlled_variables",
        )
        raw = returned.projection_as_dict(projection)
        controlled = cast(list[object], raw["controlled_variables"])
        controlled[0] = tuple(cast(list[object], controlled[0]))
        _failure(
            lambda: returned.decode_run_public_experiment_design_projection(raw),
            category="structural_projection_invalid",
            path="public_experiment_design.controlled_variables[0]",
        )
        return

    first = cast(list[object], controlled[0])
    first[0] = "e\u0301"
    _failure(
        lambda: returned.decode_run_public_experiment_design_projection(raw),
        category="structural_projection_invalid",
        path="public_experiment_design.controlled_variables[0][0]",
    )
    raw = returned.projection_as_dict(projection)
    first = cast(list[object], cast(list[object], raw["controlled_variables"])[0])
    cast(dict[str, object], first[1])["kind"] = "bool"
    _failure(
        lambda: returned.decode_run_public_experiment_design_projection(raw),
        category="structural_projection_invalid",
        path="control_value.kind",
    )
    for field in ("experiment_family", "intervention_arm", "intervention_variable"):
        raw = returned.projection_as_dict(projection)
        raw[field] = "not an ID"
        _failure(
            partial(returned.decode_run_public_experiment_design_projection, raw),
            category="structural_projection_invalid",
            path=f"public_experiment_design.{field}",
        )


@pytest.mark.parametrize("mode", ["reversed", "duplicate"])
def test_public_design_constructor_science_rejects_unsorted_or_duplicate_names(mode: str) -> None:
    projection = returned.project_public_experiment_design(_design())
    controlled = projection.controlled_variables
    changed = (
        tuple(reversed(controlled))
        if mode == "reversed"
        else controlled + ((controlled[-1][0], controlled[-1][1]),)
    )
    _failure(
        lambda: returned.reconstruct_public_experiment_design(
            replace(projection, controlled_variables=changed)
        ),
        category="scientific_record_invalid",
        path="public_experiment_design",
    )


@pytest.mark.parametrize("mode", ["missing", "mismatch"])
def test_public_design_relation_requires_exact_explicit_context(mode: str) -> None:
    domain = _design()
    projection = returned.project_public_experiment_design(domain)
    if mode == "missing":
        _failure(
            lambda: returned.validate_public_experiment_design_relation(projection),
            category="missing_relation_context",
            path="public_experiment_design",
        )
        return
    _failure(
        lambda: returned.validate_public_experiment_design_relation(
            projection,
            expected_design=replace(domain, intervention_arm="sgd"),
        ),
        category="scientific_record_invalid",
        path="public_experiment_design",
    )


def test_hypothesis_context_round_trips_ordered_f64_fields_exactly() -> None:
    domain = _hypothesis()
    projection = returned.project_hypothesis_decision_context(domain)
    raw = returned.projection_as_dict(projection)

    assert tuple(field.name for field in fields(type(projection))) == HYPOTHESIS_CONTEXT_FIELDS
    assert tuple(raw) == HYPOTHESIS_CONTEXT_FIELDS
    assert raw["most_favorable_outcome"] == f64(domain.most_favorable_outcome)
    assert raw["posterior_if_observed"] == f64(domain.posterior_if_observed)
    assert raw["posterior_probability"] == f64(domain.posterior_probability)
    assert returned.decode_run_hypothesis_decision_context_projection(raw) == projection
    assert returned.reconstruct_hypothesis_decision_context(projection) == domain
    assert returned.projection_matches_domain(projection, domain)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("most_favorable_outcome", 0.25, id="raw-float"),
        pytest.param("posterior_if_observed", "f64:7ff0000000000000", id="infinity"),
        pytest.param("posterior_probability", True, id="bool"),
        pytest.param("statement", "e\u0301", id="non-nfc"),
    ],
)
def test_hypothesis_context_decoder_rejects_noncanonical_fields(field: str, value: object) -> None:
    raw = returned.projection_as_dict(returned.project_hypothesis_decision_context(_hypothesis()))
    raw[field] = value
    _failure(
        lambda: returned.decode_run_hypothesis_decision_context_projection(raw),
        category="structural_projection_invalid",
        path=f"hypothesis_decision_context.{field}",
    )


@pytest.mark.parametrize("mode", ["missing", "mismatch"])
def test_hypothesis_context_relation_requires_exact_explicit_context(mode: str) -> None:
    domain = _hypothesis()
    projection = returned.project_hypothesis_decision_context(domain)
    if mode == "missing":
        _failure(
            lambda: returned.validate_hypothesis_decision_context_relation(projection),
            category="missing_relation_context",
            path="hypothesis_decision_context",
        )
        return
    _failure(
        lambda: returned.validate_hypothesis_decision_context_relation(
            projection,
            expected_context=replace(domain, hypothesis_id="hypothesis-other"),
        ),
        category="scientific_record_invalid",
        path="hypothesis_decision_context",
    )


@pytest.mark.parametrize("matched_experiment_id", [None, 11])
def test_candidate_score_round_trips_both_exact_matched_pair_forms(
    matched_experiment_id: int | None,
) -> None:
    domain = _score(matched_experiment_id=matched_experiment_id)
    projection = returned.project_candidate_score(domain)
    raw = returned.projection_as_dict(projection)

    assert tuple(field.name for field in fields(type(projection))) == CANDIDATE_SCORE_FIELDS
    assert tuple(raw) == CANDIDATE_SCORE_FIELDS
    assert raw["matched_experiment_id"] == matched_experiment_id
    assert raw["completes_matched_pair"] is (matched_experiment_id is not None)
    assert returned.decode_run_candidate_score_projection(raw) == projection
    assert returned.reconstruct_candidate_score(projection) == domain
    assert returned.projection_matches_domain(projection, domain)


@pytest.mark.parametrize(
    ("completes", "matched_id"),
    [(True, None), (False, 11)],
)
def test_candidate_score_reconstruction_enforces_matched_pair_coupling(
    completes: bool, matched_id: int | None
) -> None:
    projection = returned.project_candidate_score(_score())
    _failure(
        lambda: returned.reconstruct_candidate_score(
            replace(
                projection,
                completes_matched_pair=completes,
                matched_experiment_id=matched_id,
            )
        ),
        category="scientific_record_invalid",
        path="candidate_score",
    )


@pytest.mark.parametrize(
    "field",
    [
        "estimated_cost",
        "expected_information_gain",
        "expected_posterior_entropy",
        "prior_entropy",
    ],
)
def test_candidate_score_reconstruction_enforces_nonnegative_finite_science(
    field: str,
) -> None:
    projection = returned.project_candidate_score(_score())
    _failure(
        lambda: returned.reconstruct_candidate_score(
            replace(projection, **cast(Any, {field: f64(-0.125)}))
        ),
        category="scientific_record_invalid",
        path="candidate_score",
    )


def test_candidate_score_decoder_is_closed_strict_nfc_and_noncoercing() -> None:
    projection = returned.project_candidate_score(_score())
    invalid: list[tuple[dict[str, object], str]] = []

    raw = returned.projection_as_dict(projection)
    del raw["score_reason"]
    invalid.append((raw, "candidate_score.score_reason"))
    raw = returned.projection_as_dict(projection) | {"unexpected": None}
    invalid.append((raw, "candidate_score"))
    raw = returned.projection_as_dict(projection)
    cast(dict[str, object], raw["candidate"])["model_width"] = True
    invalid.append((raw, "candidate.model_width"))
    raw = returned.projection_as_dict(projection)
    raw["completes_matched_pair"] = 1
    invalid.append((raw, "candidate_score.completes_matched_pair"))
    raw = returned.projection_as_dict(projection)
    raw["matched_experiment_id"] = True
    invalid.append((raw, "candidate_score.matched_experiment_id"))
    raw = returned.projection_as_dict(projection)
    raw["ranking_reason"] = "e\u0301"
    invalid.append((raw, "candidate_score.ranking_reason"))
    raw = returned.projection_as_dict(projection)
    raw["expected_information_gain"] = 0.25
    invalid.append((raw, "candidate_score.expected_information_gain"))

    for payload, path in invalid:
        _failure(
            partial(returned.decode_run_candidate_score_projection, payload),
            category="structural_projection_invalid",
            path=path,
        )


def test_candidate_score_nested_candidate_failure_precedes_outer_science() -> None:
    projection = returned.project_candidate_score(_score())
    malformed = replace(
        projection,
        candidate=replace(
            projection.candidate,
            learning_rate="f64:7ff0000000000000",
        ),
        score_reason="",
    )
    _failure(
        lambda: returned.reconstruct_candidate_score(malformed),
        category="structural_projection_invalid",
        path="candidate.learning_rate",
    )


@pytest.mark.parametrize("mode", ["missing", "mismatch"])
def test_candidate_score_relation_requires_exact_explicit_context(mode: str) -> None:
    domain = _score()
    projection = returned.project_candidate_score(domain)
    if mode == "missing":
        _failure(
            lambda: returned.validate_candidate_score_relation(projection),
            category="missing_relation_context",
            path="candidate_score",
        )
        return
    _failure(
        lambda: returned.validate_candidate_score_relation(
            projection,
            expected_score=replace(domain, score_reason="different reason"),
        ),
        category="scientific_record_invalid",
        path="candidate_score",
    )


@pytest.mark.parametrize("fallback_reason", [None, "no positive information gain"])
def test_decision_trace_round_trips_both_optional_fallback_forms(
    fallback_reason: str | None,
) -> None:
    domain = _trace(fallback_reason=fallback_reason)
    projection = returned.project_decision_trace(domain)
    raw = returned.projection_as_dict(projection)

    assert tuple(field.name for field in fields(type(projection))) == DECISION_TRACE_FIELDS
    assert tuple(raw) == DECISION_TRACE_FIELDS
    assert raw["fallback_reason"] == fallback_reason
    assert returned.decode_run_decision_trace_projection(raw) == projection
    assert returned.reconstruct_decision_trace(projection) == domain
    assert returned.projection_matches_domain(projection, domain)


def test_decision_trace_preserves_hypothesis_and_candidate_ranking_order() -> None:
    projection = returned.project_decision_trace(_trace())
    reordered = replace(
        projection,
        hypotheses=tuple(reversed(projection.hypotheses)),
        ranked_candidates=tuple(reversed(projection.ranked_candidates)),
        selected=projection.ranked_candidates[1],
    )

    rebuilt = returned.reconstruct_decision_trace(reordered)
    assert tuple(item.hypothesis_id for item in rebuilt.hypotheses) == (
        "hypothesis-b",
        "hypothesis-a",
    )
    assert tuple(item.candidate.candidate_id for item in rebuilt.ranked_candidates) == (
        "candidate-b",
        "candidate-a",
    )
    assert rebuilt.selected == rebuilt.ranked_candidates[0]
    assert returned.project_decision_trace(rebuilt) == reordered


@pytest.mark.parametrize("mode", ["empty-ranking", "selected", "policy", "max-cost"])
def test_decision_trace_reconstruction_enforces_existing_domain_science(mode: str) -> None:
    projection = returned.project_decision_trace(_trace())
    if mode == "empty-ranking":
        changed = replace(projection, ranked_candidates=())
    elif mode == "selected":
        changed = replace(projection, selected=projection.ranked_candidates[1])
    elif mode == "policy":
        changed = replace(projection, policy="other-policy")
    else:
        changed = replace(projection, max_cost=f64(-0.125))
    _failure(
        lambda: returned.reconstruct_decision_trace(changed),
        category="scientific_record_invalid",
        path="decision_trace",
    )


def test_decision_trace_preserves_supplied_identities_without_recomputation() -> None:
    projection = returned.project_decision_trace(_trace())
    changed_candidate = replace(projection.selected.candidate, candidate_id="candidate-replayed")
    changed_score = replace(projection.selected, candidate=changed_candidate)
    replayed = replace(
        projection,
        belief_state_id="belief-replayed",
        ranked_candidates=(changed_score, projection.ranked_candidates[1]),
        selected=changed_score,
        suggestion_id="suggestion-replayed",
    )

    rebuilt = returned.reconstruct_decision_trace(replayed)
    assert rebuilt.suggestion_id == "suggestion-replayed"
    assert rebuilt.belief_state_id == "belief-replayed"
    assert rebuilt.selected.candidate.candidate_id == "candidate-replayed"
    assert returned.project_decision_trace(rebuilt) == replayed


def test_decision_trace_decoder_is_closed_strict_nfc_and_noncoercing() -> None:
    projection = returned.project_decision_trace(_trace())
    invalid: list[tuple[dict[str, object], str]] = []

    raw = returned.projection_as_dict(projection)
    del raw["suggestion_id"]
    invalid.append((raw, "decision_trace.suggestion_id"))
    raw = returned.projection_as_dict(projection) | {"unexpected": None}
    invalid.append((raw, "decision_trace"))
    raw = returned.projection_as_dict(projection)
    raw["hypotheses"] = tuple(cast(list[object], raw["hypotheses"]))
    invalid.append((raw, "decision_trace.hypotheses"))
    raw = returned.projection_as_dict(projection)
    raw["ranked_candidates"] = tuple(cast(list[object], raw["ranked_candidates"]))
    invalid.append((raw, "decision_trace.ranked_candidates"))
    raw = returned.projection_as_dict(projection)
    raw["max_cost"] = 4.0
    invalid.append((raw, "decision_trace.max_cost"))
    raw = returned.projection_as_dict(projection)
    raw["policy"] = "e\u0301"
    invalid.append((raw, "decision_trace.policy"))
    raw = returned.projection_as_dict(projection)
    raw["fallback_reason"] = False
    invalid.append((raw, "decision_trace.fallback_reason"))

    for payload, path in invalid:
        _failure(
            partial(returned.decode_run_decision_trace_projection, payload),
            category="structural_projection_invalid",
            path=path,
        )


def test_projection_mapping_rejects_raw_mappings_in_nested_projection_slots() -> None:
    projection = returned.project_decision_trace(_trace())
    raw_hypothesis = returned.projection_as_dict(projection.hypotheses[0])
    raw_selected = returned.projection_as_dict(projection.selected)
    malformed = (
        replace(projection, hypotheses=(cast(Any, raw_hypothesis),)),
        replace(projection, selected=cast(Any, raw_selected)),
    )
    for value in malformed:
        _failure(
            partial(returned.projection_as_dict, value),
            category="structural_projection_invalid",
        )


def test_decision_trace_reconstruction_never_executes_information_gain_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    domain = _trace()
    projection = returned.project_decision_trace(domain)

    def forbidden_decide(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("policy execution is forbidden during pure reconstruction")

    monkeypatch.setattr(InformationGainPolicy, "decide", forbidden_decide)
    assert returned.reconstruct_decision_trace(projection) == domain
    returned.validate_decision_trace_relation(projection, expected_trace=domain)
    _failure(
        lambda: returned.validate_decision_trace_relation(projection),
        category="missing_relation_context",
        path="decision_trace",
    )
    _failure(
        lambda: returned.validate_decision_trace_relation(
            projection, expected_trace=replace(domain, rationale="different rationale")
        ),
        category="scientific_record_invalid",
        path="decision_trace",
    )
