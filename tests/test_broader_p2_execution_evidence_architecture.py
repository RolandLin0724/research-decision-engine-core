"""Phase-specific adversarial tests for the Stage-2E architecture guard."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests import p2_execution_evidence_architecture_guard as architecture

_guard = architecture.execution_evidence_architecture_checks
_ROOT = Path(__file__).resolve().parents[1]
_PATH = _ROOT / "research_decision_engine" / "benchmarks" / "broader_execution.py"
_SOURCE = _PATH.read_text(encoding="utf-8")
_BASELINE_SOURCE = ast.unparse(
    architecture._strip_manifest(
        ast.parse(_SOURCE), architecture.CURRENT_EXECUTION_EVIDENCE_MANIFEST
    )
)
_EXECUTION_DOMAIN = "validation_evidence_execution/v1"


def _checks(extra: str = "") -> dict[str, bool]:
    source = f"{_SOURCE}\n{extra}\n" if extra else _SOURCE
    return dict(_guard(source, manifest=architecture.CURRENT_EXECUTION_EVIDENCE_MANIFEST))


def _future_checks(
    monkeypatch: pytest.MonkeyPatch,
    extra: str,
    manifest: architecture.ExecutionEvidenceManifest,
) -> dict[str, bool]:
    monkeypatch.setattr(architecture, "_SUPPORTED_MANIFESTS", (manifest,))
    return dict(_guard(f"{_BASELINE_SOURCE}\n{extra}\n", manifest=manifest))


def _replace_function_once(source: str, function_name: str, old: str, new: str) -> str:
    function = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    segment = ast.get_source_segment(source, function)
    assert segment is not None and segment.count(old) == 1
    return source.replace(segment, segment.replace(old, new, 1), 1)


def test_phase_e_accepts_only_the_exact_executor_attestation_surface() -> None:
    checks = _checks()

    assert all(checks.values()), [name for name, passed in checks.items() if not passed]
    manifest = architecture.CURRENT_EXECUTION_EVIDENCE_MANIFEST
    assert manifest.phase == "2E"
    assert manifest.projection_classes == frozenset(
        {
            "ExecutionInstanceProjection",
            "ExecutionIdentityProjection",
            "SubmittedJobsProjection",
            "ExecutionStartProjection",
            "WorkerIdentityProjection",
            "ReturnedResultProjection",
            "ResultBatchProjection",
            "ExecutionCompletionProjection",
            "ReturnedResultsProjection",
            "WorkerResultOrderProjection",
            "ExecutorAttestationProjection",
        }
    )
    assert manifest.identity_domains == (
        *architecture.PHASE_C2_MANIFEST.identity_domains,
        (
            "executor_attestation_id",
            "validation_evidence_executor_attestation/v1",
        ),
    )
    assert manifest.added_classes - architecture.PHASE_C2_MANIFEST.added_classes == frozenset(
        {"ExecutorAttestationProjection"}
    )
    assert manifest.added_functions - architecture.PHASE_C2_MANIFEST.added_functions == (
        architecture._STAGE_E_HELPERS
        | {
            "decode_executor_attestation_projection",
            "executor_attestation_id",
            "validate_stage2e_executor_attestation",
        }
    )
    assert manifest.decoder_functions - architecture.PHASE_C2_MANIFEST.decoder_functions == (
        frozenset({"decode_executor_attestation_projection"})
    )
    assert manifest.reader_methods - architecture.PHASE_C2_MANIFEST.reader_methods == frozenset(
        {
            "callable_projection",
            "executor_implementation",
            "returned_results_projection",
            "submitted_jobs_projection",
            "worker_result_order_projection",
        }
    )
    assert manifest.added_annassigns - architecture.PHASE_C2_MANIFEST.added_annassigns == frozenset(
        {"_E_AU_CTX", "_E_EI_CTX", "_E_ID_CTX", "_E_NS_CTX", "_E_RT_CTX", "_E_SR_CTX"}
    )
    assert manifest.added_import_occurrences[
        len(architecture.PHASE_C2_MANIFEST.added_import_occurrences) :
    ] == (
        architecture.ExecutionEvidenceImport(
            architecture._EVIDENCE_MODULE, "ValidationAuthorityProjection"
        ),
        architecture.ExecutionEvidenceImport(
            architecture._RETURNED_MODULE,
            "validate_returned_run_projection_shape",
        ),
    )
    assert manifest.added_type_aliases == architecture.PHASE_C2_MANIFEST.added_type_aliases
    assert manifest.projection_classes == frozenset(architecture._STAGE_2D2_SCHEMAS)
    assert manifest.projection_classes.isdisjoint(
        {
            "JobResultMappingProjection",
            "CalibrationCandidatePairProjection",
            "CalibrationSelectionProjection",
        }
    )
    assert architecture._STAGE_2D2_FIELDS["ReturnedResultsProjection"] == (
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
    assert architecture._STAGE_2D2_FIELDS["WorkerResultOrderProjection"] == (
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
    assert architecture._STAGE_2D2_SCHEMAS["ReturnedResultsProjection"] == (
        "broader-replication-returned-results/v1"
    )
    assert architecture._STAGE_2D2_SCHEMAS["WorkerResultOrderProjection"] == (
        "broader-replication-worker-result-order/v1"
    )
    assert architecture._STAGE_2D2_FIELDS["ExecutorAttestationProjection"] == (
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
    assert architecture._STAGE_2D2_SCHEMAS["ExecutorAttestationProjection"] == (
        "broader-replication-executor-attestation/v1"
    )
    assert architecture.PHASE_C2_MANIFEST.projection_classes == manifest.projection_classes - {
        "ExecutorAttestationProjection"
    }
    assert "executor_attestation_id" not in dict(architecture.PHASE_C2_MANIFEST.identity_domains)
    e_boundary_mutations = "\n".join(
        (
            "AliasExecutorAttestation = ExecutorAttestationProjection",
            "def job_result_mapping_id(value: object) -> str:\n"
            "    return protocol_hash('validation_evidence_job_result_mapping/v1', value)",
            "def result_aggregate_id(value: object) -> str:\n"
            "    return protocol_hash('validation_evidence_result_aggregate/v1', value)",
            "def second_executor_attestation_id(value: object) -> str:\n"
            "    return protocol_hash('validation_evidence_executor_attestation/v1', value)",
            "def second_attestation_domain(value: object) -> str:\n"
            "    return protocol_hash('validation_evidence_executor_attestation/v2', value)",
            "def calibration_candidate_pair_id(value: object) -> str:\n"
            "    return protocol_hash("
            "'validation_evidence_calibration_candidate_pair/v1', value)",
            "result_order_sha256 = _identity_digest",
            "def promote_historical_attestation() -> object:\n"
            "    return ActualExecutorAttestation()",
            "def validate_stage2d2_result_batch_completion(extra=None) -> None:\n    pass",
            "def validate_stage2d2_result_aggregates(*args, **kwargs) -> None:\n    pass",
            "def validate_stage2e_executor_attestation(*args, **kwargs) -> None:\n    pass",
        )
    )
    mutated_checks = _checks(e_boundary_mutations)
    assert mutated_checks["no-projection-or-function-alias"] is False
    assert mutated_checks["exact-identity-domain-surface"] is False
    assert mutated_checks["no-stage-2e-or-later-surface"] is False
    assert mutated_checks["no-unapproved-identity-surface"] is False
    assert mutated_checks["no-historical-task-c-identity"] is False
    assert mutated_checks["no-historical-task-c-attestation"] is False
    assert mutated_checks["no-live-capability-or-registry"] is False
    assert mutated_checks["exact-phase-c1-completion-signature"] is False
    assert mutated_checks["exact-phase-c2-aggregate-signature"] is False
    assert mutated_checks["exact-phase-e-attestation-signatures"] is False


def test_phase_b_freezes_one_batch_call_and_every_added_import_reference() -> None:
    call = (
        "        accepted_payloads = validate_returned_run_batch(\n"
        "            returned_runs_in_actual_delivery_order="
        "returned_runs_in_actual_delivery_order,\n"
        "            returned_domains_in_actual_delivery_order="
        "returned_domains_in_actual_delivery_order,\n"
        "        )\n"
    )
    duplicate_call = (
        call + "        extra_acceptance = validate_returned_run_batch(\n"
        "            returned_runs_in_actual_delivery_order="
        "returned_runs_in_actual_delivery_order,\n"
        "            returned_domains_in_actual_delivery_order="
        "returned_domains_in_actual_delivery_order,\n"
        "        )\n"
    )
    reference_mutation = _SOURCE.replace(
        call,
        f"{call}        batch_function = validate_returned_run_batch\n"
        "        domain_type = BroaderArmRun\n",
        1,
    ).replace(
        "    ReturnedRunProjectionError,\n",
        "    ReturnedRunProjectionError,\n"
        "    result_payload_sha256 as forbidden_single_payload_hash,\n",
        1,
    )
    mutations = (
        _SOURCE.replace(call, duplicate_call, 1),
        _SOURCE.replace(call, "        accepted_payloads = ()\n", 1),
        reference_mutation,
    )
    assert all(mutated != _SOURCE for mutated in mutations)
    for mutated in mutations:
        checks = dict(_guard(mutated, manifest=architecture.CURRENT_EXECUTION_EVIDENCE_MANIFEST))
        assert checks["exact-resolved-added-import-surface"] is False


@pytest.mark.parametrize(
    "parameter",
    ("job_result_mapping", "mapping_validator", "decoder_factory"),
)
def test_phase_b_rejects_caller_mapping_and_factory_parameters(parameter: str) -> None:
    closing = (
        "    carried_returned_result_ids_in_actual_delivery_order: tuple[str, ...],\n"
        ") -> tuple[tuple[ReturnedResultObservation, ...], JobResultMapping]:"
    )
    mutated = _SOURCE.replace(
        closing,
        "    carried_returned_result_ids_in_actual_delivery_order: tuple[str, ...],\n"
        f"    {parameter}: object,\n"
        ") -> tuple[tuple[ReturnedResultObservation, ...], JobResultMapping]:",
        1,
    )

    assert mutated != _SOURCE
    assert (
        dict(_guard(mutated, manifest=architecture.CURRENT_EXECUTION_EVIDENCE_MANIFEST))[
            "exact-phase-b-function-signatures"
        ]
        is False
    )


def _batch_hypothetical_surfaces(
    cases: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (
            "\n".join(source for source, _check in cases[index : index + 6]),
            tuple(check for _source, check in cases[index : index + 6]),
        )
        for index in range(0, len(cases), 6)
    )


# fmt: off
_HYPOTHETICAL_SURFACE_CASES: tuple[tuple[str, str], ...] = (
        ("Alias = ExecutorAttestationProjection", "no-projection-or-function-alias"),
        ("Alias = ReturnedResultProjection", "no-projection-or-function-alias"),
        ("Alias: object = ExecutionSpecificationProjection", "no-projection-or-function-alias"),
        (
            "from research_decision_engine.benchmarks.broader_runner "
            "import run_arm as harmless\nharmless()",
            "no-forbidden-qualified-call",
        ),
        (
            "from research_decision_engine.benchmarks.broader_runner import run_arm\n"
            "first = run_arm\nsecond = first\nsecond()",
            "no-forbidden-qualified-call",
        ),
        ("__all__ = ('ExecutorAttestationProjection',)", "no-export-surface"),
        (
            "def __getattr__(name: str) -> object:\n    return ExecutionSpecificationProjection",
            "no-module-dynamic-hooks",
        ),
        (
            "def __dir__() -> list[str]:\n    return ['ReturnedResultProjection']",
            "no-module-dynamic-hooks",
        ),
        ("ReturnedResultProjection = type('ReturnedResultProjection', (), {})",
         "no-dynamic-projection-construction"),
        (
            "def second_execution_id(value: object) -> str:\n"
            "    return protocol_hash('validation_evidence_execution/v1', value)",
            "exact-identity-domain-surface",
        ),
        (
            "def decode_hidden(value: object) -> object:\n    return getattr(value, '__dict__')",
            "no-reflective-decoder",
        ),
        (
            "def _d2_exact(projection, decoded, context):\n    context.as_dict()",
            "no-dynamic-indirection",
        ),
        (
            "def _d2_exact(projection, decoded, context):\n    return context.as_dict",
            "no-dynamic-indirection",
        ),
        (
            "def _d2_fail(context, path, detail):\n    raise ValueError",
            "exact-top-level-function-surface",
        ),
        ("class ExecutionStartProjection:\n    pass", "exact-top-level-class-surface"),
        ("_D2_CHECKPOINT: Final = 'shadow'", "exact-annassign-surface"),
        ("type _Stage2D2DecodeContext = object", "exact-type-alias-surface"),
        (
            "def write_evidence() -> None:\n    Path('evidence.json').write_text('{}')",
            "no-evidence-writer",
        ),
        ("def issue_live_capability() -> object:\n"
         "    return _allocate_production_plan_capability()", "no-live-capability-or-registry"),
        ("class ExecutionEvidenceReader:\n    pass", "no-reader-or-persistence"),
        ("class ExecutorAttestationProjection:\n    pass", "exact-top-level-class-surface"),
        ("class ShadowExecutorAttestationProjection:\n    pass", "exact-top-level-class-surface"),
        (
            "def dynamic_attestation_factory():\n"
            "    return make_dataclass('DynamicExecutorAttestationProjection', [])",
            "no-dynamic-projection-construction",
        ),
        ("class ResultBatchProjection:\n    pass", "exact-top-level-class-surface"),
        ("class ExecutionCompletionProjection:\n    pass", "exact-top-level-class-surface"),
        ("class ReturnedResultsProjection:\n    pass", "exact-top-level-class-surface"),
        ("class WorkerResultOrderProjection:\n    pass", "exact-top-level-class-surface"),
        ("class JobResultMappingProjection:\n    pass", "no-future-projection-surface"),
        ("class CalibrationCandidatePairProjection:\n    pass", "no-stage-2e-or-later-surface"),
        ("class CalibrationSelectionProjection:\n    pass", "no-stage-2e-or-later-surface"),
        (
            "def calibration_candidate_pair_id(value: object) -> str:\n"
            "    return protocol_hash("
            "'validation_evidence_calibration_candidate_pair/v1', value)",
            "no-stage-2e-or-later-surface",
        ),
        ("returned_result_id = _returned_result_identity", "no-historical-task-c-identity"),
        (
            "def promote_historical_attestation() -> object:\n"
            "    return ActualExecutorAttestation()",
            "no-historical-task-c-attestation",
        ),
        (
            "def issue_attestation_signing_capability() -> object:\n"
            "    return object()",
            "no-live-capability-or-registry",
        ),
        (
            "def second_returned_result_id(value: object) -> str:\n"
            "    return protocol_hash('validation_evidence_returned_result/v1', value)",
            "exact-identity-domain-surface",
        ),
        (
            "def job_result_mapping_id(value: object) -> str:\n"
            "    return protocol_hash('validation_evidence_job_result_mapping/v1', value)",
            "exact-identity-domain-surface",
        ),
    )
# fmt: on


@pytest.mark.parametrize(
    ("source", "intended_check"),
    _HYPOTHETICAL_SURFACE_CASES,
)
def test_hypothetical_surfaces_fail_their_semantic_boundary(
    source: str,
    intended_check: str,
) -> None:
    assert _checks(source)[intended_check] is False


@pytest.mark.parametrize(
    ("source", "intended_checks"),
    _batch_hypothetical_surfaces(_HYPOTHETICAL_SURFACE_CASES),
    ids=(
        "aliases-calls-and-export",
        "hooks-dynamic-construction-identity-and-reflection",
        "indirection-surfaces-and-evidence-writer",
        "capability-reader-attestation-and-result-batch",
        "completion-aggregate-and-future-projections",
        "future-identity-history-and-capability",
    ),
)
def test_batched_hypothetical_surfaces_fail_all_semantic_boundaries(
    source: str,
    intended_checks: tuple[str, ...],
) -> None:
    checks = _checks(source)
    assert all(checks[intended_check] is False for intended_check in intended_checks)


def test_one_argument_type_check_is_not_misclassified_as_reflection() -> None:
    source = "def decode_hypothetical(value: object) -> type:\n    return type(value)"

    assert _checks(source)["no-reflective-decoder"] is True


def test_stage_e_nested_type_boundary_rejects_each_unsafe_source_mutation() -> None:
    def replace(function: str, before: str, after: str, source: str = _SOURCE) -> str:
        return _replace_function_once(source, function, before, after)

    shape = "    projection = _stage2e_type(value, expected, context, path)\n"
    attested = "    attested_executor_implementation_mapping = _stage2e_projection_mapping(\n"
    owned = (
        "    elif expected is ExecutorImplementationProjection:\n"
        "        mapping = ExecutorImplementationProjection.as_dict(\n"
        "            cast(ExecutorImplementationProjection, projection)\n"
        "        )\n"
    )
    deep = (
        "    elif expected is ExecutorImplementationProjection:\n"
        "        implementation = cast(ExecutorImplementationProjection, projection)\n"
        "        _stage2e_projection_shape(\n"
        "            implementation.callable,\n"
        "            CallableProjection,\n"
        "            context,\n"
        '            f"{path}.callable",\n'
        "        )\n"
    )
    early_hash = replace(
        "executor_attestation_id",
        "    mapping = _stage2e_projection_mapping(\n",
        "    identity = protocol_hash('validation_evidence_executor_attestation/v1', {})\n"
        "    mapping = _stage2e_projection_mapping(\n",
    )
    mutations = (
        (
            "removed exact check",
            replace("_stage2e_projection_shape", shape, "    projection = value\n"),
            "exact-stage-e-type-before-touch",
        ),
        (
            "isinstance acceptance",
            replace(
                "_stage2e_type",
                "    if type(value) is not expected:\n",
                "    if not isinstance(value, expected):\n",
            ),
            "exact-stage-e-type-before-touch",
        ),
        (
            "comparison before check",
            replace(
                "validate_stage2e_executor_attestation",
                attested,
                "    executor_attestation.executor_implementation "
                "== expected_executor_implementation\n"
                f"{attested}",
            ),
            "exact-stage-e-type-before-touch",
        ),
        (
            "conversion before check",
            replace(
                "validate_stage2e_executor_attestation",
                attested,
                f"    executor_attestation.executor_implementation.as_dict()\n{attested}",
            ),
            "exact-stage-e-type-before-touch",
        ),
        (
            "arbitrary as_dict",
            replace(
                "_stage2e_projection_mapping",
                owned,
                "    elif expected is ExecutorImplementationProjection:\n"
                "        mapping = projection.as_dict()\n",
            ),
            "stage-e-explicit-type-owned-serialization",
        ),
        (
            "mapping coercion",
            replace(
                "_stage2e_projection_mapping",
                shape.replace("_stage2e_type", "_stage2e_projection_shape"),
                "    projection = expected(**dict(value))\n",
            ),
            "stage-e-explicit-type-owned-serialization",
        ),
        (
            "subclass acceptance",
            replace(
                "_stage2e_type",
                "    if type(value) is not expected:\n",
                "    if type(value) is not expected and not issubclass(type(value), expected):\n",
            ),
            "exact-stage-e-type-before-touch",
        ),
        (
            "omitted deep validation",
            replace(
                "_stage2e_projection_shape",
                deep,
                "    elif expected is ExecutorImplementationProjection:\n        pass\n",
            ),
            "stage-e-explicit-type-owned-serialization",
        ),
        (
            "reflective serialization",
            replace(
                "_stage2e_projection_mapping",
                owned,
                "    elif expected is ExecutorImplementationProjection:\n"
                "        mapping = vars(projection)\n",
            ),
            "stage-e-explicit-type-owned-serialization",
        ),
        (
            "ID hash before validation",
            replace(
                "executor_attestation_id",
                '    return protocol_hash("validation_evidence_executor_attestation/v1", mapping)',
                "    return identity",
                early_hash,
            ),
            "stage-e-id-shape-before-hash",
        ),
    )
    for label, mutated, intended_check in mutations:
        assert mutated != _SOURCE, label
        checks = dict(_guard(mutated, manifest=architecture.CURRENT_EXECUTION_EVIDENCE_MANIFEST))
        assert checks[intended_check] is False, label


@pytest.mark.parametrize(
    "case",
    (
        "catch-no-internal-shape-error-at-3n12",
        "leak-raw-returned-run-projection-error",
        "map-deep-shape-error-to-3n15",
        "validate-later-deep-shape-before-earlier-3n",
        "hash-attestation-before-deep-shape",
    ),
)
def test_deep_returned_run_boundary_mutations_have_independent_findings(
    case: str,
) -> None:
    shape_branch = (
        "        try:\n"
        "            validate_returned_run_projection_shape(projection, path=path)\n"
        "        except ReturnedRunProjectionError as error:\n"
        "            _d2_fail(context, error.path, str(error))\n"
    )
    if case == "catch-no-internal-shape-error-at-3n12":
        mutated = _replace_function_once(
            _SOURCE,
            "_stage2e_projection_shape",
            shape_branch,
            "        validate_returned_run_projection_shape(projection, path=path)\n",
        )
        intended_check = "exact-stage-e-type-before-touch"
    elif case == "leak-raw-returned-run-projection-error":
        mutated = _replace_function_once(
            _SOURCE,
            "_stage2e_projection_shape",
            "            _d2_fail(context, error.path, str(error))\n",
            "            raise error\n",
        )
        intended_check = "exact-stage-e-type-before-touch"
    elif case == "map-deep-shape-error-to-3n15":
        mutated = _replace_function_once(
            _SOURCE,
            "_stage2e_projection_shape",
            "            _d2_fail(context, error.path, str(error))\n",
            "            _d2_fail(_E_ID_CTX, error.path, str(error))\n",
        )
        intended_check = "exact-stage-e-type-before-touch"
    elif case == "validate-later-deep-shape-before-earlier-3n":
        mutated = _replace_function_once(
            _SOURCE,
            "validate_stage2e_executor_attestation",
            "    accepted_observations, expected_mapping = validate_stage2d2_result_aggregates(\n",
            "    validate_returned_run_projection_shape(\n"
            "        executor_attestation.returned_results.results_in_submission_order[0][1]\n"
            "    )\n"
            "    accepted_observations, expected_mapping = validate_stage2d2_result_aggregates(\n",
        )
        intended_check = "exact-stage-e-type-before-touch"
    else:
        mutated = _replace_function_once(
            _SOURCE,
            "executor_attestation_id",
            "    mapping = _stage2e_projection_mapping(\n",
            "    identity = protocol_hash(\n"
            '        "validation_evidence_executor_attestation/v1", {}\n'
            "    )\n"
            "    mapping = _stage2e_projection_mapping(\n",
        )
        mutated = _replace_function_once(
            mutated,
            "executor_attestation_id",
            '    return protocol_hash("validation_evidence_executor_attestation/v1", mapping)',
            "    return identity",
        )
        intended_check = "stage-e-id-shape-before-hash"
    assert mutated != _SOURCE
    checks = dict(_guard(mutated, manifest=architecture.CURRENT_EXECUTION_EVIDENCE_MANIFEST))
    assert checks[intended_check] is False


@pytest.mark.parametrize(
    ("class_name", "method_name", "shadow"),
    (
        (
            "ExecutionInstanceProjection",
            "as_dict",
            "    def as_dict(self):\n        return {}\n\n",
        ),
        (
            "_ExecutionEvidenceDecoder",
            "closed",
            "    def closed(self, names):\n        return self\n\n",
        ),
        (
            "ExecutionInstanceProjection",
            "as_dict",
            "    as_dict = lambda self: {}\n\n",
        ),
    ),
)
def test_added_class_member_shadows_fail_exact_body_surface(
    class_name: str,
    method_name: str,
    shadow: str,
) -> None:
    class_start = _SOURCE.index(f"class {class_name}:")
    insertion = _SOURCE.index(f"    def {method_name}", class_start)
    mutated = f"{_SOURCE[:insertion]}{shadow}{_SOURCE[insertion:]}"

    checks = dict(_guard(mutated, manifest=architecture.CURRENT_EXECUTION_EVIDENCE_MANIFEST))

    assert checks["exact-added-class-body-surface"] is False


def test_future_manifests_close_indirect_hash_reflection_state_and_class_bypasses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = architecture.PHASE_G_MANIFEST._replace(
        phase="2D.2A",
        added_functions=frozenset({"execution_id"}),
        identity_domains=(("execution_id", _EXECUTION_DOMAIN),),
    )
    identity_class = identity._replace(added_classes=frozenset({"HashProbe"}))
    probe = architecture.PHASE_G_MANIFEST._replace(
        phase="2D.2A", added_functions=frozenset({"future_probe"})
    )
    decoder = probe._replace(
        added_functions=frozenset({"decode_probe"}),
        decoder_functions=frozenset({"decode_probe"}),
    )
    # fmt: off
    cases = (
        ("def execution_id(value):\n protocol_hash('" + _EXECUTION_DOMAIN + "', value)\n"
         " return protocol_hash('" + _EXECUTION_DOMAIN + "', value)", identity,
         "exact-identity-domain-surface"),
        ("def execution_id(value):\n digest = protocol_hash\n"
         " return digest('" + _EXECUTION_DOMAIN + "', value)", identity,
         "exact-identity-domain-surface"),
        ("def execution_id(value):\n return protocol_hash("
         "domain='" + _EXECUTION_DOMAIN + "', projection=value)", identity,
         "exact-identity-domain-surface"),
        ("def execution_id(value):\n protocol_hash('unknown-domain/v1', value)\n"
         " return protocol_hash('" + _EXECUTION_DOMAIN + "', value)", identity,
         "exact-identity-domain-surface"),
        ("class HashProbe:\n def digest(self, value):\n"
         "  return protocol_hash('unknown-domain/v1', value)\n"
         "def execution_id(value):\n return protocol_hash('" + _EXECUTION_DOMAIN + "', value)",
         identity_class, "exact-identity-domain-surface"),
        ("def decode_probe(value):\n inspect.getmembers(value)\n dir(value)\n"
         " return inspect.getattr_static(value, 'field')",
         decoder, "no-reflective-decoder"),
        ("def future_probe():\n _ProductionPreparationCapability()\n"
         " _issue_execution_specification(None)\n return ActualExecutorAttestation()",
         probe, "no-live-capability-or-registry"),
        ("def future_probe():\n _EXECUTION_SPECIFICATIONS.setdefault('x', None)\n"
         " _EXECUTOR_ATTESTATIONS['x'] = None\n _RESULT_BATCH_ATTESTATIONS['x'] = None",
         probe, "no-live-capability-or-registry"),
        ("def future_probe():\n return __build_class__(lambda: None, 'Projection')",
         probe, "no-dynamic-projection-construction"),
        ("def future_probe():\n datetime.now()\n CodeType()\n FunctionType()\n"
         " callable_projection(None)\n return _seal_production_component_callable(None)",
         probe, "closed-imported-call-surface"),
        ("def future_probe():\n return callable_projection",
         probe, "closed-imported-reference-surface"),
    )
    # fmt: on
    for source, manifest, intended_check in cases:
        checks = _future_checks(monkeypatch, source, manifest)
        assert checks["supported-phase-manifest"] and checks["legacy-ast-fingerprint"]
        assert checks[intended_check] is False
    auxiliary = architecture.PHASE_G_MANIFEST._replace(
        phase="2D.2A",
        added_classes=frozenset({"_ExecutionEvidenceDecoder"}),
        added_functions=frozenset({"validate_stage2d2_execution_foundations"}),
        reader_methods=frozenset({"runtime"}),
        auxiliary_hashes=architecture.PHASE_A_MANIFEST.auxiliary_hashes,
    )
    source = (
        "@dataclass(frozen=True, slots=True)\nclass _ExecutionEvidenceDecoder:\n"
        " def runtime(self, value):\n"
        "  protocol_hash('pytest_interpreter_identity/v1', value)\n"
        "  protocol_hash('pytest_platform_identity/v1', value)\n"
        "def validate_stage2d2_execution_foundations(value):\n"
        " return protocol_hash('validation_evidence_runtime/v1', value)"
    )
    assert all(_future_checks(monkeypatch, source, auxiliary).values())
