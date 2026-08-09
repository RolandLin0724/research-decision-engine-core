# ruff: noqa: SIM905
from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError, fields, replace
from typing import Any, Final, Literal, cast

import pytest

from research_decision_engine.benchmarks import broader_execution as ex
from research_decision_engine.benchmarks import broader_returned_run as returned
from research_decision_engine.benchmarks.broader_protocol import protocol_hash
from research_decision_engine.benchmarks.broader_validation_evidence import (
    EVIDENCE_CONTRACT_CHECKPOINT,
    CallableProjection,
    FileProjection,
    ImplementationProjection,
    RuntimeProjection,
    ValidationAuthorityProjection,
)
from tests.test_broader_p2_result_aggregates import _attach_c2, c2_kwargs
from tests.test_broader_p2_result_batch_completion import _attach_c1

CHECKPOINT: Final = "89c0b4fadba33b9fd9a257b43eacf476b7779d59"
STUDY: Final = "broader-closed-loop-replication/v1"
SCHEMA: Final = "broader-replication-executor-attestation/v1"
DOMAIN: Final = "validation_evidence_executor_attestation/v1"
BAD: Final = "f" * 64
VALID_ATTESTATION_ID: Final = "c24724266e7985f7bedef16467cbec5b3d3a8e4d038e398d9ce16227f5f583b6"
HOOK_NAMES: Final = (
    "as_dict",
    "to_dict",
    "__eq__",
    "__ne__",
    "__getattr__",
    "__iter__",
    "__hash__",
    "__bool__",
)

type _NestedPath = tuple[str | int, ...]
type _HookCounts = dict[str, int]
type _LookalikeShape = Literal["conversion", "mapping", "attributes", "subclass"]

FIELD_NAMES: Final = tuple(
    (
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
    ).split()  # noqa: SIM905 - compact immutable contract table
)
TYPE_NAMES: Final = tuple(
    (
        "tuple[str,...] int str int str str str str str str str Literal['success'] "
        "str ExecutorImplementationProjection str Literal['serial','thread_pool'] "
        "ImplementationProjection JobResultMapping str tuple[str,...] str str "
        f"Literal['{CHECKPOINT}'] str Literal['input_order','completion_order'] "
        "tuple[str,...] ReturnedResultsProjection str str RuntimeProjection str str "
        f"Literal['{SCHEMA}'] str Literal['{STUDY}'] SubmittedJobsProjection str "
        "Literal['production'] str str WorkerResultOrderProjection str"
    ).split()  # noqa: SIM905 - compact immutable relation table
)


def h(number: int) -> str:
    return f"{number:064x}"


def _callable(number: int, name: str) -> tuple[CallableProjection, str]:
    source = FileProjection(17, rf"C:\rde\{name}.py", h(number + 1))
    projection = CallableProjection(h(number), "function", "tests.stage2e", name, source)
    return projection, protocol_hash("validation_evidence_callable/v1", projection.as_dict())


def _rebind_specification(kwargs: dict[str, Any], specification_id: str) -> None:
    execution = replace(kwargs["execution"], execution_specification_id=specification_id)
    execution_id = ex.execution_id(execution)
    submitted = replace(
        kwargs["submitted_jobs"],
        execution_id=execution_id,
        execution_specification_id=specification_id,
    )
    start = replace(
        kwargs["execution_start"],
        execution_id=execution_id,
        execution_specification_id=specification_id,
    )
    workers = tuple(
        (
            changed := replace(worker, execution_specification_id=specification_id),
            ex.worker_identity(changed),
        )
        for worker, _identity in kwargs["workers_in_actual_delivery_order"]
    )
    returned = tuple(
        replace(
            projection,
            execution_id=execution_id,
            execution_specification_id=specification_id,
        )
        for projection in kwargs["returned_result_projections_in_actual_delivery_order"]
    )
    returned_ids = tuple(ex.returned_result_id(projection) for projection in returned)
    kwargs.update(
        expected_execution=execution,
        execution=execution,
        carried_execution_id=execution_id,
        expected_submitted_jobs=submitted,
        submitted_jobs=submitted,
        carried_submitted_jobs_sha256=ex.submitted_jobs_sha256(submitted),
        expected_execution_start=start,
        execution_start=start,
        carried_execution_start_id=ex.execution_start_id(start),
        expected_workers_in_actual_delivery_order=tuple(worker for worker, _id in workers),
        workers_in_actual_delivery_order=workers,
        returned_result_projections_in_actual_delivery_order=returned,
        carried_returned_result_ids_in_actual_delivery_order=returned_ids,
    )
    kwargs.update(_attach_c2(_attach_c1(kwargs)))


def valid_kwargs() -> dict[str, Any]:
    kwargs = c2_kwargs()
    execution = kwargs["execution"]
    submitted = kwargs["submitted_jobs"]

    first_worker = kwargs["workers_in_actual_delivery_order"][0]
    workers = (first_worker, first_worker)
    kwargs["expected_workers_in_actual_delivery_order"] = (
        first_worker[0],
        first_worker[0],
    )
    kwargs["workers_in_actual_delivery_order"] = workers

    job_callable, job_callable_id = _callable(100, "job")
    executor_callable, executor_callable_id = _callable(110, "executor")
    executor_implementation = ex.ExecutorImplementationProjection(
        executor_callable,
        executor_callable_id,
        submitted.implementation.implementation_tree_sha256,
    )
    executor_implementation_id = protocol_hash(
        "validation_evidence_executor_implementation/v1",
        executor_implementation.as_dict(),
    )
    configuration = ex.ExecutorConfigurationProjection(
        job_callable_id,
        "serial",
        "input_order",
        "serial_call_in_input_order",
        None,
        1,
    )
    configuration_sha256 = protocol_hash(
        "validation_evidence_executor_configuration/v1",
        configuration.as_dict(),
    )
    submitted = replace(submitted, configuration_sha256=configuration_sha256)
    kwargs.update(
        expected_submitted_jobs=submitted,
        submitted_jobs=submitted,
        carried_submitted_jobs_sha256=ex.submitted_jobs_sha256(submitted),
    )

    purpose: Literal["smoke_validation"] = "smoke_validation"
    namespace = f"{STUDY}/production/{purpose}"
    specification = ex.ExecutionSpecificationProjection(
        callable=job_callable,
        callable_identity=job_callable_id,
        configuration=configuration,
        configuration_sha256=configuration_sha256,
        evidence_contract_checkpoint=EVIDENCE_CONTRACT_CHECKPOINT,
        expected_completion=ex.ExecutionExpectedCompletionProjection(len(submitted.jobs)),
        execution_purpose=purpose,
        executor_kind="serial",
        executor_implementation=executor_implementation,
        executor_implementation_identity=executor_implementation_id,
        implementation=submitted.implementation,
        normalized_execution_namespace=namespace,
        protocol_checkpoint=CHECKPOINT,
        result_delivery_mode="input_order",
        role="primary_smoke",
        runtime=submitted.runtime,
        runtime_identity=submitted.runtime_identity,
        scheduling_mode="serial_call_in_input_order",
        specification_issuer_identity=h(120),
        submitted_jobs=submitted.jobs,
        timeout_ms=None,
        validation_run_id=execution.validation_run_id,
        worker_count=1,
    )
    specification_id = protocol_hash(
        "validation_evidence_execution_specification/v1",
        specification.as_dict(),
    )
    _rebind_specification(kwargs, specification_id)
    execution = kwargs["execution"]
    submitted = kwargs["submitted_jobs"]
    completion = kwargs["execution_completion"]
    completion_id = kwargs["carried_execution_completion_id"]
    returned_results = kwargs["returned_results"]
    worker_order = kwargs["worker_result_order"]
    first_worker = kwargs["workers_in_actual_delivery_order"][0]
    authority = ValidationAuthorityProjection(
        EVIDENCE_CONTRACT_CHECKPOINT,
        h(121),
        submitted.implementation,
        h(122),
        ("pytest-junit.xml", "validation_bindings.json"),
        specification_id,
        (h(123), h(124)),
        CHECKPOINT,
        h(125),
        h(126),
        submitted.runtime,
        submitted.runtime_identity,
        execution.validation_run_id,
    )
    accepted_job_ids = tuple(reversed(tuple(job.submitted_job_id for job in submitted.jobs)))
    result_batch = kwargs["result_batch"]
    attestation = ex.ExecutorAttestationProjection(
        accepted_job_ids=accepted_job_ids,
        actual_worker_count=1,
        completed_at=completion.completed_at,
        configured_worker_count=1,
        configuration_sha256=configuration_sha256,
        evidence_contract_checkpoint=EVIDENCE_CONTRACT_CHECKPOINT,
        execution_completion_id=completion_id,
        execution_id=kwargs["carried_execution_id"],
        execution_purpose=purpose,
        execution_specification_id=execution.execution_specification_id,
        execution_start_id=kwargs["carried_execution_start_id"],
        execution_status="success",
        executor_implementation_identity=executor_implementation_id,
        executor_implementation=executor_implementation,
        execution_instance_identity=kwargs["carried_execution_instance_identity"],
        executor_kind="serial",
        implementation=submitted.implementation,
        job_result_mapping=kwargs["job_result_mapping"],
        normalized_execution_namespace=namespace,
        observed_worker_ids=(first_worker[1],),
        oracle_binding_id=execution.oracle_binding_id,
        oracle_execution_id=execution.oracle_execution_id,
        protocol_checkpoint=CHECKPOINT,
        result_batch_id=kwargs["carried_result_batch_id"],
        result_delivery_mode="input_order",
        result_payload_sha256_in_delivery_order=(
            result_batch.result_payload_sha256_in_delivery_order
        ),
        returned_results=returned_results,
        returned_results_sha256=kwargs["carried_returned_results_sha256"],
        role=execution.role,
        runtime=submitted.runtime,
        runtime_identity=submitted.runtime_identity,
        scheduling_mode="serial_call_in_input_order",
        schema_version=SCHEMA,
        started_at=kwargs["execution_start"].started_at,
        study_id=STUDY,
        submitted_jobs=submitted,
        submitted_jobs_sha256=kwargs["carried_submitted_jobs_sha256"],
        trust_domain="production",
        validation_authority_id=execution.validation_authority_id,
        validation_run_id=execution.validation_run_id,
        worker_result_order=worker_order,
        worker_result_order_sha256=kwargs["carried_worker_result_order_sha256"],
    )
    kwargs.update(
        expected_validation_authority=authority,
        expected_execution_specification=specification,
        expected_executor_implementation=executor_implementation,
        expected_executor_implementation_identity=executor_implementation_id,
        accepted_job_ids_in_actual_acceptance_order=accepted_job_ids,
        executor_attestation=attestation,
        carried_executor_attestation_id=ex.executor_attestation_id(attestation),
    )
    return kwargs


def invoke(kwargs: dict[str, Any]) -> ex.ExecutorAttestationProjection:
    return ex.validate_stage2e_executor_attestation(**kwargs)


def assert_failure(kwargs: dict[str, Any], code: str) -> ex.ExecutorProvenanceError:
    with pytest.raises(ex.ExecutorProvenanceError) as captured:
        invoke(kwargs)
    assert captured.value.error_code == code
    assert not getattr(captured.value, "workload_started", False)
    assert not getattr(captured.value, "scoring_entered", False)
    assert not getattr(captured.value, "evidence_checkpointed", False)
    return captured.value


def _nested_value(value: object, path: _NestedPath) -> object:
    current = value
    for part in path:
        if type(part) is str:
            current = getattr(current, part)
        else:
            assert type(current) is tuple
            current = current[cast(int, part)]
    return current


def _nested_replace(value: object, path: _NestedPath, replacement: object) -> object:
    if not path:
        return replacement
    part, *remaining = path
    if type(part) is str:
        nested = getattr(value, part)
        return replace(
            cast(Any, value),
            **{part: _nested_replace(nested, tuple(remaining), replacement)},
        )
    assert type(value) is tuple
    changed = list(value)
    index = cast(int, part)
    changed[index] = _nested_replace(changed[index], tuple(remaining), replacement)
    return tuple(changed)


def _hook_lookalike(
    valid: object,
    shape: _LookalikeShape = "conversion",
) -> tuple[object, _HookCounts]:
    counts = dict.fromkeys(HOOK_NAMES, 0)

    def recorded(name: str, result: object) -> object:
        def hook(*_args: object) -> object:
            counts[name] += 1
            return result

        return hook

    try:
        as_dict_result = cast(Any, valid).as_dict()
    except AttributeError:
        as_dict_result = {}
    namespace: dict[str, object] = {
        "__slots__": () if shape == "subclass" else ("__dict__",),
        "as_dict": recorded("as_dict", as_dict_result),
        "to_dict": recorded("to_dict", {}),
        "__eq__": recorded("__eq__", True),
        "__ne__": recorded("__ne__", False),
        "__getattr__": recorded("__getattr__", None),
        "__iter__": recorded("__iter__", iter(())),
        "__hash__": recorded("__hash__", 1),
        "__bool__": recorded("__bool__", True),
    }
    if shape == "subclass":
        lookalike_type = type(
            f"CallerDefined{type(valid).__name__}Subclass",
            (type(valid),),
            namespace,
        )
        lookalike = lookalike_type(
            *(getattr(valid, field.name) for field in fields(cast(Any, valid)))
        )
    elif shape == "mapping":
        namespace["__slots__"] = ()
        lookalike_type = type("CallerDefinedProjectionMapping", (dict,), namespace)
        lookalike = lookalike_type(as_dict_result)
    else:
        lookalike_type = type("CallerDefinedProjectionLookalike", (object,), namespace)
        lookalike = lookalike_type()
        if shape == "attributes":
            for field in fields(cast(Any, valid)):
                object.__setattr__(lookalike, field.name, getattr(valid, field.name))
    assert counts == dict.fromkeys(HOOK_NAMES, 0)
    return lookalike, counts


def _assert_zero_hooks(counts: _HookCounts, case: str) -> None:
    assert counts == dict.fromkeys(HOOK_NAMES, 0), f"{case}: {counts}"


def _assert_stage2e_nested_rejection(
    monkeypatch: pytest.MonkeyPatch,
    *,
    case: str,
    path: _NestedPath,
    code: str,
    error_path: str | tuple[str, ...],
    shape: _LookalikeShape = "conversion",
) -> None:
    kwargs = valid_kwargs()
    attestation = cast(ex.ExecutorAttestationProjection, kwargs["executor_attestation"])
    lookalike, counts = _hook_lookalike(_nested_value(attestation, path), shape)
    kwargs["executor_attestation"] = _nested_replace(attestation, path, lookalike)
    identity_entered = False

    def forbidden_identity(_projection: ex.ExecutorAttestationProjection) -> str:
        nonlocal identity_entered
        identity_entered = True
        raise AssertionError(f"{case}: later executor-attestation identity entered")

    with monkeypatch.context() as scoped:
        scoped.setattr(ex, "executor_attestation_id", forbidden_identity)
        error = assert_failure(kwargs, code)
    error_paths = (error_path,) if type(error_path) is str else error_path
    assert all(expected in str(error) for expected in error_paths), f"{case}: {error}"
    _assert_zero_hooks(counts, case)
    assert identity_entered is False, case


def test_exact_contract_round_trip_domain_and_determinism() -> None:
    attestation = cast(ex.ExecutorAttestationProjection, valid_kwargs()["executor_attestation"])
    assert ex.ExecutorAttestationProjection.__name__ == "ExecutorAttestationProjection"
    assert tuple(field.name for field in fields(attestation)) == FIELD_NAMES
    assert tuple(attestation.as_dict()) == FIELD_NAMES
    annotations = tuple(
        value.replace(", ", ",")
        for value in ex.ExecutorAttestationProjection.__annotations__.values()
    )
    assert annotations == TYPE_NAMES
    assert attestation.schema_version == SCHEMA
    assert ex.decode_executor_attestation_projection(attestation.as_dict()) == attestation
    expected = protocol_hash(DOMAIN, attestation.as_dict())
    assert expected == VALID_ATTESTATION_ID
    assert [ex.executor_attestation_id(attestation) for _ in range(2)] == [expected] * 2


def test_projection_is_frozen_slotted_and_capability_free() -> None:
    attestation = cast(ex.ExecutorAttestationProjection, valid_kwargs()["executor_attestation"])
    assert not hasattr(attestation, "__dict__")
    with pytest.raises(FrozenInstanceError):
        attestation.role = "fixture_primary"  # type: ignore[misc]
    malformed = replace(attestation, implementation=object())  # type: ignore[arg-type]
    with pytest.raises(ex.ExecutorProvenanceError) as captured:
        ex.executor_attestation_id(malformed)
    assert captured.value.error_code == "EXECUTOR_ATTESTATION_ID_MISMATCH"
    malformed_rows = (
        ("returned_results", "results_in_submission_order", ((BAD,),)),
        ("worker_result_order", "results_in_actual_delivery_order", ((0, BAD),)),
    )
    for outer, inner, rows in malformed_rows:
        nested = replace(getattr(attestation, outer), **{inner: rows})
        projection = replace(attestation, **{outer: nested})
        with pytest.raises(ex.ExecutorProvenanceError) as captured:
            ex.executor_attestation_id(projection)
        assert captured.value.error_code == "EXECUTOR_ATTESTATION_ID_MISMATCH"
    assert not any(
        token in ex.ExecutorAttestationProjection.__annotations__
        for token in ("capability", "signature", "calibration_selection_id")
    )


def test_minimal_valid_complete_chain() -> None:
    kwargs = valid_kwargs()
    attestation = cast(ex.ExecutorAttestationProjection, kwargs["executor_attestation"])
    assert type(attestation.executor_implementation) is ex.ExecutorImplementationProjection
    assert type(attestation.implementation) is ImplementationProjection
    assert type(attestation.job_result_mapping) is tuple
    assert type(attestation.returned_results) is ex.ReturnedResultsProjection
    assert type(attestation.runtime) is RuntimeProjection
    assert type(attestation.submitted_jobs) is ex.SubmittedJobsProjection
    assert type(attestation.worker_result_order) is ex.WorkerResultOrderProjection
    assert invoke(kwargs) == attestation
    assert ex.executor_attestation_id(attestation) == VALID_ATTESTATION_ID
    attestation = replace(kwargs["executor_attestation"], execution_id=BAD)
    kwargs["executor_attestation"] = attestation
    kwargs["carried_executor_attestation_id"] = ex.executor_attestation_id(attestation)
    assert_failure(kwargs, "EXECUTION_SPECIFICATION_RELATION_MISMATCH")


EI: Final = "EXECUTOR_IMPLEMENTATION_IDENTITY_MISMATCH"
ID: Final = "EXECUTOR_ATTESTATION_ID_MISMATCH"
MAP: Final = "EXECUTION_JOB_RESULT_MAPPING_MISMATCH"
RA: Final = "EXECUTION_RETURNED_RESULTS_MISMATCH"
RT: Final = "RUNTIME_IDENTITY_MISMATCH"
SJ: Final = "EXECUTION_SUBMITTED_JOBS_MISMATCH"
WO: Final = "EXECUTION_RESULT_ORDER_MISMATCH"

DIRECT_NESTED_BOUNDARY_CASES: Final[tuple[tuple[str, _NestedPath, str], ...]] = (
    ("executor_implementation", ("executor_implementation",), EI),
    ("implementation", ("implementation",), ID),
    ("job_result_mapping", ("job_result_mapping",), MAP),
    ("returned_results", ("returned_results",), RA),
    ("runtime", ("runtime",), RT),
    ("submitted_jobs", ("submitted_jobs",), SJ),
    ("worker_result_order", ("worker_result_order",), WO),
)

DEEP_NESTED_BOUNDARY_CASES: Final[tuple[tuple[str, _NestedPath, str], ...]] = (
    ("executor_implementation.callable", ("executor_implementation", "callable"), EI),
    ("runtime.base_interpreter", ("runtime", "base_interpreter"), RT),
    ("submitted_jobs.jobs[0]", ("submitted_jobs", "jobs", 0), SJ),
    (
        "submitted_jobs.jobs[0].projection",
        ("submitted_jobs", "jobs", 0, "projection"),
        SJ,
    ),
    (
        "submitted_jobs.jobs[0].projection.arm",
        ("submitted_jobs", "jobs", 0, "projection", "arm"),
        SJ,
    ),
    (
        "returned_results.implementation",
        ("returned_results", "implementation"),
        RA,
    ),
    ("returned_results.runtime", ("returned_results", "runtime"), RA),
    (
        "returned_results.results_in_submission_order[0]",
        ("returned_results", "results_in_submission_order", 0),
        RA,
    ),
    (
        "returned_results.results_in_submission_order[0].projection.lineage",
        ("returned_results", "results_in_submission_order", 0, 1, "lineage"),
        RA,
    ),
    (
        "worker_result_order.implementation",
        ("worker_result_order", "implementation"),
        WO,
    ),
    ("worker_result_order.runtime", ("worker_result_order", "runtime"), WO),
    (
        "worker_result_order.results_in_actual_delivery_order[0]",
        ("worker_result_order", "results_in_actual_delivery_order", 0),
        WO,
    ),
    (
        "worker_result_order.results_in_actual_delivery_order[0].worker",
        ("worker_result_order", "results_in_actual_delivery_order", 0, 2),
        WO,
    ),
)

ERROR_PATH_OVERRIDES: Final = {
    "returned_results.results_in_submission_order[0].projection.lineage": (
        "returned_results.results_in_submission_order[0].projection",
        "lineage",
    ),
}

NESTED_SHAPE_CASES: Final[tuple[tuple[str, _LookalikeShape], ...]] = (
    ("conversion_method", "conversion"),
    ("mapping_shaped", "mapping"),
    ("matching_attributes", "attributes"),
    ("projection_subclass", "subclass"),
)


@pytest.mark.parametrize("group", ("direct", "deep", "shapes"))
def test_nested_public_boundary_rejects_before_caller_hooks_or_identity(
    monkeypatch: pytest.MonkeyPatch,
    group: str,
) -> None:
    type BoundaryCase = tuple[
        str,
        _NestedPath,
        str,
        str | tuple[str, ...],
        _LookalikeShape,
    ]
    cases: tuple[BoundaryCase, ...]
    if group == "direct":
        cases = tuple(
            (
                case,
                path,
                code,
                ERROR_PATH_OVERRIDES.get(case, f"executor_attestation.{case}"),
                "conversion",
            )
            for case, path, code in DIRECT_NESTED_BOUNDARY_CASES
        )
    elif group == "deep":
        cases = tuple(
            (
                case,
                path,
                code,
                ERROR_PATH_OVERRIDES.get(case, f"executor_attestation.{case}"),
                "conversion",
            )
            for case, path, code in DEEP_NESTED_BOUNDARY_CASES
        )
    else:
        cases = tuple(
            (
                case,
                ("executor_implementation",),
                EI,
                "executor_attestation.executor_implementation",
                shape,
            )
            for case, shape in NESTED_SHAPE_CASES
        )
    for case, path, code, error_path, shape in cases:
        _assert_stage2e_nested_rejection(
            monkeypatch,
            case=case,
            path=path,
            code=code,
            error_path=error_path,
            shape=shape,
        )


def test_executor_attestation_id_rejects_nested_shapes_before_hooks_or_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity_cases = (
        *((case, path, "conversion") for case, path, _code in DIRECT_NESTED_BOUNDARY_CASES),
        (
            "deep_callable",
            ("executor_implementation", "callable"),
            "conversion",
        ),
        *(
            (case, ("executor_implementation",), shape)
            for case, shape in NESTED_SHAPE_CASES
            if shape != "conversion"
        ),
    )
    for case, path, shape in identity_cases:
        attestation = cast(
            ex.ExecutorAttestationProjection,
            valid_kwargs()["executor_attestation"],
        )
        lookalike, counts = _hook_lookalike(
            _nested_value(attestation, path),
            cast(_LookalikeShape, shape),
        )
        malformed = cast(
            ex.ExecutorAttestationProjection,
            _nested_replace(attestation, path, lookalike),
        )
        hash_entered = False

        def forbidden_hash(_domain: str, _projection: object) -> str:
            nonlocal hash_entered
            hash_entered = True
            raise AssertionError("canonical hash entered")

        with monkeypatch.context() as scoped:
            scoped.setattr(ex, "protocol_hash", forbidden_hash)
            with pytest.raises(ex.ExecutorProvenanceError) as captured:
                ex.executor_attestation_id(malformed)
        assert captured.value.error_code == "EXECUTOR_ATTESTATION_ID_MISMATCH", case
        assert "executor_attestation" in str(captured.value), case
        _assert_zero_hooks(counts, case)
        assert hash_entered is False, case


def _replace_returned_run(
    kwargs: dict[str, Any],
    row_index: int,
    path: _NestedPath,
    replacement: object,
) -> ex.ExecutorAttestationProjection:
    attestation = cast(ex.ExecutorAttestationProjection, kwargs["executor_attestation"])
    returned_results = attestation.returned_results
    rows = list(returned_results.results_in_submission_order)
    row = rows[row_index]
    rows[row_index] = (
        row[0],
        cast(Any, _nested_replace(row[1], path, replacement)),
        row[2],
    )
    changed = replace(returned_results, results_in_submission_order=tuple(rows))
    attestation = replace(attestation, returned_results=changed)
    kwargs["executor_attestation"] = attestation
    return attestation


def _deep_stage2e_error(
    kwargs: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    code: str = RA,
) -> ex.ExecutorProvenanceError:
    entered: list[str] = []
    original_mapping = ex._stage2e_projection_mapping

    def monitored(
        value: object,
        expected: type[object],
        context: object,
        path: str,
    ) -> object:
        if path in {
            "executor_attestation.worker_result_order",
            "executor_attestation.runtime",
            "executor_attestation",
        }:
            entered.append(path)
        return original_mapping(value, expected, cast(Any, context), path)

    def forbidden_identity(_projection: ex.ExecutorAttestationProjection) -> str:
        entered.append("executor_attestation_id")
        raise AssertionError("later identity entered")

    with monkeypatch.context() as scoped:
        scoped.setattr(ex, "_stage2e_projection_mapping", monitored)
        scoped.setattr(ex, "executor_attestation_id", forbidden_identity)
        error = assert_failure(kwargs, code)
    assert entered == []
    return error


@pytest.mark.parametrize(
    ("row_index", "kind"), ((0, "lookahead_plan_trace"), (1, "decision_trace"))
)
def test_each_returned_run_policy_variant_passes_the_public_boundary(
    row_index: int,
    kind: str,
) -> None:
    kwargs = valid_kwargs()
    rows = kwargs["executor_attestation"].returned_results.results_in_submission_order
    assert {decision.policy_trace.kind for decision in rows[row_index][1].decisions} == {kind}
    assert invoke(kwargs) == kwargs["executor_attestation"]


@pytest.mark.parametrize(
    ("delivery", "acceptance"),
    (("input_order", "submission"), ("completion_order", "reverse")),
)
def test_thread_pool_valid_controls_preserve_deep_returned_run_boundary(
    delivery: str,
    acceptance: str,
) -> None:
    kwargs = valid_kwargs()
    first = kwargs["workers_in_actual_delivery_order"][0][0]
    second = replace(
        first,
        thread_id=first.thread_id + 17,
        thread_name=f"{first.thread_name}-second",
    )
    workers = ((first, ex.worker_identity(first)), (second, ex.worker_identity(second)))
    kwargs["expected_workers_in_actual_delivery_order"] = (first, second)
    kwargs["workers_in_actual_delivery_order"] = workers
    execution = replace(kwargs["execution"], role="altered_order_replay")
    kwargs["execution"] = kwargs["expected_execution"] = execution
    old_spec = kwargs["expected_execution_specification"]
    scheduling = "thread_pool_concurrent_submission"
    configuration = replace(
        old_spec.configuration,
        executor_kind="thread_pool",
        result_delivery_mode=delivery,
        scheduling_mode=scheduling,
        worker_count=2,
    )
    configuration_id = protocol_hash(
        "validation_evidence_executor_configuration/v1",
        configuration.as_dict(),
    )
    submitted = replace(kwargs["submitted_jobs"], configuration_sha256=configuration_id)
    kwargs.update(
        submitted_jobs=submitted,
        expected_submitted_jobs=submitted,
        carried_submitted_jobs_sha256=ex.submitted_jobs_sha256(submitted),
    )
    specification = replace(
        old_spec,
        configuration=configuration,
        configuration_sha256=configuration_id,
        executor_kind="thread_pool",
        result_delivery_mode=delivery,
        role="altered_order_replay",
        scheduling_mode=scheduling,
        submitted_jobs=submitted.jobs,
        worker_count=2,
    )
    specification_id = protocol_hash(
        "validation_evidence_execution_specification/v1",
        specification.as_dict(),
    )
    _rebind_specification(kwargs, specification_id)
    authority = replace(
        kwargs["expected_validation_authority"],
        replay_execution_specification_id=specification_id,
    )
    submitted = kwargs["submitted_jobs"]
    completion = kwargs["execution_completion"]
    batch = kwargs["result_batch"]
    job_ids = tuple(job.submitted_job_id for job in submitted.jobs)
    accepted = job_ids if acceptance == "submission" else tuple(reversed(job_ids))
    attestation = replace(
        kwargs["executor_attestation"],
        accepted_job_ids=accepted,
        actual_worker_count=len(completion.observed_worker_ids),
        configured_worker_count=2,
        configuration_sha256=configuration_id,
        execution_completion_id=kwargs["carried_execution_completion_id"],
        execution_id=kwargs["carried_execution_id"],
        execution_specification_id=specification_id,
        execution_start_id=kwargs["carried_execution_start_id"],
        executor_kind="thread_pool",
        job_result_mapping=kwargs["job_result_mapping"],
        observed_worker_ids=completion.observed_worker_ids,
        result_batch_id=kwargs["carried_result_batch_id"],
        result_delivery_mode=delivery,
        result_payload_sha256_in_delivery_order=(batch.result_payload_sha256_in_delivery_order),
        returned_results=kwargs["returned_results"],
        returned_results_sha256=kwargs["carried_returned_results_sha256"],
        role="altered_order_replay",
        scheduling_mode=scheduling,
        submitted_jobs=submitted,
        submitted_jobs_sha256=kwargs["carried_submitted_jobs_sha256"],
        worker_result_order=kwargs["worker_result_order"],
        worker_result_order_sha256=kwargs["carried_worker_result_order_sha256"],
    )
    kwargs.update(
        expected_validation_authority=authority,
        expected_execution_specification=specification,
        accepted_job_ids_in_actual_acceptance_order=accepted,
        executor_attestation=attestation,
        carried_executor_attestation_id=ex.executor_attestation_id(attestation),
    )
    assert invoke(kwargs) == attestation


@pytest.mark.parametrize(
    "case",
    (
        "wrong-projection-type",
        "plain-object",
        "mapping-payload",
        "projection-subclass",
        "wrong-tag-payload-combination",
        "copied-valid-id-wrong-variant",
    ),
)
def test_policy_trace_payload_defects_reject_at_3n12_without_hooks(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    kwargs = valid_kwargs()
    rows = kwargs["executor_attestation"].returned_results.results_in_submission_order
    trace = rows[0][1].decisions[0].policy_trace
    counts: _HookCounts | None = None
    if case == "wrong-projection-type":
        payload = rows[0][1].completed_experiments[0].candidate
    elif case in {"plain-object", "mapping-payload", "projection-subclass"}:
        shape: _LookalikeShape = {
            "plain-object": "conversion",
            "mapping-payload": "mapping",
            "projection-subclass": "subclass",
        }[case]  # type: ignore[assignment]
        payload, counts = _hook_lookalike(trace.projection, shape)
    elif case == "wrong-tag-payload-combination":
        payload = trace.projection
        trace = replace(trace, kind="decision_trace")
    else:
        decision = rows[1][1].decisions[0].policy_trace.projection
        payload = replace(decision, suggestion_id=trace.projection.plan_id)
    trace = replace(trace, projection=payload)
    _replace_returned_run(
        kwargs,
        0,
        ("decisions", 0, "policy_trace"),
        trace,
    )
    error = _deep_stage2e_error(kwargs, monkeypatch)
    assert "results_in_submission_order[0].projection.decisions[0].policy_trace" in str(error)
    if counts is not None:
        _assert_zero_hooks(counts, case)


@pytest.mark.parametrize(
    ("family", "kind"),
    (
        *(("provenance", kind) for kind in ("null", "bool", "i64", "f64", "string")),
        *(("control", kind) for kind in ("i64", "f64", "string")),
        *(
            ("second-action", kind)
            for kind in ("opens_pair", "completes_pair", "ineligible", "stop")
        ),
    ),
)
def test_every_returned_run_tag_payload_combination_passes_shape_authority(
    family: str,
    kind: str,
) -> None:
    run = valid_kwargs()["executor_attestation"].returned_results.results_in_submission_order[0][1]
    path: _NestedPath
    replacement: object
    if family == "provenance":
        path = ("decisions", 0, "policy_trace", "projection", "provenance", "details", 0, 1)
        payload = {
            "null": None,
            "bool": True,
            "i64": 7,
            "f64": "f64:3ff0000000000000",
            "string": "value",
        }[kind]
        replacement = returned.ProvenanceValueProjection(cast(Any, kind), payload)
    elif family == "control":
        path = (
            "decisions",
            0,
            "policy_trace",
            "projection",
            "selected",
            "public_design",
            "controlled_variables",
            0,
            1,
        )
        payload = 7 if kind == "i64" else "value"
        replacement = returned.ControlValueProjection(cast(Any, kind), payload)
    else:
        path = (
            "decisions",
            0,
            "policy_trace",
            "projection",
            "selected",
            "branches",
            0,
            "second_action",
        )
        second = cast(Any, _nested_value(run, path))
        replacement = replace(
            second,
            action_effect=kind,
            candidate=None if kind == "stop" else run.completed_experiments[0].candidate,
        )
    changed = cast(returned.ReturnedRunProjection, _nested_replace(run, path, replacement))
    assert returned.validate_returned_run_projection_shape(changed) is changed


@pytest.mark.parametrize(
    "case",
    (
        "provenance-kind-payload",
        "control-kind-payload",
        "second-action-stop-with-candidate",
        "second-action-nonstop-without-candidate",
        "effect-source-kind",
        "sigma-status",
        "authorization-kind",
        "run-status",
    ),
)
def test_other_returned_run_tag_and_literal_defects_reject_at_3n12(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    kwargs = valid_kwargs()
    run = kwargs["executor_attestation"].returned_results.results_in_submission_order[0][1]
    paths: dict[str, _NestedPath] = {
        "provenance-kind-payload": (
            "decisions",
            0,
            "policy_trace",
            "projection",
            "provenance",
            "details",
            0,
            1,
        ),
        "control-kind-payload": (
            "decisions",
            0,
            "policy_trace",
            "projection",
            "selected",
            "public_design",
            "controlled_variables",
            0,
            1,
        ),
        "second-action-stop-with-candidate": (
            "decisions",
            0,
            "policy_trace",
            "projection",
            "selected",
            "branches",
            0,
            "second_action",
        ),
        "second-action-nonstop-without-candidate": (
            "decisions",
            0,
            "policy_trace",
            "projection",
            "selected",
            "branches",
            0,
            "second_action",
        ),
        "effect-source-kind": ("effect_history", 0),
        "sigma-status": ("updates", 0, "sigma_estimate"),
        "authorization-kind": ("actions", 1, "oracle_observation", "authorization"),
        "run-status": (),
    }
    path = paths[case]
    value = _nested_value(run, path)
    changes: dict[str, object]
    if case == "provenance-kind-payload":
        changes = {"kind": "bool"}
    elif case == "control-kind-payload":
        changes = {"kind": "i64"}
    elif case == "second-action-stop-with-candidate":
        changes = {"candidate": run.completed_experiments[0].candidate}
    elif case == "second-action-nonstop-without-candidate":
        changes = {"action_effect": "opens_pair"}
    elif case == "effect-source-kind":
        changes = {"source_kind": "unknown"}
    elif case == "sigma-status":
        changes = {"status": "unknown"}
    elif case == "authorization-kind":
        changes = {"kind": "unknown"}
    else:
        changes = {"run_status": "unknown"}
    _replace_returned_run(kwargs, 0, path, replace(cast(Any, value), **changes))
    _deep_stage2e_error(kwargs, monkeypatch)


@pytest.mark.parametrize(
    "case",
    (
        "list-for-decisions-tuple",
        "list-for-probability-row",
        "bool-for-integer",
        "integer-for-boolean",
        "missing-arm-row-field",
        "nested-projection-substitute",
    ),
)
def test_deep_container_row_and_primitive_shapes_reject_at_3n12(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    kwargs = valid_kwargs()
    run = kwargs["executor_attestation"].returned_results.results_in_submission_order[0][1]
    path: _NestedPath
    replacement: object
    if case == "list-for-decisions-tuple":
        path, replacement = ("decisions",), list(run.decisions)
    elif case == "list-for-probability-row":
        path, replacement = ("initial_probabilities", 0), list(run.initial_probabilities[0])
    elif case == "bool-for-integer":
        path, replacement = ("seed",), True
    elif case == "integer-for-boolean":
        path = ("diagnostics", 0, "diagnostics_disagree")
        replacement = 1
    elif case == "missing-arm-row-field":
        path, replacement = ("arm",), run.arm[:3]
    else:
        path, replacement = ("lineage",), object()
    _replace_returned_run(kwargs, 0, path, replacement)
    _deep_stage2e_error(kwargs, monkeypatch)


@pytest.mark.parametrize("shape", ("conversion", "mapping", "subclass"))
def test_executor_attestation_id_rejects_deep_policy_shape_before_hash(
    monkeypatch: pytest.MonkeyPatch,
    shape: _LookalikeShape,
) -> None:
    kwargs = valid_kwargs()
    attestation = kwargs["executor_attestation"]
    trace = attestation.returned_results.results_in_submission_order[0][1].decisions[0].policy_trace
    payload, counts = _hook_lookalike(trace.projection, shape)
    malformed = _replace_returned_run(
        kwargs,
        0,
        ("decisions", 0, "policy_trace"),
        replace(trace, projection=payload),
    )
    hash_entered = False

    def forbidden_hash(_domain: str, _projection: object) -> str:
        nonlocal hash_entered
        hash_entered = True
        raise AssertionError("canonical hash entered")

    monkeypatch.setattr(ex, "protocol_hash", forbidden_hash)
    with pytest.raises(ex.ExecutorProvenanceError) as captured:
        ex.executor_attestation_id(malformed)
    assert captured.value.error_code == ID
    assert hash_entered is False
    _assert_zero_hooks(counts, shape)


def test_coherently_rehashed_deep_inconsistency_still_rejects_at_3n12(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = valid_kwargs()
    run = kwargs["executor_attestation"].returned_results.results_in_submission_order[0][1]
    path = ("decisions", 0, "policy_trace", "projection", "provenance", "details", 0, 1)
    tagged = cast(returned.ProvenanceValueProjection, _nested_value(run, path))
    attestation = _replace_returned_run(
        kwargs,
        0,
        path,
        replace(tagged, kind="bool"),
    )
    returned_hash = protocol_hash(
        "validation_evidence_returned_results/v1",
        attestation.returned_results.as_dict(),
    )
    attestation = replace(attestation, returned_results_sha256=returned_hash)
    kwargs["executor_attestation"] = attestation
    kwargs["carried_executor_attestation_id"] = protocol_hash(DOMAIN, attestation.as_dict())
    assert returned_hash != kwargs["carried_returned_results_sha256"]
    _deep_stage2e_error(kwargs, monkeypatch)


@pytest.mark.parametrize(
    ("earlier", "code"),
    (
        ("implementation", EI),
        ("submitted", SJ),
        ("batch", "EXECUTION_RESULT_BATCH_ID_MISMATCH"),
        ("completion", "EXECUTION_COMPLETION_ID_MISMATCH"),
        ("worker", RA),
        ("identity", RA),
    ),
)
def test_deep_3n12_shape_fault_preserves_global_first_failure(
    monkeypatch: pytest.MonkeyPatch,
    earlier: str,
    code: str,
) -> None:
    kwargs = valid_kwargs()
    if earlier in {"implementation", "submitted", "batch", "completion"}:
        _relation_fault(kwargs, earlier)
    elif earlier == "worker":
        attestation = kwargs["executor_attestation"]
        kwargs["executor_attestation"] = replace(attestation, worker_result_order_sha256=BAD)
    else:
        kwargs["carried_executor_attestation_id"] = BAD
    trace = (
        kwargs["executor_attestation"]
        .returned_results.results_in_submission_order[0][1]
        .decisions[0]
        .policy_trace
    )
    _replace_returned_run(
        kwargs, 0, ("decisions", 0, "policy_trace"), replace(trace, projection=object())
    )
    _deep_stage2e_error(kwargs, monkeypatch, code)


def _change(
    attestation: ex.ExecutorAttestationProjection,
    field_name: str,
) -> object:
    value = getattr(attestation, field_name)
    if field_name in {
        "schema_version",
        "execution_status",
        "protocol_checkpoint",
        "study_id",
        "trust_domain",
    }:
        return f"{value}-invalid"
    if field_name == "accepted_job_ids":
        return tuple(reversed(value))
    if field_name in {"actual_worker_count", "configured_worker_count"}:
        return value + 1
    if field_name == "completed_at":
        return "2026-01-02T03:04:08.000000Z"
    if field_name == "started_at":
        return "2026-01-02T03:04:07.000000Z"
    if field_name == "executor_kind":
        return "thread_pool"
    if field_name == "result_delivery_mode":
        return "completion_order"
    if field_name == "executor_implementation":
        return replace(value, callable_identity=BAD)
    if field_name == "implementation":
        return replace(value, dependency_lock_sha256=BAD)
    if field_name == "job_result_mapping":
        return tuple(reversed(value))
    if field_name == "observed_worker_ids":
        return (BAD,)
    if field_name == "result_payload_sha256_in_delivery_order":
        return tuple(reversed(value))
    if field_name == "returned_results":
        return replace(value, oracle_binding_id=BAD)
    if field_name == "runtime":
        return replace(value, python_build_date="Mar  7 2025")
    if field_name == "submitted_jobs":
        return replace(value, configuration_sha256=BAD)
    if field_name == "worker_result_order":
        return replace(value, oracle_binding_id=BAD)
    if len(value) == 64:
        return BAD if value != BAD else "e" * 64
    if len(value) == 40:
        return "e" * 40
    return f"{value}-changed"


@pytest.mark.parametrize("field_name", FIELD_NAMES)
def test_every_field_is_total_to_identity_or_closed_literal(field_name: str) -> None:
    attestation = cast(ex.ExecutorAttestationProjection, valid_kwargs()["executor_attestation"])
    mutated = replace(cast(Any, attestation), **{field_name: _change(attestation, field_name)})
    if field_name in {
        "schema_version",
        "execution_status",
        "protocol_checkpoint",
        "study_id",
        "trust_domain",
    }:
        with pytest.raises(ex.ExecutorProvenanceError) as captured:
            ex.executor_attestation_id(mutated)
        assert captured.value.error_code == "EXECUTOR_ATTESTATION_ID_MISMATCH"
    else:
        assert ex.executor_attestation_id(mutated) != ex.executor_attestation_id(attestation)


@pytest.mark.parametrize(
    "case",
    (
        "missing",
        "extra",
        "reordered",
        "bool_for_u64",
        "tuple_for_list",
        "malformed_h64",
        "non_nfc",
        "nested_extra",
    ),
)
def test_decoder_is_closed_ordered_and_strict(case: str) -> None:
    attestation = cast(ex.ExecutorAttestationProjection, valid_kwargs()["executor_attestation"])
    raw = attestation.as_dict()
    if case == "missing":
        raw.pop("role")
    elif case == "extra":
        raw["extra"] = "forbidden"
    elif case == "reordered":
        raw = dict(reversed(tuple(raw.items())))
    elif case == "bool_for_u64":
        raw["actual_worker_count"] = True
    elif case == "tuple_for_list":
        raw["accepted_job_ids"] = tuple(attestation.accepted_job_ids)
    elif case == "malformed_h64":
        raw["execution_id"] = "A" * 64
    elif case == "non_nfc":
        raw["scheduling_mode"] = "e\u0301"
    else:
        nested = cast(dict[str, object], raw["executor_implementation"])
        nested["extra"] = "forbidden"
    with pytest.raises(ex.ExecutorProvenanceError) as captured:
        ex.decode_executor_attestation_projection(raw)
    assert captured.value.error_code == "EXECUTOR_ATTESTATION_ID_MISMATCH"


RELATION_CASES: Final = tuple(
    tuple(item.split("="))
    for item in (
        "unauthorized=EXECUTOR_ATTESTATION_SPECIFICATION_UNAUTHORIZED "
        "implementation=EXECUTOR_IMPLEMENTATION_IDENTITY_MISMATCH "
        "execution=EXECUTION_SPECIFICATION_RELATION_MISMATCH "
        "configuration=EXECUTION_SPECIFICATION_RELATION_MISMATCH "
        "namespace=EXECUTION_NAMESPACE_MISMATCH start=EXECUTION_START_ID_MISMATCH "
        "submitted=EXECUTION_SUBMITTED_JOBS_MISMATCH "
        "returned=EXECUTION_RETURNED_RESULT_ID_MISMATCH "
        "mapping=EXECUTION_JOB_RESULT_MAPPING_MISMATCH "
        "batch=EXECUTION_RESULT_BATCH_ID_MISMATCH "
        "completion=EXECUTION_COMPLETION_ID_MISMATCH "
        "aggregate=EXECUTION_RETURNED_RESULTS_MISMATCH "
        "worker=EXECUTION_RESULT_ORDER_MISMATCH runtime=RUNTIME_IDENTITY_MISMATCH"
    ).split()  # noqa: SIM905 - compact immutable relation table
)


def _relation_fault(kwargs: dict[str, Any], case: str) -> None:
    attestation = kwargs["executor_attestation"]
    if case == "unauthorized":
        attestation = replace(attestation, execution_specification_id=BAD)
    elif case == "implementation":
        kwargs["expected_executor_implementation_identity"] = BAD
        kwargs["expected_execution_specification"] = replace(
            kwargs["expected_execution_specification"],
            executor_implementation_identity=BAD,
        )
        attestation = replace(attestation, executor_implementation_identity=BAD)
    elif case == "execution":
        implementation = replace(
            kwargs["expected_executor_implementation"],
            implementation_tree_sha256=BAD,
        )
        implementation_id = protocol_hash(
            "validation_evidence_executor_implementation/v1",
            implementation.as_dict(),
        )
        kwargs["expected_executor_implementation"] = implementation
        kwargs["expected_executor_implementation_identity"] = implementation_id
        kwargs["expected_execution_specification"] = replace(
            kwargs["expected_execution_specification"],
            executor_implementation=implementation,
            executor_implementation_identity=implementation_id,
        )
        attestation = replace(
            attestation,
            executor_implementation=implementation,
            executor_implementation_identity=implementation_id,
        )
    elif case == "configuration":
        attestation = replace(attestation, configuration_sha256=BAD)
    elif case == "namespace":
        attestation = replace(attestation, normalized_execution_namespace="wrong")
    elif case == "start":
        attestation = replace(attestation, execution_start_id=BAD)
    elif case == "submitted":
        attestation = replace(attestation, submitted_jobs_sha256=BAD)
    elif case == "returned":
        mapping = (
            (attestation.job_result_mapping[0][0], BAD),
            *attestation.job_result_mapping[1:],
        )
        attestation = replace(attestation, job_result_mapping=mapping)
    elif case == "mapping":
        attestation = replace(
            attestation,
            job_result_mapping=tuple(reversed(attestation.job_result_mapping)),
        )
    elif case == "batch":
        attestation = replace(attestation, result_batch_id=BAD)
    elif case == "completion":
        attestation = replace(attestation, execution_completion_id=BAD)
    elif case == "aggregate":
        attestation = replace(attestation, returned_results_sha256=BAD)
    elif case == "worker":
        attestation = replace(attestation, worker_result_order_sha256=BAD)
    elif case == "runtime":
        attestation = replace(attestation, runtime_identity=BAD)
    else:
        raise AssertionError(case)
    kwargs["executor_attestation"] = attestation
    kwargs["carried_executor_attestation_id"] = ex.executor_attestation_id(attestation)


@pytest.mark.parametrize(("case", "code"), RELATION_CASES)
def test_exact_3n_relation_and_authorization_failures(case: str, code: str) -> None:
    kwargs = valid_kwargs()
    _relation_fault(kwargs, case)
    assert_failure(kwargs, code)
    if case == "returned":
        kwargs = valid_kwargs()
        attestation = cast(ex.ExecutorAttestationProjection, kwargs["executor_attestation"])
        attestation = replace(
            attestation,
            result_payload_sha256_in_delivery_order=tuple(
                reversed(attestation.result_payload_sha256_in_delivery_order)
            ),
        )
        kwargs["executor_attestation"] = attestation
        kwargs["carried_executor_attestation_id"] = ex.executor_attestation_id(attestation)
        assert_failure(kwargs, code)


@pytest.mark.parametrize(
    ("earlier", "code"),
    (
        ("completion", "EXECUTION_COMPLETION_ID_MISMATCH"),
        ("aggregate", "EXECUTION_RETURNED_RESULTS_MISMATCH"),
        ("worker", "EXECUTION_RESULT_ORDER_MISMATCH"),
    ),
)
def test_all_3g_to_3m_predicates_precede_3n(earlier: str, code: str) -> None:
    kwargs = valid_kwargs()
    _relation_fault(kwargs, "unauthorized")
    if earlier == "completion":
        kwargs["carried_execution_completion_id"] = BAD
    elif earlier == "aggregate":
        kwargs["carried_returned_results_sha256"] = BAD
    else:
        kwargs["carried_worker_result_order_sha256"] = BAD
    assert_failure(kwargs, code)


COMPOUND_CASES: Final = (
    ("unauthorized", "implementation", "EXECUTOR_ATTESTATION_SPECIFICATION_UNAUTHORIZED"),
    ("implementation", "forged_id", "EXECUTOR_IMPLEMENTATION_IDENTITY_MISMATCH"),
    ("execution", "forged_id", "EXECUTION_SPECIFICATION_RELATION_MISMATCH"),
    ("aggregate", "forged_id", "EXECUTION_RETURNED_RESULTS_MISMATCH"),
    ("worker", "forged_id", "EXECUTION_RESULT_ORDER_MISMATCH"),
    ("runtime", "forged_id", "RUNTIME_IDENTITY_MISMATCH"),
    ("oracle", "forged_id", "EXECUTOR_ATTESTATION_ID_MISMATCH"),
    ("authority_run", "forged_id", "EXECUTOR_ATTESTATION_ID_MISMATCH"),
)


@pytest.mark.parametrize(("first", "second", "code"), COMPOUND_CASES)
def test_compound_faults_stop_at_exact_first_3n_predicate(
    first: str,
    second: str,
    code: str,
) -> None:
    kwargs = valid_kwargs()
    attestation = cast(ex.ExecutorAttestationProjection, kwargs["executor_attestation"])
    if first in dict(RELATION_CASES):  # type: ignore[arg-type]
        _relation_fault(kwargs, first)
        attestation = cast(ex.ExecutorAttestationProjection, kwargs["executor_attestation"])
    elif first == "oracle":
        attestation = replace(attestation, oracle_binding_id=BAD)
    elif first == "authority_run":
        attestation = replace(attestation, validation_run_id=BAD)
    else:
        raise AssertionError(first)
    if second == "implementation":
        attestation = replace(attestation, executor_implementation_identity="e" * 64)
    if second == "forged_id":
        kwargs["carried_executor_attestation_id"] = BAD
    kwargs["executor_attestation"] = attestation
    assert_failure(kwargs, code)


def test_earlier_3n_failure_does_not_recompute_id_or_accept_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = valid_kwargs()
    _relation_fault(kwargs, "configuration")
    entered = False

    def forbidden(_projection: ex.ExecutorAttestationProjection) -> str:
        nonlocal entered
        entered = True
        raise AssertionError("later identity entered")

    monkeypatch.setattr(ex, "executor_attestation_id", forbidden)
    assert_failure(kwargs, "EXECUTION_SPECIFICATION_RELATION_MISMATCH")
    assert entered is False
    parameters = inspect.signature(ex.validate_stage2e_executor_attestation).parameters
    assert not any(
        token in name
        for name in parameters
        for token in ("authorized", "validator", "callback", "calibration", "reader")
    )


def test_historical_task_c_attestation_is_not_p2_identity_authority() -> None:
    assert not issubclass(ex.ActualExecutorAttestation, ex.ExecutorAttestationProjection)
    source = inspect.getsource(ex.executor_attestation_id)
    assert DOMAIN in source
    assert "_identity_digest" not in source
    assert "result_order_sha256" not in source
