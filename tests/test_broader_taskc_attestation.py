from __future__ import annotations

import copy
import time
from dataclasses import replace
from typing import Any, cast

import pytest

import research_decision_engine.benchmarks.broader_execution as execution_module
from research_decision_engine.benchmarks.broader_execution import (
    ActualExecutorAttestation,
    ExecutorProvenanceError,
    _invalidate_executor_attestation,
    execute_deterministic_map,
    executor_attestation_payload,
    validate_executor_attestation,
)
from tests.taskc_execution_harness import execute_fixture


@pytest.mark.taskc_attestation
def test_real_complete_execution_issues_one_success_attestation() -> None:
    results, attestation = execute_fixture()
    payload = executor_attestation_payload(attestation)
    assert payload["execution_status"] == "success"
    assert payload["returned_result_count"] == len(results)
    assert payload["completion_identity"]
    assert payload["execution_start_identity"]
    assert cast(str, payload["execution_started_at"]) <= cast(
        str, payload["execution_completed_at"]
    )
    assert validate_executor_attestation(attestation, results=results) is attestation


@pytest.mark.taskc_attestation
def test_attestation_cannot_be_constructed_copied_deepcopied_or_mutated() -> None:
    _, attestation = execute_fixture()
    with pytest.raises(TypeError, match="issued only"):
        ActualExecutorAttestation()
    with pytest.raises(TypeError, match="cannot be copied"):
        copy.copy(attestation)
    with pytest.raises(TypeError, match="cannot be deep-copied"):
        copy.deepcopy(attestation)
    with pytest.raises(AttributeError):
        object.__setattr__(attestation, "forged", True)


@pytest.mark.taskc_attestation
@pytest.mark.parametrize(
    ("field", "changed_value"),
    (
        ("actual_worker_count", 99),
        ("configured_worker_count", 99),
        ("executor_kind", "thread_pool"),
        ("scheduling_mode", "changed-scheduling"),
        ("result_delivery_mode", "completion_order"),
        ("observed_worker_identities", ("forged-worker",)),
        ("study_id", "other-study"),
        ("validation_run_id", "other-validation-run"),
        ("implementation_commit", "f" * 40),
        ("runtime_identity", "f" * 64),
    ),
)
def test_registry_mutation_makes_attestation_stale(
    field: str,
    changed_value: object,
) -> None:
    results, mutated = execute_fixture((7, 9))
    record = execution_module._EXECUTOR_ATTESTATIONS[mutated]
    record.observation = cast(Any, replace)(record.observation, **{field: changed_value})
    with pytest.raises(ExecutorProvenanceError) as changed:
        validate_executor_attestation(mutated, results=results)
    assert changed.value.error_code == "EXECUTION_ATTESTATION_STALE"
    assert changed.value.validation_layer == "executor_attestation"
    assert changed.value.scoring_entered is False
    assert changed.value.scientific_output_entered is False


@pytest.mark.taskc_attestation
def test_explicit_revocation_makes_attestation_stale() -> None:
    results, revoked = execute_fixture((11, 13))
    _invalidate_executor_attestation(revoked)
    with pytest.raises(ExecutorProvenanceError) as stale:
        validate_executor_attestation(revoked, results=results)
    assert stale.value.error_code == "EXECUTION_ATTESTATION_STALE"


@pytest.mark.taskc_attestation
def test_fixture_attestation_is_rejected_by_production_consumer() -> None:
    results, attestation = execute_fixture()
    with pytest.raises(ExecutorProvenanceError) as captured:
        validate_executor_attestation(
            attestation,
            results=results,
            require_trust_domain="production",
        )
    assert captured.value.error_code == "EXECUTION_TRUST_DOMAIN_MISMATCH"


@pytest.mark.taskc_attestation
@pytest.mark.parametrize("attack", ("failure", "timeout"))
def test_failed_or_timed_out_execution_cannot_issue_success(attack: str) -> None:
    before = len(execution_module._EXECUTOR_ATTESTATIONS)

    def work(job: int) -> int:
        if attack == "failure":
            raise RuntimeError("planned failure")
        time.sleep(0.04)
        return job

    with pytest.raises((RuntimeError, TimeoutError)):
        execute_deterministic_map(
            work,
            (1,),
            worker_count=2,
            executor_kind="thread_pool",
            result_order="completion_order",
            timeout_seconds=0.005 if attack == "timeout" else None,
        )
    assert len(execution_module._EXECUTOR_ATTESTATIONS) == before
