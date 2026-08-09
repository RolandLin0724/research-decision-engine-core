"""Trusted local direct-child command workload adapter."""

from __future__ import annotations

import json
import math
import os
import stat
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal, cast

from research_decision_engine.adapters import WorkloadAdapterError
from research_decision_engine.run_spec import (
    CandidateSpec,
    NormalizedObservation,
    _canonical_json_bytes,
    _object_without_duplicate_keys,
    _reject_nonfinite_json_constant,
    _validated_string,
)

_TERMINATION_GRACE_SECONDS: Final = 1.0
_STDERR_EXCERPT_BYTES: Final = 4096
_OBSERVATION_KEYS: Final = frozenset({"cost", "objective_value"})

CommandOutputReason = Literal[
    "oversized_stdout",
    "oversized_stderr",
    "encoding_violation",
    "malformed_json",
    "invalid_normalized_observation",
    "output_io_failure",
]
CommandOutputStream = Literal["stdout", "stderr"]


class CommandAdapterError(WorkloadAdapterError):
    """Base class for ordinary CommandAdapter failures."""


class CommandBuildError(CommandAdapterError):
    """The trusted command builder failed or returned an invalid invocation."""


class CommandTimeoutError(CommandAdapterError):
    """The direct child exceeded its timeout."""

    def __init__(self, *, timeout_seconds: float, direct_child_reaped: bool) -> None:
        self.timed_out = True
        self.timeout_seconds = timeout_seconds
        self.direct_child_reaped = direct_child_reaped
        self.descendant_process_tree_cleanup_guaranteed = False
        super().__init__(
            f"Direct child timed out after {timeout_seconds!r} seconds; "
            f"direct_child_reaped={direct_child_reaped!r}. "
            "Descendant process-tree cleanup is not guaranteed."
        )


class CommandExitError(CommandAdapterError):
    """The direct child exited with a nonzero return code."""

    def __init__(self, *, return_code: int, stderr: bytes) -> None:
        self.return_code = return_code
        self.stderr_excerpt = stderr[:_STDERR_EXCERPT_BYTES]
        self.stderr_excerpt_truncated = len(stderr) > _STDERR_EXCERPT_BYTES
        super().__init__(
            f"Direct child exited with return code {return_code}; "
            f"stderr_excerpt_bytes={len(self.stderr_excerpt)}, "
            f"stderr_excerpt_truncated={self.stderr_excerpt_truncated!r}."
        )


class CommandOutputError(CommandAdapterError):
    """The child output violated a size, encoding, JSON, or observation rule."""

    def __init__(
        self,
        reason: CommandOutputReason,
        *,
        stream: CommandOutputStream | None = None,
        observed_bytes: int | None = None,
        limit_bytes: int | None = None,
    ) -> None:
        self.reason = reason
        self.stream = stream
        self.observed_bytes = observed_bytes
        self.limit_bytes = limit_bytes
        details = []
        if stream is not None:
            details.append(f"stream={stream}")
        if observed_bytes is not None:
            details.append(f"observed_bytes={observed_bytes}")
        if limit_bytes is not None:
            details.append(f"limit_bytes={limit_bytes}")
        suffix = f" ({', '.join(details)})" if details else ""
        super().__init__(f"Command output violation: {reason}{suffix}.")


@dataclass(frozen=True, slots=True, init=False)
class CommandInvocation:
    """One immutable, direct-child command invocation without shell semantics."""

    argv: tuple[str, ...]
    cwd: Path | None
    _environment_items: tuple[tuple[str, str], ...] = field(repr=False)
    inherit_environment: bool
    timeout_seconds: float
    max_stdout_bytes: int
    max_stderr_bytes: int

    def __init__(
        self,
        *,
        argv: tuple[str, ...],
        cwd: Path | None,
        environment_overrides: Mapping[str, str],
        inherit_environment: bool,
        timeout_seconds: float,
        max_stdout_bytes: int,
        max_stderr_bytes: int,
    ) -> None:
        if type(argv) is not tuple or not argv:
            raise ValueError("argv must be a nonempty exact tuple of strings.")
        if any(type(argument) is not str for argument in argv):
            raise TypeError("Every argv member must be an exact string.")
        if not argv[0]:
            raise ValueError("argv executable must be nonempty.")
        if any("\0" in argument for argument in argv):
            raise ValueError("argv members must not contain NUL.")

        normalized_cwd: Path | None
        if cwd is None:
            normalized_cwd = None
        else:
            if not isinstance(cwd, Path):
                raise TypeError("cwd must be a pathlib.Path or None.")
            normalized_cwd = Path(os.path.abspath(cwd))
            if not normalized_cwd.is_dir():
                raise ValueError("cwd must be an existing directory.")

        if not isinstance(environment_overrides, Mapping):
            raise TypeError("environment_overrides must be a mapping.")
        environment: dict[str, str] = {}
        for key, value in environment_overrides.items():
            if type(key) is not str or type(value) is not str:
                raise TypeError("Environment keys and values must be exact strings.")
            if "\0" in key or "\0" in value:
                raise ValueError("Environment keys and values must not contain NUL.")
            environment[key] = value

        if type(inherit_environment) is not bool:
            raise TypeError("inherit_environment must be an exact boolean.")
        normalized_timeout = _positive_finite_real(timeout_seconds, "timeout_seconds")
        normalized_stdout_limit = _positive_integer(max_stdout_bytes, "max_stdout_bytes")
        normalized_stderr_limit = _positive_integer(max_stderr_bytes, "max_stderr_bytes")

        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "cwd", normalized_cwd)
        object.__setattr__(self, "_environment_items", tuple(sorted(environment.items())))
        object.__setattr__(self, "inherit_environment", inherit_environment)
        object.__setattr__(self, "timeout_seconds", normalized_timeout)
        object.__setattr__(self, "max_stdout_bytes", normalized_stdout_limit)
        object.__setattr__(self, "max_stderr_bytes", normalized_stderr_limit)

    @property
    def environment_overrides(self) -> Mapping[str, str]:
        """Return a detached read-only copy of the environment overrides."""

        return MappingProxyType(dict(self._environment_items))


@dataclass(frozen=True, slots=True, init=False)
class CommandAdapter:
    """Execute one trusted local direct child for each truth-free candidate.

    The builder and command are not sandboxed. Only the direct child is terminated
    and reaped on timeout; descendant process-tree cleanup is not guaranteed.
    Identity comes solely from the declared adapter ID and version.
    """

    adapter_id: str
    adapter_version: str
    _command_builder: Callable[[CandidateSpec], CommandInvocation] = field(
        repr=False, compare=False
    )

    def __init__(
        self,
        command_builder: Callable[[CandidateSpec], CommandInvocation],
        *,
        adapter_id: str,
        adapter_version: str,
    ) -> None:
        if not callable(command_builder):
            raise TypeError("command_builder must be callable.")
        object.__setattr__(
            self, "adapter_id", _validated_string(adapter_id, field_name="adapter_id")
        )
        object.__setattr__(
            self,
            "adapter_version",
            _validated_string(adapter_version, field_name="adapter_version"),
        )
        object.__setattr__(self, "_command_builder", command_builder)

    def evaluate(self, candidate: CandidateSpec) -> NormalizedObservation:
        """Build once, execute once without a shell, and return one observation."""

        if type(candidate) is not CandidateSpec:
            raise TypeError("candidate must be an exact CandidateSpec.")
        try:
            built = self._command_builder(candidate)
        except Exception as exc:
            raise CommandBuildError("Command builder failed.") from exc
        if type(built) is not CommandInvocation:
            error = TypeError("command_builder must return an exact CommandInvocation.")
            raise CommandBuildError("Command builder returned an invalid invocation.") from error
        try:
            invocation = CommandInvocation(
                argv=built.argv,
                cwd=built.cwd,
                environment_overrides=built.environment_overrides,
                inherit_environment=built.inherit_environment,
                timeout_seconds=built.timeout_seconds,
                max_stdout_bytes=built.max_stdout_bytes,
                max_stderr_bytes=built.max_stderr_bytes,
            )
        except Exception as exc:
            raise CommandBuildError("Command builder returned an invalid invocation.") from exc
        return _execute(invocation)


def _positive_finite_real(value: object, field_name: str) -> float:
    if type(value) not in (int, float):
        raise TypeError(f"{field_name} must be a real number, not a boolean.")
    normalized = float(cast(int | float, value))
    if not math.isfinite(normalized) or normalized <= 0.0:
        raise ValueError(f"{field_name} must be finite and strictly positive.")
    return normalized


def _positive_integer(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an integer, not a boolean.")
    if value <= 0:
        raise ValueError(f"{field_name} must be positive.")
    return value


def _environment(invocation: CommandInvocation) -> dict[str, str]:
    environment = os.environ.copy() if invocation.inherit_environment else {}
    for key, value in invocation.environment_overrides.items():
        if os.name == "nt":
            folded_key = key.casefold()
            for inherited_key in tuple(environment):
                if inherited_key.casefold() == folded_key:
                    del environment[inherited_key]
        environment[key] = value
    return environment


def _execute(invocation: CommandInvocation) -> NormalizedObservation:
    if invocation.cwd is not None and not invocation.cwd.is_dir():
        raise CommandBuildError("Command invocation cwd is no longer an existing directory.")

    temporary_directory: tempfile.TemporaryDirectory[str] | None = None
    try:
        temporary_directory = tempfile.TemporaryDirectory(
            prefix="rde-command-adapter-",
            dir=_temporary_parent(invocation),
        )
        temporary_root = temporary_directory.name
        try:
            root = Path(temporary_root)
            with (
                (root / "stdout.bin").open("x+b") as stdout_file,
                (root / "stderr.bin").open("x+b") as stderr_file,
            ):
                try:
                    process = subprocess.Popen(  # noqa: S603 - direct argv is the contract
                        invocation.argv,
                        shell=False,
                        stdin=subprocess.DEVNULL,
                        stdout=stdout_file,
                        stderr=stderr_file,
                        cwd=invocation.cwd,
                        env=_environment(invocation),
                        close_fds=True,
                    )
                except (OSError, ValueError) as exc:
                    raise CommandAdapterError("Direct child process could not be started.") from exc

                try:
                    return_code = process.wait(timeout=invocation.timeout_seconds)
                except subprocess.TimeoutExpired as exc:
                    reaped = _terminate_and_reap(process)
                    raise CommandTimeoutError(
                        timeout_seconds=invocation.timeout_seconds,
                        direct_child_reaped=reaped,
                    ) from exc
                except Exception as exc:
                    _terminate_and_reap(process)
                    raise CommandAdapterError("Waiting for the direct child failed.") from exc
                except BaseException:
                    _terminate_and_reap(process)
                    raise

                stdout_size = _regular_file_size(stdout_file, "stdout")
                stderr_size = _regular_file_size(stderr_file, "stderr")
                if stdout_size > invocation.max_stdout_bytes:
                    raise CommandOutputError(
                        "oversized_stdout",
                        stream="stdout",
                        observed_bytes=stdout_size,
                        limit_bytes=invocation.max_stdout_bytes,
                    )
                if stderr_size > invocation.max_stderr_bytes:
                    raise CommandOutputError(
                        "oversized_stderr",
                        stream="stderr",
                        observed_bytes=stderr_size,
                        limit_bytes=invocation.max_stderr_bytes,
                    )
                stdout = _read_exact(stdout_file, stdout_size, "stdout")
                stderr = _read_exact(stderr_file, stderr_size, "stderr")
        except BaseException:
            with suppress(Exception):
                temporary_directory.cleanup()
            raise
        try:
            temporary_directory.cleanup()
        except Exception as exc:
            raise CommandAdapterError("CommandAdapter temporary-output cleanup failed.") from exc
    except CommandAdapterError:
        raise
    except Exception as exc:
        raise CommandAdapterError("CommandAdapter temporary-output handling failed.") from exc

    if return_code != 0:
        raise CommandExitError(return_code=return_code, stderr=stderr)
    return _decode_observation(stdout)


def _terminate_and_reap(process: subprocess.Popen[bytes]) -> bool:
    try:
        if process.poll() is not None:
            return True
    except Exception:
        pass

    with suppress(Exception):
        process.terminate()
    try:
        process.wait(timeout=_TERMINATION_GRACE_SECONDS)
        return True
    except Exception:
        pass

    try:
        if process.poll() is None:
            process.kill()
    except Exception:
        with suppress(Exception):
            process.kill()
    try:
        process.wait(timeout=_TERMINATION_GRACE_SECONDS)
        return True
    except Exception:
        try:
            return process.poll() is not None
        except Exception:
            return False


def _temporary_parent(invocation: CommandInvocation) -> str:
    parent = Path(tempfile.gettempdir()).resolve()
    repository_roots = {
        repository
        for candidate in (Path(__file__).resolve(), Path.cwd(), invocation.cwd)
        if candidate is not None
        for repository in (_containing_repository(candidate),)
        if repository is not None
    }
    if any(
        parent == repository or parent.is_relative_to(repository) for repository in repository_roots
    ):
        raise CommandAdapterError(
            "CommandAdapter temporary-output parent must be outside the repository."
        )
    return str(parent)


def _containing_repository(path: Path) -> Path | None:
    current = path if path.is_dir() else path.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate.resolve()
    return None


def _regular_file_size(file: object, stream: CommandOutputStream) -> int:
    try:
        descriptor = cast(int, file.fileno())  # type: ignore[attr-defined]
        status = os.fstat(descriptor)
    except (AttributeError, OSError, ValueError) as exc:
        raise CommandOutputError("output_io_failure", stream=stream) from exc
    if not stat.S_ISREG(status.st_mode):
        raise CommandOutputError("output_io_failure", stream=stream)
    return status.st_size


def _read_exact(file: object, size: int, stream: CommandOutputStream) -> bytes:
    try:
        file.seek(0)  # type: ignore[attr-defined]
        payload = cast(bytes, file.read(size))  # type: ignore[attr-defined]
        trailing = cast(bytes, file.read(1))  # type: ignore[attr-defined]
    except (AttributeError, OSError, ValueError) as exc:
        raise CommandOutputError("output_io_failure", stream=stream) from exc
    if len(payload) != size or trailing:
        raise CommandOutputError(
            "output_io_failure",
            stream=stream,
            observed_bytes=len(payload) + len(trailing),
        )
    return payload


def _decode_observation(encoded: bytes) -> NormalizedObservation:
    if encoded.startswith(b"\xef\xbb\xbf"):
        raise CommandOutputError("encoding_violation", stream="stdout", observed_bytes=len(encoded))
    try:
        text = encoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CommandOutputError(
            "encoding_violation", stream="stdout", observed_bytes=len(encoded)
        ) from exc
    if b"\r" in encoded or not encoded.endswith(b"\n") or encoded.endswith(b"\n\n"):
        raise CommandOutputError("malformed_json", stream="stdout", observed_bytes=len(encoded))
    try:
        payload = cast(
            object,
            json.loads(
                text,
                object_pairs_hook=_object_without_duplicate_keys,
                parse_constant=_reject_nonfinite_json_constant,
                parse_float=_parse_finite_float,
            ),
        )
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise CommandOutputError(
            "malformed_json", stream="stdout", observed_bytes=len(encoded)
        ) from exc
    if type(payload) is not dict or frozenset(payload) != _OBSERVATION_KEYS:
        raise CommandOutputError(
            "invalid_normalized_observation", stream="stdout", observed_bytes=len(encoded)
        )
    observation_payload = cast(dict[str, object], payload)
    try:
        observation = NormalizedObservation(
            objective_value=cast(float, observation_payload["objective_value"]),
            cost=cast(float, observation_payload["cost"]),
        )
    except (OverflowError, TypeError, ValueError) as exc:
        raise CommandOutputError(
            "invalid_normalized_observation", stream="stdout", observed_bytes=len(encoded)
        ) from exc
    expected = _canonical_json_bytes(
        {"cost": observation.cost, "objective_value": observation.objective_value}
    )
    if encoded != expected:
        raise CommandOutputError("malformed_json", stream="stdout", observed_bytes=len(encoded))
    return observation


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("Non-finite JSON numbers are forbidden.")
    return parsed
