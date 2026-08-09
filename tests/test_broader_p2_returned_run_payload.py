from __future__ import annotations

import ast
import hashlib
import inspect
from collections.abc import Callable
from dataclasses import fields, replace
from functools import cache, partial
from pathlib import Path
from typing import Any, Literal, NoReturn, cast

import pytest

import research_decision_engine.benchmarks.broader_oracle as oracle
import research_decision_engine.benchmarks.broader_validation_evidence as stage1
from research_decision_engine.belief_models import MatchedEffectObservation, belief_model
from research_decision_engine.benchmarks import broader_returned_run as returned
from research_decision_engine.benchmarks.broader_calibration_history import (
    CALIBRATION_SELECTION_VERSION,
    CalibrationHistorySelection,
)
from research_decision_engine.benchmarks.broader_calibration_selector_replay import (
    raw_effect_sha256,
)
from research_decision_engine.benchmarks.broader_calibration_selector_replay import (
    replay_calibration_history_selection as selector_replay,
)
from research_decision_engine.benchmarks.broader_oracle import (
    ObservationAuthority,
    RevealedObservation,
)
from research_decision_engine.benchmarks.broader_protocol import (
    canonical_json_bytes,
    f64,
    protocol_hash,
)
from research_decision_engine.benchmarks.broader_runner import (
    BroaderArmRun,
    arm_spec,
    run_arm,
    validate_lineage_binding,
)
from research_decision_engine.benchmarks.broader_worlds import (
    CANDIDATES_BY_ID,
    GROUP_IDS,
    WORLDS_BY_ID,
)
from tests import p2_returned_run_architecture_guard as architecture

WORLD_ID = "d3_adam"
SEED = 9000
BUDGET_ID = "budget-2.25"
BUDGET = 2.25
SCHEMA_VERSION = "broader-replication-returned-run/v1"
PAYLOAD_HASH_DOMAIN = "validation_evidence_returned_run_payload/v1"

RETURNED_RUN_FIELDS = (
    "actions",
    "arm",
    "budget",
    "budget_id",
    "calibration",
    "calibration_cost",
    "comparison_id",
    "completed_experiments",
    "decision_cost",
    "decisions",
    "diagnostics",
    "effect_history",
    "evidence",
    "initial_probabilities",
    "lineage",
    "run_id",
    "run_status",
    "schema_version",
    "seed",
    "terminal_reason",
    "updates",
    "world_id",
)
ARM_FIELDS = ("arm_id", "arm_order", "belief_model_id", "policy_id")
STAGES = tuple(f"S{index}" for index in range(1, 11))
_NO_RESULT = object()


@cache
def _run(arm_id: str) -> BroaderArmRun:
    """Create one deterministic unit-level run without P2 execution or evidence writing."""

    world = WORLDS_BY_ID[WORLD_ID]
    return run_arm(
        arm=arm_spec(arm_id),
        world=world.public,
        seed=SEED,
        budget_id=BUDGET_ID,
        budget=BUDGET,
        authority=ObservationAuthority(world=world, seed=SEED),
    )


@cache
def _multi_update_run() -> BroaderArmRun:
    """Create a small two-update run for order instrumentation."""

    world = WORLDS_BY_ID["h_adam_low"]
    return run_arm(
        arm=arm_spec("fixed_lookahead"),
        world=world.public,
        seed=SEED,
        budget_id="budget-4.50",
        budget=4.5,
        authority=ObservationAuthority(world=world, seed=SEED),
    )


@pytest.fixture(scope="module")
def fixed_run() -> BroaderArmRun:
    return _run("fixed_lookahead")


@pytest.fixture(scope="module")
def calibrated_run() -> BroaderArmRun:
    return _run("calibrated_ig")


def _dataclass_primitives(value: object) -> tuple[tuple[str, object], ...]:
    return tuple((field.name, getattr(value, field.name)) for field in fields(cast(Any, value)))


def _oracle_current_identity_snapshot() -> tuple[str, object]:
    current = oracle._current_oracle_identities
    return (
        "currentness_callable",
        (
            current.__module__,
            current.__qualname__,
            id(current.__code__),
            current.__code__.co_code,
            repr(current.__code__.co_consts),
        ),
    )


def _oracle_record_primitives(record: object) -> tuple[tuple[str, object], ...]:
    projected: list[tuple[str, object]] = [("record_object_id", id(record))]
    for name in ("binding", "result", "evidence"):
        if hasattr(record, name):
            projected.append((f"{name}_object_id", id(getattr(record, name))))
    for name in ("fingerprint", "active", "execution_claimed"):
        if hasattr(record, name):
            projected.append((name, getattr(record, name)))
    return tuple(projected)


def _observable_state_snapshot() -> tuple[object, ...]:
    production = stage1._production_registry_snapshot()
    with oracle._EVIDENCE_LOCK:
        issued = tuple(
            (
                name,
                tuple(
                    (key, _oracle_record_primitives(record))
                    for key, record in sorted(registry.items())
                ),
            )
            for name, registry in (
                ("evidence_bindings", oracle._ISSUED_ORACLE_EVIDENCE_BINDINGS),
                ("conformance_results", oracle._ISSUED_ORACLE_CONFORMANCE_RESULTS),
                ("fixture_bindings", oracle._ISSUED_ORACLE_FIXTURE_BINDINGS),
                ("fixture_results", oracle._ISSUED_ORACLE_FIXTURE_RESULTS),
                ("fixture_evidence", oracle._ISSUED_ORACLE_FIXTURE_EVIDENCE),
            )
        )
        used = (
            tuple(sorted(oracle._USED_VALIDATION_RUN_IDENTITIES)),
            tuple(sorted(oracle._USED_EVIDENCE_BUNDLE_IDENTITIES)),
        )
    return (
        _dataclass_primitives(production),
        _oracle_current_identity_snapshot(),
        issued,
        used,
        tuple((key, repr(value)) for key, value in CANDIDATES_BY_ID.items()),
        tuple((key, repr(value)) for key, value in WORLDS_BY_ID.items()),
    )


def _tree_snapshot(root: Path) -> tuple[tuple[str, str, bytes | None], ...]:
    return tuple(
        (
            "file" if path.is_file() else "directory",
            path.relative_to(root).as_posix(),
            path.read_bytes() if path.is_file() else None,
        )
        for path in sorted(root.rglob("*"))
    )


def _scientific_call_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, str]]:
    original = returned._scientific
    calls: list[tuple[str, str]] = []

    def scientific(path: str, detail: str) -> NoReturn:
        calls.append((path, detail))
        original(path, detail)

    monkeypatch.setattr(returned, "_scientific", scientific)
    return calls


def _failure(
    call: Callable[[], object],
    *,
    category: returned.ValidationCategory,
    path: str | None = None,
    path_prefix: str | None = None,
) -> returned.ReturnedRunProjectionError:
    before = _observable_state_snapshot()
    result: object = _NO_RESULT
    with pytest.raises(returned.ReturnedRunProjectionError) as captured:
        result = call()
    error = captured.value
    assert result is _NO_RESULT
    assert _observable_state_snapshot() == before
    assert error.category == category
    assert error.failure_code == (
        returned.EXECUTION_RETURNED_SCIENTIFIC_RECORD_INVALID
        if category == "scientific_record_invalid"
        else None
    )
    if path is not None:
        assert error.path == path
    if path_prefix is not None:
        assert error.path.startswith(path_prefix)
    assert all(
        not hasattr(error, name)
        for name in ("scientific_output", "recommendation", "capability", "evidence_write")
    )
    return error


def _selection_identity_with_digests(
    selection: CalibrationHistorySelection,
    digest_sequence: tuple[str, ...],
) -> str:
    return protocol_hash(
        CALIBRATION_SELECTION_VERSION,
        {
            "study_id": selection.study_id,
            "world_id": selection.world_id,
            "seed": selection.seed,
            "namespace": selection.namespace,
            "comparison_group_id": selection.comparison_group_id,
            "target_comparison_group_id": selection.target_comparison_group_id,
            "source_sequence_cutoff": selection.source_sequence_cutoff,
            "source_effect_ids": list(selection.source_effect_ids),
            "source_effect_payload_sha256": list(digest_sequence),
            "source_observation_identities": [
                list(item) for item in selection.source_observation_identities
            ],
            "source_oracle_key_ids": list(selection.source_oracle_key_ids),
            "source_candidate_pairs": [list(item) for item in selection.source_candidate_pairs],
            "source_replication_ids": list(selection.source_replication_ids),
            "effect_values": [f64(item) for item in selection.effect_values],
            "sample_count": selection.sample_count,
            "sample_mean": f64(selection.sample_mean),
            "sample_standard_deviation": f64(selection.sample_standard_deviation),
            "ddof": selection.ddof,
            "sigma_floor": f64(selection.sigma_floor),
            "estimated_sigma": f64(selection.estimated_sigma),
            "eligibility_basis": selection.eligibility_basis,
        },
    )


@pytest.mark.parametrize("arm_id", ["fixed_ig", "calibrated_ig"])
def test_returned_run_exact_frozen_schema_and_version(arm_id: str) -> None:
    run = _run(arm_id)
    projection = returned.project_returned_run(run)
    raw = returned.projection_as_dict(projection)

    assert len(RETURNED_RUN_FIELDS) == 22
    assert tuple(field.name for field in fields(type(projection))) == RETURNED_RUN_FIELDS
    assert tuple(raw) == RETURNED_RUN_FIELDS
    assert "result_payload_sha256" not in raw
    assert raw["schema_version"] == SCHEMA_VERSION
    assert tuple(cast(dict[str, object], raw["arm"])) == ARM_FIELDS
    assert isinstance(raw["actions"], list)
    assert isinstance(raw["completed_experiments"], list)
    assert isinstance(raw["decisions"], list)
    assert isinstance(raw["diagnostics"], list)
    assert isinstance(raw["effect_history"], list)
    assert isinstance(raw["evidence"], list)
    assert isinstance(raw["initial_probabilities"], list)
    assert isinstance(raw["updates"], list)
    assert (raw["calibration"] is None) == (run.calibration is None)
    assert returned.decode_returned_run_projection(raw) == projection
    assert returned.decode_returned_run_projection(dict(reversed(tuple(raw.items())))) == projection


def test_returned_run_decoder_is_closed_strict_and_noncoercing(fixed_run: BroaderArmRun) -> None:
    projection = returned.project_returned_run(fixed_run)
    raw = returned.projection_as_dict(projection)
    malformed: list[object] = []

    missing = dict(raw)
    del missing["run_id"]
    malformed.append(missing)
    malformed.append(dict(raw) | {"unexpected": None})
    malformed.append(tuple(raw.items()))

    wrong_budget = dict(raw)
    wrong_budget["budget"] = BUDGET
    malformed.append(wrong_budget)
    wrong_seed = dict(raw)
    wrong_seed["seed"] = True
    malformed.append(wrong_seed)
    wrong_actions = dict(raw)
    wrong_actions["actions"] = tuple(cast(list[object], raw["actions"]))
    malformed.append(wrong_actions)
    wrong_action_item = dict(raw)
    wrong_action_item["actions"] = [None, *cast(list[object], raw["actions"])[1:]]
    malformed.append(wrong_action_item)
    wrong_calibration = dict(raw)
    wrong_calibration["calibration"] = {}
    malformed.append(wrong_calibration)
    wrong_status = dict(raw)
    wrong_status["run_status"] = "success"
    malformed.append(wrong_status)
    wrong_version = dict(raw)
    wrong_version["schema_version"] = "broader-replication-returned-run/v2"
    malformed.append(wrong_version)
    wrong_arm = dict(raw)
    arm = dict(cast(dict[str, object], raw["arm"]))
    arm["arm_order"] = True
    wrong_arm["arm"] = arm
    malformed.append(wrong_arm)

    for payload in malformed:
        _failure(
            partial(returned.decode_returned_run_projection, payload),
            category="structural_projection_invalid",
        )


@pytest.mark.parametrize(
    ("run_status", "terminal_reason"),
    [
        ("invalid", "candidate_space_exhausted"),
        ("invalid", "integrity_abort"),
        ("complete", "integrity_abort"),
    ],
)
def test_decodable_invalid_and_integrity_abort_runs_are_never_accepted(
    run_status: Literal["complete", "invalid"],
    terminal_reason: Literal["candidate_space_exhausted", "budget_exhausted", "integrity_abort"],
) -> None:
    run = _run("fixed_ig")
    projection = replace(
        returned.project_returned_run(run),
        run_status=run_status,
        terminal_reason=terminal_reason,
    )

    _failure(
        partial(returned.reconstruct_returned_run, projection),
        category="scientific_record_invalid",
        path="returned_run.S9.11",
    )


@pytest.mark.parametrize("arm_id", ["fixed_ig", "calibrated_ig"])
def test_returned_run_projects_reconstructs_and_matches_expected_relation(arm_id: str) -> None:
    run = _run(arm_id)
    projection = returned.project_returned_run(run)

    assert returned.reconstruct_returned_run(projection) == run
    assert returned.projection_matches_domain(projection, run)
    returned.validate_returned_run_relation(projection, expected_run=run)


def test_returned_run_relation_requires_and_compares_exact_expected_run(
    fixed_run: BroaderArmRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection = returned.project_returned_run(fixed_run)
    calls: list[returned.ReturnedRunProjection] = []

    def reconstruct(value: returned.ReturnedRunProjection) -> BroaderArmRun:
        calls.append(value)
        return fixed_run

    monkeypatch.setattr(returned, "reconstruct_returned_run", reconstruct)
    _failure(
        partial(returned.validate_returned_run_relation, projection),
        category="missing_relation_context",
        path="returned_run",
    )
    _failure(
        partial(
            returned.validate_returned_run_relation,
            projection,
            expected_run=replace(fixed_run, comparison_id="comparison:other"),
        ),
        category="scientific_record_invalid",
        path="returned_run",
    )
    assert calls == [projection, projection]


@pytest.mark.parametrize("arm_id", ["fixed_ig", "calibrated_ig"])
def test_result_payload_sha256_uses_exact_domain_and_complete_projection(
    arm_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(arm_id)
    projection = returned.project_returned_run(run)
    reconstructed: list[returned.ReturnedRunProjection] = []

    def validate(value: returned.ReturnedRunProjection) -> BroaderArmRun:
        reconstructed.append(value)
        return run

    monkeypatch.setattr(returned, "reconstruct_returned_run", validate)
    expected = protocol_hash(PAYLOAD_HASH_DOMAIN, returned.projection_as_dict(projection))

    assert returned.result_payload_sha256(projection) == expected
    assert reconstructed == [projection]


def test_result_payload_hash_is_deterministic_and_has_no_caller_hash_parameter() -> None:
    projection = returned.project_returned_run(_run("fixed_ig"))

    assert returned.result_payload_sha256(projection) == returned.result_payload_sha256(projection)
    assert tuple(inspect.signature(returned.result_payload_sha256).parameters) == ("projection",)


def test_result_payload_hash_covers_a_nested_projection_change(
    fixed_run: BroaderArmRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection = returned.project_returned_run(fixed_run)
    action = projection.actions[0]
    changed = replace(
        projection,
        actions=(
            replace(
                action,
                new_evidence_ids=(*action.new_evidence_ids, "evidence:hash-only"),
            ),
            *projection.actions[1:],
        ),
    )
    monkeypatch.setattr(returned, "reconstruct_returned_run", lambda _value: fixed_run)

    assert returned.result_payload_sha256(changed) == protocol_hash(
        PAYLOAD_HASH_DOMAIN,
        returned.projection_as_dict(changed),
    )
    assert returned.result_payload_sha256(changed) != returned.result_payload_sha256(projection)


def test_result_payload_hash_is_not_attempted_after_gate_failure(
    fixed_run: BroaderArmRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection = returned.project_returned_run(fixed_run)
    hash_calls: list[tuple[str, object]] = []

    def reject(_value: returned.ReturnedRunProjection) -> BroaderArmRun:
        returned._scientific("returned_run.S1", "gate sentinel")

    def hash_after_gate(domain: str, value: object) -> str:
        hash_calls.append((domain, value))
        return "0" * 64

    monkeypatch.setattr(returned, "reconstruct_returned_run", reject)
    monkeypatch.setattr(returned, "protocol_hash", hash_after_gate)

    _failure(
        partial(returned.result_payload_sha256, projection),
        category="scientific_record_invalid",
        path="returned_run.S1",
    )
    assert hash_calls == []


def _install_stage_sentinels(
    monkeypatch: pytest.MonkeyPatch,
    run: BroaderArmRun,
    *,
    stop: str | None,
) -> list[str]:
    calls: list[str] = []

    def reached(stage: str) -> None:
        calls.append(stage)
        if stage == stop:
            returned._scientific(f"returned_run.{stage}", "sentinel failure")

    def s1(_projection: returned.ReturnedRunProjection) -> None:
        reached("S1")

    def s2(
        _projection: returned.ReturnedRunProjection,
    ) -> tuple[dict[object, object], tuple[object, ...], tuple[object, ...]]:
        reached("S2")
        return {}, (), ()

    def s3(
        _projection: returned.ReturnedRunProjection,
        _cache: dict[object, object],
    ) -> tuple[
        object, tuple[object, ...], tuple[object, ...], tuple[object, ...], dict[object, object]
    ]:
        reached("S3")
        return run.lineage, (), (), (), {}

    def s4(
        _projection: returned.ReturnedRunProjection,
        _cache: dict[object, object],
    ) -> None:
        reached("S4")

    def s5(
        _projection: returned.ReturnedRunProjection,
        _cache: dict[object, object],
    ) -> dict[object, object]:
        reached("S5")
        return {}

    def s6(_projection: returned.ReturnedRunProjection) -> dict[object, object]:
        reached("S6")
        return {}

    def s7(*_args: object) -> object:
        reached("S7")
        return run.calibration

    def s8(*_args: object, **_kwargs: object) -> BroaderArmRun:
        reached("S8")
        return run

    def s9(_run: BroaderArmRun) -> None:
        reached("S9")

    def s10(_run: BroaderArmRun) -> None:
        reached("S10")

    monkeypatch.setattr(returned, "_validate_returned_run_s1", s1)
    monkeypatch.setattr(returned, "_construct_returned_run_s2", s2)
    monkeypatch.setattr(returned, "_construct_returned_run_s3", s3)
    monkeypatch.setattr(returned, "_construct_returned_run_s4", s4)
    monkeypatch.setattr(returned, "_construct_returned_run_s5", s5)
    monkeypatch.setattr(returned, "_validate_returned_run_s6", s6)
    monkeypatch.setattr(returned, "_construct_returned_run_s7", s7)
    monkeypatch.setattr(returned, "_construct_returned_run_s8", s8)
    monkeypatch.setattr(returned, "_validate_returned_run_s9", s9)
    monkeypatch.setattr(returned, "_validate_returned_run_s10", s10)
    return calls


def test_reconstruction_invokes_exact_s1_through_s10_outer_order(
    fixed_run: BroaderArmRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection = returned.project_returned_run(fixed_run)
    calls = _install_stage_sentinels(monkeypatch, fixed_run, stop=None)

    assert returned.reconstruct_returned_run(projection) is fixed_run
    assert tuple(calls) == STAGES


@pytest.mark.parametrize("stop", STAGES)
def test_each_scientific_stage_stops_every_later_stage(
    stop: str,
    fixed_run: BroaderArmRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection = returned.project_returned_run(fixed_run)
    calls = _install_stage_sentinels(monkeypatch, fixed_run, stop=stop)

    _failure(
        partial(returned.reconstruct_returned_run, projection),
        category="scientific_record_invalid",
        path=f"returned_run.{stop}",
    )
    assert tuple(calls) == STAGES[: STAGES.index(stop) + 1]


def _stage_defect(stage: str) -> returned.ReturnedRunProjection:
    if stage == "S1":
        return replace(returned.project_returned_run(_run("fixed_ig")), budget=f64(-1.0))
    if stage == "S2":
        projection = returned.project_returned_run(_run("fixed_lookahead"))
        evidence = projection.evidence[0]
        bad_evidence = replace(evidence, evidence_id="")
        return replace(projection, evidence=(bad_evidence, *projection.evidence[1:]))
    if stage == "S3":
        projection = returned.project_returned_run(_run("fixed_lookahead"))
        current_state = projection.lineage.current_state
        changed_state = replace(
            current_state,
            lineage_id=f"{current_state.lineage_id}/substituted",
        )
        return replace(
            projection,
            lineage=replace(projection.lineage, current_state=changed_state),
        )
    if stage == "S4":
        projection = returned.project_returned_run(_run("fixed_ig"))
        decision = projection.decisions[0]
        policy = decision.policy_trace
        decision_trace = cast(returned.RunDecisionTraceProjection, policy.projection)
        selected_score = replace(decision_trace.selected, score_reason="")
        changed_decision_trace = replace(
            decision_trace,
            selected=selected_score,
            ranked_candidates=(selected_score, *decision_trace.ranked_candidates[1:]),
        )
        changed_policy = replace(policy, projection=changed_decision_trace)
        return replace(
            projection,
            decisions=(replace(decision, policy_trace=changed_policy), *projection.decisions[1:]),
        )
    if stage == "S5":
        projection = returned.project_returned_run(_run("fixed_lookahead"))
        decision = projection.decisions[0]
        policy = decision.policy_trace
        lookahead_trace = cast(returned.RunLookaheadTraceProjection, policy.projection)
        first_action = lookahead_trace.selected
        branch = first_action.branches[0]
        second_action = replace(branch.second_action, reason="")
        changed_first = replace(
            first_action,
            branches=(
                replace(branch, second_action=second_action),
                *first_action.branches[1:],
            ),
        )
        changed_lookahead_trace = replace(lookahead_trace, selected=changed_first)
        changed_policy = replace(policy, projection=changed_lookahead_trace)
        return replace(
            projection,
            decisions=(replace(decision, policy_trace=changed_policy), *projection.decisions[1:]),
        )
    if stage == "S6":
        projection = returned.project_returned_run(_run("fixed_ig"))
        index = next(
            index
            for index, action in enumerate(projection.actions)
            if action.oracle_observation is not None
        )
        action = projection.actions[index]
        observation = cast(returned.RunRevealedObservationProjection, action.oracle_observation)
        changed_action = replace(
            action,
            oracle_observation=replace(observation, z="0.125"),
        )
        return replace(
            projection,
            actions=(
                *projection.actions[:index],
                changed_action,
                *projection.actions[index + 1 :],
            ),
        )
    if stage == "S7":
        projection = returned.project_returned_run(_run("calibrated_ig"))
        calibration = cast(returned.RunCalibrationProjection, projection.calibration)
        estimates = calibration.estimates
        changed_estimate = replace(
            estimates[0],
            comparison_group_id=estimates[1].comparison_group_id,
        )
        changed_calibration = replace(
            calibration,
            estimates=(changed_estimate, *estimates[1:]),
        )
        return replace(projection, calibration=changed_calibration)
    if stage == "S8":
        projection = returned.project_returned_run(_run("fixed_ig"))
        return replace(projection, decisions=projection.decisions[:-1])
    if stage == "S9":
        projection = returned.project_returned_run(_run("fixed_lookahead"))
        run = _run("fixed_lookahead")
        return replace(projection, decision_cost=f64(run.decision_cost + 0.125))
    if stage == "S10":
        projection = returned.project_returned_run(_run("fixed_ig"))
        return replace(projection, comparison_id="comparison:substituted")
    raise AssertionError(f"unknown stage {stage}")


@pytest.mark.parametrize(
    ("stage", "expected_path"),
    [
        ("S1", "returned_run.S1.numeric.budget"),
        ("S2", "evidence"),
        ("S3", "lineage"),
        ("S4", "candidate_score"),
        ("S5", "lookahead_second_action"),
        ("S6", "returned_run.S6"),
        ("S7", "returned_run.S7.estimates.comparison_group_id"),
        ("S8", "returned_run.S8"),
        ("S9", "returned_run.S9.8"),
        ("S10", "returned_run.S10.11"),
    ],
)
def test_real_projection_defects_fail_in_their_frozen_stage(
    stage: str,
    expected_path: str,
) -> None:
    _failure(
        partial(returned.reconstruct_returned_run, _stage_defect(stage)),
        category="scientific_record_invalid",
        path_prefix=expected_path,
    )


def test_s6_reconstructs_each_observation_only_through_the_pure_formula(
    calibrated_run: BroaderArmRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection = returned.project_returned_run(calibrated_run)
    contexts = returned._returned_observation_contexts(projection)
    original = returned._pure_revealed_observation
    calls: list[tuple[returned.RunRevealedObservationProjection, dict[str, object]]] = []

    def pure(
        observation: returned.RunRevealedObservationProjection,
        **kwargs: object,
    ) -> RevealedObservation:
        calls.append((observation, dict(kwargs)))
        return original(observation, **cast(Any, kwargs))

    monkeypatch.setattr(returned, "_pure_revealed_observation", pure)

    reconstructed = returned._validate_returned_run_s6(projection)

    assert len(calls) == len(contexts)
    assert len(reconstructed) == len({item[0] for item in contexts})
    for call, context in zip(calls, contexts, strict=True):
        observation, kind, source_id, candidate_id, path = context
        assert call == (
            observation,
            {
                "run_id": projection.run_id,
                "world_id": projection.world_id,
                "seed": projection.seed,
                "expected_kind": kind,
                "expected_source_id": source_id,
                "expected_candidate_id": candidate_id,
                "path": path,
            },
        )


def test_s6_source_has_no_authority_issuance_or_capability_consumer() -> None:
    source = Path(returned.__file__ or "").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_validate_returned_run_s6"
    )
    calls = {
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    loaded_names = {
        node.id
        for node in ast.walk(function)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }

    assert "_pure_revealed_observation" in loaded_names
    assert (calls | loaded_names).isdisjoint(
        {
            "ObservationAuthority",
            "authorize_observation",
            "_revealed_record",
            "reobserve_authorized_observation",
            "selected_only_interface",
            "observe_selected",
        }
    )


def _construct_s8_from_domain(
    projection: returned.ReturnedRunProjection,
    run: BroaderArmRun,
) -> BroaderArmRun:
    """Supply already reconstructed S2-S7 domain records to the isolated S8 gate."""

    observations: dict[returned.RunRevealedObservationProjection, Any] = {}
    for projected, action in zip(projection.actions, run.actions, strict=True):
        if projected.oracle_observation is not None:
            assert action.oracle_observation is not None
            observations[projected.oracle_observation] = action.oracle_observation
    traces: dict[returned.RunPolicyTraceProjection, Any] = {
        projected.policy_trace: decision.policy_trace
        for projected, decision in zip(projection.decisions, run.decisions, strict=True)
    }
    return returned._construct_returned_run_s8(
        projection,
        completed=run.completed_experiments,
        evidence=run.evidence,
        lineage=run.lineage,
        updates=run.updates,
        diagnostics=run.diagnostics,
        effects=run.effect_history,
        calibration=run.calibration,
        observations=observations,
        traces=traces,
    )


def _s8_defect(case: str) -> returned.ReturnedRunProjection:
    projection = returned.project_returned_run(_run("fixed_lookahead"))
    if case == "S8.5":
        selected_decision = projection.decisions[1]
        changed_decision_action = replace(
            selected_decision,
            selected_candidate_id=projection.actions[0].candidate_id,
        )
        return replace(
            projection,
            decisions=(
                *projection.decisions[:1],
                changed_decision_action,
                *projection.decisions[2:],
            ),
        )
    if case == "S8.6":
        feasibility_decision = projection.decisions[0]
        changed_feasibility = replace(feasibility_decision, affordable_candidate_ids=())
        return replace(
            projection,
            decisions=(changed_feasibility, *projection.decisions[1:]),
        )
    if case == "S8.7":
        cost_action = projection.actions[0]
        changed_cost = replace(cost_action, cost=f64(0.0))
        return replace(projection, actions=(changed_cost, *projection.actions[1:]))
    if case == "S8.8":
        completed = projection.completed_experiments[0]
        changed_experiment = replace(completed, record_id=completed.record_id + 1000)
        return replace(
            projection,
            completed_experiments=(
                changed_experiment,
                *projection.completed_experiments[1:],
            ),
        )
    if case == "S8.9":
        evidence_action = projection.actions[-1]
        changed_evidence = replace(
            evidence_action,
            new_evidence_ids=("evidence:substituted",),
        )
        return replace(
            projection,
            actions=(*projection.actions[:-1], changed_evidence),
        )
    raise AssertionError(f"unknown S8 case {case}")


@pytest.mark.parametrize(
    ("case", "expected_path"),
    [
        ("S8.5", "returned_run.S8.decision_action"),
        ("S8.6", "returned_run.S8.feasibility"),
        ("S8.7", "returned_run.S8.cost"),
        ("S8.8", "returned_run.S8.completed_experiments"),
        ("S8.9", "returned_run.S8.new_evidence_ids"),
    ],
)
def test_s8_5_through_s8_9_have_distinct_predicate_gates(
    case: str,
    expected_path: str,
    fixed_run: BroaderArmRun,
) -> None:
    _failure(
        partial(_construct_s8_from_domain, _s8_defect(case), fixed_run),
        category="scientific_record_invalid",
        path=expected_path,
    )


def test_s8_5_completes_for_every_action_before_any_s8_6_check(
    fixed_run: BroaderArmRun,
) -> None:
    projection = _s8_defect("S8.5")
    first = projection.decisions[0]
    projection = replace(
        projection,
        decisions=(
            replace(first, affordable_candidate_ids=()),
            *projection.decisions[1:],
        ),
    )

    _failure(
        partial(_construct_s8_from_domain, projection, fixed_run),
        category="scientific_record_invalid",
        path="returned_run.S8.decision_action",
    )


def _s9_1(run: BroaderArmRun) -> BroaderArmRun:
    return replace(run, evidence=run.evidence[:-1])


def _s9_2(run: BroaderArmRun) -> BroaderArmRun:
    return replace(run, diagnostics=run.diagnostics[:-1])


def _s9_3(run: BroaderArmRun) -> BroaderArmRun:
    update = run.updates[0]
    changed = replace(update, state_before=update.posterior_state)
    return replace(run, updates=(changed, *run.updates[1:]))


def _s9_4(run: BroaderArmRun) -> BroaderArmRun:
    lineage = replace(run.lineage, current_state=run.updates[0].state_before)
    return replace(run, lineage=lineage)


def _s9_5(run: BroaderArmRun) -> BroaderArmRun:
    update = run.updates[0]
    evidence = update.evidence
    details = tuple(
        item for item in evidence.provenance.details if item[0] != "comparison_group_id"
    )
    changed_evidence = replace(
        evidence,
        provenance=replace(evidence.provenance, details=details),
    )
    bayesian = replace(update.bayesian_update, evidence=changed_evidence)
    changed_update = replace(update, evidence=changed_evidence, bayesian_update=bayesian)
    return replace(
        run,
        evidence=(changed_evidence, *run.evidence[1:]),
        updates=(changed_update, *run.updates[1:]),
    )


def _s9_6(run: BroaderArmRun) -> BroaderArmRun:
    return replace(run, effect_history=run.effect_history[:-1])


def _s9_7(run: BroaderArmRun) -> BroaderArmRun:
    calibration = cast(Any, run.calibration)
    changed = replace(calibration, estimates=tuple(reversed(calibration.estimates)))
    return replace(run, calibration=changed)


def _s9_8(run: BroaderArmRun) -> BroaderArmRun:
    return replace(run, decision_cost=run.decision_cost + 0.125)


def _s9_9(run: BroaderArmRun) -> BroaderArmRun:
    return replace(run, calibration_cost=1.0)


def _s9_10(run: BroaderArmRun) -> BroaderArmRun:
    action = run.actions[0]
    changed = replace(
        action,
        cumulative_decision_cost=action.cumulative_decision_cost + 0.125,
    )
    return replace(run, actions=(changed, *run.actions[1:]))


def _s9_11(run: BroaderArmRun) -> BroaderArmRun:
    terminal: Literal["candidate_space_exhausted", "budget_exhausted"] = (
        "candidate_space_exhausted"
        if run.terminal_reason != "candidate_space_exhausted"
        else "budget_exhausted"
    )
    return replace(run, terminal_reason=terminal)


type RunMutation = Callable[[BroaderArmRun], BroaderArmRun]


@pytest.mark.parametrize(
    ("case", "mutate", "fixture_name"),
    [
        ("S9.1", _s9_1, "fixed"),
        ("S9.2", _s9_2, "fixed"),
        ("S9.3", _s9_3, "fixed"),
        ("S9.4", _s9_4, "fixed"),
        ("S9.5", _s9_5, "fixed"),
        ("S9.6", _s9_6, "fixed"),
        ("S9.7", _s9_7, "calibrated"),
        ("S9.8", _s9_8, "fixed"),
        ("S9.9", _s9_9, "fixed"),
        ("S9.10", _s9_10, "fixed"),
        ("S9.11", _s9_11, "fixed"),
    ],
)
def test_all_eleven_s9_cross_object_reconciliations_are_distinct_and_ordered(
    case: str,
    mutate: RunMutation,
    fixture_name: str,
    fixed_run: BroaderArmRun,
    calibrated_run: BroaderArmRun,
) -> None:
    run = calibrated_run if fixture_name == "calibrated" else fixed_run
    _failure(
        partial(returned._validate_returned_run_s9, mutate(run)),
        category="scientific_record_invalid",
        path_prefix=f"returned_run.{case}",
    )


@pytest.mark.parametrize(
    ("mutate", "expected_path"),
    [
        (lambda run: _s9_11(_s9_1(run)), "returned_run.S9.1"),
        (lambda run: _s9_8(_s9_6(run)), "returned_run.S9.6"),
        (lambda run: _s9_11(_s9_8(run)), "returned_run.S9.8"),
    ],
)
def test_s9_compound_defects_stop_at_the_earlier_numbered_predicate(
    mutate: RunMutation,
    expected_path: str,
    fixed_run: BroaderArmRun,
) -> None:
    _failure(
        partial(returned._validate_returned_run_s9, mutate(fixed_run)),
        category="scientific_record_invalid",
        path_prefix=expected_path,
    )


def _s9_3_boundary_defect(
    run: BroaderArmRun,
    boundary: Literal["interior", "final"],
) -> BroaderArmRun:
    first, second = run.updates
    updates = (first, first, second) if boundary == "interior" else (first, second, first)
    return replace(
        run,
        updates=updates,
        evidence=tuple(item.evidence for item in updates),
        diagnostics=tuple(item.diagnostic for item in updates),
    )


@pytest.mark.parametrize(
    ("boundary", "expected_path"),
    [
        ("interior", "returned_run.S9.3.updates[1]"),
        ("final", "returned_run.S9.3.updates[2]"),
    ],
)
def test_s9_3_rejects_interior_and_final_adjacency_discontinuity(
    boundary: Literal["interior", "final"],
    expected_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _s9_3_boundary_defect(_multi_update_run(), boundary)
    ledger = _scientific_call_ledger(monkeypatch)

    _failure(
        partial(returned._validate_returned_run_s9, run),
        category="scientific_record_invalid",
        path=expected_path,
    )

    assert ledger == [(expected_path, "adjacent states differ")]


def test_s9_3_compound_faults_preserve_numbered_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adjacency_defect = _s9_3_boundary_defect(_multi_update_run(), "interior")
    ledger = _scientific_call_ledger(monkeypatch)

    _failure(
        partial(returned._validate_returned_run_s9, _s9_1(adjacency_defect)),
        category="scientific_record_invalid",
        path="returned_run.S9.1",
    )
    assert ledger == [("returned_run.S9.1", "run/update evidence differs")]

    ledger.clear()
    later_calls: list[str] = []
    original_same_f64 = returned._same_f64

    def same_f64(left: float, right: float, path: str) -> bool:
        if path.startswith("returned_run.S9.8"):
            later_calls.append(path)
        return original_same_f64(left, right, path)

    monkeypatch.setattr(returned, "_same_f64", same_f64)
    _failure(
        partial(returned._validate_returned_run_s9, _s9_8(adjacency_defect)),
        category="scientific_record_invalid",
        path="returned_run.S9.3.updates[1]",
    )
    assert ledger == [("returned_run.S9.3.updates[1]", "adjacent states differ")]
    assert later_calls == []


def _s9_6_chronology_defect(case: str) -> BroaderArmRun:
    run = _multi_update_run()
    first, second = run.effect_history
    effects: tuple[MatchedEffectObservation, ...]
    if case == "sequence_regression":
        effects = (
            replace(first, available_sequence=second.available_sequence),
            replace(second, available_sequence=first.available_sequence),
        )
    elif case == "duplicate_sequence":
        effects = (first, replace(second, available_sequence=first.available_sequence))
    elif case == "available_before_source":
        effects = (replace(first, available_sequence=0), second)
    elif case == "invalid_cutoff":
        update = run.updates[1]
        changed_update = replace(
            update,
            sigma_estimate=replace(
                update.sigma_estimate,
                cutoff_sequence=update.sigma_estimate.cutoff_sequence + 1,
            ),
        )
        return replace(
            run,
            updates=(run.updates[0], changed_update),
            decision_cost=run.decision_cost + 0.125,
        )
    elif case == "comparison_group":
        effects = (replace(first, comparison_group_id=second.comparison_group_id), second)
    else:
        assert case == "multiple"
        effects = tuple(
            replace(item, observed_effect=item.observed_effect + 0.125)
            for item in reversed(run.effect_history)
        )
    return replace(run, effect_history=effects, decision_cost=run.decision_cost + 0.125)


@pytest.mark.parametrize(
    ("case", "expected_detail"),
    [
        ("sequence_regression", "decision-effect availability differs"),
        ("duplicate_sequence", "decision-effect availability differs"),
        ("available_before_source", "decision-effect availability differs"),
        ("invalid_cutoff", "decision-effect availability differs"),
        ("comparison_group", "effect history content differs"),
        ("multiple", "effect history order or cardinality differs"),
    ],
)
def test_s9_6_rejects_each_chronology_subrelation_before_s9_8(
    case: str,
    expected_detail: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    later_calls: list[str] = []
    original_same_f64 = returned._same_f64

    def same_f64(left: float, right: float, path: str) -> bool:
        if path.startswith("returned_run.S9.8"):
            later_calls.append(path)
        return original_same_f64(left, right, path)

    monkeypatch.setattr(returned, "_same_f64", same_f64)
    ledger = _scientific_call_ledger(monkeypatch)

    _failure(
        partial(returned._validate_returned_run_s9, _s9_6_chronology_defect(case)),
        category="scientific_record_invalid",
        path="returned_run.S9.6",
    )

    assert ledger == [("returned_run.S9.6", expected_detail)]
    assert later_calls == []


def _s9_7_reconciliation_defect(case: str) -> BroaderArmRun:
    run = _run("calibrated_ig")
    calibration = cast(Any, run.calibration)
    effects = calibration.effects
    observations = calibration.observations
    decision_effects = run.effect_history[len(effects) :]
    if case == "effect_missing":
        changed_effects = effects[:-1]
        calibration = replace(calibration, effects=changed_effects)
        return replace(
            run,
            calibration=calibration,
            effect_history=(*changed_effects, *decision_effects),
        )
    if case == "effect_extra":
        changed_effects = (
            *effects,
            replace(effects[0], effect_id=f"{effects[0].effect_id}/extra"),
        )
        calibration = replace(calibration, effects=changed_effects)
        return replace(
            run,
            calibration=calibration,
            effect_history=(*changed_effects, *decision_effects),
        )
    if case == "effect_reordered":
        changed_effects = tuple(reversed(effects))
        calibration = replace(calibration, effects=changed_effects)
        return replace(
            run,
            calibration=calibration,
            effect_history=(*changed_effects, *decision_effects),
        )
    if case == "effect_identity_distinct":
        changed_effects = (
            replace(effects[0], effect_id=f"{effects[0].effect_id}/distinct"),
            *effects[1:],
        )
        calibration = replace(calibration, effects=changed_effects)
        return replace(
            run,
            calibration=calibration,
            effect_history=(*changed_effects, *decision_effects),
        )
    if case == "observation_missing":
        calibration = replace(calibration, observations=observations[:-1])
    elif case == "observation_extra":
        calibration = replace(
            calibration,
            observations=(
                *observations,
                replace(
                    observations[0],
                    oracle_use_id=f"{observations[0].oracle_use_id}/extra",
                ),
            ),
        )
    elif case == "observation_reordered":
        calibration = replace(calibration, observations=tuple(reversed(observations)))
    else:
        assert case == "observation_identity_distinct"
        changed_observations = (
            replace(
                observations[0],
                oracle_use_id=f"{observations[0].oracle_use_id}/distinct",
            ),
            *observations[1:],
        )
        calibration = replace(calibration, observations=changed_observations)
    return replace(run, calibration=calibration)


@pytest.mark.parametrize(
    ("case", "expected_detail"),
    [
        ("effect_missing", "calibration effects differ"),
        ("effect_extra", "calibration effects differ"),
        ("effect_reordered", "calibration effects differ"),
        ("effect_identity_distinct", "calibration effects differ"),
        ("observation_missing", "calibration observations differ"),
        ("observation_extra", "calibration observations differ"),
        ("observation_reordered", "calibration observations differ"),
        ("observation_identity_distinct", "calibration observations differ"),
    ],
)
def test_s9_7_reconciles_ordered_deployment_records_before_s9_8(
    case: str,
    expected_detail: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _s9_7_reconciliation_defect(case)
    run = replace(run, decision_cost=run.decision_cost + 0.125)
    later_calls: list[str] = []
    original_same_f64 = returned._same_f64

    def same_f64(left: float, right: float, path: str) -> bool:
        if path.startswith("returned_run.S9.8"):
            later_calls.append(path)
        return original_same_f64(left, right, path)

    monkeypatch.setattr(returned, "_same_f64", same_f64)
    ledger = _scientific_call_ledger(monkeypatch)

    _failure(
        partial(returned._validate_returned_run_s9, run),
        category="scientific_record_invalid",
        path="returned_run.S9.7",
    )

    assert ledger == [("returned_run.S9.7", expected_detail)]
    assert later_calls == []


def test_s9_6_fault_precedes_a_compound_s9_7_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run("calibrated_ig")
    calibration = cast(Any, run.calibration)
    changed = replace(
        calibration,
        effects=tuple(reversed(calibration.effects)),
        observations=tuple(reversed(calibration.observations)),
    )
    ledger = _scientific_call_ledger(monkeypatch)

    _failure(
        partial(returned._validate_returned_run_s9, replace(run, calibration=changed)),
        category="scientific_record_invalid",
        path="returned_run.S9.6",
    )

    assert ledger == [("returned_run.S9.6", "effect history order or cardinality differs")]


def _s10_record_defect(stage: str, run: BroaderArmRun) -> BroaderArmRun:
    if stage == "S10.1":
        experiment = run.completed_experiments[0]
        candidate = replace(
            experiment.candidate,
            model_width=experiment.candidate.model_width + 1,
        )
        changed = replace(experiment, candidate=candidate)
        return replace(run, completed_experiments=(changed, *run.completed_experiments[1:]))
    if stage == "S10.2":
        experiment = run.completed_experiments[0]
        changed = replace(experiment, record_id=experiment.record_id + 10_000)
        return replace(run, completed_experiments=(changed, *run.completed_experiments[1:]))
    if stage == "S10.3":
        lineage = replace(run.lineage, created_at=f"{run.lineage.created_at}/distinct")
        return replace(run, lineage=lineage)
    if stage == "S10.6":
        return replace(run, evidence=run.evidence[:-1])
    assert stage == "S10.7"
    update = run.updates[0]
    diagnostic = replace(
        update.diagnostic,
        diagnostic_id=f"{update.diagnostic.diagnostic_id}/distinct",
    )
    changed_update = replace(update, diagnostic=diagnostic)
    return replace(run, updates=(changed_update, *run.updates[1:]))


@pytest.mark.parametrize(
    ("stage", "expected_path", "expected_detail"),
    [
        ("S10.1", "returned_run.S10.1", "candidate registry relation differs"),
        ("S10.2", "returned_run.S10.2", "experiment identity differs"),
        ("S10.3", "returned_run.S10.3", "initial lineage differs"),
        ("S10.4", "returned_run.S10.4", "S10.4 binding sentinel"),
        ("S10.5", "returned_run.S10.5", "S10.5 eligibility sentinel"),
        ("S10.6", "returned_run.S10.6", "eligible evidence cardinality differs"),
        (
            "S10.7",
            "returned_run.S10.7.updates[0]",
            "diagnostic differs",
        ),
        ("S10.8", "returned_run.S10.8", "S10.8 final-lineage sentinel"),
    ],
)
def test_s10_1_through_s10_8_fail_before_invalid_s10_11(
    stage: str,
    expected_path: str,
    expected_detail: str,
    fixed_run: BroaderArmRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = replace(fixed_run, comparison_id="comparison:later-invalid")
    if stage in {"S10.1", "S10.2", "S10.3", "S10.6", "S10.7"}:
        run = _s10_record_defect(stage, run)
    elif stage == "S10.4":

        def reject_initial_binding(**_kwargs: object) -> NoReturn:
            raise ValueError("S10.4 binding sentinel")

        monkeypatch.setattr(returned, "validate_lineage_binding", reject_initial_binding)
    elif stage == "S10.5":

        class EligibilityProxy:
            def valid_unapplied_pairs(self, *_args: object, **_kwargs: object) -> NoReturn:
                raise ValueError("S10.5 eligibility sentinel")

        monkeypatch.setattr(
            returned,
            "evidence_eligibility_contract",
            lambda: cast(Any, EligibilityProxy()),
        )
    else:
        assert stage == "S10.8"

        def reject_recorded_final_binding(**kwargs: object) -> None:
            if kwargs["lineage"] is run.lineage:
                raise ValueError("S10.8 final-lineage sentinel")
            validate_lineage_binding(**cast(Any, kwargs))

        monkeypatch.setattr(
            returned,
            "validate_lineage_binding",
            reject_recorded_final_binding,
        )

    later_calls: list[str] = []

    def forbidden_comparison_identity(**_kwargs: object) -> NoReturn:
        later_calls.append("S10.11")
        raise AssertionError("S10.11 ran after an earlier invalid predicate")

    monkeypatch.setattr(returned, "comparison_identity", forbidden_comparison_identity)
    ledger = _scientific_call_ledger(monkeypatch)

    _failure(
        partial(returned._validate_returned_run_s10, run),
        category="scientific_record_invalid",
        path=expected_path,
    )

    assert ledger == [(expected_path, expected_detail)]
    assert later_calls == []


def test_s10_10_failure_stops_invalid_s10_11(
    fixed_run: BroaderArmRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = replace(fixed_run, comparison_id="comparison:later-invalid")
    wrong_run_id = "run:" + ("0" * 64 if run.run_id != "run:" + "0" * 64 else "1" * 64)
    later_calls: list[str] = []

    monkeypatch.setattr(returned, "run_identity", lambda **_kwargs: wrong_run_id)

    def forbidden_comparison_identity(**_kwargs: object) -> NoReturn:
        later_calls.append("S10.11")
        raise AssertionError("S10.11 ran after invalid S10.10")

    monkeypatch.setattr(returned, "comparison_identity", forbidden_comparison_identity)
    ledger = _scientific_call_ledger(monkeypatch)

    _failure(
        partial(returned._validate_returned_run_s10, run),
        category="scientific_record_invalid",
        path="returned_run.S10.10",
    )

    assert ledger == [("returned_run.S10.10", "run identity differs")]
    assert later_calls == []


def test_s10_9_invokes_the_pure_selector_replay_once_per_calibration_group(
    calibrated_run: BroaderArmRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = selector_replay
    calls: list[dict[str, object]] = []
    digest_calls: list[object] = []

    def replay(**kwargs: Any) -> Any:
        calls.append(dict(kwargs))
        return original(**kwargs)

    def digest(effect: object) -> str:
        digest_calls.append(effect)
        return raw_effect_sha256(cast(Any, effect))

    monkeypatch.setattr(returned, "replay_calibration_history_selection", replay)
    monkeypatch.setattr(returned, "raw_effect_sha256", digest)

    effects = returned._s10_calibration_effects(calibrated_run)
    calibration = calibrated_run.calibration
    assert calibration is not None
    assert effects == calibration.effects
    assert [item["comparison_group_id"] for item in calls] == list(GROUP_IDS)
    assert [item["group_index"] for item in calls] == list(range(len(GROUP_IDS)))
    assert [item["recorded_observations"] for item in calls] == [
        estimate.observations for estimate in calibration.estimates
    ]
    assert all(item["recorded_effects"] == calibrated_run.effect_history for item in calls)
    assert all(item["run_id"] == calibrated_run.run_id for item in calls)
    assert tuple(digest_calls) == calibration.effects


def test_s10_9_fixed_arm_never_enters_calibration_selector_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(**_kwargs: Any) -> Any:
        raise AssertionError("fixed arm entered calibration selector replay")

    monkeypatch.setattr(returned, "replay_calibration_history_selection", forbidden)

    assert returned._s10_calibration_effects(_run("fixed_ig")) == ()


@pytest.mark.parametrize("case", ["selected_history", "raw_digest_provenance"])
def test_s10_9_rejects_recorded_selector_source_mismatches(case: str) -> None:
    run = _run("calibrated_ig")
    projection = returned.project_returned_run(run)
    calibration = cast(returned.RunCalibrationProjection, projection.calibration)
    estimate = calibration.estimates[0]
    if case == "selected_history":
        reordered_effects = tuple(reversed(estimate.effects))
        changed = replace(
            estimate,
            source_effect_ids=tuple(item.effect_id for item in reordered_effects),
            effects=reordered_effects,
        )
        deployment_effects = (*reordered_effects, *calibration.effects[len(reordered_effects) :])
        changed_calibration = replace(
            calibration,
            effects=deployment_effects,
            estimates=(changed, *calibration.estimates[1:]),
        )
        projection = replace(
            projection,
            calibration=changed_calibration,
            effect_history=deployment_effects,
        )
    else:
        assert case == "raw_digest_provenance"
        changed = replace(estimate, provenance_sha256="0" * 64)
        projection = replace(
            projection,
            calibration=replace(
                calibration,
                estimates=(changed, *calibration.estimates[1:]),
            ),
        )

    _failure(
        partial(returned.reconstruct_returned_run, projection),
        category="scientific_record_invalid",
        path_prefix="returned_run.S10.9",
    )


@pytest.mark.parametrize("case", ["malformed", "wrong_h64", "cross_group_duplicate"])
def test_s10_9_rejects_invalid_selector_protocol_hash_results(
    case: str,
    calibrated_run: BroaderArmRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = selector_replay
    first_identity: list[str] = []

    def replay(**kwargs: Any) -> Any:
        selection = original(**kwargs)
        group_index = cast(int, kwargs["group_index"])
        if case == "malformed" and group_index == 0:
            return replace(selection, selection_identity="not-lowercase-h64")
        if case == "wrong_h64" and group_index == 0:
            return replace(selection, selection_identity="f" * 64)
        if group_index == 0:
            first_identity.append(selection.selection_identity)
        if case == "cross_group_duplicate" and group_index == 1:
            return replace(selection, selection_identity=first_identity[0])
        return selection

    monkeypatch.setattr(returned, "replay_calibration_history_selection", replay)

    _failure(
        partial(returned._s10_calibration_effects, calibrated_run),
        category="scientific_record_invalid",
        path_prefix="returned_run.S10.9",
    )


def test_s10_9_rejects_a_well_formed_wrong_raw_digest_sequence(
    calibrated_run: BroaderArmRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = selector_replay

    def replay(**kwargs: Any) -> Any:
        selection = original(**kwargs)
        if cast(int, kwargs["group_index"]) != 0:
            return selection
        replacement = "0" * 64
        if replacement == selection.source_effect_payload_sha256[0]:
            replacement = "1" * 64
        return replace(
            selection,
            source_effect_payload_sha256=(
                replacement,
                *selection.source_effect_payload_sha256[1:],
            ),
        )

    monkeypatch.setattr(returned, "replay_calibration_history_selection", replay)

    _failure(
        partial(returned._s10_calibration_effects, calibrated_run),
        category="scientific_record_invalid",
        path_prefix="returned_run.S10.9",
    )


@pytest.mark.parametrize(
    "case",
    [
        "selected_effect_order",
        "one_digest_changed",
        "digest_reordered",
        "digest_duplicated",
        "digest_count_changed",
        "digest_case_changed",
        "digest_without_final_lf",
        "protocol_hash_substitute",
        "correct_digests_wrong_identity",
    ],
)
def test_s10_9_rejects_each_selector_effect_content_mutation(
    case: str,
    calibrated_run: BroaderArmRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = selector_replay

    def replay(**kwargs: Any) -> Any:
        selection = original(**kwargs)
        if cast(int, kwargs["group_index"]) != 0:
            return selection
        digests = selection.source_effect_payload_sha256
        if case == "selected_effect_order":
            reordered_effects = tuple(reversed(selection.effects))
            assert reordered_effects != selection.effects
            return replace(selection, effects=reordered_effects)
        if case == "one_digest_changed":
            replacement = "0" * 64 if digests[0] != "0" * 64 else "1" * 64
            return replace(
                selection,
                source_effect_payload_sha256=(replacement, *digests[1:]),
            )
        if case == "digest_reordered":
            reordered_digests = tuple(reversed(digests))
            assert reordered_digests != digests
            return replace(selection, source_effect_payload_sha256=reordered_digests)
        if case == "digest_duplicated":
            assert len(digests) > 1 and digests[0] != digests[1]
            return replace(
                selection,
                source_effect_payload_sha256=(digests[0], digests[0], *digests[2:]),
            )
        if case == "digest_count_changed":
            return replace(selection, source_effect_payload_sha256=digests[:-1])
        if case == "digest_case_changed":
            uppercase_digest = digests[0].upper()
            assert uppercase_digest != digests[0]
            return replace(
                selection,
                source_effect_payload_sha256=(uppercase_digest, *digests[1:]),
            )
        if case == "digest_without_final_lf":
            without_final_lf = hashlib.sha256(
                canonical_json_bytes(selection.effects[0].to_dict(), final_lf=False)
            ).hexdigest()
            assert without_final_lf != digests[0]
            return replace(
                selection,
                source_effect_payload_sha256=(without_final_lf, *digests[1:]),
            )
        if case == "protocol_hash_substitute":
            framed_digest = protocol_hash(
                "calibration-effect-test-substitute/v1",
                selection.effects[0].to_dict(),
            )
            assert framed_digest != digests[0]
            return replace(
                selection,
                source_effect_payload_sha256=(framed_digest, *digests[1:]),
            )
        assert case == "correct_digests_wrong_identity"
        wrong_identity = "f" * 64 if selection.selection_identity != "f" * 64 else "e" * 64
        return replace(selection, selection_identity=wrong_identity)

    monkeypatch.setattr(returned, "replay_calibration_history_selection", replay)

    _failure(
        partial(returned._s10_calibration_effects, calibrated_run),
        category="scientific_record_invalid",
        path_prefix="returned_run.S10.9",
    )


def test_s10_9_rejects_coherent_forged_digests_before_later_checks_or_effects(
    calibrated_run: BroaderArmRun,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original = selector_replay
    forged_selection_seen = False
    later_events: list[str] = []

    def replay(**kwargs: Any) -> Any:
        nonlocal forged_selection_seen
        selection = original(**kwargs)
        if cast(int, kwargs["group_index"]) != 0:
            return selection
        independent_digests = tuple(raw_effect_sha256(item) for item in selection.effects)
        assert independent_digests == selection.source_effect_payload_sha256
        replacement = "0" * 64 if independent_digests[0] != "0" * 64 else "1" * 64
        forged_digests = (replacement, *independent_digests[1:])
        forged_identity = _selection_identity_with_digests(selection, forged_digests)
        assert len(forged_digests) == len(selection.effects) == selection.sample_count
        assert all(
            len(item) == 64 and all(character in "0123456789abcdef" for character in item)
            for item in forged_digests
        )
        assert forged_digests != independent_digests
        assert forged_identity != selection.selection_identity
        assert forged_identity == _selection_identity_with_digests(selection, forged_digests)
        forged_selection_seen = True
        return replace(
            selection,
            source_effect_payload_sha256=forged_digests,
            selection_identity=forged_identity,
        )

    def forbidden_later(name: str) -> Callable[..., object]:
        def forbidden(*_args: object, **_kwargs: object) -> object:
            later_events.append(name)
            raise AssertionError(f"{name} ran after an invalid selector digest")

        return forbidden

    monkeypatch.setattr(returned, "replay_calibration_history_selection", replay)
    monkeypatch.setattr(returned, "_decide", forbidden_later("recommendation"))
    monkeypatch.setattr(returned, "run_identity", forbidden_later("S10.10"))
    monkeypatch.setattr(returned, "comparison_identity", forbidden_later("S10.11"))
    ledger = _scientific_call_ledger(monkeypatch)
    observable_before = _observable_state_snapshot()
    run_projection_before = returned.projection_as_dict(
        returned.project_returned_run(calibrated_run)
    )
    tree_before = _tree_snapshot(tmp_path)
    evidence_root = tmp_path / "evidence"
    output_root = tmp_path / "scientific-output"
    assert not evidence_root.exists()
    assert not output_root.exists()

    _failure(
        partial(returned._validate_returned_run_s10, calibrated_run),
        category="scientific_record_invalid",
        path_prefix="returned_run.S10.9",
    )

    assert forged_selection_seen
    assert ledger == [
        (
            "returned_run.S10.9.calibration[0].selector",
            "calibration selector replay differs",
        )
    ]
    assert later_events == []
    assert _observable_state_snapshot() == observable_before
    assert (
        returned.projection_as_dict(returned.project_returned_run(calibrated_run))
        == run_projection_before
    )
    assert _tree_snapshot(tmp_path) == tree_before
    assert not evidence_root.exists()
    assert not output_root.exists()


def test_s10_8_validates_each_temporary_lineage_before_the_next_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _multi_update_run()
    assert len(run.updates) == 2
    events: list[tuple[str, int]] = []
    original_validate = validate_lineage_binding
    model = belief_model(run.arm.belief_model_id)

    class ModelProxy:
        def update(self, **kwargs: Any) -> Any:
            lineage = kwargs["lineage"]
            events.append(("update", lineage.current_state.state.sequence))
            return model.update(**kwargs)

    def validate(**kwargs: Any) -> None:
        lineage = kwargs["lineage"]
        events.append(("validate", lineage.current_state.state.sequence))
        original_validate(**kwargs)

    monkeypatch.setattr(returned, "belief_model", lambda _model_id: cast(Any, ModelProxy()))
    monkeypatch.setattr(returned, "validate_lineage_binding", validate)

    returned._validate_returned_run_s10_updates(run)

    assert events == [
        ("validate", 0),
        ("update", 0),
        ("validate", 1),
        ("update", 1),
        ("validate", 2),
        ("validate", 2),
    ]


def test_s10_runs_replay_before_run_and_comparison_identity(
    fixed_run: BroaderArmRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        returned,
        "_validate_returned_run_s10_updates",
        lambda _run: calls.append("S10.1-S10.8"),
    )
    monkeypatch.setattr(
        returned,
        "_validate_returned_run_s10_replay",
        lambda _run: calls.append("S10.9"),
    )

    def run_identity(**_kwargs: object) -> str:
        calls.append("S10.10")
        return fixed_run.run_id

    def comparison_identity(**_kwargs: object) -> str:
        calls.append("S10.11")
        return fixed_run.comparison_id

    monkeypatch.setattr(returned, "run_identity", run_identity)
    monkeypatch.setattr(returned, "comparison_identity", comparison_identity)

    returned._validate_returned_run_s10(fixed_run)

    assert calls == ["S10.1-S10.8", "S10.9", "S10.10", "S10.11"]


@pytest.mark.parametrize("kind", ["foundational", "calibration"])
def test_nested_failure_precedes_outer_run_reconciliation(kind: str) -> None:
    projection = returned.project_returned_run(
        _run("calibrated_ig") if kind == "calibration" else _run("fixed_lookahead")
    )
    run = _run("calibrated_ig") if kind == "calibration" else _run("fixed_lookahead")
    projection = replace(projection, decision_cost=f64(run.decision_cost + 0.125))
    if kind == "foundational":
        evidence = projection.evidence[0]
        changed = replace(evidence, evidence_id="")
        projection = replace(projection, evidence=(changed, *projection.evidence[1:]))
        path = "evidence"
    else:
        calibration = cast(returned.RunCalibrationProjection, projection.calibration)
        estimate = calibration.estimates[0]
        observation = replace(estimate.observations[0], z="0.125")
        changed_estimate = replace(
            estimate,
            observations=(observation, *estimate.observations[1:]),
        )
        projection = replace(
            projection,
            calibration=replace(
                calibration,
                estimates=(changed_estimate, *calibration.estimates[1:]),
            ),
        )
        path = "returned_run.S6"
    error = _failure(
        partial(returned.reconstruct_returned_run, projection),
        category="scientific_record_invalid",
        path_prefix=path,
    )
    assert not error.path.startswith("returned_run.S9")


def test_architecture_authorizes_exactly_returned_run_for_phase_2d_1b() -> None:
    module_path = Path(returned.__file__ or "")
    source = module_path.read_text(encoding="utf-8")
    classes = architecture.top_level_class_names(source)

    assert architecture.EXPECTED_AUTHORIZED_TOP_LEVEL_CLASS_COUNT == 34
    assert architecture.is_exact_authorized_top_level_class_set(classes)
    assert "ReturnedRunProjection" in classes
    assert all(passed for _name, passed in architecture.current_stage_manifest_regression_checks())
    assert not architecture.is_exact_authorized_top_level_class_set(
        classes | {"RunUnexpectedStage2Projection"}
    )


def test_architecture_rejects_every_stage_2d_2_or_later_projection() -> None:
    later = {
        "ReturnedResultProjection",
        "ExecutionInstanceProjection",
        "ExecutionIdentityProjection",
        "ExecutionStartProjection",
        "SubmittedJobsProjection",
        "WorkerIdentityProjection",
        "ResultBatchProjection",
        "ExecutionCompletionProjection",
        "ReturnedResultsProjection",
        "WorkerResultOrderProjection",
        "ExecutorAttestationProjection",
        "CalibrationCandidatePairProjection",
        "CalibrationSourceObservationProjection",
        "CalibrationSelectionProjection",
    }
    expected = set(architecture.AUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES)

    assert later == architecture.CURRENT_STAGE_UNAUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES
    assert later.isdisjoint(expected)
    for name in sorted(later):
        assert not architecture.is_exact_authorized_top_level_class_set(expected | {name})


def test_payload_source_has_no_authority_workload_evidence_or_reflection_surface() -> None:
    module_path = Path(returned.__file__ or "")
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = architecture.imported_module_roots(source)
    called = architecture.called_function_names(source)

    assert all(passed for _name, passed in architecture.returned_run_architecture_checks(source))
    assert architecture.imports_are_authorized(imported)
    assert architecture.returned_run_path_imports_are_authorized(source)
    assert architecture.imported_names_from_module(
        source,
        "broader_calibration_selector_replay",
    ) == {"raw_effect_sha256", "replay_calibration_history_selection"}
    assert "hashlib" not in architecture.imported_module_leaves(source)
    assert called.isdisjoint(architecture.PERMANENT_FORBIDDEN_CALLS)
    assert architecture.dynamic_projection_class_assignments(source) == set()
    assert all(pattern not in source for pattern in architecture.forbidden_source_or_ast_patterns())
    forbidden_attributes = {
        "issue",
        "execute",
        "persist",
        "write_evidence",
        "recommend",
        "world_authority",
        "selected_only_interface",
        "observe_selected",
        "reobserve_authorized_observation",
        "replay_decisions",
        "validate_recorded_calibration",
    }
    assert {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}.isdisjoint(
        forbidden_attributes
    )
    assert "result_payload_sha256" in source
    assert PAYLOAD_HASH_DOMAIN in source
