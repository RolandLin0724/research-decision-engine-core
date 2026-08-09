"""Versioned Gaussian belief models with isolated scientific lineages."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import sys
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from research_decision_engine.calibration import CalibrationMatchedEffect
from research_decision_engine.optimizer_effect import (
    PREDICTED_EFFECT_STANDARD_DEVIATION,
    UPDATE_RULE_VERSION,
    optimizer_effect_hypotheses,
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
)

FIXED_SIGMA_MODEL_ID = "fixed_sigma_gaussian"
CALIBRATED_SIGMA_MODEL_ID = "replicated_noise_calibrated_gaussian"
DEFAULT_BELIEF_MODEL_ID = CALIBRATED_SIGMA_MODEL_ID
FIXED_SIGMA_MODEL_VERSION = "fixed-sigma-gaussian/v1"
CALIBRATED_SIGMA_MODEL_VERSION = "replicated-noise-calibrated-gaussian/v1"
SIGMA_ESTIMATOR_VERSION = "prior-matched-effect-sample-standard-deviation/v1"
ADEQUACY_DIAGNOSTIC_VERSION = "prequential-model-adequacy/v1"

FIXED_SIGMA = PREDICTED_EFFECT_STANDARD_DEVIATION
SIGMA_FLOOR = 0.05
VARIANCE_FLOOR = 0.0025
MINIMUM_PRIOR_EFFECTS = 5
ADEQUACY_MINIMUM_RESIDUALS = 10
TAIL_ALARM_THRESHOLD = 0.05
RESIDUAL_OUTLIER_THRESHOLD = 3.0
RESIDUAL_WINDOW_SIZE = 5
RESIDUAL_ALARM_COUNT = 2

type SigmaEstimateStatus = Literal["fixed", "baseline_fallback", "calibrated"]
type AdequacyState = Literal["adequate", "uncertain", "appears_misspecified"]
type EffectSourceKind = Literal["calibration", "decision"]


@dataclass(frozen=True, slots=True)
class MatchedEffectObservation:
    """One valid matched effect eligible for a later sigma estimate."""

    effect_id: str
    comparison_group_id: str
    observed_effect: float
    available_sequence: int
    source_kind: EffectSourceKind
    source_ids: tuple[str, ...]
    created_at: str
    provenance: Provenance

    def __post_init__(self) -> None:
        if not self.effect_id.strip() or not self.comparison_group_id.strip():
            raise ReasoningError("Matched-effect identifiers must not be empty.")
        if not math.isfinite(self.observed_effect):
            raise ReasoningError("Matched effect must be finite.")
        if self.available_sequence < 0:
            raise ReasoningError("Matched-effect availability sequence must be non-negative.")
        if not self.source_ids or len(self.source_ids) != len(set(self.source_ids)):
            raise ReasoningError("Matched-effect source IDs must be non-empty and unique.")

    @classmethod
    def from_calibration(cls, effect: CalibrationMatchedEffect) -> MatchedEffectObservation:
        return cls(
            effect_id=effect.calibration_effect_id,
            comparison_group_id=effect.comparison_group_id,
            observed_effect=effect.observed_effect,
            available_sequence=effect.available_sequence,
            source_kind="calibration",
            source_ids=(effect.adam_arm_id, effect.sgd_arm_id),
            created_at=effect.created_at,
            provenance=effect.provenance,
        )

    @classmethod
    def from_decision(
        cls, evidence: Evidence, *, available_sequence: int
    ) -> MatchedEffectObservation:
        details = evidence.provenance.details_dict()
        comparison_group_id = details.get("comparison_group_id")
        if not isinstance(comparison_group_id, str) or not comparison_group_id.strip():
            raise ReasoningError("Decision evidence lacks a public comparison-group identity.")
        if details.get("source_experiment_status") != "completed_successfully":
            raise ReasoningError("Decision matched effects require successful source experiments.")
        return cls(
            effect_id=evidence.evidence_id,
            comparison_group_id=comparison_group_id,
            observed_effect=evidence.observed_comparison,
            available_sequence=available_sequence,
            source_kind="decision",
            source_ids=tuple(str(item) for item in evidence.source_experiment_ids),
            created_at=evidence.created_at,
            provenance=Provenance.create(
                method="decision-evidence-to-matched-effect",
                version=SIGMA_ESTIMATOR_VERSION,
                details={
                    "comparison_group_id": comparison_group_id,
                    "evidence_id": evidence.evidence_id,
                    "source_evidence_method": evidence.provenance.method,
                    "source_experiment_ids": json.dumps(evidence.source_experiment_ids),
                },
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "effect_id": self.effect_id,
            "comparison_group_id": self.comparison_group_id,
            "observed_effect": self.observed_effect,
            "available_sequence": self.available_sequence,
            "source_kind": self.source_kind,
            "source_ids": list(self.source_ids),
            "created_at": self.created_at,
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SigmaEstimate:
    """A reconstructable pre-update standard-deviation selection."""

    estimate_id: str
    belief_model_id: str
    belief_model_version: str
    lineage_id: str
    evidence_id: str
    comparison_group_id: str
    cutoff_sequence: int
    source_effect_ids: tuple[str, ...]
    sample_count: int
    sample_mean: float | None
    raw_sample_standard_deviation: float | None
    sigma_floor: float
    variance_floor: float
    estimated_sigma: float
    status: SigmaEstimateStatus
    estimator_version: str
    current_evidence_excluded: bool
    created_at: str
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.sample_count != len(self.source_effect_ids):
            raise ReasoningError("Sigma-estimate source count does not match source IDs.")
        if len(self.source_effect_ids) != len(set(self.source_effect_ids)):
            raise ReasoningError("Sigma-estimate source IDs must be unique.")
        if not math.isclose(self.sigma_floor**2, self.variance_floor, abs_tol=1e-15):
            raise ReasoningError("Sigma and variance floors are inconsistent.")
        if not math.isfinite(self.estimated_sigma) or self.estimated_sigma < self.sigma_floor:
            raise ReasoningError("Estimated sigma must be finite and at least the sigma floor.")
        if self.status == "calibrated":
            if self.sample_count < MINIMUM_PRIOR_EFFECTS:
                raise ReasoningError("Calibrated sigma requires five prior matched effects.")
            if self.sample_mean is None or self.raw_sample_standard_deviation is None:
                raise ReasoningError("Calibrated sigma requires sample statistics.")
        if not self.current_evidence_excluded:
            raise ReasoningError("The current evidence must be excluded from its sigma estimate.")

    def to_dict(self) -> dict[str, object]:
        return {
            "estimate_id": self.estimate_id,
            "belief_model_id": self.belief_model_id,
            "belief_model_version": self.belief_model_version,
            "lineage_id": self.lineage_id,
            "evidence_id": self.evidence_id,
            "comparison_group_id": self.comparison_group_id,
            "cutoff_sequence": self.cutoff_sequence,
            "source_effect_ids": list(self.source_effect_ids),
            "sample_count": self.sample_count,
            "sample_mean": self.sample_mean,
            "raw_sample_standard_deviation": self.raw_sample_standard_deviation,
            "sigma_floor": self.sigma_floor,
            "variance_floor": self.variance_floor,
            "estimated_sigma": self.estimated_sigma,
            "status": self.status,
            "estimator_version": self.estimator_version,
            "current_evidence_excluded": self.current_evidence_excluded,
            "created_at": self.created_at,
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ModelBeliefState:
    """A belief state explicitly owned by one model lineage."""

    belief_model_id: str
    belief_model_version: str
    lineage_id: str
    state: BeliefState

    def to_dict(self) -> dict[str, object]:
        return {
            "belief_model_id": self.belief_model_id,
            "belief_model_version": self.belief_model_version,
            "lineage_id": self.lineage_id,
            "state": self.state.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class BeliefModelLineage:
    """Immutable current-state pointer for one belief model."""

    lineage_id: str
    belief_model_id: str
    belief_model_version: str
    lineage_key: str
    current_state: ModelBeliefState
    created_at: str

    def __post_init__(self) -> None:
        state = self.current_state
        if (
            state.lineage_id != self.lineage_id
            or state.belief_model_id != self.belief_model_id
            or state.belief_model_version != self.belief_model_version
        ):
            raise ReasoningError("Belief-model lineage and current state do not match.")


@dataclass(frozen=True, slots=True)
class PredictiveInterval:
    probability: float
    lower: float
    upper: float
    contains_observation: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "probability": self.probability,
            "lower": self.lower,
            "upper": self.upper,
            "contains_observation": self.contains_observation,
        }


@dataclass(frozen=True, slots=True)
class ModelAdequacyDiagnostic:
    """Truth-free prequential model-adequacy record."""

    diagnostic_id: str
    belief_model_id: str
    belief_model_version: str
    lineage_id: str
    belief_state_before_id: str
    evidence_id: str
    sigma_estimate_id: str
    comparison_group_id: str
    predictive_mean: float
    predictive_variance: float
    predictive_density: float
    predictive_log_likelihood: float
    predictive_cdf: float
    posterior_predictive_tail_probability: float
    standardized_residual: float
    per_hypothesis_residuals: tuple[tuple[str, float], ...]
    central_intervals: tuple[PredictiveInterval, ...]
    residual_count: int
    rolling_residual_outlier_count: int
    tail_alarm: bool
    residual_outlier: bool
    repeated_residual_alarm: bool
    diagnostics_disagree: bool
    adequacy_state: AdequacyState
    diagnostic_version: str
    created_at: str
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.residual_count <= 0:
            raise ReasoningError("A diagnostic record must include its current residual.")
        if not 0.0 <= self.predictive_cdf <= 1.0:
            raise ReasoningError("Predictive CDF must be in [0, 1].")
        if not 0.0 <= self.posterior_predictive_tail_probability <= 1.0:
            raise ReasoningError("Predictive tail probability must be in [0, 1].")
        if self.predictive_density <= 0.0 or not math.isfinite(self.predictive_density):
            raise ReasoningError("Predictive density must be finite and positive.")

    def to_dict(self) -> dict[str, object]:
        return {
            "diagnostic_id": self.diagnostic_id,
            "belief_model_id": self.belief_model_id,
            "belief_model_version": self.belief_model_version,
            "lineage_id": self.lineage_id,
            "belief_state_before_id": self.belief_state_before_id,
            "evidence_id": self.evidence_id,
            "sigma_estimate_id": self.sigma_estimate_id,
            "comparison_group_id": self.comparison_group_id,
            "predictive_mean": self.predictive_mean,
            "predictive_variance": self.predictive_variance,
            "predictive_density": self.predictive_density,
            "predictive_log_likelihood": self.predictive_log_likelihood,
            "predictive_cdf": self.predictive_cdf,
            "posterior_predictive_tail_probability": self.posterior_predictive_tail_probability,
            "standardized_residual": self.standardized_residual,
            "per_hypothesis_residuals": dict(self.per_hypothesis_residuals),
            "central_intervals": [item.to_dict() for item in self.central_intervals],
            "residual_count": self.residual_count,
            "rolling_residual_outlier_count": self.rolling_residual_outlier_count,
            "tail_alarm": self.tail_alarm,
            "residual_outlier": self.residual_outlier,
            "repeated_residual_alarm": self.repeated_residual_alarm,
            "diagnostics_disagree": self.diagnostics_disagree,
            "adequacy_state": self.adequacy_state,
            "diagnostic_version": self.diagnostic_version,
            "created_at": self.created_at,
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ModelBeliefUpdate:
    """One Bayesian update plus model, estimator, and lineage provenance."""

    model_update_id: str
    belief_model_id: str
    belief_model_version: str
    lineage_id: str
    state_before: ModelBeliefState
    evidence: Evidence
    sigma_estimate: SigmaEstimate
    bayesian_update: BeliefUpdate
    posterior_state: ModelBeliefState
    diagnostic: ModelAdequacyDiagnostic
    created_at: str
    provenance: Provenance

    def __post_init__(self) -> None:
        for state in (self.state_before, self.posterior_state):
            if state.lineage_id != self.lineage_id or state.belief_model_id != self.belief_model_id:
                raise ReasoningError("Model belief update crosses lineage boundaries.")
        if self.bayesian_update.evidence.evidence_id != self.evidence.evidence_id:
            raise ReasoningError("Model belief update references inconsistent evidence.")

    def to_dict(self) -> dict[str, object]:
        return {
            "model_update_id": self.model_update_id,
            "belief_model_id": self.belief_model_id,
            "belief_model_version": self.belief_model_version,
            "lineage_id": self.lineage_id,
            "state_before": self.state_before.to_dict(),
            "evidence": self.evidence.to_dict(),
            "sigma_estimate": self.sigma_estimate.to_dict(),
            "bayesian_update": self.bayesian_update.to_dict(),
            "posterior_state": self.posterior_state.to_dict(),
            "diagnostic": self.diagnostic.to_dict(),
            "created_at": self.created_at,
            "provenance": self.provenance.to_dict(),
        }


class BeliefModel(Protocol):
    """A versioned likelihood model that updates only its supplied lineage."""

    model_id: str
    model_version: str

    def select_sigma(
        self,
        *,
        lineage: BeliefModelLineage,
        evidence: Evidence,
        comparison_group_id: str,
        cutoff_sequence: int,
        effect_history: tuple[MatchedEffectObservation, ...],
    ) -> SigmaEstimate:
        """Select a reconstructable sigma from strictly prior matched effects."""

    def calculate_likelihoods(
        self,
        *,
        evidence: Evidence,
        sigma_estimate: SigmaEstimate,
    ) -> tuple[tuple[str, float], ...]:
        """Calculate every hypothesis likelihood under the selected sigma."""

    def create_belief_update(
        self,
        *,
        lineage: BeliefModelLineage,
        evidence: Evidence,
        sigma_estimate: SigmaEstimate,
    ) -> BeliefUpdate:
        """Create the deterministic Bayesian update for this lineage."""

    def produce_diagnostic(
        self,
        *,
        lineage: BeliefModelLineage,
        evidence: Evidence,
        comparison_group_id: str,
        sigma_estimate: SigmaEstimate,
        diagnostic_history: tuple[ModelAdequacyDiagnostic, ...],
    ) -> ModelAdequacyDiagnostic:
        """Score evidence prequentially without evaluator truth."""

    def update(
        self,
        *,
        lineage: BeliefModelLineage,
        evidence: Evidence,
        effect_history: tuple[MatchedEffectObservation, ...],
        diagnostic_history: tuple[ModelAdequacyDiagnostic, ...],
    ) -> tuple[BeliefModelLineage, ModelBeliefUpdate, MatchedEffectObservation]:
        """Apply one prequentially scored evidence item to an isolated lineage."""


@dataclass(frozen=True, slots=True)
class GaussianBeliefModel:
    """Fixed or replicated-noise-calibrated Gaussian evidence model."""

    model_id: str
    model_version: str

    def __post_init__(self) -> None:
        if self.model_id not in {FIXED_SIGMA_MODEL_ID, CALIBRATED_SIGMA_MODEL_ID}:
            raise ReasoningError(f"Unknown Gaussian belief model: {self.model_id}")

    def update(
        self,
        *,
        lineage: BeliefModelLineage,
        evidence: Evidence,
        effect_history: tuple[MatchedEffectObservation, ...],
        diagnostic_history: tuple[ModelAdequacyDiagnostic, ...],
    ) -> tuple[BeliefModelLineage, ModelBeliefUpdate, MatchedEffectObservation]:
        self._validate_lineage(lineage)
        before = lineage.current_state
        comparison_group_id = _comparison_group_id(evidence)
        cutoff_sequence = before.state.sequence + 1
        sigma_estimate = self.select_sigma(
            lineage=lineage,
            evidence=evidence,
            comparison_group_id=comparison_group_id,
            cutoff_sequence=cutoff_sequence,
            effect_history=effect_history,
        )
        diagnostic = self.produce_diagnostic(
            lineage=lineage,
            evidence=evidence,
            comparison_group_id=comparison_group_id,
            sigma_estimate=sigma_estimate,
            diagnostic_history=diagnostic_history,
        )
        bayesian_update = self.create_belief_update(
            lineage=lineage,
            evidence=evidence,
            sigma_estimate=sigma_estimate,
        )
        posterior_state = ModelBeliefState(
            belief_model_id=self.model_id,
            belief_model_version=self.model_version,
            lineage_id=lineage.lineage_id,
            state=bayesian_update.posterior_belief_state,
        )
        model_update_id = _stable_id(
            "model-update",
            {
                "belief_model_id": self.model_id,
                "belief_model_version": self.model_version,
                "evidence_id": evidence.evidence_id,
                "lineage_id": lineage.lineage_id,
                "posterior_state_id": posterior_state.state.belief_state_id,
                "sigma_estimate_id": sigma_estimate.estimate_id,
            },
        )
        model_update = ModelBeliefUpdate(
            model_update_id=model_update_id,
            belief_model_id=self.model_id,
            belief_model_version=self.model_version,
            lineage_id=lineage.lineage_id,
            state_before=before,
            evidence=evidence,
            sigma_estimate=sigma_estimate,
            bayesian_update=bayesian_update,
            posterior_state=posterior_state,
            diagnostic=diagnostic,
            created_at=evidence.created_at,
            provenance=Provenance.create(
                method="versioned-gaussian-belief-update",
                version=self.model_version,
                details={
                    "bayesian_update_id": bayesian_update.update_id,
                    "belief_model_id": self.model_id,
                    "evidence_id": evidence.evidence_id,
                    "lineage_id": lineage.lineage_id,
                    "sigma_estimate_id": sigma_estimate.estimate_id,
                },
            ),
        )
        updated_lineage = replace(lineage, current_state=posterior_state)
        current_effect = MatchedEffectObservation.from_decision(
            evidence,
            available_sequence=cutoff_sequence,
        )
        return updated_lineage, model_update, current_effect

    def _validate_lineage(self, lineage: BeliefModelLineage) -> None:
        if (
            lineage.belief_model_id != self.model_id
            or lineage.belief_model_version != self.model_version
        ):
            raise ReasoningError("Belief model cannot read or update another model's lineage.")

    def select_sigma(
        self,
        *,
        lineage: BeliefModelLineage,
        evidence: Evidence,
        comparison_group_id: str,
        cutoff_sequence: int,
        effect_history: tuple[MatchedEffectObservation, ...],
    ) -> SigmaEstimate:
        self._validate_lineage(lineage)
        if cutoff_sequence != lineage.current_state.state.sequence + 1:
            raise ReasoningError("Sigma cutoff must equal the lineage's next update sequence.")
        if comparison_group_id != _comparison_group_id(evidence):
            raise ReasoningError("Sigma comparison group must match the current evidence.")
        eligible = tuple(
            sorted(
                (
                    item
                    for item in effect_history
                    if item.comparison_group_id == comparison_group_id
                    and item.available_sequence < cutoff_sequence
                    and item.effect_id != evidence.evidence_id
                ),
                key=lambda item: (item.available_sequence, item.effect_id),
            )
        )
        values = tuple(item.observed_effect for item in eligible)
        if self.model_id == FIXED_SIGMA_MODEL_ID:
            status: SigmaEstimateStatus = "fixed"
            sample_mean: float | None = None
            raw_sigma: float | None = None
            estimated_sigma = FIXED_SIGMA
            sources: tuple[MatchedEffectObservation, ...] = ()
        elif len(eligible) < MINIMUM_PRIOR_EFFECTS:
            status = "baseline_fallback"
            sample_mean = statistics.fmean(values) if values else None
            raw_sigma = statistics.stdev(values) if len(values) >= 2 else None
            estimated_sigma = FIXED_SIGMA
            sources = eligible
        else:
            status = "calibrated"
            sample_mean = statistics.fmean(values)
            raw_sigma = statistics.stdev(values)
            estimated_sigma = max(raw_sigma, SIGMA_FLOOR)
            sources = eligible

        source_ids = tuple(item.effect_id for item in sources)
        estimate_id = _stable_id(
            "sigma-estimate",
            {
                "belief_model_id": self.model_id,
                "cutoff_sequence": cutoff_sequence,
                "evidence_id": evidence.evidence_id,
                "lineage_id": lineage.lineage_id,
                "source_effect_ids": source_ids,
                "status": status,
            },
        )
        return SigmaEstimate(
            estimate_id=estimate_id,
            belief_model_id=self.model_id,
            belief_model_version=self.model_version,
            lineage_id=lineage.lineage_id,
            evidence_id=evidence.evidence_id,
            comparison_group_id=comparison_group_id,
            cutoff_sequence=cutoff_sequence,
            source_effect_ids=source_ids,
            sample_count=len(sources),
            sample_mean=sample_mean,
            raw_sample_standard_deviation=raw_sigma,
            sigma_floor=SIGMA_FLOOR,
            variance_floor=VARIANCE_FLOOR,
            estimated_sigma=estimated_sigma,
            status=status,
            estimator_version=SIGMA_ESTIMATOR_VERSION,
            current_evidence_excluded=True,
            created_at=evidence.created_at,
            provenance=Provenance.create(
                method="select-pre-update-evidence-standard-deviation",
                version=SIGMA_ESTIMATOR_VERSION,
                details={
                    "belief_model_id": self.model_id,
                    "comparison_group_id": comparison_group_id,
                    "current_evidence_excluded": True,
                    "ddof": 1,
                    "estimated_sigma": estimated_sigma,
                    "evidence_id": evidence.evidence_id,
                    "lineage_id": lineage.lineage_id,
                    "minimum_prior_effects": MINIMUM_PRIOR_EFFECTS,
                    "sample_count": len(sources),
                    "source_effect_ids": json.dumps(source_ids),
                    "status": status,
                },
            ),
        )

    def calculate_likelihoods(
        self,
        *,
        evidence: Evidence,
        sigma_estimate: SigmaEstimate,
    ) -> tuple[tuple[str, float], ...]:
        self._validate_estimate(sigma_estimate)
        if sigma_estimate.evidence_id != evidence.evidence_id:
            raise ReasoningError("Sigma estimate must belong to the current evidence.")
        return tuple(
            (
                hypothesis.hypothesis_id,
                hypothesis.prediction_model.likelihood(evidence.observed_comparison),
            )
            for hypothesis in self._hypotheses(sigma_estimate.estimated_sigma)
        )

    def create_belief_update(
        self,
        *,
        lineage: BeliefModelLineage,
        evidence: Evidence,
        sigma_estimate: SigmaEstimate,
    ) -> BeliefUpdate:
        self._validate_lineage(lineage)
        self._validate_estimate(sigma_estimate)
        self._validate_estimate_context(
            lineage=lineage,
            evidence=evidence,
            comparison_group_id=_comparison_group_id(evidence),
            estimate=sigma_estimate,
        )
        return BayesianBeliefUpdater(update_rule_version=UPDATE_RULE_VERSION).update(
            hypotheses=self._hypotheses(sigma_estimate.estimated_sigma),
            belief_state=lineage.current_state.state,
            evidence=evidence,
        )

    def produce_diagnostic(
        self,
        *,
        lineage: BeliefModelLineage,
        evidence: Evidence,
        comparison_group_id: str,
        sigma_estimate: SigmaEstimate,
        diagnostic_history: tuple[ModelAdequacyDiagnostic, ...],
    ) -> ModelAdequacyDiagnostic:
        self._validate_lineage(lineage)
        self._validate_estimate(sigma_estimate)
        self._validate_estimate_context(
            lineage=lineage,
            evidence=evidence,
            comparison_group_id=comparison_group_id,
            estimate=sigma_estimate,
        )
        return _diagnose(
            model=self,
            lineage=lineage,
            evidence=evidence,
            comparison_group_id=comparison_group_id,
            sigma_estimate=sigma_estimate,
            hypotheses=self._hypotheses(sigma_estimate.estimated_sigma),
            diagnostic_history=diagnostic_history,
        )

    def _hypotheses(self, sigma: float) -> tuple[Hypothesis, ...]:
        return _hypotheses_with_sigma(
            sigma,
            prediction_version=f"{self.model_version}/evidence-prediction",
        )

    def _validate_estimate(self, estimate: SigmaEstimate) -> None:
        if (
            estimate.belief_model_id != self.model_id
            or estimate.belief_model_version != self.model_version
        ):
            raise ReasoningError("Belief model cannot use another model's sigma estimate.")

    @staticmethod
    def _validate_estimate_context(
        *,
        lineage: BeliefModelLineage,
        evidence: Evidence,
        comparison_group_id: str,
        estimate: SigmaEstimate,
    ) -> None:
        if estimate.lineage_id != lineage.lineage_id:
            raise ReasoningError("Sigma estimate belongs to another belief lineage.")
        if estimate.evidence_id != evidence.evidence_id:
            raise ReasoningError("Sigma estimate must belong to the current evidence.")
        if estimate.comparison_group_id != comparison_group_id:
            raise ReasoningError("Sigma estimate comparison group does not match evidence.")


def belief_models() -> tuple[GaussianBeliefModel, ...]:
    """Return the two frozen belief models in stable order."""

    return (
        GaussianBeliefModel(FIXED_SIGMA_MODEL_ID, FIXED_SIGMA_MODEL_VERSION),
        GaussianBeliefModel(CALIBRATED_SIGMA_MODEL_ID, CALIBRATED_SIGMA_MODEL_VERSION),
    )


def belief_model(model_id: str) -> GaussianBeliefModel:
    for model in belief_models():
        if model.model_id == model_id:
            return model
    raise ReasoningError(f"Unknown belief model: {model_id}")


def initial_model_lineage(
    model: GaussianBeliefModel,
    *,
    lineage_key: str,
    created_at: str,
) -> BeliefModelLineage:
    """Create a separate uniform-prior state for one model lineage."""

    hypotheses = tuple(sorted(optimizer_effect_hypotheses(), key=lambda item: item.hypothesis_id))
    hypothesis_ids = tuple(item.hypothesis_id for item in hypotheses)
    priors = tuple(item.prior_probability for item in hypotheses)
    lineage_id = _stable_id(
        "lineage",
        {
            "belief_model_id": model.model_id,
            "belief_model_version": model.model_version,
            "lineage_key": lineage_key,
        },
    )
    state_id = _stable_id(
        "model-belief",
        {
            "belief_model_id": model.model_id,
            "lineage_id": lineage_id,
            "priors": priors,
            "sequence": 0,
        },
    )
    state = ModelBeliefState(
        belief_model_id=model.model_id,
        belief_model_version=model.model_version,
        lineage_id=lineage_id,
        state=BeliefState(
            belief_state_id=state_id,
            hypothesis_ids=hypothesis_ids,
            prior_probabilities=priors,
            posterior_probabilities=priors,
            evidence_ids=(),
            sequence=0,
            created_at=created_at,
        ),
    )
    return BeliefModelLineage(
        lineage_id=lineage_id,
        belief_model_id=model.model_id,
        belief_model_version=model.model_version,
        lineage_key=lineage_key,
        current_state=state,
        created_at=created_at,
    )


def _diagnose(
    *,
    model: GaussianBeliefModel,
    lineage: BeliefModelLineage,
    evidence: Evidence,
    comparison_group_id: str,
    sigma_estimate: SigmaEstimate,
    hypotheses: tuple[Hypothesis, ...],
    diagnostic_history: tuple[ModelAdequacyDiagnostic, ...],
) -> ModelAdequacyDiagnostic:
    probabilities = lineage.current_state.state.posterior_probabilities
    means = tuple(item.prediction_model.parameters()["mean"] for item in hypotheses)
    sigma = sigma_estimate.estimated_sigma
    observed = evidence.observed_comparison
    predictive_mean = math.fsum(
        probability * mean for probability, mean in zip(probabilities, means, strict=True)
    )
    predictive_variance = sigma**2 + math.fsum(
        probability * (mean - predictive_mean) ** 2
        for probability, mean in zip(probabilities, means, strict=True)
    )
    density = math.fsum(
        probability * _normal_density(observed, mean, sigma)
        for probability, mean in zip(probabilities, means, strict=True)
    )
    density = max(density, sys.float_info.min)
    cdf = min(
        1.0,
        max(
            0.0,
            math.fsum(
                probability * _normal_cdf(observed, mean, sigma)
                for probability, mean in zip(probabilities, means, strict=True)
            ),
        ),
    )
    tail_probability = min(1.0, max(0.0, 2.0 * min(cdf, 1.0 - cdf)))
    standardized_residual = (observed - predictive_mean) / math.sqrt(predictive_variance)
    per_hypothesis = tuple(
        (hypothesis.hypothesis_id, (observed - mean) / sigma)
        for hypothesis, mean in zip(hypotheses, means, strict=True)
    )
    intervals = tuple(
        _central_interval(
            probability=probability,
            observed=observed,
            weights=probabilities,
            means=means,
            sigma=sigma,
        )
        for probability in (0.50, 0.80, 0.95)
    )
    residual_outlier = abs(standardized_residual) > RESIDUAL_OUTLIER_THRESHOLD
    prior_outliers = [item.residual_outlier for item in diagnostic_history[-4:]]
    rolling_outlier_count = sum((*prior_outliers, residual_outlier))
    repeated_alarm = rolling_outlier_count >= RESIDUAL_ALARM_COUNT
    tail_alarm = tail_probability < TAIL_ALARM_THRESHOLD
    disagree = tail_alarm != residual_outlier
    residual_count = len(diagnostic_history) + 1
    if tail_alarm or repeated_alarm:
        adequacy_state: AdequacyState = "appears_misspecified"
    elif residual_count < ADEQUACY_MINIMUM_RESIDUALS or disagree:
        adequacy_state = "uncertain"
    else:
        adequacy_state = "adequate"
    diagnostic_id = _stable_id(
        "model-diagnostic",
        {
            "belief_model_id": model.model_id,
            "evidence_id": evidence.evidence_id,
            "lineage_id": lineage.lineage_id,
            "sigma_estimate_id": sigma_estimate.estimate_id,
        },
    )
    return ModelAdequacyDiagnostic(
        diagnostic_id=diagnostic_id,
        belief_model_id=model.model_id,
        belief_model_version=model.model_version,
        lineage_id=lineage.lineage_id,
        belief_state_before_id=lineage.current_state.state.belief_state_id,
        evidence_id=evidence.evidence_id,
        sigma_estimate_id=sigma_estimate.estimate_id,
        comparison_group_id=comparison_group_id,
        predictive_mean=predictive_mean,
        predictive_variance=predictive_variance,
        predictive_density=density,
        predictive_log_likelihood=math.log(density),
        predictive_cdf=cdf,
        posterior_predictive_tail_probability=tail_probability,
        standardized_residual=standardized_residual,
        per_hypothesis_residuals=per_hypothesis,
        central_intervals=intervals,
        residual_count=residual_count,
        rolling_residual_outlier_count=rolling_outlier_count,
        tail_alarm=tail_alarm,
        residual_outlier=residual_outlier,
        repeated_residual_alarm=repeated_alarm,
        diagnostics_disagree=disagree,
        adequacy_state=adequacy_state,
        diagnostic_version=ADEQUACY_DIAGNOSTIC_VERSION,
        created_at=evidence.created_at,
        provenance=Provenance.create(
            method="prequential-posterior-predictive-diagnostic",
            version=ADEQUACY_DIAGNOSTIC_VERSION,
            details={
                "belief_state_before_id": lineage.current_state.state.belief_state_id,
                "evidence_id": evidence.evidence_id,
                "hidden_truth_available": False,
                "residual_count": residual_count,
                "sigma_estimate_id": sigma_estimate.estimate_id,
            },
        ),
    )


def _hypotheses_with_sigma(sigma: float, *, prediction_version: str) -> tuple[Hypothesis, ...]:
    return tuple(
        Hypothesis(
            hypothesis_id=hypothesis.hypothesis_id,
            statement=hypothesis.statement,
            prior_probability=hypothesis.prior_probability,
            prediction_model=GaussianEvidencePrediction(
                mean=hypothesis.prediction_model.parameters()["mean"],
                standard_deviation=sigma,
                model_version=prediction_version,
            ),
        )
        for hypothesis in optimizer_effect_hypotheses()
    )


def _comparison_group_id(evidence: Evidence) -> str:
    value = evidence.provenance.details_dict().get("comparison_group_id")
    if not isinstance(value, str) or not value.strip():
        raise ReasoningError("Evidence lacks a public comparison-group identity.")
    return value


def _normal_density(value: float, mean: float, sigma: float) -> float:
    standardized = (value - mean) / sigma
    return math.exp(-0.5 * standardized**2) / (sigma * math.sqrt(2.0 * math.pi))


def _normal_cdf(value: float, mean: float, sigma: float) -> float:
    return 0.5 * (1.0 + math.erf((value - mean) / (sigma * math.sqrt(2.0))))


def _mixture_cdf(
    value: float,
    *,
    weights: tuple[float, ...],
    means: tuple[float, ...],
    sigma: float,
) -> float:
    return math.fsum(
        weight * _normal_cdf(value, mean, sigma)
        for weight, mean in zip(weights, means, strict=True)
    )


def _mixture_quantile(
    probability: float,
    *,
    weights: tuple[float, ...],
    means: tuple[float, ...],
    sigma: float,
) -> float:
    lower = min(means) - 12.0 * sigma
    upper = max(means) + 12.0 * sigma
    for _ in range(100):
        midpoint = (lower + upper) / 2.0
        if _mixture_cdf(midpoint, weights=weights, means=means, sigma=sigma) < probability:
            lower = midpoint
        else:
            upper = midpoint
    return (lower + upper) / 2.0


def _central_interval(
    *,
    probability: float,
    observed: float,
    weights: tuple[float, ...],
    means: tuple[float, ...],
    sigma: float,
) -> PredictiveInterval:
    tail = (1.0 - probability) / 2.0
    lower = _mixture_quantile(tail, weights=weights, means=means, sigma=sigma)
    upper = _mixture_quantile(1.0 - tail, weights=weights, means=means, sigma=sigma)
    return PredictiveInterval(
        probability=probability,
        lower=lower,
        upper=upper,
        contains_observation=lower <= observed <= upper,
    )


def _stable_id(prefix: str, payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"
