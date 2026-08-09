"""Domain-independent scientific reasoning abstractions."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

PROBABILITY_TOLERANCE = 1e-9
DEFAULT_UPDATE_RULE_VERSION = "bayesian-update/v1"

type ProvenanceValue = str | int | float | bool | None


class ReasoningError(ValueError):
    """Base class for invalid reasoning operations."""


class DuplicateEvidenceError(ReasoningError):
    """Raised when evidence is applied twice in one belief lineage."""


class InvalidBeliefUpdateError(ReasoningError):
    """Raised when likelihoods cannot produce a valid posterior."""


@dataclass(frozen=True, slots=True)
class Provenance:
    """Immutable, flat provenance metadata for a derived scientific object."""

    method: str
    version: str
    details: tuple[tuple[str, ProvenanceValue], ...]

    @classmethod
    def create(
        cls,
        *,
        method: str,
        version: str,
        details: Mapping[str, ProvenanceValue],
    ) -> Provenance:
        return cls(method=method, version=version, details=tuple(sorted(details.items())))

    def __post_init__(self) -> None:
        _require_text(self.method, "Provenance method")
        _require_text(self.version, "Provenance version")
        keys = tuple(key for key, _ in self.details)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ReasoningError("Provenance detail keys must be unique and sorted.")
        for key, value in self.details:
            _require_text(key, "Provenance detail key")
            if isinstance(value, float) and not math.isfinite(value):
                raise ReasoningError(f"Provenance detail {key!r} must be finite.")

    def details_dict(self) -> dict[str, ProvenanceValue]:
        return dict(self.details)

    def to_dict(self) -> dict[str, object]:
        return {
            "method": self.method,
            "version": self.version,
            "details": self.details_dict(),
        }


class EvidencePredictionModel(Protocol):
    """A deterministic distribution over an observed evidence comparison."""

    @property
    def model_type(self) -> str:
        """Return the stable prediction-model type."""

    @property
    def version(self) -> str:
        """Return the prediction-model version."""

    def likelihood(self, observed_comparison: float) -> float:
        """Return the likelihood density assigned to an observed comparison."""

    def parameters(self) -> dict[str, float]:
        """Return parameters sufficient to reconstruct this prediction model."""


@dataclass(frozen=True, slots=True)
class GaussianEvidencePrediction:
    """A fixed univariate Gaussian prediction for a numeric evidence value."""

    mean: float
    standard_deviation: float
    model_version: str = "gaussian-evidence/v1"

    def __post_init__(self) -> None:
        if not math.isfinite(self.mean):
            raise ReasoningError("Gaussian mean must be finite.")
        if not math.isfinite(self.standard_deviation) or self.standard_deviation <= 0.0:
            raise ReasoningError("Gaussian standard deviation must be finite and positive.")
        _require_text(self.model_version, "Prediction-model version")

    @property
    def model_type(self) -> str:
        return "gaussian"

    @property
    def version(self) -> str:
        return self.model_version

    def likelihood(self, observed_comparison: float) -> float:
        if not math.isfinite(observed_comparison):
            raise ReasoningError("Observed comparison must be finite.")
        standardized = (observed_comparison - self.mean) / self.standard_deviation
        normalizer = self.standard_deviation * math.sqrt(2.0 * math.pi)
        return math.exp(-0.5 * standardized * standardized) / normalizer

    def parameters(self) -> dict[str, float]:
        return {"mean": self.mean, "standard_deviation": self.standard_deviation}


def prediction_model_from_record(
    *, model_type: str, version: str, parameters: Mapping[str, float]
) -> EvidencePredictionModel:
    """Reconstruct a supported deterministic prediction model."""

    if model_type != "gaussian":
        raise ReasoningError(f"Unsupported prediction model type: {model_type}")
    try:
        mean = parameters["mean"]
        standard_deviation = parameters["standard_deviation"]
    except KeyError as error:
        raise ReasoningError(f"Missing Gaussian prediction parameter: {error.args[0]}") from error
    return GaussianEvidencePrediction(
        mean=mean,
        standard_deviation=standard_deviation,
        model_version=version,
    )


@dataclass(frozen=True, slots=True)
class Hypothesis:
    """A stable scientific claim with a prior and predicted evidence distribution."""

    hypothesis_id: str
    statement: str
    prior_probability: float
    prediction_model: EvidencePredictionModel

    def __post_init__(self) -> None:
        _require_text(self.hypothesis_id, "Hypothesis ID")
        _require_text(self.statement, "Hypothesis statement")
        if not math.isfinite(self.prior_probability) or not 0.0 <= self.prior_probability <= 1.0:
            raise ReasoningError("Hypothesis prior probability must be finite and in [0, 1].")

    def to_dict(self) -> dict[str, object]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "statement": self.statement,
            "prior_probability": self.prior_probability,
            "prediction_model": {
                "type": self.prediction_model.model_type,
                "version": self.prediction_model.version,
                "parameters": self.prediction_model.parameters(),
            },
        }


@dataclass(frozen=True, slots=True)
class Evidence:
    """A reproducible comparison derived from one or more source experiments."""

    evidence_id: str
    source_experiment_ids: tuple[int, ...]
    observed_comparison: float
    observed_outcome: str
    provenance: Provenance
    created_at: str

    def __post_init__(self) -> None:
        _require_text(self.evidence_id, "Evidence ID")
        _require_text(self.observed_outcome, "Observed outcome")
        _require_text(self.created_at, "Evidence creation time")
        if not self.source_experiment_ids:
            raise ReasoningError("Evidence must reference at least one source experiment.")
        if any(source_id <= 0 for source_id in self.source_experiment_ids):
            raise ReasoningError("Evidence source experiment IDs must be positive.")
        if self.source_experiment_ids != tuple(sorted(set(self.source_experiment_ids))):
            raise ReasoningError("Evidence source experiment IDs must be unique and sorted.")
        if not math.isfinite(self.observed_comparison):
            raise ReasoningError("Evidence observed comparison must be finite.")

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "source_experiment_ids": list(self.source_experiment_ids),
            "observed_comparison": self.observed_comparison,
            "observed_outcome": self.observed_outcome,
            "provenance": self.provenance.to_dict(),
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class BeliefState:
    """A normalized prior and current posterior over competing hypotheses."""

    belief_state_id: str
    hypothesis_ids: tuple[str, ...]
    prior_probabilities: tuple[float, ...]
    posterior_probabilities: tuple[float, ...]
    evidence_ids: tuple[str, ...]
    sequence: int
    created_at: str
    parent_belief_state_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.belief_state_id, "Belief-state ID")
        _require_text(self.created_at, "Belief-state creation time")
        if not self.hypothesis_ids:
            raise ReasoningError("Belief state must contain at least one hypothesis.")
        if self.hypothesis_ids != tuple(sorted(set(self.hypothesis_ids))):
            raise ReasoningError("Belief-state hypothesis IDs must be unique and sorted.")
        if len(self.prior_probabilities) != len(self.hypothesis_ids):
            raise ReasoningError("Belief-state prior probabilities do not match hypotheses.")
        if len(self.posterior_probabilities) != len(self.hypothesis_ids):
            raise ReasoningError("Belief-state posterior probabilities do not match hypotheses.")
        _validate_probability_distribution(self.prior_probabilities, "Prior")
        _validate_probability_distribution(self.posterior_probabilities, "Posterior")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ReasoningError("Belief state cannot contain duplicate evidence IDs.")
        if self.sequence < 0 or self.sequence != len(self.evidence_ids):
            raise ReasoningError("Belief-state sequence must equal its evidence count.")
        if self.sequence == 0 and self.parent_belief_state_id is not None:
            raise ReasoningError("Initial belief state cannot have a parent.")
        if self.sequence > 0 and self.parent_belief_state_id is None:
            raise ReasoningError("Updated belief state must reference its parent.")

    def prior_for(self, hypothesis_id: str) -> float:
        return self.prior_probabilities[self._hypothesis_index(hypothesis_id)]

    def posterior_for(self, hypothesis_id: str) -> float:
        return self.posterior_probabilities[self._hypothesis_index(hypothesis_id)]

    def prior_map(self) -> dict[str, float]:
        return dict(zip(self.hypothesis_ids, self.prior_probabilities, strict=True))

    def posterior_map(self) -> dict[str, float]:
        return dict(zip(self.hypothesis_ids, self.posterior_probabilities, strict=True))

    def to_dict(self) -> dict[str, object]:
        return {
            "belief_state_id": self.belief_state_id,
            "parent_belief_state_id": self.parent_belief_state_id,
            "sequence": self.sequence,
            "prior_probabilities": self.prior_map(),
            "posterior_probabilities": self.posterior_map(),
            "evidence_ids": list(self.evidence_ids),
            "created_at": self.created_at,
        }

    def _hypothesis_index(self, hypothesis_id: str) -> int:
        try:
            return self.hypothesis_ids.index(hypothesis_id)
        except ValueError as error:
            raise ReasoningError(f"Unknown hypothesis in belief state: {hypothesis_id}") from error


@dataclass(frozen=True, slots=True)
class HypothesisLikelihood:
    """The complete calculation for one hypothesis in a belief update."""

    hypothesis_id: str
    prior_for_update: float
    likelihood: float
    unnormalized_weight: float
    posterior_probability: float

    def __post_init__(self) -> None:
        _require_text(self.hypothesis_id, "Likelihood hypothesis ID")
        for name, value in (
            ("prior for update", self.prior_for_update),
            ("likelihood", self.likelihood),
            ("unnormalized weight", self.unnormalized_weight),
            ("posterior probability", self.posterior_probability),
        ):
            if not math.isfinite(value) or value < 0.0:
                raise ReasoningError(f"Hypothesis {name} must be finite and non-negative.")

    def to_dict(self) -> dict[str, object]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "prior_for_update": self.prior_for_update,
            "likelihood": self.likelihood,
            "unnormalized_weight": self.unnormalized_weight,
            "posterior_probability": self.posterior_probability,
        }


@dataclass(frozen=True, slots=True)
class BeliefUpdate:
    """A complete evidence-to-posterior Bayesian update event."""

    update_id: str
    belief_state_before: BeliefState
    evidence: Evidence
    likelihoods: tuple[HypothesisLikelihood, ...]
    posterior_belief_state: BeliefState
    update_rule_version: str
    normalization_constant: float
    provenance: Provenance
    created_at: str

    def __post_init__(self) -> None:
        _require_text(self.update_id, "Belief-update ID")
        _require_text(self.update_rule_version, "Belief-update rule version")
        _require_text(self.created_at, "Belief-update creation time")
        if not math.isfinite(self.normalization_constant) or self.normalization_constant <= 0.0:
            raise InvalidBeliefUpdateError(
                "Belief-update normalization constant must be finite and positive."
            )
        likelihood_ids = tuple(item.hypothesis_id for item in self.likelihoods)
        if likelihood_ids != self.belief_state_before.hypothesis_ids:
            raise ReasoningError("Belief-update likelihoods must cover every hypothesis in order.")
        posterior = self.posterior_belief_state
        if posterior.parent_belief_state_id != self.belief_state_before.belief_state_id:
            raise ReasoningError(
                "Posterior belief state must reference the state before the update."
            )
        expected_evidence_ids = self.belief_state_before.evidence_ids + (self.evidence.evidence_id,)
        if posterior.evidence_ids != expected_evidence_ids:
            raise ReasoningError("Posterior belief state must append exactly the update evidence.")

    def to_dict(self) -> dict[str, object]:
        return {
            "update_id": self.update_id,
            "belief_state_before": self.belief_state_before.to_dict(),
            "evidence": self.evidence.to_dict(),
            "likelihoods": [item.to_dict() for item in self.likelihoods],
            "posterior_belief_state": self.posterior_belief_state.to_dict(),
            "update_rule_version": self.update_rule_version,
            "normalization_constant": self.normalization_constant,
            "provenance": self.provenance.to_dict(),
            "created_at": self.created_at,
        }


class BayesianBeliefUpdater:
    """Apply deterministic discrete Bayes updates using hypothesis likelihood models."""

    def __init__(self, update_rule_version: str = DEFAULT_UPDATE_RULE_VERSION) -> None:
        _require_text(update_rule_version, "Belief-update rule version")
        self.update_rule_version = update_rule_version

    def update(
        self,
        *,
        hypotheses: tuple[Hypothesis, ...],
        belief_state: BeliefState,
        evidence: Evidence,
    ) -> BeliefUpdate:
        ordered_hypotheses = tuple(sorted(hypotheses, key=lambda item: item.hypothesis_id))
        hypothesis_ids = tuple(item.hypothesis_id for item in ordered_hypotheses)
        if hypothesis_ids != belief_state.hypothesis_ids:
            raise ReasoningError("Hypotheses do not match the belief state.")
        if evidence.evidence_id in belief_state.evidence_ids:
            raise DuplicateEvidenceError(
                f"Evidence {evidence.evidence_id} is already present in this belief lineage."
            )

        likelihood_values: list[float] = []
        unnormalized_weights: list[float] = []
        for hypothesis in ordered_hypotheses:
            likelihood = hypothesis.prediction_model.likelihood(evidence.observed_comparison)
            if not math.isfinite(likelihood) or likelihood < 0.0:
                raise InvalidBeliefUpdateError(
                    f"Hypothesis {hypothesis.hypothesis_id} produced an invalid likelihood."
                )
            prior_for_update = belief_state.posterior_for(hypothesis.hypothesis_id)
            weight = prior_for_update * likelihood
            if not math.isfinite(weight) or weight < 0.0:
                raise InvalidBeliefUpdateError(
                    f"Hypothesis {hypothesis.hypothesis_id} produced an invalid weight."
                )
            likelihood_values.append(likelihood)
            unnormalized_weights.append(weight)

        normalization_constant = math.fsum(unnormalized_weights)
        if not math.isfinite(normalization_constant) or normalization_constant <= 0.0:
            raise InvalidBeliefUpdateError(
                "Evidence has zero or numerically invalid total likelihood; belief state unchanged."
            )

        posterior_values = tuple(weight / normalization_constant for weight in unnormalized_weights)
        posterior_state_id = _stable_id(
            "belief",
            {
                "before": belief_state.belief_state_id,
                "evidence": evidence.evidence_id,
                "posterior": posterior_values,
                "rule": self.update_rule_version,
            },
        )
        posterior_state = BeliefState(
            belief_state_id=posterior_state_id,
            hypothesis_ids=hypothesis_ids,
            prior_probabilities=belief_state.prior_probabilities,
            posterior_probabilities=posterior_values,
            evidence_ids=belief_state.evidence_ids + (evidence.evidence_id,),
            sequence=belief_state.sequence + 1,
            created_at=evidence.created_at,
            parent_belief_state_id=belief_state.belief_state_id,
        )

        calculations = tuple(
            HypothesisLikelihood(
                hypothesis_id=hypothesis.hypothesis_id,
                prior_for_update=belief_state.posterior_for(hypothesis.hypothesis_id),
                likelihood=likelihood,
                unnormalized_weight=weight,
                posterior_probability=posterior,
            )
            for hypothesis, likelihood, weight, posterior in zip(
                ordered_hypotheses,
                likelihood_values,
                unnormalized_weights,
                posterior_values,
                strict=True,
            )
        )
        update_id = _stable_id(
            "update",
            {
                "before": belief_state.belief_state_id,
                "evidence": evidence.evidence_id,
                "posterior": posterior_state_id,
                "rule": self.update_rule_version,
            },
        )
        provenance = Provenance.create(
            method="discrete-bayesian-belief-update",
            version=self.update_rule_version,
            details={
                "belief_state_before_id": belief_state.belief_state_id,
                "evidence_id": evidence.evidence_id,
                "formula": "posterior = prior_for_update * likelihood / normalization_constant",
                "hypothesis_count": len(ordered_hypotheses),
                "normalization_constant": normalization_constant,
                "posterior_belief_state_id": posterior_state_id,
            },
        )
        return BeliefUpdate(
            update_id=update_id,
            belief_state_before=belief_state,
            evidence=evidence,
            likelihoods=calculations,
            posterior_belief_state=posterior_state,
            update_rule_version=self.update_rule_version,
            normalization_constant=normalization_constant,
            provenance=provenance,
            created_at=evidence.created_at,
        )


def initial_belief_state(hypotheses: tuple[Hypothesis, ...], *, created_at: str) -> BeliefState:
    """Create the normalized initial state from hypothesis priors."""

    ordered_hypotheses = tuple(sorted(hypotheses, key=lambda item: item.hypothesis_id))
    hypothesis_ids = tuple(item.hypothesis_id for item in ordered_hypotheses)
    if len(hypothesis_ids) != len(set(hypothesis_ids)):
        raise ReasoningError("Hypothesis IDs must be unique.")
    priors = tuple(item.prior_probability for item in ordered_hypotheses)
    state_id = _stable_id(
        "belief",
        {"hypothesis_ids": hypothesis_ids, "priors": priors, "sequence": 0},
    )
    return BeliefState(
        belief_state_id=state_id,
        hypothesis_ids=hypothesis_ids,
        prior_probabilities=priors,
        posterior_probabilities=priors,
        evidence_ids=(),
        sequence=0,
        created_at=created_at,
    )


def _validate_probability_distribution(probabilities: tuple[float, ...], label: str) -> None:
    if any(not math.isfinite(value) or value < 0.0 for value in probabilities):
        raise ReasoningError(f"{label} probabilities must be finite and non-negative.")
    total = math.fsum(probabilities)
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=PROBABILITY_TOLERANCE):
        raise ReasoningError(f"{label} probabilities must sum to 1; received {total!r}.")


def _stable_id(prefix: str, payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _require_text(value: str, label: str) -> None:
    if not value.strip():
        raise ReasoningError(f"{label} must not be empty.")
