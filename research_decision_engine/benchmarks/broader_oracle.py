"""Exact selected-only oracle for the frozen broader replication."""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable, Iterator
from dataclasses import InitVar, dataclass
from decimal import (
    ROUND_HALF_EVEN,
    Clamped,
    Context,
    Decimal,
    DivisionByZero,
    FloatOperation,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    Subnormal,
    Underflow,
    localcontext,
)
from pathlib import Path
from types import FunctionType
from typing import Final, Literal, NoReturn, Protocol, Self, SupportsIndex, cast

from research_decision_engine.benchmarks.broader_protocol import (
    DESIGN_FILENAME,
    EXPECTED_ORACLE_DOMAIN_SHA256,
    FULL_SEEDS,
    PROTOCOL_CHECKPOINT,
    PROTOCOL_VERSION,
    PUBLIC_PROVENANCE_ROLE_TOKENS,
    SMOKE_SEEDS,
    SMOKE_WORLD_IDS,
    SOURCE_CHECKPOINT,
    canonical_json_bytes,
    f64,
    protocol_hash,
    repository_root,
    runtime_id,
)
from research_decision_engine.benchmarks.broader_validation_evidence import (
    EVIDENCE_CONTRACT_CHECKPOINT,
    STUDY_ID,
    CallableProjection,
    FileProjection,
    ImplementationProjection,
    Layer0Context,
    P2Stage1Error,
    RuntimeProjection,
    ValidationRun,
    _allocate_production_plan_capability,
    _fixture_validation_run_id,
    _FixtureValidationRun,
    _PlanDraft,
    _production_validation_run_id,
    _ProductionPreparationCapability,
    _record_production_plan_draft,
    _register_fixture_plan,
    _register_production_component_callable,
    _require_production_preparation,
    callable_projection,
)
from research_decision_engine.benchmarks.broader_worlds import (
    CANDIDATES_BY_ID,
    DECISION_ORACLE_CANDIDATE_IDS,
    GROUP_IDS,
    WORLDS,
    WORLDS_BY_ID,
    BenchmarkWorld,
    hidden_arm_mean,
    hidden_observation_sigma,
)

ORACLE_VERSION: Final = "broader_selected_only_oracle/v1"
DECISION_NAMESPACE: Final = "rde.broader.decision-outcome/v1"
CALIBRATION_NAMESPACE: Final = "rde.broader.calibration-outcome/v1"
CONFORMANCE_GENERATOR_VERSION: Final = "broader-oracle-conformance/v1"
EXPECTED_ORACLE_PARTITION_COUNTS: Final = (
    ("full_decision", 24_576),
    ("full_calibration", 92_160),
    ("smoke_decision", 256),
    ("smoke_calibration", 960),
)
EXPECTED_ORACLE_KEY_COUNT: Final = 117_952

type OracleExecutionStatus = Literal["COMPLETED", "FAILED"]
type OracleKey = tuple[str, ...]
type OraclePartition = tuple[str, Iterable[OracleKey]]

_BINDING_CONSTRUCTION_KEY: Final = object()
_RESULT_CONSTRUCTION_KEY: Final = object()
_FIXTURE_BINDING_CONSTRUCTION_KEY: Final = object()
_FIXTURE_RESULT_CONSTRUCTION_KEY: Final = object()
_FIXTURE_EVIDENCE_CONSTRUCTION_KEY: Final = object()
_FIXTURE_ISSUANCE_KEY: Final = object()

_P_LOW = Decimal("0.02425")
_P_HIGH = Decimal("0.97575")
_A = tuple(
    Decimal(item)
    for item in (
        "-39.69683028665376",
        "220.9460984245205",
        "-275.9285104469687",
        "138.3577518672690",
        "-30.66479806614716",
        "2.506628277459239",
    )
)
_B = tuple(
    Decimal(item)
    for item in (
        "-54.47609879822406",
        "161.5858368580409",
        "-155.6989798598866",
        "66.80131188771972",
        "-13.28068155288572",
    )
)
_C = tuple(
    Decimal(item)
    for item in (
        "-0.007784894002430293",
        "-0.3223964580411365",
        "-2.400758277161838",
        "-2.549732539343734",
        "4.374664141464968",
        "2.938163982698783",
    )
)
_D = tuple(
    Decimal(item)
    for item in (
        "0.007784695709041462",
        "0.3224671290700398",
        "2.445134137142996",
        "3.754408661907416",
    )
)


class OracleError(ValueError):
    """Raised for unauthorized or malformed oracle access."""


class OraclePlan:
    """Opaque exact-issued P2 Oracle plan capability."""

    __slots__ = ()

    def __new__(cls) -> NoReturn:
        raise TypeError("Production P2 Oracle plans have no public constructor.")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("P2 Oracle plans cannot be subclassed.")

    def __copy__(self) -> NoReturn:
        raise TypeError("P2 Oracle plans cannot be copied.")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("P2 Oracle plans cannot be deep-copied.")

    def __reduce__(self) -> NoReturn:
        raise TypeError("P2 Oracle plans cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("P2 Oracle plans cannot be serialized.")


class _FixtureOraclePlan:
    """Opaque fixture-only Oracle plan, disjoint from production authority."""

    __slots__ = ()

    def __new__(cls) -> NoReturn:
        raise TypeError("Fixture P2 Oracle plans have no public constructor.")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("Fixture P2 Oracle plans cannot be subclassed.")

    def __copy__(self) -> NoReturn:
        raise TypeError("Fixture P2 Oracle plans cannot be copied.")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("Fixture P2 Oracle plans cannot be deep-copied.")

    def __reduce__(self) -> NoReturn:
        raise TypeError("Fixture P2 Oracle plans cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Fixture P2 Oracle plans cannot be serialized.")


@dataclass(frozen=True, slots=True)
class OracleDecisionRowProjection:
    candidate_id: str
    replication_id: str

    def as_dict(self) -> dict[str, object]:
        return {"candidate_id": self.candidate_id, "replication_id": self.replication_id}


@dataclass(frozen=True, slots=True)
class OracleCalibrationRowProjection:
    comparison_group_id: str
    intervention_arm: Literal["adam", "sgd"]
    replication_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "comparison_group_id": self.comparison_group_id,
            "intervention_arm": self.intervention_arm,
            "replication_id": self.replication_id,
        }


@dataclass(frozen=True, slots=True)
class OracleEnumerationDomainProjection:
    calibration_rows: tuple[OracleCalibrationRowProjection, ...]
    decision_rows: tuple[OracleDecisionRowProjection, ...]
    full_seeds: tuple[int, ...]
    full_world_ids: tuple[str, ...]
    smoke_seeds: tuple[int, ...]
    smoke_world_ids: tuple[str, ...]
    schema_version: str = "broader-replication-oracle-enumeration-domain/v1"
    oracle_version: str = ORACLE_VERSION
    protocol_checkpoint: str = PROTOCOL_CHECKPOINT
    calibration_namespace: str = CALIBRATION_NAMESPACE
    decision_namespace: str = DECISION_NAMESPACE

    def as_dict(self) -> dict[str, object]:
        return {
            "calibration_rows": [row.as_dict() for row in self.calibration_rows],
            "calibration_key_field_order": [
                "namespace",
                "study_id",
                "oracle_version",
                "world_id",
                "seed",
                "comparison_group_id",
                "intervention_arm",
                "replication_id",
            ],
            "decision_key_field_order": [
                "namespace",
                "study_id",
                "oracle_version",
                "world_id",
                "seed",
                "candidate_id",
                "replication_id",
            ],
            "decision_rows": [row.as_dict() for row in self.decision_rows],
            "calibration_namespace": self.calibration_namespace,
            "decision_namespace": self.decision_namespace,
            "full_seeds": list(self.full_seeds),
            "full_world_ids": list(self.full_world_ids),
            "oracle_version": self.oracle_version,
            "protocol_checkpoint": self.protocol_checkpoint,
            "schema_version": self.schema_version,
            "smoke_seeds": list(self.smoke_seeds),
            "smoke_world_ids": list(self.smoke_world_ids),
        }


@dataclass(frozen=True, slots=True)
class OracleImplementationProjection:
    callable: CallableProjection
    conformance_version: str = CONFORMANCE_GENERATOR_VERSION
    oracle_version: str = ORACLE_VERSION
    schema_version: str = "broader-replication-oracle-implementation/v1"

    def as_dict(self) -> dict[str, object]:
        return {
            "callable": self.callable.as_dict(),
            "conformance_version": self.conformance_version,
            "oracle_version": self.oracle_version,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class OracleExpectedPartitionProjection:
    count: int
    partition_id: str

    def as_dict(self) -> dict[str, object]:
        return {"count": self.count, "partition_id": self.partition_id}


@dataclass(frozen=True, slots=True)
class OraclePlanProjection:
    evidence_contract_checkpoint: str
    implementation: ImplementationProjection
    oracle_enumeration_domain_id: str
    oracle_implementation: CallableProjection
    oracle_implementation_identity: str
    oracle_source: FileProjection
    plan_issuer_identity: str
    runtime: RuntimeProjection
    runtime_identity: str
    validation_run_id: str
    conformance_version: str = CONFORMANCE_GENERATOR_VERSION
    expected_digest: str = EXPECTED_ORACLE_DOMAIN_SHA256
    expected_key_count: int = EXPECTED_ORACLE_KEY_COUNT
    expected_unique_key_count: int = EXPECTED_ORACLE_KEY_COUNT
    oracle_version: str = ORACLE_VERSION
    protocol_checkpoint: str = PROTOCOL_CHECKPOINT
    schema_version: str = "broader-replication-oracle-plan/v1"
    study_id: str = STUDY_ID

    def as_dict(self) -> dict[str, object]:
        return {
            "conformance_version": self.conformance_version,
            "deterministic_execution_policy": {
                "digest_algorithm": "sha256-canonical-jsonl",
                "digest_row_field_order": [
                    "namespace",
                    "serialized_key_hex",
                    "digest_hex",
                    "u_string",
                    "z_string",
                ],
                "execution_mode": "serial",
                "partition_order": [
                    "full_decision",
                    "full_calibration",
                    "smoke_decision",
                    "smoke_calibration",
                ],
            },
            "evidence_contract_checkpoint": self.evidence_contract_checkpoint,
            "expected_completion": {
                "actual_digest_required": True,
                "all_keys_required": True,
                "comparison_result_required": "MATCH",
                "failure_details_count": 0,
                "required_status": "COMPLETED",
            },
            "expected_digest": self.expected_digest,
            "expected_key_count": self.expected_key_count,
            "expected_partitions": [
                OracleExpectedPartitionProjection(count, partition).as_dict()
                for partition, count in EXPECTED_ORACLE_PARTITION_COUNTS
            ],
            "expected_unique_key_count": self.expected_unique_key_count,
            "implementation": self.implementation.as_dict(),
            "oracle_enumeration_domain_id": self.oracle_enumeration_domain_id,
            "oracle_implementation": self.oracle_implementation.as_dict(),
            "oracle_implementation_identity": self.oracle_implementation_identity,
            "oracle_source": self.oracle_source.as_dict(),
            "oracle_version": self.oracle_version,
            "plan_issuer_identity": self.plan_issuer_identity,
            "protocol_checkpoint": self.protocol_checkpoint,
            "runtime": self.runtime.as_dict(),
            "runtime_identity": self.runtime_identity,
            "schema_version": self.schema_version,
            "study_id": self.study_id,
            "timeout_policy": {
                "on_timeout": "terminate-and-fail",
                "wall_timeout_ms": 10800000,
            },
            "validation_run_id": self.validation_run_id,
        }


@dataclass(frozen=True, slots=True)
class OracleTransform:
    serialized_key: bytes
    digest_hex: str
    u_string: str
    z_string: str

    @property
    def z(self) -> float:
        return float(self.z_string)


@dataclass(frozen=True, slots=True, eq=False)
class OracleEvidenceBinding:
    """Historical P1 binding; never a P2 Oracle plan or oracle_binding_id."""

    validation_run_identity: str
    evidence_bundle_identity: str
    implementation_commit: str
    design_checkpoint_commit: str
    source_design_sha256: str
    implementation_source_sha256: str
    implementation_test_sha256: str
    binding_identity: str
    _construction_key: InitVar[object]

    def __post_init__(self, _construction_key: object) -> None:
        if _construction_key is not _BINDING_CONSTRUCTION_KEY:
            raise TypeError("Oracle evidence bindings are issued only by the guarded begin path.")

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, memo: object) -> Self:
        del memo
        return self

    def __reduce__(self) -> NoReturn:
        raise TypeError("Oracle evidence bindings cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Oracle evidence bindings cannot be serialized.")


@dataclass(frozen=True, slots=True, eq=False)
class OracleConformanceResult:
    """Actual Oracle enumeration observations, with no expected result embedded."""

    conformance_version: str
    oracle_version: str
    issuer_kind: Literal["production"]
    execution_status: OracleExecutionStatus
    actual_key_count: int
    actual_unique_key_count: int
    actual_partition_counts: tuple[tuple[str, int], ...]
    actual_sha256: str
    oracle_source_sha256: str
    implementation_commit: str
    design_checkpoint_commit: str
    source_design_sha256: str
    implementation_source_sha256: str
    implementation_test_sha256: str
    validation_run_identity: str
    evidence_bundle_identity: str
    evidence_binding_identity: str
    execution_identity: str
    failure_details: tuple[str, ...]
    _construction_key: InitVar[object]

    def __post_init__(self, _construction_key: object) -> None:
        if _construction_key is not _RESULT_CONSTRUCTION_KEY:
            raise TypeError("Oracle conformance results are issued only by actual enumeration.")

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, memo: object) -> Self:
        del memo
        return self

    def __reduce__(self) -> NoReturn:
        raise TypeError("Oracle conformance results cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Oracle conformance results cannot be serialized.")


@dataclass(frozen=True, slots=True, eq=False)
class OracleFixtureBinding:
    """Exact test-only identity for one bounded diagnostic enumeration."""

    validation_run_identity: str
    evidence_bundle_identity: str
    implementation_commit: str
    design_checkpoint_commit: str
    source_design_sha256: str
    implementation_source_sha256: str
    implementation_test_sha256: str
    binding_identity: str
    _construction_key: InitVar[object]

    def __post_init__(self, _construction_key: object) -> None:
        if _construction_key is not _FIXTURE_BINDING_CONSTRUCTION_KEY:
            raise TypeError("Oracle fixture bindings are issued only by the fixture begin path.")

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, memo: object) -> Self:
        del memo
        return self

    def __reduce__(self) -> NoReturn:
        raise TypeError("Oracle fixture bindings cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Oracle fixture bindings cannot be serialized.")


@dataclass(frozen=True, slots=True, eq=False)
class OracleFixtureResult:
    """Non-authoritative observations derived by one bounded fixture enumeration."""

    conformance_version: str
    oracle_version: str
    execution_status: OracleExecutionStatus
    actual_key_count: int
    actual_unique_key_count: int
    actual_partition_counts: tuple[tuple[str, int], ...]
    actual_sha256: str
    oracle_source_sha256: str
    implementation_commit: str
    design_checkpoint_commit: str
    source_design_sha256: str
    implementation_source_sha256: str
    implementation_test_sha256: str
    validation_run_identity: str
    evidence_bundle_identity: str
    evidence_binding_identity: str
    execution_identity: str
    failure_details: tuple[str, ...]
    _construction_key: InitVar[object]

    def __post_init__(self, _construction_key: object) -> None:
        if _construction_key is not _FIXTURE_RESULT_CONSTRUCTION_KEY:
            raise TypeError("Oracle fixture results are issued only by bounded enumeration.")

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, memo: object) -> Self:
        del memo
        return self

    def __reduce__(self) -> NoReturn:
        raise TypeError("Oracle fixture results cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Oracle fixture results cannot be serialized.")


@dataclass(frozen=True, slots=True, eq=False)
class OracleFixtureEvidence:
    """Exact test-only capability for one bounded fixture enumeration.

    Production Oracle validators and evidence generators never accept this capability. It
    exists only so bounded conformance tests can use an explicit trust domain without
    replacing the production validator.
    """

    result: OracleFixtureResult
    binding: OracleFixtureBinding
    fixture_identity: str
    _construction_key: InitVar[object]

    def __post_init__(self, _construction_key: object) -> None:
        if _construction_key is not _FIXTURE_EVIDENCE_CONSTRUCTION_KEY:
            raise TypeError("Oracle fixture evidence is issued only by bounded enumeration.")

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, memo: object) -> Self:
        del memo
        return self

    def __reduce__(self) -> NoReturn:
        raise TypeError("Oracle fixture evidence cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Oracle fixture evidence cannot be serialized.")


@dataclass(frozen=True, slots=True)
class _CurrentOracleIdentities:
    implementation_commit: str
    design_checkpoint_commit: str
    source_design_sha256: str
    implementation_source_sha256: str
    implementation_test_sha256: str
    oracle_source_sha256: str


@dataclass(slots=True)
class _IssuedOracleEvidenceBinding:
    binding: OracleEvidenceBinding
    fingerprint: str
    active: bool
    execution_claimed: bool


@dataclass(frozen=True, slots=True)
class _IssuedOracleConformanceResult:
    result: OracleConformanceResult
    binding: OracleEvidenceBinding
    fingerprint: str


@dataclass(slots=True)
class _IssuedOracleFixtureBinding:
    binding: OracleFixtureBinding
    fingerprint: str
    active: bool
    execution_claimed: bool


@dataclass(frozen=True, slots=True)
class _IssuedOracleFixtureResult:
    result: OracleFixtureResult
    binding: OracleFixtureBinding
    fingerprint: str


@dataclass(frozen=True, slots=True)
class _IssuedOracleFixtureEvidence:
    evidence: OracleFixtureEvidence
    result: OracleFixtureResult
    binding: OracleFixtureBinding
    fingerprint: str


@dataclass(frozen=True, slots=True)
class _OracleEnumeration:
    execution_status: OracleExecutionStatus
    actual_key_count: int
    actual_unique_key_count: int
    actual_partition_counts: tuple[tuple[str, int], ...]
    actual_sha256: str
    failure_details: tuple[str, ...]


_ISSUED_ORACLE_EVIDENCE_BINDINGS: dict[int, _IssuedOracleEvidenceBinding] = {}
_ISSUED_ORACLE_CONFORMANCE_RESULTS: dict[int, _IssuedOracleConformanceResult] = {}
_ISSUED_ORACLE_FIXTURE_BINDINGS: dict[int, _IssuedOracleFixtureBinding] = {}
_ISSUED_ORACLE_FIXTURE_RESULTS: dict[int, _IssuedOracleFixtureResult] = {}
_ISSUED_ORACLE_FIXTURE_EVIDENCE: dict[int, _IssuedOracleFixtureEvidence] = {}
_USED_VALIDATION_RUN_IDENTITIES: set[str] = set()
_USED_EVIDENCE_BUNDLE_IDENTITIES: set[str] = set()
_EVIDENCE_LOCK = threading.RLock()


def oracle_enumeration_domain_projection() -> OracleEnumerationDomainProjection:
    return OracleEnumerationDomainProjection(
        calibration_rows=tuple(
            OracleCalibrationRowProjection(
                comparison_group_id=group_id,
                intervention_arm=arm,
                replication_id=f"calibration-{group_index:02d}-r{replication_index:04d}",
            )
            for group_index, group_id in enumerate(GROUP_IDS)
            for arm in ("adam", "sgd")
            for replication_index in range(1, 6)
        ),
        decision_rows=tuple(
            OracleDecisionRowProjection(
                candidate_id=candidate_id,
                replication_id=CANDIDATES_BY_ID[candidate_id].replication_id,
            )
            for candidate_id in DECISION_ORACLE_CANDIDATE_IDS
        ),
        full_seeds=FULL_SEEDS,
        full_world_ids=tuple(world.public.world_id for world in WORLDS),
        smoke_seeds=SMOKE_SEEDS,
        smoke_world_ids=SMOKE_WORLD_IDS,
    )


def oracle_enumeration_domain_id(
    projection: OracleEnumerationDomainProjection,
) -> str:
    return protocol_hash("validation_evidence_oracle_enumeration_domain/v1", projection.as_dict())


def _oracle_plan_id_from_projection(
    projection: OraclePlanProjection,
    *,
    expected_callable: CallableProjection,
) -> str:
    mapping = projection.as_dict()
    expected_fields = {
        "conformance_version",
        "deterministic_execution_policy",
        "evidence_contract_checkpoint",
        "expected_completion",
        "expected_digest",
        "expected_key_count",
        "expected_partitions",
        "expected_unique_key_count",
        "implementation",
        "oracle_enumeration_domain_id",
        "oracle_implementation",
        "oracle_implementation_identity",
        "oracle_source",
        "oracle_version",
        "plan_issuer_identity",
        "protocol_checkpoint",
        "runtime",
        "runtime_identity",
        "schema_version",
        "study_id",
        "timeout_policy",
        "validation_run_id",
    }
    if (
        set(mapping) != expected_fields
        or "validation_authority_id" in mapping
        or "oracle_binding_id" in mapping
    ):
        raise P2Stage1Error(
            "ORACLE_PLAN_ID_MISMATCH",
            "Oracle plan differs from its frozen authority-free schema.",
            layer="oracle_plan",
        )
    expected_implementation = protocol_hash(
        "validation_evidence_oracle_implementation/v1",
        OracleImplementationProjection(expected_callable).as_dict(),
    )
    if (
        projection.oracle_implementation != expected_callable
        or projection.oracle_implementation_identity != expected_implementation
        or projection.oracle_source != projection.oracle_implementation.source
    ):
        raise P2Stage1Error(
            "ORACLE_PLAN_ID_MISMATCH",
            "Oracle implementation projection does not reconcile.",
            layer="oracle_plan",
        )
    expected_domain_id = oracle_enumeration_domain_id(oracle_enumeration_domain_projection())
    if (
        projection.oracle_enumeration_domain_id != expected_domain_id
        or projection.conformance_version != CONFORMANCE_GENERATOR_VERSION
        or projection.expected_digest != EXPECTED_ORACLE_DOMAIN_SHA256
        or projection.expected_key_count != EXPECTED_ORACLE_KEY_COUNT
        or projection.expected_unique_key_count != EXPECTED_ORACLE_KEY_COUNT
        or projection.oracle_version != ORACLE_VERSION
        or projection.protocol_checkpoint != PROTOCOL_CHECKPOINT
        or projection.schema_version != "broader-replication-oracle-plan/v1"
        or projection.study_id != STUDY_ID
        or re.fullmatch(r"[0-9a-f]{64}", projection.validation_run_id) is None
    ):
        raise P2Stage1Error(
            "ORACLE_PLAN_ID_MISMATCH",
            "Oracle plan fixed literals, domain, or validation run differ.",
            layer="oracle_plan",
        )
    if projection.evidence_contract_checkpoint != EVIDENCE_CONTRACT_CHECKPOINT:
        raise P2Stage1Error(
            "EVIDENCE_CONTRACT_CHECKPOINT_MISMATCH",
            "Oracle plan uses another evidence-contract checkpoint.",
            layer="oracle_plan",
        )
    return protocol_hash("validation_evidence_oracle_plan/v1", mapping)


def oracle_plan_id_from_projection(projection: OraclePlanProjection) -> str:
    expected_callable, _ = _require_trusted_oracle_callable()
    return _oracle_plan_id_from_projection(
        projection,
        expected_callable=expected_callable,
    )


def _build_oracle_plan_projection(
    *,
    context: Layer0Context,
    validation_run_id: str,
    implementation_callable: CallableProjection,
) -> OraclePlanProjection:
    """Build the closed Oracle projection from one internally resolved run ID."""

    enumeration = oracle_enumeration_domain_projection()
    implementation = OracleImplementationProjection(implementation_callable)
    implementation_identity = protocol_hash(
        "validation_evidence_oracle_implementation/v1", implementation.as_dict()
    )
    return OraclePlanProjection(
        evidence_contract_checkpoint=EVIDENCE_CONTRACT_CHECKPOINT,
        implementation=context.implementation,
        oracle_enumeration_domain_id=oracle_enumeration_domain_id(enumeration),
        oracle_implementation=implementation_callable,
        oracle_implementation_identity=implementation_identity,
        oracle_source=implementation_callable.source,
        plan_issuer_identity=context.oracle_plan_issuer_identity,
        runtime=context.runtime,
        runtime_identity=context.runtime_identity,
        validation_run_id=validation_run_id,
    )


def _build_fixture_oracle_plan_projection(
    *,
    context: Layer0Context,
    validation_run: _FixtureValidationRun,
) -> OraclePlanProjection:
    """Build a nonproduction Oracle projection for the disjoint fixture registry."""

    implementation_callable, _ = _require_trusted_oracle_callable()
    return _build_oracle_plan_projection(
        context=context,
        validation_run_id=_fixture_validation_run_id(validation_run),
        implementation_callable=implementation_callable,
    )


def _issue_fixture_oracle_plan(
    *,
    projection: OraclePlanProjection,
    validation_run: _FixtureValidationRun,
) -> _FixtureOraclePlan:
    """Register an exact Oracle plan only in the fixture plan registry."""

    if type(projection) is not OraclePlanProjection:
        raise P2Stage1Error(
            "ORACLE_PLAN_ID_MISMATCH",
            "Fixture Oracle plan requires the exact closed projection type.",
            layer="plan_identities",
        )
    run_id = _fixture_validation_run_id(validation_run)
    if projection.validation_run_id != run_id:
        raise P2Stage1Error(
            "ISSUED_PLAN_RUN_MISMATCH",
            "Fixture Oracle plan and validation-run capability differ.",
            layer="plan_identities",
        )
    persistent_id = oracle_plan_id_from_projection(projection)
    capability = cast(
        _FixtureOraclePlan,
        object.__new__(cast(type[object], _FixtureOraclePlan)),
    )
    _register_fixture_plan(
        _PlanDraft(
            capability=capability,
            kind="oracle",
            role="oracle",
            persistent_id=persistent_id,
            validation_run=validation_run,
            validation_run_id=run_id,
            projection=projection,
        )
    )
    return capability


def oracle_plan_id(plan: OraclePlan) -> str:
    from research_decision_engine.benchmarks.broader_validation_evidence import plan_persistent_id

    if type(plan) is not OraclePlan:
        raise P2Stage1Error(
            "ISSUED_PLAN_CAPABILITY_INVALID",
            "Exact production OraclePlan capability required.",
            layer="live_issued_plan_binding",
        )
    return plan_persistent_id(plan)


def p2_oracle_plan_projection(plan: OraclePlan) -> OraclePlanProjection:
    from research_decision_engine.benchmarks.broader_validation_evidence import plan_projection

    if type(plan) is not OraclePlan:
        raise P2Stage1Error(
            "ISSUED_PLAN_CAPABILITY_INVALID",
            "Exact production OraclePlan capability required.",
            layer="live_issued_plan_binding",
        )
    projection = plan_projection(plan)
    if type(projection) is not OraclePlanProjection:
        raise P2Stage1Error(
            "ORACLE_PLAN_ID_MISMATCH",
            "Issued production OraclePlan has the wrong projection type.",
            layer="plan_identities",
        )
    return projection


def _fixture_oracle_plan_id(plan: _FixtureOraclePlan) -> str:
    from research_decision_engine.benchmarks.broader_validation_evidence import plan_persistent_id

    if type(plan) is not _FixtureOraclePlan:
        raise P2Stage1Error(
            "ISSUED_PLAN_CAPABILITY_INVALID",
            "Exact fixture Oracle plan capability required.",
            layer="live_issued_plan_binding",
        )
    return plan_persistent_id(plan)


def _fixture_oracle_plan_projection(plan: _FixtureOraclePlan) -> OraclePlanProjection:
    from research_decision_engine.benchmarks.broader_validation_evidence import plan_projection

    if type(plan) is not _FixtureOraclePlan:
        raise P2Stage1Error(
            "ISSUED_PLAN_CAPABILITY_INVALID",
            "Exact fixture Oracle plan capability required.",
            layer="live_issued_plan_binding",
        )
    projection = plan_projection(plan)
    if type(projection) is not OraclePlanProjection:
        raise P2Stage1Error(
            "ORACLE_PLAN_ID_MISMATCH",
            "Issued fixture Oracle plan has the wrong projection type.",
            layer="plan_identities",
        )
    return projection


def begin_oracle_evidence_binding(
    *,
    validation_run_identity: str,
    evidence_bundle_identity: str,
) -> OracleEvidenceBinding:
    """Issue one historical P1 binding; this path cannot mint P2 plan authority."""

    _validate_external_identity(validation_run_identity, "validation run")
    _validate_external_identity(evidence_bundle_identity, "evidence bundle")
    if validation_run_identity == evidence_bundle_identity:
        raise OracleError("Validation-run and evidence-bundle identities must be distinct.")
    identities = _current_oracle_identities()
    binding_values = {
        "design_checkpoint_commit": identities.design_checkpoint_commit,
        "evidence_bundle_identity": evidence_bundle_identity,
        "implementation_commit": identities.implementation_commit,
        "implementation_source_sha256": identities.implementation_source_sha256,
        "implementation_test_sha256": identities.implementation_test_sha256,
        "source_design_sha256": identities.source_design_sha256,
        "validation_run_identity": validation_run_identity,
    }
    binding = OracleEvidenceBinding(
        validation_run_identity=validation_run_identity,
        evidence_bundle_identity=evidence_bundle_identity,
        implementation_commit=identities.implementation_commit,
        design_checkpoint_commit=identities.design_checkpoint_commit,
        source_design_sha256=identities.source_design_sha256,
        implementation_source_sha256=identities.implementation_source_sha256,
        implementation_test_sha256=identities.implementation_test_sha256,
        binding_identity=protocol_hash("oracle_evidence_binding/v1", binding_values),
        _construction_key=_BINDING_CONSTRUCTION_KEY,
    )
    record = _IssuedOracleEvidenceBinding(
        binding=binding,
        fingerprint=_binding_fingerprint(binding),
        active=True,
        execution_claimed=False,
    )
    with _EVIDENCE_LOCK:
        if validation_run_identity in _USED_VALIDATION_RUN_IDENTITIES:
            raise OracleError("Validation-run identity was already bound in this process.")
        if evidence_bundle_identity in _USED_EVIDENCE_BUNDLE_IDENTITIES:
            raise OracleError("Evidence-bundle identity was already bound in this process.")
        _USED_VALIDATION_RUN_IDENTITIES.add(validation_run_identity)
        _USED_EVIDENCE_BUNDLE_IDENTITIES.add(evidence_bundle_identity)
        _ISSUED_ORACLE_EVIDENCE_BINDINGS[id(binding)] = record
    return binding


def close_oracle_evidence_binding(binding: OracleEvidenceBinding) -> None:
    """Make an issued binding and every associated result stale."""

    record = _require_issued_binding(binding, require_active=True, require_current=False)
    with _EVIDENCE_LOCK:
        current = _ISSUED_ORACLE_EVIDENCE_BINDINGS.get(id(binding))
        if current is not record or current.binding is not binding or not current.active:
            raise OracleError("Oracle evidence binding is forged or stale.")
        current.active = False


def _begin_oracle_fixture_binding(
    *,
    validation_run_identity: str,
    evidence_bundle_identity: str,
) -> OracleFixtureBinding:
    """Issue a bounded fixture binding in a registry disjoint from production evidence."""

    _validate_external_identity(validation_run_identity, "fixture validation run")
    _validate_external_identity(evidence_bundle_identity, "fixture evidence bundle")
    if validation_run_identity == evidence_bundle_identity:
        raise OracleError("Fixture validation-run and evidence-bundle identities must differ.")
    identities = _current_oracle_identities()
    binding_values = {
        "design_checkpoint_commit": identities.design_checkpoint_commit,
        "evidence_bundle_identity": evidence_bundle_identity,
        "implementation_commit": identities.implementation_commit,
        "implementation_source_sha256": identities.implementation_source_sha256,
        "implementation_test_sha256": identities.implementation_test_sha256,
        "source_design_sha256": identities.source_design_sha256,
        "validation_run_identity": validation_run_identity,
    }
    binding = OracleFixtureBinding(
        validation_run_identity=validation_run_identity,
        evidence_bundle_identity=evidence_bundle_identity,
        implementation_commit=identities.implementation_commit,
        design_checkpoint_commit=identities.design_checkpoint_commit,
        source_design_sha256=identities.source_design_sha256,
        implementation_source_sha256=identities.implementation_source_sha256,
        implementation_test_sha256=identities.implementation_test_sha256,
        binding_identity=protocol_hash("oracle_fixture_binding/v1", binding_values),
        _construction_key=_FIXTURE_BINDING_CONSTRUCTION_KEY,
    )
    record = _IssuedOracleFixtureBinding(
        binding=binding,
        fingerprint=_fixture_binding_fingerprint(binding),
        active=True,
        execution_claimed=False,
    )
    with _EVIDENCE_LOCK:
        if validation_run_identity in _USED_VALIDATION_RUN_IDENTITIES:
            raise OracleError("Validation-run identity was already bound in this process.")
        if evidence_bundle_identity in _USED_EVIDENCE_BUNDLE_IDENTITIES:
            raise OracleError("Evidence-bundle identity was already bound in this process.")
        _USED_VALIDATION_RUN_IDENTITIES.add(validation_run_identity)
        _USED_EVIDENCE_BUNDLE_IDENTITIES.add(evidence_bundle_identity)
        _ISSUED_ORACLE_FIXTURE_BINDINGS[id(binding)] = record
    return binding


def _close_oracle_fixture_binding(binding: OracleFixtureBinding) -> None:
    """Revoke one fixture binding and every diagnostic derived from it."""

    record = _require_issued_fixture_binding(
        binding,
        require_active=True,
        require_current=False,
    )
    with _EVIDENCE_LOCK:
        current = _ISSUED_ORACLE_FIXTURE_BINDINGS.get(id(binding))
        if current is not record or current.binding is not binding or not current.active:
            raise OracleError("Oracle fixture binding is forged or stale.")
        current.active = False


@dataclass(frozen=True, slots=True)
class ObservationAuthorization:
    authorization_id: str
    run_id: str
    source_id: str
    candidate_id: str
    kind: str


@dataclass(frozen=True, slots=True)
class RevealedObservation:
    oracle_key_id: str
    oracle_use_id: str
    authorization_id: str
    namespace: str
    world_id: str
    seed: int
    candidate_id: str
    comparison_group_id: str | None
    intervention_arm: str | None
    replication_id: str
    key_fields: tuple[str, ...]
    serialized_key_hex: str
    digest: str
    u: str
    z: str
    revealed_observation: float
    outcome_digest: str


class SelectedObservationInterface(Protocol):
    """The complete policy-external selected-only observation surface."""

    def observe_selected(self, authorization: ObservationAuthorization) -> RevealedObservation:
        """Reveal exactly the authorized selected outcome."""


class _SelectedOnlyOracle:
    """Capability object with no enumeration or counterfactual method."""

    __slots__ = ("_observe",)

    def __init__(self, observe: Callable[[ObservationAuthorization], RevealedObservation]) -> None:
        self._observe = observe

    def observe_selected(self, authorization: ObservationAuthorization) -> RevealedObservation:
        return self._observe(authorization)


class ObservationAuthority:
    """Evaluator-only owner of hidden world parameters and revealed-use history."""

    def __init__(
        self,
        *,
        world: BenchmarkWorld,
        seed: int,
        decision_namespace: str = DECISION_NAMESPACE,
        calibration_namespace: str = CALIBRATION_NAMESPACE,
    ) -> None:
        self._world = world
        self._seed = seed
        self._decision_namespace = decision_namespace
        self._calibration_namespace = calibration_namespace
        self._used_authorizations: set[str] = set()
        self._revealed: list[RevealedObservation] = []

    def assert_bound_to(self, *, world: BenchmarkWorld, seed: int) -> None:
        """Validate evaluator provenance without exposing hidden values to policies."""

        if self._world != world:
            raise OracleError("Observation authority is bound to a different benchmark world.")
        if self._seed != seed:
            raise OracleError("Observation authority is bound to a different evaluation seed.")
        if self._decision_namespace != DECISION_NAMESPACE:
            raise OracleError("Observation authority decision namespace is not frozen.")
        if self._calibration_namespace != CALIBRATION_NAMESPACE:
            raise OracleError("Observation authority calibration namespace is not frozen.")
        if self._used_authorizations or self._revealed:
            raise OracleError("Observation authority must be unused when a trajectory starts.")

    @property
    def bound_world_id(self) -> str:
        """Evaluator-only public binding used by runner preflight checks."""

        return self._world.public.world_id

    @property
    def bound_seed(self) -> int:
        """Evaluator-only seed binding used by runner preflight checks."""

        return self._seed

    def selected_only_interface(self) -> SelectedObservationInterface:
        return _SelectedOnlyOracle(self._observe_selected)

    def revealed_observations(self) -> tuple[RevealedObservation, ...]:
        return tuple(self._revealed)

    def _observe_selected(self, authorization: ObservationAuthorization) -> RevealedObservation:
        if authorization.authorization_id in self._used_authorizations:
            raise OracleError("An observation authorization can be consumed only once.")
        if authorization.kind == "decision":
            revealed = self._decision_observation(authorization)
        elif authorization.kind == "calibration":
            revealed = self._calibration_observation(authorization)
        else:
            raise OracleError(f"Unknown oracle authorization kind: {authorization.kind}")
        self._used_authorizations.add(authorization.authorization_id)
        self._revealed.append(revealed)
        return revealed

    def _decision_observation(self, authorization: ObservationAuthorization) -> RevealedObservation:
        try:
            definition = CANDIDATES_BY_ID[authorization.candidate_id]
        except KeyError as error:
            raise OracleError("Decision authorization references an unknown candidate.") from error
        if definition.role == "setup":
            raise OracleError("Setup actions never invoke the observation oracle.")
        key = decision_key(
            world_id=self._world.public.world_id,
            seed=self._seed,
            candidate_id=definition.candidate_id,
            replication_id=definition.replication_id,
            namespace=self._decision_namespace,
        )
        transform = transform_key(key)
        observed = hidden_arm_mean(self._world, definition.candidate_id) + (
            hidden_observation_sigma(self._world, definition.candidate_id) * transform.z
        )
        return _revealed_record(
            authorization=authorization,
            key=key,
            transform=transform,
            observed=observed,
            comparison_group_id=(
                definition.comparison_group_id if definition.role == "optimizer_arm" else None
            ),
            intervention_arm=(
                definition.intervention_arm if definition.role == "optimizer_arm" else None
            ),
            replication_id=definition.replication_id,
        )

    def _calibration_observation(
        self, authorization: ObservationAuthorization
    ) -> RevealedObservation:
        parsed = _parse_calibration_candidate(authorization.candidate_id)
        group_id, arm, replication_id = parsed
        base_candidate_id = f"g{group_id[-2:]}-{arm}-r1"
        key = calibration_key(
            world_id=self._world.public.world_id,
            seed=self._seed,
            comparison_group_id=group_id,
            intervention_arm=arm,
            replication_id=replication_id,
            namespace=self._calibration_namespace,
        )
        transform = transform_key(key)
        observed = hidden_arm_mean(self._world, base_candidate_id) + (
            hidden_observation_sigma(self._world, base_candidate_id) * transform.z
        )
        return _revealed_record(
            authorization=authorization,
            key=key,
            transform=transform,
            observed=observed,
            comparison_group_id=group_id,
            intervention_arm=arm,
            replication_id=replication_id,
        )


def authorize_observation(
    *, run_id: str, source_id: str, candidate_id: str, kind: str
) -> ObservationAuthorization:
    authorization_id = runtime_id(
        "authorization",
        "authorization_id/v1",
        {
            "candidate_id": candidate_id,
            "kind": kind,
            "run_id": run_id,
            "source_id": source_id,
        },
    )
    return ObservationAuthorization(
        authorization_id=authorization_id,
        run_id=run_id,
        source_id=source_id,
        candidate_id=candidate_id,
        kind=kind,
    )


def decision_key(
    *,
    world_id: str,
    seed: int,
    candidate_id: str,
    replication_id: str,
    namespace: str = DECISION_NAMESPACE,
) -> tuple[str, ...]:
    return (
        namespace,
        PROTOCOL_VERSION,
        ORACLE_VERSION,
        world_id,
        str(seed),
        candidate_id,
        replication_id,
    )


def calibration_key(
    *,
    world_id: str,
    seed: int,
    comparison_group_id: str,
    intervention_arm: str,
    replication_id: str,
    namespace: str = CALIBRATION_NAMESPACE,
) -> tuple[str, ...]:
    return (
        namespace,
        PROTOCOL_VERSION,
        ORACLE_VERSION,
        world_id,
        str(seed),
        comparison_group_id,
        intervention_arm,
        replication_id,
    )


def transform_key(key: tuple[str, ...]) -> OracleTransform:
    serialized = json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(serialized).digest()
    q64 = int.from_bytes(digest[:8], "big")
    k = q64 >> 12
    context = _decimal_context()
    with localcontext(context):
        u = Decimal(2 * k + 1) / Decimal(2**53)
        z = _acklam(u)
        u_quantized = u.quantize(Decimal("1E-53"), rounding=ROUND_HALF_EVEN)
        z_quantized = z.quantize(Decimal("1E-30"), rounding=ROUND_HALF_EVEN)
        if z_quantized.is_zero():
            z_quantized = abs(z_quantized)
        u_string = format(u_quantized, ".53f")
        z_string = format(z_quantized, ".30f")
    return OracleTransform(
        serialized_key=serialized,
        digest_hex=digest.hex(),
        u_string=u_string,
        z_string=z_string,
    )


def execute_oracle_conformance(binding: OracleEvidenceBinding) -> OracleConformanceResult:
    """Claim one binding and issue one result from the frozen production enumerator.

    Closing or invalidating the binding after its terminal claim revokes issuance and leaves
    the binding permanently non-retryable; no partial authoritative result is registered.
    """

    _claim_oracle_conformance_execution(binding)
    enumeration = _enumerate_oracle_partitions(_production_oracle_conformance_partitions())
    _require_issued_binding(binding, require_active=True, require_current=True)
    oracle_source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    actual_values = _enumeration_execution_values(
        enumeration,
        binding=binding,
        oracle_source_sha256=oracle_source_sha256,
        issuer_kind="production",
    )
    result = OracleConformanceResult(
        conformance_version=CONFORMANCE_GENERATOR_VERSION,
        oracle_version=ORACLE_VERSION,
        issuer_kind="production",
        execution_status=enumeration.execution_status,
        actual_key_count=enumeration.actual_key_count,
        actual_unique_key_count=enumeration.actual_unique_key_count,
        actual_partition_counts=enumeration.actual_partition_counts,
        actual_sha256=enumeration.actual_sha256,
        oracle_source_sha256=oracle_source_sha256,
        implementation_commit=binding.implementation_commit,
        design_checkpoint_commit=binding.design_checkpoint_commit,
        source_design_sha256=binding.source_design_sha256,
        implementation_source_sha256=binding.implementation_source_sha256,
        implementation_test_sha256=binding.implementation_test_sha256,
        validation_run_identity=binding.validation_run_identity,
        evidence_bundle_identity=binding.evidence_bundle_identity,
        evidence_binding_identity=binding.binding_identity,
        execution_identity=protocol_hash("oracle_conformance_execution/v1", actual_values),
        failure_details=enumeration.failure_details,
        _construction_key=_RESULT_CONSTRUCTION_KEY,
    )
    record = _IssuedOracleConformanceResult(
        result=result,
        binding=binding,
        fingerprint=_result_fingerprint(result),
    )
    with _EVIDENCE_LOCK:
        binding_record = _ISSUED_ORACLE_EVIDENCE_BINDINGS.get(id(binding))
        if (
            binding_record is None
            or binding_record.binding is not binding
            or not binding_record.active
        ):
            raise OracleError("Oracle evidence binding became stale during enumeration.")
        _ISSUED_ORACLE_CONFORMANCE_RESULTS[id(result)] = record
    return result


def _install_stage1_oracle_plan_authority() -> tuple[
    Callable[[], tuple[CallableProjection, str]],
    Callable[
        [_ProductionPreparationCapability, Layer0Context, ValidationRun],
        _PlanDraft,
    ],
]:
    """Capture the exact production Oracle callable after its definition is complete."""

    trusted_module = sys.modules[__name__]
    trusted_function = execute_oracle_conformance
    trusted_code = trusted_function.__code__
    project_callable = callable_projection
    trusted_projection, trusted_identity = project_callable(trusted_function)
    expected_source = (
        repository_root() / "research_decision_engine" / "benchmarks" / "broader_oracle.py"
    ).resolve(strict=True)
    if trusted_projection.source.path != str(expected_source):
        raise RuntimeError("Oracle callable source is not the trusted broader_oracle.py file.")
    require_preparation = _require_production_preparation
    production_run_id = _production_validation_run_id
    build_projection = _build_oracle_plan_projection
    compute_plan_id = _oracle_plan_id_from_projection
    production_plan_type = cast(type[OraclePlan], OraclePlan)
    draft_type = _PlanDraft
    allocate_plan = _allocate_production_plan_capability
    record_plan = _record_production_plan_draft

    def require_trusted_oracle_callable() -> tuple[CallableProjection, str]:
        current = trusted_module.__dict__.get("execute_oracle_conformance")
        current_source = inspect.getsourcefile(current) if type(current) is FunctionType else None
        try:
            resolved_source = (
                None if current_source is None else Path(current_source).resolve(strict=True)
            )
        except OSError:
            resolved_source = None
        if (
            current is not trusted_function
            or type(current) is not FunctionType
            or current.__code__ is not trusted_code
            or current.__module__ != __name__
            or current.__qualname__ != "execute_oracle_conformance"
            or resolved_source != expected_source
        ):
            raise P2Stage1Error(
                "ORACLE_PLAN_ID_MISMATCH",
                "The live Oracle callable is not the exact captured production implementation.",
                layer="oracle_plan",
            )
        current_projection, current_identity = project_callable(current)
        if current_projection != trusted_projection or current_identity != trusted_identity:
            raise P2Stage1Error(
                "ORACLE_PLAN_ID_MISMATCH",
                "Oracle callable code or source bytes changed after trusted capture.",
                layer="oracle_plan",
            )
        return trusted_projection, trusted_identity

    def issue_production_oracle_plan_draft(
        preparation: _ProductionPreparationCapability,
        context: Layer0Context,
        validation_run: ValidationRun,
    ) -> _PlanDraft:
        require_preparation(preparation, validation_run=validation_run)
        run_id = production_run_id(validation_run)
        implementation_callable, _ = require_trusted_oracle_callable()
        projection = build_projection(
            context=context,
            validation_run_id=run_id,
            implementation_callable=implementation_callable,
        )
        persistent_id = compute_plan_id(
            projection,
            expected_callable=implementation_callable,
        )
        capability: OraclePlan = cast(
            OraclePlan,
            allocate_plan(
                preparation,
                validation_run,
                capability_type=production_plan_type,
                kind="oracle",
                role="oracle",
                persistent_id=persistent_id,
            ),
        )
        draft = draft_type(
            capability=capability,
            kind="oracle",
            role="oracle",
            persistent_id=persistent_id,
            validation_run=validation_run,
            validation_run_id=run_id,
            projection=projection,
        )
        record_plan(preparation, validation_run, draft)
        require_preparation(preparation, validation_run=validation_run)
        return draft

    return require_trusted_oracle_callable, issue_production_oracle_plan_draft


(
    _require_trusted_oracle_callable,
    _issue_production_oracle_plan_draft,
) = _install_stage1_oracle_plan_authority()
_issue_production_oracle_plan_draft = cast(
    Callable[[_ProductionPreparationCapability, Layer0Context, ValidationRun], _PlanDraft],
    _register_production_component_callable(
        "oracle_plan",
        _issue_production_oracle_plan_draft,
    ),
)


def validate_oracle_conformance_result(
    result: OracleConformanceResult,
    *,
    binding: OracleEvidenceBinding,
) -> OracleConformanceResult:
    """Require exact issued production evidence and compare it to the frozen target."""

    _validate_expected_conformance(
        result,
        binding=binding,
        expected_key_count=EXPECTED_ORACLE_KEY_COUNT,
        expected_unique_key_count=EXPECTED_ORACLE_KEY_COUNT,
        expected_partition_counts=EXPECTED_ORACLE_PARTITION_COUNTS,
        expected_sha256=EXPECTED_ORACLE_DOMAIN_SHA256,
    )
    return result


def _execute_oracle_fixture(
    binding: OracleFixtureBinding,
    partitions: Iterable[OraclePartition],
) -> OracleFixtureResult:
    """Issue non-authoritative data from a deliberately small deterministic fixture."""

    return _execute_oracle_fixture_partitions(
        binding,
        partitions,
        issuance_key=_FIXTURE_ISSUANCE_KEY,
    )


def _validate_oracle_fixture_result(
    result: OracleFixtureResult,
    *,
    binding: OracleFixtureBinding,
    expected_key_count: int,
    expected_unique_key_count: int,
    expected_partition_counts: tuple[tuple[str, int], ...],
    expected_sha256: str,
) -> OracleFixtureResult:
    """Validate a small fixture without making it acceptable as production evidence."""

    _validate_expected_fixture_conformance(
        result,
        binding=binding,
        expected_key_count=expected_key_count,
        expected_unique_key_count=expected_unique_key_count,
        expected_partition_counts=expected_partition_counts,
        expected_sha256=expected_sha256,
    )
    return result


def _issue_oracle_conformance_fixture(
    binding: OracleFixtureBinding,
    partitions: Iterable[OraclePartition],
    *,
    expected_key_count: int,
    expected_unique_key_count: int,
    expected_partition_counts: tuple[tuple[str, int], ...],
    expected_sha256: str,
) -> OracleFixtureEvidence:
    """Execute and bind one small fixture to a non-production consumer capability."""

    result = _execute_oracle_fixture(binding, partitions)
    _validate_oracle_fixture_result(
        result,
        binding=binding,
        expected_key_count=expected_key_count,
        expected_unique_key_count=expected_unique_key_count,
        expected_partition_counts=expected_partition_counts,
        expected_sha256=expected_sha256,
    )
    fixture_identity = protocol_hash(
        "oracle_conformance_fixture_evidence/v1",
        {
            "evidence_binding_identity": binding.binding_identity,
            "execution_identity": result.execution_identity,
        },
    )
    evidence = OracleFixtureEvidence(
        result=result,
        binding=binding,
        fixture_identity=fixture_identity,
        _construction_key=_FIXTURE_EVIDENCE_CONSTRUCTION_KEY,
    )
    record = _IssuedOracleFixtureEvidence(
        evidence=evidence,
        result=result,
        binding=binding,
        fingerprint=_fixture_evidence_fingerprint(evidence),
    )
    with _EVIDENCE_LOCK:
        _require_issued_fixture_result(
            result,
            binding=binding,
        )
        _ISSUED_ORACLE_FIXTURE_EVIDENCE[id(evidence)] = record
    return evidence


def _validate_oracle_fixture_evidence(
    evidence: OracleFixtureEvidence,
) -> OracleFixtureEvidence:
    """Require an exact, current fixture capability in the fixture-only trust domain."""

    if type(evidence) is not OracleFixtureEvidence:
        raise OracleError("Fixture Oracle evidence requires an exact issued capability.")
    with _EVIDENCE_LOCK:
        record = _ISSUED_ORACLE_FIXTURE_EVIDENCE.get(id(evidence))
    if record is None or record.evidence is not evidence:
        raise OracleError("Fixture Oracle evidence capability is forged or stale.")
    if evidence.result is not record.result or evidence.binding is not record.binding:
        raise OracleError("Fixture Oracle evidence differs from its issued result binding.")
    if record.fingerprint != _fixture_evidence_fingerprint(evidence):
        raise OracleError("Fixture Oracle evidence differs from its issued fingerprint.")
    expected_identity = protocol_hash(
        "oracle_conformance_fixture_evidence/v1",
        {
            "evidence_binding_identity": evidence.binding.binding_identity,
            "execution_identity": evidence.result.execution_identity,
        },
    )
    if evidence.fixture_identity != expected_identity:
        raise OracleError("Fixture Oracle evidence identity does not reconcile.")
    _require_issued_fixture_result(
        evidence.result,
        binding=evidence.binding,
    )
    if evidence.result.execution_status != "COMPLETED" or evidence.result.failure_details:
        raise OracleError("Fixture Oracle enumeration did not complete successfully.")
    return evidence


def _execute_oracle_fixture_partitions(
    binding: OracleFixtureBinding,
    partitions: Iterable[OraclePartition],
    *,
    issuance_key: object,
) -> OracleFixtureResult:
    if issuance_key is not _FIXTURE_ISSUANCE_KEY:
        raise TypeError("Oracle fixture issuer is not authorized.")
    _claim_oracle_fixture_execution(binding)
    enumeration = _enumerate_oracle_partitions(partitions)
    _require_issued_fixture_binding(binding, require_active=True, require_current=True)
    oracle_source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    actual_values = _enumeration_execution_values(
        enumeration,
        binding=binding,
        oracle_source_sha256=oracle_source_sha256,
        issuer_kind="fixture",
    )
    result = OracleFixtureResult(
        conformance_version=CONFORMANCE_GENERATOR_VERSION,
        oracle_version=ORACLE_VERSION,
        execution_status=enumeration.execution_status,
        actual_key_count=enumeration.actual_key_count,
        actual_unique_key_count=enumeration.actual_unique_key_count,
        actual_partition_counts=enumeration.actual_partition_counts,
        actual_sha256=enumeration.actual_sha256,
        oracle_source_sha256=oracle_source_sha256,
        implementation_commit=binding.implementation_commit,
        design_checkpoint_commit=binding.design_checkpoint_commit,
        source_design_sha256=binding.source_design_sha256,
        implementation_source_sha256=binding.implementation_source_sha256,
        implementation_test_sha256=binding.implementation_test_sha256,
        validation_run_identity=binding.validation_run_identity,
        evidence_bundle_identity=binding.evidence_bundle_identity,
        evidence_binding_identity=binding.binding_identity,
        execution_identity=protocol_hash("oracle_fixture_execution/v1", actual_values),
        failure_details=enumeration.failure_details,
        _construction_key=_FIXTURE_RESULT_CONSTRUCTION_KEY,
    )
    record = _IssuedOracleFixtureResult(
        result=result,
        binding=binding,
        fingerprint=_fixture_result_fingerprint(result),
    )
    with _EVIDENCE_LOCK:
        binding_record = _ISSUED_ORACLE_FIXTURE_BINDINGS.get(id(binding))
        if (
            binding_record is None
            or binding_record.binding is not binding
            or not binding_record.active
        ):
            raise OracleError("Oracle fixture binding became stale during enumeration.")
        _ISSUED_ORACLE_FIXTURE_RESULTS[id(result)] = record
    return result


def _enumerate_oracle_partitions(
    partitions: Iterable[OraclePartition],
) -> _OracleEnumeration:
    digest = hashlib.sha256()
    actual_key_count = 0
    unique_keys: set[OracleKey] = set()
    partition_counts: list[tuple[str, int]] = []
    observed_partition_names: set[str] = set()
    active_partition_name: str | None = None
    active_partition_count = 0
    status: OracleExecutionStatus = "COMPLETED"
    failure_details: tuple[str, ...] = ()
    try:
        for partition_name, keys in partitions:
            active_partition_name = partition_name
            active_partition_count = 0
            if not isinstance(partition_name, str) or not partition_name:
                raise OracleError("Oracle conformance partition name is empty or malformed.")
            if partition_name in observed_partition_names:
                raise OracleError("Oracle conformance partition names must be unique.")
            observed_partition_names.add(partition_name)
            for key in keys:
                active_partition_count += 1
                actual_key_count += 1
                if type(key) is not tuple or not all(isinstance(item, str) for item in key):
                    raise OracleError("Oracle conformance enumerated a malformed key.")
                unique_keys.add(key)
                transformed = transform_key(key)
                line = (
                    key[0],
                    transformed.serialized_key.hex(),
                    transformed.digest_hex,
                    transformed.u_string,
                    transformed.z_string,
                )
                digest.update(canonical_json_bytes(line, final_lf=True))
            partition_counts.append((partition_name, active_partition_count))
            active_partition_name = None
            active_partition_count = 0
    except Exception as error:
        status = "FAILED"
        if active_partition_name is not None:
            partition_counts.append((active_partition_name, active_partition_count))
        failure_details = (f"{type(error).__module__}.{type(error).__qualname__}: {error}",)

    return _OracleEnumeration(
        execution_status=status,
        actual_key_count=actual_key_count,
        actual_unique_key_count=len(unique_keys),
        actual_partition_counts=tuple(partition_counts),
        actual_sha256=digest.hexdigest(),
        failure_details=failure_details,
    )


def _validate_expected_conformance(
    result: OracleConformanceResult,
    *,
    binding: OracleEvidenceBinding,
    expected_key_count: int,
    expected_unique_key_count: int,
    expected_partition_counts: tuple[tuple[str, int], ...],
    expected_sha256: str,
) -> None:
    _require_issued_result(
        result,
        binding=binding,
    )
    if result.execution_status != "COMPLETED" or result.failure_details:
        raise OracleError("Oracle conformance execution did not complete successfully.")
    if result.actual_key_count != sum(count for _, count in result.actual_partition_counts):
        raise OracleError("Oracle conformance partition counts do not sum to the actual total.")
    if result.actual_key_count != expected_key_count:
        raise OracleError(
            f"Oracle conformance enumerated {result.actual_key_count} keys, "
            f"not {expected_key_count}."
        )
    if result.actual_unique_key_count != expected_unique_key_count:
        raise OracleError(
            f"Oracle conformance enumerated {result.actual_unique_key_count} unique keys, "
            f"not {expected_unique_key_count}."
        )
    if result.actual_partition_counts != expected_partition_counts:
        raise OracleError("Oracle conformance partition counts differ from the required target.")
    if result.actual_sha256 != expected_sha256:
        raise OracleError(
            "Oracle conformance digest mismatch: "
            f"observed {result.actual_sha256}, expected {expected_sha256}."
        )
    _require_issued_result(result, binding=binding)


def _validate_expected_fixture_conformance(
    result: OracleFixtureResult,
    *,
    binding: OracleFixtureBinding,
    expected_key_count: int,
    expected_unique_key_count: int,
    expected_partition_counts: tuple[tuple[str, int], ...],
    expected_sha256: str,
) -> None:
    _require_issued_fixture_result(result, binding=binding)
    if result.execution_status != "COMPLETED" or result.failure_details:
        raise OracleError("Oracle fixture execution did not complete successfully.")
    if result.actual_key_count != sum(count for _, count in result.actual_partition_counts):
        raise OracleError("Oracle fixture partition counts do not sum to the actual total.")
    if result.actual_key_count != expected_key_count:
        raise OracleError(
            f"Oracle fixture enumerated {result.actual_key_count} keys, not {expected_key_count}."
        )
    if result.actual_unique_key_count != expected_unique_key_count:
        raise OracleError(
            "Oracle fixture enumerated "
            f"{result.actual_unique_key_count} unique keys, not {expected_unique_key_count}."
        )
    if result.actual_partition_counts != expected_partition_counts:
        raise OracleError("Oracle fixture partition counts differ from the required target.")
    if result.actual_sha256 != expected_sha256:
        raise OracleError(
            "Oracle fixture digest mismatch: "
            f"observed {result.actual_sha256}, expected {expected_sha256}."
        )
    _require_issued_fixture_result(result, binding=binding)


def _production_oracle_conformance_partitions() -> Iterator[OraclePartition]:
    """Yield the four frozen partitions without exposing them to policy code."""

    yield "full_decision", _full_decision_keys()
    yield "full_calibration", _full_calibration_keys()
    yield "smoke_decision", _smoke_decision_keys()
    yield "smoke_calibration", _smoke_calibration_keys()


def _full_decision_keys() -> Iterator[OracleKey]:
    for world in WORLDS:
        for seed in FULL_SEEDS:
            yield from _decision_keys(world.public.world_id, seed)


def _full_calibration_keys() -> Iterator[OracleKey]:
    for world in WORLDS:
        for seed in FULL_SEEDS:
            yield from _calibration_keys(world.public.world_id, seed)


def _smoke_decision_keys() -> Iterator[OracleKey]:
    for world_id in SMOKE_WORLD_IDS:
        for seed in SMOKE_SEEDS:
            yield from _decision_keys(world_id, seed)


def _smoke_calibration_keys() -> Iterator[OracleKey]:
    for world_id in SMOKE_WORLD_IDS:
        for seed in SMOKE_SEEDS:
            yield from _calibration_keys(world_id, seed)


def _decision_keys(world_id: str, seed: int) -> Iterator[tuple[str, ...]]:
    for candidate_id in DECISION_ORACLE_CANDIDATE_IDS:
        definition = CANDIDATES_BY_ID[candidate_id]
        yield decision_key(
            world_id=world_id,
            seed=seed,
            candidate_id=candidate_id,
            replication_id=definition.replication_id,
        )


def _calibration_keys(world_id: str, seed: int) -> Iterator[tuple[str, ...]]:
    for group_index, group_id in enumerate(GROUP_IDS):
        for arm in ("adam", "sgd"):
            for replication_index in range(1, 6):
                yield calibration_key(
                    world_id=world_id,
                    seed=seed,
                    comparison_group_id=group_id,
                    intervention_arm=arm,
                    replication_id=(f"calibration-{group_index:02d}-r{replication_index:04d}"),
                )


def _validate_external_identity(value: str, label: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise OracleError(f"Oracle {label} identity is empty or noncanonical.")


def _binding_values(binding: OracleEvidenceBinding) -> dict[str, str]:
    return {
        "design_checkpoint_commit": binding.design_checkpoint_commit,
        "evidence_bundle_identity": binding.evidence_bundle_identity,
        "implementation_commit": binding.implementation_commit,
        "implementation_source_sha256": binding.implementation_source_sha256,
        "implementation_test_sha256": binding.implementation_test_sha256,
        "source_design_sha256": binding.source_design_sha256,
        "validation_run_identity": binding.validation_run_identity,
    }


def _binding_fingerprint(binding: OracleEvidenceBinding) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {**_binding_values(binding), "binding_identity": binding.binding_identity},
            final_lf=True,
        )
    ).hexdigest()


def _fixture_binding_values(binding: OracleFixtureBinding) -> dict[str, str]:
    return {
        "design_checkpoint_commit": binding.design_checkpoint_commit,
        "evidence_bundle_identity": binding.evidence_bundle_identity,
        "implementation_commit": binding.implementation_commit,
        "implementation_source_sha256": binding.implementation_source_sha256,
        "implementation_test_sha256": binding.implementation_test_sha256,
        "source_design_sha256": binding.source_design_sha256,
        "validation_run_identity": binding.validation_run_identity,
    }


def _fixture_binding_fingerprint(binding: OracleFixtureBinding) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                **_fixture_binding_values(binding),
                "binding_identity": binding.binding_identity,
            },
            final_lf=True,
        )
    ).hexdigest()


def _enumeration_execution_values(
    enumeration: _OracleEnumeration,
    *,
    binding: OracleEvidenceBinding | OracleFixtureBinding,
    oracle_source_sha256: str,
    issuer_kind: Literal["production", "fixture"],
) -> dict[str, object]:
    return {
        "actual_key_count": enumeration.actual_key_count,
        "actual_partition_counts": list(enumeration.actual_partition_counts),
        "actual_sha256": enumeration.actual_sha256,
        "actual_unique_key_count": enumeration.actual_unique_key_count,
        "conformance_version": CONFORMANCE_GENERATOR_VERSION,
        "design_checkpoint_commit": binding.design_checkpoint_commit,
        "evidence_binding_identity": binding.binding_identity,
        "evidence_bundle_identity": binding.evidence_bundle_identity,
        "execution_status": enumeration.execution_status,
        "failure_details": list(enumeration.failure_details),
        "implementation_commit": binding.implementation_commit,
        "implementation_source_sha256": binding.implementation_source_sha256,
        "implementation_test_sha256": binding.implementation_test_sha256,
        "issuer_kind": issuer_kind,
        "oracle_source_sha256": oracle_source_sha256,
        "oracle_version": ORACLE_VERSION,
        "source_design_sha256": binding.source_design_sha256,
        "validation_run_identity": binding.validation_run_identity,
    }


def _execution_values(result: OracleConformanceResult) -> dict[str, object]:
    return {
        "actual_key_count": result.actual_key_count,
        "actual_partition_counts": list(result.actual_partition_counts),
        "actual_sha256": result.actual_sha256,
        "actual_unique_key_count": result.actual_unique_key_count,
        "conformance_version": result.conformance_version,
        "design_checkpoint_commit": result.design_checkpoint_commit,
        "evidence_binding_identity": result.evidence_binding_identity,
        "evidence_bundle_identity": result.evidence_bundle_identity,
        "execution_status": result.execution_status,
        "failure_details": list(result.failure_details),
        "implementation_commit": result.implementation_commit,
        "implementation_source_sha256": result.implementation_source_sha256,
        "implementation_test_sha256": result.implementation_test_sha256,
        "issuer_kind": result.issuer_kind,
        "oracle_source_sha256": result.oracle_source_sha256,
        "oracle_version": result.oracle_version,
        "source_design_sha256": result.source_design_sha256,
        "validation_run_identity": result.validation_run_identity,
    }


def _result_fingerprint(result: OracleConformanceResult) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {**_execution_values(result), "execution_identity": result.execution_identity},
            final_lf=True,
        )
    ).hexdigest()


def _fixture_execution_values(result: OracleFixtureResult) -> dict[str, object]:
    return {
        "actual_key_count": result.actual_key_count,
        "actual_partition_counts": list(result.actual_partition_counts),
        "actual_sha256": result.actual_sha256,
        "actual_unique_key_count": result.actual_unique_key_count,
        "conformance_version": result.conformance_version,
        "design_checkpoint_commit": result.design_checkpoint_commit,
        "evidence_binding_identity": result.evidence_binding_identity,
        "evidence_bundle_identity": result.evidence_bundle_identity,
        "execution_status": result.execution_status,
        "failure_details": list(result.failure_details),
        "implementation_commit": result.implementation_commit,
        "implementation_source_sha256": result.implementation_source_sha256,
        "implementation_test_sha256": result.implementation_test_sha256,
        "issuer_kind": "fixture",
        "oracle_source_sha256": result.oracle_source_sha256,
        "oracle_version": result.oracle_version,
        "source_design_sha256": result.source_design_sha256,
        "validation_run_identity": result.validation_run_identity,
    }


def _fixture_result_fingerprint(result: OracleFixtureResult) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                **_fixture_execution_values(result),
                "execution_identity": result.execution_identity,
            },
            final_lf=True,
        )
    ).hexdigest()


def _fixture_evidence_fingerprint(evidence: OracleFixtureEvidence) -> str:
    return protocol_hash(
        "oracle_conformance_fixture_evidence_fingerprint/v1",
        {
            "evidence_binding_identity": evidence.binding.binding_identity,
            "execution_identity": evidence.result.execution_identity,
            "fixture_identity": evidence.fixture_identity,
        },
    )


def _require_issued_binding(
    binding: OracleEvidenceBinding,
    *,
    require_active: bool,
    require_current: bool,
) -> _IssuedOracleEvidenceBinding:
    if type(binding) is not OracleEvidenceBinding:
        raise OracleError("Oracle evidence requires an exact issued binding.")
    with _EVIDENCE_LOCK:
        record = _ISSUED_ORACLE_EVIDENCE_BINDINGS.get(id(binding))
    if record is None or record.binding is not binding:
        raise OracleError("Oracle evidence binding is forged or stale.")
    observed_fingerprint = _binding_fingerprint(binding)
    if record.fingerprint != observed_fingerprint:
        raise OracleError("Oracle evidence binding differs from its issued fingerprint.")
    expected_binding_identity = protocol_hash(
        "oracle_evidence_binding/v1",
        _binding_values(binding),
    )
    if binding.binding_identity != expected_binding_identity:
        raise OracleError("Oracle evidence binding identity does not reconcile.")
    if require_active and not record.active:
        raise OracleError("Oracle evidence binding is stale.")
    if require_current:
        current = _current_oracle_identities()
        observed = (
            binding.implementation_commit,
            binding.design_checkpoint_commit,
            binding.source_design_sha256,
            binding.implementation_source_sha256,
            binding.implementation_test_sha256,
        )
        expected = (
            current.implementation_commit,
            current.design_checkpoint_commit,
            current.source_design_sha256,
            current.implementation_source_sha256,
            current.implementation_test_sha256,
        )
        if observed != expected:
            raise OracleError("Oracle evidence binding differs from current source identities.")
    with _EVIDENCE_LOCK:
        current_record = _ISSUED_ORACLE_EVIDENCE_BINDINGS.get(id(binding))
        if (
            current_record is not record
            or current_record.binding is not binding
            or current_record.fingerprint != observed_fingerprint
        ):
            raise OracleError("Oracle evidence binding is forged or stale.")
        if require_active and not current_record.active:
            raise OracleError("Oracle evidence binding is stale.")
    return record


def _claim_oracle_conformance_execution(
    binding: OracleEvidenceBinding,
) -> _IssuedOracleEvidenceBinding:
    """Atomically reserve one binding for exactly one enumeration attempt."""

    record = _require_issued_binding(binding, require_active=True, require_current=True)
    with _EVIDENCE_LOCK:
        current = _ISSUED_ORACLE_EVIDENCE_BINDINGS.get(id(binding))
        if current is not record or current.binding is not binding or not current.active:
            raise OracleError("Oracle evidence binding is forged or stale.")
        if current.execution_claimed:
            raise OracleError("Oracle evidence binding already claimed an execution attempt.")
        current.execution_claimed = True
    return record


def _require_issued_fixture_binding(
    binding: OracleFixtureBinding,
    *,
    require_active: bool,
    require_current: bool,
) -> _IssuedOracleFixtureBinding:
    if type(binding) is not OracleFixtureBinding:
        raise OracleError("Oracle fixture evidence requires an exact issued fixture binding.")
    with _EVIDENCE_LOCK:
        record = _ISSUED_ORACLE_FIXTURE_BINDINGS.get(id(binding))
    if record is None or record.binding is not binding:
        raise OracleError("Oracle fixture binding is forged or stale.")
    observed_fingerprint = _fixture_binding_fingerprint(binding)
    if record.fingerprint != observed_fingerprint:
        raise OracleError("Oracle fixture binding differs from its issued fingerprint.")
    expected_identity = protocol_hash(
        "oracle_fixture_binding/v1",
        _fixture_binding_values(binding),
    )
    if binding.binding_identity != expected_identity:
        raise OracleError("Oracle fixture binding identity does not reconcile.")
    if require_active and not record.active:
        raise OracleError("Oracle fixture binding is stale.")
    if require_current:
        current = _current_oracle_identities()
        observed = (
            binding.implementation_commit,
            binding.design_checkpoint_commit,
            binding.source_design_sha256,
            binding.implementation_source_sha256,
            binding.implementation_test_sha256,
        )
        expected = (
            current.implementation_commit,
            current.design_checkpoint_commit,
            current.source_design_sha256,
            current.implementation_source_sha256,
            current.implementation_test_sha256,
        )
        if observed != expected:
            raise OracleError("Oracle fixture binding differs from current source identities.")
    with _EVIDENCE_LOCK:
        current_record = _ISSUED_ORACLE_FIXTURE_BINDINGS.get(id(binding))
        if (
            current_record is not record
            or current_record.binding is not binding
            or current_record.fingerprint != observed_fingerprint
        ):
            raise OracleError("Oracle fixture binding is forged or stale.")
        if require_active and not current_record.active:
            raise OracleError("Oracle fixture binding is stale.")
    return record


def _claim_oracle_fixture_execution(
    binding: OracleFixtureBinding,
) -> _IssuedOracleFixtureBinding:
    """Atomically reserve one fixture binding for one terminal enumeration attempt."""

    record = _require_issued_fixture_binding(
        binding,
        require_active=True,
        require_current=True,
    )
    with _EVIDENCE_LOCK:
        current = _ISSUED_ORACLE_FIXTURE_BINDINGS.get(id(binding))
        if current is not record or current.binding is not binding or not current.active:
            raise OracleError("Oracle fixture binding is forged or stale.")
        if current.execution_claimed:
            raise OracleError("Oracle fixture binding already claimed an execution attempt.")
        current.execution_claimed = True
    return record


def _require_issued_result(
    result: OracleConformanceResult,
    *,
    binding: OracleEvidenceBinding,
) -> _IssuedOracleConformanceResult:
    _require_issued_binding(binding, require_active=True, require_current=True)
    if type(result) is not OracleConformanceResult:
        raise OracleError("Oracle conformance evidence requires an exact issued result.")
    with _EVIDENCE_LOCK:
        record = _ISSUED_ORACLE_CONFORMANCE_RESULTS.get(id(result))
    if record is None or record.result is not result:
        raise OracleError("Oracle conformance result is forged or stale.")
    if record.binding is not binding:
        raise OracleError("Oracle conformance result belongs to another evidence binding.")
    if result.issuer_kind != "production":
        raise OracleError("Oracle conformance result was not issued by the production enumerator.")
    if record.fingerprint != _result_fingerprint(result):
        raise OracleError("Oracle conformance result differs from its issued fingerprint.")
    if result.execution_identity != protocol_hash(
        "oracle_conformance_execution/v1", _execution_values(result)
    ):
        raise OracleError("Oracle conformance execution identity does not reconcile.")
    binding_values = (
        result.implementation_commit,
        result.design_checkpoint_commit,
        result.source_design_sha256,
        result.implementation_source_sha256,
        result.implementation_test_sha256,
        result.validation_run_identity,
        result.evidence_bundle_identity,
        result.evidence_binding_identity,
    )
    expected_binding_values = (
        binding.implementation_commit,
        binding.design_checkpoint_commit,
        binding.source_design_sha256,
        binding.implementation_source_sha256,
        binding.implementation_test_sha256,
        binding.validation_run_identity,
        binding.evidence_bundle_identity,
        binding.binding_identity,
    )
    if binding_values != expected_binding_values:
        raise OracleError("Oracle conformance result source or run binding differs.")
    current = _current_oracle_identities()
    if (
        result.conformance_version != CONFORMANCE_GENERATOR_VERSION
        or result.oracle_version != ORACLE_VERSION
        or result.oracle_source_sha256 != current.oracle_source_sha256
    ):
        raise OracleError("Oracle conformance implementation identity differs.")
    _require_issued_binding(binding, require_active=True, require_current=True)
    return record


def _require_issued_fixture_result(
    result: OracleFixtureResult,
    *,
    binding: OracleFixtureBinding,
) -> _IssuedOracleFixtureResult:
    _require_issued_fixture_binding(binding, require_active=True, require_current=True)
    if type(result) is not OracleFixtureResult:
        raise OracleError("Oracle fixture evidence requires an exact issued fixture result.")
    with _EVIDENCE_LOCK:
        record = _ISSUED_ORACLE_FIXTURE_RESULTS.get(id(result))
    if record is None or record.result is not result:
        raise OracleError("Oracle fixture result is forged or stale.")
    if record.binding is not binding:
        raise OracleError("Oracle fixture result belongs to another fixture binding.")
    if record.fingerprint != _fixture_result_fingerprint(result):
        raise OracleError("Oracle fixture result differs from its issued fingerprint.")
    if result.execution_identity != protocol_hash(
        "oracle_fixture_execution/v1",
        _fixture_execution_values(result),
    ):
        raise OracleError("Oracle fixture execution identity does not reconcile.")
    observed_binding = (
        result.implementation_commit,
        result.design_checkpoint_commit,
        result.source_design_sha256,
        result.implementation_source_sha256,
        result.implementation_test_sha256,
        result.validation_run_identity,
        result.evidence_bundle_identity,
        result.evidence_binding_identity,
    )
    expected_binding = (
        binding.implementation_commit,
        binding.design_checkpoint_commit,
        binding.source_design_sha256,
        binding.implementation_source_sha256,
        binding.implementation_test_sha256,
        binding.validation_run_identity,
        binding.evidence_bundle_identity,
        binding.binding_identity,
    )
    if observed_binding != expected_binding:
        raise OracleError("Oracle fixture result source or run binding differs.")
    current = _current_oracle_identities()
    if (
        result.conformance_version != CONFORMANCE_GENERATOR_VERSION
        or result.oracle_version != ORACLE_VERSION
        or result.oracle_source_sha256 != current.oracle_source_sha256
    ):
        raise OracleError("Oracle fixture implementation identity differs.")
    _require_issued_fixture_binding(binding, require_active=True, require_current=True)
    return record


def _current_oracle_identities() -> _CurrentOracleIdentities:
    root = repository_root().resolve(strict=True)
    git_root = Path(_git_text(root, "rev-parse", "--show-toplevel")).resolve(strict=True)
    if git_root != root:
        raise OracleError("Oracle evidence Git root differs from the repository root.")
    implementation_commit = _git_text(root, "rev-parse", "--verify", "HEAD^{commit}")
    if (
        re.fullmatch(r"[0-9a-f]{40}", implementation_commit) is None
        or implementation_commit in PUBLIC_PROVENANCE_ROLE_TOKENS
    ):
        raise OracleError("Oracle evidence implementation commit is not GIT40.")
    design_bytes = (root / DESIGN_FILENAME).read_bytes()
    checkpoint_design_bytes = _git_bytes(
        root,
        "show",
        f"{implementation_commit}:{DESIGN_FILENAME}",
    )
    if design_bytes != checkpoint_design_bytes:
        raise OracleError("Working design bytes differ from the frozen checkpoint.")
    implementation_paths = tuple(
        sorted((root / "research_decision_engine" / "benchmarks").glob("broader_*.py"))
    )
    test_paths = tuple(sorted((root / "tests").glob("test_broader*.py")))
    oracle_path = Path(__file__).resolve(strict=True)
    return _CurrentOracleIdentities(
        implementation_commit=implementation_commit,
        design_checkpoint_commit=SOURCE_CHECKPOINT,
        source_design_sha256=hashlib.sha256(design_bytes).hexdigest(),
        implementation_source_sha256=_source_bundle_hash(
            implementation_paths,
            domain="broader_smoke_implementation/v1",
        ),
        implementation_test_sha256=_source_bundle_hash(
            test_paths,
            domain="broader_smoke_tests/v1",
        ),
        oracle_source_sha256=hashlib.sha256(oracle_path.read_bytes()).hexdigest(),
    )


def _source_bundle_hash(paths: tuple[Path, ...], *, domain: str) -> str:
    root = repository_root()
    records = tuple(
        (path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest())
        for path in paths
    )
    return protocol_hash(
        domain,
        {"files": [{"path": path, "sha256": sha256} for path, sha256 in records]},
    )


def _git_text(root: Path, *arguments: str) -> str:
    return _git_bytes(root, *arguments).decode("utf-8").strip()


def _git_bytes(root: Path, *arguments: str) -> bytes:
    git = shutil.which("git")
    if git is None:
        raise OracleError("Git executable is unavailable for Oracle evidence binding.")
    completed = subprocess.run(
        (git, *arguments),
        cwd=root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise OracleError(f"Git identity command failed: {detail}")
    return completed.stdout


def _decimal_context() -> Context:
    context = Context(
        prec=80,
        rounding=ROUND_HALF_EVEN,
        Emin=-999999,
        Emax=999999,
        capitals=1,
        clamp=0,
    )
    context.traps[InvalidOperation] = True
    context.traps[DivisionByZero] = True
    context.traps[Overflow] = True
    context.traps[FloatOperation] = True
    context.traps[Underflow] = False
    context.traps[Subnormal] = False
    context.traps[Inexact] = False
    context.traps[Rounded] = False
    context.traps[Clamped] = False
    context.clear_flags()
    return context


def _acklam(u: Decimal) -> Decimal:
    if u < _P_LOW:
        q = (-Decimal(2) * u.ln()).sqrt()
        return _polynomial_six(q, _C) / _denominator_five(q, _D)
    if u <= _P_HIGH:
        q = u - Decimal("0.5")
        r = q * q
        return (_polynomial_six(r, _A) * q) / _denominator_six(r, _B)
    q = (-Decimal(2) * (Decimal(1) - u).ln()).sqrt()
    return -(_polynomial_six(q, _C) / _denominator_five(q, _D))


def _polynomial_six(value: Decimal, coefficients: tuple[Decimal, ...]) -> Decimal:
    result = coefficients[0]
    for coefficient in coefficients[1:]:
        result = result * value + coefficient
    return result


def _denominator_five(value: Decimal, coefficients: tuple[Decimal, ...]) -> Decimal:
    result = coefficients[0]
    for coefficient in coefficients[1:]:
        result = result * value + coefficient
    return result * value + Decimal(1)


def _denominator_six(value: Decimal, coefficients: tuple[Decimal, ...]) -> Decimal:
    result = coefficients[0]
    for coefficient in coefficients[1:]:
        result = result * value + coefficient
    return result * value + Decimal(1)


def _parse_calibration_candidate(candidate_id: str) -> tuple[str, str, str]:
    parts = candidate_id.split("-")
    if len(parts) != 4 or parts[0] != "cal" or parts[2] not in {"adam", "sgd"}:
        raise OracleError(f"Malformed calibration candidate ID: {candidate_id}")
    if not parts[1].isdigit() or not parts[3].startswith("r"):
        raise OracleError(f"Malformed calibration candidate ID: {candidate_id}")
    group_index = int(parts[1])
    replication_index = int(parts[3][1:])
    if group_index not in range(3) or replication_index not in range(1, 6):
        raise OracleError(f"Calibration candidate ID is out of range: {candidate_id}")
    return (
        f"group-{group_index:02d}",
        parts[2],
        f"calibration-{group_index:02d}-r{replication_index:04d}",
    )


def _revealed_record(
    *,
    authorization: ObservationAuthorization,
    key: tuple[str, ...],
    transform: OracleTransform,
    observed: float,
    comparison_group_id: str | None,
    intervention_arm: str | None,
    replication_id: str,
) -> RevealedObservation:
    oracle_key_id = runtime_id("oracle-key", "oracle_key_id/v1", {"key_fields": list(key)})
    oracle_use_id = f"oracle-use/{authorization.authorization_id}/{oracle_key_id}"
    outcome_digest = protocol_hash(
        "revealed_outcome/v1",
        {"oracle_key_id": oracle_key_id, "revealed_observation": f64(observed)},
    )
    return RevealedObservation(
        oracle_key_id=oracle_key_id,
        oracle_use_id=oracle_use_id,
        authorization_id=authorization.authorization_id,
        namespace=key[0],
        world_id=key[3],
        seed=int(key[4]),
        candidate_id=authorization.candidate_id,
        comparison_group_id=comparison_group_id,
        intervention_arm=intervention_arm,
        replication_id=replication_id,
        key_fields=key,
        serialized_key_hex=transform.serialized_key.hex(),
        digest=transform.digest_hex,
        u=transform.u_string,
        z=transform.z_string,
        revealed_observation=observed,
        outcome_digest=outcome_digest,
    )


def world_authority(world_id: str, seed: int) -> ObservationAuthority:
    return ObservationAuthority(world=WORLDS_BY_ID[world_id], seed=seed)


def reobserve_authorized_observation(
    *,
    world_id: str,
    seed: int,
    authorization: ObservationAuthorization,
) -> RevealedObservation:
    """Independently regenerate one persisted selected observation.

    This evaluator-only reconstruction path deliberately starts with a fresh authority. It
    therefore derives the namespace, Oracle key, transform, outcome, and all authorization
    bindings from the frozen world and protocol instead of accepting any stored observation
    field as authoritative.
    """

    try:
        world = WORLDS_BY_ID[world_id]
    except KeyError as error:
        raise OracleError(f"Unknown broader-replication world: {world_id}") from error
    authority = ObservationAuthority(world=world, seed=seed)
    return authority.selected_only_interface().observe_selected(authorization)
