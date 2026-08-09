"""Complete registry-driven analysis path for the broader replication study."""

from __future__ import annotations

import math
from collections import Counter, OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final, Literal, cast

from research_decision_engine.benchmarks.broader_execution import (
    _IssuedAttestation,
    _require_issued_result_batch,
)
from research_decision_engine.benchmarks.broader_pipeline import (
    PairedRunResult,
    _pair_completed_runs_validated,
)
from research_decision_engine.benchmarks.broader_protocol import (
    FULL_SEEDS,
    ProtocolSnapshot,
    load_protocol_snapshot,
    protocol_hash,
)
from research_decision_engine.benchmarks.broader_runner import (
    ArmMetrics,
    BroaderArmRun,
    crossed_decision_traces,
    validate_recorded_calibration,
)
from research_decision_engine.benchmarks.broader_statistics import (
    ActionabilityBlock,
    ActionabilityComposite,
    ActionabilityResult,
    ActionPartition,
    ActionTuple,
    BootstrapReplicate,
    BranchDecision,
    ComparisonRateRow,
    ContrastInference,
    DecisionBoolean,
    EstimandDataset,
    FormulaExecutionTrace,
    GateStatus,
    HolmResult,
    OutcomeRow,
    PairedMetricRow,
    PairedProbabilityRow,
    ResamplingEstimand,
    SignFlipReplicate,
    VetoResult,
    execute_formula_traced,
)
from research_decision_engine.benchmarks.broader_worlds import CANDIDATES_BY_ID, WORLDS_BY_ID
from research_decision_engine.decision import DecisionTrace
from research_decision_engine.lookahead import LookaheadPlanTrace

POLICY_BY_SCOPE: Final = {
    "IG": "information_gain",
    "LA": "lookahead_information_gain",
}
ACTIONABLE_MECHANISMS: Final = (
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
)


@dataclass(frozen=True, slots=True)
class TruthFreeClassification:
    first_divergence_step: int
    fixed_candidate_id: str
    calibrated_candidate_id: str
    pre_divergence_fixed_belief: tuple[tuple[str, float], ...]
    pre_divergence_calibrated_belief: tuple[tuple[str, float], ...]
    first_action_divergent: bool
    sequence_class: str
    predicate_results: tuple[tuple[str, bool], ...]
    primary_mechanism_id: str
    contributing_mechanism_ids: tuple[str, ...]
    controller_stage_id: str
    mechanism_row_without_outcome_sha256: str


@dataclass(frozen=True, slots=True)
class AnalyzedComparison:
    paired: PairedRunResult
    truth_free: TruthFreeClassification | None

    @property
    def divergent(self) -> bool:
        return self.truth_free is not None


@dataclass(frozen=True, slots=True)
class ContrastComputation:
    contrast_id: str
    analysis_class: str
    research_question_id: str
    policy_scope: str
    population_scope: str
    metric_id: str
    estimand_id: str
    source_contrast_id: str | None
    missingness_counts: tuple[tuple[str, int], ...]
    n_present: int | None
    n_absent: int | None
    present_weight: float | None
    absent_weight: float | None
    left_value: float | None
    right_value: float | None
    left_denominator: float | None
    right_denominator: float | None
    estimate: float | None
    ci_low: float | None
    ci_high: float | None
    usable_bootstrap_replicates: int
    test_statistic: float | None
    permutation_count: int | None
    extreme_count: int | None
    p_raw: float | None
    p_adjusted: float | None
    holm_rank: int | None
    statistical_hypothesis_id: str | None
    holm_member: bool
    result_status: Literal["ESTIMATED", "INCONCLUSIVE"]
    estimability_status: Literal["estimated", "not_estimable"]
    inference: ContrastInference
    dataset: EstimandDataset | None
    actionability: ActionabilityComposite | None = None


@dataclass(frozen=True, slots=True)
class GateComputation:
    gate_id: str
    formula_id: str
    output: object
    trace: FormulaExecutionTrace

    @property
    def status(self) -> GateStatus:
        if isinstance(self.output, GateStatus):
            return self.output
        if isinstance(self.output, DecisionBoolean):
            return self.output.status
        if isinstance(self.output, ActionabilityResult):
            return self.output.actionability_complete.status
        if isinstance(self.output, BranchDecision):
            return self.output.gate_status
        raise TypeError(f"Gate {self.gate_id} produced an unsupported output.")


@dataclass(frozen=True, slots=True)
class ProductionAnalysisConfig:
    bootstrap_replicates: int = 10_000
    sign_flip_replicates: int = 10_000

    def __post_init__(self) -> None:
        if not 1 <= self.bootstrap_replicates <= 10_000:
            raise ValueError("Bootstrap replicate count must be 1 through 10,000.")
        if not 1 <= self.sign_flip_replicates <= 10_000:
            raise ValueError("Sign-flip replicate count must be 1 through 10,000.")


@dataclass(frozen=True, slots=True)
class PreGateAnalysisResult:
    """Temporary raw and derived scientific claims before any gate is evaluated."""

    comparisons: tuple[AnalyzedComparison, ...]
    contrasts: tuple[ContrastComputation, ...]
    bootstrap_rows: tuple[BootstrapReplicate, ...]
    sign_flip_rows: tuple[SignFlipReplicate, ...]
    holm_results: tuple[HolmResult, ...]
    formula_traces: tuple[FormulaExecutionTrace, ...]


@dataclass(frozen=True, slots=True)
class ProductionAnalysisResult:
    comparisons: tuple[AnalyzedComparison, ...]
    contrasts: tuple[ContrastComputation, ...]
    bootstrap_rows: tuple[BootstrapReplicate, ...]
    sign_flip_rows: tuple[SignFlipReplicate, ...]
    holm_results: tuple[HolmResult, ...]
    gates: tuple[GateComputation, ...]
    veto_results: tuple[VetoResult, ...]
    action_partition: ActionPartition
    actionability: ActionabilityResult
    decision: BranchDecision
    formula_traces: tuple[FormulaExecutionTrace, ...]

    def contrast(self, contrast_id: str) -> ContrastComputation:
        return next(item for item in self.contrasts if item.contrast_id == contrast_id)

    def gate(self, gate_id: str) -> GateComputation:
        return next(item for item in self.gates if item.gate_id == gate_id)


@dataclass(frozen=True, slots=True)
class _AnalysisBinding:
    analysis: PreGateAnalysisResult | ProductionAnalysisResult
    execution: _IssuedAttestation
    lineage: object


_ISSUED_ANALYSES: dict[int, _AnalysisBinding] = {}


def _register_analysis(
    analysis: PreGateAnalysisResult | ProductionAnalysisResult,
    execution: _IssuedAttestation,
    *,
    lineage: object | None = None,
) -> None:
    _ISSUED_ANALYSES[id(analysis)] = _AnalysisBinding(
        analysis,
        execution,
        object() if lineage is None else lineage,
    )


def _require_issued_analysis(
    analysis: PreGateAnalysisResult | ProductionAnalysisResult,
    *,
    runs: Sequence[BroaderArmRun] | None = None,
) -> _IssuedAttestation:
    binding = _ISSUED_ANALYSES.get(id(analysis))
    if binding is None or binding.analysis is not analysis:
        raise ValueError("Scientific analysis was not issued from an exact executor result batch.")
    execution = _require_issued_result_batch(
        binding.execution.returned_results,
        expected_purposes=(
            "production_conformance",
            "diagnostic_conformance",
            "full_study",
        ),
    )
    if execution is not binding.execution or (
        runs is not None and runs is not execution.returned_results
    ):
        raise ValueError("Scientific analysis belongs to another exact executor result batch.")
    return execution


def _issued_analysis_lineage(
    analysis: PreGateAnalysisResult | ProductionAnalysisResult,
) -> object:
    """Return the opaque lineage shared only by exact derived analysis stages."""

    _require_issued_analysis(analysis)
    return _ISSUED_ANALYSES[id(analysis)].lineage


def analyze_trajectories(
    runs: Sequence[BroaderArmRun],
    *,
    config: ProductionAnalysisConfig | None = None,
) -> ProductionAnalysisResult:
    """Run the production trajectory-to-decision path without persisting artifacts."""

    raw = analyze_scientific_artifacts(runs, config=config)
    return derive_provisional_analysis(raw, run_count=len(runs))


def analyze_scientific_artifacts(
    runs: Sequence[BroaderArmRun],
    *,
    config: ProductionAnalysisConfig | None = None,
) -> PreGateAnalysisResult:
    """Derive comparisons, contrasts, resampling, and Holm before gate execution."""

    execution = _require_issued_result_batch(
        runs,
        expected_purposes=(
            "production_conformance",
            "diagnostic_conformance",
            "full_study",
        ),
    )
    configuration = config or ProductionAnalysisConfig()
    snapshot = load_protocol_snapshot()
    comparisons = _analyze_comparisons(runs)
    traces: list[FormulaExecutionTrace] = []
    bootstrap_rows: list[BootstrapReplicate] = []
    sign_rows: list[SignFlipReplicate] = []
    computed: list[ContrastComputation] = []

    confirmatory_specs = snapshot.registry("confirmatory").records()
    for specification in confirmatory_specs:
        computation, new_bootstrap, new_signs, new_traces = _compute_confirmatory(
            specification,
            comparisons,
            configuration,
        )
        computed.append(computation)
        bootstrap_rows.extend(new_bootstrap)
        sign_rows.extend(new_signs)
        traces.extend(new_traces)

    holm_execution = execute_formula_traced(
        "HOLM-64",
        _ordered_operands(
            snapshot,
            "HOLM-64",
            {
                "ordered_64_statistical_hypothesis_ids": snapshot.registry(
                    "statistical_hypothesis"
                ).ids("statistical_hypothesis_id"),
                "p_raw": {
                    item.statistical_hypothesis_id: item.p_raw
                    for item in computed
                    if item.holm_member and item.statistical_hypothesis_id is not None
                },
                "statistical_hypothesis_order": snapshot.registry("statistical_hypothesis").ids(
                    "statistical_hypothesis_id"
                ),
            },
        ),
    )
    holm_results = cast(tuple[HolmResult, ...], holm_execution.output)
    traces.append(holm_execution.trace)
    holm_by_id = {item.statistical_hypothesis_id: item for item in holm_results}
    computed = [_apply_holm(item, holm_by_id) for item in computed]
    computed_by_id = {item.contrast_id: item for item in computed}

    for specification in snapshot.registry("decision").records():
        item, trace = _compute_decision_contrast(specification, comparisons, computed_by_id)
        computed.append(item)
        computed_by_id[item.contrast_id] = item
        traces.extend(trace)
    for specification in snapshot.registry("descriptive").records():
        item, trace = _compute_descriptive(specification, comparisons)
        computed.append(item)
        computed_by_id[item.contrast_id] = item
        traces.extend(trace)

    analysis = PreGateAnalysisResult(
        comparisons=comparisons,
        contrasts=tuple(computed),
        bootstrap_rows=tuple(bootstrap_rows),
        sign_flip_rows=tuple(sign_rows),
        holm_results=holm_results,
        formula_traces=tuple(traces),
    )
    _register_analysis(analysis, execution)
    return analysis


def derive_provisional_analysis(
    raw: PreGateAnalysisResult,
    *,
    run_count: int,
) -> ProductionAnalysisResult:
    """Derive gates and the provisional A/B/C/D decision after A01-A15."""

    execution = _require_issued_analysis(raw)
    snapshot = load_protocol_snapshot()
    computed_by_id = {item.contrast_id: item for item in raw.contrasts}
    (
        gates,
        veto_results,
        partition,
        actionability,
        decision,
        gate_traces,
    ) = _evaluate_gates(
        snapshot,
        computed_by_id,
        raw.comparisons,
        audit_statuses=None,
        run_count=run_count,
    )
    analysis = ProductionAnalysisResult(
        comparisons=raw.comparisons,
        contrasts=raw.contrasts,
        bootstrap_rows=raw.bootstrap_rows,
        sign_flip_rows=raw.sign_flip_rows,
        holm_results=raw.holm_results,
        gates=gates,
        veto_results=veto_results,
        action_partition=partition,
        actionability=actionability,
        decision=decision,
        formula_traces=(*raw.formula_traces, *gate_traces),
    )
    _register_analysis(
        analysis,
        execution,
        lineage=_issued_analysis_lineage(raw),
    )
    return analysis


def finalize_analysis_with_audits(
    analysis: ProductionAnalysisResult,
    audit_statuses: Mapping[str, GateStatus],
) -> ProductionAnalysisResult:
    """Recompute canonical gates and the final decision from executed audit results."""

    execution = _require_issued_analysis(analysis)
    snapshot = load_protocol_snapshot()
    expected_audits = snapshot.registry("audit").ids("audit_id")
    if tuple(audit_statuses) != expected_audits:
        raise ValueError("Final analysis requires all 16 audits in frozen order.")
    if any(status is not GateStatus.PASS for status in audit_statuses.values()):
        raise ValueError("Canonical analysis cannot finalize with a failed or unresolved audit.")
    contrast_by_id = {item.contrast_id: item for item in analysis.contrasts}
    (
        gates,
        veto_results,
        partition,
        actionability,
        decision,
        gate_traces,
    ) = _evaluate_gates(
        snapshot,
        contrast_by_id,
        analysis.comparisons,
        audit_statuses=audit_statuses,
        run_count=len(analysis.comparisons) * 2,
    )
    if decision != analysis.decision:
        raise ValueError("Final audited decision differs from the provisional decision.")
    finalized = replace(
        analysis,
        gates=gates,
        veto_results=veto_results,
        action_partition=partition,
        actionability=actionability,
        decision=decision,
        formula_traces=(*analysis.formula_traces, *gate_traces),
    )
    _register_analysis(
        finalized,
        execution,
        lineage=_issued_analysis_lineage(analysis),
    )
    return finalized


def recompute_provisional_decision(analysis: ProductionAnalysisResult) -> BranchDecision:
    """Independently rederive the provisional decision using local integrity PASS."""

    snapshot = load_protocol_snapshot()
    contrast_by_id = {item.contrast_id: item for item in analysis.contrasts}
    *_, decision, _ = _evaluate_gates(
        snapshot,
        contrast_by_id,
        analysis.comparisons,
        audit_statuses=None,
        run_count=len(analysis.comparisons) * 2,
    )
    return decision


def _analyze_comparisons(runs: Sequence[BroaderArmRun]) -> tuple[AnalyzedComparison, ...]:
    grouped: dict[str, list[BroaderArmRun]] = {}
    for run in runs:
        grouped.setdefault(run.comparison_id, []).append(run)
    truth_free: dict[str, TruthFreeClassification | None] = {}
    for comparison_id, pair in grouped.items():
        if len(pair) != 2:
            raise ValueError(f"Comparison {comparison_id} does not contain exactly two runs.")
        fixed = next(item for item in pair if item.arm.arm_id.startswith("fixed_"))
        calibrated = next(item for item in pair if item.arm.arm_id.startswith("calibrated_"))
        truth_free[comparison_id] = classify_truth_free(fixed, calibrated)
    evaluator_rows = _pair_completed_runs_validated(runs)
    return tuple(
        AnalyzedComparison(item, truth_free[item.comparison_id]) for item in evaluator_rows
    )


def classify_truth_free(
    fixed: BroaderArmRun, calibrated: BroaderArmRun
) -> TruthFreeClassification | None:
    # Classification can return before crossed scoring when trajectories are identical, so
    # validate both sigma paths here as the common scientific-analysis entry boundary.
    validate_recorded_calibration(fixed)
    validate_recorded_calibration(calibrated)
    left = fixed.selected_candidate_ids
    right = calibrated.selected_candidate_ids
    if left == right:
        return None
    limit = min(len(left), len(right))
    first = next((index for index in range(limit) if left[index] != right[index]), limit)
    fixed_candidate = left[first] if first < len(left) else "<terminal>"
    calibrated_candidate = right[first] if first < len(right) else "<terminal>"
    sequence_class = (
        "same_experiment_set_different_order"
        if set(left) == set(right)
        else "different_experiment_set"
    )
    first_action = first == 0
    fixed_belief = _belief_before(fixed, first)
    calibrated_belief = _belief_before(calibrated, first)
    traces = crossed_decision_traces(fixed, calibrated, zero_based_step=first)
    score_maps = {context: _trace_score_map(trace) for context, trace in traces.items()}
    winners = {context: next(iter(scores)) for context, scores in score_maps.items()}
    ranges = {
        context: max(cast(float, item["total"]) for item in scores.values())
        - min(cast(float, item["total"]) for item in scores.values())
        for context, scores in score_maps.items()
    }
    fixed_selected = fixed_candidate
    calibrated_selected = calibrated_candidate
    margins = {
        context: cast(float, scores[calibrated_selected]["total"])
        - cast(float, scores[fixed_selected]["total"])
        for context, scores in score_maps.items()
    }
    belief_contribution = 0.5 * ((margins["CF"] - margins["FF"]) + (margins["CC"] - margins["FC"]))
    sigma_contribution = 0.5 * ((margins["FC"] - margins["FF"]) + (margins["CC"] - margins["CF"]))
    interaction_value = margins["CC"] - margins["CF"] - margins["FC"] + margins["FF"]
    flattening = ranges["CC"] < ranges["FF"] - 1e-12 and winners["FC"] != winners["FF"]
    belief_reordering = winners["CF"] != winners["FF"]
    group_sigma_reordering = winners["FC"] != winners["FF"] and not flattening
    interaction = (
        winners["CC"] != winners["FF"]
        and winners["CF"] == winners["FF"]
        and winners["FC"] == winners["FF"]
        and abs(interaction_value) > 1e-12
    )
    cost_tiebreak = any(
        _ranking_stage(scores)
        in {
            "lower_expected_total_cost",
            "greater_information_gain_per_expected_cost",
            "stable_lexicographic_candidate_id",
        }
        for context, scores in score_maps.items()
        if context in {"FF", "CC"}
    )
    fixed_first_evidence = _first_evidence_step(fixed)
    calibrated_first_evidence = _first_evidence_step(calibrated)
    pair_delay = fixed_first_evidence is not None and (
        calibrated_first_evidence is None or calibrated_first_evidence > fixed_first_evidence
    )
    fixed_plan = score_maps["FF"][fixed_selected]
    calibrated_plan = score_maps["CC"][calibrated_selected]
    pair_opener_change = (
        fixed_plan["effect"] == "opens_pair"
        and calibrated_plan["effect"] == "opens_pair"
        and fixed_plan["group"] != calibrated_plan["group"]
    )
    same_set_order = sequence_class == "same_experiment_set_different_order"
    budget_crowd_out = set(left) != set(right) and len(left) != len(right)
    conservative = pair_delay or len(calibrated.evidence) < len(fixed.evidence)
    predicate_map = {
        "SCORE_FLATTENING": flattening,
        "BELIEF_STATE_REORDERING": belief_reordering,
        "GROUP_SIGMA_REORDERING": group_sigma_reordering,
        "BELIEF_SIGMA_INTERACTION": interaction,
        "COST_TIEBREAK_CHANGE": cost_tiebreak,
        "PAIR_COMPLETION_DELAY": pair_delay,
        "PAIR_OPENER_CHANGE": pair_opener_change,
        "SAME_SET_DIFFERENT_ORDER": same_set_order,
        "BUDGET_CROWD_OUT": budget_crowd_out,
        "CONSERVATIVE_NONCOMMITMENT": conservative,
    }
    numerical = [
        item
        for item in (
            "SCORE_FLATTENING",
            "BELIEF_STATE_REORDERING",
            "GROUP_SIGMA_REORDERING",
            "BELIEF_SIGMA_INTERACTION",
        )
        if predicate_map[item]
    ]
    if numerical:
        if "BELIEF_STATE_REORDERING" in numerical and any(
            item in numerical for item in ("SCORE_FLATTENING", "GROUP_SIGMA_REORDERING")
        ):
            if abs(belief_contribution) > abs(sigma_contribution) + 1e-12:
                primary = "BELIEF_STATE_REORDERING"
            elif "SCORE_FLATTENING" in numerical:
                primary = "SCORE_FLATTENING"
            else:
                primary = "GROUP_SIGMA_REORDERING"
        else:
            primary = next(item for item in ACTIONABLE_MECHANISMS if item in numerical)
    else:
        primary = next(
            (item for item in ACTIONABLE_MECHANISMS if predicate_map[item]),
            "NO_STABLE_MECHANISM",
        )
    contributing = [
        item for item in ACTIONABLE_MECHANISMS if item != primary and predicate_map[item]
    ]
    predicates = tuple((item, predicate_map[item]) for item in ACTIONABLE_MECHANISMS)
    hash_payload = {
        "comparison_id": fixed.comparison_id,
        "policy_id": fixed.arm.policy_id,
        "first_divergence_step": first + 1,
        "fixed_candidate_id": fixed_candidate,
        "calibrated_candidate_id": calibrated_candidate,
        "fixed_sequence": list(left),
        "calibrated_sequence": list(right),
        "first_action_divergent": first_action,
        "sequence_class": sequence_class,
        "predicate_results": dict(predicates),
        "primary_mechanism_id": primary,
        "contributing_mechanism_ids": contributing,
        "controller_stage_id": "CONTROLLER-STAGE-SELECTION",
    }
    return TruthFreeClassification(
        first + 1,
        fixed_candidate,
        calibrated_candidate,
        fixed_belief,
        calibrated_belief,
        first_action,
        sequence_class,
        predicates,
        primary,
        tuple(contributing),
        "CONTROLLER-STAGE-SELECTION",
        protocol_hash("truth_free_mechanism_row/v1", hash_payload),
    )


def _trace_score_map(
    trace: DecisionTrace | LookaheadPlanTrace,
) -> dict[str, dict[str, float | str]]:
    scores: dict[str, dict[str, float | str]] = {}
    if isinstance(trace, DecisionTrace):
        for item in trace.ranked_candidates:
            candidate_id = item.candidate.candidate_id
            cost = item.estimated_cost
            total = item.expected_information_gain
            assessment = (
                "completes_pair"
                if item.completes_matched_pair
                else ("opens_pair" if "opens" in item.score_reason.lower() else "ineligible")
            )
            scores[candidate_id] = {
                "immediate": total,
                "total": total,
                "cost": cost,
                "ratio": total / cost if cost > 0.0 else 0.0,
                "effect": assessment,
                "group": CANDIDATES_BY_ID[candidate_id].comparison_group_id,
            }
        return scores
    selected = trace.selected
    scores[selected.candidate.candidate_id] = {
        "immediate": selected.immediate_information_gain,
        "total": selected.expected_total_information_gain,
        "cost": selected.expected_total_cost,
        "ratio": selected.information_gain_per_expected_cost,
        "effect": selected.action_effect,
        "group": selected.public_design.comparison_group_id,
    }
    for alternative in trace.alternatives:
        scores[alternative.candidate.candidate_id] = {
            "immediate": alternative.immediate_information_gain,
            "total": alternative.expected_total_information_gain,
            "cost": alternative.expected_total_cost,
            "ratio": alternative.information_gain_per_expected_cost,
            "effect": alternative.action_effect,
            "group": alternative.comparison_group_id,
        }
    return dict(
        sorted(
            scores.items(),
            key=lambda item: (
                -cast(float, item[1]["total"]),
                cast(float, item[1]["cost"]),
                -cast(float, item[1]["ratio"]),
                item[0],
            ),
        )
    )


def _ranking_stage(scores: Mapping[str, Mapping[str, float | str]]) -> str:
    ordered = tuple(scores.items())
    if len(ordered) < 2:
        return "only_candidate"
    winner = ordered[0][1]
    top = tuple(
        item
        for item in ordered
        if abs(cast(float, item[1]["total"]) - cast(float, winner["total"])) <= 1e-12
    )
    if len(top) == 1:
        return "greater_expected_total_information_gain"
    minimum_cost = min(cast(float, item[1]["cost"]) for item in top)
    cost_tied = tuple(
        item for item in top if abs(cast(float, item[1]["cost"]) - minimum_cost) <= 1e-12
    )
    if len(cost_tied) == 1:
        return "lower_expected_total_cost"
    maximum_ratio = max(cast(float, item[1]["ratio"]) for item in cost_tied)
    ratio_tied = tuple(
        item for item in cost_tied if abs(cast(float, item[1]["ratio"]) - maximum_ratio) <= 1e-12
    )
    return (
        "greater_information_gain_per_expected_cost"
        if len(ratio_tied) == 1
        else "stable_lexicographic_candidate_id"
    )


def _first_evidence_step(run: BroaderArmRun) -> int | None:
    return next((item.step for item in run.actions if item.new_evidence_ids), None)


def _belief_before(run: BroaderArmRun, zero_based_action: int) -> tuple[tuple[str, float], ...]:
    if zero_based_action == 0:
        return run.initial_probabilities
    if zero_based_action - 1 < len(run.actions):
        return run.actions[zero_based_action - 1].posterior_probabilities
    return run.final_probabilities


def _optimizer_group(candidate_id: str) -> str | None:
    return candidate_id[:3] if candidate_id.startswith("g") else None


def _compute_confirmatory(
    specification: Mapping[str, str],
    comparisons: Sequence[AnalyzedComparison],
    config: ProductionAnalysisConfig,
) -> tuple[
    ContrastComputation,
    tuple[BootstrapReplicate, ...],
    tuple[SignFlipReplicate, ...],
    tuple[FormulaExecutionTrace, ...],
]:
    dataset, metadata, formula_traces = _build_dataset(specification, comparisons)
    missing_status = metadata["missing_status"]
    estimate = cast(float | None, metadata["estimate"])
    result_status: Literal["ESTIMATED", "INCONCLUSIVE"] = (
        "ESTIMATED"
        if missing_status is GateStatus.PASS and estimate is not None
        else "INCONCLUSIVE"
    )
    estimand = ResamplingEstimand(specification["estimand_id"], dataset)
    bootstrap: list[BootstrapReplicate] = []
    signs: list[SignFlipReplicate] = []
    traces = list(formula_traces)
    for replicate_index in range(config.bootstrap_replicates):
        execution = execute_formula_traced(
            "bootstrap_10000",
            _ordered_operands(
                load_protocol_snapshot(),
                "bootstrap_10000",
                {
                    "contrast_id": specification["contrast_id"],
                    "replicate_index": replicate_index,
                    "ordered_128_seed_blocks": FULL_SEEDS,
                    "estimand_formula_id": estimand,
                },
            ),
        )
        bootstrap.append(cast(BootstrapReplicate, execution.output))
        traces.append(execution.trace)
    valid_estimates = sorted(item.estimate for item in bootstrap if item.estimate is not None)
    required = math.ceil(0.95 * config.bootstrap_replicates)
    ci_low: float | None = None
    ci_high: float | None = None
    if result_status == "ESTIMATED" and len(valid_estimates) >= required:
        ci_low = valid_estimates[math.ceil(0.025 * len(valid_estimates)) - 1]
        ci_high = valid_estimates[math.ceil(0.975 * len(valid_estimates)) - 1]
    else:
        result_status = "INCONCLUSIVE"
    p_raw: float | None = None
    extreme_count: int | None = None
    if specification["holm_member"] == "true":
        for replicate_index in range(config.sign_flip_replicates):
            execution = execute_formula_traced(
                "signflip_10000",
                _ordered_operands(
                    load_protocol_snapshot(),
                    "signflip_10000",
                    {
                        "contrast_id": specification["contrast_id"],
                        "replicate_index": replicate_index,
                        "ordered_paired_seed_blocks": FULL_SEEDS,
                        "observed_statistic": estimate if estimate is not None else 0.0,
                        "estimand_formula_id": estimand,
                    },
                ),
            )
            signs.append(cast(SignFlipReplicate, execution.output))
            traces.append(execution.trace)
        if result_status == "ESTIMATED" and all(item.extreme is not None for item in signs):
            extreme_count = sum(bool(item.extreme) for item in signs)
            p_raw = (1 + extreme_count) / (config.sign_flip_replicates + 1)
        else:
            result_status = "INCONCLUSIVE"
            ci_low = None
            ci_high = None
    inference = ContrastInference(
        estimate if result_status == "ESTIMATED" else None, ci_low, ci_high, None, result_status
    )
    item = _contrast_from_metadata(
        specification,
        metadata,
        inference,
        dataset,
        usable_bootstrap=len(valid_estimates),
        permutation_count=config.sign_flip_replicates if p_raw is not None else None,
        extreme_count=extreme_count,
        p_raw=p_raw,
    )
    return item, tuple(bootstrap), tuple(signs), tuple(traces)


def _build_dataset(
    specification: Mapping[str, str], comparisons: Sequence[AnalyzedComparison]
) -> tuple[EstimandDataset, dict[str, object], tuple[FormulaExecutionTrace, ...]]:
    eligible = tuple(item for item in comparisons if _eligible(specification, item))
    weights = {seed: 1.0 for seed in FULL_SEEDS}
    metric_rows: list[PairedMetricRow] = []
    probability_rows: list[PairedProbabilityRow] = []
    outcomes: list[OutcomeRow] = []
    rates: list[ComparisonRateRow] = []
    for item in eligible:
        weight = _population_weight(specification["population_scope"], item)
        paired = item.paired
        fixed_value = _metric_value(paired.fixed_metrics, specification["metric_id"])
        calibrated_value = _metric_value(paired.calibrated_metrics, specification["metric_id"])
        metric_rows.append(
            PairedMetricRow(
                paired.comparison_id, paired.seed, weight, fixed_value, calibrated_value
            )
        )
        probability_rows.append(
            PairedProbabilityRow(
                paired.comparison_id,
                paired.seed,
                weight,
                paired.fixed_metrics.top_probability,
                paired.fixed_metrics.prediction_correct,
                paired.calibrated_metrics.top_probability,
                paired.calibrated_metrics.prediction_correct,
            )
        )
        outcomes.append(
            OutcomeRow(
                paired.comparison_id,
                paired.seed,
                weight,
                paired.outcome_label if item.divergent else "nondivergent",
                item.divergent,
                item.truth_free.primary_mechanism_id if item.truth_free is not None else None,
            )
        )
        rate_value = (
            item.truth_free.first_action_divergent
            if specification["metric_id"] == "first_action_divergence" and item.truth_free
            else item.divergent
        )
        rates.append(ComparisonRateRow(paired.comparison_id, paired.seed, weight, rate_value))

    estimand_id = specification["estimand_id"]
    traces: list[FormulaExecutionTrace] = []
    metadata: dict[str, object] = {
        "missingness_counts": (),
        "n_present": None,
        "n_absent": None,
        "present_weight": None,
        "absent_weight": None,
        "left_value": None,
        "right_value": None,
        "left_denominator": None,
        "right_denominator": None,
        "estimate": None,
        "missing_status": GateStatus.INCONCLUSIVE,
    }
    dataset = EstimandDataset(estimand_id, specification["metric_id"])
    if estimand_id == "calibrated_minus_fixed":
        dataset = replace(
            dataset,
            paired_metric_rows=tuple(metric_rows),
            paired_probability_rows=tuple(probability_rows),
        )
        complete = tuple(
            row.fixed_value is not None and row.calibrated_value is not None for row in metric_rows
        )
        denominator_execution = execute_formula_traced(
            "DEN-PAIRED",
            _ordered_operands(
                load_protocol_snapshot(),
                "DEN-PAIRED",
                {
                    "paired_rows": tuple(metric_rows),
                    "complete_pair_indicator": complete,
                    "seed_block_weights": weights,
                },
            ),
        )
        denominator = cast(float, denominator_execution.output)
        complete_seeds = len(
            {row.seed for row, flag in zip(metric_rows, complete, strict=True) if flag}
        )
        missing = {
            "n_total_pairs": len(metric_rows),
            "n_complete_pairs": sum(complete),
            "n_fixed_missing_only": sum(
                row.fixed_value is None and row.calibrated_value is not None for row in metric_rows
            ),
            "n_calibrated_missing_only": sum(
                row.fixed_value is not None and row.calibrated_value is None for row in metric_rows
            ),
            "n_both_missing": sum(
                row.fixed_value is None and row.calibrated_value is None for row in metric_rows
            ),
        }
        missing_execution = execute_formula_traced(
            "MISS-PAIR20",
            _ordered_operands(
                load_protocol_snapshot(),
                "MISS-PAIR20",
                {
                    **missing,
                    "weighted_paired_denominator": denominator,
                    "n_complete_seed_blocks": complete_seeds,
                },
            ),
        )
        if missing_execution.output is GateStatus.PASS:
            numerator_id = "NUM-ECE" if specification["metric_id"] == "ece" else "NUM-CMF"
            numerator_values: dict[str, object] = (
                {
                    "paired_probability_rows": tuple(probability_rows),
                    "ece_bin_edges": tuple(index / 10.0 for index in range(11)),
                    "seed_block_weights": weights,
                }
                if numerator_id == "NUM-ECE"
                else {
                    "paired_rows": tuple(metric_rows),
                    "metric_id": specification["metric_id"],
                    "seed_block_weights": weights,
                }
            )
            numerator_execution = execute_formula_traced(
                numerator_id,
                _ordered_operands(load_protocol_snapshot(), numerator_id, numerator_values),
            )
            metadata["estimate"] = numerator_execution.output
            traces.append(numerator_execution.trace)
        metadata.update(
            missingness_counts=tuple(missing.items()),
            left_denominator=denominator,
            right_denominator=denominator,
            missing_status=missing_execution.output,
        )
        traces.extend((denominator_execution.trace, missing_execution.trace))
    elif estimand_id == "helped_minus_hurt":
        dataset = replace(dataset, outcome_rows=tuple(outcomes))
        classifiable = tuple(
            row for row in outcomes if row.divergent and row.outcome_label in {"helped", "hurt"}
        )
        denominator_execution = execute_formula_traced(
            "DEN-DIVERGENT",
            _ordered_operands(
                load_protocol_snapshot(),
                "DEN-DIVERGENT",
                {
                    "divergent_outcome_rows": tuple(outcomes),
                    "seed_block_weights": weights,
                    "helped_label": "helped",
                    "hurt_label": "hurt",
                },
            ),
        )
        counts = Counter(row.outcome_label for row in outcomes if row.divergent)
        missing_execution = execute_formula_traced(
            "MISS-DIVERGENT20",
            _ordered_operands(
                load_protocol_snapshot(),
                "MISS-DIVERGENT20",
                {
                    "n_helped": counts["helped"],
                    "n_hurt": counts["hurt"],
                    "n_mixed": counts["mixed"],
                    "n_unresolved": counts[None],
                    "weighted_divergent_denominator": denominator_execution.output,
                },
            ),
        )
        if missing_execution.output is GateStatus.PASS:
            numerator_execution = execute_formula_traced(
                "NUM-HELP-HURT",
                _ordered_operands(
                    load_protocol_snapshot(),
                    "NUM-HELP-HURT",
                    {
                        "divergent_outcome_rows": tuple(outcomes),
                        "seed_block_weights": weights,
                        "helped_label": "helped",
                        "hurt_label": "hurt",
                        "mixed_label": "mixed",
                    },
                ),
            )
            metadata["estimate"] = numerator_execution.output
            traces.append(numerator_execution.trace)
        metadata.update(
            missingness_counts=tuple(
                (f"n_{key}", counts[key]) for key in ("helped", "hurt", "mixed")
            ),
            left_denominator=denominator_execution.output,
            right_denominator=denominator_execution.output,
            missing_status=missing_execution.output,
        )
        traces.extend((denominator_execution.trace, missing_execution.trace))
    elif estimand_id in {"conditional_harm_difference", "sequence_harm_difference"}:
        right, left = _split_right_left(specification, eligible, outcomes)
        dataset = replace(dataset, right_outcome_rows=right, left_outcome_rows=left)
        denominator_execution = execute_formula_traced(
            "DEN-TWO-DIVERGENT-RATES",
            _ordered_operands(
                load_protocol_snapshot(),
                "DEN-TWO-DIVERGENT-RATES",
                {
                    "target_divergent_rows": right,
                    "comparator_divergent_rows": left,
                    "seed_block_weights": weights,
                    "helped_label": "helped",
                    "hurt_label": "hurt",
                },
            ),
        )
        right_den, left_den = cast(tuple[float, float], denominator_execution.output)
        right_count = sum(row.outcome_label in {"helped", "hurt"} for row in right)
        left_count = sum(row.outcome_label in {"helped", "hurt"} for row in left)
        missing_id = (
            "MISS-SEQUENCE30" if estimand_id == "sequence_harm_difference" else "MISS-TWO-RATES20"
        )
        missing_values = (
            {
                "weighted_same_set_different_order_denominator": right_den,
                "weighted_other_divergence_denominator": left_den,
                "n_same_set_different_order_raw": right_count,
                "n_other_divergence_raw": left_count,
            }
            if missing_id == "MISS-SEQUENCE30"
            else {
                "weighted_target_denominator": right_den,
                "weighted_comparator_denominator": left_den,
                "n_target_divergent_raw": right_count,
                "n_comparator_divergent_raw": left_count,
            }
        )
        missing_execution = execute_formula_traced(
            missing_id,
            _ordered_operands(load_protocol_snapshot(), missing_id, missing_values),
        )
        if missing_execution.output is GateStatus.PASS:
            numerator_execution = execute_formula_traced(
                "NUM-HARM-RIGHT-LEFT",
                _ordered_operands(
                    load_protocol_snapshot(),
                    "NUM-HARM-RIGHT-LEFT",
                    {
                        "right_population_rows": right,
                        "left_population_rows": left,
                        "seed_block_weights": weights,
                    },
                ),
            )
            metadata["estimate"] = numerator_execution.output
            traces.append(numerator_execution.trace)
        metadata.update(
            missingness_counts=(("n_right", right_count), ("n_left", left_count)),
            n_present=right_count,
            n_absent=left_count,
            present_weight=right_den,
            absent_weight=left_den,
            left_denominator=left_den,
            right_denominator=right_den,
            missing_status=missing_execution.output,
        )
        traces.extend((denominator_execution.trace, missing_execution.trace))
    elif estimand_id == "mechanism_harm_difference":
        mechanism = _mechanism_for(specification)
        present = tuple(
            row for row in outcomes if row.divergent and row.primary_mechanism_id == mechanism
        )
        absent = tuple(
            row for row in outcomes if row.divergent and row.primary_mechanism_id != mechanism
        )
        dataset = replace(dataset, present_outcome_rows=present, absent_outcome_rows=absent)
        denominator_execution = execute_formula_traced(
            "DEN-PRESENT-ABSENT",
            _ordered_operands(
                load_protocol_snapshot(),
                "DEN-PRESENT-ABSENT",
                {
                    "present_rows": present,
                    "absent_rows": absent,
                    "seed_block_weights": weights,
                    "helped_label": "helped",
                    "hurt_label": "hurt",
                },
            ),
        )
        present_den, absent_den = cast(tuple[float, float], denominator_execution.output)
        classifiable = tuple(
            row for row in (*present, *absent) if row.outcome_label in {"helped", "hurt"}
        )
        counts = Counter(row.outcome_label for row in outcomes if row.divergent)
        missing_execution = execute_formula_traced(
            "MISS-MECHANISM20",
            _ordered_operands(
                load_protocol_snapshot(),
                "MISS-MECHANISM20",
                {
                    "weighted_present_helped_sum": math.fsum(
                        row.weight for row in present if row.outcome_label == "helped"
                    ),
                    "weighted_present_hurt_sum": math.fsum(
                        row.weight for row in present if row.outcome_label == "hurt"
                    ),
                    "weighted_absent_helped_sum": math.fsum(
                        row.weight for row in absent if row.outcome_label == "helped"
                    ),
                    "weighted_absent_hurt_sum": math.fsum(
                        row.weight for row in absent if row.outcome_label == "hurt"
                    ),
                    "n_complete_seed_blocks": len({row.seed for row in classifiable}),
                    "n_mixed": counts["mixed"],
                    "n_unresolved": counts[None],
                },
            ),
        )
        if missing_execution.output is GateStatus.PASS:
            numerator_execution = execute_formula_traced(
                "NUM-HARM-PRESENT-ABSENT",
                _ordered_operands(
                    load_protocol_snapshot(),
                    "NUM-HARM-PRESENT-ABSENT",
                    {
                        "mechanism_present_rows": present,
                        "mechanism_absent_rows": absent,
                        "seed_block_weights": weights,
                    },
                ),
            )
            metadata["estimate"] = numerator_execution.output
            traces.append(numerator_execution.trace)
        metadata.update(
            missingness_counts=(("n_mixed", counts["mixed"]), ("n_unresolved", counts[None])),
            n_present=len(present),
            n_absent=len(absent),
            present_weight=present_den,
            absent_weight=absent_den,
            left_denominator=absent_den,
            right_denominator=present_den,
            missing_status=missing_execution.output,
        )
        traces.extend((denominator_execution.trace, missing_execution.trace))
    elif estimand_id == "combined_primary_share":
        classifiable = tuple(row for row in outcomes if row.divergent and row.primary_mechanism_id)
        dataset = replace(dataset, classifiable_rows=classifiable)
        denominator_execution = execute_formula_traced(
            "DEN-CLASSIFIABLE",
            _ordered_operands(
                load_protocol_snapshot(),
                "DEN-CLASSIFIABLE",
                {"classifiable_divergences": classifiable, "seed_block_weights": weights},
            ),
        )
        denominator = cast(float, denominator_execution.output)
        missing_execution = execute_formula_traced(
            "MISS-DOMINANCE30",
            _ordered_operands(
                load_protocol_snapshot(),
                "MISS-DOMINANCE30",
                {
                    "weighted_classifiable_denominator": denominator,
                    "n_classifiable_raw": len(classifiable),
                },
            ),
        )
        if missing_execution.output is GateStatus.PASS:
            policy = specification["policy_scope"]
            count_values = {
                "weighted_classifiable_denominator": denominator,
                "COUNT-PRIMARY-SF-IG": math.fsum(
                    row.weight
                    for row in classifiable
                    if row.primary_mechanism_id == "SCORE_FLATTENING"
                )
                if policy == "IG"
                else None,
                "COUNT-PRIMARY-GSR-IG": math.fsum(
                    row.weight
                    for row in classifiable
                    if row.primary_mechanism_id == "GROUP_SIGMA_REORDERING"
                )
                if policy == "IG"
                else None,
                "COUNT-PRIMARY-SF-LA": math.fsum(
                    row.weight
                    for row in classifiable
                    if row.primary_mechanism_id == "SCORE_FLATTENING"
                )
                if policy == "LA"
                else None,
                "COUNT-PRIMARY-GSR-LA": math.fsum(
                    row.weight
                    for row in classifiable
                    if row.primary_mechanism_id == "GROUP_SIGMA_REORDERING"
                )
                if policy == "LA"
                else None,
            }
            numerator_execution = execute_formula_traced(
                "NUM-COMBINED-SHARE",
                _ordered_operands(load_protocol_snapshot(), "NUM-COMBINED-SHARE", count_values),
            )
            metadata["estimate"] = numerator_execution.output
            traces.append(numerator_execution.trace)
        metadata.update(
            missingness_counts=(("n_classifiable", len(classifiable)),),
            left_denominator=denominator,
            right_denominator=denominator,
            missing_status=missing_execution.output,
        )
        traces.extend((denominator_execution.trace, missing_execution.trace))
    elif estimand_id == "divergence_rate_difference":
        target, comparator = _split_rate_rows(specification, eligible, rates)
        dataset = replace(dataset, target_rate_rows=target, comparator_rate_rows=comparator)
        denominator_execution = execute_formula_traced(
            "DEN-ALL-PAIRS",
            _ordered_operands(
                load_protocol_snapshot(),
                "DEN-ALL-PAIRS",
                {"comparison_rows": (*target, *comparator), "seed_block_weights": weights},
            ),
        )
        target_den = math.fsum(row.weight for row in target)
        comparator_den = math.fsum(row.weight for row in comparator)
        missing_execution = execute_formula_traced(
            "MISS-TWO-RATES20",
            _ordered_operands(
                load_protocol_snapshot(),
                "MISS-TWO-RATES20",
                {
                    "weighted_target_denominator": target_den,
                    "weighted_comparator_denominator": comparator_den,
                    "n_target_divergent_raw": sum(bool(row.divergent) for row in target),
                    "n_comparator_divergent_raw": sum(bool(row.divergent) for row in comparator),
                },
            ),
        )
        if missing_execution.output is GateStatus.PASS:
            numerator_execution = execute_formula_traced(
                "NUM-DIVERGENCE-RD",
                _ordered_operands(
                    load_protocol_snapshot(),
                    "NUM-DIVERGENCE-RD",
                    {
                        "target_pairs": target,
                        "comparator_pairs": comparator,
                        "seed_block_weights": weights,
                    },
                ),
            )
            metadata["estimate"] = numerator_execution.output
            traces.append(numerator_execution.trace)
        metadata.update(
            missingness_counts=(("n_target", len(target)), ("n_comparator", len(comparator))),
            left_denominator=comparator_den,
            right_denominator=target_den,
            missing_status=missing_execution.output,
        )
        traces.extend((denominator_execution.trace, missing_execution.trace))
    else:
        raise ValueError(f"Unsupported frozen estimand {estimand_id}.")
    return dataset, metadata, tuple(traces)


def _compute_decision_contrast(
    specification: Mapping[str, str],
    comparisons: Sequence[AnalyzedComparison],
    computed: Mapping[str, ContrastComputation],
) -> tuple[ContrastComputation, tuple[FormulaExecutionTrace, ...]]:
    source = computed[specification["source_contrast_id"]]
    source_inference = source.inference
    blocks = _actionability_blocks(specification, comparisons)
    total = (source.n_present or 0) + (source.n_absent or 0)
    composite = ActionabilityComposite(
        source_inference,
        source.n_present,
        source.n_absent,
        source.present_weight,
        source.absent_weight,
        (source.n_present or 0) / total if total else None,
        blocks,
    )
    execution = execute_formula_traced(
        "NUM-ACTIONABILITY",
        _ordered_operands(
            load_protocol_snapshot(),
            "NUM-ACTIONABILITY",
            {
                "decision_contrast_rows": composite,
                "five_block_rows": blocks,
                "source_confirmatory_row": source_inference,
            },
        ),
    )
    status = source.result_status
    item = ContrastComputation(
        specification["contrast_id"],
        specification["analysis_class"],
        specification["research_question_id"],
        specification["policy_scope"],
        specification["population_scope"],
        specification["metric_id"],
        specification["estimand_id"],
        specification["source_contrast_id"],
        source.missingness_counts,
        source.n_present,
        source.n_absent,
        source.present_weight,
        source.absent_weight,
        source.left_value,
        source.right_value,
        source.left_denominator,
        source.right_denominator,
        source.estimate,
        source.ci_low,
        source.ci_high,
        0,
        source.test_statistic,
        source.permutation_count,
        source.extreme_count,
        source.p_raw,
        source.p_adjusted,
        source.holm_rank,
        None,
        False,
        status,
        "estimated" if status == "ESTIMATED" else "not_estimable",
        source_inference,
        None,
        cast(ActionabilityComposite, execution.output),
    )
    return item, (execution.trace,)


def _compute_descriptive(
    specification: Mapping[str, str], comparisons: Sequence[AnalyzedComparison]
) -> tuple[ContrastComputation, tuple[FormulaExecutionTrace, ...]]:
    dataset, metadata, traces = _build_dataset(specification, comparisons)
    estimate = cast(float | None, metadata["estimate"])
    status: Literal["ESTIMATED", "INCONCLUSIVE"] = (
        "ESTIMATED"
        if metadata["missing_status"] is GateStatus.PASS and estimate is not None
        else "INCONCLUSIVE"
    )
    inference = ContrastInference(
        estimate if status == "ESTIMATED" else None, None, None, None, status
    )
    return (
        _contrast_from_metadata(
            specification,
            metadata,
            inference,
            dataset,
            usable_bootstrap=0,
            permutation_count=None,
            extreme_count=None,
            p_raw=None,
        ),
        traces,
    )


def _contrast_from_metadata(
    specification: Mapping[str, str],
    metadata: Mapping[str, object],
    inference: ContrastInference,
    dataset: EstimandDataset,
    *,
    usable_bootstrap: int,
    permutation_count: int | None,
    extreme_count: int | None,
    p_raw: float | None,
) -> ContrastComputation:
    status = inference.result_status
    return ContrastComputation(
        specification["contrast_id"],
        specification["analysis_class"],
        specification["research_question_id"],
        specification["policy_scope"],
        specification["population_scope"],
        specification["metric_id"],
        specification["estimand_id"],
        None
        if specification["source_contrast_id"] == "null"
        else specification["source_contrast_id"],
        cast(tuple[tuple[str, int], ...], metadata["missingness_counts"]),
        cast(int | None, metadata["n_present"]),
        cast(int | None, metadata["n_absent"]),
        cast(float | None, metadata["present_weight"]),
        cast(float | None, metadata["absent_weight"]),
        cast(float | None, metadata["left_value"]),
        cast(float | None, metadata["right_value"]),
        cast(float | None, metadata["left_denominator"]),
        cast(float | None, metadata["right_denominator"]),
        inference.estimate,
        inference.ci_low,
        inference.ci_high,
        usable_bootstrap,
        inference.estimate,
        permutation_count,
        extreme_count,
        p_raw,
        inference.p_adjusted,
        None,
        None
        if specification["statistical_hypothesis_id"] == "null"
        else specification["statistical_hypothesis_id"],
        specification["holm_member"] == "true",
        status,
        "estimated" if status == "ESTIMATED" else "not_estimable",
        inference,
        dataset,
    )


def _apply_holm(item: ContrastComputation, holm: Mapping[str, HolmResult]) -> ContrastComputation:
    if not item.holm_member or item.statistical_hypothesis_id is None:
        return item
    result = holm[item.statistical_hypothesis_id]
    inference = replace(item.inference, p_adjusted=result.p_adjusted)
    return replace(
        item,
        p_adjusted=result.p_adjusted,
        holm_rank=result.holm_rank,
        result_status=result.result_status,
        estimability_status="estimated" if result.result_status == "ESTIMATED" else "not_estimable",
        inference=inference,
    )


def _evaluate_gates(
    snapshot: ProtocolSnapshot,
    contrasts: Mapping[str, ContrastComputation],
    comparisons: Sequence[AnalyzedComparison],
    *,
    audit_statuses: Mapping[str, GateStatus] | None,
    run_count: int,
) -> tuple[
    tuple[GateComputation, ...],
    tuple[VetoResult, ...],
    ActionPartition,
    ActionabilityResult,
    BranchDecision,
    tuple[FormulaExecutionTrace, ...],
]:
    gates: list[GateComputation] = []
    traces: list[FormulaExecutionTrace] = []
    gate_by_id: dict[str, GateComputation] = {}

    def evaluate(gate_id: str, formula_id: str, operands: Mapping[str, object]) -> object:
        execution = execute_formula_traced(
            formula_id,
            _ordered_operands(snapshot, formula_id, operands),
        )
        result = GateComputation(gate_id, formula_id, execution.output, execution.trace)
        gates.append(result)
        gate_by_id[gate_id] = result
        traces.append(execution.trace)
        return execution.output

    if audit_statuses is None:
        provisional_trace = FormulaExecutionTrace(
            formula_id="F-INTEGRITY",
            ordered_operand_ids=(),
            operand_values=(),
            output_value=GateStatus.PASS,
            output_status=GateStatus.PASS.value,
        )
        provisional = GateComputation(
            "G-INTEGRITY", "F-INTEGRITY", GateStatus.PASS, provisional_trace
        )
        gates.append(provisional)
        gate_by_id[provisional.gate_id] = provisional
    else:
        if tuple(audit_statuses) != snapshot.registry("audit").ids("audit_id"):
            raise ValueError("G-INTEGRITY audit operands differ from the frozen registry.")
        evaluate("G-INTEGRITY", "F-INTEGRITY", audit_statuses)
    evaluate(
        "G-CORE",
        "F-CORE",
        {
            "COUNT-ARM-RUNS": run_count,
            "COUNT-COMPARISONS": len(comparisons),
            "COUNT-SIGMA-ROWS": len(
                {
                    (item.paired.world_id, item.paired.seed, group)
                    for item in comparisons
                    for group in ("group-00", "group-01", "group-02")
                }
            ),
            "COUNT-CONTRAST-ROWS": 122,
            "FK-ALL": True,
        },
    )
    for gate_id, calibration_ids in (
        ("G-CAL-IG", ("BR-C001", "BR-C002", "BR-C003", "BR-C004", "BR-C005")),
        ("G-CAL-LA", ("BR-C006", "BR-C007", "BR-C008", "BR-C009", "BR-C010")),
    ):
        evaluate(
            gate_id,
            "F-CAL",
            dict(
                zip(
                    (
                        "policy_nll",
                        "policy_brier",
                        "policy_ece",
                        "policy_confidently_wrong",
                        "policy_true_probability",
                    ),
                    (contrasts[item].inference for item in calibration_ids),
                    strict=True,
                )
            ),
        )
    evaluate(
        "G-CAL-BOTH",
        "F-AND",
        {
            "ordered_gate_status_operands": (
                gate_by_id["G-CAL-IG"].status,
                gate_by_id["G-CAL-LA"].status,
            )
        },
    )
    hard_ids = tuple(f"BR-C{index:03d}" for index in range(47, 67))
    evaluate(
        "G-HARD-SAFETY", "F-HARD-SAFETY", {item: contrasts[item].inference for item in hard_ids}
    )
    for gate_id, controller_ids in (
        (
            "G-CTRL-IG",
            ("BR-C001", "BR-C002", "BR-C005", "BR-C004", "BR-C011", "BR-C012", "BR-C013"),
        ),
        (
            "G-CTRL-LA",
            ("BR-C006", "BR-C007", "BR-C010", "BR-C009", "BR-C014", "BR-C015", "BR-C016"),
        ),
    ):
        names = (
            "policy_nll",
            "policy_brier",
            "policy_true_probability",
            "policy_confidently_wrong",
            "policy_helped_minus_hurt",
            "policy_conditional_efficiency",
            "policy_end_to_end_efficiency",
        )
        evaluate(
            gate_id,
            "F-CTRL",
            {
                **dict(
                    zip(
                        names,
                        (contrasts[item].inference for item in controller_ids),
                        strict=True,
                    )
                ),
                "G-HARD-SAFETY": gate_by_id["G-HARD-SAFETY"].status,
            },
        )
    evaluate(
        "G-CTRL-BOTH",
        "F-AND",
        {
            "ordered_gate_status_operands": (
                gate_by_id["G-CTRL-IG"].status,
                gate_by_id["G-CTRL-LA"].status,
            )
        },
    )
    concentration = (
        ("G-RQ2-COST-IG", "BR-C017"),
        ("G-RQ2-BUDGET-IG", "BR-C018"),
        ("G-RQ2-COST-LA", "BR-C019"),
        ("G-RQ2-BUDGET-LA", "BR-C020"),
    )
    for gate_id, contrast_id in concentration:
        item = contrasts[contrast_id]
        evaluate(
            gate_id,
            "F-CONCENTRATION",
            {
                "target_divergent_count": item.n_present,
                "comparator_divergent_count": item.n_absent,
                "contrast_estimate": item.estimate,
                "ci_low": item.ci_low,
                "p_adjusted": item.p_adjusted,
            },
        )
    for gate_id, contrast_id, policy in (
        ("G-RQ3-IG", "BR-C067", "information_gain"),
        ("G-RQ3-LA", "BR-C068", "lookahead_information_gain"),
    ):
        item = contrasts[contrast_id]
        classifiable = tuple(
            value for value in comparisons if value.paired.policy_id == policy and value.truth_free
        )
        counts = Counter(
            value.truth_free.primary_mechanism_id for value in classifiable if value.truth_free
        )
        evaluate(
            gate_id,
            "F-DOMINANCE",
            {
                "classifiable_count": len(classifiable),
                "combined_primary_share": item.estimate,
                "ci_low": item.ci_low,
                "score_flattening_share": counts["SCORE_FLATTENING"] / len(classifiable)
                if classifiable
                else None,
                "group_sigma_reordering_share": counts["GROUP_SIGMA_REORDERING"] / len(classifiable)
                if classifiable
                else None,
            },
        )
    for gate_id, contrast_id in (("G-RQ4-IG", "BR-C021"), ("G-RQ4-LA", "BR-C022")):
        item = contrasts[contrast_id]
        evaluate(
            gate_id,
            "F-ORDER",
            {
                "present_count": item.n_present,
                "absent_count": item.n_absent,
                "contrast_estimate": item.estimate,
                "ci_low": item.ci_low,
                "p_adjusted": item.p_adjusted,
            },
        )
    action_statuses: list[GateStatus] = []
    decision_specs = snapshot.registry("decision").records()
    for specification in decision_specs:
        source_contrast = contrasts[specification["source_contrast_id"]]
        decision_contrast = contrasts[specification["contrast_id"]]
        output = evaluate(
            specification["gate_id"],
            "F-ACTION",
            {
                "decision_contrast": cast(ActionabilityComposite, decision_contrast.actionability),
                "source_confirmatory_contrast": source_contrast.inference,
                "five_actionability_blocks": cast(
                    ActionabilityComposite, decision_contrast.actionability
                ).blocks,
                "mechanism_allowlist": _mechanism_for(specification) in ACTIONABLE_MECHANISMS,
                "truth_free_provenance": True,
            },
        )
        action_statuses.append(cast(GateStatus, output))
    action_output = cast(
        ActionabilityResult,
        evaluate(
            "G-ACTIONABILITY-COMPLETE",
            "F-ACTION-COMPLETE",
            {"ordered_20_action_gate_statuses": tuple(action_statuses)},
        ),
    )
    controller_change = cast(
        DecisionBoolean,
        evaluate(
            "G-CONTROLLER-CHANGE",
            "F-CONTROLLER-CHANGE",
            {
                "G-INTEGRITY": gate_by_id["G-INTEGRITY"].status,
                "G-CORE": gate_by_id["G-CORE"].status,
                "G-CAL-BOTH": gate_by_id["G-CAL-BOTH"].status,
                "G-CTRL-BOTH": gate_by_id["G-CTRL-BOTH"].status,
                "G-HARD-SAFETY": gate_by_id["G-HARD-SAFETY"].status,
            },
        ),
    )
    veto_results: list[VetoResult] = []
    action_by_decision = {item.decision_contrast_id: item for item in _action_tuples(snapshot)}
    for veto in snapshot.registry("veto").records():
        source_action = action_by_decision[veto["decision_contrast_id"]]
        own = contrasts[veto["own_confirmatory_contrast_id"]]
        other = contrasts[veto["required_veto_contrast_id"]]
        execution = execute_formula_traced(
            "F-VETO",
            _ordered_operands(
                snapshot,
                "F-VETO",
                {
                    "source_tuple": source_action,
                    "required_veto_contrast_id": veto["required_veto_contrast_id"],
                    "own_effect": own.estimate,
                    "other_policy_effect": other.estimate,
                    "other_policy_ci": (other.ci_low, other.ci_high),
                    "other_policy_holm_p": other.p_adjusted,
                    "support_counts": {"resolved": other.result_status == "ESTIMATED"},
                },
            ),
        )
        traces.append(execution.trace)
        veto_results.append(
            VetoResult(source_action, cast(str, execution.output))  # type: ignore[arg-type]
        )
    veto_complete = cast(
        DecisionBoolean,
        evaluate(
            "G-VETO-COMPLETE",
            "F-VETO-COMPLETE",
            {"P_RAW": action_output.p_raw, "ordered_20_veto_evaluations": tuple(veto_results)},
        ),
    )
    partition_execution = execute_formula_traced(
        "F-P",
        _ordered_operands(
            snapshot,
            "F-P",
            {"P_RAW": action_output.p_raw, "ordered_20_veto_evaluations": tuple(veto_results)},
        ),
    )
    partition = cast(ActionPartition, partition_execution.output)
    traces.append(partition_execution.trace)
    unique = cast(
        DecisionBoolean,
        evaluate(
            "G-UNIQUE-ACTIONABLE-MECHANISM",
            "F-UNIQUE-MECHANISM",
            {"P": partition.surviving_tuples, "VETO_COMPLETE": veto_complete},
        ),
    )
    b_authorized = cast(
        DecisionBoolean,
        evaluate(
            "G-B-AUTHORIZATION",
            "F-B-AUTHORIZATION",
            {
                "CONTROLLER_CHANGE_NEEDED": controller_change,
                "ACTIONABILITY_COMPLETE": action_output.actionability_complete,
                "VETO_COMPLETE": veto_complete,
                "P_RAW": action_output.p_raw,
                "ordered_20_veto_evaluations": tuple(veto_results),
                "P": partition.surviving_tuples,
                "UNIQUE_ACTIONABLE_MECHANISM": unique,
            },
        ),
    )
    ppo = cast(
        DecisionBoolean,
        evaluate(
            "G-PPO",
            "F-PPO",
            {
                "G-INTEGRITY": gate_by_id["G-INTEGRITY"].status,
                "G-CORE": gate_by_id["G-CORE"].status,
                "G-CAL-BOTH": gate_by_id["G-CAL-BOTH"].status,
                "G-CTRL-BOTH": gate_by_id["G-CTRL-BOTH"].status,
                "G-HARD-SAFETY": gate_by_id["G-HARD-SAFETY"].status,
                "G-ACTIONABILITY-COMPLETE": gate_by_id["G-ACTIONABILITY-COMPLETE"].status,
                "VETO_COMPLETE": veto_complete,
                "P": partition.surviving_tuples,
                "CONTROLLER_CHANGE_NEEDED": controller_change,
            },
        ),
    )
    final_decision_result = cast(
        BranchDecision,
        evaluate(
            "G-FINAL",
            "F-DECISION-TABLE",
            {
                "G-B-AUTHORIZATION": gate_by_id["G-B-AUTHORIZATION"].status,
                "B_AUTHORIZED": b_authorized,
                "VETO_COMPLETE": veto_complete,
                "CONTROLLER_CHANGE_NEEDED": controller_change,
                "PPO_ELIGIBLE": ppo,
                "ordered_branch_registry": snapshot.registry("branch").records(),
            },
        ),
    )
    if tuple(item.gate_id for item in gates) != snapshot.registry("gate").ids("gate_id"):
        raise ValueError("Production gate execution order differs from the 44-row freeze.")
    return (
        tuple(gates),
        tuple(veto_results),
        partition,
        action_output,
        final_decision_result,
        tuple(traces),
    )


def _ordered_operands(
    snapshot: ProtocolSnapshot,
    formula_id: str,
    values: Mapping[str, object],
) -> OrderedDict[str, object]:
    specification = next(
        row for row in snapshot.registry("formula").records() if row["formula_id"] == formula_id
    )
    order = tuple(specification["ordered_operand_ids"].split(";"))
    if set(values) != set(order):
        raise KeyError(
            f"Formula {formula_id} production operands differ; "
            f"expected={order}, got={tuple(values)}."
        )
    return OrderedDict((identifier, values[identifier]) for identifier in order)


def _action_tuples(snapshot: ProtocolSnapshot) -> tuple[ActionTuple, ...]:
    mechanisms = snapshot.registry("mechanism").ids("mechanism_id")[:10]
    return tuple(
        ActionTuple(
            row["policy_scope"],
            mechanisms[index % 10],
            row["contrast_id"],
            row["source_contrast_id"],
        )
        for index, row in enumerate(snapshot.registry("decision").records())
    )


def _eligible(specification: Mapping[str, str], item: AnalyzedComparison) -> bool:
    if item.paired.policy_id != POLICY_BY_SCOPE[specification["policy_scope"]]:
        return False
    population = specification["population_scope"]
    world = WORLDS_BY_ID[item.paired.world_id].public
    if "PRIMARY" in population or "BUDGET" in population or "SAMESET" in population:
        return True
    if "HIGH" in population:
        return item.paired.world_id in {"h_adam_high", "h_null_high", "h_sgd_high"}
    if "HET" in population:
        return world.block == "heterogeneous_noise"
    if "ASYM" in population:
        return item.paired.world_id in {
            "c_adam_a",
            "c_sgd_a",
            "c_adam_b",
            "c_sgd_b",
            "d2_adam",
            "d2_sgd",
        }
    block_name = {
        "HOM": "homogeneous",
        "WEAK": "weak_effect",
        "HET": "heterogeneous_noise",
        "COST": "asymmetric_cost",
        "DELAY": "delay",
    }
    return any(token in population and world.block == block for token, block in block_name.items())


def _population_weight(population: str, item: AnalyzedComparison) -> float:
    world = WORLDS_BY_ID[item.paired.world_id]
    truth = world.hidden.scientific_hypothesis_id
    eligible_worlds = tuple(
        value
        for value in WORLDS_BY_ID.values()
        if _world_in_population(population, value.public.world_id)
        and value.hidden.scientific_hypothesis_id == truth
    )
    truth_count = len(
        {
            value.hidden.scientific_hypothesis_id
            for value in WORLDS_BY_ID.values()
            if _world_in_population(population, value.public.world_id)
        }
    )
    if not eligible_worlds or truth_count == 0:
        return 0.0
    budget_count = 3
    return 1.0 / (truth_count * len(eligible_worlds) * budget_count * len(FULL_SEEDS))


def _world_in_population(population: str, world_id: str) -> bool:
    world = WORLDS_BY_ID[world_id].public
    if "PRIMARY" in population or "BUDGET" in population or "SAMESET" in population:
        return True
    if "HIGH" in population:
        return world_id in {"h_adam_high", "h_null_high", "h_sgd_high"}
    if "ASYM" in population:
        return world_id in {
            "c_adam_a",
            "c_sgd_a",
            "c_adam_b",
            "c_sgd_b",
            "d2_adam",
            "d2_sgd",
        }
    if "BLOCK" in population:
        token = population.rsplit("-", 1)[-1]
        return (
            world.block
            == {
                "HOM": "homogeneous",
                "WEAK": "weak_effect",
                "HET": "heterogeneous_noise",
                "COST": "asymmetric_cost",
                "DELAY": "delay",
            }[token]
        )
    return world.block == "heterogeneous_noise" if "HET" in population else False


def _metric_value(metrics: ArmMetrics, metric_id: str) -> float | None:
    values: dict[str, float | None] = {
        "nll": metrics.nll,
        "brier": metrics.brier,
        "ece": None,
        "confidently_wrong": float(metrics.confidently_wrong),
        "true_probability": metrics.true_probability,
        "conditional_brier_efficiency": metrics.conditional_brier_efficiency,
        "end_to_end_brier_efficiency": metrics.end_to_end_brier_efficiency,
        "decision_cost": metrics.decision_cost,
        "calibration_cost": metrics.calibration_cost,
        "required_total_cost": metrics.required_total_cost,
        "best_observed_objective": metrics.best_observed_objective,
        "first_action_divergence": None,
        "any_divergence": None,
        "harm_risk": None,
        "combined_numerical_share": None,
    }
    return values[metric_id]


def _split_right_left(
    specification: Mapping[str, str],
    eligible: Sequence[AnalyzedComparison],
    outcomes: Sequence[OutcomeRow],
) -> tuple[tuple[OutcomeRow, ...], tuple[OutcomeRow, ...]]:
    by_id = {item.paired.comparison_id: item for item in eligible}
    right: list[OutcomeRow] = []
    left: list[OutcomeRow] = []
    for row in outcomes:
        item = by_id[row.comparison_id]
        if specification["estimand_id"] == "sequence_harm_difference":
            is_right = bool(
                item.truth_free
                and item.truth_free.sequence_class == "same_experiment_set_different_order"
            )
        elif "ASYM" in specification["population_scope"]:
            is_right = item.paired.world_id.startswith("c_")
        else:
            is_right = item.paired.budget_id != "budget-2.25"
        (right if is_right else left).append(row)
    return tuple(right), tuple(left)


def _split_rate_rows(
    specification: Mapping[str, str],
    eligible: Sequence[AnalyzedComparison],
    rows: Sequence[ComparisonRateRow],
) -> tuple[tuple[ComparisonRateRow, ...], tuple[ComparisonRateRow, ...]]:
    by_id = {item.paired.comparison_id: item for item in eligible}
    target: list[ComparisonRateRow] = []
    comparator: list[ComparisonRateRow] = []
    for row in rows:
        item = by_id[row.comparison_id]
        is_target = (
            item.paired.world_id.startswith("c_")
            if "ASYM" in specification["population_scope"]
            else item.paired.budget_id != "budget-2.25"
        )
        (target if is_target else comparator).append(row)
    return tuple(target), tuple(comparator)


def _mechanism_for(specification: Mapping[str, str]) -> str:
    hypothesis = specification.get("statistical_hypothesis_id", "")
    for mechanism in (*ACTIONABLE_MECHANISMS, "NO_STABLE_MECHANISM"):
        if hypothesis.endswith(mechanism):
            return mechanism
    contrast_id = specification["source_contrast_id"]
    source = next(
        row
        for row in load_protocol_snapshot().registry("confirmatory").records()
        if row["contrast_id"] == contrast_id
    )
    return _mechanism_for(source)


def _actionability_blocks(
    specification: Mapping[str, str], comparisons: Sequence[AnalyzedComparison]
) -> tuple[ActionabilityBlock, ...]:
    source = next(
        row
        for row in load_protocol_snapshot().registry("confirmatory").records()
        if row["contrast_id"] == specification["source_contrast_id"]
    )
    mechanism = _mechanism_for(source)
    blocks = (
        ("homogeneous", "HOM"),
        ("weak_effect", "WEAK"),
        ("heterogeneous_noise", "HET"),
        ("asymmetric_cost", "COST"),
        ("delay", "DELAY"),
    )
    result: list[ActionabilityBlock] = []
    for block, population_suffix in blocks:
        population_id = f"POP-BLOCK-{specification['policy_scope']}-{population_suffix}"
        rows = tuple(
            item
            for item in comparisons
            if item.paired.policy_id == POLICY_BY_SCOPE[specification["policy_scope"]]
            and WORLDS_BY_ID[item.paired.world_id].public.block == block
            and item.truth_free is not None
        )
        present = tuple(
            item
            for item in rows
            if item.truth_free and item.truth_free.primary_mechanism_id == mechanism
        )
        absent = tuple(item for item in rows if item not in present)
        present_outcomes = tuple(
            OutcomeRow(
                item.paired.comparison_id,
                item.paired.seed,
                1.0,
                item.paired.outcome_label,
                True,
                mechanism,
            )
            for item in present
        )
        absent_outcomes = tuple(
            OutcomeRow(
                item.paired.comparison_id,
                item.paired.seed,
                1.0,
                item.paired.outcome_label,
                True,
                item.truth_free.primary_mechanism_id if item.truth_free else None,
            )
            for item in absent
        )
        try:
            estimate = math.fsum(row.outcome_label == "hurt" for row in present_outcomes) / len(
                present_outcomes
            ) - math.fsum(row.outcome_label == "hurt" for row in absent_outcomes) / len(
                absent_outcomes
            )
        except ZeroDivisionError:
            estimate = None
        result.append(
            ActionabilityBlock(
                population_id,
                len(rows),
                len(present),
                len(absent),
                estimate,
                "estimated" if estimate is not None else "not_estimable",
            )
        )
    return tuple(result)
