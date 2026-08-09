from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from research_decision_engine.benchmarks.broader_lifecycle import (
    OPTIONAL_REPORT_NAME,
    AttemptAuthority,
    LifecycleInvariantError,
    LifecycleState,
    PreparedAttempt,
    RetryDisposition,
    RetrySource,
    SelectedReader,
)
from research_decision_engine.benchmarks.broader_lifecycle_io import (
    StagingLayout,
    TargetPaths,
    canonical_ledger_bytes,
    parse_canonical_ledger_bytes,
    raw_sha256,
    scan_lifecycle_namespace,
)
from research_decision_engine.benchmarks.broader_lifecycle_records import (
    ARTIFACT_FILENAMES,
    PROTOCOL_CHECKPOINT,
    SOURCE_DESIGN_CHECKPOINT,
    STUDY_ID,
    AttemptRecord,
    FailurePhase,
    FailureRecord,
    LifecycleRecordError,
    RetryKind,
    RetryTerminalResult,
    validate_record,
)
from tests.taskb_lifecycle_harness import controlled_authority
from tests.test_broader_lifecycle_crash import (
    AUTH_C,
    PUB_C,
    _add_failure,
    _install_bound_retry,
    _sculpt_publication,
)
from tests.test_broader_lifecycle_reader import (
    AUTH_A,
    AUTH_B,
    IDENTITY,
    PUB_A,
    PUB_B,
    NoOpGraphValidator,
    _artifact_map,
    _canonical_target,
    _install_publication,
    _ledger_directory,
    _primary,
    _reader,
)


def _authority(primary: Path) -> AttemptAuthority:
    return controlled_authority(primary, NoOpGraphValidator(), IDENTITY)


def _source_binding(
    primary: Path,
    attempt: bytes,
    failure: bytes | None,
    *,
    attempt_sha256: str | None = None,
    failure_sha256: str | None = None,
) -> RetrySource:
    return RetrySource(
        RetryKind.R1,
        _canonical_target(primary, primary),
        PUB_A,
        AUTH_A,
        attempt_sha256 or raw_sha256(attempt),
        failure_sha256
        if failure_sha256 is not None
        else (None if failure is None else raw_sha256(failure)),
        RetryTerminalResult.ABORTED_BEFORE_PUBLICATION,
    )


def _prepare_retry(authority: AttemptAuthority, source: RetrySource) -> PreparedAttempt:
    artifacts = _artifact_map()
    return authority.prepare(
        {name: artifacts[name] for name in ARTIFACT_FILENAMES[:11]},
        IDENTITY,
        retry_source=source,
    )


def _rewrite_source_attempt(primary: Path, field: str, value: object) -> bytes:
    path = TargetPaths.from_target(
        primary,
        PUB_A,
        primary_target=primary,
    ).attempt_file
    parsed = parse_canonical_ledger_bytes(path.read_bytes())
    assert isinstance(parsed, Mapping)
    mutated = dict(parsed)
    mutated[field] = value
    content = canonical_ledger_bytes(mutated)
    path.write_bytes(content)
    return content


@pytest.mark.taskb_retry
def test_missing_retry_source_is_invalid_and_cannot_be_inferred(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    child_target = primary.with_name(f"{primary.name}.retry-{PUB_B}")
    _install_bound_retry(
        primary,
        child_target,
        PUB_B,
        AUTH_B,
        source_target=primary,
        source_publication_id=PUB_A,
        source_authorization_attempt_id=AUTH_A,
        source_attempt_sha256="0" * 64,
        source_failure_sha256=None,
        stage="A",
    )

    child = _reader(primary).classify(STUDY_ID, child_target, PUB_B)
    assert child.selected_reader is SelectedReader.AMENDED
    assert child.terminal_state is LifecycleState.INVALID
    assert child.retry_disposition is RetryDisposition.RN
    assert child.reason == "INVALID_RETRY_SOURCE_BINDING"
    assert child.canonical_inventory == ()
    assert child.diagnostic_status == "NONE"


@pytest.mark.taskb_retry
@pytest.mark.parametrize("mismatch", ["attempt", "failure"])
def test_reader_rejects_retry_source_hash_mismatch(tmp_path: Path, mismatch: str) -> None:
    primary = _primary(tmp_path)
    source_attempt = _sculpt_publication(primary, "A")
    source_failure = _add_failure(primary, primary, PUB_A, "A")
    child_target = primary.with_name(f"{primary.name}.retry-{PUB_B}")
    _install_bound_retry(
        primary,
        child_target,
        PUB_B,
        AUTH_B,
        source_target=primary,
        source_publication_id=PUB_A,
        source_authorization_attempt_id=AUTH_A,
        source_attempt_sha256=("0" * 64 if mismatch == "attempt" else raw_sha256(source_attempt)),
        source_failure_sha256=("1" * 64 if mismatch == "failure" else raw_sha256(source_failure)),
        stage="A",
    )

    child = _reader(primary).classify(STUDY_ID, child_target, PUB_B)
    assert child.selected_reader is SelectedReader.AMENDED
    assert child.terminal_state is LifecycleState.INVALID
    assert child.retry_disposition is RetryDisposition.RN
    assert child.reason == "INVALID_RETRY_SOURCE_BINDING"
    assert child.canonical_inventory == ()
    assert child.diagnostic_status == "NONE"


@pytest.mark.taskb_retry
@pytest.mark.parametrize("mismatch", ["attempt", "failure"])
def test_authority_rejects_bad_source_hash_before_issuing_child(
    tmp_path: Path,
    mismatch: str,
) -> None:
    primary = _primary(tmp_path)
    source_attempt = _sculpt_publication(primary, "A")
    source_failure = _add_failure(primary, primary, PUB_A, "A")
    source = _source_binding(
        primary,
        source_attempt,
        source_failure,
        attempt_sha256="0" * 64 if mismatch == "attempt" else None,
        failure_sha256="1" * 64 if mismatch == "failure" else None,
    )
    authority = _authority(primary)
    prepared = _prepare_retry(authority, source)

    with pytest.raises(LifecycleInvariantError), authority.issue(prepared):
        pytest.fail("A mismatched source hash must not receive an authorization.")

    attempt_path = TargetPaths.from_target(
        prepared.target,
        prepared.publication_id,
        primary_target=primary,
    ).attempt_file
    assert not attempt_path.exists()


@pytest.mark.taskb_retry
@pytest.mark.parametrize(
    ("field", "foreign_value"),
    [
        ("study_id", "foreign-study"),
        ("protocol_checkpoint", "1" * 40),
    ],
    ids=["cross-study", "cross-checkpoint"],
)
def test_cross_scope_retry_source_is_rejected(
    tmp_path: Path,
    field: str,
    foreign_value: str,
) -> None:
    primary = _primary(tmp_path)
    _sculpt_publication(primary, "A")
    source_attempt = _rewrite_source_attempt(primary, field, foreign_value)
    source = _source_binding(primary, source_attempt, None)
    authority = _authority(primary)
    prepared = _prepare_retry(authority, source)

    source_result = _reader(primary).classify(STUDY_ID, primary, PUB_A)
    assert source_result.terminal_state is LifecycleState.INVALID
    assert source_result.retry_disposition is RetryDisposition.RN
    with pytest.raises((LifecycleInvariantError, LifecycleRecordError)), authority.issue(prepared):
        pytest.fail("A cross-scope source must not receive an authorization.")


@pytest.mark.taskb_retry
def test_one_valid_child_is_explicitly_bound_without_repairing_source(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    source_attempt = _sculpt_publication(primary, "A")
    source_failure = _add_failure(primary, primary, PUB_A, "A")
    source = _source_binding(primary, source_attempt, source_failure)
    authority = _authority(primary)
    prepared = _prepare_retry(authority, source)

    with authority.issue(prepared) as issued:
        child_attempt = issued.claim(issued.authorization)

    child_record = validate_record("attempt.json", child_attempt)
    assert isinstance(child_record, AttemptRecord)
    assert child_record.retry_kind is RetryKind.R1
    assert child_record.retry_of_publication_id == PUB_A
    assert child_record.retry_source_canonical_target == _canonical_target(primary, primary)
    assert child_record.retry_source_attempt_sha256 == raw_sha256(source_attempt)
    assert child_record.retry_source_failure_sha256 == raw_sha256(source_failure)
    assert child_record.retry_authorization_id == prepared.authorization_attempt_id
    assert child_record.envelope.publication_id == prepared.publication_id

    reader = _reader(primary)
    source_result = reader.classify(STUDY_ID, primary, PUB_A)
    child_result = reader.classify(
        STUDY_ID,
        prepared.target,
        prepared.publication_id,
    )
    assert source_result.selected_reader is SelectedReader.AMENDED
    assert source_result.terminal_state is LifecycleState.ABORTED_BEFORE_PUBLICATION
    assert source_result.retry_disposition is RetryDisposition.RN
    assert source_result.canonical_inventory == ()
    assert source_result.diagnostic_status == "VALID"
    assert child_result.selected_reader is SelectedReader.AMENDED
    assert child_result.terminal_state is LifecycleState.ABORTED_BEFORE_PUBLICATION
    assert child_result.retry_disposition is RetryDisposition.RX
    assert child_result.canonical_inventory == ()
    assert child_result.diagnostic_status == "NONE"


@pytest.mark.taskb_retry
def test_attempt_only_source_is_durably_closed_before_r1_child_issuance(
    tmp_path: Path,
) -> None:
    primary = _primary(tmp_path)
    source_attempt = _sculpt_publication(primary, "A")
    source = _source_binding(primary, source_attempt, None)
    authority = _authority(primary)
    prepared = _prepare_retry(authority, source)

    with authority.issue(prepared) as issued:
        child_attempt = issued.claim(issued.authorization)
        bound_source = issued.prepared.retry_source

    source_failure_path = (
        TargetPaths.from_target(primary, PUB_A, primary_target=primary).attempt_directory
        / "failure.json"
    )
    source_failure = source_failure_path.read_bytes()
    failure_record = validate_record("failure.json", source_failure)
    child_record = validate_record("attempt.json", child_attempt)
    assert isinstance(failure_record, FailureRecord)
    assert failure_record.phase is FailurePhase.RECOVERY
    assert isinstance(child_record, AttemptRecord)
    assert child_record.retry_kind is RetryKind.R1
    assert child_record.retry_source_failure_sha256 == raw_sha256(source_failure)
    assert bound_source is not None
    assert bound_source.failure_sha256 == raw_sha256(source_failure)
    assert issued.prepared.target == primary


@pytest.mark.taskb_retry
def test_fresh_target_rx_is_rejected_when_safe_r1_placement_is_available(
    tmp_path: Path,
) -> None:
    primary = _primary(tmp_path)
    source_attempt = _sculpt_publication(primary, "A")
    source_failure = _add_failure(primary, primary, PUB_A, "A")
    source = RetrySource(
        RetryKind.RX,
        _canonical_target(primary, primary),
        PUB_A,
        AUTH_A,
        raw_sha256(source_attempt),
        raw_sha256(source_failure),
        RetryTerminalResult.ABORTED_BEFORE_PUBLICATION,
    )
    authority = _authority(primary)
    prepared = _prepare_retry(authority, source)

    with (
        pytest.raises(LifecycleInvariantError, match="R1 placement"),
        authority.issue(prepared),
    ):
        pytest.fail("A safe attempt-only source must use issuer-selected R1 placement.")

    attempt = TargetPaths.from_target(
        prepared.target,
        prepared.publication_id,
        primary_target=primary,
    ).attempt_file
    assert not attempt.exists()


@pytest.mark.taskb_retry
def test_benign_external_staging_does_not_justify_fresh_target_rx(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    source_attempt = _sculpt_publication(primary, "A")
    source_failure = _add_failure(primary, primary, PUB_A, "A")
    source_staging = StagingLayout.from_target(
        primary,
        PUB_A,
        primary_target=primary,
    )
    source_staging.ensure_root()
    source_staging.stage_m11.write_bytes(b"benign operational staging")
    source = RetrySource(
        RetryKind.RX,
        _canonical_target(primary, primary),
        PUB_A,
        AUTH_A,
        raw_sha256(source_attempt),
        raw_sha256(source_failure),
        RetryTerminalResult.ABORTED_BEFORE_PUBLICATION,
    )
    authority = _authority(primary)
    prepared = _prepare_retry(authority, source)

    assert scan_lifecycle_namespace(primary).unsafe_staging_publications == ()
    with (
        pytest.raises(LifecycleInvariantError, match="R1 placement"),
        authority.issue(prepared),
    ):
        pytest.fail("Benign staging must not make fresh-target placement eligible.")


@pytest.mark.taskb_retry
def test_unsafe_stage_failure_blocks_r1_and_permits_fresh_target_rx(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    source_attempt = _sculpt_publication(primary, "A")
    source_staging = StagingLayout.from_target(
        primary,
        PUB_A,
        primary_target=primary,
    )
    source_staging.ensure_root()
    source_staging.stage_failure.mkdir()
    authority = _authority(primary)
    r1_source = _source_binding(primary, source_attempt, None)
    r1_prepared = _prepare_retry(authority, r1_source)

    namespace = scan_lifecycle_namespace(primary)
    assert namespace.unsafe_staging_publications == (source_staging.root,)
    with (
        pytest.raises(LifecycleInvariantError, match="R1 placement"),
        authority.issue(r1_prepared),
    ):
        pytest.fail("A nonregular failure stage must block same-target R1 placement.")

    rx_source = RetrySource(
        RetryKind.RX,
        _canonical_target(primary, primary),
        PUB_A,
        AUTH_A,
        raw_sha256(source_attempt),
        None,
        RetryTerminalResult.ABORTED_BEFORE_PUBLICATION,
    )
    rx_prepared = _prepare_retry(authority, rx_source)
    with authority.issue(rx_prepared) as issued:
        child_attempt_bytes = issued.claim(issued.authorization)

    child_attempt = validate_record("attempt.json", child_attempt_bytes)
    assert isinstance(child_attempt, AttemptRecord)
    assert child_attempt.retry_kind is RetryKind.RX
    assert child_attempt.retry_of_publication_id == PUB_A
    assert rx_prepared.target != primary
    assert not (
        TargetPaths.from_target(primary, PUB_A, primary_target=primary).attempt_directory
        / "failure.json"
    ).exists()


@pytest.mark.taskb_retry
def test_unremovable_regular_stage_failure_permits_fresh_target_rx(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = _primary(tmp_path)
    source_attempt = _sculpt_publication(primary, "A")
    source_staging = StagingLayout.from_target(
        primary,
        PUB_A,
        primary_target=primary,
    )
    source_staging.ensure_root()
    source_staging.stage_failure.write_bytes(b"ordinary but unremovable residue")
    real_unlink = Path.unlink

    def refuse_source_reset(path: Path, missing_ok: bool = False) -> None:
        if path == source_staging.stage_failure:
            raise PermissionError("injected unremovable failure stage")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", refuse_source_reset)
    source = RetrySource(
        RetryKind.RX,
        _canonical_target(primary, primary),
        PUB_A,
        AUTH_A,
        raw_sha256(source_attempt),
        None,
        RetryTerminalResult.ABORTED_BEFORE_PUBLICATION,
    )
    authority = _authority(primary)
    prepared = _prepare_retry(authority, source)

    with authority.issue(prepared) as issued:
        child_attempt_bytes = issued.claim(issued.authorization)

    child_attempt = validate_record("attempt.json", child_attempt_bytes)
    assert isinstance(child_attempt, AttemptRecord)
    assert child_attempt.retry_kind is RetryKind.RX
    assert child_attempt.retry_source_failure_sha256 is None
    assert source_staging.stage_failure.read_bytes() == b"ordinary but unremovable residue"


@pytest.mark.taskb_retry
def test_other_unsafe_attributable_stage_blocks_r1_but_allows_fresh_rx(
    tmp_path: Path,
) -> None:
    primary = _primary(tmp_path)
    source_attempt = _sculpt_publication(primary, "A")
    source_failure = _add_failure(primary, primary, PUB_A, "A")
    source_staging = StagingLayout.from_target(
        primary,
        PUB_A,
        primary_target=primary,
    )
    source_staging.ensure_root()
    source_staging.stage_m11.mkdir()
    authority = _authority(primary)
    source = RetrySource(
        RetryKind.RX,
        _canonical_target(primary, primary),
        PUB_A,
        AUTH_A,
        raw_sha256(source_attempt),
        raw_sha256(source_failure),
        RetryTerminalResult.ABORTED_BEFORE_PUBLICATION,
    )
    prepared = _prepare_retry(authority, source)

    with authority.issue(prepared) as issued:
        child_attempt_bytes = issued.claim(issued.authorization)

    child_attempt = validate_record("attempt.json", child_attempt_bytes)
    assert isinstance(child_attempt, AttemptRecord)
    assert child_attempt.retry_kind is RetryKind.RX
    assert child_attempt.retry_source_failure_sha256 == raw_sha256(source_failure)
    assert source_staging.stage_m11.is_dir()


@pytest.mark.taskb_retry
def test_unsafe_preauthorization_staging_cannot_justify_fresh_rx(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    source_attempt = _sculpt_publication(primary, "A")
    source_failure = _add_failure(primary, primary, PUB_A, "A")
    unbound_staging = StagingLayout.from_target(
        primary,
        PUB_B,
        primary_target=primary,
    )
    unbound_staging.ensure_root()
    unbound_staging.stage_m11.mkdir()
    source = RetrySource(
        RetryKind.RX,
        _canonical_target(primary, primary),
        PUB_A,
        AUTH_A,
        raw_sha256(source_attempt),
        raw_sha256(source_failure),
        RetryTerminalResult.ABORTED_BEFORE_PUBLICATION,
    )
    authority = _authority(primary)
    prepared = _prepare_retry(authority, source)

    with (
        pytest.raises(LifecycleInvariantError, match="not attributable"),
        authority.issue(prepared),
    ):
        pytest.fail("Unsafe staging without a durable valid attempt must fail closed.")

    assert not TargetPaths.from_target(
        prepared.target,
        prepared.publication_id,
        primary_target=primary,
    ).attempt_file.exists()


@pytest.mark.taskb_retry
def test_fresh_rx_report_only_target_collision_is_rejected_before_authorization(
    tmp_path: Path,
) -> None:
    primary = _primary(tmp_path)
    source_attempt = _sculpt_publication(primary, "M12")
    source = RetrySource(
        RetryKind.RX,
        _canonical_target(primary, primary),
        PUB_A,
        AUTH_A,
        raw_sha256(source_attempt),
        None,
        RetryTerminalResult.MANIFEST_PUBLISHED_INCOMPLETE,
    )
    authority = _authority(primary)
    prepared = _prepare_retry(authority, source)
    prepared.target.mkdir()
    report = prepared.target / OPTIONAL_REPORT_NAME
    report.write_text("optional report only\n", encoding="utf-8")

    with (
        pytest.raises(LifecycleInvariantError, match="physically absent"),
        authority.issue(prepared),
    ):
        pytest.fail("A report-only RX target must not receive an authorization.")

    paths = TargetPaths.from_target(
        prepared.target,
        prepared.publication_id,
        primary_target=primary,
    )
    assert not paths.attempt_file.exists()
    assert {entry.name for entry in prepared.target.iterdir()} == {OPTIONAL_REPORT_NAME}
    source_result = _reader(primary).classify(STUDY_ID, primary, PUB_A)
    candidate_result = _reader(primary).classify(
        STUDY_ID,
        prepared.target,
        prepared.publication_id,
    )
    assert source_result.terminal_state is LifecycleState.MANIFEST_PUBLISHED_INCOMPLETE
    assert source_result.retry_disposition is RetryDisposition.RX
    assert candidate_result.terminal_state is LifecycleState.NEVER_PUBLISHED
    assert candidate_result.retry_disposition is RetryDisposition.RN


@pytest.mark.taskb_unique_success
@pytest.mark.taskb_retry
def test_same_target_r1_child_owns_canonical_success_without_repairing_source(
    tmp_path: Path,
) -> None:
    primary = _primary(tmp_path)
    source_attempt = _sculpt_publication(primary, "A")
    source_failure = _add_failure(primary, primary, PUB_A, "A")
    source = _source_binding(primary, source_attempt, source_failure)
    authority = _authority(primary)
    prepared = _prepare_retry(authority, source)
    artifacts = _artifact_map()

    result = authority.finalize(
        prepared,
        manifest_builder=lambda _first_eleven: artifacts["run_manifest.json"],
        recommendation_builder=lambda _first_twelve: artifacts["recommendation.json"],
    )

    assert tuple(result) == ARTIFACT_FILENAMES
    reader = _reader(primary)
    parent = reader.classify(STUDY_ID, primary, PUB_A)
    child = reader.classify(STUDY_ID, primary, prepared.publication_id)
    assert parent.terminal_state is LifecycleState.ABORTED_BEFORE_PUBLICATION
    assert parent.retry_disposition is RetryDisposition.RN
    assert parent.canonical_inventory == ()
    assert child.terminal_state is LifecycleState.SUCCESS
    assert child.retry_disposition is RetryDisposition.RN
    assert child.canonical_inventory == ARTIFACT_FILENAMES


@pytest.mark.taskb_retry
def test_parseable_noncanonical_allegation_blocks_another_child_without_becoming_edge(
    tmp_path: Path,
) -> None:
    primary = _primary(tmp_path)
    source_attempt = _sculpt_publication(primary, "A")
    source_failure = _add_failure(primary, primary, PUB_A, "A")
    child_target = primary.with_name(f"{primary.name}.retry-{PUB_B}")
    _install_bound_retry(
        primary,
        child_target,
        PUB_B,
        AUTH_B,
        source_target=primary,
        source_publication_id=PUB_A,
        source_authorization_attempt_id=AUTH_A,
        source_attempt_sha256=raw_sha256(source_attempt),
        source_failure_sha256=raw_sha256(source_failure),
        stage="A",
    )
    child_path = TargetPaths.from_target(
        child_target,
        PUB_B,
        primary_target=primary,
    ).attempt_file
    value = parse_canonical_ledger_bytes(child_path.read_bytes())
    child_path.write_text(json.dumps(value, indent=2), encoding="utf-8", newline="\n")

    reader = _reader(primary)
    parent = reader.classify(STUDY_ID, primary, PUB_A)
    child = reader.classify(STUDY_ID, child_target, PUB_B)
    assert parent.terminal_state is LifecycleState.ABORTED_BEFORE_PUBLICATION
    assert parent.retry_disposition is RetryDisposition.RN
    assert child.terminal_state is LifecycleState.INVALID
    assert child.retry_disposition is RetryDisposition.RN


@pytest.mark.taskb_retry
def test_partial_retry_tuple_precedes_multiple_allegation_reason(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    source_attempt = _sculpt_publication(primary, "A")
    source_failure = _add_failure(primary, primary, PUB_A, "A")
    complete_target = primary.with_name(f"{primary.name}.retry-{PUB_B}")
    partial_target = primary.with_name(f"{primary.name}.retry-{PUB_C}")
    for target, publication_id, authorization_id in (
        (complete_target, PUB_B, AUTH_B),
        (partial_target, PUB_C, AUTH_C),
    ):
        _install_bound_retry(
            primary,
            target,
            publication_id,
            authorization_id,
            source_target=primary,
            source_publication_id=PUB_A,
            source_authorization_attempt_id=AUTH_A,
            source_attempt_sha256=raw_sha256(source_attempt),
            source_failure_sha256=raw_sha256(source_failure),
            stage="A",
        )
    partial_attempt = TargetPaths.from_target(
        partial_target,
        PUB_C,
        primary_target=primary,
    ).attempt_file
    value = parse_canonical_ledger_bytes(partial_attempt.read_bytes())
    assert isinstance(value, dict)
    value["retry_source_attempt_sha256"] = None
    partial_attempt.write_bytes(canonical_ledger_bytes(value))

    reader = _reader(primary)
    source = reader.classify(STUDY_ID, primary, PUB_A)
    complete = reader.classify(STUDY_ID, complete_target, PUB_B)
    partial = reader.classify(STUDY_ID, partial_target, PUB_C)

    assert source.terminal_state is LifecycleState.INVALID
    assert source.reason == "MULTIPLE_RETRY_CHILDREN"
    assert complete.terminal_state is LifecycleState.INVALID
    assert complete.reason == "MULTIPLE_RETRY_CHILDREN"
    assert partial.terminal_state is LifecycleState.INVALID
    assert partial.reason == "INVALID_RETRY_SOURCE_BINDING"
    assert all(
        result.retry_disposition is RetryDisposition.RN for result in (source, complete, partial)
    )


@pytest.mark.taskb_retry
def test_multiple_allegation_precedes_complete_retry_placement_defect(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    source_attempt = _sculpt_publication(primary, "A")
    source_failure = _add_failure(primary, primary, PUB_A, "A")
    valid_target = primary.with_name(f"{primary.name}.retry-{PUB_B}")
    misplaced_target = primary.with_name(f"{primary.name}.retry-{PUB_C}")
    for target, publication_id, authorization_id in (
        (valid_target, PUB_B, AUTH_B),
        (misplaced_target, PUB_C, AUTH_C),
    ):
        _install_bound_retry(
            primary,
            target,
            publication_id,
            authorization_id,
            source_target=primary,
            source_publication_id=PUB_A,
            source_authorization_attempt_id=AUTH_A,
            source_attempt_sha256=raw_sha256(source_attempt),
            source_failure_sha256=raw_sha256(source_failure),
            stage="A",
        )
    misplaced_attempt = TargetPaths.from_target(
        misplaced_target,
        PUB_C,
        primary_target=primary,
    ).attempt_file
    value = parse_canonical_ledger_bytes(misplaced_attempt.read_bytes())
    assert isinstance(value, dict)
    value["retry_kind"] = RetryKind.R1.value
    misplaced_attempt.write_bytes(canonical_ledger_bytes(value))

    reader = _reader(primary)
    source = reader.classify(STUDY_ID, primary, PUB_A)
    valid = reader.classify(STUDY_ID, valid_target, PUB_B)
    misplaced = reader.classify(STUDY_ID, misplaced_target, PUB_C)

    for result in (source, valid, misplaced):
        assert result.terminal_state is LifecycleState.INVALID
        assert result.retry_disposition is RetryDisposition.RN
        assert result.reason == "MULTIPLE_RETRY_CHILDREN"


@pytest.mark.taskb_retry
def test_multiple_allegation_needs_source_scope_not_full_source_validity(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    _sculpt_publication(primary, "A")
    source_path = TargetPaths.from_target(primary, PUB_A, primary_target=primary).attempt_file
    source_value = parse_canonical_ledger_bytes(source_path.read_bytes())
    assert isinstance(source_value, dict)
    source_value["unexpected_source_field"] = "structural defect after fixed scope"
    source_attempt = canonical_ledger_bytes(source_value)
    source_path.write_bytes(source_attempt)

    children = (
        (primary.with_name(f"{primary.name}.retry-{PUB_B}"), PUB_B, AUTH_B),
        (primary.with_name(f"{primary.name}.retry-{PUB_C}"), PUB_C, AUTH_C),
    )
    for target, publication_id, authorization_id in children:
        _install_bound_retry(
            primary,
            target,
            publication_id,
            authorization_id,
            source_target=primary,
            source_publication_id=PUB_A,
            source_authorization_attempt_id=AUTH_A,
            source_attempt_sha256=raw_sha256(source_attempt),
            source_failure_sha256=None,
            stage="A",
        )

    reader = _reader(primary)
    for target, publication_id, _authorization_id in children:
        child = reader.classify(STUDY_ID, target, publication_id)
        assert child.terminal_state is LifecycleState.INVALID
        assert child.retry_disposition is RetryDisposition.RN
        assert child.reason == "MULTIPLE_RETRY_CHILDREN"


@pytest.mark.taskb_retry
@pytest.mark.parametrize("reused_id", ["publication", "authorization"])
def test_descendant_cannot_reuse_an_admitted_ancestor_identifier(
    tmp_path: Path,
    reused_id: str,
) -> None:
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
    descendant_publication = PUB_A if reused_id == "publication" else PUB_C
    descendant_authorization = AUTH_C if reused_id == "publication" else AUTH_A
    descendant_target = primary.with_name(f"{primary.name}.retry-{descendant_publication}")
    _install_bound_retry(
        primary,
        descendant_target,
        descendant_publication,
        descendant_authorization,
        source_target=child_target,
        source_publication_id=PUB_B,
        source_authorization_attempt_id=AUTH_B,
        source_attempt_sha256=raw_sha256(child_attempt),
        source_failure_sha256=None,
        stage="A",
    )

    reader = _reader(primary)
    root = reader.classify(STUDY_ID, primary, PUB_A)
    child = reader.classify(STUDY_ID, child_target, PUB_B)
    descendant = reader.classify(
        STUDY_ID,
        descendant_target,
        descendant_publication,
    )

    assert root.terminal_state is LifecycleState.ABORTED_BEFORE_PUBLICATION
    assert child.terminal_state is LifecycleState.ABORTED_BEFORE_PUBLICATION
    assert root.retry_disposition is RetryDisposition.RN
    assert child.retry_disposition is RetryDisposition.RN
    assert descendant.terminal_state is LifecycleState.INVALID
    assert descendant.retry_disposition is RetryDisposition.RN
    assert descendant.reason == "INVALID_RETRY_SOURCE_BINDING"


@pytest.mark.taskb_retry
def test_malformed_same_target_history_is_rn_not_automatic_rx(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    _sculpt_publication(primary, "A")
    _add_failure(primary, primary, PUB_A, "A")
    malformed = _ledger_directory(primary, PUB_B)
    (malformed / "M11").write_bytes(b"{}\n")

    result = _reader(primary).classify(STUDY_ID, primary, PUB_A)

    assert result.terminal_state is LifecycleState.ABORTED_BEFORE_PUBLICATION
    assert result.retry_disposition is RetryDisposition.RN
    assert result.reason is None


@pytest.mark.taskb_retry
def test_unapproved_same_target_history_is_rn_not_a_reader_exception(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    _sculpt_publication(primary, "A")
    _add_failure(primary, primary, PUB_A, "A")
    malformed = _ledger_directory(primary, PUB_B)
    (malformed / "unapproved-final").write_bytes(b"safe-but-unapproved")

    result = _reader(primary).classify(STUDY_ID, primary, PUB_A)

    assert result.terminal_state is LifecycleState.ABORTED_BEFORE_PUBLICATION
    assert result.retry_disposition is RetryDisposition.RN
    assert result.reason is None


@pytest.mark.taskb_retry
def test_unadmitted_same_target_closed_retry_history_blocks_r1(
    tmp_path: Path,
) -> None:
    primary = _primary(tmp_path)
    source_attempt = _sculpt_publication(primary, "A")
    source_failure = _add_failure(primary, primary, PUB_A, "A")
    _install_publication(
        primary,
        publication_id=PUB_B,
        authorization_attempt_id=AUTH_B,
        stage="attempt",
    )
    unadmitted_path = TargetPaths.from_target(
        primary,
        PUB_B,
        primary_target=primary,
    ).attempt_file
    value = parse_canonical_ledger_bytes(unadmitted_path.read_bytes())
    assert isinstance(value, dict)
    value.update(
        {
            "retry_kind": RetryKind.R1.value,
            "retry_of_publication_id": PUB_C,
            "retry_source_canonical_target": _canonical_target(primary, primary),
            "retry_source_authorization_attempt_id": AUTH_C,
            "retry_source_attempt_sha256": "1" * 64,
            "retry_source_failure_sha256": "2" * 64,
            "retry_source_terminal_result": RetryTerminalResult.ABORTED_BEFORE_PUBLICATION.value,
            "retry_authorization_id": AUTH_B,
        }
    )
    unadmitted_path.write_bytes(canonical_ledger_bytes(value))
    _add_failure(primary, primary, PUB_B, "A")

    result = _reader(primary).classify(STUDY_ID, primary, PUB_A)
    assert result.terminal_state is LifecycleState.ABORTED_BEFORE_PUBLICATION
    assert result.retry_disposition is RetryDisposition.RN

    authority = _authority(primary)
    prepared = _prepare_retry(
        authority,
        _source_binding(primary, source_attempt, source_failure),
    )
    with pytest.raises(LifecycleInvariantError), authority.issue(prepared):
        pytest.fail("Unadmitted same-target history must block R1 authorization issuance.")


@pytest.mark.taskb_retry
@pytest.mark.parametrize(
    ("field", "foreign_value"),
    [("study_id", "foreign-study"), ("protocol_checkpoint", "1" * 40)],
)
def test_valid_foreign_scope_i0_history_is_unrelated_to_r1(
    tmp_path: Path,
    field: str,
    foreign_value: str,
) -> None:
    primary = _primary(tmp_path)
    source_attempt = _sculpt_publication(primary, "A")
    source_failure = _add_failure(primary, primary, PUB_A, "A")
    _install_publication(
        primary,
        publication_id=PUB_B,
        authorization_attempt_id=AUTH_B,
        stage="attempt",
    )
    foreign_attempt = TargetPaths.from_target(
        primary,
        PUB_B,
        primary_target=primary,
    ).attempt_file
    value = parse_canonical_ledger_bytes(foreign_attempt.read_bytes())
    assert isinstance(value, dict)
    value[field] = foreign_value
    foreign_attempt.write_bytes(canonical_ledger_bytes(value))

    reader_result = _reader(primary).classify(STUDY_ID, primary, PUB_A)
    assert reader_result.terminal_state is LifecycleState.ABORTED_BEFORE_PUBLICATION
    assert reader_result.retry_disposition is RetryDisposition.RX
    assert PUB_B in reader_result.unrelated_publications

    authority = _authority(primary)
    prepared = _prepare_retry(
        authority,
        _source_binding(primary, source_attempt, source_failure),
    )
    with authority.issue(prepared) as issued:
        attempt_bytes = issued.claim(issued.authorization)
    attempt = validate_record("attempt.json", attempt_bytes)
    assert isinstance(attempt, AttemptRecord)
    assert attempt.retry_kind is RetryKind.R1


@pytest.mark.taskb_retry
def test_two_local_all_null_roots_admit_neither_publication(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    _install_publication(primary, publication_id=PUB_A, authorization_attempt_id=AUTH_A)
    _install_publication(primary, publication_id=PUB_B, authorization_attempt_id=AUTH_B)

    reader = _reader(primary)
    first = reader.classify(STUDY_ID, primary, PUB_A)
    second = reader.classify(STUDY_ID, primary, PUB_B)
    for result in (first, second):
        assert result.terminal_state is LifecycleState.INVALID
        assert result.retry_disposition is RetryDisposition.RN
        assert result.selected_reader is SelectedReader.AMENDED
        assert result.canonical_inventory == ()


@pytest.mark.taskb_retry
def test_zero_independent_owner_claim_is_ambiguous_not_chronological(
    tmp_path: Path,
) -> None:
    primary = _primary(tmp_path)
    _sculpt_publication(primary, "A")
    _add_failure(primary, primary, PUB_A, "A")
    primary.mkdir()
    mismatched = _artifact_map()
    mismatched[ARTIFACT_FILENAMES[0]] = (
        json.dumps(
            {"source_checkpoint_identifier": PROTOCOL_CHECKPOINT, "unowned": True},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    for name in ARTIFACT_FILENAMES[:11]:
        (primary / name).write_bytes(mismatched[name])

    result = _reader(primary).classify(STUDY_ID, primary, PUB_A)
    assert result.terminal_state is LifecycleState.INVALID
    assert result.retry_disposition is RetryDisposition.RN
    assert result.reason == "AMBIGUOUS_CROSS_ATTEMPT_ATTRIBUTION"


@pytest.mark.taskb_retry
def test_later_historical_p0_owner_is_excluded_from_p1_source_inventory(
    tmp_path: Path,
) -> None:
    primary = _primary(tmp_path)
    _sculpt_publication(primary, "A")
    _add_failure(primary, primary, PUB_A, "A")
    historical = _artifact_map(SOURCE_DESIGN_CHECKPOINT)
    primary.mkdir()
    for name in ARTIFACT_FILENAMES:
        (primary / name).write_bytes(historical[name])

    reader = _reader(primary)
    source = reader.classify(STUDY_ID, primary, PUB_A)
    historical_result = reader.classify(STUDY_ID, primary, PUB_B)
    assert source.terminal_state is LifecycleState.ABORTED_BEFORE_PUBLICATION
    assert source.retry_disposition is RetryDisposition.RN
    assert source.canonical_inventory == ()
    assert historical_result.terminal_state is LifecycleState.SUCCESS
    assert historical_result.selected_reader is SelectedReader.HISTORICAL
    assert historical_result.canonical_inventory == ARTIFACT_FILENAMES


@pytest.mark.taskb_retry
def test_two_alleged_children_make_attribution_invalid(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    source_attempt = _sculpt_publication(primary, "A")
    source_failure = _add_failure(primary, primary, PUB_A, "A")
    children = (
        (
            primary.with_name(f"{primary.name}.retry-{PUB_B}"),
            PUB_B,
            AUTH_B,
        ),
        (
            primary.with_name(f"{primary.name}.retry-{PUB_C}"),
            PUB_C,
            AUTH_C,
        ),
    )
    for target, publication_id, authorization_attempt_id in children:
        _install_bound_retry(
            primary,
            target,
            publication_id,
            authorization_attempt_id,
            source_target=primary,
            source_publication_id=PUB_A,
            source_authorization_attempt_id=AUTH_A,
            source_attempt_sha256=raw_sha256(source_attempt),
            source_failure_sha256=raw_sha256(source_failure),
            stage="A",
        )

    reader = _reader(primary)
    source_result = reader.classify(STUDY_ID, primary, PUB_A)
    assert source_result.selected_reader is SelectedReader.AMENDED
    assert source_result.terminal_state is LifecycleState.INVALID
    assert source_result.retry_disposition is RetryDisposition.RN
    assert source_result.canonical_inventory == ()
    assert source_result.diagnostic_status == "VALID"
    for target, publication_id, _ in children:
        child = reader.classify(STUDY_ID, target, publication_id)
        assert child.selected_reader is SelectedReader.AMENDED
        assert child.terminal_state is LifecycleState.INVALID
        assert child.retry_disposition is RetryDisposition.RN
        assert child.canonical_inventory == ()
        assert child.diagnostic_status == "NONE"


@pytest.mark.taskb_retry
def test_later_unrelated_publication_does_not_gain_ownership_by_chronology(
    tmp_path: Path,
) -> None:
    primary = _primary(tmp_path)
    source_attempt = _sculpt_publication(primary, "A")
    source_failure = _add_failure(primary, primary, PUB_A, "A")
    unrelated_target = primary.with_name(f"{primary.name}.retry-{PUB_B}")
    missing_source_target = primary.with_name(f"{primary.name}.retry-{PUB_C}")
    _install_bound_retry(
        primary,
        unrelated_target,
        PUB_B,
        AUTH_B,
        source_target=missing_source_target,
        source_publication_id=PUB_C,
        source_authorization_attempt_id=AUTH_C,
        source_attempt_sha256="2" * 64,
        source_failure_sha256=None,
        stage="A",
    )

    reader = _reader(primary)
    source_result = reader.classify(STUDY_ID, primary, PUB_A)
    unrelated_result = reader.classify(STUDY_ID, unrelated_target, PUB_B)
    assert source_result.selected_reader is SelectedReader.AMENDED
    assert source_result.terminal_state is LifecycleState.ABORTED_BEFORE_PUBLICATION
    assert source_result.retry_disposition is RetryDisposition.RX
    assert source_result.canonical_inventory == ()
    assert source_result.diagnostic_status == "VALID"
    assert source_result.unrelated_publications == (PUB_B,)
    assert unrelated_result.terminal_state is LifecycleState.INVALID
    assert unrelated_result.retry_disposition is RetryDisposition.RN
    assert raw_sha256(
        TargetPaths.from_target(primary, PUB_A, primary_target=primary).attempt_file.read_bytes()
    ) == raw_sha256(source_attempt)
    assert raw_sha256(
        (
            TargetPaths.from_target(primary, PUB_A, primary_target=primary).attempt_directory
            / "failure.json"
        ).read_bytes()
    ) == raw_sha256(source_failure)


@pytest.mark.taskb_retry
def test_existing_study_success_blocks_retry_authorization_and_new_publication(
    tmp_path: Path,
) -> None:
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
        stage="MF",
    )
    source = _source_binding(primary, source_attempt, source_failure)
    authority = _authority(primary)
    prepared = _prepare_retry(authority, source)

    reader = _reader(primary)
    source_result = reader.classify(STUDY_ID, primary, PUB_A)
    winner_result = reader.classify(STUDY_ID, winner_target, PUB_B)
    assert source_result.terminal_state is LifecycleState.ABORTED_BEFORE_PUBLICATION
    assert source_result.retry_disposition is RetryDisposition.RN
    assert winner_result.terminal_state is LifecycleState.SUCCESS
    assert winner_result.retry_disposition is RetryDisposition.RN
    assert winner_result.canonical_inventory == ARTIFACT_FILENAMES
    with (
        pytest.raises(LifecycleInvariantError, match="Study SUCCESS prohibits"),
        authority.issue(prepared),
    ):
        pytest.fail("Existing study SUCCESS must prohibit a retry authorization.")

    absent = reader.classify(STUDY_ID, prepared.target, prepared.publication_id)
    assert absent.selected_reader is None
    assert absent.terminal_state is LifecycleState.NEVER_PUBLISHED
    assert absent.retry_disposition is RetryDisposition.RN
    assert absent.canonical_inventory == ()
    assert absent.diagnostic_status == "NONE"
