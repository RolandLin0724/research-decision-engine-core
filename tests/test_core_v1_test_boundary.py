from __future__ import annotations

import hashlib
import subprocess
import sys
import tomllib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CORE_MANIFEST = REPOSITORY_ROOT / "tests" / "core_v1_pytest.txt"
EXPERIMENTAL_MANIFEST = REPOSITORY_ROOT / "tests" / "experimental_pytest.txt"
OPENING_NODEIDS = REPOSITORY_ROOT / "tests" / "core_v1_opening_nodeids.txt"
OPENING_NODEIDS_SHA256 = "e1b6e72e65a1cd4fbab76dc471a52b38ddd9e5653e239ebf4e4b382906961190"
RUNBUNDLE_OPENING_NODEIDS = REPOSITORY_ROOT / "tests" / "core_v1_runbundle_opening_nodeids.txt"
RUNBUNDLE_OPENING_NODEIDS_SHA256 = (
    "11e0d740305e564cd89b5501b6d1a8ddd02720f71d7730def7003faaf4138385"
)


def _manifest_entries(path: Path) -> tuple[str, ...]:
    raw = path.read_bytes()
    assert raw.endswith(b"\n")
    assert not raw.endswith(b"\n\n")
    entries = tuple(raw.decode("utf-8").splitlines())
    assert entries == tuple(sorted(entries))
    assert len(entries) == len(set(entries))
    assert all(entry and not set(entry).intersection("*?[]") for entry in entries)
    assert all((REPOSITORY_ROOT / entry).is_file() for entry in entries)
    return entries


def test_core_v1_pytest_boundary_is_explicit_and_complete() -> None:
    core_entries = _manifest_entries(CORE_MANIFEST)
    experimental_entries = _manifest_entries(EXPERIMENTAL_MANIFEST)
    discovered_entries = tuple(
        sorted(
            path.relative_to(REPOSITORY_ROOT).as_posix()
            for path in (REPOSITORY_ROOT / "tests").glob("test_*.py")
        )
    )

    assert set(core_entries).isdisjoint(experimental_entries)
    assert tuple(sorted((*core_entries, *experimental_entries))) == discovered_entries
    assert "tests/test_core_v1_test_boundary.py" in core_entries
    assert {
        "tests/test_closed_loop.py",
        "tests/test_closed_loop_cli_e2e.py",
        "tests/test_closed_loop_evaluation.py",
    }.issubset(experimental_entries)

    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text("utf-8"))
    pytest_options = pyproject["tool"]["pytest"]["ini_options"]
    assert pytest_options["addopts"] == [
        "--noconftest",
        "-p",
        "no:cacheprovider",
        "@tests/core_v1_pytest.txt",
    ]

    opening_bytes = OPENING_NODEIDS.read_bytes()
    opening_nodeids = tuple(opening_bytes.decode("utf-8").splitlines())
    assert len(opening_nodeids) == 83
    assert opening_bytes.endswith(b"\n")
    assert hashlib.sha256(opening_bytes).hexdigest() == OPENING_NODEIDS_SHA256

    runbundle_opening_bytes = RUNBUNDLE_OPENING_NODEIDS.read_bytes()
    runbundle_opening_nodeids = tuple(runbundle_opening_bytes.decode("utf-8").splitlines())
    assert len(runbundle_opening_nodeids) == 123
    assert runbundle_opening_bytes.endswith(b"\n")
    assert hashlib.sha256(runbundle_opening_bytes).hexdigest() == RUNBUNDLE_OPENING_NODEIDS_SHA256
    assert set(opening_nodeids).issubset(runbundle_opening_nodeids)

    collection = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            "-o",
            "addopts=",
            "--noconftest",
            "-p",
            "no:cacheprovider",
            "--collect-only",
            "-q",
            *core_entries,
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert collection.returncode == 0, collection.stderr
    current_nodeids = {
        line
        for line in collection.stdout.splitlines()
        if line.startswith("tests/") and "::" in line
    }
    assert set(opening_nodeids).issubset(current_nodeids)
    assert set(runbundle_opening_nodeids).issubset(current_nodeids)
