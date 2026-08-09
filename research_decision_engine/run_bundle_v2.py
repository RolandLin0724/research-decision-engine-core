"""Strict RunBundle v2 export, verification, and recorded-observation replay."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import random
import sqlite3
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Final, Literal, cast

from research_decision_engine.generic_policies import PriorGreedyPolicy
from research_decision_engine.policies import _select_random_available
from research_decision_engine.policy_contracts import (
    GREEDY_PRIOR_POLICY_ID,
    RANDOM_POLICY_ID,
    REPLAY_CONTRACT_V2,
    RUN_BUNDLE_V2_SCHEMA,
    RUN_SPEC_V2_SCHEMA,
    RUNSPEC_CANDIDATE_ORDER,
    ReplayDecisionMismatchError,
    ReplayPolicyUnavailableError,
    ReplayRationaleMismatchError,
    RunBundleVersionMismatchError,
    UtilityNumber,
)
from research_decision_engine.run_bundle import (
    _AncestryGuard,
    _close_ancestry_guard,
    _close_directory_guard,
    _DirectoryGuard,
    _exact_path,
    _open_ancestry_guard,
    _open_directory_guard,
    _physical_identity,
    _publish_directory_no_replace,
    _read_stable_member,
    _remove_owned_bundle_directory,
    _remove_owned_empty_directory,
    _remove_owned_replay_database,
    _require_ancestry_guard,
    _require_directory_identity,
    _require_member_identities,
    _require_owned_replay_database,
    _require_plain_directory,
    _require_replay_database_identity,
    _strict_bundle_inventory,
    _write_new_file,
)
from research_decision_engine.run_spec import (
    CandidateSpec,
    CompletedWorkloadExperiment,
    NormalizedObservation,
    _canonical_json_bytes,
    _canonical_json_text,
    _object_without_duplicate_keys,
    _reject_nonfinite_json_constant,
)
from research_decision_engine.run_spec_v2 import RunSpecV2
from research_decision_engine.storage import SCHEMA_VERSION, ExperimentStore

_SCHEMA: Final = RUN_BUNDLE_V2_SCHEMA
_ARTIFACT_ROLE: Final = "portable_recorded_observation_run_bundle"
_REPLAY_CONTRACT: Final = REPLAY_CONTRACT_V2
_BUNDLE_NAME: Final = "run-bundle.json"
_SIDECAR_NAME: Final = "run-bundle.json.sha256"
_REPLAY_DATABASE_NAME: Final = "replay.sqlite3"
_REPLAY_CREATED_AT: Final = "1970-01-01T00:00:00+00:00"
_DIST_NAME: Final = "research-decision-engine"
_RANDOM_SELECTION_RULE: Final = "random-choice-over-remaining-candidates/v2"
_GREEDY_SELECTION_RULE: Final = "highest-declared-prior-utility-among-eligible-candidates/v1"

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
_DECISION_KEYS = frozenset(
    {
        "policy_id",
        "policy_seed",
        "selected_candidate_id",
        "selected_prior_utility",
        "eligible_candidate_count",
        "tie_break",
    }
)
_RATIONALE_KEYS = frozenset(
    {
        "policy_id",
        "selected_candidate_id",
        "selected_prior_utility",
        "eligible_candidate_count",
        "tie_break",
        "eligible_candidate_ids",
        "completed_candidate_ids",
        "selection_rule",
    }
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

type StopReasonV2 = Literal[
    "completed",
    "experiment_budget_exhausted",
    "cost_budget_exhausted",
    "candidate_space_exhausted",
    "stopped_by_caller",
]


class RunBundleV2Error(RuntimeError):
    """Base class for RunBundle v2 failures."""


class RunBundleV2ValidationError(RunBundleV2Error):
    """A requested v2 bundle or trace violates the closed contract."""


class RunBundleV2VerificationError(RunBundleV2Error):
    """A materialized v2 bundle fails strict read-only verification."""


class RunBundleV2ReplayError(RunBundleV2Error):
    """A verified v2 bundle cannot be replayed equivalently."""


@dataclass(frozen=True, slots=True, init=False)
class RunBundleStepV2:
    """One immutable v2 decision, rationale, and recorded observation."""

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
            raise RunBundleV2ValidationError("step_index must be a nonnegative integer.")
        if type(selected_candidate_id) is not str or not selected_candidate_id:
            raise RunBundleV2ValidationError("selected_candidate_id must be nonempty.")
        if type(cumulative_cost) is not float or not math.isfinite(cumulative_cost):
            raise RunBundleV2ValidationError("cumulative_cost must be an exact finite float.")
        if cumulative_cost < 0.0 or _is_negative_zero(cumulative_cost):
            raise RunBundleV2ValidationError("cumulative_cost must use nonnegative canonical zero.")
        if not isinstance(decision, Mapping) or not isinstance(rationale, Mapping):
            raise RunBundleV2ValidationError("decision and rationale must be mappings.")
        if not isinstance(observation, Mapping) or type(belief_lineage) not in (list, tuple):
            raise RunBundleV2ValidationError(
                "observation must be a mapping and belief_lineage a list or tuple."
            )
        if any(not isinstance(item, Mapping) for item in belief_lineage):
            raise RunBundleV2ValidationError("Every belief lineage entry must be a mapping.")

        try:
            decision_payload = _required_object(dict(decision), _DECISION_KEYS, "decision")
            rationale_payload = _required_object(dict(rationale), _RATIONALE_KEYS, "rationale")
            observation_payload = _required_object(
                dict(observation), _OBSERVATION_KEYS, "observation"
            )
            lineage_payload = [dict(item) for item in belief_lineage]
            _reject_hidden_truth_v2(
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
                field_name="RunBundleStepV2",
            )
            _validate_closed_decision_and_rationale(
                step_index=step_index,
                selected_candidate_id=selected_candidate_id,
                decision=decision_payload,
                rationale=rationale_payload,
            )
            if observation_payload["candidate_id"] != selected_candidate_id:
                raise RunBundleV2ValidationError(
                    "Observation candidate does not match the selected candidate."
                )
            normalized_observation = NormalizedObservation(
                objective_value=cast(float, observation_payload["objective_value"]),
                cost=cast(float, observation_payload["cost"]),
            )
            if _canonical_json_bytes(observation_payload) != _canonical_json_bytes(
                _observation_payload(selected_candidate_id, normalized_observation)
            ):
                raise RunBundleV2ValidationError(
                    "Observation is not the exact normalized public payload."
                )
            if lineage_payload:
                raise RunBundleV2ValidationError(
                    "RunBundle v2 random and greedy_prior steps have empty belief lineage."
                )
            if cumulative_cost < normalized_observation.cost:
                raise RunBundleV2ValidationError(
                    "cumulative_cost cannot be less than the step cost."
                )
            decision_json = _canonical_json_text(decision_payload)
            rationale_json = _canonical_json_text(rationale_payload)
            observation_json = _canonical_json_text(observation_payload)
            lineage_json = _canonical_json_text(lineage_payload)
        except RunBundleV2ValidationError:
            raise
        except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
            raise RunBundleV2ValidationError(
                "RunBundleStepV2 payload is not canonical JSON data."
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
        return _json_object_copy(self._decision_json)

    @property
    def rationale(self) -> Mapping[str, object]:
        return _json_object_copy(self._rationale_json)

    @property
    def observation(self) -> Mapping[str, object]:
        return _json_object_copy(self._observation_json)

    @property
    def belief_lineage(self) -> tuple[Mapping[str, object], ...]:
        value = cast(object, json.loads(self._belief_lineage_json))
        if type(value) is not list:
            raise AssertionError("Stored belief lineage is not a JSON array.")
        return tuple(cast(dict[str, object], item) for item in value)

    def to_payload(self) -> dict[str, object]:
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
class CompletedWorkloadRunTraceV2:
    """One immutable explicitly bounded RunSpec v2 execution trace."""

    run_spec: RunSpecV2
    steps: tuple[RunBundleStepV2, ...]
    stop_reason: StopReasonV2

    def __init__(
        self,
        *,
        run_spec: RunSpecV2,
        steps: Sequence[RunBundleStepV2],
        stop_reason: StopReasonV2,
    ) -> None:
        if type(run_spec) is not RunSpecV2:
            raise RunBundleVersionMismatchError("RunBundle v2 requires an exact RunSpecV2.")
        if type(steps) not in (list, tuple) or any(
            type(step) is not RunBundleStepV2 for step in steps
        ):
            raise RunBundleV2ValidationError(
                "steps must be an explicit list or tuple of exact RunBundleStepV2 records."
            )
        if type(stop_reason) is not str or stop_reason not in _STOP_REASONS:
            raise RunBundleV2ValidationError("stop_reason is not supported by RunBundle v2.")
        object.__setattr__(self, "run_spec", run_spec)
        object.__setattr__(self, "steps", tuple(steps))
        object.__setattr__(self, "stop_reason", stop_reason)


@dataclass(frozen=True, slots=True, init=False)
class RunBundleV2:
    """Immutable decoded rde-core-run-bundle/v2 artifact."""

    schema_version: Literal["rde-core-run-bundle/v2"]
    artifact_role: Literal["portable_recorded_observation_run_bundle"]
    replay_contract: Literal["RECORDED_OBSERVATION_DECISION_REPLAY_V2"]
    run_spec: RunSpecV2
    run_spec_sha256: str
    steps: tuple[RunBundleStepV2, ...]
    root_member_count: Literal[2]
    _producer_json: str = field(repr=False)
    _terminal_summary_json: str = field(repr=False)
    _section_sha256_json: str = field(repr=False)
    _canonical_bytes: bytes = field(repr=False)

    def __init__(self) -> None:
        raise TypeError("RunBundleV2 instances are created only by export or verification.")

    @classmethod
    def _from_validated(
        cls,
        *,
        run_spec: RunSpecV2,
        run_spec_sha256: str,
        producer: Mapping[str, object],
        steps: Sequence[RunBundleStepV2],
        terminal_summary: Mapping[str, object],
        section_sha256: Mapping[str, object],
        canonical_bytes: bytes,
    ) -> RunBundleV2:
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
        return cast(Mapping[str, str], _json_object_copy(self._producer_json))

    @property
    def terminal_summary(self) -> Mapping[str, object]:
        return _json_object_copy(self._terminal_summary_json)

    @property
    def section_sha256(self) -> Mapping[str, str]:
        return cast(Mapping[str, str], _json_object_copy(self._section_sha256_json))

    def to_canonical_bytes(self) -> bytes:
        return bytes(self._canonical_bytes)


@dataclass(frozen=True, slots=True)
class RunBundleV2VerificationResult:
    valid: Literal[True]
    bundle_sha256: str
    run_spec_sha256: str
    steps_sha256: str
    terminal_summary_sha256: str
    step_count: int
    selected_candidate_ids: tuple[str, ...]
    bundle: RunBundleV2 = field(repr=False)


@dataclass(frozen=True, slots=True)
class RunBundleV2ReplayResult:
    replay_contract: Literal["RECORDED_OBSERVATION_DECISION_REPLAY_V2"]
    bundle_sha256: str
    run_spec_sha256: str
    steps_sha256: str
    terminal_summary_sha256: str
    history_sha256: str
    step_count: int
    selected_candidate_ids: tuple[str, ...]
    sqlite_schema_version: int
    adapter_execution_count: Literal[0]
    command_execution_count: Literal[0]
    equivalent: Literal[True]


@dataclass(frozen=True, slots=True)
class _PolicySelectionV2:
    candidate: CandidateSpec
    eligible_candidate_ids: tuple[str, ...]
    selected_prior_utility: UtilityNumber | None
    policy_seed: int | None
    tie_break: Literal["runspec_candidate_order"]
    selection_rule: str


type _PolicyFactoryV2 = Callable[[RunSpecV2, frozenset[str]], _PolicySelectionV2]


def _random_policy_factory_v2(
    run_spec: RunSpecV2, completed_candidate_ids: frozenset[str]
) -> _PolicySelectionV2:
    eligible = tuple(
        candidate
        for candidate in run_spec.candidates
        if candidate.candidate_id not in completed_candidate_ids
    )
    if type(run_spec.policy_seed) is not int:
        raise RunBundleV2ValidationError("RunSpec v2 random replay requires an exact seed.")
    selected = _select_random_available(
        run_spec.candidates,
        completed_candidate_ids,
        random.Random(run_spec.policy_seed),
    )
    return _PolicySelectionV2(
        candidate=selected,
        eligible_candidate_ids=tuple(candidate.candidate_id for candidate in eligible),
        selected_prior_utility=None,
        policy_seed=run_spec.policy_seed,
        tie_break=RUNSPEC_CANDIDATE_ORDER,
        selection_rule=_RANDOM_SELECTION_RULE,
    )


def _greedy_policy_factory_v2(
    run_spec: RunSpecV2, completed_candidate_ids: frozenset[str]
) -> _PolicySelectionV2:
    eligible_ids = tuple(
        candidate.candidate_id
        for candidate in run_spec.candidates
        if candidate.candidate_id not in completed_candidate_ids
    )
    policy = PriorGreedyPolicy(run_spec)
    selected = policy.select(completed_candidate_ids)
    return _PolicySelectionV2(
        candidate=selected,
        eligible_candidate_ids=eligible_ids,
        selected_prior_utility=policy.prior_utility(selected.candidate_id),
        policy_seed=None,
        tie_break=RUNSPEC_CANDIDATE_ORDER,
        selection_rule=_GREEDY_SELECTION_RULE,
    )


_SUPPORTED_POLICY_FACTORIES_V2: Mapping[str, _PolicyFactoryV2] = MappingProxyType(
    {
        RANDOM_POLICY_ID: _random_policy_factory_v2,
        GREEDY_PRIOR_POLICY_ID: _greedy_policy_factory_v2,
    }
)


def _selection_for(
    run_spec: RunSpecV2, completed_candidate_ids: frozenset[str]
) -> _PolicySelectionV2:
    factory = _SUPPORTED_POLICY_FACTORIES_V2.get(run_spec.policy_id)
    if factory is None:
        raise ReplayPolicyUnavailableError(
            "RunBundle v2 replay supports only random and greedy_prior."
        )
    return factory(run_spec, completed_candidate_ids)


def _decision_payload(run_spec: RunSpecV2, selection: _PolicySelectionV2) -> dict[str, object]:
    return {
        "policy_id": run_spec.policy_id,
        "policy_seed": selection.policy_seed,
        "selected_candidate_id": selection.candidate.candidate_id,
        "selected_prior_utility": selection.selected_prior_utility,
        "eligible_candidate_count": len(selection.eligible_candidate_ids),
        "tie_break": selection.tie_break,
    }


def _rationale_payload(
    run_spec: RunSpecV2,
    selection: _PolicySelectionV2,
    completed_candidate_ids: Sequence[str],
) -> dict[str, object]:
    return {
        "policy_id": run_spec.policy_id,
        "selected_candidate_id": selection.candidate.candidate_id,
        "selected_prior_utility": selection.selected_prior_utility,
        "eligible_candidate_count": len(selection.eligible_candidate_ids),
        "tie_break": selection.tie_break,
        "eligible_candidate_ids": list(selection.eligible_candidate_ids),
        "completed_candidate_ids": list(completed_candidate_ids),
        "selection_rule": selection.selection_rule,
    }


def _observation_payload(
    candidate_id: str, observation: NormalizedObservation
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "objective_value": observation.objective_value,
        "cost": observation.cost,
    }


def _run_bundle_step_v2_from_completion(
    *,
    run_spec: RunSpecV2,
    record: CompletedWorkloadExperiment,
    completed_candidate_ids: Sequence[str],
    cumulative_cost: float,
) -> RunBundleStepV2:
    """Capture one completion using the exact finite static v2 policy factory."""

    if type(run_spec) is not RunSpecV2:
        raise RunBundleVersionMismatchError("Trace capture requires an exact RunSpecV2.")
    if type(record) is not CompletedWorkloadExperiment:
        raise RunBundleV2ValidationError(
            "Trace capture requires an exact CompletedWorkloadExperiment."
        )
    if type(completed_candidate_ids) not in (list, tuple) or any(
        type(candidate_id) is not str for candidate_id in completed_candidate_ids
    ):
        raise RunBundleV2ValidationError("Trace candidate history must be explicit strings.")
    if type(cumulative_cost) is not float or not math.isfinite(cumulative_cost):
        raise RunBundleV2ValidationError("Trace cumulative cost must be an exact float.")
    if run_spec.cost_budget is not None and cumulative_cost >= run_spec.cost_budget:
        raise RunBundleV2ValidationError(
            "Trace capture continues after its cost budget is exhausted."
        )
    candidate_by_id = {candidate.candidate_id: candidate for candidate in run_spec.candidates}
    expected_candidate = candidate_by_id.get(record.candidate.candidate_id)
    if (
        record.run_spec_fingerprint != run_spec.fingerprint()
        or record.policy_id != run_spec.policy_id
        or record.candidate != expected_candidate
    ):
        raise RunBundleV2ValidationError("Completed record is inconsistent with its RunSpecV2.")
    selection = _selection_for(run_spec, frozenset(completed_candidate_ids))
    if selection.candidate != record.candidate:
        raise RunBundleV2ValidationError("Completed record selection diverges from the policy.")
    observation = NormalizedObservation(
        record.observation.objective_value,
        record.observation.cost,
    )
    next_cumulative_cost = cumulative_cost + observation.cost
    if not math.isfinite(next_cumulative_cost):
        raise RunBundleV2ValidationError("Trace cumulative cost must remain finite.")
    if run_spec.cost_budget is not None and next_cumulative_cost > run_spec.cost_budget:
        raise RunBundleV2ValidationError("Completed record exceeds its cost budget.")
    return RunBundleStepV2(
        step_index=len(completed_candidate_ids),
        selected_candidate_id=selection.candidate.candidate_id,
        decision=_decision_payload(run_spec, selection),
        rationale=_rationale_payload(run_spec, selection, completed_candidate_ids),
        observation=_observation_payload(selection.candidate.candidate_id, observation),
        belief_lineage=[],
        cumulative_cost=next_cumulative_cost,
    )


def export_run_bundle_v2(
    destination: Path,
    *,
    trace: CompletedWorkloadRunTraceV2,
) -> RunBundleV2VerificationResult:
    """Atomically export one exact two-file RunBundle v2 directory."""

    try:
        destination_path = _exact_path(destination, field_name="destination")
    except Exception as exc:
        raise RunBundleV2ValidationError("RunBundle v2 destination is invalid.") from exc
    if os.path.lexists(destination_path):
        raise RunBundleV2ValidationError("RunBundle v2 destination must not already exist.")
    try:
        _require_plain_directory(destination_path.parent, "RunBundle v2 destination parent")
        bundle = _build_run_bundle_v2(trace)
    except (RunBundleV2Error, RunBundleVersionMismatchError):
        raise
    except Exception as exc:
        raise RunBundleV2ValidationError("RunBundle v2 export input validation failed.") from exc

    encoded = bundle.to_canonical_bytes()
    sidecar = hashlib.sha256(encoded).hexdigest().encode("ascii") + b"\n"
    temporary_path: Path | None = None
    root_identity: tuple[int, int] | None = None
    member_identities: dict[str, tuple[int, int]] = {}
    published_guard: _DirectoryGuard | None = None
    success = False
    try:
        temporary_path = Path(
            tempfile.mkdtemp(
                prefix=f".{destination_path.name}.tmp-",
                dir=destination_path.parent,
            )
        )
        root_identity = _physical_identity(temporary_path.lstat())
        _write_new_file(
            temporary_path / _BUNDLE_NAME,
            encoded,
            owned_member_identities=member_identities,
        )
        _write_new_file(
            temporary_path / _SIDECAR_NAME,
            sidecar,
            owned_member_identities=member_identities,
        )
        verify_run_bundle_v2(temporary_path)
        published_guard = _publish_directory_no_replace(
            temporary_path,
            destination_path,
            expected_identity=root_identity,
        )
        temporary_path = None
        if _physical_identity(destination_path.lstat()) != root_identity:
            raise RunBundleV2ValidationError("Published RunBundle v2 identity changed.")
        result = verify_run_bundle_v2(destination_path)
        _close_directory_guard(published_guard)
        published_guard = None
        success = True
        return result
    except (RunBundleV2Error, RunBundleVersionMismatchError):
        raise
    except Exception as exc:
        raise RunBundleV2ValidationError("RunBundle v2 atomic export failed.") from exc
    finally:
        if not success and root_identity is not None:
            if temporary_path is not None:
                _remove_owned_bundle_directory(
                    temporary_path,
                    root_identity=root_identity,
                    member_identities=member_identities,
                )
            _remove_owned_bundle_directory(
                destination_path,
                root_identity=root_identity,
                member_identities=member_identities,
            )
        if published_guard is not None:
            with suppress(OSError):
                _close_directory_guard(published_guard)


def verify_run_bundle_v2(bundle_directory: Path) -> RunBundleV2VerificationResult:
    """Strictly and read-only verify an exact RunBundle v2 directory."""

    ancestry_guard: _AncestryGuard | None = None
    try:
        root = _exact_path(bundle_directory, field_name="bundle_directory")
        ancestry_guard = _open_ancestry_guard(root, label="RunBundle v2 root")
        root_identity = _physical_identity(root.lstat())
        paths = _strict_bundle_inventory(root)
        identities = {name: _physical_identity(path.lstat()) for name, path in paths.items()}
        encoded = _read_stable_member(
            paths[_BUNDLE_NAME], expected_identity=identities[_BUNDLE_NAME]
        )
        sidecar = _read_stable_member(
            paths[_SIDECAR_NAME], expected_identity=identities[_SIDECAR_NAME]
        )
        bundle_sha256 = _sha256(encoded)
        if sidecar != bundle_sha256.encode("ascii") + b"\n" or len(sidecar) != 65:
            raise RunBundleV2VerificationError(
                "RunBundle v2 sidecar is malformed or does not match."
            )
        payload = _decode_canonical_document(encoded)
        bundle = _validated_bundle_v2(payload, encoded)

        final_paths = _strict_bundle_inventory(root)
        final_identities = {
            name: _physical_identity(path.lstat()) for name, path in final_paths.items()
        }
        if final_identities != identities:
            raise RunBundleV2VerificationError(
                "RunBundle v2 member identity changed while verified."
            )
        if (
            _read_stable_member(
                final_paths[_BUNDLE_NAME], expected_identity=identities[_BUNDLE_NAME]
            )
            != encoded
            or _read_stable_member(
                final_paths[_SIDECAR_NAME], expected_identity=identities[_SIDECAR_NAME]
            )
            != sidecar
        ):
            raise RunBundleV2VerificationError("RunBundle v2 members changed while verified.")
        _require_member_identities(final_paths, expected=identities)
        if _physical_identity(root.lstat()) != root_identity:
            raise RunBundleV2VerificationError("RunBundle v2 root identity changed.")
        sections = bundle.section_sha256
        result = RunBundleV2VerificationResult(
            valid=True,
            bundle_sha256=bundle_sha256,
            run_spec_sha256=bundle.run_spec_sha256,
            steps_sha256=sections["steps"],
            terminal_summary_sha256=sections["terminal_summary"],
            step_count=len(bundle.steps),
            selected_candidate_ids=tuple(step.selected_candidate_id for step in bundle.steps),
            bundle=bundle,
        )
        _require_ancestry_guard(ancestry_guard, label="RunBundle v2 root")
        _close_ancestry_guard(ancestry_guard)
        ancestry_guard = None
        return result
    except (RunBundleV2VerificationError, RunBundleVersionMismatchError):
        raise
    except Exception as exc:
        raise RunBundleV2VerificationError("RunBundle v2 strict verification failed.") from exc
    finally:
        if ancestry_guard is not None:
            with suppress(OSError):
                _close_ancestry_guard(ancestry_guard)


def replay_run_bundle_v2(
    bundle_directory: Path, destination_directory: Path
) -> RunBundleV2ReplayResult:
    """Replay only static decisions and recorded observations into fresh SQLite state."""

    try:
        verification = verify_run_bundle_v2(bundle_directory)
    except (RunBundleV2VerificationError, RunBundleVersionMismatchError) as exc:
        raise RunBundleV2ReplayError("Replay input failed RunBundle v2 verification.") from exc
    try:
        destination = _exact_path(destination_directory, field_name="destination_directory")
    except Exception as exc:
        raise RunBundleV2ReplayError("Replay destination path is invalid.") from exc

    created_destination = False
    destination_identity: tuple[int, int] | None = None
    destination_guard: _DirectoryGuard | None = None
    database_path = destination / _REPLAY_DATABASE_NAME
    descriptor: int | None = None
    temporary_path: Path | None = None
    database_identity: tuple[int, int] | None = None
    success = False
    try:
        if os.path.lexists(destination):
            _require_plain_directory(destination, "RunBundle v2 replay destination")
            with os.scandir(destination) as scanner:
                if list(scanner):
                    raise RunBundleV2ReplayError("Replay destination directory must be empty.")
        else:
            _require_plain_directory(destination.parent, "Replay destination parent")
            destination.mkdir()
            created_destination = True
        destination_identity = _physical_identity(destination.lstat())
        destination_guard = _open_directory_guard(
            destination, expected_identity=destination_identity
        )

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{_REPLAY_DATABASE_NAME}.tmp-",
            suffix=".sqlite3",
            dir=destination,
        )
        temporary_path = Path(temporary_name)
        database_identity = _physical_identity(os.fstat(descriptor))
        _require_owned_replay_database(
            temporary_path,
            expected_identity=database_identity,
            descriptor=descriptor,
        )

        bundle = verification.bundle
        run_spec = bundle.run_spec
        completed_ids: set[str] = set()
        completed_order: list[str] = []
        expected_history: list[CompletedWorkloadExperiment] = []
        replayed_steps: list[dict[str, object]] = []
        cumulative_cost = 0.0
        with ExperimentStore(temporary_path) as store:
            store.init_schema()
            for recorded_step in bundle.steps:
                if run_spec.cost_budget is not None and cumulative_cost >= run_spec.cost_budget:
                    raise RunBundleV2ReplayError(
                        "Recorded replay continues after the cost budget is exhausted."
                    )
                selection = _selection_for(run_spec, frozenset(completed_ids))
                if selection.candidate.candidate_id != recorded_step.selected_candidate_id:
                    raise ReplayDecisionMismatchError(
                        f"Policy selection mismatch at step {recorded_step.step_index}."
                    )
                decision = _decision_payload(run_spec, selection)
                if _canonical_json_bytes(decision) != _canonical_json_bytes(
                    dict(recorded_step.decision)
                ):
                    raise ReplayDecisionMismatchError(
                        f"Decision payload mismatch at step {recorded_step.step_index}."
                    )
                rationale = _rationale_payload(run_spec, selection, completed_order)
                if _canonical_json_bytes(rationale) != _canonical_json_bytes(
                    dict(recorded_step.rationale)
                ):
                    raise ReplayRationaleMismatchError(
                        f"Rationale payload mismatch at step {recorded_step.step_index}."
                    )

                raw_observation = recorded_step.observation
                observation = NormalizedObservation(
                    objective_value=cast(float, raw_observation["objective_value"]),
                    cost=cast(float, raw_observation["cost"]),
                )
                cumulative_cost += observation.cost
                if run_spec.cost_budget is not None and cumulative_cost > run_spec.cost_budget:
                    raise RunBundleV2ReplayError("Recorded replay exceeds the cost budget.")
                if cumulative_cost != recorded_step.cumulative_cost:
                    raise RunBundleV2ReplayError(
                        f"Cumulative cost mismatch at step {recorded_step.step_index}."
                    )
                expected = CompletedWorkloadExperiment(
                    run_spec_fingerprint=run_spec.fingerprint(),
                    candidate=selection.candidate,
                    policy_id=run_spec.policy_id,
                    observation=observation,
                    created_at=_REPLAY_CREATED_AT,
                )
                persisted = store.add_workload_experiment(expected)
                if persisted != expected:
                    raise RunBundleV2ReplayError(
                        f"Persistence mismatch at step {recorded_step.step_index}."
                    )
                expected_history.append(expected)
                completed_ids.add(selection.candidate.candidate_id)
                completed_order.append(selection.candidate.candidate_id)
                replayed_steps.append(recorded_step.to_payload())

        replayed_steps_sha256 = _sha256(_canonical_json_bytes(replayed_steps))
        recorded_summary = dict(bundle.terminal_summary)
        terminal_summary = _terminal_summary_payload(
            replayed_steps,
            stop_reason=cast(StopReasonV2, recorded_summary["stop_reason"]),
            steps_sha256=replayed_steps_sha256,
        )
        if _canonical_json_bytes(terminal_summary) != _canonical_json_bytes(recorded_summary):
            raise RunBundleV2ReplayError("Terminal summary mismatch after replay.")

        with ExperimentStore(temporary_path) as reopened:
            reopened.init_schema()
            history = reopened.list_workload_experiments(run_spec.fingerprint())
            integrity = reopened._connection().execute("PRAGMA integrity_check").fetchone()
            if reopened.schema_version() != SCHEMA_VERSION or history != expected_history:
                raise RunBundleV2ReplayError("Reopened SQLite history is inconsistent.")
            if integrity is None or str(integrity[0]) != "ok":
                raise RunBundleV2ReplayError("Reopened SQLite integrity check failed.")

        _require_owned_replay_database(
            temporary_path,
            expected_identity=database_identity,
            descriptor=descriptor,
        )
        _require_directory_identity(
            destination,
            expected_identity=destination_identity,
            label="Replay destination",
        )
        os.link(temporary_path, database_path, follow_symlinks=False)
        if _physical_identity(database_path.lstat()) != database_identity:
            raise RunBundleV2ReplayError("Replay publication changed database identity.")

        published_connection = sqlite3.connect(
            f"{database_path.as_uri()}?mode=ro&immutable=1", uri=True
        )
        published_connection.row_factory = sqlite3.Row
        published = ExperimentStore(database_path)
        published.connection = published_connection
        try:
            published_history = published.list_workload_experiments(run_spec.fingerprint())
            published_integrity = (
                published._connection().execute("PRAGMA integrity_check").fetchone()
            )
            if published.schema_version() != SCHEMA_VERSION:
                raise RunBundleV2ReplayError("Published SQLite schema is inconsistent.")
            if published_history != expected_history:
                raise RunBundleV2ReplayError("Published SQLite history is inconsistent.")
            if published_integrity is None or str(published_integrity[0]) != "ok":
                raise RunBundleV2ReplayError("Published SQLite integrity check failed.")
        finally:
            published_connection.close()
            published.connection = None

        final_verification = verify_run_bundle_v2(bundle_directory)
        if final_verification.bundle_sha256 != verification.bundle_sha256:
            raise RunBundleV2ReplayError("Replay modified the source RunBundle v2.")
        history_sha256 = _sha256(
            _canonical_json_bytes([_history_payload(record) for record in expected_history])
        )
        result = RunBundleV2ReplayResult(
            replay_contract=_REPLAY_CONTRACT,
            bundle_sha256=verification.bundle_sha256,
            run_spec_sha256=verification.run_spec_sha256,
            steps_sha256=verification.steps_sha256,
            terminal_summary_sha256=verification.terminal_summary_sha256,
            history_sha256=history_sha256,
            step_count=verification.step_count,
            selected_candidate_ids=verification.selected_candidate_ids,
            sqlite_schema_version=SCHEMA_VERSION,
            adapter_execution_count=0,
            command_execution_count=0,
            equivalent=True,
        )
        os.close(descriptor)
        descriptor = None
        if not _remove_owned_replay_database(temporary_path, expected_identity=database_identity):
            raise RunBundleV2ReplayError("Replay temporary database could not be removed.")
        temporary_path = None
        _require_replay_database_identity(database_path, expected_identity=database_identity)
        _close_directory_guard(destination_guard)
        destination_guard = None
        success = True
        return result
    except (
        RunBundleV2ReplayError,
        ReplayPolicyUnavailableError,
        ReplayDecisionMismatchError,
        ReplayRationaleMismatchError,
    ):
        raise
    except Exception as exc:
        raise RunBundleV2ReplayError("Recorded-observation v2 replay failed.") from exc
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        if not success and database_identity is not None:
            if temporary_path is not None:
                _remove_owned_replay_database(temporary_path, expected_identity=database_identity)
            _remove_owned_replay_database(database_path, expected_identity=database_identity)
        if destination_guard is not None:
            with suppress(OSError):
                _close_directory_guard(destination_guard)
        if not success and created_destination and destination_identity is not None:
            _remove_owned_empty_directory(destination, expected_identity=destination_identity)


def _build_run_bundle_v2(trace: CompletedWorkloadRunTraceV2) -> RunBundleV2:
    if type(trace) is not CompletedWorkloadRunTraceV2:
        raise RunBundleV2ValidationError("trace must be an exact CompletedWorkloadRunTraceV2.")
    steps = [step.to_payload() for step in trace.steps]
    run_spec_bytes = trace.run_spec.to_canonical_bytes()
    run_spec_payload = _decode_canonical_document(run_spec_bytes)
    if type(run_spec_payload) is not dict:
        raise AssertionError("Canonical RunSpec v2 is not a JSON object.")
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
    sections = {
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
        "section_sha256": sections,
        "root_member_count": 2,
    }
    encoded = _canonical_json_bytes(payload)
    return _validated_bundle_v2(payload, encoded)


def _validated_bundle_v2(payload: object, encoded: bytes) -> RunBundleV2:
    top = _required_object(payload, _TOP_LEVEL_KEYS, "RunBundle v2")
    _reject_hidden_truth_v2(top)
    _reject_absolute_paths(top, field_name="RunBundle v2")
    if top["schema_version"] != _SCHEMA:
        raise RunBundleVersionMismatchError("Expected rde-core-run-bundle/v2.")
    if top["artifact_role"] != _ARTIFACT_ROLE or top["replay_contract"] != _REPLAY_CONTRACT:
        raise RunBundleV2ValidationError("RunBundle v2 role or replay contract is invalid.")
    if type(top["root_member_count"]) is not int or top["root_member_count"] != 2:
        raise RunBundleV2ValidationError("RunBundle v2 root_member_count must be exactly 2.")

    producer = _required_object(top["producer"], _PRODUCER_KEYS, "producer")
    if any(type(value) is not str or not value for value in producer.values()):
        raise RunBundleV2ValidationError("Every producer field must be a nonempty string.")

    run_spec_payload = _required_object(top["run_spec"], None, "run_spec")
    if run_spec_payload.get("schema") != RUN_SPEC_V2_SCHEMA:
        raise RunBundleVersionMismatchError("RunBundle v2 embeds only rde-core-run-spec/v2.")
    try:
        run_spec = RunSpecV2.from_canonical_bytes(_canonical_json_bytes(run_spec_payload))
    except RunBundleVersionMismatchError:
        raise
    except (TypeError, ValueError) as exc:
        raise RunBundleV2ValidationError("Embedded RunSpecV2 is invalid.") from exc
    run_spec_sha256 = _required_digest(top["run_spec_sha256"], "run_spec_sha256")
    if run_spec_sha256 != run_spec.fingerprint():
        raise RunBundleV2ValidationError("Embedded RunSpecV2 SHA-256 does not match.")

    raw_sections = _required_object(top["section_sha256"], _SECTION_KEYS, "section_sha256")
    sections = {
        key: _required_digest(raw_sections[key], f"section_sha256.{key}")
        for key in sorted(_SECTION_KEYS)
    }
    if sections["run_spec"] != run_spec_sha256:
        raise RunBundleV2ValidationError("RunSpec v2 section SHA-256 does not match.")

    raw_steps = top["steps"]
    if type(raw_steps) is not list:
        raise RunBundleV2ValidationError("RunBundle v2 steps must be a JSON array.")
    steps: list[RunBundleStepV2] = []
    completed_ids: list[str] = []
    previous_cost = 0.0
    for index, raw_step in enumerate(raw_steps):
        step = _validate_step(
            raw_step,
            expected_index=index,
            run_spec=run_spec,
            completed_candidate_ids=tuple(completed_ids),
            previous_cost=previous_cost,
        )
        steps.append(step)
        completed_ids.append(step.selected_candidate_id)
        previous_cost = step.cumulative_cost
    if len(steps) > run_spec.experiment_count_budget:
        raise RunBundleV2ValidationError("RunBundle v2 steps exceed the experiment budget.")
    steps_sha256 = _sha256(_canonical_json_bytes(raw_steps))
    if sections["steps"] != steps_sha256:
        raise RunBundleV2ValidationError("Steps section SHA-256 does not match.")

    terminal = _validate_terminal_summary(
        top["terminal_summary"],
        steps=steps,
        run_spec=run_spec,
        steps_sha256=steps_sha256,
    )
    if sections["terminal_summary"] != _sha256(_canonical_json_bytes(terminal)):
        raise RunBundleV2ValidationError("Terminal section SHA-256 does not match.")
    if _canonical_json_bytes(top) != encoded:
        raise RunBundleV2ValidationError("RunBundle v2 is not exact canonical JSON.")
    return RunBundleV2._from_validated(
        run_spec=run_spec,
        run_spec_sha256=run_spec_sha256,
        producer=producer,
        steps=steps,
        terminal_summary=terminal,
        section_sha256=sections,
        canonical_bytes=encoded,
    )


def _validate_step(
    value: object,
    *,
    expected_index: int,
    run_spec: RunSpecV2,
    completed_candidate_ids: tuple[str, ...],
    previous_cost: float,
) -> RunBundleStepV2:
    raw = _required_object(value, _STEP_KEYS, f"steps[{expected_index}]")
    if run_spec.cost_budget is not None and previous_cost >= run_spec.cost_budget:
        raise RunBundleV2ValidationError("RunBundle v2 continues after cost exhaustion.")
    step = RunBundleStepV2(
        step_index=cast(int, raw["step_index"]),
        selected_candidate_id=cast(str, raw["selected_candidate_id"]),
        decision=cast(dict[str, object], raw["decision"]),
        rationale=cast(dict[str, object], raw["rationale"]),
        observation=cast(dict[str, object], raw["observation"]),
        belief_lineage=cast(list[dict[str, object]], raw["belief_lineage"]),
        cumulative_cost=cast(float, raw["cumulative_cost"]),
    )
    if step.step_index != expected_index:
        raise RunBundleV2ValidationError("RunBundle v2 step indices must be contiguous.")
    completed = frozenset(completed_candidate_ids)
    if step.selected_candidate_id in completed:
        raise RunBundleV2ValidationError("RunBundle v2 selects a candidate more than once.")
    selection = _selection_for(run_spec, completed)
    if step.selected_candidate_id != selection.candidate.candidate_id:
        raise RunBundleV2ValidationError("Selected sequence diverges from the v2 policy.")
    expected_decision = _decision_payload(run_spec, selection)
    expected_rationale = _rationale_payload(run_spec, selection, completed_candidate_ids)
    if _canonical_json_bytes(dict(step.decision)) != _canonical_json_bytes(expected_decision):
        raise RunBundleV2ValidationError("Decision does not bind exact RunSpec v2 semantics.")
    if _canonical_json_bytes(dict(step.rationale)) != _canonical_json_bytes(expected_rationale):
        raise RunBundleV2ValidationError("Rationale does not bind exact RunSpec v2 semantics.")
    observation = step.observation
    normalized = NormalizedObservation(
        objective_value=cast(float, observation["objective_value"]),
        cost=cast(float, observation["cost"]),
    )
    expected_cost = previous_cost + normalized.cost
    if not math.isfinite(expected_cost) or step.cumulative_cost != expected_cost:
        raise RunBundleV2ValidationError("RunBundle v2 cumulative cost is inconsistent.")
    if run_spec.cost_budget is not None and step.cumulative_cost > run_spec.cost_budget:
        raise RunBundleV2ValidationError("RunBundle v2 exceeds the cost budget.")
    return step


def _validate_terminal_summary(
    value: object,
    *,
    steps: Sequence[RunBundleStepV2],
    run_spec: RunSpecV2,
    steps_sha256: str,
) -> dict[str, object]:
    summary = _required_object(value, _TERMINAL_KEYS, "terminal_summary")
    if type(summary["completed_steps"]) is not int or summary["completed_steps"] != len(steps):
        raise RunBundleV2ValidationError("Terminal completed_steps does not match.")
    selected_ids = [step.selected_candidate_id for step in steps]
    if summary["selected_candidate_ids"] != selected_ids:
        raise RunBundleV2ValidationError("Terminal selected sequence does not match.")
    expected_total = steps[-1].cumulative_cost if steps else 0.0
    total = _finite_nonnegative_float(summary["total_cost"], "terminal_summary.total_cost")
    if total != expected_total:
        raise RunBundleV2ValidationError("Terminal total_cost does not match.")
    stop_reason = _required_nonempty_string(summary["stop_reason"], "stop_reason")
    if stop_reason not in _STOP_REASONS:
        raise RunBundleV2ValidationError("Terminal stop_reason is unsupported.")
    _validate_stop_reason(
        cast(StopReasonV2, stop_reason),
        completed_steps=len(steps),
        total_cost=total,
        run_spec=run_spec,
    )
    if summary["final_belief_fingerprint"] is not None:
        raise RunBundleV2ValidationError("RunBundle v2 has no belief fingerprint.")
    if (
        _required_digest(summary["decision_history_sha256"], "decision_history_sha256")
        != steps_sha256
    ):
        raise RunBundleV2ValidationError("Terminal history SHA-256 does not match.")
    return summary


def _validate_stop_reason(
    stop_reason: StopReasonV2,
    *,
    completed_steps: int,
    total_cost: float,
    run_spec: RunSpecV2,
) -> None:
    if (
        stop_reason == "experiment_budget_exhausted"
        and completed_steps != run_spec.experiment_count_budget
    ):
        raise RunBundleV2ValidationError(
            "experiment_budget_exhausted requires the exact experiment budget."
        )
    if stop_reason == "cost_budget_exhausted" and (
        run_spec.cost_budget is None or total_cost < run_spec.cost_budget
    ):
        raise RunBundleV2ValidationError("cost_budget_exhausted requires a reached cost budget.")
    if stop_reason == "candidate_space_exhausted" and completed_steps != len(run_spec.candidates):
        raise RunBundleV2ValidationError(
            "candidate_space_exhausted requires every candidate to be completed."
        )


def _validate_closed_decision_and_rationale(
    *,
    step_index: int,
    selected_candidate_id: str,
    decision: dict[str, object],
    rationale: dict[str, object],
) -> None:
    policy_id = decision["policy_id"]
    if type(policy_id) is not str or policy_id not in (
        RANDOM_POLICY_ID,
        GREEDY_PRIOR_POLICY_ID,
    ):
        raise RunBundleV2ValidationError("Decision policy identity is unsupported.")
    for key in (
        "policy_id",
        "selected_candidate_id",
        "selected_prior_utility",
        "eligible_candidate_count",
        "tie_break",
    ):
        if rationale[key] != decision[key]:
            raise RunBundleV2ValidationError(f"Decision/rationale field {key!r} differs.")
    if decision["selected_candidate_id"] != selected_candidate_id:
        raise RunBundleV2ValidationError("Decision candidate does not match its step.")
    eligible_count = decision["eligible_candidate_count"]
    if type(eligible_count) is not int or eligible_count <= 0:
        raise RunBundleV2ValidationError("eligible_candidate_count must be positive.")
    eligible_ids = rationale["eligible_candidate_ids"]
    completed_ids = rationale["completed_candidate_ids"]
    if type(eligible_ids) is not list or any(type(item) is not str for item in eligible_ids):
        raise RunBundleV2ValidationError("eligible_candidate_ids must be a string array.")
    if type(completed_ids) is not list or any(type(item) is not str for item in completed_ids):
        raise RunBundleV2ValidationError("completed_candidate_ids must be a string array.")
    if len(eligible_ids) != eligible_count or len(completed_ids) != step_index:
        raise RunBundleV2ValidationError("Rationale candidate counts are inconsistent.")
    if len(set(eligible_ids)) != len(eligible_ids) or len(set(completed_ids)) != len(completed_ids):
        raise RunBundleV2ValidationError("Rationale candidate lists contain duplicates.")
    if set(eligible_ids).intersection(completed_ids) or selected_candidate_id not in eligible_ids:
        raise RunBundleV2ValidationError("Rationale eligibility context is inconsistent.")
    if decision["tie_break"] != RUNSPEC_CANDIDATE_ORDER:
        raise RunBundleV2ValidationError("Decision tie_break is unsupported.")
    utility = decision["selected_prior_utility"]
    if policy_id == RANDOM_POLICY_ID:
        seed = decision["policy_seed"]
        if type(seed) is not int or utility is not None:
            raise RunBundleV2ValidationError(
                "random requires an integer seed and null selected_prior_utility."
            )
        if rationale["selection_rule"] != _RANDOM_SELECTION_RULE:
            raise RunBundleV2ValidationError("Random rationale selection rule is invalid.")
    else:
        if decision["policy_seed"] is not None:
            raise RunBundleV2ValidationError("greedy_prior requires a null policy seed.")
        _utility_number(utility)
        if rationale["selection_rule"] != _GREEDY_SELECTION_RULE:
            raise RunBundleV2ValidationError("greedy_prior rationale rule is invalid.")


def _terminal_summary_payload(
    steps: Sequence[Mapping[str, object]],
    *,
    stop_reason: StopReasonV2,
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
        raise RunBundleV2ValidationError(
            "Installed package metadata is required to export RunBundle v2."
        ) from exc
    if package_name is None:
        raise RunBundleV2ValidationError("Installed package name metadata is missing.")
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
        raise RunBundleV2ValidationError("Canonical JSON input must be exact bytes.")
    if encoded.startswith(b"\xef\xbb\xbf") or b"\r" in encoded:
        raise RunBundleV2ValidationError("Canonical JSON forbids BOM and CR bytes.")
    if not encoded.endswith(b"\n") or encoded.endswith(b"\n\n"):
        raise RunBundleV2ValidationError("Canonical JSON requires exactly one final LF.")
    try:
        payload = cast(
            object,
            json.loads(
                encoded.decode("utf-8"),
                object_pairs_hook=_object_without_duplicate_keys,
                parse_constant=_reject_nonfinite_json_constant,
                parse_float=_parse_finite_float,
            ),
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise RunBundleV2ValidationError("Document is not strict finite UTF-8 JSON.") from exc
    if _canonical_json_bytes(payload) != encoded:
        raise RunBundleV2ValidationError("Document is not exact canonical JSON.")
    return payload


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("Non-finite JSON numbers are forbidden.")
    return parsed


def _required_object(
    value: object, expected_keys: frozenset[str] | None, field_name: str
) -> dict[str, object]:
    if type(value) is not dict:
        raise RunBundleV2ValidationError(f"{field_name} must be a JSON object.")
    result = cast(dict[str, object], value)
    if expected_keys is not None and frozenset(result) != expected_keys:
        missing = sorted(expected_keys.difference(result))
        unknown = sorted(set(result).difference(expected_keys))
        raise RunBundleV2ValidationError(
            f"{field_name} fields are not exact; missing={missing!r}, unknown={unknown!r}."
        )
    return result


def _required_nonempty_string(value: object, field_name: str) -> str:
    if type(value) is not str or not value:
        raise RunBundleV2ValidationError(f"{field_name} must be a nonempty string.")
    return value


def _required_digest(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RunBundleV2ValidationError(
            f"{field_name} must be exactly 64 lowercase SHA-256 hex characters."
        )
    return value


def _finite_nonnegative_float(value: object, field_name: str) -> float:
    if type(value) is not float or not math.isfinite(value) or value < 0.0:
        raise RunBundleV2ValidationError(f"{field_name} must be an exact nonnegative float.")
    if _is_negative_zero(value):
        raise RunBundleV2ValidationError(f"{field_name} must use canonical positive zero.")
    return value


def _utility_number(value: object) -> UtilityNumber:
    if type(value) is int:
        if not -(2**63) <= value <= 2**63 - 1:
            raise RunBundleV2ValidationError("selected_prior_utility integer is out of range.")
        return value
    if type(value) is float and math.isfinite(value) and not _is_negative_zero(value):
        return value
    raise RunBundleV2ValidationError("selected_prior_utility must be a finite JSON number.")


def _is_negative_zero(value: float) -> bool:
    return value == 0.0 and math.copysign(1.0, value) < 0.0


def _reject_hidden_truth_v2(value: object, path: tuple[str, ...] = ()) -> None:
    """Reject semantic field names while treating utility-map keys as candidate IDs."""

    if type(value) is dict:
        for key, item in cast(dict[str, object], value).items():
            if path == ("run_spec", "policy", "config") and key == "utility_by_candidate_id":
                if type(item) is dict:
                    for utility in cast(dict[str, object], item).values():
                        _reject_hidden_truth_v2(utility, path + (key, "<candidate-id>"))
                else:
                    _reject_hidden_truth_v2(item, path + (key,))
                continue
            normalized = "_".join(part for part in _key_parts(key.casefold()) if part)
            if normalized in _HIDDEN_TRUTH_KEYS:
                raise RunBundleV2ValidationError(
                    f"RunBundle v2 contains forbidden hidden-truth field {key!r}."
                )
            _reject_hidden_truth_v2(item, path + (key,))
    elif type(value) is list:
        for item in cast(list[object], value):
            _reject_hidden_truth_v2(item, path)


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


def _reject_absolute_paths(value: object, *, field_name: str) -> None:
    if type(value) is str:
        windows = PureWindowsPath(value)
        if (
            value.casefold().startswith("file:")
            or windows.is_absolute()
            or bool(windows.root)
            or bool(windows.drive)
            or PurePosixPath(value).is_absolute()
        ):
            raise RunBundleV2ValidationError(f"{field_name} must not contain an absolute path.")
    elif type(value) is dict:
        for key, item in cast(dict[str, object], value).items():
            _reject_absolute_paths(key, field_name=f"{field_name} key")
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
