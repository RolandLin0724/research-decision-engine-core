from __future__ import annotations

import time
from dataclasses import replace
from typing import cast

import pytest

import research_decision_engine.benchmarks.broader_execution as execution_module
from research_decision_engine.benchmarks.broader_execution import (
    ExecutorProvenanceError,
    execute_deterministic_map,
    executor_attestation_payload,
    executor_provenance_payload,
    validate_executor_attestation,
)
from tests.taskc_execution_harness import TaskCResult, execute_fixture, result_for


@pytest.mark.taskc_result_order
def test_result_order_hash_uses_real_returned_results_not_submitted_jobs() -> None:
    jobs = (5, 1, 3)
    results, attestation = execute_fixture(jobs)
    detail = executor_attestation_payload(attestation)
    provenance = executor_provenance_payload(attestation)
    payload_ids = tuple(execution_module._value_identity(item) for item in results)
    result_ids = cast(tuple[str, ...], detail["returned_result_identities"])
    job_ids = tuple(execution_module._value_identity(item) for item in jobs)
    assert detail["result_payload_sha256"] == payload_ids
    assert result_ids != payload_ids
    assert provenance["worker_result_order_sha256"] == execution_module._identity_digest(result_ids)
    assert provenance["worker_result_order_sha256"] != execution_module._identity_digest(job_ids)
    assert provenance["worker_result_payload_order_sha256"] == (
        execution_module._identity_digest(payload_ids)
    )


@pytest.mark.taskc_result_order
def test_completion_delivery_order_is_the_executor_observed_order() -> None:
    def delayed(job: int) -> TaskCResult:
        time.sleep(0.03 if job == 1 else 0.001)
        return result_for(job)

    results, attestation = execute_deterministic_map(
        delayed,
        (1, 2),
        worker_count=2,
        executor_kind="thread_pool",
        result_order="completion_order",
    )
    assert tuple(item.job_id for item in results) == (2, 1)
    detail = executor_attestation_payload(attestation)
    assert detail["returned_result_identities"] == tuple(
        execution_module._returned_result_identity(
            execution_id=cast(str, detail["execution_id"]),
            submitted_job_identity=execution_module._value_identity(item.job_id),
            result_payload_sha256=execution_module._value_identity(item),
        )
        for item in results
    )


@pytest.mark.taskc_result_order
def test_equal_payloads_from_another_execution_cannot_be_substituted() -> None:
    first_results, first_attestation = execute_fixture((1, 3, 5))
    second_results, _ = execute_fixture((1, 3, 5))
    assert second_results == first_results
    assert second_results is not first_results
    with pytest.raises(ExecutorProvenanceError) as captured:
        validate_executor_attestation(first_attestation, results=second_results)
    assert captured.value.error_code == "EXECUTION_RESULT_OCCURRENCE_MISMATCH"
    assert captured.value.validation_layer == "executor_attestation"
    assert captured.value.scoring_entered is False
    assert captured.value.scientific_output_entered is False


@pytest.mark.taskc_result_order
@pytest.mark.parametrize(
    ("attack", "expected_code"),
    (
        ("reordered", "EXECUTION_RESULT_ORDER_MISMATCH"),
        ("missing", "EXECUTION_RESULT_COUNT_MISMATCH"),
        ("extra", "EXECUTION_RESULT_COUNT_MISMATCH"),
        ("duplicate", "EXECUTION_DUPLICATE_RESULT_ID"),
        ("substituted", "EXECUTION_RESULT_SET_MISMATCH"),
    ),
)
def test_result_sequence_attacks_fail_before_use(attack: str, expected_code: str) -> None:
    results, attestation = execute_fixture((1, 3, 5))
    attacked: tuple[object, ...]
    if attack == "reordered":
        attacked = tuple(reversed(results))
    elif attack == "missing":
        attacked = results[:-1]
    elif attack == "extra":
        attacked = (*results, TaskCResult(99, 99))
    elif attack == "duplicate":
        attacked = (results[0], results[0], results[2])
    else:
        attacked = (results[0], TaskCResult(77, 77), results[2])
    with pytest.raises(ExecutorProvenanceError) as captured:
        validate_executor_attestation(attestation, results=attacked)
    assert captured.value.error_code == expected_code
    assert captured.value.validation_layer == "executor_attestation"
    assert captured.value.scoring_entered is False
    assert captured.value.scientific_output_entered is False


@pytest.mark.taskc_result_order
def test_complete_job_result_mapping_is_bijective_and_tamper_evident() -> None:
    results, attestation = execute_fixture((2, 4, 6), worker_count=2)
    detail = executor_attestation_payload(attestation)
    mapping = cast(tuple[tuple[str, str], ...], detail["job_to_result_mapping"])
    submitted = cast(tuple[str, ...], detail["submitted_job_identities"])
    returned = cast(tuple[str, ...], detail["returned_result_identities"])
    assert tuple(item[0] for item in mapping) == submitted
    assert {item[1] for item in mapping} == set(returned)
    record = execution_module._EXECUTOR_ATTESTATIONS[attestation]
    record.observation = replace(
        record.observation,
        job_to_result_mapping=tuple(reversed(record.observation.job_to_result_mapping)),
    )
    with pytest.raises(ExecutorProvenanceError) as captured:
        validate_executor_attestation(attestation, results=results)
    assert captured.value.error_code == "EXECUTION_ATTESTATION_STALE"
