from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from research_decision_engine.benchmarks.broader_lifecycle import (
    LifecycleInvariantError,
    LifecycleState,
    OperationalRead,
    RetryDisposition,
    RetrySource,
    SelectedReader,
)
from research_decision_engine.benchmarks.broader_lifecycle_io import (
    StagingLayout,
    StudyLock,
    TargetPaths,
    raw_sha256,
)
from research_decision_engine.benchmarks.broader_lifecycle_records import (
    ARTIFACT_FILENAMES,
    STUDY_ID,
    AttemptRecord,
    FailedTransition,
    FailureErrorCode,
    FailurePhase,
    InventoryEntry,
    InventoryNamespace,
    LedgerPredecessor,
    RetryKind,
    RetryTerminalResult,
    build_attempt_record,
    build_failure_record,
    build_m11_record,
    build_m12_record,
    build_m13_record,
    build_mf_record,
    envelope_for_record,
    make_binding_envelope,
    validate_record,
)
from tests.taskb_lifecycle_harness import controlled_authority
from tests.test_broader_lifecycle_reader import (
    AUTH_A,
    AUTH_B,
    IDENTITY,
    PUB_A,
    PUB_B,
    NoOpGraphValidator,
    _artifact_hashes,
    _artifact_map,
    _canonical_target,
    _install_publication,
    _primary,
    _reader,
)

PUB_C = "publication-" + "3" * 64
PUB_D = "publication-" + "4" * 64
AUTH_C = "authorization-attempt-" + "5" * 64
AUTH_D = "authorization-attempt-" + "6" * 64

_STAGE_SHAPE: Mapping[str, tuple[int, tuple[str, ...]]] = {
    "A": (0, ()),
    "g": (1, ()),
    "G": (11, ()),
    "M11": (11, ("M11",)),
    "V": (12, ("M11",)),
    "M12": (12, ("M11", "M12")),
    "R": (13, ("M11", "M12")),
    "M13": (13, ("M11", "M12", "M13")),
    "MF": (13, ("M11", "M12", "M13", "MF")),
}


def _paths(primary: Path, target: Path, publication_id: str) -> TargetPaths:
    return TargetPaths.from_target(
        target,
        publication_id,
        primary_target=primary,
    )


def _sculpt_publication(
    primary: Path,
    stage: str,
    *,
    target: Path | None = None,
    publication_id: str = PUB_A,
    authorization_attempt_id: str = AUTH_A,
) -> bytes:
    selected = target or primary
    attempt = _install_publication(
        primary,
        target=selected,
        publication_id=publication_id,
        authorization_attempt_id=authorization_attempt_id,
        stage="success",
    )
    artifact_count, markers = _STAGE_SHAPE[stage]
    paths = _paths(primary, selected, publication_id)
    for marker in ("M11", "M12", "M13", "MF"):
        if marker not in markers:
            (paths.attempt_directory / marker).unlink()
    for name in ARTIFACT_FILENAMES[artifact_count:]:
        (selected / name).unlink()
    if artifact_count == 0:
        selected.rmdir()
    return attempt


def _inventory(
    primary: Path, target: Path, publication_id: str, stage: str
) -> tuple[InventoryEntry, ...]:
    artifact_count, markers = _STAGE_SHAPE[stage]
    paths = _paths(primary, target, publication_id)
    entries: list[InventoryEntry] = [
        InventoryEntry(
            InventoryNamespace.LEDGER,
            "attempt.json",
            raw_sha256(paths.attempt_file.read_bytes()),
        )
    ]
    for name in ARTIFACT_FILENAMES[: min(artifact_count, 11)]:
        entries.append(
            InventoryEntry(
                InventoryNamespace.CANONICAL, name, raw_sha256((target / name).read_bytes())
            )
        )
    if "M11" in markers:
        entries.append(
            InventoryEntry(
                InventoryNamespace.LEDGER,
                "M11",
                raw_sha256((paths.attempt_directory / "M11").read_bytes()),
            )
        )
    if artifact_count >= 12:
        entries.append(
            InventoryEntry(
                InventoryNamespace.CANONICAL,
                "run_manifest.json",
                raw_sha256((target / "run_manifest.json").read_bytes()),
            )
        )
    if "M12" in markers:
        entries.append(
            InventoryEntry(
                InventoryNamespace.LEDGER,
                "M12",
                raw_sha256((paths.attempt_directory / "M12").read_bytes()),
            )
        )
    if artifact_count >= 13:
        entries.append(
            InventoryEntry(
                InventoryNamespace.CANONICAL,
                "recommendation.json",
                raw_sha256((target / "recommendation.json").read_bytes()),
            )
        )
    if "M13" in markers:
        entries.append(
            InventoryEntry(
                InventoryNamespace.LEDGER,
                "M13",
                raw_sha256((paths.attempt_directory / "M13").read_bytes()),
            )
        )
    return tuple(entries)


def _add_failure(
    primary: Path,
    target: Path,
    publication_id: str,
    stage: str,
    *,
    graph_failure: bool = False,
) -> bytes:
    paths = _paths(primary, target, publication_id)
    attempt = validate_record("attempt.json", paths.attempt_file.read_bytes())
    assert isinstance(attempt, AttemptRecord)
    inventory = _inventory(primary, target, publication_id, stage)
    if graph_failure:
        phase = FailurePhase.GRAPH_VALIDATION
        transition = FailedTransition.M13_TO_GRAPH_VALIDATION
        error = FailureErrorCode.VALIDATION_GRAPH
        predecessor = LedgerPredecessor.M13
    else:
        phase = FailurePhase.RECOVERY
        transition = FailedTransition.ATTEMPT_TO_ARTIFACTS_1_11
        error = FailureErrorCode.RECOVERY_ABANDONED
        predecessor = LedgerPredecessor.ATTEMPT
    predecessor_hash = next(
        entry.byte_sha256
        for entry in inventory
        if entry.namespace is InventoryNamespace.LEDGER and entry.filename == predecessor.value
    )
    failure = build_failure_record(
        envelope_for_record(attempt.envelope, "failure.json"),
        phase=phase,
        failed_transition=transition,
        error_code=error,
        predecessor_filename=predecessor,
        predecessor_sha256=predecessor_hash,
        observed_inventory=inventory,
    )
    (paths.attempt_directory / "failure.json").write_bytes(failure)
    return failure


@dataclass(frozen=True, slots=True)
class CrashCase:
    row: str
    stage: str | None
    state: LifecycleState
    retry: RetryDisposition
    artifact_count: int
    diagnostic: str = "NONE"
    graph_defect: bool = False
    failure: str | None = None
    staging_residue: bool = False


CRASH_CASES = (
    CrashCase("1a", None, LifecycleState.NEVER_PUBLISHED, RetryDisposition.R0, 0),
    CrashCase(
        "1b",
        None,
        LifecycleState.NEVER_PUBLISHED,
        RetryDisposition.R0,
        0,
        staging_residue=True,
    ),
    CrashCase(
        "1c-failure-absent", "A", LifecycleState.ABORTED_BEFORE_PUBLICATION, RetryDisposition.RX, 0
    ),
    CrashCase(
        "1c-failure-survives",
        "A",
        LifecycleState.ABORTED_BEFORE_PUBLICATION,
        RetryDisposition.RX,
        0,
        diagnostic="VALID",
        failure="attempt",
    ),
    CrashCase("2-attempt-absent", None, LifecycleState.NEVER_PUBLISHED, RetryDisposition.R0, 0),
    CrashCase(
        "2-attempt-survives", "A", LifecycleState.ABORTED_BEFORE_PUBLICATION, RetryDisposition.RX, 0
    ),
    CrashCase("3", "A", LifecycleState.ABORTED_BEFORE_PUBLICATION, RetryDisposition.RX, 0),
    CrashCase(
        "4a-group-absent", "A", LifecycleState.ABORTED_BEFORE_PUBLICATION, RetryDisposition.RX, 0
    ),
    CrashCase(
        "4a-group-survives",
        "G",
        LifecycleState.PARTIAL_SCIENTIFIC_PUBLICATION_INVALID,
        RetryDisposition.RX,
        11,
    ),
    CrashCase(
        "4b", "g", LifecycleState.PARTIAL_SCIENTIFIC_PUBLICATION_INVALID, RetryDisposition.RX, 1
    ),
    CrashCase(
        "5-m11-absent",
        "G",
        LifecycleState.PARTIAL_SCIENTIFIC_PUBLICATION_INVALID,
        RetryDisposition.RX,
        11,
    ),
    CrashCase(
        "5-m11-survives",
        "M11",
        LifecycleState.PARTIAL_SCIENTIFIC_PUBLICATION_INVALID,
        RetryDisposition.RX,
        11,
    ),
    CrashCase(
        "6", "M11", LifecycleState.PARTIAL_SCIENTIFIC_PUBLICATION_INVALID, RetryDisposition.RX, 11
    ),
    CrashCase(
        "7-manifest-absent",
        "M11",
        LifecycleState.PARTIAL_SCIENTIFIC_PUBLICATION_INVALID,
        RetryDisposition.RX,
        11,
    ),
    CrashCase(
        "7-manifest-survives",
        "V",
        LifecycleState.MANIFEST_PUBLISHED_INCOMPLETE,
        RetryDisposition.RX,
        12,
    ),
    CrashCase(
        "8-m12-absent", "V", LifecycleState.MANIFEST_PUBLISHED_INCOMPLETE, RetryDisposition.RX, 12
    ),
    CrashCase(
        "8-m12-survives",
        "M12",
        LifecycleState.MANIFEST_PUBLISHED_INCOMPLETE,
        RetryDisposition.RX,
        12,
    ),
    CrashCase("9", "M12", LifecycleState.MANIFEST_PUBLISHED_INCOMPLETE, RetryDisposition.RX, 12),
    CrashCase(
        "10-recommendation-absent",
        "M12",
        LifecycleState.MANIFEST_PUBLISHED_INCOMPLETE,
        RetryDisposition.RX,
        12,
    ),
    CrashCase(
        "10-recommendation-survives",
        "R",
        LifecycleState.RECOMMENDATION_PUBLISHED_NOT_FINALIZED,
        RetryDisposition.RX,
        13,
    ),
    CrashCase(
        "10-recommendation-defect",
        "R",
        LifecycleState.INVALID,
        RetryDisposition.RN,
        13,
        graph_defect=True,
    ),
    CrashCase(
        "11-m13-absent",
        "R",
        LifecycleState.RECOMMENDATION_PUBLISHED_NOT_FINALIZED,
        RetryDisposition.RX,
        13,
    ),
    CrashCase(
        "11-m13-survives",
        "M13",
        LifecycleState.RECOMMENDATION_PUBLISHED_NOT_FINALIZED,
        RetryDisposition.RX,
        13,
    ),
    CrashCase(
        "11-graph-defect",
        "M13",
        LifecycleState.INVALID,
        RetryDisposition.RN,
        13,
        graph_defect=True,
    ),
    CrashCase(
        "12-valid",
        "M13",
        LifecycleState.RECOMMENDATION_PUBLISHED_NOT_FINALIZED,
        RetryDisposition.RX,
        13,
    ),
    CrashCase(
        "12-defect", "M13", LifecycleState.INVALID, RetryDisposition.RN, 13, graph_defect=True
    ),
    CrashCase(
        "13-valid",
        "M13",
        LifecycleState.RECOMMENDATION_PUBLISHED_NOT_FINALIZED,
        RetryDisposition.RX,
        13,
    ),
    CrashCase(
        "13-defect", "M13", LifecycleState.INVALID, RetryDisposition.RN, 13, graph_defect=True
    ),
    CrashCase(
        "13-defect-failure-survives",
        "M13",
        LifecycleState.INVALID,
        RetryDisposition.RX,
        13,
        diagnostic="VALID",
        graph_defect=True,
        failure="graph",
    ),
    CrashCase(
        "14-mf-absent",
        "M13",
        LifecycleState.RECOMMENDATION_PUBLISHED_NOT_FINALIZED,
        RetryDisposition.RX,
        13,
    ),
    CrashCase("14-mf-survives", "MF", LifecycleState.SUCCESS, RetryDisposition.RN, 13),
    CrashCase(
        "14-mf-defect", "MF", LifecycleState.INVALID, RetryDisposition.RN, 13, graph_defect=True
    ),
    CrashCase("15-success", "MF", LifecycleState.SUCCESS, RetryDisposition.RN, 13),
    CrashCase(
        "15-post-mf-defect",
        "MF",
        LifecycleState.INVALID,
        RetryDisposition.RN,
        13,
        graph_defect=True,
    ),
)


@pytest.mark.taskb_crash
@pytest.mark.parametrize("case", CRASH_CASES, ids=lambda case: case.row)
def test_crash_rows_1a_through_15_are_reconstructed_from_survivors(
    tmp_path: Path, case: CrashCase
) -> None:
    primary = _primary(tmp_path)
    if case.stage is not None:
        _sculpt_publication(primary, case.stage)
    if case.staging_residue:
        StagingLayout.from_target(
            primary,
            PUB_A,
            primary_target=primary,
        ).ensure_root()
    if case.failure == "attempt":
        _add_failure(primary, primary, PUB_A, "A")
    elif case.failure == "graph":
        _add_failure(primary, primary, PUB_A, "M13", graph_failure=True)
    validator = NoOpGraphValidator(fail_13=case.graph_defect)
    result = _reader(primary, validator).classify(STUDY_ID, primary, PUB_A)

    assert result.operational is None
    assert result.selected_reader is (None if case.stage is None else SelectedReader.AMENDED)
    assert result.terminal_state is case.state
    assert result.retry_disposition is case.retry
    assert result.canonical_inventory == ARTIFACT_FILENAMES[: case.artifact_count]
    assert result.diagnostic_status == case.diagnostic
    assert (result.retry_disposition in {RetryDisposition.R0, RetryDisposition.RX}) is (
        case.retry in {RetryDisposition.R0, RetryDisposition.RX}
    )
    assert bool(result.staging_residue) is case.staging_residue


@pytest.mark.taskb_crash
def test_visible_survivors_are_unclassified_while_writer_lock_is_active(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    _sculpt_publication(primary, "M13")
    lock = StudyLock.for_primary_target(primary)
    assert lock.acquire_exclusive(blocking=True)
    try:
        result = _reader(primary).classify(STUDY_ID, primary, PUB_A)
    finally:
        lock.release()
    assert result.operational is OperationalRead.WRITER_ACTIVE
    assert result.selected_reader is None
    assert result.terminal_state is None
    assert result.retry_disposition is None
    assert result.canonical_inventory == ()
    assert result.diagnostic_status == "NONE"


def _install_bound_retry(
    primary: Path,
    target: Path,
    publication_id: str,
    authorization_attempt_id: str,
    *,
    source_target: Path,
    source_publication_id: str,
    source_authorization_attempt_id: str,
    source_attempt_sha256: str,
    source_failure_sha256: str | None,
    stage: str,
) -> bytes:
    artifacts = _artifact_map()
    envelope = make_binding_envelope(
        "attempt.json",
        canonical_target=_canonical_target(target, primary),
        publication_id=publication_id,
        implementation_commit=IDENTITY.implementation_commit,
        implementation_tree_sha256=IDENTITY.implementation_tree_sha256,
        implementation_diff_sha256=IDENTITY.implementation_diff_sha256,
        authorization_attempt_id=authorization_attempt_id,
    )
    attempt = build_attempt_record(
        envelope,
        _artifact_hashes(artifacts, 11),
        retry_kind=RetryKind.RX,
        retry_of_publication_id=source_publication_id,
        retry_source_canonical_target=_canonical_target(source_target, primary),
        retry_source_authorization_attempt_id=source_authorization_attempt_id,
        retry_source_attempt_sha256=source_attempt_sha256,
        retry_source_failure_sha256=source_failure_sha256,
        retry_source_terminal_result=RetryTerminalResult.ABORTED_BEFORE_PUBLICATION,
        retry_authorization_id=authorization_attempt_id,
    )
    paths = _paths(primary, target, publication_id)
    paths.attempt_directory.mkdir(parents=True)
    paths.attempt_file.write_bytes(attempt)
    artifact_count, markers = _STAGE_SHAPE[stage]
    if artifact_count:
        target.mkdir()
        for name in ARTIFACT_FILENAMES[:artifact_count]:
            (target / name).write_bytes(artifacts[name])
    if "M11" in markers:
        m11 = build_m11_record(
            envelope_for_record(envelope, "M11"),
            attempt_sha256=raw_sha256(attempt),
            artifacts_1_11=_artifact_hashes(artifacts, 11),
        )
        (paths.attempt_directory / "M11").write_bytes(m11)
    if "M12" in markers:
        m12 = build_m12_record(
            envelope_for_record(envelope, "M12"),
            m11_sha256=raw_sha256(m11),
            manifest_byte_sha256=raw_sha256(artifacts["run_manifest.json"]),
        )
        (paths.attempt_directory / "M12").write_bytes(m12)
    if "M13" in markers:
        m13 = build_m13_record(
            envelope_for_record(envelope, "M13"),
            m12_sha256=raw_sha256(m12),
            recommendation_byte_sha256=raw_sha256(artifacts["recommendation.json"]),
        )
        (paths.attempt_directory / "M13").write_bytes(m13)
    if "MF" in markers:
        mf = build_mf_record(
            envelope_for_record(envelope, "MF"),
            m13_sha256=raw_sha256(m13),
            artifacts_1_13=_artifact_hashes(artifacts, 13),
        )
        (paths.attempt_directory / "MF").write_bytes(mf)
    return attempt


@pytest.mark.taskb_crash
def test_crash_row_16_waiter_is_refused_after_distinct_winner_success(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    _sculpt_publication(primary, "MF")
    waiter = primary.with_name(f"{primary.name}.retry-{PUB_B}")
    reader = _reader(primary)

    winner = reader.classify(STUDY_ID, primary, PUB_A)
    waiting = reader.classify(STUDY_ID, waiter, PUB_B)
    assert winner.selected_reader is SelectedReader.AMENDED
    assert winner.terminal_state is LifecycleState.SUCCESS
    assert winner.retry_disposition is RetryDisposition.RN
    assert winner.canonical_inventory == ARTIFACT_FILENAMES
    assert winner.diagnostic_status == "NONE"
    assert waiting.selected_reader is None
    assert waiting.terminal_state is LifecycleState.NEVER_PUBLISHED
    assert waiting.retry_disposition is RetryDisposition.RN
    assert waiting.canonical_inventory == ()
    assert waiting.diagnostic_status == "NONE"
    assert waiting.retry_disposition not in {RetryDisposition.R0, RetryDisposition.RX}


@pytest.mark.taskb_crash
def test_crash_row_17_closed_child_never_advances_after_descendant_success(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    root_attempt = _sculpt_publication(primary, "A")
    root_failure = _add_failure(primary, primary, PUB_A, "A")
    child_target = primary.with_name(f"{primary.name}.retry-{PUB_B}")
    child_attempt = _install_bound_retry(
        primary,
        child_target,
        PUB_B,
        AUTH_B,
        source_target=primary,
        source_publication_id=PUB_A,
        source_authorization_attempt_id=AUTH_A,
        source_attempt_sha256=raw_sha256(root_attempt),
        source_failure_sha256=raw_sha256(root_failure),
        stage="A",
    )
    child_failure = _add_failure(primary, child_target, PUB_B, "A")
    descendant_target = primary.with_name(f"{primary.name}.retry-{PUB_C}")
    _install_bound_retry(
        primary,
        descendant_target,
        PUB_C,
        AUTH_C,
        source_target=child_target,
        source_publication_id=PUB_B,
        source_authorization_attempt_id=AUTH_B,
        source_attempt_sha256=raw_sha256(child_attempt),
        source_failure_sha256=raw_sha256(child_failure),
        stage="MF",
    )
    reader = _reader(primary)

    child = reader.classify(STUDY_ID, child_target, PUB_B)
    descendant = reader.classify(STUDY_ID, descendant_target, PUB_C)
    assert child.selected_reader is SelectedReader.AMENDED
    assert child.terminal_state is LifecycleState.ABORTED_BEFORE_PUBLICATION
    assert child.retry_disposition is RetryDisposition.RN
    assert child.canonical_inventory == ()
    assert child.diagnostic_status == "VALID"
    assert descendant.selected_reader is SelectedReader.AMENDED
    assert descendant.terminal_state is LifecycleState.SUCCESS
    assert descendant.retry_disposition is RetryDisposition.RN
    assert descendant.canonical_inventory == ARTIFACT_FILENAMES
    assert descendant.diagnostic_status == "NONE"


@pytest.mark.taskb_crash
def test_crash_row_18_serializes_same_source_to_one_child(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    source_attempt = _sculpt_publication(primary, "A")
    source_failure = _add_failure(primary, primary, PUB_A, "A")
    winner_target = primary.with_name(f"{primary.name}.retry-{PUB_B}")
    _install_bound_retry(
        primary,
        winner_target,
        PUB_B,
        AUTH_B,
        source_target=primary,
        source_publication_id=PUB_A,
        source_authorization_attempt_id=AUTH_A,
        source_attempt_sha256=raw_sha256(source_attempt),
        source_failure_sha256=raw_sha256(source_failure),
        stage="A",
    )
    source_binding = RetrySource(
        RetryKind.RX,
        _canonical_target(primary, primary),
        PUB_A,
        AUTH_A,
        raw_sha256(source_attempt),
        raw_sha256(source_failure),
        RetryTerminalResult.ABORTED_BEFORE_PUBLICATION,
    )
    authority = controlled_authority(primary, NoOpGraphValidator(), IDENTITY)
    artifacts = _artifact_map()
    loser = authority.prepare(
        {name: artifacts[name] for name in ARTIFACT_FILENAMES[:11]},
        IDENTITY,
        retry_source=source_binding,
    )
    with (
        pytest.raises(LifecycleInvariantError, match="not currently RX eligible"),
        authority.issue(loser),
    ):
        pytest.fail("A second child authorization must not be issued.")

    reader = _reader(primary)
    source = reader.classify(STUDY_ID, primary, PUB_A)
    winner = reader.classify(STUDY_ID, winner_target, PUB_B)
    rejected = reader.classify(STUDY_ID, loser.target, loser.publication_id)
    assert source.terminal_state is LifecycleState.ABORTED_BEFORE_PUBLICATION
    assert source.retry_disposition is RetryDisposition.RN
    assert source.canonical_inventory == ()
    assert source.diagnostic_status == "VALID"
    assert winner.terminal_state is LifecycleState.ABORTED_BEFORE_PUBLICATION
    assert winner.retry_disposition is RetryDisposition.RX
    assert winner.canonical_inventory == ()
    assert winner.diagnostic_status == "NONE"
    assert rejected.selected_reader is None
    assert rejected.terminal_state is LifecycleState.NEVER_PUBLISHED
    assert rejected.retry_disposition is RetryDisposition.RN
    assert rejected.canonical_inventory == ()
    assert rejected.diagnostic_status == "NONE"
