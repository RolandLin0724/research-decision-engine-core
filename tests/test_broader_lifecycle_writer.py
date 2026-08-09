from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

import research_decision_engine.benchmarks.broader_lifecycle as lifecycle
from research_decision_engine.benchmarks.broader_lifecycle import (
    AttemptAuthority,
    ImplementationIdentity,
    LifecycleInvariantError,
)
from research_decision_engine.benchmarks.broader_lifecycle_io import (
    ExistingDestinationError,
    publish_bytes_no_replace,
    publish_directory_bytes_no_replace,
)
from research_decision_engine.benchmarks.broader_lifecycle_records import (
    ARTIFACT_FILENAMES,
    PROTOCOL_CHECKPOINT,
    FailureErrorCode,
    FailurePhase,
    FailureRecord,
    validate_record,
)
from tests.taskb_lifecycle_harness import controlled_authority

IDENTITY = ImplementationIdentity("a" * 40, "b" * 64, "c" * 64)


class _Graph:
    def validate_11(self, artifacts: Mapping[str, bytes]) -> None:
        assert tuple(artifacts) == ARTIFACT_FILENAMES[:11]

    def validate_12(self, artifacts: Mapping[str, bytes]) -> None:
        assert tuple(artifacts) == ARTIFACT_FILENAMES[:12]

    def validate_13(self, artifacts: Mapping[str, bytes]) -> None:
        assert tuple(artifacts) == ARTIFACT_FILENAMES

    def validate_historical(self, artifacts: Mapping[str, bytes]) -> None:
        assert tuple(artifacts) == ARTIFACT_FILENAMES


def _artifact(name: str) -> bytes:
    if name.endswith(".csv"):
        return f"source_checkpoint_identifier\n{PROTOCOL_CHECKPOINT}\n".encode()
    value = {"source_checkpoint_identifier": PROTOCOL_CHECKPOINT, "name": name}
    if name == "run_manifest.json":
        value.update(
            {
                "implementation_commit": IDENTITY.implementation_commit,
                "implementation_tree_sha256": IDENTITY.implementation_tree_sha256,
                "implementation_diff_sha256": IDENTITY.implementation_diff_sha256,
            }
        )
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _first_eleven() -> dict[str, bytes]:
    return {name: _artifact(name) for name in ARTIFACT_FILENAMES[:11]}


def _authority(tmp_path: Path) -> tuple[AttemptAuthority, Path]:
    target = tmp_path / "broader-replication-v1-128-seeds"
    return controlled_authority(target, _Graph(), IDENTITY), target


@pytest.mark.taskb_durability
def test_writer_publishes_the_only_success_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority, target = _authority(tmp_path)
    prepared = authority.prepare(_first_eleven(), IDENTITY)
    events: list[str] = []
    real_directory = publish_directory_bytes_no_replace
    real_file = publish_bytes_no_replace

    def publish_directory(*args: object, **kwargs: object) -> dict[str, bytes]:
        events.append(cast(Path, args[1]).name)
        return real_directory(*args, **kwargs)  # type: ignore[arg-type]

    def publish_file(*args: object, **kwargs: object) -> bytes:
        events.append(cast(Path, args[1]).name)
        return real_file(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(lifecycle, "publish_directory_bytes_no_replace", publish_directory)
    monkeypatch.setattr(lifecycle, "publish_bytes_no_replace", publish_file)

    result = authority.finalize(
        prepared,
        manifest_builder=lambda _artifacts: _artifact("run_manifest.json"),
        recommendation_builder=lambda _artifacts: _artifact("recommendation.json"),
    )

    assert tuple(result) == ARTIFACT_FILENAMES
    assert events == [
        prepared.publication_id,
        target.name,
        "M11",
        "run_manifest.json",
        "M12",
        "recommendation.json",
        "M13",
        "MF",
    ]
    ledger = Path(str(target) + ".rde-attempts") / prepared.publication_id
    assert {entry.name for entry in ledger.iterdir()} == {
        "attempt.json",
        "M11",
        "M12",
        "M13",
        "MF",
    }


@pytest.mark.taskb_diagnostic
def test_manifest_builder_failure_closes_exact_m11_prefix(tmp_path: Path) -> None:
    authority, target = _authority(tmp_path)
    before = _first_eleven()
    prepared = authority.prepare(before, IDENTITY)

    def fail_manifest(_artifacts: Mapping[str, bytes]) -> bytes:
        raise RuntimeError("controlled manifest construction failure")

    with (
        pytest.raises(
            LifecycleInvariantError,
            match="trusted manifest builder failed",
        ) as caught,
        authority.issue(prepared) as issued,
    ):
        issued.finalize(
            issued.authorization,
            manifest_builder=fail_manifest,
            recommendation_builder=lambda _artifacts: _artifact("recommendation.json"),
        )
    assert isinstance(caught.value.__cause__, RuntimeError)

    assert {name: (target / name).read_bytes() for name in ARTIFACT_FILENAMES[:11]} == before
    assert not (target / "run_manifest.json").exists()
    ledger = Path(str(target) + ".rde-attempts") / prepared.publication_id
    record = validate_record("failure.json", (ledger / "failure.json").read_bytes())
    assert isinstance(record, FailureRecord)
    assert record.phase is FailurePhase.MANIFEST
    assert record.error_code is FailureErrorCode.INTERNAL_INVARIANT
    assert {entry.name for entry in ledger.iterdir()} == {"attempt.json", "M11", "failure.json"}


@pytest.mark.taskb_diagnostic
def test_existing_manifest_is_not_adopted_or_rewritten(tmp_path: Path) -> None:
    authority, target = _authority(tmp_path)
    prepared = authority.prepare(_first_eleven(), IDENTITY)
    manifest = _artifact("run_manifest.json")

    def collide(_artifacts: Mapping[str, bytes]) -> bytes:
        (target / "run_manifest.json").write_bytes(manifest)
        return manifest

    with pytest.raises(ExistingDestinationError), authority.issue(prepared) as issued:
        issued.finalize(
            issued.authorization,
            manifest_builder=collide,
            recommendation_builder=lambda _artifacts: _artifact("recommendation.json"),
        )

    assert (target / "run_manifest.json").read_bytes() == manifest
    assert not (target / "recommendation.json").exists()
    ledger = Path(str(target) + ".rde-attempts") / prepared.publication_id
    record = validate_record("failure.json", (ledger / "failure.json").read_bytes())
    assert isinstance(record, FailureRecord)
    assert record.error_code is FailureErrorCode.NAMESPACE_EXISTING_FINAL
    assert not (ledger / "M12").exists()


@pytest.mark.taskb_crash
def test_recovery_closes_attempt_only_once_with_identical_bytes(tmp_path: Path) -> None:
    authority, target = _authority(tmp_path)
    prepared = authority.prepare(_first_eleven(), IDENTITY)
    with authority.issue(prepared) as issued:
        issued.claim(issued.authorization)

    first = authority.recover_abandoned(target, prepared.publication_id)
    second = authority.recover_abandoned(target, prepared.publication_id)
    assert second == first
    record = validate_record("failure.json", first)
    assert isinstance(record, FailureRecord)
    assert record.phase is FailurePhase.RECOVERY
    assert record.error_code is FailureErrorCode.RECOVERY_ABANDONED
    assert not target.exists()
