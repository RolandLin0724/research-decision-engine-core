from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import research_decision_engine.benchmarks.broader_oracle as oracle_module
import research_decision_engine.benchmarks.broader_smoke as smoke_module
from research_decision_engine.benchmarks.broader_audits import (
    IntegrityAuditContext,
    SmokeAuditResult,
    evaluate_audit,
)
from research_decision_engine.benchmarks.broader_oracle import (
    OracleConformanceResult,
    OracleError,
    OracleEvidenceBinding,
    OracleFixtureBinding,
    OracleFixtureResult,
    begin_oracle_evidence_binding,
    decision_key,
    transform_key,
)
from research_decision_engine.benchmarks.broader_protocol import (
    EXPECTED_ORACLE_DOMAIN_SHA256,
    canonical_json_bytes,
    protocol_hash,
)
from research_decision_engine.benchmarks.broader_smoke import (
    ProductionFixtureEvidence,
    SmokeSummary,
)

_AUTHORIZED_SMOKE_JSON_KEYS = {
    "all_smoke_audits_passed",
    "arm_count",
    "audits",
    "budget_count",
    "canonical_artifact_contract_count",
    "canonical_full_study_audits_run",
    "deterministic_replay_equal",
    "deterministic_smoke_success",
    "first_pass_seconds",
    "first_payload_sha256",
    "full_replication_authorized",
    "full_replication_run",
    "implementation_blockers",
    "implementation_contracts_complete",
    "implementation_file_sha256",
    "implementation_source_sha256",
    "implementation_test_sha256",
    "independent_review_status",
    "integrity_audit_count",
    "operational_concerns",
    "oracle_conformance_run",
    "oracle_conformance_sha256",
    "oracle_domain_count",
    "output_bytes",
    "production_fixture",
    "protected_source_sha256",
    "protocol_version",
    "replay_payload_sha256",
    "replay_seconds",
    "replay_trajectory_count",
    "safe_for_full_replication",
    "scientific_conclusions_permitted",
    "smoke_seed_count",
    "smoke_trajectory_count",
    "smoke_version",
    "smoke_world_count",
    "test_count",
    "test_file_sha256",
    "validation_only",
}


def _summary(*, output_bytes: int = 0, smoke_version: str = "test-smoke/v1") -> SmokeSummary:
    audit = SmokeAuditResult(
        audit_id="A04-ORACLE-ISOLATION",
        audit_order=4,
        requirement="actual execution is required",
        observed="INCONCLUSIVE",
        status="INCONCLUSIVE",
    )
    fixture = ProductionFixtureEvidence(
        validation_only=True,
        trajectory_count=1,
        replay_trajectory_count=1,
        deterministic_replay_equal=True,
        audit_statuses=((audit.audit_id, audit.status),),
        all_audits_passed=False,
        canonical_artifact_count=13,
        finalization_succeeded=True,
        early_optimizer_rejection_verified=True,
        success=False,
    )
    return SmokeSummary(
        smoke_version=smoke_version,
        protocol_version="test-protocol/v1",
        validation_only=True,
        scientific_conclusions_permitted=False,
        smoke_world_count=1,
        smoke_seed_count=1,
        budget_count=1,
        arm_count=1,
        smoke_trajectory_count=1,
        replay_trajectory_count=1,
        canonical_artifact_contract_count=13,
        integrity_audit_count=1,
        first_payload_sha256="1" * 64,
        replay_payload_sha256="1" * 64,
        deterministic_replay_equal=True,
        first_pass_seconds=1.0,
        replay_seconds=1.0,
        output_bytes=output_bytes,
        test_count=1,
        implementation_source_sha256="2" * 64,
        implementation_test_sha256="3" * 64,
        implementation_file_sha256=(("implementation.py", "4" * 64),),
        test_file_sha256=(("test_implementation.py", "5" * 64),),
        protected_source_sha256=(("protected.py", "6" * 64),),
        oracle_domain_count=None,
        oracle_conformance_sha256=None,
        oracle_conformance_run=False,
        audits=(audit,),
        all_smoke_audits_passed=False,
        deterministic_smoke_success=True,
        implementation_contracts_complete=True,
        production_fixture=fixture,
        independent_review_status="pending",
        canonical_full_study_audits_run=False,
        full_replication_run=False,
        full_replication_authorized=False,
        implementation_blockers=(),
        operational_concerns=("No scientific interpretation was performed.",),
        safe_for_full_replication=False,
    )


def _persist(output_directory: Path, evidence: smoke_module.RenderedSmokeEvidence) -> None:
    output_directory.mkdir()
    (output_directory / "smoke_validation.json").write_bytes(evidence.json_bytes)
    (output_directory / "SMOKE_VALIDATION_REPORT.md").write_bytes(evidence.markdown_bytes)


def _oracle_binding(tmp_path: Path, label: str = "primary") -> OracleEvidenceBinding:
    return begin_oracle_evidence_binding(
        validation_run_identity=hashlib.sha256(
            f"validation:{tmp_path}:{label}".encode()
        ).hexdigest(),
        evidence_bundle_identity=hashlib.sha256(f"bundle:{tmp_path}:{label}".encode()).hexdigest(),
    )


def _oracle_fixture_binding(tmp_path: Path, label: str = "primary") -> OracleFixtureBinding:
    return oracle_module._begin_oracle_fixture_binding(
        validation_run_identity=hashlib.sha256(
            f"fixture-validation:{tmp_path}:{label}".encode()
        ).hexdigest(),
        evidence_bundle_identity=hashlib.sha256(
            f"fixture-bundle:{tmp_path}:{label}".encode()
        ).hexdigest(),
    )


def _oracle_fixture_partitions() -> tuple[tuple[str, tuple[tuple[str, ...], ...]], ...]:
    return (
        (
            "first",
            (
                decision_key(
                    world_id="h_adam_low",
                    seed=9000,
                    candidate_id="g00-adam-r1",
                    replication_id="decision-group-00-r0001",
                ),
                decision_key(
                    world_id="h_adam_low",
                    seed=9000,
                    candidate_id="g00-sgd-r1",
                    replication_id="decision-group-00-r0001",
                ),
            ),
        ),
        (
            "second",
            (
                decision_key(
                    world_id="h_null_high",
                    seed=9001,
                    candidate_id="irrelevant-objective-r1",
                    replication_id="irrelevant-r0001",
                ),
            ),
        ),
    )


def _oracle_fixture_digest(
    partitions: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...],
) -> str:
    digest = hashlib.sha256()
    for _, keys in partitions:
        for key in keys:
            transformed = transform_key(key)
            digest.update(
                canonical_json_bytes(
                    (
                        key[0],
                        transformed.serialized_key.hex(),
                        transformed.digest_hex,
                        transformed.u_string,
                        transformed.z_string,
                    ),
                    final_lf=True,
                )
            )
    return digest.hexdigest()


def _issued_oracle_fixture(
    tmp_path: Path,
) -> tuple[
    OracleFixtureBinding,
    OracleFixtureResult,
    tuple[tuple[str, tuple[tuple[str, ...], ...]], ...],
]:
    binding = _oracle_fixture_binding(tmp_path)
    partitions = _oracle_fixture_partitions()
    result = oracle_module._execute_oracle_fixture(binding, partitions)
    oracle_module._validate_oracle_fixture_result(
        result,
        binding=binding,
        expected_key_count=3,
        expected_unique_key_count=3,
        expected_partition_counts=(("first", 2), ("second", 1)),
        expected_sha256=_oracle_fixture_digest(partitions),
    )
    return binding, result, partitions


def _oracle_audit_context(
    result: OracleConformanceResult | None,
    binding: OracleEvidenceBinding | None,
) -> IntegrityAuditContext:
    return IntegrityAuditContext(
        runs=(),
        replay_runs=(),
        first_payload=b"[]\n",
        replay_payload=b"[]\n",
        historical_before=(),
        historical_after=(),
        oracle_conformance_result=result,
        oracle_evidence_binding=binding,
    )


def test_actual_small_oracle_execution_issues_derived_immutable_result(tmp_path: Path) -> None:
    binding, result, partitions = _issued_oracle_fixture(tmp_path)
    with pytest.raises(OracleError, match="already claimed an execution attempt"):
        oracle_module._execute_oracle_fixture(binding, partitions)

    assert result.execution_status == "COMPLETED"
    assert type(result) is OracleFixtureResult
    assert type(binding) is OracleFixtureBinding
    assert id(result) not in oracle_module._ISSUED_ORACLE_CONFORMANCE_RESULTS
    assert id(binding) not in oracle_module._ISSUED_ORACLE_EVIDENCE_BINDINGS
    assert result.failure_details == ()
    assert result.actual_key_count == result.actual_unique_key_count == 3
    assert result.actual_partition_counts == (("first", 2), ("second", 1))
    assert result.actual_sha256 == _oracle_fixture_digest(partitions)
    assert result.implementation_commit == binding.implementation_commit
    assert result.source_design_sha256 == binding.source_design_sha256
    assert result.implementation_source_sha256 == binding.implementation_source_sha256
    assert result.implementation_test_sha256 == binding.implementation_test_sha256
    assert result.validation_run_identity == binding.validation_run_identity
    assert result.evidence_bundle_identity == binding.evidence_bundle_identity
    with pytest.raises((AttributeError, TypeError)):
        result.actual_key_count = 4  # type: ignore[misc]


def test_frozen_expected_digest_and_caller_claims_are_not_execution_proof(
    tmp_path: Path,
) -> None:
    binding = _oracle_binding(tmp_path)
    lookalike = SimpleNamespace(
        execution_status="PASS",
        actual_key_count=117_952,
        actual_unique_key_count=117_952,
        actual_sha256=EXPECTED_ORACLE_DOMAIN_SHA256,
    )

    with pytest.raises(OracleError, match="exact issued result"):
        smoke_module._validated_oracle_evidence(
            cast(OracleConformanceResult, lookalike),
            binding,
        )


def test_exact_production_lookalike_without_execution_provenance_is_rejected(
    tmp_path: Path,
) -> None:
    binding = _oracle_binding(tmp_path, "exact-lookalike")
    current = oracle_module._current_oracle_identities()
    forged = object.__new__(OracleConformanceResult)
    values: dict[str, object] = {
        "conformance_version": oracle_module.CONFORMANCE_GENERATOR_VERSION,
        "oracle_version": oracle_module.ORACLE_VERSION,
        "issuer_kind": "production",
        "execution_status": "COMPLETED",
        "actual_key_count": 117_952,
        "actual_unique_key_count": 117_952,
        "actual_partition_counts": oracle_module.EXPECTED_ORACLE_PARTITION_COUNTS,
        "actual_sha256": EXPECTED_ORACLE_DOMAIN_SHA256,
        "oracle_source_sha256": current.oracle_source_sha256,
        "implementation_commit": binding.implementation_commit,
        "design_checkpoint_commit": binding.design_checkpoint_commit,
        "source_design_sha256": binding.source_design_sha256,
        "implementation_source_sha256": binding.implementation_source_sha256,
        "implementation_test_sha256": binding.implementation_test_sha256,
        "validation_run_identity": binding.validation_run_identity,
        "evidence_bundle_identity": binding.evidence_bundle_identity,
        "evidence_binding_identity": binding.binding_identity,
        "failure_details": (),
    }
    for field_name, value in values.items():
        object.__setattr__(forged, field_name, value)
    object.__setattr__(
        forged,
        "execution_identity",
        protocol_hash(
            "oracle_conformance_execution/v1",
            oracle_module._execution_values(forged),
        ),
    )

    try:
        with pytest.raises(OracleError, match="forged or stale"):
            oracle_module.validate_oracle_conformance_result(forged, binding=binding)
    finally:
        oracle_module.close_oracle_evidence_binding(binding)


def test_a04_rejects_caller_claims_and_nonproduction_fixture_results(tmp_path: Path) -> None:
    binding, result, _ = _issued_oracle_fixture(tmp_path)
    caller_binding = _oracle_binding(tmp_path, "caller-lookalike")
    lookalike = SimpleNamespace(
        execution_status="PASS",
        actual_key_count=117_952,
        actual_unique_key_count=117_952,
        actual_sha256=EXPECTED_ORACLE_DOMAIN_SHA256,
    )

    try:
        missing = evaluate_audit("A04-ORACLE-ISOLATION", _oracle_audit_context(None, None))
        caller = evaluate_audit(
            "A04-ORACLE-ISOLATION",
            _oracle_audit_context(
                cast(OracleConformanceResult, lookalike),
                caller_binding,
            ),
        )
        fixture = evaluate_audit(
            "A04-ORACLE-ISOLATION",
            _oracle_audit_context(
                cast(OracleConformanceResult, result),
                cast(OracleEvidenceBinding, binding),
            ),
        )

        assert missing.status == "FAIL"
        assert caller.status == "FAIL"
        assert fixture.status == "FAIL"
        assert "exact issued result" in caller.detail
        assert "exact issued binding" in fixture.detail
    finally:
        oracle_module.close_oracle_evidence_binding(caller_binding)
        oracle_module._close_oracle_fixture_binding(binding)


def test_old_caller_supplied_digest_api_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="oracle_conformance_sha256"):
        smoke_module.run_smoke(
            tmp_path / "evidence",
            oracle_conformance_sha256=EXPECTED_ORACLE_DOMAIN_SHA256,  # type: ignore[call-arg]
        )


def test_smoke_generation_requires_explicit_pytest_and_oracle_capabilities() -> None:
    signature = inspect.signature(smoke_module.run_smoke)
    for name in (
        "validation_result",
        "oracle_conformance_result",
        "oracle_evidence_binding",
    ):
        parameter = signature.parameters[name]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty


def test_smoke_cli_refuses_before_any_implicit_oracle_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed = False

    def unexpected_execution(binding: OracleEvidenceBinding) -> OracleConformanceResult:
        nonlocal executed
        del binding
        executed = True
        raise AssertionError("CLI started an implicit Oracle audit.")

    monkeypatch.setattr(smoke_module, "execute_oracle_conformance", unexpected_execution)
    with pytest.raises(RuntimeError, match="requires an in-process exact-issued pytest result"):
        smoke_module.main(["smoke", "--output-directory", str(tmp_path / "evidence")])
    assert not executed


def test_manually_constructed_exact_result_lookalike_is_rejected(tmp_path: Path) -> None:
    binding, result, partitions = _issued_oracle_fixture(tmp_path)
    lookalike = object.__new__(OracleFixtureResult)
    for item in fields(OracleFixtureResult):
        object.__setattr__(lookalike, item.name, getattr(result, item.name))

    with pytest.raises(OracleError, match="forged or stale"):
        oracle_module._validate_oracle_fixture_result(
            lookalike,
            binding=binding,
            expected_key_count=3,
            expected_unique_key_count=3,
            expected_partition_counts=(("first", 2), ("second", 1)),
            expected_sha256=_oracle_fixture_digest(partitions),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("execution_status", "PASS"),
        ("actual_key_count", 117_952),
        ("actual_sha256", EXPECTED_ORACLE_DOMAIN_SHA256),
    ),
)
def test_mutated_caller_status_count_or_digest_is_rejected(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    binding, result, partitions = _issued_oracle_fixture(tmp_path)
    object.__setattr__(result, field, value)

    with pytest.raises(OracleError, match="issued fingerprint"):
        oracle_module._validate_oracle_fixture_result(
            result,
            binding=binding,
            expected_key_count=3,
            expected_unique_key_count=3,
            expected_partition_counts=(("first", 2), ("second", 1)),
            expected_sha256=_oracle_fixture_digest(partitions),
        )


@pytest.mark.parametrize("identity_kind", ("design", "implementation"))
def test_issued_result_from_another_source_identity_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    identity_kind: str,
) -> None:
    current = oracle_module._current_oracle_identities()
    if identity_kind == "design":
        other = replace(
            current,
            design_checkpoint_commit="0" * 40,
            source_design_sha256="0" * 64,
        )
    else:
        other = replace(
            current,
            implementation_commit="0" * 40,
            implementation_source_sha256="0" * 64,
            implementation_test_sha256="0" * 64,
            oracle_source_sha256="0" * 64,
        )
    monkeypatch.setattr(oracle_module, "_current_oracle_identities", lambda: other)
    binding = _oracle_fixture_binding(tmp_path)
    partitions = _oracle_fixture_partitions()
    result = oracle_module._execute_oracle_fixture(binding, partitions)
    monkeypatch.undo()

    with pytest.raises(OracleError, match="current source identities"):
        oracle_module._validate_oracle_fixture_result(
            result,
            binding=binding,
            expected_key_count=3,
            expected_unique_key_count=3,
            expected_partition_counts=(("first", 2), ("second", 1)),
            expected_sha256=_oracle_fixture_digest(partitions),
        )


def test_changed_or_duplicate_key_is_rejected(tmp_path: Path) -> None:
    baseline = _oracle_fixture_partitions()
    expected_sha256 = _oracle_fixture_digest(baseline)
    changed_key = decision_key(
        world_id="h_adam_low",
        seed=9002,
        candidate_id="g00-adam-r1",
        replication_id="decision-group-00-r0001",
    )
    attacks = (
        (("first", (baseline[0][1][0], changed_key)), ("second", baseline[1][1])),
        (("first", (*baseline[0][1], baseline[0][1][0])), ("second", baseline[1][1])),
    )
    for index, partitions in enumerate(attacks):
        binding = _oracle_fixture_binding(tmp_path, f"key-attack-{index}")
        result = oracle_module._execute_oracle_fixture(binding, partitions)
        with pytest.raises(OracleError, match="digest mismatch|unique keys"):
            oracle_module._validate_oracle_fixture_result(
                result,
                binding=binding,
                expected_key_count=3 if index == 0 else 4,
                expected_unique_key_count=3 if index == 0 else 4,
                expected_partition_counts=(
                    ("first", 2 if index == 0 else 3),
                    ("second", 1),
                ),
                expected_sha256=expected_sha256,
            )


def test_changed_partition_is_rejected_even_when_digest_is_correct(tmp_path: Path) -> None:
    baseline = _oracle_fixture_partitions()
    repartitioned = (
        ("first", (baseline[0][1][0],)),
        ("second", (baseline[0][1][1], *baseline[1][1])),
    )
    binding = _oracle_fixture_binding(tmp_path)
    result = oracle_module._execute_oracle_fixture(binding, repartitioned)

    assert result.actual_sha256 == _oracle_fixture_digest(baseline)
    with pytest.raises(OracleError, match="partition counts"):
        oracle_module._validate_oracle_fixture_result(
            result,
            binding=binding,
            expected_key_count=3,
            expected_unique_key_count=3,
            expected_partition_counts=(("first", 2), ("second", 1)),
            expected_sha256=_oracle_fixture_digest(baseline),
        )


def test_fixture_result_cannot_be_promoted_to_frozen_production_evidence(tmp_path: Path) -> None:
    binding, result, _ = _issued_oracle_fixture(tmp_path)

    with pytest.raises(OracleError, match="exact issued binding"):
        oracle_module.validate_oracle_conformance_result(
            cast(OracleConformanceResult, result),
            binding=cast(OracleEvidenceBinding, binding),
        )

    production_binding = _oracle_binding(tmp_path, "production-domain")
    try:
        with pytest.raises(OracleError, match="exact issued result"):
            oracle_module.validate_oracle_conformance_result(
                cast(OracleConformanceResult, result),
                binding=production_binding,
            )
        a04 = evaluate_audit(
            "A04-ORACLE-ISOLATION",
            _oracle_audit_context(
                cast(OracleConformanceResult, result),
                production_binding,
            ),
        )
        assert a04.status == "FAIL"
        assert "exact issued result" in a04.detail
    finally:
        oracle_module.close_oracle_evidence_binding(production_binding)


def test_stale_result_cannot_be_reused_for_another_evidence_bundle(tmp_path: Path) -> None:
    binding, result, partitions = _issued_oracle_fixture(tmp_path)
    other_binding = _oracle_fixture_binding(tmp_path, "other-bundle")

    with pytest.raises(OracleError, match="another fixture binding"):
        oracle_module._validate_oracle_fixture_result(
            result,
            binding=other_binding,
            expected_key_count=3,
            expected_unique_key_count=3,
            expected_partition_counts=(("first", 2), ("second", 1)),
            expected_sha256=_oracle_fixture_digest(partitions),
        )


def test_evidence_binding_owns_the_summary_implementation_and_test_identity(
    tmp_path: Path,
) -> None:
    binding = _oracle_binding(tmp_path)
    summary = replace(
        _summary(),
        implementation_source_sha256=binding.implementation_source_sha256,
        implementation_test_sha256=binding.implementation_test_sha256,
    )

    smoke_module._assert_oracle_binding_matches_summary(binding, summary)
    with pytest.raises(RuntimeError, match="changed during the validation run"):
        smoke_module._assert_oracle_binding_matches_summary(
            binding,
            replace(summary, implementation_test_sha256="0" * 64),
        )


def test_output_bytes_changes_with_final_markdown_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = smoke_module._render_smoke_evidence(_summary())
    renderer = smoke_module._markdown_report
    monkeypatch.setattr(
        smoke_module,
        "_markdown_report",
        lambda summary, **kwargs: renderer(summary, **kwargs) + "more\n",
    )

    changed = smoke_module._render_smoke_evidence(_summary())

    assert changed.summary.output_bytes == len(changed.json_bytes) + len(changed.markdown_bytes)
    assert changed.summary.output_bytes > baseline.summary.output_bytes


def test_output_bytes_changes_with_final_json_length_only() -> None:
    baseline = smoke_module._render_smoke_evidence(_summary())
    changed = smoke_module._render_smoke_evidence(_summary(smoke_version="test-smoke/longer/v1"))

    assert len(changed.markdown_bytes) == len(baseline.markdown_bytes)
    assert len(changed.json_bytes) > len(baseline.json_bytes)
    assert changed.summary.output_bytes == len(changed.json_bytes) + len(changed.markdown_bytes)
    assert changed.summary.output_bytes > baseline.summary.output_bytes


def test_rendering_ignores_stale_or_caller_supplied_output_bytes_and_is_repeatable() -> None:
    first = smoke_module._render_smoke_evidence(_summary(output_bytes=15_905))
    second = smoke_module._render_smoke_evidence(_summary(output_bytes=999_999))

    assert first == second
    assert first.summary.output_bytes != 15_905
    assert first.summary.output_bytes == len(first.json_bytes) + len(first.markdown_bytes)


def test_markdown_identifies_oracle_evidence_as_a_separately_executed_result() -> None:
    evidence = smoke_module._render_smoke_evidence(replace(_summary(), oracle_conformance_run=True))
    markdown = evidence.markdown_bytes.decode("utf-8")

    assert "Separately executed Oracle conformance result consumed by smoke: true" in markdown
    assert "Oracle conformance run by smoke" not in markdown


def test_smoke_json_schema_and_readiness_fields_remain_frozen() -> None:
    evidence = smoke_module._render_smoke_evidence(_summary())
    document = json.loads(evidence.json_bytes)

    assert set(document) == _AUTHORIZED_SMOKE_JSON_KEYS
    assert document["independent_review_status"] == "pending"
    assert document["safe_for_full_replication"] is False
    assert document["full_replication_authorized"] is False


def test_persisted_evidence_reopens_to_the_exact_derived_total(tmp_path: Path) -> None:
    evidence = smoke_module._render_smoke_evidence(_summary())
    output_directory = tmp_path / "evidence"
    _persist(output_directory, evidence)

    reopened = smoke_module._verify_persisted_smoke_evidence(output_directory, evidence)

    assert reopened == evidence.summary.output_bytes
    assert (output_directory / "smoke_validation.json").read_bytes() == evidence.json_bytes
    assert (output_directory / "SMOKE_VALIDATION_REPORT.md").read_bytes() == (
        evidence.markdown_bytes
    )


def test_unbound_junit_side_file_is_rejected_without_changing_output_bytes(
    tmp_path: Path,
) -> None:
    evidence = smoke_module._render_smoke_evidence(_summary())
    output_directory = tmp_path / "evidence"
    _persist(output_directory, evidence)
    (output_directory / "pytest-junit.xml").write_bytes(b"<testsuites />\n")

    assert evidence.summary.output_bytes == len(evidence.json_bytes) + len(evidence.markdown_bytes)
    with pytest.raises(RuntimeError, match="lacks an issued validation-result binding"):
        smoke_module._verify_persisted_smoke_evidence(output_directory, evidence)


def test_persisted_verifier_rejects_the_committed_15905_vs_18125_inconsistency(
    tmp_path: Path,
) -> None:
    output_directory = tmp_path / "stale"
    output_directory.mkdir()
    json_bytes = b'{"output_bytes":15905}\n'
    report_bytes = b"x" * (18_125 - len(json_bytes))
    (output_directory / "smoke_validation.json").write_bytes(json_bytes)
    (output_directory / "SMOKE_VALIDATION_REPORT.md").write_bytes(report_bytes)

    with pytest.raises(RuntimeError, match="recorded 15905, reopened 18125"):
        smoke_module._verify_persisted_smoke_evidence(output_directory)


def test_fixed_point_failure_is_bounded_and_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke_module,
        "_markdown_report",
        lambda summary, **kwargs: "x" * (summary.output_bytes + 1),
    )

    with pytest.raises(RuntimeError, match="did not reach a fixed point"):
        smoke_module._render_smoke_evidence(_summary())


def test_persisted_verifier_rejects_post_render_byte_changes(tmp_path: Path) -> None:
    evidence = smoke_module._render_smoke_evidence(_summary())
    output_directory = tmp_path / "evidence"
    _persist(output_directory, evidence)
    report_path = output_directory / "SMOKE_VALIDATION_REPORT.md"
    report_path.write_bytes(report_path.read_bytes() + b"changed\n")

    with pytest.raises(RuntimeError, match="differs from the reopened"):
        smoke_module._verify_persisted_smoke_evidence(output_directory, evidence)
