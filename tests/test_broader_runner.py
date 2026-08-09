from __future__ import annotations

import math
import statistics
from dataclasses import replace

import pytest

import research_decision_engine.benchmarks.broader_runner as runner_module
from research_decision_engine.belief_models import MatchedEffectObservation
from research_decision_engine.benchmarks.broader_analysis import (
    ProductionAnalysisConfig,
    analyze_scientific_artifacts,
)
from research_decision_engine.benchmarks.broader_execution import execute_deterministic_map
from research_decision_engine.benchmarks.broader_oracle import (
    DECISION_NAMESPACE,
    ObservationAuthority,
    RevealedObservation,
)
from research_decision_engine.benchmarks.broader_protocol import FrozenArm, f64, protocol_hash
from research_decision_engine.benchmarks.broader_runner import (
    BroaderArmRun,
    CalibrationGroupEstimate,
    RunProvenanceError,
    arm_spec,
    calibration_sigma_provenance_sha256,
    crossed_decision_traces,
    initial_lineage_for,
    replay_decisions,
    run_arm,
    run_identity,
    terminal_reason_for,
)
from research_decision_engine.benchmarks.broader_worlds import (
    CANDIDATE_CATALOG,
    GROUP_IDS,
    WORLDS,
    WORLDS_BY_ID,
    candidate_costs,
)


def _run(arm_id: str, world_id: str = "d3_adam") -> BroaderArmRun:
    world = WORLDS_BY_ID[world_id]
    return run_arm(
        arm=arm_spec(arm_id),
        world=world.public,
        seed=9000,
        budget_id="budget-2.25",
        budget=2.25,
        authority=ObservationAuthority(world=world, seed=9000),
    )


def test_depth_three_executes_real_setup_then_replans() -> None:
    run = _run("fixed_lookahead")

    assert run.selected_candidate_ids == (
        "g00-setup-r1",
        "g00-adam-r1",
        "g00-sgd-r1",
    )
    assert run.actions[0].oracle_observation is None
    assert run.actions[0].new_evidence_ids == ()
    assert run.actions[1].new_evidence_ids == ()
    assert len(run.actions[2].new_evidence_ids) == 1
    assert run.decision_cost == 2.25
    assert all(item.fixed_policy_regression_match for item in run.decisions)
    assert "g00-adam-r1" not in run.decisions[0].affordable_candidate_ids
    assert "g00-adam-r1" in run.decisions[1].affordable_candidate_ids


def test_depth_three_replay_rejects_missing_setup_and_early_optimizer_availability() -> None:
    run = _run("fixed_lookahead")
    missing_setup = replace(
        run,
        decisions=run.decisions[1:],
        actions=run.actions[1:],
    )
    with pytest.raises(RunProvenanceError, match="public candidate state"):
        replay_decisions(missing_setup)

    first = run.decisions[0]
    early = replace(
        first,
        public_feasible_candidate_ids=(
            *first.public_feasible_candidate_ids,
            "g00-adam-r1",
        ),
        affordable_candidate_ids=(*first.affordable_candidate_ids, "g00-adam-r1"),
    )
    early_available = replace(run, decisions=(early, *run.decisions[1:]))
    with pytest.raises(RunProvenanceError, match="public candidate state"):
        replay_decisions(early_available)


def test_fixed_and_calibrated_arms_have_isolated_lineages_and_equal_priors() -> None:
    fixed = _run("fixed_ig", "g_adam_lmh")
    calibrated = _run("calibrated_ig", "g_adam_lmh")

    assert fixed.lineage.lineage_id != calibrated.lineage.lineage_id
    assert fixed.initial_probabilities == calibrated.initial_probabilities
    assert fixed.calibration is None
    assert fixed.calibration_cost == 0.0
    assert calibrated.calibration is not None
    assert len(calibrated.calibration.effects) == 15
    assert calibrated.calibration_cost > 0.0
    assert fixed.completed_experiments is not calibrated.completed_experiments
    assert fixed.effect_history != calibrated.effect_history
    assert {item.decision_id for item in fixed.decisions}.isdisjoint(
        item.decision_id for item in calibrated.decisions
    )


def test_all_terminal_reasons_have_frozen_precedence() -> None:
    assert terminal_reason_for((), (), integrity_failure=False) == "candidate_space_exhausted"
    assert terminal_reason_for(("candidate",), (), integrity_failure=False) == "budget_exhausted"
    assert terminal_reason_for(("candidate",), (), integrity_failure=True) == "integrity_abort"
    with pytest.raises(ValueError, match="cannot be assigned"):
        terminal_reason_for(("candidate",), ("candidate",), integrity_failure=False)


@pytest.mark.parametrize(
    "world_id", [world.public.world_id for world in WORLDS if world.public.depth == 3]
)
def test_every_depth_three_world_requires_public_setup(world_id: str) -> None:
    world = WORLDS_BY_ID[world_id].public
    from research_decision_engine.benchmarks.broader_worlds import PublicFeasibilityState

    initial = PublicFeasibilityState(world)
    assert not any(
        candidate.endswith(("adam-r1", "sgd-r1"))
        for candidate in initial.publicly_feasible_candidate_ids()
    )
    for setup_id in world.setup_candidate_ids:
        transitioned = initial.complete(setup_id)
        group = setup_id[1:3]
        assert f"g{group}-adam-r1" in transitioned.publicly_feasible_candidate_ids()
        assert f"g{group}-sgd-r1" in transitioned.publicly_feasible_candidate_ids()


def test_run_preflight_rejects_every_mismatched_binding_without_observation() -> None:
    world = WORLDS_BY_ID["h_adam_low"]

    seed_authority = ObservationAuthority(world=world, seed=1001)
    with pytest.raises(RunProvenanceError, match="different evaluation seed"):
        run_arm(
            arm=arm_spec("fixed_ig"),
            world=world.public,
            seed=1000,
            budget_id="budget-2.25",
            budget=2.25,
            authority=seed_authority,
        )
    assert seed_authority.revealed_observations() == ()

    other = WORLDS_BY_ID["h_sgd_low"]
    world_authority = ObservationAuthority(world=other, seed=1000)
    with pytest.raises(RunProvenanceError, match="different benchmark world"):
        run_arm(
            arm=arm_spec("fixed_ig"),
            world=world.public,
            seed=1000,
            budget_id="budget-2.25",
            budget=2.25,
            authority=world_authority,
        )
    assert world_authority.revealed_observations() == ()

    for budget_id, budget in (("budget-2.25", 4.5), ("budget-unknown", 2.25)):
        authority = ObservationAuthority(world=world, seed=1000)
        with pytest.raises(RunProvenanceError, match="Budget"):
            run_arm(
                arm=arm_spec("fixed_ig"),
                world=world.public,
                seed=1000,
                budget_id=budget_id,
                budget=budget,
                authority=authority,
            )
        assert authority.revealed_observations() == ()

    wrong_arm = FrozenArm(1, "fixed_ig", "fixed_sigma_gaussian", "lookahead_information_gain")
    authority = ObservationAuthority(world=world, seed=1000)
    with pytest.raises(RunProvenanceError, match="Arm, policy"):
        run_arm(
            arm=wrong_arm,
            world=world.public,
            seed=1000,
            budget_id="budget-2.25",
            budget=2.25,
            authority=authority,
        )

    namespace_authority = ObservationAuthority(
        world=world,
        seed=1000,
        decision_namespace=DECISION_NAMESPACE + ".wrong",
    )
    with pytest.raises(RunProvenanceError, match="namespace"):
        run_arm(
            arm=arm_spec("fixed_ig"),
            world=world.public,
            seed=1000,
            budget_id="budget-2.25",
            budget=2.25,
            authority=namespace_authority,
        )


def test_supplied_lineage_mismatch_fails_before_any_observation() -> None:
    arm = arm_spec("fixed_ig")
    world = WORLDS_BY_ID["h_adam_low"]
    run_id = run_identity(arm_id=arm.arm_id, world_id=world.public.world_id, seed=1000, budget=2.25)
    crossed = replace(initial_lineage_for(arm=arm, run_id=run_id), lineage_key="run:another")
    authority = ObservationAuthority(world=world, seed=1000)
    with pytest.raises(RunProvenanceError, match="does not belong"):
        run_arm(
            arm=arm,
            world=world.public,
            seed=1000,
            budget_id="budget-2.25",
            budget=2.25,
            authority=authority,
            initial_lineage=crossed,
        )
    assert authority.revealed_observations() == ()


@pytest.mark.parametrize("mismatch", ("catalog", "cost"))
def test_catalog_and_cost_mismatches_fail_before_observation(mismatch: str) -> None:
    arm = arm_spec("fixed_ig")
    world = WORLDS_BY_ID["h_adam_low"]
    authority = ObservationAuthority(world=world, seed=1000)
    catalog = CANDIDATE_CATALOG[:-1] if mismatch == "catalog" else CANDIDATE_CATALOG
    costs = candidate_costs(world.public)
    if mismatch == "cost":
        costs = {**costs, next(iter(costs)): 99.0}
    with pytest.raises(RunProvenanceError, match="catalog|cost table"):
        run_arm(
            arm=arm,
            world=world.public,
            seed=1000,
            budget_id="budget-2.25",
            budget=2.25,
            authority=authority,
            candidate_catalog=catalog,
            cost_table=costs,
        )
    assert authority.revealed_observations() == ()


def test_separate_authority_mismatch_fails_before_either_authority_reveals() -> None:
    world = WORLDS_BY_ID["h_adam_low"]
    decision = ObservationAuthority(world=world, seed=1000)
    calibration = ObservationAuthority(world=world, seed=1001)
    with pytest.raises(RunProvenanceError, match="different evaluation seed"):
        run_arm(
            arm=arm_spec("calibrated_ig"),
            world=world.public,
            seed=1000,
            budget_id="budget-2.25",
            budget=2.25,
            decision_authority=decision,
            calibration_authority=calibration,
        )
    assert decision.revealed_observations() == ()
    assert calibration.revealed_observations() == ()


def _rehash_estimate(estimate: CalibrationGroupEstimate) -> CalibrationGroupEstimate:
    return replace(
        estimate,
        provenance_sha256=calibration_sigma_provenance_sha256(
            sigma_estimate_id=estimate.sigma_estimate_id,
            calibration_prefix_id=estimate.calibration_prefix_id,
            comparison_group_id=estimate.comparison_group_id,
            source_effect_ids=estimate.source_effect_ids,
            source_sequence_cutoff=estimate.source_sequence_cutoff,
            sample_count=estimate.sample_count,
            sample_mean=estimate.sample_mean,
            raw_sample_standard_deviation=estimate.raw_sample_standard_deviation,
            ddof=estimate.ddof,
            sigma_floor=estimate.sigma_floor,
            estimated_sigma=estimate.estimated_sigma,
            belief_model_id=estimate.belief_model_id,
            lineage_id=estimate.lineage_id,
            effects=estimate.effects,
        ),
    )


def _replace_first_estimate(
    run: BroaderArmRun,
    estimate: CalibrationGroupEstimate,
    *,
    synchronize_effects: bool = False,
) -> BroaderArmRun:
    assert run.calibration is not None
    estimates = (estimate, *run.calibration.estimates[1:])
    deployment = replace(run.calibration, estimates=estimates)
    if not synchronize_effects:
        return replace(run, calibration=deployment)
    calibration_effects = (*estimate.effects, *run.calibration.effects[5:])
    deployment = replace(deployment, effects=calibration_effects)
    effect_history = (*calibration_effects, *run.effect_history[len(calibration_effects) :])
    return replace(run, calibration=deployment, effect_history=effect_history)


def _corrupt_first_calibration_observation(run: BroaderArmRun) -> BroaderArmRun:
    assert run.calibration is not None
    estimate = run.calibration.estimates[0]
    observation = estimate.observations[0]
    changed_observation = replace(
        observation,
        revealed_observation=observation.revealed_observation + 1.0,
    )
    changed_estimate = replace(
        estimate,
        observations=(changed_observation, *estimate.observations[1:]),
    )
    return _replace_first_estimate(run, changed_estimate)


def _mutated_deployment_effects(
    run: BroaderArmRun,
    mutation: str,
) -> tuple[MatchedEffectObservation, ...]:
    assert run.calibration is not None
    effects = run.calibration.effects
    if mutation == "reversal":
        return tuple(reversed(effects))
    if mutation == "adjacent_swap":
        return (effects[1], effects[0], *effects[2:])
    if mutation == "rotated_identity_sequence":
        return (*effects[1:], effects[0])
    if mutation == "foreign_identity":
        return (replace(effects[0], effect_id=f"{effects[0].effect_id}/foreign"), *effects[1:])
    if mutation == "equal_values_distinct_ids":
        return (
            effects[0],
            replace(effects[0], effect_id=effects[1].effect_id),
            *effects[2:],
        )
    if mutation == "duplicate_identity":
        return (
            effects[0],
            replace(effects[1], effect_id=effects[0].effect_id),
            *effects[2:],
        )
    if mutation == "missing":
        return effects[:-1]
    if mutation == "extra":
        return (*effects, replace(effects[-1], effect_id=f"{effects[-1].effect_id}/extra"))
    if mutation == "order_plus_later_value":
        changed_last = replace(
            effects[-1],
            observed_effect=math.nextafter(effects[-1].observed_effect, math.inf),
        )
        return (effects[1], effects[0], *effects[2:-1], changed_last)
    if mutation == "ordered_value":
        return (
            replace(
                effects[0],
                observed_effect=math.nextafter(effects[0].observed_effect, math.inf),
            ),
            *effects[1:],
        )
    raise AssertionError(f"Unknown effect deployment mutation: {mutation}")


def _mutated_deployment_observations(
    run: BroaderArmRun,
    mutation: str,
) -> tuple[RevealedObservation, ...]:
    assert run.calibration is not None
    observations = run.calibration.observations
    if mutation == "reversal":
        return tuple(reversed(observations))
    if mutation == "adjacent_swap":
        return (observations[1], observations[0], *observations[2:])
    if mutation == "rotated_identity_sequence":
        return (*observations[1:], observations[0])
    if mutation == "foreign_identity":
        return (
            replace(
                observations[0],
                oracle_use_id=f"{observations[0].oracle_use_id}/foreign",
            ),
            *observations[1:],
        )
    if mutation == "equal_values_distinct_ids":
        return (
            observations[0],
            replace(observations[0], oracle_use_id=observations[1].oracle_use_id),
            *observations[2:],
        )
    if mutation == "duplicate_identity":
        return (
            observations[0],
            replace(observations[1], oracle_use_id=observations[0].oracle_use_id),
            *observations[2:],
        )
    if mutation == "missing":
        return observations[:-1]
    if mutation == "extra":
        return (
            *observations,
            replace(
                observations[-1],
                oracle_use_id=f"{observations[-1].oracle_use_id}/extra",
            ),
        )
    if mutation == "order_plus_later_key":
        changed_last = replace(
            observations[-1],
            oracle_key_id=f"{observations[-1].oracle_key_id}/foreign",
        )
        return (observations[1], observations[0], *observations[2:-1], changed_last)
    if mutation == "ordered_outcome":
        return (
            replace(
                observations[0],
                outcome_digest=f"{observations[0].outcome_digest}0",
            ),
            *observations[1:],
        )
    raise AssertionError(f"Unknown observation deployment mutation: {mutation}")


def test_crossed_scoring_and_analysis_reject_corrupt_calibration_before_decide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed = _run("fixed_ig", "g_adam_lmh")
    calibrated = _run("calibrated_ig", "g_adam_lmh")
    assert fixed.selected_candidate_ids == calibrated.selected_candidate_ids
    corrupted = _corrupt_first_calibration_observation(calibrated)
    scoring_called = False

    def forbidden_scoring(*args: object, **kwargs: object) -> None:
        nonlocal scoring_called
        del args, kwargs
        scoring_called = True
        raise AssertionError("planner scoring must not run")

    monkeypatch.setattr(runner_module, "_decide", forbidden_scoring)
    with pytest.raises(RunProvenanceError, match="frozen Oracle"):
        crossed_decision_traces(fixed, corrupted, zero_based_step=0)
    with pytest.raises(RunProvenanceError, match="frozen Oracle"):
        attested_runs, _ = execute_deterministic_map(
            lambda run: run,
            (fixed, corrupted),
            worker_count=1,
            executor_kind="serial",
            execution_purpose="diagnostic_conformance",
        )
        analyze_scientific_artifacts(
            attested_runs,
            config=ProductionAnalysisConfig(
                bootstrap_replicates=1,
                sign_flip_replicates=1,
            ),
        )
    assert scoring_called is False


def test_evaluate_arm_rejects_corrupt_calibration_before_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _corrupt_first_calibration_observation(_run("calibrated_ig", "g_adam_lmh"))
    metrics_called = False

    def forbidden_metrics(*args: object, **kwargs: object) -> None:
        nonlocal metrics_called
        del args, kwargs
        metrics_called = True
        raise AssertionError("ArmMetrics must not be constructed")

    monkeypatch.setattr(runner_module, "ArmMetrics", forbidden_metrics)
    truth = WORLDS_BY_ID[run.world_id].hidden.scientific_hypothesis_id
    with pytest.raises(RunProvenanceError, match="frozen Oracle"):
        runner_module.evaluate_arm(run, truth)
    assert metrics_called is False


@pytest.mark.sigma_reconstruction
@pytest.mark.parametrize(
    ("field", "expected_message"),
    (
        (
            "sigma_estimate_id",
            "Calibration identity or replication cardinality differs.",
        ),
        (
            "calibration_prefix_id",
            "Calibration identity or replication cardinality differs.",
        ),
        ("comparison_group_id", "Calibration estimates differ from frozen group order."),
        (
            "source_effect_ids",
            "Complete recorded calibration estimate does not reproduce.",
        ),
        pytest.param(
            "source_effect_ordering",
            "Complete recorded calibration estimate does not reproduce.",
            id=(
                "source_effect_ordering-Calibration source effects or provenance do not reproduce."
            ),
        ),
        (
            "source_sequence_cutoff",
            "Complete recorded calibration estimate does not reproduce.",
        ),
        ("sample_count", "Complete recorded calibration estimate does not reproduce."),
        ("sample_mean", "Complete recorded calibration estimate does not reproduce."),
        (
            "raw_sample_standard_deviation",
            "Complete recorded calibration estimate does not reproduce.",
        ),
        ("ddof", "Complete recorded calibration estimate does not reproduce."),
        ("sigma_floor", "Complete recorded calibration estimate does not reproduce."),
        (
            "estimated_sigma",
            "Complete recorded calibration estimate does not reproduce.",
        ),
        ("physical_cost", "Complete recorded calibration estimate does not reproduce."),
        ("belief_model_id", "Complete recorded calibration estimate does not reproduce."),
        ("lineage_id", "Complete recorded calibration estimate does not reproduce."),
        (
            "provenance_sha256",
            "Complete recorded calibration estimate does not reproduce.",
        ),
        pytest.param(
            "synchronized_source_sequence",
            "Calibration effect chronology differs.",
            id=(
                "synchronized_source_sequence-Current or future evidence entered a "
                "calibration sigma estimate."
            ),
        ),
        pytest.param(
            "source_provenance",
            "Calibration source effect or provenance does not reproduce.",
            id=("source_provenance-Calibration source effects or provenance do not reproduce."),
        ),
        (
            "effect_cardinality",
            "Calibration identity or replication cardinality differs.",
        ),
        (
            "observation_cardinality",
            "Calibration identity or replication cardinality differs.",
        ),
    ),
)
def test_complete_calibrated_sigma_claim_is_reconciled_before_planner_scoring(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    expected_message: str,
) -> None:
    run = _run("calibrated_ig", "g_adam_lmh")
    assert run.calibration is not None
    estimate = run.calibration.estimates[0]
    synchronize_effects = False
    if field == "sigma_estimate_id":
        changed = replace(estimate, sigma_estimate_id=f"{estimate.sigma_estimate_id}/forged")
    elif field == "calibration_prefix_id":
        changed = replace(
            estimate,
            calibration_prefix_id=f"{estimate.calibration_prefix_id}/forged",
        )
    elif field == "comparison_group_id":
        changed = replace(
            estimate,
            comparison_group_id=run.calibration.estimates[1].comparison_group_id,
        )
    elif field == "source_effect_ids":
        changed = replace(
            estimate,
            source_effect_ids=("calibration-effect/forged", *estimate.source_effect_ids[1:]),
        )
    elif field == "source_effect_ordering":
        changed = replace(
            estimate,
            source_effect_ids=tuple(reversed(estimate.source_effect_ids)),
            effects=tuple(reversed(estimate.effects)),
        )
        synchronize_effects = True
    elif field == "source_sequence_cutoff":
        changed = replace(estimate, source_sequence_cutoff=2)
    elif field == "sample_count":
        changed = replace(estimate, sample_count=6)
    elif field == "sample_mean":
        changed = replace(estimate, sample_mean=estimate.sample_mean + 0.01)
    elif field == "raw_sample_standard_deviation":
        changed = replace(
            estimate,
            raw_sample_standard_deviation=estimate.raw_sample_standard_deviation + 0.01,
        )
    elif field == "ddof":
        changed = replace(estimate, ddof=0)
    elif field == "sigma_floor":
        changed = replace(estimate, sigma_floor=0.06)
    elif field == "estimated_sigma":
        changed = replace(estimate, estimated_sigma=estimate.estimated_sigma + 0.01)
    elif field == "physical_cost":
        changed = replace(estimate, physical_cost=estimate.physical_cost + 0.01)
    elif field == "belief_model_id":
        changed = replace(estimate, belief_model_id="fixed_sigma_gaussian")
    elif field == "lineage_id":
        changed = replace(estimate, lineage_id=f"{estimate.lineage_id}/foreign")
    elif field == "provenance_sha256":
        changed = replace(estimate, provenance_sha256="0" * 64)
    elif field == "synchronized_source_sequence":
        effects = (
            replace(estimate.effects[0], available_sequence=1),
            *estimate.effects[1:],
        )
        changed = replace(estimate, effects=effects)
        synchronize_effects = True
    elif field == "source_provenance":
        source = estimate.effects[0]
        effects = (
            replace(
                source,
                provenance=replace(source.provenance, method="forged-calibration-effect"),
            ),
            *estimate.effects[1:],
        )
        changed = replace(estimate, effects=effects)
        synchronize_effects = True
    elif field == "effect_cardinality":
        changed = replace(estimate, effects=estimate.effects[:-1])
        synchronize_effects = True
    else:
        changed = replace(estimate, observations=estimate.observations[:-1])
    if field != "provenance_sha256":
        changed = _rehash_estimate(changed)
    corrupted = _replace_first_estimate(
        run,
        changed,
        synchronize_effects=synchronize_effects,
    )
    scoring_called = False

    def forbidden_scoring(*args: object, **kwargs: object) -> None:
        nonlocal scoring_called
        del args, kwargs
        scoring_called = True
        raise AssertionError("planner scoring must not run")

    monkeypatch.setattr(runner_module, "_decide", forbidden_scoring)
    with pytest.raises(RunProvenanceError) as captured:
        replay_decisions(corrupted)
    assert type(captured.value).__name__ == "RunProvenanceError"
    assert str(captured.value) == expected_message
    assert scoring_called is False


@pytest.mark.sigma_reconstruction
@pytest.mark.parametrize(
    "field",
    (
        "sample_mean",
        "raw_sample_standard_deviation",
        "sigma_floor",
        "estimated_sigma",
        "physical_cost",
        "deployment_cost",
        "run_calibration_cost",
    ),
)
def test_one_ulp_calibration_numeric_mutation_fails_before_scoring_or_metrics(
    field: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run("calibrated_ig", "g_adam_lmh")
    assert run.calibration is not None
    estimate = run.calibration.estimates[0]
    if field == "deployment_cost":
        changed_cost = math.nextafter(run.calibration.cost, math.inf)
        corrupted = replace(
            run,
            calibration=replace(run.calibration, cost=changed_cost),
        )
        message = "Calibration deployment cost does not reconcile."
    elif field == "run_calibration_cost":
        changed_cost = math.nextafter(run.calibration_cost, math.inf)
        corrupted = replace(run, calibration_cost=changed_cost)
        message = "Calibration deployment cost does not reconcile."
    else:
        if field == "sample_mean":
            value = estimate.sample_mean
            changed_value = math.nextafter(value, math.inf)
            changed = replace(estimate, sample_mean=changed_value)
        elif field == "raw_sample_standard_deviation":
            value = estimate.raw_sample_standard_deviation
            changed_value = math.nextafter(value, math.inf)
            changed = replace(estimate, raw_sample_standard_deviation=changed_value)
        elif field == "sigma_floor":
            value = estimate.sigma_floor
            changed_value = math.nextafter(value, math.inf)
            changed = replace(estimate, sigma_floor=changed_value)
        elif field == "estimated_sigma":
            value = estimate.estimated_sigma
            changed_value = math.nextafter(value, math.inf)
            changed = replace(estimate, estimated_sigma=changed_value)
        else:
            assert field == "physical_cost"
            value = estimate.physical_cost
            changed_value = math.nextafter(value, math.inf)
            changed = replace(estimate, physical_cost=changed_value)
        assert f64(changed_value) != f64(value)
        changed = _rehash_estimate(changed)
        corrupted = _replace_first_estimate(run, changed)
        message = "Complete recorded calibration estimate does not reproduce."

    scoring_called = False
    metrics_called = False

    def forbidden_scoring(*args: object, **kwargs: object) -> None:
        nonlocal scoring_called
        del args, kwargs
        scoring_called = True
        raise AssertionError("planner scoring must not run")

    def forbidden_metrics(*args: object, **kwargs: object) -> None:
        nonlocal metrics_called
        del args, kwargs
        metrics_called = True
        raise AssertionError("ArmMetrics must not be constructed")

    monkeypatch.setattr(runner_module, "_decide", forbidden_scoring)
    monkeypatch.setattr(runner_module, "ArmMetrics", forbidden_metrics)
    with pytest.raises(RunProvenanceError) as replay_error:
        replay_decisions(corrupted)
    truth = WORLDS_BY_ID[run.world_id].hidden.scientific_hypothesis_id
    with pytest.raises(RunProvenanceError) as evaluation_error:
        runner_module.evaluate_arm(corrupted, truth)
    assert str(replay_error.value) == message
    assert str(evaluation_error.value) == message
    assert scoring_called is False
    assert metrics_called is False


@pytest.mark.sigma_reconstruction
@pytest.mark.parametrize(
    ("relationship", "message"),
    (
        (
            "deployment_effect_order",
            "Calibration deployment effect ordering differs.",
        ),
        pytest.param(
            "deployment_effect_cardinality",
            "Calibration deployment effect population differs.",
            id=("deployment_effect_cardinality-Calibration deployment effect ordering differs."),
        ),
        (
            "deployment_observation_order",
            "Calibration deployment observation ordering differs.",
        ),
        pytest.param(
            "deployment_observation_cardinality",
            "Calibration deployment observation population differs.",
            id=(
                "deployment_observation_cardinality-Calibration deployment observation "
                "ordering differs."
            ),
        ),
        ("deployment_cost", "Calibration deployment cost does not reconcile."),
        ("run_calibration_cost", "Calibration deployment cost does not reconcile."),
        pytest.param(
            "effect_history_prefix",
            "Calibration matched-effect value differs.",
            id=(
                "effect_history_prefix-Calibration estimator history is not exactly the five "
                "strictly prior matched effects."
            ),
        ),
    ),
)
def test_calibration_deployment_relationships_fail_before_planner_scoring(
    relationship: str,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run("calibrated_ig", "g_adam_lmh")
    assert run.calibration is not None
    calibration = run.calibration
    if relationship == "deployment_effect_order":
        corrupted = replace(
            run,
            calibration=replace(calibration, effects=tuple(reversed(calibration.effects))),
        )
    elif relationship == "deployment_effect_cardinality":
        corrupted = replace(
            run,
            calibration=replace(calibration, effects=calibration.effects[:-1]),
        )
    elif relationship == "deployment_observation_order":
        corrupted = replace(
            run,
            calibration=replace(
                calibration,
                observations=tuple(reversed(calibration.observations)),
            ),
        )
    elif relationship == "deployment_observation_cardinality":
        corrupted = replace(
            run,
            calibration=replace(calibration, observations=calibration.observations[:-1]),
        )
    elif relationship == "deployment_cost":
        corrupted = replace(
            run,
            calibration=replace(calibration, cost=calibration.cost + 1.0),
        )
    elif relationship == "run_calibration_cost":
        corrupted = replace(run, calibration_cost=run.calibration_cost + 1.0)
    else:
        corrupted = replace(
            run,
            effect_history=(
                replace(
                    run.effect_history[0],
                    observed_effect=run.effect_history[0].observed_effect + 1.0,
                ),
                *run.effect_history[1:],
            ),
        )
    scoring_called = False

    def forbidden_scoring(*args: object, **kwargs: object) -> None:
        nonlocal scoring_called
        del args, kwargs
        scoring_called = True
        raise AssertionError("planner scoring must not run")

    monkeypatch.setattr(runner_module, "_decide", forbidden_scoring)
    with pytest.raises(RunProvenanceError) as captured:
        replay_decisions(corrupted)
    assert str(captured.value) == message
    assert scoring_called is False


@pytest.mark.sigma_reconstruction
@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("reversal", "Calibration deployment effect ordering differs."),
        ("adjacent_swap", "Calibration deployment effect ordering differs."),
        ("rotated_identity_sequence", "Calibration deployment effect ordering differs."),
        ("foreign_identity", "Calibration deployment effect ordering differs."),
        ("equal_values_distinct_ids", "Calibration deployment effect population differs."),
        ("duplicate_identity", "Calibration deployment effect population differs."),
        ("missing", "Calibration deployment effect population differs."),
        ("extra", "Calibration deployment effect population differs."),
        ("order_plus_later_value", "Calibration deployment effect ordering differs."),
        ("ordered_value", "Calibration deployment effect population differs."),
    ),
)
def test_effect_deployment_tuple_validation_stops_before_scoring(
    mutation: str,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run("calibrated_ig", "g_adam_lmh")
    assert run.calibration is not None
    corrupted = replace(
        run,
        calibration=replace(
            run.calibration,
            effects=_mutated_deployment_effects(run, mutation),
        ),
    )
    scoring_called = False

    def forbidden_scoring(*args: object, **kwargs: object) -> None:
        nonlocal scoring_called
        del args, kwargs
        scoring_called = True
        raise AssertionError("planner scoring must not run")

    monkeypatch.setattr(runner_module, "_decide", forbidden_scoring)
    with pytest.raises(RunProvenanceError) as captured:
        replay_decisions(corrupted)
    assert str(captured.value) == message
    assert scoring_called is False


@pytest.mark.sigma_reconstruction
@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("reversal", "Calibration deployment observation ordering differs."),
        ("adjacent_swap", "Calibration deployment observation ordering differs."),
        (
            "rotated_identity_sequence",
            "Calibration deployment observation ordering differs.",
        ),
        ("foreign_identity", "Calibration deployment observation ordering differs."),
        (
            "equal_values_distinct_ids",
            "Calibration deployment observation population differs.",
        ),
        (
            "duplicate_identity",
            "Calibration deployment observation population differs.",
        ),
        ("missing", "Calibration deployment observation population differs."),
        ("extra", "Calibration deployment observation population differs."),
        (
            "order_plus_later_key",
            "Calibration deployment observation ordering differs.",
        ),
        ("ordered_outcome", "Calibration deployment observation population differs."),
    ),
)
def test_observation_deployment_tuple_validation_stops_before_scoring(
    mutation: str,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run("calibrated_ig", "g_adam_lmh")
    assert run.calibration is not None
    corrupted = replace(
        run,
        calibration=replace(
            run.calibration,
            observations=_mutated_deployment_observations(run, mutation),
        ),
    )
    scoring_called = False

    def forbidden_scoring(*args: object, **kwargs: object) -> None:
        nonlocal scoring_called
        del args, kwargs
        scoring_called = True
        raise AssertionError("planner scoring must not run")

    monkeypatch.setattr(runner_module, "_decide", forbidden_scoring)
    with pytest.raises(RunProvenanceError) as captured:
        replay_decisions(corrupted)
    assert str(captured.value) == message
    assert scoring_called is False


@pytest.mark.sigma_reconstruction
def test_valid_deployment_order_preserves_deterministic_scientific_run() -> None:
    run = _run("calibrated_ig", "g_adam_lmh")
    repeated = _run("calibrated_ig", "g_adam_lmh")
    assert run == repeated
    assert run.calibration is not None
    assert repeated.calibration is not None

    before = (
        run,
        runner_module.validated_calibration_history_selections(run),
    )
    replayed = replay_decisions(run)
    canonical_effects = runner_module.validate_recorded_calibration(run)
    after = (
        run,
        runner_module.validated_calibration_history_selections(run),
    )

    assert before == after
    assert run.run_id == "run:d16c536d5ee8b94ec372d5ef28cbe71a3854f7249588abea9d275ca3176a0b93"
    assert (
        run.comparison_id
        == "comparison:6a353d795300a7ae2b1303052d23c8e21a387af5e20d3100acbed7769ca32014"
    )
    assert run.selected_candidate_ids == (
        "irrelevant-objective-r1",
        "redundant-objective-r1",
        "g00-adam-r1",
    )
    assert replayed == tuple(decision.policy_trace for decision in run.decisions)
    assert tuple(
        (
            estimate.sample_mean,
            estimate.raw_sample_standard_deviation,
            estimate.estimated_sigma,
        )
        for estimate in run.calibration.estimates
    ) == (
        (0.1276892162048, 0.029254340466194934, 0.05),
        (0.177758292114, 0.17301458048901713, 0.17301458048901713),
        (0.17716358818539998, 0.21926050604680192, 0.21926050604680192),
    )
    assert tuple(selection.selection_identity for selection in before[1]) == (
        "5c143dd7e99cefc271979494c9d17b4019ddb163259beed53523d0ade84c5255",
        "672577ce88847bb7e416d3dbfb55a6cb245d304092344ae7100dbb284740a0a2",
        "b00869092e245b61d0273451b4e94f0d4bd36d73be1cb63a492912063217186f",
    )
    assert canonical_effects == run.calibration.effects
    assert run.calibration.effects == tuple(
        effect for estimate in run.calibration.estimates for effect in estimate.effects
    )
    assert run.calibration.observations == tuple(
        observation
        for estimate in run.calibration.estimates
        for observation in estimate.observations
    )
    assert run.effect_history == repeated.effect_history
    assert (run.decision_cost, run.calibration_cost, run.calibration.cost) == (
        2.25,
        30.0,
        30.0,
    )
    assert (run.terminal_reason, run.run_status) == ("budget_exhausted", "complete")


@pytest.mark.sigma_reconstruction
def test_calibration_chronology_rejects_real_decision_effect_before_scoring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run("calibrated_lookahead", "g_adam_lmh")
    assert run.calibration is not None
    estimate = run.calibration.estimates[0]
    decision_effect = next(
        item
        for item in run.effect_history
        if item.source_kind == "decision"
        and item.comparison_group_id == estimate.comparison_group_id
    )
    assert decision_effect.available_sequence == 1
    changed_estimate = _rehash_estimate(
        replace(
            estimate,
            source_effect_ids=(decision_effect.effect_id, *estimate.source_effect_ids[1:]),
        )
    )
    corrupted = _replace_first_estimate(run, changed_estimate)
    scoring_called = False

    def forbidden_scoring(*args: object, **kwargs: object) -> None:
        nonlocal scoring_called
        del args, kwargs
        scoring_called = True
        raise AssertionError("planner scoring must not run")

    monkeypatch.setattr(runner_module, "_decide", forbidden_scoring)
    with pytest.raises(RunProvenanceError) as captured:
        replay_decisions(corrupted)
    assert str(captured.value) == "Complete recorded calibration estimate does not reproduce."
    assert scoring_called is False


@pytest.mark.sigma_reconstruction
def test_estimator_semantics_are_independently_reconstructed_from_five_matched_effects() -> None:
    for world_id, floor_expected in (("h_adam_low", True), ("h_adam_high", False)):
        sources = runner_module.reconstruct_calibration_sources(
            run_id=f"semantic-proof/{world_id}",
            world_id=world_id,
            seed=9000,
            comparison_group_id=GROUP_IDS[0],
        )
        values = tuple(sources.effect_values)
        assert len(values) == sources.sample_count == 5
        assert tuple(effect.observed_effect for effect in sources.effects) == values
        assert all(effect.available_sequence == 0 for effect in sources.effects)
        for index, (adam, sgd) in enumerate(sources.source_candidate_pairs, start=1):
            assert adam.endswith(f"adam-r{index:04d}")
            assert sgd.endswith(f"sgd-r{index:04d}")
            left = sources.observations[2 * (index - 1)]
            right = sources.observations[2 * (index - 1) + 1]
            assert values[index - 1] == round(
                left.revealed_observation - right.revealed_observation,
                12,
            )
        manual_mean = math.fsum(values) / 5
        manual_sample_sd = math.sqrt(math.fsum((value - manual_mean) ** 2 for value in values) / 4)
        population_sd = math.sqrt(math.fsum((value - manual_mean) ** 2 for value in values) / 5)
        assert math.isclose(sources.sample_mean, manual_mean, rel_tol=0.0, abs_tol=1e-15)
        assert math.isclose(
            sources.sample_standard_deviation,
            manual_sample_sd,
            rel_tol=0.0,
            abs_tol=1e-15,
        )
        assert f64(sources.sample_standard_deviation) != f64(population_sd)
        assert sources.sigma_floor == 0.05
        assert math.isclose(
            sources.estimated_sigma,
            max(manual_sample_sd, 0.05),
            rel_tol=0.0,
            abs_tol=1e-15,
        )
        assert (sources.estimated_sigma == sources.sigma_floor) is floor_expected


@pytest.mark.sigma_reconstruction
def test_extra_pre_cutoff_decision_effect_fails_at_sigma_guard_before_scoring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run("calibrated_lookahead", "g_adam_lmh")
    decision_effect = next(item for item in run.effect_history if item.source_kind == "decision")
    corrupted = replace(
        run,
        effect_history=(*run.effect_history, replace(decision_effect, available_sequence=0)),
    )
    scoring_called = False

    def forbidden_scoring(*args: object, **kwargs: object) -> None:
        nonlocal scoring_called
        del args, kwargs
        scoring_called = True
        raise AssertionError("planner scoring must not run")

    monkeypatch.setattr(runner_module, "_decide", forbidden_scoring)
    with pytest.raises(RunProvenanceError) as captured:
        replay_decisions(corrupted)
    assert type(captured.value).__name__ == "RunProvenanceError"
    assert str(captured.value) == "Calibration history contains a duplicate effect ID."
    assert scoring_called is False


@pytest.mark.oracle_reconstruction
@pytest.mark.parametrize(
    "field",
    (
        "oracle_key_id",
        "oracle_use_id",
        "authorization_id",
        "world_id",
        "seed",
        "candidate_id",
        "replication_id",
        "namespace",
        "comparison_group_id",
        "intervention_arm",
        "key_fields",
        "serialized_key_hex",
        "digest",
        "u",
        "z",
        "revealed_observation",
        "outcome_digest",
    ),
)
def test_calibration_oracle_reobservation_rejects_corruption_before_scoring(
    field: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run("calibrated_ig", "g_adam_lmh")
    assert run.calibration is not None
    estimate = run.calibration.estimates[0]
    observation = estimate.observations[0]
    if field == "oracle_key_id":
        changed_observation = replace(
            observation, oracle_key_id=f"{observation.oracle_key_id}/forged"
        )
    elif field == "oracle_use_id":
        changed_observation = replace(
            observation, oracle_use_id=f"{observation.oracle_use_id}/forged"
        )
    elif field == "authorization_id":
        changed_observation = replace(
            observation, authorization_id=f"{observation.authorization_id}/forged"
        )
    elif field == "world_id":
        changed_observation = replace(observation, world_id=f"{observation.world_id}/forged")
    elif field == "seed":
        changed_observation = replace(observation, seed=observation.seed + 1)
    elif field == "candidate_id":
        changed_observation = replace(
            observation, candidate_id=f"{observation.candidate_id}/forged"
        )
    elif field == "replication_id":
        changed_observation = replace(
            observation, replication_id=f"{observation.replication_id}/forged"
        )
    elif field == "namespace":
        changed_observation = replace(observation, namespace=f"{observation.namespace}/forged")
    elif field == "comparison_group_id":
        changed_observation = replace(
            observation,
            comparison_group_id=f"{observation.comparison_group_id}/forged",
        )
    elif field == "intervention_arm":
        changed_observation = replace(
            observation,
            intervention_arm="sgd" if observation.intervention_arm == "adam" else "adam",
        )
    elif field == "key_fields":
        changed_observation = replace(
            observation,
            key_fields=(*observation.key_fields[:-1], f"{observation.key_fields[-1]}/forged"),
        )
    elif field == "serialized_key_hex":
        changed_observation = replace(
            observation,
            serialized_key_hex=f"{observation.serialized_key_hex}00",
        )
    elif field == "digest":
        changed_observation = replace(observation, digest="0" * 64)
    elif field == "u":
        changed_observation = replace(observation, u="0.5")
    elif field == "z":
        changed_observation = replace(observation, z="0.0")
    elif field == "revealed_observation":
        changed_observation = replace(
            observation,
            revealed_observation=observation.revealed_observation + 1.0,
        )
    else:
        changed_observation = replace(observation, outcome_digest="0" * 64)
    if field in {"oracle_key_id", "revealed_observation"}:
        changed_observation = replace(
            changed_observation,
            outcome_digest=protocol_hash(
                "revealed_outcome/v1",
                {
                    "oracle_key_id": changed_observation.oracle_key_id,
                    "revealed_observation": f64(changed_observation.revealed_observation),
                },
            ),
        )
    changed_estimate = replace(
        estimate,
        observations=(changed_observation, *estimate.observations[1:]),
    )
    corrupted = _replace_first_estimate(run, changed_estimate)
    scoring_called = False

    def forbidden_scoring(*args: object, **kwargs: object) -> None:
        nonlocal scoring_called
        del args, kwargs
        scoring_called = True
        raise AssertionError("planner scoring must not run")

    monkeypatch.setattr(runner_module, "_decide", forbidden_scoring)
    with pytest.raises(RunProvenanceError) as captured:
        replay_decisions(corrupted)
    assert str(captured.value) == (
        "Calibration source observation does not reproduce from the frozen Oracle."
    )
    assert scoring_called is False


@pytest.mark.oracle_reconstruction
def test_corrupt_calibration_observation_fails_before_effect_or_sigma_derivation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corrupted = _corrupt_first_calibration_observation(_run("calibrated_ig", "g_adam_lmh"))
    effect_called = False
    stdev_called = False
    scoring_called = False

    def forbidden_effect(*args: object, **kwargs: object) -> None:
        nonlocal effect_called
        del args, kwargs
        effect_called = True
        raise AssertionError("matched-effect reconstruction must not run")

    def forbidden_stdev(*args: object, **kwargs: object) -> None:
        nonlocal stdev_called
        del args, kwargs
        stdev_called = True
        raise AssertionError("sigma reconstruction must not run")

    def forbidden_scoring(*args: object, **kwargs: object) -> None:
        nonlocal scoring_called
        del args, kwargs
        scoring_called = True
        raise AssertionError("planner scoring must not run")

    monkeypatch.setattr(runner_module, "expected_calibration_effect", forbidden_effect)
    monkeypatch.setattr(statistics, "stdev", forbidden_stdev)
    monkeypatch.setattr(runner_module, "_decide", forbidden_scoring)
    with pytest.raises(RunProvenanceError) as captured:
        replay_decisions(corrupted)
    assert str(captured.value) == (
        "Calibration source observation does not reproduce from the frozen Oracle."
    )
    assert effect_called is False
    assert stdev_called is False
    assert scoring_called is False


def test_fixed_arm_calibration_contamination_fails_before_reconstruction_or_scoring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed = _run("fixed_ig", "g_adam_lmh")
    calibrated = _run("calibrated_ig", "g_adam_lmh")
    assert calibrated.calibration is not None
    contaminated = replace(
        fixed,
        calibration=calibrated.calibration,
        calibration_cost=calibrated.calibration_cost,
    )
    reconstruction_called = False
    scoring_called = False

    def forbidden_reconstruction(*args: object, **kwargs: object) -> None:
        nonlocal reconstruction_called
        del args, kwargs
        reconstruction_called = True
        raise AssertionError("fixed arms must not reconstruct calibration")

    def forbidden_scoring(*args: object, **kwargs: object) -> None:
        nonlocal scoring_called
        del args, kwargs
        scoring_called = True
        raise AssertionError("planner scoring must not run")

    monkeypatch.setattr(
        runner_module,
        "reconstruct_calibration_sources",
        forbidden_reconstruction,
    )
    monkeypatch.setattr(runner_module, "_decide", forbidden_scoring)
    with pytest.raises(RunProvenanceError, match="Fixed arm consumed a calibration deployment"):
        replay_decisions(contaminated)
    assert reconstruction_called is False
    assert scoring_called is False


@pytest.mark.sigma_reconstruction
def test_calibration_sigma_sources_are_strictly_prior_and_fixed_path_is_distinct() -> None:
    calibrated = _run("calibrated_ig", "g_adam_lmh")
    assert calibrated.calibration is not None
    for estimate in calibrated.calibration.estimates:
        assert all(
            effect.available_sequence < estimate.source_sequence_cutoff
            for effect in estimate.effects
        )
    replay_decisions(calibrated)

    fixed = _run("fixed_ig", "g_adam_lmh")
    assert fixed.calibration is None
    assert all(effect.source_kind != "calibration" for effect in fixed.effect_history)
    replay_decisions(fixed)
