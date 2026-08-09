"""Frozen 384-trajectory implementation-validation smoke study."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, suppress
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from types import FunctionType
from typing import Final, cast

from research_decision_engine.benchmarks.broader_artifacts import (
    artifact_contracts,
    build_protocol_snapshot_payload,
    build_world_definitions_payload,
)
from research_decision_engine.benchmarks.broader_assembly import finalize_validation_artifacts
from research_decision_engine.benchmarks.broader_audits import (
    PROTECTED_HASHES,
    SmokeAuditContext,
    SmokeAuditResult,
    assert_audit_executor_completeness,
    historical_hash_map,
    run_smoke_audits,
)
from research_decision_engine.benchmarks.broader_conformance import (
    CONFORMANCE_PROFILE,
    ProductionConformanceFixture,
    build_conformance_payloads,
    build_production_fixture,
)
from research_decision_engine.benchmarks.broader_execution import (
    _SMOKE_VALIDATION_EXECUTION_KEY,
    ActualExecutorAttestation,
    ExecutorProvenanceError,
    ExecutorTrustDomain,
    _require_issued_result_batch,
    execute_deterministic_map,
    validate_executor_attestation,
)
from research_decision_engine.benchmarks.broader_oracle import (
    ObservationAuthority,
    OracleConformanceResult,
    OracleError,
    OracleEvidenceBinding,
    begin_oracle_evidence_binding,
    close_oracle_evidence_binding,
    execute_oracle_conformance,
    validate_oracle_conformance_result,
)
from research_decision_engine.benchmarks.broader_pipeline import (
    validate_orchestration_contracts,
)
from research_decision_engine.benchmarks.broader_protocol import (
    ARMS,
    PROTOCOL_VERSION,
    SMOKE_SEEDS,
    SMOKE_WORLD_IDS,
    FrozenArm,
    canonical_json_bytes,
    load_protocol_snapshot,
    protocol_hash,
    repository_root,
)
from research_decision_engine.benchmarks.broader_runner import BroaderArmRun, run_arm
from research_decision_engine.benchmarks.broader_statistics import assert_executor_completeness
from research_decision_engine.benchmarks.broader_validation import (
    PytestValidationError,
    PytestValidationObservation,
    PytestValidationOwnerClaim,
    PytestValidationResult,
    bind_pytest_validation_result_to_bundle,
    claim_pytest_validation_result_owner,
    consume_pytest_validation_result,
    issued_pytest_validation_junit_bytes,
    observe_pytest_validation_result,
    release_pytest_validation_result_owner,
    validate_pytest_validation_result,
)
from research_decision_engine.benchmarks.broader_worlds import BUDGETS, WORLDS_BY_ID

SMOKE_VERSION: Final = "broader-replication-smoke/v2"
DEFAULT_OUTPUT_DIRECTORY: Final = "broader-replication-smoke-v2"


@dataclass(slots=True)
class _SmokeEvidenceOwner:
    validation_result: PytestValidationResult
    owner_claim: PytestValidationOwnerClaim
    observation: PytestValidationObservation | None = None
    evidence_bundle_identity: str | None = None
    oracle_binding: OracleEvidenceBinding | None = None
    terminal_use_claimed: bool = False


_SMOKE_EVIDENCE_OWNERS: dict[int, _SmokeEvidenceOwner] = {}
_SMOKE_EVIDENCE_OWNER_LOCK = threading.RLock()


@dataclass(frozen=True, slots=True)
class SmokePass:
    runs: tuple[BroaderArmRun, ...]
    returned_runs: tuple[BroaderArmRun, ...]
    deterministic_payload: bytes
    elapsed_seconds: float
    executor_attestation: ActualExecutorAttestation


@dataclass(frozen=True, slots=True)
class _IssuedSmokePass:
    smoke_pass: SmokePass
    runs: tuple[BroaderArmRun, ...]
    returned_runs: tuple[BroaderArmRun, ...]
    deterministic_payload: bytes
    elapsed_seconds: float
    executor_attestation: ActualExecutorAttestation
    execution_authority: object | None
    world_ids: tuple[str, ...]
    budget_ids: tuple[str, ...]


_ISSUED_SMOKE_PASSES: dict[int, _IssuedSmokePass] = {}
_SMOKE_PASS_LOCK = threading.RLock()


@dataclass(frozen=True, slots=True)
class ProductionFixtureEvidence:
    """Validation-only state from the bounded production-path conformance fixture."""

    validation_only: bool
    trajectory_count: int
    replay_trajectory_count: int
    deterministic_replay_equal: bool
    audit_statuses: tuple[tuple[str, str], ...]
    all_audits_passed: bool
    canonical_artifact_count: int
    finalization_succeeded: bool
    early_optimizer_rejection_verified: bool
    success: bool


@dataclass(frozen=True, slots=True)
class SmokeSummary:
    smoke_version: str
    protocol_version: str
    validation_only: bool
    scientific_conclusions_permitted: bool
    smoke_world_count: int
    smoke_seed_count: int
    budget_count: int
    arm_count: int
    smoke_trajectory_count: int
    replay_trajectory_count: int
    canonical_artifact_contract_count: int
    integrity_audit_count: int
    first_payload_sha256: str
    replay_payload_sha256: str
    deterministic_replay_equal: bool
    first_pass_seconds: float
    replay_seconds: float
    output_bytes: int
    test_count: int | None
    implementation_source_sha256: str
    implementation_test_sha256: str
    implementation_file_sha256: tuple[tuple[str, str], ...]
    test_file_sha256: tuple[tuple[str, str], ...]
    protected_source_sha256: tuple[tuple[str, str], ...]
    oracle_domain_count: int | None
    oracle_conformance_sha256: str | None
    oracle_conformance_run: bool
    audits: tuple[SmokeAuditResult, ...]
    all_smoke_audits_passed: bool
    deterministic_smoke_success: bool
    implementation_contracts_complete: bool
    production_fixture: ProductionFixtureEvidence
    independent_review_status: str
    canonical_full_study_audits_run: bool
    full_replication_run: bool
    full_replication_authorized: bool
    implementation_blockers: tuple[str, ...]
    operational_concerns: tuple[str, ...]
    safe_for_full_replication: bool


@dataclass(frozen=True, slots=True)
class RenderedSmokeEvidence:
    """Exact final bytes for the two files counted by ``output_bytes``."""

    summary: SmokeSummary
    markdown_bytes: bytes
    json_bytes: bytes
    junit_bytes: bytes | None = None


@dataclass(frozen=True, slots=True)
class _SmokeEvidenceContext:
    """Validated non-JSON provenance rendered into the canonical Markdown report."""

    pytest: PytestValidationObservation
    evidence_bundle_identity: str
    oracle_binding_identity: str
    oracle_execution_identity: str


@dataclass(frozen=True, slots=True)
class BoundedValidationEvidence:
    """Observed outcomes from one pytest, Oracle, smoke, replay, and fixture chain."""

    summary: SmokeSummary
    pytest: PytestValidationObservation
    oracle: OracleConformanceResult


def execute_smoke_pass(
    *,
    arm_order: Sequence[FrozenArm] = ARMS,
    worker_count: int = 1,
    execution_authority: object | None = None,
) -> SmokePass:
    return execute_validation_pass(
        world_ids=SMOKE_WORLD_IDS,
        seeds=SMOKE_SEEDS,
        budgets=BUDGETS,
        arm_order=arm_order,
        worker_count=worker_count,
        expected_count=384,
        execution_authority=execution_authority,
    )


def execute_validation_pass(
    *,
    world_ids: Sequence[str],
    seeds: Sequence[int],
    budgets: Sequence[tuple[str, float]],
    arm_order: Sequence[FrozenArm] = ARMS,
    worker_count: int = 1,
    expected_count: int | None = None,
    execution_authority: object | None = None,
) -> SmokePass:
    """Run the same production executor on an explicitly bounded validation matrix."""

    started = time.perf_counter()
    if worker_count < 1:
        raise ValueError("Smoke worker count must be positive.")
    world_id_order = tuple(world_ids)
    seed_order = tuple(seeds)
    budget_order = tuple(budgets)
    frozen_arm_order = tuple(arm_order)
    jobs: list[tuple[str, int, str, float, FrozenArm]] = []
    for world_id in world_id_order:
        for seed in seed_order:
            for budget_id, budget in budget_order:
                jobs.extend((world_id, seed, budget_id, budget, arm) for arm in frozen_arm_order)
    executed, executor_attestation = execute_deterministic_map(
        _execute_job,
        jobs,
        worker_count=worker_count,
        executor_kind="serial" if worker_count == 1 else "thread_pool",
        result_order="input_order",
        execution_authority=execution_authority,
        execution_purpose="smoke_validation",
        _orchestrator_execution_key=_SMOKE_VALIDATION_EXECUTION_KEY,
    )
    validate_executor_attestation(
        executor_attestation,
        results=executed,
        execution_authority=execution_authority,
        expected_purpose="smoke_validation",
    )
    canonical_runs = _canonical_smoke_runs(
        executed,
        world_ids=world_id_order,
        budget_ids=tuple(budget_id for budget_id, _ in budget_order),
    )
    if expected_count is not None and len(canonical_runs) != expected_count:
        raise RuntimeError(
            f"Validation pass produced {len(canonical_runs)} trajectories, not {expected_count}."
        )
    payload = canonical_json_bytes(
        [_truth_free_projection(run) for run in canonical_runs], final_lf=True
    )
    smoke_pass = SmokePass(
        runs=canonical_runs,
        returned_runs=executed,
        deterministic_payload=payload,
        elapsed_seconds=time.perf_counter() - started,
        executor_attestation=executor_attestation,
    )
    issued = _IssuedSmokePass(
        smoke_pass=smoke_pass,
        runs=canonical_runs,
        returned_runs=executed,
        deterministic_payload=payload,
        elapsed_seconds=smoke_pass.elapsed_seconds,
        executor_attestation=executor_attestation,
        execution_authority=execution_authority,
        world_ids=world_id_order,
        budget_ids=tuple(budget_id for budget_id, _ in budget_order),
    )
    with _SMOKE_PASS_LOCK:
        _ISSUED_SMOKE_PASSES[id(smoke_pass)] = issued
    return smoke_pass


def _canonical_smoke_runs(
    returned_runs: Sequence[BroaderArmRun],
    *,
    world_ids: Sequence[str],
    budget_ids: Sequence[str],
) -> tuple[BroaderArmRun, ...]:
    world_order = {world_id: index for index, world_id in enumerate(world_ids)}
    budget_order = {budget_id: index for index, budget_id in enumerate(budget_ids)}
    arm_canonical_order = {arm.arm_id: arm.arm_order for arm in ARMS}
    return tuple(
        sorted(
            returned_runs,
            key=lambda run: (
                world_order[run.world_id],
                run.seed,
                budget_order[run.budget_id],
                arm_canonical_order[run.arm.arm_id],
            ),
        )
    )


def _require_issued_smoke_pass(
    smoke_pass: SmokePass,
    *,
    execution_authority: object | None,
    expected_validation_run_id: str | None = None,
    expected_evidence_bundle_identity: str | None = None,
    require_trust_domain: ExecutorTrustDomain | None = None,
) -> _IssuedSmokePass:
    with _SMOKE_PASS_LOCK:
        issued = _ISSUED_SMOKE_PASSES.get(id(smoke_pass))
    if issued is None or smoke_pass is not issued.smoke_pass:
        raise ExecutorProvenanceError(
            "Smoke audit requires the exact SmokePass issued by validation execution.",
            error_code="SMOKE_PASS_NOT_ISSUED",
            validation_layer="smoke_pass_binding",
        )
    if (
        smoke_pass.runs is not issued.runs
        or smoke_pass.returned_runs is not issued.returned_runs
        or smoke_pass.deterministic_payload != issued.deterministic_payload
        or smoke_pass.elapsed_seconds != issued.elapsed_seconds
        or smoke_pass.executor_attestation is not issued.executor_attestation
        or execution_authority is not issued.execution_authority
    ):
        raise ExecutorProvenanceError(
            "Issued SmokePass fields differ from their execution-time values.",
            error_code="SMOKE_PASS_BINDING_MISMATCH",
            validation_layer="smoke_pass_binding",
        )
    result_record = _require_issued_result_batch(
        smoke_pass.returned_runs,
        expected_purposes=("smoke_validation",),
        require_trust_domain=require_trust_domain,
    )
    if (
        result_record.attestation is not smoke_pass.executor_attestation
        or result_record.authority is not execution_authority
    ):
        raise ExecutorProvenanceError(
            "SmokePass executor evidence is cross-bound to another result batch.",
            error_code="SMOKE_PASS_EXECUTION_MISMATCH",
            validation_layer="smoke_pass_binding",
        )
    validate_executor_attestation(
        smoke_pass.executor_attestation,
        results=smoke_pass.returned_runs,
        execution_authority=execution_authority,
        expected_purpose="smoke_validation",
        expected_validation_run_id=expected_validation_run_id,
        expected_evidence_bundle_identity=expected_evidence_bundle_identity,
        require_trust_domain=require_trust_domain,
    )
    canonical_runs = _canonical_smoke_runs(
        smoke_pass.returned_runs,
        world_ids=issued.world_ids,
        budget_ids=issued.budget_ids,
    )
    if len(canonical_runs) != len(smoke_pass.runs) or any(
        actual is not expected
        for actual, expected in zip(smoke_pass.runs, canonical_runs, strict=True)
    ):
        raise ExecutorProvenanceError(
            "SmokePass runs are not the canonical exact-object ordering of returned runs.",
            error_code="SMOKE_PASS_RUN_ORDER_MISMATCH",
            validation_layer="smoke_pass_binding",
        )
    expected_payload = canonical_json_bytes(
        [_truth_free_projection(run) for run in canonical_runs], final_lf=True
    )
    if smoke_pass.deterministic_payload != expected_payload:
        raise ExecutorProvenanceError(
            "SmokePass deterministic payload differs from its exact canonical runs.",
            error_code="SMOKE_PASS_PAYLOAD_MISMATCH",
            validation_layer="smoke_pass_binding",
        )
    return issued


def run_smoke(
    output_directory: Path,
    *,
    validation_result: PytestValidationResult,
    oracle_conformance_result: OracleConformanceResult,
    oracle_evidence_binding: OracleEvidenceBinding,
) -> SmokeSummary:
    """Authoritatively consume one pytest result and one explicit Oracle result."""

    owner: _SmokeEvidenceOwner | None = None
    pytest_consumed = False
    try:
        owner = _take_smoke_evidence_owner(validation_result, oracle_evidence_binding)
        _validated_oracle_evidence(oracle_conformance_result, oracle_evidence_binding)
        observation = validate_pytest_validation_result(
            validation_result,
            validation_run_identity=oracle_evidence_binding.validation_run_identity,
            owner_claim=owner.owner_claim,
        )
        evidence_bundle_identity = _smoke_evidence_bundle_identity(observation)
        if oracle_evidence_binding.evidence_bundle_identity != evidence_bundle_identity:
            raise RuntimeError("Oracle evidence binding differs from the pytest evidence bundle.")
        return _run_bound_smoke(
            output_directory,
            validation_result=validation_result,
            oracle_conformance_result=oracle_conformance_result,
            oracle_evidence_binding=oracle_evidence_binding,
            pytest_owner_claim=owner.owner_claim,
        )
    finally:
        try:
            if owner is not None:
                consume_pytest_validation_result(
                    validation_result,
                    validation_run_identity=oracle_evidence_binding.validation_run_identity,
                    evidence_bundle_identity=oracle_evidence_binding.evidence_bundle_identity,
                    owner_claim=owner.owner_claim,
                )
                pytest_consumed = True
        finally:
            try:
                if owner is not None:
                    with suppress(OracleError):
                        close_oracle_evidence_binding(oracle_evidence_binding)
            finally:
                if owner is not None and pytest_consumed:
                    _release_smoke_evidence_owner(owner)


def _run_bound_smoke(
    output_directory: Path,
    *,
    validation_result: PytestValidationResult,
    oracle_conformance_result: OracleConformanceResult,
    oracle_evidence_binding: OracleEvidenceBinding,
    pytest_owner_claim: PytestValidationOwnerClaim,
) -> SmokeSummary:
    if output_directory.exists():
        raise FileExistsError(
            f"Smoke output directory already exists and will not be overwritten: {output_directory}"
        )
    snapshot = load_protocol_snapshot()
    implementation_files, implementation_digest = _implementation_hashes()
    test_files, test_digest = _test_hashes()
    pytest_observation = validate_pytest_validation_result(
        validation_result,
        validation_run_identity=oracle_evidence_binding.validation_run_identity,
        owner_claim=pytest_owner_claim,
    )
    expected_bundle_identity = _smoke_evidence_bundle_identity(pytest_observation)
    if oracle_evidence_binding.evidence_bundle_identity != expected_bundle_identity:
        raise RuntimeError("Oracle evidence binding differs from the pytest evidence bundle.")
    oracle_domain_count, oracle_conformance_sha256 = _validated_oracle_evidence(
        oracle_conformance_result,
        oracle_evidence_binding,
    )
    junit_bytes = issued_pytest_validation_junit_bytes(
        validation_result,
        evidence_bundle_identity=expected_bundle_identity,
        owner_claim=pytest_owner_claim,
    )
    if (
        pytest_observation.junit_xml_sha256 is None
        or len(junit_bytes) != pytest_observation.junit_xml_byte_count
        or hashlib.sha256(junit_bytes).hexdigest() != pytest_observation.junit_xml_sha256
    ):
        raise RuntimeError("Registry-owned JUnit bytes differ from the pytest observation.")
    protected_files = _protected_hashes()
    historical_before = historical_hash_map()
    first = execute_smoke_pass(execution_authority=oracle_evidence_binding)
    replay = execute_smoke_pass(
        arm_order=tuple(reversed(ARMS)),
        worker_count=2,
        execution_authority=oracle_evidence_binding,
    )
    historical_after = historical_hash_map()
    audits = run_smoke_audits(
        _smoke_audit_context(
            first,
            replay,
            historical_before=historical_before,
            historical_after=historical_after,
            oracle_result=oracle_conformance_result,
            oracle_binding=oracle_evidence_binding,
        )
    )
    contracts = artifact_contracts(snapshot)
    assert_executor_completeness()
    assert_audit_executor_completeness()
    protocol_payload = build_protocol_snapshot_payload(snapshot)
    world_payload = build_world_definitions_payload()
    artifact_registry = protocol_payload["artifact_registry"]
    world_registry = world_payload["worlds"]
    if not isinstance(artifact_registry, list) or len(artifact_registry) != 13:
        raise RuntimeError("Protocol snapshot does not contain 13 artifact contracts.")
    if not isinstance(world_registry, list) or len(world_registry) != 24:
        raise RuntimeError("World artifact projection does not contain 24 worlds.")
    production_fixture = build_production_fixture(
        oracle_conformance_result=oracle_conformance_result,
        oracle_evidence_binding=oracle_evidence_binding,
    )
    with tempfile.TemporaryDirectory(prefix="rde-conformance-") as temporary:
        conformance_target = Path(temporary) / "canonical"
        conformance_plan, conformance_operational, conformance_authorization = (
            build_conformance_payloads(
                conformance_target,
                oracle_conformance_result=oracle_conformance_result,
                oracle_evidence_binding=oracle_evidence_binding,
                fixture=production_fixture,
            )
        )
        conformance_artifacts = finalize_validation_artifacts(
            conformance_target,
            conformance_plan,
            conformance_operational,
            conformance_authorization,
            profile=CONFORMANCE_PROFILE,
        )
    fixture_evidence = _production_fixture_evidence(
        production_fixture,
        canonical_artifact_count=len(conformance_artifacts),
        expected_artifact_count=len(contracts),
        oracle_result=oracle_conformance_result,
        oracle_binding=oracle_evidence_binding,
    )
    validate_orchestration_contracts()
    all_passed = all(item.status == "PASS" for item in audits)
    no_failures = all(item.status != "FAIL" for item in audits)
    first_digest = hashlib.sha256(first.deterministic_payload).hexdigest()
    replay_digest = hashlib.sha256(replay.deterministic_payload).hexdigest()
    deterministic = first.deterministic_payload == replay.deterministic_payload
    deterministic_success = deterministic and no_failures
    implementation_complete = len(contracts) == len(conformance_artifacts) == 13
    blockers = tuple(
        item
        for item, present in (
            ("One or more smoke invariants failed.", not no_failures),
            ("Deterministic replay failed.", not deterministic),
            ("The populated 13-artifact conformance graph failed.", not implementation_complete),
            ("The bounded production conformance fixture failed.", not fixture_evidence.success),
        )
        if present
    )
    summary = SmokeSummary(
        smoke_version=SMOKE_VERSION,
        protocol_version=PROTOCOL_VERSION,
        validation_only=True,
        scientific_conclusions_permitted=False,
        smoke_world_count=8,
        smoke_seed_count=4,
        budget_count=3,
        arm_count=4,
        smoke_trajectory_count=len(first.runs),
        replay_trajectory_count=len(replay.runs),
        canonical_artifact_contract_count=len(contracts),
        integrity_audit_count=len(audits),
        first_payload_sha256=first_digest,
        replay_payload_sha256=replay_digest,
        deterministic_replay_equal=deterministic,
        first_pass_seconds=first.elapsed_seconds,
        replay_seconds=replay.elapsed_seconds,
        output_bytes=0,
        test_count=pytest_observation.total,
        implementation_source_sha256=implementation_digest,
        implementation_test_sha256=test_digest,
        implementation_file_sha256=implementation_files,
        test_file_sha256=test_files,
        protected_source_sha256=protected_files,
        oracle_domain_count=oracle_domain_count,
        oracle_conformance_sha256=oracle_conformance_sha256,
        oracle_conformance_run=True,
        audits=audits,
        all_smoke_audits_passed=all_passed,
        deterministic_smoke_success=deterministic_success,
        implementation_contracts_complete=implementation_complete,
        production_fixture=fixture_evidence,
        independent_review_status="pending",
        canonical_full_study_audits_run=False,
        full_replication_run=False,
        full_replication_authorized=False,
        implementation_blockers=blockers,
        operational_concerns=(
            "The 36,864-trajectory study and 1,300,000 resampling rows remain "
            "intentionally unexecuted.",
            "A12, A13, A15, and A16 remain INCONCLUSIVE without populated canonical "
            "full-study artifacts.",
            "The separate 117,952-key Oracle conformance result is recorded alongside "
            "smoke but is not inferred from smoke trajectories.",
            "Runtime and storage for the full replication remain estimates until an "
            "independent run.",
        ),
        safe_for_full_replication=False,
    )
    _assert_oracle_binding_matches_summary(oracle_evidence_binding, summary)
    _validated_oracle_evidence(oracle_conformance_result, oracle_evidence_binding)
    evidence = _seal_bound_smoke_evidence(
        summary,
        validation_result=validation_result,
        oracle_conformance_result=oracle_conformance_result,
        oracle_evidence_binding=oracle_evidence_binding,
        pytest_owner_claim=pytest_owner_claim,
    )
    summary = evidence.summary
    output_directory.mkdir(parents=True)
    json_path = output_directory / "smoke_validation.json"
    report_path = output_directory / "SMOKE_VALIDATION_REPORT.md"
    junit_path = output_directory / "pytest-junit.xml"
    json_path.write_bytes(evidence.json_bytes)
    report_path.write_bytes(evidence.markdown_bytes)
    junit_path.write_bytes(junit_bytes)
    _verify_persisted_smoke_evidence(output_directory, evidence)
    validate_pytest_validation_result(
        validation_result,
        validation_run_identity=oracle_evidence_binding.validation_run_identity,
        owner_claim=pytest_owner_claim,
    )
    _assert_oracle_binding_matches_summary(oracle_evidence_binding, summary)
    _validated_oracle_evidence(oracle_conformance_result, oracle_evidence_binding)
    return summary


def _smoke_audit_context(
    first: SmokePass,
    replay: SmokePass,
    *,
    historical_before: tuple[tuple[str, str], ...],
    historical_after: tuple[tuple[str, str], ...],
    oracle_result: OracleConformanceResult,
    oracle_binding: OracleEvidenceBinding,
) -> SmokeAuditContext:
    """Bind a separately executed Oracle audit into the smoke audit evidence."""

    _validated_oracle_evidence(oracle_result, oracle_binding)
    for item in (first, replay):
        _require_issued_smoke_pass(
            item,
            execution_authority=oracle_binding,
            expected_validation_run_id=oracle_binding.validation_run_identity,
            expected_evidence_bundle_identity=oracle_binding.evidence_bundle_identity,
            require_trust_domain="production",
        )
    return SmokeAuditContext(
        runs=first.runs,
        replay_runs=replay.runs,
        first_payload=first.deterministic_payload,
        replay_payload=replay.deterministic_payload,
        historical_before=historical_before,
        historical_after=historical_after,
        oracle_conformance_result=oracle_result,
        oracle_evidence_binding=oracle_binding,
        executor_attestation=first.executor_attestation,
        replay_executor_attestation=replay.executor_attestation,
        executor_results=first.returned_runs,
        replay_executor_results=replay.returned_runs,
        execution_authority=oracle_binding,
        execution_purpose="smoke_validation",
    )


def _production_fixture_evidence(
    fixture: ProductionConformanceFixture,
    *,
    canonical_artifact_count: int,
    expected_artifact_count: int,
    oracle_result: OracleConformanceResult,
    oracle_binding: OracleEvidenceBinding,
) -> ProductionFixtureEvidence:
    """Summarize bounded implementation checks without exposing scientific results."""

    validate_executor_attestation(
        fixture.executor_attestation,
        results=fixture.runs,
        execution_authority=fixture.oracle_evidence_binding,
        expected_purpose="production_conformance",
        expected_validation_run_id=oracle_binding.validation_run_identity,
        expected_evidence_bundle_identity=oracle_binding.evidence_bundle_identity,
        require_trust_domain="production",
    )
    validate_executor_attestation(
        fixture.replay_executor_attestation,
        results=fixture.replay_runs,
        execution_authority=fixture.oracle_evidence_binding,
        expected_purpose="production_conformance",
        expected_validation_run_id=oracle_binding.validation_run_identity,
        expected_evidence_bundle_identity=oracle_binding.evidence_bundle_identity,
        require_trust_domain="production",
    )
    first_payload = canonical_json_bytes(
        [_truth_free_projection(run) for run in fixture.runs], final_lf=True
    )
    replay_payload = canonical_json_bytes(
        [_truth_free_projection(run) for run in fixture.replay_runs], final_lf=True
    )
    replay_equal = first_payload == replay_payload
    _validated_oracle_evidence(oracle_result, oracle_binding)
    audit_statuses = tuple((item.audit_id, item.status) for item in fixture.audits)
    expected_audit_statuses = tuple(
        (audit_id, "PASS")
        for audit_id in load_protocol_snapshot().registry("audit").ids("audit_id")
    )
    all_audits_passed = audit_statuses == expected_audit_statuses
    finalization_succeeded = canonical_artifact_count == expected_artifact_count == 13
    counts_exact = (
        len(fixture.runs) == len(fixture.replay_runs) == CONFORMANCE_PROFILE.arm_runs == 252
    )
    success = (
        counts_exact
        and replay_equal
        and all_audits_passed
        and finalization_succeeded
        and fixture.early_optimizer_rejection_verified
    )
    return ProductionFixtureEvidence(
        validation_only=True,
        trajectory_count=len(fixture.runs),
        replay_trajectory_count=len(fixture.replay_runs),
        deterministic_replay_equal=replay_equal,
        audit_statuses=audit_statuses,
        all_audits_passed=all_audits_passed,
        canonical_artifact_count=canonical_artifact_count,
        finalization_succeeded=finalization_succeeded,
        early_optimizer_rejection_verified=fixture.early_optimizer_rejection_verified,
        success=success,
    )


def _truth_free_projection(run: BroaderArmRun) -> dict[str, object]:
    return {
        "run_id": run.run_id,
        "comparison_id": run.comparison_id,
        "arm_id": run.arm.arm_id,
        "world_id": run.world_id,
        "seed": run.seed,
        "budget_id": run.budget_id,
        "budget": run.budget,
        "lineage_id": run.lineage.lineage_id,
        "initial_probabilities": dict(run.initial_probabilities),
        "final_probabilities": dict(run.final_probabilities),
        "selected_candidate_ids": list(run.selected_candidate_ids),
        "decision_cost": run.decision_cost,
        "calibration_cost": run.calibration_cost,
        "terminal_reason": run.terminal_reason,
        "decisions": [
            {
                "decision_id": decision.decision_id,
                "belief_state_id": decision.belief_state_id,
                "selected_candidate_id": decision.selected_candidate_id,
                "public_feasible_candidate_ids": list(decision.public_feasible_candidate_ids),
                "affordable_candidate_ids": list(decision.affordable_candidate_ids),
                "policy_trace": decision.policy_trace.to_dict(),
            }
            for decision in run.decisions
        ],
        "actions": [
            {
                "step": action.step,
                "candidate_id": action.candidate_id,
                "role": action.role,
                "cost": action.cost,
                "cumulative_decision_cost": action.cumulative_decision_cost,
                "oracle_digest": (
                    action.oracle_observation.digest
                    if action.oracle_observation is not None
                    else None
                ),
                "new_evidence_ids": list(action.new_evidence_ids),
                "posterior_probabilities": dict(action.posterior_probabilities),
            }
            for action in run.actions
        ],
    }


def _implementation_hashes() -> tuple[tuple[tuple[str, str], ...], str]:
    root = repository_root()
    paths = tuple(sorted((root / "research_decision_engine" / "benchmarks").glob("broader_*.py")))
    return _file_hashes(paths, domain="broader_smoke_implementation/v1")


def begin_smoke_evidence_binding(
    validation_result: PytestValidationResult,
) -> OracleEvidenceBinding:
    """Bind one completed production pytest run to one future smoke evidence bundle."""

    owner = _claim_smoke_evidence_owner(validation_result)
    pytest_bound = False
    binding: OracleEvidenceBinding | None = None
    try:
        observation = observe_pytest_validation_result(
            validation_result,
            owner_claim=owner.owner_claim,
        )
        validate_pytest_validation_result(
            validation_result,
            validation_run_identity=observation.validation_run_identity,
            owner_claim=owner.owner_claim,
        )
        evidence_bundle_identity = _smoke_evidence_bundle_identity(observation)
        bind_pytest_validation_result_to_bundle(
            validation_result,
            validation_run_identity=observation.validation_run_identity,
            evidence_bundle_identity=evidence_bundle_identity,
            owner_claim=owner.owner_claim,
        )
        pytest_bound = True
        binding = begin_oracle_evidence_binding(
            validation_run_identity=observation.validation_run_identity,
            evidence_bundle_identity=evidence_bundle_identity,
        )
        _bind_smoke_evidence_owner(
            owner,
            observation=observation,
            evidence_bundle_identity=evidence_bundle_identity,
            oracle_binding=binding,
        )
        if (
            binding.implementation_commit != observation.implementation_commit
            or binding.implementation_source_sha256 != _implementation_hashes()[1]
            or binding.implementation_test_sha256 != _test_hashes()[1]
        ):
            raise RuntimeError("Oracle evidence binding differs from the pytest source identities.")
        return binding
    except Exception:
        pytest_consumed = not pytest_bound
        try:
            if pytest_bound:
                consume_pytest_validation_result(
                    validation_result,
                    validation_run_identity=observation.validation_run_identity,
                    evidence_bundle_identity=evidence_bundle_identity,
                    owner_claim=owner.owner_claim,
                )
                pytest_consumed = True
        finally:
            try:
                if binding is not None:
                    close_oracle_evidence_binding(binding)
            finally:
                if pytest_consumed:
                    _release_smoke_evidence_owner(owner, release_validation_claim=not pytest_bound)
        raise


def _build_bounded_validation_evidence_entrypoint() -> Callable[..., BoundedValidationEvidence]:
    """Seal Stage-1 preparation into the sole production evidence entry point."""

    stage1_gate: Callable[[], AbstractContextManager[None]] | None = None
    trusted_stage1_gate: Callable[[], AbstractContextManager[None]] | None = None
    function_type = FunctionType

    def execute_bounded_validation_evidence(
        output_directory: Path,
        *,
        validation_result: PytestValidationResult,
        oracle_conformance_result: OracleConformanceResult,
        oracle_evidence_binding: OracleEvidenceBinding,
    ) -> BoundedValidationEvidence:
        """Prepare exact P2 authority without crossing the Stage-2 execution boundary."""

        gate = stage1_gate
        if gate is None or gate is not trusted_stage1_gate or gate.__class__ is not function_type:
            from research_decision_engine.benchmarks.broader_validation_evidence import (
                P2Stage1Error,
            )

            raise P2Stage1Error(
                "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                "The exact P2 Stage-1 production gate is not installed.",
                layer="live_executor_implementation_issuance",
            )
        trusted_gate = gate
        expected_gate_qualname = (
            "_make_production_registry.<locals>.install_entrypoint.<locals>.gate"
        )
        if (
            trusted_gate.__module__
            != "research_decision_engine.benchmarks.broader_validation_evidence"
            or trusted_gate.__qualname__ != expected_gate_qualname
            or trusted_gate.__code__.co_name != "gate"
            or trusted_gate.__code__.co_qualname != expected_gate_qualname
        ):
            from research_decision_engine.benchmarks.broader_validation_evidence import (
                P2Stage1Error,
            )

            raise P2Stage1Error(
                "CALLABLE_IDENTITY_MISMATCH",
                "The exact P2 Stage-1 production gate was replaced.",
                layer="live_executor_implementation_issuance",
            )
        from research_decision_engine.benchmarks.broader_validation_evidence import (
            P2Stage1Error,
        )

        with trusted_gate():
            pass
        raise P2Stage1Error(
            "P2_STAGE2_NOT_AUTHORIZED",
            "Stage 1 prepared one complete authority; Stage 2 execution remains unauthorized.",
            layer="stage_boundary",
        )

    execute_bounded_validation_evidence.__name__ = "execute_bounded_validation_evidence"
    execute_bounded_validation_evidence.__qualname__ = "execute_bounded_validation_evidence"
    from research_decision_engine.benchmarks import broader_validation_evidence

    installed_gate, public_entrypoint = broader_validation_evidence._install_production_entrypoint(
        execute_bounded_validation_evidence
    )
    stage1_gate = cast(Callable[[], AbstractContextManager[None]], installed_gate)
    trusted_stage1_gate = stage1_gate
    return cast(Callable[..., BoundedValidationEvidence], public_entrypoint)


def _claim_smoke_evidence_owner(
    validation_result: PytestValidationResult,
) -> _SmokeEvidenceOwner:
    """Atomically reserve one pytest capability for one smoke binding owner."""

    owner_claim = claim_pytest_validation_result_owner(validation_result)
    owner = _SmokeEvidenceOwner(
        validation_result=validation_result,
        owner_claim=owner_claim,
    )
    try:
        with _SMOKE_EVIDENCE_OWNER_LOCK:
            existing = _SMOKE_EVIDENCE_OWNERS.get(id(validation_result))
            if existing is not None:
                raise PytestValidationError(
                    "Pytest validation result already has an active smoke evidence owner."
                )
            _SMOKE_EVIDENCE_OWNERS[id(validation_result)] = owner
    except Exception:
        release_pytest_validation_result_owner(
            validation_result,
            owner_claim=owner_claim,
        )
        raise
    return owner


def _bind_smoke_evidence_owner(
    owner: _SmokeEvidenceOwner,
    *,
    observation: PytestValidationObservation,
    evidence_bundle_identity: str,
    oracle_binding: OracleEvidenceBinding,
) -> None:
    with _SMOKE_EVIDENCE_OWNER_LOCK:
        current = _SMOKE_EVIDENCE_OWNERS.get(id(owner.validation_result))
        if current is not owner or owner.oracle_binding is not None:
            raise PytestValidationError("Smoke evidence ownership claim is forged or stale.")
        owner.observation = observation
        owner.evidence_bundle_identity = evidence_bundle_identity
        owner.oracle_binding = oracle_binding


def _smoke_evidence_owner(
    validation_result: PytestValidationResult,
    oracle_binding: OracleEvidenceBinding,
) -> _SmokeEvidenceOwner:
    with _SMOKE_EVIDENCE_OWNER_LOCK:
        owner = _SMOKE_EVIDENCE_OWNERS.get(id(validation_result))
        if (
            owner is None
            or owner.validation_result is not validation_result
            or owner.oracle_binding is not oracle_binding
            or owner.observation is None
            or owner.evidence_bundle_identity != oracle_binding.evidence_bundle_identity
        ):
            raise PytestValidationError(
                "Smoke evidence requires its exact active pytest/Oracle ownership claim."
            )
        return owner


def _smoke_evidence_owner_observation(
    validation_result: PytestValidationResult,
    oracle_binding: OracleEvidenceBinding,
) -> PytestValidationObservation:
    owner = _smoke_evidence_owner(validation_result, oracle_binding)
    if owner.observation is None:  # pragma: no cover - narrowed under the owner lock
        raise PytestValidationError("Smoke evidence ownership claim lacks pytest observation.")
    return owner.observation


def _take_smoke_evidence_owner(
    validation_result: PytestValidationResult,
    oracle_binding: OracleEvidenceBinding,
) -> _SmokeEvidenceOwner:
    with _SMOKE_EVIDENCE_OWNER_LOCK:
        owner = _smoke_evidence_owner(validation_result, oracle_binding)
        if owner.terminal_use_claimed:
            raise PytestValidationError("Smoke evidence ownership claim is already in use.")
        owner.terminal_use_claimed = True
        return owner


def _release_smoke_evidence_owner(
    owner: _SmokeEvidenceOwner,
    *,
    release_validation_claim: bool = False,
) -> None:
    if release_validation_claim:
        release_pytest_validation_result_owner(
            owner.validation_result,
            owner_claim=owner.owner_claim,
        )
    with _SMOKE_EVIDENCE_OWNER_LOCK:
        current = _SMOKE_EVIDENCE_OWNERS.get(id(owner.validation_result))
        if current is owner:
            del _SMOKE_EVIDENCE_OWNERS[id(owner.validation_result)]


def _smoke_evidence_bundle_identity(observation: PytestValidationObservation) -> str:
    _, implementation_source_sha256 = _implementation_hashes()
    _, implementation_test_sha256 = _test_hashes()
    return protocol_hash(
        "smoke_evidence_bundle/v2",
        {
            "complete_test_bundle_sha256": observation.complete_test_bundle_sha256,
            "implementation_commit": observation.implementation_commit,
            "implementation_diff_sha256": observation.implementation_diff_sha256,
            "implementation_source_sha256": implementation_source_sha256,
            "implementation_test_sha256": implementation_test_sha256,
            "implementation_tree_sha256": observation.implementation_tree_sha256,
            "junit_xml_byte_count": observation.junit_xml_byte_count,
            "junit_xml_sha256": observation.junit_xml_sha256,
            "output_filenames": [
                "SMOKE_VALIDATION_REPORT.md",
                "pytest-junit.xml",
                "smoke_validation.json",
            ],
            "pytest_command_sha256": observation.command_sha256,
            "pytest_result_identity": observation.result_identity,
            "smoke_version": SMOKE_VERSION,
            "validation_run_identity": observation.validation_run_identity,
        },
    )


def _validated_oracle_evidence(
    result: OracleConformanceResult,
    binding: OracleEvidenceBinding,
) -> tuple[int, str]:
    validated = validate_oracle_conformance_result(result, binding=binding)
    return validated.actual_unique_key_count, validated.actual_sha256


def _assert_oracle_binding_matches_summary(
    binding: OracleEvidenceBinding,
    summary: SmokeSummary,
) -> None:
    _, implementation_source_sha256 = _implementation_hashes()
    _, implementation_test_sha256 = _test_hashes()
    expected = (
        summary.implementation_source_sha256,
        summary.implementation_test_sha256,
    )
    if (
        binding.implementation_source_sha256,
        binding.implementation_test_sha256,
    ) != expected or (implementation_source_sha256, implementation_test_sha256) != expected:
        raise RuntimeError(
            "Smoke implementation/test identities changed during the validation run."
        )


def _seal_bound_smoke_evidence(
    summary: SmokeSummary,
    *,
    validation_result: PytestValidationResult,
    oracle_conformance_result: OracleConformanceResult,
    oracle_evidence_binding: OracleEvidenceBinding,
    pytest_owner_claim: PytestValidationOwnerClaim,
) -> RenderedSmokeEvidence:
    """Seal authoritative bytes only from exact current pytest and Oracle capabilities."""

    pytest_observation = validate_pytest_validation_result(
        validation_result,
        validation_run_identity=oracle_evidence_binding.validation_run_identity,
        owner_claim=pytest_owner_claim,
    )
    evidence_bundle_identity = _smoke_evidence_bundle_identity(pytest_observation)
    if oracle_evidence_binding.evidence_bundle_identity != evidence_bundle_identity:
        raise RuntimeError("Oracle and pytest evidence bundles differ at the rendering boundary.")
    _assert_oracle_binding_matches_summary(oracle_evidence_binding, summary)
    _validated_oracle_evidence(oracle_conformance_result, oracle_evidence_binding)
    junit_bytes = issued_pytest_validation_junit_bytes(
        validation_result,
        evidence_bundle_identity=evidence_bundle_identity,
        owner_claim=pytest_owner_claim,
    )
    if (
        pytest_observation.junit_xml_sha256 is None
        or len(junit_bytes) != pytest_observation.junit_xml_byte_count
        or hashlib.sha256(junit_bytes).hexdigest() != pytest_observation.junit_xml_sha256
    ):
        raise RuntimeError("Registry-owned JUnit bytes differ at the rendering boundary.")
    return _render_smoke_evidence(
        summary,
        context=_SmokeEvidenceContext(
            pytest=pytest_observation,
            evidence_bundle_identity=evidence_bundle_identity,
            oracle_binding_identity=oracle_evidence_binding.binding_identity,
            oracle_execution_identity=oracle_conformance_result.execution_identity,
        ),
        junit_bytes=junit_bytes,
    )


def _test_hashes() -> tuple[tuple[tuple[str, str], ...], str]:
    root = repository_root()
    paths = tuple(sorted((root / "tests").glob("test_broader*.py")))
    return _file_hashes(paths, domain="broader_smoke_tests/v1")


def _protected_hashes() -> tuple[tuple[str, str], ...]:
    root = repository_root()
    records = tuple(
        (relative, hashlib.sha256((root / relative).read_bytes()).hexdigest())
        for relative in sorted(PROTECTED_HASHES)
    )
    mismatches = tuple(
        relative for relative, digest in records if digest != PROTECTED_HASHES[relative]
    )
    if mismatches:
        raise RuntimeError(f"Protected smoke source hashes differ: {mismatches}")
    return records


def _file_hashes(paths: Sequence[Path], *, domain: str) -> tuple[tuple[tuple[str, str], ...], str]:
    root = repository_root()
    records = tuple(
        (path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest())
        for path in paths
    )
    digest = protocol_hash(
        domain,
        {"files": [{"path": path, "sha256": sha256} for path, sha256 in records]},
    )
    return records, digest


def _execute_job(job: tuple[str, int, str, float, FrozenArm]) -> BroaderArmRun:
    world_id, seed, budget_id, budget, arm = job
    world = WORLDS_BY_ID[world_id]
    return run_arm(
        arm=arm,
        world=world.public,
        seed=seed,
        budget_id=budget_id,
        budget=budget,
        authority=ObservationAuthority(world=world, seed=seed),
    )


def _summary_dict(summary: SmokeSummary) -> dict[str, object]:
    data = asdict(summary)
    data["audits"] = [asdict(item) for item in summary.audits]
    return data


def _markdown_report(
    summary: SmokeSummary,
    *,
    context: _SmokeEvidenceContext | None = None,
    json_sha256: str | None = None,
) -> str:
    audit_rows = "\n".join(
        f"| {item.audit_id} | {item.status} | {item.observed} |" for item in summary.audits
    )
    blockers = (
        "None."
        if not summary.implementation_blockers
        else "\n".join(f"- {item}" for item in summary.implementation_blockers)
    )
    concerns = "\n".join(f"- {item}" for item in summary.operational_concerns)
    fixture = summary.production_fixture
    fixture_audit_states = ", ".join(
        f"{audit_id}={status}" for audit_id, status in fixture.audit_statuses
    )
    oracle_result_consumed = str(summary.oracle_conformance_run).lower()
    pytest_evidence = ""
    if context is not None:
        if json_sha256 is None:
            raise RuntimeError("Bound smoke Markdown requires the final JSON SHA-256.")
        observation = context.pytest
        skipped_rows = (
            "None."
            if not observation.skipped_node_ids
            else "\n".join(
                "- "
                + canonical_json_bytes((node_id, reason), final_lf=False).decode("utf-8").strip()
                for node_id, reason in zip(
                    observation.skipped_node_ids,
                    observation.skipped_reasons,
                    strict=True,
                )
            )
        )
        command_json = canonical_json_bytes(list(observation.command), final_lf=False).decode(
            "utf-8"
        )
        pytest_evidence = f"""
## Complete Pytest Evidence

- Validation run identity: `{observation.validation_run_identity}`
- Evidence bundle identity: `{context.evidence_bundle_identity}`
- Implementation commit: `{observation.implementation_commit}`
- Implementation tree SHA-256: `{observation.implementation_tree_sha256}`
- Implementation diff SHA-256: `{observation.implementation_diff_sha256}`
- Broader source SHA-256: `{observation.broader_source_sha256}`
- Complete test bundle SHA-256: `{observation.complete_test_bundle_sha256}`
- Pytest command: `{command_json}`
- Pytest command SHA-256: `{observation.command_sha256}`
- Dependency-lock SHA-256: `{observation.uv_lock_sha256}`
- Interpreter identity SHA-256: `{observation.interpreter_identity_sha256}`
- Platform identity SHA-256: `{observation.platform_identity_sha256}`
- Process start identity: `{observation.subprocess_start_identity}`
- Process completion identity: `{observation.subprocess_completion_identity}`
- Pytest result identity: `{observation.result_identity}`
- Execution status: {observation.execution_status}
- Execution completed: {str(observation.completed).lower()}
- Tests: {observation.total}
- Passed: {observation.passed}
- Skipped: {observation.skipped}
- Failed: {observation.failed}
- Errors: {observation.errors}
- Native JUnit runtime: {observation.runtime_seconds} seconds
- Native JUnit XML bytes: {observation.junit_xml_byte_count}
- Native JUnit XML SHA-256: `{observation.junit_xml_sha256}`
- Smoke validation JSON SHA-256: `{json_sha256}`
- Oracle binding identity: `{context.oracle_binding_identity}`
- Oracle execution identity: `{context.oracle_execution_identity}`

Exact skipped-test node IDs and reasons parsed from the actual pytest execution:

{skipped_rows}

The exact-issued pytest result, native JUnit bytes, Oracle result, Markdown report, and
smoke JSON are bound to the validation-run and evidence-bundle identities above. JUnit is
side evidence and is intentionally excluded from `output_bytes`.
"""
    return f"""# Broader Replication Smoke Validation

This is implementation validation only. It contains no confirmatory analysis, promotion
decision, controller-modification decision, or scientific conclusion.

## Implementation Coverage

- Frozen worlds implemented: 24
- Smoke worlds exercised: {summary.smoke_world_count}
- Frozen arms exercised: {summary.arm_count}
- Budgets exercised: {summary.budget_count}
- Canonical artifact contracts implemented and validated:
  {summary.canonical_artifact_contract_count}
- Frozen integrity-audit implementations exercised: {summary.integrity_audit_count}

## Exact Smoke Counts

- Primary smoke trajectories: {summary.smoke_trajectory_count}
- Independent replay trajectories: {summary.replay_trajectory_count}
- Smoke seeds: {summary.smoke_seed_count}
- Full-study trajectories: not run

## Runtime And Storage

- First pass: {summary.first_pass_seconds:.6f} seconds
- Replay: {summary.replay_seconds:.6f} seconds
- Output storage: {summary.output_bytes} bytes
- Complete pytest count: {summary.test_count}

{pytest_evidence}

## Current Implementation Hashes

- Broader implementation bundle SHA-256: `{summary.implementation_source_sha256}`
- Broader test bundle SHA-256: `{summary.implementation_test_sha256}`
- Protected source files verified: {len(summary.protected_source_sha256)}

## Artifact Validation

The implementation exposes 13 executable artifact contracts. Smoke data are not canonical
scientific artifacts, so full-population count, relationship, resampling, and finalization
audits remain INCONCLUSIVE here rather than being inferred from the smoke matrix.

## Audit Results

| Audit | Smoke validation | Observation |
| --- | --- | --- |
{audit_rows}

These are smoke-scoped implementation checks. INCONCLUSIVE means the defining full
population was not supplied; it is never converted to PASS or FAIL.

## Deterministic Replay

- Equal: {str(summary.deterministic_replay_equal).lower()}
- First payload SHA-256: `{summary.first_payload_sha256}`
- Replay payload SHA-256: `{summary.replay_payload_sha256}`
- Separately executed Oracle conformance result consumed by smoke: {oracle_result_consumed}
- Oracle conformance keys: {summary.oracle_domain_count}
- Oracle conformance SHA-256: `{summary.oracle_conformance_sha256}`

## Production Conformance Fixture

This bounded fixture exercises the production artifact path for implementation validation
only. Its record contains no comparative metric, gate interpretation, recommendation, or
scientific conclusion.

- Primary trajectories: {fixture.trajectory_count}
- Replay trajectories: {fixture.replay_trajectory_count}
- Deterministic replay equal: {str(fixture.deterministic_replay_equal).lower()}
- Audit states: {fixture_audit_states}
- All 16 fixture audits passed: {str(fixture.all_audits_passed).lower()}
- Canonical artifacts finalized: {fixture.canonical_artifact_count}
- Finalization succeeded: {str(fixture.finalization_succeeded).lower()}
- Depth-three early-action rejection verified:
  {str(fixture.early_optimizer_rejection_verified).lower()}
- Overall production fixture success: {str(fixture.success).lower()}

## Readiness Separation

- Deterministic smoke success: **{str(summary.deterministic_smoke_success)}**
- Executable contract registry complete: **{str(summary.implementation_contracts_complete)}**
- Independent review status: **{summary.independent_review_status}**
- Full replication authorized: **{str(summary.full_replication_authorized)}**

## Implementation Blockers

{blockers}

## Operational Concerns

{concerns}

## Full Replication Readiness

Safe to begin the full replication: **{str(summary.safe_for_full_replication)}**.
Smoke success alone never authorizes the full study.
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Broader-replication validation tools")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("oracle-audit", help="run the frozen 117,952-key audit")
    smoke = subcommands.add_parser("smoke", help="run the exact 384-trajectory smoke twice")
    smoke.add_argument(
        "--output-directory",
        type=Path,
        default=Path(DEFAULT_OUTPUT_DIRECTORY),
    )
    return parser


def _render_smoke_evidence(
    summary: SmokeSummary,
    *,
    context: _SmokeEvidenceContext | None = None,
    junit_bytes: bytes | None = None,
) -> RenderedSmokeEvidence:
    """Pure byte renderer; only ``_seal_bound_smoke_evidence`` is authoritative."""

    if (context is None) != (junit_bytes is None):
        raise RuntimeError("Bound smoke rendering requires both pytest context and JUnit bytes.")
    current = replace(summary, output_bytes=0)
    for _ in range(10):
        json_bytes = canonical_json_bytes(_summary_dict(current), final_lf=True)
        report_bytes = _markdown_report(
            current,
            context=context,
            json_sha256=hashlib.sha256(json_bytes).hexdigest() if context is not None else None,
        ).encode("utf-8")
        observed = len(json_bytes) + len(report_bytes)
        if observed == current.output_bytes:
            return RenderedSmokeEvidence(
                summary=current,
                markdown_bytes=report_bytes,
                json_bytes=json_bytes,
                junit_bytes=junit_bytes,
            )
        current = replace(current, output_bytes=observed)
    raise RuntimeError("Smoke output byte count did not reach a fixed point.")


def _verify_persisted_smoke_evidence(
    output_directory: Path,
    evidence: RenderedSmokeEvidence | None = None,
) -> int:
    """Reopen the two counted files and reject stale or noncanonical byte evidence."""

    json_path = output_directory / "smoke_validation.json"
    report_path = output_directory / "SMOKE_VALIDATION_REPORT.md"
    junit_path = output_directory / "pytest-junit.xml"
    json_bytes = json_path.read_bytes()
    report_bytes = report_path.read_bytes()
    try:
        document = json.loads(json_bytes)
    except (UnicodeDecodeError, ValueError) as error:
        raise RuntimeError("Persisted smoke JSON is not valid UTF-8 canonical JSON.") from error
    if not isinstance(document, dict):
        raise RuntimeError("Persisted smoke JSON must contain one object.")
    persisted_output_bytes = document.get("output_bytes")
    if type(persisted_output_bytes) is not int:
        raise RuntimeError("Persisted smoke output_bytes must be an integer.")
    reopened_total = len(json_bytes) + len(report_bytes)
    if persisted_output_bytes != reopened_total:
        raise RuntimeError(
            "Persisted smoke output_bytes differs from the reopened Markdown and JSON total: "
            f"recorded {persisted_output_bytes}, reopened {reopened_total}."
        )
    if evidence is not None:
        if json_bytes != evidence.json_bytes or report_bytes != evidence.markdown_bytes:
            raise RuntimeError("Persisted smoke evidence bytes differ from the final rendering.")
        if evidence.summary.output_bytes != reopened_total:
            raise RuntimeError("Final smoke summary differs from the reopened evidence byte total.")
        if evidence.junit_bytes is None:
            if junit_path.exists():
                raise RuntimeError("Persisted JUnit XML lacks an issued validation-result binding.")
        elif not junit_path.is_file() or junit_path.is_symlink():
            raise RuntimeError("Persisted JUnit XML is missing or is not a regular file.")
        elif junit_path.read_bytes() != evidence.junit_bytes:
            raise RuntimeError("Persisted JUnit XML differs from the exact issued pytest result.")
    return reopened_total


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "oracle-audit":
        nonce = secrets.token_hex(32)
        validation_run_identity = protocol_hash(
            "standalone_oracle_validation_run/v1",
            {"nonce": nonce},
        )
        binding = begin_oracle_evidence_binding(
            validation_run_identity=validation_run_identity,
            evidence_bundle_identity=protocol_hash(
                "standalone_oracle_evidence_bundle/v1",
                {"nonce": nonce, "validation_run_identity": validation_run_identity},
            ),
        )
        try:
            result = execute_oracle_conformance(binding)
            validate_oracle_conformance_result(result, binding=binding)
            print(
                f"oracle keys: {result.actual_unique_key_count}\n"
                f"sha256: {result.actual_sha256}\nstatus: PASS"
            )
            return 0
        finally:
            close_oracle_evidence_binding(binding)
    raise RuntimeError(
        "Smoke evidence generation requires an in-process exact-issued pytest result and "
        "an explicitly executed OracleConformanceResult; pass both capabilities to the "
        "bounded validation orchestration API."
    )


execute_bounded_validation_evidence = _build_bounded_validation_evidence_entrypoint()
del _build_bounded_validation_evidence_entrypoint


if __name__ == "__main__":
    raise SystemExit(main())
