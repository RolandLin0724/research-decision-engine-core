from __future__ import annotations

import ast
import hashlib
import inspect
import textwrap
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import research_decision_engine.benchmarks.broader_audits as audit_module
import research_decision_engine.benchmarks.broader_conformance as conformance_module
import research_decision_engine.benchmarks.broader_oracle as oracle_module
import research_decision_engine.benchmarks.broader_projection as projection_module
import research_decision_engine.benchmarks.broader_smoke as smoke_module
import tests.test_broader_oracle_support as oracle_support_module
from research_decision_engine.benchmarks.broader_analysis import ProductionAnalysisResult
from research_decision_engine.benchmarks.broader_audits import (
    FixtureAuditDiagnostic,
    IntegrityAuditContext,
    IntegrityAuditResult,
    PreFinalizationAuthorization,
    evaluate_audit,
)
from research_decision_engine.benchmarks.broader_execution import ExecutorProvenanceError
from research_decision_engine.benchmarks.broader_oracle import (
    OracleConformanceResult,
    OracleError,
    OracleEvidenceBinding,
    OracleFixtureBinding,
    OracleFixtureEvidence,
    OracleFixtureResult,
    decision_key,
    transform_key,
)
from research_decision_engine.benchmarks.broader_protocol import (
    EXPECTED_ORACLE_DOMAIN_SHA256,
    canonical_json_bytes,
)
from research_decision_engine.benchmarks.broader_validation import (
    PytestValidationError,
    PytestValidationResult,
)


def _binding(tmp_path: Path, label: str) -> OracleFixtureBinding:
    identity = tmp_path.resolve().as_posix()
    return oracle_module._begin_oracle_fixture_binding(
        validation_run_identity=hashlib.sha256(
            f"validation:{identity}:{label}".encode()
        ).hexdigest(),
        evidence_bundle_identity=hashlib.sha256(f"bundle:{identity}:{label}".encode()).hexdigest(),
    )


def _fixture_partitions() -> tuple[
    tuple[str, tuple[tuple[str, ...], ...]],
    ...,
]:
    return (
        (
            "tiny",
            (
                decision_key(
                    world_id="h_adam_low",
                    seed=9000,
                    candidate_id="g00-adam-r1",
                    replication_id="decision-group-00-r0001",
                ),
            ),
        ),
    )


def _fixture_digest(
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


def _fixture_result(
    tmp_path: Path,
    label: str,
) -> tuple[OracleFixtureBinding, OracleFixtureResult]:
    binding = _binding(tmp_path, label)
    partitions = _fixture_partitions()
    result = oracle_module._execute_oracle_fixture(binding, partitions)
    oracle_module._validate_oracle_fixture_result(
        result,
        binding=binding,
        expected_key_count=1,
        expected_unique_key_count=1,
        expected_partition_counts=(("tiny", 1),),
        expected_sha256=_fixture_digest(partitions),
    )
    return binding, result


def _fixture_evidence(tmp_path: Path, label: str) -> OracleFixtureEvidence:
    binding = _binding(tmp_path, label)
    partitions = _fixture_partitions()
    return oracle_module._issue_oracle_conformance_fixture(
        binding,
        partitions,
        expected_key_count=1,
        expected_unique_key_count=1,
        expected_partition_counts=(("tiny", 1),),
        expected_sha256=_fixture_digest(partitions),
    )


def _audit_context(
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


def _fixture_audit_context(evidence: OracleFixtureEvidence) -> IntegrityAuditContext:
    return IntegrityAuditContext(
        runs=(),
        replay_runs=(),
        first_payload=b"[]\n",
        replay_payload=b"[]\n",
        historical_before=(),
        historical_after=(),
        oracle_fixture_result=evidence.result,
        oracle_fixture_binding=evidence.binding,
    )


def _forged_result() -> OracleConformanceResult:
    return cast(
        OracleConformanceResult,
        SimpleNamespace(
            execution_status="PASS",
            actual_key_count=117_952,
            actual_unique_key_count=117_952,
            actual_sha256=EXPECTED_ORACLE_DOMAIN_SHA256,
        ),
    )


def test_conformance_entry_points_require_keyword_only_oracle_evidence_before_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry_points = (
        conformance_module.build_production_fixture,
        conformance_module.build_conformance_payloads,
        conformance_module._build_audited_conformance_plan,
    )
    for entry_point in entry_points:
        signature = inspect.signature(entry_point)
        for name in ("oracle_conformance_result", "oracle_evidence_binding"):
            parameter = signature.parameters[name]
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
            assert parameter.default is inspect.Parameter.empty

    computation_reached = False

    def unexpected_computation(*args: object, **kwargs: object) -> object:
        nonlocal computation_reached
        del args, kwargs
        computation_reached = True
        raise AssertionError("Missing evidence reached bounded conformance computation.")

    monkeypatch.setattr(
        conformance_module,
        "_build_production_fixture_uncached",
        unexpected_computation,
    )
    with pytest.raises(TypeError):
        conformance_module.build_production_fixture()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        conformance_module.build_conformance_payloads(  # type: ignore[call-arg]
            tmp_path / "target"
        )
    with pytest.raises(TypeError):
        conformance_module._build_audited_conformance_plan()  # type: ignore[call-arg]
    assert not computation_reached


def test_conformance_module_has_no_oracle_execution_authority() -> None:
    namespace = vars(conformance_module)
    assert "_resolve_oracle_evidence" not in namespace
    assert "begin_oracle_evidence_binding" not in namespace
    assert "execute_oracle_conformance" not in namespace
    assert "secrets" not in namespace

    source = inspect.getsource(conformance_module)
    assert "begin_oracle_evidence_binding" not in source
    assert "execute_oracle_conformance" not in source
    assert "import secrets" not in source
    assert not hasattr(conformance_module, "_build_production_fixture_cached")
    assert not hasattr(conformance_module, "_build_diagnostic_conformance_fixture_cached")

    production_entry = inspect.getsource(conformance_module.build_production_fixture)
    computation = production_entry.index("_build_production_fixture_uncached(")
    validations = tuple(
        index
        for index in range(len(production_entry))
        if production_entry.startswith("_require_oracle_evidence(", index)
    )
    assert len(validations) == 2
    assert validations[0] < computation < validations[1]


def test_oracle_has_no_public_zero_argument_full_domain_authority() -> None:
    for name in (
        "oracle_conformance_digest",
        "assert_oracle_conformance",
        "oracle_conformance_partitions",
        "conformance_keys",
    ):
        assert not hasattr(oracle_module, name)
    assert not hasattr(oracle_module, "_execute_oracle_conformance_partitions")
    assert not hasattr(oracle_module, "_PRODUCTION_ISSUANCE_KEY")

    signature = inspect.signature(oracle_module.execute_oracle_conformance)
    assert tuple(signature.parameters) == ("binding",)
    assert signature.parameters["binding"].default is inspect.Parameter.empty
    source = inspect.getsource(oracle_module.execute_oracle_conformance)
    assert "_production_oracle_conformance_partitions()" in source
    assert "issuance_key" not in source
    assert "partitions" not in signature.parameters


def test_oracle_result_validators_recheck_authority_after_value_comparisons() -> None:
    for validator, authority_check in (
        (oracle_module._validate_expected_conformance, "_require_issued_result("),
        (
            oracle_module._validate_expected_fixture_conformance,
            "_require_issued_fixture_result(",
        ),
    ):
        source = inspect.getsource(validator)
        assert source.count(authority_check) == 2
        assert source.rindex(authority_check) > source.rindex("actual_sha256")


def test_test_support_has_no_implicit_production_oracle_route() -> None:
    support = oracle_support_module.ConformanceOracleSupport
    assert not hasattr(support, "issue")
    signature = inspect.signature(support.from_executed)
    for name in ("result", "binding"):
        parameter = signature.parameters[name]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty

    conftest_source = (Path(__file__).with_name("conftest.py")).read_text(encoding="utf-8")
    assert "--run-broader-production-oracle-audit" not in conftest_source
    assert "request.config.getoption(" not in conftest_source
    assert "begin_oracle_evidence_binding(" not in conftest_source
    assert "execute_oracle_conformance(" not in conftest_source

    production_start = conftest_source.index("def conformance_oracle_support(")
    production_end = conftest_source.index("\n\n@pytest.fixture", production_start)
    production_source = conftest_source[production_start:production_end]
    assert "pytest.skip(" in production_source

    fixture_start = conftest_source.index("def fixture_conformance_oracle_support(")
    fixture_end = conftest_source.index("\n\n@pytest.fixture", fixture_start)
    fixture_source = conftest_source[fixture_start:fixture_end]
    assert "FixtureConformanceOracleSupport.issue()" in fixture_source
    assert "yield support" in fixture_source
    assert "support.close()" in fixture_source

    fixture_issue_source = inspect.getsource(
        oracle_support_module.FixtureConformanceOracleSupport.issue
    )
    assert "_begin_oracle_fixture_binding(" in fixture_issue_source
    assert "_issue_oracle_conformance_fixture(" in fixture_issue_source
    assert "begin_oracle_evidence_binding(" not in fixture_issue_source
    assert "execute_oracle_conformance(" not in fixture_issue_source

    conftest_tree = ast.parse(conftest_source)
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "issue"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "ConformanceOracleSupport"
        for node in ast.walk(conftest_tree)
    )


def test_one_binding_allows_only_one_concurrent_fixture_execution(
    tmp_path: Path,
) -> None:
    binding = _binding(tmp_path, "concurrent-execution")
    started = threading.Event()
    release = threading.Event()

    def blocked_partitions() -> Iterator[tuple[str, tuple[tuple[str, ...], ...]]]:
        started.set()
        if not release.wait(timeout=5):
            raise AssertionError("Fixture execution was not released.")
        yield from _fixture_partitions()

    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(
            oracle_module._execute_oracle_fixture,
            binding,
            blocked_partitions(),
        )
        assert started.wait(timeout=5)
        with pytest.raises(OracleError, match="already claimed an execution attempt"):
            oracle_module._execute_oracle_fixture(binding, _fixture_partitions())
        release.set()
        result = first.result(timeout=5)

    oracle_module._validate_oracle_fixture_result(
        result,
        binding=binding,
        expected_key_count=1,
        expected_unique_key_count=1,
        expected_partition_counts=(("tiny", 1),),
        expected_sha256=_fixture_digest(_fixture_partitions()),
    )


def test_failed_fixture_execution_permanently_owns_its_binding(tmp_path: Path) -> None:
    binding = _binding(tmp_path, "failed-execution")

    def failed_keys() -> Iterator[tuple[str, ...]]:
        yield _fixture_partitions()[0][1][0]
        raise RuntimeError("deterministic fixture failure")

    result = oracle_module._execute_oracle_fixture(
        binding,
        (("tiny", failed_keys()),),
    )
    assert result.execution_status == "FAILED"
    assert result.actual_key_count == 1
    with pytest.raises(OracleError, match="already claimed an execution attempt"):
        oracle_module._execute_oracle_fixture(binding, _fixture_partitions())


def test_binding_revocation_after_claim_issues_no_partial_result_and_cannot_retry(
    tmp_path: Path,
) -> None:
    binding = _binding(tmp_path, "revoked-execution")
    started = threading.Event()
    release = threading.Event()

    def blocked_keys() -> Iterator[tuple[str, ...]]:
        started.set()
        if not release.wait(timeout=5):
            raise AssertionError("Fixture enumeration was not released.")
        yield _fixture_partitions()[0][1][0]

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            oracle_module._execute_oracle_fixture,
            binding,
            (("tiny", blocked_keys()),),
        )
        assert started.wait(timeout=5)
        oracle_module._close_oracle_fixture_binding(binding)
        release.set()
        with pytest.raises(OracleError, match="stale"):
            future.result(timeout=5)

    binding_record = oracle_module._ISSUED_ORACLE_FIXTURE_BINDINGS[id(binding)]
    assert binding_record.execution_claimed is True
    assert all(
        record.binding is not binding
        for record in oracle_module._ISSUED_ORACLE_FIXTURE_RESULTS.values()
    )
    with pytest.raises(OracleError, match="stale"):
        oracle_module._execute_oracle_fixture(binding, _fixture_partitions())


def test_evidence_generators_require_explicit_oracle_evidence_and_never_enumerate() -> None:
    for entry_point in (smoke_module.run_smoke, smoke_module.execute_bounded_validation_evidence):
        signature = inspect.signature(entry_point)
        for name in ("oracle_conformance_result", "oracle_evidence_binding"):
            parameter = signature.parameters[name]
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
            assert parameter.default is inspect.Parameter.empty
        source = inspect.getsource(entry_point)
        assert "execute_oracle_conformance(" not in source
        assert "begin_oracle_evidence_binding(" not in source


def test_smoke_owner_claim_precedes_use_and_only_terminal_owner_closes() -> None:
    begin_source = inspect.getsource(smoke_module.begin_smoke_evidence_binding)
    assert begin_source.index("_claim_smoke_evidence_owner(") < begin_source.index(
        "observe_pytest_validation_result("
    )
    for call in (
        "observe_pytest_validation_result(",
        "validate_pytest_validation_result(",
        "bind_pytest_validation_result_to_bundle(",
        "consume_pytest_validation_result(",
    ):
        call_start = begin_source.index(call)
        assert "owner_claim=owner.owner_claim" in begin_source[call_start:]

    run_source = inspect.getsource(smoke_module.run_smoke)
    assert run_source.index("_take_smoke_evidence_owner(") < run_source.index(
        "_validated_oracle_evidence("
    )
    close_start = run_source.index("close_oracle_evidence_binding(")
    assert "if owner is not None" in run_source[:close_start]
    orchestration_source = inspect.getsource(smoke_module.execute_bounded_validation_evidence)
    assert "close_oracle_evidence_binding(" not in orchestration_source
    assert "consume_pytest_validation_result(" not in orchestration_source


def test_a04_missing_cross_fixture_and_forged_evidence_fail_closed(
    tmp_path: Path,
) -> None:
    binding, fixture_result = _fixture_result(tmp_path, "a04-primary")
    other_binding = _binding(tmp_path, "a04-other")
    forged_binding = cast(OracleEvidenceBinding, SimpleNamespace())
    cases = (
        (_audit_context(None, None), "are required"),
        (_audit_context(None, cast(OracleEvidenceBinding, binding)), "are required"),
        (_audit_context(cast(OracleConformanceResult, fixture_result), None), "are required"),
        (
            _audit_context(
                cast(OracleConformanceResult, fixture_result),
                cast(OracleEvidenceBinding, binding),
            ),
            "exact issued binding",
        ),
        (
            _audit_context(
                cast(OracleConformanceResult, fixture_result),
                cast(OracleEvidenceBinding, other_binding),
            ),
            "exact issued binding",
        ),
        (_audit_context(_forged_result(), forged_binding), "exact issued binding"),
        (
            _audit_context(cast(OracleConformanceResult, fixture_result), forged_binding),
            "exact issued binding",
        ),
    )

    for context, expected_detail in cases:
        observation = evaluate_audit("A04-ORACLE-ISOLATION", context)
        assert observation.status == "FAIL"
        assert expected_detail in observation.detail


def test_conformance_entries_reject_invalid_evidence_before_bounded_computation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding, fixture_result = _fixture_result(tmp_path, "entry-primary")
    other_binding = _binding(tmp_path, "entry-other")
    computation_count = 0

    def unexpected_computation(
        *,
        oracle_conformance_result: OracleConformanceResult,
        oracle_evidence_binding: OracleEvidenceBinding,
    ) -> conformance_module.ProductionConformanceFixture:
        nonlocal computation_count
        del oracle_conformance_result, oracle_evidence_binding
        computation_count += 1
        raise AssertionError("Invalid evidence reached bounded conformance computation.")

    monkeypatch.setattr(
        conformance_module,
        "_build_production_fixture_uncached",
        unexpected_computation,
    )

    with pytest.raises(OracleError, match="exact issued binding"):
        conformance_module.build_production_fixture(
            oracle_conformance_result=cast(OracleConformanceResult, fixture_result),
            oracle_evidence_binding=cast(OracleEvidenceBinding, binding),
        )
    with pytest.raises(OracleError, match="exact issued binding"):
        conformance_module._build_audited_conformance_plan(
            oracle_conformance_result=cast(OracleConformanceResult, fixture_result),
            oracle_evidence_binding=cast(OracleEvidenceBinding, binding),
            fixture=cast(conformance_module.ProductionConformanceFixture, object()),
        )
    with pytest.raises(OracleError, match="exact issued binding"):
        conformance_module.build_conformance_payloads(
            tmp_path / "target",
            oracle_conformance_result=cast(OracleConformanceResult, fixture_result),
            oracle_evidence_binding=cast(OracleEvidenceBinding, binding),
            fixture=cast(conformance_module.ProductionConformanceFixture, object()),
        )
    with pytest.raises(OracleError, match="exact issued binding"):
        conformance_module.build_production_fixture(
            oracle_conformance_result=cast(OracleConformanceResult, fixture_result),
            oracle_evidence_binding=cast(OracleEvidenceBinding, other_binding),
        )
    with pytest.raises(OracleError, match="exact issued binding"):
        conformance_module.build_production_fixture(
            oracle_conformance_result=_forged_result(),
            oracle_evidence_binding=cast(OracleEvidenceBinding, binding),
        )
    assert computation_count == 0


def test_fixture_only_capability_is_exact_and_cannot_be_forged_or_promoted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = _fixture_evidence(tmp_path, "fixture-domain")
    sentinel = cast(conformance_module.DiagnosticConformanceFixture, object())
    computation_count = 0

    def bounded_computation(
        *,
        oracle_fixture_evidence: OracleFixtureEvidence,
    ) -> conformance_module.DiagnosticConformanceFixture:
        nonlocal computation_count
        assert oracle_fixture_evidence is evidence
        computation_count += 1
        return sentinel

    monkeypatch.setattr(
        conformance_module,
        "_build_diagnostic_conformance_fixture_uncached",
        bounded_computation,
    )
    assert (
        conformance_module._build_diagnostic_conformance_fixture(
            oracle_fixture_evidence=evidence,
        )
        is sentinel
    )
    assert (
        conformance_module._build_diagnostic_conformance_fixture(
            oracle_fixture_evidence=evidence,
        )
        is sentinel
    )
    assert computation_count == 2

    forged = object.__new__(OracleFixtureEvidence)
    object.__setattr__(forged, "result", evidence.result)
    object.__setattr__(forged, "binding", evidence.binding)
    object.__setattr__(forged, "fixture_identity", evidence.fixture_identity)
    with pytest.raises(OracleError, match="forged or stale"):
        conformance_module._build_diagnostic_conformance_fixture(
            oracle_fixture_evidence=forged,
        )
    assert computation_count == 2

    with pytest.raises(OracleError, match="exact issued binding"):
        conformance_module.build_production_fixture(
            oracle_conformance_result=cast(OracleConformanceResult, evidence.result),
            oracle_evidence_binding=cast(OracleEvidenceBinding, evidence.binding),
        )


def test_fixture_domain_has_no_production_audit_or_finalization_issuer() -> None:
    for name in (
        "_build_fixture_only_conformance_payloads",
        "_build_fixture_only_audited_conformance_plan",
    ):
        assert not hasattr(conformance_module, name)

    fixture_audit_source = inspect.getsource(audit_module._run_fixture_pre_finalization_audits)
    assert "_issue_pre_finalization_authorization" not in fixture_audit_source
    assert "PreFinalizationAuthorization" not in fixture_audit_source
    fixture_lifecycle_source = inspect.getsource(
        conformance_module._execute_fixture_audited_lifecycle
    )
    assert "execute_pre_finalization_audits" not in fixture_lifecycle_source
    assert "execute_finalization_audit" not in fixture_lifecycle_source
    assert "authorize_validation_finalization" not in fixture_lifecycle_source


def test_fixture_diagnostics_and_manual_pass_tuples_cannot_enter_authority_registries(
    tmp_path: Path,
    diagnostic_conformance_fixture: conformance_module.DiagnosticConformanceFixture,
) -> None:
    evidence = _fixture_evidence(tmp_path, "diagnostic-registry-separation")
    context = _fixture_audit_context(evidence)
    registry_sizes = (
        len(audit_module._ISSUED_PRE_FINALIZATION_AUTHORIZATIONS),
        len(audit_module._ISSUED_FINALIZATION_AUDIT_CERTIFICATES),
        len(audit_module._ISSUED_FINALIZATION_AUTHORIZATIONS),
        len(audit_module._CONSUMED_FINALIZATION_AUTHORIZATIONS),
    )

    with pytest.raises(ExecutorProvenanceError, match="A06 requires exact"):
        audit_module._run_fixture_pre_finalization_audits(
            context,
            oracle_fixture_evidence=evidence,
        )
    diagnostics = diagnostic_conformance_fixture.audits[:-1]
    final_diagnostic = diagnostic_conformance_fixture.audits[-1]
    assert all(type(item) is FixtureAuditDiagnostic for item in (*diagnostics, final_diagnostic))
    assert all(not item.authoritative for item in (*diagnostics, final_diagnostic))
    assert not hasattr(audit_module, "_issue_pre_finalization_authorization")
    with pytest.raises(ValueError, match="exact authoritative audit results"):
        projection_module.build_post_audit_payloads(
            (),
            cast(ProductionAnalysisResult, object()),
            cast(tuple[IntegrityAuditResult, ...], diagnostics),
            {},
        )

    manual_pass = tuple(
        IntegrityAuditResult(
            audit_id=item.audit_id,
            audit_order=item.audit_order,
            requirement=item.requirement,
            observed="PASS",
            status="PASS",
        )
        for item in diagnostics
    )
    for lookalike in (diagnostics, manual_pass):
        with pytest.raises(ValueError, match="issued A01-A15 authorization"):
            audit_module.execute_finalization_audit(
                context,
                cast(PreFinalizationAuthorization, lookalike),
            )

    assert registry_sizes == (
        len(audit_module._ISSUED_PRE_FINALIZATION_AUTHORIZATIONS),
        len(audit_module._ISSUED_FINALIZATION_AUDIT_CERTIFICATES),
        len(audit_module._ISSUED_FINALIZATION_AUTHORIZATIONS),
        len(audit_module._CONSUMED_FINALIZATION_AUTHORIZATIONS),
    )


def test_finalization_authority_call_graph_revalidates_exact_oracle_lineage() -> None:
    transitions = {
        audit_module.execute_pre_finalization_audits: {"_require_authoritative_oracle_context"},
        audit_module.execute_finalization_audit: {"_require_authoritative_oracle_context"},
        audit_module.seal_finalization_authorization: {
            "_require_authoritative_oracle_context",
            "_validate_finalization_certificate_record",
        },
        audit_module._validate_finalization_certificate_record: {
            "_require_authoritative_oracle_context"
        },
        audit_module._validate_finalization_certificate_binding: {
            "_validate_finalization_certificate_record"
        },
        audit_module.finalization_audit_results: {"_require_authoritative_oracle_context"},
        audit_module.consume_finalization_authorization: {"_require_authoritative_oracle_evidence"},
        audit_module._finalization_receipt_record: {"_require_authoritative_oracle_evidence"},
        audit_module.finalization_receipt_audit_results: {"_finalization_receipt_record"},
        audit_module.finalization_receipt_binding: {"_finalization_receipt_record"},
        audit_module.claimed_finalization_receipt_binding: {"_finalization_receipt_record"},
        audit_module.claim_finalization_receipt_writer: {"_finalization_receipt_record"},
        audit_module.publish_finalization_receipt_writer: {"_finalization_receipt_record"},
        audit_module.advance_finalization_receipt: {"_finalization_receipt_record"},
        audit_module.complete_finalization_receipt: {"_finalization_receipt_record"},
    }
    for transition, required_calls in transitions.items():
        tree = ast.parse(
            textwrap.dedent(inspect.getsource(cast(Callable[..., object], transition)))
        )
        call_names = {
            node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))
        }
        assert required_calls <= call_names

    pre_source = inspect.getsource(audit_module.execute_pre_finalization_audits)
    assert (
        pre_source.index("_run_selected_audits(")
        < pre_source.index("_require_authoritative_oracle_context(")
        < pre_source.index("PreFinalizationAuthorization(")
    )
    final_source = inspect.getsource(audit_module.execute_finalization_audit)
    assert (
        final_source.index("_expected_finalization_plan_binding(")
        < final_source.rindex("_require_authoritative_oracle_context(")
        < final_source.index("FinalizationAuditCertificate(")
    )
    seal_source = inspect.getsource(audit_module.seal_finalization_authorization)
    assert seal_source.rindex("_require_authoritative_oracle_context(") < seal_source.index(
        "FinalizationAuthorization("
    )
    consume_source = inspect.getsource(audit_module.consume_finalization_authorization)
    assert consume_source.index("_require_authoritative_oracle_evidence(") < consume_source.index(
        "ConsumedFinalizationAuthorization("
    )

    authorization_fields = audit_module._FinalizationAuthorizationRecord.__dataclass_fields__
    receipt_fields = audit_module._FinalizationReceiptRecord.__dataclass_fields__
    for record_fields in (authorization_fields, receipt_fields):
        assert "oracle_conformance_result" in record_fields
        assert "oracle_evidence_binding" in record_fields

    validator_source = inspect.getsource(audit_module._require_authoritative_oracle_evidence)
    assert "validate_oracle_conformance_result(" in validator_source
    assert "_validate_oracle_fixture" not in validator_source
    assert not issubclass(OracleFixtureResult, OracleConformanceResult)
    assert not issubclass(OracleFixtureBinding, OracleEvidenceBinding)


def test_report_attempt_without_smoke_owner_rejects_without_closing_binding(
    tmp_path: Path,
) -> None:
    evidence = _fixture_evidence(tmp_path, "fixture-report")

    with pytest.raises(PytestValidationError, match="exact active pytest/Oracle ownership claim"):
        smoke_module.run_smoke(
            tmp_path / "evidence",
            validation_result=cast(PytestValidationResult, object()),
            oracle_conformance_result=cast(OracleConformanceResult, evidence.result),
            oracle_evidence_binding=cast(OracleEvidenceBinding, evidence.binding),
        )
    assert not (tmp_path / "evidence").exists()
    assert oracle_module._validate_oracle_fixture_evidence(evidence) is evidence
    oracle_module._close_oracle_fixture_binding(evidence.binding)


def test_fixture_capability_is_repeatable_only_while_its_binding_is_active(
    tmp_path: Path,
) -> None:
    evidence = _fixture_evidence(tmp_path, "active-lifecycle")

    assert oracle_module._validate_oracle_fixture_evidence(evidence) is evidence
    assert oracle_module._validate_oracle_fixture_evidence(evidence) is evidence
    oracle_module._close_oracle_fixture_binding(evidence.binding)
    with pytest.raises(OracleError, match="stale"):
        oracle_module._validate_oracle_fixture_evidence(evidence)


def test_fixture_binding_rechecks_activity_after_identity_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = _fixture_evidence(tmp_path, "identity-observation-race")
    identity_observed = threading.Event()
    release_identity = threading.Event()
    current_identities = oracle_module._current_oracle_identities

    def blocked_current_identities() -> object:
        identity_observed.set()
        if not release_identity.wait(timeout=5):
            raise AssertionError("Oracle identity observation was not released.")
        return current_identities()

    monkeypatch.setattr(oracle_module, "_current_oracle_identities", blocked_current_identities)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            oracle_module._require_issued_fixture_binding,
            evidence.binding,
            require_active=True,
            require_current=True,
        )
        if not identity_observed.wait(timeout=5):
            release_identity.set()
            raise AssertionError("Fixture validation did not observe current identities.")
        oracle_module._close_oracle_fixture_binding(evidence.binding)
        release_identity.set()
        with pytest.raises(OracleError, match="stale"):
            future.result(timeout=5)


def test_fixture_result_validation_rechecks_after_terminal_identity_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding, result = _fixture_result(tmp_path, "terminal-validation-race")
    terminal_identity_observed = threading.Event()
    release_terminal_identity = threading.Event()
    current_identities = oracle_module._current_oracle_identities
    identity_observation_count = 0

    def blocked_terminal_identities() -> object:
        nonlocal identity_observation_count
        identity_observation_count += 1
        if identity_observation_count == 4:
            terminal_identity_observed.set()
            if not release_terminal_identity.wait(timeout=5):
                raise AssertionError("Terminal Oracle identity observation was not released.")
        return current_identities()

    monkeypatch.setattr(oracle_module, "_current_oracle_identities", blocked_terminal_identities)
    partitions = _fixture_partitions()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            oracle_module._validate_oracle_fixture_result,
            result,
            binding=binding,
            expected_key_count=1,
            expected_unique_key_count=1,
            expected_partition_counts=(("tiny", 1),),
            expected_sha256=_fixture_digest(partitions),
        )
        if not terminal_identity_observed.wait(timeout=5):
            release_terminal_identity.set()
            raise AssertionError("Fixture validation did not reach terminal identity observation.")
        oracle_module._close_oracle_fixture_binding(binding)
        release_terminal_identity.set()
        with pytest.raises(OracleError, match="stale"):
            future.result(timeout=5)
    assert identity_observation_count == 4


def test_fixture_build_rejects_concurrent_close_after_computation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = _fixture_evidence(tmp_path, "concurrent-close")
    started = threading.Event()
    release = threading.Event()
    sentinel = cast(conformance_module.DiagnosticConformanceFixture, object())

    def bounded_computation(
        *,
        oracle_fixture_evidence: OracleFixtureEvidence,
    ) -> conformance_module.DiagnosticConformanceFixture:
        assert oracle_fixture_evidence is evidence
        started.set()
        if not release.wait(timeout=5):
            raise AssertionError("Fixture computation was not released.")
        return sentinel

    monkeypatch.setattr(
        conformance_module,
        "_build_diagnostic_conformance_fixture_uncached",
        bounded_computation,
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            conformance_module._build_diagnostic_conformance_fixture,
            oracle_fixture_evidence=evidence,
        )
        assert started.wait(timeout=5)
        oracle_module._close_oracle_fixture_binding(evidence.binding)
        release.set()
        with pytest.raises(OracleError, match="stale"):
            future.result(timeout=5)
