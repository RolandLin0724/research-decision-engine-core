from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "core-v1.yml"

CHECKOUT_SHA = "de0fac2e4500dabe0009e67214ff5f5447ce83dd"
SETUP_PYTHON_SHA = "a309ff8b426b58ec0e2a45f0f869d46889d02405"


def _workflow_text() -> str:
    raw = WORKFLOW.read_bytes()
    assert raw.endswith(b"\n")
    assert b"\r" not in raw
    return raw.decode("utf-8")


def test_core_v1_workflow_has_exact_triggers_permissions_and_matrix() -> None:
    workflow = _workflow_text()

    assert workflow.startswith("name: RDE Core v1\n\n")
    assert workflow.count("\non:\n") == 1
    assert "\non:\n  push:\n  pull_request:\n\npermissions:\n" in workflow
    assert workflow.count("permissions:") == 1
    assert "\npermissions:\n  contents: read\n\njobs:\n" in workflow
    assert "runs-on: ${{ matrix.os }}" in workflow
    assert "os: [ubuntu-latest, windows-latest]" in workflow
    assert 'python-version: ["3.12"]' in workflow
    assert (
        "matrix:\n"
        "        os: [ubuntu-latest, windows-latest]\n"
        '        python-version: ["3.12"]\n\n'
        "    steps:\n"
    ) in workflow
    assert "python-version: ${{ matrix.python-version }}" in workflow
    assert "macos-" not in workflow
    assert "ubuntu-latest" in workflow
    assert "windows-latest" in workflow
    assert workflow.count("python-version:") == 2


def test_core_v1_workflow_pins_all_actions_to_the_verified_full_shas() -> None:
    workflow = _workflow_text()
    action_references = re.findall(r"(?m)^\s*uses:\s*([^@\s]+)@([^\s]+)\s*$", workflow)

    assert action_references == [
        ("actions/checkout", CHECKOUT_SHA),
        ("actions/setup-python", SETUP_PYTHON_SHA),
    ]
    assert all(re.fullmatch(r"[0-9a-f]{40}", revision) for _, revision in action_references)
    checkout_step = (
        "      - name: Check out source\n"
        f"        uses: actions/checkout@{CHECKOUT_SHA}\n"
        "        with:\n"
        "          persist-credentials: false\n"
        "          fetch-depth: 0\n\n"
        "      - name: Set up Python\n"
    )
    assert workflow.count(checkout_step) == 1
    assert workflow.count("persist-credentials:") == 1
    assert workflow.count("fetch-depth:") == 1
    assert re.search(r"(?i)(?<![a-z0-9_])git(?:\.exe)?(?![a-z0-9_])", workflow) is None


def test_core_v1_workflow_uses_the_exact_locked_toolchain_and_quality_gates() -> None:
    workflow = _workflow_text()

    assert workflow.count("python -m pip install uv==0.11.32") == 1
    assert workflow.count("uv sync --locked") == 1
    assert "uv run ruff format --check ." in workflow
    assert "uv run ruff check ." in workflow
    assert "uv run mypy ." in workflow
    assert "uv run python -m pytest -q -p no:cacheprovider" in workflow
    assert "uv build --sdist --wheel" in workflow


def test_core_v1_workflow_checks_release_fixtures_and_deterministic_collection() -> None:
    workflow = _workflow_text()
    checker = "uv run python -m research_decision_engine.core_release_check"

    assert f"run: {checker}\n" in workflow
    assert (
        f"{checker} --collect-nodeids .core-v1-nodeids-1.txt\n"
        f"          {checker} --collect-nodeids .core-v1-nodeids-2.txt\n"
    ) in workflow
    assert (
        f"{checker} --compare-nodeids .core-v1-nodeids-1.txt "
        ".core-v1-nodeids-2.txt "
        "research_decision_engine/core-fixtures-v1/core-test-nodeids.txt"
    ) in workflow


def test_core_v1_workflow_runs_compatibility_smokes_and_full_sqlite_fault_tests() -> None:
    workflow = _workflow_text()

    for test_path in (
        "tests/test_sqlite_migration_atomicity.py",
        "tests/test_run_bundle_replay.py",
        "tests/test_run_bundle_v2_replay.py",
        "tests/test_run_bundle_v3_replay.py",
        "tests/test_python_function_adapter.py",
        "tests/test_command_adapter_compression_example.py",
        "tests/test_command_adapter_compression_v2_example.py",
        "tests/test_command_adapter_compression_v3_example.py",
    ):
        assert test_path in workflow

    assert "complete SQLite v1-to-v6 fault and retry matrix" in workflow
    assert "RunBundle replay without workload execution" in workflow
    assert "PythonFunctionAdapter example" in workflow
    assert "CommandAdapter CPU examples and all three v3 policies" in workflow


def test_core_v1_workflow_checks_only_the_built_wheel_in_an_isolated_environment() -> None:
    workflow = _workflow_text()
    isolated_wheel_prefix = 'uv run --isolated --no-project --with "${{ env.RDE_CORE_WHEEL }}" -- '

    assert workflow.count("shell: python") == 1
    assert workflow.count('glob("research_decision_engine-*.whl")') == 1
    assert "if len(wheels) != 1:" in workflow
    assert 'expected_filename = f"research_decision_engine-{version}-py3-none-any.whl"' in workflow
    assert "if wheel.name != expected_filename:" in workflow
    assert 'name.endswith(".dist-info/METADATA")' in workflow
    assert "if len(metadata_members) != 1:" in workflow
    assert 'metadata.get("Name") != project_name' in workflow
    assert 'metadata.get("Version") != version' in workflow
    assert 'Path(os.environ["GITHUB_ENV"])' in workflow
    assert 'github_env.write(f"RDE_CORE_WHEEL={wheel.resolve()}\\n")' in workflow
    assert (
        re.search(
            r"research_decision_engine-(?!\*)(?!\{)[^\s\"']+-py3-none-any\.whl",
            workflow,
        )
        is None
    )
    assert workflow.count("working-directory: ${{ runner.temp }}") == 2
    assert workflow.count('"${{ env.RDE_CORE_WHEEL }}"') == 2
    assert (
        isolated_wheel_prefix + "python -m research_decision_engine.core_release_check --installed"
    ) in workflow
    assert isolated_wheel_prefix + "rde --help" in workflow


def test_core_v1_workflow_has_no_privileged_or_out_of_scope_configuration() -> None:
    workflow = _workflow_text()
    lowered = workflow.casefold()

    assert "secrets" not in lowered
    assert "permissions: write" not in lowered
    assert not re.search(r"(?m)^\s+[a-z-]+:\s*write\s*$", lowered)
    for forbidden in (
        "assurance",
        "package-l",
        "package-p",
        "candidate restoration",
        "broader",
        "recovery root",
        "stage-2f",
        "p4",
    ):
        assert forbidden not in lowered
