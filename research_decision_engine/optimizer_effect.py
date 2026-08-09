"""Synthetic-domain reasoning about the observed optimizer effect."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from research_decision_engine.evidence_eligibility import (
    MatchedExperimentPair,
    OptimizerEvidenceEligibilityContract,
)
from research_decision_engine.reasoning import (
    BayesianBeliefUpdater,
    BeliefState,
    BeliefUpdate,
    Evidence,
    GaussianEvidencePrediction,
    Hypothesis,
    Provenance,
    ReasoningError,
    initial_belief_state,
)
from research_decision_engine.storage import ExperimentStore

ADAM_ADVANTAGE_ID = "optimizer.adam-advantage"
NO_ADVANTAGE_ID = "optimizer.no-consistent-advantage"
SGD_ADVANTAGE_ID = "optimizer.sgd-advantage"

EVIDENCE_METHOD = "matched-optimizer-effect"
EVIDENCE_METHOD_VERSION = "matched-optimizer-effect/v1"
UPDATE_RULE_VERSION = "optimizer-effect-bayesian-update/v1"
PREDICTION_MODEL_VERSION = "optimizer-effect-gaussian/v1"
PRACTICAL_EFFECT_THRESHOLD = 0.01
PREDICTED_EFFECT_STANDARD_DEVIATION = 0.05


def optimizer_effect_hypotheses() -> tuple[Hypothesis, ...]:
    """Return the three fixed competing hypotheses for this application."""

    prior = 1.0 / 3.0
    return (
        Hypothesis(
            hypothesis_id=ADAM_ADVANTAGE_ID,
            statement="Adam has a consistent practical performance advantage over SGD.",
            prior_probability=prior,
            prediction_model=GaussianEvidencePrediction(
                mean=0.10,
                standard_deviation=PREDICTED_EFFECT_STANDARD_DEVIATION,
                model_version=PREDICTION_MODEL_VERSION,
            ),
        ),
        Hypothesis(
            hypothesis_id=NO_ADVANTAGE_ID,
            statement="Neither optimizer has a consistent practical performance advantage.",
            prior_probability=prior,
            prediction_model=GaussianEvidencePrediction(
                mean=0.0,
                standard_deviation=PREDICTED_EFFECT_STANDARD_DEVIATION,
                model_version=PREDICTION_MODEL_VERSION,
            ),
        ),
        Hypothesis(
            hypothesis_id=SGD_ADVANTAGE_ID,
            statement="SGD has a consistent practical performance advantage over Adam.",
            prior_probability=prior,
            prediction_model=GaussianEvidencePrediction(
                mean=-0.10,
                standard_deviation=PREDICTED_EFFECT_STANDARD_DEVIATION,
                model_version=PREDICTION_MODEL_VERSION,
            ),
        ),
    )


def ensure_optimizer_reasoning(store: ExperimentStore) -> BeliefState:
    """Register the fixed hypotheses and create the initial belief state once."""

    hypotheses = optimizer_effect_hypotheses()
    store.register_hypotheses(hypotheses)
    current = store.current_belief_state()
    if current is None:
        current = initial_belief_state(hypotheses, created_at=datetime.now(UTC).isoformat())
        store.add_initial_belief_state(current)
    expected_ids = tuple(sorted(hypothesis.hypothesis_id for hypothesis in hypotheses))
    if current.hypothesis_ids != expected_ids:
        raise ReasoningError("Stored belief state does not match optimizer-effect hypotheses.")
    return current


def synchronize_optimizer_reasoning(
    store: ExperimentStore,
    *,
    eligibility: OptimizerEvidenceEligibilityContract | None = None,
) -> list[BeliefUpdate]:
    """Derive and apply every new valid matched-pair evidence item in stable order."""

    hypotheses = optimizer_effect_hypotheses()
    current = ensure_optimizer_reasoning(store)
    updater = BayesianBeliefUpdater(update_rule_version=UPDATE_RULE_VERSION)
    updates: list[BeliefUpdate] = []
    completed = store.list_completed_experiments()
    contract = eligibility or OptimizerEvidenceEligibilityContract.from_candidates(
        item.candidate for item in completed
    )
    applied_source_pairs = frozenset(item.source_experiment_ids for item in store.list_evidence())

    for pair in contract.valid_unapplied_pairs(
        completed,
        applied_source_pairs=applied_source_pairs,
    ):
        evidence = _evidence_from_pair(pair, contract)
        if store.evidence_exists(evidence.evidence_id):
            if store.update_id_for_evidence(evidence.evidence_id) is None:
                raise ReasoningError(
                    f"Evidence {evidence.evidence_id} exists without a belief update."
                )
            continue
        update = updater.update(
            hypotheses=hypotheses,
            belief_state=current,
            evidence=evidence,
        )
        store.add_reasoning_step(update)
        current = update.posterior_belief_state
        updates.append(update)

    return updates


def evidence_from_matched_pair(
    pair: MatchedExperimentPair,
    eligibility: OptimizerEvidenceEligibilityContract,
) -> Evidence:
    """Derive optimizer evidence from one contract-validated matched pair."""

    return _evidence_from_pair(pair, eligibility)


def _evidence_from_pair(
    pair: MatchedExperimentPair,
    eligibility: OptimizerEvidenceEligibilityContract,
) -> Evidence:
    sgd_experiment = pair.sgd_experiment
    adam_experiment = pair.adam_experiment
    sgd_candidate = sgd_experiment.candidate
    adam_candidate = adam_experiment.candidate
    sgd_design = eligibility.design_for(sgd_candidate)
    adam_design = eligibility.design_for(adam_candidate)
    if sgd_design.intervention_arm != "sgd" or adam_design.intervention_arm != "adam":
        raise ReasoningError("Matched optimizer evidence requires complementary optimizer arms.")
    if sgd_design.comparison_key != adam_design.comparison_key:
        raise ReasoningError(
            "Matched optimizer evidence requires equal public comparison structure."
        )

    source_ids = pair.source_experiment_ids
    evidence_id = _evidence_id(source_ids)
    observed_effect = round(adam_experiment.observed_value - sgd_experiment.observed_value, 12)
    if observed_effect > PRACTICAL_EFFECT_THRESHOLD:
        observed_outcome = "adam-win"
    elif observed_effect < -PRACTICAL_EFFECT_THRESHOLD:
        observed_outcome = "sgd-win"
    else:
        observed_outcome = "practical-tie"

    provenance = Provenance.create(
        method=EVIDENCE_METHOD,
        version=EVIDENCE_METHOD_VERSION,
        details={
            "adam_experiment_id": adam_experiment.record_id,
            "adam_observed_value": adam_experiment.observed_value,
            "comparison_formula": "adam_observed_value - sgd_observed_value",
            "comparison_group_id": pair.comparison_group_id,
            "controlled_learning_rate": sgd_candidate.learning_rate,
            "controlled_model_width": sgd_candidate.model_width,
            "controlled_regularization": sgd_candidate.regularization,
            "controlled_variables_equal": True,
            "experiment_family": sgd_design.experiment_family,
            "intervention_variable": sgd_design.intervention_variable,
            "observed_outcome": observed_outcome,
            "practical_effect_threshold": PRACTICAL_EFFECT_THRESHOLD,
            "sgd_experiment_id": sgd_experiment.record_id,
            "sgd_observed_value": sgd_experiment.observed_value,
            "source_experiment_status": "completed_successfully",
        },
    )
    return Evidence(
        evidence_id=evidence_id,
        source_experiment_ids=source_ids,
        observed_comparison=observed_effect,
        observed_outcome=observed_outcome,
        provenance=provenance,
        created_at=max(sgd_experiment.created_at, adam_experiment.created_at),
    )


def _evidence_id(source_ids: tuple[int, ...]) -> str:
    canonical_pair = ":".join(str(source_id) for source_id in source_ids)
    digest = hashlib.sha256(f"optimizer-effect:{canonical_pair}".encode()).hexdigest()[:24]
    return f"evidence-{digest}"
