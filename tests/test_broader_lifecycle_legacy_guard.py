from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

import research_decision_engine.benchmarks.broader_assembly as assembly
from research_decision_engine.benchmarks.broader_artifact_graph import FROZEN_ARTIFACT_PROFILE
from research_decision_engine.benchmarks.broader_artifacts import (
    ArtifactValidationError,
    artifact_contracts,
)
from research_decision_engine.benchmarks.broader_assembly import (
    AssemblyOperationalProvenance,
    CanonicalFinalizationPlan,
)
from research_decision_engine.benchmarks.broader_audits import (
    FinalizationAuditCertificate,
    FinalizationAuthorization,
)
from research_decision_engine.benchmarks.broader_protocol import protocol_hash


@pytest.mark.taskb_authorization
@pytest.mark.parametrize(
    "operation",
    [
        lambda target: assembly.authorize_canonical_finalization(
            target,
            cast(CanonicalFinalizationPlan, object()),
            cast(AssemblyOperationalProvenance, object()),
            cast(FinalizationAuditCertificate, object()),
        ),
        lambda target: assembly.finalize_canonical_artifacts(
            target,
            cast(CanonicalFinalizationPlan, object()),
            cast(AssemblyOperationalProvenance, object()),
            cast(FinalizationAuthorization, object()),
        ),
    ],
)
def test_superseded_public_canonical_wrappers_fail_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: Callable[[Path], object],
) -> None:
    target = tmp_path / assembly.CANONICAL_OUTPUT_DIRECTORY

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("superseded private canonical writer was reached")

    monkeypatch.setattr(assembly, "_authorize_finalization", forbidden)
    monkeypatch.setattr(assembly, "_finalize_artifacts", forbidden)

    with pytest.raises(
        ArtifactValidationError,
        match="superseding attempt-ledger lifecycle coordinator",
    ):
        operation(target)

    assert not target.exists()
    assert not (tmp_path / "validation_failure.json").exists()


@pytest.mark.taskb_authorization
def test_validation_only_wrappers_remain_separate_from_canonical_guard() -> None:
    assert assembly.finalize_validation_artifacts is not assembly.finalize_canonical_artifacts
    assert (
        assembly.authorize_validation_finalization is not assembly.authorize_canonical_finalization
    )


@pytest.mark.taskb_authorization
@pytest.mark.parametrize(
    "relative_target",
    (
        assembly.CANONICAL_OUTPUT_DIRECTORY + ".retry-publication-" + "a" * 64,
        assembly.CANONICAL_OUTPUT_DIRECTORY + ".rde-attempts",
        assembly.CANONICAL_OUTPUT_DIRECTORY + ".rde-staging",
        assembly.CANONICAL_OUTPUT_DIRECTORY + ".retry-malformed",
        assembly.CANONICAL_OUTPUT_DIRECTORY + ".retry-publication-" + "b" * 64 + ".rde-attempts",
    ),
)
def test_validation_only_writer_rejects_every_reserved_lifecycle_family_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_target: str,
) -> None:
    monkeypatch.setattr(assembly, "repository_root", lambda: tmp_path)
    profile = replace(FROZEN_ARTIFACT_PROFILE, canonical=False)

    with pytest.raises(ArtifactValidationError, match="frozen lifecycle family"):
        assembly._require_finalization_context(
            tmp_path / relative_target,
            artifact_contracts(),
            profile,
            finalization_scope=assembly.VALIDATION_FINALIZATION_SCOPE,
        )


@pytest.mark.taskb_diagnostic
def test_original_early_validation_failure_contract_is_unchanged(tmp_path: Path) -> None:
    target = tmp_path / assembly.CANONICAL_OUTPUT_DIRECTORY
    error = ArtifactValidationError("controlled pre-publication validation failure")

    assembly._emit_validation_failure(target, error)
    failure_path = tmp_path / "validation_failure.json"
    first = failure_path.read_bytes()
    assembly._emit_validation_failure(target, error)

    assert failure_path.read_bytes() == first
    value = json.loads(first)
    assert set(value) == {
        "schema_version",
        "phase",
        "error_code",
        "path",
        "message",
        "context",
        "details_sha256",
    }
    assert value["schema_version"] == "validation-failure/v1"
    details = {name: value[name] for name in ("phase", "error_code", "path", "message", "context")}
    assert value["details_sha256"] == protocol_hash("validation_failure_details/v1", details)
    assert not target.exists()
    assert not Path(str(target) + ".rde-attempts").exists()
