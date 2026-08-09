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
)
from research_decision_engine.evidence_eligibility import PublicExperimentDesign
from research_decision_engine.lookahead import (
    LOOKAHEAD_INFORMATION_GAIN_POLICY,
    LOOKAHEAD_INFORMATION_GAIN_POLICY_VERSION,
    NO_EVIDENCE_BRANCH_ID,
    NO_EVIDENCE_BRANCH_LABEL,
    TIE_BREAKING_ORDER,
    LookaheadAlternative,
    LookaheadBranch,
    LookaheadFirstActionPlan,
    LookaheadInformationGainPolicy,
    LookaheadPlanTrace,
    LookaheadSecondAction,
)
from research_decision_engine.reasoning import Provenance
from research_decision_engine.types import Candidate

SECOND_ACTION_FIELDS = (
    "action_effect",
    "candidate",
    "estimated_cost",
    "expected_information_gain",
    "information_gain_per_cost",
    "reason",
)
BRANCH_FIELDS = (
    "branch_id",
    "branch_total_cost",
    "budget_feasible",
    "evidence_lower_bound",
    "evidence_upper_bound",
    "label",
    "posterior_entropy",
    "posterior_probabilities",
    "probability",
    "second_action",
    "terminal_entropy",
)
FIRST_ACTION_FIELDS = (
    "action_effect",
    "branches",
    "candidate",
    "expected_terminal_entropy",
    "expected_total_cost",
    "expected_total_information_gain",
    "first_action_cost",
    "immediate_information_gain",
    "information_gain_per_expected_cost",
    "prior_entropy",
    "public_design",
    "ranking_reason",
)
ALTERNATIVE_FIELDS = (
    "action_effect",
    "candidate",
    "comparison_group_id",
    "expected_total_cost",
    "expected_total_information_gain",
    "immediate_information_gain",
    "information_gain_per_expected_cost",
    "ranking_reason",
)
TRACE_FIELDS = (
    "alternatives",
    "belief_state_id",
    "candidate_set_fingerprint",
    "completed_state_fingerprint",
    "created_at",
    "current_hypothesis_probabilities",
    "fallback_reason",
    "max_cost",
    "plan_id",
    "policy",
    "policy_version",
    "provenance",
    "rationale",
    "selected",
    "tie_breaking_order",
)
PUBLIC_NONSTOP_EFFECTS = ("opens_pair", "completes_pair", "ineligible")
INTERNAL_EFFECTS = (
    "completed_candidate",
    "duplicate_arm",
    "already_completed_pair",
    "ambiguous_counterpart",
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


def _design(
    candidate_id: str = "candidate-a", *, optimizer: str = "adam"
) -> PublicExperimentDesign:
    return PublicExperimentDesign(
        candidate_id=candidate_id,
        experiment_family="optimizer-comparison",
        comparison_group_id="group-1",
        controlled_variables=(("learning_rate", 0.125), ("model_width", 64)),
        intervention_variable="optimizer",
        intervention_arm=optimizer,
    )


def _second(action_effect: str = "completes_pair") -> LookaheadSecondAction:
    stop = action_effect == "stop"
    return LookaheadSecondAction(
        candidate=None if stop else _candidate("candidate-b", optimizer="sgd"),
        action_effect=cast(Any, action_effect),
        expected_information_gain=0.0 if stop else 0.25,
        estimated_cost=0.0 if stop else 1.0,
        information_gain_per_cost=0.0 if stop else 0.25,
        reason="STOP preserves budget" if stop else "public second action",
    )


def _branch(mode: str = "no-evidence", *, probability: float = 1.0) -> LookaheadBranch:
    if mode == "no-evidence":
        branch_id, label = NO_EVIDENCE_BRANCH_ID, NO_EVIDENCE_BRANCH_LABEL
        lower, upper = None, None
        second = _second()
    elif mode == "lower-tail":
        branch_id, label = "evidence-bin-000", "LOW_TAIL"
        lower, upper = None, -0.5
        second = _second("stop")
    elif mode == "middle":
        branch_id, label = "evidence-bin-001", "MIDDLE"
        lower, upper = -0.5, 0.5
        second = _second("stop")
    else:
        branch_id, label = "evidence-bin-002", "HIGH_TAIL"
        lower, upper = 0.5, None
        second = _second("stop")
    return LookaheadBranch(
        branch_id=branch_id,
        label=label,
        probability=probability,
        evidence_lower_bound=lower,
        evidence_upper_bound=upper,
        posterior_probabilities=(("hypothesis-a", 0.625), ("hypothesis-b", 0.375)),
        posterior_entropy=0.75,
        second_action=second,
        terminal_entropy=0.5,
        branch_total_cost=2.0,
        budget_feasible=True,
    )


def _first(action_effect: str = "opens_pair") -> LookaheadFirstActionPlan:
    return LookaheadFirstActionPlan(
        candidate=_candidate(),
        public_design=_design(),
        action_effect=cast(Any, action_effect),
        first_action_cost=1.0,
        prior_entropy=1.0,
        immediate_information_gain=0.125,
        expected_terminal_entropy=0.5,
        expected_total_information_gain=0.5,
        expected_total_cost=2.0,
        information_gain_per_expected_cost=0.25,
        branches=(_branch(),),
        ranking_reason="selected by approved ordering",
    )


def _alternative(
    candidate_id: str = "candidate-b", *, action_effect: str = "completes_pair"
) -> LookaheadAlternative:
    return LookaheadAlternative(
        candidate=_candidate(candidate_id, optimizer="sgd"),
        action_effect=cast(Any, action_effect),
        comparison_group_id="group-1",
        immediate_information_gain=0.25,
        expected_total_information_gain=0.375,
        expected_total_cost=2.25,
        information_gain_per_expected_cost=1.0 / 6.0,
        ranking_reason=f"{candidate_id} lost deterministically",
    )


def _trace(*, fallback_reason: str | None = None) -> LookaheadPlanTrace:
    return LookaheadPlanTrace(
        plan_id="plan-preserved",
        policy=LOOKAHEAD_INFORMATION_GAIN_POLICY,
        policy_version=LOOKAHEAD_INFORMATION_GAIN_POLICY_VERSION,
        created_at="2026-01-01T00:00:00+00:00",
        belief_state_id="belief-1",
        current_hypothesis_probabilities=(
            ("hypothesis-a", 0.625),
            ("hypothesis-b", 0.375),
        ),
        completed_state_fingerprint="completed-fingerprint-preserved",
        candidate_set_fingerprint="candidate-fingerprint-preserved",
        max_cost=4.0,
        selected=_first(),
        alternatives=(
            _alternative("candidate-b"),
            _alternative("candidate-c", action_effect="ineligible"),
        ),
        tie_breaking_order=TIE_BREAKING_ORDER,
        fallback_reason=fallback_reason,
        rationale="candidate-a wins the recorded two-step ranking",
        provenance=Provenance(
            method="two-step-lookahead",
            version="provenance/v1",
            details=(("belief_state_id", "belief-1"),),
        ),
    )


def _decision_trace() -> DecisionTrace:
    candidate = _candidate()
    score = CandidateScore(
        candidate=candidate,
        expected_information_gain=0.25,
        prior_entropy=0.75,
        expected_posterior_entropy=0.5,
        estimated_cost=1.0,
        completes_matched_pair=False,
        matched_experiment_id=None,
        score_reason="recorded score",
        ranking_reason="selected",
    )
    hypothesis = HypothesisDecisionContext(
        hypothesis_id="hypothesis-a",
        statement="statement",
        posterior_probability=1.0,
        most_favorable_outcome=0.25,
        most_favorable_outcome_label="positive",
        posterior_if_observed=1.0,
    )
    return DecisionTrace(
        suggestion_id="suggestion-1",
        policy=INFORMATION_GAIN_POLICY,
        policy_version="information-gain/v1",
        created_at="2026-01-01T00:00:00+00:00",
        belief_state_id="belief-1",
        selected=score,
        hypotheses=(hypothesis,),
        max_cost=4.0,
        fallback_reason=None,
        rationale="selected recorded candidate",
        ranked_candidates=(score,),
        provenance=Provenance("decision", "provenance/v1", ()),
    )


@pytest.mark.parametrize("action_effect", [*PUBLIC_NONSTOP_EFFECTS, "stop"])
def test_second_action_round_trips_all_four_public_effect_tags(action_effect: str) -> None:
    domain = _second(action_effect)
    projection = returned.project_lookahead_second_action(domain)
    raw = returned.projection_as_dict(projection)

    assert tuple(field.name for field in fields(type(projection))) == SECOND_ACTION_FIELDS
    assert tuple(raw) == SECOND_ACTION_FIELDS
    assert raw["action_effect"] == action_effect
    assert (raw["candidate"] is None) is (action_effect == "stop")
    assert returned.decode_run_lookahead_second_action_projection(raw) == projection
    assert returned.reconstruct_lookahead_second_action(projection) == domain
    assert returned.projection_matches_domain(projection, domain)


@pytest.mark.parametrize("mode", ["stop-with-candidate", "action-without-candidate"])
def test_second_action_reconstruction_enforces_stop_candidate_coupling(mode: str) -> None:
    projection = returned.project_lookahead_second_action(_second("stop"))
    changed = (
        replace(
            projection,
            candidate=returned.project_candidate(_candidate("candidate-b")),
        )
        if mode == "stop-with-candidate"
        else replace(projection, action_effect="opens_pair")
    )
    _failure(
        partial(returned.reconstruct_lookahead_second_action, changed),
        category="scientific_record_invalid",
        path="lookahead_second_action",
    )


def test_second_action_rejects_every_internal_eligibility_effect() -> None:
    projection = returned.project_lookahead_second_action(_second())
    for action_effect in INTERNAL_EFFECTS:
        raw = returned.projection_as_dict(projection)
        raw["action_effect"] = action_effect
        _failure(
            partial(returned.decode_run_lookahead_second_action_projection, raw),
            category="structural_projection_invalid",
            path="lookahead_second_action.action_effect",
        )


def test_second_action_decoder_is_closed_strict_and_never_uses_from_dict() -> None:
    domain = _second()
    projection = returned.project_lookahead_second_action(domain)
    invalid: list[object] = []
    raw = returned.projection_as_dict(projection)
    del raw["reason"]
    invalid.append(raw)
    invalid.append(returned.projection_as_dict(projection) | {"extra": None})
    raw = returned.projection_as_dict(projection)
    raw["estimated_cost"] = 1.0
    invalid.append(raw)
    raw = returned.projection_as_dict(projection)
    raw["reason"] = "e\u0301"
    invalid.append(raw)
    raw = returned.projection_as_dict(projection)
    cast(dict[str, object], raw["candidate"])["model_width"] = True
    invalid.append(raw)
    invalid.append(domain.to_dict())
    for payload in invalid:
        _failure(
            partial(returned.decode_run_lookahead_second_action_projection, payload),
            category="structural_projection_invalid",
        )


@pytest.mark.parametrize("mode", ["no-evidence", "lower-tail", "middle"])
def test_branch_round_trips_no_evidence_and_evidence_bound_forms(mode: str) -> None:
    domain = _branch(mode)
    projection = returned.project_lookahead_branch(domain)
    raw = returned.projection_as_dict(projection)

    assert tuple(field.name for field in fields(type(projection))) == BRANCH_FIELDS
    assert tuple(raw) == BRANCH_FIELDS
    assert raw["posterior_probabilities"] == [
        ["hypothesis-a", f64(0.625)],
        ["hypothesis-b", f64(0.375)],
    ]
    assert returned.decode_run_lookahead_branch_projection(raw) == projection
    assert returned.reconstruct_lookahead_branch(projection) == domain
    assert returned.projection_matches_domain(projection, domain)


@pytest.mark.parametrize(
    "mode",
    [
        "no-evidence-wrong-label",
        "label-with-wrong-id",
        "no-evidence-with-bound",
        "evidence-without-bounds",
        "evidence-with-no-evidence-label",
    ],
)
def test_branch_enforces_exact_no_evidence_marker_and_bounds_coupling(mode: str) -> None:
    projection = returned.project_lookahead_branch(_branch())
    if mode == "no-evidence-wrong-label":
        changed = replace(projection, label="OTHER")
    elif mode == "label-with-wrong-id":
        changed = replace(projection, branch_id="evidence-bin-000")
    elif mode == "no-evidence-with-bound":
        changed = replace(projection, evidence_upper_bound=f64(0.5))
    elif mode == "evidence-without-bounds":
        changed = replace(projection, branch_id="evidence-bin-000", label="LOW")
    else:
        changed = replace(
            projection,
            branch_id="evidence-bin-000",
            evidence_upper_bound=f64(0.5),
        )
    _failure(
        partial(returned.reconstruct_lookahead_branch, changed),
        category="scientific_record_invalid",
        path="lookahead_branch",
    )


@pytest.mark.parametrize("mode", ["reordered", "duplicate", "wrong-total", "negative"])
def test_branch_constructor_science_enforces_ordered_probability_pairs(mode: str) -> None:
    projection = returned.project_lookahead_branch(_branch())
    probabilities = projection.posterior_probabilities
    if mode == "reordered":
        changed = tuple(reversed(probabilities))
    elif mode == "duplicate":
        changed = (probabilities[0], probabilities[0])
    elif mode == "wrong-total":
        changed = (
            (probabilities[0][0], f64(0.5)),
            (probabilities[1][0], f64(0.25)),
        )
    else:
        changed = (
            (probabilities[0][0], f64(-0.125)),
            (probabilities[1][0], f64(1.125)),
        )
    _failure(
        partial(
            returned.reconstruct_lookahead_branch,
            replace(projection, posterior_probabilities=changed),
        ),
        category="scientific_record_invalid",
        path="lookahead_branch",
    )


@pytest.mark.parametrize("field", ["probability", "posterior_entropy", "branch_total_cost"])
def test_branch_constructor_science_enforces_probability_and_nonnegative_values(
    field: str,
) -> None:
    projection = returned.project_lookahead_branch(_branch())
    value = f64(1.125) if field == "probability" else f64(-0.125)
    _failure(
        partial(
            returned.reconstruct_lookahead_branch,
            replace(projection, **cast(Any, {field: value})),
        ),
        category="scientific_record_invalid",
        path="lookahead_branch",
    )


def test_branch_decoder_is_closed_strict_and_never_uses_from_dict() -> None:
    domain = _branch()
    projection = returned.project_lookahead_branch(domain)
    invalid: list[object] = []
    raw = returned.projection_as_dict(projection)
    del raw["terminal_entropy"]
    invalid.append(raw)
    invalid.append(returned.projection_as_dict(projection) | {"extra": None})
    raw = returned.projection_as_dict(projection)
    raw["budget_feasible"] = 1
    invalid.append(raw)
    raw = returned.projection_as_dict(projection)
    raw["evidence_lower_bound"] = 0.0
    invalid.append(raw)
    raw = returned.projection_as_dict(projection)
    raw["posterior_probabilities"] = tuple(cast(list[object], raw["posterior_probabilities"]))
    invalid.append(raw)
    raw = returned.projection_as_dict(projection)
    pairs = cast(list[object], raw["posterior_probabilities"])
    pairs[0] = tuple(cast(list[object], pairs[0]))
    invalid.append(raw)
    invalid.append(domain.to_dict())
    for payload in invalid:
        _failure(
            partial(returned.decode_run_lookahead_branch_projection, payload),
            category="structural_projection_invalid",
        )


def test_branch_nested_second_action_failure_precedes_outer_science() -> None:
    projection = returned.project_lookahead_branch(_branch())
    second = replace(
        projection.second_action,
        candidate=replace(
            cast(returned.RunCandidateProjection, projection.second_action.candidate),
            model_width=True,
        ),
    )
    malformed = replace(projection, posterior_entropy=f64(-0.125), second_action=second)
    _failure(
        partial(returned.reconstruct_lookahead_branch, malformed),
        category="structural_projection_invalid",
        path="candidate.model_width",
    )


@pytest.mark.parametrize("action_effect", PUBLIC_NONSTOP_EFFECTS)
def test_first_action_round_trips_each_nonstop_public_effect(action_effect: str) -> None:
    domain = _first(action_effect)
    projection = returned.project_lookahead_first_action(domain)
    raw = returned.projection_as_dict(projection)

    assert tuple(field.name for field in fields(type(projection))) == FIRST_ACTION_FIELDS
    assert tuple(raw) == FIRST_ACTION_FIELDS
    assert returned.decode_run_lookahead_first_action_projection(raw) == projection
    assert returned.reconstruct_lookahead_first_action(projection) == domain
    assert returned.projection_matches_domain(projection, domain)


def test_first_action_preserves_recorded_branch_order_without_sorting() -> None:
    first = _branch("lower-tail", probability=0.375)
    second = _branch("upper-tail", probability=0.625)
    domain = replace(_first("completes_pair"), branches=(first, second))
    projection = returned.project_lookahead_first_action(domain)
    reordered = replace(projection, branches=tuple(reversed(projection.branches)))

    rebuilt = returned.reconstruct_lookahead_first_action(reordered)
    assert tuple(item.branch_id for item in rebuilt.branches) == (
        "evidence-bin-002",
        "evidence-bin-000",
    )
    assert returned.project_lookahead_first_action(rebuilt) == reordered


@pytest.mark.parametrize("mode", ["design", "empty-branches", "branch-total", "negative"])
def test_first_action_reconstruction_enforces_existing_constructor_science(mode: str) -> None:
    projection = returned.project_lookahead_first_action(_first())
    if mode == "design":
        changed = replace(
            projection,
            public_design=replace(projection.public_design, candidate_id="candidate-other"),
        )
    elif mode == "empty-branches":
        changed = replace(projection, branches=())
    elif mode == "branch-total":
        changed = replace(
            projection,
            branches=(replace(projection.branches[0], probability=f64(0.5)),),
        )
    else:
        changed = replace(projection, first_action_cost=f64(-0.125))
    _failure(
        partial(returned.reconstruct_lookahead_first_action, changed),
        category="scientific_record_invalid",
        path="lookahead_first_action",
    )


def test_first_action_decoder_is_closed_strict_and_never_uses_from_dict() -> None:
    domain = _first()
    projection = returned.project_lookahead_first_action(domain)
    invalid: list[object] = []
    raw = returned.projection_as_dict(projection)
    del raw["ranking_reason"]
    invalid.append(raw)
    invalid.append(returned.projection_as_dict(projection) | {"extra": None})
    raw = returned.projection_as_dict(projection)
    raw["branches"] = tuple(cast(list[object], raw["branches"]))
    invalid.append(raw)
    raw = returned.projection_as_dict(projection)
    cast(dict[str, object], raw["candidate"])["model_width"] = True
    invalid.append(raw)
    raw = returned.projection_as_dict(projection)
    raw["first_action_cost"] = 1.0
    invalid.append(raw)
    raw = returned.projection_as_dict(projection)
    raw["action_effect"] = "stop"
    invalid.append(raw)
    invalid.append(domain.to_dict())
    for payload in invalid:
        _failure(
            partial(returned.decode_run_lookahead_first_action_projection, payload),
            category="structural_projection_invalid",
        )


@pytest.mark.parametrize("action_effect", PUBLIC_NONSTOP_EFFECTS)
def test_alternative_round_trips_each_nonstop_public_effect(action_effect: str) -> None:
    domain = _alternative(action_effect=action_effect)
    projection = returned.project_lookahead_alternative(domain)
    raw = returned.projection_as_dict(projection)

    assert tuple(field.name for field in fields(type(projection))) == ALTERNATIVE_FIELDS
    assert tuple(raw) == ALTERNATIVE_FIELDS
    assert returned.decode_run_lookahead_alternative_projection(raw) == projection
    assert returned.reconstruct_lookahead_alternative(projection) == domain
    assert returned.projection_matches_domain(projection, domain)


def test_alternative_decoder_rejects_internal_tags_and_from_dict_coercion() -> None:
    domain = _alternative()
    projection = returned.project_lookahead_alternative(domain)
    invalid: list[object] = [domain.to_dict()]
    for action_effect in (*INTERNAL_EFFECTS, "stop"):
        raw = returned.projection_as_dict(projection)
        raw["action_effect"] = action_effect
        invalid.append(raw)
    invalid.append(returned.projection_as_dict(projection) | {"extra": None})
    raw = returned.projection_as_dict(projection)
    raw["ranking_reason"] = "e\u0301"
    invalid.append(raw)
    for payload in invalid:
        _failure(
            partial(returned.decode_run_lookahead_alternative_projection, payload),
            category="structural_projection_invalid",
        )


@pytest.mark.parametrize("fallback_reason", [None, "no positive two-step information gain"])
def test_lookahead_trace_round_trips_both_optional_fallback_forms(
    fallback_reason: str | None,
) -> None:
    domain = _trace(fallback_reason=fallback_reason)
    projection = returned.project_lookahead_trace(domain)
    raw = returned.projection_as_dict(projection)

    assert tuple(field.name for field in fields(type(projection))) == TRACE_FIELDS
    assert tuple(raw) == TRACE_FIELDS
    assert raw["fallback_reason"] == fallback_reason
    assert raw["tie_breaking_order"] == list(TIE_BREAKING_ORDER)
    assert returned.decode_run_lookahead_trace_projection(raw) == projection
    assert returned.reconstruct_lookahead_trace(projection) == domain
    assert returned.projection_matches_domain(projection, domain)


def test_trace_preserves_alternative_order_ids_and_fingerprints_without_recomputation() -> None:
    projection = returned.project_lookahead_trace(_trace())
    replayed = replace(
        projection,
        alternatives=tuple(reversed(projection.alternatives)),
        candidate_set_fingerprint="candidate-fingerprint-replayed",
        completed_state_fingerprint="completed-fingerprint-replayed",
        plan_id="plan-replayed",
    )

    rebuilt = returned.reconstruct_lookahead_trace(replayed)
    assert tuple(item.candidate.candidate_id for item in rebuilt.alternatives) == (
        "candidate-c",
        "candidate-b",
    )
    assert rebuilt.plan_id == "plan-replayed"
    assert rebuilt.candidate_set_fingerprint == "candidate-fingerprint-replayed"
    assert rebuilt.completed_state_fingerprint == "completed-fingerprint-replayed"
    assert returned.project_lookahead_trace(rebuilt) == replayed


@pytest.mark.parametrize("mode", ["policy", "tie-order", "infeasible", "probabilities"])
def test_trace_reconstruction_enforces_existing_constructor_science(mode: str) -> None:
    projection = returned.project_lookahead_trace(_trace())
    if mode == "policy":
        changed = replace(projection, policy="other-policy")
    elif mode == "tie-order":
        changed = replace(projection, tie_breaking_order=tuple(reversed(TIE_BREAKING_ORDER)))
    elif mode == "infeasible":
        selected = replace(
            projection.selected,
            branches=(replace(projection.selected.branches[0], budget_feasible=False),),
        )
        changed = replace(projection, selected=selected)
    else:
        changed = replace(
            projection,
            current_hypothesis_probabilities=(
                ("hypothesis-a", f64(0.5)),
                ("hypothesis-b", f64(0.25)),
            ),
        )
    _failure(
        partial(returned.reconstruct_lookahead_trace, changed),
        category="scientific_record_invalid",
        path="lookahead_trace",
    )


def test_trace_decoder_is_closed_strict_and_never_uses_from_dict() -> None:
    domain = _trace()
    projection = returned.project_lookahead_trace(domain)
    invalid: list[object] = []
    raw = returned.projection_as_dict(projection)
    del raw["plan_id"]
    invalid.append(raw)
    invalid.append(returned.projection_as_dict(projection) | {"extra": None})
    raw = returned.projection_as_dict(projection)
    raw["alternatives"] = tuple(cast(list[object], raw["alternatives"]))
    invalid.append(raw)
    raw = returned.projection_as_dict(projection)
    raw["tie_breaking_order"] = tuple(cast(list[object], raw["tie_breaking_order"]))
    invalid.append(raw)
    raw = returned.projection_as_dict(projection)
    raw["max_cost"] = 4.0
    invalid.append(raw)
    raw = returned.projection_as_dict(projection)
    raw["rationale"] = "e\u0301"
    invalid.append(raw)
    invalid.append(domain.to_dict())
    for payload in invalid:
        _failure(
            partial(returned.decode_run_lookahead_trace_projection, payload),
            category="structural_projection_invalid",
        )


def test_trace_nested_selected_failure_precedes_outer_policy_science() -> None:
    projection = returned.project_lookahead_trace(_trace())
    branch = projection.selected.branches[0]
    second = replace(
        branch.second_action,
        candidate=replace(
            cast(returned.RunCandidateProjection, branch.second_action.candidate),
            model_width=True,
        ),
    )
    selected = replace(
        projection.selected,
        branches=(replace(branch, second_action=second),),
    )
    malformed = replace(projection, policy="other-policy", selected=selected)
    _failure(
        partial(returned.reconstruct_lookahead_trace, malformed),
        category="structural_projection_invalid",
        path="candidate.model_width",
    )


@pytest.mark.parametrize("mode", ["missing", "mismatch"])
def test_trace_relation_requires_exact_explicit_context(mode: str) -> None:
    domain = _trace()
    projection = returned.project_lookahead_trace(domain)
    if mode == "missing":
        _failure(
            partial(returned.validate_lookahead_trace_relation, projection),
            category="missing_relation_context",
            path="lookahead_trace",
        )
        return
    _failure(
        lambda: returned.validate_lookahead_trace_relation(
            projection,
            expected_trace=replace(domain, rationale="different rationale"),
        ),
        category="scientific_record_invalid",
        path="lookahead_trace",
    )


@pytest.mark.parametrize("kind", ["decision_trace", "lookahead_plan_trace"])
def test_policy_trace_is_an_exact_two_branch_tagged_union(kind: str) -> None:
    domain: DecisionTrace | LookaheadPlanTrace = (
        _decision_trace() if kind == "decision_trace" else _trace()
    )
    projection = returned.project_policy_trace(domain)
    raw = returned.projection_as_dict(projection)

    assert tuple(field.name for field in fields(type(projection))) == ("kind", "projection")
    assert tuple(raw) == ("kind", "projection")
    assert raw["kind"] == kind
    assert returned.decode_run_policy_trace_projection(raw) == projection
    assert returned.reconstruct_policy_trace(projection) == domain


@pytest.mark.parametrize("mode", ["dataclass-conflict", "mapping-conflict", "unknown-tag"])
def test_policy_trace_rejects_omitted_unknown_and_conflicting_union_branches(mode: str) -> None:
    lookahead = returned.project_lookahead_trace(_trace())
    if mode == "dataclass-conflict":
        malformed = returned.RunPolicyTraceProjection("decision_trace", lookahead)
        _failure(
            partial(returned.projection_as_dict, malformed),
            category="structural_projection_invalid",
            path="policy_trace.projection",
        )
        return
    raw = {
        "kind": "decision_trace" if mode == "mapping-conflict" else "unknown",
        "projection": returned.projection_as_dict(lookahead),
    }
    _failure(
        partial(returned.decode_run_policy_trace_projection, raw),
        category="structural_projection_invalid",
        path="policy_trace.kind" if mode == "unknown-tag" else None,
    )


@pytest.mark.parametrize("mode", ["missing", "mismatch"])
def test_policy_trace_relation_requires_exact_explicit_context(mode: str) -> None:
    domain = _trace()
    projection = returned.project_policy_trace(domain)
    if mode == "missing":
        _failure(
            partial(returned.validate_policy_trace_relation, projection),
            category="missing_relation_context",
            path="policy_trace",
        )
        return
    _failure(
        lambda: returned.validate_policy_trace_relation(
            projection,
            expected_trace=_decision_trace(),
        ),
        category="scientific_record_invalid",
        path="policy_trace",
    )


def test_lookahead_reconstruction_never_executes_planning_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    domain = _trace()
    projection = returned.project_lookahead_trace(domain)

    def forbidden_decide(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("planning execution is forbidden during pure reconstruction")

    monkeypatch.setattr(LookaheadInformationGainPolicy, "decide", forbidden_decide)
    assert returned.reconstruct_lookahead_trace(projection) == domain
    returned.validate_lookahead_trace_relation(projection, expected_trace=domain)
