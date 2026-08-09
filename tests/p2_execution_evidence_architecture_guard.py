"""Test-owned Stage-2E architecture boundary for execution evidence."""

from __future__ import annotations

import ast
import hashlib
from collections import Counter
from typing import Final, Literal, NamedTuple

from tests import p2_returned_run_architecture_guard as alias_guard

type ExecutionEvidencePhase = Literal["G", "2D.2A", "2D.2B", "2D.2C1", "2D.2C2", "2E"]

_MODULE: Final = "research_decision_engine.benchmarks.broader_execution"
_LEGACY_AST_SHA256: Final = "e7c7263f8008a349789fbb629684dc94305a988ec37b0878a493b76bfc1b2c29"
_EVIDENCE_MODULE: Final = "research_decision_engine.benchmarks.broader_validation_evidence"
_RETURNED_MODULE: Final = "research_decision_engine.benchmarks.broader_returned_run"
_RUNNER_MODULE: Final = "research_decision_engine.benchmarks.broader_runner"


def _words(text: str) -> tuple[str, ...]:
    return tuple(text.split())


class ExecutionEvidenceImport(NamedTuple):
    """One exact top-level import occurrence."""

    module: str | None
    name: str
    asname: str | None = None
    level: int = 0


class ExecutionEvidenceManifest(NamedTuple):
    """Exact test authority added by one cumulative Stage-2D.2 phase."""

    phase: ExecutionEvidencePhase
    added_classes: frozenset[str]
    projection_classes: frozenset[str]
    added_functions: frozenset[str]
    added_assignments: frozenset[str]
    added_annassigns: frozenset[str]
    added_type_aliases: frozenset[str]
    added_import_occurrences: tuple[ExecutionEvidenceImport, ...]
    decoder_functions: frozenset[str]
    reader_methods: frozenset[str]
    identity_domains: tuple[tuple[str, str], ...]
    auxiliary_hashes: tuple[tuple[tuple[str, ...], str], ...]
    resolved_added_imports_sha256: str
    sensitive_unresolved_sha256: str
    legacy_ast_sha256: str


PHASE_G_MANIFEST: Final = ExecutionEvidenceManifest(
    phase="G",
    added_classes=frozenset(),
    projection_classes=frozenset(),
    added_functions=frozenset(),
    added_assignments=frozenset(),
    added_annassigns=frozenset(),
    added_type_aliases=frozenset(),
    added_import_occurrences=(),
    decoder_functions=frozenset(),
    reader_methods=frozenset(),
    identity_domains=(),
    auxiliary_hashes=(),
    resolved_added_imports_sha256="2e38e77b22c314a449e91fafed92a43826ac6aa403ae6a8acb6cf58239fbaf5d",
    sensitive_unresolved_sha256="2e38e77b22c314a449e91fafed92a43826ac6aa403ae6a8acb6cf58239fbaf5d",
    legacy_ast_sha256=_LEGACY_AST_SHA256,
)
PHASE_A_MANIFEST: Final = ExecutionEvidenceManifest(
    phase="2D.2A",
    added_classes=frozenset(
        _words(
            "ExecutionIdentityProjection ExecutionInstanceProjection ExecutionStartProjection "
            "SubmittedJobsProjection WorkerIdentityProjection _ExecutionEvidenceDecoder"
        )
    ),
    projection_classes=frozenset(
        _words(
            "ExecutionIdentityProjection ExecutionInstanceProjection ExecutionStartProjection "
            "SubmittedJobsProjection WorkerIdentityProjection"
        )
    ),
    added_functions=frozenset(
        _words(
            "_d2_exact _d2_fail _d2_type decode_execution_identity_projection "
            "decode_execution_instance_projection decode_execution_start_projection "
            "decode_submitted_jobs_projection decode_worker_identity_projection execution_id "
            "execution_instance_identity execution_start_id submitted_jobs_sha256 "
            "validate_stage2d2_execution_foundations worker_identity"
        )
    ),
    added_assignments=frozenset(),
    added_annassigns=frozenset(
        _words(
            "_D2_CHECKPOINT _D2_E_CTX _D2_I_CTX _D2_RL_CTX _D2_SJ_CTX _D2_ST_CTX "
            "_D2_STUDY _D2_W_CTX"
        )
    ),
    added_type_aliases=frozenset({"_Stage2D2DecodeContext"}),
    added_import_occurrences=(
        ExecutionEvidenceImport(None, "math"),
        ExecutionEvidenceImport(None, "struct"),
        ExecutionEvidenceImport(None, "unicodedata"),
        ExecutionEvidenceImport(_EVIDENCE_MODULE, "FileProjection"),
        ExecutionEvidenceImport(_EVIDENCE_MODULE, "InterpreterIdentityProjection"),
        ExecutionEvidenceImport(_EVIDENCE_MODULE, "PlatformIdentityProjection"),
    ),
    decoder_functions=frozenset(
        _words(
            "decode_execution_identity_projection decode_execution_instance_projection "
            "decode_execution_start_projection decode_submitted_jobs_projection "
            "decode_worker_identity_projection"
        )
    ),
    reader_methods=frozenset(
        _words(
            "closed f64 fail field file git40 h64 hashes i64 identifier implementation items "
            "job literal npath runtime string timestamp u64"
        )
    ),
    identity_domains=(
        ("execution_instance_identity", "validation_evidence_execution_instance/v1"),
        ("execution_id", "validation_evidence_execution/v1"),
        ("submitted_jobs_sha256", "validation_evidence_submitted_jobs/v1"),
        ("execution_start_id", "validation_evidence_execution_start/v1"),
        ("worker_identity", "validation_evidence_worker_identity/v1"),
    ),
    auxiliary_hashes=(
        (("_ExecutionEvidenceDecoder", "runtime"), "pytest_interpreter_identity/v1"),
        (("_ExecutionEvidenceDecoder", "runtime"), "pytest_platform_identity/v1"),
        (("validate_stage2d2_execution_foundations",), "validation_evidence_runtime/v1"),
    ),
    resolved_added_imports_sha256="9986a84d9a22409020db1991fcab38f00f2d63e1b06fb4ef7240aef2b42697eb",
    sensitive_unresolved_sha256="253d1a9183da74b8ad26ed94fc957f0d8a0eeb066b9a5b5cbd1f263954cbbac2",
    legacy_ast_sha256=_LEGACY_AST_SHA256,
)
PHASE_B_MANIFEST: Final = PHASE_A_MANIFEST._replace(
    phase="2D.2B",
    added_classes=PHASE_A_MANIFEST.added_classes | frozenset({"ReturnedResultProjection"}),
    projection_classes=PHASE_A_MANIFEST.projection_classes
    | frozenset({"ReturnedResultProjection"}),
    added_functions=PHASE_A_MANIFEST.added_functions
    | frozenset(
        _words(
            "_d2_payload_job build_job_result_mapping decode_returned_result_projection "
            "returned_result_id validate_stage2d2_returned_results"
        )
    ),
    added_annassigns=PHASE_A_MANIFEST.added_annassigns
    | frozenset({"_D2_M_CTX", "_D2_RO_CTX", "_D2_RR_CTX"}),
    added_type_aliases=PHASE_A_MANIFEST.added_type_aliases
    | frozenset({"JobResultMapping", "ReturnedResultObservation"}),
    added_import_occurrences=PHASE_A_MANIFEST.added_import_occurrences
    + (
        ExecutionEvidenceImport(_RETURNED_MODULE, "ReturnedRunProjection"),
        ExecutionEvidenceImport(_RETURNED_MODULE, "ReturnedRunProjectionError"),
        ExecutionEvidenceImport(_RETURNED_MODULE, "validate_returned_run_batch"),
        ExecutionEvidenceImport(_RUNNER_MODULE, "BroaderArmRun"),
    ),
    decoder_functions=PHASE_A_MANIFEST.decoder_functions
    | frozenset({"decode_returned_result_projection"}),
    identity_domains=PHASE_A_MANIFEST.identity_domains
    + (("returned_result_id", "validation_evidence_returned_result/v1"),),
    resolved_added_imports_sha256="9ede14f98a61f754678afa33e3e9858047333e54ba9bf2aa16f21c54ef1e41a5",
    sensitive_unresolved_sha256="4599694a42c127bf72789d62f040cbe276cc8eb0a5459eca239bb7c07d0687b4",
)
PHASE_C1_MANIFEST: Final = PHASE_B_MANIFEST._replace(
    phase="2D.2C1",
    added_classes=PHASE_B_MANIFEST.added_classes
    | frozenset({"ResultBatchProjection", "ExecutionCompletionProjection"}),
    projection_classes=PHASE_B_MANIFEST.projection_classes
    | frozenset({"ResultBatchProjection", "ExecutionCompletionProjection"}),
    added_functions=PHASE_B_MANIFEST.added_functions
    | frozenset(
        _words(
            "decode_result_batch_projection decode_execution_completion_projection "
            "result_batch_id execution_completion_id "
            "validate_stage2d2_result_batch_completion"
        )
    ),
    added_annassigns=PHASE_B_MANIFEST.added_annassigns | frozenset({"_D2_B_CTX", "_D2_C_CTX"}),
    decoder_functions=PHASE_B_MANIFEST.decoder_functions
    | frozenset({"decode_result_batch_projection", "decode_execution_completion_projection"}),
    reader_methods=PHASE_B_MANIFEST.reader_methods | frozenset({"h64s", "mapping"}),
    identity_domains=PHASE_B_MANIFEST.identity_domains
    + (
        ("result_batch_id", "validation_evidence_result_batch/v1"),
        ("execution_completion_id", "validation_evidence_execution_completion/v1"),
    ),
    resolved_added_imports_sha256="98bc63c167cb6a000d3ca1767ed40132731b20eac8519be08123b1d83166962b",
    sensitive_unresolved_sha256="e9b19645ff55ed35c28b6b587d6e918354c72d83b790228c1b00ae5eb1d03e5c",
)
PHASE_C2_MANIFEST: Final = PHASE_C1_MANIFEST._replace(
    phase="2D.2C2",
    added_classes=PHASE_C1_MANIFEST.added_classes
    | frozenset({"ReturnedResultsProjection", "WorkerResultOrderProjection"}),
    projection_classes=PHASE_C1_MANIFEST.projection_classes
    | frozenset({"ReturnedResultsProjection", "WorkerResultOrderProjection"}),
    added_functions=PHASE_C1_MANIFEST.added_functions
    | frozenset(
        _words(
            "decode_returned_results_projection decode_worker_result_order_projection "
            "returned_results_sha256 worker_result_order_sha256 "
            "validate_stage2d2_result_aggregates"
        )
    ),
    added_annassigns=PHASE_C1_MANIFEST.added_annassigns | frozenset({"_D2_RA_CTX", "_D2_WO_CTX"}),
    added_import_occurrences=PHASE_C1_MANIFEST.added_import_occurrences
    + (
        ExecutionEvidenceImport(_RETURNED_MODULE, "decode_returned_run_projection"),
        ExecutionEvidenceImport(_RETURNED_MODULE, "projection_as_dict"),
    ),
    decoder_functions=PHASE_C1_MANIFEST.decoder_functions
    | frozenset({"decode_returned_results_projection", "decode_worker_result_order_projection"}),
    reader_methods=PHASE_C1_MANIFEST.reader_methods | frozenset({"returned_run", "worker"}),
    identity_domains=PHASE_C1_MANIFEST.identity_domains
    + (
        ("returned_results_sha256", "validation_evidence_returned_results/v1"),
        ("worker_result_order_sha256", "validation_evidence_worker_result_order/v1"),
    ),
    resolved_added_imports_sha256="2f9e242d7e639fc17b9e3b1b0f70277aaba2f5d76379e823e9a4b671b24d3191",
    sensitive_unresolved_sha256="87b3ecc8a4bbddbd805b26805021bd6a6b1e0fc2d8f433555dc541f7535efc71",
)
PHASE_E_MANIFEST: Final = PHASE_C2_MANIFEST._replace(
    phase="2E",
    added_classes=PHASE_C2_MANIFEST.added_classes | frozenset({"ExecutorAttestationProjection"}),
    projection_classes=PHASE_C2_MANIFEST.projection_classes
    | frozenset({"ExecutorAttestationProjection"}),
    added_functions=PHASE_C2_MANIFEST.added_functions
    | frozenset(
        _words(
            "decode_executor_attestation_projection executor_attestation_id "
            "validate_stage2e_executor_attestation _stage2e_type _stage2e_strings "
            "_stage2e_string_sequence _stage2e_job_result_mapping "
            "_stage2e_submitted_job_sequence _stage2e_projection_children "
            "_stage2e_projection_shape _stage2e_plain_value _stage2e_projection_mapping"
        )
    ),
    added_annassigns=PHASE_C2_MANIFEST.added_annassigns
    | frozenset(_words("_E_AU_CTX _E_EI_CTX _E_SR_CTX _E_NS_CTX _E_RT_CTX _E_ID_CTX")),
    added_import_occurrences=PHASE_C2_MANIFEST.added_import_occurrences
    + (
        ExecutionEvidenceImport(_EVIDENCE_MODULE, "ValidationAuthorityProjection"),
        ExecutionEvidenceImport(
            _RETURNED_MODULE,
            "validate_returned_run_projection_shape",
        ),
    ),
    decoder_functions=PHASE_C2_MANIFEST.decoder_functions
    | frozenset({"decode_executor_attestation_projection"}),
    reader_methods=PHASE_C2_MANIFEST.reader_methods
    | frozenset(
        _words(
            "callable_projection executor_implementation returned_results_projection "
            "submitted_jobs_projection worker_result_order_projection"
        )
    ),
    identity_domains=PHASE_C2_MANIFEST.identity_domains
    + (
        (
            "executor_attestation_id",
            "validation_evidence_executor_attestation/v1",
        ),
    ),
    auxiliary_hashes=PHASE_C2_MANIFEST.auxiliary_hashes
    + (
        (
            ("validate_stage2e_executor_attestation",),
            "validation_evidence_executor_implementation/v1",
        ),
        (
            ("validate_stage2e_executor_attestation",),
            "validation_evidence_execution_specification/v1",
        ),
        (
            ("validate_stage2e_executor_attestation",),
            "validation_evidence_executor_configuration/v1",
        ),
        (
            ("validate_stage2e_executor_attestation",),
            "validation_evidence_runtime/v1",
        ),
    ),
    resolved_added_imports_sha256="48b3eeef060d2006ed69d09870032d0fe8f48401d5c3647c9f607abc0caf2450",
    sensitive_unresolved_sha256="3f86d94b8c42a8e13f297fc9f60d9c34e198f760c5ca236c5039f7546038caca",
)
CURRENT_EXECUTION_EVIDENCE_MANIFEST: Final = PHASE_E_MANIFEST
_SUPPORTED_MANIFESTS: Final = (
    PHASE_G_MANIFEST,
    PHASE_A_MANIFEST,
    PHASE_B_MANIFEST,
    PHASE_C1_MANIFEST,
    PHASE_C2_MANIFEST,
    PHASE_E_MANIFEST,
)

# These literals describe the approved parent, not a production-discovered API.
# fmt: off
_LEGACY_CLASSES: Final = frozenset({
        "ExecutorProvenanceError", "ExecutorImplementationIdentity",
        "_FixtureExecutorImplementationIdentity", "ValidationJobArmProjection",
        "ValidationJobProjection", "SubmittedJobProjection", "ExecutorConfigurationProjection",
        "ExecutorImplementationProjection", "ExecutionExpectedCompletionProjection",
        "ExecutionSpecificationProjection", "_IssuedExecutorImplementation",
        "ExecutionSpecification", "_FixtureExecutionSpecification", "ActualExecutorAttestation",
        "_ExecutionEnvironment", "_AuthorityContext", "_SpecificationObservation",
        "_IssuedSpecification", "_ExecutorObservation", "_IssuedAttestation",
})
_LEGACY_FUNCTIONS: Final = frozenset({
        "_opaque_runtime_callable", "_executor_implementation_fingerprint",
        "_make_executor_implementation_registry",
        "_make_production_executor_implementation_registry",
        "_install_executor_registry_accessors", "validation_job_projection",
        "_validate_identifier", "_validate_validation_job_projection", "submitted_job_id",
        "_validation_job_content", "_submitted_jobs", "_canonical_production_submitted_jobs",
        "_compiled_top_level_function", "_resolved_callable_source",
        "_verified_job_callable_projection", "_validate_execution_specification_context",
        "_execution_specification_id_from_projection", "execution_specification_id_from_projection",
        "_fixture_execution_specification_id_from_projection",
        "_assemble_execution_specification_projection", "_issue_fixture_execution_specification",
        "_install_execution_specification_accessors", "execute_deterministic_map",
        "validate_executor_attestation", "executor_execution_specification",
        "_require_issued_result_batch", "execution_specification_payload",
        "executor_attestation_payload", "executor_provenance_payload",
        "_invalidate_executor_attestation", "_deterministic_configuration_sha256",
        "_execution_identity_values", "_issue_execution_specification",
        "_claim_execution_specification", "_require_specification", "_require_attestation",
        "_validate_authority_record", "_validate_specification_relations",
        "_validate_attestation_specification_relations", "_authority_context",
        "_current_execution_environment", "_validated_configuration",
        "_validate_completed_indexes", "_normalized_namespace",
        "_next_executor_instance_identity", "_worker_identity", "_timestamp",
        "_callable_identity", "_observation_fingerprint", "_returned_result_identity",
        "_identity_digest", "_value_identity", "_execution_identity", "_error",
        "_install_stage1_executor_implementation_authority",
        "_install_production_execution_plan_issuer",
})
_LEGACY_ASSIGNMENTS: Final = frozenset({
        "_EXECUTION_COUNTER", "_COUNTER_LOCK", "_ATTESTATION_LOCK",
        "_issue_production_executor_implementation_record",
        "_require_production_executor_implementation_record",
        "_invalidate_production_executor_implementation_record",
        "_production_executor_implementation_record_count",
        "_issue_fixture_executor_implementation_record",
        "_require_fixture_executor_implementation_record",
        "_invalidate_fixture_executor_implementation_record",
        "_reset_fixture_executor_implementation_records",
        "_fixture_executor_implementation_record_count",
        "_production_executor_implementation_current_count",
        "_require_production_executor_implementation", "_require_fixture_executor_implementation",
        "_invalidate_production_executor_implementation",
        "_invalidate_fixture_executor_implementation", "_reset_fixture_executor_implementations",
        "executor_implementation_projection", "executor_implementation_identity",
        "_production_executor_implementation_is_current",
        "_fixture_executor_implementation_projection",
        "_fixture_executor_implementation_identity", "execution_specification_id",
        "p2_execution_specification_projection", "_fixture_execution_specification_id",
        "_fixture_execution_specification_projection", "_require_trusted_executor_callable",
        "_issue_production_executor_implementation", "_issue_fixture_executor_implementation",
        "_issue_production_execution_plan_drafts",
})
_LEGACY_ANNASSIGNS: Final = frozenset({
        "_SPECIFICATION_CONSTRUCTION_KEY", "_ATTESTATION_CONSTRUCTION_KEY",
        "_FULL_STUDY_EXECUTION_KEY", "_PRODUCTION_CONFORMANCE_EXECUTION_KEY",
        "_DIAGNOSTIC_CONFORMANCE_EXECUTION_KEY", "_SMOKE_VALIDATION_EXECUTION_KEY",
        "_PROCESS_EXECUTOR_NONCE", "_P2_EXECUTION_ROLE_ORDER", "_P2_EXECUTION_CONFIGURATIONS",
        "_P2_SMOKE_WORLD_IDS", "_P2_SMOKE_SEEDS", "_P2_BUDGETS", "_P2_ARMS",
        "_P2_FIXTURE_WORLD_SEEDS", "_EXECUTOR_ISSUER_ENTRY_POINT",
        "_FIXTURE_EXECUTOR_ISSUER_ENTRY_POINT", "_EXECUTION_SPECIFICATIONS",
        "_EXECUTOR_ATTESTATIONS", "_RESULT_BATCH_ATTESTATIONS",
})
_LEGACY_TYPE_ALIASES: Final = frozenset({
        "ExecutorKind", "ResultOrder", "ExecutionPurpose", "ExecutorTrustDomain",
        "P2ExecutionRole", "P2ExecutionConfiguration",
})
_LEGACY_DELETES: Final = frozenset({
        "_production_executor_implementation_record_count",
        "_fixture_executor_implementation_record_count",
        "_make_production_executor_implementation_registry",
        "_make_executor_implementation_registry",
        "_install_executor_registry_accessors", "_install_execution_specification_accessors",
        "_issue_production_executor_implementation_record",
        "_issue_fixture_executor_implementation_record",
        "_install_stage1_executor_implementation_authority",
        "_install_production_execution_plan_issuer",
})
# fmt: on


def _import_group(
    module: str | None, names: tuple[str, ...]
) -> tuple[ExecutionEvidenceImport, ...]:
    return tuple(ExecutionEvidenceImport(module, name) for name in names)


_PROTOCOL_MODULE = "research_decision_engine.benchmarks.broader_protocol"
# fmt: off
_LEGACY_IMPORTS: Final = (
    ExecutionEvidenceImport("__future__", "annotations"),
    *_import_group(None, (
        "hashlib", "importlib", "inspect", "os", "platform", "re", "secrets", "sys", "threading",
    )),
    ExecutionEvidenceImport("collections", "Counter"),
    *_import_group("collections.abc", ("Callable", "Mapping", "Sequence")),
    *_import_group("concurrent.futures", ("ThreadPoolExecutor", "as_completed")),
    *_import_group("dataclasses", ("asdict", "dataclass", "fields", "is_dataclass")),
    ExecutionEvidenceImport("dataclasses", "replace", "dataclass_replace"),
    *_import_group("datetime", ("UTC", "datetime")),
    ExecutionEvidenceImport("enum", "Enum"), ExecutionEvidenceImport("pathlib", "Path"),
    *_import_group("types", ("CodeType", "FunctionType", "MappingProxyType")),
    *_import_group("typing", ("Final", "Literal", "NoReturn", "SupportsIndex", "cast")),
    *_import_group(_PROTOCOL_MODULE, (
        "PROTOCOL_CHECKPOINT", "PROTOCOL_VERSION", "SOURCE_CHECKPOINT",
        "canonical_json_bytes", "f64", "protocol_hash", "repository_root",
    )),
    *_import_group(_EVIDENCE_MODULE, (
        "EVIDENCE_CONTRACT_CHECKPOINT", "STUDY_ID", "CallableProjection",
        "ImplementationProjection", "IssuerProjection", "Layer0Context", "P2Stage1Error",
        "RuntimeProjection", "ValidationRun", "_allocate_production_plan_capability",
        "_fixture_validation_run_id", "_FixtureValidationRun", "_PlanDraft",
        "_production_validation_run_id", "_ProductionPreparationCapability",
        "_record_production_plan_draft", "_register_fixture_plan",
        "_require_production_preparation", "_seal_production_component_callable",
        "callable_projection",
    )),
    ExecutionEvidenceImport(
        _EVIDENCE_MODULE, "_opaque_runtime_callable", "_trusted_opaque_runtime_callable"
    ),
)
# fmt: on

_STAGE_2D2_SCHEMAS: Final = {
    "ExecutionInstanceProjection": "broader-replication-execution-instance/v1",
    "ExecutionIdentityProjection": "broader-replication-execution/v1",
    "SubmittedJobsProjection": "broader-replication-submitted-jobs/v1",
    "ExecutionStartProjection": "broader-replication-execution-start/v1",
    "WorkerIdentityProjection": "broader-replication-worker-identity/v1",
    "ReturnedResultProjection": "broader-replication-returned-result/v1",
    "ResultBatchProjection": "broader-replication-result-batch/v1",
    "ExecutionCompletionProjection": "broader-replication-execution-completion/v1",
    "ReturnedResultsProjection": "broader-replication-returned-results/v1",
    "WorkerResultOrderProjection": "broader-replication-worker-result-order/v1",
    "ExecutorAttestationProjection": "broader-replication-executor-attestation/v1",
}
_STAGE_2D2_FIELDS: Final = {
    "ExecutionInstanceProjection": _words(
        "counter issuer_identity process_id process_nonce process_started_at schema_version"
    ),
    "ExecutionIdentityProjection": _words(
        "execution_instance execution_instance_identity execution_specification_id "
        "implementation_commit implementation_diff_sha256 implementation_tree_sha256 "
        "oracle_binding_id oracle_execution_id protocol_checkpoint role runtime_identity "
        "schema_version study_id validation_authority_id validation_run_id"
    ),
    "SubmittedJobsProjection": _words(
        "configuration_sha256 execution_id execution_specification_id implementation jobs "
        "oracle_binding_id oracle_execution_id protocol_checkpoint runtime runtime_identity "
        "schema_version study_id validation_authority_id validation_run_id"
    ),
    "ExecutionStartProjection": _words(
        "execution_id execution_instance_identity execution_specification_id schema_version "
        "started_at validation_authority_id validation_run_id"
    ),
    "WorkerIdentityProjection": _words(
        "execution_instance_identity execution_specification_id process_id schema_version "
        "thread_id thread_name validation_authority_id validation_run_id"
    ),
    "ReturnedResultProjection": _words(
        "execution_id execution_specification_id result_payload_sha256 schema_version "
        "submitted_job_id validation_authority_id validation_run_id"
    ),
    "ResultBatchProjection": _words(
        "execution_id execution_specification_id job_result_mapping "
        "result_payload_sha256_in_delivery_order returned_result_ids_in_delivery_order "
        "schema_version validation_authority_id validation_run_id"
    ),
    "ExecutionCompletionProjection": _words(
        "completed_at execution_id execution_specification_id execution_start_id "
        "execution_status job_result_mapping observed_worker_ids "
        "returned_result_ids_in_delivery_order schema_version validation_authority_id "
        "validation_run_id"
    ),
    "ReturnedResultsProjection": _words(
        "execution_completion_id execution_id execution_specification_id execution_status "
        "implementation job_result_mapping oracle_binding_id oracle_execution_id "
        "protocol_checkpoint results_in_submission_order runtime runtime_identity "
        "schema_version study_id validation_authority_id validation_run_id"
    ),
    "WorkerResultOrderProjection": _words(
        "execution_completion_id execution_id execution_specification_id execution_status "
        "implementation job_result_mapping oracle_binding_id oracle_execution_id "
        "protocol_checkpoint results_in_actual_delivery_order runtime runtime_identity "
        "schema_version study_id validation_authority_id validation_run_id"
    ),
    "ExecutorAttestationProjection": _words(
        "accepted_job_ids actual_worker_count completed_at configured_worker_count "
        "configuration_sha256 evidence_contract_checkpoint execution_completion_id "
        "execution_id execution_purpose execution_specification_id execution_start_id "
        "execution_status executor_implementation_identity executor_implementation "
        "execution_instance_identity executor_kind implementation job_result_mapping "
        "normalized_execution_namespace observed_worker_ids oracle_binding_id "
        "oracle_execution_id protocol_checkpoint result_batch_id result_delivery_mode "
        "result_payload_sha256_in_delivery_order returned_results returned_results_sha256 "
        "role runtime runtime_identity scheduling_mode schema_version started_at study_id "
        "submitted_jobs submitted_jobs_sha256 trust_domain validation_authority_id "
        "validation_run_id worker_result_order worker_result_order_sha256"
    ),
}
_PHASE_A_READER_METHOD_ORDER: Final = _words(
    "fail closed field hashes items h64s mapping worker returned_run string identifier h64 "
    "git40 u64 i64 literal timestamp f64 npath file implementation callable_projection "
    "executor_implementation submitted_jobs_projection returned_results_projection "
    "worker_result_order_projection runtime job"
)
_STAGE_2D2_DOMAINS: Final = {
    "execution_instance_identity": "validation_evidence_execution_instance/v1",
    "execution_id": "validation_evidence_execution/v1",
    "submitted_jobs_sha256": "validation_evidence_submitted_jobs/v1",
    "execution_start_id": "validation_evidence_execution_start/v1",
    "worker_identity": "validation_evidence_worker_identity/v1",
    "returned_result_id": "validation_evidence_returned_result/v1",
    "result_batch_id": "validation_evidence_result_batch/v1",
    "execution_completion_id": "validation_evidence_execution_completion/v1",
    "returned_results_sha256": "validation_evidence_returned_results/v1",
    "worker_result_order_sha256": "validation_evidence_worker_result_order/v1",
    "executor_attestation_id": "validation_evidence_executor_attestation/v1",
}
# fmt: off
_AUXILIARY_HASHES: Final = frozenset({
    (("_ExecutionEvidenceDecoder", "runtime"), "pytest_interpreter_identity/v1"),
    (("_ExecutionEvidenceDecoder", "runtime"), "pytest_platform_identity/v1"),
    (("validate_stage2d2_execution_foundations",), "validation_evidence_runtime/v1"),
    (("validate_stage2e_executor_attestation",),
     "validation_evidence_executor_configuration/v1"),
    (("validate_stage2e_executor_attestation",),
     "validation_evidence_executor_implementation/v1"),
    (("validate_stage2e_executor_attestation",),
     "validation_evidence_execution_specification/v1"),
    (("validate_stage2e_executor_attestation",), "validation_evidence_runtime/v1"),
})
_LATER_PROJECTIONS: Final = frozenset({
    "ScientificCalibrationSelectionProjection", "CalibrationSourceObservationProjection",
    "CalibrationCandidatePairProjection", "StrictChronologyProjection",
    "CalibrationSelectionProjection",
})
_FORBIDDEN_PROJECTIONS: Final = _LATER_PROJECTIONS | frozenset({
    "JobResultMappingProjection",
})
_LATER_IDENTITY_NAMES: Final = frozenset({
    "calibration_candidate_pair_id", "calibration_selection_id", "oracle_key_id",
    "outcome_digest", "selector_result_identity", "source_observation_identity",
    "strict_chronology_id",
})
_FORBIDDEN_IDENTITY_NAMES: Final = _LATER_IDENTITY_NAMES | frozenset({
    "aggregate_id", "aggregate_identity", "aggregate_sha256",
    "job_result_mapping_id", "job_result_mapping_identity", "job_result_mapping_sha256",
    "result_aggregate_id", "result_aggregate_identity", "result_aggregate_sha256",
    "returned_results_id", "returned_results_identity", "worker_result_order_id",
    "worker_result_order_identity",
})
_LATER_IDENTITY_DOMAINS: Final = frozenset({
    "oracle_key_id/v1", "revealed_outcome/v1",
    "validation_evidence_calibration_candidate_pair/v1",
    "validation_evidence_calibration_chronology/v1",
    "validation_evidence_calibration_selection/v1",
    "validation_evidence_calibration_source_observation/v1",
})
_FORBIDDEN_IDENTITY_DOMAINS: Final = _LATER_IDENTITY_DOMAINS | frozenset({
    "validation_evidence_aggregate/v1",
    "validation_evidence_job_result_mapping/v1",
    "validation_evidence_result_aggregate/v1",
})
_HISTORICAL_IDENTITIES: Final = frozenset(
    {
        "_execution_identity",
        "_returned_result_identity",
        "_worker_identity",
        "_identity_digest",
        "result_order_sha256",
    }
)
_HISTORICAL_ATTESTATION_SURFACE: Final = frozenset({
    "ActualExecutorAttestation", "executor_attestation_payload", "executor_provenance_payload",
    "validate_executor_attestation",
})
_REFLECTION_LEAVES: Final = frozenset({
    "__class__", "__dict__", "__getattribute__", "__import__", "__mro__", "__subclasses__",
    "asdict", "compile", "dir", "eval", "exec", "fields", "getattr", "getattr_static",
    "getmembers", "globals", "hasattr", "is_dataclass", "locals", "make_dataclass", "mro",
    "new_class", "pickle", "repr", "setattr", "vars",
})
_FORBIDDEN_CALL_LEAVES: Final = frozenset({
    "execute_deterministic_map", "open", "run", "run_arm", "system", "write_bytes",
    "repository_root", "write_text", "world_authority",
})
_FORBIDDEN_CALL_MARKERS: Final = (
    "asyncio.", "broader_oracle.", "broader_conformance.", "broader_smoke.",
    "concurrent.futures.", "hashlib.", "http.", "importlib.", "inspect.", "os.", "pathlib.",
    "platform.", "requests.", "secrets.", "socket.", "sqlite3.", "subprocess.", "sys.",
    "threading.", "urllib.", ".policies.", ".storage.",
)
_CAPABILITY_OR_REGISTRY_MARKERS: Final = (
    "_allocate_production_plan_capability", "_ProductionPreparationCapability",
    "_record_production_plan_draft", "_register_fixture_plan",
    "_require_production_preparation", "_EXECUTION_SPECIFICATIONS", "_EXECUTOR_ATTESTATIONS",
    "_RESULT_BATCH_ATTESTATIONS", "CANDIDATES_BY_ID", "CANDIDATE_CATALOG",
    "WORLDS_BY_ID", "capability", "private_key", "registry", "secret_key", "signing",
)
_PURE_LEGACY_TARGETS: Final = frozenset({
    "ExecutionExpectedCompletionProjection", "ExecutionSpecificationProjection",
    "ExecutorConfigurationProjection",
    "ExecutorImplementationProjection", "ExecutorProvenanceError", "SubmittedJobProjection",
    "ValidationJobArmProjection", "ValidationJobProjection", "_validation_job_content",
    "submitted_job_id",
})
_PURE_EVIDENCE_PROJECTIONS = (
    "CallableProjection", "FileProjection", "ImplementationProjection",
    "InterpreterIdentityProjection", "PlatformIdentityProjection", "RuntimeProjection",
    "ValidationAuthorityProjection",
)
_PURE_IMPORTED_CALLS: Final = frozenset({
    "dataclasses.dataclass", "datetime.datetime.strptime", "math.isfinite", "re.fullmatch",
    "re.match", "struct.unpack", "typing.cast", "unicodedata.normalize",
    f"{_PROTOCOL_MODULE}.protocol_hash",
    f"{_RETURNED_MODULE}.decode_returned_run_projection",
    f"{_RETURNED_MODULE}.projection_as_dict",
    f"{_RETURNED_MODULE}.validate_returned_run_batch",
    f"{_RETURNED_MODULE}.validate_returned_run_projection_shape",
    *(f"{_EVIDENCE_MODULE}.{name}{suffix}" for name in _PURE_EVIDENCE_PROJECTIONS
      for suffix in ("", ".as_dict")),
})
_PURE_IMPORTED_REFERENCES: Final = frozenset({
    "typing.Final", "typing.Literal", "typing.NoReturn",
    f"{_RETURNED_MODULE}.ReturnedRunProjection",
    f"{_RETURNED_MODULE}.ReturnedRunProjectionError",
    f"{_RUNNER_MODULE}.BroaderArmRun",
    *(f"{_EVIDENCE_MODULE}.{name}" for name in _PURE_EVIDENCE_PROJECTIONS),
})
_PURE_CALL_QUALIFIERS = ("datetime.datetime", "math", "re", "struct", "unicodedata")
_EVIDENCE_MUTATORS: Final = frozenset({
    "add", "append", "insert", "record", "setdefault", "update", "write",
    "write_bytes", "write_text",
})
_TOP_LEVEL_NODES = (
    ast.AnnAssign, ast.Assign, ast.ClassDef, ast.Delete, ast.Expr, ast.FunctionDef,
    ast.Import, ast.ImportFrom, ast.TypeAlias,
)
_PHASE_B_SIGNATURES: Final = {
    "_d2_payload_job": (
        ("payload", "submitted_jobs", "submitted_job_identity"),
        (),
    ),
    "build_job_result_mapping": (
        ("submitted_jobs", "results_in_actual_delivery_order"),
        (),
    ),
    "decode_returned_result_projection": (("value",), ()),
    "returned_result_id": (("projection",), ()),
    "validate_stage2d2_returned_results": (
        (),
        _words(
            "expected_execution_instance execution_instance "
            "carried_execution_instance_identity expected_execution execution "
            "carried_execution_id expected_submitted_jobs submitted_jobs "
            "carried_submitted_jobs_sha256 expected_execution_start execution_start "
            "carried_execution_start_id expected_workers_in_actual_delivery_order "
            "workers_in_actual_delivery_order returned_domains_in_actual_delivery_order "
            "returned_runs_in_actual_delivery_order "
            "returned_result_projections_in_actual_delivery_order "
            "carried_returned_result_ids_in_actual_delivery_order"
        ),
    ),
}
_C1_RESULT_PARAMETERS: Final = (
    *_PHASE_B_SIGNATURES["validate_stage2d2_returned_results"][1],
    *_words("job_result_mapping result_batch carried_result_batch_id observed_execution_status "
            "observed_completed_at execution_completion carried_execution_completion_id"),
)
_C2_RESULT_PARAMETERS: Final = (
    *_C1_RESULT_PARAMETERS, *_words(
        "returned_results carried_returned_results_sha256 worker_result_order "
        "carried_worker_result_order_sha256")
)
_E_RESULT_PARAMETERS: Final = (
    *_words(
        "expected_validation_authority expected_execution_specification "
        "expected_executor_implementation expected_executor_implementation_identity "
        "accepted_job_ids_in_actual_acceptance_order"
    ),
    *_C2_RESULT_PARAMETERS,
    *_words("executor_attestation carried_executor_attestation_id"),
)
_RESULT_VALIDATION_RETURN: Final = "tuple[tuple[ReturnedResultObservation, ...], JobResultMapping]"
_STAGE_E_HELPERS: Final = frozenset(
    _words(
        "_stage2e_type _stage2e_strings _stage2e_string_sequence "
        "_stage2e_job_result_mapping _stage2e_submitted_job_sequence "
        "_stage2e_projection_children _stage2e_projection_shape "
        "_stage2e_plain_value _stage2e_projection_mapping"
    )
)
_STAGE_E_TYPE_FUNCTIONS: Final = _words(
    "_stage2e_type _stage2e_strings _stage2e_string_sequence "
    "_stage2e_job_result_mapping _stage2e_submitted_job_sequence "
    "_stage2e_projection_children _stage2e_projection_shape "
    "validate_stage2e_executor_attestation"
)
_STAGE_E_SERIALIZATION_FUNCTIONS: Final = _words(
    "_stage2e_projection_children _stage2e_projection_shape "
    "_stage2e_plain_value _stage2e_projection_mapping"
)
_STAGE_E_TYPE_SHA256: Final = "6a81c3a2c990fe16725b49514a29ff39574691254170f0438d8b7e4cf553c99a"
_STAGE_E_SERIALIZATION_SHA256: Final = (
    "c0f910a322ce17994e66113f0f7e23ffa95ddfadc617c95fa2adf1dd8a96a620"
)
_STAGE_E_ID_SHA256: Final = "02a3347ae4d8a2adad48c223b3b784ab0647294c3aa57e4df06222cb5b28d62e"
# fmt: on


def _stored_names(target: ast.AST) -> frozenset[str]:
    return frozenset(
        node.id
        for node in ast.walk(target)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    )


def _target_names(target: ast.AST) -> frozenset[str]:
    return frozenset(node.id for node in ast.walk(target) if isinstance(node, ast.Name))


def _binding_names(node: ast.stmt) -> frozenset[str]:
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return frozenset({node.name})
    if isinstance(node, ast.Assign):
        return frozenset().union(*(_stored_names(target) for target in node.targets))
    if isinstance(node, ast.AnnAssign):
        return _stored_names(node.target)
    if isinstance(node, ast.TypeAlias):
        return frozenset({node.name.id})
    if isinstance(node, ast.Delete):
        return frozenset().union(*(_target_names(target) for target in node.targets))
    return frozenset()


def _imports(tree: ast.Module) -> tuple[ExecutionEvidenceImport, ...]:
    occurrences: list[ExecutionEvidenceImport] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            occurrences.extend(
                ExecutionEvidenceImport(None, item.name, item.asname) for item in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            occurrences.extend(
                ExecutionEvidenceImport(node.module, item.name, item.asname, node.level)
                for item in node.names
            )
    return tuple(occurrences)


def _surface(tree: ast.Module, kind: type[ast.stmt]) -> frozenset[str]:
    return frozenset(
        name for node in tree.body if isinstance(node, kind) for name in _binding_names(node)
    )


def _surface_occurrences(tree: ast.Module, kind: type[ast.stmt]) -> Counter[str]:
    return Counter(
        name for node in tree.body if isinstance(node, kind) for name in _binding_names(node)
    )


def _strip_manifest(tree: ast.Module, manifest: ExecutionEvidenceManifest) -> ast.Module:
    added_imports = Counter(manifest.added_import_occurrences)
    body: list[ast.stmt] = []
    for node in tree.body:
        names = _binding_names(node)
        if (
            isinstance(node, ast.ClassDef)
            and names <= manifest.added_classes
            or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and names <= manifest.added_functions
            or isinstance(node, ast.Assign)
            and names
            and names <= manifest.added_assignments
            or isinstance(node, ast.AnnAssign)
            and names <= manifest.added_annassigns
            or isinstance(node, ast.TypeAlias)
            and names <= manifest.added_type_aliases
        ):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            retained: list[ast.alias] = []
            for item in node.names:
                occurrence = (
                    ExecutionEvidenceImport(None, item.name, item.asname)
                    if isinstance(node, ast.Import)
                    else ExecutionEvidenceImport(node.module, item.name, item.asname, node.level)
                )
                if added_imports[occurrence]:
                    added_imports[occurrence] -= 1
                else:
                    retained.append(item)
            if retained:
                body.append(
                    ast.Import(names=retained)
                    if isinstance(node, ast.Import)
                    else ast.ImportFrom(module=node.module, names=retained, level=node.level)
                )
            continue
        body.append(node)
    return ast.Module(body=body, type_ignores=tree.type_ignores)


def _root_is_delta(node: ast.stmt, manifest: ExecutionEvidenceManifest) -> bool:
    names = _binding_names(node)
    if isinstance(node, ast.ClassDef):
        return not names <= _LEGACY_CLASSES
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return not names <= _LEGACY_FUNCTIONS
    if isinstance(node, ast.Assign):
        return bool(names - _LEGACY_ASSIGNMENTS)
    if isinstance(node, ast.AnnAssign):
        return bool(names - _LEGACY_ANNASSIGNS)
    if isinstance(node, ast.TypeAlias):
        return bool(names - _LEGACY_TYPE_ALIASES)
    if isinstance(node, ast.Delete):
        return bool(names - _LEGACY_DELETES)
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return bool(
            Counter(_imports(ast.Module(body=[node], type_ignores=[]))) - Counter(_LEGACY_IMPORTS)
        )
    return not (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _delta_nodes(tree: ast.Module, manifest: ExecutionEvidenceManifest) -> tuple[ast.AST, ...]:
    return tuple(
        child for root in tree.body if _root_is_delta(root, manifest) for child in ast.walk(root)
    )


def _delta_lines(nodes: tuple[ast.AST, ...]) -> frozenset[int]:
    return frozenset(
        line
        for node in nodes
        if hasattr(node, "lineno")
        for line in range(node.lineno, getattr(node, "end_lineno", node.lineno) + 1)
    )


def _class_schema_pairs(
    tree: ast.Module, manifest: ExecutionEvidenceManifest
) -> frozenset[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name not in manifest.projection_classes:
            continue
        pairs.update(
            (node.name, value.value)
            for value in ast.walk(node)
            if isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and value.value.startswith("broader-replication-")
            and value.value.endswith("/v1")
        )
    return frozenset(pairs)


def _is_exact_frozen_slots_dataclass(node: ast.ClassDef) -> bool:
    if len(node.decorator_list) != 1:
        return False
    decorator = node.decorator_list[0]
    return (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Name)
        and decorator.func.id == "dataclass"
        and not decorator.args
        and tuple(keyword.arg for keyword in decorator.keywords) == ("frozen", "slots")
        and all(
            isinstance(keyword.value, ast.Constant) and keyword.value.value is True
            for keyword in decorator.keywords
        )
        and not node.bases
        and not node.keywords
    )


def _added_class_body_is_exact(node: ast.ClassDef, manifest: ExecutionEvidenceManifest) -> bool:
    members = tuple(
        child
        for child in node.body
        if not (
            isinstance(child, ast.Expr)
            and isinstance(child.value, ast.Constant)
            and isinstance(child.value.value, str)
        )
    )
    fields = tuple(
        child.target.id
        for child in members
        if isinstance(child, ast.AnnAssign)
        and isinstance(child.target, ast.Name)
        and child.value is None
    )
    methods = tuple(child.name for child in members if isinstance(child, ast.FunctionDef))
    expected_fields: tuple[str, ...] | None
    expected_methods: tuple[str, ...]
    if node.name in manifest.projection_classes:
        expected_fields = _STAGE_2D2_FIELDS.get(node.name)
        expected_methods = ("as_dict",)
    elif "Decoder" in node.name:
        expected_fields = ("value", "path", "context") if "fail" in manifest.reader_methods else ()
        expected_methods = tuple(
            name for name in _PHASE_A_READER_METHOD_ORDER if name in manifest.reader_methods
        )
    else:
        return False
    if expected_fields is None:
        return False
    expected_kinds = (ast.AnnAssign,) * len(expected_fields) + (ast.FunctionDef,) * len(
        expected_methods
    )
    return (
        _is_exact_frozen_slots_dataclass(node)
        and tuple(type(member) for member in members) == expected_kinds
        and fields == expected_fields
        and methods == expected_methods
        and all(
            not method.decorator_list for method in members if isinstance(method, ast.FunctionDef)
        )
    )


def _qualified_target_is_forbidden(target: str) -> bool:
    leaf = target.rsplit(".", 1)[-1]
    return leaf in _FORBIDDEN_CALL_LEAVES or any(
        marker in target for marker in _FORBIDDEN_CALL_MARKERS
    )


def _target_is_reflective(target: str) -> bool:
    return target.startswith("inspect.") or target.rsplit(".", 1)[-1] in _REFLECTION_LEAVES


def _value_aliases_surface(value: ast.AST, aliases: frozenset[str]) -> bool:
    if isinstance(value, ast.Name):
        return isinstance(value.ctx, ast.Load) and value.id in aliases
    if isinstance(value, ast.Call):
        return any(
            _value_aliases_surface(item, aliases)
            for item in (
                *value.args,
                *(keyword.value for keyword in value.keywords),
            )
        )
    return any(_value_aliases_surface(child, aliases) for child in ast.iter_child_nodes(value))


def _resolved_added_imports_sha256(
    calls: tuple[alias_guard.ResolvedCall, ...],
    references: tuple[alias_guard.ResolvedReference, ...],
    manifest: ExecutionEvidenceManifest,
) -> str:
    origins = frozenset(
        f"{item.module}.{item.name}" if item.module is not None else item.name
        for item in manifest.added_import_occurrences
    )

    def is_added_import_target(target: str) -> bool:
        return any(target == origin or target.startswith(f"{origin}.") for origin in origins)

    rows = tuple(
        sorted(
            (
                "call",
                call.scope,
                call.spelling,
                target,
                call.lineno,
            )
            for call in calls
            for target in call.targets
            if is_added_import_target(target)
        )
        + sorted(
            (
                "reference",
                reference.scope,
                reference.spelling,
                target,
                reference.lineno,
            )
            for reference in references
            for target in reference.targets
            if is_added_import_target(target)
        )
    )
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def _signatures_are_exact(
    tree: ast.Module,
    signatures: dict[str, tuple[tuple[str, ...], tuple[str, ...]]],
    return_annotation: str | None = None,
) -> bool:
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for name, (positional, keyword_only) in signatures.items():
        node = functions.get(name)
        if node is None:
            return False
        arguments = node.args
        if (
            tuple(item.arg for item in (*arguments.posonlyargs, *arguments.args)) != positional
            or tuple(item.arg for item in arguments.kwonlyargs) != keyword_only
            or arguments.vararg is not None
            or arguments.kwarg is not None
            or arguments.defaults
            or any(default is not None for default in arguments.kw_defaults)
            or return_annotation is not None
            and (node.returns is None or ast.unparse(node.returns) != return_annotation)
        ):
            return False
    return True


def _stage_e_function_digest(tree: ast.Module, names: tuple[str, ...]) -> str:
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    if not functions.keys() >= set(names):
        return ""
    rows = tuple((name, ast.dump(functions[name])) for name in names)
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def _stage_e_nested_boundary_checks(tree: ast.Module) -> tuple[bool, bool, bool]:
    return (
        _stage_e_function_digest(tree, _STAGE_E_TYPE_FUNCTIONS) == _STAGE_E_TYPE_SHA256,
        _stage_e_function_digest(tree, _STAGE_E_SERIALIZATION_FUNCTIONS)
        == _STAGE_E_SERIALIZATION_SHA256,
        _stage_e_function_digest(tree, ("executor_attestation_id",)) == _STAGE_E_ID_SHA256,
    )


def _stage_e_analysis_source(source: str, manifest: ExecutionEvidenceManifest) -> str:
    if manifest.phase != "2E":
        return source
    tree, lines = ast.parse(source), source.splitlines(keepends=True)
    mapper = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_stage2e_projection_mapping"
    )
    assert mapper.end_lineno is not None
    start = mapper.body[0].lineno - 1
    lines[start : mapper.end_lineno] = ["    pass\n", *(["\n"] * (mapper.end_lineno - start - 1))]
    return "".join(lines)


def execution_evidence_architecture_checks(
    source: str,
    *,
    manifest: ExecutionEvidenceManifest,
    analysis: alias_guard.QualifiedSymbolAnalysis | None = None,
) -> tuple[tuple[str, bool], ...]:
    """Return exact, alias-aware checks for one cumulative Stage-2D.2 phase."""

    tree = ast.parse(source)
    if analysis is None:
        analysis = alias_guard.analyze_qualified_symbols(
            _stage_e_analysis_source(source, manifest), module_name=_MODULE
        )._replace(source_text=source)
    elif analysis.source_text != source or analysis.module_name != _MODULE:
        raise ValueError("precomputed analysis does not match execution-evidence source")

    delta_nodes = _delta_nodes(tree, manifest)
    delta_lines = _delta_lines(delta_nodes)
    delta_names = frozenset(node.id for node in delta_nodes if isinstance(node, ast.Name))
    delta_strings = frozenset(
        node.value
        for node in delta_nodes
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )
    delta_calls = tuple(call for call in analysis.calls if call.lineno in delta_lines)
    delta_references = tuple(
        reference for reference in analysis.references if reference.lineno in delta_lines
    )
    delta_findings = tuple(
        finding for finding in analysis.findings if finding.lineno in delta_lines
    )
    delta_targets = frozenset(
        target for call in delta_calls for target in call.targets
    ) | frozenset(target for reference in delta_references for target in reference.targets)
    delta_binding_names = frozenset(
        binding.name for binding in analysis.binding_events if binding.lineno in delta_lines
    )
    delta_origins = frozenset(
        origin
        for binding in (*analysis.imports, *analysis.binding_events)
        if binding.lineno in delta_lines
        for origin in binding.origins
    )
    # fmt: off
    import_origins = frozenset(origin for binding in analysis.imports for origin in binding.origins)
    imported_call_sites = Counter(
        (call.lineno, target) for call in delta_calls for target in call.targets
        if any(target == origin or target.startswith(f"{origin}.") for origin in import_origins)
    )
    imported_call_targets = frozenset(target for _line, target in imported_call_sites)
    resolved_added_imports_sha256 = _resolved_added_imports_sha256(
        delta_calls, delta_references, manifest
    )
    imported_reference_sites = Counter(
        (reference.lineno, target) for reference in delta_references for target in reference.targets
        if target not in _PURE_IMPORTED_REFERENCES
        and any(target == origin or target.startswith(f"{origin}.") for origin in import_origins)
    )
    expected_imported_reference_sites = Counter(
        site for site, count in imported_call_sites.items()
        if site[1] not in _PURE_IMPORTED_REFERENCES for _occurrence in range(count)
    ) + Counter(
        (line, qualifier) for (line, target), count in imported_call_sites.items()
        for qualifier in _PURE_CALL_QUALIFIERS if target.startswith(f"{qualifier}.")
        for _occurrence in range(count)
    )
    delta_symbols = (
        delta_binding_names
        | delta_names
        | delta_strings
        | frozenset(target.rsplit(".", 1)[-1] for target in delta_targets | delta_origins)
    )
    alias_origins = (
        _LEGACY_CLASSES | _LEGACY_FUNCTIONS | frozenset(_STAGE_2D2_SCHEMAS) | _LATER_PROJECTIONS
    )
    fingerprinted = {
        *_STAGE_E_TYPE_FUNCTIONS,
        *_STAGE_E_SERIALIZATION_FUNCTIONS,
        "executor_attestation_id",
    }
    fingerprinted_spans = tuple(
        (node.lineno, node.end_lineno)
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in fingerprinted
        and node.end_lineno is not None
    )
    projection_or_function_alias = any(
        binding.lineno in delta_lines
        and binding.kind in {"assign", "annassign"}
        and any(origin.rsplit(".", 1)[-1] in alias_origins for origin in binding.origins)
        for binding in analysis.binding_events
    ) or any(
        isinstance(node, (ast.Assign, ast.AnnAssign))
        and node.value is not None
        and not any(start <= node.lineno <= end for start, end in fingerprinted_spans)
        and _value_aliases_surface(node.value, alias_origins)
        for node in delta_nodes
    )
    protocol_target = "research_decision_engine.benchmarks.broader_protocol.protocol_hash"
    protocol_calls = tuple(call for call in delta_calls if protocol_target in call.targets)
    protocol_references = tuple(
        reference for reference in delta_references if protocol_target in reference.targets
    )
    protocol_alias = any(
        binding.lineno in delta_lines and protocol_target in binding.origins
        for binding in analysis.binding_events
    )

    expected_hashes = (
        tuple(((name,), domain) for name, domain in manifest.identity_domains)
        + manifest.auxiliary_hashes
    )

    def exact_identity_call(scope: tuple[str, ...], domain: str) -> bool:
        def syntax_is_exact(call: alias_guard.ResolvedCall) -> bool:
            syntax = [
                node
                for node in delta_nodes
                if isinstance(node, ast.Call)
                and node.lineno == call.lineno
                and isinstance(node.func, ast.Name)
                and node.func.id == "protocol_hash"
                and len(node.args) == 2
                and not node.keywords
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == domain
            ]
            return len(syntax) == 1

        return (
            sum(
                call.scope == scope and call.spelling == "protocol_hash" and syntax_is_exact(call)
                for call in protocol_calls
            )
            == 1
        )

    identity_hash_surface = bool(
        len(protocol_calls) == len(expected_hashes)
        and not protocol_alias
        and Counter((item.scope, item.spelling, item.lineno) for item in protocol_calls)
        == Counter((item.scope, item.spelling, item.lineno) for item in protocol_references)
        and all(exact_identity_call(*identity) for identity in expected_hashes)
    )
    expected_schemas = frozenset(
        (name, _STAGE_2D2_SCHEMAS[name]) for name in manifest.projection_classes
    )
    class_occurrences = _surface_occurrences(tree, ast.ClassDef)
    function_occurrences = _surface_occurrences(tree, ast.FunctionDef)
    assignment_occurrences = _surface_occurrences(tree, ast.Assign)
    annassign_occurrences = _surface_occurrences(tree, ast.AnnAssign)
    type_alias_occurrences = _surface_occurrences(tree, ast.TypeAlias)
    actual_classes = frozenset(class_occurrences)
    actual_functions = frozenset(function_occurrences)
    all_classes = frozenset(node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
    decoder_method_occurrences = Counter(
        child.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name in manifest.added_classes
        and "Decoder" in node.name
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    decoder_methods = frozenset(decoder_method_occurrences)
    exact_added_class_bodies = all(
        _added_class_body_is_exact(node, manifest)
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name in manifest.added_classes
    )
    legacy_digest = hashlib.sha256(
        ast.dump(_strip_manifest(tree, manifest)).encode("utf-8")
    ).hexdigest()
    forbidden_future = (
        frozenset(_STAGE_2D2_SCHEMAS) - manifest.projection_classes
    ) | _FORBIDDEN_PROJECTIONS
    approved_identity_names = frozenset(name for name, _domain in manifest.identity_domains)
    approved_identity_domains = frozenset(domain for _name, domain in manifest.identity_domains)
    future_identity_names = frozenset(_STAGE_2D2_DOMAINS) - approved_identity_names
    future_identity_domains = (
        frozenset(_STAGE_2D2_DOMAINS.values()) - approved_identity_domains
    )
    reflective_targets = frozenset(
        target for target in delta_targets if _target_is_reflective(target)
    )
    decoder_lines = frozenset(
        line
        for node in tree.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name.startswith("decode_")
            or isinstance(node, ast.ClassDef)
            and "Decoder" in node.name
        )
        for line in range(node.lineno, (node.end_lineno or node.lineno) + 1)
    )
    reflective_decoder = any(
        call.lineno in decoder_lines
        and (
            _target_is_reflective(call.spelling)
            or any(_target_is_reflective(target) for target in call.targets)
        )
        for call in analysis.calls
    ) or any(
        getattr(node, "lineno", 0) in decoder_lines
        and isinstance(node, (ast.Attribute, ast.Name))
        and (node.attr if isinstance(node, ast.Attribute) else node.id) in _REFLECTION_LEAVES
        for node in delta_nodes
    )
    reader_or_persistence = any(
        token in name.casefold()
        for name in delta_binding_names
        for token in ("reader", "persistence", "repository", "storage", "store")
    )
    evidence_writer = any(
        ("evidence" in target.casefold() and target.rsplit(".", 1)[-1] in _EVIDENCE_MUTATORS)
        or target.rsplit(".", 1)[-1] in {"write_bytes", "write_text"}
        for target in delta_targets
    ) or any(
        call.spelling.rsplit(".", 1)[-1] in {"write_bytes", "write_text"} for call in delta_calls
    )
    live_surfaces = (
        delta_symbols | delta_targets | frozenset(call.spelling for call in delta_calls)
        | frozenset(f.symbol for f in delta_findings)
    )
    forbidden_legacy_targets = (_LEGACY_CLASSES | _LEGACY_FUNCTIONS) - _PURE_LEGACY_TARGETS
    legacy_live_target = any(
        target.startswith(f"{_MODULE}.")
        and target.rsplit(".", 1)[-1] in forbidden_legacy_targets
        for target in delta_targets
    )
    capability_or_registry = legacy_live_target or any(
        marker.casefold() in target.casefold() for target in live_surfaces
        for marker in _CAPABILITY_OR_REGISTRY_MARKERS
    )
    dynamic_codes = {
        "alias-cycle", "dynamic-call", "dynamic-class", "dynamic-module-mutation",
        "dynamic-namespace-reference", "dynamic-scope-binding", "dynamic-__all__",
        "qualified-state-mutation", "unresolved-call-alias", "unresolved-sensitive-provenance",
    }
    sensitive_unresolved_calls = Counter(
        (call.scope, call.spelling) for call in delta_calls if call.sensitive_unresolved
    )
    sensitive_unresolved_references = Counter(
        (reference.scope, reference.spelling)
        for reference in delta_references
        if not reference.targets and "." in reference.spelling
    )
    sensitive_rows = tuple(
        sorted(
            (
                "call",
                scope,
                spelling,
                count,
            )
            for (scope, spelling), count in sensitive_unresolved_calls.items()
        )
        + sorted(
            (
                "reference",
                scope,
                spelling,
                count,
            )
            for (scope, spelling), count in sensitive_unresolved_references.items()
        )
    )
    sensitive_unresolved_sha256 = hashlib.sha256(
        repr(sensitive_rows).encode("utf-8")
    ).hexdigest()
    unsafe_dynamic = (
        sensitive_unresolved_sha256 != manifest.sensitive_unresolved_sha256
        or any(
            finding.code in dynamic_codes - {"unresolved-sensitive-provenance"}
            for finding in delta_findings
        )
    )
    dynamic_projection = any(f.code == "dynamic-class" for f in delta_findings) or any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and (node.func.id in {"__build_class__", "make_dataclass", "new_class"}
             or node.func.id == "type" and len(node.args) == 3)
        for node in delta_nodes
    )
    (
        stage_e_type_before_touch,
        stage_e_trusted_serialization,
        stage_e_identity_before_hash,
    ) = _stage_e_nested_boundary_checks(tree)
    return (
        ("supported-phase-manifest", manifest in _SUPPORTED_MANIFESTS),
        ("exact-top-level-class-surface",
         class_occurrences == Counter(_LEGACY_CLASSES | manifest.added_classes)
         and all_classes == actual_classes),
        ("exact-projection-class-surface",
         frozenset(name for name in actual_classes if name in _STAGE_2D2_SCHEMAS)
         == manifest.projection_classes),
        ("exact-added-class-body-surface", exact_added_class_bodies),
        ("exact-top-level-function-surface",
         function_occurrences == Counter(_LEGACY_FUNCTIONS | manifest.added_functions)),
        ("exact-assignment-surface",
         assignment_occurrences
         == Counter(_LEGACY_ASSIGNMENTS | manifest.added_assignments)),
        ("exact-annassign-surface",
         annassign_occurrences
         == Counter(_LEGACY_ANNASSIGNS | manifest.added_annassigns)),
        ("exact-type-alias-surface",
         type_alias_occurrences
         == Counter(_LEGACY_TYPE_ALIASES | manifest.added_type_aliases)),
        ("exact-import-occurrence-surface",
         Counter(_imports(tree)) == Counter((*_LEGACY_IMPORTS,
                                             *manifest.added_import_occurrences))),
        ("legacy-ast-fingerprint", legacy_digest == manifest.legacy_ast_sha256),
        ("closed-top-level-root-surface",
         all(isinstance(node, _TOP_LEVEL_NODES) for node in tree.body)),
        ("no-future-projection-surface",
         forbidden_future.isdisjoint(delta_symbols | analysis.exports)),
        ("no-stage-2e-or-later-surface",
         future_identity_names.isdisjoint(delta_symbols | analysis.exports)
         and future_identity_domains.isdisjoint(delta_strings)
         and _LATER_PROJECTIONS.isdisjoint(delta_symbols | analysis.exports)
         and _LATER_IDENTITY_NAMES.isdisjoint(delta_symbols | analysis.exports)
         and _LATER_IDENTITY_DOMAINS.isdisjoint(delta_strings)),
        ("no-unapproved-identity-surface",
         _FORBIDDEN_IDENTITY_NAMES.isdisjoint(delta_symbols)
         and _FORBIDDEN_IDENTITY_DOMAINS.isdisjoint(delta_strings)),
        ("no-export-surface", not analysis.exports and "__all__" not in delta_binding_names),
        ("no-module-dynamic-hooks", {"__getattr__", "__dir__"}.isdisjoint(delta_binding_names)),
        ("no-dynamic-projection-construction", not dynamic_projection),
        ("no-projection-or-function-alias", not projection_or_function_alias),
        ("exact-schema-literal-surface", _class_schema_pairs(tree, manifest) == expected_schemas),
        ("exact-identity-domain-surface",
         identity_hash_surface
         and len({domain for _name, domain in manifest.identity_domains})
         == len(manifest.identity_domains)
         and set(manifest.identity_domains) <= set(_STAGE_2D2_DOMAINS.items())
         and len(set(manifest.auxiliary_hashes)) == len(manifest.auxiliary_hashes)
         and set(manifest.auxiliary_hashes) <= _AUXILIARY_HASHES),
        ("closed-decoder-surface",
         frozenset(name for name in actual_functions - _LEGACY_FUNCTIONS
                   if name.startswith("decode_")) == manifest.decoder_functions
         and decoder_methods == manifest.reader_methods
         and decoder_method_occurrences == Counter(manifest.reader_methods)),
        ("no-reflective-decoder", not reflective_decoder),
        ("no-reader-or-persistence", not reader_or_persistence),
        ("no-forbidden-qualified-call",
         not any(_qualified_target_is_forbidden(target) for target in delta_targets)
         and not reflective_targets),
        ("no-evidence-writer", not evidence_writer),
        ("no-live-capability-or-registry", not capability_or_registry),
        ("closed-imported-call-surface", imported_call_targets <= _PURE_IMPORTED_CALLS),
        ("closed-imported-reference-surface",
         imported_reference_sites == expected_imported_reference_sites),
        ("exact-resolved-added-import-surface",
         resolved_added_imports_sha256 == manifest.resolved_added_imports_sha256),
        ("exact-phase-b-function-signatures",
         not PHASE_B_MANIFEST.added_functions <= manifest.added_functions
         or _signatures_are_exact(tree, _PHASE_B_SIGNATURES)),
        ("exact-phase-c1-completion-signature",
         not PHASE_C1_MANIFEST.added_functions <= manifest.added_functions
         or _signatures_are_exact(
             tree, {"validate_stage2d2_result_batch_completion": ((), _C1_RESULT_PARAMETERS)},
             _RESULT_VALIDATION_RETURN)),
        ("exact-phase-c2-aggregate-signature",
         not PHASE_C2_MANIFEST.added_functions <= manifest.added_functions
         or _signatures_are_exact(
              tree, {"validate_stage2d2_result_aggregates": ((), _C2_RESULT_PARAMETERS)},
              _RESULT_VALIDATION_RETURN)),
        ("exact-phase-e-attestation-signatures",
         not PHASE_E_MANIFEST.added_functions <= manifest.added_functions
         or (
             _signatures_are_exact(
                 tree,
                 {"decode_executor_attestation_projection": (("value",), ())},
                 "ExecutorAttestationProjection")
             and _signatures_are_exact(
                 tree,
                 {"executor_attestation_id": (("projection",), ())},
                 "str")
             and _signatures_are_exact(
                 tree,
                 {"validate_stage2e_executor_attestation": ((), _E_RESULT_PARAMETERS)},
                  "ExecutorAttestationProjection")
          )),
        ("exact-stage-e-type-before-touch",
         manifest.phase != "2E" or stage_e_type_before_touch),
        ("stage-e-explicit-type-owned-serialization",
         manifest.phase != "2E" or stage_e_trusted_serialization),
        ("stage-e-id-shape-before-hash",
         manifest.phase != "2E" or stage_e_identity_before_hash),
        ("no-dynamic-indirection", not unsafe_dynamic),
        ("no-historical-task-c-identity",
         _HISTORICAL_IDENTITIES.isdisjoint(delta_names)
         and not any(target.rsplit(".", 1)[-1] in _HISTORICAL_IDENTITIES
                      for target in delta_targets)),
        ("no-historical-task-c-attestation",
         _HISTORICAL_ATTESTATION_SURFACE.isdisjoint(delta_names)
         and not any(target.rsplit(".", 1)[-1] in _HISTORICAL_ATTESTATION_SURFACE
                     for target in delta_targets)),
    )
    # fmt: on
