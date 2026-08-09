from __future__ import annotations

import multiprocessing
import os
from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError
from pathlib import Path
from queue import Empty

import pytest

import research_decision_engine.benchmarks.broader_lifecycle_io as lifecycle_io
from research_decision_engine.benchmarks.broader_lifecycle_io import (
    CanonicalLedgerError,
    DurabilityError,
    ExistingDestinationError,
    NamespaceIdentifierScan,
    NamespaceScanError,
    PublicationValidationError,
    StagingLayout,
    StudyLock,
    TargetPaths,
    UnsafePathError,
    canonical_json_bytes,
    canonical_ledger_bytes,
    ensure_ordinary_directory_durable,
    is_path_within,
    normalize_target,
    ordinary_directory,
    ordinary_file,
    parse_canonical_ledger_bytes,
    publish_bytes_no_replace,
    publish_directory_bytes_no_replace,
    publish_staged_directory_no_replace,
    raw_sha256,
    scan_lifecycle_namespace,
    validate_authorization_attempt_id,
    validate_ledger_final_name,
    validate_publication_id,
)

PUBLICATION_ID = "publication-" + "1" * 64
AUTHORIZATION_ATTEMPT_ID = "authorization-attempt-" + "2" * 64


def _publication_id(character: str) -> str:
    return "publication-" + character * 64


def _authorization_attempt_id(character: str) -> str:
    return "authorization-attempt-" + character * 64


def _race_publish(
    staging: str,
    destination: str,
    content: bytes,
    gate: multiprocessing.synchronize.Event,
    result_queue: multiprocessing.queues.Queue[tuple[str, str]],
) -> None:
    gate.wait(timeout=10)
    try:
        publish_bytes_no_replace(staging, destination, content)
    except ExistingDestinationError:
        result_queue.put(("EXISTS", content.decode("ascii")))
    except Exception as error:  # pragma: no cover - reported to the parent for exact assertion
        result_queue.put(("ERROR", repr(error)))
    else:
        result_queue.put(("CREATED", content.decode("ascii")))


def _layout(tmp_path: Path) -> tuple[Path, TargetPaths, StagingLayout]:
    primary = tmp_path / "broader-replication-v1-128-seeds"
    paths = TargetPaths.from_target(
        primary,
        PUBLICATION_ID,
        primary_target=primary,
    )
    staging = StagingLayout.from_target(
        primary,
        PUBLICATION_ID,
        primary_target=primary,
    )
    return primary, paths, staging


@pytest.mark.taskb_ledger
def test_exact_canonical_ledger_serialization_and_raw_hash() -> None:
    value: dict[str, object] = {
        "z": [True, None, -2],
        "a": "caf\N{LATIN SMALL LETTER E WITH ACUTE}",
    }
    expected = b'{"a":"caf\xc3\xa9","z":[true,null,-2]}\n'

    assert canonical_json_bytes(value) == expected[:-1]
    assert canonical_ledger_bytes(value) == expected
    assert parse_canonical_ledger_bytes(expected) == value
    assert (
        raw_sha256(expected) == "aa688b20a0e9492415f895a6a7019837d539b4fb4019baa3e3af414ffae60daf"
    )


@pytest.mark.taskb_ledger
@pytest.mark.parametrize(
    "data",
    [
        b'{"a":1,"a":1}\n',
        b'{"a":1.0}\n',
        b'{"a":NaN}\n',
        b' {"a":1}\n',
        b'{"b":1,"a":2}\n',
        b'{"a":1}',
        b'{"a":1}\n\n',
        b'\xef\xbb\xbf{"a":1}\n',
        b'{"a":"\\u00e9"}\n',
        '{"a":"e\N{COMBINING ACUTE ACCENT}"}\n'.encode(),
        b"[1,2]\n",
    ],
)
def test_parser_rejects_duplicate_float_and_noncanonical_equivalents(data: bytes) -> None:
    with pytest.raises(CanonicalLedgerError):
        parse_canonical_ledger_bytes(data)


@pytest.mark.taskb_ledger
@pytest.mark.parametrize(
    "value",
    [
        {"a": 1.0},
        {"a": [float("nan")]},
        {"a": "e\N{COMBINING ACUTE ACCENT}"},
        {"\N{LATIN SMALL LETTER E WITH ACUTE}": 1},
        {"a": (1, 2)},
    ],
)
def test_serializer_rejects_float_non_nfc_non_ascii_key_and_non_json_container(
    value: Mapping[str, object],
) -> None:
    with pytest.raises(CanonicalLedgerError):
        canonical_ledger_bytes(value)


@pytest.mark.taskb_ledger
def test_closed_identifier_and_ledger_name_grammars() -> None:
    assert validate_publication_id(PUBLICATION_ID) == PUBLICATION_ID
    assert validate_authorization_attempt_id(AUTHORIZATION_ATTEMPT_ID) == AUTHORIZATION_ATTEMPT_ID
    assert {
        validate_ledger_final_name(name)
        for name in ("attempt.json", "M11", "M12", "M13", "MF", "failure.json")
    } == lifecycle_io.LEDGER_FINAL_NAMES

    for invalid in ("publication-" + "A" * 64, "publication-1", "1" * 64, None):
        with pytest.raises(UnsafePathError):
            validate_publication_id(invalid)
    with pytest.raises(UnsafePathError):
        validate_ledger_final_name("warning.json")


@pytest.mark.taskb_ledger
def test_target_scope_and_exact_external_layout(tmp_path: Path) -> None:
    primary, paths, staging = _layout(tmp_path)
    retry = primary.with_name(f"{primary.name}.retry-{PUBLICATION_ID}")

    assert normalize_target(primary, primary_target=primary) == paths.canonical_target
    assert normalize_target(retry, primary_target=primary).endswith(f".retry-{PUBLICATION_ID}")
    assert paths.ledger_root == paths.target.with_name(paths.target.name + ".rde-attempts")
    assert paths.attempt_directory == paths.ledger_root / PUBLICATION_ID
    assert paths.attempt_file == paths.attempt_directory / "attempt.json"
    assert staging.root == paths.staging_parent / PUBLICATION_ID
    assert staging.attempt_publication == staging.root / "attempt-publication"
    assert staging.prepared_artifacts_1_11 == staging.root / "prepared-artifacts-1-11"
    assert staging.artifacts_1_11_publication == staging.root / "artifacts-1-11-publication"
    assert not is_path_within(staging.root, paths.target)
    assert not is_path_within(staging.root, paths.attempt_directory)


@pytest.mark.taskb_ledger
def test_target_rejects_dot_aliases_generated_suffixes_and_unrelated_siblings(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "broader-replication-v1-128-seeds"
    raw_dot = f"{tmp_path}{os.sep}.{os.sep}{primary.name}"
    raw_dot_dot = f"{tmp_path}{os.sep}child{os.sep}..{os.sep}{primary.name}"
    raw_empty = f"{tmp_path}{os.sep}{os.sep}{primary.name}"
    raw_trailing = f"{primary}{os.sep}"

    for target in (
        raw_dot,
        raw_dot_dot,
        raw_empty,
        raw_trailing,
        primary.with_name("unrelated-publication"),
        primary.with_name(primary.name + ".retry-publication-" + "a" * 63),
        primary.with_name(primary.name + ".rde-attempts"),
        primary.with_name(primary.name + ".rde-staging"),
    ):
        with pytest.raises(UnsafePathError):
            normalize_target(target, primary_target=primary)


@pytest.mark.taskb_ledger
def test_reparse_ancestor_fails_closed_where_symlinks_are_available(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked"
    try:
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks are unavailable: {error}")
    target = linked_parent / "broader-replication-v1-128-seeds"

    with pytest.raises(UnsafePathError):
        normalize_target(target, primary_target=target)


@pytest.mark.taskb_ledger
def test_existing_target_leaf_is_never_followed_by_pure_normalization(tmp_path: Path) -> None:
    real_target = tmp_path / "real-target"
    real_target.mkdir()
    target = tmp_path / "broader-replication-v1-128-seeds"
    try:
        target.symlink_to(real_target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks are unavailable: {error}")

    canonical = normalize_target(target, primary_target=target)

    assert canonical.endswith("broader-replication-v1-128-seeds")
    assert not ordinary_directory(target)


@pytest.mark.taskb_durability
def test_durable_directory_creation_is_idempotent_and_rejects_non_directory(
    tmp_path: Path,
) -> None:
    ledger_root = tmp_path / "ledger"

    assert ensure_ordinary_directory_durable(ledger_root) is True
    assert ensure_ordinary_directory_durable(ledger_root) is False
    assert ordinary_directory(ledger_root)

    wrong_type = tmp_path / "wrong-type"
    wrong_type.write_bytes(b"not a directory")
    with pytest.raises(UnsafePathError):
        ensure_ordinary_directory_durable(wrong_type)


@pytest.mark.taskb_durability
def test_external_file_publication_is_no_clobber_and_cleans_its_failed_stage(
    tmp_path: Path,
) -> None:
    _primary, paths, staging = _layout(tmp_path)
    staging.ensure_root()
    ensure_ordinary_directory_durable(paths.ledger_root)
    ensure_ordinary_directory_durable(paths.attempt_directory)
    destination = paths.attempt_directory / "M11"
    first = b'{"kind":"first"}\n'

    assert publish_bytes_no_replace(staging.stage_m11, destination, first) == first
    assert ordinary_file(destination)
    assert destination.read_bytes() == first
    assert not os.path.lexists(staging.stage_m11)

    with pytest.raises(ExistingDestinationError):
        publish_bytes_no_replace(staging.stage_m11, destination, b"second\n")

    assert destination.read_bytes() == first
    assert not os.path.lexists(staging.stage_m11)
    assert {entry.name for entry in paths.attempt_directory.iterdir()} == {"M11"}


@pytest.mark.taskb_durability
def test_preexisting_stage_residue_fails_without_mutation_or_cleanup(tmp_path: Path) -> None:
    _primary, paths, staging = _layout(tmp_path)
    staging.ensure_root()
    ensure_ordinary_directory_durable(paths.ledger_root)
    ensure_ordinary_directory_durable(paths.attempt_directory)
    staging.stage_m11.write_bytes(b"residue")
    destination = paths.attempt_directory / "M11"

    with pytest.raises(ExistingDestinationError):
        publish_bytes_no_replace(staging.stage_m11, destination, b"new")

    assert staging.stage_m11.read_bytes() == b"residue"
    assert not os.path.lexists(destination)


@pytest.mark.taskb_durability
def test_attempt_directory_publication_has_exact_final_inventory(tmp_path: Path) -> None:
    _primary, paths, staging = _layout(tmp_path)
    staging.ensure_root()
    ledger_created = ensure_ordinary_directory_durable(paths.ledger_root)
    attempt = b'{"kind":"attempt"}\n'

    installed = publish_directory_bytes_no_replace(
        staging.attempt_publication,
        paths.attempt_directory,
        {"attempt.json": attempt},
        durability_directories=(
            paths.attempt_directory,
            paths.ledger_root,
            paths.ledger_root.parent,
        )
        if ledger_created
        else (paths.attempt_directory, paths.ledger_root),
    )

    assert installed == {"attempt.json": attempt}
    assert paths.attempt_file.read_bytes() == attempt
    assert {entry.name for entry in paths.attempt_directory.iterdir()} == {"attempt.json"}
    assert not os.path.lexists(staging.attempt_publication)
    assert not any(
        entry.name.endswith((".tmp", ".partial", ".incomplete"))
        for entry in paths.attempt_directory.iterdir()
    )


@pytest.mark.taskb_durability
def test_staged_directory_reflush_and_publication_work_on_current_platform(tmp_path: Path) -> None:
    _primary, paths, staging = _layout(tmp_path)
    staging.ensure_root()
    ensure_ordinary_directory_durable(paths.ledger_root)
    staging.create_prepared_artifacts({"attempt.json": b"{}\n"})

    installed = publish_staged_directory_no_replace(
        staging.prepared_artifacts_1_11,
        paths.attempt_directory,
        {"attempt.json": b"{}\n"},
    )

    assert installed == {"attempt.json": b"{}\n"}


@pytest.mark.taskb_durability
def test_directory_flush_failure_before_install_cleans_owned_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _primary, paths, staging = _layout(tmp_path)
    staging.ensure_root()
    ensure_ordinary_directory_durable(paths.ledger_root)

    def fail_directory_flush(_path: lifecycle_io.StrPath) -> None:
        raise DurabilityError("injected staged-directory barrier failure")

    monkeypatch.setattr(lifecycle_io, "fsync_directory", fail_directory_flush)
    with pytest.raises(DurabilityError, match="injected"):
        publish_directory_bytes_no_replace(
            staging.attempt_publication,
            paths.attempt_directory,
            {"attempt.json": b"{}\n"},
        )

    assert not os.path.lexists(staging.attempt_publication)
    assert not os.path.lexists(paths.attempt_directory)


@pytest.mark.taskb_durability
def test_post_install_directory_barrier_failure_preserves_exact_final(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _primary, paths, staging = _layout(tmp_path)
    staging.ensure_root()
    ensure_ordinary_directory_durable(paths.ledger_root)
    ensure_ordinary_directory_durable(paths.attempt_directory)
    destination = paths.attempt_directory / "M11"
    content = b"durable-stage-but-unconfirmed-directory-entry\n"

    def fail_chain(_directories: Sequence[str | os.PathLike[str]]) -> None:
        raise DurabilityError("injected final-directory barrier failure")

    monkeypatch.setattr(lifecycle_io, "fsync_directory_chain", fail_chain)
    with pytest.raises(DurabilityError, match="injected"):
        publish_bytes_no_replace(staging.stage_m11, destination, content)

    assert destination.read_bytes() == content
    assert ordinary_file(destination)
    assert not os.path.lexists(staging.stage_m11)


@pytest.mark.taskb_durability
def test_readback_validator_failure_never_removes_or_rewrites_final(tmp_path: Path) -> None:
    _primary, paths, staging = _layout(tmp_path)
    staging.ensure_root()
    ensure_ordinary_directory_durable(paths.ledger_root)
    ensure_ordinary_directory_durable(paths.attempt_directory)
    destination = paths.attempt_directory / "M11"
    content = b"installed-before-semantic-validation\n"

    def reject(_installed: bytes) -> None:
        raise PublicationValidationError("injected exact readback rejection")

    with pytest.raises(PublicationValidationError, match="injected"):
        publish_bytes_no_replace(
            staging.stage_m11,
            destination,
            content,
            validator=reject,
        )

    assert destination.read_bytes() == content
    assert not os.path.lexists(staging.stage_m11)
    with pytest.raises(ExistingDestinationError):
        publish_bytes_no_replace(staging.stage_m11, destination, b"replacement")
    assert destination.read_bytes() == content


@pytest.mark.taskb_durability
def test_shared_and_exclusive_study_lock_conflict(tmp_path: Path) -> None:
    primary = tmp_path / "broader-replication-v1-128-seeds"
    first = StudyLock.for_primary_target(primary)
    second = StudyLock.for_primary_target(primary)
    third = StudyLock.for_primary_target(primary)
    assert first.acquire_shared(blocking=False)
    assert second.acquire_shared(blocking=False)
    assert not third.acquire_exclusive(blocking=False)
    first.release()
    second.release()

    assert third.acquire_exclusive(blocking=False)
    assert not first.acquire_shared(blocking=False)
    third.release()
    assert ordinary_file(third.path)


@pytest.mark.taskb_durability
def test_two_process_file_publication_has_exactly_one_winner(tmp_path: Path) -> None:
    _primary, paths, staging = _layout(tmp_path)
    staging.ensure_root()
    ensure_ordinary_directory_durable(paths.ledger_root)
    ensure_ordinary_directory_durable(paths.attempt_directory)
    destination = paths.attempt_directory / "M11"
    context = multiprocessing.get_context("spawn")
    gate = context.Event()
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_race_publish,
            args=(str(staging.stage_m11), str(destination), content, gate, result_queue),
        )
        for content in (b"first", b"second")
    ]
    for process in processes:
        process.start()
    gate.set()
    for process in processes:
        process.join(timeout=20)
        assert not process.is_alive()
        assert process.exitcode == 0
    try:
        results = [result_queue.get(timeout=5), result_queue.get(timeout=5)]
    except Empty as error:  # pragma: no cover - only reached for a broken subprocess contract
        raise AssertionError("publication race worker did not report") from error

    assert sorted(status for status, _value in results) == ["CREATED", "EXISTS"]
    winner = next(value.encode("ascii") for status, value in results if status == "CREATED")
    assert destination.read_bytes() == winner
    assert not os.path.lexists(staging.stage_m11)


@pytest.mark.taskb_ledger
def test_global_namespace_scan_collects_disk_and_attempt_identifier_collisions(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "broader-replication-v1-128-seeds"
    primary.mkdir()
    rx_publication = _publication_id("a")
    (tmp_path / f"{primary.name}.retry-{rx_publication}").mkdir()

    ledger_publication = _publication_id("b")
    final_publication = _publication_id("c")
    final_authorization = _authorization_attempt_id("d")
    ledger_root = tmp_path / f"{primary.name}.rde-attempts"
    attempt_directory = ledger_root / ledger_publication
    attempt_directory.mkdir(parents=True)
    (attempt_directory / "attempt.json").write_bytes(
        (
            '{ "publication_id":"'
            + final_publication
            + '","authorization_attempt_id":"'
            + final_authorization
            + '" }'
        ).encode()
    )

    staging_publication = _publication_id("e")
    staged_publication = _publication_id("f")
    staged_authorization = _authorization_attempt_id("0")
    staging_root = tmp_path / f"{primary.name}.rde-staging"
    staged_attempt = staging_root / staging_publication / "attempt-publication"
    staged_attempt.mkdir(parents=True)
    (staged_attempt / "attempt.json").write_bytes(
        (
            '{"publication_id":"'
            + staged_publication
            + '","authorization_attempt_id":"'
            + staged_authorization
        ).encode()
    )

    result = scan_lifecycle_namespace(primary)

    assert result.publication_ids == frozenset(
        {
            rx_publication,
            ledger_publication,
            final_publication,
            staging_publication,
            staged_publication,
        }
    )
    assert result.authorization_attempt_ids == frozenset(
        {final_authorization, staged_authorization}
    )
    assert result.targets == (primary, tmp_path / f"{primary.name}.retry-{rx_publication}")
    assert result.ledger_roots == (ledger_root,)
    assert result.staging_roots == (staging_root,)


@pytest.mark.taskb_authorization
def test_scan_collects_json_escaped_parseable_attempt_identifiers(tmp_path: Path) -> None:
    primary = tmp_path / "broader-replication-v1-128-seeds"
    ledger_publication = _publication_id("1")
    embedded_publication = _publication_id("2")
    embedded_authorization = _authorization_attempt_id("3")
    attempt_directory = tmp_path / f"{primary.name}.rde-attempts" / ledger_publication
    attempt_directory.mkdir(parents=True)
    escaped_publication = embedded_publication.replace("publication", "public\\u0061tion")
    escaped_authorization = embedded_authorization.replace("authorization", "authoriz\\u0061tion")
    (attempt_directory / "attempt.json").write_bytes(
        (
            '{"publication_id":"'
            + escaped_publication
            + '","authorization_attempt_id":"'
            + escaped_authorization
            + '"}\n'
        ).encode()
    )

    result = scan_lifecycle_namespace(primary)

    assert embedded_publication in result.publication_ids
    assert embedded_authorization in result.authorization_attempt_ids


@pytest.mark.taskb_ledger
@pytest.mark.parametrize("fault", ["malformed_rx", "malformed_ledger_child"])
def test_global_namespace_scan_fails_closed_on_malformed_candidate_namespaces(
    tmp_path: Path,
    fault: str,
) -> None:
    primary = tmp_path / "broader-replication-v1-128-seeds"
    if fault == "malformed_rx":
        (tmp_path / f"{primary.name}.retry-not-a-publication-id").mkdir()
    else:
        (tmp_path / f"{primary.name}.rde-attempts" / "not-a-publication-id").mkdir(parents=True)

    with pytest.raises(NamespaceScanError) as captured:
        scan_lifecycle_namespace(primary)

    assert captured.value.protocol_error_code == "NAMESPACE_GLOBAL_SCAN"
    assert captured.value.failed_path is not None


@pytest.mark.taskb_ledger
def test_global_namespace_scan_reports_attributable_unsafe_staging_structurally(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "broader-replication-v1-128-seeds"
    publication_root = tmp_path / f"{primary.name}.rde-staging" / _publication_id("4")
    publication_root.mkdir(parents=True)
    (publication_root / "stage-warning.json").write_bytes(b"unsafe")

    result = scan_lifecycle_namespace(primary)

    assert result.unsafe_staging_publications == (publication_root,)
    assert result.publication_ids == frozenset({_publication_id("4")})


@pytest.mark.taskb_ledger
def test_staged_attempt_extra_is_reported_after_exact_attempt_ids_are_collected(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "broader-replication-v1-128-seeds"
    staging_publication = _publication_id("7")
    embedded_publication = _publication_id("8")
    embedded_authorization = _authorization_attempt_id("9")
    publication_root = tmp_path / f"{primary.name}.rde-staging" / staging_publication
    attempt_stage = publication_root / "attempt-publication"
    attempt_stage.mkdir(parents=True)
    (attempt_stage / "attempt.json").write_bytes(
        (
            '{"publication_id":"'
            + embedded_publication
            + '","authorization_attempt_id":"'
            + embedded_authorization
            + '"}'
        ).encode()
    )
    (attempt_stage / "unexpected-residue").mkdir()

    result = scan_lifecycle_namespace(primary)

    assert result.unsafe_staging_publications == (publication_root,)
    assert result.publication_ids == frozenset({staging_publication, embedded_publication})
    assert result.authorization_attempt_ids == frozenset({embedded_authorization})


@pytest.mark.taskb_ledger
def test_extra_staged_artifact_member_is_structured_unsafe_residue(tmp_path: Path) -> None:
    primary = tmp_path / "broader-replication-v1-128-seeds"
    staging_publication = _publication_id("a")
    publication_root = tmp_path / f"{primary.name}.rde-staging" / staging_publication
    prepared = publication_root / "prepared-artifacts-1-11"
    prepared.mkdir(parents=True)
    (prepared / "protocol_snapshot.json").write_bytes(b"benign staged bytes")
    (prepared / "unexpected.json").write_bytes(b"unsafe extra")

    result = scan_lifecycle_namespace(primary)

    assert result.unsafe_staging_publications == (publication_root,)


@pytest.mark.taskb_ledger
def test_global_namespace_scan_rejects_unsafe_or_unreadable_candidate_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "broader-replication-v1-128-seeds"
    ledger_root = tmp_path / f"{primary.name}.rde-attempts"
    ledger_root.mkdir()
    real_scandir = os.scandir

    def deny_ledger(path: str | os.PathLike[str]) -> object:
        if os.path.normcase(os.path.abspath(os.fspath(path))) == os.path.normcase(
            os.path.abspath(ledger_root)
        ):
            raise PermissionError("injected unreadable candidate namespace")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", deny_ledger)

    with pytest.raises(NamespaceScanError, match="unreadable"):
        scan_lifecycle_namespace(primary)


@pytest.mark.taskb_ledger
def test_global_namespace_scan_ignores_unrelated_siblings_and_is_immutable(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "broader-replication-v1-128-seeds"
    unrelated_root = tmp_path / "another-study.rde-attempts"
    (unrelated_root / "not-a-publication-id").mkdir(parents=True)
    (tmp_path / f"{primary.name}-backup").write_text(
        _publication_id("5") + _authorization_attempt_id("6"),
        encoding="utf-8",
    )

    result = scan_lifecycle_namespace(primary)

    assert isinstance(result, NamespaceIdentifierScan)
    assert result.targets == ()
    assert result.ledger_roots == ()
    assert result.staging_roots == ()
    assert result.publication_ids == frozenset()
    assert result.authorization_attempt_ids == frozenset()
    with pytest.raises(FrozenInstanceError):
        result.primary_target = tmp_path  # type: ignore[misc]
