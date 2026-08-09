# ruff: noqa: SIM905
from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError, fields, replace
from typing import Any, Final, cast

import pytest

from research_decision_engine.benchmarks import broader_execution as ex
from research_decision_engine.benchmarks import broader_returned_run as returned
from research_decision_engine.benchmarks.broader_protocol import protocol_hash
from tests.test_broader_p2_result_batch_completion import (
    _accepted_observations,
    _attach_c1,
    c1_kwargs,
)
from tests.test_broader_p2_returned_result import (
    _job,
    _one_result_kwargs,
    _result,
    graph,
)

RETURNED_ERROR: Final = "EXECUTION_RETURNED_RESULTS_MISMATCH"
ORDER_ERROR: Final = "EXECUTION_RESULT_ORDER_MISMATCH"
COMPLETION_ERROR: Final = "EXECUTION_COMPLETION_ID_MISMATCH"
SCIENTIFIC_ERROR: Final = "EXECUTION_RETURNED_SCIENTIFIC_RECORD_INVALID"
BAD: Final = "f" * 64
ALT: Final = "e" * 64
CHECKPOINT: Final = "89c0b4fadba33b9fd9a257b43eacf476b7779d59"
STUDY: Final = "broader-closed-loop-replication/v1"

HEAD_FIELDS: Final = tuple(
    (
        "execution_completion_id execution_id execution_specification_id execution_status "
        "implementation job_result_mapping oracle_binding_id oracle_execution_id "
        "protocol_checkpoint"
    ).split()  # noqa: SIM905 - compact immutable contract table
)
TAIL_FIELDS: Final = tuple(
    "runtime runtime_identity schema_version study_id "
    "validation_authority_id validation_run_id".split()  # noqa: SIM905
)
RETURNED_FIELDS: Final = (*HEAD_FIELDS, "results_in_submission_order", *TAIL_FIELDS)
ORDER_FIELDS: Final = (*HEAD_FIELDS, "results_in_actual_delivery_order", *TAIL_FIELDS)
FIELD_CASES: Final = tuple(("ReturnedResultsProjection", name) for name in RETURNED_FIELDS) + tuple(
    ("WorkerResultOrderProjection", name) for name in ORDER_FIELDS
)
HEAD_TYPES: Final = (
    *"str str str Literal['success'] ImplementationProjection JobResultMapping str str".split(),  # noqa: SIM905
    f"Literal['{CHECKPOINT}']",
)
TAIL_TYPES: Final = (
    *"RuntimeProjection str schema".split(),  # noqa: SIM905
    f"Literal['{STUDY}']",
    "str",
    "str",
)


def _attach_c2(c1: dict[str, Any]) -> dict[str, Any]:
    kwargs = dict(c1)
    execution = cast(ex.ExecutionIdentityProjection, kwargs["execution"])
    submitted = cast(ex.SubmittedJobsProjection, kwargs["submitted_jobs"])
    mapping = cast(ex.JobResultMapping, kwargs["job_result_mapping"])
    observations = _accepted_observations(kwargs)
    by_result_id = {row[1]: row for row in observations}
    submission_rows = tuple(
        (result_id, by_result_id[result_id][2], submitted_job_id)
        for submitted_job_id, result_id in mapping
    )
    workers = cast(
        tuple[tuple[ex.WorkerIdentityProjection, str], ...],
        kwargs["workers_in_actual_delivery_order"],
    )
    result_ids = cast(
        tuple[str, ...],
        kwargs["carried_returned_result_ids_in_actual_delivery_order"],
    )
    delivery_rows = tuple(
        (index, result_id, worker, worker_id)
        for index, (result_id, (worker, worker_id)) in enumerate(
            zip(result_ids, workers, strict=True)
        )
    )
    common: dict[str, Any] = {
        "execution_completion_id": cast(str, kwargs["carried_execution_completion_id"]),
        "execution_id": cast(str, kwargs["carried_execution_id"]),
        "execution_specification_id": execution.execution_specification_id,
        "execution_status": "success",
        "implementation": submitted.implementation,
        "job_result_mapping": mapping,
        "oracle_binding_id": execution.oracle_binding_id,
        "oracle_execution_id": execution.oracle_execution_id,
        "protocol_checkpoint": CHECKPOINT,
        "runtime": submitted.runtime,
        "runtime_identity": submitted.runtime_identity,
        "study_id": STUDY,
        "validation_authority_id": execution.validation_authority_id,
        "validation_run_id": execution.validation_run_id,
    }
    returned_results = ex.ReturnedResultsProjection(
        **common,
        results_in_submission_order=submission_rows,
        schema_version="broader-replication-returned-results/v1",
    )
    worker_order = ex.WorkerResultOrderProjection(
        **common,
        results_in_actual_delivery_order=delivery_rows,
        schema_version="broader-replication-worker-result-order/v1",
    )
    kwargs.update(
        returned_results=returned_results,
        carried_returned_results_sha256=ex.returned_results_sha256(returned_results),
        worker_result_order=worker_order,
        carried_worker_result_order_sha256=ex.worker_result_order_sha256(worker_order),
    )
    return kwargs


def c2_kwargs() -> dict[str, Any]:
    return _attach_c2(c1_kwargs())


def invoke(
    kwargs: dict[str, Any],
) -> tuple[tuple[ex.ReturnedResultObservation, ...], ex.JobResultMapping]:
    return ex.validate_stage2d2_result_aggregates(**kwargs)


def assert_failure(kwargs: dict[str, Any], code: str) -> None:
    with pytest.raises(ex.ExecutorProvenanceError) as captured:
        invoke(kwargs)
    assert captured.value.error_code == code
    assert not getattr(captured.value, "workload_started", False)
    assert not getattr(captured.value, "evidence_checkpointed", False)


def _aggregate_tools(
    kwargs: dict[str, Any],
    returned_kind: bool,
) -> tuple[Any, Any, Any]:
    kind = "returned_results" if returned_kind else "worker_result_order"
    return (
        kwargs[kind],
        getattr(ex, f"decode_{kind}_projection"),
        getattr(ex, f"{kind}_sha256"),
    )


@pytest.mark.parametrize(
    ("name", "field_names", "kind"),
    (
        ("ReturnedResultsProjection", RETURNED_FIELDS, "returned-results"),
        ("WorkerResultOrderProjection", ORDER_FIELDS, "worker-result-order"),
    ),
)
def test_exact_projection_contract(
    name: str,
    field_names: tuple[str, ...],
    kind: str,
) -> None:
    kwargs = c2_kwargs()
    schema = f"broader-replication-{kind}/v1"
    domain = f"validation_evidence_{kind.replace('-', '_')}/v1"
    projection, decoder, identity = _aggregate_tools(kwargs, name == "ReturnedResultsProjection")
    annotations = tuple(
        value.replace(", ", ",") for value in type(projection).__annotations__.values()
    )
    row_type = (
        "tuple[tuple[str,ReturnedRunProjection,str],...]"
        if name == "ReturnedResultsProjection"
        else "tuple[tuple[int,str,WorkerIdentityProjection,str],...]"
    )
    schema_type = f"Literal['{schema}']"
    assert tuple(field.name for field in fields(projection)) == field_names
    assert annotations == (*HEAD_TYPES, row_type, *TAIL_TYPES[:2], schema_type, *TAIL_TYPES[3:])
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


def _changed_raw(projection: object, field_name: str) -> dict[str, object]:
    raw = cast(dict[str, object], cast(Any, projection).as_dict())
    value = raw[field_name]
    if field_name in {
        "execution_status",
        "protocol_checkpoint",
        "schema_version",
        "study_id",
    }:
        raw[field_name] = "invalid"
    elif type(value) is str:
        raw[field_name] = BAD if value != BAD else ALT
    elif type(value) is list:
        raw[field_name] = list(reversed(value)) if len(value) > 1 else value + [None]
    else:
        raw[field_name] = {}
    return raw


@pytest.mark.parametrize(("name", "field_name"), FIELD_CASES)
def test_every_field_is_strictly_decoded_and_identity_bound(
    name: str,
    field_name: str,
) -> None:
    kwargs = c2_kwargs()
    projection, decoder, identity = _aggregate_tools(kwargs, name == "ReturnedResultsProjection")
    before = identity(projection)
    try:
        changed = decoder(_changed_raw(projection, field_name))
    except ex.ExecutorProvenanceError:
        return
    assert changed != projection
    assert identity(changed) != before


STRICT_CASES: Final = tuple(
    (f"{kind}-{fault}", kind)
    for kind in ("returned", "worker")
    for fault in ("missing", "extra", "top-order", "row-order")
)


@pytest.mark.parametrize(("case", "kind"), STRICT_CASES)
def test_decoders_are_strictly_closed_and_ordered(case: str, kind: str) -> None:
    kwargs = c2_kwargs()
    projection, decoder, _identity = _aggregate_tools(kwargs, kind == "returned")
    raw = cast(Any, projection).as_dict()
    row_name = (
        "results_in_submission_order" if kind == "returned" else "results_in_actual_delivery_order"
    )
    if case.endswith("missing"):
        raw.pop("execution_completion_id")
    elif case.endswith("extra"):
        raw["extra"] = None
    elif case.endswith("top-order"):
        raw = dict(reversed(tuple(raw.items())))
    else:
        rows = cast(list[dict[str, object]], raw[row_name])
        rows[0] = dict(reversed(tuple(rows[0].items())))
    with pytest.raises(ex.ExecutorProvenanceError) as captured:
        decoder(raw)
    assert captured.value.error_code == (RETURNED_ERROR if kind == "returned" else ORDER_ERROR)


@pytest.mark.parametrize(
    ("kind", "path"),
    (
        ("returned-head", "returned_results.execution_completion_id"),
        ("worker-head", "worker_result_order.execution_completion_id"),
        ("returned-row", "returned_results.results_in_submission_order[0].returned_result_id"),
        ("worker-row", "worker_result_order.results_in_actual_delivery_order[0].delivery_index"),
    ),
)
def test_raw_compound_decoding_uses_displayed_field_order(kind: str, path: str) -> None:
    kwargs = c2_kwargs()
    is_returned = kind.startswith("returned")
    projection, decoder, _identity = _aggregate_tools(kwargs, is_returned)
    raw = cast(Any, projection).as_dict()
    if kind.endswith("head"):
        raw["execution_completion_id"] = "bad"
        raw["job_result_mapping"] = {}
    elif is_returned:
        row = cast(list[dict[str, object]], raw["results_in_submission_order"])[0]
        row["returned_result_id"] = "bad"
        row["projection"] = {}
    else:
        row = cast(list[dict[str, object]], raw["results_in_actual_delivery_order"])[0]
        row["delivery_index"] = True
        row["worker"] = {}
    with pytest.raises(ex.ExecutorProvenanceError) as captured:
        decoder(raw)
    code = RETURNED_ERROR if is_returned else ORDER_ERROR
    assert captured.value.error_code == code
    assert str(captured.value).startswith(f"{code} at {path}:")


def _reversed_c1(field_names: str) -> dict[str, Any]:
    phase_b = dict(graph()["kwargs"])
    for name in field_names.split():
        phase_b[name] = tuple(reversed(phase_b[name]))
    return _attach_c1(phase_b)


def _reverse_delivery_c1() -> dict[str, Any]:
    return _reversed_c1(
        "expected_workers_in_actual_delivery_order workers_in_actual_delivery_order "
        "returned_domains_in_actual_delivery_order returned_runs_in_actual_delivery_order "
        "returned_result_projections_in_actual_delivery_order "
        "carried_returned_result_ids_in_actual_delivery_order"
    )


def _submission_permuted_c1() -> dict[str, Any]:
    base = graph()
    kwargs = dict(base["kwargs"])
    domains = tuple(reversed(base["domains"]))
    payloads = tuple(reversed(base["payloads"]))
    jobs = tuple(_job(payload, index) for index, payload in enumerate(payloads))
    submitted = replace(kwargs["submitted_jobs"], jobs=jobs)
    results = tuple(
        _result(kwargs, job, payload) for job, payload in zip(jobs, payloads, strict=True)
    )
    delivery = tuple(
        sorted(
            range(len(results)),
            key=lambda index: ex.returned_result_id(results[index]),
            reverse=True,
        )
    )
    kwargs.update(
        expected_submitted_jobs=submitted,
        submitted_jobs=submitted,
        carried_submitted_jobs_sha256=ex.submitted_jobs_sha256(submitted),
        returned_domains_in_actual_delivery_order=tuple(domains[index] for index in delivery),
        returned_runs_in_actual_delivery_order=tuple(payloads[index] for index in delivery),
        returned_result_projections_in_actual_delivery_order=tuple(
            results[index] for index in delivery
        ),
        carried_returned_result_ids_in_actual_delivery_order=tuple(
            ex.returned_result_id(results[index]) for index in delivery
        ),
    )
    return _attach_c1(kwargs)


def _worker_reassigned_c1() -> dict[str, Any]:
    return _reversed_c1(
        "expected_workers_in_actual_delivery_order workers_in_actual_delivery_order"
    )


def _four_order_c1() -> tuple[dict[str, Any], tuple[int, ...], tuple[int, ...]]:
    base = graph()
    kwargs = dict(base["kwargs"])
    domain, payload = base["domains"][0], base["payloads"][0]
    submission, acceptance, delivery, first_worker = (
        (0, 1, 2),
        (1, 2, 0),
        (2, 0, 1),
        (2, 1, 0),
    )
    assert len({submission, acceptance, delivery, first_worker}) == 4
    jobs = tuple(_job(payload, index) for index in submission)
    submitted = replace(kwargs["submitted_jobs"], jobs=jobs)
    results = tuple(_result(kwargs, job, payload) for job in jobs)
    base_worker = cast(
        tuple[tuple[ex.WorkerIdentityProjection, str], ...],
        kwargs["workers_in_actual_delivery_order"],
    )[0][0]
    workers = tuple(
        replace(base_worker, thread_id=401 + index, thread_name=f"c2-worker-{index}")
        for index in submission
    )
    worker_rows = tuple((worker, ex.worker_identity(worker)) for worker in workers)
    delivered_workers = tuple(worker_rows[index] for index in first_worker)
    kwargs.update(
        expected_submitted_jobs=submitted,
        submitted_jobs=submitted,
        carried_submitted_jobs_sha256=ex.submitted_jobs_sha256(submitted),
        expected_workers_in_actual_delivery_order=tuple(row[0] for row in delivered_workers),
        workers_in_actual_delivery_order=delivered_workers,
        returned_domains_in_actual_delivery_order=(domain,) * 3,
        returned_runs_in_actual_delivery_order=(payload,) * 3,
        returned_result_projections_in_actual_delivery_order=tuple(
            results[index] for index in delivery
        ),
        carried_returned_result_ids_in_actual_delivery_order=tuple(
            ex.returned_result_id(results[index]) for index in delivery
        ),
    )
    return _attach_c1(kwargs), acceptance, first_worker


def test_delivery_permutation_preserves_local_submission_rows_but_changes_enclosures() -> None:
    baseline = c2_kwargs()
    permuted = _attach_c2(_reverse_delivery_c1())
    invoke(permuted)
    left = cast(ex.ReturnedResultsProjection, baseline["returned_results"])
    right = cast(ex.ReturnedResultsProjection, permuted["returned_results"])
    left_order = cast(ex.WorkerResultOrderProjection, baseline["worker_result_order"])
    right_order = cast(ex.WorkerResultOrderProjection, permuted["worker_result_order"])
    assert right.results_in_submission_order == left.results_in_submission_order
    assert replace(right, execution_completion_id=left.execution_completion_id) == left
    assert right != left
    assert ex.returned_results_sha256(right) != ex.returned_results_sha256(left)
    assert tuple(row[1] for row in right_order.results_in_actual_delivery_order) == tuple(
        reversed(tuple(row[1] for row in left_order.results_in_actual_delivery_order))
    )
    assert right_order != left_order
    assert ex.worker_result_order_sha256(right_order) != ex.worker_result_order_sha256(left_order)
    assert permuted["carried_result_batch_id"] != baseline["carried_result_batch_id"]
    assert (
        permuted["carried_execution_completion_id"] != baseline["carried_execution_completion_id"]
    )


def test_submission_permutation_changes_submission_rows_without_sorting_delivery() -> None:
    baseline = c2_kwargs()
    permuted = _attach_c2(_submission_permuted_c1())
    invoke(permuted)
    returned_value = cast(ex.ReturnedResultsProjection, permuted["returned_results"])
    order = cast(ex.WorkerResultOrderProjection, permuted["worker_result_order"])
    assert (
        returned_value.results_in_submission_order
        != cast(
            ex.ReturnedResultsProjection, baseline["returned_results"]
        ).results_in_submission_order
    )
    assert tuple(row[2] for row in returned_value.results_in_submission_order) == tuple(
        row[0] for row in returned_value.job_result_mapping
    )
    observed_ids = cast(
        tuple[str, ...],
        permuted["carried_returned_result_ids_in_actual_delivery_order"],
    )
    assert tuple(row[1] for row in order.results_in_actual_delivery_order) == observed_ids
    assert tuple(row[1] for row in order.results_in_actual_delivery_order) != tuple(
        sorted(observed_ids)
    )


def test_worker_reassignment_changes_completion_transitively_and_worker_order_directly() -> None:
    baseline = c2_kwargs()
    reassigned = _attach_c2(_worker_reassigned_c1())
    invoke(reassigned)
    left = cast(ex.ReturnedResultsProjection, baseline["returned_results"])
    right = cast(ex.ReturnedResultsProjection, reassigned["returned_results"])
    left_order = cast(ex.WorkerResultOrderProjection, baseline["worker_result_order"])
    right_order = cast(ex.WorkerResultOrderProjection, reassigned["worker_result_order"])
    assert right.results_in_submission_order == left.results_in_submission_order
    assert right.execution_completion_id != left.execution_completion_id
    assert ex.returned_results_sha256(right) != ex.returned_results_sha256(left)
    assert tuple(row[1] for row in right_order.results_in_actual_delivery_order) == tuple(
        row[1] for row in left_order.results_in_actual_delivery_order
    )
    assert tuple(row[3] for row in right_order.results_in_actual_delivery_order) == tuple(
        reversed(tuple(row[3] for row in left_order.results_in_actual_delivery_order))
    )
    assert ex.worker_result_order_sha256(right_order) != ex.worker_result_order_sha256(left_order)


def test_serial_single_occurrence_does_not_collapse_projection_or_identity_meaning() -> None:
    kwargs = _attach_c2(_attach_c1(_one_result_kwargs()))
    invoke(kwargs)
    returned_value = cast(ex.ReturnedResultsProjection, kwargs["returned_results"])
    order = cast(ex.WorkerResultOrderProjection, kwargs["worker_result_order"])
    assert len(returned_value.results_in_submission_order) == 1
    assert tuple(row[0] for row in order.results_in_actual_delivery_order) == (0,)
    assert type(returned_value).__name__ != type(order).__name__
    assert returned_value.as_dict() != order.as_dict()
    assert ex.returned_results_sha256(returned_value) != ex.worker_result_order_sha256(order)


def test_all_four_order_notions_remain_distinct_and_acceptance_is_not_consumed() -> None:
    c1, acceptance, first_worker = _four_order_c1()
    kwargs = _attach_c2(c1)
    invoke(kwargs)
    returned_value = cast(ex.ReturnedResultsProjection, kwargs["returned_results"])
    order = cast(ex.WorkerResultOrderProjection, kwargs["worker_result_order"])
    submission = tuple(row[0] for row in returned_value.job_result_mapping)
    delivery = tuple(row[1] for row in order.results_in_actual_delivery_order)
    worker_ids = cast(
        tuple[tuple[ex.WorkerIdentityProjection, str], ...],
        kwargs["workers_in_actual_delivery_order"],
    )
    first_worker_ids = tuple(worker_ids[index][1] for index in range(len(first_worker)))
    assert submission != delivery
    assert first_worker_ids == tuple(row[3] for row in order.results_in_actual_delivery_order)
    assert acceptance not in (tuple(range(3)), (2, 0, 1), first_worker)
    parameters = inspect.signature(ex.validate_stage2d2_result_aggregates).parameters
    assert all("accept" not in name for name in parameters)


ATTACK_CASES: Final = tuple(
    (f"returned-{fault}", RETURNED_ERROR)
    for fault in (
        "missing extra reordered swapped-result swapped-payload duplicate-job "
        "mapping completion hash"
    ).split()  # noqa: SIM905 - compact parametrization preserves nine nodes
) + tuple(
    (f"worker-{fault}", ORDER_ERROR)
    for fault in (
        "missing extra swapped-index duplicate-index nonzero-first wrong-assignment "
        "copied-identity foreign-result submission-order hash historical-hash"
    ).split()  # noqa: SIM905 - compact parametrization preserves eleven nodes
)


def _raw_hash(
    value: ex.ReturnedResultsProjection | ex.WorkerResultOrderProjection,
) -> str:
    kind = (
        "returned_results" if type(value) is ex.ReturnedResultsProjection else "worker_result_order"
    )
    return protocol_hash(f"validation_evidence_{kind}/v1", value.as_dict())


@pytest.mark.parametrize(("case", "code"), ATTACK_CASES)
def test_literal_submission_and_delivery_aggregate_attacks(case: str, code: str) -> None:
    kwargs = c2_kwargs()
    if case.startswith("returned-"):
        key = "returned_results"
        value = cast(Any, kwargs["returned_results"])
        rows = value.results_in_submission_order
        fault = case.removeprefix("returned-")
        row_attacks = {
            "missing": rows[:-1],
            "extra": rows + ((BAD, rows[0][1], ALT),),
            "reordered": tuple(reversed(rows)),
            "swapped-result": (
                (rows[1][0], rows[0][1], rows[0][2]),
                (rows[0][0], rows[1][1], rows[1][2]),
            ),
            "swapped-payload": (
                (rows[0][0], rows[1][1], rows[0][2]),
                (rows[1][0], rows[0][1], rows[1][2]),
            ),
            "duplicate-job": (rows[0], (rows[1][0], rows[1][1], rows[0][2])),
        }
        if fault in row_attacks:
            value = replace(value, results_in_submission_order=row_attacks[fault])
        elif fault == "mapping":
            value = replace(value, job_result_mapping=tuple(reversed(value.job_result_mapping)))
        elif fault == "completion":
            value = replace(value, execution_completion_id=BAD)
        else:
            kwargs["carried_returned_results_sha256"] = BAD
            assert_failure(kwargs, code)
            return
    else:
        key = "worker_result_order"
        value = cast(Any, kwargs["worker_result_order"])
        rows = value.results_in_actual_delivery_order
        fault = case.removeprefix("worker-")
        submission_ids = tuple(row[1] for row in value.job_result_mapping)
        row_attacks = {
            "missing": rows[:-1],
            "extra": rows + ((len(rows), BAD, rows[0][2], rows[0][3]),),
            "swapped-index": ((1, *rows[0][1:]), (0, *rows[1][1:])),
            "duplicate-index": (rows[0], (0, *rows[1][1:])),
            "nonzero-first": tuple((index + 1, *row[1:]) for index, row in enumerate(rows)),
            "wrong-assignment": (
                (0, rows[0][1], rows[1][2], rows[1][3]),
                (1, rows[1][1], rows[0][2], rows[0][3]),
            ),
            "copied-identity": ((0, rows[0][1], rows[0][2], rows[1][3]), rows[1]),
            "foreign-result": ((0, BAD, *rows[0][2:]), rows[1]),
            "submission-order": tuple(
                (index, submission_ids[index], row[2], row[3]) for index, row in enumerate(rows)
            ),
        }
        if fault in row_attacks:
            value = replace(value, results_in_actual_delivery_order=row_attacks[fault])
        elif fault == "hash":
            kwargs["carried_worker_result_order_sha256"] = BAD
            assert_failure(kwargs, code)
            return
        else:
            kwargs["carried_worker_result_order_sha256"] = ex._identity_digest(
                tuple(row[1] for row in rows)
            )
            assert_failure(kwargs, code)
            return
    kwargs[key] = value
    kwargs[f"carried_{key}_sha256"] = _raw_hash(value)
    assert_failure(kwargs, code)


def test_foreign_relations_are_rejected_with_recomputed_aggregate_hashes() -> None:
    for key, code, fields_to_change in (
        (
            "returned_results",
            RETURNED_ERROR,
            "execution_id execution_specification_id validation_authority_id validation_run_id",
        ),
        (
            "worker_result_order",
            ORDER_ERROR,
            "execution_completion_id execution_id execution_specification_id "
            "validation_authority_id validation_run_id",
        ),
    ):
        for field_name in fields_to_change.split():
            kwargs = c2_kwargs()
            value = replace(cast(Any, kwargs[key]), **cast(Any, {field_name: BAD}))
            kwargs[key] = value
            kwargs[f"carried_{key}_sha256"] = _raw_hash(value)
            assert_failure(kwargs, code)


def test_aggregate_objects_and_hash_domains_cannot_substitute_for_each_other() -> None:
    kwargs = c2_kwargs()
    returned_value = cast(ex.ReturnedResultsProjection, kwargs["returned_results"])
    order = cast(ex.WorkerResultOrderProjection, kwargs["worker_result_order"])
    returned_hash = ex.returned_results_sha256(returned_value)
    order_hash = ex.worker_result_order_sha256(order)
    for key, own, foreign, foreign_hash, code in (
        ("returned_results", returned_value, order, order_hash, RETURNED_ERROR),
        ("worker_result_order", order, returned_value, returned_hash, ORDER_ERROR),
    ):
        for value in (own, foreign):
            attacked = c2_kwargs()
            attacked[key] = value
            attacked[f"carried_{key}_sha256"] = foreign_hash
            assert_failure(attacked, code)


def _nested_scientific_attack() -> dict[str, Any]:
    phase_b = dict(graph()["kwargs"])
    payloads = list(phase_b["returned_runs_in_actual_delivery_order"])
    payloads[0] = replace(payloads[0], run_id="forged-run")
    phase_b["returned_runs_in_actual_delivery_order"] = tuple(payloads)
    results = list(phase_b["returned_result_projections_in_actual_delivery_order"])
    payload_hash = protocol_hash(
        "validation_evidence_returned_run_payload/v1",
        returned.projection_as_dict(payloads[0]),
    )
    results[0] = replace(results[0], result_payload_sha256=payload_hash)
    result_ids = list(phase_b["carried_returned_result_ids_in_actual_delivery_order"])
    result_ids[0] = ex.returned_result_id(results[0])
    phase_b["returned_result_projections_in_actual_delivery_order"] = tuple(results)
    phase_b["carried_returned_result_ids_in_actual_delivery_order"] = tuple(result_ids)
    submitted = cast(ex.SubmittedJobsProjection, phase_b["submitted_jobs"])
    mapping = ex.build_job_result_mapping(submitted.jobs, _accepted_observations(phase_b))
    return _attach_c2(_attach_c1(phase_b, mapping=mapping))


def test_nested_scientific_mutation_beats_recomputed_c1_and_c2_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = _nested_scientific_attack()

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("3m aggregate construction ran after nested scientific failure")

    monkeypatch.setattr(ex, "decode_returned_results_projection", forbidden)
    assert_failure(kwargs, SCIENTIFIC_ERROR)


COMPOUND_CASES: Final = (
    ("completion+returned", COMPLETION_ERROR, "decode_returned_results_projection"),
    ("returned-relation+hash", RETURNED_ERROR, "returned_results_sha256"),
    ("returned-hash+worker", RETURNED_ERROR, "decode_worker_result_order_projection"),
    ("worker-relation+hash", ORDER_ERROR, "worker_result_order_sha256"),
    ("submission+delivery", RETURNED_ERROR, "decode_worker_result_order_projection"),
    ("foreign-completion+worker", RETURNED_ERROR, "decode_worker_result_order_projection"),
    ("wrong-worker-identity+hash", ORDER_ERROR, "worker_result_order_sha256"),
    ("historical-order+valid-returned", ORDER_ERROR, "executor_attestation_id"),
)


def _add_compound_fault(kwargs: dict[str, Any], case: str) -> None:
    returned_value = cast(ex.ReturnedResultsProjection, kwargs["returned_results"])
    order = cast(ex.WorkerResultOrderProjection, kwargs["worker_result_order"])
    if case == "completion+returned":
        kwargs["carried_execution_completion_id"] = BAD
        kwargs["carried_returned_results_sha256"] = BAD
    elif case == "returned-relation+hash":
        kwargs["returned_results"] = replace(returned_value, execution_id=BAD)
        kwargs["carried_returned_results_sha256"] = BAD
    elif case == "returned-hash+worker":
        kwargs["carried_returned_results_sha256"] = BAD
        kwargs["worker_result_order"] = replace(order, execution_id=BAD)
    elif case == "worker-relation+hash":
        kwargs["worker_result_order"] = replace(order, execution_id=BAD)
        kwargs["carried_worker_result_order_sha256"] = BAD
    elif case == "submission+delivery":
        kwargs["returned_results"] = replace(
            returned_value,
            results_in_submission_order=tuple(reversed(returned_value.results_in_submission_order)),
        )
        kwargs["worker_result_order"] = replace(order, execution_id=BAD)
    elif case == "foreign-completion+worker":
        kwargs["returned_results"] = replace(returned_value, execution_completion_id=BAD)
        kwargs["worker_result_order"] = replace(order, execution_completion_id=BAD)
    elif case == "wrong-worker-identity+hash":
        rows = order.results_in_actual_delivery_order
        kwargs["worker_result_order"] = replace(
            order,
            results_in_actual_delivery_order=((0, rows[0][1], rows[0][2], BAD), rows[1]),
        )
        kwargs["carried_worker_result_order_sha256"] = BAD
    else:
        kwargs["carried_worker_result_order_sha256"] = ex._identity_digest(
            tuple(row[1] for row in order.results_in_actual_delivery_order)
        )


@pytest.mark.parametrize(("case", "code", "sentinel"), COMPOUND_CASES)
def test_compound_faults_stop_at_exact_3l_to_3m_first_failure(
    case: str,
    code: str,
    sentinel: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = c2_kwargs()
    _add_compound_fault(kwargs, case)

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError(f"later predicate {sentinel} was evaluated")

    monkeypatch.setattr(ex, sentinel, forbidden, raising=False)
    assert_failure(kwargs, code)
