from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from research_decision_engine.belief_models import (
    CALIBRATED_SIGMA_MODEL_ID,
    MatchedEffectObservation,
    belief_models,
    initial_model_lineage,
)
from research_decision_engine.benchmarks.worlds import (
    build_benchmark_world,
    paired_evaluation_worlds,
)
from research_decision_engine.calibration import build_calibration_prefix
from research_decision_engine.optimizer_effect import synchronize_optimizer_reasoning
from research_decision_engine.reasoning import DuplicateEvidenceError
from research_decision_engine.robust_storage import RobustBeliefStore
from research_decision_engine.storage import SCHEMA_VERSION, ExperimentStore
from research_decision_engine.types import ExperimentRecord
from tests.sqlite_migration_helpers import downgrade_to_exact_schema


def test_v5_migration_preserves_existing_experiment_and_reasoning_rows(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "migration.sqlite"
    with ExperimentStore(db_path) as store:
        store.init_schema()
        record = _persist_matched_pair(store)[0]
        synchronize_optimizer_reasoning(store)
        evidence_ids = [item.evidence_id for item in store.list_evidence()]

    connection = sqlite3.connect(db_path)
    downgrade_to_exact_schema(connection, 4)
    connection.close()

    with ExperimentStore(db_path) as store:
        store.init_schema()
        assert store.connection is not None
        tables = {
            str(row[0])
            for row in store.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert store.schema_version() == SCHEMA_VERSION
        assert store.get_record(record.record_id or 0).candidate.candidate_id == (
            record.candidate.candidate_id
        )
        assert [item.evidence_id for item in store.list_evidence()] == evidence_ids
        assert "belief_model_lineages" in tables
        assert "sigma_estimates" in tables
        assert "model_adequacy_diagnostics" in tables


def test_robust_records_are_persisted_traceable_isolated_and_costed(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "robust.sqlite"
    config = paired_evaluation_worlds()[2]
    design, world = build_benchmark_world(config, seed=4)
    prefix = build_calibration_prefix(
        world_id=config.world_id,
        evaluation_seed=4,
        designs=design.evidence_eligibility().designs,
        candidates={item.candidate_id: item for item in design.candidates},
        cost=design.cost,
        observe_pair=world.observe_calibration_pair,
        created_at="t0",
    )

    with ExperimentStore(db_path) as store:
        store.init_schema()
        robust = RobustBeliefStore(store)
        robust.add_calibration_prefix(prefix)
        pair_candidates = [
            item
            for item in design.candidates
            if item.candidate_id in {"pair-00-sgd", "pair-00-adam"}
        ]
        records = []
        for candidate in pair_candidates:
            records.append(
                store.add_record(
                    ExperimentRecord(
                        record_id=None,
                        candidate=candidate,
                        policy="test",
                        observed_value=world.observe(candidate),
                        true_value=world.observe(candidate),
                        cost=design.cost(candidate),
                        created_at=f"t-{candidate.candidate_id}",
                    )
                )
            )
        synchronize_optimizer_reasoning(store, eligibility=design.evidence_eligibility())
        evidence = store.list_evidence()[0]
        calibration_history = tuple(
            MatchedEffectObservation.from_calibration(item) for item in prefix.matched_effects
        )
        update_ids = []
        for model in belief_models():
            lineage = initial_model_lineage(model, lineage_key="persisted", created_at="t0")
            robust.add_lineage(lineage)
            _, update, _ = model.update(
                lineage=lineage,
                evidence=evidence,
                effect_history=calibration_history,
                diagnostic_history=(),
            )
            robust.add_model_update(update, effect_history=calibration_history)
            update_ids.append(update.model_update_id)
            with pytest.raises(DuplicateEvidenceError):
                robust.add_model_update(update, effect_history=calibration_history)

        robust.add_decision_cost(run_id="run", record=records[0])
        conflicting_key = f"calibration-arm:{prefix.arms[0].calibration_arm_id}"
        with pytest.raises(sqlite3.IntegrityError, match="calibration ledger"):
            robust.add_decision_cost(
                run_id="run",
                record=records[1],
                source_record_key=conflicting_key,
            )
        robust.add_decision_cost(run_id="run", record=records[1])

        estimates = robust.sigma_estimates()
        calibrated = next(item for item in estimates if item["status"] == "calibrated")
        explanation = robust.explain_sigma_estimate(str(calibrated["id"]))
        assert explanation is not None
        assert explanation["sample_count"] == 5
        assert len(explanation["sources"]) == 5
        assert all(item["source_kind"] == "calibration" for item in explanation["sources"])
        assert all(item["observed_effect"] is not None for item in explanation["sources"])
        assert len(robust.belief_lineages()) == 2
        assert len({item["current_state_id"] for item in robust.belief_lineages()}) == 2
        assert len(robust.model_adequacy()) == 2
        assert len(update_ids) == len(set(update_ids))
        assert store.connection is not None
        default_models = store.connection.execute(
            "SELECT id FROM belief_models WHERE is_default = 1"
        ).fetchall()
        assert [str(item[0]) for item in default_models] == [CALIBRATED_SIGMA_MODEL_ID]
        cost = robust.cost_summary()
        assert cost["calibration_cost"] == pytest.approx(prefix.calibration_cost)
        assert cost["decision_cost"] == pytest.approx(sum(item.cost for item in records))
        assert cost["total_cost"] == pytest.approx(cost["calibration_cost"] + cost["decision_cost"])


def _persist_matched_pair(store: ExperimentStore) -> tuple[ExperimentRecord, ...]:
    from research_decision_engine.world import DeterministicSyntheticWorld

    world = DeterministicSyntheticWorld()
    records = []
    for candidate in world.candidates()[:2]:
        observed_value, true_value, cost = world.evaluate(candidate)
        records.append(
            store.add_record(
                ExperimentRecord(
                    record_id=None,
                    candidate=candidate,
                    policy="test",
                    observed_value=observed_value,
                    true_value=true_value,
                    cost=cost,
                    created_at=f"t-{candidate.candidate_id}",
                )
            )
        )
    return tuple(records)
