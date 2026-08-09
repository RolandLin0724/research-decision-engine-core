from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import cast

import pytest

import research_decision_engine.benchmarks.broader_runner as runner_module
from research_decision_engine.belief_models import MatchedEffectObservation
from research_decision_engine.benchmarks.broader_audits import (
    IntegrityAuditContext,
    evaluate_audit,
)
from research_decision_engine.benchmarks.broader_calibration_history import (
    CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
    CalibrationHistorySelection,
)
from research_decision_engine.benchmarks.broader_oracle import RevealedObservation
from research_decision_engine.benchmarks.broader_projection import (
    _calibration_rows,
    _oracle_rows,
)
from research_decision_engine.benchmarks.broader_protocol import canonical_json_bytes, f64
from research_decision_engine.benchmarks.broader_runner import (
    calibration_sigma_provenance_sha256,
    reconstruct_calibration_sources,
    replay_decisions,
    validated_calibration_history_selections,
)
from tests.taskc_calibration_harness import calibrated_deployment_runs, calibrated_run


def _recording_selector(
    observed: list[str],
) -> Callable[..., CalibrationHistorySelection]:
    authoritative = runner_module.select_calibration_history

    def select(
        *,
        run_id: str,
        world_id: str,
        seed: int,
        comparison_group_id: str,
        recorded_observations: Sequence[RevealedObservation] | None = None,
        recorded_effects: Sequence[MatchedEffectObservation] | None = None,
        source_sequence_cutoff: int = CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
    ) -> CalibrationHistorySelection:
        selection = authoritative(
            run_id=run_id,
            world_id=world_id,
            seed=seed,
            comparison_group_id=comparison_group_id,
            recorded_observations=recorded_observations,
            recorded_effects=recorded_effects,
            source_sequence_cutoff=source_sequence_cutoff,
        )
        observed.append(selection.selection_identity)
        return selection

    return select


@pytest.mark.taskc_consumer_consistency
def test_reconstruction_validation_projection_and_provenance_share_one_selection_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = calibrated_run()
    runs = calibrated_deployment_runs()
    assert run.calibration is not None
    expected = validated_calibration_history_selections(run)
    expected_ids = {item.selection_identity for item in expected}
    observed: list[str] = []
    monkeypatch.setattr(runner_module, "select_calibration_history", _recording_selector(observed))

    reconstruction = reconstruct_calibration_sources(
        run_id=run.run_id,
        world_id=run.world_id,
        seed=run.seed,
        comparison_group_id=expected[0].comparison_group_id,
        recorded_observations=run.calibration.estimates[0].observations,
        recorded_effects=run.effect_history,
    )
    assert reconstruction.selection.selection_identity == expected[0].selection_identity
    assert set(observed) == {expected[0].selection_identity}

    observed.clear()
    validated = validated_calibration_history_selections(run)
    assert tuple(item.selection_identity for item in validated) == tuple(
        item.selection_identity for item in expected
    )
    assert set(observed) == expected_ids

    observed.clear()
    rows = _calibration_rows(runs)
    assert set(observed) == expected_ids
    by_group = {item.comparison_group_id: item for item in expected}
    for row in rows:
        selection = by_group[str(row["comparison_group_id"])]
        assert tuple(cast(list[str], row["effect_ids"])) == selection.source_effect_ids
        assert tuple(cast(list[str], row["replication_ids"])) == (selection.source_replication_ids)
        assert (
            tuple(tuple(item) for item in cast(list[list[str]], row["source_candidate_pairs"]))
            == selection.source_candidate_pairs
        )
        assert tuple(cast(list[str], row["source_oracle_key_ids"])) == (
            selection.source_oracle_key_ids
        )
        assert tuple(cast(list[str], row["effect_values"])) == tuple(
            f64(item) for item in selection.effect_values
        )
        assert row["sample_mean"] == f64(selection.sample_mean)
        assert row["sample_standard_deviation"] == f64(selection.sample_standard_deviation)

    estimate = run.calibration.estimates[0]
    assert estimate.provenance_sha256 == calibration_sigma_provenance_sha256(
        sigma_estimate_id=estimate.sigma_estimate_id,
        calibration_prefix_id=estimate.calibration_prefix_id,
        comparison_group_id=estimate.comparison_group_id,
        source_effect_ids=expected[0].source_effect_ids,
        source_sequence_cutoff=expected[0].source_sequence_cutoff,
        sample_count=expected[0].sample_count,
        sample_mean=expected[0].sample_mean,
        raw_sample_standard_deviation=expected[0].sample_standard_deviation,
        ddof=expected[0].ddof,
        sigma_floor=expected[0].sigma_floor,
        estimated_sigma=expected[0].estimated_sigma,
        belief_model_id=estimate.belief_model_id,
        lineage_id=estimate.lineage_id,
        effects=expected[0].effects,
    )


@pytest.mark.taskc_consumer_consistency
def test_replay_oracle_projection_and_audits_consume_the_same_selection_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = calibrated_run()
    runs = calibrated_deployment_runs()
    expected_ids = {
        item.selection_identity for item in validated_calibration_history_selections(run)
    }
    observed: list[str] = []
    monkeypatch.setattr(runner_module, "select_calibration_history", _recording_selector(observed))

    replay_decisions(run)
    assert set(observed) == expected_ids

    observed.clear()
    oracle_rows = _oracle_rows(runs)
    assert oracle_rows
    assert set(observed) == expected_ids

    context = IntegrityAuditContext(
        runs=runs,
        replay_runs=(),
        first_payload=canonical_json_bytes([item.run_id for item in runs], final_lf=True),
        replay_payload=b"",
        historical_before=(),
        historical_after=(),
    )
    observed.clear()
    assert evaluate_audit("A05-COMMON-RANDOMNESS", context).status == "PASS"
    assert set(observed) == expected_ids

    observed.clear()
    assert evaluate_audit("A08-CALIBRATION-SEPARATION", context).status == "PASS"
    assert set(observed) == expected_ids

    observed.clear()
    planner_audit = evaluate_audit("A09-PLANNER-AND-EVIDENCE", context)
    assert planner_audit.status == "INCONCLUSIVE"
    assert "Local planner/evidence checks passed" in planner_audit.detail
    assert set(observed) == expected_ids
