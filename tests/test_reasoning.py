from __future__ import annotations

import math

import pytest

from research_decision_engine.optimizer_effect import (
    ADAM_ADVANTAGE_ID,
    optimizer_effect_hypotheses,
)
from research_decision_engine.reasoning import (
    BayesianBeliefUpdater,
    BeliefState,
    DuplicateEvidenceError,
    Evidence,
    InvalidBeliefUpdateError,
    Provenance,
    ReasoningError,
    initial_belief_state,
)

CREATED_AT = "2026-01-01T00:00:00+00:00"


def test_probabilities_are_validated_and_updates_normalize_to_one() -> None:
    hypotheses = optimizer_effect_hypotheses()
    initial = initial_belief_state(hypotheses, created_at=CREATED_AT)
    update = BayesianBeliefUpdater().update(
        hypotheses=hypotheses,
        belief_state=initial,
        evidence=_evidence("evidence-positive", 0.10, (1, 2)),
    )

    assert math.fsum(update.posterior_belief_state.posterior_probabilities) == pytest.approx(1.0)

    with pytest.raises(ReasoningError, match="must sum to 1"):
        BeliefState(
            belief_state_id="invalid",
            hypothesis_ids=initial.hypothesis_ids,
            prior_probabilities=initial.prior_probabilities,
            posterior_probabilities=(0.5, 0.5, 0.5),
            evidence_ids=(),
            sequence=0,
            created_at=CREATED_AT,
        )

    with pytest.raises(ReasoningError, match="finite and non-negative"):
        BeliefState(
            belief_state_id="invalid",
            hypothesis_ids=initial.hypothesis_ids,
            prior_probabilities=initial.prior_probabilities,
            posterior_probabilities=(math.nan, 0.5, 0.5),
            evidence_ids=(),
            sequence=0,
            created_at=CREATED_AT,
        )


def test_supporting_and_contradictory_evidence_revise_belief() -> None:
    hypotheses = optimizer_effect_hypotheses()
    updater = BayesianBeliefUpdater()
    initial = initial_belief_state(hypotheses, created_at=CREATED_AT)

    supporting = updater.update(
        hypotheses=hypotheses,
        belief_state=initial,
        evidence=_evidence("evidence-supporting", 0.10, (1, 2)),
    )
    after_support = supporting.posterior_belief_state.posterior_for(ADAM_ADVANTAGE_ID)

    contradictory = updater.update(
        hypotheses=hypotheses,
        belief_state=supporting.posterior_belief_state,
        evidence=_evidence("evidence-contradictory", -0.10, (3, 4)),
    )
    after_contradiction = contradictory.posterior_belief_state.posterior_for(ADAM_ADVANTAGE_ID)

    assert after_support > initial.posterior_for(ADAM_ADVANTAGE_ID)
    assert after_contradiction < after_support


def test_belief_update_is_deterministic() -> None:
    hypotheses = optimizer_effect_hypotheses()
    initial = initial_belief_state(hypotheses, created_at=CREATED_AT)
    evidence = _evidence("evidence-deterministic", 0.075, (1, 2))
    updater = BayesianBeliefUpdater()

    left = updater.update(hypotheses=hypotheses, belief_state=initial, evidence=evidence)
    right = updater.update(hypotheses=hypotheses, belief_state=initial, evidence=evidence)

    assert left == right


def test_independent_evidence_order_has_equivalent_posterior() -> None:
    hypotheses = optimizer_effect_hypotheses()
    initial = initial_belief_state(hypotheses, created_at=CREATED_AT)
    updater = BayesianBeliefUpdater()
    first = _evidence("evidence-first", 0.08, (1, 2))
    second = _evidence("evidence-second", -0.02, (3, 4))

    first_then_second = updater.update(
        hypotheses=hypotheses,
        belief_state=updater.update(
            hypotheses=hypotheses,
            belief_state=initial,
            evidence=first,
        ).posterior_belief_state,
        evidence=second,
    ).posterior_belief_state
    second_then_first = updater.update(
        hypotheses=hypotheses,
        belief_state=updater.update(
            hypotheses=hypotheses,
            belief_state=initial,
            evidence=second,
        ).posterior_belief_state,
        evidence=first,
    ).posterior_belief_state

    assert first_then_second.posterior_probabilities == pytest.approx(
        second_then_first.posterior_probabilities,
        abs=1e-12,
    )


def test_duplicate_evidence_is_rejected() -> None:
    hypotheses = optimizer_effect_hypotheses()
    updater = BayesianBeliefUpdater()
    evidence = _evidence("evidence-duplicate", 0.10, (1, 2))
    updated = updater.update(
        hypotheses=hypotheses,
        belief_state=initial_belief_state(hypotheses, created_at=CREATED_AT),
        evidence=evidence,
    )

    with pytest.raises(DuplicateEvidenceError):
        updater.update(
            hypotheses=hypotheses,
            belief_state=updated.posterior_belief_state,
            evidence=evidence,
        )


def test_zero_total_likelihood_is_rejected_without_a_posterior() -> None:
    hypotheses = optimizer_effect_hypotheses()
    initial = initial_belief_state(hypotheses, created_at=CREATED_AT)

    with pytest.raises(InvalidBeliefUpdateError, match="zero or numerically invalid"):
        BayesianBeliefUpdater().update(
            hypotheses=hypotheses,
            belief_state=initial,
            evidence=_evidence("evidence-underflow", 1e100, (1, 2)),
        )


def _evidence(
    evidence_id: str, observed_comparison: float, source_ids: tuple[int, ...]
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        source_experiment_ids=source_ids,
        observed_comparison=observed_comparison,
        observed_outcome="test-comparison",
        provenance=Provenance.create(
            method="test-evidence",
            version="test-evidence/v1",
            details={"comparison_formula": "left - right"},
        ),
        created_at=CREATED_AT,
    )
