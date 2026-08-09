"""Truth-free finite-table information gain for generic Core workloads."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from functools import reduce
from math import gcd
from types import MappingProxyType
from typing import ClassVar, Final, Literal, cast

from research_decision_engine.policy_contracts import (
    INFORMATION_GAIN_TABLE_CLASSIFICATION,
    INFORMATION_GAIN_TABLE_POLICY_ID,
    RUNSPEC_CANDIDATE_ORDER,
    PolicyContractError,
    UnsupportedPolicyForSchemaError,
)
from research_decision_engine.run_spec import CandidateSpec, CompletedWorkloadExperiment

INFORMATION_GAIN_BELIEF_SCHEMA: Final = "rde-core-information-gain-belief/v1"
INFORMATION_GAIN_SCORE_QUANTUM: Final = Decimal("1e-30")
_INFORMATION_GAIN_EMIN: Final = -999_999
_INFORMATION_GAIN_EMAX: Final = 999_999

# The bound is deliberately far above JSON's signed-64 range while keeping
# adversarial construction and repeated exact multiplication finitely bounded.
# It applies to every authoritative or intermediate integer weight.
MAX_INFORMATION_GAIN_INTEGER_BITS: Final = 12_000

_EVIDENCE_MODEL_KEYS: Final = frozenset(
    {
        "hypothesis_ids",
        "prior_weight_by_hypothesis",
        "observation_metric",
        "outcome_ids",
        "outcome_thresholds",
        "likelihood_row_total",
        "likelihood_weight_by_candidate_id",
    }
)


class InformationGainContractError(PolicyContractError):
    """Base class for finite-table information-gain contract failures."""


class EvidenceModelError(InformationGainContractError):
    """Base class for invalid finite-table evidence models and observations."""


class EvidenceModelDecodeError(EvidenceModelError):
    """Canonical evidence-model bytes or payload are malformed."""


class EmptyOrDuplicateHypothesisSetError(EvidenceModelError):
    """The ordered hypothesis set is empty, duplicated, or contains invalid IDs."""


class PriorKeyMismatchError(EvidenceModelError):
    """Prior-weight keys do not exactly equal the hypothesis IDs."""


class NonpositivePriorWeightError(EvidenceModelError):
    """A prior weight is not an exact positive bounded integer."""


class InvalidOutcomeSetError(EvidenceModelError):
    """The ordered outcome set does not contain distinct valid IDs."""


class InvalidThresholdError(EvidenceModelError):
    """Evidence-model thresholds do not define a finite strict partition."""


class InvalidThresholdCountError(InvalidThresholdError):
    """The threshold count does not equal the outcome count minus one."""


class InvalidThresholdOrderError(InvalidThresholdError):
    """Thresholds are not finite and strictly increasing."""


class ObservationMetricError(EvidenceModelError):
    """An observation cannot be classified by the declared metric."""


class MissingObservationMetricError(ObservationMetricError):
    """The declared observation metric is absent."""


class NonfiniteObservationMetricError(ObservationMetricError):
    """The declared observation metric is boolean, nonnumeric, or nonfinite."""


class LikelihoodCandidateKeyMismatchError(EvidenceModelError):
    """Likelihood candidate keys do not match the exact RunSpec candidates."""


class LikelihoodHypothesisKeyMismatchError(EvidenceModelError):
    """A likelihood table does not cover the exact hypotheses."""


class LikelihoodOutcomeKeyMismatchError(EvidenceModelError):
    """A likelihood row does not cover the exact outcomes."""


class InvalidLikelihoodWeightError(EvidenceModelError):
    """A likelihood weight or row total is not an exact bounded integer."""


class LikelihoodRowTotalMismatchError(EvidenceModelError):
    """A likelihood row does not sum to the declared row total."""


class ImpossibleEvidenceError(InformationGainContractError):
    """An observation has zero probability under every current hypothesis."""


class InvalidInformationGainBeliefError(InformationGainContractError):
    """An ordered exact integer belief state is invalid."""


class UnsupportedInformationGainNumericContractError(InformationGainContractError):
    """The frozen Decimal information-gain contract cannot represent a result."""


@dataclass(frozen=True, slots=True)
class InformationGainNumericContract:
    """Public description of the frozen deterministic score calculation."""

    implementation: Literal["decimal.Decimal"] = "decimal.Decimal"
    precision: Literal[50] = 50
    rounding: Literal["ROUND_HALF_EVEN"] = "ROUND_HALF_EVEN"
    logarithm: Literal["Decimal.ln"] = "Decimal.ln"
    base_conversion: Literal["divide_by_Decimal_2_ln"] = "divide_by_Decimal_2_ln"
    score_quantum: Literal["1e-30"] = "1e-30"

    def to_payload(self) -> dict[str, object]:
        return {
            "implementation": self.implementation,
            "precision": self.precision,
            "rounding": self.rounding,
            "logarithm": self.logarithm,
            "base_conversion": self.base_conversion,
            "score_quantum": self.score_quantum,
        }


INFORMATION_GAIN_NUMERIC_CONTRACT: Final = InformationGainNumericContract()


@dataclass(frozen=True, slots=True, init=False, eq=False)
class FiniteTableEvidenceModel:
    """Immutable user-declared finite hypothesis/outcome likelihood table.

    All caller-owned collections are copied. Public mappings are read-only
    mapping proxies, and nested likelihood mappings are recursively read-only.
    """

    hypothesis_ids: tuple[str, ...]
    prior_weight_by_hypothesis: Mapping[str, int] = field(repr=False)
    observation_metric: str
    outcome_ids: tuple[str, ...]
    outcome_thresholds: tuple[int | float, ...]
    likelihood_row_total: int
    likelihood_weight_by_candidate_id: Mapping[str, Mapping[str, Mapping[str, int]]] = field(
        repr=False
    )

    def __init__(
        self,
        *,
        hypothesis_ids: Sequence[str],
        prior_weight_by_hypothesis: Mapping[str, int],
        observation_metric: str,
        outcome_ids: Sequence[str],
        outcome_thresholds: Sequence[int | float],
        likelihood_row_total: int,
        likelihood_weight_by_candidate_id: Mapping[str, Mapping[str, Mapping[str, int]]],
    ) -> None:
        hypotheses = _ordered_ids(
            hypothesis_ids,
            minimum_count=1,
            error_type=EmptyOrDuplicateHypothesisSetError,
            label="hypothesis_ids",
        )
        outcomes = _ordered_ids(
            outcome_ids,
            minimum_count=2,
            error_type=InvalidOutcomeSetError,
            label="outcome_ids",
        )
        metric = _nonempty_exact_string(observation_metric, "observation_metric")

        priors_input = _exact_mapping(
            prior_weight_by_hypothesis,
            label="prior_weight_by_hypothesis",
        )
        if frozenset(priors_input) != frozenset(hypotheses):
            raise PriorKeyMismatchError(
                "Prior-weight keys must exactly equal the declared hypothesis IDs."
            )
        priors = {
            hypothesis_id: _bounded_integer(
                priors_input[hypothesis_id],
                label=f"prior_weight_by_hypothesis[{hypothesis_id!r}]",
                minimum=1,
                error_type=NonpositivePriorWeightError,
            )
            for hypothesis_id in hypotheses
        }

        if type(outcome_thresholds) not in (list, tuple):
            raise InvalidThresholdError("outcome_thresholds must be an ordered list or tuple.")
        threshold_values = tuple(
            _finite_real(value, label=f"outcome_thresholds[{index}]")
            for index, value in enumerate(outcome_thresholds)
        )
        if len(threshold_values) != len(outcomes) - 1:
            raise InvalidThresholdCountError("Threshold count must equal outcome count minus one.")
        if any(
            left >= right
            for left, right in zip(threshold_values, threshold_values[1:], strict=False)
        ):
            raise InvalidThresholdOrderError("Outcome thresholds must be strictly increasing.")

        row_total = _bounded_integer(
            likelihood_row_total,
            label="likelihood_row_total",
            minimum=1,
            error_type=InvalidLikelihoodWeightError,
        )
        outer_input = _exact_mapping(
            likelihood_weight_by_candidate_id,
            label="likelihood_weight_by_candidate_id",
        )
        frozen_outer: dict[str, Mapping[str, Mapping[str, int]]] = {}
        for raw_candidate_id, raw_hypothesis_map in outer_input.items():
            candidate_id = _nonempty_exact_string(raw_candidate_id, "likelihood candidate ID")
            hypothesis_map = _exact_mapping(
                raw_hypothesis_map,
                label=f"likelihood[{candidate_id!r}]",
            )
            if frozenset(hypothesis_map) != frozenset(hypotheses):
                raise LikelihoodHypothesisKeyMismatchError(
                    f"Likelihood hypotheses for candidate {candidate_id!r} do not match."
                )
            frozen_hypotheses: dict[str, Mapping[str, int]] = {}
            for hypothesis_id in hypotheses:
                outcome_map = _exact_mapping(
                    hypothesis_map[hypothesis_id],
                    label=f"likelihood[{candidate_id!r}][{hypothesis_id!r}]",
                )
                if frozenset(outcome_map) != frozenset(outcomes):
                    raise LikelihoodOutcomeKeyMismatchError(
                        "Likelihood outcome keys must exactly equal the declared outcomes."
                    )
                row = {
                    outcome_id: _bounded_integer(
                        outcome_map[outcome_id],
                        label=(f"likelihood[{candidate_id!r}][{hypothesis_id!r}][{outcome_id!r}]"),
                        minimum=0,
                        error_type=InvalidLikelihoodWeightError,
                    )
                    for outcome_id in outcomes
                }
                if sum(row.values()) != row_total:
                    raise LikelihoodRowTotalMismatchError(
                        "Every likelihood row must sum to likelihood_row_total."
                    )
                # A positive row total plus exact equality already excludes all-zero rows.
                frozen_hypotheses[hypothesis_id] = MappingProxyType(row)
            frozen_outer[candidate_id] = MappingProxyType(frozen_hypotheses)

        object.__setattr__(self, "hypothesis_ids", hypotheses)
        object.__setattr__(self, "prior_weight_by_hypothesis", MappingProxyType(priors))
        object.__setattr__(self, "observation_metric", metric)
        object.__setattr__(self, "outcome_ids", outcomes)
        object.__setattr__(self, "outcome_thresholds", threshold_values)
        object.__setattr__(self, "likelihood_row_total", row_total)
        object.__setattr__(
            self,
            "likelihood_weight_by_candidate_id",
            MappingProxyType(frozen_outer),
        )

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        """Return the declared table candidate IDs without imposing semantic order."""

        return tuple(self.likelihood_weight_by_candidate_id)

    def validate_candidate_ids(self, candidate_ids: Sequence[str]) -> None:
        """Require exact coverage of one ordered RunSpec candidate identity set."""

        ordered = _ordered_ids(
            candidate_ids,
            minimum_count=1,
            error_type=LikelihoodCandidateKeyMismatchError,
            label="candidate_ids",
        )
        if frozenset(ordered) != frozenset(self.likelihood_weight_by_candidate_id):
            raise LikelihoodCandidateKeyMismatchError(
                "Likelihood candidate keys must exactly equal the RunSpec candidate IDs."
            )

    def classify_observation(self, observation: Mapping[str, object]) -> str:
        """Classify exactly one declared finite observation metric."""

        values = _exact_mapping(observation, label="observation")
        if self.observation_metric not in values:
            raise MissingObservationMetricError(
                f"Observation is missing metric {self.observation_metric!r}."
            )
        if frozenset(values) != frozenset({self.observation_metric}):
            raise ObservationMetricError(
                "Observation classification requires exactly the declared metric."
            )
        try:
            metric_value = _finite_real(
                values[self.observation_metric],
                label=f"observation[{self.observation_metric!r}]",
            )
        except InvalidThresholdError as exc:
            raise NonfiniteObservationMetricError(str(exc)) from exc
        for outcome_id, threshold in zip(
            self.outcome_ids,
            self.outcome_thresholds,
            strict=False,
        ):
            if metric_value < threshold:
                return outcome_id
        return self.outcome_ids[-1]

    def likelihood_weight(self, candidate_id: str, hypothesis_id: str, outcome_id: str) -> int:
        """Return one exact declared likelihood weight."""

        try:
            hypothesis_map = self.likelihood_weight_by_candidate_id[candidate_id]
        except KeyError as exc:
            raise LikelihoodCandidateKeyMismatchError("Unknown likelihood candidate ID.") from exc
        try:
            outcome_map = hypothesis_map[hypothesis_id]
        except KeyError as exc:
            raise LikelihoodHypothesisKeyMismatchError("Unknown likelihood hypothesis ID.") from exc
        try:
            return outcome_map[outcome_id]
        except KeyError as exc:
            raise LikelihoodOutcomeKeyMismatchError("Unknown likelihood outcome ID.") from exc

    def to_payload(self) -> dict[str, object]:
        return {
            "hypothesis_ids": list(self.hypothesis_ids),
            "prior_weight_by_hypothesis": dict(self.prior_weight_by_hypothesis),
            "observation_metric": self.observation_metric,
            "outcome_ids": list(self.outcome_ids),
            "outcome_thresholds": list(self.outcome_thresholds),
            "likelihood_row_total": self.likelihood_row_total,
            "likelihood_weight_by_candidate_id": {
                candidate_id: {
                    hypothesis_id: dict(outcome_map)
                    for hypothesis_id, outcome_map in hypothesis_map.items()
                }
                for candidate_id, hypothesis_map in (self.likelihood_weight_by_candidate_id.items())
            },
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> FiniteTableEvidenceModel:
        try:
            data = _exact_mapping(payload, label="evidence_model")
            if frozenset(data) != _EVIDENCE_MODEL_KEYS:
                raise EvidenceModelDecodeError(
                    "Evidence-model payload must contain exactly its closed fields."
                )
            return cls(
                hypothesis_ids=cast(
                    tuple[str, ...],
                    _exact_sequence(data["hypothesis_ids"], "hypothesis_ids"),
                ),
                prior_weight_by_hypothesis=cast(
                    Mapping[str, int],
                    _exact_mapping(
                        data["prior_weight_by_hypothesis"],
                        label="prior_weight_by_hypothesis",
                    ),
                ),
                observation_metric=cast(str, data["observation_metric"]),
                outcome_ids=cast(
                    tuple[str, ...],
                    _exact_sequence(data["outcome_ids"], "outcome_ids"),
                ),
                outcome_thresholds=cast(
                    Sequence[int | float],
                    _exact_sequence(data["outcome_thresholds"], "outcome_thresholds"),
                ),
                likelihood_row_total=cast(int, data["likelihood_row_total"]),
                likelihood_weight_by_candidate_id=cast(
                    Mapping[str, Mapping[str, Mapping[str, int]]],
                    _exact_mapping(
                        data["likelihood_weight_by_candidate_id"],
                        label="likelihood_weight_by_candidate_id",
                    ),
                ),
            )
        except InformationGainContractError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise EvidenceModelDecodeError("Evidence-model payload is invalid.") from exc

    def to_canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_payload())

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> FiniteTableEvidenceModel:
        if type(encoded) is not bytes:
            raise TypeError("encoded must be exact bytes.")
        try:
            text = encoded.decode("utf-8")
            payload = json.loads(
                text,
                object_pairs_hook=_object_without_duplicate_keys,
                parse_constant=_reject_nonfinite_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise EvidenceModelDecodeError("Evidence-model bytes are invalid JSON.") from exc
        if type(payload) is not dict:
            raise EvidenceModelDecodeError("Evidence-model top level must be an object.")
        model = cls.from_payload(cast(dict[str, object], payload))
        if model.to_canonical_bytes() != encoded:
            raise EvidenceModelDecodeError("Evidence-model JSON bytes are not canonical.")
        return model

    def fingerprint(self) -> str:
        return hashlib.sha256(self.to_canonical_bytes()).hexdigest()

    def __eq__(self, other: object) -> bool:
        return type(other) is FiniteTableEvidenceModel and self.to_canonical_bytes() == (
            other.to_canonical_bytes()
        )

    def __hash__(self) -> int:
        return hash(self.fingerprint())


@dataclass(frozen=True, slots=True)
class InformationGainBeliefLineage:
    """One exact completed-observation transition in hypothesis order."""

    step_index: int
    candidate_id: str
    outcome_id: str
    weights_before: tuple[int, ...]
    weights_after: tuple[int, ...]
    belief_fingerprint_before: str
    belief_fingerprint_after: str

    def __post_init__(self) -> None:
        if type(self.step_index) is not int or self.step_index < 0:
            raise InvalidInformationGainBeliefError("step_index must be a nonnegative integer.")
        _nonempty_exact_string(self.candidate_id, "candidate_id")
        _nonempty_exact_string(self.outcome_id, "outcome_id")
        before = _belief_weights(self.weights_before)
        after = _belief_weights(self.weights_after)
        if len(before) != len(after):
            raise InvalidInformationGainBeliefError(
                "Belief lineage weights must have equal nonzero lengths."
            )
        _required_fingerprint(self.belief_fingerprint_before, "belief_fingerprint_before")
        _required_fingerprint(self.belief_fingerprint_after, "belief_fingerprint_after")
        object.__setattr__(self, "weights_before", before)
        object.__setattr__(self, "weights_after", after)

    def to_payload(self) -> dict[str, object]:
        return {
            "step_index": self.step_index,
            "candidate_id": self.candidate_id,
            "outcome_id": self.outcome_id,
            "weights_before": list(self.weights_before),
            "weights_after": list(self.weights_after),
            "belief_fingerprint_before": self.belief_fingerprint_before,
            "belief_fingerprint_after": self.belief_fingerprint_after,
        }


@dataclass(frozen=True, slots=True)
class InformationGainSelectionDetails:
    """Immutable policy result used by execution, export, and replay."""

    candidate: CandidateSpec
    eligible_candidate_ids: tuple[str, ...]
    selected_information_gain_bits: str
    current_belief_weights: tuple[int, ...]
    current_belief_fingerprint: str
    evidence_model_fingerprint: str

    def selection_metadata(self) -> Mapping[str, object]:
        """Return the exact closed public decision binding."""

        return MappingProxyType(
            {
                "policy_identity": INFORMATION_GAIN_TABLE_POLICY_ID,
                "selected_candidate_id": self.candidate.candidate_id,
                "selected_information_gain_bits": self.selected_information_gain_bits,
                "eligible_candidate_count": len(self.eligible_candidate_ids),
                "current_belief_fingerprint": self.current_belief_fingerprint,
                "evidence_model_fingerprint": self.evidence_model_fingerprint,
                "tie_break": RUNSPEC_CANDIDATE_ORDER,
            }
        )


class TableInformationGainPolicy:
    """Select maximum declared-table EIG without observing or executing candidates."""

    name: ClassVar[Literal["information_gain_table"]] = "information_gain_table"
    semantic_classification: ClassVar[
        Literal["USER_DECLARED_FINITE_HYPOTHESIS_OUTCOME_LIKELIHOOD_TABLE"]
    ] = "USER_DECLARED_FINITE_HYPOTHESIS_OUTCOME_LIKELIHOOD_TABLE"
    tie_break: ClassVar[Literal["runspec_candidate_order"]] = "runspec_candidate_order"

    def __init__(self, run_spec: object) -> None:
        # Local import prevents the v3 codec's public evidence-model import from
        # forming a module cycle.
        try:
            from research_decision_engine.run_spec_v3 import RunSpecV3
        except ImportError as exc:  # pragma: no cover - transitional integration guard
            raise UnsupportedPolicyForSchemaError("RunSpec v3 is unavailable.") from exc

        if type(run_spec) is not RunSpecV3:
            raise TypeError("run_spec must be an exact RunSpecV3.")
        typed_spec = run_spec
        if typed_spec.policy_id != INFORMATION_GAIN_TABLE_POLICY_ID:
            raise UnsupportedPolicyForSchemaError(
                "TableInformationGainPolicy requires an information_gain_table RunSpec v3."
            )
        config = _exact_mapping(typed_spec.policy_config, label="policy_config")
        if frozenset(config) != frozenset({"evidence_model", "tie_break"}):
            raise InformationGainContractError(
                "information_gain_table policy configuration must be closed."
            )
        if config["tie_break"] != RUNSPEC_CANDIDATE_ORDER:
            raise InformationGainContractError(
                "information_gain_table requires runspec_candidate_order."
            )
        model = FiniteTableEvidenceModel.from_payload(
            _exact_mapping(config["evidence_model"], label="evidence_model")
        )
        raw_candidates = typed_spec.candidates
        if type(raw_candidates) not in (list, tuple):
            raise TypeError("RunSpecV3 candidates must be ordered.")
        candidates = tuple(
            CandidateSpec(candidate.candidate_id, candidate.parameters)
            for candidate in cast(Sequence[CandidateSpec], raw_candidates)
        )
        model.validate_candidate_ids(tuple(candidate.candidate_id for candidate in candidates))

        self._run_spec = run_spec
        self._run_spec_fingerprint = typed_spec.fingerprint()
        self._candidates = candidates
        self._candidate_by_id = MappingProxyType(
            {candidate.candidate_id: candidate for candidate in candidates}
        )
        self._evidence_model = model

    @property
    def evidence_model(self) -> FiniteTableEvidenceModel:
        return self._evidence_model

    def current_belief(
        self, history: Sequence[CompletedWorkloadExperiment]
    ) -> tuple[tuple[int, ...], str]:
        weights, _ = self._replay_history(history)
        return weights, information_gain_belief_fingerprint(
            self.evidence_model.hypothesis_ids,
            weights,
        )

    def select(self, history: Sequence[CompletedWorkloadExperiment]) -> CandidateSpec:
        return self.selection_details(history).candidate

    def selection_details(
        self, history: Sequence[CompletedWorkloadExperiment]
    ) -> InformationGainSelectionDetails:
        weights, completed = self._replay_history(history)
        eligible = tuple(
            candidate for candidate in self._candidates if candidate.candidate_id not in completed
        )
        if not eligible:
            raise ValueError("No available candidates remain.")
        selected = eligible[0]
        selected_score = expected_information_gain_bits(
            self.evidence_model,
            weights,
            selected.candidate_id,
        )
        for candidate in eligible[1:]:
            score = expected_information_gain_bits(
                self.evidence_model,
                weights,
                candidate.candidate_id,
            )
            if score > selected_score:
                selected = candidate
                selected_score = score
        return InformationGainSelectionDetails(
            candidate=CandidateSpec(selected.candidate_id, selected.parameters),
            eligible_candidate_ids=tuple(candidate.candidate_id for candidate in eligible),
            selected_information_gain_bits=format_information_gain_bits(selected_score),
            current_belief_weights=weights,
            current_belief_fingerprint=information_gain_belief_fingerprint(
                self.evidence_model.hypothesis_ids,
                weights,
            ),
            evidence_model_fingerprint=self.evidence_model.fingerprint(),
        )

    def selection_metadata(
        self, history: Sequence[CompletedWorkloadExperiment]
    ) -> Mapping[str, object]:
        return self.selection_details(history).selection_metadata()

    def lineage_for_observation(
        self,
        history: Sequence[CompletedWorkloadExperiment],
        record: CompletedWorkloadExperiment,
    ) -> InformationGainBeliefLineage:
        if type(record) is not CompletedWorkloadExperiment:
            raise TypeError("record must be an exact CompletedWorkloadExperiment.")
        details = self.selection_details(history)
        if record.candidate != details.candidate:
            raise InformationGainContractError(
                "Completed record does not match the information-gain selection."
            )
        self._validate_record(record)
        outcome_id = self.evidence_model.classify_observation(
            {self.evidence_model.observation_metric: record.observation.objective_value}
        )
        weights_after = update_information_gain_belief(
            self.evidence_model,
            details.current_belief_weights,
            candidate_id=record.candidate.candidate_id,
            outcome_id=outcome_id,
        )
        return InformationGainBeliefLineage(
            step_index=len(tuple(history)),
            candidate_id=record.candidate.candidate_id,
            outcome_id=outcome_id,
            weights_before=details.current_belief_weights,
            weights_after=weights_after,
            belief_fingerprint_before=details.current_belief_fingerprint,
            belief_fingerprint_after=information_gain_belief_fingerprint(
                self.evidence_model.hypothesis_ids,
                weights_after,
            ),
        )

    def _replay_history(
        self, history: Sequence[CompletedWorkloadExperiment]
    ) -> tuple[tuple[int, ...], frozenset[str]]:
        if type(history) not in (list, tuple):
            raise TypeError("history must be an ordered list or tuple.")
        weights = initial_information_gain_belief(self.evidence_model)
        completed: set[str] = set()
        for record in history:
            if type(record) is not CompletedWorkloadExperiment:
                raise TypeError("Every history item must be an exact CompletedWorkloadExperiment.")
            self._validate_record(record)
            candidate_id = record.candidate.candidate_id
            if candidate_id in completed:
                raise InformationGainContractError("History contains a repeated candidate.")
            outcome_id = self.evidence_model.classify_observation(
                {self.evidence_model.observation_metric: record.observation.objective_value}
            )
            weights = update_information_gain_belief(
                self.evidence_model,
                weights,
                candidate_id=candidate_id,
                outcome_id=outcome_id,
            )
            completed.add(candidate_id)
        return weights, frozenset(completed)

    def _validate_record(self, record: CompletedWorkloadExperiment) -> None:
        expected_candidate = self._candidate_by_id.get(record.candidate.candidate_id)
        if (
            record.run_spec_fingerprint != self._run_spec_fingerprint
            or record.policy_id != INFORMATION_GAIN_TABLE_POLICY_ID
            or record.candidate != expected_candidate
        ):
            raise InformationGainContractError(
                "Completed history record is inconsistent with the exact RunSpecV3."
            )


def initial_information_gain_belief(model: FiniteTableEvidenceModel) -> tuple[int, ...]:
    """Return exact prior weights in semantic hypothesis order."""

    if type(model) is not FiniteTableEvidenceModel:
        raise TypeError("model must be an exact FiniteTableEvidenceModel.")
    return tuple(model.prior_weight_by_hypothesis[item] for item in model.hypothesis_ids)


def update_information_gain_belief(
    model: FiniteTableEvidenceModel,
    weights: Sequence[int],
    *,
    candidate_id: str,
    outcome_id: str,
) -> tuple[int, ...]:
    """Apply one exact integer likelihood update and canonical GCD reduction."""

    if type(model) is not FiniteTableEvidenceModel:
        raise TypeError("model must be an exact FiniteTableEvidenceModel.")
    before = _belief_weights(weights, expected_count=len(model.hypothesis_ids))
    products: list[int] = []
    for hypothesis_id, old_weight in zip(model.hypothesis_ids, before, strict=True):
        likelihood = model.likelihood_weight(candidate_id, hypothesis_id, outcome_id)
        product = old_weight * likelihood
        _bounded_integer(
            product,
            label="intermediate belief weight",
            minimum=0,
            error_type=InvalidInformationGainBeliefError,
        )
        products.append(product)
    if not any(products):
        raise ImpossibleEvidenceError(
            "Observed outcome has zero probability under every current hypothesis."
        )
    divisor = reduce(gcd, products)
    if divisor <= 0:
        raise InvalidInformationGainBeliefError("Belief GCD must be positive.")
    return tuple(value // divisor for value in products)


def information_gain_belief_fingerprint(
    hypothesis_ids: Sequence[str], weights: Sequence[int]
) -> str:
    """Hash schema, semantic hypothesis order, and exact aligned weights."""

    hypotheses = _ordered_ids(
        hypothesis_ids,
        minimum_count=1,
        error_type=InvalidInformationGainBeliefError,
        label="hypothesis_ids",
    )
    normalized_weights = _belief_weights(weights, expected_count=len(hypotheses))
    payload = {
        "schema": INFORMATION_GAIN_BELIEF_SCHEMA,
        "hypothesis_ids": list(hypotheses),
        "weights": list(normalized_weights),
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def expected_information_gain_bits(
    model: FiniteTableEvidenceModel,
    weights: Sequence[int],
    candidate_id: str,
) -> Decimal:
    """Compute one candidate's quantized expected Shannon information gain."""

    if type(model) is not FiniteTableEvidenceModel:
        raise TypeError("model must be an exact FiniteTableEvidenceModel.")
    belief = _belief_weights(weights, expected_count=len(model.hypothesis_ids))
    if not any(belief):
        raise InvalidInformationGainBeliefError("Belief weights cannot all be zero.")
    # Resolve the candidate before entering numeric work and return a typed key error.
    if candidate_id not in model.likelihood_weight_by_candidate_id:
        raise LikelihoodCandidateKeyMismatchError("Unknown likelihood candidate ID.")

    try:
        with localcontext(_new_information_gain_decimal_context()):
            decimal_zero = Decimal(0)
            total_weight = Decimal(sum(belief))
            current = tuple(Decimal(weight) / total_weight for weight in belief)
            ln_two = Decimal(2).ln()
            current_entropy = _decimal_entropy(current, ln_two)
            expected_posterior_entropy = decimal_zero
            row_total = Decimal(model.likelihood_row_total)

            for outcome_id in model.outcome_ids:
                weighted = tuple(
                    probability
                    * (
                        Decimal(model.likelihood_weight(candidate_id, hypothesis_id, outcome_id))
                        / row_total
                    )
                    for hypothesis_id, probability in zip(
                        model.hypothesis_ids,
                        current,
                        strict=True,
                    )
                )
                predictive_probability = sum(weighted, decimal_zero)
                if predictive_probability == decimal_zero:
                    continue
                posterior = tuple(value / predictive_probability for value in weighted)
                expected_posterior_entropy += predictive_probability * _decimal_entropy(
                    posterior,
                    ln_two,
                )

            score = current_entropy - expected_posterior_entropy
            quantized = score.quantize(INFORMATION_GAIN_SCORE_QUANTUM)
            if quantized < decimal_zero:
                raise UnsupportedInformationGainNumericContractError(
                    "Quantized expected information gain is negative."
                )
            return quantized if quantized else decimal_zero.quantize(INFORMATION_GAIN_SCORE_QUANTUM)
    except UnsupportedInformationGainNumericContractError:
        raise
    except (DecimalException, OverflowError, ValueError) as exc:
        raise UnsupportedInformationGainNumericContractError(
            "The frozen Decimal information-gain calculation failed."
        ) from exc


def format_information_gain_bits(score: Decimal) -> str:
    """Serialize an exact quantized score with exactly thirty fractional places."""

    if type(score) is not Decimal or not score.is_finite() or score < 0:
        raise UnsupportedInformationGainNumericContractError(
            "Information-gain score must be a finite nonnegative Decimal."
        )
    try:
        with localcontext(_new_information_gain_decimal_context()):
            quantized = score.quantize(INFORMATION_GAIN_SCORE_QUANTUM)
    except DecimalException as exc:
        raise UnsupportedInformationGainNumericContractError(
            "Information-gain score cannot be quantized by the frozen contract."
        ) from exc
    if quantized == 0:
        quantized = Decimal("0E-30")
    return format(quantized, ".30f")


def _decimal_entropy(probabilities: tuple[Decimal, ...], ln_two: Decimal) -> Decimal:
    return -sum(
        (value * (value.ln() / ln_two) for value in probabilities if value != 0),
        Decimal(0),
    )


def _new_information_gain_decimal_context() -> Context:
    """Return a complete fresh context independent of ambient Decimal state."""

    return Context(
        prec=INFORMATION_GAIN_NUMERIC_CONTRACT.precision,
        rounding=ROUND_HALF_EVEN,
        Emin=_INFORMATION_GAIN_EMIN,
        Emax=_INFORMATION_GAIN_EMAX,
        capitals=1,
        clamp=0,
        flags=[],
        traps=[InvalidOperation, DivisionByZero, Overflow],
    )


def _ordered_ids(
    values: Sequence[str],
    *,
    minimum_count: int,
    error_type: type[InformationGainContractError],
    label: str,
) -> tuple[str, ...]:
    if type(values) not in (list, tuple):
        raise error_type(f"{label} must be an ordered list or tuple.")
    ordered = tuple(values)
    if len(ordered) < minimum_count:
        raise error_type(f"{label} has too few entries.")
    if any(type(item) is not str or not item for item in ordered):
        raise error_type(f"Every {label} entry must be a nonempty exact string.")
    if len(ordered) != len(set(ordered)):
        raise error_type(f"{label} entries must be unique.")
    return ordered


def _nonempty_exact_string(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise InformationGainContractError(f"{label} must be a nonempty exact string.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise InformationGainContractError(f"{label} must be valid UTF-8 text.") from exc
    return value


def _bounded_integer(
    value: object,
    *,
    label: str,
    minimum: int,
    error_type: type[InformationGainContractError],
) -> int:
    if type(value) is not int or value < minimum:
        raise error_type(f"{label} must be an exact integer at least {minimum}.")
    if value.bit_length() > MAX_INFORMATION_GAIN_INTEGER_BITS:
        raise error_type(
            f"{label} exceeds the documented {MAX_INFORMATION_GAIN_INTEGER_BITS}-bit safety bound."
        )
    return value


def _finite_real(value: object, *, label: str) -> int | float:
    if type(value) not in (int, float):
        raise InvalidThresholdError(f"{label} must be an exact finite real, not a boolean.")
    if type(value) is int:
        integer = value
        if integer.bit_length() > MAX_INFORMATION_GAIN_INTEGER_BITS:
            raise InvalidThresholdError(
                f"{label} exceeds the documented "
                f"{MAX_INFORMATION_GAIN_INTEGER_BITS}-bit safety bound."
            )
        return integer
    normalized = cast(float, value)
    if not math.isfinite(normalized):
        raise InvalidThresholdError(f"{label} must be finite.")
    return 0.0 if normalized == 0.0 else normalized


def _belief_weights(
    weights: Sequence[int], *, expected_count: int | None = None
) -> tuple[int, ...]:
    if type(weights) not in (list, tuple):
        raise InvalidInformationGainBeliefError("Belief weights must be an ordered list or tuple.")
    values = tuple(
        _bounded_integer(
            value,
            label=f"belief weight {index}",
            minimum=0,
            error_type=InvalidInformationGainBeliefError,
        )
        for index, value in enumerate(weights)
    )
    if not values or (expected_count is not None and len(values) != expected_count):
        raise InvalidInformationGainBeliefError("Belief weights do not match the hypotheses.")
    if not any(values):
        raise InvalidInformationGainBeliefError("Belief weights cannot all be zero.")
    return values


def _exact_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping.")
    result: dict[str, object] = {}
    for key, item in cast(Mapping[object, object], value).items():
        if type(key) is not str or not key:
            raise TypeError(f"{label} keys must be nonempty exact strings.")
        result[key] = item
    return result


def _exact_sequence(value: object, label: str) -> tuple[object, ...]:
    if type(value) not in (list, tuple):
        raise TypeError(f"{label} must be an ordered list or tuple.")
    return tuple(cast(Sequence[object], value))


def _canonical_json_bytes(payload: object) -> bytes:
    try:
        return (
            json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise EvidenceModelDecodeError("Content cannot be canonical UTF-8 JSON.") from exc


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key!r}.")
        result[key] = value
    return result


def _reject_nonfinite_json_constant(value: str) -> object:
    raise ValueError(f"Non-finite JSON constant is forbidden: {value}.")


def _required_fingerprint(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise InvalidInformationGainBeliefError(f"{label} must be a lowercase SHA-256 digest.")
    return value


assert TableInformationGainPolicy.name == INFORMATION_GAIN_TABLE_POLICY_ID
assert TableInformationGainPolicy.semantic_classification == INFORMATION_GAIN_TABLE_CLASSIFICATION
assert TableInformationGainPolicy.tie_break == RUNSPEC_CANDIDATE_ORDER
