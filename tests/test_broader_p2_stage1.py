from __future__ import annotations

import _functools  # type: ignore[import-not-found]
import builtins
import concurrent.futures.thread as futures_thread
import contextlib
import copy
import errno
import functools
import hashlib
import inspect
import json
import os
import pathlib
import pickle
import platform
import secrets
import subprocess
import sys
import tempfile
import threading
import typing
import zlib
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from dataclasses import FrozenInstanceError, dataclass, replace
from pathlib import Path
from types import CodeType, FrameType, ModuleType
from typing import Any, cast

import pytest

import research_decision_engine.benchmarks.broader_analysis as broader_analysis
import research_decision_engine.benchmarks.broader_execution as execution
import research_decision_engine.benchmarks.broader_oracle as oracle
import research_decision_engine.benchmarks.broader_protocol as broader_protocol
import research_decision_engine.benchmarks.broader_statistics as broader_statistics
import research_decision_engine.benchmarks.broader_validation as validation
import research_decision_engine.benchmarks.broader_validation_evidence as stage1
import research_decision_engine.benchmarks.reporting as reporting
from research_decision_engine.benchmarks import broader_conformance, broader_smoke
from research_decision_engine.benchmarks.broader_conformance import (
    CONFORMANCE_DEPTH_THREE_SEEDS,
    CONFORMANCE_DEPTH_THREE_WORLD_ID,
    CONFORMANCE_SEEDS,
    CONFORMANCE_WORLD_ID,
)
from research_decision_engine.benchmarks.broader_protocol import (
    ARMS,
    PROTOCOL_CHECKPOINT,
    SMOKE_SEEDS,
    SMOKE_WORLD_IDS,
    protocol_hash,
    repository_root,
)
from research_decision_engine.benchmarks.broader_worlds import BUDGETS

type FixturePlanSet = tuple[
    validation._FixturePytestPlan,
    oracle._FixtureOraclePlan,
    execution._FixtureExecutionSpecification,
    execution._FixtureExecutionSpecification,
    execution._FixtureExecutionSpecification,
    execution._FixtureExecutionSpecification,
]


@dataclass(frozen=True, slots=True)
class _FixtureStage1:
    context: stage1.Layer0Context
    run: stage1._FixtureValidationRun
    executor_implementation: execution._FixtureExecutorImplementationIdentity
    plans: FixturePlanSet


@pytest.fixture(autouse=True)
def _isolated_stage1_and_no_workload() -> Iterator[dict[str, int]]:
    """Reset only fixture state and stop any accidental workload at its first frame."""

    stage1._reset_fixture_registries()
    watched_functions: tuple[tuple[str, object], ...] = (
        ("subprocess", subprocess.Popen.__init__),
        ("oracle", oracle._enumerate_oracle_partitions),
        ("executor", ThreadPoolExecutor.submit),
        ("smoke_entry", broader_smoke.run_smoke),
        ("bound_smoke", broader_smoke._run_bound_smoke),
        ("smoke", broader_smoke._execute_job),
        ("production_fixture", broader_conformance.build_production_fixture),
        ("replay", broader_conformance._execute_audited_lifecycle),
        ("fixture", broader_conformance._execute_fixture_audited_lifecycle),
        ("conformance_runs", broader_conformance._execute_runs),
        ("replay_fixture", broader_conformance._execute_run_job),
        ("pytest", validation.execute_pytest_validation),
        ("calibration", broader_statistics.expected_calibration_error),
        ("scoring", broader_analysis._trace_score_map),
        ("evidence_render", broader_smoke._render_smoke_evidence),
        ("evidence", reporting.write_benchmark_outputs),
    )
    watched: dict[CodeType, str] = {
        cast(CodeType, cast(Any, function).__code__): name for name, function in watched_functions
    }
    calls = {name: 0 for name, _ in watched_functions}
    previous = sys.getprofile()
    previous_thread_profile = threading.getprofile()

    def profile(frame: FrameType, event: str, arg: object) -> None:
        name = watched.get(frame.f_code) if event == "call" else None
        if name is not None:
            calls[name] += 1
            raise AssertionError(f"P2 Stage-1 test entered prohibited {name} workload")
        if previous is not None:
            previous(frame, cast(Any, event), arg)

    sys.setprofile(profile)
    threading.setprofile(profile)
    try:
        yield calls
    finally:
        threading.setprofile(previous_thread_profile)
        sys.setprofile(previous)
        stage1._reset_fixture_registries()
    assert calls == {name: 0 for name, _ in watched_functions}


def _assert_fail_closed(error: stage1.P2Stage1Error) -> None:
    assert error.workload_started is False
    assert error.scoring_entered is False
    assert error.scientific_output_entered is False
    assert error.evidence_checkpointed is False
    assert error.independent_review_status == "pending"
    assert error.safe_for_full_replication is False
    assert error.full_replication_authorized is False


@contextmanager
def _expect_stage1_error(
    *error_codes: str,
) -> Iterator[pytest.ExceptionInfo[stage1.P2Stage1Error]]:
    """Require every Stage-1 rejection to carry the complete fail-closed status."""

    with pytest.raises(stage1.P2Stage1Error) as captured:
        yield captured
    _assert_fail_closed(captured.value)
    if error_codes:
        assert captured.value.error_code in error_codes


def _git_object_bytes(kind: str, payload: bytes) -> bytes:
    return f"{kind} {len(payload)}\0".encode("ascii") + payload


def _git_object_id(kind: str, payload: bytes) -> str:
    return hashlib.sha1(  # noqa: S324 - Git object identity is defined as SHA-1.
        _git_object_bytes(kind, payload),
        usedforsecurity=False,
    ).hexdigest()


def _write_loose_git_object(git_directory: Path, kind: str, payload: bytes) -> str:
    raw = _git_object_bytes(kind, payload)
    object_id = hashlib.sha1(  # noqa: S324 - Git object identity is defined as SHA-1.
        raw,
        usedforsecurity=False,
    ).hexdigest()
    destination = git_directory / "objects" / object_id[:2] / object_id[2:]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(zlib.compress(raw))
    return object_id


def _synthetic_clean_git_repository(tmp_path: Path) -> tuple[Path, str, str]:
    root = (tmp_path / "git-repository").resolve()
    root.mkdir()
    (root / "research_decision_engine").mkdir()
    (root / "tests").mkdir()
    tracked = {
        "pyproject.toml": b"[project]\nname = 'stage1-git-test'\n",
        "uv.lock": b"version = 1\n",
    }
    object_ids: dict[str, str] = {}
    for relative, raw in tracked.items():
        (root / relative).write_bytes(raw)
        object_ids[relative] = _git_object_id("blob", raw)

    tree_payload = b"".join(
        b"100644 " + relative.encode("utf-8") + b"\0" + bytes.fromhex(object_ids[relative])
        for relative in sorted(tracked, key=str.encode)
    )
    root_tree = _git_object_id("tree", tree_payload)
    git_directory = root / ".git"
    commit_payload = (
        f"tree {root_tree}\n"
        "author Stage One <stage1@example.invalid> 0 +0000\n"
        "committer Stage One <stage1@example.invalid> 0 +0000\n"
        "\nsynthetic clean snapshot\n"
    ).encode("ascii")
    commit = _write_loose_git_object(git_directory, "commit", commit_payload)
    (git_directory / "HEAD").write_text(commit + "\n", encoding="ascii")

    index_entries = bytearray()
    for relative in sorted(tracked, key=str.encode):
        path_raw = relative.encode("utf-8")
        fixed = (
            b"\0" * 24
            + (0o100644).to_bytes(4, "big")
            + b"\0" * 12
            + bytes.fromhex(object_ids[relative])
            + len(path_raw).to_bytes(2, "big")
        )
        entry = fixed + path_raw + b"\0"
        index_entries.extend(entry)
        index_entries.extend(b"\0" * ((-len(entry)) % 8))
    index_payload = b"DIRC" + (2).to_bytes(4, "big") + len(tracked).to_bytes(4, "big")
    index_payload += bytes(index_entries)
    index_checksum = hashlib.sha1(  # noqa: S324 - Git index checksum is defined as SHA-1.
        index_payload,
        usedforsecurity=False,
    ).digest()
    (git_directory / "index").write_bytes(index_payload + index_checksum)
    return root, commit, root_tree


def _current_bootstrap_manifest_material() -> tuple[Path, bytes]:
    root = repository_root().resolve(strict=True)
    snapshot = stage1._current_git_snapshot(root)
    runtime, runtime_identity = stage1._current_runtime()
    dependency_environment = validation._current_production_dependency_environment()
    dependency_lock_sha256 = hashlib.sha256(dict(snapshot.scoped_blobs)["uv.lock"]).hexdigest()
    git_directory = stage1._resolve_git_directory(root)
    return (
        stage1._trusted_bootstrap_manifest_path(git_directory, snapshot.commit),
        stage1._trusted_bootstrap_manifest_bytes(
            snapshot=snapshot,
            dependency_lock_sha256=dependency_lock_sha256,
            runtime=runtime,
            runtime_identity=runtime_identity,
            dependency_environment=dependency_environment,
        ),
    )


@pytest.fixture(scope="module", autouse=True)
def _provision_clean_tree_bootstrap_manifest() -> Iterator[None]:
    if os.environ.get("RDE_STAGE1_CLEAN_PRODUCTION_TESTS") != "1":
        yield
        return
    manifest_path, expected_bytes = _current_bootstrap_manifest_material()
    created_directories: list[Path] = []
    for directory in (manifest_path.parent.parent, manifest_path.parent):
        if directory.exists():
            assert directory.is_dir() and not directory.is_symlink() and not directory.is_junction()
            continue
        directory.mkdir()
        created_directories.append(directory)
    created_manifest = False
    try:
        try:
            with manifest_path.open("xb") as handle:
                handle.write(expected_bytes)
            created_manifest = True
        except FileExistsError:
            assert manifest_path.read_bytes() == expected_bytes
        status = manifest_path.stat(follow_symlinks=False)
        manifest_identity = (status.st_dev, status.st_ino)
        yield
        final_status = manifest_path.stat(follow_symlinks=False)
        assert (final_status.st_dev, final_status.st_ino) == manifest_identity
        assert manifest_path.read_bytes() == expected_bytes
    finally:
        if created_manifest and manifest_path.exists():
            final_status = manifest_path.stat(follow_symlinks=False)
            if (final_status.st_dev, final_status.st_ino) == manifest_identity:
                manifest_path.unlink()
        for directory in reversed(created_directories):
            if directory.exists():
                directory.rmdir()


def _smoke_jobs(*, reversed_arms: bool = False) -> tuple[tuple[str, int, str, float, object], ...]:
    arms = tuple(reversed(ARMS)) if reversed_arms else ARMS
    return tuple(
        (world_id, seed, budget_id, budget, arm)
        for world_id in SMOKE_WORLD_IDS
        for seed in SMOKE_SEEDS
        for budget_id, budget in BUDGETS
        for arm in arms
    )


def _fixture_jobs() -> tuple[tuple[str, int, str, float, object], ...]:
    return tuple(
        (world_id, seed, budget_id, budget, arm)
        for world_id, seeds in (
            (CONFORMANCE_WORLD_ID, CONFORMANCE_SEEDS),
            (CONFORMANCE_DEPTH_THREE_WORLD_ID, CONFORMANCE_DEPTH_THREE_SEEDS),
        )
        for seed in seeds
        for budget_id, budget in BUDGETS
        for arm in ARMS
    )


def _file_projection() -> stage1.FileProjection:
    path = (repository_root() / "pyproject.toml").resolve(strict=True)
    raw = path.read_bytes()
    return stage1.FileProjection(len(raw), str(path), hashlib.sha256(raw).hexdigest())


def _pytest_projection(
    context: stage1.Layer0Context,
    run: stage1._FixtureValidationRun,
) -> validation.PytestPlanProjection:
    file = _file_projection()
    root = str(repository_root().resolve(strict=True))
    environment = (
        validation.PytestEnvironmentRow(
            name="PYTHONHASHSEED",
            name_sha256=hashlib.sha256(b"PYTHONHASHSEED").hexdigest(),
            value_byte_count=1,
            value_sha256=hashlib.sha256(b"0").hexdigest(),
        ),
    )
    environment_id = protocol_hash(
        "validation_evidence_pytest_environment/v1",
        [row.as_dict() for row in environment],
    )
    return validation.PytestPlanProjection(
        argv=(root, "-P", "-m", "pytest", str(repository_root() / "tests")),
        conftests=(),
        control_paths=validation.PytestControlPathsProjection(root, root, root),
        controlled_environment=tuple(
            validation.PytestControlledEnvironmentRow(
                "unset" if value is None else "set", name, value
            )
            for name, value in validation._CONTROLLED_SUBPROCESS_ENVIRONMENT
        ),
        environment=environment,
        environment_sha256=environment_id,
        evidence_contract_checkpoint=stage1.EVIDENCE_CONTRACT_CHECKPOINT,
        implementation=context.implementation,
        junit_destination=validation.PytestJunitDestinationProjection(
            destination_path=root,
            device_id=1,
            file_id=1,
            initial_sha256=hashlib.sha256(b"x" * 32).hexdigest(),
        ),
        plan_issuer_identity=context.pytest_plan_issuer_identity,
        plugins=(),
        protocol_checkpoint=PROTOCOL_CHECKPOINT,
        pytest_configuration=file,
        pytest_rootdir=root,
        pytest_runtime=validation.PytestRuntimeProjection(
            pluggy_source=file,
            pluggy_version="fixture",
            pytest_source=file,
            pytest_version="fixture",
            validation_plugin_source=file,
        ),
        repository_root=root,
        runtime=context.runtime,
        runtime_identity=context.runtime_identity,
        selected_tests=(
            validation.PytestSelectedTestProjection(
                "path", str((repository_root() / "tests").resolve(strict=True))
            ),
        ),
        validation_run_id=stage1._fixture_validation_run_id(run),
        working_directory=root,
    )


def _canonical_plan_set() -> _FixtureStage1:
    """Issue the exact fixture-domain analogue of the frozen six production slots."""

    context = stage1._fixture_layer0_context()
    run = stage1._issue_fixture_validation_run()
    executor_implementation = execution._issue_fixture_executor_implementation(context, run)
    pytest_plan = validation._issue_fixture_pytest_plan(
        projection=_pytest_projection(context, run),
        validation_run=run,
    )
    oracle_plan = oracle._issue_fixture_oracle_plan(
        projection=oracle._build_fixture_oracle_plan_projection(
            context=context,
            validation_run=run,
        ),
        validation_run=run,
    )
    execution_plans = (
        execution._issue_fixture_execution_specification(
            context=context,
            validation_run=run,
            executor_implementation=executor_implementation,
            function=broader_smoke._execute_job,
            jobs=_smoke_jobs(),
            role="primary_smoke",
        ),
        execution._issue_fixture_execution_specification(
            context=context,
            validation_run=run,
            executor_implementation=executor_implementation,
            function=broader_smoke._execute_job,
            jobs=_smoke_jobs(reversed_arms=True),
            role="altered_order_replay",
        ),
        execution._issue_fixture_execution_specification(
            context=context,
            validation_run=run,
            executor_implementation=executor_implementation,
            function=broader_conformance._execute_run_job,
            jobs=_fixture_jobs(),
            role="fixture_primary",
        ),
        execution._issue_fixture_execution_specification(
            context=context,
            validation_run=run,
            executor_implementation=executor_implementation,
            function=broader_conformance._execute_run_job,
            jobs=_fixture_jobs(),
            role="fixture_replay",
        ),
    )
    return _FixtureStage1(
        context,
        run,
        executor_implementation,
        (pytest_plan, oracle_plan, *execution_plans),
    )


def _primary_projection(bundle: _FixtureStage1) -> execution.ExecutionSpecificationProjection:
    return execution._fixture_execution_specification_projection(bundle.plans[2])


def test_a_production_authority_has_no_importable_token_or_mutable_registry() -> None:
    source = inspect.getsource(stage1)
    for removed_name in (
        "_INVOCATION_CONSTRUCTION_KEY",
        "_ProductionInvocation",
        "_INVOCATIONS",
        "_begin_production_invocation",
        "_issue_validation_run",
        "_register_plan",
    ):
        assert removed_name not in source
        assert not hasattr(stage1, removed_name)
    registry_names = {
        name
        for name, value in vars(stage1).items()
        if isinstance(value, dict)
        and any(fragment in name for fragment in ("RUN_RECORD", "PLAN_RECORD", "AUTHORITY_RECORD"))
    }
    assert registry_names == {
        "_FIXTURE_RUN_RECORDS",
        "_FIXTURE_PLAN_RECORDS",
        "_FIXTURE_AUTHORITY_RECORDS",
    }
    summary = stage1._production_registry_snapshot()
    with pytest.raises(FrozenInstanceError):
        summary.reserved_runs = 1  # type: ignore[misc]
    for capability_type in (
        stage1.ValidationRun,
        stage1.ValidationAuthority,
        validation.PytestPlan,
        oracle.OraclePlan,
        execution.ExecutionSpecification,
    ):
        for constructor_name in ("from_id", "from_mapping", "deserialize", "promote"):
            assert not hasattr(capability_type, constructor_name)
    opaque_source = cast(
        tuple[object, object, object, CodeType],
        cast(Any, broader_smoke.execute_bounded_validation_evidence)._rde_opaque_source,
    )
    public_code = opaque_source[3]
    public_parameters = public_code.co_varnames[
        : public_code.co_argcount + public_code.co_kwonlyargcount
    ]
    assert not any(
        name
        in {
            "validation_run_id",
            "plan_id",
            "validation_authority_id",
            "jobs",
            "configuration",
        }
        for name in public_parameters
    )


def test_a_every_production_component_issuer_rejects_lookalikes(tmp_path: Path) -> None:
    preparation: stage1._ProductionPreparationCapability = object.__new__(
        cast(Any, stage1._ProductionPreparationCapability)
    )
    run: stage1.ValidationRun = object.__new__(cast(Any, stage1.ValidationRun))
    executor_implementation: execution.ExecutorImplementationIdentity = object.__new__(
        cast(Any, execution.ExecutorImplementationIdentity)
    )
    context = stage1._fixture_layer0_context()
    control_directory_status = tmp_path.stat(follow_symlinks=False)
    control_directory_identity = (
        control_directory_status.st_dev,
        control_directory_status.st_ino,
    )
    calls: tuple[Callable[[], object], ...] = (
        lambda: execution._issue_production_executor_implementation(
            preparation,
            context,
            run,
            lambda _: None,
            lambda _: None,
        ),
        lambda: validation._issue_production_pytest_plan_draft(
            preparation=preparation,
            context=context,
            validation_run=run,
            control_directory=tmp_path,
            control_directory_identity=control_directory_identity,
        ),
        lambda: oracle._issue_production_oracle_plan_draft(preparation, context, run),
        lambda: execution._issue_production_execution_plan_drafts(
            preparation,
            context,
            run,
            executor_implementation,
        ),
    )
    before = stage1._production_registry_snapshot()
    for call in calls:
        with _expect_stage1_error("EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE"):
            call()
    assert stage1._production_registry_snapshot() == before


def test_a_opaque_production_capabilities_reject_construct_copy_pickle_and_reduce() -> None:
    with pytest.raises(TypeError):
        stage1._ProductionPreparationCapability()
    with pytest.raises(TypeError):
        stage1.ValidationRun()
    for capability_type in (
        stage1._ProductionPreparationCapability,
        stage1.ValidationRun,
        stage1._ProductionSessionToken,
    ):
        forged: object = object.__new__(cast(Any, capability_type))
        operations: tuple[Callable[[object], object], ...] = (
            copy.copy,
            copy.deepcopy,
            pickle.dumps,
        )
        for operation in operations:
            with pytest.raises(TypeError):
                operation(forged)
        with pytest.raises(TypeError):
            forged.__reduce__()


def test_a_replay_cross_run_caller_strings_and_spoofed_stack_never_authorize() -> None:
    forged_preparation: stage1._ProductionPreparationCapability = object.__new__(
        cast(Any, stage1._ProductionPreparationCapability)
    )
    first_run: stage1.ValidationRun = object.__new__(cast(Any, stage1.ValidationRun))
    second_run: stage1.ValidationRun = object.__new__(cast(Any, stage1.ValidationRun))

    for run in (first_run, first_run, second_run):
        with _expect_stage1_error("EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE"):
            stage1._require_production_preparation(forged_preparation, validation_run=run)
    with _expect_stage1_error("EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE"):
        stage1._reserve_production_validation_run(cast(Any, "caller-chosen-token"))
    with _expect_stage1_error("VALIDATION_RUN_STALE"):
        stage1.validation_run_id(cast(Any, "a" * 64))

    def spoofed_entrypoint() -> object:
        return stage1._reserve_production_validation_run(forged_preparation)

    spoofed_entrypoint.__module__ = broader_smoke.__name__
    spoofed_entrypoint.__qualname__ = "execute_bounded_validation_evidence"
    with _expect_stage1_error("EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE"):
        spoofed_entrypoint()


def test_a_private_looking_registry_mutation_cannot_make_authority_current() -> None:
    before = stage1._production_registry_snapshot()
    fake_run: stage1.ValidationRun = object.__new__(cast(Any, stage1.ValidationRun))
    caller_registry: dict[object, object] = {fake_run: {"validation_run_id": "1" * 64}}
    assert caller_registry[fake_run]
    with _expect_stage1_error("VALIDATION_RUN_STALE"):
        stage1.validation_run_id(fake_run)
    assert stage1._production_registry_snapshot() == before


def test_a_component_anchor_rejects_monkeypatched_module_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = execution._issue_production_executor_implementation

    def replacement(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return object()

    issuers = stage1._ProductionComponentIssuers(
        executor_implementation=original,
        pytest_plan=validation._issue_production_pytest_plan_draft,
        pytest_runtime_validate=validation._validate_production_pytest_runtime,
        oracle_plan=oracle._issue_production_oracle_plan_draft,
        execution_plans=execution._issue_production_execution_plan_drafts,
        executor_invalidator=execution._invalidate_production_executor_implementation,
        executor_is_current=execution._production_executor_implementation_is_current,
        junit_cleanup=validation._cleanup_retained_junit_handle,
        junit_is_open=validation._retained_junit_handle_is_open,
        junit_is_cleaned=validation._retained_junit_handle_is_cleaned,
        anchors=(
            (
                execution,
                "_issue_production_executor_implementation",
                original,
                getattr(original, "__code__", None),
            ),
        ),
    )
    monkeypatch.setattr(execution, "_issue_production_executor_implementation", replacement)
    with _expect_stage1_error(
        "CALLABLE_IDENTITY_MISMATCH",
        "EXECUTION_SPECIFICATION_RELATION_MISMATCH",
    ):
        issuers.validate()


@pytest.mark.skip(
    reason="OUT_OF_SCOPE_TRUSTED_PROCESS_V1: retained closure-inspection demonstration"
)
def test_a_production_gate_and_registries_expose_no_python_closure_state() -> None:
    production_callables = (
        broader_smoke.execute_bounded_validation_evidence,
        stage1._require_production_preparation,
        stage1._reserve_production_validation_run,
        stage1._require_production_run,
        stage1._production_registry_snapshot,
        execution._require_production_executor_implementation_record,
        execution.executor_implementation_projection,
        execution.executor_implementation_identity,
    )
    for production_callable in production_callables:
        assert not hasattr(production_callable, "__closure__")
        assert not hasattr(production_callable, "__code__")
        assert not hasattr(production_callable, "__wrapped__")


@pytest.mark.parametrize(
    "dependency",
    (
        "executor_module",
        "json_encoder",
        "pytest_module",
        "pluggy_module",
        "pytest_plugin_module",
        "default_plugins",
        "sys_implementation",
    ),
)
def test_b_transitive_external_runtime_changes_are_rejected_before_preparation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    dependency: str,
) -> None:
    if dependency == "executor_module":
        monkeypatch.setattr(futures_thread, "_WorkItem", object)
    elif dependency == "json_encoder":

        def changed_encode(self: object, value: object) -> str:
            del self, value
            return "{}"

        monkeypatch.setattr(json.JSONEncoder, "encode", changed_encode)
    elif dependency in {"pytest_module", "pluggy_module", "pytest_plugin_module"}:
        module_name = {
            "pytest_module": "pytest",
            "pluggy_module": "pluggy",
            "pytest_plugin_module": "_pytest.mark",
        }[dependency]
        assert module_name in sys.modules
        monkeypatch.setitem(sys.modules, module_name, ModuleType(module_name))
    elif dependency == "default_plugins":
        config_module = sys.modules.get("_pytest.config")
        assert type(config_module) is ModuleType
        default_plugins = config_module.default_plugins
        assert type(default_plugins) is tuple
        monkeypatch.setattr(
            config_module,
            "default_plugins",
            (*default_plugins, "rde_forbidden_plugin"),
        )
    else:
        monkeypatch.setattr(sys.implementation, "cache_tag", "forged-stage1-cache-tag")
    before = stage1._production_registry_snapshot()
    with _expect_stage1_error("CALLABLE_IDENTITY_MISMATCH", "RUNTIME_IDENTITY_MISMATCH"):
        broader_smoke.execute_bounded_validation_evidence(
            tmp_path,
            validation_result=cast(Any, None),
            oracle_conformance_result=cast(Any, None),
            oracle_evidence_binding=cast(Any, None),
        )
    assert stage1._production_registry_snapshot() == before


@pytest.mark.parametrize(
    "attack",
    (
        "clean",
        "tracked_bytes",
        "index_checksum",
        "untracked_source",
        "root_module",
        "root_dist_info",
        "nested_cache_source",
        "message_tree",
        "duplicate_header_tree",
        "missing_loose_commit",
    ),
)
def test_b_direct_git_snapshot_fails_closed_without_subprocess(
    tmp_path: Path,
    attack: str,
) -> None:
    root, commit, root_tree = _synthetic_clean_git_repository(tmp_path)
    git_directory = root / ".git"
    if attack == "tracked_bytes":
        (root / "pyproject.toml").write_bytes(b"changed after indexing\n")
    elif attack == "index_checksum":
        index_path = git_directory / "index"
        corrupted = bytearray(index_path.read_bytes())
        corrupted[-1] ^= 1
        index_path.write_bytes(corrupted)
    elif attack == "untracked_source":
        (root / "tests" / "untracked_attack.py").write_text("ATTACK = True\n", encoding="utf-8")
    elif attack == "root_module":
        (root / "sitecustomize.py").write_text("ATTACK = True\n", encoding="utf-8")
    elif attack == "root_dist_info":
        (root / "forged_runtime-1.0.dist-info").mkdir()
    elif attack == "nested_cache_source":
        nested_cache = root / "tests" / "cache"
        nested_cache.mkdir()
        (nested_cache / "conftest.py").write_text("ATTACK = True\n", encoding="utf-8")
    elif attack in {"message_tree", "duplicate_header_tree"}:
        second_header = f"tree {'f' * 40}\n" if attack == "duplicate_header_tree" else ""
        message_line = f"tree {'f' * 40}\n" if attack == "message_tree" else ""
        commit_payload = (
            f"tree {root_tree}\n"
            f"{second_header}"
            "author Stage One <stage1@example.invalid> 0 +0000\n"
            "committer Stage One <stage1@example.invalid> 0 +0000\n"
            f"\nsynthetic clean snapshot\n{message_line}"
        ).encode("ascii")
        commit = _write_loose_git_object(git_directory, "commit", commit_payload)
        (git_directory / "HEAD").write_text(commit + "\n", encoding="ascii")
    elif attack == "missing_loose_commit":
        (git_directory / "objects" / commit[:2] / commit[2:]).unlink()

    if attack in {"clean", "message_tree"}:
        snapshot = stage1._current_git_snapshot(root)
        assert snapshot.commit == commit
        assert snapshot.root_tree == root_tree
        assert tuple(entry.path for entry in snapshot.entries) == ("pyproject.toml", "uv.lock")
        return
    with _expect_stage1_error("IMPLEMENTATION_IDENTITY_MISMATCH"):
        stage1._current_git_snapshot(root)


def test_b_git_snapshot_resolves_worktree_metadata_from_exact_common_directory(
    tmp_path: Path,
) -> None:
    root, commit, root_tree = _synthetic_clean_git_repository(tmp_path)
    common_directory = (tmp_path / "common.git").resolve()
    (root / ".git").rename(common_directory)
    worktree_directory = common_directory / "worktrees" / "stage1"
    worktree_directory.mkdir(parents=True)
    (common_directory / "HEAD").replace(worktree_directory / "HEAD")
    (common_directory / "index").replace(worktree_directory / "index")
    (worktree_directory / "commondir").write_text("../..\n", encoding="utf-8")
    (root / ".git").write_text(f"gitdir: {worktree_directory}\n", encoding="utf-8")

    snapshot = stage1._current_git_snapshot(root)

    assert snapshot.commit == commit
    assert snapshot.root_tree == root_tree
    assert stage1._resolve_git_common_directory(worktree_directory) == common_directory


@pytest.mark.parametrize(
    "attack",
    (
        "exact",
        "missing",
        "wrong_head",
        "wrong_commit",
        "wrong_tree",
        "wrong_lock",
        "wrong_interpreter",
        "wrong_base_interpreter",
        "wrong_runtime",
        "wrong_dependency",
        "extra_field",
        "noncanonical",
    ),
)
def test_b_external_bootstrap_manifest_is_exact_and_not_self_attested(
    tmp_path: Path,
    attack: str,
) -> None:
    root, _commit, _root_tree = _synthetic_clean_git_repository(tmp_path)
    snapshot = stage1._current_git_snapshot(root)
    context = stage1._fixture_layer0_context(implementation_seed="bootstrap-anchor")
    runtime = context.runtime
    runtime_identity = context.runtime_identity
    dependency_environment = (
        ("pluggy", "1.0", str(tmp_path.resolve()), "a" * 64),
        ("pytest", "1.0", str(tmp_path.resolve()), "b" * 64),
    )
    dependency_lock_sha256 = hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest()
    git_directory = stage1._resolve_git_directory(root)
    manifest_path = stage1._trusted_bootstrap_manifest_path(git_directory, snapshot.commit)
    manifest_path.parent.mkdir()
    expected = stage1._trusted_bootstrap_manifest_bytes(
        snapshot=snapshot,
        dependency_lock_sha256=dependency_lock_sha256,
        runtime=runtime,
        runtime_identity=runtime_identity,
        dependency_environment=dependency_environment,
    )
    attacked_snapshot = snapshot
    if attack != "missing":
        manifest = cast(dict[str, Any], json.loads(expected))
        if attack == "wrong_head":
            attacked_snapshot = replace(snapshot, commit="f" * 40)
        elif attack == "wrong_commit":
            manifest["implementation_commit"] = "e" * 40
        elif attack == "wrong_tree":
            manifest["implementation_root_tree"] = "d" * 40
        elif attack == "wrong_lock":
            manifest["dependency_lock_sha256"] = "c" * 64
        elif attack == "wrong_interpreter":
            cast(dict[str, object], manifest["interpreter"])["sha256"] = "9" * 64
        elif attack == "wrong_base_interpreter":
            cast(dict[str, object], manifest["base_interpreter"])["path"] = "wrong"
        elif attack == "wrong_runtime":
            manifest["runtime_identity"] = "8" * 64
        elif attack == "wrong_dependency":
            cast(list[dict[str, object]], manifest["dependency_environment"])[0][
                "installation_identity"
            ] = "7" * 64
        elif attack == "extra_field":
            manifest["caller_selected"] = True
        raw = (
            json.dumps(
                manifest,
                allow_nan=False,
                ensure_ascii=True,
                indent=2 if attack == "noncanonical" else None,
                separators=None if attack == "noncanonical" else (",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
        manifest_path.write_bytes(raw)

    def validation_call() -> None:
        stage1._validate_trusted_bootstrap_manifest(
            git_directory=git_directory,
            snapshot=attacked_snapshot,
            dependency_lock_sha256=dependency_lock_sha256,
            runtime=runtime,
            runtime_identity=runtime_identity,
            dependency_environment=dependency_environment,
        )

    if attack == "exact":
        validation_call()
    else:
        with _expect_stage1_error("IMPLEMENTATION_IDENTITY_MISMATCH"):
            validation_call()


def test_b_git_metadata_junction_is_rejected_before_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, _commit, _root_tree = _synthetic_clean_git_repository(tmp_path)
    original_is_junction = Path.is_junction

    def attacked_is_junction(path: Path) -> bool:
        return path.name == ".git" or original_is_junction(path)

    monkeypatch.setattr(Path, "is_junction", attacked_is_junction)
    with _expect_stage1_error("IMPLEMENTATION_IDENTITY_MISMATCH"):
        stage1._current_git_snapshot(root)


def test_b_gitfile_target_ancestor_junction_is_rejected_before_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, _commit, _root_tree = _synthetic_clean_git_repository(tmp_path)
    marker = root / ".git"
    linked_parent = tmp_path / "linked-parent"
    linked_parent.mkdir()
    metadata = linked_parent / "metadata.git"
    marker.rename(metadata)
    marker.write_text(f"gitdir: {metadata}\n", encoding="utf-8")
    original_is_junction = Path.is_junction

    def attacked_is_junction(path: Path) -> bool:
        return path.name == linked_parent.name or original_is_junction(path)

    monkeypatch.setattr(Path, "is_junction", attacked_is_junction)
    with _expect_stage1_error("IMPLEMENTATION_IDENTITY_MISMATCH"):
        stage1._current_git_snapshot(root)


@pytest.mark.skip(
    reason="OUT_OF_SCOPE_TRUSTED_PROCESS_V1: retained arbitrary monkeypatch demonstration"
)
@pytest.mark.parametrize(
    "dependency",
    (
        "builtins",
        "builtins_all",
        "builtins_any",
        "builtins_build_class",
        "builtins_sorted",
        "hashlib",
        "json",
        "lru_wrapper",
        "native_lru_wrapper",
        "runtime_cast",
        "mapping_proxy",
        "contextvar",
        "rlock",
        "path_class",
        "path_defaults",
        "context_manager_class",
        "platform",
        "platform_helper",
        "tempfile",
        "tempdir_cache",
    ),
)
def test_b_preseal_external_dependency_provenance_is_authenticated(
    monkeypatch: pytest.MonkeyPatch,
    dependency: str,
) -> None:
    invoked = False
    original_context_manager_class: Any = None
    if dependency == "builtins":
        monkeypatch.setattr(builtins, "compile", lambda *args, **kwargs: None)
    elif dependency == "builtins_all":
        monkeypatch.setattr(builtins, "all", lambda _: True)
    elif dependency == "builtins_any":
        monkeypatch.setattr(builtins, "any", lambda _: False)
    elif dependency == "builtins_build_class":
        monkeypatch.setattr(builtins, "__build_class__", lambda *args, **kwargs: object)
    elif dependency == "builtins_sorted":
        monkeypatch.setattr(builtins, "sorted", lambda _: [])
    elif dependency == "hashlib":
        monkeypatch.setattr(hashlib, "sha256", lambda _: object())
    elif dependency == "json":
        monkeypatch.setattr(json, "dumps", lambda _: "{}")
    elif dependency in {"lru_wrapper", "native_lru_wrapper"}:

        def poison_wrapper(*args: object, **kwargs: object) -> object:
            nonlocal invoked
            del args, kwargs
            invoked = True
            return object()

        target = functools if dependency == "lru_wrapper" else _functools
        monkeypatch.setattr(target, "_lru_cache_wrapper", poison_wrapper)
    elif dependency == "runtime_cast":

        def poison_cast(value: object) -> object:
            nonlocal invoked
            invoked = True
            return value

        monkeypatch.setattr(stage1, "_runtime_cast", poison_cast)
    elif dependency == "mapping_proxy":
        monkeypatch.setattr(stage1, "MappingProxyType", dict)
    elif dependency == "contextvar":
        monkeypatch.setattr(stage1, "ContextVar", object)
    elif dependency == "rlock":
        monkeypatch.setattr(threading, "_CRLock", object)
    elif dependency == "path_class":
        monkeypatch.setattr(pathlib, "Path", object)
        monkeypatch.setattr(stage1, "Path", object)
    elif dependency == "path_defaults":
        defaults = Path.relative_to.__kwdefaults__
        assert defaults is not None
        monkeypatch.setitem(defaults, "walk_up", True)
    elif dependency == "context_manager_class":
        original_context_manager_class = contextlib._GeneratorContextManager
        contextlib._GeneratorContextManager = object  # type: ignore[assignment,misc]
    elif dependency == "platform":
        monkeypatch.setattr(platform, "python_version", lambda: "forged")
    elif dependency == "platform_helper":
        monkeypatch.setattr(platform, "_sys_version", lambda *_: ("CPython", "3.12.13"))
    elif dependency == "tempfile":
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(repository_root()))
    else:
        monkeypatch.setattr(tempfile, "tempdir", str(repository_root()))
    try:
        with pytest.raises(
            RuntimeError,
            match="substituted|boundary changed|caller-overridden|differ|forged",
        ):
            stage1._validate_external_runtime_provenance()
    finally:
        if original_context_manager_class is not None:
            contextlib._GeneratorContextManager = (  # type: ignore[misc]
                original_context_manager_class
            )
    if dependency in {"lru_wrapper", "native_lru_wrapper", "runtime_cast"}:
        assert not invoked
    module_source = Path(stage1.__file__).read_text(encoding="utf-8")
    assert module_source.index("\n_validate_external_runtime_provenance()\n") < module_source.index(
        "def _install_production_component_source_authority"
    )
    installer = module_source.split("def _install_current_production_preparer", 1)[1]
    assert installer.index("_validate_external_runtime_provenance()") < installer.index(
        "trusted_module = sys.modules[__name__]"
    )


@pytest.mark.skip(
    reason="OUT_OF_SCOPE_TRUSTED_PROCESS_V1: retained typing.cast poisoning demonstration"
)
def test_b_runtime_cast_never_dispatches_through_typing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoked = False

    def poison_cast(_target: object, value: object) -> object:
        nonlocal invoked
        invoked = True
        return value

    monkeypatch.setattr(typing, "cast", poison_cast)
    stage1._validate_external_runtime_provenance()
    assert not invoked
    assert not hasattr(stage1._runtime_cast, "__wrapped__")
    assert not hasattr(stage1._runtime_cast, "__code__")
    assert not hasattr(stage1._runtime_cast, "__closure__")
    source = Path(stage1.__file__).read_text(encoding="utf-8")
    assert "SupportsIndex, cast" not in source
    assert source.index("_validate_external_runtime_provenance()") < source.index("@dataclass")


@pytest.mark.parametrize(
    "attack",
    (
        "clean",
        "visible_code",
        "foreign_globals",
        "generated_dataclass",
        "dataclass_field_flags",
        "foreign_class_base",
        "opaque_source",
        "protocol_checkpoint",
        "protocol_hashlib",
    ),
)
def test_b_loaded_project_and_opaque_code_reconciles_to_trusted_bytes(
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    root = repository_root().resolve(strict=True)
    trusted_blobs: dict[str, bytes] = {}
    for module_name, module in tuple(sys.modules.items()):
        if not (
            module_name == "research_decision_engine"
            or (module_name.startswith("research_decision_engine.") and type(module) is ModuleType)
        ):
            continue
        source_name = module.__file__
        assert isinstance(source_name, str)
        source_path = Path(source_name)
        if source_path.suffix == ".pyc":
            source_path = source_path.with_suffix(".py")
        source_path = source_path.resolve(strict=True)
        trusted_blobs[source_path.relative_to(root).as_posix()] = source_path.read_bytes()

    if attack == "visible_code":

        def replacement(path: str) -> bool:
            del path
            return True

        monkeypatch.setattr(stage1._implementation_path_is_scoped, "__code__", replacement.__code__)
    elif attack == "foreign_globals":

        def replacement(path: str) -> bool:
            del path
            return True

        monkeypatch.setattr(stage1, "_implementation_path_is_scoped", replacement)
    elif attack == "generated_dataclass":
        generated = stage1.FileProjection.__init__
        monkeypatch.setattr(
            generated,
            "__code__",
            generated.__code__.replace(co_filename="<stage1-generated-attack>"),
        )
    elif attack == "dataclass_field_flags":
        monkeypatch.setattr(stage1._GitSnapshot.__dataclass_fields__["commit"], "compare", False)
    elif attack == "foreign_class_base":

        class ForeignProtocolError(RuntimeError):
            pass

        ForeignProtocolError.__module__ = broader_protocol.__name__
        ForeignProtocolError.__name__ = "ProtocolError"
        ForeignProtocolError.__qualname__ = "ProtocolError"
        monkeypatch.setattr(broader_protocol, "ProtocolError", ForeignProtocolError)
    elif attack == "opaque_source":
        monkeypatch.delattr(
            execution._issue_production_executor_implementation, "_rde_opaque_source"
        )
    elif attack == "protocol_checkpoint":
        forged_checkpoint = "f" * 40
        monkeypatch.setattr(broader_protocol, "PROTOCOL_CHECKPOINT", forged_checkpoint)
        monkeypatch.setattr(stage1, "PROTOCOL_CHECKPOINT", forged_checkpoint)
    elif attack == "protocol_hashlib":
        forged_hashlib = ModuleType("hashlib")
        forged_hashlib.sha256 = hashlib.sha256  # type: ignore[attr-defined]
        monkeypatch.setattr(broader_protocol, "hashlib", forged_hashlib)

    if attack == "clean":
        stage1._validate_loaded_implementation_bytes(root=root, trusted_blobs=trusted_blobs)
    else:
        with _expect_stage1_error("IMPLEMENTATION_IDENTITY_MISMATCH"):
            stage1._validate_loaded_implementation_bytes(root=root, trusted_blobs=trusted_blobs)


def test_b_executor_identity_is_exact_stable_and_source_bound() -> None:
    first = _canonical_plan_set()
    first_projection = execution._fixture_executor_implementation_projection(
        first.executor_implementation
    )
    identity = execution._fixture_executor_implementation_identity(first.executor_implementation)
    assert first_projection.callable.module_name == execution.__name__
    assert first_projection.callable.qualname == "execute_deterministic_map"
    assert first_projection.implementation_tree_sha256 == (
        first.context.implementation.implementation_tree_sha256
    )
    stage1._reset_fixture_registries()
    second = _canonical_plan_set()
    assert (
        execution._fixture_executor_implementation_identity(second.executor_implementation)
        == identity
    )


def test_b_replaced_or_wrapped_executor_module_global_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = stage1._fixture_layer0_context()
    run = stage1._issue_fixture_validation_run()

    def wrapper(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return None

    monkeypatch.setattr(execution, "execute_deterministic_map", wrapper)
    with _expect_stage1_error("EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE"):
        execution._issue_fixture_executor_implementation(context, run)


def test_b_changed_executor_code_object_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    context = stage1._fixture_layer0_context()
    run = stage1._issue_fixture_validation_run()
    trusted = execution.execute_deterministic_map

    def replacement(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return None

    monkeypatch.setattr(trusted, "__code__", replacement.__code__)
    with _expect_stage1_error("EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE"):
        execution._issue_fixture_executor_implementation(context, run)


def test_b_changed_executor_source_resolution_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = stage1._fixture_layer0_context()
    run = stage1._issue_fixture_validation_run()
    monkeypatch.setattr(
        execution.inspect,  # type: ignore[attr-defined]
        "getsourcefile",
        lambda _: None,
    )
    with _expect_stage1_error(
        "CALLABLE_IDENTITY_MISMATCH",
        "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
    ):
        execution._issue_fixture_executor_implementation(context, run)


def test_b_replaced_role_callable_and_arbitrary_callable_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = broader_smoke._execute_job

    def wrapper(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return None

    monkeypatch.setattr(broader_smoke, "_execute_job", wrapper)
    with _expect_stage1_error("CALLABLE_IDENTITY_MISMATCH"):
        execution._verified_job_callable_projection("primary_smoke")

    monkeypatch.setattr(broader_smoke, "_execute_job", original)
    context = stage1._fixture_layer0_context()
    run = stage1._issue_fixture_validation_run()
    implementation = execution._issue_fixture_executor_implementation(context, run)
    with _expect_stage1_error(
        "CALLABLE_IDENTITY_MISMATCH",
        "EXECUTION_SPECIFICATION_RELATION_MISMATCH",
    ):
        execution._issue_fixture_execution_specification(
            context=context,
            validation_run=run,
            executor_implementation=implementation,
            function=wrapper,
            jobs=_smoke_jobs(),
            role="primary_smoke",
        )


def test_b_replaced_oracle_global_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    context = stage1._fixture_layer0_context()
    run = stage1._issue_fixture_validation_run()

    def wrapper(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return None

    monkeypatch.setattr(oracle, "execute_oracle_conformance", wrapper)
    with _expect_stage1_error("ORACLE_PLAN_ID_MISMATCH"):
        oracle._build_fixture_oracle_plan_projection(context=context, validation_run=run)


@pytest.mark.parametrize("attack", ("callable", "source", "implementation_tree"))
def test_b_detached_callable_and_implementation_identity_attacks_fail(attack: str) -> None:
    projection = _primary_projection(_canonical_plan_set())
    if attack == "callable":
        changed = replace(projection, callable_identity="f" * 64)
    elif attack == "source":
        changed_source = replace(projection.callable.source, sha256="f" * 64)
        changed_callable = replace(projection.callable, source=changed_source)
        changed = replace(projection, callable=changed_callable)
    else:
        changed_implementation = replace(
            projection.executor_implementation,
            implementation_tree_sha256="f" * 64,
        )
        changed = replace(projection, executor_implementation=changed_implementation)
    with _expect_stage1_error(
        "CALLABLE_IDENTITY_MISMATCH",
        "EXECUTOR_IMPLEMENTATION_IDENTITY_MISMATCH",
    ):
        execution._fixture_execution_specification_id_from_projection(changed)


def test_b_stale_executor_implementation_is_unreadable() -> None:
    bundle = _canonical_plan_set()
    execution._invalidate_fixture_executor_implementation(bundle.executor_implementation)
    with _expect_stage1_error("EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE"):
        execution._fixture_executor_implementation_identity(bundle.executor_implementation)
    with _expect_stage1_error("EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE"):
        execution._fixture_executor_implementation_projection(bundle.executor_implementation)


def test_c_validation_run_is_exact_fresh_and_not_caller_supplied() -> None:
    first = stage1._issue_fixture_validation_run()
    second = stage1._issue_fixture_validation_run()
    first_id = stage1._fixture_validation_run_id(first)
    second_id = stage1._fixture_validation_run_id(second)
    assert len(first_id) == 64
    assert set(first_id) <= set("0123456789abcdef")
    assert first_id != second_id
    with _expect_stage1_error("VALIDATION_RUN_STALE"):
        stage1._fixture_validation_run_id(cast(Any, first_id))
    with _expect_stage1_error("VALIDATION_RUN_STALE"):
        stage1.validation_run_id(cast(Any, first))


@pytest.mark.parametrize("state", ("reserved", "authority_bound"))
def test_c_reserved_and_bound_run_id_collisions_are_rejected(
    state: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if state == "authority_bound":
        bundle = _canonical_plan_set()
        stage1._issue_fixture_authority(
            context=bundle.context,
            validation_run=bundle.run,
            plans=bundle.plans,
        )
        run = bundle.run
    else:
        run = stage1._issue_fixture_validation_run()
    repeated = bytes.fromhex(stage1._fixture_validation_run_id(run))
    monkeypatch.setattr(secrets, "token_bytes", lambda _: repeated)
    with _expect_stage1_error("VALIDATION_RUN_COLLISION"):
        stage1._issue_fixture_validation_run()


def test_c_rng_monkeypatch_cannot_authorize_a_production_component(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chosen = b"\x11" * 32
    monkeypatch.setattr(secrets, "token_bytes", lambda _: chosen)
    assert not hasattr(stage1, "_make_production_registry")
    assert not hasattr(execution, "_make_production_executor_implementation_registry")
    assert not hasattr(execution, "_make_executor_implementation_registry")
    module_source = Path(stage1.__file__).read_text(encoding="utf-8")
    production_registry_source = module_source.split(
        "def _make_production_registry",
        1,
    )[1].split("\n\n(\n    _require_production_preparation", 1)[0]
    assert "entropy = os.urandom" in production_registry_source
    assert "secrets.token_bytes" not in production_registry_source
    before = stage1._production_registry_snapshot()
    preparation: stage1._ProductionPreparationCapability = object.__new__(
        cast(Any, stage1._ProductionPreparationCapability)
    )
    run: stage1.ValidationRun = object.__new__(cast(Any, stage1.ValidationRun))
    with _expect_stage1_error("EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE"):
        execution._issue_production_executor_implementation(
            preparation,
            stage1._fixture_layer0_context(),
            run,
            lambda _: None,
            lambda _: None,
        )
    assert stage1._production_registry_snapshot() == before


def test_c_production_cleanup_scope_starts_before_run_reservation() -> None:
    source = inspect.getsource(stage1._prepare_production_stage1)
    cleanup_scope = source.index("try:")
    assert cleanup_scope < source.index("consume_preparation(preparation, session_token)")
    assert cleanup_scope < source.index("validation_run = reserve_run(preparation)")
    assert source.index(
        "owned_control_directory: _OwnedControlDirectory | None = None"
    ) < source.index("try:")
    assert source.index("junit_handle: object | None = None") < source.index("try:")
    assert "abort = collaborators.abort" in source
    assert "for _ in range(3):" in source
    assert source.count("abort(") == 1
    assert "local_control_directory=(" in source
    assert "local_junit_handle=(" in source
    assert "local_executor_implementation=executor_implementation" in source
    assert "executor_invalidator=invalidate_executor" in source
    assert "junit_cleanup=cleanup_junit" in source
    control_section = source.split("def retain_provisional_control_directory", 1)[1]
    assert control_section.index("transition_physical_resource(") < control_section.index(
        'if failure_point == "after_control_directory_creation_before_ledger"'
    )
    executor_section = source.split("def allocate_executor_capability", 1)[1]
    assert executor_section.index("allocate_executor_implementation(") < executor_section.index(
        "executor_implementation = issue_executor_implementation("
    )
    assert executor_section.index("confirm_executor_implementation(") < executor_section.index(
        'if failure_point == "after_executor_issuance_before_ledger"'
    )
    junit_section = source.split("def retain_junit_handle", 1)[1]
    assert junit_section.index("transition_physical_resource(") < junit_section.index(
        'if failure_point == "after_junit_ownership_before_ledger"'
    )


def test_c_control_directory_authority_rejects_direct_creation_and_temp_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixed_temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    before_fixed = frozenset(fixed_temp_root.glob("rde-p2-stage1-*"))
    before_override = frozenset(tmp_path.iterdir())
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    forged: stage1._ProductionPreparationCapability = object.__new__(
        cast(Any, stage1._ProductionPreparationCapability)
    )
    with _expect_stage1_error("EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE"):
        stage1._create_owned_control_directory(forged)
    assert frozenset(fixed_temp_root.glob("rde-p2-stage1-*")) == before_fixed
    assert frozenset(tmp_path.iterdir()) == before_override


def test_c_forged_control_directory_record_cannot_remove_an_unissued_directory(
    tmp_path: Path,
) -> None:
    unrelated = tmp_path / "rde-p2-stage1-unissued"
    unrelated.mkdir()
    status = unrelated.stat(follow_symlinks=False)
    forged = stage1._OwnedControlDirectory(
        path=unrelated,
        device_id=status.st_dev,
        file_id=status.st_ino,
    )
    with _expect_stage1_error("PYTEST_PLAN_ID_MISMATCH"):
        stage1._remove_empty_owned_control_directory(forged)
    assert unrelated.exists()
    unrelated.rmdir()


def test_d_exact_canonical_four_job_sets_and_configurations_succeed() -> None:
    bundle = _canonical_plan_set()
    projections = tuple(
        execution._fixture_execution_specification_projection(plan) for plan in bundle.plans[2:]
    )
    assert tuple(item.role for item in projections) == (
        "primary_smoke",
        "altered_order_replay",
        "fixture_primary",
        "fixture_replay",
    )
    assert tuple(len(item.submitted_jobs) for item in projections) == (384, 384, 252, 252)
    assert tuple(item.submitted_jobs for item in projections) == tuple(
        execution._canonical_production_submitted_jobs(role)
        for role in execution._P2_EXECUTION_ROLE_ORDER
    )
    assert len({item.executor_implementation_identity for item in projections}) == 1
    assert tuple(item.worker_count for item in projections) == (1, 2, 1, 1)
    assert tuple(item.executor_kind for item in projections) == (
        "serial",
        "thread_pool",
        "serial",
        "serial",
    )


def test_d_supported_parent_pytest_environment_cannot_change_closed_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = stage1._fixture_layer0_context()
    run = stage1._issue_fixture_validation_run()
    baseline = _pytest_projection(context, run)
    monkeypatch.setenv("PYTEST_ADDOPTS", "--maxfail=1 -p arbitrary_plugin")
    monkeypatch.setenv("PYTEST_PLUGINS", "arbitrary_plugin")
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "0")
    observed = _pytest_projection(context, run)
    assert observed == baseline
    controlled = {row.name: (row.action, row.value) for row in observed.controlled_environment}
    assert controlled["PYTEST_ADDOPTS"] == ("unset", None)
    assert controlled["PYTEST_PLUGINS"] == ("unset", None)
    assert controlled["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == ("set", "1")


@pytest.mark.parametrize("attack", ("same_count", "reordered", "wrong_callable"))
def test_d_live_arbitrary_jobs_order_and_role_callable_are_rejected(attack: str) -> None:
    context = stage1._fixture_layer0_context()
    run = stage1._issue_fixture_validation_run()
    implementation = execution._issue_fixture_executor_implementation(context, run)
    jobs = _smoke_jobs()
    function: Callable[..., object] = broader_smoke._execute_job
    if attack == "same_count":
        first = jobs[0]
        jobs = ((f"{first[0]}-attacked", *first[1:]), *jobs[1:])
    elif attack == "reordered":
        jobs = tuple(reversed(jobs))
    else:
        function = broader_conformance._execute_run_job
    with _expect_stage1_error(
        "CALLABLE_IDENTITY_MISMATCH",
        "EXECUTION_SUBMITTED_JOBS_MISMATCH",
        "EXECUTION_SPECIFICATION_RELATION_MISMATCH",
    ):
        execution._issue_fixture_execution_specification(
            context=context,
            validation_run=run,
            executor_implementation=implementation,
            function=function,
            jobs=jobs,
            role="primary_smoke",
        )


@pytest.mark.parametrize(
    "attack",
    ("worker", "scheduling", "delivery", "executor_kind", "timeout"),
)
def test_d_wrong_closed_configuration_is_rejected(attack: str) -> None:
    projection = _primary_projection(_canonical_plan_set())
    if attack == "worker":
        changed = replace(projection, worker_count=2)
    elif attack == "scheduling":
        changed = replace(projection, scheduling_mode="attacked")
    elif attack == "delivery":
        changed = replace(projection, result_delivery_mode="completion_order")
    elif attack == "executor_kind":
        changed = replace(projection, executor_kind="thread_pool")
    else:
        changed = replace(projection, timeout_ms=1)
    with _expect_stage1_error("EXECUTION_SPECIFICATION_RELATION_MISMATCH"):
        execution._fixture_execution_specification_id_from_projection(changed)


@pytest.mark.parametrize(
    "attack",
    ("arm_order", "seed", "budget", "world", "submission_index", "scope"),
)
def test_d_wrong_job_and_scope_relations_are_rejected(attack: str) -> None:
    projection = _primary_projection(_canonical_plan_set())
    if attack == "scope":
        changed = replace(
            projection,
            execution_purpose="production_conformance",
            normalized_execution_namespace=(f"{stage1.STUDY_ID}/production/production_conformance"),
        )
    else:
        first = projection.submitted_jobs[0]
        job = first.projection
        if attack == "arm_order":
            job = replace(job, arm=replace(job.arm, arm_order=job.arm.arm_order + 1))
        elif attack == "seed":
            job = replace(job, seed=job.seed + 1)
        elif attack == "budget":
            job = replace(job, budget="f64:4000000000000000")
        elif attack == "world":
            job = replace(job, world_id=f"{job.world_id}-attacked")
        else:
            job = replace(job, submission_index=99)
        submitted = replace(
            first,
            projection=job,
            submitted_job_id=execution.submitted_job_id(job),
        )
        changed = replace(
            projection,
            submitted_jobs=(submitted, *projection.submitted_jobs[1:]),
        )
    with _expect_stage1_error(
        "EXECUTION_SPECIFICATION_RELATION_MISMATCH",
        "EXECUTION_SUBMITTED_JOBS_MISMATCH",
    ):
        execution._fixture_execution_specification_id_from_projection(changed)


def test_d_schema_contains_ordered_jobs_and_no_aggregate_job_hash() -> None:
    projection = _primary_projection(_canonical_plan_set())
    mapping = projection.as_dict()
    assert "submitted_jobs" in mapping
    assert "submitted_jobs_sha256" not in mapping
    assert not hasattr(projection, "submitted_jobs_sha256")
    assert projection.expected_completion.submitted_job_count == len(projection.submitted_jobs)
    source = inspect.getsource(execution.ExecutionSpecificationProjection)
    assert "submitted_jobs_sha256" not in source
    assert "submission_order_sha256" not in source


def test_e_retained_junit_handle_is_open_exclusive_uncopyable_and_cleaned(
    tmp_path: Path,
) -> None:
    control_directory = (tmp_path / "stage1-control").resolve()
    control_directory.mkdir()
    destination = control_directory / "pytest-junit.xml"
    handle = validation._create_guarded_junit_file(
        destination,
        initial_bytes=b"j" * 32,
    )
    try:
        assert validation._retained_junit_handle_is_open(handle)
        assert handle.destination_path == destination.resolve(strict=True)
        assert handle.control_directory == control_directory
        assert handle.initial_byte_count == 32
        assert destination.read_bytes() == b"j" * 32
        with pytest.raises(validation.PytestValidationError):
            validation._create_guarded_junit_file(destination, initial_bytes=b"k" * 32)
        operations: tuple[Callable[[object], object], ...] = (
            copy.copy,
            copy.deepcopy,
            pickle.dumps,
        )
        for operation in operations:
            with pytest.raises(TypeError):
                operation(handle)
    finally:
        validation._cleanup_retained_junit_handle(
            handle,
            remove_control_directory=True,
        )
    assert not destination.exists()
    assert not control_directory.exists()
    assert not validation._retained_junit_handle_is_open(handle)
    validation._cleanup_retained_junit_handle(
        handle,
        remove_control_directory=True,
    )


def test_e_retained_junit_partial_cleanup_preserves_central_directory_owner(
    tmp_path: Path,
) -> None:
    control_directory = (tmp_path / "split-owner-control").resolve()
    control_directory.mkdir()
    status = control_directory.stat(follow_symlinks=False)
    destination = control_directory / "pytest-junit.xml"
    handle = validation._create_guarded_junit_file(
        destination,
        initial_bytes=b"s" * 32,
        expected_control_directory_identity=(status.st_dev, status.st_ino),
    )
    try:
        validation._cleanup_retained_junit_handle(
            handle,
            remove_control_directory=False,
        )
        assert validation._retained_junit_handle_is_cleaned(handle)
        assert not validation._retained_junit_handle_is_open(handle)
        assert not destination.exists()
        assert control_directory.is_dir()
        assert tuple(control_directory.iterdir()) == ()
        validation._cleanup_retained_junit_handle(
            handle,
            remove_control_directory=False,
        )
        assert control_directory.is_dir()
    finally:
        if destination.exists():
            validation._cleanup_retained_junit_handle(
                handle,
                remove_control_directory=False,
            )
        if control_directory.exists():
            control_directory.rmdir()


def test_e_junit_descriptor_is_provisionally_owned_before_identity_work(
    tmp_path: Path,
) -> None:
    control_directory = (tmp_path / "provisional-junit-control").resolve()
    control_directory.mkdir()
    directory_status = control_directory.stat(follow_symlinks=False)
    destination = control_directory / "pytest-junit.xml"
    retained: list[object] = []
    promoted: list[object] = []

    def retain_provisional(handle: object) -> None:
        retained.append(handle)
        raise RuntimeError("injected immediately after provisional JUnit retention")

    with pytest.raises(RuntimeError, match="immediately after provisional JUnit retention"):
        validation._create_guarded_junit_file(
            destination,
            initial_bytes=b"p" * 32,
            expected_control_directory_identity=(
                directory_status.st_dev,
                directory_status.st_ino,
            ),
            retain_provisional_handle=cast(Any, retain_provisional),
            retain_handle=cast(
                Any, lambda provisional, handle: promoted.append((provisional, handle))
            ),
        )

    assert len(retained) == 1
    assert promoted == []
    provisional = retained[0]
    assert validation._retained_junit_handle_is_cleaned(provisional)
    assert not validation._retained_junit_handle_is_open(provisional)
    assert not destination.exists()
    assert control_directory.is_dir()
    validation._cleanup_retained_junit_handle(
        provisional,
        remove_control_directory=False,
    )
    control_directory.rmdir()


def test_e_junit_no_replace_race_never_removes_the_unowned_winner(
    tmp_path: Path,
) -> None:
    control_directory = (tmp_path / "junit-no-replace-race").resolve()
    control_directory.mkdir()
    directory_status = control_directory.stat(follow_symlinks=False)
    destination = control_directory / "pytest-junit.xml"
    unowned_bytes = b"ordinary concurrent winner"
    retained: list[object] = []

    def retain_provisional(handle: object) -> None:
        destination.write_bytes(unowned_bytes)
        retained.append(handle)

    with pytest.raises(
        validation.PytestValidationError,
        match="securely pre-create retained pytest JUnit output",
    ):
        validation._create_guarded_junit_file(
            destination,
            initial_bytes=b"r" * 32,
            expected_control_directory_identity=(
                directory_status.st_dev,
                directory_status.st_ino,
            ),
            retain_provisional_handle=cast(Any, retain_provisional),
            retain_handle=cast(Any, lambda provisional, handle: None),
        )

    assert len(retained) == 1
    provisional = retained[0]
    assert destination.read_bytes() == unowned_bytes
    assert not validation._retained_junit_handle_is_cleaned(provisional)
    with pytest.raises(
        validation.PytestValidationError,
        match="ownership is ambiguous after failed no-replace acquisition",
    ):
        validation._cleanup_retained_junit_handle(
            provisional,
            remove_control_directory=False,
        )
    assert destination.read_bytes() == unowned_bytes

    destination.unlink()
    validation._cleanup_retained_junit_handle(
        provisional,
        remove_control_directory=False,
    )
    assert validation._retained_junit_handle_is_cleaned(provisional)
    control_directory.rmdir()


def test_e_junit_open_return_interruption_remains_centrally_cleanable(
    tmp_path: Path,
) -> None:
    control_directory = (tmp_path / "junit-open-return-interruption").resolve()
    control_directory.mkdir()
    directory_status = control_directory.stat(follow_symlinks=False)
    destination = control_directory / "pytest-junit.xml"
    retained: list[object] = []
    create_code = cast(
        tuple[object, object, object, CodeType],
        cast(Any, validation._create_guarded_junit_file)._rde_opaque_source,
    )[3]
    interrupted = False
    previous_profile = sys.getprofile()

    def interrupt_open_return(frame: FrameType, event: str, arg: object) -> None:
        nonlocal interrupted
        if (
            not interrupted
            and frame.f_code is create_code
            and event == "c_return"
            and arg is builtins.open
        ):
            interrupted = True
            raise KeyboardInterrupt("injected at retained JUnit open return")
        if previous_profile is not None:
            previous_profile(frame, cast(Any, event), arg)

    sys.setprofile(interrupt_open_return)
    try:
        with pytest.raises(KeyboardInterrupt, match="retained JUnit open return"):
            validation._create_guarded_junit_file(
                destination,
                initial_bytes=b"a" * 32,
                expected_control_directory_identity=(
                    directory_status.st_dev,
                    directory_status.st_ino,
                ),
                retain_provisional_handle=cast(Any, retained.append),
                retain_handle=cast(Any, lambda provisional, handle: None),
            )
    finally:
        sys.setprofile(previous_profile)

    assert interrupted
    assert len(retained) == 1
    provisional = retained[0]
    assert validation._retained_junit_handle_is_cleaned(provisional)
    assert not destination.exists()
    validation._cleanup_retained_junit_handle(
        provisional,
        remove_control_directory=False,
    )
    control_directory.rmdir()


def test_e_junit_partial_promotion_interruption_reconciles_provisional_owner(
    tmp_path: Path,
) -> None:
    control_directory = (tmp_path / "junit-partial-promotion").resolve()
    control_directory.mkdir()
    directory_status = control_directory.stat(follow_symlinks=False)
    destination = control_directory / "pytest-junit.xml"
    retained: list[object] = []
    create_code = cast(
        tuple[object, object, object, CodeType],
        cast(Any, validation._create_guarded_junit_file)._rde_opaque_source,
    )[3]
    source_lines = Path(create_code.co_filename).read_text(encoding="utf-8").splitlines()
    interruption_line = next(
        line_number
        for _, _, line_number in create_code.co_lines()
        if line_number is not None
        and source_lines[line_number - 1].strip()
        == "issued_states[retained_handle] = retained_state"
    )
    interrupted = False
    previous_trace = sys.gettrace()

    def interrupt_partial_promotion(frame: FrameType, event: str, arg: object) -> Any:
        nonlocal interrupted
        if (
            not interrupted
            and frame.f_code is create_code
            and event == "line"
            and frame.f_lineno == interruption_line
        ):
            interrupted = True
            raise KeyboardInterrupt("injected during retained JUnit promotion")
        if previous_trace is not None:
            previous_trace(frame, cast(Any, event), arg)
        return interrupt_partial_promotion

    sys.settrace(interrupt_partial_promotion)
    try:
        with pytest.raises(KeyboardInterrupt, match="retained JUnit promotion"):
            validation._create_guarded_junit_file(
                destination,
                initial_bytes=b"i" * 32,
                expected_control_directory_identity=(
                    directory_status.st_dev,
                    directory_status.st_ino,
                ),
                retain_provisional_handle=cast(Any, retained.append),
                retain_handle=cast(Any, lambda provisional, handle: None),
            )
    finally:
        sys.settrace(previous_trace)

    assert interrupted
    assert len(retained) == 1
    provisional = retained[0]
    assert validation._retained_junit_handle_is_cleaned(provisional)
    assert not destination.exists()
    validation._cleanup_retained_junit_handle(
        provisional,
        remove_control_directory=False,
    )
    control_directory.rmdir()


@pytest.mark.parametrize(
    "callback_point",
    (
        "begin_acquisition",
        "acquisition_checkpoint",
        "retain_provisional",
        "retained_checkpoint",
        "retain_handle",
        "cancel_acquisition",
    ),
)
def test_e_junit_central_callbacks_never_hold_the_component_lock(
    tmp_path: Path,
    callback_point: str,
) -> None:
    control_directory = (tmp_path / f"junit-lock-order-{callback_point}").resolve()
    control_directory.mkdir()
    existing = validation._create_guarded_junit_file(
        control_directory / "existing.xml",
        initial_bytes=b"l" * 32,
    )
    candidate: object | None = None
    observed_errors: list[BaseException] = []

    def require_component_lock_released() -> None:
        completed = threading.Event()

        def observe_existing() -> None:
            try:
                assert validation._retained_junit_handle_is_open(existing)
            except BaseException as error:
                observed_errors.append(error)
            finally:
                completed.set()

        observer = threading.Thread(target=observe_existing, daemon=True)
        observer.start()
        assert completed.wait(2), "central callback ran while holding the JUnit component lock"
        observer.join(2)
        assert not observer.is_alive()
        assert observed_errors == []

    def callback(name: str) -> None:
        if callback_point == name:
            require_component_lock_released()

    def acquisition_checkpoint() -> None:
        callback("acquisition_checkpoint")
        if callback_point == "cancel_acquisition":
            raise OSError("injected cancellation-path lock-order check")

    try:
        if callback_point == "cancel_acquisition":
            with pytest.raises(
                validation.PytestValidationError,
                match="securely pre-create retained pytest JUnit output",
            ):
                validation._create_guarded_junit_file(
                    control_directory / "candidate.xml",
                    initial_bytes=b"c" * 32,
                    retain_provisional_handle=cast(Any, lambda handle: None),
                    retain_handle=cast(Any, lambda provisional, handle: None),
                    begin_acquisition=lambda: callback("begin_acquisition"),
                    cancel_acquisition=lambda: callback("cancel_acquisition"),
                    acquisition_checkpoint=acquisition_checkpoint,
                    retained_checkpoint=lambda: callback("retained_checkpoint"),
                )
        else:
            candidate = validation._create_guarded_junit_file(
                control_directory / "candidate.xml",
                initial_bytes=b"c" * 32,
                retain_provisional_handle=cast(Any, lambda handle: callback("retain_provisional")),
                retain_handle=cast(Any, lambda provisional, handle: callback("retain_handle")),
                begin_acquisition=lambda: callback("begin_acquisition"),
                cancel_acquisition=lambda: callback("cancel_acquisition"),
                acquisition_checkpoint=acquisition_checkpoint,
                retained_checkpoint=lambda: callback("retained_checkpoint"),
            )
            assert validation._retained_junit_handle_is_open(candidate)
    finally:
        if candidate is not None:
            validation._cleanup_retained_junit_handle(
                candidate,
                remove_control_directory=False,
            )
        validation._cleanup_retained_junit_handle(
            existing,
            remove_control_directory=False,
        )
        assert tuple(control_directory.iterdir()) == ()
        control_directory.rmdir()


def test_e_provisional_junit_identity_retry_retains_cleanup_authority(
    tmp_path: Path,
) -> None:
    control_directory = (tmp_path / "provisional-identity-retry").resolve()
    control_directory.mkdir()
    directory_status = control_directory.stat(follow_symlinks=False)
    destination = control_directory / "pytest-junit.xml"
    retained: list[object] = []

    def retain_provisional(handle: object) -> None:
        retained.append(handle)

    def retained_checkpoint() -> None:
        raise RuntimeError("injected after provisional retention")

    with (
        cast(Any, validation._provisional_junit_identity_failure_scope(3)),
        pytest.raises(RuntimeError, match="after provisional retention"),
    ):
        validation._create_guarded_junit_file(
            destination,
            initial_bytes=b"u" * 32,
            expected_control_directory_identity=(
                directory_status.st_dev,
                directory_status.st_ino,
            ),
            retain_provisional_handle=cast(Any, retain_provisional),
            retain_handle=cast(Any, lambda provisional, handle: None),
            begin_acquisition=lambda: None,
            cancel_acquisition=lambda: None,
            acquisition_checkpoint=lambda: None,
            retained_checkpoint=retained_checkpoint,
        )

    assert len(retained) == 1
    provisional = retained[0]
    assert destination.exists()
    assert not validation._retained_junit_handle_is_cleaned(provisional)
    validation._cleanup_retained_junit_handle(
        provisional,
        remove_control_directory=False,
    )
    assert validation._retained_junit_handle_is_cleaned(provisional)
    assert not destination.exists()
    validation._cleanup_retained_junit_handle(
        provisional,
        remove_control_directory=False,
    )
    control_directory.rmdir()


def test_e_retained_junit_rejects_substituted_control_directory_identity(
    tmp_path: Path,
) -> None:
    control_directory = (tmp_path / "identity-control").resolve()
    moved_directory = (tmp_path / "original-identity-control").resolve()
    control_directory.mkdir()
    original_status = control_directory.stat(follow_symlinks=False)
    expected_identity = (original_status.st_dev, original_status.st_ino)
    control_directory.rename(moved_directory)
    control_directory.mkdir()
    replacement_status = control_directory.stat(follow_symlinks=False)
    if (replacement_status.st_dev, replacement_status.st_ino) == expected_identity:
        pytest.skip("filesystem immediately reused the control-directory identity")
    try:
        with pytest.raises(
            validation.PytestValidationError,
            match="centrally owned directory",
        ):
            validation._create_guarded_junit_file(
                control_directory / "pytest-junit.xml",
                initial_bytes=b"i" * 32,
                expected_control_directory_identity=expected_identity,
            )
        assert not (control_directory / "pytest-junit.xml").exists()
    finally:
        control_directory.rmdir()
        moved_directory.rmdir()


def test_e_retained_junit_cleanup_retries_without_closing_a_reused_descriptor(
    tmp_path: Path,
    request: pytest.FixtureRequest,
    _isolated_stage1_and_no_workload: dict[str, int],
) -> None:
    control_directory = (tmp_path / "retry-control").resolve()
    control_directory.mkdir()
    destination = control_directory / "pytest-junit.xml"
    initial_bytes = b"r" * 32
    handle = validation._create_guarded_junit_file(
        destination,
        initial_bytes=initial_bytes,
    )
    unrelated_path = tmp_path / "unrelated.txt"
    teardown_identity: list[tuple[int, int] | None] = [None]
    teardown_descriptors: set[int] = set()

    def cleanup_test_resources() -> None:
        expected_identity = teardown_identity[0]
        for descriptor in tuple(teardown_descriptors):
            try:
                status = os.fstat(descriptor)
            except OSError as error:
                if error.errno != errno.EBADF:
                    raise
            else:
                if (
                    expected_identity is not None
                    and (
                        status.st_dev,
                        status.st_ino,
                    )
                    == expected_identity
                ):
                    os.close(descriptor)
            teardown_descriptors.discard(descriptor)
        validation._cleanup_retained_junit_handle(
            handle,
            remove_control_directory=True,
        )
        if unrelated_path.exists() and expected_identity is not None:
            status = unrelated_path.stat(follow_symlinks=False)
            if (status.st_dev, status.st_ino) == expected_identity:
                unrelated_path.unlink()

    request.addfinalizer(cleanup_test_resources)
    owned_descriptor = handle.descriptor
    owned_identity = handle.file_identity
    owned_path = handle.destination_path
    owned_status = os.fstat(owned_descriptor)
    assert owned_path == destination
    assert (
        validation._regular_single_link_file_identity(
            owned_status,
            "owned retained JUnit descriptor",
        )
        == owned_identity
    )
    assert validation._retained_junit_handle_is_open(handle)

    module_path = Path(validation.__file__).resolve(strict=True)
    source_lines = module_path.read_text(encoding="utf-8").splitlines()
    cleanup_code = cast(
        tuple[object, object, object, CodeType],
        cast(Any, validation._cleanup_retained_junit_handle)._rde_opaque_source,
    )[3]
    interruption_line = next(
        line_number
        for _, _, line_number in cleanup_code.co_lines()
        if line_number is not None
        and source_lines[line_number - 1].strip() == "state.descriptor_closed = True"
        and source_lines[line_number].strip() == "if not state.destination_removed:"
    )
    close_verified_descriptor_line = next(
        line_number
        for line_number, line in enumerate(source_lines, start=1)
        if line.strip() == "def close_verified_descriptor("
    )
    mismatch_return_line = next(
        line_number
        for line_number, line in enumerate(source_lines, start=1)
        if line.strip() == "return"
        and source_lines[line_number - 2].strip()
        == "quarantined_descriptor_owners.append(descriptor_owner)"
    )

    interruption_states: list[tuple[int, tuple[int, int], bool, bool, bool, str]] = []
    previous_trace = sys.gettrace()

    def interrupt_after_close_before_ledger(
        frame: FrameType,
        event: str,
        arg: object,
    ) -> Any:
        if (
            not interruption_states
            and event == "line"
            and frame.f_code is cleanup_code
            and frame.f_lineno == interruption_line
        ):
            state = cast(Any, frame.f_locals["state"])
            interruption_states.append(
                (
                    state.descriptor,
                    state.file_identity,
                    state.descriptor_close_in_progress,
                    state.descriptor_closed,
                    state.destination_removed,
                    state.ownership_state,
                )
            )
            raise KeyboardInterrupt("injected after JUnit close before ledger commit")
        if previous_trace is not None:
            previous_trace(frame, cast(Any, event), arg)
        return interrupt_after_close_before_ledger

    sys.settrace(interrupt_after_close_before_ledger)
    try:
        with pytest.raises(KeyboardInterrupt, match="after JUnit close before ledger commit"):
            validation._cleanup_retained_junit_handle(
                handle,
                remove_control_directory=True,
            )
    finally:
        sys.settrace(previous_trace)

    assert interruption_states == [
        (owned_descriptor, owned_identity, True, False, False, "cleanup_pending")
    ]
    with pytest.raises(OSError) as closed_descriptor:
        os.fstat(owned_descriptor)
    assert closed_descriptor.value.errno == errno.EBADF
    assert destination.read_bytes() == initial_bytes
    assert not validation._retained_junit_handle_is_open(handle)
    assert not validation._retained_junit_handle_is_cleaned(handle)

    unrelated_bytes = b"unrelated descriptor must survive cleanup"
    unrelated_path.write_bytes(unrelated_bytes)
    unrelated_path_status = unrelated_path.stat(follow_symlinks=False)
    unrelated_identity = validation._regular_single_link_file_identity(
        unrelated_path_status,
        "unrelated path",
    )
    teardown_identity[0] = unrelated_identity
    assert unrelated_path != owned_path
    assert unrelated_identity != owned_identity

    source_descriptor: int | None = None
    reused_descriptor: int | None = None
    try:
        source_descriptor = os.open(
            unrelated_path,
            os.O_RDWR | cast(int, getattr(os, "O_BINARY", 0)),
        )
        teardown_descriptors.add(source_descriptor)
        assert (
            validation._regular_single_link_file_identity(
                os.fstat(source_descriptor),
                "unrelated source descriptor",
            )
            == unrelated_identity
        )
        if source_descriptor == owned_descriptor:
            distinct_source_descriptor = os.dup(source_descriptor)
            teardown_descriptors.add(distinct_source_descriptor)
            os.close(source_descriptor)
            teardown_descriptors.discard(source_descriptor)
            source_descriptor = distinct_source_descriptor
        assert source_descriptor != owned_descriptor
        reused_descriptor = os.dup2(
            source_descriptor,
            owned_descriptor,
            inheritable=False,
        )
        teardown_descriptors.add(reused_descriptor)
        assert reused_descriptor == owned_descriptor
        os.close(source_descriptor)
        teardown_descriptors.discard(source_descriptor)
        source_descriptor = None

        reused_identity = validation._regular_single_link_file_identity(
            os.fstat(reused_descriptor),
            "reused unrelated descriptor",
        )
        assert reused_identity == unrelated_identity
        assert reused_identity != owned_identity
        assert not validation._retained_junit_handle_is_cleaned(handle)
        assert (
            validation._regular_single_link_file_identity(
                destination.stat(follow_symlinks=False),
                "owned retained JUnit path before retry",
            )
            == owned_identity
        )
        assert destination.read_bytes() == initial_bytes
        unrelated_before_cleanup = unrelated_path.stat(follow_symlinks=False)

        mismatch_observations: list[tuple[int, tuple[int, int], tuple[int, int]]] = []
        completed_cleanup_states: list[tuple[int, bool, bool, bool, bool, bool, str]] = []

        def observe_identity_aware_retry(
            frame: FrameType,
            event: str,
            arg: object,
        ) -> Any:
            if (
                event == "line"
                and frame.f_code.co_filename == cleanup_code.co_filename
                and frame.f_code.co_name == "close_verified_descriptor"
                and frame.f_code.co_firstlineno == close_verified_descriptor_line
                and frame.f_lineno == mismatch_return_line
            ):
                current_status = cast(os.stat_result, frame.f_locals["current_status"])
                mismatch_observations.append(
                    (
                        cast(int, frame.f_locals["descriptor"]),
                        (current_status.st_dev, current_status.st_ino),
                        cast(tuple[int, int], frame.f_locals["expected"]),
                    )
                )
            if event == "return" and frame.f_code is cleanup_code:
                state = cast(Any, frame.f_locals["state"])
                completed_cleanup_states.append(
                    (
                        state.descriptor,
                        state.descriptor_close_in_progress,
                        state.descriptor_closed,
                        state.destination_unlink_in_progress,
                        state.destination_removed,
                        state.control_directory_removed,
                        state.ownership_state,
                    )
                )
            if previous_trace is not None:
                previous_trace(frame, cast(Any, event), arg)
            return observe_identity_aware_retry

        sys.settrace(observe_identity_aware_retry)
        try:
            validation._cleanup_retained_junit_handle(
                handle,
                remove_control_directory=True,
            )
        finally:
            sys.settrace(previous_trace)

        assert mismatch_observations == [(owned_descriptor, unrelated_identity, owned_identity)]
        assert completed_cleanup_states == [
            (owned_descriptor, True, True, True, True, True, "cleanup_complete")
        ]
        assert validation._retained_junit_handle_is_cleaned(handle)
        assert not validation._retained_junit_handle_is_open(handle)
        assert not owned_path.exists()
        assert not control_directory.exists()

        assert (
            validation._regular_single_link_file_identity(
                os.fstat(reused_descriptor),
                "surviving unrelated descriptor",
            )
            == unrelated_identity
        )
        os.lseek(reused_descriptor, 0, os.SEEK_SET)
        assert os.read(reused_descriptor, len(unrelated_bytes) + 1) == unrelated_bytes
        unrelated_after_cleanup = unrelated_path.stat(follow_symlinks=False)
        assert (
            validation._regular_single_link_file_identity(
                unrelated_after_cleanup,
                "surviving unrelated path",
            )
            == unrelated_identity
        )
        assert unrelated_after_cleanup.st_size == unrelated_before_cleanup.st_size
        assert unrelated_after_cleanup.st_mtime_ns == unrelated_before_cleanup.st_mtime_ns
        assert unrelated_path.read_bytes() == unrelated_bytes

        validation._cleanup_retained_junit_handle(
            handle,
            remove_control_directory=True,
        )
        assert validation._retained_junit_handle_is_cleaned(handle)
        assert (
            validation._regular_single_link_file_identity(
                os.fstat(reused_descriptor),
                "unrelated descriptor after idempotent cleanup",
            )
            == unrelated_identity
        )
        assert unrelated_path.read_bytes() == unrelated_bytes
        assert all(count == 0 for count in _isolated_stage1_and_no_workload.values())
    finally:
        for descriptor in (source_descriptor, reused_descriptor):
            if descriptor is None:
                continue
            try:
                final_status = os.fstat(descriptor)
            except OSError as error:
                if error.errno != errno.EBADF:
                    raise
            else:
                if (final_status.st_dev, final_status.st_ino) == unrelated_identity:
                    os.close(descriptor)
            teardown_descriptors.discard(descriptor)
        validation._cleanup_retained_junit_handle(
            handle,
            remove_control_directory=True,
        )
        if unrelated_path.exists():
            final_unrelated_status = unrelated_path.stat(follow_symlinks=False)
            assert (
                validation._regular_single_link_file_identity(
                    final_unrelated_status,
                    "final unrelated test path",
                )
                == unrelated_identity
            )
            unrelated_path.unlink()
    assert not destination.exists()
    assert not control_directory.exists()


def test_e_retained_junit_retry_recognizes_committed_unlink(tmp_path: Path) -> None:
    control_directory = (tmp_path / "post-unlink-retry-control").resolve()
    control_directory.mkdir()
    destination = control_directory / "pytest-junit.xml"
    handle = validation._create_guarded_junit_file(destination, initial_bytes=b"v" * 32)
    with (
        cast(Any, validation._retained_junit_post_unlink_failure_scope(1)),
        pytest.raises(validation.PytestValidationError, match="unlink"),
    ):
        validation._cleanup_retained_junit_handle(
            handle,
            remove_control_directory=False,
        )
    assert not destination.exists()
    assert not validation._retained_junit_handle_is_cleaned(handle)
    validation._cleanup_retained_junit_handle(
        handle,
        remove_control_directory=False,
    )
    assert validation._retained_junit_handle_is_cleaned(handle)
    validation._cleanup_retained_junit_handle(
        handle,
        remove_control_directory=False,
    )
    control_directory.rmdir()


def test_e_forged_retained_junit_handle_cannot_remove_an_unissued_resource(
    tmp_path: Path,
) -> None:
    control_directory = (tmp_path / "forged-control").resolve()
    control_directory.mkdir()
    destination = control_directory / "pytest-junit.xml"
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    initial = b"f" * 32
    try:
        os.write(descriptor, initial)
        os.fsync(descriptor)
        file_status = os.fstat(descriptor)
        directory_status = control_directory.stat(follow_symlinks=False)
        forged = validation._RetainedJunitHandle(
            descriptor=descriptor,
            destination_path=destination.resolve(strict=True),
            control_directory=control_directory,
            control_directory_identity=(directory_status.st_dev, directory_status.st_ino),
            file_identity=(file_status.st_dev, file_status.st_ino),
            initial_sha256=hashlib.sha256(initial).hexdigest(),
            initial_byte_count=len(initial),
        )
        with pytest.raises(validation.PytestValidationError):
            validation._cleanup_retained_junit_handle(
                forged,
                remove_control_directory=True,
            )
        os.fstat(descriptor)
        assert destination.read_bytes() == initial
    finally:
        os.close(descriptor)
        destination.unlink(missing_ok=True)
        control_directory.rmdir()


def test_e_renamed_retained_junit_resource_is_not_falsely_certified_clean(
    tmp_path: Path,
) -> None:
    control_directory = (tmp_path / "rename-control").resolve()
    control_directory.mkdir()
    destination = control_directory / "pytest-junit.xml"
    handle = validation._create_guarded_junit_file(destination, initial_bytes=b"m" * 32)
    with (
        cast(Any, validation._retained_junit_cleanup_failure_scope(1)),
        pytest.raises(validation.PytestValidationError),
    ):
        validation._cleanup_retained_junit_handle(
            handle,
            remove_control_directory=True,
        )
    moved_directory = (tmp_path / "renamed-control").resolve()
    control_directory.rename(moved_directory)
    with pytest.raises(validation.PytestValidationError):
        validation._cleanup_retained_junit_handle(
            handle,
            remove_control_directory=True,
        )
    assert not validation._retained_junit_handle_is_cleaned(handle)
    moved_destination = moved_directory / destination.name
    assert moved_destination.read_bytes() == b"m" * 32
    moved_destination.unlink()
    moved_directory.rmdir()


def test_e_production_session_owns_handle_before_binding_and_cleans_on_abort() -> None:
    source = inspect.getsource(stage1._prepare_production_stage1)
    assert "def retain_provisional_junit_handle" in source
    assert "def retain_junit_handle" in source
    assert "retain_provisional_handle=retain_provisional_junit_handle" in source
    assert "retain_handle=retain_junit_handle" in source
    assert "pytest_draft, returned_junit_handle" in source
    assert "junit_handle=junit_handle" in source
    assert source.index("junit_handle = handle") < source.index("publish_binding(")
    assert "control_directory_identity=" in source
    assert "local_junit_handle=(" in source
    assert "local_control_directory=(" in source
    assert "local_executor_implementation=executor_implementation" in source
    assert "return junit_handle" not in source
    registry_source = Path(stage1.__file__).read_text(encoding="utf-8")
    cleanup_source = registry_source.split("    def cleanup_session(", maxsplit=1)[1].split(
        "    def abort_preparation(", maxsplit=1
    )[0]
    assert "remove_control_directory=False" in cleanup_source
    assert "remove_control_directory(control_directory)" in cleanup_source
    assert cleanup_source.index("remove_control_directory=False") < cleanup_source.index(
        "remove_control_directory(control_directory)"
    )
    assert cleanup_source.index("remove_control_directory(control_directory)") < (
        cleanup_source.index("resources_cleaned=True")
    )
    assert cleanup_source.index("resources_cleaned=True") < cleanup_source.rindex(
        "pending_resources.pop(session_token, None)"
    )
    module_source = Path(validation.__file__).read_text(encoding="utf-8")
    issuer_source = module_source.split(
        "def _install_production_pytest_plan_draft_issuer",
        maxsplit=1,
    )[1].split("def _issue_fixture_pytest_plan", maxsplit=1)[0]
    assert "create_guarded_junit_file" in issuer_source
    assert issuer_source.index(
        "retain_provisional_handle=retain_provisional_handle"
    ) < issuer_source.index("projection = build_projection")
    assert issuer_source.index("retain_handle=retain_handle") < issuer_source.index(
        "projection = build_projection"
    )
    assert "retained_handle_is_open" in issuer_source
    assert "return draft, retained_handle" in issuer_source


def test_e_historical_test_support_has_no_production_oracle_minting_route() -> None:
    root = repository_root()
    conftest = (root / "tests" / "conftest.py").read_text(encoding="utf-8")
    historical = (root / "tests" / "test_broader_oracle_explicit.py").read_text(encoding="utf-8")
    for forbidden in (
        "begin_oracle_evidence_binding",
        "execute_oracle_conformance",
        "--run-broader-oracle-production",
    ):
        assert forbidden not in conftest
    assert "test_test_support_has_no_implicit_production_oracle_route" in historical
    assert "fixture" in historical


def test_f_exact_six_bind_once_to_one_authority_without_changing_plan_ids() -> None:
    bundle = _canonical_plan_set()
    ids_before = tuple(stage1.plan_persistent_id(plan) for plan in bundle.plans)
    authority = stage1._issue_fixture_authority(
        context=bundle.context,
        validation_run=bundle.run,
        plans=bundle.plans,
    )
    projection = stage1._fixture_validation_authority_projection(authority)
    assert stage1._fixture_validation_authority_id(authority) == (
        stage1.validation_authority_id_from_projection(projection)
    )
    assert tuple(stage1.plan_persistent_id(plan) for plan in bundle.plans) == ids_before
    assert all(stage1.plan_binding_state(plan) == "authority_bound" for plan in bundle.plans)
    record = stage1._FIXTURE_AUTHORITY_RECORDS[authority]
    assert tuple(draft.capability for draft in record.binding.plans.ordered()) == (bundle.plans)
    assert {draft.validation_run for draft in record.binding.plans.ordered()} == {bundle.run}
    assert stage1._fixture_registry_counts() == (1, 6, 1)


@pytest.mark.parametrize(
    "attack",
    ("missing", "extra", "duplicate", "reordered", "wrong_type"),
)
def test_f_missing_extra_duplicate_reordered_and_wrong_type_sets_fail(attack: str) -> None:
    bundle = _canonical_plan_set()
    attacked: tuple[object, ...]
    if attack == "missing":
        attacked = bundle.plans[:-1]
    elif attack == "extra":
        attacked = (*bundle.plans, bundle.plans[-1])
    elif attack == "duplicate":
        attacked = (*bundle.plans[:5], bundle.plans[4])
    elif attack == "reordered":
        attacked = (
            bundle.plans[0],
            bundle.plans[1],
            bundle.plans[2],
            bundle.plans[3],
            bundle.plans[5],
            bundle.plans[4],
        )
    else:
        attacked = (object(), *bundle.plans[1:])
    with _expect_stage1_error(
        "ISSUED_PLAN_CAPABILITY_INVALID",
        "VALIDATION_AUTHORITY_PLAN_MISSING",
        "VALIDATION_AUTHORITY_PLAN_EXTRA",
        "VALIDATION_AUTHORITY_PLAN_ORDER_MISMATCH",
        "VALIDATION_AUTHORITY_PLAN_SET_MISMATCH",
    ):
        stage1._issue_fixture_authority(
            context=bundle.context,
            validation_run=bundle.run,
            plans=attacked,
        )
    assert stage1._fixture_registry_counts() == (1, 6, 0)
    assert all(stage1.plan_binding_state(plan) == "authority_unbound" for plan in bundle.plans)


def test_f_another_run_plan_is_rejected_without_partial_binding() -> None:
    target = _canonical_plan_set()
    other = _canonical_plan_set()
    attacked = (other.plans[0], *target.plans[1:])
    with _expect_stage1_error(
        "ISSUED_PLAN_RUN_MISMATCH",
        "ISSUED_PLAN_STALE",
        "VALIDATION_AUTHORITY_PLAN_SET_MISMATCH",
    ):
        stage1._issue_fixture_authority(
            context=target.context,
            validation_run=target.run,
            plans=attacked,
        )
    assert stage1._fixture_registry_counts() == (2, 12, 0)
    assert all(stage1.plan_binding_state(plan) == "authority_unbound" for plan in target.plans)
    assert all(stage1.plan_binding_state(plan) == "authority_unbound" for plan in other.plans)


def test_f_seventh_and_late_plan_registration_are_rejected() -> None:
    bundle = _canonical_plan_set()

    def issue_seventh() -> object:
        return execution._issue_fixture_execution_specification(
            context=bundle.context,
            validation_run=bundle.run,
            executor_implementation=bundle.executor_implementation,
            function=broader_smoke._execute_job,
            jobs=_smoke_jobs(),
            role="primary_smoke",
        )

    with _expect_stage1_error("VALIDATION_AUTHORITY_PLAN_SET_MISMATCH"):
        issue_seventh()
    assert stage1._fixture_registry_counts() == (1, 6, 0)
    stage1._issue_fixture_authority(
        context=bundle.context,
        validation_run=bundle.run,
        plans=bundle.plans,
    )
    with _expect_stage1_error(
        "ISSUED_PLAN_STALE",
        "VALIDATION_AUTHORITY_PLAN_SET_MISMATCH",
    ):
        issue_seventh()
    assert stage1._fixture_registry_counts() == (1, 6, 1)


def test_f_stateful_plan_iterable_is_materialized_exactly_once() -> None:
    bundle = _canonical_plan_set()

    class StatefulPlans:
        def __init__(self, plans: FixturePlanSet) -> None:
            self.plans = plans
            self.iterations = 0

        def __iter__(self) -> Iterator[object]:
            self.iterations += 1
            values = self.plans if self.iterations == 1 else tuple(reversed(self.plans))
            return iter(values)

    sequence = StatefulPlans(bundle.plans)
    authority = stage1._issue_fixture_authority(
        context=bundle.context,
        validation_run=bundle.run,
        plans=cast(Sequence[object], sequence),
    )
    assert sequence.iterations == 1
    assert stage1._fixture_validation_authority_id(authority)
    assert all(stage1.plan_binding_state(plan) == "authority_bound" for plan in bundle.plans)


def test_g_original_job_list_and_returned_mutable_rendering_are_defensive() -> None:
    context = stage1._fixture_layer0_context()
    run = stage1._issue_fixture_validation_run()
    implementation = execution._issue_fixture_executor_implementation(context, run)
    original_jobs = list(_smoke_jobs())
    plan = execution._issue_fixture_execution_specification(
        context=context,
        validation_run=run,
        executor_implementation=implementation,
        function=broader_smoke._execute_job,
        jobs=original_jobs,
        role="primary_smoke",
    )
    original_jobs.clear()
    projection = execution._fixture_execution_specification_projection(plan)
    assert len(projection.submitted_jobs) == 384
    rendered: Any = projection.as_dict()
    rendered["submitted_jobs"][0]["projection"]["arm"]["arm_id"] = "attacked"
    rendered["implementation"]["implementation_tree_sha256"] = "f" * 64
    assert (
        execution._fixture_execution_specification_projection(plan).submitted_jobs[0]
        == projection.submitted_jobs[0]
    )
    assert execution._fixture_execution_specification_id(plan) == (
        execution._fixture_execution_specification_id_from_projection(projection)
    )


def test_g_frozen_projection_blocks_normal_assignment_and_detects_forced_mutation() -> None:
    bundle = _canonical_plan_set()
    projection = _primary_projection(bundle)
    with pytest.raises(FrozenInstanceError):
        projection.worker_count = 99  # type: ignore[misc]
    object.__setattr__(projection, "worker_count", 99)
    with _expect_stage1_error(
        "EXECUTION_SPECIFICATION_RELATION_MISMATCH",
        "ISSUED_PLAN_MUTATED_AFTER_AUTHORITY",
    ):
        stage1.plan_persistent_id(bundle.plans[2])


def test_g_post_binding_plan_and_authority_mutation_are_detected() -> None:
    bundle = _canonical_plan_set()
    authority = stage1._issue_fixture_authority(
        context=bundle.context,
        validation_run=bundle.run,
        plans=bundle.plans,
    )
    plan_projection = _primary_projection(bundle)
    object.__setattr__(plan_projection, "worker_count", 99)
    with _expect_stage1_error(
        "EXECUTION_SPECIFICATION_RELATION_MISMATCH",
        "ISSUED_PLAN_MUTATED_AFTER_AUTHORITY",
    ):
        stage1._fixture_validation_authority_id(authority)

    stage1._reset_fixture_registries()
    bundle = _canonical_plan_set()
    authority = stage1._issue_fixture_authority(
        context=bundle.context,
        validation_run=bundle.run,
        plans=bundle.plans,
    )
    authority_projection = stage1._fixture_validation_authority_projection(authority)
    object.__setattr__(authority_projection, "pytest_plan_id", "f" * 64)
    with _expect_stage1_error("VALIDATION_AUTHORITY_ID_MISMATCH"):
        stage1._fixture_validation_authority_id(authority)


def test_g_capability_copy_reconstruction_and_registry_record_copy_do_not_authorize() -> None:
    bundle = _canonical_plan_set()
    capability = bundle.plans[2]
    for operation in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            operation(capability)
    lookalike = object.__new__(execution._FixtureExecutionSpecification)
    with _expect_stage1_error("ISSUED_PLAN_CAPABILITY_INVALID"):
        execution._fixture_execution_specification_id(lookalike)
    copied_draft = copy.copy(stage1._FIXTURE_PLAN_RECORDS[capability].draft)
    reconstructed = replace(copied_draft, capability=object())
    with _expect_stage1_error("ISSUED_PLAN_CAPABILITY_INVALID"):
        stage1.plan_persistent_id(reconstructed.capability)


_PREPUBLICATION_FAILURES: tuple[stage1.BindingFailurePoint, ...] = (
    "before_authority_construction",
    "validate_plan_0",
    "validate_plan_1",
    "validate_plan_2",
    "validate_plan_3",
    "validate_plan_4",
    "validate_plan_5",
    "after_authority_construction",
    "before_publication",
    "publication_failure",
)
_PRODUCTION_RESOURCE_FAILURES: tuple[stage1.BindingFailurePoint, ...] = (
    "after_run_reservation_before_ledger",
    "control_directory_acquisition_failure",
    "after_control_directory_creation_before_ledger",
    "after_executor_issuance_before_ledger",
    "junit_acquisition_failure",
    "after_junit_acquisition_before_identity",
    "after_junit_ownership_before_ledger",
)
_PRODUCTION_ALLOCATION_FAILURES: tuple[stage1.BindingFailurePoint, ...] = (
    "after_plan_0_allocation",
    "after_plan_1_allocation",
    "after_plan_2_allocation",
    "after_plan_3_allocation",
    "after_plan_4_allocation",
    "after_plan_5_allocation",
    "after_authority_allocation_before_binding",
)


@pytest.mark.parametrize("failure_point", _PREPUBLICATION_FAILURES)
def test_h_every_prepublication_failure_leaves_zero_visible_binding(
    failure_point: stage1.BindingFailurePoint,
) -> None:
    bundle = _canonical_plan_set()
    with _expect_stage1_error("PARTIAL_AUTHORITY_BINDING_FORBIDDEN"):
        stage1._issue_fixture_authority(
            context=bundle.context,
            validation_run=bundle.run,
            plans=bundle.plans,
            failure_point=failure_point,
        )
    assert stage1._fixture_registry_counts() == (1, 6, 0)
    assert all(stage1.plan_binding_state(plan) == "authority_unbound" for plan in bundle.plans)


def test_h_publication_uses_one_authoritative_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _canonical_plan_set()
    original = stage1._single_assignment_publish
    calls = 0

    def counted_publish(
        registry: dict[Any, Any],
        key: Any,
        value: Any,
        *,
        failure_point: stage1.BindingFailurePoint | None,
    ) -> None:
        nonlocal calls
        calls += 1
        original(registry, key, value, failure_point=failure_point)

    monkeypatch.setattr(stage1, "_single_assignment_publish", counted_publish)
    stage1._issue_fixture_authority(
        context=bundle.context,
        validation_run=bundle.run,
        plans=bundle.plans,
    )
    assert calls == 1
    assert stage1._fixture_registry_counts() == (1, 6, 1)
    assert all(stage1.plan_binding_state(plan) == "authority_bound" for plan in bundle.plans)
    assert all(
        not hasattr(record, "authority") and not hasattr(record, "binding")
        for record in stage1._FIXTURE_PLAN_RECORDS.values()
    )


def test_h_failure_after_publication_leaves_one_complete_binding() -> None:
    bundle = _canonical_plan_set()
    with _expect_stage1_error("PARTIAL_AUTHORITY_BINDING_FORBIDDEN"):
        stage1._issue_fixture_authority(
            context=bundle.context,
            validation_run=bundle.run,
            plans=bundle.plans,
            failure_point="after_publication",
        )
    assert stage1._fixture_registry_counts() == (1, 6, 1)
    authority = next(iter(stage1._FIXTURE_AUTHORITY_RECORDS))
    binding = stage1._require_authority(authority)
    assert tuple(draft.capability for draft in binding.plans.ordered()) == bundle.plans
    assert all(stage1.plan_binding_state(plan) == "authority_bound" for plan in bundle.plans)


def test_h_concurrent_same_run_issuance_has_one_complete_winner() -> None:
    bundle = _canonical_plan_set()
    barrier = threading.Barrier(3)
    authorities: list[object] = []
    errors: list[BaseException] = []

    def issue() -> None:
        barrier.wait()
        try:
            authorities.append(
                stage1._issue_fixture_authority(
                    context=bundle.context,
                    validation_run=bundle.run,
                    plans=bundle.plans,
                )
            )
        except BaseException as error:
            errors.append(error)

    threads = tuple(threading.Thread(target=issue) for _ in range(2))
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert len(authorities) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], stage1.P2Stage1Error)
    _assert_fail_closed(errors[0])
    assert stage1._fixture_registry_counts() == (1, 6, 1)
    assert all(stage1.plan_binding_state(plan) == "authority_bound" for plan in bundle.plans)
    authority = cast(stage1._FixtureValidationAuthority, authorities[0])
    binding = stage1._require_authority(authority)
    assert tuple(draft.capability for draft in binding.plans.ordered()) == bundle.plans


@pytest.mark.skipif(
    os.environ.get("RDE_STAGE1_CLEAN_PRODUCTION_TESTS") != "1",
    reason="actual production preparation requires a committed clean Git snapshot",
)
def test_h_missing_external_bootstrap_anchor_fails_before_run_reservation(
    tmp_path: Path,
    _isolated_stage1_and_no_workload: dict[str, int],
) -> None:
    manifest_path, expected_bytes = _current_bootstrap_manifest_material()
    quarantine = manifest_path.with_name("trusted-local-process-v1.test-absent")
    assert not quarantine.exists()
    status = manifest_path.stat(follow_symlinks=False)
    manifest_identity = (status.st_dev, status.st_ino)
    before = stage1._production_registry_snapshot()
    manifest_path.rename(quarantine)
    try:
        with _expect_stage1_error("IMPLEMENTATION_IDENTITY_MISMATCH"):
            broader_smoke.execute_bounded_validation_evidence(
                tmp_path / "forbidden-output",
                validation_result=cast(Any, object()),
                oracle_conformance_result=cast(Any, object()),
                oracle_evidence_binding=cast(Any, object()),
            )
        assert stage1._production_registry_snapshot() == before
        assert all(count == 0 for count in _isolated_stage1_and_no_workload.values())
    finally:
        quarantine_status = quarantine.stat(follow_symlinks=False)
        assert (quarantine_status.st_dev, quarantine_status.st_ino) == manifest_identity
        assert quarantine.read_bytes() == expected_bytes
        quarantine.rename(manifest_path)


@pytest.mark.skipif(
    os.environ.get("RDE_STAGE1_CLEAN_PRODUCTION_TESTS") != "1",
    reason="actual production preparation requires a committed clean Git snapshot",
)
@pytest.mark.parametrize(
    "failure_point",
    (
        *_PRODUCTION_RESOURCE_FAILURES,
        *_PRODUCTION_ALLOCATION_FAILURES,
        *_PREPUBLICATION_FAILURES,
        "after_publication",
    ),
)
def test_h_actual_production_commit_path_is_atomic_and_cleans_resources(
    failure_point: stage1.BindingFailurePoint,
    tmp_path: Path,
    request: pytest.FixtureRequest,
    _isolated_stage1_and_no_workload: dict[str, int],
) -> None:
    before = stage1._production_registry_snapshot()
    executor_count_before = execution._production_executor_implementation_current_count()
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    control_paths_before = frozenset(temp_root.glob("rde-p2-stage1-*"))
    output_directory = tmp_path / "forbidden-output"
    descriptor_reuse_case = failure_point == "after_junit_ownership_before_ledger"
    unrelated_path = tmp_path / "production-unrelated.txt"
    unrelated_bytes = b"production descriptor reuse must preserve these bytes"
    unrelated_identity: tuple[int, int] | None = None
    reuse_source_descriptor: int | None = None
    reused_descriptor: int | None = None
    teardown_descriptors: set[int] = set()
    cleanup_code = cast(
        tuple[object, object, object, CodeType],
        cast(Any, validation._cleanup_retained_junit_handle)._rde_opaque_source,
    )[3]
    validation_source = Path(cleanup_code.co_filename).read_text(encoding="utf-8").splitlines()
    cleanup_interruption_line = next(
        line_number
        for _, _, line_number in cleanup_code.co_lines()
        if line_number is not None
        and validation_source[line_number - 1].strip() == "state.descriptor_closed = True"
        and validation_source[line_number].strip() == "if not state.destination_removed:"
    )
    close_verified_descriptor_line = next(
        line_number
        for line_number, line in enumerate(validation_source, start=1)
        if line.strip() == "def close_verified_descriptor("
    )
    if descriptor_reuse_case:
        unrelated_path.write_bytes(unrelated_bytes)
        unrelated_status = unrelated_path.stat(follow_symlinks=False)
        unrelated_identity = validation._regular_single_link_file_identity(
            unrelated_status,
            "production unrelated path",
        )

    def cleanup_descriptor_reuse_artifacts() -> None:
        for descriptor in tuple(teardown_descriptors):
            try:
                status = os.fstat(descriptor)
            except OSError as error:
                if error.errno != errno.EBADF:
                    raise
            else:
                if (
                    unrelated_identity is not None
                    and (
                        status.st_dev,
                        status.st_ino,
                    )
                    == unrelated_identity
                ):
                    os.close(descriptor)
            teardown_descriptors.discard(descriptor)
        if unrelated_path.exists() and unrelated_identity is not None:
            status = unrelated_path.stat(follow_symlinks=False)
            if (status.st_dev, status.st_ino) == unrelated_identity:
                unrelated_path.unlink()

    request.addfinalizer(cleanup_descriptor_reuse_artifacts)
    cleanup_scope: Any = (
        validation._retained_junit_cleanup_failure_scope(2)
        if failure_point in {"after_junit_ownership_before_ledger", "before_publication"}
        else nullcontext()
    )
    publication_events: list[tuple[str, stage1._ProductionRegistrySummary]] = []
    cleanup_entries: list[tuple[int, tuple[int, int], Path, bytes, bool]] = []
    interruption_states: list[tuple[int, tuple[int, int], bool, bool, bool, str, int, bool]] = []
    close_results: list[tuple[int, tuple[int, int], tuple[int, int]]] = []
    precommit_mismatch_states: list[tuple[bool, bool, tuple[int, int], bytes]] = []
    completed_cleanup_states: list[tuple[int, bool, bool, bool, bool, bool, str]] = []
    interrupted_state: list[Any] = []
    previous_profile = sys.getprofile()
    previous_trace = sys.gettrace()

    def observe_publication(frame: FrameType, event: str, arg: object) -> None:
        if (
            event in {"call", "return"}
            and frame.f_code is stage1._single_assignment_publish.__code__
        ):
            publication_events.append((event, stage1._production_registry_snapshot()))
        if (
            descriptor_reuse_case
            and event == "return"
            and frame.f_code.co_filename == cleanup_code.co_filename
            and frame.f_code.co_name == "close_verified_descriptor"
            and frame.f_code.co_firstlineno == close_verified_descriptor_line
            and "current_status" in frame.f_locals
        ):
            current_status = cast(os.stat_result, frame.f_locals["current_status"])
            expected_identity = cast(tuple[int, int], frame.f_locals["expected"])
            current_identity = (current_status.st_dev, current_status.st_ino)
            close_results.append(
                (
                    cast(int, frame.f_locals["descriptor"]),
                    current_identity,
                    expected_identity,
                )
            )
            if current_identity != expected_identity:
                state = interrupted_state[0]
                owned_path = Path(cast(str, state.destination))
                path_status = owned_path.stat(follow_symlinks=False)
                precommit_mismatch_states.append(
                    (
                        state.descriptor_closed,
                        state.destination_removed,
                        (path_status.st_dev, path_status.st_ino),
                        owned_path.read_bytes(),
                    )
                )
        if (
            descriptor_reuse_case
            and event == "return"
            and frame.f_code is cleanup_code
            and "state" in frame.f_locals
        ):
            state = cast(Any, frame.f_locals["state"])
            if state.ownership_state == "cleanup_complete":
                completed_cleanup_states.append(
                    (
                        state.descriptor,
                        state.descriptor_close_in_progress,
                        state.descriptor_closed,
                        state.destination_unlink_in_progress,
                        state.destination_removed,
                        state.control_directory_removed,
                        state.ownership_state,
                    )
                )
        if previous_profile is not None:
            previous_profile(frame, cast(Any, event), arg)

    def interrupt_production_cleanup(
        frame: FrameType,
        event: str,
        arg: object,
    ) -> Any:
        nonlocal reuse_source_descriptor, reused_descriptor
        if (
            descriptor_reuse_case
            and not cleanup_entries
            and event == "call"
            and frame.f_code is cleanup_code
            and type(frame.f_locals.get("handle")) is validation._RetainedJunitHandle
        ):
            handle = cast(validation._RetainedJunitHandle, frame.f_locals["handle"])
            descriptor_status = os.fstat(handle.descriptor)
            cleanup_entries.append(
                (
                    handle.descriptor,
                    handle.file_identity,
                    handle.destination_path,
                    handle.destination_path.read_bytes(),
                    cast(bool, frame.f_locals["remove_control_directory"]),
                )
            )
            if (descriptor_status.st_dev, descriptor_status.st_ino) != handle.file_identity:
                raise AssertionError("production cleanup did not receive the owned descriptor")
        if (
            descriptor_reuse_case
            and not interruption_states
            and event == "line"
            and frame.f_code is cleanup_code
            and frame.f_lineno == cleanup_interruption_line
        ):
            state = cast(Any, frame.f_locals["state"])
            interrupted_state.append(state)
            closed_errno: int | None = None
            try:
                os.fstat(state.descriptor)
            except OSError as error:
                closed_errno = error.errno
            if closed_errno != errno.EBADF:
                raise AssertionError("production JUnit descriptor was not closed before reuse")
            if unrelated_identity is None:
                raise AssertionError("production unrelated identity was not established")
            reuse_source_descriptor = os.open(
                unrelated_path,
                os.O_RDWR | cast(int, getattr(os, "O_BINARY", 0)),
            )
            teardown_descriptors.add(reuse_source_descriptor)
            if reuse_source_descriptor == state.descriptor:
                distinct_source_descriptor = os.dup(reuse_source_descriptor)
                teardown_descriptors.add(distinct_source_descriptor)
                os.close(reuse_source_descriptor)
                teardown_descriptors.discard(reuse_source_descriptor)
                reuse_source_descriptor = distinct_source_descriptor
            source_is_distinct = reuse_source_descriptor != state.descriptor
            reused_descriptor = os.dup2(
                reuse_source_descriptor,
                state.descriptor,
                inheritable=False,
            )
            teardown_descriptors.add(reused_descriptor)
            os.close(reuse_source_descriptor)
            teardown_descriptors.discard(reuse_source_descriptor)
            reuse_source_descriptor = None
            reused_status = os.fstat(reused_descriptor)
            interruption_states.append(
                (
                    state.descriptor,
                    state.file_identity,
                    state.descriptor_close_in_progress,
                    state.descriptor_closed,
                    state.destination_removed,
                    state.ownership_state,
                    closed_errno,
                    source_is_distinct,
                )
            )
            if (
                reused_descriptor != state.descriptor
                or (reused_status.st_dev, reused_status.st_ino) != unrelated_identity
            ):
                raise AssertionError("dup2 did not install the unrelated descriptor identity")
            raise KeyboardInterrupt("injected after JUnit close before ledger commit")
        if previous_trace is not None:
            previous_trace(frame, cast(Any, event), arg)
        return interrupt_production_cleanup

    sys.setprofile(observe_publication)
    if descriptor_reuse_case:
        sys.settrace(interrupt_production_cleanup)
    try:
        expected_error = (
            "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE"
            if failure_point
            in {"control_directory_acquisition_failure", "junit_acquisition_failure"}
            else "PARTIAL_AUTHORITY_BINDING_FORBIDDEN"
        )
        with (
            cleanup_scope,
            cast(Any, stage1._production_failure_scope(failure_point)),
            _expect_stage1_error(expected_error) as captured,
        ):
            broader_smoke.execute_bounded_validation_evidence(
                output_directory,
                validation_result=cast(Any, object()),
                oracle_conformance_result=cast(Any, object()),
                oracle_evidence_binding=cast(Any, object()),
            )
    finally:
        sys.settrace(previous_trace)
        sys.setprofile(previous_profile)
    expected_events = (
        ["call", "return"] if failure_point in {"publication_failure", "after_publication"} else []
    )
    assert [event for event, _ in publication_events] == expected_events
    if publication_events:
        before_publication = publication_events[0][1]
        assert before_publication.reserved_runs == before.reserved_runs + 1
        assert before_publication.current_bound_runs == before.current_bound_runs
        assert before_publication.current_plan_count == before.current_plan_count
        assert before_publication.current_authority_count == before.current_authority_count
        assert before_publication.complete_bindings == before.complete_bindings
        assert before_publication.complete_binding_plan_slots == before.complete_binding_plan_slots
        assert before_publication.partial_binding_records == before.partial_binding_records == 0
        assert (
            before_publication.retained_junit_handle_count == before.retained_junit_handle_count + 1
        )
        assert before_publication.terminal_runs == before.terminal_runs
        assert before_publication.terminal_complete_bindings == before.terminal_complete_bindings
        assert before_publication.resources_cleaned_count == before.resources_cleaned_count

        after_publication = publication_events[1][1]
        if failure_point == "publication_failure":
            assert after_publication == before_publication
        else:
            assert after_publication.reserved_runs == before.reserved_runs
            assert after_publication.current_bound_runs == before.current_bound_runs + 1
            assert after_publication.current_plan_count == before.current_plan_count + 6
            assert after_publication.current_authority_count == before.current_authority_count + 1
            assert after_publication.complete_bindings == before.complete_bindings + 1
            assert (
                after_publication.complete_binding_plan_slots
                == before.complete_binding_plan_slots + 6
            )
            assert after_publication.partial_binding_records == before.partial_binding_records == 0
            assert (
                after_publication.retained_junit_handle_count
                == before.retained_junit_handle_count + 1
            )
            assert after_publication.terminal_runs == before.terminal_runs
            assert after_publication.terminal_complete_bindings == before.terminal_complete_bindings
            assert after_publication.resources_cleaned_count == before.resources_cleaned_count
    notes = "\n".join(getattr(captured.value, "__notes__", ()))
    if failure_point in {"after_junit_ownership_before_ledger", "before_publication"}:
        assert "Injected retained JUnit cleanup failure" in notes
    if descriptor_reuse_case:
        assert "injected after JUnit close before ledger commit" in notes
    if failure_point == "before_publication":
        assert "Stage-1 cleanup also failed" in notes
    after = stage1._production_registry_snapshot()
    assert not output_directory.exists()
    assert frozenset(temp_root.glob("rde-p2-stage1-*")) == control_paths_before
    assert execution._production_executor_implementation_current_count() == executor_count_before
    assert after.reserved_runs == before.reserved_runs
    assert after.current_bound_runs == before.current_bound_runs
    assert after.current_plan_count == before.current_plan_count
    assert after.current_authority_count == before.current_authority_count
    assert after.retained_junit_handle_count == before.retained_junit_handle_count
    assert after.partial_binding_records == before.partial_binding_records == 0
    assert after.terminal_runs == before.terminal_runs + 1
    assert after.resources_cleaned_count == before.resources_cleaned_count + 1
    if failure_point == "after_publication":
        assert after.complete_bindings == before.complete_bindings + 1
        assert after.terminal_complete_bindings == before.terminal_complete_bindings + 1
        assert after.complete_binding_plan_slots == before.complete_binding_plan_slots + 6
    else:
        assert after.complete_bindings == before.complete_bindings
        assert after.terminal_complete_bindings == before.terminal_complete_bindings
        assert after.complete_binding_plan_slots == before.complete_binding_plan_slots
    if descriptor_reuse_case:
        assert len(cleanup_entries) == 1
        (
            owned_descriptor,
            owned_identity,
            owned_path,
            owned_bytes,
            remove_control_directory,
        ) = cleanup_entries[0]
        assert remove_control_directory is False
        assert interruption_states == [
            (
                owned_descriptor,
                owned_identity,
                True,
                False,
                False,
                "cleanup_pending",
                errno.EBADF,
                True,
            )
        ]
        assert close_results == [
            (owned_descriptor, owned_identity, owned_identity),
            (owned_descriptor, unrelated_identity, owned_identity),
        ]
        assert precommit_mismatch_states == [(False, False, owned_identity, owned_bytes)]
        assert completed_cleanup_states == [
            (
                owned_descriptor,
                True,
                True,
                True,
                True,
                False,
                "cleanup_complete",
            )
        ]
        assert reused_descriptor == owned_descriptor
        assert unrelated_identity is not None
        assert (
            validation._regular_single_link_file_identity(
                os.fstat(reused_descriptor),
                "surviving production unrelated descriptor",
            )
            == unrelated_identity
        )
        os.lseek(reused_descriptor, 0, os.SEEK_SET)
        assert os.read(reused_descriptor, len(unrelated_bytes) + 1) == unrelated_bytes
        assert unrelated_path.read_bytes() == unrelated_bytes
        assert not owned_path.exists()
        assert not owned_path.parent.exists()
        cleanup_descriptor_reuse_artifacts()
        assert not unrelated_path.exists()
    assert all(count == 0 for count in _isolated_stage1_and_no_workload.values())


@pytest.mark.skipif(
    os.environ.get("RDE_STAGE1_CLEAN_PRODUCTION_TESTS") != "1",
    reason="actual production preparation requires a committed clean Git snapshot",
)
@pytest.mark.parametrize(
    ("boundary", "target_source_line"),
    (
        ("directory_component_promotion", "records[owned] = row"),
        ("directory_central_to_local", "owned_control_directory = exact_owned"),
        ("junit_central_to_local", "junit_handle = handle"),
    ),
)
def test_h_async_promotion_gaps_reconcile_to_central_cleanup(
    boundary: str,
    target_source_line: str,
    tmp_path: Path,
    _isolated_stage1_and_no_workload: dict[str, int],
) -> None:
    before = stage1._production_registry_snapshot()
    executor_count_before = execution._production_executor_implementation_current_count()
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    control_paths_before = frozenset(temp_root.glob("rde-p2-stage1-*"))
    output_directory = tmp_path / "forbidden-output"
    if boundary == "directory_component_promotion":
        target_code = cast(
            tuple[object, object, object, CodeType],
            cast(Any, stage1._create_owned_control_directory)._rde_opaque_source,
        )[3]
    else:
        callback_name = (
            "retain_owned_control_directory"
            if boundary == "directory_central_to_local"
            else "retain_junit_handle"
        )
        target_code = next(
            constant
            for constant in stage1._prepare_production_stage1.__code__.co_consts
            if isinstance(constant, CodeType) and constant.co_name == callback_name
        )
    source_lines = Path(target_code.co_filename).read_text(encoding="utf-8").splitlines()
    interruption_line = next(
        line_number
        for _, _, line_number in target_code.co_lines()
        if line_number is not None and source_lines[line_number - 1].strip() == target_source_line
    )
    interrupted = False
    previous_trace = sys.gettrace()

    def interrupt_promotion(frame: FrameType, event: str, arg: object) -> Any:
        nonlocal interrupted
        if (
            not interrupted
            and frame.f_code is target_code
            and event == "line"
            and frame.f_lineno == interruption_line
        ):
            interrupted = True
            raise KeyboardInterrupt(f"injected at {boundary}")
        if previous_trace is not None:
            previous_trace(frame, cast(Any, event), arg)
        return interrupt_promotion

    sys.settrace(interrupt_promotion)
    try:
        with _expect_stage1_error("EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE"):
            broader_smoke.execute_bounded_validation_evidence(
                output_directory,
                validation_result=cast(Any, object()),
                oracle_conformance_result=cast(Any, object()),
                oracle_evidence_binding=cast(Any, object()),
            )
    finally:
        sys.settrace(previous_trace)

    assert interrupted
    assert not output_directory.exists()
    assert frozenset(temp_root.glob("rde-p2-stage1-*")) == control_paths_before
    assert execution._production_executor_implementation_current_count() == executor_count_before
    after = stage1._production_registry_snapshot()
    assert after.reserved_runs == before.reserved_runs
    assert after.current_bound_runs == before.current_bound_runs
    assert after.current_plan_count == before.current_plan_count
    assert after.current_authority_count == before.current_authority_count
    assert after.retained_junit_handle_count == before.retained_junit_handle_count
    assert after.partial_binding_records == before.partial_binding_records == 0
    assert after.terminal_runs == before.terminal_runs + 1
    assert after.resources_cleaned_count == before.resources_cleaned_count + 1
    assert after.complete_bindings == before.complete_bindings
    assert after.terminal_complete_bindings == before.terminal_complete_bindings
    assert after.complete_binding_plan_slots == before.complete_binding_plan_slots
    assert all(count == 0 for count in _isolated_stage1_and_no_workload.values())


@pytest.mark.skipif(
    os.environ.get("RDE_STAGE1_CLEAN_PRODUCTION_TESTS") != "1",
    reason="actual production preparation requires a committed clean Git snapshot",
)
@pytest.mark.parametrize(
    ("failure_point", "resource_name"),
    (
        ("control_directory_acquisition_failure", "control_directory"),
        ("junit_acquisition_failure", "junit"),
    ),
)
def test_h_abort_normalizes_interrupted_ownerless_acquisition_cancel(
    failure_point: stage1.BindingFailurePoint,
    resource_name: str,
    tmp_path: Path,
    _isolated_stage1_and_no_workload: dict[str, int],
) -> None:
    before = stage1._production_registry_snapshot()
    executor_count_before = execution._production_executor_implementation_current_count()
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    control_paths_before = frozenset(temp_root.glob("rde-p2-stage1-*"))
    output_directory = tmp_path / "forbidden-output"
    source_lines = Path(stage1.__file__).read_text(encoding="utf-8").splitlines()
    interrupted = False
    previous_trace = sys.gettrace()

    def interrupt_cancel_transition(frame: FrameType, event: str, arg: object) -> Any:
        nonlocal interrupted
        if (
            not interrupted
            and event == "line"
            and frame.f_code.co_name == "transition_physical_resource"
            and frame.f_locals.get("state") == "none"
            and frame.f_locals.get("resource_name") == resource_name
            and source_lines[frame.f_lineno - 1].strip()
            == "pending_resources[session_token] = updated"
        ):
            interrupted = True
            raise KeyboardInterrupt(f"injected during {resource_name} cancellation")
        if previous_trace is not None:
            previous_trace(frame, cast(Any, event), arg)
        return interrupt_cancel_transition

    sys.settrace(interrupt_cancel_transition)
    try:
        with (
            cast(Any, stage1._production_failure_scope(failure_point)),
            _expect_stage1_error("EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE"),
        ):
            broader_smoke.execute_bounded_validation_evidence(
                output_directory,
                validation_result=cast(Any, object()),
                oracle_conformance_result=cast(Any, object()),
                oracle_evidence_binding=cast(Any, object()),
            )
    finally:
        sys.settrace(previous_trace)

    assert interrupted
    assert not output_directory.exists()
    assert frozenset(temp_root.glob("rde-p2-stage1-*")) == control_paths_before
    assert execution._production_executor_implementation_current_count() == executor_count_before
    after = stage1._production_registry_snapshot()
    assert after.reserved_runs == before.reserved_runs
    assert after.current_bound_runs == before.current_bound_runs
    assert after.current_plan_count == before.current_plan_count
    assert after.current_authority_count == before.current_authority_count
    assert after.retained_junit_handle_count == before.retained_junit_handle_count
    assert after.partial_binding_records == before.partial_binding_records == 0
    assert after.terminal_runs == before.terminal_runs + 1
    assert after.resources_cleaned_count == before.resources_cleaned_count + 1
    assert after.complete_bindings == before.complete_bindings
    assert after.terminal_complete_bindings == before.terminal_complete_bindings
    assert after.complete_binding_plan_slots == before.complete_binding_plan_slots
    assert all(count == 0 for count in _isolated_stage1_and_no_workload.values())


@pytest.mark.skipif(
    os.environ.get("RDE_STAGE1_CLEAN_PRODUCTION_TESTS") != "1",
    reason="actual production preparation requires a committed clean Git snapshot",
)
def test_h_final_provenance_recheck_rejects_prepublication_worktree_drift(
    tmp_path: Path,
    _isolated_stage1_and_no_workload: dict[str, int],
) -> None:
    before = stage1._production_registry_snapshot()
    executor_count_before = execution._production_executor_implementation_current_count()
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    control_paths_before = frozenset(temp_root.glob("rde-p2-stage1-*"))
    output_directory = tmp_path / "forbidden-output"
    tracked_test = repository_root() / "tests" / "test_broader_oracle_explicit.py"
    original_bytes = tracked_test.read_bytes()
    prepare_code = stage1._prepare_production_stage1.__code__
    prepare_source = Path(prepare_code.co_filename).read_text(encoding="utf-8").splitlines()
    drift_line = next(
        line_number
        for _, _, line_number in prepare_code.co_lines()
        if line_number is not None and prepare_source[line_number - 1].strip() == "publish_binding("
    )
    changed = False
    previous_trace = sys.gettrace()

    def introduce_drift(frame: FrameType, event: str, arg: object) -> Any:
        nonlocal changed
        if (
            not changed
            and frame.f_code is prepare_code
            and event == "line"
            and frame.f_lineno == drift_line
        ):
            tracked_test.write_bytes(original_bytes + b"\n# transient prepublication drift\n")
            changed = True
        if previous_trace is not None:
            previous_trace(frame, cast(Any, event), arg)
        return introduce_drift

    sys.settrace(introduce_drift)
    try:
        with _expect_stage1_error("IMPLEMENTATION_IDENTITY_MISMATCH"):
            broader_smoke.execute_bounded_validation_evidence(
                output_directory,
                validation_result=cast(Any, object()),
                oracle_conformance_result=cast(Any, object()),
                oracle_evidence_binding=cast(Any, object()),
            )
    finally:
        sys.settrace(previous_trace)
        tracked_test.write_bytes(original_bytes)

    assert changed
    assert tracked_test.read_bytes() == original_bytes
    assert not output_directory.exists()
    assert frozenset(temp_root.glob("rde-p2-stage1-*")) == control_paths_before
    assert execution._production_executor_implementation_current_count() == executor_count_before
    after = stage1._production_registry_snapshot()
    assert after.reserved_runs == before.reserved_runs
    assert after.current_bound_runs == before.current_bound_runs
    assert after.current_plan_count == before.current_plan_count
    assert after.current_authority_count == before.current_authority_count
    assert after.retained_junit_handle_count == before.retained_junit_handle_count
    assert after.partial_binding_records == before.partial_binding_records == 0
    assert after.terminal_runs == before.terminal_runs + 1
    assert after.resources_cleaned_count == before.resources_cleaned_count + 1
    assert after.complete_bindings == before.complete_bindings
    assert after.terminal_complete_bindings == before.terminal_complete_bindings
    assert after.complete_binding_plan_slots == before.complete_binding_plan_slots
    assert all(count == 0 for count in _isolated_stage1_and_no_workload.values())


@pytest.mark.skipif(
    os.environ.get("RDE_STAGE1_CLEAN_PRODUCTION_TESTS") != "1",
    reason="actual production preparation requires a committed clean Git snapshot",
)
def test_h_successful_stage1_stops_before_unauthorized_stage2_workload(
    tmp_path: Path,
    _isolated_stage1_and_no_workload: dict[str, int],
) -> None:
    before = stage1._production_registry_snapshot()
    executor_count_before = execution._production_executor_implementation_current_count()
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    control_paths_before = frozenset(temp_root.glob("rde-p2-stage1-*"))
    output_directory = tmp_path / "forbidden-output"

    with _expect_stage1_error("P2_STAGE2_NOT_AUTHORIZED") as captured:
        broader_smoke.execute_bounded_validation_evidence(
            output_directory,
            validation_result=cast(Any, object()),
            oracle_conformance_result=cast(Any, object()),
            oracle_evidence_binding=cast(Any, object()),
        )

    assert captured.value.validation_layer == "stage_boundary"
    assert not output_directory.exists()
    assert frozenset(temp_root.glob("rde-p2-stage1-*")) == control_paths_before
    assert execution._production_executor_implementation_current_count() == executor_count_before

    after = stage1._production_registry_snapshot()
    assert after.reserved_runs == before.reserved_runs
    assert after.current_bound_runs == before.current_bound_runs
    assert after.current_plan_count == before.current_plan_count
    assert after.current_authority_count == before.current_authority_count
    assert after.retained_junit_handle_count == before.retained_junit_handle_count
    assert after.partial_binding_records == before.partial_binding_records == 0
    assert after.terminal_runs == before.terminal_runs + 1
    assert after.resources_cleaned_count == before.resources_cleaned_count + 1
    assert after.complete_bindings == before.complete_bindings + 1
    assert after.terminal_complete_bindings == before.terminal_complete_bindings + 1
    assert after.complete_binding_plan_slots == before.complete_binding_plan_slots + 6
    assert all(count == 0 for count in _isolated_stage1_and_no_workload.values())


@pytest.mark.skipif(
    os.environ.get("RDE_STAGE1_CLEAN_PRODUCTION_TESTS") != "1",
    reason="actual production preparation requires a committed clean Git snapshot",
)
def test_h_concurrent_public_sessions_publish_only_complete_terminal_bindings(
    tmp_path: Path,
    _isolated_stage1_and_no_workload: dict[str, int],
) -> None:
    before = stage1._production_registry_snapshot()
    executor_count_before = execution._production_executor_implementation_current_count()
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    control_paths_before = frozenset(temp_root.glob("rde-p2-stage1-*"))
    barrier = threading.Barrier(3)
    errors: list[BaseException] = []

    def run(index: int) -> None:
        barrier.wait()
        try:
            broader_smoke.execute_bounded_validation_evidence(
                tmp_path / f"forbidden-output-{index}",
                validation_result=cast(Any, object()),
                oracle_conformance_result=cast(Any, object()),
                oracle_evidence_binding=cast(Any, object()),
            )
        except BaseException as error:
            errors.append(error)

    threads = tuple(threading.Thread(target=run, args=(index,)) for index in range(2))
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()

    assert len(errors) == 2
    assert all(
        isinstance(error, stage1.P2Stage1Error) and error.error_code == "P2_STAGE2_NOT_AUTHORIZED"
        for error in errors
    )
    for error in errors:
        _assert_fail_closed(cast(stage1.P2Stage1Error, error))
    assert not any((tmp_path / f"forbidden-output-{index}").exists() for index in range(2))
    assert frozenset(temp_root.glob("rde-p2-stage1-*")) == control_paths_before
    assert execution._production_executor_implementation_current_count() == executor_count_before

    after = stage1._production_registry_snapshot()
    assert after.reserved_runs == before.reserved_runs
    assert after.current_bound_runs == before.current_bound_runs
    assert after.current_plan_count == before.current_plan_count
    assert after.current_authority_count == before.current_authority_count
    assert after.retained_junit_handle_count == before.retained_junit_handle_count
    assert after.partial_binding_records == before.partial_binding_records == 0
    assert after.terminal_runs == before.terminal_runs + 2
    assert after.resources_cleaned_count == before.resources_cleaned_count + 2
    assert after.complete_bindings == before.complete_bindings + 2
    assert after.terminal_complete_bindings == before.terminal_complete_bindings + 2
    assert after.complete_binding_plan_slots == before.complete_binding_plan_slots + 12
    assert all(count == 0 for count in _isolated_stage1_and_no_workload.values())


@pytest.mark.skipif(
    os.environ.get("RDE_STAGE1_CLEAN_PRODUCTION_TESTS") != "1",
    reason="actual production preparation requires a committed clean Git snapshot",
)
def test_h_owned_directory_cleanup_retries_after_committed_rmdir(
    tmp_path: Path,
    _isolated_stage1_and_no_workload: dict[str, int],
) -> None:
    before = stage1._production_registry_snapshot()
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    sibling = Path(tempfile.mkdtemp(prefix="rde-p2-stage1-sibling-", dir=temp_root))
    sibling_sentinel = sibling / "sentinel.bin"
    sibling_sentinel.write_bytes(b"stage1-sibling-must-survive")
    sibling_status = sibling.stat(follow_symlinks=False)
    sibling_identity = (sibling_status.st_dev, sibling_status.st_ino)
    control_paths_before = frozenset(temp_root.glob("rde-p2-stage1-*"))
    output_directory = tmp_path / "forbidden-output"
    abort_code = cast(
        tuple[object, object, object, CodeType],
        cast(Any, stage1._abort_production_preparation)._rde_opaque_source,
    )[3]
    abort_snapshots: list[stage1._ProductionRegistrySummary] = []
    previous_profile = sys.getprofile()

    def observe_abort(frame: FrameType, event: str, arg: object) -> None:
        if event == "return" and frame.f_code is abort_code:
            abort_snapshots.append(stage1._production_registry_snapshot())
        if previous_profile is not None:
            previous_profile(frame, cast(Any, event), arg)

    sys.setprofile(observe_abort)
    try:
        with (
            cast(Any, stage1._owned_control_directory_post_rmdir_failure_scope(6)),
            cast(
                Any,
                stage1._production_failure_scope("after_control_directory_creation_before_ledger"),
            ),
            _expect_stage1_error("PARTIAL_AUTHORITY_BINDING_FORBIDDEN"),
        ):
            broader_smoke.execute_bounded_validation_evidence(
                output_directory,
                validation_result=cast(Any, object()),
                oracle_conformance_result=cast(Any, object()),
                oracle_evidence_binding=cast(Any, object()),
            )
        sys.setprofile(previous_profile)
        after = stage1._production_registry_snapshot()
        assert not output_directory.exists()
        assert frozenset(temp_root.glob("rde-p2-stage1-*")) == control_paths_before
        current_sibling_status = sibling.stat(follow_symlinks=False)
        assert (current_sibling_status.st_dev, current_sibling_status.st_ino) == sibling_identity
        assert sibling_sentinel.read_bytes() == b"stage1-sibling-must-survive"
        assert after.terminal_runs == before.terminal_runs + 1
        assert after.resources_cleaned_count == before.resources_cleaned_count + 1
        assert after.partial_binding_records == before.partial_binding_records == 0
        assert after.current_bound_runs == before.current_bound_runs
        assert after.current_plan_count == before.current_plan_count
        assert after.current_authority_count == before.current_authority_count
        assert after.complete_bindings == before.complete_bindings
        assert after.complete_binding_plan_slots == before.complete_binding_plan_slots
        assert len(abort_snapshots) == 3
        assert abort_snapshots[0].terminal_runs == before.terminal_runs + 1
        assert abort_snapshots[0].resources_cleaned_count == before.resources_cleaned_count
        assert abort_snapshots[1].resources_cleaned_count == before.resources_cleaned_count + 1
        assert (
            abort_snapshots[2].resources_cleaned_count == abort_snapshots[1].resources_cleaned_count
        )
        assert all(count == 0 for count in _isolated_stage1_and_no_workload.values())
    finally:
        sys.setprofile(previous_profile)
        if sibling_sentinel.exists():
            sibling_sentinel.unlink()
        if sibling.exists():
            sibling.rmdir()


@pytest.mark.skipif(
    os.environ.get("RDE_STAGE1_CLEAN_PRODUCTION_TESTS") != "1",
    reason="actual production preparation requires a committed clean Git snapshot",
)
def test_h_central_cleanup_preserves_directory_until_junit_unlink_retry_completes(
    tmp_path: Path,
    _isolated_stage1_and_no_workload: dict[str, int],
) -> None:
    before = stage1._production_registry_snapshot()
    executor_count_before = execution._production_executor_implementation_current_count()
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    control_paths_before = frozenset(temp_root.glob("rde-p2-stage1-*"))
    output_directory = tmp_path / "forbidden-output"

    with (
        cast(Any, validation._retained_junit_post_unlink_failure_scope(1)),
        cast(Any, stage1._production_failure_scope("before_publication")),
        _expect_stage1_error("PARTIAL_AUTHORITY_BINDING_FORBIDDEN") as captured,
    ):
        broader_smoke.execute_bounded_validation_evidence(
            output_directory,
            validation_result=cast(Any, object()),
            oracle_conformance_result=cast(Any, object()),
            oracle_evidence_binding=cast(Any, object()),
        )

    assert "Could not unlink the exact retained JUnit destination" in "\n".join(
        getattr(captured.value, "__notes__", ())
    )
    assert not output_directory.exists()
    assert frozenset(temp_root.glob("rde-p2-stage1-*")) == control_paths_before
    assert execution._production_executor_implementation_current_count() == executor_count_before
    after = stage1._production_registry_snapshot()
    assert after.reserved_runs == before.reserved_runs
    assert after.current_bound_runs == before.current_bound_runs
    assert after.current_plan_count == before.current_plan_count
    assert after.current_authority_count == before.current_authority_count
    assert after.retained_junit_handle_count == before.retained_junit_handle_count
    assert after.partial_binding_records == before.partial_binding_records == 0
    assert after.terminal_runs == before.terminal_runs + 1
    assert after.resources_cleaned_count == before.resources_cleaned_count + 1
    assert after.complete_bindings == before.complete_bindings
    assert after.terminal_complete_bindings == before.terminal_complete_bindings
    assert after.complete_binding_plan_slots == before.complete_binding_plan_slots
    assert all(count == 0 for count in _isolated_stage1_and_no_workload.values())


@pytest.mark.skipif(
    os.environ.get("RDE_STAGE1_CLEAN_PRODUCTION_TESTS") != "1",
    reason="actual production preparation requires a committed clean Git snapshot",
)
def test_h_owned_directory_cleanup_never_removes_same_path_substitution(
    tmp_path: Path,
    _isolated_stage1_and_no_workload: dict[str, int],
) -> None:
    create_code = cast(
        tuple[object, object, object, CodeType],
        cast(Any, stage1._create_owned_control_directory)._rde_opaque_source,
    )[3]
    remove_code = cast(
        tuple[object, object, object, CodeType],
        cast(Any, stage1._remove_empty_owned_control_directory)._rde_opaque_source,
    )[3]
    original: Path | None = None
    moved: Path | None = None
    survivor: Path | None = None
    sentinel: Path | None = None
    phase = "waiting"
    replacement_survived_rejection = False
    previous_profile = sys.getprofile()

    def substitute_then_restore(frame: FrameType, event: str, arg: object) -> None:
        nonlocal original, moved, survivor, sentinel, phase
        nonlocal replacement_survived_rejection
        if event == "return" and frame.f_code is create_code and phase == "waiting":
            assert type(arg) is stage1._OwnedControlDirectory
            owned = arg
            original = owned.path
            moved = original.with_name(original.name + "-owned-original")
            survivor = original.with_name(original.name + "-replacement-survivor")
            assert not moved.exists() and not survivor.exists()
            original.rename(moved)
            original.mkdir()
            sentinel = original / "unowned-sentinel.bin"
            sentinel.write_bytes(b"same-path replacement must survive")
            phase = "substituted"
        elif event == "return" and frame.f_code is remove_code and phase == "substituted":
            phase = "restoring"
            assert original is not None and moved is not None and survivor is not None
            assert (
                sentinel is not None
                and sentinel.read_bytes() == b"same-path replacement must survive"
            )
            replacement_survived_rejection = True
            original.rename(survivor)
            moved.rename(original)
            phase = "restored"
        if previous_profile is not None:
            previous_profile(frame, cast(Any, event), arg)

    sys.setprofile(substitute_then_restore)
    try:
        with _expect_stage1_error("EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE"):
            broader_smoke.execute_bounded_validation_evidence(
                tmp_path / "forbidden-output",
                validation_result=cast(Any, object()),
                oracle_conformance_result=cast(Any, object()),
                oracle_evidence_binding=cast(Any, object()),
            )
    finally:
        sys.setprofile(previous_profile)
    try:
        assert phase == "restored"
        assert replacement_survived_rejection
        assert original is not None and not original.exists()
        assert survivor is not None and survivor.is_dir()
        assert sentinel is not None
        survivor_sentinel = survivor / sentinel.name
        assert survivor_sentinel.read_bytes() == b"same-path replacement must survive"
        assert not (tmp_path / "forbidden-output").exists()
        assert all(count == 0 for count in _isolated_stage1_and_no_workload.values())
    finally:
        if survivor is not None and survivor.exists():
            survivor_sentinel = survivor / "unowned-sentinel.bin"
            survivor_sentinel.unlink(missing_ok=True)
            survivor.rmdir()
        if moved is not None and moved.exists():
            moved.rmdir()
        if original is not None and original.exists():
            original.rmdir()


def test_h_rebinding_never_creates_a_second_or_partial_authority() -> None:
    bundle = _canonical_plan_set()
    authority = stage1._issue_fixture_authority(
        context=bundle.context,
        validation_run=bundle.run,
        plans=bundle.plans,
    )
    with _expect_stage1_error("ISSUED_PLAN_AUTHORITY_MISMATCH"):
        stage1._issue_fixture_authority(
            context=bundle.context,
            validation_run=bundle.run,
            plans=bundle.plans,
        )
    assert tuple(stage1._FIXTURE_AUTHORITY_RECORDS) == (authority,)
    assert all(stage1.plan_binding_state(plan) == "authority_bound" for plan in bundle.plans)


def test_i_fixture_capabilities_fail_all_production_accessors_at_domain_barrier() -> None:
    bundle = _canonical_plan_set()
    authority = stage1._issue_fixture_authority(
        context=bundle.context,
        validation_run=bundle.run,
        plans=bundle.plans,
    )
    before = stage1._production_registry_snapshot()
    production_accesses: tuple[Callable[[], object], ...] = (
        lambda: stage1.validation_run_id(cast(Any, bundle.run)),
        lambda: execution.executor_implementation_identity(
            cast(Any, bundle.executor_implementation)
        ),
        lambda: execution.executor_implementation_projection(
            cast(Any, bundle.executor_implementation)
        ),
        lambda: validation.pytest_plan_id(cast(Any, bundle.plans[0])),
        lambda: validation.p2_pytest_plan_projection(cast(Any, bundle.plans[0])),
        lambda: oracle.oracle_plan_id(cast(Any, bundle.plans[1])),
        lambda: oracle.p2_oracle_plan_projection(cast(Any, bundle.plans[1])),
        lambda: execution.execution_specification_id(cast(Any, bundle.plans[2])),
        lambda: execution.p2_execution_specification_projection(cast(Any, bundle.plans[2])),
        lambda: stage1.validation_authority_id(cast(Any, authority)),
        lambda: stage1.validation_authority_projection(cast(Any, authority)),
    )
    for access in production_accesses:
        with _expect_stage1_error(
            "EVIDENCE_TRUST_DOMAIN_MISMATCH",
            "EXECUTOR_IMPLEMENTATION_ISSUANCE_UNAVAILABLE",
            "EXECUTOR_IMPLEMENTATION_IDENTITY_MISMATCH",
            "ISSUED_PLAN_CAPABILITY_INVALID",
            "VALIDATION_RUN_STALE",
        ):
            access()
    assert stage1._production_registry_snapshot() == before


def test_i_correct_looking_fixture_plan_reaches_true_production_domain_check() -> None:
    bundle = _canonical_plan_set()
    fixture_plan = bundle.plans[2]
    projection = execution._fixture_execution_specification_projection(fixture_plan)
    assert projection.trust_domain == "production"
    assert len(projection.submitted_jobs) == 384
    with _expect_stage1_error("EVIDENCE_TRUST_DOMAIN_MISMATCH") as captured:
        stage1._require_plan(fixture_plan, expected_domain="production")
    assert captured.value.validation_layer == "validation_authority"


def test_i_no_promotion_retagging_or_shared_registry_path_exists() -> None:
    combined = "\n".join(
        (
            inspect.getsource(stage1),
            inspect.getsource(execution),
            inspect.getsource(validation),
            inspect.getsource(oracle),
        )
    )
    for forbidden in (
        "from_fixture",
        "promote_fixture",
        "convert_fixture",
        "retag_fixture",
    ):
        assert forbidden not in combined
    for issuer in (
        execution._issue_fixture_execution_specification,
        validation._issue_fixture_pytest_plan,
        oracle._issue_fixture_oracle_plan,
    ):
        assert "trust_domain" not in inspect.signature(issuer).parameters
    for production_issuer in cast(
        tuple[Callable[..., object], ...],
        (
            execution._issue_production_execution_plan_drafts,
            validation._issue_production_pytest_plan_draft,
            oracle._issue_production_oracle_plan_draft,
        ),
    ):
        assert not hasattr(production_issuer, "__wrapped__")
        try:
            parameters = inspect.signature(production_issuer).parameters
        except (TypeError, ValueError):
            continue
        assert "trust_domain" not in parameters
    bundle = _canonical_plan_set()
    assert type(bundle.run) is stage1._FixtureValidationRun
    assert type(bundle.executor_implementation) is (
        execution._FixtureExecutorImplementationIdentity
    )
    assert type(bundle.plans[0]) is validation._FixturePytestPlan
    assert type(bundle.plans[1]) is oracle._FixtureOraclePlan
    assert all(type(plan) is execution._FixtureExecutionSpecification for plan in bundle.plans[2:])


def test_i_stale_plan_and_authority_capabilities_are_unreadable() -> None:
    bundle = _canonical_plan_set()
    stage1._invalidate_plan(bundle.plans[3])
    with _expect_stage1_error("ISSUED_PLAN_STALE"):
        stage1.plan_persistent_id(bundle.plans[3])
    with _expect_stage1_error("ISSUED_PLAN_STALE"):
        stage1._issue_fixture_authority(
            context=bundle.context,
            validation_run=bundle.run,
            plans=bundle.plans,
        )

    stage1._reset_fixture_registries()
    bundle = _canonical_plan_set()
    authority = stage1._issue_fixture_authority(
        context=bundle.context,
        validation_run=bundle.run,
        plans=bundle.plans,
    )
    current = stage1._FIXTURE_AUTHORITY_RECORDS[authority]
    stage1._FIXTURE_AUTHORITY_RECORDS[authority] = replace(current, active=False)
    with _expect_stage1_error("VALIDATION_AUTHORITY_NOT_CURRENT"):
        stage1._fixture_validation_authority_id(authority)


def test_j_stage1_control_paths_bind_without_any_workload_call(
    _isolated_stage1_and_no_workload: dict[str, int],
) -> None:
    bundle = _canonical_plan_set()
    stage1._issue_fixture_authority(
        context=bundle.context,
        validation_run=bundle.run,
        plans=bundle.plans,
    )
    assert all(count == 0 for count in _isolated_stage1_and_no_workload.values())


def test_j_unbound_and_bound_plans_are_explicitly_nonexecutable() -> None:
    bundle = _canonical_plan_set()
    with _expect_stage1_error("ISSUED_PLAN_AUTHORITY_MISMATCH"):
        stage1.assert_stage1_plan_not_executable(bundle.plans[2])
    stage1._issue_fixture_authority(
        context=bundle.context,
        validation_run=bundle.run,
        plans=bundle.plans,
    )
    with _expect_stage1_error("P2_STAGE3_EXECUTION_NOT_IMPLEMENTED"):
        stage1.assert_stage1_plan_not_executable(bundle.plans[2])


def test_j_production_components_expose_no_jobs_callable_role_or_layer0_overrides() -> None:
    execution_issuer = execution._issue_production_execution_plan_drafts
    assert not hasattr(execution_issuer, "__wrapped__")
    with pytest.raises((TypeError, ValueError)):
        inspect.signature(execution_issuer)
    attested_code = cast(
        tuple[object, object, object, CodeType], cast(Any, execution_issuer)._rde_opaque_source
    )[3]
    execution_parameters = set(
        attested_code.co_varnames[: attested_code.co_argcount + attested_code.co_kwonlyargcount]
    )
    assert execution_parameters == {
        "preparation",
        "context",
        "validation_run",
        "executor_implementation",
    }
    assert not {"jobs", "function", "role", "purpose", "configuration"} & execution_parameters
    for issuer in (
        validation._issue_production_pytest_plan_draft,
        oracle._issue_production_oracle_plan_draft,
    ):
        assert not hasattr(issuer, "__wrapped__")
        try:
            parameters = inspect.signature(issuer).parameters
        except (TypeError, ValueError):
            continue
        assert "projection" not in parameters
    preparation_parameters = inspect.signature(stage1._prepare_production_stage1).parameters
    assert not {
        "context",
        "validation_run_id",
        "implementation",
        "runtime",
        "jobs",
        "callable",
    } & set(preparation_parameters)
    source = inspect.getsource(stage1._prepare_production_stage1)
    assert "collaborators.derive_context" in source
    assert "collaborators.reserve_run" in source
    assert "execute_deterministic_map(" not in source
    assert "execute_oracle_conformance(" not in source
    assert "execute_pytest_validation(" not in source
