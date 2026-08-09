"""Portable recorded-observation RunBundle export, verification, and replay."""

from __future__ import annotations

import errno as _errno
import hashlib
import json
import math
import os
import platform
import random
import sqlite3
import stat
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from ctypes import CDLL as _CDLL
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Final, Literal, cast
from typing import Protocol as _Protocol

from research_decision_engine.policies import _select_random_available
from research_decision_engine.run_spec import (
    CandidateSpec,
    CompletedWorkloadExperiment,
    NormalizedObservation,
    RunSpec,
    _canonical_json_bytes,
    _canonical_json_text,
    _object_without_duplicate_keys,
    _reject_nonfinite_json_constant,
)
from research_decision_engine.storage import SCHEMA_VERSION, ExperimentStore

_SCHEMA: Final[Literal["rde-core-run-bundle/v1"]] = "rde-core-run-bundle/v1"
_ARTIFACT_ROLE: Final[Literal["portable_recorded_observation_run_bundle"]] = (
    "portable_recorded_observation_run_bundle"
)
_REPLAY_CONTRACT: Final[Literal["RECORDED_OBSERVATION_DECISION_REPLAY_V1"]] = (
    "RECORDED_OBSERVATION_DECISION_REPLAY_V1"
)
_BUNDLE_NAME: Final = "run-bundle.json"
_SIDECAR_NAME: Final = "run-bundle.json.sha256"
_REPLAY_DATABASE_NAME: Final = "replay.sqlite3"
_REPLAY_CREATED_AT: Final = "1970-01-01T00:00:00+00:00"
_SELECTION_RULE: Final = "random-choice-over-remaining-candidates/v1"
_DIST_NAME: Final = "research-decision-engine"

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "artifact_role",
        "replay_contract",
        "run_spec",
        "run_spec_sha256",
        "producer",
        "steps",
        "terminal_summary",
        "section_sha256",
        "root_member_count",
    }
)
_PRODUCER_KEYS = frozenset(
    {"package_name", "package_version", "python_implementation", "python_version"}
)
_SECTION_KEYS = frozenset({"run_spec", "steps", "terminal_summary"})
_STEP_KEYS = frozenset(
    {
        "step_index",
        "selected_candidate_id",
        "decision",
        "rationale",
        "observation",
        "belief_lineage",
        "cumulative_cost",
    }
)
_DECISION_KEYS = frozenset({"policy_config", "policy_id", "policy_seed", "selected_candidate_id"})
_RATIONALE_KEYS = frozenset(
    {"available_candidate_ids", "completed_candidate_ids", "selection_rule"}
)
_OBSERVATION_KEYS = frozenset({"candidate_id", "objective_value", "cost"})
_TERMINAL_KEYS = frozenset(
    {
        "completed_steps",
        "selected_candidate_ids",
        "total_cost",
        "stop_reason",
        "final_belief_fingerprint",
        "decision_history_sha256",
    }
)
_STOP_REASONS = frozenset(
    {
        "completed",
        "experiment_budget_exhausted",
        "cost_budget_exhausted",
        "candidate_space_exhausted",
        "stopped_by_caller",
    }
)
_HIDDEN_TRUTH_KEYS = frozenset(
    {
        "benchmark_truth",
        "benchmarktruth",
        "ground_truth",
        "groundtruth",
        "hidden_truth",
        "hiddentruth",
        "oracle_value",
        "oracle_values",
        "oraclevalue",
        "oraclevalues",
        "potential_outcome",
        "potential_outcomes",
        "potentialoutcome",
        "potentialoutcomes",
        "true_value",
        "true_values",
        "truevalue",
        "truevalues",
        "unselected_outcome",
        "unselected_outcomes",
        "unselectedoutcome",
        "unselectedoutcomes",
    }
)

StopReason = Literal[
    "completed",
    "experiment_budget_exhausted",
    "cost_budget_exhausted",
    "candidate_space_exhausted",
    "stopped_by_caller",
]


class RunBundleError(RuntimeError):
    """Base class for all portable RunBundle failures."""


class RunBundleValidationError(RunBundleError):
    """A requested RunBundle or export violates the v1 contract."""


class RunBundleVerificationError(RunBundleError):
    """A materialized RunBundle fails strict read-only verification."""


class RunBundleReplayError(RunBundleError):
    """A verified RunBundle cannot be replayed equivalently."""


@dataclass(frozen=True, slots=True, init=False)
class RunBundleStep:
    """One immutable recorded decision and normalized observation."""

    step_index: int
    selected_candidate_id: str
    cumulative_cost: float
    _decision_json: str = field(repr=False)
    _rationale_json: str = field(repr=False)
    _observation_json: str = field(repr=False)
    _belief_lineage_json: str = field(repr=False)

    def __init__(
        self,
        *,
        step_index: int,
        selected_candidate_id: str,
        decision: Mapping[str, object],
        rationale: Mapping[str, object],
        observation: Mapping[str, object],
        belief_lineage: Sequence[Mapping[str, object]],
        cumulative_cost: float,
    ) -> None:
        if type(step_index) is not int or step_index < 0:
            raise RunBundleValidationError("step_index must be a nonnegative integer.")
        if type(selected_candidate_id) is not str or not selected_candidate_id:
            raise RunBundleValidationError("selected_candidate_id must be nonempty.")
        if type(cumulative_cost) is not float or not math.isfinite(cumulative_cost):
            raise RunBundleValidationError("cumulative_cost must be an exact finite float.")
        if cumulative_cost < 0.0 or (
            cumulative_cost == 0.0 and math.copysign(1.0, cumulative_cost) < 0.0
        ):
            raise RunBundleValidationError("cumulative_cost must use nonnegative canonical zero.")
        if not isinstance(decision, Mapping) or not isinstance(rationale, Mapping):
            raise RunBundleValidationError("decision and rationale must be mappings.")
        if not isinstance(observation, Mapping) or type(belief_lineage) not in (list, tuple):
            raise RunBundleValidationError(
                "observation must be a mapping and belief_lineage a list or tuple."
            )
        if any(not isinstance(item, Mapping) for item in belief_lineage):
            raise RunBundleValidationError("Every belief lineage entry must be a mapping.")
        try:
            decision_payload = _required_object(dict(decision), _DECISION_KEYS, "decision")
            rationale_payload = _required_object(dict(rationale), _RATIONALE_KEYS, "rationale")
            observation_payload = _required_object(
                dict(observation), _OBSERVATION_KEYS, "observation"
            )
            lineage_payload = [dict(item) for item in belief_lineage]
            _reject_hidden_truth(
                {
                    "decision": decision_payload,
                    "rationale": rationale_payload,
                    "observation": observation_payload,
                    "belief_lineage": lineage_payload,
                }
            )
            _reject_absolute_paths(
                {
                    "decision": decision_payload,
                    "rationale": rationale_payload,
                    "observation": observation_payload,
                    "belief_lineage": lineage_payload,
                },
                field_name="RunBundleStep",
            )
            if decision_payload["selected_candidate_id"] != selected_candidate_id:
                raise RunBundleValidationError("Decision candidate does not match the step.")
            if observation_payload["candidate_id"] != selected_candidate_id:
                raise RunBundleValidationError("Observation candidate does not match the step.")
            if decision_payload["policy_id"] != "random" or decision_payload["policy_config"] != {}:
                raise RunBundleValidationError(
                    "RunBundle v1 step policy must be random with {} config."
                )
            policy_seed = decision_payload["policy_seed"]
            if type(policy_seed) is not int or policy_seed < -(2**63) or policy_seed > 2**63 - 1:
                raise RunBundleValidationError(
                    "Decision policy_seed must be a signed 64-bit integer."
                )
            available_ids = rationale_payload["available_candidate_ids"]
            completed_ids = rationale_payload["completed_candidate_ids"]
            if type(available_ids) is not list or any(
                type(item) is not str for item in available_ids
            ):
                raise RunBundleValidationError(
                    "Rationale available candidates must be a string list."
                )
            if type(completed_ids) is not list or any(
                type(item) is not str for item in completed_ids
            ):
                raise RunBundleValidationError(
                    "Rationale completed candidates must be a string list."
                )
            if len(available_ids) != len(set(available_ids)) or len(completed_ids) != len(
                set(completed_ids)
            ):
                raise RunBundleValidationError(
                    "Rationale candidate lists must not contain duplicates."
                )
            if set(available_ids).intersection(completed_ids):
                raise RunBundleValidationError(
                    "Rationale available and completed candidates overlap."
                )
            if selected_candidate_id not in available_ids or len(completed_ids) != step_index:
                raise RunBundleValidationError("Rationale context does not match the step index.")
            if rationale_payload["selection_rule"] != _SELECTION_RULE:
                raise RunBundleValidationError("Rationale selection rule is unsupported.")
            normalized_observation = NormalizedObservation(
                objective_value=cast(float, observation_payload["objective_value"]),
                cost=cast(float, observation_payload["cost"]),
            )
            if _canonical_json_bytes(observation_payload) != _canonical_json_bytes(
                _observation_payload(selected_candidate_id, normalized_observation)
            ):
                raise RunBundleValidationError("Observation is not the exact normalized payload.")
            if lineage_payload:
                raise RunBundleValidationError(
                    "RunBundle v1 random steps have empty belief lineage."
                )
            if cumulative_cost < normalized_observation.cost:
                raise RunBundleValidationError("cumulative_cost cannot be less than the step cost.")
            decision_json = _canonical_json_text(decision_payload)
            rationale_json = _canonical_json_text(rationale_payload)
            observation_json = _canonical_json_text(observation_payload)
            lineage_json = _canonical_json_text(lineage_payload)
        except RunBundleValidationError:
            raise
        except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
            raise RunBundleValidationError(
                "RunBundleStep payload is not canonical JSON data."
            ) from exc
        object.__setattr__(self, "step_index", step_index)
        object.__setattr__(self, "selected_candidate_id", selected_candidate_id)
        object.__setattr__(self, "cumulative_cost", cumulative_cost)
        object.__setattr__(self, "_decision_json", decision_json)
        object.__setattr__(self, "_rationale_json", rationale_json)
        object.__setattr__(self, "_observation_json", observation_json)
        object.__setattr__(self, "_belief_lineage_json", lineage_json)

    @property
    def decision(self) -> Mapping[str, object]:
        """Return a detached canonical decision payload."""

        return _json_object_copy(self._decision_json)

    @property
    def rationale(self) -> Mapping[str, object]:
        """Return a detached canonical rationale payload."""

        return _json_object_copy(self._rationale_json)

    @property
    def observation(self) -> Mapping[str, object]:
        """Return a detached candidate-bound normalized observation payload."""

        return _json_object_copy(self._observation_json)

    @property
    def belief_lineage(self) -> tuple[Mapping[str, object], ...]:
        """Return detached belief/update lineage entries for this step."""

        value = cast(object, json.loads(self._belief_lineage_json))
        if type(value) is not list:
            raise AssertionError("Stored belief lineage is not a JSON array.")
        return tuple(cast(dict[str, object], item) for item in value)

    def to_payload(self) -> dict[str, object]:
        """Return this step's exact seven-field canonical payload."""

        return {
            "step_index": self.step_index,
            "selected_candidate_id": self.selected_candidate_id,
            "decision": dict(self.decision),
            "rationale": dict(self.rationale),
            "observation": dict(self.observation),
            "belief_lineage": [dict(item) for item in self.belief_lineage],
            "cumulative_cost": self.cumulative_cost,
        }


@dataclass(frozen=True, slots=True, init=False)
class RunBundle:
    """Immutable decoded ``rde-core-run-bundle/v1`` artifact."""

    schema_version: Literal["rde-core-run-bundle/v1"]
    artifact_role: Literal["portable_recorded_observation_run_bundle"]
    replay_contract: Literal["RECORDED_OBSERVATION_DECISION_REPLAY_V1"]
    run_spec: RunSpec
    run_spec_sha256: str
    steps: tuple[RunBundleStep, ...]
    root_member_count: Literal[2]
    _producer_json: str = field(repr=False)
    _terminal_summary_json: str = field(repr=False)
    _section_sha256_json: str = field(repr=False)
    _canonical_bytes: bytes = field(repr=False)

    def __init__(self) -> None:
        raise TypeError("RunBundle instances are created only by export or strict verification.")

    @classmethod
    def _from_validated(
        cls,
        *,
        run_spec: RunSpec,
        run_spec_sha256: str,
        producer: Mapping[str, object],
        steps: Sequence[RunBundleStep],
        terminal_summary: Mapping[str, object],
        section_sha256: Mapping[str, object],
        canonical_bytes: bytes,
    ) -> RunBundle:
        self = object.__new__(cls)
        object.__setattr__(self, "schema_version", _SCHEMA)
        object.__setattr__(self, "artifact_role", _ARTIFACT_ROLE)
        object.__setattr__(self, "replay_contract", _REPLAY_CONTRACT)
        object.__setattr__(self, "run_spec", run_spec)
        object.__setattr__(self, "run_spec_sha256", run_spec_sha256)
        object.__setattr__(self, "steps", tuple(steps))
        object.__setattr__(self, "root_member_count", 2)
        object.__setattr__(self, "_producer_json", _canonical_json_text(dict(producer)))
        object.__setattr__(
            self, "_terminal_summary_json", _canonical_json_text(dict(terminal_summary))
        )
        object.__setattr__(self, "_section_sha256_json", _canonical_json_text(dict(section_sha256)))
        object.__setattr__(self, "_canonical_bytes", bytes(canonical_bytes))
        return self

    @property
    def producer(self) -> Mapping[str, str]:
        """Return detached, non-executable producer provenance."""

        return cast(Mapping[str, str], _json_object_copy(self._producer_json))

    @property
    def terminal_summary(self) -> Mapping[str, object]:
        """Return a detached terminal summary payload."""

        return _json_object_copy(self._terminal_summary_json)

    @property
    def section_sha256(self) -> Mapping[str, str]:
        """Return detached hashes for the three canonical sections."""

        return cast(Mapping[str, str], _json_object_copy(self._section_sha256_json))

    def to_canonical_bytes(self) -> bytes:
        """Return the exact canonical ``run-bundle.json`` bytes."""

        return bytes(self._canonical_bytes)


@dataclass(frozen=True, slots=True)
class RunBundleVerificationResult:
    """Successful immutable verification result; invalid bundles raise."""

    valid: Literal[True]
    bundle_sha256: str
    run_spec_sha256: str
    steps_sha256: str
    terminal_summary_sha256: str
    step_count: int
    selected_candidate_ids: tuple[str, ...]
    bundle: RunBundle = field(repr=False)


@dataclass(frozen=True, slots=True)
class RunBundleReplayResult:
    """Destination-independent recorded-observation replay result."""

    replay_contract: Literal["RECORDED_OBSERVATION_DECISION_REPLAY_V1"]
    bundle_sha256: str
    run_spec_sha256: str
    steps_sha256: str
    terminal_summary_sha256: str
    history_sha256: str
    step_count: int
    selected_candidate_ids: tuple[str, ...]
    sqlite_schema_version: int
    equivalent: Literal[True]


@dataclass(frozen=True, slots=True, init=False)
class CompletedWorkloadRunTrace:
    """One immutable, explicitly bounded generic workload execution trace."""

    run_spec: RunSpec
    steps: tuple[RunBundleStep, ...]
    stop_reason: StopReason

    def __init__(
        self,
        *,
        run_spec: RunSpec,
        steps: Sequence[RunBundleStep],
        stop_reason: StopReason,
    ) -> None:
        if type(run_spec) is not RunSpec:
            raise RunBundleValidationError("run_spec must be an exact RunSpec.")
        if type(steps) not in (list, tuple) or any(
            type(step) is not RunBundleStep for step in steps
        ):
            raise RunBundleValidationError(
                "steps must be an explicit list or tuple of exact RunBundleStep records."
            )
        if type(stop_reason) is not str or stop_reason not in _STOP_REASONS:
            raise RunBundleValidationError("stop_reason is not supported by RunBundle v1.")
        object.__setattr__(self, "run_spec", run_spec)
        object.__setattr__(self, "steps", tuple(steps))
        object.__setattr__(self, "stop_reason", stop_reason)


PolicySelection = tuple[CandidateSpec, tuple[str, ...]]
PolicyFactory = Callable[[RunSpec, frozenset[str]], PolicySelection]


def _random_policy_factory(
    run_spec: RunSpec, completed_candidate_ids: frozenset[str]
) -> PolicySelection:
    available = tuple(
        candidate
        for candidate in run_spec.candidates
        if candidate.candidate_id not in completed_candidate_ids
    )
    selected = _select_random_available(
        run_spec.candidates,
        completed_candidate_ids,
        random.Random(run_spec.policy_seed),
    )
    return selected, tuple(item.candidate_id for item in available)


_SUPPORTED_POLICY_FACTORIES: Mapping[str, PolicyFactory] = MappingProxyType(
    {"random": _random_policy_factory}
)


def export_run_bundle(
    destination: Path,
    *,
    trace: CompletedWorkloadRunTrace,
) -> RunBundleVerificationResult:
    """Atomically export one exact, explicitly bounded completed run trace."""

    destination_path = _exact_path(destination, field_name="destination")
    if os.path.lexists(destination_path):
        raise RunBundleValidationError("RunBundle destination must not already exist.")
    try:
        _require_plain_directory(destination_path.parent, "RunBundle destination parent")
        bundle = _build_run_bundle(trace)
    except RunBundleError:
        raise
    except Exception as exc:
        raise RunBundleValidationError("RunBundle export input validation failed.") from exc
    encoded = bundle.to_canonical_bytes()
    sidecar = hashlib.sha256(encoded).hexdigest().encode("ascii") + b"\n"

    temporary_path: Path | None = None
    temporary_root_identity: tuple[int, int] | None = None
    owned_member_identities: dict[str, tuple[int, int]] = {}
    published_guard: _DirectoryGuard | None = None
    publication_happened = False
    try:
        temporary_path = Path(
            tempfile.mkdtemp(
                prefix=f".{destination_path.name}.tmp-",
                dir=destination_path.parent,
            )
        )
        temporary_root_identity = _physical_identity(temporary_path.lstat())
        _write_new_file(
            temporary_path / _BUNDLE_NAME,
            encoded,
            owned_member_identities=owned_member_identities,
        )
        _write_new_file(
            temporary_path / _SIDECAR_NAME,
            sidecar,
            owned_member_identities=owned_member_identities,
        )
        verify_run_bundle(temporary_path)
        published_guard = _publish_directory_no_replace(
            temporary_path,
            destination_path,
            expected_identity=temporary_root_identity,
        )
        publication_happened = True
        temporary_path = None
        if _physical_identity(destination_path.lstat()) != temporary_root_identity:
            raise RunBundleValidationError("Published RunBundle root identity changed.")
        result = verify_run_bundle(destination_path)
        _close_directory_guard(published_guard)
        published_guard = None
        return result
    except BaseException as exc:
        if temporary_path is not None and temporary_root_identity is not None:
            _remove_owned_bundle_directory(
                temporary_path,
                root_identity=temporary_root_identity,
                member_identities=owned_member_identities,
            )
        if temporary_root_identity is not None:
            _remove_owned_bundle_directory(
                destination_path,
                root_identity=temporary_root_identity,
                member_identities=owned_member_identities,
            )
        if published_guard is not None:
            with suppress(OSError):
                _close_directory_guard(published_guard)
            published_guard = None
        if isinstance(exc, RunBundleError):
            raise
        if isinstance(exc, Exception):
            message = (
                "RunBundle export failed after publication; owned bytes were cleaned up."
                if publication_happened
                else "RunBundle export failed without publication."
            )
            raise RunBundleValidationError(message) from exc
        raise


def verify_run_bundle(bundle_directory: Path) -> RunBundleVerificationResult:
    """Strictly and read-only verify one exact two-member RunBundle directory."""

    ancestry_guard: _AncestryGuard | None = None
    member_guards: tuple[_PosixMemberGuard, ...] = ()
    member_guard_by_name: dict[str, _PosixMemberGuard] = {}
    try:
        root = _exact_path(bundle_directory, field_name="bundle_directory")
        ancestry_guard = _open_ancestry_guard(root, label="RunBundle root")
        root_guard = ancestry_guard.components[-1].guard
        root_identity = _physical_identity(root.lstat())
        member_paths = _strict_bundle_inventory(root)
        if root_guard.windows:
            member_identities = {
                name: _physical_identity(path.lstat()) for name, path in member_paths.items()
            }
        else:
            member_guards = _open_posix_member_guards(root_guard)
            member_guard_by_name = {guard.name: guard for guard in member_guards}
            member_identities = {
                name: guard.identity for name, guard in member_guard_by_name.items()
            }
        encoded = _read_stable_member(
            member_paths[_BUNDLE_NAME],
            expected_identity=member_identities[_BUNDLE_NAME],
            posix_guard=member_guard_by_name.get(_BUNDLE_NAME),
        )
        sidecar = _read_stable_member(
            member_paths[_SIDECAR_NAME],
            expected_identity=member_identities[_SIDECAR_NAME],
            posix_guard=member_guard_by_name.get(_SIDECAR_NAME),
        )
        bundle_sha256 = hashlib.sha256(encoded).hexdigest()
        if len(sidecar) != 65 or sidecar != bundle_sha256.encode("ascii") + b"\n":
            raise RunBundleVerificationError("RunBundle sidecar is malformed or does not match.")
        payload = _decode_canonical_document(encoded)
        bundle = _validated_bundle(payload, encoded)
        final_member_paths = _strict_bundle_inventory(root)
        final_member_identities = {
            name: _physical_identity(path.lstat()) for name, path in final_member_paths.items()
        }
        if final_member_identities != member_identities:
            raise RunBundleVerificationError("RunBundle member identity changed while verified.")
        if (
            _read_stable_member(
                final_member_paths[_BUNDLE_NAME],
                expected_identity=member_identities[_BUNDLE_NAME],
                posix_guard=member_guard_by_name.get(_BUNDLE_NAME),
            )
            != encoded
            or _read_stable_member(
                final_member_paths[_SIDECAR_NAME],
                expected_identity=member_identities[_SIDECAR_NAME],
                posix_guard=member_guard_by_name.get(_SIDECAR_NAME),
            )
            != sidecar
        ):
            raise RunBundleVerificationError("RunBundle members changed while verified.")
        _require_member_identities(final_member_paths, expected=member_identities)
        if _physical_identity(root.lstat()) != root_identity:
            raise RunBundleVerificationError("RunBundle root identity changed while verified.")
        sections = bundle.section_sha256
        result = RunBundleVerificationResult(
            valid=True,
            bundle_sha256=bundle_sha256,
            run_spec_sha256=bundle.run_spec_sha256,
            steps_sha256=sections["steps"],
            terminal_summary_sha256=sections["terminal_summary"],
            step_count=len(bundle.steps),
            selected_candidate_ids=tuple(step.selected_candidate_id for step in bundle.steps),
            bundle=bundle,
        )
        _require_ancestry_guard(ancestry_guard, label="RunBundle root")
        if member_guards:
            _require_posix_member_guards(
                root_guard,
                member_guards,
                expected=member_identities,
            )
            _close_posix_member_guards(member_guards)
            member_guards = ()
        _close_ancestry_guard(ancestry_guard)
        ancestry_guard = None
        return result
    except RunBundleVerificationError:
        if ancestry_guard is not None:
            with suppress(OSError):
                _close_ancestry_guard(ancestry_guard)
        raise
    except Exception as exc:
        if ancestry_guard is not None:
            with suppress(OSError):
                _close_ancestry_guard(ancestry_guard)
        raise RunBundleVerificationError("RunBundle strict verification failed.") from exc
    except BaseException:
        if ancestry_guard is not None:
            with suppress(OSError):
                _close_ancestry_guard(ancestry_guard)
        raise
    finally:
        if member_guards:
            with suppress(OSError):
                _close_posix_member_guards(member_guards)


def replay_run_bundle(bundle_directory: Path, destination_directory: Path) -> RunBundleReplayResult:
    """Replay policy decisions with recorded observations into fresh SQLite state."""

    try:
        verification = verify_run_bundle(bundle_directory)
    except RunBundleVerificationError as exc:
        raise RunBundleReplayError("Replay input failed RunBundle verification.") from exc

    try:
        destination = _exact_path(destination_directory, field_name="destination_directory")
    except RunBundleValidationError as exc:
        raise RunBundleReplayError("Replay destination path is invalid.") from exc
    created_destination = False
    destination_identity: tuple[int, int] | None = None
    destination_guard: _DirectoryGuard | None = None
    database_path = destination / _REPLAY_DATABASE_NAME
    temporary_database_descriptor: int | None = None
    temporary_database_path: Path | None = None
    temporary_database_identity: tuple[int, int] | None = None
    published_database_identity: tuple[int, int] | None = None
    try:
        if os.path.lexists(destination):
            _require_plain_directory(destination, "Replay destination")
            with os.scandir(destination) as scanner:
                destination_entries = list(scanner)
            if destination_entries:
                raise RunBundleReplayError("Replay destination directory must be empty.")
            destination_identity = _physical_identity(destination.lstat())
        else:
            _require_plain_directory(destination.parent, "Replay destination parent")
            destination.mkdir()
            created_destination = True
            destination_identity = _physical_identity(destination.lstat())

        if destination_identity is None:
            raise AssertionError("Replay destination identity was not captured.")
        destination_guard = _open_directory_guard(
            destination,
            expected_identity=destination_identity,
        )
        _require_directory_identity(
            destination,
            expected_identity=destination_identity,
            label="Replay destination",
        )

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{_REPLAY_DATABASE_NAME}.tmp-",
            suffix=".sqlite3",
            dir=destination,
        )
        temporary_database_descriptor = descriptor
        temporary_database_path = Path(temporary_name)
        temporary_database_identity = _physical_identity(os.fstat(descriptor))
        _require_owned_replay_database(
            temporary_database_path,
            expected_identity=temporary_database_identity,
            descriptor=temporary_database_descriptor,
        )

        bundle = verification.bundle
        run_spec = bundle.run_spec
        factory = _SUPPORTED_POLICY_FACTORIES.get(run_spec.policy_id)
        if factory is None:
            raise RunBundleReplayError(
                f"Unsupported replay policy identity: {run_spec.policy_id!r}."
            )

        completed_ids: set[str] = set()
        completed_order: list[str] = []
        replayed_steps: list[dict[str, object]] = []
        expected_history: list[CompletedWorkloadExperiment] = []
        cumulative_cost = 0.0
        with ExperimentStore(temporary_database_path) as store:
            store.init_schema()
            for recorded_step in bundle.steps:
                if run_spec.cost_budget is not None and cumulative_cost >= run_spec.cost_budget:
                    raise RunBundleReplayError(
                        "Recorded replay continues after the RunSpec cost budget is exhausted."
                    )
                selected, available_ids = factory(run_spec, frozenset(completed_ids))
                if selected.candidate_id != recorded_step.selected_candidate_id:
                    raise RunBundleReplayError(
                        f"Policy selection mismatch at step {recorded_step.step_index}."
                    )
                decision = _decision_payload(run_spec, selected.candidate_id)
                if _canonical_json_bytes(decision) != _canonical_json_bytes(
                    dict(recorded_step.decision)
                ):
                    raise RunBundleReplayError(
                        f"Decision payload mismatch at step {recorded_step.step_index}."
                    )
                rationale = _rationale_payload(available_ids, completed_order)
                if _canonical_json_bytes(rationale) != _canonical_json_bytes(
                    dict(recorded_step.rationale)
                ):
                    raise RunBundleReplayError(
                        f"Rationale payload mismatch at step {recorded_step.step_index}."
                    )

                observation_payload = recorded_step.observation
                observation = NormalizedObservation(
                    objective_value=cast(float, observation_payload["objective_value"]),
                    cost=cast(float, observation_payload["cost"]),
                )
                cumulative_cost += observation.cost
                if run_spec.cost_budget is not None and cumulative_cost > run_spec.cost_budget:
                    raise RunBundleReplayError("Recorded replay exceeds the RunSpec cost budget.")
                if cumulative_cost != recorded_step.cumulative_cost:
                    raise RunBundleReplayError(
                        f"Cumulative cost mismatch at step {recorded_step.step_index}."
                    )
                if recorded_step.belief_lineage:
                    raise RunBundleReplayError(
                        "The v1 random workload path has no applicable belief update."
                    )

                expected = CompletedWorkloadExperiment(
                    run_spec_fingerprint=run_spec.fingerprint(),
                    candidate=selected,
                    policy_id=run_spec.policy_id,
                    observation=observation,
                    created_at=_REPLAY_CREATED_AT,
                )
                persisted = store.add_workload_experiment(expected)
                if persisted != expected:
                    raise RunBundleReplayError(
                        f"Persistence mismatch at step {recorded_step.step_index}."
                    )
                expected_history.append(expected)
                completed_ids.add(selected.candidate_id)
                completed_order.append(selected.candidate_id)
                replayed_steps.append(
                    _step_payload(
                        step_index=recorded_step.step_index,
                        selected_candidate_id=selected.candidate_id,
                        decision=decision,
                        rationale=rationale,
                        observation=_observation_payload(selected.candidate_id, observation),
                        cumulative_cost=cumulative_cost,
                    )
                )

        _require_owned_replay_database(
            temporary_database_path,
            expected_identity=temporary_database_identity,
            descriptor=temporary_database_descriptor,
        )

        replayed_steps_sha256 = _sha256(_canonical_json_bytes(replayed_steps))
        recorded_summary = dict(bundle.terminal_summary)
        terminal_summary = _terminal_summary_payload(
            replayed_steps,
            stop_reason=cast(StopReason, recorded_summary["stop_reason"]),
            steps_sha256=replayed_steps_sha256,
        )
        if _canonical_json_bytes(terminal_summary) != _canonical_json_bytes(recorded_summary):
            raise RunBundleReplayError("Terminal summary mismatch after replay.")

        with ExperimentStore(temporary_database_path) as reopened:
            reopened.init_schema()
            reopened_history = reopened.list_workload_experiments(run_spec.fingerprint())
            integrity = reopened._connection().execute("PRAGMA integrity_check").fetchone()
            if reopened.schema_version() != SCHEMA_VERSION:
                raise RunBundleReplayError("Replayed SQLite schema version is inconsistent.")
            if reopened_history != expected_history:
                raise RunBundleReplayError("Reopened SQLite history does not match replay state.")
            if integrity is None or str(integrity[0]) != "ok":
                raise RunBundleReplayError("Replayed SQLite integrity check failed.")

        _require_owned_replay_database(
            temporary_database_path,
            expected_identity=temporary_database_identity,
            descriptor=temporary_database_descriptor,
        )
        _require_directory_identity(
            destination,
            expected_identity=destination_identity,
            label="Replay destination",
        )
        os.link(temporary_database_path, database_path, follow_symlinks=False)
        published_database_identity = _physical_identity(database_path.lstat())
        if published_database_identity != temporary_database_identity:
            raise RunBundleReplayError("Replay publication changed database identity.")
        _require_owned_replay_database(
            temporary_database_path,
            expected_identity=temporary_database_identity,
            descriptor=temporary_database_descriptor,
        )
        _require_owned_replay_database(
            database_path,
            expected_identity=temporary_database_identity,
            descriptor=temporary_database_descriptor,
        )
        _require_directory_identity(
            destination,
            expected_identity=destination_identity,
            label="Replay destination",
        )
        published_connection = sqlite3.connect(
            f"{database_path.as_uri()}?mode=ro&immutable=1",
            uri=True,
        )
        published_connection.row_factory = sqlite3.Row
        published = ExperimentStore(database_path)
        published.connection = published_connection
        try:
            _require_owned_replay_database(
                temporary_database_path,
                expected_identity=temporary_database_identity,
                descriptor=temporary_database_descriptor,
            )
            _require_owned_replay_database(
                database_path,
                expected_identity=temporary_database_identity,
                descriptor=temporary_database_descriptor,
            )
            published_history = published.list_workload_experiments(run_spec.fingerprint())
            published_integrity = (
                published._connection().execute("PRAGMA integrity_check").fetchone()
            )
            if published.schema_version() != SCHEMA_VERSION:
                raise RunBundleReplayError("Published replay schema version is inconsistent.")
            if published_history != expected_history:
                raise RunBundleReplayError("Published replay history does not match replay state.")
            if published_integrity is None or str(published_integrity[0]) != "ok":
                raise RunBundleReplayError("Published replay SQLite integrity check failed.")
        finally:
            published_connection.close()
            published.connection = None

        _require_owned_replay_database(
            temporary_database_path,
            expected_identity=temporary_database_identity,
            descriptor=temporary_database_descriptor,
        )
        _require_owned_replay_database(
            database_path,
            expected_identity=temporary_database_identity,
            descriptor=temporary_database_descriptor,
        )

        final_verification = verify_run_bundle(bundle_directory)
        if final_verification.bundle_sha256 != verification.bundle_sha256:
            raise RunBundleReplayError("Replay modified the source RunBundle.")
        history_sha256 = _sha256(
            _canonical_json_bytes([_history_payload(record) for record in expected_history])
        )
        result = RunBundleReplayResult(
            replay_contract=_REPLAY_CONTRACT,
            bundle_sha256=verification.bundle_sha256,
            run_spec_sha256=verification.run_spec_sha256,
            steps_sha256=verification.steps_sha256,
            terminal_summary_sha256=verification.terminal_summary_sha256,
            history_sha256=history_sha256,
            step_count=verification.step_count,
            selected_candidate_ids=verification.selected_candidate_ids,
            sqlite_schema_version=SCHEMA_VERSION,
            equivalent=True,
        )
        _require_owned_replay_database(
            temporary_database_path,
            expected_identity=temporary_database_identity,
            descriptor=temporary_database_descriptor,
        )
        _require_owned_replay_database(
            database_path,
            expected_identity=temporary_database_identity,
            descriptor=temporary_database_descriptor,
        )
        os.close(temporary_database_descriptor)
        temporary_database_descriptor = None
        if not _remove_owned_replay_database(
            temporary_database_path,
            expected_identity=temporary_database_identity,
        ):
            raise RunBundleReplayError("Replay temporary database could not be removed safely.")
        if os.path.lexists(temporary_database_path):
            raise RunBundleReplayError("Replay temporary database path remained occupied.")
        temporary_database_path = None
        _require_replay_database_identity(
            database_path,
            expected_identity=temporary_database_identity,
        )
        _close_directory_guard(destination_guard)
        destination_guard = None
        return result
    except BaseException as exc:
        if temporary_database_descriptor is not None:
            with suppress(OSError):
                os.close(temporary_database_descriptor)
            temporary_database_descriptor = None
        if temporary_database_path is not None and temporary_database_identity is not None:
            _remove_owned_replay_database(
                temporary_database_path, expected_identity=temporary_database_identity
            )
        if temporary_database_identity is not None:
            _remove_owned_replay_database(
                database_path,
                expected_identity=temporary_database_identity,
            )
        if destination_guard is not None:
            with suppress(OSError):
                _close_directory_guard(destination_guard)
            destination_guard = None
        if created_destination and destination_identity is not None:
            _remove_owned_empty_directory(
                destination,
                expected_identity=destination_identity,
            )
        if isinstance(exc, RunBundleReplayError):
            raise
        if isinstance(exc, Exception):
            raise RunBundleReplayError("Recorded-observation replay failed.") from exc
        raise


def _build_run_bundle(trace: CompletedWorkloadRunTrace) -> RunBundle:
    if type(trace) is not CompletedWorkloadRunTrace:
        raise RunBundleValidationError("trace must be an exact CompletedWorkloadRunTrace.")
    steps = [step.to_payload() for step in trace.steps]
    run_spec_bytes = trace.run_spec.to_canonical_bytes()
    run_spec_payload = _decode_canonical_document(run_spec_bytes)
    if type(run_spec_payload) is not dict:
        raise AssertionError("Canonical RunSpec is not a JSON object.")
    run_spec_sha256 = trace.run_spec.fingerprint()
    steps_sha256 = _sha256(_canonical_json_bytes(steps))
    terminal_summary = _terminal_summary_payload(
        steps, stop_reason=trace.stop_reason, steps_sha256=steps_sha256
    )
    _validate_stop_reason(
        trace.stop_reason,
        completed_steps=len(steps),
        total_cost=cast(float, terminal_summary["total_cost"]),
        run_spec=trace.run_spec,
    )
    section_sha256 = {
        "run_spec": run_spec_sha256,
        "steps": steps_sha256,
        "terminal_summary": _sha256(_canonical_json_bytes(terminal_summary)),
    }
    payload: dict[str, object] = {
        "schema_version": _SCHEMA,
        "artifact_role": _ARTIFACT_ROLE,
        "replay_contract": _REPLAY_CONTRACT,
        "run_spec": run_spec_payload,
        "run_spec_sha256": run_spec_sha256,
        "producer": _producer_payload(),
        "steps": steps,
        "terminal_summary": terminal_summary,
        "section_sha256": section_sha256,
        "root_member_count": 2,
    }
    encoded = _canonical_json_bytes(payload)
    return _validated_bundle(payload, encoded)


def _run_bundle_step_from_completion(
    *,
    run_spec: RunSpec,
    record: CompletedWorkloadExperiment,
    completed_candidate_ids: Sequence[str],
    cumulative_cost: float,
) -> RunBundleStep:
    """Capture the exact current random-policy semantics around one completion."""

    if type(run_spec) is not RunSpec or type(record) is not CompletedWorkloadExperiment:
        raise RunBundleValidationError("Trace capture requires exact RunSpec and completion types.")
    if type(completed_candidate_ids) not in (list, tuple) or any(
        type(candidate_id) is not str for candidate_id in completed_candidate_ids
    ):
        raise RunBundleValidationError("Trace capture candidate history must be explicit strings.")
    if type(cumulative_cost) is not float or not math.isfinite(cumulative_cost):
        raise RunBundleValidationError("Trace capture cumulative cost must be an exact float.")
    if run_spec.cost_budget is not None and cumulative_cost >= run_spec.cost_budget:
        raise RunBundleValidationError(
            "Trace capture continues after its cost budget is exhausted."
        )
    candidate_by_id = {candidate.candidate_id: candidate for candidate in run_spec.candidates}
    expected_candidate = candidate_by_id.get(record.candidate.candidate_id)
    if (
        record.run_spec_fingerprint != run_spec.fingerprint()
        or record.policy_id != run_spec.policy_id
        or record.candidate != expected_candidate
    ):
        raise RunBundleValidationError("Completed record is inconsistent with its RunSpec.")
    factory = _SUPPORTED_POLICY_FACTORIES.get(run_spec.policy_id)
    if factory is None:
        raise RunBundleValidationError(
            f"Unsupported trace policy identity: {run_spec.policy_id!r}."
        )
    selected, available_ids = factory(run_spec, frozenset(completed_candidate_ids))
    if selected != record.candidate:
        raise RunBundleValidationError("Completed record selection diverges from the policy.")
    observation = NormalizedObservation(
        record.observation.objective_value,
        record.observation.cost,
    )
    next_cumulative_cost = cumulative_cost + observation.cost
    if not math.isfinite(next_cumulative_cost):
        raise RunBundleValidationError("Trace cumulative cost must remain finite.")
    if run_spec.cost_budget is not None and next_cumulative_cost > run_spec.cost_budget:
        raise RunBundleValidationError("Completed record exceeds its cost budget.")
    return RunBundleStep(
        step_index=len(completed_candidate_ids),
        selected_candidate_id=selected.candidate_id,
        decision=_decision_payload(run_spec, selected.candidate_id),
        rationale=_rationale_payload(available_ids, completed_candidate_ids),
        observation=_observation_payload(selected.candidate_id, observation),
        belief_lineage=[],
        cumulative_cost=next_cumulative_cost,
    )


def _validated_bundle(payload: object, encoded: bytes) -> RunBundle:
    top = _required_object(payload, _TOP_LEVEL_KEYS, "RunBundle")
    _reject_hidden_truth(top)
    _reject_absolute_paths(top, field_name="RunBundle")
    if top["schema_version"] != _SCHEMA:
        raise RunBundleValidationError(f"Unsupported RunBundle schema: {top['schema_version']!r}.")
    if top["artifact_role"] != _ARTIFACT_ROLE:
        raise RunBundleValidationError("RunBundle artifact role is invalid.")
    if top["replay_contract"] != _REPLAY_CONTRACT:
        raise RunBundleValidationError("RunBundle replay contract is invalid.")
    if type(top["root_member_count"]) is not int or top["root_member_count"] != 2:
        raise RunBundleValidationError("RunBundle root_member_count must be exactly 2.")

    producer = _required_object(top["producer"], _PRODUCER_KEYS, "producer")
    for key, value in producer.items():
        if type(value) is not str or not value:
            raise RunBundleValidationError(f"producer.{key} must be a nonempty string.")

    run_spec_payload = _required_object(top["run_spec"], None, "run_spec")
    run_spec_bytes = _canonical_json_bytes(run_spec_payload)
    try:
        run_spec = RunSpec.from_canonical_bytes(run_spec_bytes)
    except (TypeError, ValueError) as exc:
        raise RunBundleValidationError("Embedded RunSpec is invalid.") from exc
    run_spec_sha256 = _required_digest(top["run_spec_sha256"], "run_spec_sha256")
    if run_spec_sha256 != run_spec.fingerprint():
        raise RunBundleValidationError("Embedded RunSpec SHA-256 does not match.")

    section_sha256 = _required_object(top["section_sha256"], _SECTION_KEYS, "section_sha256")
    normalized_sections = {
        key: _required_digest(section_sha256[key], f"section_sha256.{key}")
        for key in sorted(_SECTION_KEYS)
    }
    if normalized_sections["run_spec"] != run_spec_sha256:
        raise RunBundleValidationError("RunSpec section SHA-256 does not match.")

    raw_steps = top["steps"]
    if type(raw_steps) is not list:
        raise RunBundleValidationError("RunBundle steps must be a JSON array.")
    steps: list[RunBundleStep] = []
    completed_ids: list[str] = []
    previous_cost = 0.0
    for expected_index, raw_step in enumerate(raw_steps):
        step = _validate_step(
            raw_step,
            expected_index=expected_index,
            run_spec=run_spec,
            completed_candidate_ids=tuple(completed_ids),
            previous_cost=previous_cost,
        )
        steps.append(step)
        completed_ids.append(step.selected_candidate_id)
        previous_cost = step.cumulative_cost
    if len(steps) > run_spec.experiment_count_budget:
        raise RunBundleValidationError("RunBundle steps exceed the RunSpec budget.")
    computed_steps_sha256 = _sha256(_canonical_json_bytes(raw_steps))
    if normalized_sections["steps"] != computed_steps_sha256:
        raise RunBundleValidationError("Steps section SHA-256 does not match.")

    terminal_summary = _validate_terminal_summary(
        top["terminal_summary"],
        steps=steps,
        run_spec=run_spec,
        steps_sha256=computed_steps_sha256,
    )
    computed_terminal_sha256 = _sha256(_canonical_json_bytes(terminal_summary))
    if normalized_sections["terminal_summary"] != computed_terminal_sha256:
        raise RunBundleValidationError("Terminal-summary section SHA-256 does not match.")
    if _canonical_json_bytes(top) != encoded:
        raise RunBundleValidationError("RunBundle document is not exact canonical JSON.")

    return RunBundle._from_validated(
        run_spec=run_spec,
        run_spec_sha256=run_spec_sha256,
        producer=producer,
        steps=steps,
        terminal_summary=terminal_summary,
        section_sha256=normalized_sections,
        canonical_bytes=encoded,
    )


def _validate_step(
    value: object,
    *,
    expected_index: int,
    run_spec: RunSpec,
    completed_candidate_ids: tuple[str, ...],
    previous_cost: float,
) -> RunBundleStep:
    step = _required_object(value, _STEP_KEYS, f"steps[{expected_index}]")
    if run_spec.cost_budget is not None and previous_cost >= run_spec.cost_budget:
        raise RunBundleValidationError(
            "RunBundle continues after the RunSpec cost budget is exhausted."
        )
    if type(step["step_index"]) is not int or step["step_index"] != expected_index:
        raise RunBundleValidationError("RunBundle step indices must start at 0 and be contiguous.")
    candidate_id = _required_nonempty_string(
        step["selected_candidate_id"], f"steps[{expected_index}].selected_candidate_id"
    )
    candidate_ids = tuple(candidate.candidate_id for candidate in run_spec.candidates)
    if candidate_id not in candidate_ids:
        raise RunBundleValidationError("RunBundle step selects an unknown candidate.")
    completed_ids = frozenset(completed_candidate_ids)
    if candidate_id in completed_ids:
        raise RunBundleValidationError("RunBundle selects a candidate more than once.")
    factory = _SUPPORTED_POLICY_FACTORIES.get(run_spec.policy_id)
    if factory is None:
        raise RunBundleValidationError(
            f"Unsupported bundle policy identity: {run_spec.policy_id!r}."
        )
    expected_candidate, policy_available_ids = factory(run_spec, completed_ids)
    if candidate_id != expected_candidate.candidate_id:
        raise RunBundleValidationError(
            "RunBundle selected-candidate sequence diverges from the policy."
        )

    decision = _required_object(step["decision"], _DECISION_KEYS, "decision")
    if decision["selected_candidate_id"] != candidate_id:
        raise RunBundleValidationError("Decision candidate does not match the selected candidate.")
    if decision["policy_id"] != run_spec.policy_id:
        raise RunBundleValidationError("Decision policy does not match the RunSpec.")
    if decision["policy_config"] != dict(run_spec.policy_config):
        raise RunBundleValidationError("Decision policy configuration does not match RunSpec.")
    if decision["policy_seed"] != run_spec.policy_seed:
        raise RunBundleValidationError("Decision policy seed does not match RunSpec.")

    rationale = _required_object(step["rationale"], _RATIONALE_KEYS, "rationale")
    available_ids_value = rationale["available_candidate_ids"]
    if type(available_ids_value) is not list or any(
        type(item) is not str for item in available_ids_value
    ):
        raise RunBundleValidationError("Rationale available candidates must be a string array.")
    expected_available = list(policy_available_ids)
    if available_ids_value != expected_available:
        raise RunBundleValidationError("RunBundle selected-candidate sequence is inconsistent.")
    if rationale["completed_candidate_ids"] != list(completed_candidate_ids):
        raise RunBundleValidationError("Rationale completed candidates are inconsistent.")
    if rationale["selection_rule"] != _SELECTION_RULE:
        raise RunBundleValidationError("Rationale selection rule is unsupported.")

    observation = _required_object(step["observation"], _OBSERVATION_KEYS, "observation")
    if observation["candidate_id"] != candidate_id:
        raise RunBundleValidationError("Observation candidate does not match the decision.")
    try:
        normalized_observation = NormalizedObservation(
            objective_value=cast(float, observation["objective_value"]),
            cost=cast(float, observation["cost"]),
        )
    except (TypeError, ValueError) as exc:
        raise RunBundleValidationError("Recorded observation is invalid.") from exc
    if _canonical_json_bytes(observation) != _canonical_json_bytes(
        _observation_payload(candidate_id, normalized_observation)
    ):
        raise RunBundleValidationError(
            "Recorded observation is not the exact normalized public payload."
        )

    belief_lineage = step["belief_lineage"]
    if type(belief_lineage) is not list:
        raise RunBundleValidationError("belief_lineage must be a JSON array.")
    if belief_lineage:
        raise RunBundleValidationError(
            "RunSpec v1 random replay has no applicable belief-update lineage."
        )
    raw_cumulative_cost = step["cumulative_cost"]
    cumulative_cost = _finite_nonnegative_number(
        raw_cumulative_cost, f"steps[{expected_index}].cumulative_cost"
    )
    if (
        type(raw_cumulative_cost) is not float
        or raw_cumulative_cost != cumulative_cost
        or (raw_cumulative_cost == 0.0 and math.copysign(1.0, raw_cumulative_cost) < 0.0)
    ):
        raise RunBundleValidationError("RunBundle cumulative cost must be an exact float.")
    expected_cost = previous_cost + normalized_observation.cost
    if not math.isfinite(expected_cost) or cumulative_cost != expected_cost:
        raise RunBundleValidationError("RunBundle cumulative cost is inconsistent or decreasing.")
    if run_spec.cost_budget is not None and cumulative_cost > run_spec.cost_budget:
        raise RunBundleValidationError("RunBundle exceeds the RunSpec cost budget.")

    return RunBundleStep(
        step_index=expected_index,
        selected_candidate_id=candidate_id,
        decision=decision,
        rationale=rationale,
        observation=observation,
        belief_lineage=cast(list[dict[str, object]], belief_lineage),
        cumulative_cost=cumulative_cost,
    )


def _validate_terminal_summary(
    value: object,
    *,
    steps: Sequence[RunBundleStep],
    run_spec: RunSpec,
    steps_sha256: str,
) -> dict[str, object]:
    summary = _required_object(value, _TERMINAL_KEYS, "terminal_summary")
    if type(summary["completed_steps"]) is not int or summary["completed_steps"] != len(steps):
        raise RunBundleValidationError("Terminal completed_steps does not match steps.")
    selected_ids = [step.selected_candidate_id for step in steps]
    if summary["selected_candidate_ids"] != selected_ids:
        raise RunBundleValidationError("Terminal selected-candidate sequence is inconsistent.")
    expected_total = steps[-1].cumulative_cost if steps else 0.0
    raw_total_cost = summary["total_cost"]
    total_cost = _finite_nonnegative_number(raw_total_cost, "terminal_summary.total_cost")
    if (
        type(raw_total_cost) is not float
        or raw_total_cost != total_cost
        or (raw_total_cost == 0.0 and math.copysign(1.0, raw_total_cost) < 0.0)
    ):
        raise RunBundleValidationError("Terminal total_cost must be an exact float.")
    if total_cost != expected_total:
        raise RunBundleValidationError("Terminal total_cost does not match steps.")
    stop_reason = _required_nonempty_string(summary["stop_reason"], "terminal_summary.stop_reason")
    if stop_reason not in _STOP_REASONS:
        raise RunBundleValidationError("Terminal stop_reason is unsupported.")
    _validate_stop_reason(
        cast(StopReason, stop_reason),
        completed_steps=len(steps),
        total_cost=total_cost,
        run_spec=run_spec,
    )
    if summary["final_belief_fingerprint"] is not None:
        raise RunBundleValidationError(
            "RunSpec v1 random replay must have a null final belief fingerprint."
        )
    history_hash = _required_digest(
        summary["decision_history_sha256"], "terminal_summary.decision_history_sha256"
    )
    if history_hash != steps_sha256:
        raise RunBundleValidationError("Terminal decision-history SHA-256 does not match steps.")
    return summary


def _validate_stop_reason(
    stop_reason: StopReason,
    *,
    completed_steps: int,
    total_cost: float,
    run_spec: RunSpec,
) -> None:
    if (
        stop_reason == "experiment_budget_exhausted"
        and completed_steps != run_spec.experiment_count_budget
    ):
        raise RunBundleValidationError(
            "experiment_budget_exhausted requires the exact experiment budget."
        )
    if stop_reason == "cost_budget_exhausted" and (
        run_spec.cost_budget is None or total_cost < run_spec.cost_budget
    ):
        raise RunBundleValidationError("cost_budget_exhausted requires a reached cost budget.")
    if stop_reason == "candidate_space_exhausted" and completed_steps != len(run_spec.candidates):
        raise RunBundleValidationError(
            "candidate_space_exhausted requires every candidate to be completed."
        )


def _decision_payload(run_spec: RunSpec, candidate_id: str) -> dict[str, object]:
    return {
        "policy_config": dict(run_spec.policy_config),
        "policy_id": run_spec.policy_id,
        "policy_seed": run_spec.policy_seed,
        "selected_candidate_id": candidate_id,
    }


def _rationale_payload(
    available_candidate_ids: Sequence[str], completed_candidate_ids: Sequence[str]
) -> dict[str, object]:
    return {
        "available_candidate_ids": list(available_candidate_ids),
        "completed_candidate_ids": list(completed_candidate_ids),
        "selection_rule": _SELECTION_RULE,
    }


def _observation_payload(
    candidate_id: str, observation: NormalizedObservation
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "objective_value": observation.objective_value,
        "cost": observation.cost,
    }


def _step_payload(
    *,
    step_index: int,
    selected_candidate_id: str,
    decision: Mapping[str, object],
    rationale: Mapping[str, object],
    observation: Mapping[str, object],
    cumulative_cost: float,
) -> dict[str, object]:
    return {
        "step_index": step_index,
        "selected_candidate_id": selected_candidate_id,
        "decision": dict(decision),
        "rationale": dict(rationale),
        "observation": dict(observation),
        "belief_lineage": [],
        "cumulative_cost": cumulative_cost,
    }


def _terminal_summary_payload(
    steps: Sequence[Mapping[str, object]],
    *,
    stop_reason: StopReason,
    steps_sha256: str,
) -> dict[str, object]:
    return {
        "completed_steps": len(steps),
        "selected_candidate_ids": [step["selected_candidate_id"] for step in steps],
        "total_cost": steps[-1]["cumulative_cost"] if steps else 0.0,
        "stop_reason": stop_reason,
        "final_belief_fingerprint": None,
        "decision_history_sha256": steps_sha256,
    }


def _producer_payload() -> dict[str, object]:
    try:
        distribution = metadata.distribution(_DIST_NAME)
        package_name = distribution.metadata["Name"]
        package_version = distribution.version
    except (KeyError, metadata.PackageNotFoundError) as exc:
        raise RunBundleValidationError(
            "Installed package metadata is required to export a RunBundle."
        ) from exc
    if package_name is None:
        raise RunBundleValidationError("Installed package name metadata is missing.")
    return {
        "package_name": package_name,
        "package_version": package_version,
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
    }


def _history_payload(record: CompletedWorkloadExperiment) -> dict[str, object]:
    return {
        "run_spec_sha256": record.run_spec_fingerprint,
        "candidate_id": record.candidate.candidate_id,
        "parameters": dict(record.candidate.parameters),
        "policy_id": record.policy_id,
        "observation": _observation_payload(record.candidate.candidate_id, record.observation),
    }


def _decode_canonical_document(encoded: bytes) -> object:
    if type(encoded) is not bytes:
        raise RunBundleValidationError("Canonical JSON input must be exact bytes.")
    if encoded.startswith(b"\xef\xbb\xbf") or b"\r" in encoded:
        raise RunBundleValidationError("Canonical JSON forbids BOM and CR bytes.")
    if not encoded.endswith(b"\n") or encoded.endswith(b"\n\n"):
        raise RunBundleValidationError("Canonical JSON requires exactly one final LF.")
    try:
        text = encoded.decode("utf-8")
        payload = cast(
            object,
            json.loads(
                text,
                object_pairs_hook=_object_without_duplicate_keys,
                parse_constant=_reject_nonfinite_json_constant,
                parse_float=_parse_finite_float,
            ),
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise RunBundleValidationError("Document is not strict finite UTF-8 JSON.") from exc
    if _canonical_json_bytes(payload) != encoded:
        raise RunBundleValidationError("Document is not exact canonical JSON.")
    return payload


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("Non-finite JSON numbers are forbidden.")
    return parsed


def _required_object(
    value: object,
    expected_keys: frozenset[str] | None,
    field_name: str,
) -> dict[str, object]:
    if type(value) is not dict:
        raise RunBundleValidationError(f"{field_name} must be a JSON object.")
    result = cast(dict[str, object], value)
    if expected_keys is not None and frozenset(result) != expected_keys:
        missing = sorted(expected_keys.difference(result))
        unknown = sorted(set(result).difference(expected_keys))
        raise RunBundleValidationError(
            f"{field_name} fields are not exact; missing={missing!r}, unknown={unknown!r}."
        )
    return result


def _required_nonempty_string(value: object, field_name: str) -> str:
    if type(value) is not str or not value:
        raise RunBundleValidationError(f"{field_name} must be a nonempty string.")
    return value


def _required_digest(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RunBundleValidationError(
            f"{field_name} must be exactly 64 lowercase SHA-256 hex characters."
        )
    return value


def _finite_nonnegative_number(value: object, field_name: str) -> float:
    if type(value) not in (int, float):
        raise RunBundleValidationError(f"{field_name} must be a finite number.")
    normalized = float(cast(int | float, value))
    if not math.isfinite(normalized) or normalized < 0.0:
        raise RunBundleValidationError(f"{field_name} must be finite and nonnegative.")
    return 0.0 if normalized == 0.0 else normalized


def _reject_hidden_truth(value: object) -> None:
    if type(value) is dict:
        for key, item in cast(dict[str, object], value).items():
            normalized_key = "_".join(part for part in _key_parts(key.casefold()) if part)
            if normalized_key in _HIDDEN_TRUTH_KEYS:
                raise RunBundleValidationError(
                    f"RunBundle contains forbidden hidden-truth field {key!r}."
                )
            _reject_hidden_truth(item)
    elif type(value) is list:
        for item in cast(list[object], value):
            _reject_hidden_truth(item)


def _key_parts(value: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    for character in value:
        if character.isalnum():
            current.append(character)
        elif current:
            parts.append("".join(current))
            current = []
    if current:
        parts.append("".join(current))
    return parts


def _reject_absolute_path(value: str, *, field_name: str) -> None:
    windows_path = PureWindowsPath(value)
    if (
        value.casefold().startswith("file:")
        or windows_path.is_absolute()
        or bool(windows_path.root)
        or bool(windows_path.drive)
        or PurePosixPath(value).is_absolute()
    ):
        raise RunBundleValidationError(f"{field_name} must not contain an absolute path.")


def _reject_absolute_paths(value: object, *, field_name: str) -> None:
    if type(value) is str:
        _reject_absolute_path(value, field_name=field_name)
    elif type(value) is dict:
        for key, item in cast(dict[str, object], value).items():
            _reject_absolute_path(key, field_name=f"{field_name} key")
            _reject_absolute_paths(item, field_name=f"{field_name}.{key}")
    elif type(value) is list:
        for index, item in enumerate(cast(list[object], value)):
            _reject_absolute_paths(item, field_name=f"{field_name}[{index}]")


def _json_object_copy(encoded: str) -> dict[str, object]:
    value = cast(object, json.loads(encoded))
    if type(value) is not dict:
        raise AssertionError("Stored canonical JSON is not an object.")
    return cast(dict[str, object], value)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _physical_identity(status: os.stat_result) -> tuple[int, int]:
    return status.st_dev, status.st_ino


def _exact_path(value: Path, *, field_name: str) -> Path:
    if not isinstance(value, Path):
        raise RunBundleValidationError(f"{field_name} must be a pathlib.Path.")
    return Path(os.path.abspath(value))


def _is_reparse(path: Path, status: os.stat_result | None = None) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and cast(Callable[[], bool], is_junction)():
        return True
    actual_status = path.lstat() if status is None else status
    reparse_flag = cast(int, getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    attributes = cast(int, getattr(actual_status, "st_file_attributes", 0))
    return bool(reparse_flag and attributes & reparse_flag)


def _require_plain_directory(path: Path, label: str) -> None:
    if not os.path.lexists(path):
        raise RunBundleValidationError(f"{label} does not exist.")
    _reject_reparse_ancestry(path, label=label)
    status = path.lstat()
    if not stat.S_ISDIR(status.st_mode) or _is_reparse(path, status):
        raise RunBundleValidationError(f"{label} must be an ordinary non-reparse directory.")


def _reject_reparse_ancestry(path: Path, *, label: str) -> None:
    absolute = Path(os.path.abspath(path))
    chain = tuple(reversed(absolute.parents)) + (absolute,)
    for component in chain:
        if not os.path.lexists(component):
            continue
        status = component.lstat()
        if _is_reparse(component, status):
            raise RunBundleValidationError(
                f"{label} must not traverse a symlink, junction, or reparse ancestor."
            )


def _require_directory_identity(
    path: Path,
    *,
    expected_identity: tuple[int, int],
    label: str,
) -> None:
    _require_plain_directory(path, label)
    if _physical_identity(path.lstat()) != expected_identity:
        raise RunBundleValidationError(f"{label} identity changed during the operation.")


@dataclass(frozen=True, slots=True)
class _DirectoryGuard:
    handle: int
    windows: bool


@dataclass(frozen=True, slots=True)
class _PosixMemberGuard:
    name: str
    root_descriptor: int
    descriptor: int
    identity: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _GuardedAncestryComponent:
    path: Path
    identity: tuple[int, int]
    guard: _DirectoryGuard


@dataclass(frozen=True, slots=True)
class _AncestryGuard:
    components: tuple[_GuardedAncestryComponent, ...]


class _WinDLLFactory(_Protocol):
    def __call__(self, name: str, *, use_last_error: bool) -> _CDLL: ...


def _require_windows_api() -> None:
    if os.name != "nt":
        raise OSError(_errno.ENOSYS, "Windows APIs are unavailable on this platform.")


def _windows_kernel32() -> _CDLL:
    _require_windows_api()
    import ctypes

    win_dll = getattr(ctypes, "WinDLL", None)
    if not callable(win_dll):
        raise OSError(_errno.ENOSYS, "ctypes.WinDLL is unavailable on Windows.")
    return cast(_WinDLLFactory, win_dll)("kernel32", use_last_error=True)


def _windows_last_error() -> int:
    _require_windows_api()
    import ctypes

    get_last_error = getattr(ctypes, "get_last_error", None)
    if not callable(get_last_error):
        raise OSError(_errno.ENOSYS, "ctypes.get_last_error is unavailable on Windows.")
    return cast(Callable[[], int], get_last_error)()


def _windows_error(error_code: int) -> OSError:
    _require_windows_api()
    import ctypes

    win_error = getattr(ctypes, "WinError", None)
    if not callable(win_error):
        raise OSError(_errno.ENOSYS, "ctypes.WinError is unavailable on Windows.")
    return cast(Callable[[int], OSError], win_error)(error_code)


def _open_windows_directory_handle(
    path: Path,
    *,
    desired_access: int,
    share_mode: int,
) -> int:
    import ctypes
    from ctypes import wintypes

    kernel32 = _windows_kernel32()
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path),
        desired_access,
        share_mode,
        None,
        3,
        0x02000000 | 0x00200000,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle is None or handle == invalid_handle:
        raise _windows_error(_windows_last_error())
    return cast(int, handle)


def _windows_directory_handle_identity(handle: int) -> tuple[int, int]:
    identity, attributes, _ = _windows_handle_information(handle)
    if not attributes & 0x10 or attributes & 0x400:
        raise RunBundleValidationError("Guarded path is not an ordinary directory.")
    return identity


def _windows_handle_information(handle: int) -> tuple[tuple[int, int], int, int]:
    import ctypes
    from ctypes import wintypes

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("file_attributes", wintypes.DWORD),
            ("creation_time", wintypes.FILETIME),
            ("last_access_time", wintypes.FILETIME),
            ("last_write_time", wintypes.FILETIME),
            ("volume_serial_number", wintypes.DWORD),
            ("file_size_high", wintypes.DWORD),
            ("file_size_low", wintypes.DWORD),
            ("number_of_links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        ]

    kernel32 = _windows_kernel32()
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ByHandleFileInformation)]
    get_information.restype = wintypes.BOOL
    information = _ByHandleFileInformation()
    if not get_information(handle, ctypes.byref(information)):
        raise _windows_error(_windows_last_error())
    file_index = (information.file_index_high << 32) | information.file_index_low
    return (
        (information.volume_serial_number, file_index),
        information.file_attributes,
        information.number_of_links,
    )


def _windows_identity_matches(
    native_identity: tuple[int, int], stat_identity: tuple[int, int]
) -> bool:
    return (
        native_identity[0] == stat_identity[0] & 0xFFFFFFFF
        and native_identity[1] == stat_identity[1]
    )


def _close_windows_handle(handle: int) -> None:
    from ctypes import wintypes

    kernel32 = _windows_kernel32()
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    if not close_handle(handle):
        raise _windows_error(_windows_last_error())


def _open_directory_guard(
    path: Path,
    *,
    expected_identity: tuple[int, int],
    delete_access: bool = False,
    block_rename: bool = False,
) -> _DirectoryGuard:
    if os.name == "nt":
        requested_delete_access = delete_access or block_rename
        handle = _open_windows_directory_handle(
            path,
            desired_access=0x80 | (0x00010000 if requested_delete_access else 0),
            share_mode=0x1 | 0x2 | (0x4 if delete_access and not block_rename else 0),
        )
        try:
            native_identity = _windows_directory_handle_identity(handle)
            if not _windows_identity_matches(native_identity, expected_identity):
                raise RunBundleValidationError("Guarded directory identity is inconsistent.")
        except BaseException:
            with suppress(OSError):
                _close_windows_handle(handle)
            raise
        return _DirectoryGuard(handle=handle, windows=True)

    flags = os.O_RDONLY | cast(int, getattr(os, "O_DIRECTORY", 0))
    flags |= cast(int, getattr(os, "O_NOFOLLOW", 0))
    descriptor = os.open(path, flags)
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISDIR(status.st_mode) or _physical_identity(status) != expected_identity:
            raise RunBundleValidationError("Guarded directory identity is inconsistent.")
    except BaseException:
        with suppress(OSError):
            os.close(descriptor)
        raise
    return _DirectoryGuard(handle=descriptor, windows=False)


def _close_directory_guard(guard: _DirectoryGuard) -> None:
    if guard.windows:
        _close_windows_handle(guard.handle)
    else:
        os.close(guard.handle)


def _open_ancestry_guard(path: Path, *, label: str) -> _AncestryGuard:
    absolute = Path(os.path.abspath(path))
    chain = tuple(reversed(absolute.parents)) + (absolute,)
    components: list[_GuardedAncestryComponent] = []
    try:
        for component in chain:
            status = component.lstat()
            if not stat.S_ISDIR(status.st_mode) or _is_reparse(component, status):
                raise RunBundleVerificationError(
                    f"{label} must not traverse a symlink, junction, or reparse ancestor."
                )
            identity = _physical_identity(status)
            try:
                guard = _open_directory_guard(
                    component,
                    expected_identity=identity,
                    block_rename=os.name == "nt",
                )
            except OSError as exc:
                if os.name != "nt" or getattr(exc, "winerror", None) not in {5, 32, 33}:
                    raise
                guard = _open_directory_guard(component, expected_identity=identity)
            after = component.lstat()
            if (
                not stat.S_ISDIR(after.st_mode)
                or _is_reparse(component, after)
                or _physical_identity(after) != identity
            ):
                _close_directory_guard(guard)
                raise RunBundleVerificationError(f"{label} ancestry changed while guarded.")
            components.append(
                _GuardedAncestryComponent(
                    path=component,
                    identity=identity,
                    guard=guard,
                )
            )
        result = _AncestryGuard(components=tuple(components))
        _require_ancestry_guard(result, label=label)
        return result
    except BaseException:
        for guarded in reversed(components):
            with suppress(OSError):
                _close_directory_guard(guarded.guard)
        raise


def _require_ancestry_guard(guard: _AncestryGuard, *, label: str) -> None:
    for component in guard.components:
        status = component.path.lstat()
        if (
            not stat.S_ISDIR(status.st_mode)
            or _is_reparse(component.path, status)
            or _physical_identity(status) != component.identity
        ):
            raise RunBundleVerificationError(f"{label} ancestry changed while verified.")
        if component.guard.windows:
            native_identity = _windows_directory_handle_identity(component.guard.handle)
            if not _windows_identity_matches(native_identity, component.identity):
                raise RunBundleVerificationError(f"{label} handle identity changed while verified.")
        else:
            opened = os.fstat(component.guard.handle)
            if not stat.S_ISDIR(opened.st_mode) or _physical_identity(opened) != component.identity:
                raise RunBundleVerificationError(f"{label} handle identity changed while verified.")


def _close_ancestry_guard(guard: _AncestryGuard) -> None:
    first_error: OSError | None = None
    for component in reversed(guard.components):
        try:
            _close_directory_guard(component.guard)
        except OSError as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error


def _open_posix_member_guards(
    root_guard: _DirectoryGuard,
) -> tuple[_PosixMemberGuard, ...]:
    if root_guard.windows:
        raise AssertionError("POSIX member guards require a POSIX root descriptor.")
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if type(no_follow) is not int:
        raise RunBundleVerificationError("POSIX no-follow member opening is unavailable.")
    nonblocking = getattr(os, "O_NONBLOCK", None)
    if type(nonblocking) is not int:
        raise RunBundleVerificationError("POSIX nonblocking member opening is unavailable.")
    flags = os.O_RDONLY | no_follow | nonblocking
    close_on_exec = getattr(os, "O_CLOEXEC", None)
    if type(close_on_exec) is int:
        flags |= close_on_exec

    guards: list[_PosixMemberGuard] = []
    identities: set[tuple[int, int]] = set()
    try:
        for name in (_BUNDLE_NAME, _SIDECAR_NAME):
            try:
                descriptor = os.open(name, flags, dir_fd=root_guard.handle)
            except OSError as exc:
                raise RunBundleVerificationError(
                    f"RunBundle member {name!r} could not be guarded without following links."
                ) from exc
            try:
                opened = os.fstat(descriptor)
                visible = os.stat(
                    name,
                    dir_fd=root_guard.handle,
                    follow_symlinks=False,
                )
                identity = _physical_identity(opened)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or not stat.S_ISREG(visible.st_mode)
                    or opened.st_nlink != 1
                    or visible.st_nlink != 1
                    or _physical_identity(visible) != identity
                    or identity in identities
                ):
                    raise RunBundleVerificationError(
                        f"RunBundle member {name!r} identity is inconsistent while guarded."
                    )
            except BaseException:
                with suppress(OSError):
                    os.close(descriptor)
                raise
            guards.append(
                _PosixMemberGuard(
                    name=name,
                    root_descriptor=root_guard.handle,
                    descriptor=descriptor,
                    identity=identity,
                )
            )
            identities.add(identity)
    except BaseException:
        with suppress(OSError):
            _close_posix_member_guards(guards)
        raise
    return tuple(guards)


def _require_posix_member_guards(
    root_guard: _DirectoryGuard,
    guards: Sequence[_PosixMemberGuard],
    *,
    expected: Mapping[str, tuple[int, int]],
) -> None:
    if root_guard.windows:
        raise AssertionError("POSIX member guards require a POSIX root descriptor.")
    if len(guards) != len(expected):
        raise RunBundleVerificationError("RunBundle member guard inventory changed while verified.")
    for guard in guards:
        try:
            opened = os.fstat(guard.descriptor)
            visible = os.stat(
                guard.name,
                dir_fd=root_guard.handle,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise RunBundleVerificationError(
                "RunBundle member identity changed while verified."
            ) from exc
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(visible.st_mode)
            or opened.st_nlink != 1
            or visible.st_nlink != 1
            or _physical_identity(opened) != guard.identity
            or guard.identity != expected[guard.name]
            or _physical_identity(visible) != guard.identity
        ):
            raise RunBundleVerificationError("RunBundle member identity changed while verified.")


def _close_posix_member_guards(guards: Sequence[_PosixMemberGuard]) -> None:
    first_error: OSError | None = None
    for guard in reversed(guards):
        try:
            os.close(guard.descriptor)
        except OSError as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error


def _publish_directory_no_replace(
    source: Path,
    destination: Path,
    *,
    expected_identity: tuple[int, int],
) -> _DirectoryGuard:
    _require_directory_identity(
        source,
        expected_identity=expected_identity,
        label="RunBundle temporary root",
    )
    guard = _open_directory_guard(
        source,
        expected_identity=expected_identity,
        delete_access=True,
    )
    if os.name != "nt":
        try:
            _posix_rename_directory_no_replace(source, destination)
        except BaseException:
            with suppress(OSError):
                _close_directory_guard(guard)
            raise
        return guard

    import ctypes
    from ctypes import wintypes

    handle = guard.handle
    try:
        native_identity = _windows_directory_handle_identity(handle)
        if not _windows_identity_matches(native_identity, expected_identity):
            raise RunBundleValidationError("RunBundle publication source identity changed.")

        class _FileRenameHeader(ctypes.Structure):
            _fields_ = [
                ("replace_if_exists", ctypes.c_ubyte),
                ("root_directory", wintypes.HANDLE),
                ("file_name_length", wintypes.DWORD),
            ]

        encoded_destination = str(destination).encode("utf-16-le")
        file_name_offset = _FileRenameHeader.file_name_length.offset + ctypes.sizeof(wintypes.DWORD)
        buffer = ctypes.create_string_buffer(
            ctypes.sizeof(_FileRenameHeader) + len(encoded_destination) + 2
        )
        header = _FileRenameHeader.from_buffer(buffer)
        header.replace_if_exists = 0
        header.root_directory = None
        header.file_name_length = len(encoded_destination)
        ctypes.memmove(
            ctypes.addressof(buffer) + file_name_offset,
            encoded_destination,
            len(encoded_destination),
        )
        kernel32 = _windows_kernel32()
        set_information = kernel32.SetFileInformationByHandle
        set_information.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        set_information.restype = wintypes.BOOL
        if not set_information(handle, 3, buffer, len(buffer)):
            error = _windows_last_error()
            if error in {80, 183}:
                raise RunBundleValidationError("RunBundle destination appeared before publication.")
            raise _windows_error(error)
    except BaseException:
        with suppress(OSError):
            _close_directory_guard(guard)
        raise
    return guard


def _posix_rename_directory_no_replace(source: Path, destination: Path) -> None:
    """Use the platform's atomic exclusive rename, or fail closed."""

    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    encoded_source = os.fsencode(source)
    encoded_destination = os.fsencode(destination)
    if hasattr(libc, "renameat2"):
        renameat2 = libc.renameat2
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        if renameat2(-100, encoded_source, -100, encoded_destination, 1) == 0:
            return
    elif hasattr(libc, "renamex_np"):
        renamex_np = libc.renamex_np
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        if renamex_np(encoded_source, encoded_destination, 0x00000004) == 0:
            return
    else:
        raise OSError(_errno.ENOTSUP, "Atomic no-replace directory rename is unavailable.")

    error = ctypes.get_errno()
    if error in {_errno.EEXIST, _errno.ENOTEMPTY}:
        raise RunBundleValidationError("RunBundle destination appeared before publication.")
    raise OSError(error, os.strerror(error), destination)


def _require_owned_replay_database(
    path: Path,
    *,
    expected_identity: tuple[int, int],
    descriptor: int,
) -> None:
    status = path.lstat()
    opened = os.fstat(descriptor)
    if (
        not stat.S_ISREG(status.st_mode)
        or not stat.S_ISREG(opened.st_mode)
        or _is_reparse(path, status)
        or _physical_identity(status) != expected_identity
        or _physical_identity(opened) != expected_identity
    ):
        raise RunBundleReplayError("Replay temporary database identity changed.")


def _require_replay_database_identity(path: Path, *, expected_identity: tuple[int, int]) -> None:
    status = path.lstat()
    if (
        not stat.S_ISREG(status.st_mode)
        or _is_reparse(path, status)
        or status.st_nlink != 1
        or _physical_identity(status) != expected_identity
    ):
        raise RunBundleReplayError("Published replay database identity changed.")


def _remove_windows_owned_path(
    path: Path,
    *,
    expected_identity: tuple[int, int],
    directory: bool,
) -> bool:
    import ctypes
    from ctypes import wintypes

    try:
        handle = _open_windows_directory_handle(
            path,
            desired_access=0x00010000 | 0x80,
            share_mode=0x1 | 0x2 | 0x4,
        )
    except OSError:
        return False
    try:
        identity, attributes, _ = _windows_handle_information(handle)
        is_directory = bool(attributes & 0x10)
        if (
            not _windows_identity_matches(identity, expected_identity)
            or bool(attributes & 0x400)
            or is_directory != directory
        ):
            return False

        kernel32 = _windows_kernel32()
        set_information = kernel32.SetFileInformationByHandle
        set_information.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        set_information.restype = wintypes.BOOL

        class _FileDispositionInformationEx(ctypes.Structure):
            _fields_ = [("flags", wintypes.DWORD)]

        extended = _FileDispositionInformationEx(flags=0x1 | 0x2 | 0x10)
        disposition_applied = bool(
            set_information(handle, 21, ctypes.byref(extended), ctypes.sizeof(extended))
        )
        if not disposition_applied:

            class _FileDispositionInformation(ctypes.Structure):
                _fields_ = [("delete_file", wintypes.BOOL)]

            legacy = _FileDispositionInformation(delete_file=True)
            disposition_applied = bool(
                set_information(handle, 4, ctypes.byref(legacy), ctypes.sizeof(legacy))
            )
    finally:
        with suppress(OSError):
            _close_windows_handle(handle)
    return disposition_applied and not os.path.lexists(path)


def _remove_owned_path(
    path: Path,
    *,
    expected_identity: tuple[int, int],
    directory: bool,
) -> bool:
    if os.name == "nt":
        return _remove_windows_owned_path(
            path,
            expected_identity=expected_identity,
            directory=directory,
        )
    try:
        status = path.lstat()
        if (
            _physical_identity(status) != expected_identity
            or _is_reparse(path, status)
            or stat.S_ISDIR(status.st_mode) != directory
            or (not directory and not stat.S_ISREG(status.st_mode))
        ):
            return False
        if directory:
            path.rmdir()
        else:
            path.unlink()
    except OSError:
        return False
    return True


def _remove_owned_empty_directory(
    path: Path,
    *,
    expected_identity: tuple[int, int],
) -> None:
    _remove_owned_path(
        path,
        expected_identity=expected_identity,
        directory=True,
    )


def _strict_bundle_inventory(root: Path) -> dict[str, Path]:
    try:
        _require_plain_directory(root, "RunBundle root")
        with os.scandir(root) as scanner:
            entries = list(scanner)
    except RunBundleValidationError as exc:
        raise RunBundleVerificationError(str(exc)) from exc
    if len(entries) != 2 or {entry.name for entry in entries} != {
        _BUNDLE_NAME,
        _SIDECAR_NAME,
    }:
        raise RunBundleVerificationError(
            "RunBundle root must contain exactly run-bundle.json and its sidecar."
        )
    paths: dict[str, Path] = {}
    identities: set[tuple[int, int]] = set()
    for entry in entries:
        path = Path(entry.path)
        # Windows DirEntry.stat() can report zero inode/link fields; Path.lstat()
        # supplies the physical identity needed for alias rejection.
        status = path.lstat()
        if not stat.S_ISREG(status.st_mode) or _is_reparse(path, status) or status.st_nlink != 1:
            raise RunBundleVerificationError(
                f"RunBundle member {entry.name!r} must be one unaliased ordinary file."
            )
        identity = (status.st_dev, status.st_ino)
        if identity in identities:
            raise RunBundleVerificationError("RunBundle members must not alias one file.")
        identities.add(identity)
        paths[entry.name] = path
    return paths


def _write_new_file(
    path: Path,
    content: bytes,
    *,
    owned_member_identities: dict[str, tuple[int, int]],
) -> None:
    with path.open("xb") as stream:
        owned_member_identities[path.name] = _physical_identity(os.fstat(stream.fileno()))
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _read_stable_member(
    path: Path,
    *,
    expected_identity: tuple[int, int],
    posix_guard: _PosixMemberGuard | None = None,
) -> bytes:
    if posix_guard is not None:
        return _read_stable_posix_guarded_member(
            posix_guard,
            expected_identity=expected_identity,
        )
    before = path.lstat()
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        content = stream.read()
    after = path.lstat()
    if any(
        not stat.S_ISREG(item.st_mode) or _is_reparse(path, item) or item.st_nlink != 1
        for item in (before, opened, after)
    ):
        raise RunBundleVerificationError("RunBundle member changed physical file type while read.")
    before_identity = (before.st_dev, before.st_ino)
    if (
        before_identity != expected_identity
        or (opened.st_dev, opened.st_ino) != expected_identity
        or (after.st_dev, after.st_ino) != expected_identity
    ):
        raise RunBundleVerificationError("RunBundle member identity changed while read.")
    if before.st_size != len(content) or after.st_size != len(content):
        raise RunBundleVerificationError("RunBundle member size changed while read.")
    if (before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise RunBundleVerificationError("RunBundle member metadata changed while read.")
    return content


def _read_stable_posix_guarded_member(
    guard: _PosixMemberGuard,
    *,
    expected_identity: tuple[int, int],
) -> bytes:
    try:
        before = os.stat(
            guard.name,
            dir_fd=guard.root_descriptor,
            follow_symlinks=False,
        )
        opened_before = os.fstat(guard.descriptor)
    except OSError as exc:
        raise RunBundleVerificationError("RunBundle member identity changed while read.") from exc
    opening_snapshots = (before, opened_before)
    if any(not stat.S_ISREG(item.st_mode) for item in opening_snapshots):
        raise RunBundleVerificationError("RunBundle member changed physical file type while read.")
    if (
        any(item.st_nlink == 0 for item in opening_snapshots)
        or _physical_identity(before) != expected_identity
        or _physical_identity(opened_before) != expected_identity
        or guard.identity != expected_identity
    ):
        raise RunBundleVerificationError("RunBundle member identity changed while read.")
    if any(item.st_nlink != 1 for item in opening_snapshots):
        raise RunBundleVerificationError(
            f"RunBundle member {guard.name!r} must be one unaliased ordinary file."
        )

    os.lseek(guard.descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while chunk := os.read(guard.descriptor, 64 * 1024):
        chunks.append(chunk)
    content = b"".join(chunks)

    try:
        opened_after = os.fstat(guard.descriptor)
        after = os.stat(
            guard.name,
            dir_fd=guard.root_descriptor,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise RunBundleVerificationError("RunBundle member identity changed while read.") from exc
    final_snapshots = (opened_before, opened_after, before, after)
    if any(not stat.S_ISREG(item.st_mode) for item in final_snapshots):
        raise RunBundleVerificationError("RunBundle member changed physical file type while read.")
    if any(item.st_nlink == 0 for item in final_snapshots) or any(
        _physical_identity(item) != expected_identity for item in final_snapshots
    ):
        raise RunBundleVerificationError("RunBundle member identity changed while read.")
    if any(item.st_nlink != 1 for item in final_snapshots):
        raise RunBundleVerificationError(
            f"RunBundle member {guard.name!r} must be one unaliased ordinary file."
        )
    if any(item.st_size != len(content) for item in final_snapshots):
        raise RunBundleVerificationError("RunBundle member size changed while read.")
    if (opened_before.st_mtime_ns, opened_before.st_ctime_ns) != (
        opened_after.st_mtime_ns,
        opened_after.st_ctime_ns,
    ) or (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns):
        raise RunBundleVerificationError("RunBundle member metadata changed while read.")
    return content


def _require_member_identities(
    paths: Mapping[str, Path], *, expected: Mapping[str, tuple[int, int]]
) -> None:
    for name, path in paths.items():
        status = path.lstat()
        if (
            not stat.S_ISREG(status.st_mode)
            or _is_reparse(path, status)
            or status.st_nlink != 1
            or _physical_identity(status) != expected[name]
        ):
            raise RunBundleVerificationError("RunBundle member identity changed while verified.")


def _remove_owned_bundle_directory(
    path: Path,
    *,
    root_identity: tuple[int, int],
    member_identities: Mapping[str, tuple[int, int]],
) -> None:
    """Remove only known task-created bundle members and their plain directory."""

    with suppress(OSError):
        status = path.lstat()
        if (
            not stat.S_ISDIR(status.st_mode)
            or _is_reparse(path, status)
            or _physical_identity(status) != root_identity
        ):
            return
        with os.scandir(path) as scanner:
            entries = list(scanner)
        for entry in entries:
            if entry.name not in member_identities:
                continue
            member = Path(entry.path)
            _remove_owned_path(
                member,
                expected_identity=member_identities[entry.name],
                directory=False,
            )
        with os.scandir(path) as scanner:
            remaining_entries = list(scanner)
        if not remaining_entries:
            _remove_owned_path(
                path,
                expected_identity=root_identity,
                directory=True,
            )


def _remove_owned_replay_database(
    database_path: Path, *, expected_identity: tuple[int, int]
) -> bool:
    return _remove_owned_path(
        database_path,
        expected_identity=expected_identity,
        directory=False,
    )
