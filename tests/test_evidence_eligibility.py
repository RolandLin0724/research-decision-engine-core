from __future__ import annotations

from pathlib import Path

from research_decision_engine.evidence_eligibility import (
    OptimizerEvidenceEligibilityContract,
    default_public_design,
)
from research_decision_engine.optimizer_effect import synchronize_optimizer_reasoning
from research_decision_engine.storage import ExperimentStore
from research_decision_engine.types import Candidate, CompletedExperiment, ExperimentRecord

CREATED_AT = "2026-01-01T00:00:00+00:00"


def test_public_structure_opens_and_completes_matched_pair() -> None:
    sgd = _candidate("pair-sgd", optimizer="sgd")
    adam = _candidate("pair-adam", optimizer="adam")
    contract = OptimizerEvidenceEligibilityContract.from_candidates((sgd, adam))

    opener = contract.assess_candidate(sgd, [])
    closer = contract.assess_candidate(adam, [_completed(1, sgd)])

    assert opener.effect == "opens_pair"
    assert closer.effect == "completes_pair"
    assert closer.counterpart_experiment_id == 1
    assert (
        contract.design_for(sgd).controlled_variables
        == contract.design_for(adam).controlled_variables
    )
    assert "true" not in repr(contract.to_dict()).lower()
    assert "outcome" not in repr(contract.to_dict()).lower()


def test_same_group_label_with_different_controls_is_not_a_match() -> None:
    sgd = _candidate("sgd", optimizer="sgd", learning_rate=0.001)
    adam = _candidate("adam", optimizer="adam", learning_rate=0.01)
    designs = (
        default_public_design(sgd, comparison_group_id="shared-label"),
        default_public_design(adam, comparison_group_id="shared-label"),
    )
    contract = OptimizerEvidenceEligibilityContract.from_candidates(
        (sgd, adam), public_designs=designs
    )

    assessment = contract.assess_candidate(adam, [_completed(1, sgd)])

    assert assessment.effect == "opens_pair"
    assert contract.valid_unapplied_pairs([_completed(1, sgd), _completed(2, adam)]) == ()


def test_publicly_irrelevant_candidates_cannot_create_evidence(tmp_path: Path) -> None:
    sgd = _candidate("objective-sgd", optimizer="sgd")
    adam = _candidate("objective-adam", optimizer="adam")
    designs = (
        default_public_design(sgd, experiment_family="objective-only"),
        default_public_design(adam, experiment_family="objective-only"),
    )
    contract = OptimizerEvidenceEligibilityContract.from_candidates(
        (sgd, adam), public_designs=designs
    )

    with ExperimentStore(tmp_path / "irrelevant.sqlite") as store:
        store.init_schema()
        store.add_record(_record(sgd, 0.4))
        store.add_record(_record(adam, 0.8))

        assert contract.assess_candidate(sgd, []).effect == "ineligible"
        assert synchronize_optimizer_reasoning(store, eligibility=contract) == []
        assert store.list_evidence() == []
        assert store.list_belief_updates() == []


def test_applied_source_pair_is_not_eligible_twice() -> None:
    sgd = _candidate("sgd", optimizer="sgd")
    adam = _candidate("adam", optimizer="adam")
    completed = [_completed(1, sgd), _completed(2, adam)]
    contract = OptimizerEvidenceEligibilityContract.from_candidates((sgd, adam))

    assert len(contract.valid_unapplied_pairs(completed)) == 1
    assert (
        contract.valid_unapplied_pairs(
            completed,
            applied_source_pairs=frozenset({(1, 2)}),
        )
        == ()
    )


def _candidate(
    candidate_id: str,
    *,
    optimizer: str,
    learning_rate: float = 0.001,
) -> Candidate:
    return Candidate(
        candidate_id=candidate_id,
        learning_rate=learning_rate,
        regularization=0.001,
        model_width=32,
        optimizer=optimizer,
    )


def _completed(record_id: int, candidate: Candidate) -> CompletedExperiment:
    return CompletedExperiment(
        record_id=record_id,
        candidate=candidate,
        observed_value=0.5,
        created_at=CREATED_AT,
    )


def _record(candidate: Candidate, observed_value: float) -> ExperimentRecord:
    return ExperimentRecord(
        record_id=None,
        candidate=candidate,
        policy="test",
        observed_value=observed_value,
        true_value=observed_value,
        cost=1.0,
        created_at=CREATED_AT,
    )
