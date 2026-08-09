import json
import sqlite3
from pathlib import Path

from research_decision_engine.optimizer_effect import synchronize_optimizer_reasoning
from research_decision_engine.runner import run_next, suggest_information_gain
from research_decision_engine.storage import SCHEMA_VERSION, ExperimentStore
from research_decision_engine.types import Candidate, ExperimentRecord
from research_decision_engine.world import DeterministicSyntheticWorld
from tests.sqlite_migration_helpers import downgrade_to_exact_schema


def test_sqlite_store_records_experiment_history(tmp_path: Path) -> None:
    db_path = tmp_path / "rde.sqlite"

    with ExperimentStore(db_path) as store:
        store.init_schema()
        record = run_next(store, policy_name="greedy", seed=0)
        records = store.list_records()

    assert record.record_id == 1
    assert len(records) == 1
    assert records[0].candidate.candidate_id == "cand-000"


def test_schema_migration_preserves_legacy_experiment_history(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE experiments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id TEXT NOT NULL UNIQUE,
            policy TEXT NOT NULL,
            observed_value REAL NOT NULL,
            true_value REAL NOT NULL,
            cost REAL NOT NULL,
            created_at TEXT NOT NULL,
            params_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO experiments (
            candidate_id, policy, observed_value, true_value, cost, created_at, params_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy-candidate",
            "random",
            0.5,
            0.51,
            1.0,
            "2026-01-01T00:00:00+00:00",
            json.dumps(
                {
                    "learning_rate": 0.01,
                    "regularization": 0.001,
                    "model_width": 32,
                    "optimizer": "sgd",
                },
                sort_keys=True,
            ),
        ),
    )
    connection.commit()
    connection.close()

    with ExperimentStore(db_path) as store:
        store.init_schema()
        records = store.list_records()

        assert store.schema_version() == SCHEMA_VERSION
        assert len(records) == 1
        assert records[0].candidate.candidate_id == "legacy-candidate"


def test_v3_migration_preserves_v2_reasoning_history(tmp_path: Path) -> None:
    db_path = tmp_path / "reasoning-v2.sqlite"
    world = DeterministicSyntheticWorld()

    with ExperimentStore(db_path) as store:
        store.init_schema()
        _add_candidate(store, world.candidates()[0])
        _add_candidate(store, world.candidates()[1])
        synchronize_optimizer_reasoning(store)
        assert len(store.list_belief_updates()) == 1

    connection = sqlite3.connect(db_path)
    downgrade_to_exact_schema(connection, 2)
    connection.close()

    with ExperimentStore(db_path) as store:
        store.init_schema()
        current = store.current_belief_state()

        assert store.schema_version() == SCHEMA_VERSION
        assert len(store.list_records()) == 2
        assert len(store.list_evidence()) == 1
        assert len(store.list_belief_updates()) == 1
        assert current is not None
        assert current.sequence == 1


def test_v4_migration_preserves_v3_decision_history(tmp_path: Path) -> None:
    db_path = tmp_path / "decision-v3.sqlite"

    with ExperimentStore(db_path) as store:
        store.init_schema()
        trace = suggest_information_gain(store, max_cost=1.0)
        assert len(store.list_decision_traces()) == 1

    connection = sqlite3.connect(db_path)
    downgrade_to_exact_schema(connection, 3)
    connection.close()

    with ExperimentStore(db_path) as store:
        store.init_schema()

        assert store.schema_version() == SCHEMA_VERSION
        assert store.get_decision_trace(trace.suggestion_id) == trace
        assert store.list_lookahead_plan_traces() == []


def _add_candidate(store: ExperimentStore, candidate: Candidate) -> ExperimentRecord:
    observed_value, true_value, cost = DeterministicSyntheticWorld().evaluate(candidate)
    return store.add_record(
        ExperimentRecord.new(
            candidate=candidate,
            policy="test",
            observed_value=observed_value,
            true_value=true_value,
            cost=cost,
        )
    )
