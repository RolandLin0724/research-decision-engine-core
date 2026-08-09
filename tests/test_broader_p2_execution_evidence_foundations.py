from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from typing import Any, Final, cast

import pytest

from research_decision_engine.benchmarks import broader_execution as ex
from research_decision_engine.benchmarks.broader_protocol import protocol_hash
from research_decision_engine.benchmarks.broader_validation_evidence import (
    FileProjection,
    ImplementationProjection,
    InterpreterIdentityProjection,
    PlatformIdentityProjection,
    RuntimeProjection,
)

CHECKPOINT: Final = "89c0b4fadba33b9fd9a257b43eacf476b7779d59"
STUDY: Final = "broader-closed-loop-replication/v1"
STARTED, EXECUTION_STARTED = (
    "2026-01-02T03:04:05.000000Z",
    "2026-01-02T03:04:06.000000Z",
)
ID_ERROR, RELATION_ERROR = (
    "EXECUTION_ID_MISMATCH",
    "EXECUTION_SPECIFICATION_RELATION_MISMATCH",
)
SUBMITTED_ERROR, START_ERROR, WORKER_ERROR = (
    "EXECUTION_SUBMITTED_JOBS_MISMATCH",
    "EXECUTION_START_ID_MISMATCH",
    "EXECUTION_RESULT_ORDER_MISMATCH",
)


def h(number: int) -> str:
    return f"{number:064x}"


def construct(cls: Any, *groups: tuple[Any, ...]) -> Any:
    return cls(*(item for group in groups for item in group))


def words(text: str) -> tuple[str, ...]:
    return tuple(text.split())


FIELD_NAMES = {
    "ExecutionInstanceProjection": words(
        "counter issuer_identity process_id process_nonce process_started_at schema_version"
    ),
    "ExecutionIdentityProjection": words(
        "execution_instance execution_instance_identity execution_specification_id "
        "implementation_commit implementation_diff_sha256 implementation_tree_sha256 "
        "oracle_binding_id oracle_execution_id protocol_checkpoint role runtime_identity "
        "schema_version study_id validation_authority_id validation_run_id"
    ),
    "SubmittedJobsProjection": words(
        "configuration_sha256 execution_id execution_specification_id implementation jobs "
        "oracle_binding_id oracle_execution_id protocol_checkpoint runtime runtime_identity "
        "schema_version study_id validation_authority_id validation_run_id"
    ),
    "ExecutionStartProjection": words(
        "execution_id execution_instance_identity execution_specification_id schema_version "
        "started_at validation_authority_id validation_run_id"
    ),
    "WorkerIdentityProjection": words(
        "execution_instance_identity execution_specification_id process_id schema_version "
        "thread_id thread_name validation_authority_id validation_run_id"
    ),
}
TYPE_NAMES = {
    "ExecutionInstanceProjection": words(
        "int str int str str Literal['broader-replication-execution-instance/v1']"
    ),
    "ExecutionIdentityProjection": words(
        "ExecutionInstanceProjection str str str str str str str "
        "Literal['89c0b4fadba33b9fd9a257b43eacf476b7779d59'] str str "
        "Literal['broader-replication-execution/v1'] str str str"
    ),
    "SubmittedJobsProjection": words(
        "str str str ImplementationProjection tuple[SubmittedJobProjection,...] str str "
        "Literal['89c0b4fadba33b9fd9a257b43eacf476b7779d59'] RuntimeProjection str "
        "Literal['broader-replication-submitted-jobs/v1'] "
        "Literal['broader-closed-loop-replication/v1'] str str"
    ),
    "ExecutionStartProjection": words(
        "str str str Literal['broader-replication-execution-start/v1'] str str str"
    ),
    "WorkerIdentityProjection": words(
        "str str int Literal['broader-replication-worker-identity/v1'] int str str str"
    ),
}
EI, EX, SJ, ES, WI = FIELD_NAMES


def surface(
    schema: str, decoder_stem: str, identity_name: str, actual_key: str | None = None
) -> tuple[str, Any, Any, str]:
    decoder = getattr(ex, f"decode_{decoder_stem}_projection")
    return schema, decoder, getattr(ex, identity_name), actual_key or decoder_stem


SURFACES: dict[str, tuple[str, Any, Any, str]] = {
    EI: surface("execution-instance", "execution_instance", "execution_instance_identity"),
    EX: surface("execution", "execution_identity", "execution_id", "execution"),
    SJ: surface("submitted-jobs", "submitted_jobs", "submitted_jobs_sha256"),
    ES: surface("execution-start", "execution_start", "execution_start_id"),
    WI: surface("worker-identity", "worker_identity", "worker_identity"),
}
FIELD_CASES = tuple((name, field) for name, names in FIELD_NAMES.items() for field in names)


def runtime(path: str = r"C:\rde\python.exe") -> RuntimeProjection:
    executable = FileProjection(12, path, h(1))
    interpreter = InterpreterIdentityProjection(
        "cpython-312",
        "MSC v.1938",
        path,
        executable.sha256,
        "cpython",
        "3.12.2",
    )
    platform = PlatformIdentityProjection("x86_64", "win32", "11", "Windows", "10.0")
    return RuntimeProjection(
        executable,
        executable,
        interpreter,
        protocol_hash("pytest_interpreter_identity/v1", interpreter.as_dict()),
        platform,
        protocol_hash("pytest_platform_identity/v1", platform.as_dict()),
        "Feb  6 2024",
        "main",
    )


def submitted_job(
    submission_index: int, arm_id: str, arm_order: int, seed: int, budget: str
) -> ex.SubmittedJobProjection:
    projection = ex.ValidationJobProjection(
        ex.ValidationJobArmProjection(arm_id, arm_order, "belief", "policy"),
        budget,
        "budget",
        seed,
        submission_index,
        "world",
    )
    return ex.SubmittedJobProjection(ex.submitted_job_id(projection), projection)


def graph() -> dict[str, Any]:
    instance = construct(
        ex.ExecutionInstanceProjection,
        (7, h(2), 101, h(3), STARTED),
        ("broader-replication-execution-instance/v1",),
    )
    instance_id = ex.execution_instance_identity(instance)
    runtime_value = runtime()
    runtime_id = protocol_hash("validation_evidence_runtime/v1", runtime_value.as_dict())
    implementation = ImplementationProjection(h(4), "5" * 40, h(6), h(7), h(8), h(9))
    execution = construct(
        ex.ExecutionIdentityProjection,
        (instance, instance_id, h(10), implementation.implementation_commit),
        (implementation.implementation_diff_sha256, implementation.implementation_tree_sha256),
        (h(11), h(12), CHECKPOINT, "primary_smoke", runtime_id),
        ("broader-replication-execution/v1", STUDY, h(13), h(14)),
    )
    execution_id = ex.execution_id(execution)
    jobs = (
        submitted_job(0, "arm-z", 2, 0, "f64:3ff0000000000000"),
        submitted_job(1, "arm-a", 1, 100, "f64:4000000000000000"),
    )
    submitted = construct(
        ex.SubmittedJobsProjection,
        (h(15), execution_id, execution.execution_specification_id, implementation, jobs),
        (execution.oracle_binding_id, execution.oracle_execution_id, CHECKPOINT),
        (runtime_value, runtime_id, "broader-replication-submitted-jobs/v1", STUDY),
        (execution.validation_authority_id, execution.validation_run_id),
    )
    start = construct(
        ex.ExecutionStartProjection,
        (execution_id, instance_id, execution.execution_specification_id),
        ("broader-replication-execution-start/v1", EXECUTION_STARTED),
        (execution.validation_authority_id, execution.validation_run_id),
    )
    workers = tuple(
        construct(
            ex.WorkerIdentityProjection,
            (instance_id, execution.execution_specification_id, instance.process_id),
            ("broader-replication-worker-identity/v1", 201 + index, f"worker-{index}"),
            (execution.validation_authority_id, execution.validation_run_id),
        )
        for index in range(2)
    )
    observations = tuple((worker, ex.worker_identity(worker)) for worker in workers)
    kwargs = {
        "expected_execution_instance": instance,
        "execution_instance": instance,
        "carried_execution_instance_identity": instance_id,
        "expected_execution": execution,
        "execution": execution,
        "carried_execution_id": execution_id,
        "expected_submitted_jobs": submitted,
        "submitted_jobs": submitted,
        "carried_submitted_jobs_sha256": ex.submitted_jobs_sha256(submitted),
        "expected_execution_start": start,
        "execution_start": start,
        "carried_execution_start_id": ex.execution_start_id(start),
        "expected_workers_in_actual_delivery_order": workers,
        "workers_in_actual_delivery_order": observations,
    }
    return {
        "objects": dict(
            zip(FIELD_NAMES, (instance, execution, submitted, start, workers[0]), strict=True)
        ),
        "kwargs": kwargs,
    }


def assert_failure(kwargs: dict[str, Any], code: str) -> ex.ExecutorProvenanceError:
    with pytest.raises(ex.ExecutorProvenanceError) as captured:
        ex.validate_stage2d2_execution_foundations(**kwargs)
    assert captured.value.error_code == code
    return captured.value


def changed(value: object) -> object:
    if type(value) is int:
        return value + 1
    if type(value) is str:
        if value.endswith("Z"):
            return "2026-01-02T03:04:07.000000Z"
        if len(value) in (40, 64):
            return ("a" if value[0] != "a" else "b") * len(value)
        return f"{value}-changed"
    if type(value) is list:
        return []
    if type(value) is dict:
        key = next(iter(value))
        value[key] = changed(value[key])
        return value
    raise AssertionError(f"no mutation for {type(value).__name__}")


@pytest.mark.parametrize("projection_name", FIELD_NAMES)
def test_exact_fields_schemas_round_trips_and_domains(projection_name: str) -> None:
    projection = graph()["objects"][projection_name]
    schema_slug, decoder, identity, domain_slug = SURFACES[projection_name]
    assert tuple(field.name for field in fields(projection)) == FIELD_NAMES[projection_name]
    annotations = tuple(
        value.replace(", ", ",") for value in type(projection).__annotations__.values()
    )
    assert annotations == TYPE_NAMES[projection_name]
    assert tuple(projection.as_dict()) == FIELD_NAMES[projection_name]
    assert projection.schema_version == f"broader-replication-{schema_slug}/v1"
    assert decoder(projection.as_dict()) == projection
    assert identity(projection) == protocol_hash(
        f"validation_evidence_{domain_slug}/v1", projection.as_dict()
    )
    assert not hasattr(projection, "__dict__")
    with pytest.raises(FrozenInstanceError):
        setattr(projection, FIELD_NAMES[projection_name][0], None)


@pytest.mark.parametrize(("projection_name", "field_name"), FIELD_CASES)
def test_every_projection_field_is_decoded_and_identity_bound(
    projection_name: str,
    field_name: str,
) -> None:
    baseline = graph()
    projection = baseline["objects"][projection_name]
    raw = projection.as_dict()
    raw[field_name] = changed(raw[field_name])
    _schema, decoder, identity, actual_key = SURFACES[projection_name]
    try:
        mutated = decoder(raw)
    except ex.ExecutorProvenanceError:
        return
    assert identity(mutated) != identity(projection)
    kwargs = dict(baseline["kwargs"])
    if projection_name == "WorkerIdentityProjection":
        observations = list(kwargs["workers_in_actual_delivery_order"])
        observations[0] = (mutated, identity(mutated))
        kwargs["workers_in_actual_delivery_order"] = tuple(observations)
    else:
        kwargs[actual_key] = mutated
    relation_fields = {
        "execution_specification_id",
        "implementation_commit",
        "implementation_diff_sha256",
        "implementation_tree_sha256",
        "oracle_binding_id",
        "oracle_execution_id",
        "role",
        "runtime_identity",
        "study_id",
        "validation_authority_id",
        "validation_run_id",
    }
    expected = {
        "ExecutionInstanceProjection": ID_ERROR,
        "ExecutionIdentityProjection": (
            RELATION_ERROR if field_name in relation_fields else ID_ERROR
        ),
        "SubmittedJobsProjection": SUBMITTED_ERROR,
        "ExecutionStartProjection": START_ERROR,
        "WorkerIdentityProjection": WORKER_ERROR,
    }[projection_name]
    assert_failure(kwargs, expected)


@pytest.mark.parametrize("projection_name", FIELD_NAMES)
@pytest.mark.parametrize("shape", ("missing", "extra", "order"))
def test_decoders_are_strictly_closed(projection_name: str, shape: str) -> None:
    raw = graph()["objects"][projection_name].as_dict()
    if shape == "missing":
        raw.pop(next(iter(raw)))
    elif shape == "extra":
        raw["extra"] = None
    else:
        raw = dict(reversed(tuple(raw.items())))
    with pytest.raises(ex.ExecutorProvenanceError):
        SURFACES[projection_name][1](raw)


def set_nested(mapping: dict[str, object], path: tuple[str | int, ...], value: object) -> None:
    cursor: object = mapping
    for component in path[:-1]:
        if isinstance(component, int):
            cursor = cast(list[object], cursor)[component]
        else:
            cursor = cast(dict[str, object], cursor)[component]
    final = path[-1]
    if isinstance(final, int):
        cast(list[object], cursor)[final] = value
    else:
        cast(dict[str, object], cursor)[final] = value


STRICT_VALUES: tuple[tuple[str, tuple[str | int, ...], object], ...] = (
    (EI, ("counter",), True),
    (EI, ("process_id",), 1.0),
    (EI, ("counter",), -1),
    (EI, ("process_id",), 2**64),
    (EI, ("process_nonce",), "A" * 64),
    (EI, ("process_started_at",), "2026-01-02T03:04:05Z"),
    (EI, ("process_started_at",), "2026-02-30T00:00:00.000000Z"),
    (EX, ("implementation_commit",), "5" * 39),
    (EX, ("role",), "not canonical"),
    (SJ, ("jobs",), ()),
    (SJ, ("jobs", 0, "projection", "arm", "arm_order"), True),
    (SJ, ("jobs", 0, "projection", "seed"), True),
    (SJ, ("jobs", 0, "projection", "seed"), 2**63),
    (SJ, ("jobs", 0, "projection", "submission_index"), True),
    (SJ, ("jobs", 0, "projection", "budget"), "f64:8000000000000000"),
    (SJ, ("runtime", "base_interpreter", "byte_count"), True),
    (SJ, ("runtime", "interpreter_identity_sha256"), h(70)),
    (SJ, ("runtime", "platform_identity_sha256"), h(70)),
    (SJ, ("runtime", "interpreter", "path"), "/other/python"),
    (SJ, ("runtime", "interpreter", "sha256"), h(70)),
    (SJ, ("runtime", "interpreter", "path"), "relative/python"),
    (SJ, ("runtime", "interpreter", "path"), r"C:/rde/python.exe"),
    (SJ, ("runtime", "interpreter", "path"), r"C:\rde\..\python.exe"),
    (SJ, ("runtime", "interpreter", "path"), r"C:\rde\\python.exe"),
    (SJ, ("runtime", "interpreter", "path"), "/opt/rde/python/"),
    (ES, ("started_at",), "2026-01-02T03:04:05.000000+00:00"),
    (WI, ("process_id",), True),
    (WI, ("thread_id",), True),
    (WI, ("thread_name",), "e\u0301"),
    (WI, ("thread_name",), "\ud800"),
)


@pytest.mark.parametrize(("projection_name", "path", "bad"), STRICT_VALUES)
def test_scalar_decoding_is_exact(
    projection_name: str,
    path: tuple[str | int, ...],
    bad: object,
) -> None:
    raw = graph()["objects"][projection_name].as_dict()
    set_nested(raw, path, bad)
    with pytest.raises(ex.ExecutorProvenanceError):
        SURFACES[projection_name][1](raw)


@pytest.mark.parametrize(
    "path",
    (r"C:\rde\python.exe", "C:\\", "/opt/rde/python", "/"),
)
def test_runtime_paths_are_host_neutral_for_both_canonical_families(path: str) -> None:
    submitted = cast(ex.SubmittedJobsProjection, graph()["objects"]["SubmittedJobsProjection"])
    runtime_value = runtime(path)
    mutated = replace(
        submitted,
        runtime=runtime_value,
        runtime_identity=protocol_hash("validation_evidence_runtime/v1", runtime_value.as_dict()),
    )
    assert ex.decode_submitted_jobs_projection(mutated.as_dict()) == mutated


def test_producer_submission_order_is_preserved_without_sorting() -> None:
    submitted = cast(ex.SubmittedJobsProjection, graph()["objects"]["SubmittedJobsProjection"])
    assert submitted.jobs[0].submitted_job_id > submitted.jobs[1].submitted_job_id
    decoded = ex.decode_submitted_jobs_projection(submitted.as_dict())
    assert decoded.jobs == submitted.jobs
    assert tuple(job.projection.submission_index for job in decoded.jobs) == (0, 1)


@pytest.mark.parametrize("case", ("duplicate", "reordered", "reindexed", "replaced"))
def test_submitted_jobs_reject_duplicate_reordered_reindexed_or_replaced_rows(
    case: str,
) -> None:
    submitted = cast(ex.SubmittedJobsProjection, graph()["objects"]["SubmittedJobsProjection"])
    first, second = submitted.jobs
    if case == "duplicate":
        jobs = (first, first)
    elif case == "reordered":
        jobs = (second, first)
    elif case == "reindexed":
        projection = replace(second.projection, submission_index=0)
        jobs = (first, ex.SubmittedJobProjection(ex.submitted_job_id(projection), projection))
    else:
        jobs = (first, replace(second, projection=replace(second.projection, seed=101)))
    with pytest.raises(ex.ExecutorProvenanceError):
        ex.decode_submitted_jobs_projection(replace(submitted, jobs=jobs).as_dict())


@pytest.mark.parametrize(
    ("key", "code"),
    (
        ("carried_execution_instance_identity", ID_ERROR),
        ("carried_execution_id", ID_ERROR),
        ("carried_submitted_jobs_sha256", SUBMITTED_ERROR),
        ("carried_execution_start_id", START_ERROR),
        ("worker_identity", WORKER_ERROR),
    ),
)
def test_every_carried_identity_is_recomputed(key: str, code: str) -> None:
    kwargs = dict(graph()["kwargs"])
    if key == "worker_identity":
        observations = list(kwargs["workers_in_actual_delivery_order"])
        observations[0] = (observations[0][0], h(60))
        kwargs["workers_in_actual_delivery_order"] = tuple(observations)
    else:
        kwargs[key] = h(60)
    assert_failure(kwargs, code)


class ProjectionImpostor:
    def __init__(self, mapping: dict[str, object]) -> None:
        self.mapping = mapping

    def as_dict(self) -> dict[str, object]:
        return self.mapping


@pytest.mark.parametrize(
    ("key", "code"),
    (("execution_instance", ID_ERROR), ("execution_start", START_ERROR)),
)
def test_projection_like_impostors_are_not_accepted_as_exact_types(key: str, code: str) -> None:
    kwargs = dict(graph()["kwargs"])
    kwargs[key] = ProjectionImpostor(kwargs[key].as_dict())
    assert_failure(kwargs, code)


def test_execution_instance_occurrence_and_issuer_relations_are_distinct() -> None:
    baseline = graph()
    execution = baseline["objects"][EX]
    for change, code in (({"counter": 8}, ID_ERROR), ({"issuer_identity": h(61)}, RELATION_ERROR)):
        foreign = replace(execution.execution_instance, **change)
        mutated = replace(
            execution,
            execution_instance=foreign,
            execution_instance_identity=ex.execution_instance_identity(foreign),
        )
        kwargs = dict(baseline["kwargs"])
        kwargs["execution"] = mutated
        assert_failure(kwargs, code)


def test_execution_start_must_not_precede_the_process_occurrence() -> None:
    kwargs = dict(graph()["kwargs"])
    start = replace(kwargs["execution_start"], started_at="2026-01-02T03:04:04.999999Z")
    kwargs["execution_start"] = start
    kwargs["carried_execution_start_id"] = ex.execution_start_id(start)
    assert_failure(kwargs, START_ERROR)


@pytest.mark.parametrize("thread_id", (0, 9_999_999))
def test_zero_or_fixed_get_ident_style_thread_substitution_is_rejected(thread_id: int) -> None:
    kwargs = dict(graph()["kwargs"])
    observations = list(kwargs["workers_in_actual_delivery_order"])
    worker = replace(observations[0][0], thread_id=thread_id)
    observations[0] = (worker, ex.worker_identity(worker))
    kwargs["workers_in_actual_delivery_order"] = tuple(observations)
    assert_failure(kwargs, WORKER_ERROR)


def uncalled(*_args: object, **_kwargs: object) -> Any:
    raise AssertionError("a later identity predicate was called")


STAGES = (
    ("instance", ID_ERROR),
    ("execution", RELATION_ERROR),
    ("submitted", SUBMITTED_ERROR),
    ("start", START_ERROR),
    ("worker", WORKER_ERROR),
)
IDENTITY_ORDER = words(
    "execution_instance_identity execution_id submitted_jobs_sha256 execution_start_id "
    "worker_identity"
)


@pytest.mark.parametrize(("stage", "code"), STAGES)
def test_compound_faults_follow_3g_3h_3i_3j_predicate_order(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    code: str,
) -> None:
    kwargs = dict(graph()["kwargs"])
    worker_observations = list(kwargs["workers_in_actual_delivery_order"])
    worker_observations[0] = (replace(worker_observations[0][0], process_id=0), h(63))
    kwargs["workers_in_actual_delivery_order"] = tuple(worker_observations)
    if stage in {"instance", "execution", "submitted", "start"}:
        kwargs["execution_start"] = replace(
            kwargs["execution_start"],
            started_at="2026-01-02T03:04:04.999999Z",
        )
    if stage in {"instance", "execution", "submitted"}:
        kwargs["submitted_jobs"] = replace(kwargs["submitted_jobs"], configuration_sha256=h(63))
    if stage in {"instance", "execution"}:
        kwargs["execution"] = replace(kwargs["execution"], execution_specification_id=h(63))
    if stage == "instance":
        kwargs["execution_instance"] = replace(kwargs["execution_instance"], process_id=0)
    for identity_name in IDENTITY_ORDER[[item[0] for item in STAGES].index(stage) :]:
        monkeypatch.setattr(ex, identity_name, uncalled)
    assert_failure(kwargs, code)


def test_all_worker_native_observations_precede_any_predecessor_or_identity_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = dict(graph()["kwargs"])
    first, second = kwargs["workers_in_actual_delivery_order"]
    earlier_predecessor_fault = replace(first[0], validation_run_id=h(63))
    later_native_fault = replace(second[0], process_id=0)
    kwargs["workers_in_actual_delivery_order"] = (
        (earlier_predecessor_fault, h(63)),
        (later_native_fault, h(63)),
    )
    monkeypatch.setattr(ex, "worker_identity", uncalled)
    failure = assert_failure(kwargs, WORKER_ERROR)
    assert "workers[1]" in str(failure)


def test_submission_envelope_fault_precedes_nested_runtime_integrity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = dict(graph()["kwargs"])
    submitted = kwargs["submitted_jobs"]
    bad_runtime = replace(submitted.runtime, interpreter_identity_sha256=h(63))
    kwargs["submitted_jobs"] = replace(submitted, configuration_sha256=h(63), runtime=bad_runtime)
    real_hash = protocol_hash
    runtime_domains = words(
        "validation_evidence_runtime/v1 pytest_interpreter_identity/v1 pytest_platform_identity/v1"
    )

    def guarded_hash(domain: str, value: object) -> str:
        if domain in runtime_domains:
            raise AssertionError("nested runtime predicate was called")
        return real_hash(domain, value)

    monkeypatch.setattr(ex, "protocol_hash", guarded_hash)
    assert_failure(kwargs, SUBMITTED_ERROR)


def test_validation_uses_no_workload_scoring_evidence_capability_or_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = words(
        "execute_deterministic_map validation_job_projection "
        "_issue_fixture_execution_specification _issue_execution_specification "
        "_require_production_executor_implementation _allocate_production_plan_capability"
    )
    for name in forbidden:
        monkeypatch.setattr(ex, name, uncalled)
    ex.validate_stage2d2_execution_foundations(**graph()["kwargs"])
