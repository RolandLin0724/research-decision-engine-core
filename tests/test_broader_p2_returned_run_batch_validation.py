# ruff: noqa: SIM905

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from functools import cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from research_decision_engine.benchmarks import broader_returned_run as returned
from research_decision_engine.benchmarks.broader_calibration_selector_replay import (
    replay_calibration_history_selection,
)
from research_decision_engine.benchmarks.broader_oracle import ObservationAuthority
from research_decision_engine.benchmarks.broader_protocol import protocol_hash
from research_decision_engine.benchmarks.broader_runner import BroaderArmRun, arm_spec, run_arm
from research_decision_engine.benchmarks.broader_worlds import GROUP_IDS, WORLDS_BY_ID
from tests import p2_returned_run_architecture_guard as architecture

WORLD_ID = "d3_adam"
SEED = 9000
BUDGET_ID = "budget-2.25"
BUDGET = 2.25
PAYLOAD_HASH_DOMAIN = "validation_evidence_returned_run_payload/v1"
STAGES = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10")
STRUCTURAL: returned.ValidationCategory = "structural_projection_invalid"
SCIENTIFIC: returned.ValidationCategory = "scientific_record_invalid"
SCIENCE_CODE = returned.EXECUTION_RETURNED_SCIENTIFIC_RECORD_INVALID
STRUCTURAL_CASES = """projection_container context_container count projection_type
context_type wrong_seed_type empty_run_id wrong_actions_container wrong_schema_version
malformed_context_only malformed_policy_branch""".split()
CONTEXT_CASES = """swapped duplicate cross_world cross_seed cross_comparison cross_budget
cross_calibration cross_oracle""".split()
type Projection = returned.ReturnedRunProjection
type RunPair = tuple[BroaderArmRun, BroaderArmRun]
type Delivery = tuple[RunPair, tuple[Projection, Projection]]
type DataPath = tuple[str | int, ...]
type MP = pytest.MonkeyPatch
type Error = returned.ReturnedRunProjectionError
type ProbeResult = tuple[list[tuple[str, str]], list[str]]
type Check = Callable[[], object]
type Category = returned.ValidationCategory
type Projections = tuple[Projection, ...]
type Contexts = tuple[BroaderArmRun, ...]
type Accepted = tuple[tuple[BroaderArmRun, str], ...]
_MISSING = object()

IDENTIFIER_SPECS = (
    """\
update_id fixed_lookahead updates.0.bayesian_update update_id belief_update
effect_id calibrated_ig effect_history.0 effect_id matched_effect
effect_group calibrated_ig effect_history.0 comparison_group_id matched_effect
suggestion_id fixed_ig decisions.0.policy_trace.projection suggestion_id decision_trace
"""
    "branch_id fixed_lookahead decisions.0.policy_trace.projection.selected.branches.0 "
    "branch_id lookahead_branch\n"
    """\
plan_id fixed_lookahead decisions.0.policy_trace.projection plan_id lookahead_trace
belief_state_id fixed_lookahead decisions.0.policy_trace.projection belief_state_id lookahead_trace
"""
    "candidate_set_fingerprint fixed_lookahead decisions.0.policy_trace.projection "
    "candidate_set_fingerprint lookahead_trace\n"
    "completed_state_fingerprint fixed_lookahead decisions.0.policy_trace.projection "
    "completed_state_fingerprint lookahead_trace\n"
).splitlines()


@cache
def _run(arm_id: str, seed: int = SEED) -> BroaderArmRun:
    world = WORLDS_BY_ID[WORLD_ID]
    return run_arm(
        arm=arm_spec(arm_id),
        world=world.public,
        seed=seed,
        budget_id=BUDGET_ID,
        budget=BUDGET,
        authority=ObservationAuthority(world=world, seed=seed),
    )


@cache
def _projection(arm_id: str) -> Projection:
    return returned.project_returned_run(_run(arm_id))


@cache
def _delivery() -> Delivery:
    runs = (_run("fixed_ig"), _run("fixed_lookahead"))
    projections = tuple(returned.project_returned_run(run) for run in runs)
    return cast(Delivery, (runs, projections))


def _error(call: Check, category: Category, **expected: str | None) -> Error:
    with pytest.raises(returned.ReturnedRunProjectionError) as caught:
        call()
    error = caught.value
    assert error.category == category
    expected_code = SCIENCE_CODE if category == SCIENTIFIC else None
    assert error.failure_code == expected_code
    if (path := expected.get("path")) is not None:
        assert error.path == path
    if (prefix := expected.get("path_prefix")) is not None:
        assert error.path.startswith(prefix)
    if (detail := expected.get("detail")) is not None:
        assert detail in str(error)
    return error


def _diagnostic_signature(call: Check) -> tuple[Category, str | None, str, str]:
    with pytest.raises(returned.ReturnedRunProjectionError) as caught:
        call()
    error = caught.value
    return error.category, error.failure_code, error.path, str(error)


def _batch(projections: Projections, contexts: Contexts | None) -> Accepted:
    return returned.validate_returned_run_batch(
        returned_runs_in_actual_delivery_order=projections,
        returned_domains_in_actual_delivery_order=contexts,
    )


def _batch_error(
    projections: Any,
    contexts: Any,
    category: returned.ValidationCategory,
    **expected: str | None,
) -> Error:
    return _error(
        lambda: _batch(projections, contexts),
        category,
        **expected,
    )


def _science(
    projections: Any,
    contexts: Any,
    path: str,
    detail: str | None = None,
    *,
    prefix: bool = False,
) -> Error:
    return _batch_error(
        projections,
        contexts,
        SCIENTIFIC,
        **{"detail": detail, "path_prefix" if prefix else "path": path},
    )


def _edit(owner: Any, path: DataPath, value: Any = _MISSING, **changes: Any) -> Any:
    if not path:
        return replace(owner, **changes) if value is _MISSING else value
    head, *tail = path
    if isinstance(head, int):
        changed = _edit(owner[head], tuple(tail), value, **changes)
        return (*owner[:head], changed, *owner[head + 1 :])
    return replace(
        owner,
        **{head: _edit(getattr(owner, head), tuple(tail), value, **changes)},
    )


def _duck_arm(run: BroaderArmRun) -> SimpleNamespace:
    fields = ("arm_id", "arm_order", "belief_model_id", "policy_id")
    return SimpleNamespace(**{field: getattr(run.arm, field) for field in fields})


def _probe(
    monkeypatch: MP,
    projections: tuple[Projection, ...],
    runs: tuple[BroaderArmRun, ...],
    *failures: tuple[str, str],
    patch_hash: bool = True,
) -> ProbeResult:
    run_by_id = {run.run_id: run for run in runs}
    assert set(run_by_id) == {projection.run_id for projection in projections}
    calls: list[tuple[str, str]] = []
    hash_calls: list[str] = []

    def reached(stage: str, run_id: str) -> None:
        calls.append((stage, run_id))
        if (stage, run_id) in failures:
            returned._scientific(f"returned_run.{stage}", f"sentinel failure for {run_id}")

    def stage(name: str, result: Callable[[Any], object]) -> Callable[..., object]:
        def invoke(item: Any, *_args: object, **_kwargs: object) -> object:
            reached(name, item.run_id)
            if name in {"S3", "S4", "S5"}:
                assert _args == ({"run_id": item.run_id},)
            return result(item)

        return invoke

    def s7(_cal: object, observations: dict[object, object], _effects: object) -> object:
        run_id = cast(str, observations["run_id"])
        reached("S7", run_id)
        return run_by_id[run_id].calibration

    stages: dict[str, tuple[str, Callable[[Any], object]]] = {
        "S1": ("validate", lambda _p: None),
        "S2": ("construct", lambda p: ({"run_id": p.run_id}, (), ())),
        "S3": ("construct", lambda p: (run_by_id[p.run_id].lineage, (), (), (), {})),
        "S4": ("construct", lambda _p: None),
        "S5": ("construct", lambda _p: {}),
        "S6": ("validate", lambda p: {"run_id": p.run_id}),
        "S8": ("construct", lambda p: run_by_id[p.run_id]),
        "S9": ("validate", lambda _p: None),
        "S10": ("validate", lambda _p: None),
    }
    for name, (verb, result) in stages.items():
        monkeypatch.setattr(returned, f"_{verb}_returned_run_{name.lower()}", stage(name, result))
    monkeypatch.setattr(returned, "_construct_returned_run_s7", s7)
    if patch_hash:

        def accepted_hash(projection: Projection) -> str:
            hash_calls.append(projection.run_id)
            calls.append(("H", projection.run_id))
            return f"payload-hash/{projection.run_id}"

        monkeypatch.setattr(returned, "_accepted_result_payload_sha256", accepted_hash)
    return calls, hash_calls


@pytest.mark.parametrize("case", ["empty", "single", "repeated", "missing_context"])
def test_batch_basics(case: str, monkeypatch: MP) -> None:
    if case == "empty":
        assert _batch((), ()) == ()
        return
    if case == "repeated":
        runs, projections = _delivery()
        _probe(monkeypatch, projections, runs)
        assert _batch(projections, runs) == _batch(projections, runs)
        return
    run = _run("fixed_ig")
    projection = _projection("fixed_ig")
    if case == "single":
        expected_hash = returned.result_payload_sha256(projection)
        assert _batch((projection,), (run,)) == ((run, expected_hash),)
        return
    calls, hash_calls = _probe(monkeypatch, (projection,), (run,))
    category: Category = "missing_relation_context"
    detail = "enclosing relation context is required"
    _batch_error((projection,), None, category, path="returned_run", detail=detail)
    assert calls == [(stage, run.run_id) for stage in STAGES]
    assert hash_calls == []


@pytest.mark.parametrize("case", ["missing", "extra", "wrong_primitive"])
def test_raw_returned_run_schema_faults_remain_structural(case: str) -> None:
    raw = returned.projection_as_dict(_projection("fixed_ig"))
    if case == "missing":
        del raw["run_id"]
    elif case == "extra":
        raw["unexpected"] = "value"
    else:
        raw["seed"] = True
    _error(lambda: returned.decode_returned_run_projection(raw), STRUCTURAL)


def _structural_case(case: str) -> tuple[Any, Any]:
    run = _run("fixed_ig")
    projection = _projection("fixed_ig")
    simple: dict[str, tuple[Any, Any]] = {
        "projection_container": ([projection], (run,)),
        "context_container": ((projection,), [run]),
        "count": ((projection,), ()),
        "projection_type": ((object(),), (run,)),
        "context_type": ((projection,), (object(),)),
    }
    if case in simple:
        return simple[case]
    if case == "wrong_seed_type":
        return (
            (replace(projection, seed=cast(Any, True)),),
            (replace(run, seed=cast(Any, True)),),
        )
    if case == "empty_run_id":
        return (replace(projection, run_id=""),), (run,)
    if case == "wrong_schema_version":
        version = cast(Any, "broader-replication-returned-run/v2")
        return (replace(projection, schema_version=version),), (run,)
    policy = replace(projection.decisions[0].policy_trace, kind="lookahead_plan_trace")
    if case == "malformed_policy_branch":
        return (_edit(projection, ("decisions", 0), policy_trace=policy),), (run,)
    if case == "wrong_actions_container":
        changed = _edit(projection, ("decisions", 0), policy_trace=policy)
        changed = replace(changed, actions=cast(Any, list(projection.actions)), schema_version=2)
        return (changed,), (replace(run, actions=cast(Any, list(run.actions))),)
    if case == "malformed_context_only":
        changed = replace(
            run,
            actions=cast(Any, list(run.actions)),
            arm=cast(Any, _duck_arm(run)),
            calibration=cast(Any, object()),
        )
        return (projection,), (changed,)
    raise AssertionError(f"unknown structural case: {case}")


def _nested_structure(projection: Projection, run: BroaderArmRun) -> None:
    calibrated = _run("calibrated_ig")
    calibrated_projection = _projection("calibrated_ig")
    assert calibrated.calibration is not None
    malformed_calibration = _edit(
        calibrated.calibration, ("estimates", 0, "observations", 0), object()
    )
    bad_role_projection = _edit(projection, ("actions", 0), role="")
    bad_role_context = _edit(run, ("actions", 0), role="")
    bad_source_projection = _edit(
        calibrated_projection, ("effect_history", 0), source_kind="e\u0301"
    )
    bad_source_context = _edit(calibrated, ("effect_history", 0), source_kind="e\u0301")
    bad_calibration = replace(calibrated, calibration=malformed_calibration)
    cases = (
        (bad_role_projection, bad_role_context, "arm_action.role"),
        (projection, replace(run, arm=cast(Any, _duck_arm(run))), "returned_run.arm"),
        (projection, _edit(run, ("actions", 0), object()), "arm_action"),
        (bad_source_projection, bad_source_context, "matched_effect.source_kind"),
        (calibrated_projection, bad_calibration, "revealed_observation"),
    )
    for candidate, context, path in cases:
        _batch_error((candidate,), (context,), STRUCTURAL, path=path)


@pytest.mark.parametrize("case", STRUCTURAL_CASES)
def test_structural_faults_never_enter_s1(case: str, monkeypatch: MP) -> None:
    valid_run = _run("fixed_ig")
    valid_projection = _projection("fixed_ig")
    calls, hash_calls = _probe(monkeypatch, (valid_projection,), (valid_run,))
    projections, contexts = _structural_case(case)
    paths = {
        "wrong_actions_container": "returned_run.actions",
        "empty_run_id": "returned_run.run_id",
        "wrong_schema_version": "returned_run.schema_version",
        "malformed_context_only": "returned_run.actions",
        "malformed_policy_branch": "policy_trace.projection",
    }
    path = paths.get(case)
    detail = "tag and projection type do not match" if case.endswith("policy_branch") else None
    _batch_error(projections, contexts, STRUCTURAL, path=path, detail=detail)
    if case == "empty_run_id":
        _nested_structure(valid_projection, valid_run)
    assert calls == []
    assert hash_calls == []


@pytest.mark.parametrize("stage", STAGES)
def test_one_payload_batch_preserves_each_stage_failure_exactly(
    stage: str,
    monkeypatch: MP,
) -> None:
    run = _run("fixed_ig")
    projection = _projection("fixed_ig")
    calls, hash_calls = _probe(monkeypatch, (projection,), (run,), (stage, run.run_id))
    detail = f"sentinel failure for {run.run_id}"
    _science((projection,), (run,), f"returned_run.{stage}", detail)
    expected = [(item, run.run_id) for item in STAGES[: STAGES.index(stage) + 1]]
    assert calls == expected
    assert hash_calls == []


@pytest.mark.parametrize(
    ("case", "expected_path"),
    [(spec.split()[0], spec.split()[-1]) for spec in IDENTIFIER_SPECS],
)
def test_blank_stage_identifiers_are_scientific(case: str, expected_path: str) -> None:
    spec = next(item for item in IDENTIFIER_SPECS if item.startswith(f"{case} "))
    _, arm_id, raw_path, field, _ = spec.split()
    path = tuple(int(part) if part.isdigit() else part for part in raw_path.split("."))
    projection = _edit(_projection(arm_id), path, **{field: " "})
    returned._validate_returned_run_projection_structure(projection)
    _error(
        lambda: returned.reconstruct_returned_run(projection),
        SCIENTIFIC,
        path=expected_path,
    )


def test_blocked_actual_delivery_reproduction_is_stage_major(monkeypatch: MP) -> None:
    runs, projections = _delivery()
    calls, hash_calls = _probe(monkeypatch, projections, runs)
    result = _batch(projections, runs)
    assert calls == [
        *((stage, run.run_id) for stage in STAGES for run in runs),
        *(("H", run.run_id) for run in runs),
    ]
    assert hash_calls == [run.run_id for run in runs]
    assert tuple(run for run, _ in result) == runs


@pytest.mark.parametrize(
    ("earlier_stage", "later_stage"),
    [("S1", "S10"), ("S2", "S9")],
)
def test_earlier_stage_on_later_payload_beats_later_stage_on_earlier_payload(
    earlier_stage: str,
    later_stage: str,
    monkeypatch: MP,
) -> None:
    runs, projections = _delivery()
    first, second = runs
    calls, hash_calls = _probe(
        monkeypatch,
        projections,
        runs,
        (later_stage, first.run_id),
        (earlier_stage, second.run_id),
    )
    _science(projections, runs, f"returned_runs[1].returned_run.{earlier_stage}")
    assert calls == [
        (stage, run.run_id) for stage in STAGES[: STAGES.index(earlier_stage) + 1] for run in runs
    ]
    assert hash_calls == []


def test_three_payload_faults_use_stage_then_delivery_order(monkeypatch: MP) -> None:
    runs = (
        _run("fixed_ig"),
        _run("fixed_lookahead"),
        _run("fixed_ig", seed=SEED + 1),
    )
    projections = tuple(returned.project_returned_run(run) for run in runs)
    calls, hash_calls = _probe(
        monkeypatch,
        projections,
        runs,
        ("S8", runs[0].run_id),
        ("S3", runs[1].run_id),
        ("S5", runs[2].run_id),
    )

    _science(projections, runs, "returned_runs[1].returned_run.S3")
    assert calls[-1] == ("S3", runs[1].run_id)
    assert ("S3", runs[2].run_id) not in calls
    assert hash_calls == []


@pytest.mark.parametrize("reverse", [False, True], ids=["original", "reversed"])
def test_same_stage_failure_follows_delivery_order(reverse: bool, monkeypatch: MP) -> None:
    original_runs, original_projections = _delivery()
    runs = original_runs[::-1] if reverse else original_runs
    projections = original_projections[::-1] if reverse else original_projections
    failures = tuple(("S4", run.run_id) for run in runs)
    calls, hash_calls = _probe(monkeypatch, projections, runs, *failures)
    error = _science(projections, runs, "returned_runs[0].returned_run.S4")
    assert runs[0].run_id in str(error)
    assert calls[-1] == ("S4", runs[0].run_id)
    assert ("S4", runs[1].run_id) not in calls
    assert hash_calls == []


def test_later_structure_beats_earlier_science(monkeypatch: MP) -> None:
    runs, projections = _delivery()
    first, second = runs
    calls, hash_calls = _probe(monkeypatch, projections, runs, ("S1", first.run_id))
    malformed = cast(Projection, object())
    _batch_error(
        (projections[0], malformed),
        (replace(first, world_id="h_adam_low"), second),
        STRUCTURAL,
        path="returned_runs[1].projection",
    )
    assert calls == []
    assert hash_calls == []


def test_aligned_action_step_zero_reaches_s1(monkeypatch: MP) -> None:
    (first_run, second_run), (first_projection, second_projection) = _delivery()
    aligned_run = _edit(first_run, ("actions", 0), step=0)
    aligned_projection = _edit(first_projection, ("actions", 0), step=0)
    monkeypatch.setattr(
        returned,
        "_construct_returned_run_s2",
        lambda *_args, **_kwargs: pytest.fail("S2 ran after the aligned S1 fault"),
    )
    monkeypatch.setattr(
        returned,
        "_accepted_result_payload_sha256",
        lambda *_args, **_kwargs: pytest.fail("hash ran after the aligned S1 fault"),
    )

    args = ((aligned_projection, second_projection), (aligned_run, second_run))
    _science(
        *args,
        "returned_runs[0].returned_run.S1.numeric.actions[0]",
        "action scalar domain differs",
    )
    _science(
        (aligned_projection,),
        None,
        "returned_run.S1.numeric.actions[0]",
        "action scalar domain differs",
    )


def test_aligned_invalid_enum_reaches_science(monkeypatch: MP) -> None:
    run = _run("calibrated_ig")
    projection = _projection("calibrated_ig")
    assert run.calibration is not None
    assert projection.calibration is not None
    calibration_observation = ("calibration", "observations", 0)
    aligned_calibration_run = _edit(
        run, calibration_observation, comparison_group_id="unknown-group"
    )
    aligned_calibration_projection = _edit(
        projection, calibration_observation, comparison_group_id="unknown-group"
    )
    monkeypatch.setattr(
        returned,
        "_construct_returned_run_s7_stage",
        lambda *_args, **_kwargs: pytest.fail("S7 ran after the aligned S6 fault"),
    )
    args = ((aligned_calibration_projection,), (aligned_calibration_run,))
    _science(
        *args,
        "revealed_observation.key_fields.comparison_group_id",
        "Oracle key fact differs from the revealed record",
    )

    effect = ("effect_history", 0)
    aligned_run = _edit(run, effect, source_kind="unknown")
    aligned_projection = _edit(projection, effect, source_kind="unknown")
    monkeypatch.setattr(
        returned,
        "_construct_returned_run_s2",
        lambda *_args, **_kwargs: pytest.fail("S2 ran after the aligned S1 enum fault"),
    )

    args = ((aligned_projection,), (aligned_run,))
    _science(
        *args,
        "returned_run.S1.enums.effects[",
        "unknown effect source kind",
        prefix=True,
    )


def _context_case(case: str, runs: RunPair) -> tuple[RunPair, int]:
    first, second = runs
    if case == "swapped":
        return (second, first), 0
    if case == "duplicate":
        return (first, first), 1
    changes: dict[str, dict[str, object]] = {
        "cross_world": {"world_id": "h_adam_low"},
        "cross_seed": {"seed": SEED + 1},
        "cross_comparison": {"comparison_id": f"{second.comparison_id}/cross"},
        "cross_budget": {"budget": second.budget + 0.25},
    }
    if case in changes:
        return (first, replace(second, **cast(Any, changes[case]))), 1
    if case == "cross_calibration":
        calibrated = _run("calibrated_ig")
        assert calibrated.calibration is not None
        changed = replace(
            second,
            calibration=calibrated.calibration,
            calibration_cost=calibrated.calibration_cost,
        )
        return (first, changed), 1
    if case == "cross_oracle":
        index = next(
            i for i, action in enumerate(second.actions) if action.oracle_observation is not None
        )
        observation = second.actions[index].oracle_observation
        assert observation is not None
        zeros = "0" * 64
        changed = _edit(
            second,
            ("actions", index, "oracle_observation"),
            digest=zeros if observation.digest != zeros else "1" * 64,
        )
        return (first, changed), 1
    raise AssertionError(f"unknown context case: {case}")


@pytest.mark.parametrize("case", CONTEXT_CASES)
def test_contexts_are_payload_local(case: str, monkeypatch: MP) -> None:
    runs, projections = _delivery()
    contexts, failure_index = _context_case(case, runs)
    calls, hash_calls = _probe(monkeypatch, projections, runs)
    path = f"returned_runs[{failure_index}].returned_run"
    _science(projections, contexts, path, "enclosing returned-run relation differs")
    assert calls == [(stage, run.run_id) for stage in STAGES for run in runs]
    assert hash_calls == []


def test_none_context_failure_precedence_is_stage_major(monkeypatch: MP) -> None:
    _batch_error(
        (),
        None,
        "missing_relation_context",
        path="returned_run",
        detail="enclosing relation context is required",
    )

    runs, projections = _delivery()
    first, second = runs
    with monkeypatch.context() as patch:
        calls, hash_calls = _probe(
            patch,
            projections,
            runs,
            ("S9", first.run_id),
            ("S1", second.run_id),
        )
        _science(projections, None, "returned_runs[1].returned_run.S1")
        assert calls == [("S1", first.run_id), ("S1", second.run_id)]
        assert ("S9", first.run_id) not in calls
        assert hash_calls == []

    with monkeypatch.context() as patch:
        calls, hash_calls = _probe(patch, projections, runs)
        _batch_error(
            projections,
            None,
            "missing_relation_context",
            path="returned_runs[0].returned_run",
            detail="enclosing relation context is required",
        )
        assert calls == [(stage, run.run_id) for stage in STAGES for run in runs]
        assert hash_calls == []

    run = _run("fixed_ig")
    projection = _projection("fixed_ig")
    with monkeypatch.context() as patch:
        calls, hash_calls = _probe(patch, (projection,), (run,))
        malformed = cast(Projection, object())
        _batch_error((malformed,), None, STRUCTURAL, path="projection")
        assert calls == []
        assert hash_calls == []


def test_supplied_relation_fault_does_not_preempt_s1(monkeypatch: MP) -> None:
    run = _run("fixed_ig")
    projection = _projection("fixed_ig")
    invalid_context = replace(run, world_id="h_adam_low")
    calls, hash_calls = _probe(
        monkeypatch,
        (projection,),
        (run,),
        ("S1", run.run_id),
    )

    _science(
        (projection,),
        (invalid_context,),
        "returned_run.S1",
        f"sentinel failure for {run.run_id}",
    )
    assert calls == [("S1", run.run_id)]
    assert hash_calls == []


def test_single_payload_batch_matches_approved_context_diagnostics() -> None:
    run = _run("fixed_ig")
    projection = _projection("fixed_ig")

    missing = _diagnostic_signature(lambda: returned.validate_returned_run_relation(projection))
    assert _diagnostic_signature(lambda: _batch((projection,), None)) == missing
    assert _diagnostic_signature(lambda: _batch((projection,), None)) == missing

    malformed = cast(Projection, object())
    structural = _diagnostic_signature(lambda: returned.validate_returned_run_relation(malformed))
    assert _diagnostic_signature(lambda: _batch((malformed,), None)) == structural

    aligned_s1 = _edit(projection, ("actions", 0), step=0)
    scientific = _diagnostic_signature(lambda: returned.validate_returned_run_relation(aligned_s1))
    assert _diagnostic_signature(lambda: _batch((aligned_s1,), None)) == scientific

    invalid_context = replace(run, world_id="h_adam_low")
    relation = _diagnostic_signature(
        lambda: returned.validate_returned_run_relation(
            projection,
            expected_run=invalid_context,
        )
    )
    assert _diagnostic_signature(lambda: _batch((projection,), (invalid_context,))) == relation


def test_single_payload_none_stage_faults_match_approved_api(monkeypatch: MP) -> None:
    run = _run("fixed_ig")
    projection = _projection("fixed_ig")
    for stage in ("S2", "S5", "S10"):
        with monkeypatch.context() as patch:
            calls, hash_calls = _probe(
                patch,
                (projection,),
                (run,),
                (stage, run.run_id),
            )
            single = _diagnostic_signature(
                lambda: returned.validate_returned_run_relation(projection)
            )
            expected_calls = [(item, run.run_id) for item in STAGES[: STAGES.index(stage) + 1]]
            assert calls == expected_calls
            assert hash_calls == []

            calls.clear()
            batch = _diagnostic_signature(lambda: _batch((projection,), None))
            assert batch == single
            assert calls == expected_calls
            assert hash_calls == []


def test_real_oracle_and_selector_state_is_payload_local(monkeypatch: MP) -> None:
    runs = (_run("calibrated_ig"), _run("fixed_lookahead"))
    projections = tuple(returned.project_returned_run(run) for run in runs)
    original_observation = returned._pure_revealed_observation
    original_replay = replay_calibration_history_selection
    observation_run_ids: list[str] = []
    selector_run_ids: list[str] = []

    def recording(target: Callable[..., object], seen: list[str]) -> Callable[..., object]:
        def invoke(*args: object, **kwargs: object) -> object:
            seen.append(cast(str, kwargs["run_id"]))
            return target(*args, **cast(Any, kwargs))

        return invoke

    observe = recording(original_observation, observation_run_ids)
    replay = recording(original_replay, selector_run_ids)
    monkeypatch.setattr(returned, "_pure_revealed_observation", observe)
    monkeypatch.setattr(returned, "replay_calibration_history_selection", replay)
    accepted = _batch(projections, runs)
    assert tuple(run for run, _payload_hash in accepted) == runs
    observation_contexts = returned._returned_observation_contexts
    expected_ids = [p.run_id for p in projections for _ in observation_contexts(p)]
    assert observation_run_ids == expected_ids
    assert selector_run_ids == [projections[0].run_id] * len(GROUP_IDS)


@pytest.mark.parametrize("case", ["single", "reordered", "mutated", "failed"])
def test_payload_hash_contracts(case: str, monkeypatch: MP) -> None:
    if case == "single":
        run = _run("fixed_ig")
        projection = _projection("fixed_ig")
        _probe(monkeypatch, (projection,), (run,), patch_hash=False)
        batch_hash = _batch((projection,), (run,))[0][1]
        single_hash = returned.result_payload_sha256(projection)
        assert batch_hash == single_hash
        expected = protocol_hash(PAYLOAD_HASH_DOMAIN, returned.projection_as_dict(projection))
        assert batch_hash == expected
        return
    if case == "mutated":
        mutated_runs = (
            _run("fixed_ig"),
            _run("fixed_lookahead"),
            _run("fixed_lookahead", seed=SEED + 1),
        )
        mutated = tuple(returned.project_returned_run(run) for run in mutated_runs)
        _probe(monkeypatch, mutated, mutated_runs, patch_hash=False)
        original = _batch(mutated[:2], mutated_runs[:2])
        changed = _batch((mutated[0], mutated[2]), (mutated_runs[0], mutated_runs[2]))
        assert original[0][1] == changed[0][1]
        assert original[1][1] != changed[1][1]
        return
    runs, projections = _delivery()
    if case == "reordered":
        _probe(monkeypatch, projections, runs, patch_hash=False)
        forward = _batch(projections, runs)
        reverse = _batch(projections[::-1], runs[::-1])
        assert {run.run_id: payload_hash for run, payload_hash in forward} == {
            run.run_id: payload_hash for run, payload_hash in reverse
        }
        return
    _first, second = runs
    _calls, hash_calls = _probe(monkeypatch, projections, runs, ("S10", second.run_id))
    _science(projections, runs, "returned_runs[1].returned_run.S10")
    assert hash_calls == []


def _replace_once(source: str, before: str, after: str) -> str:
    assert source.count(before) == 1
    return source.replace(before, after, 1)


def _swap_once(source: str, left: str, right: str) -> str:
    marker = "__RETURNED_RUN_ARCHITECTURE_SWAP__"
    return _replace_once(
        _replace_once(_replace_once(source, left, marker), right, left), marker, right
    )


def _architecture_checks(source: str) -> dict[str, bool]:
    analysis = architecture.analyze_qualified_symbols(
        source,
        module_name=architecture.RETURNED_RUN_MODULE_NAME,
    )
    return dict(architecture.returned_run_architecture_checks(source, analysis=analysis))


def test_batch_architecture_rejects_stage_schedule_mutations() -> None:
    source = Path(returned.__file__ or "").read_text(encoding="utf-8")
    check = "exact-returned-run-batch-stage-major-schedule"
    current = _architecture_checks(source)
    assert current[check]
    s1 = "_validate_returned_run_s1(projection)"
    s2 = "_construct_returned_run_s2(projection)"
    s9 = "_validate_returned_run_s9(run)"
    s10 = "_validate_returned_run_s10(run)"
    mutations = {
        "S2-before-S1": _swap_once(source, s1, s2),
        "S10-before-S9": _swap_once(source, s9, s10),
        "conditional-S1": _replace_once(
            source,
            s1,
            f"if False:\n                {s1}",
        ),
        "repeated-S9-loop": _replace_once(
            source,
            s9,
            f"for _repeat in (0, 1):\n                {s9}",
        ),
        "wrong-S1-payload": _replace_once(
            source,
            s1,
            "_validate_returned_run_s1(returned_runs_in_actual_delivery_order[0])",
        ),
        "omitted-S4": _replace_once(
            source,
            "_construct_returned_run_s4(projection, caches[index])",
            "None",
        ),
        "duplicated-S9": _replace_once(source, s9, f"{s9}\n            {s9}"),
        "payload-major": _replace_once(
            _replace_once(source, s1, f"{s1}\n            {s2}"),
            f"cache, completed, evidence = {s2}",
            "cache, completed, evidence = {}, (), ()",
        ),
    }
    for mutation, changed in mutations.items():
        assert _architecture_checks(changed)[check] is False, mutation


def test_batch_architecture_rejects_hash_and_identity_mutations() -> None:
    source = Path(returned.__file__ or "").read_text(encoding="utf-8")
    helper_prefix = (
        "def _accepted_result_payload_sha256(projection: ReturnedRunProjection) -> str:\n"
        "    return protocol_hash("
    )
    helper = """\
def _accepted_result_payload_sha256(projection: ReturnedRunProjection) -> str:
    return protocol_hash(
        "validation_evidence_returned_run_payload/v1",
        projection_as_dict(projection),
    )
"""
    nested = """\
def _accepted_result_payload_sha256(projection: ReturnedRunProjection) -> str:
    def batch_hash(value: ReturnedRunProjection) -> str:
        return protocol_hash("returned_run_batch/v1", projection_as_dict(value))

    return batch_hash(projection)
"""
    return_line = "    return tuple(zip(runs, hashes, strict=True))"
    wrapper = (
        "    def batch_identity() -> str:\n"
        '        return protocol_hash("returned_run_batch/v1", {"hashes": list(hashes)})\n\n'
        "    batch_identity()\n"
        f"{return_line}"
    )
    transitive_alias = (
        "    first_hash = protocol_hash\n"
        "    second_hash = first_hash\n"
        '    second_hash("returned_run_batch/v1", {"hashes": list(hashes)})\n'
        f"{return_line}"
    )
    mutations = {
        "direct-domain": source.replace(
            PAYLOAD_HASH_DOMAIN,
            "validation_evidence_returned_run_batch/v1",
            1,
        ),
        "aliased-primitive": _replace_once(
            source,
            helper_prefix,
            helper_prefix.replace(
                "    return protocol_hash(",
                "    payload_hash = protocol_hash\n    return payload_hash(",
            ),
        ),
        "helper-returned": _replace_once(source, helper, nested),
        "second-identity": _replace_once(source, return_line, wrapper),
        "transitive-alias": _replace_once(source, return_line, transitive_alias),
    }
    for mutation, changed in mutations.items():
        checks = _architecture_checks(changed)
        assert checks["no-returned-run-batch-hash-or-identity"] is False, mutation
        if mutation in {"direct-domain", "aliased-primitive", "helper-returned"}:
            assert checks["exact-returned-run-payload-hash-domain-and-call"] is False

    benign_payload = _replace_once(
        source,
        '            "oracle_key_id": oracle_key_id,\n'
        '            "revealed_observation": f64(observed),',
        '            "oracle_key_id": oracle_key_id,\n'
        '            "note": "ordinary batch test data",\n'
        '            "revealed_observation": f64(observed),',
    )
    assert _architecture_checks(benign_payload)["no-returned-run-batch-hash-or-identity"] is True


def test_batch_architecture_rejects_injected_validator_surfaces() -> None:
    source = Path(returned.__file__ or "").read_text(encoding="utf-8")
    public_domain = (
        "    returned_domains_in_actual_delivery_order: tuple[BroaderArmRun, ...] | None,\n"
    )
    public_close = ") -> tuple[tuple[BroaderArmRun, str], ...]:"
    public_end = public_domain + public_close

    def public(parameter: str) -> str:
        return _replace_once(
            source,
            public_end,
            f"{public_domain}    {parameter}\n{public_close}",
        )

    s1_header = "def _validate_returned_run_s1(projection: ReturnedRunProjection) -> None:\n"
    mutations = {
        "validators": public("validators: tuple[Callable[..., object], ...] = (),"),
        "validator-map": public("validator_map: dict[str, Callable[..., object]] | None = None,"),
        "callable-alias": public("checks: tuple[Callable[..., object], ...] = (),"),
        "S2-S1-sequence": public(
            "stage_order: tuple[Callable[..., object], ...] = "
            "(_construct_returned_run_s2, _validate_returned_run_s1),"
        ),
        "validator-kwargs": _replace_once(
            source,
            public_end,
            f"{public_domain}    **kwargs: object\n{public_close}",
        ),
        "private-forwarded-kwargs": _replace_once(
            source,
            s1_header,
            "def _validate_returned_run_s1("
            "projection: ReturnedRunProjection, **options: object) -> None:\n"
            "    for operation in cast("
            "tuple[Callable[..., object], ...], options.get('validators', ())):\n"
            "        operation(projection)\n",
        ),
    }
    for mutation, changed in mutations.items():
        checks = _architecture_checks(changed)
        assert checks["closed-returned-run-batch-validator-surface"] is False, mutation
        assert checks["exact-returned-run-batch-public-signature"] is (
            mutation == "private-forwarded-kwargs"
        )
