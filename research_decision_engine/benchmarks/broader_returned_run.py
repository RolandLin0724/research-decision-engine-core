"""Pure foundational projections for a returned broader-replication run.

Decoders accept already parsed exact ``dict``/``list`` trees. A normal Python
dictionary cannot retain duplicate JSON object keys, so the earlier canonical
parser must reject them.
"""

from __future__ import annotations

import math
import statistics
import struct
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Final, Literal, Never, cast

from ..belief_models import (
    ADEQUACY_MINIMUM_RESIDUALS,
    CALIBRATED_SIGMA_MODEL_ID,
    CALIBRATED_SIGMA_MODEL_VERSION,
    FIXED_SIGMA_MODEL_ID,
    MINIMUM_PRIOR_EFFECTS,
    RESIDUAL_ALARM_COUNT,
    RESIDUAL_OUTLIER_THRESHOLD,
    RESIDUAL_WINDOW_SIZE,
    SIGMA_FLOOR,
    TAIL_ALARM_THRESHOLD,
    AdequacyState,
    BeliefModelLineage,
    EffectSourceKind,
    MatchedEffectObservation,
    ModelAdequacyDiagnostic,
    ModelBeliefState,
    ModelBeliefUpdate,
    PredictiveInterval,
    SigmaEstimate,
    SigmaEstimateStatus,
    belief_model,
)
from ..closed_loop import build_candidate_group_prediction_adapter
from ..decision import CandidateScore, DecisionTrace, HypothesisDecisionContext
from ..evidence_eligibility import (
    ControlValue as DomainControlValue,
)
from ..evidence_eligibility import (
    MatchedExperimentPair,
    PublicExperimentDesign,
)
from ..lookahead import (
    NO_EVIDENCE_BRANCH_ID,
    NO_EVIDENCE_BRANCH_LABEL,
    LookaheadAlternative,
    LookaheadBranch,
    LookaheadFirstActionPlan,
    LookaheadPlanTrace,
    LookaheadSecondAction,
)
from ..optimizer_effect import (
    ADAM_ADVANTAGE_ID,
    NO_ADVANTAGE_ID,
    SGD_ADVANTAGE_ID,
    evidence_from_matched_pair,
)
from ..reasoning import (
    PROBABILITY_TOLERANCE,
    BeliefState,
    BeliefUpdate,
    Evidence,
    HypothesisLikelihood,
    Provenance,
    ProvenanceValue,
    ReasoningError,
)
from ..types import Candidate, CompletedExperiment
from .broader_calibration_history import (
    CALIBRATION_ELIGIBILITY_BASIS,
    CALIBRATION_SELECTION_VERSION,
    expected_calibration_effect,
)
from .broader_calibration_selector_replay import (
    raw_effect_sha256,
    replay_calibration_history_selection,
)
from .broader_oracle import (
    CALIBRATION_NAMESPACE,
    OracleError,
    _parse_calibration_candidate,
    calibration_key,
    decision_key,
    transform_key,
)
from .broader_protocol import (
    PROTOCOL_VERSION,
    FrozenArm,
    ProtocolError,
    canonical_json_bytes,
    f64,
    protocol_hash,
    runtime_id,
)
from .broader_runner import (  # type: ignore[attr-defined]
    CALIBRATION_SIGMA_DDOF,
    CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
    CREATED_AT,
    GROUP_IDS,
    ArmAction,
    ArmDecision,
    BroaderArmRun,
    CalibrationDeployment,
    CalibrationGroupEstimate,
    RevealedObservation,
    _decide,
    _experiment_record_id,
    _fixed_policy_match,
    arm_spec,
    calibration_sigma_provenance_sha256,
    comparison_identity,
    initial_lineage_for,
    run_identity,
    terminal_reason_for,
    validate_lineage_binding,
)
from .broader_worlds import (
    BUDGETS,
    CANDIDATE_CATALOG,
    CANDIDATES_BY_ID,
    WORLDS_BY_ID,
    PublicFeasibilityState,
    candidate_costs,
    evidence_eligibility_contract,
    hidden_arm_mean,
    hidden_observation_sigma,
)

EXECUTION_RETURNED_SCIENTIFIC_RECORD_INVALID: Final = "EXECUTION_RETURNED_SCIENTIFIC_RECORD_INVALID"
type ValidationCategory = Literal[
    "structural_projection_invalid", "scientific_record_invalid", "missing_relation_context"
]


class ReturnedRunProjectionError(ValueError):
    """The module's sole deterministic local failure representation."""

    __slots__ = ("category", "failure_code", "path")

    def __init__(
        self,
        *,
        category: ValidationCategory,
        failure_code: str | None,
        path: str,
        detail: str,
    ) -> None:
        self.category, self.failure_code, self.path = category, failure_code, path
        super().__init__(f"{failure_code or category} at {path}: {detail}")


@dataclass(frozen=True, slots=True)
class ProvenanceValueProjection:
    """One exact mandatory ``kind``/``value`` provenance scalar."""

    kind: Literal["null", "bool", "i64", "f64", "string"]
    value: None | bool | int | str


@dataclass(frozen=True, slots=True)
class RunProvenanceProjection:
    details: tuple[tuple[str, ProvenanceValueProjection], ...]
    method: str
    version: str


@dataclass(frozen=True, slots=True)
class RunCandidateProjection:
    candidate_id: str
    learning_rate: str
    model_width: int
    optimizer: str
    regularization: str


@dataclass(frozen=True, slots=True)
class RunCompletedExperimentProjection:
    candidate: RunCandidateProjection
    created_at: str
    observed_value: str
    record_id: int


@dataclass(frozen=True, slots=True)
class RunEvidenceProjection:
    created_at: str
    evidence_id: str
    observed_comparison: str
    observed_outcome: str
    provenance: RunProvenanceProjection
    source_experiment_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RunBeliefStateProjection:
    belief_state_id: str
    created_at: str
    evidence_ids: tuple[str, ...]
    hypothesis_ids: tuple[str, ...]
    parent_belief_state_id: str | None
    posterior_probabilities: tuple[str, ...]
    prior_probabilities: tuple[str, ...]
    sequence: int


@dataclass(frozen=True, slots=True)
class RunHypothesisLikelihoodProjection:
    hypothesis_id: str
    likelihood: str
    posterior_probability: str
    prior_for_update: str
    unnormalized_weight: str


@dataclass(frozen=True, slots=True)
class RunBeliefUpdateProjection:
    belief_state_before: RunBeliefStateProjection
    created_at: str
    evidence: RunEvidenceProjection
    likelihoods: tuple[RunHypothesisLikelihoodProjection, ...]
    normalization_constant: str
    posterior_belief_state: RunBeliefStateProjection
    provenance: RunProvenanceProjection
    update_id: str
    update_rule_version: str


@dataclass(frozen=True, slots=True)
class RunMatchedEffectProjection:
    available_sequence: int
    comparison_group_id: str
    created_at: str
    effect_id: str
    observed_effect: str
    provenance: RunProvenanceProjection
    source_ids: tuple[str, ...]
    source_kind: EffectSourceKind


@dataclass(frozen=True, slots=True)
class RunSigmaEstimateProjection:
    belief_model_id: str
    belief_model_version: str
    comparison_group_id: str
    created_at: str
    current_evidence_excluded: bool
    cutoff_sequence: int
    estimated_sigma: str
    estimate_id: str
    estimator_version: str
    evidence_id: str
    lineage_id: str
    provenance: RunProvenanceProjection
    raw_sample_standard_deviation: str | None
    sample_count: int
    sample_mean: str | None
    sigma_floor: str
    source_effect_ids: tuple[str, ...]
    status: SigmaEstimateStatus
    variance_floor: str


@dataclass(frozen=True, slots=True)
class RunModelBeliefStateProjection:
    belief_model_id: str
    belief_model_version: str
    lineage_id: str
    state: RunBeliefStateProjection


@dataclass(frozen=True, slots=True)
class RunLineageProjection:
    belief_model_id: str
    belief_model_version: str
    created_at: str
    current_state: RunModelBeliefStateProjection
    lineage_id: str
    lineage_key: str


@dataclass(frozen=True, slots=True)
class RunPredictiveIntervalProjection:
    contains_observation: bool
    lower: str
    probability: str
    upper: str


@dataclass(frozen=True, slots=True)
class RunDiagnosticProjection:
    adequacy_state: AdequacyState
    belief_model_id: str
    belief_model_version: str
    belief_state_before_id: str
    central_intervals: tuple[RunPredictiveIntervalProjection, ...]
    comparison_group_id: str
    created_at: str
    diagnostic_id: str
    diagnostic_version: str
    diagnostics_disagree: bool
    evidence_id: str
    lineage_id: str
    per_hypothesis_residuals: tuple[tuple[str, str], ...]
    posterior_predictive_tail_probability: str
    predictive_cdf: str
    predictive_density: str
    predictive_log_likelihood: str
    predictive_mean: str
    predictive_variance: str
    provenance: RunProvenanceProjection
    repeated_residual_alarm: bool
    residual_count: int
    residual_outlier: bool
    rolling_residual_outlier_count: int
    sigma_estimate_id: str
    standardized_residual: str
    tail_alarm: bool


@dataclass(frozen=True, slots=True)
class RunModelUpdateProjection:
    bayesian_update: RunBeliefUpdateProjection
    belief_model_id: str
    belief_model_version: str
    created_at: str
    diagnostic: RunDiagnosticProjection
    evidence: RunEvidenceProjection
    lineage_id: str
    model_update_id: str
    posterior_state: RunModelBeliefStateProjection
    provenance: RunProvenanceProjection
    sigma_estimate: RunSigmaEstimateProjection
    state_before: RunModelBeliefStateProjection


@dataclass(frozen=True, slots=True)
class RunObservationAuthorizationProjection:
    candidate_id: str
    kind: Literal["calibration", "decision"]
    run_id: str
    source_id: str


@dataclass(frozen=True, slots=True)
class RunRevealedObservationProjection:
    authorization: RunObservationAuthorizationProjection
    authorization_id: str
    candidate_id: str
    comparison_group_id: str | None
    digest: str
    intervention_arm: str | None
    key_fields: tuple[str, ...]
    namespace: str
    oracle_key_id: str
    oracle_use_id: str
    outcome_digest: str
    replication_id: str
    revealed_observation: str
    seed: int
    serialized_key_hex: str
    u: str
    world_id: str
    z: str


@dataclass(frozen=True, slots=True)
class RunCalibrationEstimateProjection:
    belief_model_id: str
    calibration_prefix_id: str
    comparison_group_id: str
    ddof: int
    effects: tuple[RunMatchedEffectProjection, ...]
    estimated_sigma: str
    lineage_id: str
    observations: tuple[RunRevealedObservationProjection, ...]
    physical_cost: str
    provenance_sha256: str
    raw_sample_standard_deviation: str
    sample_count: int
    sample_mean: str
    sigma_estimate_id: str
    sigma_floor: str
    source_effect_ids: tuple[str, ...]
    source_sequence_cutoff: int


@dataclass(frozen=True, slots=True)
class RunCalibrationProjection:
    cost: str
    effects: tuple[RunMatchedEffectProjection, ...]
    estimates: tuple[RunCalibrationEstimateProjection, ...]
    observations: tuple[RunRevealedObservationProjection, ...]


@dataclass(frozen=True, slots=True)
class ControlValueProjection:
    """One exact controlled-variable scalar with an explicit branch tag."""

    kind: Literal["i64", "f64", "string"]
    value: int | str


@dataclass(frozen=True, slots=True)
class RunPublicExperimentDesignProjection:
    candidate_id: str
    comparison_group_id: str
    controlled_variables: tuple[tuple[str, ControlValueProjection], ...]
    experiment_family: str
    intervention_arm: str
    intervention_variable: str


@dataclass(frozen=True, slots=True)
class RunHypothesisDecisionContextProjection:
    hypothesis_id: str
    most_favorable_outcome: str
    most_favorable_outcome_label: str
    posterior_if_observed: str
    posterior_probability: str
    statement: str


@dataclass(frozen=True, slots=True)
class RunCandidateScoreProjection:
    candidate: RunCandidateProjection
    completes_matched_pair: bool
    estimated_cost: str
    expected_information_gain: str
    expected_posterior_entropy: str
    matched_experiment_id: int | None
    prior_entropy: str
    ranking_reason: str
    score_reason: str


@dataclass(frozen=True, slots=True)
class RunDecisionTraceProjection:
    belief_state_id: str
    created_at: str
    fallback_reason: str | None
    hypotheses: tuple[RunHypothesisDecisionContextProjection, ...]
    max_cost: str
    policy: str
    policy_version: str
    provenance: RunProvenanceProjection
    ranked_candidates: tuple[RunCandidateScoreProjection, ...]
    rationale: str
    selected: RunCandidateScoreProjection
    suggestion_id: str


type PublicActionEffect = Literal["opens_pair", "completes_pair", "ineligible", "stop"]
type NonStopPublicActionEffect = Literal["opens_pair", "completes_pair", "ineligible"]


@dataclass(frozen=True, slots=True)
class RunLookaheadSecondActionProjection:
    action_effect: PublicActionEffect
    candidate: RunCandidateProjection | None
    estimated_cost: str
    expected_information_gain: str
    information_gain_per_cost: str
    reason: str


@dataclass(frozen=True, slots=True)
class RunLookaheadBranchProjection:
    branch_id: str
    branch_total_cost: str
    budget_feasible: bool
    evidence_lower_bound: str | None
    evidence_upper_bound: str | None
    label: str
    posterior_entropy: str
    posterior_probabilities: tuple[tuple[str, str], ...]
    probability: str
    second_action: RunLookaheadSecondActionProjection
    terminal_entropy: str


@dataclass(frozen=True, slots=True)
class RunLookaheadFirstActionProjection:
    action_effect: NonStopPublicActionEffect
    branches: tuple[RunLookaheadBranchProjection, ...]
    candidate: RunCandidateProjection
    expected_terminal_entropy: str
    expected_total_cost: str
    expected_total_information_gain: str
    first_action_cost: str
    immediate_information_gain: str
    information_gain_per_expected_cost: str
    prior_entropy: str
    public_design: RunPublicExperimentDesignProjection
    ranking_reason: str


@dataclass(frozen=True, slots=True)
class RunLookaheadAlternativeProjection:
    action_effect: NonStopPublicActionEffect
    candidate: RunCandidateProjection
    comparison_group_id: str
    expected_total_cost: str
    expected_total_information_gain: str
    immediate_information_gain: str
    information_gain_per_expected_cost: str
    ranking_reason: str


@dataclass(frozen=True, slots=True)
class RunLookaheadTraceProjection:
    alternatives: tuple[RunLookaheadAlternativeProjection, ...]
    belief_state_id: str
    candidate_set_fingerprint: str
    completed_state_fingerprint: str
    created_at: str
    current_hypothesis_probabilities: tuple[tuple[str, str], ...]
    fallback_reason: str | None
    max_cost: str
    plan_id: str
    policy: str
    policy_version: str
    provenance: RunProvenanceProjection
    rationale: str
    selected: RunLookaheadFirstActionProjection
    tie_breaking_order: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RunPolicyTraceProjection:
    kind: Literal["decision_trace", "lookahead_plan_trace"]
    projection: RunDecisionTraceProjection | RunLookaheadTraceProjection


@dataclass(frozen=True, slots=True)
class RunArmDecisionProjection:
    affordable_candidate_ids: tuple[str, ...]
    belief_state_id: str
    decision_id: str
    fixed_policy_regression_match: bool
    policy_trace: RunPolicyTraceProjection
    public_feasible_candidate_ids: tuple[str, ...]
    remaining_budget: str
    selected_candidate_id: str
    step: int


@dataclass(frozen=True, slots=True)
class RunArmActionProjection:
    candidate_id: str
    cost: str
    cumulative_decision_cost: str
    decision_id: str
    new_evidence_ids: tuple[str, ...]
    observed_objective: str | None
    oracle_observation: RunRevealedObservationProjection | None
    posterior_probabilities: tuple[tuple[str, str], ...]
    role: str
    step: int


type RunArmValue = tuple[str, int, str, str]


@dataclass(frozen=True, slots=True)
class ReturnedRunProjection:
    actions: tuple[RunArmActionProjection, ...]
    arm: RunArmValue
    budget: str
    budget_id: str
    calibration: RunCalibrationProjection | None
    calibration_cost: str
    comparison_id: str
    completed_experiments: tuple[RunCompletedExperimentProjection, ...]
    decision_cost: str
    decisions: tuple[RunArmDecisionProjection, ...]
    diagnostics: tuple[RunDiagnosticProjection, ...]
    effect_history: tuple[RunMatchedEffectProjection, ...]
    evidence: tuple[RunEvidenceProjection, ...]
    initial_probabilities: tuple[tuple[str, str], ...]
    lineage: RunLineageProjection
    run_id: str
    run_status: Literal["complete", "invalid"]
    schema_version: Literal["broader-replication-returned-run/v1"]
    seed: int
    terminal_reason: str
    updates: tuple[RunModelUpdateProjection, ...]
    world_id: str


type FieldCheck = Callable[[object, str], object]
type FlatSchema = tuple[tuple[str, FieldCheck], ...]

_MISSING_CONTEXT: Final = object()


def _fail(category: ValidationCategory, path: str, detail: str) -> Never:
    code = (
        EXECUTION_RETURNED_SCIENTIFIC_RECORD_INVALID
        if category == "scientific_record_invalid"
        else None
    )
    raise ReturnedRunProjectionError(category=category, failure_code=code, path=path, detail=detail)


def _structural(path: str, detail: str) -> Never:
    _fail("structural_projection_invalid", path, detail)


def _scientific(path: str, detail: str) -> Never:
    _fail("scientific_record_invalid", path, detail)


def _missing_context(path: str) -> Never:
    _fail("missing_relation_context", path, "enclosing relation context is required")


def validate_returned_run_projection_shape(
    value: object,
    *,
    path: str = "returned_run",
    _defer_scientific_validation: bool = False,
) -> ReturnedRunProjection:
    """Require the complete exact runtime shape of one returned-run projection.

    The private defer mode preserves the established Stage-2D ordering: it
    validates exact runtime types while leaving scientific tags and enums to S1.
    Policy-trace coupling and the schema version remain structural in both modes.
    """

    def _tuple_value(raw: object, field_path: str) -> tuple[object, ...]:
        if type(raw) is not tuple:
            _structural(field_path, "expected an exact tuple")
        return raw

    def _string_value(raw: object, field_path: str) -> str:
        if type(raw) is not str:
            _structural(field_path, "expected an exact string")
        return raw

    def _integer_value(raw: object, field_path: str) -> int:
        if type(raw) is not int:
            _structural(field_path, "expected an exact integer")
        return raw

    def _boolean_value(raw: object, field_path: str) -> bool:
        if type(raw) is not bool:
            _structural(field_path, "expected an exact Boolean")
        return raw

    def _optional_string_value(raw: object, field_path: str) -> None:
        if raw is not None:
            _string_value(raw, field_path)

    def _optional_integer_value(raw: object, field_path: str) -> None:
        if raw is not None:
            _integer_value(raw, field_path)

    def _literal_value(
        raw: object,
        field_path: str,
        allowed: tuple[str, ...],
    ) -> str:
        text = _string_value(raw, field_path)
        if text not in allowed:
            _structural(field_path, "unknown literal value")
        return text

    def _scientific_literal_value(
        raw: object,
        field_path: str,
        allowed: tuple[str, ...],
    ) -> str:
        if _defer_scientific_validation:
            return _string_value(raw, field_path)
        return _literal_value(raw, field_path, allowed)

    def _string_sequence(raw: object, field_path: str) -> None:
        for index, item in enumerate(_tuple_value(raw, field_path)):
            _string_value(item, f"{field_path}[{index}]")

    def _integer_sequence(raw: object, field_path: str) -> None:
        for index, item in enumerate(_tuple_value(raw, field_path)):
            _integer_value(item, f"{field_path}[{index}]")

    def _string_pairs(raw: object, field_path: str) -> None:
        for index, item in enumerate(_tuple_value(raw, field_path)):
            row_path = f"{field_path}[{index}]"
            row = _tuple_value(item, row_path)
            if len(row) != 2:
                _structural(row_path, "expected an exact two-element tuple")
            _string_value(row[0], f"{row_path}[0]")
            _string_value(row[1], f"{row_path}[1]")

    def _provenance_value(
        raw: object,
        field_path: str,
    ) -> ProvenanceValueProjection:
        if type(raw) is not ProvenanceValueProjection:
            _structural(field_path, "expected exact ProvenanceValueProjection")
        kind = _string_value(raw.kind, f"{field_path}.kind")
        payload = raw.value
        if _defer_scientific_validation:
            if payload is None or type(payload) in {bool, int, str}:
                return raw
            _structural(
                f"{field_path}.value",
                "expected an exact provenance scalar",
            )
        if kind == "null":
            if payload is not None:
                _structural(f"{field_path}.value", "null kind requires None")
        elif kind == "bool":
            _boolean_value(payload, f"{field_path}.value")
        elif kind == "i64":
            _integer_value(payload, f"{field_path}.value")
        elif kind in {"f64", "string"}:
            _string_value(payload, f"{field_path}.value")
        else:
            _structural(f"{field_path}.kind", "unknown provenance-value kind")
        return raw

    def _provenance(raw: object, field_path: str) -> RunProvenanceProjection:
        if type(raw) is not RunProvenanceProjection:
            _structural(field_path, "expected exact RunProvenanceProjection")
        details_path = f"{field_path}.details"
        for index, item in enumerate(_tuple_value(raw.details, details_path)):
            row_path = f"{details_path}[{index}]"
            row = _tuple_value(item, row_path)
            if len(row) != 2:
                _structural(row_path, "expected an exact two-element tuple")
            _string_value(row[0], f"{row_path}[0]")
            _provenance_value(row[1], f"{row_path}[1]")
        _string_value(raw.method, f"{field_path}.method")
        _string_value(raw.version, f"{field_path}.version")
        return raw

    def _candidate(raw: object, field_path: str) -> RunCandidateProjection:
        if type(raw) is not RunCandidateProjection:
            _structural(field_path, "expected exact RunCandidateProjection")
        _string_value(raw.candidate_id, f"{field_path}.candidate_id")
        _string_value(raw.learning_rate, f"{field_path}.learning_rate")
        _integer_value(raw.model_width, f"{field_path}.model_width")
        _string_value(raw.optimizer, f"{field_path}.optimizer")
        _string_value(raw.regularization, f"{field_path}.regularization")
        return raw

    def _completed_experiment(
        raw: object,
        field_path: str,
    ) -> RunCompletedExperimentProjection:
        if type(raw) is not RunCompletedExperimentProjection:
            _structural(field_path, "expected exact RunCompletedExperimentProjection")
        _candidate(raw.candidate, f"{field_path}.candidate")
        _string_value(raw.created_at, f"{field_path}.created_at")
        _string_value(raw.observed_value, f"{field_path}.observed_value")
        _integer_value(raw.record_id, f"{field_path}.record_id")
        return raw

    def _evidence(raw: object, field_path: str) -> RunEvidenceProjection:
        if type(raw) is not RunEvidenceProjection:
            _structural(field_path, "expected exact RunEvidenceProjection")
        _string_value(raw.created_at, f"{field_path}.created_at")
        _string_value(raw.evidence_id, f"{field_path}.evidence_id")
        _string_value(raw.observed_comparison, f"{field_path}.observed_comparison")
        _string_value(raw.observed_outcome, f"{field_path}.observed_outcome")
        _provenance(raw.provenance, f"{field_path}.provenance")
        _integer_sequence(raw.source_experiment_ids, f"{field_path}.source_experiment_ids")
        return raw

    def _belief_state(raw: object, field_path: str) -> RunBeliefStateProjection:
        if type(raw) is not RunBeliefStateProjection:
            _structural(field_path, "expected exact RunBeliefStateProjection")
        _string_value(raw.belief_state_id, f"{field_path}.belief_state_id")
        _string_value(raw.created_at, f"{field_path}.created_at")
        _string_sequence(raw.evidence_ids, f"{field_path}.evidence_ids")
        _string_sequence(raw.hypothesis_ids, f"{field_path}.hypothesis_ids")
        _optional_string_value(
            raw.parent_belief_state_id,
            f"{field_path}.parent_belief_state_id",
        )
        _string_sequence(
            raw.posterior_probabilities,
            f"{field_path}.posterior_probabilities",
        )
        _string_sequence(raw.prior_probabilities, f"{field_path}.prior_probabilities")
        _integer_value(raw.sequence, f"{field_path}.sequence")
        return raw

    def _likelihood(
        raw: object,
        field_path: str,
    ) -> RunHypothesisLikelihoodProjection:
        if type(raw) is not RunHypothesisLikelihoodProjection:
            _structural(field_path, "expected exact RunHypothesisLikelihoodProjection")
        _string_value(raw.hypothesis_id, f"{field_path}.hypothesis_id")
        _string_value(raw.likelihood, f"{field_path}.likelihood")
        _string_value(raw.posterior_probability, f"{field_path}.posterior_probability")
        _string_value(raw.prior_for_update, f"{field_path}.prior_for_update")
        _string_value(raw.unnormalized_weight, f"{field_path}.unnormalized_weight")
        return raw

    def _belief_update(raw: object, field_path: str) -> RunBeliefUpdateProjection:
        if type(raw) is not RunBeliefUpdateProjection:
            _structural(field_path, "expected exact RunBeliefUpdateProjection")
        _belief_state(raw.belief_state_before, f"{field_path}.belief_state_before")
        _string_value(raw.created_at, f"{field_path}.created_at")
        _evidence(raw.evidence, f"{field_path}.evidence")
        likelihoods_path = f"{field_path}.likelihoods"
        for index, item in enumerate(_tuple_value(raw.likelihoods, likelihoods_path)):
            _likelihood(item, f"{likelihoods_path}[{index}]")
        _string_value(raw.normalization_constant, f"{field_path}.normalization_constant")
        _belief_state(
            raw.posterior_belief_state,
            f"{field_path}.posterior_belief_state",
        )
        _provenance(raw.provenance, f"{field_path}.provenance")
        _string_value(raw.update_id, f"{field_path}.update_id")
        _string_value(raw.update_rule_version, f"{field_path}.update_rule_version")
        return raw

    def _matched_effect(raw: object, field_path: str) -> RunMatchedEffectProjection:
        if type(raw) is not RunMatchedEffectProjection:
            _structural(field_path, "expected exact RunMatchedEffectProjection")
        _integer_value(raw.available_sequence, f"{field_path}.available_sequence")
        _string_value(raw.comparison_group_id, f"{field_path}.comparison_group_id")
        _string_value(raw.created_at, f"{field_path}.created_at")
        _string_value(raw.effect_id, f"{field_path}.effect_id")
        _string_value(raw.observed_effect, f"{field_path}.observed_effect")
        _provenance(raw.provenance, f"{field_path}.provenance")
        _string_sequence(raw.source_ids, f"{field_path}.source_ids")
        _scientific_literal_value(
            raw.source_kind,
            f"{field_path}.source_kind",
            ("calibration", "decision"),
        )
        return raw

    def _sigma_estimate(raw: object, field_path: str) -> RunSigmaEstimateProjection:
        if type(raw) is not RunSigmaEstimateProjection:
            _structural(field_path, "expected exact RunSigmaEstimateProjection")
        _string_value(raw.belief_model_id, f"{field_path}.belief_model_id")
        _string_value(raw.belief_model_version, f"{field_path}.belief_model_version")
        _string_value(raw.comparison_group_id, f"{field_path}.comparison_group_id")
        _string_value(raw.created_at, f"{field_path}.created_at")
        _boolean_value(
            raw.current_evidence_excluded,
            f"{field_path}.current_evidence_excluded",
        )
        _integer_value(raw.cutoff_sequence, f"{field_path}.cutoff_sequence")
        _string_value(raw.estimated_sigma, f"{field_path}.estimated_sigma")
        _string_value(raw.estimate_id, f"{field_path}.estimate_id")
        _string_value(raw.estimator_version, f"{field_path}.estimator_version")
        _string_value(raw.evidence_id, f"{field_path}.evidence_id")
        _string_value(raw.lineage_id, f"{field_path}.lineage_id")
        _provenance(raw.provenance, f"{field_path}.provenance")
        _optional_string_value(
            raw.raw_sample_standard_deviation,
            f"{field_path}.raw_sample_standard_deviation",
        )
        _integer_value(raw.sample_count, f"{field_path}.sample_count")
        _optional_string_value(raw.sample_mean, f"{field_path}.sample_mean")
        _string_value(raw.sigma_floor, f"{field_path}.sigma_floor")
        _string_sequence(raw.source_effect_ids, f"{field_path}.source_effect_ids")
        _scientific_literal_value(
            raw.status,
            f"{field_path}.status",
            ("fixed", "baseline_fallback", "calibrated"),
        )
        _string_value(raw.variance_floor, f"{field_path}.variance_floor")
        return raw

    def _model_belief_state(
        raw: object,
        field_path: str,
    ) -> RunModelBeliefStateProjection:
        if type(raw) is not RunModelBeliefStateProjection:
            _structural(field_path, "expected exact RunModelBeliefStateProjection")
        _string_value(raw.belief_model_id, f"{field_path}.belief_model_id")
        _string_value(raw.belief_model_version, f"{field_path}.belief_model_version")
        _string_value(raw.lineage_id, f"{field_path}.lineage_id")
        _belief_state(raw.state, f"{field_path}.state")
        return raw

    def _lineage(raw: object, field_path: str) -> RunLineageProjection:
        if type(raw) is not RunLineageProjection:
            _structural(field_path, "expected exact RunLineageProjection")
        _string_value(raw.belief_model_id, f"{field_path}.belief_model_id")
        _string_value(raw.belief_model_version, f"{field_path}.belief_model_version")
        _string_value(raw.created_at, f"{field_path}.created_at")
        _model_belief_state(raw.current_state, f"{field_path}.current_state")
        _string_value(raw.lineage_id, f"{field_path}.lineage_id")
        _string_value(raw.lineage_key, f"{field_path}.lineage_key")
        return raw

    def _predictive_interval(
        raw: object,
        field_path: str,
    ) -> RunPredictiveIntervalProjection:
        if type(raw) is not RunPredictiveIntervalProjection:
            _structural(field_path, "expected exact RunPredictiveIntervalProjection")
        _boolean_value(raw.contains_observation, f"{field_path}.contains_observation")
        _string_value(raw.lower, f"{field_path}.lower")
        _string_value(raw.probability, f"{field_path}.probability")
        _string_value(raw.upper, f"{field_path}.upper")
        return raw

    def _diagnostic(raw: object, field_path: str) -> RunDiagnosticProjection:
        if type(raw) is not RunDiagnosticProjection:
            _structural(field_path, "expected exact RunDiagnosticProjection")
        _scientific_literal_value(
            raw.adequacy_state,
            f"{field_path}.adequacy_state",
            ("adequate", "uncertain", "appears_misspecified"),
        )
        _string_value(raw.belief_model_id, f"{field_path}.belief_model_id")
        _string_value(raw.belief_model_version, f"{field_path}.belief_model_version")
        _string_value(raw.belief_state_before_id, f"{field_path}.belief_state_before_id")
        intervals_path = f"{field_path}.central_intervals"
        for index, item in enumerate(_tuple_value(raw.central_intervals, intervals_path)):
            _predictive_interval(item, f"{intervals_path}[{index}]")
        _string_value(raw.comparison_group_id, f"{field_path}.comparison_group_id")
        _string_value(raw.created_at, f"{field_path}.created_at")
        _string_value(raw.diagnostic_id, f"{field_path}.diagnostic_id")
        _string_value(raw.diagnostic_version, f"{field_path}.diagnostic_version")
        _boolean_value(raw.diagnostics_disagree, f"{field_path}.diagnostics_disagree")
        _string_value(raw.evidence_id, f"{field_path}.evidence_id")
        _string_value(raw.lineage_id, f"{field_path}.lineage_id")
        _string_pairs(
            raw.per_hypothesis_residuals,
            f"{field_path}.per_hypothesis_residuals",
        )
        _string_value(
            raw.posterior_predictive_tail_probability,
            f"{field_path}.posterior_predictive_tail_probability",
        )
        _string_value(raw.predictive_cdf, f"{field_path}.predictive_cdf")
        _string_value(raw.predictive_density, f"{field_path}.predictive_density")
        _string_value(
            raw.predictive_log_likelihood,
            f"{field_path}.predictive_log_likelihood",
        )
        _string_value(raw.predictive_mean, f"{field_path}.predictive_mean")
        _string_value(raw.predictive_variance, f"{field_path}.predictive_variance")
        _provenance(raw.provenance, f"{field_path}.provenance")
        _boolean_value(
            raw.repeated_residual_alarm,
            f"{field_path}.repeated_residual_alarm",
        )
        _integer_value(raw.residual_count, f"{field_path}.residual_count")
        _boolean_value(raw.residual_outlier, f"{field_path}.residual_outlier")
        _integer_value(
            raw.rolling_residual_outlier_count,
            f"{field_path}.rolling_residual_outlier_count",
        )
        _string_value(raw.sigma_estimate_id, f"{field_path}.sigma_estimate_id")
        _string_value(raw.standardized_residual, f"{field_path}.standardized_residual")
        _boolean_value(raw.tail_alarm, f"{field_path}.tail_alarm")
        return raw

    def _model_update(raw: object, field_path: str) -> RunModelUpdateProjection:
        if type(raw) is not RunModelUpdateProjection:
            _structural(field_path, "expected exact RunModelUpdateProjection")
        _belief_update(raw.bayesian_update, f"{field_path}.bayesian_update")
        _string_value(raw.belief_model_id, f"{field_path}.belief_model_id")
        _string_value(raw.belief_model_version, f"{field_path}.belief_model_version")
        _string_value(raw.created_at, f"{field_path}.created_at")
        _diagnostic(raw.diagnostic, f"{field_path}.diagnostic")
        _evidence(raw.evidence, f"{field_path}.evidence")
        _string_value(raw.lineage_id, f"{field_path}.lineage_id")
        _string_value(raw.model_update_id, f"{field_path}.model_update_id")
        _model_belief_state(raw.posterior_state, f"{field_path}.posterior_state")
        _provenance(raw.provenance, f"{field_path}.provenance")
        _sigma_estimate(raw.sigma_estimate, f"{field_path}.sigma_estimate")
        _model_belief_state(raw.state_before, f"{field_path}.state_before")
        return raw

    def _observation_authorization(
        raw: object,
        field_path: str,
    ) -> RunObservationAuthorizationProjection:
        if type(raw) is not RunObservationAuthorizationProjection:
            _structural(
                field_path,
                "expected exact RunObservationAuthorizationProjection",
            )
        _string_value(raw.candidate_id, f"{field_path}.candidate_id")
        _scientific_literal_value(
            raw.kind,
            f"{field_path}.kind",
            ("calibration", "decision"),
        )
        _string_value(raw.run_id, f"{field_path}.run_id")
        _string_value(raw.source_id, f"{field_path}.source_id")
        return raw

    def _revealed_observation(
        raw: object,
        field_path: str,
    ) -> RunRevealedObservationProjection:
        if type(raw) is not RunRevealedObservationProjection:
            _structural(field_path, "expected exact RunRevealedObservationProjection")
        _observation_authorization(raw.authorization, f"{field_path}.authorization")
        _string_value(raw.authorization_id, f"{field_path}.authorization_id")
        _string_value(raw.candidate_id, f"{field_path}.candidate_id")
        _optional_string_value(
            raw.comparison_group_id,
            f"{field_path}.comparison_group_id",
        )
        _string_value(raw.digest, f"{field_path}.digest")
        _optional_string_value(raw.intervention_arm, f"{field_path}.intervention_arm")
        _string_sequence(raw.key_fields, f"{field_path}.key_fields")
        _string_value(raw.namespace, f"{field_path}.namespace")
        _string_value(raw.oracle_key_id, f"{field_path}.oracle_key_id")
        _string_value(raw.oracle_use_id, f"{field_path}.oracle_use_id")
        _string_value(raw.outcome_digest, f"{field_path}.outcome_digest")
        _string_value(raw.replication_id, f"{field_path}.replication_id")
        _string_value(raw.revealed_observation, f"{field_path}.revealed_observation")
        _integer_value(raw.seed, f"{field_path}.seed")
        _string_value(raw.serialized_key_hex, f"{field_path}.serialized_key_hex")
        _string_value(raw.u, f"{field_path}.u")
        _string_value(raw.world_id, f"{field_path}.world_id")
        _string_value(raw.z, f"{field_path}.z")
        return raw

    def _calibration_estimate(
        raw: object,
        field_path: str,
    ) -> RunCalibrationEstimateProjection:
        if type(raw) is not RunCalibrationEstimateProjection:
            _structural(field_path, "expected exact RunCalibrationEstimateProjection")
        _string_value(raw.belief_model_id, f"{field_path}.belief_model_id")
        _string_value(raw.calibration_prefix_id, f"{field_path}.calibration_prefix_id")
        _string_value(raw.comparison_group_id, f"{field_path}.comparison_group_id")
        _integer_value(raw.ddof, f"{field_path}.ddof")
        effects_path = f"{field_path}.effects"
        for index, item in enumerate(_tuple_value(raw.effects, effects_path)):
            _matched_effect(item, f"{effects_path}[{index}]")
        _string_value(raw.estimated_sigma, f"{field_path}.estimated_sigma")
        _string_value(raw.lineage_id, f"{field_path}.lineage_id")
        observations_path = f"{field_path}.observations"
        for index, item in enumerate(_tuple_value(raw.observations, observations_path)):
            _revealed_observation(item, f"{observations_path}[{index}]")
        _string_value(raw.physical_cost, f"{field_path}.physical_cost")
        _string_value(raw.provenance_sha256, f"{field_path}.provenance_sha256")
        _string_value(
            raw.raw_sample_standard_deviation,
            f"{field_path}.raw_sample_standard_deviation",
        )
        _integer_value(raw.sample_count, f"{field_path}.sample_count")
        _string_value(raw.sample_mean, f"{field_path}.sample_mean")
        _string_value(raw.sigma_estimate_id, f"{field_path}.sigma_estimate_id")
        _string_value(raw.sigma_floor, f"{field_path}.sigma_floor")
        _string_sequence(raw.source_effect_ids, f"{field_path}.source_effect_ids")
        _integer_value(
            raw.source_sequence_cutoff,
            f"{field_path}.source_sequence_cutoff",
        )
        return raw

    def _calibration(raw: object, field_path: str) -> RunCalibrationProjection:
        if type(raw) is not RunCalibrationProjection:
            _structural(field_path, "expected exact RunCalibrationProjection")
        _string_value(raw.cost, f"{field_path}.cost")
        effects_path = f"{field_path}.effects"
        for index, item in enumerate(_tuple_value(raw.effects, effects_path)):
            _matched_effect(item, f"{effects_path}[{index}]")
        estimates_path = f"{field_path}.estimates"
        for index, item in enumerate(_tuple_value(raw.estimates, estimates_path)):
            _calibration_estimate(item, f"{estimates_path}[{index}]")
        observations_path = f"{field_path}.observations"
        for index, item in enumerate(_tuple_value(raw.observations, observations_path)):
            _revealed_observation(item, f"{observations_path}[{index}]")
        return raw

    def _control_value(raw: object, field_path: str) -> ControlValueProjection:
        if type(raw) is not ControlValueProjection:
            _structural(field_path, "expected exact ControlValueProjection")
        kind = _string_value(raw.kind, f"{field_path}.kind")
        if _defer_scientific_validation:
            if type(raw.value) is int or type(raw.value) is str:
                return raw
            _structural(
                f"{field_path}.value",
                "expected an exact control scalar",
            )
        if kind == "i64":
            _integer_value(raw.value, f"{field_path}.value")
        elif kind in {"f64", "string"}:
            _string_value(raw.value, f"{field_path}.value")
        else:
            _structural(f"{field_path}.kind", "unknown control-value kind")
        return raw

    def _public_design(
        raw: object,
        field_path: str,
    ) -> RunPublicExperimentDesignProjection:
        if type(raw) is not RunPublicExperimentDesignProjection:
            _structural(
                field_path,
                "expected exact RunPublicExperimentDesignProjection",
            )
        _string_value(raw.candidate_id, f"{field_path}.candidate_id")
        _string_value(raw.comparison_group_id, f"{field_path}.comparison_group_id")
        controls_path = f"{field_path}.controlled_variables"
        for index, item in enumerate(_tuple_value(raw.controlled_variables, controls_path)):
            row_path = f"{controls_path}[{index}]"
            row = _tuple_value(item, row_path)
            if len(row) != 2:
                _structural(row_path, "expected an exact two-element tuple")
            _string_value(row[0], f"{row_path}[0]")
            _control_value(row[1], f"{row_path}[1]")
        _string_value(raw.experiment_family, f"{field_path}.experiment_family")
        _string_value(raw.intervention_arm, f"{field_path}.intervention_arm")
        _string_value(raw.intervention_variable, f"{field_path}.intervention_variable")
        return raw

    def _hypothesis_context(
        raw: object,
        field_path: str,
    ) -> RunHypothesisDecisionContextProjection:
        if type(raw) is not RunHypothesisDecisionContextProjection:
            _structural(
                field_path,
                "expected exact RunHypothesisDecisionContextProjection",
            )
        _string_value(raw.hypothesis_id, f"{field_path}.hypothesis_id")
        _string_value(
            raw.most_favorable_outcome,
            f"{field_path}.most_favorable_outcome",
        )
        _string_value(
            raw.most_favorable_outcome_label,
            f"{field_path}.most_favorable_outcome_label",
        )
        _string_value(raw.posterior_if_observed, f"{field_path}.posterior_if_observed")
        _string_value(raw.posterior_probability, f"{field_path}.posterior_probability")
        _string_value(raw.statement, f"{field_path}.statement")
        return raw

    def _candidate_score(raw: object, field_path: str) -> RunCandidateScoreProjection:
        if type(raw) is not RunCandidateScoreProjection:
            _structural(field_path, "expected exact RunCandidateScoreProjection")
        _candidate(raw.candidate, f"{field_path}.candidate")
        _boolean_value(
            raw.completes_matched_pair,
            f"{field_path}.completes_matched_pair",
        )
        _string_value(raw.estimated_cost, f"{field_path}.estimated_cost")
        _string_value(
            raw.expected_information_gain,
            f"{field_path}.expected_information_gain",
        )
        _string_value(
            raw.expected_posterior_entropy,
            f"{field_path}.expected_posterior_entropy",
        )
        _optional_integer_value(
            raw.matched_experiment_id,
            f"{field_path}.matched_experiment_id",
        )
        _string_value(raw.prior_entropy, f"{field_path}.prior_entropy")
        _string_value(raw.ranking_reason, f"{field_path}.ranking_reason")
        _string_value(raw.score_reason, f"{field_path}.score_reason")
        return raw

    def _decision_trace(raw: object, field_path: str) -> RunDecisionTraceProjection:
        if type(raw) is not RunDecisionTraceProjection:
            _structural(field_path, "expected exact RunDecisionTraceProjection")
        _string_value(raw.belief_state_id, f"{field_path}.belief_state_id")
        _string_value(raw.created_at, f"{field_path}.created_at")
        _optional_string_value(raw.fallback_reason, f"{field_path}.fallback_reason")
        hypotheses_path = f"{field_path}.hypotheses"
        for index, item in enumerate(_tuple_value(raw.hypotheses, hypotheses_path)):
            _hypothesis_context(item, f"{hypotheses_path}[{index}]")
        _string_value(raw.max_cost, f"{field_path}.max_cost")
        _string_value(raw.policy, f"{field_path}.policy")
        _string_value(raw.policy_version, f"{field_path}.policy_version")
        _provenance(raw.provenance, f"{field_path}.provenance")
        ranked_path = f"{field_path}.ranked_candidates"
        for index, item in enumerate(_tuple_value(raw.ranked_candidates, ranked_path)):
            _candidate_score(item, f"{ranked_path}[{index}]")
        _string_value(raw.rationale, f"{field_path}.rationale")
        _candidate_score(raw.selected, f"{field_path}.selected")
        _string_value(raw.suggestion_id, f"{field_path}.suggestion_id")
        return raw

    def _second_action(
        raw: object,
        field_path: str,
    ) -> RunLookaheadSecondActionProjection:
        if type(raw) is not RunLookaheadSecondActionProjection:
            _structural(
                field_path,
                "expected exact RunLookaheadSecondActionProjection",
            )
        effect = _scientific_literal_value(
            raw.action_effect,
            f"{field_path}.action_effect",
            ("opens_pair", "completes_pair", "ineligible", "stop"),
        )
        if _defer_scientific_validation:
            if raw.candidate is not None:
                _candidate(raw.candidate, f"{field_path}.candidate")
        elif effect == "stop":
            if raw.candidate is not None:
                _structural(
                    f"{field_path}.candidate",
                    "stop action requires a None candidate",
                )
        else:
            _candidate(raw.candidate, f"{field_path}.candidate")
        _string_value(raw.estimated_cost, f"{field_path}.estimated_cost")
        _string_value(
            raw.expected_information_gain,
            f"{field_path}.expected_information_gain",
        )
        _string_value(
            raw.information_gain_per_cost,
            f"{field_path}.information_gain_per_cost",
        )
        _string_value(raw.reason, f"{field_path}.reason")
        return raw

    def _branch(raw: object, field_path: str) -> RunLookaheadBranchProjection:
        if type(raw) is not RunLookaheadBranchProjection:
            _structural(field_path, "expected exact RunLookaheadBranchProjection")
        _string_value(raw.branch_id, f"{field_path}.branch_id")
        _string_value(raw.branch_total_cost, f"{field_path}.branch_total_cost")
        _boolean_value(raw.budget_feasible, f"{field_path}.budget_feasible")
        _optional_string_value(
            raw.evidence_lower_bound,
            f"{field_path}.evidence_lower_bound",
        )
        _optional_string_value(
            raw.evidence_upper_bound,
            f"{field_path}.evidence_upper_bound",
        )
        _string_value(raw.label, f"{field_path}.label")
        _string_value(raw.posterior_entropy, f"{field_path}.posterior_entropy")
        _string_pairs(
            raw.posterior_probabilities,
            f"{field_path}.posterior_probabilities",
        )
        _string_value(raw.probability, f"{field_path}.probability")
        _second_action(raw.second_action, f"{field_path}.second_action")
        _string_value(raw.terminal_entropy, f"{field_path}.terminal_entropy")
        return raw

    def _first_action(
        raw: object,
        field_path: str,
    ) -> RunLookaheadFirstActionProjection:
        if type(raw) is not RunLookaheadFirstActionProjection:
            _structural(
                field_path,
                "expected exact RunLookaheadFirstActionProjection",
            )
        _scientific_literal_value(
            raw.action_effect,
            f"{field_path}.action_effect",
            ("opens_pair", "completes_pair", "ineligible"),
        )
        branches_path = f"{field_path}.branches"
        for index, item in enumerate(_tuple_value(raw.branches, branches_path)):
            _branch(item, f"{branches_path}[{index}]")
        _candidate(raw.candidate, f"{field_path}.candidate")
        _string_value(
            raw.expected_terminal_entropy,
            f"{field_path}.expected_terminal_entropy",
        )
        _string_value(raw.expected_total_cost, f"{field_path}.expected_total_cost")
        _string_value(
            raw.expected_total_information_gain,
            f"{field_path}.expected_total_information_gain",
        )
        _string_value(raw.first_action_cost, f"{field_path}.first_action_cost")
        _string_value(
            raw.immediate_information_gain,
            f"{field_path}.immediate_information_gain",
        )
        _string_value(
            raw.information_gain_per_expected_cost,
            f"{field_path}.information_gain_per_expected_cost",
        )
        _string_value(raw.prior_entropy, f"{field_path}.prior_entropy")
        _public_design(raw.public_design, f"{field_path}.public_design")
        _string_value(raw.ranking_reason, f"{field_path}.ranking_reason")
        return raw

    def _alternative(
        raw: object,
        field_path: str,
    ) -> RunLookaheadAlternativeProjection:
        if type(raw) is not RunLookaheadAlternativeProjection:
            _structural(
                field_path,
                "expected exact RunLookaheadAlternativeProjection",
            )
        _scientific_literal_value(
            raw.action_effect,
            f"{field_path}.action_effect",
            ("opens_pair", "completes_pair", "ineligible"),
        )
        _candidate(raw.candidate, f"{field_path}.candidate")
        _string_value(raw.comparison_group_id, f"{field_path}.comparison_group_id")
        _string_value(raw.expected_total_cost, f"{field_path}.expected_total_cost")
        _string_value(
            raw.expected_total_information_gain,
            f"{field_path}.expected_total_information_gain",
        )
        _string_value(
            raw.immediate_information_gain,
            f"{field_path}.immediate_information_gain",
        )
        _string_value(
            raw.information_gain_per_expected_cost,
            f"{field_path}.information_gain_per_expected_cost",
        )
        _string_value(raw.ranking_reason, f"{field_path}.ranking_reason")
        return raw

    def _lookahead_trace(
        raw: object,
        field_path: str,
    ) -> RunLookaheadTraceProjection:
        if type(raw) is not RunLookaheadTraceProjection:
            _structural(field_path, "expected exact RunLookaheadTraceProjection")
        alternatives_path = f"{field_path}.alternatives"
        for index, item in enumerate(_tuple_value(raw.alternatives, alternatives_path)):
            _alternative(item, f"{alternatives_path}[{index}]")
        _string_value(raw.belief_state_id, f"{field_path}.belief_state_id")
        _string_value(
            raw.candidate_set_fingerprint,
            f"{field_path}.candidate_set_fingerprint",
        )
        _string_value(
            raw.completed_state_fingerprint,
            f"{field_path}.completed_state_fingerprint",
        )
        _string_value(raw.created_at, f"{field_path}.created_at")
        _string_pairs(
            raw.current_hypothesis_probabilities,
            f"{field_path}.current_hypothesis_probabilities",
        )
        _optional_string_value(raw.fallback_reason, f"{field_path}.fallback_reason")
        _string_value(raw.max_cost, f"{field_path}.max_cost")
        _string_value(raw.plan_id, f"{field_path}.plan_id")
        _string_value(raw.policy, f"{field_path}.policy")
        _string_value(raw.policy_version, f"{field_path}.policy_version")
        _provenance(raw.provenance, f"{field_path}.provenance")
        _string_value(raw.rationale, f"{field_path}.rationale")
        _first_action(raw.selected, f"{field_path}.selected")
        _string_sequence(raw.tie_breaking_order, f"{field_path}.tie_breaking_order")
        return raw

    def _policy_trace(raw: object, field_path: str) -> RunPolicyTraceProjection:
        if type(raw) is not RunPolicyTraceProjection:
            _structural(field_path, "expected exact RunPolicyTraceProjection")
        tag_path = "policy_trace" if _defer_scientific_validation else field_path
        kind = _literal_value(
            raw.kind,
            f"{tag_path}.kind",
            ("decision_trace", "lookahead_plan_trace"),
        )
        if kind == "decision_trace":
            if type(raw.projection) is not RunDecisionTraceProjection:
                _structural(
                    f"{tag_path}.projection",
                    "tag and projection type do not match",
                )
            _decision_trace(raw.projection, f"{field_path}.projection")
        else:
            if type(raw.projection) is not RunLookaheadTraceProjection:
                _structural(
                    f"{tag_path}.projection",
                    "tag and projection type do not match",
                )
            _lookahead_trace(raw.projection, f"{field_path}.projection")
        return raw

    def _arm_decision(raw: object, field_path: str) -> RunArmDecisionProjection:
        if type(raw) is not RunArmDecisionProjection:
            _structural(field_path, "expected exact RunArmDecisionProjection")
        _string_sequence(
            raw.affordable_candidate_ids,
            f"{field_path}.affordable_candidate_ids",
        )
        _string_value(raw.belief_state_id, f"{field_path}.belief_state_id")
        _string_value(raw.decision_id, f"{field_path}.decision_id")
        _boolean_value(
            raw.fixed_policy_regression_match,
            f"{field_path}.fixed_policy_regression_match",
        )
        _policy_trace(raw.policy_trace, f"{field_path}.policy_trace")
        _string_sequence(
            raw.public_feasible_candidate_ids,
            f"{field_path}.public_feasible_candidate_ids",
        )
        _string_value(raw.remaining_budget, f"{field_path}.remaining_budget")
        _string_value(raw.selected_candidate_id, f"{field_path}.selected_candidate_id")
        _integer_value(raw.step, f"{field_path}.step")
        return raw

    def _arm_action(raw: object, field_path: str) -> RunArmActionProjection:
        if type(raw) is not RunArmActionProjection:
            _structural(field_path, "expected exact RunArmActionProjection")
        _string_value(raw.candidate_id, f"{field_path}.candidate_id")
        _string_value(raw.cost, f"{field_path}.cost")
        _string_value(
            raw.cumulative_decision_cost,
            f"{field_path}.cumulative_decision_cost",
        )
        _string_value(raw.decision_id, f"{field_path}.decision_id")
        _string_sequence(raw.new_evidence_ids, f"{field_path}.new_evidence_ids")
        _optional_string_value(
            raw.observed_objective,
            f"{field_path}.observed_objective",
        )
        if raw.oracle_observation is not None:
            _revealed_observation(
                raw.oracle_observation,
                f"{field_path}.oracle_observation",
            )
        _string_pairs(
            raw.posterior_probabilities,
            f"{field_path}.posterior_probabilities",
        )
        _string_value(raw.role, f"{field_path}.role")
        _integer_value(raw.step, f"{field_path}.step")
        return raw

    def _returned_run(raw: object, field_path: str) -> ReturnedRunProjection:
        if type(raw) is not ReturnedRunProjection:
            _structural(field_path, "expected exact ReturnedRunProjection")
        actions_path = f"{field_path}.actions"
        for index, item in enumerate(_tuple_value(raw.actions, actions_path)):
            _arm_action(item, f"{actions_path}[{index}]")
        arm_path = f"{field_path}.arm"
        arm = _tuple_value(raw.arm, arm_path)
        if len(arm) != 4:
            _structural(arm_path, "expected an exact four-element tuple")
        _string_value(arm[0], f"{arm_path}[0]")
        _integer_value(arm[1], f"{arm_path}[1]")
        _string_value(arm[2], f"{arm_path}[2]")
        _string_value(arm[3], f"{arm_path}[3]")
        _string_value(raw.budget, f"{field_path}.budget")
        _string_value(raw.budget_id, f"{field_path}.budget_id")
        if raw.calibration is not None:
            _calibration(raw.calibration, f"{field_path}.calibration")
        _string_value(raw.calibration_cost, f"{field_path}.calibration_cost")
        _string_value(raw.comparison_id, f"{field_path}.comparison_id")
        experiments_path = f"{field_path}.completed_experiments"
        for index, item in enumerate(_tuple_value(raw.completed_experiments, experiments_path)):
            _completed_experiment(item, f"{experiments_path}[{index}]")
        _string_value(raw.decision_cost, f"{field_path}.decision_cost")
        decisions_path = f"{field_path}.decisions"
        for index, item in enumerate(_tuple_value(raw.decisions, decisions_path)):
            _arm_decision(item, f"{decisions_path}[{index}]")
        diagnostics_path = f"{field_path}.diagnostics"
        for index, item in enumerate(_tuple_value(raw.diagnostics, diagnostics_path)):
            _diagnostic(item, f"{diagnostics_path}[{index}]")
        effects_path = f"{field_path}.effect_history"
        for index, item in enumerate(_tuple_value(raw.effect_history, effects_path)):
            _matched_effect(item, f"{effects_path}[{index}]")
        evidence_path = f"{field_path}.evidence"
        for index, item in enumerate(_tuple_value(raw.evidence, evidence_path)):
            _evidence(item, f"{evidence_path}[{index}]")
        _string_pairs(
            raw.initial_probabilities,
            f"{field_path}.initial_probabilities",
        )
        _lineage(raw.lineage, f"{field_path}.lineage")
        _string_value(raw.run_id, f"{field_path}.run_id")
        _scientific_literal_value(
            raw.run_status,
            f"{field_path}.run_status",
            ("complete", "invalid"),
        )
        _literal_value(
            raw.schema_version,
            f"{field_path}.schema_version",
            ("broader-replication-returned-run/v1",),
        )
        _integer_value(raw.seed, f"{field_path}.seed")
        _string_value(raw.terminal_reason, f"{field_path}.terminal_reason")
        updates_path = f"{field_path}.updates"
        for index, item in enumerate(_tuple_value(raw.updates, updates_path)):
            _model_update(item, f"{updates_path}[{index}]")
        _string_value(raw.world_id, f"{field_path}.world_id")
        return raw

    return _returned_run(value, path)


def _projection_list(value: object) -> object:
    if type(value) is tuple:
        return list(value)
    # A projection-side list is invalid; this marker makes the ordered decoder reject it.
    return None if type(value) is list else value


def _projection_child[T](
    value: object, expected: type[T], mapping: Callable[[T], dict[str, object]]
) -> object:
    return mapping(value) if type(value) is expected else None


def _provenance_value_mapping(value: ProvenanceValueProjection) -> dict[str, object]:
    return {"kind": value.kind, "value": value.value}


def _provenance_mapping(value: RunProvenanceProjection) -> dict[str, object]:
    details: object = value.details
    if type(details) is tuple:
        encoded: list[object] = []
        for pair in details:
            if type(pair) is tuple and len(pair) == 2:
                item = _projection_child(
                    pair[1], ProvenanceValueProjection, _provenance_value_mapping
                )
                encoded.append([pair[0], item])
            else:
                encoded.append(None if type(pair) is list else pair)
        details = encoded
    elif type(details) is list:
        details = None
    return {"details": details, "method": value.method, "version": value.version}


def _candidate_mapping(value: RunCandidateProjection) -> dict[str, object]:
    head = value.candidate_id, value.learning_rate, value.model_width
    return _flat_record(_CANDIDATE_SCHEMA, *head, value.optimizer, value.regularization)


def _experiment_mapping(value: RunCompletedExperimentProjection) -> dict[str, object]:
    candidate = _projection_child(value.candidate, RunCandidateProjection, _candidate_mapping)
    return _flat_record(
        _EXPERIMENT_SCHEMA, candidate, value.created_at, value.observed_value, value.record_id
    )


def _evidence_mapping(value: RunEvidenceProjection) -> dict[str, object]:
    provenance = _projection_child(value.provenance, RunProvenanceProjection, _provenance_mapping)
    head = value.created_at, value.evidence_id, value.observed_comparison
    tail = value.observed_outcome, provenance, _projection_list(value.source_experiment_ids)
    return _flat_record(_EVIDENCE_SCHEMA, *head, *tail)


def _belief_state_mapping(value: RunBeliefStateProjection) -> dict[str, object]:
    head = value.belief_state_id, value.created_at, _projection_list(value.evidence_ids)
    middle = _projection_list(value.hypothesis_ids), value.parent_belief_state_id
    tail = (
        _projection_list(value.posterior_probabilities),
        _projection_list(value.prior_probabilities),
    )
    return _flat_record(_BELIEF_SCHEMA, *head, *middle, *tail, value.sequence)


def _likelihood_mapping(value: RunHypothesisLikelihoodProjection) -> dict[str, object]:
    head = value.hypothesis_id, value.likelihood, value.posterior_probability
    return _flat_record(
        _LIKELIHOOD_SCHEMA, *head, value.prior_for_update, value.unnormalized_weight
    )


def _update_mapping(value: RunBeliefUpdateProjection) -> dict[str, object]:
    likelihoods: object = value.likelihoods
    before = _projection_child(
        value.belief_state_before, RunBeliefStateProjection, _belief_state_mapping
    )
    evidence = _projection_child(value.evidence, RunEvidenceProjection, _evidence_mapping)
    if type(likelihoods) is tuple:
        likelihoods = [
            _likelihood_mapping(item) if type(item) is RunHypothesisLikelihoodProjection else None
            for item in likelihoods
        ]
    elif type(likelihoods) is list:
        likelihoods = None
    posterior = _projection_child(
        value.posterior_belief_state, RunBeliefStateProjection, _belief_state_mapping
    )
    provenance = _projection_child(value.provenance, RunProvenanceProjection, _provenance_mapping)
    head = before, value.created_at, evidence, likelihoods, value.normalization_constant
    tail = posterior, provenance, value.update_id, value.update_rule_version
    return _flat_record(_UPDATE_SCHEMA, *head, *tail)


def _matched_effect_mapping(value: RunMatchedEffectProjection) -> dict[str, object]:
    provenance = _projection_child(value.provenance, RunProvenanceProjection, _provenance_mapping)
    head = value.available_sequence, value.comparison_group_id, value.created_at, value.effect_id
    tail = value.observed_effect, provenance, _projection_list(value.source_ids), value.source_kind
    return _flat_record(_MATCHED_EFFECT_SCHEMA, *head, *tail)


def _sigma_estimate_mapping(value: RunSigmaEstimateProjection) -> dict[str, object]:
    provenance = _projection_child(value.provenance, RunProvenanceProjection, _provenance_mapping)
    head = value.belief_model_id, value.belief_model_version, value.comparison_group_id
    time = value.created_at, value.current_evidence_excluded, value.cutoff_sequence
    identity = value.estimated_sigma, value.estimate_id, value.estimator_version
    relation = value.evidence_id, value.lineage_id, provenance
    sample = value.raw_sample_standard_deviation, value.sample_count, value.sample_mean
    tail = value.sigma_floor, _projection_list(value.source_effect_ids), value.status
    return _flat_record(
        _SIGMA_ESTIMATE_SCHEMA,
        *head,
        *time,
        *identity,
        *relation,
        *sample,
        *tail,
        value.variance_floor,
    )


def _model_belief_state_mapping(value: RunModelBeliefStateProjection) -> dict[str, object]:
    state = _projection_child(value.state, RunBeliefStateProjection, _belief_state_mapping)
    return _flat_record(
        _MODEL_BELIEF_STATE_SCHEMA,
        value.belief_model_id,
        value.belief_model_version,
        value.lineage_id,
        state,
    )


def _lineage_mapping(value: RunLineageProjection) -> dict[str, object]:
    current = _projection_child(
        value.current_state, RunModelBeliefStateProjection, _model_belief_state_mapping
    )
    return _flat_record(
        _LINEAGE_SCHEMA,
        value.belief_model_id,
        value.belief_model_version,
        value.created_at,
        current,
        value.lineage_id,
        value.lineage_key,
    )


def _predictive_interval_mapping(value: RunPredictiveIntervalProjection) -> dict[str, object]:
    return _flat_record(
        _PREDICTIVE_INTERVAL_SCHEMA,
        value.contains_observation,
        value.lower,
        value.probability,
        value.upper,
    )


def _diagnostic_mapping(value: RunDiagnosticProjection) -> dict[str, object]:
    intervals: object = value.central_intervals
    if type(intervals) is tuple:
        intervals = [
            _predictive_interval_mapping(item)
            if type(item) is RunPredictiveIntervalProjection
            else None
            for item in intervals
        ]
    elif type(intervals) is list:
        intervals = None
    residuals: object = value.per_hypothesis_residuals
    if type(residuals) is tuple:
        encoded: list[object] = []
        for pair in residuals:
            if type(pair) is tuple and len(pair) == 2:
                encoded.append([pair[0], pair[1]])
            else:
                encoded.append(None if type(pair) is list else pair)
        residuals = encoded
    elif type(residuals) is list:
        residuals = None
    provenance = _projection_child(value.provenance, RunProvenanceProjection, _provenance_mapping)
    model = value.adequacy_state, value.belief_model_id, value.belief_model_version
    identity = value.belief_state_before_id, intervals, value.comparison_group_id
    record = value.created_at, value.diagnostic_id, value.diagnostic_version
    relation = value.diagnostics_disagree, value.evidence_id, value.lineage_id, residuals
    probabilities = value.posterior_predictive_tail_probability, value.predictive_cdf
    prediction = value.predictive_density, value.predictive_log_likelihood
    moments = value.predictive_mean, value.predictive_variance, provenance
    alarms = value.repeated_residual_alarm, value.residual_count, value.residual_outlier
    tail = value.rolling_residual_outlier_count, value.sigma_estimate_id
    return _flat_record(
        _DIAGNOSTIC_SCHEMA,
        *model,
        *identity,
        *record,
        *relation,
        *probabilities,
        *prediction,
        *moments,
        *alarms,
        *tail,
        value.standardized_residual,
        value.tail_alarm,
    )


def _model_update_mapping(value: RunModelUpdateProjection) -> dict[str, object]:
    bayesian = _projection_child(value.bayesian_update, RunBeliefUpdateProjection, _update_mapping)
    diagnostic = _projection_child(value.diagnostic, RunDiagnosticProjection, _diagnostic_mapping)
    evidence = _projection_child(value.evidence, RunEvidenceProjection, _evidence_mapping)
    posterior = _projection_child(
        value.posterior_state, RunModelBeliefStateProjection, _model_belief_state_mapping
    )
    provenance = _projection_child(value.provenance, RunProvenanceProjection, _provenance_mapping)
    sigma = _projection_child(
        value.sigma_estimate, RunSigmaEstimateProjection, _sigma_estimate_mapping
    )
    before = _projection_child(
        value.state_before, RunModelBeliefStateProjection, _model_belief_state_mapping
    )
    head = bayesian, value.belief_model_id, value.belief_model_version, value.created_at
    middle = diagnostic, evidence, value.lineage_id, value.model_update_id
    return _flat_record(_MODEL_UPDATE_SCHEMA, *head, *middle, posterior, provenance, sigma, before)


def _observation_authorization_mapping(
    value: RunObservationAuthorizationProjection,
) -> dict[str, object]:
    return _flat_record(
        _OBSERVATION_AUTHORIZATION_SCHEMA,
        value.candidate_id,
        value.kind,
        value.run_id,
        value.source_id,
    )


def _revealed_observation_mapping(value: RunRevealedObservationProjection) -> dict[str, object]:
    authorization = _projection_child(
        value.authorization,
        RunObservationAuthorizationProjection,
        _observation_authorization_mapping,
    )
    return _flat_record(
        _REVEALED_OBSERVATION_SCHEMA,
        authorization,
        value.authorization_id,
        value.candidate_id,
        value.comparison_group_id,
        value.digest,
        value.intervention_arm,
        _projection_list(value.key_fields),
        value.namespace,
        value.oracle_key_id,
        value.oracle_use_id,
        value.outcome_digest,
        value.replication_id,
        value.revealed_observation,
        value.seed,
        value.serialized_key_hex,
        value.u,
        value.world_id,
        value.z,
    )


def _calibration_estimate_mapping(
    value: RunCalibrationEstimateProjection,
) -> dict[str, object]:
    effects = _projection_sequence_mapping(
        value.effects,
        RunMatchedEffectProjection,
        _matched_effect_mapping,
    )
    observations = _projection_sequence_mapping(
        value.observations,
        RunRevealedObservationProjection,
        _revealed_observation_mapping,
    )
    return _flat_record(
        _CALIBRATION_ESTIMATE_SCHEMA,
        value.belief_model_id,
        value.calibration_prefix_id,
        value.comparison_group_id,
        value.ddof,
        effects,
        value.estimated_sigma,
        value.lineage_id,
        observations,
        value.physical_cost,
        value.provenance_sha256,
        value.raw_sample_standard_deviation,
        value.sample_count,
        value.sample_mean,
        value.sigma_estimate_id,
        value.sigma_floor,
        _projection_list(value.source_effect_ids),
        value.source_sequence_cutoff,
    )


def _calibration_mapping(value: RunCalibrationProjection) -> dict[str, object]:
    effects = _projection_sequence_mapping(
        value.effects,
        RunMatchedEffectProjection,
        _matched_effect_mapping,
    )
    estimates = _projection_sequence_mapping(
        value.estimates,
        RunCalibrationEstimateProjection,
        _calibration_estimate_mapping,
    )
    observations = _projection_sequence_mapping(
        value.observations,
        RunRevealedObservationProjection,
        _revealed_observation_mapping,
    )
    return _flat_record(
        _CALIBRATION_SCHEMA,
        value.cost,
        effects,
        estimates,
        observations,
    )


def _control_value_mapping(value: ControlValueProjection) -> dict[str, object]:
    return {"kind": value.kind, "value": value.value}


def _controlled_variables_mapping(
    value: object,
) -> object:
    if type(value) is list:
        return None
    if type(value) is not tuple:
        return value
    encoded: list[object] = []
    for pair in value:
        if type(pair) is not tuple or len(pair) != 2:
            encoded.append(None if type(pair) is list else pair)
            continue
        control = _projection_child(pair[1], ControlValueProjection, _control_value_mapping)
        encoded.append([pair[0], control])
    return encoded


def _public_design_mapping(value: RunPublicExperimentDesignProjection) -> dict[str, object]:
    return _flat_record(
        _PUBLIC_DESIGN_SCHEMA,
        value.candidate_id,
        value.comparison_group_id,
        _controlled_variables_mapping(value.controlled_variables),
        value.experiment_family,
        value.intervention_arm,
        value.intervention_variable,
    )


def _hypothesis_decision_context_mapping(
    value: RunHypothesisDecisionContextProjection,
) -> dict[str, object]:
    return _flat_record(
        _HYPOTHESIS_DECISION_CONTEXT_SCHEMA,
        value.hypothesis_id,
        value.most_favorable_outcome,
        value.most_favorable_outcome_label,
        value.posterior_if_observed,
        value.posterior_probability,
        value.statement,
    )


def _candidate_score_mapping(value: RunCandidateScoreProjection) -> dict[str, object]:
    candidate = _projection_child(value.candidate, RunCandidateProjection, _candidate_mapping)
    return _flat_record(
        _CANDIDATE_SCORE_SCHEMA,
        candidate,
        value.completes_matched_pair,
        value.estimated_cost,
        value.expected_information_gain,
        value.expected_posterior_entropy,
        value.matched_experiment_id,
        value.prior_entropy,
        value.ranking_reason,
        value.score_reason,
    )


def _decision_trace_mapping(value: RunDecisionTraceProjection) -> dict[str, object]:
    hypotheses: object = value.hypotheses
    if type(hypotheses) is tuple:
        hypotheses = [
            _hypothesis_decision_context_mapping(item)
            if type(item) is RunHypothesisDecisionContextProjection
            else None
            for item in hypotheses
        ]
    elif type(hypotheses) is list:
        hypotheses = None
    provenance = _projection_child(
        value.provenance,
        RunProvenanceProjection,
        _provenance_mapping,
    )
    ranked: object = value.ranked_candidates
    if type(ranked) is tuple:
        ranked = [
            _candidate_score_mapping(item) if type(item) is RunCandidateScoreProjection else None
            for item in ranked
        ]
    elif type(ranked) is list:
        ranked = None
    selected = _projection_child(
        value.selected, RunCandidateScoreProjection, _candidate_score_mapping
    )
    return _flat_record(
        _DECISION_TRACE_SCHEMA,
        value.belief_state_id,
        value.created_at,
        value.fallback_reason,
        hypotheses,
        value.max_cost,
        value.policy,
        value.policy_version,
        provenance,
        ranked,
        value.rationale,
        selected,
        value.suggestion_id,
    )


def _probability_pairs_mapping(value: object) -> object:
    if type(value) is list:
        return None
    if type(value) is not tuple:
        return value
    encoded: list[object] = []
    for pair in value:
        if type(pair) is tuple and len(pair) == 2:
            encoded.append([pair[0], pair[1]])
        else:
            encoded.append(None if type(pair) is list else pair)
    return encoded


def _projection_sequence_mapping[T](
    value: object,
    expected: type[T],
    mapping: Callable[[T], dict[str, object]],
) -> object:
    if type(value) is list:
        return None
    if type(value) is not tuple:
        return value
    return [mapping(item) if type(item) is expected else None for item in value]


def _lookahead_second_action_mapping(
    value: RunLookaheadSecondActionProjection,
) -> dict[str, object]:
    candidate: object = value.candidate
    if candidate is not None:
        candidate = _projection_child(candidate, RunCandidateProjection, _candidate_mapping)
    return _flat_record(
        _LOOKAHEAD_SECOND_ACTION_SCHEMA,
        value.action_effect,
        candidate,
        value.estimated_cost,
        value.expected_information_gain,
        value.information_gain_per_cost,
        value.reason,
    )


def _lookahead_branch_mapping(value: RunLookaheadBranchProjection) -> dict[str, object]:
    second = _projection_child(
        value.second_action,
        RunLookaheadSecondActionProjection,
        _lookahead_second_action_mapping,
    )
    return _flat_record(
        _LOOKAHEAD_BRANCH_SCHEMA,
        value.branch_id,
        value.branch_total_cost,
        value.budget_feasible,
        value.evidence_lower_bound,
        value.evidence_upper_bound,
        value.label,
        value.posterior_entropy,
        _probability_pairs_mapping(value.posterior_probabilities),
        value.probability,
        second,
        value.terminal_entropy,
    )


def _lookahead_first_action_mapping(
    value: RunLookaheadFirstActionProjection,
) -> dict[str, object]:
    branches = _projection_sequence_mapping(
        value.branches, RunLookaheadBranchProjection, _lookahead_branch_mapping
    )
    candidate = _projection_child(value.candidate, RunCandidateProjection, _candidate_mapping)
    design = _projection_child(
        value.public_design,
        RunPublicExperimentDesignProjection,
        _public_design_mapping,
    )
    return _flat_record(
        _LOOKAHEAD_FIRST_ACTION_SCHEMA,
        value.action_effect,
        branches,
        candidate,
        value.expected_terminal_entropy,
        value.expected_total_cost,
        value.expected_total_information_gain,
        value.first_action_cost,
        value.immediate_information_gain,
        value.information_gain_per_expected_cost,
        value.prior_entropy,
        design,
        value.ranking_reason,
    )


def _lookahead_alternative_mapping(
    value: RunLookaheadAlternativeProjection,
) -> dict[str, object]:
    candidate = _projection_child(value.candidate, RunCandidateProjection, _candidate_mapping)
    return _flat_record(
        _LOOKAHEAD_ALTERNATIVE_SCHEMA,
        value.action_effect,
        candidate,
        value.comparison_group_id,
        value.expected_total_cost,
        value.expected_total_information_gain,
        value.immediate_information_gain,
        value.information_gain_per_expected_cost,
        value.ranking_reason,
    )


def _lookahead_trace_mapping(value: RunLookaheadTraceProjection) -> dict[str, object]:
    alternatives = _projection_sequence_mapping(
        value.alternatives,
        RunLookaheadAlternativeProjection,
        _lookahead_alternative_mapping,
    )
    provenance = _projection_child(
        value.provenance,
        RunProvenanceProjection,
        _provenance_mapping,
    )
    selected = _projection_child(
        value.selected,
        RunLookaheadFirstActionProjection,
        _lookahead_first_action_mapping,
    )
    return _flat_record(
        _LOOKAHEAD_TRACE_SCHEMA,
        alternatives,
        value.belief_state_id,
        value.candidate_set_fingerprint,
        value.completed_state_fingerprint,
        value.created_at,
        _probability_pairs_mapping(value.current_hypothesis_probabilities),
        value.fallback_reason,
        value.max_cost,
        value.plan_id,
        value.policy,
        value.policy_version,
        provenance,
        value.rationale,
        selected,
        _projection_list(value.tie_breaking_order),
    )


def _policy_trace_mapping(
    value: RunPolicyTraceProjection,
    *,
    defer_validation: bool = False,
) -> dict[str, object]:
    projection: object
    if type(value.projection) is RunDecisionTraceProjection and (
        defer_validation or value.kind == "decision_trace"
    ):
        projection = _projection_child(
            value.projection,
            RunDecisionTraceProjection,
            _decision_trace_mapping,
        )
    elif type(value.projection) is RunLookaheadTraceProjection and (
        defer_validation or value.kind == "lookahead_plan_trace"
    ):
        projection = _projection_child(
            value.projection,
            RunLookaheadTraceProjection,
            _lookahead_trace_mapping,
        )
    elif defer_validation:
        projection = None
    elif value.kind not in {"decision_trace", "lookahead_plan_trace"}:
        _structural("policy_trace.kind", "unknown policy-trace tag")
    else:
        _structural("policy_trace.projection", "tag and projection type do not match")
    return {"kind": value.kind, "projection": projection}


def _arm_decision_mapping(
    value: RunArmDecisionProjection,
    *,
    defer_policy_validation: bool = False,
) -> dict[str, object]:
    policy_trace = _projection_child(
        value.policy_trace,
        RunPolicyTraceProjection,
        lambda item: _policy_trace_mapping(
            item,
            defer_validation=defer_policy_validation,
        ),
    )
    return _flat_record(
        _ARM_DECISION_SCHEMA,
        _projection_list(value.affordable_candidate_ids),
        value.belief_state_id,
        value.decision_id,
        value.fixed_policy_regression_match,
        policy_trace,
        _projection_list(value.public_feasible_candidate_ids),
        value.remaining_budget,
        value.selected_candidate_id,
        value.step,
    )


def _arm_action_mapping(value: RunArmActionProjection) -> dict[str, object]:
    observation: object = value.oracle_observation
    if observation is not None:
        observation = _projection_child(
            observation,
            RunRevealedObservationProjection,
            _revealed_observation_mapping,
        )
    return _flat_record(
        _ARM_ACTION_SCHEMA,
        value.candidate_id,
        value.cost,
        value.cumulative_decision_cost,
        value.decision_id,
        _projection_list(value.new_evidence_ids),
        value.observed_objective,
        observation,
        _probability_pairs_mapping(value.posterior_probabilities),
        value.role,
        value.step,
    )


def _arm_value_mapping(value: object) -> object:
    if type(value) is not tuple or len(value) != 4:
        return None
    arm_id, arm_order, belief_model_id, policy_id = value
    return {
        "arm_id": arm_id,
        "arm_order": arm_order,
        "belief_model_id": belief_model_id,
        "policy_id": policy_id,
    }


def _returned_run_mapping(
    value: ReturnedRunProjection,
    *,
    defer_policy_validation: bool = False,
) -> dict[str, object]:
    calibration: object = value.calibration
    if calibration is not None:
        calibration = _projection_child(
            calibration,
            RunCalibrationProjection,
            _calibration_mapping,
        )
    lineage = _projection_child(value.lineage, RunLineageProjection, _lineage_mapping)
    return _flat_record(
        _RETURNED_RUN_SCHEMA,
        _projection_sequence_mapping(value.actions, RunArmActionProjection, _arm_action_mapping),
        _arm_value_mapping(value.arm),
        value.budget,
        value.budget_id,
        calibration,
        value.calibration_cost,
        value.comparison_id,
        _projection_sequence_mapping(
            value.completed_experiments,
            RunCompletedExperimentProjection,
            _experiment_mapping,
        ),
        value.decision_cost,
        _projection_sequence_mapping(
            value.decisions,
            RunArmDecisionProjection,
            lambda item: _arm_decision_mapping(
                item,
                defer_policy_validation=defer_policy_validation,
            ),
        ),
        _projection_sequence_mapping(
            value.diagnostics,
            RunDiagnosticProjection,
            _diagnostic_mapping,
        ),
        _projection_sequence_mapping(
            value.effect_history,
            RunMatchedEffectProjection,
            _matched_effect_mapping,
        ),
        _projection_sequence_mapping(value.evidence, RunEvidenceProjection, _evidence_mapping),
        _probability_pairs_mapping(value.initial_probabilities),
        lineage,
        value.run_id,
        value.run_status,
        value.schema_version,
        value.seed,
        value.terminal_reason,
        _projection_sequence_mapping(
            value.updates,
            RunModelUpdateProjection,
            _model_update_mapping,
        ),
        value.world_id,
    )


def projection_as_dict(value: object) -> dict[str, object]:
    """Encode through one explicit family and validate in displayed field order."""

    decoder: Callable[[object], object]
    if type(value) is ProvenanceValueProjection:
        raw, decoder = _provenance_value_mapping(value), decode_provenance_value_projection
    elif type(value) is RunProvenanceProjection:
        raw, decoder = _provenance_mapping(value), decode_run_provenance_projection
    elif type(value) is RunCandidateProjection:
        raw, decoder = _candidate_mapping(value), decode_run_candidate_projection
    elif type(value) is RunCompletedExperimentProjection:
        raw, decoder = _experiment_mapping(value), decode_run_completed_experiment_projection
    elif type(value) is RunEvidenceProjection:
        raw, decoder = _evidence_mapping(value), decode_run_evidence_projection
    elif type(value) is RunBeliefStateProjection:
        raw, decoder = _belief_state_mapping(value), decode_run_belief_state_projection
    elif type(value) is RunHypothesisLikelihoodProjection:
        raw, decoder = _likelihood_mapping(value), decode_run_hypothesis_likelihood_projection
    elif type(value) is RunBeliefUpdateProjection:
        raw, decoder = _update_mapping(value), decode_run_belief_update_projection
    elif type(value) is RunMatchedEffectProjection:
        raw, decoder = _matched_effect_mapping(value), decode_run_matched_effect_projection
    elif type(value) is RunSigmaEstimateProjection:
        raw, decoder = _sigma_estimate_mapping(value), decode_run_sigma_estimate_projection
    elif type(value) is RunModelBeliefStateProjection:
        raw, decoder = _model_belief_state_mapping(value), decode_run_model_belief_state_projection
    elif type(value) is RunLineageProjection:
        raw, decoder = _lineage_mapping(value), decode_run_lineage_projection
    elif type(value) is RunPredictiveIntervalProjection:
        raw = _predictive_interval_mapping(value)
        decoder = decode_run_predictive_interval_projection
    elif type(value) is RunDiagnosticProjection:
        raw, decoder = _diagnostic_mapping(value), decode_run_diagnostic_projection
    elif type(value) is RunModelUpdateProjection:
        raw, decoder = _model_update_mapping(value), decode_run_model_update_projection
    elif type(value) is RunObservationAuthorizationProjection:
        raw = _observation_authorization_mapping(value)
        decoder = decode_run_observation_authorization_projection
    elif type(value) is RunRevealedObservationProjection:
        raw = _revealed_observation_mapping(value)
        decoder = decode_run_revealed_observation_projection
    elif type(value) is RunCalibrationEstimateProjection:
        raw = _calibration_estimate_mapping(value)
        decoder = decode_run_calibration_estimate_projection
    elif type(value) is RunCalibrationProjection:
        raw = _calibration_mapping(value)
        decoder = decode_run_calibration_projection
    elif type(value) is ControlValueProjection:
        raw, decoder = _control_value_mapping(value), decode_control_value_projection
    elif type(value) is RunPublicExperimentDesignProjection:
        raw = _public_design_mapping(value)
        decoder = decode_run_public_experiment_design_projection
    elif type(value) is RunHypothesisDecisionContextProjection:
        raw = _hypothesis_decision_context_mapping(value)
        decoder = decode_run_hypothesis_decision_context_projection
    elif type(value) is RunCandidateScoreProjection:
        raw, decoder = _candidate_score_mapping(value), decode_run_candidate_score_projection
    elif type(value) is RunDecisionTraceProjection:
        raw, decoder = _decision_trace_mapping(value), decode_run_decision_trace_projection
    elif type(value) is RunLookaheadSecondActionProjection:
        raw = _lookahead_second_action_mapping(value)
        decoder = decode_run_lookahead_second_action_projection
    elif type(value) is RunLookaheadBranchProjection:
        raw, decoder = _lookahead_branch_mapping(value), decode_run_lookahead_branch_projection
    elif type(value) is RunLookaheadFirstActionProjection:
        raw = _lookahead_first_action_mapping(value)
        decoder = decode_run_lookahead_first_action_projection
    elif type(value) is RunLookaheadAlternativeProjection:
        raw = _lookahead_alternative_mapping(value)
        decoder = decode_run_lookahead_alternative_projection
    elif type(value) is RunLookaheadTraceProjection:
        raw, decoder = _lookahead_trace_mapping(value), decode_run_lookahead_trace_projection
    elif type(value) is RunPolicyTraceProjection:
        raw, decoder = _policy_trace_mapping(value), decode_run_policy_trace_projection
    elif type(value) is RunArmDecisionProjection:
        raw, decoder = _arm_decision_mapping(value), decode_run_arm_decision_projection
    elif type(value) is RunArmActionProjection:
        raw, decoder = _arm_action_mapping(value), decode_run_arm_action_projection
    elif type(value) is ReturnedRunProjection:
        # The complete returned-run gate owns scientific tag/enum/coupling
        # validation at S1.  Mapping still walks the closed handwritten type
        # topology, but re-decoding here would let nested standalone decoders
        # misclassify those scientific defects as structural before S1.
        return _returned_run_mapping(value)
    else:
        _structural("projection", "unsupported projection type")
    decoder(raw)
    return raw


def _closed_dict(value: object, fields: tuple[str, ...], path: str) -> dict[str, object]:
    if type(value) is not dict:
        _structural(path, "expected an exact parsed dictionary")
    parsed: dict[str, object] = value
    for field in fields:
        if field not in parsed:
            _structural(f"{path}.{field}", "required field is missing")
    if len(parsed) != len(fields):
        _structural(path, "closed projection contains an extra field")
    return parsed


def _list(value: object, path: str) -> list[object]:
    if type(value) is not list:
        _structural(path, "expected an exact parsed list")
    return value


def _string(value: object, path: str) -> str:
    if type(value) is not str:
        _structural(path, "expected a string")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        _structural(path, "lone surrogate code points are forbidden")
    if unicodedata.normalize("NFC", value) != value:
        _structural(path, "string is not NFC")
    return value


def _is_structurally_admitted_string(
    value: object,
    *,
    identifier: bool = False,
) -> bool:
    if (
        type(value) is not str
        or any(0xD800 <= ord(character) <= 0xDFFF for character in value)
        or unicodedata.normalize("NFC", value) != value
    ):
        return False
    if not identifier:
        return True
    first = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    admitted = first + "._:/-"
    return (
        bool(value) and value[0] in first and all(character in admitted for character in value[1:])
    )


def _id(value: object, path: str) -> str:
    text = _string(value, path)
    first = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    admitted = first + "._:/-"
    if not text or text[0] not in first or any(char not in admitted for char in text[1:]):
        _structural(path, "expected a canonical ID")
    return text


def _i64(value: object, path: str) -> int:
    if type(value) is not int or not -(2**63) <= value <= 2**63 - 1:
        _structural(path, "expected a signed 64-bit integer")
    return value


def _bool(value: object, path: str) -> bool:
    if type(value) is not bool:
        _structural(path, "expected a Boolean")
    return value


def _optional_id(value: object, path: str) -> str | None:
    return None if value is None else _id(value, path)


def _optional_string(value: object, path: str) -> str | None:
    return None if value is None else _string(value, path)


def _optional_i64(value: object, path: str) -> int | None:
    return None if value is None else _i64(value, path)


def _authorization_kind(value: object, path: str) -> Literal["calibration", "decision"]:
    text = _string(value, path)
    if text == "calibration":
        return "calibration"
    if text == "decision":
        return "decision"
    _structural(path, "unknown observation-authorization kind")


def _arm_value(value: object, path: str) -> RunArmValue:
    parsed = _closed_dict(
        value,
        ("arm_id", "arm_order", "belief_model_id", "policy_id"),
        path,
    )
    return (
        _id(parsed["arm_id"], f"{path}.arm_id"),
        _i64(parsed["arm_order"], f"{path}.arm_order"),
        _id(parsed["belief_model_id"], f"{path}.belief_model_id"),
        _id(parsed["policy_id"], f"{path}.policy_id"),
    )


def _run_status(value: object, path: str) -> Literal["complete", "invalid"]:
    text = _string(value, path)
    if text == "complete":
        return "complete"
    if text == "invalid":
        return "invalid"
    _structural(path, "unknown returned-run status")


def _returned_run_schema_version(
    value: object,
    path: str,
) -> Literal["broader-replication-returned-run/v1"]:
    text = _string(value, path)
    if text != "broader-replication-returned-run/v1":
        _structural(path, "unknown returned-run schema version")
    return "broader-replication-returned-run/v1"


def _public_action_effect(value: object, path: str) -> PublicActionEffect:
    text = _id(value, path)
    if text == "opens_pair":
        return "opens_pair"
    if text == "completes_pair":
        return "completes_pair"
    if text == "ineligible":
        return "ineligible"
    if text == "stop":
        return "stop"
    _structural(path, "unknown public action-effect tag")


def _non_stop_public_action_effect(value: object, path: str) -> NonStopPublicActionEffect:
    effect = _public_action_effect(value, path)
    if effect == "stop":
        _structural(path, "STOP is not valid for a first action or alternative")
    return effect


def _h64(value: object, path: str) -> str:
    text = _string(value, path)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        _structural(path, "expected 64 lowercase hexadecimal characters")
    return text


def _hexbytes(value: object, path: str) -> str:
    text = _string(value, path)
    if len(text) % 2 or any(char not in "0123456789abcdef" for char in text):
        _structural(path, "expected even-length lowercase hexadecimal bytes")
    if bytes.fromhex(text).hex() != text:
        _structural(path, "hexadecimal bytes are not canonical")
    return text


def _effect_source_kind(value: object, path: str) -> EffectSourceKind:
    text = _string(value, path)
    if text == "calibration":
        return "calibration"
    if text == "decision":
        return "decision"
    _structural(path, "unknown matched-effect source kind")


def _f64_text(value: object, path: str) -> str:
    text = _string(value, path)
    if (
        len(text) != 20
        or not text.startswith("f64:")
        or any(char not in "0123456789abcdef" for char in text[4:])
    ):
        _structural(path, "expected a canonical F64 string")
    decoded = struct.unpack(">d", bytes.fromhex(text[4:]))[0]
    try:
        canonical = f64(decoded)
    except ProtocolError as error:
        _structural(path, str(error))
    if canonical != text:
        _structural(path, "F64 string is not canonical")
    return text


def _float_from_f64(value: object, path: str) -> float:
    text = _f64_text(value, path)
    return float(struct.unpack(">d", bytes.fromhex(text[4:]))[0])


def _project_float(value: object, path: str) -> str:
    if type(value) is not float:
        _structural(path, "scientific F64 field is not a float")
    try:
        return f64(value)
    except ProtocolError as error:
        _structural(path, str(error))


def _decoded_items[T](value: object, path: str, check: Callable[[object, str], T]) -> tuple[T, ...]:
    return tuple(check(item, f"{path}[{i}]") for i, item in enumerate(_list(value, path)))


def _optional_f64(value: object, path: str) -> str | None:
    return None if value is None else _f64_text(value, path)


def _decoded_residuals(value: object, path: str) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    for i, raw_pair in enumerate(_list(value, path)):
        pair_path = f"{path}[{i}]"
        pair = _list(raw_pair, pair_path)
        if len(pair) != 2:
            _structural(pair_path, "residual must be a two-element pair")
        result.append((_id(pair[0], f"{pair_path}[0]"), _f64_text(pair[1], f"{pair_path}[1]")))
    return tuple(result)


def _decoded_controlled_variables(
    value: object, path: str
) -> tuple[tuple[str, ControlValueProjection], ...]:
    result: list[tuple[str, ControlValueProjection]] = []
    for i, raw_pair in enumerate(_list(value, path)):
        pair_path = f"{path}[{i}]"
        pair = _list(raw_pair, pair_path)
        if len(pair) != 2:
            _structural(pair_path, "controlled variable must be a two-element pair")
        result.append(
            (
                _string(pair[0], f"{pair_path}[0]"),
                decode_control_value_projection(pair[1]),
            )
        )
    return tuple(result)


def _decoded_probability_pairs(value: object, path: str) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    for i, raw_pair in enumerate(_list(value, path)):
        pair_path = f"{path}[{i}]"
        pair = _list(raw_pair, pair_path)
        if len(pair) != 2:
            _structural(pair_path, "probability must be a two-element pair")
        result.append((_id(pair[0], f"{pair_path}[0]"), _f64_text(pair[1], f"{pair_path}[1]")))
    return tuple(result)


def _projected_items[S, T](
    value: tuple[S, ...], path: str, check: Callable[[S, str], T]
) -> tuple[T, ...]:
    if type(value) is not tuple:
        _structural(path, "expected an exact tuple")
    return tuple(check(item, f"{path}[{i}]") for i, item in enumerate(value))


_CANDIDATE_SCHEMA: FlatSchema = (
    (("candidate_id", _id), ("learning_rate", _f64_text))
    + (("model_width", _i64), ("optimizer", _string))
    + (("regularization", _f64_text),)
)
_EXPERIMENT_SCHEMA: FlatSchema = (
    ("candidate", lambda value, _path: decode_run_candidate_projection(value)),
) + (("created_at", _string), ("observed_value", _f64_text), ("record_id", _i64))
_EVIDENCE_SCHEMA: FlatSchema = (
    (("created_at", _string), ("evidence_id", _id))
    + (("observed_comparison", _f64_text), ("observed_outcome", _string))
    + (("provenance", lambda value, _path: decode_run_provenance_projection(value)),)
    + (("source_experiment_ids", lambda value, path: _decoded_items(value, path, _i64)),)
)
_BELIEF_SCHEMA: FlatSchema = (
    (("belief_state_id", _id), ("created_at", _string))
    + (("evidence_ids", lambda value, path: _decoded_items(value, path, _id)),)
    + (("hypothesis_ids", lambda value, path: _decoded_items(value, path, _id)),)
    + (("parent_belief_state_id", lambda value, path: None if value is None else _id(value, path)),)
    + (("posterior_probabilities", lambda value, path: _decoded_items(value, path, _f64_text)),)
    + (("prior_probabilities", lambda value, path: _decoded_items(value, path, _f64_text)),)
    + (("sequence", _i64),)
)
_LIKELIHOOD_SCHEMA: FlatSchema = (
    (("hypothesis_id", _id), ("likelihood", _f64_text))
    + (("posterior_probability", _f64_text), ("prior_for_update", _f64_text))
    + (("unnormalized_weight", _f64_text),)
)
_UPDATE_SCHEMA: FlatSchema = (
    (("belief_state_before", lambda value, _path: decode_run_belief_state_projection(value)),)
    + (("created_at", _string),)
    + (("evidence", lambda value, _path: decode_run_evidence_projection(value)),)
    + (
        (
            "likelihoods",
            lambda value, path: _decoded_items(
                value, path, lambda item, _: decode_run_hypothesis_likelihood_projection(item)
            ),
        ),
    )
    + (("normalization_constant", _f64_text),)
    + (("posterior_belief_state", lambda value, _path: decode_run_belief_state_projection(value)),)
    + (("provenance", lambda value, _path: decode_run_provenance_projection(value)),)
    + (("update_id", _id), ("update_rule_version", _string))
)
_OBSERVATION_AUTHORIZATION_SCHEMA: FlatSchema = (
    ("candidate_id", _id),
    ("kind", _authorization_kind),
    ("run_id", _id),
    ("source_id", _id),
)
_REVEALED_OBSERVATION_SCHEMA: FlatSchema = (
    (
        "authorization",
        lambda value, _path: decode_run_observation_authorization_projection(value),
    ),
    ("authorization_id", _id),
    ("candidate_id", _id),
    ("comparison_group_id", _optional_id),
    ("digest", _h64),
    ("intervention_arm", _optional_id),
    ("key_fields", lambda value, path: _decoded_items(value, path, _string)),
    ("namespace", _id),
    ("oracle_key_id", _id),
    ("oracle_use_id", _id),
    ("outcome_digest", _h64),
    ("replication_id", _id),
    ("revealed_observation", _f64_text),
    ("seed", _i64),
    ("serialized_key_hex", _hexbytes),
    ("u", _string),
    ("world_id", _id),
    ("z", _string),
)
_CALIBRATION_ESTIMATE_SCHEMA: FlatSchema = (
    ("belief_model_id", _id),
    ("calibration_prefix_id", _id),
    ("comparison_group_id", _id),
    ("ddof", _i64),
    (
        "effects",
        lambda value, path: _decoded_items(
            value,
            path,
            lambda item, _: decode_run_matched_effect_projection(item),
        ),
    ),
    ("estimated_sigma", _f64_text),
    ("lineage_id", _id),
    (
        "observations",
        lambda value, path: _decoded_items(
            value,
            path,
            lambda item, _: decode_run_revealed_observation_projection(item),
        ),
    ),
    ("physical_cost", _f64_text),
    ("provenance_sha256", _h64),
    ("raw_sample_standard_deviation", _f64_text),
    ("sample_count", _i64),
    ("sample_mean", _f64_text),
    ("sigma_estimate_id", _id),
    ("sigma_floor", _f64_text),
    ("source_effect_ids", lambda value, path: _decoded_items(value, path, _id)),
    ("source_sequence_cutoff", _i64),
)
_CALIBRATION_SCHEMA: FlatSchema = (
    ("cost", _f64_text),
    (
        "effects",
        lambda value, path: _decoded_items(
            value,
            path,
            lambda item, _: decode_run_matched_effect_projection(item),
        ),
    ),
    (
        "estimates",
        lambda value, path: _decoded_items(
            value,
            path,
            lambda item, _: decode_run_calibration_estimate_projection(item),
        ),
    ),
    (
        "observations",
        lambda value, path: _decoded_items(
            value,
            path,
            lambda item, _: decode_run_revealed_observation_projection(item),
        ),
    ),
)
_PUBLIC_DESIGN_SCHEMA: FlatSchema = (
    ("candidate_id", _id),
    ("comparison_group_id", _id),
    ("controlled_variables", _decoded_controlled_variables),
    ("experiment_family", _id),
    ("intervention_arm", _id),
    ("intervention_variable", _id),
)
_HYPOTHESIS_DECISION_CONTEXT_SCHEMA: FlatSchema = (
    ("hypothesis_id", _id),
    ("most_favorable_outcome", _f64_text),
    ("most_favorable_outcome_label", _string),
    ("posterior_if_observed", _f64_text),
    ("posterior_probability", _f64_text),
    ("statement", _string),
)
_CANDIDATE_SCORE_SCHEMA: FlatSchema = (
    ("candidate", lambda value, _path: decode_run_candidate_projection(value)),
    ("completes_matched_pair", _bool),
    ("estimated_cost", _f64_text),
    ("expected_information_gain", _f64_text),
    ("expected_posterior_entropy", _f64_text),
    ("matched_experiment_id", _optional_i64),
    ("prior_entropy", _f64_text),
    ("ranking_reason", _string),
    ("score_reason", _string),
)
_DECISION_TRACE_SCHEMA: FlatSchema = (
    ("belief_state_id", _id),
    ("created_at", _string),
    ("fallback_reason", _optional_string),
    (
        "hypotheses",
        lambda value, path: _decoded_items(
            value,
            path,
            lambda item, _: decode_run_hypothesis_decision_context_projection(item),
        ),
    ),
    ("max_cost", _f64_text),
    ("policy", _string),
    ("policy_version", _string),
    ("provenance", lambda value, _path: decode_run_provenance_projection(value)),
    (
        "ranked_candidates",
        lambda value, path: _decoded_items(
            value, path, lambda item, _: decode_run_candidate_score_projection(item)
        ),
    ),
    ("rationale", _string),
    ("selected", lambda value, _path: decode_run_candidate_score_projection(value)),
    ("suggestion_id", _id),
)
_LOOKAHEAD_SECOND_ACTION_SCHEMA: FlatSchema = (
    ("action_effect", _public_action_effect),
    (
        "candidate",
        lambda value, _path: None if value is None else decode_run_candidate_projection(value),
    ),
    ("estimated_cost", _f64_text),
    ("expected_information_gain", _f64_text),
    ("information_gain_per_cost", _f64_text),
    ("reason", _string),
)
_LOOKAHEAD_BRANCH_SCHEMA: FlatSchema = (
    ("branch_id", _id),
    ("branch_total_cost", _f64_text),
    ("budget_feasible", _bool),
    ("evidence_lower_bound", _optional_f64),
    ("evidence_upper_bound", _optional_f64),
    ("label", _string),
    ("posterior_entropy", _f64_text),
    ("posterior_probabilities", _decoded_probability_pairs),
    ("probability", _f64_text),
    (
        "second_action",
        lambda value, _path: decode_run_lookahead_second_action_projection(value),
    ),
    ("terminal_entropy", _f64_text),
)
_LOOKAHEAD_FIRST_ACTION_SCHEMA: FlatSchema = (
    ("action_effect", _non_stop_public_action_effect),
    (
        "branches",
        lambda value, path: _decoded_items(
            value, path, lambda item, _: decode_run_lookahead_branch_projection(item)
        ),
    ),
    ("candidate", lambda value, _path: decode_run_candidate_projection(value)),
    ("expected_terminal_entropy", _f64_text),
    ("expected_total_cost", _f64_text),
    ("expected_total_information_gain", _f64_text),
    ("first_action_cost", _f64_text),
    ("immediate_information_gain", _f64_text),
    ("information_gain_per_expected_cost", _f64_text),
    ("prior_entropy", _f64_text),
    (
        "public_design",
        lambda value, _path: decode_run_public_experiment_design_projection(value),
    ),
    ("ranking_reason", _string),
)
_LOOKAHEAD_ALTERNATIVE_SCHEMA: FlatSchema = (
    ("action_effect", _non_stop_public_action_effect),
    ("candidate", lambda value, _path: decode_run_candidate_projection(value)),
    ("comparison_group_id", _id),
    ("expected_total_cost", _f64_text),
    ("expected_total_information_gain", _f64_text),
    ("immediate_information_gain", _f64_text),
    ("information_gain_per_expected_cost", _f64_text),
    ("ranking_reason", _string),
)
_LOOKAHEAD_TRACE_SCHEMA: FlatSchema = (
    (
        "alternatives",
        lambda value, path: _decoded_items(
            value, path, lambda item, _: decode_run_lookahead_alternative_projection(item)
        ),
    ),
    ("belief_state_id", _id),
    ("candidate_set_fingerprint", _id),
    ("completed_state_fingerprint", _id),
    ("created_at", _string),
    ("current_hypothesis_probabilities", _decoded_probability_pairs),
    ("fallback_reason", _optional_string),
    ("max_cost", _f64_text),
    ("plan_id", _id),
    ("policy", _string),
    ("policy_version", _string),
    ("provenance", lambda value, _path: decode_run_provenance_projection(value)),
    ("rationale", _string),
    (
        "selected",
        lambda value, _path: decode_run_lookahead_first_action_projection(value),
    ),
    ("tie_breaking_order", lambda value, path: _decoded_items(value, path, _string)),
)
_ARM_DECISION_SCHEMA: FlatSchema = (
    (
        "affordable_candidate_ids",
        lambda value, path: _decoded_items(value, path, _id),
    ),
    ("belief_state_id", _id),
    ("decision_id", _id),
    ("fixed_policy_regression_match", _bool),
    ("policy_trace", lambda value, _path: decode_run_policy_trace_projection(value)),
    (
        "public_feasible_candidate_ids",
        lambda value, path: _decoded_items(value, path, _id),
    ),
    ("remaining_budget", _f64_text),
    ("selected_candidate_id", _id),
    ("step", _i64),
)
_ARM_ACTION_SCHEMA: FlatSchema = (
    ("candidate_id", _id),
    ("cost", _f64_text),
    ("cumulative_decision_cost", _f64_text),
    ("decision_id", _id),
    ("new_evidence_ids", lambda value, path: _decoded_items(value, path, _id)),
    ("observed_objective", _optional_f64),
    (
        "oracle_observation",
        lambda value, _path: (
            None if value is None else decode_run_revealed_observation_projection(value)
        ),
    ),
    ("posterior_probabilities", _decoded_probability_pairs),
    ("role", _id),
    ("step", _i64),
)
_RETURNED_RUN_SCHEMA: FlatSchema = (
    (
        "actions",
        lambda value, path: _decoded_items(
            value, path, lambda item, _item_path: decode_run_arm_action_projection(item)
        ),
    ),
    ("arm", _arm_value),
    ("budget", _f64_text),
    ("budget_id", _id),
    (
        "calibration",
        lambda value, _path: None if value is None else decode_run_calibration_projection(value),
    ),
    ("calibration_cost", _f64_text),
    ("comparison_id", _id),
    (
        "completed_experiments",
        lambda value, path: _decoded_items(
            value,
            path,
            lambda item, _item_path: decode_run_completed_experiment_projection(item),
        ),
    ),
    ("decision_cost", _f64_text),
    (
        "decisions",
        lambda value, path: _decoded_items(
            value, path, lambda item, _item_path: decode_run_arm_decision_projection(item)
        ),
    ),
    (
        "diagnostics",
        lambda value, path: _decoded_items(
            value, path, lambda item, _item_path: decode_run_diagnostic_projection(item)
        ),
    ),
    (
        "effect_history",
        lambda value, path: _decoded_items(
            value, path, lambda item, _item_path: decode_run_matched_effect_projection(item)
        ),
    ),
    (
        "evidence",
        lambda value, path: _decoded_items(
            value, path, lambda item, _item_path: decode_run_evidence_projection(item)
        ),
    ),
    ("initial_probabilities", _decoded_probability_pairs),
    ("lineage", lambda value, _path: decode_run_lineage_projection(value)),
    ("run_id", _id),
    ("run_status", _run_status),
    ("schema_version", _returned_run_schema_version),
    ("seed", _i64),
    ("terminal_reason", _id),
    (
        "updates",
        lambda value, path: _decoded_items(
            value, path, lambda item, _item_path: decode_run_model_update_projection(item)
        ),
    ),
    ("world_id", _id),
)
_MATCHED_EFFECT_SCHEMA: FlatSchema = (
    (("available_sequence", _i64), ("comparison_group_id", _id))
    + (("created_at", _string), ("effect_id", _id), ("observed_effect", _f64_text))
    + (("provenance", lambda value, _path: decode_run_provenance_projection(value)),)
    + (("source_ids", lambda value, path: _decoded_items(value, path, _id)),)
    + (("source_kind", _effect_source_kind),)
)
_SIGMA_ESTIMATE_SCHEMA: FlatSchema = (
    (("belief_model_id", _id), ("belief_model_version", _string))
    + (("comparison_group_id", _id), ("created_at", _string))
    + (("current_evidence_excluded", _bool), ("cutoff_sequence", _i64))
    + (("estimated_sigma", _f64_text), ("estimate_id", _id))
    + (("estimator_version", _string), ("evidence_id", _id), ("lineage_id", _id))
    + (("provenance", lambda value, _path: decode_run_provenance_projection(value)),)
    + (("raw_sample_standard_deviation", _optional_f64), ("sample_count", _i64))
    + (("sample_mean", _optional_f64), ("sigma_floor", _f64_text))
    + (("source_effect_ids", lambda value, path: _decoded_items(value, path, _id)),)
    + (("status", _string), ("variance_floor", _f64_text))
)
_MODEL_BELIEF_STATE_SCHEMA: FlatSchema = (
    ("belief_model_id", _id),
    ("belief_model_version", _string),
    ("lineage_id", _id),
) + (("state", lambda value, _path: decode_run_belief_state_projection(value)),)
_LINEAGE_SCHEMA: FlatSchema = (
    (("belief_model_id", _id), ("belief_model_version", _string), ("created_at", _string))
    + (
        (
            "current_state",
            lambda value, _path: decode_run_model_belief_state_projection(value),
        ),
    )
    + (("lineage_id", _id), ("lineage_key", _string))
)
_PREDICTIVE_INTERVAL_SCHEMA: FlatSchema = (
    ("contains_observation", _bool),
    ("lower", _f64_text),
) + (("probability", _f64_text), ("upper", _f64_text))
_DIAGNOSTIC_SCHEMA: FlatSchema = (
    (("adequacy_state", _string), ("belief_model_id", _id))
    + (("belief_model_version", _string), ("belief_state_before_id", _id))
    + (
        (
            "central_intervals",
            lambda value, path: _decoded_items(
                value,
                path,
                lambda item, _: decode_run_predictive_interval_projection(item),
            ),
        ),
    )
    + (("comparison_group_id", _id), ("created_at", _string), ("diagnostic_id", _id))
    + (("diagnostic_version", _string), ("diagnostics_disagree", _bool))
    + (("evidence_id", _id), ("lineage_id", _id))
    + (("per_hypothesis_residuals", _decoded_residuals),)
    + (("posterior_predictive_tail_probability", _f64_text), ("predictive_cdf", _f64_text))
    + (("predictive_density", _f64_text), ("predictive_log_likelihood", _f64_text))
    + (("predictive_mean", _f64_text), ("predictive_variance", _f64_text))
    + (("provenance", lambda value, _path: decode_run_provenance_projection(value)),)
    + (("repeated_residual_alarm", _bool), ("residual_count", _i64))
    + (("residual_outlier", _bool), ("rolling_residual_outlier_count", _i64))
    + (("sigma_estimate_id", _id), ("standardized_residual", _f64_text))
    + (("tail_alarm", _bool),)
)
_MODEL_UPDATE_SCHEMA: FlatSchema = (
    (("bayesian_update", lambda value, _path: decode_run_belief_update_projection(value)),)
    + (("belief_model_id", _id), ("belief_model_version", _string), ("created_at", _string))
    + (("diagnostic", lambda value, _path: decode_run_diagnostic_projection(value)),)
    + (("evidence", lambda value, _path: decode_run_evidence_projection(value)),)
    + (("lineage_id", _id), ("model_update_id", _id))
    + (
        (
            "posterior_state",
            lambda value, _path: decode_run_model_belief_state_projection(value),
        ),
    )
    + (("provenance", lambda value, _path: decode_run_provenance_projection(value)),)
    + (("sigma_estimate", lambda value, _path: decode_run_sigma_estimate_projection(value)),)
    + (
        (
            "state_before",
            lambda value, _path: decode_run_model_belief_state_projection(value),
        ),
    )
)


def _flat_record(schema: FlatSchema, *values: object) -> dict[str, object]:
    return dict(zip((name for name, _check in schema), values, strict=True))


def _decode_flat[T](
    value: object, path: str, schema: FlatSchema, constructor: Callable[..., T]
) -> T:
    fields = tuple(name for name, _check in schema)
    parsed = _closed_dict(value, fields, path)
    values = (check(parsed[name], f"{path}.{name}") for name, check in schema)
    return constructor(*values)


def project_provenance_value(value: ProvenanceValue) -> ProvenanceValueProjection:
    if value is None:
        return ProvenanceValueProjection("null", None)
    if type(value) is bool:
        return ProvenanceValueProjection("bool", value)
    if type(value) is int:
        return ProvenanceValueProjection("i64", _i64(value, "value"))
    if type(value) is float:
        return ProvenanceValueProjection("f64", _project_float(value, "value"))
    if type(value) is str:
        return ProvenanceValueProjection("string", _string(value, "value"))
    _structural("value", "unsupported provenance value type")


def decode_provenance_value_projection(value: object) -> ProvenanceValueProjection:
    parsed = _closed_dict(value, ("kind", "value"), "provenance_value")
    kind = _string(parsed["kind"], "provenance_value.kind")
    raw = parsed["value"]
    if kind == "null":
        if raw is not None:
            _structural("provenance_value.value", "null kind requires an explicit null")
        return ProvenanceValueProjection("null", None)
    if kind == "bool":
        if type(raw) is not bool:
            _structural("provenance_value.value", "bool kind requires a Boolean")
        return ProvenanceValueProjection("bool", raw)
    if kind == "i64":
        return ProvenanceValueProjection("i64", _i64(raw, "provenance_value.value"))
    if kind == "f64":
        return ProvenanceValueProjection("f64", _f64_text(raw, "provenance_value.value"))
    if kind == "string":
        return ProvenanceValueProjection("string", _string(raw, "provenance_value.value"))
    _structural("provenance_value.kind", "unknown provenance value kind")


def provenance_value_from_projection(projection: ProvenanceValueProjection) -> ProvenanceValue:
    projection_as_dict(projection)
    if projection.kind == "f64":
        return _float_from_f64(projection.value, "provenance_value.value")
    return projection.value


def project_provenance(value: Provenance) -> RunProvenanceProjection:
    if type(value) is not Provenance:
        _structural("provenance", "expected Provenance")

    def project_detail(
        pair: tuple[str, ProvenanceValue],
        path: str,
    ) -> tuple[str, ProvenanceValueProjection]:
        if type(pair) is not tuple or len(pair) != 2:
            _structural(path, "detail must be an exact two-element tuple")
        return _string(pair[0], f"{path}[0]"), project_provenance_value(pair[1])

    details = _projected_items(
        value.details,
        "provenance.details",
        project_detail,
    )
    method = _string(value.method, "provenance.method")
    version = _string(value.version, "provenance.version")
    return RunProvenanceProjection(details, method, version)


def project_candidate(value: Candidate) -> RunCandidateProjection:
    if type(value) is not Candidate:
        _structural("candidate", "expected Candidate")
    candidate_id = _id(value.candidate_id, "candidate.candidate_id")
    learning_rate = _project_float(value.learning_rate, "candidate.learning_rate")
    model_width = _i64(value.model_width, "candidate.model_width")
    optimizer = _string(value.optimizer, "candidate.optimizer")
    regularization = _project_float(value.regularization, "candidate.regularization")
    return RunCandidateProjection(
        candidate_id, learning_rate, model_width, optimizer, regularization
    )


def project_completed_experiment(
    value: CompletedExperiment,
) -> RunCompletedExperimentProjection:
    if type(value) is not CompletedExperiment:
        _structural("completed_experiment", "expected CompletedExperiment")
    candidate = project_candidate(value.candidate)
    created_at = _string(value.created_at, "completed_experiment.created_at")
    observed = _project_float(value.observed_value, "completed_experiment.observed_value")
    record_id = _i64(value.record_id, "completed_experiment.record_id")
    return RunCompletedExperimentProjection(candidate, created_at, observed, record_id)


def project_evidence(value: Evidence) -> RunEvidenceProjection:
    if type(value) is not Evidence:
        _structural("evidence", "expected Evidence")
    created_at = _string(value.created_at, "evidence.created_at")
    evidence_id = _id(value.evidence_id, "evidence.evidence_id")
    comparison = _project_float(value.observed_comparison, "evidence.observed_comparison")
    outcome = _string(value.observed_outcome, "evidence.observed_outcome")
    provenance = project_provenance(value.provenance)
    sources = _projected_items(value.source_experiment_ids, "evidence.source_experiment_ids", _i64)
    values = created_at, evidence_id, comparison, outcome, provenance, sources
    return RunEvidenceProjection(*values)


def project_belief_state(value: BeliefState) -> RunBeliefStateProjection:
    if type(value) is not BeliefState:
        _structural("belief_state", "expected BeliefState")
    path = "belief_state"
    state_id = _id(value.belief_state_id, f"{path}.belief_state_id")
    created_at = _string(value.created_at, f"{path}.created_at")
    evidence_ids = _projected_items(value.evidence_ids, f"{path}.evidence_ids", _id)
    hypothesis_ids = _projected_items(value.hypothesis_ids, f"{path}.hypothesis_ids", _id)
    parent = value.parent_belief_state_id
    if parent is not None:
        parent = _id(parent, f"{path}.parent_belief_state_id")
    posterior = _projected_items(
        value.posterior_probabilities, f"{path}.posterior_probabilities", _project_float
    )
    prior = _projected_items(
        value.prior_probabilities, f"{path}.prior_probabilities", _project_float
    )
    sequence = _i64(value.sequence, f"{path}.sequence")
    values = state_id, created_at, evidence_ids, hypothesis_ids, parent, posterior, prior, sequence
    return RunBeliefStateProjection(*values)


def project_hypothesis_likelihood(
    value: HypothesisLikelihood,
) -> RunHypothesisLikelihoodProjection:
    if type(value) is not HypothesisLikelihood:
        _structural("hypothesis_likelihood", "expected HypothesisLikelihood")
    path = "hypothesis_likelihood"
    hypothesis_id = _id(value.hypothesis_id, f"{path}.hypothesis_id")
    likelihood = _project_float(value.likelihood, f"{path}.likelihood")
    posterior = _project_float(value.posterior_probability, f"{path}.posterior_probability")
    prior = _project_float(value.prior_for_update, f"{path}.prior_for_update")
    weight = _project_float(value.unnormalized_weight, f"{path}.unnormalized_weight")
    return RunHypothesisLikelihoodProjection(hypothesis_id, likelihood, posterior, prior, weight)


def project_belief_update(value: BeliefUpdate) -> RunBeliefUpdateProjection:
    if type(value) is not BeliefUpdate:
        _structural("belief_update", "expected BeliefUpdate")
    path = "belief_update"
    before = project_belief_state(value.belief_state_before)
    created_at = _string(value.created_at, f"{path}.created_at")
    evidence = project_evidence(value.evidence)
    likelihoods = _projected_items(
        value.likelihoods,
        f"{path}.likelihoods",
        lambda item, _: project_hypothesis_likelihood(item),
    )
    normalization = _project_float(value.normalization_constant, f"{path}.normalization_constant")
    posterior = project_belief_state(value.posterior_belief_state)
    provenance = project_provenance(value.provenance)
    update_id = _id(value.update_id, f"{path}.update_id")
    rule = _string(value.update_rule_version, f"{path}.update_rule_version")
    head = before, created_at, evidence, likelihoods, normalization
    tail = posterior, provenance, update_id, rule
    return RunBeliefUpdateProjection(*head, *tail)


def _checked_projection[T](projection: T) -> T:
    projection_as_dict(projection)
    return projection


def _checked_scientific_projection[T](
    projection: T,
    *,
    validate_science: bool,
) -> T:
    return _checked_projection(projection) if validate_science else projection


def _project_matched_effect(
    value: MatchedEffectObservation,
    *,
    validate_science: bool,
) -> RunMatchedEffectProjection:
    if type(value) is not MatchedEffectObservation:
        _structural("matched_effect", "expected MatchedEffectObservation")
    return _checked_scientific_projection(
        RunMatchedEffectProjection(
            value.available_sequence,
            value.comparison_group_id,
            value.created_at,
            value.effect_id,
            _project_float(value.observed_effect, "matched_effect.observed_effect"),
            project_provenance(value.provenance),
            value.source_ids,
            value.source_kind,
        ),
        validate_science=validate_science,
    )


def project_matched_effect(value: MatchedEffectObservation) -> RunMatchedEffectProjection:
    return _project_matched_effect(value, validate_science=True)


def _project_optional_float(value: float | None, path: str) -> str | None:
    return None if value is None else _project_float(value, path)


def _project_sigma_estimate(
    value: SigmaEstimate,
    *,
    validate_science: bool,
) -> RunSigmaEstimateProjection:
    if type(value) is not SigmaEstimate:
        _structural("sigma_estimate", "expected SigmaEstimate")
    path = "sigma_estimate"
    values = (
        value.belief_model_id,
        value.belief_model_version,
        value.comparison_group_id,
        value.created_at,
        value.current_evidence_excluded,
        value.cutoff_sequence,
        _project_float(value.estimated_sigma, f"{path}.estimated_sigma"),
        value.estimate_id,
        value.estimator_version,
        value.evidence_id,
        value.lineage_id,
        project_provenance(value.provenance),
        _project_optional_float(
            value.raw_sample_standard_deviation,
            f"{path}.raw_sample_standard_deviation",
        ),
        value.sample_count,
        _project_optional_float(value.sample_mean, f"{path}.sample_mean"),
        _project_float(value.sigma_floor, f"{path}.sigma_floor"),
        value.source_effect_ids,
        value.status,
        _project_float(value.variance_floor, f"{path}.variance_floor"),
    )
    return _checked_scientific_projection(
        RunSigmaEstimateProjection(*values),
        validate_science=validate_science,
    )


def project_sigma_estimate(value: SigmaEstimate) -> RunSigmaEstimateProjection:
    return _project_sigma_estimate(value, validate_science=True)


def project_model_belief_state(value: ModelBeliefState) -> RunModelBeliefStateProjection:
    if type(value) is not ModelBeliefState:
        _structural("model_belief_state", "expected ModelBeliefState")
    return _checked_projection(
        RunModelBeliefStateProjection(
            value.belief_model_id,
            value.belief_model_version,
            value.lineage_id,
            project_belief_state(value.state),
        )
    )


def project_lineage(value: BeliefModelLineage) -> RunLineageProjection:
    if type(value) is not BeliefModelLineage:
        _structural("lineage", "expected BeliefModelLineage")
    return _checked_projection(
        RunLineageProjection(
            value.belief_model_id,
            value.belief_model_version,
            value.created_at,
            project_model_belief_state(value.current_state),
            value.lineage_id,
            value.lineage_key,
        )
    )


def project_predictive_interval(value: PredictiveInterval) -> RunPredictiveIntervalProjection:
    if type(value) is not PredictiveInterval:
        _structural("predictive_interval", "expected PredictiveInterval")
    return _checked_projection(
        RunPredictiveIntervalProjection(
            value.contains_observation,
            _project_float(value.lower, "predictive_interval.lower"),
            _project_float(value.probability, "predictive_interval.probability"),
            _project_float(value.upper, "predictive_interval.upper"),
        )
    )


def _project_diagnostic(
    value: ModelAdequacyDiagnostic,
    *,
    validate_science: bool,
) -> RunDiagnosticProjection:
    if type(value) is not ModelAdequacyDiagnostic:
        _structural("diagnostic", "expected ModelAdequacyDiagnostic")
    path = "diagnostic"

    def project_residual(
        pair: tuple[str, float],
        pair_path: str,
    ) -> tuple[str, str]:
        if type(pair) is not tuple or len(pair) != 2:
            _structural(pair_path, "residual must be an exact two-element tuple")
        return _id(pair[0], f"{pair_path}[0]"), _project_float(
            pair[1],
            f"{pair_path}[1]",
        )

    residuals = _projected_items(
        value.per_hypothesis_residuals,
        f"{path}.per_hypothesis_residuals",
        project_residual,
    )
    central_intervals = _projected_items(
        value.central_intervals,
        f"{path}.central_intervals",
        lambda item, _: project_predictive_interval(item),
    )
    values = (
        value.adequacy_state,
        value.belief_model_id,
        value.belief_model_version,
        value.belief_state_before_id,
        central_intervals,
        value.comparison_group_id,
        value.created_at,
        value.diagnostic_id,
        value.diagnostic_version,
        value.diagnostics_disagree,
        value.evidence_id,
        value.lineage_id,
        residuals,
        _project_float(
            value.posterior_predictive_tail_probability,
            f"{path}.posterior_predictive_tail_probability",
        ),
        _project_float(value.predictive_cdf, f"{path}.predictive_cdf"),
        _project_float(value.predictive_density, f"{path}.predictive_density"),
        _project_float(value.predictive_log_likelihood, f"{path}.predictive_log_likelihood"),
        _project_float(value.predictive_mean, f"{path}.predictive_mean"),
        _project_float(value.predictive_variance, f"{path}.predictive_variance"),
        project_provenance(value.provenance),
        value.repeated_residual_alarm,
        value.residual_count,
        value.residual_outlier,
        value.rolling_residual_outlier_count,
        value.sigma_estimate_id,
        _project_float(value.standardized_residual, f"{path}.standardized_residual"),
        value.tail_alarm,
    )
    return _checked_scientific_projection(
        RunDiagnosticProjection(*values),
        validate_science=validate_science,
    )


def project_diagnostic(value: ModelAdequacyDiagnostic) -> RunDiagnosticProjection:
    return _project_diagnostic(value, validate_science=True)


def _project_model_update(
    value: ModelBeliefUpdate,
    *,
    validate_science: bool,
) -> RunModelUpdateProjection:
    if type(value) is not ModelBeliefUpdate:
        _structural("model_update", "expected ModelBeliefUpdate")
    return _checked_scientific_projection(
        RunModelUpdateProjection(
            project_belief_update(value.bayesian_update),
            value.belief_model_id,
            value.belief_model_version,
            value.created_at,
            _project_diagnostic(
                value.diagnostic,
                validate_science=validate_science,
            ),
            project_evidence(value.evidence),
            value.lineage_id,
            value.model_update_id,
            project_model_belief_state(value.posterior_state),
            project_provenance(value.provenance),
            _project_sigma_estimate(
                value.sigma_estimate,
                validate_science=validate_science,
            ),
            project_model_belief_state(value.state_before),
        ),
        validate_science=validate_science,
    )


def project_model_update(value: ModelBeliefUpdate) -> RunModelUpdateProjection:
    return _project_model_update(value, validate_science=True)


def project_control_value(value: DomainControlValue) -> ControlValueProjection:
    if type(value) is int:
        return _checked_projection(
            ControlValueProjection("i64", _i64(value, "control_value.value"))
        )
    if type(value) is float:
        encoded = _project_float(value, "control_value.value")
        return _checked_projection(ControlValueProjection("f64", encoded))
    if type(value) is str:
        text = _string(value, "control_value.value")
        return _checked_projection(ControlValueProjection("string", text))
    _structural("control_value", "unsupported controlled-variable value type")


def _project_controlled_variables(
    value: object, path: str
) -> tuple[tuple[str, ControlValueProjection], ...]:
    if type(value) is not tuple:
        _structural(path, "expected an exact tuple")
    result: list[tuple[str, ControlValueProjection]] = []
    for i, raw_pair in enumerate(value):
        pair_path = f"{path}[{i}]"
        if type(raw_pair) is not tuple or len(raw_pair) != 2:
            _structural(pair_path, "controlled variable must be an exact two-element tuple")
        name = _string(raw_pair[0], f"{pair_path}[0]")
        result.append((name, project_control_value(raw_pair[1])))
    return tuple(result)


def project_public_experiment_design(
    value: PublicExperimentDesign,
) -> RunPublicExperimentDesignProjection:
    if type(value) is not PublicExperimentDesign:
        _structural("public_experiment_design", "expected PublicExperimentDesign")
    path = "public_experiment_design"
    controlled = _project_controlled_variables(
        value.controlled_variables, f"{path}.controlled_variables"
    )
    return _checked_projection(
        RunPublicExperimentDesignProjection(
            value.candidate_id,
            value.comparison_group_id,
            controlled,
            value.experiment_family,
            value.intervention_arm,
            value.intervention_variable,
        )
    )


def project_hypothesis_decision_context(
    value: HypothesisDecisionContext,
) -> RunHypothesisDecisionContextProjection:
    if type(value) is not HypothesisDecisionContext:
        _structural("hypothesis_decision_context", "expected HypothesisDecisionContext")
    path = "hypothesis_decision_context"
    return _checked_projection(
        RunHypothesisDecisionContextProjection(
            value.hypothesis_id,
            _project_float(value.most_favorable_outcome, f"{path}.most_favorable_outcome"),
            value.most_favorable_outcome_label,
            _project_float(value.posterior_if_observed, f"{path}.posterior_if_observed"),
            _project_float(value.posterior_probability, f"{path}.posterior_probability"),
            value.statement,
        )
    )


def project_candidate_score(value: CandidateScore) -> RunCandidateScoreProjection:
    if type(value) is not CandidateScore:
        _structural("candidate_score", "expected CandidateScore")
    path = "candidate_score"
    return _checked_projection(
        RunCandidateScoreProjection(
            project_candidate(value.candidate),
            value.completes_matched_pair,
            _project_float(value.estimated_cost, f"{path}.estimated_cost"),
            _project_float(
                value.expected_information_gain,
                f"{path}.expected_information_gain",
            ),
            _project_float(
                value.expected_posterior_entropy,
                f"{path}.expected_posterior_entropy",
            ),
            value.matched_experiment_id,
            _project_float(value.prior_entropy, f"{path}.prior_entropy"),
            value.ranking_reason,
            value.score_reason,
        )
    )


def project_decision_trace(value: DecisionTrace) -> RunDecisionTraceProjection:
    if type(value) is not DecisionTrace:
        _structural("decision_trace", "expected DecisionTrace")
    path = "decision_trace"
    hypotheses = _projected_items(
        value.hypotheses,
        f"{path}.hypotheses",
        lambda item, _: project_hypothesis_decision_context(item),
    )
    ranked = _projected_items(
        value.ranked_candidates,
        f"{path}.ranked_candidates",
        lambda item, _: project_candidate_score(item),
    )
    return _checked_projection(
        RunDecisionTraceProjection(
            value.belief_state_id,
            value.created_at,
            value.fallback_reason,
            hypotheses,
            _project_float(value.max_cost, f"{path}.max_cost"),
            value.policy,
            value.policy_version,
            project_provenance(value.provenance),
            ranked,
            value.rationale,
            project_candidate_score(value.selected),
            value.suggestion_id,
        )
    )


def _project_probability_pairs(value: object, path: str) -> tuple[tuple[str, str], ...]:
    if type(value) is not tuple:
        _structural(path, "expected an exact tuple")
    result: list[tuple[str, str]] = []
    for i, raw_pair in enumerate(value):
        pair_path = f"{path}[{i}]"
        if type(raw_pair) is not tuple or len(raw_pair) != 2:
            _structural(pair_path, "probability must be an exact two-element tuple")
        result.append(
            (
                _id(raw_pair[0], f"{pair_path}[0]"),
                _project_float(raw_pair[1], f"{pair_path}[1]"),
            )
        )
    return tuple(result)


def _lf64(value: object, path: str, field: str) -> str:
    """Project one named Lookahead F64 field."""

    return _project_float(value, f"{path}.{field}")


def _project_lookahead_second_action(
    value: LookaheadSecondAction,
    *,
    validate_science: bool,
) -> RunLookaheadSecondActionProjection:
    if type(value) is not LookaheadSecondAction:
        _structural("lookahead_second_action", "expected LookaheadSecondAction")
    path = "lookahead_second_action"
    candidate = None if value.candidate is None else project_candidate(value.candidate)
    action_effect = (
        _public_action_effect(value.action_effect, f"{path}.action_effect")
        if validate_science
        else cast(
            PublicActionEffect,
            _string(value.action_effect, f"{path}.action_effect"),
        )
    )
    return _checked_scientific_projection(
        RunLookaheadSecondActionProjection(
            action_effect,
            candidate,
            _lf64(value.estimated_cost, path, "estimated_cost"),
            _lf64(value.expected_information_gain, path, "expected_information_gain"),
            _lf64(value.information_gain_per_cost, path, "information_gain_per_cost"),
            value.reason,
        ),
        validate_science=validate_science,
    )


def project_lookahead_second_action(
    value: LookaheadSecondAction,
) -> RunLookaheadSecondActionProjection:
    return _project_lookahead_second_action(value, validate_science=True)


def _validate_evidence_bound_coupling(projection: RunLookaheadBranchProjection) -> None:
    no_evidence_id = projection.branch_id == NO_EVIDENCE_BRANCH_ID
    no_evidence_label = projection.label == NO_EVIDENCE_BRANCH_LABEL
    both_missing = (
        projection.evidence_lower_bound is None and projection.evidence_upper_bound is None
    )
    if no_evidence_id != no_evidence_label:
        _scientific("lookahead_branch", "no-evidence branch ID and label do not couple")
    if no_evidence_id != both_missing:
        _scientific("lookahead_branch", "branch identity and evidence bounds do not couple")


def _project_lookahead_branch(
    value: LookaheadBranch,
    *,
    validate_science: bool,
) -> RunLookaheadBranchProjection:
    if type(value) is not LookaheadBranch:
        _structural("lookahead_branch", "expected LookaheadBranch")
    path = "lookahead_branch"
    projection = _checked_scientific_projection(
        RunLookaheadBranchProjection(
            value.branch_id,
            _lf64(value.branch_total_cost, path, "branch_total_cost"),
            value.budget_feasible,
            _project_optional_float(value.evidence_lower_bound, f"{path}.evidence_lower_bound"),
            _project_optional_float(value.evidence_upper_bound, f"{path}.evidence_upper_bound"),
            value.label,
            _lf64(value.posterior_entropy, path, "posterior_entropy"),
            _project_probability_pairs(
                value.posterior_probabilities,
                f"{path}.posterior_probabilities",
            ),
            _lf64(value.probability, path, "probability"),
            _project_lookahead_second_action(
                value.second_action,
                validate_science=validate_science,
            ),
            _lf64(value.terminal_entropy, path, "terminal_entropy"),
        ),
        validate_science=validate_science,
    )
    if validate_science:
        _validate_evidence_bound_coupling(projection)
    return projection


def project_lookahead_branch(value: LookaheadBranch) -> RunLookaheadBranchProjection:
    return _project_lookahead_branch(value, validate_science=True)


def _project_lookahead_first_action(
    value: LookaheadFirstActionPlan,
    *,
    validate_science: bool,
) -> RunLookaheadFirstActionProjection:
    if type(value) is not LookaheadFirstActionPlan:
        _structural("lookahead_first_action", "expected LookaheadFirstActionPlan")
    path = "lookahead_first_action"
    branches = _projected_items(
        value.branches,
        f"{path}.branches",
        lambda item, _: _project_lookahead_branch(
            item,
            validate_science=validate_science,
        ),
    )
    action_effect = (
        _non_stop_public_action_effect(value.action_effect, f"{path}.action_effect")
        if validate_science
        else cast(
            NonStopPublicActionEffect,
            _string(value.action_effect, f"{path}.action_effect"),
        )
    )
    return _checked_scientific_projection(
        RunLookaheadFirstActionProjection(
            action_effect,
            branches,
            project_candidate(value.candidate),
            _lf64(value.expected_terminal_entropy, path, "expected_terminal_entropy"),
            _lf64(value.expected_total_cost, path, "expected_total_cost"),
            _lf64(
                value.expected_total_information_gain,
                path,
                "expected_total_information_gain",
            ),
            _lf64(value.first_action_cost, path, "first_action_cost"),
            _lf64(value.immediate_information_gain, path, "immediate_information_gain"),
            _lf64(
                value.information_gain_per_expected_cost,
                path,
                "information_gain_per_expected_cost",
            ),
            _lf64(value.prior_entropy, path, "prior_entropy"),
            project_public_experiment_design(value.public_design),
            value.ranking_reason,
        ),
        validate_science=validate_science,
    )


def project_lookahead_first_action(
    value: LookaheadFirstActionPlan,
) -> RunLookaheadFirstActionProjection:
    return _project_lookahead_first_action(value, validate_science=True)


def _project_lookahead_alternative(
    value: LookaheadAlternative,
    *,
    validate_science: bool,
) -> RunLookaheadAlternativeProjection:
    if type(value) is not LookaheadAlternative:
        _structural("lookahead_alternative", "expected LookaheadAlternative")
    path = "lookahead_alternative"
    action_effect = (
        _non_stop_public_action_effect(value.action_effect, f"{path}.action_effect")
        if validate_science
        else cast(
            NonStopPublicActionEffect,
            _string(value.action_effect, f"{path}.action_effect"),
        )
    )
    return _checked_scientific_projection(
        RunLookaheadAlternativeProjection(
            action_effect,
            project_candidate(value.candidate),
            value.comparison_group_id,
            _lf64(value.expected_total_cost, path, "expected_total_cost"),
            _lf64(
                value.expected_total_information_gain,
                path,
                "expected_total_information_gain",
            ),
            _lf64(value.immediate_information_gain, path, "immediate_information_gain"),
            _lf64(
                value.information_gain_per_expected_cost,
                path,
                "information_gain_per_expected_cost",
            ),
            value.ranking_reason,
        ),
        validate_science=validate_science,
    )


def project_lookahead_alternative(
    value: LookaheadAlternative,
) -> RunLookaheadAlternativeProjection:
    return _project_lookahead_alternative(value, validate_science=True)


def _project_lookahead_trace(
    value: LookaheadPlanTrace,
    *,
    validate_science: bool,
) -> RunLookaheadTraceProjection:
    if type(value) is not LookaheadPlanTrace:
        _structural("lookahead_trace", "expected LookaheadPlanTrace")
    path = "lookahead_trace"
    alternatives = _projected_items(
        value.alternatives,
        f"{path}.alternatives",
        lambda item, _: _project_lookahead_alternative(
            item,
            validate_science=validate_science,
        ),
    )
    probabilities = _project_probability_pairs(
        value.current_hypothesis_probabilities,
        f"{path}.current_hypothesis_probabilities",
    )
    tie_breaking = _projected_items(
        value.tie_breaking_order,
        f"{path}.tie_breaking_order",
        _string,
    )
    return _checked_scientific_projection(
        RunLookaheadTraceProjection(
            alternatives,
            value.belief_state_id,
            value.candidate_set_fingerprint,
            value.completed_state_fingerprint,
            value.created_at,
            probabilities,
            value.fallback_reason,
            _lf64(value.max_cost, path, "max_cost"),
            value.plan_id,
            value.policy,
            value.policy_version,
            project_provenance(value.provenance),
            value.rationale,
            _project_lookahead_first_action(
                value.selected,
                validate_science=validate_science,
            ),
            tie_breaking,
        ),
        validate_science=validate_science,
    )


def project_lookahead_trace(value: LookaheadPlanTrace) -> RunLookaheadTraceProjection:
    return _project_lookahead_trace(value, validate_science=True)


def _project_policy_trace(
    value: DecisionTrace | LookaheadPlanTrace,
    *,
    validate_science: bool,
) -> RunPolicyTraceProjection:
    if type(value) is DecisionTrace:
        return _checked_scientific_projection(
            RunPolicyTraceProjection("decision_trace", project_decision_trace(value)),
            validate_science=validate_science,
        )
    if type(value) is LookaheadPlanTrace:
        return _checked_scientific_projection(
            RunPolicyTraceProjection(
                "lookahead_plan_trace",
                _project_lookahead_trace(
                    value,
                    validate_science=validate_science,
                ),
            ),
            validate_science=validate_science,
        )
    _structural("policy_trace", "expected DecisionTrace or LookaheadPlanTrace")


def project_policy_trace(value: DecisionTrace | LookaheadPlanTrace) -> RunPolicyTraceProjection:
    return _project_policy_trace(value, validate_science=True)


def _validate_unique_ids(values: tuple[str, ...], path: str) -> None:
    if len(values) != len(set(values)):
        _scientific(path, "IDs must be unique in recorded order")


def _validate_arm_decision_projection(
    projection: RunArmDecisionProjection,
    trace: DecisionTrace | LookaheadPlanTrace,
) -> None:
    path = "arm_decision"
    remaining = _float_from_f64(projection.remaining_budget, f"{path}.remaining_budget")
    if projection.step < 1:
        _scientific(f"{path}.step", "decision steps are one-based")
    if remaining < 0.0:
        _scientific(f"{path}.remaining_budget", "remaining budget must be non-negative")
    public_path = f"{path}.public_feasible_candidate_ids"
    affordable_path = f"{path}.affordable_candidate_ids"
    _validate_unique_ids(projection.public_feasible_candidate_ids, public_path)
    _validate_unique_ids(projection.affordable_candidate_ids, affordable_path)
    public_positions = {
        candidate_id: index
        for index, candidate_id in enumerate(projection.public_feasible_candidate_ids)
    }
    try:
        affordable_positions = tuple(
            public_positions[candidate_id] for candidate_id in projection.affordable_candidate_ids
        )
    except KeyError:
        _scientific(affordable_path, "affordable candidates are not all publicly feasible")
    if affordable_positions != tuple(sorted(affordable_positions)):
        _scientific(affordable_path, "affordable candidates changed public feasible order")
    if projection.selected_candidate_id not in projection.affordable_candidate_ids:
        _scientific(f"{path}.selected_candidate_id", "selected candidate is not affordable")
    if trace.candidate.candidate_id != projection.selected_candidate_id:
        _scientific(f"{path}.policy_trace", "policy trace selected a different candidate")
    if trace.belief_state_id != projection.belief_state_id:
        _scientific(f"{path}.policy_trace", "policy trace used a different belief state")
    if not _same_f64(trace.max_cost, remaining, f"{path}.remaining_budget"):
        _scientific(f"{path}.policy_trace", "policy trace used a different remaining budget")


def _project_revealed_observation(
    value: RevealedObservation,
    authorization: RunObservationAuthorizationProjection | None,
    *,
    calibration_prefix_id: str | None = None,
    expected_run_id: str | None = None,
    validate_science: bool,
) -> RunRevealedObservationProjection:
    if type(value) is not RevealedObservation:
        _structural("revealed_observation", "expected RevealedObservation")
    if authorization is None:
        if calibration_prefix_id is None or expected_run_id is None:
            _missing_context("revealed_observation.authorization")
        authorization = _calibration_authorization(
            value,
            calibration_prefix_id=calibration_prefix_id,
            expected_run_id=expected_run_id,
        )
    if type(authorization) is not RunObservationAuthorizationProjection:
        _structural("revealed_observation.authorization", "expected authorization projection")
    projection = _checked_projection(
        RunRevealedObservationProjection(
            authorization,
            value.authorization_id,
            value.candidate_id,
            value.comparison_group_id,
            value.digest,
            value.intervention_arm,
            value.key_fields,
            value.namespace,
            value.oracle_key_id,
            value.oracle_use_id,
            value.outcome_digest,
            value.replication_id,
            _project_float(
                value.revealed_observation,
                "revealed_observation.revealed_observation",
            ),
            value.seed,
            value.serialized_key_hex,
            value.u,
            value.world_id,
            value.z,
        )
    )
    if validate_science:
        validate_revealed_observation_projection(projection)
    return projection


def _calibration_authorization(
    observation: RevealedObservation,
    *,
    calibration_prefix_id: str,
    expected_run_id: str,
) -> RunObservationAuthorizationProjection:
    run_id = _id(expected_run_id, "expected_run_id")
    candidate_id = _id(observation.candidate_id, "calibration_observation.candidate_id")
    prefix = _id(calibration_prefix_id, "calibration_estimate.calibration_prefix_id")
    return _checked_projection(
        RunObservationAuthorizationProjection(
            candidate_id,
            "calibration",
            run_id,
            f"{prefix}/{candidate_id}",
        )
    )


def _calibration_run_id(
    observations: tuple[RunRevealedObservationProjection, ...],
    *,
    path: str,
) -> str:
    if not observations:
        _scientific(path, "calibration observations are required")
    run_id = observations[0].authorization.run_id
    if any(item.authorization.run_id != run_id for item in observations[1:]):
        _scientific(path, "calibration observations cross run identities")
    return run_id


def _validate_calibration_estimate_projection(
    projection: RunCalibrationEstimateProjection,
    effects: tuple[MatchedEffectObservation, ...],
    observations: tuple[RevealedObservation, ...],
) -> None:
    path = "calibration_estimate"
    if len(effects) != 5 or projection.sample_count != len(effects):
        _scientific(f"{path}.sample_count", "calibration sample cardinality differs")
    if len(observations) != 2 * len(effects):
        _scientific(f"{path}.observations", "calibration observation cardinality differs")
    if projection.ddof != CALIBRATION_SIGMA_DDOF:
        _scientific(f"{path}.ddof", "calibration estimator ddof differs")
    if projection.source_sequence_cutoff != CALIBRATION_SOURCE_SEQUENCE_CUTOFF:
        _scientific(f"{path}.source_sequence_cutoff", "calibration cutoff differs")
    if projection.belief_model_id != CALIBRATED_SIGMA_MODEL_ID:
        _scientific(f"{path}.belief_model_id", "calibration belief model differs")
    if projection.sigma_estimate_id != f"sigma-estimate/{projection.calibration_prefix_id}":
        _scientific(f"{path}.sigma_estimate_id", "calibration estimate identity differs")

    effect_ids = tuple(item.effect_id for item in effects)
    _validate_unique_ids(effect_ids, f"{path}.effects")
    if projection.source_effect_ids != effect_ids:
        _scientific(f"{path}.source_effect_ids", "ordered source effects differ")
    for index, effect in enumerate(effects):
        effect_path = f"{path}.effects[{index}]"
        if (
            effect.comparison_group_id != projection.comparison_group_id
            or effect.source_kind != "calibration"
            or effect.available_sequence >= projection.source_sequence_cutoff
        ):
            _scientific(effect_path, "calibration effect scope or chronology differs")
        if len(effect.source_ids) != 2:
            _scientific(f"{effect_path}.source_ids", "calibration effect requires one pair")

    oracle_use_ids = tuple(item.oracle_use_id for item in observations)
    _validate_unique_ids(oracle_use_ids, f"{path}.observations")
    run_id = _calibration_run_id(projection.observations, path=f"{path}.observations")
    for index, observation in enumerate(observations):
        observation_path = f"{path}.observations[{index}]"
        authorization = projection.observations[index].authorization
        if (
            authorization.kind != "calibration"
            or authorization.run_id != run_id
            or authorization.candidate_id != observation.candidate_id
            or authorization.source_id
            != f"{projection.calibration_prefix_id}/{observation.candidate_id}"
            or observation.comparison_group_id != projection.comparison_group_id
        ):
            _scientific(observation_path, "calibration observation scope differs")

    for index, effect in enumerate(effects):
        left = observations[2 * index]
        right = observations[2 * index + 1]
        effect_path = f"{path}.effects[{index}]"
        if (
            effect.source_ids != (left.candidate_id, right.candidate_id)
            or left.intervention_arm != "adam"
            or right.intervention_arm != "sgd"
            or left.replication_id != right.replication_id
        ):
            _scientific(effect_path, "calibration pair order or replication differs")
        expected_effect = round(left.revealed_observation - right.revealed_observation, 12)
        if not _same_f64(effect.observed_effect, expected_effect, f"{effect_path}.observed_effect"):
            _scientific(f"{effect_path}.observed_effect", "calibration effect value differs")

    values = tuple(item.observed_effect for item in effects)
    sample_mean = statistics.mean(values)
    sample_sd = statistics.stdev(values)
    recorded_mean = _float_from_f64(projection.sample_mean, f"{path}.sample_mean")
    recorded_sd = _float_from_f64(
        projection.raw_sample_standard_deviation,
        f"{path}.raw_sample_standard_deviation",
    )
    sigma_floor = _float_from_f64(projection.sigma_floor, f"{path}.sigma_floor")
    estimated_sigma = _float_from_f64(
        projection.estimated_sigma,
        f"{path}.estimated_sigma",
    )
    physical_cost = _float_from_f64(projection.physical_cost, f"{path}.physical_cost")
    if not _same_f64(recorded_mean, sample_mean, f"{path}.sample_mean"):
        _scientific(f"{path}.sample_mean", "calibration sample mean differs")
    if not _same_f64(recorded_sd, sample_sd, f"{path}.raw_sample_standard_deviation"):
        _scientific(
            f"{path}.raw_sample_standard_deviation",
            "calibration sample standard deviation differs",
        )
    if not _same_f64(sigma_floor, SIGMA_FLOOR, f"{path}.sigma_floor"):
        _scientific(f"{path}.sigma_floor", "calibration sigma floor differs")
    if not _same_f64(
        estimated_sigma,
        max(sample_sd, SIGMA_FLOOR),
        f"{path}.estimated_sigma",
    ):
        _scientific(f"{path}.estimated_sigma", "calibration sigma estimate differs")
    if physical_cost <= 0.0:
        _scientific(f"{path}.physical_cost", "calibration physical cost must be positive")

    try:
        provenance = calibration_sigma_provenance_sha256(
            sigma_estimate_id=projection.sigma_estimate_id,
            calibration_prefix_id=projection.calibration_prefix_id,
            comparison_group_id=projection.comparison_group_id,
            source_effect_ids=projection.source_effect_ids,
            source_sequence_cutoff=projection.source_sequence_cutoff,
            sample_count=projection.sample_count,
            sample_mean=recorded_mean,
            raw_sample_standard_deviation=recorded_sd,
            ddof=projection.ddof,
            sigma_floor=sigma_floor,
            estimated_sigma=estimated_sigma,
            belief_model_id=projection.belief_model_id,
            lineage_id=projection.lineage_id,
            effects=effects,
        )
    except (ProtocolError, ValueError) as error:
        _scientific(f"{path}.provenance_sha256", str(error))
    if projection.provenance_sha256 != provenance:
        _scientific(f"{path}.provenance_sha256", "calibration provenance differs")


def _project_calibration_estimate(
    value: CalibrationGroupEstimate,
    *,
    expected_run_id: str | None = None,
    validate_science: bool,
) -> RunCalibrationEstimateProjection:
    if type(value) is not CalibrationGroupEstimate:
        _structural("calibration_estimate", "expected CalibrationGroupEstimate")
    if expected_run_id is None:
        _missing_context("calibration_estimate.run_id")
    run_id = _id(expected_run_id, "expected_run_id")
    path = "calibration_estimate"
    effects = _projected_items(
        value.effects,
        f"{path}.effects",
        lambda item, _: _project_matched_effect(
            item,
            validate_science=validate_science,
        ),
    )
    observations = _projected_items(
        value.observations,
        f"{path}.observations",
        lambda item, _: _project_revealed_observation(
            item,
            None,
            calibration_prefix_id=value.calibration_prefix_id,
            expected_run_id=run_id,
            validate_science=validate_science,
        ),
    )
    projection = _checked_scientific_projection(
        RunCalibrationEstimateProjection(
            value.belief_model_id,
            value.calibration_prefix_id,
            value.comparison_group_id,
            value.ddof,
            effects,
            _project_float(value.estimated_sigma, f"{path}.estimated_sigma"),
            value.lineage_id,
            observations,
            _project_float(value.physical_cost, f"{path}.physical_cost"),
            value.provenance_sha256,
            _project_float(
                value.raw_sample_standard_deviation,
                f"{path}.raw_sample_standard_deviation",
            ),
            value.sample_count,
            _project_float(value.sample_mean, f"{path}.sample_mean"),
            value.sigma_estimate_id,
            _project_float(value.sigma_floor, f"{path}.sigma_floor"),
            value.source_effect_ids,
            value.source_sequence_cutoff,
        ),
        validate_science=validate_science,
    )
    if validate_science:
        _validate_calibration_estimate_projection(projection, value.effects, value.observations)
    return projection


def project_calibration_estimate(
    value: CalibrationGroupEstimate,
    *,
    expected_run_id: str | None = None,
) -> RunCalibrationEstimateProjection:
    return _project_calibration_estimate(
        value,
        expected_run_id=expected_run_id,
        validate_science=True,
    )


def _project_calibration(
    value: CalibrationDeployment,
    *,
    expected_run_id: str | None = None,
    validate_science: bool,
) -> RunCalibrationProjection:
    if type(value) is not CalibrationDeployment:
        _structural("calibration", "expected CalibrationDeployment")
    if expected_run_id is None:
        _missing_context("calibration.run_id")
    run_id = _id(expected_run_id, "expected_run_id")

    def project_observation(
        observation: RevealedObservation,
        _path: str,
    ) -> RunRevealedObservationProjection:
        if type(observation) is not RevealedObservation:
            _structural("revealed_observation", "expected RevealedObservation")
        for estimate in value.estimates:
            if any(
                type(source) is RevealedObservation
                and (
                    source.authorization_id == observation.authorization_id
                    or source.candidate_id == observation.candidate_id
                )
                for source in estimate.observations
            ):
                prefix = estimate.calibration_prefix_id
                break
        else:
            prefix = (
                value.estimates[0].calibration_prefix_id
                if value.estimates
                else "structural-calibration-prefix"
            )
        return _project_revealed_observation(
            observation,
            None,
            calibration_prefix_id=prefix,
            expected_run_id=run_id,
            validate_science=False,
        )

    estimates = _projected_items(
        value.estimates,
        "calibration.estimates",
        lambda item, _: _project_calibration_estimate(
            item,
            expected_run_id=run_id,
            validate_science=validate_science,
        ),
    )
    if validate_science:
        expected_effects = tuple(item for estimate in value.estimates for item in estimate.effects)
        expected_observations = tuple(
            item for estimate in value.estimates for item in estimate.observations
        )
        if value.effects != expected_effects:
            _scientific("calibration.effects", "deployment effects differ from estimate order")
        if value.observations != expected_observations:
            _scientific(
                "calibration.observations",
                "deployment observations differ from estimate order",
            )
        expected_cost = math.fsum(item.physical_cost for item in value.estimates)
        if not _same_f64(value.cost, expected_cost, "calibration.cost"):
            _scientific("calibration.cost", "deployment cost differs")
        effects = tuple(item for estimate in estimates for item in estimate.effects)
        observations = tuple(item for estimate in estimates for item in estimate.observations)
    else:
        effects = _projected_items(
            value.effects,
            "calibration.effects",
            lambda item, _: _project_matched_effect(
                item,
                validate_science=False,
            ),
        )
        observations = _projected_items(
            value.observations,
            "calibration.observations",
            project_observation,
        )
    return _checked_scientific_projection(
        RunCalibrationProjection(
            _project_float(value.cost, "calibration.cost"),
            effects,
            estimates,
            observations,
        ),
        validate_science=validate_science,
    )


def project_calibration(
    value: CalibrationDeployment,
    *,
    expected_run_id: str | None = None,
) -> RunCalibrationProjection:
    return _project_calibration(
        value,
        expected_run_id=expected_run_id,
        validate_science=True,
    )


def _validate_arm_action_projection(
    projection: RunArmActionProjection,
    observation: RevealedObservation | None,
) -> None:
    path = "arm_action"
    cost = _float_from_f64(projection.cost, f"{path}.cost")
    cumulative = _float_from_f64(
        projection.cumulative_decision_cost,
        f"{path}.cumulative_decision_cost",
    )
    if projection.step < 1:
        _scientific(f"{path}.step", "action steps are one-based")
    if cost < 0.0 or cumulative < 0.0:
        _scientific(f"{path}.cost", "action costs must be non-negative")
    if cost > cumulative:
        _scientific(f"{path}.cumulative_decision_cost", "cumulative cost is below action cost")
    _validate_unique_ids(projection.new_evidence_ids, f"{path}.new_evidence_ids")
    hypothesis_ids = tuple(item[0] for item in projection.posterior_probabilities)
    if not hypothesis_ids or hypothesis_ids != tuple(sorted(set(hypothesis_ids))):
        _scientific(
            f"{path}.posterior_probabilities",
            "posterior hypothesis IDs must be unique and sorted",
        )
    probabilities = _reconstruct_probability_pairs(
        projection.posterior_probabilities,
        f"{path}.posterior_probabilities",
    )
    values = tuple(item[1] for item in probabilities)
    try:
        total_probability = math.fsum(values)
    except OverflowError as error:
        _scientific(f"{path}.posterior_probabilities", str(error))
    if any(value < 0.0 for value in values) or not math.isclose(
        total_probability,
        1.0,
        rel_tol=0.0,
        abs_tol=PROBABILITY_TOLERANCE,
    ):
        _scientific(f"{path}.posterior_probabilities", "probabilities must sum to one")
    if (projection.observed_objective is None) != (projection.oracle_observation is None):
        _scientific(f"{path}.observed_objective", "outcome nullability differs from Oracle")
    if (projection.role == "setup") != (projection.observed_objective is None):
        _scientific(f"{path}.role", "setup role and outcome nullability differ")
    if projection.role == "setup" and projection.new_evidence_ids:
        _scientific(f"{path}.new_evidence_ids", "setup actions cannot create evidence")
    oracle = projection.oracle_observation
    if oracle is None:
        if observation is not None:
            _scientific(f"{path}.oracle_observation", "field-total comparison failed")
        return
    if observation is None:
        _scientific(f"{path}.oracle_observation", "field-total comparison failed")
    validate_revealed_observation_projection(oracle)
    if oracle.authorization.kind != "decision":
        auth_path = f"{path}.oracle_observation.authorization.kind"
        _scientific(auth_path, "arm actions require a decision authorization")
    relations = (
        (oracle.candidate_id, projection.candidate_id, "candidate_id"),
        (oracle.authorization.candidate_id, projection.candidate_id, "authorization.candidate_id"),
        (oracle.authorization.source_id, projection.decision_id, "authorization.source_id"),
    )
    for actual, expected, field in relations:
        if actual != expected:
            _scientific(f"{path}.oracle_observation.{field}", "Oracle/action relation differs")
    if projection.observed_objective != oracle.revealed_observation:
        _scientific(f"{path}.observed_objective", "revealed observation differs")


def _project_arm_decision(
    value: ArmDecision,
    *,
    validate_science: bool,
) -> RunArmDecisionProjection:
    if type(value) is not ArmDecision:
        _structural("arm_decision", "expected ArmDecision")
    path = "arm_decision"
    projection = _checked_scientific_projection(
        RunArmDecisionProjection(
            _projected_items(
                value.affordable_candidate_ids, f"{path}.affordable_candidate_ids", _id
            ),
            value.belief_state_id,
            value.decision_id,
            value.fixed_policy_regression_match,
            _project_policy_trace(
                value.policy_trace,
                validate_science=validate_science,
            ),
            _projected_items(
                value.public_feasible_candidate_ids,
                f"{path}.public_feasible_candidate_ids",
                _id,
            ),
            _project_float(value.remaining_budget, f"{path}.remaining_budget"),
            value.selected_candidate_id,
            value.step,
        ),
        validate_science=validate_science,
    )
    if validate_science:
        _validate_arm_decision_projection(projection, value.policy_trace)
    return projection


def project_arm_decision(value: ArmDecision) -> RunArmDecisionProjection:
    return _project_arm_decision(value, validate_science=True)


def _project_arm_action(
    value: ArmAction,
    authorization: RunObservationAuthorizationProjection | None,
    *,
    expected_run_id: str | None = None,
    validate_science: bool,
) -> RunArmActionProjection:
    if type(value) is not ArmAction:
        _structural("arm_action", "expected ArmAction")
    path = "arm_action"
    observation = value.oracle_observation
    if observation is not None and authorization is None:
        if expected_run_id is None:
            _missing_context(f"{path}.oracle_observation.authorization.run_id")
        authorization = _checked_projection(
            RunObservationAuthorizationProjection(
                value.candidate_id,
                "decision",
                _id(expected_run_id, "expected_run_id"),
                value.decision_id,
            )
        )
    elif observation is None and expected_run_id is not None:
        _id(expected_run_id, "expected_run_id")
    if (observation is None) != (authorization is None):
        _missing_context(f"{path}.oracle_observation.authorization")
    oracle = (
        None
        if observation is None or authorization is None
        else _project_revealed_observation(
            observation,
            authorization,
            validate_science=validate_science,
        )
    )
    projection = _checked_scientific_projection(
        RunArmActionProjection(
            value.candidate_id,
            _project_float(value.cost, f"{path}.cost"),
            _project_float(
                value.cumulative_decision_cost,
                f"{path}.cumulative_decision_cost",
            ),
            value.decision_id,
            _projected_items(value.new_evidence_ids, f"{path}.new_evidence_ids", _id),
            _project_optional_float(value.observed_objective, f"{path}.observed_objective"),
            oracle,
            _project_probability_pairs(
                value.posterior_probabilities,
                f"{path}.posterior_probabilities",
            ),
            value.role,
            value.step,
        ),
        validate_science=validate_science,
    )
    if validate_science:
        _validate_arm_action_projection(projection, observation)
    return projection


def project_arm_action(
    value: ArmAction,
    *,
    expected_run_id: str | None = None,
) -> RunArmActionProjection:
    return _project_arm_action(
        value,
        None,
        expected_run_id=expected_run_id,
        validate_science=True,
    )


def _project_returned_run(
    value: BroaderArmRun,
    *,
    validate_science: bool,
) -> ReturnedRunProjection:
    if type(value) is not BroaderArmRun:
        _structural("returned_run", "expected BroaderArmRun")
    actions = _projected_items(
        value.actions,
        "returned_run.actions",
        lambda item, _: _project_arm_action(
            item,
            None,
            expected_run_id=value.run_id,
            validate_science=validate_science,
        ),
    )
    if type(value.arm) is not FrozenArm:
        _structural("returned_run.arm", "expected FrozenArm")
    arm: RunArmValue = (
        _id(value.arm.arm_id, "returned_run.arm.arm_id"),
        _i64(value.arm.arm_order, "returned_run.arm.arm_order"),
        _id(value.arm.belief_model_id, "returned_run.arm.belief_model_id"),
        _id(value.arm.policy_id, "returned_run.arm.policy_id"),
    )
    projection = ReturnedRunProjection(
        actions,
        arm,
        _project_float(value.budget, "returned_run.budget"),
        _id(value.budget_id, "returned_run.budget_id"),
        (
            None
            if value.calibration is None
            else _project_calibration(
                value.calibration,
                expected_run_id=value.run_id,
                validate_science=validate_science,
            )
        ),
        _project_float(
            value.calibration_cost,
            "returned_run.calibration_cost",
        ),
        _id(value.comparison_id, "returned_run.comparison_id"),
        _projected_items(
            value.completed_experiments,
            "returned_run.completed_experiments",
            lambda item, _: project_completed_experiment(item),
        ),
        _project_float(value.decision_cost, "returned_run.decision_cost"),
        _projected_items(
            value.decisions,
            "returned_run.decisions",
            lambda item, _: _project_arm_decision(
                item,
                validate_science=validate_science,
            ),
        ),
        _projected_items(
            value.diagnostics,
            "returned_run.diagnostics",
            lambda item, _: _project_diagnostic(
                item,
                validate_science=validate_science,
            ),
        ),
        _projected_items(
            value.effect_history,
            "returned_run.effect_history",
            lambda item, _: _project_matched_effect(
                item,
                validate_science=validate_science,
            ),
        ),
        _projected_items(
            value.evidence,
            "returned_run.evidence",
            lambda item, _: project_evidence(item),
        ),
        _project_probability_pairs(
            value.initial_probabilities,
            "returned_run.initial_probabilities",
        ),
        project_lineage(value.lineage),
        _id(value.run_id, "returned_run.run_id"),
        cast(
            Literal["complete", "invalid"],
            _string(value.run_status, "returned_run.run_status"),
        ),
        "broader-replication-returned-run/v1",
        _i64(value.seed, "returned_run.seed"),
        _id(value.terminal_reason, "returned_run.terminal_reason"),
        _projected_items(
            value.updates,
            "returned_run.updates",
            lambda item, _: _project_model_update(
                item,
                validate_science=validate_science,
            ),
        ),
        _id(value.world_id, "returned_run.world_id"),
    )
    return _checked_scientific_projection(
        projection,
        validate_science=validate_science,
    )


def project_returned_run(value: BroaderArmRun) -> ReturnedRunProjection:
    """Project one complete scientific run without adding an identity."""

    return _project_returned_run(value, validate_science=True)


def decode_run_provenance_projection(value: object) -> RunProvenanceProjection:
    parsed = _closed_dict(value, ("details", "method", "version"), "provenance")
    details: list[tuple[str, ProvenanceValueProjection]] = []
    for i, raw_pair in enumerate(_list(parsed["details"], "provenance.details")):
        path = f"provenance.details[{i}]"
        pair = _list(raw_pair, path)
        if len(pair) != 2:
            _structural(path, "detail must be a two-element pair")
        key = _string(pair[0], f"{path}[0]")
        details.append((key, decode_provenance_value_projection(pair[1])))
    method = _string(parsed["method"], "provenance.method")
    version = _string(parsed["version"], "provenance.version")
    return RunProvenanceProjection(tuple(details), method, version)


def decode_run_candidate_projection(value: object) -> RunCandidateProjection:
    return _decode_flat(value, "candidate", _CANDIDATE_SCHEMA, RunCandidateProjection)


def decode_run_completed_experiment_projection(
    value: object,
) -> RunCompletedExperimentProjection:
    return _decode_flat(
        value, "completed_experiment", _EXPERIMENT_SCHEMA, RunCompletedExperimentProjection
    )


def decode_run_evidence_projection(value: object) -> RunEvidenceProjection:
    return _decode_flat(value, "evidence", _EVIDENCE_SCHEMA, RunEvidenceProjection)


def decode_run_belief_state_projection(value: object) -> RunBeliefStateProjection:
    return _decode_flat(value, "belief_state", _BELIEF_SCHEMA, RunBeliefStateProjection)


def decode_run_hypothesis_likelihood_projection(
    value: object,
) -> RunHypothesisLikelihoodProjection:
    return _decode_flat(
        value,
        "hypothesis_likelihood",
        _LIKELIHOOD_SCHEMA,
        RunHypothesisLikelihoodProjection,
    )


def decode_run_belief_update_projection(value: object) -> RunBeliefUpdateProjection:
    return _decode_flat(value, "belief_update", _UPDATE_SCHEMA, RunBeliefUpdateProjection)


def decode_run_matched_effect_projection(value: object) -> RunMatchedEffectProjection:
    return _decode_flat(value, "matched_effect", _MATCHED_EFFECT_SCHEMA, RunMatchedEffectProjection)


def decode_run_sigma_estimate_projection(value: object) -> RunSigmaEstimateProjection:
    return _decode_flat(value, "sigma_estimate", _SIGMA_ESTIMATE_SCHEMA, RunSigmaEstimateProjection)


def decode_run_model_belief_state_projection(value: object) -> RunModelBeliefStateProjection:
    return _decode_flat(
        value,
        "model_belief_state",
        _MODEL_BELIEF_STATE_SCHEMA,
        RunModelBeliefStateProjection,
    )


def decode_run_lineage_projection(value: object) -> RunLineageProjection:
    return _decode_flat(value, "lineage", _LINEAGE_SCHEMA, RunLineageProjection)


def decode_run_predictive_interval_projection(
    value: object,
) -> RunPredictiveIntervalProjection:
    return _decode_flat(
        value,
        "predictive_interval",
        _PREDICTIVE_INTERVAL_SCHEMA,
        RunPredictiveIntervalProjection,
    )


def decode_run_diagnostic_projection(value: object) -> RunDiagnosticProjection:
    return _decode_flat(value, "diagnostic", _DIAGNOSTIC_SCHEMA, RunDiagnosticProjection)


def decode_run_model_update_projection(value: object) -> RunModelUpdateProjection:
    return _decode_flat(value, "model_update", _MODEL_UPDATE_SCHEMA, RunModelUpdateProjection)


def decode_run_observation_authorization_projection(
    value: object,
) -> RunObservationAuthorizationProjection:
    return _decode_flat(
        value,
        "observation_authorization",
        _OBSERVATION_AUTHORIZATION_SCHEMA,
        RunObservationAuthorizationProjection,
    )


def decode_run_revealed_observation_projection(
    value: object,
) -> RunRevealedObservationProjection:
    return _decode_flat(
        value,
        "revealed_observation",
        _REVEALED_OBSERVATION_SCHEMA,
        RunRevealedObservationProjection,
    )


def decode_run_calibration_estimate_projection(
    value: object,
) -> RunCalibrationEstimateProjection:
    return _decode_flat(
        value,
        "calibration_estimate",
        _CALIBRATION_ESTIMATE_SCHEMA,
        RunCalibrationEstimateProjection,
    )


def decode_run_calibration_projection(value: object) -> RunCalibrationProjection:
    return _decode_flat(
        value,
        "calibration",
        _CALIBRATION_SCHEMA,
        RunCalibrationProjection,
    )


def decode_control_value_projection(value: object) -> ControlValueProjection:
    parsed = _closed_dict(value, ("kind", "value"), "control_value")
    kind = _string(parsed["kind"], "control_value.kind")
    raw = parsed["value"]
    if kind == "i64":
        return ControlValueProjection("i64", _i64(raw, "control_value.value"))
    if kind == "f64":
        return ControlValueProjection("f64", _f64_text(raw, "control_value.value"))
    if kind == "string":
        return ControlValueProjection("string", _string(raw, "control_value.value"))
    _structural("control_value.kind", "unknown controlled-variable value kind")


def decode_run_public_experiment_design_projection(
    value: object,
) -> RunPublicExperimentDesignProjection:
    return _decode_flat(
        value,
        "public_experiment_design",
        _PUBLIC_DESIGN_SCHEMA,
        RunPublicExperimentDesignProjection,
    )


def decode_run_hypothesis_decision_context_projection(
    value: object,
) -> RunHypothesisDecisionContextProjection:
    return _decode_flat(
        value,
        "hypothesis_decision_context",
        _HYPOTHESIS_DECISION_CONTEXT_SCHEMA,
        RunHypothesisDecisionContextProjection,
    )


def decode_run_candidate_score_projection(value: object) -> RunCandidateScoreProjection:
    return _decode_flat(
        value, "candidate_score", _CANDIDATE_SCORE_SCHEMA, RunCandidateScoreProjection
    )


def decode_run_decision_trace_projection(value: object) -> RunDecisionTraceProjection:
    return _decode_flat(value, "decision_trace", _DECISION_TRACE_SCHEMA, RunDecisionTraceProjection)


def decode_run_lookahead_second_action_projection(
    value: object,
) -> RunLookaheadSecondActionProjection:
    return _decode_flat(
        value,
        "lookahead_second_action",
        _LOOKAHEAD_SECOND_ACTION_SCHEMA,
        RunLookaheadSecondActionProjection,
    )


def decode_run_lookahead_branch_projection(value: object) -> RunLookaheadBranchProjection:
    return _decode_flat(
        value, "lookahead_branch", _LOOKAHEAD_BRANCH_SCHEMA, RunLookaheadBranchProjection
    )


def decode_run_lookahead_first_action_projection(
    value: object,
) -> RunLookaheadFirstActionProjection:
    return _decode_flat(
        value,
        "lookahead_first_action",
        _LOOKAHEAD_FIRST_ACTION_SCHEMA,
        RunLookaheadFirstActionProjection,
    )


def decode_run_lookahead_alternative_projection(
    value: object,
) -> RunLookaheadAlternativeProjection:
    return _decode_flat(
        value,
        "lookahead_alternative",
        _LOOKAHEAD_ALTERNATIVE_SCHEMA,
        RunLookaheadAlternativeProjection,
    )


def decode_run_lookahead_trace_projection(value: object) -> RunLookaheadTraceProjection:
    return _decode_flat(
        value, "lookahead_trace", _LOOKAHEAD_TRACE_SCHEMA, RunLookaheadTraceProjection
    )


def decode_run_policy_trace_projection(value: object) -> RunPolicyTraceProjection:
    parsed = _closed_dict(value, ("kind", "projection"), "policy_trace")
    kind = _string(parsed["kind"], "policy_trace.kind")
    if kind == "decision_trace":
        return RunPolicyTraceProjection(
            "decision_trace",
            decode_run_decision_trace_projection(parsed["projection"]),
        )
    if kind == "lookahead_plan_trace":
        return RunPolicyTraceProjection(
            "lookahead_plan_trace",
            decode_run_lookahead_trace_projection(parsed["projection"]),
        )
    _structural("policy_trace.kind", "unknown policy-trace kind")


def decode_run_arm_decision_projection(value: object) -> RunArmDecisionProjection:
    return _decode_flat(value, "arm_decision", _ARM_DECISION_SCHEMA, RunArmDecisionProjection)


def decode_run_arm_action_projection(value: object) -> RunArmActionProjection:
    return _decode_flat(value, "arm_action", _ARM_ACTION_SCHEMA, RunArmActionProjection)


def decode_returned_run_projection(value: object) -> ReturnedRunProjection:
    return _decode_flat(value, "returned_run", _RETURNED_RUN_SCHEMA, ReturnedRunProjection)


# Reconstruction strictly decodes first, then invokes each existing constructor once.
def _rebuild[T, P](
    path: str,
    constructor: Callable[..., T],
    args: tuple[object, ...],
    projection: P,
    projector: Callable[[T], P],
) -> T:
    try:
        result = constructor(*args)
    except (ReasoningError, OverflowError) as error:
        _scientific(path, str(error))
    if projector(result) != projection:
        _scientific(path, "field-total comparison failed")
    return result


def reconstruct_provenance(projection: RunProvenanceProjection) -> Provenance:
    projection_as_dict(projection)
    details = tuple(
        (key, provenance_value_from_projection(value)) for key, value in projection.details
    )
    args = projection.method, projection.version, details
    return _rebuild("provenance", Provenance, args, projection, project_provenance)


def reconstruct_candidate(projection: RunCandidateProjection) -> Candidate:
    projection_as_dict(projection)
    learning_rate = _float_from_f64(projection.learning_rate, "candidate.learning_rate")
    regularization = _float_from_f64(projection.regularization, "candidate.regularization")
    head = projection.candidate_id, learning_rate, regularization
    args = *head, projection.model_width, projection.optimizer
    return _rebuild("candidate", Candidate, args, projection, project_candidate)


def control_value_from_projection(projection: ControlValueProjection) -> DomainControlValue:
    projection_as_dict(projection)
    if projection.kind == "f64":
        return _float_from_f64(projection.value, "control_value.value")
    return projection.value


def reconstruct_public_experiment_design(
    projection: RunPublicExperimentDesignProjection,
) -> PublicExperimentDesign:
    projection_as_dict(projection)
    controlled = tuple(
        (name, control_value_from_projection(value))
        for name, value in projection.controlled_variables
    )
    args = (
        projection.candidate_id,
        projection.experiment_family,
        projection.comparison_group_id,
        controlled,
        projection.intervention_variable,
        projection.intervention_arm,
    )
    return _rebuild(
        "public_experiment_design",
        PublicExperimentDesign,
        args,
        projection,
        project_public_experiment_design,
    )


def reconstruct_hypothesis_decision_context(
    projection: RunHypothesisDecisionContextProjection,
) -> HypothesisDecisionContext:
    projection_as_dict(projection)
    path = "hypothesis_decision_context"
    args = (
        projection.hypothesis_id,
        projection.statement,
        _float_from_f64(projection.posterior_probability, f"{path}.posterior_probability"),
        _float_from_f64(
            projection.most_favorable_outcome,
            f"{path}.most_favorable_outcome",
        ),
        projection.most_favorable_outcome_label,
        _float_from_f64(projection.posterior_if_observed, f"{path}.posterior_if_observed"),
    )
    return _rebuild(
        path,
        HypothesisDecisionContext,
        args,
        projection,
        project_hypothesis_decision_context,
    )


def reconstruct_candidate_score(projection: RunCandidateScoreProjection) -> CandidateScore:
    projection_as_dict(projection)
    path = "candidate_score"
    args = (
        reconstruct_candidate(projection.candidate),
        _float_from_f64(
            projection.expected_information_gain,
            f"{path}.expected_information_gain",
        ),
        _float_from_f64(projection.prior_entropy, f"{path}.prior_entropy"),
        _float_from_f64(
            projection.expected_posterior_entropy,
            f"{path}.expected_posterior_entropy",
        ),
        _float_from_f64(projection.estimated_cost, f"{path}.estimated_cost"),
        projection.completes_matched_pair,
        projection.matched_experiment_id,
        projection.score_reason,
        projection.ranking_reason,
    )
    return _rebuild(path, CandidateScore, args, projection, project_candidate_score)


def reconstruct_decision_trace(projection: RunDecisionTraceProjection) -> DecisionTrace:
    projection_as_dict(projection)
    hypotheses = tuple(
        reconstruct_hypothesis_decision_context(item) for item in projection.hypotheses
    )
    ranked = tuple(reconstruct_candidate_score(item) for item in projection.ranked_candidates)
    selected = reconstruct_candidate_score(projection.selected)
    args = (
        projection.suggestion_id,
        projection.policy,
        projection.policy_version,
        projection.created_at,
        projection.belief_state_id,
        selected,
        hypotheses,
        _float_from_f64(projection.max_cost, "decision_trace.max_cost"),
        projection.fallback_reason,
        projection.rationale,
        ranked,
        reconstruct_provenance(projection.provenance),
    )
    return _rebuild("decision_trace", DecisionTrace, args, projection, project_decision_trace)


def reconstruct_lookahead_second_action(
    projection: RunLookaheadSecondActionProjection,
) -> LookaheadSecondAction:
    projection_as_dict(projection)
    path = "lookahead_second_action"
    candidate = (
        None if projection.candidate is None else reconstruct_candidate(projection.candidate)
    )
    args = (
        candidate,
        projection.action_effect,
        _from_lf64(projection.expected_information_gain, path, "expected_information_gain"),
        _from_lf64(projection.estimated_cost, path, "estimated_cost"),
        _from_lf64(projection.information_gain_per_cost, path, "information_gain_per_cost"),
        projection.reason,
    )
    return _rebuild(
        path,
        LookaheadSecondAction,
        args,
        projection,
        project_lookahead_second_action,
    )


def _reconstruct_probability_pairs(
    projection: tuple[tuple[str, str], ...], path: str
) -> tuple[tuple[str, float], ...]:
    return tuple(
        (hypothesis_id, _float_from_f64(probability, f"{path}[{i}][1]"))
        for i, (hypothesis_id, probability) in enumerate(projection)
    )


def _from_lf64(value: object, path: str, field: str) -> float:
    """Reconstruct one named Lookahead F64 field."""

    return _float_from_f64(value, f"{path}.{field}")


def reconstruct_lookahead_branch(
    projection: RunLookaheadBranchProjection,
) -> LookaheadBranch:
    projection_as_dict(projection)
    _validate_evidence_bound_coupling(projection)
    path = "lookahead_branch"
    lower = (
        None
        if projection.evidence_lower_bound is None
        else _float_from_f64(projection.evidence_lower_bound, f"{path}.evidence_lower_bound")
    )
    upper = (
        None
        if projection.evidence_upper_bound is None
        else _float_from_f64(projection.evidence_upper_bound, f"{path}.evidence_upper_bound")
    )
    args = (
        projection.branch_id,
        projection.label,
        _from_lf64(projection.probability, path, "probability"),
        lower,
        upper,
        _reconstruct_probability_pairs(
            projection.posterior_probabilities,
            f"{path}.posterior_probabilities",
        ),
        _from_lf64(projection.posterior_entropy, path, "posterior_entropy"),
        reconstruct_lookahead_second_action(projection.second_action),
        _from_lf64(projection.terminal_entropy, path, "terminal_entropy"),
        _from_lf64(projection.branch_total_cost, path, "branch_total_cost"),
        projection.budget_feasible,
    )
    return _rebuild(path, LookaheadBranch, args, projection, project_lookahead_branch)


def reconstruct_lookahead_first_action(
    projection: RunLookaheadFirstActionProjection,
) -> LookaheadFirstActionPlan:
    projection_as_dict(projection)
    path = "lookahead_first_action"
    args = (
        reconstruct_candidate(projection.candidate),
        reconstruct_public_experiment_design(projection.public_design),
        projection.action_effect,
        _from_lf64(projection.first_action_cost, path, "first_action_cost"),
        _from_lf64(projection.prior_entropy, path, "prior_entropy"),
        _from_lf64(projection.immediate_information_gain, path, "immediate_information_gain"),
        _from_lf64(projection.expected_terminal_entropy, path, "expected_terminal_entropy"),
        _from_lf64(
            projection.expected_total_information_gain,
            path,
            "expected_total_information_gain",
        ),
        _from_lf64(projection.expected_total_cost, path, "expected_total_cost"),
        _from_lf64(
            projection.information_gain_per_expected_cost,
            path,
            "information_gain_per_expected_cost",
        ),
        tuple(reconstruct_lookahead_branch(item) for item in projection.branches),
        projection.ranking_reason,
    )
    return _rebuild(
        path,
        LookaheadFirstActionPlan,
        args,
        projection,
        project_lookahead_first_action,
    )


def reconstruct_lookahead_alternative(
    projection: RunLookaheadAlternativeProjection,
) -> LookaheadAlternative:
    projection_as_dict(projection)
    path = "lookahead_alternative"
    args = (
        reconstruct_candidate(projection.candidate),
        projection.action_effect,
        projection.comparison_group_id,
        _from_lf64(projection.immediate_information_gain, path, "immediate_information_gain"),
        _from_lf64(
            projection.expected_total_information_gain,
            path,
            "expected_total_information_gain",
        ),
        _from_lf64(projection.expected_total_cost, path, "expected_total_cost"),
        _from_lf64(
            projection.information_gain_per_expected_cost,
            path,
            "information_gain_per_expected_cost",
        ),
        projection.ranking_reason,
    )
    return _rebuild(
        path,
        LookaheadAlternative,
        args,
        projection,
        project_lookahead_alternative,
    )


def reconstruct_lookahead_trace(
    projection: RunLookaheadTraceProjection,
) -> LookaheadPlanTrace:
    projection_as_dict(projection)
    path = "lookahead_trace"
    args = (
        projection.plan_id,
        projection.policy,
        projection.policy_version,
        projection.created_at,
        projection.belief_state_id,
        _reconstruct_probability_pairs(
            projection.current_hypothesis_probabilities,
            f"{path}.current_hypothesis_probabilities",
        ),
        projection.completed_state_fingerprint,
        projection.candidate_set_fingerprint,
        _from_lf64(projection.max_cost, path, "max_cost"),
        reconstruct_lookahead_first_action(projection.selected),
        tuple(reconstruct_lookahead_alternative(item) for item in projection.alternatives),
        projection.tie_breaking_order,
        projection.fallback_reason,
        projection.rationale,
        reconstruct_provenance(projection.provenance),
    )
    return _rebuild(path, LookaheadPlanTrace, args, projection, project_lookahead_trace)


def reconstruct_policy_trace(
    projection: RunPolicyTraceProjection,
) -> DecisionTrace | LookaheadPlanTrace:
    projection_as_dict(projection)
    nested = projection.projection
    if projection.kind == "decision_trace":
        if type(nested) is not RunDecisionTraceProjection:
            _structural("policy_trace.projection", "tag and projection type do not match")
        result: DecisionTrace | LookaheadPlanTrace = reconstruct_decision_trace(nested)
    else:
        if type(nested) is not RunLookaheadTraceProjection:
            _structural("policy_trace.projection", "tag and projection type do not match")
        result = reconstruct_lookahead_trace(nested)
    if project_policy_trace(result) != projection:
        _scientific("policy_trace", "field-total comparison failed")
    return result


def _reconstruct_revealed_observation(
    projection: RunRevealedObservationProjection,
) -> RevealedObservation:
    validate_revealed_observation_projection(projection)
    args = (
        projection.oracle_key_id,
        projection.oracle_use_id,
        projection.authorization_id,
        projection.namespace,
        projection.world_id,
        projection.seed,
        projection.candidate_id,
        projection.comparison_group_id,
        projection.intervention_arm,
        projection.replication_id,
        projection.key_fields,
        projection.serialized_key_hex,
        projection.digest,
        projection.u,
        projection.z,
        _float_from_f64(
            projection.revealed_observation,
            "revealed_observation.revealed_observation",
        ),
        projection.outcome_digest,
    )
    return _rebuild(
        "revealed_observation",
        RevealedObservation,
        args,
        projection,
        lambda value: _project_revealed_observation(
            value,
            projection.authorization,
            validate_science=True,
        ),
    )


def reconstruct_calibration_estimate(
    projection: RunCalibrationEstimateProjection,
) -> CalibrationGroupEstimate:
    projection_as_dict(projection)
    effects = tuple(reconstruct_matched_effect(item) for item in projection.effects)
    observations = tuple(
        _reconstruct_revealed_observation(item) for item in projection.observations
    )
    _validate_calibration_estimate_projection(projection, effects, observations)
    args = (
        projection.sigma_estimate_id,
        projection.calibration_prefix_id,
        projection.comparison_group_id,
        projection.source_effect_ids,
        projection.source_sequence_cutoff,
        projection.sample_count,
        _float_from_f64(projection.sample_mean, "calibration_estimate.sample_mean"),
        _float_from_f64(
            projection.raw_sample_standard_deviation,
            "calibration_estimate.raw_sample_standard_deviation",
        ),
        projection.ddof,
        _float_from_f64(projection.sigma_floor, "calibration_estimate.sigma_floor"),
        _float_from_f64(
            projection.estimated_sigma,
            "calibration_estimate.estimated_sigma",
        ),
        projection.belief_model_id,
        projection.lineage_id,
        projection.provenance_sha256,
        effects,
        observations,
        _float_from_f64(projection.physical_cost, "calibration_estimate.physical_cost"),
    )
    run_id = _calibration_run_id(
        projection.observations,
        path="calibration_estimate.observations",
    )
    return _rebuild(
        "calibration_estimate",
        CalibrationGroupEstimate,
        args,
        projection,
        lambda value: project_calibration_estimate(value, expected_run_id=run_id),
    )


def _validate_calibration_projection(
    projection: RunCalibrationProjection,
    estimates: tuple[CalibrationGroupEstimate, ...],
) -> None:
    if len(estimates) != len(GROUP_IDS):
        _scientific("calibration.estimates", "deployment estimate cardinality differs")
    if tuple(item.comparison_group_id for item in estimates) != GROUP_IDS:
        _scientific("calibration.estimates", "deployment estimate group order differs")
    _validate_unique_ids(
        tuple(item.sigma_estimate_id for item in estimates),
        "calibration.estimates",
    )
    expected_effects = tuple(item for estimate in projection.estimates for item in estimate.effects)
    expected_observations = tuple(
        item for estimate in projection.estimates for item in estimate.observations
    )
    if projection.effects != expected_effects:
        _scientific("calibration.effects", "deployment effect sequence differs")
    if projection.observations != expected_observations:
        _scientific("calibration.observations", "deployment observation sequence differs")
    expected_cost = math.fsum(item.physical_cost for item in estimates)
    recorded_cost = _float_from_f64(projection.cost, "calibration.cost")
    if not _same_f64(recorded_cost, expected_cost, "calibration.cost"):
        _scientific("calibration.cost", "deployment cost differs")


def reconstruct_calibration(projection: RunCalibrationProjection) -> CalibrationDeployment:
    projection_as_dict(projection)
    estimates = tuple(reconstruct_calibration_estimate(item) for item in projection.estimates)
    effects = tuple(reconstruct_matched_effect(item) for item in projection.effects)
    observations = tuple(
        _reconstruct_revealed_observation(item) for item in projection.observations
    )
    _validate_calibration_projection(projection, estimates)
    args = (
        estimates,
        effects,
        observations,
        _float_from_f64(projection.cost, "calibration.cost"),
    )
    run_id = _calibration_run_id(projection.observations, path="calibration.observations")
    return _rebuild(
        "calibration",
        CalibrationDeployment,
        args,
        projection,
        lambda value: project_calibration(value, expected_run_id=run_id),
    )


def reconstruct_arm_decision(projection: RunArmDecisionProjection) -> ArmDecision:
    projection_as_dict(projection)
    trace = reconstruct_policy_trace(projection.policy_trace)
    _validate_arm_decision_projection(projection, trace)
    args = (
        projection.decision_id,
        projection.step,
        projection.selected_candidate_id,
        _float_from_f64(projection.remaining_budget, "arm_decision.remaining_budget"),
        projection.belief_state_id,
        projection.public_feasible_candidate_ids,
        projection.affordable_candidate_ids,
        trace,
        projection.fixed_policy_regression_match,
    )
    return _rebuild(
        "arm_decision",
        ArmDecision,
        args,
        projection,
        project_arm_decision,
    )


def reconstruct_arm_action(projection: RunArmActionProjection) -> ArmAction:
    projection_as_dict(projection)
    oracle = (
        None
        if projection.oracle_observation is None
        else _reconstruct_revealed_observation(projection.oracle_observation)
    )
    _validate_arm_action_projection(projection, oracle)
    args = (
        projection.step,
        projection.candidate_id,
        projection.role,
        _float_from_f64(projection.cost, "arm_action.cost"),
        _float_from_f64(
            projection.cumulative_decision_cost,
            "arm_action.cumulative_decision_cost",
        ),
        projection.decision_id,
        (
            None
            if projection.observed_objective is None
            else _float_from_f64(
                projection.observed_objective,
                "arm_action.observed_objective",
            )
        ),
        oracle,
        projection.new_evidence_ids,
        _reconstruct_probability_pairs(
            projection.posterior_probabilities,
            "arm_action.posterior_probabilities",
        ),
    )
    return _rebuild(
        "arm_action",
        ArmAction,
        args,
        projection,
        lambda value: _project_arm_action(
            value,
            None
            if projection.oracle_observation is None
            else projection.oracle_observation.authorization,
            validate_science=True,
        ),
    )


def reconstruct_completed_experiment(
    projection: RunCompletedExperimentProjection,
) -> CompletedExperiment:
    projection_as_dict(projection)
    candidate = reconstruct_candidate(projection.candidate)
    observed = _float_from_f64(projection.observed_value, "completed_experiment.observed_value")
    args = projection.record_id, candidate, observed, projection.created_at
    return _rebuild(
        "completed_experiment", CompletedExperiment, args, projection, project_completed_experiment
    )


def _reconstruct_evidence(projection: RunEvidenceProjection, provenance: Provenance) -> Evidence:
    comparison = _float_from_f64(projection.observed_comparison, "evidence.observed_comparison")
    head = projection.evidence_id, projection.source_experiment_ids, comparison
    args = *head, projection.observed_outcome, provenance, projection.created_at
    return _rebuild("evidence", Evidence, args, projection, project_evidence)


def reconstruct_evidence(projection: RunEvidenceProjection) -> Evidence:
    projection_as_dict(projection)
    return _reconstruct_evidence(projection, reconstruct_provenance(projection.provenance))


def reconstruct_belief_state(projection: RunBeliefStateProjection) -> BeliefState:
    projection_as_dict(projection)
    posterior = tuple(
        _float_from_f64(item, f"belief_state.posterior_probabilities[{i}]")
        for i, item in enumerate(projection.posterior_probabilities)
    )
    prior = tuple(
        _float_from_f64(item, f"belief_state.prior_probabilities[{i}]")
        for i, item in enumerate(projection.prior_probabilities)
    )
    head = projection.belief_state_id, projection.hypothesis_ids, prior, posterior
    tail = projection.evidence_ids, projection.sequence, projection.created_at
    args = *head, *tail, projection.parent_belief_state_id
    return _rebuild("belief_state", BeliefState, args, projection, project_belief_state)


def reconstruct_hypothesis_likelihood(
    projection: RunHypothesisLikelihoodProjection,
) -> HypothesisLikelihood:
    projection_as_dict(projection)
    path = "hypothesis_likelihood"
    prior = _float_from_f64(projection.prior_for_update, f"{path}.prior_for_update")
    likelihood = _float_from_f64(projection.likelihood, f"{path}.likelihood")
    weight = _float_from_f64(projection.unnormalized_weight, f"{path}.unnormalized_weight")
    posterior = _float_from_f64(projection.posterior_probability, f"{path}.posterior_probability")
    args = projection.hypothesis_id, prior, likelihood, weight, posterior
    return _rebuild(path, HypothesisLikelihood, args, projection, project_hypothesis_likelihood)


def _same_f64(left: float, right: float, path: str) -> bool:
    try:
        return f64(left) == f64(right)
    except ProtocolError as error:
        _scientific(path, str(error))


def _validate_belief_update_relations(update: BeliefUpdate) -> None:
    before, posterior = update.belief_state_before, update.posterior_belief_state
    if posterior.hypothesis_ids != before.hypothesis_ids:
        _scientific("belief_update.posterior_belief_state.hypothesis_ids", "alignment differs")
    path = "belief_update.posterior_belief_state.prior_probabilities"
    if len(posterior.prior_probabilities) != len(before.prior_probabilities) or any(
        not _same_f64(left, right, path)
        for left, right in zip(
            posterior.prior_probabilities, before.prior_probabilities, strict=True
        )
    ):
        _scientific(path, "priors differ")
    if posterior.sequence != before.sequence + 1:
        _scientific("belief_update.posterior_belief_state.sequence", "sequence did not advance")
    if posterior.created_at != update.evidence.created_at:
        _scientific("belief_update.posterior_belief_state.created_at", "time differs from evidence")
    if update.created_at != update.evidence.created_at:
        _scientific("belief_update.created_at", "time differs from evidence")
    for i, item in enumerate(update.likelihoods):
        path = f"belief_update.likelihoods[{i}]"
        if not _same_f64(item.prior_for_update, before.posterior_probabilities[i], path):
            _scientific(f"{path}.prior_for_update", "prior differs")
        if not _same_f64(item.unnormalized_weight, item.prior_for_update * item.likelihood, path):
            _scientific(f"{path}.unnormalized_weight", "weight differs")
    try:
        normalization = math.fsum(item.unnormalized_weight for item in update.likelihoods)
    except OverflowError as error:
        _scientific("belief_update.normalization_constant", str(error))
    if not _same_f64(
        update.normalization_constant, normalization, "belief_update.normalization_constant"
    ):
        _scientific("belief_update.normalization_constant", "normalization differs")
    for i, item in enumerate(update.likelihoods):
        path = f"belief_update.likelihoods[{i}].posterior_probability"
        if not _same_f64(
            item.posterior_probability,
            item.unnormalized_weight / update.normalization_constant,
            path,
        ):
            _scientific(path, "posterior differs")
        state_path = f"belief_update.posterior_belief_state.posterior_probabilities[{i}]"
        if not _same_f64(
            posterior.posterior_probabilities[i], item.posterior_probability, state_path
        ):
            _scientific(state_path, "posterior does not match likelihood record")


def reconstruct_belief_update(projection: RunBeliefUpdateProjection) -> BeliefUpdate:
    projection_as_dict(projection)
    evidence_provenance = reconstruct_provenance(projection.evidence.provenance)
    update_provenance = reconstruct_provenance(projection.provenance)
    evidence = _reconstruct_evidence(projection.evidence, evidence_provenance)
    before = reconstruct_belief_state(projection.belief_state_before)
    posterior = reconstruct_belief_state(projection.posterior_belief_state)
    likelihoods = tuple(reconstruct_hypothesis_likelihood(item) for item in projection.likelihoods)
    normalization = _float_from_f64(
        projection.normalization_constant, "belief_update.normalization_constant"
    )
    head = projection.update_id, before, evidence, likelihoods, posterior
    tail = projection.update_rule_version, normalization, update_provenance, projection.created_at
    args = *head, *tail
    result = _rebuild("belief_update", BeliefUpdate, args, projection, project_belief_update)
    _validate_belief_update_relations(result)
    return result


def reconstruct_matched_effect(
    projection: RunMatchedEffectProjection,
) -> MatchedEffectObservation:
    projection_as_dict(projection)
    effect = _float_from_f64(projection.observed_effect, "matched_effect.observed_effect")
    args = (
        projection.effect_id,
        projection.comparison_group_id,
        effect,
        projection.available_sequence,
        projection.source_kind,
        projection.source_ids,
        projection.created_at,
        reconstruct_provenance(projection.provenance),
    )
    return _rebuild(
        "matched_effect", MatchedEffectObservation, args, projection, project_matched_effect
    )


def _validate_sigma_coupling(projection: RunSigmaEstimateProjection) -> None:
    path, count = "sigma_estimate", projection.sample_count
    mean_missing = projection.sample_mean is None
    raw_missing = projection.raw_sample_standard_deviation is None
    if projection.status == "fixed":
        valid = count == 0 and not projection.source_effect_ids and mean_missing and raw_missing
    elif projection.status == "baseline_fallback":
        valid = (
            0 <= count < MINIMUM_PRIOR_EFFECTS
            and mean_missing == (count == 0)
            and raw_missing == (count < 2)
        )
    elif projection.status == "calibrated":
        valid = count >= MINIMUM_PRIOR_EFFECTS and not mean_missing and not raw_missing
    else:
        _scientific(f"{path}.status", "unknown sigma-estimate status")
    if not valid:
        _scientific(path, "status, count, sources, and sample statistics do not couple")


def reconstruct_sigma_estimate(projection: RunSigmaEstimateProjection) -> SigmaEstimate:
    projection_as_dict(projection)
    _validate_sigma_coupling(projection)
    path = "sigma_estimate"
    mean = (
        None
        if projection.sample_mean is None
        else _float_from_f64(projection.sample_mean, f"{path}.sample_mean")
    )
    raw = (
        None
        if projection.raw_sample_standard_deviation is None
        else _float_from_f64(
            projection.raw_sample_standard_deviation,
            f"{path}.raw_sample_standard_deviation",
        )
    )
    sigma = _float_from_f64(projection.estimated_sigma, f"{path}.estimated_sigma")
    sigma_floor = _float_from_f64(projection.sigma_floor, f"{path}.sigma_floor")
    variance_floor = _float_from_f64(projection.variance_floor, f"{path}.variance_floor")
    if projection.cutoff_sequence <= 0:
        _scientific(f"{path}.cutoff_sequence", "cutoff must be positive")
    if sigma_floor <= 0.0 or variance_floor <= 0.0:
        _scientific(f"{path}.sigma_floor", "sigma and variance floors must be positive")
    if raw is not None and raw < 0.0:
        _scientific(f"{path}.raw_sample_standard_deviation", "sample deviation is negative")
    args = (
        projection.estimate_id,
        projection.belief_model_id,
        projection.belief_model_version,
        projection.lineage_id,
        projection.evidence_id,
        projection.comparison_group_id,
        projection.cutoff_sequence,
        projection.source_effect_ids,
        projection.sample_count,
        mean,
        raw,
        sigma_floor,
        variance_floor,
        sigma,
        projection.status,
        projection.estimator_version,
        projection.current_evidence_excluded,
        projection.created_at,
        reconstruct_provenance(projection.provenance),
    )
    return _rebuild(path, SigmaEstimate, args, projection, project_sigma_estimate)


def reconstruct_model_belief_state(
    projection: RunModelBeliefStateProjection,
) -> ModelBeliefState:
    projection_as_dict(projection)
    state = reconstruct_belief_state(projection.state)
    args = projection.belief_model_id, projection.belief_model_version, projection.lineage_id, state
    return _rebuild(
        "model_belief_state", ModelBeliefState, args, projection, project_model_belief_state
    )


def reconstruct_lineage(projection: RunLineageProjection) -> BeliefModelLineage:
    projection_as_dict(projection)
    current = reconstruct_model_belief_state(projection.current_state)
    args = (
        projection.lineage_id,
        projection.belief_model_id,
        projection.belief_model_version,
        projection.lineage_key,
        current,
        projection.created_at,
    )
    return _rebuild("lineage", BeliefModelLineage, args, projection, project_lineage)


def _reconstruct_predictive_interval(
    projection: RunPredictiveIntervalProjection,
    path: str,
    observation: float | None = None,
) -> PredictiveInterval:
    lower = _float_from_f64(projection.lower, f"{path}.lower")
    probability = _float_from_f64(projection.probability, f"{path}.probability")
    upper = _float_from_f64(projection.upper, f"{path}.upper")
    if not 0.0 < probability < 1.0:
        _scientific(f"{path}.probability", "probability must be strictly between zero and one")
    if lower > upper:
        _scientific(path, "lower bound exceeds upper bound")
    if observation is not None and projection.contains_observation != (
        lower <= observation <= upper
    ):
        _scientific(f"{path}.contains_observation", "flag differs from the observation relation")
    args = probability, lower, upper, projection.contains_observation
    return _rebuild(path, PredictiveInterval, args, projection, project_predictive_interval)


def reconstruct_predictive_interval(
    projection: RunPredictiveIntervalProjection,
) -> PredictiveInterval:
    projection_as_dict(projection)
    return _reconstruct_predictive_interval(projection, "predictive_interval")


def _diagnostic_adequacy(projection: RunDiagnosticProjection) -> AdequacyState:
    if projection.tail_alarm or projection.repeated_residual_alarm:
        return "appears_misspecified"
    if projection.residual_count < ADEQUACY_MINIMUM_RESIDUALS or projection.diagnostics_disagree:
        return "uncertain"
    return "adequate"


def _reconstruct_diagnostic(
    projection: RunDiagnosticProjection,
    observation: float | None = None,
    *,
    cached_intervals: tuple[PredictiveInterval, ...] | None = None,
    cached_provenance: Provenance | None = None,
) -> ModelAdequacyDiagnostic:
    projection_as_dict(projection)
    intervals = (
        tuple(
            _reconstruct_predictive_interval(
                item,
                f"diagnostic.central_intervals[{i}]",
                observation,
            )
            for i, item in enumerate(projection.central_intervals)
        )
        if cached_intervals is None
        else cached_intervals
    )
    if observation is not None and any(
        item.contains_observation != (item.lower <= observation <= item.upper) for item in intervals
    ):
        _scientific("diagnostic.central_intervals", "observation containment differs")
    path = "diagnostic"
    probability_order = tuple(item.probability for item in intervals)
    if probability_order != (0.50, 0.80, 0.95):
        _scientific(f"{path}.central_intervals", "central interval order differs")
    residuals = tuple(
        (hypothesis_id, _float_from_f64(value, f"{path}.per_hypothesis_residuals[{i}][1]"))
        for i, (hypothesis_id, value) in enumerate(projection.per_hypothesis_residuals)
    )
    residual_ids = tuple(item[0] for item in residuals)
    if not residual_ids or len(residual_ids) != len(set(residual_ids)):
        _scientific(
            f"{path}.per_hypothesis_residuals", "hypothesis IDs must be nonempty and unique"
        )
    tail_probability = _float_from_f64(
        projection.posterior_predictive_tail_probability,
        f"{path}.posterior_predictive_tail_probability",
    )
    cdf = _float_from_f64(projection.predictive_cdf, f"{path}.predictive_cdf")
    density = _float_from_f64(projection.predictive_density, f"{path}.predictive_density")
    log_likelihood = _float_from_f64(
        projection.predictive_log_likelihood, f"{path}.predictive_log_likelihood"
    )
    mean = _float_from_f64(projection.predictive_mean, f"{path}.predictive_mean")
    variance = _float_from_f64(projection.predictive_variance, f"{path}.predictive_variance")
    standardized = _float_from_f64(
        projection.standardized_residual, f"{path}.standardized_residual"
    )
    if density <= 0.0 or not 0.0 <= cdf <= 1.0 or not 0.0 <= tail_probability <= 1.0:
        _scientific(path, "predictive probabilities or density are outside their domain")
    if variance <= 0.0:
        _scientific(f"{path}.predictive_variance", "predictive variance must be positive")
    if not _same_f64(log_likelihood, math.log(density), f"{path}.predictive_log_likelihood"):
        _scientific(f"{path}.predictive_log_likelihood", "log-density relation differs")
    expected_tail = min(1.0, max(0.0, 2.0 * min(cdf, 1.0 - cdf)))
    if not _same_f64(
        tail_probability, expected_tail, f"{path}.posterior_predictive_tail_probability"
    ):
        _scientific(f"{path}.posterior_predictive_tail_probability", "CDF relation differs")
    expected_outlier = abs(standardized) > RESIDUAL_OUTLIER_THRESHOLD
    rolling = projection.rolling_residual_outlier_count
    if not int(expected_outlier) <= rolling <= min(RESIDUAL_WINDOW_SIZE, projection.residual_count):
        _scientific(f"{path}.rolling_residual_outlier_count", "rolling count is infeasible")
    expected_tail_alarm = tail_probability < TAIL_ALARM_THRESHOLD
    relations = (
        projection.residual_outlier == expected_outlier,
        projection.tail_alarm == expected_tail_alarm,
        projection.repeated_residual_alarm == (rolling >= RESIDUAL_ALARM_COUNT),
        projection.diagnostics_disagree == (expected_tail_alarm != expected_outlier),
    )
    if not all(relations):
        _scientific(path, "diagnostic alarm relations differ")
    if projection.adequacy_state not in {"adequate", "uncertain", "appears_misspecified"}:
        _scientific(f"{path}.adequacy_state", "unknown adequacy state")
    if projection.adequacy_state != _diagnostic_adequacy(projection):
        _scientific(f"{path}.adequacy_state", "adequacy precedence differs")
    identity = projection.diagnostic_id, projection.belief_model_id, projection.belief_model_version
    relation = (
        projection.lineage_id,
        projection.belief_state_before_id,
        projection.evidence_id,
        projection.sigma_estimate_id,
        projection.comparison_group_id,
    )
    prediction = mean, variance, density, log_likelihood, cdf, tail_probability, standardized
    alarms = (
        projection.residual_count,
        rolling,
        projection.tail_alarm,
        projection.residual_outlier,
        projection.repeated_residual_alarm,
        projection.diagnostics_disagree,
    )
    tail = projection.adequacy_state, projection.diagnostic_version, projection.created_at
    args = (
        *identity,
        *relation,
        *prediction,
        residuals,
        intervals,
        *alarms,
        *tail,
        (
            reconstruct_provenance(projection.provenance)
            if cached_provenance is None
            else cached_provenance
        ),
    )
    return _rebuild(path, ModelAdequacyDiagnostic, args, projection, project_diagnostic)


def reconstruct_diagnostic(projection: RunDiagnosticProjection) -> ModelAdequacyDiagnostic:
    return _reconstruct_diagnostic(projection)


def reconstruct_model_update(projection: RunModelUpdateProjection) -> ModelBeliefUpdate:
    projection_as_dict(projection)
    provenance = reconstruct_provenance(projection.provenance)
    before = reconstruct_model_belief_state(projection.state_before)
    evidence = reconstruct_evidence(projection.evidence)
    sigma = reconstruct_sigma_estimate(projection.sigma_estimate)
    bayesian = reconstruct_belief_update(projection.bayesian_update)
    posterior = reconstruct_model_belief_state(projection.posterior_state)
    diagnostic = _reconstruct_diagnostic(projection.diagnostic, evidence.observed_comparison)
    path = "model_update"
    wrappers = before, posterior
    if any(
        state.belief_model_id != projection.belief_model_id
        or state.belief_model_version != projection.belief_model_version
        or state.lineage_id != projection.lineage_id
        for state in wrappers
    ):
        _scientific(path, "model-state wrapper crosses the model lineage")
    if before.state != bayesian.belief_state_before:
        _scientific(f"{path}.state_before", "Bayesian before state differs")
    if evidence != bayesian.evidence:
        _scientific(f"{path}.evidence", "Bayesian evidence differs")
    if posterior.state != bayesian.posterior_belief_state:
        _scientific(f"{path}.posterior_state", "Bayesian posterior state differs")
    group = evidence.provenance.details_dict().get("comparison_group_id")
    if type(group) is not str or not group.strip():
        _scientific(f"{path}.evidence", "comparison-group context is absent")
    sigma_relation = (
        sigma.belief_model_id == projection.belief_model_id
        and sigma.belief_model_version == projection.belief_model_version
        and sigma.lineage_id == projection.lineage_id
        and sigma.evidence_id == evidence.evidence_id
        and sigma.comparison_group_id == group
        and sigma.cutoff_sequence == before.state.sequence + 1
        and sigma.created_at == evidence.created_at
    )
    if not sigma_relation:
        _scientific(f"{path}.sigma_estimate", "sigma context differs")
    diagnostic_relation = (
        diagnostic.belief_model_id == projection.belief_model_id
        and diagnostic.belief_model_version == projection.belief_model_version
        and diagnostic.lineage_id == projection.lineage_id
        and diagnostic.belief_state_before_id == before.state.belief_state_id
        and diagnostic.evidence_id == evidence.evidence_id
        and diagnostic.sigma_estimate_id == sigma.estimate_id
        and diagnostic.comparison_group_id == group
        and diagnostic.created_at == evidence.created_at
    )
    if not diagnostic_relation:
        _scientific(f"{path}.diagnostic", "diagnostic context differs")
    residual_ids = tuple(item[0] for item in diagnostic.per_hypothesis_residuals)
    if residual_ids != before.state.hypothesis_ids:
        _scientific(f"{path}.diagnostic.per_hypothesis_residuals", "order differs")
    expected_residual = (evidence.observed_comparison - diagnostic.predictive_mean) / math.sqrt(
        diagnostic.predictive_variance
    )
    if not _same_f64(diagnostic.standardized_residual, expected_residual, path):
        _scientific(f"{path}.diagnostic.standardized_residual", "evidence relation differs")
    if projection.created_at != evidence.created_at:
        _scientific(f"{path}.created_at", "evidence chronology differs")
    identity = (
        projection.model_update_id,
        projection.belief_model_id,
        projection.belief_model_version,
        projection.lineage_id,
    )
    args = (
        *identity,
        before,
        evidence,
        sigma,
        bayesian,
        posterior,
        diagnostic,
        projection.created_at,
        provenance,
    )
    return _rebuild(path, ModelBeliefUpdate, args, projection, project_model_update)


def recompute_observation_authorization_id(
    projection: RunObservationAuthorizationProjection,
) -> str:
    """Recompute the existing authorization identity without issuing authority."""

    projection_as_dict(projection)
    return runtime_id(
        "authorization",
        "authorization_id/v1",
        {
            "candidate_id": projection.candidate_id,
            "kind": projection.kind,
            "run_id": projection.run_id,
            "source_id": projection.source_id,
        },
    )


def recompute_revealed_oracle_key_id(projection: RunRevealedObservationProjection) -> str:
    """Recompute the frozen Oracle-key identity from ordered key fields."""

    projection_as_dict(projection)
    return runtime_id(
        "oracle-key",
        "oracle_key_id/v1",
        {"key_fields": list(projection.key_fields)},
    )


def recompute_revealed_outcome_digest(projection: RunRevealedObservationProjection) -> str:
    """Recompute the frozen revealed-outcome digest from exact F64 bits."""

    projection_as_dict(projection)
    return protocol_hash(
        "revealed_outcome/v1",
        {
            "oracle_key_id": projection.oracle_key_id,
            "revealed_observation": projection.revealed_observation,
        },
    )


def recompute_revealed_oracle_use_id(projection: RunRevealedObservationProjection) -> str:
    """Recompute the existing authorization/key use relation."""

    projection_as_dict(projection)
    return f"oracle-use/{projection.authorization_id}/{projection.oracle_key_id}"


def _validate_revealed_key_facts(projection: RunRevealedObservationProjection) -> None:
    key_fields = projection.key_fields
    expected_count = 8 if projection.authorization.kind == "calibration" else 7
    if len(key_fields) != expected_count:
        _scientific("revealed_observation.key_fields", "Oracle key field count differs")
    facts = (
        (key_fields[0], projection.namespace, "namespace"),
        (key_fields[3], projection.world_id, "world_id"),
        (key_fields[4], str(projection.seed), "seed"),
        (key_fields[-1], projection.replication_id, "replication_id"),
    )
    for actual, expected, field in facts:
        if actual != expected:
            _scientific(
                f"revealed_observation.key_fields.{field}",
                "Oracle key fact differs from the revealed record",
            )
    keyed: tuple[tuple[str, str | None, str], ...]
    if projection.authorization.kind == "calibration":
        if projection.comparison_group_id is None or projection.intervention_arm is None:
            _scientific(
                "revealed_observation.comparison_group_id",
                "calibration keys require comparison group and intervention arm",
            )
        keyed = (
            (key_fields[5], projection.comparison_group_id, "comparison_group_id"),
            (key_fields[6], projection.intervention_arm, "intervention_arm"),
        )
    else:
        keyed = ((key_fields[5], projection.candidate_id, "candidate_id"),)
    for actual, expected, field in keyed:
        if actual != expected:
            _scientific(
                f"revealed_observation.key_fields.{field}",
                "Oracle key fact differs from the revealed record",
            )


def validate_revealed_observation_projection(
    projection: RunRevealedObservationProjection,
) -> None:
    """Validate only closed local relations; never consult or consume a live Oracle."""

    projection_as_dict(projection)
    authorization_id = recompute_observation_authorization_id(projection.authorization)
    if projection.authorization_id != authorization_id:
        _scientific(
            "revealed_observation.authorization_id",
            "nested authorization identity differs",
        )
    if projection.candidate_id != projection.authorization.candidate_id:
        _scientific(
            "revealed_observation.candidate_id",
            "nested authorization candidate differs",
        )
    if (projection.comparison_group_id is None) != (projection.intervention_arm is None):
        _scientific(
            "revealed_observation.comparison_group_id",
            "comparison group and intervention arm nullability differs",
        )
    _validate_revealed_key_facts(projection)
    if projection.oracle_key_id != recompute_revealed_oracle_key_id(projection):
        _scientific("revealed_observation.oracle_key_id", "Oracle key identity differs")
    if projection.outcome_digest != recompute_revealed_outcome_digest(projection):
        _scientific("revealed_observation.outcome_digest", "revealed outcome digest differs")
    if projection.oracle_use_id != recompute_revealed_oracle_use_id(projection):
        _scientific("revealed_observation.oracle_use_id", "Oracle use relation differs")
    serialized_key_hex = canonical_json_bytes(list(projection.key_fields)).hex()
    if projection.serialized_key_hex != serialized_key_hex:
        _scientific(
            "revealed_observation.serialized_key_hex",
            "serialized Oracle key bytes differ",
        )


def observation_authorization_projections_match(
    projection: RunObservationAuthorizationProjection,
    expected: RunObservationAuthorizationProjection,
) -> bool:
    """Compare two pure authorization records after exact reconstruction checks."""

    if type(expected) is not RunObservationAuthorizationProjection:
        _structural("expected_authorization", "context must be an authorization projection")
    recompute_observation_authorization_id(projection)
    recompute_observation_authorization_id(expected)
    return projection == expected


def revealed_observation_projections_match(
    projection: RunRevealedObservationProjection,
    expected: RunRevealedObservationProjection,
) -> bool:
    """Compare two pure revealed records after all closed local relations pass."""

    if type(expected) is not RunRevealedObservationProjection:
        _structural("expected_revealed_observation", "context must be a revealed projection")
    validate_revealed_observation_projection(projection)
    validate_revealed_observation_projection(expected)
    return projection == expected


def validate_observation_authorization_relation(
    projection: RunObservationAuthorizationProjection,
    *,
    expected_candidate_id: str | None = None,
    expected_kind: Literal["calibration", "decision"] | None = None,
    expected_run_id: str | None = None,
    expected_source_id: str | None = None,
    expected_authorization_id: str | None = None,
) -> None:
    """Compare every authorization fact with required pure enclosing context."""

    authorization_id = recompute_observation_authorization_id(projection)
    if (
        expected_candidate_id is None
        or expected_kind is None
        or expected_run_id is None
        or expected_source_id is None
        or expected_authorization_id is None
    ):
        _missing_context("observation_authorization")
    expected_facts = (
        (
            projection.candidate_id,
            _id(expected_candidate_id, "expected_candidate_id"),
            "candidate_id",
        ),
        (projection.kind, _authorization_kind(expected_kind, "expected_kind"), "kind"),
        (projection.run_id, _id(expected_run_id, "expected_run_id"), "run_id"),
        (projection.source_id, _id(expected_source_id, "expected_source_id"), "source_id"),
        (
            authorization_id,
            _id(expected_authorization_id, "expected_authorization_id"),
            "authorization_id",
        ),
    )
    for actual, expected, field in expected_facts:
        if actual != expected:
            _scientific(
                f"observation_authorization.{field}",
                "enclosing authorization relation differs",
            )


def validate_revealed_observation_relations(
    projection: RunRevealedObservationProjection,
    *,
    expected_authorization: RunObservationAuthorizationProjection | None = None,
    expected_authorization_id: str | None = None,
    expected_namespace: str | None = None,
    expected_world_id: str | None = None,
    expected_seed: int | None = None,
    expected_candidate_id: str | None = None,
    expected_comparison_group_id: object = _MISSING_CONTEXT,
    expected_intervention_arm: object = _MISSING_CONTEXT,
    expected_replication_id: str | None = None,
    expected_key_fields: tuple[str, ...] | None = None,
    expected_oracle_key_id: str | None = None,
    expected_outcome_digest: str | None = None,
    expected_oracle_use_id: str | None = None,
) -> None:
    """Validate every required enclosing Oracle fact without live authority."""

    projection_as_dict(projection)
    if expected_authorization is None:
        _missing_context("revealed_observation.authorization")
    if type(expected_authorization) is not RunObservationAuthorizationProjection:
        _structural("expected_authorization", "context must be an authorization projection")
    if expected_authorization_id is None:
        _missing_context("revealed_observation.authorization_id")
    validate_observation_authorization_relation(
        projection.authorization,
        expected_candidate_id=expected_authorization.candidate_id,
        expected_kind=expected_authorization.kind,
        expected_run_id=expected_authorization.run_id,
        expected_source_id=expected_authorization.source_id,
        expected_authorization_id=expected_authorization_id,
    )
    validate_revealed_observation_projection(projection)
    if expected_namespace is None:
        _missing_context("revealed_observation.namespace")
    if expected_world_id is None:
        _missing_context("revealed_observation.world_id")
    if expected_seed is None:
        _missing_context("revealed_observation.seed")
    if expected_candidate_id is None:
        _missing_context("revealed_observation.candidate_id")
    if expected_comparison_group_id is _MISSING_CONTEXT:
        _missing_context("revealed_observation.comparison_group_id")
    if expected_intervention_arm is _MISSING_CONTEXT:
        _missing_context("revealed_observation.intervention_arm")
    if expected_replication_id is None:
        _missing_context("revealed_observation.replication_id")
    if expected_key_fields is None:
        _missing_context("revealed_observation.key_fields")
    if expected_oracle_key_id is None:
        _missing_context("revealed_observation.oracle_key_id")
    if expected_outcome_digest is None:
        _missing_context("revealed_observation.outcome_digest")
    if expected_oracle_use_id is None:
        _missing_context("revealed_observation.oracle_use_id")
    comparison_group_id = _optional_id(
        expected_comparison_group_id,
        "expected_comparison_group_id",
    )
    intervention_arm = _optional_id(expected_intervention_arm, "expected_intervention_arm")
    key_fields = _projected_items(expected_key_fields, "expected_key_fields", _string)
    expected_facts: tuple[tuple[object, object, str], ...] = (
        (projection.namespace, _id(expected_namespace, "expected_namespace"), "namespace"),
        (projection.world_id, _id(expected_world_id, "expected_world_id"), "world_id"),
        (projection.seed, _i64(expected_seed, "expected_seed"), "seed"),
        (
            projection.candidate_id,
            _id(expected_candidate_id, "expected_candidate_id"),
            "candidate_id",
        ),
        (projection.comparison_group_id, comparison_group_id, "comparison_group_id"),
        (projection.intervention_arm, intervention_arm, "intervention_arm"),
        (
            projection.replication_id,
            _id(expected_replication_id, "expected_replication_id"),
            "replication_id",
        ),
        (projection.key_fields, key_fields, "key_fields"),
        (
            projection.oracle_key_id,
            _id(expected_oracle_key_id, "expected_oracle_key_id"),
            "oracle_key_id",
        ),
        (
            projection.outcome_digest,
            _h64(expected_outcome_digest, "expected_outcome_digest"),
            "outcome_digest",
        ),
        (
            projection.oracle_use_id,
            _id(expected_oracle_use_id, "expected_oracle_use_id"),
            "oracle_use_id",
        ),
    )
    for actual, expected, field in expected_facts:
        if actual != expected:
            _scientific(
                f"revealed_observation.{field}",
                "enclosing Oracle relation differs",
            )


def _scientific_call[T, **P](
    path: str,
    call: Callable[P, T],
    /,
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    """Map an existing pure scientific failure at its numbered local stage."""

    try:
        return call(*args, **kwargs)
    except ReturnedRunProjectionError:
        raise
    except (KeyError, OracleError, ReasoningError, ValueError, OverflowError) as error:
        _scientific(path, str(error))


def _policy_payload(
    value: RunPolicyTraceProjection,
) -> RunDecisionTraceProjection | RunLookaheadTraceProjection:
    nested = value.projection
    if type(nested) is RunDecisionTraceProjection:
        return nested
    if type(nested) is RunLookaheadTraceProjection:
        return nested
    _structural("returned_run.decisions.policy_trace.projection", "unknown projection type")


def _returned_policy_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunPolicyTraceProjection, ...]:
    return tuple(decision.policy_trace for decision in projection.decisions)


def _returned_decision_trace_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunDecisionTraceProjection, ...]:
    result: list[RunDecisionTraceProjection] = []
    for policy in _returned_policy_occurrences(projection):
        nested = _policy_payload(policy)
        if isinstance(nested, RunDecisionTraceProjection):
            result.append(nested)
    return tuple(result)


def _returned_lookahead_trace_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunLookaheadTraceProjection, ...]:
    result: list[RunLookaheadTraceProjection] = []
    for policy in _returned_policy_occurrences(projection):
        nested = _policy_payload(policy)
        if isinstance(nested, RunLookaheadTraceProjection):
            result.append(nested)
    return tuple(result)


def _policy_candidate_occurrences(
    policy: RunPolicyTraceProjection,
) -> tuple[RunCandidateProjection, ...]:
    nested = _policy_payload(policy)
    if isinstance(nested, RunDecisionTraceProjection):
        return (
            *(score.candidate for score in nested.ranked_candidates),
            nested.selected.candidate,
        )
    alternative_candidates = tuple(alternative.candidate for alternative in nested.alternatives)
    second_candidates = tuple(
        branch.second_action.candidate
        for branch in nested.selected.branches
        if branch.second_action.candidate is not None
    )
    return (*alternative_candidates, *second_candidates, nested.selected.candidate)


def _returned_candidate_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunCandidateProjection, ...]:
    completed_candidates = tuple(item.candidate for item in projection.completed_experiments)
    policy_candidates = tuple(
        candidate
        for policy in _returned_policy_occurrences(projection)
        for candidate in _policy_candidate_occurrences(policy)
    )
    return (*completed_candidates, *policy_candidates)


def _returned_diagnostic_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunDiagnosticProjection, ...]:
    return (*projection.diagnostics, *(update.diagnostic for update in projection.updates))


def _returned_sigma_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunSigmaEstimateProjection, ...]:
    return tuple(update.sigma_estimate for update in projection.updates)


def _returned_evidence_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunEvidenceProjection, ...]:
    nested = tuple(
        evidence
        for update in projection.updates
        for evidence in (update.bayesian_update.evidence, update.evidence)
    )
    return (*projection.evidence, *nested)


def _returned_belief_state_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunBeliefStateProjection, ...]:
    nested = tuple(
        state
        for update in projection.updates
        for state in (
            update.bayesian_update.belief_state_before,
            update.bayesian_update.posterior_belief_state,
            update.posterior_state.state,
            update.state_before.state,
        )
    )
    return (projection.lineage.current_state.state, *nested)


def _returned_model_state_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunModelBeliefStateProjection, ...]:
    nested = tuple(
        state
        for update in projection.updates
        for state in (update.posterior_state, update.state_before)
    )
    return (projection.lineage.current_state, *nested)


def _returned_likelihood_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunHypothesisLikelihoodProjection, ...]:
    return tuple(
        likelihood
        for update in projection.updates
        for likelihood in update.bayesian_update.likelihoods
    )


def _returned_interval_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunPredictiveIntervalProjection, ...]:
    return tuple(
        interval
        for diagnostic in _returned_diagnostic_occurrences(projection)
        for interval in diagnostic.central_intervals
    )


def _returned_score_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunCandidateScoreProjection, ...]:
    return tuple(
        score
        for trace in _returned_decision_trace_occurrences(projection)
        for score in (*trace.ranked_candidates, trace.selected)
    )


def _returned_context_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunHypothesisDecisionContextProjection, ...]:
    return tuple(
        context
        for trace in _returned_decision_trace_occurrences(projection)
        for context in trace.hypotheses
    )


def _returned_second_action_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunLookaheadSecondActionProjection, ...]:
    return tuple(
        branch.second_action
        for trace in _returned_lookahead_trace_occurrences(projection)
        for branch in trace.selected.branches
    )


def _returned_branch_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunLookaheadBranchProjection, ...]:
    return tuple(
        branch
        for trace in _returned_lookahead_trace_occurrences(projection)
        for branch in trace.selected.branches
    )


def _returned_first_action_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunLookaheadFirstActionProjection, ...]:
    return tuple(trace.selected for trace in _returned_lookahead_trace_occurrences(projection))


def _returned_alternative_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunLookaheadAlternativeProjection, ...]:
    return tuple(
        alternative
        for trace in _returned_lookahead_trace_occurrences(projection)
        for alternative in trace.alternatives
    )


def _returned_design_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunPublicExperimentDesignProjection, ...]:
    return tuple(item.public_design for item in _returned_first_action_occurrences(projection))


def _returned_provenance_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunProvenanceProjection, ...]:
    calibration_provenances: tuple[RunProvenanceProjection, ...] = ()
    if projection.calibration is not None:
        calibration_provenances = (
            *(effect.provenance for effect in projection.calibration.effects),
            *(
                effect.provenance
                for estimate in projection.calibration.estimates
                for effect in estimate.effects
            ),
        )
    policy_provenances = tuple(
        _policy_payload(policy).provenance for policy in _returned_policy_occurrences(projection)
    )
    update_provenances = tuple(
        provenance
        for update in projection.updates
        for provenance in (
            update.bayesian_update.evidence.provenance,
            update.bayesian_update.provenance,
            update.diagnostic.provenance,
            update.evidence.provenance,
            update.provenance,
            update.sigma_estimate.provenance,
        )
    )
    return (
        *calibration_provenances,
        *policy_provenances,
        *(diagnostic.provenance for diagnostic in projection.diagnostics),
        *(effect.provenance for effect in projection.effect_history),
        *(evidence.provenance for evidence in projection.evidence),
        *update_provenances,
    )


def _returned_control_value_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[ControlValueProjection, ...]:
    return tuple(
        control
        for design in _returned_design_occurrences(projection)
        for _, control in design.controlled_variables
    )


def _s1_probability_distribution(values: tuple[str, ...], path: str) -> tuple[float, ...]:
    parsed = tuple(_float_from_f64(value, f"{path}[{index}]") for index, value in enumerate(values))
    try:
        total = math.fsum(parsed)
    except OverflowError as error:
        _scientific(path, str(error))
    if any(value < 0.0 for value in parsed) or not math.isclose(
        total,
        1.0,
        rel_tol=0.0,
        abs_tol=PROBABILITY_TOLERANCE,
    ):
        _scientific(path, "probabilities must form a distribution")
    return parsed


def _s1_probability_pair_distribution(
    values: tuple[tuple[str, str], ...],
    path: str,
) -> tuple[tuple[str, float], ...]:
    parsed = _reconstruct_probability_pairs(values, path)
    _s1_probability_distribution(tuple(value for _, value in values), path)
    return parsed


def _s1_non_negative(value: str, path: str) -> float:
    parsed = _float_from_f64(value, path)
    if parsed < 0.0:
        _scientific(path, "value must be non-negative")
    return parsed


def _s1_positive(value: str, path: str) -> float:
    parsed = _float_from_f64(value, path)
    if parsed <= 0.0:
        _scientific(path, "value must be positive")
    return parsed


def _validate_returned_run_s1_tags(projection: ReturnedRunProjection) -> None:
    for provenance_index, provenance in enumerate(_returned_provenance_occurrences(projection)):
        for detail_index, (_, provenance_value) in enumerate(provenance.details):
            path = f"returned_run.S1.tags.provenance[{provenance_index}][{detail_index}]"
            kind, value = provenance_value.kind, provenance_value.value
            valid = (
                (kind == "null" and value is None)
                or (kind == "bool" and type(value) is bool)
                or (kind == "i64" and type(value) is int)
                or (kind == "f64" and type(value) is str)
                or (kind == "string" and type(value) is str)
            )
            if not valid:
                _scientific(path, "provenance tag and payload do not couple")
    for control_index, control_value in enumerate(_returned_control_value_occurrences(projection)):
        path = f"returned_run.S1.tags.control_values[{control_index}]"
        valid = (
            (control_value.kind == "i64" and type(control_value.value) is int)
            or (control_value.kind == "f64" and type(control_value.value) is str)
            or (control_value.kind == "string" and type(control_value.value) is str)
        )
        if not valid:
            _scientific(path, "control-value tag and payload do not couple")
    for policy_index, policy in enumerate(_returned_policy_occurrences(projection)):
        nested = _policy_payload(policy)
        valid = (
            policy.kind == "decision_trace" and type(nested) is RunDecisionTraceProjection
        ) or (policy.kind == "lookahead_plan_trace" and type(nested) is RunLookaheadTraceProjection)
        if not valid:
            _scientific(
                f"returned_run.S1.tags.policy_traces[{policy_index}]",
                "policy tag and payload do not couple",
            )
    for action_index, second_action in enumerate(_returned_second_action_occurrences(projection)):
        if (second_action.action_effect == "stop") != (second_action.candidate is None):
            _scientific(
                f"returned_run.S1.tags.second_actions[{action_index}]",
                "stop tag and candidate payload do not couple",
            )


def _validate_returned_run_s1_enums(projection: ReturnedRunProjection) -> None:
    if projection.run_status not in {"complete", "invalid"}:
        _scientific("returned_run.S1.enums.run_status", "unknown run status")
    if projection.terminal_reason not in {
        "budget_exhausted",
        "candidate_space_exhausted",
        "integrity_abort",
    }:
        _scientific("returned_run.S1.enums.terminal_reason", "unknown terminal reason")
    for action_index, action in enumerate(projection.actions):
        if action.role not in {"optimizer_arm", "setup", "irrelevant", "redundant"}:
            _scientific(
                f"returned_run.S1.enums.actions[{action_index}].role",
                "unknown candidate role",
            )
    for effect_index, effect in enumerate(_returned_effect_occurrences(projection)):
        if effect.source_kind not in {"calibration", "decision"}:
            _scientific(
                f"returned_run.S1.enums.effects[{effect_index}].source_kind",
                "unknown effect source kind",
            )
    for sigma_index, sigma in enumerate(_returned_sigma_occurrences(projection)):
        if sigma.status not in {"fixed", "baseline_fallback", "calibrated"}:
            _scientific(
                f"returned_run.S1.enums.sigma[{sigma_index}].status",
                "unknown sigma-estimate status",
            )
    for diagnostic_index, diagnostic in enumerate(_returned_diagnostic_occurrences(projection)):
        if diagnostic.adequacy_state not in {"adequate", "uncertain", "appears_misspecified"}:
            _scientific(
                f"returned_run.S1.enums.diagnostics[{diagnostic_index}].adequacy_state",
                "unknown adequacy state",
            )
    allowed_effects = {"opens_pair", "completes_pair", "ineligible"}
    for first_index, first_action in enumerate(_returned_first_action_occurrences(projection)):
        if first_action.action_effect not in allowed_effects:
            _scientific(
                f"returned_run.S1.enums.first_actions[{first_index}].action_effect",
                "unknown public action effect",
            )
    for alternative_index, alternative in enumerate(_returned_alternative_occurrences(projection)):
        if alternative.action_effect not in allowed_effects:
            _scientific(
                f"returned_run.S1.enums.alternatives[{alternative_index}].action_effect",
                "unknown public action effect",
            )
    for second_index, second_action in enumerate(_returned_second_action_occurrences(projection)):
        if second_action.action_effect not in {*allowed_effects, "stop"}:
            _scientific(
                f"returned_run.S1.enums.second_actions[{second_index}].action_effect",
                "unknown public action effect",
            )
    for observation_index, observation in enumerate(_returned_observation_occurrences(projection)):
        if observation.authorization.kind not in {"calibration", "decision"}:
            _scientific(
                f"returned_run.S1.enums.observations[{observation_index}].authorization.kind",
                "unknown observation-authorization kind",
            )


def _validate_returned_run_s1_optional(projection: ReturnedRunProjection) -> None:
    for action_index, action in enumerate(projection.actions):
        path = f"returned_run.S1.optional.actions[{action_index}]"
        if (action.observed_objective is None) != (action.oracle_observation is None):
            _scientific(path, "outcome and Oracle optional fields do not couple")
        if (action.role == "setup") != (action.observed_objective is None):
            _scientific(path, "setup role and outcome optional fields do not couple")
    for observation_index, observation in enumerate(_returned_observation_occurrences(projection)):
        path = f"returned_run.S1.optional.observations[{observation_index}]"
        pair_missing = observation.comparison_group_id is None
        if pair_missing != (observation.intervention_arm is None):
            _scientific(path, "comparison group and intervention arm do not couple")
        if observation.authorization.kind == "calibration" and pair_missing:
            _scientific(path, "calibration observations require pair metadata")
    for sigma in _returned_sigma_occurrences(projection):
        _validate_sigma_coupling(sigma)
    for branch in _returned_branch_occurrences(projection):
        _validate_evidence_bound_coupling(branch)
    for score_index, score in enumerate(_returned_score_occurrences(projection)):
        if score.completes_matched_pair != (score.matched_experiment_id is not None):
            _scientific(
                f"returned_run.S1.optional.scores[{score_index}]",
                "matched-pair status and experiment reference do not couple",
            )
    for state_index, state in enumerate(_returned_belief_state_occurrences(projection)):
        if (state.sequence == 0) != (state.parent_belief_state_id is None):
            _scientific(
                f"returned_run.S1.optional.belief_states[{state_index}]",
                "state sequence and parent nullability do not couple",
            )


def _validate_returned_run_s1_numeric(projection: ReturnedRunProjection) -> None:
    for value, field in (
        (projection.budget, "budget"),
        (projection.calibration_cost, "calibration_cost"),
        (projection.decision_cost, "decision_cost"),
    ):
        _s1_non_negative(value, f"returned_run.S1.numeric.{field}")
    _s1_probability_pair_distribution(
        projection.initial_probabilities,
        "returned_run.S1.numeric.initial_probabilities",
    )
    for candidate_index, candidate in enumerate(_returned_candidate_occurrences(projection)):
        path = f"returned_run.S1.numeric.candidates[{candidate_index}]"
        _s1_positive(candidate.learning_rate, f"{path}.learning_rate")
        _s1_non_negative(candidate.regularization, f"{path}.regularization")
        if candidate.model_width <= 0:
            _scientific(f"{path}.model_width", "model width must be positive")
    for experiment_index, experiment in enumerate(projection.completed_experiments):
        _float_from_f64(
            experiment.observed_value,
            f"returned_run.S1.numeric.completed_experiments[{experiment_index}].observed_value",
        )
        if experiment.record_id <= 0:
            _scientific(
                f"returned_run.S1.numeric.completed_experiments[{experiment_index}].record_id",
                "record ID must be positive",
            )
    for evidence_index, evidence in enumerate(_returned_evidence_occurrences(projection)):
        _float_from_f64(
            evidence.observed_comparison,
            f"returned_run.S1.numeric.evidence[{evidence_index}].observed_comparison",
        )
        if not evidence.source_experiment_ids or any(
            source_id <= 0 for source_id in evidence.source_experiment_ids
        ):
            _scientific(
                f"returned_run.S1.numeric.evidence[{evidence_index}].source_experiment_ids",
                "evidence requires positive source experiment IDs",
            )
    for state_index, state in enumerate(_returned_belief_state_occurrences(projection)):
        path = f"returned_run.S1.numeric.belief_states[{state_index}]"
        _s1_probability_distribution(state.prior_probabilities, f"{path}.prior_probabilities")
        _s1_probability_distribution(
            state.posterior_probabilities,
            f"{path}.posterior_probabilities",
        )
        if state.sequence < 0:
            _scientific(f"{path}.sequence", "state sequence must be non-negative")
    for likelihood_index, likelihood in enumerate(_returned_likelihood_occurrences(projection)):
        path = f"returned_run.S1.numeric.likelihoods[{likelihood_index}]"
        for value, field in (
            (likelihood.likelihood, "likelihood"),
            (likelihood.posterior_probability, "posterior_probability"),
            (likelihood.prior_for_update, "prior_for_update"),
            (likelihood.unnormalized_weight, "unnormalized_weight"),
        ):
            _s1_non_negative(value, f"{path}.{field}")
    for update_index, update in enumerate(projection.updates):
        _s1_positive(
            update.bayesian_update.normalization_constant,
            f"returned_run.S1.numeric.updates[{update_index}].normalization_constant",
        )
    for effect_index, effect in enumerate(_returned_effect_occurrences(projection)):
        _float_from_f64(
            effect.observed_effect,
            f"returned_run.S1.numeric.effects[{effect_index}].observed_effect",
        )
        if effect.available_sequence < 0:
            _scientific(
                f"returned_run.S1.numeric.effects[{effect_index}].available_sequence",
                "effect availability must be non-negative",
            )
    for sigma_index, sigma in enumerate(_returned_sigma_occurrences(projection)):
        path = f"returned_run.S1.numeric.sigma[{sigma_index}]"
        if sigma.cutoff_sequence <= 0 or sigma.sample_count < 0:
            _scientific(path, "sigma sequence and sample count differ from their domains")
        estimated = _s1_positive(sigma.estimated_sigma, f"{path}.estimated_sigma")
        sigma_floor = _s1_positive(sigma.sigma_floor, f"{path}.sigma_floor")
        variance_floor = _s1_positive(sigma.variance_floor, f"{path}.variance_floor")
        if estimated < sigma_floor or not math.isclose(
            sigma_floor**2,
            variance_floor,
            rel_tol=0.0,
            abs_tol=1e-15,
        ):
            _scientific(path, "sigma estimate and floors do not couple")
        if sigma.sample_mean is not None:
            _float_from_f64(sigma.sample_mean, f"{path}.sample_mean")
        if sigma.raw_sample_standard_deviation is not None:
            _s1_non_negative(
                sigma.raw_sample_standard_deviation,
                f"{path}.raw_sample_standard_deviation",
            )
    for interval_index, interval in enumerate(_returned_interval_occurrences(projection)):
        path = f"returned_run.S1.numeric.intervals[{interval_index}]"
        probability = _float_from_f64(interval.probability, f"{path}.probability")
        lower = _float_from_f64(interval.lower, f"{path}.lower")
        upper = _float_from_f64(interval.upper, f"{path}.upper")
        if not 0.0 < probability < 1.0 or lower > upper:
            _scientific(path, "predictive interval domain differs")
    for diagnostic_index, diagnostic in enumerate(_returned_diagnostic_occurrences(projection)):
        path = f"returned_run.S1.numeric.diagnostics[{diagnostic_index}]"
        density = _s1_positive(diagnostic.predictive_density, f"{path}.predictive_density")
        variance = _s1_positive(diagnostic.predictive_variance, f"{path}.predictive_variance")
        del density, variance
        cdf = _float_from_f64(diagnostic.predictive_cdf, f"{path}.predictive_cdf")
        tail = _float_from_f64(
            diagnostic.posterior_predictive_tail_probability,
            f"{path}.posterior_predictive_tail_probability",
        )
        if not 0.0 <= cdf <= 1.0 or not 0.0 <= tail <= 1.0:
            _scientific(path, "diagnostic probabilities differ from their domains")
        for value, field in (
            (diagnostic.predictive_log_likelihood, "predictive_log_likelihood"),
            (diagnostic.predictive_mean, "predictive_mean"),
            (diagnostic.standardized_residual, "standardized_residual"),
        ):
            _float_from_f64(value, f"{path}.{field}")
        for residual_index, (_, value) in enumerate(diagnostic.per_hypothesis_residuals):
            _float_from_f64(value, f"{path}.per_hypothesis_residuals[{residual_index}][1]")
        if (
            diagnostic.residual_count <= 0
            or diagnostic.rolling_residual_outlier_count < 0
            or diagnostic.rolling_residual_outlier_count
            > min(RESIDUAL_WINDOW_SIZE, diagnostic.residual_count)
        ):
            _scientific(path, "diagnostic count domain differs")
    for context_index, context in enumerate(_returned_context_occurrences(projection)):
        path = f"returned_run.S1.numeric.contexts[{context_index}]"
        for value, field in (
            (context.most_favorable_outcome, "most_favorable_outcome"),
            (context.posterior_if_observed, "posterior_if_observed"),
            (context.posterior_probability, "posterior_probability"),
        ):
            parsed = _float_from_f64(value, f"{path}.{field}")
            if field != "most_favorable_outcome" and not 0.0 <= parsed <= 1.0:
                _scientific(f"{path}.{field}", "probability must be in [0, 1]")
    for score_index, score in enumerate(_returned_score_occurrences(projection)):
        path = f"returned_run.S1.numeric.scores[{score_index}]"
        for value, field in (
            (score.estimated_cost, "estimated_cost"),
            (score.expected_information_gain, "expected_information_gain"),
            (score.expected_posterior_entropy, "expected_posterior_entropy"),
            (score.prior_entropy, "prior_entropy"),
        ):
            _s1_non_negative(value, f"{path}.{field}")
        if score.matched_experiment_id is not None and score.matched_experiment_id <= 0:
            _scientific(f"{path}.matched_experiment_id", "experiment ID must be positive")
    for trace_index, decision_trace in enumerate(_returned_decision_trace_occurrences(projection)):
        _s1_non_negative(
            decision_trace.max_cost,
            f"returned_run.S1.numeric.decision_traces[{trace_index}].max_cost",
        )
    for trace_index, lookahead_trace in enumerate(
        _returned_lookahead_trace_occurrences(projection)
    ):
        path = f"returned_run.S1.numeric.lookahead_traces[{trace_index}]"
        _s1_non_negative(lookahead_trace.max_cost, f"{path}.max_cost")
        _s1_probability_pair_distribution(
            lookahead_trace.current_hypothesis_probabilities,
            f"{path}.current_hypothesis_probabilities",
        )
    for second_index, second_action in enumerate(_returned_second_action_occurrences(projection)):
        path = f"returned_run.S1.numeric.second_actions[{second_index}]"
        for value, field in (
            (second_action.estimated_cost, "estimated_cost"),
            (second_action.expected_information_gain, "expected_information_gain"),
            (second_action.information_gain_per_cost, "information_gain_per_cost"),
        ):
            _s1_non_negative(value, f"{path}.{field}")
    for branch_index, branch in enumerate(_returned_branch_occurrences(projection)):
        path = f"returned_run.S1.numeric.branches[{branch_index}]"
        probability = _float_from_f64(branch.probability, f"{path}.probability")
        if not 0.0 <= probability <= 1.0:
            _scientific(f"{path}.probability", "branch probability must be in [0, 1]")
        _s1_probability_pair_distribution(
            branch.posterior_probabilities,
            f"{path}.posterior_probabilities",
        )
        for value, field in (
            (branch.branch_total_cost, "branch_total_cost"),
            (branch.posterior_entropy, "posterior_entropy"),
            (branch.terminal_entropy, "terminal_entropy"),
        ):
            _s1_non_negative(value, f"{path}.{field}")
        bounds = tuple(
            None if value is None else _float_from_f64(value, f"{path}.{field}")
            for value, field in (
                (branch.evidence_lower_bound, "evidence_lower_bound"),
                (branch.evidence_upper_bound, "evidence_upper_bound"),
            )
        )
        if bounds[0] is not None and bounds[1] is not None and bounds[0] > bounds[1]:
            _scientific(path, "branch evidence bounds are reversed")
    for first_index, first_action in enumerate(_returned_first_action_occurrences(projection)):
        path = f"returned_run.S1.numeric.first_actions[{first_index}]"
        for value, field in (
            (first_action.expected_terminal_entropy, "expected_terminal_entropy"),
            (first_action.expected_total_cost, "expected_total_cost"),
            (first_action.expected_total_information_gain, "expected_total_information_gain"),
            (first_action.first_action_cost, "first_action_cost"),
            (first_action.immediate_information_gain, "immediate_information_gain"),
            (
                first_action.information_gain_per_expected_cost,
                "information_gain_per_expected_cost",
            ),
            (first_action.prior_entropy, "prior_entropy"),
        ):
            _s1_non_negative(value, f"{path}.{field}")
    for alternative_index, alternative in enumerate(_returned_alternative_occurrences(projection)):
        path = f"returned_run.S1.numeric.alternatives[{alternative_index}]"
        for value, field in (
            (alternative.expected_total_cost, "expected_total_cost"),
            (alternative.expected_total_information_gain, "expected_total_information_gain"),
            (alternative.immediate_information_gain, "immediate_information_gain"),
            (
                alternative.information_gain_per_expected_cost,
                "information_gain_per_expected_cost",
            ),
        ):
            _s1_non_negative(value, f"{path}.{field}")
    for decision_index, decision in enumerate(projection.decisions):
        _s1_non_negative(
            decision.remaining_budget,
            f"returned_run.S1.numeric.decisions[{decision_index}].remaining_budget",
        )
        if decision.step < 1:
            _scientific(
                f"returned_run.S1.numeric.decisions[{decision_index}].step",
                "decision step must be one-based",
            )
    for action_index, action in enumerate(projection.actions):
        path = f"returned_run.S1.numeric.actions[{action_index}]"
        cost = _s1_non_negative(action.cost, f"{path}.cost")
        cumulative = _s1_non_negative(
            action.cumulative_decision_cost,
            f"{path}.cumulative_decision_cost",
        )
        if action.step < 1 or cumulative < cost:
            _scientific(path, "action scalar domain differs")
        if action.observed_objective is not None:
            _float_from_f64(action.observed_objective, f"{path}.observed_objective")
        _s1_probability_pair_distribution(
            action.posterior_probabilities,
            f"{path}.posterior_probabilities",
        )
    for observation_index, observation in enumerate(_returned_observation_occurrences(projection)):
        _float_from_f64(
            observation.revealed_observation,
            f"returned_run.S1.numeric.observations[{observation_index}].revealed_observation",
        )
    calibration = projection.calibration
    if calibration is not None:
        _s1_non_negative(calibration.cost, "returned_run.S1.numeric.calibration.cost")
        for estimate_index, estimate in enumerate(calibration.estimates):
            path = f"returned_run.S1.numeric.calibration.estimates[{estimate_index}]"
            _s1_positive(estimate.estimated_sigma, f"{path}.estimated_sigma")
            _s1_non_negative(estimate.physical_cost, f"{path}.physical_cost")
            _s1_non_negative(
                estimate.raw_sample_standard_deviation,
                f"{path}.raw_sample_standard_deviation",
            )
            _float_from_f64(estimate.sample_mean, f"{path}.sample_mean")
            _s1_positive(estimate.sigma_floor, f"{path}.sigma_floor")
            if estimate.sample_count < 0 or estimate.source_sequence_cutoff < 0:
                _scientific(path, "calibration count or cutoff differs from its domain")


def _validate_returned_run_s1_pairs(projection: ReturnedRunProjection) -> None:
    for provenance_index, provenance in enumerate(_returned_provenance_occurrences(projection)):
        keys = tuple(key for key, _ in provenance.details)
        if keys != tuple(sorted(set(keys))):
            _scientific(
                f"returned_run.S1.pairs.provenance[{provenance_index}]",
                "provenance detail keys must be unique and sorted",
            )
    for design_index, design in enumerate(_returned_design_occurrences(projection)):
        names = tuple(name for name, _ in design.controlled_variables)
        if names != tuple(sorted(set(names))):
            _scientific(
                f"returned_run.S1.pairs.designs[{design_index}]",
                "controlled-variable names must be unique and sorted",
            )
    for diagnostic_index, diagnostic in enumerate(_returned_diagnostic_occurrences(projection)):
        residual_ids = tuple(item[0] for item in diagnostic.per_hypothesis_residuals)
        if not residual_ids or residual_ids != tuple(sorted(set(residual_ids))):
            _scientific(
                f"returned_run.S1.pairs.diagnostics[{diagnostic_index}]",
                "residual hypothesis IDs must be nonempty, unique, and sorted",
            )
    for effect_index, effect in enumerate(_returned_effect_occurrences(projection)):
        if not effect.source_ids or len(effect.source_ids) != len(set(effect.source_ids)):
            _scientific(
                f"returned_run.S1.pairs.effects[{effect_index}].source_ids",
                "effect source IDs must be nonempty and unique",
            )
        if effect.source_kind == "calibration" and len(effect.source_ids) != 2:
            _scientific(
                f"returned_run.S1.pairs.effects[{effect_index}].source_ids",
                "calibration effect requires one left/right source pair",
            )


def _s1_require_hypothesis_order(values: tuple[str, ...], path: str) -> None:
    expected = (ADAM_ADVANTAGE_ID, NO_ADVANTAGE_ID, SGD_ADVANTAGE_ID)
    if values != expected:
        _scientific(path, "hypothesis sequence differs from frozen registry order")


def _validate_returned_run_s1_sequences(projection: ReturnedRunProjection) -> None:
    _s1_require_hypothesis_order(
        tuple(item[0] for item in projection.initial_probabilities),
        "returned_run.S1.sequences.initial_probabilities",
    )
    for evidence_index, evidence in enumerate(_returned_evidence_occurrences(projection)):
        if evidence.source_experiment_ids != tuple(sorted(set(evidence.source_experiment_ids))):
            _scientific(
                f"returned_run.S1.sequences.evidence[{evidence_index}]",
                "source experiment IDs must be unique and sorted",
            )
    for state_index, state in enumerate(_returned_belief_state_occurrences(projection)):
        path = f"returned_run.S1.sequences.belief_states[{state_index}]"
        _s1_require_hypothesis_order(state.hypothesis_ids, f"{path}.hypothesis_ids")
        if (
            len(state.prior_probabilities) != len(state.hypothesis_ids)
            or len(state.posterior_probabilities) != len(state.hypothesis_ids)
            or state.sequence != len(state.evidence_ids)
            or len(state.evidence_ids) != len(set(state.evidence_ids))
        ):
            _scientific(path, "belief-state parallel sequence cardinality differs")
    for update_index, update in enumerate(projection.updates):
        likelihood_ids = tuple(item.hypothesis_id for item in update.bayesian_update.likelihoods)
        if likelihood_ids != update.bayesian_update.belief_state_before.hypothesis_ids:
            _scientific(
                f"returned_run.S1.sequences.updates[{update_index}].likelihoods",
                "likelihood order differs from the state hypothesis order",
            )
    for sigma_index, sigma in enumerate(_returned_sigma_occurrences(projection)):
        if (
            sigma.sample_count != len(sigma.source_effect_ids)
            or len(sigma.source_effect_ids) != len(set(sigma.source_effect_ids))
            or not sigma.current_evidence_excluded
        ):
            _scientific(
                f"returned_run.S1.sequences.sigma[{sigma_index}]",
                "sigma source sequence or exclusion flag differs",
            )
    expected_interval_probabilities = (0.50, 0.80, 0.95)
    for diagnostic_index, diagnostic in enumerate(_returned_diagnostic_occurrences(projection)):
        path = f"returned_run.S1.sequences.diagnostics[{diagnostic_index}]"
        probabilities = tuple(
            _float_from_f64(item.probability, f"{path}.central_intervals")
            for item in diagnostic.central_intervals
        )
        if probabilities != expected_interval_probabilities:
            _scientific(path, "central interval sequence differs")
        _s1_require_hypothesis_order(
            tuple(item[0] for item in diagnostic.per_hypothesis_residuals),
            f"{path}.per_hypothesis_residuals",
        )
    for trace_index, decision_trace in enumerate(_returned_decision_trace_occurrences(projection)):
        if (
            not decision_trace.ranked_candidates
            or decision_trace.ranked_candidates[0] != decision_trace.selected
        ):
            _scientific(
                f"returned_run.S1.sequences.decision_traces[{trace_index}]",
                "selected score must be first in recorded ranking order",
            )
        _s1_require_hypothesis_order(
            tuple(context.hypothesis_id for context in decision_trace.hypotheses),
            f"returned_run.S1.sequences.decision_traces[{trace_index}].hypotheses",
        )
    for trace_index, lookahead_trace in enumerate(
        _returned_lookahead_trace_occurrences(projection)
    ):
        _s1_require_hypothesis_order(
            tuple(
                hypothesis_id
                for hypothesis_id, _ in lookahead_trace.current_hypothesis_probabilities
            ),
            f"returned_run.S1.sequences.lookahead_traces[{trace_index}]",
        )
        if not lookahead_trace.selected.branches:
            _scientific(
                f"returned_run.S1.sequences.lookahead_traces[{trace_index}].branches",
                "selected first action must contain branches",
            )
        branch_probability = math.fsum(
            _float_from_f64(
                branch.probability,
                f"returned_run.S1.sequences.lookahead_traces[{trace_index}].branches",
            )
            for branch in lookahead_trace.selected.branches
        )
        if not math.isclose(
            branch_probability,
            1.0,
            rel_tol=0.0,
            abs_tol=PROBABILITY_TOLERANCE,
        ):
            _scientific(
                f"returned_run.S1.sequences.lookahead_traces[{trace_index}].branches",
                "branch probabilities must sum to one",
            )
        if any(not branch.budget_feasible for branch in lookahead_trace.selected.branches):
            _scientific(
                f"returned_run.S1.sequences.lookahead_traces[{trace_index}].branches",
                "selected plan contains an infeasible branch",
            )
    for action_index, action in enumerate(projection.actions):
        _s1_require_hypothesis_order(
            tuple(item[0] for item in action.posterior_probabilities),
            f"returned_run.S1.sequences.actions[{action_index}].posterior_probabilities",
        )
        if len(action.new_evidence_ids) != len(set(action.new_evidence_ids)):
            _scientific(
                f"returned_run.S1.sequences.actions[{action_index}].new_evidence_ids",
                "action evidence IDs must be unique",
            )
        if action.role == "setup" and action.new_evidence_ids:
            _scientific(
                f"returned_run.S1.sequences.actions[{action_index}].new_evidence_ids",
                "setup action cannot create evidence",
            )
    calibration = projection.calibration
    if calibration is not None:
        if len(calibration.estimates) != len(GROUP_IDS):
            _scientific(
                "returned_run.S1.sequences.calibration.estimates",
                "calibration estimate cardinality differs",
            )
        for estimate_index, estimate in enumerate(calibration.estimates):
            path = f"returned_run.S1.sequences.calibration.estimates[{estimate_index}]"
            if (
                len(estimate.effects) != 5
                or len(estimate.observations) != 10
                or estimate.sample_count != len(estimate.effects)
                or estimate.source_effect_ids
                != tuple(effect.effect_id for effect in estimate.effects)
            ):
                _scientific(path, "calibration fixed/parallel sequence differs")
        if len(calibration.effects) != sum(
            len(estimate.effects) for estimate in calibration.estimates
        ) or len(calibration.observations) != sum(
            len(estimate.observations) for estimate in calibration.estimates
        ):
            _scientific(
                "returned_run.S1.sequences.calibration",
                "calibration deployment sequence cardinality differs",
            )


def _validate_returned_run_s1(projection: ReturnedRunProjection) -> None:
    if projection.schema_version != "broader-replication-returned-run/v1":
        _structural("returned_run.schema_version", "unknown returned-run schema version")
    # Frozen global order: tags, enums, optionals, numeric domains, pair roles,
    # then fixed/parallel sequence relations.  Each pass traverses occurrences
    # in the handwritten payload order exposed by the helpers above.
    _validate_returned_run_s1_tags(projection)
    _validate_returned_run_s1_enums(projection)
    _validate_returned_run_s1_optional(projection)
    _validate_returned_run_s1_numeric(projection)
    _validate_returned_run_s1_pairs(projection)
    _validate_returned_run_s1_sequences(projection)


def _returned_observation_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunRevealedObservationProjection, ...]:
    result = tuple(
        item.oracle_observation
        for item in projection.actions
        if item.oracle_observation is not None
    )
    calibration = projection.calibration
    if calibration is None:
        return result
    estimates = tuple(
        observation for estimate in calibration.estimates for observation in estimate.observations
    )
    return (*result, *estimates, *calibration.observations)


type _ReturnedObservationContext = tuple[
    RunRevealedObservationProjection,
    Literal["calibration", "decision"],
    str,
    str,
    str,
]


def _calibration_observation_context(
    observation: RunRevealedObservationProjection,
    *,
    projection: ReturnedRunProjection,
    group_index: int,
    observation_index: int,
    path: str,
) -> _ReturnedObservationContext:
    comparison_group_id = GROUP_IDS[group_index]
    replication_index = (observation_index // 2) + 1
    intervention_arm = ("adam", "sgd")[observation_index % 2]
    candidate_id = f"cal-{group_index:02d}-{intervention_arm}-r{replication_index:04d}"
    calibration_prefix_id = (
        f"calibration-prefix/{projection.world_id}/{projection.seed}/{comparison_group_id}"
    )
    return (
        observation,
        "calibration",
        f"{calibration_prefix_id}/{candidate_id}",
        candidate_id,
        path,
    )


def _returned_observation_contexts(
    projection: ReturnedRunProjection,
) -> tuple[_ReturnedObservationContext, ...]:
    action_contexts: list[_ReturnedObservationContext] = []
    for action_index, action_projection in enumerate(projection.actions):
        observation = action_projection.oracle_observation
        if observation is not None:
            action_contexts.append(
                (
                    observation,
                    "decision",
                    action_projection.decision_id,
                    action_projection.candidate_id,
                    f"returned_run.S6.actions[{action_index}].oracle_observation",
                )
            )
    calibration = projection.calibration
    if calibration is None:
        return tuple(action_contexts)
    estimate_contexts = tuple(
        _calibration_observation_context(
            observation,
            projection=projection,
            group_index=group_index,
            observation_index=observation_index,
            path=(
                "returned_run.S6.calibration.estimates"
                f"[{group_index}].observations[{observation_index}]"
            ),
        )
        for group_index, estimate_projection in enumerate(calibration.estimates)
        for observation_index, observation in enumerate(estimate_projection.observations)
    )
    deployment_contexts = tuple(
        _calibration_observation_context(
            observation,
            projection=projection,
            group_index=observation_index // 10,
            observation_index=observation_index % 10,
            path=f"returned_run.S6.calibration.observations[{observation_index}]",
        )
        for observation_index, observation in enumerate(calibration.observations)
    )
    return (*action_contexts, *estimate_contexts, *deployment_contexts)


def _pure_revealed_observation(
    projection: RunRevealedObservationProjection,
    *,
    run_id: str,
    world_id: str,
    seed: int,
    expected_kind: Literal["calibration", "decision"],
    expected_source_id: str,
    expected_candidate_id: str,
    path: str,
) -> RevealedObservation:
    expected_authorization = RunObservationAuthorizationProjection(
        expected_candidate_id,
        expected_kind,
        run_id,
        expected_source_id,
    )
    expected_authorization_id = recompute_observation_authorization_id(expected_authorization)
    validate_observation_authorization_relation(
        projection.authorization,
        expected_candidate_id=expected_candidate_id,
        expected_kind=expected_kind,
        expected_run_id=run_id,
        expected_source_id=expected_source_id,
        expected_authorization_id=expected_authorization_id,
    )
    if not observation_authorization_projections_match(
        projection.authorization,
        expected_authorization,
    ):
        _scientific(
            f"{path}.authorization",
            "observation authorization differs from its enclosing action or calibration position",
        )
    world = WORLDS_BY_ID[world_id]
    if expected_kind == "decision":
        definition = CANDIDATES_BY_ID[expected_candidate_id]
        if definition.role == "setup":
            _scientific(path, "setup action has an Oracle observation")
        key = decision_key(
            world_id=world_id,
            seed=seed,
            candidate_id=definition.candidate_id,
            replication_id=definition.replication_id,
        )
        base_candidate_id = definition.candidate_id
        comparison_group_id = (
            definition.comparison_group_id if definition.role == "optimizer_arm" else None
        )
        intervention_arm = (
            definition.intervention_arm if definition.role == "optimizer_arm" else None
        )
        replication_id = definition.replication_id
    else:
        comparison_group_id, intervention_arm, replication_id = _parse_calibration_candidate(
            expected_candidate_id
        )
        base_candidate_id = f"g{comparison_group_id[-2:]}-{intervention_arm}-r1"
        key = calibration_key(
            world_id=world_id,
            seed=seed,
            comparison_group_id=comparison_group_id,
            intervention_arm=intervention_arm,
            replication_id=replication_id,
        )
    transform = transform_key(key)
    observed = hidden_arm_mean(world, base_candidate_id) + (
        hidden_observation_sigma(world, base_candidate_id) * transform.z
    )
    oracle_key_id = runtime_id(
        "oracle-key",
        "oracle_key_id/v1",
        {"key_fields": list(key)},
    )
    oracle_use_id = f"oracle-use/{expected_authorization_id}/{oracle_key_id}"
    outcome_digest = protocol_hash(
        "revealed_outcome/v1",
        {
            "oracle_key_id": oracle_key_id,
            "revealed_observation": f64(observed),
        },
    )
    expected_projection = RunRevealedObservationProjection(
        expected_authorization,
        expected_authorization_id,
        expected_candidate_id,
        comparison_group_id,
        transform.digest_hex,
        intervention_arm,
        key,
        key[0],
        oracle_key_id,
        oracle_use_id,
        outcome_digest,
        replication_id,
        f64(observed),
        seed,
        transform.serialized_key.hex(),
        transform.u_string,
        world_id,
        transform.z_string,
    )
    if not revealed_observation_projections_match(projection, expected_projection):
        _scientific(path, "Oracle observation does not reproduce")
    return RevealedObservation(
        oracle_key_id=expected_projection.oracle_key_id,
        oracle_use_id=expected_projection.oracle_use_id,
        authorization_id=expected_projection.authorization_id,
        namespace=expected_projection.namespace,
        world_id=expected_projection.world_id,
        seed=expected_projection.seed,
        candidate_id=expected_projection.candidate_id,
        comparison_group_id=expected_projection.comparison_group_id,
        intervention_arm=expected_projection.intervention_arm,
        replication_id=expected_projection.replication_id,
        key_fields=expected_projection.key_fields,
        serialized_key_hex=expected_projection.serialized_key_hex,
        digest=expected_projection.digest,
        u=expected_projection.u,
        z=expected_projection.z,
        revealed_observation=observed,
        outcome_digest=expected_projection.outcome_digest,
    )


def _validate_returned_run_s6(
    projection: ReturnedRunProjection,
) -> dict[RunRevealedObservationProjection, RevealedObservation]:
    reconstructed: dict[RunRevealedObservationProjection, RevealedObservation] = {}
    for observation, kind, source_id, candidate_id, path in _returned_observation_contexts(
        projection
    ):
        reconstructed[observation] = _scientific_call(
            path,
            _pure_revealed_observation,
            observation,
            run_id=projection.run_id,
            world_id=projection.world_id,
            seed=projection.seed,
            expected_kind=kind,
            expected_source_id=source_id,
            expected_candidate_id=candidate_id,
            path=path,
        )
    return reconstructed


def _returned_effect_occurrences(
    projection: ReturnedRunProjection,
) -> tuple[RunMatchedEffectProjection, ...]:
    calibration = projection.calibration
    nested: tuple[RunMatchedEffectProjection, ...] = ()
    if calibration is not None:
        nested = (
            *calibration.effects,
            *(item for estimate in calibration.estimates for item in estimate.effects),
        )
    return (*nested, *projection.effect_history)


def _construct_returned_run_s2(
    projection: ReturnedRunProjection,
) -> tuple[dict[object, object], tuple[CompletedExperiment, ...], tuple[Evidence, ...]]:
    cache: dict[object, object] = {}
    for index, candidate_projection in enumerate(_returned_candidate_occurrences(projection)):
        cache[candidate_projection] = _scientific_call(
            f"returned_run.S2.candidates[{index}]",
            reconstruct_candidate,
            candidate_projection,
        )
    completed_items: list[CompletedExperiment] = []
    for index, completed_projection in enumerate(projection.completed_experiments):
        completed_args = (
            completed_projection.record_id,
            cast(Candidate, cache[completed_projection.candidate]),
            _float_from_f64(
                completed_projection.observed_value,
                "completed_experiment.observed_value",
            ),
            completed_projection.created_at,
        )
        completed_items.append(
            _scientific_call(
                f"returned_run.S2.completed_experiments[{index}]",
                _rebuild,
                "completed_experiment",
                CompletedExperiment,
                completed_args,
                completed_projection,
                project_completed_experiment,
            )
        )
    completed = tuple(completed_items)
    cache.update(zip(projection.completed_experiments, completed, strict=True))
    for index, provenance_projection in enumerate(_returned_provenance_occurrences(projection)):
        cache[provenance_projection] = _scientific_call(
            f"returned_run.S2.provenances[{index}]",
            reconstruct_provenance,
            provenance_projection,
        )
    for index, evidence_projection in enumerate(_returned_evidence_occurrences(projection)):
        cache[evidence_projection] = _scientific_call(
            f"returned_run.S2.evidence[{index}]",
            _reconstruct_evidence,
            evidence_projection,
            cast(Provenance, cache[evidence_projection.provenance]),
        )
    for index, state_projection in enumerate(_returned_belief_state_occurrences(projection)):
        cache[state_projection] = _scientific_call(
            f"returned_run.S2.belief_states[{index}]",
            reconstruct_belief_state,
            state_projection,
        )
    for index, likelihood_projection in enumerate(_returned_likelihood_occurrences(projection)):
        cache[likelihood_projection] = _scientific_call(
            f"returned_run.S2.likelihoods[{index}]",
            reconstruct_hypothesis_likelihood,
            likelihood_projection,
        )
    evidence = tuple(
        cast(Evidence, cache[evidence_projection]) for evidence_projection in projection.evidence
    )
    return cache, completed, evidence


def _sigma_from_s3(item: RunSigmaEstimateProjection, cache: dict[object, object]) -> SigmaEstimate:
    _validate_sigma_coupling(item)
    path = "sigma_estimate"
    args = (
        item.estimate_id,
        item.belief_model_id,
        item.belief_model_version,
        item.lineage_id,
        item.evidence_id,
        item.comparison_group_id,
        item.cutoff_sequence,
        item.source_effect_ids,
        item.sample_count,
        (
            None
            if item.sample_mean is None
            else _float_from_f64(item.sample_mean, f"{path}.sample_mean")
        ),
        (
            None
            if item.raw_sample_standard_deviation is None
            else _float_from_f64(
                item.raw_sample_standard_deviation,
                f"{path}.raw_sample_standard_deviation",
            )
        ),
        _float_from_f64(item.sigma_floor, f"{path}.sigma_floor"),
        _float_from_f64(item.variance_floor, f"{path}.variance_floor"),
        _float_from_f64(item.estimated_sigma, f"{path}.estimated_sigma"),
        item.status,
        item.estimator_version,
        item.current_evidence_excluded,
        item.created_at,
        cast(Provenance, cache[item.provenance]),
    )
    return _rebuild(path, SigmaEstimate, args, item, project_sigma_estimate)


def _diagnostic_from_s3(
    item: RunDiagnosticProjection,
    cache: dict[object, object],
) -> ModelAdequacyDiagnostic:
    path = "diagnostic"
    residuals = tuple(
        (hypothesis_id, _float_from_f64(value, f"{path}.per_hypothesis_residuals[{index}][1]"))
        for index, (hypothesis_id, value) in enumerate(item.per_hypothesis_residuals)
    )
    args = (
        item.diagnostic_id,
        item.belief_model_id,
        item.belief_model_version,
        item.lineage_id,
        item.belief_state_before_id,
        item.evidence_id,
        item.sigma_estimate_id,
        item.comparison_group_id,
        _float_from_f64(item.predictive_mean, f"{path}.predictive_mean"),
        _float_from_f64(item.predictive_variance, f"{path}.predictive_variance"),
        _float_from_f64(item.predictive_density, f"{path}.predictive_density"),
        _float_from_f64(item.predictive_log_likelihood, f"{path}.predictive_log_likelihood"),
        _float_from_f64(item.predictive_cdf, f"{path}.predictive_cdf"),
        _float_from_f64(
            item.posterior_predictive_tail_probability,
            f"{path}.posterior_predictive_tail_probability",
        ),
        _float_from_f64(item.standardized_residual, f"{path}.standardized_residual"),
        residuals,
        tuple(cast(PredictiveInterval, cache[value]) for value in item.central_intervals),
        item.residual_count,
        item.rolling_residual_outlier_count,
        item.tail_alarm,
        item.residual_outlier,
        item.repeated_residual_alarm,
        item.diagnostics_disagree,
        item.adequacy_state,
        item.diagnostic_version,
        item.created_at,
        cast(Provenance, cache[item.provenance]),
    )
    return _rebuild(path, ModelAdequacyDiagnostic, args, item, project_diagnostic)


def _construct_returned_run_s3(
    projection: ReturnedRunProjection,
    cache: dict[object, object],
) -> tuple[
    BeliefModelLineage,
    tuple[ModelBeliefUpdate, ...],
    tuple[ModelAdequacyDiagnostic, ...],
    tuple[MatchedEffectObservation, ...],
    dict[RunMatchedEffectProjection, MatchedEffectObservation],
]:
    # S3 declared type order: Bayesian update, model state, lineage, interval,
    # matched effect, sigma, diagnostic, then enclosing model update.
    for index, model_update_projection in enumerate(projection.updates):
        belief_update_projection = model_update_projection.bayesian_update
        belief_update_args = (
            belief_update_projection.update_id,
            cast(
                BeliefState,
                cache[belief_update_projection.belief_state_before],
            ),
            cast(Evidence, cache[belief_update_projection.evidence]),
            tuple(
                cast(HypothesisLikelihood, cache[likelihood_projection])
                for likelihood_projection in belief_update_projection.likelihoods
            ),
            cast(
                BeliefState,
                cache[belief_update_projection.posterior_belief_state],
            ),
            belief_update_projection.update_rule_version,
            _float_from_f64(
                belief_update_projection.normalization_constant,
                "belief_update.normalization_constant",
            ),
            cast(Provenance, cache[belief_update_projection.provenance]),
            belief_update_projection.created_at,
        )
        belief_update = _scientific_call(
            f"returned_run.S3.belief_updates[{index}]",
            _rebuild,
            "belief_update",
            BeliefUpdate,
            belief_update_args,
            belief_update_projection,
            project_belief_update,
        )
        _validate_belief_update_relations(belief_update)
        cache[belief_update_projection] = belief_update
    for index, model_state_projection in enumerate(_returned_model_state_occurrences(projection)):
        model_state_args = (
            model_state_projection.belief_model_id,
            model_state_projection.belief_model_version,
            model_state_projection.lineage_id,
            cast(BeliefState, cache[model_state_projection.state]),
        )
        cache[model_state_projection] = _scientific_call(
            f"returned_run.S3.model_states[{index}]",
            _rebuild,
            "model_belief_state",
            ModelBeliefState,
            model_state_args,
            model_state_projection,
            project_model_belief_state,
        )
    lineage_args = (
        projection.lineage.lineage_id,
        projection.lineage.belief_model_id,
        projection.lineage.belief_model_version,
        projection.lineage.lineage_key,
        cast(ModelBeliefState, cache[projection.lineage.current_state]),
        projection.lineage.created_at,
    )
    lineage = _scientific_call(
        "returned_run.S3.lineage",
        _rebuild,
        "lineage",
        BeliefModelLineage,
        lineage_args,
        projection.lineage,
        project_lineage,
    )
    cache[projection.lineage] = lineage
    diagnostic_occurrences = _returned_diagnostic_occurrences(projection)
    for index, interval_projection in enumerate(_returned_interval_occurrences(projection)):
        cache[interval_projection] = _scientific_call(
            f"returned_run.S3.intervals[{index}]",
            _reconstruct_predictive_interval,
            interval_projection,
            "predictive_interval",
        )
    effect_by_projection: dict[RunMatchedEffectProjection, MatchedEffectObservation] = {}
    for index, effect_projection in enumerate(_returned_effect_occurrences(projection)):
        effect_args = (
            effect_projection.effect_id,
            effect_projection.comparison_group_id,
            _float_from_f64(
                effect_projection.observed_effect,
                "matched_effect.observed_effect",
            ),
            effect_projection.available_sequence,
            effect_projection.source_kind,
            effect_projection.source_ids,
            effect_projection.created_at,
            cast(Provenance, cache[effect_projection.provenance]),
        )
        effect = _scientific_call(
            f"returned_run.S3.effects[{index}]",
            _rebuild,
            "matched_effect",
            MatchedEffectObservation,
            effect_args,
            effect_projection,
            project_matched_effect,
        )
        effect_by_projection[effect_projection] = effect
        cache[effect_projection] = effect
    for index, model_update_projection in enumerate(projection.updates):
        sigma_projection = model_update_projection.sigma_estimate
        cache[sigma_projection] = _scientific_call(
            f"returned_run.S3.sigma[{index}]",
            _sigma_from_s3,
            sigma_projection,
            cache,
        )
    for index, diagnostic_projection in enumerate(diagnostic_occurrences):
        cache[diagnostic_projection] = _scientific_call(
            f"returned_run.S3.diagnostics[{index}]",
            _diagnostic_from_s3,
            diagnostic_projection,
            cache,
        )
    updates: list[ModelBeliefUpdate] = []
    for index, model_update_projection in enumerate(projection.updates):
        model_update_args = (
            model_update_projection.model_update_id,
            model_update_projection.belief_model_id,
            model_update_projection.belief_model_version,
            model_update_projection.lineage_id,
            cast(ModelBeliefState, cache[model_update_projection.state_before]),
            cast(Evidence, cache[model_update_projection.evidence]),
            cast(SigmaEstimate, cache[model_update_projection.sigma_estimate]),
            cast(BeliefUpdate, cache[model_update_projection.bayesian_update]),
            cast(
                ModelBeliefState,
                cache[model_update_projection.posterior_state],
            ),
            cast(
                ModelAdequacyDiagnostic,
                cache[model_update_projection.diagnostic],
            ),
            model_update_projection.created_at,
            cast(Provenance, cache[model_update_projection.provenance]),
        )
        update = _scientific_call(
            f"returned_run.S3.model_updates[{index}]",
            _rebuild,
            "model_update",
            ModelBeliefUpdate,
            model_update_args,
            model_update_projection,
            project_model_update,
        )
        cache[model_update_projection] = update
        updates.append(update)
    diagnostics = tuple(
        cast(ModelAdequacyDiagnostic, cache[diagnostic_projection])
        for diagnostic_projection in projection.diagnostics
    )
    effects = tuple(
        effect_by_projection[effect_projection] for effect_projection in projection.effect_history
    )
    return lineage, tuple(updates), diagnostics, effects, effect_by_projection


def _construct_returned_run_s4(
    projection: ReturnedRunProjection,
    cache: dict[object, object],
) -> None:
    decision_traces = _returned_decision_trace_occurrences(projection)
    for index, design_projection in enumerate(_returned_design_occurrences(projection)):
        cache[design_projection] = _scientific_call(
            f"returned_run.S4.designs[{index}]",
            reconstruct_public_experiment_design,
            design_projection,
        )
    for index, context_projection in enumerate(_returned_context_occurrences(projection)):
        cache[context_projection] = _scientific_call(
            f"returned_run.S4.contexts[{index}]",
            reconstruct_hypothesis_decision_context,
            context_projection,
        )
    for index, score_projection in enumerate(_returned_score_occurrences(projection)):
        path = "candidate_score"
        score_args = (
            cast(Candidate, cache[score_projection.candidate]),
            _float_from_f64(
                score_projection.expected_information_gain,
                f"{path}.expected_information_gain",
            ),
            _float_from_f64(score_projection.prior_entropy, f"{path}.prior_entropy"),
            _float_from_f64(
                score_projection.expected_posterior_entropy,
                f"{path}.expected_posterior_entropy",
            ),
            _float_from_f64(
                score_projection.estimated_cost,
                f"{path}.estimated_cost",
            ),
            score_projection.completes_matched_pair,
            score_projection.matched_experiment_id,
            score_projection.score_reason,
            score_projection.ranking_reason,
        )
        cache[score_projection] = _scientific_call(
            f"returned_run.S4.scores[{index}]",
            _rebuild,
            path,
            CandidateScore,
            score_args,
            score_projection,
            project_candidate_score,
        )
    for index, decision_trace_projection in enumerate(decision_traces):
        decision_trace_args = (
            decision_trace_projection.suggestion_id,
            decision_trace_projection.policy,
            decision_trace_projection.policy_version,
            decision_trace_projection.created_at,
            decision_trace_projection.belief_state_id,
            cast(CandidateScore, cache[decision_trace_projection.selected]),
            tuple(
                cast(HypothesisDecisionContext, cache[context_projection])
                for context_projection in decision_trace_projection.hypotheses
            ),
            _float_from_f64(decision_trace_projection.max_cost, "decision_trace.max_cost"),
            decision_trace_projection.fallback_reason,
            decision_trace_projection.rationale,
            tuple(
                cast(CandidateScore, cache[score_projection])
                for score_projection in decision_trace_projection.ranked_candidates
            ),
            cast(Provenance, cache[decision_trace_projection.provenance]),
        )
        decision_trace = _scientific_call(
            f"returned_run.S4.traces[{index}]",
            _rebuild,
            "decision_trace",
            DecisionTrace,
            decision_trace_args,
            decision_trace_projection,
            project_decision_trace,
        )
        cache[decision_trace_projection] = decision_trace


def _construct_returned_run_s5(
    projection: ReturnedRunProjection,
    cache: dict[object, object],
) -> dict[RunPolicyTraceProjection, DecisionTrace | LookaheadPlanTrace]:
    traces: dict[RunPolicyTraceProjection, DecisionTrace | LookaheadPlanTrace] = {}
    lookahead_traces = _returned_lookahead_trace_occurrences(projection)
    for index, second_projection in enumerate(_returned_second_action_occurrences(projection)):
        second_action_args = (
            (
                None
                if second_projection.candidate is None
                else cast(Candidate, cache[second_projection.candidate])
            ),
            second_projection.action_effect,
            _from_lf64(
                second_projection.expected_information_gain,
                "lookahead_second_action",
                "expected_information_gain",
            ),
            _from_lf64(
                second_projection.estimated_cost,
                "lookahead_second_action",
                "estimated_cost",
            ),
            _from_lf64(
                second_projection.information_gain_per_cost,
                "lookahead_second_action",
                "information_gain_per_cost",
            ),
            second_projection.reason,
        )
        cache[second_projection] = _scientific_call(
            f"returned_run.S5.second_actions[{index}]",
            _rebuild,
            "lookahead_second_action",
            LookaheadSecondAction,
            second_action_args,
            second_projection,
            project_lookahead_second_action,
        )
    for index, branch_projection in enumerate(_returned_branch_occurrences(projection)):
        branch_args = (
            branch_projection.branch_id,
            branch_projection.label,
            _from_lf64(
                branch_projection.probability,
                "lookahead_branch",
                "probability",
            ),
            (
                None
                if branch_projection.evidence_lower_bound is None
                else _from_lf64(
                    branch_projection.evidence_lower_bound,
                    "lookahead_branch",
                    "evidence_lower_bound",
                )
            ),
            (
                None
                if branch_projection.evidence_upper_bound is None
                else _from_lf64(
                    branch_projection.evidence_upper_bound,
                    "lookahead_branch",
                    "evidence_upper_bound",
                )
            ),
            _reconstruct_probability_pairs(
                branch_projection.posterior_probabilities,
                "lookahead_branch.posterior_probabilities",
            ),
            _from_lf64(
                branch_projection.posterior_entropy,
                "lookahead_branch",
                "posterior_entropy",
            ),
            cast(LookaheadSecondAction, cache[branch_projection.second_action]),
            _from_lf64(
                branch_projection.terminal_entropy,
                "lookahead_branch",
                "terminal_entropy",
            ),
            _from_lf64(
                branch_projection.branch_total_cost,
                "lookahead_branch",
                "branch_total_cost",
            ),
            branch_projection.budget_feasible,
        )
        cache[branch_projection] = _scientific_call(
            f"returned_run.S5.branches[{index}]",
            _rebuild,
            "lookahead_branch",
            LookaheadBranch,
            branch_args,
            branch_projection,
            project_lookahead_branch,
        )
    for index, first_projection in enumerate(_returned_first_action_occurrences(projection)):
        first_action_args = (
            cast(Candidate, cache[first_projection.candidate]),
            cast(PublicExperimentDesign, cache[first_projection.public_design]),
            first_projection.action_effect,
            _from_lf64(
                first_projection.first_action_cost,
                "lookahead_first_action",
                "first_action_cost",
            ),
            _from_lf64(
                first_projection.prior_entropy,
                "lookahead_first_action",
                "prior_entropy",
            ),
            _from_lf64(
                first_projection.immediate_information_gain,
                "lookahead_first_action",
                "immediate_information_gain",
            ),
            _from_lf64(
                first_projection.expected_terminal_entropy,
                "lookahead_first_action",
                "expected_terminal_entropy",
            ),
            _from_lf64(
                first_projection.expected_total_information_gain,
                "lookahead_first_action",
                "expected_total_information_gain",
            ),
            _from_lf64(
                first_projection.expected_total_cost,
                "lookahead_first_action",
                "expected_total_cost",
            ),
            _from_lf64(
                first_projection.information_gain_per_expected_cost,
                "lookahead_first_action",
                "information_gain_per_expected_cost",
            ),
            tuple(
                cast(LookaheadBranch, cache[branch_projection])
                for branch_projection in first_projection.branches
            ),
            first_projection.ranking_reason,
        )
        cache[first_projection] = _scientific_call(
            f"returned_run.S5.first_actions[{index}]",
            _rebuild,
            "lookahead_first_action",
            LookaheadFirstActionPlan,
            first_action_args,
            first_projection,
            project_lookahead_first_action,
        )
    for index, alternative_projection in enumerate(_returned_alternative_occurrences(projection)):
        alternative_args = (
            cast(Candidate, cache[alternative_projection.candidate]),
            alternative_projection.action_effect,
            alternative_projection.comparison_group_id,
            _from_lf64(
                alternative_projection.immediate_information_gain,
                "lookahead_alternative",
                "immediate_information_gain",
            ),
            _from_lf64(
                alternative_projection.expected_total_information_gain,
                "lookahead_alternative",
                "expected_total_information_gain",
            ),
            _from_lf64(
                alternative_projection.expected_total_cost,
                "lookahead_alternative",
                "expected_total_cost",
            ),
            _from_lf64(
                alternative_projection.information_gain_per_expected_cost,
                "lookahead_alternative",
                "information_gain_per_expected_cost",
            ),
            alternative_projection.ranking_reason,
        )
        cache[alternative_projection] = _scientific_call(
            f"returned_run.S5.alternatives[{index}]",
            _rebuild,
            "lookahead_alternative",
            LookaheadAlternative,
            alternative_args,
            alternative_projection,
            project_lookahead_alternative,
        )
    for index, lookahead_trace_projection in enumerate(lookahead_traces):
        lookahead_trace_args = (
            lookahead_trace_projection.plan_id,
            lookahead_trace_projection.policy,
            lookahead_trace_projection.policy_version,
            lookahead_trace_projection.created_at,
            lookahead_trace_projection.belief_state_id,
            _reconstruct_probability_pairs(
                lookahead_trace_projection.current_hypothesis_probabilities,
                "lookahead_trace.current_hypothesis_probabilities",
            ),
            lookahead_trace_projection.completed_state_fingerprint,
            lookahead_trace_projection.candidate_set_fingerprint,
            _from_lf64(lookahead_trace_projection.max_cost, "lookahead_trace", "max_cost"),
            cast(LookaheadFirstActionPlan, cache[lookahead_trace_projection.selected]),
            tuple(
                cast(LookaheadAlternative, cache[alternative_projection])
                for alternative_projection in lookahead_trace_projection.alternatives
            ),
            lookahead_trace_projection.tie_breaking_order,
            lookahead_trace_projection.fallback_reason,
            lookahead_trace_projection.rationale,
            cast(Provenance, cache[lookahead_trace_projection.provenance]),
        )
        lookahead_trace = _scientific_call(
            f"returned_run.S5.traces[{index}]",
            _rebuild,
            "lookahead_trace",
            LookaheadPlanTrace,
            lookahead_trace_args,
            lookahead_trace_projection,
            project_lookahead_trace,
        )
        cache[lookahead_trace_projection] = lookahead_trace
    for policy_projection in _returned_policy_occurrences(projection):
        traces[policy_projection] = cast(
            DecisionTrace | LookaheadPlanTrace,
            cache[_policy_payload(policy_projection)],
        )
    return traces


def _construct_calibration_estimate_s7(
    projection: RunCalibrationEstimateProjection,
    observations: dict[RunRevealedObservationProjection, RevealedObservation],
    effects: dict[RunMatchedEffectProjection, MatchedEffectObservation],
) -> CalibrationGroupEstimate:
    args = (
        projection.sigma_estimate_id,
        projection.calibration_prefix_id,
        projection.comparison_group_id,
        projection.source_effect_ids,
        projection.source_sequence_cutoff,
        projection.sample_count,
        _float_from_f64(projection.sample_mean, "returned_run.S7.sample_mean"),
        _float_from_f64(
            projection.raw_sample_standard_deviation,
            "returned_run.S7.raw_sample_standard_deviation",
        ),
        projection.ddof,
        _float_from_f64(projection.sigma_floor, "returned_run.S7.sigma_floor"),
        _float_from_f64(projection.estimated_sigma, "returned_run.S7.estimated_sigma"),
        projection.belief_model_id,
        projection.lineage_id,
        projection.provenance_sha256,
        tuple(effects[item] for item in projection.effects),
        tuple(observations[item] for item in projection.observations),
        _float_from_f64(projection.physical_cost, "returned_run.S7.physical_cost"),
    )
    result = CalibrationGroupEstimate(*args)
    projected_effects = tuple(project_matched_effect(effect) for effect in result.effects)
    projected_observations = tuple(
        _project_revealed_observation(
            observation,
            observation_projection.authorization,
            validate_science=True,
        )
        for observation_projection, observation in zip(
            projection.observations,
            result.observations,
            strict=True,
        )
    )
    declared_fields: tuple[tuple[object, object, str], ...] = (
        (result.sigma_estimate_id, projection.sigma_estimate_id, "sigma_estimate_id"),
        (
            result.calibration_prefix_id,
            projection.calibration_prefix_id,
            "calibration_prefix_id",
        ),
        (
            result.comparison_group_id,
            projection.comparison_group_id,
            "comparison_group_id",
        ),
        (result.source_effect_ids, projection.source_effect_ids, "source_effect_ids"),
        (
            result.source_sequence_cutoff,
            projection.source_sequence_cutoff,
            "source_sequence_cutoff",
        ),
        (result.sample_count, projection.sample_count, "sample_count"),
        (f64(result.sample_mean), projection.sample_mean, "sample_mean"),
        (
            f64(result.raw_sample_standard_deviation),
            projection.raw_sample_standard_deviation,
            "raw_sample_standard_deviation",
        ),
        (result.ddof, projection.ddof, "ddof"),
        (f64(result.sigma_floor), projection.sigma_floor, "sigma_floor"),
        (f64(result.estimated_sigma), projection.estimated_sigma, "estimated_sigma"),
        (result.belief_model_id, projection.belief_model_id, "belief_model_id"),
        (result.lineage_id, projection.lineage_id, "lineage_id"),
        (
            result.provenance_sha256,
            projection.provenance_sha256,
            "provenance_sha256",
        ),
        (projected_effects, projection.effects, "effects"),
        (projected_observations, projection.observations, "observations"),
        (f64(result.physical_cost), projection.physical_cost, "physical_cost"),
    )
    for actual, expected, field in declared_fields:
        if actual != expected:
            _scientific(
                f"returned_run.S7.calibration_estimate.{field}",
                "field-total comparison failed",
            )
    return result


def _construct_returned_run_s7(
    projection: RunCalibrationProjection | None,
    observations: dict[RunRevealedObservationProjection, RevealedObservation],
    effects: dict[RunMatchedEffectProjection, MatchedEffectObservation],
) -> CalibrationDeployment | None:
    if projection is None:
        return None
    comparison_group_ids = tuple(
        estimate_projection.comparison_group_id for estimate_projection in projection.estimates
    )
    if comparison_group_ids != GROUP_IDS:
        _scientific(
            "returned_run.S7.estimates.comparison_group_id",
            "calibration estimates are not in exact GROUP_IDS order",
        )
    estimates = tuple(
        _scientific_call(
            f"returned_run.S7.estimates[{index}]",
            _construct_calibration_estimate_s7,
            estimate_projection,
            observations,
            effects,
        )
        for index, estimate_projection in enumerate(projection.estimates)
    )
    result = CalibrationDeployment(
        estimates,
        tuple(effects[effect_projection] for effect_projection in projection.effects),
        tuple(
            observations[observation_projection]
            for observation_projection in projection.observations
        ),
        _float_from_f64(projection.cost, "returned_run.S7.cost"),
    )
    projected_observations = tuple(
        _project_revealed_observation(
            observation,
            observation_projection.authorization,
            validate_science=True,
        )
        for observation_projection, observation in zip(
            projection.observations,
            result.observations,
            strict=True,
        )
    )
    declared_fields: tuple[tuple[object, object, str], ...] = (
        (result.estimates, estimates, "estimates"),
        (
            tuple(project_matched_effect(effect) for effect in result.effects),
            projection.effects,
            "effects",
        ),
        (projected_observations, projection.observations, "observations"),
        (f64(result.cost), projection.cost, "cost"),
    )
    for actual, expected, field in declared_fields:
        if actual != expected:
            _scientific(
                f"returned_run.S7.calibration.{field}",
                "field-total comparison failed",
            )
    return result


def _arm_action_from_s8(
    projection: RunArmActionProjection,
    observation: RevealedObservation | None,
) -> ArmAction:
    return ArmAction(
        projection.step,
        projection.candidate_id,
        projection.role,
        _float_from_f64(projection.cost, "returned_run.S8.action.cost"),
        _float_from_f64(
            projection.cumulative_decision_cost,
            "returned_run.S8.action.cumulative_decision_cost",
        ),
        projection.decision_id,
        (
            None
            if projection.observed_objective is None
            else _float_from_f64(
                projection.observed_objective,
                "returned_run.S8.action.observed_objective",
            )
        ),
        observation,
        projection.new_evidence_ids,
        _reconstruct_probability_pairs(
            projection.posterior_probabilities,
            "returned_run.S8.action.posterior_probabilities",
        ),
    )


def _arm_decision_from_s8(
    projection: RunArmDecisionProjection,
    trace: DecisionTrace | LookaheadPlanTrace,
) -> ArmDecision:
    return ArmDecision(
        projection.decision_id,
        projection.step,
        projection.selected_candidate_id,
        _float_from_f64(projection.remaining_budget, "returned_run.S8.decision.remaining_budget"),
        projection.belief_state_id,
        projection.public_feasible_candidate_ids,
        projection.affordable_candidate_ids,
        trace,
        projection.fixed_policy_regression_match,
    )


def _construct_returned_run_s8(
    projection: ReturnedRunProjection,
    *,
    completed: tuple[CompletedExperiment, ...],
    evidence: tuple[Evidence, ...],
    lineage: BeliefModelLineage,
    updates: tuple[ModelBeliefUpdate, ...],
    diagnostics: tuple[ModelAdequacyDiagnostic, ...],
    effects: tuple[MatchedEffectObservation, ...],
    calibration: CalibrationDeployment | None,
    observations: dict[RunRevealedObservationProjection, RevealedObservation],
    traces: dict[RunPolicyTraceProjection, DecisionTrace | LookaheadPlanTrace],
) -> BroaderArmRun:
    # S8.1: resolve and compare the complete frozen arm before any world fact.
    arm_id, arm_order, belief_model_id, policy_id = projection.arm
    arm = _scientific_call("returned_run.S8.arm", lambda: arm_spec(arm_id))
    if (arm.arm_id, arm.arm_order, arm.belief_model_id, arm.policy_id) != (
        arm_id,
        arm_order,
        belief_model_id,
        policy_id,
    ):
        _scientific("returned_run.S8.arm", "frozen arm differs")

    # S8.2: resolve the world, then its one admitted budget ID/value pair.
    world = _scientific_call(
        "returned_run.S8.world_id",
        lambda: WORLDS_BY_ID[projection.world_id],
    )
    budget = _float_from_f64(projection.budget, "returned_run.S8.budget")
    budget_matches = tuple(
        value for budget_id, value in BUDGETS if budget_id == projection.budget_id
    )
    if (
        len(budget_matches) != 1
        or projection.budget_id not in world.public.budget_ids
        or f64(budget_matches[0]) != projection.budget
    ):
        _scientific("returned_run.S8.budget", "frozen budget relation differs")

    # Construct the child records once, in the declared ArmDecision/ArmAction order.
    try:
        decisions = tuple(
            _arm_decision_from_s8(item, traces[item.policy_trace]) for item in projection.decisions
        )
        actions = tuple(
            _arm_action_from_s8(
                item,
                None if item.oracle_observation is None else observations[item.oracle_observation],
            )
            for item in projection.actions
        )
    except (KeyError, ValueError) as error:
        _scientific("returned_run.S8.records", str(error))

    # S8.3: candidate registry, costs, and public feasibility state, in that order.
    try:
        definitions = tuple(CANDIDATES_BY_ID[item.candidate_id] for item in actions)
    except KeyError as error:
        _scientific("returned_run.S8.candidate", str(error))
    costs = _scientific_call(
        "returned_run.S8.candidate_costs",
        lambda: candidate_costs(world.public),
    )
    public_state = _scientific_call(
        "returned_run.S8.public_state",
        lambda: PublicFeasibilityState(world.public),
    )

    # S8.4: cardinalities and the complete contiguous one-based step sequences.
    if len(decisions) != len(actions):
        _scientific("returned_run.S8.actions", "decision/action cardinality differs")
    non_setup = tuple(item for item in actions if item.role != "setup")
    if len(non_setup) != len(completed):
        _scientific(
            "returned_run.S8.completed_experiments",
            "non-setup action/experiment cardinality differs",
        )
    expected_steps = tuple(range(1, len(actions) + 1))
    if (
        tuple(item.step for item in decisions) != expected_steps
        or tuple(item.step for item in actions) != expected_steps
    ):
        _scientific("returned_run.S8.step", "steps are not contiguous and one-based")

    # Build the enclosing dataclass only after its children, before run relations.
    run = BroaderArmRun(
        projection.run_id,
        projection.comparison_id,
        arm,
        projection.world_id,
        projection.seed,
        projection.budget_id,
        budget,
        lineage,
        _reconstruct_probability_pairs(
            projection.initial_probabilities,
            "returned_run.initial_probabilities",
        ),
        decisions,
        actions,
        completed,
        evidence,
        updates,
        diagnostics,
        effects,
        calibration,
        _float_from_f64(projection.decision_cost, "returned_run.decision_cost"),
        _float_from_f64(projection.calibration_cost, "returned_run.calibration_cost"),
        _terminal_reason_value(projection.terminal_reason),
        projection.run_status,
    )

    step_records = tuple(zip(decisions, actions, definitions, strict=True))

    # S8.5: complete this predicate for every action before entering S8.6.
    for index, (decision, action, definition) in enumerate(step_records, start=1):
        expected_decision_id = f"decision/{projection.run_id}/{index:04d}"
        if (
            decision.decision_id != expected_decision_id
            or action.decision_id != decision.decision_id
            or decision.policy_trace.candidate.candidate_id != decision.selected_candidate_id
            or action.candidate_id != decision.selected_candidate_id
            or action.role != definition.role
        ):
            _scientific("returned_run.S8.decision_action", "decision/action relation differs")

    # S8.6: replay the complete public-feasibility sequence before S8.7.  Cost
    # prefixes come from the frozen catalog so a later recorded-cost defect does
    # not change an earlier predicate for a subsequent action.
    feasibility_state = public_state
    feasibility_cost = 0.0
    for decision, action, _ in step_records:
        expected_public = feasibility_state.publicly_feasible_candidate_ids()
        remaining = budget - feasibility_cost
        expected_affordable = tuple(
            candidate_id for candidate_id in expected_public if costs[candidate_id] <= remaining
        )
        if (
            decision.public_feasible_candidate_ids != expected_public
            or not _same_f64(decision.remaining_budget, remaining, "returned_run.S8.remaining")
            or decision.affordable_candidate_ids != expected_affordable
            or decision.selected_candidate_id not in expected_affordable
        ):
            _scientific("returned_run.S8.feasibility", "public feasibility relation differs")
        try:
            feasibility_state = feasibility_state.complete(action.candidate_id)
        except ValueError as error:
            _scientific("returned_run.S8.feasibility", str(error))
        feasibility_cost += costs[action.candidate_id]

    # S8.7: complete cost, affordability, and outcome/Oracle coupling before S8.8.
    for index, (decision, action, _) in enumerate(step_records):
        if not _same_f64(action.cost, costs[action.candidate_id], "returned_run.S8.cost"):
            _scientific("returned_run.S8.cost", "candidate cost differs")
        if action.cost > decision.remaining_budget:
            _scientific("returned_run.S8.cost", "selected action was not affordable")
        setup = action.role == "setup"
        if (
            (action.observed_objective is None) != setup
            or (action.oracle_observation is None) != setup
            or (action.observed_objective is None) != (action.oracle_observation is None)
        ):
            _scientific("returned_run.S8.optional", "setup/outcome optional relation differs")
        oracle_projection = projection.actions[index].oracle_observation
        if oracle_projection is not None and (
            oracle_projection.authorization.candidate_id != action.candidate_id
            or oracle_projection.candidate_id != action.candidate_id
            or oracle_projection.authorization.source_id != action.decision_id
        ):
            _scientific(
                "returned_run.S8.oracle_observation.authorization",
                "decision observation is not bound to its action",
            )
        if (
            action.observed_objective is not None
            and action.oracle_observation is not None
            and not _same_f64(
                action.observed_objective,
                action.oracle_observation.revealed_observation,
                "returned_run.S8.oracle_observation.revealed_observation",
            )
        ):
            _scientific(
                "returned_run.S8.observed_objective",
                "action objective differs from its Oracle observation",
            )

    # S8.8: bind all non-setup actions to complete stored experiment records.
    # Carry the stored record ID here; its formula is intentionally deferred to S10.2.
    completed_index = 0
    for index, (_, action, definition) in enumerate(step_records, start=1):
        if action.role != "setup":
            experiment = completed[completed_index]
            stored_record_id = projection.completed_experiments[completed_index].record_id
            completed_index += 1
            if action.observed_objective is None:
                _scientific(
                    "returned_run.S8.completed_experiments",
                    "non-setup action lacks an experiment outcome",
                )
            expected_experiment = CompletedExperiment(
                stored_record_id,
                definition.candidate,
                action.observed_objective,
                f"{CREATED_AT}#experiment:{index:04d}",
            )
            if experiment != expected_experiment:
                _scientific(
                    "returned_run.S8.completed_experiments",
                    "action/experiment record relation differs",
                )

    # S8.9: complete action evidence/update and posterior-snapshot reconciliation.
    evidence_index = 0
    current_probabilities = _reconstruct_probability_pairs(
        projection.initial_probabilities,
        "returned_run.initial_probabilities",
    )
    for _, action, _ in step_records:
        new_count = len(action.new_evidence_ids)
        if new_count > len(evidence) - evidence_index or new_count > len(updates) - evidence_index:
            _scientific("returned_run.S8.new_evidence_ids", "action evidence count overflows run")
        new_evidence = evidence[evidence_index : evidence_index + new_count]
        new_updates = updates[evidence_index : evidence_index + new_count]
        if tuple(item.evidence_id for item in new_evidence) != action.new_evidence_ids:
            _scientific("returned_run.S8.new_evidence_ids", "action evidence order differs")
        if tuple(item.evidence.evidence_id for item in new_updates) != action.new_evidence_ids:
            _scientific(
                "returned_run.S8.new_evidence_ids",
                "action update-evidence order differs",
            )
        if new_count:
            last_update = new_updates[-1]
            current_probabilities = tuple(
                sorted(last_update.posterior_state.state.posterior_map().items())
            )
        if action.posterior_probabilities != current_probabilities:
            _scientific("returned_run.S8.posterior_probabilities", "action snapshot differs")
        evidence_index += new_count
    if evidence_index != len(evidence) or evidence_index != len(updates):
        _scientific("returned_run.S8.evidence", "run evidence is absent from action chronology")

    # S8.10: declared field-total comparisons, children before the enclosing run.
    # Compare the reconstructed records directly. Re-projecting the enclosing run here
    # would repeat nested validation before the ordered S9/S10 predicates.
    for index, (decision, recorded) in enumerate(zip(decisions, projection.decisions, strict=True)):
        if (
            decision.decision_id,
            decision.step,
            decision.selected_candidate_id,
            f64(decision.remaining_budget),
            decision.belief_state_id,
            decision.public_feasible_candidate_ids,
            decision.affordable_candidate_ids,
            decision.policy_trace,
            decision.fixed_policy_regression_match,
        ) != (
            recorded.decision_id,
            recorded.step,
            recorded.selected_candidate_id,
            recorded.remaining_budget,
            recorded.belief_state_id,
            recorded.public_feasible_candidate_ids,
            recorded.affordable_candidate_ids,
            traces[recorded.policy_trace],
            recorded.fixed_policy_regression_match,
        ):
            _scientific(
                f"returned_run.S8.decision[{index}]",
                "field-total comparison failed",
            )
    for index, (action, recorded_action) in enumerate(
        zip(actions, projection.actions, strict=True)
    ):
        recorded_observation = (
            None
            if recorded_action.oracle_observation is None
            else observations[recorded_action.oracle_observation]
        )
        if (
            action.step,
            action.candidate_id,
            action.role,
            f64(action.cost),
            f64(action.cumulative_decision_cost),
            action.decision_id,
            (None if action.observed_objective is None else f64(action.observed_objective)),
            action.oracle_observation,
            action.new_evidence_ids,
            tuple(
                (hypothesis_id, f64(probability))
                for hypothesis_id, probability in action.posterior_probabilities
            ),
        ) != (
            recorded_action.step,
            recorded_action.candidate_id,
            recorded_action.role,
            recorded_action.cost,
            recorded_action.cumulative_decision_cost,
            recorded_action.decision_id,
            recorded_action.observed_objective,
            recorded_observation,
            recorded_action.new_evidence_ids,
            recorded_action.posterior_probabilities,
        ):
            _scientific(
                f"returned_run.S8.action[{index}]",
                "field-total comparison failed",
            )
    if (
        run.run_id,
        run.comparison_id,
        run.arm,
        run.world_id,
        run.seed,
        run.budget_id,
        f64(run.budget),
        run.lineage,
        tuple(
            (hypothesis_id, f64(probability))
            for hypothesis_id, probability in run.initial_probabilities
        ),
        run.decisions,
        run.actions,
        run.completed_experiments,
        run.evidence,
        run.updates,
        run.diagnostics,
        run.effect_history,
        run.calibration,
        f64(run.decision_cost),
        f64(run.calibration_cost),
        run.terminal_reason,
        run.run_status,
    ) != (
        projection.run_id,
        projection.comparison_id,
        arm,
        projection.world_id,
        projection.seed,
        projection.budget_id,
        projection.budget,
        lineage,
        projection.initial_probabilities,
        decisions,
        actions,
        completed,
        evidence,
        updates,
        diagnostics,
        effects,
        calibration,
        projection.decision_cost,
        projection.calibration_cost,
        projection.terminal_reason,
        projection.run_status,
    ):
        _scientific("returned_run.S8", "BroaderArmRun field-total comparison failed")
    return run


def _validate_returned_run_s9(run: BroaderArmRun) -> None:
    # S9.1: run evidence versus both update occurrences.
    if run.evidence != tuple(item.evidence for item in run.updates) or run.evidence != tuple(
        item.bayesian_update.evidence for item in run.updates
    ):
        _scientific("returned_run.S9.1", "run/update evidence differs")
    # S9.2: run diagnostics versus update diagnostics.
    if run.diagnostics != tuple(item.diagnostic for item in run.updates):
        _scientific("returned_run.S9.2", "run/update diagnostics differ")
    # S9.3: adjacent continuity first, then the nested Bayesian/model wrappers.
    for index in range(1, len(run.updates)):
        if run.updates[index - 1].posterior_state != run.updates[index].state_before:
            _scientific(f"returned_run.S9.3.updates[{index}]", "adjacent states differ")
    for index, update in enumerate(run.updates):
        if (
            update.state_before.state != update.bayesian_update.belief_state_before
            or update.posterior_state.state != update.bayesian_update.posterior_belief_state
        ):
            _scientific(f"returned_run.S9.3.updates[{index}]", "Bayesian wrapper differs")
    # S9.4: final lineage state.
    if run.updates:
        if run.lineage.current_state != run.updates[-1].posterior_state:
            _scientific("returned_run.S9.4", "final lineage state differs")
    else:
        initial_state = run.lineage.current_state.state
        initial_prior = tuple(
            zip(
                initial_state.hypothesis_ids,
                initial_state.prior_probabilities,
                strict=True,
            )
        )
        initial_posterior = tuple(sorted(initial_state.posterior_map().items()))
        if (
            initial_state.sequence != 0
            or initial_state.evidence_ids
            or initial_state.parent_belief_state_id is not None
            or initial_prior != run.initial_probabilities
            or initial_posterior != run.initial_probabilities
        ):
            _scientific("returned_run.S9.4", "untouched initial state differs")
    # S9.5: decision effects from update evidence.
    try:
        decision_effects = tuple(
            MatchedEffectObservation.from_decision(
                update.evidence,
                available_sequence=update.sigma_estimate.cutoff_sequence,
            )
            for update in run.updates
        )
    except ValueError as error:
        _scientific("returned_run.S9.5", str(error))
    # S9.6: calibration-first, decision-next exact chronology.
    calibration_effects = () if run.calibration is None else run.calibration.effects
    expected_history = (*calibration_effects, *decision_effects)
    if len(run.effect_history) != len(expected_history):
        _scientific("returned_run.S9.6", "effect history order or cardinality differs")
    recorded_calibration_effects = run.effect_history[: len(calibration_effects)]
    recorded_decision_effects = run.effect_history[len(calibration_effects) :]
    if (
        tuple(item.effect_id for item in recorded_calibration_effects)
        != tuple(item.effect_id for item in calibration_effects)
        or tuple(item.effect_id for item in recorded_decision_effects)
        != tuple(item.effect_id for item in decision_effects)
        or any(item.source_kind != "calibration" for item in recorded_calibration_effects)
        or any(item.source_kind != "decision" for item in recorded_decision_effects)
    ):
        _scientific("returned_run.S9.6", "effect history order or cardinality differs")
    if any(effect.available_sequence != 0 for effect in recorded_calibration_effects):
        _scientific("returned_run.S9.6", "calibration-effect availability differs")
    if any(
        effect.available_sequence != update.sigma_estimate.cutoff_sequence
        for effect, update in zip(recorded_decision_effects, run.updates, strict=True)
    ):
        _scientific("returned_run.S9.6", "decision-effect availability differs")
    if run.effect_history != expected_history:
        _scientific("returned_run.S9.6", "effect history content differs")
    # S9.7: estimate/deployment duplicate-by-value reconciliation.
    if run.calibration is not None:
        calibration = run.calibration
        if tuple(item.comparison_group_id for item in calibration.estimates) != GROUP_IDS:
            _scientific("returned_run.S9.7", "calibration estimate group order differs")
        if calibration.effects != tuple(
            effect for estimate in calibration.estimates for effect in estimate.effects
        ):
            _scientific("returned_run.S9.7", "calibration effects differ")
        if calibration.observations != tuple(
            observation
            for estimate in calibration.estimates
            for observation in estimate.observations
        ):
            _scientific("returned_run.S9.7", "calibration observations differ")
    # S9.8: decision cost.
    expected_decision_cost = math.fsum(item.cost for item in run.actions)
    if not _same_f64(run.decision_cost, expected_decision_cost, "returned_run.S9.8"):
        _scientific("returned_run.S9.8", "decision cost differs")
    # S9.9: fixed/calibrated arm coupling.
    if run.arm.belief_model_id == FIXED_SIGMA_MODEL_ID:
        if run.calibration is not None or not _same_f64(
            run.calibration_cost, 0.0, "returned_run.S9.9"
        ):
            _scientific("returned_run.S9.9", "fixed arm consumed calibration")
    elif run.arm.belief_model_id == CALIBRATED_SIGMA_MODEL_ID:
        if run.calibration is None or not _same_f64(
            run.calibration_cost,
            run.calibration.cost,
            "returned_run.S9.9",
        ):
            _scientific("returned_run.S9.9", "calibrated arm lacks deployment cost")
    else:
        _scientific("returned_run.S9.9", "unknown frozen belief model")
    # S9.10: cumulative prefixes, final equality, and budget.
    cumulative = 0.0
    for index, action in enumerate(run.actions):
        cumulative += action.cost
        if not _same_f64(
            action.cumulative_decision_cost,
            cumulative,
            f"returned_run.S9.10.actions[{index}]",
        ):
            _scientific("returned_run.S9.10", "cumulative decision cost differs")
    if (
        not _same_f64(cumulative, run.decision_cost, "returned_run.S9.10")
        or cumulative > run.budget
    ):
        _scientific("returned_run.S9.10", "final cumulative cost or budget bound differs")
    # S9.11: terminal relation. Invalid/integrity-abort payloads are decodable, never accepted.
    world = WORLDS_BY_ID[run.world_id].public
    state = PublicFeasibilityState(world)
    for action in run.actions:
        state = state.complete(action.candidate_id)
    unexecuted = state.publicly_feasible_candidate_ids()
    remaining = run.budget - run.decision_cost
    costs = candidate_costs(world)
    affordable = tuple(item for item in unexecuted if costs[item] <= remaining)
    terminal = _scientific_call(
        "returned_run.S9.11",
        lambda: terminal_reason_for(unexecuted, affordable, integrity_failure=False),
    )
    if (
        run.run_status != "complete"
        or run.terminal_reason == "integrity_abort"
        or run.terminal_reason != terminal
    ):
        _scientific("returned_run.S9.11", "terminal reason and run status do not couple")


def _s10_calibration_effects(run: BroaderArmRun) -> tuple[MatchedEffectObservation, ...]:
    if run.arm.belief_model_id == FIXED_SIGMA_MODEL_ID:
        if run.calibration is not None or run.calibration_cost != 0.0:
            _scientific("returned_run.S10.9", "fixed arm consumed calibration")
        if any(item.source_kind == "calibration" for item in run.effect_history):
            _scientific(
                "returned_run.S10.9",
                "fixed arm effect history contains calibration data",
            )
        return ()
    if run.arm.belief_model_id != CALIBRATED_SIGMA_MODEL_ID:
        _scientific("returned_run.S10.9", "run uses an unknown frozen belief model")
    calibration = run.calibration
    if calibration is None or len(calibration.estimates) != len(GROUP_IDS):
        _scientific("returned_run.S10.9", "calibrated arm lacks a deployment")
    if tuple(item.comparison_group_id for item in calibration.estimates) != GROUP_IDS:
        _scientific("returned_run.S10.9", "calibration group order differs")
    expected_deployment_effects: list[MatchedEffectObservation] = []
    expected_deployment_observations: list[RevealedObservation] = []
    selector_physical_costs: list[float] = []
    for group_index, estimate in enumerate(calibration.estimates):
        group_id = GROUP_IDS[group_index]
        prefix = f"calibration-prefix/{run.world_id}/{run.seed}/{group_id}"
        if (
            estimate.calibration_prefix_id != prefix
            or estimate.sigma_estimate_id != f"sigma-estimate/{prefix}"
            or len(estimate.effects) != 5
            or len(estimate.observations) != 10
        ):
            _scientific(
                f"returned_run.S10.9.calibration[{group_index}]",
                "calibration identity or replication cardinality differs",
            )
        expected_observations = estimate.observations
        expected_effects = tuple(
            expected_calibration_effect(
                prefix_id=prefix,
                world_id=run.world_id,
                comparison_group_id=group_id,
                group_index=group_index,
                replication_index=replication_index,
                observed_effect=round(
                    expected_observations[2 * (replication_index - 1)].revealed_observation
                    - expected_observations[2 * (replication_index - 1) + 1].revealed_observation,
                    12,
                ),
            )
            for replication_index in range(1, 6)
        )
        try:
            costs = candidate_costs(WORLDS_BY_ID[run.world_id].public)
        except (KeyError, ValueError) as error:
            _scientific(
                f"returned_run.S10.9.calibration[{group_index}].costs",
                str(error),
            )
        physical_cost = 5.0 * (
            costs[f"g{group_index:02d}-adam-r1"] + costs[f"g{group_index:02d}-sgd-r1"]
        )
        selection = _scientific_call(
            f"returned_run.S10.9.calibration[{group_index}].selector",
            replay_calibration_history_selection,
            run_id=run.run_id,
            world_id=run.world_id,
            seed=run.seed,
            comparison_group_id=group_id,
            group_index=group_index,
            expected_observations=expected_observations,
            expected_effects=expected_effects,
            physical_cost=physical_cost,
            recorded_observations=estimate.observations,
            recorded_effects=run.effect_history,
            source_sequence_cutoff=CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
        )
        expected_candidate_pairs = tuple(
            (
                f"cal-{group_index:02d}-adam-r{replication_index:04d}",
                f"cal-{group_index:02d}-sgd-r{replication_index:04d}",
            )
            for replication_index in range(1, 6)
        )
        expected_replication_ids = tuple(
            f"calibration-{group_index:02d}-r{replication_index:04d}"
            for replication_index in range(1, 6)
        )
        expected_observation_identities = tuple(
            (item.oracle_key_id, item.outcome_digest) for item in expected_observations
        )
        expected_oracle_key_ids = tuple(item.oracle_key_id for item in expected_observations)
        expected_values = tuple(item.observed_effect for item in expected_effects)
        expected_mean = statistics.mean(expected_values)
        expected_standard_deviation = statistics.stdev(expected_values)
        expected_estimated_sigma = max(expected_standard_deviation, SIGMA_FLOOR)
        expected_source_ids = tuple(item.effect_id for item in expected_effects)
        independently_recomputed_digest_sequence = tuple(
            raw_effect_sha256(item) for item in expected_effects
        )
        digest_sequence = selection.source_effect_payload_sha256
        digest_format_valid = all(
            type(item) is str
            and len(item) == 64
            and all(character in "0123456789abcdef" for character in item)
            for item in digest_sequence
        )
        expected_selection_identity = protocol_hash(
            CALIBRATION_SELECTION_VERSION,
            {
                "study_id": PROTOCOL_VERSION,
                "world_id": run.world_id,
                "seed": run.seed,
                "namespace": CALIBRATION_NAMESPACE,
                "comparison_group_id": group_id,
                "target_comparison_group_id": group_id,
                "source_sequence_cutoff": CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
                "source_effect_ids": list(expected_source_ids),
                "source_effect_payload_sha256": list(independently_recomputed_digest_sequence),
                "source_observation_identities": [
                    list(item) for item in expected_observation_identities
                ],
                "source_oracle_key_ids": list(expected_oracle_key_ids),
                "source_candidate_pairs": [list(item) for item in expected_candidate_pairs],
                "source_replication_ids": list(expected_replication_ids),
                "effect_values": [f64(item) for item in expected_values],
                "sample_count": len(expected_effects),
                "sample_mean": f64(expected_mean),
                "sample_standard_deviation": f64(expected_standard_deviation),
                "ddof": CALIBRATION_SIGMA_DDOF,
                "sigma_floor": f64(SIGMA_FLOOR),
                "estimated_sigma": f64(expected_estimated_sigma),
                "eligibility_basis": CALIBRATION_ELIGIBILITY_BASIS,
            },
        )
        selector_relation = (
            selection.study_id == PROTOCOL_VERSION
            and selection.world_id == run.world_id
            and selection.seed == run.seed
            and selection.namespace == CALIBRATION_NAMESPACE
            and selection.comparison_group_id == group_id
            and selection.target_comparison_group_id == group_id
            and selection.source_sequence_cutoff == CALIBRATION_SOURCE_SEQUENCE_CUTOFF
            and selection.source_effect_ids == expected_source_ids
            and digest_format_valid
            and len(digest_sequence) == len(expected_effects)
            and digest_sequence == independently_recomputed_digest_sequence
            and selection.source_observation_identities == expected_observation_identities
            and selection.source_oracle_key_ids == expected_oracle_key_ids
            and selection.source_candidate_pairs == expected_candidate_pairs
            and selection.source_replication_ids == expected_replication_ids
            and selection.effect_values == expected_values
            and selection.sample_count == len(expected_effects)
            and _same_f64(
                selection.sample_mean,
                expected_mean,
                "returned_run.S10.9.selector.sample_mean",
            )
            and _same_f64(
                selection.sample_standard_deviation,
                expected_standard_deviation,
                "returned_run.S10.9.selector.sample_standard_deviation",
            )
            and selection.ddof == CALIBRATION_SIGMA_DDOF
            and _same_f64(
                selection.sigma_floor,
                SIGMA_FLOOR,
                "returned_run.S10.9.selector.sigma_floor",
            )
            and _same_f64(
                selection.estimated_sigma,
                expected_estimated_sigma,
                "returned_run.S10.9.selector.estimated_sigma",
            )
            and _same_f64(
                selection.physical_cost,
                physical_cost,
                "returned_run.S10.9.selector.physical_cost",
            )
            and selection.eligibility_basis == CALIBRATION_ELIGIBILITY_BASIS
            and selection.current_observation_excluded is True
            and selection.current_effect_excluded is True
            and selection.future_history_excluded is True
            and selection.effects == expected_effects
            and selection.observations == expected_observations
            and selection.selection_identity == expected_selection_identity
        )
        if not selector_relation:
            _scientific(
                f"returned_run.S10.9.calibration[{group_index}].selector",
                "calibration selector replay differs",
            )
        if estimate.effects != selection.effects:
            _scientific(
                f"returned_run.S10.9.calibration[{group_index}].effects",
                "recorded calibration source effects differ",
            )
        provenance_sha256 = calibration_sigma_provenance_sha256(
            sigma_estimate_id=f"sigma-estimate/{prefix}",
            calibration_prefix_id=prefix,
            comparison_group_id=group_id,
            source_effect_ids=selection.source_effect_ids,
            source_sequence_cutoff=CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
            sample_count=selection.sample_count,
            sample_mean=selection.sample_mean,
            raw_sample_standard_deviation=selection.sample_standard_deviation,
            ddof=CALIBRATION_SIGMA_DDOF,
            sigma_floor=SIGMA_FLOOR,
            estimated_sigma=selection.estimated_sigma,
            belief_model_id=CALIBRATED_SIGMA_MODEL_ID,
            lineage_id=run.lineage.lineage_id,
            effects=selection.effects,
        )
        if (
            estimate.source_effect_ids != selection.source_effect_ids
            or estimate.source_sequence_cutoff != CALIBRATION_SOURCE_SEQUENCE_CUTOFF
            or estimate.sample_count != selection.sample_count
            or not _same_f64(
                estimate.sample_mean,
                selection.sample_mean,
                "returned_run.S10.9.sample_mean",
            )
            or not _same_f64(
                estimate.raw_sample_standard_deviation,
                selection.sample_standard_deviation,
                "returned_run.S10.9.sample_standard_deviation",
            )
            or estimate.ddof != CALIBRATION_SIGMA_DDOF
            or not _same_f64(estimate.sigma_floor, SIGMA_FLOOR, "returned_run.S10.9.sigma_floor")
            or not _same_f64(
                estimate.estimated_sigma,
                selection.estimated_sigma,
                "returned_run.S10.9.estimated_sigma",
            )
            or estimate.belief_model_id != CALIBRATED_SIGMA_MODEL_ID
            or estimate.lineage_id != run.lineage.lineage_id
            or estimate.provenance_sha256 != provenance_sha256
            or estimate.observations != selection.observations
            or not _same_f64(
                estimate.physical_cost,
                selection.physical_cost,
                "returned_run.S10.9.physical_cost",
            )
        ):
            _scientific("returned_run.S10.9", "recorded calibration estimate differs")
        expected_deployment_effects.extend(selection.effects)
        expected_deployment_observations.extend(selection.observations)
        selector_physical_costs.append(selection.physical_cost)
    expected_effect_tuple = tuple(expected_deployment_effects)
    expected_observation_tuple = tuple(expected_deployment_observations)
    expected_cost = math.fsum(selector_physical_costs)
    if (
        calibration.effects != expected_effect_tuple
        or calibration.observations != expected_observation_tuple
        or not _same_f64(calibration.cost, expected_cost, "returned_run.S10.9.cost")
        or not _same_f64(run.calibration_cost, expected_cost, "returned_run.S10.9.run_cost")
    ):
        _scientific("returned_run.S10.9", "recorded calibration deployment differs")
    return expected_effect_tuple


def _s10_candidate_occurrences(run: BroaderArmRun) -> tuple[Candidate, ...]:
    occurrences: list[Candidate] = [item.candidate for item in run.completed_experiments]
    for decision in run.decisions:
        trace = decision.policy_trace
        if type(trace) is DecisionTrace:
            occurrences.extend(item.candidate for item in trace.ranked_candidates)
            occurrences.append(trace.selected.candidate)
            continue
        if type(trace) is not LookaheadPlanTrace:
            _scientific("returned_run.S10.1", "unknown policy-trace branch")
        occurrences.extend(item.candidate for item in trace.alternatives)
        occurrences.extend(
            branch.second_action.candidate
            for branch in trace.selected.branches
            if branch.second_action.candidate is not None
        )
        occurrences.append(trace.selected.candidate)
    return tuple(occurrences)


def _validate_returned_run_s10_updates(run: BroaderArmRun) -> None:
    # S10.1: compare every nested candidate in frozen registry order.
    candidate_occurrences = _s10_candidate_occurrences(run)
    matched_occurrences = 0
    for definition in CANDIDATE_CATALOG:
        candidate_id = definition.candidate_id
        expected_candidate = CANDIDATES_BY_ID[candidate_id].candidate
        for candidate in candidate_occurrences:
            if candidate.candidate_id != candidate_id:
                continue
            matched_occurrences += 1
            if candidate != expected_candidate:
                _scientific("returned_run.S10.1", "candidate registry relation differs")
    if matched_occurrences != len(candidate_occurrences):
        _scientific("returned_run.S10.1", "candidate registry relation differs")

    # S10.2: experiment identity, strictly in non-setup action chronology.
    completed_index = 0
    for action in run.actions:
        if action.role == "setup":
            continue
        experiment = run.completed_experiments[completed_index]
        completed_index += 1
        expected_id = _experiment_record_id(run.run_id, action.step)
        if experiment.record_id != expected_id:
            _scientific("returned_run.S10.2", "experiment identity differs")

    # S10.3: reconstruct the untouched initial lineage once and compare it field-total.
    initial = _scientific_call(
        "returned_run.S10.3",
        lambda: initial_lineage_for(arm=run.arm, run_id=run.run_id),
    )
    initial_recorded_state = (
        run.updates[0].state_before if run.updates else run.lineage.current_state
    )
    if (
        initial.lineage_id != run.lineage.lineage_id
        or initial.belief_model_id != run.lineage.belief_model_id
        or initial.belief_model_version != run.lineage.belief_model_version
        or initial.lineage_key != run.lineage.lineage_key
        or initial.created_at != run.lineage.created_at
        or initial.current_state != initial_recorded_state
        or tuple(sorted(initial.current_state.state.posterior_map().items()))
        != run.initial_probabilities
    ):
        _scientific("returned_run.S10.3", "initial lineage differs")

    # S10.4: validate that one initial lineage before any eligibility operation.
    _scientific_call(
        "returned_run.S10.4",
        lambda: validate_lineage_binding(lineage=initial, arm=run.arm, run_id=run.run_id),
    )

    # S10.5: collect every valid unapplied pair in action chronology.
    eligibility = _scientific_call("returned_run.S10.5", evidence_eligibility_contract)
    completed: list[CompletedExperiment] = []
    applied_pairs: set[tuple[int, ...]] = set()
    eligible_pairs: list[MatchedExperimentPair] = []
    completed_index = 0
    for action in run.actions:
        if action.role == "setup":
            continue
        completed.append(run.completed_experiments[completed_index])
        completed_index += 1
        try:
            pairs = eligibility.valid_unapplied_pairs(
                completed,
                applied_source_pairs=frozenset(applied_pairs),
            )
        except ValueError as error:
            _scientific("returned_run.S10.5", str(error))
        eligible_pairs.extend(pairs)
        applied_pairs.update(pair.source_experiment_ids for pair in pairs)

    # S10.6: reconstruct and compare all eligible evidence before model replay.
    if len(eligible_pairs) != len(run.evidence):
        _scientific("returned_run.S10.6", "eligible evidence cardinality differs")
    for index, pair in enumerate(eligible_pairs):
        try:
            expected_evidence = evidence_from_matched_pair(pair, eligibility)
        except ValueError as error:
            _scientific(f"returned_run.S10.6.evidence[{index}]", str(error))
        if expected_evidence != run.evidence[index]:
            _scientific(
                f"returned_run.S10.6.evidence[{index}]",
                "eligible evidence differs",
            )

    # S10.7: replay every model update, including its returned decision effect.
    model = _scientific_call(
        "returned_run.S10.7",
        lambda: belief_model(run.arm.belief_model_id),
    )
    lineage = initial
    temporary_effects = list(() if run.calibration is None else run.calibration.effects)
    temporary_diagnostics: list[ModelAdequacyDiagnostic] = []
    calibration_effect_count = 0 if run.calibration is None else len(run.calibration.effects)
    recorded_decision_effects = run.effect_history[calibration_effect_count:]
    if len(run.evidence) != len(run.updates) or len(recorded_decision_effects) != len(run.updates):
        _scientific("returned_run.S10.7", "scientific update cardinality differs")
    for index, expected_evidence in enumerate(run.evidence):
        try:
            expected_lineage, expected_update, expected_effect = model.update(
                lineage=lineage,
                evidence=expected_evidence,
                effect_history=tuple(temporary_effects),
                diagnostic_history=tuple(temporary_diagnostics),
            )
        except ValueError as error:
            _scientific(f"returned_run.S10.7.updates[{index}]", str(error))
        recorded_lineage = replace(
            run.lineage,
            current_state=run.updates[index].posterior_state,
        )
        recorded_update = run.updates[index]
        path = f"returned_run.S10.7.updates[{index}]"
        if expected_lineage != recorded_lineage:
            _scientific(path, "returned lineage differs")
        if expected_update.sigma_estimate != recorded_update.sigma_estimate:
            _scientific(path, "sigma estimate differs")
        if expected_update.diagnostic != recorded_update.diagnostic:
            _scientific(path, "diagnostic differs")
        if expected_update.bayesian_update != recorded_update.bayesian_update:
            _scientific(path, "Bayesian update differs")
        if expected_update.posterior_state != recorded_update.posterior_state:
            _scientific(path, "posterior state differs")
        if (
            expected_update.model_update_id,
            expected_update.belief_model_id,
            expected_update.belief_model_version,
            expected_update.lineage_id,
            expected_update.state_before,
            expected_update.evidence,
            expected_update.created_at,
        ) != (
            recorded_update.model_update_id,
            recorded_update.belief_model_id,
            recorded_update.belief_model_version,
            recorded_update.lineage_id,
            recorded_update.state_before,
            recorded_update.evidence,
            recorded_update.created_at,
        ):
            _scientific(path, "model update differs")
        if expected_update.provenance != recorded_update.provenance:
            _scientific(path, "model-update provenance differs")
        if expected_effect != recorded_decision_effects[index]:
            _scientific(path, "decision effect differs")
        _scientific_call(
            f"returned_run.S10.8.updates[{index}]",
            validate_lineage_binding,
            lineage=expected_lineage,
            arm=run.arm,
            run_id=run.run_id,
        )
        lineage = expected_lineage
        temporary_effects.append(expected_effect)
        temporary_diagnostics.append(expected_update.diagnostic)

    # S10.8: each temporary lineage passed immediately; now validate the recorded final lineage.
    _scientific_call(
        "returned_run.S10.8",
        lambda: validate_lineage_binding(
            lineage=run.lineage,
            arm=run.arm,
            run_id=run.run_id,
        ),
    )


def _validate_returned_run_s10_replay(run: BroaderArmRun) -> None:
    calibration_effects = _s10_calibration_effects(run)
    effect_ids = tuple(item.effect_id for item in run.effect_history)
    if len(set(effect_ids)) != len(effect_ids):
        _scientific("returned_run.S10.9", "effect history contains a duplicate identity")
    try:
        decision_effects = tuple(
            MatchedEffectObservation.from_decision(
                update.evidence,
                available_sequence=update.sigma_estimate.cutoff_sequence,
            )
            for update in run.updates
        )
    except ValueError as error:
        _scientific("returned_run.S10.9.decision_effects", str(error))
    replay_effect_history = (*calibration_effects, *decision_effects)
    if replay_effect_history != run.effect_history:
        _scientific("returned_run.S10.9", "validated effect history differs")
    model = _scientific_call(
        "returned_run.S10.9",
        lambda: belief_model(run.arm.belief_model_id),
    )
    world = WORLDS_BY_ID[run.world_id].public
    costs = candidate_costs(world)
    eligibility = evidence_eligibility_contract()
    public_state = PublicFeasibilityState(world)
    states: dict[str, ModelBeliefState] = {
        run.lineage.current_state.state.belief_state_id: run.lineage.current_state
    }
    for update in run.updates:
        states[update.state_before.state.belief_state_id] = update.state_before
        states[update.posterior_state.state.belief_state_id] = update.posterior_state
    completed_count = 0
    decision_cost = 0.0
    for index, decision in enumerate(run.decisions):
        if index >= len(run.actions):
            _scientific("returned_run.S10.9", "decision has no action")
        expected_public = public_state.publicly_feasible_candidate_ids()
        remaining = run.budget - decision_cost
        expected_affordable = tuple(
            candidate_id for candidate_id in expected_public if costs[candidate_id] <= remaining
        )
        if (
            decision.public_feasible_candidate_ids != expected_public
            or decision.affordable_candidate_ids != expected_affordable
            or not math.isclose(
                decision.remaining_budget,
                remaining,
                abs_tol=1e-12,
            )
        ):
            _scientific("returned_run.S10.9", "replay feasibility differs")
        try:
            current_state = states[decision.belief_state_id]
        except KeyError as error:
            _scientific("returned_run.S10.9", str(error))
        lineage = replace(run.lineage, current_state=current_state)
        effect_history = tuple(
            item
            for item in replay_effect_history
            if item.available_sequence <= current_state.state.sequence
        )
        try:
            adapter = build_candidate_group_prediction_adapter(
                model=model,
                lineage=lineage,
                effect_history=effect_history,
                evidence_eligibility=eligibility,
            )
            candidates = tuple(
                CANDIDATES_BY_ID[candidate_id].candidate for candidate_id in expected_affordable
            )
        except (KeyError, ValueError) as error:
            _scientific("returned_run.S10.9", str(error))
        completed = run.completed_experiments[:completed_count]
        try:
            trace = _decide(
                arm=run.arm,
                adapter=adapter,
                lineage=lineage,
                candidates=candidates,
                completed=completed,
                costs=costs,
                remaining_budget=remaining,
                decision_id=decision.decision_id,
            )
        except (KeyError, ReasoningError, ValueError, OverflowError) as error:
            _scientific("returned_run.S10.9", str(error))
        action = run.actions[index]
        if (
            trace.to_dict() != decision.policy_trace.to_dict()
            or trace.candidate.candidate_id != decision.selected_candidate_id
            or action.decision_id != decision.decision_id
            or action.candidate_id != decision.selected_candidate_id
        ):
            _scientific("returned_run.S10.9", "deterministic decision replay differs")
        try:
            fixed_match = _fixed_policy_match(
                arm=run.arm,
                adapter=adapter,
                lineage=lineage,
                candidates=candidates,
                completed=completed,
                costs=costs,
                remaining_budget=remaining,
                decision_id=decision.decision_id,
                adapted=trace,
            )
        except (KeyError, ReasoningError, ValueError, OverflowError) as error:
            _scientific("returned_run.S10.9", str(error))
        if fixed_match != decision.fixed_policy_regression_match:
            _scientific("returned_run.S10.9", "fixed-policy regression relation differs")
        try:
            public_state = public_state.complete(action.candidate_id)
        except ValueError as error:
            _scientific("returned_run.S10.9", str(error))
        decision_cost += action.cost
        if action.role != "setup":
            completed_count += 1
    if len(run.actions) != len(run.decisions):
        _scientific("returned_run.S10.9", "decision/action replay cardinality differs")


def _validate_returned_run_s10(run: BroaderArmRun) -> None:
    _validate_returned_run_s10_updates(run)
    _validate_returned_run_s10_replay(run)
    expected_run_id = _scientific_call(
        "returned_run.S10.10",
        lambda: run_identity(
            arm_id=run.arm.arm_id,
            world_id=run.world_id,
            seed=run.seed,
            budget=run.budget,
        ),
    )
    if run.run_id != expected_run_id:
        _scientific("returned_run.S10.10", "run identity differs")
    expected_comparison_id = _scientific_call(
        "returned_run.S10.11",
        lambda: comparison_identity(
            policy_id=run.arm.policy_id,
            world_id=run.world_id,
            seed=run.seed,
            budget=run.budget,
        ),
    )
    if run.comparison_id != expected_comparison_id:
        _scientific("returned_run.S10.11", "comparison identity differs")


def _terminal_reason_value(
    value: str,
) -> Literal["candidate_space_exhausted", "budget_exhausted", "integrity_abort"]:
    if value == "candidate_space_exhausted":
        return "candidate_space_exhausted"
    if value == "budget_exhausted":
        return "budget_exhausted"
    if value == "integrity_abort":
        return "integrity_abort"
    _scientific("returned_run.terminal_reason", "unknown terminal reason")


def _construct_returned_run_s7_stage(
    projection: RunCalibrationProjection | None,
    observations: dict[RunRevealedObservationProjection, RevealedObservation],
    effects: dict[RunMatchedEffectProjection, MatchedEffectObservation],
) -> CalibrationDeployment | None:
    return _scientific_call(
        "returned_run.S7",
        _construct_returned_run_s7,
        projection,
        observations,
        effects,
    )


def _construct_returned_run_s8_stage(
    projection: ReturnedRunProjection,
    *,
    completed: tuple[CompletedExperiment, ...],
    evidence: tuple[Evidence, ...],
    lineage: BeliefModelLineage,
    updates: tuple[ModelBeliefUpdate, ...],
    diagnostics: tuple[ModelAdequacyDiagnostic, ...],
    effects: tuple[MatchedEffectObservation, ...],
    calibration: CalibrationDeployment | None,
    observations: dict[RunRevealedObservationProjection, RevealedObservation],
    traces: dict[RunPolicyTraceProjection, DecisionTrace | LookaheadPlanTrace],
) -> BroaderArmRun:
    return _scientific_call(
        "returned_run.S8",
        lambda: _construct_returned_run_s8(
            projection,
            completed=completed,
            evidence=evidence,
            lineage=lineage,
            updates=updates,
            diagnostics=diagnostics,
            effects=effects,
            calibration=calibration,
            observations=observations,
            traces=traces,
        ),
    )


def _reraise_returned_run_batch_error(
    error: ReturnedRunProjectionError,
    payload_index: int,
    payload_count: int,
) -> Never:
    if payload_count == 1:
        raise error
    marker = f"{error.failure_code or error.category} at {error.path}: "
    message = str(error)
    detail = message[len(marker) :] if message.startswith(marker) else message
    raise ReturnedRunProjectionError(
        category=error.category,
        failure_code=error.failure_code,
        path=f"returned_runs[{payload_index}].{error.path}",
        detail=detail,
    ) from None


def _neutralize_returned_run_structure(value: object, path: str) -> object:
    if type(value) is list:
        return [
            _neutralize_returned_run_structure(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if type(value) is not dict:
        return value
    parsed: dict[str, object] = value
    neutral = {
        name: _neutralize_returned_run_structure(item, f"{path}.{name}")
        for name, item in parsed.items()
    }
    keys = frozenset(neutral)

    scientific_identifier_fields: tuple[str, ...] = ()
    if keys == {
        "created_at",
        "evidence_id",
        "observed_comparison",
        "observed_outcome",
        "provenance",
        "source_experiment_ids",
    }:
        scientific_identifier_fields = ("evidence_id",)
    elif keys == {
        "belief_state_before",
        "created_at",
        "evidence",
        "likelihoods",
        "normalization_constant",
        "posterior_belief_state",
        "provenance",
        "update_id",
        "update_rule_version",
    }:
        scientific_identifier_fields = ("update_id",)
    elif keys == {
        "available_sequence",
        "comparison_group_id",
        "created_at",
        "effect_id",
        "observed_effect",
        "provenance",
        "source_ids",
        "source_kind",
    }:
        scientific_identifier_fields = ("comparison_group_id", "effect_id")
    elif keys == {
        "belief_state_id",
        "created_at",
        "fallback_reason",
        "hypotheses",
        "max_cost",
        "policy",
        "policy_version",
        "provenance",
        "ranked_candidates",
        "rationale",
        "selected",
        "suggestion_id",
    }:
        scientific_identifier_fields = ("suggestion_id",)
    elif keys == {
        "branch_id",
        "branch_total_cost",
        "budget_feasible",
        "evidence_lower_bound",
        "evidence_upper_bound",
        "label",
        "posterior_entropy",
        "posterior_probabilities",
        "probability",
        "second_action",
        "terminal_entropy",
    }:
        scientific_identifier_fields = ("branch_id",)
    elif keys == {
        "alternatives",
        "belief_state_id",
        "candidate_set_fingerprint",
        "completed_state_fingerprint",
        "created_at",
        "current_hypothesis_probabilities",
        "fallback_reason",
        "max_cost",
        "plan_id",
        "policy",
        "policy_version",
        "provenance",
        "rationale",
        "selected",
        "tie_breaking_order",
    }:
        scientific_identifier_fields = (
            "belief_state_id",
            "candidate_set_fingerprint",
            "completed_state_fingerprint",
            "plan_id",
        )
    for field in scientific_identifier_fields:
        identifier = parsed[field]
        if (
            type(identifier) is str
            and not identifier.strip()
            and _is_structurally_admitted_string(identifier)
        ):
            neutral = neutral | {field: "structural-placeholder"}
    if keys == {"kind", "value"}:
        kind = parsed["kind"]
        payload = parsed["value"]
        if not _is_structurally_admitted_string(kind):
            return neutral
        if type(payload) is str:
            if kind == "f64":
                return neutral
            return {"kind": "string", "value": payload}
        if type(payload) is bool:
            return {"kind": "bool", "value": payload}
        if type(payload) is int:
            return {"kind": "i64", "value": payload}
        if payload is None:
            return {"kind": "null", "value": None}
        return neutral
    if keys == {"candidate_id", "kind", "run_id", "source_id"}:
        if _is_structurally_admitted_string(parsed["kind"]):
            return neutral | {"kind": "decision"}
        return neutral
    if {"actions", "run_status", "schema_version", "terminal_reason"} <= keys:
        if _is_structurally_admitted_string(parsed["run_status"]):
            neutral = neutral | {"run_status": "complete"}
        if _is_structurally_admitted_string(parsed["terminal_reason"], identifier=True):
            neutral = neutral | {"terminal_reason": "budget_exhausted"}
    if {
        "cost",
        "posterior_probabilities",
        "role",
        "step",
    } <= keys and _is_structurally_admitted_string(parsed["role"], identifier=True):
        neutral = neutral | {"role": "setup"}
    if "action_effect" in keys and _is_structurally_admitted_string(
        parsed["action_effect"],
        identifier=True,
    ):
        action_effect = (
            "stop" if "reason" in keys and neutral.get("candidate") is None else "ineligible"
        )
        neutral = neutral | {"action_effect": action_effect}
    for field, replacement in (
        ("source_kind", "decision"),
        ("status", "fixed"),
        ("adequacy_state", "adequate"),
    ):
        if field in keys and _is_structurally_admitted_string(parsed[field]):
            neutral = neutral | {field: replacement}
    return neutral


def _validate_returned_run_projection_structure(
    projection: ReturnedRunProjection,
) -> None:
    if type(projection) is not ReturnedRunProjection:
        _structural("projection", "unsupported projection type")
    validate_returned_run_projection_shape(
        projection,
        _defer_scientific_validation=True,
    )
    raw = _neutralize_returned_run_structure(
        _returned_run_mapping(projection, defer_policy_validation=True),
        "returned_run",
    )
    decode_returned_run_projection(raw)


def _prepare_returned_run_batch(
    *,
    returned_runs_in_actual_delivery_order: tuple[ReturnedRunProjection, ...],
    returned_domains_in_actual_delivery_order: tuple[BroaderArmRun, ...] | None,
) -> None:
    if type(returned_runs_in_actual_delivery_order) is not tuple:
        _structural(
            "returned_runs_in_actual_delivery_order",
            "expected an exact tuple",
        )
    payload_count = len(returned_runs_in_actual_delivery_order)
    if returned_domains_in_actual_delivery_order is not None:
        if type(returned_domains_in_actual_delivery_order) is not tuple:
            _structural(
                "returned_domains_in_actual_delivery_order",
                "expected an exact tuple or None",
            )
        if len(returned_domains_in_actual_delivery_order) != payload_count:
            _structural(
                "returned_domains_in_actual_delivery_order",
                "returned-run projection and context counts differ",
            )
    for index, projection in enumerate(returned_runs_in_actual_delivery_order):
        try:
            _validate_returned_run_projection_structure(projection)
        except ReturnedRunProjectionError as error:
            _reraise_returned_run_batch_error(error, index, payload_count)
    if returned_domains_in_actual_delivery_order is None:
        return
    for index, expected_run in enumerate(returned_domains_in_actual_delivery_order):
        try:
            if type(expected_run) is not BroaderArmRun:
                _structural("expected_run", "context must be a BroaderArmRun")
            expected_projection = _project_returned_run(
                expected_run,
                validate_science=False,
            )
            _validate_returned_run_projection_structure(expected_projection)
        except ReturnedRunProjectionError as error:
            _reraise_returned_run_batch_error(error, index, payload_count)


def _reconstruct_returned_run_batch(
    returned_runs_in_actual_delivery_order: tuple[ReturnedRunProjection, ...],
) -> tuple[BroaderArmRun, ...]:
    payload_count = len(returned_runs_in_actual_delivery_order)
    try:
        for index, projection in enumerate(returned_runs_in_actual_delivery_order):  # noqa: B007
            _validate_returned_run_s1(projection)

        caches: list[dict[object, object]] = []
        completed_by_payload: list[tuple[CompletedExperiment, ...]] = []
        evidence_by_payload: list[tuple[Evidence, ...]] = []
        for index, projection in enumerate(returned_runs_in_actual_delivery_order):  # noqa: B007
            cache, completed, evidence = _construct_returned_run_s2(projection)
            caches.append(cache)
            completed_by_payload.append(completed)
            evidence_by_payload.append(evidence)

        lineages: list[BeliefModelLineage] = []
        updates_by_payload: list[tuple[ModelBeliefUpdate, ...]] = []
        diagnostics_by_payload: list[tuple[ModelAdequacyDiagnostic, ...]] = []
        effects_by_payload: list[tuple[MatchedEffectObservation, ...]] = []
        effect_maps: list[dict[RunMatchedEffectProjection, MatchedEffectObservation]] = []
        for index, projection in enumerate(returned_runs_in_actual_delivery_order):
            lineage, updates, diagnostics, effects, effect_map = _construct_returned_run_s3(
                projection,
                caches[index],
            )
            lineages.append(lineage)
            updates_by_payload.append(updates)
            diagnostics_by_payload.append(diagnostics)
            effects_by_payload.append(effects)
            effect_maps.append(effect_map)

        for index, projection in enumerate(returned_runs_in_actual_delivery_order):
            _construct_returned_run_s4(projection, caches[index])

        traces_by_payload: list[
            dict[RunPolicyTraceProjection, DecisionTrace | LookaheadPlanTrace]
        ] = []
        for index, projection in enumerate(returned_runs_in_actual_delivery_order):
            traces = _construct_returned_run_s5(projection, caches[index])
            traces_by_payload.append(traces)

        observations_by_payload: list[
            dict[RunRevealedObservationProjection, RevealedObservation]
        ] = []
        for index, projection in enumerate(returned_runs_in_actual_delivery_order):  # noqa: B007
            observations = _validate_returned_run_s6(projection)
            observations_by_payload.append(observations)

        calibrations: list[CalibrationDeployment | None] = []
        for index, projection in enumerate(returned_runs_in_actual_delivery_order):
            calibration = _construct_returned_run_s7_stage(
                projection.calibration,
                observations_by_payload[index],
                effect_maps[index],
            )
            calibrations.append(calibration)

        runs: list[BroaderArmRun] = []
        for index, projection in enumerate(returned_runs_in_actual_delivery_order):
            run = _construct_returned_run_s8_stage(
                projection,
                completed=completed_by_payload[index],
                evidence=evidence_by_payload[index],
                lineage=lineages[index],
                updates=updates_by_payload[index],
                diagnostics=diagnostics_by_payload[index],
                effects=effects_by_payload[index],
                calibration=calibrations[index],
                observations=observations_by_payload[index],
                traces=traces_by_payload[index],
            )
            runs.append(run)

        for index, run in enumerate(runs):  # noqa: B007
            _validate_returned_run_s9(run)

        for index, run in enumerate(runs):  # noqa: B007
            _validate_returned_run_s10(run)
    except ReturnedRunProjectionError as error:
        _reraise_returned_run_batch_error(error, index, payload_count)
    return tuple(runs)


def reconstruct_returned_run(projection: ReturnedRunProjection) -> BroaderArmRun:
    """Reconstruct and validate one payload in the frozen S1-S10 order."""

    _prepare_returned_run_batch(
        returned_runs_in_actual_delivery_order=(projection,),
        returned_domains_in_actual_delivery_order=None,
    )
    return _reconstruct_returned_run_batch((projection,))[0]


def _validate_returned_run_relation_context(
    run: BroaderArmRun,
    expected_run: BroaderArmRun | None,
) -> None:
    if expected_run is None:
        _missing_context("returned_run")
    if type(expected_run) is not BroaderArmRun:
        _structural("expected_run", "context must be a BroaderArmRun")
    if run != expected_run:
        _scientific("returned_run", "enclosing returned-run relation differs")


def validate_returned_run_relation(
    projection: ReturnedRunProjection,
    *,
    expected_run: BroaderArmRun | None = None,
) -> None:
    run = reconstruct_returned_run(projection)
    _validate_returned_run_relation_context(run, expected_run)


def result_payload_sha256(projection: ReturnedRunProjection) -> str:
    """Hash only a payload that has passed the complete frozen scientific gate."""

    reconstruct_returned_run(projection)
    return _accepted_result_payload_sha256(projection)


def _accepted_result_payload_sha256(projection: ReturnedRunProjection) -> str:
    return protocol_hash(
        "validation_evidence_returned_run_payload/v1",
        projection_as_dict(projection),
    )


def validate_returned_run_batch(
    *,
    returned_runs_in_actual_delivery_order: tuple[ReturnedRunProjection, ...],
    returned_domains_in_actual_delivery_order: tuple[BroaderArmRun, ...] | None,
) -> tuple[tuple[BroaderArmRun, str], ...]:
    """Validate returned runs in frozen S-number-major actual-delivery order."""

    _prepare_returned_run_batch(
        returned_runs_in_actual_delivery_order=returned_runs_in_actual_delivery_order,
        returned_domains_in_actual_delivery_order=returned_domains_in_actual_delivery_order,
    )
    runs = _reconstruct_returned_run_batch(returned_runs_in_actual_delivery_order)
    payload_count = len(runs)
    if returned_domains_in_actual_delivery_order is None:
        if not runs:
            _missing_context("returned_run")
        try:
            _validate_returned_run_relation_context(runs[0], None)
        except ReturnedRunProjectionError as error:
            _reraise_returned_run_batch_error(error, 0, payload_count)
    else:
        for index, (run, expected_run) in enumerate(
            zip(
                runs,
                returned_domains_in_actual_delivery_order,
                strict=True,
            )
        ):
            try:
                _validate_returned_run_relation_context(run, expected_run)
            except ReturnedRunProjectionError as error:
                _reraise_returned_run_batch_error(error, index, payload_count)
    hashes = tuple(
        _accepted_result_payload_sha256(projection)
        for projection in returned_runs_in_actual_delivery_order
    )
    return tuple(zip(runs, hashes, strict=True))


def projection_matches_domain(projection: object, value: object) -> bool:
    projection_as_dict(projection)
    if type(value) is Provenance:
        compared: object = project_provenance(value)
    elif type(value) is Candidate:
        compared = project_candidate(value)
    elif type(value) is CompletedExperiment:
        compared = project_completed_experiment(value)
    elif type(value) is Evidence:
        compared = project_evidence(value)
    elif type(value) is BeliefState:
        compared = project_belief_state(value)
    elif type(value) is HypothesisLikelihood:
        compared = project_hypothesis_likelihood(value)
    elif type(value) is BeliefUpdate:
        compared = project_belief_update(value)
    elif type(value) is MatchedEffectObservation:
        compared = project_matched_effect(value)
    elif type(value) is SigmaEstimate:
        compared = project_sigma_estimate(value)
    elif type(value) is ModelBeliefState:
        compared = project_model_belief_state(value)
    elif type(value) is BeliefModelLineage:
        compared = project_lineage(value)
    elif type(value) is PredictiveInterval:
        compared = project_predictive_interval(value)
    elif type(value) is ModelAdequacyDiagnostic:
        compared = project_diagnostic(value)
    elif type(value) is ModelBeliefUpdate:
        compared = project_model_update(value)
    elif type(value) is CalibrationGroupEstimate:
        if type(projection) is not RunCalibrationEstimateProjection:
            _structural(
                "comparison",
                "projection and domain types do not form a foundational pair",
            )
        run_id = _calibration_run_id(
            projection.observations,
            path="calibration_estimate.observations",
        )
        compared = project_calibration_estimate(value, expected_run_id=run_id)
    elif type(value) is CalibrationDeployment:
        if type(projection) is not RunCalibrationProjection:
            _structural(
                "comparison",
                "projection and domain types do not form a foundational pair",
            )
        run_id = _calibration_run_id(
            projection.observations,
            path="calibration.observations",
        )
        compared = project_calibration(value, expected_run_id=run_id)
    elif type(value) is PublicExperimentDesign:
        compared = project_public_experiment_design(value)
    elif type(value) is HypothesisDecisionContext:
        compared = project_hypothesis_decision_context(value)
    elif type(value) is CandidateScore:
        compared = project_candidate_score(value)
    elif type(value) is DecisionTrace:
        compared = project_decision_trace(value)
    elif type(value) is LookaheadSecondAction:
        compared = project_lookahead_second_action(value)
    elif type(value) is LookaheadBranch:
        compared = project_lookahead_branch(value)
    elif type(value) is LookaheadFirstActionPlan:
        compared = project_lookahead_first_action(value)
    elif type(value) is LookaheadAlternative:
        compared = project_lookahead_alternative(value)
    elif type(value) is LookaheadPlanTrace:
        compared = project_lookahead_trace(value)
    elif type(value) is ArmDecision:
        compared = project_arm_decision(value)
    elif type(value) is ArmAction:
        if type(projection) is not RunArmActionProjection:
            _structural(
                "comparison",
                "projection and domain types do not form a foundational pair",
            )
        authorization = (
            None
            if projection.oracle_observation is None
            else projection.oracle_observation.authorization
        )
        compared = _project_arm_action(
            value,
            authorization,
            validate_science=True,
        )
    elif type(value) is BroaderArmRun:
        compared = project_returned_run(value)
    else:
        _structural("comparison", "unsupported foundational domain type")
    if type(projection) is not type(compared):
        _structural("comparison", "projection and domain types do not form a foundational pair")
    return projection == compared


def validate_completed_experiment_relation(
    projection: RunCompletedExperimentProjection, *, expected_record_id: int | None = None
) -> None:
    projection_as_dict(projection)
    if expected_record_id is None:
        _missing_context("completed_experiment.record_id")
    if projection.record_id != _i64(expected_record_id, "expected_record_id"):
        _scientific("completed_experiment.record_id", "enclosing record relation differs")


def validate_evidence_relations(
    projection: RunEvidenceProjection,
    *,
    expected_source_experiment_ids: tuple[int, ...] | None = None,
    expected_created_at: str | None = None,
) -> None:
    projection_as_dict(projection)
    if expected_source_experiment_ids is None or expected_created_at is None:
        _missing_context("evidence")
    expected = _projected_items(
        expected_source_experiment_ids, "expected_source_experiment_ids", _i64
    )
    if projection.source_experiment_ids != expected:
        _scientific("evidence.source_experiment_ids", "enclosing references differ")
    if projection.created_at != _string(expected_created_at, "expected_created_at"):
        _scientific("evidence.created_at", "enclosing chronology differs")


def validate_belief_state_relation(
    projection: RunBeliefStateProjection, *, expected_state: BeliefState | None = None
) -> None:
    projection_as_dict(projection)
    if expected_state is None:
        _missing_context("belief_state")
    if type(expected_state) is not BeliefState:
        _structural("expected_state", "context must be a BeliefState")
    if project_belief_state(expected_state) != projection:
        _scientific("belief_state", "enclosing lineage relation differs")


def validate_belief_update_relation(
    projection: RunBeliefUpdateProjection, *, expected_update: BeliefUpdate | None = None
) -> None:
    projection_as_dict(projection)
    if expected_update is None:
        _missing_context("belief_update")
    if type(expected_update) is not BeliefUpdate:
        _structural("expected_update", "context must be a BeliefUpdate")
    if project_belief_update(expected_update) != projection:
        _scientific("belief_update", "enclosing update relation differs")


def _validate_expected_projection(projection: object, expected: object | None, path: str) -> None:
    if expected is None:
        _missing_context(path)
    if not projection_matches_domain(projection, expected):
        _scientific(path, "enclosing scientific relation differs")


def validate_matched_effect_relation(
    projection: RunMatchedEffectProjection,
    *,
    expected_effect: MatchedEffectObservation | None = None,
) -> None:
    reconstruct_matched_effect(projection)
    _validate_expected_projection(projection, expected_effect, "matched_effect")


def validate_sigma_estimate_relation(
    projection: RunSigmaEstimateProjection,
    *,
    expected_estimate: SigmaEstimate | None = None,
) -> None:
    reconstruct_sigma_estimate(projection)
    _validate_expected_projection(projection, expected_estimate, "sigma_estimate")


def validate_model_belief_state_relation(
    projection: RunModelBeliefStateProjection,
    *,
    expected_state: ModelBeliefState | None = None,
) -> None:
    reconstruct_model_belief_state(projection)
    _validate_expected_projection(projection, expected_state, "model_belief_state")


def validate_lineage_relation(
    projection: RunLineageProjection,
    *,
    expected_lineage: BeliefModelLineage | None = None,
) -> None:
    reconstruct_lineage(projection)
    _validate_expected_projection(projection, expected_lineage, "lineage")


def validate_predictive_interval_relation(
    projection: RunPredictiveIntervalProjection,
    *,
    expected_observation: float | None = None,
) -> None:
    projection_as_dict(projection)
    if expected_observation is None:
        _missing_context("predictive_interval")
    _project_float(expected_observation, "expected_observation")
    _reconstruct_predictive_interval(projection, "predictive_interval", expected_observation)


def validate_diagnostic_relation(
    projection: RunDiagnosticProjection,
    *,
    expected_diagnostic: ModelAdequacyDiagnostic | None = None,
) -> None:
    reconstruct_diagnostic(projection)
    _validate_expected_projection(projection, expected_diagnostic, "diagnostic")


def validate_model_update_relation(
    projection: RunModelUpdateProjection,
    *,
    expected_update: ModelBeliefUpdate | None = None,
) -> None:
    reconstruct_model_update(projection)
    if expected_update is None:
        _missing_context("model_update")
    if type(expected_update) is not ModelBeliefUpdate:
        _structural("expected_update", "context must be a ModelBeliefUpdate")
    relations = (
        (projection.provenance, expected_update.provenance, "model_update.provenance"),
        (projection.state_before, expected_update.state_before, "model_update.state_before"),
        (projection.evidence, expected_update.evidence, "model_update.evidence"),
        (projection.sigma_estimate, expected_update.sigma_estimate, "model_update.sigma_estimate"),
        (
            projection.bayesian_update,
            expected_update.bayesian_update,
            "model_update.bayesian_update",
        ),
        (
            projection.posterior_state,
            expected_update.posterior_state,
            "model_update.posterior_state",
        ),
        (projection.diagnostic, expected_update.diagnostic, "model_update.diagnostic"),
    )
    for nested, expected, path in relations:
        _validate_expected_projection(nested, expected, path)
    _validate_expected_projection(projection, expected_update, "model_update")


def _validate_calibration_observation_context(
    projection: RunRevealedObservationProjection,
    expected: RevealedObservation,
    *,
    calibration_prefix_id: str,
    expected_run_id: str,
    expected_world_id: str,
    expected_seed: int,
) -> None:
    authorization = _calibration_authorization(
        expected,
        calibration_prefix_id=calibration_prefix_id,
        expected_run_id=expected_run_id,
    )
    authorization_id = recompute_observation_authorization_id(authorization)
    validate_revealed_observation_relations(
        projection,
        expected_authorization=authorization,
        expected_authorization_id=authorization_id,
        expected_namespace=expected.namespace,
        expected_world_id=expected_world_id,
        expected_seed=expected_seed,
        expected_candidate_id=expected.candidate_id,
        expected_comparison_group_id=expected.comparison_group_id,
        expected_intervention_arm=expected.intervention_arm,
        expected_replication_id=expected.replication_id,
        expected_key_fields=expected.key_fields,
        expected_oracle_key_id=expected.oracle_key_id,
        expected_outcome_digest=expected.outcome_digest,
        expected_oracle_use_id=expected.oracle_use_id,
    )
    expected_projection = _project_revealed_observation(
        expected,
        authorization,
        validate_science=True,
    )
    if projection != expected_projection:
        _scientific(
            "calibration_estimate.observations",
            "enclosing observation value differs",
        )


def validate_calibration_estimate_relation(
    projection: RunCalibrationEstimateProjection,
    *,
    expected_estimate: CalibrationGroupEstimate | None = None,
    expected_run_id: str | None = None,
    expected_world_id: str | None = None,
    expected_seed: int | None = None,
    expected_belief_model_version: str | None = None,
) -> None:
    """Validate one estimate against complete immutable enclosing run context."""

    reconstruct_calibration_estimate(projection)
    if expected_estimate is None:
        _missing_context("calibration_estimate")
    if expected_run_id is None:
        _missing_context("calibration_estimate.run_id")
    if expected_world_id is None:
        _missing_context("calibration_estimate.world_id")
    if expected_seed is None:
        _missing_context("calibration_estimate.seed")
    if expected_belief_model_version is None:
        _missing_context("calibration_estimate.belief_model_version")
    if type(expected_estimate) is not CalibrationGroupEstimate:
        _structural("expected_estimate", "context must be a CalibrationGroupEstimate")
    run_id = _id(expected_run_id, "expected_run_id")
    world_id = _id(expected_world_id, "expected_world_id")
    seed = _i64(expected_seed, "expected_seed")
    model_version = _string(
        expected_belief_model_version,
        "expected_belief_model_version",
    )
    if model_version != CALIBRATED_SIGMA_MODEL_VERSION:
        _scientific(
            "calibration_estimate.belief_model_version",
            "enclosing belief model version differs",
        )
    expected_prefix = (
        f"calibration-prefix/{world_id}/{seed}/{expected_estimate.comparison_group_id}"
    )
    if expected_estimate.calibration_prefix_id != expected_prefix:
        _scientific(
            "calibration_estimate.calibration_prefix_id",
            "enclosing world/seed/group prefix differs",
        )
    if len(projection.effects) != len(expected_estimate.effects):
        _scientific("calibration_estimate.effects", "enclosing effect count differs")
    for nested_effect, expected_effect in zip(
        projection.effects,
        expected_estimate.effects,
        strict=True,
    ):
        validate_matched_effect_relation(nested_effect, expected_effect=expected_effect)
    if len(projection.observations) != len(expected_estimate.observations):
        _scientific(
            "calibration_estimate.observations",
            "enclosing observation count differs",
        )
    for nested_observation, expected_observation in zip(
        projection.observations,
        expected_estimate.observations,
        strict=True,
    ):
        _validate_calibration_observation_context(
            nested_observation,
            expected_observation,
            calibration_prefix_id=expected_prefix,
            expected_run_id=run_id,
            expected_world_id=world_id,
            expected_seed=seed,
        )
    expected_projection = project_calibration_estimate(
        expected_estimate,
        expected_run_id=run_id,
    )
    if projection != expected_projection:
        _scientific("calibration_estimate", "enclosing estimate relation differs")


def validate_calibration_relation(
    projection: RunCalibrationProjection,
    *,
    expected_calibration: CalibrationDeployment | None = None,
    expected_run_id: str | None = None,
    expected_world_id: str | None = None,
    expected_seed: int | None = None,
    expected_belief_model_version: str | None = None,
    expected_lineage_id: str | None = None,
) -> None:
    """Validate deployment order and every estimate's immutable run context."""

    reconstruct_calibration(projection)
    if expected_calibration is None:
        _missing_context("calibration")
    if expected_run_id is None:
        _missing_context("calibration.run_id")
    if expected_world_id is None:
        _missing_context("calibration.world_id")
    if expected_seed is None:
        _missing_context("calibration.seed")
    if expected_belief_model_version is None:
        _missing_context("calibration.belief_model_version")
    if expected_lineage_id is None:
        _missing_context("calibration.lineage_id")
    if type(expected_calibration) is not CalibrationDeployment:
        _structural("expected_calibration", "context must be a CalibrationDeployment")
    run_id = _id(expected_run_id, "expected_run_id")
    world_id = _id(expected_world_id, "expected_world_id")
    seed = _i64(expected_seed, "expected_seed")
    model_version = _string(
        expected_belief_model_version,
        "expected_belief_model_version",
    )
    lineage_id = _id(expected_lineage_id, "expected_lineage_id")
    if len(projection.estimates) != len(expected_calibration.estimates):
        _scientific("calibration.estimates", "enclosing estimate count differs")
    for nested, expected in zip(
        projection.estimates,
        expected_calibration.estimates,
        strict=True,
    ):
        if expected.lineage_id != lineage_id:
            _scientific(
                "calibration_estimate.lineage_id",
                "enclosing deployment lineage differs",
            )
        validate_calibration_estimate_relation(
            nested,
            expected_estimate=expected,
            expected_run_id=run_id,
            expected_world_id=world_id,
            expected_seed=seed,
            expected_belief_model_version=model_version,
        )
    expected_projection = project_calibration(
        expected_calibration,
        expected_run_id=run_id,
    )
    if projection != expected_projection:
        _scientific("calibration", "enclosing deployment relation differs")


def validate_public_experiment_design_relation(
    projection: RunPublicExperimentDesignProjection,
    *,
    expected_design: PublicExperimentDesign | None = None,
) -> None:
    reconstruct_public_experiment_design(projection)
    _validate_expected_projection(projection, expected_design, "public_experiment_design")


def validate_hypothesis_decision_context_relation(
    projection: RunHypothesisDecisionContextProjection,
    *,
    expected_context: HypothesisDecisionContext | None = None,
) -> None:
    reconstruct_hypothesis_decision_context(projection)
    _validate_expected_projection(projection, expected_context, "hypothesis_decision_context")


def validate_candidate_score_relation(
    projection: RunCandidateScoreProjection,
    *,
    expected_score: CandidateScore | None = None,
) -> None:
    reconstruct_candidate_score(projection)
    _validate_expected_projection(projection, expected_score, "candidate_score")


def validate_decision_trace_relation(
    projection: RunDecisionTraceProjection,
    *,
    expected_trace: DecisionTrace | None = None,
) -> None:
    reconstruct_decision_trace(projection)
    _validate_expected_projection(projection, expected_trace, "decision_trace")


def validate_lookahead_trace_relation(
    projection: RunLookaheadTraceProjection,
    *,
    expected_trace: LookaheadPlanTrace | None = None,
) -> None:
    reconstruct_lookahead_trace(projection)
    _validate_expected_projection(projection, expected_trace, "lookahead_trace")


def validate_policy_trace_relation(
    projection: RunPolicyTraceProjection,
    *,
    expected_trace: DecisionTrace | LookaheadPlanTrace | None = None,
) -> None:
    reconstruct_policy_trace(projection)
    if expected_trace is None:
        _missing_context("policy_trace")
    if project_policy_trace(expected_trace) != projection:
        _scientific("policy_trace", "enclosing scientific relation differs")


def _validate_arm_decision_action_relation(
    decision: ArmDecision,
    action: ArmAction,
    *,
    path: str,
) -> None:
    relations = (
        (action.step, decision.step, "step"),
        (action.decision_id, decision.decision_id, "decision_id"),
        (action.candidate_id, decision.selected_candidate_id, "candidate_id"),
    )
    for actual, expected, field in relations:
        if actual != expected:
            _scientific(f"{path}.{field}", "paired decision/action relation differs")
    if action.cost > decision.remaining_budget:
        _scientific(f"{path}.cost", "selected action was not affordable")


def _validate_arm_decision_id(
    decision: ArmDecision,
    expected_run_id: str,
    *,
    path: str = "arm_decision.decision_id",
) -> None:
    run_id = _id(expected_run_id, "expected_run_id")
    expected = f"decision/{run_id}/{decision.step:04d}"
    if decision.decision_id != expected:
        _scientific(path, "run/step decision identity differs")


def validate_arm_decision_relation(
    projection: RunArmDecisionProjection,
    *,
    expected_decision: ArmDecision | None = None,
    expected_action: ArmAction | None = None,
    expected_run_id: str | None = None,
) -> None:
    decision = reconstruct_arm_decision(projection)
    if expected_decision is None:
        _missing_context("arm_decision")
    if expected_action is None:
        _missing_context("arm_decision.action")
    if expected_run_id is None:
        _missing_context("arm_decision.run_id")
    if type(expected_decision) is not ArmDecision:
        _structural("expected_decision", "context must be an ArmDecision")
    if type(expected_action) is not ArmAction:
        _structural("expected_action", "context must be an ArmAction")
    project_arm_action(expected_action, expected_run_id=expected_run_id)
    expected_projection = project_arm_decision(expected_decision)
    _validate_arm_decision_id(decision, expected_run_id)
    _validate_arm_decision_action_relation(decision, expected_action, path="arm_decision.action")
    if expected_projection != projection:
        _scientific("arm_decision", "enclosing decision relation differs")


def validate_arm_action_relation(
    projection: RunArmActionProjection,
    *,
    expected_action: ArmAction | None = None,
    expected_decision: ArmDecision | None = None,
    expected_run_id: str | None = None,
    expected_previous_cumulative_decision_cost: float | None = None,
) -> None:
    action = reconstruct_arm_action(projection)
    if expected_action is None:
        _missing_context("arm_action")
    if expected_decision is None:
        _missing_context("arm_action.decision")
    if expected_run_id is None:
        _missing_context("arm_action.run_id")
    if expected_previous_cumulative_decision_cost is None:
        _missing_context("arm_action.cumulative_decision_cost")
    if type(expected_action) is not ArmAction:
        _structural("expected_action", "context must be an ArmAction")
    if type(expected_decision) is not ArmDecision:
        _structural("expected_decision", "context must be an ArmDecision")
    project_arm_decision(expected_decision)
    _validate_arm_decision_id(
        expected_decision,
        expected_run_id,
        path="arm_action.decision_id",
    )
    _validate_arm_decision_action_relation(expected_decision, action, path="arm_action")
    previous = _project_float(
        expected_previous_cumulative_decision_cost,
        "expected_previous_cumulative_decision_cost",
    )
    previous_value = _float_from_f64(previous, "expected_previous_cumulative_decision_cost")
    if not _same_f64(
        action.cumulative_decision_cost,
        previous_value + action.cost,
        "arm_action.cumulative_decision_cost",
    ):
        _scientific(
            "arm_action.cumulative_decision_cost",
            "cumulative cost does not extend the prior action prefix",
        )
    oracle = projection.oracle_observation
    if oracle is not None:
        expected_authorization = RunObservationAuthorizationProjection(
            action.candidate_id,
            "decision",
            _id(expected_run_id, "expected_run_id"),
            action.decision_id,
        )
        expected_authorization_id = recompute_observation_authorization_id(expected_authorization)
        validate_observation_authorization_relation(
            oracle.authorization,
            expected_candidate_id=action.candidate_id,
            expected_kind="decision",
            expected_run_id=expected_run_id,
            expected_source_id=action.decision_id,
            expected_authorization_id=expected_authorization_id,
        )
    expected_projection = project_arm_action(
        expected_action,
        expected_run_id=expected_run_id,
    )
    if expected_projection != projection:
        _scientific("arm_action", "enclosing action relation differs")
