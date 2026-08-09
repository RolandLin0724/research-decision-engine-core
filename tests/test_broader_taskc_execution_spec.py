from __future__ import annotations

import copy
from dataclasses import replace

import pytest

import research_decision_engine.benchmarks.broader_execution as execution_module
from research_decision_engine.benchmarks.broader_execution import (
    ExecutionSpecification,
    ExecutorProvenanceError,
    execute_deterministic_map,
    execution_specification_payload,
    executor_execution_specification,
    validate_executor_attestation,
)
from research_decision_engine.benchmarks.broader_protocol import (
    PROTOCOL_CHECKPOINT,
    PROTOCOL_VERSION,
)
from tests.taskc_execution_harness import execute_fixture


@pytest.mark.taskc_execution_spec
def test_specification_binds_exact_submitted_ids_and_order() -> None:
    jobs = (5, 1, 3)
    results, attestation = execute_fixture(jobs)
    specification = executor_execution_specification(attestation)
    payload = execution_specification_payload(specification)
    assert payload["study_id"] == PROTOCOL_VERSION
    assert payload["evaluation_id"] == PROTOCOL_VERSION
    assert payload["protocol_checkpoint"] == PROTOCOL_CHECKPOINT
    assert payload["submitted_job_count"] == 3
    assert payload["submitted_job_identities"] == tuple(
        execution_module._value_identity(item) for item in jobs
    )
    assert payload["submission_order_sha256"] == execution_module._identity_digest(
        payload["submitted_job_identities"]
    )
    assert payload["implementation_commit"]
    assert payload["implementation_tree_sha256"]
    assert payload["implementation_diff_sha256"]
    assert payload["runtime_identity"]
    assert payload["dependency_lock_sha256"]
    assert payload["executor_implementation_identity"]
    assert payload["executor_instance_identity"]
    validate_executor_attestation(attestation, results=results)


@pytest.mark.taskc_execution_spec
@pytest.mark.parametrize(
    ("jobs", "error_code"),
    (((), "EXECUTION_JOB_ID_MISSING"), ((1, 1), "EXECUTION_DUPLICATE_JOB_ID")),
)
def test_specification_rejects_missing_or_duplicate_job_ids(
    jobs: tuple[int, ...], error_code: str
) -> None:
    with pytest.raises(ExecutorProvenanceError) as captured:
        execute_fixture(jobs)
    assert captured.value.error_code == error_code
    assert captured.value.scoring_entered is False
    assert captured.value.scientific_output_entered is False


@pytest.mark.taskc_execution_spec
def test_specification_cannot_be_constructed_copied_or_deepcopied() -> None:
    _, attestation = execute_fixture()
    specification = executor_execution_specification(attestation)
    with pytest.raises(TypeError, match="issued only"):
        ExecutionSpecification()
    with pytest.raises(TypeError, match="cannot be copied"):
        copy.copy(specification)
    with pytest.raises(TypeError, match="cannot be deep-copied"):
        copy.deepcopy(specification)


@pytest.mark.taskc_execution_spec
def test_cross_study_cross_run_and_changed_runtime_fail_at_spec_or_context_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, attestation = execute_fixture()
    payload = execution_specification_payload(executor_execution_specification(attestation))
    with pytest.raises(ExecutorProvenanceError) as study:
        validate_executor_attestation(attestation, results=results, expected_study_id="other")
    assert study.value.error_code == "EXECUTION_STUDY_MISMATCH"
    with pytest.raises(ExecutorProvenanceError) as run:
        validate_executor_attestation(
            attestation,
            results=results,
            expected_validation_run_id="other-validation-run",
        )
    assert run.value.error_code == "EXECUTION_VALIDATION_RUN_MISMATCH"

    current = execution_module._current_execution_environment()
    monkeypatch.setattr(
        execution_module,
        "_current_execution_environment",
        lambda: replace(current, runtime_identity="f" * 64),
    )
    with pytest.raises(ExecutorProvenanceError) as changed:
        validate_executor_attestation(attestation, results=results)
    assert changed.value.error_code == "EXECUTION_SPECIFICATION_IMPLEMENTATION_MISMATCH"
    assert payload["validation_run_id"] != "other-validation-run"


@pytest.mark.taskc_execution_spec
def test_public_executor_cannot_claim_full_study_purpose() -> None:
    with pytest.raises(ExecutorProvenanceError) as captured:
        execute_deterministic_map(
            lambda value: value + 1,
            (1,),
            worker_count=1,
            executor_kind="serial",
            execution_purpose="full_study",
        )
    assert captured.value.error_code == "EXECUTION_FULL_STUDY_AUTHORITY_REQUIRED"
    assert captured.value.validation_layer == "execution_specification"
    assert captured.value.scoring_entered is False
    assert captured.value.scientific_output_entered is False
