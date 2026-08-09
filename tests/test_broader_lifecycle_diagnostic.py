from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

import research_decision_engine.benchmarks.broader_lifecycle as lifecycle
from research_decision_engine.benchmarks.broader_artifacts import ArtifactValidationError
from research_decision_engine.benchmarks.broader_lifecycle import (
    AttemptAuthority,
    ImplementationIdentity,
    LifecycleState,
    RetryDisposition,
    SelectedReader,
)
from research_decision_engine.benchmarks.broader_lifecycle_io import (
    DurabilityError,
    LifecycleIOError,
    PublicationValidationError,
    canonical_ledger_bytes,
    publish_bytes_no_replace,
    publish_directory_bytes_no_replace,
    raw_sha256,
)
from research_decision_engine.benchmarks.broader_lifecycle_records import (
    ARTIFACT_FILENAMES,
    PROTOCOL_CHECKPOINT,
    STUDY_ID,
    FailedTransition,
    FailureErrorCode,
    FailurePhase,
    FailureRecord,
    InventoryNamespace,
    LedgerPredecessor,
    validate_record,
)
from tests.taskb_lifecycle_harness import controlled_authority

IDENTITY = ImplementationIdentity("a" * 40, "b" * 64, "c" * 64)
OTHER_PUBLICATION = "publication-" + "d" * 64
OTHER_AUTHORIZATION = "authorization-attempt-" + "e" * 64


class _Graph:
    def __init__(self) -> None:
        self.fail_complete_graph = False

    def validate_11(self, artifacts: Mapping[str, bytes]) -> None:
        assert tuple(artifacts) == ARTIFACT_FILENAMES[:11]

    def validate_12(self, artifacts: Mapping[str, bytes]) -> None:
        assert tuple(artifacts) == ARTIFACT_FILENAMES[:12]

    def validate_13(self, artifacts: Mapping[str, bytes]) -> None:
        assert tuple(artifacts) == ARTIFACT_FILENAMES
        if self.fail_complete_graph:
            raise ArtifactValidationError("controlled complete-graph defect")

    def validate_historical(self, artifacts: Mapping[str, bytes]) -> None:
        assert tuple(artifacts) == ARTIFACT_FILENAMES


def _artifact(name: str) -> bytes:
    if name.endswith(".csv"):
        return f"source_checkpoint_identifier\n{PROTOCOL_CHECKPOINT}\n".encode()
    value: dict[str, object] = {
        "name": name,
        "source_checkpoint_identifier": PROTOCOL_CHECKPOINT,
    }
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


def _authority(tmp_path: Path) -> tuple[AttemptAuthority, Path, _Graph]:
    target = tmp_path / "broader-replication-v1-128-seeds"
    graph = _Graph()
    return controlled_authority(target, graph, IDENTITY), target, graph


@pytest.mark.taskb_durability
def test_existing_failure_recovery_reflushes_complete_applicable_directory_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, target, _graph = _authority(tmp_path)
    prepared = authority.prepare(_first_eleven(), IDENTITY)

    def fail_manifest(_artifacts: Mapping[str, bytes]) -> bytes:
        raise RuntimeError("controlled handled failure")

    with pytest.raises(lifecycle.LifecycleInvariantError):
        authority.finalize(
            prepared,
            manifest_builder=fail_manifest,
            recommendation_builder=lambda _artifacts: _artifact("recommendation.json"),
        )

    ledger_root = Path(str(target) + ".rde-attempts")
    attempt_directory = ledger_root / prepared.publication_id
    failure = (attempt_directory / "failure.json").read_bytes()
    flushed: list[Path] = []
    monkeypatch.setattr(lifecycle, "fsync_directory", lambda path: flushed.append(Path(path)))

    assert authority.recover_abandoned(target, prepared.publication_id) == failure
    assert {attempt_directory, ledger_root, ledger_root.parent, target, target.parent} <= set(
        flushed
    )


@dataclass(frozen=True, slots=True)
class _DiagnosticCase:
    id: str
    trigger: str
    phase: FailurePhase
    transition: FailedTransition
    error_code: FailureErrorCode
    predecessor: LedgerPredecessor
    inventory: tuple[tuple[InventoryNamespace, str], ...]


_A = ((InventoryNamespace.LEDGER, "attempt.json"),)
_G = _A + tuple((InventoryNamespace.CANONICAL, name) for name in ARTIFACT_FILENAMES[:11])
_M11 = _G + ((InventoryNamespace.LEDGER, "M11"),)
_V = _M11 + ((InventoryNamespace.CANONICAL, "run_manifest.json"),)
_M12 = _V + ((InventoryNamespace.LEDGER, "M12"),)
_R = _M12 + ((InventoryNamespace.CANONICAL, "recommendation.json"),)
_M13 = _R + ((InventoryNamespace.LEDGER, "M13"),)

_CASES = (
    _DiagnosticCase(
        "attempt-directory-barrier",
        "attempt-postinstall",
        FailurePhase.ATTEMPT,
        FailedTransition.INSTALL_ATTEMPT,
        FailureErrorCode.IO_DIRECTORY_FSYNC,
        LedgerPredecessor.ATTEMPT,
        _A,
    ),
    _DiagnosticCase(
        "artifacts-stage-write",
        "canonical-directory",
        FailurePhase.ARTIFACTS_1_11,
        FailedTransition.ATTEMPT_TO_ARTIFACTS_1_11,
        FailureErrorCode.IO_STAGE_WRITE,
        LedgerPredecessor.ATTEMPT,
        _A,
    ),
    _DiagnosticCase(
        "m11-stage-write",
        "M11",
        FailurePhase.M11,
        FailedTransition.ARTIFACTS_1_11_TO_M11,
        FailureErrorCode.IO_STAGE_WRITE,
        LedgerPredecessor.ATTEMPT,
        _G,
    ),
    _DiagnosticCase(
        "manifest-stage-write",
        "run_manifest.json",
        FailurePhase.MANIFEST,
        FailedTransition.M11_TO_MANIFEST,
        FailureErrorCode.IO_STAGE_WRITE,
        LedgerPredecessor.M11,
        _M11,
    ),
    _DiagnosticCase(
        "m12-stage-write",
        "M12",
        FailurePhase.M12,
        FailedTransition.MANIFEST_TO_M12,
        FailureErrorCode.IO_STAGE_WRITE,
        LedgerPredecessor.M11,
        _V,
    ),
    _DiagnosticCase(
        "recommendation-stage-write",
        "recommendation.json",
        FailurePhase.RECOMMENDATION,
        FailedTransition.M12_TO_RECOMMENDATION,
        FailureErrorCode.IO_STAGE_WRITE,
        LedgerPredecessor.M12,
        _M12,
    ),
    _DiagnosticCase(
        "m13-stage-write",
        "M13",
        FailurePhase.M13,
        FailedTransition.RECOMMENDATION_TO_M13,
        FailureErrorCode.IO_STAGE_WRITE,
        LedgerPredecessor.M12,
        _R,
    ),
    _DiagnosticCase(
        "graph-validation",
        "graph-after-M13",
        FailurePhase.GRAPH_VALIDATION,
        FailedTransition.M13_TO_GRAPH_VALIDATION,
        FailureErrorCode.VALIDATION_GRAPH,
        LedgerPredecessor.M13,
        _M13,
    ),
    _DiagnosticCase(
        "mf-stage-write",
        "MF",
        FailurePhase.MF,
        FailedTransition.GRAPH_VALIDATION_TO_MF,
        FailureErrorCode.IO_STAGE_WRITE,
        LedgerPredecessor.M13,
        _M13,
    ),
)


def _path_for_inventory(
    target: Path,
    ledger: Path,
    namespace: InventoryNamespace,
    filename: str,
) -> Path:
    return (ledger if namespace is InventoryNamespace.LEDGER else target) / filename


@pytest.mark.taskb_diagnostic
@pytest.mark.parametrize("case", _CASES, ids=lambda case: case.id)
def test_writer_diagnostic_matrix_has_exact_frozen_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: _DiagnosticCase,
) -> None:
    authority, target, graph = _authority(tmp_path)
    prepared = authority.prepare(_first_eleven(), IDENTITY)
    real_directory = publish_directory_bytes_no_replace
    real_file = publish_bytes_no_replace

    def publish_directory(*args: object, **kwargs: object) -> dict[str, bytes]:
        destination = cast(Path, args[1])
        if case.trigger == "canonical-directory" and destination == target:
            raise LifecycleIOError(
                "controlled artifact stage failure",
                protocol_error_code="IO_STAGE_WRITE",
                failed_path=prepared.staging.artifacts_1_11_publication,
            )
        result = real_directory(*args, **kwargs)  # type: ignore[arg-type]
        if case.trigger == "attempt-postinstall" and destination.name == prepared.publication_id:
            raise DurabilityError(
                "controlled attempt directory barrier",
                protocol_error_code="IO_DIRECTORY_FSYNC",
                failed_path=destination,
            )
        return result

    def publish_file(*args: object, **kwargs: object) -> bytes:
        destination = cast(Path, args[1])
        if case.trigger == destination.name:
            raise LifecycleIOError(
                "controlled final-name stage failure",
                protocol_error_code="IO_STAGE_WRITE",
                failed_path=cast(Path, args[0]),
            )
        result = real_file(*args, **kwargs)  # type: ignore[arg-type]
        if case.trigger == "graph-after-M13" and destination.name == "M13":
            graph.fail_complete_graph = True
        return result

    monkeypatch.setattr(lifecycle, "publish_directory_bytes_no_replace", publish_directory)
    monkeypatch.setattr(lifecycle, "publish_bytes_no_replace", publish_file)

    expected_exception = (
        ArtifactValidationError if case.trigger == "graph-after-M13" else LifecycleIOError
    )
    with pytest.raises(expected_exception):
        authority.finalize(
            prepared,
            manifest_builder=lambda _artifacts: _artifact("run_manifest.json"),
            recommendation_builder=lambda _artifacts: _artifact("recommendation.json"),
        )

    ledger = Path(str(target) + ".rde-attempts") / prepared.publication_id
    failure_bytes = (ledger / "failure.json").read_bytes()
    record = validate_record("failure.json", failure_bytes)
    assert isinstance(record, FailureRecord)
    assert record.phase is case.phase
    assert record.failed_transition is case.transition
    assert record.error_code is case.error_code
    assert record.predecessor_filename is case.predecessor
    predecessor = ledger / case.predecessor.value
    assert record.predecessor_sha256 == raw_sha256(predecessor.read_bytes())
    assert tuple((entry.namespace, entry.filename) for entry in record.observed_inventory) == (
        case.inventory
    )
    for entry in record.observed_inventory:
        installed = _path_for_inventory(target, ledger, entry.namespace, entry.filename)
        assert entry.byte_sha256 == raw_sha256(installed.read_bytes())
    assert "MF" not in {entry.name for entry in ledger.iterdir()}


@pytest.mark.taskb_diagnostic
def test_final_graph_reread_io_has_exact_readback_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, target, _graph = _authority(tmp_path)
    prepared = authority.prepare(_first_eleven(), IDENTITY)
    ledger = Path(str(target) + ".rde-attempts") / prepared.publication_id
    real_read = lifecycle._read_exact_regular_files

    def read_exact(directory: Path, names: tuple[str, ...]) -> dict[str, bytes]:
        if directory == target and tuple(names) == ARTIFACT_FILENAMES and (ledger / "M13").exists():
            raise OSError("controlled final-graph reread failure")
        return real_read(directory, names)

    monkeypatch.setattr(lifecycle, "_read_exact_regular_files", read_exact)
    with pytest.raises(PublicationValidationError):
        authority.finalize(
            prepared,
            manifest_builder=lambda _artifacts: _artifact("run_manifest.json"),
            recommendation_builder=lambda _artifacts: _artifact("recommendation.json"),
        )

    failure = validate_record("failure.json", (ledger / "failure.json").read_bytes())
    assert isinstance(failure, FailureRecord)
    assert failure.phase is FailurePhase.GRAPH_VALIDATION
    assert failure.failed_transition is FailedTransition.M13_TO_GRAPH_VALIDATION
    assert failure.error_code is FailureErrorCode.IO_FINAL_READBACK
    assert failure.predecessor_filename is LedgerPredecessor.M13
    assert tuple((entry.namespace, entry.filename) for entry in failure.observed_inventory) == _M13
    assert "MF" not in {entry.name for entry in ledger.iterdir()}
    result = authority._reader(IDENTITY).classify(
        STUDY_ID,
        target,
        prepared.publication_id,
    )
    assert result.selected_reader is SelectedReader.AMENDED
    assert result.terminal_state is LifecycleState.RECOMMENDATION_PUBLISHED_NOT_FINALIZED
    assert result.retry_disposition is RetryDisposition.RX
    assert result.canonical_inventory == ARTIFACT_FILENAMES
    assert result.diagnostic_status == "VALID"


@pytest.mark.taskb_diagnostic
def test_recovery_diagnostic_is_deterministic_and_does_not_rewrite_canonical(
    tmp_path: Path,
) -> None:
    authority, target, _graph = _authority(tmp_path)
    prepared = authority.prepare(_first_eleven(), IDENTITY)
    with authority.issue(prepared) as issued:
        issued.claim(issued.authorization)

    before = {path: path.read_bytes() for path in target.iterdir()} if target.exists() else {}
    first = authority.recover_abandoned(target, prepared.publication_id)
    second = authority.recover_abandoned(target, prepared.publication_id)
    assert second == first
    assert (
        {path: path.read_bytes() for path in target.iterdir()} if target.exists() else {}
    ) == before
    record = validate_record("failure.json", first)
    assert isinstance(record, FailureRecord)
    assert record.phase is FailurePhase.RECOVERY
    assert record.failed_transition is FailedTransition.ATTEMPT_TO_ARTIFACTS_1_11
    assert record.error_code is FailureErrorCode.RECOVERY_ABANDONED
    assert record.predecessor_filename is LedgerPredecessor.ATTEMPT
    assert tuple((entry.namespace, entry.filename) for entry in record.observed_inventory) == _A


@pytest.mark.taskb_diagnostic
def test_failure_publication_cannot_mutate_another_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, target, _graph = _authority(tmp_path)
    prepared = authority.prepare(_first_eleven(), IDENTITY)
    real_directory = publish_directory_bytes_no_replace

    def fail_artifacts(*args: object, **kwargs: object) -> dict[str, bytes]:
        destination = cast(Path, args[1])
        if destination == target:
            raise LifecycleIOError(
                "controlled selected-publication failure",
                protocol_error_code="IO_STAGE_WRITE",
                failed_path=cast(Path, args[0]),
            )
        return real_directory(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(lifecycle, "publish_directory_bytes_no_replace", fail_artifacts)
    with authority.issue(prepared) as issued:
        attempt_bytes = issued.claim(issued.authorization)
        other_directory = Path(str(target) + ".rde-attempts") / OTHER_PUBLICATION
        other_directory.mkdir(parents=True)
        other_value = json.loads(attempt_bytes)
        other_value.update(
            {
                "publication_id": OTHER_PUBLICATION,
                "authorization_attempt_id": OTHER_AUTHORIZATION,
                "protocol_checkpoint": "1" * 40,
            }
        )
        other_bytes = canonical_ledger_bytes(other_value)
        (other_directory / "attempt.json").write_bytes(other_bytes)
        other_names = tuple(path.name for path in other_directory.iterdir())

        with pytest.raises(LifecycleIOError):
            issued.finalize_claimed(
                manifest_builder=lambda _artifacts: _artifact("run_manifest.json"),
                recommendation_builder=lambda _artifacts: _artifact("recommendation.json"),
            )

    selected = Path(str(target) + ".rde-attempts") / prepared.publication_id
    assert (selected / "failure.json").is_file()
    assert (other_directory / "attempt.json").read_bytes() == other_bytes
    assert tuple(path.name for path in other_directory.iterdir()) == other_names
    assert not (other_directory / "failure.json").exists()
