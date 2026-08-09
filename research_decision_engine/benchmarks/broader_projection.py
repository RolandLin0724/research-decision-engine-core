"""Projection of production trajectories and analysis into all canonical payloads."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, cast

from research_decision_engine.benchmarks.broader_analysis import (
    AnalyzedComparison,
    ContrastComputation,
    GateComputation,
    PreGateAnalysisResult,
    ProductionAnalysisResult,
    _issued_analysis_lineage,
    _require_issued_analysis,
)
from research_decision_engine.benchmarks.broader_artifacts import (
    build_protocol_snapshot_payload,
    build_world_definitions_payload,
)
from research_decision_engine.benchmarks.broader_audits import (
    FixtureAuditDiagnostic,
    IntegrityAuditResult,
    _require_authoritative_audit_results,
    _require_issued_fixture_audit_diagnostics,
)
from research_decision_engine.benchmarks.broader_execution import _IssuedAttestation
from research_decision_engine.benchmarks.broader_oracle import (
    RevealedObservation,
)
from research_decision_engine.benchmarks.broader_protocol import (
    PROTOCOL_VERSION,
    ProtocolSnapshot,
    canonical_json_bytes,
    f64,
    load_protocol_snapshot,
    protocol_hash,
)
from research_decision_engine.benchmarks.broader_runner import (
    ArmDecision,
    ArmMetrics,
    BroaderArmRun,
    CalibrationDeploymentBinding,
    evaluate_arm,
    reconstruct_complete_calibration_claim,
    validate_recorded_calibration,
    validate_recorded_calibrations,
    validated_calibration_history_selections,
)
from research_decision_engine.benchmarks.broader_statistics import (
    ActionabilityComposite,
    ActionTuple,
    BranchDecision,
    DecisionBoolean,
    GateStatus,
    sampled_seed_ids_sha256,
    sign_vector_sha256,
)
from research_decision_engine.benchmarks.broader_worlds import (
    CANDIDATES_BY_ID,
    GROUP_IDS,
    WORLDS,
    WORLDS_BY_ID,
    PublicFeasibilityState,
    candidate_costs,
)
from research_decision_engine.reasoning import BeliefState

EVENT_TYPE_ORDER: Final = {
    "decision": 0,
    "setup": 1,
    "experiment": 2,
    "evidence": 3,
    "belief_update": 4,
    "terminal": 5,
}
TIE_BREAK_ORDER: Final = [
    "greater_expected_total_information_gain",
    "lower_expected_total_cost",
    "greater_information_gain_per_expected_cost",
    "stable_lexicographic_candidate_id",
]
WORLD_ORDER: Final = {world.public.world_id: index for index, world in enumerate(WORLDS)}
type AuditProjectionRecord = IntegrityAuditResult | FixtureAuditDiagnostic


@dataclass(frozen=True, slots=True)
class PostAuditScientificPayloads:
    """Gate and audit claims created only after the complete A01-A16 sequence."""

    gate_evaluations: dict[str, object]
    audit_results: dict[str, object]

    def as_mapping(self) -> dict[str, object]:
        return {
            "gate_evaluations.json": self.gate_evaluations,
            "audit_results.json": self.audit_results,
        }


@dataclass(frozen=True, slots=True)
class _ProjectionBinding:
    projection: object
    execution: _IssuedAttestation
    fingerprint: str
    analysis: PreGateAnalysisResult | ProductionAnalysisResult
    lineage: object
    source_prefinalization: Mapping[str, object] | None = None
    audit_results: Sequence[AuditProjectionRecord] | None = None


_ISSUED_PREFINALIZATION_PAYLOADS: dict[int, _ProjectionBinding] = {}
_ISSUED_POST_AUDIT_PAYLOADS: dict[int, _ProjectionBinding] = {}


def _projection_fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value, final_lf=True)).hexdigest()


def _require_issued_prefinalization_payloads(
    payloads: Mapping[str, object],
    *,
    analysis: PreGateAnalysisResult | ProductionAnalysisResult | None = None,
) -> _IssuedAttestation:
    binding = _ISSUED_PREFINALIZATION_PAYLOADS.get(id(payloads))
    if (
        binding is None
        or binding.projection is not payloads
        or binding.fingerprint != _projection_fingerprint(payloads)
        or (analysis is not None and binding.analysis is not analysis)
    ):
        raise ValueError("Prefinalization payloads are copied, changed, or not exact-issued.")
    return binding.execution


def _issued_prefinalization_source_analysis(
    payloads: Mapping[str, object],
) -> PreGateAnalysisResult | ProductionAnalysisResult:
    """Return the exact analysis used to issue an unchanged prefinal projection."""

    _require_issued_prefinalization_payloads(payloads)
    return _ISSUED_PREFINALIZATION_PAYLOADS[id(payloads)].analysis


def _issued_prefinalization_lineage(payloads: Mapping[str, object]) -> object:
    """Return the opaque analysis lineage bound to an unchanged projection."""

    _require_issued_prefinalization_payloads(payloads)
    return _ISSUED_PREFINALIZATION_PAYLOADS[id(payloads)].lineage


def _require_issued_post_audit_payloads(
    payloads: PostAuditScientificPayloads,
    *,
    prefinalization: Mapping[str, object] | None = None,
    audit_results: Sequence[AuditProjectionRecord] | None = None,
) -> _IssuedAttestation:
    source_lineage: object | None = None
    if prefinalization is not None:
        source_lineage = _issued_prefinalization_lineage(prefinalization)
    binding = _ISSUED_POST_AUDIT_PAYLOADS.get(id(payloads))
    if (
        binding is None
        or binding.projection is not payloads
        or binding.fingerprint != _projection_fingerprint(payloads.as_mapping())
        or (prefinalization is not None and binding.source_prefinalization is not prefinalization)
        or (audit_results is not None and binding.audit_results is not audit_results)
        or (source_lineage is not None and binding.lineage is not source_lineage)
    ):
        raise ValueError("Post-audit payloads are copied, changed, or not exact-issued.")
    if audit_results is not None:
        if type(binding.analysis) is not ProductionAnalysisResult:
            raise ValueError("Post-audit payloads lack an exact final analysis stage.")
        runs = cast(Sequence[BroaderArmRun], binding.execution.returned_results)
        if all(type(item) is IntegrityAuditResult for item in audit_results):
            audit_execution = _require_authoritative_audit_results(
                cast(Sequence[IntegrityAuditResult], audit_results),
                runs=runs,
                analysis=binding.analysis,
                prefinalization=binding.source_prefinalization,
            )
        elif all(type(item) is FixtureAuditDiagnostic for item in audit_results):
            audit_execution = _require_issued_fixture_audit_diagnostics(
                cast(Sequence[FixtureAuditDiagnostic], audit_results),
                runs=runs,
                analysis=binding.analysis,
                prefinalization=binding.source_prefinalization,
            )
        else:
            raise ValueError("Post-audit payloads mix incompatible audit trust domains.")
        if audit_execution is not binding.execution:
            raise ValueError("Post-audit payloads belong to another executor result batch.")
    return binding.execution


def build_prefinalization_payloads(
    runs: Sequence[BroaderArmRun],
    analysis: PreGateAnalysisResult | ProductionAnalysisResult,
) -> dict[str, object]:
    """Build temporary artifacts 1-9 before any gate or audit claim exists."""

    execution = _require_issued_analysis(analysis, runs=runs)
    validate_recorded_calibrations(runs)
    snapshot = load_protocol_snapshot()
    run_rows, event_rows = _run_and_event_rows(runs)
    calibration_rows = _calibration_rows(runs)
    oracle_rows = _oracle_rows(runs)
    comparison_rows = _comparison_rows(analysis.comparisons)
    contrast_rows = tuple(_contrast_row(item) for item in analysis.contrasts)
    resampling_rows = _resampling_rows(analysis)
    payloads: dict[str, object] = {
        "protocol_snapshot.json": build_protocol_snapshot_payload(snapshot),
        "world_definitions.json": build_world_definitions_payload(),
        "arm_runs.jsonl": run_rows,
        "oracle_provenance.jsonl": oracle_rows,
        "calibration_estimates.jsonl": calibration_rows,
        "trajectory_events.jsonl": event_rows,
        "comparisons.jsonl": comparison_rows,
        "contrast_results.csv": contrast_rows,
        "resampling_audit.jsonl": resampling_rows,
    }
    _ISSUED_PREFINALIZATION_PAYLOADS[id(payloads)] = _ProjectionBinding(
        payloads,
        execution,
        _projection_fingerprint(payloads),
        analysis,
        _issued_analysis_lineage(analysis),
    )
    return payloads


def build_post_audit_payloads(
    runs: Sequence[BroaderArmRun],
    analysis: ProductionAnalysisResult,
    audit_results: Sequence[IntegrityAuditResult],
    prefinalization: Mapping[str, object],
) -> PostAuditScientificPayloads:
    """Build artifacts 10-13 only after all frozen audits passed."""

    if any(type(item) is not IntegrityAuditResult for item in audit_results):
        raise ValueError("Production projection requires exact authoritative audit results.")
    audit_execution = _require_authoritative_audit_results(
        audit_results,
        runs=runs,
        analysis=analysis,
        prefinalization=prefinalization,
    )
    return _build_post_audit_payloads(
        runs,
        analysis,
        audit_results,
        prefinalization,
        audit_execution=audit_execution,
    )


def _build_fixture_post_audit_payloads(
    runs: Sequence[BroaderArmRun],
    analysis: ProductionAnalysisResult,
    audit_results: Sequence[FixtureAuditDiagnostic],
    prefinalization: Mapping[str, object],
) -> PostAuditScientificPayloads:
    """Project bounded diagnostics without creating production audit authority."""

    if any(type(item) is not FixtureAuditDiagnostic for item in audit_results):
        raise ValueError("Fixture projection requires exact non-authoritative diagnostics.")
    audit_execution = _require_issued_fixture_audit_diagnostics(
        audit_results,
        runs=runs,
        analysis=analysis,
        prefinalization=prefinalization,
    )
    return _build_post_audit_payloads(
        runs,
        analysis,
        audit_results,
        prefinalization,
        audit_execution=audit_execution,
    )


def _build_post_audit_payloads(
    runs: Sequence[BroaderArmRun],
    analysis: ProductionAnalysisResult,
    audit_results: Sequence[AuditProjectionRecord],
    prefinalization: Mapping[str, object],
    *,
    audit_execution: _IssuedAttestation,
) -> PostAuditScientificPayloads:
    """Shared schema projection after the caller establishes its disjoint trust domain."""

    execution = _require_issued_analysis(analysis, runs=runs)
    prefinal_execution = _require_issued_prefinalization_payloads(prefinalization)
    analysis_lineage = _issued_analysis_lineage(analysis)
    prefinal_lineage = _issued_prefinalization_lineage(prefinalization)
    if execution is not prefinal_execution or execution is not audit_execution:
        raise ValueError("Post-audit projection belongs to another executor result batch.")
    if analysis_lineage is not prefinal_lineage:
        raise ValueError("Post-audit projection belongs to another exact analysis lineage.")
    snapshot = load_protocol_snapshot()
    expected_audits = snapshot.registry("audit").ids("audit_id")
    if tuple(item.audit_id for item in audit_results) != expected_audits:
        raise ValueError("Scientific projection requires 16 executed audits in frozen order.")
    if any(item.status != "PASS" for item in audit_results):
        raise ValueError("Canonical projection is forbidden after a failed or unresolved audit.")
    expected_prefinal = tuple(
        item["filename"] for item in snapshot.registry("artifact").records()[:9]
    )
    if tuple(prefinalization) != expected_prefinal:
        raise ValueError("Post-audit projection requires the frozen artifacts 1-9 claims.")
    calibration_rows = cast(Sequence[object], prefinalization["calibration_estimates.jsonl"])
    gate_payload = _gate_payload(
        snapshot, analysis, audit_results, len(runs), len(calibration_rows)
    )
    audit_payload = _audit_payload(snapshot, audit_results)
    payloads = PostAuditScientificPayloads(
        gate_evaluations=gate_payload,
        audit_results=audit_payload,
    )
    _ISSUED_POST_AUDIT_PAYLOADS[id(payloads)] = _ProjectionBinding(
        payloads,
        execution,
        _projection_fingerprint(payloads.as_mapping()),
        analysis,
        analysis_lineage,
        prefinalization,
        audit_results,
    )
    return payloads


def merged_scientific_claims(
    prefinalization: Mapping[str, object], post_audit: PostAuditScientificPayloads
) -> dict[str, object]:
    """Create the exact artifacts 1-11 authorization payload."""

    return {**prefinalization, **post_audit.as_mapping()}


def derive_manifest_scientific_payload(
    promoted_scientific: Mapping[str, object],
) -> dict[str, object]:
    """Derive manifest claims only from decoded, promoted artifacts 1-11."""

    run_rows = cast(Sequence[object], promoted_scientific["arm_runs.jsonl"])
    comparison_rows = cast(Sequence[object], promoted_scientific["comparisons.jsonl"])
    calibration_rows = cast(Sequence[object], promoted_scientific["calibration_estimates.jsonl"])
    event_rows = cast(
        Sequence[Mapping[str, object]], promoted_scientific["trajectory_events.jsonl"]
    )
    oracle_rows = cast(
        Sequence[Mapping[str, object]], promoted_scientific["oracle_provenance.jsonl"]
    )
    resampling_rows = cast(
        Sequence[Mapping[str, object]], promoted_scientific["resampling_audit.jsonl"]
    )
    bootstrap = sum(row["record_type"] == "bootstrap" for row in resampling_rows)
    sign_flip = sum(row["record_type"] == "sign_flip" for row in resampling_rows)
    return _manifest_payload(
        len(run_rows),
        len(comparison_rows),
        len(calibration_rows),
        bootstrap,
        sign_flip,
        event_rows,
        oracle_rows,
    )


def recommendation_scientific_payload_identity(gate_payload: Mapping[str, object]) -> str:
    """Precommit the frozen hash without constructing or serializing the final artifact."""

    digest = hashlib.sha256()
    digest.update(b"{")
    for index, (field, value) in enumerate(_recommendation_field_items(gate_payload)):
        if index:
            digest.update(b",")
        digest.update(canonical_json_bytes(field))
        digest.update(b":")
        digest.update(canonical_json_bytes(value))
    digest.update(b"}\n")
    return digest.hexdigest()


def derive_recommendation_scientific_payload(
    gate_payload: Mapping[str, object],
) -> dict[str, object]:
    """Construct recommendation claims only after the persisted manifest validates."""

    return _recommendation_fields(gate_payload)


def _recommendation_fields(gate_payload: Mapping[str, object]) -> dict[str, object]:
    return dict(_recommendation_field_items(gate_payload))


def _recommendation_field_items(
    gate_payload: Mapping[str, object],
) -> Iterator[tuple[str, object]]:
    """Yield the scientific fields in canonical UTF-8 order from one authoritative path."""

    snapshot = load_protocol_snapshot()
    branch_id = cast(str, gate_payload["final_branch_id"])
    branch = next(
        row for row in snapshot.registry("branch").records() if row["branch_id"] == branch_id
    )
    unique = gate_payload["unique_mechanism_id"]
    authorized_policy_scopes = (
        sorted(
            {
                cast(str, item["policy_scope"])
                for item in cast(list[dict[str, object]], gate_payload["P"])
            }
        )
        if branch_id == "BRANCH-B"
        else []
    )
    yield "authorized_policy_scopes", authorized_policy_scopes
    yield "branch_id", branch_id
    yield "branch_trace", gate_payload["final_branch_trace"]
    yield "decision_precedence", int(branch["branch_order"])
    yield "evaluation_id", PROTOCOL_VERSION
    yield (
        "gate_evaluation_scientific_payload_sha256",
        hashlib.sha256(canonical_json_bytes(gate_payload, final_lf=True)).hexdigest(),
    )
    yield "gate_status", gate_payload["final_gate_status"]
    yield "integrity_status", "PASS"
    yield "recommendation", gate_payload["recommendation"]
    yield "unique_mechanism_id", unique


def _run_and_event_rows(
    runs: Sequence[BroaderArmRun],
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    run_rows: list[dict[str, object]] = []
    all_events: list[dict[str, object]] = []
    for run in runs:
        truth = WORLDS_BY_ID[run.world_id].hidden.scientific_hypothesis_id
        metrics = evaluate_arm(run, truth)
        events = _events_for_run(run)
        all_events.extend(events)
        decision_ids = [item.decision_id for item in run.decisions]
        ordered_decisions = protocol_hash(
            "ordered_decisions/v1", {"run_id": run.run_id, "decision_ids": decision_ids}
        )
        event_costs = []
        for row in events:
            payload = cast(dict[str, object], row["event_payload"])
            if payload["event_type"] not in {"setup", "experiment"}:
                continue
            specific = cast(dict[str, object], payload["event_specific_payload"])
            event_costs.append(
                {
                    "event_id": payload["event_id"],
                    "record_type": payload["event_type"],
                    "cost": specific["cost"],
                    "cumulative_decision_cost": specific["cumulative_decision_cost"],
                }
            )
        metric_payload = _metric_payload(metrics)
        prefixes = (
            [item.calibration_prefix_id for item in run.calibration.estimates]
            if run.calibration
            else []
        )
        reconciliation = protocol_hash(
            "cost_reconciliation/v1",
            {
                "run_id": run.run_id,
                "ordered_event_costs": event_costs,
                "decision_cost": metric_payload["decision_cost"],
                "calibration_prefix_ids": prefixes,
                "calibration_cost": metric_payload["calibration_cost"],
                "required_total_cost": metric_payload["required_total_cost"],
                "physical_cost_share": metric_payload["physical_cost_share"],
            },
        )
        trajectory = protocol_hash(
            "trajectory/v1",
            {
                "run_id": run.run_id,
                "ordered_decisions_sha256": ordered_decisions,
                "ordered_real_event_ids": [
                    cast(dict[str, object], row["event_payload"])["event_id"] for row in events
                ],
                "ordered_event_provenance_sha256": [row["provenance_sha256"] for row in events],
                "terminal_reason": run.terminal_reason,
                "reconciliation_sha256": reconciliation,
            },
        )
        run_rows.append(
            {
                "run_id": run.run_id,
                "comparison_id": run.comparison_id,
                "arm_id": run.arm.arm_id,
                "world_id": run.world_id,
                "seed": run.seed,
                "budget_id": run.budget_id,
                "budget": f64(run.budget),
                "policy_id": run.arm.policy_id,
                "belief_model_id": run.arm.belief_model_id,
                "lineage_id": run.lineage.lineage_id,
                "store_id": f"store/{run.run_id}",
                "initial_probabilities": _probability_payload(run.initial_probabilities),
                "final_probabilities": _probability_payload(run.final_probabilities),
                "scientific_hypothesis_id": truth,
                "metrics": metric_payload,
                "decision_ids": decision_ids,
                "event_ids": [
                    cast(dict[str, object], row["event_payload"])["event_id"] for row in events
                ],
                "calibration_prefix_ids": prefixes,
                "run_status": run.run_status,
                "terminal_reason": run.terminal_reason,
                "ordered_decisions_sha256": ordered_decisions,
                "reconciliation_sha256": reconciliation,
                "trajectory_sha256": trajectory,
            }
        )
    run_rows.sort(key=_run_order)
    all_events.sort(
        key=lambda row: (
            cast(dict[str, object], row["event_payload"])["run_id"],
            cast(dict[str, object], row["event_payload"])["sequence"],
            EVENT_TYPE_ORDER[
                cast(str, cast(dict[str, object], row["event_payload"])["event_type"])
            ],
            cast(dict[str, object], row["event_payload"])["event_id"],
        )
    )
    return tuple(run_rows), tuple(all_events)


def _events_for_run(run: BroaderArmRun) -> list[dict[str, object]]:
    world = WORLDS_BY_ID[run.world_id].public
    costs = candidate_costs(world)
    decision_ids = [item.decision_id for item in run.decisions]
    ordered_decisions = protocol_hash(
        "ordered_decisions/v1", {"run_id": run.run_id, "decision_ids": decision_ids}
    )
    completed: list[str] = []
    events: list[dict[str, object]] = []
    experiment_event_by_record: dict[int, str] = {}
    evidence_by_id = {item.evidence_id: item for item in run.evidence}
    update_by_evidence = {item.evidence.evidence_id: item for item in run.updates}
    completed_by_candidate = {
        item.candidate.candidate_id: item.record_id for item in run.completed_experiments
    }
    cost_before = 0.0
    for decision, action in zip(run.decisions, run.actions, strict=True):
        remaining = run.budget - cost_before
        unexecuted = [item for item in world.candidate_ids if item not in completed]
        eligibility_hash = protocol_hash(
            "eligibility_state/v1",
            {
                "run_id": run.run_id,
                "step": decision.step,
                "completed_candidate_ids": completed,
                "unexecuted_candidate_ids": unexecuted,
                "publicly_feasible_candidate_ids": list(decision.public_feasible_candidate_ids),
                "affordable_candidate_ids": list(decision.affordable_candidate_ids),
                "remaining_budget": f64(remaining),
            },
        )
        public_hash = protocol_hash(
            "public_state/v1",
            {
                "run_id": run.run_id,
                "step": decision.step,
                "belief_state_id": decision.belief_state_id,
                "lineage_id": run.lineage.lineage_id,
                "eligibility_state_sha256": eligibility_hash,
                "remaining_budget": f64(remaining),
            },
        )
        decision_specific = _decision_payload(run, decision, completed, unexecuted)
        events.append(
            _event(
                run,
                decision.step,
                "decision",
                candidate_id=action.candidate_id,
                public_state_sha256=public_hash,
                eligibility_state_sha256=eligibility_hash,
                sigma_estimate_id=None,
                cost_before=cost_before,
                cost_after=cost_before,
                terminal_reason=None,
                specific=decision_specific,
                ordered_decisions_sha256=ordered_decisions,
            )
        )
        action_cost_after = action.cumulative_decision_cost
        definition = CANDIDATES_BY_ID[action.candidate_id]
        if action.role == "setup":
            specific = {
                "decision_id": action.decision_id,
                "setup_completion_id": f"setup-completion/{run.run_id}/{action.step:04d}",
                "cost": f64(action.cost),
                "cumulative_decision_cost": f64(action_cost_after),
            }
            events.append(
                _event(
                    run,
                    action.step,
                    "setup",
                    candidate_id=action.candidate_id,
                    public_state_sha256=None,
                    eligibility_state_sha256=None,
                    sigma_estimate_id=None,
                    cost_before=cost_before,
                    cost_after=action_cost_after,
                    terminal_reason=None,
                    specific=specific,
                    ordered_decisions_sha256=ordered_decisions,
                )
            )
        else:
            observation = action.oracle_observation
            if observation is None or action.observed_objective is None:
                raise ValueError("A real non-setup action lacks its selected observation.")
            event_id = f"event/{run.run_id}/{action.step:04d}/experiment"
            record_id = completed_by_candidate[action.candidate_id]
            experiment_event_by_record[record_id] = event_id
            specific = {
                "decision_id": action.decision_id,
                "experiment_id": event_id,
                "observed_objective": f64(action.observed_objective),
                "cost": f64(action.cost),
                "cumulative_decision_cost": f64(action_cost_after),
                "oracle_key_id": observation.oracle_key_id,
                "oracle_use_id": observation.oracle_use_id,
            }
            sigma_id = _sigma_id(run, definition.comparison_group_id)
            events.append(
                _event(
                    run,
                    action.step,
                    "experiment",
                    candidate_id=action.candidate_id,
                    public_state_sha256=None,
                    eligibility_state_sha256=None,
                    sigma_estimate_id=sigma_id,
                    cost_before=cost_before,
                    cost_after=action_cost_after,
                    terminal_reason=None,
                    specific=specific,
                    ordered_decisions_sha256=ordered_decisions,
                )
            )
            for evidence_id in action.new_evidence_ids:
                evidence = evidence_by_id[evidence_id]
                source_events = [
                    experiment_event_by_record[item] for item in evidence.source_experiment_ids
                ]
                group = cast(str, dict(evidence.provenance.details)["comparison_group_id"])
                evidence_event = _event(
                    run,
                    action.step,
                    "evidence",
                    candidate_id=None,
                    public_state_sha256=None,
                    eligibility_state_sha256=None,
                    sigma_estimate_id=_sigma_id(run, group),
                    cost_before=action_cost_after,
                    cost_after=action_cost_after,
                    terminal_reason=None,
                    specific={
                        "evidence_id": evidence.evidence_id,
                        "source_experiment_ids": source_events,
                        "comparison_group_id": group,
                        "observed_effect": f64(evidence.observed_comparison),
                    },
                    ordered_decisions_sha256=ordered_decisions,
                )
                events.append(evidence_event)
                evidence_event_id = cast(
                    str, cast(dict[str, object], evidence_event["event_payload"])["event_id"]
                )
                update = update_by_evidence[evidence_id]
                bayesian = update.bayesian_update
                events.append(
                    _event(
                        run,
                        action.step,
                        "belief_update",
                        candidate_id=None,
                        public_state_sha256=None,
                        eligibility_state_sha256=None,
                        sigma_estimate_id=_sigma_id(run, group),
                        cost_before=action_cost_after,
                        cost_after=action_cost_after,
                        terminal_reason=None,
                        specific={
                            "belief_update_id": update.model_update_id,
                            "evidence_id": evidence_event_id,
                            "fixed_sigma": (
                                f64(update.sigma_estimate.estimated_sigma)
                                if run.arm.belief_model_id == "fixed_sigma_gaussian"
                                else None
                            ),
                            "belief_before": _belief_snapshot(
                                bayesian.belief_state_before,
                                run.lineage.lineage_id,
                            ),
                            "likelihoods": {
                                item.hypothesis_id: f64(item.likelihood)
                                for item in bayesian.likelihoods
                            },
                            "belief_after": _belief_snapshot(
                                bayesian.posterior_belief_state,
                                run.lineage.lineage_id,
                            ),
                            "update_rule_version": bayesian.update_rule_version,
                        },
                        ordered_decisions_sha256=ordered_decisions,
                    )
                )
        completed.append(action.candidate_id)
        cost_before = action_cost_after
    state = PublicFeasibilityState(world, tuple(completed))
    feasible = state.publicly_feasible_candidate_ids()
    remaining = run.budget - run.decision_cost
    affordable = tuple(item for item in feasible if costs[item] <= remaining)
    unexecuted = [item for item in world.candidate_ids if item not in completed]
    events.append(
        _event(
            run,
            len(run.actions) + 1,
            "terminal",
            candidate_id=None,
            public_state_sha256=None,
            eligibility_state_sha256=None,
            sigma_estimate_id=None,
            cost_before=run.decision_cost,
            cost_after=run.decision_cost,
            terminal_reason=run.terminal_reason,
            specific={
                "final_belief_state_id": run.lineage.current_state.state.belief_state_id,
                "remaining_budget": f64(remaining),
                "completed_candidate_ids": completed,
                "unexecuted_candidate_ids": unexecuted,
                "publicly_feasible_candidate_ids": list(feasible),
                "affordable_candidate_ids": list(affordable),
                "decision_cost": f64(run.decision_cost),
                "calibration_cost": f64(run.calibration_cost),
                "required_total_cost": f64(run.decision_cost + run.calibration_cost),
            },
            ordered_decisions_sha256=ordered_decisions,
        )
    )
    event_id_map: dict[str, str] = {}
    for event_sequence, row in enumerate(events, 1):
        payload = cast(dict[str, object], row["event_payload"])
        old_event_id = cast(str, payload["event_id"])
        event_id_map[old_event_id] = (
            f"event/{run.run_id}/{event_sequence:04d}/{payload['event_type']}"
        )
    for event_sequence, row in enumerate(events, 1):
        payload = cast(dict[str, object], row["event_payload"])
        payload["sequence"] = event_sequence
        payload["event_id"] = event_id_map[cast(str, payload["event_id"])]
        event_specific = cast(dict[str, object], payload["event_specific_payload"])
        if payload["event_type"] == "experiment":
            event_specific["experiment_id"] = payload["event_id"]
        elif payload["event_type"] == "evidence":
            event_specific["source_experiment_ids"] = [
                event_id_map[cast(str, source_id)]
                for source_id in cast(list[object], event_specific["source_experiment_ids"])
            ]
        elif payload["event_type"] == "belief_update":
            event_specific["evidence_id"] = event_id_map[cast(str, event_specific["evidence_id"])]
        row["provenance_sha256"] = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return events


def _decision_payload(
    run: BroaderArmRun,
    decision: ArmDecision,
    completed: Sequence[str],
    unexecuted: Sequence[str],
) -> dict[str, object]:
    trace = decision.policy_trace.to_dict()
    scores: list[dict[str, object]] = []
    branches: list[dict[str, object]] = []
    if run.arm.policy_id == "information_gain":
        for rank, raw in enumerate(cast(list[dict[str, object]], trace["ranked_candidates"]), 1):
            completes = cast(bool, raw["completes_matched_pair"])
            reason = cast(str, raw["score_reason"])
            public_effect = (
                "ineligible"
                if "not eligible" in reason
                else "completes_pair"
                if completes
                else "opens_pair"
            )
            eig = cast(float, raw["expected_information_gain"])
            cost = cast(float, raw["estimated_cost"])
            scores.append(
                {
                    "candidate_id": raw["candidate_id"],
                    "public_effect": public_effect,
                    "immediate_eig": f64(eig),
                    "expected_total_eig": f64(eig),
                    "expected_cost": f64(cost),
                    "eig_per_cost": f64(eig / cost if cost else 0.0),
                    "rank": rank,
                    "ranking_reason": raw["ranking_reason"],
                }
            )
    else:
        selected = cast(dict[str, object], trace["selected_first_experiment"])
        alternatives = cast(list[dict[str, object]], trace["losing_first_action_alternatives"])
        raw_scores = [selected, *alternatives]
        for rank, raw in enumerate(raw_scores, 1):
            candidate = cast(dict[str, object], raw["candidate"])
            scores.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "public_effect": raw["action_effect"],
                    "immediate_eig": f64(cast(float, raw["immediate_information_gain"])),
                    "expected_total_eig": f64(cast(float, raw["expected_total_information_gain"])),
                    "expected_cost": f64(cast(float, raw["expected_total_cost"])),
                    "eig_per_cost": f64(cast(float, raw["information_gain_per_expected_cost"])),
                    "rank": rank,
                    "ranking_reason": raw["ranking_reason"],
                }
            )
        for raw in cast(list[dict[str, object]], trace["possible_evidence_branches"]):
            second = cast(dict[str, object] | None, raw["second_action"])
            bounds = (raw["evidence_lower_bound"], raw["evidence_upper_bound"])
            branches.append(
                {
                    "planning_branch_id": raw["branch_id"],
                    "label": raw["label"],
                    "probability": f64(cast(float, raw["probability"])),
                    "evidence_lower": f64(cast(float, bounds[0]))
                    if bounds[0] is not None
                    else None,
                    "evidence_upper": f64(cast(float, bounds[1]))
                    if bounds[1] is not None
                    else None,
                    "posterior": {
                        key: f64(cast(float, value))
                        for key, value in cast(
                            dict[str, object], raw["posterior_probabilities"]
                        ).items()
                    },
                    "posterior_entropy": f64(cast(float, raw["posterior_entropy"])),
                    "second_candidate_id": second["candidate_id"] if second else None,
                    "second_public_effect": second["action_effect"] if second else "stop",
                    "second_eig": f64(
                        cast(float, second["expected_information_gain"]) if second else 0.0
                    ),
                    "second_cost": f64(cast(float, second["estimated_cost"]) if second else 0.0),
                    "terminal_entropy": f64(cast(float, raw["terminal_entropy"])),
                    "total_cost": f64(cast(float, raw["branch_total_cost"])),
                    "budget_feasible": raw["budget_feasible"],
                }
            )
    return {
        "decision_id": decision.decision_id,
        "step": decision.step,
        "belief_model_id": run.arm.belief_model_id,
        "belief_state_id": decision.belief_state_id,
        "active_sigma_estimate_ids": (
            [item.sigma_estimate_id for item in run.calibration.estimates]
            if run.calibration
            else []
        ),
        "fixed_sigma": f64(0.05) if run.arm.belief_model_id == "fixed_sigma_gaussian" else None,
        "remaining_budget": f64(decision.remaining_budget),
        "completed_candidate_ids": list(completed),
        "unexecuted_candidate_ids": list(unexecuted),
        "publicly_feasible_candidate_ids": list(decision.public_feasible_candidate_ids),
        "affordable_candidate_ids": list(decision.affordable_candidate_ids),
        "selected_candidate_id": decision.selected_candidate_id,
        "candidate_scores": scores,
        "planning_branch_tree": branches,
        "fallback_reason": trace["fallback_reason"],
        "tie_break_order": TIE_BREAK_ORDER,
    }


def _event(
    run: BroaderArmRun,
    sequence: int,
    event_type: str,
    *,
    candidate_id: str | None,
    public_state_sha256: str | None,
    eligibility_state_sha256: str | None,
    sigma_estimate_id: str | None,
    cost_before: float,
    cost_after: float,
    terminal_reason: str | None,
    specific: Mapping[str, object],
    ordered_decisions_sha256: str,
) -> dict[str, object]:
    payload = {
        "schema_version": "canonical-event-payload/v1",
        "event_type": event_type,
        "event_id": f"event/{run.run_id}/{sequence:04d}/{event_type}",
        "run_id": run.run_id,
        "sequence": sequence,
        "comparison_id": run.comparison_id,
        "world_id": run.world_id,
        "seed": run.seed,
        "budget_id": run.budget_id,
        "arm_id": run.arm.arm_id,
        "policy_id": run.arm.policy_id,
        "controller_stage_id": {
            "decision": "CONTROLLER-STAGE-SELECTION",
            "setup": "CONTROLLER-STAGE-EXECUTION",
            "experiment": "CONTROLLER-STAGE-EXECUTION",
            "evidence": "CONTROLLER-STAGE-EVIDENCE",
            "belief_update": "CONTROLLER-STAGE-BELIEF-UPDATE",
            "terminal": "CONTROLLER-STAGE-TERMINATION",
        }[event_type],
        "candidate_id": candidate_id,
        "public_state_sha256": public_state_sha256,
        "ordered_decisions_sha256": ordered_decisions_sha256,
        "eligibility_state_sha256": eligibility_state_sha256,
        "belief_lineage_id": run.lineage.lineage_id,
        "sigma_estimate_id": sigma_estimate_id,
        "cost_before": f64(cost_before),
        "cost_after": f64(cost_after),
        "status": "complete",
        "terminal_reason": terminal_reason,
        "integrity_audit_id": None,
        "event_specific_payload": dict(specific),
    }
    return {
        "event_payload": payload,
        "provenance_sha256": hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
    }


def _sigma_id(run: BroaderArmRun, group_id: str) -> str | None:
    if run.calibration is None or group_id not in GROUP_IDS:
        return None
    return next(
        item.sigma_estimate_id
        for item in run.calibration.estimates
        if item.comparison_group_id == group_id
    )


def _belief_snapshot(belief: BeliefState, lineage_id: str) -> dict[str, object]:
    probabilities = tuple(
        zip(
            belief.hypothesis_ids,
            belief.posterior_probabilities,
            strict=True,
        )
    )
    entropy = -math.fsum(value * math.log2(value) for _, value in probabilities if value > 0.0)
    return {
        "belief_state_id": belief.belief_state_id,
        "lineage_id": lineage_id,
        "sequence": belief.sequence,
        "probabilities": _probability_payload(probabilities),
        "posterior_entropy": f64(entropy),
    }


def _probability_payload(values: Sequence[tuple[str, float]]) -> dict[str, object]:
    return {key: f64(value) for key, value in values}


def _metric_payload(metrics: ArmMetrics) -> dict[str, object]:
    return {
        "true_probability": f64(metrics.true_probability),
        "top_scientific_hypothesis_id": metrics.top_scientific_hypothesis_id,
        "top_probability": f64(metrics.top_probability),
        "prediction_correct": metrics.prediction_correct,
        "confidently_wrong": metrics.confidently_wrong,
        "nll": f64(metrics.nll),
        "brier": f64(metrics.brier),
        "posterior_entropy": f64(metrics.posterior_entropy),
        "conditional_brier_efficiency": (
            f64(metrics.conditional_brier_efficiency)
            if metrics.conditional_brier_efficiency is not None
            else None
        ),
        "end_to_end_brier_efficiency": (
            f64(metrics.end_to_end_brier_efficiency)
            if metrics.end_to_end_brier_efficiency is not None
            else None
        ),
        "decision_cost": f64(metrics.decision_cost),
        "calibration_cost": f64(metrics.calibration_cost),
        "required_total_cost": f64(metrics.required_total_cost),
        "physical_cost_share": f64(metrics.physical_cost_share),
        "best_observed_objective": (
            f64(metrics.best_observed_objective)
            if metrics.best_observed_objective is not None
            else None
        ),
        "matched_pairs": metrics.matched_pairs,
        "redundant_selected": metrics.redundant_selected,
        "irrelevant_selected": metrics.irrelevant_selected,
        "outcome_experiments_completed": metrics.outcome_experiments_completed,
        "setup_actions_completed": metrics.setup_actions_completed,
        "budget_exhausted": metrics.budget_exhausted,
        "terminal_reason": metrics.terminal_reason,
    }


def _run_order(row: Mapping[str, object]) -> tuple[int, int, int, int]:
    world_index = WORLD_ORDER[cast(str, row["world_id"])]
    budget_index = ("budget-2.25", "budget-4.50", "budget-6.75").index(cast(str, row["budget_id"]))
    arm_index = ("fixed_ig", "calibrated_ig", "fixed_lookahead", "calibrated_lookahead").index(
        cast(str, row["arm_id"])
    )
    return world_index, cast(int, row["seed"]), budget_index, arm_index


def _calibration_rows(runs: Sequence[BroaderArmRun]) -> tuple[dict[str, object], ...]:
    calibrated_runs: dict[tuple[str, int], list[BroaderArmRun]] = {}
    for run in runs:
        if run.calibration is None:
            continue
        validate_recorded_calibration(run)
        calibrated_runs.setdefault((run.world_id, run.seed), []).append(run)
    rows: list[dict[str, object]] = []
    for (world_id, seed), deployed in sorted(
        calibrated_runs.items(),
        key=lambda item: (WORLD_ORDER[item[0][0]], item[0][1]),
    ):
        bindings = tuple(
            CalibrationDeploymentBinding(
                run_id=run.run_id,
                lineage_id=run.lineage.lineage_id,
                world_id=run.world_id,
                seed=run.seed,
                budget_id=run.budget_id,
                arm_id=run.arm.arm_id,
                belief_model_id=run.arm.belief_model_id,
                calibration_prefix_ids=tuple(
                    estimate.calibration_prefix_id for estimate in run.calibration.estimates
                ),
            )
            for run in deployed
            if run.calibration is not None
        )
        estimates_by_run = {
            run.run_id: {
                estimate.comparison_group_id: estimate for estimate in run.calibration.estimates
            }
            for run in deployed
            if run.calibration is not None
        }
        if any(tuple(estimates) != GROUP_IDS for estimates in estimates_by_run.values()):
            raise ValueError("Calibration projection requires the frozen group vector per run.")
        for group_id in GROUP_IDS:
            observations_by_run = {
                run_id: estimates[group_id].observations
                for run_id, estimates in estimates_by_run.items()
            }
            claim = reconstruct_complete_calibration_claim(
                world_id=world_id,
                seed=seed,
                comparison_group_id=group_id,
                deployment_bindings=bindings,
                recorded_observations_by_run=observations_by_run,
            )
            rows.append(claim.artifact_row())
    return tuple(rows)


def _oracle_rows(runs: Sequence[BroaderArmRun]) -> tuple[dict[str, object], ...]:
    keys: dict[str, dict[str, object]] = {}
    uses: list[dict[str, object]] = []
    for run in runs:
        observations: list[tuple[RevealedObservation, str, str | None, str | None]] = []
        for selection in validated_calibration_history_selections(run):
            calibration_prefix_id = (
                f"calibration-prefix/{run.world_id}/{run.seed}/{selection.comparison_group_id}"
            )
            for observation in selection.observations:
                observations.append(
                    (
                        observation,
                        "calibration",
                        None,
                        calibration_prefix_id,
                    )
                )
        for action in run.actions:
            if action.oracle_observation:
                observations.append(
                    (action.oracle_observation, "decision", action.decision_id, None)
                )
        for observation, use_kind, decision_id, prefix_id in observations:
            key_row = _oracle_key_row(observation)
            prior = keys.get(observation.oracle_key_id)
            if prior is not None and prior != key_row:
                raise ValueError("Shared Oracle key observations differ across deployments.")
            keys[observation.oracle_key_id] = key_row
            uses.append(
                {
                    "record_type": "oracle_use",
                    "oracle_use_id": observation.oracle_use_id,
                    "oracle_key_id": observation.oracle_key_id,
                    "run_id": run.run_id,
                    "arm_id": run.arm.arm_id,
                    "use_kind": use_kind,
                    "authorization_id": observation.authorization_id,
                    "decision_id": decision_id,
                    "calibration_prefix_id": prefix_id,
                }
            )
    key_rows = sorted(
        keys.values(),
        key=lambda row: tuple(
            str(row[field]).encode("utf-8")
            for field in ("namespace", "world_id", "seed", "candidate_id", "replication_id")
        ),
    )
    uses.sort(
        key=lambda row: tuple(
            str(row[field]).encode("utf-8") for field in ("oracle_key_id", "run_id", "use_kind")
        )
    )
    return (*key_rows, *uses)


def _oracle_key_row(item: RevealedObservation) -> dict[str, object]:
    return {
        "record_type": "oracle_key",
        "oracle_key_id": item.oracle_key_id,
        "namespace": item.namespace,
        "world_id": item.world_id,
        "seed": item.seed,
        "candidate_id": item.candidate_id,
        "comparison_group_id": item.comparison_group_id,
        "intervention_arm": item.intervention_arm,
        "replication_id": item.replication_id,
        "key_fields": list(item.key_fields),
        "serialized_key_hex": item.serialized_key_hex,
        "digest": item.digest,
        "u": item.u,
        "z": item.z,
        "revealed_observation": f64(item.revealed_observation),
        "outcome_digest": item.outcome_digest,
    }


def _comparison_rows(
    comparisons: Sequence[AnalyzedComparison],
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for item in comparisons:
        paired = item.paired
        row: dict[str, object] = {
            "record_type": "divergent" if item.divergent else "nondivergent",
            "comparison_id": paired.comparison_id,
            "policy_id": paired.policy_id,
            "world_id": paired.world_id,
            "seed": paired.seed,
            "budget_id": paired.budget_id,
            "budget": f64(paired.budget),
            "fixed_run_id": paired.fixed_run.run_id,
            "calibrated_run_id": paired.calibrated_run.run_id,
            "fixed_sequence": list(paired.fixed_run.selected_candidate_ids),
            "calibrated_sequence": list(paired.calibrated_run.selected_candidate_ids),
            "nll_difference": f64(paired.calibrated_metrics.nll - paired.fixed_metrics.nll),
            "brier_difference": f64(paired.calibrated_metrics.brier - paired.fixed_metrics.brier),
            "decision_cost_difference": f64(
                paired.calibrated_metrics.decision_cost - paired.fixed_metrics.decision_cost
            ),
            "outcome_label": paired.outcome_label,
        }
        if item.truth_free:
            truth_free = item.truth_free
            row.update(
                {
                    "first_divergence_step": truth_free.first_divergence_step,
                    "fixed_candidate_id": truth_free.fixed_candidate_id,
                    "calibrated_candidate_id": truth_free.calibrated_candidate_id,
                    "pre_divergence_fixed_belief": _belief_snapshot_from_probabilities(
                        paired.fixed_run,
                        truth_free.pre_divergence_fixed_belief,
                        truth_free.first_divergence_step - 1,
                    ),
                    "pre_divergence_calibrated_belief": _belief_snapshot_from_probabilities(
                        paired.calibrated_run,
                        truth_free.pre_divergence_calibrated_belief,
                        truth_free.first_divergence_step - 1,
                    ),
                    "first_action_divergent": truth_free.first_action_divergent,
                    "sequence_class": truth_free.sequence_class,
                    "predicate_results": dict(truth_free.predicate_results),
                    "primary_mechanism_id": truth_free.primary_mechanism_id,
                    "contributing_mechanism_ids": list(truth_free.contributing_mechanism_ids),
                    "controller_stage_id": truth_free.controller_stage_id,
                    "mechanism_row_without_outcome_sha256": (
                        truth_free.mechanism_row_without_outcome_sha256
                    ),
                }
            )
        rows.append(row)
    policy_order = {"information_gain": 0, "lookahead_information_gain": 1}
    rows.sort(
        key=lambda row: (
            policy_order[cast(str, row["policy_id"])],
            WORLD_ORDER[cast(str, row["world_id"])],
            cast(int, row["seed"]),
            _from_f64(cast(str, row["budget"])),
        )
    )
    return tuple(rows)


def _belief_snapshot_from_probabilities(
    run: BroaderArmRun, probabilities: Sequence[tuple[str, float]], sequence: int
) -> dict[str, object]:
    entropy = -math.fsum(value * math.log2(value) for _, value in probabilities if value > 0.0)
    state_id = (
        run.decisions[sequence].belief_state_id
        if sequence < len(run.decisions)
        else run.lineage.current_state.state.belief_state_id
    )
    return {
        "belief_state_id": state_id,
        "lineage_id": run.lineage.lineage_id,
        "sequence": sequence,
        "probabilities": _probability_payload(probabilities),
        "posterior_entropy": f64(entropy),
    }


def _contrast_row(item: ContrastComputation) -> dict[str, object]:
    counts = dict(item.missingness_counts)
    normalized_counts = {
        "n_total_pairs": counts.get("n_total_pairs", sum(counts.values())),
        "n_complete_pairs": counts.get("n_complete_pairs", sum(counts.values())),
        "n_fixed_missing_only": counts.get("n_fixed_missing_only", 0),
        "n_calibrated_missing_only": counts.get("n_calibrated_missing_only", 0),
        "n_both_missing": counts.get("n_both_missing", 0),
    }
    estimated = item.result_status == "ESTIMATED"
    inferential = estimated and item.analysis_class.startswith("confirmatory_")
    return {
        "contrast_id": item.contrast_id,
        "analysis_class": item.analysis_class,
        "research_question_id": item.research_question_id,
        "policy_scope": item.policy_scope,
        "population_scope": item.population_scope,
        "metric_id": item.metric_id,
        "estimand_id": item.estimand_id,
        "source_contrast_id": item.source_contrast_id,
        "missingness_counts": normalized_counts,
        "n_present": item.n_present,
        "n_absent": item.n_absent,
        "present_weight": _optional_f64(item.present_weight),
        "absent_weight": _optional_f64(item.absent_weight),
        "left_value": _optional_f64(item.left_value),
        "right_value": _optional_f64(item.right_value),
        "left_denominator": _optional_f64(item.left_denominator),
        "right_denominator": _optional_f64(item.right_denominator),
        "estimate": _optional_f64(item.estimate) if estimated else None,
        "ci_low": _optional_f64(item.ci_low) if inferential else None,
        "ci_high": _optional_f64(item.ci_high) if inferential else None,
        "usable_bootstrap_replicates": (
            item.usable_bootstrap_replicates
            if item.analysis_class.startswith("confirmatory_")
            else 0
        ),
        "test_statistic": _optional_f64(item.test_statistic) if inferential else None,
        "permutation_count": item.permutation_count if inferential else None,
        "extreme_count": item.extreme_count if inferential else None,
        "p_raw": _optional_f64(item.p_raw) if inferential else None,
        "p_adjusted": _optional_f64(item.p_adjusted) if inferential else None,
        "holm_rank": item.holm_rank if inferential else None,
        "statistical_hypothesis_id": item.statistical_hypothesis_id,
        "holm_member": item.holm_member,
        "result_status": item.result_status,
        "estimability_status": item.estimability_status,
    }


def _resampling_rows(
    analysis: PreGateAnalysisResult | ProductionAnalysisResult,
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for item in analysis.bootstrap_rows:
        rows.append(
            {
                "record_type": "bootstrap",
                "resample_id": f"resample/{item.contrast_id}/bootstrap/{item.replicate_index:05d}",
                "contrast_id": item.contrast_id,
                "replicate_index": item.replicate_index,
                "seed_preimage_utf8_hex": item.seed_preimage.hex(),
                "seed_digest": item.seed_digest.hex(),
                "seed": item.seed,
                "sampled_position_count": 128,
                "completion_status": "complete",
                "result_status": "valid" if item.estimate is not None else "null",
                "failure_code": item.failure_code,
                "sampled_seed_ids_sha256": sampled_seed_ids_sha256(
                    item.contrast_id, item.replicate_index, item.sampled_seed_ids
                ),
                "replicate_estimate": _optional_f64(item.estimate),
            }
        )
    for sign_item in analysis.sign_flip_rows:
        rows.append(
            {
                "record_type": "sign_flip",
                "resample_id": (
                    f"resample/{sign_item.contrast_id}/sign_flip/{sign_item.replicate_index:05d}"
                ),
                "contrast_id": sign_item.contrast_id,
                "replicate_index": sign_item.replicate_index,
                "seed_preimage_utf8_hex": sign_item.seed_preimage.hex(),
                "seed_digest": sign_item.seed_digest.hex(),
                "seed": sign_item.seed,
                "sampled_position_count": 128,
                "completion_status": "complete",
                "result_status": ("valid" if sign_item.statistic is not None else "null"),
                "failure_code": sign_item.failure_code,
                "sign_vector_sha256": sign_vector_sha256(
                    sign_item.contrast_id,
                    sign_item.replicate_index,
                    sign_item.signs,
                ),
                "replicate_statistic": _optional_f64(sign_item.statistic),
                "extreme": sign_item.extreme,
            }
        )
    return tuple(rows)


def _gate_payload(
    snapshot: ProtocolSnapshot,
    analysis: ProductionAnalysisResult,
    audit_results: Sequence[AuditProjectionRecord],
    run_count: int,
    calibration_count: int,
) -> dict[str, object]:
    protocol_payload = build_protocol_snapshot_payload(snapshot)
    registry_hashes = _registry_hashes(protocol_payload)
    gate_by_id = {item.gate_id: item for item in analysis.gates}
    contrast_by_id = {item.contrast_id: item for item in analysis.contrasts}
    audit_statuses = {item.audit_id: GateStatus(item.status) for item in audit_results}
    count_values: dict[str, object] = {
        "COUNT-ARM-RUNS": run_count,
        "COUNT-COMPARISONS": len(analysis.comparisons),
        "COUNT-SIGMA-ROWS": calibration_count,
        "COUNT-CONTRAST-ROWS": 122,
        "FK-ALL": True,
    }
    for policy_scope, policy_id in (
        ("IG", "information_gain"),
        ("LA", "lookahead_information_gain"),
    ):
        classifiable = tuple(
            item
            for item in analysis.comparisons
            if item.paired.policy_id == policy_id and item.truth_free is not None
        )
        count_values[f"COUNT-PRIMARY-SF-{policy_scope}"] = float(
            sum(
                item.truth_free is not None
                and item.truth_free.primary_mechanism_id == "SCORE_FLATTENING"
                for item in classifiable
            )
        )
        count_values[f"COUNT-PRIMARY-GSR-{policy_scope}"] = float(
            sum(
                item.truth_free is not None
                and item.truth_free.primary_mechanism_id == "GROUP_SIGMA_REORDERING"
                for item in classifiable
            )
        )
    condition_rows = snapshot.registry("gate_condition").records()
    conditions_by_gate: dict[str, list[dict[str, object]]] = {}
    for specification in condition_rows:
        gate = gate_by_id[specification["gate_id"]]
        operands = specification["ordered_operand_ids"].split(";")
        observed = [
            _observed_value(
                operand,
                contrast_by_id,
                gate_by_id,
                audit_statuses,
                count_values,
                analysis,
            )
            for operand in operands
        ]
        branch_result = None
        gate_result: str | None = gate.status.value
        if specification["result_enum"] == "branch_match_status":
            gate_result = None
            branch_result = _branch_result(analysis.decision, specification["condition_id"])
        block_results = (
            _block_results_for_gate(gate.gate_id, operands, contrast_by_id)
            if gate.formula_id == "F-ACTION"
            else []
        )
        conditions_by_gate.setdefault(gate.gate_id, []).append(
            {
                "condition_id": specification["condition_id"],
                "condition_sha256": registry_hashes["gate_condition"][
                    specification["condition_id"]
                ],
                "condition_order": int(specification["condition_order"]),
                "gate_id": gate.gate_id,
                "ordered_operand_ids": operands,
                "quantifier": specification["quantifier"],
                "observed_values": observed,
                "block_results": block_results,
                "resolution_status": (
                    "inconclusive" if gate.status is GateStatus.INCONCLUSIVE else "resolved"
                ),
                "gate_status_result": gate_result,
                "branch_match_status_result": branch_result,
            }
        )
    gate_rows = [
        {
            "gate_id": item.gate_id,
            "gate_sha256": registry_hashes["gate"][item.gate_id],
            "gate_order": index,
            "formula_id": item.formula_id,
            "formula_sha256": registry_hashes["formula"][item.formula_id],
            "conditions": conditions_by_gate[item.gate_id],
            "gate_status": item.status.value,
        }
        for index, item in enumerate(analysis.gates, 1)
    ]
    veto_rows = _veto_payloads(snapshot, analysis, registry_hashes)
    unique = {item.mechanism_id for item in analysis.action_partition.surviving_tuples}
    branch_trace = _branch_trace(snapshot, analysis.decision)
    decision_booleans = {
        "ACTIONABILITY_COMPLETE": analysis.actionability.actionability_complete,
        "VETO_COMPLETE": analysis.action_partition.veto_complete,
        "CONTROLLER_CHANGE_NEEDED": cast(DecisionBoolean, gate_by_id["G-CONTROLLER-CHANGE"].output),
        "UNIQUE_ACTIONABLE_MECHANISM": cast(
            DecisionBoolean, gate_by_id["G-UNIQUE-ACTIONABLE-MECHANISM"].output
        ),
        "PPO_ELIGIBLE": cast(DecisionBoolean, gate_by_id["G-PPO"].output),
        "B_AUTHORIZED": cast(DecisionBoolean, gate_by_id["G-B-AUTHORIZATION"].output),
    }
    return {
        "evaluation_id": PROTOCOL_VERSION,
        "gates": gate_rows,
        "P_RAW": [_action_tuple(item) for item in analysis.actionability.p_raw],
        "veto_evaluations": veto_rows,
        "VETOED_TUPLES": [_action_tuple(item) for item in analysis.action_partition.vetoed_tuples],
        "P": [_action_tuple(item) for item in analysis.action_partition.surviving_tuples],
        **{key: _decision_boolean(value) for key, value in decision_booleans.items()},
        "unique_mechanism_id": next(iter(unique)) if len(unique) == 1 else None,
        "final_branch_id": analysis.decision.branch_id,
        "final_branch_trace": branch_trace,
        "final_gate_status": analysis.decision.gate_status.value,
        "recommendation": analysis.decision.recommendation,
        "decision_precedence": int(
            next(
                row["branch_order"]
                for row in snapshot.registry("branch").records()
                if row["branch_id"] == analysis.decision.branch_id
            )
        ),
    }


def _observed_value(
    operand: str,
    contrasts: Mapping[str, ContrastComputation],
    gates: Mapping[str, GateComputation],
    audits: Mapping[str, GateStatus],
    counts: Mapping[str, object],
    analysis: ProductionAnalysisResult,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "operand_id": operand,
        "value_type": "gate_status",
        "boolean_value": None,
        "integer_value": None,
        "scalar_value": None,
        "gate_status_value": None,
        "contrast_status_value": None,
        "tuple_set_value": None,
        "veto_status_value": None,
        "branch_match_status_value": None,
    }
    if operand in contrasts:
        fields["value_type"] = "contrast_status"
        fields["contrast_status_value"] = contrasts[operand].result_status
    elif operand in gates:
        fields["gate_status_value"] = gates[operand].status.value
    elif operand in audits:
        fields["gate_status_value"] = audits[operand].value
    elif operand in counts:
        value = counts[operand]
        if isinstance(value, bool):
            fields["value_type"] = "boolean"
            fields["boolean_value"] = value
        elif isinstance(value, int):
            fields["value_type"] = "integer"
            fields["integer_value"] = value
        else:
            fields["value_type"] = "scalar"
            fields["scalar_value"] = f64(cast(float, value))
    elif operand == "P_RAW":
        fields["value_type"] = "tuple_set"
        fields["tuple_set_value"] = [_action_tuple(item) for item in analysis.actionability.p_raw]
    elif operand == "P":
        fields["value_type"] = "tuple_set"
        fields["tuple_set_value"] = [
            _action_tuple(item) for item in analysis.action_partition.surviving_tuples
        ]
    elif operand.startswith("V") and operand[1:].isdigit():
        index = int(operand[1:]) - 1
        fields["value_type"] = "veto_status"
        fields["veto_status_value"] = analysis.veto_results[index].veto_status
    elif operand.startswith("G-FINAL/C"):
        fields["value_type"] = "branch_match_status"
        fields["branch_match_status_value"] = _branch_result(analysis.decision, operand)
    else:
        symbol_gate = {
            "ACTIONABILITY_COMPLETE": "G-ACTIONABILITY-COMPLETE",
            "VETO_COMPLETE": "G-VETO-COMPLETE",
            "CONTROLLER_CHANGE_NEEDED": "G-CONTROLLER-CHANGE",
            "UNIQUE_ACTIONABLE_MECHANISM": "G-UNIQUE-ACTIONABLE-MECHANISM",
            "PPO_ELIGIBLE": "G-PPO",
            "B_AUTHORIZED": "G-B-AUTHORIZATION",
        }.get(operand)
        if symbol_gate:
            fields["gate_status_value"] = gates[symbol_gate].status.value
        else:
            fields["gate_status_value"] = "INCONCLUSIVE"
    return fields


def _block_results_for_gate(
    gate_id: str,
    operand_ids: Sequence[str],
    contrasts: Mapping[str, ContrastComputation],
) -> list[dict[str, object]]:
    decision = next(
        item
        for item in contrasts.values()
        if item.analysis_class == "decision_operand"
        and _gate_for_decision(item.contrast_id) == gate_id
    )
    composite = cast(ActionabilityComposite, decision.actionability)
    blocks = composite.blocks
    pooled = composite.pooled.estimate
    result = []
    for block in blocks:
        support = block.n_divergent >= 20 and block.n_present >= 5 and block.n_absent >= 5
        same = (
            block.estimate * pooled > 0.0
            if block.estimate is not None and pooled is not None and pooled != 0.0
            else None
        )
        opposite = (
            block.estimate * pooled < 0.0 and abs(block.estimate) >= 0.10
            if block.estimate is not None and pooled is not None
            else None
        )
        result.append(
            {
                "population_id": block.population_id,
                "operand_contrast_ids": list(operand_ids),
                "required": True,
                "n_divergent": block.n_divergent,
                "n_present": block.n_present,
                "n_absent": block.n_absent,
                "estimate": _optional_f64(block.estimate),
                "estimability_status": block.estimability_status,
                "support_predicate_passed": support,
                "same_direction_predicate_passed": same,
                "opposite_direction_predicate_passed": opposite,
                "resolution_status": (
                    "resolved" if block.estimability_status == "estimated" else "inconclusive"
                ),
            }
        )
    return result


def _gate_for_decision(contrast_id: str) -> str:
    return next(
        row["gate_id"]
        for row in load_protocol_snapshot().registry("decision").records()
        if row["contrast_id"] == contrast_id
    )


def _veto_payloads(
    snapshot: ProtocolSnapshot,
    analysis: ProductionAnalysisResult,
    hashes: Mapping[str, Mapping[str, str]],
) -> list[dict[str, object]]:
    contrast = {item.contrast_id: item for item in analysis.contrasts}
    result_by_tuple = {item.source_tuple: item for item in analysis.veto_results}
    actions = {
        item.source_tuple.decision_contrast_id: item.source_tuple for item in analysis.veto_results
    }
    rows = []
    for specification in snapshot.registry("veto").records():
        source = actions[specification["decision_contrast_id"]]
        own = contrast[specification["own_confirmatory_contrast_id"]]
        other = contrast[specification["required_veto_contrast_id"]]
        result = result_by_tuple[source]
        opposite = (
            own.estimate * other.estimate < 0.0
            if own.estimate is not None and other.estimate is not None
            else None
        )
        rows.append(
            {
                "veto_id": specification["veto_id"],
                "veto_sha256": hashes["veto"][specification["veto_id"]],
                "source_tuple": _action_tuple(source),
                "required_veto_contrast_id": specification["required_veto_contrast_id"],
                "support_resolved": other.result_status == "ESTIMATED",
                "present_count": other.n_present or 0,
                "absent_count": other.n_absent or 0,
                "other_contrast_status": other.result_status,
                "own_effect": _optional_f64(own.estimate),
                "other_effect": _optional_f64(other.estimate),
                "opposite_sign": opposite,
                "effect_threshold_passed": (
                    abs(other.estimate) >= 0.15 if other.estimate is not None else None
                ),
                "ci_condition_passed": (
                    other.ci_high < 0.0 or other.ci_low > 0.0
                    if other.ci_low is not None and other.ci_high is not None
                    else None
                ),
                "holm_condition_passed": (
                    other.p_adjusted < 0.05 if other.p_adjusted is not None else None
                ),
                "veto_status": result.veto_status,
            }
        )
    return rows


def _branch_trace(snapshot: ProtocolSnapshot, decision: BranchDecision) -> dict[str, object]:
    row = next(
        item
        for item in snapshot.registry("branch").records()
        if item["branch_id"] == decision.branch_id
    )
    match_by_branch = dict(decision.branch_matches)
    condition_results = [
        match_by_branch[_branch_for_condition(condition_id)]
        for condition_id in row["ordered_condition_ids"].split(";")
    ]
    return {
        "branch_id": decision.branch_id,
        "ordered_condition_ids_evaluated": row["ordered_condition_ids"].split(";"),
        "first_decisive_condition_id": row["first_decisive_condition_id"],
        "final_output": row["final_output"],
        "required_operand_statuses": row["required_operand_statuses"],
        "unreachable_condition_behavior": row["unreachable_condition_behavior"],
        "condition_results": condition_results,
        "gate_status": decision.gate_status.value,
    }


def _branch_for_condition(condition_id: str) -> str:
    return {
        "G-FINAL/C01": "BRANCH-B",
        "G-FINAL/C02": "BRANCH-C",
        "G-FINAL/C03": "BRANCH-D",
        "G-FINAL/C04": "BRANCH-A",
    }[condition_id]


def _branch_result(decision: BranchDecision, condition_id: str) -> str:
    return dict(decision.branch_matches)[_branch_for_condition(condition_id)]


def _audit_payload(
    snapshot: ProtocolSnapshot, audit_results: Sequence[AuditProjectionRecord]
) -> dict[str, object]:
    by_id = {item.audit_id: item for item in audit_results}
    rows = []
    for specification in snapshot.registry("audit").records():
        result = by_id[specification["audit_id"]]
        status = result.status
        rows.append(
            {
                "audit_id": specification["audit_id"],
                "audit_order": int(specification["audit_order"]),
                "expected": specification["requirement"],
                "observed": result.observed,
                "status": status,
                "audit_detail_sha256": protocol_hash(
                    "audit_detail/v1",
                    {
                        "audit_id": specification["audit_id"],
                        "expected": specification["requirement"],
                        "observed": result.observed,
                    },
                ),
            }
        )
    return {
        "evaluation_id": PROTOCOL_VERSION,
        "audits": rows,
        "all_passed": all(item["status"] == "PASS" for item in rows),
    }


def _manifest_payload(
    runs: int,
    comparisons: int,
    calibration: int,
    bootstrap: int,
    sign_flip: int,
    event_rows: Sequence[Mapping[str, object]],
    oracle_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    expected = {
        "arm_runs": 36_864,
        "fixed_calibrated_comparisons": 18_432,
        "calibration_estimates": 9_216,
        "calibration_effects": 46_080,
        "calibration_observations": 92_160,
        "calibration_oracle_use_rows": 552_960,
        "oracle_conformance_keys": 117_952,
        "confirmatory_contrasts": 66,
        "holm_hypotheses": 64,
        "decision_contrasts": 20,
        "descriptive_contrasts": 36,
        "contrast_rows": 122,
        "bootstrap_rows": 660_000,
        "sign_flip_rows": 640_000,
        "total_resampling_rows": 1_300_000,
        "count_symbol_registry_rows": 9,
        "decision_symbol_registry_rows": 9,
        "formula_registry_rows": 43,
        "gate_condition_registry_rows": 66,
        "gate_rows": 44,
        "branch_registry_rows": 4,
        "controller_stage_registry_rows": 6,
        "budget_registry_rows": 3,
        "audit_rows": 16,
        "canonical_artifacts": 13,
    }
    decision_events = sum(
        cast(dict[str, object], row["event_payload"])["event_type"] == "decision"
        for row in event_rows
    )
    selected_oracle_uses = sum(row["record_type"] == "oracle_use" for row in oracle_rows)
    return {
        "evaluation_id": PROTOCOL_VERSION,
        "status": "complete",
        "expected_counts": expected,
        "observed_counts": {
            "arm_runs": runs,
            "fixed_calibrated_comparisons": comparisons,
            "calibration_estimates": calibration,
            "contrast_rows": 122,
            "bootstrap_rows": bootstrap,
            "sign_flip_rows": sign_flip,
            "decision_events": decision_events,
            "trajectory_events": len(event_rows),
            "selected_oracle_uses": selected_oracle_uses,
        },
        "database_schema_version": 0,
    }


def _registry_hashes(payload: Mapping[str, object]) -> dict[str, dict[str, str]]:
    mappings = {
        "formula": ("formula_registry", "formula_id", "formula_sha256"),
        "gate": ("gate_registry", "gate_id", "gate_sha256"),
        "gate_condition": (
            "gate_condition_registry",
            "condition_id",
            "condition_sha256",
        ),
        "veto": ("veto_registry", "veto_id", "veto_sha256"),
    }
    return {
        name: {
            cast(str, row[id_field]): cast(str, row[hash_field])
            for row in cast(list[dict[str, object]], payload[registry_field])
        }
        for name, (registry_field, id_field, hash_field) in mappings.items()
    }


def _action_tuple(item: ActionTuple) -> dict[str, object]:
    return {
        "policy_scope": item.policy_scope,
        "mechanism_id": item.mechanism_id,
        "decision_contrast_id": item.decision_contrast_id,
        "confirmatory_contrast_id": item.confirmatory_contrast_id,
    }


def _decision_boolean(item: DecisionBoolean) -> dict[str, object]:
    return {
        "value": item.value,
        "resolution_status": item.resolution_status,
        "source_ids": list(item.source_ids),
    }


def _optional_f64(value: float | None) -> str | None:
    return f64(value) if value is not None else None


def _from_f64(value: str) -> float:
    import struct

    return cast(float, struct.unpack(">d", bytes.fromhex(value.removeprefix("f64:")))[0])
