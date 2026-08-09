from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast

import pytest

from research_decision_engine.command_adapter import CommandInvocation


def _invocation(tmp_path: Path, **changes: object) -> CommandInvocation:
    values: dict[str, object] = {
        "argv": ("python", "worker.py", "candidate-a"),
        "cwd": tmp_path,
        "environment_overrides": {"RDE_MODE": "test"},
        "inherit_environment": True,
        "timeout_seconds": 2.5,
        "max_stdout_bytes": 1024,
        "max_stderr_bytes": 2048,
    }
    values.update(changes)
    return CommandInvocation(**cast(Any, values))


def test_command_invocation_is_immutable_normalized_and_mapping_isolated(tmp_path: Path) -> None:
    environment = {"SECOND": "2", "FIRST": "1"}
    invocation = _invocation(tmp_path, environment_overrides=environment)
    environment["FIRST"] = "changed"

    assert invocation.argv == ("python", "worker.py", "candidate-a")
    assert invocation.cwd == tmp_path.resolve()
    assert dict(invocation.environment_overrides) == {"FIRST": "1", "SECOND": "2"}
    assert invocation.timeout_seconds == 2.5
    assert "FIRST" not in repr(invocation)
    with pytest.raises(TypeError):
        cast(Any, invocation.environment_overrides)["THIRD"] = "3"
    with pytest.raises(FrozenInstanceError):
        cast(Any, invocation).timeout_seconds = 3.0


def test_command_invocation_equality_uses_only_semantic_fields(tmp_path: Path) -> None:
    left = _invocation(tmp_path, environment_overrides={"A": "1", "B": "2"})
    right = _invocation(tmp_path, environment_overrides={"B": "2", "A": "1"})

    assert left == right
    assert hash(left) == hash(right)


@pytest.mark.parametrize(
    ("argv", "error_type"),
    [
        ((), ValueError),
        (("",), ValueError),
        (("python", "bad\0argument"), ValueError),
        (("python", 1), TypeError),
        (["python"], ValueError),
    ],
)
def test_command_invocation_rejects_invalid_argv(
    tmp_path: Path, argv: object, error_type: type[Exception]
) -> None:
    with pytest.raises(error_type):
        _invocation(tmp_path, argv=argv)


def test_command_invocation_rejects_invalid_cwd(tmp_path: Path) -> None:
    ordinary_file = tmp_path / "file.txt"
    ordinary_file.write_text("not a directory", encoding="utf-8")

    for value in (tmp_path / "missing", ordinary_file):
        with pytest.raises(ValueError, match="existing directory"):
            _invocation(tmp_path, cwd=value)
    with pytest.raises(TypeError, match="pathlib.Path"):
        _invocation(tmp_path, cwd=str(tmp_path))


@pytest.mark.parametrize(
    "environment",
    [
        {1: "value"},
        {"KEY": 1},
        {"BAD\0KEY": "value"},
        {"KEY": "bad\0value"},
        [("KEY", "value")],
    ],
)
def test_command_invocation_rejects_invalid_environment(
    tmp_path: Path, environment: object
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _invocation(tmp_path, environment_overrides=environment)


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("inf"), float("nan")])
def test_command_invocation_rejects_nonpositive_or_nonfinite_timeout(
    tmp_path: Path, timeout: float
) -> None:
    with pytest.raises(ValueError, match="finite and strictly positive"):
        _invocation(tmp_path, timeout_seconds=timeout)


@pytest.mark.parametrize("timeout", [True, "1", None])
def test_command_invocation_rejects_nonreal_timeout(tmp_path: Path, timeout: object) -> None:
    with pytest.raises(TypeError, match="real number"):
        _invocation(tmp_path, timeout_seconds=timeout)


@pytest.mark.parametrize("field_name", ["max_stdout_bytes", "max_stderr_bytes"])
@pytest.mark.parametrize("value", [0, -1])
def test_command_invocation_rejects_nonpositive_output_limits(
    tmp_path: Path, field_name: str, value: int
) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        _invocation(tmp_path, **{field_name: value})


@pytest.mark.parametrize("field_name", ["max_stdout_bytes", "max_stderr_bytes"])
@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_command_invocation_rejects_noninteger_output_limits(
    tmp_path: Path, field_name: str, value: object
) -> None:
    with pytest.raises(TypeError, match="must be an integer"):
        _invocation(tmp_path, **{field_name: value})


def test_command_invocation_requires_exact_boolean_inheritance(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="exact boolean"):
        _invocation(tmp_path, inherit_environment=1)
