from __future__ import annotations

import random
import sqlite3
from pathlib import Path
from typing import cast

import pytest

from research_decision_engine import (
    CandidateSpec,
    NormalizedObservation,
    PythonFunctionAdapter,
    RunSpec,
    run_workload_experiment,
)
from research_decision_engine.policies import RandomPolicy
from research_decision_engine.runner import run_next
from research_decision_engine.storage import SCHEMA_VERSION, ExperimentStore
from research_decision_engine.types import Candidate
from tests.sqlite_migration_helpers import downgrade_to_exact_schema


def _spec(
    *,
    count: int = 2,
    cost_budget: float | None = None,
    adapter_id: str = "example-score",
) -> RunSpec:
    return RunSpec(
        candidates=[
            CandidateSpec("candidate-a", {"x": 1.0}),
            CandidateSpec("candidate-b", {"x": 2.0}),
            CandidateSpec("candidate-c", {"x": 3.0}),
        ],
        policy_id="random",
        policy_config={},
        policy_seed=11,
        experiment_count_budget=count,
        cost_budget=cost_budget,
        adapter_id=adapter_id,
        adapter_version="1",
        objective_name="score",
        objective_direction="maximize",
        tie_break="candidate-order",
    )


def _adapter(
    seen: list[CandidateSpec], *, adapter_id: str = "example-score", cost: float = 0.25
) -> PythonFunctionAdapter:
    def evaluate(candidate: CandidateSpec) -> NormalizedObservation:
        seen.append(candidate)
        assert type(candidate) is CandidateSpec
        assert not hasattr(candidate, "true_value")
        return NormalizedObservation(
            objective_value=cast(float, candidate.parameters["x"]) * 10.0,
            cost=cost,
        )

    return PythonFunctionAdapter(
        evaluate,
        adapter_id=adapter_id,
        adapter_version="1",
    )


def test_runspec_policy_adapter_sqlite_path_persists_and_reopens_truth_free_history(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "workload.sqlite"
    spec = _spec()
    seen: list[CandidateSpec] = []
    adapter = _adapter(seen)

    expected_first = random.Random(spec.policy_seed).choice(list(spec.candidates))
    current_policy_choice = RandomPolicy(spec.policy_seed).select(
        [
            Candidate(
                candidate_id=candidate.candidate_id,
                learning_rate=0.01,
                regularization=0.001,
                model_width=32 + index,
                optimizer="sgd",
            )
            for index, candidate in enumerate(spec.candidates)
        ],
        [],
    )
    with ExperimentStore(db_path) as store:
        store.init_schema()
        first = run_workload_experiment(store, run_spec=spec, adapter=adapter)
        second = run_workload_experiment(store, run_spec=spec, adapter=adapter)
        in_process_history = store.list_workload_experiments(spec.fingerprint())
        generic_columns = {
            str(row[1])
            for row in store._connection().execute("PRAGMA table_info(workload_experiments)")
        }

    with ExperimentStore(db_path) as reopened:
        reopened.init_schema()
        reopened_history = reopened.list_workload_experiments(spec.fingerprint())

    assert first.candidate == expected_first
    assert first.candidate.candidate_id == current_policy_choice.candidate_id
    assert second.candidate != first.candidate
    assert seen == [first.candidate, second.candidate]
    assert in_process_history == [first, second]
    assert reopened_history == [first, second]
    assert all(record.run_spec_fingerprint == spec.fingerprint() for record in reopened_history)
    assert all(record.policy_id == "random" for record in reopened_history)
    assert "true_value" not in generic_columns


def test_v6_migration_preserves_v5_synthetic_schema_and_history(tmp_path: Path) -> None:
    db_path = tmp_path / "v5.sqlite"
    with ExperimentStore(db_path) as store:
        store.init_schema()
        synthetic_record = run_next(store, policy_name="greedy", seed=0)
        connection = store._connection()
        connection.execute("DROP TABLE workload_experiments")
        connection.execute("PRAGMA user_version = 5")
        connection.commit()
        before_schema = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_schema ORDER BY type, name"
        ).fetchall()
        assert store.schema_version() == 5

    with ExperimentStore(db_path) as migrated:
        migrated.init_schema()
        migrated.init_schema()
        after_schema = (
            migrated._connection()
            .execute(
                """
            SELECT type, name, tbl_name, sql
            FROM sqlite_schema
            WHERE tbl_name != 'workload_experiments'
            ORDER BY type, name
            """
            )
            .fetchall()
        )
        integrity = migrated._connection().execute("PRAGMA integrity_check").fetchone()
        foreign_key_errors = migrated._connection().execute("PRAGMA foreign_key_check").fetchall()

        assert migrated.schema_version() == SCHEMA_VERSION == 6
        assert migrated.list_records() == [synthetic_record]
        assert migrated.list_workload_experiments("0" * 64) == []
        generic_spec = _spec(count=1)
        generic_seen: list[CandidateSpec] = []
        generic_record = run_workload_experiment(
            migrated,
            run_spec=generic_spec,
            adapter=_adapter(generic_seen),
        )

    assert [tuple(row) for row in after_schema] == [tuple(row) for row in before_schema]
    assert integrity is not None and str(integrity[0]) == "ok"
    assert foreign_key_errors == []

    with ExperimentStore(db_path) as reopened:
        reopened.init_schema()
        assert reopened.list_records() == [synthetic_record]
        assert reopened.list_workload_experiments(generic_spec.fingerprint()) == [generic_record]


def test_v6_migration_rejects_a_conflicting_preexisting_workload_table(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "conflicting-v5.sqlite"
    with ExperimentStore(db_path) as store:
        store.init_schema()
    connection = sqlite3.connect(db_path)
    downgrade_to_exact_schema(connection, 5)
    connection.execute("CREATE TABLE workload_experiments (id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()

    with ExperimentStore(db_path) as store:
        with pytest.raises(RuntimeError, match="does not match schema v6"):
            store.init_schema()
        assert store.schema_version() == 5


def test_runner_enforces_count_and_cost_budgets_without_retry_or_partial_insert(
    tmp_path: Path,
) -> None:
    count_db = tmp_path / "count.sqlite"
    count_spec = _spec(count=1)
    count_seen: list[CandidateSpec] = []
    with ExperimentStore(count_db) as store:
        store.init_schema()
        run_workload_experiment(store, run_spec=count_spec, adapter=_adapter(count_seen))
        with pytest.raises(RuntimeError, match="count budget is exhausted"):
            run_workload_experiment(store, run_spec=count_spec, adapter=_adapter(count_seen))
        assert len(store.list_workload_experiments(count_spec.fingerprint())) == 1
    assert len(count_seen) == 1

    cost_db = tmp_path / "cost.sqlite"
    cost_spec = _spec(cost_budget=0.5)
    cost_seen: list[CandidateSpec] = []
    with ExperimentStore(cost_db) as store:
        store.init_schema()
        with pytest.raises(RuntimeError, match="would exceed"):
            run_workload_experiment(
                store,
                run_spec=cost_spec,
                adapter=_adapter(cost_seen, cost=0.75),
            )
        assert store.list_workload_experiments(cost_spec.fingerprint()) == []
    assert len(cost_seen) == 1


def test_runner_rejects_adapter_mismatch_and_inconsistent_history_before_user_code(
    tmp_path: Path,
) -> None:
    mismatch_db = tmp_path / "mismatch.sqlite"
    spec = _spec()
    mismatch_seen: list[CandidateSpec] = []
    with ExperimentStore(mismatch_db) as store:
        store.init_schema()
        with pytest.raises(ValueError, match="does not match"):
            run_workload_experiment(
                store,
                run_spec=spec,
                adapter=_adapter(mismatch_seen, adapter_id="other-adapter"),
            )
    assert mismatch_seen == []

    history_db = tmp_path / "history.sqlite"
    history_seen: list[CandidateSpec] = []
    with ExperimentStore(history_db) as store:
        store.init_schema()
        run_workload_experiment(store, run_spec=spec, adapter=_adapter(history_seen))
        store._connection().execute("UPDATE workload_experiments SET parameters_json = '{}'")
        store._connection().commit()
        with pytest.raises(RuntimeError, match="inconsistent"):
            run_workload_experiment(store, run_spec=spec, adapter=_adapter(history_seen))
    assert len(history_seen) == 1


def test_generic_workload_rows_are_isolated_by_runspec_fingerprint(tmp_path: Path) -> None:
    db_path = tmp_path / "isolated.sqlite"
    first_spec = _spec(adapter_id="first-adapter")
    second_spec = _spec(adapter_id="second-adapter")
    first_seen: list[CandidateSpec] = []
    second_seen: list[CandidateSpec] = []

    with ExperimentStore(db_path) as store:
        store.init_schema()
        first = run_workload_experiment(
            store,
            run_spec=first_spec,
            adapter=_adapter(first_seen, adapter_id="first-adapter"),
        )
        second = run_workload_experiment(
            store,
            run_spec=second_spec,
            adapter=_adapter(second_seen, adapter_id="second-adapter"),
        )

        assert store.list_workload_experiments(first_spec.fingerprint()) == [first]
        assert store.list_workload_experiments(second_spec.fingerprint()) == [second]
        assert first.candidate == second.candidate
        assert first.run_spec_fingerprint != second.run_spec_fingerprint


def test_workload_table_rejects_duplicate_candidate_for_one_runspec(tmp_path: Path) -> None:
    db_path = tmp_path / "duplicate.sqlite"
    spec = _spec()
    seen: list[CandidateSpec] = []
    with ExperimentStore(db_path) as store:
        store.init_schema()
        record = run_workload_experiment(store, run_spec=spec, adapter=_adapter(seen))
        with pytest.raises(sqlite3.IntegrityError):
            store.add_workload_experiment(record)
