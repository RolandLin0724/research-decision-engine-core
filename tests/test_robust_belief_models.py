from __future__ import annotations

import inspect
import statistics

import pytest

from research_decision_engine.belief_models import (
    CALIBRATED_SIGMA_MODEL_ID,
    FIXED_SIGMA_MODEL_ID,
    MatchedEffectObservation,
    ModelAdequacyDiagnostic,
    belief_model,
    initial_model_lineage,
)
from research_decision_engine.benchmarks.evaluation import run_benchmark_condition
from research_decision_engine.benchmarks.robust_evaluation import replay_decision_stream
from research_decision_engine.benchmarks.worlds import (
    BenchmarkDesign,
    build_benchmark_world,
    paired_evaluation_worlds,
)
from research_decision_engine.calibration import (
    CalibrationPairObserver,
    CalibrationPrefix,
    CalibrationReplicationContract,
    DuplicateCalibrationConsumptionError,
    build_calibration_prefix,
)
from research_decision_engine.reasoning import Evidence, Provenance, ReasoningError


def test_calibrated_sigma_uses_ddof_one_floor_and_strictly_prior_effects() -> None:
    model = belief_model(CALIBRATED_SIGMA_MODEL_ID)
    lineage = initial_model_lineage(model, lineage_key="sigma-test", created_at="t0")
    evidence = _evidence("current", 0.2)
    prior_values = (0.0, 0.1, 0.2, 0.3, 0.4)
    history = tuple(
        _effect(f"prior-{index}", value, available_sequence=0)
        for index, value in enumerate(prior_values)
    )
    contaminated_history = (
        *history,
        _effect(evidence.evidence_id, 99.0, available_sequence=0),
        _effect("future", 99.0, available_sequence=2),
    )

    _, update, _ = model.update(
        lineage=lineage,
        evidence=evidence,
        effect_history=contaminated_history,
        diagnostic_history=(),
    )
    _, clean_update, _ = model.update(
        lineage=lineage,
        evidence=evidence,
        effect_history=history,
        diagnostic_history=(),
    )

    estimate = update.sigma_estimate
    assert estimate.status == "calibrated"
    assert estimate.sample_count == 5
    assert estimate.sample_mean == pytest.approx(statistics.fmean(prior_values))
    assert estimate.raw_sample_standard_deviation == pytest.approx(statistics.stdev(prior_values))
    assert estimate.estimated_sigma == pytest.approx(statistics.stdev(prior_values))
    assert evidence.evidence_id not in estimate.source_effect_ids
    assert "future" not in estimate.source_effect_ids
    assert estimate.estimated_sigma == clean_update.sigma_estimate.estimated_sigma
    assert estimate.source_effect_ids == clean_update.sigma_estimate.source_effect_ids
    assert estimate.sigma_floor == 0.05
    assert estimate.variance_floor == 0.0025
    assert dict(
        model.calculate_likelihoods(evidence=evidence, sigma_estimate=estimate)
    ) == pytest.approx(
        {item.hypothesis_id: item.likelihood for item in update.bayesian_update.likelihoods}
    )
    with pytest.raises(ReasoningError, match="next update sequence"):
        model.select_sigma(
            lineage=lineage,
            evidence=evidence,
            comparison_group_id="group-a",
            cutoff_sequence=2,
            effect_history=history,
        )

    constant_history = tuple(
        _effect(f"constant-{index}", 0.12, available_sequence=0) for index in range(5)
    )
    _, floored_update, _ = model.update(
        lineage=initial_model_lineage(model, lineage_key="floor-test", created_at="t0"),
        evidence=_evidence("floor", 0.12),
        effect_history=constant_history,
        diagnostic_history=(),
    )
    assert floored_update.sigma_estimate.raw_sample_standard_deviation == 0.0
    assert floored_update.sigma_estimate.estimated_sigma == 0.05


def test_fewer_than_five_prior_effects_uses_declared_fallback() -> None:
    model = belief_model(CALIBRATED_SIGMA_MODEL_ID)
    lineage = initial_model_lineage(model, lineage_key="fallback", created_at="t0")
    _, update, _ = model.update(
        lineage=lineage,
        evidence=_evidence("fallback", 0.1),
        effect_history=tuple(_effect(f"p-{index}", float(index), 0) for index in range(4)),
        diagnostic_history=(),
    )
    assert update.sigma_estimate.status == "baseline_fallback"
    assert update.sigma_estimate.sample_count == 4
    assert update.sigma_estimate.estimated_sigma == 0.05


def test_fixed_model_exactly_reproduces_existing_controller_probabilities() -> None:
    config = paired_evaluation_worlds()[2]
    design, world = build_benchmark_world(config, seed=3)
    prefix = _prefix(config.world_id, 3, design, world.observe_calibration_pair)
    controller = run_benchmark_condition(
        world_config=config,
        policy="lookahead_information_gain",
        seed=3,
        budget=4.5,
        generated_at="t0",
    )
    replay = replay_decision_stream(
        model=belief_model(FIXED_SIGMA_MODEL_ID),
        controller=controller,
        design=design,
        prefix=prefix,
        lineage_key="fixed-equivalence",
    )

    assert [item.candidate_id for item in replay.experiment_trace] == [
        item.candidate_id for item in controller.trace
    ]
    for model_step, controller_step in zip(replay.experiment_trace, controller.trace, strict=True):
        assert dict(model_step.posterior_probabilities) == pytest.approx(
            dict(controller_step.posterior_probabilities), abs=1e-15
        )
    assert all(item.sigma_estimate.estimated_sigma == 0.05 for item in replay.updates)


def test_calibration_prefix_preserves_priors_and_uses_independent_arm_noise() -> None:
    config = paired_evaluation_worlds()[0]
    design, world = build_benchmark_world(config, seed=7)
    prefix = _prefix(config.world_id, 7, design, world.observe_calibration_pair)
    model = belief_model(CALIBRATED_SIGMA_MODEL_ID)
    lineage = initial_model_lineage(model, lineage_key="prior", created_at="t0")

    assert lineage.current_state.state.sequence == 0
    assert lineage.current_state.state.posterior_probabilities == (
        1.0 / 3.0,
        1.0 / 3.0,
        1.0 / 3.0,
    )
    assert all(item.available_sequence == 0 for item in prefix.matched_effects)
    assert all(
        item.provenance.details_dict()["scientific_evidence"] is False
        for item in prefix.matched_effects
    )
    by_id = {item.calibration_arm_id: item for item in prefix.arms}
    for replication in prefix.replications:
        adam = by_id[replication.adam_arm_id]
        sgd = by_id[replication.sgd_arm_id]
        assert adam.shared_key == sgd.shared_key
        assert adam.arm_noise_key != sgd.arm_noise_key
        assert adam.replication_seed == sgd.replication_seed
    serialized = str(prefix.to_dict())
    assert "true_hypothesis" not in serialized
    assert "observation_noise_std" not in serialized


def test_duplicate_calibration_pair_consumption_fails_explicitly() -> None:
    config = paired_evaluation_worlds()[0]
    design, world = build_benchmark_world(config, seed=1)
    prefix = _prefix(config.world_id, 1, design, world.observe_calibration_pair)
    replication = prefix.replications[0]
    group = next(
        item
        for item in prefix.groups
        if item.calibration_group_id == replication.calibration_group_id
    )
    by_id = {item.calibration_arm_id: item for item in prefix.arms}
    contract = CalibrationReplicationContract()
    contract.consume(
        group=group,
        replication_id=replication.replication_id,
        replication_seed=replication.replication_seed,
        adam_arm=by_id[replication.adam_arm_id],
        sgd_arm=by_id[replication.sgd_arm_id],
        created_at="t1",
    )
    with pytest.raises(DuplicateCalibrationConsumptionError):
        contract.consume(
            group=group,
            replication_id=replication.replication_id,
            replication_seed=replication.replication_seed,
            adam_arm=by_id[replication.adam_arm_id],
            sgd_arm=by_id[replication.sgd_arm_id],
            created_at="t1",
        )


def test_lineages_are_isolated_and_updates_are_deterministic() -> None:
    fixed = belief_model(FIXED_SIGMA_MODEL_ID)
    calibrated = belief_model(CALIBRATED_SIGMA_MODEL_ID)
    fixed_lineage = initial_model_lineage(fixed, lineage_key="shared", created_at="t0")
    calibrated_lineage = initial_model_lineage(calibrated, lineage_key="shared", created_at="t0")
    evidence = _evidence("same", 0.07)
    history = tuple(_effect(f"p-{index}", 0.05 * index, 0) for index in range(5))

    fixed_after, fixed_update, _ = fixed.update(
        lineage=fixed_lineage,
        evidence=evidence,
        effect_history=history,
        diagnostic_history=(),
    )
    calibrated_after, calibrated_update, _ = calibrated.update(
        lineage=calibrated_lineage,
        evidence=evidence,
        effect_history=history,
        diagnostic_history=(),
    )
    calibrated_again, repeated_update, _ = calibrated.update(
        lineage=calibrated_lineage,
        evidence=evidence,
        effect_history=history,
        diagnostic_history=(),
    )

    assert fixed_lineage.current_state.state.sequence == 0
    assert calibrated_lineage.current_state.state.sequence == 0
    assert fixed_after.lineage_id != calibrated_after.lineage_id
    assert calibrated_after == calibrated_again
    assert calibrated_update == repeated_update
    with pytest.raises(ReasoningError, match="another model"):
        fixed.update(
            lineage=calibrated_lineage,
            evidence=evidence,
            effect_history=history,
            diagnostic_history=(),
        )
    assert fixed_update.belief_model_id == FIXED_SIGMA_MODEL_ID


def test_adequacy_states_follow_frozen_thresholds_deterministically() -> None:
    model = belief_model(FIXED_SIGMA_MODEL_ID)
    lineage = initial_model_lineage(model, lineage_key="adequacy", created_at="t0")
    effects: list[MatchedEffectObservation] = []
    diagnostics: list[ModelAdequacyDiagnostic] = []
    for index in range(10):
        evidence = _evidence(f"ordinary-{index}", 0.0, source_start=index * 2 + 1)
        lineage, update, effect = model.update(
            lineage=lineage,
            evidence=evidence,
            effect_history=tuple(effects),
            diagnostic_history=tuple(diagnostics),
        )
        effects.append(effect)
        diagnostics.append(update.diagnostic)
    assert diagnostics[0].adequacy_state == "uncertain"
    assert diagnostics[-1].adequacy_state == "adequate"

    extreme_model = belief_model(FIXED_SIGMA_MODEL_ID)
    _, extreme_update, _ = extreme_model.update(
        lineage=initial_model_lineage(extreme_model, lineage_key="alarm", created_at="t0"),
        evidence=_evidence("extreme", 0.8),
        effect_history=(),
        diagnostic_history=(),
    )
    assert extreme_update.diagnostic.tail_alarm
    assert extreme_update.diagnostic.adequacy_state == "appears_misspecified"


def test_model_and_calibration_interfaces_do_not_accept_hidden_truth() -> None:
    forbidden = {
        "true_hypothesis_id",
        "true_optimizer_effect",
        "observation_noise_std",
        "hidden_truth",
    }
    assert not forbidden.intersection(
        inspect.signature(belief_model(FIXED_SIGMA_MODEL_ID).update).parameters
    )
    assert not forbidden.intersection(inspect.signature(build_calibration_prefix).parameters)


def _prefix(
    world_id: str,
    seed: int,
    design: BenchmarkDesign,
    observer: CalibrationPairObserver,
) -> CalibrationPrefix:
    return build_calibration_prefix(
        world_id=world_id,
        evaluation_seed=seed,
        designs=design.evidence_eligibility().designs,
        candidates={item.candidate_id: item for item in design.candidates},
        cost=design.cost,
        observe_pair=observer,
        created_at="t0",
    )


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
        observed_outcome="test",
        provenance=Provenance.create(
            method="matched-optimizer-effect",
            version="test/v1",
            details={
                "comparison_group_id": "group-a",
                "source_experiment_status": "completed_successfully",
            },
        ),
        created_at=f"t-{suffix}",
    )


def _effect(
    effect_id: str,
    observed: float,
    available_sequence: int,
) -> MatchedEffectObservation:
    return MatchedEffectObservation(
        effect_id=effect_id,
        comparison_group_id="group-a",
        observed_effect=observed,
        available_sequence=available_sequence,
        source_kind="calibration",
        source_ids=(f"{effect_id}-adam", f"{effect_id}-sgd"),
        created_at="t0",
        provenance=Provenance.create(
            method="test-effect",
            version="test/v1",
            details={"effect_id": effect_id},
        ),
    )
