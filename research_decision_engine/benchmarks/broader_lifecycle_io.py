"""Low-level path, locking, and durable publication authorities for Task B.

This module deliberately knows nothing about lifecycle record schemas, authorization,
reader classification, or scientific artifacts.  It implements only the filesystem and
canonical-JSON primitives frozen by Sections 3, 4.2, and 6 of the lifecycle amendment.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import stat
import sys
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from importlib import import_module as _import_module
from pathlib import Path
from typing import Never, cast
from typing import Protocol as _Protocol

type StrPath = str | os.PathLike[str]
type FileValidator = Callable[[bytes], None]
type DirectoryValidator = Callable[[Mapping[str, bytes]], None]

STUDY_ID = "broader-closed-loop-replication/v1"
PRIMARY_TARGET_NAME = "broader-replication-v1-128-seeds"
PUBLICATION_ID_PATTERN = re.compile(r"publication-[0-9a-f]{64}\Z")
AUTHORIZATION_ATTEMPT_ID_PATTERN = re.compile(r"authorization-attempt-[0-9a-f]{64}\Z")
_PUBLICATION_ID_BYTES_PATTERN = re.compile(
    rb"(?<![A-Za-z0-9_-])(publication-[0-9a-f]{64})(?![A-Za-z0-9_-])"
)
_AUTHORIZATION_ATTEMPT_ID_BYTES_PATTERN = re.compile(
    rb"(?<![A-Za-z0-9_-])(authorization-attempt-[0-9a-f]{64})(?![A-Za-z0-9_-])"
)
LEDGER_FINAL_NAMES = frozenset({"attempt.json", "M11", "M12", "M13", "MF", "failure.json"})
STAGING_CHILD_NAMES = frozenset(
    {
        "attempt-publication",
        "prepared-artifacts-1-11",
        "artifacts-1-11-publication",
        "stage-M11",
        "stage-run_manifest.json",
        "stage-M12",
        "stage-recommendation.json",
        "stage-M13",
        "stage-failure.json",
        "stage-MF",
    }
)
_STAGED_ARTIFACT_1_11_NAMES = frozenset(
    {
        "protocol_snapshot.json",
        "world_definitions.json",
        "arm_runs.jsonl",
        "oracle_provenance.jsonl",
        "calibration_estimates.jsonl",
        "trajectory_events.jsonl",
        "comparisons.jsonl",
        "contrast_results.csv",
        "resampling_audit.jsonl",
        "gate_evaluations.json",
        "audit_results.json",
    }
)

_REPOSITORY_ROOT = Path(__file__).resolve(strict=True).parents[2]
PRIMARY_TARGET = _REPOSITORY_ROOT / PRIMARY_TARGET_NAME
_WINDOWS_RESERVED_STEMS = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CLOCK$"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


class LifecycleIOError(RuntimeError):
    """Base class for a fail-closed lifecycle I/O error."""

    def __init__(
        self,
        message: str,
        *,
        protocol_error_code: str | None = None,
        failed_path: StrPath | None = None,
    ) -> None:
        self.protocol_error_code = protocol_error_code
        self.failed_path = None if failed_path is None else Path(failed_path)
        super().__init__(message)


class CanonicalLedgerError(LifecycleIOError):
    """Ledger bytes or a value violate the exact canonical JSON contract."""


class UnsafePathError(LifecycleIOError):
    """A path is malformed, out of scope, aliased, or has an unsafe object type."""


class ExistingDestinationError(LifecycleIOError):
    """A create-once staging or final destination already exists."""


class PublicationValidationError(LifecycleIOError):
    """Installed bytes fail exact readback validation."""


class DurabilityError(LifecycleIOError):
    """A required file or directory durability barrier failed."""


class LockUnavailableError(LifecycleIOError):
    """A nonblocking study-lock request conflicts with an active owner."""


class NamespaceScanError(UnsafePathError):
    """The global lifecycle namespace cannot be scanned safely and completely."""


def _validate_json_value(value: object, active: set[int]) -> None:
    if value is None or type(value) in {bool, int}:
        return
    if type(value) is str:
        if unicodedata.normalize("NFC", value) != value:
            raise CanonicalLedgerError("All ledger JSON strings must be NFC-normalized.")
        return
    if isinstance(value, float):
        raise CanonicalLedgerError("Floats are forbidden in ledger JSON.")
    if type(value) is list:
        identity = id(value)
        if identity in active:
            raise CanonicalLedgerError("Cyclic JSON values are forbidden.")
        active.add(identity)
        try:
            for item in cast(list[object], value):
                _validate_json_value(item, active)
        finally:
            active.remove(identity)
        return
    if type(value) is dict:
        identity = id(value)
        if identity in active:
            raise CanonicalLedgerError("Cyclic JSON values are forbidden.")
        active.add(identity)
        try:
            for key, item in cast(dict[object, object], value).items():
                if type(key) is not str or not key.isascii():
                    raise CanonicalLedgerError("All ledger JSON object keys must be ASCII strings.")
                _validate_json_value(key, active)
                _validate_json_value(item, active)
        finally:
            active.remove(identity)
        return
    raise CanonicalLedgerError(f"Unsupported ledger JSON value type: {type(value).__name__}.")


def canonical_json_bytes(value: object) -> bytes:
    """Return exact ``J(v)`` bytes (without the record LF)."""

    _validate_json_value(value, set())
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise CanonicalLedgerError("Ledger JSON serialization failed.") from error


def canonical_ledger_bytes(value: Mapping[str, object]) -> bytes:
    """Serialize one ledger record with its exact single terminal LF."""

    if type(value) is not dict:
        value = dict(value)
    return canonical_json_bytes(value) + b"\n"


def _reject_json_float(_token: str) -> Never:
    raise CanonicalLedgerError("Floats are forbidden in ledger JSON.")


def _reject_json_constant(_token: str) -> Never:
    raise CanonicalLedgerError("Non-finite JSON constants are forbidden.")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalLedgerError(f"Duplicate ledger JSON key: {key!r}.")
        result[key] = value
    return result


def parse_canonical_ledger_bytes(data: bytes) -> dict[str, object]:
    """Parse an exact ledger record and reject any noncanonical equivalent encoding."""

    if type(data) is not bytes:
        raise CanonicalLedgerError("Ledger records must be supplied as bytes.")
    try:
        text = data.decode("utf-8", errors="strict")
        parsed = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_float=_reject_json_float,
            parse_constant=_reject_json_constant,
        )
    except CanonicalLedgerError:
        raise
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise CanonicalLedgerError("Ledger record is not valid canonical UTF-8 JSON.") from error
    if type(parsed) is not dict:
        raise CanonicalLedgerError("A ledger record must be one JSON object.")
    record = cast(dict[str, object], parsed)
    _validate_json_value(record, set())
    if data != canonical_ledger_bytes(record):
        raise CanonicalLedgerError("Ledger bytes are not byte-for-byte canonical.")
    return record


def raw_sha256(data: bytes) -> str:
    """Return lowercase raw SHA-256 for exact bytes."""

    if type(data) is not bytes:
        raise TypeError("raw_sha256 requires bytes.")
    return hashlib.sha256(data).hexdigest()


def validate_publication_id(value: object) -> str:
    if type(value) is not str or PUBLICATION_ID_PATTERN.fullmatch(value) is None:
        raise UnsafePathError("Malformed publication_id.")
    return value


def validate_authorization_attempt_id(value: object) -> str:
    if type(value) is not str or AUTHORIZATION_ATTEMPT_ID_PATTERN.fullmatch(value) is None:
        raise UnsafePathError("Malformed authorization_attempt_id.")
    return value


def validate_ledger_final_name(value: object) -> str:
    if type(value) is not str or value not in LEDGER_FINAL_NAMES:
        raise UnsafePathError("Unknown ledger final name.")
    return value


def _fspath(value: StrPath) -> str:
    try:
        raw = os.fspath(value)
    except TypeError as error:
        raise UnsafePathError("A path must be one str or os.PathLike[str] value.") from error
    if type(raw) is not str or not raw or "\x00" in raw:
        raise UnsafePathError("A path must be a nonempty string without NUL.")
    return raw


def _validate_component(component: str) -> None:
    if not component or component in {".", ".."}:
        raise UnsafePathError("Empty, dot, and dot-dot path components are forbidden.")
    if any(ord(character) <= 0x1F for character in component):
        raise UnsafePathError("Control characters are forbidden in path components.")
    separators = {os.sep}
    if os.altsep is not None:
        separators.add(os.altsep)
    if any(separator in component for separator in separators):
        raise UnsafePathError("Separator characters are forbidden inside a path leaf.")
    if os.name == "nt":
        if ":" in component or component.endswith((" ", ".")):
            raise UnsafePathError("Windows device, stream, and alias components are forbidden.")
        if component.split(".", 1)[0].upper() in _WINDOWS_RESERVED_STEMS:
            raise UnsafePathError("Windows reserved device names are forbidden.")


def _lexical_absolute(value: StrPath) -> Path:
    raw = _fspath(value)
    if os.name == "nt" and raw.startswith(("\\\\.\\", "\\\\?\\", "\\??\\")):
        raise UnsafePathError("Windows device namespace paths are forbidden.")
    split_raw = raw.replace(os.altsep, os.sep) if os.altsep is not None else raw
    drive, tail = os.path.splitdrive(split_raw)
    del drive
    raw_components = tail.split(os.sep)
    for index, component in enumerate(raw_components):
        if not component:
            if index == 0 and tail.startswith(os.sep):
                continue
            raise UnsafePathError("Raw empty non-root path components are forbidden.")
        if component in {".", ".."}:
            raise UnsafePathError("Raw dot and dot-dot path components are forbidden.")
    lexical = Path(os.path.normpath(os.path.abspath(raw)))
    for component in lexical.parts[1:] if lexical.anchor else lexical.parts:
        _validate_component(component)
    return lexical


def _is_reparse(result: os.stat_result) -> bool:
    attributes = int(getattr(result, "st_file_attributes", 0))
    flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return bool(attributes & flag)


def reparse_point(path: StrPath) -> bool:
    """Return true for a symlink, junction, or other reparse point, without following it."""

    try:
        result = os.lstat(_fspath(path))
    except OSError:
        return False
    return stat.S_ISLNK(result.st_mode) or _is_reparse(result)


def ordinary_file(path: StrPath) -> bool:
    try:
        result = os.lstat(_fspath(path))
    except OSError:
        return False
    return stat.S_ISREG(result.st_mode) and not _is_reparse(result)


def ordinary_directory(path: StrPath) -> bool:
    try:
        result = os.lstat(_fspath(path))
    except OSError:
        return False
    return stat.S_ISDIR(result.st_mode) and not _is_reparse(result)


def require_ordinary_file(path: StrPath) -> os.stat_result:
    try:
        result = os.lstat(_fspath(path))
    except OSError as error:
        raise UnsafePathError(f"Unreadable or missing ordinary file: {path!s}.") from error
    if not stat.S_ISREG(result.st_mode) or _is_reparse(result):
        raise UnsafePathError(f"Path is not an ordinary regular file: {path!s}.")
    return result


def require_ordinary_directory(path: StrPath) -> os.stat_result:
    try:
        result = os.lstat(_fspath(path))
    except OSError as error:
        raise UnsafePathError(f"Unreadable or missing ordinary directory: {path!s}.") from error
    if not stat.S_ISDIR(result.st_mode) or _is_reparse(result):
        raise UnsafePathError(f"Path is not an ordinary directory: {path!s}.")
    return result


def _assert_safe_ancestors(directory: Path) -> None:
    if not directory.is_absolute():
        raise UnsafePathError("Path validation requires an absolute path.")
    current = Path(directory.anchor)
    components = directory.parts[1:] if directory.anchor else directory.parts
    require_ordinary_directory(current)
    for component in components:
        current = current / component
        require_ordinary_directory(current)


def _normalize_unscoped(value: StrPath) -> tuple[Path, str]:
    lexical = _lexical_absolute(value)
    parent = lexical.parent
    leaf = lexical.name
    if not leaf or lexical == parent:
        raise UnsafePathError("The target must be a non-root child of its parent.")
    _validate_component(leaf)
    _assert_safe_ancestors(parent)
    try:
        native_parent = os.path.realpath(parent, strict=True)
    except OSError as error:
        raise UnsafePathError("The target parent cannot be resolved safely.") from error
    native_string = os.path.normcase(os.path.normpath(os.path.join(native_parent, leaf)))
    native = Path(native_string)
    canonical = unicodedata.normalize("NFC", native.as_posix())
    if native.parent != native:
        canonical = canonical.rstrip("/")
    lowered_leaf = os.path.normcase(native.name)
    if lowered_leaf.endswith(os.path.normcase(".rde-attempts")) or lowered_leaf.endswith(
        os.path.normcase(".rde-staging")
    ):
        raise UnsafePathError("A canonical target cannot use a generated lifecycle suffix.")
    for suffix in (".rde-attempts", ".rde-staging"):
        generated = native.with_name(native.name + suffix)
        _validate_component(generated.name)
        _assert_safe_ancestors(generated.parent)
    return native, canonical


def normalize_target(value: StrPath, *, primary_target: StrPath = PRIMARY_TARGET) -> str:
    """Normalize and validate one primary or exact direct-sibling RX target."""

    native, canonical = _normalize_unscoped(value)
    primary_native, _ = _normalize_unscoped(primary_target)
    if os.path.normcase(os.path.normpath(native)) == os.path.normcase(
        os.path.normpath(primary_native)
    ):
        return canonical
    if native.parent != primary_native.parent:
        raise UnsafePathError(
            "A lifecycle target must be the primary target or a direct RX sibling."
        )
    prefix = primary_native.name + ".retry-"
    if not native.name.startswith(prefix):
        raise UnsafePathError("A lifecycle target is outside the closed target family.")
    validate_publication_id(native.name[len(prefix) :])
    return canonical


def is_path_within(path: StrPath, root: StrPath) -> bool:
    candidate = os.path.normcase(os.path.normpath(os.path.abspath(_fspath(path))))
    boundary = os.path.normcase(os.path.normpath(os.path.abspath(_fspath(root))))
    try:
        return os.path.commonpath((candidate, boundary)) == boundary
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class TargetPaths:
    target: Path
    canonical_target: str
    ledger_root: Path
    attempt_directory: Path
    attempt_file: Path
    staging_parent: Path

    @classmethod
    def from_target(
        cls,
        target: StrPath,
        publication_id: str,
        *,
        primary_target: StrPath = PRIMARY_TARGET,
    ) -> TargetPaths:
        publication_id = validate_publication_id(publication_id)
        canonical = normalize_target(target, primary_target=primary_target)
        native, _ = _normalize_unscoped(target)
        ledger_root = native.with_name(native.name + ".rde-attempts")
        attempt_directory = ledger_root / publication_id
        staging_parent = native.with_name(native.name + ".rde-staging")
        return cls(
            native,
            canonical,
            ledger_root,
            attempt_directory,
            attempt_directory / "attempt.json",
            staging_parent,
        )


@dataclass(frozen=True, slots=True)
class StagingLayout:
    target: Path
    publication_id: str
    root: Path
    attempt_publication: Path
    prepared_artifacts_1_11: Path
    artifacts_1_11_publication: Path
    stage_m11: Path
    stage_run_manifest: Path
    stage_m12: Path
    stage_recommendation: Path
    stage_m13: Path
    stage_failure: Path
    stage_mf: Path

    @classmethod
    def from_target(
        cls,
        target: StrPath,
        publication_id: str,
        *,
        primary_target: StrPath = PRIMARY_TARGET,
    ) -> StagingLayout:
        paths = TargetPaths.from_target(
            target,
            publication_id,
            primary_target=primary_target,
        )
        root = paths.staging_parent / paths.attempt_directory.name
        return cls(
            paths.target,
            paths.attempt_directory.name,
            root,
            root / "attempt-publication",
            root / "prepared-artifacts-1-11",
            root / "artifacts-1-11-publication",
            root / "stage-M11",
            root / "stage-run_manifest.json",
            root / "stage-M12",
            root / "stage-recommendation.json",
            root / "stage-M13",
            root / "stage-failure.json",
            root / "stage-MF",
        )

    def ensure_root(self) -> None:
        """Create the operational staging ancestors without adopting unsafe objects."""

        for path in (self.root.parent, self.root):
            try:
                os.mkdir(path, 0o700)
            except FileExistsError:
                require_ordinary_directory(path)

    def create_prepared_artifacts(self, artifacts: Mapping[str, bytes]) -> None:
        self.ensure_root()
        _create_staged_directory(self.prepared_artifacts_1_11, artifacts)


def study_lock_path(primary_target: StrPath = PRIMARY_TARGET) -> Path:
    native, _ = _normalize_unscoped(primary_target)
    lock = native.with_name(native.name + ".rde-lock")
    _validate_component(lock.name)
    return lock


class _Overlapped(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", ctypes.c_uint32),
        ("OffsetHigh", ctypes.c_uint32),
        ("hEvent", ctypes.c_void_p),
    ]


class _WinDLLFactory(_Protocol):
    def __call__(self, name: str, *, use_last_error: bool) -> ctypes.CDLL: ...


def _require_windows_api() -> None:
    if os.name != "nt":
        raise OSError(errno.ENOSYS, "Windows APIs are unavailable on this platform.")


def _windows_kernel32() -> ctypes.CDLL:
    _require_windows_api()
    win_dll = getattr(ctypes, "WinDLL", None)
    if not callable(win_dll):
        raise OSError(errno.ENOSYS, "ctypes.WinDLL is unavailable on Windows.")
    return cast(_WinDLLFactory, win_dll)("kernel32", use_last_error=True)


def _windows_last_error() -> int:
    _require_windows_api()
    get_last_error = getattr(ctypes, "get_last_error", None)
    if not callable(get_last_error):
        raise OSError(errno.ENOSYS, "ctypes.get_last_error is unavailable on Windows.")
    return cast(Callable[[], int], get_last_error)()


def _windows_get_osfhandle(descriptor: int) -> int:
    _require_windows_api()
    try:
        msvcrt = _import_module("msvcrt")
    except ImportError as error:
        raise OSError(errno.ENOSYS, "msvcrt is unavailable on Windows.") from error
    get_osfhandle = getattr(msvcrt, "get_osfhandle", None)
    if not callable(get_osfhandle):
        raise OSError(errno.ENOSYS, "msvcrt.get_osfhandle is unavailable on Windows.")
    return cast(Callable[[int], int], get_osfhandle)(descriptor)


class StudyLock:
    """The one cross-process shared/exclusive whole-file study lock."""

    def __init__(self, path: StrPath) -> None:
        self.path = _lexical_absolute(path)
        _assert_safe_ancestors(self.path.parent)
        _validate_component(self.path.name)
        self._file_descriptor: int | None = None
        self._overlapped: _Overlapped | None = None

    @classmethod
    def for_primary_target(cls, primary_target: StrPath = PRIMARY_TARGET) -> StudyLock:
        return cls(study_lock_path(primary_target))

    def _open(self) -> int:
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        try:
            descriptor = os.open(self.path, flags | os.O_EXCL, 0o600)
        except FileExistsError:
            require_ordinary_file(self.path)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(self.path, flags)
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or _is_reparse(opened):
                os.close(descriptor)
                raise UnsafePathError("The study lock backing object is unsafe.") from None
        return descriptor

    def _acquire(self, *, exclusive: bool, blocking: bool) -> bool:
        if self._file_descriptor is not None:
            raise LifecycleIOError("The study lock is already acquired by this object.")
        descriptor = self._open()
        try:
            if os.name == "nt":
                kernel32 = _windows_kernel32()
                lock_file_ex = kernel32.LockFileEx
                lock_file_ex.argtypes = (
                    ctypes.c_void_p,
                    ctypes.c_uint32,
                    ctypes.c_uint32,
                    ctypes.c_uint32,
                    ctypes.c_uint32,
                    ctypes.POINTER(_Overlapped),
                )
                lock_file_ex.restype = ctypes.c_int
                flags = (0x2 if exclusive else 0) | (0 if blocking else 0x1)
                overlapped = _Overlapped()
                handle = ctypes.c_void_p(_windows_get_osfhandle(descriptor))
                if not lock_file_ex(handle, flags, 0, 0xFFFFFFFF, 0xFFFFFFFF, overlapped):
                    error_code = _windows_last_error()
                    if not blocking and error_code in {32, 33, 158, 997}:
                        os.close(descriptor)
                        return False
                    raise OSError(error_code, "LockFileEx failed.")
                self._overlapped = overlapped
            else:
                fcntl = __import__("fcntl")
                fcntl_values = vars(fcntl)
                operation = int(fcntl_values["LOCK_EX" if exclusive else "LOCK_SH"])
                if not blocking:
                    operation |= int(fcntl_values["LOCK_NB"])
                flock = cast(Callable[[int, int], None], fcntl_values["flock"])
                try:
                    flock(descriptor, operation)
                except BlockingIOError:
                    os.close(descriptor)
                    return False
        except Exception:
            if self._file_descriptor is None:
                with suppress(OSError):
                    os.close(descriptor)
            raise
        self._file_descriptor = descriptor
        return True

    def acquire_shared(self, *, blocking: bool = True) -> bool:
        return self._acquire(exclusive=False, blocking=blocking)

    def acquire_exclusive(self, *, blocking: bool = True) -> bool:
        return self._acquire(exclusive=True, blocking=blocking)

    def release(self) -> None:
        descriptor = self._file_descriptor
        if descriptor is None:
            return
        try:
            if os.name == "nt":
                kernel32 = _windows_kernel32()
                unlock_file_ex = kernel32.UnlockFileEx
                unlock_file_ex.argtypes = (
                    ctypes.c_void_p,
                    ctypes.c_uint32,
                    ctypes.c_uint32,
                    ctypes.c_uint32,
                    ctypes.POINTER(_Overlapped),
                )
                unlock_file_ex.restype = ctypes.c_int
                overlapped = self._overlapped or _Overlapped()
                handle = ctypes.c_void_p(_windows_get_osfhandle(descriptor))
                if not unlock_file_ex(handle, 0, 0xFFFFFFFF, 0xFFFFFFFF, overlapped):
                    raise OSError(_windows_last_error(), "UnlockFileEx failed.")
            else:
                fcntl = __import__("fcntl")
                fcntl_values = vars(fcntl)
                flock = cast(Callable[[int, int], None], fcntl_values["flock"])
                flock(descriptor, int(fcntl_values["LOCK_UN"]))
        finally:
            self._file_descriptor = None
            self._overlapped = None
            os.close(descriptor)

    def __enter__(self) -> StudyLock:
        self.acquire_exclusive(blocking=True)
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.release()


def fsync_directory(path: StrPath) -> None:
    """Durably flush one exact ordinary directory, or fail closed."""

    directory = _lexical_absolute(path)
    require_ordinary_directory(directory)
    try:
        if os.name == "nt":
            kernel32 = _windows_kernel32()
            create_file = kernel32.CreateFileW
            create_file.argtypes = (
                ctypes.c_wchar_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_void_p,
            )
            create_file.restype = ctypes.c_void_p
            handle = create_file(
                str(directory),
                0x40000000,
                0x1 | 0x2 | 0x4,
                None,
                3,
                0x02000000 | 0x00200000,
                None,
            )
            invalid = ctypes.c_void_p(-1).value
            if handle in {None, invalid}:
                raise OSError(_windows_last_error(), "CreateFileW(directory) failed.")
            try:
                flush = kernel32.FlushFileBuffers
                flush.argtypes = (ctypes.c_void_p,)
                flush.restype = ctypes.c_int
                if not flush(handle):
                    raise OSError(_windows_last_error(), "FlushFileBuffers(directory) failed.")
            finally:
                kernel32.CloseHandle(handle)
        else:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(directory, flags)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except OSError as error:
        raise DurabilityError(
            f"Required directory flush failed for {directory!s}.",
            failed_path=directory,
        ) from error


def fsync_directory_chain(directories: Sequence[StrPath]) -> None:
    observed: set[str] = set()
    barrier_index = 0
    for directory in directories:
        lexical = os.path.normcase(os.path.normpath(os.path.abspath(_fspath(directory))))
        if lexical in observed:
            continue
        observed.add(lexical)
        try:
            fsync_directory(directory)
        except DurabilityError as error:
            code = "IO_DIRECTORY_FSYNC" if barrier_index == 0 else "IO_PARENT_DIRECTORY_FSYNC"
            raise DurabilityError(
                str(error),
                protocol_error_code=code,
                failed_path=directory,
            ) from error
        barrier_index += 1


def ensure_ordinary_directory_durable(path: StrPath) -> bool:
    """Create or safely recognize one directory and durably flush it and its parent.

    The return value is true only when this call created the directory.  Existing symlinks,
    junctions, reparse points, and non-directories fail closed rather than being adopted.
    Empty ledger/staging roots are operational namespace, so recognizing an existing exact
    ordinary directory does not recognize or adopt any protocol final within it.
    """

    directory = _lexical_absolute(path)
    _assert_safe_ancestors(directory.parent)
    created = False
    try:
        os.mkdir(directory, 0o700)
        created = True
    except FileExistsError:
        require_ordinary_directory(directory)
    try:
        fsync_directory(directory)
    except DurabilityError as error:
        raise DurabilityError(
            str(error),
            protocol_error_code="IO_DIRECTORY_FSYNC",
            failed_path=directory,
        ) from error
    try:
        fsync_directory(directory.parent)
    except DurabilityError as error:
        raise DurabilityError(
            str(error),
            protocol_error_code="IO_PARENT_DIRECTORY_FSYNC",
            failed_path=directory.parent,
        ) from error
    return created


def _write_file_exclusive(path: Path, content: bytes) -> None:
    if type(content) is not bytes:
        raise TypeError("Published content must be exact bytes.")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as error:
        raise ExistingDestinationError(
            f"Staging destination already exists: {path!s}.",
            protocol_error_code="NAMESPACE_UNEXPECTED_ENTRY",
            failed_path=path,
        ) from error
    except OSError as error:
        raise LifecycleIOError(
            f"Staging destination cannot be created: {path!s}.",
            protocol_error_code="IO_STAGE_WRITE",
            failed_path=path,
        ) from error
    try:
        with os.fdopen(descriptor, "wb") as handle:
            try:
                handle.write(content)
            except OSError as error:
                raise LifecycleIOError(
                    f"Staged bytes cannot be written: {path!s}.",
                    protocol_error_code="IO_STAGE_WRITE",
                    failed_path=path,
                ) from error
            try:
                handle.flush()
            except OSError as error:
                raise LifecycleIOError(
                    f"Staged bytes cannot be flushed: {path!s}.",
                    protocol_error_code="IO_STAGE_FLUSH",
                    failed_path=path,
                ) from error
            try:
                os.fsync(handle.fileno())
            except OSError as error:
                raise LifecycleIOError(
                    f"Staged bytes cannot be file-fsynced: {path!s}.",
                    protocol_error_code="IO_STAGE_FILE_FSYNC",
                    failed_path=path,
                ) from error
    except Exception as error:
        with suppress(OSError):
            os.unlink(path)
        if isinstance(error, LifecycleIOError):
            raise
        raise LifecycleIOError(
            f"Staged file cannot be closed after flushing: {path!s}.",
            protocol_error_code="IO_STAGE_FLUSH",
            failed_path=path,
        ) from error


def _read_ordinary_file(
    path: Path,
    *,
    protocol_error_code: str = "IO_FINAL_READBACK",
) -> bytes:
    try:
        before = require_ordinary_file(path)
    except UnsafePathError as error:
        raise PublicationValidationError(
            str(error),
            protocol_error_code="NAMESPACE_OBJECT_TYPE",
            failed_path=path,
        ) from error
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or _is_reparse(opened):
                raise PublicationValidationError(
                    "Readback object is not an ordinary file.",
                    protocol_error_code=protocol_error_code,
                    failed_path=path,
                )
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise PublicationValidationError(
                    "Readback path changed during validation.",
                    protocol_error_code=protocol_error_code,
                    failed_path=path,
                )
            return handle.read()
    except PublicationValidationError:
        raise
    except OSError as error:
        raise PublicationValidationError(
            f"Installed file cannot be reopened: {path!s}.",
            protocol_error_code=protocol_error_code,
            failed_path=path,
        ) from error


def read_exact_directory(
    path: Path,
    expected_names: set[str],
    *,
    protocol_error_code: str = "IO_FINAL_READBACK",
) -> dict[str, bytes]:
    try:
        require_ordinary_directory(path)
    except UnsafePathError as error:
        raise PublicationValidationError(
            str(error),
            protocol_error_code="NAMESPACE_OBJECT_TYPE",
            failed_path=path,
        ) from error
    try:
        with os.scandir(path) as iterator:
            entries = {entry.name: entry for entry in iterator}
    except OSError as error:
        raise PublicationValidationError(
            "Installed directory cannot be enumerated.",
            protocol_error_code=protocol_error_code,
            failed_path=path,
        ) from error
    if set(entries) != expected_names:
        raise PublicationValidationError(
            "Installed directory has missing or unexpected entries.",
            protocol_error_code="NAMESPACE_UNEXPECTED_ENTRY",
            failed_path=path,
        )
    return {
        name: _read_ordinary_file(
            path / name,
            protocol_error_code=protocol_error_code,
        )
        for name in sorted(expected_names)
    }


def _atomic_install_no_replace(staging: Path, destination: Path) -> None:
    try:
        if os.name == "nt":
            os.rename(staging, destination)
        elif sys.platform.startswith("linux"):
            library = ctypes.CDLL(None, use_errno=True)
            try:
                renameat2 = library.renameat2
            except AttributeError as error:
                raise OSError(errno.ENOTSUP, "renameat2(RENAME_NOREPLACE) unavailable") from error
            renameat2.argtypes = (
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            )
            renameat2.restype = ctypes.c_int
            if renameat2(-100, os.fsencode(staging), -100, os.fsencode(destination), 1) != 0:
                number = ctypes.get_errno()
                raise OSError(number, os.strerror(number), destination)
        elif sys.platform == "darwin":
            library = ctypes.CDLL(None, use_errno=True)
            renamex_np = library.renamex_np
            renamex_np.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
            renamex_np.restype = ctypes.c_int
            if renamex_np(os.fsencode(staging), os.fsencode(destination), 4) != 0:
                number = ctypes.get_errno()
                raise OSError(number, os.strerror(number), destination)
        else:
            raise OSError(errno.ENOTSUP, "Atomic no-replace rename is unavailable.")
    except OSError as error:
        if error.errno in {errno.EEXIST, errno.ENOTEMPTY}:
            raise ExistingDestinationError(
                f"Final destination already exists: {destination!s}.",
                protocol_error_code="NAMESPACE_EXISTING_FINAL",
                failed_path=destination,
            ) from error
        raise LifecycleIOError(
            f"Atomic no-replace installation failed: {destination!s}.",
            protocol_error_code="IO_NO_REPLACE_INSTALL",
            failed_path=destination,
        ) from error


def _publication_paths(staging: StrPath, destination: StrPath) -> tuple[Path, Path]:
    staged = _lexical_absolute(staging)
    final = _lexical_absolute(destination)
    _assert_safe_ancestors(staged.parent)
    _assert_safe_ancestors(final.parent)
    if (
        staged.parent == final.parent
        or is_path_within(staged, final)
        or is_path_within(final, staged)
    ):
        raise UnsafePathError(
            "Staging must be external to the final namespace.",
            protocol_error_code="NAMESPACE_TARGET",
            failed_path=staged,
        )
    if (
        require_ordinary_directory(staged.parent).st_dev
        != require_ordinary_directory(final.parent).st_dev
    ):
        raise UnsafePathError(
            "Staging and final destination must be on one filesystem/volume.",
            protocol_error_code="NAMESPACE_TARGET",
            failed_path=staged,
        )
    return staged, final


def _durability_paths(
    destination: Path, *, directory: bool, supplied: Sequence[StrPath] | None
) -> tuple[StrPath, ...]:
    if supplied is not None:
        if not supplied:
            raise DurabilityError("A supplied durability sequence cannot be empty.")
        return tuple(supplied)
    return (destination, destination.parent) if directory else (destination.parent,)


def publish_bytes_no_replace(
    staging: StrPath,
    destination: StrPath,
    content: bytes,
    *,
    validator: FileValidator | None = None,
    durability_directories: Sequence[StrPath] | None = None,
) -> bytes:
    """O_EXCL-stage and durably create one immutable final file."""

    staged, final = _publication_paths(staging, destination)
    _write_file_exclusive(staged, content)
    installed = False
    try:
        _atomic_install_no_replace(staged, final)
        installed = True
        observed = _read_ordinary_file(final)
        if observed != content:
            raise PublicationValidationError(
                "Installed bytes differ from the exact staged bytes.",
                protocol_error_code="IO_FINAL_READBACK",
                failed_path=final,
            )
        if validator is not None:
            validator(observed)
        fsync_directory_chain(
            _durability_paths(final, directory=False, supplied=durability_directories)
        )
        return observed
    finally:
        if not installed and os.path.lexists(staged):
            with suppress(OSError):
                os.unlink(staged)


def _validate_file_map(files: Mapping[str, bytes]) -> dict[str, bytes]:
    if not files:
        raise PublicationValidationError(
            "A staged publication directory cannot be empty.",
            protocol_error_code="VALIDATION_STAGED_BYTES",
        )
    result: dict[str, bytes] = {}
    aliases: set[str] = set()
    for name, content in files.items():
        _validate_component(name)
        alias = os.path.normcase(unicodedata.normalize("NFC", name))
        if alias in aliases:
            raise UnsafePathError(
                "Staged filenames contain a normalized/case alias.",
                protocol_error_code="NAMESPACE_UNEXPECTED_ENTRY",
            )
        aliases.add(alias)
        if type(content) is not bytes:
            raise TypeError("Published directory members must be exact bytes.")
        result[name] = content
    return result


def _create_staged_directory(path: Path, files: Mapping[str, bytes]) -> None:
    expected = _validate_file_map(files)
    try:
        os.mkdir(path, 0o700)
    except FileExistsError as error:
        raise ExistingDestinationError(
            f"Staging destination already exists: {path!s}.",
            protocol_error_code="NAMESPACE_UNEXPECTED_ENTRY",
            failed_path=path,
        ) from error
    except OSError as error:
        raise LifecycleIOError(
            f"Staged directory cannot be created: {path!s}.",
            protocol_error_code="IO_STAGE_WRITE",
            failed_path=path,
        ) from error
    created: list[Path] = []
    try:
        for name in sorted(expected, key=lambda item: item.encode("utf-8")):
            child = path / name
            _write_file_exclusive(child, expected[name])
            created.append(child)
        try:
            fsync_directory(path)
        except DurabilityError as error:
            raise DurabilityError(
                str(error),
                protocol_error_code="IO_STAGE_FLUSH",
                failed_path=path,
            ) from error
    except Exception:
        for child in reversed(created):
            with suppress(OSError):
                child.unlink()
        with suppress(OSError):
            path.rmdir()
        raise


def publish_staged_directory_no_replace(
    staging: StrPath,
    destination: StrPath,
    expected_files: Mapping[str, bytes],
    *,
    validator: DirectoryValidator | None = None,
    durability_directories: Sequence[StrPath] | None = None,
) -> dict[str, bytes]:
    """Validate, fsync, and no-replace install one already-created staged directory."""

    expected = _validate_file_map(expected_files)
    staged, final = _publication_paths(staging, destination)
    observed_stage = read_exact_directory(
        staged,
        set(expected),
        protocol_error_code="NAMESPACE_OBJECT_TYPE",
    )
    if observed_stage != expected:
        raise PublicationValidationError(
            "Staged directory bytes differ from expected bytes.",
            protocol_error_code="VALIDATION_STAGED_BYTES",
            failed_path=staged,
        )
    for name in expected:
        child = staged / name
        try:
            require_ordinary_file(child)
        except UnsafePathError as error:
            raise UnsafePathError(
                str(error),
                protocol_error_code="NAMESPACE_OBJECT_TYPE",
                failed_path=child,
            ) from error
        try:
            descriptor = os.open(
                child,
                os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                opened = os.fstat(descriptor)
                if not stat.S_ISREG(opened.st_mode) or _is_reparse(opened):
                    raise UnsafePathError(
                        "A staged directory member is not an ordinary file.",
                        protocol_error_code="NAMESPACE_OBJECT_TYPE",
                        failed_path=child,
                    )
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except UnsafePathError:
            raise
        except OSError as error:
            raise LifecycleIOError(
                f"Staged directory member cannot be file-fsynced: {child!s}.",
                protocol_error_code="IO_STAGE_FILE_FSYNC",
                failed_path=child,
            ) from error
    try:
        fsync_directory(staged)
    except DurabilityError as error:
        raise DurabilityError(
            str(error),
            protocol_error_code="IO_STAGE_FLUSH",
            failed_path=staged,
        ) from error
    _atomic_install_no_replace(staged, final)
    observed = read_exact_directory(final, set(expected))
    if observed != expected:
        raise PublicationValidationError(
            "Installed directory bytes differ from staged bytes.",
            protocol_error_code="IO_FINAL_READBACK",
            failed_path=final,
        )
    if validator is not None:
        validator(observed)
    fsync_directory_chain(_durability_paths(final, directory=True, supplied=durability_directories))
    return observed


def publish_directory_bytes_no_replace(
    staging: StrPath,
    destination: StrPath,
    files: Mapping[str, bytes],
    *,
    validator: DirectoryValidator | None = None,
    durability_directories: Sequence[StrPath] | None = None,
) -> dict[str, bytes]:
    """Exclusively create a complete staged directory and durably publish it once."""

    staged, _ = _publication_paths(staging, destination)
    _create_staged_directory(staged, files)
    try:
        return publish_staged_directory_no_replace(
            staged,
            destination,
            files,
            validator=validator,
            durability_directories=durability_directories,
        )
    except Exception:
        if os.path.lexists(staged):
            try:
                for name in files:
                    child = staged / name
                    if ordinary_file(child):
                        child.unlink()
                staged.rmdir()
            except OSError:
                pass
        raise


@dataclass(frozen=True, slots=True)
class NamespaceIdentifierScan:
    """Immutable read-only inventory used before allocating lifecycle identifiers."""

    primary_target: Path
    targets: tuple[Path, ...]
    ledger_roots: tuple[Path, ...]
    staging_roots: tuple[Path, ...]
    unsafe_staging_publications: tuple[Path, ...]
    unsafe_family_targets: tuple[Path, ...]
    malformed_family_history: bool
    publication_ids: frozenset[str]
    authorization_attempt_ids: frozenset[str]


def _scan_error(message: str, path: Path, error: BaseException | None = None) -> Never:
    failure = NamespaceScanError(
        message,
        protocol_error_code="NAMESPACE_GLOBAL_SCAN",
        failed_path=path,
    )
    if error is None:
        raise failure
    raise failure from error


def _scan_directory_names(path: Path) -> tuple[str, ...]:
    try:
        require_ordinary_directory(path)
        with os.scandir(path) as iterator:
            names = tuple(entry.name for entry in iterator)
    except (OSError, LifecycleIOError) as error:
        _scan_error(
            f"Lifecycle namespace is unreadable or not an ordinary directory: {path!s}.",
            path,
            error,
        )
    return tuple(sorted(names, key=lambda item: item.encode("utf-8")))


def _scan_observed_ordinary_file(path: Path) -> bool:
    try:
        result = os.lstat(path)
    except OSError as error:
        _scan_error(f"Lifecycle namespace object cannot be inspected: {path!s}.", path, error)
    return stat.S_ISREG(result.st_mode) and not _is_reparse(result)


def _scan_observed_ordinary_directory(path: Path) -> bool:
    try:
        result = os.lstat(path)
    except OSError as error:
        _scan_error(f"Lifecycle namespace object cannot be inspected: {path!s}.", path, error)
    return stat.S_ISDIR(result.st_mode) and not _is_reparse(result)


def _scan_readable_ordinary_file(path: Path, *, complete: bool) -> bytes:
    try:
        before = require_ordinary_file(path)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or _is_reparse(opened)
                or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            ):
                _scan_error("Lifecycle namespace file changed or is unsafe.", path)
            return handle.read() if complete else handle.read(1)
    except NamespaceScanError:
        raise
    except (OSError, LifecycleIOError) as error:
        _scan_error(f"Lifecycle namespace file is unreadable or unsafe: {path!s}.", path, error)


def _collect_json_strings(value: object, output: set[str]) -> None:
    if isinstance(value, str):
        output.add(value)
    elif isinstance(value, list):
        for item in value:
            _collect_json_strings(item, output)
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                output.add(key)
            _collect_json_strings(item, output)


def _attempt_identifiers(data: bytes) -> tuple[set[str], set[str]]:
    publication_ids = {
        match.group(1).decode("ascii") for match in _PUBLICATION_ID_BYTES_PATTERN.finditer(data)
    }
    authorization_attempt_ids = {
        match.group(1).decode("ascii")
        for match in _AUTHORIZATION_ATTEMPT_ID_BYTES_PATTERN.finditer(data)
    }
    strings: set[str] = set()
    try:
        decoded = data.decode("utf-8", errors="strict")
        parsed = json.loads(decoded)
    except (UnicodeError, json.JSONDecodeError, ValueError):
        parsed = None
    _collect_json_strings(parsed, strings)
    for value in strings:
        if PUBLICATION_ID_PATTERN.fullmatch(value) is not None:
            publication_ids.add(value)
        if AUTHORIZATION_ATTEMPT_ID_PATTERN.fullmatch(value) is not None:
            authorization_attempt_ids.add(value)
    return publication_ids, authorization_attempt_ids


def _scan_target_namespace(path: Path, *, allow_observed_unsafe: bool = False) -> bool:
    if allow_observed_unsafe and not _scan_observed_ordinary_directory(path):
        return True
    for name in _scan_directory_names(path):
        child = path / name
        if allow_observed_unsafe and not _scan_observed_ordinary_file(child):
            return True
        _scan_readable_ordinary_file(child, complete=False)
    return False


def _scan_attempt_bytes(
    path: Path,
    publication_ids: set[str],
    authorization_attempt_ids: set[str],
) -> None:
    data = _scan_readable_ordinary_file(path, complete=True)
    observed_publications, observed_authorizations = _attempt_identifiers(data)
    publication_ids.update(observed_publications)
    authorization_attempt_ids.update(observed_authorizations)


def _scan_ledger_namespace(
    root: Path,
    publication_ids: set[str],
    authorization_attempt_ids: set[str],
    *,
    allow_observed_unsafe: bool = False,
) -> bool:
    malformed = False
    if allow_observed_unsafe and not _scan_observed_ordinary_directory(root):
        return True
    for publication_name in _scan_directory_names(root):
        attempt_directory = root / publication_name
        try:
            publication_id = validate_publication_id(publication_name)
        except UnsafePathError as error:
            if not allow_observed_unsafe:
                _scan_error(
                    "Ledger root contains a malformed publication namespace.",
                    attempt_directory,
                    error,
                )
            malformed = True
            if _scan_observed_ordinary_directory(attempt_directory):
                for final_name in _scan_directory_names(attempt_directory):
                    final_path = attempt_directory / final_name
                    if _scan_observed_ordinary_file(final_path):
                        _scan_readable_ordinary_file(final_path, complete=False)
            continue
        publication_ids.add(publication_id)
        if allow_observed_unsafe and not _scan_observed_ordinary_directory(attempt_directory):
            malformed = True
            continue
        for final_name in _scan_directory_names(attempt_directory):
            if final_name not in LEDGER_FINAL_NAMES:
                if not allow_observed_unsafe:
                    _scan_error(
                        "Attempt ledger contains an unapproved final name.",
                        attempt_directory / final_name,
                    )
                malformed = True
                _scan_observed_ordinary_file(attempt_directory / final_name)
                continue
            final_path = attempt_directory / final_name
            if allow_observed_unsafe and not _scan_observed_ordinary_file(final_path):
                malformed = True
                continue
            if final_name == "attempt.json":
                _scan_attempt_bytes(final_path, publication_ids, authorization_attempt_ids)
            else:
                _scan_readable_ordinary_file(final_path, complete=False)
    return malformed


def _safe_staged_file(path: Path) -> bool:
    """Return whether one non-attempt staged file is safely inspectable.

    A defect here is attributable operational residue, not an unreadable identifier
    namespace: only staged ``attempt.json`` bytes can contribute additional IDs.
    """

    if not ordinary_file(path):
        return False
    _scan_readable_ordinary_file(path, complete=False)
    return True


def _safe_staged_directory(path: Path, allowed_names: frozenset[str]) -> bool:
    """Return whether one non-attempt staged directory is safely inspectable."""

    if not ordinary_directory(path):
        return False
    names = _scan_directory_names(path)
    for name in names:
        try:
            _validate_component(name)
        except UnsafePathError:
            return False
        if name not in allowed_names or not _safe_staged_file(path / name):
            return False
    return True


def _scan_staging_namespace(
    root: Path,
    publication_ids: set[str],
    authorization_attempt_ids: set[str],
    unsafe_staging_publications: set[Path],
) -> None:
    directory_children = {
        "attempt-publication",
        "prepared-artifacts-1-11",
        "artifacts-1-11-publication",
    }
    for publication_name in _scan_directory_names(root):
        try:
            publication_id = validate_publication_id(publication_name)
        except UnsafePathError as error:
            _scan_error(
                "Staging root contains a malformed publication namespace.",
                root / publication_name,
                error,
            )
        publication_ids.add(publication_id)
        publication_root = root / publication_name
        for child_name in _scan_directory_names(publication_root):
            if child_name not in STAGING_CHILD_NAMES:
                unsafe_staging_publications.add(publication_root)
                continue
            child = publication_root / child_name
            if child_name in directory_children:
                if child_name == "attempt-publication":
                    attempt_names = _scan_directory_names(child)
                    if "attempt.json" in attempt_names:
                        _scan_attempt_bytes(
                            child / "attempt.json",
                            publication_ids,
                            authorization_attempt_ids,
                        )
                    if any(name != "attempt.json" for name in attempt_names):
                        unsafe_staging_publications.add(publication_root)
                elif not _safe_staged_directory(child, _STAGED_ARTIFACT_1_11_NAMES):
                    unsafe_staging_publications.add(publication_root)
            elif not _safe_staged_file(child):
                unsafe_staging_publications.add(publication_root)


def _classify_top_level_namespace(
    name: str,
    primary_name: str,
) -> tuple[str, str | None] | None:
    folded = os.path.normcase(name)
    primary_folded = os.path.normcase(primary_name)
    if folded == primary_folded:
        if name != primary_name:
            raise NamespaceScanError("The primary target uses a case or normalization alias.")
        return "target", None
    exact_roots = {
        os.path.normcase(primary_name + ".rde-attempts"): ("ledger", None),
        os.path.normcase(primary_name + ".rde-staging"): ("staging", None),
    }
    if folded in exact_roots:
        expected = primary_name + (
            ".rde-attempts" if exact_roots[folded][0] == "ledger" else ".rde-staging"
        )
        if name != expected:
            raise NamespaceScanError("A lifecycle root uses a case or normalization alias.")
        return exact_roots[folded]
    retry_prefix = primary_name + ".retry-"
    retry_folded = os.path.normcase(retry_prefix)
    if folded.startswith(retry_folded):
        kind = "target"
        target_name = name
        if folded.endswith(os.path.normcase(".rde-attempts")):
            kind = "ledger"
            target_name = name[: -len(".rde-attempts")]
        elif folded.endswith(os.path.normcase(".rde-staging")):
            kind = "staging"
            target_name = name[: -len(".rde-staging")]
        if not target_name.startswith(retry_prefix):
            raise NamespaceScanError("An RX namespace uses a case or normalization alias.")
        publication_id = target_name[len(retry_prefix) :]
        try:
            validate_publication_id(publication_id)
        except UnsafePathError as error:
            raise NamespaceScanError("Malformed RX lifecycle namespace.") from error
        expected_name = target_name
        if kind == "ledger":
            expected_name += ".rde-attempts"
        elif kind == "staging":
            expected_name += ".rde-staging"
        if name != expected_name:
            raise NamespaceScanError("An RX lifecycle root uses an alias.")
        return kind, publication_id
    if folded.startswith(os.path.normcase(primary_name + ".rde-")) and folded != os.path.normcase(
        primary_name + ".rde-lock"
    ):
        raise NamespaceScanError("Malformed primary lifecycle namespace.")
    return None


def scan_lifecycle_namespace(
    primary_target: StrPath = PRIMARY_TARGET,
    *,
    inspect_staging: bool = True,
    allow_observed_unsafe: bool = False,
) -> NamespaceIdentifierScan:
    """Read every lifecycle namespace and identifier source before ID allocation.

    The operation never mutates disk.  Unrelated siblings are ignored; anything derived from
    the exact primary/RX namespace grammar is inspected completely and fails closed when its
    path, object type, inventory, or readability is unsafe.
    """

    native_primary, _canonical = _normalize_unscoped(primary_target)
    parent = native_primary.parent
    publication_ids: set[str] = set()
    authorization_attempt_ids: set[str] = set()
    targets: list[Path] = []
    ledger_roots: list[Path] = []
    staging_roots: list[Path] = []
    unsafe_staging_publications: set[Path] = set()
    unsafe_family_targets: set[Path] = set()
    malformed_family_history = False
    for name in _scan_directory_names(parent):
        path = parent / name
        try:
            classification = _classify_top_level_namespace(name, native_primary.name)
        except NamespaceScanError as error:
            if not allow_observed_unsafe:
                _scan_error(str(error), path, error)
            try:
                os.lstat(path)
            except OSError as inspection_error:
                _scan_error(
                    "Malformed lifecycle namespace cannot be inspected.",
                    path,
                    inspection_error,
                )
            unsafe_family_targets.add(native_primary)
            malformed_family_history = True
            continue
        if classification is None:
            continue
        kind, embedded_publication_id = classification
        if embedded_publication_id is not None:
            publication_ids.add(embedded_publication_id)
        if kind == "target":
            if _scan_target_namespace(
                path,
                allow_observed_unsafe=allow_observed_unsafe,
            ):
                unsafe_family_targets.add(path)
                malformed_family_history = True
            targets.append(path)
        elif kind == "ledger":
            if _scan_ledger_namespace(
                path,
                publication_ids,
                authorization_attempt_ids,
                allow_observed_unsafe=allow_observed_unsafe,
            ):
                unsafe_family_targets.add(path.with_name(path.name.removesuffix(".rde-attempts")))
                malformed_family_history = True
            ledger_roots.append(path)
        elif inspect_staging:
            _scan_staging_namespace(
                path,
                publication_ids,
                authorization_attempt_ids,
                unsafe_staging_publications,
            )
            staging_roots.append(path)
        else:
            staging_roots.append(path)

    def path_key(path: Path) -> bytes:
        return path.as_posix().encode("utf-8")

    return NamespaceIdentifierScan(
        primary_target=native_primary,
        targets=tuple(sorted(targets, key=path_key)),
        ledger_roots=tuple(sorted(ledger_roots, key=path_key)),
        staging_roots=tuple(sorted(staging_roots, key=path_key)),
        unsafe_staging_publications=tuple(sorted(unsafe_staging_publications, key=path_key)),
        unsafe_family_targets=tuple(sorted(unsafe_family_targets, key=path_key)),
        malformed_family_history=malformed_family_history,
        publication_ids=frozenset(publication_ids),
        authorization_attempt_ids=frozenset(authorization_attempt_ids),
    )


__all__ = [
    "AUTHORIZATION_ATTEMPT_ID_PATTERN",
    "CanonicalLedgerError",
    "DirectoryValidator",
    "DurabilityError",
    "ExistingDestinationError",
    "FileValidator",
    "LEDGER_FINAL_NAMES",
    "LifecycleIOError",
    "LockUnavailableError",
    "NamespaceIdentifierScan",
    "NamespaceScanError",
    "PRIMARY_TARGET",
    "PRIMARY_TARGET_NAME",
    "PUBLICATION_ID_PATTERN",
    "PublicationValidationError",
    "STAGING_CHILD_NAMES",
    "STUDY_ID",
    "StagingLayout",
    "StudyLock",
    "TargetPaths",
    "UnsafePathError",
    "canonical_json_bytes",
    "canonical_ledger_bytes",
    "ensure_ordinary_directory_durable",
    "fsync_directory",
    "fsync_directory_chain",
    "is_path_within",
    "normalize_target",
    "ordinary_directory",
    "ordinary_file",
    "parse_canonical_ledger_bytes",
    "publish_bytes_no_replace",
    "publish_directory_bytes_no_replace",
    "publish_staged_directory_no_replace",
    "raw_sha256",
    "read_exact_directory",
    "reparse_point",
    "require_ordinary_directory",
    "require_ordinary_file",
    "study_lock_path",
    "scan_lifecycle_namespace",
    "validate_authorization_attempt_id",
    "validate_ledger_final_name",
    "validate_publication_id",
]
