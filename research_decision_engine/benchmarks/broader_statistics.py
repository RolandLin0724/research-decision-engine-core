"""Frozen deterministic statistics and three-valued decision logic."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from typing import Final, Literal, cast

from research_decision_engine.benchmarks.broader_protocol import (
    FULL_SEEDS,
    PROTOCOL_VERSION,
    canonical_json_bytes,
    load_protocol_snapshot,
    protocol_hash,
)

MASK64: Final = (1 << 64) - 1
BOOTSTRAP_REPLICATES: Final = 10_000
SIGN_FLIP_REPLICATES: Final = 10_000


class GateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class DecisionBoolean:
    value: bool | None
    resolution_status: Literal["resolved", "inconclusive"]
    source_ids: tuple[str, ...]

    @classmethod
    def from_status(cls, status: GateStatus, *source_ids: str) -> DecisionBoolean:
        if status is GateStatus.INCONCLUSIVE:
            return cls(None, "inconclusive", tuple(source_ids))
        return cls(status is GateStatus.PASS, "resolved", tuple(source_ids))

    @property
    def status(self) -> GateStatus:
        if self.resolution_status == "inconclusive":
            return GateStatus.INCONCLUSIVE
        return GateStatus.PASS if self.value else GateStatus.FAIL


@dataclass(frozen=True, slots=True)
class ActionTuple:
    policy_scope: str
    mechanism_id: str
    decision_contrast_id: str
    confirmatory_contrast_id: str


@dataclass(frozen=True, slots=True)
class VetoResult:
    source_tuple: ActionTuple
    veto_status: Literal["VETOED", "NOT_VETOED", "INCONCLUSIVE"]


@dataclass(frozen=True, slots=True)
class ActionPartition:
    vetoed_tuples: tuple[ActionTuple, ...]
    surviving_tuples: tuple[ActionTuple, ...]
    veto_complete: DecisionBoolean


@dataclass(frozen=True, slots=True)
class BranchDecision:
    branch_id: str
    recommendation: str
    branch_matches: tuple[tuple[str, str], ...]
    gate_status: GateStatus


@dataclass(frozen=True, slots=True)
class HolmInput:
    statistical_hypothesis_id: str
    p_raw: float | None
    estimable: bool


@dataclass(frozen=True, slots=True)
class HolmResult:
    statistical_hypothesis_id: str
    p_raw: float | None
    p_adjusted: float | None
    holm_rank: int
    result_status: Literal["ESTIMATED", "INCONCLUSIVE"]


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    estimates: tuple[float, ...]
    null_replicates: int
    ci_low: float | None
    ci_high: float | None
    status: GateStatus


@dataclass(frozen=True, slots=True)
class SignFlipResult:
    observed_statistic: float
    extreme_count: int | None
    p_raw: float | None
    status: GateStatus


@dataclass(frozen=True, slots=True)
class BootstrapReplicate:
    contrast_id: str
    replicate_index: int
    seed_preimage: bytes
    seed_digest: bytes
    seed: int
    sampled_seed_ids: tuple[int, ...]
    estimate: float | None
    failure_code: str | None


@dataclass(frozen=True, slots=True)
class SignFlipReplicate:
    contrast_id: str
    replicate_index: int
    seed_preimage: bytes
    seed_digest: bytes
    seed: int
    signs: tuple[int, ...]
    statistic: float | None
    extreme: bool | None
    failure_code: str | None


@dataclass(frozen=True, slots=True)
class ContrastInference:
    """Typed operands consumed by the frozen gate formulas."""

    estimate: float | None
    ci_low: float | None
    ci_high: float | None
    p_adjusted: float | None
    result_status: Literal["ESTIMATED", "INCONCLUSIVE"]


@dataclass(frozen=True, slots=True)
class PairedMetricRow:
    comparison_id: str
    seed: int
    weight: float
    fixed_value: float | None
    calibrated_value: float | None


@dataclass(frozen=True, slots=True)
class PairedProbabilityRow:
    comparison_id: str
    seed: int
    weight: float
    fixed_top_probability: float | None
    fixed_correct: bool | None
    calibrated_top_probability: float | None
    calibrated_correct: bool | None


@dataclass(frozen=True, slots=True)
class OutcomeRow:
    comparison_id: str
    seed: int
    weight: float
    outcome_label: str | None
    divergent: bool
    primary_mechanism_id: str | None = None


@dataclass(frozen=True, slots=True)
class ComparisonRateRow:
    comparison_id: str
    seed: int
    weight: float
    divergent: bool | None


@dataclass(frozen=True, slots=True)
class ActionabilityBlock:
    population_id: str
    n_divergent: int
    n_present: int
    n_absent: int
    estimate: float | None
    estimability_status: Literal["estimated", "not_estimable"]


@dataclass(frozen=True, slots=True)
class ActionabilityComposite:
    pooled: ContrastInference
    n_present: int | None
    n_absent: int | None
    present_weight: float | None
    absent_weight: float | None
    prevalence: float | None
    blocks: tuple[ActionabilityBlock, ...]


@dataclass(frozen=True, slots=True)
class ActionabilityResult:
    p_raw: tuple[ActionTuple, ...]
    actionability_complete: DecisionBoolean


@dataclass(frozen=True, slots=True)
class EstimandDataset:
    """Immutable raw rows from which a registered estimand is rebuilt."""

    estimand_id: str
    metric_id: str
    paired_metric_rows: tuple[PairedMetricRow, ...] = ()
    paired_probability_rows: tuple[PairedProbabilityRow, ...] = ()
    outcome_rows: tuple[OutcomeRow, ...] = ()
    right_outcome_rows: tuple[OutcomeRow, ...] = ()
    left_outcome_rows: tuple[OutcomeRow, ...] = ()
    present_outcome_rows: tuple[OutcomeRow, ...] = ()
    absent_outcome_rows: tuple[OutcomeRow, ...] = ()
    target_rate_rows: tuple[ComparisonRateRow, ...] = ()
    comparator_rate_rows: tuple[ComparisonRateRow, ...] = ()
    classifiable_rows: tuple[OutcomeRow, ...] = ()
    selected_primary_mechanisms: tuple[str, str] = (
        "SCORE_FLATTENING",
        "GROUP_SIGMA_REORDERING",
    )


@dataclass(frozen=True, slots=True)
class ResamplingEstimand:
    """Registered estimand plus its raw rows; no callback can replace the statistic."""

    formula_id: str
    dataset: EstimandDataset

    def evaluate_bootstrap(self, sampled_seed_ids: tuple[int, ...]) -> float | None:
        return _evaluate_estimand(self.dataset, sampled_seed_ids=sampled_seed_ids)

    def evaluate_sign_flip(self, signs: tuple[int, ...]) -> float | None:
        return _evaluate_estimand(self.dataset, signs=signs)


@dataclass(frozen=True, slots=True)
class FormulaExecutionTrace:
    formula_id: str
    ordered_operand_ids: tuple[str, ...]
    operand_values: tuple[tuple[str, object, str | None], ...]
    output_value: object
    output_status: str | None


@dataclass(frozen=True, slots=True)
class FormulaExecution:
    output: object
    trace: FormulaExecutionTrace


class _TrackedOperands(Mapping[str, object]):
    """Mapping that proves every declared operand is actually read by its executor."""

    def __init__(self, values: Mapping[str, object]) -> None:
        self._values = values
        self.accessed: set[str] = set()

    def __getitem__(self, key: str) -> object:
        self.accessed.add(key)
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


type FormulaExecutor = Callable[[Mapping[str, object]], object]
type GateExecutor = Callable[[Mapping[str, object]], GateStatus | DecisionBoolean | BranchDecision]


def three_valued_and(statuses: Sequence[GateStatus]) -> GateStatus:
    if any(status is GateStatus.FAIL for status in statuses):
        return GateStatus.FAIL
    if statuses and all(status is GateStatus.PASS for status in statuses):
        return GateStatus.PASS
    return GateStatus.INCONCLUSIVE


def three_valued_or(statuses: Sequence[GateStatus]) -> GateStatus:
    if any(status is GateStatus.PASS for status in statuses):
        return GateStatus.PASS
    if statuses and all(status is GateStatus.FAIL for status in statuses):
        return GateStatus.FAIL
    return GateStatus.INCONCLUSIVE


def partition_action_tuples(
    p_raw: Sequence[ActionTuple], vetoes: Sequence[VetoResult]
) -> ActionPartition:
    by_tuple: dict[ActionTuple, list[VetoResult]] = {}
    for veto in vetoes:
        by_tuple.setdefault(veto.source_tuple, []).append(veto)
    vetoed: list[ActionTuple] = []
    surviving: list[ActionTuple] = []
    complete = True
    for item in p_raw:
        matches = by_tuple.get(item, [])
        if len(matches) != 1 or matches[0].veto_status == "INCONCLUSIVE":
            complete = False
            continue
        if matches[0].veto_status == "VETOED":
            vetoed.append(item)
        else:
            surviving.append(item)
    status = GateStatus.PASS if complete else GateStatus.INCONCLUSIVE
    return ActionPartition(
        vetoed_tuples=tuple(vetoed),
        surviving_tuples=tuple(surviving),
        veto_complete=DecisionBoolean.from_status(status, "F-VETO-COMPLETE"),
    )


def unique_actionable_mechanism(partition: ActionPartition) -> DecisionBoolean:
    if partition.veto_complete.status is GateStatus.INCONCLUSIVE:
        return DecisionBoolean.from_status(GateStatus.INCONCLUSIVE, "F-UNIQUE-MECHANISM")
    mechanisms = {item.mechanism_id for item in partition.surviving_tuples}
    return DecisionBoolean.from_status(
        GateStatus.PASS if len(mechanisms) == 1 else GateStatus.FAIL,
        "F-UNIQUE-MECHANISM",
    )


def b_authorized(
    *,
    controller_change_needed: DecisionBoolean,
    actionability_complete: DecisionBoolean,
    partition: ActionPartition,
    unique_mechanism: DecisionBoolean,
) -> DecisionBoolean:
    """F-B-AUTHORIZATION with its frozen inconclusive-first precedence."""

    required = (
        controller_change_needed.status,
        actionability_complete.status,
        partition.veto_complete.status,
        unique_mechanism.status,
    )
    if GateStatus.INCONCLUSIVE in required:
        return DecisionBoolean.from_status(GateStatus.INCONCLUSIVE, "F-B-AUTHORIZATION")
    mechanisms = {item.mechanism_id for item in partition.surviving_tuples}
    passes = (
        controller_change_needed.status is GateStatus.PASS
        and actionability_complete.status is GateStatus.PASS
        and partition.veto_complete.status is GateStatus.PASS
        and len(mechanisms) == 1
        and bool(partition.surviving_tuples)
        and unique_mechanism.status is GateStatus.PASS
    )
    return DecisionBoolean.from_status(
        GateStatus.PASS if passes else GateStatus.FAIL,
        "F-B-AUTHORIZATION",
    )


def final_decision(
    *,
    g_b_authorization: GateStatus,
    b_authorization: DecisionBoolean,
    veto_complete: DecisionBoolean,
    controller_change_needed: DecisionBoolean,
    ppo_eligible: DecisionBoolean,
) -> BranchDecision:
    """Evaluate BRANCH-B/C/D/A in the frozen first-match order."""

    authorization_consistent = g_b_authorization is b_authorization.status
    branch_b = (
        g_b_authorization is GateStatus.PASS
        and b_authorization.status is GateStatus.PASS
        and veto_complete.status is GateStatus.PASS
    )
    if branch_b:
        return _branch(
            "BRANCH-B",
            "B_DESIGN_ONE_MODIFICATION",
            "MATCH",
            "NO_MATCH",
            "NO_MATCH",
            valid=authorization_consistent,
        )
    branch_c = controller_change_needed.status is GateStatus.PASS and b_authorization.status in {
        GateStatus.FAIL,
        GateStatus.INCONCLUSIVE,
    }
    b_trace = "INCONCLUSIVE" if b_authorization.status is GateStatus.INCONCLUSIVE else "NO_MATCH"
    if branch_c:
        return _branch(
            "BRANCH-C",
            "C_NO_STABLE_MECHANISM",
            b_trace,
            "MATCH",
            "NO_MATCH",
            valid=authorization_consistent,
        )
    branch_d = (
        controller_change_needed.status is GateStatus.FAIL
        and ppo_eligible.status is GateStatus.PASS
    )
    if branch_d:
        return _branch(
            "BRANCH-D",
            "D_REAL_PPO_PILOT",
            b_trace,
            "NO_MATCH",
            "MATCH",
            valid=authorization_consistent,
        )
    return _branch(
        "BRANCH-A",
        "A_RETAIN_CURRENT",
        b_trace,
        "NO_MATCH",
        "NO_MATCH",
        valid=authorization_consistent,
    )


def weighted_mean(values: Sequence[float], weights: Sequence[float]) -> float:
    if len(values) != len(weights) or not values:
        raise ValueError("Weighted values and weights must be nonempty and aligned.")
    denominator = math.fsum(weights)
    if denominator <= 0.0:
        raise ZeroDivisionError("A weighted denominator must be strictly positive.")
    return (
        math.fsum(value * weight for value, weight in zip(values, weights, strict=True))
        / denominator
    )


def num_cmf(calibrated: Sequence[float], fixed: Sequence[float], weights: Sequence[float]) -> float:
    differences = tuple(
        calibrated_value - fixed_value
        for calibrated_value, fixed_value in zip(calibrated, fixed, strict=True)
    )
    return weighted_mean(differences, weights)


def num_help_hurt(labels: Sequence[str], weights: Sequence[float]) -> float:
    helped = math.fsum(
        weight for label, weight in zip(labels, weights, strict=True) if label == "helped"
    )
    hurt = math.fsum(
        weight for label, weight in zip(labels, weights, strict=True) if label == "hurt"
    )
    return helped - hurt


def weighted_rate(labels: Sequence[str], weights: Sequence[float], positive: str) -> float:
    included = tuple(
        (label, weight)
        for label, weight in zip(labels, weights, strict=True)
        if label in {"helped", "hurt"}
    )
    denominator = math.fsum(weight for _, weight in included)
    if denominator <= 0.0:
        raise ZeroDivisionError("Weighted helped-plus-hurt denominator is zero.")
    return math.fsum(weight for label, weight in included if label == positive) / denominator


def expected_calibration_error(
    top_probabilities: Sequence[float], correct: Sequence[bool], weights: Sequence[float]
) -> float:
    if not (len(top_probabilities) == len(correct) == len(weights)):
        raise ValueError("ECE inputs must be aligned.")
    total_weight = math.fsum(weights)
    if total_weight <= 0.0:
        raise ZeroDivisionError("ECE weight must be positive.")
    result = 0.0
    for bin_index in range(10):
        lower = bin_index / 10.0
        upper = (bin_index + 1) / 10.0
        indices = tuple(
            index
            for index, probability in enumerate(top_probabilities)
            if probability >= lower
            and (probability < upper or (bin_index == 9 and probability <= upper))
        )
        bin_weight = math.fsum(weights[index] for index in indices)
        if bin_weight == 0.0:
            continue
        confidence = (
            math.fsum(top_probabilities[index] * weights[index] for index in indices) / bin_weight
        )
        accuracy = (
            math.fsum(float(correct[index]) * weights[index] for index in indices) / bin_weight
        )
        result += (bin_weight / total_weight) * abs(accuracy - confidence)
    return result


def num_cmf_rows(rows: Sequence[PairedMetricRow]) -> float:
    complete = tuple(
        row for row in rows if row.fixed_value is not None and row.calibrated_value is not None
    )
    if not complete:
        raise ZeroDivisionError("NUM-CMF has no complete paired rows.")
    return weighted_mean(
        tuple(cast(float, row.calibrated_value) - cast(float, row.fixed_value) for row in complete),
        tuple(row.weight for row in complete),
    )


def num_ece_rows(rows: Sequence[PairedProbabilityRow]) -> float:
    complete = tuple(
        row
        for row in rows
        if row.fixed_top_probability is not None
        and row.fixed_correct is not None
        and row.calibrated_top_probability is not None
        and row.calibrated_correct is not None
    )
    if not complete:
        raise ZeroDivisionError("NUM-ECE has no complete paired rows.")
    weights = tuple(row.weight for row in complete)
    fixed = expected_calibration_error(
        tuple(cast(float, row.fixed_top_probability) for row in complete),
        tuple(cast(bool, row.fixed_correct) for row in complete),
        weights,
    )
    calibrated = expected_calibration_error(
        tuple(cast(float, row.calibrated_top_probability) for row in complete),
        tuple(cast(bool, row.calibrated_correct) for row in complete),
        weights,
    )
    return calibrated - fixed


def harm_rate(rows: Sequence[OutcomeRow]) -> float:
    labels = tuple(row.outcome_label or "" for row in rows if row.divergent)
    weights = tuple(row.weight for row in rows if row.divergent)
    return weighted_rate(labels, weights, "hurt")


def num_harm_right_left(right_rows: Sequence[OutcomeRow], left_rows: Sequence[OutcomeRow]) -> float:
    return harm_rate(right_rows) - harm_rate(left_rows)


def num_harm_present_absent(
    present_rows: Sequence[OutcomeRow], absent_rows: Sequence[OutcomeRow]
) -> float:
    return harm_rate(present_rows) - harm_rate(absent_rows)


def num_combined_share(
    *, weighted_classifiable_denominator: float, weighted_primary_sums: Sequence[float]
) -> float:
    if weighted_classifiable_denominator <= 0.0:
        raise ZeroDivisionError("NUM-COMBINED-SHARE denominator is not positive.")
    if len(weighted_primary_sums) != 2:
        raise ValueError("NUM-COMBINED-SHARE requires exactly SF and GSR sums.")
    return math.fsum(weighted_primary_sums) / weighted_classifiable_denominator


def divergence_rate(rows: Sequence[ComparisonRateRow]) -> float:
    resolved = tuple(row for row in rows if row.divergent is not None)
    denominator = math.fsum(row.weight for row in resolved)
    if denominator <= 0.0:
        raise ZeroDivisionError("Divergence-rate denominator is not positive.")
    return math.fsum(row.weight for row in resolved if row.divergent) / denominator


def num_divergence_rate_difference(
    target_rows: Sequence[ComparisonRateRow], comparator_rows: Sequence[ComparisonRateRow]
) -> float:
    return divergence_rate(target_rows) - divergence_rate(comparator_rows)


def denominator_paired(rows: Sequence[PairedMetricRow]) -> float:
    return math.fsum(
        row.weight
        for row in rows
        if row.fixed_value is not None and row.calibrated_value is not None
    )


def denominator_divergent(rows: Sequence[OutcomeRow]) -> float:
    return math.fsum(
        row.weight for row in rows if row.divergent and row.outcome_label in {"helped", "hurt"}
    )


def denominator_two_divergent_rates(
    target_rows: Sequence[OutcomeRow], comparator_rows: Sequence[OutcomeRow]
) -> tuple[float, float]:
    return denominator_divergent(target_rows), denominator_divergent(comparator_rows)


def denominator_present_absent(
    present_rows: Sequence[OutcomeRow], absent_rows: Sequence[OutcomeRow]
) -> tuple[float, float]:
    return denominator_divergent(present_rows), denominator_divergent(absent_rows)


def denominator_classifiable(rows: Sequence[OutcomeRow]) -> float:
    return math.fsum(
        row.weight for row in rows if row.divergent and row.primary_mechanism_id is not None
    )


def denominator_all_pairs(rows: Sequence[ComparisonRateRow]) -> float:
    if any(row.divergent is None for row in rows):
        raise ValueError("DEN-ALL-PAIRS encountered a missing canonical comparison.")
    return math.fsum(row.weight for row in rows)


def miss_pair20(
    *,
    n_total_pairs: int,
    n_complete_pairs: int,
    n_fixed_missing_only: int,
    n_calibrated_missing_only: int,
    n_both_missing: int,
    weighted_denominator: float,
    n_complete_seed_blocks: int,
) -> GateStatus:
    partition = n_complete_pairs + n_fixed_missing_only + n_calibrated_missing_only + n_both_missing
    if partition != n_total_pairs:
        raise ValueError("Paired missingness counts do not partition total pairs.")
    if weighted_denominator > 0.0 and n_complete_seed_blocks >= 20:
        return GateStatus.PASS
    return GateStatus.INCONCLUSIVE


def miss_divergent20(*, n_helped: int, n_hurt: int, weighted_denominator: float) -> GateStatus:
    return (
        GateStatus.PASS
        if weighted_denominator > 0.0 and n_helped >= 20 and n_hurt >= 20
        else GateStatus.INCONCLUSIVE
    )


def miss_mechanism20(
    *,
    weighted_present_helped: float,
    weighted_present_hurt: float,
    weighted_absent_helped: float,
    weighted_absent_hurt: float,
    n_complete_seed_blocks: int,
) -> GateStatus:
    present = weighted_present_helped + weighted_present_hurt
    absent = weighted_absent_helped + weighted_absent_hurt
    return (
        GateStatus.PASS
        if present > 0.0 and absent > 0.0 and n_complete_seed_blocks >= 20
        else GateStatus.INCONCLUSIVE
    )


def miss_two_rates20(
    *,
    weighted_target_denominator: float,
    weighted_comparator_denominator: float,
    n_target_divergent_raw: int,
    n_comparator_divergent_raw: int,
) -> GateStatus:
    return (
        GateStatus.PASS
        if weighted_target_denominator > 0.0
        and weighted_comparator_denominator > 0.0
        and n_target_divergent_raw >= 20
        and n_comparator_divergent_raw >= 20
        else GateStatus.INCONCLUSIVE
    )


def miss_sequence30(
    *,
    weighted_present_denominator: float,
    weighted_absent_denominator: float,
    n_present_raw: int,
    n_absent_raw: int,
) -> GateStatus:
    return (
        GateStatus.PASS
        if weighted_present_denominator > 0.0
        and weighted_absent_denominator > 0.0
        and n_present_raw >= 30
        and n_absent_raw >= 30
        else GateStatus.INCONCLUSIVE
    )


def miss_dominance30(
    *, weighted_classifiable_denominator: float, n_classifiable_raw: int
) -> GateStatus:
    return (
        GateStatus.PASS
        if weighted_classifiable_denominator > 0.0 and n_classifiable_raw >= 30
        else GateStatus.INCONCLUSIVE
    )


def miss_action25(
    *,
    weighted_present_denominator: float,
    weighted_absent_denominator: float,
    n_present_raw: int,
    n_absent_raw: int,
    block_support_counts: Sequence[tuple[int, int, int]],
) -> GateStatus:
    supported_blocks = sum(
        n_divergent >= 20 and n_present >= 5 and n_absent >= 5
        for n_divergent, n_present, n_absent in block_support_counts
    )
    return (
        GateStatus.PASS
        if weighted_present_denominator > 0.0
        and weighted_absent_denominator > 0.0
        and n_present_raw >= 25
        and n_absent_raw >= 25
        and len(block_support_counts) == 5
        and supported_blocks >= 4
        else GateStatus.INCONCLUSIVE
    )


def f_cal(
    *,
    nll: ContrastInference,
    brier: ContrastInference,
    ece: ContrastInference,
    confidently_wrong: ContrastInference,
    true_probability: ContrastInference,
) -> GateStatus:
    statuses = [
        _contrast_predicate(item, lambda value: value < 0.0, "estimate")
        for item in (nll, brier, ece)
    ]
    statuses.extend(
        _contrast_predicate(item, lambda value: value < 0.0, "ci_high")
        for item in (nll, brier, ece)
    )
    statuses.extend(
        _contrast_predicate(item, lambda value: value < 0.05, "p_adjusted")
        for item in (nll, brier, ece)
    )
    statuses.extend(
        (
            _contrast_predicate(confidently_wrong, lambda value: value <= -0.05, "estimate"),
            _contrast_predicate(confidently_wrong, lambda value: value < 0.0, "ci_high"),
            _contrast_predicate(confidently_wrong, lambda value: value < 0.05, "p_adjusted"),
            _contrast_predicate(true_probability, lambda value: value >= -0.02, "ci_low"),
        )
    )
    return three_valued_and(statuses)


def f_hard_safety(contrasts: Sequence[ContrastInference]) -> GateStatus:
    statuses: list[GateStatus] = []
    for item in contrasts:
        if item.result_status == "INCONCLUSIVE" or None in (
            item.estimate,
            item.ci_low,
            item.p_adjusted,
        ):
            statuses.append(GateStatus.INCONCLUSIVE)
            continue
        assert item.estimate is not None
        assert item.ci_low is not None
        assert item.p_adjusted is not None
        statuses.append(
            GateStatus.PASS
            if item.estimate >= 0.05 and item.ci_low > 0.0 and item.p_adjusted < 0.05
            else GateStatus.FAIL
        )
    return three_valued_or(statuses)


def f_concentration(
    *, target_count: int | None, comparator_count: int | None, contrast: ContrastInference
) -> GateStatus:
    if target_count is None or comparator_count is None:
        return GateStatus.INCONCLUSIVE
    return three_valued_and(
        (
            GateStatus.PASS if target_count >= 20 else GateStatus.FAIL,
            GateStatus.PASS if comparator_count >= 20 else GateStatus.FAIL,
            _contrast_predicate(contrast, lambda value: value >= 0.10, "estimate"),
            _contrast_predicate(contrast, lambda value: value > 0.0, "ci_low"),
            _contrast_predicate(contrast, lambda value: value < 0.05, "p_adjusted"),
        )
    )


def f_dominance(
    *,
    classifiable_count: int | None,
    combined_share: float | None,
    ci_low: float | None,
    score_flattening_share: float | None,
    group_sigma_reordering_share: float | None,
) -> GateStatus:
    values = (
        classifiable_count,
        combined_share,
        ci_low,
        score_flattening_share,
        group_sigma_reordering_share,
    )
    if any(value is None for value in values):
        return GateStatus.INCONCLUSIVE
    assert classifiable_count is not None
    assert combined_share is not None
    assert ci_low is not None
    assert score_flattening_share is not None
    assert group_sigma_reordering_share is not None
    return three_valued_and(
        (
            GateStatus.PASS if classifiable_count >= 30 else GateStatus.FAIL,
            GateStatus.PASS if combined_share >= 0.70 else GateStatus.FAIL,
            GateStatus.PASS if ci_low >= 0.60 else GateStatus.FAIL,
            GateStatus.PASS if score_flattening_share >= 0.10 else GateStatus.FAIL,
            GateStatus.PASS if group_sigma_reordering_share >= 0.10 else GateStatus.FAIL,
        )
    )


def f_veto(
    *,
    own_effect: float | None,
    other_effect: float | None,
    other_ci_low: float | None,
    other_ci_high: float | None,
    other_holm_p: float | None,
    support_resolved: bool,
) -> Literal["VETOED", "NOT_VETOED", "INCONCLUSIVE"]:
    values = (own_effect, other_effect, other_ci_low, other_ci_high, other_holm_p)
    if not support_resolved or any(value is None for value in values):
        return "INCONCLUSIVE"
    assert own_effect is not None
    assert other_effect is not None
    assert other_ci_low is not None
    assert other_ci_high is not None
    assert other_holm_p is not None
    opposite = own_effect * other_effect < 0.0
    ci_excludes_zero = other_ci_high < 0.0 or other_ci_low > 0.0
    vetoed = opposite and abs(other_effect) >= 0.15 and ci_excludes_zero and other_holm_p < 0.05
    return "VETOED" if vetoed else "NOT_VETOED"


def f_integrity(statuses: Sequence[GateStatus]) -> GateStatus:
    if len(statuses) != 16:
        return GateStatus.INCONCLUSIVE
    return three_valued_and(statuses)


def f_core(
    *,
    arm_runs: int | None,
    comparisons: int | None,
    sigma_rows: int | None,
    contrast_rows: int | None,
    all_foreign_keys_valid: bool | None,
) -> GateStatus:
    operands: tuple[tuple[int | bool | None, int | bool], ...] = (
        (arm_runs, 36_864),
        (comparisons, 18_432),
        (sigma_rows, 9_216),
        (contrast_rows, 122),
        (all_foreign_keys_valid, True),
    )
    return three_valued_and(
        tuple(
            GateStatus.INCONCLUSIVE
            if value is None
            else GateStatus.PASS
            if value == expected
            else GateStatus.FAIL
            for value, expected in operands
        )
    )


def f_ctrl(
    *,
    nll: ContrastInference,
    brier: ContrastInference,
    true_probability: ContrastInference,
    confidently_wrong: ContrastInference,
    helped_minus_hurt: ContrastInference,
    conditional_efficiency: ContrastInference,
    end_to_end_efficiency: ContrastInference,
    hard_safety: GateStatus,
) -> GateStatus:
    statuses = (
        _contrast_predicate(nll, lambda value: value < 0.0, "estimate"),
        _contrast_predicate(nll, lambda value: value < 0.0, "ci_high"),
        _contrast_predicate(nll, lambda value: value < 0.05, "p_adjusted"),
        _contrast_predicate(brier, lambda value: value < 0.0, "estimate"),
        _contrast_predicate(brier, lambda value: value < 0.0, "ci_high"),
        _contrast_predicate(brier, lambda value: value < 0.05, "p_adjusted"),
        _contrast_predicate(true_probability, lambda value: value >= 0.02, "estimate"),
        _contrast_predicate(true_probability, lambda value: value > 0.0, "ci_low"),
        _contrast_predicate(true_probability, lambda value: value < 0.05, "p_adjusted"),
        _contrast_predicate(confidently_wrong, lambda value: value <= 0.0, "estimate"),
        _contrast_predicate(confidently_wrong, lambda value: value <= 0.0, "ci_high"),
        _contrast_predicate(helped_minus_hurt, lambda value: value > 0.0, "estimate"),
        _contrast_predicate(helped_minus_hurt, lambda value: value > 0.0, "ci_low"),
        _contrast_predicate(helped_minus_hurt, lambda value: value < 0.05, "p_adjusted"),
        _contrast_predicate(conditional_efficiency, lambda value: value > 0.0, "estimate"),
        _contrast_predicate(conditional_efficiency, lambda value: value > 0.0, "ci_low"),
        _contrast_predicate(conditional_efficiency, lambda value: value < 0.05, "p_adjusted"),
        _contrast_predicate(end_to_end_efficiency, lambda value: value > 0.0, "estimate"),
        _contrast_predicate(end_to_end_efficiency, lambda value: value > 0.0, "ci_low"),
        _contrast_predicate(end_to_end_efficiency, lambda value: value < 0.05, "p_adjusted"),
        GateStatus.PASS
        if hard_safety is GateStatus.FAIL
        else GateStatus.FAIL
        if hard_safety is GateStatus.PASS
        else GateStatus.INCONCLUSIVE,
    )
    return three_valued_and(statuses)


def f_order(
    *, present_count: int | None, absent_count: int | None, contrast: ContrastInference
) -> GateStatus:
    if present_count is None or absent_count is None:
        return GateStatus.INCONCLUSIVE
    return three_valued_and(
        (
            GateStatus.PASS if present_count >= 30 else GateStatus.FAIL,
            GateStatus.PASS if absent_count >= 30 else GateStatus.FAIL,
            _contrast_predicate(contrast, lambda value: value >= 0.10, "estimate"),
            _contrast_predicate(contrast, lambda value: value > 0.0, "ci_low"),
            _contrast_predicate(contrast, lambda value: value < 0.05, "p_adjusted"),
        )
    )


def f_action(
    *,
    decision: ActionabilityComposite,
    source: ContrastInference,
    mechanism_allowed: bool | None,
    truth_free_provenance: bool | None,
) -> GateStatus:
    if len(decision.blocks) != 5:
        return GateStatus.INCONCLUSIVE
    pooled_estimate = source.estimate
    if (
        decision.n_present is None
        or decision.n_absent is None
        or decision.prevalence is None
        or pooled_estimate is None
        or mechanism_allowed is None
        or truth_free_provenance is None
    ):
        return GateStatus.INCONCLUSIVE
    eligible = tuple(
        block
        for block in decision.blocks
        if block.n_divergent >= 20 and block.n_present >= 5 and block.n_absent >= 5
    )
    block_statuses: list[GateStatus] = []
    for block in eligible:
        if block.estimability_status != "estimated" or block.estimate is None:
            block_statuses.append(GateStatus.INCONCLUSIVE)
            continue
        same_direction = pooled_estimate != 0.0 and block.estimate * pooled_estimate > 0.0
        opposite_material = block.estimate * pooled_estimate < 0.0 and abs(block.estimate) >= 0.10
        block_statuses.append(
            GateStatus.PASS if same_direction and not opposite_material else GateStatus.FAIL
        )
    statuses = [
        GateStatus.PASS if source.result_status == "ESTIMATED" else GateStatus.INCONCLUSIVE,
        GateStatus.PASS if decision.n_present >= 25 else GateStatus.FAIL,
        GateStatus.PASS if decision.n_absent >= 25 else GateStatus.FAIL,
        GateStatus.PASS if 0.10 <= decision.prevalence <= 0.90 else GateStatus.FAIL,
        GateStatus.PASS if abs(pooled_estimate) >= 0.15 else GateStatus.FAIL,
        _contrast_predicate(
            source,
            lambda _: cast(float, source.ci_high) < 0.0 or cast(float, source.ci_low) > 0.0,
            "estimate",
        )
        if source.ci_low is not None and source.ci_high is not None
        else GateStatus.INCONCLUSIVE,
        _contrast_predicate(source, lambda value: value < 0.05, "p_adjusted"),
        GateStatus.PASS if len(eligible) >= 4 else GateStatus.FAIL,
        *block_statuses,
        GateStatus.PASS if truth_free_provenance else GateStatus.FAIL,
        GateStatus.PASS if mechanism_allowed else GateStatus.FAIL,
    ]
    return three_valued_and(statuses)


def f_action_complete(
    statuses: Sequence[GateStatus], action_tuples: Sequence[ActionTuple]
) -> ActionabilityResult:
    if len(statuses) != 20 or len(action_tuples) != 20:
        return ActionabilityResult(
            (), DecisionBoolean.from_status(GateStatus.INCONCLUSIVE, "F-ACTION-COMPLETE")
        )
    p_raw = tuple(
        item
        for item, status in zip(action_tuples, statuses, strict=True)
        if status is GateStatus.PASS
    )
    complete = all(status in {GateStatus.PASS, GateStatus.FAIL} for status in statuses)
    return ActionabilityResult(
        p_raw,
        DecisionBoolean(
            True if complete else None,
            "resolved" if complete else "inconclusive",
            ("F-ACTION-COMPLETE",),
        ),
    )


def f_veto_complete(p_raw: Sequence[ActionTuple], vetoes: Sequence[VetoResult]) -> DecisionBoolean:
    return partition_action_tuples(p_raw, vetoes).veto_complete


def f_ppo(
    *,
    integrity: GateStatus,
    core: GateStatus,
    calibration: GateStatus,
    controller: GateStatus,
    hard_safety: GateStatus,
    actionability_complete: DecisionBoolean,
    veto_complete: DecisionBoolean,
    surviving: Sequence[ActionTuple],
    controller_change: DecisionBoolean,
) -> DecisionBoolean:
    statuses = (
        integrity,
        core,
        calibration,
        controller,
        GateStatus.PASS
        if hard_safety is GateStatus.FAIL
        else GateStatus.FAIL
        if hard_safety is GateStatus.PASS
        else GateStatus.INCONCLUSIVE,
        actionability_complete.status,
        veto_complete.status,
        GateStatus.PASS if not surviving else GateStatus.FAIL,
        GateStatus.PASS
        if controller_change.status is GateStatus.FAIL
        else GateStatus.FAIL
        if controller_change.status is GateStatus.PASS
        else GateStatus.INCONCLUSIVE,
    )
    return DecisionBoolean.from_status(three_valued_and(statuses), "F-PPO")


def controller_change_needed(
    *,
    integrity: GateStatus,
    core: GateStatus,
    calibration: GateStatus,
    controller: GateStatus,
    hard_safety: GateStatus,
) -> DecisionBoolean:
    nested = three_valued_or(
        (
            GateStatus.PASS
            if controller is GateStatus.FAIL
            else GateStatus.FAIL
            if controller is GateStatus.PASS
            else GateStatus.INCONCLUSIVE,
            hard_safety,
        )
    )
    status = three_valued_and((integrity, core, calibration, nested))
    return DecisionBoolean.from_status(status, "F-CONTROLLER-CHANGE")


def _contrast_predicate(
    contrast: ContrastInference,
    predicate: Callable[[float], bool],
    field: Literal["estimate", "ci_low", "ci_high", "p_adjusted"],
) -> GateStatus:
    if contrast.result_status == "INCONCLUSIVE":
        return GateStatus.INCONCLUSIVE
    value = getattr(contrast, field)
    if value is None:
        return GateStatus.INCONCLUSIVE
    return GateStatus.PASS if predicate(value) else GateStatus.FAIL


def bootstrap_seed(contrast_id: str, replicate_index: int) -> tuple[bytes, bytes, int]:
    if contrast_id not in _frozen_resampling_ids()[0]:
        raise ValueError("Bootstrap contrast ID is outside the frozen 66-member registry.")
    _validate_replicate(replicate_index)
    preimage = canonical_json_bytes(
        [
            "rde.broader.bootstrap/v2",
            PROTOCOL_VERSION,
            contrast_id,
            f"{replicate_index:05d}",
        ]
    )
    digest = hashlib.sha256(preimage).digest()
    return preimage, digest, int.from_bytes(digest[:8], "big")


def sign_flip_seed(contrast_id: str, replicate_index: int) -> tuple[bytes, bytes, int]:
    if contrast_id not in _frozen_resampling_ids()[1]:
        raise ValueError("Sign-flip contrast ID is outside the frozen HOLM-64 registry.")
    _validate_replicate(replicate_index)
    preimage = (f"broader-replication/v1|sign-flip|{contrast_id}|{replicate_index:05d}").encode()
    digest = hashlib.sha256(preimage).digest()
    return preimage, digest, int.from_bytes(digest[:8], "big")


def splitmix64_stream(seed: int, count: int) -> tuple[int, ...]:
    state = seed
    values: list[int] = []
    for _ in range(count):
        state = (state + 0x9E3779B97F4A7C15) & MASK64
        value = state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & MASK64
        value ^= value >> 31
        values.append(value & MASK64)
    return tuple(values)


def bootstrap_seed_ids(contrast_id: str, replicate_index: int) -> tuple[int, ...]:
    _, _, seed = bootstrap_seed(contrast_id, replicate_index)
    return tuple(1000 + (value & 0x7F) for value in splitmix64_stream(seed, 128))


def sign_flip_vector(contrast_id: str, replicate_index: int) -> tuple[int, ...]:
    _, _, seed = sign_flip_seed(contrast_id, replicate_index)
    return tuple(value & 1 for value in splitmix64_stream(seed, 128))


def bootstrap_replicate(
    contrast_id: str,
    replicate_index: int,
    estimand: Callable[[tuple[int, ...]], float | None],
) -> BootstrapReplicate:
    preimage, digest, seed = bootstrap_seed(contrast_id, replicate_index)
    sampled = tuple(1000 + (value & 0x7F) for value in splitmix64_stream(seed, 128))
    failure: str | None
    try:
        estimate = estimand(sampled)
    except ZeroDivisionError:
        estimate = None
        failure = "zero_denominator"
    except (KeyError, ValueError):
        estimate = None
        failure = "insufficient_complete_cases"
    else:
        if estimate is None:
            failure = "insufficient_complete_cases"
        elif not math.isfinite(estimate):
            estimate = None
            failure = "nonfinite_result"
        else:
            failure = None
    return BootstrapReplicate(
        contrast_id,
        replicate_index,
        preimage,
        digest,
        seed,
        sampled,
        estimate,
        failure,
    )


def sign_flip_replicate(
    contrast_id: str,
    replicate_index: int,
    observed_statistic: float,
    statistic: Callable[[tuple[int, ...]], float | None],
) -> SignFlipReplicate:
    preimage, digest, seed = sign_flip_seed(contrast_id, replicate_index)
    signs = tuple(value & 1 for value in splitmix64_stream(seed, 128))
    failure: str | None
    try:
        value = statistic(signs)
    except ZeroDivisionError:
        value = None
        failure = "zero_denominator"
    except (KeyError, ValueError):
        value = None
        failure = "insufficient_complete_cases"
    else:
        if value is None:
            failure = "insufficient_complete_cases"
        elif not math.isfinite(value):
            value = None
            failure = "nonfinite_result"
        else:
            failure = None
    return SignFlipReplicate(
        contrast_id,
        replicate_index,
        preimage,
        digest,
        seed,
        signs,
        value,
        abs(value) >= abs(observed_statistic) if value is not None else None,
        failure,
    )


def bootstrap_10000(
    contrast_id: str,
    estimand: Callable[[tuple[int, ...]], float | None],
    *,
    replicates: int = BOOTSTRAP_REPLICATES,
) -> BootstrapResult:
    estimates: list[float] = []
    nulls = 0
    for replicate_index in range(replicates):
        estimate = estimand(bootstrap_seed_ids(contrast_id, replicate_index))
        if estimate is None or not math.isfinite(estimate):
            nulls += 1
        else:
            estimates.append(estimate)
    required = 9_500 if replicates == 10_000 else math.ceil(0.95 * replicates)
    if len(estimates) < required:
        return BootstrapResult(tuple(estimates), nulls, None, None, GateStatus.INCONCLUSIVE)
    ordered = tuple(sorted(estimates))
    lower_index = math.ceil(0.025 * len(ordered)) - 1
    upper_index = math.ceil(0.975 * len(ordered)) - 1
    return BootstrapResult(
        ordered,
        nulls,
        ordered[lower_index],
        ordered[upper_index],
        GateStatus.PASS,
    )


def signflip_10000(
    contrast_id: str,
    observed_statistic: float,
    statistic: Callable[[tuple[int, ...]], float | None],
    *,
    replicates: int = SIGN_FLIP_REPLICATES,
) -> SignFlipResult:
    extreme = 0
    for replicate_index in range(replicates):
        value = statistic(sign_flip_vector(contrast_id, replicate_index))
        if value is None or not math.isfinite(value):
            return SignFlipResult(observed_statistic, None, None, GateStatus.INCONCLUSIVE)
        if abs(value) >= abs(observed_statistic):
            extreme += 1
    denominator = 10_001 if replicates == 10_000 else replicates + 1
    return SignFlipResult(
        observed_statistic,
        extreme,
        (1 + extreme) / denominator,
        GateStatus.PASS,
    )


def holm_64(inputs: Sequence[HolmInput]) -> tuple[HolmResult, ...]:
    expected_ids = _frozen_resampling_ids()[2]
    observed_ids = tuple(item.statistical_hypothesis_id for item in inputs)
    if observed_ids != expected_ids:
        raise ValueError("HOLM-64 requires the exact 64-member frozen hypothesis order.")
    ranked = sorted(
        enumerate(inputs),
        key=lambda item: (
            item[1].p_raw if item[1].estimable and item[1].p_raw is not None else 1.0,
            item[0],
        ),
    )
    adjusted_by_index: dict[int, tuple[float, int]] = {}
    running = 0.0
    for rank, (original_index, item) in enumerate(ranked, start=1):
        p_for_holm = item.p_raw if item.estimable and item.p_raw is not None else 1.0
        running = max(running, (64 - rank + 1) * p_for_holm)
        adjusted_by_index[original_index] = (min(1.0, running), rank)
    return tuple(
        HolmResult(
            statistical_hypothesis_id=item.statistical_hypothesis_id,
            p_raw=item.p_raw if item.estimable else None,
            p_adjusted=adjusted_by_index[index][0] if item.estimable else None,
            holm_rank=adjusted_by_index[index][1],
            result_status="ESTIMATED" if item.estimable else "INCONCLUSIVE",
        )
        for index, item in enumerate(inputs)
    )


@cache
def _frozen_resampling_ids() -> tuple[frozenset[str], frozenset[str], tuple[str, ...]]:
    snapshot = load_protocol_snapshot()
    confirmatory = snapshot.registry("confirmatory").records()
    bootstrap_ids = frozenset(row["contrast_id"] for row in confirmatory)
    sign_flip_ids = frozenset(
        row["contrast_id"] for row in confirmatory if row["holm_member"] == "true"
    )
    hypothesis_ids = snapshot.registry("statistical_hypothesis").ids("statistical_hypothesis_id")
    return bootstrap_ids, sign_flip_ids, hypothesis_ids


def sampled_seed_ids_sha256(
    contrast_id: str, replicate_index: int, sampled_seed_ids: Sequence[int]
) -> str:
    return protocol_hash(
        "sampled_seed_ids/v1",
        {
            "contrast_id": contrast_id,
            "replicate_index": replicate_index,
            "sampled_seed_ids": list(sampled_seed_ids),
        },
    )


def sign_vector_sha256(contrast_id: str, replicate_index: int, signs: Sequence[int]) -> str:
    return protocol_hash(
        "sign_vector/v1",
        {
            "contrast_id": contrast_id,
            "replicate_index": replicate_index,
            "ordered_signs_by_seed": list(signs),
        },
    )


def _seed_weight_map(value: object) -> Mapping[int, float]:
    if not isinstance(value, Mapping):
        raise TypeError("seed_block_weights must be a seed-to-weight mapping.")
    result: dict[int, float] = {}
    for seed, weight in value.items():
        if not isinstance(seed, int) or not isinstance(weight, (float, int)):
            raise TypeError("Seed-block weights require integer seeds and numeric weights.")
        numeric = float(weight)
        if not math.isfinite(numeric) or numeric < 0.0:
            raise ValueError("Seed-block weights must be finite and non-negative.")
        result[seed] = numeric
    return result


def _weighted_metric_rows(
    rows: Sequence[PairedMetricRow], seed_weights: Mapping[int, float]
) -> tuple[PairedMetricRow, ...]:
    return tuple(
        PairedMetricRow(
            row.comparison_id,
            row.seed,
            row.weight * seed_weights.get(row.seed, 0.0),
            row.fixed_value,
            row.calibrated_value,
        )
        for row in rows
    )


def _weighted_probability_rows(
    rows: Sequence[PairedProbabilityRow], seed_weights: Mapping[int, float]
) -> tuple[PairedProbabilityRow, ...]:
    return tuple(
        PairedProbabilityRow(
            row.comparison_id,
            row.seed,
            row.weight * seed_weights.get(row.seed, 0.0),
            row.fixed_top_probability,
            row.fixed_correct,
            row.calibrated_top_probability,
            row.calibrated_correct,
        )
        for row in rows
    )


def _weighted_outcome_rows(
    rows: Sequence[OutcomeRow], seed_weights: Mapping[int, float]
) -> tuple[OutcomeRow, ...]:
    return tuple(
        OutcomeRow(
            row.comparison_id,
            row.seed,
            row.weight * seed_weights.get(row.seed, 0.0),
            row.outcome_label,
            row.divergent,
            row.primary_mechanism_id,
        )
        for row in rows
    )


def _weighted_rate_rows(
    rows: Sequence[ComparisonRateRow], seed_weights: Mapping[int, float]
) -> tuple[ComparisonRateRow, ...]:
    return tuple(
        ComparisonRateRow(
            row.comparison_id,
            row.seed,
            row.weight * seed_weights.get(row.seed, 0.0),
            row.divergent,
        )
        for row in rows
    )


def _resample_rows[T](rows: Sequence[T], sampled_seed_ids: Sequence[int]) -> tuple[T, ...]:
    by_seed: dict[int, list[T]] = {}
    for row in rows:
        seed = getattr(row, "seed", None)
        if not isinstance(seed, int):
            raise TypeError("A resampled estimand row lacks an integer seed.")
        by_seed.setdefault(seed, []).append(row)
    return tuple(row for seed in sampled_seed_ids for row in by_seed.get(seed, ()))


def _flip_label(label: str | None) -> str | None:
    if label == "helped":
        return "hurt"
    if label == "hurt":
        return "helped"
    return label


def _flip_metric_rows(
    rows: Sequence[PairedMetricRow], signs: Mapping[int, int]
) -> tuple[PairedMetricRow, ...]:
    return tuple(
        PairedMetricRow(
            row.comparison_id,
            row.seed,
            row.weight,
            row.calibrated_value if signs.get(row.seed, 0) else row.fixed_value,
            row.fixed_value if signs.get(row.seed, 0) else row.calibrated_value,
        )
        for row in rows
    )


def _flip_probability_rows(
    rows: Sequence[PairedProbabilityRow], signs: Mapping[int, int]
) -> tuple[PairedProbabilityRow, ...]:
    return tuple(
        PairedProbabilityRow(
            row.comparison_id,
            row.seed,
            row.weight,
            row.calibrated_top_probability if signs.get(row.seed, 0) else row.fixed_top_probability,
            row.calibrated_correct if signs.get(row.seed, 0) else row.fixed_correct,
            row.fixed_top_probability if signs.get(row.seed, 0) else row.calibrated_top_probability,
            row.fixed_correct if signs.get(row.seed, 0) else row.calibrated_correct,
        )
        for row in rows
    )


def _flip_outcome_rows(
    rows: Sequence[OutcomeRow], signs: Mapping[int, int]
) -> tuple[OutcomeRow, ...]:
    return tuple(
        OutcomeRow(
            row.comparison_id,
            row.seed,
            row.weight,
            _flip_label(row.outcome_label) if signs.get(row.seed, 0) else row.outcome_label,
            row.divergent,
            row.primary_mechanism_id,
        )
        for row in rows
    )


def _evaluate_estimand(
    dataset: EstimandDataset,
    *,
    sampled_seed_ids: tuple[int, ...] | None = None,
    signs: tuple[int, ...] | None = None,
) -> float | None:
    if (sampled_seed_ids is None) == (signs is None):
        raise ValueError("Exactly one resampling stream must be supplied.")
    if sampled_seed_ids is not None:
        metrics = _resample_rows(dataset.paired_metric_rows, sampled_seed_ids)
        probabilities = _resample_rows(dataset.paired_probability_rows, sampled_seed_ids)
        outcomes = _resample_rows(dataset.outcome_rows, sampled_seed_ids)
        right = _resample_rows(dataset.right_outcome_rows, sampled_seed_ids)
        left = _resample_rows(dataset.left_outcome_rows, sampled_seed_ids)
        present = _resample_rows(dataset.present_outcome_rows, sampled_seed_ids)
        absent = _resample_rows(dataset.absent_outcome_rows, sampled_seed_ids)
        target = _resample_rows(dataset.target_rate_rows, sampled_seed_ids)
        comparator = _resample_rows(dataset.comparator_rate_rows, sampled_seed_ids)
        classifiable = _resample_rows(dataset.classifiable_rows, sampled_seed_ids)
    else:
        assert signs is not None
        if len(signs) != len(FULL_SEEDS):
            raise ValueError("Sign-flip estimands require all 128 frozen seed blocks.")
        sign_map = dict(zip(FULL_SEEDS, signs, strict=True))
        metrics = _flip_metric_rows(dataset.paired_metric_rows, sign_map)
        probabilities = _flip_probability_rows(dataset.paired_probability_rows, sign_map)
        outcomes = _flip_outcome_rows(dataset.outcome_rows, sign_map)
        right = _flip_outcome_rows(dataset.right_outcome_rows, sign_map)
        left = _flip_outcome_rows(dataset.left_outcome_rows, sign_map)
        present = _flip_outcome_rows(dataset.present_outcome_rows, sign_map)
        absent = _flip_outcome_rows(dataset.absent_outcome_rows, sign_map)
        target = dataset.target_rate_rows
        comparator = dataset.comparator_rate_rows
        classifiable = _flip_outcome_rows(dataset.classifiable_rows, sign_map)
    try:
        if dataset.estimand_id == "calibrated_minus_fixed":
            return (
                num_ece_rows(probabilities) if dataset.metric_id == "ece" else num_cmf_rows(metrics)
            )
        if dataset.estimand_id == "helped_minus_hurt":
            return num_help_hurt(
                tuple(row.outcome_label or "" for row in outcomes),
                tuple(row.weight for row in outcomes),
            )
        if dataset.estimand_id in {"conditional_harm_difference", "sequence_harm_difference"}:
            return num_harm_right_left(right, left)
        if dataset.estimand_id == "mechanism_harm_difference":
            return num_harm_present_absent(present, absent)
        if dataset.estimand_id == "combined_primary_share":
            denominator = denominator_classifiable(classifiable)
            selected = set(dataset.selected_primary_mechanisms)
            numerator = math.fsum(
                row.weight for row in classifiable if row.primary_mechanism_id in selected
            )
            return numerator / denominator
        if dataset.estimand_id == "divergence_rate_difference":
            return num_divergence_rate_difference(target, comparator)
    except ZeroDivisionError:
        return None
    raise ValueError(f"Unsupported registered resampling estimand: {dataset.estimand_id}")


def _status_text(value: object) -> str | None:
    if isinstance(value, GateStatus):
        return value.value
    if isinstance(value, DecisionBoolean):
        return value.status.value
    if isinstance(value, BranchDecision):
        return value.gate_status.value
    if isinstance(value, ContrastInference):
        return value.result_status
    if isinstance(value, (BootstrapReplicate, SignFlipReplicate)):
        return "valid" if value.failure_code is None else "null"
    return None


def execute_formula_traced(formula_id: str, operands: Mapping[str, object]) -> FormulaExecution:
    """Execute one frozen formula and prove its exact operand contract was honored."""

    try:
        executor = FORMULA_EXECUTORS[formula_id]
    except KeyError as error:
        raise KeyError(f"No frozen executor exists for formula {formula_id}.") from error
    required = _formula_operand_registry()[formula_id]
    actual = tuple(operands)
    missing = tuple(operand_id for operand_id in required if operand_id not in operands)
    unknown = tuple(operand_id for operand_id in actual if operand_id not in required)
    if missing or unknown:
        raise KeyError(
            f"Formula {formula_id} operand contract differs; missing={missing}, unknown={unknown}."
        )
    if actual != required:
        raise ValueError(
            f"Formula {formula_id} operands must be supplied in frozen order "
            f"{required}, got {actual}."
        )
    tracked = _TrackedOperands(operands)
    output = executor(tracked)
    ignored = tuple(operand_id for operand_id in required if operand_id not in tracked.accessed)
    if ignored:
        raise RuntimeError(f"Formula {formula_id} ignored frozen operands: {ignored}.")
    trace = FormulaExecutionTrace(
        formula_id=formula_id,
        ordered_operand_ids=required,
        operand_values=tuple(
            (operand_id, operands[operand_id], _status_text(operands[operand_id]))
            for operand_id in required
        ),
        output_value=output,
        output_status=_status_text(output),
    )
    return FormulaExecution(output, trace)


def execute_formula(formula_id: str, operands: Mapping[str, object]) -> object:
    return execute_formula_traced(formula_id, operands).output


def execute_gate(gate_id: str, operands: Mapping[str, object]) -> object:
    """Execute a gate through its sole literal formula owner."""

    try:
        executor = GATE_EXECUTORS[gate_id]
    except KeyError as error:
        raise KeyError(f"No frozen evaluator exists for gate {gate_id}.") from error
    return executor(operands)


@cache
def _formula_operand_registry() -> dict[str, tuple[str, ...]]:
    return {
        row["formula_id"]: tuple(row["ordered_operand_ids"].split(";"))
        for row in load_protocol_snapshot().registry("formula").records()
    }


def _require_metric(metric_id: str) -> None:
    if metric_id not in load_protocol_snapshot().registry("metric").ids("metric_id"):
        raise ValueError(f"Unknown frozen metric ID: {metric_id}")


@cache
def _frozen_action_tuples() -> tuple[ActionTuple, ...]:
    snapshot = load_protocol_snapshot()
    mechanisms = snapshot.registry("mechanism").ids("mechanism_id")[:10]
    decisions = snapshot.registry("decision").records()
    actions: list[ActionTuple] = []
    for index, row in enumerate(decisions):
        mechanism = mechanisms[index % 10]
        actions.append(
            ActionTuple(
                row["policy_scope"],
                mechanism,
                row["contrast_id"],
                row["source_contrast_id"],
            )
        )
    return tuple(actions)


def _veto_contrast_for(source: ActionTuple) -> str:
    matches = tuple(
        row
        for row in load_protocol_snapshot().registry("veto").records()
        if row["decision_contrast_id"] == source.decision_contrast_id
        and row["policy_scope"] == source.policy_scope
        and row["mechanism_id"] == source.mechanism_id
        and row["own_confirmatory_contrast_id"] == source.confirmatory_contrast_id
    )
    if len(matches) != 1:
        raise ValueError("F-VETO source tuple does not own exactly one frozen veto row.")
    return matches[0]["required_veto_contrast_id"]


def _formula_num_cmf(values: Mapping[str, object]) -> float:
    rows = cast(Sequence[PairedMetricRow], values["paired_rows"])
    metric_id = cast(str, values["metric_id"])
    weights = _seed_weight_map(values["seed_block_weights"])
    _require_metric(metric_id)
    if metric_id == "ece":
        raise ValueError("NUM-CMF cannot evaluate the ECE metric.")
    return num_cmf_rows(_weighted_metric_rows(rows, weights))


def _formula_num_ece(values: Mapping[str, object]) -> float:
    rows = cast(Sequence[PairedProbabilityRow], values["paired_probability_rows"])
    edges = cast(Sequence[float], values["ece_bin_edges"])
    weights = _seed_weight_map(values["seed_block_weights"])
    if tuple(float(item) for item in edges) != tuple(index / 10.0 for index in range(11)):
        raise ValueError("NUM-ECE requires the frozen eleven bin edges.")
    return num_ece_rows(_weighted_probability_rows(rows, weights))


def _formula_num_help_hurt(values: Mapping[str, object]) -> float:
    rows = cast(Sequence[OutcomeRow], values["divergent_outcome_rows"])
    weights = _seed_weight_map(values["seed_block_weights"])
    helped = cast(str, values["helped_label"])
    hurt = cast(str, values["hurt_label"])
    mixed = cast(str, values["mixed_label"])
    if (helped, hurt, mixed) != ("helped", "hurt", "mixed"):
        raise ValueError("NUM-HELP-HURT labels differ from the frozen literals.")
    weighted = _weighted_outcome_rows(rows, weights)
    helped_sum = math.fsum(row.weight for row in weighted if row.outcome_label == helped)
    hurt_sum = math.fsum(row.weight for row in weighted if row.outcome_label == hurt)
    _ = sum(row.outcome_label == mixed for row in weighted)
    return helped_sum - hurt_sum


def _formula_num_harm_right_left(values: Mapping[str, object]) -> float:
    weights = _seed_weight_map(values["seed_block_weights"])
    return num_harm_right_left(
        _weighted_outcome_rows(
            cast(Sequence[OutcomeRow], values["right_population_rows"]), weights
        ),
        _weighted_outcome_rows(cast(Sequence[OutcomeRow], values["left_population_rows"]), weights),
    )


def _formula_num_harm_present_absent(values: Mapping[str, object]) -> float:
    weights = _seed_weight_map(values["seed_block_weights"])
    return num_harm_present_absent(
        _weighted_outcome_rows(
            cast(Sequence[OutcomeRow], values["mechanism_present_rows"]), weights
        ),
        _weighted_outcome_rows(
            cast(Sequence[OutcomeRow], values["mechanism_absent_rows"]), weights
        ),
    )


def _formula_num_combined_share(values: Mapping[str, object]) -> float:
    denominator = cast(float, values["weighted_classifiable_denominator"])
    ig = (
        cast(float | None, values["COUNT-PRIMARY-SF-IG"]),
        cast(float | None, values["COUNT-PRIMARY-GSR-IG"]),
    )
    lookahead = (
        cast(float | None, values["COUNT-PRIMARY-SF-LA"]),
        cast(float | None, values["COUNT-PRIMARY-GSR-LA"]),
    )
    selected = tuple(pair for pair in (ig, lookahead) if pair[0] is not None or pair[1] is not None)
    if len(selected) != 1 or any(item is None for item in selected[0]):
        raise ValueError("NUM-COMBINED-SHARE requires exactly one complete policy count pair.")
    return num_combined_share(
        weighted_classifiable_denominator=denominator,
        weighted_primary_sums=cast(tuple[float, float], selected[0]),
    )


def _formula_num_divergence(values: Mapping[str, object]) -> float:
    weights = _seed_weight_map(values["seed_block_weights"])
    return num_divergence_rate_difference(
        _weighted_rate_rows(cast(Sequence[ComparisonRateRow], values["target_pairs"]), weights),
        _weighted_rate_rows(cast(Sequence[ComparisonRateRow], values["comparator_pairs"]), weights),
    )


def _formula_num_actionability(values: Mapping[str, object]) -> ActionabilityComposite:
    result = values["decision_contrast_rows"]
    if not isinstance(result, ActionabilityComposite):
        raise TypeError("NUM-ACTIONABILITY requires an ActionabilityComposite source.")
    blocks = tuple(cast(Sequence[ActionabilityBlock], values["five_block_rows"]))
    source = values["source_confirmatory_row"]
    if not isinstance(source, ContrastInference):
        raise TypeError("NUM-ACTIONABILITY source row must be a ContrastInference.")
    if len(blocks) != 5 or blocks != result.blocks or source != result.pooled:
        raise ValueError("NUM-ACTIONABILITY source and five-block rows do not reconcile.")
    return ActionabilityComposite(
        source,
        result.n_present,
        result.n_absent,
        result.present_weight,
        result.absent_weight,
        result.prevalence,
        blocks,
    )


def _formula_den_paired(values: Mapping[str, object]) -> float:
    rows = cast(Sequence[PairedMetricRow], values["paired_rows"])
    indicators = tuple(cast(Sequence[bool], values["complete_pair_indicator"]))
    weights = _seed_weight_map(values["seed_block_weights"])
    if len(indicators) != len(rows):
        raise ValueError("DEN-PAIRED complete-pair indicators are not aligned.")
    expected = tuple(
        row.fixed_value is not None and row.calibrated_value is not None for row in rows
    )
    if indicators != expected:
        raise ValueError("DEN-PAIRED complete-pair indicators disagree with raw rows.")
    return denominator_paired(_weighted_metric_rows(rows, weights))


def _formula_den_divergent(values: Mapping[str, object]) -> float:
    rows = cast(Sequence[OutcomeRow], values["divergent_outcome_rows"])
    weights = _seed_weight_map(values["seed_block_weights"])
    helped = cast(str, values["helped_label"])
    hurt = cast(str, values["hurt_label"])
    if (helped, hurt) != ("helped", "hurt"):
        raise ValueError("DEN-DIVERGENT labels differ from the frozen literals.")
    return math.fsum(
        row.weight
        for row in _weighted_outcome_rows(rows, weights)
        if row.divergent and row.outcome_label in {helped, hurt}
    )


def _formula_den_two_rates(values: Mapping[str, object]) -> tuple[float, float]:
    weights = _seed_weight_map(values["seed_block_weights"])
    helped = cast(str, values["helped_label"])
    hurt = cast(str, values["hurt_label"])
    if (helped, hurt) != ("helped", "hurt"):
        raise ValueError("DEN-TWO-DIVERGENT-RATES labels differ from the freeze.")
    return denominator_two_divergent_rates(
        _weighted_outcome_rows(
            cast(Sequence[OutcomeRow], values["target_divergent_rows"]), weights
        ),
        _weighted_outcome_rows(
            cast(Sequence[OutcomeRow], values["comparator_divergent_rows"]), weights
        ),
    )


def _formula_den_present_absent(values: Mapping[str, object]) -> tuple[float, float]:
    weights = _seed_weight_map(values["seed_block_weights"])
    helped = cast(str, values["helped_label"])
    hurt = cast(str, values["hurt_label"])
    if (helped, hurt) != ("helped", "hurt"):
        raise ValueError("DEN-PRESENT-ABSENT labels differ from the freeze.")
    return denominator_present_absent(
        _weighted_outcome_rows(cast(Sequence[OutcomeRow], values["present_rows"]), weights),
        _weighted_outcome_rows(cast(Sequence[OutcomeRow], values["absent_rows"]), weights),
    )


def _formula_den_classifiable(values: Mapping[str, object]) -> float:
    rows = cast(Sequence[OutcomeRow], values["classifiable_divergences"])
    weights = _seed_weight_map(values["seed_block_weights"])
    return denominator_classifiable(_weighted_outcome_rows(rows, weights))


def _formula_den_all(values: Mapping[str, object]) -> float:
    rows = cast(Sequence[ComparisonRateRow], values["comparison_rows"])
    weights = _seed_weight_map(values["seed_block_weights"])
    return denominator_all_pairs(_weighted_rate_rows(rows, weights))


def _formula_miss_pair(values: Mapping[str, object]) -> GateStatus:
    return miss_pair20(
        n_total_pairs=cast(int, values["n_total_pairs"]),
        n_complete_pairs=cast(int, values["n_complete_pairs"]),
        n_fixed_missing_only=cast(int, values["n_fixed_missing_only"]),
        n_calibrated_missing_only=cast(int, values["n_calibrated_missing_only"]),
        n_both_missing=cast(int, values["n_both_missing"]),
        weighted_denominator=cast(float, values["weighted_paired_denominator"]),
        n_complete_seed_blocks=cast(int, values["n_complete_seed_blocks"]),
    )


def _formula_miss_divergent(values: Mapping[str, object]) -> GateStatus:
    n_mixed = cast(int, values["n_mixed"])
    n_unresolved = cast(int, values["n_unresolved"])
    if n_mixed < 0 or n_unresolved < 0:
        raise ValueError("MISS-DIVERGENT20 provenance counts must be non-negative.")
    return miss_divergent20(
        n_helped=cast(int, values["n_helped"]),
        n_hurt=cast(int, values["n_hurt"]),
        weighted_denominator=cast(float, values["weighted_divergent_denominator"]),
    )


def _formula_miss_two_rates(values: Mapping[str, object]) -> GateStatus:
    return miss_two_rates20(
        weighted_target_denominator=cast(float, values["weighted_target_denominator"]),
        weighted_comparator_denominator=cast(float, values["weighted_comparator_denominator"]),
        n_target_divergent_raw=cast(int, values["n_target_divergent_raw"]),
        n_comparator_divergent_raw=cast(int, values["n_comparator_divergent_raw"]),
    )


def _formula_miss_sequence(values: Mapping[str, object]) -> GateStatus:
    return miss_sequence30(
        weighted_present_denominator=cast(
            float, values["weighted_same_set_different_order_denominator"]
        ),
        weighted_absent_denominator=cast(float, values["weighted_other_divergence_denominator"]),
        n_present_raw=cast(int, values["n_same_set_different_order_raw"]),
        n_absent_raw=cast(int, values["n_other_divergence_raw"]),
    )


def _formula_miss_mechanism(values: Mapping[str, object]) -> GateStatus:
    n_mixed = cast(int, values["n_mixed"])
    n_unresolved = cast(int, values["n_unresolved"])
    if n_mixed < 0 or n_unresolved < 0:
        raise ValueError("MISS-MECHANISM20 provenance counts must be non-negative.")
    return miss_mechanism20(
        weighted_present_helped=cast(float, values["weighted_present_helped_sum"]),
        weighted_present_hurt=cast(float, values["weighted_present_hurt_sum"]),
        weighted_absent_helped=cast(float, values["weighted_absent_helped_sum"]),
        weighted_absent_hurt=cast(float, values["weighted_absent_hurt_sum"]),
        n_complete_seed_blocks=cast(int, values["n_complete_seed_blocks"]),
    )


def _formula_miss_dominance(values: Mapping[str, object]) -> GateStatus:
    return miss_dominance30(
        weighted_classifiable_denominator=cast(float, values["weighted_classifiable_denominator"]),
        n_classifiable_raw=cast(int, values["n_classifiable_raw"]),
    )


def _formula_miss_action(values: Mapping[str, object]) -> GateStatus:
    return miss_action25(
        weighted_present_denominator=cast(float, values["weighted_present_denominator"]),
        weighted_absent_denominator=cast(float, values["weighted_absent_denominator"]),
        n_present_raw=cast(int, values["n_present_raw"]),
        n_absent_raw=cast(int, values["n_absent_raw"]),
        block_support_counts=cast(
            Sequence[tuple[int, int, int]], values["five_block_support_counts"]
        ),
    )


def _formula_bootstrap(values: Mapping[str, object]) -> BootstrapReplicate:
    ordered = tuple(cast(Sequence[int], values["ordered_128_seed_blocks"]))
    if ordered != FULL_SEEDS:
        raise ValueError("bootstrap_10000 requires the exact frozen 128 seed blocks.")
    estimand = values["estimand_formula_id"]
    if not isinstance(estimand, ResamplingEstimand):
        raise TypeError("bootstrap_10000 requires a registered resampling estimand.")
    return bootstrap_replicate(
        cast(str, values["contrast_id"]),
        cast(int, values["replicate_index"]),
        estimand.evaluate_bootstrap,
    )


def _formula_sign_flip(values: Mapping[str, object]) -> SignFlipReplicate:
    ordered = tuple(cast(Sequence[int], values["ordered_paired_seed_blocks"]))
    if ordered != FULL_SEEDS:
        raise ValueError("signflip_10000 requires the exact frozen paired seed blocks.")
    estimand = values["estimand_formula_id"]
    if not isinstance(estimand, ResamplingEstimand):
        raise TypeError("signflip_10000 requires a registered resampling estimand.")
    return sign_flip_replicate(
        cast(str, values["contrast_id"]),
        cast(int, values["replicate_index"]),
        cast(float, values["observed_statistic"]),
        estimand.evaluate_sign_flip,
    )


def _formula_holm(values: Mapping[str, object]) -> tuple[HolmResult, ...]:
    ids = tuple(cast(Sequence[str], values["ordered_64_statistical_hypothesis_ids"]))
    p_values = cast(Mapping[str, float | None], values["p_raw"])
    order = tuple(cast(Sequence[str], values["statistical_hypothesis_order"]))
    expected = _frozen_resampling_ids()[2]
    if ids != expected or order != expected or set(p_values) != set(expected):
        raise ValueError("HOLM-64 inputs differ from the exact frozen family and order.")
    return holm_64(
        tuple(
            HolmInput(identifier, p_values[identifier], p_values[identifier] is not None)
            for identifier in ids
        )
    )


def _formula_integrity(values: Mapping[str, object]) -> GateStatus:
    ordered_ids = _formula_operand_registry()["F-INTEGRITY"]
    return f_integrity(tuple(cast(GateStatus, values[identifier]) for identifier in ordered_ids))


def _formula_core(values: Mapping[str, object]) -> GateStatus:
    return f_core(
        arm_runs=cast(int | None, values.get("COUNT-ARM-RUNS")),
        comparisons=cast(int | None, values.get("COUNT-COMPARISONS")),
        sigma_rows=cast(int | None, values.get("COUNT-SIGMA-ROWS")),
        contrast_rows=cast(int | None, values.get("COUNT-CONTRAST-ROWS")),
        all_foreign_keys_valid=cast(bool | None, values.get("FK-ALL")),
    )


def _formula_cal(values: Mapping[str, object]) -> GateStatus:
    return f_cal(
        nll=cast(ContrastInference, values["policy_nll"]),
        brier=cast(ContrastInference, values["policy_brier"]),
        ece=cast(ContrastInference, values["policy_ece"]),
        confidently_wrong=cast(ContrastInference, values["policy_confidently_wrong"]),
        true_probability=cast(ContrastInference, values["policy_true_probability"]),
    )


def _formula_and(values: Mapping[str, object]) -> GateStatus:
    return three_valued_and(cast(Sequence[GateStatus], values["ordered_gate_status_operands"]))


def _formula_hard_safety(values: Mapping[str, object]) -> GateStatus:
    ids = _formula_operand_registry()["F-HARD-SAFETY"]
    return f_hard_safety(tuple(cast(ContrastInference, values[identifier]) for identifier in ids))


def _formula_ctrl(values: Mapping[str, object]) -> GateStatus:
    return f_ctrl(
        nll=cast(ContrastInference, values["policy_nll"]),
        brier=cast(ContrastInference, values["policy_brier"]),
        true_probability=cast(ContrastInference, values["policy_true_probability"]),
        confidently_wrong=cast(ContrastInference, values["policy_confidently_wrong"]),
        helped_minus_hurt=cast(ContrastInference, values["policy_helped_minus_hurt"]),
        conditional_efficiency=cast(ContrastInference, values["policy_conditional_efficiency"]),
        end_to_end_efficiency=cast(ContrastInference, values["policy_end_to_end_efficiency"]),
        hard_safety=cast(GateStatus, values["G-HARD-SAFETY"]),
    )


def _formula_concentration(values: Mapping[str, object]) -> GateStatus:
    inference = ContrastInference(
        cast(float | None, values["contrast_estimate"]),
        cast(float | None, values["ci_low"]),
        None,
        cast(float | None, values["p_adjusted"]),
        "ESTIMATED"
        if all(values[item] is not None for item in ("contrast_estimate", "ci_low", "p_adjusted"))
        else "INCONCLUSIVE",
    )
    return f_concentration(
        target_count=cast(int | None, values["target_divergent_count"]),
        comparator_count=cast(int | None, values["comparator_divergent_count"]),
        contrast=inference,
    )


def _formula_dominance(values: Mapping[str, object]) -> GateStatus:
    return f_dominance(
        classifiable_count=cast(int | None, values.get("classifiable_count")),
        combined_share=cast(float | None, values.get("combined_primary_share")),
        ci_low=cast(float | None, values.get("ci_low")),
        score_flattening_share=cast(float | None, values.get("score_flattening_share")),
        group_sigma_reordering_share=cast(float | None, values.get("group_sigma_reordering_share")),
    )


def _formula_order(values: Mapping[str, object]) -> GateStatus:
    inference = ContrastInference(
        cast(float | None, values["contrast_estimate"]),
        cast(float | None, values["ci_low"]),
        None,
        cast(float | None, values["p_adjusted"]),
        "ESTIMATED"
        if all(values[item] is not None for item in ("contrast_estimate", "ci_low", "p_adjusted"))
        else "INCONCLUSIVE",
    )
    return f_order(
        present_count=cast(int | None, values["present_count"]),
        absent_count=cast(int | None, values["absent_count"]),
        contrast=inference,
    )


def _formula_action(values: Mapping[str, object]) -> GateStatus:
    decision = cast(ActionabilityComposite, values["decision_contrast"])
    source = cast(ContrastInference, values["source_confirmatory_contrast"])
    blocks = tuple(cast(Sequence[ActionabilityBlock], values["five_actionability_blocks"]))
    if decision.pooled != source or decision.blocks != blocks:
        raise ValueError("F-ACTION source and five-block operands do not reconcile.")
    return f_action(
        decision=decision,
        source=source,
        mechanism_allowed=cast(bool | None, values["mechanism_allowlist"]),
        truth_free_provenance=cast(bool | None, values["truth_free_provenance"]),
    )


def _formula_action_complete(values: Mapping[str, object]) -> ActionabilityResult:
    return f_action_complete(
        cast(Sequence[GateStatus], values["ordered_20_action_gate_statuses"]),
        _frozen_action_tuples(),
    )


def _formula_veto(values: Mapping[str, object]) -> str:
    source = values["source_tuple"]
    if not isinstance(source, ActionTuple):
        raise TypeError("F-VETO source_tuple must be an ActionTuple.")
    contrast_id = cast(str, values["required_veto_contrast_id"])
    expected = _veto_contrast_for(source)
    if contrast_id != expected:
        raise ValueError("F-VETO required contrast does not match its frozen source tuple.")
    interval = cast(Sequence[float | None], values["other_policy_ci"])
    if len(interval) != 2:
        raise ValueError("F-VETO other_policy_ci must contain lower and upper values.")
    support = values["support_counts"]
    if isinstance(support, Mapping):
        support_resolved = bool(support.get("resolved"))
    elif isinstance(support, bool):
        support_resolved = support
    else:
        raise TypeError("F-VETO support_counts must expose a resolved boolean.")
    return f_veto(
        own_effect=cast(float | None, values["own_effect"]),
        other_effect=cast(float | None, values["other_policy_effect"]),
        other_ci_low=interval[0],
        other_ci_high=interval[1],
        other_holm_p=cast(float | None, values["other_policy_holm_p"]),
        support_resolved=support_resolved,
    )


def _formula_veto_complete(values: Mapping[str, object]) -> DecisionBoolean:
    return f_veto_complete(
        cast(Sequence[ActionTuple], values["P_RAW"]),
        cast(Sequence[VetoResult], values["ordered_20_veto_evaluations"]),
    )


def _formula_partition(values: Mapping[str, object]) -> ActionPartition:
    return partition_action_tuples(
        cast(Sequence[ActionTuple], values["P_RAW"]),
        cast(Sequence[VetoResult], values["ordered_20_veto_evaluations"]),
    )


def _formula_unique(values: Mapping[str, object]) -> DecisionBoolean:
    partition = ActionPartition(
        (),
        tuple(cast(Sequence[ActionTuple], values["P"])),
        cast(DecisionBoolean, values["VETO_COMPLETE"]),
    )
    return unique_actionable_mechanism(partition)


def _formula_controller_change(values: Mapping[str, object]) -> DecisionBoolean:
    return controller_change_needed(
        integrity=cast(GateStatus, values["G-INTEGRITY"]),
        core=cast(GateStatus, values["G-CORE"]),
        calibration=cast(GateStatus, values["G-CAL-BOTH"]),
        controller=cast(GateStatus, values["G-CTRL-BOTH"]),
        hard_safety=cast(GateStatus, values["G-HARD-SAFETY"]),
    )


def _formula_ppo(values: Mapping[str, object]) -> DecisionBoolean:
    return f_ppo(
        integrity=cast(GateStatus, values["G-INTEGRITY"]),
        core=cast(GateStatus, values["G-CORE"]),
        calibration=cast(GateStatus, values["G-CAL-BOTH"]),
        controller=cast(GateStatus, values["G-CTRL-BOTH"]),
        hard_safety=cast(GateStatus, values["G-HARD-SAFETY"]),
        actionability_complete=DecisionBoolean.from_status(
            cast(GateStatus, values["G-ACTIONABILITY-COMPLETE"]),
            "G-ACTIONABILITY-COMPLETE",
        ),
        veto_complete=cast(DecisionBoolean, values["VETO_COMPLETE"]),
        surviving=cast(Sequence[ActionTuple], values["P"]),
        controller_change=cast(DecisionBoolean, values["CONTROLLER_CHANGE_NEEDED"]),
    )


def _formula_b_authorization(values: Mapping[str, object]) -> DecisionBoolean:
    p_raw = tuple(cast(Sequence[ActionTuple], values["P_RAW"]))
    vetoes = tuple(cast(Sequence[VetoResult], values["ordered_20_veto_evaluations"]))
    partition = partition_action_tuples(p_raw, vetoes)
    declared_veto = cast(DecisionBoolean, values["VETO_COMPLETE"])
    declared_p = tuple(cast(Sequence[ActionTuple], values["P"]))
    if partition.veto_complete.status is not declared_veto.status:
        raise ValueError("F-B-AUTHORIZATION VETO_COMPLETE does not reproduce.")
    if partition.surviving_tuples != declared_p:
        raise ValueError("F-B-AUTHORIZATION P does not reproduce from veto rows.")
    return b_authorized(
        controller_change_needed=cast(DecisionBoolean, values["CONTROLLER_CHANGE_NEEDED"]),
        actionability_complete=cast(DecisionBoolean, values["ACTIONABILITY_COMPLETE"]),
        partition=partition,
        unique_mechanism=cast(DecisionBoolean, values["UNIQUE_ACTIONABLE_MECHANISM"]),
    )


def _formula_decision(values: Mapping[str, object]) -> BranchDecision:
    branch_ids = tuple(
        cast(str, row["branch_id"])
        for row in cast(Sequence[Mapping[str, object]], values["ordered_branch_registry"])
    )
    expected = load_protocol_snapshot().registry("branch").ids("branch_id")
    if branch_ids != expected:
        raise ValueError("F-DECISION-TABLE branch registry differs from the freeze.")
    return final_decision(
        g_b_authorization=cast(GateStatus, values["G-B-AUTHORIZATION"]),
        b_authorization=cast(DecisionBoolean, values["B_AUTHORIZED"]),
        veto_complete=cast(DecisionBoolean, values["VETO_COMPLETE"]),
        controller_change_needed=cast(DecisionBoolean, values["CONTROLLER_CHANGE_NEEDED"]),
        ppo_eligible=cast(DecisionBoolean, values["PPO_ELIGIBLE"]),
    )


FORMULA_EXECUTORS: Final[dict[str, FormulaExecutor]] = {
    "NUM-CMF": _formula_num_cmf,
    "NUM-ECE": _formula_num_ece,
    "NUM-HELP-HURT": _formula_num_help_hurt,
    "NUM-HARM-RIGHT-LEFT": _formula_num_harm_right_left,
    "NUM-HARM-PRESENT-ABSENT": _formula_num_harm_present_absent,
    "NUM-COMBINED-SHARE": _formula_num_combined_share,
    "NUM-DIVERGENCE-RD": _formula_num_divergence,
    "NUM-ACTIONABILITY": _formula_num_actionability,
    "DEN-PAIRED": _formula_den_paired,
    "DEN-DIVERGENT": _formula_den_divergent,
    "DEN-TWO-DIVERGENT-RATES": _formula_den_two_rates,
    "DEN-PRESENT-ABSENT": _formula_den_present_absent,
    "DEN-CLASSIFIABLE": _formula_den_classifiable,
    "DEN-ALL-PAIRS": _formula_den_all,
    "MISS-PAIR20": _formula_miss_pair,
    "MISS-DIVERGENT20": _formula_miss_divergent,
    "MISS-TWO-RATES20": _formula_miss_two_rates,
    "MISS-SEQUENCE30": _formula_miss_sequence,
    "MISS-MECHANISM20": _formula_miss_mechanism,
    "MISS-DOMINANCE30": _formula_miss_dominance,
    "MISS-ACTION25": _formula_miss_action,
    "bootstrap_10000": _formula_bootstrap,
    "signflip_10000": _formula_sign_flip,
    "HOLM-64": _formula_holm,
    "F-INTEGRITY": _formula_integrity,
    "F-CORE": _formula_core,
    "F-CAL": _formula_cal,
    "F-AND": _formula_and,
    "F-HARD-SAFETY": _formula_hard_safety,
    "F-CTRL": _formula_ctrl,
    "F-CONCENTRATION": _formula_concentration,
    "F-DOMINANCE": _formula_dominance,
    "F-ORDER": _formula_order,
    "F-ACTION": _formula_action,
    "F-ACTION-COMPLETE": _formula_action_complete,
    "F-VETO": _formula_veto,
    "F-VETO-COMPLETE": _formula_veto_complete,
    "F-P": _formula_partition,
    "F-UNIQUE-MECHANISM": _formula_unique,
    "F-CONTROLLER-CHANGE": _formula_controller_change,
    "F-PPO": _formula_ppo,
    "F-B-AUTHORIZATION": _formula_b_authorization,
    "F-DECISION-TABLE": _formula_decision,
}


@dataclass(frozen=True, slots=True)
class RegisteredGateExecutor:
    gate_id: str
    formula_id: str

    def __call__(self, operands: Mapping[str, object]) -> object:
        return execute_formula(self.formula_id, operands)


def _build_gate_executors() -> dict[str, RegisteredGateExecutor]:
    snapshot = load_protocol_snapshot()
    return {
        row["gate_id"]: RegisteredGateExecutor(row["gate_id"], row["formula_id"])
        for row in snapshot.registry("gate").records()
    }


GATE_EXECUTORS: Final = _build_gate_executors()


@dataclass(frozen=True, slots=True)
class ContrastExecutionPlan:
    contrast_id: str
    estimand_id: str
    numerator_formula_id: str
    denominator_formula_id: str
    missingness_formula_id: str
    ci_formula_id: str | None
    permutation_formula_id: str | None


def contrast_execution_plans() -> tuple[ContrastExecutionPlan, ...]:
    snapshot = load_protocol_snapshot()
    records = (
        snapshot.registry("confirmatory").records()
        + snapshot.registry("decision").records()
        + snapshot.registry("descriptive").records()
    )
    return tuple(
        ContrastExecutionPlan(
            contrast_id=row["contrast_id"],
            estimand_id=row["estimand_id"],
            numerator_formula_id=row["numerator"],
            denominator_formula_id=row["denominator"],
            missingness_formula_id=row["missingness_rule"],
            ci_formula_id=(
                row["ci_method"] if row["ci_method"] not in {"none", "reuse_source"} else None
            ),
            permutation_formula_id=(
                row["permutation_method"]
                if row["permutation_method"] not in {"none", "reuse_source"}
                else None
            ),
        )
        for row in records
    )


ESTIMAND_EXECUTORS: Final[dict[str, FormulaExecutor]] = {
    "calibrated_minus_fixed": _formula_num_cmf,
    "helped_minus_hurt": _formula_num_help_hurt,
    "conditional_harm_difference": _formula_num_harm_right_left,
    "mechanism_harm_difference": _formula_num_harm_present_absent,
    "sequence_harm_difference": _formula_num_harm_right_left,
    "combined_primary_share": _formula_num_combined_share,
    "divergence_rate_difference": _formula_num_divergence,
    "actionability_composite": _formula_num_actionability,
}


def assert_executor_completeness() -> None:
    snapshot = load_protocol_snapshot()
    formula_ids = set(snapshot.registry("formula").ids("formula_id"))
    if set(FORMULA_EXECUTORS) != formula_ids:
        missing = sorted(formula_ids - set(FORMULA_EXECUTORS))
        extra = sorted(set(FORMULA_EXECUTORS) - formula_ids)
        raise ValueError(f"Formula executor ownership differs; missing={missing}, extra={extra}.")
    gate_rows = snapshot.registry("gate").records()
    gate_ids = {row["gate_id"] for row in gate_rows}
    if set(GATE_EXECUTORS) != gate_ids:
        raise ValueError("Gate evaluator ownership differs from the frozen registry.")
    for row in gate_rows:
        if GATE_EXECUTORS[row["gate_id"]].formula_id != row["formula_id"]:
            raise ValueError(f"Gate {row['gate_id']} is bound to the wrong formula.")
    estimand_ids = set(snapshot.registry("estimand").ids("estimand_id"))
    if set(ESTIMAND_EXECUTORS) != estimand_ids:
        raise ValueError("Estimand executor ownership differs from the frozen registry.")
    plans = contrast_execution_plans()
    if len(plans) != 122 or len({plan.contrast_id for plan in plans}) != 122:
        raise ValueError("Contrast execution plan registry is incomplete.")
    for plan in plans:
        formula_references = (
            plan.numerator_formula_id,
            plan.denominator_formula_id,
            plan.missingness_formula_id,
            plan.ci_formula_id,
            plan.permutation_formula_id,
        )
        if any(item is not None and item not in FORMULA_EXECUTORS for item in formula_references):
            raise ValueError(f"Contrast {plan.contrast_id} has an unowned executor reference.")


def _branch(
    branch_id: str,
    recommendation: str,
    b_status: str,
    c_status: str,
    d_status: str,
    *,
    valid: bool,
) -> BranchDecision:
    statuses = (
        ("BRANCH-B", b_status),
        ("BRANCH-C", c_status),
        ("BRANCH-D", d_status),
        ("BRANCH-A", "MATCH" if branch_id == "BRANCH-A" else "NO_MATCH"),
    )
    return BranchDecision(
        branch_id,
        recommendation,
        statuses,
        GateStatus.PASS if valid else GateStatus.FAIL,
    )


def _validate_replicate(replicate_index: int) -> None:
    if replicate_index not in range(10_000):
        raise ValueError("Frozen resampling replicate index must be 0 through 9999.")


def validate_seed_schedule() -> None:
    if tuple(range(1000, 1128)) != FULL_SEEDS:
        raise ValueError("Frozen 128-seed order changed.")
    sample = bootstrap_seed_ids("BR-C001", 0)
    if len(sample) != 128 or not set(sample).issubset(FULL_SEEDS):
        raise ValueError("INDEX128 generated an invalid bootstrap stream.")
