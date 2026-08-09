"""Exact-issued executor/result attestations for broader-replication work."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import math
import os
import platform
import re
import secrets
import struct
import sys
import threading
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, fields, is_dataclass
from dataclasses import replace as dataclass_replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from types import CodeType, FunctionType, MappingProxyType
from typing import Final, Literal, NoReturn, SupportsIndex, cast

from research_decision_engine.benchmarks.broader_protocol import (
    PROTOCOL_CHECKPOINT,
    PROTOCOL_VERSION,
    canonical_json_bytes,
    f64,
    protocol_hash,
    repository_root,
)
from research_decision_engine.benchmarks.broader_returned_run import (
    ReturnedRunProjection,
    ReturnedRunProjectionError,
    decode_returned_run_projection,
    projection_as_dict,
    validate_returned_run_batch,
    validate_returned_run_projection_shape,
)
from research_decision_engine.benchmarks.broader_runner import BroaderArmRun
from research_decision_engine.benchmarks.broader_validation_evidence import (
    EVIDENCE_CONTRACT_CHECKPOINT,
    STUDY_ID,
    CallableProjection,
    ImplementationProjection,
    IssuerProjection,
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
    _require_production_preparation,
    _seal_production_component_callable,
    callable_projection,
)

# isort: split
from research_decision_engine.benchmarks.broader_validation_evidence import (
    FileProjection,
    InterpreterIdentityProjection,
    PlatformIdentityProjection,
    ValidationAuthorityProjection,
)
from research_decision_engine.benchmarks.broader_validation_evidence import (
    _opaque_runtime_callable as _trusted_opaque_runtime_callable,
)


def _opaque_runtime_callable(function: Callable[..., object]) -> Callable[..., object]:
    """Hide production registry closures behind a non-caching C call boundary."""

    return _trusted_opaque_runtime_callable(function)


type ExecutorKind = Literal["serial", "thread_pool"]
type ResultOrder = Literal["input_order", "completion_order"]
type ExecutionPurpose = Literal[
    "diagnostic",
    "smoke_validation",
    "production_conformance",
    "diagnostic_conformance",
    "full_study",
]
type ExecutorTrustDomain = Literal["production", "fixture"]
type P2ExecutionRole = Literal[
    "primary_smoke", "altered_order_replay", "fixture_primary", "fixture_replay"
]
type P2ExecutionConfiguration = tuple[
    Literal["smoke_validation", "production_conformance"],
    Literal["serial", "thread_pool"],
    int,
    str,
    Literal["input_order", "completion_order"],
    int,
]

_SPECIFICATION_CONSTRUCTION_KEY: Final = object()
_ATTESTATION_CONSTRUCTION_KEY: Final = object()
_FULL_STUDY_EXECUTION_KEY: Final = object()
_PRODUCTION_CONFORMANCE_EXECUTION_KEY: Final = object()
_DIAGNOSTIC_CONFORMANCE_EXECUTION_KEY: Final = object()
_SMOKE_VALIDATION_EXECUTION_KEY: Final = object()
_PROCESS_EXECUTOR_NONCE: Final = secrets.token_hex(32)
_EXECUTION_COUNTER = 0
_COUNTER_LOCK = threading.Lock()

_P2_EXECUTION_ROLE_ORDER: Final[tuple[P2ExecutionRole, ...]] = (
    "primary_smoke",
    "altered_order_replay",
    "fixture_primary",
    "fixture_replay",
)
_P2_EXECUTION_CONFIGURATIONS: Final[Mapping[P2ExecutionRole, P2ExecutionConfiguration]] = (
    MappingProxyType(
        {
            "primary_smoke": (
                "smoke_validation",
                "serial",
                1,
                "serial_call_in_input_order",
                "input_order",
                384,
            ),
            "altered_order_replay": (
                "smoke_validation",
                "thread_pool",
                2,
                "thread_pool_concurrent_submission",
                "input_order",
                384,
            ),
            "fixture_primary": (
                "production_conformance",
                "serial",
                1,
                "serial_call_in_input_order",
                "input_order",
                252,
            ),
            "fixture_replay": (
                "production_conformance",
                "serial",
                1,
                "serial_call_in_input_order",
                "input_order",
                252,
            ),
        }
    )
)
_P2_SMOKE_WORLD_IDS: Final = (
    "h_adam_low",
    "h_null_high",
    "w_sgd_medium",
    "g_adam_lmh",
    "g_null_hml",
    "c_sgd_a",
    "d2_null",
    "d3_adam",
)
_P2_SMOKE_SEEDS: Final = (9000, 9001, 9002, 9003)
_P2_BUDGETS: Final = (
    ("budget-2.25", 2.25),
    ("budget-4.50", 4.5),
    ("budget-6.75", 6.75),
)
_P2_ARMS: Final = (
    (1, "fixed_ig", "fixed_sigma_gaussian", "information_gain"),
    (2, "calibrated_ig", "replicated_noise_calibrated_gaussian", "information_gain"),
    (3, "fixed_lookahead", "fixed_sigma_gaussian", "lookahead_information_gain"),
    (
        4,
        "calibrated_lookahead",
        "replicated_noise_calibrated_gaussian",
        "lookahead_information_gain",
    ),
)
_P2_FIXTURE_WORLD_SEEDS: Final = (
    ("g_sgd_hml", tuple(range(1000, 1020))),
    ("d3_adam", (1000,)),
)
_EXECUTOR_ISSUER_ENTRY_POINT: Final = (
    "research_decision_engine.benchmarks.broader_execution.execute_deterministic_map"
)
_FIXTURE_EXECUTOR_ISSUER_ENTRY_POINT: Final = "fixture.execution_specification"


class ExecutorProvenanceError(ValueError):
    """Raised before scientific use when exact executor evidence disagrees."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "EXECUTOR_PROVENANCE_INVALID",
        validation_layer: str = "executor_attestation",
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.validation_layer = validation_layer
        self.scoring_entered = False
        self.scientific_output_entered = False


class ExecutorImplementationIdentity:
    """Opaque exact-issued P2 executor implementation capability."""

    __slots__ = ()

    def __new__(cls, construction_key: object | None = None) -> ExecutorImplementationIdentity:
        del construction_key
        raise TypeError("Production executor implementation identities have no public constructor.")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("Executor implementation identities cannot be subclassed.")

    def __copy__(self) -> NoReturn:
        raise TypeError("Executor implementation identities cannot be copied.")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("Executor implementation identities cannot be deep-copied.")

    def __reduce__(self) -> NoReturn:
        raise TypeError("Executor implementation identities cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Executor implementation identities cannot be serialized.")


class _FixtureExecutorImplementationIdentity:
    """Opaque fixture-only executor implementation capability."""

    __slots__ = ()

    def __new__(
        cls, construction_key: object | None = None
    ) -> _FixtureExecutorImplementationIdentity:
        del construction_key
        raise TypeError("Fixture executor implementation identities have no public constructor.")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("Fixture executor implementation identities cannot be subclassed.")

    def __copy__(self) -> NoReturn:
        raise TypeError("Fixture executor implementation identities cannot be copied.")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("Fixture executor implementation identities cannot be deep-copied.")

    def __reduce__(self) -> NoReturn:
        raise TypeError("Fixture executor implementation identities cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Fixture executor implementation identities cannot be serialized.")


@dataclass(frozen=True, slots=True)
class ValidationJobArmProjection:
    arm_id: str
    arm_order: int
    belief_model_id: str
    policy_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "arm_id": self.arm_id,
            "arm_order": self.arm_order,
            "belief_model_id": self.belief_model_id,
            "policy_id": self.policy_id,
        }


@dataclass(frozen=True, slots=True)
class ValidationJobProjection:
    """Handwritten closed pre-execution projection for one submitted job."""

    arm: ValidationJobArmProjection
    budget: str
    budget_id: str
    seed: int
    submission_index: int
    world_id: str
    schema_version: str = "broader-replication-validation-job/v1"

    def as_dict(self) -> dict[str, object]:
        return {
            "arm": self.arm.as_dict(),
            "budget": self.budget,
            "budget_id": self.budget_id,
            "schema_version": self.schema_version,
            "seed": self.seed,
            "submission_index": self.submission_index,
            "world_id": self.world_id,
        }


@dataclass(frozen=True, slots=True)
class SubmittedJobProjection:
    submitted_job_id: str
    projection: ValidationJobProjection

    def as_dict(self) -> dict[str, object]:
        return {
            "submitted_job_id": self.submitted_job_id,
            "projection": self.projection.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class ExecutorConfigurationProjection:
    callable_identity: str
    executor_kind: Literal["serial", "thread_pool"]
    result_delivery_mode: Literal["input_order", "completion_order"]
    scheduling_mode: str
    timeout_ms: int | None
    worker_count: int
    schema_version: str = "broader-replication-executor-configuration/v1"

    def as_dict(self) -> dict[str, object]:
        return {
            "callable_identity": self.callable_identity,
            "executor_kind": self.executor_kind,
            "result_delivery_mode": self.result_delivery_mode,
            "scheduling_mode": self.scheduling_mode,
            "schema_version": self.schema_version,
            "timeout_ms": self.timeout_ms,
            "worker_count": self.worker_count,
        }


@dataclass(frozen=True, slots=True)
class ExecutorImplementationProjection:
    callable: CallableProjection
    callable_identity: str
    implementation_tree_sha256: str
    schema_version: str = "broader-replication-executor-implementation/v1"

    def as_dict(self) -> dict[str, object]:
        return {
            "callable": self.callable.as_dict(),
            "callable_identity": self.callable_identity,
            "implementation_tree_sha256": self.implementation_tree_sha256,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ExecutionExpectedCompletionProjection:
    submitted_job_count: int
    all_jobs_accepted: Literal[True] = True
    all_results_required: Literal[True] = True
    required_status: Literal["success"] = "success"

    def as_dict(self) -> dict[str, object]:
        return {
            "all_jobs_accepted": self.all_jobs_accepted,
            "all_results_required": self.all_results_required,
            "required_status": self.required_status,
            "submitted_job_count": self.submitted_job_count,
        }


@dataclass(frozen=True, slots=True)
class ExecutionSpecificationProjection:
    """The sole frozen P2 authority-free executor-plan projection."""

    callable: CallableProjection
    callable_identity: str
    configuration: ExecutorConfigurationProjection
    configuration_sha256: str
    evidence_contract_checkpoint: str
    expected_completion: ExecutionExpectedCompletionProjection
    execution_purpose: Literal["smoke_validation", "production_conformance"]
    executor_kind: Literal["serial", "thread_pool"]
    executor_implementation: ExecutorImplementationProjection
    executor_implementation_identity: str
    implementation: ImplementationProjection
    normalized_execution_namespace: str
    protocol_checkpoint: str
    result_delivery_mode: Literal["input_order", "completion_order"]
    role: Literal["primary_smoke", "altered_order_replay", "fixture_primary", "fixture_replay"]
    runtime: RuntimeProjection
    runtime_identity: str
    scheduling_mode: str
    specification_issuer_identity: str
    submitted_jobs: tuple[SubmittedJobProjection, ...]
    timeout_ms: int | None
    validation_run_id: str
    worker_count: int
    schema_version: str = "broader-replication-execution-specification/v1"
    study_id: str = STUDY_ID
    trust_domain: Literal["production"] = "production"

    def as_dict(self) -> dict[str, object]:
        return {
            "callable": self.callable.as_dict(),
            "callable_identity": self.callable_identity,
            "configuration": self.configuration.as_dict(),
            "configuration_sha256": self.configuration_sha256,
            "evidence_contract_checkpoint": self.evidence_contract_checkpoint,
            "expected_completion": self.expected_completion.as_dict(),
            "execution_purpose": self.execution_purpose,
            "executor_kind": self.executor_kind,
            "executor_implementation": self.executor_implementation.as_dict(),
            "executor_implementation_identity": self.executor_implementation_identity,
            "implementation": self.implementation.as_dict(),
            "normalized_execution_namespace": self.normalized_execution_namespace,
            "protocol_checkpoint": self.protocol_checkpoint,
            "result_delivery_mode": self.result_delivery_mode,
            "role": self.role,
            "runtime": self.runtime.as_dict(),
            "runtime_identity": self.runtime_identity,
            "scheduling_mode": self.scheduling_mode,
            "schema_version": self.schema_version,
            "specification_issuer_identity": self.specification_issuer_identity,
            "study_id": self.study_id,
            "submitted_jobs": [job.as_dict() for job in self.submitted_jobs],
            "timeout_ms": self.timeout_ms,
            "trust_domain": self.trust_domain,
            "validation_run_id": self.validation_run_id,
            "worker_count": self.worker_count,
        }


@dataclass(frozen=True, slots=True)
class ExecutionInstanceProjection:
    counter: int
    issuer_identity: str
    process_id: int
    process_nonce: str
    process_started_at: str
    schema_version: Literal["broader-replication-execution-instance/v1"]

    def as_dict(self) -> dict[str, object]:
        return {
            "counter": self.counter,
            "issuer_identity": self.issuer_identity,
            "process_id": self.process_id,
            "process_nonce": self.process_nonce,
            "process_started_at": self.process_started_at,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ExecutionIdentityProjection:
    execution_instance: ExecutionInstanceProjection
    execution_instance_identity: str
    execution_specification_id: str
    implementation_commit: str
    implementation_diff_sha256: str
    implementation_tree_sha256: str
    oracle_binding_id: str
    oracle_execution_id: str
    protocol_checkpoint: Literal["89c0b4fadba33b9fd9a257b43eacf476b7779d59"]
    role: str
    runtime_identity: str
    schema_version: Literal["broader-replication-execution/v1"]
    study_id: str
    validation_authority_id: str
    validation_run_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "execution_instance": self.execution_instance.as_dict(),
            "execution_instance_identity": self.execution_instance_identity,
            "execution_specification_id": self.execution_specification_id,
            "implementation_commit": self.implementation_commit,
            "implementation_diff_sha256": self.implementation_diff_sha256,
            "implementation_tree_sha256": self.implementation_tree_sha256,
            "oracle_binding_id": self.oracle_binding_id,
            "oracle_execution_id": self.oracle_execution_id,
            "protocol_checkpoint": self.protocol_checkpoint,
            "role": self.role,
            "runtime_identity": self.runtime_identity,
            "schema_version": self.schema_version,
            "study_id": self.study_id,
            "validation_authority_id": self.validation_authority_id,
            "validation_run_id": self.validation_run_id,
        }


@dataclass(frozen=True, slots=True)
class SubmittedJobsProjection:
    configuration_sha256: str
    execution_id: str
    execution_specification_id: str
    implementation: ImplementationProjection
    jobs: tuple[SubmittedJobProjection, ...]
    oracle_binding_id: str
    oracle_execution_id: str
    protocol_checkpoint: Literal["89c0b4fadba33b9fd9a257b43eacf476b7779d59"]
    runtime: RuntimeProjection
    runtime_identity: str
    schema_version: Literal["broader-replication-submitted-jobs/v1"]
    study_id: Literal["broader-closed-loop-replication/v1"]
    validation_authority_id: str
    validation_run_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "configuration_sha256": self.configuration_sha256,
            "execution_id": self.execution_id,
            "execution_specification_id": self.execution_specification_id,
            "implementation": self.implementation.as_dict(),
            "jobs": [job.as_dict() for job in self.jobs],
            "oracle_binding_id": self.oracle_binding_id,
            "oracle_execution_id": self.oracle_execution_id,
            "protocol_checkpoint": self.protocol_checkpoint,
            "runtime": self.runtime.as_dict(),
            "runtime_identity": self.runtime_identity,
            "schema_version": self.schema_version,
            "study_id": self.study_id,
            "validation_authority_id": self.validation_authority_id,
            "validation_run_id": self.validation_run_id,
        }


@dataclass(frozen=True, slots=True)
class ExecutionStartProjection:
    execution_id: str
    execution_instance_identity: str
    execution_specification_id: str
    schema_version: Literal["broader-replication-execution-start/v1"]
    started_at: str
    validation_authority_id: str
    validation_run_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "execution_instance_identity": self.execution_instance_identity,
            "execution_specification_id": self.execution_specification_id,
            "schema_version": self.schema_version,
            "started_at": self.started_at,
            "validation_authority_id": self.validation_authority_id,
            "validation_run_id": self.validation_run_id,
        }


@dataclass(frozen=True, slots=True)
class WorkerIdentityProjection:
    execution_instance_identity: str
    execution_specification_id: str
    process_id: int
    schema_version: Literal["broader-replication-worker-identity/v1"]
    thread_id: int
    thread_name: str
    validation_authority_id: str
    validation_run_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "execution_instance_identity": self.execution_instance_identity,
            "execution_specification_id": self.execution_specification_id,
            "process_id": self.process_id,
            "schema_version": self.schema_version,
            "thread_id": self.thread_id,
            "thread_name": self.thread_name,
            "validation_authority_id": self.validation_authority_id,
            "validation_run_id": self.validation_run_id,
        }


@dataclass(frozen=True, slots=True)
class ReturnedResultProjection:
    execution_id: str
    execution_specification_id: str
    result_payload_sha256: str
    schema_version: Literal["broader-replication-returned-result/v1"]
    submitted_job_id: str
    validation_authority_id: str
    validation_run_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "execution_specification_id": self.execution_specification_id,
            "result_payload_sha256": self.result_payload_sha256,
            "schema_version": self.schema_version,
            "submitted_job_id": self.submitted_job_id,
            "validation_authority_id": self.validation_authority_id,
            "validation_run_id": self.validation_run_id,
        }


type JobResultMapping = tuple[tuple[str, str], ...]
type ReturnedResultObservation = tuple[
    ReturnedResultProjection,
    str,
    ReturnedRunProjection,
]


@dataclass(frozen=True, slots=True)
class ResultBatchProjection:
    execution_id: str
    execution_specification_id: str
    job_result_mapping: JobResultMapping
    result_payload_sha256_in_delivery_order: tuple[str, ...]
    returned_result_ids_in_delivery_order: tuple[str, ...]
    schema_version: Literal["broader-replication-result-batch/v1"]
    validation_authority_id: str
    validation_run_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "execution_specification_id": self.execution_specification_id,
            "job_result_mapping": [list(pair) for pair in self.job_result_mapping],
            "result_payload_sha256_in_delivery_order": list(
                self.result_payload_sha256_in_delivery_order
            ),
            "returned_result_ids_in_delivery_order": list(
                self.returned_result_ids_in_delivery_order
            ),
            "schema_version": self.schema_version,
            "validation_authority_id": self.validation_authority_id,
            "validation_run_id": self.validation_run_id,
        }


@dataclass(frozen=True, slots=True)
class ExecutionCompletionProjection:
    completed_at: str
    execution_id: str
    execution_specification_id: str
    execution_start_id: str
    execution_status: Literal["success"]
    job_result_mapping: JobResultMapping
    observed_worker_ids: tuple[str, ...]
    returned_result_ids_in_delivery_order: tuple[str, ...]
    schema_version: Literal["broader-replication-execution-completion/v1"]
    validation_authority_id: str
    validation_run_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "completed_at": self.completed_at,
            "execution_id": self.execution_id,
            "execution_specification_id": self.execution_specification_id,
            "execution_start_id": self.execution_start_id,
            "execution_status": self.execution_status,
            "job_result_mapping": [list(pair) for pair in self.job_result_mapping],
            "observed_worker_ids": list(self.observed_worker_ids),
            "returned_result_ids_in_delivery_order": list(
                self.returned_result_ids_in_delivery_order
            ),
            "schema_version": self.schema_version,
            "validation_authority_id": self.validation_authority_id,
            "validation_run_id": self.validation_run_id,
        }


@dataclass(frozen=True, slots=True)
class ReturnedResultsProjection:
    execution_completion_id: str
    execution_id: str
    execution_specification_id: str
    execution_status: Literal["success"]
    implementation: ImplementationProjection
    job_result_mapping: JobResultMapping
    oracle_binding_id: str
    oracle_execution_id: str
    protocol_checkpoint: Literal["89c0b4fadba33b9fd9a257b43eacf476b7779d59"]
    results_in_submission_order: tuple[tuple[str, ReturnedRunProjection, str], ...]
    runtime: RuntimeProjection
    runtime_identity: str
    schema_version: Literal["broader-replication-returned-results/v1"]
    study_id: Literal["broader-closed-loop-replication/v1"]
    validation_authority_id: str
    validation_run_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "execution_completion_id": self.execution_completion_id,
            "execution_id": self.execution_id,
            "execution_specification_id": self.execution_specification_id,
            "execution_status": self.execution_status,
            "implementation": self.implementation.as_dict(),
            "job_result_mapping": [list(pair) for pair in self.job_result_mapping],
            "oracle_binding_id": self.oracle_binding_id,
            "oracle_execution_id": self.oracle_execution_id,
            "protocol_checkpoint": self.protocol_checkpoint,
            "results_in_submission_order": [
                {
                    "returned_result_id": returned_result_id_value,
                    "projection": projection_as_dict(projection),
                    "submitted_job_id": submitted_job_id_value,
                }
                for returned_result_id_value, projection, submitted_job_id_value in (
                    self.results_in_submission_order
                )
            ],
            "runtime": self.runtime.as_dict(),
            "runtime_identity": self.runtime_identity,
            "schema_version": self.schema_version,
            "study_id": self.study_id,
            "validation_authority_id": self.validation_authority_id,
            "validation_run_id": self.validation_run_id,
        }


@dataclass(frozen=True, slots=True)
class WorkerResultOrderProjection:
    execution_completion_id: str
    execution_id: str
    execution_specification_id: str
    execution_status: Literal["success"]
    implementation: ImplementationProjection
    job_result_mapping: JobResultMapping
    oracle_binding_id: str
    oracle_execution_id: str
    protocol_checkpoint: Literal["89c0b4fadba33b9fd9a257b43eacf476b7779d59"]
    results_in_actual_delivery_order: tuple[tuple[int, str, WorkerIdentityProjection, str], ...]
    runtime: RuntimeProjection
    runtime_identity: str
    schema_version: Literal["broader-replication-worker-result-order/v1"]
    study_id: Literal["broader-closed-loop-replication/v1"]
    validation_authority_id: str
    validation_run_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "execution_completion_id": self.execution_completion_id,
            "execution_id": self.execution_id,
            "execution_specification_id": self.execution_specification_id,
            "execution_status": self.execution_status,
            "implementation": self.implementation.as_dict(),
            "job_result_mapping": [list(pair) for pair in self.job_result_mapping],
            "oracle_binding_id": self.oracle_binding_id,
            "oracle_execution_id": self.oracle_execution_id,
            "protocol_checkpoint": self.protocol_checkpoint,
            "results_in_actual_delivery_order": [
                {
                    "delivery_index": delivery_index,
                    "returned_result_id": returned_result_id_value,
                    "worker": worker.as_dict(),
                    "worker_identity": worker_identity_value,
                }
                for delivery_index, returned_result_id_value, worker, worker_identity_value in (
                    self.results_in_actual_delivery_order
                )
            ],
            "runtime": self.runtime.as_dict(),
            "runtime_identity": self.runtime_identity,
            "schema_version": self.schema_version,
            "study_id": self.study_id,
            "validation_authority_id": self.validation_authority_id,
            "validation_run_id": self.validation_run_id,
        }


@dataclass(frozen=True, slots=True)
class ExecutorAttestationProjection:
    accepted_job_ids: tuple[str, ...]
    actual_worker_count: int
    completed_at: str
    configured_worker_count: int
    configuration_sha256: str
    evidence_contract_checkpoint: str
    execution_completion_id: str
    execution_id: str
    execution_purpose: str
    execution_specification_id: str
    execution_start_id: str
    execution_status: Literal["success"]
    executor_implementation_identity: str
    executor_implementation: ExecutorImplementationProjection
    execution_instance_identity: str
    executor_kind: Literal["serial", "thread_pool"]
    implementation: ImplementationProjection
    job_result_mapping: JobResultMapping
    normalized_execution_namespace: str
    observed_worker_ids: tuple[str, ...]
    oracle_binding_id: str
    oracle_execution_id: str
    protocol_checkpoint: Literal["89c0b4fadba33b9fd9a257b43eacf476b7779d59"]
    result_batch_id: str
    result_delivery_mode: Literal["input_order", "completion_order"]
    result_payload_sha256_in_delivery_order: tuple[str, ...]
    returned_results: ReturnedResultsProjection
    returned_results_sha256: str
    role: str
    runtime: RuntimeProjection
    runtime_identity: str
    scheduling_mode: str
    schema_version: Literal["broader-replication-executor-attestation/v1"]
    started_at: str
    study_id: Literal["broader-closed-loop-replication/v1"]
    submitted_jobs: SubmittedJobsProjection
    submitted_jobs_sha256: str
    trust_domain: Literal["production"]
    validation_authority_id: str
    validation_run_id: str
    worker_result_order: WorkerResultOrderProjection
    worker_result_order_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "accepted_job_ids": list(self.accepted_job_ids),
            "actual_worker_count": self.actual_worker_count,
            "completed_at": self.completed_at,
            "configured_worker_count": self.configured_worker_count,
            "configuration_sha256": self.configuration_sha256,
            "evidence_contract_checkpoint": self.evidence_contract_checkpoint,
            "execution_completion_id": self.execution_completion_id,
            "execution_id": self.execution_id,
            "execution_purpose": self.execution_purpose,
            "execution_specification_id": self.execution_specification_id,
            "execution_start_id": self.execution_start_id,
            "execution_status": self.execution_status,
            "executor_implementation_identity": self.executor_implementation_identity,
            "executor_implementation": self.executor_implementation.as_dict(),
            "execution_instance_identity": self.execution_instance_identity,
            "executor_kind": self.executor_kind,
            "implementation": self.implementation.as_dict(),
            "job_result_mapping": [list(pair) for pair in self.job_result_mapping],
            "normalized_execution_namespace": self.normalized_execution_namespace,
            "observed_worker_ids": list(self.observed_worker_ids),
            "oracle_binding_id": self.oracle_binding_id,
            "oracle_execution_id": self.oracle_execution_id,
            "protocol_checkpoint": self.protocol_checkpoint,
            "result_batch_id": self.result_batch_id,
            "result_delivery_mode": self.result_delivery_mode,
            "result_payload_sha256_in_delivery_order": list(
                self.result_payload_sha256_in_delivery_order
            ),
            "returned_results": self.returned_results.as_dict(),
            "returned_results_sha256": self.returned_results_sha256,
            "role": self.role,
            "runtime": self.runtime.as_dict(),
            "runtime_identity": self.runtime_identity,
            "scheduling_mode": self.scheduling_mode,
            "schema_version": self.schema_version,
            "started_at": self.started_at,
            "study_id": self.study_id,
            "submitted_jobs": self.submitted_jobs.as_dict(),
            "submitted_jobs_sha256": self.submitted_jobs_sha256,
            "trust_domain": self.trust_domain,
            "validation_authority_id": self.validation_authority_id,
            "validation_run_id": self.validation_run_id,
            "worker_result_order": self.worker_result_order.as_dict(),
            "worker_result_order_sha256": self.worker_result_order_sha256,
        }


@dataclass(frozen=True, slots=True)
class _IssuedExecutorImplementation:
    capability: object
    projection: ExecutorImplementationProjection
    executor_implementation_identity: str
    validation_run_id: str
    fingerprint: str
    active: bool = True


class ExecutionSpecification:
    """Opaque immutable specification issued immediately before job submission."""

    __slots__ = ()

    def __new__(cls, construction_key: object | None = None) -> ExecutionSpecification:
        if construction_key is not _SPECIFICATION_CONSTRUCTION_KEY:
            raise TypeError("Execution specifications are issued only by the real executor path.")
        return super().__new__(cls)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("Execution specifications cannot be subclassed.")

    def __copy__(self) -> NoReturn:
        raise TypeError("Execution specifications cannot be copied.")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("Execution specifications cannot be deep-copied.")

    def __reduce__(self) -> NoReturn:
        raise TypeError("Execution specifications cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Execution specifications cannot be serialized.")


class _FixtureExecutionSpecification:
    """Opaque fixture plan; it can never occupy a production plan slot."""

    __slots__ = ()

    def __new__(cls, construction_key: object | None = None) -> _FixtureExecutionSpecification:
        del construction_key
        raise TypeError("Fixture execution specifications have no public constructor.")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("Fixture execution specifications cannot be subclassed.")

    def __copy__(self) -> NoReturn:
        raise TypeError("Fixture execution specifications cannot be copied.")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("Fixture execution specifications cannot be deep-copied.")

    def __reduce__(self) -> NoReturn:
        raise TypeError("Fixture execution specifications cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Fixture execution specifications cannot be serialized.")


class ActualExecutorAttestation:
    """Opaque evidence issued only after an actual executor succeeds completely."""

    __slots__ = ()

    def __new__(cls, construction_key: object | None = None) -> ActualExecutorAttestation:
        if construction_key is not _ATTESTATION_CONSTRUCTION_KEY:
            raise TypeError("Executor attestations are issued only by actual execution.")
        return super().__new__(cls)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("Executor attestations cannot be subclassed.")

    def __copy__(self) -> NoReturn:
        raise TypeError("Executor attestations cannot be copied.")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("Executor attestations cannot be deep-copied.")

    def __reduce__(self) -> NoReturn:
        raise TypeError("Executor attestations cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Executor attestations cannot be serialized.")


@dataclass(frozen=True, slots=True)
class _ExecutionEnvironment:
    """Historical Task-C environment; its hashes are never P2 registry authority."""

    implementation_commit: str
    implementation_tree_sha256: str
    implementation_diff_sha256: str
    runtime_identity: str
    dependency_lock_sha256: str
    executor_implementation_identity: str
    runtime_payload: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _AuthorityContext:
    trust_domain: ExecutorTrustDomain
    authority_kind: str
    validation_run_id: str
    evidence_bundle_identity: str
    evidence_binding_identity: str


@dataclass(frozen=True, slots=True)
class _SpecificationObservation:
    """Historical Task-C execution metadata, outside the P2 plan registry."""

    specification_identity: str
    validation_run_id: str
    study_id: str
    evaluation_id: str
    execution_id: str
    protocol_checkpoint: str
    implementation_commit: str
    implementation_tree_sha256: str
    implementation_diff_sha256: str
    runtime_identity: str
    dependency_lock_sha256: str
    executor_implementation_identity: str
    executor_instance_identity: str
    executor_kind: ExecutorKind
    configured_worker_count: int
    scheduling_mode: str
    result_delivery_mode: ResultOrder
    submitted_job_count: int
    submitted_job_identities: tuple[str, ...]
    submission_order_sha256: str
    normalized_execution_namespace: str
    execution_purpose: ExecutionPurpose
    deterministic_configuration_sha256: str
    callable_identity: str
    timeout_seconds: float | None
    trust_domain: ExecutorTrustDomain
    authority_kind: str
    evidence_bundle_identity: str
    evidence_binding_identity: str
    issued_at: str


@dataclass(slots=True)
class _IssuedSpecification:
    specification: ExecutionSpecification
    observation: _SpecificationObservation
    fingerprint: str
    environment: _ExecutionEnvironment
    authority_context: _AuthorityContext
    authority: object | None
    active: bool = True
    submission_claimed: bool = False


@dataclass(frozen=True, slots=True)
class _ExecutorObservation:
    specification_identity: str
    execution_id: str
    validation_run_id: str
    study_id: str
    evaluation_id: str
    protocol_checkpoint: str
    trust_domain: ExecutorTrustDomain
    authority_kind: str
    evidence_bundle_identity: str
    evidence_binding_identity: str
    submitted_job_identities: tuple[str, ...]
    submitted_job_count: int
    accepted_job_identities: tuple[str, ...]
    returned_result_identities: tuple[str, ...]
    returned_result_count: int
    job_to_result_mapping: tuple[tuple[str, str], ...]
    result_payload_sha256: tuple[str, ...]
    result_batch_identity: str
    configured_worker_count: int
    actual_worker_count: int
    executor_kind: ExecutorKind
    scheduling_mode: str
    result_delivery_mode: ResultOrder
    observed_worker_identities: tuple[str, ...]
    returned_worker_identities: tuple[str, ...]
    submission_order_sha256: str
    result_order_sha256: str
    job_result_mapping_sha256: str
    configuration_sha256: str
    implementation_commit: str
    implementation_tree_sha256: str
    implementation_diff_sha256: str
    runtime_identity: str
    dependency_lock_sha256: str
    executor_implementation_identity: str
    executor_instance_identity: str
    normalized_execution_namespace: str
    execution_purpose: ExecutionPurpose
    execution_started_at: str
    execution_start_identity: str
    execution_completed_at: str
    completion_identity: str
    execution_status: Literal["success"]


@dataclass(slots=True)
class _IssuedAttestation:
    attestation: ActualExecutorAttestation
    specification: ExecutionSpecification
    observation: _ExecutorObservation
    fingerprint: str
    authority_context: _AuthorityContext
    authority: object | None
    returned_results: tuple[object, ...]
    active: bool = True


_EXECUTION_SPECIFICATIONS: dict[ExecutionSpecification, _IssuedSpecification] = {}
_EXECUTOR_ATTESTATIONS: dict[ActualExecutorAttestation, _IssuedAttestation] = {}
_RESULT_BATCH_ATTESTATIONS: dict[int, _IssuedAttestation] = {}
_ATTESTATION_LOCK = threading.RLock()


def _executor_implementation_fingerprint(
    *,
    projection: ExecutorImplementationProjection,
    executor_implementation_identity: str,
    validation_run_id: str,
    capability_domain: ExecutorTrustDomain,
) -> str:
    return protocol_hash(
        "validation_evidence_live_executor_implementation_fingerprint/v1",
        {
            "capability_domain": capability_domain,
            "executor_implementation_identity": executor_implementation_identity,
            "projection": projection.as_dict(),
            "validation_run_id": validation_run_id,
        },
    )


def _make_executor_implementation_registry(
    *,
    capability_type: type[ExecutorImplementationIdentity]
    | type[_FixtureExecutorImplementationIdentity],
    capability_domain: ExecutorTrustDomain,
) -> tuple[
    Callable[
        [ExecutorImplementationProjection, str, object | None, Callable[[object], None] | None],
        object,
    ],
    Callable[[object, str | None], _IssuedExecutorImplementation],
    Callable[[object], None],
    Callable[[], None],
    Callable[[], int],
]:
    """Create one inaccessible exact-object registry for one capability domain."""

    records: dict[object, _IssuedExecutorImplementation] = {}
    lock = threading.RLock()
    allocate = object.__new__

    def issue(
        projection: ExecutorImplementationProjection,
        run_id: str,
        preallocated_capability: object | None = None,
        confirm_before_activation: Callable[[object], None] | None = None,
    ) -> object:
        identity = protocol_hash(
            "validation_evidence_executor_implementation/v1", projection.as_dict()
        )
        with lock:
            if any(record.validation_run_id == run_id for record in records.values()):
                raise P2Stage1Error(
                    "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                    "A validation run can issue its executor implementation exactly once.",
                    layer="live_executor_implementation_issuance",
                )
            if preallocated_capability is None:
                capability = allocate(capability_type)
            elif (
                capability_domain != "production"
                or type(preallocated_capability) is not capability_type
                or not callable(confirm_before_activation)
            ):
                raise P2Stage1Error(
                    "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                    "Executor registration requires one exact centrally allocated capability.",
                    layer="live_executor_implementation_issuance",
                )
            else:
                capability = preallocated_capability
            record = _IssuedExecutorImplementation(
                capability=capability,
                projection=projection,
                executor_implementation_identity=identity,
                validation_run_id=run_id,
                fingerprint=_executor_implementation_fingerprint(
                    projection=projection,
                    executor_implementation_identity=identity,
                    validation_run_id=run_id,
                    capability_domain=capability_domain,
                ),
            )
            inactive_record = dataclass_replace(record, active=False)
            records[capability] = inactive_record
        try:
            if confirm_before_activation is not None:
                confirm_before_activation(capability)
            with lock:
                if records.get(capability) is not inactive_record:
                    raise P2Stage1Error(
                        "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                        "Executor activation lost its exact centrally confirmed allocation.",
                        layer="live_executor_implementation_issuance",
                    )
                records[capability] = record
                return capability
        except BaseException:
            with lock:
                if records.get(capability) is inactive_record:
                    del records[capability]
            raise

    def require(capability: object, run_id: str | None = None) -> _IssuedExecutorImplementation:
        with lock:
            record = records.get(capability)
            if (
                type(capability) is not capability_type
                or record is None
                or record.capability is not capability
                or not record.active
            ):
                raise P2Stage1Error(
                    "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                    "An exact current executor implementation capability is required.",
                    layer="live_executor_implementation_issuance",
                )
            if record.fingerprint != _executor_implementation_fingerprint(
                projection=record.projection,
                executor_implementation_identity=record.executor_implementation_identity,
                validation_run_id=record.validation_run_id,
                capability_domain=capability_domain,
            ):
                raise P2Stage1Error(
                    "EXECUTOR_IMPLEMENTATION_IDENTITY_MISMATCH",
                    "Executor implementation capability differs from its sealed projection.",
                    layer="executor_implementation_identity/specification_reference",
                )
            if run_id is not None and record.validation_run_id != run_id:
                raise P2Stage1Error(
                    "EXECUTOR_IMPLEMENTATION_IDENTITY_MISMATCH",
                    "Executor implementation capability belongs to another validation run.",
                    layer="executor_implementation_identity/specification_reference",
                )
            recomputed = protocol_hash(
                "validation_evidence_executor_implementation/v1", record.projection.as_dict()
            )
            if recomputed != record.executor_implementation_identity:
                raise P2Stage1Error(
                    "EXECUTOR_IMPLEMENTATION_IDENTITY_MISMATCH",
                    "Executor implementation identity does not recompute.",
                    layer="executor_implementation_identity/specification_reference",
                )
            return record

    def invalidate(capability: object) -> None:
        with lock:
            record = records.get(capability)
            if type(capability) is not capability_type:
                raise P2Stage1Error(
                    "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                    "Cannot invalidate a non-executor implementation capability.",
                    layer="live_executor_implementation_issuance",
                )
            if record is None:
                # A central owner may be aborting after allocation but before
                # component registration.  No component record is already stale.
                return
            if record.capability is not capability:
                raise P2Stage1Error(
                    "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                    "Cannot invalidate a reconstructed executor implementation capability.",
                    layer="live_executor_implementation_issuance",
                )
            # Removal is the tombstone.  In particular, invalidating an
            # inactive allocation must break the issuer's later exact-record
            # activation CAS; leaving the same inactive object would permit a
            # concurrent cleanup to certify stale and then revive it.
            del records[capability]

    def reset() -> None:
        with lock:
            records.clear()

    def current_count() -> int:
        with lock:
            return sum(record.active for record in records.values())

    return issue, require, invalidate, reset, current_count


def _make_production_executor_implementation_registry(
    make_registry: Callable[..., tuple[Callable[..., object], ...]] = (
        _make_executor_implementation_registry
    ),
) -> tuple[
    Callable[
        [ExecutorImplementationProjection, str, object | None, Callable[[object], None] | None],
        object,
    ],
    Callable[[object, str | None], _IssuedExecutorImplementation],
    Callable[[object], None],
    Callable[[], int],
]:
    issue, require, invalidate, _inaccessible_reset, current_count = make_registry(
        capability_type=ExecutorImplementationIdentity,
        capability_domain="production",
    )
    del _inaccessible_reset
    return (
        cast(
            Callable[
                [
                    ExecutorImplementationProjection,
                    str,
                    object | None,
                    Callable[[object], None] | None,
                ],
                object,
            ],
            _opaque_runtime_callable(issue),
        ),
        cast(
            Callable[[object, str | None], _IssuedExecutorImplementation],
            _opaque_runtime_callable(require),
        ),
        cast(Callable[[object], None], _opaque_runtime_callable(invalidate)),
        cast(Callable[[], int], _opaque_runtime_callable(current_count)),
    )


(
    _issue_production_executor_implementation_record,
    _require_production_executor_implementation_record,
    _invalidate_production_executor_implementation_record,
    _production_executor_implementation_record_count,
) = _make_production_executor_implementation_registry()
(
    _issue_fixture_executor_implementation_record,
    _require_fixture_executor_implementation_record,
    _invalidate_fixture_executor_implementation_record,
    _reset_fixture_executor_implementation_records,
    _fixture_executor_implementation_record_count,
) = _make_executor_implementation_registry(
    capability_type=_FixtureExecutorImplementationIdentity,
    capability_domain="fixture",
)
_production_executor_implementation_current_count = _production_executor_implementation_record_count
del _production_executor_implementation_record_count
del _fixture_executor_implementation_record_count
del _make_production_executor_implementation_registry
del _make_executor_implementation_registry


def _install_executor_registry_accessors() -> tuple[
    Callable[..., _IssuedExecutorImplementation],
    Callable[..., _IssuedExecutorImplementation],
    Callable[[ExecutorImplementationIdentity], None],
    Callable[[_FixtureExecutorImplementationIdentity], None],
    Callable[[], None],
    Callable[[ExecutorImplementationIdentity], ExecutorImplementationProjection],
    Callable[[ExecutorImplementationIdentity], str],
    Callable[[object], bool],
    Callable[[_FixtureExecutorImplementationIdentity], ExecutorImplementationProjection],
    Callable[[_FixtureExecutorImplementationIdentity], str],
]:
    """Close all access and cleanup paths over the disjoint registry operations."""

    require_production_record = _require_production_executor_implementation_record
    require_fixture_record = _require_fixture_executor_implementation_record
    invalidate_production_record = _invalidate_production_executor_implementation_record
    invalidate_fixture_record = _invalidate_fixture_executor_implementation_record
    reset_fixture_records = _reset_fixture_executor_implementation_records
    production_run_id = _production_validation_run_id
    fixture_run_id = _fixture_validation_run_id

    def require_production(
        capability: ExecutorImplementationIdentity,
        *,
        validation_run: ValidationRun,
    ) -> _IssuedExecutorImplementation:
        return require_production_record(capability, production_run_id(validation_run))

    def require_fixture(
        capability: _FixtureExecutorImplementationIdentity,
        *,
        validation_run: _FixtureValidationRun,
    ) -> _IssuedExecutorImplementation:
        return require_fixture_record(capability, fixture_run_id(validation_run))

    def invalidate_production(capability: ExecutorImplementationIdentity) -> None:
        invalidate_production_record(capability)

    def invalidate_fixture(capability: _FixtureExecutorImplementationIdentity) -> None:
        invalidate_fixture_record(capability)

    def reset_fixture() -> None:
        reset_fixture_records()

    def production_projection(
        capability: ExecutorImplementationIdentity,
    ) -> ExecutorImplementationProjection:
        return require_production_record(capability, None).projection

    def production_identity(capability: ExecutorImplementationIdentity) -> str:
        return require_production_record(capability, None).executor_implementation_identity

    def production_is_current(capability: object) -> bool:
        try:
            require_production_record(capability, None)
        except P2Stage1Error:
            return False
        return True

    def fixture_projection(
        capability: _FixtureExecutorImplementationIdentity,
    ) -> ExecutorImplementationProjection:
        return require_fixture_record(capability, None).projection

    def fixture_identity(capability: _FixtureExecutorImplementationIdentity) -> str:
        return require_fixture_record(capability, None).executor_implementation_identity

    return (
        cast(
            Callable[..., _IssuedExecutorImplementation],
            _opaque_runtime_callable(require_production),
        ),
        require_fixture,
        cast(
            Callable[[ExecutorImplementationIdentity], None],
            _seal_production_component_callable(
                "executor_invalidator",
                invalidate_production,
            ),
        ),
        invalidate_fixture,
        reset_fixture,
        cast(
            Callable[[ExecutorImplementationIdentity], ExecutorImplementationProjection],
            _opaque_runtime_callable(production_projection),
        ),
        cast(
            Callable[[ExecutorImplementationIdentity], str],
            _opaque_runtime_callable(production_identity),
        ),
        cast(
            Callable[[object], bool],
            _seal_production_component_callable(
                "executor_is_current",
                production_is_current,
            ),
        ),
        fixture_projection,
        fixture_identity,
    )


(
    _require_production_executor_implementation,
    _require_fixture_executor_implementation,
    _invalidate_production_executor_implementation,
    _invalidate_fixture_executor_implementation,
    _reset_fixture_executor_implementations,
    executor_implementation_projection,
    executor_implementation_identity,
    _production_executor_implementation_is_current,
    _fixture_executor_implementation_projection,
    _fixture_executor_implementation_identity,
) = _install_executor_registry_accessors()
del _install_executor_registry_accessors


def validation_job_projection(
    *,
    submission_index: int,
    world_id: str,
    seed: int,
    budget_id: str,
    budget: float,
    arm: object,
) -> ValidationJobProjection:
    """Encode one exact frozen job without reflection or structural fallback."""

    from research_decision_engine.benchmarks.broader_protocol import FrozenArm

    if type(arm) is not FrozenArm:
        raise P2Stage1Error(
            "EXECUTION_SUBMITTED_JOBS_MISMATCH",
            "A validation job requires one exact FrozenArm.",
            layer="execution_specification",
        )
    if isinstance(submission_index, bool) or submission_index < 0 or submission_index >= 2**64:
        raise P2Stage1Error(
            "EXECUTION_SUBMITTED_JOBS_MISMATCH",
            "submission_index must be U64.",
            layer="execution_specification",
        )
    if isinstance(seed, bool) or not -(2**63) <= seed <= 2**63 - 1:
        raise P2Stage1Error(
            "EXECUTION_SUBMITTED_JOBS_MISMATCH",
            "seed must be I64.",
            layer="execution_specification",
        )
    projection = ValidationJobProjection(
        arm=ValidationJobArmProjection(
            arm_id=arm.arm_id,
            arm_order=arm.arm_order,
            belief_model_id=arm.belief_model_id,
            policy_id=arm.policy_id,
        ),
        budget=f64(budget),
        budget_id=budget_id,
        seed=seed,
        submission_index=submission_index,
        world_id=world_id,
    )
    _validate_validation_job_projection(projection)
    return projection


def _validate_identifier(value: str, *, label: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise P2Stage1Error(
            "EXECUTION_SUBMITTED_JOBS_MISMATCH",
            f"{label} must be a nonempty canonical identifier.",
            layer="execution_specification",
        )


def _validate_validation_job_projection(projection: ValidationJobProjection) -> None:
    if type(projection) is not ValidationJobProjection:
        raise P2Stage1Error(
            "EXECUTION_SUBMITTED_JOBS_MISMATCH",
            "A submitted job requires the exact closed ValidationJobProjection type.",
            layer="execution_specification",
        )
    if projection.schema_version != "broader-replication-validation-job/v1":
        raise P2Stage1Error(
            "EXECUTION_SUBMITTED_JOBS_MISMATCH",
            "Validation job schema version differs from the frozen version.",
            layer="execution_specification",
        )
    if (
        isinstance(projection.submission_index, bool)
        or not 0 <= projection.submission_index < 2**64
        or isinstance(projection.seed, bool)
        or not -(2**63) <= projection.seed < 2**63
        or type(projection.arm) is not ValidationJobArmProjection
        or isinstance(projection.arm.arm_order, bool)
        or not 0 <= projection.arm.arm_order < 2**64
        or re.fullmatch(r"f64:[0-9a-f]{16}", projection.budget) is None
    ):
        raise P2Stage1Error(
            "EXECUTION_SUBMITTED_JOBS_MISMATCH",
            "Validation job contains a malformed integer, arm, or F64 value.",
            layer="execution_specification",
        )
    for label, value in (
        ("arm_id", projection.arm.arm_id),
        ("belief_model_id", projection.arm.belief_model_id),
        ("policy_id", projection.arm.policy_id),
        ("budget_id", projection.budget_id),
        ("world_id", projection.world_id),
    ):
        _validate_identifier(value, label=label)


def submitted_job_id(projection: ValidationJobProjection) -> str:
    _validate_validation_job_projection(projection)
    return protocol_hash("validation_evidence_execution_job/v1", projection.as_dict())


def _validation_job_content(projection: ValidationJobProjection) -> tuple[object, ...]:
    return (
        projection.world_id,
        projection.seed,
        projection.budget_id,
        projection.budget,
        projection.arm.arm_id,
        projection.arm.arm_order,
        projection.arm.belief_model_id,
        projection.arm.policy_id,
    )


def _submitted_jobs(
    jobs: Sequence[tuple[str, int, str, float, object]],
) -> tuple[SubmittedJobProjection, ...]:
    projections = tuple(
        validation_job_projection(
            submission_index=index,
            world_id=world_id,
            seed=seed,
            budget_id=budget_id,
            budget=budget,
            arm=arm,
        )
        for index, (world_id, seed, budget_id, budget, arm) in enumerate(jobs)
    )
    job_content = tuple(_validation_job_content(projection) for projection in projections)
    if len(set(job_content)) != len(job_content):
        raise P2Stage1Error(
            "EXECUTION_SUBMITTED_JOBS_MISMATCH",
            "Duplicate validation jobs are forbidden.",
            layer="execution_specification",
        )
    return tuple(
        SubmittedJobProjection(submitted_job_id(projection), projection)
        for projection in projections
    )


def _canonical_production_submitted_jobs(
    role: P2ExecutionRole,
    *,
    configurations: Mapping[P2ExecutionRole, P2ExecutionConfiguration] = (
        _P2_EXECUTION_CONFIGURATIONS
    ),
    smoke_world_ids: tuple[str, ...] = _P2_SMOKE_WORLD_IDS,
    smoke_seeds: tuple[int, ...] = _P2_SMOKE_SEEDS,
    budgets: tuple[tuple[str, float], ...] = _P2_BUDGETS,
    arms: tuple[tuple[int, str, str, str], ...] = _P2_ARMS,
    fixture_world_seeds: tuple[tuple[str, tuple[int, ...]], ...] = _P2_FIXTURE_WORLD_SEEDS,
) -> tuple[SubmittedJobProjection, ...]:
    if role in ("primary_smoke", "altered_order_replay"):
        scopes = tuple((world_id, smoke_seeds) for world_id in smoke_world_ids)
        role_arms = arms if role == "primary_smoke" else tuple(reversed(arms))
    else:
        scopes = fixture_world_seeds
        role_arms = arms
    projections: list[SubmittedJobProjection] = []
    for world_id, seeds in scopes:
        for seed in seeds:
            for budget_id, budget in budgets:
                for arm_order, arm_id, belief_model_id, policy_id in role_arms:
                    job = ValidationJobProjection(
                        arm=ValidationJobArmProjection(
                            arm_id=arm_id,
                            arm_order=arm_order,
                            belief_model_id=belief_model_id,
                            policy_id=policy_id,
                        ),
                        budget=f64(budget),
                        budget_id=budget_id,
                        seed=seed,
                        submission_index=len(projections),
                        world_id=world_id,
                    )
                    projections.append(SubmittedJobProjection(submitted_job_id(job), job))
    expected_count = configurations[role][5]
    if len(projections) != expected_count:
        raise AssertionError(f"Frozen {role} builder produced {len(projections)} jobs.")
    return tuple(projections)


def _compiled_top_level_function(
    raw_source: bytes, *, source_path: Path, function_name: str
) -> CodeType:
    module_code = compile(
        raw_source,
        str(source_path),
        "exec",
        dont_inherit=True,
        optimize=sys.flags.optimize,
    )
    matches = tuple(
        value
        for value in module_code.co_consts
        if isinstance(value, CodeType)
        and value.co_name == function_name
        and value.co_qualname == function_name
    )
    if len(matches) != 1:
        raise P2Stage1Error(
            "CALLABLE_IDENTITY_MISMATCH",
            f"Trusted source does not define exactly one {function_name} callable.",
            layer="callable_identity",
        )
    return matches[0]


def _resolved_callable_source(function: object, *, label: str) -> Path:
    try:
        source_name = inspect.getsourcefile(cast(Callable[..., object], function))
        if source_name is None:
            raise OSError("callable has no source file")
        return Path(source_name).resolve(strict=True)
    except (OSError, TypeError, ValueError) as error:
        raise P2Stage1Error(
            "CALLABLE_IDENTITY_MISMATCH",
            f"{label} does not resolve to one regular trusted source file.",
            layer="callable_identity",
        ) from error


def _verified_job_callable_projection(
    role: P2ExecutionRole,
) -> tuple[CallableProjection, str]:
    module_name, function_name, relative_source = (
        (
            "research_decision_engine.benchmarks.broader_smoke",
            "_execute_job",
            Path("research_decision_engine/benchmarks/broader_smoke.py"),
        )
        if role in ("primary_smoke", "altered_order_replay")
        else (
            "research_decision_engine.benchmarks.broader_conformance",
            "_execute_run_job",
            Path("research_decision_engine/benchmarks/broader_conformance.py"),
        )
    )
    module = importlib.import_module(module_name)
    expected_source_path = (repository_root() / relative_source).resolve(strict=True)
    try:
        module_source = Path(str(getattr(module, "__file__", ""))).resolve(strict=True)
    except (OSError, ValueError) as error:
        raise P2Stage1Error(
            "CALLABLE_IDENTITY_MISMATCH",
            f"The live {module_name} module has no trusted source file.",
            layer="callable_identity",
        ) from error
    function = getattr(module, function_name, None)
    raw_source = expected_source_path.read_bytes()
    expected_code = _compiled_top_level_function(
        raw_source, source_path=expected_source_path, function_name=function_name
    )
    if (
        module_source != expected_source_path
        or type(function) is not FunctionType
        or function.__module__ != module_name
        or function.__qualname__ != function_name
        or function.__code__ != expected_code
        or _resolved_callable_source(function, label=function_name) != expected_source_path
    ):
        raise P2Stage1Error(
            "CALLABLE_IDENTITY_MISMATCH",
            f"The live {function_name} callable is not the exact trusted source implementation.",
            layer="callable_identity",
        )
    projection, identity = callable_projection(function)
    if (
        projection.bytecode_sha256 != hashlib.sha256(expected_code.co_code).hexdigest()
        or projection.source.path != str(expected_source_path)
        or projection.source.byte_count != len(raw_source)
        or projection.source.sha256 != hashlib.sha256(raw_source).hexdigest()
    ):
        raise P2Stage1Error(
            "CALLABLE_IDENTITY_MISMATCH",
            f"The live {function_name} callable projection differs from trusted source bytes.",
            layer="callable_identity",
        )
    return projection, identity


def _validate_execution_specification_context(
    context: Layer0Context, *, trust_domain: ExecutorTrustDomain
) -> None:
    issuer = context.execution_specification_issuer
    expected_entry_point = (
        _EXECUTOR_ISSUER_ENTRY_POINT
        if trust_domain == "production"
        else _FIXTURE_EXECUTOR_ISSUER_ENTRY_POINT
    )
    issuer_identity = protocol_hash("validation_evidence_issuer/v1", issuer.as_dict())
    if (
        issuer.role != "execution_specification"
        or issuer.entry_point != expected_entry_point
        or issuer.trust_domain != trust_domain
        or issuer.evidence_contract_checkpoint != EVIDENCE_CONTRACT_CHECKPOINT
        or issuer.protocol_checkpoint != PROTOCOL_CHECKPOINT
        or issuer.implementation != context.implementation
        or issuer.runtime != context.runtime
        or issuer.runtime_identity != context.runtime_identity
        or issuer_identity != context.execution_specification_issuer_identity
    ):
        raise P2Stage1Error(
            "ISSUER_IDENTITY_MISMATCH",
            "Execution specification issuer does not match its exact Layer-0 context.",
            layer="validation_authority",
        )


def _execution_specification_id_from_projection(
    projection: ExecutionSpecificationProjection,
    *,
    trusted_executor_callable: CallableProjection,
    trusted_executor_callable_identity: str,
    configurations: Mapping[P2ExecutionRole, P2ExecutionConfiguration] = (
        _P2_EXECUTION_CONFIGURATIONS
    ),
    job_callable_resolver: Callable[
        [P2ExecutionRole], tuple[CallableProjection, str]
    ] = _verified_job_callable_projection,
    job_builder: Callable[
        [P2ExecutionRole], tuple[SubmittedJobProjection, ...]
    ] = _canonical_production_submitted_jobs,
    expected_issuer_entry_point: str = _EXECUTOR_ISSUER_ENTRY_POINT,
    expected_issuer_trust_domain: ExecutorTrustDomain = "production",
) -> str:
    if type(projection) is not ExecutionSpecificationProjection:
        raise P2Stage1Error(
            "EXECUTION_SPECIFICATION_ID_MISMATCH",
            "Execution specification requires the exact frozen projection type.",
            layer="plan_identities",
        )
    mapping = projection.as_dict()
    expected_fields = {
        "callable",
        "callable_identity",
        "configuration",
        "configuration_sha256",
        "evidence_contract_checkpoint",
        "expected_completion",
        "execution_purpose",
        "executor_kind",
        "executor_implementation",
        "executor_implementation_identity",
        "implementation",
        "normalized_execution_namespace",
        "protocol_checkpoint",
        "result_delivery_mode",
        "role",
        "runtime",
        "runtime_identity",
        "scheduling_mode",
        "schema_version",
        "specification_issuer_identity",
        "study_id",
        "submitted_jobs",
        "timeout_ms",
        "trust_domain",
        "validation_run_id",
        "worker_count",
    }
    if set(mapping) != expected_fields or "submitted_jobs_sha256" in mapping:
        raise P2Stage1Error(
            "EXECUTION_SPECIFICATION_ID_MISMATCH",
            "Execution specification field set differs from the frozen closed schema.",
            layer="plan_identities",
        )
    if projection.role not in (
        "primary_smoke",
        "altered_order_replay",
        "fixture_primary",
        "fixture_replay",
    ):
        raise P2Stage1Error(
            "EXECUTION_SPECIFICATION_RELATION_MISMATCH",
            "Execution specification has no frozen production role.",
            layer="execution_specification",
        )
    if (
        type(projection.implementation) is not ImplementationProjection
        or type(projection.runtime) is not RuntimeProjection
        or type(projection.executor_implementation) is not ExecutorImplementationProjection
        or not isinstance(projection.validation_run_id, str)
        or re.fullmatch(r"[0-9a-f]{64}", projection.validation_run_id) is None
        or not isinstance(projection.runtime_identity, str)
        or re.fullmatch(r"[0-9a-f]{64}", projection.runtime_identity) is None
        or not isinstance(projection.specification_issuer_identity, str)
        or re.fullmatch(r"[0-9a-f]{64}", projection.specification_issuer_identity) is None
    ):
        raise P2Stage1Error(
            "EXECUTION_SPECIFICATION_ID_MISMATCH",
            "Execution specification contains a malformed closed Layer-0 relation.",
            layer="plan_identities",
        )
    role = projection.role
    purpose, kind, workers, scheduling, delivery, expected_count = configurations[role]
    expected_callable, expected_callable_identity = job_callable_resolver(role)
    expected_jobs = job_builder(role)
    expected_configuration = ExecutorConfigurationProjection(
        callable_identity=expected_callable_identity,
        executor_kind=kind,
        result_delivery_mode=delivery,
        scheduling_mode=scheduling,
        timeout_ms=None,
        worker_count=workers,
    )
    expected_configuration_id = protocol_hash(
        "validation_evidence_executor_configuration/v1", expected_configuration.as_dict()
    )
    expected_executor_implementation = ExecutorImplementationProjection(
        callable=trusted_executor_callable,
        callable_identity=trusted_executor_callable_identity,
        implementation_tree_sha256=projection.implementation.implementation_tree_sha256,
    )
    expected_executor_implementation_id = protocol_hash(
        "validation_evidence_executor_implementation/v1",
        expected_executor_implementation.as_dict(),
    )
    expected_runtime_identity = protocol_hash(
        "validation_evidence_runtime/v1", projection.runtime.as_dict()
    )
    expected_issuer_identity = protocol_hash(
        "validation_evidence_issuer/v1",
        IssuerProjection(
            entry_point=expected_issuer_entry_point,
            evidence_contract_checkpoint=EVIDENCE_CONTRACT_CHECKPOINT,
            implementation=projection.implementation,
            protocol_checkpoint=PROTOCOL_CHECKPOINT,
            role="execution_specification",
            runtime=projection.runtime,
            runtime_identity=expected_runtime_identity,
            trust_domain=expected_issuer_trust_domain,
        ).as_dict(),
    )
    if (
        projection.schema_version != "broader-replication-execution-specification/v1"
        or projection.evidence_contract_checkpoint != EVIDENCE_CONTRACT_CHECKPOINT
        or projection.protocol_checkpoint != PROTOCOL_CHECKPOINT
        or projection.study_id != STUDY_ID
        or projection.trust_domain != "production"
        or projection.execution_purpose != purpose
        or projection.executor_kind != kind
        or projection.worker_count != workers
        or projection.scheduling_mode != scheduling
        or projection.result_delivery_mode != delivery
        or projection.timeout_ms is not None
        or projection.normalized_execution_namespace != f"{STUDY_ID}/production/{purpose}"
        or type(projection.expected_completion) is not ExecutionExpectedCompletionProjection
        or projection.expected_completion != ExecutionExpectedCompletionProjection(expected_count)
        or type(projection.configuration) is not ExecutorConfigurationProjection
        or projection.configuration != expected_configuration
        or projection.configuration_sha256 != expected_configuration_id
        or projection.runtime_identity != expected_runtime_identity
        or projection.specification_issuer_identity != expected_issuer_identity
    ):
        raise P2Stage1Error(
            "EXECUTION_SPECIFICATION_RELATION_MISMATCH",
            f"{role} configuration differs from its exact frozen relation.",
            layer="execution_specification",
        )
    if (
        projection.callable != expected_callable
        or projection.callable_identity != expected_callable_identity
        or projection.configuration.callable_identity != projection.callable_identity
    ):
        raise P2Stage1Error(
            "CALLABLE_IDENTITY_MISMATCH",
            f"{role} does not bind its exact frozen job callable.",
            layer="callable_identity",
        )
    if projection.submitted_jobs != expected_jobs:
        raise P2Stage1Error(
            "EXECUTION_SUBMITTED_JOBS_MISMATCH",
            f"{role} submitted_jobs differ from the complete frozen ordered job set.",
            layer="execution_specification",
        )
    if (
        projection.executor_implementation != expected_executor_implementation
        or projection.executor_implementation_identity != expected_executor_implementation_id
        or projection.executor_implementation.implementation_tree_sha256
        != projection.implementation.implementation_tree_sha256
    ):
        raise P2Stage1Error(
            "EXECUTOR_IMPLEMENTATION_IDENTITY_MISMATCH",
            "Execution specification does not bind the one trusted executor implementation.",
            layer="executor_implementation_identity/specification_reference",
        )
    return protocol_hash("validation_evidence_execution_specification/v1", mapping)


def execution_specification_id_from_projection(
    projection: ExecutionSpecificationProjection,
) -> str:
    trusted_callable, trusted_identity = _require_trusted_executor_callable()
    return _execution_specification_id_from_projection(
        projection,
        trusted_executor_callable=trusted_callable,
        trusted_executor_callable_identity=trusted_identity,
    )


def _fixture_execution_specification_id_from_projection(
    projection: ExecutionSpecificationProjection,
) -> str:
    trusted_callable, trusted_identity = _require_trusted_executor_callable()
    return _execution_specification_id_from_projection(
        projection,
        trusted_executor_callable=trusted_callable,
        trusted_executor_callable_identity=trusted_identity,
        expected_issuer_entry_point=_FIXTURE_EXECUTOR_ISSUER_ENTRY_POINT,
        expected_issuer_trust_domain="fixture",
    )


def _assemble_execution_specification_projection(
    *,
    context: Layer0Context,
    run_id: str,
    implementation_record: _IssuedExecutorImplementation,
    job_callable: CallableProjection,
    job_callable_identity: str,
    submitted_jobs: tuple[SubmittedJobProjection, ...],
    role: P2ExecutionRole,
    configurations: Mapping[P2ExecutionRole, P2ExecutionConfiguration] = (
        _P2_EXECUTION_CONFIGURATIONS
    ),
) -> ExecutionSpecificationProjection:
    purpose, kind, workers, scheduling, delivery, _ = configurations[role]
    configuration = ExecutorConfigurationProjection(
        callable_identity=job_callable_identity,
        executor_kind=kind,
        result_delivery_mode=delivery,
        scheduling_mode=scheduling,
        timeout_ms=None,
        worker_count=workers,
    )
    return ExecutionSpecificationProjection(
        callable=job_callable,
        callable_identity=job_callable_identity,
        configuration=configuration,
        configuration_sha256=protocol_hash(
            "validation_evidence_executor_configuration/v1", configuration.as_dict()
        ),
        evidence_contract_checkpoint=EVIDENCE_CONTRACT_CHECKPOINT,
        expected_completion=ExecutionExpectedCompletionProjection(len(submitted_jobs)),
        execution_purpose=purpose,
        executor_kind=kind,
        executor_implementation=implementation_record.projection,
        executor_implementation_identity=(implementation_record.executor_implementation_identity),
        implementation=context.implementation,
        normalized_execution_namespace=f"{STUDY_ID}/production/{purpose}",
        protocol_checkpoint=PROTOCOL_CHECKPOINT,
        result_delivery_mode=delivery,
        role=role,
        runtime=context.runtime,
        runtime_identity=context.runtime_identity,
        scheduling_mode=scheduling,
        specification_issuer_identity=context.execution_specification_issuer_identity,
        submitted_jobs=submitted_jobs,
        timeout_ms=None,
        validation_run_id=run_id,
        worker_count=workers,
    )


def _issue_fixture_execution_specification(
    *,
    context: Layer0Context,
    validation_run: _FixtureValidationRun,
    executor_implementation: _FixtureExecutorImplementationIdentity,
    function: Callable[..., object],
    jobs: Sequence[tuple[str, int, str, float, object]],
    role: P2ExecutionRole,
) -> _FixtureExecutionSpecification:
    """Issue a controlled fixture plan into the disjoint fixture registry only."""

    if role not in _P2_EXECUTION_ROLE_ORDER:
        raise P2Stage1Error(
            "EXECUTION_SPECIFICATION_RELATION_MISMATCH",
            "Fixture execution role is not one of the four closed roles.",
            layer="execution_specification",
        )
    if type(function) is not FunctionType:
        raise P2Stage1Error(
            "CALLABLE_IDENTITY_MISMATCH",
            "Fixture execution callable must be one exact Python function.",
            layer="callable_identity",
        )
    _validate_execution_specification_context(context, trust_domain="fixture")
    run_id = _fixture_validation_run_id(validation_run)
    implementation_record = _require_fixture_executor_implementation(
        executor_implementation, validation_run=validation_run
    )
    job_callable, job_callable_identity = callable_projection(function)
    materialized_jobs = tuple(jobs)
    projection = _assemble_execution_specification_projection(
        context=context,
        run_id=run_id,
        implementation_record=implementation_record,
        job_callable=job_callable,
        job_callable_identity=job_callable_identity,
        submitted_jobs=_submitted_jobs(materialized_jobs),
        role=role,
    )
    persistent_id = _fixture_execution_specification_id_from_projection(projection)
    capability = object.__new__(_FixtureExecutionSpecification)
    _register_fixture_plan(
        _PlanDraft(
            capability=capability,
            kind="execution_specification",
            role=role,
            persistent_id=persistent_id,
            validation_run=validation_run,
            validation_run_id=run_id,
            projection=projection,
        )
    )
    return capability


def _install_execution_specification_accessors() -> tuple[
    Callable[[ExecutionSpecification], str],
    Callable[[ExecutionSpecification], ExecutionSpecificationProjection],
    Callable[[_FixtureExecutionSpecification], str],
    Callable[[_FixtureExecutionSpecification], ExecutionSpecificationProjection],
]:
    """Close public and fixture reads over disjoint exact capability types."""

    from research_decision_engine.benchmarks.broader_validation_evidence import (
        plan_persistent_id,
        plan_projection,
    )

    production_type = ExecutionSpecification
    fixture_type = _FixtureExecutionSpecification
    projection_type = ExecutionSpecificationProjection
    error_type = P2Stage1Error

    def production_id(specification: ExecutionSpecification) -> str:
        if type(specification) is not production_type:
            raise error_type(
                "EVIDENCE_TRUST_DOMAIN_MISMATCH",
                "A production specification identity requires its exact production capability.",
                layer="plan_identities",
            )
        return plan_persistent_id(specification)

    def production_projection(
        specification: ExecutionSpecification,
    ) -> ExecutionSpecificationProjection:
        if type(specification) is not production_type:
            raise error_type(
                "EVIDENCE_TRUST_DOMAIN_MISMATCH",
                "A production projection requires its exact production capability.",
                layer="plan_identities",
            )
        projection = plan_projection(specification)
        if type(projection) is not projection_type:
            raise error_type(
                "EXECUTION_SPECIFICATION_ID_MISMATCH",
                "Capability is not a production P2 execution specification.",
                layer="plan_identities",
            )
        return projection

    def fixture_id(specification: _FixtureExecutionSpecification) -> str:
        if type(specification) is not fixture_type:
            raise error_type(
                "EVIDENCE_TRUST_DOMAIN_MISMATCH",
                "A fixture execution-specification identity requires its exact fixture capability.",
                layer="plan_identities",
            )
        return plan_persistent_id(specification)

    def fixture_projection(
        specification: _FixtureExecutionSpecification,
    ) -> ExecutionSpecificationProjection:
        if type(specification) is not fixture_type:
            raise error_type(
                "EVIDENCE_TRUST_DOMAIN_MISMATCH",
                "A fixture execution-specification projection requires its exact "
                "fixture capability.",
                layer="plan_identities",
            )
        projection = plan_projection(specification)
        if type(projection) is not projection_type:
            raise error_type(
                "EXECUTION_SPECIFICATION_ID_MISMATCH",
                "Capability is not a fixture P2 execution specification.",
                layer="plan_identities",
            )
        return projection

    return production_id, production_projection, fixture_id, fixture_projection


(
    execution_specification_id,
    p2_execution_specification_projection,
    _fixture_execution_specification_id,
    _fixture_execution_specification_projection,
) = _install_execution_specification_accessors()
del _install_execution_specification_accessors


def execute_deterministic_map[T, R](
    function: Callable[[T], R],
    jobs: Sequence[T],
    *,
    worker_count: int,
    executor_kind: ExecutorKind | None = None,
    result_order: ResultOrder = "input_order",
    execution_authority: object | None = None,
    execution_purpose: ExecutionPurpose = "diagnostic",
    timeout_seconds: float | None = None,
    _full_study_execution_key: object | None = None,
    _orchestrator_execution_key: object | None = None,
) -> tuple[tuple[R, ...], ActualExecutorAttestation]:
    """Execute exact jobs and issue one historical, non-P2 Task-C attestation.

    The P2 callable identity binds this full implementation, but Stage 1 does not
    invoke it and this historical path cannot consume or mint a P2 plan.
    """

    if execution_purpose == "full_study" and _full_study_execution_key is not (
        _FULL_STUDY_EXECUTION_KEY
    ):
        _error(
            "EXECUTION_FULL_STUDY_AUTHORITY_REQUIRED",
            "Only the frozen full-study orchestrator can issue full-study execution.",
            layer="execution_specification",
        )
    expected_orchestrator_key = {
        "production_conformance": _PRODUCTION_CONFORMANCE_EXECUTION_KEY,
    }.get(execution_purpose)
    if execution_authority is not None:
        expected_orchestrator_key = {
            "diagnostic_conformance": _DIAGNOSTIC_CONFORMANCE_EXECUTION_KEY,
            "smoke_validation": _SMOKE_VALIDATION_EXECUTION_KEY,
        }.get(execution_purpose, expected_orchestrator_key)
    if (
        expected_orchestrator_key is not None
        and _orchestrator_execution_key is not expected_orchestrator_key
    ):
        _error(
            "EXECUTION_PURPOSE_AUTHORITY_REQUIRED",
            "Only the matching frozen orchestrator can issue this execution purpose.",
            layer="execution_specification",
        )
    if execution_purpose == "diagnostic" and execution_authority is not None:
        _error(
            "EXECUTION_DIAGNOSTIC_AUTHORITY_FORBIDDEN",
            "Generic diagnostic execution is restricted to local fixture authority.",
            layer="execution_specification",
        )
    resolved_kind, scheduling_mode = _validated_configuration(
        worker_count=worker_count,
        executor_kind=executor_kind,
        result_order=result_order,
        timeout_seconds=timeout_seconds,
    )
    indexed_jobs = tuple(enumerate(jobs))
    if not indexed_jobs:
        _error(
            "EXECUTION_JOB_ID_MISSING",
            "Execution requires at least one identified job.",
            layer="execution_specification",
        )
    submitted_job_identities = tuple(_value_identity(job) for _, job in indexed_jobs)
    if len(set(submitted_job_identities)) != len(submitted_job_identities):
        _error(
            "EXECUTION_DUPLICATE_JOB_ID",
            "Execution contains duplicate submitted job IDs.",
            layer="execution_specification",
        )
    environment = _current_execution_environment()
    executor_instance_identity = _next_executor_instance_identity()
    authority_context = _authority_context(
        execution_authority,
        environment=environment,
        executor_instance_identity=executor_instance_identity,
    )
    specification = _issue_execution_specification(
        function=function,
        submitted_job_identities=submitted_job_identities,
        worker_count=worker_count,
        executor_kind=resolved_kind,
        scheduling_mode=scheduling_mode,
        result_order=result_order,
        execution_purpose=execution_purpose,
        timeout_seconds=timeout_seconds,
        executor_instance_identity=executor_instance_identity,
        environment=environment,
        authority_context=authority_context,
        authority=execution_authority,
    )
    issued = _claim_execution_specification(specification)
    started_at = _timestamp()
    start_identity = protocol_hash(
        "executor_execution_start/v1",
        {
            "execution_id": issued.observation.execution_id,
            "executor_instance_identity": executor_instance_identity,
            "started_at": started_at,
        },
    )
    accepted: list[str] = []
    accepted_lock = threading.Lock()

    def invoke(indexed_job: tuple[int, T]) -> tuple[int, R, str, str]:
        index, job = indexed_job
        accepted_identity = _value_identity(job)
        if accepted_identity != submitted_job_identities[index]:
            _error("EXECUTION_JOB_MUTATED", "A submitted job changed before executor acceptance.")
        with accepted_lock:
            accepted.append(accepted_identity)
        result = function(job)
        return index, result, _value_identity(result), _worker_identity()

    try:
        if resolved_kind == "serial":
            completed = tuple(invoke(item) for item in indexed_jobs)
            actual_configured_workers = 1
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                actual_configured_workers = executor._max_workers
                if actual_configured_workers != worker_count:
                    _error(
                        "EXECUTION_CONFIGURATION_CHANGED",
                        "Executor worker configuration changed after specification issuance.",
                    )
                if result_order == "input_order":
                    completed = tuple(executor.map(invoke, indexed_jobs, timeout=timeout_seconds))
                else:
                    futures = tuple(executor.submit(invoke, item) for item in indexed_jobs)
                    completed = tuple(
                        future.result() for future in as_completed(futures, timeout=timeout_seconds)
                    )
        if _current_execution_environment() != environment:
            _error(
                "EXECUTION_IMPLEMENTATION_CHANGED",
                "Implementation or runtime changed after specification issuance.",
            )
        _validate_completed_indexes(completed, expected_count=len(indexed_jobs))
        accepted_job_identities = tuple(accepted)
        if len(accepted_job_identities) != len(submitted_job_identities) or set(
            accepted_job_identities
        ) != set(submitted_job_identities):
            _error(
                "EXECUTION_ACCEPTED_JOB_SET_MISMATCH",
                "Actual accepted jobs differ from the exact submitted set.",
            )
        result_payload_sha256 = tuple(item[2] for item in completed)
        payload_by_index = {index: payload_sha256 for index, _, payload_sha256, _ in completed}
        result_by_index = {
            index: _returned_result_identity(
                execution_id=issued.observation.execution_id,
                submitted_job_identity=submitted_job_identities[index],
                result_payload_sha256=payload_by_index[index],
            )
            for index in range(len(submitted_job_identities))
        }
        returned_result_identities = tuple(result_by_index[item[0]] for item in completed)
        if len(set(returned_result_identities)) != len(returned_result_identities):
            _error(
                "EXECUTION_DUPLICATE_RESULT_ID",
                "Executor returned duplicate execution-scoped result identities.",
            )
        mapping = tuple(
            (job_id, result_by_index[index])
            for index, job_id in enumerate(submitted_job_identities)
        )
        if len({job_id for job_id, _ in mapping}) != len(mapping) or len(
            {result_id for _, result_id in mapping}
        ) != len(mapping):
            _error("EXECUTION_MAPPING_NOT_BIJECTIVE", "Job/result mapping is not bijective.")
        returned_workers = tuple(item[3] for item in completed)
        observed_workers = tuple(dict.fromkeys(returned_workers))
        completed_at = _timestamp()
        completion_values = {
            "execution_id": issued.observation.execution_id,
            "execution_start_identity": start_identity,
            "execution_status": "success",
            "returned_result_identities": list(returned_result_identities),
            "job_to_result_mapping": [list(item) for item in mapping],
            "observed_worker_identities": list(observed_workers),
            "completed_at": completed_at,
        }
        result_batch_identity = protocol_hash(
            "executor_result_batch/v1",
            {
                "execution_id": issued.observation.execution_id,
                "returned_result_identities": list(returned_result_identities),
                "result_payload_sha256": list(result_payload_sha256),
                "job_to_result_mapping": [list(item) for item in mapping],
            },
        )
        observation = _ExecutorObservation(
            specification_identity=issued.observation.specification_identity,
            execution_id=issued.observation.execution_id,
            validation_run_id=issued.observation.validation_run_id,
            study_id=issued.observation.study_id,
            evaluation_id=issued.observation.evaluation_id,
            protocol_checkpoint=issued.observation.protocol_checkpoint,
            trust_domain=issued.observation.trust_domain,
            authority_kind=issued.observation.authority_kind,
            evidence_bundle_identity=issued.observation.evidence_bundle_identity,
            evidence_binding_identity=issued.observation.evidence_binding_identity,
            submitted_job_identities=submitted_job_identities,
            submitted_job_count=len(submitted_job_identities),
            accepted_job_identities=accepted_job_identities,
            returned_result_identities=returned_result_identities,
            returned_result_count=len(returned_result_identities),
            job_to_result_mapping=mapping,
            result_payload_sha256=result_payload_sha256,
            result_batch_identity=result_batch_identity,
            configured_worker_count=actual_configured_workers,
            actual_worker_count=len(observed_workers),
            executor_kind=resolved_kind,
            scheduling_mode=scheduling_mode,
            result_delivery_mode=result_order,
            observed_worker_identities=observed_workers,
            returned_worker_identities=returned_workers,
            submission_order_sha256=_identity_digest(submitted_job_identities),
            result_order_sha256=_identity_digest(returned_result_identities),
            job_result_mapping_sha256=_identity_digest(mapping),
            configuration_sha256=issued.observation.deterministic_configuration_sha256,
            implementation_commit=environment.implementation_commit,
            implementation_tree_sha256=environment.implementation_tree_sha256,
            implementation_diff_sha256=environment.implementation_diff_sha256,
            runtime_identity=environment.runtime_identity,
            dependency_lock_sha256=environment.dependency_lock_sha256,
            executor_implementation_identity=environment.executor_implementation_identity,
            executor_instance_identity=executor_instance_identity,
            normalized_execution_namespace=(issued.observation.normalized_execution_namespace),
            execution_purpose=issued.observation.execution_purpose,
            execution_started_at=started_at,
            execution_start_identity=start_identity,
            execution_completed_at=completed_at,
            completion_identity=protocol_hash(
                "executor_execution_completion/v1", completion_values
            ),
            execution_status="success",
        )
        results = tuple(item[1] for item in completed)
        attestation = ActualExecutorAttestation(_ATTESTATION_CONSTRUCTION_KEY)
        record = _IssuedAttestation(
            attestation=attestation,
            specification=specification,
            observation=observation,
            fingerprint=_observation_fingerprint(observation),
            authority_context=authority_context,
            authority=execution_authority,
            returned_results=results,
        )
        with _ATTESTATION_LOCK:
            _EXECUTOR_ATTESTATIONS[attestation] = record
            _RESULT_BATCH_ATTESTATIONS[id(results)] = record
        validate_executor_attestation(
            attestation,
            results=results,
            execution_authority=execution_authority,
            expected_purpose=execution_purpose,
        )
        return results, attestation
    except BaseException:
        with _ATTESTATION_LOCK:
            issued.active = False
        raise


def validate_executor_attestation(
    attestation: ActualExecutorAttestation,
    *,
    results: Sequence[object],
    execution_authority: object | None = None,
    expected_purpose: ExecutionPurpose | None = None,
    expected_study_id: str = PROTOCOL_VERSION,
    expected_validation_run_id: str | None = None,
    expected_evidence_bundle_identity: str | None = None,
    require_trust_domain: ExecutorTrustDomain | None = None,
) -> ActualExecutorAttestation:
    """Require exact issued authority paired with its real returned sequence."""

    record = _require_attestation(attestation, require_current=True)
    observation = record.observation
    specification_record = _require_specification(
        record.specification,
        require_current=True,
    )
    specification = specification_record.observation
    if execution_authority is not record.authority:
        _error(
            "EXECUTION_AUTHORITY_MISMATCH",
            "Executor attestation belongs to another execution authority.",
        )
    _validate_authority_record(record)
    _validate_specification_relations(specification_record)
    _validate_attestation_specification_relations(record, specification_record)
    if observation.study_id != expected_study_id:
        _error("EXECUTION_STUDY_MISMATCH", "Executor attestation belongs to another study.")
    if (
        expected_validation_run_id is not None
        and observation.validation_run_id != expected_validation_run_id
    ):
        _error(
            "EXECUTION_VALIDATION_RUN_MISMATCH",
            "Executor attestation belongs to another validation run.",
        )
    if (
        expected_evidence_bundle_identity is not None
        and observation.evidence_bundle_identity != expected_evidence_bundle_identity
    ):
        _error(
            "EXECUTION_EVIDENCE_BUNDLE_MISMATCH",
            "Executor attestation belongs to another evidence bundle.",
        )
    if require_trust_domain is not None and observation.trust_domain != require_trust_domain:
        _error(
            "EXECUTION_TRUST_DOMAIN_MISMATCH",
            "Fixture executor evidence cannot satisfy a production consumer.",
        )
    if expected_purpose is not None:
        expected_namespace = _normalized_namespace(expected_purpose, observation.trust_domain)
        if (
            observation.execution_purpose != expected_purpose
            or observation.normalized_execution_namespace != expected_namespace
        ):
            _error(
                "EXECUTION_NAMESPACE_MISMATCH",
                "Executor attestation belongs to another execution namespace.",
            )
    actual_payload_sha256 = tuple(_value_identity(item) for item in results)
    if len(actual_payload_sha256) != observation.returned_result_count:
        _error("EXECUTION_RESULT_COUNT_MISMATCH", "Consumed result count differs from execution.")
    if len(set(actual_payload_sha256)) != len(actual_payload_sha256) and Counter(
        actual_payload_sha256
    ) != Counter(observation.result_payload_sha256):
        _error("EXECUTION_DUPLICATE_RESULT_ID", "Consumed results contain a duplicate identity.")
    if Counter(actual_payload_sha256) != Counter(observation.result_payload_sha256):
        _error("EXECUTION_RESULT_SET_MISMATCH", "Consumed result set differs from execution.")
    if actual_payload_sha256 != observation.result_payload_sha256:
        _error(
            "EXECUTION_RESULT_ORDER_MISMATCH",
            "Consumed result order differs from actual executor delivery order.",
        )
    if results is not record.returned_results:
        _error(
            "EXECUTION_RESULT_OCCURRENCE_MISMATCH",
            "Consumed results are not the exact tuple returned by this execution.",
        )
    payload_by_result_id = dict(
        zip(
            observation.returned_result_identities,
            observation.result_payload_sha256,
            strict=True,
        )
    )
    relations_shape_valid = (
        observation.submitted_job_count == len(observation.submitted_job_identities)
        and observation.returned_result_count == len(observation.returned_result_identities)
        and observation.returned_result_count == len(observation.result_payload_sha256)
        and observation.returned_result_count == observation.submitted_job_count
        and len(observation.job_to_result_mapping) == observation.submitted_job_count
        and len(set(observation.submitted_job_identities)) == observation.submitted_job_count
        and len(set(observation.returned_result_identities)) == observation.returned_result_count
        and len({item[0] for item in observation.job_to_result_mapping})
        == observation.submitted_job_count
        and len({item[1] for item in observation.job_to_result_mapping})
        == observation.returned_result_count
        and tuple(item[0] for item in observation.job_to_result_mapping)
        == observation.submitted_job_identities
        and set(item[1] for item in observation.job_to_result_mapping)
        == set(observation.returned_result_identities)
    )
    mapping_is_execution_scoped = relations_shape_valid and all(
        result_id
        == _returned_result_identity(
            execution_id=observation.execution_id,
            submitted_job_identity=job_id,
            result_payload_sha256=payload_by_result_id[result_id],
        )
        for job_id, result_id in observation.job_to_result_mapping
    )
    expected_batch_identity = protocol_hash(
        "executor_result_batch/v1",
        {
            "execution_id": observation.execution_id,
            "returned_result_identities": list(observation.returned_result_identities),
            "result_payload_sha256": list(observation.result_payload_sha256),
            "job_to_result_mapping": [list(item) for item in observation.job_to_result_mapping],
        },
    )
    if (
        not relations_shape_valid
        or observation.result_order_sha256
        != _identity_digest(observation.returned_result_identities)
        or observation.job_result_mapping_sha256
        != _identity_digest(observation.job_to_result_mapping)
        or not mapping_is_execution_scoped
        or observation.result_batch_identity != expected_batch_identity
        or specification.execution_id != observation.execution_id
        or observation.execution_status != "success"
    ):
        _error(
            "EXECUTION_ATTESTATION_RELATION_MISMATCH",
            "Executor attestation job/result relations do not reconcile.",
        )
    return attestation


def executor_execution_specification(
    attestation: ActualExecutorAttestation,
) -> ExecutionSpecification:
    """Return the exact opaque pre-submission specification for an attestation."""

    return _require_attestation(attestation, require_current=True).specification


def _require_issued_result_batch(
    results: Sequence[object],
    *,
    expected_purposes: Sequence[ExecutionPurpose] | None = None,
    require_trust_domain: ExecutorTrustDomain | None = None,
) -> _IssuedAttestation:
    """Resolve only the exact tuple returned by one still-current executor completion."""

    with _ATTESTATION_LOCK:
        record = _RESULT_BATCH_ATTESTATIONS.get(id(results))
    if record is None or results is not record.returned_results:
        _error(
            "EXECUTION_RESULT_OCCURRENCE_MISMATCH",
            "Exact executor-returned result tuple required before scientific use.",
        )
    observation = record.observation
    if expected_purposes is not None and observation.execution_purpose not in expected_purposes:
        _error(
            "EXECUTION_PURPOSE_MISMATCH",
            "Executor result batch belongs to another execution purpose.",
        )
    validate_executor_attestation(
        record.attestation,
        results=results,
        execution_authority=record.authority,
        expected_purpose=observation.execution_purpose,
        expected_validation_run_id=observation.validation_run_id,
        expected_evidence_bundle_identity=observation.evidence_bundle_identity,
        require_trust_domain=require_trust_domain,
    )
    return record


def execution_specification_payload(
    specification: ExecutionSpecification,
) -> dict[str, object]:
    """Return a defensive detailed view of one exact issued specification."""

    observation = _require_specification(specification, require_current=True).observation
    return asdict(observation)


def executor_attestation_payload(
    attestation: ActualExecutorAttestation,
) -> dict[str, object]:
    """Return a defensive detailed view of exact observed execution."""

    observation = _require_attestation(attestation, require_current=True).observation
    return asdict(observation)


def executor_provenance_payload(
    attestation: ActualExecutorAttestation,
) -> dict[str, str]:
    """Return the one canonical manifest-compatible executor projection."""

    observation = _require_attestation(attestation, require_current=True).observation
    return {
        "executor_attestation_completion_identity": observation.completion_identity,
        "executor_evidence_binding_identity": observation.evidence_binding_identity,
        "executor_evidence_bundle_identity": observation.evidence_bundle_identity,
        "executor_execution_id": observation.execution_id,
        "executor_execution_status": observation.execution_status,
        "executor_execution_trust_domain": observation.trust_domain,
        "executor_implementation_identity": observation.executor_implementation_identity,
        "executor_instance_identity": observation.executor_instance_identity,
        "executor_job_result_mapping_sha256": observation.job_result_mapping_sha256,
        "executor_normalized_namespace": observation.normalized_execution_namespace,
        "executor_execution_purpose": observation.execution_purpose,
        "executor_result_batch_identity": observation.result_batch_identity,
        "executor_runtime_identity": observation.runtime_identity,
        "executor_specification_identity": observation.specification_identity,
        "executor_validation_run_id": observation.validation_run_id,
        "worker_configuration_sha256": observation.configuration_sha256,
        "worker_count": str(observation.configured_worker_count),
        "worker_executor_kind": observation.executor_kind,
        "worker_observed_count": str(observation.actual_worker_count),
        "worker_observed_identities_sha256": _identity_digest(
            observation.observed_worker_identities
        ),
        "worker_order": observation.result_delivery_mode,
        "worker_result_order_sha256": observation.result_order_sha256,
        "worker_result_payload_order_sha256": _identity_digest(observation.result_payload_sha256),
        "worker_returned_result_count": str(observation.returned_result_count),
        "worker_scheduling_mode": observation.scheduling_mode,
        "worker_submission_order_sha256": observation.submission_order_sha256,
        "worker_submitted_job_count": str(observation.submitted_job_count),
    }


def _invalidate_executor_attestation(attestation: ActualExecutorAttestation) -> None:
    """Revoke an issued observation for focused stale-authority tests."""

    record = _require_attestation(attestation, require_current=False)
    with _ATTESTATION_LOCK:
        record.active = False


def _deterministic_configuration_sha256(
    *,
    callable_identity: str,
    executor_kind: ExecutorKind,
    result_order: ResultOrder,
    scheduling_mode: str,
    timeout_seconds: float | None,
    worker_count: int,
) -> str:
    configuration = {
        "callable_identity": callable_identity,
        "executor_kind": executor_kind,
        "result_delivery_mode": result_order,
        "scheduling_mode": scheduling_mode,
        "timeout_seconds": timeout_seconds,
        "worker_count": worker_count,
    }
    return hashlib.sha256(canonical_json_bytes(configuration, final_lf=True)).hexdigest()


def _execution_identity_values(
    *,
    submitted_job_identities: tuple[str, ...],
    worker_count: int,
    executor_kind: ExecutorKind,
    scheduling_mode: str,
    result_order: ResultOrder,
    execution_purpose: ExecutionPurpose,
    executor_instance_identity: str,
    environment: _ExecutionEnvironment,
    authority_context: _AuthorityContext,
    configuration_sha256: str,
) -> dict[str, object]:
    return {
        "validation_run_id": authority_context.validation_run_id,
        "study_id": PROTOCOL_VERSION,
        "evaluation_id": PROTOCOL_VERSION,
        "protocol_checkpoint": PROTOCOL_CHECKPOINT,
        "implementation_commit": environment.implementation_commit,
        "implementation_tree_sha256": environment.implementation_tree_sha256,
        "implementation_diff_sha256": environment.implementation_diff_sha256,
        "runtime_identity": environment.runtime_identity,
        "dependency_lock_sha256": environment.dependency_lock_sha256,
        "executor_implementation_identity": environment.executor_implementation_identity,
        "executor_instance_identity": executor_instance_identity,
        "configured_worker_count": worker_count,
        "executor_kind": executor_kind,
        "scheduling_mode": scheduling_mode,
        "result_delivery_mode": result_order,
        "submitted_job_identities": list(submitted_job_identities),
        "normalized_execution_namespace": _normalized_namespace(
            execution_purpose,
            authority_context.trust_domain,
        ),
        "execution_purpose": execution_purpose,
        "deterministic_configuration_sha256": configuration_sha256,
        "evidence_bundle_identity": authority_context.evidence_bundle_identity,
        "evidence_binding_identity": authority_context.evidence_binding_identity,
    }


def _issue_execution_specification(
    *,
    function: Callable[..., object],
    submitted_job_identities: tuple[str, ...],
    worker_count: int,
    executor_kind: ExecutorKind,
    scheduling_mode: str,
    result_order: ResultOrder,
    execution_purpose: ExecutionPurpose,
    timeout_seconds: float | None,
    executor_instance_identity: str,
    environment: _ExecutionEnvironment,
    authority_context: _AuthorityContext,
    authority: object | None,
) -> ExecutionSpecification:
    callable_identity = _callable_identity(function)
    configuration_sha256 = _deterministic_configuration_sha256(
        callable_identity=callable_identity,
        executor_kind=executor_kind,
        result_order=result_order,
        scheduling_mode=scheduling_mode,
        timeout_seconds=timeout_seconds,
        worker_count=worker_count,
    )
    namespace = _normalized_namespace(execution_purpose, authority_context.trust_domain)
    execution_values = _execution_identity_values(
        submitted_job_identities=submitted_job_identities,
        worker_count=worker_count,
        executor_kind=executor_kind,
        scheduling_mode=scheduling_mode,
        result_order=result_order,
        execution_purpose=execution_purpose,
        executor_instance_identity=executor_instance_identity,
        environment=environment,
        authority_context=authority_context,
        configuration_sha256=configuration_sha256,
    )
    execution_id = protocol_hash("executor_execution/v1", execution_values)
    issued_at = _timestamp()
    specification_values = {**execution_values, "execution_id": execution_id}
    observation = _SpecificationObservation(
        specification_identity=protocol_hash(
            "executor_execution_specification/v1", specification_values
        ),
        validation_run_id=authority_context.validation_run_id,
        study_id=PROTOCOL_VERSION,
        evaluation_id=PROTOCOL_VERSION,
        execution_id=execution_id,
        protocol_checkpoint=PROTOCOL_CHECKPOINT,
        implementation_commit=environment.implementation_commit,
        implementation_tree_sha256=environment.implementation_tree_sha256,
        implementation_diff_sha256=environment.implementation_diff_sha256,
        runtime_identity=environment.runtime_identity,
        dependency_lock_sha256=environment.dependency_lock_sha256,
        executor_implementation_identity=environment.executor_implementation_identity,
        executor_instance_identity=executor_instance_identity,
        executor_kind=executor_kind,
        configured_worker_count=worker_count,
        scheduling_mode=scheduling_mode,
        result_delivery_mode=result_order,
        submitted_job_count=len(submitted_job_identities),
        submitted_job_identities=submitted_job_identities,
        submission_order_sha256=_identity_digest(submitted_job_identities),
        normalized_execution_namespace=namespace,
        execution_purpose=execution_purpose,
        deterministic_configuration_sha256=configuration_sha256,
        callable_identity=callable_identity,
        timeout_seconds=timeout_seconds,
        trust_domain=authority_context.trust_domain,
        authority_kind=authority_context.authority_kind,
        evidence_bundle_identity=authority_context.evidence_bundle_identity,
        evidence_binding_identity=authority_context.evidence_binding_identity,
        issued_at=issued_at,
    )
    specification = ExecutionSpecification(_SPECIFICATION_CONSTRUCTION_KEY)
    record = _IssuedSpecification(
        specification=specification,
        observation=observation,
        fingerprint=_observation_fingerprint(observation),
        environment=environment,
        authority_context=authority_context,
        authority=authority,
    )
    with _ATTESTATION_LOCK:
        _EXECUTION_SPECIFICATIONS[specification] = record
    return specification


def _claim_execution_specification(specification: ExecutionSpecification) -> _IssuedSpecification:
    record = _require_specification(specification, require_current=True)
    with _ATTESTATION_LOCK:
        if record.submission_claimed:
            _error(
                "EXECUTION_SPECIFICATION_REPLAY", "Execution specification was already submitted."
            )
        record.submission_claimed = True
    return record


def _require_specification(
    specification: ExecutionSpecification,
    *,
    require_current: bool,
) -> _IssuedSpecification:
    if type(specification) is not ExecutionSpecification:
        _error(
            "EXECUTION_SPECIFICATION_NOT_ISSUED",
            "Execution requires an exact issued specification.",
            layer="execution_specification",
        )
    with _ATTESTATION_LOCK:
        record = _EXECUTION_SPECIFICATIONS.get(specification)
    if (
        record is None
        or record.specification is not specification
        or not record.active
        or record.fingerprint != _observation_fingerprint(record.observation)
    ):
        _error(
            "EXECUTION_SPECIFICATION_STALE",
            "Execution specification is forged, changed, or stale.",
            layer="execution_specification",
        )
    if require_current and record.environment != _current_execution_environment():
        _error(
            "EXECUTION_SPECIFICATION_IMPLEMENTATION_MISMATCH",
            "Execution specification belongs to another implementation or runtime.",
            layer="execution_specification",
        )
    return record


def _require_attestation(
    attestation: ActualExecutorAttestation,
    *,
    require_current: bool,
) -> _IssuedAttestation:
    if type(attestation) is not ActualExecutorAttestation:
        _error("EXECUTION_ATTESTATION_NOT_ISSUED", "Exact issued executor attestation required.")
    with _ATTESTATION_LOCK:
        record = _EXECUTOR_ATTESTATIONS.get(attestation)
    if (
        record is None
        or record.attestation is not attestation
        or not record.active
        or record.fingerprint != _observation_fingerprint(record.observation)
        or _RESULT_BATCH_ATTESTATIONS.get(id(record.returned_results)) is not record
    ):
        _error(
            "EXECUTION_ATTESTATION_STALE",
            "Executor attestation is forged, changed, or stale.",
        )
    specification = _require_specification(record.specification, require_current=require_current)
    if (
        specification.observation.specification_identity
        != record.observation.specification_identity
    ):
        _error(
            "EXECUTION_SPECIFICATION_ATTESTATION_MISMATCH",
            "Executor attestation belongs to another specification.",
        )
    return record


def _validate_authority_record(record: _IssuedAttestation) -> None:
    expected = _authority_context(
        record.authority,
        environment=_current_execution_environment(),
        executor_instance_identity=record.observation.executor_instance_identity,
    )
    if expected != record.authority_context:
        _error(
            "EXECUTION_AUTHORITY_STALE",
            "Executor attestation authority is stale or belongs to another binding.",
        )


def _validate_specification_relations(record: _IssuedSpecification) -> None:
    """Recompute every pre-submission identity from the issued internal state."""

    observation = record.observation
    expected_configuration = _deterministic_configuration_sha256(
        callable_identity=observation.callable_identity,
        executor_kind=observation.executor_kind,
        result_order=observation.result_delivery_mode,
        scheduling_mode=observation.scheduling_mode,
        timeout_seconds=observation.timeout_seconds,
        worker_count=observation.configured_worker_count,
    )
    execution_values = _execution_identity_values(
        submitted_job_identities=observation.submitted_job_identities,
        worker_count=observation.configured_worker_count,
        executor_kind=observation.executor_kind,
        scheduling_mode=observation.scheduling_mode,
        result_order=observation.result_delivery_mode,
        execution_purpose=observation.execution_purpose,
        executor_instance_identity=observation.executor_instance_identity,
        environment=record.environment,
        authority_context=record.authority_context,
        configuration_sha256=expected_configuration,
    )
    expected_execution_id = protocol_hash("executor_execution/v1", execution_values)
    expected_specification_identity = protocol_hash(
        "executor_execution_specification/v1",
        {**execution_values, "execution_id": expected_execution_id},
    )
    environment_relations = (
        observation.implementation_commit == record.environment.implementation_commit
        and observation.implementation_tree_sha256 == record.environment.implementation_tree_sha256
        and observation.implementation_diff_sha256 == record.environment.implementation_diff_sha256
        and observation.runtime_identity == record.environment.runtime_identity
        and observation.dependency_lock_sha256 == record.environment.dependency_lock_sha256
        and observation.executor_implementation_identity
        == record.environment.executor_implementation_identity
    )
    authority_relations = (
        observation.validation_run_id == record.authority_context.validation_run_id
        and observation.trust_domain == record.authority_context.trust_domain
        and observation.authority_kind == record.authority_context.authority_kind
        and observation.evidence_bundle_identity
        == record.authority_context.evidence_bundle_identity
        and observation.evidence_binding_identity
        == record.authority_context.evidence_binding_identity
    )
    if (
        not record.active
        or not record.submission_claimed
        or not environment_relations
        or not authority_relations
        or observation.study_id != PROTOCOL_VERSION
        or observation.evaluation_id != PROTOCOL_VERSION
        or observation.protocol_checkpoint != PROTOCOL_CHECKPOINT
        or observation.submitted_job_count != len(observation.submitted_job_identities)
        or len(set(observation.submitted_job_identities)) != observation.submitted_job_count
        or observation.submission_order_sha256
        != _identity_digest(observation.submitted_job_identities)
        or observation.deterministic_configuration_sha256 != expected_configuration
        or observation.normalized_execution_namespace
        != _normalized_namespace(observation.execution_purpose, observation.trust_domain)
        or observation.execution_id != expected_execution_id
        or observation.specification_identity != expected_specification_identity
    ):
        _error(
            "EXECUTION_SPECIFICATION_RELATION_MISMATCH",
            "Execution specification fields do not reconcile with issued internal state.",
            layer="execution_specification",
        )


def _validate_attestation_specification_relations(
    record: _IssuedAttestation,
    specification_record: _IssuedSpecification,
) -> None:
    """Independently reconcile observed completion with its exact issued specification."""

    observation = record.observation
    specification = specification_record.observation
    shared_fields = (
        "specification_identity",
        "execution_id",
        "validation_run_id",
        "study_id",
        "evaluation_id",
        "protocol_checkpoint",
        "trust_domain",
        "authority_kind",
        "evidence_bundle_identity",
        "evidence_binding_identity",
        "submitted_job_identities",
        "submitted_job_count",
        "configured_worker_count",
        "executor_kind",
        "scheduling_mode",
        "result_delivery_mode",
        "submission_order_sha256",
        "implementation_commit",
        "implementation_tree_sha256",
        "implementation_diff_sha256",
        "runtime_identity",
        "dependency_lock_sha256",
        "executor_implementation_identity",
        "executor_instance_identity",
        "normalized_execution_namespace",
        "execution_purpose",
    )
    if (
        record.specification is not specification_record.specification
        or record.authority is not specification_record.authority
        or record.authority_context is not specification_record.authority_context
        or any(
            getattr(observation, field) != getattr(specification, field) for field in shared_fields
        )
        or observation.configuration_sha256 != specification.deterministic_configuration_sha256
    ):
        _error(
            "EXECUTION_SPECIFICATION_ATTESTATION_MISMATCH",
            "Executor observation differs from its exact pre-submission specification.",
        )
    accepted_matches = len(
        observation.accepted_job_identities
    ) == observation.submitted_job_count and Counter(
        observation.accepted_job_identities
    ) == Counter(observation.submitted_job_identities)
    observed_workers = tuple(dict.fromkeys(observation.returned_worker_identities))
    worker_relations = (
        len(observation.returned_worker_identities) == observation.returned_result_count
        and observation.observed_worker_identities == observed_workers
        and observation.actual_worker_count == len(observed_workers)
        and 1 <= observation.actual_worker_count <= observation.configured_worker_count
        and all(identity for identity in observation.returned_worker_identities)
        and (
            observation.executor_kind != "serial"
            or (observation.configured_worker_count == 1 and observation.actual_worker_count == 1)
        )
    )
    expected_start_identity = protocol_hash(
        "executor_execution_start/v1",
        {
            "execution_id": observation.execution_id,
            "executor_instance_identity": observation.executor_instance_identity,
            "started_at": observation.execution_started_at,
        },
    )
    expected_completion_identity = protocol_hash(
        "executor_execution_completion/v1",
        {
            "execution_id": observation.execution_id,
            "execution_start_identity": observation.execution_start_identity,
            "execution_status": observation.execution_status,
            "returned_result_identities": list(observation.returned_result_identities),
            "job_to_result_mapping": [list(item) for item in observation.job_to_result_mapping],
            "observed_worker_identities": list(observation.observed_worker_identities),
            "completed_at": observation.execution_completed_at,
        },
    )
    try:
        started_at = datetime.fromisoformat(observation.execution_started_at)
        completed_at = datetime.fromisoformat(observation.execution_completed_at)
        timestamps_valid = (
            started_at.tzinfo is not None
            and completed_at.tzinfo is not None
            and completed_at >= started_at
        )
    except ValueError:
        timestamps_valid = False
    if not accepted_matches:
        _error(
            "EXECUTION_ACCEPTED_JOB_SET_MISMATCH",
            "Actual accepted jobs differ from the exact submitted set.",
        )
    if not worker_relations:
        _error(
            "EXECUTION_WORKER_RELATION_MISMATCH",
            "Observed worker identities or counts do not reconcile with execution.",
        )
    if (
        observation.execution_status != "success"
        or observation.execution_start_identity != expected_start_identity
        or observation.completion_identity != expected_completion_identity
        or not timestamps_valid
    ):
        _error(
            "EXECUTION_COMPLETION_RELATION_MISMATCH",
            "Execution start, completion, timestamp, or status identity does not reconcile.",
        )


def _authority_context(
    authority: object | None,
    *,
    environment: _ExecutionEnvironment,
    executor_instance_identity: str,
    local_context: _AuthorityContext | None = None,
) -> _AuthorityContext:
    if authority is None:
        if local_context is not None:
            return local_context
        validation_run_id = protocol_hash(
            "local_executor_validation_run/v1",
            {
                "process_nonce": _PROCESS_EXECUTOR_NONCE,
                "executor_instance_identity": executor_instance_identity,
            },
        )
        evidence_bundle_identity = protocol_hash(
            "local_executor_evidence_bundle/v1",
            {
                "validation_run_id": validation_run_id,
                "executor_instance_identity": executor_instance_identity,
            },
        )
        return _AuthorityContext(
            trust_domain="fixture",
            authority_kind="local_fixture",
            validation_run_id=validation_run_id,
            evidence_bundle_identity=evidence_bundle_identity,
            evidence_binding_identity=protocol_hash(
                "local_executor_binding/v1",
                {
                    "validation_run_id": validation_run_id,
                    "evidence_bundle_identity": evidence_bundle_identity,
                    "implementation_commit": environment.implementation_commit,
                },
            ),
        )
    from research_decision_engine.benchmarks.broader_oracle import (
        OracleEvidenceBinding,
        OracleFixtureBinding,
        _require_issued_binding,
        _require_issued_fixture_binding,
    )

    if type(authority) is OracleEvidenceBinding:
        _require_issued_binding(authority, require_active=True, require_current=True)
        trust_domain: ExecutorTrustDomain = "production"
        authority_kind = "oracle_production"
    elif type(authority) is OracleFixtureBinding:
        _require_issued_fixture_binding(authority, require_active=True, require_current=True)
        trust_domain = "fixture"
        authority_kind = "oracle_fixture"
    else:
        _error(
            "EXECUTION_AUTHORITY_NOT_ISSUED",
            "Execution authority must be an exact active Oracle binding.",
            layer="execution_specification",
        )
    if authority.implementation_commit != environment.implementation_commit:
        _error(
            "EXECUTION_AUTHORITY_IMPLEMENTATION_MISMATCH",
            "Execution authority belongs to another implementation.",
            layer="execution_specification",
        )
    return _AuthorityContext(
        trust_domain=trust_domain,
        authority_kind=authority_kind,
        validation_run_id=authority.validation_run_identity,
        evidence_bundle_identity=authority.evidence_bundle_identity,
        evidence_binding_identity=authority.binding_identity,
    )


def _current_execution_environment() -> _ExecutionEnvironment:
    root = repository_root().resolve(strict=True)
    from research_decision_engine.benchmarks import broader_assembly as assembly

    git = assembly._resolve_git_executable()
    implementation_commit = assembly._git_text(git, root, "rev-parse", "--verify", "HEAD^{commit}")
    checkpoint_tree = assembly._git_tree(git, root, implementation_commit)
    working_tree = assembly._working_implementation_tree(git, root)
    tree_identity = assembly._implementation_tree_identity(working_tree)
    diff_identity = assembly._implementation_diff_identity(
        git,
        root,
        checkpoint_tree,
        working_tree,
        source_checkpoint=implementation_commit,
    )
    executable = Path(sys.executable).resolve(strict=True)
    build_number, build_date = platform.python_build()
    runtime = {
        "architecture": platform.machine(),
        "platform": platform.platform(),
        "python_build_date": build_date,
        "python_build_number": build_number,
        "python_cache_tag": sys.implementation.cache_tag or "none",
        "python_compiler": platform.python_compiler(),
        "python_executable": executable.as_posix(),
        "python_executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "system": platform.system(),
    }
    dependency_lock_sha256 = hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest()
    executor_source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return _ExecutionEnvironment(
        implementation_commit=implementation_commit,
        implementation_tree_sha256=tree_identity,
        implementation_diff_sha256=diff_identity,
        runtime_identity=protocol_hash("executor_runtime_identity/v1", runtime),
        dependency_lock_sha256=dependency_lock_sha256,
        executor_implementation_identity=protocol_hash(
            "executor_implementation_identity/v1",
            {
                "module": __name__,
                "source_sha256": executor_source_sha256,
                "implementation_tree_sha256": tree_identity,
            },
        ),
        runtime_payload=tuple(sorted(runtime.items())),
    )


def _validated_configuration(
    *,
    worker_count: int,
    executor_kind: ExecutorKind | None,
    result_order: ResultOrder,
    timeout_seconds: float | None,
) -> tuple[ExecutorKind, str]:
    if worker_count < 1:
        raise ValueError("Executor worker count must be positive.")
    resolved_kind: ExecutorKind = executor_kind or (
        "serial" if worker_count == 1 else "thread_pool"
    )
    if resolved_kind not in {"serial", "thread_pool"}:
        raise ValueError("Executor kind is not supported.")
    if result_order not in {"input_order", "completion_order"}:
        raise ValueError("Executor result order is not supported.")
    if resolved_kind == "serial" and worker_count != 1:
        raise ValueError("The serial executor requires exactly one worker.")
    if resolved_kind == "serial" and result_order != "input_order":
        raise ValueError("The serial executor yields only input order.")
    if timeout_seconds is not None and timeout_seconds <= 0.0:
        raise ValueError("Executor timeout must be positive when supplied.")
    scheduling_mode = (
        "serial_call_in_input_order"
        if resolved_kind == "serial"
        else "thread_pool_concurrent_submission"
    )
    return resolved_kind, scheduling_mode


def _validate_completed_indexes(
    completed: Sequence[tuple[int, object, str, str]],
    *,
    expected_count: int,
) -> None:
    indexes = tuple(item[0] for item in completed)
    if len(indexes) != expected_count or set(indexes) != set(range(expected_count)):
        _error(
            "EXECUTION_COMPLETION_SET_MISMATCH",
            "Executor completion is missing, duplicated, or contains an extra job.",
        )


def _normalized_namespace(
    purpose: ExecutionPurpose,
    trust_domain: ExecutorTrustDomain,
) -> str:
    if purpose not in {
        "diagnostic",
        "smoke_validation",
        "production_conformance",
        "diagnostic_conformance",
        "full_study",
    }:
        _error(
            "EXECUTION_PURPOSE_UNSUPPORTED",
            "Execution purpose is outside the frozen executor namespace.",
            layer="execution_specification",
        )
    return f"{PROTOCOL_VERSION}/{trust_domain}/{purpose}"


def _next_executor_instance_identity() -> str:
    global _EXECUTION_COUNTER
    with _COUNTER_LOCK:
        _EXECUTION_COUNTER += 1
        counter = _EXECUTION_COUNTER
    return protocol_hash(
        "executor_instance/v1",
        {
            "process_nonce": _PROCESS_EXECUTOR_NONCE,
            "process_id": os.getpid(),
            "counter": counter,
        },
    )


def _worker_identity() -> str:
    return (
        f"process:{os.getpid()}/thread:{threading.get_ident()}/native:{threading.get_native_id()}"
    )


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _callable_identity(function: Callable[..., object]) -> str:
    code = getattr(function, "__code__", None)
    payload: dict[str, object] = {
        "module": getattr(function, "__module__", type(function).__module__),
        "qualname": getattr(function, "__qualname__", type(function).__qualname__),
        "callable_type": f"{type(function).__module__}.{type(function).__qualname__}",
    }
    if code is not None:
        payload["code_sha256"] = hashlib.sha256(code.co_code).hexdigest()
        payload["source_file"] = inspect.getsourcefile(function) or "none"
    return protocol_hash("executor_callable_identity/v1", payload)


def _observation_fingerprint(value: object) -> str:
    if not is_dataclass(value) or isinstance(value, type):
        raise TypeError("Executor registry fingerprints require dataclass observations.")
    return hashlib.sha256(canonical_json_bytes(asdict(value), final_lf=True)).hexdigest()


def _returned_result_identity(
    *,
    execution_id: str,
    submitted_job_identity: str,
    result_payload_sha256: str,
) -> str:
    """Bind one returned occurrence to its execution, submitted job, and payload."""

    return protocol_hash(
        "executor_returned_result/v1",
        {
            "execution_id": execution_id,
            "submitted_job_identity": submitted_job_identity,
            "result_payload_sha256": result_payload_sha256,
        },
    )


def _identity_digest(order: Sequence[object]) -> str:
    """Hash one declared-order identity array using canonical JSON plus final LF."""

    return hashlib.sha256(canonical_json_bytes(list(order), final_lf=True)).hexdigest()


def _value_identity(value: object) -> str:
    return hashlib.sha256(
        canonical_json_bytes(_execution_identity(value), final_lf=True)
    ).hexdigest()


def _execution_identity(value: object) -> object:
    """Canonical structural identity for an exact submitted or returned object."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {
            "byte_length": len(value),
            "bytes_sha256": hashlib.sha256(value).hexdigest(),
        }
    if isinstance(value, Enum):
        return {
            "enum_type": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": _execution_identity(value.value),
        }
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "dataclass_type": f"{type(value).__module__}.{type(value).__qualname__}",
            "fields": [
                [field.name, _execution_identity(getattr(value, field.name))]
                for field in fields(value)
            ],
        }
    if isinstance(value, tuple):
        return {"tuple": [_execution_identity(item) for item in value]}
    if isinstance(value, list):
        return {"list": [_execution_identity(item) for item in value]}
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            _error(
                "EXECUTION_IDENTITY_UNSUPPORTED",
                "Executor mappings require string keys for canonical identity.",
            )
        return {
            "mapping": {
                key: _execution_identity(value[key])
                for key in sorted(value, key=lambda item: item.encode("utf-8"))
            }
        }
    _error(
        "EXECUTION_IDENTITY_UNSUPPORTED",
        f"Executor value type lacks canonical structural identity: {type(value).__qualname__}.",
    )


type _Stage2D2DecodeContext = tuple[str, str]

_D2_CHECKPOINT: Final = "89c0b4fadba33b9fd9a257b43eacf476b7779d59"
_D2_STUDY: Final = "broader-closed-loop-replication/v1"

_D2_I_CTX: Final = ("EXECUTION_ID_MISMATCH", "execution_instance")
_D2_E_CTX: Final = ("EXECUTION_ID_MISMATCH", "execution_identity")
_D2_RL_CTX: Final = ("EXECUTION_SPECIFICATION_RELATION_MISMATCH", "execution_identity")
_D2_SJ_CTX: Final = ("EXECUTION_SUBMITTED_JOBS_MISMATCH", "submitted_jobs")
_D2_ST_CTX: Final = ("EXECUTION_START_ID_MISMATCH", "execution_start")
_D2_W_CTX: Final = ("EXECUTION_RESULT_ORDER_MISMATCH", "worker_identity")
_D2_RR_CTX: Final = ("EXECUTION_RETURNED_RESULT_ID_MISMATCH", "returned_run")
_D2_RO_CTX: Final = ("EXECUTION_RETURNED_RESULT_ID_MISMATCH", "returned_result")
_D2_M_CTX: Final = ("EXECUTION_JOB_RESULT_MAPPING_MISMATCH", "job_result_mapping")
_D2_B_CTX: Final = ("EXECUTION_RESULT_BATCH_ID_MISMATCH", "result_batch")
_D2_C_CTX: Final = ("EXECUTION_COMPLETION_ID_MISMATCH", "execution_completion")
_D2_RA_CTX: Final = ("EXECUTION_RETURNED_RESULTS_MISMATCH", "returned_results")
_D2_WO_CTX: Final = ("EXECUTION_RESULT_ORDER_MISMATCH", "worker_result_order")
_E_AU_CTX: Final = (
    "EXECUTOR_ATTESTATION_SPECIFICATION_UNAUTHORIZED",
    "executor_attestation",
)
_E_EI_CTX: Final = (
    "EXECUTOR_IMPLEMENTATION_IDENTITY_MISMATCH",
    "executor_attestation",
)
_E_SR_CTX: Final = (
    "EXECUTION_SPECIFICATION_RELATION_MISMATCH",
    "executor_attestation",
)
_E_NS_CTX: Final = ("EXECUTION_NAMESPACE_MISMATCH", "executor_attestation")
_E_RT_CTX: Final = ("RUNTIME_IDENTITY_MISMATCH", "executor_attestation")
_E_ID_CTX: Final = ("EXECUTOR_ATTESTATION_ID_MISMATCH", "executor_attestation")


def _d2_fail(context: _Stage2D2DecodeContext, path: str, detail: str) -> NoReturn:
    code, layer = context
    raise ExecutorProvenanceError(
        f"{code} at {path}: {detail}",
        error_code=code,
        validation_layer=layer,
    )


def _d2_exact[T](
    projection: T,
    decoded: T,
    context: _Stage2D2DecodeContext,
) -> None:
    if decoded != projection:
        _d2_fail(context, context[1], "projection does not exactly reconstruct")


def _d2_type[T](
    projection: object,
    expected: type[T],
    context: _Stage2D2DecodeContext,
) -> T:
    if type(projection) is not expected:
        _d2_fail(context, context[1], "wrong projection type")
    return projection


def _stage2e_type[T](
    value: object,
    expected: type[T],
    context: _Stage2D2DecodeContext,
    path: str,
) -> T:
    if type(value) is not expected:
        _d2_fail(context, path, f"expected exact {expected.__name__}")
    return value


def _stage2e_strings(
    context: _Stage2D2DecodeContext,
    prefix: str,
    *fields: tuple[str, object],
) -> tuple[str, ...]:
    return tuple(_stage2e_type(value, str, context, f"{prefix}.{name}") for name, value in fields)


def _stage2e_string_sequence(
    value: object,
    context: _Stage2D2DecodeContext,
    path: str,
) -> tuple[str, ...]:
    values = _stage2e_type(value, tuple, context, path)
    for index in range(len(values)):
        _stage2e_type(values[index], str, context, f"{path}[{index}]")
    return cast(tuple[str, ...], values)


def _stage2e_job_result_mapping(
    value: object,
    context: _Stage2D2DecodeContext,
    path: str,
) -> list[list[str]]:
    rows = _stage2e_type(value, tuple, context, path)
    checked: list[list[str]] = []
    for index in range(len(rows)):
        row_path = f"{path}[{index}]"
        row = _stage2e_type(rows[index], tuple, context, row_path)
        if len(row) != 2:
            _d2_fail(context, row_path, "mapping row must contain exactly two values")
        checked.append(
            [
                _stage2e_type(row[0], str, context, f"{row_path}[0]"),
                _stage2e_type(row[1], str, context, f"{row_path}[1]"),
            ]
        )
    return checked


def _stage2e_submitted_job_sequence(
    value: object,
    context: _Stage2D2DecodeContext,
    path: str,
) -> None:
    jobs = _stage2e_type(value, tuple, context, path)
    for index in range(len(jobs)):
        job_path = f"{path}[{index}]"
        job = _stage2e_type(jobs[index], SubmittedJobProjection, context, job_path)
        projection = _stage2e_type(
            job.projection,
            ValidationJobProjection,
            context,
            f"{job_path}.projection",
        )
        _stage2e_type(
            projection.arm,
            ValidationJobArmProjection,
            context,
            f"{job_path}.projection.arm",
        )


def _stage2e_projection_children(
    context: _Stage2D2DecodeContext,
    path: str,
    *children: tuple[str, object, type[object]],
) -> None:
    for name, child, expected in children:
        _stage2e_projection_shape(child, expected, context, f"{path}.{name}")


def _stage2e_projection_shape[T](
    value: object,
    expected: type[T],
    context: _Stage2D2DecodeContext,
    path: str,
) -> T:
    projection = _stage2e_type(value, expected, context, path)
    if expected is CallableProjection:
        callable_projection = cast(CallableProjection, projection)
        _stage2e_projection_shape(
            callable_projection.source,
            FileProjection,
            context,
            f"{path}.source",
        )
    elif expected is RuntimeProjection:
        runtime = cast(RuntimeProjection, projection)
        _stage2e_projection_children(
            context,
            path,
            ("base_interpreter", runtime.base_interpreter, FileProjection),
            ("interpreter", runtime.interpreter, FileProjection),
            (
                "interpreter_identity",
                runtime.interpreter_identity,
                InterpreterIdentityProjection,
            ),
            ("platform_identity", runtime.platform_identity, PlatformIdentityProjection),
        )
    elif expected is ExecutorImplementationProjection:
        implementation = cast(ExecutorImplementationProjection, projection)
        _stage2e_projection_shape(
            implementation.callable,
            CallableProjection,
            context,
            f"{path}.callable",
        )
    elif expected is SubmittedJobsProjection:
        submitted = cast(SubmittedJobsProjection, projection)
        _stage2e_projection_shape(
            submitted.implementation,
            ImplementationProjection,
            context,
            f"{path}.implementation",
        )
        _stage2e_submitted_job_sequence(submitted.jobs, context, f"{path}.jobs")
        _stage2e_projection_shape(
            submitted.runtime,
            RuntimeProjection,
            context,
            f"{path}.runtime",
        )
    elif expected is ExecutionSpecificationProjection:
        specification = cast(ExecutionSpecificationProjection, projection)
        _stage2e_projection_children(
            context,
            path,
            ("callable", specification.callable, CallableProjection),
            ("configuration", specification.configuration, ExecutorConfigurationProjection),
            (
                "expected_completion",
                specification.expected_completion,
                ExecutionExpectedCompletionProjection,
            ),
            (
                "executor_implementation",
                specification.executor_implementation,
                ExecutorImplementationProjection,
            ),
            ("implementation", specification.implementation, ImplementationProjection),
            ("runtime", specification.runtime, RuntimeProjection),
        )
        _stage2e_submitted_job_sequence(
            specification.submitted_jobs,
            context,
            f"{path}.submitted_jobs",
        )
    elif expected is ReturnedRunProjection:
        try:
            validate_returned_run_projection_shape(projection, path=path)
        except ReturnedRunProjectionError as error:
            _d2_fail(context, error.path, str(error))
    elif expected is ReturnedResultsProjection:
        returned = cast(ReturnedResultsProjection, projection)
        _stage2e_projection_shape(
            returned.implementation,
            ImplementationProjection,
            context,
            f"{path}.implementation",
        )
        _stage2e_job_result_mapping(
            returned.job_result_mapping,
            context,
            f"{path}.job_result_mapping",
        )
        rows = _stage2e_type(
            returned.results_in_submission_order,
            tuple,
            context,
            f"{path}.results_in_submission_order",
        )
        for index in range(len(rows)):
            row_path = f"{path}.results_in_submission_order[{index}]"
            row = _stage2e_type(rows[index], tuple, context, row_path)
            if len(row) != 3:
                _d2_fail(context, row_path, "result row must contain exactly three values")
            _stage2e_type(row[0], str, context, f"{row_path}.returned_result_id")
            _stage2e_projection_shape(
                row[1],
                ReturnedRunProjection,
                context,
                f"{row_path}.projection",
            )
            _stage2e_type(row[2], str, context, f"{row_path}.submitted_job_id")
        _stage2e_projection_shape(
            returned.runtime,
            RuntimeProjection,
            context,
            f"{path}.runtime",
        )
    elif expected is WorkerResultOrderProjection:
        order = cast(WorkerResultOrderProjection, projection)
        _stage2e_projection_shape(
            order.implementation,
            ImplementationProjection,
            context,
            f"{path}.implementation",
        )
        _stage2e_job_result_mapping(
            order.job_result_mapping,
            context,
            f"{path}.job_result_mapping",
        )
        rows = _stage2e_type(
            order.results_in_actual_delivery_order,
            tuple,
            context,
            f"{path}.results_in_actual_delivery_order",
        )
        for index in range(len(rows)):
            row_path = f"{path}.results_in_actual_delivery_order[{index}]"
            row = _stage2e_type(rows[index], tuple, context, row_path)
            if len(row) != 4:
                _d2_fail(context, row_path, "worker row must contain exactly four values")
            _stage2e_type(row[0], int, context, f"{row_path}.delivery_index")
            _stage2e_type(row[1], str, context, f"{row_path}.returned_result_id")
            _stage2e_projection_shape(
                row[2],
                WorkerIdentityProjection,
                context,
                f"{row_path}.worker",
            )
            _stage2e_type(row[3], str, context, f"{row_path}.worker_identity")
        _stage2e_projection_shape(
            order.runtime,
            RuntimeProjection,
            context,
            f"{path}.runtime",
        )
    elif expected is ExecutorAttestationProjection:
        attestation = cast(ExecutorAttestationProjection, projection)
        for name, sequence in (
            ("accepted_job_ids", attestation.accepted_job_ids),
            ("observed_worker_ids", attestation.observed_worker_ids),
            (
                "result_payload_sha256_in_delivery_order",
                attestation.result_payload_sha256_in_delivery_order,
            ),
        ):
            _stage2e_string_sequence(sequence, context, f"{path}.{name}")
        _stage2e_job_result_mapping(
            attestation.job_result_mapping,
            context,
            f"{path}.job_result_mapping",
        )
        _stage2e_projection_children(
            context,
            path,
            (
                "executor_implementation",
                attestation.executor_implementation,
                ExecutorImplementationProjection,
            ),
            ("implementation", attestation.implementation, ImplementationProjection),
            ("returned_results", attestation.returned_results, ReturnedResultsProjection),
            ("runtime", attestation.runtime, RuntimeProjection),
            ("submitted_jobs", attestation.submitted_jobs, SubmittedJobsProjection),
            (
                "worker_result_order",
                attestation.worker_result_order,
                WorkerResultOrderProjection,
            ),
        )
    return projection


def _stage2e_plain_value(
    value: object,
    context: _Stage2D2DecodeContext,
    path: str,
) -> None:
    if value is None or type(value) is bool or type(value) is int or type(value) is str:
        return
    if type(value) is list:
        for index in range(len(value)):
            _stage2e_plain_value(value[index], context, f"{path}[{index}]")
        return
    if type(value) is dict:
        for key in value:
            _stage2e_type(key, str, context, path)
            _stage2e_plain_value(value[key], context, f"{path}.{key}")
        return
    _d2_fail(context, path, "trusted projection mapping contains a non-built-in value")


def _stage2e_projection_mapping[T](
    value: object,
    expected: type[T],
    context: _Stage2D2DecodeContext,
    path: str,
) -> dict[str, object]:
    projection = _stage2e_projection_shape(value, expected, context, path)
    if expected is FileProjection:
        mapping = FileProjection.as_dict(cast(FileProjection, projection))
    elif expected is ImplementationProjection:
        mapping = ImplementationProjection.as_dict(cast(ImplementationProjection, projection))
    elif expected is InterpreterIdentityProjection:
        mapping = InterpreterIdentityProjection.as_dict(
            cast(InterpreterIdentityProjection, projection)
        )
    elif expected is PlatformIdentityProjection:
        mapping = PlatformIdentityProjection.as_dict(cast(PlatformIdentityProjection, projection))
    elif expected is CallableProjection:
        mapping = CallableProjection.as_dict(cast(CallableProjection, projection))
    elif expected is RuntimeProjection:
        mapping = RuntimeProjection.as_dict(cast(RuntimeProjection, projection))
    elif expected is ExecutorImplementationProjection:
        mapping = ExecutorImplementationProjection.as_dict(
            cast(ExecutorImplementationProjection, projection)
        )
    elif expected is ExecutorConfigurationProjection:
        mapping = ExecutorConfigurationProjection.as_dict(
            cast(ExecutorConfigurationProjection, projection)
        )
    elif expected is ExecutionExpectedCompletionProjection:
        mapping = ExecutionExpectedCompletionProjection.as_dict(
            cast(ExecutionExpectedCompletionProjection, projection)
        )
    elif expected is SubmittedJobsProjection:
        mapping = SubmittedJobsProjection.as_dict(cast(SubmittedJobsProjection, projection))
    elif expected is ExecutionSpecificationProjection:
        mapping = ExecutionSpecificationProjection.as_dict(
            cast(ExecutionSpecificationProjection, projection)
        )
    elif expected is ReturnedRunProjection:
        try:
            mapping = projection_as_dict(cast(ReturnedRunProjection, projection))
            decode_returned_run_projection(mapping)
        except ReturnedRunProjectionError as error:
            _d2_fail(context, path, f"returned-run projection is malformed: {error}")
    elif expected is ReturnedResultsProjection:
        mapping = ReturnedResultsProjection.as_dict(cast(ReturnedResultsProjection, projection))
    elif expected is WorkerIdentityProjection:
        mapping = WorkerIdentityProjection.as_dict(cast(WorkerIdentityProjection, projection))
    elif expected is WorkerResultOrderProjection:
        mapping = WorkerResultOrderProjection.as_dict(cast(WorkerResultOrderProjection, projection))
    elif expected is ExecutorAttestationProjection:
        mapping = ExecutorAttestationProjection.as_dict(
            cast(ExecutorAttestationProjection, projection)
        )
    else:
        _d2_fail(context, path, "unsupported trusted projection type")
    _stage2e_type(mapping, dict, context, path)
    _stage2e_plain_value(mapping, context, path)
    return mapping


@dataclass(frozen=True, slots=True)
class _ExecutionEvidenceDecoder:
    value: object
    path: str
    context: _Stage2D2DecodeContext

    def fail(self, detail: str) -> NoReturn:
        _d2_fail(self.context, self.path, detail)

    def closed(self, names: tuple[str, ...]) -> _ExecutionEvidenceDecoder:
        if type(self.value) is not dict:
            self.fail("expected an exact parsed dictionary")
        parsed: dict[str, object] = self.value
        for name in names:
            if name not in parsed:
                _d2_fail(self.context, f"{self.path}.{name}", "required field is missing")
        if len(parsed) != len(names):
            self.fail("closed projection contains an extra field")
        if tuple(parsed) != names:
            self.fail("projection fields are out of frozen order")
        return self

    def field(self, name: str) -> _ExecutionEvidenceDecoder:
        values = cast(dict[str, object], self.value)
        return _ExecutionEvidenceDecoder(values[name], f"{self.path}.{name}", self.context)

    def hashes(self, names: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(self.field(name).h64() for name in names)

    def items(self) -> tuple[_ExecutionEvidenceDecoder, ...]:
        if type(self.value) is not list:
            self.fail("expected an exact parsed list")
        return tuple(
            _ExecutionEvidenceDecoder(item, f"{self.path}[{index}]", self.context)
            for index, item in enumerate(self.value)
        )

    def h64s(self, *, unique: bool = False) -> tuple[str, ...]:
        values = tuple(item.h64() for item in self.items())
        if unique and len(set(values)) != len(values):
            self.fail("ordered H64 sequence contains a duplicate")
        return values

    def mapping(self) -> JobResultMapping:
        rows: list[tuple[str, str]] = []
        for item in self.items():
            pair = item.items()
            if len(pair) != 2:
                item.fail("mapping row must contain exactly two H64 values")
            rows.append((pair[0].h64(), pair[1].h64()))
        if (
            len(set(rows)) != len(rows)
            or len({row[0] for row in rows}) != len(rows)
            or len({row[1] for row in rows}) != len(rows)
        ):
            self.fail("mapping must be a duplicate-free bijection")
        return tuple(rows)

    def worker(self) -> WorkerIdentityProjection:
        names = (
            "execution_instance_identity",
            "execution_specification_id",
            "process_id",
            "schema_version",
            "thread_id",
            "thread_name",
            "validation_authority_id",
            "validation_run_id",
        )
        record = self.closed(names)
        return WorkerIdentityProjection(
            record.field("execution_instance_identity").h64(),
            record.field("execution_specification_id").h64(),
            record.field("process_id").u64(),
            record.field("schema_version").literal("broader-replication-worker-identity/v1"),
            record.field("thread_id").u64(),
            record.field("thread_name").string(),
            record.field("validation_authority_id").h64(),
            record.field("validation_run_id").h64(),
        )

    def returned_run(self) -> ReturnedRunProjection:
        try:
            return decode_returned_run_projection(self.value)
        except ReturnedRunProjectionError as error:
            self.fail(f"returned-run projection is invalid: {error}")

    def string(self) -> str:
        if type(self.value) is not str:
            self.fail("expected a string")
        if any(0xD800 <= ord(character) <= 0xDFFF for character in self.value):
            self.fail("lone surrogate code points are forbidden")
        if unicodedata.normalize("NFC", self.value) != self.value:
            self.fail("string is not NFC")
        return self.value

    def identifier(self) -> str:
        text = self.string()
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", text) is None:
            self.fail("expected a canonical ID")
        return text

    def h64(self) -> str:
        text = self.string()
        if re.fullmatch(r"[0-9a-f]{64}", text) is None:
            self.fail("expected lowercase H64")
        return text

    def git40(self) -> str:
        text = self.string()
        if re.fullmatch(r"[0-9a-f]{40}", text) is None:
            self.fail("expected lowercase GIT40")
        return text

    def u64(self) -> int:
        if type(self.value) is not int or not 0 <= self.value <= 2**64 - 1:
            self.fail("expected an unsigned 64-bit integer")
        return self.value

    def i64(self) -> int:
        if type(self.value) is not int or not -(2**63) <= self.value <= 2**63 - 1:
            self.fail("expected a signed 64-bit integer")
        return self.value

    def literal[T: str](self, expected: T) -> T:
        if self.string() != expected:
            self.fail(f"expected literal {expected!r}")
        return expected

    def timestamp(self) -> str:
        text = self.string()
        pattern = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z"
        if re.fullmatch(pattern, text) is None:
            self.fail("expected canonical UTC RFC3339")
        try:
            datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ")
        except ValueError:
            self.fail("timestamp is not a real UTC instant")
        return text

    def f64(self) -> str:
        text = self.string()
        if re.fullmatch(r"f64:[0-9a-f]{16}", text) is None:
            self.fail("expected canonical F64")
        bits = text[4:]
        if not math.isfinite(struct.unpack(">d", bytes.fromhex(bits))[0]):
            self.fail("F64 must be finite")
        if bits == "8000000000000000":
            self.fail("negative zero is not canonical")
        return text

    def npath(self) -> str:
        text = self.string()
        windows = re.match(r"^[A-Z]:\\", text) is not None and "/" not in text
        posix = text.startswith("/") and "\\" not in text
        if not windows and not posix:
            self.fail("expected a canonical absolute path")
        separator, root_length = ("\\", 3) if windows else ("/", 1)
        if len(text) > root_length and text.endswith(separator):
            self.fail("non-root path has a trailing separator")
        parts = text[root_length:].split(separator) if len(text) > root_length else []
        if any(part in ("", ".", "..") for part in parts):
            self.fail("path contains a noncanonical component")
        return text

    def file(self) -> FileProjection:
        record = self.closed(("byte_count", "path", "sha256"))
        return FileProjection(
            record.field("byte_count").u64(),
            record.field("path").npath(),
            record.field("sha256").h64(),
        )

    def implementation(self) -> ImplementationProjection:
        names = (
            "dependency_lock_sha256",
            "implementation_commit",
            "implementation_diff_sha256",
            "implementation_tree_sha256",
            "source_bundle_sha256",
            "test_bundle_sha256",
        )
        record = self.closed(names)
        return ImplementationProjection(
            record.field(names[0]).h64(),
            record.field(names[1]).git40(),
            *(record.field(name).h64() for name in names[2:]),
        )

    def callable_projection(self) -> CallableProjection:
        names = (
            "bytecode_sha256",
            "callable_type",
            "module_name",
            "qualname",
            "schema_version",
            "source",
        )
        record = self.closed(names)
        return CallableProjection(
            record.field("bytecode_sha256").h64(),
            record.field("callable_type").string(),
            record.field("module_name").string(),
            record.field("qualname").string(),
            record.field("source").file(),
            record.field("schema_version").literal("broader-replication-validation-callable/v1"),
        )

    def executor_implementation(self) -> ExecutorImplementationProjection:
        names = (
            "callable",
            "callable_identity",
            "implementation_tree_sha256",
            "schema_version",
        )
        record = self.closed(names)
        return ExecutorImplementationProjection(
            record.field("callable").callable_projection(),
            record.field("callable_identity").h64(),
            record.field("implementation_tree_sha256").h64(),
            record.field("schema_version").literal(
                "broader-replication-executor-implementation/v1"
            ),
        )

    def submitted_jobs_projection(self) -> SubmittedJobsProjection:
        try:
            return decode_submitted_jobs_projection(self.value)
        except ExecutorProvenanceError as error:
            self.fail(f"submitted-jobs projection is invalid: {error}")

    def returned_results_projection(self) -> ReturnedResultsProjection:
        try:
            return decode_returned_results_projection(self.value)
        except ExecutorProvenanceError as error:
            self.fail(f"returned-results projection is invalid: {error}")

    def worker_result_order_projection(self) -> WorkerResultOrderProjection:
        try:
            return decode_worker_result_order_projection(self.value)
        except ExecutorProvenanceError as error:
            self.fail(f"worker-result-order projection is invalid: {error}")

    def runtime(self) -> RuntimeProjection:
        names = (
            "base_interpreter",
            "interpreter",
            "interpreter_identity",
            "interpreter_identity_sha256",
            "platform_identity",
            "platform_identity_sha256",
            "python_build_date",
            "python_build_number",
            "schema_version",
        )
        record = self.closed(names)
        identity = record.field("interpreter_identity").closed(
            (
                "cache_tag",
                "compiler",
                "executable_path",
                "executable_sha256",
                "implementation",
                "python_version",
            ),
        )
        raw_cache = identity.field("cache_tag").value
        interpreter_identity = InterpreterIdentityProjection(
            None if raw_cache is None else identity.field("cache_tag").string(),
            identity.field("compiler").string(),
            identity.field("executable_path").npath(),
            identity.field("executable_sha256").h64(),
            identity.field("implementation").string(),
            identity.field("python_version").string(),
        )
        platform_names = ("machine", "platform", "release", "system", "version")
        platform_record = record.field("platform_identity").closed(platform_names)
        platform_identity_value = PlatformIdentityProjection(
            *(platform_record.field(name).string() for name in platform_names)
        )
        runtime = RuntimeProjection(
            record.field("base_interpreter").file(),
            record.field("interpreter").file(),
            interpreter_identity,
            record.field("interpreter_identity_sha256").h64(),
            platform_identity_value,
            record.field("platform_identity_sha256").h64(),
            record.field("python_build_date").string(),
            record.field("python_build_number").string(),
            record.field("schema_version").literal("broader-replication-validation-runtime/v1"),
        )
        if (runtime.interpreter.path, runtime.interpreter.sha256) != (
            interpreter_identity.executable_path,
            interpreter_identity.executable_sha256,
        ):
            self.fail("runtime executable relation differs")
        if runtime.interpreter_identity_sha256 != protocol_hash(
            "pytest_interpreter_identity/v1", interpreter_identity.as_dict()
        ):
            self.fail("interpreter identity digest differs")
        if runtime.platform_identity_sha256 != protocol_hash(
            "pytest_platform_identity/v1", platform_identity_value.as_dict()
        ):
            self.fail("platform identity digest differs")
        return runtime

    def job(self) -> ValidationJobProjection:
        names = (
            "arm",
            "budget",
            "budget_id",
            "schema_version",
            "seed",
            "submission_index",
            "world_id",
        )
        record = self.closed(names)
        arm = record.field("arm").closed(("arm_id", "arm_order", "belief_model_id", "policy_id"))
        return ValidationJobProjection(
            ValidationJobArmProjection(
                arm.field("arm_id").identifier(),
                arm.field("arm_order").u64(),
                arm.field("belief_model_id").identifier(),
                arm.field("policy_id").identifier(),
            ),
            record.field("budget").f64(),
            record.field("budget_id").identifier(),
            record.field("seed").i64(),
            record.field("submission_index").u64(),
            record.field("world_id").identifier(),
            record.field("schema_version").literal("broader-replication-validation-job/v1"),
        )


def decode_execution_instance_projection(value: object) -> ExecutionInstanceProjection:
    names = (
        "counter",
        "issuer_identity",
        "process_id",
        "process_nonce",
        "process_started_at",
        "schema_version",
    )
    record = _ExecutionEvidenceDecoder(value, "execution_instance", _D2_I_CTX).closed(names)
    return ExecutionInstanceProjection(
        record.field("counter").u64(),
        record.field("issuer_identity").h64(),
        record.field("process_id").u64(),
        record.field("process_nonce").h64(),
        record.field("process_started_at").timestamp(),
        record.field("schema_version").literal("broader-replication-execution-instance/v1"),
    )


def decode_execution_identity_projection(value: object) -> ExecutionIdentityProjection:
    names = (
        "execution_instance",
        "execution_instance_identity",
        "execution_specification_id",
        "implementation_commit",
        "implementation_diff_sha256",
        "implementation_tree_sha256",
        "oracle_binding_id",
        "oracle_execution_id",
        "protocol_checkpoint",
        "role",
        "runtime_identity",
        "schema_version",
        "study_id",
        "validation_authority_id",
        "validation_run_id",
    )
    record = _ExecutionEvidenceDecoder(value, "execution_identity", _D2_E_CTX).closed(names)
    return ExecutionIdentityProjection(
        decode_execution_instance_projection(record.field("execution_instance").value),
        record.field("execution_instance_identity").h64(),
        record.field("execution_specification_id").h64(),
        record.field("implementation_commit").git40(),
        record.field("implementation_diff_sha256").h64(),
        record.field("implementation_tree_sha256").h64(),
        record.field("oracle_binding_id").h64(),
        record.field("oracle_execution_id").h64(),
        record.field("protocol_checkpoint").literal(_D2_CHECKPOINT),
        record.field("role").identifier(),
        record.field("runtime_identity").h64(),
        record.field("schema_version").literal("broader-replication-execution/v1"),
        record.field("study_id").identifier(),
        record.field("validation_authority_id").h64(),
        record.field("validation_run_id").h64(),
    )


def decode_submitted_jobs_projection(value: object) -> SubmittedJobsProjection:
    names = (
        "configuration_sha256",
        "execution_id",
        "execution_specification_id",
        "implementation",
        "jobs",
        "oracle_binding_id",
        "oracle_execution_id",
        "protocol_checkpoint",
        "runtime",
        "runtime_identity",
        "schema_version",
        "study_id",
        "validation_authority_id",
        "validation_run_id",
    )
    record = _ExecutionEvidenceDecoder(value, "submitted_jobs", _D2_SJ_CTX).closed(names)
    jobs: list[SubmittedJobProjection] = []
    for index, raw in enumerate(record.field("jobs").items()):
        row = raw.closed(("submitted_job_id", "projection"))
        jobs.append(
            SubmittedJobProjection(
                row.field("submitted_job_id").h64(),
                row.field("projection").job(),
            )
        )
        if (
            jobs[-1].projection.submission_index != index
            or submitted_job_id(jobs[-1].projection) != jobs[-1].submitted_job_id
            or any(item.submitted_job_id == jobs[-1].submitted_job_id for item in jobs[:-1])
        ):
            raw.fail("job index, identity, or uniqueness differs")
    return SubmittedJobsProjection(
        record.field("configuration_sha256").h64(),
        record.field("execution_id").h64(),
        record.field("execution_specification_id").h64(),
        record.field("implementation").implementation(),
        tuple(jobs),
        record.field("oracle_binding_id").h64(),
        record.field("oracle_execution_id").h64(),
        record.field("protocol_checkpoint").literal(_D2_CHECKPOINT),
        record.field("runtime").runtime(),
        record.field("runtime_identity").h64(),
        record.field("schema_version").literal("broader-replication-submitted-jobs/v1"),
        record.field("study_id").literal(_D2_STUDY),
        record.field("validation_authority_id").h64(),
        record.field("validation_run_id").h64(),
    )


def decode_execution_start_projection(value: object) -> ExecutionStartProjection:
    names = (
        "execution_id",
        "execution_instance_identity",
        "execution_specification_id",
        "schema_version",
        "started_at",
        "validation_authority_id",
        "validation_run_id",
    )
    record = _ExecutionEvidenceDecoder(value, "execution_start", _D2_ST_CTX).closed(names)
    return ExecutionStartProjection(
        record.field("execution_id").h64(),
        record.field("execution_instance_identity").h64(),
        record.field("execution_specification_id").h64(),
        record.field("schema_version").literal("broader-replication-execution-start/v1"),
        record.field("started_at").timestamp(),
        record.field("validation_authority_id").h64(),
        record.field("validation_run_id").h64(),
    )


def decode_worker_identity_projection(value: object) -> WorkerIdentityProjection:
    names = (
        "execution_instance_identity",
        "execution_specification_id",
        "process_id",
        "schema_version",
        "thread_id",
        "thread_name",
        "validation_authority_id",
        "validation_run_id",
    )
    record = _ExecutionEvidenceDecoder(value, "worker", _D2_W_CTX).closed(names)
    return WorkerIdentityProjection(
        record.field("execution_instance_identity").h64(),
        record.field("execution_specification_id").h64(),
        record.field("process_id").u64(),
        record.field("schema_version").literal("broader-replication-worker-identity/v1"),
        record.field("thread_id").u64(),
        record.field("thread_name").string(),
        record.field("validation_authority_id").h64(),
        record.field("validation_run_id").h64(),
    )


def decode_returned_result_projection(value: object) -> ReturnedResultProjection:
    names = (
        "execution_id",
        "execution_specification_id",
        "result_payload_sha256",
        "schema_version",
        "submitted_job_id",
        "validation_authority_id",
        "validation_run_id",
    )
    record = _ExecutionEvidenceDecoder(value, "returned_result", _D2_RO_CTX).closed(names)
    return ReturnedResultProjection(
        record.field("execution_id").h64(),
        record.field("execution_specification_id").h64(),
        record.field("result_payload_sha256").h64(),
        record.field("schema_version").literal("broader-replication-returned-result/v1"),
        record.field("submitted_job_id").h64(),
        record.field("validation_authority_id").h64(),
        record.field("validation_run_id").h64(),
    )


def decode_result_batch_projection(value: object) -> ResultBatchProjection:
    names = (
        "execution_id",
        "execution_specification_id",
        "job_result_mapping",
        "result_payload_sha256_in_delivery_order",
        "returned_result_ids_in_delivery_order",
        "schema_version",
        "validation_authority_id",
        "validation_run_id",
    )
    record = _ExecutionEvidenceDecoder(value, "result_batch", _D2_B_CTX).closed(names)
    execution_id_value = record.field("execution_id").h64()
    execution_specification_id_value = record.field("execution_specification_id").h64()
    mapping = record.field("job_result_mapping").mapping()
    payload_hashes = record.field("result_payload_sha256_in_delivery_order").h64s()
    returned_ids = record.field("returned_result_ids_in_delivery_order").h64s(unique=True)
    record.field("schema_version").literal("broader-replication-result-batch/v1")
    validation_authority_id = record.field("validation_authority_id").h64()
    validation_run_id = record.field("validation_run_id").h64()
    if (
        len(mapping) != len(payload_hashes)
        or len(mapping) != len(returned_ids)
        or {row[1] for row in mapping} != set(returned_ids)
    ):
        record.fail("mapping, delivery IDs, and payload hashes do not form one complete batch")
    return ResultBatchProjection(
        execution_id_value,
        execution_specification_id_value,
        mapping,
        payload_hashes,
        returned_ids,
        "broader-replication-result-batch/v1",
        validation_authority_id,
        validation_run_id,
    )


def decode_execution_completion_projection(value: object) -> ExecutionCompletionProjection:
    names = (
        "completed_at",
        "execution_id",
        "execution_specification_id",
        "execution_start_id",
        "execution_status",
        "job_result_mapping",
        "observed_worker_ids",
        "returned_result_ids_in_delivery_order",
        "schema_version",
        "validation_authority_id",
        "validation_run_id",
    )
    record = _ExecutionEvidenceDecoder(value, "execution_completion", _D2_C_CTX).closed(names)
    completed_at = record.field("completed_at").timestamp()
    execution_id_value = record.field("execution_id").h64()
    execution_specification_id_value = record.field("execution_specification_id").h64()
    execution_start_id_value = record.field("execution_start_id").h64()
    record.field("execution_status").literal("success")
    mapping = record.field("job_result_mapping").mapping()
    observed_workers = record.field("observed_worker_ids").h64s(unique=True)
    returned_ids = record.field("returned_result_ids_in_delivery_order").h64s(unique=True)
    record.field("schema_version").literal("broader-replication-execution-completion/v1")
    validation_authority_id = record.field("validation_authority_id").h64()
    validation_run_id = record.field("validation_run_id").h64()
    if (
        len(mapping) != len(returned_ids)
        or {row[1] for row in mapping} != set(returned_ids)
        or (bool(returned_ids) and not observed_workers)
    ):
        record.fail("successful completion is not complete")
    return ExecutionCompletionProjection(
        completed_at,
        execution_id_value,
        execution_specification_id_value,
        execution_start_id_value,
        "success",
        mapping,
        observed_workers,
        returned_ids,
        "broader-replication-execution-completion/v1",
        validation_authority_id,
        validation_run_id,
    )


def decode_returned_results_projection(value: object) -> ReturnedResultsProjection:
    names = (
        "execution_completion_id",
        "execution_id",
        "execution_specification_id",
        "execution_status",
        "implementation",
        "job_result_mapping",
        "oracle_binding_id",
        "oracle_execution_id",
        "protocol_checkpoint",
        "results_in_submission_order",
        "runtime",
        "runtime_identity",
        "schema_version",
        "study_id",
        "validation_authority_id",
        "validation_run_id",
    )
    record = _ExecutionEvidenceDecoder(value, "returned_results", _D2_RA_CTX).closed(names)
    execution_completion_id_value = record.field("execution_completion_id").h64()
    execution_id_value = record.field("execution_id").h64()
    execution_specification_id_value = record.field("execution_specification_id").h64()
    record.field("execution_status").literal("success")
    implementation = record.field("implementation").implementation()
    mapping = record.field("job_result_mapping").mapping()
    oracle_binding_id = record.field("oracle_binding_id").h64()
    oracle_execution_id = record.field("oracle_execution_id").h64()
    record.field("protocol_checkpoint").literal(_D2_CHECKPOINT)
    rows: list[tuple[str, ReturnedRunProjection, str]] = []
    for raw in record.field("results_in_submission_order").items():
        row = raw.closed(("returned_result_id", "projection", "submitted_job_id"))
        rows.append(
            (
                row.field("returned_result_id").h64(),
                row.field("projection").returned_run(),
                row.field("submitted_job_id").h64(),
            )
        )
    runtime = record.field("runtime").runtime()
    runtime_identity_value = record.field("runtime_identity").h64()
    record.field("schema_version").literal("broader-replication-returned-results/v1")
    record.field("study_id").literal(_D2_STUDY)
    validation_authority_id = record.field("validation_authority_id").h64()
    validation_run_id = record.field("validation_run_id").h64()
    if (
        len(rows) != len(mapping)
        or len({row[0] for row in rows}) != len(rows)
        or len({row[2] for row in rows}) != len(rows)
        or tuple((row[2], row[0]) for row in rows) != mapping
    ):
        record.field("results_in_submission_order").fail(
            "submission rows do not form the complete mapping bijection"
        )
    return ReturnedResultsProjection(
        execution_completion_id_value,
        execution_id_value,
        execution_specification_id_value,
        "success",
        implementation,
        mapping,
        oracle_binding_id,
        oracle_execution_id,
        _D2_CHECKPOINT,
        tuple(rows),
        runtime,
        runtime_identity_value,
        "broader-replication-returned-results/v1",
        _D2_STUDY,
        validation_authority_id,
        validation_run_id,
    )


def decode_worker_result_order_projection(value: object) -> WorkerResultOrderProjection:
    names = (
        "execution_completion_id",
        "execution_id",
        "execution_specification_id",
        "execution_status",
        "implementation",
        "job_result_mapping",
        "oracle_binding_id",
        "oracle_execution_id",
        "protocol_checkpoint",
        "results_in_actual_delivery_order",
        "runtime",
        "runtime_identity",
        "schema_version",
        "study_id",
        "validation_authority_id",
        "validation_run_id",
    )
    record = _ExecutionEvidenceDecoder(value, "worker_result_order", _D2_WO_CTX).closed(names)
    execution_completion_id_value = record.field("execution_completion_id").h64()
    execution_id_value = record.field("execution_id").h64()
    execution_specification_id_value = record.field("execution_specification_id").h64()
    record.field("execution_status").literal("success")
    implementation = record.field("implementation").implementation()
    mapping = record.field("job_result_mapping").mapping()
    oracle_binding_id = record.field("oracle_binding_id").h64()
    oracle_execution_id = record.field("oracle_execution_id").h64()
    record.field("protocol_checkpoint").literal(_D2_CHECKPOINT)
    rows: list[tuple[int, str, WorkerIdentityProjection, str]] = []
    for expected_index, raw in enumerate(record.field("results_in_actual_delivery_order").items()):
        row = raw.closed(("delivery_index", "returned_result_id", "worker", "worker_identity"))
        delivery_index = row.field("delivery_index").u64()
        returned_result_id_value = row.field("returned_result_id").h64()
        worker = row.field("worker").worker()
        worker_identity_value = row.field("worker_identity").h64()
        if delivery_index != expected_index or worker_identity(worker) != worker_identity_value:
            raw.fail("delivery index or worker identity differs")
        rows.append(
            (
                delivery_index,
                returned_result_id_value,
                worker,
                worker_identity_value,
            )
        )
    runtime = record.field("runtime").runtime()
    runtime_identity_value = record.field("runtime_identity").h64()
    record.field("schema_version").literal("broader-replication-worker-result-order/v1")
    record.field("study_id").literal(_D2_STUDY)
    validation_authority_id = record.field("validation_authority_id").h64()
    validation_run_id = record.field("validation_run_id").h64()
    if (
        len(rows) != len(mapping)
        or len({row[1] for row in rows}) != len(rows)
        or {row[1] for row in rows} != {pair[1] for pair in mapping}
    ):
        record.field("results_in_actual_delivery_order").fail(
            "delivery rows do not contain every mapped returned result exactly once"
        )
    return WorkerResultOrderProjection(
        execution_completion_id_value,
        execution_id_value,
        execution_specification_id_value,
        "success",
        implementation,
        mapping,
        oracle_binding_id,
        oracle_execution_id,
        _D2_CHECKPOINT,
        tuple(rows),
        runtime,
        runtime_identity_value,
        "broader-replication-worker-result-order/v1",
        _D2_STUDY,
        validation_authority_id,
        validation_run_id,
    )


def decode_executor_attestation_projection(value: object) -> ExecutorAttestationProjection:
    names = (
        "accepted_job_ids",
        "actual_worker_count",
        "completed_at",
        "configured_worker_count",
        "configuration_sha256",
        "evidence_contract_checkpoint",
        "execution_completion_id",
        "execution_id",
        "execution_purpose",
        "execution_specification_id",
        "execution_start_id",
        "execution_status",
        "executor_implementation_identity",
        "executor_implementation",
        "execution_instance_identity",
        "executor_kind",
        "implementation",
        "job_result_mapping",
        "normalized_execution_namespace",
        "observed_worker_ids",
        "oracle_binding_id",
        "oracle_execution_id",
        "protocol_checkpoint",
        "result_batch_id",
        "result_delivery_mode",
        "result_payload_sha256_in_delivery_order",
        "returned_results",
        "returned_results_sha256",
        "role",
        "runtime",
        "runtime_identity",
        "scheduling_mode",
        "schema_version",
        "started_at",
        "study_id",
        "submitted_jobs",
        "submitted_jobs_sha256",
        "trust_domain",
        "validation_authority_id",
        "validation_run_id",
        "worker_result_order",
        "worker_result_order_sha256",
    )
    record = _ExecutionEvidenceDecoder(value, "executor_attestation", _E_ID_CTX).closed(names)
    executor_kind = record.field("executor_kind").string()
    if executor_kind not in ("serial", "thread_pool"):
        record.field("executor_kind").fail("expected serial or thread_pool")
    result_delivery_mode = record.field("result_delivery_mode").string()
    if result_delivery_mode not in ("input_order", "completion_order"):
        record.field("result_delivery_mode").fail("expected input_order or completion_order")
    return ExecutorAttestationProjection(
        accepted_job_ids=record.field("accepted_job_ids").h64s(unique=True),
        actual_worker_count=record.field("actual_worker_count").u64(),
        completed_at=record.field("completed_at").timestamp(),
        configured_worker_count=record.field("configured_worker_count").u64(),
        configuration_sha256=record.field("configuration_sha256").h64(),
        evidence_contract_checkpoint=record.field("evidence_contract_checkpoint").git40(),
        execution_completion_id=record.field("execution_completion_id").h64(),
        execution_id=record.field("execution_id").h64(),
        execution_purpose=record.field("execution_purpose").identifier(),
        execution_specification_id=record.field("execution_specification_id").h64(),
        execution_start_id=record.field("execution_start_id").h64(),
        execution_status=record.field("execution_status").literal("success"),
        executor_implementation_identity=record.field("executor_implementation_identity").h64(),
        executor_implementation=record.field("executor_implementation").executor_implementation(),
        execution_instance_identity=record.field("execution_instance_identity").h64(),
        executor_kind=cast(Literal["serial", "thread_pool"], executor_kind),
        implementation=record.field("implementation").implementation(),
        job_result_mapping=record.field("job_result_mapping").mapping(),
        normalized_execution_namespace=record.field("normalized_execution_namespace").string(),
        observed_worker_ids=record.field("observed_worker_ids").h64s(unique=True),
        oracle_binding_id=record.field("oracle_binding_id").h64(),
        oracle_execution_id=record.field("oracle_execution_id").h64(),
        protocol_checkpoint=record.field("protocol_checkpoint").literal(_D2_CHECKPOINT),
        result_batch_id=record.field("result_batch_id").h64(),
        result_delivery_mode=cast(Literal["input_order", "completion_order"], result_delivery_mode),
        result_payload_sha256_in_delivery_order=record.field(
            "result_payload_sha256_in_delivery_order"
        ).h64s(),
        returned_results=record.field("returned_results").returned_results_projection(),
        returned_results_sha256=record.field("returned_results_sha256").h64(),
        role=record.field("role").identifier(),
        runtime=record.field("runtime").runtime(),
        runtime_identity=record.field("runtime_identity").h64(),
        scheduling_mode=record.field("scheduling_mode").string(),
        schema_version=record.field("schema_version").literal(
            "broader-replication-executor-attestation/v1"
        ),
        started_at=record.field("started_at").timestamp(),
        study_id=record.field("study_id").literal(_D2_STUDY),
        submitted_jobs=record.field("submitted_jobs").submitted_jobs_projection(),
        submitted_jobs_sha256=record.field("submitted_jobs_sha256").h64(),
        trust_domain=record.field("trust_domain").literal("production"),
        validation_authority_id=record.field("validation_authority_id").h64(),
        validation_run_id=record.field("validation_run_id").h64(),
        worker_result_order=record.field("worker_result_order").worker_result_order_projection(),
        worker_result_order_sha256=record.field("worker_result_order_sha256").h64(),
    )


def execution_instance_identity(projection: ExecutionInstanceProjection) -> str:
    _d2_type(projection, ExecutionInstanceProjection, _D2_I_CTX)
    mapping = projection.as_dict()
    _d2_exact(projection, decode_execution_instance_projection(mapping), _D2_I_CTX)
    return protocol_hash("validation_evidence_execution_instance/v1", mapping)


def execution_id(projection: ExecutionIdentityProjection) -> str:
    _d2_type(projection, ExecutionIdentityProjection, _D2_E_CTX)
    mapping = projection.as_dict()
    _d2_exact(projection, decode_execution_identity_projection(mapping), _D2_E_CTX)
    return protocol_hash("validation_evidence_execution/v1", mapping)


def submitted_jobs_sha256(projection: SubmittedJobsProjection) -> str:
    _d2_type(projection, SubmittedJobsProjection, _D2_SJ_CTX)
    mapping = projection.as_dict()
    _d2_exact(projection, decode_submitted_jobs_projection(mapping), _D2_SJ_CTX)
    return protocol_hash("validation_evidence_submitted_jobs/v1", mapping)


def execution_start_id(projection: ExecutionStartProjection) -> str:
    _d2_type(projection, ExecutionStartProjection, _D2_ST_CTX)
    mapping = projection.as_dict()
    _d2_exact(projection, decode_execution_start_projection(mapping), _D2_ST_CTX)
    return protocol_hash("validation_evidence_execution_start/v1", mapping)


def worker_identity(projection: WorkerIdentityProjection) -> str:
    _d2_type(projection, WorkerIdentityProjection, _D2_W_CTX)
    mapping = projection.as_dict()
    _d2_exact(projection, decode_worker_identity_projection(mapping), _D2_W_CTX)
    return protocol_hash("validation_evidence_worker_identity/v1", mapping)


def returned_result_id(projection: ReturnedResultProjection) -> str:
    _d2_type(projection, ReturnedResultProjection, _D2_RO_CTX)
    mapping = projection.as_dict()
    _d2_exact(projection, decode_returned_result_projection(mapping), _D2_RO_CTX)
    return protocol_hash("validation_evidence_returned_result/v1", mapping)


def result_batch_id(projection: ResultBatchProjection) -> str:
    _d2_type(projection, ResultBatchProjection, _D2_B_CTX)
    mapping = projection.as_dict()
    _d2_exact(projection, decode_result_batch_projection(mapping), _D2_B_CTX)
    return protocol_hash("validation_evidence_result_batch/v1", mapping)


def execution_completion_id(projection: ExecutionCompletionProjection) -> str:
    _d2_type(projection, ExecutionCompletionProjection, _D2_C_CTX)
    mapping = projection.as_dict()
    _d2_exact(projection, decode_execution_completion_projection(mapping), _D2_C_CTX)
    return protocol_hash("validation_evidence_execution_completion/v1", mapping)


def returned_results_sha256(projection: ReturnedResultsProjection) -> str:
    _d2_type(projection, ReturnedResultsProjection, _D2_RA_CTX)
    mapping = projection.as_dict()
    _d2_exact(projection, decode_returned_results_projection(mapping), _D2_RA_CTX)
    return protocol_hash("validation_evidence_returned_results/v1", mapping)


def worker_result_order_sha256(projection: WorkerResultOrderProjection) -> str:
    _d2_type(projection, WorkerResultOrderProjection, _D2_WO_CTX)
    mapping = projection.as_dict()
    _d2_exact(
        projection,
        decode_worker_result_order_projection(mapping),
        _D2_WO_CTX,
    )
    return protocol_hash("validation_evidence_worker_result_order/v1", mapping)


def executor_attestation_id(projection: ExecutorAttestationProjection) -> str:
    mapping = _stage2e_projection_mapping(
        projection,
        ExecutorAttestationProjection,
        _E_ID_CTX,
        "executor_attestation",
    )
    decoded = decode_executor_attestation_projection(mapping)
    decoded_mapping = _stage2e_projection_mapping(
        decoded,
        ExecutorAttestationProjection,
        _E_ID_CTX,
        "executor_attestation",
    )
    if decoded_mapping != mapping:
        _d2_fail(_E_ID_CTX, "executor_attestation", "projection does not exactly reconstruct")
    return protocol_hash("validation_evidence_executor_attestation/v1", mapping)


def validate_stage2d2_execution_foundations(
    *,
    expected_execution_instance: ExecutionInstanceProjection,
    execution_instance: ExecutionInstanceProjection,
    carried_execution_instance_identity: str,
    expected_execution: ExecutionIdentityProjection,
    execution: ExecutionIdentityProjection,
    carried_execution_id: str,
    expected_submitted_jobs: SubmittedJobsProjection,
    submitted_jobs: SubmittedJobsProjection,
    carried_submitted_jobs_sha256: str,
    expected_execution_start: ExecutionStartProjection,
    execution_start: ExecutionStartProjection,
    carried_execution_start_id: str,
    expected_workers_in_actual_delivery_order: tuple[WorkerIdentityProjection, ...],
    workers_in_actual_delivery_order: tuple[tuple[WorkerIdentityProjection, str], ...],
) -> None:
    _d2_type(execution_instance, ExecutionInstanceProjection, _D2_I_CTX)
    decoded_instance = decode_execution_instance_projection(execution_instance.as_dict())
    if decoded_instance.process_id == 0 or decoded_instance != expected_execution_instance:
        _d2_fail(_D2_I_CTX, "execution_instance", "trusted process observation differs")
    recomputed_instance_id = execution_instance_identity(decoded_instance)
    if recomputed_instance_id != carried_execution_instance_identity:
        _d2_fail(_D2_I_CTX, "execution_instance_identity", "identity differs")

    _d2_type(execution, ExecutionIdentityProjection, _D2_E_CTX)
    if (
        execution.execution_specification_id != expected_execution.execution_specification_id
        or execution.execution_instance.issuer_identity
        != expected_execution.execution_instance.issuer_identity
    ):
        _d2_fail(
            _D2_RL_CTX,
            "execution_identity.execution_specification_id",
            "authorized specification relation differs",
        )
    if (
        execution.execution_instance != execution_instance
        or execution.execution_instance_identity != recomputed_instance_id
    ):
        _d2_fail(
            _D2_E_CTX,
            "execution_identity.execution_instance",
            "validated instance occurrence differs",
        )
    relation_differs = (
        execution.implementation_commit != expected_execution.implementation_commit
        or execution.implementation_diff_sha256 != expected_execution.implementation_diff_sha256
        or execution.implementation_tree_sha256 != expected_execution.implementation_tree_sha256
        or execution.oracle_binding_id != expected_execution.oracle_binding_id
        or execution.oracle_execution_id != expected_execution.oracle_execution_id
        or execution.protocol_checkpoint != expected_execution.protocol_checkpoint
        or execution.role != expected_execution.role
        or execution.runtime_identity != expected_execution.runtime_identity
        or execution.study_id != expected_execution.study_id
        or execution.validation_authority_id != expected_execution.validation_authority_id
        or execution.validation_run_id != expected_execution.validation_run_id
    )
    if relation_differs:
        _d2_fail(
            _D2_RL_CTX,
            "execution_identity",
            "implementation/runtime/Oracle/authority relation differs",
        )
    if execution != expected_execution or execution_id(execution) != carried_execution_id:
        _d2_fail(_D2_E_CTX, "execution_id", "execution projection or identity differs")

    _d2_type(submitted_jobs, SubmittedJobsProjection, _D2_SJ_CTX)
    if submitted_jobs.configuration_sha256 != expected_submitted_jobs.configuration_sha256:
        _d2_fail(_D2_SJ_CTX, "submitted_jobs.configuration_sha256", "configuration differs")
    if len(submitted_jobs.jobs) != len(expected_submitted_jobs.jobs):
        _d2_fail(_D2_SJ_CTX, "submitted_jobs.jobs", "submitted job count differs")
    for index, job in enumerate(submitted_jobs.jobs):
        if (
            job != expected_submitted_jobs.jobs[index]
            or job.projection.submission_index != index
            or submitted_job_id(job.projection) != job.submitted_job_id
            or any(
                prior.submitted_job_id == job.submitted_job_id
                for prior in submitted_jobs.jobs[:index]
            )
        ):
            _d2_fail(
                _D2_SJ_CTX,
                f"submitted_jobs.jobs[{index}]",
                "submission order, identity, or uniqueness differs",
            )
    decoded_submitted = decode_submitted_jobs_projection(submitted_jobs.as_dict())
    submitted_relation_differs = (
        submitted_jobs.execution_id != carried_execution_id
        or submitted_jobs.execution_specification_id != execution.execution_specification_id
        or submitted_jobs.implementation.implementation_commit != execution.implementation_commit
        or submitted_jobs.implementation.implementation_diff_sha256
        != execution.implementation_diff_sha256
        or submitted_jobs.implementation.implementation_tree_sha256
        != execution.implementation_tree_sha256
        or submitted_jobs.oracle_binding_id != execution.oracle_binding_id
        or submitted_jobs.oracle_execution_id != execution.oracle_execution_id
        or submitted_jobs.protocol_checkpoint != execution.protocol_checkpoint
        or submitted_jobs.runtime_identity != execution.runtime_identity
        or submitted_jobs.study_id != execution.study_id
        or submitted_jobs.validation_authority_id != execution.validation_authority_id
        or submitted_jobs.validation_run_id != execution.validation_run_id
    )
    if (
        decoded_submitted != submitted_jobs
        or submitted_relation_differs
        or submitted_jobs != expected_submitted_jobs
    ):
        _d2_fail(
            _D2_SJ_CTX,
            "submitted_jobs_sha256",
            "submission aggregate or identity differs",
        )
    runtime_id = protocol_hash("validation_evidence_runtime/v1", submitted_jobs.runtime.as_dict())
    if runtime_id != submitted_jobs.runtime_identity:
        _d2_fail(
            _D2_SJ_CTX,
            "submitted_jobs.runtime_identity",
            "runtime identity differs",
        )
    if submitted_jobs_sha256(decoded_submitted) != carried_submitted_jobs_sha256:
        _d2_fail(
            _D2_SJ_CTX,
            "submitted_jobs_sha256",
            "submission aggregate or identity differs",
        )

    _d2_type(execution_start, ExecutionStartProjection, _D2_ST_CTX)
    decoded_start = decode_execution_start_projection(execution_start.as_dict())
    if (
        decoded_start.execution_id != carried_execution_id
        or decoded_start.execution_instance_identity != recomputed_instance_id
        or decoded_start.execution_specification_id != execution.execution_specification_id
        or decoded_start.validation_authority_id != execution.validation_authority_id
        or decoded_start.validation_run_id != execution.validation_run_id
        or decoded_start.started_at < execution_instance.process_started_at
    ):
        _d2_fail(_D2_ST_CTX, "execution_start", "start predecessor relation differs")
    if decoded_start != expected_execution_start:
        _d2_fail(_D2_ST_CTX, "execution_start", "complete start projection differs")
    if execution_start_id(decoded_start) != carried_execution_start_id:
        _d2_fail(_D2_ST_CTX, "execution_start_id", "start identity differs")

    if len(expected_workers_in_actual_delivery_order) != len(workers_in_actual_delivery_order):
        _d2_fail(_D2_W_CTX, "workers", "delivery observation counts differ")
    for index, (worker, _carried_worker_id) in enumerate(workers_in_actual_delivery_order):
        _d2_type(worker, WorkerIdentityProjection, _D2_W_CTX)
        expected_worker = expected_workers_in_actual_delivery_order[index]
        if (
            worker.process_id == 0
            or worker.thread_id == 0
            or worker.process_id != expected_worker.process_id
            or worker.thread_id != expected_worker.thread_id
            or worker.thread_name != expected_worker.thread_name
        ):
            _d2_fail(_D2_W_CTX, f"workers[{index}]", "native worker observation differs")
    for index, (worker, carried_worker_id) in enumerate(workers_in_actual_delivery_order):
        if (
            worker != expected_workers_in_actual_delivery_order[index]
            or worker.process_id != execution_instance.process_id
            or worker.execution_instance_identity != recomputed_instance_id
            or worker.execution_specification_id != execution.execution_specification_id
            or worker.validation_authority_id != execution.validation_authority_id
            or worker.validation_run_id != execution.validation_run_id
        ):
            _d2_fail(_D2_W_CTX, f"workers[{index}]", "worker predecessor relation differs")
        if worker_identity(worker) != carried_worker_id:
            _d2_fail(
                _D2_W_CTX,
                f"workers[{index}].worker_identity",
                "worker identity differs",
            )


def _d2_payload_job(
    payload: ReturnedRunProjection,
    submitted_jobs: tuple[SubmittedJobProjection, ...],
    submitted_job_identity: str,
) -> SubmittedJobProjection:
    matches = tuple(job for job in submitted_jobs if job.submitted_job_id == submitted_job_identity)
    if len(matches) != 1:
        _d2_fail(
            _D2_RO_CTX,
            "returned_result.submitted_job_id",
            "returned result does not identify exactly one submitted job",
        )
    payload_content = (
        payload.world_id,
        payload.seed,
        payload.budget_id,
        payload.budget,
        *payload.arm,
    )
    if _validation_job_content(matches[0].projection) != payload_content:
        _d2_fail(
            _D2_RO_CTX,
            "returned_result.submitted_job_id",
            "identified submitted job content differs from payload",
        )
    return matches[0]


def build_job_result_mapping(
    submitted_jobs: tuple[SubmittedJobProjection, ...],
    results_in_actual_delivery_order: tuple[ReturnedResultObservation, ...],
) -> JobResultMapping:
    if type(submitted_jobs) is not tuple or type(results_in_actual_delivery_order) is not tuple:
        _d2_fail(_D2_M_CTX, "job_result_mapping", "ordered inputs must be exact tuples")
    if len(submitted_jobs) != len(results_in_actual_delivery_order):
        _d2_fail(_D2_M_CTX, "job_result_mapping", "submitted and returned counts differ")

    submitted_ids: list[str] = []
    for index, job in enumerate(submitted_jobs):
        if (
            type(job) is not SubmittedJobProjection
            or type(job.projection) is not ValidationJobProjection
        ):
            _d2_fail(_D2_M_CTX, f"submitted_jobs[{index}]", "wrong submitted-job type")
        submitted_ids.append(
            _ExecutionEvidenceDecoder(
                job.submitted_job_id,
                f"submitted_jobs[{index}].submitted_job_id",
                _D2_M_CTX,
            ).h64()
        )

    result_rows: list[tuple[str, str]] = []
    for index, observation in enumerate(results_in_actual_delivery_order):
        if type(observation) is not tuple or len(observation) != 3:
            _d2_fail(_D2_M_CTX, f"results[{index}]", "wrong returned observation shape")
        projection, carried_id, payload = observation
        if type(projection) is not ReturnedResultProjection:
            _d2_fail(_D2_M_CTX, f"results[{index}]", "wrong returned-result type")
        if type(payload) is not ReturnedRunProjection:
            _d2_fail(_D2_M_CTX, f"results[{index}]", "wrong returned payload type")
        submitted_id = _ExecutionEvidenceDecoder(
            projection.submitted_job_id,
            f"results[{index}].submitted_job_id",
            _D2_M_CTX,
        ).h64()
        checked_id = _ExecutionEvidenceDecoder(
            carried_id,
            f"results[{index}].returned_result_id",
            _D2_M_CTX,
        ).h64()
        result_rows.append((submitted_id, checked_id))

    mapping_rows: list[tuple[str, str]] = []
    matched_result_indexes: set[int] = set()
    for submitted_id in submitted_ids:
        matches = tuple(
            (index, returned_id)
            for index, (result_job_id, returned_id) in enumerate(result_rows)
            if result_job_id == submitted_id
        )
        if len(matches) != 1:
            _d2_fail(
                _D2_M_CTX,
                "job_result_mapping",
                "each submitted job must identify exactly one returned result",
            )
        result_index, returned_id = matches[0]
        matched_result_indexes.add(result_index)
        mapping_rows.append((submitted_id, returned_id))

    if len(set(submitted_ids)) != len(submitted_ids):
        _d2_fail(_D2_M_CTX, "job_result_mapping", "submitted job identity is duplicated")
    returned_ids = tuple(returned_id for _submitted_id, returned_id in result_rows)
    if len(set(returned_ids)) != len(returned_ids):
        _d2_fail(_D2_M_CTX, "job_result_mapping", "returned-result identity is duplicated")
    if len(matched_result_indexes) != len(result_rows):
        _d2_fail(_D2_M_CTX, "job_result_mapping", "submitted/result sets differ")
    return tuple(mapping_rows)


def validate_stage2d2_returned_results(
    *,
    expected_execution_instance: ExecutionInstanceProjection,
    execution_instance: ExecutionInstanceProjection,
    carried_execution_instance_identity: str,
    expected_execution: ExecutionIdentityProjection,
    execution: ExecutionIdentityProjection,
    carried_execution_id: str,
    expected_submitted_jobs: SubmittedJobsProjection,
    submitted_jobs: SubmittedJobsProjection,
    carried_submitted_jobs_sha256: str,
    expected_execution_start: ExecutionStartProjection,
    execution_start: ExecutionStartProjection,
    carried_execution_start_id: str,
    expected_workers_in_actual_delivery_order: tuple[WorkerIdentityProjection, ...],
    workers_in_actual_delivery_order: tuple[tuple[WorkerIdentityProjection, str], ...],
    returned_domains_in_actual_delivery_order: tuple[BroaderArmRun, ...],
    returned_runs_in_actual_delivery_order: tuple[ReturnedRunProjection, ...],
    returned_result_projections_in_actual_delivery_order: tuple[ReturnedResultProjection, ...],
    carried_returned_result_ids_in_actual_delivery_order: tuple[str, ...],
) -> tuple[tuple[ReturnedResultObservation, ...], JobResultMapping]:
    validate_stage2d2_execution_foundations(
        expected_execution_instance=expected_execution_instance,
        execution_instance=execution_instance,
        carried_execution_instance_identity=carried_execution_instance_identity,
        expected_execution=expected_execution,
        execution=execution,
        carried_execution_id=carried_execution_id,
        expected_submitted_jobs=expected_submitted_jobs,
        submitted_jobs=submitted_jobs,
        carried_submitted_jobs_sha256=carried_submitted_jobs_sha256,
        expected_execution_start=expected_execution_start,
        execution_start=execution_start,
        carried_execution_start_id=carried_execution_start_id,
        expected_workers_in_actual_delivery_order=expected_workers_in_actual_delivery_order,
        workers_in_actual_delivery_order=workers_in_actual_delivery_order,
    )

    try:
        accepted_payloads = validate_returned_run_batch(
            returned_runs_in_actual_delivery_order=returned_runs_in_actual_delivery_order,
            returned_domains_in_actual_delivery_order=returned_domains_in_actual_delivery_order,
        )
    except ReturnedRunProjectionError as error:
        code = error.failure_code or _D2_RR_CTX[0]
        _d2_fail((code, "returned_run"), error.path, str(error))

    if type(accepted_payloads) is not tuple:
        _d2_fail(_D2_RR_CTX, "returned_runs", "batch acceptance must be an exact tuple")
    if len(returned_runs_in_actual_delivery_order) != len(accepted_payloads):
        _d2_fail(_D2_RR_CTX, "returned_runs", "batch acceptance count differs")
    payload_hashes: list[str] = []
    for index, accepted_payload in enumerate(accepted_payloads):
        if type(accepted_payload) is not tuple or len(accepted_payload) != 2:
            _d2_fail(_D2_RR_CTX, f"returned_runs[{index}]", "wrong batch result shape")
        validated_domain, payload_hash_value = accepted_payload
        if type(validated_domain) is not BroaderArmRun:
            _d2_fail(_D2_RR_CTX, f"returned_runs[{index}]", "wrong validated domain type")
        payload_hashes.append(
            _ExecutionEvidenceDecoder(
                payload_hash_value,
                f"returned_runs[{index}].result_payload_sha256",
                _D2_RR_CTX,
            ).h64()
        )

    if (
        type(returned_result_projections_in_actual_delivery_order) is not tuple
        or type(carried_returned_result_ids_in_actual_delivery_order) is not tuple
    ):
        _d2_fail(_D2_RO_CTX, "returned_results", "3k inputs must be exact tuples")
    count = len(payload_hashes)
    if not (
        len(workers_in_actual_delivery_order)
        == len(returned_result_projections_in_actual_delivery_order)
        == len(carried_returned_result_ids_in_actual_delivery_order)
        == count
    ):
        _d2_fail(_D2_RO_CTX, "returned_results", "delivery observation counts differ")

    observations: list[ReturnedResultObservation] = []
    checked_ids: list[str] = []
    for index, (
        _worker_observation,
        payload,
        payload_hash,
        result_projection,
        carried_id,
    ) in enumerate(
        zip(
            workers_in_actual_delivery_order,
            returned_runs_in_actual_delivery_order,
            payload_hashes,
            returned_result_projections_in_actual_delivery_order,
            carried_returned_result_ids_in_actual_delivery_order,
            strict=True,
        )
    ):
        if type(result_projection) is not ReturnedResultProjection:
            _d2_fail(_D2_RO_CTX, f"returned_results[{index}]", "wrong projection type")
        decoded_result = decode_returned_result_projection(result_projection.as_dict())
        if decoded_result.execution_id != carried_execution_id:
            _d2_fail(
                _D2_RO_CTX,
                f"returned_results[{index}].execution_id",
                "execution relation differs",
            )
        if decoded_result.execution_specification_id != execution.execution_specification_id:
            _d2_fail(
                _D2_RO_CTX,
                f"returned_results[{index}].execution_specification_id",
                "execution-specification relation differs",
            )
        if decoded_result.result_payload_sha256 != payload_hash:
            _d2_fail(
                _D2_RO_CTX,
                f"returned_results[{index}].result_payload_sha256",
                "accepted payload commitment differs",
            )
        job = _d2_payload_job(
            payload,
            submitted_jobs.jobs,
            decoded_result.submitted_job_id,
        )
        if decoded_result.validation_authority_id != execution.validation_authority_id:
            _d2_fail(
                _D2_RO_CTX,
                f"returned_results[{index}].validation_authority_id",
                "validation-authority relation differs",
            )
        if decoded_result.validation_run_id != execution.validation_run_id:
            _d2_fail(
                _D2_RO_CTX,
                f"returned_results[{index}].validation_run_id",
                "validation-run relation differs",
            )
        if decoded_result != ReturnedResultProjection(
            carried_execution_id,
            execution.execution_specification_id,
            payload_hash,
            "broader-replication-returned-result/v1",
            job.submitted_job_id,
            execution.validation_authority_id,
            execution.validation_run_id,
        ):
            _d2_fail(
                _D2_RO_CTX,
                f"returned_results[{index}]",
                "returned occurrence relation differs",
            )

        checked_id = _ExecutionEvidenceDecoder(
            carried_id,
            f"returned_results[{index}].returned_result_id",
            _D2_RO_CTX,
        ).h64()
        if returned_result_id(decoded_result) != checked_id:
            _d2_fail(_D2_RO_CTX, f"returned_results[{index}]", "identity differs")
        checked_ids.append(checked_id)
        observations.append((decoded_result, checked_id, payload))

    if len(set(checked_ids)) != len(checked_ids):
        _d2_fail(_D2_RO_CTX, "returned_results", "duplicate returned-result identity")

    accepted_observations = tuple(observations)
    mapping = build_job_result_mapping(submitted_jobs.jobs, accepted_observations)
    return accepted_observations, mapping


def validate_stage2d2_result_batch_completion(
    *,
    expected_execution_instance: ExecutionInstanceProjection,
    execution_instance: ExecutionInstanceProjection,
    carried_execution_instance_identity: str,
    expected_execution: ExecutionIdentityProjection,
    execution: ExecutionIdentityProjection,
    carried_execution_id: str,
    expected_submitted_jobs: SubmittedJobsProjection,
    submitted_jobs: SubmittedJobsProjection,
    carried_submitted_jobs_sha256: str,
    expected_execution_start: ExecutionStartProjection,
    execution_start: ExecutionStartProjection,
    carried_execution_start_id: str,
    expected_workers_in_actual_delivery_order: tuple[WorkerIdentityProjection, ...],
    workers_in_actual_delivery_order: tuple[tuple[WorkerIdentityProjection, str], ...],
    returned_domains_in_actual_delivery_order: tuple[BroaderArmRun, ...],
    returned_runs_in_actual_delivery_order: tuple[ReturnedRunProjection, ...],
    returned_result_projections_in_actual_delivery_order: tuple[ReturnedResultProjection, ...],
    carried_returned_result_ids_in_actual_delivery_order: tuple[str, ...],
    job_result_mapping: JobResultMapping,
    result_batch: ResultBatchProjection,
    carried_result_batch_id: str,
    observed_execution_status: str,
    observed_completed_at: str,
    execution_completion: ExecutionCompletionProjection,
    carried_execution_completion_id: str,
) -> tuple[tuple[ReturnedResultObservation, ...], JobResultMapping]:
    accepted_observations, expected_mapping = validate_stage2d2_returned_results(
        expected_execution_instance=expected_execution_instance,
        execution_instance=execution_instance,
        carried_execution_instance_identity=carried_execution_instance_identity,
        expected_execution=expected_execution,
        execution=execution,
        carried_execution_id=carried_execution_id,
        expected_submitted_jobs=expected_submitted_jobs,
        submitted_jobs=submitted_jobs,
        carried_submitted_jobs_sha256=carried_submitted_jobs_sha256,
        expected_execution_start=expected_execution_start,
        execution_start=execution_start,
        carried_execution_start_id=carried_execution_start_id,
        expected_workers_in_actual_delivery_order=expected_workers_in_actual_delivery_order,
        workers_in_actual_delivery_order=workers_in_actual_delivery_order,
        returned_domains_in_actual_delivery_order=returned_domains_in_actual_delivery_order,
        returned_runs_in_actual_delivery_order=returned_runs_in_actual_delivery_order,
        returned_result_projections_in_actual_delivery_order=(
            returned_result_projections_in_actual_delivery_order
        ),
        carried_returned_result_ids_in_actual_delivery_order=(
            carried_returned_result_ids_in_actual_delivery_order
        ),
    )

    if type(job_result_mapping) is not tuple:
        _d2_fail(_D2_M_CTX, "job_result_mapping", "mapping must be an exact tuple")
    checked_mapping: list[tuple[str, str]] = []
    for index, row in enumerate(job_result_mapping):
        if type(row) is not tuple or len(row) != 2:
            _d2_fail(
                _D2_M_CTX,
                f"job_result_mapping[{index}]",
                "mapping row must be an exact two-element tuple",
            )
        checked_mapping.append(
            (
                _ExecutionEvidenceDecoder(
                    row[0],
                    f"job_result_mapping[{index}][0]",
                    _D2_M_CTX,
                ).h64(),
                _ExecutionEvidenceDecoder(
                    row[1],
                    f"job_result_mapping[{index}][1]",
                    _D2_M_CTX,
                ).h64(),
            )
        )
    if tuple(checked_mapping) != expected_mapping:
        _d2_fail(
            _D2_M_CTX,
            "job_result_mapping",
            "complete submission-order job/result bijection differs",
        )

    expected_batch = ResultBatchProjection(
        execution_id=carried_execution_id,
        execution_specification_id=execution.execution_specification_id,
        job_result_mapping=expected_mapping,
        result_payload_sha256_in_delivery_order=tuple(
            observation[0].result_payload_sha256 for observation in accepted_observations
        ),
        returned_result_ids_in_delivery_order=tuple(
            observation[1] for observation in accepted_observations
        ),
        schema_version="broader-replication-result-batch/v1",
        validation_authority_id=execution.validation_authority_id,
        validation_run_id=execution.validation_run_id,
    )
    _d2_type(result_batch, ResultBatchProjection, _D2_B_CTX)
    decoded_batch = decode_result_batch_projection(result_batch.as_dict())
    if decoded_batch != expected_batch:
        _d2_fail(
            _D2_B_CTX,
            "result_batch",
            "submission mapping or actual-delivery batch relation differs",
        )
    recomputed_batch_id = result_batch_id(decoded_batch)
    checked_batch_id = _ExecutionEvidenceDecoder(
        carried_result_batch_id,
        "result_batch_id",
        _D2_B_CTX,
    ).h64()
    if recomputed_batch_id != checked_batch_id:
        _d2_fail(_D2_B_CTX, "result_batch_id", "identity differs")

    _d2_type(execution_completion, ExecutionCompletionProjection, _D2_C_CTX)
    if (
        type(observed_execution_status) is not str
        or observed_execution_status != "success"
        or type(execution_completion.execution_status) is not str
        or execution_completion.execution_status != "success"
    ):
        _d2_fail(
            _D2_C_CTX,
            "execution_completion.execution_status",
            "only an observed complete success may be accepted",
        )
    if execution_completion.job_result_mapping != expected_mapping:
        _d2_fail(
            _D2_C_CTX,
            "execution_completion.job_result_mapping",
            "complete submission-order mapping differs",
        )
    observed_worker_ids: list[str] = []
    seen_worker_ids: set[str] = set()
    for _worker, worker_id_value in workers_in_actual_delivery_order:
        if worker_id_value not in seen_worker_ids:
            seen_worker_ids.add(worker_id_value)
            observed_worker_ids.append(worker_id_value)
    expected_worker_ids = tuple(observed_worker_ids)
    if execution_completion.observed_worker_ids != expected_worker_ids:
        _d2_fail(
            _D2_C_CTX,
            "execution_completion.observed_worker_ids",
            "unique first-worker order differs",
        )
    expected_returned_ids = tuple(observation[1] for observation in accepted_observations)
    if execution_completion.returned_result_ids_in_delivery_order != expected_returned_ids:
        _d2_fail(
            _D2_C_CTX,
            "execution_completion.returned_result_ids_in_delivery_order",
            "actual-delivery returned-result order differs",
        )
    checked_completed_at = _ExecutionEvidenceDecoder(
        observed_completed_at,
        "execution_completion.completed_at",
        _D2_C_CTX,
    ).timestamp()
    if (
        checked_completed_at < execution_start.started_at
        or execution_completion.completed_at != checked_completed_at
    ):
        _d2_fail(
            _D2_C_CTX,
            "execution_completion.completed_at",
            "completion timestamp relation differs",
        )
    expected_completion = ExecutionCompletionProjection(
        completed_at=checked_completed_at,
        execution_id=carried_execution_id,
        execution_specification_id=execution.execution_specification_id,
        execution_start_id=carried_execution_start_id,
        execution_status="success",
        job_result_mapping=expected_mapping,
        observed_worker_ids=expected_worker_ids,
        returned_result_ids_in_delivery_order=expected_returned_ids,
        schema_version="broader-replication-execution-completion/v1",
        validation_authority_id=execution.validation_authority_id,
        validation_run_id=execution.validation_run_id,
    )
    decoded_completion = decode_execution_completion_projection(execution_completion.as_dict())
    if decoded_completion != expected_completion:
        _d2_fail(
            _D2_C_CTX,
            "execution_completion",
            "successful complete execution relation differs",
        )
    recomputed_completion_id = execution_completion_id(decoded_completion)
    checked_completion_id = _ExecutionEvidenceDecoder(
        carried_execution_completion_id,
        "execution_completion_id",
        _D2_C_CTX,
    ).h64()
    if recomputed_completion_id != checked_completion_id:
        _d2_fail(_D2_C_CTX, "execution_completion_id", "identity differs")
    return accepted_observations, expected_mapping


def validate_stage2d2_result_aggregates(
    *,
    expected_execution_instance: ExecutionInstanceProjection,
    execution_instance: ExecutionInstanceProjection,
    carried_execution_instance_identity: str,
    expected_execution: ExecutionIdentityProjection,
    execution: ExecutionIdentityProjection,
    carried_execution_id: str,
    expected_submitted_jobs: SubmittedJobsProjection,
    submitted_jobs: SubmittedJobsProjection,
    carried_submitted_jobs_sha256: str,
    expected_execution_start: ExecutionStartProjection,
    execution_start: ExecutionStartProjection,
    carried_execution_start_id: str,
    expected_workers_in_actual_delivery_order: tuple[WorkerIdentityProjection, ...],
    workers_in_actual_delivery_order: tuple[tuple[WorkerIdentityProjection, str], ...],
    returned_domains_in_actual_delivery_order: tuple[BroaderArmRun, ...],
    returned_runs_in_actual_delivery_order: tuple[ReturnedRunProjection, ...],
    returned_result_projections_in_actual_delivery_order: tuple[ReturnedResultProjection, ...],
    carried_returned_result_ids_in_actual_delivery_order: tuple[str, ...],
    job_result_mapping: JobResultMapping,
    result_batch: ResultBatchProjection,
    carried_result_batch_id: str,
    observed_execution_status: str,
    observed_completed_at: str,
    execution_completion: ExecutionCompletionProjection,
    carried_execution_completion_id: str,
    returned_results: ReturnedResultsProjection,
    carried_returned_results_sha256: str,
    worker_result_order: WorkerResultOrderProjection,
    carried_worker_result_order_sha256: str,
) -> tuple[tuple[ReturnedResultObservation, ...], JobResultMapping]:
    accepted_observations, expected_mapping = validate_stage2d2_result_batch_completion(
        expected_execution_instance=expected_execution_instance,
        execution_instance=execution_instance,
        carried_execution_instance_identity=carried_execution_instance_identity,
        expected_execution=expected_execution,
        execution=execution,
        carried_execution_id=carried_execution_id,
        expected_submitted_jobs=expected_submitted_jobs,
        submitted_jobs=submitted_jobs,
        carried_submitted_jobs_sha256=carried_submitted_jobs_sha256,
        expected_execution_start=expected_execution_start,
        execution_start=execution_start,
        carried_execution_start_id=carried_execution_start_id,
        expected_workers_in_actual_delivery_order=(expected_workers_in_actual_delivery_order),
        workers_in_actual_delivery_order=workers_in_actual_delivery_order,
        returned_domains_in_actual_delivery_order=(returned_domains_in_actual_delivery_order),
        returned_runs_in_actual_delivery_order=returned_runs_in_actual_delivery_order,
        returned_result_projections_in_actual_delivery_order=(
            returned_result_projections_in_actual_delivery_order
        ),
        carried_returned_result_ids_in_actual_delivery_order=(
            carried_returned_result_ids_in_actual_delivery_order
        ),
        job_result_mapping=job_result_mapping,
        result_batch=result_batch,
        carried_result_batch_id=carried_result_batch_id,
        observed_execution_status=observed_execution_status,
        observed_completed_at=observed_completed_at,
        execution_completion=execution_completion,
        carried_execution_completion_id=carried_execution_completion_id,
    )

    submission_rows: list[tuple[str, ReturnedRunProjection, str]] = []
    for job, (mapped_job_id, returned_result_id_value) in zip(
        submitted_jobs.jobs,
        expected_mapping,
        strict=True,
    ):
        if job.submitted_job_id != mapped_job_id:
            _d2_fail(
                _D2_RA_CTX,
                "returned_results.job_result_mapping",
                "mapping does not follow submitted-job order",
            )
        matches = tuple(
            observation
            for observation in accepted_observations
            if observation[1] == returned_result_id_value
        )
        if len(matches) != 1:
            _d2_fail(
                _D2_RA_CTX,
                "returned_results.results_in_submission_order",
                "mapped returned-result occurrence is not unique",
            )
        submission_rows.append(
            (
                returned_result_id_value,
                matches[0][2],
                job.submitted_job_id,
            )
        )
    expected_submission_rows = tuple(submission_rows)
    expected_returned_results = ReturnedResultsProjection(
        execution_completion_id=carried_execution_completion_id,
        execution_id=carried_execution_id,
        execution_specification_id=execution.execution_specification_id,
        execution_status="success",
        implementation=submitted_jobs.implementation,
        job_result_mapping=expected_mapping,
        oracle_binding_id=execution.oracle_binding_id,
        oracle_execution_id=execution.oracle_execution_id,
        protocol_checkpoint=_D2_CHECKPOINT,
        results_in_submission_order=expected_submission_rows,
        runtime=submitted_jobs.runtime,
        runtime_identity=submitted_jobs.runtime_identity,
        schema_version="broader-replication-returned-results/v1",
        study_id=_D2_STUDY,
        validation_authority_id=execution.validation_authority_id,
        validation_run_id=execution.validation_run_id,
    )

    _d2_type(returned_results, ReturnedResultsProjection, _D2_RA_CTX)
    if returned_results.job_result_mapping != expected_mapping:
        _d2_fail(
            _D2_RA_CTX,
            "returned_results.job_result_mapping",
            "submission-order mapping differs",
        )
    actual_submission_rows = returned_results.results_in_submission_order
    if type(actual_submission_rows) is not tuple:
        _d2_fail(
            _D2_RA_CTX,
            "returned_results.results_in_submission_order",
            "submission rows must be an exact tuple",
        )
    for index, expected_row in enumerate(expected_submission_rows):
        if index >= len(actual_submission_rows):
            break
        actual_row = actual_submission_rows[index]
        if type(actual_row) is not tuple or len(actual_row) != 3:
            _d2_fail(
                _D2_RA_CTX,
                f"returned_results.results_in_submission_order[{index}]",
                "submission row must be an exact three-element tuple",
            )
        if actual_row[2] != expected_row[2]:
            _d2_fail(
                _D2_RA_CTX,
                f"returned_results.results_in_submission_order[{index}].submitted_job_id",
                "submitted-job occurrence differs",
            )
        if actual_row[0] != expected_row[0]:
            _d2_fail(
                _D2_RA_CTX,
                f"returned_results.results_in_submission_order[{index}].returned_result_id",
                "returned-result occurrence differs",
            )
        if type(actual_row[1]) is not ReturnedRunProjection or actual_row[1] != expected_row[1]:
            _d2_fail(
                _D2_RA_CTX,
                f"returned_results.results_in_submission_order[{index}].projection",
                "full returned-run projection differs",
            )
    if (
        len(actual_submission_rows) != len(expected_submission_rows)
        or len({row[0] for row in actual_submission_rows}) != len(actual_submission_rows)
        or len({row[2] for row in actual_submission_rows}) != len(actual_submission_rows)
    ):
        _d2_fail(
            _D2_RA_CTX,
            "returned_results.results_in_submission_order",
            "submission-row cardinality or uniqueness differs",
        )
    decoded_returned_results = decode_returned_results_projection(returned_results.as_dict())
    if decoded_returned_results != expected_returned_results:
        _d2_fail(
            _D2_RA_CTX,
            "returned_results",
            "complete submission-order aggregate differs",
        )
    recomputed_returned_results_sha256 = returned_results_sha256(decoded_returned_results)
    checked_returned_results_sha256 = _ExecutionEvidenceDecoder(
        carried_returned_results_sha256,
        "returned_results_sha256",
        _D2_RA_CTX,
    ).h64()
    if recomputed_returned_results_sha256 != checked_returned_results_sha256:
        _d2_fail(_D2_RA_CTX, "returned_results_sha256", "identity differs")

    expected_delivery_rows = tuple(
        (index, observation[1], worker, worker_id_value)
        for index, (observation, (worker, worker_id_value)) in enumerate(
            zip(
                accepted_observations,
                workers_in_actual_delivery_order,
                strict=True,
            )
        )
    )
    expected_worker_result_order = WorkerResultOrderProjection(
        execution_completion_id=carried_execution_completion_id,
        execution_id=carried_execution_id,
        execution_specification_id=execution.execution_specification_id,
        execution_status="success",
        implementation=submitted_jobs.implementation,
        job_result_mapping=expected_mapping,
        oracle_binding_id=execution.oracle_binding_id,
        oracle_execution_id=execution.oracle_execution_id,
        protocol_checkpoint=_D2_CHECKPOINT,
        results_in_actual_delivery_order=expected_delivery_rows,
        runtime=submitted_jobs.runtime,
        runtime_identity=submitted_jobs.runtime_identity,
        schema_version="broader-replication-worker-result-order/v1",
        study_id=_D2_STUDY,
        validation_authority_id=execution.validation_authority_id,
        validation_run_id=execution.validation_run_id,
    )

    _d2_type(worker_result_order, WorkerResultOrderProjection, _D2_WO_CTX)
    actual_delivery_rows = worker_result_order.results_in_actual_delivery_order
    if type(actual_delivery_rows) is not tuple:
        _d2_fail(
            _D2_WO_CTX,
            "worker_result_order.results_in_actual_delivery_order",
            "delivery rows must be an exact tuple",
        )
    for index, expected_delivery_row in enumerate(expected_delivery_rows):
        if index >= len(actual_delivery_rows):
            break
        actual_delivery_row = actual_delivery_rows[index]
        if type(actual_delivery_row) is not tuple or len(actual_delivery_row) != 4:
            _d2_fail(
                _D2_WO_CTX,
                f"worker_result_order.results_in_actual_delivery_order[{index}]",
                "delivery row must be an exact four-element tuple",
            )
        if (
            type(actual_delivery_row[0]) is not int
            or actual_delivery_row[0] != expected_delivery_row[0]
        ):
            _d2_fail(
                _D2_WO_CTX,
                f"worker_result_order.results_in_actual_delivery_order[{index}].delivery_index",
                "zero-based delivery index differs",
            )
        if actual_delivery_row[1] != expected_delivery_row[1]:
            _d2_fail(
                _D2_WO_CTX,
                f"worker_result_order.results_in_actual_delivery_order[{index}].returned_result_id",
                "actual-delivery returned-result occurrence differs",
            )
        if (
            type(actual_delivery_row[2]) is not WorkerIdentityProjection
            or actual_delivery_row[2] != expected_delivery_row[2]
        ):
            _d2_fail(
                _D2_WO_CTX,
                f"worker_result_order.results_in_actual_delivery_order[{index}].worker",
                "worker projection differs",
            )
        if actual_delivery_row[3] != expected_delivery_row[3]:
            _d2_fail(
                _D2_WO_CTX,
                f"worker_result_order.results_in_actual_delivery_order[{index}].worker_identity",
                "worker identity differs",
            )
    if len(actual_delivery_rows) != len(expected_delivery_rows) or len(
        {row[1] for row in actual_delivery_rows}
    ) != len(actual_delivery_rows):
        _d2_fail(
            _D2_WO_CTX,
            "worker_result_order.results_in_actual_delivery_order",
            "delivery-row cardinality or returned-result uniqueness differs",
        )
    observed_worker_ids: list[str] = []
    seen_worker_ids: set[str] = set()
    for row in actual_delivery_rows:
        if row[3] not in seen_worker_ids:
            seen_worker_ids.add(row[3])
            observed_worker_ids.append(row[3])
    if tuple(observed_worker_ids) != execution_completion.observed_worker_ids:
        _d2_fail(
            _D2_WO_CTX,
            "worker_result_order.results_in_actual_delivery_order",
            "unique first-worker order differs from completion",
        )
    decoded_worker_result_order = decode_worker_result_order_projection(
        worker_result_order.as_dict()
    )
    if decoded_worker_result_order != expected_worker_result_order:
        _d2_fail(
            _D2_WO_CTX,
            "worker_result_order",
            "complete actual-delivery aggregate differs",
        )
    recomputed_worker_result_order_sha256 = worker_result_order_sha256(decoded_worker_result_order)
    checked_worker_result_order_sha256 = _ExecutionEvidenceDecoder(
        carried_worker_result_order_sha256,
        "worker_result_order_sha256",
        _D2_WO_CTX,
    ).h64()
    if recomputed_worker_result_order_sha256 != checked_worker_result_order_sha256:
        _d2_fail(_D2_WO_CTX, "worker_result_order_sha256", "identity differs")
    return accepted_observations, expected_mapping


def validate_stage2e_executor_attestation(
    *,
    expected_validation_authority: ValidationAuthorityProjection,
    expected_execution_specification: ExecutionSpecificationProjection,
    expected_executor_implementation: ExecutorImplementationProjection,
    expected_executor_implementation_identity: str,
    accepted_job_ids_in_actual_acceptance_order: tuple[str, ...],
    expected_execution_instance: ExecutionInstanceProjection,
    execution_instance: ExecutionInstanceProjection,
    carried_execution_instance_identity: str,
    expected_execution: ExecutionIdentityProjection,
    execution: ExecutionIdentityProjection,
    carried_execution_id: str,
    expected_submitted_jobs: SubmittedJobsProjection,
    submitted_jobs: SubmittedJobsProjection,
    carried_submitted_jobs_sha256: str,
    expected_execution_start: ExecutionStartProjection,
    execution_start: ExecutionStartProjection,
    carried_execution_start_id: str,
    expected_workers_in_actual_delivery_order: tuple[WorkerIdentityProjection, ...],
    workers_in_actual_delivery_order: tuple[tuple[WorkerIdentityProjection, str], ...],
    returned_domains_in_actual_delivery_order: tuple[BroaderArmRun, ...],
    returned_runs_in_actual_delivery_order: tuple[ReturnedRunProjection, ...],
    returned_result_projections_in_actual_delivery_order: tuple[ReturnedResultProjection, ...],
    carried_returned_result_ids_in_actual_delivery_order: tuple[str, ...],
    job_result_mapping: JobResultMapping,
    result_batch: ResultBatchProjection,
    carried_result_batch_id: str,
    observed_execution_status: str,
    observed_completed_at: str,
    execution_completion: ExecutionCompletionProjection,
    carried_execution_completion_id: str,
    returned_results: ReturnedResultsProjection,
    carried_returned_results_sha256: str,
    worker_result_order: WorkerResultOrderProjection,
    carried_worker_result_order_sha256: str,
    executor_attestation: ExecutorAttestationProjection,
    carried_executor_attestation_id: str,
) -> ExecutorAttestationProjection:
    """Validate the complete 3g-3n chain without issuing authority or executing work."""

    accepted_observations, expected_mapping = validate_stage2d2_result_aggregates(
        expected_execution_instance=expected_execution_instance,
        execution_instance=execution_instance,
        carried_execution_instance_identity=carried_execution_instance_identity,
        expected_execution=expected_execution,
        execution=execution,
        carried_execution_id=carried_execution_id,
        expected_submitted_jobs=expected_submitted_jobs,
        submitted_jobs=submitted_jobs,
        carried_submitted_jobs_sha256=carried_submitted_jobs_sha256,
        expected_execution_start=expected_execution_start,
        execution_start=execution_start,
        carried_execution_start_id=carried_execution_start_id,
        expected_workers_in_actual_delivery_order=(expected_workers_in_actual_delivery_order),
        workers_in_actual_delivery_order=workers_in_actual_delivery_order,
        returned_domains_in_actual_delivery_order=(returned_domains_in_actual_delivery_order),
        returned_runs_in_actual_delivery_order=returned_runs_in_actual_delivery_order,
        returned_result_projections_in_actual_delivery_order=(
            returned_result_projections_in_actual_delivery_order
        ),
        carried_returned_result_ids_in_actual_delivery_order=(
            carried_returned_result_ids_in_actual_delivery_order
        ),
        job_result_mapping=job_result_mapping,
        result_batch=result_batch,
        carried_result_batch_id=carried_result_batch_id,
        observed_execution_status=observed_execution_status,
        observed_completed_at=observed_completed_at,
        execution_completion=execution_completion,
        carried_execution_completion_id=carried_execution_completion_id,
        returned_results=returned_results,
        carried_returned_results_sha256=carried_returned_results_sha256,
        worker_result_order=worker_result_order,
        carried_worker_result_order_sha256=carried_worker_result_order_sha256,
    )

    # 3n.1: the carried specification must occupy one exact authority-plan slot.
    executor_attestation = _stage2e_type(
        executor_attestation,
        ExecutorAttestationProjection,
        _E_ID_CTX,
        "executor_attestation",
    )
    expected_validation_authority = _stage2e_type(
        expected_validation_authority,
        ValidationAuthorityProjection,
        _E_AU_CTX,
        "validation_authority",
    )
    fixture_specifications = _stage2e_type(
        expected_validation_authority.production_fixture_execution_specification_ids,
        tuple,
        _E_AU_CTX,
        "validation_authority.production_fixture_execution_specification_ids",
    )
    if len(fixture_specifications) != 2:
        _d2_fail(_E_AU_CTX, "validation_authority", "authority plan set is malformed")
    authorized_specifications = _stage2e_strings(
        _E_AU_CTX,
        "validation_authority",
        (
            "primary_smoke_execution_specification_id",
            expected_validation_authority.primary_smoke_execution_specification_id,
        ),
        (
            "replay_execution_specification_id",
            expected_validation_authority.replay_execution_specification_id,
        ),
        ("production_fixture_execution_specification_ids[0]", fixture_specifications[0]),
        ("production_fixture_execution_specification_ids[1]", fixture_specifications[1]),
    )
    checked_authorized_specifications = tuple(
        _ExecutionEvidenceDecoder(
            value,
            f"validation_authority.execution_specification_ids[{index}]",
            _E_AU_CTX,
        ).h64()
        for index, value in enumerate(authorized_specifications)
    )
    attested_execution_specification_id = _stage2e_type(
        executor_attestation.execution_specification_id,
        str,
        _E_AU_CTX,
        "executor_attestation.execution_specification_id",
    )
    if (
        len(set(checked_authorized_specifications)) != 4
        or attested_execution_specification_id not in checked_authorized_specifications
    ):
        _d2_fail(
            _E_AU_CTX,
            "executor_attestation.execution_specification_id",
            "specification is absent from the exact authority plan set",
        )

    # 3n.2: compare the already-sealed Layer-0 executor implementation occurrence.
    expected_executor_implementation_mapping = _stage2e_projection_mapping(
        expected_executor_implementation,
        ExecutorImplementationProjection,
        _E_EI_CTX,
        "expected_executor_implementation",
    )
    decoded_expected_executor_implementation = _ExecutionEvidenceDecoder(
        expected_executor_implementation_mapping,
        "expected_executor_implementation",
        _E_EI_CTX,
    ).executor_implementation()
    expected_executor_implementation_identity = _stage2e_type(
        expected_executor_implementation_identity,
        str,
        _E_EI_CTX,
        "expected_executor_implementation_identity",
    )
    recomputed_executor_implementation_identity = protocol_hash(
        "validation_evidence_executor_implementation/v1",
        expected_executor_implementation_mapping,
    )
    attested_executor_implementation_mapping = _stage2e_projection_mapping(
        executor_attestation.executor_implementation,
        ExecutorImplementationProjection,
        _E_EI_CTX,
        "executor_attestation.executor_implementation",
    )
    decoded_attested_executor_implementation = _ExecutionEvidenceDecoder(
        attested_executor_implementation_mapping,
        "executor_attestation.executor_implementation",
        _E_EI_CTX,
    ).executor_implementation()
    attested_executor_implementation_identity = _stage2e_type(
        executor_attestation.executor_implementation_identity,
        str,
        _E_EI_CTX,
        "executor_attestation.executor_implementation_identity",
    )
    expected_execution_specification = _stage2e_type(
        expected_execution_specification,
        ExecutionSpecificationProjection,
        _E_EI_CTX,
        "expected_execution_specification",
    )
    specification_executor_implementation_mapping = _stage2e_projection_mapping(
        expected_execution_specification.executor_implementation,
        ExecutorImplementationProjection,
        _E_EI_CTX,
        "expected_execution_specification.executor_implementation",
    )
    specification_executor_implementation_identity = _stage2e_type(
        expected_execution_specification.executor_implementation_identity,
        str,
        _E_EI_CTX,
        "expected_execution_specification.executor_implementation_identity",
    )
    if (
        expected_executor_implementation_identity != recomputed_executor_implementation_identity
        or attested_executor_implementation_mapping != expected_executor_implementation_mapping
        or decoded_attested_executor_implementation != decoded_expected_executor_implementation
        or attested_executor_implementation_identity != recomputed_executor_implementation_identity
        or specification_executor_implementation_mapping != expected_executor_implementation_mapping
        or specification_executor_implementation_identity
        != recomputed_executor_implementation_identity
    ):
        _d2_fail(
            _E_EI_CTX,
            "executor_attestation.executor_implementation",
            "sealed executor implementation projection or identity differs",
        )

    # 3n.3: bind the execution, instance, role, and accepted specification.
    expected_execution_specification_mapping = _stage2e_projection_mapping(
        expected_execution_specification,
        ExecutionSpecificationProjection,
        _E_SR_CTX,
        "expected_execution_specification",
    )
    recomputed_execution_specification_id = protocol_hash(
        "validation_evidence_execution_specification/v1",
        expected_execution_specification_mapping,
    )
    (
        attested_execution_id,
        attested_execution_instance_identity,
        attested_execution_specification_id,
        attested_role,
    ) = _stage2e_strings(
        _E_SR_CTX,
        "executor_attestation",
        ("execution_id", executor_attestation.execution_id),
        ("execution_instance_identity", executor_attestation.execution_instance_identity),
        ("execution_specification_id", executor_attestation.execution_specification_id),
        ("role", executor_attestation.role),
    )
    if (
        attested_execution_id != carried_execution_id
        or attested_execution_instance_identity != carried_execution_instance_identity
        or attested_execution_specification_id != recomputed_execution_specification_id
        or execution.execution_specification_id != recomputed_execution_specification_id
        or execution.execution_specification_id != expected_execution.execution_specification_id
        or attested_role != execution.role
        or execution.role != expected_execution_specification.role
    ):
        _d2_fail(
            _E_SR_CTX,
            "executor_attestation.execution_specification_id",
            "execution, instance, role, or specification relation differs",
        )

    # 3n.4: reconstruct the exact configuration and its identity.
    configuration = expected_execution_specification.configuration
    configuration_mapping = _stage2e_projection_mapping(
        configuration,
        ExecutorConfigurationProjection,
        _E_SR_CTX,
        "expected_execution_specification.configuration",
    )
    expected_configuration_mapping: dict[str, object] = {
        "callable_identity": expected_execution_specification.callable_identity,
        "executor_kind": expected_execution_specification.executor_kind,
        "result_delivery_mode": expected_execution_specification.result_delivery_mode,
        "scheduling_mode": expected_execution_specification.scheduling_mode,
        "schema_version": "broader-replication-executor-configuration/v1",
        "timeout_ms": expected_execution_specification.timeout_ms,
        "worker_count": expected_execution_specification.worker_count,
    }
    recomputed_configuration_sha256 = protocol_hash(
        "validation_evidence_executor_configuration/v1",
        expected_configuration_mapping,
    )
    (
        attested_configuration_sha256,
        attested_executor_kind,
        attested_result_delivery_mode,
        attested_scheduling_mode,
    ) = _stage2e_strings(
        _E_SR_CTX,
        "executor_attestation",
        ("configuration_sha256", executor_attestation.configuration_sha256),
        ("executor_kind", executor_attestation.executor_kind),
        ("result_delivery_mode", executor_attestation.result_delivery_mode),
        ("scheduling_mode", executor_attestation.scheduling_mode),
    )
    attested_configured_worker_count = _stage2e_type(
        executor_attestation.configured_worker_count,
        int,
        _E_SR_CTX,
        "executor_attestation.configured_worker_count",
    )
    if (
        configuration_mapping != expected_configuration_mapping
        or expected_execution_specification.configuration_sha256 != recomputed_configuration_sha256
        or submitted_jobs.configuration_sha256 != recomputed_configuration_sha256
        or attested_configuration_sha256 != recomputed_configuration_sha256
        or attested_executor_kind != expected_execution_specification.executor_kind
        or attested_result_delivery_mode != expected_execution_specification.result_delivery_mode
        or attested_scheduling_mode != expected_execution_specification.scheduling_mode
        or attested_configured_worker_count != expected_execution_specification.worker_count
    ):
        _d2_fail(
            _E_SR_CTX,
            "executor_attestation.configuration_sha256",
            "configuration projection, identity, or direct occurrence differs",
        )

    # 3n.5: compare the literal namespace derivation.
    (
        attested_study_id,
        attested_trust_domain,
        attested_execution_purpose,
        attested_normalized_execution_namespace,
    ) = _stage2e_strings(
        _E_NS_CTX,
        "executor_attestation",
        ("study_id", executor_attestation.study_id),
        ("trust_domain", executor_attestation.trust_domain),
        ("execution_purpose", executor_attestation.execution_purpose),
        (
            "normalized_execution_namespace",
            executor_attestation.normalized_execution_namespace,
        ),
    )
    expected_namespace = (
        f"{expected_execution_specification.study_id}/"
        f"{expected_execution_specification.trust_domain}/"
        f"{expected_execution_specification.execution_purpose}"
    )
    attested_namespace = f"{attested_study_id}/{attested_trust_domain}/{attested_execution_purpose}"
    if (
        expected_execution_specification.normalized_execution_namespace != expected_namespace
        or attested_normalized_execution_namespace != attested_namespace
        or attested_namespace != expected_namespace
        or attested_study_id != expected_execution_specification.study_id
        or attested_trust_domain != expected_execution_specification.trust_domain
        or attested_execution_purpose != expected_execution_specification.execution_purpose
    ):
        _d2_fail(
            _E_NS_CTX,
            "executor_attestation.normalized_execution_namespace",
            "normalized execution namespace differs",
        )

    # 3n.6: bind the exact start occurrence and timestamp.
    attested_execution_start_id, attested_started_at = _stage2e_strings(
        _D2_ST_CTX,
        "executor_attestation",
        ("execution_start_id", executor_attestation.execution_start_id),
        ("started_at", executor_attestation.started_at),
    )
    if (
        attested_execution_start_id != carried_execution_start_id
        or attested_started_at != execution_start.started_at
    ):
        _d2_fail(
            _D2_ST_CTX,
            "executor_attestation.execution_start_id",
            "execution-start projection or identity occurrence differs",
        )

    # 3n.7: bind submitted jobs and the independently observed acceptance order.
    if type(accepted_job_ids_in_actual_acceptance_order) is not tuple:
        _d2_fail(_D2_SJ_CTX, "accepted_job_ids", "acceptance order must be an exact tuple")
    checked_accepted_job_ids = tuple(
        _ExecutionEvidenceDecoder(
            value,
            f"accepted_job_ids[{index}]",
            _D2_SJ_CTX,
        ).h64()
        for index, value in enumerate(accepted_job_ids_in_actual_acceptance_order)
    )
    attested_submitted_jobs_mapping = _stage2e_projection_mapping(
        executor_attestation.submitted_jobs,
        SubmittedJobsProjection,
        _D2_SJ_CTX,
        "executor_attestation.submitted_jobs",
    )
    decoded_attested_submitted_jobs = decode_submitted_jobs_projection(
        attested_submitted_jobs_mapping
    )
    expected_submitted_jobs_mapping = _stage2e_projection_mapping(
        submitted_jobs,
        SubmittedJobsProjection,
        _D2_SJ_CTX,
        "submitted_jobs",
    )
    attested_submitted_jobs_sha256 = _stage2e_type(
        executor_attestation.submitted_jobs_sha256,
        str,
        _D2_SJ_CTX,
        "executor_attestation.submitted_jobs_sha256",
    )
    attested_accepted_job_ids = tuple(
        _stage2e_string_sequence(
            executor_attestation.accepted_job_ids,
            _D2_SJ_CTX,
            "executor_attestation.accepted_job_ids",
        )
    )
    submitted_job_ids = tuple(job.submitted_job_id for job in submitted_jobs.jobs)
    if (
        attested_submitted_jobs_mapping != expected_submitted_jobs_mapping
        or decoded_attested_submitted_jobs != submitted_jobs
        or attested_submitted_jobs_sha256 != carried_submitted_jobs_sha256
        or attested_accepted_job_ids != checked_accepted_job_ids
        or len(checked_accepted_job_ids) != len(submitted_job_ids)
        or len(set(checked_accepted_job_ids)) != len(checked_accepted_job_ids)
        or set(checked_accepted_job_ids) != set(submitted_job_ids)
    ):
        _d2_fail(
            _D2_SJ_CTX,
            "executor_attestation.accepted_job_ids",
            "submitted-jobs occurrence, identity, or acceptance permutation differs",
        )

    # 3n.8: bind returned-result payload occurrences in actual delivery order.
    expected_delivery_payload_hashes = tuple(
        observation[0].result_payload_sha256 for observation in accepted_observations
    )
    attested_mapping = executor_attestation.job_result_mapping
    attested_returned_result_ids: tuple[str, ...] | None = None
    if type(attested_mapping) is tuple:
        checked_result_ids: list[str] = []
        mapping_shape_is_exact = True
        for index in range(len(attested_mapping)):
            row = attested_mapping[index]
            if (
                type(row) is not tuple
                or len(row) != 2
                or type(row[0]) is not str
                or type(row[1]) is not str
            ):
                mapping_shape_is_exact = False
                break
            checked_result_ids.append(row[1])
        if mapping_shape_is_exact:
            attested_returned_result_ids = tuple(checked_result_ids)
    attested_delivery_payload_hashes = tuple(
        _stage2e_string_sequence(
            executor_attestation.result_payload_sha256_in_delivery_order,
            _D2_RO_CTX,
            "executor_attestation.result_payload_sha256_in_delivery_order",
        )
    )
    expected_returned_result_ids = tuple(observation[1] for observation in accepted_observations)
    if (
        attested_delivery_payload_hashes != expected_delivery_payload_hashes
        or attested_returned_result_ids is not None
        and (
            len(attested_returned_result_ids) != len(expected_returned_result_ids)
            or len(set(attested_returned_result_ids)) != len(attested_returned_result_ids)
            or set(attested_returned_result_ids) != set(expected_returned_result_ids)
        )
    ):
        _d2_fail(
            _D2_RO_CTX,
            "executor_attestation.result_payload_sha256_in_delivery_order",
            "returned-result payload occurrence order differs",
        )

    # 3n.9: bind the submission-order bijection to accepted and returned occurrences.
    mapped_submitted_job_ids = tuple(row[0] for row in expected_mapping)
    mapped_returned_result_ids = tuple(row[1] for row in expected_mapping)
    observed_returned_result_ids = tuple(row[1] for row in accepted_observations)
    attested_mapping_plain = _stage2e_job_result_mapping(
        executor_attestation.job_result_mapping,
        _D2_M_CTX,
        "executor_attestation.job_result_mapping",
    )
    decoded_attested_mapping = _ExecutionEvidenceDecoder(
        attested_mapping_plain,
        "executor_attestation.job_result_mapping",
        _D2_M_CTX,
    ).mapping()
    if (
        decoded_attested_mapping != expected_mapping
        or set(mapped_submitted_job_ids) != set(checked_accepted_job_ids)
        or len(set(mapped_submitted_job_ids)) != len(mapped_submitted_job_ids)
        or set(mapped_returned_result_ids) != set(observed_returned_result_ids)
        or len(set(mapped_returned_result_ids)) != len(mapped_returned_result_ids)
    ):
        _d2_fail(
            _D2_M_CTX,
            "executor_attestation.job_result_mapping",
            "accepted-job and returned-result bijection differs",
        )

    # 3n.10: bind the result batch and its delivery payload order.
    attested_result_batch_id = _stage2e_type(
        executor_attestation.result_batch_id,
        str,
        _D2_B_CTX,
        "executor_attestation.result_batch_id",
    )
    if (
        attested_result_batch_id != carried_result_batch_id
        or attested_delivery_payload_hashes != result_batch.result_payload_sha256_in_delivery_order
    ):
        _d2_fail(
            _D2_B_CTX,
            "executor_attestation.result_batch_id",
            "result-batch occurrence or delivery payload order differs",
        )

    # 3n.11: bind completion, success, and both timestamps.
    attested_execution_completion_id, attested_completed_at = _stage2e_strings(
        _D2_C_CTX,
        "executor_attestation",
        ("execution_completion_id", executor_attestation.execution_completion_id),
        ("completed_at", executor_attestation.completed_at),
    )
    if (
        attested_execution_completion_id != carried_execution_completion_id
        or execution_completion.execution_status != "success"
        or attested_started_at != execution_start.started_at
        or attested_completed_at != execution_completion.completed_at
    ):
        _d2_fail(
            _D2_C_CTX,
            "executor_attestation.execution_completion_id",
            "completion occurrence, success, or timestamp differs",
        )

    # 3n.12: bind the complete submission-order returned-results aggregate.
    attested_returned_results_mapping = _stage2e_projection_mapping(
        executor_attestation.returned_results,
        ReturnedResultsProjection,
        _D2_RA_CTX,
        "executor_attestation.returned_results",
    )
    decoded_attested_returned_results = decode_returned_results_projection(
        attested_returned_results_mapping
    )
    expected_returned_results_mapping = _stage2e_projection_mapping(
        returned_results,
        ReturnedResultsProjection,
        _D2_RA_CTX,
        "returned_results",
    )
    attested_returned_results_sha256 = _stage2e_type(
        executor_attestation.returned_results_sha256,
        str,
        _D2_RA_CTX,
        "executor_attestation.returned_results_sha256",
    )
    if (
        attested_returned_results_mapping != expected_returned_results_mapping
        or _stage2e_projection_mapping(
            decoded_attested_returned_results,
            ReturnedResultsProjection,
            _D2_RA_CTX,
            "executor_attestation.returned_results",
        )
        != attested_returned_results_mapping
        or attested_returned_results_sha256 != carried_returned_results_sha256
    ):
        _d2_fail(
            _D2_RA_CTX,
            "executor_attestation.returned_results",
            "returned-results projection or identity differs",
        )

    # 3n.13: bind worker order, hashes, counts, and unique worker occurrences.
    expected_observed_worker_ids: list[str] = []
    for _worker, worker_id_value in workers_in_actual_delivery_order:
        if worker_id_value not in expected_observed_worker_ids:
            expected_observed_worker_ids.append(worker_id_value)
    attested_worker_result_order_mapping = _stage2e_projection_mapping(
        executor_attestation.worker_result_order,
        WorkerResultOrderProjection,
        _D2_WO_CTX,
        "executor_attestation.worker_result_order",
    )
    decoded_attested_worker_result_order = decode_worker_result_order_projection(
        attested_worker_result_order_mapping
    )
    expected_worker_result_order_mapping = _stage2e_projection_mapping(
        worker_result_order,
        WorkerResultOrderProjection,
        _D2_WO_CTX,
        "worker_result_order",
    )
    attested_worker_result_order_sha256 = _stage2e_type(
        executor_attestation.worker_result_order_sha256,
        str,
        _D2_WO_CTX,
        "executor_attestation.worker_result_order_sha256",
    )
    attested_observed_worker_ids = tuple(
        _stage2e_string_sequence(
            executor_attestation.observed_worker_ids,
            _D2_WO_CTX,
            "executor_attestation.observed_worker_ids",
        )
    )
    attested_actual_worker_count = _stage2e_type(
        executor_attestation.actual_worker_count,
        int,
        _D2_WO_CTX,
        "executor_attestation.actual_worker_count",
    )
    if (
        attested_worker_result_order_mapping != expected_worker_result_order_mapping
        or _stage2e_projection_mapping(
            decoded_attested_worker_result_order,
            WorkerResultOrderProjection,
            _D2_WO_CTX,
            "executor_attestation.worker_result_order",
        )
        != attested_worker_result_order_mapping
        or attested_worker_result_order_sha256 != carried_worker_result_order_sha256
        or attested_observed_worker_ids != tuple(expected_observed_worker_ids)
        or attested_observed_worker_ids != execution_completion.observed_worker_ids
        or attested_actual_worker_count != len(expected_observed_worker_ids)
        or attested_configured_worker_count != expected_execution_specification.worker_count
    ):
        _d2_fail(
            _D2_WO_CTX,
            "executor_attestation.worker_result_order",
            "worker-order projection, identity, count, or occurrence differs",
        )

    # 3n.14: recompute only the carried nested runtime pair.
    runtime_mapping = _stage2e_projection_mapping(
        executor_attestation.runtime,
        RuntimeProjection,
        _E_RT_CTX,
        "executor_attestation.runtime",
    )
    decoded_runtime = _ExecutionEvidenceDecoder(
        runtime_mapping,
        "executor_attestation.runtime",
        _E_RT_CTX,
    ).runtime()
    if (
        _stage2e_projection_mapping(
            decoded_runtime,
            RuntimeProjection,
            _E_RT_CTX,
            "executor_attestation.runtime",
        )
        != runtime_mapping
    ):
        _d2_fail(
            _E_RT_CTX,
            "executor_attestation.runtime",
            "nested runtime projection does not exactly reconstruct",
        )
    recomputed_runtime_identity = protocol_hash(
        "validation_evidence_runtime/v1",
        runtime_mapping,
    )
    attested_runtime_identity = _stage2e_type(
        executor_attestation.runtime_identity,
        str,
        _E_RT_CTX,
        "executor_attestation.runtime_identity",
    )
    if attested_runtime_identity != recomputed_runtime_identity:
        _d2_fail(
            _E_RT_CTX,
            "executor_attestation.runtime_identity",
            "nested runtime identity differs",
        )

    # 3n.15: validate local literals, reconstruct every field, and accept one identity.
    attested_execution_status, attested_schema_version = _stage2e_strings(
        _E_ID_CTX,
        "executor_attestation",
        ("execution_status", executor_attestation.execution_status),
        ("schema_version", executor_attestation.schema_version),
    )
    _stage2e_type(
        executor_attestation.implementation,
        ImplementationProjection,
        _E_ID_CTX,
        "executor_attestation.implementation",
    )
    if (
        attested_execution_status != "success"
        or attested_schema_version != "broader-replication-executor-attestation/v1"
    ):
        _d2_fail(
            _E_ID_CTX,
            "executor_attestation",
            "local execution status or schema version differs",
        )
    attestation_mapping = _stage2e_projection_mapping(
        executor_attestation,
        ExecutorAttestationProjection,
        _E_ID_CTX,
        "executor_attestation",
    )
    decoded_attestation = decode_executor_attestation_projection(attestation_mapping)
    if (
        _stage2e_projection_mapping(
            decoded_attestation,
            ExecutorAttestationProjection,
            _E_ID_CTX,
            "executor_attestation",
        )
        != attestation_mapping
    ):
        _d2_fail(
            _E_ID_CTX,
            "executor_attestation",
            "complete projection does not exactly reconstruct",
        )
    checked_attestation_id = _ExecutionEvidenceDecoder(
        carried_executor_attestation_id,
        "executor_attestation_id",
        _E_ID_CTX,
    ).h64()
    if executor_attestation_id(decoded_attestation) != checked_attestation_id:
        _d2_fail(_E_ID_CTX, "executor_attestation_id", "identity differs")
    return decoded_attestation


def _error(error_code: str, message: str, *, layer: str = "executor_attestation") -> NoReturn:
    raise ExecutorProvenanceError(
        message,
        error_code=error_code,
        validation_layer=layer,
    )


def _install_stage1_executor_implementation_authority(
    production_registry_issue: Callable[
        [
            ExecutorImplementationProjection,
            str,
            object | None,
            Callable[[object], None] | None,
        ],
        object,
    ] = _issue_production_executor_implementation_record,
    fixture_registry_issue: Callable[
        [
            ExecutorImplementationProjection,
            str,
            object | None,
            Callable[[object], None] | None,
        ],
        object,
    ] = _issue_fixture_executor_implementation_record,
) -> tuple[
    Callable[[], tuple[CallableProjection, str]],
    Callable[
        [
            _ProductionPreparationCapability,
            Layer0Context,
            ValidationRun,
            Callable[[type[object]], object],
            Callable[[object], None],
        ],
        ExecutorImplementationIdentity,
    ],
    Callable[
        [Layer0Context, _FixtureValidationRun],
        _FixtureExecutorImplementationIdentity,
    ],
]:
    """Capture the exact executor only after its complete implementation exists."""

    trusted_module = sys.modules[__name__]
    trusted_module_globals = trusted_module.__dict__
    trusted_function = execute_deterministic_map
    trusted_code = trusted_function.__code__
    project_callable = callable_projection
    resolve_callable_source = _resolved_callable_source
    sha256 = hashlib.sha256
    expected_source = (
        repository_root() / "research_decision_engine" / "benchmarks" / "broader_execution.py"
    ).resolve(strict=True)
    trusted_source = expected_source.read_bytes()
    trusted_source_sha256 = sha256(trusted_source).hexdigest()
    trusted_projection, trusted_identity = project_callable(trusted_function)
    if (
        trusted_function.__globals__ is not trusted_module_globals
        or Path(trusted_code.co_filename).resolve(strict=True) != expected_source
        or trusted_projection.source.path != str(expected_source)
        or trusted_projection.source.byte_count != len(trusted_source)
        or trusted_projection.source.sha256 != trusted_source_sha256
    ):
        raise RuntimeError("Executor callable source is not the trusted broader_execution.py file.")

    def require_trusted_executor_callable() -> tuple[CallableProjection, str]:
        current = trusted_module.__dict__.get("execute_deterministic_map")
        if (
            current is not trusted_function
            or type(current) is not FunctionType
            or current.__code__ is not trusted_code
            or current.__globals__ is not trusted_module_globals
            or current.__module__ != __name__
            or current.__qualname__ != "execute_deterministic_map"
            or resolve_callable_source(current, label="execute_deterministic_map")
            != expected_source
        ):
            raise P2Stage1Error(
                "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                "The live executor callable is not the exact captured production implementation.",
                layer="live_executor_implementation_issuance",
            )
        try:
            current_source = expected_source.read_bytes()
        except OSError as error:
            raise P2Stage1Error(
                "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                "The trusted executor source bytes are no longer readable.",
                layer="live_executor_implementation_issuance",
            ) from error
        current_projection, current_identity = project_callable(current)
        if (
            current_source != trusted_source
            or sha256(current_source).hexdigest() != trusted_source_sha256
            or current_projection != trusted_projection
            or current_identity != trusted_identity
        ):
            raise P2Stage1Error(
                "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                "Executor callable code or source bytes changed after trusted capture.",
                layer="live_executor_implementation_issuance",
            )
        return trusted_projection, trusted_identity

    require_production_preparation = _require_production_preparation
    production_run_id = _production_validation_run_id
    fixture_run_id = _fixture_validation_run_id
    validate_context = _validate_execution_specification_context
    implementation_projection_type = ExecutorImplementationProjection
    production_capability_type = ExecutorImplementationIdentity
    fixture_capability_type = _FixtureExecutorImplementationIdentity
    invalidate_production = _invalidate_production_executor_implementation
    production_is_current = _production_executor_implementation_is_current

    def issue_production_executor_implementation(
        preparation: _ProductionPreparationCapability,
        context: Layer0Context,
        validation_run: ValidationRun,
        allocate_implementation: Callable[[type[object]], object],
        confirm_implementation: Callable[[object], None] | None = None,
    ) -> ExecutorImplementationIdentity:
        require_production_preparation(preparation, validation_run=validation_run)
        validate_context(context, trust_domain="production")
        executor_callable, callable_identity = require_trusted_executor_callable()
        projection = implementation_projection_type(
            callable=executor_callable,
            callable_identity=callable_identity,
            implementation_tree_sha256=context.implementation.implementation_tree_sha256,
        )
        capability: ExecutorImplementationIdentity | None = None
        try:
            allocated = allocate_implementation(production_capability_type)
            if type(allocated) is not production_capability_type:
                raise P2Stage1Error(
                    "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                    "Central executor allocation crossed capability domains.",
                    layer="live_executor_implementation_issuance",
                )
            capability = allocated
            candidate = production_registry_issue(
                projection,
                production_run_id(validation_run),
                capability,
                confirm_implementation,
            )
            if type(candidate) is not production_capability_type:
                raise AssertionError("Production executor registry crossed capability domains.")
            if candidate is not capability:
                raise P2Stage1Error(
                    "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                    "Executor registry changed the centrally allocated capability.",
                    layer="live_executor_implementation_issuance",
                )
            if not production_is_current(capability):
                raise P2Stage1Error(
                    "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                    "Production executor ownership transfer made the capability stale.",
                    layer="live_executor_implementation_issuance",
                )
        except BaseException as transfer_error:
            if capability is not None:
                cleanup_error: BaseException | None = None
                for _ in range(3):
                    try:
                        invalidate_production(capability)
                        if production_is_current(capability):
                            raise P2Stage1Error(
                                "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
                                "Failed executor ownership transfer left a current capability.",
                                layer="live_executor_implementation_issuance",
                            )
                    except BaseException as error:
                        cleanup_error = error
                    else:
                        cleanup_error = None
                        break
                if cleanup_error is not None:
                    transfer_error.add_note(
                        "Executor ownership-transfer rollback also failed: "
                        f"{type(cleanup_error).__name__}: {cleanup_error}"
                    )
            raise
        if capability is None:
            raise AssertionError("Production executor issuance returned no capability.")
        return capability

    def issue_fixture_executor_implementation(
        context: Layer0Context,
        validation_run: _FixtureValidationRun,
    ) -> _FixtureExecutorImplementationIdentity:
        validate_context(context, trust_domain="fixture")
        executor_callable, callable_identity = require_trusted_executor_callable()
        projection = implementation_projection_type(
            callable=executor_callable,
            callable_identity=callable_identity,
            implementation_tree_sha256=context.implementation.implementation_tree_sha256,
        )
        capability = fixture_registry_issue(
            projection,
            fixture_run_id(validation_run),
            None,
            None,
        )
        if type(capability) is not fixture_capability_type:
            raise AssertionError("Fixture executor registry crossed capability domains.")
        return capability

    return (
        require_trusted_executor_callable,
        cast(
            Callable[
                [
                    _ProductionPreparationCapability,
                    Layer0Context,
                    ValidationRun,
                    Callable[[type[object]], object],
                    Callable[[object], None],
                ],
                ExecutorImplementationIdentity,
            ],
            _seal_production_component_callable(
                "executor_implementation",
                issue_production_executor_implementation,
            ),
        ),
        issue_fixture_executor_implementation,
    )


def _install_production_execution_plan_issuer(
    require_trusted_executor_callable: Callable[[], tuple[CallableProjection, str]],
) -> Callable[
    [
        _ProductionPreparationCapability,
        Layer0Context,
        ValidationRun,
        ExecutorImplementationIdentity,
    ],
    tuple[_PlanDraft, _PlanDraft, _PlanDraft, _PlanDraft],
]:
    """Close production plan issuance over immutable builders and central authority checks."""

    require_preparation = _require_production_preparation
    production_run_id = _production_validation_run_id
    validate_context = _validate_execution_specification_context
    require_implementation = _require_production_executor_implementation_record
    resolve_job_callable = _verified_job_callable_projection
    canonical_job_builder = _canonical_production_submitted_jobs
    assemble_projection = _assemble_execution_specification_projection
    validate_projection = _execution_specification_id_from_projection
    draft_type = _PlanDraft
    specification_type = ExecutionSpecification
    roles = _P2_EXECUTION_ROLE_ORDER
    configurations = _P2_EXECUTION_CONFIGURATIONS
    smoke_world_ids = _P2_SMOKE_WORLD_IDS
    smoke_seeds = _P2_SMOKE_SEEDS
    budgets = _P2_BUDGETS
    arms = _P2_ARMS
    fixture_world_seeds = _P2_FIXTURE_WORLD_SEEDS
    allocate_plan = _allocate_production_plan_capability
    record_plan = _record_production_plan_draft

    def build_jobs(role: P2ExecutionRole) -> tuple[SubmittedJobProjection, ...]:
        return canonical_job_builder(
            role,
            configurations=configurations,
            smoke_world_ids=smoke_world_ids,
            smoke_seeds=smoke_seeds,
            budgets=budgets,
            arms=arms,
            fixture_world_seeds=fixture_world_seeds,
        )

    def issue_production_execution_plan_drafts(
        preparation: _ProductionPreparationCapability,
        context: Layer0Context,
        validation_run: ValidationRun,
        executor_implementation: ExecutorImplementationIdentity,
    ) -> tuple[_PlanDraft, _PlanDraft, _PlanDraft, _PlanDraft]:
        require_preparation(preparation, validation_run=validation_run)
        validate_context(context, trust_domain="production")
        run_id = production_run_id(validation_run)
        implementation_record = require_implementation(executor_implementation, run_id)
        trusted_callable, trusted_identity = require_trusted_executor_callable()
        drafts: list[_PlanDraft] = []
        for role in roles:
            job_callable, job_callable_identity = resolve_job_callable(role)
            projection = assemble_projection(
                context=context,
                run_id=run_id,
                implementation_record=implementation_record,
                job_callable=job_callable,
                job_callable_identity=job_callable_identity,
                submitted_jobs=build_jobs(role),
                role=role,
                configurations=configurations,
            )
            persistent_id = validate_projection(
                projection,
                trusted_executor_callable=trusted_callable,
                trusted_executor_callable_identity=trusted_identity,
                configurations=configurations,
                job_callable_resolver=resolve_job_callable,
                job_builder=build_jobs,
            )
            capability = allocate_plan(
                preparation,
                validation_run,
                capability_type=specification_type,
                kind="execution_specification",
                role=role,
                persistent_id=persistent_id,
            )
            draft = draft_type(
                capability=capability,
                kind="execution_specification",
                role=role,
                persistent_id=persistent_id,
                validation_run=validation_run,
                validation_run_id=run_id,
                projection=projection,
            )
            record_plan(preparation, validation_run, draft)
            drafts.append(draft)
        return (drafts[0], drafts[1], drafts[2], drafts[3])

    return cast(
        Callable[
            [
                _ProductionPreparationCapability,
                Layer0Context,
                ValidationRun,
                ExecutorImplementationIdentity,
            ],
            tuple[_PlanDraft, _PlanDraft, _PlanDraft, _PlanDraft],
        ],
        _seal_production_component_callable(
            "execution_plans",
            issue_production_execution_plan_drafts,
        ),
    )


(
    _require_trusted_executor_callable,
    _issue_production_executor_implementation,
    _issue_fixture_executor_implementation,
) = _install_stage1_executor_implementation_authority()
_issue_production_execution_plan_drafts = _install_production_execution_plan_issuer(
    _require_trusted_executor_callable
)
del _issue_production_executor_implementation_record
del _issue_fixture_executor_implementation_record
del _install_stage1_executor_implementation_authority
del _install_production_execution_plan_issuer
