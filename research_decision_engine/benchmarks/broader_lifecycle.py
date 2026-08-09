"""Superseding external finalization lifecycle for the broader replication.

This module is deliberately limited to lifecycle authority.  Scientific artifact
construction and graph rules remain owned by :mod:`broader_artifact_graph` and the
frozen artifact contracts.
"""

from __future__ import annotations

import csv
import json
import os
import re
import secrets
import stat
import subprocess
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Final, NoReturn, Protocol, SupportsIndex, cast

from research_decision_engine.benchmarks.broader_artifact_graph import (
    FROZEN_ARTIFACT_PROFILE,
    ArtifactCardinalityProfile,
    decode_and_validate_artifacts,
    decode_and_validate_audited_artifacts,
    decode_and_validate_manifest_artifacts,
)
from research_decision_engine.benchmarks.broader_artifacts import (
    ArtifactContract,
    ArtifactValidationError,
    artifact_contracts,
)
from research_decision_engine.benchmarks.broader_lifecycle_io import (
    CanonicalLedgerError,
    DurabilityError,
    ExistingDestinationError,
    LifecycleIOError,
    NamespaceIdentifierScan,
    PublicationValidationError,
    StagingLayout,
    StudyLock,
    TargetPaths,
    UnsafePathError,
    canonical_json_bytes,
    canonical_ledger_bytes,
    ensure_ordinary_directory_durable,
    fsync_directory,
    is_path_within,
    normalize_target,
    ordinary_directory,
    ordinary_file,
    parse_canonical_ledger_bytes,
    publish_bytes_no_replace,
    publish_directory_bytes_no_replace,
    raw_sha256,
    read_exact_directory,
    scan_lifecycle_namespace,
    validate_publication_id,
)
from research_decision_engine.benchmarks.broader_lifecycle_records import (
    ARTIFACT_FILENAMES,
    LEDGER_FINAL_NAMES,
    PROTOCOL_CHECKPOINT,
    RECORD_FIELDS,
    RECORD_SCHEMA_KIND,
    SOURCE_DESIGN_CHECKPOINT,
    STUDY_ID,
    ArtifactHash,
    AttemptRecord,
    BindingEnvelope,
    FailedTransition,
    FailureErrorCode,
    FailurePhase,
    FailureRecord,
    InventoryEntry,
    InventoryNamespace,
    LedgerPredecessor,
    LifecycleRecordError,
    M11Record,
    M12Record,
    M13Record,
    MFRecord,
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
    record_sha256,
    validate_attempt_retry_semantics,
    validate_record,
)
from research_decision_engine.benchmarks.broader_protocol import repository_root

PRIMARY_TARGET_NAME: Final = "broader-replication-v1-128-seeds"
OPTIONAL_REPORT_NAME: Final = "BROADER_REPLICATION_REPORT.md"
PUBLICATION_PATTERN: Final = re.compile(r"publication-[0-9a-f]{64}\Z")
AUTHORIZATION_PATTERN: Final = re.compile(r"authorization-attempt-[0-9a-f]{64}\Z")
_RETRY_TUPLE_FIELDS: Final = (
    "retry_kind",
    "retry_of_publication_id",
    "retry_source_canonical_target",
    "retry_source_authorization_attempt_id",
    "retry_source_attempt_sha256",
    "retry_source_failure_sha256",
    "retry_source_terminal_result",
    "retry_authorization_id",
)
_RETRY_REQUIRED_FIELDS: Final = tuple(
    name for name in _RETRY_TUPLE_FIELDS if name != "retry_source_failure_sha256"
)

ManifestBuilder = Callable[[Mapping[str, bytes]], bytes]
RecommendationBuilder = Callable[[Mapping[str, bytes]], bytes]


def _optional_lstat(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None


def _stat_is_reparse(result: os.stat_result) -> bool:
    attributes = int(getattr(result, "st_file_attributes", 0))
    flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return bool(attributes & flag)


def _stat_is_ordinary_file(result: os.stat_result) -> bool:
    return stat.S_ISREG(result.st_mode) and not _stat_is_reparse(result)


def _stat_is_ordinary_directory(result: os.stat_result) -> bool:
    return stat.S_ISDIR(result.st_mode) and not _stat_is_reparse(result)


class LifecycleState(StrEnum):
    """The complete frozen terminal-state enumeration."""

    NEVER_PUBLISHED = "NEVER_PUBLISHED"
    ABORTED_BEFORE_PUBLICATION = "ABORTED_BEFORE_PUBLICATION"
    PARTIAL_SCIENTIFIC_PUBLICATION_INVALID = "PARTIAL_SCIENTIFIC_PUBLICATION_INVALID"
    MANIFEST_PUBLISHED_INCOMPLETE = "MANIFEST_PUBLISHED_INCOMPLETE"
    RECOMMENDATION_PUBLISHED_NOT_FINALIZED = "RECOMMENDATION_PUBLISHED_NOT_FINALIZED"
    INVALID = "INVALID"
    SUCCESS = "SUCCESS"


class RetryDisposition(StrEnum):
    R0 = "R0"
    RX = "RX"
    RN = "RN"


class SelectedReader(StrEnum):
    AMENDED = "AMENDED"
    HISTORICAL = "HISTORICAL"


class OperationalRead(StrEnum):
    WRITER_ACTIVE = "WRITER_ACTIVE"


class CanonicalMode(StrEnum):
    ABSENT = "ABSENT"
    REPORT_ONLY = "REPORT_ONLY"
    CANONICAL_PRESENT = "CANONICAL_PRESENT"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class ImplementationIdentity:
    implementation_commit: str
    implementation_tree_sha256: str
    implementation_diff_sha256: str


@dataclass(frozen=True, slots=True)
class LifecycleClassification:
    terminal_state: LifecycleState | None
    selected_reader: SelectedReader | None
    retry_disposition: RetryDisposition | None
    reason: str | None
    canonical_inventory: tuple[str, ...]
    diagnostic_status: str
    operational: OperationalRead | None = None
    unrelated_publications: tuple[str, ...] = ()
    staging_residue: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        terminal = self.terminal_state is not None
        if self.operational is OperationalRead.WRITER_ACTIVE:
            if terminal or self.selected_reader is not None or self.retry_disposition is not None:
                raise ValueError("WRITER_ACTIVE cannot carry a terminal lifecycle result.")
        elif not terminal:
            raise ValueError("A stable reader result must have one terminal lifecycle state.")


class LifecycleScopeError(ValueError):
    """Raised when caller scope cannot be safely classified."""


class LifecycleInvariantError(ValueError):
    """Raised when a trusted writer would violate the frozen lifecycle."""


class _UnsafeR1StagingResidue(LifecycleInvariantError):
    """Exact attributable residue proves that same-target recovery is unavailable."""


class _Capability:
    __slots__ = ()

    _construction_key: Final = object()

    def __new__(cls, construction_key: object | None = None) -> _Capability:
        if construction_key is not cls._construction_key:
            raise TypeError("Attempt authorizations are issued only by the lifecycle authority.")
        return super().__new__(cls)

    def __init_subclass__(cls, **kwargs: object) -> None:
        if cls.__module__ != __name__:
            raise TypeError("Attempt authorizations cannot be subclassed.")
        super().__init_subclass__(**kwargs)

    def __copy__(self) -> NoReturn:
        raise TypeError("Attempt authorizations cannot be copied.")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("Attempt authorizations cannot be deep-copied.")

    def __reduce__(self) -> NoReturn:
        raise TypeError("Attempt authorizations cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Attempt authorizations cannot be serialized.")


class AttemptAuthorization(_Capability):
    """Exact-object, one-use authorization for one prepared attempt."""


@dataclass(frozen=True, slots=True)
class RetrySource:
    kind: RetryKind
    canonical_target: str
    publication_id: str
    authorization_attempt_id: str
    attempt_sha256: str
    failure_sha256: str | None
    terminal_result: RetryTerminalResult


@dataclass(frozen=True, slots=True)
class PreparedAttempt:
    target: Path
    canonical_target: str
    publication_id: str
    authorization_attempt_id: str
    implementation: ImplementationIdentity
    intended_artifacts: tuple[ArtifactHash, ...]
    staging: StagingLayout
    retry_source: RetrySource | None


@dataclass(slots=True)
class _AuthorizationEntry:
    authorization: AttemptAuthorization
    prepared: PreparedAttempt
    session: IssuedAttempt


_AUTHORIZATIONS: dict[AttemptAuthorization, _AuthorizationEntry] = {}
_ACTIVE_SESSIONS: set[IssuedAttempt] = set()
_AUTHORIZATION_MUTEX = threading.RLock()
_PREPARED_REQUESTS: dict[int, tuple[AttemptAuthority, PreparedAttempt, object]] = {}
_PREPARED_MUTEX = threading.RLock()
_ISSUANCE_REQUESTS: dict[int, tuple[AttemptAuthority, PreparedAttempt, StudyLock, object]] = {}
_ISSUANCE_MUTEX = threading.RLock()
_ID_TOMBSTONES: set[str] = set()
_ID_MUTEX = threading.RLock()


def _allocate_identifiers(primary_target: Path) -> tuple[str, str]:
    """Draw one identifier pair and fail the request on any collision.

    A collision never causes an in-request redraw.  Both values drawn for the
    failed request become process-lifetime tombstones, including when the disk
    namespace cannot be scanned safely.
    """

    with _ID_MUTEX:
        publication_id = "publication-" + secrets.token_hex(32)
        authorization_attempt_id = "authorization-attempt-" + secrets.token_hex(32)
        allocated = {publication_id, authorization_attempt_id}
        process_collision = bool(allocated & _ID_TOMBSTONES)
        try:
            disk = scan_lifecycle_namespace(primary_target)
        except Exception:
            _ID_TOMBSTONES.update(allocated)
            raise
        disk_collision = (
            publication_id in disk.publication_ids
            or authorization_attempt_id in disk.authorization_attempt_ids
        )
        _ID_TOMBSTONES.update(allocated)
        if process_collision or disk_collision:
            raise LifecycleInvariantError(
                "Lifecycle identifier collision; the allocated pair is tombstoned."
            )
        return publication_id, authorization_attempt_id


def _cleanup_owned_staging(staging: StagingLayout, primary_target: Path) -> None:
    """Remove only the selected publication's validated operational staging objects."""

    expected = StagingLayout.from_target(
        staging.target,
        staging.publication_id,
        primary_target=primary_target,
    )
    if expected != staging:
        raise UnsafePathError("Staging layout differs from its normalized selected publication.")
    root = staging.root
    if not os.path.lexists(root):
        return
    if not ordinary_directory(root):
        raise UnsafePathError("Owned staging root is not an ordinary directory.")

    artifact_names = frozenset(ARTIFACT_FILENAMES[:11])
    directory_children: dict[str, frozenset[str]] = {
        staging.attempt_publication.name: frozenset({"attempt.json"}),
        staging.prepared_artifacts_1_11.name: artifact_names,
        staging.artifacts_1_11_publication.name: artifact_names,
    }
    file_children = frozenset(
        {
            staging.stage_m11.name,
            staging.stage_run_manifest.name,
            staging.stage_m12.name,
            staging.stage_recommendation.name,
            staging.stage_m13.name,
            staging.stage_failure.name,
            staging.stage_mf.name,
        }
    )
    allowed = frozenset(directory_children) | file_children
    entries = tuple(root.iterdir())
    if any(entry.name not in allowed or not is_path_within(entry, root) for entry in entries):
        raise UnsafePathError("Owned staging contains an unexpected or misbound child.")

    directory_entries: list[tuple[Path, tuple[Path, ...]]] = []
    file_entries: list[Path] = []
    for entry in entries:
        if entry.name in directory_children:
            if not ordinary_directory(entry):
                raise UnsafePathError("Owned staged directory is not ordinary.")
            members = tuple(entry.iterdir())
            expected_members = directory_children[entry.name]
            if any(
                member.name not in expected_members
                or not is_path_within(member, root)
                or not ordinary_file(member)
                for member in members
            ):
                raise UnsafePathError("Owned staged directory contains an unsafe member.")
            directory_entries.append((entry, members))
        else:
            if not ordinary_file(entry):
                raise UnsafePathError("Owned staged file is not ordinary.")
            file_entries.append(entry)

    for entry in file_entries:
        entry.unlink()
    for directory, members in directory_entries:
        for member in members:
            member.unlink()
        directory.rmdir()
    fsync_directory(root)
    root.rmdir()
    fsync_directory(root.parent)


class IssuedAttempt:
    """One still-lock-held issuance/claim critical section."""

    _authority: AttemptAuthority
    _authorization: AttemptAuthorization
    _claimed: bool
    _claimed_attempt_bytes: bytes | None
    _closed: bool
    _finalization_started: bool
    _execution_binding: object
    _lock: StudyLock
    _operation_mutex: threading.RLock
    prepared: PreparedAttempt

    __slots__ = (
        "_authority",
        "_authorization",
        "_claimed",
        "_claimed_attempt_bytes",
        "_closed",
        "_finalization_started",
        "_execution_binding",
        "_lock",
        "_operation_mutex",
        "prepared",
    )

    def __init__(
        self,
        authority: AttemptAuthority,
        prepared: PreparedAttempt,
        lock: StudyLock,
    ) -> None:
        del authority, prepared, lock
        raise TypeError("Issued attempt sessions cannot be constructed directly.")

    @classmethod
    def _from_issuing_request(
        cls,
        authority: AttemptAuthority,
        prepared: PreparedAttempt,
        lock: StudyLock,
    ) -> IssuedAttempt:
        """Consume the exact internal issuance reservation and create one session."""

        with _ISSUANCE_MUTEX:
            request = _ISSUANCE_REQUESTS.pop(id(prepared), None)
            if (
                request is None
                or request[0] is not authority
                or request[1] is not prepared
                or request[2] is not lock
                or lock._file_descriptor is None
            ):
                raise LifecycleInvariantError(
                    "Issued sessions require the exact lock-held authority request."
                )
        self = object.__new__(cls)
        self._authority = authority
        self.prepared = prepared
        self._lock = lock
        self._operation_mutex = threading.RLock()
        self._claimed = False
        self._claimed_attempt_bytes = None
        self._closed = False
        self._finalization_started = False
        self._execution_binding = request[3]
        authority._require_current_execution_binding(self._execution_binding)
        authorization = AttemptAuthorization(AttemptAuthorization._construction_key)
        self._authorization = authorization
        with _AUTHORIZATION_MUTEX:
            _AUTHORIZATIONS[authorization] = _AuthorizationEntry(
                authorization,
                prepared,
                self,
            )
            _ACTIVE_SESSIONS.add(self)
        return self

    def __copy__(self) -> NoReturn:
        raise TypeError("Issued attempt sessions cannot be copied.")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("Issued attempt sessions cannot be deep-copied.")

    def __reduce__(self) -> NoReturn:
        raise TypeError("Issued attempt sessions cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Issued attempt sessions cannot be serialized.")

    @property
    def authorization(self) -> AttemptAuthorization:
        return self._authorization

    def claim(self, supplied: object) -> bytes:
        """Irreversibly claim the exact object and durably create ``attempt.json``."""

        with self._operation_mutex:
            return self._claim(supplied)

    def _claim(self, supplied: object) -> bytes:
        self._require_live_authorization(supplied)
        self._authority._require_current_execution_binding(self._execution_binding)
        authorization = cast(AttemptAuthorization, supplied)
        with _AUTHORIZATION_MUTEX:
            entry = _AUTHORIZATIONS.get(authorization)
            if entry is None or entry.authorization is not supplied or entry.session is not self:
                raise ValueError("Attempt authorization is forged, stale, copied, or consumed.")
            del _AUTHORIZATIONS[authorization]
            self._claimed = True

        # Claim is intentionally never restored, including when either check or I/O fails.
        self.prepared = self._authority._require_creation_eligible(self.prepared)
        attempt_bytes: bytes = self._authority._attempt_bytes(self.prepared)
        paths = TargetPaths.from_target(
            self.prepared.target,
            self.prepared.publication_id,
            primary_target=self._authority.primary_target,
        )
        ensure_ordinary_directory_durable(paths.ledger_root)
        publish_directory_bytes_no_replace(
            self.prepared.staging.attempt_publication,
            paths.attempt_directory,
            {"attempt.json": attempt_bytes},
            validator=lambda installed: self._authority._validate_installed_attempt(
                self.prepared,
                installed,
            ),
            durability_directories=(
                paths.attempt_directory,
                paths.ledger_root,
                paths.ledger_root.parent,
            ),
        )
        self._claimed_attempt_bytes = attempt_bytes
        return attempt_bytes

    def _require_live_authorization(self, supplied: object) -> None:
        """Non-consuming exact-object precheck for the supplied-object branch."""

        # This precheck occurs before any filesystem work by the supplied-object branch.
        if self._closed:
            raise ValueError("Attempt authorization no longer has an active issuing operation.")
        if type(supplied) is not AttemptAuthorization:
            raise ValueError("Finalization requires the exact issued attempt authorization.")
        with _AUTHORIZATION_MUTEX:
            entry = _AUTHORIZATIONS.get(supplied)
            if entry is None or entry.authorization is not supplied or entry.session is not self:
                raise ValueError("Attempt authorization is forged, stale, copied, or consumed.")

    def finalize(
        self,
        supplied: object,
        *,
        manifest_builder: ManifestBuilder,
        recommendation_builder: RecommendationBuilder,
    ) -> Mapping[str, bytes]:
        """Claim ``supplied`` and run the sole lock-held forward lifecycle."""

        with self._operation_mutex:
            return self._finalize(
                supplied,
                manifest_builder=manifest_builder,
                recommendation_builder=recommendation_builder,
            )

    def _finalize(
        self,
        supplied: object,
        *,
        manifest_builder: ManifestBuilder,
        recommendation_builder: RecommendationBuilder,
    ) -> Mapping[str, bytes]:
        self._require_live_authorization(supplied)
        self._authority._require_current_execution_binding(self._execution_binding)
        if self._finalization_started:
            raise LifecycleInvariantError("Finalization continuation may start only once.")
        self._finalization_started = True
        try:
            return self._authority._finalize_issued(
                self,
                supplied,
                manifest_builder=manifest_builder,
                recommendation_builder=recommendation_builder,
            )
        finally:
            self.close()

    def finalize_claimed(
        self,
        *,
        manifest_builder: ManifestBuilder,
        recommendation_builder: RecommendationBuilder,
    ) -> Mapping[str, bytes]:
        """Continue immediately after a successful direct :meth:`claim` call."""

        with self._operation_mutex:
            return self._finalize_claimed(
                manifest_builder=manifest_builder,
                recommendation_builder=recommendation_builder,
            )

    def _finalize_claimed(
        self,
        *,
        manifest_builder: ManifestBuilder,
        recommendation_builder: RecommendationBuilder,
    ) -> Mapping[str, bytes]:
        self._authority._require_current_execution_binding(self._execution_binding)
        if (
            self._closed
            or not self._claimed
            or self._claimed_attempt_bytes is None
            or self._finalization_started
        ):
            raise LifecycleInvariantError(
                "Finalization continuation may start only once from a still-lock-held claim."
            )
        self._finalization_started = True
        try:
            return self._authority._run_claimed_lifecycle(
                self.prepared,
                self._claimed_attempt_bytes,
                execution_binding=self._execution_binding,
                manifest_builder=manifest_builder,
                recommendation_builder=recommendation_builder,
            )
        finally:
            self.close()

    def close(self) -> None:
        with self._operation_mutex:
            self._close()

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        owns_lock = False
        with _AUTHORIZATION_MUTEX:
            if self in _ACTIVE_SESSIONS:
                _ACTIVE_SESSIONS.remove(self)
                owns_lock = True
                entry = _AUTHORIZATIONS.get(self._authorization)
                if entry is not None and entry.session is self:
                    del _AUTHORIZATIONS[self._authorization]
        if owns_lock:
            self._lock.release()


def _require_executor_bound_artifacts(artifacts: Mapping[str, bytes]) -> object:
    from research_decision_engine.benchmarks.broader_assembly import (
        _require_lifecycle_execution_binding,
    )

    return _require_lifecycle_execution_binding(artifacts)


def _revalidate_executor_binding(
    binding: object,
    artifacts: Mapping[str, bytes] | None = None,
) -> None:
    from research_decision_engine.benchmarks.broader_assembly import (
        _revalidate_lifecycle_execution_binding,
    )

    _revalidate_lifecycle_execution_binding(binding, artifacts)


def _validate_manifest_executor_binding(content: bytes, binding: object) -> None:
    from research_decision_engine.benchmarks.broader_assembly import (
        _validate_lifecycle_manifest_execution_binding,
    )

    _validate_lifecycle_manifest_execution_binding(content, binding)


class AttemptAuthority:
    """Trusted issuer for prepared artifacts and exact lock-held authorizations."""

    __graph_validator: _GraphValidator
    __identity_reader: Callable[[], ImplementationIdentity]
    __primary_target: Path
    __executor_binding_reader: Callable[[Mapping[str, bytes]], object]
    __executor_binding_validator: Callable[[object, Mapping[str, bytes] | None], None]
    __manifest_binding_validator: Callable[[bytes, object], None]

    __slots__ = (
        "__executor_binding_reader",
        "__executor_binding_validator",
        "__graph_validator",
        "__identity_reader",
        "__manifest_binding_validator",
        "__primary_target",
    )

    def __init__(self) -> None:
        object.__setattr__(
            self,
            "_AttemptAuthority__primary_target",
            repository_root() / PRIMARY_TARGET_NAME,
        )
        object.__setattr__(
            self,
            "_AttemptAuthority__graph_validator",
            FrozenGraphValidator(),
        )
        object.__setattr__(
            self,
            "_AttemptAuthority__identity_reader",
            reconstruct_implementation_identity,
        )
        object.__setattr__(
            self,
            "_AttemptAuthority__executor_binding_reader",
            _require_executor_bound_artifacts,
        )
        object.__setattr__(
            self,
            "_AttemptAuthority__executor_binding_validator",
            _revalidate_executor_binding,
        )
        object.__setattr__(
            self,
            "_AttemptAuthority__manifest_binding_validator",
            _validate_manifest_executor_binding,
        )

    def __init_subclass__(cls, **kwargs: object) -> NoReturn:
        del cls, kwargs
        raise TypeError("AttemptAuthority cannot be subclassed.")

    def __setattr__(self, name: str, value: object) -> NoReturn:
        del name, value
        raise AttributeError("AttemptAuthority trust roots are immutable.")

    def __delattr__(self, name: str) -> NoReturn:
        del name
        raise AttributeError("AttemptAuthority trust roots are immutable.")

    @property
    def primary_target(self) -> Path:
        return self.__primary_target

    @property
    def graph_validator(self) -> _GraphValidator:
        return self.__graph_validator

    def _trusted_implementation_identity(self) -> ImplementationIdentity:
        return self.__identity_reader()

    def _reader_trust_context(
        self,
    ) -> tuple[Path, _GraphValidator, Callable[[], ImplementationIdentity]]:
        return self.__primary_target, self.__graph_validator, self.__identity_reader

    def _require_current_execution_binding(
        self,
        binding: object,
        artifacts: Mapping[str, bytes] | None = None,
    ) -> None:
        self.__executor_binding_validator(binding, artifacts)

    def _require_manifest_execution_binding(self, content: bytes, binding: object) -> None:
        self.__manifest_binding_validator(content, binding)

    def prepare(
        self,
        artifacts_1_11: Mapping[str, bytes],
        implementation: ImplementationIdentity,
        *,
        retry_source: RetrySource | None = None,
    ) -> PreparedAttempt:
        """Allocate never-reused IDs and durably prepare immutable source bytes."""

        if implementation != self._trusted_implementation_identity():
            raise LifecycleInvariantError(
                "Preparation implementation identity differs from the trusted checkout."
            )
        execution_binding = self.__executor_binding_reader(artifacts_1_11)
        self._require_current_execution_binding(execution_binding)
        expected = ARTIFACT_FILENAMES[:11]
        if tuple(artifacts_1_11) != expected:
            raise LifecycleInvariantError("Preparation requires exact Artifacts 1 through 11.")
        source_artifacts = {name: bytes(artifacts_1_11[name]) for name in expected}
        self._require_current_execution_binding(execution_binding, source_artifacts)
        self.graph_validator.validate_11(source_artifacts)
        publication_id, authorization_attempt_id = _allocate_identifiers(self.primary_target)
        if retry_source is None or retry_source.kind is RetryKind.R1:
            target = (
                self.primary_target if retry_source is None else Path(retry_source.canonical_target)
            )
        else:
            target = self.primary_target.with_name(
                f"{self.primary_target.name}.retry-{publication_id}"
            )
        canonical_target = normalize_target(target, primary_target=self.primary_target)
        staging = StagingLayout.from_target(
            target,
            publication_id,
            primary_target=self.primary_target,
        )
        staging.create_prepared_artifacts(source_artifacts)
        staged = _read_exact_regular_files(staging.prepared_artifacts_1_11, expected)
        self._require_current_execution_binding(execution_binding, staged)
        self.graph_validator.validate_11(staged)
        intended = tuple(
            ArtifactHash(index, name, raw_sha256(staged[name]))
            for index, name in enumerate(expected, 1)
        )
        prepared = PreparedAttempt(
            target,
            canonical_target,
            publication_id,
            authorization_attempt_id,
            implementation,
            intended,
            staging,
            retry_source,
        )
        with _PREPARED_MUTEX:
            _PREPARED_REQUESTS[id(prepared)] = (self, prepared, execution_binding)
        return prepared

    @contextmanager
    def issue(self, prepared: PreparedAttempt) -> Iterator[IssuedAttempt]:
        """Issue and synchronously present one authorization under the authority lock."""

        with _PREPARED_MUTEX:
            entry = _PREPARED_REQUESTS.pop(id(prepared), None)
            if entry is None or entry[0] is not self or entry[1] is not prepared:
                raise LifecycleInvariantError(
                    "Issuance requires the exact one-use trusted prepared request."
                )
        execution_binding = entry[2]
        self._require_current_execution_binding(execution_binding)
        lock = StudyLock.for_primary_target(self.primary_target)
        lock.acquire_exclusive(blocking=True)
        issued: IssuedAttempt | None = None
        try:
            bound = self._require_creation_eligible(prepared, allow_source_closure=True)
            with _ISSUANCE_MUTEX:
                if id(bound) in _ISSUANCE_REQUESTS:
                    raise LifecycleInvariantError("Issuance request identity is already reserved.")
                _ISSUANCE_REQUESTS[id(bound)] = (self, bound, lock, execution_binding)
            try:
                issued = IssuedAttempt._from_issuing_request(self, bound, lock)
            finally:
                with _ISSUANCE_MUTEX:
                    request = _ISSUANCE_REQUESTS.get(id(bound))
                    if request is not None and request[0] is self and request[1] is bound:
                        del _ISSUANCE_REQUESTS[id(bound)]
            yield issued
        finally:
            if issued is not None:
                issued.close()
            else:
                lock.release()

    def finalize(
        self,
        prepared: PreparedAttempt,
        *,
        manifest_builder: ManifestBuilder,
        recommendation_builder: RecommendationBuilder,
    ) -> Mapping[str, bytes]:
        """Run one complete issuance and expose its result only after lock release."""

        with self.issue(prepared) as issued:
            result = issued.finalize(
                issued.authorization,
                manifest_builder=manifest_builder,
                recommendation_builder=recommendation_builder,
            )
        return result

    def _reader(self, identity: ImplementationIdentity) -> LifecycleReader:
        if identity != self._trusted_implementation_identity():
            raise LifecycleInvariantError(
                "Reader implementation identity differs from the trusted checkout."
            )
        return LifecycleReader._from_authority(self)

    def _require_creation_eligible(
        self,
        prepared: PreparedAttempt,
        *,
        allow_source_closure: bool = False,
    ) -> PreparedAttempt:
        if prepared.implementation != self._trusted_implementation_identity():
            raise LifecycleInvariantError(
                "Issuance implementation identity differs from the trusted checkout."
            )
        namespace = scan_lifecycle_namespace(self.primary_target)
        reader = self._reader(prepared.implementation)
        candidates = reader._local_success_candidates(lock_already_held=True)
        if candidates:
            raise LifecycleInvariantError("Study SUCCESS prohibits a new attempt.")
        if prepared.retry_source is None:
            if prepared.target != self.primary_target or os.path.lexists(prepared.target):
                raise LifecycleInvariantError("R0 requires the exact absent primary target.")
            if namespace.targets or self._durable_family_history(namespace.ledger_roots):
                raise LifecycleInvariantError(
                    "R0 requires no durable or malformed lifecycle family history."
                )
            return prepared
        source = reader._validate_retry_source_for_creation(
            prepared.retry_source,
            prepared,
            allow_missing_r1_failure=allow_source_closure,
        )
        if (
            source.kind is RetryKind.RX
            and source.terminal_result is RetryTerminalResult.ABORTED_BEFORE_PUBLICATION
            and source.failure_sha256 is None
        ):
            try:
                failure = _FailurePublisher(
                    self,
                    Path(source.canonical_target),
                    source.publication_id,
                    StagingLayout.from_target(
                        Path(source.canonical_target),
                        source.publication_id,
                        primary_target=self.primary_target,
                    ),
                    prepared.implementation,
                ).publish_recovery()
            except _UnsafeR1StagingResidue:
                pass
            else:
                source = reader._validate_retry_source_for_creation(
                    replace(source, failure_sha256=raw_sha256(failure)),
                    prepared,
                )
        if source.kind is RetryKind.R1 and source.failure_sha256 is None:
            if not allow_source_closure:
                raise LifecycleInvariantError("R1 source closure did not survive revalidation.")
            source_target = Path(source.canonical_target)
            if os.path.lexists(source_target):
                raise LifecycleInvariantError("R1 requires a physically absent source target.")
            failure = _FailurePublisher(
                self,
                source_target,
                source.publication_id,
                StagingLayout.from_target(
                    source_target,
                    source.publication_id,
                    primary_target=self.primary_target,
                ),
                prepared.implementation,
            ).publish_recovery()
            source = reader._validate_retry_source_for_creation(
                replace(source, failure_sha256=raw_sha256(failure)),
                prepared,
            )
        return replace(prepared, retry_source=source)

    def _durable_family_history(self, ledger_roots: Sequence[Path]) -> bool:
        """Return whether any selected ledger directory contains a surviving final name."""

        for root in ledger_roots:
            for publication in root.iterdir():
                if any(publication.iterdir()):
                    return True
        return False

    def _finalize_issued(
        self,
        issued: IssuedAttempt,
        supplied: object,
        *,
        manifest_builder: ManifestBuilder,
        recommendation_builder: RecommendationBuilder,
    ) -> Mapping[str, bytes]:
        expected_attempt = self._attempt_bytes(issued.prepared)
        try:
            attempt_bytes = issued.claim(supplied)
        except (
            LifecycleIOError,
            OSError,
            ValueError,
            TypeError,
            ArtifactValidationError,
        ) as error:
            try:
                _FailurePublisher(
                    self,
                    issued.prepared.target,
                    issued.prepared.publication_id,
                    issued.prepared.staging,
                    issued.prepared.implementation,
                ).publish_handled(
                    FailurePhase.ATTEMPT,
                    FailedTransition.INSTALL_ATTEMPT,
                    error,
                    expected_attempt=expected_attempt,
                )
            except (
                LifecycleIOError,
                OSError,
                ValueError,
                TypeError,
                ArtifactValidationError,
            ) as diagnostic_error:
                error.add_note(f"failure.json unavailable: {type(diagnostic_error).__name__}")
            self._cleanup_terminal_staging(issued.prepared)
            raise
        return self._run_claimed_lifecycle(
            issued.prepared,
            attempt_bytes,
            execution_binding=issued._execution_binding,
            manifest_builder=manifest_builder,
            recommendation_builder=recommendation_builder,
        )

    def _run_claimed_lifecycle(
        self,
        prepared: PreparedAttempt,
        attempt_bytes: bytes,
        *,
        execution_binding: object,
        manifest_builder: ManifestBuilder,
        recommendation_builder: RecommendationBuilder,
    ) -> Mapping[str, bytes]:
        try:
            writer = _LifecycleWriter(
                self,
                prepared,
                attempt_bytes,
                execution_binding,
            )
        except Exception as error:
            try:
                _FailurePublisher(
                    self,
                    prepared.target,
                    prepared.publication_id,
                    prepared.staging,
                    prepared.implementation,
                ).publish_handled(
                    FailurePhase.ARTIFACTS_1_11,
                    FailedTransition.ATTEMPT_TO_ARTIFACTS_1_11,
                    error,
                    expected_attempt=attempt_bytes,
                )
            except Exception as diagnostic_error:
                error.add_note(f"failure.json unavailable: {type(diagnostic_error).__name__}")
            self._cleanup_terminal_staging(prepared)
            raise
        try:
            result = writer.run(
                manifest_builder=manifest_builder,
                recommendation_builder=recommendation_builder,
            )
        except Exception:
            self._cleanup_terminal_staging(prepared)
            raise
        self._cleanup_terminal_staging(prepared)
        return result

    def _cleanup_terminal_staging(self, prepared: PreparedAttempt) -> None:
        """Best-effort cleanup; any survivor remains operational reader residue."""

        try:
            _cleanup_owned_staging(prepared.staging, self.primary_target)
        except (LifecycleIOError, OSError, ValueError):
            # Cleanup cannot undo a durable final or change terminal protocol state.
            # A survivor is exposed by the reader's operational staging_residue field.
            return

    def recover_abandoned(self, target: Path, publication_id: str) -> bytes:
        """Durably close one exact abandoned pre-MF attempt with recovery failure."""

        validate_publication_id(publication_id)
        canonical_target = normalize_target(target, primary_target=self.primary_target)
        del canonical_target
        lock = StudyLock.for_primary_target(self.primary_target)
        lock.acquire_exclusive(blocking=True)
        try:
            identity = self._trusted_implementation_identity()
            return _FailurePublisher(
                self,
                target,
                publication_id,
                StagingLayout.from_target(
                    target,
                    publication_id,
                    primary_target=self.primary_target,
                ),
                identity,
            ).publish_recovery()
        finally:
            lock.release()

    def _attempt_bytes(self, prepared: PreparedAttempt) -> bytes:
        envelope = make_binding_envelope(
            "attempt.json",
            canonical_target=prepared.canonical_target,
            publication_id=prepared.publication_id,
            implementation_commit=prepared.implementation.implementation_commit,
            implementation_tree_sha256=prepared.implementation.implementation_tree_sha256,
            implementation_diff_sha256=prepared.implementation.implementation_diff_sha256,
            authorization_attempt_id=prepared.authorization_attempt_id,
        )
        source = prepared.retry_source
        return build_attempt_record(
            envelope,
            prepared.intended_artifacts,
            retry_kind=None if source is None else source.kind,
            retry_of_publication_id=None if source is None else source.publication_id,
            retry_source_canonical_target=None if source is None else source.canonical_target,
            retry_source_authorization_attempt_id=(
                None if source is None else source.authorization_attempt_id
            ),
            retry_source_attempt_sha256=None if source is None else source.attempt_sha256,
            retry_source_failure_sha256=None if source is None else source.failure_sha256,
            retry_source_terminal_result=None if source is None else source.terminal_result,
            retry_authorization_id=(None if source is None else prepared.authorization_attempt_id),
        )

    def _validate_installed_attempt(
        self,
        prepared: PreparedAttempt,
        installed: Mapping[str, bytes],
    ) -> None:
        if tuple(installed) != ("attempt.json",):
            raise LifecycleInvariantError("Attempt publication contains an unexpected object.")
        record = validate_record("attempt.json", installed["attempt.json"])
        if not isinstance(record, AttemptRecord):
            raise LifecycleInvariantError("Installed attempt has the wrong record kind.")
        if record.envelope.canonical_target != prepared.canonical_target:
            raise LifecycleInvariantError("Installed attempt target binding differs.")
        if record.envelope.publication_id != prepared.publication_id:
            raise LifecycleInvariantError("Installed attempt publication binding differs.")


class _GraphValidator(Protocol):
    def validate_11(self, artifacts: Mapping[str, bytes]) -> None: ...

    def validate_12(self, artifacts: Mapping[str, bytes]) -> None: ...

    def validate_13(self, artifacts: Mapping[str, bytes]) -> None: ...

    def validate_historical(self, artifacts: Mapping[str, bytes]) -> None: ...


@dataclass(frozen=True, slots=True)
class FrozenGraphValidator:
    contracts: tuple[ArtifactContract, ...] = artifact_contracts()
    profile: ArtifactCardinalityProfile = FROZEN_ARTIFACT_PROFILE

    def validate_11(self, artifacts: Mapping[str, bytes]) -> None:
        decode_and_validate_audited_artifacts(
            artifacts,
            self.contracts[:11],
            profile=self.profile,
            expected_checkpoint=PROTOCOL_CHECKPOINT,
        )

    def validate_12(self, artifacts: Mapping[str, bytes]) -> None:
        decode_and_validate_manifest_artifacts(
            artifacts,
            self.contracts[:12],
            profile=self.profile,
            expected_checkpoint=PROTOCOL_CHECKPOINT,
        )

    def validate_13(self, artifacts: Mapping[str, bytes]) -> None:
        decode_and_validate_artifacts(
            artifacts,
            self.contracts,
            profile=self.profile,
            expected_checkpoint=PROTOCOL_CHECKPOINT,
        )

    def validate_historical(self, artifacts: Mapping[str, bytes]) -> None:
        decode_and_validate_artifacts(
            artifacts,
            self.contracts,
            profile=self.profile,
            expected_checkpoint=SOURCE_DESIGN_CHECKPOINT,
        )


@dataclass(frozen=True, slots=True)
class _SelectedSnapshot:
    target: Path
    canonical_target: str
    publication_id: str
    ledger: Mapping[str, bytes]
    canonical: Mapping[str, bytes]
    mode: CanonicalMode
    staging_residue: tuple[str, ...]


type _PublicationKey = tuple[str, str]

_HISTORICAL_OWNER: Final[_PublicationKey] = ("historical-p0", "historical-p0")


@dataclass(frozen=True, slots=True)
class _OwnPrefix:
    state: LifecycleState
    canonical: Mapping[str, bytes]
    failure: FailureRecord | None
    graph_invalid: bool = False


@dataclass(frozen=True, slots=True)
class _FamilyPublication:
    key: _PublicationKey
    snapshot: _SelectedSnapshot
    attempt_bytes: bytes
    local_attempt: AttemptRecord | None
    records: Mapping[str, object] | None
    own_prefix: _OwnPrefix | None


@dataclass(frozen=True, slots=True)
class _FamilyScan:
    namespace: NamespaceIdentifierScan
    attempts: tuple[tuple[Path, str, bytes], ...]
    occupied_publications: frozenset[_PublicationKey]


@dataclass(frozen=True, slots=True)
class _FamilyIndex:
    publications: Mapping[_PublicationKey, _FamilyPublication]
    occupied_publications: frozenset[_PublicationKey]
    allegations: Mapping[_PublicationKey, frozenset[_PublicationKey]]
    local_mf_candidates: frozenset[_PublicationKey]
    admitted: frozenset[_PublicationKey]
    admitted_edges: frozenset[tuple[_PublicationKey, _PublicationKey]]
    owner_claims: Mapping[str, frozenset[_PublicationKey]]
    valid_successes: frozenset[_PublicationKey]
    unsafe_family_targets: frozenset[Path]
    malformed_family_history: bool
    clean_initial_namespace: bool


ATTEMPT_READERS: Final[Mapping[str, SelectedReader]] = MappingProxyType(
    {PROTOCOL_CHECKPOINT: SelectedReader.AMENDED}
)


class LifecycleReader:
    """Independent total reader with trusted exact-checkpoint dispatch."""

    __graph_validator: _GraphValidator
    __identity_reader: Callable[[], ImplementationIdentity]
    __primary_target: Path

    __slots__ = ("__graph_validator", "__identity_reader", "__primary_target")

    def __init__(self) -> None:
        object.__setattr__(
            self,
            "_LifecycleReader__primary_target",
            repository_root() / PRIMARY_TARGET_NAME,
        )
        object.__setattr__(
            self,
            "_LifecycleReader__graph_validator",
            FrozenGraphValidator(),
        )
        object.__setattr__(
            self,
            "_LifecycleReader__identity_reader",
            reconstruct_implementation_identity,
        )

    def __init_subclass__(cls, **kwargs: object) -> NoReturn:
        del cls, kwargs
        raise TypeError("LifecycleReader cannot be subclassed.")

    def __setattr__(self, name: str, value: object) -> NoReturn:
        del name, value
        raise AttributeError("LifecycleReader trust roots are immutable.")

    def __delattr__(self, name: str) -> NoReturn:
        del name
        raise AttributeError("LifecycleReader trust roots are immutable.")

    @classmethod
    def _from_authority(cls, authority: AttemptAuthority) -> LifecycleReader:
        if type(authority) is not AttemptAuthority:
            raise LifecycleInvariantError(
                "Reader binding requires the exact trusted authority type."
            )
        primary_target, graph_validator, identity_reader = authority._reader_trust_context()
        reader = object.__new__(cls)
        object.__setattr__(
            reader,
            "_LifecycleReader__primary_target",
            primary_target,
        )
        object.__setattr__(
            reader,
            "_LifecycleReader__graph_validator",
            graph_validator,
        )
        object.__setattr__(
            reader,
            "_LifecycleReader__identity_reader",
            identity_reader,
        )
        return reader

    @property
    def primary_target(self) -> Path:
        return self.__primary_target

    @property
    def graph_validator(self) -> _GraphValidator:
        return self.__graph_validator

    def _trusted_implementation_identity(self) -> ImplementationIdentity:
        return self.__identity_reader()

    def classify(
        self,
        study_id: str,
        target: Path,
        publication_id: str,
    ) -> LifecycleClassification:
        if study_id != STUDY_ID:
            raise LifecycleScopeError("Reader study_id is outside the frozen study scope.")
        validate_publication_id(publication_id)
        canonical_target = normalize_target(target, primary_target=self.primary_target)
        lock = StudyLock.for_primary_target(self.primary_target)
        if not lock.acquire_shared(blocking=False):
            return LifecycleClassification(
                None,
                None,
                None,
                None,
                (),
                "NONE",
                operational=OperationalRead.WRITER_ACTIVE,
            )
        try:
            snapshot = self._snapshot(target, canonical_target, publication_id)
            family = self._build_family_index()
            return self._classify_snapshot(snapshot, family)
        finally:
            lock.release()

    def _snapshot(
        self,
        target: Path,
        canonical_target: str,
        publication_id: str,
    ) -> _SelectedSnapshot:
        paths = TargetPaths.from_target(
            target,
            publication_id,
            primary_target=self.primary_target,
        )
        mode, canonical = self._snapshot_canonical(paths.target)
        ledger: dict[str, bytes] = {}
        ledger_root_stat = _optional_lstat(paths.ledger_root)
        if ledger_root_stat is not None and not _stat_is_ordinary_directory(ledger_root_stat):
            ledger["<unsafe-ledger-root>"] = b""
        elif ledger_root_stat is not None:
            attempt_directory_stat = _optional_lstat(paths.attempt_directory)
            if attempt_directory_stat is not None and not _stat_is_ordinary_directory(
                attempt_directory_stat
            ):
                ledger["<unsafe-attempt-directory>"] = b""
            elif attempt_directory_stat is not None:
                for entry in paths.attempt_directory.iterdir():
                    entry_stat = os.lstat(entry)
                    if entry.name not in LEDGER_FINAL_NAMES or not _stat_is_ordinary_file(
                        entry_stat
                    ):
                        ledger[f"<unsafe-ledger-entry:{entry.name}>"] = b""
                    else:
                        ledger[entry.name] = entry.read_bytes()
        residue: list[str] = []
        staging = StagingLayout.from_target(
            paths.target,
            publication_id,
            primary_target=self.primary_target,
        ).root
        if _optional_lstat(staging) is not None:
            residue.append(staging.as_posix())
        return _SelectedSnapshot(
            paths.target,
            canonical_target,
            publication_id,
            MappingProxyType(ledger),
            MappingProxyType(canonical),
            mode,
            tuple(residue),
        )

    def _snapshot_canonical(self, target: Path) -> tuple[CanonicalMode, dict[str, bytes]]:
        target_stat = _optional_lstat(target)
        if target_stat is None:
            return CanonicalMode.ABSENT, {}
        if not _stat_is_ordinary_directory(target_stat):
            return CanonicalMode.INVALID, {}
        canonical: dict[str, bytes] = {}
        report = False
        for entry in target.iterdir():
            entry_stat = os.lstat(entry)
            if entry.name == OPTIONAL_REPORT_NAME and _stat_is_ordinary_file(entry_stat):
                report = True
                continue
            if entry.name not in ARTIFACT_FILENAMES or not _stat_is_ordinary_file(entry_stat):
                return CanonicalMode.INVALID, {}
            canonical[entry.name] = entry.read_bytes()
        if canonical:
            return CanonicalMode.CANONICAL_PRESENT, canonical
        if report:
            return CanonicalMode.REPORT_ONLY, {}
        return CanonicalMode.INVALID, {}

    def _unsafe_attributable_staging(
        self,
        snapshot: _SelectedSnapshot,
        namespace: NamespaceIdentifierScan,
        index: _FamilyIndex,
    ) -> bool:
        """Distinguish benign staging from attributable residue that blocks R1."""

        staging_parent = TargetPaths.from_target(
            snapshot.target,
            snapshot.publication_id,
            primary_target=self.primary_target,
        ).staging_parent

        def require_attributable(publication_root: Path) -> None:
            key = (snapshot.canonical_target, publication_root.name)
            publication = index.publications.get(key)
            if (
                publication is None
                or publication.local_attempt is None
                or key not in index.admitted
            ):
                raise LifecycleInvariantError(
                    "Unsafe staging residue is not attributable to one admitted prior attempt."
                )

        unsafe = False
        for publication_root in namespace.unsafe_staging_publications:
            if publication_root.parent == staging_parent:
                require_attributable(publication_root)
                unsafe = True
        if not os.path.lexists(staging_parent):
            return unsafe
        if not ordinary_directory(staging_parent):
            raise LifecycleInvariantError("The source staging namespace became unsafe.")
        try:
            publication_roots = tuple(staging_parent.iterdir())
            for publication_root in publication_roots:
                if (
                    not ordinary_directory(publication_root)
                    or PUBLICATION_PATTERN.fullmatch(publication_root.name) is None
                ):
                    raise LifecycleInvariantError(
                        "The source staging namespace became unclassifiable."
                    )
                layout = StagingLayout.from_target(
                    snapshot.target,
                    publication_root.name,
                    primary_target=self.primary_target,
                )
                directory_members = {
                    layout.attempt_publication.name: frozenset({"attempt.json"}),
                    layout.prepared_artifacts_1_11.name: frozenset(ARTIFACT_FILENAMES[:11]),
                    layout.artifacts_1_11_publication.name: frozenset(ARTIFACT_FILENAMES[:11]),
                }
                file_names = frozenset(
                    {
                        layout.stage_m11.name,
                        layout.stage_run_manifest.name,
                        layout.stage_m12.name,
                        layout.stage_recommendation.name,
                        layout.stage_m13.name,
                        layout.stage_failure.name,
                        layout.stage_mf.name,
                    }
                )
                for entry in publication_root.iterdir():
                    permitted = directory_members.get(entry.name)
                    if permitted is None:
                        if entry.name not in file_names or not ordinary_file(entry):
                            require_attributable(publication_root)
                            unsafe = True
                        continue
                    if not ordinary_directory(entry):
                        require_attributable(publication_root)
                        unsafe = True
                        continue
                    members = tuple(entry.iterdir())
                    if any(
                        member.name not in permitted or not ordinary_file(member)
                        for member in members
                    ):
                        require_attributable(publication_root)
                        unsafe = True
        except OSError as error:
            raise LifecycleInvariantError(
                "The source staging namespace changed or became unreadable."
            ) from error
        return unsafe

    def _classify_snapshot(
        self,
        snapshot: _SelectedSnapshot,
        index: _FamilyIndex | None = None,
    ) -> LifecycleClassification:
        family = self._build_family_index() if index is None else index
        if snapshot.mode is CanonicalMode.INVALID:
            return self._invalid(snapshot, None, "INVALID_CANONICAL_NAMESPACE")
        if any(name not in LEDGER_FINAL_NAMES for name in snapshot.ledger):
            return self._invalid(snapshot, None, "INVALID_LEDGER_NAMESPACE")
        evidence = bool(snapshot.ledger)
        if evidence:
            if "attempt.json" not in snapshot.ledger:
                return self._invalid(snapshot, None, "LEDGER_WITHOUT_ATTEMPT")
            return self._classify_amended(snapshot, family)
        return self._classify_without_ledger(snapshot, family)

    def _fixed_dispatch_attempt(self, snapshot: _SelectedSnapshot) -> Mapping[str, object]:
        value = parse_canonical_ledger_bytes(snapshot.ledger["attempt.json"])
        if not isinstance(value, Mapping):
            raise LifecycleInvariantError("Attempt dispatch value is not an object.")
        expected_identity = self._trusted_implementation_identity()
        fixed = {
            "study_id": STUDY_ID,
            "canonical_target": snapshot.canonical_target,
            "publication_id": snapshot.publication_id,
            "source_design_checkpoint": SOURCE_DESIGN_CHECKPOINT,
            "implementation_commit": expected_identity.implementation_commit,
            "implementation_tree_sha256": expected_identity.implementation_tree_sha256,
            "implementation_diff_sha256": expected_identity.implementation_diff_sha256,
        }
        for name, expected in fixed.items():
            if value.get(name) != expected:
                raise LifecycleInvariantError(f"Attempt dispatch binding differs: {name}.")
        checkpoint = value.get("protocol_checkpoint")
        if not isinstance(checkpoint, str) or re.fullmatch(r"[0-9a-f]{40}", checkpoint) is None:
            raise LifecycleInvariantError("Attempt checkpoint is malformed.")
        return value

    def _classify_amended(
        self,
        snapshot: _SelectedSnapshot,
        index: _FamilyIndex,
    ) -> LifecycleClassification:
        try:
            dispatch = self._fixed_dispatch_attempt(snapshot)
        except (
            CanonicalLedgerError,
            ValueError,
            TypeError,
            UnicodeError,
            LifecycleInvariantError,
        ):
            return self._invalid(snapshot, None, "INVALID_ATTEMPT_DISPATCH")
        checkpoint = cast(str, dispatch["protocol_checkpoint"])
        selected = ATTEMPT_READERS.get(checkpoint)
        if selected is None or checkpoint == SOURCE_DESIGN_CHECKPOINT:
            return self._invalid(
                snapshot,
                None,
                "UNKNOWN_OR_HISTORICAL_LEDGER_CHECKPOINT",
            )
        if not self._retry_tuple_has_closed_shape(dispatch):
            return self._invalid(
                snapshot,
                SelectedReader.AMENDED,
                "INVALID_RETRY_SOURCE_BINDING",
            )
        selected_key = (snapshot.canonical_target, snapshot.publication_id)
        try:
            records = {
                name: validate_record(
                    name,
                    content,
                    defer_attempt_retry_semantics=name == "attempt.json",
                )
                for name, content in snapshot.ledger.items()
            }
            attempt = records["attempt.json"]
            if not isinstance(attempt, AttemptRecord):
                raise LifecycleInvariantError("Attempt has the wrong record kind.")
            self._require_common_envelope(snapshot, attempt.envelope, records)
        except LifecycleRecordError as error:
            reason = "INVALID_RETRY_SOURCE_BINDING" if error.code == "RETRY_TUPLE" else "INVALID"
            return self._invalid(snapshot, SelectedReader.AMENDED, reason)
        except (ValueError, TypeError, ArtifactValidationError, LifecycleInvariantError):
            return self._invalid(snapshot, SelectedReader.AMENDED, "INVALID")

        key = selected_key
        failure = records.get("failure.json")
        typed_failure = failure if isinstance(failure, FailureRecord) else None
        if len(index.local_mf_candidates) > 1 and key in index.local_mf_candidates:
            return self._contextual_invalid(
                snapshot,
                "MULTIPLE_STUDY_SUCCESSES",
                snapshot.canonical,
                typed_failure,
            )
        source_key = (
            (
                cast(str, attempt.retry_source_canonical_target),
                cast(str, attempt.retry_of_publication_id),
            )
            if attempt.retry_kind is not None
            else None
        )
        source_publication = None if source_key is None else index.publications.get(source_key)
        implicated_source = key if len(index.allegations.get(key, frozenset())) > 1 else None
        implicated_child = (
            source_key
            if source_key is not None
            and source_publication is not None
            and self._publication_establishes_local_scope(source_publication)
            and key in index.allegations.get(source_key, frozenset())
            and len(index.allegations.get(source_key, frozenset())) > 1
            else None
        )
        if implicated_source is not None or implicated_child is not None:
            return self._contextual_invalid(
                snapshot,
                "MULTIPLE_RETRY_CHILDREN",
                {},
                typed_failure,
            )
        try:
            validate_attempt_retry_semantics(attempt)
            self._require_retry_binding(attempt, snapshot, index)
        except (LifecycleRecordError, LifecycleInvariantError):
            return self._contextual_invalid(
                snapshot,
                "INVALID_RETRY_SOURCE_BINDING",
                snapshot.canonical,
                typed_failure,
            )
        try:
            return self._classify_amended_prefix(snapshot, attempt, records, index)
        except (ValueError, TypeError, ArtifactValidationError, LifecycleInvariantError):
            return self._invalid(snapshot, SelectedReader.AMENDED, "INVALID")

    @staticmethod
    def _retry_tuple_has_closed_shape(value: Mapping[str, object]) -> bool:
        if any(name not in value for name in _RETRY_TUPLE_FIELDS):
            return False
        retry_kind = value["retry_kind"]
        if retry_kind is None:
            return all(value[name] is None for name in _RETRY_TUPLE_FIELDS[1:])
        if retry_kind not in {RetryKind.R1.value, RetryKind.RX.value}:
            return True
        if any(value[name] is None for name in _RETRY_REQUIRED_FIELDS):
            return False
        return retry_kind != RetryKind.R1.value or value["retry_source_failure_sha256"] is not None

    def _require_common_envelope(
        self,
        snapshot: _SelectedSnapshot,
        envelope: BindingEnvelope,
        records: Mapping[str, object],
    ) -> None:
        if (
            envelope.study_id != STUDY_ID
            or envelope.canonical_target != snapshot.canonical_target
            or envelope.publication_id != snapshot.publication_id
            or envelope.source_design_checkpoint != SOURCE_DESIGN_CHECKPOINT
            or envelope.protocol_checkpoint != PROTOCOL_CHECKPOINT
        ):
            raise LifecycleInvariantError("Attempt envelope differs from selected scope.")
        identity = self._trusted_implementation_identity()
        expected = (
            identity.implementation_commit,
            identity.implementation_tree_sha256,
            identity.implementation_diff_sha256,
        )
        if (
            envelope.implementation_commit,
            envelope.implementation_tree_sha256,
            envelope.implementation_diff_sha256,
        ) != expected:
            raise LifecycleInvariantError("Attempt implementation binding differs.")
        binding = (
            envelope.study_id,
            envelope.canonical_target,
            envelope.publication_id,
            envelope.source_design_checkpoint,
            envelope.protocol_checkpoint,
            envelope.implementation_commit,
            envelope.implementation_tree_sha256,
            envelope.implementation_diff_sha256,
            envelope.authorization_attempt_id,
        )
        for record in records.values():
            current = getattr(record, "envelope", None)
            current_binding = (
                (
                    current.study_id,
                    current.canonical_target,
                    current.publication_id,
                    current.source_design_checkpoint,
                    current.protocol_checkpoint,
                    current.implementation_commit,
                    current.implementation_tree_sha256,
                    current.implementation_diff_sha256,
                    current.authorization_attempt_id,
                )
                if isinstance(current, BindingEnvelope)
                else ()
            )
            if current_binding != binding:
                raise LifecycleInvariantError("Selected record envelopes disagree.")

    def _require_retry_binding(
        self,
        attempt: AttemptRecord,
        snapshot: _SelectedSnapshot,
        index: _FamilyIndex,
    ) -> None:
        key = (attempt.envelope.canonical_target, attempt.envelope.publication_id)
        publication = index.publications.get(key)
        if publication is None or publication.local_attempt != attempt or key not in index.admitted:
            raise LifecycleInvariantError("Selected attempt is not admitted in the family DAG.")
        if attempt.retry_kind is None:
            return
        source_key = (
            cast(str, attempt.retry_source_canonical_target),
            cast(str, attempt.retry_of_publication_id),
        )
        if (source_key, key) not in index.admitted_edges:
            raise LifecycleInvariantError("Retry source binding is not an admitted family edge.")

    def _validate_own_prefix(
        self,
        snapshot: _SelectedSnapshot,
        attempt: AttemptRecord,
        records: Mapping[str, object],
        *,
        canonical_override: Mapping[str, bytes] | None = None,
    ) -> _OwnPrefix:
        """Validate one publication without consulting lineage, owners, or successes."""

        self._require_common_envelope(snapshot, attempt.envelope, records)
        marker_names = tuple(name for name in ("M11", "M12", "M13", "MF") if name in records)
        if marker_names not in (
            (),
            ("M11",),
            ("M11", "M12"),
            ("M11", "M12", "M13"),
            ("M11", "M12", "M13", "MF"),
        ):
            raise LifecycleInvariantError("Selected marker set is not a legal prefix.")
        failure = records.get("failure.json")
        if failure is not None and not isinstance(failure, FailureRecord):
            raise LifecycleInvariantError("Selected failure has the wrong record type.")
        if failure is not None and "MF" in records:
            raise LifecycleInvariantError("failure.json cannot coexist with MF.")

        source = snapshot.canonical if canonical_override is None else canonical_override
        canonical = {name: source[name] for name in ARTIFACT_FILENAMES if name in source}
        if set(source) != set(canonical):
            raise LifecycleInvariantError("Canonical namespace contains an unknown artifact.")
        first_eleven = ARTIFACT_FILENAMES[:11]
        intended = {item.filename: item.byte_sha256 for item in attempt.intended_artifacts_1_11}
        for name, content in canonical.items():
            if name in first_eleven and raw_sha256(content) != intended[name]:
                raise LifecycleInvariantError("Canonical Artifact 1-11 hash differs from attempt.")
            if self._checkpoint_anchor(name, content) != PROTOCOL_CHECKPOINT:
                raise LifecycleInvariantError("Canonical checkpoint anchor differs from attempt.")

        present_eleven = tuple(name for name in first_eleven if name in canonical)
        manifest_present = "run_manifest.json" in canonical
        recommendation_present = "recommendation.json" in canonical
        if present_eleven == first_eleven:
            self.graph_validator.validate_11({name: canonical[name] for name in first_eleven})

        m11 = records.get("M11")
        if m11 is not None:
            if not isinstance(m11, M11Record) or present_eleven != first_eleven:
                raise LifecycleInvariantError("M11 lacks exact Artifacts 1-11.")
            if m11.attempt_sha256 != raw_sha256(snapshot.ledger["attempt.json"]):
                raise LifecycleInvariantError("M11 predecessor differs.")
            self._require_artifact_rows(m11.artifacts_1_11, canonical, 11)
        if manifest_present:
            if m11 is None or present_eleven != first_eleven:
                raise LifecycleInvariantError("Manifest appears before M11.")
            self.graph_validator.validate_12(
                {name: canonical[name] for name in ARTIFACT_FILENAMES[:12]}
            )
            self._require_manifest_implementation_binding(
                canonical["run_manifest.json"],
                attempt.envelope,
            )
        m12 = records.get("M12")
        if m12 is not None:
            if (
                not isinstance(m12, M12Record)
                or not manifest_present
                or not isinstance(m11, M11Record)
            ):
                raise LifecycleInvariantError("M12 lacks its manifest prefix.")
            if m12.m11_sha256 != record_sha256(m11):
                raise LifecycleInvariantError("M12 predecessor differs.")
            if m12.manifest_byte_sha256 != raw_sha256(canonical["run_manifest.json"]):
                raise LifecycleInvariantError("M12 manifest hash differs.")

        graph_error: ArtifactValidationError | None = None
        if recommendation_present:
            if m12 is None or not manifest_present:
                raise LifecycleInvariantError("Recommendation appears before M12.")
            try:
                self.graph_validator.validate_13(canonical)
            except ArtifactValidationError as error:
                graph_error = error
        m13 = records.get("M13")
        if m13 is not None:
            if (
                not isinstance(m13, M13Record)
                or not recommendation_present
                or not isinstance(m12, M12Record)
            ):
                raise LifecycleInvariantError("M13 lacks its recommendation prefix.")
            if m13.m12_sha256 != record_sha256(m12):
                raise LifecycleInvariantError("M13 predecessor differs.")
            if m13.recommendation_byte_sha256 != raw_sha256(canonical["recommendation.json"]):
                raise LifecycleInvariantError("M13 recommendation hash differs.")

        actual_inventory = self._inventory(
            _SelectedSnapshot(
                snapshot.target,
                snapshot.canonical_target,
                snapshot.publication_id,
                snapshot.ledger,
                MappingProxyType(dict(canonical)),
                snapshot.mode,
                snapshot.staging_residue,
            ),
            records,
        )
        typed_failure = failure if isinstance(failure, FailureRecord) else None
        if typed_failure is not None:
            if tuple(typed_failure.observed_inventory) != actual_inventory:
                raise LifecycleInvariantError("Failure inventory differs from selected prefix.")
            predecessor_bytes = snapshot.ledger.get(typed_failure.predecessor_filename.value)
            if predecessor_bytes is None or typed_failure.predecessor_sha256 != raw_sha256(
                predecessor_bytes
            ):
                raise LifecycleInvariantError("Failure predecessor differs from selected prefix.")
            if self._has_successor_after_failure(typed_failure, canonical, records):
                raise LifecycleInvariantError("Selected publication advanced after failure.")

        mf = records.get("MF")
        if graph_error is not None:
            compatible = (
                typed_failure is not None
                and typed_failure.phase is FailurePhase.GRAPH_VALIDATION
                and typed_failure.failed_transition is FailedTransition.M13_TO_GRAPH_VALIDATION
                and typed_failure.error_code is FailureErrorCode.VALIDATION_GRAPH
                and typed_failure.predecessor_filename is LedgerPredecessor.M13
                and isinstance(m13, M13Record)
                and mf is None
            )
            if not compatible:
                raise graph_error
            return _OwnPrefix(
                LifecycleState.INVALID,
                MappingProxyType(canonical),
                typed_failure,
                graph_invalid=True,
            )
        if typed_failure is not None and typed_failure.phase is FailurePhase.GRAPH_VALIDATION:
            transient_readback = (
                typed_failure.failed_transition is FailedTransition.M13_TO_GRAPH_VALIDATION
                and typed_failure.error_code is FailureErrorCode.IO_FINAL_READBACK
                and typed_failure.predecessor_filename is LedgerPredecessor.M13
                and isinstance(m13, M13Record)
                and mf is None
            )
            if not transient_readback:
                raise LifecycleInvariantError(
                    "Graph-validation failure contradicts the fresh selected graph."
                )
        if mf is not None:
            if not isinstance(mf, MFRecord) or not isinstance(m13, M13Record):
                raise LifecycleInvariantError("MF lacks M13.")
            if mf.m13_sha256 != record_sha256(m13):
                raise LifecycleInvariantError("MF predecessor differs.")
            self._require_artifact_rows(mf.artifacts_1_13, canonical, 13)
            return _OwnPrefix(
                LifecycleState.SUCCESS,
                MappingProxyType(canonical),
                typed_failure,
            )
        if not canonical:
            state = LifecycleState.ABORTED_BEFORE_PUBLICATION
        elif not manifest_present:
            state = LifecycleState.PARTIAL_SCIENTIFIC_PUBLICATION_INVALID
        elif not recommendation_present:
            state = LifecycleState.MANIFEST_PUBLISHED_INCOMPLETE
        else:
            state = LifecycleState.RECOMMENDATION_PUBLISHED_NOT_FINALIZED
        return _OwnPrefix(state, MappingProxyType(canonical), typed_failure)

    def _classify_amended_prefix(
        self,
        snapshot: _SelectedSnapshot,
        attempt: AttemptRecord,
        records: Mapping[str, object],
        index: _FamilyIndex,
    ) -> LifecycleClassification:
        selected_key = (snapshot.canonical_target, snapshot.publication_id)
        typed_failure = (
            records.get("failure.json")
            if isinstance(records.get("failure.json"), FailureRecord)
            else None
        )
        if snapshot.canonical:
            claims = index.owner_claims.get(snapshot.canonical_target, frozenset())
            if selected_key in claims:
                if claims != frozenset({selected_key}) or selected_key not in index.admitted:
                    return self._contextual_invalid(
                        snapshot,
                        "AMBIGUOUS_CROSS_ATTEMPT_ATTRIBUTION",
                        snapshot.canonical,
                        cast(FailureRecord | None, typed_failure),
                    )
            else:
                independent = {
                    claim
                    for claim in claims
                    if claim == _HISTORICAL_OWNER or claim in index.admitted
                }
                publication = index.publications.get(selected_key)
                own_empty = (
                    None
                    if publication is None
                    else self._empty_creation_prefix(publication, require_failure=False)
                )
                if len(claims) != 1 or claims != frozenset(independent) or own_empty is None:
                    return self._contextual_invalid(
                        snapshot,
                        "AMBIGUOUS_CROSS_ATTEMPT_ATTRIBUTION",
                        snapshot.canonical,
                        cast(FailureRecord | None, typed_failure),
                    )
                return self._result(
                    snapshot,
                    LifecycleState.ABORTED_BEFORE_PUBLICATION,
                    SelectedReader.AMENDED,
                    RetryDisposition.RN,
                    {},
                    own_empty.failure,
                    index,
                )
        marker_names = tuple(name for name in ("M11", "M12", "M13", "MF") if name in records)
        if marker_names not in (
            (),
            ("M11",),
            ("M11", "M12"),
            ("M11", "M12", "M13"),
            ("M11", "M12", "M13", "MF"),
        ):
            raise LifecycleInvariantError("Selected marker set is not a legal prefix.")
        failure = records.get("failure.json")
        if failure is not None and not isinstance(failure, FailureRecord):
            raise LifecycleInvariantError("Selected failure has the wrong record type.")
        if failure is not None and "MF" in records:
            raise LifecycleInvariantError("failure.json cannot coexist with MF.")

        canonical = {
            name: snapshot.canonical[name]
            for name in ARTIFACT_FILENAMES
            if name in snapshot.canonical
        }
        first_eleven = ARTIFACT_FILENAMES[:11]
        intended = {item.filename: item.byte_sha256 for item in attempt.intended_artifacts_1_11}
        for name in canonical:
            if name in first_eleven and raw_sha256(canonical[name]) != intended[name]:
                raise LifecycleInvariantError("Canonical Artifact 1-11 hash differs from attempt.")
            if self._checkpoint_anchor(name, canonical[name]) != PROTOCOL_CHECKPOINT:
                raise LifecycleInvariantError("Canonical checkpoint anchor differs from attempt.")

        present_eleven = tuple(name for name in first_eleven if name in canonical)
        manifest_present = "run_manifest.json" in canonical
        recommendation_present = "recommendation.json" in canonical
        m11 = records.get("M11")
        if m11 is not None:
            if not isinstance(m11, M11Record) or present_eleven != first_eleven:
                raise LifecycleInvariantError("M11 lacks exact Artifacts 1-11.")
            if m11.attempt_sha256 != raw_sha256(snapshot.ledger["attempt.json"]):
                raise LifecycleInvariantError("M11 predecessor differs.")
            self._require_artifact_rows(m11.artifacts_1_11, canonical, 11)
            self.graph_validator.validate_11({name: canonical[name] for name in first_eleven})
        if manifest_present:
            if m11 is None or present_eleven != first_eleven:
                raise LifecycleInvariantError("Manifest appears before M11.")
            self.graph_validator.validate_12(
                {name: canonical[name] for name in ARTIFACT_FILENAMES[:12]}
            )
            self._require_manifest_implementation_binding(
                canonical["run_manifest.json"],
                attempt.envelope,
            )
        m12 = records.get("M12")
        if m12 is not None:
            if (
                not isinstance(m12, M12Record)
                or not manifest_present
                or not isinstance(m11, M11Record)
            ):
                raise LifecycleInvariantError("M12 lacks its manifest prefix.")
            if m12.m11_sha256 != record_sha256(m11):
                raise LifecycleInvariantError("M12 predecessor differs.")
            if m12.manifest_byte_sha256 != raw_sha256(canonical["run_manifest.json"]):
                raise LifecycleInvariantError("M12 manifest hash differs.")
        graph_error: ArtifactValidationError | None = None
        if recommendation_present:
            if m12 is None or not manifest_present:
                raise LifecycleInvariantError("Recommendation appears before M12.")
            try:
                self.graph_validator.validate_13(canonical)
            except ArtifactValidationError as error:
                # M13 is still structurally inspectable when the full frozen graph
                # check itself failed.  That exact defect has one whitelisted
                # terminal diagnostic form, checked below after its prefix binding.
                graph_error = error
        m13 = records.get("M13")
        if m13 is not None:
            if (
                not isinstance(m13, M13Record)
                or not recommendation_present
                or not isinstance(m12, M12Record)
            ):
                raise LifecycleInvariantError("M13 lacks its recommendation prefix.")
            if m13.m12_sha256 != record_sha256(m12):
                raise LifecycleInvariantError("M13 predecessor differs.")
            if m13.recommendation_byte_sha256 != raw_sha256(canonical["recommendation.json"]):
                raise LifecycleInvariantError("M13 recommendation hash differs.")

        actual_inventory = self._inventory(snapshot, records)
        if isinstance(failure, FailureRecord):
            if tuple(failure.observed_inventory) != actual_inventory:
                raise LifecycleInvariantError("Failure inventory differs from selected prefix.")
            predecessor_name = failure.predecessor_filename.value
            predecessor_bytes = snapshot.ledger.get(predecessor_name)
            if predecessor_bytes is None or failure.predecessor_sha256 != raw_sha256(
                predecessor_bytes
            ):
                raise LifecycleInvariantError("Failure predecessor differs from selected prefix.")
            if self._has_successor_after_failure(failure, canonical, records):
                raise LifecycleInvariantError("Selected publication advanced after failure.")

        mf = records.get("MF")
        successes = set(index.valid_successes)
        alleged_children = self._alleged_children(attempt, index)
        if len(alleged_children) > 1:
            return self._result(
                snapshot,
                LifecycleState.INVALID,
                SelectedReader.AMENDED,
                RetryDisposition.RN,
                canonical,
                failure,
                index,
            )
        if graph_error is not None:
            compatible_graph_failure = (
                isinstance(failure, FailureRecord)
                and failure.phase is FailurePhase.GRAPH_VALIDATION
                and failure.failed_transition is FailedTransition.M13_TO_GRAPH_VALIDATION
                and failure.error_code is FailureErrorCode.VALIDATION_GRAPH
                and failure.predecessor_filename is LedgerPredecessor.M13
                and isinstance(m13, M13Record)
                and mf is None
            )
            if compatible_graph_failure:
                blocked = bool(successes) or bool(alleged_children)
                return self._result(
                    snapshot,
                    LifecycleState.INVALID,
                    SelectedReader.AMENDED,
                    RetryDisposition.RN if blocked else RetryDisposition.RX,
                    canonical,
                    failure,
                    index,
                )
            raise graph_error
        if isinstance(failure, FailureRecord) and failure.phase is FailurePhase.GRAPH_VALIDATION:
            transient_readback = (
                failure.failed_transition is FailedTransition.M13_TO_GRAPH_VALIDATION
                and failure.error_code is FailureErrorCode.IO_FINAL_READBACK
                and failure.predecessor_filename is LedgerPredecessor.M13
                and isinstance(m13, M13Record)
                and mf is None
            )
            if not transient_readback:
                raise LifecycleInvariantError(
                    "Graph-validation failure contradicts the fresh selected graph."
                )
        if mf is not None:
            if not isinstance(mf, MFRecord) or not isinstance(m13, M13Record):
                raise LifecycleInvariantError("MF lacks M13.")
            if mf.m13_sha256 != record_sha256(m13):
                raise LifecycleInvariantError("MF predecessor differs.")
            self._require_artifact_rows(mf.artifacts_1_13, canonical, 13)
            if len(successes) > 1 and selected_key in successes:
                return self._invalid(snapshot, SelectedReader.AMENDED, "MULTIPLE_STUDY_SUCCESSES")
            if successes != {selected_key}:
                raise LifecycleInvariantError("Selected MF is not the sole study success.")
            return self._result(
                snapshot,
                LifecycleState.SUCCESS,
                SelectedReader.AMENDED,
                RetryDisposition.RN,
                canonical,
                failure,
                index,
            )
        study_block = len(index.local_mf_candidates) > 1 or bool(successes)
        disposition = RetryDisposition.RN if study_block else RetryDisposition.RX
        if not canonical:
            state = LifecycleState.ABORTED_BEFORE_PUBLICATION
        elif not manifest_present:
            state = LifecycleState.PARTIAL_SCIENTIFIC_PUBLICATION_INVALID
        elif not recommendation_present:
            state = LifecycleState.MANIFEST_PUBLISHED_INCOMPLETE
        else:
            state = LifecycleState.RECOMMENDATION_PUBLISHED_NOT_FINALIZED
        if alleged_children:
            disposition = RetryDisposition.RN
        if snapshot.mode is CanonicalMode.REPORT_ONLY:
            disposition = RetryDisposition.RN
        if (
            state is LifecycleState.ABORTED_BEFORE_PUBLICATION
            and disposition is RetryDisposition.RX
            and not self._same_target_history_is_r1_safe(snapshot, index)
        ):
            disposition = RetryDisposition.RN
        return self._result(
            snapshot,
            state,
            SelectedReader.AMENDED,
            disposition,
            canonical,
            failure,
            index,
        )

    def _classify_without_ledger(
        self,
        snapshot: _SelectedSnapshot,
        index: _FamilyIndex,
    ) -> LifecycleClassification:
        if snapshot.mode in {CanonicalMode.ABSENT, CanonicalMode.REPORT_ONLY}:
            clean = (
                snapshot.mode is CanonicalMode.ABSENT
                and snapshot.target == self.primary_target
                and index.clean_initial_namespace
            )
            return self._result(
                snapshot,
                LifecycleState.NEVER_PUBLISHED,
                None,
                RetryDisposition.R0 if clean else RetryDisposition.RN,
                {},
                None,
                index,
            )
        if snapshot.target != self.primary_target:
            return self._invalid(snapshot, None, "HISTORICAL_TARGET_MISMATCH")
        try:
            anchors = {
                self._checkpoint_anchor(name, content)
                for name, content in snapshot.canonical.items()
            }
            if anchors != {SOURCE_DESIGN_CHECKPOINT}:
                return self._invalid(
                    snapshot,
                    None,
                    "AMENDED_OR_UNKNOWN_CANONICAL_DATA_WITHOUT_ATTEMPT",
                )
            if set(snapshot.canonical) != set(ARTIFACT_FILENAMES):
                return self._invalid(snapshot, SelectedReader.HISTORICAL, "INVALID")
            historical = {name: snapshot.canonical[name] for name in ARTIFACT_FILENAMES}
            self.graph_validator.validate_historical(historical)
        except (ValueError, TypeError, ArtifactValidationError, LifecycleInvariantError):
            return self._invalid(snapshot, SelectedReader.HISTORICAL, "INVALID")
        return self._result(
            snapshot,
            LifecycleState.SUCCESS,
            SelectedReader.HISTORICAL,
            RetryDisposition.RN,
            historical,
            None,
            index,
        )

    def _checkpoint_anchor(self, filename: str, content: bytes) -> str:
        try:
            if filename.endswith(".json"):
                value = json.loads(content)
                if not isinstance(value, Mapping):
                    raise ValueError
                anchor = value.get("source_checkpoint_identifier")
            elif filename.endswith(".jsonl"):
                first = content.splitlines()[0]
                value = json.loads(first)
                if not isinstance(value, Mapping):
                    raise ValueError
                anchor = value.get("source_checkpoint_identifier")
            elif filename.endswith(".csv"):
                text = content.decode("utf-8")
                rows = csv.DictReader(text.splitlines())
                first_row = next(rows)
                anchor = first_row.get("source_checkpoint_identifier")
            else:
                raise ValueError
        except (UnicodeError, json.JSONDecodeError, StopIteration, IndexError, ValueError) as error:
            raise LifecycleInvariantError("Canonical checkpoint anchor is malformed.") from error
        if not isinstance(anchor, str) or re.fullmatch(r"[0-9a-f]{40}", anchor) is None:
            raise LifecycleInvariantError("Canonical checkpoint anchor is malformed.")
        return anchor

    def _require_manifest_implementation_binding(
        self,
        content: bytes,
        envelope: BindingEnvelope,
    ) -> None:
        try:
            value = json.loads(content)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise LifecycleInvariantError(
                "Manifest implementation binding is unreadable."
            ) from error
        if not isinstance(value, Mapping):
            raise LifecycleInvariantError("Manifest implementation binding is not an object.")
        expected = {
            "implementation_commit": envelope.implementation_commit,
            "implementation_tree_sha256": envelope.implementation_tree_sha256,
            "implementation_diff_sha256": envelope.implementation_diff_sha256,
        }
        if any(value.get(field) != bound for field, bound in expected.items()):
            raise LifecycleInvariantError("Manifest implementation identity differs from attempt.")

    def _require_artifact_rows(
        self,
        rows: Sequence[ArtifactHash],
        canonical: Mapping[str, bytes],
        count: int,
    ) -> None:
        expected = ARTIFACT_FILENAMES[:count]
        if tuple(item.filename for item in rows) != expected:
            raise LifecycleInvariantError("Marker artifact inventory order differs.")
        for item in rows:
            if item.filename not in canonical or item.byte_sha256 != raw_sha256(
                canonical[item.filename]
            ):
                raise LifecycleInvariantError("Marker artifact hash differs.")

    def _inventory(
        self,
        snapshot: _SelectedSnapshot,
        records: Mapping[str, object],
    ) -> tuple[InventoryEntry, ...]:
        values: list[InventoryEntry] = [
            InventoryEntry(
                InventoryNamespace.LEDGER,
                "attempt.json",
                raw_sha256(snapshot.ledger["attempt.json"]),
            )
        ]
        for name in ARTIFACT_FILENAMES[:11]:
            if name in snapshot.canonical:
                values.append(
                    InventoryEntry(
                        InventoryNamespace.CANONICAL,
                        name,
                        raw_sha256(snapshot.canonical[name]),
                    )
                )
        for ledger, canonical in (
            ("M11", None),
            (None, "run_manifest.json"),
            ("M12", None),
            (None, "recommendation.json"),
            ("M13", None),
        ):
            if ledger is not None and ledger in records:
                values.append(
                    InventoryEntry(
                        InventoryNamespace.LEDGER,
                        ledger,
                        raw_sha256(snapshot.ledger[ledger]),
                    )
                )
            if canonical is not None and canonical in snapshot.canonical:
                values.append(
                    InventoryEntry(
                        InventoryNamespace.CANONICAL,
                        canonical,
                        raw_sha256(snapshot.canonical[canonical]),
                    )
                )
        return tuple(values)

    def _has_successor_after_failure(
        self,
        failure: FailureRecord,
        canonical: Mapping[str, bytes],
        records: Mapping[str, object],
    ) -> bool:
        predecessor_order = {
            LedgerPredecessor.ATTEMPT: 0,
            LedgerPredecessor.M11: 1,
            LedgerPredecessor.M12: 2,
            LedgerPredecessor.M13: 3,
        }[failure.predecessor_filename]
        occupied_order = max(
            (
                index
                for index, name in enumerate(("attempt.json", "M11", "M12", "M13"))
                if name in records
            ),
            default=0,
        )
        if occupied_order > predecessor_order:
            return True
        if predecessor_order == 0:
            expected = sum(
                1
                for item in failure.observed_inventory
                if item.namespace is InventoryNamespace.CANONICAL
            )
            return len(canonical) > expected
        return False

    def _parse_alleged_source_key(self, attempt_bytes: bytes) -> _PublicationKey | None:
        def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
            value: dict[str, object] = {}
            for name, item in pairs:
                if name in value:
                    raise ValueError("duplicate JSON key")
                value[name] = item
            return value

        try:
            text = attempt_bytes.decode("utf-8", errors="strict")
            value = json.loads(text, object_pairs_hook=unique_object)
        except (UnicodeError, json.JSONDecodeError, ValueError):
            return None
        if not isinstance(value, Mapping):
            return None
        if (
            value.get("study_id") != STUDY_ID
            or value.get("source_design_checkpoint") != SOURCE_DESIGN_CHECKPOINT
            or value.get("protocol_checkpoint") != PROTOCOL_CHECKPOINT
        ):
            return None
        source_target = value.get("retry_source_canonical_target")
        source_publication = value.get("retry_of_publication_id")
        if not isinstance(source_target, str) or not isinstance(source_publication, str):
            return None
        if PUBLICATION_PATTERN.fullmatch(source_publication) is None:
            return None
        try:
            normalized = normalize_target(
                Path(source_target),
                primary_target=self.primary_target,
            )
        except (LifecycleIOError, OSError, ValueError, TypeError):
            return None
        if normalized != source_target:
            return None
        return (source_target, source_publication)

    def _publication_establishes_local_scope(self, publication: _FamilyPublication) -> bool:
        """Establish only the source scope needed before multiple-allegation precedence."""

        attempt_bytes = publication.snapshot.ledger.get("attempt.json")
        if attempt_bytes is None:
            return False

        def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
            value: dict[str, object] = {}
            for name, item in pairs:
                if name in value:
                    raise ValueError("duplicate JSON key")
                value[name] = item
            return value

        try:
            text = attempt_bytes.decode("utf-8", errors="strict")
            value = json.loads(text, object_pairs_hook=unique_object)
        except (UnicodeError, json.JSONDecodeError, ValueError):
            return False
        return bool(
            isinstance(value, Mapping)
            and value.get("study_id") == STUDY_ID
            and value.get("source_design_checkpoint") == SOURCE_DESIGN_CHECKPOINT
            and value.get("protocol_checkpoint") == PROTOCOL_CHECKPOINT
            and value.get("canonical_target") == publication.key[0]
            and value.get("publication_id") == publication.key[1]
        )

    def _local_attempt(
        self,
        snapshot: _SelectedSnapshot,
        attempt_bytes: bytes,
    ) -> AttemptRecord | None:
        try:
            record = validate_record("attempt.json", attempt_bytes)
        except (CanonicalLedgerError, ValueError, TypeError, UnicodeError):
            return None
        if not isinstance(record, AttemptRecord):
            return None
        envelope = record.envelope
        identity = self._trusted_implementation_identity()
        if (
            envelope.canonical_target != snapshot.canonical_target
            or envelope.publication_id != snapshot.publication_id
            or (
                envelope.implementation_commit,
                envelope.implementation_tree_sha256,
                envelope.implementation_diff_sha256,
            )
            != (
                identity.implementation_commit,
                identity.implementation_tree_sha256,
                identity.implementation_diff_sha256,
            )
        ):
            return None
        if record.retry_kind is None:
            return record if snapshot.target == self.primary_target else None
        source_target = cast(str, record.retry_source_canonical_target)
        try:
            normalized_source = normalize_target(
                Path(source_target),
                primary_target=self.primary_target,
            )
        except (LifecycleIOError, OSError, ValueError, TypeError):
            return None
        if normalized_source != source_target:
            return None
        if record.retry_kind is RetryKind.R1:
            if snapshot.canonical_target != source_target:
                return None
        else:
            expected = self.primary_target.with_name(
                f"{self.primary_target.name}.retry-{snapshot.publication_id}"
            )
            if snapshot.target != expected or snapshot.canonical_target == source_target:
                return None
        if record.retry_of_publication_id == snapshot.publication_id:
            return None
        return record

    def _empty_creation_prefix(
        self,
        publication: _FamilyPublication,
        *,
        require_failure: bool,
    ) -> _OwnPrefix | None:
        if publication.records is None or publication.local_attempt is None:
            return None
        expected_names = {"attempt.json", "failure.json"}
        observed_names = set(publication.snapshot.ledger)
        if require_failure:
            if observed_names != expected_names:
                return None
        elif observed_names not in ({"attempt.json"}, expected_names):
            return None
        try:
            prefix = self._validate_own_prefix(
                publication.snapshot,
                publication.local_attempt,
                publication.records,
                canonical_override={},
            )
        except (LifecycleIOError, OSError, ValueError, TypeError, ArtifactValidationError):
            return None
        if prefix.state is not LifecycleState.ABORTED_BEFORE_PUBLICATION:
            return None
        if require_failure and prefix.failure is None:
            return None
        if prefix.failure is not None and tuple(prefix.failure.observed_inventory)[1:]:
            return None
        return prefix

    @staticmethod
    def _raw_failure_details_sha256(value: Mapping[str, object]) -> str:
        names = (
            "study_id",
            "canonical_target",
            "publication_id",
            "source_design_checkpoint",
            "protocol_checkpoint",
            "implementation_commit",
            "implementation_tree_sha256",
            "implementation_diff_sha256",
            "authorization_attempt_id",
            "phase",
            "failed_transition",
            "error_code",
            "predecessor_filename",
            "predecessor_sha256",
            "observed_inventory",
        )
        details = {name: value[name] for name in names}
        return raw_sha256(
            canonical_json_bytes(["rde.broader.lifecycle.failure-details/v1", details])
        )

    def _foreign_scope_i0_publication_is_unrelated(
        self,
        publication: _FamilyPublication,
    ) -> bool:
        """Prove a foreign-scope I0 publication without admitting it locally."""

        observed_names = set(publication.snapshot.ledger)
        if observed_names not in ({"attempt.json"}, {"attempt.json", "failure.json"}):
            return False
        values: dict[str, dict[str, object]] = {}
        validated: dict[str, object] = {}
        binding_names = (
            "study_id",
            "canonical_target",
            "publication_id",
            "source_design_checkpoint",
            "protocol_checkpoint",
            "implementation_commit",
            "implementation_tree_sha256",
            "implementation_diff_sha256",
            "authorization_attempt_id",
        )
        expected_binding: tuple[object, ...] | None = None
        try:
            for name in sorted(observed_names):
                parsed = parse_canonical_ledger_bytes(publication.snapshot.ledger[name])
                if type(parsed) is not dict:
                    return False
                value = parsed
                if set(value) != set(RECORD_FIELDS[name]):
                    return False
                if (value["schema_version"], value["kind"]) != RECORD_SCHEMA_KIND[name]:
                    return False
                binding = tuple(value[field] for field in binding_names)
                if expected_binding is None:
                    expected_binding = binding
                elif binding != expected_binding:
                    return False
                values[name] = value

            attempt_value = values["attempt.json"]
            study_id = attempt_value["study_id"]
            canonical_target = attempt_value["canonical_target"]
            publication_id = attempt_value["publication_id"]
            source_checkpoint = attempt_value["source_design_checkpoint"]
            checkpoint = attempt_value["protocol_checkpoint"]
            implementation_commit = attempt_value["implementation_commit"]
            implementation_tree = attempt_value["implementation_tree_sha256"]
            implementation_diff = attempt_value["implementation_diff_sha256"]
            authorization_id = attempt_value["authorization_attempt_id"]
            if (
                type(study_id) is not str
                or not study_id
                or type(canonical_target) is not str
                or canonical_target != publication.snapshot.canonical_target
                or type(publication_id) is not str
                or publication_id != publication.key[1]
                or PUBLICATION_PATTERN.fullmatch(publication_id) is None
                or source_checkpoint != SOURCE_DESIGN_CHECKPOINT
                or type(checkpoint) is not str
                or re.fullmatch(r"[0-9a-f]{40}", checkpoint) is None
                or type(implementation_commit) is not str
                or re.fullmatch(r"[0-9a-f]{40}", implementation_commit) is None
                or type(implementation_tree) is not str
                or re.fullmatch(r"[0-9a-f]{64}", implementation_tree) is None
                or type(implementation_diff) is not str
                or re.fullmatch(r"[0-9a-f]{64}", implementation_diff) is None
                or type(authorization_id) is not str
                or AUTHORIZATION_PATTERN.fullmatch(authorization_id) is None
                or (study_id == STUDY_ID and checkpoint == PROTOCOL_CHECKPOINT)
            ):
                return False
            normalized_target = normalize_target(
                Path(canonical_target),
                primary_target=self.primary_target,
            )
            if normalized_target != canonical_target:
                return False

            for name, original in values.items():
                translated = dict(original)
                translated["study_id"] = STUDY_ID
                translated["source_design_checkpoint"] = SOURCE_DESIGN_CHECKPOINT
                translated["protocol_checkpoint"] = PROTOCOL_CHECKPOINT
                if name == "failure.json":
                    if original["details_sha256"] != self._raw_failure_details_sha256(original):
                        return False
                    translated["details_sha256"] = self._raw_failure_details_sha256(translated)
                validated[name] = validate_record(
                    name,
                    canonical_ledger_bytes(translated),
                )
        except (
            CanonicalLedgerError,
            LifecycleIOError,
            OSError,
            KeyError,
            ValueError,
            TypeError,
            UnicodeError,
        ):
            return False

        attempt_record = validated.get("attempt.json")
        if not isinstance(attempt_record, AttemptRecord):
            return False
        failure_record = validated.get("failure.json")
        if failure_record is None:
            return True
        if not isinstance(failure_record, FailureRecord):
            return False
        inventory = tuple(failure_record.observed_inventory)
        return (
            failure_record.predecessor_filename is LedgerPredecessor.ATTEMPT
            and failure_record.predecessor_sha256 == raw_sha256(publication.attempt_bytes)
            and len(inventory) == 1
            and inventory[0].namespace is InventoryNamespace.LEDGER
            and inventory[0].filename == "attempt.json"
            and inventory[0].byte_sha256 == raw_sha256(publication.attempt_bytes)
        )

    def _same_target_history_is_r1_safe(
        self,
        snapshot: _SelectedSnapshot,
        index: _FamilyIndex,
        *,
        selected_requires_failure: bool = False,
    ) -> bool:
        selected_key = (snapshot.canonical_target, snapshot.publication_id)
        if snapshot.target in index.unsafe_family_targets:
            return False
        for key in index.occupied_publications:
            if key[0] != snapshot.canonical_target:
                continue
            publication = index.publications.get(key)
            if publication is None:
                return False
            if publication.local_attempt is None:
                if self._foreign_scope_i0_publication_is_unrelated(publication):
                    continue
                return False
            if key not in index.admitted:
                return False
            require_failure = key != selected_key or selected_requires_failure
            if (
                self._empty_creation_prefix(
                    publication,
                    require_failure=require_failure,
                )
                is None
            ):
                return False
        return True

    def _local_retry_edge(
        self,
        source: _FamilyPublication,
        child: _FamilyPublication,
        allegations: Mapping[_PublicationKey, frozenset[_PublicationKey]],
    ) -> bool:
        source_attempt = source.local_attempt
        child_attempt = child.local_attempt
        if source_attempt is None or child_attempt is None or child_attempt.retry_kind is None:
            return False
        if source.key == child.key:
            return False
        if (
            child_attempt.retry_source_canonical_target != source.key[0]
            or child_attempt.retry_of_publication_id != source.key[1]
            or child_attempt.retry_source_authorization_attempt_id
            != source_attempt.envelope.authorization_attempt_id
            or child_attempt.retry_source_attempt_sha256 != raw_sha256(source.attempt_bytes)
            or child_attempt.envelope.authorization_attempt_id
            == source_attempt.envelope.authorization_attempt_id
        ):
            return False
        if (
            child_attempt.envelope.study_id,
            child_attempt.envelope.source_design_checkpoint,
            child_attempt.envelope.protocol_checkpoint,
            child_attempt.envelope.implementation_commit,
            child_attempt.envelope.implementation_tree_sha256,
            child_attempt.envelope.implementation_diff_sha256,
        ) != (
            source_attempt.envelope.study_id,
            source_attempt.envelope.source_design_checkpoint,
            source_attempt.envelope.protocol_checkpoint,
            source_attempt.envelope.implementation_commit,
            source_attempt.envelope.implementation_tree_sha256,
            source_attempt.envelope.implementation_diff_sha256,
        ):
            return False
        if allegations.get(source.key, frozenset()) != frozenset({child.key}):
            return False
        failure_bytes = source.snapshot.ledger.get("failure.json")
        if child_attempt.retry_source_failure_sha256 is None:
            if failure_bytes is not None:
                return False
        elif (
            failure_bytes is None
            or raw_sha256(failure_bytes) != child_attempt.retry_source_failure_sha256
        ):
            return False
        creation = (
            self._empty_creation_prefix(source, require_failure=True)
            if child_attempt.retry_kind is RetryKind.R1
            else source.own_prefix
        )
        if creation is None or creation.state is LifecycleState.SUCCESS:
            return False
        if child_attempt.retry_kind is RetryKind.R1 and creation.failure is None:
            return False
        try:
            expected_result = RetryTerminalResult(creation.state.value)
        except ValueError:
            return False
        return child_attempt.retry_source_terminal_result is expected_result

    def _historical_owner_claim(self, snapshot: _SelectedSnapshot) -> bool:
        if snapshot.target != self.primary_target or set(snapshot.canonical) != set(
            ARTIFACT_FILENAMES
        ):
            return False
        try:
            historical = {name: snapshot.canonical[name] for name in ARTIFACT_FILENAMES}
            if {self._checkpoint_anchor(name, content) for name, content in historical.items()} != {
                SOURCE_DESIGN_CHECKPOINT
            }:
                return False
            self.graph_validator.validate_historical(historical)
        except (LifecycleIOError, OSError, ValueError, TypeError, ArtifactValidationError):
            return False
        return True

    def _build_family_index(self, *, strict_namespace: bool = False) -> _FamilyIndex:
        family_scan = self._scan_family(strict_namespace=strict_namespace)
        raw_publications: dict[_PublicationKey, tuple[_SelectedSnapshot, bytes]] = {}
        for target, publication_id, attempt_bytes in family_scan.attempts:
            canonical_target = normalize_target(target, primary_target=self.primary_target)
            snapshot = self._snapshot(target, canonical_target, publication_id)
            raw_publications[(canonical_target, publication_id)] = (snapshot, attempt_bytes)

        allegations_mutable: dict[_PublicationKey, set[_PublicationKey]] = {}
        for child_key, (_snapshot, attempt_bytes) in raw_publications.items():
            source_key = self._parse_alleged_source_key(attempt_bytes)
            if source_key is not None:
                allegations_mutable.setdefault(source_key, set()).add(child_key)
        allegations = {key: frozenset(children) for key, children in allegations_mutable.items()}

        publications: dict[_PublicationKey, _FamilyPublication] = {}
        for key, (snapshot, attempt_bytes) in raw_publications.items():
            local_attempt = self._local_attempt(snapshot, attempt_bytes)
            records: dict[str, object] | None = None
            own_prefix: _OwnPrefix | None = None
            if local_attempt is not None:
                try:
                    records = {
                        name: validate_record(name, content)
                        for name, content in snapshot.ledger.items()
                    }
                except (
                    LifecycleIOError,
                    OSError,
                    ValueError,
                    TypeError,
                    ArtifactValidationError,
                ):
                    records = None
                if records is not None:
                    try:
                        own_prefix = self._validate_own_prefix(
                            snapshot,
                            local_attempt,
                            records,
                        )
                    except (
                        LifecycleIOError,
                        OSError,
                        ValueError,
                        TypeError,
                        ArtifactValidationError,
                    ):
                        own_prefix = None
            publications[key] = _FamilyPublication(
                key,
                snapshot,
                attempt_bytes,
                local_attempt,
                None if records is None else MappingProxyType(records),
                own_prefix,
            )

        local_mf_candidates = frozenset(
            key
            for key, publication in publications.items()
            if publication.own_prefix is not None
            and publication.own_prefix.state is LifecycleState.SUCCESS
            and set(publication.snapshot.ledger) == {"attempt.json", "M11", "M12", "M13", "MF"}
        )

        potential_edges: set[tuple[_PublicationKey, _PublicationKey]] = set()
        for child_key, child in publications.items():
            attempt = child.local_attempt
            if attempt is None or attempt.retry_kind is None:
                continue
            source_key = (
                cast(str, attempt.retry_source_canonical_target),
                cast(str, attempt.retry_of_publication_id),
            )
            source = publications.get(source_key)
            if source is not None and self._local_retry_edge(source, child, allegations):
                potential_edges.add((source_key, child_key))

        root_candidates = {
            key
            for key, publication in publications.items()
            if publication.local_attempt is not None
            and publication.local_attempt.retry_kind is None
            and publication.snapshot.target == self.primary_target
        }
        admitted: set[_PublicationKey] = (
            set(root_candidates) if len(root_candidates) == 1 else set()
        )
        admitted_publication_ids = {key[1] for key in admitted}
        admitted_authorization_ids = {
            cast(AttemptRecord, publications[key].local_attempt).envelope.authorization_attempt_id
            for key in admitted
        }
        publication_id_owners: dict[str, set[_PublicationKey]] = {}
        authorization_id_owners: dict[str, set[_PublicationKey]] = {}
        for key, publication in publications.items():
            local_attempt = publication.local_attempt
            if local_attempt is None:
                continue
            publication_id_owners.setdefault(key[1], set()).add(key)
            authorization_id_owners.setdefault(
                local_attempt.envelope.authorization_attempt_id,
                set(),
            ).add(key)
        admitted_edges: set[tuple[_PublicationKey, _PublicationKey]] = set()
        changed = True
        while changed:
            changed = False
            for edge in sorted(potential_edges):
                source_key, child_key = edge
                if source_key in admitted and child_key not in admitted:
                    child_attempt = publications[child_key].local_attempt
                    if child_attempt is None or (
                        child_key[1] in admitted_publication_ids
                        or child_attempt.envelope.authorization_attempt_id
                        in admitted_authorization_ids
                        or len(publication_id_owners[child_key[1]]) != 1
                        or len(
                            authorization_id_owners[child_attempt.envelope.authorization_attempt_id]
                        )
                        != 1
                    ):
                        continue
                    admitted.add(child_key)
                    admitted_edges.add(edge)
                    admitted_publication_ids.add(child_key[1])
                    admitted_authorization_ids.add(child_attempt.envelope.authorization_attempt_id)
                    changed = True

        owner_claims_mutable: dict[str, set[_PublicationKey]] = {}
        representative_by_target: dict[str, _SelectedSnapshot] = {}
        for key, publication in publications.items():
            representative_by_target.setdefault(key[0], publication.snapshot)
            if publication.own_prefix is not None and publication.own_prefix.canonical:
                owner_claims_mutable.setdefault(key[0], set()).add(key)
        for target_key, snapshot in representative_by_target.items():
            if self._historical_owner_claim(snapshot):
                owner_claims_mutable.setdefault(target_key, set()).add(_HISTORICAL_OWNER)
        owner_claims = {
            target: frozenset(claims) for target, claims in owner_claims_mutable.items()
        }

        valid_successes: set[_PublicationKey] = set()
        if len(local_mf_candidates) == 1:
            candidate = next(iter(local_mf_candidates))
            if (
                candidate in admitted
                and owner_claims.get(candidate[0], frozenset()) == frozenset({candidate})
                and len(allegations.get(candidate, frozenset())) <= 1
            ):
                valid_successes.add(candidate)
        return _FamilyIndex(
            MappingProxyType(publications),
            family_scan.occupied_publications,
            MappingProxyType(allegations),
            local_mf_candidates,
            frozenset(admitted),
            frozenset(admitted_edges),
            MappingProxyType(owner_claims),
            frozenset(valid_successes),
            frozenset(family_scan.namespace.unsafe_family_targets),
            family_scan.namespace.malformed_family_history,
            not family_scan.namespace.targets
            and not family_scan.occupied_publications
            and not family_scan.namespace.malformed_family_history,
        )

    @staticmethod
    def _empty_family_index() -> _FamilyIndex:
        return _FamilyIndex(
            MappingProxyType({}),
            frozenset(),
            MappingProxyType({}),
            frozenset(),
            frozenset(),
            frozenset(),
            MappingProxyType({}),
            frozenset(),
            frozenset(),
            False,
            False,
        )

    def _alleged_children(
        self,
        source: AttemptRecord,
        index: _FamilyIndex | None = None,
    ) -> tuple[_PublicationKey, ...]:
        current = self._build_family_index() if index is None else index
        source_key = (
            source.envelope.canonical_target,
            source.envelope.publication_id,
        )
        return tuple(sorted(current.allegations.get(source_key, frozenset())))

    def _scan_family(
        self,
        *,
        strict_namespace: bool = False,
    ) -> _FamilyScan:
        attempts: list[tuple[Path, str, bytes]] = []
        occupied_publications: set[_PublicationKey] = set()
        namespace = scan_lifecycle_namespace(
            self.primary_target,
            inspect_staging=strict_namespace,
            allow_observed_unsafe=not strict_namespace,
        )
        suffix = ".rde-attempts"
        for root in namespace.ledger_roots:
            target = root.with_name(root.name[: -len(suffix)])
            target_is_observed_unsafe = target in namespace.unsafe_family_targets
            if not ordinary_directory(root) or not root.name.endswith(suffix):
                if not strict_namespace and target_is_observed_unsafe:
                    continue
                raise UnsafePathError("Family ledger root changed after the global scan.")
            canonical_target = normalize_target(target, primary_target=self.primary_target)
            for entry in root.iterdir():
                try:
                    validate_publication_id(entry.name)
                except UnsafePathError:
                    if not strict_namespace and target_is_observed_unsafe:
                        continue
                    raise
                if not ordinary_directory(entry):
                    if not strict_namespace and target_is_observed_unsafe:
                        continue
                    raise UnsafePathError(
                        "Family publication directory changed after the global scan."
                    )
                members = tuple(entry.iterdir())
                if members:
                    occupied_publications.add((canonical_target, entry.name))
                attempt = entry / "attempt.json"
                if not os.path.lexists(attempt):
                    continue
                if not ordinary_file(attempt):
                    if not strict_namespace and target_is_observed_unsafe:
                        continue
                    raise UnsafePathError("Family attempt changed after the global scan.")
                try:
                    attempt_bytes = attempt.read_bytes()
                except OSError as error:
                    raise UnsafePathError(
                        "Family attempt became unreadable after the global scan."
                    ) from error
                attempts.append((target, entry.name, attempt_bytes))
        return _FamilyScan(
            namespace,
            tuple(attempts),
            frozenset(occupied_publications),
        )

    def _local_primary_roots(self) -> set[tuple[str, str]]:
        index = self._build_family_index()
        return {
            key
            for key, publication in index.publications.items()
            if publication.local_attempt is not None
            and publication.local_attempt.retry_kind is None
            and publication.snapshot.target == self.primary_target
        }

    def _local_success_candidates(
        self,
        *,
        lock_already_held: bool,
    ) -> set[tuple[str, str]]:
        del lock_already_held
        index = self._build_family_index(strict_namespace=True)
        candidates = (
            index.local_mf_candidates
            if len(index.local_mf_candidates) > 1
            else index.valid_successes
        )
        return set(candidates)

    def _validate_retry_source_for_creation(
        self,
        source: RetrySource,
        prepared: PreparedAttempt,
        *,
        allow_missing_r1_failure: bool = False,
    ) -> RetrySource:
        if type(source) is not RetrySource or type(source.kind) is not RetryKind:
            raise LifecycleInvariantError("Retry nomination has an invalid structural type.")
        target = Path(source.canonical_target)
        canonical_target = normalize_target(target, primary_target=self.primary_target)
        if canonical_target != source.canonical_target:
            raise LifecycleInvariantError(
                "Retry source target is not its exact normalized identity."
            )
        snapshot = self._snapshot(target, canonical_target, source.publication_id)
        attempt_bytes = snapshot.ledger.get("attempt.json")
        if attempt_bytes is None or raw_sha256(attempt_bytes) != source.attempt_sha256:
            raise LifecycleInvariantError("Retry source attempt hash changed.")
        source_attempt = validate_record("attempt.json", attempt_bytes)
        if (
            not isinstance(source_attempt, AttemptRecord)
            or source_attempt.envelope.authorization_attempt_id != source.authorization_attempt_id
        ):
            raise LifecycleInvariantError("Retry source authorization identity changed.")
        failure_bytes = snapshot.ledger.get("failure.json")
        if source.failure_sha256 is None:
            if failure_bytes is not None:
                raise LifecycleInvariantError("Retry source acquired an unbound failure record.")
        elif failure_bytes is None or raw_sha256(failure_bytes) != source.failure_sha256:
            raise LifecycleInvariantError("Retry source failure hash changed.")
        index = self._build_family_index(strict_namespace=True)
        classification = self._classify_snapshot(snapshot, index)
        if classification.terminal_state is None or classification.terminal_state.value != (
            source.terminal_result.value
        ):
            raise LifecycleInvariantError("Retry source terminal state changed.")
        if classification.retry_disposition is not RetryDisposition.RX:
            raise LifecycleInvariantError("Retry source is not currently RX eligible.")
        namespace = scan_lifecycle_namespace(self.primary_target)
        unsafe_staging = self._unsafe_attributable_staging(snapshot, namespace, index)
        if source.kind is RetryKind.R1 and prepared.canonical_target != source.canonical_target:
            raise LifecycleInvariantError("R1 child target differs from its source.")
        if source.kind is RetryKind.RX:
            expected_target = self.primary_target.with_name(
                f"{self.primary_target.name}.retry-{prepared.publication_id}"
            )
            if prepared.target != expected_target or prepared.canonical_target != normalize_target(
                expected_target, primary_target=self.primary_target
            ):
                raise LifecycleInvariantError(
                    "RX child target is not its exact issuer-bound target."
                )
            if os.path.lexists(prepared.target):
                raise LifecycleInvariantError(
                    "RX child requires a safe, clean, physically absent target."
                )
        if source.kind is RetryKind.R1:
            if classification.terminal_state is not LifecycleState.ABORTED_BEFORE_PUBLICATION:
                raise LifecycleInvariantError("R1 requires an attempt-only abandoned source.")
            if snapshot.mode is not CanonicalMode.ABSENT:
                raise LifecycleInvariantError("R1 requires a physically absent canonical target.")
            if unsafe_staging:
                raise LifecycleInvariantError(
                    "R1 placement is forbidden by attributable unsafe staging residue."
                )
            if failure_bytes is None:
                if not allow_missing_r1_failure:
                    raise LifecycleInvariantError("R1 requires exact durable source closure.")
            else:
                self._require_safe_r1_history(snapshot, index)
        elif classification.terminal_state is LifecycleState.ABORTED_BEFORE_PUBLICATION:
            if snapshot.mode is not CanonicalMode.ABSENT or (
                not unsafe_staging and failure_bytes is not None
            ):
                raise LifecycleInvariantError(
                    "Fresh-target RX is forbidden while attributable unsafe residue does not "
                    "establish that R1 placement is unavailable."
                )
        terminal = classification.terminal_state
        if terminal is None:
            raise LifecycleInvariantError("Retry source lacks a stable terminal result.")
        try:
            terminal_result = RetryTerminalResult(terminal.value)
        except ValueError as error:
            raise LifecycleInvariantError(
                "Retry source terminal result is not retryable."
            ) from error
        return RetrySource(
            source.kind,
            canonical_target,
            source.publication_id,
            source_attempt.envelope.authorization_attempt_id,
            raw_sha256(attempt_bytes),
            None if failure_bytes is None else raw_sha256(failure_bytes),
            terminal_result,
        )

    def _require_safe_r1_history(
        self,
        snapshot: _SelectedSnapshot,
        index: _FamilyIndex,
    ) -> None:
        """Require every nonempty same-target publication to be an exact closed I0 prefix."""
        if not self._same_target_history_is_r1_safe(
            snapshot,
            index,
            selected_requires_failure=True,
        ):
            raise LifecycleInvariantError("R1 same-target history is not safely closed at I0.")

    def _result(
        self,
        snapshot: _SelectedSnapshot,
        state: LifecycleState,
        reader: SelectedReader | None,
        disposition: RetryDisposition,
        canonical: Mapping[str, bytes],
        failure: FailureRecord | None,
        index: _FamilyIndex,
    ) -> LifecycleClassification:
        unrelated = tuple(
            publication_id
            for canonical_target, publication_id in sorted(index.publications)
            if not (
                canonical_target == snapshot.canonical_target
                and publication_id == snapshot.publication_id
            )
        )
        return LifecycleClassification(
            state,
            reader,
            disposition,
            None,
            tuple(name for name in ARTIFACT_FILENAMES if name in canonical),
            "VALID" if failure is not None else "NONE",
            unrelated_publications=unrelated,
            staging_residue=snapshot.staging_residue,
        )

    def _invalid(
        self,
        snapshot: _SelectedSnapshot,
        reader: SelectedReader | None,
        reason: str,
    ) -> LifecycleClassification:
        return LifecycleClassification(
            LifecycleState.INVALID,
            reader,
            RetryDisposition.RN,
            reason,
            tuple(name for name in ARTIFACT_FILENAMES if name in snapshot.canonical),
            "MALFORMED" if "failure.json" in snapshot.ledger else "NONE",
            staging_residue=snapshot.staging_residue,
        )

    def _contextual_invalid(
        self,
        snapshot: _SelectedSnapshot,
        reason: str,
        canonical: Mapping[str, bytes],
        failure: FailureRecord | None,
    ) -> LifecycleClassification:
        return LifecycleClassification(
            LifecycleState.INVALID,
            SelectedReader.AMENDED,
            RetryDisposition.RN,
            reason,
            tuple(name for name in ARTIFACT_FILENAMES if name in canonical),
            "VALID" if failure is not None else "NONE",
            staging_residue=snapshot.staging_residue,
        )


def _read_exact_regular_files(directory: Path, names: Sequence[str]) -> dict[str, bytes]:
    """Read one closed ordinary-file namespace without following links."""

    if not ordinary_directory(directory):
        raise UnsafePathError(f"Expected an ordinary directory: {directory!s}.")
    entries = tuple(directory.iterdir())
    expected = set(names)
    if {entry.name for entry in entries} != expected or any(
        not ordinary_file(entry) for entry in entries
    ):
        raise UnsafePathError(
            f"Directory namespace differs from its closed inventory: {directory!s}."
        )
    return {name: (directory / name).read_bytes() for name in names}


class _LifecycleWriter:
    """The sole forward-only writer after irreversible attempt claim."""

    def __init__(
        self,
        authority: AttemptAuthority,
        prepared: PreparedAttempt,
        attempt_bytes: bytes,
        execution_binding: object,
    ) -> None:
        self.authority = authority
        self.prepared = prepared
        self.attempt_bytes = attempt_bytes
        self.execution_binding = execution_binding
        authority._require_current_execution_binding(execution_binding)
        self.paths = TargetPaths.from_target(
            prepared.target,
            prepared.publication_id,
            primary_target=authority.primary_target,
        )
        record = validate_record("attempt.json", attempt_bytes)
        if not isinstance(record, AttemptRecord):
            raise LifecycleInvariantError("Claimed attempt has the wrong record type.")
        self.attempt = record
        authority._validate_installed_attempt(prepared, {"attempt.json": attempt_bytes})

    def run(
        self,
        *,
        manifest_builder: ManifestBuilder,
        recommendation_builder: RecommendationBuilder,
    ) -> Mapping[str, bytes]:
        self.authority._require_current_execution_binding(self.execution_binding)
        prepared = cast(
            dict[str, bytes],
            self._operation(
                FailurePhase.ARTIFACTS_1_11,
                FailedTransition.ATTEMPT_TO_ARTIFACTS_1_11,
                self._prepared_artifacts,
            ),
        )
        self._operation(
            FailurePhase.ARTIFACTS_1_11,
            FailedTransition.ATTEMPT_TO_ARTIFACTS_1_11,
            lambda: publish_directory_bytes_no_replace(
                self.prepared.staging.artifacts_1_11_publication,
                self.prepared.target,
                prepared,
                validator=self._validate_installed_artifacts_1_11,
                durability_directories=(self.prepared.target, self.prepared.target.parent),
            ),
        )
        m11_bytes = cast(
            bytes,
            self._operation(
                FailurePhase.M11,
                FailedTransition.ARTIFACTS_1_11_TO_M11,
                self._build_m11,
            ),
        )
        self._operation(
            FailurePhase.M11,
            FailedTransition.ARTIFACTS_1_11_TO_M11,
            lambda: self._publish_record("M11", self.prepared.staging.stage_m11, m11_bytes),
        )

        manifest_bytes = cast(
            bytes,
            self._operation(
                FailurePhase.MANIFEST,
                FailedTransition.M11_TO_MANIFEST,
                lambda: self._build_manifest(manifest_builder, self._canonical(11)),
            ),
        )
        self._operation(
            FailurePhase.MANIFEST,
            FailedTransition.M11_TO_MANIFEST,
            lambda: publish_bytes_no_replace(
                self.prepared.staging.stage_run_manifest,
                self.prepared.target / "run_manifest.json",
                manifest_bytes,
                validator=lambda observed: self._validate_canonical_file(
                    "run_manifest.json", observed, 12
                ),
                durability_directories=(self.prepared.target,),
            ),
        )
        m12_bytes = cast(
            bytes,
            self._operation(
                FailurePhase.M12,
                FailedTransition.MANIFEST_TO_M12,
                lambda: self._build_m12(m11_bytes),
            ),
        )
        self._operation(
            FailurePhase.M12,
            FailedTransition.MANIFEST_TO_M12,
            lambda: self._publish_record("M12", self.prepared.staging.stage_m12, m12_bytes),
        )

        recommendation_bytes = cast(
            bytes,
            self._operation(
                FailurePhase.RECOMMENDATION,
                FailedTransition.M12_TO_RECOMMENDATION,
                lambda: self._build_recommendation(
                    recommendation_builder,
                    self._canonical(12),
                ),
            ),
        )
        self._operation(
            FailurePhase.RECOMMENDATION,
            FailedTransition.M12_TO_RECOMMENDATION,
            lambda: publish_bytes_no_replace(
                self.prepared.staging.stage_recommendation,
                self.prepared.target / "recommendation.json",
                recommendation_bytes,
                validator=lambda observed: self._validate_canonical_file(
                    "recommendation.json", observed, 13
                ),
                durability_directories=(self.prepared.target,),
            ),
        )
        m13_bytes = cast(
            bytes,
            self._operation(
                FailurePhase.M13,
                FailedTransition.RECOMMENDATION_TO_M13,
                lambda: self._build_m13(m12_bytes),
            ),
        )
        self._operation(
            FailurePhase.M13,
            FailedTransition.RECOMMENDATION_TO_M13,
            lambda: self._publish_record("M13", self.prepared.staging.stage_m13, m13_bytes),
        )

        validated_canonical = cast(
            dict[str, bytes],
            self._operation(
                FailurePhase.GRAPH_VALIDATION,
                FailedTransition.M13_TO_GRAPH_VALIDATION,
                self._validate_complete_graph,
            ),
        )
        mf_bytes, final_canonical = cast(
            tuple[bytes, dict[str, bytes]],
            self._operation(
                FailurePhase.MF,
                FailedTransition.GRAPH_VALIDATION_TO_MF,
                lambda: self._build_mf(m13_bytes, validated_canonical),
            ),
        )
        final_bound_artifacts = {name: final_canonical[name] for name in ARTIFACT_FILENAMES[:11]}
        self.authority._require_current_execution_binding(
            self.execution_binding,
            final_bound_artifacts,
        )
        self._operation(
            FailurePhase.MF,
            FailedTransition.GRAPH_VALIDATION_TO_MF,
            lambda: self._publish_mf(mf_bytes),
        )
        return MappingProxyType(final_canonical)

    def _operation(
        self,
        phase: FailurePhase,
        transition: FailedTransition,
        operation: Callable[[], object],
    ) -> object:
        try:
            return operation()
        except Exception as error:
            try:
                _FailurePublisher(
                    self.authority,
                    self.prepared.target,
                    self.prepared.publication_id,
                    self.prepared.staging,
                    self.prepared.implementation,
                ).publish_handled(phase, transition, error)
            except Exception as diagnostic_error:
                error.add_note(f"failure.json unavailable: {type(diagnostic_error).__name__}")
            raise

    def _prepared_artifacts(self) -> dict[str, bytes]:
        names = ARTIFACT_FILENAMES[:11]
        observed = read_exact_directory(
            self.prepared.staging.prepared_artifacts_1_11,
            set(names),
            protocol_error_code="NAMESPACE_OBJECT_TYPE",
        )
        prepared = {name: observed[name] for name in names}
        try:
            self._validate_artifacts_1_11(prepared)
        except (ArtifactValidationError, LifecycleInvariantError) as error:
            raise PublicationValidationError(
                "Prepared Artifacts 1-11 differ from the authorization-bound staged bytes.",
                protocol_error_code="VALIDATION_STAGED_BYTES",
                failed_path=self.prepared.staging.prepared_artifacts_1_11,
            ) from error
        return prepared

    def _validate_artifacts_1_11(self, artifacts: Mapping[str, bytes]) -> None:
        names = ARTIFACT_FILENAMES[:11]
        if set(artifacts) != set(names):
            raise LifecycleInvariantError("Artifacts 1-11 do not have the frozen inventory.")
        ordered = {name: artifacts[name] for name in names}
        self.authority._require_current_execution_binding(
            self.execution_binding,
            ordered,
        )
        observed = self._artifact_rows(ordered)
        if observed != self.attempt.intended_artifacts_1_11:
            raise LifecycleInvariantError("Artifacts 1-11 differ from attempt intent.")
        self.authority.graph_validator.validate_11(ordered)

    def _validate_installed_artifacts_1_11(self, artifacts: Mapping[str, bytes]) -> None:
        try:
            self._validate_artifacts_1_11(artifacts)
        except (ArtifactValidationError, LifecycleInvariantError) as error:
            raise PublicationValidationError(
                "Installed Artifacts 1-11 failed final readback validation.",
                protocol_error_code="IO_FINAL_READBACK",
                failed_path=self.prepared.target,
            ) from error

    def _canonical(self, count: int) -> dict[str, bytes]:
        names = ARTIFACT_FILENAMES[:count]
        canonical = _read_exact_regular_files(self.prepared.target, names)
        if count == 11:
            self._validate_artifacts_1_11(canonical)
        elif count == 12:
            self.authority.graph_validator.validate_12(canonical)
        elif count == 13:
            self.authority.graph_validator.validate_13(canonical)
        return canonical

    def _validate_complete_graph(self) -> dict[str, bytes]:
        """Freshly reread I13, then distinguish readback I/O from graph defects."""

        try:
            canonical = _read_exact_regular_files(
                self.prepared.target,
                ARTIFACT_FILENAMES,
            )
        except (LifecycleIOError, OSError) as error:
            raise PublicationValidationError(
                "The final graph operation could not reread the validated I13 snapshot.",
                protocol_error_code="IO_FINAL_READBACK",
                failed_path=self.prepared.target,
            ) from error
        self.authority.graph_validator.validate_13(canonical)
        return canonical

    def _artifact_rows(self, artifacts: Mapping[str, bytes]) -> tuple[ArtifactHash, ...]:
        return tuple(
            ArtifactHash(index, name, raw_sha256(content))
            for index, (name, content) in enumerate(artifacts.items(), 1)
        )

    def _build_exact_bytes(
        self,
        builder: Callable[[Mapping[str, bytes]], bytes],
        artifacts: Mapping[str, bytes],
        label: str,
    ) -> bytes:
        try:
            value = builder(MappingProxyType(dict(artifacts)))
        except Exception as error:
            raise LifecycleInvariantError(
                f"The trusted {label} builder failed before producing bytes."
            ) from error
        if type(value) is not bytes:
            raise TypeError(f"The trusted {label} builder must return exact bytes.")
        return value

    def _build_manifest(
        self,
        builder: ManifestBuilder,
        first_eleven: Mapping[str, bytes],
    ) -> bytes:
        content = self._build_exact_bytes(builder, first_eleven, "manifest")
        self.authority.graph_validator.validate_12({**first_eleven, "run_manifest.json": content})
        self._require_manifest_implementation_binding(content)
        self.authority._require_manifest_execution_binding(content, self.execution_binding)
        return content

    def _build_recommendation(
        self,
        builder: RecommendationBuilder,
        first_twelve: Mapping[str, bytes],
    ) -> bytes:
        content = self._build_exact_bytes(builder, first_twelve, "recommendation")
        self.authority.graph_validator.validate_13({**first_twelve, "recommendation.json": content})
        return content

    def _build_m11(self) -> bytes:
        first_eleven = self._canonical(11)
        content = build_m11_record(
            envelope_for_record(self.attempt.envelope, "M11"),
            attempt_sha256=raw_sha256(self.attempt_bytes),
            artifacts_1_11=self._artifact_rows(first_eleven),
        )
        record = validate_record("M11", content, expected_envelope=self.attempt.envelope)
        if not isinstance(record, M11Record):
            raise LifecycleInvariantError("Constructed M11 has the wrong record type.")
        return content

    def _build_m12(self, m11_bytes: bytes) -> bytes:
        first_twelve = self._canonical(12)
        self._require_manifest_implementation_binding(first_twelve["run_manifest.json"])
        content = build_m12_record(
            envelope_for_record(self.attempt.envelope, "M12"),
            m11_sha256=raw_sha256(m11_bytes),
            manifest_byte_sha256=raw_sha256(first_twelve["run_manifest.json"]),
        )
        record = validate_record("M12", content, expected_envelope=self.attempt.envelope)
        if not isinstance(record, M12Record):
            raise LifecycleInvariantError("Constructed M12 has the wrong record type.")
        return content

    def _build_m13(self, m12_bytes: bytes) -> bytes:
        first_thirteen = self._canonical(13)
        self._require_manifest_implementation_binding(first_thirteen["run_manifest.json"])
        content = build_m13_record(
            envelope_for_record(self.attempt.envelope, "M13"),
            m12_sha256=raw_sha256(m12_bytes),
            recommendation_byte_sha256=raw_sha256(first_thirteen["recommendation.json"]),
        )
        record = validate_record("M13", content, expected_envelope=self.attempt.envelope)
        if not isinstance(record, M13Record):
            raise LifecycleInvariantError("Constructed M13 has the wrong record type.")
        return content

    def _require_manifest_implementation_binding(self, content: bytes) -> None:
        try:
            value = json.loads(content)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise LifecycleInvariantError(
                "Manifest implementation binding is unreadable."
            ) from error
        if not isinstance(value, Mapping):
            raise LifecycleInvariantError("Manifest implementation binding is not an object.")
        expected = {
            "implementation_commit": self.attempt.envelope.implementation_commit,
            "implementation_tree_sha256": self.attempt.envelope.implementation_tree_sha256,
            "implementation_diff_sha256": self.attempt.envelope.implementation_diff_sha256,
        }
        if any(value.get(field) != bound for field, bound in expected.items()):
            raise LifecycleInvariantError("Manifest implementation identity differs from attempt.")

    def _build_mf(
        self,
        m13_bytes: bytes,
        validated_canonical: Mapping[str, bytes],
    ) -> tuple[bytes, dict[str, bytes]]:
        self._require_no_success_candidate()
        final_canonical = {name: validated_canonical[name] for name in ARTIFACT_FILENAMES}
        self._require_manifest_implementation_binding(final_canonical["run_manifest.json"])
        content = build_mf_record(
            envelope_for_record(self.attempt.envelope, "MF"),
            m13_sha256=raw_sha256(m13_bytes),
            artifacts_1_13=self._artifact_rows(final_canonical),
        )
        record = validate_record("MF", content, expected_envelope=self.attempt.envelope)
        if not isinstance(record, MFRecord):
            raise LifecycleInvariantError("Constructed MF has the wrong record type.")
        return content, final_canonical

    def _publish_record(self, name: str, staging: Path, content: bytes) -> bytes:
        destination = self.paths.attempt_directory / name
        return publish_bytes_no_replace(
            staging,
            destination,
            content,
            validator=lambda observed: self._validate_record(name, content, observed),
            durability_directories=(self.paths.attempt_directory,),
        )

    def _validate_record(self, name: str, expected: bytes, observed: bytes) -> None:
        if observed != expected:
            raise PublicationValidationError(
                f"Installed {name} bytes differ.",
                protocol_error_code="IO_FINAL_READBACK",
                failed_path=self.paths.attempt_directory / name,
            )
        try:
            validate_record(name, observed, expected_envelope=self.attempt.envelope)
        except (ValueError, TypeError) as error:
            raise PublicationValidationError(
                f"Installed {name} failed record readback validation.",
                protocol_error_code="IO_FINAL_READBACK",
                failed_path=self.paths.attempt_directory / name,
            ) from error

    def _validate_canonical_file(self, name: str, observed: bytes, count: int) -> None:
        if not ordinary_file(self.prepared.target / name):
            raise PublicationValidationError(
                f"Installed {name} is not ordinary.",
                protocol_error_code="IO_FINAL_READBACK",
                failed_path=self.prepared.target / name,
            )
        try:
            canonical = _read_exact_regular_files(
                self.prepared.target,
                ARTIFACT_FILENAMES[:count],
            )
            if canonical[name] != observed:
                raise LifecycleInvariantError(f"Installed {name} readback differs.")
            if count == 12:
                self.authority.graph_validator.validate_12(canonical)
                self._require_manifest_implementation_binding(canonical["run_manifest.json"])
            else:
                self.authority.graph_validator.validate_13(canonical)
        except (LifecycleIOError, ArtifactValidationError, LifecycleInvariantError) as error:
            raise PublicationValidationError(
                f"Installed {name} failed final readback validation.",
                protocol_error_code="IO_FINAL_READBACK",
                failed_path=self.prepared.target / name,
            ) from error

    def _require_no_success_candidate(self) -> None:
        reader = self.authority._reader(self.prepared.implementation)
        if reader._local_success_candidates(lock_already_held=True):
            raise LifecycleInvariantError("A competing study success prohibits MF.")

    def _publish_mf(self, content: bytes) -> bytes:
        def validate(observed: bytes) -> None:
            self._validate_record("MF", content, observed)
            self.authority.graph_validator.validate_13(self._canonical(13))
            reader = self.authority._reader(self.prepared.implementation)
            selected = (self.prepared.canonical_target, self.prepared.publication_id)
            if reader._local_success_candidates(lock_already_held=True) != {selected}:
                raise LifecycleInvariantError("MF does not establish the sole local study success.")

        return publish_bytes_no_replace(
            self.prepared.staging.stage_mf,
            self.paths.attempt_directory / "MF",
            content,
            validator=validate,
            durability_directories=(self.paths.attempt_directory,),
        )


class _FailurePublisher:
    """Create the one deterministic terminal diagnostic without advancing a prefix."""

    def __init__(
        self,
        authority: AttemptAuthority,
        target: Path,
        publication_id: str,
        staging: StagingLayout,
        implementation: ImplementationIdentity,
    ) -> None:
        self.authority = authority
        self.target = target
        self.publication_id = publication_id
        self.staging = staging
        self.implementation = implementation
        self.paths = TargetPaths.from_target(
            target,
            publication_id,
            primary_target=authority.primary_target,
        )
        self.reader = authority._reader(implementation)

    def publish_handled(
        self,
        phase: FailurePhase,
        transition: FailedTransition,
        error: Exception,
        *,
        expected_attempt: bytes | None = None,
    ) -> bytes:
        code = self._error_code(error, phase)
        return self._publish(
            phase,
            transition,
            code,
            expected_attempt=expected_attempt,
            allow_graph_invalid=phase is FailurePhase.GRAPH_VALIDATION,
            recovery=False,
        )

    def publish_recovery(self) -> bytes:
        snapshot, attempt, records, inventory, predecessor = self._validated_prefix(
            expected_attempt=None,
            allow_graph_invalid=False,
        )
        if "MF" in snapshot.ledger:
            raise LifecycleInvariantError("Recovery failure cannot follow MF.")
        existing = snapshot.ledger.get("failure.json")
        if existing is not None:
            record = validate_record("failure.json", existing, expected_envelope=attempt.envelope)
            if not isinstance(record, FailureRecord):
                raise LifecycleInvariantError("Existing terminal failure has the wrong type.")
            if tuple(record.observed_inventory) != inventory:
                raise LifecycleInvariantError(
                    "Existing failure inventory differs from recovery snapshot."
                )
            if (
                record.predecessor_filename is not predecessor[0]
                or record.predecessor_sha256 != predecessor[1]
            ):
                raise LifecycleInvariantError(
                    "Existing failure predecessor differs from recovery snapshot."
                )
            if self.reader._has_successor_after_failure(record, snapshot.canonical, records):
                raise LifecycleInvariantError(
                    "Existing terminal failure has a forbidden successor."
                )
            self._reflush_existing_failure(attempt, existing)
            return existing
        if self.reader._alleged_children(attempt):
            raise LifecycleInvariantError(
                "Recovery cannot add a source failure after a retry child exists."
            )
        transition = self._recovery_transition(records, snapshot.canonical)
        self._reset_failure_stage()
        return self._publish_built(
            attempt,
            FailurePhase.RECOVERY,
            transition,
            FailureErrorCode.RECOVERY_ABANDONED,
            inventory,
            predecessor,
        )

    def _publish(
        self,
        phase: FailurePhase,
        transition: FailedTransition,
        code: FailureErrorCode,
        *,
        expected_attempt: bytes | None,
        allow_graph_invalid: bool,
        recovery: bool,
    ) -> bytes:
        del recovery
        snapshot, attempt, _records, inventory, predecessor = self._validated_prefix(
            expected_attempt=expected_attempt,
            allow_graph_invalid=allow_graph_invalid,
        )
        existing = snapshot.ledger.get("failure.json")
        content = self._build(attempt, phase, transition, code, inventory, predecessor)
        if existing is not None:
            validate_record("failure.json", existing, expected_envelope=attempt.envelope)
            if existing != content:
                raise LifecycleInvariantError(
                    "Existing failure.json differs from deterministic bytes."
                )
            self._reflush_existing_failure(attempt, existing)
            return existing
        return self._publish_bytes(attempt, content)

    def _publish_built(
        self,
        attempt: AttemptRecord,
        phase: FailurePhase,
        transition: FailedTransition,
        code: FailureErrorCode,
        inventory: tuple[InventoryEntry, ...],
        predecessor: tuple[LedgerPredecessor, str],
    ) -> bytes:
        return self._publish_bytes(
            attempt,
            self._build(attempt, phase, transition, code, inventory, predecessor),
        )

    def _build(
        self,
        attempt: AttemptRecord,
        phase: FailurePhase,
        transition: FailedTransition,
        code: FailureErrorCode,
        inventory: tuple[InventoryEntry, ...],
        predecessor: tuple[LedgerPredecessor, str],
    ) -> bytes:
        return build_failure_record(
            envelope_for_record(attempt.envelope, "failure.json"),
            phase=phase,
            failed_transition=transition,
            error_code=code,
            predecessor_filename=predecessor[0],
            predecessor_sha256=predecessor[1],
            observed_inventory=inventory,
        )

    def _publish_bytes(self, attempt: AttemptRecord, content: bytes) -> bytes:
        self.staging.ensure_root()
        durability: list[Path] = [
            self.paths.attempt_directory,
            self.paths.ledger_root,
            self.paths.ledger_root.parent,
        ]
        if ordinary_directory(self.paths.target):
            durability.extend((self.paths.target, self.paths.target.parent))
        return publish_bytes_no_replace(
            self.staging.stage_failure,
            self.paths.attempt_directory / "failure.json",
            content,
            validator=lambda observed: self._validate_failure(attempt, content, observed),
            durability_directories=tuple(durability),
        )

    def _reflush_existing_failure(self, attempt: AttemptRecord, expected: bytes) -> None:
        """Revalidate a survivor and repeat every applicable post-crash barrier."""

        failure_path = self.paths.attempt_directory / "failure.json"
        if not ordinary_file(failure_path):
            raise LifecycleInvariantError("Existing failure.json is not an ordinary file.")
        observed = failure_path.read_bytes()
        self._validate_failure(attempt, expected, observed)
        directories = [
            self.paths.attempt_directory,
            self.paths.ledger_root,
            self.paths.ledger_root.parent,
        ]
        if ordinary_directory(self.paths.target):
            directories.extend((self.paths.target, self.paths.target.parent))
        for directory in directories:
            fsync_directory(directory)

    def _validate_failure(
        self,
        attempt: AttemptRecord,
        expected: bytes,
        observed: bytes,
    ) -> None:
        if observed != expected:
            raise LifecycleInvariantError("Installed failure.json bytes differ.")
        record = validate_record("failure.json", observed, expected_envelope=attempt.envelope)
        if not isinstance(record, FailureRecord):
            raise LifecycleInvariantError("Installed failure.json has the wrong record type.")

    def _validated_prefix(
        self,
        *,
        expected_attempt: bytes | None,
        allow_graph_invalid: bool,
    ) -> tuple[
        _SelectedSnapshot,
        AttemptRecord,
        dict[str, object],
        tuple[InventoryEntry, ...],
        tuple[LedgerPredecessor, str],
    ]:
        canonical_target = normalize_target(
            self.target,
            primary_target=self.authority.primary_target,
        )
        snapshot = self.reader._snapshot(self.target, canonical_target, self.publication_id)
        if snapshot.mode is CanonicalMode.INVALID:
            raise LifecycleInvariantError("Failure snapshot has an invalid canonical namespace.")
        if any(name not in LEDGER_FINAL_NAMES for name in snapshot.ledger):
            raise LifecycleInvariantError("Failure snapshot has an invalid ledger namespace.")
        attempt_bytes = snapshot.ledger.get("attempt.json")
        if attempt_bytes is None or (
            expected_attempt is not None and attempt_bytes != expected_attempt
        ):
            raise LifecycleInvariantError("Failure snapshot lacks the exact installed attempt.")
        records: dict[str, object] = {
            name: validate_record(name, content)
            for name, content in snapshot.ledger.items()
            if name != "failure.json"
        }
        attempt = records.get("attempt.json")
        if not isinstance(attempt, AttemptRecord):
            raise LifecycleInvariantError("Failure snapshot attempt has the wrong type.")
        self.reader._require_common_envelope(snapshot, attempt.envelope, records)
        self.reader._require_retry_binding(
            attempt,
            snapshot,
            self.reader._build_family_index(strict_namespace=True),
        )
        if "MF" in records:
            raise LifecycleInvariantError("failure.json cannot follow MF.")
        markers = tuple(name for name in ("M11", "M12", "M13") if name in records)
        if markers not in ((), ("M11",), ("M11", "M12"), ("M11", "M12", "M13")):
            raise LifecycleInvariantError("Failure snapshot marker set is not a legal prefix.")
        self._validate_canonical_prefix(snapshot, attempt, records, allow_graph_invalid)
        inventory = self.reader._inventory(snapshot, records)
        predecessor_name = (
            LedgerPredecessor.M13
            if "M13" in records
            else LedgerPredecessor.M12
            if "M12" in records
            else LedgerPredecessor.M11
            if "M11" in records
            else LedgerPredecessor.ATTEMPT
        )
        predecessor_bytes = snapshot.ledger[predecessor_name.value]
        return (
            snapshot,
            attempt,
            records,
            inventory,
            (predecessor_name, raw_sha256(predecessor_bytes)),
        )

    def _validate_canonical_prefix(
        self,
        snapshot: _SelectedSnapshot,
        attempt: AttemptRecord,
        records: Mapping[str, object],
        allow_graph_invalid: bool,
    ) -> None:
        canonical = {
            name: snapshot.canonical[name]
            for name in ARTIFACT_FILENAMES
            if name in snapshot.canonical
        }
        intended = {item.filename: item.byte_sha256 for item in attempt.intended_artifacts_1_11}
        for name, content in canonical.items():
            if self.reader._checkpoint_anchor(name, content) != PROTOCOL_CHECKPOINT:
                raise LifecycleInvariantError("Failure canonical checkpoint differs.")
            if name in intended and raw_sha256(content) != intended[name]:
                raise LifecycleInvariantError("Failure canonical bytes differ from attempt intent.")
        first_eleven = ARTIFACT_FILENAMES[:11]
        present_eleven = tuple(name for name in first_eleven if name in canonical)
        if present_eleven == first_eleven:
            self.authority.graph_validator.validate_11(
                {name: canonical[name] for name in first_eleven}
            )
        manifest = "run_manifest.json" in canonical
        recommendation = "recommendation.json" in canonical
        m11 = records.get("M11")
        if m11 is not None:
            if not isinstance(m11, M11Record) or present_eleven != first_eleven:
                raise LifecycleInvariantError("Failure M11 prefix is incomplete.")
            if m11.attempt_sha256 != raw_sha256(snapshot.ledger["attempt.json"]):
                raise LifecycleInvariantError("Failure M11 predecessor differs.")
            self.reader._require_artifact_rows(m11.artifacts_1_11, canonical, 11)
        if manifest:
            if m11 is None or present_eleven != first_eleven:
                raise LifecycleInvariantError("Failure manifest appears before M11.")
            self.authority.graph_validator.validate_12(
                {name: canonical[name] for name in ARTIFACT_FILENAMES[:12]}
            )
            self.reader._require_manifest_implementation_binding(
                canonical["run_manifest.json"],
                attempt.envelope,
            )
        m12 = records.get("M12")
        if m12 is not None:
            if not isinstance(m12, M12Record) or not manifest or not isinstance(m11, M11Record):
                raise LifecycleInvariantError("Failure M12 prefix is incomplete.")
            if m12.m11_sha256 != record_sha256(m11):
                raise LifecycleInvariantError("Failure M12 predecessor differs.")
            if m12.manifest_byte_sha256 != raw_sha256(canonical["run_manifest.json"]):
                raise LifecycleInvariantError("Failure M12 manifest hash differs.")
        if recommendation:
            if m12 is None or not manifest:
                raise LifecycleInvariantError("Failure recommendation appears before M12.")
            if not allow_graph_invalid:
                self.authority.graph_validator.validate_13(canonical)
        m13 = records.get("M13")
        if m13 is not None:
            if (
                not isinstance(m13, M13Record)
                or not recommendation
                or not isinstance(m12, M12Record)
            ):
                raise LifecycleInvariantError("Failure M13 prefix is incomplete.")
            if m13.m12_sha256 != record_sha256(m12):
                raise LifecycleInvariantError("Failure M13 predecessor differs.")
            if m13.recommendation_byte_sha256 != raw_sha256(canonical["recommendation.json"]):
                raise LifecycleInvariantError("Failure M13 recommendation hash differs.")

    def _recovery_transition(
        self,
        records: Mapping[str, object],
        canonical: Mapping[str, bytes],
    ) -> FailedTransition:
        if "M13" in records:
            return FailedTransition.M13_TO_GRAPH_VALIDATION
        if "recommendation.json" in canonical:
            return FailedTransition.RECOMMENDATION_TO_M13
        if "M12" in records:
            return FailedTransition.M12_TO_RECOMMENDATION
        if "run_manifest.json" in canonical:
            return FailedTransition.MANIFEST_TO_M12
        if "M11" in records:
            return FailedTransition.M11_TO_MANIFEST
        if any(name in canonical for name in ARTIFACT_FILENAMES[:11]):
            return FailedTransition.ARTIFACTS_1_11_TO_M11
        return FailedTransition.ATTEMPT_TO_ARTIFACTS_1_11

    def _reset_failure_stage(self) -> None:
        if not os.path.lexists(self.staging.stage_failure):
            return
        expected = StagingLayout.from_target(
            self.target,
            self.publication_id,
            primary_target=self.authority.primary_target,
        )
        if expected != self.staging:
            raise UnsafePathError("Recovery staging layout is not exactly target-bound.")
        if (
            not ordinary_directory(self.staging.root.parent)
            or not ordinary_directory(self.staging.root)
            or not is_path_within(self.staging.stage_failure, self.staging.root)
        ):
            raise UnsafePathError("Recovery failure staging residue is unsafe.")
        if not ordinary_file(self.staging.stage_failure):
            raise _UnsafeR1StagingResidue(
                "Recovery failure staging residue is nonregular and cannot be reset."
            )
        try:
            self.staging.stage_failure.unlink()
        except OSError as error:
            raise _UnsafeR1StagingResidue(
                "Recovery failure staging residue cannot be removed."
            ) from error
        fsync_directory(self.staging.root)

    def _error_code(self, error: Exception, phase: FailurePhase) -> FailureErrorCode:
        if isinstance(error, LifecycleIOError):
            tagged = error.protocol_error_code
            if tagged is not None:
                try:
                    return FailureErrorCode(tagged)
                except ValueError:
                    return FailureErrorCode.INTERNAL_INVARIANT
        if isinstance(error, ExistingDestinationError):
            return FailureErrorCode.NAMESPACE_EXISTING_FINAL
        if isinstance(error, UnsafePathError):
            return FailureErrorCode.NAMESPACE_TARGET
        if isinstance(error, DurabilityError):
            return FailureErrorCode.IO_DIRECTORY_FSYNC
        if isinstance(error, PublicationValidationError):
            return FailureErrorCode.IO_FINAL_READBACK
        if isinstance(error, ArtifactValidationError):
            if phase is FailurePhase.GRAPH_VALIDATION:
                return FailureErrorCode.VALIDATION_GRAPH
            return FailureErrorCode.VALIDATION_STAGED_BYTES
        return FailureErrorCode.INTERNAL_INVARIANT


def reconstruct_implementation_identity() -> ImplementationIdentity:
    """Recompute the trusted clean-checkout identity with the frozen P0 diff baseline."""

    from research_decision_engine.benchmarks.broader_assembly import (
        _git_text,
        _git_tree,
        _implementation_diff_identity,
        _implementation_tree_identity,
        _resolve_git_executable,
        _working_implementation_tree,
    )

    root = repository_root().resolve(strict=True)
    git = _resolve_git_executable()
    status = subprocess.run(
        [
            str(git),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            "pyproject.toml",
            "uv.lock",
            "research_decision_engine",
            "tests",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    if status:
        raise LifecycleInvariantError("Lifecycle dispatch requires a clean implementation tree.")
    commit = _git_text(git, root, "rev-parse", "--verify", "HEAD^{commit}")
    baseline = _git_tree(git, root, commit)
    working = _working_implementation_tree(git, root)
    return ImplementationIdentity(
        commit,
        _implementation_tree_identity(working),
        _implementation_diff_identity(git, root, baseline, working, source_checkpoint=commit),
    )
