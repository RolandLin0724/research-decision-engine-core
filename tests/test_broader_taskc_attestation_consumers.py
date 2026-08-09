from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

import research_decision_engine.benchmarks.broader_conformance as conformance_module
from research_decision_engine.benchmarks.broader_analysis import analyze_scientific_artifacts
from research_decision_engine.benchmarks.broader_assembly import (
    _require_lifecycle_execution_binding,
    reconstruct_actual_operational_provenance,
)
from research_decision_engine.benchmarks.broader_audits import (
    IntegrityAuditContext,
    _require_executor_audit_context,
    evaluate_audit,
)
from research_decision_engine.benchmarks.broader_execution import (
    ExecutorProvenanceError,
    executor_attestation_payload,
    executor_provenance_payload,
    validate_executor_attestation,
)
from research_decision_engine.benchmarks.broader_pipeline import (
    AttestedStudyExecution,
    pair_completed_runs,
)
from research_decision_engine.benchmarks.broader_protocol import canonical_json_bytes
from research_decision_engine.benchmarks.broader_smoke import (
    SmokePass,
    _require_issued_smoke_pass,
)
from tests.taskc_execution_harness import TaskCResult, execute_fixture


@pytest.mark.taskc_attestation_consumers
def test_diagnostic_operational_reconstruction_accepts_exact_attestation_and_results() -> None:
    results, attestation = execute_fixture()
    operational = reconstruct_actual_operational_provenance(
        attestation,
        consumed_results=results,
        execution_purpose="diagnostic",
    )
    detail = executor_attestation_payload(attestation)
    assert operational.started_at == detail["execution_started_at"]
    assert operational.completed_at == detail["execution_completed_at"]
    assert operational.machine["executor_execution_id"] == detail["execution_id"]


@pytest.mark.taskc_attestation_consumers
def test_operational_consumer_rejects_unrelated_results() -> None:
    _, attestation = execute_fixture()
    with pytest.raises(ExecutorProvenanceError) as captured:
        reconstruct_actual_operational_provenance(
            attestation,
            consumed_results=(TaskCResult(41, 41), TaskCResult(42, 42), TaskCResult(43, 43)),
            execution_purpose="diagnostic",
        )
    assert captured.value.error_code == "EXECUTION_RESULT_SET_MISMATCH"


@pytest.mark.taskc_attestation_consumers
@pytest.mark.parametrize("summary_kind", ("full", "worker_count", "order_hash"))
def test_summary_count_or_hash_only_cannot_replace_exact_attestation(summary_kind: str) -> None:
    results, attestation = execute_fixture()
    full = executor_provenance_payload(attestation)
    summary: object
    if summary_kind == "full":
        summary = full
    elif summary_kind == "worker_count":
        summary = {"worker_count": full["worker_count"]}
    else:
        summary = {"worker_result_order_sha256": full["worker_result_order_sha256"]}
    with pytest.raises(ExecutorProvenanceError) as captured:
        validate_executor_attestation(summary, results=results)  # type: ignore[arg-type]
    assert captured.value.error_code == "EXECUTION_ATTESTATION_NOT_ISSUED"


@pytest.mark.taskc_attestation_consumers
def test_cross_bundle_and_authority_context_are_rejected() -> None:
    results, attestation = execute_fixture()
    with pytest.raises(ExecutorProvenanceError) as bundle:
        validate_executor_attestation(
            attestation,
            results=results,
            expected_evidence_bundle_identity="unrelated-bundle",
        )
    assert bundle.value.error_code == "EXECUTION_EVIDENCE_BUNDLE_MISMATCH"
    with pytest.raises(ExecutorProvenanceError) as authority:
        validate_executor_attestation(
            attestation,
            results=results,
            execution_authority=object(),
        )
    assert authority.value.error_code == "EXECUTION_AUTHORITY_MISMATCH"


@pytest.mark.taskc_attestation_consumers
def test_missing_attestation_fails_before_operational_or_scientific_output() -> None:
    with pytest.raises(TypeError):
        reconstruct_actual_operational_provenance()  # type: ignore[call-arg]


@pytest.mark.taskc_attestation_consumers
def test_equal_results_from_another_execution_fail_operational_reconstruction() -> None:
    _, first_attestation = execute_fixture()
    second_results, _ = execute_fixture()
    with pytest.raises(ExecutorProvenanceError) as captured:
        reconstruct_actual_operational_provenance(
            first_attestation,
            consumed_results=second_results,
            execution_purpose="diagnostic",
        )
    assert captured.value.error_code == "EXECUTION_RESULT_OCCURRENCE_MISMATCH"
    assert captured.value.validation_layer == "executor_attestation"
    assert captured.value.scoring_entered is False
    assert captured.value.scientific_output_entered is False


@pytest.mark.taskc_attestation_consumers
def test_diagnostic_results_cannot_enter_scientific_analysis() -> None:
    results, _ = execute_fixture()
    with pytest.raises(ExecutorProvenanceError) as captured:
        analyze_scientific_artifacts(cast(Any, results))
    assert captured.value.error_code == "EXECUTION_PURPOSE_MISMATCH"
    assert captured.value.validation_layer == "executor_attestation"
    assert captured.value.scoring_entered is False
    assert captured.value.scientific_output_entered is False


@pytest.mark.taskc_attestation_consumers
def test_constructed_study_wrapper_cannot_promote_diagnostic_results() -> None:
    results, attestation = execute_fixture()
    wrapper = AttestedStudyExecution(cast(Any, results), attestation, None, False)
    with pytest.raises(ValueError, match="exact-issued full-study execution"):
        pair_completed_runs(wrapper)


@pytest.mark.taskc_attestation_consumers
def test_lifecycle_rejects_artifacts_without_full_study_execution_binding() -> None:
    with pytest.raises(ValueError, match="exact-issued executor-bound artifacts"):
        _require_lifecycle_execution_binding({"lookalike": b"payload"})


@pytest.mark.taskc_attestation_consumers
def test_conformance_has_no_missing_fixture_execution_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback_entered = False

    def forbidden_fallback(**_: object) -> object:
        nonlocal fallback_entered
        fallback_entered = True
        raise AssertionError("conformance fallback entered")

    monkeypatch.setattr(conformance_module, "build_production_fixture", forbidden_fallback)
    with pytest.raises(TypeError, match="fixture"):
        conformance_module.build_conformance_payloads(  # type: ignore[call-arg]
            Path("unused"),
            oracle_conformance_result=cast(Any, object()),
            oracle_evidence_binding=cast(Any, object()),
        )
    assert fallback_entered is False


@pytest.mark.taskc_attestation_consumers
def test_a06_requires_two_exact_independent_executor_result_batches() -> None:
    first_results, first_attestation = execute_fixture(execution_purpose="smoke_validation")
    replay_results, replay_attestation = execute_fixture(execution_purpose="smoke_validation")
    payload = canonical_json_bytes(
        [[item.job_id, item.value] for item in first_results],
        final_lf=True,
    )
    context = IntegrityAuditContext(
        runs=cast(Any, first_results),
        replay_runs=cast(Any, replay_results),
        first_payload=payload,
        replay_payload=payload,
        historical_before=(),
        historical_after=(),
        executor_attestation=first_attestation,
        replay_executor_attestation=replay_attestation,
        executor_results=cast(Any, first_results),
        replay_executor_results=cast(Any, replay_results),
        execution_purpose="smoke_validation",
    )
    assert evaluate_audit("A06-DETERMINISM", context).status == "PASS"

    with pytest.raises(ExecutorProvenanceError) as captured:
        _require_executor_audit_context(
            replace(context, replay_executor_attestation=first_attestation),
            trust_domain="fixture",
        )
    assert captured.value.error_code == "AUDIT_EXECUTION_RESULT_BINDING_MISMATCH"
    assert captured.value.validation_layer == "integrity_audit_context"
    assert captured.value.scoring_entered is False
    assert captured.value.scientific_output_entered is False


@pytest.mark.taskc_attestation_consumers
def test_constructed_smoke_pass_cannot_claim_executor_authority() -> None:
    results, attestation = execute_fixture(execution_purpose="smoke_validation")
    manual = SmokePass(
        runs=cast(Any, results),
        returned_runs=cast(Any, results),
        deterministic_payload=b"[]\n",
        elapsed_seconds=0.0,
        executor_attestation=attestation,
    )
    with pytest.raises(ExecutorProvenanceError) as captured:
        _require_issued_smoke_pass(
            manual,
            execution_authority=None,
            require_trust_domain="fixture",
        )
    assert captured.value.error_code == "SMOKE_PASS_NOT_ISSUED"
    assert captured.value.validation_layer == "smoke_pass_binding"
    assert captured.value.scoring_entered is False
    assert captured.value.scientific_output_entered is False
