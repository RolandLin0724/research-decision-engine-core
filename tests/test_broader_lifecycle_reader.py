from __future__ import annotations

import copy
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from research_decision_engine.benchmarks.broader_artifacts import ArtifactValidationError
from research_decision_engine.benchmarks.broader_lifecycle import (
    AttemptAuthorization,
    ImplementationIdentity,
    LifecycleInvariantError,
    LifecycleReader,
    LifecycleState,
    OperationalRead,
    RetryDisposition,
    SelectedReader,
)
from research_decision_engine.benchmarks.broader_lifecycle_io import (
    StagingLayout,
    TargetPaths,
    UnsafePathError,
    canonical_ledger_bytes,
    normalize_target,
    parse_canonical_ledger_bytes,
    raw_sha256,
)
from research_decision_engine.benchmarks.broader_lifecycle_records import (
    ARTIFACT_FILENAMES,
    PROTOCOL_CHECKPOINT,
    SOURCE_DESIGN_CHECKPOINT,
    STUDY_ID,
    ArtifactHash,
    RetryKind,
    RetryTerminalResult,
    build_attempt_record,
    build_m11_record,
    build_m12_record,
    build_m13_record,
    build_mf_record,
    envelope_for_record,
    make_binding_envelope,
)
from tests.taskb_lifecycle_harness import controlled_authority, controlled_reader

PUB_A = "publication-" + "a" * 64
PUB_B = "publication-" + "b" * 64
AUTH_A = "authorization-attempt-" + "c" * 64
AUTH_B = "authorization-attempt-" + "d" * 64
IDENTITY = ImplementationIdentity("e" * 40, "f" * 64, "0" * 64)


@dataclass(slots=True)
class NoOpGraphValidator:
    """Deterministic graph boundary used to isolate lifecycle predicates."""

    fail_13: bool = False
    calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    def _record(self, operation: str, artifacts: Mapping[str, bytes]) -> None:
        self.calls.append((operation, tuple(artifacts)))

    def validate_11(self, artifacts: Mapping[str, bytes]) -> None:
        self._record("validate_11", artifacts)

    def validate_12(self, artifacts: Mapping[str, bytes]) -> None:
        self._record("validate_12", artifacts)

    def validate_13(self, artifacts: Mapping[str, bytes]) -> None:
        self._record("validate_13", artifacts)
        if self.fail_13:
            raise ArtifactValidationError("injected complete-graph failure")

    def validate_historical(self, artifacts: Mapping[str, bytes]) -> None:
        self._record("validate_historical", artifacts)


def _primary(tmp_path: Path) -> Path:
    return tmp_path / "broader-replication-v1-128-seeds"


def _canonical_target(target: Path, primary: Path) -> str:
    result = normalize_target(target, primary_target=primary)
    assert isinstance(result, str)
    return result


def _reader(primary: Path, validator: NoOpGraphValidator | None = None) -> LifecycleReader:
    return controlled_reader(primary, validator or NoOpGraphValidator(), IDENTITY)


def _artifact_bytes(filename: str, checkpoint: str = PROTOCOL_CHECKPOINT) -> bytes:
    if filename.endswith(".csv"):
        return (f"source_checkpoint_identifier,artifact\n{checkpoint},{filename}\n").encode()
    value = {
        "artifact": filename,
        "source_checkpoint_identifier": checkpoint,
    }
    if filename == "run_manifest.json":
        value.update(
            {
                "implementation_commit": IDENTITY.implementation_commit,
                "implementation_tree_sha256": IDENTITY.implementation_tree_sha256,
                "implementation_diff_sha256": IDENTITY.implementation_diff_sha256,
            }
        )
    if filename.endswith(".jsonl"):
        return canonical_ledger_bytes(value)
    return canonical_ledger_bytes(value)


def _artifact_map(checkpoint: str = PROTOCOL_CHECKPOINT) -> dict[str, bytes]:
    return {name: _artifact_bytes(name, checkpoint) for name in ARTIFACT_FILENAMES}


def _artifact_hashes(artifacts: Mapping[str, bytes], count: int) -> tuple[ArtifactHash, ...]:
    return tuple(
        ArtifactHash(index, name, raw_sha256(artifacts[name]))
        for index, name in enumerate(ARTIFACT_FILENAMES[:count], 1)
    )


def _ledger_directory(target: Path, publication_id: str) -> Path:
    directory = Path(str(target) + ".rde-attempts") / publication_id
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def _install_publication(
    primary: Path,
    *,
    target: Path | None = None,
    publication_id: str = PUB_A,
    authorization_attempt_id: str = AUTH_A,
    stage: str = "attempt",
    retry_source: tuple[str, str, str, str] | None = None,
) -> bytes:
    selected_target = target or primary
    artifacts = _artifact_map()
    envelope = make_binding_envelope(
        "attempt.json",
        canonical_target=_canonical_target(selected_target, primary),
        publication_id=publication_id,
        implementation_commit=IDENTITY.implementation_commit,
        implementation_tree_sha256=IDENTITY.implementation_tree_sha256,
        implementation_diff_sha256=IDENTITY.implementation_diff_sha256,
        authorization_attempt_id=authorization_attempt_id,
    )
    if retry_source is None:
        attempt = build_attempt_record(envelope, _artifact_hashes(artifacts, 11))
    else:
        source_target, source_publication, source_authorization, source_attempt_sha256 = (
            retry_source
        )
        attempt = build_attempt_record(
            envelope,
            _artifact_hashes(artifacts, 11),
            retry_kind=RetryKind.RX,
            retry_of_publication_id=source_publication,
            retry_source_canonical_target=source_target,
            retry_source_authorization_attempt_id=source_authorization,
            retry_source_attempt_sha256=source_attempt_sha256,
            retry_source_failure_sha256=None,
            retry_source_terminal_result=(
                RetryTerminalResult.RECOMMENDATION_PUBLISHED_NOT_FINALIZED
            ),
            retry_authorization_id=authorization_attempt_id,
        )
    ledger = _ledger_directory(selected_target, publication_id)
    (ledger / "attempt.json").write_bytes(attempt)

    artifact_count = {
        "attempt": 0,
        "partial": 1,
        "partial11": 11,
        "manifest": 12,
        "recommendation": 13,
        "success": 13,
    }[stage]
    if artifact_count:
        selected_target.mkdir(parents=False, exist_ok=False)
        for name in ARTIFACT_FILENAMES[:artifact_count]:
            (selected_target / name).write_bytes(artifacts[name])

    if stage in {"manifest", "recommendation", "success"}:
        m11 = build_m11_record(
            envelope_for_record(envelope, "M11"),
            attempt_sha256=raw_sha256(attempt),
            artifacts_1_11=_artifact_hashes(artifacts, 11),
        )
        (ledger / "M11").write_bytes(m11)
    else:
        return attempt

    if stage in {"manifest", "recommendation", "success"}:
        m12 = build_m12_record(
            envelope_for_record(envelope, "M12"),
            m11_sha256=raw_sha256(m11),
            manifest_byte_sha256=raw_sha256(artifacts["run_manifest.json"]),
        )
        (ledger / "M12").write_bytes(m12)
    else:
        return attempt

    if stage in {"recommendation", "success"}:
        m13 = build_m13_record(
            envelope_for_record(envelope, "M13"),
            m12_sha256=raw_sha256(m12),
            recommendation_byte_sha256=raw_sha256(artifacts["recommendation.json"]),
        )
        (ledger / "M13").write_bytes(m13)
    else:
        return attempt

    if stage == "success":
        mf = build_mf_record(
            envelope_for_record(envelope, "MF"),
            m13_sha256=raw_sha256(m13),
            artifacts_1_13=_artifact_hashes(artifacts, 13),
        )
        (ledger / "MF").write_bytes(mf)
    return attempt


def _write_historical_graph(primary: Path) -> None:
    primary.mkdir(parents=False, exist_ok=True)
    for name, content in _artifact_map(SOURCE_DESIGN_CHECKPOINT).items():
        (primary / name).write_bytes(content)


@pytest.mark.taskb_reader
@pytest.mark.parametrize(
    ("stage", "expected_state", "expected_reader", "expected_retry"),
    [
        ("never", LifecycleState.NEVER_PUBLISHED, None, RetryDisposition.R0),
        (
            "attempt",
            LifecycleState.ABORTED_BEFORE_PUBLICATION,
            SelectedReader.AMENDED,
            RetryDisposition.RX,
        ),
        (
            "partial",
            LifecycleState.PARTIAL_SCIENTIFIC_PUBLICATION_INVALID,
            SelectedReader.AMENDED,
            RetryDisposition.RX,
        ),
        (
            "manifest",
            LifecycleState.MANIFEST_PUBLISHED_INCOMPLETE,
            SelectedReader.AMENDED,
            RetryDisposition.RX,
        ),
        (
            "recommendation",
            LifecycleState.RECOMMENDATION_PUBLISHED_NOT_FINALIZED,
            SelectedReader.AMENDED,
            RetryDisposition.RX,
        ),
        (
            "invalid",
            LifecycleState.INVALID,
            SelectedReader.AMENDED,
            RetryDisposition.RN,
        ),
        (
            "success",
            LifecycleState.SUCCESS,
            SelectedReader.AMENDED,
            RetryDisposition.RN,
        ),
    ],
)
def test_each_closed_terminal_state(
    tmp_path: Path,
    stage: str,
    expected_state: LifecycleState,
    expected_reader: SelectedReader | None,
    expected_retry: RetryDisposition,
) -> None:
    primary = _primary(tmp_path)
    if stage not in {"never", "invalid"}:
        _install_publication(primary, stage=stage)
    elif stage == "invalid":
        _install_publication(primary, stage="attempt")
        paths = TargetPaths.from_target(primary, PUB_A, primary_target=primary)
        (paths.attempt_directory / "M11").write_bytes(b"{}\n")
    result = _reader(primary).classify(STUDY_ID, primary, PUB_A)
    assert result.terminal_state is expected_state
    assert result.selected_reader is expected_reader
    assert result.retry_disposition is expected_retry
    assert result.operational is None


@pytest.mark.taskb_checkpoint
def test_ledger_without_attempt_is_invalid_without_dispatch(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    ledger = _ledger_directory(primary, PUB_A)
    (ledger / "M11").write_bytes(b"{}\n")
    result = _reader(primary).classify(STUDY_ID, primary, PUB_A)
    assert result.terminal_state is LifecycleState.INVALID
    assert result.selected_reader is None
    assert result.reason == "LEDGER_WITHOUT_ATTEMPT"


@pytest.mark.taskb_checkpoint
@pytest.mark.parametrize("checkpoint", ["1" * 40, SOURCE_DESIGN_CHECKPOINT])
def test_unknown_or_historical_ledger_checkpoint_never_falls_back(
    tmp_path: Path, checkpoint: str
) -> None:
    primary = _primary(tmp_path)
    _install_publication(primary, stage="attempt")
    _write_historical_graph(primary)
    paths = TargetPaths.from_target(primary, PUB_A, primary_target=primary)
    value = parse_canonical_ledger_bytes((paths.attempt_directory / "attempt.json").read_bytes())
    value["protocol_checkpoint"] = checkpoint
    (paths.attempt_directory / "attempt.json").write_bytes(canonical_ledger_bytes(value))

    result = _reader(primary).classify(STUDY_ID, primary, PUB_A)
    assert result.terminal_state is LifecycleState.INVALID
    assert result.selected_reader is None
    assert result.reason == "UNKNOWN_OR_HISTORICAL_LEDGER_CHECKPOINT"


@pytest.mark.taskb_checkpoint
def test_original_historical_graph_uses_only_historical_reader(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    _write_historical_graph(primary)
    validator = NoOpGraphValidator()
    result = _reader(primary, validator).classify(STUDY_ID, primary, PUB_A)
    assert result.terminal_state is LifecycleState.SUCCESS
    assert result.selected_reader is SelectedReader.HISTORICAL
    assert result.retry_disposition is RetryDisposition.RN
    assert ("validate_historical", ARTIFACT_FILENAMES) in validator.calls


@pytest.mark.taskb_reader
def test_unrelated_publication_residue_is_reported_not_composed(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    _install_publication(primary, stage="attempt")
    unrelated = _ledger_directory(primary, PUB_B)
    (unrelated / "attempt.json").write_bytes(b"not-json")

    result = _reader(primary).classify(STUDY_ID, primary, PUB_A)
    assert result.terminal_state is LifecycleState.ABORTED_BEFORE_PUBLICATION
    assert result.selected_reader is SelectedReader.AMENDED
    assert PUB_B in result.unrelated_publications


@pytest.mark.taskb_reader
@pytest.mark.parametrize("history", ["marker-without-attempt", "occupied-rx-target"])
def test_r0_requires_a_clean_complete_family(tmp_path: Path, history: str) -> None:
    primary = _primary(tmp_path)
    if history == "marker-without-attempt":
        unrelated = _ledger_directory(primary, PUB_B)
        (unrelated / "M11").write_bytes(b"{}\n")
    else:
        primary.with_name(f"{primary.name}.retry-{PUB_B}").mkdir()

    result = _reader(primary).classify(STUDY_ID, primary, PUB_A)

    assert result.terminal_state is LifecycleState.NEVER_PUBLISHED
    assert result.retry_disposition is RetryDisposition.RN
    assert result.reason is None


@pytest.mark.taskb_reader
def test_safely_observed_malformed_family_namespace_blocks_r0_without_read_failure(
    tmp_path: Path,
) -> None:
    primary = _primary(tmp_path)
    malformed = Path(f"{primary}.rde-attempts") / "not-a-publication-id"
    malformed.mkdir(parents=True)
    (malformed / "M11").write_bytes(b"{}\n")

    result = _reader(primary).classify(STUDY_ID, primary, PUB_A)

    assert result.terminal_state is LifecycleState.NEVER_PUBLISHED
    assert result.retry_disposition is RetryDisposition.RN
    assert result.reason is None


@pytest.mark.taskb_reader
def test_empty_family_directories_remain_operational_residue_for_r0(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    _ledger_directory(primary, PUB_B)

    result = _reader(primary).classify(STUDY_ID, primary, PUB_A)

    assert result.terminal_state is LifecycleState.NEVER_PUBLISHED
    assert result.retry_disposition is RetryDisposition.R0


@pytest.mark.taskb_reader
@pytest.mark.parametrize("unsafe_scope", ["canonical", "ledger-root", "attempt-directory"])
def test_stable_nonregular_selected_namespace_is_invalid(
    tmp_path: Path,
    unsafe_scope: str,
) -> None:
    primary = _primary(tmp_path)
    if unsafe_scope == "canonical":
        primary.write_bytes(b"not-a-directory")
        expected_reason = "INVALID_CANONICAL_NAMESPACE"
    else:
        paths = TargetPaths.from_target(primary, PUB_A, primary_target=primary)
        if unsafe_scope == "ledger-root":
            paths.ledger_root.write_bytes(b"not-a-directory")
        else:
            paths.ledger_root.mkdir()
            paths.attempt_directory.write_bytes(b"not-a-directory")
        expected_reason = "INVALID_LEDGER_NAMESPACE"

    result = _reader(primary).classify(STUDY_ID, primary, PUB_A)

    assert result.terminal_state is LifecycleState.INVALID
    assert result.retry_disposition is RetryDisposition.RN
    assert result.selected_reader is None
    assert result.reason == expected_reason


@pytest.mark.taskb_reader
def test_stable_nonregular_selected_final_is_invalid_ledger_namespace(
    tmp_path: Path,
) -> None:
    primary = _primary(tmp_path)
    _install_publication(primary, stage="attempt")
    paths = TargetPaths.from_target(primary, PUB_A, primary_target=primary)
    paths.attempt_file.unlink()
    paths.attempt_file.mkdir()

    result = _reader(primary).classify(STUDY_ID, primary, PUB_A)

    assert result.terminal_state is LifecycleState.INVALID
    assert result.retry_disposition is RetryDisposition.RN
    assert result.selected_reader is None
    assert result.reason == "INVALID_LEDGER_NAMESPACE"


@pytest.mark.taskb_reader
@pytest.mark.parametrize("selected", [True, False], ids=["selected", "family"])
def test_attempt_read_failure_propagates_without_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selected: bool,
) -> None:
    primary = _primary(tmp_path)
    _install_publication(primary, stage="attempt")
    failing_path = TargetPaths.from_target(
        primary,
        PUB_A,
        primary_target=primary,
    ).attempt_file
    if not selected:
        _install_publication(
            primary,
            publication_id=PUB_B,
            authorization_attempt_id=AUTH_B,
            stage="attempt",
        )
        failing_path = TargetPaths.from_target(
            primary,
            PUB_B,
            primary_target=primary,
        ).attempt_file
    original_read_bytes = Path.read_bytes

    def fail_selected(path: Path) -> bytes:
        if path == failing_path:
            raise PermissionError("injected attempt read failure")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_selected)

    expected_error = PermissionError if selected else UnsafePathError
    with pytest.raises(expected_error):
        _reader(primary).classify(STUDY_ID, primary, PUB_A)


@pytest.mark.taskb_reader
def test_stable_invalid_selected_namespace_still_inspects_complete_family(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = _primary(tmp_path)
    _install_publication(primary, stage="attempt")
    selected = TargetPaths.from_target(primary, PUB_A, primary_target=primary)
    (selected.attempt_directory / "unapproved-final").write_bytes(b"stable unsafe evidence")
    _install_publication(
        primary,
        publication_id=PUB_B,
        authorization_attempt_id=AUTH_B,
        stage="attempt",
    )
    unreadable = TargetPaths.from_target(primary, PUB_B, primary_target=primary).attempt_file
    original_read_bytes = Path.read_bytes

    def fail_family(path: Path) -> bytes:
        if path == unreadable:
            raise PermissionError("injected unrelated family read failure")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_family)

    with pytest.raises(UnsafePathError):
        _reader(primary).classify(STUDY_ID, primary, PUB_A)


@pytest.mark.taskb_reader
def test_unreadable_external_staging_is_operational_not_protocol_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = _primary(tmp_path)
    _install_publication(primary, stage="attempt")
    staging = StagingLayout.from_target(primary, PUB_A, primary_target=primary)
    staging.ensure_root()
    real_scandir = os.scandir

    def deny_staging(path: str | os.PathLike[str]) -> object:
        if Path(path) == staging.root:
            raise PermissionError("injected unreadable external staging")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", deny_staging)

    result = _reader(primary).classify(STUDY_ID, primary, PUB_A)

    assert result.terminal_state is LifecycleState.ABORTED_BEFORE_PUBLICATION
    assert result.retry_disposition is RetryDisposition.RX
    assert result.staging_residue == (staging.root.as_posix(),)


@pytest.mark.taskb_reader
def test_malformed_selected_marker_is_invalid(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    _install_publication(primary, stage="partial11")
    paths = TargetPaths.from_target(primary, PUB_A, primary_target=primary)
    (paths.attempt_directory / "M11").write_bytes(b'{"kind":"M11"}\n')
    result = _reader(primary).classify(STUDY_ID, primary, PUB_A)
    assert result.terminal_state is LifecycleState.INVALID
    assert result.selected_reader is SelectedReader.AMENDED
    assert result.reason == "INVALID"


@pytest.mark.taskb_reader
def test_empty_jsonl_checkpoint_anchor_is_invalid_not_unclassified(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    _install_publication(primary, stage="partial11")
    (primary / "arm_runs.jsonl").write_bytes(b"")

    result = _reader(primary).classify(STUDY_ID, primary, PUB_A)

    assert result.terminal_state is LifecycleState.INVALID
    assert result.selected_reader is SelectedReader.AMENDED
    assert result.retry_disposition is RetryDisposition.RN
    assert result.reason == "AMBIGUOUS_CROSS_ATTEMPT_ATTRIBUTION"


@pytest.mark.taskb_reader
def test_all_thirteen_and_m13_without_mf_is_not_success(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    _install_publication(primary, stage="recommendation")
    result = _reader(primary).classify(STUDY_ID, primary, PUB_A)
    assert result.terminal_state is LifecycleState.RECOMMENDATION_PUBLISHED_NOT_FINALIZED
    assert result.selected_reader is SelectedReader.AMENDED
    assert result.retry_disposition is RetryDisposition.RX
    assert result.canonical_inventory == ARTIFACT_FILENAMES


@pytest.mark.taskb_reader
def test_mf_with_failing_complete_graph_is_invalid(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    _install_publication(primary, stage="success")
    validator = NoOpGraphValidator(fail_13=True)
    result = _reader(primary, validator).classify(STUDY_ID, primary, PUB_A)
    assert result.terminal_state is LifecycleState.INVALID
    assert result.selected_reader is SelectedReader.AMENDED
    assert result.retry_disposition is RetryDisposition.RN
    assert any(operation == "validate_13" for operation, _ in validator.calls)


@pytest.mark.taskb_unique_success
def test_two_local_success_candidates_invalidate_both(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    root_attempt = _install_publication(primary, stage="success")
    child_target = primary.with_name(f"{primary.name}.retry-{PUB_B}")
    _install_publication(
        primary,
        target=child_target,
        publication_id=PUB_B,
        authorization_attempt_id=AUTH_B,
        stage="success",
        retry_source=(
            _canonical_target(primary, primary),
            PUB_A,
            AUTH_A,
            raw_sha256(root_attempt),
        ),
    )
    result = _reader(primary).classify(STUDY_ID, primary, PUB_A)
    assert result.terminal_state is LifecycleState.INVALID
    assert result.selected_reader is SelectedReader.AMENDED
    assert result.reason == "MULTIPLE_STUDY_SUCCESSES"
    assert result.retry_disposition is RetryDisposition.RN


@pytest.mark.taskb_reader
def test_mixed_publication_marker_cannot_complete_selected_attempt(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    attempt = _install_publication(primary, stage="partial11")
    artifacts = _artifact_map()
    foreign_envelope = make_binding_envelope(
        "M11",
        canonical_target=_canonical_target(primary, primary),
        publication_id=PUB_B,
        implementation_commit=IDENTITY.implementation_commit,
        implementation_tree_sha256=IDENTITY.implementation_tree_sha256,
        implementation_diff_sha256=IDENTITY.implementation_diff_sha256,
        authorization_attempt_id=AUTH_B,
    )
    foreign_m11 = build_m11_record(
        foreign_envelope,
        attempt_sha256=raw_sha256(attempt),
        artifacts_1_11=_artifact_hashes(artifacts, 11),
    )
    paths = TargetPaths.from_target(primary, PUB_A, primary_target=primary)
    (paths.attempt_directory / "M11").write_bytes(foreign_m11)

    result = _reader(primary).classify(STUDY_ID, primary, PUB_A)
    assert result.terminal_state is LifecycleState.INVALID
    assert result.selected_reader is SelectedReader.AMENDED
    assert result.retry_disposition is RetryDisposition.RN


@pytest.mark.taskb_authorization
def test_writer_active_has_no_terminal_classification(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    artifacts = _artifact_map()
    validator = NoOpGraphValidator()
    reader = _reader(primary, validator)
    authority = controlled_authority(
        primary,
        validator,
        IDENTITY,
    )
    prepared = authority.prepare(
        {name: artifacts[name] for name in ARTIFACT_FILENAMES[:11]}, IDENTITY
    )
    with authority.issue(prepared):
        result = reader.classify(STUDY_ID, primary, prepared.publication_id)
        assert result.operational is OperationalRead.WRITER_ACTIVE
        assert result.terminal_state is None
        assert result.selected_reader is None
        assert result.retry_disposition is None


@pytest.mark.taskb_authorization
def test_fake_copy_and_replay_reject_but_genuine_claim_succeeds(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    artifacts = _artifact_map()
    authority = controlled_authority(primary, NoOpGraphValidator(), IDENTITY)
    prepared = authority.prepare(
        {name: artifacts[name] for name in ARTIFACT_FILENAMES[:11]}, IDENTITY
    )
    with authority.issue(prepared) as issued:
        authorization = issued.authorization
        with pytest.raises(TypeError):
            copy.copy(authorization)
        with pytest.raises(TypeError):
            copy.deepcopy(authorization)
        with pytest.raises(ValueError, match="exact issued"):
            issued.claim(object())
        lookalike = AttemptAuthorization(AttemptAuthorization._construction_key)
        with pytest.raises(ValueError, match="forged|stale|copied|consumed"):
            issued.claim(lookalike)

        attempt = issued.claim(authorization)
        assert parse_canonical_ledger_bytes(attempt)["publication_id"] == prepared.publication_id
        with pytest.raises(ValueError, match="forged|stale|copied|consumed"):
            issued.claim(authorization)


@pytest.mark.taskb_authorization
def test_failed_genuine_claim_is_irreversibly_consumed(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    artifacts = _artifact_map()
    authority = controlled_authority(primary, NoOpGraphValidator(), IDENTITY)
    prepared = authority.prepare(
        {name: artifacts[name] for name in ARTIFACT_FILENAMES[:11]}, IDENTITY
    )
    with authority.issue(prepared) as issued:
        paths = TargetPaths.from_target(
            primary,
            prepared.publication_id,
            primary_target=primary,
        )
        paths.attempt_directory.mkdir(parents=True)
        existing = b"existing-final-must-not-be-overwritten"
        paths.attempt_file.write_bytes(existing)
        with pytest.raises(LifecycleInvariantError, match="history"):
            issued.claim(issued.authorization)
        assert paths.attempt_file.read_bytes() == existing
        with pytest.raises(ValueError, match="forged|stale|copied|consumed"):
            issued.claim(issued.authorization)
