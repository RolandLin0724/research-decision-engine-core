from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields, replace
from functools import partial
from typing import Any, cast

import pytest

from research_decision_engine.benchmarks import broader_returned_run as returned
from research_decision_engine.benchmarks.broader_oracle import RevealedObservation
from research_decision_engine.benchmarks.broader_protocol import (
    canonical_json_bytes,
    f64,
    protocol_hash,
    runtime_id,
)
from research_decision_engine.benchmarks.broader_runner import ArmAction, ArmDecision
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
    LookaheadBranch,
    LookaheadFirstActionPlan,
    LookaheadPlanTrace,
    LookaheadSecondAction,
)
from research_decision_engine.reasoning import Provenance
from research_decision_engine.types import Candidate

RUN_ID = "run-arm-test"
DECISION_ID = f"decision/{RUN_ID}/0001"
DECISION_FIELDS = (
    "affordable_candidate_ids",
    "belief_state_id",
    "decision_id",
    "fixed_policy_regression_match",
    "policy_trace",
    "public_feasible_candidate_ids",
    "remaining_budget",
    "selected_candidate_id",
    "step",
)
ACTION_FIELDS = (
    "candidate_id",
    "cost",
    "cumulative_decision_cost",
    "decision_id",
    "new_evidence_ids",
    "observed_objective",
    "oracle_observation",
    "posterior_probabilities",
    "role",
    "step",
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
    return Candidate(candidate_id, 0.125, 0.0625, 64, optimizer)


def _provenance(method: str) -> Provenance:
    return Provenance(method, "provenance/v1", (("belief_state_id", "belief-1"),))


def _decision_trace() -> DecisionTrace:
    score = CandidateScore(
        _candidate(), 0.25, 0.75, 0.5, 1.0, False, None, "recorded score", "selected"
    )
    hypothesis = HypothesisDecisionContext("hypothesis-a", "statement", 1.0, 0.25, "positive", 1.0)
    return DecisionTrace(
        "suggestion-1",
        INFORMATION_GAIN_POLICY,
        "information-gain/v1",
        "2026-01-01T00:00:00+00:00",
        "belief-1",
        score,
        (hypothesis,),
        4.0,
        None,
        "selected candidate-a",
        (score,),
        _provenance("decision"),
    )


def _lookahead_trace() -> LookaheadPlanTrace:
    candidate = _candidate()
    design = PublicExperimentDesign(
        "candidate-a",
        "optimizer-comparison",
        "group-1",
        (("learning_rate", 0.125), ("model_width", 64)),
        "optimizer",
        "adam",
    )
    second = LookaheadSecondAction(None, "stop", 0.0, 0.0, 0.0, "STOP preserves budget")
    branch = LookaheadBranch(
        NO_EVIDENCE_BRANCH_ID,
        NO_EVIDENCE_BRANCH_LABEL,
        1.0,
        None,
        None,
        (("hypothesis-a", 1.0),),
        0.0,
        second,
        0.0,
        1.0,
        True,
    )
    selected = LookaheadFirstActionPlan(
        candidate, design, "opens_pair", 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, (branch,), "selected"
    )
    return LookaheadPlanTrace(
        "plan-1",
        LOOKAHEAD_INFORMATION_GAIN_POLICY,
        LOOKAHEAD_INFORMATION_GAIN_POLICY_VERSION,
        "2026-01-01T00:00:00+00:00",
        "belief-1",
        (("hypothesis-a", 1.0),),
        "completed-fingerprint",
        "candidate-fingerprint",
        4.0,
        selected,
        (),
        TIE_BREAKING_ORDER,
        None,
        "selected candidate-a",
        _provenance("lookahead"),
    )


def _decision(*, lookahead: bool = False) -> ArmDecision:
    return ArmDecision(
        decision_id=DECISION_ID,
        step=1,
        selected_candidate_id="candidate-a",
        remaining_budget=4.0,
        belief_state_id="belief-1",
        public_feasible_candidate_ids=("candidate-b", "candidate-a", "candidate-c"),
        affordable_candidate_ids=("candidate-a", "candidate-c"),
        policy_trace=_lookahead_trace() if lookahead else _decision_trace(),
        fixed_policy_regression_match=True,
    )


def _revealed_observation() -> RevealedObservation:
    candidate_id = "candidate-a"
    authorization_id = runtime_id(
        "authorization",
        "authorization_id/v1",
        {
            "candidate_id": candidate_id,
            "kind": "decision",
            "run_id": RUN_ID,
            "source_id": DECISION_ID,
        },
    )
    namespace = "rde.broader.decision-outcome/v1"
    world_id, seed, replication_id = "world-1", 7, "replication-0001"
    key_fields = (
        namespace,
        "broader-replication/v3",
        "broader-selected-only-oracle/v1",
        world_id,
        str(seed),
        candidate_id,
        replication_id,
    )
    oracle_key_id = runtime_id("oracle-key", "oracle_key_id/v1", {"key_fields": list(key_fields)})
    outcome_digest = protocol_hash(
        "revealed_outcome/v1",
        {"oracle_key_id": oracle_key_id, "revealed_observation": f64(0.25)},
    )
    return RevealedObservation(
        oracle_key_id,
        f"oracle-use/{authorization_id}/{oracle_key_id}",
        authorization_id,
        namespace,
        world_id,
        seed,
        candidate_id,
        None,
        None,
        replication_id,
        key_fields,
        canonical_json_bytes(list(key_fields)).hex(),
        "a" * 64,
        "0.50000000000000000000000000000000000000000000000000000",
        "-0.250000000000000000000000000000",
        0.25,
        outcome_digest,
    )


def _action(*, observed: bool = False) -> ArmAction:
    return ArmAction(
        step=1,
        candidate_id="candidate-a",
        role="evidence" if observed else "setup",
        cost=1.0,
        cumulative_decision_cost=1.0,
        decision_id=DECISION_ID,
        observed_objective=0.25 if observed else None,
        oracle_observation=_revealed_observation() if observed else None,
        new_evidence_ids=("evidence-1", "evidence-2") if observed else (),
        posterior_probabilities=(("hypothesis-a", 0.625), ("hypothesis-b", 0.375)),
    )


@pytest.mark.parametrize("lookahead", [False, True], ids=["decision", "lookahead"])
def test_arm_decision_round_trips_both_policy_union_branches(lookahead: bool) -> None:
    domain = _decision(lookahead=lookahead)
    projection = returned.project_arm_decision(domain)
    raw = returned.projection_as_dict(projection)

    assert tuple(field.name for field in fields(type(projection))) == DECISION_FIELDS
    assert tuple(raw) == DECISION_FIELDS
    assert cast(dict[str, object], raw["policy_trace"])["kind"] == (
        "lookahead_plan_trace" if lookahead else "decision_trace"
    )
    assert returned.decode_run_arm_decision_projection(raw) == projection
    assert returned.reconstruct_arm_decision(projection) == domain
    assert returned.projection_matches_domain(projection, domain)


def test_arm_decision_preserves_feasible_and_affordable_producer_order() -> None:
    domain = replace(
        _decision(),
        public_feasible_candidate_ids=("candidate-c", "candidate-a", "candidate-b"),
        affordable_candidate_ids=("candidate-a", "candidate-b"),
    )
    projection = returned.project_arm_decision(domain)
    rebuilt = returned.reconstruct_arm_decision(projection)
    assert rebuilt.public_feasible_candidate_ids == domain.public_feasible_candidate_ids
    assert rebuilt.affordable_candidate_ids == domain.affordable_candidate_ids


@pytest.mark.parametrize("mode", ["duplicates", "nonmember", "reordered", "selected", "scalar"])
def test_arm_decision_rejects_invalid_membership_order_and_scalars(mode: str) -> None:
    projection = returned.project_arm_decision(_decision())
    invalid: tuple[returned.RunArmDecisionProjection, ...]
    if mode == "duplicates":
        invalid = (
            replace(projection, public_feasible_candidate_ids=("candidate-a", "candidate-a")),
            replace(projection, affordable_candidate_ids=("candidate-a", "candidate-a")),
        )
    elif mode == "nonmember":
        invalid = (replace(projection, affordable_candidate_ids=("candidate-other",)),)
    elif mode == "reordered":
        invalid = (replace(projection, affordable_candidate_ids=("candidate-c", "candidate-a")),)
    elif mode == "selected":
        invalid = (replace(projection, selected_candidate_id="candidate-b"),)
    else:
        invalid = (
            replace(projection, step=0),
            replace(projection, remaining_budget=f64(-0.125)),
        )
    for value in invalid:
        _failure(
            partial(returned.reconstruct_arm_decision, value),
            category="scientific_record_invalid",
        )


def test_arm_decision_decoder_is_closed_strict_noncoercing_and_side_effect_free() -> None:
    projection = returned.project_arm_decision(_decision())
    invalid: list[object] = []
    raw = returned.projection_as_dict(projection)
    del raw["decision_id"]
    invalid.append(raw)
    invalid.append(returned.projection_as_dict(projection) | {"extra": None})
    raw = returned.projection_as_dict(projection)
    raw["step"] = True
    invalid.append(raw)
    raw = returned.projection_as_dict(projection)
    raw["fixed_policy_regression_match"] = 1
    invalid.append(raw)
    raw = returned.projection_as_dict(projection)
    raw["remaining_budget"] = 4.0
    invalid.append(raw)
    raw = returned.projection_as_dict(projection)
    raw["affordable_candidate_ids"] = tuple(cast(list[object], raw["affordable_candidate_ids"]))
    invalid.append(raw)
    invalid.append(cast(Any, _decision().policy_trace).to_dict())
    for payload in invalid:
        _failure(
            partial(returned.decode_run_arm_decision_projection, payload),
            category="structural_projection_invalid",
        )
    for name in ("issue", "execute", "persist", "write_evidence"):
        assert not hasattr(projection, name)


def test_arm_decision_relation_accepts_exact_run_decision_and_action() -> None:
    decision, action = _decision(), _action()
    returned.validate_arm_decision_relation(
        returned.project_arm_decision(decision),
        expected_decision=decision,
        expected_action=action,
        expected_run_id=RUN_ID,
    )


@pytest.mark.parametrize("mode", ["run", "step", "candidate"])
def test_arm_decision_relation_rejects_cross_context_substitution(mode: str) -> None:
    decision, action = _decision(), _action()
    run_id = "run-other" if mode == "run" else RUN_ID
    if mode == "step":
        action = replace(action, step=2)
    elif mode == "candidate":
        action = replace(action, candidate_id="candidate-other")
    _failure(
        lambda: returned.validate_arm_decision_relation(
            returned.project_arm_decision(decision),
            expected_decision=decision,
            expected_action=action,
            expected_run_id=run_id,
        ),
        category="scientific_record_invalid",
    )


def test_arm_decision_relation_reports_each_missing_context_without_side_effects() -> None:
    decision, action = _decision(), _action()
    projection = returned.project_arm_decision(decision)
    operations = (
        partial(returned.validate_arm_decision_relation, projection),
        partial(returned.validate_arm_decision_relation, projection, expected_decision=decision),
        partial(
            returned.validate_arm_decision_relation,
            projection,
            expected_decision=decision,
            expected_action=action,
        ),
    )
    for operation in operations:
        _failure(operation, category="missing_relation_context")


def test_setup_action_round_trips_exact_null_and_empty_forms() -> None:
    domain = _action()
    projection = returned.project_arm_action(domain, expected_run_id=RUN_ID)
    raw = returned.projection_as_dict(projection)
    assert tuple(field.name for field in fields(type(projection))) == ACTION_FIELDS
    assert tuple(raw) == ACTION_FIELDS
    assert raw["observed_objective"] is None
    assert raw["oracle_observation"] is None
    assert raw["new_evidence_ids"] == []
    assert returned.decode_run_arm_action_projection(raw) == projection
    assert returned.reconstruct_arm_action(projection) == domain
    assert returned.projection_matches_domain(projection, domain)


def test_observed_action_round_trips_manual_pure_revealed_observation() -> None:
    domain = _action(observed=True)
    projection = returned.project_arm_action(domain, expected_run_id=RUN_ID)
    assert projection.observed_objective == f64(0.25)
    assert projection.oracle_observation is not None
    assert projection.oracle_observation.authorization.run_id == RUN_ID
    assert projection.oracle_observation.authorization.source_id == DECISION_ID
    assert returned.reconstruct_arm_action(projection) == domain
    assert returned.projection_matches_domain(projection, domain)

    oracle = projection.oracle_observation
    crossed_authorization = replace(oracle.authorization, run_id="run-other")
    crossed_authorization_id = returned.recompute_observation_authorization_id(
        crossed_authorization
    )
    crossed = replace(
        projection,
        oracle_observation=replace(
            oracle,
            authorization=crossed_authorization,
            authorization_id=crossed_authorization_id,
            oracle_use_id=f"oracle-use/{crossed_authorization_id}/{oracle.oracle_key_id}",
        ),
    )
    _failure(
        lambda: returned.validate_arm_action_relation(
            crossed,
            expected_action=domain,
            expected_decision=_decision(),
            expected_run_id=RUN_ID,
            expected_previous_cumulative_decision_cost=0.0,
        ),
        category="scientific_record_invalid",
        path="observation_authorization.run_id",
    )


def test_arm_action_decoder_is_closed_strict_and_noncoercing() -> None:
    projection = returned.project_arm_action(_action(), expected_run_id=RUN_ID)
    invalid: list[object] = []
    raw = returned.projection_as_dict(projection)
    del raw["candidate_id"]
    invalid.append(raw)
    invalid.append(returned.projection_as_dict(projection) | {"extra": None})
    for field, value in (("cost", 1.0), ("step", True), ("role", "e\u0301")):
        raw = returned.projection_as_dict(projection)
        raw[field] = value
        invalid.append(raw)
    raw = returned.projection_as_dict(projection)
    raw["new_evidence_ids"] = tuple(cast(list[object], raw["new_evidence_ids"]))
    invalid.append(raw)
    raw = returned.projection_as_dict(projection)
    raw["posterior_probabilities"] = tuple(cast(list[object], raw["posterior_probabilities"]))
    invalid.append(raw)
    for payload in invalid:
        _failure(
            partial(returned.decode_run_arm_action_projection, payload),
            category="structural_projection_invalid",
        )


@pytest.mark.parametrize(
    "mode", ["objective-only", "oracle-only", "setup-observed", "setup-evidence", "costs"]
)
def test_arm_action_rejects_outcome_role_evidence_and_cost_coupling(mode: str) -> None:
    setup = returned.project_arm_action(_action(), expected_run_id=RUN_ID)
    observed = returned.project_arm_action(_action(observed=True), expected_run_id=RUN_ID)
    invalid: tuple[returned.RunArmActionProjection, ...]
    if mode == "objective-only":
        invalid = (replace(setup, observed_objective=f64(0.25)),)
    elif mode == "oracle-only":
        invalid = (
            replace(observed, observed_objective=None),
            replace(observed, observed_objective=f64(0.5)),
        )
    elif mode == "setup-observed":
        invalid = (
            replace(observed, role="setup"),
            replace(observed, candidate_id="candidate-b"),
        )
    elif mode == "setup-evidence":
        invalid = (replace(setup, new_evidence_ids=("evidence-1",)),)
    else:
        invalid = (
            replace(setup, cost=f64(-0.125)),
            replace(setup, cost=f64(1.25), cumulative_decision_cost=f64(1.0)),
        )
    for value in invalid:
        _failure(
            partial(returned.reconstruct_arm_action, value),
            category="scientific_record_invalid",
        )


def test_action_preserves_new_evidence_order() -> None:
    projection = returned.project_arm_action(_action(observed=True), expected_run_id=RUN_ID)
    reordered = replace(projection, new_evidence_ids=tuple(reversed(projection.new_evidence_ids)))
    assert returned.reconstruct_arm_action(reordered).new_evidence_ids == (
        "evidence-2",
        "evidence-1",
    )


def test_action_rejects_duplicate_new_evidence_ids() -> None:
    projection = returned.project_arm_action(_action(observed=True), expected_run_id=RUN_ID)
    _failure(
        partial(
            returned.reconstruct_arm_action,
            replace(projection, new_evidence_ids=("evidence-1", "evidence-1")),
        ),
        category="scientific_record_invalid",
        path="arm_action.new_evidence_ids",
    )


@pytest.mark.parametrize("mode", ["reordered", "duplicate", "wrong-total", "negative"])
def test_action_rejects_invalid_posterior_order_duplicates_and_values(mode: str) -> None:
    projection = returned.project_arm_action(_action(), expected_run_id=RUN_ID)
    pairs = projection.posterior_probabilities
    if mode == "reordered":
        changed = tuple(reversed(pairs))
    elif mode == "duplicate":
        changed = (pairs[0], pairs[0])
    elif mode == "wrong-total":
        changed = ((pairs[0][0], f64(0.5)), (pairs[1][0], f64(0.25)))
    else:
        changed = ((pairs[0][0], f64(-0.125)), (pairs[1][0], f64(1.125)))
    _failure(
        partial(
            returned.reconstruct_arm_action,
            replace(projection, posterior_probabilities=changed),
        ),
        category="scientific_record_invalid",
        path="arm_action.posterior_probabilities",
    )


@pytest.mark.parametrize("observed", [False, True], ids=["setup", "observed"])
def test_arm_action_relation_accepts_exact_cost_prefix_and_decision(observed: bool) -> None:
    decision, action = _decision(), _action(observed=observed)
    returned.validate_arm_action_relation(
        returned.project_arm_action(action, expected_run_id=RUN_ID),
        expected_action=action,
        expected_decision=decision,
        expected_run_id=RUN_ID,
        expected_previous_cumulative_decision_cost=0.0,
    )


@pytest.mark.parametrize("mode", ["step", "candidate", "cumulative"])
def test_arm_action_relation_rejects_cross_context_and_cost_prefix(mode: str) -> None:
    decision, action = _decision(), _action()
    previous = 0.25 if mode == "cumulative" else 0.0
    if mode == "step":
        decision = replace(decision, step=2, decision_id=f"decision/{RUN_ID}/0002")
    elif mode == "candidate":
        decision = replace(decision, selected_candidate_id="candidate-other")
    _failure(
        lambda: returned.validate_arm_action_relation(
            returned.project_arm_action(action, expected_run_id=RUN_ID),
            expected_action=action,
            expected_decision=decision,
            expected_run_id=RUN_ID,
            expected_previous_cumulative_decision_cost=previous,
        ),
        category="scientific_record_invalid",
    )


def test_arm_action_reports_projection_and_relation_context_as_missing() -> None:
    observed = _action(observed=True)
    _failure(
        partial(returned.project_arm_action, observed),
        category="missing_relation_context",
        path="arm_action.oracle_observation.authorization.run_id",
    )
    decision, action = _decision(), _action()
    projection = returned.project_arm_action(action, expected_run_id=RUN_ID)
    operations = (
        partial(returned.validate_arm_action_relation, projection),
        partial(returned.validate_arm_action_relation, projection, expected_action=action),
        partial(
            returned.validate_arm_action_relation,
            projection,
            expected_action=action,
            expected_decision=decision,
        ),
        partial(
            returned.validate_arm_action_relation,
            projection,
            expected_action=action,
            expected_decision=decision,
            expected_run_id=RUN_ID,
        ),
    )
    for operation in operations:
        _failure(operation, category="missing_relation_context")


def test_nested_oracle_failure_precedes_outer_action_science() -> None:
    projection = returned.project_arm_action(_action(observed=True), expected_run_id=RUN_ID)
    oracle = cast(returned.RunRevealedObservationProjection, projection.oracle_observation)
    malformed = replace(
        projection,
        oracle_observation=replace(oracle, seed=True),
        role="setup",
    )
    _failure(
        partial(returned.reconstruct_arm_action, malformed),
        category="structural_projection_invalid",
        path="revealed_observation.seed",
    )
