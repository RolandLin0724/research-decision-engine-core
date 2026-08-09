from __future__ import annotations

import copy
import hashlib
import json
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

import research_decision_engine.benchmarks.broader_assembly as assembly_module
import research_decision_engine.benchmarks.broader_conformance as conformance_module
import research_decision_engine.benchmarks.broader_projection as projection_module
from research_decision_engine.benchmarks.broader_analysis import derive_provisional_analysis
from research_decision_engine.benchmarks.broader_artifact_graph import (
    FROZEN_ARTIFACT_PROFILE,
    decode_and_validate_artifacts,
    decode_and_validate_audited_artifacts,
)
from research_decision_engine.benchmarks.broader_artifacts import (
    ArtifactValidationError,
    artifact_contracts,
)
from research_decision_engine.benchmarks.broader_assembly import (
    CanonicalFinalizationPlan,
    assemble_audited_scientific_artifacts,
    authorize_canonical_finalization,
    authorize_validation_finalization,
    finalize_validation_artifacts,
)
from research_decision_engine.benchmarks.broader_audits import (
    HISTORICAL_ROOTS,
    ConsumedFinalizationAuthorization,
    FinalizationAuthorization,
    IntegrityAuditContext,
    _validate_finalization_certificate_binding,
    advance_finalization_receipt,
    claim_finalization_receipt_writer,
    consume_finalization_authorization,
    execute_finalization_audit,
    execute_pre_finalization_audits,
    finalization_plan_binding_sha256,
    finalization_receipt_audit_results,
    finalization_receipt_binding,
    historical_hash_map,
    invalidate_finalization_audit_certificate,
    invalidate_finalization_receipt,
    seal_finalization_authorization,
)
from research_decision_engine.benchmarks.broader_conformance import (
    CONFORMANCE_PROFILE,
    DiagnosticConformanceFixture,
)
from research_decision_engine.benchmarks.broader_execution import (
    ActualExecutorAttestation,
    execute_deterministic_map,
    executor_provenance_payload,
)
from research_decision_engine.benchmarks.broader_projection import (
    derive_manifest_scientific_payload,
    derive_recommendation_scientific_payload,
    recommendation_scientific_payload_identity,
)
from research_decision_engine.benchmarks.broader_protocol import (
    canonical_json_bytes,
    load_protocol_snapshot,
    repository_root,
)
from tests.test_broader_oracle_support import ConformanceOracleSupport


def _authorized(
    target: Path,
    conformance_oracle_support: ConformanceOracleSupport,
) -> tuple[
    CanonicalFinalizationPlan,
    assembly_module.AssemblyOperationalProvenance,
    FinalizationAuthorization,
]:
    return conformance_oracle_support.payloads(target)


def _finalize(
    target: Path,
    plan: CanonicalFinalizationPlan,
    operational: assembly_module.AssemblyOperationalProvenance,
    authorization: FinalizationAuthorization,
) -> dict[str, bytes]:
    return finalize_validation_artifacts(
        target,
        plan,
        operational,
        authorization,
        profile=CONFORMANCE_PROFILE,
    )


def _consumed(
    target: Path,
    conformance_oracle_support: ConformanceOracleSupport,
) -> tuple[
    CanonicalFinalizationPlan,
    assembly_module.AssemblyOperationalProvenance,
    ConsumedFinalizationAuthorization,
    dict[str, bytes],
]:
    plan, operational, authorization = _authorized(target, conformance_oracle_support)
    binding = assembly_module._finalization_binding(
        target,
        plan,
        operational,
        artifact_contracts(),
        profile=CONFORMANCE_PROFILE,
        finalization_scope=assembly_module.VALIDATION_FINALIZATION_SCOPE,
    )
    receipt = consume_finalization_authorization(authorization, binding)
    audits = finalization_receipt_audit_results(
        receipt,
        expected_phase="authorization_consumed",
    )
    artifacts = assemble_audited_scientific_artifacts(
        plan,
        operational,
        audits,
        profile=CONFORMANCE_PROFILE,
    )
    return plan, operational, receipt, artifacts


def test_manifest_reopens_promoted_bytes_and_recommendation_is_created_last(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "canonical"
    plan, operational, authorization = _authorized(target, conformance_oracle_support)
    expected_names = tuple(item.filename for item in artifact_contracts())
    original_manifest = derive_manifest_scientific_payload
    original_recommendation = derive_recommendation_scientific_payload
    original_recommendation_fields = projection_module._recommendation_fields
    original_read = assembly_module._read_exact_artifacts
    original_atomic = cast(Any, assembly_module._atomic_create)
    original_hashes = assembly_module._promoted_artifact_hashes
    original_identity = recommendation_scientific_payload_identity
    original_verify = cast(
        Any,
        assembly_module._verify_constructed_recommendation_commitment,
    )
    observed: list[str] = []
    stage_events: list[str] = []
    canonical_reads: list[tuple[str, ...]] = []
    manifest_read_count = 0
    recommendation_field_materializations: list[str] = []
    original_decision = plan.post_audit.gate_evaluations["recommendation"]

    def recording_read(
        directory: Path,
        names: tuple[str, ...],
        *,
        transient_paths: tuple[Path, ...] = (),
    ) -> dict[str, bytes]:
        nonlocal manifest_read_count
        result = original_read(directory, names, transient_paths=transient_paths)
        if directory == target:
            canonical_reads.append(names)
            if names == expected_names[:11] and "A" not in stage_events:
                stage_events.append("A")
            if names == expected_names[:12]:
                manifest_read_count += 1
                if manifest_read_count == 1:
                    stage_events.append("D")
                elif manifest_read_count == 2:
                    stage_events.append("E")
        return result

    def recording_hashes(
        graph: object,
    ) -> tuple[dict[str, str], dict[str, str]]:
        result = original_hashes(cast(Any, graph))
        stage_events.append("B")
        return result

    def recording_identity(gate: dict[str, object]) -> str:
        result = original_identity(gate)
        stage_events.append("C")
        return result

    def recording_atomic(
        directory: Path,
        filename: str,
        content: bytes,
        **kwargs: object,
    ) -> None:
        original_atomic(directory, filename, content, **kwargs)
        if filename == "recommendation.json":
            stage_events.append("H")

    def recording_verify(*args: object, **kwargs: object) -> None:
        original_verify(*args, **kwargs)
        stage_events.append("G")

    def manifest_from_disk(scientific: dict[str, object]) -> dict[str, object]:
        observed.append("manifest")
        assert target.is_dir()
        assert all((target / name).is_file() for name in expected_names[:11])
        assert not (target / "run_manifest.json").exists()
        assert not (target / "recommendation.json").exists()
        assert tuple(scientific) == expected_names[:11]
        assert expected_names[:11] in canonical_reads
        plan.post_audit.gate_evaluations["recommendation"] = (
            "C_NO_STABLE_ACTIONABLE_MECHANISM"
            if original_decision != "C_NO_STABLE_ACTIONABLE_MECHANISM"
            else "A_RETAIN_CURRENT_CONTROLLER"
        )
        return original_manifest(scientific)

    def recommendation_after_manifest(gate: dict[str, object]) -> dict[str, object]:
        observed.append("recommendation")
        assert all((target / name).is_file() for name in expected_names[:12])
        assert not (target / "recommendation.json").exists()
        result = original_recommendation(gate)
        stage_events.append("F")
        return result

    def recommendation_fields_after_manifest(gate: dict[str, object]) -> dict[str, object]:
        assert (target / "run_manifest.json").is_file()
        recommendation_field_materializations.append("recommendation_fields")
        return original_recommendation_fields(gate)

    monkeypatch.setattr(assembly_module, "_read_exact_artifacts", recording_read)
    monkeypatch.setattr(assembly_module, "_promoted_artifact_hashes", recording_hashes)
    monkeypatch.setattr(
        assembly_module,
        "recommendation_scientific_payload_identity",
        recording_identity,
    )
    monkeypatch.setattr(assembly_module, "_atomic_create", recording_atomic)
    monkeypatch.setattr(
        assembly_module,
        "_verify_constructed_recommendation_commitment",
        recording_verify,
    )
    monkeypatch.setattr(
        assembly_module,
        "derive_manifest_scientific_payload",
        manifest_from_disk,
    )
    monkeypatch.setattr(
        assembly_module,
        "derive_recommendation_scientific_payload",
        recommendation_after_manifest,
    )
    monkeypatch.setattr(
        projection_module,
        "_recommendation_fields",
        recommendation_fields_after_manifest,
    )

    persisted = _finalize(target, plan, operational, authorization)
    graph = decode_and_validate_artifacts(
        persisted,
        artifact_contracts(),
        profile=CONFORMANCE_PROFILE,
    )

    assert observed == ["manifest", "recommendation"]
    assert stage_events == list("ABCDEFGH")
    assert recommendation_field_materializations == ["recommendation_fields"]
    recommendation = cast(dict[str, object], graph.artifact("recommendation.json").scientific)
    committed_identity = cast(
        str,
        graph.artifact("run_manifest.json").operational["recommendation_scientific_payload_sha256"],
    )
    assert (
        committed_identity
        == hashlib.sha256(canonical_json_bytes(recommendation, final_lf=True)).hexdigest()
    )
    assert recommendation["recommendation"] == original_decision
    assert plan.post_audit.gate_evaluations["recommendation"] != original_decision


@pytest.mark.parametrize(
    ("stage", "expected_files"),
    (
        ("A_reopen_promoted", 11),
        ("B_derive_manifest_hashes", 11),
        ("C_commit_recommendation", 11),
        ("D_validate_manifest", 12),
        ("E_reopen_manifest", 12),
        ("F_construct_recommendation", 12),
        ("G_verify_recommendation_hash", 12),
        ("H_persist_recommendation", 12),
        ("I_reopen_recommendation", 13),
    ),
)
@pytest.mark.lifecycle_interruption
def test_finalization_interruption_never_precomputes_later_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    expected_files: int,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / stage / "canonical"
    plan, operational, authorization = _authorized(target, conformance_oracle_support)
    if stage == "A_reopen_promoted":
        original_read = assembly_module._read_exact_artifacts

        def fail_reopen(
            directory: Path,
            names: tuple[str, ...],
            *,
            transient_paths: tuple[Path, ...] = (),
        ) -> dict[str, bytes]:
            if directory == target and len(names) == 11:
                raise ArtifactValidationError(f"injected {stage}")
            return original_read(directory, names, transient_paths=transient_paths)

        monkeypatch.setattr(assembly_module, "_read_exact_artifacts", fail_reopen)
    elif stage == "B_derive_manifest_hashes":
        monkeypatch.setattr(
            assembly_module,
            "_promoted_artifact_hashes",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                ArtifactValidationError("injected B manifest hashes")
            ),
        )
    elif stage == "C_commit_recommendation":
        monkeypatch.setattr(
            assembly_module,
            "recommendation_scientific_payload_identity",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                ArtifactValidationError("injected C commitment")
            ),
        )
    elif stage in {"D_validate_manifest", "E_reopen_manifest"}:
        original_read = assembly_module._read_exact_artifacts
        manifest_reads = 0

        def fail_manifest_read(
            directory: Path,
            names: tuple[str, ...],
            *,
            transient_paths: tuple[Path, ...] = (),
        ) -> dict[str, bytes]:
            nonlocal manifest_reads
            if directory == target and len(names) == 12:
                manifest_reads += 1
            blocked_read = 1 if stage.startswith("D") else 2
            if manifest_reads == blocked_read:
                raise ArtifactValidationError(f"injected {stage}")
            return original_read(directory, names, transient_paths=transient_paths)

        monkeypatch.setattr(assembly_module, "_read_exact_artifacts", fail_manifest_read)
    elif stage == "F_construct_recommendation":
        monkeypatch.setattr(
            assembly_module,
            "derive_recommendation_scientific_payload",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                ArtifactValidationError("injected F recommendation")
            ),
        )
    elif stage == "G_verify_recommendation_hash":
        monkeypatch.setattr(
            assembly_module,
            "_verify_constructed_recommendation_commitment",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                ArtifactValidationError("injected G recommendation hash")
            ),
        )
    elif stage == "H_persist_recommendation":
        original_atomic = cast(Any, assembly_module._atomic_create)

        def fail_recommendation_persistence(
            directory: Path,
            filename: str,
            content: bytes,
            **kwargs: object,
        ) -> None:
            if filename == "recommendation.json":
                raise ArtifactValidationError("injected H recommendation persistence")
            original_atomic(directory, filename, content, **kwargs)

        monkeypatch.setattr(
            assembly_module,
            "_atomic_create",
            fail_recommendation_persistence,
        )
    else:
        original_read = assembly_module._read_exact_artifacts

        def fail_final_reopen(
            directory: Path,
            names: tuple[str, ...],
            *,
            transient_paths: tuple[Path, ...] = (),
        ) -> dict[str, bytes]:
            if directory == target and len(names) == 13:
                raise ArtifactValidationError("injected I recommendation reopen")
            return original_read(directory, names, transient_paths=transient_paths)

        monkeypatch.setattr(assembly_module, "_read_exact_artifacts", fail_final_reopen)

    with pytest.raises((ArtifactValidationError, OSError), match="injected"):
        _finalize(target, plan, operational, authorization)

    observed_files = {item.name for item in target.iterdir()} if target.exists() else set()
    assert len(observed_files) == expected_files
    assert ("run_manifest.json" in observed_files) is (expected_files >= 12)
    assert ("recommendation.json" in observed_files) is (expected_files == 13)
    if expected_files == 13:
        persisted_before_retry = {
            path.name: path.read_bytes() for path in target.iterdir() if path.is_file()
        }
        monkeypatch.setattr(assembly_module, "_read_exact_artifacts", original_read)
        with pytest.raises(
            ValueError,
            match="forged, stale, copied, or already consumed",
        ):
            _finalize(target, plan, operational, authorization)
        assert {
            path.name: path.read_bytes() for path in target.iterdir() if path.is_file()
        } == persisted_before_retry
        retry_plan, retry_operational, retry_authorization = _authorized(
            target,
            conformance_oracle_support,
        )
        with pytest.raises(
            assembly_module.CanonicalCreateOnceError,
            match=assembly_module.CANONICAL_CREATE_ONCE_ERROR,
        ):
            _finalize(target, retry_plan, retry_operational, retry_authorization)
        assert {
            path.name: path.read_bytes() for path in target.iterdir() if path.is_file()
        } == persisted_before_retry


def test_authorization_is_nonconstructible_noncopyable_and_nonserializable(
    tmp_path: Path,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "canonical"
    plan, operational, authorization = _authorized(target, conformance_oracle_support)

    with pytest.raises(TypeError, match="issued only"):
        FinalizationAuthorization()
    with pytest.raises(TypeError, match="cannot be subclassed"):

        class ForgedAuthorization(FinalizationAuthorization):
            pass

    with pytest.raises(TypeError, match="cannot be copied"):
        copy.copy(authorization)
    with pytest.raises(TypeError, match="cannot be deep-copied"):
        copy.deepcopy(authorization)
    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(authorization)

    _finalize(target, plan, operational, authorization)


@pytest.mark.parametrize("attack", ("none", "lookalike"))
def test_forged_authorization_fails_at_identity_validator_before_writes(
    tmp_path: Path,
    attack: str,
    diagnostic_conformance_fixture: DiagnosticConformanceFixture,
) -> None:
    target = tmp_path / attack / "canonical"
    fixture = diagnostic_conformance_fixture
    plan = fixture.finalization_plan
    operational = fixture.operational

    class Lookalike:
        pass

    forged = None if attack == "none" else Lookalike()
    with pytest.raises(ValueError, match="exact issued capability"):
        _finalize(
            target,
            plan,
            operational,
            cast(FinalizationAuthorization, forged),
        )
    assert not target.exists()


def test_authorization_is_single_use_after_success(
    tmp_path: Path,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "canonical"
    plan, operational, authorization = _authorized(target, conformance_oracle_support)
    _finalize(target, plan, operational, authorization)

    second = tmp_path / "second"
    with pytest.raises(ValueError, match="forged, stale, copied, or already consumed"):
        _finalize(second, plan, operational, authorization)
    assert not second.exists()


def test_authorization_is_single_use_after_failed_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "canonical"
    plan, operational, authorization = _authorized(target, conformance_oracle_support)
    original = assembly_module._promote_scientific_artifacts
    monkeypatch.setattr(
        assembly_module,
        "_promote_scientific_artifacts",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ArtifactValidationError("injected consumed failure")
        ),
    )
    with pytest.raises(ArtifactValidationError, match="injected consumed failure"):
        _finalize(target, plan, operational, authorization)
    monkeypatch.setattr(assembly_module, "_promote_scientific_artifacts", original)

    with pytest.raises(ValueError, match="forged, stale, copied, or already consumed"):
        _finalize(target, plan, operational, authorization)
    assert not target.exists()


@pytest.mark.parametrize(
    "attack",
    (
        "output_directory",
        "operational_provenance",
        "implementation_hash",
        "source_design_hash",
        "scientific_payload",
        "audit_claims",
        "decision",
    ),
)
def test_authorization_is_bound_to_exact_context_and_consumed_on_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    bound_target = tmp_path / attack / "bound"
    plan, operational, authorization = _authorized(
        bound_target,
        conformance_oracle_support,
    )
    target = bound_target
    attempted_plan = plan
    attempted_operational = operational
    if attack == "output_directory":
        target = tmp_path / attack / "other"
    elif attack == "operational_provenance":
        attempted_operational = replace(operational, machine={"fixture": "changed"})
    elif attack == "implementation_hash":
        attempted_operational = replace(operational, implementation_tree_sha256="3" * 64)
    elif attack == "source_design_hash":
        snapshot = load_protocol_snapshot()
        monkeypatch.setattr(
            assembly_module,
            "load_protocol_snapshot",
            lambda: replace(snapshot, source_design_sha256="f" * 64),
        )
    else:
        post_audit = copy.deepcopy(plan.post_audit)
        if attack == "scientific_payload":
            post_audit.gate_evaluations["evaluation_id"] = "broader-replication/changed"
        elif attack == "audit_claims":
            post_audit.audit_results["all_passed"] = False
        else:
            current = post_audit.gate_evaluations["recommendation"]
            post_audit.gate_evaluations["recommendation"] = (
                "C_NO_STABLE_ACTIONABLE_MECHANISM"
                if current != "C_NO_STABLE_ACTIONABLE_MECHANISM"
                else "A_RETAIN_CURRENT_CONTROLLER"
            )
        attempted_plan = replace(plan, post_audit=post_audit)

    with pytest.raises(ValueError, match="context does not match"):
        _finalize(target, attempted_plan, attempted_operational, authorization)
    assert not target.exists()

    with pytest.raises(ValueError, match="forged, stale, copied, or already consumed"):
        _finalize(bound_target, plan, operational, authorization)
    assert not bound_target.exists()


def test_wrong_lifecycle_phase_consumes_authorization_before_writes(
    tmp_path: Path,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "canonical"
    plan, operational, authorization = _authorized(target, conformance_oracle_support)
    binding = assembly_module._finalization_binding(
        target,
        plan,
        operational,
        artifact_contracts(),
        profile=CONFORMANCE_PROFILE,
        finalization_scope=assembly_module.VALIDATION_FINALIZATION_SCOPE,
    )
    binding["lifecycle_phase"] = "manifest_persisted"

    with pytest.raises(ValueError, match="context does not match"):
        consume_finalization_authorization(authorization, binding)
    assert not target.exists()
    with pytest.raises(ValueError, match="forged, stale, copied, or already consumed"):
        _finalize(target, plan, operational, authorization)


def test_direct_scientific_writer_rejects_missing_and_forged_receipts_before_writes(
    tmp_path: Path,
    diagnostic_conformance_fixture: DiagnosticConformanceFixture,
) -> None:
    fixture = diagnostic_conformance_fixture
    artifacts = assembly_module._assemble_audited_artifact_bytes(
        fixture.finalization_plan,
        fixture.operational,
        artifact_contracts(),
        CONFORMANCE_PROFILE,
    )
    for index, forged in enumerate((None, object())):
        target = tmp_path / f"forged-{index}" / "canonical"
        with pytest.raises(ValueError, match="exact consumed receipt"):
            assembly_module._promote_scientific_artifacts(
                target,
                artifacts,
                artifact_contracts()[:11],
                CONFORMANCE_PROFILE,
                receipt=cast(ConsumedFinalizationAuthorization, forged),
            )
        assert not target.exists()


@pytest.mark.writer_authorization
def test_actual_lowest_directory_writer_rejects_receipt_mutations_before_publish(
    tmp_path: Path,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "bound" / "canonical"
    _, _, receipt, artifacts = _consumed(target, conformance_oracle_support)
    staging = tmp_path / "empty-stage"
    staging.mkdir()
    contracts = artifact_contracts()[:11]
    try:
        for forged in (None, object()):
            with pytest.raises(ValueError, match="exact consumed receipt"):
                assembly_module._publish_claimed_canonical_entry(
                    target,
                    staging,
                    target,
                    receipt=cast(ConsumedFinalizationAuthorization, forged),
                    expected_phase="authorization_consumed",
                    contracts=contracts,
                    profile=CONFORMANCE_PROFILE,
                    expected_artifacts=artifacts,
                )
            assert not target.exists()
        with pytest.raises(ValueError, match="not exclusively claimed"):
            assembly_module._publish_claimed_canonical_entry(
                target,
                staging,
                target,
                receipt=receipt,
                expected_phase="authorization_consumed",
                contracts=contracts,
                profile=CONFORMANCE_PROFILE,
                expected_artifacts=artifacts,
            )
        assert not target.exists()

        claim_finalization_receipt_writer(receipt, expected_phase="authorization_consumed")
        other = tmp_path / "other" / "canonical"
        with pytest.raises(ArtifactValidationError, match="target differs"):
            assembly_module._publish_claimed_canonical_entry(
                other,
                staging,
                other,
                receipt=receipt,
                expected_phase="authorization_consumed",
                contracts=contracts,
                profile=CONFORMANCE_PROFILE,
                expected_artifacts=artifacts,
            )
        assert not other.exists()
    finally:
        invalidate_finalization_receipt(receipt)


def test_direct_scientific_writer_is_bound_to_directory_and_single_use(
    tmp_path: Path,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "bound" / "canonical"
    _, _, receipt, artifacts = _consumed(target, conformance_oracle_support)
    other = tmp_path / "other" / "canonical"
    try:
        with pytest.raises(ArtifactValidationError, match="target differs"):
            assembly_module._promote_scientific_artifacts(
                other,
                artifacts,
                artifact_contracts()[:11],
                CONFORMANCE_PROFILE,
                receipt=receipt,
            )
        assert not other.exists()

        assembly_module._promote_scientific_artifacts(
            target,
            artifacts,
            artifact_contracts()[:11],
            CONFORMANCE_PROFILE,
            receipt=receipt,
        )
        with pytest.raises(ValueError, match="stale or already claimed"):
            assembly_module._promote_scientific_artifacts(
                target,
                artifacts,
                artifact_contracts()[:11],
                CONFORMANCE_PROFILE,
                receipt=receipt,
            )
    finally:
        invalidate_finalization_receipt(receipt)


@pytest.mark.writer_authorization
def test_receipt_writer_claim_is_thread_atomic(
    tmp_path: Path,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "claim-race" / "canonical"
    _, _, receipt, _ = _consumed(target, conformance_oracle_support)
    barrier = threading.Barrier(2)

    def claim() -> str:
        barrier.wait(timeout=30)
        try:
            claim_finalization_receipt_writer(
                receipt,
                expected_phase="authorization_consumed",
            )
        except ValueError as error:
            return str(error)
        return "SUCCESS"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(executor.map(lambda _: claim(), range(2)))
        assert results.count("SUCCESS") == 1
        assert results.count("Finalization receipt writer phase is stale or already claimed.") == 1
        assert not target.exists()
    finally:
        invalidate_finalization_receipt(receipt)


@pytest.mark.writer_authorization
def test_concurrent_authorized_directory_publish_is_atomic_and_no_clobber(
    tmp_path: Path,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "race" / "canonical"
    _, _, first_receipt, first_artifacts = _consumed(target, conformance_oracle_support)
    _, _, second_receipt, second_artifacts = _consumed(target, conformance_oracle_support)
    barrier = threading.Barrier(2)

    def publish(
        receipt_and_artifacts: tuple[ConsumedFinalizationAuthorization, dict[str, bytes]],
    ) -> tuple[str, str]:
        receipt, artifacts = receipt_and_artifacts
        barrier.wait(timeout=30)
        try:
            assembly_module._promote_scientific_artifacts(
                target,
                artifacts,
                artifact_contracts()[:11],
                CONFORMANCE_PROFILE,
                receipt=receipt,
            )
        except assembly_module.CanonicalCreateOnceError as error:
            return error.error_code, str(error)
        return "SUCCESS", ""

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(
                executor.map(
                    publish,
                    (
                        (first_receipt, first_artifacts),
                        (second_receipt, second_artifacts),
                    ),
                )
            )
        assert sorted(code for code, _ in results) == [
            assembly_module.CANONICAL_CREATE_ONCE_ERROR,
            "SUCCESS",
        ]
        failure = next(message for code, message in results if code != "SUCCESS")
        assert failure.startswith(f"{assembly_module.CANONICAL_CREATE_ONCE_ERROR}:")
        published = assembly_module._read_exact_artifacts(
            target,
            tuple(contract.filename for contract in artifact_contracts()[:11]),
        )
        assert published in (first_artifacts, second_artifacts)
        published_snapshot = dict(published)
        winner = first_receipt if results[0][0] == "SUCCESS" else second_receipt
        loser = second_receipt if winner is first_receipt else first_receipt
        advance_finalization_receipt(
            winner,
            expected_phase="authorization_consumed",
            next_phase="scientific_artifacts_promoted",
        )
        with pytest.raises(ValueError, match="before publication"):
            advance_finalization_receipt(
                loser,
                expected_phase="authorization_consumed",
                next_phase="scientific_artifacts_promoted",
            )
        with pytest.raises(ValueError, match="not 'authorization_consumed'"):
            assembly_module._promote_scientific_artifacts(
                target,
                first_artifacts if winner is first_receipt else second_artifacts,
                artifact_contracts()[:11],
                CONFORMANCE_PROFILE,
                receipt=winner,
            )
        with pytest.raises(ValueError, match="stale or already claimed"):
            assembly_module._promote_scientific_artifacts(
                target,
                second_artifacts if loser is second_receipt else first_artifacts,
                artifact_contracts()[:11],
                CONFORMANCE_PROFILE,
                receipt=loser,
            )
        assert (
            assembly_module._read_exact_artifacts(
                target,
                tuple(contract.filename for contract in artifact_contracts()[:11]),
            )
            == published_snapshot
        )
        assert not tuple(target.parent.glob(".canonical.artifacts-1-11.*.incomplete"))
        assert all(path.is_file() and not path.is_symlink() for path in target.iterdir())
    finally:
        invalidate_finalization_receipt(first_receipt)
        invalidate_finalization_receipt(second_receipt)


def test_scientific_promotion_reopens_exact_staged_bytes_before_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "canonical"
    _, _, receipt, artifacts = _consumed(target, conformance_oracle_support)
    original_write = Path.write_bytes

    def mutate_one_staged_file(path: Path, content: bytes) -> int:
        if (
            path.parent.name.startswith(".canonical.artifacts-1-11.")
            and path.parent.name.endswith(".incomplete")
            and path.name == "protocol_snapshot.json"
        ):
            content += b" "
        return original_write(path, content)

    monkeypatch.setattr(Path, "write_bytes", mutate_one_staged_file)
    try:
        with pytest.raises(ArtifactValidationError, match="Reopened staged scientific bytes"):
            assembly_module._promote_scientific_artifacts(
                target,
                artifacts,
                artifact_contracts()[:11],
                CONFORMANCE_PROFILE,
                receipt=receipt,
            )
        assert not target.exists()
        assert not tuple(tmp_path.glob(".canonical.artifacts-1-11.*.incomplete"))
    finally:
        invalidate_finalization_receipt(receipt)


def test_consumed_receipt_cannot_be_copied_before_direct_writer_use(
    tmp_path: Path,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "canonical"
    _, _, receipt, _ = _consumed(target, conformance_oracle_support)
    try:
        with pytest.raises(TypeError, match="cannot be copied"):
            copy.copy(receipt)
        with pytest.raises(TypeError, match="cannot be deep-copied"):
            copy.deepcopy(receipt)
        assert not target.exists()
    finally:
        invalidate_finalization_receipt(receipt)


@pytest.mark.actual_state_provenance
def test_authorization_rejects_synthetic_hashes_and_caller_created_clean_state(
    tmp_path: Path,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    plan, operational, certificate = conformance_oracle_support.audited_plan()
    attempts = (
        (
            replace(operational, implementation_tree_sha256="1" * 64),
            "Caller operational provenance implementation_tree_sha256 differs from actual state.",
        ),
        (
            replace(operational, implementation_diff_sha256="2" * 64),
            "Caller operational provenance implementation_diff_sha256 differs from actual state.",
        ),
        (
            replace(
                operational,
                implementation_tree_clean=not operational.implementation_tree_clean,
            ),
            "Caller operational provenance implementation_tree_clean differs from actual state.",
        ),
        (
            replace(operational, started_at="caller invented"),
            "Caller operational provenance started_at is not canonical.",
        ),
        (
            replace(
                operational,
                started_at="2030-01-01T00:00:00.000000Z",
                completed_at="2029-01-01T00:00:00.000000Z",
            ),
            "Caller operational completion precedes its start.",
        ),
        (
            replace(
                operational,
                started_at="2000-01-01T00:00:00.000000Z",
                completed_at="2000-01-01T00:00:00.000000Z",
            ),
            "Operational provenance was not issued by actual-state reconstruction.",
        ),
    )
    try:
        for index, (attempted, expected_message) in enumerate(attempts):
            target = tmp_path / f"attempt-{index}"
            with pytest.raises(ArtifactValidationError) as captured:
                authorize_validation_finalization(
                    target,
                    plan,
                    attempted,
                    certificate,
                    profile=CONFORMANCE_PROFILE,
                )
            assert type(captured.value).__name__ == "ArtifactValidationError"
            assert str(captured.value) == expected_message
            assert not target.exists()

        original_tree_sha256 = operational.implementation_tree_sha256
        object.__setattr__(operational, "implementation_tree_sha256", "3" * 64)
        mutated_target = tmp_path / "mutated-issued-provenance"
        try:
            with pytest.raises(ArtifactValidationError) as captured_mutation:
                authorize_validation_finalization(
                    mutated_target,
                    plan,
                    operational,
                    certificate,
                    profile=CONFORMANCE_PROFILE,
                )
            assert type(captured_mutation.value).__name__ == "ArtifactValidationError"
            assert str(captured_mutation.value) == (
                "Operational provenance differs from the exact bytes issued by "
                "actual-state reconstruction."
            )
            assert not mutated_target.exists()
        finally:
            object.__setattr__(
                operational,
                "implementation_tree_sha256",
                original_tree_sha256,
            )
    finally:
        invalidate_finalization_audit_certificate(certificate)


@pytest.mark.actual_state_provenance
@pytest.mark.parametrize(
    ("attack", "base_configuration", "changed_configuration"),
    (
        (
            "worker_count",
            (1, "thread_pool", "input_order"),
            (2, "thread_pool", "input_order"),
        ),
        (
            "worker_mode",
            (1, "serial", "input_order"),
            (1, "thread_pool", "input_order"),
        ),
        (
            "worker_order",
            (2, "thread_pool", "input_order"),
            (2, "thread_pool", "completion_order"),
        ),
    ),
)
def test_actual_executor_mismatch_reaches_operational_provenance_guard(
    tmp_path: Path,
    attack: str,
    base_configuration: tuple[int, str, str],
    changed_configuration: tuple[int, str, str],
) -> None:
    jobs = tuple(range(-8, 0))
    base_results, base_attestation = execute_deterministic_map(
        abs,
        jobs,
        worker_count=base_configuration[0],
        executor_kind=cast(Any, base_configuration[1]),
        result_order=cast(Any, base_configuration[2]),
    )
    changed_results, changed_attestation = execute_deterministic_map(
        abs,
        jobs,
        worker_count=changed_configuration[0],
        executor_kind=cast(Any, changed_configuration[1]),
        result_order=cast(Any, changed_configuration[2]),
    )
    assert sorted(base_results) == sorted(changed_results)
    base_payload = executor_provenance_payload(base_attestation)
    changed_payload = executor_provenance_payload(changed_attestation)
    payload_field = {
        "worker_count": "worker_count",
        "worker_mode": "worker_executor_kind",
        "worker_order": "worker_order",
    }[attack]
    assert base_payload[payload_field] != changed_payload[payload_field]
    operational = assembly_module.reconstruct_actual_operational_provenance(
        base_attestation,
        consumed_results=base_results,
        execution_purpose="diagnostic",
    )
    actual = assembly_module._reconstruct_actual_finalization_state(
        tmp_path / "canonical",
        executor_attestation=changed_attestation,
    )
    with pytest.raises(ArtifactValidationError) as captured:
        assembly_module._require_actual_operational_provenance(
            operational,
            actual,
            finalization_scope=assembly_module.VALIDATION_FINALIZATION_SCOPE,
        )
    assert type(captured.value).__name__ == "ArtifactValidationError"
    assert str(captured.value) == (
        "Caller operational provenance machine differs from actual state."
    )
    assert not (tmp_path / "canonical").exists()


@pytest.mark.actual_state_provenance
def test_actual_executor_order_hashes_exact_submitted_job_identities() -> None:
    jobs = (-8, -5, -3, -1)
    forward_results, forward_attestation = execute_deterministic_map(
        abs,
        jobs,
        worker_count=2,
        executor_kind="thread_pool",
        result_order="input_order",
    )
    reversed_results, reversed_attestation = execute_deterministic_map(
        abs,
        tuple(reversed(jobs)),
        worker_count=2,
        executor_kind="thread_pool",
        result_order="input_order",
    )
    assert sorted(forward_results) == sorted(reversed_results)
    forward = executor_provenance_payload(forward_attestation)
    reversed_payload = executor_provenance_payload(reversed_attestation)
    assert (
        forward["worker_configuration_sha256"] == (reversed_payload["worker_configuration_sha256"])
    )
    assert (
        forward["worker_submission_order_sha256"]
        != (reversed_payload["worker_submission_order_sha256"])
    )
    assert forward["worker_result_order_sha256"] != (reversed_payload["worker_result_order_sha256"])


@pytest.mark.actual_state_provenance
def test_interpreter_path_and_hash_are_actual_and_mismatch_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, attestation = execute_deterministic_map(
        abs,
        (-1,),
        worker_count=1,
        executor_kind="serial",
    )
    operational = assembly_module.reconstruct_actual_operational_provenance(
        attestation,
        consumed_results=results,
        execution_purpose="diagnostic",
    )
    executable = Path(sys.executable).resolve(strict=True)
    assert operational.machine["python_executable"] == executable.as_posix()
    assert (
        operational.machine["python_executable_sha256"]
        == hashlib.sha256(executable.read_bytes()).hexdigest()
    )
    assert operational.machine["python_compiler"]
    assert operational.machine["python_build_number"]
    assert operational.machine["python_build_date"]

    copied_executable = tmp_path / executable.name
    shutil.copyfile(executable, copied_executable)
    monkeypatch.setattr(sys, "executable", os.fspath(copied_executable))
    changed_actual = assembly_module._reconstruct_actual_finalization_state(
        tmp_path / "canonical",
        executor_attestation=attestation,
    )
    with pytest.raises(ArtifactValidationError) as captured:
        assembly_module._require_actual_operational_provenance(
            operational,
            changed_actual,
            finalization_scope=assembly_module.VALIDATION_FINALIZATION_SCOPE,
        )
    assert str(captured.value) == (
        "Caller operational provenance machine differs from actual state."
    )
    assert not (tmp_path / "canonical").exists()


@pytest.mark.actual_state_provenance
@pytest.mark.parametrize("dirty_kind", ("unstaged", "staged", "untracked"))
def test_real_git_dirty_state_is_rejected_for_canonical_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dirty_kind: str,
) -> None:
    source = repository_root()
    clone = tmp_path / "clean-clone"
    git = assembly_module._resolve_git_executable()
    subprocess.run(
        [
            os.fspath(git),
            "-c",
            "core.autocrlf=false",
            "clone",
            "--quiet",
            "--no-hardlinks",
            os.fspath(source),
            os.fspath(clone),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [os.fspath(git), "-C", os.fspath(clone), "config", "core.autocrlf", "false"],
        check=True,
        capture_output=True,
    )
    for historical_root in HISTORICAL_ROOTS:
        shutil.copytree(
            source / historical_root,
            clone / historical_root,
            dirs_exist_ok=True,
        )
    if dirty_kind == "untracked":
        (clone / "disallowed-untracked.txt").write_text("dirty\n", encoding="utf-8")
    else:
        pyproject = clone / "pyproject.toml"
        pyproject.write_bytes(pyproject.read_bytes() + f"\n# {dirty_kind}\n".encode())
        if dirty_kind == "staged":
            subprocess.run(
                [os.fspath(git), "-C", os.fspath(clone), "add", "pyproject.toml"],
                check=True,
                capture_output=True,
            )
    results, attestation = execute_deterministic_map(
        abs,
        (-1,),
        worker_count=1,
        executor_kind="serial",
    )
    monkeypatch.setattr(assembly_module, "repository_root", lambda: clone)
    with pytest.raises(
        ArtifactValidationError,
        match="checkout differs from the exact executor implementation",
    ):
        assembly_module.reconstruct_actual_operational_provenance(
            attestation,
            consumed_results=results,
            execution_purpose="diagnostic",
        )
    actual = assembly_module._reconstruct_actual_finalization_state(
        tmp_path / "canonical",
        executor_attestation=attestation,
    )
    assert actual["implementation_tree_clean"] is False
    assert not (tmp_path / "canonical").exists()


@pytest.mark.parametrize(
    "attack",
    ("implementation", "source", "protected", "dependency", "runtime", "historical"),
)
def test_direct_writer_reconstructs_actual_state_immediately_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / attack / "canonical"
    _, _, receipt, artifacts = _consumed(target, conformance_oracle_support)
    original = assembly_module._reconstruct_actual_finalization_state

    def changed_actual_state(
        canonical_target: Path | None = None,
        *,
        transient_paths: tuple[Path, ...] = (),
        authorized_output_directory: bool = False,
        executor_attestation: ActualExecutorAttestation,
    ) -> dict[str, object]:
        actual = copy.deepcopy(
            original(
                canonical_target,
                transient_paths=transient_paths,
                authorized_output_directory=authorized_output_directory,
                executor_attestation=executor_attestation,
            )
        )
        if attack == "implementation":
            actual["implementation_tree_sha256"] = "a" * 64
        elif attack == "source":
            actual["source_design_sha256"] = "b" * 64
        elif attack == "protected":
            actual["protected_source_sha256"] = {"changed": "e" * 64}
            actual["protected_source_matches"] = False
        elif attack == "dependency":
            actual["dependency_lock_sha256"] = "c" * 64
        elif attack == "runtime":
            actual["machine"] = {"changed": "runtime"}
        else:
            actual["historical_source_sha256"] = {"changed": "d" * 64}
        return actual

    monkeypatch.setattr(
        assembly_module,
        "_reconstruct_actual_finalization_state",
        changed_actual_state,
    )
    try:
        with pytest.raises(
            ArtifactValidationError,
            match="changed after authorization|changed protected source",
        ):
            assembly_module._promote_scientific_artifacts(
                target,
                artifacts,
                artifact_contracts()[:11],
                CONFORMANCE_PROFILE,
                receipt=receipt,
            )
        assert not target.exists()
    finally:
        invalidate_finalization_receipt(receipt)


def test_promotion_late_actual_state_recheck_runs_after_entry_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "late-change" / "canonical"
    _, _, receipt, artifacts = _consumed(target, conformance_oracle_support)
    original = assembly_module._reconstruct_actual_finalization_state
    calls = 0

    def changes_only_at_late_recheck(
        canonical_target: Path | None = None,
        *,
        transient_paths: tuple[Path, ...] = (),
        authorized_output_directory: bool = False,
        executor_attestation: ActualExecutorAttestation,
    ) -> dict[str, object]:
        nonlocal calls
        calls += 1
        actual = copy.deepcopy(
            original(
                canonical_target,
                transient_paths=transient_paths,
                authorized_output_directory=authorized_output_directory,
                executor_attestation=executor_attestation,
            )
        )
        if calls >= 2:
            actual["implementation_tree_sha256"] = "e" * 64
        return actual

    monkeypatch.setattr(
        assembly_module,
        "_reconstruct_actual_finalization_state",
        changes_only_at_late_recheck,
    )
    try:
        with pytest.raises(ArtifactValidationError, match="changed after authorization"):
            assembly_module._promote_scientific_artifacts(
                target,
                artifacts,
                artifact_contracts()[:11],
                CONFORMANCE_PROFILE,
                receipt=receipt,
            )
        assert calls >= 2
        assert not target.exists()
        assert not tuple(target.parent.glob(f".{target.name}.artifacts-1-11.*.incomplete"))
    finally:
        invalidate_finalization_receipt(receipt)


@pytest.mark.parametrize("entry_kind", ("directory", "symlink"))
def test_manifest_reader_rejects_nonregular_and_symlink_stage_entries(
    tmp_path: Path,
    entry_kind: str,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / entry_kind / "canonical"
    _, _, receipt, artifacts = _consumed(target, conformance_oracle_support)
    contracts = artifact_contracts()
    try:
        assembly_module._promote_scientific_artifacts(
            target,
            artifacts,
            contracts[:11],
            CONFORMANCE_PROFILE,
            receipt=receipt,
        )
        advance_finalization_receipt(
            receipt,
            expected_phase="authorization_consumed",
            next_phase="scientific_artifacts_promoted",
        )
        if entry_kind == "directory":
            (target / "unexpected-directory").mkdir()
        else:
            artifact = target / "world_definitions.json"
            external = tmp_path / "external-world-definitions.json"
            external.write_bytes(artifact.read_bytes())
            artifact.unlink()
            try:
                artifact.symlink_to(external)
            except OSError as error:
                pytest.skip(f"Artifact symlink creation is unavailable: {error}")
        with pytest.raises(ArtifactValidationError, match="non-regular or symlink entries"):
            assembly_module._derive_manifest_from_promoted_artifacts(
                target,
                receipt,
                contracts,
                CONFORMANCE_PROFILE,
            )
        assert not (target / "run_manifest.json").exists()
        assert not (target / "recommendation.json").exists()
    finally:
        invalidate_finalization_receipt(receipt)


@pytest.mark.writer_authorization
def test_dangling_symlinks_cannot_occupy_promotion_or_atomic_destination(
    tmp_path: Path,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "dangling" / "canonical"
    _, _, receipt, artifacts = _consumed(target, conformance_oracle_support)
    contracts = artifact_contracts()
    dangling_directory_target = tmp_path / "external-missing-directory"
    dangling_file_target = tmp_path / "external-missing-file"
    destination = target / "run_manifest.json"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.symlink_to(dangling_directory_target, target_is_directory=True)
        except OSError as error:
            pytest.skip(f"Dangling symlink creation is unavailable: {error}")
        with pytest.raises(ArtifactValidationError) as captured_directory:
            assembly_module._promote_scientific_artifacts(
                target,
                artifacts,
                contracts[:11],
                CONFORMANCE_PROFILE,
                receipt=receipt,
            )
        assert str(captured_directory.value) == (
            "Canonical writer target differs from the receipt binding."
        )
        assert not dangling_directory_target.exists()
        target.unlink()

        assembly_module._promote_scientific_artifacts(
            target,
            artifacts,
            contracts[:11],
            CONFORMANCE_PROFILE,
            receipt=receipt,
        )
        advance_finalization_receipt(
            receipt,
            expected_phase="authorization_consumed",
            next_phase="scientific_artifacts_promoted",
        )
        manifest = assembly_module._derive_manifest_from_promoted_artifacts(
            target,
            receipt,
            contracts,
            CONFORMANCE_PROFILE,
        )
        destination.symlink_to(dangling_file_target)
        with pytest.raises(assembly_module.CanonicalCreateOnceError) as captured_file:
            assembly_module._atomic_create(
                target,
                "run_manifest.json",
                manifest,
                receipt=receipt,
                contracts=contracts,
                profile=CONFORMANCE_PROFILE,
            )
        assert captured_file.value.error_code == assembly_module.CANONICAL_CREATE_ONCE_ERROR
        assert str(captured_file.value) == (
            f"{assembly_module.CANONICAL_CREATE_ONCE_ERROR}: "
            f"canonical destination already exists: {destination}"
        )
        assert not dangling_file_target.exists()
        with pytest.raises(ValueError, match="before publication"):
            advance_finalization_receipt(
                receipt,
                expected_phase="scientific_artifacts_promoted",
                next_phase="manifest_persisted",
            )
        with pytest.raises(ValueError, match="stale or already claimed"):
            assembly_module._atomic_create(
                target,
                "run_manifest.json",
                manifest,
                receipt=receipt,
                contracts=contracts,
                profile=CONFORMANCE_PROFILE,
            )
    finally:
        if os.path.lexists(destination):
            destination.unlink()
        if target.is_symlink():
            target.unlink()
        invalidate_finalization_receipt(receipt)


@pytest.mark.writer_authorization
def test_atomic_manifest_writer_requires_exact_phase_receipt_and_content(
    tmp_path: Path,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "canonical"
    _, _, receipt, artifacts = _consumed(target, conformance_oracle_support)
    contracts = artifact_contracts()
    try:
        with pytest.raises(ValueError, match="not 'scientific_artifacts_promoted'"):
            assembly_module._atomic_create(
                target,
                "run_manifest.json",
                b"{}\n",
                receipt=receipt,
                contracts=contracts,
                profile=CONFORMANCE_PROFILE,
            )
        assert not target.exists()

        assembly_module._promote_scientific_artifacts(
            target,
            artifacts,
            contracts[:11],
            CONFORMANCE_PROFILE,
            receipt=receipt,
        )
        advance_finalization_receipt(
            receipt,
            expected_phase="authorization_consumed",
            next_phase="scientific_artifacts_promoted",
        )
        manifest = assembly_module._derive_manifest_from_promoted_artifacts(
            target,
            receipt,
            contracts,
            CONFORMANCE_PROFILE,
        )
        with pytest.raises(ArtifactValidationError):
            assembly_module._atomic_create(
                target,
                "run_manifest.json",
                manifest + b" ",
                receipt=receipt,
                contracts=contracts,
                profile=CONFORMANCE_PROFILE,
            )
        assert not (target / "run_manifest.json").exists()

        assembly_module._atomic_create(
            target,
            "run_manifest.json",
            manifest,
            receipt=receipt,
            contracts=contracts,
            profile=CONFORMANCE_PROFILE,
        )
        with pytest.raises(ValueError, match="stale or already claimed"):
            assembly_module._atomic_create(
                target,
                "run_manifest.json",
                manifest,
                receipt=receipt,
                contracts=contracts,
                profile=CONFORMANCE_PROFILE,
            )
    finally:
        invalidate_finalization_receipt(receipt)


def test_atomic_writer_reopens_exact_temporary_bytes_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "canonical"
    contracts = artifact_contracts()
    _, _, receipt, artifacts = _consumed(target, conformance_oracle_support)
    original_publish = cast(Any, assembly_module._publish_claimed_canonical_entry)
    try:
        assembly_module._promote_scientific_artifacts(
            target,
            artifacts,
            contracts[:11],
            CONFORMANCE_PROFILE,
            receipt=receipt,
        )
        advance_finalization_receipt(
            receipt,
            expected_phase="authorization_consumed",
            next_phase="scientific_artifacts_promoted",
        )
        manifest = assembly_module._derive_manifest_from_promoted_artifacts(
            target,
            receipt,
            contracts,
            CONFORMANCE_PROFILE,
        )

        def mutate_temporary(
            directory: Path,
            staging: Path,
            destination: Path,
            **kwargs: object,
        ) -> None:
            staging.write_bytes(staging.read_bytes() + b" ")
            original_publish(directory, staging, destination, **kwargs)

        monkeypatch.setattr(
            assembly_module,
            "_publish_claimed_canonical_entry",
            mutate_temporary,
        )
        with pytest.raises(ArtifactValidationError, match="staging bytes changed"):
            assembly_module._atomic_create(
                target,
                "run_manifest.json",
                manifest,
                receipt=receipt,
                contracts=contracts,
                profile=CONFORMANCE_PROFILE,
            )
        assert not (target / "run_manifest.json").exists()
        assert not tuple(target.glob(".run_manifest.json.*.incomplete"))
    finally:
        invalidate_finalization_receipt(receipt)


@pytest.mark.writer_authorization
@pytest.mark.parametrize("filename", ("run_manifest.json", "recommendation.json"))
def test_atomic_file_publish_loses_destination_race_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / filename / "canonical"
    contracts = artifact_contracts()
    _, _, receipt, artifacts = _consumed(target, conformance_oracle_support)
    original_actual_check = assembly_module._require_current_actual_state
    race_ready = threading.Event()
    competitor_finished = threading.Event()
    competitor_identity: list[tuple[int, int]] = []
    transient_check_count = 0
    try:
        assembly_module._promote_scientific_artifacts(
            target,
            artifacts,
            contracts[:11],
            CONFORMANCE_PROFILE,
            receipt=receipt,
        )
        advance_finalization_receipt(
            receipt,
            expected_phase="authorization_consumed",
            next_phase="scientific_artifacts_promoted",
        )
        manifest = assembly_module._derive_manifest_from_promoted_artifacts(
            target,
            receipt,
            contracts,
            CONFORMANCE_PROFILE,
        )
        if filename == "run_manifest.json":
            content = manifest
            expected_phase = "scientific_artifacts_promoted"
            next_phase = "manifest_persisted"
        else:
            assembly_module._atomic_create(
                target,
                "run_manifest.json",
                manifest,
                receipt=receipt,
                contracts=contracts,
                profile=CONFORMANCE_PROFILE,
            )
            advance_finalization_receipt(
                receipt,
                expected_phase="scientific_artifacts_promoted",
                next_phase="manifest_persisted",
            )
            content = assembly_module._derive_recommendation_from_persisted_manifest(
                target,
                receipt,
                contracts,
                CONFORMANCE_PROFILE,
            )
            assembly_module._verify_constructed_recommendation_commitment(
                target,
                content,
                receipt,
                contracts,
                CONFORMANCE_PROFILE,
            )
            expected_phase = "manifest_persisted"
            next_phase = "recommendation_persisted"

        def pause_after_staging_validation(
            binding: dict[str, object],
            directory: Path,
            *,
            transient_paths: tuple[Path, ...] = (),
            operational: assembly_module.AssemblyOperationalProvenance | None = None,
            authorized_output_directory: bool = False,
        ) -> None:
            nonlocal transient_check_count
            original_actual_check(
                binding,
                directory,
                transient_paths=transient_paths,
                operational=operational,
                authorized_output_directory=authorized_output_directory,
            )
            if transient_paths and transient_paths[0].name.startswith(f".{filename}."):
                transient_check_count += 1
                if transient_check_count == 2:
                    race_ready.set()
                    assert competitor_finished.wait(timeout=30)

        monkeypatch.setattr(
            assembly_module,
            "_require_current_actual_state",
            pause_after_staging_validation,
        )
        destination = target / filename

        def competing_creator() -> None:
            assert race_ready.wait(timeout=30)
            descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            stat = os.lstat(destination)
            competitor_identity.append((stat.st_dev, stat.st_ino))
            competitor_finished.set()

        competitor = threading.Thread(target=competing_creator)
        competitor.start()
        with pytest.raises(assembly_module.CanonicalCreateOnceError) as captured:
            assembly_module._atomic_create(
                target,
                filename,
                content,
                receipt=receipt,
                contracts=contracts,
                profile=CONFORMANCE_PROFILE,
            )
        competitor.join(timeout=30)
        assert not competitor.is_alive()
        assert captured.value.error_code == assembly_module.CANONICAL_CREATE_ONCE_ERROR
        assert str(captured.value).startswith(f"{assembly_module.CANONICAL_CREATE_ONCE_ERROR}:")
        assert destination.read_bytes() == content
        published_stat = os.lstat(destination)
        assert competitor_identity == [(published_stat.st_dev, published_stat.st_ino)]
        assert not tuple(target.glob(f".{filename}.*.incomplete"))
        with pytest.raises(ValueError, match="before publication"):
            advance_finalization_receipt(
                receipt,
                expected_phase=expected_phase,
                next_phase=next_phase,
            )
        with pytest.raises(ValueError, match="stale or already claimed"):
            assembly_module._atomic_create(
                target,
                filename,
                content,
                receipt=receipt,
                contracts=contracts,
                profile=CONFORMANCE_PROFILE,
            )
        assert not tuple(target.glob(f".{filename}.*.incomplete"))
    finally:
        invalidate_finalization_receipt(receipt)


@pytest.mark.writer_authorization
def test_direct_recommendation_writer_rejects_forgery_phase_content_and_reuse(
    tmp_path: Path,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    contracts = artifact_contracts()
    forged_target = tmp_path / "forged" / "canonical"
    with pytest.raises(ValueError, match="exact consumed receipt"):
        assembly_module._atomic_create(
            forged_target,
            "recommendation.json",
            b"{}\n",
            receipt=cast(ConsumedFinalizationAuthorization, object()),
            contracts=contracts,
            profile=CONFORMANCE_PROFILE,
        )
    assert not forged_target.exists()

    wrong_phase_target = tmp_path / "wrong-phase" / "canonical"
    _, _, wrong_phase_receipt, _ = _consumed(
        wrong_phase_target,
        conformance_oracle_support,
    )
    try:
        with pytest.raises(ValueError, match="not 'manifest_persisted'"):
            assembly_module._atomic_create(
                wrong_phase_target,
                "recommendation.json",
                b"{}\n",
                receipt=wrong_phase_receipt,
                contracts=contracts,
                profile=CONFORMANCE_PROFILE,
            )
        assert not wrong_phase_target.exists()
    finally:
        invalidate_finalization_receipt(wrong_phase_receipt)

    target = tmp_path / "valid" / "canonical"
    _, _, receipt, artifacts = _consumed(target, conformance_oracle_support)
    try:
        assembly_module._promote_scientific_artifacts(
            target,
            artifacts,
            contracts[:11],
            CONFORMANCE_PROFILE,
            receipt=receipt,
        )
        advance_finalization_receipt(
            receipt,
            expected_phase="authorization_consumed",
            next_phase="scientific_artifacts_promoted",
        )
        manifest = assembly_module._derive_manifest_from_promoted_artifacts(
            target,
            receipt,
            contracts,
            CONFORMANCE_PROFILE,
        )
        assembly_module._atomic_create(
            target,
            "run_manifest.json",
            manifest,
            receipt=receipt,
            contracts=contracts,
            profile=CONFORMANCE_PROFILE,
        )
        advance_finalization_receipt(
            receipt,
            expected_phase="scientific_artifacts_promoted",
            next_phase="manifest_persisted",
        )
        recommendation = assembly_module._derive_recommendation_from_persisted_manifest(
            target,
            receipt,
            contracts,
            CONFORMANCE_PROFILE,
        )
        with pytest.raises(ArtifactValidationError):
            assembly_module._atomic_create(
                target,
                "recommendation.json",
                recommendation + b" ",
                receipt=receipt,
                contracts=contracts,
                profile=CONFORMANCE_PROFILE,
            )
        assert not (target / "recommendation.json").exists()

        assembly_module._atomic_create(
            target,
            "recommendation.json",
            recommendation,
            receipt=receipt,
            contracts=contracts,
            profile=CONFORMANCE_PROFILE,
        )
        with pytest.raises(ValueError, match="stale or already claimed"):
            assembly_module._atomic_create(
                target,
                "recommendation.json",
                recommendation,
                receipt=receipt,
                contracts=contracts,
                profile=CONFORMANCE_PROFILE,
            )
    finally:
        invalidate_finalization_receipt(receipt)


def test_contract_profile_and_authorization_time_bytes_are_bound_before_promotion(
    tmp_path: Path,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "canonical"
    _, _, receipt, artifacts = _consumed(target, conformance_oracle_support)
    contracts = artifact_contracts()
    altered_contracts = list(contracts)
    altered_contracts[4] = replace(
        altered_contracts[4],
        schema_version="calibration-estimate/v3",
    )
    tampered_artifacts = dict(artifacts)
    audit_document = cast(dict[str, object], json.loads(artifacts["audit_results.json"]))
    content_hashes = cast(dict[str, str], audit_document["artifact_content_sha256"])
    content_hashes[next(iter(content_hashes))] = "f" * 64
    tampered_artifacts["audit_results.json"] = canonical_json_bytes(
        audit_document,
        final_lf=True,
    )
    try:
        with pytest.raises(ArtifactValidationError, match="frozen registry prefix"):
            decode_and_validate_audited_artifacts(
                artifacts,
                tuple(altered_contracts[:11]),
                profile=CONFORMANCE_PROFILE,
            )
        with pytest.raises(ArtifactValidationError, match="frozen registry"):
            assembly_module._promote_scientific_artifacts(
                target,
                artifacts,
                tuple(altered_contracts[:11]),
                CONFORMANCE_PROFILE,
                receipt=receipt,
            )
        with pytest.raises(ArtifactValidationError, match="artifact profile differs"):
            assembly_module._promote_scientific_artifacts(
                target,
                artifacts,
                contracts[:11],
                replace(
                    CONFORMANCE_PROFILE, bootstrap_rows=CONFORMANCE_PROFILE.bootstrap_rows + 66
                ),
                receipt=receipt,
            )
        with pytest.raises(ArtifactValidationError, match="authorization-time bytes"):
            assembly_module._promote_scientific_artifacts(
                target,
                tampered_artifacts,
                contracts[:11],
                CONFORMANCE_PROFILE,
                receipt=receipt,
            )
        assert not target.exists()
    finally:
        invalidate_finalization_receipt(receipt)


def test_canonical_and_validation_finalization_have_disjoint_profile_target_scope(
    tmp_path: Path,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    plan, operational, certificate = conformance_oracle_support.audited_plan()
    frozen_target = repository_root() / assembly_module.CANONICAL_OUTPUT_DIRECTORY
    try:
        with pytest.raises(ArtifactValidationError, match="exact frozen output directory"):
            authorize_canonical_finalization(
                tmp_path / "not-frozen-output",
                plan,
                operational,
                certificate,
                profile=FROZEN_ARTIFACT_PROFILE,
            )
        with pytest.raises(ArtifactValidationError, match="exact frozen artifact profile"):
            authorize_canonical_finalization(
                frozen_target,
                plan,
                operational,
                certificate,
                profile=CONFORMANCE_PROFILE,
            )
        with pytest.raises(ArtifactValidationError, match="cannot target"):
            authorize_validation_finalization(
                frozen_target,
                plan,
                operational,
                certificate,
                profile=CONFORMANCE_PROFILE,
            )
        with pytest.raises(ArtifactValidationError, match="noncanonical artifact profile"):
            authorize_validation_finalization(
                tmp_path / "validation",
                plan,
                operational,
                certificate,
                profile=FROZEN_ARTIFACT_PROFILE,
            )
        altered_contracts = list(artifact_contracts())
        altered_contracts[4] = replace(
            altered_contracts[4],
            schema_version="calibration-estimate/v3",
        )
        with pytest.raises(ArtifactValidationError, match="frozen registry"):
            authorize_validation_finalization(
                tmp_path / "custom-contract",
                plan,
                operational,
                certificate,
                contracts=altered_contracts,
                profile=CONFORMANCE_PROFILE,
            )
        assert not frozen_target.exists()
    finally:
        invalidate_finalization_audit_certificate(certificate)


def test_pre_audits_cannot_be_laundered_into_a_different_a16_context(
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    fixture = conformance_oracle_support.production_fixture()
    historical = historical_hash_map()
    context = IntegrityAuditContext(
        runs=fixture.runs,
        replay_runs=fixture.replay_runs,
        first_payload=conformance_module._replay_payload(fixture.runs),
        replay_payload=conformance_module._replay_payload(fixture.replay_runs),
        historical_before=historical,
        historical_after=historical,
        scope="conformance",
        artifact_graph=fixture.prefinalization.graph,
        analysis=fixture.raw_analysis,
        profile=CONFORMANCE_PROFILE,
        prefinalization_payloads=fixture.prefinalization_payloads,
        oracle_conformance_result=fixture.oracle_conformance_result,
        oracle_evidence_binding=fixture.oracle_evidence_binding,
        prefinal_operational_provenance_sha256=(
            fixture.prefinalization.operational_provenance_sha256
        ),
        executor_attestation=fixture.executor_attestation,
        replay_executor_attestation=fixture.replay_executor_attestation,
        executor_results=fixture.runs,
        replay_executor_results=fixture.replay_runs,
        execution_authority=fixture.oracle_evidence_binding,
        execution_purpose="production_conformance",
    )
    pre_authorization = execute_pre_finalization_audits(context)
    provisional = derive_provisional_analysis(fixture.raw_analysis, run_count=len(fixture.runs))
    with pytest.raises(ValueError, match="differs from the A01-A15 audited context"):
        execute_finalization_audit(
            replace(
                context,
                replay_payload=context.replay_payload + b"changed",
                analysis=provisional,
            ),
            pre_authorization,
        )


def test_a16_certificate_rejects_cross_plan_and_historical_laundering(
    tmp_path: Path,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "cross-plan"
    plan, operational, certificate = conformance_oracle_support.audited_plan()
    binding = assembly_module._finalization_binding(
        target,
        plan,
        operational,
        artifact_contracts(),
        profile=CONFORMANCE_PROFILE,
        finalization_scope=assembly_module.VALIDATION_FINALIZATION_SCOPE,
    )
    altered_scientific = plan.scientific_claims()
    altered_gate = cast(dict[str, object], altered_scientific["gate_evaluations.json"])
    altered_gate["recommendation"] = "laundered-plan"
    binding["audit_certificate_plan_sha256"] = finalization_plan_binding_sha256(
        altered_scientific,
        CONFORMANCE_PROFILE,
    )
    with pytest.raises(ValueError, match="plan or profile differs"):
        _validate_finalization_certificate_binding(certificate, binding)
    invalidate_finalization_audit_certificate(certificate)
    assert not target.exists()

    historical_target = tmp_path / "historical"
    plan, operational, certificate = conformance_oracle_support.audited_plan()
    binding = assembly_module._finalization_binding(
        historical_target,
        plan,
        operational,
        artifact_contracts(),
        profile=CONFORMANCE_PROFILE,
        finalization_scope=assembly_module.VALIDATION_FINALIZATION_SCOPE,
    )
    provenance = copy.deepcopy(cast(dict[str, object], binding["operational_provenance"]))
    before = cast(dict[str, str], provenance["historical_before_sha256"])
    before[next(iter(before))] = "0" * 64
    binding["operational_provenance"] = provenance
    with pytest.raises(ValueError, match="A14-audited historical map"):
        _validate_finalization_certificate_binding(certificate, binding)
    invalidate_finalization_audit_certificate(certificate)
    assert not historical_target.exists()


def test_prefinal_operational_identity_and_direct_seal_provenance_cannot_be_mixed(
    tmp_path: Path,
    conformance_oracle_support: ConformanceOracleSupport,
    diagnostic_conformance_fixture: DiagnosticConformanceFixture,
) -> None:
    mixed_target = tmp_path / "mixed"
    plan, _, certificate = conformance_oracle_support.audited_plan()
    different_operational = assembly_module.reconstruct_actual_operational_provenance(
        diagnostic_conformance_fixture.executor_attestation,
        consumed_results=diagnostic_conformance_fixture.runs,
        execution_authority=diagnostic_conformance_fixture.oracle_fixture_binding,
        execution_purpose="diagnostic_conformance",
    )
    try:
        with pytest.raises(ArtifactValidationError, match="Prefinal artifacts differ"):
            authorize_validation_finalization(
                mixed_target,
                plan,
                different_operational,
                certificate,
                profile=CONFORMANCE_PROFILE,
            )
        assert not mixed_target.exists()
    finally:
        invalidate_finalization_audit_certificate(certificate)

    direct_target = tmp_path / "direct-seal"
    plan, operational, certificate = conformance_oracle_support.audited_plan()
    binding = assembly_module._finalization_binding(
        direct_target,
        plan,
        operational,
        artifact_contracts(),
        profile=CONFORMANCE_PROFILE,
        finalization_scope=assembly_module.VALIDATION_FINALIZATION_SCOPE,
    )
    different_issued_operational = assembly_module.reconstruct_actual_operational_provenance(
        diagnostic_conformance_fixture.executor_attestation,
        consumed_results=diagnostic_conformance_fixture.runs,
        execution_authority=diagnostic_conformance_fixture.oracle_fixture_binding,
        execution_purpose="diagnostic_conformance",
    )
    replacement_payload = assembly_module._operational_provenance_payload(
        different_issued_operational
    )
    assert replacement_payload != binding["operational_provenance"]
    binding["operational_provenance"] = replacement_payload
    binding["operational_provenance_sha256"] = assembly_module._operational_provenance_sha256(
        different_issued_operational
    )
    try:
        with pytest.raises(ArtifactValidationError, match="Prefinal artifacts differ"):
            assembly_module._issue_checked_finalization_binding_attestation(
                direct_target,
                plan,
                different_issued_operational,
                certificate,
                artifact_contracts(),
                CONFORMANCE_PROFILE,
                finalization_scope=assembly_module.VALIDATION_FINALIZATION_SCOPE,
                binding=binding,
            )
        with pytest.raises(ValueError, match="exact issued binding attestation"):
            seal_finalization_authorization(certificate, binding)
        assert not direct_target.exists()
    finally:
        invalidate_finalization_audit_certificate(certificate)


def test_replaced_prefinal_operational_identity_cannot_be_laundered(
    tmp_path: Path,
    conformance_oracle_support: ConformanceOracleSupport,
    diagnostic_conformance_fixture: DiagnosticConformanceFixture,
) -> None:
    target = tmp_path / "replaced-prefinal"
    plan_a, _, certificate_a = conformance_oracle_support.audited_plan()
    operational_b = assembly_module.reconstruct_actual_operational_provenance(
        diagnostic_conformance_fixture.executor_attestation,
        consumed_results=diagnostic_conformance_fixture.runs,
        execution_authority=diagnostic_conformance_fixture.oracle_fixture_binding,
        execution_purpose="diagnostic_conformance",
    )
    forged_prefinal = replace(
        plan_a.prefinalization,
        operational_provenance_sha256=assembly_module._operational_provenance_sha256(operational_b),
    )
    forged_plan = replace(plan_a, prefinalization=forged_prefinal)

    try:
        with pytest.raises(
            ArtifactValidationError,
            match="not issued by exact prefinalization assembly",
        ):
            authorize_validation_finalization(
                target,
                forged_plan,
                operational_b,
                certificate_a,
                profile=CONFORMANCE_PROFILE,
            )
        assert not target.exists()
    finally:
        invalidate_finalization_audit_certificate(certificate_a)


def test_certificate_a_rejects_separately_issued_prefinal_b(
    tmp_path: Path,
    conformance_oracle_support: ConformanceOracleSupport,
    diagnostic_conformance_fixture: DiagnosticConformanceFixture,
) -> None:
    target = tmp_path / "cross-prefinal-certificate"
    fixture = diagnostic_conformance_fixture
    plan_a, _, certificate_a = conformance_oracle_support.audited_plan()
    operational_b = assembly_module.reconstruct_actual_operational_provenance(
        diagnostic_conformance_fixture.executor_attestation,
        consumed_results=diagnostic_conformance_fixture.runs,
        execution_authority=diagnostic_conformance_fixture.oracle_fixture_binding,
        execution_purpose="diagnostic_conformance",
    )
    prefinal_b = assembly_module.assemble_prefinalization_artifacts(
        projection_module.build_prefinalization_payloads(
            fixture.runs,
            fixture.raw_analysis,
        ),
        operational_b,
        profile=CONFORMANCE_PROFILE,
    )
    plan_b = CanonicalFinalizationPlan(prefinal_b, plan_a.post_audit)
    assert plan_b.scientific_claims() == plan_a.scientific_claims()

    try:
        with pytest.raises(
            ValueError,
            match="A01-A16 audited prefinal set",
        ):
            authorize_validation_finalization(
                target,
                plan_b,
                operational_b,
                certificate_a,
                profile=CONFORMANCE_PROFILE,
            )
        assert not target.exists()
    finally:
        invalidate_finalization_audit_certificate(certificate_a)


def test_direct_writer_rejects_missing_or_changed_binding_semantics_before_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "invalid-binding"
    _, _, receipt, artifacts = _consumed(target, conformance_oracle_support)
    original_binding = finalization_receipt_binding
    mutation: dict[str, object] = {
        "field": "artifact_content_sha256",
        "value": None,
        "remove": True,
    }

    def altered_binding(
        exact_receipt: ConsumedFinalizationAuthorization,
        *,
        expected_phase: str,
    ) -> dict[str, object]:
        binding = original_binding(exact_receipt, expected_phase=expected_phase)
        field = cast(str, mutation["field"])
        if mutation["remove"] is True:
            del binding[field]
        else:
            binding[field] = mutation["value"]
        return binding

    monkeypatch.setattr(
        assembly_module,
        "finalization_receipt_binding",
        altered_binding,
    )
    try:
        cases: tuple[tuple[str, object, bool, str], ...] = (
            ("artifact_content_sha256", None, True, "binding fields differ"),
            ("design_checkpoint", "0" * 40, False, "design_checkpoint differs"),
            ("source_design_sha256", "0" * 64, False, "source_design_sha256 differs"),
            ("source_checkpoint_identity", "changed", False, "source_checkpoint_identity differs"),
            ("ordered_run_identity_sha256", "0" * 64, False, "run identity differs"),
            ("g_integrity", "FAIL", False, "G-INTEGRITY differs"),
            ("provisional_decision", {}, False, "provisional decision differs"),
        )
        for field, value, remove, expected in cases:
            mutation.update(field=field, value=value, remove=remove)
            with pytest.raises(ArtifactValidationError, match=expected):
                assembly_module._promote_scientific_artifacts(
                    target,
                    artifacts,
                    artifact_contracts()[:11],
                    CONFORMANCE_PROFILE,
                    receipt=receipt,
                )
        assert not target.exists()
    finally:
        invalidate_finalization_receipt(receipt)


def test_actual_source_and_test_edits_change_tree_and_diff_identities(tmp_path: Path) -> None:
    git = assembly_module._resolve_git_executable()
    assembly_module._git_bytes(git, tmp_path, "init", "--quiet")
    assembly_module._git_bytes(git, tmp_path, "config", "user.name", "RDE Test")
    assembly_module._git_bytes(git, tmp_path, "config", "user.email", "rde@example.invalid")
    package = tmp_path / "research_decision_engine"
    tests = tmp_path / "tests"
    package.mkdir()
    tests.mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (package / "fixture.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tests / "test_fixture.py").write_text("def test_fixture(): pass\n", encoding="utf-8")
    assembly_module._git_bytes(git, tmp_path, "add", ".")
    assembly_module._git_bytes(git, tmp_path, "commit", "--quiet", "-m", "checkpoint")
    checkpoint = assembly_module._git_text(git, tmp_path, "rev-parse", "HEAD")
    checkpoint_tree = assembly_module._git_tree(git, tmp_path, checkpoint)
    before_tree = assembly_module._working_implementation_tree(git, tmp_path)
    before_tree_identity = assembly_module._implementation_tree_identity(before_tree)
    before_diff_identity = assembly_module._implementation_diff_identity(
        git,
        tmp_path,
        checkpoint_tree,
        before_tree,
        source_checkpoint=checkpoint,
    )

    (package / "fixture.py").write_text("VALUE = 2\n", encoding="utf-8")
    (tests / "test_fixture.py").write_text(
        "def test_fixture():\n    assert True\n", encoding="utf-8"
    )
    after_tree = assembly_module._working_implementation_tree(git, tmp_path)
    after_tree_identity = assembly_module._implementation_tree_identity(after_tree)
    after_diff_identity = assembly_module._implementation_diff_identity(
        git,
        tmp_path,
        checkpoint_tree,
        after_tree,
        source_checkpoint=checkpoint,
    )

    assert after_tree_identity != before_tree_identity
    assert after_diff_identity != before_diff_identity

    (tests / "test_untracked.py").write_text("def test_untracked(): pass\n", encoding="utf-8")
    with_untracked = assembly_module._working_implementation_tree(git, tmp_path)
    assert "tests/test_untracked.py" not in with_untracked
    assert assembly_module._implementation_tree_identity(with_untracked) == after_tree_identity
    assert (
        assembly_module._implementation_diff_identity(
            git,
            tmp_path,
            checkpoint_tree,
            with_untracked,
            source_checkpoint=checkpoint,
        )
        == after_diff_identity
    )


def test_in_repository_target_does_not_self_invalidate_actual_state(
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    root = repository_root()
    container = Path(tempfile.mkdtemp(prefix=".rde-finalization-test-", dir=root))
    target = container / "canonical"
    try:
        plan, operational, authorization = _authorized(target, conformance_oracle_support)
        persisted = _finalize(target, plan, operational, authorization)
        assert len(persisted) == 13
        assert (target / "recommendation.json").is_file()
    finally:
        shutil.rmtree(container, ignore_errors=True)


def test_validation_failure_schema_remains_exact(
    tmp_path: Path,
    diagnostic_conformance_fixture: DiagnosticConformanceFixture,
) -> None:
    target = tmp_path / "canonical"
    fixture = diagnostic_conformance_fixture
    plan = fixture.finalization_plan
    operational = fixture.operational
    with pytest.raises(ValueError, match="exact issued capability"):
        _finalize(target, plan, operational, cast(FinalizationAuthorization, object()))

    failure_path = tmp_path / "validation_failure.json"
    failure = json.loads(failure_path.read_bytes())
    assert set(failure) == {
        "schema_version",
        "phase",
        "error_code",
        "path",
        "message",
        "context",
        "details_sha256",
    }
