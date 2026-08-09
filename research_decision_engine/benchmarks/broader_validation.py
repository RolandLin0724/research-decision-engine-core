"""Exact-issued pytest validation evidence for the broader replication.

The public runner owns the complete pytest command.  A plugin loaded in the
pytest subprocess emits a nonce-bound execution receipt, and this module keeps
the exact JUnit bytes behind an opaque, process-local result object.  Callers
can observe or copy issued evidence, but cannot construct validation claims.
"""

from __future__ import annotations

import atexit
import configparser
import errno
import hashlib
import importlib
import importlib.metadata as importlib_metadata
import json
import os
import platform
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import xml.etree.ElementTree as ElementTree
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import BuiltinFunctionType, MappingProxyType, ModuleType
from typing import Any, Final, Literal, NoReturn, Protocol, SupportsIndex, cast

from research_decision_engine.benchmarks.broader_protocol import (
    DESIGN_FILENAME,
    PROTOCOL_CHECKPOINT,
    PUBLIC_PROVENANCE_ROLE_TOKENS,
    SOURCE_CHECKPOINT,
    canonical_json_bytes,
    protocol_hash,
    repository_root,
)
from research_decision_engine.benchmarks.broader_validation_evidence import (
    EVIDENCE_CONTRACT_CHECKPOINT,
    STUDY_ID,
    FileProjection,
    ImplementationProjection,
    Layer0Context,
    P2Stage1Error,
    RuntimeProjection,
    ValidationRun,
    _allocate_production_plan_capability,
    _fixture_validation_run_id,
    _FixtureValidationRun,
    _opaque_runtime_callable,
    _PlanDraft,
    _production_validation_run_id,
    _ProductionPreparationCapability,
    _record_production_plan_draft,
    _register_fixture_plan,
    _require_production_preparation,
    _seal_production_component_callable,
)

PYTEST_VALIDATION_VERSION: Final = "broader-pytest-validation/v1"
DEFAULT_PYTEST_TIMEOUT_SECONDS: Final = 10_800.0
MAX_PYTEST_TIMEOUT_SECONDS: Final = 10_800.0

type PytestValidationIssuerKind = Literal["production", "fixture"]
type PytestValidationExecutionStatus = Literal["COMPLETED", "FAILED"]

_PLUGIN_NAME: Final = "research_decision_engine.benchmarks.broader_validation"
_ENV_PREFIX: Final = "RDE_BROADER_PYTEST_VALIDATION_"
_ENV_NONCE: Final = f"{_ENV_PREFIX}NONCE"
_ENV_RUN_IDENTITY: Final = f"{_ENV_PREFIX}RUN_IDENTITY"
_ENV_COMMAND_SHA256: Final = f"{_ENV_PREFIX}COMMAND_SHA256"
_ENV_START_SEED_IDENTITY: Final = f"{_ENV_PREFIX}START_SEED_IDENTITY"
_ENV_SPECIFICATION_PATH: Final = f"{_ENV_PREFIX}SPECIFICATION_PATH"
_ENV_START_RECEIPT_PATH: Final = f"{_ENV_PREFIX}START_RECEIPT_PATH"
_ENV_RECEIPT_PATH: Final = f"{_ENV_PREFIX}RECEIPT_PATH"
_ENV_JUNIT_PATH: Final = f"{_ENV_PREFIX}JUNIT_PATH"
_CONTROLLED_SUBPROCESS_ENVIRONMENT: Final = (
    ("COVERAGE_PROCESS_START", None),
    ("PYTEST_ADDOPTS", None),
    ("PYTEST_CURRENT_TEST", None),
    ("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1"),
    ("PYTEST_PLUGINS", None),
    ("PYTEST_VERSION", None),
    ("PYTHONHASHSEED", "0"),
    ("PYTHONHOME", None),
    ("PYTHONNOUSERSITE", "1"),
    ("PYTHONPATH", None),
    ("PYTHONSAFEPATH", "1"),
    ("PYTHONSTARTUP", None),
)
_RESULT_CONSTRUCTION_KEY: Final = object()
_OWNER_CLAIM_CONSTRUCTION_KEY: Final = object()
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_START_RECEIPT_WAIT_SECONDS: Final = 30.0
_TERMINATION_WAIT_SECONDS: Final = 10.0
_AUTHORITATIVE_JUNIT_PLUGIN_NAME: Final = "rde-authoritative-junitxml"

type PluginIdentity = tuple[
    str,
    str,
    str,
    str | None,
    str | None,
    str | None,
    str | None,
]
type FileIdentity = tuple[int, int]
type PluginLifecycleAction = Literal["register", "unregister"]


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class _RetainedJunitHandle:
    """Exact open JUnit control resource owned by one Stage-1 session."""

    descriptor: int
    destination_path: Path
    control_directory: Path
    control_directory_identity: FileIdentity
    file_identity: FileIdentity
    initial_sha256: str
    initial_byte_count: int

    def __copy__(self) -> NoReturn:
        raise TypeError("Retained JUnit handles cannot be copied.")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("Retained JUnit handles cannot be deep-copied.")

    def __reduce__(self) -> NoReturn:
        raise TypeError("Retained JUnit handles cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Retained JUnit handles cannot be serialized.")


@dataclass(frozen=True, slots=True, eq=False)
class _ProvisionalJunitHandle:
    """Internal token registered before retained-JUnit creation can continue."""

    destination_path: Path
    control_directory: Path
    control_directory_identity: FileIdentity

    def __copy__(self) -> NoReturn:
        raise TypeError("Provisional JUnit handles cannot be copied.")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("Provisional JUnit handles cannot be deep-copied.")

    def __reduce__(self) -> NoReturn:
        raise TypeError("Provisional JUnit handles cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Provisional JUnit handles cannot be serialized.")


@dataclass(frozen=True, slots=True)
class _PluginLifecycleEvent:
    sequence: int
    action: PluginLifecycleAction
    plugin_identity: PluginIdentity


@dataclass(slots=True)
class _PluginLifecycleTracker:
    manager: object
    events: tuple[_PluginLifecycleEvent, ...]
    lock: threading.RLock
    original_unregister: Callable[..., object] | None
    guarded_unregister: Callable[..., object] | None


_PYTEST_CONFIGURE_RUNTIME_PLUGINS: Final[tuple[tuple[str, str, str], ...]] = (
    ("runtime:_pytest.config:PytestPluginManager", "_pytest.config", "PytestPluginManager"),
    ("pytestconfig", "_pytest.config", "Config"),
    ("session", "_pytest.main", "Session"),
    ("capturemanager", "_pytest.capture", "CaptureManager"),
    ("terminalreporter", "_pytest.terminal", "TerminalReporter"),
    ("terminalprogress", "_pytest.terminalprogress", "_pytest.terminalprogress"),
    ("lfplugin", "_pytest.cacheprovider", "LFPlugin"),
    ("nfplugin", "_pytest.cacheprovider", "NFPlugin"),
    ("legacypath-tmpdir", "_pytest.legacypath", "LegacyTmpdirPlugin"),
    ("logging-plugin", "_pytest.logging", "LoggingPlugin"),
    (
        _AUTHORITATIVE_JUNIT_PLUGIN_NAME,
        _PLUGIN_NAME,
        "_AuthoritativeLogXML",
    ),
)
_PYTEST_SESSION_RUNTIME_PLUGINS: Final[tuple[tuple[str, str, str], ...]] = (
    ("funcmanage", "_pytest.fixtures", "FixtureManager"),
)


class PytestValidationError(ValueError):
    """Raised when pytest evidence was not issued or no longer reconciles."""


class _PytestExecutionSpecification:
    """Opaque exact-issued P2 pytest plan, migrated from the internal specification slot."""

    __slots__ = ()

    def __new__(cls) -> _PytestExecutionSpecification:
        raise TypeError("P2 pytest plans have no public constructor.")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("P2 pytest plans cannot be subclassed.")

    def __copy__(self) -> NoReturn:
        raise TypeError("P2 pytest plans cannot be copied.")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("P2 pytest plans cannot be deep-copied.")

    def __reduce__(self) -> NoReturn:
        raise TypeError("P2 pytest plans cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("P2 pytest plans cannot be serialized.")


PytestPlan = _PytestExecutionSpecification


class _FixturePytestPlan:
    """Opaque fixture-only pytest plan, disjoint from production authority."""

    __slots__ = ()

    def __new__(cls) -> _FixturePytestPlan:
        raise TypeError("Fixture pytest plans have no public constructor.")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("Fixture pytest plans cannot be subclassed.")

    def __copy__(self) -> NoReturn:
        raise TypeError("Fixture pytest plans cannot be copied.")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("Fixture pytest plans cannot be deep-copied.")

    def __reduce__(self) -> NoReturn:
        raise TypeError("Fixture pytest plans cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Fixture pytest plans cannot be serialized.")


@dataclass(frozen=True, slots=True)
class PytestControlledEnvironmentRow:
    action: Literal["set", "unset"]
    name: str
    value: str | None

    def as_dict(self) -> dict[str, object]:
        return {"action": self.action, "name": self.name, "value": self.value}


@dataclass(frozen=True, slots=True)
class PytestEnvironmentRow:
    name: str
    name_sha256: str
    value_byte_count: int
    value_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "name_sha256": self.name_sha256,
            "value_byte_count": self.value_byte_count,
            "value_sha256": self.value_sha256,
        }


@dataclass(frozen=True, slots=True)
class PytestPluginProjection:
    distribution_name: str | None
    distribution_version: str | None
    module_name: str
    plugin_name: str
    qualname: str
    source_path: str | None
    source_sha256: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "distribution_name": self.distribution_name,
            "distribution_version": self.distribution_version,
            "module_name": self.module_name,
            "plugin_name": self.plugin_name,
            "qualname": self.qualname,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
        }


@dataclass(frozen=True, slots=True)
class PytestControlPathsProjection:
    completion_receipt_path: str
    specification_path: str
    start_receipt_path: str

    def as_dict(self) -> dict[str, object]:
        return {
            "completion_receipt_path": self.completion_receipt_path,
            "specification_path": self.specification_path,
            "start_receipt_path": self.start_receipt_path,
        }


@dataclass(frozen=True, slots=True)
class PytestJunitDestinationProjection:
    destination_path: str
    device_id: int
    file_id: int
    initial_sha256: str
    mode: str = "exclusive-precreated-retained-handle"
    writer: str = "rde-authoritative-junitxml"
    final_evidence_filename: str = "pytest-junit.xml"
    initial_byte_count: int = 32

    def as_dict(self) -> dict[str, object]:
        return {
            "destination_path": self.destination_path,
            "device_id": self.device_id,
            "file_id": self.file_id,
            "final_evidence_filename": self.final_evidence_filename,
            "initial_byte_count": self.initial_byte_count,
            "initial_sha256": self.initial_sha256,
            "mode": self.mode,
            "writer": self.writer,
        }


@dataclass(frozen=True, slots=True)
class PytestRuntimeProjection:
    pluggy_source: FileProjection
    pluggy_version: str
    pytest_source: FileProjection
    pytest_version: str
    validation_plugin_source: FileProjection

    def as_dict(self) -> dict[str, object]:
        return {
            "pluggy_source": self.pluggy_source.as_dict(),
            "pluggy_version": self.pluggy_version,
            "pytest_source": self.pytest_source.as_dict(),
            "pytest_version": self.pytest_version,
            "validation_plugin_source": self.validation_plugin_source.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class PytestSelectedTestProjection:
    kind: Literal["path", "node_id"]
    value: str

    def as_dict(self) -> dict[str, object]:
        return {self.kind: self.value, "kind": self.kind}


@dataclass(frozen=True, slots=True)
class PytestPlanProjection:
    argv: tuple[str, ...]
    conftests: tuple[FileProjection, ...]
    control_paths: PytestControlPathsProjection
    controlled_environment: tuple[PytestControlledEnvironmentRow, ...]
    environment: tuple[PytestEnvironmentRow, ...]
    environment_sha256: str
    evidence_contract_checkpoint: str
    implementation: ImplementationProjection
    junit_destination: PytestJunitDestinationProjection
    plan_issuer_identity: str
    plugins: tuple[PytestPluginProjection, ...]
    protocol_checkpoint: str
    pytest_configuration: FileProjection
    pytest_rootdir: str
    pytest_runtime: PytestRuntimeProjection
    repository_root: str
    runtime: RuntimeProjection
    runtime_identity: str
    selected_tests: tuple[PytestSelectedTestProjection, ...]
    validation_run_id: str
    working_directory: str
    schema_version: str = "broader-replication-pytest-plan/v1"
    reserved_environment_prefix: str = "RDE_BROADER_PYTEST_VALIDATION_"
    study_id: str = STUDY_ID

    def as_dict(self) -> dict[str, object]:
        return {
            "argv": list(self.argv),
            "conftests": [item.as_dict() for item in self.conftests],
            "control_paths": self.control_paths.as_dict(),
            "controlled_environment": [item.as_dict() for item in self.controlled_environment],
            "environment": [item.as_dict() for item in self.environment],
            "environment_sha256": self.environment_sha256,
            "evidence_contract_checkpoint": self.evidence_contract_checkpoint,
            "expected_completion": {
                "allow_skips": True,
                "deselection_allowed": False,
                "errors": 0,
                "failed": 0,
                "failure_details_count": 0,
                "required_exit_code": 0,
                "required_status": "COMPLETED",
                "termination_state": "normal_exit",
                "timed_out": False,
            },
            "implementation": self.implementation.as_dict(),
            "junit_destination": self.junit_destination.as_dict(),
            "plan_issuer_identity": self.plan_issuer_identity,
            "plugins": [item.as_dict() for item in self.plugins],
            "protocol_checkpoint": self.protocol_checkpoint,
            "pytest_configuration": self.pytest_configuration.as_dict(),
            "pytest_rootdir": self.pytest_rootdir,
            "pytest_runtime": self.pytest_runtime.as_dict(),
            "repository_root": self.repository_root,
            "reserved_environment_prefix": self.reserved_environment_prefix,
            "runtime": self.runtime.as_dict(),
            "runtime_identity": self.runtime_identity,
            "schema_version": self.schema_version,
            "selected_tests": [item.as_dict() for item in self.selected_tests],
            "study_id": self.study_id,
            "timeout_policy": {
                "completion_receipt_timeout_ms": 10000,
                "kill_grace_ms": 10000,
                "on_timeout": "terminate-then-kill-and-fail",
                "start_receipt_timeout_ms": 30000,
                "wall_timeout_ms": 10800000,
            },
            "validation_run_id": self.validation_run_id,
            "working_directory": self.working_directory,
        }


class PytestValidationResult:
    """Opaque capability issued only after an actual pytest subprocess."""

    __slots__ = ()

    def __new__(cls, construction_key: object | None = None) -> PytestValidationResult:
        if construction_key is not _RESULT_CONSTRUCTION_KEY:
            raise TypeError("Pytest validation results are issued only by actual execution.")
        return super().__new__(cls)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("Pytest validation results cannot be subclassed.")

    def __copy__(self) -> NoReturn:
        raise TypeError("Pytest validation results cannot be copied.")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("Pytest validation results cannot be deep-copied.")

    def __reduce__(self) -> NoReturn:
        raise TypeError("Pytest validation results cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Pytest validation results cannot be serialized.")


class PytestValidationOwnerClaim:
    """Opaque, registry-bound authority for one claimed validation result."""

    __slots__ = ()

    def __new__(cls, construction_key: object | None = None) -> PytestValidationOwnerClaim:
        if construction_key is not _OWNER_CLAIM_CONSTRUCTION_KEY:
            raise TypeError("Pytest validation owner claims are issued only by the registry.")
        return super().__new__(cls)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("Pytest validation owner claims cannot be subclassed.")

    def __copy__(self) -> NoReturn:
        raise TypeError("Pytest validation owner claims cannot be copied.")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("Pytest validation owner claims cannot be deep-copied.")

    def __reduce__(self) -> NoReturn:
        raise TypeError("Pytest validation owner claims cannot be serialized.")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("Pytest validation owner claims cannot be serialized.")


@dataclass(frozen=True, slots=True)
class PytestValidationObservation:
    """Immutable facts independently observed from one pytest execution."""

    validation_version: str
    issuer_kind: PytestValidationIssuerKind
    execution_status: PytestValidationExecutionStatus
    validation_run_identity: str
    execution_specification_identity: str
    implementation_repository_root: str
    pytest_root_directory: str
    pytest_config_path: str
    pytest_working_directory: str
    pytest_test_selection: tuple[str, ...]
    implementation_commit: str
    design_checkpoint_commit: str
    source_design_sha256: str
    implementation_tree_sha256: str
    implementation_diff_sha256: str
    broader_source_sha256: str
    complete_test_bundle_sha256: str
    command: tuple[str, ...]
    command_sha256: str
    interpreter_path: str
    interpreter_executable_sha256: str
    base_interpreter_path: str
    base_interpreter_executable_sha256: str
    uv_lock_sha256: str
    interpreter_identity_sha256: str
    platform_identity_sha256: str
    pytest_version: str
    pytest_source_sha256: str
    pluggy_version: str
    pluggy_source_sha256: str
    validation_plugin_source_sha256: str
    subprocess_environment_sha256: str
    effective_plugin_identities: tuple[PluginIdentity, ...]
    effective_conftest_identities: tuple[tuple[str, str], ...]
    subprocess_start_identity: str | None
    subprocess_completion_identity: str | None
    junit_xml_path: str
    junit_xml_sha256: str | None
    junit_xml_byte_count: int
    total: int
    passed: int
    skipped: int
    failed: int
    errors: int
    runtime_seconds: str | None
    collected_node_ids: tuple[str, ...]
    deselected_node_ids: tuple[str, ...]
    junit_case_identities: tuple[str, ...]
    skipped_node_ids: tuple[str, ...]
    skipped_reasons: tuple[str, ...]
    exit_code: int | None
    completed: bool
    failure_details: tuple[str, ...]
    result_identity: str


@dataclass(frozen=True, slots=True)
class _CurrentValidationIdentities:
    implementation_commit: str
    design_checkpoint_commit: str
    source_design_sha256: str
    implementation_tree_sha256: str
    implementation_diff_sha256: str
    broader_source_sha256: str
    complete_test_bundle_sha256: str
    uv_lock_sha256: str
    interpreter_identity_sha256: str
    platform_identity_sha256: str


@dataclass(frozen=True, slots=True)
class _HistoricalPytestExecutionSpecification:
    """Historical P1 subprocess specification; never a P2 plan authority."""

    validation_version: str
    issuer_kind: PytestValidationIssuerKind
    validation_run_identity: str
    implementation_repository_root: str
    pytest_root_directory: str
    pytest_config_path: str
    pytest_config_sha256: str
    pytest_working_directory: str
    pytest_test_selection: tuple[str, ...]
    selection_source_sha256: str
    junit_xml_path: str
    junit_initial_sha256: str
    junit_initial_byte_count: int
    junit_file_identity: FileIdentity
    command: tuple[str, ...]
    command_sha256: str
    controlled_environment: tuple[tuple[str, str | None], ...]
    implementation_commit: str
    implementation_tree_sha256: str
    implementation_diff_sha256: str
    broader_source_sha256: str
    complete_test_bundle_sha256: str
    uv_lock_sha256: str
    interpreter_path: str
    interpreter_executable_sha256: str
    base_interpreter_path: str
    base_interpreter_executable_sha256: str
    interpreter_identity_sha256: str
    platform_identity_sha256: str
    pytest_version: str
    pytest_source_sha256: str
    pluggy_version: str
    pluggy_source_sha256: str
    validation_plugin_path: str
    validation_plugin_source_sha256: str
    subprocess_environment_sha256: str
    expected_conftest_identities: tuple[tuple[str, str], ...]
    expected_ephemeral_plugin_identities: tuple[PluginIdentity, ...]
    expected_initial_plugin_identities: tuple[PluginIdentity, ...]
    expected_final_plugin_identities: tuple[PluginIdentity, ...]
    configuration_boundary_sha256: str
    execution_specification_identity: str


@dataclass(frozen=True, slots=True)
class _ObservedPytestConfiguration:
    root_directory: str
    config_path: str | None
    invocation_directory: str
    invocation_arguments: tuple[str, ...]
    resolved_arguments: tuple[str, ...]
    testpaths: tuple[str, ...]
    addopts: tuple[str, ...]


@dataclass(slots=True)
class _AuthoritativeProcessObserver:
    launcher_pid: int
    plugin_pid: int
    topology: Literal["direct", "launcher-child"]
    retained_handle: int | None
    os_image_path: str
    os_image_sha256: str


@dataclass(slots=True)
class _IssuedPytestValidationResult:
    result: PytestValidationResult
    observation: PytestValidationObservation
    observation_fingerprint: str
    specification: _HistoricalPytestExecutionSpecification
    specification_fingerprint: str
    junit_xml_bytes: bytes
    evidence_bundle_identity: str | None
    owner_claim: PytestValidationOwnerClaim | None
    active: bool


@dataclass(frozen=True, slots=True)
class _JunitObservation:
    exact_bytes: bytes
    sha256: str
    byte_count: int
    total: int
    passed: int
    skipped: int
    failed: int
    errors: int
    runtime_seconds: str
    case_identities: tuple[str, ...]
    node_ids: tuple[str, ...]
    skipped_node_ids: tuple[str, ...]
    skipped_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _PluginSkip:
    node_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class _PendingPytestCompletion:
    config: object
    exit_code: int
    failure_details: tuple[str, ...]
    junit: _JunitObservation | None
    junit_writer_identity: str | None
    session_plugin_identities: tuple[PluginIdentity, ...]
    observed_configuration: _ObservedPytestConfiguration
    collected_node_ids: tuple[str, ...]
    deselected_node_ids: tuple[str, ...]
    skips: tuple[_PluginSkip, ...]


@dataclass(slots=True)
class _PluginState:
    nonce: str
    validation_run_identity: str
    command_sha256: str
    start_seed_identity: str
    execution_specification_identity: str
    start_receipt_path: Path
    receipt_path: Path
    junit_path: Path
    junit_file_identity: FileIdentity
    junit_file_descriptor: int
    pid: int
    parent_pid: int
    argv_tail: tuple[str, ...]
    plugin_source_sha256: str
    pytest_version: str
    pytest_source_sha256: str
    pluggy_version: str
    pluggy_source_sha256: str
    interpreter_path: str
    interpreter_executable_sha256: str
    base_interpreter_path: str
    base_interpreter_executable_sha256: str
    observed_configuration: _ObservedPytestConfiguration
    controlled_environment: tuple[tuple[str, str | None], ...]
    subprocess_environment_sha256: str
    subprocess_start_identity: str
    start_receipt_sha256: str
    initial_plugin_identities: tuple[PluginIdentity, ...]
    initial_plugin_lifecycle_events: tuple[_PluginLifecycleEvent, ...]
    plugin_lifecycle_start_identity: str
    plugin_lifecycle_tracker: _PluginLifecycleTracker
    skips: list[_PluginSkip]
    skipped_node_ids: set[str]
    collected_node_ids: list[str]
    deselected_node_ids: list[str]
    pending_completion: _PendingPytestCompletion | None
    terminal_callback_pid: int
    terminalized: bool


class _PytestReport(Protocol):
    nodeid: str
    skipped: bool
    longrepr: object


class _PytestItem(Protocol):
    nodeid: str


class _PytestSession(Protocol):
    config: object
    items: list[_PytestItem]


class _ProcessMonitor(Protocol):
    pid: int

    def poll(self) -> int | None: ...


_ISSUED_RESULTS: dict[int, _IssuedPytestValidationResult] = {}
_USED_VALIDATION_RUN_IDENTITIES: set[str] = set()
_USED_EVIDENCE_BUNDLE_IDENTITIES: set[str] = set()
_RESULT_LOCK = threading.RLock()
_PLUGIN_STATE: _PluginState | None = None
_PLUGIN_LIFECYCLE_TRACKERS: dict[int, _PluginLifecycleTracker] = {}


def _regular_single_link_file_identity(status: os.stat_result, label: str) -> FileIdentity:
    if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
        raise PytestValidationError(f"{label} is not one private regular file.")
    if status.st_dev < 0 or status.st_ino <= 0:
        raise PytestValidationError(f"{label} has no stable filesystem identity.")
    return status.st_dev, status.st_ino


def _private_directory_identity(status: os.stat_result, label: str) -> FileIdentity:
    if not stat.S_ISDIR(status.st_mode):
        raise PytestValidationError(f"{label} is not a private directory.")
    if status.st_dev < 0 or status.st_ino <= 0:
        raise PytestValidationError(f"{label} has no stable filesystem identity.")
    return status.st_dev, status.st_ino


def _path_is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _validate_retained_junit_handle_identity(handle: _RetainedJunitHandle) -> None:
    if type(handle) is not _RetainedJunitHandle:
        raise PytestValidationError("Exact retained JUnit handle required.")
    if type(handle.descriptor) is not int or handle.descriptor < 0:
        raise PytestValidationError("Retained JUnit descriptor is invalid.")
    if (
        not isinstance(handle.destination_path, Path)
        or not isinstance(handle.control_directory, Path)
        or type(handle.control_directory_identity) is not tuple
        or len(handle.control_directory_identity) != 2
        or any(type(value) is not int for value in handle.control_directory_identity)
        or type(handle.file_identity) is not tuple
        or len(handle.file_identity) != 2
        or any(type(value) is not int for value in handle.file_identity)
        or type(handle.initial_sha256) is not str
        or _HEX_SHA256.fullmatch(handle.initial_sha256) is None
        or type(handle.initial_byte_count) is not int
        or handle.initial_byte_count != 32
    ):
        raise PytestValidationError("Retained JUnit handle metadata is malformed.")
    if (
        handle.destination_path.parent != handle.control_directory
        or _path_is_link_like(handle.control_directory)
        or _private_directory_identity(
            handle.control_directory.stat(follow_symlinks=False),
            "retained JUnit control directory",
        )
        != handle.control_directory_identity
        or _path_is_link_like(handle.destination_path)
    ):
        raise PytestValidationError("Retained JUnit control path changed after creation.")
    descriptor_status = os.fstat(handle.descriptor)
    path_status = handle.destination_path.stat(follow_symlinks=False)
    if (
        _regular_single_link_file_identity(descriptor_status, "retained JUnit handle")
        != handle.file_identity
        or _regular_single_link_file_identity(path_status, "retained JUnit path")
        != handle.file_identity
    ):
        raise PytestValidationError("Retained JUnit file identity changed after creation.")


def _validate_retained_junit_handle(handle: _RetainedJunitHandle) -> None:
    _validate_retained_junit_handle_identity(handle)
    if os.fstat(handle.descriptor).st_size != handle.initial_byte_count:
        raise PytestValidationError("Retained JUnit creation seed size changed after creation.")
    raw = _read_file_descriptor(handle.descriptor)
    if (
        len(raw) != handle.initial_byte_count
        or hashlib.sha256(raw).hexdigest() != handle.initial_sha256
    ):
        raise PytestValidationError("Retained JUnit creation seed changed after creation.")


def _install_retained_junit_operations() -> tuple[
    Callable[..., _RetainedJunitHandle],
    Callable[[object], bool],
    Callable[[object], bool],
    Callable[..., None],
    Callable[..., object],
    Callable[..., object],
    Callable[..., object],
]:
    """Issue and clean only exact retained JUnit resources from one authority."""

    handle_type = _RetainedJunitHandle
    provisional_handle_type = _ProvisionalJunitHandle

    class HandleState:
        __slots__ = (
            "control_directory",
            "control_directory_identity",
            "control_directory_path",
            "control_directory_removed",
            "creation_complete",
            "descriptor",
            "descriptor_closed",
            "descriptor_close_in_progress",
            "descriptor_owner",
            "destination",
            "destination_path",
            "destination_removed",
            "destination_unlink_in_progress",
            "file_identity",
            "initial_byte_count",
            "initial_sha256",
            "ownership_state",
        )

        def __init__(
            self,
            *,
            descriptor: int,
            descriptor_owner: object,
            destination_path: Path,
            destination: str,
            control_directory_path: Path,
            control_directory: str,
            control_directory_identity: FileIdentity,
            file_identity: FileIdentity,
            initial_sha256: str,
            initial_byte_count: int,
        ) -> None:
            self.descriptor = descriptor
            self.descriptor_owner = descriptor_owner
            self.destination_path = destination_path
            self.destination = destination
            self.control_directory_path = control_directory_path
            self.control_directory = control_directory
            self.control_directory_identity = control_directory_identity
            self.file_identity = file_identity
            self.initial_sha256 = initial_sha256
            self.initial_byte_count = initial_byte_count
            self.descriptor_closed = False
            self.descriptor_close_in_progress = False
            self.destination_removed = False
            self.destination_unlink_in_progress = False
            self.control_directory_removed = False
            self.creation_complete = False
            self.ownership_state: Literal[
                "acquired",
                "centrally_registered",
                "retained",
                "transferred_for_later_execution",
                "released",
                "cleanup_pending",
                "cleanup_complete",
            ] = "acquired"

    class ProvisionalState:
        __slots__ = (
            "control_directory",
            "control_directory_identity",
            "descriptor",
            "descriptor_acquisition_state",
            "descriptor_closed",
            "descriptor_close_in_progress",
            "descriptor_owner",
            "destination",
            "destination_removed",
            "destination_unlink_in_progress",
            "destination_absence_verified",
            "file_identity",
            "ownership_state",
            "promoted_handle",
        )

        def __init__(
            self,
            *,
            destination: str,
            control_directory: str,
            control_directory_identity: FileIdentity,
        ) -> None:
            self.destination = destination
            self.control_directory = control_directory
            self.control_directory_identity = control_directory_identity
            self.descriptor: int | None = None
            self.descriptor_owner: object | None = None
            self.descriptor_acquisition_state: Literal[
                "not_started",
                "open_in_progress",
                "opened",
                "open_failed",
            ] = "not_started"
            self.descriptor_closed = False
            self.descriptor_close_in_progress = False
            self.destination_removed = False
            self.destination_unlink_in_progress = False
            self.destination_absence_verified = False
            self.file_identity: FileIdentity | None = None
            self.promoted_handle: _RetainedJunitHandle | None = None
            self.ownership_state: Literal[
                "acquired",
                "centrally_registered",
                "retained",
                "transferred_for_later_execution",
                "released",
                "cleanup_pending",
                "cleanup_complete",
            ] = "acquired"

    error_type = PytestValidationError
    hex_sha256 = _HEX_SHA256
    path_type = Path
    concrete_path_type = type(path_type("."))
    authority_lock = threading.RLock()
    issued_states: dict[_RetainedJunitHandle, HandleState] = {}
    provisional_states: dict[_ProvisionalJunitHandle, ProvisionalState] = {}
    quarantined_descriptor_owners: list[object] = []
    cleanup_failure_remaining: ContextVar[int] = ContextVar(
        "rde_retained_junit_cleanup_failure_remaining",
        default=0,
    )
    provisional_identity_failure_remaining: ContextVar[int] = ContextVar(
        "rde_provisional_junit_identity_failure_remaining",
        default=0,
    )
    post_unlink_failure_remaining: ContextVar[int] = ContextVar(
        "rde_retained_junit_post_unlink_failure_remaining",
        default=0,
    )
    os_close = os.close
    os_fstat = os.fstat
    os_fspath = os.fspath
    os_fsync = os.fsync
    os_get_inheritable = os.get_inheritable
    os_lseek = os.lseek
    os_read = os.read
    os_rmdir = os.rmdir
    os_scandir = os.scandir
    os_set_inheritable = os.set_inheritable
    os_stat = os.stat
    os_unlink = os.unlink
    os_write = os.write
    open_file = open
    os_pread = cast(Callable[[int, int, int], bytes] | None, getattr(os, "pread", None))
    path_dirname = os.path.dirname
    path_isjunction = cast(
        Callable[[str], bool] | None,
        getattr(os.path, "isjunction", None),
    )
    stat_isdir = stat.S_ISDIR
    stat_islink = stat.S_ISLNK
    stat_isreg = stat.S_ISREG
    sha256 = hashlib.sha256
    file_not_found_type = FileNotFoundError
    os_error_type = OSError
    bad_descriptor_errno = errno.EBADF
    seek_current = os.SEEK_CUR
    seek_set = os.SEEK_SET

    def identity(status: os.stat_result) -> FileIdentity:
        return status.st_dev, status.st_ino

    def is_owned_regular_file(status: os.stat_result, expected: FileIdentity) -> bool:
        return (
            stat_isreg(status.st_mode)
            and status.st_nlink == 1
            and status.st_dev >= 0
            and status.st_ino > 0
            and identity(status) == expected
        )

    def is_owned_directory(status: os.stat_result, expected: FileIdentity) -> bool:
        return (
            stat_isdir(status.st_mode)
            and status.st_dev >= 0
            and status.st_ino > 0
            and identity(status) == expected
        )

    def regular_file_identity(status: os.stat_result, label: str) -> FileIdentity:
        if (
            not stat_isreg(status.st_mode)
            or status.st_nlink != 1
            or status.st_dev < 0
            or status.st_ino <= 0
        ):
            raise error_type(f"{label} is not one private regular file.")
        return identity(status)

    def directory_identity(status: os.stat_result, label: str) -> FileIdentity:
        if not stat_isdir(status.st_mode) or status.st_dev < 0 or status.st_ino <= 0:
            raise error_type(f"{label} is not one private directory.")
        return identity(status)

    def is_link_like(path: str, status: os.stat_result) -> bool:
        return stat_islink(status.st_mode) or bool(
            path_isjunction is not None and path_isjunction(path)
        )

    def metadata_matches(handle: _RetainedJunitHandle, state: HandleState) -> bool:
        try:
            return (
                type(handle.descriptor) is int
                and handle.descriptor == state.descriptor
                and type(handle.destination_path) is concrete_path_type
                and handle.destination_path == state.destination_path
                and os_fspath(handle.destination_path) == state.destination
                and type(handle.control_directory) is concrete_path_type
                and handle.control_directory == state.control_directory_path
                and os_fspath(handle.control_directory) == state.control_directory
                and type(handle.file_identity) is tuple
                and handle.file_identity == state.file_identity
                and len(handle.file_identity) == 2
                and all(type(value) is int for value in handle.file_identity)
                and type(handle.control_directory_identity) is tuple
                and handle.control_directory_identity == state.control_directory_identity
                and len(handle.control_directory_identity) == 2
                and all(type(value) is int for value in handle.control_directory_identity)
                and type(handle.initial_sha256) is str
                and handle.initial_sha256 == state.initial_sha256
                and hex_sha256.fullmatch(handle.initial_sha256) is not None
                and type(handle.initial_byte_count) is int
                and handle.initial_byte_count == state.initial_byte_count == 32
                and path_dirname(state.destination) == state.control_directory
            )
        except (AttributeError, TypeError, ValueError):
            return False

    def issued_state(
        handle: object,
    ) -> tuple[_RetainedJunitHandle, HandleState] | None:
        if type(handle) is not handle_type:
            return None
        exact_handle = handle
        try:
            state = issued_states.get(exact_handle)
        except (TypeError, ValueError):
            return None
        if state is None or not metadata_matches(exact_handle, state):
            return None
        return exact_handle, state

    def provisional_state(
        handle: object,
    ) -> tuple[_ProvisionalJunitHandle, ProvisionalState] | None:
        if type(handle) is not provisional_handle_type:
            return None
        provisional = handle
        try:
            state = provisional_states.get(provisional)
        except (TypeError, ValueError):
            return None
        if (
            state is None
            or type(provisional.destination_path) is not concrete_path_type
            or os_fspath(provisional.destination_path) != state.destination
            or type(provisional.control_directory) is not concrete_path_type
            or os_fspath(provisional.control_directory) != state.control_directory
            or provisional.control_directory_identity != state.control_directory_identity
        ):
            return None
        return provisional, state

    def descriptor_bytes(descriptor: int, byte_count: int) -> bytes:
        if os_pread is not None:
            chunks: list[bytes] = []
            offset = 0
            while offset < byte_count:
                chunk = os_pread(descriptor, min(1024 * 1024, byte_count - offset), offset)
                if not chunk:
                    break
                chunks.append(chunk)
                offset += len(chunk)
            return b"".join(chunks)
        original_offset = os_lseek(descriptor, 0, seek_current)
        try:
            os_lseek(descriptor, 0, seek_set)
            chunks = []
            remaining = byte_count
            while remaining:
                chunk = os_read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            return b"".join(chunks)
        finally:
            os_lseek(descriptor, original_offset, seek_set)

    def close_verified_descriptor(
        descriptor_owner: object | None,
        descriptor: int,
        expected: FileIdentity,
    ) -> None:
        last_error: BaseException | None = None
        for _ in range(3):
            try:
                current_status = os_fstat(descriptor)
            except os_error_type as error:
                if error.errno == bad_descriptor_errno:
                    return
                last_error = error
                continue
            if identity(current_status) != expected:
                # The original descriptor is closed and its number was reused.
                if descriptor_owner is not None and not bool(
                    getattr(descriptor_owner, "closed", False)
                ):
                    # Keep a still-open raw owner alive without ever touching a
                    # descriptor number that now belongs to another resource.
                    quarantined_descriptor_owners.append(descriptor_owner)
                return
            try:
                if descriptor_owner is None:
                    os_close(descriptor)
                else:
                    close_owner = getattr(descriptor_owner, "close", None)
                    owner_fileno = getattr(descriptor_owner, "fileno", None)
                    if not callable(close_owner) or not callable(owner_fileno):
                        raise error_type("Retained JUnit descriptor owner is invalid.")
                    if owner_fileno() != descriptor:
                        raise error_type("Retained JUnit descriptor owner changed identity.")
                    close_owner()
            except os_error_type as error:
                last_error = error
                continue
            return
        raise error_type("Could not close the exact retained JUnit descriptor.") from last_error

    def validate_owned_resource(state: HandleState) -> None:
        descriptor_status = os_fstat(state.descriptor)
        destination_status = os_stat(state.destination, follow_symlinks=False)
        directory_status = os_stat(state.control_directory, follow_symlinks=False)
        if (
            is_link_like(state.destination, destination_status)
            or is_link_like(state.control_directory, directory_status)
            or not is_owned_regular_file(descriptor_status, state.file_identity)
            or not is_owned_regular_file(destination_status, state.file_identity)
            or not is_owned_directory(
                directory_status,
                state.control_directory_identity,
            )
            or descriptor_status.st_size != state.initial_byte_count
        ):
            raise error_type("Retained JUnit ownership changed after creation.")
        raw = descriptor_bytes(state.descriptor, state.initial_byte_count)
        if len(raw) != state.initial_byte_count or sha256(raw).hexdigest() != state.initial_sha256:
            raise error_type("Retained JUnit creation seed changed after creation.")

    def validate_owned_paths(state: HandleState) -> None:
        destination_status = os_stat(state.destination, follow_symlinks=False)
        directory_status = os_stat(state.control_directory, follow_symlinks=False)
        if (
            is_link_like(state.destination, destination_status)
            or is_link_like(state.control_directory, directory_status)
            or not is_owned_regular_file(destination_status, state.file_identity)
            or not is_owned_directory(
                directory_status,
                state.control_directory_identity,
            )
        ):
            raise error_type("Retained JUnit paths changed after creation.")

    def validate_owned_control_directory(state: HandleState) -> None:
        directory_status = os_stat(state.control_directory, follow_symlinks=False)
        if is_link_like(state.control_directory, directory_status) or not is_owned_directory(
            directory_status,
            state.control_directory_identity,
        ):
            raise error_type("Retained JUnit control directory changed after creation.")

    def descriptor_is_gone(state: HandleState) -> bool:
        try:
            current_status = os_fstat(state.descriptor)
        except os_error_type as error:
            return error.errno == bad_descriptor_errno
        return identity(current_status) != state.file_identity

    def path_is_absent(path: str) -> bool:
        try:
            os_stat(path, follow_symlinks=False)
        except file_not_found_type:
            return True
        except os_error_type:
            return False
        return False

    def partial_cleanup_postconditions(state: HandleState) -> bool:
        return (
            state.descriptor_closed
            and state.destination_removed
            and descriptor_is_gone(state)
            and path_is_absent(state.destination)
        )

    def full_cleanup_postconditions(state: HandleState) -> bool:
        return (
            partial_cleanup_postconditions(state)
            and state.control_directory_removed
            and path_is_absent(state.control_directory)
        )

    def provisional_rollback(state: ProvisionalState) -> tuple[str, ...]:
        descriptor = state.descriptor
        failures: list[str] = []
        if descriptor is None and state.descriptor_owner is not None:
            try:
                owner_fileno = getattr(state.descriptor_owner, "fileno", None)
                if not callable(owner_fileno):
                    raise error_type("Provisional JUnit descriptor owner is invalid.")
                descriptor = owner_fileno()
            except BaseException as error:
                failures.append(
                    "could not recover provisional retained JUnit descriptor "
                    f"({type(error).__name__}: {error})"
                )
            else:
                state.descriptor = descriptor
        if descriptor is None:
            if state.descriptor_acquisition_state == "not_started":
                return ()
            if state.descriptor_acquisition_state == "open_failed":
                if path_is_absent(state.destination):
                    return ()
                return (
                    "provisional retained JUnit destination ownership is ambiguous after "
                    "failed no-replace acquisition",
                )
            if not state.destination_absence_verified:
                return ("provisional retained JUnit destination ownership is ambiguous",)
            try:
                directory_status = os_stat(state.control_directory, follow_symlinks=False)
            except BaseException as error:
                return (
                    "could not verify self-closing provisional JUnit directory "
                    f"({type(error).__name__}: {error})",
                )
            if is_link_like(state.control_directory, directory_status) or not is_owned_directory(
                directory_status,
                state.control_directory_identity,
            ):
                return ("provisional retained JUnit control directory changed after acquisition",)
            try:
                destination_status = os_stat(state.destination, follow_symlinks=False)
            except file_not_found_type:
                state.descriptor_closed = True
                state.destination_removed = True
                return ()
            except BaseException as error:
                return (
                    "could not recover self-closing provisional JUnit acquisition "
                    f"({type(error).__name__}: {error})",
                )
            try:
                state.file_identity = regular_file_identity(
                    destination_status,
                    "self-closed provisional retained JUnit path",
                )
            except BaseException as error:
                return (
                    "could not identify self-closed provisional JUnit acquisition "
                    f"({type(error).__name__}: {error})",
                )
            state.descriptor_closed = True
            descriptor = None

        if descriptor is not None and not state.descriptor_closed and state.file_identity is None:
            last_identity_error: BaseException | None = None
            for _ in range(3):
                try:
                    remaining_failures = provisional_identity_failure_remaining.get()
                    if remaining_failures:
                        provisional_identity_failure_remaining.set(remaining_failures - 1)
                        raise os_error_type("Injected provisional JUnit identity failure.")
                    descriptor_status = os_fstat(descriptor)
                except os_error_type as error:
                    if error.errno == bad_descriptor_errno:
                        state.descriptor_closed = True
                        break
                    last_identity_error = error
                    continue
                try:
                    state.file_identity = regular_file_identity(
                        descriptor_status,
                        "provisional retained JUnit descriptor",
                    )
                except BaseException as error:
                    last_identity_error = error
                break
            if state.file_identity is None and not state.descriptor_closed:
                failures.append(
                    "could not establish provisional descriptor identity"
                    + (
                        ""
                        if last_identity_error is None
                        else f" ({type(last_identity_error).__name__}: {last_identity_error})"
                    )
                )

        if (
            descriptor is not None
            and not state.descriptor_closed
            and state.file_identity is not None
        ):
            state.descriptor_close_in_progress = True
            try:
                close_verified_descriptor(
                    state.descriptor_owner,
                    descriptor,
                    state.file_identity,
                )
            except BaseException as error:
                failures.append(
                    "could not close provisional retained JUnit descriptor "
                    f"({type(error).__name__}: {error})"
                )
            else:
                state.descriptor_closed = True

        if not state.descriptor_closed:
            failures.append("provisional retained JUnit descriptor may remain open")
            return tuple(failures)
        if state.destination_removed:
            if not path_is_absent(state.destination):
                failures.append("provisional retained JUnit destination reappeared after unlink")
            return tuple(failures)
        if state.file_identity is None:
            failures.append(
                "cannot unlink provisional retained JUnit destination without exact identity"
            )
            return tuple(failures)

        try:
            directory_status = os_stat(state.control_directory, follow_symlinks=False)
        except file_not_found_type as error:
            failures.append(
                "provisional retained JUnit control directory disappeared before unlink "
                f"({type(error).__name__}: {error})"
            )
            return tuple(failures)
        except BaseException as error:
            failures.append(
                "could not verify provisional retained JUnit control directory "
                f"({type(error).__name__}: {error})"
            )
            return tuple(failures)
        if is_link_like(state.control_directory, directory_status) or not is_owned_directory(
            directory_status,
            state.control_directory_identity,
        ):
            failures.append("provisional retained JUnit control directory changed before unlink")
            return tuple(failures)

        try:
            destination_status = os_stat(state.destination, follow_symlinks=False)
        except file_not_found_type as error:
            if not state.destination_unlink_in_progress:
                failures.append(
                    "provisional retained JUnit destination disappeared before unlink "
                    f"({type(error).__name__}: {error})"
                )
                return tuple(failures)
            state.destination_removed = True
            return ()
        except BaseException as error:
            failures.append(
                "could not verify provisional retained JUnit destination "
                f"({type(error).__name__}: {error})"
            )
            return tuple(failures)
        if is_link_like(state.destination, destination_status) or not is_owned_regular_file(
            destination_status,
            state.file_identity,
        ):
            failures.append("provisional retained JUnit destination changed before unlink")
            return tuple(failures)

        state.destination_unlink_in_progress = True
        unlink_error: BaseException | None = None
        try:
            os_unlink(state.destination)
        except BaseException as error:
            unlink_error = error
        try:
            os_stat(state.destination, follow_symlinks=False)
        except file_not_found_type:
            state.destination_removed = True
        except BaseException as error:
            failures.append(
                "could not verify provisional retained JUnit unlink "
                f"({type(error).__name__}: {error})"
            )
        else:
            if unlink_error is not None:
                failures.append(
                    "could not unlink provisional retained JUnit file "
                    f"({type(unlink_error).__name__}: {unlink_error})"
                )
            failures.append("provisional retained JUnit file remained after unlink")
        return tuple(failures)

    def create(
        path: Path,
        *,
        initial_bytes: bytes,
        expected_control_directory_identity: FileIdentity | None = None,
        retain_provisional_handle: Callable[[_ProvisionalJunitHandle], None] | None = None,
        retain_handle: (
            Callable[[_ProvisionalJunitHandle, _RetainedJunitHandle], None] | None
        ) = None,
        begin_acquisition: Callable[[], None] | None = None,
        cancel_acquisition: Callable[[], None] | None = None,
        acquisition_checkpoint: Callable[[], None] | None = None,
        retained_checkpoint: Callable[[], None] | None = None,
    ) -> _RetainedJunitHandle:
        if type(path) is not concrete_path_type:
            raise error_type("Exact retained JUnit destination path required.")
        if type(initial_bytes) is not bytes or len(initial_bytes) != 32:
            raise error_type("Retained JUnit creation seed must contain exactly 32 bytes.")
        if expected_control_directory_identity is not None and (
            type(expected_control_directory_identity) is not tuple
            or len(expected_control_directory_identity) != 2
            or any(type(value) is not int for value in expected_control_directory_identity)
        ):
            raise error_type("Expected JUnit control-directory identity is malformed.")
        if (retain_provisional_handle is None) != (retain_handle is None) or (
            retain_provisional_handle is not None
            and (not callable(retain_provisional_handle) or not callable(retain_handle))
        ):
            raise error_type("Retained JUnit creation requires two exact ownership sinks.")
        acquisition_callbacks = (
            begin_acquisition,
            cancel_acquisition,
            acquisition_checkpoint,
            retained_checkpoint,
        )
        if any(callback is not None for callback in acquisition_callbacks) and not all(
            callable(callback) for callback in acquisition_callbacks
        ):
            raise error_type("Retained JUnit acquisition callbacks must be complete callables.")
        destination_path = path
        control_directory_path = path.parent
        destination = os_fspath(destination_path)
        control_directory = os_fspath(control_directory_path)
        if path_dirname(destination) != control_directory:
            raise error_type("Retained JUnit destination escaped its control directory.")
        initial_sha256 = sha256(initial_bytes).hexdigest()
        descriptor: int | None = None
        descriptor_owner: object | None = None
        expected_file_identity: FileIdentity | None = None
        expected_directory_identity: FileIdentity | None = None
        retained_handle: _RetainedJunitHandle | None = None
        retained_state: HandleState | None = None
        provisional_handle: _ProvisionalJunitHandle | None = None
        provisional_record: ProvisionalState | None = None
        central_ownership_confirmed = False
        acquisition_attempted = False
        try:
            with authority_lock:
                directory_status = os_stat(control_directory, follow_symlinks=False)
                if is_link_like(control_directory, directory_status):
                    raise error_type("Retained JUnit control directory cannot be link-like.")
                expected_directory_identity = directory_identity(
                    directory_status,
                    "retained JUnit control directory",
                )
                if (
                    expected_control_directory_identity is not None
                    and expected_directory_identity != expected_control_directory_identity
                ):
                    raise error_type(
                        "Retained JUnit control directory is not the centrally owned directory."
                    )
                provisional_handle = provisional_handle_type(
                    destination_path=destination_path,
                    control_directory=control_directory_path,
                    control_directory_identity=expected_directory_identity,
                )
                provisional_record = ProvisionalState(
                    destination=destination,
                    control_directory=control_directory,
                    control_directory_identity=expected_directory_identity,
                )
                provisional_states[provisional_handle] = provisional_record
                try:
                    os_stat(destination, follow_symlinks=False)
                except file_not_found_type:
                    provisional_record.destination_absence_verified = True
                except os_error_type as error:
                    raise error_type(
                        "Could not verify the retained JUnit destination before creation."
                    ) from error
                else:
                    raise error_type("Retained JUnit destination already exists.")
            if begin_acquisition is not None:
                acquisition_attempted = True
                begin_acquisition()
                cast(Callable[[], None], acquisition_checkpoint)()
            if retain_provisional_handle is not None:
                retain_provisional_handle(provisional_handle)
                central_ownership_confirmed = True
                with authority_lock:
                    current_provisional = provisional_state(provisional_handle)
                    if (
                        current_provisional is None
                        or current_provisional[1] is not provisional_record
                        or provisional_record.ownership_state != "acquired"
                        or provisional_record.descriptor is not None
                        or provisional_record.descriptor_owner is not None
                    ):
                        raise error_type(
                            "Retained JUnit provisional ownership changed during central "
                            "registration."
                        )
                    provisional_record.ownership_state = "centrally_registered"
            with authority_lock:
                current_provisional = provisional_state(provisional_handle)
                expected_provisional_state = (
                    "centrally_registered" if retain_provisional_handle is not None else "acquired"
                )
                if (
                    current_provisional is None
                    or current_provisional[1] is not provisional_record
                    or provisional_record.ownership_state != expected_provisional_state
                    or provisional_record.descriptor is not None
                    or provisional_record.descriptor_owner is not None
                    or not provisional_record.destination_absence_verified
                    or provisional_record.descriptor_acquisition_state != "not_started"
                ):
                    raise error_type(
                        "Retained JUnit provisional ownership changed before acquisition."
                    )
                provisional_record.descriptor_acquisition_state = "open_in_progress"
                try:
                    provisional_record.descriptor_owner = open_file(
                        destination,
                        "x+b",
                        buffering=0,
                    )
                except os_error_type:
                    provisional_record.descriptor_acquisition_state = "open_failed"
                    raise
                descriptor_owner = provisional_record.descriptor_owner
                provisional_record.descriptor_acquisition_state = "opened"
                owner_fileno = getattr(descriptor_owner, "fileno", None)
                if not callable(owner_fileno):
                    raise error_type("Retained JUnit descriptor owner is invalid.")
                descriptor = owner_fileno()
                provisional_record.descriptor = descriptor
            if retained_checkpoint is not None:
                retained_checkpoint()
            with authority_lock:
                current_provisional = provisional_state(provisional_handle)
                expected_provisional_state = (
                    "centrally_registered" if retain_provisional_handle is not None else "acquired"
                )
                if (
                    current_provisional is None
                    or current_provisional[1] is not provisional_record
                    or provisional_record.ownership_state != expected_provisional_state
                    or provisional_record.descriptor != descriptor
                    or provisional_record.descriptor_acquisition_state != "opened"
                    or provisional_record.promoted_handle is not None
                ):
                    raise error_type(
                        "Retained JUnit provisional ownership changed before promotion."
                    )
                if type(descriptor) is not int or descriptor < 0:
                    raise error_type("Retained JUnit creation returned an invalid descriptor.")
                descriptor_status = os_fstat(descriptor)
                expected_file_identity = regular_file_identity(
                    descriptor_status,
                    "pre-created retained JUnit descriptor",
                )
                provisional_record.file_identity = expected_file_identity
                os_set_inheritable(descriptor, False)
                if os_get_inheritable(descriptor):
                    raise error_type("Retained JUnit descriptor remained inheritable.")
                written = 0
                while written < len(initial_bytes):
                    count = os_write(descriptor, initial_bytes[written:])
                    if type(count) is not int or count <= 0:
                        raise error_type("Could not write the retained JUnit creation seed.")
                    written += count
                os_fsync(descriptor)
                descriptor_status = os_fstat(descriptor)
                destination_status = os_stat(destination, follow_symlinks=False)
                directory_status = os_stat(control_directory, follow_symlinks=False)
                if (
                    is_link_like(destination, destination_status)
                    or is_link_like(control_directory, directory_status)
                    or not is_owned_regular_file(
                        descriptor_status,
                        expected_file_identity,
                    )
                    or not is_owned_regular_file(
                        destination_status,
                        expected_file_identity,
                    )
                    or not is_owned_directory(
                        directory_status,
                        expected_directory_identity,
                    )
                    or descriptor_status.st_size != len(initial_bytes)
                ):
                    raise error_type("Retained JUnit ownership changed during creation.")
                raw = descriptor_bytes(descriptor, len(initial_bytes))
                if raw != initial_bytes or sha256(raw).hexdigest() != initial_sha256:
                    raise error_type("Retained JUnit creation seed changed during creation.")
                retained_handle = handle_type(
                    descriptor=descriptor,
                    destination_path=destination_path,
                    control_directory=control_directory_path,
                    control_directory_identity=expected_directory_identity,
                    file_identity=expected_file_identity,
                    initial_sha256=initial_sha256,
                    initial_byte_count=len(initial_bytes),
                )
                retained_state = HandleState(
                    descriptor=descriptor,
                    descriptor_owner=descriptor_owner,
                    destination_path=destination_path,
                    destination=destination,
                    control_directory_path=control_directory_path,
                    control_directory=control_directory,
                    control_directory_identity=expected_directory_identity,
                    file_identity=expected_file_identity,
                    initial_sha256=initial_sha256,
                    initial_byte_count=len(initial_bytes),
                )
                provisional_record.promoted_handle = retained_handle
                issued_states[retained_handle] = retained_state
                provisional_record.ownership_state = "retained"
            if retain_handle is not None:
                retain_handle(provisional_handle, retained_handle)
            with authority_lock:
                current_provisional = provisional_state(provisional_handle)
                current_retained = issued_state(retained_handle)
                if (
                    current_provisional is None
                    or current_provisional[1] is not provisional_record
                    or current_retained is None
                    or current_retained[1] is not retained_state
                    or provisional_record.promoted_handle is not retained_handle
                    or provisional_record.ownership_state != "retained"
                    or retained_state.ownership_state != "acquired"
                    or retained_state.creation_complete
                    or retained_state.descriptor_closed
                    or retained_state.destination_removed
                    or retained_state.control_directory_removed
                ):
                    raise error_type("Retained JUnit ownership changed during central promotion.")
                retained_state.creation_complete = True
                retained_state.ownership_state = (
                    "transferred_for_later_execution" if retain_handle is not None else "retained"
                )
                if retain_handle is not None:
                    provisional_record.ownership_state = "transferred_for_later_execution"
                else:
                    provisional_states.pop(provisional_handle, None)
            return retained_handle
        except BaseException as creation_error:
            cancellation_failure: str | None = None
            rollback_failures: tuple[str, ...]
            if (
                provisional_record is not None
                and descriptor_owner is not None
                and provisional_record.descriptor_owner is None
            ):
                provisional_record.descriptor_owner = descriptor_owner
            if provisional_handle is not None:
                try:
                    cleanup(provisional_handle, remove_control_directory=False)
                except BaseException as cleanup_error:
                    rollback_failures = (
                        "provisional retained JUnit cleanup failed "
                        f"({type(cleanup_error).__name__}: {cleanup_error})",
                    )
                else:
                    rollback_failures = ()
            elif provisional_record is None:
                rollback_failures = (
                    ()
                    if descriptor is None
                    else ("provisional retained JUnit ownership state was lost",)
                )
            else:
                with authority_lock:
                    provisional_record.ownership_state = "cleanup_pending"
                    rollback_failures = provisional_rollback(provisional_record)
            rollback_verified_complete = not rollback_failures and (
                descriptor is None
                or (
                    provisional_record is not None
                    and provisional_record.descriptor_closed
                    and provisional_record.destination_removed
                )
            )
            if (
                rollback_verified_complete
                and acquisition_attempted
                and not central_ownership_confirmed
                and cancel_acquisition is not None
            ):
                try:
                    cancel_acquisition()
                except BaseException as cancellation_error:
                    cancellation_failure = (
                        "Central JUnit acquisition cancellation failed "
                        f"({type(cancellation_error).__name__}: {cancellation_error})."
                    )
            if isinstance(creation_error, os_error_type) and not isinstance(
                creation_error,
                error_type,
            ):
                normalized = error_type(
                    "Could not securely pre-create retained pytest JUnit output."
                )
                if rollback_failures:
                    normalized.add_note(
                        "Retained JUnit provisional rollback was incomplete: "
                        + "; ".join(rollback_failures)
                    )
                if cancellation_failure is not None:
                    normalized.add_note(cancellation_failure)
                raise normalized from creation_error
            if rollback_failures:
                creation_error.add_note(
                    "Retained JUnit provisional rollback was incomplete: "
                    + "; ".join(rollback_failures)
                )
            if cancellation_failure is not None:
                creation_error.add_note(cancellation_failure)
            raise

    def is_open(handle: object) -> bool:
        with authority_lock:
            provisional = provisional_state(handle)
            if provisional is not None:
                promoted = provisional[1].promoted_handle
                return promoted is not None and is_open(promoted)
            resolved = issued_state(handle)
            if resolved is None:
                return False
            _, state = resolved
            if (
                state.descriptor_closed
                or state.destination_removed
                or state.control_directory_removed
                or not state.creation_complete
            ):
                return False
            try:
                validate_owned_resource(state)
            except BaseException as error:
                if isinstance(
                    error,
                    (AttributeError, error_type, os_error_type, TypeError, ValueError),
                ):
                    return False
                raise
            return True

    def is_cleaned(handle: object) -> bool:
        with authority_lock:
            provisional = provisional_state(handle)
            if provisional is not None:
                state = provisional[1]
                if state.ownership_state == "cleanup_complete":
                    return True
                return state.promoted_handle is not None and is_cleaned(state.promoted_handle)
            resolved = issued_state(handle)
            # The JUnit authority owns the descriptor and file.  The Stage-1
            # directory authority independently owns and certifies the parent.
            return resolved is not None and partial_cleanup_postconditions(resolved[1])

    def cleanup(handle: object, *, remove_control_directory: bool) -> None:
        if type(remove_control_directory) is not bool:
            raise error_type("Retained JUnit cleanup mode must be exact.")
        with authority_lock:
            provisional = provisional_state(handle)
            if provisional is not None:
                _, provisional_record = provisional
                if provisional_record.ownership_state == "cleanup_complete":
                    return
                provisional_record.ownership_state = "cleanup_pending"
                if provisional_record.promoted_handle is not None:
                    promoted = issued_state(provisional_record.promoted_handle)
                    if promoted is None:
                        rollback_failures = provisional_rollback(provisional_record)
                        if rollback_failures:
                            raise error_type(
                                "Retained JUnit provisional cleanup was incomplete: "
                                + "; ".join(rollback_failures)
                            )
                    else:
                        cleanup(
                            provisional_record.promoted_handle,
                            remove_control_directory=remove_control_directory,
                        )
                    provisional_record.ownership_state = "released"
                    provisional_record.ownership_state = "cleanup_complete"
                    return
                rollback_failures = provisional_rollback(provisional_record)
                if rollback_failures:
                    raise error_type(
                        "Retained JUnit provisional cleanup was incomplete: "
                        + "; ".join(rollback_failures)
                    )
                provisional_record.ownership_state = "released"
                provisional_record.ownership_state = "cleanup_complete"
                return
            resolved = issued_state(handle)
            if resolved is None:
                raise error_type("Exact issued retained JUnit handle required for cleanup.")
            _, state = resolved
            if state.ownership_state == "cleanup_complete":
                return
            state.ownership_state = "cleanup_pending"
            if not state.descriptor_closed:
                try:
                    if not state.descriptor_close_in_progress:
                        validate_owned_resource(state)
                        state.descriptor_close_in_progress = True
                    close_verified_descriptor(
                        state.descriptor_owner,
                        state.descriptor,
                        state.file_identity,
                    )
                except BaseException as error:
                    raise error_type(
                        "Refusing to remove a changed or stale retained JUnit resource."
                    ) from error
                state.descriptor_closed = True
            if not state.destination_removed:
                remaining_failures = cleanup_failure_remaining.get()
                if remaining_failures:
                    cleanup_failure_remaining.set(remaining_failures - 1)
                    raise error_type("Injected retained JUnit cleanup failure before unlink.")
                try:
                    validate_owned_paths(state)
                except file_not_found_type as error:
                    if not state.destination_unlink_in_progress:
                        raise error_type(
                            "Retained JUnit destination disappeared before owned cleanup."
                        ) from error
                    try:
                        validate_owned_control_directory(state)
                    except BaseException as directory_error:
                        raise error_type(
                            "Could not verify retained JUnit cleanup after unlink."
                        ) from directory_error
                    state.destination_removed = True
                    state.ownership_state = "released"
                except os_error_type as error:
                    raise error_type(
                        "Could not verify retained JUnit paths for cleanup."
                    ) from error
                else:
                    state.destination_unlink_in_progress = True
                    try:
                        os_unlink(state.destination)
                        remaining_failures = post_unlink_failure_remaining.get()
                        if remaining_failures:
                            post_unlink_failure_remaining.set(remaining_failures - 1)
                            raise os_error_type("Injected retained JUnit post-unlink failure.")
                    except os_error_type as error:
                        raise error_type(
                            "Could not unlink the exact retained JUnit destination."
                        ) from error
                    state.destination_removed = True
                    state.ownership_state = "released"
            if remove_control_directory and not state.control_directory_removed:
                try:
                    directory_status = os_stat(
                        state.control_directory,
                        follow_symlinks=False,
                    )
                except file_not_found_type as error:
                    raise error_type(
                        "Retained JUnit control directory disappeared before owned cleanup."
                    ) from error
                except os_error_type as error:
                    raise error_type(
                        "Could not verify the retained JUnit control directory."
                    ) from error
                if is_link_like(
                    state.control_directory,
                    directory_status,
                ) or not is_owned_directory(
                    directory_status,
                    state.control_directory_identity,
                ):
                    raise error_type("Refusing to remove a changed JUnit control directory.")
                try:
                    with os_scandir(state.control_directory) as entries:
                        if next(entries, None) is not None:
                            raise error_type(
                                "Refusing to remove a JUnit control directory containing "
                                "unrelated resources."
                            )
                except file_not_found_type as error:
                    raise error_type(
                        "Retained JUnit control directory disappeared before empty check."
                    ) from error
                except os_error_type as error:
                    raise error_type(
                        "Could not inspect the exact retained JUnit control directory."
                    ) from error
                try:
                    os_rmdir(state.control_directory)
                except os_error_type as error:
                    raise error_type(
                        "Could not remove the exact retained JUnit control directory."
                    ) from error
                state.control_directory_removed = True
            postconditions_met = (
                full_cleanup_postconditions(state)
                if remove_control_directory
                else partial_cleanup_postconditions(state)
            )
            if not postconditions_met:
                raise error_type("Retained JUnit cleanup postconditions were not satisfied.")
            state.ownership_state = "cleanup_complete"

    @contextmanager
    def failure_scope(attempts: int) -> Iterator[None]:
        if isinstance(attempts, bool) or type(attempts) is not int or not 1 <= attempts <= 2:
            raise error_type("Retained JUnit cleanup injection requires one or two failures.")
        if cleanup_failure_remaining.get() != 0:
            raise error_type("Retained JUnit cleanup failure injection cannot be nested.")
        token = cleanup_failure_remaining.set(attempts)
        try:
            yield
        finally:
            cleanup_failure_remaining.reset(token)

    @contextmanager
    def provisional_identity_failure_scope(attempts: int) -> Iterator[None]:
        if isinstance(attempts, bool) or type(attempts) is not int or not 1 <= attempts <= 6:
            raise error_type(
                "Provisional JUnit identity injection requires one through six failures."
            )
        if provisional_identity_failure_remaining.get() != 0:
            raise error_type("Provisional JUnit identity failure injection cannot be nested.")
        token = provisional_identity_failure_remaining.set(attempts)
        try:
            yield
        finally:
            provisional_identity_failure_remaining.reset(token)

    @contextmanager
    def post_unlink_failure_scope(attempts: int) -> Iterator[None]:
        if isinstance(attempts, bool) or type(attempts) is not int or not 1 <= attempts <= 2:
            raise error_type("Retained JUnit post-unlink injection requires one or two failures.")
        if post_unlink_failure_remaining.get() != 0:
            raise error_type("Retained JUnit post-unlink failure injection cannot be nested.")
        token = post_unlink_failure_remaining.set(attempts)
        try:
            yield
        finally:
            post_unlink_failure_remaining.reset(token)

    def opaque(function: Callable[..., object]) -> Callable[..., object]:
        source = getattr(function, "__wrapped__", function)
        if type(source) is not type(opaque):
            raise RuntimeError("Retained JUnit source attestation requires one Python function.")
        source_function = cast(Any, source)
        code = source_function.__code__
        source_attestation = (
            source_function.__module__,
            code.co_qualname,
            code.co_firstlineno,
            code,
        )
        wrapped = _opaque_runtime_callable(function)
        cast(Any, wrapped)._rde_opaque_source = source_attestation
        return wrapped

    return (
        cast(Callable[..., _RetainedJunitHandle], opaque(create)),
        cast(
            Callable[[object], bool],
            _seal_production_component_callable("junit_is_open", is_open),
        ),
        cast(
            Callable[[object], bool],
            _seal_production_component_callable("junit_is_cleaned", is_cleaned),
        ),
        cast(
            Callable[..., None],
            _seal_production_component_callable("junit_cleanup", cleanup),
        ),
        opaque(failure_scope),
        opaque(provisional_identity_failure_scope),
        opaque(post_unlink_failure_scope),
    )


(
    _create_guarded_junit_file,
    _retained_junit_handle_is_open,
    _retained_junit_handle_is_cleaned,
    _cleanup_retained_junit_handle,
    _retained_junit_cleanup_failure_scope,
    _provisional_junit_identity_failure_scope,
    _retained_junit_post_unlink_failure_scope,
) = _install_retained_junit_operations()
del _install_retained_junit_operations


def _create_historical_guarded_junit_file(path: Path, *, initial_bytes: bytes) -> FileIdentity:
    """Preserve the historical reopen-on-configure path outside P2 Stage 1."""

    flags = (
        os.O_CREAT
        | os.O_EXCL
        | os.O_RDWR
        | cast(int, getattr(os, "O_BINARY", 0))
        | cast(int, getattr(os, "O_NOFOLLOW", 0))
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        written = 0
        while written < len(initial_bytes):
            count = os.write(descriptor, initial_bytes[written:])
            if count <= 0:
                raise RuntimeError("Could not seed the historical JUnit output.")
            written += count
        os.fsync(descriptor)
        descriptor_status = os.fstat(descriptor)
        path_status = path.stat(follow_symlinks=False)
        descriptor_identity = _regular_single_link_file_identity(
            descriptor_status,
            "historical JUnit descriptor",
        )
        if (
            _path_is_link_like(path)
            or _regular_single_link_file_identity(path_status, "historical JUnit path")
            != descriptor_identity
            or descriptor_status.st_size != len(initial_bytes)
            or _read_file_descriptor(descriptor) != initial_bytes
        ):
            raise RuntimeError("Historical JUnit creation changed during setup.")
        return descriptor_identity
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _open_guarded_junit_file(
    path: Path,
    *,
    expected_identity: FileIdentity,
    expected_sha256: str,
    expected_byte_count: int,
) -> int:
    flags = (
        os.O_RDWR | cast(int, getattr(os, "O_BINARY", 0)) | cast(int, getattr(os, "O_NOFOLLOW", 0))
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise RuntimeError("Could not open the pre-created JUnit output.") from error
    try:
        status = os.fstat(descriptor)
        path_status = path.stat(follow_symlinks=False)
        if (
            _regular_single_link_file_identity(status, "opened JUnit") != expected_identity
            or _regular_single_link_file_identity(path_status, "opened JUnit path")
            != expected_identity
            or status.st_size != expected_byte_count
        ):
            raise RuntimeError("Pre-created JUnit file identity changed before pytest configure.")
        raw = _read_file_descriptor(descriptor)
        if len(raw) != expected_byte_count or hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise RuntimeError("Pre-created JUnit creation seed changed before pytest configure.")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_file_descriptor(descriptor: int) -> bytes:
    status = os.fstat(descriptor)
    if status.st_size < 0:
        raise PytestValidationError("Bound JUnit descriptor size is invalid.")
    pread = cast(Callable[[int, int, int], bytes] | None, getattr(os, "pread", None))
    if pread is not None:
        chunks: list[bytes] = []
        offset = 0
        while offset < status.st_size:
            chunk = pread(descriptor, min(1024 * 1024, status.st_size - offset), offset)
            if not chunk:
                break
            chunks.append(chunk)
            offset += len(chunk)
        return b"".join(chunks)
    current = os.lseek(descriptor, 0, os.SEEK_CUR)
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        remaining = status.st_size
        chunks = []
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    finally:
        os.lseek(descriptor, current, os.SEEK_SET)


def _document_file_identity(document: dict[str, object]) -> FileIdentity:
    raw = document.get("junit_file_identity")
    if (
        not isinstance(raw, list)
        or len(raw) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) for item in raw)
    ):
        raise RuntimeError("Pytest execution specification JUnit identity is malformed.")
    return cast(FileIdentity, tuple(raw))


def _install_authoritative_junit_writer(
    config: object,
    *,
    specification_document: dict[str, object],
    junit_path: Path,
) -> tuple[FileIdentity, int]:
    expected_identity = _document_file_identity(specification_document)
    expected_sha256 = _document_str(specification_document, "junit_initial_sha256")
    expected_byte_count_value = specification_document.get("junit_initial_byte_count")
    if (
        isinstance(expected_byte_count_value, bool)
        or not isinstance(expected_byte_count_value, int)
        or expected_byte_count_value <= 0
    ):
        raise RuntimeError("Pytest execution specification JUnit seed size is malformed.")
    descriptor = _open_guarded_junit_file(
        junit_path,
        expected_identity=expected_identity,
        expected_sha256=expected_sha256,
        expected_byte_count=expected_byte_count_value,
    )
    manager = cast(Any, config).pluginmanager
    matches = [
        plugin
        for _, plugin in manager.list_name_plugin()
        if plugin is not None
        and type(plugin).__module__ == "_pytest.junitxml"
        and type(plugin).__qualname__ == "LogXML"
    ]
    if len(matches) != 1:
        os.close(descriptor)
        raise RuntimeError("Native pytest JUnit writer identity is missing or ambiguous.")
    native_writer = matches[0]
    if str(Path(cast(str, native_writer.logfile)).resolve()) != str(junit_path):
        os.close(descriptor)
        raise RuntimeError("Native pytest JUnit writer targets another output path.")
    if manager.unregister(native_writer) is None:
        os.close(descriptor)
        raise RuntimeError("Native pytest JUnit writer could not be reserved.")
    authoritative_type = type(
        "_AuthoritativeLogXML",
        (type(native_writer),),
        {
            "__module__": __name__,
            "pytest_sessionfinish": _authoritative_junit_sessionfinish,
        },
    )
    native_writer.__class__ = authoritative_type
    native_writer._rde_junit_descriptor = descriptor
    native_writer._rde_junit_file_identity = expected_identity
    native_writer._rde_junit_writer_identity = None
    if manager.register(native_writer, _AUTHORITATIVE_JUNIT_PLUGIN_NAME) is None:
        os.close(descriptor)
        raise RuntimeError("Authoritative pytest JUnit writer could not be registered.")
    return expected_identity, descriptor


def _authoritative_junit_sessionfinish(self: object) -> None:
    writer = cast(Any, self)
    duration = writer.suite_start.elapsed()
    numtests = (
        writer.stats["passed"]
        + writer.stats["failure"]
        + writer.stats["skipped"]
        + writer.stats["error"]
        - writer.cnt_double_fail_tests
    )
    suite_node = ElementTree.Element(
        "testsuite",
        name=writer.suite_name,
        errors=str(writer.stats["error"]),
        failures=str(writer.stats["failure"]),
        skipped=str(writer.stats["skipped"]),
        tests=str(numtests),
        time=f"{duration.seconds:.3f}",
        timestamp=writer.suite_start.as_utc().astimezone().isoformat(),
        hostname=platform.node(),
    )
    global_properties = writer._get_global_properties_node()
    if global_properties is not None:
        suite_node.append(global_properties)
    for node_reporter in writer.node_reporters_ordered:
        suite_node.append(node_reporter.to_xml())
    testsuites = ElementTree.Element("testsuites")
    testsuites.set("name", "pytest tests")
    testsuites.append(suite_node)
    payload_text = '<?xml version="1.0" encoding="utf-8"?>' + ElementTree.tostring(
        testsuites, encoding="unicode"
    )
    payload = payload_text.replace("\n", os.linesep).encode("utf-8")
    descriptor = cast(int, writer._rde_junit_descriptor)
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.ftruncate(descriptor, 0)
    written = 0
    while written < len(payload):
        written += os.write(descriptor, payload[written:])
    os.fsync(descriptor)
    writer._rde_junit_writer_identity = protocol_hash(
        "pytest_authoritative_junit_writer/v1",
        {
            "file_identity": list(cast(FileIdentity, writer._rde_junit_file_identity)),
            "junit_byte_count": len(payload),
            "junit_sha256": hashlib.sha256(payload).hexdigest(),
            "validation_plugin_source_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
        },
    )


def execute_pytest_validation(
    *,
    validation_run_identity: str,
    timeout_seconds: float = DEFAULT_PYTEST_TIMEOUT_SECONDS,
) -> PytestValidationResult:
    """Execute the historical P1 repository's fixed, complete pytest suite.

    This production API deliberately accepts no target, selector, pytest
    option, environment, expected count, or caller-supplied result. It does not
    issue or consume the P2 ``pytest_plan_id`` capability.
    """

    return _execute_pytest_validation(
        validation_run_identity=validation_run_identity,
        issuer_kind="production",
        targets=(),
        timeout_seconds=timeout_seconds,
        execution_root=None,
    )


def pytest_plan_id_from_projection(projection: PytestPlanProjection) -> str:
    mapping = projection.as_dict()
    expected_fields = {
        "argv",
        "conftests",
        "control_paths",
        "controlled_environment",
        "environment",
        "environment_sha256",
        "evidence_contract_checkpoint",
        "expected_completion",
        "implementation",
        "junit_destination",
        "plan_issuer_identity",
        "plugins",
        "protocol_checkpoint",
        "pytest_configuration",
        "pytest_rootdir",
        "pytest_runtime",
        "repository_root",
        "reserved_environment_prefix",
        "runtime",
        "runtime_identity",
        "schema_version",
        "selected_tests",
        "study_id",
        "timeout_policy",
        "validation_run_id",
        "working_directory",
    }
    if set(mapping) != expected_fields or "validation_authority_id" in mapping:
        raise P2Stage1Error(
            "PYTEST_PLAN_ID_MISMATCH",
            "Pytest plan differs from its frozen closed authority-free schema.",
            layer="plan_identities",
        )
    if projection.evidence_contract_checkpoint != EVIDENCE_CONTRACT_CHECKPOINT:
        raise P2Stage1Error(
            "EVIDENCE_CONTRACT_CHECKPOINT_MISMATCH",
            "Pytest plan uses another evidence-contract checkpoint.",
            layer="plan_identities",
        )
    if (
        projection.protocol_checkpoint != PROTOCOL_CHECKPOINT
        or projection.schema_version != "broader-replication-pytest-plan/v1"
        or projection.reserved_environment_prefix != "RDE_BROADER_PYTEST_VALIDATION_"
        or projection.study_id != STUDY_ID
        or re.fullmatch(r"[0-9a-f]{64}", projection.validation_run_id) is None
        or projection.junit_destination.final_evidence_filename != "pytest-junit.xml"
        or projection.junit_destination.initial_byte_count != 32
        or projection.junit_destination.mode != "exclusive-precreated-retained-handle"
        or projection.junit_destination.writer != "rde-authoritative-junitxml"
    ):
        raise P2Stage1Error(
            "PYTEST_PLAN_ID_MISMATCH",
            "Pytest plan fixed literals or validation run differ from the frozen schema.",
            layer="plan_identities",
        )
    expected_environment = protocol_hash(
        "validation_evidence_pytest_environment/v1",
        [row.as_dict() for row in projection.environment],
    )
    if projection.environment_sha256 != expected_environment:
        raise P2Stage1Error(
            "PYTEST_PLAN_ID_MISMATCH",
            "Pytest environment identity does not recompute.",
            layer="plan_identities",
        )
    return protocol_hash("validation_evidence_pytest_plan/v1", mapping)


class _ProductionPytestPlanDraftIssuer(Protocol):
    def __call__(
        self,
        *,
        preparation: _ProductionPreparationCapability,
        context: Layer0Context,
        validation_run: ValidationRun,
        control_directory: Path,
        control_directory_identity: FileIdentity,
        retain_provisional_handle: Callable[[_ProvisionalJunitHandle], None] | None = None,
        retain_handle: (
            Callable[[_ProvisionalJunitHandle, _RetainedJunitHandle], None] | None
        ) = None,
        begin_acquisition: Callable[[], None] | None = None,
        cancel_acquisition: Callable[[], None] | None = None,
        acquisition_checkpoint: Callable[[], None] | None = None,
        retained_checkpoint: Callable[[], None] | None = None,
    ) -> tuple[_PlanDraft, _RetainedJunitHandle]: ...


def _install_production_pytest_plan_draft_issuer(
    entropy_module: ModuleType,
    entropy: Callable[[int], bytes],
) -> tuple[_ProductionPytestPlanDraftIssuer, Callable[[], None]]:
    """Seal the exact OS entropy authority into the production-only issuer."""

    entropy_origin = getattr(entropy, "__module__", None)
    if (
        type(entropy) is not BuiltinFunctionType
        or getattr(entropy, "__name__", None) != "urandom"
        or type(entropy_origin) is not str
        or getattr(entropy_module, "urandom", None) is not entropy
    ):
        raise RuntimeError("The exact OS-random authority is unavailable at module installation.")
    trusted_module = sys.modules[__name__]
    require_preparation = _require_production_preparation
    production_run_id = _production_validation_run_id
    path_is_link_like = _path_is_link_like
    create_guarded_junit_file = _create_guarded_junit_file
    build_projection = _build_production_pytest_plan_projection
    compute_plan_id = pytest_plan_id_from_projection
    retained_handle_is_open = _retained_junit_handle_is_open
    production_plan_type = PytestPlan
    draft_type = _PlanDraft
    error_type = P2Stage1Error
    allocate_plan = _allocate_production_plan_capability
    record_plan = _record_production_plan_draft
    trusted_sys_modules = sys.modules
    importlib.import_module("pytest")
    importlib.import_module("pluggy")
    root = repository_root().resolve(strict=True)
    tests_root = (root / "tests").resolve(strict=True)
    initial_plugins, final_plugins = _expected_plugin_lifecycle(
        _expected_conftest_identities(root, (str(tests_root),))
    )
    plugin_module_names = {identity[1] for identity in (*initial_plugins, *final_plugins)}
    trusted_module_names = {
        "pytest",
        "pluggy",
        "_pytest.config",
        *(
            name
            for name in plugin_module_names
            if type(trusted_sys_modules.get(name)) is ModuleType
        ),
    }
    trusted_module_map: dict[str, ModuleType] = {}
    trusted_module_rows: list[tuple[str, ModuleType, object, str, Path, bytes]] = []
    for module_name in sorted(trusted_module_names):
        module = trusted_sys_modules.get(module_name)
        if type(module) is not ModuleType:
            raise RuntimeError(
                f"Trusted pytest runtime module is unavailable during sealing: {module_name}."
            )
        trusted_runtime_module = module
        module_file = getattr(trusted_runtime_module, "__file__", None)
        if not isinstance(module_file, str):
            raise RuntimeError(
                f"Trusted pytest runtime module has no source during sealing: {module_name}."
            )
        source_path = Path(module_file)
        if source_path.suffix == ".pyc" and source_path.with_suffix(".py").is_file():
            source_path = source_path.with_suffix(".py")
        source_path = source_path.resolve(strict=True)
        trusted_module_map[module_name] = trusted_runtime_module
        trusted_module_rows.append(
            (
                module_name,
                trusted_runtime_module,
                getattr(trusted_runtime_module, "__spec__", None),
                module_file,
                source_path,
                source_path.read_bytes(),
            )
        )
    trusted_modules: Mapping[str, ModuleType] = MappingProxyType(trusted_module_map)
    distribution_module_names = plugin_module_names | {"pytest", "pluggy"}
    trusted_distribution_identities: Mapping[str, tuple[str | None, str | None]] = MappingProxyType(
        {
            module_name: _module_distribution_identity(module_name)
            for module_name in distribution_module_names
        }
    )
    trusted_pytest_version = importlib_metadata.version("pytest")
    trusted_pluggy_version = importlib_metadata.version("pluggy")
    config_module = trusted_modules["_pytest.config"]
    trusted_default_plugins = getattr(config_module, "default_plugins", None)
    if not isinstance(trusted_default_plugins, tuple):
        raise RuntimeError("Trusted pytest default plugin tuple is unavailable during sealing.")
    anchors = tuple(
        (
            name,
            value,
            getattr(value, "__code__", None),
        )
        for name, value in (
            ("_require_production_preparation", require_preparation),
            ("_production_validation_run_id", production_run_id),
            ("_path_is_link_like", path_is_link_like),
            ("_create_guarded_junit_file", create_guarded_junit_file),
            ("_build_production_pytest_plan_projection", build_projection),
            ("pytest_plan_id_from_projection", compute_plan_id),
            ("_retained_junit_handle_is_open", retained_handle_is_open),
            ("_allocate_production_plan_capability", allocate_plan),
            ("_record_production_plan_draft", record_plan),
            ("PytestPlan", production_plan_type),
            ("_PlanDraft", draft_type),
            ("P2Stage1Error", error_type),
            ("EVIDENCE_CONTRACT_CHECKPOINT", EVIDENCE_CONTRACT_CHECKPOINT),
            ("PROTOCOL_CHECKPOINT", PROTOCOL_CHECKPOINT),
            ("STUDY_ID", STUDY_ID),
            ("protocol_hash", protocol_hash),
            ("repository_root", repository_root),
        )
    )

    def validate_dependencies() -> None:
        if sys.modules is not trusted_sys_modules:
            raise error_type(
                "CALLABLE_IDENTITY_MISMATCH",
                "The interpreter module registry was replaced.",
                layer="plan_identities",
            )
        for (
            module_name,
            module,
            module_spec,
            module_file,
            source_path,
            source_bytes,
        ) in trusted_module_rows:
            if (
                trusted_sys_modules.get(module_name) is not module
                or getattr(module, "__spec__", None) is not module_spec
                or getattr(module, "__file__", None) != module_file
                or source_path.read_bytes() != source_bytes
            ):
                raise error_type(
                    "CALLABLE_IDENTITY_MISMATCH",
                    f"Trusted pytest runtime module changed: {module_name}.",
                    layer="plan_identities",
                )
        if getattr(config_module, "default_plugins", None) is not trusted_default_plugins:
            raise error_type(
                "CALLABLE_IDENTITY_MISMATCH",
                "Trusted pytest default plugin contract changed.",
                layer="plan_identities",
            )
        for name, expected, code in anchors:
            current = trusted_module.__dict__.get(name)
            if current is not expected or (
                code is not None and getattr(current, "__code__", None) is not code
            ):
                raise error_type(
                    "CALLABLE_IDENTITY_MISMATCH",
                    f"Trusted production pytest dependency was replaced: {name}.",
                    layer="plan_identities",
                )

    def issue(
        *,
        preparation: _ProductionPreparationCapability,
        context: Layer0Context,
        validation_run: ValidationRun,
        control_directory: Path,
        control_directory_identity: FileIdentity,
        retain_provisional_handle: Callable[[_ProvisionalJunitHandle], None] | None = None,
        retain_handle: (
            Callable[[_ProvisionalJunitHandle, _RetainedJunitHandle], None] | None
        ) = None,
        begin_acquisition: Callable[[], None] | None = None,
        cancel_acquisition: Callable[[], None] | None = None,
        acquisition_checkpoint: Callable[[], None] | None = None,
        retained_checkpoint: Callable[[], None] | None = None,
    ) -> tuple[_PlanDraft, _RetainedJunitHandle]:
        validate_dependencies()
        require_preparation(preparation, validation_run=validation_run)
        if (
            retain_provisional_handle is None
            or retain_handle is None
            or not callable(retain_provisional_handle)
            or not callable(retain_handle)
            or begin_acquisition is None
            or cancel_acquisition is None
            or acquisition_checkpoint is None
            or retained_checkpoint is None
            or not callable(begin_acquisition)
            or not callable(cancel_acquisition)
            or not callable(acquisition_checkpoint)
            or not callable(retained_checkpoint)
        ):
            raise error_type(
                "PYTEST_PLAN_ID_MISMATCH",
                "Production pytest issuance requires exact session resource ownership.",
                layer="plan_identities",
            )
        if (
            type(control_directory_identity) is not tuple
            or len(control_directory_identity) != 2
            or any(type(value) is not int for value in control_directory_identity)
        ):
            raise error_type(
                "PYTEST_PLAN_ID_MISMATCH",
                "Production pytest issuance requires the exact owned directory identity.",
                layer="plan_identities",
            )
        run_id = production_run_id(validation_run)
        if (
            getattr(entropy_module, "urandom", None) is not entropy
            or type(entropy) is not BuiltinFunctionType
            or getattr(entropy, "__name__", None) != "urandom"
            or getattr(entropy, "__module__", None) != entropy_origin
        ):
            raise error_type(
                "PYTEST_PLAN_ID_MISMATCH",
                "Production pytest OS-entropy authority was replaced.",
                layer="plan_identities",
            )
        control_root = control_directory.resolve(strict=True)
        if (
            control_root != control_directory
            or path_is_link_like(control_root)
            or not control_root.is_dir()
        ):
            raise error_type(
                "PYTEST_PLAN_ID_MISMATCH",
                "Pytest control directory must be an exact regular directory.",
                layer="plan_identities",
            )
        initial_bytes = entropy(32)
        if type(initial_bytes) is not bytes or len(initial_bytes) != 32:
            raise error_type(
                "PYTEST_PLAN_ID_MISMATCH",
                "Production pytest entropy did not return exactly 32 bytes.",
                layer="plan_identities",
            )
        junit_path = control_root / "pytest-junit.xml"
        retained_handle = create_guarded_junit_file(
            junit_path,
            initial_bytes=initial_bytes,
            expected_control_directory_identity=control_directory_identity,
            retain_provisional_handle=retain_provisional_handle,
            retain_handle=retain_handle,
            begin_acquisition=begin_acquisition,
            cancel_acquisition=cancel_acquisition,
            acquisition_checkpoint=acquisition_checkpoint,
            retained_checkpoint=retained_checkpoint,
        )
        if retained_handle.control_directory_identity != control_directory_identity:
            raise error_type(
                "PYTEST_PLAN_ID_MISMATCH",
                "Retained JUnit ownership differs from the central directory owner.",
                layer="plan_identities",
            )
        projection = build_projection(
            context=context,
            validation_run_id=run_id,
            control_directory=control_root,
            retained_handle=retained_handle,
            trusted_modules=trusted_modules,
            trusted_distribution_identities=trusted_distribution_identities,
            trusted_pytest_version=trusted_pytest_version,
            trusted_pluggy_version=trusted_pluggy_version,
        )
        persistent_id = compute_plan_id(projection)
        capability = allocate_plan(
            preparation,
            validation_run,
            capability_type=production_plan_type,
            kind="pytest",
            role="pytest",
            persistent_id=persistent_id,
        )
        draft = draft_type(
            capability=capability,
            kind="pytest",
            role="pytest",
            persistent_id=persistent_id,
            validation_run=validation_run,
            validation_run_id=run_id,
            projection=projection,
        )
        record_plan(preparation, validation_run, draft)
        if not retained_handle_is_open(retained_handle):
            raise error_type(
                "PYTEST_PLAN_ID_MISMATCH",
                "Production pytest plan lost its retained JUnit handle.",
                layer="plan_identities",
            )
        validate_dependencies()
        require_preparation(preparation, validation_run=validation_run)
        return draft, retained_handle

    wrapped_issue = _seal_production_component_callable("pytest_plan", issue)
    wrapped_validate = _seal_production_component_callable(
        "pytest_runtime_validate",
        validate_dependencies,
    )
    return (
        cast(_ProductionPytestPlanDraftIssuer, wrapped_issue),
        cast(Callable[[], None], wrapped_validate),
    )


def _issue_fixture_pytest_plan(
    *,
    projection: PytestPlanProjection,
    validation_run: _FixtureValidationRun,
) -> _FixturePytestPlan:
    """Register a fixture-only pytest plan in the disjoint fixture registry."""

    if type(projection) is not PytestPlanProjection:
        raise P2Stage1Error(
            "PYTEST_PLAN_ID_MISMATCH",
            "Fixture pytest plan requires the exact closed projection type.",
            layer="plan_identities",
        )
    run_id = _fixture_validation_run_id(validation_run)
    if projection.validation_run_id != run_id:
        raise P2Stage1Error(
            "ISSUED_PLAN_RUN_MISMATCH",
            "Fixture pytest plan and validation-run capability differ.",
            layer="plan_identities",
        )
    persistent_id = pytest_plan_id_from_projection(projection)
    capability = object.__new__(_FixturePytestPlan)
    draft = _PlanDraft(
        capability=capability,
        kind="pytest",
        role="pytest",
        persistent_id=persistent_id,
        validation_run=validation_run,
        validation_run_id=run_id,
        projection=projection,
    )
    _register_fixture_plan(draft)
    return capability


def _build_production_pytest_plan_projection(
    *,
    context: Layer0Context,
    validation_run_id: str,
    control_directory: Path,
    retained_handle: _RetainedJunitHandle,
    trusted_modules: Mapping[str, ModuleType],
    trusted_distribution_identities: Mapping[str, tuple[str | None, str | None]],
    trusted_pytest_version: str,
    trusted_pluggy_version: str,
) -> PytestPlanProjection:
    """Construct but never execute the exact production pytest plan."""

    root = repository_root().resolve(strict=True)
    config_path = (root / "pyproject.toml").resolve(strict=True)
    tests_root = (root / "tests").resolve(strict=True)
    control_root = control_directory.resolve(strict=True)
    if (
        control_root != control_directory
        or _path_is_link_like(control_root)
        or not control_root.is_dir()
        or type(retained_handle) is not _RetainedJunitHandle
        or retained_handle.control_directory != control_root
        or not _retained_junit_handle_is_open(retained_handle)
    ):
        raise P2Stage1Error(
            "PYTEST_PLAN_ID_MISMATCH",
            "Pytest control directory and retained JUnit handle do not reconcile.",
            layer="plan_identities",
        )
    junit_path = retained_handle.destination_path
    specification_path = control_root / "pytest-plan.json"
    start_receipt_path = control_root / "pytest-start.json"
    completion_receipt_path = control_root / "pytest-completion.json"
    selected = (PytestSelectedTestProjection("path", str(tests_root)),)
    command = (
        str(Path(sys.executable).resolve(strict=True)),
        "-P",
        "-m",
        "pytest",
        "-p",
        _PLUGIN_NAME,
        "-c",
        str(config_path),
        f"--rootdir={root}",
        f"--confcutdir={tests_root}",
        f"--junitxml={junit_path.resolve(strict=True)}",
        str(tests_root),
    )
    environment = _base_subprocess_environment()
    environment_rows = tuple(
        PytestEnvironmentRow(
            name=name,
            name_sha256=hashlib.sha256(name.encode("utf-8")).hexdigest(),
            value_byte_count=len(value.encode("utf-8")),
            value_sha256=hashlib.sha256(value.encode("utf-8")).hexdigest(),
        )
        for name, value in sorted(environment.items(), key=lambda item: item[0].encode("utf-8"))
    )
    controlled = tuple(
        PytestControlledEnvironmentRow("unset" if value is None else "set", name, value)
        for name, value in _CONTROLLED_SUBPROCESS_ENVIRONMENT
    )
    expected_conftests = _expected_conftest_identities(root, (str(tests_root),))
    _, expected_plugins = _expected_plugin_lifecycle(
        expected_conftests,
        trusted_modules=trusted_modules,
        trusted_distribution_identities=trusted_distribution_identities,
    )
    plugins = tuple(
        sorted(
            (
                PytestPluginProjection(
                    distribution_name=distribution_name,
                    distribution_version=distribution_version,
                    module_name=module_name,
                    plugin_name=plugin_name,
                    qualname=qualname,
                    source_path=source_path,
                    source_sha256=source_sha256,
                )
                for (
                    plugin_name,
                    module_name,
                    qualname,
                    source_path,
                    source_sha256,
                    distribution_name,
                    distribution_version,
                ) in expected_plugins
            ),
            key=lambda item: tuple(
                "" if value is None else value
                for value in (
                    item.distribution_name,
                    item.distribution_version,
                    item.module_name,
                    item.plugin_name,
                    item.qualname,
                    item.source_path,
                    item.source_sha256,
                )
            ),
        )
    )
    conftests = tuple(
        FileProjection(
            byte_count=len(Path(path).read_bytes()),
            path=path,
            sha256=sha256,
        )
        for path, sha256 in expected_conftests
    )
    pytest_module = trusted_modules.get("pytest")
    pluggy_module = trusted_modules.get("pluggy")
    if type(pytest_module) is not ModuleType or type(pluggy_module) is not ModuleType:
        raise P2Stage1Error(
            "PYTEST_PLAN_ID_MISMATCH",
            "Trusted pytest runtime modules are unavailable.",
            layer="plan_identities",
        )
    pytest_source = _module_source_file(pytest_module)
    pluggy_source = _module_source_file(pluggy_module)
    validation_source_raw = Path(__file__).read_bytes()
    validation_source = FileProjection(
        len(validation_source_raw),
        str(Path(__file__).resolve(strict=True)),
        hashlib.sha256(validation_source_raw).hexdigest(),
    )
    config_raw = config_path.read_bytes()
    environment_sha256 = protocol_hash(
        "validation_evidence_pytest_environment/v1",
        [row.as_dict() for row in environment_rows],
    )
    return PytestPlanProjection(
        argv=command,
        conftests=conftests,
        control_paths=PytestControlPathsProjection(
            completion_receipt_path=str(completion_receipt_path.resolve()),
            specification_path=str(specification_path.resolve()),
            start_receipt_path=str(start_receipt_path.resolve()),
        ),
        controlled_environment=controlled,
        environment=environment_rows,
        environment_sha256=environment_sha256,
        evidence_contract_checkpoint=EVIDENCE_CONTRACT_CHECKPOINT,
        implementation=context.implementation,
        junit_destination=PytestJunitDestinationProjection(
            destination_path=str(junit_path),
            device_id=retained_handle.file_identity[0],
            file_id=retained_handle.file_identity[1],
            initial_sha256=retained_handle.initial_sha256,
            initial_byte_count=retained_handle.initial_byte_count,
        ),
        plan_issuer_identity=context.pytest_plan_issuer_identity,
        plugins=plugins,
        protocol_checkpoint=PROTOCOL_CHECKPOINT,
        pytest_configuration=FileProjection(
            len(config_raw), str(config_path), hashlib.sha256(config_raw).hexdigest()
        ),
        pytest_rootdir=str(root),
        pytest_runtime=PytestRuntimeProjection(
            pluggy_source=pluggy_source,
            pluggy_version=trusted_pluggy_version,
            pytest_source=pytest_source,
            pytest_version=trusted_pytest_version,
            validation_plugin_source=validation_source,
        ),
        repository_root=str(root),
        runtime=context.runtime,
        runtime_identity=context.runtime_identity,
        selected_tests=selected,
        validation_run_id=validation_run_id,
        working_directory=str(root),
    )


def _module_source_file(module: ModuleType) -> FileProjection:
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str):
        raise P2Stage1Error(
            "PYTEST_PLAN_ID_MISMATCH",
            "Pytest runtime module has no source file.",
            layer="plan_identities",
        )
    path = Path(module_file)
    if path.suffix == ".pyc" and path.with_suffix(".py").is_file():
        path = path.with_suffix(".py")
    path = path.resolve(strict=True)
    raw = path.read_bytes()
    return FileProjection(len(raw), str(path), hashlib.sha256(raw).hexdigest())


def pytest_plan_id(plan: PytestPlan) -> str:
    from research_decision_engine.benchmarks.broader_validation_evidence import plan_persistent_id

    if type(plan) is not PytestPlan:
        raise P2Stage1Error(
            "ISSUED_PLAN_CAPABILITY_INVALID",
            "Exact production PytestPlan capability required.",
            layer="live_issued_plan_binding",
        )
    return plan_persistent_id(plan)


def p2_pytest_plan_projection(plan: PytestPlan) -> PytestPlanProjection:
    from research_decision_engine.benchmarks.broader_validation_evidence import plan_projection

    if type(plan) is not PytestPlan:
        raise P2Stage1Error(
            "ISSUED_PLAN_CAPABILITY_INVALID",
            "Exact production PytestPlan capability required.",
            layer="live_issued_plan_binding",
        )
    projection = plan_projection(plan)
    if type(projection) is not PytestPlanProjection:
        raise P2Stage1Error(
            "PYTEST_PLAN_ID_MISMATCH",
            "Issued PytestPlan has the wrong projection type.",
            layer="plan_identities",
        )
    return projection


def _fixture_pytest_plan_id(plan: _FixturePytestPlan) -> str:
    from research_decision_engine.benchmarks.broader_validation_evidence import plan_persistent_id

    if type(plan) is not _FixturePytestPlan:
        raise P2Stage1Error(
            "ISSUED_PLAN_CAPABILITY_INVALID",
            "Exact fixture pytest plan capability required.",
            layer="live_issued_plan_binding",
        )
    return plan_persistent_id(plan)


def _fixture_pytest_plan_projection(plan: _FixturePytestPlan) -> PytestPlanProjection:
    from research_decision_engine.benchmarks.broader_validation_evidence import plan_projection

    if type(plan) is not _FixturePytestPlan:
        raise P2Stage1Error(
            "ISSUED_PLAN_CAPABILITY_INVALID",
            "Exact fixture pytest plan capability required.",
            layer="live_issued_plan_binding",
        )
    projection = plan_projection(plan)
    if type(projection) is not PytestPlanProjection:
        raise P2Stage1Error(
            "PYTEST_PLAN_ID_MISMATCH",
            "Issued fixture pytest plan has the wrong projection type.",
            layer="plan_identities",
        )
    return projection


def _execute_pytest_validation_fixture(
    *,
    validation_run_identity: str,
    targets: Sequence[Path],
    timeout_seconds: float = 60.0,
    execution_root: Path | None = None,
) -> PytestValidationResult:
    """Run real pytest against explicit tiny targets for unit tests only."""

    if not targets:
        raise PytestValidationError("A pytest validation fixture needs an explicit target.")
    resolved_targets: list[str] = []
    for target in targets:
        if not isinstance(target, Path):
            raise TypeError("Pytest validation fixture targets must be pathlib.Path values.")
        if target.is_symlink() or not (target.is_file() or target.is_dir()):
            raise PytestValidationError(
                "Pytest validation fixture targets must be regular files or directories."
            )
        resolved_targets.append(str(target.resolve(strict=True)))
    return _execute_pytest_validation(
        validation_run_identity=validation_run_identity,
        issuer_kind="fixture",
        targets=tuple(resolved_targets),
        timeout_seconds=timeout_seconds,
        execution_root=None if execution_root is None else execution_root.resolve(strict=True),
    )


def observe_pytest_validation_result(
    result: PytestValidationResult,
    *,
    owner_claim: PytestValidationOwnerClaim | None = None,
) -> PytestValidationObservation:
    """Return the immutable observation for one exact, current issued object."""

    return _require_issued_result(
        result,
        require_active=True,
        require_current=True,
        owner_claim=owner_claim,
    ).observation


def claim_pytest_validation_result_owner(
    result: PytestValidationResult,
) -> PytestValidationOwnerClaim:
    """Atomically reserve one active result for one exact opaque owner."""

    record = _require_issued_result(
        result,
        require_active=True,
        require_current=True,
        owner_claim=None,
    )
    claim = PytestValidationOwnerClaim(_OWNER_CLAIM_CONSTRUCTION_KEY)
    with _RESULT_LOCK:
        current = _ISSUED_RESULTS.get(id(result))
        if (
            current is not record
            or current.result is not result
            or not current.active
            or current.owner_claim is not None
        ):
            raise PytestValidationError("Pytest validation result is already claimed or stale.")
        current.owner_claim = claim
    return claim


def release_pytest_validation_result_owner(
    result: PytestValidationResult,
    *,
    owner_claim: PytestValidationOwnerClaim,
) -> None:
    """Release one exact active claim without consuming its validation result."""

    record = _require_issued_result(
        result,
        require_active=True,
        require_current=True,
        owner_claim=owner_claim,
    )
    with _RESULT_LOCK:
        current = _ISSUED_RESULTS.get(id(result))
        if (
            current is not record
            or current.result is not result
            or not current.active
            or current.owner_claim is not owner_claim
        ):
            raise PytestValidationError("Pytest validation owner claim is forged or stale.")
        current.owner_claim = None


def validate_pytest_validation_result(
    result: PytestValidationResult,
    *,
    validation_run_identity: str,
    owner_claim: PytestValidationOwnerClaim | None = None,
) -> PytestValidationObservation:
    """Validate a successful production full-suite result for the named run."""

    _validate_external_identity(validation_run_identity, "validation run")
    record = _require_issued_result(
        result,
        require_active=True,
        require_current=True,
        owner_claim=owner_claim,
    )
    observation = record.observation
    if observation.validation_run_identity != validation_run_identity:
        raise PytestValidationError("Pytest result belongs to another validation run.")
    if observation.issuer_kind != "production":
        raise PytestValidationError("Fixture pytest evidence is not production evidence.")
    if not _is_fixed_production_command(observation):
        raise PytestValidationError("Production pytest command differs from the fixed command.")
    if (
        observation.execution_status != "COMPLETED"
        or not observation.completed
        or observation.exit_code != 0
        or observation.failed != 0
        or observation.errors != 0
        or observation.junit_xml_sha256 is None
        or observation.subprocess_start_identity is None
        or observation.subprocess_completion_identity is None
        or observation.total <= 0
        or observation.total != len(observation.collected_node_ids)
        or bool(observation.deselected_node_ids)
        or not observation.junit_case_identities
    ):
        raise PytestValidationError("Production pytest validation did not complete successfully.")
    return observation


def bind_pytest_validation_result_to_bundle(
    result: PytestValidationResult,
    *,
    validation_run_identity: str,
    evidence_bundle_identity: str,
    owner_claim: PytestValidationOwnerClaim | None = None,
) -> PytestValidationObservation:
    """Bind one exact issued result to one evidence bundle identity."""

    _validate_external_identity(validation_run_identity, "validation run")
    _validate_external_identity(evidence_bundle_identity, "evidence bundle")
    if validation_run_identity == evidence_bundle_identity:
        raise PytestValidationError(
            "Validation-run and evidence-bundle identities must be distinct."
        )
    record = _require_issued_result(
        result,
        require_active=True,
        require_current=True,
        owner_claim=owner_claim,
    )
    if record.observation.validation_run_identity != validation_run_identity:
        raise PytestValidationError("Pytest result belongs to another validation run.")
    with _RESULT_LOCK:
        current = _ISSUED_RESULTS.get(id(result))
        if current is not record or current.result is not result or not current.active:
            raise PytestValidationError("Pytest validation result is forged or stale.")
        _require_owner_claim(current, owner_claim)
        if current.evidence_bundle_identity is not None:
            if current.evidence_bundle_identity != evidence_bundle_identity:
                raise PytestValidationError("Pytest result is already bound to another bundle.")
            return current.observation
        if evidence_bundle_identity in _USED_EVIDENCE_BUNDLE_IDENTITIES:
            raise PytestValidationError("Evidence-bundle identity already has pytest evidence.")
        current.evidence_bundle_identity = evidence_bundle_identity
        _USED_EVIDENCE_BUNDLE_IDENTITIES.add(evidence_bundle_identity)
    return record.observation


def issued_pytest_validation_junit_bytes(
    result: PytestValidationResult,
    *,
    evidence_bundle_identity: str | None = None,
    owner_claim: PytestValidationOwnerClaim | None = None,
) -> bytes:
    """Return a defensive copy of registry-owned exact JUnit bytes."""

    record = _require_issued_result(
        result,
        require_active=True,
        require_current=True,
        owner_claim=owner_claim,
    )
    _require_bundle_if_supplied(record, evidence_bundle_identity)
    if record.observation.junit_xml_sha256 is None:
        raise PytestValidationError("Issued pytest result has no validated JUnit XML bytes.")
    return bytes(bytearray(record.junit_xml_bytes))


def validate_pytest_validation_junit_bytes(
    result: PytestValidationResult,
    junit_xml_bytes: bytes | bytearray | memoryview,
    *,
    evidence_bundle_identity: str | None = None,
    owner_claim: PytestValidationOwnerClaim | None = None,
) -> None:
    """Reject substituted or changed JUnit bytes for an exact issued result."""

    record = _require_issued_result(
        result,
        require_active=True,
        require_current=True,
        owner_claim=owner_claim,
    )
    _require_bundle_if_supplied(record, evidence_bundle_identity)
    supplied = bytes(junit_xml_bytes)
    if supplied != record.junit_xml_bytes:
        raise PytestValidationError("JUnit XML bytes differ from the issued pytest evidence.")
    observed_hash = record.observation.junit_xml_sha256
    if observed_hash is None or hashlib.sha256(supplied).hexdigest() != observed_hash:
        raise PytestValidationError("JUnit XML hash differs from the issued pytest evidence.")


def consume_pytest_validation_result(
    result: PytestValidationResult,
    *,
    validation_run_identity: str,
    evidence_bundle_identity: str,
    owner_claim: PytestValidationOwnerClaim | None = None,
) -> PytestValidationObservation:
    """Consume a bound result once and make its capability stale."""

    _validate_external_identity(validation_run_identity, "validation run")
    _validate_external_identity(evidence_bundle_identity, "evidence bundle")
    record = _require_issued_result(
        result,
        require_active=True,
        require_current=True,
        owner_claim=owner_claim,
    )
    if record.observation.validation_run_identity != validation_run_identity:
        raise PytestValidationError("Pytest result belongs to another validation run.")
    if record.evidence_bundle_identity != evidence_bundle_identity:
        raise PytestValidationError("Pytest result belongs to another evidence bundle.")
    with _RESULT_LOCK:
        current = _ISSUED_RESULTS.get(id(result))
        if current is not record or current.result is not result or not current.active:
            raise PytestValidationError("Pytest validation result is forged or stale.")
        _require_owner_claim(current, owner_claim)
        current.active = False
        current.owner_claim = None
    return record.observation


def pytest_plugin_registered(plugin: object, plugin_name: str, manager: object) -> None:
    """Trace every historic and future registration in the validation subprocess."""

    if os.environ.get(_ENV_NONCE) is None:
        return
    tracker = _plugin_lifecycle_tracker(manager)
    _record_plugin_lifecycle_event(
        tracker,
        action="register",
        plugin_name=plugin_name,
        plugin=plugin,
    )


def _plugin_lifecycle_tracker(manager: object) -> _PluginLifecycleTracker:
    key = id(manager)
    tracker = _PLUGIN_LIFECYCLE_TRACKERS.get(key)
    if tracker is not None:
        if tracker.manager is not manager:
            raise RuntimeError("Pytest plugin lifecycle manager identity was reused.")
        return tracker
    observed_manager = cast(Any, manager)
    original_unregister = cast(Callable[..., object], observed_manager.unregister)
    tracker = _PluginLifecycleTracker(
        manager=manager,
        events=(),
        lock=threading.RLock(),
        original_unregister=original_unregister,
        guarded_unregister=None,
    )

    def guarded_unregister(plugin: object | None = None, name: str | None = None) -> object:
        with tracker.lock:
            target_plugin = plugin
            target_name = name
            if target_name is None and target_plugin is not None:
                target_name = cast(str | None, observed_manager.get_name(target_plugin))
            if target_plugin is None and target_name is not None:
                target_plugin = observed_manager.get_plugin(target_name)
            result = original_unregister(plugin=plugin, name=name)
            if result is not None:
                if target_plugin is None or target_name is None:
                    raise RuntimeError("Unregistered pytest plugin lacked a traceable identity.")
                _record_plugin_lifecycle_event(
                    tracker,
                    action="unregister",
                    plugin_name=target_name,
                    plugin=target_plugin,
                )
            return result

    tracker.guarded_unregister = guarded_unregister
    observed_manager.unregister = guarded_unregister
    _PLUGIN_LIFECYCLE_TRACKERS[key] = tracker
    return tracker


def _record_plugin_lifecycle_event(
    tracker: _PluginLifecycleTracker,
    *,
    action: PluginLifecycleAction,
    plugin_name: str,
    plugin: object,
) -> None:
    identity = _plugin_identity_from_object(plugin_name, plugin)
    with tracker.lock:
        tracker.events = (
            *tracker.events,
            _PluginLifecycleEvent(
                sequence=len(tracker.events), action=action, plugin_identity=identity
            ),
        )


def _require_plugin_lifecycle_tracker(config: object) -> _PluginLifecycleTracker:
    manager = cast(Any, config).pluginmanager
    tracker = _PLUGIN_LIFECYCLE_TRACKERS.get(id(manager))
    if tracker is None or tracker.manager is not manager:
        raise RuntimeError("Pytest plugin lifecycle tracing was not installed historically.")
    if cast(Any, manager).unregister is not tracker.guarded_unregister:
        raise RuntimeError("Pytest plugin lifecycle unregistration guard was replaced.")
    return tracker


def _plugin_lifecycle_snapshot(
    tracker: _PluginLifecycleTracker,
) -> tuple[_PluginLifecycleEvent, ...]:
    with tracker.lock:
        return tracker.events


def _plugin_lifecycle_event_values(event: _PluginLifecycleEvent) -> dict[str, object]:
    return {
        "action": event.action,
        "plugin_identity": list(event.plugin_identity),
        "sequence": event.sequence,
    }


def pytest_configure(config: object) -> None:
    """Persist the independently observed start of the pytest process chain."""

    global _PLUGIN_STATE
    provided = {
        name: os.environ.get(name)
        for name in (
            _ENV_NONCE,
            _ENV_RUN_IDENTITY,
            _ENV_COMMAND_SHA256,
            _ENV_START_SEED_IDENTITY,
            _ENV_SPECIFICATION_PATH,
            _ENV_START_RECEIPT_PATH,
            _ENV_RECEIPT_PATH,
            _ENV_JUNIT_PATH,
        )
    }
    if all(value is None for value in provided.values()):
        return
    if any(value is None for value in provided.values()):
        raise RuntimeError("Incomplete broader pytest validation plugin environment.")
    nonce = _required_environment_value(provided, _ENV_NONCE)
    validation_run_identity = _required_environment_value(provided, _ENV_RUN_IDENTITY)
    command_sha256 = _required_environment_value(provided, _ENV_COMMAND_SHA256)
    start_seed_identity = _required_environment_value(provided, _ENV_START_SEED_IDENTITY)
    specification_path = Path(_required_environment_value(provided, _ENV_SPECIFICATION_PATH))
    start_receipt_path = Path(_required_environment_value(provided, _ENV_START_RECEIPT_PATH))
    receipt_path = Path(_required_environment_value(provided, _ENV_RECEIPT_PATH))
    junit_path = Path(_required_environment_value(provided, _ENV_JUNIT_PATH))
    _require_sha256(nonce, "plugin nonce")
    _validate_external_identity(validation_run_identity, "plugin validation run")
    _require_sha256(command_sha256, "plugin command")
    _require_sha256(start_seed_identity, "plugin start seed")
    for path, label in (
        (specification_path, "specification"),
        (start_receipt_path, "start receipt"),
        (receipt_path, "completion receipt"),
        (junit_path, "JUnit"),
    ):
        if not path.is_absolute():
            raise RuntimeError(f"Pytest validation {label} path is not absolute.")
    if start_receipt_path.exists() or receipt_path.exists():
        raise RuntimeError("Pytest validation receipt paths are not fresh.")
    specification_document = _load_canonical_json_object(
        specification_path, "pytest execution specification"
    )
    specification_identity = _document_str(
        specification_document, "execution_specification_identity"
    )
    specification_values = {
        key: value
        for key, value in specification_document.items()
        if key != "execution_specification_identity"
    }
    if specification_identity != protocol_hash(
        "pytest_execution_specification/v1", specification_values
    ):
        raise RuntimeError("Pytest execution specification identity does not reconcile.")
    if (
        _document_str(specification_document, "validation_run_identity") != validation_run_identity
        or _document_str(specification_document, "command_sha256") != command_sha256
        or _document_str(specification_document, "junit_xml_path") != str(junit_path)
    ):
        raise RuntimeError("Pytest execution specification differs from the plugin environment.")
    junit_file_identity, junit_file_descriptor = _install_authoritative_junit_writer(
        config,
        specification_document=specification_document,
        junit_path=junit_path,
    )

    argv_tail = tuple(sys.argv[1:])
    plugin_path = Path(__file__).resolve(strict=True)
    plugin_source_sha256 = hashlib.sha256(plugin_path.read_bytes()).hexdigest()
    pytest_version, pytest_source_sha256 = _distribution_runtime_identity("pytest")
    pluggy_version, pluggy_source_sha256 = _distribution_runtime_identity("pluggy")
    controlled_environment = tuple(_expected_runtime_controlled_environment(pytest_version).items())
    if dict(controlled_environment) != {
        name: os.environ.get(name) for name, _ in _CONTROLLED_SUBPROCESS_ENVIRONMENT
    }:
        raise RuntimeError("Pytest runtime control environment differs from its specification.")
    subprocess_environment_sha256 = _subprocess_environment_sha256(_base_subprocess_environment())
    interpreter_path = str(Path(sys.executable).resolve(strict=True))
    interpreter_executable_sha256 = hashlib.sha256(Path(interpreter_path).read_bytes()).hexdigest()
    base_interpreter_path = str(
        Path(cast(str, getattr(sys, "_base_executable", sys.executable))).resolve(strict=True)
    )
    base_interpreter_executable_sha256 = hashlib.sha256(
        Path(base_interpreter_path).read_bytes()
    ).hexdigest()
    observed_configuration = _observe_pytest_configuration(config)
    initial_plugin_identities = _effective_plugin_identities(config)
    plugin_lifecycle_tracker = _require_plugin_lifecycle_tracker(config)
    initial_plugin_lifecycle_events = _plugin_lifecycle_snapshot(plugin_lifecycle_tracker)
    plugin_lifecycle_start_identity = protocol_hash(
        "pytest_plugin_lifecycle_start/v1",
        {
            "events": [
                _plugin_lifecycle_event_values(item) for item in initial_plugin_lifecycle_events
            ],
            "initial_plugin_identities": [list(item) for item in initial_plugin_identities],
        },
    )
    start_values: dict[str, object] = {
        "argv_tail": list(argv_tail),
        "command_sha256": command_sha256,
        "controlled_environment": dict(controlled_environment),
        "base_interpreter_executable_sha256": base_interpreter_executable_sha256,
        "base_interpreter_path": base_interpreter_path,
        "execution_specification_identity": specification_identity,
        "interpreter_executable_sha256": interpreter_executable_sha256,
        "interpreter_path": interpreter_path,
        "junit_file_identity": list(junit_file_identity),
        "nonce": nonce,
        "observed_configuration": _observed_configuration_values(observed_configuration),
        "parent_pid": os.getppid(),
        "pid": os.getpid(),
        "plugin_identities": [list(item) for item in initial_plugin_identities],
        "plugin_lifecycle_events": [
            _plugin_lifecycle_event_values(item) for item in initial_plugin_lifecycle_events
        ],
        "plugin_lifecycle_start_identity": plugin_lifecycle_start_identity,
        "plugin_source_sha256": plugin_source_sha256,
        "pluggy_source_sha256": pluggy_source_sha256,
        "pluggy_version": pluggy_version,
        "pytest_source_sha256": pytest_source_sha256,
        "pytest_version": pytest_version,
        "start_seed_identity": start_seed_identity,
        "subprocess_environment_sha256": subprocess_environment_sha256,
        "validation_run_identity": validation_run_identity,
        "validation_version": PYTEST_VALIDATION_VERSION,
    }
    subprocess_start_identity = protocol_hash("pytest_subprocess_start/v2", start_values)
    start_receipt_values = {
        **start_values,
        "subprocess_start_identity": subprocess_start_identity,
    }
    start_receipt_bytes = canonical_json_bytes(start_receipt_values, final_lf=True)
    _write_exclusive_bytes(start_receipt_path, start_receipt_bytes, "start receipt")
    _PLUGIN_STATE = _PluginState(
        nonce=nonce,
        validation_run_identity=validation_run_identity,
        command_sha256=command_sha256,
        start_seed_identity=start_seed_identity,
        execution_specification_identity=specification_identity,
        start_receipt_path=start_receipt_path,
        receipt_path=receipt_path,
        junit_path=junit_path,
        junit_file_identity=junit_file_identity,
        junit_file_descriptor=junit_file_descriptor,
        pid=os.getpid(),
        parent_pid=os.getppid(),
        argv_tail=argv_tail,
        plugin_source_sha256=plugin_source_sha256,
        pytest_version=pytest_version,
        pytest_source_sha256=pytest_source_sha256,
        pluggy_version=pluggy_version,
        pluggy_source_sha256=pluggy_source_sha256,
        interpreter_path=interpreter_path,
        interpreter_executable_sha256=interpreter_executable_sha256,
        base_interpreter_path=base_interpreter_path,
        base_interpreter_executable_sha256=base_interpreter_executable_sha256,
        observed_configuration=observed_configuration,
        controlled_environment=controlled_environment,
        subprocess_environment_sha256=subprocess_environment_sha256,
        subprocess_start_identity=subprocess_start_identity,
        start_receipt_sha256=hashlib.sha256(start_receipt_bytes).hexdigest(),
        initial_plugin_identities=initial_plugin_identities,
        initial_plugin_lifecycle_events=initial_plugin_lifecycle_events,
        plugin_lifecycle_start_identity=plugin_lifecycle_start_identity,
        plugin_lifecycle_tracker=plugin_lifecycle_tracker,
        skips=[],
        skipped_node_ids=set(),
        collected_node_ids=[],
        deselected_node_ids=[],
        pending_completion=None,
        terminal_callback_pid=os.getpid(),
        terminalized=False,
    )


pytest_configure.pytest_impl = {  # type: ignore[attr-defined]
    "hookwrapper": False,
    "optionalhook": False,
    "specname": None,
    "tryfirst": False,
    "trylast": True,
    "wrapper": False,
}


def pytest_runtest_logreport(report: _PytestReport) -> None:
    """Capture exact pytest node IDs and skip reasons in execution order."""

    state = _PLUGIN_STATE
    if state is None or not report.skipped or report.nodeid in state.skipped_node_ids:
        return
    reason = _exact_skip_reason(report.longrepr)
    state.skips.append(_PluginSkip(node_id=report.nodeid, reason=reason))
    state.skipped_node_ids.add(report.nodeid)


def pytest_deselected(items: Sequence[_PytestItem]) -> None:
    """Record every exact node ID removed from the configured collection."""

    state = _PLUGIN_STATE
    if state is not None:
        state.deselected_node_ids.extend(item.nodeid for item in items)


def pytest_collection_finish(session: _PytestSession) -> None:
    """Record the final ordered collection after every deselection hook."""

    state = _PLUGIN_STATE
    if state is not None:
        state.collected_node_ids[:] = [item.nodeid for item in session.items]


def pytest_sessionfinish(session: _PytestSession, exitstatus: int) -> Iterator[None]:
    """Capture an immutable session checkpoint after native JUnit finalization."""

    try:
        yield
    finally:
        state = _PLUGIN_STATE
        if state is not None:
            _capture_pending_pytest_completion(state, session, exitstatus)


def _capture_pending_pytest_completion(
    state: _PluginState,
    session: _PytestSession,
    exitstatus: int,
) -> None:
    if state.pending_completion is not None:
        raise RuntimeError("Pytest validation session completion was captured more than once.")
    failure_details: list[str] = []
    junit: _JunitObservation | None = None
    junit_writer_identity: str | None = None
    if state.junit_path.is_file() and not state.junit_path.is_symlink():
        try:
            junit = _read_junit_observation(
                state.junit_path,
                pytest_root=Path(state.observed_configuration.root_directory),
                expected_file_identity=state.junit_file_identity,
                open_file_descriptor=state.junit_file_descriptor,
            )
            junit_writer_identity = _validated_authoritative_junit_writer_identity(
                session.config,
                state=state,
                junit=junit,
            )
        except PytestValidationError as error:
            failure_details.append(str(error))
    else:
        failure_details.append("native pytest JUnit was not finalized before the receipt")
    plugin_manager = cast(Any, session.config).pluginmanager
    if (
        state.plugin_lifecycle_tracker.manager is not plugin_manager
        or cast(Any, plugin_manager).unregister
        is not state.plugin_lifecycle_tracker.guarded_unregister
    ):
        failure_details.append("pytest plugin lifecycle guard was replaced")
    try:
        session_plugin_identities = _effective_plugin_identities(session.config)
    except PytestValidationError as error:
        failure_details.append(str(error))
        session_plugin_identities = ()
    try:
        observed_configuration = _observe_pytest_configuration(session.config)
    except (OSError, PytestValidationError) as error:
        failure_details.append(str(error))
        observed_configuration = state.observed_configuration
    if observed_configuration != state.observed_configuration:
        failure_details.append(
            "Effective pytest root/config/arguments changed after configuration."
        )
    state.pending_completion = _PendingPytestCompletion(
        config=session.config,
        exit_code=int(exitstatus),
        failure_details=tuple(failure_details),
        junit=junit,
        junit_writer_identity=junit_writer_identity,
        session_plugin_identities=session_plugin_identities,
        observed_configuration=observed_configuration,
        collected_node_ids=tuple(state.collected_node_ids),
        deselected_node_ids=tuple(state.deselected_node_ids),
        skips=tuple(state.skips),
    )


def _finalize_pytest_receipt_at_process_exit(issuing_pid: int) -> None:
    state = _PLUGIN_STATE
    if (
        state is None
        or issuing_pid != os.getpid()
        or state.terminal_callback_pid != issuing_pid
        or state.terminalized
    ):
        return
    state.terminalized = True
    try:
        pending = state.pending_completion
        if pending is not None:
            _finalize_pytest_receipt(state, pending)
    finally:
        with suppress(OSError):
            os.close(state.junit_file_descriptor)


def _finalize_pytest_receipt(
    state: _PluginState,
    pending: _PendingPytestCompletion,
) -> None:
    failure_details = list(pending.failure_details)
    if pending.junit is not None:
        try:
            terminal_junit = _read_junit_observation(
                state.junit_path,
                pytest_root=Path(pending.observed_configuration.root_directory),
                expected_file_identity=state.junit_file_identity,
                open_file_descriptor=state.junit_file_descriptor,
            )
            if terminal_junit != pending.junit:
                failure_details.append(
                    "pytest plugin and reopened JUnit observations differ after "
                    "session finalization"
                )
        except PytestValidationError as error:
            failure_details.append(str(error))
    plugin_manager = cast(Any, pending.config).pluginmanager
    if (
        state.plugin_lifecycle_tracker.manager is not plugin_manager
        or cast(Any, plugin_manager).unregister
        is not state.plugin_lifecycle_tracker.guarded_unregister
    ):
        failure_details.append("pytest plugin lifecycle guard was replaced")
    plugin_lifecycle_events = _plugin_lifecycle_snapshot(state.plugin_lifecycle_tracker)
    if (
        plugin_lifecycle_events[: len(state.initial_plugin_lifecycle_events)]
        != state.initial_plugin_lifecycle_events
    ):
        failure_details.append("pytest plugin lifecycle trace changed its start prefix")
    try:
        final_plugin_identities = _effective_plugin_identities(pending.config)
    except PytestValidationError as error:
        failure_details.append(str(error))
        final_plugin_identities = ()
    plugin_lifecycle_completion_identity = protocol_hash(
        "pytest_plugin_lifecycle_completion/v2",
        {
            "events": [_plugin_lifecycle_event_values(item) for item in plugin_lifecycle_events],
            "final_plugin_identities": [list(item) for item in final_plugin_identities],
            "session_plugin_identities": [list(item) for item in pending.session_plugin_identities],
            "start_identity": state.plugin_lifecycle_start_identity,
        },
    )
    conftest_identities = _conftest_identities(pending.session_plugin_identities)
    junit_values = None if pending.junit is None else _junit_values(pending.junit)
    receipt_values: dict[str, object] = {
        "argv_tail": list(state.argv_tail),
        "base_interpreter_executable_sha256": state.base_interpreter_executable_sha256,
        "base_interpreter_path": state.base_interpreter_path,
        "collected_node_ids": list(pending.collected_node_ids),
        "command_sha256": state.command_sha256,
        "conftest_identities": [list(item) for item in conftest_identities],
        "controlled_environment": dict(state.controlled_environment),
        "deselected_node_ids": list(pending.deselected_node_ids),
        "execution_specification_identity": state.execution_specification_identity,
        "exit_code": pending.exit_code,
        "failure_details": failure_details,
        "interpreter_executable_sha256": state.interpreter_executable_sha256,
        "interpreter_path": state.interpreter_path,
        "junit": junit_values,
        "junit_file_identity": list(state.junit_file_identity),
        "junit_writer_identity": pending.junit_writer_identity,
        "nonce": state.nonce,
        "observed_configuration": _observed_configuration_values(pending.observed_configuration),
        "parent_pid": state.parent_pid,
        "pid": state.pid,
        "final_plugin_identities": [list(item) for item in final_plugin_identities],
        "initial_plugin_identities": [list(item) for item in state.initial_plugin_identities],
        "session_plugin_identities": [list(item) for item in pending.session_plugin_identities],
        "plugin_source_sha256": state.plugin_source_sha256,
        "plugin_lifecycle_completion_identity": (plugin_lifecycle_completion_identity),
        "plugin_lifecycle_events": [
            _plugin_lifecycle_event_values(item) for item in plugin_lifecycle_events
        ],
        "plugin_lifecycle_start_identity": state.plugin_lifecycle_start_identity,
        "pluggy_source_sha256": state.pluggy_source_sha256,
        "pluggy_version": state.pluggy_version,
        "pytest_source_sha256": state.pytest_source_sha256,
        "pytest_version": state.pytest_version,
        "skips": [{"node_id": skip.node_id, "reason": skip.reason} for skip in pending.skips],
        "start_receipt_sha256": state.start_receipt_sha256,
        "start_seed_identity": state.start_seed_identity,
        "subprocess_start_identity": state.subprocess_start_identity,
        "subprocess_environment_sha256": state.subprocess_environment_sha256,
        "validation_run_identity": state.validation_run_identity,
        "validation_version": PYTEST_VALIDATION_VERSION,
    }
    receipt_values["subprocess_completion_identity"] = protocol_hash(
        "pytest_subprocess_completion/v3", receipt_values
    )
    _write_exclusive_bytes(
        state.receipt_path,
        canonical_json_bytes(receipt_values, final_lf=True),
        "completion receipt",
    )


def _validated_authoritative_junit_writer_identity(
    config: object,
    *,
    state: _PluginState,
    junit: _JunitObservation,
) -> str:
    writer = cast(Any, config).pluginmanager.get_plugin(_AUTHORITATIVE_JUNIT_PLUGIN_NAME)
    if (
        writer is None
        or type(writer).__module__ != _PLUGIN_NAME
        or type(writer).__qualname__ != "_AuthoritativeLogXML"
        or getattr(writer, "_rde_junit_descriptor", None) != state.junit_file_descriptor
        or getattr(writer, "_rde_junit_file_identity", None) != state.junit_file_identity
    ):
        raise PytestValidationError("Authoritative pytest JUnit writer identity changed.")
    expected = protocol_hash(
        "pytest_authoritative_junit_writer/v1",
        {
            "file_identity": list(state.junit_file_identity),
            "junit_byte_count": junit.byte_count,
            "junit_sha256": junit.sha256,
            "validation_plugin_source_sha256": state.plugin_source_sha256,
        },
    )
    observed = getattr(writer, "_rde_junit_writer_identity", None)
    if observed != expected:
        raise PytestValidationError("Authoritative pytest JUnit writer receipt is invalid.")
    return expected


pytest_sessionfinish.pytest_impl = {  # type: ignore[attr-defined]
    "hookwrapper": True,
    "optionalhook": False,
    "specname": None,
    "tryfirst": True,
    "trylast": False,
    "wrapper": False,
}


def _windows_creation_flags() -> int:
    if os.name != "nt":
        raise OSError(errno.ENOSYS, "Windows process creation flags are unavailable.")
    creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", None)
    if type(creation_flags) is not int:
        raise OSError(
            errno.ENOSYS,
            "subprocess.CREATE_NEW_PROCESS_GROUP is unavailable on Windows.",
        )
    return creation_flags


def _execute_pytest_validation(
    *,
    validation_run_identity: str,
    issuer_kind: PytestValidationIssuerKind,
    targets: tuple[str, ...],
    timeout_seconds: float,
    execution_root: Path | None,
) -> PytestValidationResult:
    _validate_external_identity(validation_run_identity, "validation run")
    _validate_timeout(timeout_seconds)
    _reserve_validation_run_identity(validation_run_identity)
    identities = _current_validation_identities()
    implementation_root = repository_root().resolve(strict=True)
    pytest_root = (execution_root or implementation_root).resolve(strict=True)
    config_candidate = pytest_root / "pyproject.toml"
    if not config_candidate.is_file() or config_candidate.is_symlink():
        raise PytestValidationError("Authoritative pytest configuration is not a regular file.")
    config_path = config_candidate.resolve(strict=True)
    test_root_candidate = pytest_root / "tests"
    if not test_root_candidate.is_dir() or test_root_candidate.is_symlink():
        raise PytestValidationError("Authoritative pytest test root is not a regular directory.")
    authorized_test_root = test_root_candidate.resolve(strict=True)
    _configuration_boundary_sha256(pytest_root)
    selection: tuple[str, ...]
    if issuer_kind == "production":
        if targets:
            raise PytestValidationError("Production pytest validation cannot accept targets.")
        selection = (str((pytest_root / "tests").resolve(strict=True)),)
    else:
        selection = targets
    if any(
        Path(selected).resolve(strict=True) != authorized_test_root
        and authorized_test_root not in Path(selected).resolve(strict=True).parents
        for selected in selection
    ):
        raise PytestValidationError("Pytest selection escapes the authoritative test root.")
    executable = sys.executable
    if not executable or not Path(executable).is_absolute():
        raise PytestValidationError("sys.executable is not an absolute interpreter path.")
    nonce = secrets.token_hex(32)
    failure_details: list[str] = []
    exit_code: int | None = None
    launcher_exit_code: int | None = None
    process_pid: int | None = None
    process_observer: _AuthoritativeProcessObserver | None = None
    stdout = b""
    stderr = b""
    start_receipt: dict[str, object] | None = None
    cleanup_plugin_pid: int | None = None
    receipt: dict[str, object] | None = None
    junit: _JunitObservation | None = None
    timed_out = False

    with tempfile.TemporaryDirectory(prefix="rde-pytest-validation-") as temporary:
        temporary_path = Path(temporary).resolve(strict=True)
        junit_path = temporary_path / "pytest-junit.xml"
        junit_initial_bytes = secrets.token_bytes(32)
        junit_file_identity = _create_historical_guarded_junit_file(
            junit_path,
            initial_bytes=junit_initial_bytes,
        )
        specification_path = temporary_path / "pytest-execution-specification.json"
        start_receipt_path = temporary_path / "pytest-plugin-start-receipt.json"
        receipt_path = temporary_path / "pytest-plugin-receipt.json"
        command = (
            executable,
            "-P",
            "-m",
            "pytest",
            "-p",
            _PLUGIN_NAME,
            "-c",
            str(config_path),
            f"--rootdir={pytest_root}",
            f"--confcutdir={authorized_test_root}",
            f"--junitxml={junit_path}",
            *selection,
        )
        command_sha256 = protocol_hash("pytest_validation_command/v1", list(command))
        environment = _base_subprocess_environment()
        subprocess_environment_sha256 = _subprocess_environment_sha256(environment)
        specification = _build_execution_specification(
            validation_run_identity=validation_run_identity,
            issuer_kind=issuer_kind,
            implementation_root=implementation_root,
            pytest_root=pytest_root,
            config_path=config_path,
            selection=selection,
            junit_path=junit_path,
            command=command,
            command_sha256=command_sha256,
            subprocess_environment_sha256=subprocess_environment_sha256,
            junit_initial_bytes=junit_initial_bytes,
            junit_file_identity=junit_file_identity,
            identities=identities,
        )
        _write_exclusive_bytes(
            specification_path,
            canonical_json_bytes(_specification_document(specification), final_lf=True),
            "execution specification",
        )
        start_seed_identity = protocol_hash(
            "pytest_subprocess_start_seed/v2",
            {
                "command_sha256": command_sha256,
                "execution_specification_identity": (
                    specification.execution_specification_identity
                ),
                "identities": _identity_values(identities),
                "nonce": nonce,
                "validation_run_identity": validation_run_identity,
            },
        )
        environment.update(
            {
                _ENV_NONCE: nonce,
                _ENV_RUN_IDENTITY: validation_run_identity,
                _ENV_COMMAND_SHA256: command_sha256,
                _ENV_START_SEED_IDENTITY: start_seed_identity,
                _ENV_SPECIFICATION_PATH: str(specification_path),
                _ENV_START_RECEIPT_PATH: str(start_receipt_path),
                _ENV_RECEIPT_PATH: str(receipt_path),
                _ENV_JUNIT_PATH: str(junit_path),
            }
        )
        print(
            f"pytest validation: starting {issuer_kind} execution for {validation_run_identity}",
            flush=True,
        )
        started = time.monotonic()
        try:
            popen_options: dict[str, object] = {
                "cwd": pytest_root,
                "env": environment,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
            }
            if os.name == "nt":
                popen_options["creationflags"] = _windows_creation_flags()
            else:
                popen_options["start_new_session"] = True
            process = subprocess.Popen(  # noqa: S603
                command,
                **cast(dict[str, Any], popen_options),
            )
            process_pid = process.pid
            start_wait_deadline = min(
                started + timeout_seconds,
                started + _START_RECEIPT_WAIT_SECONDS,
            )
            while not start_receipt_path.exists() and time.monotonic() < start_wait_deadline:
                time.sleep(0.01)
            if start_receipt_path.is_file() and not start_receipt_path.is_symlink():
                try:
                    start_receipt = _load_and_validate_start_receipt(
                        receipt_path=start_receipt_path,
                        expected_nonce=nonce,
                        expected_run_identity=validation_run_identity,
                        expected_command=command,
                        expected_start_seed_identity=start_seed_identity,
                        expected_pid=process_pid,
                        specification=specification,
                    )
                    cleanup_plugin_pid = _receipt_int(start_receipt, "pid")
                    process_observer = _open_authoritative_process_observer(
                        launcher_pid=process_pid,
                        start_receipt=start_receipt,
                        specification=specification,
                    )
                except PytestValidationError as error:
                    failure_details.append(str(error))
                    cleanup_plugin_pid = _cleanup_plugin_pid(
                        start_receipt_path,
                        expected_nonce=nonce,
                        expected_launcher_pid=process_pid,
                    )
                    start_receipt = None
            elif process.poll() is None and time.monotonic() >= started + timeout_seconds:
                timed_out = True

            try:
                remaining = max(0.0, started + timeout_seconds - time.monotonic())
                if timed_out or remaining == 0.0:
                    raise subprocess.TimeoutExpired(command, timeout_seconds)
                stdout, stderr = process.communicate(timeout=remaining)
                launcher_exit_code = process.returncode
                exit_code = launcher_exit_code
                if not _wait_for_authoritative_process_end(
                    process,
                    observed_plugin_pid=cleanup_plugin_pid,
                    deadline=started + timeout_seconds,
                    is_alive=_process_observer_liveness_probe(process_observer),
                ):
                    timed_out = True
                    stdout, stderr = _terminate_process_tree(
                        process,
                        observed_plugin_pid=cleanup_plugin_pid,
                    )
                    launcher_exit_code = process.returncode
                    exit_code = launcher_exit_code
                    failure_details.append(
                        "authoritative pytest child outlived its bounded launcher execution"
                    )
            except subprocess.TimeoutExpired:
                timed_out = True
                stdout, stderr = _terminate_process_tree(
                    process,
                    observed_plugin_pid=cleanup_plugin_pid,
                )
                launcher_exit_code = process.returncode
                exit_code = launcher_exit_code
                failure_details.append(
                    f"pytest exceeded the {timeout_seconds:g}-second validation ceiling"
                )
            if process_observer is not None:
                if not timed_out:
                    try:
                        exit_code = _authoritative_process_exit_code(
                            process,
                            process_observer,
                        )
                    except PytestValidationError as error:
                        failure_details.append(str(error))
                        exit_code = None
                if process_observer.retained_handle is not None:
                    try:
                        _windows_close_process_handle(process_observer.retained_handle)
                    except PytestValidationError as error:
                        failure_details.append(str(error))
                        exit_code = None
                    process_observer.retained_handle = None
        except OSError as error:
            failure_details.append(f"pytest could not start: {type(error).__name__}: {error}")

        if start_receipt is None and start_receipt_path.is_file() and not timed_out:
            try:
                start_receipt = _load_and_validate_start_receipt(
                    receipt_path=start_receipt_path,
                    expected_nonce=nonce,
                    expected_run_identity=validation_run_identity,
                    expected_command=command,
                    expected_start_seed_identity=start_seed_identity,
                    expected_pid=process_pid,
                    specification=specification,
                )
                cleanup_plugin_pid = _receipt_int(start_receipt, "pid")
                process_observer = _open_authoritative_process_observer(
                    launcher_pid=cast(int, process_pid),
                    start_receipt=start_receipt,
                    specification=specification,
                )
                exit_code = _authoritative_process_exit_code(
                    process,
                    process_observer,
                )
                if process_observer.retained_handle is not None:
                    _windows_close_process_handle(process_observer.retained_handle)
                    process_observer.retained_handle = None
            except PytestValidationError as error:
                failure_details.append(str(error))
                cleanup_plugin_pid = _cleanup_plugin_pid(
                    start_receipt_path,
                    expected_nonce=nonce,
                    expected_launcher_pid=process_pid,
                )
                start_receipt = None
        if start_receipt is None:
            failure_details.append("pytest plugin did not persist a valid start receipt")

        if receipt_path.is_file() and not receipt_path.is_symlink() and not timed_out:
            try:
                receipt = _load_and_validate_receipt(
                    receipt_path=receipt_path,
                    expected_nonce=nonce,
                    expected_run_identity=validation_run_identity,
                    expected_command=command,
                    expected_command_sha256=command_sha256,
                    expected_start_seed_identity=start_seed_identity,
                    expected_pid=process_pid,
                    expected_start_receipt=start_receipt,
                    specification=specification,
                )
            except PytestValidationError as error:
                failure_details.append(str(error))
        else:
            failure_details.append("pytest plugin did not persist its execution receipt")

        if junit_path.is_file() and not junit_path.is_symlink() and not timed_out:
            try:
                junit = _read_junit_observation(
                    junit_path,
                    pytest_root=pytest_root,
                    expected_file_identity=specification.junit_file_identity,
                )
            except PytestValidationError as error:
                failure_details.append(str(error))
        else:
            failure_details.append("pytest did not persist its JUnit XML output")

        current_identities = _current_validation_identities()
        if current_identities != identities:
            failure_details.append(
                "repository or runtime identity changed during pytest validation"
            )

        if not _specification_sources_are_current(
            specification,
            require_ephemeral_junit=True,
        ):
            failure_details.append("pytest configuration or selected test sources changed")
        if receipt is not None:
            try:
                _reconcile_process_exit_codes(
                    launcher_exit_code=launcher_exit_code,
                    plugin_exit_code=exit_code,
                    receipt_exit_code=_receipt_int(receipt, "exit_code"),
                )
            except PytestValidationError as error:
                failure_details.append(str(error))
                receipt = None
        if receipt is not None and junit is not None:
            receipt_skips = _receipt_skips(receipt)
            receipt_junit = _receipt_junit(receipt)
            collected_node_ids = _receipt_string_tuple(receipt, "collected_node_ids")
            deselected_node_ids = _receipt_string_tuple(receipt, "deselected_node_ids")
            if receipt_junit != _junit_values(junit):
                failure_details.append("pytest plugin and reopened JUnit observations differ")
                receipt = None
            elif tuple((item.node_id, item.reason) for item in receipt_skips) != tuple(
                zip(junit.skipped_node_ids, junit.skipped_reasons, strict=True)
            ):
                failure_details.append(
                    "pytest plugin and reopened JUnit skipped-test identities differ"
                )
                receipt = None
            elif collected_node_ids != junit.node_ids:
                failure_details.append(
                    "pytest collection and reopened JUnit test identities differ"
                )
                receipt = None
            elif len(set(collected_node_ids)) != len(collected_node_ids):
                failure_details.append("pytest collection contains duplicate node IDs")
                receipt = None
            elif len(set(deselected_node_ids)) != len(deselected_node_ids):
                failure_details.append("pytest deselection contains duplicate node IDs")
                receipt = None
        if exit_code not in (None, 0):
            failure_details.append(
                "pytest exited with code "
                f"{exit_code}; stdout_sha256={hashlib.sha256(stdout).hexdigest()}; "
                f"stderr_sha256={hashlib.sha256(stderr).hexdigest()}"
            )

        completed = (
            exit_code == 0
            and receipt is not None
            and junit is not None
            and current_identities == identities
            and _specification_sources_are_current(
                specification,
                require_ephemeral_junit=True,
            )
            and not timed_out
        )
        execution_status: PytestValidationExecutionStatus = "COMPLETED" if completed else "FAILED"
        skipped_records = _receipt_skips(receipt) if receipt is not None else ()
        collected_node_ids = (
            _receipt_string_tuple(receipt, "collected_node_ids") if receipt is not None else ()
        )
        deselected_node_ids = (
            _receipt_string_tuple(receipt, "deselected_node_ids") if receipt is not None else ()
        )
        plugin_identities = (
            _receipt_plugin_identities(receipt, "session_plugin_identities")
            if receipt is not None
            else ()
        )
        conftest_identities = _receipt_conftest_identities(receipt) if receipt is not None else ()
        observation_values: dict[str, object] = {
            "base_interpreter_executable_sha256": (
                specification.base_interpreter_executable_sha256
            ),
            "base_interpreter_path": specification.base_interpreter_path,
            "broader_source_sha256": identities.broader_source_sha256,
            "collected_node_ids": list(collected_node_ids),
            "command": list(command),
            "command_sha256": command_sha256,
            "completed": completed,
            "complete_test_bundle_sha256": identities.complete_test_bundle_sha256,
            "deselected_node_ids": list(deselected_node_ids),
            "design_checkpoint_commit": identities.design_checkpoint_commit,
            "effective_conftest_identities": [list(item) for item in conftest_identities],
            "effective_plugin_identities": [list(item) for item in plugin_identities],
            "errors": 0 if junit is None else junit.errors,
            "execution_specification_identity": (specification.execution_specification_identity),
            "execution_status": execution_status,
            "exit_code": exit_code,
            "failed": 0 if junit is None else junit.failed,
            "failure_details": list(failure_details),
            "implementation_commit": identities.implementation_commit,
            "implementation_diff_sha256": identities.implementation_diff_sha256,
            "implementation_repository_root": str(implementation_root),
            "implementation_tree_sha256": identities.implementation_tree_sha256,
            "interpreter_executable_sha256": (specification.interpreter_executable_sha256),
            "interpreter_identity_sha256": identities.interpreter_identity_sha256,
            "interpreter_path": specification.interpreter_path,
            "issuer_kind": issuer_kind,
            "junit_case_identities": ([] if junit is None else list(junit.case_identities)),
            "junit_xml_byte_count": 0 if junit is None else junit.byte_count,
            "junit_xml_path": str(junit_path),
            "junit_xml_sha256": None if junit is None else junit.sha256,
            "passed": 0 if junit is None else junit.passed,
            "platform_identity_sha256": identities.platform_identity_sha256,
            "pluggy_source_sha256": specification.pluggy_source_sha256,
            "pluggy_version": specification.pluggy_version,
            "pytest_config_path": str(config_path),
            "pytest_root_directory": str(pytest_root),
            "pytest_source_sha256": specification.pytest_source_sha256,
            "pytest_test_selection": list(selection),
            "pytest_version": specification.pytest_version,
            "pytest_working_directory": str(pytest_root),
            "runtime_seconds": None if junit is None else junit.runtime_seconds,
            "skipped": 0 if junit is None else junit.skipped,
            "skipped_node_ids": [item.node_id for item in skipped_records],
            "skipped_reasons": [item.reason for item in skipped_records],
            "source_design_sha256": identities.source_design_sha256,
            "subprocess_completion_identity": (
                None if receipt is None else _receipt_str(receipt, "subprocess_completion_identity")
            ),
            "subprocess_environment_sha256": (specification.subprocess_environment_sha256),
            "subprocess_start_identity": (
                None
                if start_receipt is None
                else _receipt_str(start_receipt, "subprocess_start_identity")
            ),
            "total": 0 if junit is None else junit.total,
            "uv_lock_sha256": identities.uv_lock_sha256,
            "validation_plugin_source_sha256": (specification.validation_plugin_source_sha256),
            "validation_run_identity": validation_run_identity,
            "validation_version": PYTEST_VALIDATION_VERSION,
        }
        result_identity = protocol_hash("pytest_validation_result/v1", observation_values)
        observation = PytestValidationObservation(
            validation_version=PYTEST_VALIDATION_VERSION,
            issuer_kind=issuer_kind,
            execution_status=execution_status,
            validation_run_identity=validation_run_identity,
            execution_specification_identity=(specification.execution_specification_identity),
            implementation_repository_root=str(implementation_root),
            pytest_root_directory=str(pytest_root),
            pytest_config_path=str(config_path),
            pytest_working_directory=str(pytest_root),
            pytest_test_selection=selection,
            implementation_commit=identities.implementation_commit,
            design_checkpoint_commit=identities.design_checkpoint_commit,
            source_design_sha256=identities.source_design_sha256,
            implementation_tree_sha256=identities.implementation_tree_sha256,
            implementation_diff_sha256=identities.implementation_diff_sha256,
            broader_source_sha256=identities.broader_source_sha256,
            complete_test_bundle_sha256=identities.complete_test_bundle_sha256,
            command=command,
            command_sha256=command_sha256,
            interpreter_path=specification.interpreter_path,
            interpreter_executable_sha256=(specification.interpreter_executable_sha256),
            base_interpreter_path=specification.base_interpreter_path,
            base_interpreter_executable_sha256=(specification.base_interpreter_executable_sha256),
            uv_lock_sha256=identities.uv_lock_sha256,
            interpreter_identity_sha256=identities.interpreter_identity_sha256,
            platform_identity_sha256=identities.platform_identity_sha256,
            pytest_version=specification.pytest_version,
            pytest_source_sha256=specification.pytest_source_sha256,
            pluggy_version=specification.pluggy_version,
            pluggy_source_sha256=specification.pluggy_source_sha256,
            validation_plugin_source_sha256=(specification.validation_plugin_source_sha256),
            effective_plugin_identities=plugin_identities,
            effective_conftest_identities=conftest_identities,
            subprocess_start_identity=(
                None
                if start_receipt is None
                else _receipt_str(start_receipt, "subprocess_start_identity")
            ),
            subprocess_completion_identity=(
                None if receipt is None else _receipt_str(receipt, "subprocess_completion_identity")
            ),
            subprocess_environment_sha256=(specification.subprocess_environment_sha256),
            junit_xml_path=str(junit_path),
            junit_xml_sha256=None if junit is None else junit.sha256,
            junit_xml_byte_count=0 if junit is None else junit.byte_count,
            total=0 if junit is None else junit.total,
            passed=0 if junit is None else junit.passed,
            skipped=0 if junit is None else junit.skipped,
            failed=0 if junit is None else junit.failed,
            errors=0 if junit is None else junit.errors,
            runtime_seconds=None if junit is None else junit.runtime_seconds,
            collected_node_ids=collected_node_ids,
            deselected_node_ids=deselected_node_ids,
            junit_case_identities=() if junit is None else junit.case_identities,
            skipped_node_ids=tuple(item.node_id for item in skipped_records),
            skipped_reasons=tuple(item.reason for item in skipped_records),
            exit_code=exit_code,
            completed=completed,
            failure_details=tuple(failure_details),
            result_identity=result_identity,
        )
        result = PytestValidationResult(_RESULT_CONSTRUCTION_KEY)
        record = _IssuedPytestValidationResult(
            result=result,
            observation=observation,
            observation_fingerprint=_observation_fingerprint(observation),
            specification=specification,
            specification_fingerprint=_specification_fingerprint(specification),
            junit_xml_bytes=b"" if junit is None else junit.exact_bytes,
            evidence_bundle_identity=None,
            owner_claim=None,
            active=True,
        )
        with _RESULT_LOCK:
            _ISSUED_RESULTS[id(result)] = record
        print(
            f"pytest validation: {execution_status.lower()} {issuer_kind} execution "
            f"with exit code {exit_code}",
            flush=True,
        )
        return result


def _reserve_validation_run_identity(validation_run_identity: str) -> None:
    with _RESULT_LOCK:
        if validation_run_identity in _USED_VALIDATION_RUN_IDENTITIES:
            raise PytestValidationError("Validation-run identity already has pytest evidence.")
        _USED_VALIDATION_RUN_IDENTITIES.add(validation_run_identity)


def _validate_timeout(timeout_seconds: float) -> None:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not 0.0 < float(timeout_seconds) <= MAX_PYTEST_TIMEOUT_SECONDS
    ):
        raise PytestValidationError(
            f"Pytest timeout must be positive and at most {MAX_PYTEST_TIMEOUT_SECONDS:g} seconds."
        )


def _load_and_validate_start_receipt(
    *,
    receipt_path: Path,
    expected_nonce: str,
    expected_run_identity: str,
    expected_command: tuple[str, ...],
    expected_start_seed_identity: str,
    expected_pid: int | None,
    specification: _HistoricalPytestExecutionSpecification,
) -> dict[str, object]:
    receipt = _load_canonical_json_object(receipt_path, "pytest plugin start receipt")
    expected_keys = {
        "argv_tail",
        "base_interpreter_executable_sha256",
        "base_interpreter_path",
        "command_sha256",
        "controlled_environment",
        "execution_specification_identity",
        "interpreter_executable_sha256",
        "interpreter_path",
        "junit_file_identity",
        "nonce",
        "observed_configuration",
        "parent_pid",
        "pid",
        "plugin_identities",
        "plugin_lifecycle_events",
        "plugin_lifecycle_start_identity",
        "plugin_source_sha256",
        "pluggy_source_sha256",
        "pluggy_version",
        "pytest_source_sha256",
        "pytest_version",
        "start_seed_identity",
        "subprocess_environment_sha256",
        "subprocess_start_identity",
        "validation_run_identity",
        "validation_version",
    }
    if set(receipt) != expected_keys:
        raise PytestValidationError("Pytest plugin receipt fields differ from the contract.")
    expected_argv_tail = _pytest_argument_tail(expected_command)
    argv_tail = _receipt_string_tuple(receipt, "argv_tail")
    if argv_tail != expected_argv_tail:
        raise PytestValidationError("Pytest plugin observed another command line.")
    if (
        _receipt_str(receipt, "nonce") != expected_nonce
        or _receipt_str(receipt, "validation_run_identity") != expected_run_identity
        or _receipt_str(receipt, "command_sha256") != specification.command_sha256
        or _receipt_str(receipt, "start_seed_identity") != expected_start_seed_identity
        or _receipt_str(receipt, "validation_version") != PYTEST_VALIDATION_VERSION
        or _receipt_str(receipt, "execution_specification_identity")
        != specification.execution_specification_identity
        or _receipt_str(receipt, "subprocess_environment_sha256")
        != specification.subprocess_environment_sha256
    ):
        raise PytestValidationError("Pytest plugin receipt does not belong to this subprocess.")
    receipt_pid = _receipt_int(receipt, "pid")
    receipt_parent_pid = _receipt_int(receipt, "parent_pid")
    _validate_process_topology(
        expected_pid=expected_pid,
        receipt_pid=receipt_pid,
        receipt_parent_pid=receipt_parent_pid,
        issuer_pid=os.getpid(),
    )
    expected_controlled_environment = _expected_runtime_controlled_environment(
        specification.pytest_version
    )
    if receipt.get("controlled_environment") != expected_controlled_environment:
        raise PytestValidationError("Pytest subprocess control environment differs.")
    _validate_runtime_receipt_identities(receipt, specification)
    if _receipt_file_identity(receipt, "junit_file_identity") != specification.junit_file_identity:
        raise PytestValidationError("Pytest JUnit file identity differs from its specification.")
    observed_configuration = _receipt_observed_configuration(receipt)
    _validate_observed_configuration(observed_configuration, specification)
    plugin_identities = _receipt_plugin_identities(receipt, "plugin_identities")
    _validate_effective_plugin_identities(plugin_identities, specification)
    if plugin_identities != specification.expected_initial_plugin_identities:
        raise PytestValidationError(
            "Effective pytest plugin set differs from the exact configured lifecycle."
        )
    plugin_lifecycle_events = _receipt_plugin_lifecycle_events(receipt, "plugin_lifecycle_events")
    _validate_plugin_lifecycle_trace(
        plugin_lifecycle_events,
        specification,
        completed_phase=False,
    )
    expected_plugin_lifecycle_start_identity = protocol_hash(
        "pytest_plugin_lifecycle_start/v1",
        {
            "events": [_plugin_lifecycle_event_values(item) for item in plugin_lifecycle_events],
            "initial_plugin_identities": [list(item) for item in plugin_identities],
        },
    )
    if (
        _receipt_str(receipt, "plugin_lifecycle_start_identity")
        != expected_plugin_lifecycle_start_identity
    ):
        raise PytestValidationError("Pytest plugin lifecycle start identity is invalid.")
    expected_start = protocol_hash(
        "pytest_subprocess_start/v2",
        {
            "argv_tail": list(argv_tail),
            "base_interpreter_executable_sha256": (
                specification.base_interpreter_executable_sha256
            ),
            "base_interpreter_path": specification.base_interpreter_path,
            "command_sha256": specification.command_sha256,
            "controlled_environment": expected_controlled_environment,
            "execution_specification_identity": (specification.execution_specification_identity),
            "interpreter_executable_sha256": (specification.interpreter_executable_sha256),
            "interpreter_path": specification.interpreter_path,
            "junit_file_identity": list(specification.junit_file_identity),
            "nonce": expected_nonce,
            "observed_configuration": _observed_configuration_values(observed_configuration),
            "parent_pid": receipt_parent_pid,
            "pid": receipt_pid,
            "plugin_identities": [list(item) for item in plugin_identities],
            "plugin_lifecycle_events": [
                _plugin_lifecycle_event_values(item) for item in plugin_lifecycle_events
            ],
            "plugin_lifecycle_start_identity": (expected_plugin_lifecycle_start_identity),
            "plugin_source_sha256": specification.validation_plugin_source_sha256,
            "pluggy_source_sha256": specification.pluggy_source_sha256,
            "pluggy_version": specification.pluggy_version,
            "pytest_source_sha256": specification.pytest_source_sha256,
            "pytest_version": specification.pytest_version,
            "start_seed_identity": expected_start_seed_identity,
            "subprocess_environment_sha256": (specification.subprocess_environment_sha256),
            "validation_run_identity": expected_run_identity,
            "validation_version": PYTEST_VALIDATION_VERSION,
        },
    )
    if _receipt_str(receipt, "subprocess_start_identity") != expected_start:
        raise PytestValidationError("Pytest subprocess start identity does not reconcile.")
    return receipt


def _validate_process_topology(
    *,
    expected_pid: int | None,
    receipt_pid: int,
    receipt_parent_pid: int,
    issuer_pid: int,
) -> None:
    direct_child = receipt_pid == expected_pid and receipt_parent_pid == issuer_pid
    launcher_child = (
        receipt_parent_pid == expected_pid
        and receipt_pid != expected_pid
        and receipt_pid != issuer_pid
    )
    if (
        expected_pid is None
        or expected_pid <= 0
        or receipt_pid <= 0
        or receipt_parent_pid <= 0
        or issuer_pid <= 0
        or not (direct_child or launcher_child)
    ):
        raise PytestValidationError("Pytest plugin process chain differs from the issuer.")


def _cleanup_plugin_pid(
    receipt_path: Path,
    *,
    expected_nonce: str,
    expected_launcher_pid: int | None,
) -> int | None:
    try:
        receipt = _load_canonical_json_object(receipt_path, "pytest cleanup start receipt")
        if _receipt_str(receipt, "nonce") != expected_nonce:
            return None
        receipt_pid = _receipt_int(receipt, "pid")
        _validate_process_topology(
            expected_pid=expected_launcher_pid,
            receipt_pid=receipt_pid,
            receipt_parent_pid=_receipt_int(receipt, "parent_pid"),
            issuer_pid=os.getpid(),
        )
        return receipt_pid
    except PytestValidationError:
        return None


def _open_authoritative_process_observer(
    *,
    launcher_pid: int,
    start_receipt: dict[str, object],
    specification: _HistoricalPytestExecutionSpecification,
) -> _AuthoritativeProcessObserver:
    plugin_pid = _receipt_int(start_receipt, "pid")
    if plugin_pid == launcher_pid:
        return _AuthoritativeProcessObserver(
            launcher_pid=launcher_pid,
            plugin_pid=plugin_pid,
            topology="direct",
            retained_handle=None,
            os_image_path=specification.interpreter_path,
            os_image_sha256=specification.interpreter_executable_sha256,
        )
    if os.name != "nt":
        raise PytestValidationError(
            "Launcher-child pytest topology lacks a retained OS exit-code capability."
        )
    handle = _windows_open_process_handle(plugin_pid)
    try:
        image_path = str(Path(_windows_process_image_path(handle)).resolve(strict=True))
        image_sha256 = hashlib.sha256(Path(image_path).read_bytes()).hexdigest()
        if (
            not os.path.samefile(image_path, specification.base_interpreter_path)
            or image_sha256 != specification.base_interpreter_executable_sha256
        ):
            raise PytestValidationError(
                "Authoritative pytest child OS image differs from the base interpreter."
            )
        return _AuthoritativeProcessObserver(
            launcher_pid=launcher_pid,
            plugin_pid=plugin_pid,
            topology="launcher-child",
            retained_handle=handle,
            os_image_path=image_path,
            os_image_sha256=image_sha256,
        )
    except BaseException:
        _windows_close_process_handle(handle)
        raise


def _windows_open_process_handle(pid: int) -> int:
    _, kernel32, _ = _windows_kernel32()
    handle = kernel32.OpenProcess(0x00101000, False, pid)
    if not handle:
        raise PytestValidationError(
            "Authoritative pytest child process handle could not be retained."
        )
    return cast(int, handle)


def _windows_process_image_path(handle: int) -> str:
    ctypes, kernel32, wintypes = _windows_kernel32()
    capacity = 32_768
    buffer = cast(Any, ctypes).create_unicode_buffer(capacity)
    size = cast(Any, wintypes).DWORD(capacity)
    if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, cast(Any, ctypes).byref(size)):
        raise PytestValidationError(
            "Authoritative pytest child OS image path could not be queried."
        )
    value = cast(str, buffer.value)
    if not value or len(value) != cast(int, size.value):
        raise PytestValidationError("Authoritative pytest child OS image path is malformed.")
    return value


def _windows_process_exit_code(handle: int) -> int:
    ctypes, kernel32, wintypes = _windows_kernel32()
    exit_code = cast(Any, wintypes).DWORD()
    if not kernel32.GetExitCodeProcess(handle, cast(Any, ctypes).byref(exit_code)):
        raise PytestValidationError("Authoritative pytest child OS exit code could not be queried.")
    return cast(int, exit_code.value)


def _windows_close_process_handle(handle: int) -> None:
    _, kernel32, _ = _windows_kernel32()
    if not kernel32.CloseHandle(handle):
        raise PytestValidationError(
            "Authoritative pytest child process handle could not be closed."
        )


class _WindowsFunction(Protocol):
    argtypes: object
    restype: object

    def __call__(self, *args: object) -> object: ...


class _WindowsKernel32(Protocol):
    OpenProcess: _WindowsFunction
    QueryFullProcessImageNameW: _WindowsFunction
    GetExitCodeProcess: _WindowsFunction
    CloseHandle: _WindowsFunction


class _WinDLLFactory(Protocol):
    def __call__(self, name: str, *, use_last_error: bool) -> _WindowsKernel32: ...


def _windows_kernel32() -> tuple[ModuleType, _WindowsKernel32, ModuleType]:
    if os.name != "nt":
        raise PytestValidationError("Windows process APIs are unavailable on this platform.")
    ctypes = importlib.import_module("ctypes")
    wintypes = importlib.import_module("ctypes.wintypes")
    win_dll = getattr(ctypes, "WinDLL", None)
    if not callable(win_dll):
        raise PytestValidationError("ctypes.WinDLL is unavailable on Windows.")
    kernel32 = cast(_WinDLLFactory, win_dll)("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [
        cast(Any, wintypes).DWORD,
        cast(Any, wintypes).BOOL,
        cast(Any, wintypes).DWORD,
    ]
    kernel32.OpenProcess.restype = cast(Any, wintypes).HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        cast(Any, wintypes).HANDLE,
        cast(Any, wintypes).DWORD,
        cast(Any, wintypes).LPWSTR,
        cast(Any, ctypes).POINTER(cast(Any, wintypes).DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = cast(Any, wintypes).BOOL
    kernel32.GetExitCodeProcess.argtypes = [
        cast(Any, wintypes).HANDLE,
        cast(Any, ctypes).POINTER(cast(Any, wintypes).DWORD),
    ]
    kernel32.GetExitCodeProcess.restype = cast(Any, wintypes).BOOL
    kernel32.CloseHandle.argtypes = [cast(Any, wintypes).HANDLE]
    kernel32.CloseHandle.restype = cast(Any, wintypes).BOOL
    return ctypes, kernel32, wintypes


def _windows_last_error(ctypes_module: ModuleType) -> int:
    if os.name != "nt":
        raise PytestValidationError("Windows process APIs are unavailable on this platform.")
    get_last_error = getattr(ctypes_module, "get_last_error", None)
    if not callable(get_last_error):
        raise PytestValidationError("ctypes.get_last_error is unavailable on Windows.")
    return cast(Callable[[], int], get_last_error)()


def _authoritative_process_exit_code(
    process: subprocess.Popen[bytes],
    observer: _AuthoritativeProcessObserver,
) -> int:
    if observer.topology == "direct":
        if process.returncode is None:
            raise PytestValidationError("Direct pytest process has no OS exit code.")
        return process.returncode
    if observer.retained_handle is None:
        raise PytestValidationError("Pytest child process handle is missing.")
    exit_code = _windows_process_exit_code(observer.retained_handle)
    if exit_code == 259:
        raise PytestValidationError("Authoritative pytest child is still active.")
    return exit_code


def _process_observer_liveness_probe(
    observer: _AuthoritativeProcessObserver | None,
) -> Callable[[int], bool]:
    if observer is None or observer.retained_handle is None:
        return _process_is_alive

    def retained_handle_is_alive(pid: int) -> bool:
        if pid != observer.plugin_pid:
            raise PytestValidationError("Pytest liveness probe received another process id.")
        return _windows_process_exit_code(cast(int, observer.retained_handle)) == 259

    return retained_handle_is_alive


def _reconcile_process_exit_codes(
    *,
    launcher_exit_code: int | None,
    plugin_exit_code: int | None,
    receipt_exit_code: int,
) -> None:
    if (
        launcher_exit_code is None
        or plugin_exit_code is None
        or launcher_exit_code != plugin_exit_code
        or plugin_exit_code != receipt_exit_code
    ):
        raise PytestValidationError(
            "Pytest launcher, authoritative child, and receipt exit codes differ."
        )


def _load_and_validate_receipt(
    *,
    receipt_path: Path,
    expected_nonce: str,
    expected_run_identity: str,
    expected_command: tuple[str, ...],
    expected_command_sha256: str,
    expected_start_seed_identity: str,
    expected_pid: int | None,
    expected_start_receipt: dict[str, object] | None,
    specification: _HistoricalPytestExecutionSpecification,
) -> dict[str, object]:
    if expected_start_receipt is None:
        raise PytestValidationError("Pytest completion receipt lacks a valid start receipt.")
    receipt = _load_canonical_json_object(receipt_path, "pytest plugin completion receipt")
    expected_keys = {
        "argv_tail",
        "base_interpreter_executable_sha256",
        "base_interpreter_path",
        "collected_node_ids",
        "command_sha256",
        "conftest_identities",
        "controlled_environment",
        "deselected_node_ids",
        "execution_specification_identity",
        "exit_code",
        "failure_details",
        "final_plugin_identities",
        "initial_plugin_identities",
        "interpreter_executable_sha256",
        "interpreter_path",
        "junit",
        "junit_file_identity",
        "junit_writer_identity",
        "nonce",
        "observed_configuration",
        "parent_pid",
        "pid",
        "plugin_lifecycle_completion_identity",
        "plugin_lifecycle_events",
        "plugin_lifecycle_start_identity",
        "plugin_source_sha256",
        "pluggy_source_sha256",
        "pluggy_version",
        "pytest_source_sha256",
        "pytest_version",
        "session_plugin_identities",
        "skips",
        "start_receipt_sha256",
        "start_seed_identity",
        "subprocess_completion_identity",
        "subprocess_environment_sha256",
        "subprocess_start_identity",
        "validation_run_identity",
        "validation_version",
    }
    if set(receipt) != expected_keys:
        raise PytestValidationError("Pytest plugin completion receipt fields differ.")
    expected_argv_tail = _pytest_argument_tail(expected_command)
    if _receipt_string_tuple(receipt, "argv_tail") != expected_argv_tail:
        raise PytestValidationError("Pytest plugin observed another command line.")
    if (
        _receipt_str(receipt, "nonce") != expected_nonce
        or _receipt_str(receipt, "validation_run_identity") != expected_run_identity
        or _receipt_str(receipt, "command_sha256") != expected_command_sha256
        or _receipt_str(receipt, "start_seed_identity") != expected_start_seed_identity
        or _receipt_str(receipt, "validation_version") != PYTEST_VALIDATION_VERSION
        or _receipt_str(receipt, "execution_specification_identity")
        != specification.execution_specification_identity
        or _receipt_str(receipt, "subprocess_environment_sha256")
        != specification.subprocess_environment_sha256
    ):
        raise PytestValidationError("Pytest completion receipt belongs to another execution.")
    receipt_pid = _receipt_int(receipt, "pid")
    receipt_parent_pid = _receipt_int(receipt, "parent_pid")
    if (
        expected_pid is None
        or receipt_pid != _receipt_int(expected_start_receipt, "pid")
        or receipt_parent_pid != _receipt_int(expected_start_receipt, "parent_pid")
        or expected_pid not in (receipt_pid, receipt_parent_pid)
    ):
        raise PytestValidationError("Pytest completion process chain differs from its start.")
    expected_start_sha256 = hashlib.sha256(
        canonical_json_bytes(expected_start_receipt, final_lf=True)
    ).hexdigest()
    if _receipt_str(receipt, "start_receipt_sha256") != expected_start_sha256:
        raise PytestValidationError("Pytest completion receipt does not bind its start receipt.")
    if _receipt_str(receipt, "subprocess_start_identity") != _receipt_str(
        expected_start_receipt, "subprocess_start_identity"
    ):
        raise PytestValidationError("Pytest completion receipt changed its start identity.")
    if receipt.get("controlled_environment") != _expected_runtime_controlled_environment(
        specification.pytest_version
    ):
        raise PytestValidationError("Pytest subprocess control environment differs.")
    _validate_runtime_receipt_identities(receipt, specification)
    if _receipt_file_identity(receipt, "junit_file_identity") != specification.junit_file_identity:
        raise PytestValidationError("Pytest completion changed the JUnit file identity.")
    observed_configuration = _receipt_observed_configuration(receipt)
    _validate_observed_configuration(observed_configuration, specification)
    initial_plugin_identities = _receipt_plugin_identities(receipt, "initial_plugin_identities")
    session_plugin_identities = _receipt_plugin_identities(receipt, "session_plugin_identities")
    final_plugin_identities = _receipt_plugin_identities(receipt, "final_plugin_identities")
    start_plugin_identities = _receipt_plugin_identities(
        expected_start_receipt, "plugin_identities"
    )
    if initial_plugin_identities != start_plugin_identities:
        raise PytestValidationError("Pytest completion receipt changed its initial plugin set.")
    _validate_plugin_identity_transition(
        initial_plugin_identities,
        session_plugin_identities,
        final_plugin_identities,
        specification,
    )
    start_plugin_lifecycle_events = _receipt_plugin_lifecycle_events(
        expected_start_receipt, "plugin_lifecycle_events"
    )
    plugin_lifecycle_events = _receipt_plugin_lifecycle_events(receipt, "plugin_lifecycle_events")
    if (
        plugin_lifecycle_events[: len(start_plugin_lifecycle_events)]
        != start_plugin_lifecycle_events
    ):
        raise PytestValidationError("Pytest completion lifecycle trace changed its start prefix.")
    _validate_plugin_lifecycle_trace(
        plugin_lifecycle_events,
        specification,
        completed_phase=True,
    )
    plugin_lifecycle_start_identity = _receipt_str(
        expected_start_receipt, "plugin_lifecycle_start_identity"
    )
    if _receipt_str(receipt, "plugin_lifecycle_start_identity") != (
        plugin_lifecycle_start_identity
    ):
        raise PytestValidationError("Pytest completion changed its lifecycle start identity.")
    expected_plugin_lifecycle_completion_identity = protocol_hash(
        "pytest_plugin_lifecycle_completion/v2",
        {
            "events": [_plugin_lifecycle_event_values(item) for item in plugin_lifecycle_events],
            "final_plugin_identities": [list(item) for item in final_plugin_identities],
            "session_plugin_identities": [list(item) for item in session_plugin_identities],
            "start_identity": plugin_lifecycle_start_identity,
        },
    )
    if (
        _receipt_str(receipt, "plugin_lifecycle_completion_identity")
        != expected_plugin_lifecycle_completion_identity
    ):
        raise PytestValidationError("Pytest plugin lifecycle completion identity is invalid.")
    conftest_identities = _receipt_conftest_identities(receipt)
    if conftest_identities != specification.expected_conftest_identities:
        raise PytestValidationError("Effective pytest conftest identities differ from selection.")
    collected = _receipt_string_tuple(receipt, "collected_node_ids")
    deselected = _receipt_string_tuple(receipt, "deselected_node_ids")
    if (
        not collected
        or len(set(collected)) != len(collected)
        or len(set(deselected)) != len(deselected)
        or set(collected).intersection(deselected)
    ):
        raise PytestValidationError("Pytest collection/deselection identities are invalid.")
    if deselected:
        raise PytestValidationError("Authoritative pytest execution deselected tests.")
    _receipt_skips(receipt)
    receipt_junit = _receipt_junit(receipt)
    expected_writer_identity = protocol_hash(
        "pytest_authoritative_junit_writer/v1",
        {
            "file_identity": list(specification.junit_file_identity),
            "junit_byte_count": receipt_junit["byte_count"],
            "junit_sha256": receipt_junit["sha256"],
            "validation_plugin_source_sha256": (specification.validation_plugin_source_sha256),
        },
    )
    if _receipt_str(receipt, "junit_writer_identity") != expected_writer_identity:
        raise PytestValidationError("Pytest authoritative JUnit writer identity is invalid.")
    failure_details = receipt.get("failure_details")
    if not isinstance(failure_details, list) or not all(
        isinstance(item, str) for item in failure_details
    ):
        raise PytestValidationError("Pytest completion failure details are malformed.")
    if failure_details:
        raise PytestValidationError(
            "Pytest terminal receipt reported failure: " + "; ".join(failure_details)
        )
    values_without_completion = {
        key: value for key, value in receipt.items() if key != "subprocess_completion_identity"
    }
    expected_completion = protocol_hash(
        "pytest_subprocess_completion/v3", values_without_completion
    )
    if _receipt_str(receipt, "subprocess_completion_identity") != expected_completion:
        raise PytestValidationError("Pytest subprocess completion identity does not reconcile.")
    return receipt


def _read_guarded_junit_bytes(
    path: Path,
    *,
    expected_file_identity: FileIdentity | None,
    open_file_descriptor: int | None,
) -> bytes:
    if expected_file_identity is None:
        if open_file_descriptor is not None:
            raise PytestValidationError("JUnit descriptor lacks an expected file identity.")
        return path.read_bytes()
    if path.is_symlink():
        raise PytestValidationError("Pytest JUnit output was replaced by a symbolic link.")
    flags = (
        os.O_RDONLY
        | cast(int, getattr(os, "O_BINARY", 0))
        | cast(int, getattr(os, "O_NOFOLLOW", 0))
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        before_descriptor = os.fstat(descriptor)
        before_path = path.stat(follow_symlinks=False)
        if (
            _regular_single_link_file_identity(before_descriptor, "reopened JUnit descriptor")
            != expected_file_identity
            or _regular_single_link_file_identity(before_path, "persisted JUnit path")
            != expected_file_identity
        ):
            raise PytestValidationError("Persisted JUnit file identity changed.")
        path_bytes = _read_file_descriptor(descriptor)
        after_descriptor = os.fstat(descriptor)
        after_path = path.stat(follow_symlinks=False)
        if (
            _regular_single_link_file_identity(after_descriptor, "reopened JUnit descriptor")
            != expected_file_identity
            or _regular_single_link_file_identity(after_path, "persisted JUnit path")
            != expected_file_identity
            or before_descriptor.st_size != after_descriptor.st_size
            or before_descriptor.st_mtime_ns != after_descriptor.st_mtime_ns
        ):
            raise PytestValidationError("Persisted JUnit changed while it was reopened.")
        if open_file_descriptor is not None:
            descriptor_status = os.fstat(open_file_descriptor)
            if (
                _regular_single_link_file_identity(descriptor_status, "bound JUnit descriptor")
                != expected_file_identity
                or _read_file_descriptor(open_file_descriptor) != path_bytes
            ):
                raise PytestValidationError(
                    "Persisted JUnit differs from the authoritative writer descriptor."
                )
        return path_bytes
    except OSError as error:
        raise PytestValidationError("Persisted JUnit could not be securely reopened.") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_junit_observation(
    path: Path,
    *,
    pytest_root: Path,
    expected_file_identity: FileIdentity | None = None,
    open_file_descriptor: int | None = None,
) -> _JunitObservation:
    exact_bytes = _read_guarded_junit_bytes(
        path,
        expected_file_identity=expected_file_identity,
        open_file_descriptor=open_file_descriptor,
    )
    if not exact_bytes:
        raise PytestValidationError("Pytest JUnit XML is empty.")
    try:
        root = ElementTree.fromstring(exact_bytes)
    except ElementTree.ParseError as error:
        raise PytestValidationError("Pytest JUnit XML is malformed.") from error
    suites: tuple[ElementTree.Element, ...]
    if root.tag == "testsuite":
        suites = (root,)
    elif root.tag == "testsuites":
        suites = tuple(child for child in root if child.tag == "testsuite")
    else:
        raise PytestValidationError("Pytest JUnit XML has an unexpected root element.")
    if not suites:
        raise PytestValidationError("Pytest JUnit XML contains no test suite.")
    total = 0
    skipped = 0
    failed = 0
    errors = 0
    runtimes: list[Decimal] = []
    runtime_texts: list[str] = []
    case_identities: list[str] = []
    node_ids: list[str] = []
    skipped_node_ids: list[str] = []
    skipped_reasons: list[str] = []
    for suite in suites:
        suite_total = _xml_nonnegative_int(suite.attrib, "tests")
        suite_skipped = _xml_nonnegative_int(suite.attrib, "skipped")
        suite_failed = _xml_nonnegative_int(suite.attrib, "failures")
        suite_errors = _xml_nonnegative_int(suite.attrib, "errors")
        test_cases = tuple(suite.iter("testcase"))
        actual_skipped = sum(1 for case in test_cases if case.find("skipped") is not None)
        actual_failed = sum(1 for case in test_cases if case.find("failure") is not None)
        actual_errors = sum(1 for case in test_cases if case.find("error") is not None)
        for case in test_cases:
            node_id = _junit_testcase_node_id(case, pytest_root=pytest_root)
            node_ids.append(node_id)
            children = [
                {
                    "attributes": dict(sorted(child.attrib.items())),
                    "tag": child.tag,
                    "text": child.text,
                }
                for child in case
            ]
            case_identities.append(
                protocol_hash(
                    "pytest_junit_case/v1",
                    {
                        "attributes": dict(sorted(case.attrib.items())),
                        "children": children,
                        "index": len(case_identities),
                    },
                )
            )
            skipped_element = case.find("skipped")
            if skipped_element is not None:
                message = skipped_element.attrib.get("message")
                if message is None:
                    raise PytestValidationError(
                        "Pytest JUnit skipped testcase omits its exact reason."
                    )
                skipped_node_ids.append(node_id)
                skipped_reasons.append(f"Skipped: {message}")
        if (
            suite_total != len(test_cases)
            or suite_skipped != actual_skipped
            or suite_failed != actual_failed
            or suite_errors != actual_errors
            or suite_skipped + suite_failed + suite_errors > suite_total
        ):
            raise PytestValidationError("Pytest JUnit XML counts do not reconcile.")
        runtime_text = suite.attrib.get("time")
        if runtime_text is None:
            raise PytestValidationError("Pytest JUnit XML omits suite runtime.")
        try:
            runtime = Decimal(runtime_text)
        except InvalidOperation as error:
            raise PytestValidationError("Pytest JUnit XML runtime is not decimal.") from error
        if not runtime.is_finite() or runtime < 0:
            raise PytestValidationError("Pytest JUnit XML runtime is not finite and nonnegative.")
        total += suite_total
        skipped += suite_skipped
        failed += suite_failed
        errors += suite_errors
        runtimes.append(runtime)
        runtime_texts.append(runtime_text)
    if root.tag == "testsuites":
        for attribute, observed in (
            ("tests", total),
            ("skipped", skipped),
            ("failures", failed),
            ("errors", errors),
        ):
            if (
                attribute in root.attrib
                and _xml_nonnegative_int(root.attrib, attribute) != observed
            ):
                raise PytestValidationError("Pytest JUnit XML root counts do not reconcile.")
    runtime_seconds = (
        runtime_texts[0] if len(runtime_texts) == 1 else format(sum(runtimes, Decimal(0)), "f")
    )
    if (
        len(node_ids) != total
        or len(set(node_ids)) != len(node_ids)
        or len(skipped_node_ids) != skipped
        or len(set(skipped_node_ids)) != len(skipped_node_ids)
    ):
        raise PytestValidationError("Pytest JUnit testcase identities do not reconcile.")
    return _JunitObservation(
        exact_bytes=exact_bytes,
        sha256=hashlib.sha256(exact_bytes).hexdigest(),
        byte_count=len(exact_bytes),
        total=total,
        passed=total - skipped - failed - errors,
        skipped=skipped,
        failed=failed,
        errors=errors,
        runtime_seconds=runtime_seconds,
        case_identities=tuple(case_identities),
        node_ids=tuple(node_ids),
        skipped_node_ids=tuple(skipped_node_ids),
        skipped_reasons=tuple(skipped_reasons),
    )


def _junit_testcase_node_id(
    testcase: ElementTree.Element,
    *,
    pytest_root: Path,
) -> str:
    classname = testcase.attrib.get("classname")
    name = testcase.attrib.get("name")
    if (
        classname is None
        or not classname
        or name is None
        or not name
        or any(not part for part in classname.split("."))
    ):
        raise PytestValidationError("Pytest JUnit testcase identity is malformed.")
    root = pytest_root.resolve(strict=True)
    test_root = (root / "tests").resolve(strict=True)
    parts = classname.split(".")
    candidates: list[tuple[Path, tuple[str, ...]]] = []
    for module_part_count in range(1, len(parts) + 1):
        candidate = root.joinpath(*parts[:module_part_count]).with_suffix(".py")
        if (
            candidate.is_file()
            and not candidate.is_symlink()
            and test_root in candidate.resolve(strict=True).parents
        ):
            candidates.append((candidate.resolve(strict=True), tuple(parts[module_part_count:])))
    if len(candidates) != 1:
        raise PytestValidationError(
            "Pytest JUnit testcase does not identify one authoritative test source."
        )
    source, scopes = candidates[0]
    relative = source.relative_to(root).as_posix()
    return "::".join((relative, *scopes, name))


def _xml_nonnegative_int(attributes: dict[str, str], name: str) -> int:
    value = attributes.get(name)
    if value is None or not value.isascii() or not value.isdecimal():
        raise PytestValidationError(f"Pytest JUnit XML {name} count is not an integer.")
    parsed = int(value)
    if parsed < 0:
        raise PytestValidationError(f"Pytest JUnit XML {name} count is negative.")
    return parsed


def _junit_values(junit: _JunitObservation) -> dict[str, object]:
    return {
        "byte_count": junit.byte_count,
        "case_identities": list(junit.case_identities),
        "errors": junit.errors,
        "exact_bytes_hex": junit.exact_bytes.hex(),
        "failed": junit.failed,
        "node_ids": list(junit.node_ids),
        "passed": junit.passed,
        "runtime_seconds": junit.runtime_seconds,
        "sha256": junit.sha256,
        "skipped": junit.skipped,
        "skipped_node_ids": list(junit.skipped_node_ids),
        "skipped_reasons": list(junit.skipped_reasons),
        "total": junit.total,
    }


def _build_execution_specification(
    *,
    validation_run_identity: str,
    issuer_kind: PytestValidationIssuerKind,
    implementation_root: Path,
    pytest_root: Path,
    config_path: Path,
    selection: tuple[str, ...],
    junit_path: Path,
    command: tuple[str, ...],
    command_sha256: str,
    subprocess_environment_sha256: str,
    junit_initial_bytes: bytes,
    junit_file_identity: FileIdentity,
    identities: _CurrentValidationIdentities,
) -> _HistoricalPytestExecutionSpecification:
    interpreter_path = str(Path(sys.executable).resolve(strict=True))
    interpreter_executable_sha256 = hashlib.sha256(Path(interpreter_path).read_bytes()).hexdigest()
    base_interpreter_path = str(
        Path(cast(str, getattr(sys, "_base_executable", sys.executable))).resolve(strict=True)
    )
    base_interpreter_executable_sha256 = hashlib.sha256(
        Path(base_interpreter_path).read_bytes()
    ).hexdigest()
    pytest_version, pytest_source_sha256 = _distribution_runtime_identity("pytest")
    pluggy_version, pluggy_source_sha256 = _distribution_runtime_identity("pluggy")
    plugin_path = Path(__file__).resolve(strict=True)
    expected_conftests = _expected_conftest_identities(pytest_root, selection)
    expected_initial_plugins, expected_final_plugins = _expected_plugin_lifecycle(
        expected_conftests
    )
    expected_ephemeral_plugins = _expected_ephemeral_plugin_identities()
    values: dict[str, object] = {
        "base_interpreter_executable_sha256": base_interpreter_executable_sha256,
        "base_interpreter_path": base_interpreter_path,
        "broader_source_sha256": identities.broader_source_sha256,
        "command": list(command),
        "command_sha256": command_sha256,
        "complete_test_bundle_sha256": identities.complete_test_bundle_sha256,
        "configuration_boundary_sha256": _configuration_boundary_sha256(pytest_root),
        "controlled_environment": dict(_CONTROLLED_SUBPROCESS_ENVIRONMENT),
        "expected_conftest_identities": [list(item) for item in expected_conftests],
        "expected_ephemeral_plugin_identities": [list(item) for item in expected_ephemeral_plugins],
        "expected_final_plugin_identities": [list(item) for item in expected_final_plugins],
        "expected_initial_plugin_identities": [list(item) for item in expected_initial_plugins],
        "implementation_commit": identities.implementation_commit,
        "implementation_diff_sha256": identities.implementation_diff_sha256,
        "implementation_repository_root": str(implementation_root),
        "implementation_tree_sha256": identities.implementation_tree_sha256,
        "interpreter_executable_sha256": interpreter_executable_sha256,
        "interpreter_identity_sha256": identities.interpreter_identity_sha256,
        "interpreter_path": interpreter_path,
        "issuer_kind": issuer_kind,
        "junit_xml_path": str(junit_path),
        "junit_file_identity": list(junit_file_identity),
        "junit_initial_byte_count": len(junit_initial_bytes),
        "junit_initial_sha256": hashlib.sha256(junit_initial_bytes).hexdigest(),
        "platform_identity_sha256": identities.platform_identity_sha256,
        "pluggy_source_sha256": pluggy_source_sha256,
        "pluggy_version": pluggy_version,
        "pytest_config_path": str(config_path),
        "pytest_config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "pytest_root_directory": str(pytest_root),
        "pytest_source_sha256": pytest_source_sha256,
        "pytest_test_selection": list(selection),
        "pytest_version": pytest_version,
        "pytest_working_directory": str(pytest_root),
        "selection_source_sha256": _selection_source_sha256(selection),
        "subprocess_environment_sha256": subprocess_environment_sha256,
        "uv_lock_sha256": identities.uv_lock_sha256,
        "validation_plugin_path": str(plugin_path),
        "validation_plugin_source_sha256": hashlib.sha256(plugin_path.read_bytes()).hexdigest(),
        "validation_run_identity": validation_run_identity,
        "validation_version": PYTEST_VALIDATION_VERSION,
    }
    specification_identity = protocol_hash("pytest_execution_specification/v1", values)
    return _HistoricalPytestExecutionSpecification(
        validation_version=PYTEST_VALIDATION_VERSION,
        issuer_kind=issuer_kind,
        validation_run_identity=validation_run_identity,
        implementation_repository_root=str(implementation_root),
        pytest_root_directory=str(pytest_root),
        pytest_config_path=str(config_path),
        pytest_config_sha256=cast(str, values["pytest_config_sha256"]),
        pytest_working_directory=str(pytest_root),
        pytest_test_selection=selection,
        selection_source_sha256=cast(str, values["selection_source_sha256"]),
        junit_xml_path=str(junit_path),
        junit_initial_sha256=cast(str, values["junit_initial_sha256"]),
        junit_initial_byte_count=len(junit_initial_bytes),
        junit_file_identity=junit_file_identity,
        command=command,
        command_sha256=command_sha256,
        controlled_environment=_CONTROLLED_SUBPROCESS_ENVIRONMENT,
        implementation_commit=identities.implementation_commit,
        implementation_tree_sha256=identities.implementation_tree_sha256,
        implementation_diff_sha256=identities.implementation_diff_sha256,
        broader_source_sha256=identities.broader_source_sha256,
        complete_test_bundle_sha256=identities.complete_test_bundle_sha256,
        uv_lock_sha256=identities.uv_lock_sha256,
        interpreter_path=interpreter_path,
        interpreter_executable_sha256=interpreter_executable_sha256,
        base_interpreter_path=base_interpreter_path,
        base_interpreter_executable_sha256=base_interpreter_executable_sha256,
        interpreter_identity_sha256=identities.interpreter_identity_sha256,
        platform_identity_sha256=identities.platform_identity_sha256,
        pytest_version=pytest_version,
        pytest_source_sha256=pytest_source_sha256,
        pluggy_version=pluggy_version,
        pluggy_source_sha256=pluggy_source_sha256,
        validation_plugin_path=str(plugin_path),
        validation_plugin_source_sha256=cast(str, values["validation_plugin_source_sha256"]),
        subprocess_environment_sha256=subprocess_environment_sha256,
        expected_conftest_identities=expected_conftests,
        expected_ephemeral_plugin_identities=expected_ephemeral_plugins,
        expected_initial_plugin_identities=expected_initial_plugins,
        expected_final_plugin_identities=expected_final_plugins,
        configuration_boundary_sha256=cast(str, values["configuration_boundary_sha256"]),
        execution_specification_identity=specification_identity,
    )


def _specification_values(
    specification: _HistoricalPytestExecutionSpecification,
) -> dict[str, object]:
    return {
        "base_interpreter_executable_sha256": (specification.base_interpreter_executable_sha256),
        "base_interpreter_path": specification.base_interpreter_path,
        "broader_source_sha256": specification.broader_source_sha256,
        "command": list(specification.command),
        "command_sha256": specification.command_sha256,
        "complete_test_bundle_sha256": specification.complete_test_bundle_sha256,
        "configuration_boundary_sha256": specification.configuration_boundary_sha256,
        "controlled_environment": dict(specification.controlled_environment),
        "expected_conftest_identities": [
            list(item) for item in specification.expected_conftest_identities
        ],
        "expected_ephemeral_plugin_identities": [
            list(item) for item in specification.expected_ephemeral_plugin_identities
        ],
        "expected_final_plugin_identities": [
            list(item) for item in specification.expected_final_plugin_identities
        ],
        "expected_initial_plugin_identities": [
            list(item) for item in specification.expected_initial_plugin_identities
        ],
        "implementation_commit": specification.implementation_commit,
        "implementation_diff_sha256": specification.implementation_diff_sha256,
        "implementation_repository_root": specification.implementation_repository_root,
        "implementation_tree_sha256": specification.implementation_tree_sha256,
        "interpreter_executable_sha256": specification.interpreter_executable_sha256,
        "interpreter_identity_sha256": specification.interpreter_identity_sha256,
        "interpreter_path": specification.interpreter_path,
        "issuer_kind": specification.issuer_kind,
        "junit_xml_path": specification.junit_xml_path,
        "junit_file_identity": list(specification.junit_file_identity),
        "junit_initial_byte_count": specification.junit_initial_byte_count,
        "junit_initial_sha256": specification.junit_initial_sha256,
        "platform_identity_sha256": specification.platform_identity_sha256,
        "pluggy_source_sha256": specification.pluggy_source_sha256,
        "pluggy_version": specification.pluggy_version,
        "pytest_config_path": specification.pytest_config_path,
        "pytest_config_sha256": specification.pytest_config_sha256,
        "pytest_root_directory": specification.pytest_root_directory,
        "pytest_source_sha256": specification.pytest_source_sha256,
        "pytest_test_selection": list(specification.pytest_test_selection),
        "pytest_version": specification.pytest_version,
        "pytest_working_directory": specification.pytest_working_directory,
        "selection_source_sha256": specification.selection_source_sha256,
        "subprocess_environment_sha256": specification.subprocess_environment_sha256,
        "uv_lock_sha256": specification.uv_lock_sha256,
        "validation_plugin_path": specification.validation_plugin_path,
        "validation_plugin_source_sha256": (specification.validation_plugin_source_sha256),
        "validation_run_identity": specification.validation_run_identity,
        "validation_version": specification.validation_version,
    }


def _specification_document(
    specification: _HistoricalPytestExecutionSpecification,
) -> dict[str, object]:
    return {
        **_specification_values(specification),
        "execution_specification_identity": (specification.execution_specification_identity),
    }


def _specification_fingerprint(specification: _HistoricalPytestExecutionSpecification) -> str:
    return hashlib.sha256(
        canonical_json_bytes(_specification_document(specification), final_lf=True)
    ).hexdigest()


def _selection_source_sha256(selection: tuple[str, ...]) -> str:
    rows: list[dict[str, object]] = []
    for selected_text in selection:
        selected = Path(selected_text).resolve(strict=True)
        paths = (
            (selected,)
            if selected.is_file()
            else tuple(
                path for path in selected.rglob("*.py") if path.is_file() and not path.is_symlink()
            )
        )
        for path in paths:
            raw = path.read_bytes()
            rows.append(
                {
                    "byte_count": len(raw),
                    "path": str(path.resolve(strict=True)),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
    rows.sort(key=lambda row: cast(str, row["path"]).encode("utf-8"))
    return protocol_hash("pytest_selected_sources/v1", rows)


def _expected_conftest_identities(
    pytest_root: Path,
    selection: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    paths: set[Path] = set()
    test_root = (pytest_root / "tests").resolve()
    for selected_text in selection:
        selected = Path(selected_text).resolve(strict=True)
        if selected.is_dir():
            paths.update(selected.rglob("conftest.py"))
            cursor = selected
        else:
            cursor = selected.parent
        if cursor == test_root or test_root in cursor.parents:
            while cursor == test_root or test_root in cursor.parents:
                candidate = cursor / "conftest.py"
                if candidate.is_file() and not candidate.is_symlink():
                    paths.add(candidate)
                if cursor == test_root:
                    break
                cursor = cursor.parent
    identities = tuple(
        (str(path.resolve(strict=True)), hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(paths, key=lambda item: str(item).encode("utf-8"))
        if path.is_file() and not path.is_symlink()
    )
    return identities


def _expected_plugin_lifecycle(
    expected_conftests: tuple[tuple[str, str], ...],
    *,
    trusted_modules: Mapping[str, ModuleType] | None = None,
    trusted_distribution_identities: Mapping[str, tuple[str | None, str | None]] | None = None,
) -> tuple[tuple[PluginIdentity, ...], tuple[PluginIdentity, ...]]:
    config_module = (
        importlib.import_module("_pytest.config")
        if trusted_modules is None
        else trusted_modules.get("_pytest.config")
    )
    if type(config_module) is not ModuleType:
        raise PytestValidationError("Trusted pytest configuration module is unavailable.")
    default_plugins = getattr(config_module, "default_plugins", None)
    if not isinstance(default_plugins, tuple) or not all(
        isinstance(item, str) for item in default_plugins
    ):
        raise PytestValidationError("Installed pytest default plugin contract is malformed.")
    initial: list[PluginIdentity] = []
    for plugin_name in default_plugins:
        module_name = f"_pytest.{plugin_name}"
        initial.append(
            _expected_plugin_identity(
                registration_name=plugin_name,
                module_name=module_name,
                qualname=module_name,
                trusted_modules=trusted_modules,
                trusted_distribution_identities=trusted_distribution_identities,
            )
        )
    initial.append(
        _expected_plugin_identity(
            registration_name=_PLUGIN_NAME,
            module_name=_PLUGIN_NAME,
            qualname=_PLUGIN_NAME,
            trusted_modules=trusted_modules,
            trusted_distribution_identities=trusted_distribution_identities,
        )
    )
    for registration_name, module_name, qualname in _PYTEST_CONFIGURE_RUNTIME_PLUGINS:
        initial.append(
            _expected_plugin_identity(
                registration_name=registration_name,
                module_name=module_name,
                qualname=qualname,
                trusted_modules=trusted_modules,
                trusted_distribution_identities=trusted_distribution_identities,
            )
        )
    for source_path, source_sha256 in expected_conftests:
        initial.append(
            _expected_plugin_identity(
                registration_name=source_path,
                module_name=_expected_conftest_module_name(Path(source_path)),
                qualname=_expected_conftest_module_name(Path(source_path)),
                source_path=source_path,
                source_sha256=source_sha256,
                trusted_modules=trusted_modules,
                trusted_distribution_identities=trusted_distribution_identities,
            )
        )
    initial_plugins = tuple(sorted(initial, key=_plugin_identity_sort_key))
    if len(set(initial_plugins)) != len(initial_plugins):
        raise PytestValidationError("Expected pytest plugin lifecycle contains duplicates.")
    final = list(initial_plugins)
    for registration_name, module_name, qualname in _PYTEST_SESSION_RUNTIME_PLUGINS:
        final.append(
            _expected_plugin_identity(
                registration_name=registration_name,
                module_name=module_name,
                qualname=qualname,
                trusted_modules=trusted_modules,
                trusted_distribution_identities=trusted_distribution_identities,
            )
        )
    final_plugins = tuple(sorted(final, key=_plugin_identity_sort_key))
    if len(set(final_plugins)) != len(final_plugins):
        raise PytestValidationError("Expected final pytest plugin lifecycle contains duplicates.")
    return initial_plugins, final_plugins


def _expected_ephemeral_plugin_identities() -> tuple[PluginIdentity, ...]:
    return (
        _expected_plugin_identity(
            registration_name="runtime:_pytest.junitxml:LogXML",
            module_name="_pytest.junitxml",
            qualname="LogXML",
        ),
    )


def _expected_plugin_identity(
    *,
    registration_name: str,
    module_name: str,
    qualname: str,
    source_path: str | None = None,
    source_sha256: str | None = None,
    trusted_modules: Mapping[str, ModuleType] | None = None,
    trusted_distribution_identities: Mapping[str, tuple[str | None, str | None]] | None = None,
) -> PluginIdentity:
    if source_path is None:
        module = (
            importlib.import_module(module_name)
            if trusted_modules is None
            else trusted_modules.get(module_name)
        )
        if type(module) is not ModuleType:
            raise PytestValidationError(
                f"Expected trusted pytest plugin module is unavailable: {module_name}."
            )
        module_file = getattr(module, "__file__", None)
        if not isinstance(module_file, str):
            raise PytestValidationError(
                f"Expected pytest plugin has no source file: {module_name}."
            )
        candidate = Path(module_file)
        if candidate.suffix == ".pyc" and candidate.with_suffix(".py").is_file():
            candidate = candidate.with_suffix(".py")
        if not candidate.is_file() or candidate.is_symlink():
            raise PytestValidationError(
                f"Expected pytest plugin source is not regular: {module_name}."
            )
        candidate = candidate.resolve(strict=True)
        source_path = str(candidate)
        source_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
    elif source_sha256 is None:
        raise PytestValidationError("Expected pytest plugin source hash is missing.")
    if trusted_distribution_identities is None:
        distribution_name, distribution_version = _module_distribution_identity(module_name)
    else:
        distribution_identity = trusted_distribution_identities.get(module_name)
        if distribution_identity is None:
            raise PytestValidationError(
                f"Expected trusted pytest distribution identity is unavailable: {module_name}."
            )
        distribution_name, distribution_version = distribution_identity
    return (
        registration_name,
        module_name,
        qualname,
        source_path,
        source_sha256,
        distribution_name,
        distribution_version,
    )


def _module_distribution_identity(module_name: str) -> tuple[str | None, str | None]:
    candidates = importlib_metadata.packages_distributions().get(module_name.partition(".")[0], [])
    if not candidates:
        return None, None
    distribution_name = sorted(candidates, key=str.casefold)[0]
    try:
        return distribution_name, importlib_metadata.version(distribution_name)
    except importlib_metadata.PackageNotFoundError:
        return None, None


def _expected_conftest_module_name(path: Path) -> str:
    package_parts: list[str] = []
    cursor = path.parent
    while (cursor / "__init__.py").is_file() and not (cursor / "__init__.py").is_symlink():
        package_parts.append(cursor.name)
        cursor = cursor.parent
    if not package_parts:
        return "conftest"
    return ".".join((*reversed(package_parts), "conftest"))


def _configuration_boundary_sha256(pytest_root: Path) -> str:
    root = pytest_root.resolve(strict=True)
    rows: list[dict[str, object]] = []
    cursor = root
    while True:
        names = ["conftest.py", ".pytest.ini", "pytest.ini", "setup.cfg", "tox.ini"]
        if cursor != root:
            names.append("pyproject.toml")
        for name in names:
            candidate = cursor / name
            row: dict[str, object] = {
                "exists": candidate.exists() or candidate.is_symlink(),
                "path": str(candidate),
            }
            if candidate.exists() or candidate.is_symlink():
                if not candidate.is_file() or candidate.is_symlink():
                    raise PytestValidationError(
                        f"Unauthorized pytest boundary path is not a regular file: {candidate}."
                    )
                try:
                    raw = candidate.read_bytes()
                except OSError as error:
                    raise PytestValidationError(
                        f"Unauthorized pytest boundary path cannot be read: {candidate}."
                    ) from error
                row["byte_count"] = len(raw)
                row["sha256"] = hashlib.sha256(raw).hexdigest()
                if name == "conftest.py" or _is_pytest_configuration(candidate, raw):
                    raise PytestValidationError(
                        f"Unauthorized pytest configuration exists outside tests: {candidate}."
                    )
            rows.append(row)
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent
    return protocol_hash("pytest_configuration_boundary/v1", rows)


def _is_pytest_configuration(path: Path, raw: bytes) -> bool:
    if path.name in {".pytest.ini", "pytest.ini"}:
        return True
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PytestValidationError(
            f"Potential pytest configuration is not UTF-8: {path}."
        ) from error
    if path.name == "pyproject.toml":
        try:
            document = tomllib.loads(text)
        except tomllib.TOMLDecodeError as error:
            raise PytestValidationError(
                f"Potential parent pytest configuration is malformed: {path}."
            ) from error
        tool = document.get("tool")
        return (
            isinstance(tool, dict)
            and isinstance(tool.get("pytest"), dict)
            and "ini_options" in tool["pytest"]
        )
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(text)
    except configparser.Error as error:
        raise PytestValidationError(
            f"Potential parent pytest configuration is malformed: {path}."
        ) from error
    expected_section = "tool:pytest" if path.name == "setup.cfg" else "pytest"
    return parser.has_section(expected_section)


def _specification_sources_are_current(
    specification: _HistoricalPytestExecutionSpecification,
    *,
    require_ephemeral_junit: bool,
) -> bool:
    try:
        config_path = Path(specification.pytest_config_path).resolve(strict=True)
        pytest_root = Path(specification.pytest_root_directory).resolve(strict=True)
        plugin_path = Path(specification.validation_plugin_path).resolve(strict=True)
        junit_path = Path(specification.junit_xml_path)
        pytest_version, pytest_sha256 = _distribution_runtime_identity("pytest")
        pluggy_version, pluggy_sha256 = _distribution_runtime_identity("pluggy")
        expected_conftests = _expected_conftest_identities(
            pytest_root, specification.pytest_test_selection
        )
        expected_initial_plugins, expected_final_plugins = _expected_plugin_lifecycle(
            expected_conftests
        )
        expected_ephemeral_plugins = _expected_ephemeral_plugin_identities()
        return (
            hashlib.sha256(config_path.read_bytes()).hexdigest()
            == specification.pytest_config_sha256
            and _selection_source_sha256(specification.pytest_test_selection)
            == specification.selection_source_sha256
            and expected_conftests == specification.expected_conftest_identities
            and expected_ephemeral_plugins == specification.expected_ephemeral_plugin_identities
            and expected_initial_plugins == specification.expected_initial_plugin_identities
            and expected_final_plugins == specification.expected_final_plugin_identities
            and _configuration_boundary_sha256(pytest_root)
            == specification.configuration_boundary_sha256
            and _subprocess_environment_sha256(_base_subprocess_environment())
            == specification.subprocess_environment_sha256
            and (
                not require_ephemeral_junit
                or (
                    not junit_path.is_symlink()
                    and _regular_single_link_file_identity(
                        junit_path.stat(follow_symlinks=False), "persisted JUnit path"
                    )
                    == specification.junit_file_identity
                )
            )
            and hashlib.sha256(plugin_path.read_bytes()).hexdigest()
            == specification.validation_plugin_source_sha256
            and pytest_version == specification.pytest_version
            and pytest_sha256 == specification.pytest_source_sha256
            and pluggy_version == specification.pluggy_version
            and pluggy_sha256 == specification.pluggy_source_sha256
            and hashlib.sha256(Path(specification.interpreter_path).read_bytes()).hexdigest()
            == specification.interpreter_executable_sha256
            and hashlib.sha256(Path(specification.base_interpreter_path).read_bytes()).hexdigest()
            == specification.base_interpreter_executable_sha256
        )
    except (OSError, PytestValidationError):
        return False


def _distribution_runtime_identity(distribution_name: str) -> tuple[str, str]:
    try:
        distribution = importlib_metadata.distribution(distribution_name)
    except importlib_metadata.PackageNotFoundError as error:
        raise PytestValidationError(
            f"Required pytest runtime distribution is missing: {distribution_name}."
        ) from error
    rows: list[dict[str, object]] = []
    for relative in sorted(distribution.files or (), key=lambda item: str(item).encode("utf-8")):
        path = Path(str(distribution.locate_file(relative)))
        if not path.is_file() or path.is_symlink() or path.suffix in {".pyc", ".pyo"}:
            continue
        raw = path.read_bytes()
        rows.append(
            {
                "byte_count": len(raw),
                "path": str(relative).replace("\\", "/"),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    if not rows:
        raise PytestValidationError(
            f"Required pytest runtime distribution has no files: {distribution_name}."
        )
    return distribution.version, protocol_hash(
        "pytest_runtime_distribution/v1",
        {"distribution": distribution_name, "files": rows, "version": distribution.version},
    )


def _current_production_dependency_environment() -> tuple[tuple[str, str, str, str], ...]:
    """Return exact installed identities for the Stage-1 pytest dependency set."""

    rows: list[tuple[str, str, str, str]] = []
    for distribution_name in ("pluggy", "pytest"):
        distribution = importlib_metadata.distribution(distribution_name)
        installation_root = Path(str(distribution.locate_file(""))).resolve(strict=True)
        if (
            not installation_root.is_dir()
            or installation_root.is_symlink()
            or _path_is_link_like(installation_root)
        ):
            raise PytestValidationError(
                f"Required dependency installation root is irregular: {distribution_name}."
            )
        version, installation_identity = _distribution_runtime_identity(distribution_name)
        rows.append(
            (
                distribution_name,
                version,
                str(installation_root),
                installation_identity,
            )
        )
    return tuple(rows)


def _distribution_file_identities(distribution_name: str) -> dict[str, str]:
    try:
        distribution = importlib_metadata.distribution(distribution_name)
    except importlib_metadata.PackageNotFoundError as error:
        raise PytestValidationError(
            f"Required plugin distribution is missing: {distribution_name}."
        ) from error
    identities: dict[str, str] = {}
    for relative in distribution.files or ():
        path = Path(str(distribution.locate_file(relative)))
        if path.is_file() and not path.is_symlink() and path.suffix not in {".pyc", ".pyo"}:
            resolved = str(path.resolve(strict=True))
            identities[resolved] = hashlib.sha256(path.read_bytes()).hexdigest()
    return identities


def _observe_pytest_configuration(config: object) -> _ObservedPytestConfiguration:
    observed = cast(Any, config)
    invocation = observed.invocation_params
    inipath = observed.inipath
    testpaths = observed.getini("testpaths")
    addopts = observed.getini("addopts")
    return _ObservedPytestConfiguration(
        root_directory=str(Path(observed.rootpath).resolve(strict=True)),
        config_path=(None if inipath is None else str(Path(inipath).resolve(strict=True))),
        invocation_directory=str(Path(invocation.dir).resolve(strict=True)),
        invocation_arguments=tuple(str(item) for item in invocation.args),
        resolved_arguments=tuple(str(item) for item in observed.args),
        testpaths=tuple(str(item) for item in testpaths),
        addopts=tuple(str(item) for item in addopts),
    )


def _observed_configuration_values(
    observation: _ObservedPytestConfiguration,
) -> dict[str, object]:
    return {
        "addopts": list(observation.addopts),
        "config_path": observation.config_path,
        "invocation_arguments": list(observation.invocation_arguments),
        "invocation_directory": observation.invocation_directory,
        "resolved_arguments": list(observation.resolved_arguments),
        "root_directory": observation.root_directory,
        "testpaths": list(observation.testpaths),
    }


def _receipt_observed_configuration(
    receipt: dict[str, object],
) -> _ObservedPytestConfiguration:
    value = receipt.get("observed_configuration")
    expected_keys = {
        "addopts",
        "config_path",
        "invocation_arguments",
        "invocation_directory",
        "resolved_arguments",
        "root_directory",
        "testpaths",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise PytestValidationError("Observed pytest configuration receipt is malformed.")
    config_path = value.get("config_path")
    if config_path is not None and not isinstance(config_path, str):
        raise PytestValidationError("Observed pytest config path is malformed.")
    return _ObservedPytestConfiguration(
        root_directory=_object_str(value, "root_directory"),
        config_path=config_path,
        invocation_directory=_object_str(value, "invocation_directory"),
        invocation_arguments=_object_string_tuple(value, "invocation_arguments"),
        resolved_arguments=_object_string_tuple(value, "resolved_arguments"),
        testpaths=_object_string_tuple(value, "testpaths"),
        addopts=_object_string_tuple(value, "addopts"),
    )


def _validate_observed_configuration(
    observed: _ObservedPytestConfiguration,
    specification: _HistoricalPytestExecutionSpecification,
) -> None:
    if (
        observed.root_directory != specification.pytest_root_directory
        or observed.config_path != specification.pytest_config_path
        or observed.invocation_directory != specification.pytest_working_directory
        or observed.invocation_arguments != _pytest_argument_tail(specification.command)
        or observed.resolved_arguments != specification.pytest_test_selection
        or observed.testpaths != ("tests",)
        or observed.addopts
    ):
        raise PytestValidationError(
            "Effective pytest root/config/arguments differ from the frozen specification."
        )


def _effective_plugin_identities(config: object) -> tuple[PluginIdentity, ...]:
    manager = cast(Any, config).pluginmanager
    identities = [
        _plugin_identity_from_object(str(raw_name), plugin)
        for raw_name, plugin in manager.list_name_plugin()
        if plugin is not None
    ]
    if len(set(identities)) != len(identities):
        raise PytestValidationError("Effective pytest plugin identities are duplicate.")
    return tuple(sorted(identities, key=_plugin_identity_sort_key))


def _plugin_identity_from_object(raw_name: str, plugin: object) -> PluginIdentity:
    name = str(raw_name)
    module: ModuleType | None
    if isinstance(plugin, ModuleType):
        module = plugin
        qualname = module.__name__
        module_name = module.__name__
    elif isinstance(plugin, type):
        module_name = plugin.__module__
        module = sys.modules.get(module_name)
        qualname = plugin.__qualname__
    else:
        plugin_type = type(plugin)
        module_name = plugin_type.__module__
        module = sys.modules.get(module_name)
        qualname = plugin_type.__qualname__
    if name.isascii() and name.isdecimal():
        name = f"runtime:{module_name}:{qualname}"
    source_path: str | None = None
    source_sha256: str | None = None
    module_file = None if module is None else getattr(module, "__file__", None)
    if isinstance(module_file, str):
        candidate = Path(module_file)
        if candidate.suffix == ".pyc":
            source_candidate = candidate.with_suffix(".py")
            if source_candidate.is_file():
                candidate = source_candidate
        if candidate.is_file() and not candidate.is_symlink():
            candidate = candidate.resolve(strict=True)
            source_path = str(candidate)
            source_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
    distribution_name, distribution_version = _module_distribution_identity(module_name)
    return (
        name,
        module_name,
        qualname,
        source_path,
        source_sha256,
        distribution_name,
        distribution_version,
    )


def _plugin_identity_sort_key(identity: PluginIdentity) -> tuple[str, ...]:
    return tuple("" if item is None else item for item in identity)


def _conftest_identities(
    plugin_identities: tuple[PluginIdentity, ...],
) -> tuple[tuple[str, str], ...]:
    values = {
        (source_path, source_sha256)
        for _, _, _, source_path, source_sha256, _, _ in plugin_identities
        if source_path is not None
        and source_sha256 is not None
        and Path(source_path).name == "conftest.py"
    }
    return tuple(sorted(values, key=lambda item: item[0].encode("utf-8")))


def _validate_effective_plugin_identities(
    plugin_identities: tuple[PluginIdentity, ...],
    specification: _HistoricalPytestExecutionSpecification,
) -> None:
    if not plugin_identities or len(set(plugin_identities)) != len(plugin_identities):
        raise PytestValidationError("Effective pytest plugin identities are empty or duplicate.")
    pytest_files = _distribution_file_identities("pytest")
    pluggy_files = _distribution_file_identities("pluggy")
    conftest_files = dict(specification.expected_conftest_identities)
    explicit_plugin = {
        specification.validation_plugin_path: (specification.validation_plugin_source_sha256)
    }
    allowed_files = {**pytest_files, **pluggy_files, **conftest_files, **explicit_plugin}
    for identity in plugin_identities:
        (
            _,
            module_name,
            _,
            source_path,
            source_sha256,
            distribution_name,
            distribution_version,
        ) = identity
        if source_path is None or source_sha256 is None:
            if not module_name.startswith(("_pytest", "pytest", "pluggy")):
                raise PytestValidationError(
                    f"Effective pytest plugin lacks bound source identity: {module_name}."
                )
            continue
        if allowed_files.get(source_path) != source_sha256:
            raise PytestValidationError(
                f"Effective pytest plugin is outside the frozen sources: {source_path}."
            )
        normalized_distribution = (
            None if distribution_name is None else distribution_name.casefold().replace("_", "-")
        )
        if normalized_distribution == "pytest" and (
            distribution_version != specification.pytest_version
        ):
            raise PytestValidationError("Effective pytest plugin version differs.")
        if normalized_distribution == "pluggy" and (
            distribution_version != specification.pluggy_version
        ):
            raise PytestValidationError("Effective pluggy plugin version differs.")


def _validate_plugin_identity_transition(
    initial: tuple[PluginIdentity, ...],
    session: tuple[PluginIdentity, ...],
    final: tuple[PluginIdentity, ...],
    specification: _HistoricalPytestExecutionSpecification,
) -> None:
    _validate_effective_plugin_identities(initial, specification)
    _validate_effective_plugin_identities(session, specification)
    _validate_effective_plugin_identities(final, specification)
    if initial != specification.expected_initial_plugin_identities:
        raise PytestValidationError(
            "Effective initial pytest plugin set differs from the exact lifecycle."
        )
    if session != specification.expected_final_plugin_identities:
        raise PytestValidationError(
            "Effective session-final pytest plugin set differs from the exact lifecycle."
        )
    if final != _expected_terminal_plugin_identities(specification):
        raise PytestValidationError(
            "Effective process-terminal pytest plugin set differs from the exact lifecycle."
        )


def _expected_terminal_plugin_identities(
    specification: _HistoricalPytestExecutionSpecification,
) -> tuple[PluginIdentity, ...]:
    authoritative = tuple(
        identity
        for identity in specification.expected_final_plugin_identities
        if identity[:3] == (_AUTHORITATIVE_JUNIT_PLUGIN_NAME, _PLUGIN_NAME, "_AuthoritativeLogXML")
    )
    if len(authoritative) != 1:
        raise PytestValidationError("Authoritative terminal JUnit lifecycle is ambiguous.")
    return tuple(
        identity
        for identity in specification.expected_final_plugin_identities
        if identity != authoritative[0]
    )


def _receipt_plugin_identities(
    receipt: dict[str, object],
    field_name: str,
) -> tuple[PluginIdentity, ...]:
    value = receipt.get(field_name)
    if not isinstance(value, list):
        raise PytestValidationError("Pytest plugin identity receipt is malformed.")
    identities: list[PluginIdentity] = []
    for raw in value:
        if not isinstance(raw, list) or len(raw) != 7:
            raise PytestValidationError("Pytest plugin identity row is malformed.")
        if not all(item is None or isinstance(item, str) for item in raw):
            raise PytestValidationError("Pytest plugin identity value is malformed.")
        if not all(isinstance(raw[index], str) for index in (0, 1, 2)):
            raise PytestValidationError("Pytest plugin identity name is malformed.")
        identities.append(
            cast(
                PluginIdentity,
                tuple(raw),
            )
        )
    parsed = tuple(identities)
    if parsed != tuple(sorted(parsed, key=_plugin_identity_sort_key)):
        raise PytestValidationError("Pytest plugin identities are not canonical.")
    return parsed


def _receipt_plugin_lifecycle_events(
    receipt: dict[str, object],
    field_name: str,
) -> tuple[_PluginLifecycleEvent, ...]:
    value = receipt.get(field_name)
    if not isinstance(value, list):
        raise PytestValidationError("Pytest plugin lifecycle trace is malformed.")
    events: list[_PluginLifecycleEvent] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict) or set(raw) != {
            "action",
            "plugin_identity",
            "sequence",
        }:
            raise PytestValidationError("Pytest plugin lifecycle event is malformed.")
        action = raw.get("action")
        sequence = raw.get("sequence")
        identity_rows = _receipt_plugin_identities(
            {"identity": [raw.get("plugin_identity")]},
            "identity",
        )
        if (
            action not in ("register", "unregister")
            or isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence != index
            or len(identity_rows) != 1
        ):
            raise PytestValidationError("Pytest plugin lifecycle event is not canonical.")
        events.append(
            _PluginLifecycleEvent(
                sequence=sequence,
                action=cast(PluginLifecycleAction, action),
                plugin_identity=identity_rows[0],
            )
        )
    return tuple(events)


def _validate_plugin_lifecycle_trace(
    events: tuple[_PluginLifecycleEvent, ...],
    specification: _HistoricalPytestExecutionSpecification,
    *,
    completed_phase: bool,
) -> None:
    registrations = Counter(event.plugin_identity for event in events if event.action == "register")
    unregistrations = Counter(
        event.plugin_identity for event in events if event.action == "unregister"
    )
    expected_registrations = Counter(specification.expected_initial_plugin_identities)
    expected_registrations.update(specification.expected_ephemeral_plugin_identities)
    expected_unregistrations = Counter(specification.expected_ephemeral_plugin_identities)
    if completed_phase:
        initial = Counter(specification.expected_initial_plugin_identities)
        session = Counter(specification.expected_final_plugin_identities)
        terminal = Counter(_expected_terminal_plugin_identities(specification))
        if initial - session or terminal - session:
            raise PytestValidationError("Expected pytest plugin lifecycle removes core plugins.")
        expected_registrations.update(session - initial)
        expected_unregistrations.update(session - terminal)
    if registrations != expected_registrations or unregistrations != expected_unregistrations:
        raise PytestValidationError(
            "Pytest plugin lifecycle contains an unauthorized transient mutation."
        )
    if len(specification.expected_ephemeral_plugin_identities) != 1:
        raise PytestValidationError("Expected pytest ephemeral plugin contract is ambiguous.")
    native_junit = specification.expected_ephemeral_plugin_identities[0]
    authoritative_junit = tuple(
        identity
        for identity in specification.expected_initial_plugin_identities
        if identity[:3] == (_AUTHORITATIVE_JUNIT_PLUGIN_NAME, _PLUGIN_NAME, "_AuthoritativeLogXML")
    )
    if len(authoritative_junit) != 1:
        raise PytestValidationError("Authoritative JUnit plugin lifecycle is ambiguous.")
    native_register = next(
        event.sequence
        for event in events
        if event.action == "register" and event.plugin_identity == native_junit
    )
    native_unregister = next(
        event.sequence
        for event in events
        if event.action == "unregister" and event.plugin_identity == native_junit
    )
    authoritative_register = next(
        event.sequence
        for event in events
        if event.action == "register" and event.plugin_identity == authoritative_junit[0]
    )
    authoritative_unregister = (
        next(
            event.sequence
            for event in events
            if event.action == "unregister" and event.plugin_identity == authoritative_junit[0]
        )
        if completed_phase
        else None
    )
    if not native_register < native_unregister < authoritative_register or (
        authoritative_unregister is not None
        and not authoritative_register < authoritative_unregister
    ):
        raise PytestValidationError(
            "Native and authoritative JUnit plugin lifecycle order differs."
        )


def _receipt_file_identity(
    receipt: dict[str, object],
    field_name: str,
) -> FileIdentity:
    value = receipt.get(field_name)
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
    ):
        raise PytestValidationError("Pytest file identity receipt is malformed.")
    return cast(FileIdentity, tuple(value))


def _receipt_conftest_identities(
    receipt: dict[str, object],
) -> tuple[tuple[str, str], ...]:
    value = receipt.get("conftest_identities")
    if not isinstance(value, list):
        raise PytestValidationError("Pytest conftest identity receipt is malformed.")
    rows: list[tuple[str, str]] = []
    for raw in value:
        if (
            not isinstance(raw, list)
            or len(raw) != 2
            or not all(isinstance(item, str) for item in raw)
        ):
            raise PytestValidationError("Pytest conftest identity row is malformed.")
        rows.append((raw[0], raw[1]))
    parsed = tuple(rows)
    if parsed != tuple(sorted(parsed, key=lambda item: item[0].encode("utf-8"))):
        raise PytestValidationError("Pytest conftest identities are not canonical.")
    return parsed


def _validate_runtime_receipt_identities(
    receipt: dict[str, object],
    specification: _HistoricalPytestExecutionSpecification,
) -> None:
    expected = (
        specification.interpreter_path,
        specification.interpreter_executable_sha256,
        specification.base_interpreter_path,
        specification.base_interpreter_executable_sha256,
        specification.pytest_version,
        specification.pytest_source_sha256,
        specification.pluggy_version,
        specification.pluggy_source_sha256,
        specification.validation_plugin_source_sha256,
    )
    observed = tuple(
        _receipt_str(receipt, name)
        for name in (
            "interpreter_path",
            "interpreter_executable_sha256",
            "base_interpreter_path",
            "base_interpreter_executable_sha256",
            "pytest_version",
            "pytest_source_sha256",
            "pluggy_version",
            "pluggy_source_sha256",
            "plugin_source_sha256",
        )
    )
    if observed != expected:
        raise PytestValidationError("Pytest runtime/interpreter identities differ.")


def _receipt_junit(receipt: dict[str, object]) -> dict[str, object]:
    value = receipt.get("junit")
    expected_keys = {
        "byte_count",
        "case_identities",
        "errors",
        "exact_bytes_hex",
        "failed",
        "node_ids",
        "passed",
        "runtime_seconds",
        "sha256",
        "skipped",
        "skipped_node_ids",
        "skipped_reasons",
        "total",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise PytestValidationError("Pytest JUnit receipt is malformed.")
    for name in ("byte_count", "errors", "failed", "passed", "skipped", "total"):
        parsed = value.get(name)
        if isinstance(parsed, bool) or not isinstance(parsed, int) or parsed < 0:
            raise PytestValidationError("Pytest JUnit receipt count is malformed.")
    sha256 = _object_str(value, "sha256")
    runtime = _object_str(value, "runtime_seconds")
    exact_hex = _object_str(value, "exact_bytes_hex")
    case_identities = _object_string_tuple(value, "case_identities")
    node_ids = _object_string_tuple(value, "node_ids")
    skipped_node_ids = _object_string_tuple(value, "skipped_node_ids")
    skipped_reasons = _object_string_tuple(value, "skipped_reasons")
    try:
        exact_bytes = bytes.fromhex(exact_hex)
        runtime_decimal = Decimal(runtime)
    except (ValueError, InvalidOperation) as error:
        raise PytestValidationError("Pytest JUnit receipt encoding is malformed.") from error
    if (
        exact_hex != exact_bytes.hex()
        or len(exact_bytes) != value["byte_count"]
        or hashlib.sha256(exact_bytes).hexdigest() != sha256
        or _HEX_SHA256.fullmatch(sha256) is None
        or not runtime_decimal.is_finite()
        or runtime_decimal < 0
        or len(case_identities) != value["total"]
        or len(set(case_identities)) != len(case_identities)
        or len(node_ids) != value["total"]
        or len(set(node_ids)) != len(node_ids)
        or len(skipped_node_ids) != value["skipped"]
        or len(skipped_reasons) != value["skipped"]
        or len(set(skipped_node_ids)) != len(skipped_node_ids)
        or value["passed"] + value["skipped"] + value["failed"] + value["errors"] != value["total"]
    ):
        raise PytestValidationError("Pytest JUnit receipt does not reconcile.")
    return cast(dict[str, object], value)


def _pytest_argument_tail(command: tuple[str, ...]) -> tuple[str, ...]:
    try:
        module_index = command.index("pytest")
    except ValueError as error:
        raise PytestValidationError("Pytest command omits its module name.") from error
    if module_index < 2 or command[module_index - 1] != "-m":
        raise PytestValidationError("Pytest command does not use python -m pytest.")
    return command[module_index + 1 :]


def _expected_runtime_controlled_environment(pytest_version: str) -> dict[str, str | None]:
    expected = dict(_CONTROLLED_SUBPROCESS_ENVIRONMENT)
    expected["PYTEST_VERSION"] = pytest_version
    return expected


def _base_subprocess_environment() -> dict[str, str]:
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith(_ENV_PREFIX)
    }
    for name, expected_value in _CONTROLLED_SUBPROCESS_ENVIRONMENT:
        if expected_value is None:
            environment.pop(name, None)
        else:
            environment[name] = expected_value
    return environment


def _subprocess_environment_sha256(environment: dict[str, str]) -> str:
    rows: list[dict[str, object]] = []
    for name in sorted(environment, key=os.fsencode):
        if name.startswith(_ENV_PREFIX):
            raise PytestValidationError(
                "RDE nonce-bearing variables cannot enter the base environment identity."
            )
        name_bytes = os.fsencode(name)
        value_bytes = os.fsencode(environment[name])
        rows.append(
            {
                "name_sha256": hashlib.sha256(name_bytes).hexdigest(),
                "value_byte_count": len(value_bytes),
                "value_sha256": hashlib.sha256(value_bytes).hexdigest(),
            }
        )
    return protocol_hash("pytest_subprocess_environment/v1", rows)


def _load_canonical_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        raw = path.read_bytes()
        loaded = json.loads(raw)
        canonical = canonical_json_bytes(loaded, final_lf=True)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise PytestValidationError(f"{label} is not valid canonical JSON.") from error
    if (
        not raw.endswith(b"\n")
        or raw != canonical
        or not isinstance(loaded, dict)
        or not all(isinstance(key, str) for key in loaded)
    ):
        raise PytestValidationError(f"{label} is not a canonical JSON object.")
    return cast(dict[str, object], loaded)


def _write_exclusive_bytes(path: Path, payload: bytes, label: str) -> None:
    try:
        with path.open("xb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    except OSError as error:
        raise RuntimeError(f"Could not write pytest validation {label}.") from error


def _document_str(document: dict[str, object], name: str) -> str:
    value = document.get(name)
    if not isinstance(value, str):
        raise RuntimeError(f"Pytest execution specification {name} is malformed.")
    return value


def _object_str(document: dict[object, object], name: str) -> str:
    value = document.get(name)
    if not isinstance(value, str):
        raise PytestValidationError(f"Pytest receipt {name} is malformed.")
    return value


def _object_string_tuple(document: dict[object, object], name: str) -> tuple[str, ...]:
    value = document.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PytestValidationError(f"Pytest receipt {name} is not a string list.")
    return tuple(value)


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        ctypes, kernel32, wintypes = _windows_kernel32()
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return _windows_last_error(ctypes) == 5
        try:
            exit_code = cast(Any, wintypes).DWORD()
            if not kernel32.GetExitCodeProcess(handle, cast(Any, ctypes).byref(exit_code)):
                return True
            return cast(int, exit_code.value) == 259
        finally:
            if not kernel32.CloseHandle(handle):
                raise PytestValidationError("Process liveness handle could not be closed.")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_authoritative_process_end(
    process: _ProcessMonitor,
    *,
    observed_plugin_pid: int | None,
    deadline: float,
    clock: Callable[[], float] = time.monotonic,
    pause: Callable[[float], None] = time.sleep,
    is_alive: Callable[[int], bool] = _process_is_alive,
) -> bool:
    while True:
        launcher_alive = process.poll() is None
        plugin_alive = (
            observed_plugin_pid is not None
            and observed_plugin_pid != process.pid
            and is_alive(observed_plugin_pid)
        )
        if not launcher_alive and not plugin_alive:
            return True
        remaining = deadline - clock()
        if remaining <= 0:
            return False
        pause(min(0.01, remaining))


def _require_process_tree_terminated(
    process: _ProcessMonitor,
    *,
    observed_plugin_pid: int | None,
    deadline: float,
    failure_details: str,
    clock: Callable[[], float] = time.monotonic,
    pause: Callable[[float], None] = time.sleep,
    is_alive: Callable[[int], bool] = _process_is_alive,
) -> None:
    if not _wait_for_authoritative_process_end(
        process,
        observed_plugin_pid=observed_plugin_pid,
        deadline=deadline,
        clock=clock,
        pause=pause,
        is_alive=is_alive,
    ):
        raise PytestValidationError(
            "Pytest process tree remained alive after bounded cleanup: " + failure_details
        )


def _terminate_process_tree(
    process: subprocess.Popen[bytes],
    *,
    observed_plugin_pid: int | None,
) -> tuple[bytes, bytes]:
    termination_failures: list[str] = []
    pids = tuple(
        dict.fromkeys(pid for pid in (process.pid, observed_plugin_pid) if pid is not None)
    )
    if os.name == "nt":
        taskkill = shutil.which("taskkill.exe") or shutil.which("taskkill")
        if taskkill is None:
            termination_failures.append("taskkill is unavailable")
        else:
            for pid in pids:
                try:
                    completed = subprocess.run(  # noqa: S603
                        (taskkill, "/PID", str(pid), "/T", "/F"),
                        check=False,
                        capture_output=True,
                        timeout=_TERMINATION_WAIT_SECONDS,
                    )
                    if completed.returncode != 0 and _process_is_alive(pid):
                        termination_failures.append(
                            f"taskkill returned {completed.returncode} for pid {pid}"
                        )
                except (OSError, subprocess.TimeoutExpired) as error:
                    termination_failures.append(
                        f"taskkill failed for pid {pid}: {type(error).__name__}"
                    )
    else:
        try:
            cast(Any, os).killpg(process.pid, cast(Any, signal).SIGKILL)
        except OSError as error:
            if _process_is_alive(process.pid):
                termination_failures.append(
                    f"process-group termination failed: {type(error).__name__}"
                )
        if observed_plugin_pid not in (None, process.pid):
            try:
                os.kill(observed_plugin_pid, cast(Any, signal).SIGKILL)
            except OSError as error:
                if _process_is_alive(observed_plugin_pid):
                    termination_failures.append(
                        f"pytest-child termination failed: {type(error).__name__}"
                    )
    if process.poll() is None:
        with suppress(OSError):
            process.kill()
    try:
        stdout, stderr = process.communicate(timeout=_TERMINATION_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        with suppress(OSError):
            process.kill()
        try:
            stdout, stderr = process.communicate(timeout=_TERMINATION_WAIT_SECONDS)
        except subprocess.TimeoutExpired as final_error:
            raise PytestValidationError(
                "Pytest launcher pipes did not close within the bounded cleanup window."
            ) from final_error
    details = "; ".join(termination_failures) or "termination command did not stop every pid"
    _require_process_tree_terminated(
        process,
        observed_plugin_pid=observed_plugin_pid,
        deadline=time.monotonic() + _TERMINATION_WAIT_SECONDS,
        failure_details=details,
    )
    return stdout, stderr


def _current_validation_identities() -> _CurrentValidationIdentities:
    root = repository_root().resolve(strict=True)
    implementation_commit = _git_text(root, "rev-parse", "--verify", "HEAD^{commit}").strip()
    if (
        not re.fullmatch(r"[0-9a-f]{40}", implementation_commit)
        or implementation_commit in PUBLIC_PROVENANCE_ROLE_TOKENS
    ):
        raise PytestValidationError("Current implementation commit is not a full Git object ID.")
    tracked_modes = _tracked_modes(root)
    current_paths = set(tracked_modes)
    current_paths.update(_untracked_paths(root))
    current_rows: list[dict[str, object]] = []
    for relative in sorted(current_paths, key=lambda item: item.encode("utf-8")):
        if not _is_implementation_scope(relative):
            continue
        path = root / Path(relative)
        if not path.exists() and not path.is_symlink():
            continue
        raw = os.readlink(path).encode("utf-8") if path.is_symlink() else path.read_bytes()
        git_mode = tracked_modes.get(relative)
        if git_mode is None:
            git_mode = _untracked_git_mode(path)
        current_rows.append(
            {
                "byte_count": len(raw),
                "git_mode": git_mode,
                "path": relative,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "tracked": relative in tracked_modes,
            }
        )
    head_rows = _head_tree_rows(root, implementation_commit)
    implementation_tree_sha256 = protocol_hash(
        "pytest_current_implementation_tree/v1", current_rows
    )
    implementation_diff_sha256 = protocol_hash(
        "pytest_current_implementation_diff/v1",
        {
            "current_rows": current_rows,
            "head_rows": head_rows,
            "implementation_commit": implementation_commit,
        },
    )
    broader_rows = [
        row
        for row in current_rows
        if str(row["path"]).startswith("research_decision_engine/benchmarks/broader_")
        and str(row["path"]).endswith(".py")
    ]
    test_rows = [
        row
        for row in current_rows
        if str(row["path"]).startswith("tests/") and str(row["path"]).endswith(".py")
    ]
    if not broader_rows or not test_rows:
        raise PytestValidationError("Broader sources or complete tests could not be identified.")
    design_bytes = (root / DESIGN_FILENAME).read_bytes()
    frozen_design_bytes = _git_bytes(
        root,
        "show",
        f"{implementation_commit}:{DESIGN_FILENAME}",
    )
    if design_bytes != frozen_design_bytes:
        raise PytestValidationError("Frozen broader design source differs from its checkpoint.")
    lock_bytes = (root / "uv.lock").read_bytes()
    executable_path = Path(sys.executable).resolve(strict=True)
    executable_bytes = executable_path.read_bytes()
    interpreter_identity_sha256 = protocol_hash(
        "pytest_interpreter_identity/v1",
        {
            "cache_tag": sys.implementation.cache_tag,
            "compiler": platform.python_compiler(),
            "executable_path": str(executable_path),
            "executable_sha256": hashlib.sha256(executable_bytes).hexdigest(),
            "implementation": sys.implementation.name,
            "python_version": platform.python_version(),
        },
    )
    platform_identity_sha256 = protocol_hash(
        "pytest_platform_identity/v1",
        {
            "machine": platform.machine(),
            "platform": platform.platform(),
            "release": platform.release(),
            "system": platform.system(),
            "version": platform.version(),
        },
    )
    return _CurrentValidationIdentities(
        implementation_commit=implementation_commit,
        design_checkpoint_commit=SOURCE_CHECKPOINT,
        source_design_sha256=hashlib.sha256(design_bytes).hexdigest(),
        implementation_tree_sha256=implementation_tree_sha256,
        implementation_diff_sha256=implementation_diff_sha256,
        broader_source_sha256=protocol_hash("broader_validation_sources/v1", broader_rows),
        complete_test_bundle_sha256=protocol_hash("complete_pytest_bundle/v1", test_rows),
        uv_lock_sha256=hashlib.sha256(lock_bytes).hexdigest(),
        interpreter_identity_sha256=interpreter_identity_sha256,
        platform_identity_sha256=platform_identity_sha256,
    )


def _tracked_modes(root: Path) -> dict[str, str]:
    output = _git_bytes(
        root,
        "ls-files",
        "--stage",
        "-z",
        "--",
        "pyproject.toml",
        "uv.lock",
        "research_decision_engine",
        "tests",
    )
    modes: dict[str, str] = {}
    for item in output.split(b"\0"):
        if not item:
            continue
        metadata, separator, path_bytes = item.partition(b"\t")
        parts = metadata.split(b" ")
        if not separator or len(parts) != 3:
            raise PytestValidationError("Could not parse tracked implementation identity.")
        mode = parts[0].decode("ascii")
        stage = parts[2].decode("ascii")
        relative = path_bytes.decode("utf-8")
        if stage != "0":
            raise PytestValidationError("Unmerged implementation files cannot be validated.")
        modes[relative] = mode
    return modes


def _untracked_paths(root: Path) -> tuple[str, ...]:
    output = _git_bytes(
        root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        "pyproject.toml",
        "uv.lock",
        "research_decision_engine",
        "tests",
    )
    return tuple(item.decode("utf-8") for item in output.split(b"\0") if item)


def _head_tree_rows(root: Path, implementation_commit: str) -> list[dict[str, str]]:
    if (
        not re.fullmatch(r"[0-9a-f]{40}", implementation_commit)
        or implementation_commit in PUBLIC_PROVENANCE_ROLE_TOKENS
    ):
        raise PytestValidationError(
            "Committed tree revision is not a captured implementation commit."
        )
    output = _git_bytes(
        root,
        "ls-tree",
        "-r",
        "-z",
        implementation_commit,
        "--",
        "pyproject.toml",
        "uv.lock",
        "research_decision_engine",
        "tests",
    )
    rows: list[dict[str, str]] = []
    for item in output.split(b"\0"):
        if not item:
            continue
        metadata, separator, path_bytes = item.partition(b"\t")
        parts = metadata.split(b" ")
        if not separator or len(parts) != 3:
            raise PytestValidationError("Could not parse committed implementation identity.")
        relative = path_bytes.decode("utf-8")
        if _is_implementation_scope(relative):
            rows.append(
                {
                    "git_mode": parts[0].decode("ascii"),
                    "git_object": parts[2].decode("ascii"),
                    "path": relative,
                }
            )
    rows.sort(key=lambda row: row["path"].encode("utf-8"))
    return rows


def _is_implementation_scope(relative: str) -> bool:
    return relative in {"pyproject.toml", "uv.lock"} or relative.startswith(
        ("research_decision_engine/", "tests/")
    )


def _untracked_git_mode(path: Path) -> str:
    if path.is_symlink():
        return "120000"
    return "100755" if path.stat().st_mode & stat.S_IXUSR else "100644"


def _git_text(root: Path, *arguments: str) -> str:
    return _git_bytes(root, *arguments).decode("utf-8")


def _git_bytes(root: Path, *arguments: str) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        raise PytestValidationError("Git is required to issue pytest validation evidence.")
    completed = subprocess.run(  # noqa: S603
        (executable, *arguments),
        cwd=root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise PytestValidationError(f"Git identity command failed: {detail}")
    return completed.stdout


def _identity_values(identities: _CurrentValidationIdentities) -> dict[str, str]:
    return {
        "broader_source_sha256": identities.broader_source_sha256,
        "complete_test_bundle_sha256": identities.complete_test_bundle_sha256,
        "design_checkpoint_commit": identities.design_checkpoint_commit,
        "implementation_commit": identities.implementation_commit,
        "implementation_diff_sha256": identities.implementation_diff_sha256,
        "implementation_tree_sha256": identities.implementation_tree_sha256,
        "interpreter_identity_sha256": identities.interpreter_identity_sha256,
        "platform_identity_sha256": identities.platform_identity_sha256,
        "source_design_sha256": identities.source_design_sha256,
        "uv_lock_sha256": identities.uv_lock_sha256,
    }


def _require_issued_result(
    result: PytestValidationResult,
    *,
    require_active: bool,
    require_current: bool,
    owner_claim: PytestValidationOwnerClaim | None,
) -> _IssuedPytestValidationResult:
    if type(result) is not PytestValidationResult:
        raise PytestValidationError("Pytest validation result is not an exact issued object.")
    with _RESULT_LOCK:
        record = _ISSUED_RESULTS.get(id(result))
        if record is None or record.result is not result:
            raise PytestValidationError("Pytest validation result is forged or unknown.")
        if require_active and not record.active:
            raise PytestValidationError("Pytest validation result is stale or already consumed.")
        _require_owner_claim(record, owner_claim)
        observation = record.observation
        specification = record.specification
        if record.observation_fingerprint != _observation_fingerprint(observation):
            raise PytestValidationError("Pytest validation observation was mutated.")
        if observation.result_identity != protocol_hash(
            "pytest_validation_result/v1", _observation_values(observation)
        ):
            raise PytestValidationError("Pytest validation result identity was mutated.")
        if record.specification_fingerprint != _specification_fingerprint(
            specification
        ) or specification.execution_specification_identity != protocol_hash(
            "pytest_execution_specification/v1",
            _specification_values(specification),
        ):
            raise PytestValidationError("Pytest execution specification was mutated.")
        if observation.junit_xml_sha256 is None:
            if record.junit_xml_bytes:
                raise PytestValidationError("Unexpected JUnit bytes exist for failed evidence.")
        elif (
            len(record.junit_xml_bytes) != observation.junit_xml_byte_count
            or hashlib.sha256(record.junit_xml_bytes).hexdigest() != observation.junit_xml_sha256
        ):
            raise PytestValidationError("Registry-owned JUnit XML bytes were altered.")
    if require_current:
        current = _current_validation_identities()
        if _identity_values(current) != _observation_identity_values(
            observation
        ) or not _specification_sources_are_current(
            specification,
            require_ephemeral_junit=False,
        ):
            raise PytestValidationError("Pytest validation result source identity is stale.")
    with _RESULT_LOCK:
        current_record = _ISSUED_RESULTS.get(id(result))
        if current_record is not record or current_record.result is not result:
            raise PytestValidationError("Pytest validation result changed during validation.")
        if require_active and not current_record.active:
            raise PytestValidationError("Pytest validation result is stale or already consumed.")
        _require_owner_claim(current_record, owner_claim)
        if current_record.observation_fingerprint != _observation_fingerprint(
            current_record.observation
        ) or current_record.specification_fingerprint != _specification_fingerprint(
            current_record.specification
        ):
            raise PytestValidationError("Pytest validation result changed during validation.")
    return record


def _require_owner_claim(
    record: _IssuedPytestValidationResult,
    owner_claim: PytestValidationOwnerClaim | None,
) -> None:
    if record.owner_claim is None:
        if owner_claim is not None:
            raise PytestValidationError("Pytest validation owner claim is forged or stale.")
    elif record.owner_claim is not owner_claim:
        raise PytestValidationError("Pytest validation result belongs to another owner claim.")


def _observation_values(observation: PytestValidationObservation) -> dict[str, object]:
    return {
        "base_interpreter_executable_sha256": (observation.base_interpreter_executable_sha256),
        "base_interpreter_path": observation.base_interpreter_path,
        "broader_source_sha256": observation.broader_source_sha256,
        "collected_node_ids": list(observation.collected_node_ids),
        "command": list(observation.command),
        "command_sha256": observation.command_sha256,
        "completed": observation.completed,
        "complete_test_bundle_sha256": observation.complete_test_bundle_sha256,
        "deselected_node_ids": list(observation.deselected_node_ids),
        "design_checkpoint_commit": observation.design_checkpoint_commit,
        "effective_conftest_identities": [
            list(item) for item in observation.effective_conftest_identities
        ],
        "effective_plugin_identities": [
            list(item) for item in observation.effective_plugin_identities
        ],
        "errors": observation.errors,
        "execution_specification_identity": (observation.execution_specification_identity),
        "execution_status": observation.execution_status,
        "exit_code": observation.exit_code,
        "failed": observation.failed,
        "failure_details": list(observation.failure_details),
        "implementation_commit": observation.implementation_commit,
        "implementation_diff_sha256": observation.implementation_diff_sha256,
        "implementation_repository_root": observation.implementation_repository_root,
        "implementation_tree_sha256": observation.implementation_tree_sha256,
        "interpreter_executable_sha256": observation.interpreter_executable_sha256,
        "interpreter_identity_sha256": observation.interpreter_identity_sha256,
        "interpreter_path": observation.interpreter_path,
        "issuer_kind": observation.issuer_kind,
        "junit_case_identities": list(observation.junit_case_identities),
        "junit_xml_byte_count": observation.junit_xml_byte_count,
        "junit_xml_path": observation.junit_xml_path,
        "junit_xml_sha256": observation.junit_xml_sha256,
        "passed": observation.passed,
        "platform_identity_sha256": observation.platform_identity_sha256,
        "pluggy_source_sha256": observation.pluggy_source_sha256,
        "pluggy_version": observation.pluggy_version,
        "pytest_config_path": observation.pytest_config_path,
        "pytest_root_directory": observation.pytest_root_directory,
        "pytest_source_sha256": observation.pytest_source_sha256,
        "pytest_test_selection": list(observation.pytest_test_selection),
        "pytest_version": observation.pytest_version,
        "pytest_working_directory": observation.pytest_working_directory,
        "runtime_seconds": observation.runtime_seconds,
        "skipped": observation.skipped,
        "skipped_node_ids": list(observation.skipped_node_ids),
        "skipped_reasons": list(observation.skipped_reasons),
        "source_design_sha256": observation.source_design_sha256,
        "subprocess_completion_identity": observation.subprocess_completion_identity,
        "subprocess_environment_sha256": observation.subprocess_environment_sha256,
        "subprocess_start_identity": observation.subprocess_start_identity,
        "total": observation.total,
        "uv_lock_sha256": observation.uv_lock_sha256,
        "validation_plugin_source_sha256": (observation.validation_plugin_source_sha256),
        "validation_run_identity": observation.validation_run_identity,
        "validation_version": observation.validation_version,
    }


def _observation_fingerprint(observation: PytestValidationObservation) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {**_observation_values(observation), "result_identity": observation.result_identity},
            final_lf=True,
        )
    ).hexdigest()


def _observation_identity_values(observation: PytestValidationObservation) -> dict[str, str]:
    return {
        "broader_source_sha256": observation.broader_source_sha256,
        "complete_test_bundle_sha256": observation.complete_test_bundle_sha256,
        "design_checkpoint_commit": observation.design_checkpoint_commit,
        "implementation_commit": observation.implementation_commit,
        "implementation_diff_sha256": observation.implementation_diff_sha256,
        "implementation_tree_sha256": observation.implementation_tree_sha256,
        "interpreter_identity_sha256": observation.interpreter_identity_sha256,
        "platform_identity_sha256": observation.platform_identity_sha256,
        "source_design_sha256": observation.source_design_sha256,
        "uv_lock_sha256": observation.uv_lock_sha256,
    }


def _is_fixed_production_command(observation: PytestValidationObservation) -> bool:
    root = Path(observation.implementation_repository_root)
    test_root = root / "tests"
    expected = (
        sys.executable,
        "-P",
        "-m",
        "pytest",
        "-p",
        _PLUGIN_NAME,
        "-c",
        observation.pytest_config_path,
        f"--rootdir={observation.pytest_root_directory}",
        f"--confcutdir={test_root}",
        f"--junitxml={observation.junit_xml_path}",
        *observation.pytest_test_selection,
    )
    return (
        observation.command == expected
        and observation.command_sha256
        == protocol_hash("pytest_validation_command/v1", list(expected))
        and observation.pytest_root_directory == str(root)
        and observation.pytest_working_directory == str(root)
        and observation.pytest_config_path == str(root / "pyproject.toml")
        and observation.pytest_test_selection == (str(root / "tests"),)
    )


def _require_bundle_if_supplied(
    record: _IssuedPytestValidationResult,
    evidence_bundle_identity: str | None,
) -> None:
    if evidence_bundle_identity is None:
        return
    _validate_external_identity(evidence_bundle_identity, "evidence bundle")
    if record.evidence_bundle_identity != evidence_bundle_identity:
        raise PytestValidationError("Pytest result belongs to another evidence bundle.")


def _validate_external_identity(value: str, label: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise PytestValidationError(f"Pytest {label} identity is empty or noncanonical.")


def _require_sha256(value: str, label: str) -> None:
    if _HEX_SHA256.fullmatch(value) is None:
        raise RuntimeError(f"Pytest validation {label} is not canonical SHA-256.")


def _required_environment_value(values: dict[str, str | None], name: str) -> str:
    value = values[name]
    if value is None:
        raise RuntimeError("Incomplete broader pytest validation plugin environment.")
    return value


def _exact_skip_reason(longrepr: object) -> str:
    if isinstance(longrepr, tuple) and len(longrepr) >= 3:
        return str(longrepr[2])
    return str(longrepr)


def _receipt_str(receipt: dict[str, object], name: str) -> str:
    value = receipt.get(name)
    if not isinstance(value, str):
        raise PytestValidationError(f"Pytest plugin receipt {name} is not text.")
    return value


def _receipt_int(receipt: dict[str, object], name: str) -> int:
    value = receipt.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PytestValidationError(f"Pytest plugin receipt {name} is not an integer.")
    return value


def _receipt_string_tuple(receipt: dict[str, object], name: str) -> tuple[str, ...]:
    value = receipt.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PytestValidationError(f"Pytest plugin receipt {name} is not a string list.")
    return tuple(value)


def _receipt_skips(receipt: dict[str, object] | None) -> tuple[_PluginSkip, ...]:
    if receipt is None:
        return ()
    value = receipt.get("skips")
    if not isinstance(value, list):
        raise PytestValidationError("Pytest plugin receipt skips are malformed.")
    skips: list[_PluginSkip] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"node_id", "reason"}:
            raise PytestValidationError("Pytest plugin skip record is malformed.")
        node_id = item.get("node_id")
        reason = item.get("reason")
        if (
            not isinstance(node_id, str)
            or not node_id
            or not isinstance(reason, str)
            or node_id in seen
        ):
            raise PytestValidationError("Pytest plugin skip record is noncanonical.")
        seen.add(node_id)
        skips.append(_PluginSkip(node_id=node_id, reason=reason))
    return tuple(skips)


(
    _issue_production_pytest_plan_draft,
    _validate_production_pytest_runtime,
) = _install_production_pytest_plan_draft_issuer(os, os.urandom)
del _install_production_pytest_plan_draft_issuer


if os.environ.get(_ENV_NONCE) is not None:
    atexit.register(_finalize_pytest_receipt_at_process_exit, os.getpid())
