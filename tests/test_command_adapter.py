from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast

import pytest

import research_decision_engine.command_adapter as command_module
from research_decision_engine import CandidateSpec, NormalizedObservation, WorkloadAdapter
from research_decision_engine.command_adapter import (
    CommandAdapter,
    CommandAdapterError,
    CommandBuildError,
    CommandExitError,
    CommandInvocation,
    CommandOutputError,
    CommandTimeoutError,
)

_OBSERVATION = b'{"cost":0.25,"objective_value":3.5}\n'
_COMMAND_INTERNALS = cast(Any, command_module)


def _invocation(
    tmp_path: Path,
    *,
    argv: tuple[str, ...] | None = None,
    environment_overrides: dict[str, str] | None = None,
    inherit_environment: bool = True,
    timeout_seconds: float = 2.0,
    max_stdout_bytes: int = 1024,
    max_stderr_bytes: int = 1024,
) -> CommandInvocation:
    return CommandInvocation(
        argv=argv or (sys.executable, "-c", "raise AssertionError('unused')"),
        cwd=tmp_path,
        environment_overrides=environment_overrides or {},
        inherit_environment=inherit_environment,
        timeout_seconds=timeout_seconds,
        max_stdout_bytes=max_stdout_bytes,
        max_stderr_bytes=max_stderr_bytes,
    )


def _adapter(invocation: CommandInvocation) -> CommandAdapter:
    return CommandAdapter(
        lambda candidate: invocation, adapter_id="local-command", adapter_version="1"
    )


def _patch_process(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stdout_payload: bytes = _OBSERVATION,
    stderr_payload: bytes = b"",
    return_code: int = 0,
) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    class FakeProcess:
        def wait(self, timeout: float | None = None) -> int:
            return return_code

        def poll(self) -> int:
            return return_code

    def fake_popen(argv: tuple[str, ...], **kwargs: object) -> FakeProcess:
        calls.append({"argv": argv, **kwargs})
        stdout = cast(Any, kwargs["stdout"])
        stderr = cast(Any, kwargs["stderr"])
        stdout.write(stdout_payload)
        stdout.flush()
        stderr.write(stderr_payload)
        stderr.flush()
        return FakeProcess()

    monkeypatch.setattr(_COMMAND_INTERNALS.subprocess, "Popen", fake_popen)
    return calls


def test_command_adapter_has_stable_identity_and_calls_builder_once_with_truth_free_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process_calls = _patch_process(monkeypatch)
    builder_calls: list[CandidateSpec] = []

    def sensitive_builder(candidate: CandidateSpec) -> CommandInvocation:
        builder_calls.append(candidate)
        assert type(candidate) is CandidateSpec
        assert dict(candidate.parameters) == {"x": 3.5}
        assert not hasattr(candidate, "true_value")
        return _invocation(tmp_path)

    adapter = CommandAdapter(
        sensitive_builder, adapter_id="local-command", adapter_version="2026-08-04"
    )
    structural_adapter: WorkloadAdapter = adapter
    candidate = CandidateSpec("candidate-a", {"x": 3.5})

    assert structural_adapter.evaluate(candidate) == NormalizedObservation(3.5, 0.25)
    assert structural_adapter.adapter_id == "local-command"
    assert structural_adapter.adapter_version == "2026-08-04"
    assert builder_calls == [candidate]
    assert len(process_calls) == 1
    assert "sensitive_builder" not in repr(adapter)
    with pytest.raises(FrozenInstanceError):
        cast(Any, adapter).adapter_id = "changed"


def test_command_adapter_starts_one_direct_child_without_shell_and_composes_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RDE_INHERITED_SENTINEL", "inherited")
    process_calls = _patch_process(monkeypatch, stderr_payload=b"diagnostic")
    invocation = _invocation(
        tmp_path,
        argv=("program", "; echo not-a-shell | &", "argument with spaces"),
        environment_overrides={"RDE_OVERRIDE": "explicit"},
    )

    assert _adapter(invocation).evaluate(CandidateSpec("candidate-a", {})) == (
        NormalizedObservation(3.5, 0.25)
    )
    call = process_calls[0]
    assert call["argv"] == invocation.argv
    assert call["shell"] is False
    assert call["stdin"] == subprocess.DEVNULL
    assert call["cwd"] == tmp_path.resolve()
    assert call["close_fds"] is True
    environment = cast(dict[str, str], call["env"])
    assert environment["RDE_INHERITED_SENTINEL"] == "inherited"
    assert environment["RDE_OVERRIDE"] == "explicit"


def test_command_adapter_can_use_an_explicit_noninherited_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RDE_MUST_NOT_INHERIT", "secret")
    process_calls = _patch_process(monkeypatch)
    invocation = _invocation(
        tmp_path,
        environment_overrides={"ONLY_VALUE": "present"},
        inherit_environment=False,
    )

    _adapter(invocation).evaluate(CandidateSpec("candidate-a", {}))
    assert process_calls[0]["env"] == {"ONLY_VALUE": "present"}


def test_environment_overrides_follow_platform_key_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inherited_key = "RDE_CASE_SENSITIVE_SENTINEL"
    override_key = inherited_key.lower()
    monkeypatch.setenv(inherited_key, "inherited")
    process_calls = _patch_process(monkeypatch)
    invocation = _invocation(
        tmp_path,
        environment_overrides={override_key: "explicit"},
    )

    _adapter(invocation).evaluate(CandidateSpec("candidate-a", {}))
    environment = cast(dict[str, str], process_calls[0]["env"])
    matches = {key: value for key, value in environment.items() if key.casefold() == override_key}
    if os.name == "nt":
        assert matches == {override_key: "explicit"}
    else:
        assert matches == {inherited_key: "inherited", override_key: "explicit"}


def test_command_adapter_executes_metacharacters_as_argv_data_in_explicit_cwd(
    tmp_path: Path,
) -> None:
    metacharacters = "; echo forged-output | & $(ignored)"
    program = (
        "import os,sys;"
        "ok=(sys.argv[1]==sys.argv[2] and os.getcwd()==sys.argv[3] "
        "and os.environ['RDE_CHILD_VALUE']=='expected');"
        "sys.stderr.write('diagnostic\\n');"
        "sys.stdout.buffer.write("
        'b\'{"cost":0.25,"objective_value":3.5}\\n\' if ok else '
        'b\'{"cost":0.0,"objective_value":0.0}\\n\')'
    )
    invocation = _invocation(
        tmp_path,
        argv=(
            sys.executable,
            "-c",
            program,
            metacharacters,
            metacharacters,
            str(tmp_path.resolve()),
        ),
        environment_overrides={"RDE_CHILD_VALUE": "expected"},
    )

    assert _adapter(invocation).evaluate(CandidateSpec("candidate-a", {})) == (
        NormalizedObservation(3.5, 0.25)
    )


def test_command_adapter_wraps_builder_exception_and_preserves_cause(tmp_path: Path) -> None:
    failure = ValueError("user builder failure")

    def builder(candidate: CandidateSpec) -> CommandInvocation:
        raise failure

    adapter = CommandAdapter(builder, adapter_id="local-command", adapter_version="1")
    with pytest.raises(CommandBuildError) as raised:
        adapter.evaluate(CandidateSpec("candidate-a", {}))
    assert raised.value.__cause__ is failure


@pytest.mark.parametrize("failure_type", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_command_adapter_does_not_swallow_builder_base_exceptions(
    failure_type: type[BaseException],
) -> None:
    def builder(candidate: CandidateSpec) -> CommandInvocation:
        raise failure_type()

    adapter = CommandAdapter(builder, adapter_id="local-command", adapter_version="1")
    with pytest.raises(failure_type):
        adapter.evaluate(CandidateSpec("candidate-a", {}))


def test_command_adapter_rejects_candidate_subclass_before_builder(tmp_path: Path) -> None:
    class CandidateSubclass(CandidateSpec):
        pass

    calls = 0

    def builder(candidate: CandidateSpec) -> CommandInvocation:
        nonlocal calls
        calls += 1
        return _invocation(tmp_path)

    adapter = CommandAdapter(builder, adapter_id="local-command", adapter_version="1")
    with pytest.raises(TypeError, match="exact CandidateSpec"):
        adapter.evaluate(CandidateSubclass("candidate-a", {}))
    assert calls == 0


def test_command_adapter_rejects_wrong_or_tampered_builder_result(tmp_path: Path) -> None:
    wrong = CommandAdapter(
        cast(Any, lambda candidate: {"argv": ["program"]}),
        adapter_id="local-command",
        adapter_version="1",
    )
    with pytest.raises(CommandBuildError) as wrong_result:
        wrong.evaluate(CandidateSpec("candidate-a", {}))
    assert isinstance(wrong_result.value.__cause__, TypeError)

    invocation = _invocation(tmp_path)
    object.__setattr__(invocation, "timeout_seconds", 0.0)
    with pytest.raises(CommandBuildError) as tampered:
        _adapter(invocation).evaluate(CandidateSpec("candidate-a", {}))
    assert isinstance(tampered.value.__cause__, ValueError)


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (b"\xff\n", "encoding_violation"),
        (b"\xef\xbb\xbf" + _OBSERVATION, "encoding_violation"),
        (_OBSERVATION.replace(b"\n", b"\r\n"), "malformed_json"),
        (_OBSERVATION.rstrip(b"\n"), "malformed_json"),
        (_OBSERVATION + b"\n", "malformed_json"),
        (b"prefix" + _OBSERVATION, "malformed_json"),
        (b'{"cost":0.25,"cost":0.5,"objective_value":3.5}\n', "malformed_json"),
        (b'{"cost":0.25,"objective_value":NaN}\n', "malformed_json"),
        (b'{"cost":0.25,"objective_value":Infinity}\n', "malformed_json"),
        (b'{"cost":0.25,"objective_value":-Infinity}\n', "malformed_json"),
        (b'{"cost":0.25,"objective_value":1e999}\n', "malformed_json"),
        (
            b'{"cost":0,"objective_value":' + b"9" * 400 + b"}\n",
            "invalid_normalized_observation",
        ),
        (b'{"cost":0.25,"objective_value":3.5,"unknown":1}\n', "invalid_normalized_observation"),
        (
            b'{"cost":0.25,"objective_value":3.5,"true_value":9.0}\n',
            "invalid_normalized_observation",
        ),
        (b'{"cost":-1.0,"objective_value":3.5}\n', "invalid_normalized_observation"),
        (b'{"objective_value":3.5, "cost":0.25}\n', "malformed_json"),
    ],
)
def test_command_adapter_strictly_rejects_invalid_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    reason: str,
) -> None:
    _patch_process(monkeypatch, stdout_payload=payload)
    with pytest.raises(CommandOutputError) as raised:
        _adapter(_invocation(tmp_path)).evaluate(CandidateSpec("candidate-a", {}))
    assert raised.value.reason == reason
    assert raised.value.stream == "stdout"


@pytest.mark.parametrize(
    ("stdout_payload", "stderr_payload", "reason", "stream"),
    [
        (_OBSERVATION + b"x", b"", "oversized_stdout", "stdout"),
        (_OBSERVATION, b"xx", "oversized_stderr", "stderr"),
    ],
)
def test_command_adapter_enforces_file_backed_output_limits_before_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stdout_payload: bytes,
    stderr_payload: bytes,
    reason: str,
    stream: str,
) -> None:
    _patch_process(monkeypatch, stdout_payload=stdout_payload, stderr_payload=stderr_payload)
    invocation = _invocation(
        tmp_path,
        max_stdout_bytes=len(_OBSERVATION),
        max_stderr_bytes=1,
    )
    with pytest.raises(CommandOutputError) as raised:
        _adapter(invocation).evaluate(CandidateSpec("candidate-a", {}))
    assert (raised.value.reason, raised.value.stream) == (reason, stream)


def test_command_exit_error_is_bounded_and_does_not_dump_secret_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = b"SUPER_SECRET_VALUE"
    stderr = secret + b"x" * 5000
    process_calls = _patch_process(monkeypatch, stderr_payload=stderr, return_code=7)
    invocation = _invocation(tmp_path, max_stderr_bytes=len(stderr))

    with pytest.raises(CommandExitError) as raised:
        _adapter(invocation).evaluate(CandidateSpec("candidate-a", {}))
    error = raised.value
    assert error.return_code == 7
    assert len(error.stderr_excerpt) == 4096
    assert error.stderr_excerpt_truncated is True
    assert secret in error.stderr_excerpt
    assert secret.decode() not in str(error)
    assert secret.decode() not in repr(error)
    assert len(process_calls) == 1


def test_command_timeout_terminates_kills_and_reaps_direct_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[object] = []

    class TimeoutProcess:
        wait_count = 0

        def wait(self, timeout: float | None = None) -> int:
            self.wait_count += 1
            events.append(("wait", timeout))
            if self.wait_count < 3:
                assert timeout is not None
                raise subprocess.TimeoutExpired(("program",), timeout)
            return -9

        def poll(self) -> int | None:
            events.append("poll")
            return None

        def terminate(self) -> None:
            events.append("terminate")

        def kill(self) -> None:
            events.append("kill")

    def fake_popen(*args: object, **kwargs: object) -> TimeoutProcess:
        return TimeoutProcess()

    monkeypatch.setattr(_COMMAND_INTERNALS.subprocess, "Popen", fake_popen)
    invocation = _invocation(tmp_path, timeout_seconds=0.125)

    with pytest.raises(CommandTimeoutError) as raised:
        _adapter(invocation).evaluate(CandidateSpec("candidate-a", {}))
    error = raised.value
    assert error.timed_out is True
    assert error.timeout_seconds == 0.125
    assert error.direct_child_reaped is True
    assert error.descendant_process_tree_cleanup_guaranteed is False
    assert "process-tree cleanup is not guaranteed" in str(error)
    assert events == [
        ("wait", 0.125),
        "poll",
        "terminate",
        ("wait", 1.0),
        "poll",
        "kill",
        ("wait", 1.0),
    ]


def test_timeout_cleanup_never_uses_an_unbounded_wait_and_reports_unreaped_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[object] = []

    class ResistantProcess:
        def wait(self, timeout: float | None = None) -> int:
            events.append(("wait", timeout))
            if len([event for event in events if isinstance(event, tuple)]) == 2:
                raise OSError("grace wait failed")
            assert timeout is not None
            raise subprocess.TimeoutExpired(("program",), timeout)

        def poll(self) -> None:
            events.append("poll")
            return None

        def terminate(self) -> None:
            events.append("terminate")
            raise OSError("terminate failed")

        def kill(self) -> None:
            events.append("kill")
            raise OSError("kill failed")

    monkeypatch.setattr(
        _COMMAND_INTERNALS.subprocess, "Popen", lambda *args, **kwargs: ResistantProcess()
    )
    invocation = _invocation(tmp_path, timeout_seconds=0.125)

    with pytest.raises(CommandTimeoutError) as raised:
        _adapter(invocation).evaluate(CandidateSpec("candidate-a", {}))

    assert raised.value.direct_child_reaped is False
    waits = [event for event in events if isinstance(event, tuple)]
    assert waits == [("wait", 0.125), ("wait", 1.0), ("wait", 1.0)]
    assert all(timeout is not None for _, timeout in waits)
    assert events.count("kill") >= 1


def test_command_adapter_never_retries_after_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process_calls = _patch_process(monkeypatch, return_code=2)
    builder_calls = 0

    def builder(candidate: CandidateSpec) -> CommandInvocation:
        nonlocal builder_calls
        builder_calls += 1
        return _invocation(tmp_path)

    adapter = CommandAdapter(builder, adapter_id="local-command", adapter_version="1")
    with pytest.raises(CommandExitError):
        adapter.evaluate(CandidateSpec("candidate-a", {}))
    assert builder_calls == 1
    assert len(process_calls) == 1


def test_real_timeout_reaps_the_direct_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_popen = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []

    def capturing_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(_COMMAND_INTERNALS.subprocess, "Popen", capturing_popen)
    invocation = _invocation(
        tmp_path,
        argv=(sys.executable, "-c", "import time; time.sleep(60)"),
        timeout_seconds=0.05,
    )

    with pytest.raises(CommandTimeoutError) as raised:
        _adapter(invocation).evaluate(CandidateSpec("candidate-a", {}))

    assert raised.value.direct_child_reaped is True
    assert len(processes) == 1
    assert processes[0].poll() is not None


def test_temporary_output_files_are_removed_after_success_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_temporary_directory = _COMMAND_INTERNALS.tempfile.TemporaryDirectory
    created: list[Path] = []

    def tracked_temporary_directory(*args: Any, **kwargs: Any) -> Any:
        kwargs["dir"] = tmp_path
        temporary = real_temporary_directory(*args, **kwargs)
        created.append(Path(temporary.name))
        return temporary

    monkeypatch.setattr(
        _COMMAND_INTERNALS.tempfile,
        "TemporaryDirectory",
        tracked_temporary_directory,
    )
    invocation = _invocation(tmp_path)
    _patch_process(monkeypatch)
    _adapter(invocation).evaluate(CandidateSpec("candidate-a", {}))
    assert len(created) == 1 and not created[-1].exists()

    _patch_process(monkeypatch, stdout_payload=b"not-json\n")
    with pytest.raises(CommandOutputError):
        _adapter(invocation).evaluate(CandidateSpec("candidate-a", {}))
    assert len(created) == 2 and all(not path.exists() for path in created)


def test_temporary_output_parent_inside_repository_fails_before_process_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process_calls = _patch_process(monkeypatch)
    repository_root = Path(command_module.__file__).resolve().parent.parent
    monkeypatch.setattr(_COMMAND_INTERNALS.tempfile, "gettempdir", lambda: str(repository_root))

    with pytest.raises(CommandAdapterError, match="outside the repository"):
        _adapter(_invocation(tmp_path)).evaluate(CandidateSpec("candidate-a", {}))

    assert process_calls == []


def test_temporary_cleanup_failure_does_not_replace_typed_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_root = tmp_path / "owned-output"
    cleanup_calls = 0

    class FailingCleanupDirectory:
        def __init__(self, *args: object, **kwargs: object) -> None:
            output_root.mkdir()
            self.name = str(output_root)

        def cleanup(self) -> None:
            nonlocal cleanup_calls
            cleanup_calls += 1
            raise OSError("simulated cleanup failure")

    class NeverExitsProcess:
        def wait(self, timeout: float | None = None) -> int:
            assert timeout is not None
            raise subprocess.TimeoutExpired(("program",), timeout)

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            return None

        def kill(self) -> None:
            return None

    monkeypatch.setattr(_COMMAND_INTERNALS.tempfile, "TemporaryDirectory", FailingCleanupDirectory)
    monkeypatch.setattr(
        _COMMAND_INTERNALS.subprocess, "Popen", lambda *args, **kwargs: NeverExitsProcess()
    )

    with pytest.raises(CommandTimeoutError) as raised:
        _adapter(_invocation(tmp_path, timeout_seconds=0.125)).evaluate(
            CandidateSpec("candidate-a", {})
        )

    assert raised.value.timed_out is True
    assert raised.value.direct_child_reaped is False
    assert cleanup_calls == 1


def test_inherited_environment_secret_is_not_dumped_when_process_start_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "RDE_SUPER_SECRET_ENVIRONMENT_VALUE"
    monkeypatch.setenv("RDE_SECRET", secret)

    def failing_popen(*args: object, **kwargs: object) -> object:
        environment = cast(dict[str, str], kwargs["env"])
        assert environment["RDE_SECRET"] == secret
        raise OSError("ordinary launch failure")

    monkeypatch.setattr(_COMMAND_INTERNALS.subprocess, "Popen", failing_popen)
    with pytest.raises(CommandAdapterError) as raised:
        _adapter(_invocation(tmp_path)).evaluate(CandidateSpec("candidate-a", {}))

    assert secret not in str(raised.value)
    assert secret not in repr(raised.value)
