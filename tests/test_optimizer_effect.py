from __future__ import annotations

from pathlib import Path

import pytest

from research_decision_engine.optimizer_effect import (
    ADAM_ADVANTAGE_ID,
    synchronize_optimizer_reasoning,
)
from research_decision_engine.storage import ExperimentStore
from research_decision_engine.types import Candidate, ExperimentRecord
from research_decision_engine.world import DeterministicSyntheticWorld


def test_only_matched_experiments_generate_traceable_evidence(tmp_path: Path) -> None:
    world = DeterministicSyntheticWorld()
    candidates = world.candidates()

    with ExperimentStore(tmp_path / "matched.sqlite") as store:
        store.init_schema()
        sgd_record = _add_candidate(store, candidates[0])
        assert synchronize_optimizer_reasoning(store) == []
        assert store.list_evidence() == []

        adam_record = _add_candidate(store, candidates[1])
        updates = synchronize_optimizer_reasoning(store)

        assert len(updates) == 1
        evidence = updates[0].evidence
        assert evidence.source_experiment_ids == (sgd_record.record_id, adam_record.record_id)
        assert evidence.observed_comparison == pytest.approx(
            adam_record.observed_value - sgd_record.observed_value
        )
        assert evidence.provenance.details_dict()["controlled_variables_equal"] is True
        assert "true_value" not in evidence.provenance.details_dict()

        persisted = store.get_belief_update(updates[0].update_id)
        assert persisted == updates[0]
        for source_id in persisted.evidence.source_experiment_ids:
            assert store.get_record(source_id).record_id == source_id


def test_unmatched_experiments_do_not_generate_evidence(tmp_path: Path) -> None:
    world = DeterministicSyntheticWorld()
    candidates = world.candidates()

    with ExperimentStore(tmp_path / "unmatched.sqlite") as store:
        store.init_schema()
        _add_candidate(store, candidates[0])
        _add_candidate(store, candidates[3])

        assert synchronize_optimizer_reasoning(store) == []
        assert store.list_evidence() == []
        current = store.current_belief_state()
        assert current is not None
        assert current.sequence == 0


def test_same_matched_pair_is_not_applied_twice(tmp_path: Path) -> None:
    world = DeterministicSyntheticWorld()
    candidates = world.candidates()

    with ExperimentStore(tmp_path / "duplicate.sqlite") as store:
        store.init_schema()
        _add_candidate(store, candidates[0])
        _add_candidate(store, candidates[1])

        first_updates = synchronize_optimizer_reasoning(store)
        second_updates = synchronize_optimizer_reasoning(store)

        assert len(first_updates) == 1
        assert second_updates == []
        assert len(store.list_evidence()) == 1
        assert len(store.list_belief_updates()) == 1
        current = store.current_belief_state()
        assert current is not None
        assert current.sequence == 1
        assert current.posterior_for(ADAM_ADVANTAGE_ID) > current.prior_for(ADAM_ADVANTAGE_ID)


def _add_candidate(store: ExperimentStore, candidate: Candidate) -> ExperimentRecord:
    world = DeterministicSyntheticWorld()
    observed_value, true_value, cost = world.evaluate(candidate)
    return store.add_record(
        ExperimentRecord.new(
            candidate=candidate,
            policy="test",
            observed_value=observed_value,
            true_value=true_value,
            cost=cost,
        )
    )
