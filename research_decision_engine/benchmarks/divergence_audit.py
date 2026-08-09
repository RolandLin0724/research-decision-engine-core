"""Frozen, truth-safe divergence-mechanism audit over recorded trajectories."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import random
import statistics
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from research_decision_engine.belief_models import (
    CALIBRATED_SIGMA_MODEL_ID,
    FIXED_SIGMA,
    FIXED_SIGMA_MODEL_ID,
    MINIMUM_PRIOR_EFFECTS,
    SIGMA_FLOOR,
)
from research_decision_engine.decision import (
    discretized_gaussian_evidence_outcomes,
    expected_information_gain,
)
from research_decision_engine.evidence_eligibility import (
    OptimizerEvidenceEligibilityContract,
    PublicExperimentDesign,
    default_public_design,
)
from research_decision_engine.optimizer_effect import optimizer_effect_hypotheses
from research_decision_engine.reasoning import (
    BeliefState,
    GaussianEvidencePrediction,
    Hypothesis,
)
from research_decision_engine.types import Candidate, CompletedExperiment

AUDIT_VERSION = "divergence-mechanism-audit/v1"
AUDIT_SCHEMA_VERSION = "divergence-audit-artifacts/v1"
CLASSIFICATION_RULE_VERSION = "frozen-divergence-mechanisms/v1"
SCORING_ADAPTER_VERSION = "read-only-recorded-state-scorer/v1"
EXPECTED_DIVERGENCE_COUNT = 189
EXPECTED_HELPED_COUNT = 68
EXPECTED_HURT_COUNT = 118
EXPECTED_MIXED_COUNT = 3
NUMERICAL_TOLERANCE = 1e-12
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_MASTER_SEED = 20_260_710
BOOTSTRAP_MINIMUM_USABLE = 50
COMMITMENT_THRESHOLD = 0.80
DOMINANCE_PREVALENCE = 0.40

type JsonObject = dict[str, Any]
type OutcomeLabel = Literal["helped", "hurt", "mixed", "tied"]
type SetRelation = Literal["SAME_SET_DIFFERENT_ORDER", "PARTIAL_OVERLAP", "DISJOINT"]
type Mechanism = Literal[
    "SCORE_FLATTENING",
    "BELIEF_STATE_REORDERING",
    "GROUP_SIGMA_REORDERING",
    "BELIEF_SIGMA_INTERACTION",
    "COST_TIEBREAK_CHANGE",
    "PAIR_COMPLETION_DELAY",
    "PAIR_OPENER_CHANGE",
    "SAME_SET_DIFFERENT_ORDER",
    "BUDGET_CROWD_OUT",
    "CONSERVATIVE_NONCOMMITMENT",
    "PLANNER_MODEL_MISMATCH",
    "NO_STABLE_MECHANISM",
]

MECHANISMS: tuple[Mechanism, ...] = (
    "SCORE_FLATTENING",
    "BELIEF_STATE_REORDERING",
    "GROUP_SIGMA_REORDERING",
    "BELIEF_SIGMA_INTERACTION",
    "COST_TIEBREAK_CHANGE",
    "PAIR_COMPLETION_DELAY",
    "PAIR_OPENER_CHANGE",
    "SAME_SET_DIFFERENT_ORDER",
    "BUDGET_CROWD_OUT",
    "CONSERVATIVE_NONCOMMITMENT",
    "PLANNER_MODEL_MISMATCH",
    "NO_STABLE_MECHANISM",
)

PASS_A_FILENAMES = frozenset(
    {
        "run_manifest.json",
        "protocol_snapshot.json",
        "potential_outcome_commitments.jsonl",
        "decision_traces.jsonl",
        "evidence_belief_traces.jsonl",
        "calibration_prefixes.jsonl",
    }
)
PASS_B_FILENAMES = frozenset(
    {
        "divergence_events.jsonl",
        "per_run_results.jsonl",
        "threshold_results.csv",
    }
)
FORBIDDEN_INPUT_FILENAMES = frozenset(
    {
        "potential_outcomes.jsonl",
        "failure_cases.jsonl",
    }
)

FROZEN_OUTPUT_FILENAMES = (
    "divergence_manifest.json",
    "divergence_cases.jsonl",
    "divergence_cases.csv",
    "mechanism_summary.csv",
    "mechanism_by_condition.csv",
    "score_decomposition.csv",
    "sequence_comparison.csv",
    "harm_concentration.csv",
    "planner_compatibility_audit.json",
    "DIVERGENCE_AUDIT_REPORT.md",
)


class DivergenceAuditError(RuntimeError):
    """Raised when a frozen audit invariant cannot be satisfied."""


@dataclass(frozen=True, slots=True)
class CandidateRecord:
    """One public candidate specification reconstructed from recorded traces."""

    candidate: Candidate
    cost: float
    public_design: PublicExperimentDesign

    def to_dict(self) -> JsonObject:
        return {
            "candidate_id": self.candidate.candidate_id,
            "params": self.candidate.params(),
            "cost": self.cost,
            "public_design": self.public_design.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class RecordedPredictionSnapshot:
    """Truth-free hypothesis predictions recorded for one comparison group."""

    snapshot_id: str
    belief_model_id: str
    belief_model_version: str
    lineage_id: str
    belief_state_id: str
    comparison_group_id: str
    estimated_sigma: float
    sigma_status: str
    source_effect_ids: tuple[str, ...]
    means: tuple[tuple[str, float], ...]
    standard_deviations: tuple[tuple[str, float], ...]

    @classmethod
    def from_json(cls, row: Mapping[str, Any]) -> RecordedPredictionSnapshot:
        predictions = _mapping(row["hypothesis_predictions"], "hypothesis predictions")
        means: list[tuple[str, float]] = []
        sigmas: list[tuple[str, float]] = []
        for hypothesis_id in sorted(predictions):
            parameters = _mapping(predictions[hypothesis_id], "hypothesis parameters")
            means.append((hypothesis_id, _number(parameters["mean"], "hypothesis mean")))
            sigmas.append(
                (
                    hypothesis_id,
                    _number(parameters["standard_deviation"], "hypothesis sigma"),
                )
            )
        return cls(
            snapshot_id=_text(row["snapshot_id"], "snapshot ID"),
            belief_model_id=_text(row["belief_model_id"], "belief model ID"),
            belief_model_version=_text(row["belief_model_version"], "belief model version"),
            lineage_id=_text(row["lineage_id"], "lineage ID"),
            belief_state_id=_text(row["belief_state_id"], "belief state ID"),
            comparison_group_id=_text(row["comparison_group_id"], "comparison group ID"),
            estimated_sigma=_number(row["estimated_sigma"], "estimated sigma"),
            sigma_status=_text(row["sigma_status"], "sigma status"),
            source_effect_ids=tuple(
                _text(item, "source effect ID")
                for item in _sequence(row["source_effect_ids"], "source effect IDs")
            ),
            means=tuple(means),
            standard_deviations=tuple(sigmas),
        )

    def to_dict(self) -> JsonObject:
        return {
            "snapshot_id": self.snapshot_id,
            "belief_model_id": self.belief_model_id,
            "belief_model_version": self.belief_model_version,
            "lineage_id": self.lineage_id,
            "belief_state_id": self.belief_state_id,
            "comparison_group_id": self.comparison_group_id,
            "estimated_sigma": self.estimated_sigma,
            "sigma_status": self.sigma_status,
            "source_effect_ids": list(self.source_effect_ids),
            "means": dict(self.means),
            "standard_deviations": dict(self.standard_deviations),
        }


@dataclass(frozen=True, slots=True)
class DivergencePair:
    """Truth-free pairing discovered solely from selected-action sequences."""

    divergence_id: str
    case_id: str
    world_id: str
    seed: int
    budget_label: str
    policy: str
    fixed_run_id: str
    calibrated_run_id: str
    common_prefix_length: int
    first_divergence_step: int
    fixed_sequence: tuple[str, ...]
    calibrated_sequence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BranchScore:
    """One immutable branch in a read-only score reconstruction."""

    branch_id: str
    probability: float
    posterior_probabilities: tuple[float, ...]
    posterior_entropy: float
    second_candidate_id: str
    second_action_effect: str
    second_information_gain: float
    second_cost: float
    terminal_entropy: float
    branch_total_cost: float
    budget_feasible: bool

    def to_dict(self, hypothesis_ids: tuple[str, ...]) -> JsonObject:
        return {
            "branch_id": self.branch_id,
            "probability": self.probability,
            "posterior_probabilities": dict(
                zip(hypothesis_ids, self.posterior_probabilities, strict=True)
            ),
            "posterior_entropy": self.posterior_entropy,
            "second_candidate_id": self.second_candidate_id,
            "second_action_effect": self.second_action_effect,
            "second_information_gain": self.second_information_gain,
            "second_cost": self.second_cost,
            "terminal_entropy": self.terminal_entropy,
            "branch_total_cost": self.branch_total_cost,
            "budget_feasible": self.budget_feasible,
        }


@dataclass(frozen=True, slots=True)
class CandidatePlanScore:
    """Reconstructed frozen two-step score for one recorded first candidate."""

    candidate_id: str
    action_effect: str
    comparison_group_id: str
    first_cost: float
    prior_entropy: float
    immediate_information_gain: float
    delayed_information_gain: float
    expected_terminal_entropy: float
    expected_total_information_gain: float
    expected_total_cost: float
    information_gain_per_expected_cost: float
    branches: tuple[BranchScore, ...]

    def sort_key(self) -> tuple[float, float, float, str]:
        return (
            -self.expected_total_information_gain,
            self.expected_total_cost,
            -self.information_gain_per_expected_cost,
            self.candidate_id,
        )

    def to_dict(self, hypothesis_ids: tuple[str, ...]) -> JsonObject:
        branch_payload = [item.to_dict(hypothesis_ids) for item in self.branches]
        return {
            "candidate_id": self.candidate_id,
            "action_effect": self.action_effect,
            "comparison_group_id": self.comparison_group_id,
            "first_cost": self.first_cost,
            "prior_entropy": self.prior_entropy,
            "immediate_information_gain": self.immediate_information_gain,
            "delayed_information_gain": self.delayed_information_gain,
            "expected_terminal_entropy": self.expected_terminal_entropy,
            "expected_total_information_gain": self.expected_total_information_gain,
            "expected_total_cost": self.expected_total_cost,
            "information_gain_per_expected_cost": self.information_gain_per_expected_cost,
            "branch_count": len(branch_payload),
            "branch_probability_sum": math.fsum(item.probability for item in self.branches),
            "all_branches_budget_feasible": all(item.budget_feasible for item in self.branches),
            "branch_tree_sha256": _stable_hash(branch_payload),
            "branches": branch_payload,
        }


@dataclass(frozen=True, slots=True)
class ContextReplay:
    """Complete candidate ranking in one crossed posterior/sigma context."""

    context: Literal["FF", "CF", "FC", "CC"]
    hypothesis_ids: tuple[str, ...]
    posterior_probabilities: tuple[float, ...]
    sigma_by_group: tuple[tuple[str, float], ...]
    ranked_plans: tuple[CandidatePlanScore, ...]

    @property
    def winner(self) -> CandidatePlanScore:
        return self.ranked_plans[0]

    def plan(self, candidate_id: str) -> CandidatePlanScore:
        for item in self.ranked_plans:
            if item.candidate_id == candidate_id:
                return item
        raise DivergenceAuditError(f"Missing replay score for candidate {candidate_id}.")

    def to_dict(self) -> JsonObject:
        return {
            "context": self.context,
            "posterior_probabilities": dict(
                zip(self.hypothesis_ids, self.posterior_probabilities, strict=True)
            ),
            "sigma_by_group": dict(self.sigma_by_group),
            "winner": self.winner.candidate_id,
            "ranked_plans": [item.to_dict(self.hypothesis_ids) for item in self.ranked_plans],
        }


@dataclass(frozen=True, slots=True)
class SequenceSummary:
    """Truth-free comparison of the two recorded selected-action sequences."""

    fixed_sequence: tuple[str, ...]
    calibrated_sequence: tuple[str, ...]
    fixed_action_effects: tuple[str, ...]
    calibrated_action_effects: tuple[str, ...]
    fixed_pair_events: tuple[JsonObject, ...]
    calibrated_pair_events: tuple[JsonObject, ...]
    fixed_first_evidence_step: int | None
    calibrated_first_evidence_step: int | None
    fixed_first_evidence_cost: float | None
    calibrated_first_evidence_cost: float | None
    fixed_cost_before_first_evidence: float | None
    calibrated_cost_before_first_evidence: float | None
    fixed_remaining_budget_after_first_evidence: float | None
    calibrated_remaining_budget_after_first_evidence: float | None
    fixed_evidence_count: int
    calibrated_evidence_count: int
    fixed_evidence_order: tuple[str, ...]
    calibrated_evidence_order: tuple[str, ...]
    fixed_sigma_source_order: tuple[tuple[str, ...], ...]
    calibrated_sigma_source_order: tuple[tuple[str, ...], ...]
    fixed_final_set: tuple[str, ...]
    calibrated_final_set: tuple[str, ...]
    intersection: tuple[str, ...]
    union: tuple[str, ...]
    set_relation: SetRelation
    jaccard_similarity: float
    order_similarity: float
    sequence_edit_distance: int
    fixed_commitment_step: int | None
    calibrated_commitment_step: int | None
    calibrated_delayed_commitment: bool
    pair_completion_delay: JsonObject | None
    budget_crowd_out: JsonObject | None
    fixed_decision_cost: float
    calibrated_decision_cost: float
    fixed_stop_reason: str
    calibrated_stop_reason: str

    def to_dict(self) -> JsonObject:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MechanismClassification:
    """One deterministic primary label plus all true contributing predicates."""

    primary_mechanism: Mechanism
    contributing_mechanisms: tuple[Mechanism, ...]
    predicate_evidence: tuple[tuple[Mechanism, JsonObject], ...]
    classification_confidence: str = "rule_determined"
    rule_version: str = CLASSIFICATION_RULE_VERSION

    def to_dict(self) -> JsonObject:
        return {
            "primary_mechanism": self.primary_mechanism,
            "contributing_mechanisms": list(self.contributing_mechanisms),
            "classification_confidence": self.classification_confidence,
            "rule_version": self.rule_version,
            "predicate_evidence": {
                mechanism: evidence for mechanism, evidence in self.predicate_evidence
            },
        }


@dataclass(frozen=True, slots=True)
class TruthFreeDivergenceCase:
    """Complete classifier output whose type cannot represent evaluator truth."""

    pair: DivergencePair
    oracle_version: str
    commitment_id: str
    budget: float
    public_initial_fingerprint: str
    fixed_belief_state_id: str
    calibrated_belief_state_id: str
    fixed_lineage_id: str
    calibrated_lineage_id: str
    fixed_posterior: tuple[tuple[str, float], ...]
    calibrated_posterior: tuple[tuple[str, float], ...]
    fixed_snapshots: tuple[RecordedPredictionSnapshot, ...]
    calibrated_snapshots: tuple[RecordedPredictionSnapshot, ...]
    candidates: tuple[CandidateRecord, ...]
    replays: tuple[ContextReplay, ...]
    decomposition: JsonObject
    sequence: SequenceSummary
    classification: MechanismClassification
    compatibility_passed: bool
    compatibility_check_ids: tuple[str, ...]

    def replay(self, context: str) -> ContextReplay:
        for item in self.replays:
            if item.context == context:
                return item
        raise DivergenceAuditError(f"Missing crossed replay context {context}.")

    def to_dict(self) -> JsonObject:
        pair_payload = asdict(self.pair)
        return {
            "audit_version": AUDIT_VERSION,
            "case_id": self.pair.case_id,
            "pair": pair_payload,
            "oracle_version": self.oracle_version,
            "commitment_id": self.commitment_id,
            "budget": self.budget,
            "public_initial_fingerprint": self.public_initial_fingerprint,
            "fixed_belief_state_id": self.fixed_belief_state_id,
            "calibrated_belief_state_id": self.calibrated_belief_state_id,
            "fixed_lineage_id": self.fixed_lineage_id,
            "calibrated_lineage_id": self.calibrated_lineage_id,
            "fixed_posterior": dict(self.fixed_posterior),
            "calibrated_posterior": dict(self.calibrated_posterior),
            "fixed_snapshots": [item.to_dict() for item in self.fixed_snapshots],
            "calibrated_snapshots": [item.to_dict() for item in self.calibrated_snapshots],
            "candidates": [item.to_dict() for item in self.candidates],
            "four_context_replays": [item.to_dict() for item in self.replays],
            "score_decomposition": self.decomposition,
            "sequence_analysis": self.sequence.to_dict(),
            "classification": self.classification.to_dict(),
            "compatibility_passed": self.compatibility_passed,
            "compatibility_check_ids": list(self.compatibility_check_ids),
        }


@dataclass(frozen=True, slots=True)
class EvaluatorOutcome:
    """Pass-B-only truth-dependent labels and final metrics."""

    divergence_id: str
    outcome_label: OutcomeLabel
    hidden_true_hypothesis: str
    fixed_metrics: JsonObject
    calibrated_metrics: JsonObject
    metric_differences: JsonObject

    def to_dict(self) -> JsonObject:
        return {
            "divergence_id": self.divergence_id,
            "outcome_label": self.outcome_label,
            "hidden_true_hypothesis": self.hidden_true_hypothesis,
            "fixed_metrics": self.fixed_metrics,
            "calibrated_metrics": self.calibrated_metrics,
            "metric_differences": self.metric_differences,
        }


@dataclass(frozen=True, slots=True)
class AuditedDivergenceCase:
    """Immutable Pass-A classification joined to a separate Pass-B outcome."""

    truth_free: TruthFreeDivergenceCase
    truth_free_sha256: str
    evaluator_only: EvaluatorOutcome

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "case_id": self.truth_free.pair.case_id,
            "truth_free_sha256": self.truth_free_sha256,
            "truth_free": self.truth_free.to_dict(),
            "evaluator_only": self.evaluator_only.to_dict(),
        }


@dataclass(slots=True)
class CompatibilityAccumulator:
    """Aggregate deterministic compatibility checks without evaluator fields."""

    checked: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    failures: dict[str, list[JsonObject]] = field(default_factory=lambda: defaultdict(list))
    maximum_error: dict[str, float] = field(default_factory=dict)

    def record(
        self,
        check_id: str,
        record_id: str,
        passed: bool,
        *,
        expected: object = None,
        observed: object = None,
        error: float = 0.0,
    ) -> None:
        self.checked[check_id].append(record_id)
        self.maximum_error[check_id] = max(self.maximum_error.get(check_id, 0.0), error)
        if not passed:
            self.failures[check_id].append(
                {
                    "record_id": record_id,
                    "expected": expected,
                    "observed": observed,
                    "absolute_error": error,
                }
            )

    def case_passed(self, record_ids: Iterable[str]) -> bool:
        relevant = set(record_ids)
        return not any(
            failure["record_id"] in relevant
            for failures in self.failures.values()
            for failure in failures
        )

    def to_dict(self, *, source_checks: JsonObject) -> JsonObject:
        checks = []
        for check_id in sorted(self.checked):
            failures = self.failures.get(check_id, [])
            checks.append(
                {
                    "check_id": check_id,
                    "status": "PASS" if not failures else "FAIL",
                    "checked_record_count": len(self.checked[check_id]),
                    "checked_record_ids": sorted(self.checked[check_id]),
                    "failure_count": len(failures),
                    "failures": failures,
                    "maximum_absolute_error": self.maximum_error.get(check_id, 0.0),
                }
            )
        source_passed = (
            bool(source_checks.get("all_frozen_source_hashes_match"))
            and bool(source_checks.get("all_frozen_design_hashes_match"))
            and bool(source_checks.get("no_embedded_fixed_sigma_in_scoring_paths"))
        )
        return {
            "audit_version": AUDIT_VERSION,
            "overall_status": (
                "PASS" if source_passed and all(not item["failures"] for item in checks) else "FAIL"
            ),
            "checks": checks,
            "source_checks": source_checks,
        }


@dataclass(slots=True)
class AccessLedger:
    """Record and enforce the two-pass artifact access boundary."""

    pass_a_files: list[str] = field(default_factory=list)
    pass_b_files: list[str] = field(default_factory=list)
    pass_a_closed: bool = False
    pass_a_staging_sha256: str | None = None

    def record(self, path: Path, *, stage: Literal["A", "B"]) -> None:
        name = path.name
        if name in FORBIDDEN_INPUT_FILENAMES:
            raise DivergenceAuditError(f"Forbidden audit input access attempted: {name}")
        if stage == "A":
            if self.pass_a_closed:
                raise DivergenceAuditError("Pass A input was accessed after classification closed.")
            if name not in PASS_A_FILENAMES:
                raise DivergenceAuditError(f"File is not allowed during Pass A: {name}")
            self.pass_a_files.append(name)
        else:
            if not self.pass_a_closed or self.pass_a_staging_sha256 is None:
                raise DivergenceAuditError(
                    "Evaluator fields cannot be opened before Pass A closes."
                )
            if name not in PASS_B_FILENAMES:
                raise DivergenceAuditError(f"File is not allowed during Pass B: {name}")
            self.pass_b_files.append(name)

    def close_pass_a(self, staging_sha256: str) -> None:
        if self.pass_a_closed:
            raise DivergenceAuditError("Pass A was closed more than once.")
        self.pass_a_closed = True
        self.pass_a_staging_sha256 = staging_sha256


@dataclass(frozen=True, slots=True)
class DivergenceAuditResult:
    """Complete frozen audit ready for versioned artifact serialization."""

    input_directory: Path
    repository_root: Path
    generated_at: str
    bootstrap_resamples: int
    cases: tuple[AuditedDivergenceCase, ...]
    mechanism_summary_rows: tuple[JsonObject, ...]
    mechanism_condition_rows: tuple[JsonObject, ...]
    score_rows: tuple[JsonObject, ...]
    sequence_rows: tuple[JsonObject, ...]
    harm_rows: tuple[JsonObject, ...]
    compatibility: JsonObject
    audit_checks: JsonObject
    recommendation: str
    source_artifact_hashes: tuple[tuple[str, str], ...]
    design_hashes: tuple[tuple[str, str], ...]
    access_ledger: JsonObject
    staging_sha256: str
    extracted_truth_free_sha256: str


class ReadOnlyScoringAdapter:
    """Reconstruct recorded scores without an oracle, outcome API, or persistence."""

    __slots__ = ("_candidates", "_completed", "_eligibility", "_max_cost")

    def __init__(
        self,
        *,
        candidates: tuple[CandidateRecord, ...],
        completed_experiments: tuple[CompletedExperiment, ...],
        max_cost: float,
    ) -> None:
        if not math.isfinite(max_cost) or max_cost < 0.0:
            raise DivergenceAuditError("Recorded remaining budget must be finite and non-negative.")
        self._candidates = candidates
        self._completed = completed_experiments
        self._max_cost = max_cost
        self._eligibility = OptimizerEvidenceEligibilityContract.from_candidates(
            (item.candidate for item in candidates),
            public_designs=(item.public_design for item in candidates),
        )

    def replay(
        self,
        *,
        context: Literal["FF", "CF", "FC", "CC"],
        hypothesis_ids: tuple[str, ...],
        posterior_probabilities: tuple[float, ...],
        snapshots: tuple[RecordedPredictionSnapshot, ...],
    ) -> ContextReplay:
        if len(hypothesis_ids) != len(posterior_probabilities):
            raise DivergenceAuditError("Replay posterior does not match hypotheses.")
        _validate_probabilities(posterior_probabilities, "replay posterior")
        snapshot_by_group = {item.comparison_group_id: item for item in snapshots}
        plans: list[CandidatePlanScore] = []
        completed_ids = {item.candidate.candidate_id for item in self._completed}
        for record in sorted(self._candidates, key=lambda item: item.candidate.candidate_id):
            candidate = record.candidate
            if candidate.candidate_id in completed_ids or record.cost > self._max_cost:
                continue
            assessment = self._eligibility.assess_candidate(candidate, self._completed)
            if assessment.effect in {
                "completed_candidate",
                "duplicate_arm",
                "already_completed_pair",
                "ambiguous_counterpart",
            }:
                continue
            plans.append(
                self._score_first_action(
                    record=record,
                    action_effect=assessment.effect,
                    hypothesis_ids=hypothesis_ids,
                    posterior_probabilities=posterior_probabilities,
                    snapshot_by_group=snapshot_by_group,
                )
            )
        if not plans:
            raise DivergenceAuditError("No feasible recorded candidate can be replayed.")
        ranked = tuple(sorted(plans, key=CandidatePlanScore.sort_key))
        return ContextReplay(
            context=context,
            hypothesis_ids=hypothesis_ids,
            posterior_probabilities=posterior_probabilities,
            sigma_by_group=tuple(
                sorted((group, item.estimated_sigma) for group, item in snapshot_by_group.items())
            ),
            ranked_plans=ranked,
        )

    def _score_first_action(
        self,
        *,
        record: CandidateRecord,
        action_effect: str,
        hypothesis_ids: tuple[str, ...],
        posterior_probabilities: tuple[float, ...],
        snapshot_by_group: Mapping[str, RecordedPredictionSnapshot],
    ) -> CandidatePlanScore:
        simulated = CompletedExperiment(
            record_id=0,
            candidate=record.candidate,
            observed_value=0.0,
            created_at="SIMULATED-NOT-PERSISTED",
        )
        completed_after_first = (*self._completed, simulated)
        if action_effect == "completes_pair":
            snapshot = _required_snapshot(
                snapshot_by_group, record.public_design.comparison_group_id
            )
            hypotheses = _hypotheses_from_snapshot(snapshot)
            distribution = discretized_gaussian_evidence_outcomes(
                hypotheses,
                posterior_probabilities,
            )
            immediate = distribution.expected_information_gain
            outcomes = tuple(
                (
                    item.branch_id,
                    item.predictive_probability,
                    item.posterior_probabilities,
                    item.posterior_entropy,
                )
                for item in distribution.branches
            )
        else:
            immediate = 0.0
            outcomes = (
                (
                    "no-evidence-yet",
                    1.0,
                    posterior_probabilities,
                    _entropy(posterior_probabilities),
                ),
            )
        branches = tuple(
            self._score_branch(
                branch_id=branch_id,
                probability=probability,
                posterior_probabilities=branch_posterior,
                posterior_entropy=posterior_entropy,
                first_cost=record.cost,
                completed_after_first=completed_after_first,
                snapshot_by_group=snapshot_by_group,
            )
            for branch_id, probability, branch_posterior, posterior_entropy in outcomes
        )
        if any(not item.budget_feasible for item in branches):
            raise DivergenceAuditError("Read-only replay exceeded a recorded hard budget.")
        prior_entropy = _entropy(posterior_probabilities)
        expected_terminal_entropy = math.fsum(
            item.probability * item.terminal_entropy for item in branches
        )
        total_information_gain = max(0.0, prior_entropy - expected_terminal_entropy)
        expected_cost = math.fsum(item.probability * item.branch_total_cost for item in branches)
        ratio = 0.0 if expected_cost <= 0.0 else total_information_gain / expected_cost
        return CandidatePlanScore(
            candidate_id=record.candidate.candidate_id,
            action_effect=action_effect,
            comparison_group_id=record.public_design.comparison_group_id,
            first_cost=record.cost,
            prior_entropy=prior_entropy,
            immediate_information_gain=immediate,
            delayed_information_gain=max(0.0, total_information_gain - immediate),
            expected_terminal_entropy=expected_terminal_entropy,
            expected_total_information_gain=total_information_gain,
            expected_total_cost=expected_cost,
            information_gain_per_expected_cost=ratio,
            branches=branches,
        )

    def _score_branch(
        self,
        *,
        branch_id: str,
        probability: float,
        posterior_probabilities: tuple[float, ...],
        posterior_entropy: float,
        first_cost: float,
        completed_after_first: tuple[CompletedExperiment, ...],
        snapshot_by_group: Mapping[str, RecordedPredictionSnapshot],
    ) -> BranchScore:
        choices: list[tuple[float, float, float, str, str]] = [(0.0, 0.0, 0.0, "STOP", "stop")]
        completed_ids = {item.candidate.candidate_id for item in completed_after_first}
        remaining = self._max_cost - first_cost
        for record in sorted(self._candidates, key=lambda item: item.candidate.candidate_id):
            candidate = record.candidate
            if (
                candidate.candidate_id in completed_ids
                or record.cost > remaining + NUMERICAL_TOLERANCE
            ):
                continue
            assessment = self._eligibility.assess_candidate(candidate, completed_after_first)
            if assessment.effect != "completes_pair":
                continue
            snapshot = _required_snapshot(
                snapshot_by_group, record.public_design.comparison_group_id
            )
            distribution = discretized_gaussian_evidence_outcomes(
                _hypotheses_from_snapshot(snapshot),
                posterior_probabilities,
            )
            information_gain = distribution.expected_information_gain
            ratio = 0.0 if record.cost <= 0.0 else information_gain / record.cost
            choices.append(
                (information_gain, record.cost, ratio, candidate.candidate_id, assessment.effect)
            )
        best = sorted(choices, key=lambda item: (-item[0], item[1], -item[2], item[3]))[0]
        second_information, second_cost, _, second_id, second_effect = best
        terminal_entropy = max(0.0, posterior_entropy - second_information)
        branch_total_cost = first_cost + second_cost
        return BranchScore(
            branch_id=branch_id,
            probability=probability,
            posterior_probabilities=posterior_probabilities,
            posterior_entropy=posterior_entropy,
            second_candidate_id=second_id,
            second_action_effect=second_effect,
            second_information_gain=second_information,
            second_cost=second_cost,
            terminal_entropy=terminal_entropy,
            branch_total_cost=branch_total_cost,
            budget_feasible=branch_total_cost <= self._max_cost + NUMERICAL_TOLERANCE,
        )


def _hypotheses_from_snapshot(
    snapshot: RecordedPredictionSnapshot,
) -> tuple[Hypothesis, ...]:
    means = dict(snapshot.means)
    sigmas = dict(snapshot.standard_deviations)
    base = {item.hypothesis_id: item for item in optimizer_effect_hypotheses()}
    return tuple(
        Hypothesis(
            hypothesis_id=hypothesis_id,
            statement=base[hypothesis_id].statement,
            prior_probability=base[hypothesis_id].prior_probability,
            prediction_model=GaussianEvidencePrediction(
                mean=means[hypothesis_id],
                standard_deviation=sigmas[hypothesis_id],
                model_version=f"{SCORING_ADAPTER_VERSION}/recorded-prediction",
            ),
        )
        for hypothesis_id in sorted(means)
    )


def _required_snapshot(
    snapshots: Mapping[str, RecordedPredictionSnapshot], group_id: str
) -> RecordedPredictionSnapshot:
    try:
        return snapshots[group_id]
    except KeyError as error:
        raise DivergenceAuditError(
            f"Recorded matched comparison group has no prediction snapshot: {group_id}"
        ) from error


def _mapping(value: object, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise DivergenceAuditError(f"{label} must be an object.")
    return cast(JsonObject, value)


def _sequence(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise DivergenceAuditError(f"{label} must be a list.")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise DivergenceAuditError(f"{label} must be a non-empty string.")
    return value


def _number(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise DivergenceAuditError(f"{label} must be numeric.")
    result = float(value)
    if not math.isfinite(result):
        raise DivergenceAuditError(f"{label} must be finite.")
    return result


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise DivergenceAuditError(f"{label} must be an integer.")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise DivergenceAuditError(f"{label} must be Boolean.")
    return value


def _entropy(probabilities: tuple[float, ...]) -> float:
    return -math.fsum(value * math.log2(value) for value in probabilities if value > 0.0)


def _validate_probabilities(probabilities: tuple[float, ...], label: str) -> None:
    if any(not math.isfinite(value) or value < 0.0 for value in probabilities):
        raise DivergenceAuditError(f"{label} contains an invalid probability.")
    if not math.isclose(math.fsum(probabilities), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise DivergenceAuditError(f"{label} must sum to one.")


def _stable_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _stable_id(prefix: str, payload: object, length: int = 24) -> str:
    return f"{prefix}-{_stable_hash(payload)[:length]}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_line(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


@dataclass(slots=True)
class _CatalogBuilder:
    candidate: Candidate
    cost: float
    public_design: PublicExperimentDesign | None


@dataclass(slots=True)
class _RunSummary:
    run_id: str
    world_id: str
    seed: int
    budget_label: str
    policy: str
    belief_model_id: str
    arm_id: str
    selected_by_step: dict[int, str] = field(default_factory=dict)

    @property
    def sequence(self) -> tuple[str, ...]:
        return tuple(self.selected_by_step[step] for step in sorted(self.selected_by_step))


@dataclass(frozen=True, slots=True)
class _AuditWorkspace:
    input_directory: Path
    manifest: JsonObject
    protocol: JsonObject
    pairs: tuple[DivergencePair, ...]
    decisions_by_run: Mapping[str, tuple[JsonObject, ...]]
    evidence_by_run: Mapping[str, JsonObject]
    catalog_by_world: Mapping[str, tuple[CandidateRecord, ...]]
    commitments: Mapping[tuple[str, int], JsonObject]
    calibration_effects: Mapping[str, JsonObject]
    compatibility: CompatibilityAccumulator
    source_checks: JsonObject
    source_artifact_hashes: tuple[tuple[str, str], ...]
    source_artifact_stats: tuple[tuple[str, int, int], ...]
    design_hashes: tuple[tuple[str, str], ...]
    ledger: AccessLedger


class _ArtifactReader:
    def __init__(self, root: Path, ledger: AccessLedger) -> None:
        self.root = root
        self.ledger = ledger

    def read_json(self, name: str, *, stage: Literal["A", "B"]) -> JsonObject:
        path = self.root / name
        self.ledger.record(path, stage=stage)
        with path.open(encoding="utf-8") as stream:
            return _mapping(json.load(stream), name)

    def iter_jsonl(self, name: str, *, stage: Literal["A", "B"]) -> Iterator[JsonObject]:
        path = self.root / name
        self.ledger.record(path, stage=stage)
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                try:
                    yield _mapping(json.loads(line), f"{name}:{line_number}")
                except json.JSONDecodeError as error:
                    raise DivergenceAuditError(
                        f"Invalid JSON in {name} at line {line_number}."
                    ) from error


def _candidate_from_json(payload: Mapping[str, Any]) -> Candidate:
    params = _mapping(payload["params"], "candidate parameters")
    return Candidate(
        candidate_id=_text(payload["candidate_id"], "candidate ID"),
        learning_rate=_number(params["learning_rate"], "learning rate"),
        regularization=_number(params["regularization"], "regularization"),
        model_width=_integer(params["model_width"], "model width"),
        optimizer=_text(params["optimizer"], "optimizer"),
    )


def _public_design_from_json(payload: Mapping[str, Any]) -> PublicExperimentDesign:
    controls = _mapping(payload["controlled_variables"], "controlled variables")
    return PublicExperimentDesign(
        candidate_id=_text(payload["candidate_id"], "public-design candidate ID"),
        experiment_family=_text(payload["experiment_family"], "experiment family"),
        comparison_group_id=_text(payload["comparison_group_id"], "comparison group ID"),
        controlled_variables=tuple(
            sorted((name, cast(str | int | float, value)) for name, value in controls.items())
        ),
        intervention_variable=_text(payload["intervention_variable"], "intervention variable"),
        intervention_arm=_text(payload["intervention_arm"], "intervention arm"),
    )


def _selected_catalog_item(
    row: Mapping[str, Any],
) -> tuple[Candidate, float, PublicExperimentDesign | None]:
    trace = _mapping(row["policy_trace"], "policy trace")
    policy = _text(row["policy"], "policy")
    if policy == "lookahead_information_gain":
        selected = _mapping(trace["selected_first_experiment"], "selected first experiment")
        candidate = _candidate_from_json(_mapping(selected["candidate"], "selected candidate"))
        design = _public_design_from_json(
            _mapping(selected["public_design"], "selected public design")
        )
        return candidate, _number(selected["first_action_cost"], "first action cost"), design
    if policy == "information_gain":
        selected = _mapping(trace["selected"], "selected candidate score")
        candidate = _candidate_from_json(selected)
        return candidate, _number(selected["estimated_cost"], "estimated cost"), None
    raise DivergenceAuditError(f"Unexpected frozen belief-aware policy: {policy}")


def _merge_catalog_item(
    catalog: dict[str, dict[str, _CatalogBuilder]],
    *,
    world_id: str,
    candidate: Candidate,
    cost: float,
    design: PublicExperimentDesign | None,
) -> None:
    world = catalog.setdefault(world_id, {})
    existing = world.get(candidate.candidate_id)
    if existing is None:
        world[candidate.candidate_id] = _CatalogBuilder(candidate, cost, design)
        return
    if existing.candidate != candidate or not math.isclose(
        existing.cost, cost, rel_tol=0.0, abs_tol=NUMERICAL_TOLERANCE
    ):
        raise DivergenceAuditError(
            f"Candidate catalog changed within world {world_id}: {candidate.candidate_id}"
        )
    if design is not None:
        if existing.public_design is not None and existing.public_design != design:
            raise DivergenceAuditError(
                f"Public candidate design changed within world {world_id}: {candidate.candidate_id}"
            )
        existing.public_design = design


def _finalize_catalog(
    builders: Mapping[str, Mapping[str, _CatalogBuilder]],
) -> dict[str, tuple[CandidateRecord, ...]]:
    result: dict[str, tuple[CandidateRecord, ...]] = {}
    for world_id, items in builders.items():
        records = []
        for candidate_id in sorted(items):
            item = items[candidate_id]
            design = item.public_design or default_public_design(item.candidate)
            records.append(CandidateRecord(item.candidate, item.cost, design))
        result[world_id] = tuple(records)
    return result


def _discover_pairs(
    summaries: Mapping[str, _RunSummary],
    *,
    expected_count: int,
) -> tuple[DivergencePair, ...]:
    by_condition: dict[tuple[str, int, str, str], dict[str, _RunSummary]] = defaultdict(dict)
    for item in summaries.values():
        key = (item.world_id, item.seed, item.budget_label, item.policy)
        if item.belief_model_id in by_condition[key]:
            raise DivergenceAuditError(f"Duplicate arm in frozen condition: {key}")
        by_condition[key][item.belief_model_id] = item
    pairs: list[DivergencePair] = []
    for (world_id, seed, budget_label, policy), arms in sorted(by_condition.items()):
        if set(arms) != {FIXED_SIGMA_MODEL_ID, CALIBRATED_SIGMA_MODEL_ID}:
            raise DivergenceAuditError(
                f"Frozen condition lacks exactly the two belief models: "
                f"{world_id}/{seed}/{budget_label}/{policy}"
            )
        fixed = arms[FIXED_SIGMA_MODEL_ID]
        calibrated = arms[CALIBRATED_SIGMA_MODEL_ID]
        fixed_sequence = fixed.sequence
        calibrated_sequence = calibrated.sequence
        common_prefix = 0
        for left, right in zip(fixed_sequence, calibrated_sequence, strict=False):
            if left != right:
                break
            common_prefix += 1
        if common_prefix == max(len(fixed_sequence), len(calibrated_sequence)):
            continue
        first_step = common_prefix + 1
        divergence_id = _stable_id(
            "divergence",
            {
                "budget_label": budget_label,
                "calibrated_run_id": calibrated.run_id,
                "fixed_run_id": fixed.run_id,
                "policy": policy,
                "seed": seed,
                "world_id": world_id,
            },
        )
        case_id = _stable_id(
            "divergence-case",
            {
                "audit_version": AUDIT_VERSION,
                "calibrated_run_id": calibrated.run_id,
                "divergence_id": divergence_id,
                "fixed_run_id": fixed.run_id,
            },
        )
        pairs.append(
            DivergencePair(
                divergence_id=divergence_id,
                case_id=case_id,
                world_id=world_id,
                seed=seed,
                budget_label=budget_label,
                policy=policy,
                fixed_run_id=fixed.run_id,
                calibrated_run_id=calibrated.run_id,
                common_prefix_length=common_prefix,
                first_divergence_step=first_step,
                fixed_sequence=fixed_sequence,
                calibrated_sequence=calibrated_sequence,
            )
        )
    if len(pairs) != expected_count:
        raise DivergenceAuditError(
            f"Frozen divergence population mismatch: expected {expected_count}, found {len(pairs)}."
        )
    return tuple(pairs)


def discover_divergence_pairs_from_rows(
    rows: Iterable[Mapping[str, Any]], *, expected_count: int
) -> tuple[DivergencePair, ...]:
    """Discover divergent pairs from truth-free decision rows for focused tests."""

    summaries: dict[str, _RunSummary] = {}
    for row in rows:
        run_id = _text(row["run_id"], "run ID")
        summary = summaries.setdefault(
            run_id,
            _RunSummary(
                run_id=run_id,
                world_id=_text(row["world_id"], "world ID"),
                seed=_integer(row["evaluation_seed"], "evaluation seed"),
                budget_label=_text(row["budget_label"], "budget label"),
                policy=_text(row["policy"], "policy"),
                belief_model_id=_text(row["belief_model_id"], "belief model ID"),
                arm_id=_text(row["arm_id"], "arm ID"),
            ),
        )
        step = _integer(row["step"], "decision step")
        candidate_id = _text(row["selected_candidate_id"], "selected candidate ID")
        if step in summary.selected_by_step:
            raise DivergenceAuditError(f"Duplicate decision step in run {run_id}: {step}")
        summary.selected_by_step[step] = candidate_id
    return _discover_pairs(summaries, expected_count=expected_count)


def _belief_state_for_information_trace(trace: Mapping[str, Any]) -> BeliefState:
    contexts = _sequence(trace["hypotheses"], "hypothesis contexts")
    ordered = sorted(
        (_mapping(item, "hypothesis context") for item in contexts),
        key=lambda item: _text(item["hypothesis_id"], "hypothesis ID"),
    )
    hypothesis_ids = tuple(_text(item["hypothesis_id"], "hypothesis ID") for item in ordered)
    posterior = tuple(
        _number(item["posterior_probability"], "posterior probability") for item in ordered
    )
    _validate_probabilities(posterior, "information-gain posterior")
    priors_by_id = {
        item.hypothesis_id: item.prior_probability for item in optimizer_effect_hypotheses()
    }
    return BeliefState(
        belief_state_id=_text(trace["belief_state_id"], "belief state ID"),
        hypothesis_ids=hypothesis_ids,
        prior_probabilities=tuple(priors_by_id[item] for item in hypothesis_ids),
        posterior_probabilities=posterior,
        evidence_ids=(),
        sequence=0,
        created_at="RECORDED-READ-ONLY",
    )


def _check_information_trace(
    row: Mapping[str, Any],
    catalog: tuple[CandidateRecord, ...],
    compatibility: CompatibilityAccumulator,
) -> None:
    record_id = _text(row["decision_trace_id"], "decision trace ID")
    trace = _mapping(row["policy_trace"], "policy trace")
    model_id = _text(row["belief_model_id"], "belief model ID")
    lineage_id = _text(row["lineage_id"], "lineage ID")
    belief_state_id = _text(row["belief_state_id"], "belief state ID")
    snapshots = tuple(
        RecordedPredictionSnapshot.from_json(_mapping(item, "prediction snapshot"))
        for item in _sequence(row["prediction_snapshots"], "prediction snapshots")
    )
    lineage_ok = all(
        item.belief_model_id == model_id
        and item.lineage_id == lineage_id
        and item.belief_state_id == belief_state_id
        for item in snapshots
    )
    compatibility.record("lineage_identity", record_id, lineage_ok)
    sigma_ok = all(
        all(
            math.isclose(value, item.estimated_sigma, rel_tol=0.0, abs_tol=NUMERICAL_TOLERANCE)
            for _, value in item.standard_deviations
        )
        for item in snapshots
    )
    compatibility.record("prediction_bundle_sigma", record_id, sigma_ok)
    state = _belief_state_for_information_trace(trace)
    estimates = {
        item.comparison_group_id: expected_information_gain(_hypotheses_from_snapshot(item), state)
        for item in snapshots
    }
    canonical = expected_information_gain(_hypotheses_from_snapshot(snapshots[0]), state)
    catalog_by_id = {item.candidate.candidate_id: item for item in catalog}
    scores = tuple(
        _mapping(item, "ranked candidate score")
        for item in _sequence(trace["ranked_candidates"], "ranked candidates")
    )
    max_error = 0.0
    scores_ok = True
    for score in scores:
        candidate_id = _text(score["candidate_id"], "scored candidate ID")
        candidate = catalog_by_id[candidate_id]
        estimate = estimates.get(candidate.public_design.comparison_group_id, canonical)
        completes = _boolean(score["completes_matched_pair"], "completes pair")
        expected_ig = estimate.expected_information_gain if completes else 0.0
        expected_entropy = (
            estimate.expected_posterior_entropy if completes else estimate.prior_entropy
        )
        errors = (
            abs(_number(score["expected_information_gain"], "recorded EIG") - expected_ig),
            abs(
                _number(score["expected_posterior_entropy"], "recorded entropy") - expected_entropy
            ),
            abs(_number(score["prior_entropy"], "recorded prior entropy") - estimate.prior_entropy),
        )
        max_error = max(max_error, *errors)
        scores_ok = scores_ok and max(errors) <= NUMERICAL_TOLERANCE
    compatibility.record(
        "one_step_scoring",
        record_id,
        scores_ok,
        error=max_error,
        expected="active model EIG for every recorded candidate",
        observed="recorded candidate scores",
    )
    expected_order = tuple(
        _text(item["candidate_id"], "candidate ID")
        for item in sorted(
            scores,
            key=lambda item: (
                -_number(item["expected_information_gain"], "candidate EIG"),
                _number(item["estimated_cost"], "candidate cost"),
                _text(item["candidate_id"], "candidate ID"),
            ),
        )
    )
    recorded_order = tuple(_text(item["candidate_id"], "candidate ID") for item in scores)
    compatibility.record(
        "ranking_and_explanation",
        record_id,
        expected_order == recorded_order
        and _text(row["selected_candidate_id"], "selected candidate") == expected_order[0],
        expected=expected_order,
        observed=recorded_order,
    )


def _source_and_design_checks(
    *, repository_root: Path, protocol: Mapping[str, Any]
) -> tuple[JsonObject, tuple[tuple[str, str], ...]]:
    source_expected = _mapping(protocol["source_sha256"], "frozen source hashes")
    source_rows: list[JsonObject] = []
    for relative_path, expected_hash in sorted(source_expected.items()):
        path = repository_root / relative_path
        actual = _sha256(path)
        source_rows.append(
            {
                "path": relative_path,
                "expected_sha256": _text(expected_hash, "expected source hash"),
                "actual_sha256": actual,
                "passed": actual == expected_hash,
            }
        )
    closed_loop_path = repository_root / "research_decision_engine" / "closed_loop.py"
    tree = ast.parse(closed_loop_path.read_text(encoding="utf-8"))
    scored_functions = {
        "decide_information_gain_with_adapter",
        "decide_lookahead_with_adapter",
        "_plan_first_action_with_adapter",
        "_plan_branch_with_adapter",
        "_best_second_action_with_adapter",
    }
    embedded_fixed_sigma: list[str] = []
    for node in tree.body:
        if (
            isinstance(node, ast.FunctionDef)
            and node.name in scored_functions
            and any(
                isinstance(child, ast.Name) and child.id == "FIXED_SIGMA"
                for child in ast.walk(node)
            )
        ):
            embedded_fixed_sigma.append(node.name)
    checks: JsonObject = {
        "frozen_source_hashes": source_rows,
        "all_frozen_source_hashes_match": all(item["passed"] for item in source_rows),
        "scored_function_names": sorted(scored_functions),
        "embedded_fixed_sigma_functions": embedded_fixed_sigma,
        "no_embedded_fixed_sigma_in_scoring_paths": not embedded_fixed_sigma,
        "closed_loop_source_sha256": _sha256(closed_loop_path),
    }
    design_expected = _mapping(protocol["design_sha256"], "frozen design hashes")
    design_hashes = tuple(
        (name, _sha256(repository_root / name)) for name in sorted(design_expected)
    )
    design_rows: list[JsonObject] = [
        {
            "path": name,
            "expected_sha256": design_expected[name],
            "actual_sha256": actual,
            "passed": actual == design_expected[name],
        }
        for name, actual in design_hashes
    ]
    checks["frozen_design_hashes"] = design_rows
    checks["all_frozen_design_hashes_match"] = all(item["passed"] for item in design_rows)
    return checks, design_hashes


def _snapshot_source_artifacts(
    root: Path, manifest: Mapping[str, Any]
) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, int, int], ...]]:
    declared = _mapping(manifest["output_sha256"], "source artifact hashes")
    hashes: list[tuple[str, str]] = []
    stats: list[tuple[str, int, int]] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if not path.is_file():
            continue
        stat = path.stat()
        stats.append((path.name, stat.st_size, stat.st_mtime_ns))
        if path.name in FORBIDDEN_INPUT_FILENAMES:
            continue
        if path.name in declared:
            actual = _sha256(path)
            if actual != declared[path.name]:
                raise DivergenceAuditError(f"Source artifact hash mismatch: {path.name}")
            hashes.append((path.name, actual))
    return tuple(hashes), tuple(stats)


def _load_workspace(
    *,
    input_directory: Path,
    repository_root: Path,
    expected_population: int,
) -> _AuditWorkspace:
    ledger = AccessLedger()
    reader = _ArtifactReader(input_directory, ledger)
    manifest = reader.read_json("run_manifest.json", stage="A")
    protocol = reader.read_json("protocol_snapshot.json", stage="A")
    if _text(manifest["evaluation_version"], "evaluation version") != (
        "closed-loop-belief-control-evaluation/v1"
    ):
        raise DivergenceAuditError("Unexpected closed-loop evaluation version.")
    source_artifact_hashes, source_artifact_stats = _snapshot_source_artifacts(
        input_directory, manifest
    )
    source_checks, design_hashes = _source_and_design_checks(
        repository_root=repository_root,
        protocol=protocol,
    )

    run_summaries: dict[str, _RunSummary] = {}
    catalog_builders: dict[str, dict[str, _CatalogBuilder]] = {}
    for row in reader.iter_jsonl("decision_traces.jsonl", stage="A"):
        run_id = _text(row["run_id"], "run ID")
        world_id = _text(row["world_id"], "world ID")
        summary = run_summaries.setdefault(
            run_id,
            _RunSummary(
                run_id=run_id,
                world_id=world_id,
                seed=_integer(row["evaluation_seed"], "evaluation seed"),
                budget_label=_text(row["budget_label"], "budget label"),
                policy=_text(row["policy"], "policy"),
                belief_model_id=_text(row["belief_model_id"], "belief model ID"),
                arm_id=_text(row["arm_id"], "arm ID"),
            ),
        )
        step = _integer(row["step"], "step")
        if step in summary.selected_by_step:
            raise DivergenceAuditError(f"Duplicate decision step for run {run_id}: {step}")
        summary.selected_by_step[step] = _text(
            row["selected_candidate_id"], "selected candidate ID"
        )
        candidate, cost, design = _selected_catalog_item(row)
        _merge_catalog_item(
            catalog_builders,
            world_id=world_id,
            candidate=candidate,
            cost=cost,
            design=design,
        )
    if len(run_summaries) != 3_200:
        raise DivergenceAuditError(f"Expected 3,200 closed-loop runs, found {len(run_summaries)}.")
    pairs = _discover_pairs(run_summaries, expected_count=expected_population)
    catalog_by_world = _finalize_catalog(catalog_builders)
    relevant_run_ids = {
        run_id for pair in pairs for run_id in (pair.fixed_run_id, pair.calibrated_run_id)
    }

    compatibility = CompatibilityAccumulator()
    decision_rows: dict[str, list[JsonObject]] = defaultdict(list)
    for row in reader.iter_jsonl("decision_traces.jsonl", stage="A"):
        world_id = _text(row["world_id"], "world ID")
        if _text(row["policy"], "policy") == "information_gain":
            _check_information_trace(row, catalog_by_world[world_id], compatibility)
        run_id = _text(row["run_id"], "run ID")
        if run_id in relevant_run_ids:
            decision_rows[run_id].append(row)
    ordered_decisions = {
        run_id: tuple(sorted(rows, key=lambda row: _integer(row["step"], "step")))
        for run_id, rows in decision_rows.items()
    }

    evidence_by_run: dict[str, JsonObject] = {}
    for row in reader.iter_jsonl("evidence_belief_traces.jsonl", stage="A"):
        run_id = _text(row["run_id"], "run ID")
        if run_id in relevant_run_ids:
            evidence_by_run[run_id] = row
    if set(evidence_by_run) != relevant_run_ids:
        raise DivergenceAuditError("Missing evidence trace for one or more divergent arms.")

    commitments: dict[tuple[str, int], JsonObject] = {}
    for row in reader.iter_jsonl("potential_outcome_commitments.jsonl", stage="A"):
        key = (
            _text(row["world_id"], "commitment world ID"),
            _integer(row["evaluation_seed"], "commitment seed"),
        )
        commitments[key] = row

    calibration_effects: dict[str, JsonObject] = {}
    for row in reader.iter_jsonl("calibration_prefixes.jsonl", stage="A"):
        for effect_value in _sequence(row["matched_effects"], "calibration matched effects"):
            effect = _mapping(effect_value, "calibration matched effect")
            calibration_effects[_text(effect["calibration_effect_id"], "calibration effect ID")] = (
                effect
            )

    return _AuditWorkspace(
        input_directory=input_directory,
        manifest=manifest,
        protocol=protocol,
        pairs=pairs,
        decisions_by_run=ordered_decisions,
        evidence_by_run=evidence_by_run,
        catalog_by_world=catalog_by_world,
        commitments=commitments,
        calibration_effects=calibration_effects,
        compatibility=compatibility,
        source_checks=source_checks,
        source_artifact_hashes=source_artifact_hashes,
        source_artifact_stats=source_artifact_stats,
        design_hashes=design_hashes,
        ledger=ledger,
    )


def _candidate_lookup(catalog: Sequence[CandidateRecord]) -> dict[str, CandidateRecord]:
    return {item.candidate.candidate_id: item for item in catalog}


def _completed_before_step(
    evidence_trace: Mapping[str, Any],
    catalog: Sequence[CandidateRecord],
    step: int,
) -> tuple[CompletedExperiment, ...]:
    lookup = _candidate_lookup(catalog)
    completed = []
    for value in _sequence(evidence_trace["experiments"], "experiments"):
        experiment = _mapping(value, "experiment")
        experiment_step = _integer(experiment["step"], "experiment step")
        if experiment_step >= step:
            continue
        candidate_id = _text(experiment["candidate_id"], "experiment candidate ID")
        completed.append(
            CompletedExperiment(
                record_id=_integer(experiment["experiment_id"], "experiment ID"),
                candidate=lookup[candidate_id].candidate,
                observed_value=_number(experiment["observed_value"], "observed value"),
                created_at=_text(experiment["created_at"], "experiment creation time"),
            )
        )
    return tuple(sorted(completed, key=lambda item: item.record_id))


def _lookahead_posterior(row: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[float, ...]]:
    trace = _mapping(row["policy_trace"], "lookahead policy trace")
    probabilities = _mapping(
        trace["current_hypothesis_probabilities"], "current hypothesis probabilities"
    )
    hypothesis_ids = tuple(sorted(probabilities))
    posterior = tuple(
        _number(probabilities[item], "posterior probability") for item in hypothesis_ids
    )
    _validate_probabilities(posterior, "lookahead posterior")
    return hypothesis_ids, posterior


def _recorded_snapshots(row: Mapping[str, Any]) -> tuple[RecordedPredictionSnapshot, ...]:
    return tuple(
        sorted(
            (
                RecordedPredictionSnapshot.from_json(_mapping(item, "prediction snapshot"))
                for item in _sequence(row["prediction_snapshots"], "prediction snapshots")
            ),
            key=lambda item: item.comparison_group_id,
        )
    )


def _stored_lookahead_scores(row: Mapping[str, Any]) -> dict[str, JsonObject]:
    trace = _mapping(row["policy_trace"], "lookahead policy trace")
    selected = _mapping(trace["selected_first_experiment"], "selected first experiment")
    selected_candidate = _mapping(selected["candidate"], "selected candidate")
    result = {
        _text(selected_candidate["candidate_id"], "selected candidate ID"): {
            "immediate_information_gain": selected["immediate_information_gain"],
            "expected_total_information_gain": selected["expected_total_information_gain"],
            "expected_total_cost": selected["expected_total_cost"],
            "information_gain_per_expected_cost": selected["information_gain_per_expected_cost"],
            "action_effect": selected["action_effect"],
        }
    }
    for value in _sequence(
        trace["losing_first_action_alternatives"], "losing first-action alternatives"
    ):
        alternative = _mapping(value, "losing first-action alternative")
        candidate = _mapping(alternative["candidate"], "alternative candidate")
        result[_text(candidate["candidate_id"], "alternative candidate ID")] = alternative
    return result


def _check_sigma_provenance(
    *,
    row: Mapping[str, Any],
    evidence_trace: Mapping[str, Any],
    calibration_effects: Mapping[str, JsonObject],
    compatibility: CompatibilityAccumulator,
) -> None:
    record_id = _text(row["decision_trace_id"], "decision trace ID")
    model_id = _text(row["belief_model_id"], "belief model ID")
    history = {
        _text(item["effect_id"], "matched-effect ID"): item
        for value in _sequence(evidence_trace["matched_effect_history"], "matched-effect history")
        for item in (_mapping(value, "matched-effect observation"),)
    }
    all_ok = True
    max_error = 0.0
    for snapshot in _recorded_snapshots(row):
        predictions_ok = all(
            math.isclose(
                sigma,
                snapshot.estimated_sigma,
                rel_tol=0.0,
                abs_tol=NUMERICAL_TOLERANCE,
            )
            for _, sigma in snapshot.standard_deviations
        )
        all_ok = all_ok and predictions_ok
        if model_id == FIXED_SIGMA_MODEL_ID:
            fixed_ok = (
                math.isclose(
                    snapshot.estimated_sigma,
                    FIXED_SIGMA,
                    rel_tol=0.0,
                    abs_tol=NUMERICAL_TOLERANCE,
                )
                and not snapshot.source_effect_ids
                and snapshot.sigma_status == "fixed"
            )
            all_ok = all_ok and fixed_ok
            continue
        source_rows = []
        for source_id in snapshot.source_effect_ids:
            source = history.get(source_id)
            if source is None:
                all_ok = False
                continue
            if _text(source["comparison_group_id"], "source group") != (
                snapshot.comparison_group_id
            ):
                all_ok = False
            if _text(source["source_kind"], "effect source kind") == "calibration":
                calibration = calibration_effects.get(source_id)
                if calibration is None:
                    all_ok = False
                else:
                    error = abs(
                        _number(source["observed_effect"], "history observed effect")
                        - _number(calibration["observed_effect"], "calibration observed effect")
                    )
                    max_error = max(max_error, error)
                    all_ok = all_ok and error <= NUMERICAL_TOLERANCE
            source_rows.append(source)
        if len(source_rows) < MINIMUM_PRIOR_EFFECTS:
            expected_sigma = FIXED_SIGMA
            expected_status = "baseline_fallback"
        else:
            expected_sigma = max(
                statistics.stdev(
                    _number(item["observed_effect"], "source observed effect")
                    for item in source_rows
                ),
                SIGMA_FLOOR,
            )
            expected_status = "calibrated"
        error = abs(snapshot.estimated_sigma - expected_sigma)
        max_error = max(max_error, error)
        all_ok = (
            all_ok and error <= NUMERICAL_TOLERANCE and snapshot.sigma_status == expected_status
        )
    compatibility.record(
        "sigma_provenance",
        record_id,
        all_ok,
        expected="strictly-prior group-local recorded effects",
        observed="recorded prediction snapshots",
        error=max_error,
    )


def _check_lookahead_trace(
    *,
    row: Mapping[str, Any],
    evidence_trace: Mapping[str, Any],
    catalog: tuple[CandidateRecord, ...],
    calibration_effects: Mapping[str, JsonObject],
    compatibility: CompatibilityAccumulator,
) -> ContextReplay:
    record_id = _text(row["decision_trace_id"], "decision trace ID")
    step = _integer(row["step"], "decision step")
    completed = _completed_before_step(evidence_trace, catalog, step)
    hypothesis_ids, posterior = _lookahead_posterior(row)
    snapshots = _recorded_snapshots(row)
    adapter = ReadOnlyScoringAdapter(
        candidates=catalog,
        completed_experiments=completed,
        max_cost=_number(row["remaining_budget"], "remaining budget"),
    )
    context: Literal["FF", "CC"] = (
        "FF" if _text(row["belief_model_id"], "belief model ID") == FIXED_SIGMA_MODEL_ID else "CC"
    )
    replay = adapter.replay(
        context=context,
        hypothesis_ids=hypothesis_ids,
        posterior_probabilities=posterior,
        snapshots=snapshots,
    )
    selected_id = _text(row["selected_candidate_id"], "selected candidate ID")
    compatibility.record(
        "active_lookahead_winner",
        record_id,
        replay.winner.candidate_id == selected_id,
        expected=replay.winner.candidate_id,
        observed=selected_id,
    )
    recorded = _stored_lookahead_scores(row)
    computed_ids = tuple(item.candidate_id for item in replay.ranked_plans)
    compatibility.record(
        "candidate_set_and_feasibility",
        record_id,
        set(computed_ids) == set(recorded),
        expected=sorted(computed_ids),
        observed=sorted(recorded),
    )
    max_error = 0.0
    aggregate_ok = set(computed_ids) == set(recorded)
    for plan in replay.ranked_plans:
        stored = recorded.get(plan.candidate_id)
        if stored is None:
            continue
        pairs = (
            (
                plan.immediate_information_gain,
                _number(stored["immediate_information_gain"], "stored immediate EIG"),
            ),
            (
                plan.expected_total_information_gain,
                _number(stored["expected_total_information_gain"], "stored total EIG"),
            ),
            (
                plan.expected_total_cost,
                _number(stored["expected_total_cost"], "stored expected cost"),
            ),
            (
                plan.information_gain_per_expected_cost,
                _number(stored["information_gain_per_expected_cost"], "stored EIG per cost"),
            ),
        )
        errors = tuple(abs(expected - observed) for expected, observed in pairs)
        max_error = max(max_error, *errors)
        aggregate_ok = aggregate_ok and max(errors) <= NUMERICAL_TOLERANCE
        aggregate_ok = aggregate_ok and plan.action_effect == _text(
            stored["action_effect"], "stored action effect"
        )
    compatibility.record(
        "plan_aggregation",
        record_id,
        aggregate_ok,
        expected="recomputed candidate aggregates",
        observed="stored candidate aggregates",
        error=max_error,
    )
    selected_plan = replay.plan(selected_id)
    trace = _mapping(row["policy_trace"], "policy trace")
    stored_branches = tuple(
        _mapping(item, "stored lookahead branch")
        for item in _sequence(trace["possible_evidence_branches"], "stored branches")
    )
    branch_ok = len(stored_branches) == len(selected_plan.branches)
    branch_error = 0.0
    for expected_branch, stored_branch in zip(
        selected_plan.branches, stored_branches, strict=False
    ):
        stored_posterior_map = _mapping(
            stored_branch["posterior_probabilities"], "stored branch posterior"
        )
        stored_posterior = tuple(
            _number(stored_posterior_map[item], "stored branch probability")
            for item in hypothesis_ids
        )
        second = _mapping(stored_branch["second_action"], "stored second action")
        comparisons = (
            abs(
                expected_branch.probability
                - _number(stored_branch["probability"], "branch probability")
            ),
            abs(
                expected_branch.posterior_entropy
                - _number(stored_branch["posterior_entropy"], "branch entropy")
            ),
            abs(
                expected_branch.terminal_entropy
                - _number(stored_branch["terminal_entropy"], "terminal entropy")
            ),
            abs(
                expected_branch.branch_total_cost
                - _number(stored_branch["branch_total_cost"], "branch total cost")
            ),
            max(
                abs(left - right)
                for left, right in zip(
                    expected_branch.posterior_probabilities, stored_posterior, strict=True
                )
            ),
        )
        branch_error = max(branch_error, *comparisons)
        branch_ok = (
            branch_ok
            and max(comparisons) <= NUMERICAL_TOLERANCE
            and expected_branch.branch_id == _text(stored_branch["branch_id"], "branch ID")
            and expected_branch.second_candidate_id
            == _text(second["candidate_id"], "second candidate ID")
            and expected_branch.budget_feasible
            == _boolean(stored_branch["budget_feasible"], "budget feasibility")
        )
    compatibility.record(
        "branch_probabilities_and_posteriors",
        record_id,
        branch_ok,
        expected="active-model branch tree",
        observed="stored branch tree",
        error=branch_error,
    )
    no_evidence_ok = all(
        not (
            plan.action_effect == "opens_pair"
            and (
                len(plan.branches) != 1
                or plan.branches[0].branch_id != "no-evidence-yet"
                or plan.immediate_information_gain != 0.0
            )
        )
        for plan in replay.ranked_plans
    )
    compatibility.record("pair_opener_semantics", record_id, no_evidence_ok)
    budget_ok = all(
        branch.budget_feasible
        and branch.branch_total_cost
        <= _number(row["remaining_budget"], "remaining budget") + NUMERICAL_TOLERANCE
        for plan in replay.ranked_plans
        for branch in plan.branches
    )
    compatibility.record("branch_budget_semantics", record_id, budget_ok)
    lineage_ok = all(
        item.belief_model_id == row["belief_model_id"]
        and item.belief_model_version == row["belief_model_version"]
        and item.lineage_id == row["lineage_id"]
        and item.belief_state_id == row["belief_state_id"]
        for item in snapshots
    )
    compatibility.record("lineage_identity", record_id, lineage_ok)
    normalization_ok = all(
        math.isclose(
            math.fsum(branch.posterior_probabilities),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        for plan in replay.ranked_plans
        for branch in plan.branches
    )
    compatibility.record("hypothetical_posterior_normalization", record_id, normalization_ok)
    ranking_ok = tuple(item.candidate_id for item in replay.ranked_plans)[0] == selected_id
    compatibility.record("ranking_and_explanation", record_id, ranking_ok)
    if _text(row["belief_model_id"], "belief model ID") == FIXED_SIGMA_MODEL_ID:
        compatibility.record(
            "fixed_arm_regression",
            record_id,
            _boolean(row["fixed_policy_regression_match"], "fixed policy regression match"),
        )
    _check_sigma_provenance(
        row=row,
        evidence_trace=evidence_trace,
        calibration_effects=calibration_effects,
        compatibility=compatibility,
    )
    return replay


def _arm_sequence_data(
    *,
    evidence_trace: Mapping[str, Any],
    decisions: Sequence[Mapping[str, Any]],
    catalog: tuple[CandidateRecord, ...],
    budget: float,
) -> JsonObject:
    lookup = _candidate_lookup(catalog)
    eligibility = OptimizerEvidenceEligibilityContract.from_candidates(
        (item.candidate for item in catalog),
        public_designs=(item.public_design for item in catalog),
    )
    completed: list[CompletedExperiment] = []
    action_effects: list[str] = []
    pair_events: list[JsonObject] = []
    experiments = tuple(
        sorted(
            (
                _mapping(item, "experiment")
                for item in _sequence(evidence_trace["experiments"], "experiments")
            ),
            key=lambda item: _integer(item["step"], "experiment step"),
        )
    )
    for experiment in experiments:
        candidate_id = _text(experiment["candidate_id"], "candidate ID")
        record = lookup[candidate_id]
        assessment = eligibility.assess_candidate(record.candidate, completed)
        action_effects.append(assessment.effect)
        if assessment.effect in {"opens_pair", "completes_pair"}:
            pair_events.append(
                {
                    "step": _integer(experiment["step"], "experiment step"),
                    "candidate_id": candidate_id,
                    "comparison_group_id": assessment.comparison_group_id,
                    "effect": assessment.effect,
                    "counterpart_candidate_id": assessment.counterpart_candidate_id,
                    "counterpart_experiment_id": assessment.counterpart_experiment_id,
                }
            )
        completed.append(
            CompletedExperiment(
                record_id=_integer(experiment["experiment_id"], "experiment ID"),
                candidate=record.candidate,
                observed_value=_number(experiment["observed_value"], "observed value"),
                created_at=_text(experiment["created_at"], "experiment creation time"),
            )
        )
    posterior_trace = tuple(
        sorted(
            (
                _mapping(item, "posterior trace item")
                for item in _sequence(evidence_trace["posterior_trace"], "posterior trace")
            ),
            key=lambda item: _integer(item["step"], "posterior step"),
        )
    )
    evidence_steps = [
        item for item in posterior_trace if _sequence(item["new_evidence_ids"], "new evidence IDs")
    ]
    first = evidence_steps[0] if evidence_steps else None
    if first is None:
        first_step = None
        first_cost = None
        cost_before = None
        remaining_after = None
    else:
        first_step = _integer(first["step"], "first evidence step")
        first_cost = _number(first["cumulative_decision_cost"], "first evidence cost")
        first_experiment_cost = _number(first["experiment_cost"], "first experiment cost")
        cost_before = first_cost - first_experiment_cost
        remaining_after = budget - first_cost
    commitment_step = None
    for item in posterior_trace:
        probabilities = _mapping(item["posterior_probabilities"], "posterior probabilities")
        if max(_number(value, "posterior probability") for value in probabilities.values()) >= (
            COMMITMENT_THRESHOLD
        ):
            commitment_step = _integer(item["step"], "commitment step")
            break
    updates = tuple(
        _mapping(item, "model update")
        for item in _sequence(evidence_trace["model_updates"], "model updates")
    )
    sigma_source_order = tuple(
        tuple(
            _text(source, "sigma source ID")
            for source in _sequence(
                _mapping(update["sigma_estimate"], "sigma estimate")["source_effect_ids"],
                "sigma source effect IDs",
            )
        )
        for update in updates
    )
    decision_cost = (
        0.0
        if not experiments
        else _number(experiments[-1]["cumulative_decision_cost"], "final decision cost")
    )
    sequence = tuple(_text(item["candidate_id"], "candidate ID") for item in experiments)
    remaining = budget - decision_cost
    unselected = [item for item in catalog if item.candidate.candidate_id not in set(sequence)]
    feasible_remaining = [
        item for item in unselected if item.cost <= remaining + NUMERICAL_TOLERANCE
    ]
    if remaining <= NUMERICAL_TOLERANCE:
        stop_reason = "decision_budget_exhausted"
    elif not feasible_remaining:
        stop_reason = "no_feasible_candidate_remains"
    else:
        stop_reason = "recorded_stopping_condition"
    return {
        "sequence": sequence,
        "action_effects": tuple(action_effects),
        "pair_events": tuple(pair_events),
        "first_evidence_step": first_step,
        "first_evidence_cost": first_cost,
        "cost_before_first_evidence": cost_before,
        "remaining_budget_after_first_evidence": remaining_after,
        "evidence_count": len(_sequence(evidence_trace["evidence"], "evidence")),
        "evidence_order": tuple(
            _text(item["evidence_id"], "evidence ID")
            for value in _sequence(evidence_trace["evidence"], "evidence")
            for item in (_mapping(value, "evidence item"),)
        ),
        "sigma_source_order": sigma_source_order,
        "commitment_step": commitment_step,
        "decision_cost": decision_cost,
        "stop_reason": stop_reason,
        "matched_pair_count": sum(effect == "completes_pair" for effect in action_effects),
        "decision_trace_ids": tuple(
            _text(item["decision_trace_id"], "decision trace ID") for item in decisions
        ),
    }


def _edit_distance(left: Sequence[str], right: Sequence[str]) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_item in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_item in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_item != right_item),
                )
            )
        previous = current
    return previous[-1]


def _path_cost_to_evidence(
    *,
    candidate: CandidateRecord,
    completed: Sequence[CompletedExperiment],
    catalog: Sequence[CandidateRecord],
    eligibility: OptimizerEvidenceEligibilityContract,
) -> float | None:
    assessment = eligibility.assess_candidate(candidate.candidate, completed)
    if assessment.effect == "completes_pair":
        return candidate.cost
    if assessment.effect != "opens_pair":
        return None
    design = candidate.public_design
    complement_costs = [
        item.cost
        for item in catalog
        if item.public_design.comparison_group_id == design.comparison_group_id
        and item.public_design.intervention_arm != design.intervention_arm
    ]
    return None if not complement_costs else candidate.cost + min(complement_costs)


def _budget_crowd_out(
    *,
    fixed_sequence: tuple[str, ...],
    calibrated_sequence: tuple[str, ...],
    calibrated_trace: Mapping[str, Any],
    catalog: tuple[CandidateRecord, ...],
    budget: float,
    divergence_step: int,
) -> JsonObject | None:
    missing = sorted(set(fixed_sequence).difference(calibrated_sequence))
    if not missing:
        return None
    lookup = _candidate_lookup(catalog)
    eligibility = OptimizerEvidenceEligibilityContract.from_candidates(
        (item.candidate for item in catalog),
        public_designs=(item.public_design for item in catalog),
    )
    experiments = tuple(
        sorted(
            (
                _mapping(item, "experiment")
                for item in _sequence(calibrated_trace["experiments"], "experiments")
            ),
            key=lambda item: _integer(item["step"], "experiment step"),
        )
    )
    initial_completed: list[CompletedExperiment] = []
    initial_cost = 0.0
    for experiment in experiments:
        if _integer(experiment["step"], "experiment step") >= divergence_step:
            break
        completed_candidate = lookup[_text(experiment["candidate_id"], "candidate ID")].candidate
        initial_completed.append(
            CompletedExperiment(
                record_id=_integer(experiment["experiment_id"], "experiment ID"),
                candidate=completed_candidate,
                observed_value=_number(experiment["observed_value"], "observed value"),
                created_at=_text(experiment["created_at"], "created at"),
            )
        )
        initial_cost = _number(experiment["cumulative_decision_cost"], "cumulative cost")
    for candidate_id in missing:
        missing_candidate = lookup[candidate_id]
        initial_path = _path_cost_to_evidence(
            candidate=missing_candidate,
            completed=initial_completed,
            catalog=catalog,
            eligibility=eligibility,
        )
        if initial_path is None or initial_path > budget - initial_cost + NUMERICAL_TOLERANCE:
            continue
        completed = list(initial_completed)
        states: list[tuple[int, float, float | None]] = []
        for experiment in experiments:
            step = _integer(experiment["step"], "experiment step")
            if step < divergence_step:
                continue
            selected = lookup[_text(experiment["candidate_id"], "candidate ID")]
            completed.append(
                CompletedExperiment(
                    record_id=_integer(experiment["experiment_id"], "experiment ID"),
                    candidate=selected.candidate,
                    observed_value=_number(experiment["observed_value"], "observed value"),
                    created_at=_text(experiment["created_at"], "created at"),
                )
            )
            remaining = budget - _number(
                experiment["cumulative_decision_cost"], "cumulative decision cost"
            )
            path = _path_cost_to_evidence(
                candidate=missing_candidate,
                completed=completed,
                catalog=catalog,
                eligibility=eligibility,
            )
            states.append((step, remaining, path))
        for index, (step, remaining, path) in enumerate(states):
            infeasible = path is not None and path > remaining + NUMERICAL_TOLERANCE
            remains_infeasible = all(
                later_path is None or later_path > later_remaining + NUMERICAL_TOLERANCE
                for _, later_remaining, later_path in states[index:]
            )
            if infeasible and remains_infeasible:
                return {
                    "candidate_id": candidate_id,
                    "initial_path_cost": initial_path,
                    "crowd_out_step": step,
                    "remaining_budget": remaining,
                    "required_path_cost": path,
                    "association_only": True,
                }
    return None


def _pair_completion_delay(
    *,
    fixed_data: Mapping[str, Any],
    calibrated_data: Mapping[str, Any],
    divergence_step: int,
) -> JsonObject | None:
    fixed_events = tuple(cast(tuple[JsonObject, ...], fixed_data["pair_events"]))
    calibrated_events = tuple(cast(tuple[JsonObject, ...], calibrated_data["pair_events"]))
    fixed_event = next(
        (
            item
            for item in fixed_events
            if item["step"] == divergence_step and item["effect"] == "completes_pair"
        ),
        None,
    )
    if fixed_event is None:
        return None
    group_id = _text(fixed_event["comparison_group_id"], "comparison group ID")
    calibrated_at_step = next(
        (item for item in calibrated_events if item["step"] == divergence_step), None
    )
    if calibrated_at_step is not None and (
        calibrated_at_step["effect"] == "completes_pair"
        and calibrated_at_step["comparison_group_id"] == group_id
    ):
        return None
    later = next(
        (
            item
            for item in calibrated_events
            if item["effect"] == "completes_pair"
            and item["comparison_group_id"] == group_id
            and _integer(item["step"], "pair completion step") > divergence_step
        ),
        None,
    )
    return {
        "comparison_group_id": group_id,
        "fixed_completion_step": divergence_step,
        "calibrated_completion_step": None if later is None else later["step"],
        "delay_steps": None
        if later is None
        else _integer(later["step"], "calibrated completion step") - divergence_step,
        "never_completed": later is None,
    }


def _build_sequence_summary(
    *,
    pair: DivergencePair,
    fixed_trace: Mapping[str, Any],
    calibrated_trace: Mapping[str, Any],
    fixed_decisions: Sequence[Mapping[str, Any]],
    calibrated_decisions: Sequence[Mapping[str, Any]],
    catalog: tuple[CandidateRecord, ...],
    budget: float,
) -> SequenceSummary:
    fixed = _arm_sequence_data(
        evidence_trace=fixed_trace,
        decisions=fixed_decisions,
        catalog=catalog,
        budget=budget,
    )
    calibrated = _arm_sequence_data(
        evidence_trace=calibrated_trace,
        decisions=calibrated_decisions,
        catalog=catalog,
        budget=budget,
    )
    fixed_sequence = cast(tuple[str, ...], fixed["sequence"])
    calibrated_sequence = cast(tuple[str, ...], calibrated["sequence"])
    fixed_set = set(fixed_sequence)
    calibrated_set = set(calibrated_sequence)
    intersection = tuple(sorted(fixed_set.intersection(calibrated_set)))
    union = tuple(sorted(fixed_set.union(calibrated_set)))
    if fixed_set == calibrated_set and fixed_sequence != calibrated_sequence:
        relation: SetRelation = "SAME_SET_DIFFERENT_ORDER"
    elif fixed_set.intersection(calibrated_set):
        relation = "PARTIAL_OVERLAP"
    else:
        relation = "DISJOINT"
    jaccard = 1.0 if not union else len(intersection) / len(union)
    edit_distance = _edit_distance(fixed_sequence, calibrated_sequence)
    max_length = max(len(fixed_sequence), len(calibrated_sequence))
    order_similarity = 1.0 if max_length == 0 else 1.0 - edit_distance / max_length
    fixed_commitment = cast(int | None, fixed["commitment_step"])
    calibrated_commitment = cast(int | None, calibrated["commitment_step"])
    delayed_commitment = fixed_commitment is not None and (
        calibrated_commitment is None or calibrated_commitment > fixed_commitment
    )
    return SequenceSummary(
        fixed_sequence=fixed_sequence,
        calibrated_sequence=calibrated_sequence,
        fixed_action_effects=cast(tuple[str, ...], fixed["action_effects"]),
        calibrated_action_effects=cast(tuple[str, ...], calibrated["action_effects"]),
        fixed_pair_events=cast(tuple[JsonObject, ...], fixed["pair_events"]),
        calibrated_pair_events=cast(tuple[JsonObject, ...], calibrated["pair_events"]),
        fixed_first_evidence_step=cast(int | None, fixed["first_evidence_step"]),
        calibrated_first_evidence_step=cast(int | None, calibrated["first_evidence_step"]),
        fixed_first_evidence_cost=cast(float | None, fixed["first_evidence_cost"]),
        calibrated_first_evidence_cost=cast(float | None, calibrated["first_evidence_cost"]),
        fixed_cost_before_first_evidence=cast(float | None, fixed["cost_before_first_evidence"]),
        calibrated_cost_before_first_evidence=cast(
            float | None, calibrated["cost_before_first_evidence"]
        ),
        fixed_remaining_budget_after_first_evidence=cast(
            float | None, fixed["remaining_budget_after_first_evidence"]
        ),
        calibrated_remaining_budget_after_first_evidence=cast(
            float | None, calibrated["remaining_budget_after_first_evidence"]
        ),
        fixed_evidence_count=_integer(fixed["evidence_count"], "fixed evidence count"),
        calibrated_evidence_count=_integer(
            calibrated["evidence_count"], "calibrated evidence count"
        ),
        fixed_evidence_order=cast(tuple[str, ...], fixed["evidence_order"]),
        calibrated_evidence_order=cast(tuple[str, ...], calibrated["evidence_order"]),
        fixed_sigma_source_order=cast(tuple[tuple[str, ...], ...], fixed["sigma_source_order"]),
        calibrated_sigma_source_order=cast(
            tuple[tuple[str, ...], ...], calibrated["sigma_source_order"]
        ),
        fixed_final_set=tuple(sorted(fixed_set)),
        calibrated_final_set=tuple(sorted(calibrated_set)),
        intersection=intersection,
        union=union,
        set_relation=relation,
        jaccard_similarity=jaccard,
        order_similarity=order_similarity,
        sequence_edit_distance=edit_distance,
        fixed_commitment_step=fixed_commitment,
        calibrated_commitment_step=calibrated_commitment,
        calibrated_delayed_commitment=delayed_commitment,
        pair_completion_delay=_pair_completion_delay(
            fixed_data=fixed,
            calibrated_data=calibrated,
            divergence_step=pair.first_divergence_step,
        ),
        budget_crowd_out=_budget_crowd_out(
            fixed_sequence=fixed_sequence,
            calibrated_sequence=calibrated_sequence,
            calibrated_trace=calibrated_trace,
            catalog=catalog,
            budget=budget,
            divergence_step=pair.first_divergence_step,
        ),
        fixed_decision_cost=_number(fixed["decision_cost"], "fixed decision cost"),
        calibrated_decision_cost=_number(calibrated["decision_cost"], "calibrated decision cost"),
        fixed_stop_reason=_text(fixed["stop_reason"], "fixed stop reason"),
        calibrated_stop_reason=_text(calibrated["stop_reason"], "calibrated stop reason"),
    )


def _ranking_stage(replay: ContextReplay) -> str:
    winner = replay.winner
    other = replay.ranked_plans[1] if len(replay.ranked_plans) > 1 else None
    if other is None:
        return "only_candidate"
    top = tuple(
        item
        for item in replay.ranked_plans
        if abs(item.expected_total_information_gain - winner.expected_total_information_gain)
        <= NUMERICAL_TOLERANCE
    )
    if len(top) == 1:
        return "greater_expected_total_information_gain"
    minimum_cost = min(item.expected_total_cost for item in top)
    cost_tied = tuple(
        item for item in top if abs(item.expected_total_cost - minimum_cost) <= NUMERICAL_TOLERANCE
    )
    if len(cost_tied) == 1:
        return "lower_expected_total_cost"
    maximum_ratio = max(item.information_gain_per_expected_cost for item in cost_tied)
    ratio_tied = tuple(
        item
        for item in cost_tied
        if abs(item.information_gain_per_expected_cost - maximum_ratio) <= NUMERICAL_TOLERANCE
    )
    if len(ratio_tied) == 1:
        return "greater_information_gain_per_expected_cost"
    return "stable_lexicographic_candidate_id"


def shapley_score_decomposition(
    *,
    replays: Mapping[str, ContextReplay],
    fixed_candidate_id: str,
    calibrated_candidate_id: str,
) -> JsonObject:
    """Apply the exact frozen two-factor Shapley margin decomposition."""

    margins: dict[str, float] = {}
    immediate_margins: dict[str, float] = {}
    future_margins: dict[str, float] = {}
    cost_margins: dict[str, float] = {}
    ratio_margins: dict[str, float] = {}
    for context in ("FF", "CF", "FC", "CC"):
        replay = replays[context]
        calibrated = replay.plan(calibrated_candidate_id)
        fixed = replay.plan(fixed_candidate_id)
        margins[context] = (
            calibrated.expected_total_information_gain - fixed.expected_total_information_gain
        )
        immediate_margins[context] = (
            calibrated.immediate_information_gain - fixed.immediate_information_gain
        )
        future_margins[context] = (
            calibrated.delayed_information_gain - fixed.delayed_information_gain
        )
        cost_margins[context] = calibrated.expected_total_cost - fixed.expected_total_cost
        ratio_margins[context] = (
            calibrated.information_gain_per_expected_cost - fixed.information_gain_per_expected_cost
        )
    belief = 0.5 * ((margins["CF"] - margins["FF"]) + (margins["CC"] - margins["FC"]))
    sigma = 0.5 * ((margins["FC"] - margins["FF"]) + (margins["CC"] - margins["CF"]))
    interaction = margins["CC"] - margins["CF"] - margins["FC"] + margins["FF"]
    reconciliation_error = abs((belief + sigma) - (margins["CC"] - margins["FF"]))
    temporal_error = max(
        abs(margins[key] - immediate_margins[key] - future_margins[key]) for key in margins
    )
    if reconciliation_error > NUMERICAL_TOLERANCE or temporal_error > NUMERICAL_TOLERANCE:
        raise DivergenceAuditError("Frozen Shapley or temporal decomposition did not reconcile.")
    ranges = {
        context: max(item.expected_total_information_gain for item in replay.ranked_plans)
        - min(item.expected_total_information_gain for item in replay.ranked_plans)
        for context, replay in replays.items()
    }
    return {
        "fixed_candidate_id": fixed_candidate_id,
        "calibrated_candidate_id": calibrated_candidate_id,
        "margins": margins,
        "immediate_margins": immediate_margins,
        "future_margins": future_margins,
        "expected_cost_margins": cost_margins,
        "information_gain_per_cost_margins": ratio_margins,
        "belief_state_contribution": belief,
        "sigma_likelihood_contribution": sigma,
        "belief_sigma_interaction": interaction,
        "reconciliation_error": reconciliation_error,
        "temporal_reconciliation_error": temporal_error,
        "score_ranges": ranges,
        "ranking_stages": {context: _ranking_stage(replay) for context, replay in replays.items()},
        "winners": {context: replay.winner.candidate_id for context, replay in replays.items()},
        "branch_budget_feasible": {
            context: all(
                branch.budget_feasible for plan in replay.ranked_plans for branch in plan.branches
            )
            for context, replay in replays.items()
        },
        "tolerance": NUMERICAL_TOLERANCE,
        "association_not_causation": True,
    }


def _classify_mechanisms(
    *,
    replays: Mapping[str, ContextReplay],
    decomposition: Mapping[str, Any],
    sequence: SequenceSummary,
    fixed_selected: str,
    calibrated_selected: str,
    compatibility_passed: bool,
) -> MechanismClassification:
    ff = replays["FF"]
    cf = replays["CF"]
    fc = replays["FC"]
    cc = replays["CC"]
    fixed_plan = ff.plan(fixed_selected)
    calibrated_plan = cc.plan(calibrated_selected)
    ranges = _mapping(decomposition["score_ranges"], "score ranges")
    flattening = (
        _number(ranges["CC"], "CC score range")
        < _number(ranges["FF"], "FF score range") - NUMERICAL_TOLERANCE
        and fc.winner.candidate_id != ff.winner.candidate_id
    )
    belief_reordering = cf.winner.candidate_id != ff.winner.candidate_id
    group_sigma_reordering = fc.winner.candidate_id != ff.winner.candidate_id and not flattening
    interaction = (
        cc.winner.candidate_id != ff.winner.candidate_id
        and cf.winner.candidate_id == ff.winner.candidate_id
        and fc.winner.candidate_id == ff.winner.candidate_id
        and abs(_number(decomposition["belief_sigma_interaction"], "interaction"))
        > NUMERICAL_TOLERANCE
    )
    ranking_stages = _mapping(decomposition["ranking_stages"], "ranking stages")
    cost_tiebreak = any(
        ranking_stages[context]
        in {
            "lower_expected_total_cost",
            "greater_information_gain_per_expected_cost",
            "stable_lexicographic_candidate_id",
        }
        for context in ("FF", "CC")
    )
    pair_delay = sequence.pair_completion_delay is not None
    pair_opener_change = (
        fixed_plan.action_effect == "opens_pair"
        and calibrated_plan.action_effect == "opens_pair"
        and fixed_plan.comparison_group_id != calibrated_plan.comparison_group_id
    )
    same_set_order = sequence.set_relation == "SAME_SET_DIFFERENT_ORDER"
    budget_crowd_out = sequence.budget_crowd_out is not None
    conservative = sequence.calibrated_delayed_commitment
    predicates: dict[Mechanism, JsonObject] = {
        "SCORE_FLATTENING": {
            "matched": flattening,
            "fixed_score_range": ranges["FF"],
            "calibrated_score_range": ranges["CC"],
            "sigma_only_winner": fc.winner.candidate_id,
            "fixed_winner": ff.winner.candidate_id,
        },
        "BELIEF_STATE_REORDERING": {
            "matched": belief_reordering,
            "belief_only_winner": cf.winner.candidate_id,
            "fixed_winner": ff.winner.candidate_id,
        },
        "GROUP_SIGMA_REORDERING": {
            "matched": group_sigma_reordering,
            "sigma_only_winner": fc.winner.candidate_id,
            "score_flattening_excluded": not flattening,
        },
        "BELIEF_SIGMA_INTERACTION": {
            "matched": interaction,
            "interaction_value": decomposition["belief_sigma_interaction"],
            "winners": decomposition["winners"],
        },
        "COST_TIEBREAK_CHANGE": {
            "matched": cost_tiebreak,
            "ranking_stages": ranking_stages,
            "expected_cost_margins": decomposition["expected_cost_margins"],
        },
        "PAIR_COMPLETION_DELAY": {
            "matched": pair_delay,
            "evidence": sequence.pair_completion_delay,
        },
        "PAIR_OPENER_CHANGE": {
            "matched": pair_opener_change,
            "fixed_action_effect": fixed_plan.action_effect,
            "calibrated_action_effect": calibrated_plan.action_effect,
            "fixed_comparison_group_id": fixed_plan.comparison_group_id,
            "calibrated_comparison_group_id": calibrated_plan.comparison_group_id,
        },
        "SAME_SET_DIFFERENT_ORDER": {
            "matched": same_set_order,
            "set_relation": sequence.set_relation,
            "fixed_sequence": list(sequence.fixed_sequence),
            "calibrated_sequence": list(sequence.calibrated_sequence),
        },
        "BUDGET_CROWD_OUT": {
            "matched": budget_crowd_out,
            "evidence": sequence.budget_crowd_out,
            "association_only": True,
        },
        "CONSERVATIVE_NONCOMMITMENT": {
            "matched": conservative,
            "fixed_commitment_step": sequence.fixed_commitment_step,
            "calibrated_commitment_step": sequence.calibrated_commitment_step,
            "threshold": COMMITMENT_THRESHOLD,
        },
        "PLANNER_MODEL_MISMATCH": {
            "matched": not compatibility_passed,
            "compatibility_passed": compatibility_passed,
        },
        "NO_STABLE_MECHANISM": {"matched": False, "excluded_predicates_complete": True},
    }
    true_nonresidual = [
        mechanism
        for mechanism in MECHANISMS[:-1]
        if _boolean(predicates[mechanism]["matched"], "mechanism predicate")
    ]
    if not true_nonresidual:
        predicates["NO_STABLE_MECHANISM"]["matched"] = True
        primary: Mechanism = "NO_STABLE_MECHANISM"
    elif not compatibility_passed:
        primary = "PLANNER_MODEL_MISMATCH"
    else:
        numerical = [
            mechanism
            for mechanism in (
                "SCORE_FLATTENING",
                "BELIEF_STATE_REORDERING",
                "GROUP_SIGMA_REORDERING",
                "BELIEF_SIGMA_INTERACTION",
            )
            if mechanism in true_nonresidual
        ]
        if numerical:
            if "BELIEF_STATE_REORDERING" in numerical and any(
                item in numerical for item in ("SCORE_FLATTENING", "GROUP_SIGMA_REORDERING")
            ):
                belief_value = abs(
                    _number(decomposition["belief_state_contribution"], "belief contribution")
                )
                sigma_value = abs(
                    _number(decomposition["sigma_likelihood_contribution"], "sigma contribution")
                )
                if belief_value > sigma_value + NUMERICAL_TOLERANCE:
                    primary = "BELIEF_STATE_REORDERING"
                elif "SCORE_FLATTENING" in numerical:
                    primary = "SCORE_FLATTENING"
                else:
                    primary = "GROUP_SIGMA_REORDERING"
            else:
                primary = next(mechanism for mechanism in MECHANISMS if mechanism in numerical)
        else:
            primary = next(mechanism for mechanism in MECHANISMS if mechanism in true_nonresidual)
    contributing = tuple(
        mechanism
        for mechanism in MECHANISMS
        if mechanism != primary
        and _boolean(predicates[mechanism]["matched"], "mechanism predicate")
    )
    return MechanismClassification(
        primary_mechanism=primary,
        contributing_mechanisms=contributing,
        predicate_evidence=tuple((item, predicates[item]) for item in MECHANISMS),
    )


def _global_source_compatibility_passed(source_checks: Mapping[str, Any]) -> bool:
    return (
        _boolean(source_checks["all_frozen_source_hashes_match"], "source-hash check")
        and _boolean(source_checks["all_frozen_design_hashes_match"], "design-hash check")
        and _boolean(
            source_checks["no_embedded_fixed_sigma_in_scoring_paths"],
            "embedded fixed-sigma check",
        )
    )


def _shared_history_fingerprint(
    completed: Sequence[CompletedExperiment], catalog: Sequence[CandidateRecord]
) -> str:
    lookup = _candidate_lookup(catalog)
    payload = [
        {
            "candidate_id": item.candidate.candidate_id,
            "experiment_id": item.record_id,
            "observed_value": item.observed_value,
            "public_design": lookup[item.candidate.candidate_id].public_design.to_dict(),
        }
        for item in completed
    ]
    return _stable_id("public-history", payload)


def _construct_truth_free_cases(
    workspace: _AuditWorkspace,
) -> tuple[TruthFreeDivergenceCase, ...]:
    active_replays: dict[str, ContextReplay] = {}
    relevant_runs = {
        run_id for pair in workspace.pairs for run_id in (pair.fixed_run_id, pair.calibrated_run_id)
    }
    for run_id in sorted(relevant_runs):
        evidence_trace = workspace.evidence_by_run[run_id]
        world_id = _text(evidence_trace["world_id"], "world ID")
        catalog = workspace.catalog_by_world[world_id]
        for row in workspace.decisions_by_run[run_id]:
            if _text(row["policy"], "policy") != "lookahead_information_gain":
                raise DivergenceAuditError("Frozen divergent population must use lookahead.")
            replay = _check_lookahead_trace(
                row=row,
                evidence_trace=evidence_trace,
                catalog=catalog,
                calibration_effects=workspace.calibration_effects,
                compatibility=workspace.compatibility,
            )
            active_replays[_text(row["decision_trace_id"], "decision trace ID")] = replay

    global_compatibility = _global_source_compatibility_passed(workspace.source_checks)
    cases: list[TruthFreeDivergenceCase] = []
    for pair in workspace.pairs:
        fixed_decisions = workspace.decisions_by_run[pair.fixed_run_id]
        calibrated_decisions = workspace.decisions_by_run[pair.calibrated_run_id]
        index = pair.common_prefix_length
        if index >= len(fixed_decisions) or index >= len(calibrated_decisions):
            raise DivergenceAuditError("Frozen divergence cannot involve a missing decision.")
        fixed_row = fixed_decisions[index]
        calibrated_row = calibrated_decisions[index]
        fixed_trace = workspace.evidence_by_run[pair.fixed_run_id]
        calibrated_trace = workspace.evidence_by_run[pair.calibrated_run_id]
        catalog = workspace.catalog_by_world[pair.world_id]
        budget = _number(fixed_row["remaining_budget"], "fixed remaining budget")
        calibrated_budget = _number(
            calibrated_row["remaining_budget"], "calibrated remaining budget"
        )
        if not math.isclose(budget, calibrated_budget, rel_tol=0.0, abs_tol=NUMERICAL_TOLERANCE):
            raise DivergenceAuditError("Paired arms have different pre-divergence budgets.")
        fixed_completed = _completed_before_step(fixed_trace, catalog, pair.first_divergence_step)
        calibrated_completed = _completed_before_step(
            calibrated_trace, catalog, pair.first_divergence_step
        )
        fixed_history = tuple(
            (item.candidate.candidate_id, item.observed_value) for item in fixed_completed
        )
        calibrated_history = tuple(
            (item.candidate.candidate_id, item.observed_value) for item in calibrated_completed
        )
        if fixed_history != calibrated_history:
            raise DivergenceAuditError("Paired arms do not share pre-divergence public history.")
        fixed_hypotheses, fixed_posterior = _lookahead_posterior(fixed_row)
        calibrated_hypotheses, calibrated_posterior = _lookahead_posterior(calibrated_row)
        if fixed_hypotheses != calibrated_hypotheses:
            raise DivergenceAuditError("Paired arms use different hypothesis identities.")
        fixed_snapshots = _recorded_snapshots(fixed_row)
        calibrated_snapshots = _recorded_snapshots(calibrated_row)
        fixed_groups = tuple(item.comparison_group_id for item in fixed_snapshots)
        calibrated_groups = tuple(item.comparison_group_id for item in calibrated_snapshots)
        if fixed_groups != calibrated_groups:
            raise DivergenceAuditError("Paired arms expose different comparison groups.")
        for fixed_snapshot, calibrated_snapshot in zip(
            fixed_snapshots, calibrated_snapshots, strict=True
        ):
            if fixed_snapshot.means != calibrated_snapshot.means:
                raise DivergenceAuditError("Crossed replay found model-dependent hypothesis means.")
        adapter = ReadOnlyScoringAdapter(
            candidates=catalog,
            completed_experiments=fixed_completed,
            max_cost=budget,
        )
        replays: dict[str, ContextReplay] = {
            "FF": adapter.replay(
                context="FF",
                hypothesis_ids=fixed_hypotheses,
                posterior_probabilities=fixed_posterior,
                snapshots=fixed_snapshots,
            ),
            "CF": adapter.replay(
                context="CF",
                hypothesis_ids=fixed_hypotheses,
                posterior_probabilities=calibrated_posterior,
                snapshots=fixed_snapshots,
            ),
            "FC": adapter.replay(
                context="FC",
                hypothesis_ids=fixed_hypotheses,
                posterior_probabilities=fixed_posterior,
                snapshots=calibrated_snapshots,
            ),
            "CC": adapter.replay(
                context="CC",
                hypothesis_ids=fixed_hypotheses,
                posterior_probabilities=calibrated_posterior,
                snapshots=calibrated_snapshots,
            ),
        }
        fixed_selected = _text(fixed_row["selected_candidate_id"], "fixed candidate")
        calibrated_selected = _text(calibrated_row["selected_candidate_id"], "calibrated candidate")
        fixed_active_id = _text(fixed_row["decision_trace_id"], "fixed decision trace ID")
        calibrated_active_id = _text(
            calibrated_row["decision_trace_id"], "calibrated decision trace ID"
        )
        if replays["FF"].winner.candidate_id != fixed_selected:
            workspace.compatibility.record(
                "four_context_active_ranking",
                fixed_active_id,
                False,
                expected=replays["FF"].winner.candidate_id,
                observed=fixed_selected,
            )
        else:
            workspace.compatibility.record("four_context_active_ranking", fixed_active_id, True)
        if replays["CC"].winner.candidate_id != calibrated_selected:
            workspace.compatibility.record(
                "four_context_active_ranking",
                calibrated_active_id,
                False,
                expected=replays["CC"].winner.candidate_id,
                observed=calibrated_selected,
            )
        else:
            workspace.compatibility.record(
                "four_context_active_ranking", calibrated_active_id, True
            )
        decomposition = shapley_score_decomposition(
            replays=replays,
            fixed_candidate_id=fixed_selected,
            calibrated_candidate_id=calibrated_selected,
        )
        sequence = _build_sequence_summary(
            pair=pair,
            fixed_trace=fixed_trace,
            calibrated_trace=calibrated_trace,
            fixed_decisions=fixed_decisions,
            calibrated_decisions=calibrated_decisions,
            catalog=catalog,
            budget=budget,
        )
        check_ids = tuple(
            _text(item["decision_trace_id"], "decision trace ID")
            for item in (*fixed_decisions, *calibrated_decisions)
        )
        compatibility_passed = global_compatibility and workspace.compatibility.case_passed(
            check_ids
        )
        classification = _classify_mechanisms(
            replays=replays,
            decomposition=decomposition,
            sequence=sequence,
            fixed_selected=fixed_selected,
            calibrated_selected=calibrated_selected,
            compatibility_passed=compatibility_passed,
        )
        fixed_policy_trace = _mapping(fixed_row["policy_trace"], "fixed policy trace")
        calibrated_policy_trace = _mapping(
            calibrated_row["policy_trace"], "calibrated policy trace"
        )
        fixed_candidate_fingerprint = _text(
            fixed_policy_trace["candidate_set_fingerprint"], "candidate-set fingerprint"
        )
        calibrated_candidate_fingerprint = _text(
            calibrated_policy_trace["candidate_set_fingerprint"],
            "calibrated candidate-set fingerprint",
        )
        fixed_completed_fingerprint = _text(
            fixed_policy_trace["completed_state_fingerprint"], "completed-state fingerprint"
        )
        calibrated_completed_fingerprint = _text(
            calibrated_policy_trace["completed_state_fingerprint"],
            "calibrated completed-state fingerprint",
        )
        if (
            fixed_candidate_fingerprint != calibrated_candidate_fingerprint
            or fixed_completed_fingerprint != calibrated_completed_fingerprint
        ):
            raise DivergenceAuditError("Paired arms have different public initial fingerprints.")
        commitment = workspace.commitments[(pair.world_id, pair.seed)]
        commitment_candidates = tuple(
            sorted(
                _text(item, "committed candidate ID")
                for item in _sequence(commitment["candidate_ids"], "committed candidates")
            )
        )
        catalog_candidates = tuple(sorted(item.candidate.candidate_id for item in catalog))
        if commitment_candidates != catalog_candidates:
            raise DivergenceAuditError("Public candidate catalog does not match commitment.")
        public_initial_fingerprint = _stable_id(
            "public-initial-condition",
            {
                "candidate_set_fingerprint": fixed_candidate_fingerprint,
                "completed_state_fingerprint": fixed_completed_fingerprint,
                "history_fingerprint": _shared_history_fingerprint(fixed_completed, catalog),
            },
        )
        cases.append(
            TruthFreeDivergenceCase(
                pair=pair,
                oracle_version=_text(commitment["oracle_version"], "oracle version"),
                commitment_id=_text(commitment["commitment_id"], "commitment ID"),
                budget=budget,
                public_initial_fingerprint=public_initial_fingerprint,
                fixed_belief_state_id=_text(fixed_row["belief_state_id"], "fixed belief state ID"),
                calibrated_belief_state_id=_text(
                    calibrated_row["belief_state_id"], "calibrated belief state ID"
                ),
                fixed_lineage_id=_text(fixed_row["lineage_id"], "fixed lineage ID"),
                calibrated_lineage_id=_text(calibrated_row["lineage_id"], "calibrated lineage ID"),
                fixed_posterior=tuple(zip(fixed_hypotheses, fixed_posterior, strict=True)),
                calibrated_posterior=tuple(
                    zip(calibrated_hypotheses, calibrated_posterior, strict=True)
                ),
                fixed_snapshots=fixed_snapshots,
                calibrated_snapshots=calibrated_snapshots,
                candidates=catalog,
                replays=tuple(replays[item] for item in ("FF", "CF", "FC", "CC")),
                decomposition=decomposition,
                sequence=sequence,
                classification=classification,
                compatibility_passed=compatibility_passed,
                compatibility_check_ids=check_ids,
            )
        )
    return tuple(cases)


def _metric_subset(metrics: Mapping[str, Any]) -> JsonObject:
    names = (
        "negative_log_true_hypothesis_probability",
        "final_brier_score",
        "final_true_hypothesis_probability",
        "final_true_hypothesis_rank",
        "final_posterior_entropy",
        "confidently_wrong",
        "prediction_correct",
        "reached_sustained_80_confidence",
        "reached_sustained_95_confidence",
        "decision_cost_to_sustained_80_confidence",
        "decision_cost_to_sustained_95_confidence",
        "matched_evidence_pairs_completed",
        "redundant_experiments_selected",
        "decision_cost",
        "calibration_cost",
        "required_total_cost",
        "budget_exhausted",
        "best_observed_objective",
    )
    return {name: metrics.get(name) for name in names}


def _metric_differences(fixed: Mapping[str, Any], calibrated: Mapping[str, Any]) -> JsonObject:
    result: JsonObject = {}
    for name in fixed:
        left = fixed[name]
        right = calibrated[name]
        if isinstance(left, bool) and isinstance(right, bool):
            result[name] = int(right) - int(left)
        elif isinstance(left, (int, float)) and isinstance(right, (int, float)):
            result[name] = float(right) - float(left)
        elif left is None or right is None:
            result[name] = None
    return result


def _join_evaluator_outcomes(
    *,
    workspace: _AuditWorkspace,
    truth_free_cases: tuple[TruthFreeDivergenceCase, ...],
    reader: _ArtifactReader,
) -> tuple[AuditedDivergenceCase, ...]:
    divergence_events = {
        _text(row["divergence_id"], "divergence ID"): row
        for row in reader.iter_jsonl("divergence_events.jsonl", stage="B")
    }
    relevant_run_ids = {
        run_id
        for item in truth_free_cases
        for run_id in (item.pair.fixed_run_id, item.pair.calibrated_run_id)
    }
    run_results: dict[str, JsonObject] = {}
    for row in reader.iter_jsonl("per_run_results.jsonl", stage="B"):
        run_id = _text(row["run_id"], "run ID")
        if run_id in relevant_run_ids:
            run_results[run_id] = row
    if set(run_results) != relevant_run_ids:
        raise DivergenceAuditError("Evaluator pass lacks one or more divergent run results.")
    outcomes: list[AuditedDivergenceCase] = []
    labels: Counter[str] = Counter()
    for truth_free in truth_free_cases:
        pair = truth_free.pair
        event = divergence_events.get(pair.divergence_id)
        if event is None:
            raise DivergenceAuditError(
                f"Evaluator pass lacks divergence event {pair.divergence_id}."
            )
        event_pair = (
            _text(event["fixed_run_id"], "event fixed run ID"),
            _text(event["calibrated_run_id"], "event calibrated run ID"),
        )
        if event_pair != (pair.fixed_run_id, pair.calibrated_run_id):
            raise DivergenceAuditError("Evaluator divergence pair does not match Pass A.")
        label = _text(event["correctness_effect"], "correctness effect")
        if label not in {"helped", "hurt", "mixed", "tied"}:
            raise DivergenceAuditError(f"Unexpected evaluator outcome label: {label}")
        labels[label] += 1
        fixed_result = run_results[pair.fixed_run_id]
        calibrated_result = run_results[pair.calibrated_run_id]
        fixed_metrics = _metric_subset(_mapping(fixed_result["metrics"], "fixed metrics"))
        calibrated_metrics = _metric_subset(
            _mapping(calibrated_result["metrics"], "calibrated metrics")
        )
        evaluator = _mapping(event["evaluator_only"], "event evaluator block")
        hidden_truth = _text(evaluator["hidden_true_hypothesis"], "hidden true hypothesis")
        fixed_truth = _text(
            _mapping(fixed_result["evaluator_only"], "fixed evaluator block")[
                "hidden_true_hypothesis"
            ],
            "fixed hidden truth",
        )
        calibrated_truth = _text(
            _mapping(calibrated_result["evaluator_only"], "calibrated evaluator block")[
                "hidden_true_hypothesis"
            ],
            "calibrated hidden truth",
        )
        if hidden_truth != fixed_truth or hidden_truth != calibrated_truth:
            raise DivergenceAuditError("Evaluator truth differs within a paired case.")
        truth_payload = truth_free.to_dict()
        truth_hash = _stable_hash(truth_payload)
        outcomes.append(
            AuditedDivergenceCase(
                truth_free=truth_free,
                truth_free_sha256=truth_hash,
                evaluator_only=EvaluatorOutcome(
                    divergence_id=pair.divergence_id,
                    outcome_label=cast(OutcomeLabel, label),
                    hidden_true_hypothesis=hidden_truth,
                    fixed_metrics=fixed_metrics,
                    calibrated_metrics=calibrated_metrics,
                    metric_differences=_metric_differences(fixed_metrics, calibrated_metrics),
                ),
            )
        )
    expected_labels = {
        "helped": EXPECTED_HELPED_COUNT,
        "hurt": EXPECTED_HURT_COUNT,
        "mixed": EXPECTED_MIXED_COUNT,
        "tied": 0,
    }
    if len(outcomes) == EXPECTED_DIVERGENCE_COUNT and dict(labels) != {
        key: value for key, value in expected_labels.items() if value
    }:
        raise DivergenceAuditError(
            f"Frozen evaluator-label counts changed: observed {dict(labels)}."
        )
    return tuple(outcomes)


def _percentile(sorted_values: Sequence[float], quantile: float) -> float:
    if not sorted_values:
        raise DivergenceAuditError("Cannot calculate a percentile from no values.")
    position = (len(sorted_values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def _bootstrap_seed(key: Sequence[object]) -> int:
    payload = json.dumps(
        [BOOTSTRAP_MASTER_SEED, *key], sort_keys=True, separators=(",", ":")
    ).encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _bootstrap_ratio_ci(
    *,
    cases: Sequence[AuditedDivergenceCase],
    key: Sequence[object],
    numerator: Callable[[AuditedDivergenceCase], float],
    denominator: Callable[[AuditedDivergenceCase], float],
    resamples: int,
) -> tuple[float | None, float | None, int]:
    seeds = tuple(range(100))
    numerator_by_seed = [0.0] * 100
    denominator_by_seed = [0.0] * 100
    for item in cases:
        seed = item.truth_free.pair.seed
        numerator_by_seed[seed] += numerator(item)
        denominator_by_seed[seed] += denominator(item)
    rng = random.Random(_bootstrap_seed(key))
    values: list[float] = []
    for _ in range(resamples):
        numerator_total = 0.0
        denominator_total = 0.0
        for _ in seeds:
            selected = rng.randrange(100)
            numerator_total += numerator_by_seed[selected]
            denominator_total += denominator_by_seed[selected]
        if denominator_total > 0.0:
            values.append(numerator_total / denominator_total)
    if len(values) < BOOTSTRAP_MINIMUM_USABLE:
        return None, None, len(values)
    values.sort()
    return _percentile(values, 0.025), _percentile(values, 0.975), len(values)


def _matches_role(
    item: AuditedDivergenceCase, mechanism: Mechanism, role: Literal["primary", "any"]
) -> bool:
    classification = item.truth_free.classification
    if role == "primary":
        return classification.primary_mechanism == mechanism
    return mechanism == classification.primary_mechanism or mechanism in (
        classification.contributing_mechanisms
    )


def _outcome_matches(item: AuditedDivergenceCase, scope: str) -> bool:
    return scope == "all" or item.evaluator_only.outcome_label == scope


def _mechanism_summary_rows(
    cases: tuple[AuditedDivergenceCase, ...], *, resamples: int
) -> tuple[JsonObject, ...]:
    rows: list[JsonObject] = []
    roles: tuple[Literal["primary", "any"], ...] = ("primary", "any")
    for scope in ("all", "helped", "hurt", "mixed"):
        for role in roles:
            for mechanism in MECHANISMS:
                selected = [item for item in cases if _outcome_matches(item, scope)]
                count = sum(_matches_role(item, mechanism, role) for item in selected)
                denominator_count = len(selected)
                proportion = None if denominator_count == 0 else count / denominator_count

                def frequency_numerator(
                    item: AuditedDivergenceCase,
                    current_scope: str = scope,
                    current_role: Literal["primary", "any"] = role,
                    current_mechanism: Mechanism = mechanism,
                ) -> float:
                    return float(
                        _outcome_matches(item, current_scope)
                        and _matches_role(item, current_mechanism, current_role)
                    )

                def frequency_denominator(
                    item: AuditedDivergenceCase, current_scope: str = scope
                ) -> float:
                    return float(_outcome_matches(item, current_scope))

                low, high, usable = _bootstrap_ratio_ci(
                    cases=cases,
                    key=("mechanism-summary", scope, role, mechanism),
                    numerator=frequency_numerator,
                    denominator=frequency_denominator,
                    resamples=resamples,
                )
                rows.append(
                    {
                        "summary_kind": "mechanism_frequency",
                        "scope": scope,
                        "role": role,
                        "mechanism": mechanism,
                        "metric": None,
                        "count": count,
                        "denominator": denominator_count,
                        "proportion": proportion,
                        "mean": None,
                        "median": None,
                        "standard_deviation": None,
                        "confidence_interval_low": low,
                        "confidence_interval_high": high,
                        "usable_bootstrap_replicates": usable,
                        "confidence_interval_method": "paired-seed-block-percentile-bootstrap",
                    }
                )
    metric_names = (
        "negative_log_true_hypothesis_probability",
        "final_brier_score",
        "final_true_hypothesis_probability",
        "final_posterior_entropy",
        "confidently_wrong",
        "prediction_correct",
        "reached_sustained_80_confidence",
        "reached_sustained_95_confidence",
        "matched_evidence_pairs_completed",
        "redundant_experiments_selected",
        "decision_cost",
        "calibration_cost",
        "required_total_cost",
        "best_observed_objective",
    )
    for mechanism in MECHANISMS:
        mechanism_cases = [
            item for item in cases if item.truth_free.classification.primary_mechanism == mechanism
        ]
        if not mechanism_cases:
            continue
        for metric in metric_names:
            values = [
                float(item.evaluator_only.metric_differences[metric])
                for item in mechanism_cases
                if isinstance(item.evaluator_only.metric_differences.get(metric), (int, float))
            ]
            if not values:
                continue

            def metric_numerator(
                item: AuditedDivergenceCase,
                current_mechanism: Mechanism = mechanism,
                current_metric: str = metric,
            ) -> float:
                value = item.evaluator_only.metric_differences.get(current_metric)
                if (
                    item.truth_free.classification.primary_mechanism == current_mechanism
                    and isinstance(value, (int, float))
                ):
                    return float(value)
                return 0.0

            def metric_denominator(
                item: AuditedDivergenceCase,
                current_mechanism: Mechanism = mechanism,
                current_metric: str = metric,
            ) -> float:
                return float(
                    item.truth_free.classification.primary_mechanism == current_mechanism
                    and isinstance(
                        item.evaluator_only.metric_differences.get(current_metric),
                        (int, float),
                    )
                )

            low, high, usable = _bootstrap_ratio_ci(
                cases=cases,
                key=("mechanism-metric", mechanism, metric),
                numerator=metric_numerator,
                denominator=metric_denominator,
                resamples=resamples,
            )
            rows.append(
                {
                    "summary_kind": "mean_metric_change_calibrated_minus_fixed",
                    "scope": "all",
                    "role": "primary",
                    "mechanism": mechanism,
                    "metric": metric,
                    "count": len(values),
                    "denominator": len(values),
                    "proportion": None,
                    "mean": statistics.fmean(values),
                    "median": statistics.median(values),
                    "standard_deviation": statistics.stdev(values) if len(values) > 1 else 0.0,
                    "confidence_interval_low": low,
                    "confidence_interval_high": high,
                    "usable_bootstrap_replicates": usable,
                    "confidence_interval_method": "paired-seed-block-percentile-bootstrap",
                }
            )
    return tuple(rows)


def _mechanism_condition_rows(
    cases: tuple[AuditedDivergenceCase, ...], protocol: Mapping[str, Any]
) -> tuple[JsonObject, ...]:
    world_payload = _mapping(protocol["worlds"], "world protocol")
    world_ids = tuple(
        sorted(
            _text(_mapping(item, "world configuration")["world_id"], "world ID")
            for item in _sequence(world_payload["configurations"], "world configurations")
        )
    )
    dimensions = {
        "world": world_ids,
        "budget": ("short", "large"),
        "policy": ("information_gain", "lookahead_information_gain"),
    }
    rows: list[JsonObject] = []
    for dimension, values in dimensions.items():
        for value in values:
            for scope in ("all", "helped", "hurt", "mixed"):
                denominator_cases = [
                    item
                    for item in cases
                    if _condition_value(item, dimension) == value and _outcome_matches(item, scope)
                ]
                for role in ("primary", "any"):
                    for mechanism in MECHANISMS:
                        count = sum(
                            _matches_role(item, mechanism, role) for item in denominator_cases
                        )
                        denominator = len(denominator_cases)
                        rows.append(
                            {
                                "dimension": dimension,
                                "condition": value,
                                "scope": scope,
                                "role": role,
                                "mechanism": mechanism,
                                "count": count,
                                "denominator": denominator,
                                "proportion": None if denominator == 0 else count / denominator,
                            }
                        )
    return tuple(rows)


def _condition_value(item: AuditedDivergenceCase, dimension: str) -> str:
    pair = item.truth_free.pair
    if dimension == "world":
        return pair.world_id
    if dimension == "budget":
        return pair.budget_label
    if dimension == "policy":
        return pair.policy
    raise DivergenceAuditError(f"Unknown condition dimension: {dimension}")


def _sigma_ratio_bin(value: float) -> str:
    if value < 2.0:
        return "[1,2)"
    if value < 4.0:
        return "[2,4)"
    if value < 8.0:
        return "[4,8)"
    return "[8,infinity)"


def _entropy_bin(value: float) -> str:
    if value < 0.25:
        return "[0,0.25)"
    if value < 0.75:
        return "[0.25,0.75)"
    if value < 1.25:
        return "[0.75,1.25)"
    return "[1.25,log2(3)+tau]"


def _remaining_budget_bin(value: float) -> str:
    if value <= 0.25:
        return "[0,0.25]"
    if value <= 0.50:
        return "(0.25,0.50]"
    if value <= 0.75:
        return "(0.50,0.75]"
    return "(0.75,1.00]"


def _predivergence_matched_state(case: TruthFreeDivergenceCase) -> str:
    open_groups: set[str] = set()
    for event in case.sequence.fixed_pair_events:
        if _integer(event["step"], "pair event step") >= case.pair.first_divergence_step:
            continue
        group = _text(event["comparison_group_id"], "comparison group ID")
        if event["effect"] == "opens_pair":
            open_groups.add(group)
        elif event["effect"] == "completes_pair":
            open_groups.discard(group)
    if not open_groups:
        return "no_open_pair"
    if len(open_groups) == 1:
        return "one_open_pair"
    return "multiple_open_pairs"


def _harm_attributes(item: AuditedDivergenceCase) -> dict[str, set[str]]:
    case = item.truth_free
    cc = case.replay("CC")
    selected = cc.winner
    snapshots = {entry.comparison_group_id: entry for entry in case.calibrated_snapshots}
    snapshot = snapshots.get(selected.comparison_group_id)
    sigma_ratio = 1.0 if snapshot is None else snapshot.estimated_sigma / FIXED_SIGMA
    entropy = _entropy(tuple(value for _, value in case.calibrated_posterior))
    remaining_fraction = 1.0
    fixed_effect = case.replay("FF").winner.action_effect
    calibrated_effect = selected.action_effect

    def normalize_effect(value: str) -> str:
        return value if value in {"opens_pair", "completes_pair"} else "neither"

    pressure = all(
        plan.expected_total_information_gain <= NUMERICAL_TOLERANCE for plan in cc.ranked_plans
    )
    any_mechanisms = {
        case.classification.primary_mechanism,
        *case.classification.contributing_mechanisms,
    }
    return {
        "world": {case.pair.world_id},
        "budget": {case.pair.budget_label},
        "policy": {case.pair.policy},
        "sigma_ratio": {_sigma_ratio_bin(sigma_ratio)},
        "posterior_entropy": {_entropy_bin(entropy)},
        "fixed_first_action_type": {normalize_effect(fixed_effect)},
        "calibrated_first_action_type": {normalize_effect(calibrated_effect)},
        "matched_pair_state": {_predivergence_matched_state(case)},
        "near_budget_exhaustion": {str(remaining_fraction <= 0.25).lower()},
        "structural_budget_pressure": {str(pressure).lower()},
        "final_set_relation": {case.sequence.set_relation},
        "remaining_budget_fraction": {_remaining_budget_bin(remaining_fraction)},
        "primary_mechanism": {case.classification.primary_mechanism},
        "any_mechanism": set(any_mechanisms),
        "first_divergence_step": {str(case.pair.first_divergence_step)},
    }


def _harm_strata(protocol: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    worlds = tuple(
        sorted(
            _text(_mapping(item, "world configuration")["world_id"], "world ID")
            for item in _sequence(
                _mapping(protocol["worlds"], "worlds")["configurations"],
                "world configurations",
            )
        )
    )
    dimensions: dict[str, tuple[str, ...]] = {
        "world": worlds,
        "budget": ("short", "large"),
        "policy": ("information_gain", "lookahead_information_gain"),
        "sigma_ratio": ("[1,2)", "[2,4)", "[4,8)", "[8,infinity)"),
        "posterior_entropy": (
            "[0,0.25)",
            "[0.25,0.75)",
            "[0.75,1.25)",
            "[1.25,log2(3)+tau]",
        ),
        "fixed_first_action_type": ("opens_pair", "completes_pair", "neither"),
        "calibrated_first_action_type": ("opens_pair", "completes_pair", "neither"),
        "matched_pair_state": ("no_open_pair", "one_open_pair", "multiple_open_pairs"),
        "near_budget_exhaustion": ("true", "false"),
        "structural_budget_pressure": ("true", "false"),
        "final_set_relation": (
            "SAME_SET_DIFFERENT_ORDER",
            "PARTIAL_OVERLAP",
            "DISJOINT",
        ),
        "remaining_budget_fraction": (
            "[0,0.25]",
            "(0.25,0.50]",
            "(0.50,0.75]",
            "(0.75,1.00]",
        ),
        "primary_mechanism": MECHANISMS,
        "any_mechanism": MECHANISMS,
        "first_divergence_step": ("1",),
    }
    return tuple((dimension, value) for dimension, values in dimensions.items() for value in values)


def _harm_bootstrap_intervals(
    *,
    cases: tuple[AuditedDivergenceCase, ...],
    in_stratum: Callable[[AuditedDivergenceCase], bool],
    key: tuple[object, ...],
    resamples: int,
) -> tuple[dict[str, tuple[float | None, float | None]], int]:
    arrays = {name: [0.0] * 100 for name in ("harm_in", "count_in", "harm_out", "count_out")}
    for item in cases:
        seed = item.truth_free.pair.seed
        inside = in_stratum(item)
        harmed = item.evaluator_only.outcome_label == "hurt"
        arrays["count_in" if inside else "count_out"][seed] += 1.0
        if harmed:
            arrays["harm_in" if inside else "harm_out"][seed] += 1.0
    rng = random.Random(_bootstrap_seed(key))
    values: dict[str, list[float]] = defaultdict(list)
    for _ in range(resamples):
        totals = {name: 0.0 for name in arrays}
        for _ in range(100):
            selected = rng.randrange(100)
            for name, array in arrays.items():
                totals[name] += array[selected]
        total_harms = totals["harm_in"] + totals["harm_out"]
        total_cases = totals["count_in"] + totals["count_out"]
        harm_share = None if total_harms == 0 else totals["harm_in"] / total_harms
        harm_rate = None if totals["count_in"] == 0 else totals["harm_in"] / totals["count_in"]
        stratum_share = None if total_cases == 0 else totals["count_in"] / total_cases
        lift = (
            None
            if harm_share is None or stratum_share is None or stratum_share == 0
            else harm_share / stratum_share
        )
        complement_rate = (
            None if totals["count_out"] == 0 else totals["harm_out"] / totals["count_out"]
        )
        risk_difference = (
            None if harm_rate is None or complement_rate is None else harm_rate - complement_rate
        )
        risk_ratio = (
            None
            if harm_rate is None or complement_rate is None or complement_rate == 0
            else harm_rate / complement_rate
        )
        for name, value in (
            ("harmful_case_share", harm_share),
            ("conditional_harm_rate", harm_rate),
            ("concentration_lift", lift),
            ("risk_difference", risk_difference),
            ("risk_ratio", risk_ratio),
        ):
            if value is not None and math.isfinite(value):
                values[name].append(value)
    result: dict[str, tuple[float | None, float | None]] = {}
    minimum_usable = min((len(item) for item in values.values()), default=0)
    for name in (
        "harmful_case_share",
        "conditional_harm_rate",
        "concentration_lift",
        "risk_difference",
        "risk_ratio",
    ):
        samples = sorted(values.get(name, []))
        if len(samples) < BOOTSTRAP_MINIMUM_USABLE:
            result[name] = (None, None)
        else:
            result[name] = (_percentile(samples, 0.025), _percentile(samples, 0.975))
    return result, minimum_usable


def _harm_concentration_rows(
    cases: tuple[AuditedDivergenceCase, ...],
    protocol: Mapping[str, Any],
    *,
    resamples: int,
) -> tuple[JsonObject, ...]:
    attributes = {item.truth_free.pair.case_id: _harm_attributes(item) for item in cases}
    total_harms = sum(item.evaluator_only.outcome_label == "hurt" for item in cases)
    rows: list[JsonObject] = []
    for dimension, value in _harm_strata(protocol):

        def inside(item: AuditedDivergenceCase, d: str = dimension, v: str = value) -> bool:
            return v in attributes[item.truth_free.pair.case_id][d]

        selected = [item for item in cases if inside(item)]
        harm_count = sum(item.evaluator_only.outcome_label == "hurt" for item in selected)
        complement = [item for item in cases if not inside(item)]
        complement_harms = sum(item.evaluator_only.outcome_label == "hurt" for item in complement)
        divergent_count = len(selected)
        harm_share = None if total_harms == 0 else harm_count / total_harms
        harm_rate = None if divergent_count == 0 else harm_count / divergent_count
        stratum_share = divergent_count / len(cases)
        lift = None if harm_share is None or stratum_share == 0 else harm_share / stratum_share
        complement_rate = None if not complement else complement_harms / len(complement)
        risk_difference = (
            None if harm_rate is None or complement_rate is None else harm_rate - complement_rate
        )
        risk_ratio = (
            None
            if harm_rate is None or complement_rate is None or complement_rate == 0
            else harm_rate / complement_rate
        )
        intervals, usable = _harm_bootstrap_intervals(
            cases=cases,
            in_stratum=inside,
            key=("harm-concentration", dimension, value),
            resamples=resamples,
        )
        row: JsonObject = {
            "dimension": dimension,
            "stratum": value,
            "divergent_count": divergent_count,
            "harm_count": harm_count,
            "harmful_case_share": harm_share,
            "conditional_harm_rate": harm_rate,
            "concentration_lift": lift,
            "risk_difference": risk_difference,
            "risk_ratio": risk_ratio,
            "usable_bootstrap_replicates": usable,
            "confidence_interval_method": "paired-seed-block-percentile-bootstrap",
        }
        for metric, (low, high) in intervals.items():
            row[f"{metric}_ci_low"] = low
            row[f"{metric}_ci_high"] = high
        rows.append(row)
    return tuple(rows)


def _score_decomposition_rows(cases: tuple[AuditedDivergenceCase, ...]) -> tuple[JsonObject, ...]:
    rows: list[JsonObject] = []
    for audited in cases:
        case = audited.truth_free
        decomposition = case.decomposition
        fixed_id = _text(decomposition["fixed_candidate_id"], "fixed candidate ID")
        calibrated_id = _text(decomposition["calibrated_candidate_id"], "calibrated candidate ID")
        margins = _mapping(decomposition["margins"], "score margins")
        immediate = _mapping(decomposition["immediate_margins"], "immediate margins")
        future = _mapping(decomposition["future_margins"], "future margins")
        cost = _mapping(decomposition["expected_cost_margins"], "cost margins")
        ratio = _mapping(decomposition["information_gain_per_cost_margins"], "ratio margins")
        stages = _mapping(decomposition["ranking_stages"], "ranking stages")
        for replay in case.replays:
            fixed = replay.plan(fixed_id)
            calibrated = replay.plan(calibrated_id)
            rows.append(
                {
                    "case_id": case.pair.case_id,
                    "world_id": case.pair.world_id,
                    "seed": case.pair.seed,
                    "budget_label": case.pair.budget_label,
                    "policy": case.pair.policy,
                    "outcome_label": audited.evaluator_only.outcome_label,
                    "context": replay.context,
                    "posterior_probabilities": json.dumps(
                        dict(
                            zip(
                                replay.hypothesis_ids,
                                replay.posterior_probabilities,
                                strict=True,
                            )
                        ),
                        sort_keys=True,
                    ),
                    "sigma_by_group": json.dumps(dict(replay.sigma_by_group), sort_keys=True),
                    "winner": replay.winner.candidate_id,
                    "fixed_candidate_id": fixed_id,
                    "calibrated_candidate_id": calibrated_id,
                    "fixed_candidate_score": fixed.expected_total_information_gain,
                    "calibrated_candidate_score": calibrated.expected_total_information_gain,
                    "total_score_margin": margins[replay.context],
                    "immediate_margin": immediate[replay.context],
                    "future_margin": future[replay.context],
                    "expected_cost_margin": cost[replay.context],
                    "information_gain_per_cost_margin": ratio[replay.context],
                    "belief_state_contribution": decomposition["belief_state_contribution"],
                    "sigma_likelihood_contribution": decomposition["sigma_likelihood_contribution"],
                    "belief_sigma_interaction": decomposition["belief_sigma_interaction"],
                    "reconciliation_error": decomposition["reconciliation_error"],
                    "temporal_reconciliation_error": decomposition["temporal_reconciliation_error"],
                    "ranking_stage": stages[replay.context],
                    "fixed_branch_tree_sha256": _stable_hash(
                        fixed.to_dict(replay.hypothesis_ids)["branches"]
                    ),
                    "calibrated_branch_tree_sha256": _stable_hash(
                        calibrated.to_dict(replay.hypothesis_ids)["branches"]
                    ),
                    "fixed_branches": json.dumps(
                        fixed.to_dict(replay.hypothesis_ids)["branches"], sort_keys=True
                    ),
                    "calibrated_branches": json.dumps(
                        calibrated.to_dict(replay.hypothesis_ids)["branches"],
                        sort_keys=True,
                    ),
                    "all_branches_budget_feasible": all(
                        branch.budget_feasible
                        for plan in replay.ranked_plans
                        for branch in plan.branches
                    ),
                    "ranked_candidate_scores": json.dumps(
                        [
                            {
                                "candidate_id": item.candidate_id,
                                "immediate_information_gain": item.immediate_information_gain,
                                "delayed_information_gain": item.delayed_information_gain,
                                "expected_total_information_gain": (
                                    item.expected_total_information_gain
                                ),
                                "expected_total_cost": item.expected_total_cost,
                                "information_gain_per_expected_cost": (
                                    item.information_gain_per_expected_cost
                                ),
                            }
                            for item in replay.ranked_plans
                        ],
                        sort_keys=True,
                    ),
                    "tolerance": NUMERICAL_TOLERANCE,
                }
            )
    return tuple(rows)


def _sequence_rows(cases: tuple[AuditedDivergenceCase, ...]) -> tuple[JsonObject, ...]:
    rows: list[JsonObject] = []
    for audited in cases:
        case = audited.truth_free
        sequence = case.sequence
        rows.append(
            {
                "case_id": case.pair.case_id,
                "world_id": case.pair.world_id,
                "seed": case.pair.seed,
                "budget_label": case.pair.budget_label,
                "policy": case.pair.policy,
                "outcome_label": audited.evaluator_only.outcome_label,
                "first_divergence_step": case.pair.first_divergence_step,
                "fixed_sequence": json.dumps(sequence.fixed_sequence),
                "calibrated_sequence": json.dumps(sequence.calibrated_sequence),
                "fixed_action_effects": json.dumps(sequence.fixed_action_effects),
                "calibrated_action_effects": json.dumps(sequence.calibrated_action_effects),
                "fixed_pair_events": json.dumps(sequence.fixed_pair_events, sort_keys=True),
                "calibrated_pair_events": json.dumps(
                    sequence.calibrated_pair_events, sort_keys=True
                ),
                "fixed_first_evidence_step": sequence.fixed_first_evidence_step,
                "calibrated_first_evidence_step": sequence.calibrated_first_evidence_step,
                "fixed_first_evidence_cost": sequence.fixed_first_evidence_cost,
                "calibrated_first_evidence_cost": sequence.calibrated_first_evidence_cost,
                "fixed_cost_before_first_evidence": (sequence.fixed_cost_before_first_evidence),
                "calibrated_cost_before_first_evidence": (
                    sequence.calibrated_cost_before_first_evidence
                ),
                "fixed_remaining_budget_after_first_evidence": (
                    sequence.fixed_remaining_budget_after_first_evidence
                ),
                "calibrated_remaining_budget_after_first_evidence": (
                    sequence.calibrated_remaining_budget_after_first_evidence
                ),
                "fixed_evidence_count": sequence.fixed_evidence_count,
                "calibrated_evidence_count": sequence.calibrated_evidence_count,
                "fixed_evidence_order": json.dumps(sequence.fixed_evidence_order),
                "calibrated_evidence_order": json.dumps(sequence.calibrated_evidence_order),
                "fixed_sigma_source_order": json.dumps(sequence.fixed_sigma_source_order),
                "calibrated_sigma_source_order": json.dumps(sequence.calibrated_sigma_source_order),
                "fixed_final_set": json.dumps(sequence.fixed_final_set),
                "calibrated_final_set": json.dumps(sequence.calibrated_final_set),
                "intersection": json.dumps(sequence.intersection),
                "union": json.dumps(sequence.union),
                "set_relation": sequence.set_relation,
                "jaccard_similarity": sequence.jaccard_similarity,
                "order_similarity": sequence.order_similarity,
                "sequence_edit_distance": sequence.sequence_edit_distance,
                "fixed_commitment_step": sequence.fixed_commitment_step,
                "calibrated_commitment_step": sequence.calibrated_commitment_step,
                "calibrated_delayed_commitment": sequence.calibrated_delayed_commitment,
                "pair_completion_delay": json.dumps(sequence.pair_completion_delay, sort_keys=True),
                "budget_crowd_out": json.dumps(sequence.budget_crowd_out, sort_keys=True),
                "fixed_decision_cost": sequence.fixed_decision_cost,
                "calibrated_decision_cost": sequence.calibrated_decision_cost,
                "decision_cost_difference": (
                    sequence.calibrated_decision_cost - sequence.fixed_decision_cost
                ),
                "fixed_stop_reason": sequence.fixed_stop_reason,
                "calibrated_stop_reason": sequence.calibrated_stop_reason,
            }
        )
    return tuple(rows)


def _dominance_interval(
    *,
    cases: tuple[AuditedDivergenceCase, ...],
    first: Mechanism,
    second: Mechanism,
    resamples: int,
) -> tuple[float | None, float | None, int]:
    return _bootstrap_ratio_ci(
        cases=cases,
        key=("dominance", first, second),
        numerator=lambda item: (
            float(item.evaluator_only.outcome_label == "hurt" and _matches_role(item, first, "any"))
            - float(
                item.evaluator_only.outcome_label == "hurt" and _matches_role(item, second, "any")
            )
        ),
        denominator=lambda item: float(item.evaluator_only.outcome_label == "hurt"),
        resamples=resamples,
    )


def _recommendation(
    *,
    cases: tuple[AuditedDivergenceCase, ...],
    audit_complete: bool,
    resamples: int,
) -> tuple[str, JsonObject]:
    if not audit_complete:
        return (
            "Repair or reconstruct the divergence-audit instrumentation, then rerun the "
            "same frozen audit.",
            {"rule": "audit_incomplete", "dominant_mechanism": None},
        )
    if any(
        item.truth_free.classification.primary_mechanism == "PLANNER_MODEL_MISMATCH"
        or "PLANNER_MODEL_MISMATCH" in item.truth_free.classification.contributing_mechanisms
        for item in cases
    ):
        return (
            "Correct the planner-belief compatibility defect and replay the unchanged "
            "frozen closed-loop protocol.",
            {"rule": "planner_model_mismatch", "dominant_mechanism": None},
        )
    harmful = [item for item in cases if item.evaluator_only.outcome_label == "hurt"]
    candidates = tuple(item for item in MECHANISMS if item != "NO_STABLE_MECHANISM")
    prevalence = {
        mechanism: sum(_matches_role(item, mechanism, "any") for item in harmful) / len(harmful)
        for mechanism in candidates
    }
    ordered = sorted(candidates, key=lambda item: (-prevalence[item], MECHANISMS.index(item)))
    first, second = ordered[:2]
    low, high, usable = _dominance_interval(
        cases=cases,
        first=first,
        second=second,
        resamples=resamples,
    )
    dominant = prevalence[first] >= DOMINANCE_PREVALENCE and low is not None and low > 0.0
    details: JsonObject = {
        "rule": "dominant_measured_harmful_mechanism" if dominant else "no_stable_dominance",
        "candidate_mechanism": first,
        "runner_up": second,
        "candidate_prevalence": prevalence[first],
        "runner_up_prevalence": prevalence[second],
        "prevalence_difference_ci_low": low,
        "prevalence_difference_ci_high": high,
        "usable_bootstrap_replicates": usable,
        "required_prevalence": DOMINANCE_PREVALENCE,
        "required_lower_ci_bound": 0.0,
        "dominant_mechanism": first if dominant else None,
    }
    if not dominant:
        return (
            "Replicate the closed-loop evaluation on a broader predeclared seed and world "
            "set before changing an algorithm.",
            details,
        )
    mapping: dict[Mechanism, str] = {
        "BUDGET_CROWD_OUT": (
            "Evaluate a predeclared cost-aware decision revision against the frozen controllers."
        ),
        "CONSERVATIVE_NONCOMMITMENT": (
            "Run a commitment-and-stopping study without changing the belief model."
        ),
        "SCORE_FLATTENING": (
            "Run a calibrated-sigma acquisition-sensitivity study focused on candidate-score "
            "compression and group-relative ranking."
        ),
        "GROUP_SIGMA_REORDERING": (
            "Run a calibrated-sigma acquisition-sensitivity study focused on candidate-score "
            "compression and group-relative ranking."
        ),
        "BELIEF_STATE_REORDERING": "Run a posterior-sensitivity experiment-selection study.",
        "BELIEF_SIGMA_INTERACTION": ("Run a joint belief-likelihood planner-compatibility study."),
        "PAIR_COMPLETION_DELAY": (
            "Evaluate a predeclared matched-pair completion sequencing rule."
        ),
        "PAIR_OPENER_CHANGE": (
            "Evaluate comparison-group opener selection under the unchanged two-step horizon."
        ),
        "SAME_SET_DIFFERENT_ORDER": "Run a prequential evidence-order sensitivity study.",
        "COST_TIEBREAK_CHANGE": "Run a deterministic tie-break robustness study.",
        "PLANNER_MODEL_MISMATCH": (
            "Correct the planner-belief compatibility defect and replay the unchanged frozen "
            "closed-loop protocol."
        ),
        "NO_STABLE_MECHANISM": (
            "Replicate the closed-loop evaluation on a broader predeclared seed and world set "
            "before changing an algorithm."
        ),
    }
    return mapping[first], details


def _current_artifact_stats(root: Path) -> tuple[tuple[str, int, int], ...]:
    return tuple(
        (path.name, path.stat().st_size, path.stat().st_mtime_ns)
        for path in sorted(root.iterdir(), key=lambda item: item.name)
        if path.is_file()
    )


def _audit_checks(
    *,
    workspace: _AuditWorkspace,
    cases: tuple[AuditedDivergenceCase, ...],
    staging_sha256: str,
    extracted_sha256: str,
    compatibility: Mapping[str, Any],
) -> JsonObject:
    primary_count = sum(
        item.truth_free.classification.primary_mechanism in MECHANISMS for item in cases
    )
    truth_free_fields = {item.name for item in fields(TruthFreeDivergenceCase)}
    forbidden_truth_fields = {
        "hidden_true_hypothesis",
        "outcome_label",
        "correctness_effect",
        "nll",
        "brier",
    }
    set_relations = Counter(item.truth_free.sequence.set_relation for item in cases)
    condition_counts = Counter(
        (item.truth_free.pair.world_id, item.truth_free.pair.budget_label) for item in cases
    )
    checks: JsonObject = {
        "population_exactly_189": len(cases) == EXPECTED_DIVERGENCE_COUNT,
        "every_case_has_one_primary_mechanism": primary_count == len(cases),
        "truth_free_type_excludes_evaluator_fields": not truth_free_fields.intersection(
            forbidden_truth_fields
        ),
        "classification_precedes_evaluator_join": staging_sha256 == extracted_sha256,
        "staging_sha256": staging_sha256,
        "extracted_truth_free_sha256": extracted_sha256,
        "all_score_decompositions_reconcile": all(
            _number(item.truth_free.decomposition["reconciliation_error"], "error")
            <= NUMERICAL_TOLERANCE
            and _number(item.truth_free.decomposition["temporal_reconciliation_error"], "error")
            <= NUMERICAL_TOLERANCE
            for item in cases
        ),
        "planner_compatibility_passed": compatibility["overall_status"] == "PASS",
        "no_forbidden_input_opened": not set(workspace.ledger.pass_a_files).intersection(
            FORBIDDEN_INPUT_FILENAMES
        )
        and not set(workspace.ledger.pass_b_files).intersection(FORBIDDEN_INPUT_FILENAMES),
        "source_artifacts_unchanged_during_audit": workspace.source_artifact_stats
        == _current_artifact_stats(workspace.input_directory),
        "frozen_set_relation_counts_match": set_relations
        == Counter(
            {
                "SAME_SET_DIFFERENT_ORDER": 90,
                "PARTIAL_OVERLAP": 5,
                "DISJOINT": 94,
            }
        ),
        "frozen_condition_counts_match": condition_counts
        == Counter(
            {
                ("adverse_noisy_observations", "short"): 42,
                ("adverse_noisy_observations", "large"): 42,
                ("asymmetric_experiment_costs", "short"): 27,
                ("asymmetric_experiment_costs", "large"): 28,
                ("no_optimizer_advantage", "short"): 25,
                ("no_optimizer_advantage", "large"): 25,
            }
        ),
        "all_divergences_at_frozen_step_and_policy": all(
            item.truth_free.pair.first_divergence_step == 1
            and item.truth_free.pair.policy == "lookahead_information_gain"
            for item in cases
        ),
        "classification_rule_version": CLASSIFICATION_RULE_VERSION,
        "numerical_tolerance": NUMERICAL_TOLERANCE,
    }
    boolean_values = [value for value in checks.values() if isinstance(value, bool)]
    checks["all_prewrite_acceptance_checks_passed"] = all(boolean_values)
    return checks


def _truth_free_stream_bytes(cases: Sequence[TruthFreeDivergenceCase]) -> bytes:
    return b"".join(
        _json_line({"case_id": item.pair.case_id, "truth_free": item.to_dict()})
        for item in sorted(
            cases,
            key=lambda item: (
                item.pair.world_id,
                item.pair.seed,
                item.pair.budget_label,
                item.pair.policy,
                item.pair.case_id,
            ),
        )
    )


def run_divergence_audit(
    *,
    input_directory: Path,
    repository_root: Path,
    generated_at: str | None = None,
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES,
) -> DivergenceAuditResult:
    """Run the frozen audit without executing a policy trajectory or observation oracle."""

    if bootstrap_resamples <= 0:
        raise ValueError("Bootstrap resamples must be positive.")
    workspace = _load_workspace(
        input_directory=input_directory,
        repository_root=repository_root,
        expected_population=EXPECTED_DIVERGENCE_COUNT,
    )
    truth_free_cases = _construct_truth_free_cases(workspace)
    if len(truth_free_cases) != EXPECTED_DIVERGENCE_COUNT:
        raise DivergenceAuditError("Pass A did not classify exactly 189 cases.")
    staging_bytes = _truth_free_stream_bytes(truth_free_cases)
    with tempfile.TemporaryDirectory(prefix="rde-divergence-pass-a-") as temporary:
        staging_path = Path(temporary) / "truth-free-classifications.jsonl"
        staging_path.write_bytes(staging_bytes)
        staging_sha256 = _sha256(staging_path)
        workspace.ledger.close_pass_a(staging_sha256)
        reader = _ArtifactReader(input_directory, workspace.ledger)
        cases = _join_evaluator_outcomes(
            workspace=workspace,
            truth_free_cases=truth_free_cases,
            reader=reader,
        )
        extracted_bytes = _truth_free_stream_bytes(tuple(item.truth_free for item in cases))
        extracted_sha256 = hashlib.sha256(extracted_bytes).hexdigest()
        if extracted_sha256 != staging_sha256:
            raise DivergenceAuditError("Evaluator join altered truth-free classifications.")

    compatibility = workspace.compatibility.to_dict(source_checks=workspace.source_checks)
    mechanism_rows = _mechanism_summary_rows(cases, resamples=bootstrap_resamples)
    condition_rows = _mechanism_condition_rows(cases, workspace.protocol)
    score_rows = _score_decomposition_rows(cases)
    sequence_rows = _sequence_rows(cases)
    harm_rows = _harm_concentration_rows(
        cases,
        workspace.protocol,
        resamples=bootstrap_resamples,
    )
    checks = _audit_checks(
        workspace=workspace,
        cases=cases,
        staging_sha256=staging_sha256,
        extracted_sha256=extracted_sha256,
        compatibility=compatibility,
    )
    audit_complete = _boolean(
        checks["all_prewrite_acceptance_checks_passed"], "prewrite audit acceptance"
    )
    recommendation, recommendation_details = _recommendation(
        cases=cases,
        audit_complete=audit_complete,
        resamples=bootstrap_resamples,
    )
    checks["recommendation_rule"] = recommendation_details
    access_payload: JsonObject = {
        "classification_input_type": "TruthFreeDivergenceCase",
        "classifier_fields": sorted(item.name for item in fields(TruthFreeDivergenceCase)),
        "pass_a_files": sorted(set(workspace.ledger.pass_a_files)),
        "pass_b_files": sorted(set(workspace.ledger.pass_b_files)),
        "pass_a_closed_before_pass_b": workspace.ledger.pass_a_closed,
        "pass_a_staging_sha256": workspace.ledger.pass_a_staging_sha256,
        "forbidden_files": sorted(FORBIDDEN_INPUT_FILENAMES),
        "forbidden_files_accessed": sorted(
            set((*workspace.ledger.pass_a_files, *workspace.ledger.pass_b_files)).intersection(
                FORBIDDEN_INPUT_FILENAMES
            )
        ),
        "outcome_labels_available_to_classifier": False,
        "hidden_truth_available_to_scoring_adapter": False,
        "oracle_available_to_scoring_adapter": False,
        "persistence_available_to_scoring_adapter": False,
    }
    return DivergenceAuditResult(
        input_directory=input_directory,
        repository_root=repository_root,
        generated_at=generated_at or datetime.now(UTC).isoformat(),
        bootstrap_resamples=bootstrap_resamples,
        cases=tuple(
            sorted(
                cases,
                key=lambda item: (
                    item.truth_free.pair.world_id,
                    item.truth_free.pair.seed,
                    item.truth_free.pair.budget_label,
                    item.truth_free.pair.policy,
                    item.truth_free.pair.case_id,
                ),
            )
        ),
        mechanism_summary_rows=mechanism_rows,
        mechanism_condition_rows=condition_rows,
        score_rows=score_rows,
        sequence_rows=sequence_rows,
        harm_rows=harm_rows,
        compatibility=compatibility,
        audit_checks=checks,
        recommendation=recommendation,
        source_artifact_hashes=workspace.source_artifact_hashes,
        design_hashes=workspace.design_hashes,
        access_ledger=access_payload,
        staging_sha256=staging_sha256,
        extracted_truth_free_sha256=extracted_sha256,
    )


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m research_decision_engine.benchmarks.divergence_audit"
    )
    parser.add_argument(
        "--input-directory",
        type=Path,
        default=Path("closed-loop-evaluation-v1-100-seeds"),
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("divergence-audit-v1-189-cases"),
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    return parser


def main() -> int:
    args = _build_cli_parser().parse_args()
    from research_decision_engine.benchmarks.divergence_reporting import (
        render_divergence_terminal_summary,
        write_divergence_outputs,
    )

    result = run_divergence_audit(
        input_directory=args.input_directory.resolve(),
        repository_root=args.repository_root.resolve(),
    )
    paths = write_divergence_outputs(result, args.output_directory.resolve())
    print(render_divergence_terminal_summary(result, paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
