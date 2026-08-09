from __future__ import annotations

import copy
import hashlib
import inspect
import pickle
import re
import sys
import threading
import time
import xml.etree.ElementTree as ElementTree
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from pathlib import Path

import pytest

import research_decision_engine.benchmarks.broader_smoke as smoke_module
import research_decision_engine.benchmarks.broader_validation as validation
from research_decision_engine.benchmarks.broader_protocol import protocol_hash, repository_root
from research_decision_engine.benchmarks.broader_validation import (
    DEFAULT_PYTEST_TIMEOUT_SECONDS,
    MAX_PYTEST_TIMEOUT_SECONDS,
    PytestValidationError,
    PytestValidationObservation,
    PytestValidationOwnerClaim,
    PytestValidationResult,
    _execute_pytest_validation_fixture,
    bind_pytest_validation_result_to_bundle,
    claim_pytest_validation_result_owner,
    consume_pytest_validation_result,
    execute_pytest_validation,
    issued_pytest_validation_junit_bytes,
    observe_pytest_validation_result,
    release_pytest_validation_result_owner,
    validate_pytest_validation_junit_bytes,
    validate_pytest_validation_result,
)


def _identity(label: str) -> str:
    return f"test:{label}:{protocol_hash('pytest_validation_test_identity/v1', label)}"


def _write_tiny_suite(path: Path, *, variant: str) -> None:
    path.write_text(
        "\n".join(
            (
                "import pytest",
                "",
                "def test_actual_pass():",
                f"    assert {variant!r}",
                "",
                "@pytest.mark.parametrize('value', [1, 2])",
                "def test_actual_parameter(value):",
                "    assert value in (1, 2)",
                "",
                "@pytest.mark.skip(reason='first exact fixture reason')",
                "def test_actual_skip_first():",
                "    raise AssertionError('skip did not execute')",
                "",
                "@pytest.mark.skip(reason='second exact fixture reason')",
                "def test_actual_skip_second():",
                "    raise AssertionError('skip did not execute')",
                "",
            )
        ),
        encoding="utf-8",
        newline="\n",
    )


def _write_authoritative_config(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)
    config = root / "pyproject.toml"
    config.write_text(
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
        encoding="utf-8",
        newline="\n",
    )
    return config


def _write_tiny_repository(root: Path, *, filename: str, variant: str) -> Path:
    _write_authoritative_config(root)
    target = root / "tests" / filename
    _write_tiny_suite(target, variant=variant)
    return target


@pytest.fixture(scope="module")
def primary_result(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[PytestValidationResult, Path]:
    root = tmp_path_factory.mktemp("pytest-validation-primary")
    target = _write_tiny_repository(
        root,
        filename="test_tiny_primary.py",
        variant="primary",
    )
    result = _execute_pytest_validation_fixture(
        validation_run_identity=_identity("primary-run"),
        targets=(target,),
        execution_root=root,
    )
    return result, target.resolve(strict=True)


@pytest.fixture(scope="module")
def secondary_result(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[PytestValidationResult, Path]:
    root = tmp_path_factory.mktemp("pytest-validation-secondary")
    target = _write_tiny_repository(
        root,
        filename="test_tiny_secondary.py",
        variant="secondary-with-a-different-name",
    )
    result = _execute_pytest_validation_fixture(
        validation_run_identity=_identity("secondary-run"),
        targets=(target,),
        execution_root=root,
    )
    return result, target.resolve(strict=True)


def test_actual_fixture_execution_issues_exact_observation(
    primary_result: tuple[PytestValidationResult, Path],
) -> None:
    result, target = primary_result
    observation = observe_pytest_validation_result(result)

    assert observation.validation_version == validation.PYTEST_VALIDATION_VERSION
    assert observation.issuer_kind == "fixture"
    assert observation.execution_status == "COMPLETED"
    assert observation.completed is True
    assert observation.exit_code == 0
    assert observation.total == 5
    assert observation.passed == 3
    assert observation.skipped == 2
    assert observation.failed == 0
    assert observation.errors == 0
    assert observation.runtime_seconds is not None
    assert Decimal(observation.runtime_seconds).is_finite()
    assert Decimal(observation.runtime_seconds) >= 0
    root = target.parent.parent
    assert observation.implementation_repository_root == str(repository_root().resolve(strict=True))
    assert observation.pytest_root_directory == str(root)
    assert observation.pytest_working_directory == str(root)
    assert observation.pytest_config_path == str(root / "pyproject.toml")
    assert observation.pytest_test_selection == (str(target),)
    assert observation.command == (
        sys.executable,
        "-P",
        "-m",
        "pytest",
        "-p",
        "research_decision_engine.benchmarks.broader_validation",
        "-c",
        str(root / "pyproject.toml"),
        f"--rootdir={root}",
        f"--confcutdir={root / 'tests'}",
        f"--junitxml={observation.junit_xml_path}",
        str(target),
    )
    assert observation.command_sha256 == protocol_hash(
        "pytest_validation_command/v1", list(observation.command)
    )
    for identity in (
        observation.execution_specification_identity,
        observation.implementation_tree_sha256,
        observation.implementation_diff_sha256,
        observation.broader_source_sha256,
        observation.complete_test_bundle_sha256,
        observation.interpreter_executable_sha256,
        observation.base_interpreter_executable_sha256,
        observation.uv_lock_sha256,
        observation.interpreter_identity_sha256,
        observation.platform_identity_sha256,
        observation.pytest_source_sha256,
        observation.pluggy_source_sha256,
        observation.validation_plugin_source_sha256,
        observation.subprocess_environment_sha256,
        observation.subprocess_start_identity,
        observation.subprocess_completion_identity,
        observation.result_identity,
    ):
        assert identity is not None
        assert re.fullmatch(r"[0-9a-f]{64}", identity)
    assert Path(observation.interpreter_path).is_file()
    assert Path(observation.base_interpreter_path).is_file()
    assert observation.pytest_version
    assert observation.pluggy_version
    assert observation.effective_plugin_identities
    assert observation.effective_conftest_identities == ()
    assert observation.deselected_node_ids == ()
    assert len(observation.collected_node_ids) == observation.total
    assert len(observation.junit_case_identities) == observation.total
    assert len(set(observation.junit_case_identities)) == observation.total
    assert observation.subprocess_environment_sha256 == (
        validation._subprocess_environment_sha256(validation._base_subprocess_environment())
    )


def test_junit_bytes_counts_runtime_and_exact_ordered_skips_are_derived(
    primary_result: tuple[PytestValidationResult, Path],
) -> None:
    result, _ = primary_result
    observation = observe_pytest_validation_result(result)
    first_copy = issued_pytest_validation_junit_bytes(result)
    second_copy = issued_pytest_validation_junit_bytes(result)

    assert first_copy == second_copy
    assert first_copy is not second_copy
    assert len(first_copy) == observation.junit_xml_byte_count
    assert hashlib.sha256(first_copy).hexdigest() == observation.junit_xml_sha256
    validate_pytest_validation_junit_bytes(result, first_copy)
    root = ElementTree.fromstring(first_copy)
    test_cases = tuple(root.iter("testcase"))
    assert len(test_cases) == observation.total
    assert len(tuple(root.iter("skipped"))) == observation.skipped
    assert observation.skipped_node_ids[0].endswith("test_tiny_primary.py::test_actual_skip_first")
    assert observation.skipped_node_ids[1].endswith("test_tiny_primary.py::test_actual_skip_second")
    assert observation.skipped_reasons == (
        "Skipped: first exact fixture reason",
        "Skipped: second exact fixture reason",
    )
    assert observation.collected_node_ids == (
        "tests/test_tiny_primary.py::test_actual_pass",
        "tests/test_tiny_primary.py::test_actual_parameter[1]",
        "tests/test_tiny_primary.py::test_actual_parameter[2]",
        "tests/test_tiny_primary.py::test_actual_skip_first",
        "tests/test_tiny_primary.py::test_actual_skip_second",
    )
    assert observation.skipped_node_ids == observation.collected_node_ids[-2:]
    suite = root if root.tag == "testsuite" else next(iter(root))
    assert observation.runtime_seconds == suite.attrib["time"]


def test_result_cannot_be_constructed_subclassed_copied_pickled_or_mutated(
    primary_result: tuple[PytestValidationResult, Path],
) -> None:
    result, _ = primary_result
    observation = observe_pytest_validation_result(result)

    with pytest.raises(TypeError, match="issued only by actual execution"):
        PytestValidationResult()
    with pytest.raises(TypeError, match="cannot be subclassed"):

        class ForgedResult(PytestValidationResult):
            pass

    with pytest.raises(TypeError, match="cannot be copied"):
        copy.copy(result)
    with pytest.raises(TypeError, match="cannot be deep-copied"):
        copy.deepcopy(result)
    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(result)
    with pytest.raises(AttributeError):
        result.status = "PASS"  # type: ignore[attr-defined]
    with pytest.raises(FrozenInstanceError):
        observation.total = 999  # type: ignore[misc]


def test_manual_lookalikes_and_caller_claims_are_rejected() -> None:
    fake_result = object()
    constructor = inspect.signature(PytestValidationObservation)

    assert "passed" in constructor.parameters
    assert "total" in constructor.parameters
    with pytest.raises(PytestValidationError, match="exact issued object"):
        observe_pytest_validation_result(fake_result)  # type: ignore[arg-type]
    with pytest.raises(PytestValidationError, match="exact issued object"):
        validate_pytest_validation_result(
            fake_result,  # type: ignore[arg-type]
            validation_run_identity=_identity("lookalike-run"),
        )
    public_parameters = inspect.signature(execute_pytest_validation).parameters
    assert tuple(public_parameters) == ("validation_run_identity", "timeout_seconds")
    assert "targets" not in public_parameters
    assert "passed" not in public_parameters
    assert "total" not in public_parameters
    assert "status" not in public_parameters


def test_full_subprocess_environment_identity_is_deterministic_and_private() -> None:
    first = validation._subprocess_environment_sha256(
        {"ORDINARY": "same", "SENSITIVE_TOKEN": "first-secret"}
    )
    repeated = validation._subprocess_environment_sha256(
        {"SENSITIVE_TOKEN": "first-secret", "ORDINARY": "same"}
    )
    changed = validation._subprocess_environment_sha256(
        {"ORDINARY": "same", "SENSITIVE_TOKEN": "second-secret"}
    )

    assert first == repeated
    assert first != changed
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert "secret" not in first
    with pytest.raises(PytestValidationError, match="nonce-bearing"):
        validation._subprocess_environment_sha256({"RDE_BROADER_PYTEST_VALIDATION_FORGED": "value"})


def test_process_topology_accepts_direct_and_windows_launcher_children() -> None:
    validation._validate_process_topology(
        expected_pid=200,
        receipt_pid=200,
        receipt_parent_pid=100,
        issuer_pid=100,
    )
    validation._validate_process_topology(
        expected_pid=200,
        receipt_pid=300,
        receipt_parent_pid=200,
        issuer_pid=100,
    )


@pytest.mark.parametrize(
    ("expected_pid", "receipt_pid", "receipt_parent_pid", "issuer_pid"),
    (
        (200, 300, 400, 100),
        (200, 200, 400, 100),
        (200, 200, 200, 100),
        (None, 300, 200, 100),
        (0, 300, 200, 100),
        (200, 0, 200, 100),
        (200, 300, 0, 100),
    ),
)
def test_process_topology_rejects_unrelated_or_invalid_pids(
    expected_pid: int | None,
    receipt_pid: int,
    receipt_parent_pid: int,
    issuer_pid: int,
) -> None:
    with pytest.raises(PytestValidationError, match="process chain differs"):
        validation._validate_process_topology(
            expected_pid=expected_pid,
            receipt_pid=receipt_pid,
            receipt_parent_pid=receipt_parent_pid,
            issuer_pid=issuer_pid,
        )


def test_launcher_exit_waits_for_authoritative_child_and_verifies_kill() -> None:
    class ExitedLauncher:
        pid = 200

        @staticmethod
        def poll() -> int:
            return 0

    launcher = ExitedLauncher()
    clock_value = [0.0]
    pauses: list[float] = []
    child_states = iter((True, True, False))

    def pause(delay: float) -> None:
        pauses.append(delay)
        clock_value[0] += delay

    assert validation._wait_for_authoritative_process_end(
        launcher,
        observed_plugin_pid=300,
        deadline=1.0,
        clock=lambda: clock_value[0],
        pause=pause,
        is_alive=lambda pid: next(child_states),
    )
    assert pauses

    clock_value[0] = 0.0
    with pytest.raises(PytestValidationError, match="remained alive after bounded cleanup"):
        validation._require_process_tree_terminated(
            launcher,
            observed_plugin_pid=300,
            deadline=0.02,
            failure_details="simulated kill did not stop child",
            clock=lambda: clock_value[0],
            pause=pause,
            is_alive=lambda pid: True,
        )

    validation._reconcile_process_exit_codes(
        launcher_exit_code=0,
        plugin_exit_code=0,
        receipt_exit_code=0,
    )
    for launcher_code, plugin_code, receipt_code in ((0, 1, 1), (0, 0, 1), (None, 0, 0)):
        with pytest.raises(PytestValidationError, match="exit codes differ"):
            validation._reconcile_process_exit_codes(
                launcher_exit_code=launcher_code,
                plugin_exit_code=plugin_code,
                receipt_exit_code=receipt_code,
            )


def test_fixture_result_is_never_accepted_as_production_evidence(
    primary_result: tuple[PytestValidationResult, Path],
) -> None:
    result, _ = primary_result

    with pytest.raises(PytestValidationError, match="not production evidence"):
        validate_pytest_validation_result(
            result,
            validation_run_identity=_identity("primary-run"),
        )


def test_swapped_and_tampered_junit_bytes_are_rejected(
    primary_result: tuple[PytestValidationResult, Path],
    secondary_result: tuple[PytestValidationResult, Path],
) -> None:
    primary, _ = primary_result
    secondary, _ = secondary_result
    primary_bytes = issued_pytest_validation_junit_bytes(primary)
    secondary_bytes = issued_pytest_validation_junit_bytes(secondary)

    assert primary_bytes != secondary_bytes
    with pytest.raises(PytestValidationError, match="differ from the issued"):
        validate_pytest_validation_junit_bytes(primary, secondary_bytes)
    with pytest.raises(PytestValidationError, match="differ from the issued"):
        validate_pytest_validation_junit_bytes(primary, primary_bytes + b"\n")


def test_smoke_bundle_identity_binds_the_exact_junit_and_validation_run(
    secondary_result: tuple[PytestValidationResult, Path],
) -> None:
    result, _ = secondary_result
    observation = observe_pytest_validation_result(result)
    bundle_identity = smoke_module._smoke_evidence_bundle_identity(observation)

    bound = bind_pytest_validation_result_to_bundle(
        result,
        validation_run_identity=observation.validation_run_identity,
        evidence_bundle_identity=bundle_identity,
    )

    assert bound is observation
    assert issued_pytest_validation_junit_bytes(
        result,
        evidence_bundle_identity=bundle_identity,
    )
    assert (
        smoke_module._smoke_evidence_bundle_identity(
            replace(observation, junit_xml_sha256="f" * 64)
        )
        != bundle_identity
    )
    assert (
        smoke_module._smoke_evidence_bundle_identity(
            replace(observation, validation_run_identity=_identity("changed-run"))
        )
        != bundle_identity
    )


@pytest.mark.parametrize(
    "identity_field",
    (
        "implementation_commit",
        "design_checkpoint_commit",
        "source_design_sha256",
        "implementation_tree_sha256",
        "implementation_diff_sha256",
        "broader_source_sha256",
        "complete_test_bundle_sha256",
        "uv_lock_sha256",
        "interpreter_identity_sha256",
        "platform_identity_sha256",
    ),
)
def test_cross_run_and_current_identity_changes_are_rejected(
    primary_result: tuple[PytestValidationResult, Path],
    monkeypatch: pytest.MonkeyPatch,
    identity_field: str,
) -> None:
    result, _ = primary_result

    with pytest.raises(PytestValidationError, match="another validation run"):
        bind_pytest_validation_result_to_bundle(
            result,
            validation_run_identity=_identity("wrong-run"),
            evidence_bundle_identity=_identity("wrong-run-bundle"),
        )
    current = validation._current_validation_identities()
    changed = replace(
        current,
        **{identity_field: "0" * (40 if identity_field.endswith("commit") else 64)},
    )
    monkeypatch.setattr(validation, "_current_validation_identities", lambda: changed)
    with pytest.raises(PytestValidationError, match="source identity is stale"):
        observe_pytest_validation_result(result)


def test_bundle_binding_wrong_bundle_and_consumption_are_single_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _write_tiny_repository(
        tmp_path,
        filename="test_tiny_consumable.py",
        variant="consumable",
    )
    run_identity = _identity("consumable-run")
    bundle_identity = _identity("consumable-bundle")
    other_bundle_identity = _identity("other-bundle")
    monkeypatch.setenv("PYTEST_ADDOPTS", f"--ignore={target}")
    monkeypatch.setenv("PYTEST_PLUGINS", "caller_supplied_plugin_must_not_load")
    result = _execute_pytest_validation_fixture(
        validation_run_identity=run_identity,
        targets=(target,),
        execution_root=tmp_path,
    )

    observation = bind_pytest_validation_result_to_bundle(
        result,
        validation_run_identity=run_identity,
        evidence_bundle_identity=bundle_identity,
    )
    assert observation.validation_run_identity == run_identity
    assert observation.completed is True
    assert observation.total == 5
    exact_bytes = issued_pytest_validation_junit_bytes(
        result, evidence_bundle_identity=bundle_identity
    )
    validate_pytest_validation_junit_bytes(
        result,
        exact_bytes,
        evidence_bundle_identity=bundle_identity,
    )
    with pytest.raises(PytestValidationError, match="another bundle"):
        bind_pytest_validation_result_to_bundle(
            result,
            validation_run_identity=run_identity,
            evidence_bundle_identity=other_bundle_identity,
        )
    with pytest.raises(PytestValidationError, match="another evidence bundle"):
        issued_pytest_validation_junit_bytes(result, evidence_bundle_identity=other_bundle_identity)
    consumed = consume_pytest_validation_result(
        result,
        validation_run_identity=run_identity,
        evidence_bundle_identity=bundle_identity,
    )
    assert consumed is observation
    with pytest.raises(PytestValidationError, match="stale or already consumed"):
        observe_pytest_validation_result(result)
    with pytest.raises(PytestValidationError, match="stale or already consumed"):
        bind_pytest_validation_result_to_bundle(
            result,
            validation_run_identity=run_identity,
            evidence_bundle_identity=bundle_identity,
        )


def test_mutated_counts_runtime_skips_and_rehashed_xml_fail_registry_fingerprint(
    tmp_path: Path,
) -> None:
    _write_authoritative_config(tmp_path)
    target = tmp_path / "tests" / "test_tiny_mutation.py"
    target.write_text(
        "def test_actual_failure():\n    assert False\n",
        encoding="utf-8",
        newline="\n",
    )
    result = _execute_pytest_validation_fixture(
        validation_run_identity=_identity("mutation-run"),
        targets=(target,),
        execution_root=tmp_path,
    )
    observation = observe_pytest_validation_result(result)
    record = validation._ISSUED_RESULTS[id(result)]
    assert observation.completed is False
    assert observation.execution_status == "FAILED"
    assert observation.exit_code == 1
    assert observation.failed == 1
    assert observation.failure_details

    attacks = (
        ("total", observation.total + 1),
        ("runtime_seconds", "999.0"),
        ("skipped_node_ids", (*observation.skipped_node_ids, "forged::skip")),
        ("skipped_reasons", (*observation.skipped_reasons, "forged reason")),
        ("pytest_root_directory", str(tmp_path / "changed-root")),
        ("pytest_test_selection", (str(tmp_path / "changed-selection.py"),)),
        ("collected_node_ids", (*observation.collected_node_ids, "forged::test")),
        (
            "effective_plugin_identities",
            (*observation.effective_plugin_identities, ("forged",) * 7),
        ),
    )
    for field, attack in attacks:
        original = getattr(observation, field)
        object.__setattr__(observation, field, attack)
        with pytest.raises(PytestValidationError, match="observation was mutated"):
            observe_pytest_validation_result(result)
        object.__setattr__(observation, field, original)

    original_bytes = record.junit_xml_bytes
    original_sha256 = observation.junit_xml_sha256
    original_byte_count = observation.junit_xml_byte_count
    changed_bytes = original_bytes + b"\n"
    record.junit_xml_bytes = changed_bytes
    object.__setattr__(
        observation,
        "junit_xml_sha256",
        hashlib.sha256(changed_bytes).hexdigest(),
    )
    object.__setattr__(observation, "junit_xml_byte_count", len(changed_bytes))
    with pytest.raises(PytestValidationError, match="observation was mutated"):
        observe_pytest_validation_result(result)
    record.junit_xml_bytes = original_bytes
    object.__setattr__(observation, "junit_xml_sha256", original_sha256)
    object.__setattr__(observation, "junit_xml_byte_count", original_byte_count)
    assert observe_pytest_validation_result(result) is observation


@pytest.mark.parametrize(
    ("filename", "contents"),
    (
        ("conftest.py", "raise AssertionError('parent conftest must be rejected')\n"),
        ("pytest.ini", "[pytest]\naddopts = --ignore=tests\n"),
        (
            "pyproject.toml",
            '[tool.pytest.ini_options]\naddopts = "--ignore=tests"\n',
        ),
    ),
)
def test_parent_pytest_configuration_and_conftest_are_rejected_preflight(
    tmp_path: Path,
    filename: str,
    contents: str,
) -> None:
    root = tmp_path / "authoritative"
    target = _write_tiny_repository(
        root,
        filename="test_parent_boundary.py",
        variant="parent-boundary",
    )
    (tmp_path / filename).write_text(contents, encoding="utf-8", newline="\n")

    with pytest.raises(PytestValidationError, match="Unauthorized pytest configuration"):
        _execute_pytest_validation_fixture(
            validation_run_identity=_identity(f"parent-boundary-{filename}"),
            targets=(target,),
            execution_root=root,
        )


@pytest.mark.parametrize(
    ("filename", "contents"),
    (
        ("conftest.py", "raise AssertionError('root conftest must be rejected')\n"),
        ("pytest.ini", "[pytest]\naddopts = --ignore=tests\n"),
    ),
)
def test_repository_root_pytest_configuration_is_rejected_preflight(
    tmp_path: Path,
    filename: str,
    contents: str,
) -> None:
    target = _write_tiny_repository(
        tmp_path,
        filename="test_root_boundary.py",
        variant="root-boundary",
    )
    (tmp_path / filename).write_text(contents, encoding="utf-8", newline="\n")

    with pytest.raises(PytestValidationError, match="Unauthorized pytest configuration"):
        _execute_pytest_validation_fixture(
            validation_run_identity=_identity(f"root-boundary-{filename}"),
            targets=(target,),
            execution_root=tmp_path,
        )


def test_root_shadow_module_and_nonpytest_parent_files_cannot_change_execution(
    tmp_path: Path,
) -> None:
    root = tmp_path / "authoritative"
    target = _write_tiny_repository(
        root,
        filename="test_shadow_resistance.py",
        variant="shadow-resistance",
    )
    (root / "pytest.py").write_text(
        "raise AssertionError('cwd pytest.py shadowed installed pytest')\n",
        encoding="utf-8",
        newline="\n",
    )
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'unrelated-parent-project'\nversion = '0'\n",
        encoding="utf-8",
        newline="\n",
    )

    result = _execute_pytest_validation_fixture(
        validation_run_identity=_identity("shadow-resistant-run"),
        targets=(target,),
        execution_root=root,
    )
    observation = observe_pytest_validation_result(result)

    assert observation.completed is True
    assert observation.total == 5
    assert observation.pytest_config_path == str(root / "pyproject.toml")
    assert observation.command[1] == "-P"
    assert f"--confcutdir={root / 'tests'}" in observation.command


def test_selection_outside_authoritative_tests_root_is_rejected(tmp_path: Path) -> None:
    _write_authoritative_config(tmp_path)
    target = tmp_path / "outside.py"
    target.write_text("def test_outside():\n    assert True\n", encoding="utf-8", newline="\n")

    with pytest.raises(PytestValidationError, match="escapes the authoritative test root"):
        _execute_pytest_validation_fixture(
            validation_run_identity=_identity("escaped-selection-run"),
            targets=(target,),
            execution_root=tmp_path,
        )


@pytest.mark.parametrize("mutated_name", ("pyproject.toml", "tests/conftest.py"))
def test_authoritative_config_or_conftest_mutation_during_run_is_rejected(
    tmp_path: Path,
    mutated_name: str,
) -> None:
    config = _write_authoritative_config(tmp_path)
    conftest = tmp_path / "tests" / "conftest.py"
    conftest.write_text("BOUNDARY_VALUE = 1\n", encoding="utf-8", newline="\n")
    mutated = config if mutated_name == "pyproject.toml" else conftest
    target = tmp_path / "tests" / "test_mutate_boundary.py"
    target.write_text(
        "from pathlib import Path\n\n"
        "def test_mutate_bound_source():\n"
        f"    Path({str(mutated)!r}).write_text('changed during validation\\n', "
        "encoding='utf-8', newline='\\n')\n",
        encoding="utf-8",
        newline="\n",
    )

    result = _execute_pytest_validation_fixture(
        validation_run_identity=_identity(f"mutated-boundary-{mutated_name}"),
        targets=(target,),
        execution_root=tmp_path,
    )
    observation = validation._ISSUED_RESULTS[id(result)].observation

    assert observation.completed is False
    assert observation.execution_status == "FAILED"
    with pytest.raises(PytestValidationError, match="source identity is stale"):
        observe_pytest_validation_result(result)


@pytest.mark.parametrize(
    "attack",
    ("external-extra", "authorized-extra", "removed-conftest", "removed-core"),
)
def test_extra_or_removed_effective_pytest_plugin_is_rejected(
    tmp_path: Path,
    attack: str,
) -> None:
    _write_authoritative_config(tmp_path)
    target = tmp_path / "tests" / "test_plugin_boundary.py"
    target.write_text("def test_plugin_boundary():\n    assert True\n", encoding="utf-8")
    conftest = tmp_path / "tests" / "conftest.py"
    if attack == "external-extra":
        extra_plugin = tmp_path / "extra_plugin.py"
        extra_plugin.write_text(
            "def pytest_collection_modifyitems(items):\n    del items\n",
            encoding="utf-8",
            newline="\n",
        )
        conftest.write_text(
            "import importlib.util\n"
            "from pathlib import Path\n"
            "import pytest\n\n"
            f"PLUGIN_PATH = Path({str(extra_plugin)!r})\n"
            "SPEC = importlib.util.spec_from_file_location("
            "'unexpected_runtime_plugin', PLUGIN_PATH)\n"
            "assert SPEC is not None and SPEC.loader is not None\n"
            "PLUGIN = importlib.util.module_from_spec(SPEC)\n"
            "SPEC.loader.exec_module(PLUGIN)\n\n"
            "@pytest.hookimpl(tryfirst=True)\n"
            "def pytest_configure(config):\n"
            "    config.pluginmanager.register(PLUGIN, 'unexpected-runtime-plugin')\n",
            encoding="utf-8",
            newline="\n",
        )
    elif attack == "authorized-extra":
        conftest.write_text(
            "import pytest\n\n"
            "class AuthorizedSourceExtra:\n"
            "    pass\n\n"
            "@pytest.hookimpl(tryfirst=True)\n"
            "def pytest_configure(config):\n"
            "    config.pluginmanager.register(\n"
            "        AuthorizedSourceExtra(), 'authorized-source-extra'\n"
            "    )\n",
            encoding="utf-8",
            newline="\n",
        )
    elif attack == "removed-conftest":
        conftest.write_text(
            "import sys\n\n"
            "def pytest_collection_finish(session):\n"
            "    session.config.pluginmanager.unregister(sys.modules[__name__])\n",
            encoding="utf-8",
            newline="\n",
        )
    else:
        conftest.write_text(
            "def pytest_collection_finish(session):\n"
            "    plugin = session.config.pluginmanager.get_plugin('recwarn')\n"
            "    assert plugin is not None\n"
            "    session.config.pluginmanager.unregister(plugin)\n",
            encoding="utf-8",
            newline="\n",
        )

    result = _execute_pytest_validation_fixture(
        validation_run_identity=_identity(f"plugin-set-{attack}"),
        targets=(target,),
        execution_root=tmp_path,
    )
    observation = validation._ISSUED_RESULTS[id(result)].observation

    assert observation.completed is False
    assert observation.execution_status == "FAILED"
    assert any("plugin" in detail.lower() for detail in observation.failure_details)


@pytest.mark.parametrize(
    "attack",
    (
        "configure-extra",
        "collection-extra",
        "remove-readd",
        "sessionfinish-extra",
        "unconfigure-remove-readd",
    ),
)
def test_transient_plugin_lifecycle_mutations_are_rejected(
    tmp_path: Path,
    attack: str,
) -> None:
    _write_authoritative_config(tmp_path)
    target = tmp_path / "tests" / "test_transient_plugin.py"
    target.write_text("def test_transient_plugin():\n    assert True\n", encoding="utf-8")
    if attack in ("configure-extra", "collection-extra"):
        hook_name = (
            "pytest_configure" if attack == "configure-extra" else ("pytest_collection_modifyitems")
        )
        hook_arguments = "config" if attack == "configure-extra" else "config, items"
        conftest_source = (
            "import pytest\n\n"
            "class TransientExtra:\n"
            "    def __init__(self):\n"
            "        self.used = False\n\n"
            "    def use(self):\n"
            "        self.used = True\n\n"
            "@pytest.hookimpl(tryfirst=True)\n"
            f"def {hook_name}({hook_arguments}):\n"
            "    plugin = TransientExtra()\n"
            f"    config.pluginmanager.register(plugin, 'transient-{attack}')\n"
            "    plugin.use()\n"
            "    assert plugin.used\n"
            "    config.pluginmanager.unregister(plugin)\n"
        )
    elif attack == "remove-readd":
        conftest_source = (
            "def pytest_collection_modifyitems(config, items):\n"
            "    plugin = config.pluginmanager.get_plugin('recwarn')\n"
            "    assert plugin is not None\n"
            "    config.pluginmanager.unregister(plugin)\n"
            "    assert config.pluginmanager.register(plugin, 'recwarn') == 'recwarn'\n"
        )
    elif attack == "sessionfinish-extra":
        conftest_source = (
            "import pytest\n\n"
            "class PostSessionExtra:\n"
            "    def __init__(self):\n"
            "        self.used = False\n\n"
            "    def use(self):\n"
            "        self.used = True\n\n"
            "@pytest.hookimpl(hookwrapper=True, tryfirst=True)\n"
            "def pytest_sessionfinish(session):\n"
            "    yield\n"
            "    plugin = PostSessionExtra()\n"
            "    session.config.pluginmanager.register(plugin, 'post-session-extra')\n"
            "    plugin.use()\n"
            "    assert plugin.used\n"
            "    session.config.pluginmanager.unregister(plugin)\n"
        )
    else:
        conftest_source = (
            "import os\n"
            "from pathlib import Path\n\n"
            "def pytest_unconfigure(config):\n"
            "    receipt = Path(\n"
            "        os.environ['RDE_BROADER_PYTEST_VALIDATION_RECEIPT_PATH']\n"
            "    )\n"
            "    assert not receipt.exists()\n"
            "    plugin = config.pluginmanager.get_plugin('recwarn')\n"
            "    assert plugin is not None\n"
            "    config.pluginmanager.unregister(plugin)\n"
            "    assert config.pluginmanager.register(plugin, 'recwarn') == 'recwarn'\n"
        )
    (tmp_path / "tests" / "conftest.py").write_text(
        conftest_source,
        encoding="utf-8",
        newline="\n",
    )

    result = _execute_pytest_validation_fixture(
        validation_run_identity=_identity(f"transient-plugin-{attack}"),
        targets=(target,),
        execution_root=tmp_path,
    )
    observation = validation._ISSUED_RESULTS[id(result)].observation

    assert observation.completed is False
    assert observation.execution_status == "FAILED"
    assert any("lifecycle" in detail.lower() for detail in observation.failure_details)


@pytest.mark.parametrize("attack", ("rootdir", "arguments", "nodeids"))
def test_disposable_execution_rejects_forged_root_arguments_and_collected_nodeids(
    tmp_path: Path,
    attack: str,
) -> None:
    _write_authoritative_config(tmp_path)
    target = tmp_path / "tests" / "test_execution_identity.py"
    target.write_text("def test_execution_identity():\n    assert True\n", encoding="utf-8")
    alternate_root = tmp_path / "alternate-root"
    _write_authoritative_config(alternate_root)
    (alternate_root / "tests" / target.name).write_bytes(target.read_bytes())
    if attack == "rootdir":
        mutation = (
            "    state.observed_configuration = replace(\n"
            "        state.observed_configuration,\n"
            f"        root_directory={str(alternate_root)!r},\n"
            "    )\n"
        )
    elif attack == "arguments":
        mutation = (
            "    state.observed_configuration = replace(\n"
            "        state.observed_configuration,\n"
            "        resolved_arguments=('forged-selection.py',),\n"
            "    )\n"
        )
    else:
        mutation = "    state.collected_node_ids[:] = ['tests/forged.py::test_forged']\n"
    (tmp_path / "tests" / "conftest.py").write_text(
        "from dataclasses import replace\n"
        "import research_decision_engine.benchmarks.broader_validation as validation\n\n"
        "def pytest_sessionfinish(session):\n"
        "    state = validation._PLUGIN_STATE\n"
        "    assert state is not None\n" + mutation,
        encoding="utf-8",
        newline="\n",
    )

    result = _execute_pytest_validation_fixture(
        validation_run_identity=_identity(f"execution-identity-{attack}"),
        targets=(target,),
        execution_root=tmp_path,
    )
    observation = validation._ISSUED_RESULTS[id(result)].observation

    assert observation.completed is False
    if attack == "nodeids":
        assert any("collection" in detail.lower() for detail in observation.failure_details)
    else:
        assert any("root/config/arguments" in detail for detail in observation.failure_details)


def test_parent_reopens_final_junit_and_rejects_post_receipt_rewrite(
    tmp_path: Path,
) -> None:
    _write_authoritative_config(tmp_path)
    target = tmp_path / "tests" / "test_late_junit.py"
    target.write_text("def test_late_junit():\n    assert True\n", encoding="utf-8")
    (tmp_path / "tests" / "conftest.py").write_text(
        "from pathlib import Path\n\n"
        "def pytest_unconfigure(config):\n"
        "    junit = Path(str(config.option.xmlpath))\n"
        "    junit.write_bytes(junit.read_bytes() + b'\\n')\n",
        encoding="utf-8",
        newline="\n",
    )

    result = _execute_pytest_validation_fixture(
        validation_run_identity=_identity("late-junit-rewrite"),
        targets=(target,),
        execution_root=tmp_path,
    )
    observation = validation._ISSUED_RESULTS[id(result)].observation

    assert observation.completed is False
    assert any("JUnit observations differ" in detail for detail in observation.failure_details)


@pytest.mark.parametrize("attack", ("replace", "hardlink", "other-process"))
def test_authoritative_junit_file_rejects_replacement_hardlink_and_other_writer(
    tmp_path: Path,
    attack: str,
) -> None:
    _write_authoritative_config(tmp_path)
    target = tmp_path / "tests" / "test_junit_producer.py"
    target.write_text("def test_junit_producer():\n    assert True\n", encoding="utf-8")
    conftest = tmp_path / "tests" / "conftest.py"
    if attack == "replace":
        hook = (
            "import os\n"
            "from pathlib import Path\n\n"
            "def pytest_unconfigure(config):\n"
            "    junit = Path(str(config.option.xmlpath))\n"
            "    replacement = junit.with_name('replacement.xml')\n"
            "    replacement.write_bytes(junit.read_bytes())\n"
            "    os.replace(replacement, junit)\n"
        )
    elif attack == "hardlink":
        hook = (
            "import os\n"
            "from pathlib import Path\n\n"
            "def pytest_sessionfinish(session):\n"
            "    junit = Path(str(session.config.option.xmlpath))\n"
            "    os.link(junit, junit.with_name('linked-copy.xml'))\n"
        )
    else:
        hook = (
            "import subprocess\n"
            "import sys\n"
            "from pathlib import Path\n\n"
            "def pytest_unconfigure(config):\n"
            "    junit = Path(str(config.option.xmlpath))\n"
            "    subprocess.run([sys.executable, '-c', "
            "'from pathlib import Path; p=Path(__import__(\"sys\").argv[1]); '"
            "'p.write_bytes(p.read_bytes()+b\"\\n\")', str(junit)], check=True)\n"
        )
    conftest.write_text(hook, encoding="utf-8", newline="\n")

    result = _execute_pytest_validation_fixture(
        validation_run_identity=_identity(f"junit-producer-{attack}"),
        targets=(target,),
        execution_root=tmp_path,
    )
    observation = validation._ISSUED_RESULTS[id(result)].observation

    assert observation.completed is False
    assert observation.execution_status == "FAILED"
    assert observation.failure_details


def test_parent_junit_parser_derives_exact_node_id_and_skip_reason(
    tmp_path: Path,
) -> None:
    _write_authoritative_config(tmp_path)
    (tmp_path / "tests" / "test_parent_parse.py").write_text(
        "def test_skipped_case():\n    raise AssertionError\n",
        encoding="utf-8",
        newline="\n",
    )
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<testsuites name="pytest tests">'
        '<testsuite name="pytest" errors="0" failures="0" skipped="1" '
        'tests="1" time="0.125">'
        '<testcase classname="tests.test_parent_parse" name="test_skipped_case" '
        'time="0.001"><skipped type="pytest.skip" '
        'message="exact parent-derived reason">source.py:1: exact parent-derived reason'
        "</skipped></testcase></testsuite></testsuites>",
        encoding="utf-8",
        newline="\n",
    )

    observation = validation._read_junit_observation(
        junit_path,
        pytest_root=tmp_path,
    )

    assert observation.node_ids == ("tests/test_parent_parse.py::test_skipped_case",)
    assert observation.skipped_node_ids == observation.node_ids
    assert observation.skipped_reasons == ("Skipped: exact parent-derived reason",)


def test_parent_junit_parser_rejects_truncated_xml(tmp_path: Path) -> None:
    junit_path = tmp_path / "truncated.xml"
    junit_path.write_bytes(b'<testsuites><testsuite tests="1">')

    with pytest.raises(PytestValidationError, match="malformed"):
        validation._read_junit_observation(junit_path, pytest_root=tmp_path)


def test_zero_collected_tests_cannot_be_completed_evidence(tmp_path: Path) -> None:
    _write_authoritative_config(tmp_path)
    target = tmp_path / "tests" / "test_empty.py"
    target.write_text("VALUE = 1\n", encoding="utf-8", newline="\n")

    result = _execute_pytest_validation_fixture(
        validation_run_identity=_identity("zero-collected-run"),
        targets=(target,),
        execution_root=tmp_path,
    )
    observation = observe_pytest_validation_result(result)

    assert observation.completed is False
    assert observation.execution_status == "FAILED"
    assert observation.total == 0


def test_owner_claim_is_opaque_exclusive_releasable_and_terminally_stale(
    tmp_path: Path,
) -> None:
    target = _write_tiny_repository(
        tmp_path,
        filename="test_owner_claim.py",
        variant="owner-claim",
    )
    run_identity = _identity("owner-claim-run")
    bundle_identity = _identity("owner-claim-bundle")
    result = _execute_pytest_validation_fixture(
        validation_run_identity=run_identity,
        targets=(target,),
        execution_root=tmp_path,
    )
    exact_junit = issued_pytest_validation_junit_bytes(result)

    with pytest.raises(TypeError, match="issued only by the registry"):
        PytestValidationOwnerClaim()
    claim = claim_pytest_validation_result_owner(result)
    with pytest.raises(TypeError, match="cannot be copied"):
        copy.copy(claim)
    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(claim)
    with pytest.raises(PytestValidationError, match="another owner claim"):
        observe_pytest_validation_result(result)
    with pytest.raises(PytestValidationError, match="another owner claim"):
        validate_pytest_validation_result(
            result,
            validation_run_identity=run_identity,
        )
    with pytest.raises(PytestValidationError, match="another owner claim"):
        bind_pytest_validation_result_to_bundle(
            result,
            validation_run_identity=run_identity,
            evidence_bundle_identity=bundle_identity,
        )
    with pytest.raises(PytestValidationError, match="another owner claim"):
        issued_pytest_validation_junit_bytes(result)
    with pytest.raises(PytestValidationError, match="another owner claim"):
        validate_pytest_validation_junit_bytes(result, exact_junit)
    with pytest.raises(PytestValidationError, match="another owner claim"):
        consume_pytest_validation_result(
            result,
            validation_run_identity=run_identity,
            evidence_bundle_identity=bundle_identity,
        )
    with pytest.raises(PytestValidationError, match="another owner claim"):
        claim_pytest_validation_result_owner(result)

    observation = observe_pytest_validation_result(result, owner_claim=claim)
    bind_pytest_validation_result_to_bundle(
        result,
        validation_run_identity=run_identity,
        evidence_bundle_identity=bundle_identity,
        owner_claim=claim,
    )
    assert issued_pytest_validation_junit_bytes(result, owner_claim=claim)
    consumed = consume_pytest_validation_result(
        result,
        validation_run_identity=run_identity,
        evidence_bundle_identity=bundle_identity,
        owner_claim=claim,
    )

    assert consumed is observation
    with pytest.raises(PytestValidationError, match="stale or already consumed"):
        observe_pytest_validation_result(result, owner_claim=claim)


def test_released_owner_claim_cannot_be_reused(tmp_path: Path) -> None:
    target = _write_tiny_repository(
        tmp_path,
        filename="test_release_claim.py",
        variant="release-claim",
    )
    result = _execute_pytest_validation_fixture(
        validation_run_identity=_identity("release-claim-run"),
        targets=(target,),
        execution_root=tmp_path,
    )
    first = claim_pytest_validation_result_owner(result)
    release_pytest_validation_result_owner(result, owner_claim=first)

    with pytest.raises(PytestValidationError, match="forged or stale"):
        observe_pytest_validation_result(result, owner_claim=first)
    assert observe_pytest_validation_result(result).completed is True
    second = claim_pytest_validation_result_owner(result)
    assert second is not first
    release_pytest_validation_result_owner(result, owner_claim=second)


def test_concurrent_terminal_consumption_has_exactly_one_winner(tmp_path: Path) -> None:
    target = _write_tiny_repository(
        tmp_path,
        filename="test_atomic_consume.py",
        variant="atomic-consume",
    )
    run_identity = _identity("atomic-consume-run")
    bundle_identity = _identity("atomic-consume-bundle")
    result = _execute_pytest_validation_fixture(
        validation_run_identity=run_identity,
        targets=(target,),
        execution_root=tmp_path,
    )
    bind_pytest_validation_result_to_bundle(
        result,
        validation_run_identity=run_identity,
        evidence_bundle_identity=bundle_identity,
    )
    barrier = threading.Barrier(2)

    def attempt_consume() -> str:
        barrier.wait(timeout=5)
        try:
            consume_pytest_validation_result(
                result,
                validation_run_identity=run_identity,
                evidence_bundle_identity=bundle_identity,
            )
        except PytestValidationError as error:
            return str(error)
        return "consumed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _: attempt_consume(), range(2)))

    assert outcomes.count("consumed") == 1
    assert sum("stale" in outcome for outcome in outcomes) == 1


def test_timeout_kills_process_tree_and_rejects_late_child_write(tmp_path: Path) -> None:
    _write_authoritative_config(tmp_path)
    marker = tmp_path / "late-child-marker.txt"
    spawned = tmp_path / "child-spawned.txt"
    target = tmp_path / "tests" / "test_timeout_tree.py"
    child_code = (
        "import time\n"
        "from pathlib import Path\n"
        "time.sleep(5)\n"
        f"Path({str(marker)!r}).write_text('late', encoding='utf-8')\n"
    )
    target.write_text(
        "import subprocess\n"
        "import sys\n"
        "import time\n"
        "from pathlib import Path\n\n"
        "def test_timeout_tree():\n"
        f"    subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
        f"    Path({str(spawned)!r}).write_text('spawned', encoding='utf-8')\n"
        "    time.sleep(30)\n",
        encoding="utf-8",
        newline="\n",
    )

    result = _execute_pytest_validation_fixture(
        validation_run_identity=_identity("timeout-tree-run"),
        targets=(target,),
        execution_root=tmp_path,
        timeout_seconds=3.0,
    )
    observation = validation._ISSUED_RESULTS[id(result)].observation

    assert spawned.is_file()
    assert observation.completed is False
    assert observation.subprocess_start_identity is not None
    deadline = time.monotonic() + 5.5
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(0.05)
    assert not marker.exists()


def test_timeout_ceiling_is_fixed_without_starting_production_pytest(
    primary_result: tuple[PytestValidationResult, Path],
) -> None:
    _, target = primary_result

    assert DEFAULT_PYTEST_TIMEOUT_SECONDS == 10_800.0
    assert MAX_PYTEST_TIMEOUT_SECONDS == 10_800.0
    with pytest.raises(PytestValidationError, match="at most 10800 seconds"):
        _execute_pytest_validation_fixture(
            validation_run_identity=_identity("invalid-timeout-run"),
            targets=(target,),
            timeout_seconds=MAX_PYTEST_TIMEOUT_SECONDS + 1,
        )
