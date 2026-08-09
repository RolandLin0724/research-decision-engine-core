from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError, fields, replace
from functools import cache
from typing import Any, Final, cast

import pytest

from research_decision_engine.benchmarks import broader_execution as ex
from research_decision_engine.benchmarks import broader_returned_run as returned
from research_decision_engine.benchmarks.broader_protocol import f64, protocol_hash
from tests.test_broader_p2_execution_evidence_foundations import graph as foundation_graph
from tests.test_broader_p2_returned_run_payload import _run

RESULT_ERROR: Final = "EXECUTION_RETURNED_RESULT_ID_MISMATCH"
MAPPING_ERROR: Final = "EXECUTION_JOB_RESULT_MAPPING_MISMATCH"
ORDER_ERROR: Final = "EXECUTION_RESULT_ORDER_MISMATCH"
SUBMITTED_ERROR: Final = "EXECUTION_SUBMITTED_JOBS_MISMATCH"
SCIENTIFIC_ERROR: Final = "EXECUTION_RETURNED_SCIENTIFIC_RECORD_INVALID"
BAD: Final = "f" * 64
FIELDS: Final = (
    "execution_id",
    "execution_specification_id",
    "result_payload_sha256",
    "schema_version",
    "submitted_job_id",
    "validation_authority_id",
    "validation_run_id",
)
ANNOTATIONS: Final = (
    "str",
    "str",
    "str",
    "Literal['broader-replication-returned-result/v1']",
    "str",
    "str",
    "str",
)


def _job(
    payload: returned.ReturnedRunProjection,
    submission_index: int,
) -> ex.SubmittedJobProjection:
    projection = ex.ValidationJobProjection(
        ex.ValidationJobArmProjection(*payload.arm),
        payload.budget,
        payload.budget_id,
        payload.seed,
        submission_index,
        payload.world_id,
    )
    return ex.SubmittedJobProjection(ex.submitted_job_id(projection), projection)


def _result(
    kwargs: dict[str, Any],
    job: ex.SubmittedJobProjection,
    payload: returned.ReturnedRunProjection,
) -> ex.ReturnedResultProjection:
    execution = cast(ex.ExecutionIdentityProjection, kwargs["execution"])
    return ex.ReturnedResultProjection(
        kwargs["carried_execution_id"],
        execution.execution_specification_id,
        returned.result_payload_sha256(payload),
        "broader-replication-returned-result/v1",
        job.submitted_job_id,
        execution.validation_authority_id,
        execution.validation_run_id,
    )


@cache
def graph() -> dict[str, Any]:
    base = foundation_graph()
    kwargs = dict(base["kwargs"])
    domains = (_run("fixed_lookahead"), _run("fixed_ig"))
    payloads = tuple(returned.project_returned_run(item) for item in domains)
    jobs = tuple(_job(payload, index) for index, payload in enumerate(payloads))
    submitted = replace(kwargs["submitted_jobs"], jobs=jobs)
    kwargs.update(
        expected_submitted_jobs=submitted,
        submitted_jobs=submitted,
        carried_submitted_jobs_sha256=ex.submitted_jobs_sha256(submitted),
    )
    results_in_submission_order = tuple(
        _result(kwargs, job, payload) for job, payload in zip(jobs, payloads, strict=True)
    )
    delivery = (1, 0)
    delivered_domains = tuple(domains[index] for index in delivery)
    delivered_payloads = tuple(payloads[index] for index in delivery)
    delivered_results = tuple(results_in_submission_order[index] for index in delivery)
    delivered_ids = tuple(ex.returned_result_id(item) for item in delivered_results)
    observations = tuple(
        (projection, result_id, payload)
        for projection, result_id, payload in zip(
            delivered_results,
            delivered_ids,
            delivered_payloads,
            strict=True,
        )
    )
    mapping = ex.build_job_result_mapping(jobs, observations)
    kwargs.update(
        returned_domains_in_actual_delivery_order=delivered_domains,
        returned_runs_in_actual_delivery_order=delivered_payloads,
        returned_result_projections_in_actual_delivery_order=delivered_results,
        carried_returned_result_ids_in_actual_delivery_order=delivered_ids,
    )
    return {
        "domains": domains,
        "jobs": jobs,
        "kwargs": kwargs,
        "mapping": mapping,
        "observations": observations,
        "payloads": payloads,
        "results_in_submission_order": results_in_submission_order,
    }


def invoke(
    kwargs: dict[str, Any],
) -> tuple[tuple[ex.ReturnedResultObservation, ...], ex.JobResultMapping]:
    return ex.validate_stage2d2_returned_results(**kwargs)


def assert_failure(
    kwargs: dict[str, Any],
    code: str,
) -> ex.ExecutorProvenanceError:
    with pytest.raises(ex.ExecutorProvenanceError) as captured:
        invoke(kwargs)
    assert captured.value.error_code == code
    assert not getattr(captured.value, "workload_started", False)
    assert not getattr(captured.value, "evidence_checkpointed", False)
    return captured.value


def direct_id(projection: ex.ReturnedResultProjection) -> str:
    return protocol_hash("validation_evidence_returned_result/v1", projection.as_dict())


def replace_delivered_result(
    kwargs: dict[str, Any],
    index: int,
    projection: object,
    result_id: str,
) -> None:
    results = list(kwargs["returned_result_projections_in_actual_delivery_order"])
    result_ids = list(kwargs["carried_returned_result_ids_in_actual_delivery_order"])
    results[index], result_ids[index] = projection, result_id
    kwargs["returned_result_projections_in_actual_delivery_order"] = tuple(results)
    kwargs["carried_returned_result_ids_in_actual_delivery_order"] = tuple(result_ids)


def uncalled(*_args: object, **_kwargs: object) -> Any:
    raise AssertionError("a later predicate was called")


def _one_result_kwargs() -> dict[str, Any]:
    baseline = graph()
    kwargs = dict(baseline["kwargs"])
    domain, payload = baseline["domains"][0], baseline["payloads"][0]
    job = _job(payload, 0)
    submitted = replace(kwargs["submitted_jobs"], jobs=(job,))
    result = _result(kwargs, job, payload)
    worker = kwargs["workers_in_actual_delivery_order"][0]
    kwargs.update(
        expected_submitted_jobs=submitted,
        submitted_jobs=submitted,
        carried_submitted_jobs_sha256=ex.submitted_jobs_sha256(submitted),
        expected_workers_in_actual_delivery_order=(worker[0],),
        workers_in_actual_delivery_order=(worker,),
        returned_domains_in_actual_delivery_order=(domain,),
        returned_runs_in_actual_delivery_order=(payload,),
        returned_result_projections_in_actual_delivery_order=(result,),
        carried_returned_result_ids_in_actual_delivery_order=(ex.returned_result_id(result),),
    )
    return kwargs


def test_returned_result_exact_frozen_slots_schema_domain_and_round_trip() -> None:
    projection = graph()["results_in_submission_order"][0]
    assert tuple(field.name for field in fields(projection)) == FIELDS
    assert tuple(projection.as_dict()) == FIELDS
    assert (
        tuple(
            annotation.replace(", ", ",")
            for annotation in ex.ReturnedResultProjection.__annotations__.values()
        )
        == ANNOTATIONS
    )
    assert projection.schema_version == "broader-replication-returned-result/v1"
    assert ex.decode_returned_result_projection(projection.as_dict()) == projection
    assert ex.returned_result_id(projection) == protocol_hash(
        "validation_evidence_returned_result/v1",
        projection.as_dict(),
    )
    assert ex.returned_result_id(projection) == (
        "f1dbac0328620636ce7a4b120f97e425a9f5c88a00fe3292c18140ea34143e2e"
    )
    assert not hasattr(projection, "__dict__")
    with pytest.raises(FrozenInstanceError):
        projection.execution_id = BAD


@pytest.mark.parametrize("field_name", FIELDS)
def test_every_returned_result_field_is_identity_and_relation_bound(field_name: str) -> None:
    kwargs = dict(graph()["kwargs"])
    original = kwargs["returned_result_projections_in_actual_delivery_order"][0]
    value = "broader-replication-returned-result/v2" if field_name == "schema_version" else BAD
    mutated = replace(original, **{field_name: value})
    if field_name == "schema_version":
        with pytest.raises(ex.ExecutorProvenanceError):
            ex.decode_returned_result_projection(mutated.as_dict())
    else:
        assert ex.decode_returned_result_projection(mutated.as_dict()) == mutated
        assert ex.returned_result_id(mutated) != ex.returned_result_id(original)
    replace_delivered_result(kwargs, 0, mutated, direct_id(mutated))
    assert_failure(kwargs, RESULT_ERROR)


@pytest.mark.parametrize("shape", ("missing", "extra", "order"))
def test_returned_result_decoder_is_strictly_closed(shape: str) -> None:
    raw = graph()["results_in_submission_order"][0].as_dict()
    if shape == "missing":
        raw.pop("submitted_job_id")
    elif shape == "extra":
        raw["extra"] = None
    else:
        raw = dict(reversed(tuple(raw.items())))
    with pytest.raises(ex.ExecutorProvenanceError):
        ex.decode_returned_result_projection(raw)


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    (
        ("execution_id", True),
        ("execution_specification_id", 1),
        ("result_payload_sha256", "A" * 64),
        ("submitted_job_id", "0" * 63),
        ("validation_authority_id", ["0" * 64]),
        ("validation_run_id", "e\u0301"),
        ("schema_version", {"value": "broader-replication-returned-result/v1"}),
    ),
)
def test_returned_result_decoder_rejects_wrong_primitives_hashes_and_nfc(
    field_name: str,
    bad_value: object,
) -> None:
    raw = graph()["results_in_submission_order"][0].as_dict()
    raw[field_name] = bad_value
    with pytest.raises(ex.ExecutorProvenanceError):
        ex.decode_returned_result_projection(raw)


@pytest.mark.parametrize("raw", ([], (), {"execution_id": {"nested": "value"}}))
def test_returned_result_decoder_rejects_wrong_top_level_or_nested_shape(raw: object) -> None:
    with pytest.raises(ex.ExecutorProvenanceError):
        ex.decode_returned_result_projection(raw)


class ProjectionImpostor:
    def __init__(self, projection: ex.ReturnedResultProjection) -> None:
        self.projection = projection

    def as_dict(self) -> dict[str, object]:
        return self.projection.as_dict()


def test_result_occurrence_requires_the_exact_projection_type() -> None:
    kwargs = dict(graph()["kwargs"])
    projection = kwargs["returned_result_projections_in_actual_delivery_order"][0]
    replace_delivered_result(kwargs, 0, ProjectionImpostor(projection), direct_id(projection))
    assert_failure(kwargs, RESULT_ERROR)


def test_historical_task_c_domain_cannot_substitute_for_returned_result_id() -> None:
    kwargs = dict(graph()["kwargs"])
    projection = kwargs["returned_result_projections_in_actual_delivery_order"][0]
    historical_id = protocol_hash("executor_returned_result/v1", projection.as_dict())
    replace_delivered_result(kwargs, 0, projection, historical_id)
    assert historical_id != ex.returned_result_id(projection)
    assert_failure(kwargs, RESULT_ERROR)


@pytest.mark.parametrize(
    "field_name",
    (
        "execution_id",
        "execution_specification_id",
        "submitted_job_id",
        "validation_authority_id",
        "validation_run_id",
    ),
)
def test_foreign_execution_specification_job_authority_and_run_are_rejected(
    field_name: str,
) -> None:
    kwargs = dict(graph()["kwargs"])
    projection = kwargs["returned_result_projections_in_actual_delivery_order"][0]
    mutated = replace(projection, **{field_name: BAD})
    replace_delivered_result(kwargs, 0, mutated, direct_id(mutated))
    assert_failure(kwargs, RESULT_ERROR)


def test_wrong_worker_is_rejected_before_batch_or_returned_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = dict(graph()["kwargs"])
    observations = list(kwargs["workers_in_actual_delivery_order"])
    observations[0] = (observations[0][0], BAD)
    kwargs["workers_in_actual_delivery_order"] = tuple(observations)
    monkeypatch.setattr(ex, "validate_returned_run_batch", uncalled)
    monkeypatch.setattr(ex, "returned_result_id", uncalled)
    assert_failure(kwargs, ORDER_ERROR)


def test_valid_phase_b_returns_delivery_occurrences_and_submission_mapping() -> None:
    observations, mapping = invoke(dict(graph()["kwargs"]))
    assert observations == graph()["observations"]
    assert mapping == graph()["mapping"]
    assert type(observations) is tuple
    assert type(mapping) is tuple
    assert all(type(row) is tuple and len(row) == 2 for row in mapping)


def test_complete_delivery_sequence_calls_approved_batch_api_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = dict(graph()["kwargs"])
    real_batch = cast(Any, ex).validate_returned_run_batch
    calls: list[tuple[object, object]] = []

    def tracked_batch(
        *,
        returned_runs_in_actual_delivery_order: tuple[returned.ReturnedRunProjection, ...],
        returned_domains_in_actual_delivery_order: tuple[object, ...],
    ) -> object:
        calls.append(
            (
                returned_runs_in_actual_delivery_order,
                returned_domains_in_actual_delivery_order,
            )
        )
        return real_batch(
            returned_runs_in_actual_delivery_order=returned_runs_in_actual_delivery_order,
            returned_domains_in_actual_delivery_order=cast(
                Any, returned_domains_in_actual_delivery_order
            ),
        )

    monkeypatch.setattr(ex, "validate_returned_run_batch", tracked_batch)
    invoke(kwargs)
    assert calls == [
        (
            kwargs["returned_runs_in_actual_delivery_order"],
            kwargs["returned_domains_in_actual_delivery_order"],
        )
    ]


def test_one_payload_execution_still_calls_batch_api_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = _one_result_kwargs()
    real_batch = cast(Any, ex).validate_returned_run_batch
    calls = 0

    def tracked_batch(**batch_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real_batch(**cast(Any, batch_kwargs))

    monkeypatch.setattr(ex, "validate_returned_run_batch", tracked_batch)
    observations, mapping = invoke(kwargs)
    assert calls == 1
    assert len(observations) == len(mapping) == 1


def test_nested_payload_change_with_recomputed_outer_commitments_is_rejected() -> None:
    kwargs = dict(graph()["kwargs"])
    payloads = list(kwargs["returned_runs_in_actual_delivery_order"])
    payloads[0] = replace(payloads[0], run_id="forged-run")
    kwargs["returned_runs_in_actual_delivery_order"] = tuple(payloads)
    projection = kwargs["returned_result_projections_in_actual_delivery_order"][0]
    payload_hash = protocol_hash(
        "validation_evidence_returned_run_payload/v1",
        returned.projection_as_dict(payloads[0]),
    )
    mutated = replace(projection, result_payload_sha256=payload_hash)
    replace_delivered_result(kwargs, 0, mutated, direct_id(mutated))
    assert_failure(kwargs, SCIENTIFIC_ERROR)


def test_complete_scientific_batch_precedes_first_returned_result_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = dict(graph()["kwargs"])
    domains = list(kwargs["returned_domains_in_actual_delivery_order"])
    payloads = list(kwargs["returned_runs_in_actual_delivery_order"])
    domains[1] = replace(domains[1], budget=-1.0)
    payloads[1] = replace(payloads[1], budget=f64(-1.0))
    kwargs["returned_domains_in_actual_delivery_order"] = tuple(domains)
    kwargs["returned_runs_in_actual_delivery_order"] = tuple(payloads)
    ids = list(kwargs["carried_returned_result_ids_in_actual_delivery_order"])
    ids[0] = BAD
    kwargs["carried_returned_result_ids_in_actual_delivery_order"] = tuple(ids)
    monkeypatch.setattr(ex, "returned_result_id", uncalled)
    monkeypatch.setattr(ex, "build_job_result_mapping", uncalled)
    assert_failure(kwargs, SCIENTIFIC_ERROR)


def test_batch_structural_preparation_for_all_precedes_science_and_3k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = dict(graph()["kwargs"])
    domains = list(kwargs["returned_domains_in_actual_delivery_order"])
    payloads = list(kwargs["returned_runs_in_actual_delivery_order"])
    domains[0] = replace(domains[0], budget=-1.0)
    payloads[0] = replace(payloads[0], budget=f64(-1.0))
    payloads[1] = replace(payloads[1], budget="not-f64")
    kwargs["returned_domains_in_actual_delivery_order"] = tuple(domains)
    kwargs["returned_runs_in_actual_delivery_order"] = tuple(payloads)
    monkeypatch.setattr(ex, "returned_result_id", uncalled)
    monkeypatch.setattr(ex, "build_job_result_mapping", uncalled)
    failure = assert_failure(kwargs, RESULT_ERROR)
    assert "returned_runs[1]" in str(failure)


def test_batch_science_precedes_malformed_3k_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = dict(graph()["kwargs"])
    domains = list(kwargs["returned_domains_in_actual_delivery_order"])
    payloads = list(kwargs["returned_runs_in_actual_delivery_order"])
    domains[0] = replace(domains[0], budget=-1.0)
    payloads[0] = replace(payloads[0], budget=f64(-1.0))
    kwargs["returned_domains_in_actual_delivery_order"] = tuple(domains)
    kwargs["returned_runs_in_actual_delivery_order"] = tuple(payloads)
    kwargs["returned_result_projections_in_actual_delivery_order"] = list(
        kwargs["returned_result_projections_in_actual_delivery_order"]
    )
    monkeypatch.setattr(ex, "returned_result_id", uncalled)
    monkeypatch.setattr(ex, "build_job_result_mapping", uncalled)
    assert_failure(kwargs, SCIENTIFIC_ERROR)


def test_3k_relation_and_id_are_interleaved_per_delivery_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = dict(graph()["kwargs"])
    second = kwargs["returned_result_projections_in_actual_delivery_order"][1]
    foreign = replace(second, validation_run_id=BAD)
    replace_delivered_result(kwargs, 1, foreign, direct_id(foreign))
    real_id = ex.returned_result_id
    checked: list[ex.ReturnedResultProjection] = []

    def tracked_id(projection: ex.ReturnedResultProjection) -> str:
        checked.append(projection)
        return real_id(projection)

    monkeypatch.setattr(ex, "returned_result_id", tracked_id)
    monkeypatch.setattr(ex, "build_job_result_mapping", uncalled)
    assert_failure(kwargs, RESULT_ERROR)
    assert checked == [kwargs["returned_result_projections_in_actual_delivery_order"][0]]


def test_first_3k_relation_fault_calls_no_identity_or_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = dict(graph()["kwargs"])
    first = kwargs["returned_result_projections_in_actual_delivery_order"][0]
    foreign = replace(first, execution_id=BAD)
    replace_delivered_result(kwargs, 0, foreign, direct_id(foreign))
    monkeypatch.setattr(ex, "returned_result_id", uncalled)
    monkeypatch.setattr(ex, "build_job_result_mapping", uncalled)
    assert_failure(kwargs, RESULT_ERROR)


def test_first_3k_identity_fault_stops_before_second_occurrence_and_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = dict(graph()["kwargs"])
    ids = list(kwargs["carried_returned_result_ids_in_actual_delivery_order"])
    ids[0] = BAD
    kwargs["carried_returned_result_ids_in_actual_delivery_order"] = tuple(ids)
    real_payload_job = ex._d2_payload_job
    calls = 0

    def tracked_payload_job(*args: object, **call_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real_payload_job(*cast(Any, args), **cast(Any, call_kwargs))

    monkeypatch.setattr(ex, "_d2_payload_job", tracked_payload_job)
    monkeypatch.setattr(ex, "build_job_result_mapping", uncalled)
    assert_failure(kwargs, RESULT_ERROR)
    assert calls == 1


def test_duplicate_accepted_result_identity_precedes_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = dict(graph()["kwargs"])
    domains = kwargs["returned_domains_in_actual_delivery_order"]
    payloads = kwargs["returned_runs_in_actual_delivery_order"]
    results = kwargs["returned_result_projections_in_actual_delivery_order"]
    ids = kwargs["carried_returned_result_ids_in_actual_delivery_order"]
    kwargs["returned_domains_in_actual_delivery_order"] = (domains[0], domains[0])
    kwargs["returned_runs_in_actual_delivery_order"] = (payloads[0], payloads[0])
    kwargs["returned_result_projections_in_actual_delivery_order"] = (results[0], results[0])
    kwargs["carried_returned_result_ids_in_actual_delivery_order"] = (ids[0], ids[0])
    monkeypatch.setattr(ex, "build_job_result_mapping", uncalled)
    assert_failure(kwargs, RESULT_ERROR)


def _mapping_case(case: str) -> tuple[object, object]:
    jobs = graph()["jobs"]
    observations = graph()["observations"]
    if case == "jobs-list":
        return list(jobs), observations
    if case == "results-list":
        return jobs, list(observations)
    if case == "duplicate-result-id":
        second = observations[1]
        return jobs, (observations[0], (second[0], observations[0][1], second[2]))
    if case == "duplicate-job-id":
        return (jobs[0], jobs[0]), observations
    if case == "duplicate-mapping-occurrence":
        first_projection, _first_id, _first_payload = observations[0]
        second_projection, _second_id, second_payload = observations[1]
        foreign = replace(
            second_projection,
            submitted_job_id=first_projection.submitted_job_id,
        )
        return jobs, (observations[0], (foreign, direct_id(foreign), second_payload))
    if case == "two-jobs-one-result":
        return jobs, observations[:1]
    if case == "one-job-two-results":
        return jobs[:1], observations
    projection, _result_id, payload = observations[0]
    foreign = replace(projection, submitted_job_id=BAD)
    return jobs, ((foreign, direct_id(foreign), payload), observations[1])


@pytest.mark.parametrize(
    "case",
    (
        "jobs-list",
        "results-list",
        "duplicate-result-id",
        "duplicate-job-id",
        "duplicate-mapping-occurrence",
        "two-jobs-one-result",
        "one-job-two-results",
        "equal-count-different-set",
    ),
)
def test_mapping_builder_rejects_every_non_bijection(case: str) -> None:
    jobs, observations = _mapping_case(case)
    with pytest.raises(ex.ExecutorProvenanceError) as captured:
        ex.build_job_result_mapping(cast(Any, jobs), cast(Any, observations))
    assert captured.value.error_code == MAPPING_ERROR


def test_mapping_builder_consumes_accepted_ids_without_rehashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ex, "returned_result_id", uncalled)
    assert (
        ex.build_job_result_mapping(graph()["jobs"], graph()["observations"]) == graph()["mapping"]
    )


def test_mapping_is_exact_submission_order_not_delivery_or_dictionary_order() -> None:
    observations, mapping = invoke(dict(graph()["kwargs"]))
    jobs = graph()["jobs"]
    assert tuple(pair[0] for pair in mapping) == tuple(job.submitted_job_id for job in jobs)
    assert tuple(item[0].submitted_job_id for item in observations) == tuple(
        reversed(tuple(job.submitted_job_id for job in jobs))
    )
    assert mapping == tuple(
        (
            job.submitted_job_id,
            next(
                item[1] for item in observations if item[0].submitted_job_id == job.submitted_job_id
            ),
        )
        for job in jobs
    )


def test_duplicate_scientific_content_distinct_jobs_produce_distinct_occurrences() -> None:
    kwargs = dict(graph()["kwargs"])
    domain, payload = graph()["domains"][0], graph()["payloads"][0]
    jobs = (_job(payload, 0), _job(payload, 1))
    submitted = replace(kwargs["submitted_jobs"], jobs=jobs)
    kwargs.update(
        expected_submitted_jobs=submitted,
        submitted_jobs=submitted,
        carried_submitted_jobs_sha256=ex.submitted_jobs_sha256(submitted),
    )
    results = tuple(_result(kwargs, job, payload) for job in jobs)
    delivered = (results[1], results[0])
    delivered_ids = tuple(ex.returned_result_id(item) for item in delivered)
    kwargs.update(
        returned_domains_in_actual_delivery_order=(domain, domain),
        returned_runs_in_actual_delivery_order=(payload, payload),
        returned_result_projections_in_actual_delivery_order=delivered,
        carried_returned_result_ids_in_actual_delivery_order=delivered_ids,
    )
    observations, mapping = invoke(kwargs)
    assert results[0].result_payload_sha256 == results[1].result_payload_sha256
    assert results[0].submitted_job_id != results[1].submitted_job_id
    assert delivered_ids[0] != delivered_ids[1]
    assert tuple(row[0] for row in mapping) == tuple(job.submitted_job_id for job in jobs)
    assert observations[0][0] == delivered[0]


def test_missing_accepted_result_reaches_mapping_after_complete_3k() -> None:
    kwargs = dict(graph()["kwargs"])
    for name in (
        "returned_domains_in_actual_delivery_order",
        "returned_runs_in_actual_delivery_order",
        "returned_result_projections_in_actual_delivery_order",
        "carried_returned_result_ids_in_actual_delivery_order",
    ):
        kwargs[name] = kwargs[name][:1]
    kwargs["expected_workers_in_actual_delivery_order"] = kwargs[
        "expected_workers_in_actual_delivery_order"
    ][:1]
    kwargs["workers_in_actual_delivery_order"] = kwargs["workers_in_actual_delivery_order"][:1]
    assert_failure(kwargs, MAPPING_ERROR)


def test_swapping_delivery_preserves_mapping_and_batch_input_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = graph()
    kwargs = dict(baseline["kwargs"])
    for name in (
        "expected_workers_in_actual_delivery_order",
        "workers_in_actual_delivery_order",
        "returned_domains_in_actual_delivery_order",
        "returned_runs_in_actual_delivery_order",
        "returned_result_projections_in_actual_delivery_order",
        "carried_returned_result_ids_in_actual_delivery_order",
    ):
        kwargs[name] = tuple(reversed(kwargs[name]))
    real_batch = cast(Any, ex).validate_returned_run_batch
    seen: list[object] = []

    def tracked_batch(**batch_kwargs: object) -> object:
        seen.append(batch_kwargs["returned_runs_in_actual_delivery_order"])
        return real_batch(**cast(Any, batch_kwargs))

    monkeypatch.setattr(ex, "validate_returned_run_batch", tracked_batch)
    observations, mapping = invoke(kwargs)
    assert seen == [kwargs["returned_runs_in_actual_delivery_order"]]
    assert mapping == baseline["mapping"]
    assert observations == tuple(reversed(baseline["observations"]))


def test_reversing_submission_changes_only_canonical_mapping_order() -> None:
    kwargs = dict(graph()["kwargs"])
    domains = tuple(reversed(graph()["domains"]))
    payloads = tuple(reversed(graph()["payloads"]))
    jobs = tuple(_job(payload, index) for index, payload in enumerate(payloads))
    submitted = replace(kwargs["submitted_jobs"], jobs=jobs)
    kwargs.update(
        expected_submitted_jobs=submitted,
        submitted_jobs=submitted,
        carried_submitted_jobs_sha256=ex.submitted_jobs_sha256(submitted),
    )
    results = tuple(
        _result(kwargs, job, payload) for job, payload in zip(jobs, payloads, strict=True)
    )
    delivery = (1, 0)
    kwargs.update(
        returned_domains_in_actual_delivery_order=tuple(domains[index] for index in delivery),
        returned_runs_in_actual_delivery_order=tuple(payloads[index] for index in delivery),
        returned_result_projections_in_actual_delivery_order=tuple(
            results[index] for index in delivery
        ),
        carried_returned_result_ids_in_actual_delivery_order=tuple(
            ex.returned_result_id(results[index]) for index in delivery
        ),
    )
    _observations, mapping = invoke(kwargs)
    assert tuple(row[0] for row in mapping) == tuple(job.submitted_job_id for job in jobs)
    assert mapping != graph()["mapping"]


def test_acceptance_order_is_not_a_phase_b_input_or_order_alias() -> None:
    parameters = inspect.signature(ex.validate_stage2d2_returned_results).parameters
    assert "acceptance_order" not in parameters
    submission_order = (0, 1, 2)
    acceptance_order = (1, 2, 0)
    delivery_order = (2, 0, 1)
    assert len({submission_order, acceptance_order, delivery_order}) == 3


@pytest.mark.parametrize(
    ("case", "expected_code"),
    (
        ("worker+s1", ORDER_ERROR),
        ("s1+result-id", SCIENTIFIC_ERROR),
        ("payload-hash+result-id", RESULT_ERROR),
        ("result-id+missing-mapping", RESULT_ERROR),
        ("result-id+duplicate-mapping", RESULT_ERROR),
        ("mapping-missing+extra", MAPPING_ERROR),
        ("duplicate-job+duplicate-result", SUBMITTED_ERROR),
        ("cross-execution+mapping", RESULT_ERROR),
        ("cross-run+mapping", RESULT_ERROR),
    ),
)
def test_compound_fault_table_stops_at_exact_first_predicate(
    case: str,
    expected_code: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = dict(graph()["kwargs"])
    if case == "worker+s1":
        workers = list(kwargs["workers_in_actual_delivery_order"])
        workers[0] = (workers[0][0], BAD)
        kwargs["workers_in_actual_delivery_order"] = tuple(workers)
        domains = list(kwargs["returned_domains_in_actual_delivery_order"])
        payloads = list(kwargs["returned_runs_in_actual_delivery_order"])
        domains[0] = replace(domains[0], budget=-1.0)
        payloads[0] = replace(payloads[0], budget=f64(-1.0))
        kwargs["returned_domains_in_actual_delivery_order"] = tuple(domains)
        kwargs["returned_runs_in_actual_delivery_order"] = tuple(payloads)
        monkeypatch.setattr(ex, "validate_returned_run_batch", uncalled)
    elif case == "s1+result-id":
        domains = list(kwargs["returned_domains_in_actual_delivery_order"])
        payloads = list(kwargs["returned_runs_in_actual_delivery_order"])
        domains[0] = replace(domains[0], budget=-1.0)
        payloads[0] = replace(payloads[0], budget=f64(-1.0))
        kwargs["returned_domains_in_actual_delivery_order"] = tuple(domains)
        kwargs["returned_runs_in_actual_delivery_order"] = tuple(payloads)
        ids = list(kwargs["carried_returned_result_ids_in_actual_delivery_order"])
        ids[0] = BAD
        kwargs["carried_returned_result_ids_in_actual_delivery_order"] = tuple(ids)
        monkeypatch.setattr(ex, "returned_result_id", uncalled)
    elif case == "payload-hash+result-id":
        first = kwargs["returned_result_projections_in_actual_delivery_order"][0]
        foreign = replace(first, result_payload_sha256=BAD)
        replace_delivered_result(kwargs, 0, foreign, BAD)
        monkeypatch.setattr(ex, "returned_result_id", uncalled)
    elif case == "result-id+missing-mapping":
        for name in (
            "returned_domains_in_actual_delivery_order",
            "returned_runs_in_actual_delivery_order",
            "returned_result_projections_in_actual_delivery_order",
            "carried_returned_result_ids_in_actual_delivery_order",
            "expected_workers_in_actual_delivery_order",
            "workers_in_actual_delivery_order",
        ):
            kwargs[name] = kwargs[name][:1]
        kwargs["carried_returned_result_ids_in_actual_delivery_order"] = (BAD,)
        monkeypatch.setattr(ex, "build_job_result_mapping", uncalled)
    elif case == "result-id+duplicate-mapping":
        ids = list(kwargs["carried_returned_result_ids_in_actual_delivery_order"])
        ids[0] = BAD
        kwargs["carried_returned_result_ids_in_actual_delivery_order"] = tuple(ids)
        monkeypatch.setattr(ex, "build_job_result_mapping", uncalled)
    elif case == "mapping-missing+extra":
        jobs, observations = _mapping_case("equal-count-different-set")
        with pytest.raises(ex.ExecutorProvenanceError) as captured:
            ex.build_job_result_mapping(cast(Any, jobs), cast(Any, observations))
        assert captured.value.error_code == expected_code
        return
    elif case == "duplicate-job+duplicate-result":
        jobs = graph()["jobs"]
        submitted = replace(kwargs["submitted_jobs"], jobs=(jobs[0], jobs[0]))
        kwargs.update(
            expected_submitted_jobs=submitted,
            submitted_jobs=submitted,
            carried_submitted_jobs_sha256=BAD,
        )
        results = kwargs["returned_result_projections_in_actual_delivery_order"]
        ids = kwargs["carried_returned_result_ids_in_actual_delivery_order"]
        kwargs["returned_result_projections_in_actual_delivery_order"] = (
            results[0],
            results[0],
        )
        kwargs["carried_returned_result_ids_in_actual_delivery_order"] = (ids[0], ids[0])
        monkeypatch.setattr(ex, "validate_returned_run_batch", uncalled)
    else:
        first = kwargs["returned_result_projections_in_actual_delivery_order"][0]
        field_name = "execution_id" if case == "cross-execution+mapping" else "validation_run_id"
        foreign = replace(first, **{field_name: BAD})
        replace_delivered_result(kwargs, 0, foreign, direct_id(foreign))
        monkeypatch.setattr(ex, "build_job_result_mapping", uncalled)
    assert_failure(kwargs, expected_code)


def test_phase_b_uses_no_phase_c_workload_scoring_evidence_or_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "result_batch_id",
        "execution_completion_id",
        "returned_results_sha256",
        "worker_result_order_sha256",
        "executor_attestation_id",
        "execute_deterministic_map",
        "run_arm",
        "score_candidates",
        "write_validation_evidence",
        "_issue_fixture_execution_specification",
        "_issue_execution_specification",
        "_require_production_executor_implementation",
        "_allocate_production_plan_capability",
    ):
        monkeypatch.setattr(ex, name, uncalled, raising=False)
    invoke(dict(graph()["kwargs"]))
