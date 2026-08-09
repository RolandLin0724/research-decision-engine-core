"""Deterministic, non-scientific production conformance fixture."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, Literal, cast, overload

from research_decision_engine.benchmarks.broader_analysis import (
    PreGateAnalysisResult,
    ProductionAnalysisConfig,
    ProductionAnalysisResult,
    analyze_scientific_artifacts,
    derive_provisional_analysis,
    finalize_analysis_with_audits,
)
from research_decision_engine.benchmarks.broader_artifact_graph import (
    ArtifactCardinalityProfile,
)
from research_decision_engine.benchmarks.broader_assembly import (
    AssemblyOperationalProvenance,
    CanonicalFinalizationPlan,
    PrefinalizationArtifactSet,
    assemble_prefinalization_artifacts,
    authorize_validation_finalization,
    reconstruct_actual_operational_provenance,
)
from research_decision_engine.benchmarks.broader_audits import (
    FinalizationAuditCertificate,
    FinalizationAuthorization,
    FixtureAuditDiagnostic,
    IntegrityAuditContext,
    IntegrityAuditResult,
    _register_fixture_audit_diagnostics,
    _run_fixture_finalization_audit,
    _run_fixture_pre_finalization_audits,
    execute_finalization_audit,
    execute_pre_finalization_audits,
    finalization_audit_results,
    historical_hash_map,
    invalidate_finalization_audit_certificate,
)
from research_decision_engine.benchmarks.broader_execution import (
    _DIAGNOSTIC_CONFORMANCE_EXECUTION_KEY,
    _PRODUCTION_CONFORMANCE_EXECUTION_KEY,
    ActualExecutorAttestation,
    execute_deterministic_map,
    executor_provenance_payload,
    validate_executor_attestation,
)
from research_decision_engine.benchmarks.broader_oracle import (
    ObservationAuthority,
    OracleConformanceResult,
    OracleEvidenceBinding,
    OracleFixtureBinding,
    OracleFixtureEvidence,
    OracleFixtureResult,
    _validate_oracle_fixture_evidence,
    validate_oracle_conformance_result,
)
from research_decision_engine.benchmarks.broader_projection import (
    _build_fixture_post_audit_payloads,
    build_post_audit_payloads,
    build_prefinalization_payloads,
)
from research_decision_engine.benchmarks.broader_protocol import (
    ARMS,
    FrozenArm,
    canonical_json_bytes,
)
from research_decision_engine.benchmarks.broader_runner import BroaderArmRun, run_arm
from research_decision_engine.benchmarks.broader_statistics import GateStatus
from research_decision_engine.benchmarks.broader_worlds import (
    BUDGETS,
    WORLDS_BY_ID,
    PublicFeasibilityState,
)

CONFORMANCE_WORLD_ID: Final = "g_sgd_hml"
CONFORMANCE_DEPTH_THREE_WORLD_ID: Final = "d3_adam"
CONFORMANCE_SEEDS: Final = tuple(range(1000, 1020))
CONFORMANCE_DEPTH_THREE_SEEDS: Final = (1000,)
CONFORMANCE_BOOTSTRAP_REPLICATES: Final = 4
CONFORMANCE_SIGN_FLIP_REPLICATES: Final = 4
CONFORMANCE_PROFILE: Final = ArtifactCardinalityProfile.conformance_fixture(
    arm_runs=252,
    comparisons=126,
    calibration_estimates=63,
    bootstrap_replicates=CONFORMANCE_BOOTSTRAP_REPLICATES,
    sign_flip_replicates=CONFORMANCE_SIGN_FLIP_REPLICATES,
)


@dataclass(frozen=True, slots=True)
class ProductionConformanceFixture:
    """Raw trajectories, analysis, and payloads from one production-path fixture."""

    runs: tuple[BroaderArmRun, ...]
    replay_runs: tuple[BroaderArmRun, ...]
    raw_analysis: PreGateAnalysisResult
    analysis: ProductionAnalysisResult
    prefinalization_payloads: Mapping[str, object]
    prefinalization: PrefinalizationArtifactSet
    finalization_plan: CanonicalFinalizationPlan
    operational: AssemblyOperationalProvenance
    audits: tuple[IntegrityAuditResult, ...]
    early_optimizer_rejection_verified: bool
    executor_attestation: ActualExecutorAttestation
    replay_executor_attestation: ActualExecutorAttestation
    oracle_conformance_result: OracleConformanceResult
    oracle_evidence_binding: OracleEvidenceBinding


@dataclass(frozen=True, slots=True)
class DiagnosticConformanceFixture:
    """Bounded conformance data carrying no production audit or Oracle authority."""

    runs: tuple[BroaderArmRun, ...]
    replay_runs: tuple[BroaderArmRun, ...]
    raw_analysis: PreGateAnalysisResult
    analysis: ProductionAnalysisResult
    prefinalization_payloads: Mapping[str, object]
    prefinalization: PrefinalizationArtifactSet
    finalization_plan: CanonicalFinalizationPlan
    operational: AssemblyOperationalProvenance
    audits: tuple[FixtureAuditDiagnostic, ...]
    early_optimizer_rejection_verified: bool
    executor_attestation: ActualExecutorAttestation
    replay_executor_attestation: ActualExecutorAttestation
    oracle_fixture_result: OracleFixtureResult
    oracle_fixture_binding: OracleFixtureBinding


_ISSUED_PRODUCTION_FIXTURES: dict[int, ProductionConformanceFixture] = {}


def build_production_fixture(
    *,
    oracle_conformance_result: OracleConformanceResult,
    oracle_evidence_binding: OracleEvidenceBinding,
) -> ProductionConformanceFixture:
    """Build the bounded fixture from exact, currently valid production evidence."""

    _require_oracle_evidence(
        oracle_conformance_result,
        oracle_evidence_binding,
    )
    fixture = _build_production_fixture_uncached(
        oracle_conformance_result=oracle_conformance_result,
        oracle_evidence_binding=oracle_evidence_binding,
    )
    _require_oracle_evidence(oracle_conformance_result, oracle_evidence_binding)
    return fixture


def _require_oracle_evidence(
    result: OracleConformanceResult,
    binding: OracleEvidenceBinding,
) -> None:
    if validate_oracle_conformance_result(result, binding=binding) is not result:
        raise RuntimeError("Oracle conformance validation returned another result.")


def _build_diagnostic_conformance_fixture(
    *,
    oracle_fixture_evidence: OracleFixtureEvidence,
) -> DiagnosticConformanceFixture:
    """Build bounded test data in a trust domain rejected by production consumers."""

    evidence = _validate_oracle_fixture_evidence(oracle_fixture_evidence)
    fixture = _build_diagnostic_conformance_fixture_uncached(
        oracle_fixture_evidence=evidence,
    )
    _validate_oracle_fixture_evidence(evidence)
    return fixture


def _build_production_fixture_uncached(
    *,
    oracle_conformance_result: OracleConformanceResult,
    oracle_evidence_binding: OracleEvidenceBinding,
) -> ProductionConformanceFixture:
    return _build_conformance_fixture_data(
        oracle_conformance_result=oracle_conformance_result,
        oracle_evidence_binding=oracle_evidence_binding,
        oracle_fixture_evidence=None,
    )


def _build_diagnostic_conformance_fixture_uncached(
    *,
    oracle_fixture_evidence: OracleFixtureEvidence,
) -> DiagnosticConformanceFixture:
    evidence = _validate_oracle_fixture_evidence(oracle_fixture_evidence)
    return _build_conformance_fixture_data(
        oracle_conformance_result=None,
        oracle_evidence_binding=None,
        oracle_fixture_evidence=evidence,
    )


@overload
def _build_conformance_fixture_data(
    *,
    oracle_conformance_result: OracleConformanceResult,
    oracle_evidence_binding: OracleEvidenceBinding,
    oracle_fixture_evidence: None,
) -> ProductionConformanceFixture: ...


@overload
def _build_conformance_fixture_data(
    *,
    oracle_conformance_result: None,
    oracle_evidence_binding: None,
    oracle_fixture_evidence: OracleFixtureEvidence,
) -> DiagnosticConformanceFixture: ...


def _build_conformance_fixture_data(
    *,
    oracle_conformance_result: OracleConformanceResult | None,
    oracle_evidence_binding: OracleEvidenceBinding | None,
    oracle_fixture_evidence: OracleFixtureEvidence | None,
) -> ProductionConformanceFixture | DiagnosticConformanceFixture:
    """Execute the frozen production path over a small validation-only population."""

    frozen_world = WORLDS_BY_ID[CONFORMANCE_DEPTH_THREE_WORLD_ID]
    execution_authority: OracleEvidenceBinding | OracleFixtureBinding
    execution_purpose: Literal["production_conformance", "diagnostic_conformance"]
    if oracle_fixture_evidence is None:
        if type(oracle_evidence_binding) is not OracleEvidenceBinding:
            raise ValueError("Production conformance execution requires exact Oracle binding.")
        execution_authority = oracle_evidence_binding
        execution_purpose = "production_conformance"
    else:
        execution_authority = _validate_oracle_fixture_evidence(oracle_fixture_evidence).binding
        execution_purpose = "diagnostic_conformance"
    runs, executor_attestation = _execute_runs(
        execution_authority=execution_authority,
        execution_purpose=execution_purpose,
    )
    replay_runs, replay_attestation = _execute_runs(
        execution_authority=execution_authority,
        execution_purpose=execution_purpose,
    )
    first_executor = executor_provenance_payload(executor_attestation)
    replay_executor = executor_provenance_payload(replay_attestation)
    comparable_fields = (
        "worker_configuration_sha256",
        "worker_count",
        "worker_executor_kind",
        "worker_order",
        "worker_result_payload_order_sha256",
        "worker_scheduling_mode",
        "worker_submission_order_sha256",
        "worker_submitted_job_count",
    )
    if any(first_executor[field] != replay_executor[field] for field in comparable_fields):
        raise ValueError("Production conformance replay used a different actual executor.")
    raw_analysis = analyze_scientific_artifacts(
        runs,
        config=ProductionAnalysisConfig(
            bootstrap_replicates=CONFORMANCE_BOOTSTRAP_REPLICATES,
            sign_flip_replicates=CONFORMANCE_SIGN_FLIP_REPLICATES,
        ),
    )
    operational = _operational_provenance(
        executor_attestation,
        runs=runs,
        execution_authority=execution_authority,
        execution_purpose=execution_purpose,
    )
    prefinalization_payloads = build_prefinalization_payloads(runs, raw_analysis)
    prefinalization = assemble_prefinalization_artifacts(
        prefinalization_payloads,
        operational,
        profile=CONFORMANCE_PROFILE,
    )
    analysis: ProductionAnalysisResult
    audits: tuple[IntegrityAuditResult, ...] | tuple[FixtureAuditDiagnostic, ...]
    if oracle_fixture_evidence is None:
        if (
            type(oracle_conformance_result) is not OracleConformanceResult
            or type(oracle_evidence_binding) is not OracleEvidenceBinding
        ):
            raise ValueError("Production conformance data requires exact Oracle evidence.")
        analysis, audits, certificate = _execute_audited_lifecycle(
            runs,
            replay_runs,
            raw_analysis,
            prefinalization_payloads,
            prefinalization,
            executor_attestation,
            replay_attestation,
            oracle_conformance_result,
            oracle_evidence_binding,
        )
    else:
        if oracle_conformance_result is not None or oracle_evidence_binding is not None:
            raise ValueError("Fixture conformance data cannot carry production Oracle evidence.")
        analysis, audits = _execute_fixture_audited_lifecycle(
            runs,
            replay_runs,
            raw_analysis,
            prefinalization_payloads,
            prefinalization,
            executor_attestation,
            replay_attestation,
            oracle_fixture_evidence,
        )
    if oracle_fixture_evidence is None:
        try:
            post_audit = build_post_audit_payloads(
                runs,
                analysis,
                cast(tuple[IntegrityAuditResult, ...], audits),
                prefinalization_payloads,
            )
        finally:
            invalidate_finalization_audit_certificate(certificate)
    else:
        post_audit = _build_fixture_post_audit_payloads(
            runs,
            analysis,
            cast(tuple[FixtureAuditDiagnostic, ...], audits),
            prefinalization_payloads,
        )
    finalization_plan = CanonicalFinalizationPlan(prefinalization, post_audit)
    calibration_rows = cast(
        Sequence[object],
        prefinalization.scientific_claims()["calibration_estimates.jsonl"],
    )
    if len(calibration_rows) != CONFORMANCE_PROFILE.calibration_estimates:
        raise ValueError("Production conformance calibration count differs from its profile.")
    state = PublicFeasibilityState(frozen_world.public)
    try:
        state.complete("g00-adam-r1")
    except ValueError:
        early_rejection = True
    else:
        early_rejection = False
    if not early_rejection:
        raise ValueError("Depth-three conformance failed to reject an early optimizer arm.")
    if oracle_fixture_evidence is None:
        fixture = ProductionConformanceFixture(
            runs,
            replay_runs,
            raw_analysis,
            analysis,
            prefinalization_payloads,
            prefinalization,
            finalization_plan,
            operational,
            cast(tuple[IntegrityAuditResult, ...], audits),
            early_rejection,
            executor_attestation,
            replay_attestation,
            cast(OracleConformanceResult, oracle_conformance_result),
            cast(OracleEvidenceBinding, oracle_evidence_binding),
        )
        _ISSUED_PRODUCTION_FIXTURES[id(fixture)] = fixture
        return fixture
    evidence = _validate_oracle_fixture_evidence(oracle_fixture_evidence)
    return DiagnosticConformanceFixture(
        runs,
        replay_runs,
        raw_analysis,
        analysis,
        prefinalization_payloads,
        prefinalization,
        finalization_plan,
        operational,
        cast(tuple[FixtureAuditDiagnostic, ...], audits),
        early_rejection,
        executor_attestation,
        replay_attestation,
        evidence.result,
        evidence.binding,
    )


def _execute_audited_lifecycle(
    runs: tuple[BroaderArmRun, ...],
    replay_runs: tuple[BroaderArmRun, ...],
    raw_analysis: PreGateAnalysisResult,
    prefinalization_payloads: Mapping[str, object],
    prefinalization: PrefinalizationArtifactSet,
    executor_attestation: ActualExecutorAttestation,
    replay_executor_attestation: ActualExecutorAttestation,
    oracle_conformance_result: OracleConformanceResult,
    oracle_evidence_binding: OracleEvidenceBinding,
) -> tuple[
    ProductionAnalysisResult,
    tuple[IntegrityAuditResult, ...],
    FinalizationAuditCertificate,
]:
    audit_context = _conformance_audit_context(
        runs,
        replay_runs,
        raw_analysis,
        prefinalization_payloads,
        prefinalization,
        executor_attestation,
        replay_executor_attestation,
        oracle_conformance_result,
        oracle_evidence_binding,
    )
    pre_authorization = execute_pre_finalization_audits(audit_context)
    provisional_analysis = derive_provisional_analysis(raw_analysis, run_count=len(runs))
    finalization_context = replace(audit_context, analysis=provisional_analysis)
    certificate = execute_finalization_audit(finalization_context, pre_authorization)
    audits = finalization_audit_results(certificate)
    audit_statuses = {item.audit_id: GateStatus(item.status) for item in audits}
    analysis = finalize_analysis_with_audits(provisional_analysis, audit_statuses)
    return analysis, audits, certificate


def _execute_fixture_audited_lifecycle(
    runs: tuple[BroaderArmRun, ...],
    replay_runs: tuple[BroaderArmRun, ...],
    raw_analysis: PreGateAnalysisResult,
    prefinalization_payloads: Mapping[str, object],
    prefinalization: PrefinalizationArtifactSet,
    executor_attestation: ActualExecutorAttestation,
    replay_executor_attestation: ActualExecutorAttestation,
    oracle_fixture_evidence: OracleFixtureEvidence,
) -> tuple[ProductionAnalysisResult, tuple[FixtureAuditDiagnostic, ...]]:
    """Compute bounded fixture observations without issuing finalization authority."""

    evidence = _validate_oracle_fixture_evidence(oracle_fixture_evidence)
    audit_context = _fixture_conformance_audit_context(
        runs,
        replay_runs,
        raw_analysis,
        prefinalization_payloads,
        prefinalization,
        executor_attestation,
        replay_executor_attestation,
        evidence,
    )
    pre_audits = _run_fixture_pre_finalization_audits(
        audit_context,
        oracle_fixture_evidence=evidence,
    )
    provisional_analysis = derive_provisional_analysis(raw_analysis, run_count=len(runs))
    finalization_context = replace(audit_context, analysis=provisional_analysis)
    audits = (
        *pre_audits,
        _run_fixture_finalization_audit(
            finalization_context,
            oracle_fixture_evidence=evidence,
        ),
    )
    if any(item.status != "PASS" for item in audits):
        raise ValueError("Bounded fixture audit observations did not all pass.")
    _register_fixture_audit_diagnostics(
        finalization_context,
        audits,
        oracle_fixture_evidence=evidence,
    )
    audit_statuses = {item.audit_id: GateStatus(item.status) for item in audits}
    return finalize_analysis_with_audits(provisional_analysis, audit_statuses), audits


def _conformance_audit_context(
    runs: tuple[BroaderArmRun, ...],
    replay_runs: tuple[BroaderArmRun, ...],
    raw_analysis: PreGateAnalysisResult,
    prefinalization_payloads: Mapping[str, object],
    prefinalization: PrefinalizationArtifactSet,
    executor_attestation: ActualExecutorAttestation,
    replay_executor_attestation: ActualExecutorAttestation,
    oracle_conformance_result: OracleConformanceResult,
    oracle_evidence_binding: OracleEvidenceBinding,
) -> IntegrityAuditContext:
    first_payload = _replay_payload(runs)
    replay_payload = _replay_payload(replay_runs)
    historical = historical_hash_map()
    return IntegrityAuditContext(
        runs=runs,
        replay_runs=replay_runs,
        first_payload=first_payload,
        replay_payload=replay_payload,
        historical_before=historical,
        historical_after=historical,
        scope="conformance",
        artifact_graph=prefinalization.graph,
        analysis=raw_analysis,
        profile=CONFORMANCE_PROFILE,
        prefinalization_payloads=prefinalization_payloads,
        oracle_conformance_result=oracle_conformance_result,
        oracle_evidence_binding=oracle_evidence_binding,
        prefinal_operational_provenance_sha256=(prefinalization.operational_provenance_sha256),
        executor_attestation=executor_attestation,
        replay_executor_attestation=replay_executor_attestation,
        executor_results=runs,
        replay_executor_results=replay_runs,
        execution_authority=oracle_evidence_binding,
        execution_purpose="production_conformance",
    )


def _fixture_conformance_audit_context(
    runs: tuple[BroaderArmRun, ...],
    replay_runs: tuple[BroaderArmRun, ...],
    raw_analysis: PreGateAnalysisResult,
    prefinalization_payloads: Mapping[str, object],
    prefinalization: PrefinalizationArtifactSet,
    executor_attestation: ActualExecutorAttestation,
    replay_executor_attestation: ActualExecutorAttestation,
    oracle_fixture_evidence: OracleFixtureEvidence,
) -> IntegrityAuditContext:
    evidence = _validate_oracle_fixture_evidence(oracle_fixture_evidence)
    first_payload = _replay_payload(runs)
    replay_payload = _replay_payload(replay_runs)
    historical = historical_hash_map()
    return IntegrityAuditContext(
        runs=runs,
        replay_runs=replay_runs,
        first_payload=first_payload,
        replay_payload=replay_payload,
        historical_before=historical,
        historical_after=historical,
        scope="conformance",
        artifact_graph=prefinalization.graph,
        analysis=raw_analysis,
        profile=CONFORMANCE_PROFILE,
        prefinalization_payloads=prefinalization_payloads,
        oracle_fixture_result=evidence.result,
        oracle_fixture_binding=evidence.binding,
        prefinal_operational_provenance_sha256=(prefinalization.operational_provenance_sha256),
        executor_attestation=executor_attestation,
        replay_executor_attestation=replay_executor_attestation,
        executor_results=runs,
        replay_executor_results=replay_runs,
        execution_authority=evidence.binding,
        execution_purpose="diagnostic_conformance",
    )


def _execute_runs(
    *,
    execution_authority: OracleEvidenceBinding | OracleFixtureBinding,
    execution_purpose: Literal["production_conformance", "diagnostic_conformance"],
) -> tuple[tuple[BroaderArmRun, ...], ActualExecutorAttestation]:
    jobs = tuple(
        (world_id, seed, budget_id, budget, arm)
        for world_id, seeds in (
            (CONFORMANCE_WORLD_ID, CONFORMANCE_SEEDS),
            (CONFORMANCE_DEPTH_THREE_WORLD_ID, CONFORMANCE_DEPTH_THREE_SEEDS),
        )
        for seed in seeds
        for budget_id, budget in BUDGETS
        for arm in ARMS
    )
    runs, attestation = execute_deterministic_map(
        _execute_run_job,
        jobs,
        worker_count=1,
        executor_kind="serial",
        result_order="input_order",
        execution_authority=execution_authority,
        execution_purpose=execution_purpose,
        _orchestrator_execution_key=(
            _PRODUCTION_CONFORMANCE_EXECUTION_KEY
            if execution_purpose == "production_conformance"
            else _DIAGNOSTIC_CONFORMANCE_EXECUTION_KEY
        ),
    )
    validate_executor_attestation(
        attestation,
        results=runs,
        execution_authority=execution_authority,
        expected_purpose=execution_purpose,
        expected_validation_run_id=execution_authority.validation_run_identity,
        expected_evidence_bundle_identity=execution_authority.evidence_bundle_identity,
        require_trust_domain=(
            "production" if type(execution_authority) is OracleEvidenceBinding else "fixture"
        ),
    )
    return runs, attestation


def _execute_run_job(job: tuple[str, int, str, float, FrozenArm]) -> BroaderArmRun:
    world_id, seed, budget_id, budget, arm = job
    return run_arm(
        arm=arm,
        world=WORLDS_BY_ID[world_id].public,
        seed=seed,
        budget_id=budget_id,
        budget=budget,
        authority=ObservationAuthority(world=WORLDS_BY_ID[world_id], seed=seed),
    )


def _replay_payload(runs: Sequence[BroaderArmRun]) -> bytes:
    return canonical_json_bytes(
        [
            {
                "run_id": run.run_id,
                "selected_candidate_ids": list(run.selected_candidate_ids),
                "final_probabilities": dict(run.final_probabilities),
                "decision_cost": run.decision_cost,
                "calibration_cost": run.calibration_cost,
            }
            for run in runs
        ],
        final_lf=True,
    )


def build_conformance_payloads(
    target: Path,
    *,
    oracle_conformance_result: OracleConformanceResult,
    oracle_evidence_binding: OracleEvidenceBinding,
    fixture: ProductionConformanceFixture,
) -> tuple[
    CanonicalFinalizationPlan,
    AssemblyOperationalProvenance,
    FinalizationAuthorization,
]:
    """Return a staged plan and fresh authorization sealed to one exact target."""

    _require_oracle_evidence(
        oracle_conformance_result,
        oracle_evidence_binding,
    )
    plan, operational, certificate = _build_audited_conformance_plan(
        oracle_conformance_result=oracle_conformance_result,
        oracle_evidence_binding=oracle_evidence_binding,
        fixture=fixture,
    )
    authorization = authorize_validation_finalization(
        target,
        plan,
        operational,
        certificate,
        profile=CONFORMANCE_PROFILE,
    )
    return plan, operational, authorization


def _build_audited_conformance_plan(
    *,
    oracle_conformance_result: OracleConformanceResult,
    oracle_evidence_binding: OracleEvidenceBinding,
    fixture: ProductionConformanceFixture,
) -> tuple[
    CanonicalFinalizationPlan,
    AssemblyOperationalProvenance,
    FinalizationAuditCertificate,
]:
    """Build a fresh plan, provenance record, and exact-context audit certificate."""

    _require_oracle_evidence(
        oracle_conformance_result,
        oracle_evidence_binding,
    )
    if (
        type(fixture) is not ProductionConformanceFixture
        or _ISSUED_PRODUCTION_FIXTURES.get(id(fixture)) is not fixture
    ):
        raise ValueError("Conformance requires an exact-issued production fixture.")
    if (
        fixture.oracle_conformance_result is not oracle_conformance_result
        or fixture.oracle_evidence_binding is not oracle_evidence_binding
    ):
        raise ValueError("Conformance fixture belongs to another exact Oracle evidence bundle.")
    validate_executor_attestation(
        fixture.executor_attestation,
        results=fixture.runs,
        execution_authority=oracle_evidence_binding,
        expected_purpose="production_conformance",
        expected_validation_run_id=oracle_evidence_binding.validation_run_identity,
        expected_evidence_bundle_identity=oracle_evidence_binding.evidence_bundle_identity,
        require_trust_domain="production",
    )
    validate_executor_attestation(
        fixture.replay_executor_attestation,
        results=fixture.replay_runs,
        execution_authority=oracle_evidence_binding,
        expected_purpose="production_conformance",
        expected_validation_run_id=oracle_evidence_binding.validation_run_identity,
        expected_evidence_bundle_identity=oracle_evidence_binding.evidence_bundle_identity,
        require_trust_domain="production",
    )
    operational = _operational_provenance(
        fixture.executor_attestation,
        runs=fixture.runs,
        execution_authority=fixture.oracle_evidence_binding,
        execution_purpose="production_conformance",
    )
    prefinalization_payloads = build_prefinalization_payloads(
        fixture.runs,
        fixture.raw_analysis,
    )
    prefinalization = assemble_prefinalization_artifacts(
        prefinalization_payloads,
        operational,
        profile=CONFORMANCE_PROFILE,
    )
    analysis, audits, certificate = _execute_audited_lifecycle(
        fixture.runs,
        fixture.replay_runs,
        fixture.raw_analysis,
        prefinalization_payloads,
        prefinalization,
        fixture.executor_attestation,
        fixture.replay_executor_attestation,
        fixture.oracle_conformance_result,
        fixture.oracle_evidence_binding,
    )
    if analysis != fixture.analysis or audits != fixture.audits:
        invalidate_finalization_audit_certificate(certificate)
        raise ValueError("Repeated conformance audit lifecycle differs from the frozen fixture.")
    plan = CanonicalFinalizationPlan(
        prefinalization,
        build_post_audit_payloads(
            fixture.runs,
            analysis,
            audits,
            prefinalization_payloads,
        ),
    )
    return plan, operational, certificate


def _operational_provenance(
    executor_attestation: ActualExecutorAttestation,
    *,
    runs: Sequence[BroaderArmRun],
    execution_authority: OracleEvidenceBinding | OracleFixtureBinding,
    execution_purpose: Literal["production_conformance", "diagnostic_conformance"],
) -> AssemblyOperationalProvenance:
    return reconstruct_actual_operational_provenance(
        executor_attestation,
        consumed_results=runs,
        execution_authority=execution_authority,
        execution_purpose=execution_purpose,
    )
