"""Substantive tri-state implementations of the 16 frozen integrity audits."""

from __future__ import annotations

import hashlib
import inspect
import math
import threading
from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass, replace
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, NoReturn, SupportsIndex, cast

from research_decision_engine.benchmarks.broader_artifact_graph import (
    ArtifactCardinalityProfile,
    CanonicalArtifactGraph,
    validate_available_artifact_graph,
)
from research_decision_engine.benchmarks.broader_artifacts import artifact_contracts
from research_decision_engine.benchmarks.broader_calibration_history import (
    CalibrationHistorySelection,
)
from research_decision_engine.benchmarks.broader_execution import (
    ActualExecutorAttestation,
    ExecutionPurpose,
    ExecutorProvenanceError,
    ExecutorTrustDomain,
    _IssuedAttestation,
    _require_issued_result_batch,
    _value_identity,
    validate_executor_attestation,
)
from research_decision_engine.benchmarks.broader_oracle import (
    CALIBRATION_NAMESPACE,
    DECISION_NAMESPACE,
    OracleConformanceResult,
    OracleError,
    OracleEvidenceBinding,
    OracleFixtureBinding,
    OracleFixtureEvidence,
    OracleFixtureResult,
    RevealedObservation,
    SelectedObservationInterface,
    _validate_oracle_fixture_evidence,
    authorize_observation,
    calibration_key,
    decision_key,
    validate_oracle_conformance_result,
)
from research_decision_engine.benchmarks.broader_pipeline import (
    FrozenAnalysisOrchestrator,
    FrozenStudyOrchestrator,
)
from research_decision_engine.benchmarks.broader_protocol import (
    FULL_SEEDS,
    SMOKE_SEEDS,
    FrozenArm,
    ProtocolSnapshot,
    canonical_json_bytes,
    load_protocol_snapshot,
    repository_root,
    runtime_id,
)
from research_decision_engine.benchmarks.broader_runner import (
    BroaderArmRun,
    RunProvenanceError,
    replay_decisions,
    terminal_reason_for,
    validate_lineage_binding,
    validate_recorded_calibration,
    validated_calibration_history_selections,
)
from research_decision_engine.benchmarks.broader_statistics import (
    ActionTuple,
    DecisionBoolean,
    GateStatus,
    HolmInput,
    ResamplingEstimand,
    VetoResult,
    assert_executor_completeness,
    b_authorized,
    bootstrap_replicate,
    final_decision,
    holm_64,
    partition_action_tuples,
    sign_flip_replicate,
    unique_actionable_mechanism,
)
from research_decision_engine.benchmarks.broader_worlds import (
    CANDIDATES_BY_ID,
    PublicWorldDefinition,
    validate_worlds,
)
from research_decision_engine.evidence_eligibility import PublicExperimentDesign
from research_decision_engine.types import Candidate

if TYPE_CHECKING:
    from research_decision_engine.benchmarks.broader_analysis import (
        PreGateAnalysisResult,
        ProductionAnalysisResult,
    )

type AuditStatus = Literal["PASS", "FAIL", "INCONCLUSIVE"]

HISTORICAL_ROOTS: Final = (
    "benchmark-validation-output",
    "lookahead-benchmark-validation-output",
    "paired-evaluation-v1-100-seeds",
    "robust-belief-evaluation-v1-100-seeds",
    "robust-belief-evaluation-v1-100-seeds-accepted",
    "closed-loop-evaluation-v1-100-seeds",
    "divergence-audit-v1-189-cases",
)

PROTECTED_HASHES: Final = {
    "research_decision_engine/policies.py": (
        "98c0ecf1528287bc36797e3e14d46d9f28dee8982ac59b6795067c34599ed366"
    ),
    "research_decision_engine/decision.py": (
        "1c028f7544ca59196844e8a6c550a786bb60ca90bfa87a779442359ca750f6d6"
    ),
    "research_decision_engine/lookahead.py": (
        "a039c5b4ad8a5fed303465f10109285c6a46b84226c277550fa49a2df2dbb629"
    ),
    "research_decision_engine/reasoning.py": (
        "d0bdccb3d3bbbbce24db285f45fb26027f07056962d55ebc11d536e1a47456ff"
    ),
    "research_decision_engine/optimizer_effect.py": (
        "724505faef2a86e0564aa62108b116020a77f6876dbc9468ebcd199d0cd65de7"
    ),
    "research_decision_engine/evidence_eligibility.py": (
        "ac58eb1f08b0f90b23c177c6ff1262ab2871c18fd6bf22dbe0fab2904ead44fe"
    ),
    "research_decision_engine/belief_models.py": (
        "2b022592c6c7cb5ce52de69e27fc05dc806369aceef339a466669d5d462b78a3"
    ),
    "research_decision_engine/calibration.py": (
        "18702a0772ceab15aad3a02ecc8e11503cf11958f5b12bbca3e833f8e0d115fd"
    ),
    "research_decision_engine/closed_loop.py": (
        "1007aa226bec060470b1a347b0a5e9caa07e6e3d5bf13e1ae2e345f1790ec80d"
    ),
    "research_decision_engine/benchmarks/worlds.py": (
        "377bedbe41ff97fe6a5c12232f6c9d2a9d1793868c253cfb837dc77f2f2215a5"
    ),
    "research_decision_engine/benchmarks/paired_evaluation.py": (
        "c901d00e1f08b9ab92cef00a4e3e34dc7b74999cc7459677eaa08f925c51f2c4"
    ),
    "research_decision_engine/benchmarks/closed_loop_evaluation.py": (
        "4ff9752aaafd039ab1d0a574988fdc23212a3022f9dc8e1517ec72c09a556bbb"
    ),
    "research_decision_engine/benchmarks/divergence_audit.py": (
        "bdec5399324d48d84a8534ceeb377b9315056737b0da6ddd559444f6c86ba97b"
    ),
}


@dataclass(frozen=True, slots=True)
class AuditObservation:
    status: AuditStatus
    detail: str


@dataclass(frozen=True, slots=True)
class IntegrityAuditResult:
    audit_id: str
    audit_order: int
    requirement: str
    observed: str
    status: AuditStatus


@dataclass(frozen=True, slots=True)
class FixtureAuditDiagnostic:
    """Non-authoritative A01-A16 observation from bounded fixture evidence."""

    audit_id: str
    audit_order: int
    requirement: str
    observed: str
    status: AuditStatus

    @property
    def authoritative(self) -> Literal[False]:
        return False


SmokeAuditResult = IntegrityAuditResult


@dataclass(frozen=True, slots=True)
class IntegrityAuditContext:
    runs: tuple[BroaderArmRun, ...]
    replay_runs: tuple[BroaderArmRun, ...]
    first_payload: bytes
    replay_payload: bytes
    historical_before: tuple[tuple[str, str], ...]
    historical_after: tuple[tuple[str, str], ...]
    scope: Literal["smoke", "conformance", "full"] = "smoke"
    artifact_graph: CanonicalArtifactGraph | None = None
    analysis: PreGateAnalysisResult | ProductionAnalysisResult | None = None
    profile: ArtifactCardinalityProfile | None = None
    prefinalization_payloads: Mapping[str, object] | None = None
    oracle_conformance_result: OracleConformanceResult | None = None
    oracle_evidence_binding: OracleEvidenceBinding | None = None
    oracle_fixture_result: OracleFixtureResult | None = None
    oracle_fixture_binding: OracleFixtureBinding | None = None
    prefinal_operational_provenance_sha256: str | None = None
    executor_attestation: ActualExecutorAttestation | None = None
    replay_executor_attestation: ActualExecutorAttestation | None = None
    executor_results: tuple[BroaderArmRun, ...] | None = None
    replay_executor_results: tuple[BroaderArmRun, ...] | None = None
    execution_authority: object | None = None
    execution_purpose: ExecutionPurpose | None = None


SmokeAuditContext = IntegrityAuditContext


_CAPABILITY_CONSTRUCTION_KEY: Final = object()
FINALIZATION_AUTHORIZATION_VERSION: Final = "broader-finalization-authorization/v2"


class _OpaqueCapability:
    """Identity-only capability that cannot be copied, serialized, or subclassed."""

    __slots__ = ()

    def __new__(cls, construction_key: object | None = None) -> _OpaqueCapability:
        if construction_key is not _CAPABILITY_CONSTRUCTION_KEY:
            raise TypeError(f"{cls.__name__} is issued only by the audited lifecycle.")
        return super().__new__(cls)

    def __init_subclass__(cls, **kwargs: object) -> None:
        if cls.__module__ != __name__:
            raise TypeError("Finalization capabilities cannot be subclassed.")
        super().__init_subclass__(**kwargs)

    def __copy__(self) -> None:
        raise TypeError("Finalization capabilities cannot be copied.")

    def __deepcopy__(self, memo: object) -> None:
        del memo
        raise TypeError("Finalization capabilities cannot be deep-copied.")

    def __reduce__(self) -> NoReturn:
        raise TypeError("Finalization capabilities cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Finalization capabilities cannot be serialized.")


class PreFinalizationAuthorization(_OpaqueCapability):
    """Opaque evidence that A01-A15 executed successfully before gates."""


class FinalizationAuditCertificate(_OpaqueCapability):
    """Opaque A01-A16 result awaiting exact-context sealing."""


class FinalizationAuthorization(_OpaqueCapability):
    """Opaque, exact-context, single-use permission to begin finalization."""


class ConsumedFinalizationAuthorization(_OpaqueCapability):
    """Internal phase receipt retained after the public capability is consumed."""


class FinalizationAuditError(ValueError):
    """Raised when the executed audit lifecycle cannot authorize artifacts."""

    def __init__(self, audit_results: tuple[IntegrityAuditResult, ...]) -> None:
        self.audit_results = audit_results
        failures = tuple(
            (item.audit_id, item.status, item.observed)
            for item in audit_results
            if item.status != "PASS"
        )
        super().__init__(f"Canonical finalization is prohibited: {failures}")


@dataclass(slots=True)
class _FinalizationAuthorizationRecord:
    audit_results: tuple[IntegrityAuditResult, ...]
    binding: bytes
    binding_payload: dict[str, object]
    oracle_conformance_result: OracleConformanceResult
    oracle_evidence_binding: OracleEvidenceBinding


@dataclass(slots=True)
class _FinalizationReceiptRecord:
    audit_results: tuple[IntegrityAuditResult, ...]
    binding: bytes
    binding_payload: dict[str, object]
    lifecycle_phase: str
    writer_state: Literal["available", "claimed", "published"]
    oracle_conformance_result: OracleConformanceResult
    oracle_evidence_binding: OracleEvidenceBinding


@dataclass(slots=True)
class _PreFinalizationAuditRecord:
    audit_results: tuple[IntegrityAuditResult, ...]
    context: IntegrityAuditContext


@dataclass(slots=True)
class _FinalizationAuditCertificateRecord:
    audit_results: tuple[IntegrityAuditResult, ...]
    context: IntegrityAuditContext
    plan_binding_sha256: str


@dataclass(slots=True)
class _AuthoritativeAuditResultBatchRecord:
    audit_results: tuple[IntegrityAuditResult, ...]
    context: IntegrityAuditContext
    execution: _IssuedAttestation
    certificate: FinalizationAuditCertificate


@dataclass(slots=True)
class _FixtureAuditResultBatchRecord:
    audit_results: tuple[FixtureAuditDiagnostic, ...]
    context: IntegrityAuditContext
    execution: _IssuedAttestation


_ISSUED_PRE_FINALIZATION_AUTHORIZATIONS: dict[
    PreFinalizationAuthorization, _PreFinalizationAuditRecord
] = {}
_ISSUED_FINALIZATION_AUDIT_CERTIFICATES: dict[
    FinalizationAuditCertificate, _FinalizationAuditCertificateRecord
] = {}
_ISSUED_FINALIZATION_AUTHORIZATIONS: dict[
    FinalizationAuthorization, _FinalizationAuthorizationRecord
] = {}
_CONSUMED_FINALIZATION_AUTHORIZATIONS: dict[
    ConsumedFinalizationAuthorization, _FinalizationReceiptRecord
] = {}
_ISSUED_AUTHORITATIVE_AUDIT_RESULTS: dict[int, _AuthoritativeAuditResultBatchRecord] = {}
_ISSUED_FIXTURE_AUDIT_RESULTS: dict[int, _FixtureAuditResultBatchRecord] = {}
_FINALIZATION_CAPABILITY_LOCK = threading.RLock()


def _require_authoritative_oracle_evidence(
    result: OracleConformanceResult,
    binding: OracleEvidenceBinding,
) -> tuple[OracleConformanceResult, OracleEvidenceBinding]:
    """Revalidate the exact production Oracle lineage at an authority transition."""

    if validate_oracle_conformance_result(result, binding=binding) is not result:
        raise OracleError("Oracle conformance validation returned another result.")
    return result, binding


def _require_authoritative_oracle_context(
    context: IntegrityAuditContext,
) -> tuple[OracleConformanceResult, OracleEvidenceBinding]:
    result = context.oracle_conformance_result
    binding = context.oracle_evidence_binding
    if (
        result is None
        or binding is None
        or context.oracle_fixture_result is not None
        or context.oracle_fixture_binding is not None
    ):
        raise OracleError("Finalization authority requires exact production Oracle evidence.")
    return _require_authoritative_oracle_evidence(result, binding)


def _executor_context_error(error_code: str, message: str) -> NoReturn:
    raise ExecutorProvenanceError(
        message,
        error_code=error_code,
        validation_layer="integrity_audit_context",
    )


def _executor_trust_domain_for_context(
    context: IntegrityAuditContext,
) -> ExecutorTrustDomain:
    authority = context.execution_authority
    if type(authority) is OracleEvidenceBinding:
        return "production"
    if authority is None or type(authority) is OracleFixtureBinding:
        return "fixture"
    _executor_context_error(
        "AUDIT_EXECUTION_AUTHORITY_NOT_ISSUED",
        "Audit execution authority is outside the exact Oracle or local fixture domains.",
    )


def _expected_audit_execution_purpose(
    context: IntegrityAuditContext,
    *,
    trust_domain: ExecutorTrustDomain,
) -> ExecutionPurpose:
    if context.scope == "full":
        if trust_domain != "production":
            _executor_context_error(
                "AUDIT_EXECUTION_TRUST_DOMAIN_MISMATCH",
                "Full-study audits require production executor evidence.",
            )
        expected: ExecutionPurpose = "full_study"
    elif context.scope == "conformance":
        expected = (
            "production_conformance" if trust_domain == "production" else "diagnostic_conformance"
        )
    else:
        expected = "smoke_validation"
    if context.execution_purpose != expected:
        _executor_context_error(
            "AUDIT_EXECUTION_PURPOSE_MISMATCH",
            f"{context.scope} audit context requires executor purpose {expected!r}.",
        )
    authority = context.execution_authority
    if trust_domain == "production":
        if type(authority) is not OracleEvidenceBinding:
            _executor_context_error(
                "AUDIT_EXECUTION_AUTHORITY_MISMATCH",
                "Production audits require an exact production Oracle binding.",
            )
        if (
            context.scope in {"conformance", "full"}
            and context.oracle_evidence_binding is not authority
        ):
            _executor_context_error(
                "AUDIT_EXECUTION_AUTHORITY_MISMATCH",
                "Audited executor results belong to another production Oracle binding.",
            )
    else:
        if authority is not None and type(authority) is not OracleFixtureBinding:
            _executor_context_error(
                "AUDIT_EXECUTION_AUTHORITY_MISMATCH",
                "Fixture audits require an exact fixture Oracle binding or local authority.",
            )
        if context.scope == "conformance" and context.oracle_fixture_binding is not authority:
            _executor_context_error(
                "AUDIT_EXECUTION_AUTHORITY_MISMATCH",
                "Diagnostic audit results belong to another fixture Oracle binding.",
            )
    return expected


def _require_executor_audit_context(
    context: IntegrityAuditContext,
    *,
    trust_domain: ExecutorTrustDomain,
) -> tuple[_IssuedAttestation, _IssuedAttestation]:
    """Require both exact executor-returned populations before an audit can pass."""

    expected_purpose = _expected_audit_execution_purpose(
        context,
        trust_domain=trust_domain,
    )
    primary_attestation = context.executor_attestation
    replay_attestation = context.replay_executor_attestation
    if (
        type(primary_attestation) is not ActualExecutorAttestation
        or type(replay_attestation) is not ActualExecutorAttestation
    ):
        _executor_context_error(
            "AUDIT_EXECUTION_ATTESTATION_MISSING",
            "A06 requires exact primary and replay executor attestations.",
        )
    primary_results = context.runs if context.executor_results is None else context.executor_results
    replay_results = (
        context.replay_runs
        if context.replay_executor_results is None
        else context.replay_executor_results
    )
    primary = _require_issued_result_batch(
        primary_results,
        expected_purposes=(expected_purpose,),
        require_trust_domain=trust_domain,
    )
    replay = _require_issued_result_batch(
        replay_results,
        expected_purposes=(expected_purpose,),
        require_trust_domain=trust_domain,
    )
    if (
        primary is replay
        or primary.attestation is not primary_attestation
        or replay.attestation is not replay_attestation
    ):
        _executor_context_error(
            "AUDIT_EXECUTION_RESULT_BINDING_MISMATCH",
            "Audit populations are not bound to their declared independent executions.",
        )
    if sorted(map(id, context.runs)) != sorted(map(id, primary_results)) or sorted(
        map(id, context.replay_runs)
    ) != sorted(map(id, replay_results)):
        _executor_context_error(
            "AUDIT_EXECUTION_POPULATION_MISMATCH",
            "Audited run populations are not exact-object reorderings of executor results.",
        )
    validate_executor_attestation(
        primary_attestation,
        results=primary_results,
        execution_authority=context.execution_authority,
        expected_purpose=expected_purpose,
        require_trust_domain=trust_domain,
    )
    validate_executor_attestation(
        replay_attestation,
        results=replay_results,
        execution_authority=context.execution_authority,
        expected_purpose=expected_purpose,
        require_trust_domain=trust_domain,
    )
    return primary, replay


def _audit_truth_free_projection(run: BroaderArmRun) -> dict[str, object]:
    """Own the deterministic smoke projection inside the audit boundary."""

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


def _recomputed_audit_payload(
    context: IntegrityAuditContext,
    runs: tuple[BroaderArmRun, ...],
    execution: _IssuedAttestation,
) -> bytes:
    """Recompute one declared payload only from its exact executor result objects."""

    if sorted(map(id, runs)) != sorted(map(id, execution.returned_results)):
        _executor_context_error(
            "AUDIT_EXECUTION_PAYLOAD_POPULATION_MISMATCH",
            "Determinism payload population differs from the exact executor result tuple.",
        )
    projected = _declared_determinism_projection(context, runs)
    payload = canonical_json_bytes(projected, final_lf=True)
    structural_payload = canonical_json_bytes(
        [_value_identity(run) for run in runs],
        final_lf=True,
    )
    return canonical_json_bytes(
        {
            "declared_projection_sha256": hashlib.sha256(payload).hexdigest(),
            "structural_result_order_sha256": hashlib.sha256(structural_payload).hexdigest(),
        },
        final_lf=True,
    )


def _declared_determinism_projection(
    context: IntegrityAuditContext,
    runs: tuple[BroaderArmRun, ...],
) -> object:
    """Rebuild the declared replay view without trusting caller-provided bytes."""

    if all(type(run) is BroaderArmRun for run in runs):
        if context.scope == "smoke":
            return [_audit_truth_free_projection(run) for run in runs]
        return [
            {
                "run_id": run.run_id,
                "selected_candidate_ids": list(run.selected_candidate_ids),
                "final_probabilities": dict(run.final_probabilities),
                "decision_cost": run.decision_cost,
                "calibration_cost": run.calibration_cost,
            }
            for run in runs
        ]
    if all(is_dataclass(run) for run in runs):
        return [[getattr(run, field.name) for field in fields(run)] for run in runs]
    return [_value_identity(run) for run in runs]


def _require_deterministic_audit_payloads(
    context: IntegrityAuditContext,
    primary: _IssuedAttestation,
    replay: _IssuedAttestation,
) -> tuple[bytes, bytes]:
    """Bind declared replay bytes to recomputation from both exact result tuples."""

    primary_projection = _declared_determinism_projection(context, context.runs)
    replay_projection = _declared_determinism_projection(context, context.replay_runs)
    declared_primary = canonical_json_bytes(primary_projection, final_lf=True)
    declared_replay = canonical_json_bytes(replay_projection, final_lf=True)
    if context.first_payload != declared_primary or context.replay_payload != declared_replay:
        _executor_context_error(
            "AUDIT_DETERMINISM_PAYLOAD_BINDING_MISMATCH",
            "Declared deterministic payload bytes differ from exact-result recomputation.",
        )
    return (
        _recomputed_audit_payload(context, context.runs, primary),
        _recomputed_audit_payload(context, context.replay_runs, replay),
    )


def _register_authoritative_audit_results(
    audit_results: tuple[IntegrityAuditResult, ...],
    *,
    context: IntegrityAuditContext,
    certificate: FinalizationAuditCertificate,
) -> _AuthoritativeAuditResultBatchRecord:
    execution, _ = _require_executor_audit_context(context, trust_domain="production")
    expected_ids = load_protocol_snapshot().registry("audit").ids("audit_id")
    if (
        type(audit_results) is not tuple
        or any(type(item) is not IntegrityAuditResult for item in audit_results)
        or tuple(item.audit_id for item in audit_results) != expected_ids
    ):
        raise ValueError("Authoritative audit registration requires exact A01-A16 results.")
    certificate_record = _ISSUED_FINALIZATION_AUDIT_CERTIFICATES.get(certificate)
    if (
        certificate_record is None
        or certificate_record.audit_results is not audit_results
        or certificate_record.context is not context
    ):
        raise ValueError("Audit results do not belong to the declared exact certificate context.")
    record = _AuthoritativeAuditResultBatchRecord(
        audit_results,
        context,
        execution,
        certificate,
    )
    with _FINALIZATION_CAPABILITY_LOCK:
        prior = _ISSUED_AUTHORITATIVE_AUDIT_RESULTS.get(id(audit_results))
        if prior is not None and prior.audit_results is not audit_results:
            raise ValueError("Authoritative audit result registry identity collision.")
        _ISSUED_AUTHORITATIVE_AUDIT_RESULTS[id(audit_results)] = record
    return record


def _require_authoritative_audit_results(
    audit_results: Sequence[IntegrityAuditResult],
    *,
    runs: Sequence[BroaderArmRun],
    analysis: ProductionAnalysisResult | None = None,
    prefinalization: Mapping[str, object] | None = None,
) -> _IssuedAttestation:
    """Resolve A01-A16 results only for their exact certificate and execution."""

    with _FINALIZATION_CAPABILITY_LOCK:
        record = _ISSUED_AUTHORITATIVE_AUDIT_RESULTS.get(id(audit_results))
        certificate_record = (
            _ISSUED_FINALIZATION_AUDIT_CERTIFICATES.get(record.certificate)
            if record is not None
            else None
        )
    if (
        record is None
        or audit_results is not record.audit_results
        or certificate_record is None
        or certificate_record.audit_results is not record.audit_results
        or certificate_record.context is not record.context
    ):
        raise ValueError("Production projection requires exact issued A01-A16 certificate results.")
    execution, _ = _require_executor_audit_context(
        record.context,
        trust_domain="production",
    )
    consumed_execution = _require_issued_result_batch(
        runs,
        expected_purposes=("production_conformance", "full_study"),
        require_trust_domain="production",
    )
    if (
        runs is not record.context.runs
        or execution is not record.execution
        or consumed_execution is not record.execution
    ):
        raise ValueError("Audit results belong to another executor result batch.")
    _require_audit_projection_context(
        record.context,
        record.audit_results,
        analysis=analysis,
        prefinalization=prefinalization,
    )
    return execution


def _discard_authoritative_audit_results(
    audit_results: tuple[IntegrityAuditResult, ...],
) -> None:
    with _FINALIZATION_CAPABILITY_LOCK:
        record = _ISSUED_AUTHORITATIVE_AUDIT_RESULTS.get(id(audit_results))
        if record is not None and record.audit_results is audit_results:
            del _ISSUED_AUTHORITATIVE_AUDIT_RESULTS[id(audit_results)]


def _register_fixture_audit_diagnostics(
    context: IntegrityAuditContext,
    audit_results: tuple[FixtureAuditDiagnostic, ...],
    *,
    oracle_fixture_evidence: OracleFixtureEvidence,
) -> tuple[FixtureAuditDiagnostic, ...]:
    """Bind bounded diagnostics to their exact fixture executor population."""

    _require_fixture_audit_context(context, oracle_fixture_evidence)
    execution, _ = _require_executor_audit_context(context, trust_domain="fixture")
    expected_ids = load_protocol_snapshot().registry("audit").ids("audit_id")
    if (
        type(audit_results) is not tuple
        or any(type(item) is not FixtureAuditDiagnostic for item in audit_results)
        or tuple(item.audit_id for item in audit_results) != expected_ids
    ):
        raise ValueError("Fixture audit registration requires exact A01-A16 diagnostics.")
    record = _FixtureAuditResultBatchRecord(audit_results, context, execution)
    with _FINALIZATION_CAPABILITY_LOCK:
        prior = _ISSUED_FIXTURE_AUDIT_RESULTS.get(id(audit_results))
        if prior is not None and prior.audit_results is not audit_results:
            raise ValueError("Fixture audit result registry identity collision.")
        _ISSUED_FIXTURE_AUDIT_RESULTS[id(audit_results)] = record
    return audit_results


def _require_issued_fixture_audit_diagnostics(
    audit_results: Sequence[FixtureAuditDiagnostic],
    *,
    runs: Sequence[BroaderArmRun],
    analysis: ProductionAnalysisResult | None = None,
    prefinalization: Mapping[str, object] | None = None,
) -> _IssuedAttestation:
    """Resolve bounded diagnostics only for their exact fixture execution."""

    with _FINALIZATION_CAPABILITY_LOCK:
        record = _ISSUED_FIXTURE_AUDIT_RESULTS.get(id(audit_results))
    if record is None or audit_results is not record.audit_results:
        raise ValueError("Fixture projection requires exact issued A01-A16 diagnostics.")
    execution, _ = _require_executor_audit_context(record.context, trust_domain="fixture")
    consumed_execution = _require_issued_result_batch(
        runs,
        expected_purposes=("diagnostic_conformance",),
        require_trust_domain="fixture",
    )
    if (
        runs is not record.context.runs
        or execution is not record.execution
        or consumed_execution is not record.execution
    ):
        raise ValueError("Fixture audit diagnostics belong to another executor result batch.")
    _require_audit_projection_context(
        record.context,
        record.audit_results,
        analysis=analysis,
        prefinalization=prefinalization,
    )
    return execution


def _require_audit_projection_context(
    context: IntegrityAuditContext,
    audit_results: Sequence[IntegrityAuditResult | FixtureAuditDiagnostic],
    *,
    analysis: ProductionAnalysisResult | None,
    prefinalization: Mapping[str, object] | None,
) -> None:
    """Bind post-audit projection to the exact prefinal claims and audited analysis."""

    if (analysis is None) != (prefinalization is None):
        raise ValueError("Audit projection analysis and prefinalization must be bound together.")
    if analysis is None:
        return
    if prefinalization is None:
        raise ValueError("Audit projection requires exact prefinalization payloads.")
    if prefinalization is not context.prefinalization_payloads:
        raise ValueError("Audit results belong to another exact prefinalization payload set.")
    from research_decision_engine.benchmarks.broader_analysis import (
        ProductionAnalysisResult,
        _issued_analysis_lineage,
        _require_issued_analysis,
        finalize_analysis_with_audits,
    )
    from research_decision_engine.benchmarks.broader_projection import (
        _issued_prefinalization_lineage,
        _issued_prefinalization_source_analysis,
        _require_issued_prefinalization_payloads,
    )

    if (
        type(context.analysis) is not ProductionAnalysisResult
        or type(analysis) is not ProductionAnalysisResult
    ):
        raise ValueError("Audit projection requires the exact production analysis stage.")
    context_execution = _require_issued_analysis(context.analysis, runs=context.runs)
    analysis_execution = _require_issued_analysis(analysis, runs=context.runs)
    prefinal_execution = _require_issued_prefinalization_payloads(prefinalization)
    source_analysis = _issued_prefinalization_source_analysis(prefinalization)
    lineage = _issued_analysis_lineage(context.analysis)
    if (
        context_execution is not analysis_execution
        or context_execution is not prefinal_execution
        or _issued_analysis_lineage(analysis) is not lineage
        or _issued_analysis_lineage(source_analysis) is not lineage
        or _issued_prefinalization_lineage(prefinalization) is not lineage
    ):
        raise ValueError("Audit projection crosses an exact analysis or executor lineage.")
    statuses = {item.audit_id: GateStatus(item.status) for item in audit_results}
    expected = finalize_analysis_with_audits(context.analysis, statuses)
    if analysis != expected or _issued_analysis_lineage(expected) is not lineage:
        raise ValueError("Post-audit analysis differs from the exact A01-A16 audited analysis.")


def _require_prefinal_audit_context(
    context: IntegrityAuditContext,
    execution: _IssuedAttestation,
) -> None:
    """Bind A01-A15 entry to exact analysis-derived prefinal scientific claims."""

    from research_decision_engine.benchmarks.broader_analysis import (
        PreGateAnalysisResult,
        _issued_analysis_lineage,
        _require_issued_analysis,
    )
    from research_decision_engine.benchmarks.broader_projection import (
        _issued_prefinalization_lineage,
        _issued_prefinalization_source_analysis,
        _require_issued_prefinalization_payloads,
    )

    analysis = context.analysis
    payloads = context.prefinalization_payloads
    if type(analysis) is not PreGateAnalysisResult or payloads is None:
        raise ValueError("A01-A15 requires exact pre-gate analysis and prefinal payloads.")
    analysis_execution = _require_issued_analysis(analysis, runs=context.runs)
    projection_execution = _require_issued_prefinalization_payloads(
        payloads,
        analysis=analysis,
    )
    source_analysis = _issued_prefinalization_source_analysis(payloads)
    if (
        analysis_execution is not execution
        or projection_execution is not execution
        or source_analysis is not analysis
        or _issued_prefinalization_lineage(payloads) is not _issued_analysis_lineage(analysis)
    ):
        raise ValueError("Prefinal audit context crosses an analysis or executor lineage.")


def historical_hash_map(root: Path | None = None) -> tuple[tuple[str, str], ...]:
    repository = root or repository_root()
    records: list[tuple[str, str]] = []
    for root_name in HISTORICAL_ROOTS:
        directory = repository / root_name
        if not directory.is_dir():
            raise ValueError(f"Historical root is missing: {root_name}")
        for path in directory.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"Historical path is a symlink: {path}")
            if path.is_file():
                relative = path.relative_to(directory).as_posix()
                records.append(
                    (f"{root_name}/{relative}", hashlib.sha256(path.read_bytes()).hexdigest())
                )
    ordered = tuple(sorted(records, key=lambda item: item[0].encode("utf-8")))
    if len({item[0] for item in ordered}) != len(ordered):
        raise ValueError("Historical map contains duplicate normalized paths.")
    return ordered


def run_integrity_audits(context: IntegrityAuditContext) -> tuple[IntegrityAuditResult, ...]:
    snapshot = load_protocol_snapshot()
    results: list[IntegrityAuditResult] = []
    for row in snapshot.registry("audit").records():
        audit_id = row["audit_id"]
        try:
            observation = evaluate_audit(audit_id, context, snapshot=snapshot)
        except Exception as error:  # one audit failure must not hide later audit diagnostics
            observation = AuditObservation("FAIL", f"{type(error).__name__}: {error}")
        results.append(
            IntegrityAuditResult(
                audit_id=audit_id,
                audit_order=int(row["audit_order"]),
                requirement=row["requirement"],
                observed=observation.detail,
                status=observation.status,
            )
        )
    return tuple(results)


def run_pre_finalization_audits(
    context: IntegrityAuditContext,
) -> tuple[IntegrityAuditResult, ...]:
    """Execute A01-A15 before any canonical recommendation or manifest exists."""

    return _run_selected_audits(context, audit_ids=tuple(AUDIT_EXECUTORS)[:15])


def run_finalization_audit(context: IntegrityAuditContext) -> IntegrityAuditResult:
    """Execute A16 only against an in-memory provisional analysis result."""

    return _run_selected_audits(context, audit_ids=("A16-FINALIZATION",))[0]


def finalization_plan_binding_sha256(
    scientific: Mapping[str, object],
    profile: ArtifactCardinalityProfile,
) -> str:
    """Identify the exact 1-11 scientific plan and cardinality scope audited for A16."""

    expected_names = tuple(contract.filename for contract in artifact_contracts()[:11])
    if tuple(scientific) != expected_names:
        raise ValueError("Finalization plan binding requires exact artifacts 1-11.")
    payload = {
        "artifact_cardinality_profile": {
            "arm_runs": profile.arm_runs,
            "comparisons": profile.comparisons,
            "calibration_estimates": profile.calibration_estimates,
            "bootstrap_rows": profile.bootstrap_rows,
            "sign_flip_rows": profile.sign_flip_rows,
            "bootstrap_replicates_per_contrast": (profile.bootstrap_replicates_per_contrast),
            "sign_flip_replicates_per_hypothesis": (profile.sign_flip_replicates_per_hypothesis),
            "canonical": profile.canonical,
        },
        "scientific_claim_sha256": {
            name: hashlib.sha256(canonical_json_bytes(scientific[name], final_lf=True)).hexdigest()
            for name in expected_names
        },
    }
    return hashlib.sha256(canonical_json_bytes(payload, final_lf=True)).hexdigest()


def _validate_audit_context_transition(
    prefinal: IntegrityAuditContext,
    final: IntegrityAuditContext,
) -> None:
    from research_decision_engine.benchmarks.broader_analysis import (
        PreGateAnalysisResult,
        ProductionAnalysisResult,
        _issued_analysis_lineage,
        _require_issued_analysis,
        derive_provisional_analysis,
    )

    if (
        replace(prefinal, analysis=None) != replace(final, analysis=None)
        or final.prefinalization_payloads is not prefinal.prefinalization_payloads
    ):
        raise ValueError("A16 audit context differs from the A01-A15 audited context.")
    if type(prefinal.analysis) is not PreGateAnalysisResult:
        raise ValueError("A01-A15 authorization lacks the exact pre-gate analysis.")
    if type(final.analysis) is not ProductionAnalysisResult:
        raise ValueError("A16 requires the exact issued provisional analysis stage.")
    execution, _ = _require_executor_audit_context(
        prefinal,
        trust_domain="production",
    )
    _require_prefinal_audit_context(prefinal, execution)
    prefinal_execution = _require_issued_analysis(prefinal.analysis, runs=prefinal.runs)
    final_execution = _require_issued_analysis(final.analysis, runs=final.runs)
    lineage = _issued_analysis_lineage(prefinal.analysis)
    expected = derive_provisional_analysis(prefinal.analysis, run_count=len(prefinal.runs))
    if (
        final.analysis != expected
        or prefinal_execution is not execution
        or final_execution is not execution
        or _issued_analysis_lineage(final.analysis) is not lineage
        or _issued_analysis_lineage(expected) is not lineage
    ):
        raise ValueError("A16 provisional analysis differs from the audited pre-gate analysis.")


def _expected_finalization_plan_binding(
    context: IntegrityAuditContext,
    results: tuple[IntegrityAuditResult, ...],
) -> str:
    from research_decision_engine.benchmarks.broader_analysis import (
        ProductionAnalysisResult,
        finalize_analysis_with_audits,
    )
    from research_decision_engine.benchmarks.broader_projection import (
        build_post_audit_payloads,
        merged_scientific_claims,
    )

    if type(context.analysis) is not ProductionAnalysisResult:
        raise ValueError("A16 certificate lacks the exact provisional analysis.")
    if context.artifact_graph is None or context.profile is None:
        raise ValueError("A16 certificate lacks the prefinal graph or artifact profile.")
    if context.prefinalization_payloads is None:
        raise ValueError("A16 certificate lacks the exact issued prefinal scientific payloads.")
    if context.prefinal_operational_provenance_sha256 is None:
        raise ValueError("A16 certificate lacks the prefinal operational provenance identity.")
    audit_statuses = {item.audit_id: GateStatus(item.status) for item in results}
    final_analysis = finalize_analysis_with_audits(context.analysis, audit_statuses)
    prefinal = context.prefinalization_payloads
    post_audit = build_post_audit_payloads(
        context.runs,
        final_analysis,
        results,
        prefinal,
    )
    return finalization_plan_binding_sha256(
        merged_scientific_claims(prefinal, post_audit),
        context.profile,
    )


def execute_pre_finalization_audits(
    context: IntegrityAuditContext,
) -> PreFinalizationAuthorization:
    """Execute and register A01-A15 without accepting external result tuples."""

    execution, _ = _require_executor_audit_context(context, trust_domain="production")
    _require_prefinal_audit_context(context, execution)
    results = _run_selected_audits(context, audit_ids=tuple(AUDIT_EXECUTORS)[:15])
    if any(item.status != "PASS" for item in results):
        raise FinalizationAuditError(results)
    _require_authoritative_oracle_context(context)
    authorization = PreFinalizationAuthorization(_CAPABILITY_CONSTRUCTION_KEY)
    _ISSUED_PRE_FINALIZATION_AUTHORIZATIONS[authorization] = _PreFinalizationAuditRecord(
        results,
        context,
    )
    return authorization


def _run_fixture_pre_finalization_audits(
    context: IntegrityAuditContext,
    *,
    oracle_fixture_evidence: OracleFixtureEvidence,
) -> tuple[FixtureAuditDiagnostic, ...]:
    """Return explicitly non-authoritative A01-A15 fixture diagnostics."""

    execution, _ = _require_executor_audit_context(context, trust_domain="fixture")
    _require_prefinal_audit_context(context, execution)
    _require_fixture_audit_context(context, oracle_fixture_evidence)
    return _run_fixture_selected_audits(
        context,
        audit_ids=tuple(AUDIT_EXECUTORS)[:15],
        oracle_fixture_evidence=oracle_fixture_evidence,
    )


def _run_fixture_finalization_audit(
    context: IntegrityAuditContext,
    *,
    oracle_fixture_evidence: OracleFixtureEvidence,
) -> FixtureAuditDiagnostic:
    """Return an explicitly non-authoritative A16 fixture diagnostic."""

    _require_executor_audit_context(context, trust_domain="fixture")
    _require_fixture_audit_context(context, oracle_fixture_evidence)
    return _run_fixture_selected_audits(
        context,
        audit_ids=("A16-FINALIZATION",),
        oracle_fixture_evidence=oracle_fixture_evidence,
    )[0]


def execute_finalization_audit(
    context: IntegrityAuditContext,
    pre_authorization: PreFinalizationAuthorization,
) -> FinalizationAuditCertificate:
    """Execute A16 after an issued A01-A15 authorization and provisional gates."""

    if type(pre_authorization) is not PreFinalizationAuthorization:
        raise ValueError("A16 requires an issued A01-A15 authorization.")
    pre_record = _ISSUED_PRE_FINALIZATION_AUTHORIZATIONS.pop(pre_authorization, None)
    if pre_record is None:
        raise ValueError("A16 requires an issued A01-A15 authorization.")
    _require_executor_audit_context(pre_record.context, trust_domain="production")
    _require_authoritative_oracle_context(pre_record.context)
    _validate_audit_context_transition(pre_record.context, context)
    _require_executor_audit_context(context, trust_domain="production")
    _require_authoritative_oracle_context(context)
    final = run_finalization_audit(context)
    results = (*pre_record.audit_results, final)
    if any(item.status != "PASS" for item in results):
        raise FinalizationAuditError(results)
    _require_authoritative_oracle_context(context)
    certificate = FinalizationAuditCertificate(_CAPABILITY_CONSTRUCTION_KEY)
    certificate_record = _FinalizationAuditCertificateRecord(
        results,
        context,
        "",
    )
    _ISSUED_FINALIZATION_AUDIT_CERTIFICATES[certificate] = certificate_record
    try:
        _register_authoritative_audit_results(
            results,
            context=context,
            certificate=certificate,
        )
        certificate_record.plan_binding_sha256 = _expected_finalization_plan_binding(
            context,
            results,
        )
    except BaseException:
        _ISSUED_FINALIZATION_AUDIT_CERTIFICATES.pop(certificate, None)
        _discard_authoritative_audit_results(results)
        raise
    return certificate


def seal_finalization_authorization(
    certificate: FinalizationAuditCertificate,
    binding: Mapping[str, object],
    *,
    binding_attestation: object | None = None,
) -> FinalizationAuthorization:
    """Consume an A01-A16 certificate and issue one exact-context capability."""

    if type(certificate) is not FinalizationAuditCertificate:
        raise ValueError("Only an issued A01-A16 certificate can be sealed.")
    certificate_record = _ISSUED_FINALIZATION_AUDIT_CERTIFICATES.get(certificate)
    if certificate_record is None:
        raise ValueError("Only a fresh A01-A16 certificate can be sealed.")
    _require_authoritative_audit_results(
        certificate_record.audit_results,
        runs=certificate_record.context.runs,
    )
    _require_authoritative_oracle_context(certificate_record.context)
    from research_decision_engine.benchmarks.broader_assembly import (
        _consume_finalization_binding_attestation,
    )

    _consume_finalization_binding_attestation(binding_attestation, binding)
    del _ISSUED_FINALIZATION_AUDIT_CERTIFICATES[certificate]
    _discard_authoritative_audit_results(certificate_record.audit_results)
    _validate_finalization_certificate_record(certificate_record, binding)
    results = certificate_record.audit_results
    oracle_result, oracle_binding = _require_authoritative_oracle_context(
        certificate_record.context
    )
    binding_bytes = _authorization_binding_bytes(results, binding)
    authorization = FinalizationAuthorization(_CAPABILITY_CONSTRUCTION_KEY)
    _ISSUED_FINALIZATION_AUTHORIZATIONS[authorization] = _FinalizationAuthorizationRecord(
        results,
        binding_bytes,
        deepcopy(dict(binding)),
        oracle_result,
        oracle_binding,
    )
    return authorization


def _validate_finalization_certificate_binding(
    certificate: FinalizationAuditCertificate,
    binding: Mapping[str, object],
) -> None:
    """Test the exact certificate-to-binding transition without issuing capability."""

    if type(certificate) is not FinalizationAuditCertificate:
        raise ValueError("Only an issued A01-A16 certificate can be validated.")
    record = _ISSUED_FINALIZATION_AUDIT_CERTIFICATES.get(certificate)
    if record is None:
        raise ValueError("Only a fresh A01-A16 certificate can be validated.")
    _validate_finalization_certificate_record(record, binding)


def _validate_finalization_certificate_record(
    certificate_record: _FinalizationAuditCertificateRecord,
    binding: Mapping[str, object],
) -> None:
    _require_executor_audit_context(
        certificate_record.context,
        trust_domain="production",
    )
    _require_authoritative_oracle_context(certificate_record.context)
    if binding.get("authorization_version") != FINALIZATION_AUTHORIZATION_VERSION:
        raise ValueError("Finalization authorization version differs from the frozen version.")
    if binding.get("lifecycle_phase") != "ready_to_promote_scientific_artifacts":
        raise ValueError("Finalization authorization has the wrong lifecycle phase.")
    if binding.get("audit_certificate_plan_sha256") != (certificate_record.plan_binding_sha256):
        raise ValueError("Finalization plan or profile differs from the audited certificate.")
    audited_prefinal_operational = certificate_record.context.prefinal_operational_provenance_sha256
    if (
        audited_prefinal_operational is None
        or binding.get("operational_provenance_sha256") != audited_prefinal_operational
    ):
        raise ValueError(
            "Finalization operational provenance differs from the A01-A16 audited prefinal set."
        )
    operational = binding.get("operational_provenance")
    if not isinstance(operational, Mapping):
        raise ValueError("Finalization binding lacks operational provenance.")
    for field, audited in (
        ("historical_before_sha256", certificate_record.context.historical_before),
        ("historical_after_sha256", certificate_record.context.historical_after),
    ):
        observed = operational.get(field)
        if not isinstance(observed, Mapping) or dict(observed) != dict(audited):
            raise ValueError(f"Finalization {field} differs from the A14-audited historical map.")


def consume_finalization_authorization(
    authorization: FinalizationAuthorization,
    binding: Mapping[str, object],
) -> ConsumedFinalizationAuthorization:
    """Atomically consume the exact registered capability before any disk promotion."""

    with _FINALIZATION_CAPABILITY_LOCK:
        record = _pop_finalization_authorization_record(authorization)
        _require_authoritative_oracle_evidence(
            record.oracle_conformance_result,
            record.oracle_evidence_binding,
        )
        observed = _authorization_binding_bytes(record.audit_results, binding)
        if observed != record.binding:
            raise ValueError("Finalization capability context does not match its sealed binding.")
        receipt = ConsumedFinalizationAuthorization(_CAPABILITY_CONSTRUCTION_KEY)
        _CONSUMED_FINALIZATION_AUTHORIZATIONS[receipt] = _FinalizationReceiptRecord(
            record.audit_results,
            record.binding,
            deepcopy(record.binding_payload),
            "authorization_consumed",
            "available",
            record.oracle_conformance_result,
            record.oracle_evidence_binding,
        )
    return receipt


def invalidate_unconsumed_finalization_authorization(
    authorization: FinalizationAuthorization,
) -> None:
    """Fail closed after exact-context construction rejects an issued capability."""

    _pop_finalization_authorization_record(authorization)


def _pop_finalization_authorization_record(
    authorization: FinalizationAuthorization,
) -> _FinalizationAuthorizationRecord:
    """Pop exactly one issued authorization while preserving forgery diagnostics."""

    if type(authorization) is not FinalizationAuthorization:
        raise ValueError("Finalization requires the exact issued capability object.")
    record = _ISSUED_FINALIZATION_AUTHORIZATIONS.pop(authorization, None)
    if record is None:
        raise ValueError("Finalization capability is forged, stale, copied, or already consumed.")
    return record


def finalization_receipt_audit_results(
    receipt: ConsumedFinalizationAuthorization,
    *,
    expected_phase: str,
) -> tuple[IntegrityAuditResult, ...]:
    """Return executed audits only for the exact internal receipt and phase."""

    with _FINALIZATION_CAPABILITY_LOCK:
        record = _finalization_receipt_record(receipt)
        if record.lifecycle_phase != expected_phase:
            raise ValueError(
                f"Finalization receipt phase is {record.lifecycle_phase!r}, not {expected_phase!r}."
            )
        return record.audit_results


def finalization_receipt_binding(
    receipt: ConsumedFinalizationAuthorization,
    *,
    expected_phase: str,
) -> dict[str, object]:
    """Return a defensive copy of the exact binding registered for one receipt phase."""

    with _FINALIZATION_CAPABILITY_LOCK:
        record = _finalization_receipt_record(receipt)
        if record.lifecycle_phase != expected_phase:
            raise ValueError(
                f"Finalization receipt phase is {record.lifecycle_phase!r}, not {expected_phase!r}."
            )
        if record.writer_state != "available":
            raise ValueError("Finalization receipt writer phase is stale or already claimed.")
        return deepcopy(record.binding_payload)


def claimed_finalization_receipt_binding(
    receipt: ConsumedFinalizationAuthorization,
    *,
    expected_phase: str,
) -> dict[str, object]:
    """Return binding evidence only while the exact lowest writer owns the phase."""

    with _FINALIZATION_CAPABILITY_LOCK:
        record = _finalization_receipt_record(receipt)
        if record.lifecycle_phase != expected_phase or record.writer_state != "claimed":
            raise ValueError("Finalization receipt writer was not exclusively claimed.")
        return deepcopy(record.binding_payload)


def claim_finalization_receipt_writer(
    receipt: ConsumedFinalizationAuthorization,
    *,
    expected_phase: str,
) -> None:
    """Consume one phase's writer permission immediately before filesystem mutation."""

    with _FINALIZATION_CAPABILITY_LOCK:
        record = _finalization_receipt_record(receipt)
        if record.lifecycle_phase != expected_phase or record.writer_state != "available":
            raise ValueError("Finalization receipt writer phase is stale or already claimed.")
        record.writer_state = "claimed"


def publish_finalization_receipt_writer(
    receipt: ConsumedFinalizationAuthorization,
    *,
    expected_phase: str,
) -> None:
    """Record that the claimed lowest writer completed atomic publication."""

    with _FINALIZATION_CAPABILITY_LOCK:
        record = _finalization_receipt_record(receipt)
        if record.lifecycle_phase != expected_phase or record.writer_state != "claimed":
            raise ValueError("Finalization receipt writer was not exclusively claimed.")
        record.writer_state = "published"


def advance_finalization_receipt(
    receipt: ConsumedFinalizationAuthorization,
    *,
    expected_phase: str,
    next_phase: str,
) -> None:
    """Advance one exact receipt through the forward-only filesystem lifecycle."""

    allowed = {
        "authorization_consumed": "scientific_artifacts_promoted",
        "scientific_artifacts_promoted": "manifest_persisted",
        "manifest_persisted": "recommendation_persisted",
    }
    if allowed.get(expected_phase) != next_phase:
        raise ValueError("Finalization receipt transition is not frozen.")
    with _FINALIZATION_CAPABILITY_LOCK:
        record = _finalization_receipt_record(receipt)
        if record.lifecycle_phase != expected_phase:
            raise ValueError("Finalization receipt is stale or in the wrong lifecycle phase.")
        if record.writer_state != "published":
            raise ValueError("Finalization receipt phase cannot advance before publication.")
        record.lifecycle_phase = next_phase
        record.writer_state = "available"


def complete_finalization_receipt(receipt: ConsumedFinalizationAuthorization) -> None:
    """Invalidate the internal receipt after recommendation persistence."""

    with _FINALIZATION_CAPABILITY_LOCK:
        record = _finalization_receipt_record(receipt)
        if record.lifecycle_phase != "recommendation_persisted":
            raise ValueError("Finalization cannot complete before recommendation persistence.")
        del _CONSUMED_FINALIZATION_AUTHORIZATIONS[receipt]


def invalidate_finalization_receipt(receipt: ConsumedFinalizationAuthorization) -> None:
    """Fail closed after any interrupted post-consumption lifecycle."""

    with _FINALIZATION_CAPABILITY_LOCK:
        _CONSUMED_FINALIZATION_AUTHORIZATIONS.pop(receipt, None)


def finalization_audit_results(
    certificate: FinalizationAuditCertificate,
) -> tuple[IntegrityAuditResult, ...]:
    """Expose immutable audit results without exposing issuance identity."""

    if type(certificate) is not FinalizationAuditCertificate:
        raise ValueError("A16 audit results require the exact issued certificate.")
    record = _ISSUED_FINALIZATION_AUDIT_CERTIFICATES.get(certificate)
    if record is None:
        raise ValueError("A16 audit certificate is stale or already sealed.")
    _require_authoritative_audit_results(record.audit_results, runs=record.context.runs)
    _require_authoritative_oracle_context(record.context)
    return record.audit_results


def invalidate_finalization_audit_certificate(
    certificate: FinalizationAuditCertificate,
) -> None:
    """Discard an unsealed certificate used only to validate an in-memory fixture."""

    record = _ISSUED_FINALIZATION_AUDIT_CERTIFICATES.pop(certificate, None)
    if record is not None:
        _discard_authoritative_audit_results(record.audit_results)


def _authorization_binding_bytes(
    audit_results: tuple[IntegrityAuditResult, ...],
    binding: Mapping[str, object],
) -> bytes:
    payload = {
        "binding": dict(binding),
        "audit_results": [
            {
                "audit_id": item.audit_id,
                "audit_order": item.audit_order,
                "requirement": item.requirement,
                "observed": item.observed,
                "status": item.status,
            }
            for item in audit_results
        ],
    }
    return canonical_json_bytes(payload, final_lf=True)


def _finalization_receipt_record(
    receipt: ConsumedFinalizationAuthorization,
) -> _FinalizationReceiptRecord:
    if type(receipt) is not ConsumedFinalizationAuthorization:
        raise ValueError("Finalization requires the exact consumed receipt object.")
    record = _CONSUMED_FINALIZATION_AUTHORIZATIONS.get(receipt)
    if record is None:
        raise ValueError("Finalization receipt is forged, stale, copied, or completed.")
    _require_authoritative_oracle_evidence(
        record.oracle_conformance_result,
        record.oracle_evidence_binding,
    )
    return record


def _run_selected_audits(
    context: IntegrityAuditContext,
    *,
    audit_ids: tuple[str, ...],
) -> tuple[IntegrityAuditResult, ...]:
    snapshot = load_protocol_snapshot()
    registry = {row["audit_id"]: row for row in snapshot.registry("audit").records()}
    results: list[IntegrityAuditResult] = []
    for audit_id in audit_ids:
        row = registry[audit_id]
        try:
            observation = evaluate_audit(audit_id, context, snapshot=snapshot)
        except Exception as error:
            observation = AuditObservation("FAIL", f"{type(error).__name__}: {error}")
        results.append(
            IntegrityAuditResult(
                audit_id=audit_id,
                audit_order=int(row["audit_order"]),
                requirement=row["requirement"],
                observed=observation.detail,
                status=observation.status,
            )
        )
    return tuple(results)


def _run_fixture_selected_audits(
    context: IntegrityAuditContext,
    *,
    audit_ids: tuple[str, ...],
    oracle_fixture_evidence: OracleFixtureEvidence,
) -> tuple[FixtureAuditDiagnostic, ...]:
    """Execute bounded diagnostics without constructing authoritative result objects."""

    _require_fixture_audit_context(context, oracle_fixture_evidence)
    snapshot = load_protocol_snapshot()
    registry = {row["audit_id"]: row for row in snapshot.registry("audit").records()}
    diagnostics: list[FixtureAuditDiagnostic] = []
    for audit_id in audit_ids:
        row = registry[audit_id]
        try:
            if audit_id == "A04-ORACLE-ISOLATION":
                observation = _audit_oracle_fixture(
                    context,
                    snapshot,
                    oracle_fixture_evidence,
                )
            else:
                observation = evaluate_audit(audit_id, context, snapshot=snapshot)
        except Exception as error:
            observation = AuditObservation("FAIL", f"{type(error).__name__}: {error}")
        diagnostics.append(
            FixtureAuditDiagnostic(
                audit_id=audit_id,
                audit_order=int(row["audit_order"]),
                requirement=row["requirement"],
                observed=observation.detail,
                status=observation.status,
            )
        )
    return tuple(diagnostics)


def run_smoke_audits(context: SmokeAuditContext) -> tuple[SmokeAuditResult, ...]:
    return run_integrity_audits(context)


def evaluate_audit(
    audit_id: str,
    context: IntegrityAuditContext,
    *,
    snapshot: ProtocolSnapshot | None = None,
) -> AuditObservation:
    protocol = snapshot or load_protocol_snapshot()
    try:
        check = AUDIT_EXECUTORS[audit_id]
    except KeyError as error:
        raise ValueError(f"No executable audit owner exists for {audit_id}.") from error
    return check(context, protocol)


def _audit_seeds(_: IntegrityAuditContext, __: ProtocolSnapshot) -> AuditObservation:
    expected_digest = "28ee6854626047a99bd2e1538d200aabccd89a0d77870db011d7aa0d0b4f6093"
    observed_digest = hashlib.sha256(canonical_json_bytes(list(FULL_SEEDS))).hexdigest()
    if (
        tuple(range(1000, 1128)) != FULL_SEEDS
        or tuple(range(9000, 9004)) != SMOKE_SEEDS
        or len(set(FULL_SEEDS)) != 128
        or len(set(SMOKE_SEEDS)) != 4
        or set(FULL_SEEDS).intersection(SMOKE_SEEDS)
        or set(FULL_SEEDS).intersection(range(100))
        or observed_digest != expected_digest
    ):
        return AuditObservation("FAIL", "Seed schedule, separation, or digest differs.")
    return AuditObservation("PASS", "PASS")


def _audit_worlds(_: IntegrityAuditContext, __: ProtocolSnapshot) -> AuditObservation:
    validate_worlds()
    FrozenStudyOrchestrator().validate_population_shape()
    return AuditObservation("PASS", "PASS")


def _audit_truth_isolation(_: IntegrityAuditContext, __: ProtocolSnapshot) -> AuditObservation:
    public_fields = set(PublicWorldDefinition.__dataclass_fields__)
    forbidden = {"hidden", "truth", "effect_size", "group_sigmas", "scientific_hypothesis_id"}
    methods = {
        name
        for name, value in inspect.getmembers(SelectedObservationInterface)
        if callable(value) and not name.startswith("_")
    }
    if public_fields.intersection(forbidden) or methods != {"observe_selected"}:
        return AuditObservation("FAIL", "Policy-facing public types expose evaluator capability.")
    return AuditObservation("PASS", "PASS")


def _audit_oracle(context: IntegrityAuditContext, _: ProtocolSnapshot) -> AuditObservation:
    result = context.oracle_conformance_result
    binding = context.oracle_evidence_binding
    if result is None or binding is None:
        return AuditObservation(
            "FAIL",
            "Exact Oracle conformance result and evidence binding are required.",
        )
    try:
        validate_oracle_conformance_result(result, binding=binding)
    except OracleError as error:
        return AuditObservation("FAIL", f"Oracle conformance evidence was rejected: {error}")
    methods = {
        name
        for name, value in inspect.getmembers(SelectedObservationInterface)
        if callable(value) and not name.startswith("_")
    }
    if methods != {"observe_selected"}:
        return AuditObservation("FAIL", "Selected-only interface exposes another capability.")
    return AuditObservation("PASS", "PASS")


def _require_fixture_audit_context(
    context: IntegrityAuditContext,
    evidence: OracleFixtureEvidence,
) -> OracleFixtureEvidence:
    validated = _validate_oracle_fixture_evidence(evidence)
    if (
        context.oracle_conformance_result is not None
        or context.oracle_evidence_binding is not None
        or context.oracle_fixture_result is not validated.result
        or context.oracle_fixture_binding is not validated.binding
    ):
        raise OracleError("Fixture audit context differs from its exact Oracle capability.")
    return validated


def _audit_oracle_fixture(
    context: IntegrityAuditContext,
    _: ProtocolSnapshot,
    evidence: OracleFixtureEvidence,
) -> AuditObservation:
    """Validate bounded test evidence without changing production A04 authority."""

    try:
        _require_fixture_audit_context(context, evidence)
    except OracleError as error:
        return AuditObservation("FAIL", f"Fixture Oracle evidence was rejected: {error}")
    methods = {
        name
        for name, value in inspect.getmembers(SelectedObservationInterface)
        if callable(value) and not name.startswith("_")
    }
    if methods != {"observe_selected"}:
        return AuditObservation("FAIL", "Selected-only interface exposes another capability.")
    return AuditObservation("PASS", "PASS")


def _audit_common_randomness(
    context: IntegrityAuditContext, _: ProtocolSnapshot
) -> AuditObservation:
    expected: list[tuple[str, str, str, str, tuple[str, ...], RevealedObservation | None]] = []
    for run in context.runs:
        for action in run.actions:
            definition = CANDIDATES_BY_ID[action.candidate_id]
            if definition.role == "setup":
                if action.oracle_observation is not None:
                    return AuditObservation("FAIL", "A setup action produced an observation.")
                continue
            expected_key = decision_key(
                world_id=run.world_id,
                seed=run.seed,
                candidate_id=action.candidate_id,
                replication_id=definition.replication_id,
            )
            expected.append(
                (
                    run.run_id,
                    action.decision_id,
                    "decision",
                    action.candidate_id,
                    expected_key,
                    action.oracle_observation,
                )
            )
        try:
            selections = validated_calibration_history_selections(run)
        except RunProvenanceError as error:
            return AuditObservation("FAIL", str(error))
        for selection in selections:
            group_index = int(selection.comparison_group_id[-2:])
            prefix_id = (
                f"calibration-prefix/{run.world_id}/{run.seed}/{selection.comparison_group_id}"
            )
            for observation in selection.observations:
                replication_index = int(observation.candidate_id.rsplit("r", 1)[1])
                arm_name = cast(str, observation.intervention_arm)
                candidate_id = f"cal-{group_index:02d}-{arm_name}-r{replication_index:04d}"
                source_id = f"{prefix_id}/{candidate_id}"
                expected_key = calibration_key(
                    world_id=run.world_id,
                    seed=run.seed,
                    comparison_group_id=selection.comparison_group_id,
                    intervention_arm=arm_name,
                    replication_id=observation.replication_id,
                )
                expected.append(
                    (
                        run.run_id,
                        source_id,
                        "calibration",
                        candidate_id,
                        expected_key,
                        observation,
                    )
                )

    if not expected:
        return AuditObservation("INCONCLUSIVE", "No expected selected observations were supplied.")
    key_identity: dict[str, tuple[str, ...]] = {}
    oracle_use_ids: set[str] = set()
    by_public_key: dict[tuple[str, ...], list[tuple[str, str, float, str, str]]] = defaultdict(list)
    for run_id, source_id, kind, candidate_id, expected_key, revealed in expected:
        if revealed is None:
            return AuditObservation(
                "FAIL", "A selected action is missing its required observation."
            )
        expected_authorization = authorize_observation(
            run_id=run_id,
            source_id=source_id,
            candidate_id=candidate_id,
            kind=kind,
        )
        expected_key_id = runtime_id(
            "oracle-key", "oracle_key_id/v1", {"key_fields": list(expected_key)}
        )
        expected_use_id = f"oracle-use/{expected_authorization.authorization_id}/{expected_key_id}"
        expected_namespace = DECISION_NAMESPACE if kind == "decision" else CALIBRATION_NAMESPACE
        if (
            revealed.authorization_id != expected_authorization.authorization_id
            or revealed.candidate_id != candidate_id
            or revealed.oracle_key_id != expected_key_id
            or revealed.oracle_use_id != expected_use_id
            or revealed.key_fields != expected_key
            or revealed.namespace != expected_namespace
            or revealed.world_id != expected_key[3]
            or revealed.seed != int(expected_key[4])
        ):
            return AuditObservation(
                "FAIL", "An observation does not match its selected action authorization and key."
            )
        prior = key_identity.setdefault(revealed.oracle_key_id, expected_key)
        if prior != expected_key:
            return AuditObservation("FAIL", "One oracle key was reused across public outcomes.")
        if revealed.oracle_use_id in oracle_use_ids:
            return AuditObservation("FAIL", "One oracle use was shared across real actions.")
        oracle_use_ids.add(revealed.oracle_use_id)
        by_public_key[expected_key].append(
            (
                run_id,
                source_id,
                revealed.revealed_observation,
                revealed.digest,
                revealed.oracle_key_id,
            )
        )
    shared_groups = 0
    for values in by_public_key.values():
        owners = {(run_id, source) for run_id, source, *_ in values}
        outcomes = {(observed, digest, key_id) for _, _, observed, digest, key_id in values}
        if len(values) != len(owners):
            return AuditObservation(
                "FAIL", "One arm/budget owner revealed the same public outcome more than once."
            )
        if len(owners) > 1:
            shared_groups += 1
            if len(outcomes) != 1:
                return AuditObservation("FAIL", "Common-randomness outcomes differ across owners.")
    expected_shared = sum(len(values) > 1 for values in by_public_key.values())
    if shared_groups != expected_shared or shared_groups == 0:
        return AuditObservation("FAIL", "No required cross-arm/budget shared outcome was observed.")
    if context.artifact_graph is not None:
        validate_available_artifact_graph(context.artifact_graph)
    return AuditObservation("PASS", f"PASS ({shared_groups} shared public outcome groups)")


def _audit_determinism(context: IntegrityAuditContext, _: ProtocolSnapshot) -> AuditObservation:
    if not context.replay_runs:
        return AuditObservation("INCONCLUSIVE", "Independent replay population was not supplied.")
    try:
        primary, replay = _require_executor_audit_context(
            context,
            trust_domain=_executor_trust_domain_for_context(context),
        )
        first_payload, replay_payload = _require_deterministic_audit_payloads(
            context,
            primary,
            replay,
        )
    except (ExecutorProvenanceError, ValueError) as error:
        return AuditObservation(
            "FAIL",
            f"Independent executor evidence was rejected: {error}",
        )
    if first_payload != replay_payload:
        return AuditObservation("FAIL", "Independent scientific payload replay differs.")
    if len(context.runs) != len(context.replay_runs):
        return AuditObservation("FAIL", "Replay trajectory count differs.")
    if set(map(id, context.runs)).intersection(map(id, context.replay_runs)):
        return AuditObservation("FAIL", "Replay reused an in-memory trajectory object.")
    return AuditObservation("PASS", "PASS")


def _audit_arm_isolation(context: IntegrityAuditContext, _: ProtocolSnapshot) -> AuditObservation:
    if not context.runs:
        return AuditObservation("INCONCLUSIVE", "No arm histories were supplied.")
    run_ids: set[str] = set()
    lineage_ids: set[str] = set()
    owned_ids: dict[str, str] = {}
    object_owners: dict[int, tuple[str, str]] = {}
    for run in context.runs:
        if run.run_id in run_ids or run.lineage.lineage_id in lineage_ids:
            return AuditObservation("FAIL", "Run or lineage identity crosses arms.")
        run_ids.add(run.run_id)
        lineage_ids.add(run.lineage.lineage_id)
        validate_lineage_binding(lineage=run.lineage, arm=run.arm, run_id=run.run_id)
        owned_roots = {
            "lineage": run.lineage,
            "decisions": run.decisions,
            "actions": run.actions,
            "completed_experiments": run.completed_experiments,
            "evidence": run.evidence,
            "updates": run.updates,
            "diagnostics": run.diagnostics,
            "effect_history": run.effect_history,
            "calibration": run.calibration,
        }
        local_seen: set[int] = set()
        for root_name, owned_object in owned_roots.items():
            for identity, path in _owned_identity_objects(
                owned_object, path=root_name, local_seen=local_seen
            ):
                previous = object_owners.setdefault(identity, (run.run_id, path))
                if previous[0] != run.run_id:
                    return AuditObservation(
                        "FAIL",
                        "Two arms share an owned nested object: "
                        f"{previous[0]}:{previous[1]} and {run.run_id}:{path}.",
                    )
        identifiers = [decision.decision_id for decision in run.decisions]
        identifiers += [evidence.evidence_id for evidence in run.evidence]
        identifiers += [update.model_update_id for update in run.updates]
        identifiers += [
            action.oracle_observation.oracle_use_id
            for action in run.actions
            if action.oracle_observation is not None
        ]
        identifiers += [
            action.oracle_observation.authorization_id
            for action in run.actions
            if action.oracle_observation is not None
        ]
        identifiers += [
            state_id
            for update in run.updates
            for state_id in (
                update.state_before.state.belief_state_id,
                update.posterior_state.state.belief_state_id,
            )
        ]
        identifiers.append(run.lineage.current_state.state.belief_state_id)
        for identifier in identifiers:
            previous_run_id = owned_ids.setdefault(identifier, run.run_id)
            if previous_run_id != run.run_id:
                return AuditObservation("FAIL", "A scientific/provenance ID crosses arm histories.")
        if any(
            not item.decision_id.startswith(f"decision/{run.run_id}/") for item in run.decisions
        ):
            return AuditObservation("FAIL", "Decision identity belongs to another run.")
        lineage_state_ids = {run.lineage.current_state.state.belief_state_id}
        lineage_state_ids.update(
            state_id
            for update in run.updates
            for state_id in (
                update.state_before.state.belief_state_id,
                update.posterior_state.state.belief_state_id,
            )
        )
        if any(item.belief_state_id not in lineage_state_ids for item in run.decisions):
            return AuditObservation("FAIL", "Decision belief state crosses its run lineage.")
        if any(action.decision_id not in identifiers for action in run.actions):
            return AuditObservation("FAIL", "Action references a foreign decision.")
        completed_ids = {item.record_id for item in run.completed_experiments}
        for evidence in run.evidence:
            if not set(evidence.source_experiment_ids).issubset(completed_ids):
                return AuditObservation("FAIL", "Evidence references another arm's experiment.")
        if any(update.lineage_id != run.lineage.lineage_id for update in run.updates):
            return AuditObservation("FAIL", "Belief update belongs to another lineage.")
    if context.artifact_graph is not None:
        validate_available_artifact_graph(context.artifact_graph)
        artifact_owners: dict[int, str] = {}
        for filename in ("arm_runs.jsonl", "trajectory_events.jsonl"):
            rows = cast_rows(context.artifact_graph.artifact(filename).scientific)
            for row in rows:
                owner = cast(
                    str,
                    row["run_id"]
                    if filename == "arm_runs.jsonl"
                    else cast(dict[str, object], row["event_payload"])["run_id"],
                )
                for identity, path in _owned_identity_objects(
                    row, path=f"{filename}/{owner}", local_seen=set()
                ):
                    previous_artifact_owner = artifact_owners.setdefault(identity, owner)
                    if previous_artifact_owner != owner:
                        return AuditObservation(
                            "FAIL", f"Canonical nested payload crosses run owners at {path}."
                        )
    return AuditObservation("PASS", "PASS")


def _owned_identity_objects(
    value: object, *, path: str, local_seen: set[int]
) -> tuple[tuple[int, str], ...]:
    """Return recursively owned identities, excluding frozen globally shared values."""

    if value is None or isinstance(value, (str, bytes, int, float, bool, Enum)):
        return ()
    if isinstance(value, (Candidate, FrozenArm, PublicExperimentDesign)):
        return ()
    if isinstance(value, (Mapping, Sequence)) and len(value) == 0:
        return ()
    if isinstance(value, tuple) and _is_deeply_immutable_tuple(value):
        return ()
    identity = id(value)
    if identity in local_seen:
        return ()
    local_seen.add(identity)
    found: list[tuple[int, str]] = [(identity, path)]
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            found.extend(
                _owned_identity_objects(
                    getattr(value, field.name),
                    path=f"{path}.{field.name}",
                    local_seen=local_seen,
                )
            )
    elif isinstance(value, Mapping):
        for key, item in value.items():
            found.extend(
                _owned_identity_objects(item, path=f"{path}[{key!r}]", local_seen=local_seen)
            )
    elif isinstance(value, Sequence):
        for index, item in enumerate(value):
            found.extend(
                _owned_identity_objects(item, path=f"{path}[{index}]", local_seen=local_seen)
            )
    return tuple(found)


def _is_deeply_immutable_tuple(value: tuple[object, ...]) -> bool:
    return all(
        isinstance(item, (str, bytes, int, float, bool, Enum))
        or (isinstance(item, tuple) and _is_deeply_immutable_tuple(item))
        for item in value
    )


def _audit_calibration(context: IntegrityAuditContext, _: ProtocolSnapshot) -> AuditObservation:
    if not context.runs:
        return AuditObservation("INCONCLUSIVE", "No calibration lineages were supplied.")
    prior = (
        ("optimizer.adam-advantage", 1.0 / 3.0),
        ("optimizer.no-consistent-advantage", 1.0 / 3.0),
        ("optimizer.sgd-advantage", 1.0 / 3.0),
    )
    for run in context.runs:
        try:
            validate_recorded_calibration(run)
        except RunProvenanceError as error:
            return AuditObservation("FAIL", str(error))
        if run.initial_probabilities != prior:
            return AuditObservation("FAIL", "Calibration changed the scientific prior.")
        scientific_evidence_ids = set(run.lineage.current_state.state.evidence_ids)
        if run.arm.belief_model_id == "fixed_sigma_gaussian":
            if run.calibration is not None or run.calibration_cost != 0.0:
                return AuditObservation("FAIL", "Fixed arm consumed calibration.")
        else:
            calibration = run.calibration
            if (
                calibration is None
                or len(calibration.estimates) != 3
                or len(calibration.effects) != 15
                or len(calibration.observations) != 30
            ):
                return AuditObservation("FAIL", "Calibrated arm prefix structure differs.")
            prefix_effect_ids = {item.effect_id for item in calibration.effects}
            if prefix_effect_ids.intersection(scientific_evidence_ids):
                return AuditObservation(
                    "FAIL", "Calibration effect entered scientific belief evidence."
                )
    return AuditObservation("PASS", "PASS")


def _audit_planner_and_evidence(
    context: IntegrityAuditContext, _: ProtocolSnapshot
) -> AuditObservation:
    if not context.runs:
        return AuditObservation("INCONCLUSIVE", "No planner/evidence traces were supplied.")
    for run in context.runs:
        try:
            replay_decisions(run)
        except RunProvenanceError as error:
            return AuditObservation("FAIL", str(error))
        if run.arm.belief_model_id == "fixed_sigma_gaussian" and not all(
            item.fixed_policy_regression_match for item in run.decisions
        ):
            return AuditObservation(
                "FAIL", "Frozen fixed-policy replay differs from adapter output."
            )
        if any(
            action.role == "setup" and action.oracle_observation is not None
            for action in run.actions
        ):
            return AuditObservation("FAIL", "A setup action invoked the observation oracle.")
        source_pairs = tuple(item.source_experiment_ids for item in run.evidence)
        if len(source_pairs) != len(set(source_pairs)):
            return AuditObservation("FAIL", "A matched pair generated duplicate evidence.")
        completed = {item.record_id for item in run.completed_experiments}
        if any(not set(pair).issubset(completed) for pair in source_pairs):
            return AuditObservation(
                "FAIL", "Evidence source pair is not in real completed history."
            )
        if len(run.updates) != len(run.evidence):
            return AuditObservation("FAIL", "Belief-update/evidence chronology differs.")
    if context.analysis is not None:
        from research_decision_engine.benchmarks.broader_analysis import classify_truth_free

        for item in context.analysis.comparisons:
            expected = classify_truth_free(item.paired.fixed_run, item.paired.calibrated_run)
            if expected != item.truth_free:
                return AuditObservation(
                    "FAIL", "In-memory truth-free mechanism classification differs from replay."
                )
    if context.artifact_graph is None and context.analysis is None:
        return AuditObservation(
            "INCONCLUSIVE",
            "Local planner/evidence checks passed; canonical truth-free classification was absent.",
        )
    if context.artifact_graph is None:
        return AuditObservation("PASS", "PASS")
    validate_available_artifact_graph(context.artifact_graph)
    from research_decision_engine.benchmarks.broader_analysis import classify_truth_free
    from research_decision_engine.benchmarks.broader_projection import _events_for_run

    graph_comparisons = {
        cast(str, row["comparison_id"]): row
        for row in cast_rows(context.artifact_graph.artifact("comparisons.jsonl").scientific)
    }
    graph_events = {
        cast(str, cast(dict[str, object], row["event_payload"])["event_id"]): row
        for row in cast_rows(context.artifact_graph.artifact("trajectory_events.jsonl").scientific)
    }
    grouped: dict[str, list[BroaderArmRun]] = defaultdict(list)
    for run in context.runs:
        grouped[run.comparison_id].append(run)
        for expected_event in _events_for_run(run):
            expected_payload = cast(dict[str, object], expected_event["event_payload"])
            if expected_payload["event_type"] != "decision":
                continue
            observed = graph_events.get(cast(str, expected_payload["event_id"]))
            if observed != expected_event:
                return AuditObservation(
                    "FAIL", "Canonical decision score, ranking, or selection differs from replay."
                )
    for comparison_id, pair in grouped.items():
        if len(pair) != 2:
            return AuditObservation("FAIL", "A comparison lacks two isolated arm histories.")
        fixed = next(item for item in pair if item.arm.arm_id.startswith("fixed_"))
        calibrated = next(item for item in pair if item.arm.arm_id.startswith("calibrated_"))
        expected = classify_truth_free(fixed, calibrated)
        observed = graph_comparisons[comparison_id]
        if expected is None:
            if observed["record_type"] != "nondivergent":
                return AuditObservation("FAIL", "Stored divergence label disagrees with replay.")
            continue
        expected_predicates = dict(expected.predicate_results)
        observed_fixed_belief = cast(
            dict[str, object],
            cast(dict[str, object], observed["pre_divergence_fixed_belief"])["probabilities"],
        )
        observed_calibrated_belief = cast(
            dict[str, object],
            cast(dict[str, object], observed["pre_divergence_calibrated_belief"])["probabilities"],
        )
        if (
            observed["record_type"] != "divergent"
            or observed["first_divergence_step"] != expected.first_divergence_step
            or observed["fixed_candidate_id"] != expected.fixed_candidate_id
            or observed["calibrated_candidate_id"] != expected.calibrated_candidate_id
            or observed["sequence_class"] != expected.sequence_class
            or observed["predicate_results"] != expected_predicates
            or observed["primary_mechanism_id"] != expected.primary_mechanism_id
            or tuple(cast(list[str], observed["contributing_mechanism_ids"]))
            != expected.contributing_mechanism_ids
            or observed["mechanism_row_without_outcome_sha256"]
            != expected.mechanism_row_without_outcome_sha256
            or {key: _audit_f64(value) for key, value in observed_fixed_belief.items()}
            != dict(expected.pre_divergence_fixed_belief)
            or {key: _audit_f64(value) for key, value in observed_calibrated_belief.items()}
            != dict(expected.pre_divergence_calibrated_belief)
        ):
            return AuditObservation(
                "FAIL", "Truth-free mechanism provenance disagrees with crossed replay."
            )
    return AuditObservation("PASS", "PASS")


def _audit_f64(value: object) -> float:
    if not isinstance(value, str) or not value.startswith("f64:"):
        raise ValueError("Expected canonical f64 value.")
    import struct

    return cast(float, struct.unpack(">d", bytes.fromhex(value[4:]))[0])


def _audit_costs(context: IntegrityAuditContext, _: ProtocolSnapshot) -> AuditObservation:
    if not context.runs:
        return AuditObservation("INCONCLUSIVE", "No cost ledgers were supplied.")
    for run in context.runs:
        decision_cost = math.fsum(item.cost for item in run.actions)
        calibration_cost = run.calibration.cost if run.calibration is not None else 0.0
        if not math.isclose(run.decision_cost, decision_cost, abs_tol=1e-12):
            return AuditObservation("FAIL", "Decision cost does not reconcile chronologically.")
        if not math.isclose(run.calibration_cost, calibration_cost, abs_tol=1e-12):
            return AuditObservation("FAIL", "Calibration cost does not reconcile.")
        if run.decision_cost > run.budget + 1e-12:
            return AuditObservation("FAIL", "Decision budget was exceeded.")
        physical_share = (
            run.decision_cost + run.calibration_cost / 6.0
            if run.arm.arm_id.startswith("calibrated_")
            else run.decision_cost
        )
        if not math.isfinite(physical_share):
            return AuditObservation("FAIL", "Physical cost share is nonfinite.")
    if context.artifact_graph is None:
        if context.analysis is not None:
            return AuditObservation("PASS", "PASS")
        return AuditObservation(
            "INCONCLUSIVE", "In-memory ledgers passed; canonical cost fields were not supplied."
        )
    validate_available_artifact_graph(context.artifact_graph)
    return AuditObservation("PASS", "PASS")


def _audit_source_freeze(_: IntegrityAuditContext, __: ProtocolSnapshot) -> AuditObservation:
    root = repository_root()
    for relative, expected in PROTECTED_HASHES.items():
        observed = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        if observed != expected:
            return AuditObservation("FAIL", f"Protected source changed: {relative}")
    return AuditObservation("PASS", "PASS")


def _audit_matrix(context: IntegrityAuditContext, _: ProtocolSnapshot) -> AuditObservation:
    if (
        context.scope == "conformance"
        and context.analysis is not None
        and context.profile is not None
    ):
        unique_selections: dict[str, CalibrationHistorySelection] = {}
        selection_identities: dict[str, str] = {}
        try:
            for run in context.runs:
                for selection in validated_calibration_history_selections(run):
                    prefix_id = (
                        f"calibration-prefix/{run.world_id}/{run.seed}/"
                        f"{selection.comparison_group_id}"
                    )
                    prior_identity = selection_identities.setdefault(
                        prefix_id, selection.selection_identity
                    )
                    if prior_identity != selection.selection_identity:
                        return AuditObservation(
                            "FAIL", "Shared calibration prefix has inconsistent selection identity."
                        )
                    unique_selections.setdefault(prefix_id, selection)
        except RunProvenanceError as error:
            return AuditObservation("FAIL", str(error))
        calibration_estimates = len(unique_selections)
        effects = sum(len(item.effects) for item in unique_selections.values())
        observations = sum(len(item.observations) for item in unique_selections.values())
        if (
            len(context.runs) != context.profile.arm_runs
            or len(context.analysis.comparisons) != context.profile.comparisons
            or calibration_estimates != context.profile.calibration_estimates
            or effects != calibration_estimates * 5
            or observations != calibration_estimates * 10
        ):
            return AuditObservation("FAIL", "Conformance population does not reconcile.")
        return AuditObservation("PASS", "PASS (declared non-scientific conformance profile)")
    if context.scope != "full" or context.artifact_graph is None:
        return AuditObservation(
            "INCONCLUSIVE",
            f"Supplied population has {len(context.runs)} runs; full 36,864-run matrix absent.",
        )
    graph = context.artifact_graph
    counts = {
        item.contract.filename: len(cast_rows(item.scientific))
        for item in graph.artifacts
        if item.contract.format in {"JSONL", "CSV"}
    }
    if (
        counts.get("arm_runs.jsonl") != 36_864
        or counts.get("comparisons.jsonl") != 18_432
        or counts.get("calibration_estimates.jsonl") != 9_216
    ):
        return AuditObservation("FAIL", "Actual canonical study matrix counts differ.")
    calibration_rows = cast_rows(graph.artifact("calibration_estimates.jsonl").scientific)
    effects = sum(len(cast_list(row["effect_ids"])) for row in calibration_rows)
    observations = sum(len(cast_list(row["source_oracle_key_ids"])) for row in calibration_rows)
    if effects != 46_080 or observations != 92_160:
        return AuditObservation("FAIL", "Calibration effect/observation counts differ.")
    return AuditObservation("PASS", "PASS")


def _audit_registries(
    context: IntegrityAuditContext, snapshot: ProtocolSnapshot
) -> AuditObservation:
    snapshot.validate()
    assert_executor_completeness()
    if len(artifact_contracts(snapshot)) != 13:
        return AuditObservation("FAIL", "Artifact contract registry count differs.")
    if context.artifact_graph is None:
        return AuditObservation(
            "INCONCLUSIVE", "Literal registries/executors passed; relational artifacts absent."
        )
    validate_available_artifact_graph(context.artifact_graph)
    return AuditObservation("PASS", "PASS")


def _audit_historical(context: IntegrityAuditContext, _: ProtocolSnapshot) -> AuditObservation:
    if not context.historical_before or not context.historical_after:
        return AuditObservation("INCONCLUSIVE", "Historical before/after maps were not supplied.")
    if context.historical_before != context.historical_after:
        return AuditObservation("FAIL", "Frozen historical artifact universe changed.")
    return AuditObservation("PASS", "PASS")


def _audit_resampling(context: IntegrityAuditContext, _: ProtocolSnapshot) -> AuditObservation:
    FrozenAnalysisOrchestrator().validate_declared_counts()
    if context.analysis is not None:
        contrasts = {item.contrast_id: item for item in context.analysis.contrasts}
        for bootstrap_item in context.analysis.bootstrap_rows:
            contrast = contrasts[bootstrap_item.contrast_id]
            if contrast.dataset is None:
                return AuditObservation("FAIL", "Bootstrap contrast lacks its raw dataset.")
            estimand = ResamplingEstimand(contrast.estimand_id, contrast.dataset)
            if bootstrap_item != bootstrap_replicate(
                bootstrap_item.contrast_id,
                bootstrap_item.replicate_index,
                estimand.evaluate_bootstrap,
            ):
                return AuditObservation("FAIL", "A bootstrap row failed exact recomputation.")
        for sign_item in context.analysis.sign_flip_rows:
            contrast = contrasts[sign_item.contrast_id]
            if contrast.dataset is None:
                return AuditObservation("FAIL", "Sign-flip contrast lacks its raw dataset.")
            estimand = ResamplingEstimand(contrast.estimand_id, contrast.dataset)
            if sign_item != sign_flip_replicate(
                sign_item.contrast_id,
                sign_item.replicate_index,
                contrast.estimate if contrast.estimate is not None else 0.0,
                estimand.evaluate_sign_flip,
            ):
                return AuditObservation("FAIL", "A sign-flip row failed exact recomputation.")
        hypothesis_ids = (
            load_protocol_snapshot()
            .registry("statistical_hypothesis")
            .ids("statistical_hypothesis_id")
        )
        by_hypothesis = {
            item.statistical_hypothesis_id: item
            for item in context.analysis.contrasts
            if item.holm_member and item.statistical_hypothesis_id is not None
        }
        expected_holm = holm_64(
            tuple(
                HolmInput(
                    hypothesis_id,
                    by_hypothesis[hypothesis_id].p_raw,
                    by_hypothesis[hypothesis_id].p_raw is not None,
                )
                for hypothesis_id in hypothesis_ids
            )
        )
        if expected_holm != context.analysis.holm_results:
            return AuditObservation("FAIL", "HOLM-64 failed complete recomputation.")
        if context.scope == "conformance":
            return AuditObservation("PASS", "PASS (every supplied conformance resample)")
    if context.artifact_graph is None:
        return AuditObservation(
            "INCONCLUSIVE", "No resampling and Holm artifact graph was supplied."
        )
    validate_available_artifact_graph(context.artifact_graph)
    rows = cast_rows(context.artifact_graph.artifact("resampling_audit.jsonl").scientific)
    if context.scope != "full" or len(rows) != 1_300_000:
        return AuditObservation(
            "INCONCLUSIVE",
            f"All {len(rows)} supplied rows reproduce; full 1,300,000-row input is absent.",
        )
    return AuditObservation("PASS", "PASS")


def _audit_finalization(context: IntegrityAuditContext, _: ProtocolSnapshot) -> AuditObservation:
    _validate_decision_truth_table()
    if context.analysis is None:
        return AuditObservation(
            "INCONCLUSIVE", "Decision truth table passed; provisional canonical decision absent."
        )
    from research_decision_engine.benchmarks.broader_analysis import (
        ProductionAnalysisResult,
        recompute_provisional_decision,
    )

    if not isinstance(context.analysis, ProductionAnalysisResult):
        return AuditObservation(
            "INCONCLUSIVE", "A16 cannot run before provisional gate derivation."
        )
    if recompute_provisional_decision(context.analysis) != context.analysis.decision:
        return AuditObservation("FAIL", "Provisional A/B/C/D decision did not reproduce.")
    return AuditObservation("PASS", "PASS")


def _validate_decision_truth_table() -> None:
    statuses = tuple(GateStatus)
    for g_b in statuses:
        for b_status in statuses:
            for veto_status in statuses:
                for change_status in statuses:
                    for ppo_status in statuses:
                        result = final_decision(
                            g_b_authorization=g_b,
                            b_authorization=DecisionBoolean.from_status(b_status),
                            veto_complete=DecisionBoolean.from_status(veto_status),
                            controller_change_needed=DecisionBoolean.from_status(change_status),
                            ppo_eligible=DecisionBoolean.from_status(ppo_status),
                        )
                        if g_b is not b_status:
                            if result.gate_status is not GateStatus.FAIL:
                                raise ValueError(
                                    "G-B/B authorization mismatch did not fail G-FINAL."
                                )
                            continue
                        if (
                            g_b is GateStatus.PASS
                            and b_status is GateStatus.PASS
                            and veto_status is GateStatus.PASS
                        ):
                            expected = "BRANCH-B"
                        elif change_status is GateStatus.PASS and b_status in {
                            GateStatus.FAIL,
                            GateStatus.INCONCLUSIVE,
                        }:
                            expected = "BRANCH-C"
                        elif change_status is GateStatus.FAIL and ppo_status is GateStatus.PASS:
                            expected = "BRANCH-D"
                        else:
                            expected = "BRANCH-A"
                        if (
                            result.branch_id != expected
                            or result.gate_status is not GateStatus.PASS
                        ):
                            raise ValueError("F-DECISION-TABLE truth table differs.")
    action = ActionTuple("IG", "SCORE_FLATTENING", "BR-J001", "BR-C023")
    partition = partition_action_tuples((action,), (VetoResult(action, "INCONCLUSIVE"),))
    unique = unique_actionable_mechanism(partition)
    authorization = b_authorized(
        controller_change_needed=DecisionBoolean.from_status(GateStatus.PASS),
        actionability_complete=DecisionBoolean.from_status(GateStatus.PASS),
        partition=partition,
        unique_mechanism=unique,
    )
    if authorization.status is not GateStatus.INCONCLUSIVE:
        raise ValueError("F-B-AUTHORIZATION masked an unresolved veto.")
    terminal_reason_for((), (), integrity_failure=False)
    terminal_reason_for(("candidate",), (), integrity_failure=False)
    terminal_reason_for(("candidate",), (), integrity_failure=True)


def cast_rows(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, tuple) or not all(isinstance(item, dict) for item in value):
        raise ValueError("Expected decoded canonical rows.")
    return value


def cast_list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Expected canonical list.")
    return value


AUDIT_EXECUTORS: Final = {
    "A01-SEEDS": _audit_seeds,
    "A02-WORLDS": _audit_worlds,
    "A03-TRUTH-ISOLATION": _audit_truth_isolation,
    "A04-ORACLE-ISOLATION": _audit_oracle,
    "A05-COMMON-RANDOMNESS": _audit_common_randomness,
    "A06-DETERMINISM": _audit_determinism,
    "A07-ARM-ISOLATION": _audit_arm_isolation,
    "A08-CALIBRATION-SEPARATION": _audit_calibration,
    "A09-PLANNER-AND-EVIDENCE": _audit_planner_and_evidence,
    "A10-COSTS": _audit_costs,
    "A11-SOURCE-FREEZE": _audit_source_freeze,
    "A12-MATRIX": _audit_matrix,
    "A13-REGISTRIES": _audit_registries,
    "A14-HISTORICAL": _audit_historical,
    "A15-RESAMPLING": _audit_resampling,
    "A16-FINALIZATION": _audit_finalization,
}


def assert_audit_executor_completeness() -> None:
    frozen = set(load_protocol_snapshot().registry("audit").ids("audit_id"))
    if set(AUDIT_EXECUTORS) != frozen:
        raise ValueError("Integrity audit executor ownership differs from the frozen registry.")
