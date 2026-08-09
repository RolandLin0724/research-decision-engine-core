from __future__ import annotations

import copy
import json
import os
import secrets
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Event

import pytest

import research_decision_engine.benchmarks.broader_lifecycle as lifecycle
from research_decision_engine.benchmarks.broader_lifecycle import (
    AttemptAuthority,
    FrozenGraphValidator,
    ImplementationIdentity,
    LifecycleInvariantError,
    LifecycleReader,
)
from research_decision_engine.benchmarks.broader_lifecycle_io import (
    PRIMARY_TARGET,
    PublicationValidationError,
    StagingLayout,
    StudyLock,
    TargetPaths,
    is_path_within,
    ordinary_directory,
    parse_canonical_ledger_bytes,
)
from research_decision_engine.benchmarks.broader_lifecycle_records import (
    ARTIFACT_FILENAMES,
    PROTOCOL_CHECKPOINT,
    FailureErrorCode,
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


def _authority(tmp_path: Path, scope: str = "study") -> tuple[AttemptAuthority, Path]:
    parent = tmp_path / scope
    parent.mkdir()
    target = parent / "broader-replication-v1-128-seeds"
    return controlled_authority(target, _Graph(), IDENTITY), target


def _fixed_identifier_draws(
    monkeypatch: pytest.MonkeyPatch,
    *values: str,
) -> list[int]:
    remaining = list(values)
    calls: list[int] = []

    def draw(byte_count: int) -> str:
        calls.append(byte_count)
        if not remaining:
            raise AssertionError("identifier allocator redrew after a collision")
        return remaining.pop(0)

    monkeypatch.setattr(secrets, "token_hex", draw)
    return calls


@pytest.mark.taskb_authorization
def test_public_constructors_expose_no_target_or_trust_root_override(tmp_path: Path) -> None:
    authority_constructor: Callable[..., object] = AttemptAuthority
    reader_constructor: Callable[..., object] = LifecycleReader

    with pytest.raises(TypeError):
        authority_constructor(tmp_path / "alternate-target")
    with pytest.raises(TypeError):
        authority_constructor(_graph_validator=_Graph())
    with pytest.raises(TypeError):
        reader_constructor(tmp_path / "alternate-target")
    with pytest.raises(TypeError):
        reader_constructor(graph_validator=_Graph())

    authority = AttemptAuthority()
    reader = LifecycleReader()
    assert authority.primary_target == PRIMARY_TARGET
    assert reader.primary_target == PRIMARY_TARGET
    assert type(authority.graph_validator) is FrozenGraphValidator
    assert type(reader.graph_validator) is FrozenGraphValidator
    for instance, name, replacement in (
        (authority, "primary_target", tmp_path / "alternate-target"),
        (authority, "graph_validator", _Graph()),
        (authority, "_identity_provider", lambda: IDENTITY),
        (authority, "_reader_factory", lambda _identity: reader),
        (reader, "primary_target", tmp_path / "alternate-target"),
        (reader, "graph_validator", _Graph()),
        (reader, "_identity_provider", lambda: IDENTITY),
    ):
        with pytest.raises(AttributeError, match="immutable"):
            setattr(instance, name, replacement)


@pytest.mark.taskb_authorization
def test_manual_issued_session_construction_cannot_create_live_authorization(
    tmp_path: Path,
) -> None:
    authority, target = _authority(tmp_path)
    prepared = authority.prepare(_first_eleven(), IDENTITY)
    unacquired_lock = StudyLock.for_primary_target(target)

    with pytest.raises(TypeError, match="cannot be constructed directly"):
        lifecycle.IssuedAttempt(authority, prepared, unacquired_lock)
    with pytest.raises(LifecycleInvariantError, match="lock-held authority request"):
        lifecycle.IssuedAttempt._from_issuing_request(
            authority,
            prepared,
            unacquired_lock,
        )

    with authority.issue(prepared) as issued:
        attempt = issued.claim(issued.authorization)
    assert parse_canonical_ledger_bytes(attempt)["publication_id"] == prepared.publication_id


@pytest.mark.taskb_authorization
def test_disk_identifier_collision_fails_pair_without_redraw_and_tombstones_both(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, target = _authority(tmp_path)
    publication_hex = "1" * 64
    authorization_hex = "2" * 64
    publication_id = "publication-" + publication_hex
    authorization_id = "authorization-attempt-" + authorization_hex
    collision = target.with_name(target.name + ".rde-attempts") / publication_id
    collision.mkdir(parents=True)
    tombstones: set[str] = set()
    monkeypatch.setattr(lifecycle, "_ID_TOMBSTONES", tombstones)
    calls = _fixed_identifier_draws(monkeypatch, publication_hex, authorization_hex)

    with pytest.raises(LifecycleInvariantError, match="identifier|collision"):
        authority.prepare(_first_eleven(), IDENTITY)

    assert calls == [32, 32]
    assert tombstones == {publication_id, authorization_id}
    staging = StagingLayout.from_target(
        target,
        publication_id,
        primary_target=target,
    )
    assert not os.path.lexists(staging.root)


@pytest.mark.taskb_authorization
def test_process_tombstone_collision_fails_pair_without_redraw_and_tombstones_both(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, target = _authority(tmp_path)
    publication_hex = "3" * 64
    authorization_hex = "4" * 64
    publication_id = "publication-" + publication_hex
    authorization_id = "authorization-attempt-" + authorization_hex
    tombstones = {publication_id}
    monkeypatch.setattr(lifecycle, "_ID_TOMBSTONES", tombstones)
    calls = _fixed_identifier_draws(monkeypatch, publication_hex, authorization_hex)

    with pytest.raises(LifecycleInvariantError, match="identifier|collision"):
        authority.prepare(_first_eleven(), IDENTITY)

    assert calls == [32, 32]
    assert tombstones == {publication_id, authorization_id}
    staging = StagingLayout.from_target(
        target,
        publication_id,
        primary_target=target,
    )
    assert not os.path.lexists(staging.root)


@pytest.mark.taskb_authorization
def test_r0_rejects_second_root_after_any_durable_attempt_history(tmp_path: Path) -> None:
    authority, target = _authority(tmp_path)
    first = authority.prepare(_first_eleven(), IDENTITY)
    with authority.issue(first) as issued:
        issued.claim(issued.authorization)
    second = authority.prepare(_first_eleven(), IDENTITY)

    with pytest.raises(LifecycleInvariantError, match="history"), authority.issue(second):
        pytest.fail("R0 cannot issue a second root after durable attempt history.")

    second_attempt = TargetPaths.from_target(
        target,
        second.publication_id,
        primary_target=target,
    ).attempt_file
    assert not second_attempt.exists()


@pytest.mark.taskb_authorization
def test_r0_rejects_malformed_durable_family_history(tmp_path: Path) -> None:
    authority, target = _authority(tmp_path)
    malformed_publication = "publication-" + "8" * 64
    malformed = Path(str(target) + ".rde-attempts") / malformed_publication
    malformed.mkdir(parents=True)
    (malformed / "attempt.json").write_bytes(b'{"publication_id":"publication-' + b"8" * 64)
    prepared = authority.prepare(_first_eleven(), IDENTITY)

    with pytest.raises(LifecycleInvariantError, match="history"), authority.issue(prepared):
        pytest.fail("Malformed durable family history must block R0.")


@pytest.mark.taskb_authorization
def test_copied_prepared_request_cannot_reach_authorization(tmp_path: Path) -> None:
    authority, _target = _authority(tmp_path)
    prepared = authority.prepare(_first_eleven(), IDENTITY)
    copied = replace(prepared)

    with (
        pytest.raises(LifecycleInvariantError, match="exact one-use trusted prepared"),
        authority.issue(copied),
    ):
        pytest.fail("A copied prepared request cannot receive an authorization.")

    with authority.issue(prepared) as issued:
        attempt = issued.claim(issued.authorization)
    assert parse_canonical_ledger_bytes(attempt)["publication_id"] == prepared.publication_id


@pytest.mark.taskb_authorization
def test_issued_session_copy_or_forged_wrapper_cannot_release_authority_lock(
    tmp_path: Path,
) -> None:
    authority, target = _authority(tmp_path)
    prepared = authority.prepare(_first_eleven(), IDENTITY)

    with authority.issue(prepared) as issued:
        with pytest.raises(TypeError, match="cannot be copied"):
            copy.copy(issued)
        with pytest.raises(TypeError, match="cannot be deep-copied"):
            copy.deepcopy(issued)

        forged = object.__new__(lifecycle.IssuedAttempt)
        for name in lifecycle.IssuedAttempt.__slots__:
            object.__setattr__(forged, name, getattr(issued, name))
        forged.close()

        probe = StudyLock.for_primary_target(target)
        assert not probe.acquire_exclusive(blocking=False)
        attempt = issued.claim(issued.authorization)

    assert parse_canonical_ledger_bytes(attempt)["publication_id"] == prepared.publication_id


@pytest.mark.taskb_authorization
def test_concurrent_close_cannot_release_lock_during_claim_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, target = _authority(tmp_path)
    prepared = authority.prepare(_first_eleven(), IDENTITY)
    claim_started = Event()
    permit_claim = Event()
    close_started = Event()
    real_revalidate = AttemptAuthority._require_creation_eligible

    def paused_revalidate(
        selected_authority: AttemptAuthority,
        candidate: lifecycle.PreparedAttempt,
        *,
        allow_source_closure: bool = False,
    ) -> lifecycle.PreparedAttempt:
        assert selected_authority is authority
        claim_started.set()
        assert permit_claim.wait(timeout=10)
        return real_revalidate(
            selected_authority,
            candidate,
            allow_source_closure=allow_source_closure,
        )

    with authority.issue(prepared) as issued:
        monkeypatch.setattr(AttemptAuthority, "_require_creation_eligible", paused_revalidate)
        with ThreadPoolExecutor(max_workers=2) as executor:
            claim_future = executor.submit(issued.claim, issued.authorization)
            assert claim_started.wait(timeout=10)

            def concurrent_close() -> None:
                close_started.set()
                issued.close()

            close_future = executor.submit(concurrent_close)
            assert close_started.wait(timeout=10)
            assert not close_future.done()
            probe = StudyLock.for_primary_target(target)
            assert not probe.acquire_exclusive(blocking=False)

            permit_claim.set()
            attempt = claim_future.result(timeout=20)
            close_future.result(timeout=20)

    assert parse_canonical_ledger_bytes(attempt)["publication_id"] == prepared.publication_id
    _assert_study_lock_is_released(target)


@pytest.mark.taskb_authorization
def test_concurrent_alias_claim_has_exactly_one_winner(tmp_path: Path) -> None:
    authority, target = _authority(tmp_path)
    prepared = authority.prepare(_first_eleven(), IDENTITY)
    gate = Barrier(3)

    with authority.issue(prepared) as issued:
        first_alias = issued.authorization
        second_alias = first_alias

        def claim(alias: object) -> tuple[str, object]:
            gate.wait(timeout=10)
            try:
                return "winner", issued.claim(alias)
            except Exception as error:  # returned for exact parent-thread assertion
                return "loser", error

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(claim, first_alias),
                executor.submit(claim, second_alias),
            )
            gate.wait(timeout=10)
            outcomes = [future.result(timeout=20) for future in futures]

    winners = [value for status, value in outcomes if status == "winner"]
    losers = [value for status, value in outcomes if status == "loser"]
    assert len(winners) == 1
    assert len(losers) == 1
    assert type(losers[0]) is ValueError
    assert isinstance(winners[0], bytes)
    attempt = parse_canonical_ledger_bytes(winners[0])
    assert attempt["publication_id"] == prepared.publication_id
    paths = TargetPaths.from_target(target, prepared.publication_id, primary_target=target)
    assert paths.attempt_file.read_bytes() == winners[0]


@pytest.mark.taskb_authorization
def test_fake_and_wrong_wrapper_rejections_do_not_consume_exact_authorization(
    tmp_path: Path,
) -> None:
    first_authority, first_target = _authority(tmp_path, "first-study")
    second_authority, _second_target = _authority(tmp_path, "second-study")
    first_prepared = first_authority.prepare(_first_eleven(), IDENTITY)
    second_prepared = second_authority.prepare(_first_eleven(), IDENTITY)

    with (
        first_authority.issue(first_prepared) as first_issued,
        second_authority.issue(second_prepared) as second_issued,
    ):
        exact = first_issued.authorization
        with pytest.raises(ValueError, match="exact issued"):
            first_issued.claim(object())
        with pytest.raises(ValueError, match="forged|stale|copied|consumed"):
            second_issued.claim(exact)
        attempt = first_issued.claim(exact)

    assert parse_canonical_ledger_bytes(attempt)["publication_id"] == first_prepared.publication_id
    paths = TargetPaths.from_target(
        first_target,
        first_prepared.publication_id,
        primary_target=first_target,
    )
    assert paths.attempt_file.read_bytes() == attempt


def _finalize(
    authority: AttemptAuthority, prepared: lifecycle.PreparedAttempt
) -> Mapping[str, bytes]:
    return authority.finalize(
        prepared,
        manifest_builder=lambda _artifacts: _artifact("run_manifest.json"),
        recommendation_builder=lambda _artifacts: _artifact("recommendation.json"),
    )


def _assert_study_lock_is_released(target: Path) -> None:
    probe = StudyLock.for_primary_target(target)
    assert probe.acquire_exclusive(blocking=False)
    probe.release()


@pytest.mark.taskb_authorization
@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_finalize_releases_study_lock_before_result_or_exception_is_exposed(
    tmp_path: Path,
    outcome: str,
) -> None:
    authority, target = _authority(tmp_path)
    prepared = authority.prepare(_first_eleven(), IDENTITY)

    if outcome == "success":
        result = _finalize(authority, prepared)
        assert tuple(result) == ARTIFACT_FILENAMES
    else:

        def fail_manifest(_artifacts: Mapping[str, bytes]) -> bytes:
            raise RuntimeError("controlled handled finalization failure")

        with pytest.raises(
            LifecycleInvariantError,
            match="trusted manifest builder failed",
        ) as captured:
            authority.finalize(
                prepared,
                manifest_builder=fail_manifest,
                recommendation_builder=lambda _artifacts: _artifact("recommendation.json"),
            )
        assert isinstance(captured.value.__cause__, RuntimeError)

    _assert_study_lock_is_released(target)


@pytest.mark.taskb_authorization
@pytest.mark.parametrize("first_outcome", ["return", "raise"])
def test_claimed_finalize_continuation_cannot_be_started_twice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first_outcome: str,
) -> None:
    authority, _target = _authority(tmp_path)
    prepared = authority.prepare(_first_eleven(), IDENTITY)
    calls = 0

    def continuation(
        selected_authority: AttemptAuthority,
        _prepared: lifecycle.PreparedAttempt,
        _attempt_bytes: bytes,
        *,
        manifest_builder: lifecycle.ManifestBuilder,
        recommendation_builder: lifecycle.RecommendationBuilder,
    ) -> Mapping[str, bytes]:
        nonlocal calls
        assert selected_authority is authority
        del manifest_builder, recommendation_builder
        calls += 1
        if first_outcome == "raise":
            raise RuntimeError("controlled continuation failure")
        return {}

    monkeypatch.setattr(AttemptAuthority, "_run_claimed_lifecycle", continuation)
    with authority.issue(prepared) as issued:
        issued.claim(issued.authorization)
        if first_outcome == "raise":
            with pytest.raises(RuntimeError, match="controlled continuation"):
                issued.finalize_claimed(
                    manifest_builder=lambda _artifacts: b"unused",
                    recommendation_builder=lambda _artifacts: b"unused",
                )
        else:
            assert not issued.finalize_claimed(
                manifest_builder=lambda _artifacts: b"unused",
                recommendation_builder=lambda _artifacts: b"unused",
            )

        with pytest.raises(LifecycleInvariantError, match="continuation|already|once"):
            issued.finalize_claimed(
                manifest_builder=lambda _artifacts: b"unused",
                recommendation_builder=lambda _artifacts: b"unused",
            )

    assert calls == 1


@pytest.mark.taskb_durability
@pytest.mark.parametrize("outcome", ["success", "handled-failure"])
def test_terminal_finalize_cleans_its_owned_staging_root(
    tmp_path: Path,
    outcome: str,
) -> None:
    authority, _target = _authority(tmp_path)
    prepared = authority.prepare(_first_eleven(), IDENTITY)
    assert ordinary_directory(prepared.staging.root)

    if outcome == "success":
        _finalize(authority, prepared)
    else:

        def fail_manifest(_artifacts: Mapping[str, bytes]) -> bytes:
            raise RuntimeError("controlled handled staging cleanup failure")

        with pytest.raises(
            LifecycleInvariantError,
            match="trusted manifest builder failed",
        ) as captured:
            authority.finalize(
                prepared,
                manifest_builder=fail_manifest,
                recommendation_builder=lambda _artifacts: _artifact("recommendation.json"),
            )
        assert isinstance(captured.value.__cause__, RuntimeError)

    assert not os.path.lexists(prepared.staging.root)


@pytest.mark.taskb_diagnostic
def test_post_claim_reopen_rejects_changed_prepared_source_with_exact_code(
    tmp_path: Path,
) -> None:
    authority, target = _authority(tmp_path)
    prepared = authority.prepare(_first_eleven(), IDENTITY)
    changed = prepared.staging.prepared_artifacts_1_11 / ARTIFACT_FILENAMES[0]
    changed.write_bytes(
        b'{"source_checkpoint_identifier":"' + PROTOCOL_CHECKPOINT.encode() + b'"}\n'
    )

    with pytest.raises(PublicationValidationError, match="authorization-bound staged bytes"):
        _finalize(authority, prepared)

    paths = TargetPaths.from_target(target, prepared.publication_id, primary_target=target)
    failure = validate_record(
        "failure.json",
        (paths.attempt_directory / "failure.json").read_bytes(),
    )
    assert isinstance(failure, FailureRecord)
    assert failure.error_code is FailureErrorCode.VALIDATION_STAGED_BYTES
    assert not target.exists()
    assert not os.path.lexists(prepared.staging.root)


@pytest.mark.taskb_durability
def test_abrupt_direct_claim_residue_is_only_external_operational_state(
    tmp_path: Path,
) -> None:
    authority, target = _authority(tmp_path)
    prepared = authority.prepare(_first_eleven(), IDENTITY)
    with authority.issue(prepared) as issued:
        attempt = issued.claim(issued.authorization)

    paths = TargetPaths.from_target(target, prepared.publication_id, primary_target=target)
    assert paths.attempt_file.read_bytes() == attempt
    assert not os.path.lexists(target)
    assert {entry.name for entry in paths.attempt_directory.iterdir()} == {"attempt.json"}
    if os.path.lexists(prepared.staging.root):
        assert ordinary_directory(prepared.staging.root)
        assert not is_path_within(prepared.staging.root, target)
        assert not is_path_within(prepared.staging.root, paths.attempt_directory)
