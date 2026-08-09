from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError, fields, replace
from typing import Any, Final, cast

import pytest

from research_decision_engine.benchmarks import broader_execution as ex
from research_decision_engine.benchmarks import broader_returned_run as returned
from research_decision_engine.benchmarks.broader_protocol import protocol_hash
from tests.test_broader_p2_returned_result import (
    _job,
    _result,
)
from tests.test_broader_p2_returned_result import (
    graph as phase_b_graph,
)

BATCH_ERROR: Final = "EXECUTION_RESULT_BATCH_ID_MISMATCH"
COMPLETION_ERROR: Final = "EXECUTION_COMPLETION_ID_MISMATCH"
MAPPING_ERROR: Final = "EXECUTION_JOB_RESULT_MAPPING_MISMATCH"
RESULT_ERROR: Final = "EXECUTION_RETURNED_RESULT_ID_MISMATCH"
SCIENTIFIC_ERROR: Final = "EXECUTION_RETURNED_SCIENTIFIC_RECORD_INVALID"
BAD: Final = "f" * 64
ALT: Final = "e" * 64
COMPLETED: Final = "2026-01-02T03:04:07.000000Z"

BATCH_FIELDS: Final = (
    "execution_id",
    "execution_specification_id",
    "job_result_mapping",
    "result_payload_sha256_in_delivery_order",
    "returned_result_ids_in_delivery_order",
    "schema_version",
    "validation_authority_id",
    "validation_run_id",
)
COMPLETION_FIELDS: Final = (
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
TYPE_NAMES: Final = {
    "ResultBatchProjection": (
        "str",
        "str",
        "JobResultMapping",
        "tuple[str,...]",
        "tuple[str,...]",
        "Literal['broader-replication-result-batch/v1']",
        "str",
        "str",
    ),
    "ExecutionCompletionProjection": (
        "str",
        "str",
        "str",
        "str",
        "Literal['success']",
        "JobResultMapping",
        "tuple[str,...]",
        "tuple[str,...]",
        "Literal['broader-replication-execution-completion/v1']",
        "str",
        "str",
    ),
}
FIELD_CASES: Final = tuple(
    ("ResultBatchProjection", field_name) for field_name in BATCH_FIELDS
) + tuple(("ExecutionCompletionProjection", field_name) for field_name in COMPLETION_FIELDS)


def _accepted_observations(kwargs: dict[str, Any]) -> tuple[ex.ReturnedResultObservation, ...]:
    projections = cast(
        tuple[ex.ReturnedResultProjection, ...],
        kwargs["returned_result_projections_in_actual_delivery_order"],
    )
    result_ids = cast(
        tuple[str, ...],
        kwargs["carried_returned_result_ids_in_actual_delivery_order"],
    )
    payloads = cast(
        tuple[returned.ReturnedRunProjection, ...],
        kwargs["returned_runs_in_actual_delivery_order"],
    )
    return tuple(
        (projection, result_id, payload)
        for projection, result_id, payload in zip(
            projections,
            result_ids,
            payloads,
            strict=True,
        )
    )


def _unique_worker_ids(kwargs: dict[str, Any]) -> tuple[str, ...]:
    workers = cast(
        tuple[tuple[ex.WorkerIdentityProjection, str], ...],
        kwargs["workers_in_actual_delivery_order"],
    )
    observed: list[str] = []
    for _worker, worker_id in workers:
        if worker_id not in observed:
            observed.append(worker_id)
    return tuple(observed)


def _attach_c1(
    phase_b_kwargs: dict[str, Any],
    *,
    mapping: ex.JobResultMapping | None = None,
    completed_at: str = COMPLETED,
) -> dict[str, Any]:
    kwargs = dict(phase_b_kwargs)
    observations = _accepted_observations(kwargs)
    if mapping is None:
        submitted = cast(ex.SubmittedJobsProjection, kwargs["submitted_jobs"])
        mapping = ex.build_job_result_mapping(submitted.jobs, observations)
    execution = cast(ex.ExecutionIdentityProjection, kwargs["execution"])
    result_batch = ex.ResultBatchProjection(
        execution_id=cast(str, kwargs["carried_execution_id"]),
        execution_specification_id=execution.execution_specification_id,
        job_result_mapping=mapping,
        result_payload_sha256_in_delivery_order=tuple(
            observation[0].result_payload_sha256 for observation in observations
        ),
        returned_result_ids_in_delivery_order=tuple(observation[1] for observation in observations),
        schema_version="broader-replication-result-batch/v1",
        validation_authority_id=execution.validation_authority_id,
        validation_run_id=execution.validation_run_id,
    )
    completion = ex.ExecutionCompletionProjection(
        completed_at=completed_at,
        execution_id=cast(str, kwargs["carried_execution_id"]),
        execution_specification_id=execution.execution_specification_id,
        execution_start_id=cast(str, kwargs["carried_execution_start_id"]),
        execution_status="success",
        job_result_mapping=mapping,
        observed_worker_ids=_unique_worker_ids(kwargs),
        returned_result_ids_in_delivery_order=tuple(observation[1] for observation in observations),
        schema_version="broader-replication-execution-completion/v1",
        validation_authority_id=execution.validation_authority_id,
        validation_run_id=execution.validation_run_id,
    )
    kwargs.update(
        job_result_mapping=mapping,
        result_batch=result_batch,
        carried_result_batch_id=ex.result_batch_id(result_batch),
        observed_execution_status="success",
        observed_completed_at=completed_at,
        execution_completion=completion,
        carried_execution_completion_id=ex.execution_completion_id(completion),
    )
    return kwargs


def c1_kwargs() -> dict[str, Any]:
    return _attach_c1(dict(phase_b_graph()["kwargs"]), mapping=phase_b_graph()["mapping"])


def invoke(
    kwargs: dict[str, Any],
) -> tuple[tuple[ex.ReturnedResultObservation, ...], ex.JobResultMapping]:
    return ex.validate_stage2d2_result_batch_completion(**kwargs)


def assert_failure(kwargs: dict[str, Any], code: str) -> ex.ExecutorProvenanceError:
    with pytest.raises(ex.ExecutorProvenanceError) as captured:
        invoke(kwargs)
    assert captured.value.error_code == code
    assert not getattr(captured.value, "workload_started", False)
    assert not getattr(captured.value, "evidence_checkpointed", False)
    return captured.value


@pytest.mark.parametrize(
    ("projection_name", "field_names", "schema", "domain"),
    (
        (
            "ResultBatchProjection",
            BATCH_FIELDS,
            "broader-replication-result-batch/v1",
            "validation_evidence_result_batch/v1",
        ),
        (
            "ExecutionCompletionProjection",
            COMPLETION_FIELDS,
            "broader-replication-execution-completion/v1",
            "validation_evidence_execution_completion/v1",
        ),
    ),
)
def test_exact_projection_contracts(
    projection_name: str,
    field_names: tuple[str, ...],
    schema: str,
    domain: str,
) -> None:
    kwargs = c1_kwargs()
    projection = kwargs[
        "result_batch" if projection_name == "ResultBatchProjection" else "execution_completion"
    ]
    decoder = (
        ex.decode_result_batch_projection
        if projection_name == "ResultBatchProjection"
        else ex.decode_execution_completion_projection
    )
    identity = (
        ex.result_batch_id
        if projection_name == "ResultBatchProjection"
        else ex.execution_completion_id
    )
    annotations = tuple(
        annotation.replace(", ", ",") for annotation in type(projection).__annotations__.values()
    )

    assert tuple(field.name for field in fields(projection)) == field_names
    assert annotations == TYPE_NAMES[projection_name]
    assert tuple(projection.as_dict()) == field_names
    assert projection.schema_version == schema
    assert decoder(projection.as_dict()) == projection
    assert identity(projection) == protocol_hash(domain, projection.as_dict())
    assert not hasattr(projection, "__dict__")
    with pytest.raises(FrozenInstanceError):
        setattr(projection, field_names[0], None)
    with pytest.raises(ex.ExecutorProvenanceError):
        decoder([])
    with pytest.raises(ex.ExecutorProvenanceError):
        identity(cast(Any, projection.as_dict()))


def _changed_field(projection: object, field_name: str) -> dict[str, object]:
    raw = cast(dict[str, object], cast(Any, projection).as_dict())
    if field_name == "completed_at":
        raw[field_name] = "2026-01-02T03:04:08.000000Z"
    elif field_name in {"schema_version", "execution_status"}:
        raw[field_name] = "invalid"
    elif type(raw[field_name]) is list:
        values = cast(list[object], raw[field_name])
        raw[field_name] = list(reversed(values)) if len(values) > 1 else values + [BAD]
    else:
        raw[field_name] = BAD if raw[field_name] != BAD else ALT
    return raw


@pytest.mark.parametrize(("projection_name", "field_name"), FIELD_CASES)
def test_every_field_is_strictly_decoded_and_identity_bound(
    projection_name: str,
    field_name: str,
) -> None:
    kwargs = c1_kwargs()
    projection = kwargs[
        "result_batch" if projection_name == "ResultBatchProjection" else "execution_completion"
    ]
    decoder = (
        ex.decode_result_batch_projection
        if projection_name == "ResultBatchProjection"
        else ex.decode_execution_completion_projection
    )
    identity = (
        ex.result_batch_id
        if projection_name == "ResultBatchProjection"
        else ex.execution_completion_id
    )
    identity = cast(Any, identity)
    original_id = identity(projection)
    try:
        changed = decoder(_changed_field(projection, field_name))
    except ex.ExecutorProvenanceError:
        assert field_name in {"schema_version", "execution_status"}
    else:
        assert changed != projection
        assert identity(changed) != original_id


STRICT_CASES: Final = (
    ("batch-missing", "ResultBatchProjection"),
    ("batch-extra", "ResultBatchProjection"),
    ("batch-reordered-fields", "ResultBatchProjection"),
    ("mapping-row-tuple", "ResultBatchProjection"),
    ("payload-hash-tuple", "ResultBatchProjection"),
    ("bad-completion-time", "ExecutionCompletionProjection"),
    ("bad-completion-status", "ExecutionCompletionProjection"),
    ("duplicate-observed-worker", "ExecutionCompletionProjection"),
)


@pytest.mark.parametrize(("case", "projection_name"), STRICT_CASES)
def test_decoders_reject_noncanonical_or_nonclosed_values(
    case: str,
    projection_name: str,
) -> None:
    kwargs = c1_kwargs()
    projection = kwargs[
        "result_batch" if projection_name == "ResultBatchProjection" else "execution_completion"
    ]
    raw = projection.as_dict()
    decoder = (
        ex.decode_result_batch_projection
        if projection_name == "ResultBatchProjection"
        else ex.decode_execution_completion_projection
    )
    if case == "batch-missing":
        raw.pop("execution_id")
    elif case == "batch-extra":
        raw["extra"] = None
    elif case == "batch-reordered-fields":
        raw = dict(reversed(tuple(raw.items())))
    elif case == "mapping-row-tuple":
        mapping = cast(list[object], raw["job_result_mapping"])
        mapping[0] = tuple(cast(list[object], mapping[0]))
    elif case == "payload-hash-tuple":
        raw["result_payload_sha256_in_delivery_order"] = tuple(
            cast(list[object], raw["result_payload_sha256_in_delivery_order"])
        )
    elif case == "bad-completion-time":
        raw["completed_at"] = "2026-01-02T03:04:07Z"
    elif case == "bad-completion-status":
        raw["execution_status"] = "failed"
    else:
        workers = cast(list[str], raw["observed_worker_ids"])
        raw["observed_worker_ids"] = [workers[0], workers[0]]

    with pytest.raises(ex.ExecutorProvenanceError) as captured:
        decoder(raw)
    assert captured.value.error_code == (
        BATCH_ERROR if projection_name == "ResultBatchProjection" else COMPLETION_ERROR
    )


@pytest.mark.parametrize(
    ("projection_name", "first_field", "bad_first", "expected_path"),
    (
        (
            "ResultBatchProjection",
            "execution_id",
            "not-an-h64",
            "result_batch.execution_id",
        ),
        (
            "ExecutionCompletionProjection",
            "completed_at",
            "not-a-timestamp",
            "execution_completion.completed_at",
        ),
    ),
)
def test_raw_compound_decoder_faults_follow_displayed_field_order(
    projection_name: str,
    first_field: str,
    bad_first: str,
    expected_path: str,
) -> None:
    kwargs = c1_kwargs()
    projection = kwargs[
        "result_batch" if projection_name == "ResultBatchProjection" else "execution_completion"
    ]
    decoder = (
        ex.decode_result_batch_projection
        if projection_name == "ResultBatchProjection"
        else ex.decode_execution_completion_projection
    )
    raw = projection.as_dict()
    raw[first_field] = bad_first
    raw["job_result_mapping"] = {}

    with pytest.raises(ex.ExecutorProvenanceError) as captured:
        decoder(raw)
    expected_code = BATCH_ERROR if projection_name == "ResultBatchProjection" else COMPLETION_ERROR
    assert captured.value.error_code == expected_code
    assert captured.value.validation_layer == (
        "result_batch" if projection_name == "ResultBatchProjection" else "execution_completion"
    )
    assert str(captured.value).startswith(f"{expected_code} at {expected_path}:")


def test_valid_c1_calls_phase_b_once_and_enters_no_later_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = c1_kwargs()
    real_phase_b = ex.validate_stage2d2_returned_results
    calls = 0

    def tracked_phase_b(**phase_b_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real_phase_b(**cast(Any, phase_b_kwargs))

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError(
            "C2, Stage-2E, workload, scoring, evidence, or persistence was entered"
        )

    monkeypatch.setattr(ex, "validate_stage2d2_returned_results", tracked_phase_b)
    for name in (
        "build_returned_results_projection",
        "returned_results_sha256",
        "build_worker_result_order_projection",
        "worker_result_order_sha256",
        "executor_attestation_id",
        "run_arm",
        "score_candidates",
        "write_validation_evidence",
        "ExecutionEvidenceReader",
    ):
        monkeypatch.setattr(ex, name, forbidden, raising=False)

    observations, mapping = invoke(kwargs)
    assert calls == 1
    assert observations == phase_b_graph()["observations"]
    assert mapping == phase_b_graph()["mapping"]
    assert type(observations) is tuple
    assert type(mapping) is tuple


def test_delivery_permutation_changes_delivery_members_but_not_submission_mapping() -> None:
    baseline = c1_kwargs()
    phase_b_kwargs = dict(phase_b_graph()["kwargs"])
    for name in (
        "expected_workers_in_actual_delivery_order",
        "workers_in_actual_delivery_order",
        "returned_domains_in_actual_delivery_order",
        "returned_runs_in_actual_delivery_order",
        "returned_result_projections_in_actual_delivery_order",
        "carried_returned_result_ids_in_actual_delivery_order",
    ):
        phase_b_kwargs[name] = tuple(reversed(phase_b_kwargs[name]))
    permuted = _attach_c1(phase_b_kwargs)

    permuted_observations, permuted_mapping = invoke(permuted)
    baseline_batch = cast(ex.ResultBatchProjection, baseline["result_batch"])
    permuted_batch = cast(ex.ResultBatchProjection, permuted["result_batch"])
    baseline_completion = cast(ex.ExecutionCompletionProjection, baseline["execution_completion"])
    permuted_completion = cast(ex.ExecutionCompletionProjection, permuted["execution_completion"])

    assert permuted_mapping == baseline["job_result_mapping"]
    assert permuted_observations == tuple(reversed(phase_b_graph()["observations"]))
    assert permuted_batch.job_result_mapping == baseline_batch.job_result_mapping
    assert permuted_batch.returned_result_ids_in_delivery_order == tuple(
        reversed(baseline_batch.returned_result_ids_in_delivery_order)
    )
    assert permuted_batch.result_payload_sha256_in_delivery_order == tuple(
        reversed(baseline_batch.result_payload_sha256_in_delivery_order)
    )
    assert ex.result_batch_id(permuted_batch) != ex.result_batch_id(baseline_batch)
    assert permuted_completion.job_result_mapping == baseline_completion.job_result_mapping
    assert permuted_completion.returned_result_ids_in_delivery_order == tuple(
        reversed(baseline_completion.returned_result_ids_in_delivery_order)
    )
    assert permuted_completion.observed_worker_ids == tuple(
        reversed(baseline_completion.observed_worker_ids)
    )
    assert ex.execution_completion_id(permuted_completion) != ex.execution_completion_id(
        baseline_completion
    )
    assert (
        "acceptance_order"
        not in inspect.signature(ex.validate_stage2d2_result_batch_completion).parameters
    )


def test_duplicate_content_and_repeated_workers_preserve_first_delivery_appearance() -> None:
    baseline = phase_b_graph()
    kwargs = dict(baseline["kwargs"])
    domain = baseline["domains"][0]
    payload = baseline["payloads"][0]
    jobs = tuple(_job(payload, index) for index in range(3))
    submitted = replace(kwargs["submitted_jobs"], jobs=jobs)
    kwargs.update(
        expected_submitted_jobs=submitted,
        submitted_jobs=submitted,
        carried_submitted_jobs_sha256=ex.submitted_jobs_sha256(submitted),
    )
    results = tuple(_result(kwargs, job, payload) for job in jobs)
    delivery_indexes = (2, 0, 1)
    delivered_results = tuple(results[index] for index in delivery_indexes)
    delivered_ids = tuple(ex.returned_result_id(result) for result in delivered_results)
    base_workers = cast(
        tuple[tuple[ex.WorkerIdentityProjection, str], ...],
        baseline["kwargs"]["workers_in_actual_delivery_order"],
    )
    delivered_workers = (base_workers[1], base_workers[0], base_workers[1])
    kwargs.update(
        expected_workers_in_actual_delivery_order=tuple(row[0] for row in delivered_workers),
        workers_in_actual_delivery_order=delivered_workers,
        returned_domains_in_actual_delivery_order=(domain, domain, domain),
        returned_runs_in_actual_delivery_order=(payload, payload, payload),
        returned_result_projections_in_actual_delivery_order=delivered_results,
        carried_returned_result_ids_in_actual_delivery_order=delivered_ids,
    )
    complete = _attach_c1(kwargs)

    observations, mapping = invoke(complete)
    batch = cast(ex.ResultBatchProjection, complete["result_batch"])
    completion = cast(ex.ExecutionCompletionProjection, complete["execution_completion"])
    assert tuple(row[0] for row in mapping) == tuple(job.submitted_job_id for job in jobs)
    assert tuple(row[1] for row in mapping) == tuple(
        ex.returned_result_id(result) for result in results
    )
    assert tuple(observation[1] for observation in observations) == delivered_ids
    assert len(set(batch.result_payload_sha256_in_delivery_order)) == 1
    assert len(set(batch.returned_result_ids_in_delivery_order)) == 3
    assert completion.observed_worker_ids == (base_workers[1][1], base_workers[0][1])
    assert len(completion.observed_worker_ids) == 2


def test_submission_acceptance_delivery_and_first_worker_orders_are_all_distinct() -> None:
    baseline = phase_b_graph()
    kwargs = dict(baseline["kwargs"])
    domain = baseline["domains"][0]
    payload = baseline["payloads"][0]
    submission_order = (0, 1, 2, 3)
    acceptance_order = (1, 3, 0, 2)
    delivery_order = (2, 0, 3, 1)
    unique_first_worker_order = (3, 2, 1, 0)
    assert (
        len(
            {
                submission_order,
                acceptance_order,
                delivery_order,
                unique_first_worker_order,
            }
        )
        == 4
    )

    jobs = tuple(_job(payload, index) for index in submission_order)
    accepted_job_ids = tuple(jobs[index].submitted_job_id for index in acceptance_order)
    submitted = replace(kwargs["submitted_jobs"], jobs=jobs)
    kwargs.update(
        expected_submitted_jobs=submitted,
        submitted_jobs=submitted,
        carried_submitted_jobs_sha256=ex.submitted_jobs_sha256(submitted),
    )
    results = tuple(_result(kwargs, job, payload) for job in jobs)
    delivered_results = tuple(results[index] for index in delivery_order)
    delivered_ids = tuple(ex.returned_result_id(result) for result in delivered_results)
    base_worker = cast(
        tuple[tuple[ex.WorkerIdentityProjection, str], ...],
        baseline["kwargs"]["workers_in_actual_delivery_order"],
    )[0][0]
    worker_projections = tuple(
        replace(
            base_worker,
            thread_id=301 + index,
            thread_name=f"four-order-worker-{index}",
        )
        for index in submission_order
    )
    worker_observations = tuple(
        (worker, ex.worker_identity(worker)) for worker in worker_projections
    )
    delivered_workers = tuple(worker_observations[index] for index in unique_first_worker_order)
    kwargs.update(
        expected_workers_in_actual_delivery_order=tuple(row[0] for row in delivered_workers),
        workers_in_actual_delivery_order=delivered_workers,
        returned_domains_in_actual_delivery_order=(domain,) * 4,
        returned_runs_in_actual_delivery_order=(payload,) * 4,
        returned_result_projections_in_actual_delivery_order=delivered_results,
        carried_returned_result_ids_in_actual_delivery_order=delivered_ids,
    )
    complete = _attach_c1(kwargs)

    _observations, mapping = invoke(complete)
    batch = cast(ex.ResultBatchProjection, complete["result_batch"])
    completion = cast(ex.ExecutionCompletionProjection, complete["execution_completion"])
    assert tuple(row[0] for row in mapping) == tuple(
        jobs[index].submitted_job_id for index in submission_order
    )
    assert accepted_job_ids != tuple(row[0] for row in mapping)
    assert batch.returned_result_ids_in_delivery_order == tuple(
        ex.returned_result_id(results[index]) for index in delivery_order
    )
    assert completion.observed_worker_ids == tuple(
        worker_observations[index][1] for index in unique_first_worker_order
    )
    parameters = inspect.signature(ex.validate_stage2d2_result_batch_completion).parameters
    assert all("accept" not in name for name in parameters)
    assert all("accept" not in field.name for field in fields(batch))
    assert all("accept" not in field.name for field in fields(completion))


@pytest.mark.parametrize(
    ("case", "code"),
    (
        ("mapping-missing", MAPPING_ERROR),
        ("mapping-extra", MAPPING_ERROR),
        ("mapping-reordered", MAPPING_ERROR),
        ("mapping-foreign", MAPPING_ERROR),
        ("batch-mapping", BATCH_ERROR),
        ("batch-result-order", BATCH_ERROR),
        ("batch-payload-order", BATCH_ERROR),
        ("batch-delivery-missing", BATCH_ERROR),
        ("batch-delivery-extra", BATCH_ERROR),
        ("batch-result-duplicate", BATCH_ERROR),
    ),
)
def test_mapping_and_result_batch_attacks(case: str, code: str) -> None:
    kwargs = c1_kwargs()
    mapping = cast(ex.JobResultMapping, kwargs["job_result_mapping"])
    if case == "mapping-missing":
        kwargs["job_result_mapping"] = mapping[:-1]
    elif case == "mapping-extra":
        kwargs["job_result_mapping"] = mapping + (mapping[0],)
    elif case == "mapping-reordered":
        kwargs["job_result_mapping"] = tuple(reversed(mapping))
    elif case == "mapping-foreign":
        kwargs["job_result_mapping"] = ((BAD, mapping[0][1]),) + mapping[1:]
    else:
        batch = cast(ex.ResultBatchProjection, kwargs["result_batch"])
        if case == "batch-mapping":
            batch = replace(batch, job_result_mapping=tuple(reversed(mapping)))
        elif case == "batch-result-order":
            batch = replace(
                batch,
                returned_result_ids_in_delivery_order=tuple(
                    reversed(batch.returned_result_ids_in_delivery_order)
                ),
            )
        elif case == "batch-payload-order":
            batch = replace(
                batch,
                result_payload_sha256_in_delivery_order=tuple(
                    reversed(batch.result_payload_sha256_in_delivery_order)
                ),
            )
        elif case == "batch-delivery-missing":
            batch = replace(
                batch,
                result_payload_sha256_in_delivery_order=(
                    batch.result_payload_sha256_in_delivery_order[:-1]
                ),
                returned_result_ids_in_delivery_order=(
                    batch.returned_result_ids_in_delivery_order[:-1]
                ),
            )
        elif case == "batch-delivery-extra":
            batch = replace(
                batch,
                result_payload_sha256_in_delivery_order=(
                    batch.result_payload_sha256_in_delivery_order + (BAD,)
                ),
                returned_result_ids_in_delivery_order=(
                    batch.returned_result_ids_in_delivery_order + (BAD,)
                ),
            )
        else:
            batch = replace(
                batch,
                returned_result_ids_in_delivery_order=(
                    batch.returned_result_ids_in_delivery_order[0],
                    batch.returned_result_ids_in_delivery_order[0],
                ),
            )
        kwargs["result_batch"] = batch
        kwargs["carried_result_batch_id"] = protocol_hash(
            "validation_evidence_result_batch/v1",
            batch.as_dict(),
        )
    assert_failure(kwargs, code)


def test_sorted_result_ids_cannot_replace_observed_delivery_order() -> None:
    candidates: tuple[dict[str, Any], ...] = (c1_kwargs(),)
    reversed_phase_b = dict(phase_b_graph()["kwargs"])
    for name in (
        "expected_workers_in_actual_delivery_order",
        "workers_in_actual_delivery_order",
        "returned_domains_in_actual_delivery_order",
        "returned_runs_in_actual_delivery_order",
        "returned_result_projections_in_actual_delivery_order",
        "carried_returned_result_ids_in_actual_delivery_order",
    ):
        reversed_phase_b[name] = tuple(reversed(reversed_phase_b[name]))
    candidates += (_attach_c1(reversed_phase_b),)
    kwargs = next(
        candidate
        for candidate in candidates
        if cast(
            ex.ResultBatchProjection,
            candidate["result_batch"],
        ).returned_result_ids_in_delivery_order
        != tuple(
            sorted(
                cast(
                    ex.ResultBatchProjection,
                    candidate["result_batch"],
                ).returned_result_ids_in_delivery_order
            )
        )
    )
    batch = cast(ex.ResultBatchProjection, kwargs["result_batch"])
    sorted_batch = replace(
        batch,
        returned_result_ids_in_delivery_order=tuple(
            sorted(batch.returned_result_ids_in_delivery_order)
        ),
    )
    kwargs["result_batch"] = sorted_batch
    kwargs["carried_result_batch_id"] = ex.result_batch_id(sorted_batch)
    assert_failure(kwargs, BATCH_ERROR)


def test_historical_raw_result_order_hash_is_not_a_result_batch_id() -> None:
    kwargs = c1_kwargs()
    batch = cast(ex.ResultBatchProjection, kwargs["result_batch"])
    historical = ex._identity_digest(batch.returned_result_ids_in_delivery_order)
    assert historical != ex.result_batch_id(batch)
    kwargs["carried_result_batch_id"] = historical
    assert_failure(kwargs, BATCH_ERROR)


def test_foreign_execution_specification_authority_and_run_relations_are_rejected() -> None:
    for field_name in (
        "execution_id",
        "execution_specification_id",
        "validation_authority_id",
        "validation_run_id",
    ):
        batch_kwargs = c1_kwargs()
        batch = replace(
            cast(ex.ResultBatchProjection, batch_kwargs["result_batch"]),
            **cast(Any, {field_name: BAD}),
        )
        batch_kwargs["result_batch"] = batch
        batch_kwargs["carried_result_batch_id"] = ex.result_batch_id(batch)
        assert_failure(batch_kwargs, BATCH_ERROR)

    for field_name in (
        "execution_id",
        "execution_specification_id",
        "execution_start_id",
        "validation_authority_id",
        "validation_run_id",
    ):
        completion_kwargs = c1_kwargs()
        completion = replace(
            cast(
                ex.ExecutionCompletionProjection,
                completion_kwargs["execution_completion"],
            ),
            **cast(Any, {field_name: BAD}),
        )
        completion_kwargs["execution_completion"] = completion
        completion_kwargs["carried_execution_completion_id"] = ex.execution_completion_id(
            completion
        )
        assert_failure(completion_kwargs, COMPLETION_ERROR)


@pytest.mark.parametrize(
    ("case", "value"),
    (
        ("status", "failed"),
        ("status", "timed_out"),
        ("status", "cancelled"),
        ("status", "incomplete"),
        ("timestamp-invalid", "2026-01-02T03:04:07Z"),
        ("timestamp-before-start", "2026-01-02T03:04:05.999999Z"),
        ("timestamp-mismatch", "2026-01-02T03:04:08.000000Z"),
    ),
)
def test_only_exact_observed_complete_success_and_timestamp_are_accepted(
    case: str,
    value: str,
) -> None:
    kwargs = c1_kwargs()
    if case == "status":
        kwargs["observed_execution_status"] = value
    else:
        kwargs["observed_completed_at"] = value
    assert_failure(kwargs, COMPLETION_ERROR)


@pytest.mark.parametrize(
    "case",
    (
        "mapping",
        "result-order",
        "worker-order",
        "missing-worker",
        "extra-worker",
        "foreign-worker",
    ),
)
def test_completion_mapping_delivery_and_unique_worker_attacks(case: str) -> None:
    kwargs = c1_kwargs()
    completion = cast(ex.ExecutionCompletionProjection, kwargs["execution_completion"])
    if case == "mapping":
        completion = replace(
            completion,
            job_result_mapping=tuple(reversed(completion.job_result_mapping)),
        )
    elif case == "result-order":
        completion = replace(
            completion,
            returned_result_ids_in_delivery_order=tuple(
                reversed(completion.returned_result_ids_in_delivery_order)
            ),
        )
    elif case == "worker-order":
        completion = replace(
            completion,
            observed_worker_ids=tuple(reversed(completion.observed_worker_ids)),
        )
    elif case == "missing-worker":
        completion = replace(
            completion,
            observed_worker_ids=completion.observed_worker_ids[:-1],
        )
    elif case == "extra-worker":
        completion = replace(
            completion,
            observed_worker_ids=completion.observed_worker_ids + (BAD,),
        )
    else:
        completion = replace(
            completion,
            observed_worker_ids=(BAD,) + completion.observed_worker_ids[1:],
        )
    kwargs["execution_completion"] = completion
    kwargs["carried_execution_completion_id"] = ex.execution_completion_id(completion)
    assert_failure(kwargs, COMPLETION_ERROR)


def test_nested_scientific_mutation_beats_every_recomputed_c1_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = dict(phase_b_graph()["kwargs"])
    payloads = list(kwargs["returned_runs_in_actual_delivery_order"])
    payloads[0] = replace(payloads[0], run_id="forged-run")
    kwargs["returned_runs_in_actual_delivery_order"] = tuple(payloads)
    results = list(kwargs["returned_result_projections_in_actual_delivery_order"])
    payload_hash = protocol_hash(
        "validation_evidence_returned_run_payload/v1",
        returned.projection_as_dict(payloads[0]),
    )
    results[0] = replace(results[0], result_payload_sha256=payload_hash)
    result_ids = list(kwargs["carried_returned_result_ids_in_actual_delivery_order"])
    result_ids[0] = ex.returned_result_id(results[0])
    kwargs["returned_result_projections_in_actual_delivery_order"] = tuple(results)
    kwargs["carried_returned_result_ids_in_actual_delivery_order"] = tuple(result_ids)
    submitted = cast(ex.SubmittedJobsProjection, kwargs["submitted_jobs"])
    mapping = ex.build_job_result_mapping(submitted.jobs, _accepted_observations(kwargs))
    complete = _attach_c1(kwargs, mapping=mapping)

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("3l identity work ran after a nested 3j scientific failure")

    monkeypatch.setattr(ex, "result_batch_id", forbidden)
    monkeypatch.setattr(ex, "execution_completion_id", forbidden)
    assert_failure(complete, SCIENTIFIC_ERROR)


COMPOUND_CASES: Final = (
    ("returned-result+batch", RESULT_ERROR, "decode_result_batch_projection"),
    ("mapping+batch", MAPPING_ERROR, "decode_result_batch_projection"),
    ("batch-relation+batch-id", BATCH_ERROR, "result_batch_id"),
    ("batch-id+completion-status", BATCH_ERROR, "decode_execution_completion_projection"),
    ("completion-status+completion-id", COMPLETION_ERROR, "execution_completion_id"),
    ("completion-time+completion-id", COMPLETION_ERROR, "execution_completion_id"),
    ("foreign-batch+worker-sequence", BATCH_ERROR, "decode_execution_completion_projection"),
    ("incomplete+forged-success", MAPPING_ERROR, "decode_result_batch_projection"),
    ("timeout+forged-success-id", COMPLETION_ERROR, "execution_completion_id"),
)


def _add_compound_fault(kwargs: dict[str, Any], case: str) -> None:
    if case == "returned-result+batch":
        result_ids = list(kwargs["carried_returned_result_ids_in_actual_delivery_order"])
        result_ids[0] = BAD
        kwargs["carried_returned_result_ids_in_actual_delivery_order"] = tuple(result_ids)
        kwargs["carried_result_batch_id"] = BAD
    elif case == "mapping+batch":
        kwargs["job_result_mapping"] = tuple(reversed(kwargs["job_result_mapping"]))
        kwargs["carried_result_batch_id"] = BAD
    elif case == "batch-relation+batch-id":
        kwargs["result_batch"] = replace(kwargs["result_batch"], execution_id=BAD)
        kwargs["carried_result_batch_id"] = BAD
    elif case == "batch-id+completion-status":
        kwargs["carried_result_batch_id"] = BAD
        kwargs["observed_execution_status"] = "failed"
    elif case == "completion-status+completion-id":
        kwargs["observed_execution_status"] = "failed"
        kwargs["carried_execution_completion_id"] = BAD
    elif case == "completion-time+completion-id":
        kwargs["observed_completed_at"] = "2026-01-02T03:04:05.999999Z"
        kwargs["carried_execution_completion_id"] = BAD
    elif case == "foreign-batch+worker-sequence":
        batch = replace(kwargs["result_batch"], execution_id=BAD)
        kwargs["result_batch"] = batch
        kwargs["carried_result_batch_id"] = ex.result_batch_id(batch)
        completion = replace(
            kwargs["execution_completion"],
            observed_worker_ids=tuple(reversed(kwargs["execution_completion"].observed_worker_ids)),
        )
        kwargs["execution_completion"] = completion
        kwargs["carried_execution_completion_id"] = ex.execution_completion_id(completion)
    elif case == "incomplete+forged-success":
        for name in (
            "expected_workers_in_actual_delivery_order",
            "workers_in_actual_delivery_order",
            "returned_domains_in_actual_delivery_order",
            "returned_runs_in_actual_delivery_order",
            "returned_result_projections_in_actual_delivery_order",
            "carried_returned_result_ids_in_actual_delivery_order",
        ):
            kwargs[name] = kwargs[name][:1]
    else:
        kwargs["observed_execution_status"] = "timed_out"


@pytest.mark.parametrize(("case", "code", "sentinel"), COMPOUND_CASES)
def test_compound_faults_stop_at_the_exact_3k_to_3l_first_failure(
    case: str,
    code: str,
    sentinel: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = c1_kwargs()
    _add_compound_fault(kwargs, case)

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError(f"later predicate {sentinel} was evaluated")

    monkeypatch.setattr(ex, sentinel, forbidden)
    assert_failure(kwargs, code)
