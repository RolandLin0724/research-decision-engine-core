from __future__ import annotations

import inspect
from dataclasses import replace

import pytest

import research_decision_engine.benchmarks.broader_audits as audit_module
from research_decision_engine.benchmarks.broader_artifact_graph import (
    CanonicalArtifactGraph,
    decode_and_validate_artifacts,
)
from research_decision_engine.benchmarks.broader_artifacts import artifact_contracts
from research_decision_engine.benchmarks.broader_assembly import finalize_validation_artifacts
from research_decision_engine.benchmarks.broader_audits import (
    IntegrityAuditContext,
    assert_audit_executor_completeness,
    evaluate_audit,
    run_integrity_audits,
)
from research_decision_engine.benchmarks.broader_conformance import (
    CONFORMANCE_PROFILE,
    DiagnosticConformanceFixture,
)
from research_decision_engine.benchmarks.broader_oracle import ObservationAuthority
from research_decision_engine.benchmarks.broader_protocol import (
    ARMS,
    canonical_json_bytes,
    protocol_hash,
)
from research_decision_engine.benchmarks.broader_runner import BroaderArmRun, run_arm
from research_decision_engine.benchmarks.broader_worlds import WORLDS_BY_ID
from research_decision_engine.decision import DecisionTrace
from tests.test_broader_oracle_support import ConformanceOracleSupport


def _runs() -> tuple[BroaderArmRun, ...]:
    world = WORLDS_BY_ID["h_adam_low"]
    return tuple(
        run_arm(
            arm=arm,
            world=world.public,
            seed=9000,
            budget_id="budget-2.25",
            budget=2.25,
            authority=ObservationAuthority(world=world, seed=9000),
        )
        for arm in ARMS
    )


@pytest.fixture(scope="module")
def baseline_context() -> IntegrityAuditContext:
    runs = _runs()
    replay = _runs()
    payload = canonical_json_bytes([run.run_id for run in runs], final_lf=True)
    replay_payload = canonical_json_bytes([run.run_id for run in replay], final_lf=True)
    return IntegrityAuditContext(
        runs=runs,
        replay_runs=replay,
        first_payload=payload,
        replay_payload=replay_payload,
        historical_before=(("frozen/file", "0" * 64),),
        historical_after=(("frozen/file", "0" * 64),),
    )


@pytest.fixture(scope="module")
def conformance_graph(
    tmp_path_factory: pytest.TempPathFactory,
    conformance_oracle_support: ConformanceOracleSupport,
) -> CanonicalArtifactGraph:
    target = tmp_path_factory.mktemp("audit-conformance-graph") / "canonical"
    plan, operational, authorization = conformance_oracle_support.payloads(target)
    artifacts = finalize_validation_artifacts(
        target,
        plan,
        operational,
        authorization,
        profile=CONFORMANCE_PROFILE,
    )
    return decode_and_validate_artifacts(
        artifacts,
        artifact_contracts(),
        profile=CONFORMANCE_PROFILE,
    )


def test_all_16_audits_have_one_executor_and_smoke_never_passes_vacuously(
    baseline_context: IntegrityAuditContext,
) -> None:
    assert_audit_executor_completeness()
    results = run_integrity_audits(baseline_context)
    assert len(results) == 16
    assert {item.audit_id for item in results if item.status == "FAIL"} == {
        "A04-ORACLE-ISOLATION",
        "A06-DETERMINISM",
    }
    statuses = {item.audit_id: item.status for item in results}
    for audit_id in (
        "A09-PLANNER-AND-EVIDENCE",
        "A10-COSTS",
        "A12-MATRIX",
        "A13-REGISTRIES",
        "A15-RESAMPLING",
        "A16-FINALIZATION",
    ):
        assert statuses[audit_id] == "INCONCLUSIVE"


def test_each_audit_has_a_deliberately_broken_or_missing_requirement_path(
    baseline_context: IntegrityAuditContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audit_module, "FULL_SEEDS", (1000,))
    assert evaluate_audit("A01-SEEDS", baseline_context).status == "FAIL"
    monkeypatch.undo()

    monkeypatch.setattr(
        audit_module, "validate_worlds", lambda: (_ for _ in ()).throw(ValueError("broken"))
    )
    with pytest.raises(ValueError, match="broken"):
        evaluate_audit("A02-WORLDS", baseline_context)
    monkeypatch.undo()

    original_getmembers = inspect.getmembers

    def extra_method(value: object) -> list[tuple[str, object]]:
        return [*original_getmembers(value), ("peek", lambda: None)]

    monkeypatch.setattr(inspect, "getmembers", extra_method)
    assert evaluate_audit("A03-TRUTH-ISOLATION", baseline_context).status == "FAIL"
    monkeypatch.undo()

    wrong_oracle = replace(
        baseline_context,
        oracle_conformance_result=object(),  # type: ignore[arg-type]
        oracle_evidence_binding=object(),  # type: ignore[arg-type]
    )
    assert evaluate_audit("A04-ORACLE-ISOLATION", wrong_oracle).status == "FAIL"

    one_run = replace(baseline_context, runs=baseline_context.runs[:1])
    assert evaluate_audit("A05-COMMON-RANDOMNESS", one_run).status == "FAIL"

    no_replay = replace(baseline_context, replay_runs=(), replay_payload=b"")
    assert evaluate_audit("A06-DETERMINISM", no_replay).status == "INCONCLUSIVE"

    crossed = replace(baseline_context, runs=(baseline_context.runs[0],) * 2)
    assert evaluate_audit("A07-ARM-ISOLATION", crossed).status == "FAIL"

    calibrated = baseline_context.runs[1]
    fake_fixed = replace(calibrated, arm=ARMS[0])
    bad_calibration = replace(baseline_context, runs=(fake_fixed,))
    assert evaluate_audit("A08-CALIBRATION-SEPARATION", bad_calibration).status == "FAIL"

    bad_decision = replace(
        baseline_context.runs[0].decisions[0], fixed_policy_regression_match=False
    )
    bad_planner_run = replace(
        baseline_context.runs[0],
        decisions=(bad_decision, *baseline_context.runs[0].decisions[1:]),
    )
    bad_planner = replace(baseline_context, runs=(bad_planner_run,))
    assert evaluate_audit("A09-PLANNER-AND-EVIDENCE", bad_planner).status == "FAIL"

    bad_cost_run = replace(
        baseline_context.runs[0], decision_cost=baseline_context.runs[0].decision_cost + 1.0
    )
    assert (
        evaluate_audit("A10-COSTS", replace(baseline_context, runs=(bad_cost_run,))).status
        == "FAIL"
    )

    monkeypatch.setitem(
        audit_module.PROTECTED_HASHES, "research_decision_engine/policies.py", "0" * 64
    )
    assert evaluate_audit("A11-SOURCE-FREEZE", baseline_context).status == "FAIL"
    monkeypatch.undo()

    for audit_id in ("A12-MATRIX", "A13-REGISTRIES", "A15-RESAMPLING", "A16-FINALIZATION"):
        assert evaluate_audit(audit_id, baseline_context).status == "INCONCLUSIVE"

    historical = replace(baseline_context, historical_after=(("frozen/file", "1" * 64),))
    assert evaluate_audit("A14-HISTORICAL", historical).status == "FAIL"


def test_common_randomness_rejects_mismatched_and_excessive_reveals(
    baseline_context: IntegrityAuditContext,
) -> None:
    left, right = baseline_context.runs[:2]
    left_action = next(item for item in left.actions if item.oracle_observation is not None)
    right_index = next(
        index
        for index, item in enumerate(right.actions)
        if item.candidate_id == left_action.candidate_id and item.oracle_observation is not None
    )
    right_action = right.actions[right_index]
    assert right_action.oracle_observation is not None
    mismatched_observation = replace(
        right_action.oracle_observation,
        revealed_observation=right_action.oracle_observation.revealed_observation + 1.0,
    )
    mismatched_actions = list(right.actions)
    mismatched_actions[right_index] = replace(
        right_action,
        oracle_observation=mismatched_observation,
    )
    mismatched = replace(right, actions=tuple(mismatched_actions))
    assert (
        evaluate_audit(
            "A05-COMMON-RANDOMNESS",
            replace(baseline_context, runs=(left, mismatched)),
        ).status
        == "FAIL"
    )

    assert left_action.oracle_observation is not None
    duplicate_observation = replace(
        left_action.oracle_observation,
        oracle_use_id=left_action.oracle_observation.oracle_use_id + "/duplicate",
    )
    excessive = replace(
        left,
        actions=(
            *left.actions,
            replace(left_action, oracle_observation=duplicate_observation),
        ),
    )
    assert (
        evaluate_audit(
            "A05-COMMON-RANDOMNESS",
            replace(baseline_context, runs=(excessive,)),
        ).status
        == "FAIL"
    )


@pytest.mark.parametrize(
    "corruption",
    ("missing", "cross_world", "cross_seed", "unauthorized", "namespace"),
)
def test_common_randomness_derives_expected_observations_before_validation(
    baseline_context: IntegrityAuditContext, corruption: str
) -> None:
    run = baseline_context.runs[0]
    index = next(
        index for index, action in enumerate(run.actions) if action.oracle_observation is not None
    )
    action = run.actions[index]
    observation = action.oracle_observation
    assert observation is not None
    if corruption == "missing":
        changed_observation = None
    elif corruption == "cross_world":
        changed_observation = replace(observation, world_id="h_sgd_low")
    elif corruption == "cross_seed":
        changed_observation = replace(observation, seed=observation.seed + 1)
    elif corruption == "unauthorized":
        changed_observation = replace(
            observation, authorization_id=observation.authorization_id + "/foreign"
        )
    else:
        changed_observation = replace(observation, namespace="rde.broader.calibration-outcome/v1")
    actions = list(run.actions)
    actions[index] = replace(action, oracle_observation=changed_observation)
    corrupted = replace(run, actions=tuple(actions))

    result = evaluate_audit(
        "A05-COMMON-RANDOMNESS",
        replace(baseline_context, runs=(corrupted, *baseline_context.runs[1:])),
    )
    assert result.status == "FAIL"


def test_common_randomness_rejects_cross_budget_use_identity(
    baseline_context: IntegrityAuditContext,
) -> None:
    short = baseline_context.runs[0]
    world = WORLDS_BY_ID[short.world_id]
    long = run_arm(
        arm=short.arm,
        world=world.public,
        seed=short.seed,
        budget_id="budget-4.50",
        budget=4.5,
        authority=ObservationAuthority(world=world, seed=short.seed),
    )
    short_action = next(item for item in short.actions if item.oracle_observation is not None)
    long_index = next(
        index
        for index, item in enumerate(long.actions)
        if item.candidate_id == short_action.candidate_id and item.oracle_observation is not None
    )
    actions = list(long.actions)
    actions[long_index] = replace(
        actions[long_index], oracle_observation=short_action.oracle_observation
    )
    corrupted = replace(long, actions=tuple(actions))

    assert (
        evaluate_audit(
            "A05-COMMON-RANDOMNESS",
            replace(baseline_context, runs=(short, corrupted)),
        ).status
        == "FAIL"
    )


def test_common_randomness_rejects_observation_attached_to_setup(
    baseline_context: IntegrityAuditContext,
) -> None:
    world = WORLDS_BY_ID["d3_adam"]
    run = run_arm(
        arm=next(item for item in ARMS if item.arm_id == "fixed_lookahead"),
        world=world.public,
        seed=9000,
        budget_id="budget-2.25",
        budget=2.25,
        authority=ObservationAuthority(world=world, seed=9000),
    )
    observed = next(
        item.oracle_observation for item in run.actions if item.oracle_observation is not None
    )
    actions = list(run.actions)
    actions[0] = replace(actions[0], oracle_observation=observed)
    corrupted = replace(run, actions=tuple(actions))

    assert (
        evaluate_audit(
            "A05-COMMON-RANDOMNESS",
            replace(baseline_context, runs=(corrupted,)),
        ).status
        == "FAIL"
    )


def test_arm_isolation_rejects_shared_history_container(
    baseline_context: IntegrityAuditContext,
) -> None:
    left, right = baseline_context.runs[:2]
    aliased_right = replace(right, actions=left.actions)
    result = evaluate_audit(
        "A07-ARM-ISOLATION",
        replace(baseline_context, runs=(left, aliased_right)),
    )
    assert result.status == "FAIL"


def test_arm_isolation_rejects_one_shared_nested_diagnostic(
    baseline_context: IntegrityAuditContext,
    diagnostic_conformance_fixture: DiagnosticConformanceFixture,
) -> None:
    fixture = diagnostic_conformance_fixture
    calibrated = tuple(
        item
        for item in fixture.runs
        if item.arm.arm_id.startswith("calibrated_") and item.diagnostics
    )
    left, right = calibrated[:2]
    aliased = replace(
        right,
        diagnostics=(left.diagnostics[0], *right.diagnostics[1:]),
    )
    result = evaluate_audit(
        "A07-ARM-ISOLATION",
        replace(baseline_context, runs=(left, aliased)),
    )
    assert result.status == "FAIL"


def test_planner_replay_rejects_calibrated_score_and_selection_corruption(
    baseline_context: IntegrityAuditContext,
) -> None:
    calibrated = next(item for item in baseline_context.runs if item.arm.arm_id == "calibrated_ig")
    decision = calibrated.decisions[0]
    trace = decision.policy_trace
    assert isinstance(trace, DecisionTrace)
    ranked = trace.ranked_candidates
    changed_score = replace(
        ranked[0],
        expected_information_gain=ranked[0].expected_information_gain + 0.001,
    )
    changed_trace = replace(
        trace,
        selected=changed_score,
        ranked_candidates=(changed_score, *ranked[1:]),
    )
    changed_decision = replace(decision, policy_trace=changed_trace)
    score_run = replace(
        calibrated,
        decisions=(changed_decision, *calibrated.decisions[1:]),
    )
    assert (
        evaluate_audit(
            "A09-PLANNER-AND-EVIDENCE",
            replace(baseline_context, runs=(score_run,)),
        ).status
        == "FAIL"
    )

    alternative = next(
        candidate_id
        for candidate_id in decision.affordable_candidate_ids
        if candidate_id != decision.selected_candidate_id
    )
    selected_run = replace(
        calibrated,
        decisions=(
            replace(decision, selected_candidate_id=alternative),
            *calibrated.decisions[1:],
        ),
    )
    assert (
        evaluate_audit(
            "A09-PLANNER-AND-EVIDENCE",
            replace(baseline_context, runs=(selected_run,)),
        ).status
        == "FAIL"
    )


def test_planner_replay_rejects_a_corrupted_recorded_calibration_sigma(
    baseline_context: IntegrityAuditContext,
) -> None:
    calibrated = next(item for item in baseline_context.runs if item.arm.arm_id == "calibrated_ig")
    assert calibrated.calibration is not None
    estimates = calibrated.calibration.estimates
    corrupted_estimate = replace(estimates[0], estimated_sigma=estimates[0].estimated_sigma + 0.01)
    corrupted_deployment = replace(
        calibrated.calibration,
        estimates=(corrupted_estimate, *estimates[1:]),
    )
    corrupted = replace(calibrated, calibration=corrupted_deployment)
    context = replace(baseline_context, runs=(corrupted,))

    assert evaluate_audit("A08-CALIBRATION-SEPARATION", context).status == "FAIL"
    assert evaluate_audit("A09-PLANNER-AND-EVIDENCE", context).status == "FAIL"


def test_mechanism_reconstruction_rejects_valid_self_hash_for_wrong_label(
    baseline_context: IntegrityAuditContext,
    diagnostic_conformance_fixture: DiagnosticConformanceFixture,
) -> None:
    fixture = diagnostic_conformance_fixture
    comparison = next(item for item in fixture.analysis.comparisons if item.truth_free is not None)
    truth = comparison.truth_free
    assert truth is not None
    fixed = comparison.paired.fixed_run
    calibrated = comparison.paired.calibrated_run
    wrong_primary = (
        "GROUP_SIGMA_REORDERING"
        if truth.primary_mechanism_id != "GROUP_SIGMA_REORDERING"
        else "SCORE_FLATTENING"
    )
    payload = {
        "comparison_id": fixed.comparison_id,
        "policy_id": fixed.arm.policy_id,
        "first_divergence_step": truth.first_divergence_step,
        "fixed_candidate_id": truth.fixed_candidate_id,
        "calibrated_candidate_id": truth.calibrated_candidate_id,
        "fixed_sequence": list(fixed.selected_candidate_ids),
        "calibrated_sequence": list(calibrated.selected_candidate_ids),
        "first_action_divergent": truth.first_action_divergent,
        "sequence_class": truth.sequence_class,
        "predicate_results": dict(truth.predicate_results),
        "primary_mechanism_id": wrong_primary,
        "contributing_mechanism_ids": list(truth.contributing_mechanism_ids),
        "controller_stage_id": truth.controller_stage_id,
    }
    wrong_truth = replace(
        truth,
        primary_mechanism_id=wrong_primary,
        mechanism_row_without_outcome_sha256=protocol_hash("truth_free_mechanism_row/v1", payload),
    )
    wrong_comparison = replace(comparison, truth_free=wrong_truth)
    wrong_analysis = replace(fixture.analysis, comparisons=(wrong_comparison,))
    context = replace(
        baseline_context,
        runs=(fixed, calibrated),
        analysis=wrong_analysis,
    )

    assert evaluate_audit("A09-PLANNER-AND-EVIDENCE", context).status == "FAIL"


def test_population_artifact_resampling_and_finalization_audits_do_not_pass_mutations(
    baseline_context: IntegrityAuditContext,
    conformance_graph: CanonicalArtifactGraph,
    diagnostic_conformance_fixture: DiagnosticConformanceFixture,
) -> None:
    conformance_context = replace(
        baseline_context,
        scope="full",
        artifact_graph=conformance_graph,
        analysis=diagnostic_conformance_fixture.analysis,
    )
    assert evaluate_audit("A12-MATRIX", conformance_context).status == "FAIL"
    assert evaluate_audit("A15-RESAMPLING", conformance_context).status == "INCONCLUSIVE"
    assert evaluate_audit("A13-REGISTRIES", conformance_context).status == "PASS"
    assert evaluate_audit("A16-FINALIZATION", conformance_context).status == "PASS"

    incomplete_graph = replace(
        conformance_graph,
        artifacts=conformance_graph.artifacts[:-3],
    )
    results = run_integrity_audits(replace(conformance_context, artifact_graph=incomplete_graph))
    statuses = {item.audit_id: item.status for item in results}
    assert statuses["A13-REGISTRIES"] == "FAIL"
    assert statuses["A16-FINALIZATION"] == "PASS"
