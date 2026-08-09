"""Strict RunBundle v3 export, verification, and recorded-observation replay."""

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

from research_decision_engine.information_gain_table import (
    InformationGainBeliefLineage,
    TableInformationGainPolicy,
)
from research_decision_engine.policies import _select_random_available
from research_decision_engine.policy_contracts import (
    GREEDY_PRIOR_POLICY_ID,
    INFORMATION_GAIN_TABLE_POLICY_ID,
    RANDOM_POLICY_ID,
    REPLAY_CONTRACT_V3,
    RUN_BUNDLE_V3_SCHEMA,
    RUN_SPEC_V3_SCHEMA,
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
from research_decision_engine.run_spec_v3 import RunSpecV3
from research_decision_engine.storage import SCHEMA_VERSION, ExperimentStore

_SCHEMA: Final = RUN_BUNDLE_V3_SCHEMA
_ARTIFACT_ROLE: Final = "portable_recorded_observation_run_bundle"
_REPLAY_CONTRACT: Final = REPLAY_CONTRACT_V3
_BUNDLE_NAME: Final = "run-bundle.json"
_SIDECAR_NAME: Final = "run-bundle.json.sha256"
_REPLAY_DATABASE_NAME: Final = "replay.sqlite3"
_REPLAY_CREATED_AT: Final = "1970-01-01T00:00:00+00:00"
_DIST_NAME: Final = "research-decision-engine"
_RANDOM_SELECTION_RULE: Final = "random-choice-over-remaining-candidates/v2"
_GREEDY_SELECTION_RULE: Final = "highest-declared-prior-utility-among-eligible-candidates/v1"
_INFORMATION_GAIN_SELECTION_RULE: Final = (
    "largest-expected-shannon-information-gain-under-declared-evidence-model/v1"
)

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
_V2_DECISION_KEYS = frozenset(
    {
        "policy_id",
        "policy_seed",
        "selected_candidate_id",
        "selected_prior_utility",
        "eligible_candidate_count",
        "tie_break",
    }
)
_V2_RATIONALE_KEYS = frozenset(
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
_INFORMATION_GAIN_DECISION_KEYS = frozenset(
    {
        "policy_identity",
        "selected_candidate_id",
        "selected_information_gain_bits",
        "eligible_candidate_count",
        "current_belief_fingerprint",
        "evidence_model_fingerprint",
        "tie_break",
    }
)
_INFORMATION_GAIN_RATIONALE_KEYS = frozenset(
    set(_INFORMATION_GAIN_DECISION_KEYS)
    | {"eligible_candidate_ids", "completed_candidate_ids", "selection_rule"}
)
_OBSERVATION_KEYS = frozenset({"candidate_id", "objective_value", "cost"})
_LINEAGE_KEYS = frozenset(
    {
        "step_index",
        "candidate_id",
        "outcome_id",
        "weights_before",
        "weights_after",
        "belief_fingerprint_before",
        "belief_fingerprint_after",
    }
)
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
        "benchmarktruth",
        "groundtruth",
        "hiddentruth",
        "oraclevalue",
        "oraclevalues",
        "potentialoutcome",
        "potentialoutcomes",
        "truevalue",
        "truevalues",
        "unselectedoutcome",
        "unselectedoutcomes",
    }
)

type StopReasonV3 = Literal[
    "completed",
    "experiment_budget_exhausted",
    "cost_budget_exhausted",
    "candidate_space_exhausted",
    "stopped_by_caller",
]


class RunBundleV3Error(RuntimeError):
    """Base class for RunBundle v3 failures."""


class RunBundleV3ValidationError(RunBundleV3Error):
    """A RunBundle v3 value violates its closed contract."""


class RunBundleV3VerificationError(RunBundleV3Error):
    """A materialized RunBundle v3 fails strict read-only verification."""


class RunBundleV3ReplayError(RunBundleV3Error):
    """A verified RunBundle v3 cannot be replayed equivalently."""


class ReplayBeliefMismatchError(RunBundleV3ValidationError):
    """Recorded information-gain belief lineage differs from exact replay."""


class ReplayInformationGainScoreMismatchError(RunBundleV3ValidationError):
    """Recorded information-gain score differs from exact replay."""


@dataclass(frozen=True, slots=True, init=False)
class RunBundleStepV3:
    """One immutable v3 decision, recorded observation, and optional lineage."""

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
            raise RunBundleV3ValidationError("step_index must be a nonnegative integer.")
        if type(selected_candidate_id) is not str or not selected_candidate_id:
            raise RunBundleV3ValidationError("selected_candidate_id must be nonempty.")
        if type(cumulative_cost) is not float or not math.isfinite(cumulative_cost):
            raise RunBundleV3ValidationError("cumulative_cost must be an exact finite float.")
        if cumulative_cost < 0.0 or _is_negative_zero(cumulative_cost):
            raise RunBundleV3ValidationError("cumulative_cost must use nonnegative canonical zero.")
        if not isinstance(decision, Mapping) or not isinstance(rationale, Mapping):
            raise RunBundleV3ValidationError("decision and rationale must be mappings.")
        if not isinstance(observation, Mapping) or type(belief_lineage) not in (list, tuple):
            raise RunBundleV3ValidationError(
                "observation must be a mapping and belief_lineage a list or tuple."
            )
        if any(not isinstance(item, Mapping) for item in belief_lineage):
            raise RunBundleV3ValidationError("Every belief lineage entry must be a mapping.")

        decision_payload = dict(decision)
        rationale_payload = dict(rationale)
        observation_payload = _required_object(dict(observation), _OBSERVATION_KEYS, "observation")
        lineage_payload = [dict(item) for item in belief_lineage]
        policy_identity = _policy_identity(decision_payload)
        if policy_identity == INFORMATION_GAIN_TABLE_POLICY_ID:
            decision_payload = _required_object(
                decision_payload, _INFORMATION_GAIN_DECISION_KEYS, "decision"
            )
            rationale_payload = _required_object(
                rationale_payload, _INFORMATION_GAIN_RATIONALE_KEYS, "rationale"
            )
            if len(lineage_payload) != 1:
                raise RunBundleV3ValidationError(
                    "information_gain_table requires exactly one lineage entry per step."
                )
            _required_object(lineage_payload[0], _LINEAGE_KEYS, "belief_lineage[0]")
            _validate_information_gain_closed_payloads(
                step_index=step_index,
                selected_candidate_id=selected_candidate_id,
                decision=decision_payload,
                rationale=rationale_payload,
                lineage=lineage_payload[0],
            )
        elif policy_identity in (RANDOM_POLICY_ID, GREEDY_PRIOR_POLICY_ID):
            decision_payload = _required_object(decision_payload, _V2_DECISION_KEYS, "decision")
            rationale_payload = _required_object(rationale_payload, _V2_RATIONALE_KEYS, "rationale")
            if lineage_payload:
                raise RunBundleV3ValidationError(
                    "RunBundle v3 random and greedy_prior steps have empty belief lineage."
                )
            _validate_v2_closed_payloads(
                step_index=step_index,
                selected_candidate_id=selected_candidate_id,
                decision=decision_payload,
                rationale=rationale_payload,
            )
        else:
            raise RunBundleV3ValidationError("Decision policy identity is unsupported by v3.")

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
            field_name="RunBundleStepV3",
        )
        if observation_payload["candidate_id"] != selected_candidate_id:
            raise RunBundleV3ValidationError(
                "Observation candidate does not match the selected candidate."
            )
        normalized = NormalizedObservation(
            objective_value=cast(float, observation_payload["objective_value"]),
            cost=cast(float, observation_payload["cost"]),
        )
        if _canonical_json_bytes(observation_payload) != _canonical_json_bytes(
            _observation_payload(selected_candidate_id, normalized)
        ):
            raise RunBundleV3ValidationError("Observation is not the exact normalized payload.")
        if cumulative_cost < normalized.cost:
            raise RunBundleV3ValidationError("cumulative_cost cannot be less than step cost.")

        object.__setattr__(self, "step_index", step_index)
        object.__setattr__(self, "selected_candidate_id", selected_candidate_id)
        object.__setattr__(self, "cumulative_cost", cumulative_cost)
        object.__setattr__(self, "_decision_json", _canonical_json_text(decision_payload))
        object.__setattr__(self, "_rationale_json", _canonical_json_text(rationale_payload))
        object.__setattr__(self, "_observation_json", _canonical_json_text(observation_payload))
        object.__setattr__(self, "_belief_lineage_json", _canonical_json_text(lineage_payload))

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
class CompletedWorkloadRunTraceV3:
    """One immutable explicitly bounded RunSpec v3 execution trace."""

    run_spec: RunSpecV3
    steps: tuple[RunBundleStepV3, ...]
    stop_reason: StopReasonV3

    def __init__(
        self,
        *,
        run_spec: RunSpecV3,
        steps: Sequence[RunBundleStepV3],
        stop_reason: StopReasonV3,
    ) -> None:
        if type(run_spec) is not RunSpecV3:
            raise RunBundleVersionMismatchError("RunBundle v3 requires an exact RunSpecV3.")
        if type(steps) not in (list, tuple) or any(
            type(step) is not RunBundleStepV3 for step in steps
        ):
            raise RunBundleV3ValidationError(
                "steps must be an explicit list or tuple of exact RunBundleStepV3 records."
            )
        if type(stop_reason) is not str or stop_reason not in _STOP_REASONS:
            raise RunBundleV3ValidationError("stop_reason is not supported by RunBundle v3.")
        object.__setattr__(self, "run_spec", run_spec)
        object.__setattr__(self, "steps", tuple(steps))
        object.__setattr__(self, "stop_reason", stop_reason)


@dataclass(frozen=True, slots=True, init=False)
class RunBundleV3:
    """Immutable decoded ``rde-core-run-bundle/v3`` artifact."""

    schema_version: Literal["rde-core-run-bundle/v3"]
    artifact_role: Literal["portable_recorded_observation_run_bundle"]
    replay_contract: Literal["RECORDED_OBSERVATION_DECISION_REPLAY_V3"]
    run_spec: RunSpecV3
    run_spec_sha256: str
    steps: tuple[RunBundleStepV3, ...]
    root_member_count: Literal[2]
    _producer_json: str = field(repr=False)
    _terminal_summary_json: str = field(repr=False)
    _section_sha256_json: str = field(repr=False)
    _canonical_bytes: bytes = field(repr=False)

    def __init__(self) -> None:
        raise TypeError("RunBundleV3 instances are created only by export or verification.")

    @classmethod
    def _from_validated(
        cls,
        *,
        run_spec: RunSpecV3,
        run_spec_sha256: str,
        producer: Mapping[str, object],
        steps: Sequence[RunBundleStepV3],
        terminal_summary: Mapping[str, object],
        section_sha256: Mapping[str, object],
        canonical_bytes: bytes,
    ) -> RunBundleV3:
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
class RunBundleV3VerificationResult:
    valid: Literal[True]
    bundle_sha256: str
    run_spec_sha256: str
    steps_sha256: str
    terminal_summary_sha256: str
    step_count: int
    selected_candidate_ids: tuple[str, ...]
    bundle: RunBundleV3 = field(repr=False)


@dataclass(frozen=True, slots=True)
class RunBundleV3ReplayResult:
    replay_contract: Literal["RECORDED_OBSERVATION_DECISION_REPLAY_V3"]
    bundle_sha256: str
    run_spec_sha256: str
    steps_sha256: str
    terminal_summary_sha256: str
    history_sha256: str
    step_count: int
    selected_candidate_ids: tuple[str, ...]
    sqlite_schema_version: int
    adapter_execution_count: Literal[0]
    callable_execution_count: Literal[0]
    command_execution_count: Literal[0]
    equivalent: Literal[True]


@dataclass(frozen=True, slots=True)
class _PolicySelectionV3:
    candidate: CandidateSpec
    eligible_candidate_ids: tuple[str, ...]
    decision: Mapping[str, object]
    rationale: Mapping[str, object]


type _PolicyFactoryV3 = Callable[
    [RunSpecV3, tuple[CompletedWorkloadExperiment, ...]], _PolicySelectionV3
]


def _random_policy_factory_v3(
    run_spec: RunSpecV3, history: tuple[CompletedWorkloadExperiment, ...]
) -> _PolicySelectionV3:
    completed_ids = frozenset(item.candidate.candidate_id for item in history)
    eligible = tuple(
        candidate
        for candidate in run_spec.candidates
        if candidate.candidate_id not in completed_ids
    )
    if type(run_spec.policy_seed) is not int:
        raise RunBundleV3ValidationError("RunSpec v3 random replay requires an exact seed.")
    selected = _select_random_available(
        run_spec.candidates, completed_ids, random.Random(run_spec.policy_seed)
    )
    decision = {
        "policy_id": RANDOM_POLICY_ID,
        "policy_seed": run_spec.policy_seed,
        "selected_candidate_id": selected.candidate_id,
        "selected_prior_utility": None,
        "eligible_candidate_count": len(eligible),
        "tie_break": RUNSPEC_CANDIDATE_ORDER,
    }
    rationale = {
        "policy_id": RANDOM_POLICY_ID,
        "selected_candidate_id": selected.candidate_id,
        "selected_prior_utility": None,
        "eligible_candidate_count": len(eligible),
        "tie_break": RUNSPEC_CANDIDATE_ORDER,
        "eligible_candidate_ids": [item.candidate_id for item in eligible],
        "completed_candidate_ids": [item.candidate.candidate_id for item in history],
        "selection_rule": _RANDOM_SELECTION_RULE,
    }
    return _PolicySelectionV3(
        selected, tuple(item.candidate_id for item in eligible), decision, rationale
    )


def _greedy_policy_factory_v3(
    run_spec: RunSpecV3, history: tuple[CompletedWorkloadExperiment, ...]
) -> _PolicySelectionV3:
    completed_ids = frozenset(item.candidate.candidate_id for item in history)
    eligible = tuple(
        candidate
        for candidate in run_spec.candidates
        if candidate.candidate_id not in completed_ids
    )
    raw_utilities = run_spec.policy_config.get("utility_by_candidate_id")
    if type(raw_utilities) is not dict:
        raise RunBundleV3ValidationError("greedy_prior requires a closed utility map.")
    utilities = cast(dict[str, UtilityNumber], raw_utilities)
    selected: CandidateSpec | None = None
    selected_utility: UtilityNumber | None = None
    for candidate in eligible:
        utility = utilities[candidate.candidate_id]
        if selected is None or selected_utility is None or utility > selected_utility:
            selected = candidate
            selected_utility = utility
    if selected is None or selected_utility is None:
        raise RunBundleV3ValidationError("No available candidates remain.")
    decision = {
        "policy_id": GREEDY_PRIOR_POLICY_ID,
        "policy_seed": None,
        "selected_candidate_id": selected.candidate_id,
        "selected_prior_utility": selected_utility,
        "eligible_candidate_count": len(eligible),
        "tie_break": RUNSPEC_CANDIDATE_ORDER,
    }
    rationale = {
        "policy_id": GREEDY_PRIOR_POLICY_ID,
        "selected_candidate_id": selected.candidate_id,
        "selected_prior_utility": selected_utility,
        "eligible_candidate_count": len(eligible),
        "tie_break": RUNSPEC_CANDIDATE_ORDER,
        "eligible_candidate_ids": [item.candidate_id for item in eligible],
        "completed_candidate_ids": [item.candidate.candidate_id for item in history],
        "selection_rule": _GREEDY_SELECTION_RULE,
    }
    return _PolicySelectionV3(
        selected, tuple(item.candidate_id for item in eligible), decision, rationale
    )


def _information_gain_policy_factory_v3(
    run_spec: RunSpecV3, history: tuple[CompletedWorkloadExperiment, ...]
) -> _PolicySelectionV3:
    policy = TableInformationGainPolicy(run_spec)
    selection_details = policy.selection_details(history)
    details = _required_object(
        dict(selection_details.selection_metadata()),
        _INFORMATION_GAIN_DECISION_KEYS,
        "information-gain selection details",
    )
    if details["policy_identity"] != INFORMATION_GAIN_TABLE_POLICY_ID:
        raise RunBundleV3ValidationError("Information-gain policy identity is inconsistent.")
    selected_id = _required_nonempty_string(
        details["selected_candidate_id"], "selected_candidate_id"
    )
    selected = selection_details.candidate
    if selected.candidate_id != selected_id:
        raise RunBundleV3ValidationError("Information-gain selection metadata is inconsistent.")
    if selected is None:
        raise RunBundleV3ValidationError("Information-gain policy selected an unknown candidate.")
    completed_ids = frozenset(item.candidate.candidate_id for item in history)
    eligible = tuple(
        candidate
        for candidate in run_spec.candidates
        if candidate.candidate_id not in completed_ids
    )
    if selected_id not in {item.candidate_id for item in eligible}:
        raise RunBundleV3ValidationError(
            "Information-gain policy selected an ineligible candidate."
        )
    if details["eligible_candidate_count"] != len(eligible):
        raise RunBundleV3ValidationError("Information-gain eligible candidate count differs.")
    _validate_fixed_information_gain_score(details["selected_information_gain_bits"])
    rationale = {
        **details,
        "eligible_candidate_ids": [item.candidate_id for item in eligible],
        "completed_candidate_ids": [item.candidate.candidate_id for item in history],
        "selection_rule": _INFORMATION_GAIN_SELECTION_RULE,
    }
    return _PolicySelectionV3(
        selected,
        tuple(item.candidate_id for item in eligible),
        details,
        rationale,
    )


_SUPPORTED_POLICY_FACTORIES_V3: Mapping[str, _PolicyFactoryV3] = MappingProxyType(
    {
        RANDOM_POLICY_ID: _random_policy_factory_v3,
        GREEDY_PRIOR_POLICY_ID: _greedy_policy_factory_v3,
        INFORMATION_GAIN_TABLE_POLICY_ID: _information_gain_policy_factory_v3,
    }
)


def _selection_for_v3(
    run_spec: RunSpecV3, history: Sequence[CompletedWorkloadExperiment]
) -> _PolicySelectionV3:
    factory = _SUPPORTED_POLICY_FACTORIES_V3.get(run_spec.policy_id)
    if factory is None:
        raise ReplayPolicyUnavailableError(
            "RunBundle v3 replay supports only random, greedy_prior, and information_gain_table."
        )
    return factory(run_spec, tuple(history))


def _lineage_for_record(
    run_spec: RunSpecV3,
    history: Sequence[CompletedWorkloadExperiment],
    record: CompletedWorkloadExperiment,
) -> list[dict[str, object]]:
    if run_spec.policy_id != INFORMATION_GAIN_TABLE_POLICY_ID:
        return []
    lineage = TableInformationGainPolicy(run_spec).lineage_for_observation(tuple(history), record)
    if type(lineage) is not InformationGainBeliefLineage:
        raise RunBundleV3ValidationError(
            "Information-gain policy returned a noncanonical belief-lineage record."
        )
    payload = _required_object(lineage.to_payload(), _LINEAGE_KEYS, "belief lineage")
    return [payload]


def _run_bundle_step_v3_from_completion(
    *,
    run_spec: RunSpecV3,
    record: CompletedWorkloadExperiment,
    completed_history: Sequence[CompletedWorkloadExperiment],
    cumulative_cost: float,
) -> RunBundleStepV3:
    """Capture one completion using the exact finite static v3 policy factory."""

    if type(run_spec) is not RunSpecV3:
        raise RunBundleVersionMismatchError("Trace capture requires an exact RunSpecV3.")
    if type(record) is not CompletedWorkloadExperiment:
        raise RunBundleV3ValidationError(
            "Trace capture requires an exact CompletedWorkloadExperiment."
        )
    if type(completed_history) not in (list, tuple) or any(
        type(item) is not CompletedWorkloadExperiment for item in completed_history
    ):
        raise RunBundleV3ValidationError("Trace history must contain exact completion records.")
    if type(cumulative_cost) is not float or not math.isfinite(cumulative_cost):
        raise RunBundleV3ValidationError("Trace cumulative cost must be an exact finite float.")
    if run_spec.cost_budget is not None and cumulative_cost >= run_spec.cost_budget:
        raise RunBundleV3ValidationError("Trace capture continues after cost exhaustion.")
    candidate_by_id = {candidate.candidate_id: candidate for candidate in run_spec.candidates}
    expected_candidate = candidate_by_id.get(record.candidate.candidate_id)
    if (
        record.run_spec_fingerprint != run_spec.fingerprint()
        or record.policy_id != run_spec.policy_id
        or record.candidate != expected_candidate
    ):
        raise RunBundleV3ValidationError("Completed record is inconsistent with its RunSpecV3.")
    selection = _selection_for_v3(run_spec, completed_history)
    if selection.candidate != record.candidate:
        raise RunBundleV3ValidationError("Completed record selection diverges from the policy.")
    observation = NormalizedObservation(record.observation.objective_value, record.observation.cost)
    next_cost = cumulative_cost + observation.cost
    if not math.isfinite(next_cost):
        raise RunBundleV3ValidationError("Trace cumulative cost must remain finite.")
    if run_spec.cost_budget is not None and next_cost > run_spec.cost_budget:
        raise RunBundleV3ValidationError("Completed record exceeds its cost budget.")
    return RunBundleStepV3(
        step_index=len(completed_history),
        selected_candidate_id=selection.candidate.candidate_id,
        decision=selection.decision,
        rationale=selection.rationale,
        observation=_observation_payload(selection.candidate.candidate_id, observation),
        belief_lineage=_lineage_for_record(run_spec, completed_history, record),
        cumulative_cost=next_cost,
    )


def export_run_bundle_v3(
    destination: Path, *, trace: CompletedWorkloadRunTraceV3
) -> RunBundleV3VerificationResult:
    """Atomically export one exact two-file RunBundle v3 directory."""

    try:
        destination_path = _exact_path(destination, field_name="destination")
    except Exception as exc:
        raise RunBundleV3ValidationError("RunBundle v3 destination is invalid.") from exc
    if os.path.lexists(destination_path):
        raise RunBundleV3ValidationError("RunBundle v3 destination must not already exist.")
    try:
        _require_plain_directory(destination_path.parent, "RunBundle v3 destination parent")
        bundle = _build_run_bundle_v3(trace)
    except (RunBundleV3Error, RunBundleVersionMismatchError):
        raise
    except Exception as exc:
        raise RunBundleV3ValidationError("RunBundle v3 export validation failed.") from exc

    encoded = bundle.to_canonical_bytes()
    sidecar = hashlib.sha256(encoded).hexdigest().encode("ascii") + b"\n"
    temporary_path: Path | None = None
    root_identity: tuple[int, int] | None = None
    member_identities: dict[str, tuple[int, int]] = {}
    published_guard: _DirectoryGuard | None = None
    success = False
    try:
        temporary_path = Path(
            tempfile.mkdtemp(prefix=f".{destination_path.name}.tmp-", dir=destination_path.parent)
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
        verify_run_bundle_v3(temporary_path)
        published_guard = _publish_directory_no_replace(
            temporary_path, destination_path, expected_identity=root_identity
        )
        temporary_path = None
        if _physical_identity(destination_path.lstat()) != root_identity:
            raise RunBundleV3ValidationError("Published RunBundle v3 identity changed.")
        result = verify_run_bundle_v3(destination_path)
        _close_directory_guard(published_guard)
        published_guard = None
        success = True
        return result
    except (RunBundleV3Error, RunBundleVersionMismatchError):
        raise
    except Exception as exc:
        raise RunBundleV3ValidationError("RunBundle v3 atomic export failed.") from exc
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


def verify_run_bundle_v3(bundle_directory: Path) -> RunBundleV3VerificationResult:
    """Strictly and read-only verify an exact RunBundle v3 directory."""

    ancestry_guard: _AncestryGuard | None = None
    try:
        root = _exact_path(bundle_directory, field_name="bundle_directory")
        ancestry_guard = _open_ancestry_guard(root, label="RunBundle v3 root")
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
            raise RunBundleV3VerificationError(
                "RunBundle v3 sidecar is malformed or does not match."
            )
        bundle = _validated_bundle_v3(_decode_canonical_document(encoded), encoded)

        final_paths = _strict_bundle_inventory(root)
        final_identities = {
            name: _physical_identity(path.lstat()) for name, path in final_paths.items()
        }
        if final_identities != identities:
            raise RunBundleV3VerificationError("RunBundle v3 member identity changed.")
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
            raise RunBundleV3VerificationError("RunBundle v3 members changed while verified.")
        _require_member_identities(final_paths, expected=identities)
        if _physical_identity(root.lstat()) != root_identity:
            raise RunBundleV3VerificationError("RunBundle v3 root identity changed.")
        sections = bundle.section_sha256
        result = RunBundleV3VerificationResult(
            valid=True,
            bundle_sha256=bundle_sha256,
            run_spec_sha256=bundle.run_spec_sha256,
            steps_sha256=sections["steps"],
            terminal_summary_sha256=sections["terminal_summary"],
            step_count=len(bundle.steps),
            selected_candidate_ids=tuple(step.selected_candidate_id for step in bundle.steps),
            bundle=bundle,
        )
        _require_ancestry_guard(ancestry_guard, label="RunBundle v3 root")
        _close_ancestry_guard(ancestry_guard)
        ancestry_guard = None
        return result
    except (
        RunBundleV3Error,
        RunBundleVersionMismatchError,
        ReplayDecisionMismatchError,
        ReplayRationaleMismatchError,
    ):
        raise
    except Exception as exc:
        raise RunBundleV3VerificationError("RunBundle v3 strict verification failed.") from exc
    finally:
        if ancestry_guard is not None:
            with suppress(OSError):
                _close_ancestry_guard(ancestry_guard)


def replay_run_bundle_v3(
    bundle_directory: Path, destination_directory: Path
) -> RunBundleV3ReplayResult:
    """Replay only static decisions and recorded observations into fresh SQLite state."""

    try:
        verification = verify_run_bundle_v3(bundle_directory)
    except (
        ReplayBeliefMismatchError,
        ReplayInformationGainScoreMismatchError,
        ReplayDecisionMismatchError,
        ReplayRationaleMismatchError,
    ):
        raise
    except (RunBundleV3Error, RunBundleVersionMismatchError) as exc:
        raise RunBundleV3ReplayError("Replay input failed RunBundle v3 verification.") from exc
    try:
        destination = _exact_path(destination_directory, field_name="destination_directory")
    except Exception as exc:
        raise RunBundleV3ReplayError("Replay destination path is invalid.") from exc

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
            _require_plain_directory(destination, "RunBundle v3 replay destination")
            with os.scandir(destination) as scanner:
                if list(scanner):
                    raise RunBundleV3ReplayError("Replay destination directory must be empty.")
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
            temporary_path, expected_identity=database_identity, descriptor=descriptor
        )

        bundle = verification.bundle
        run_spec = bundle.run_spec
        history: list[CompletedWorkloadExperiment] = []
        rebuilt_steps: list[RunBundleStepV3] = []
        cumulative_cost = 0.0
        with ExperimentStore(temporary_path) as store:
            store.init_schema()
            for recorded_step in bundle.steps:
                selection = _selection_for_v3(run_spec, history)
                _compare_selection(recorded_step, selection)
                raw_observation = recorded_step.observation
                observation = NormalizedObservation(
                    objective_value=cast(float, raw_observation["objective_value"]),
                    cost=cast(float, raw_observation["cost"]),
                )
                record = CompletedWorkloadExperiment(
                    run_spec_fingerprint=run_spec.fingerprint(),
                    candidate=selection.candidate,
                    policy_id=run_spec.policy_id,
                    observation=observation,
                    created_at=_REPLAY_CREATED_AT,
                )
                rebuilt = _run_bundle_step_v3_from_completion(
                    run_spec=run_spec,
                    record=record,
                    completed_history=history,
                    cumulative_cost=cumulative_cost,
                )
                _compare_rebuilt_step(recorded_step, rebuilt)
                persisted = store.add_workload_experiment(record)
                if persisted != record:
                    raise RunBundleV3ReplayError(
                        f"Persistence mismatch at step {recorded_step.step_index}."
                    )
                history.append(record)
                rebuilt_steps.append(rebuilt)
                cumulative_cost = rebuilt.cumulative_cost

        replayed_payload = [step.to_payload() for step in rebuilt_steps]
        replayed_steps_sha256 = _sha256(_canonical_json_bytes(replayed_payload))
        recorded_summary = dict(bundle.terminal_summary)
        terminal = _terminal_summary_payload(
            run_spec,
            replayed_payload,
            stop_reason=cast(StopReasonV3, recorded_summary["stop_reason"]),
            steps_sha256=replayed_steps_sha256,
        )
        if _canonical_json_bytes(terminal) != _canonical_json_bytes(recorded_summary):
            raise RunBundleV3ReplayError("Terminal summary mismatch after replay.")

        with ExperimentStore(temporary_path) as reopened:
            reopened.init_schema()
            reopened_history = reopened.list_workload_experiments(run_spec.fingerprint())
            reopened_steps = _steps_from_history(run_spec, reopened_history)
            integrity = reopened._connection().execute("PRAGMA integrity_check").fetchone()
            if reopened.schema_version() != SCHEMA_VERSION or reopened_history != history:
                raise RunBundleV3ReplayError("Reopened SQLite history is inconsistent.")
            if [step.to_payload() for step in reopened_steps] != replayed_payload:
                raise ReplayBeliefMismatchError("Reopened SQLite lineage is inconsistent.")
            if integrity is None or str(integrity[0]) != "ok":
                raise RunBundleV3ReplayError("Reopened SQLite integrity check failed.")

        _require_owned_replay_database(
            temporary_path, expected_identity=database_identity, descriptor=descriptor
        )
        _require_directory_identity(
            destination, expected_identity=destination_identity, label="Replay destination"
        )
        os.link(temporary_path, database_path, follow_symlinks=False)
        if _physical_identity(database_path.lstat()) != database_identity:
            raise RunBundleV3ReplayError("Replay publication changed database identity.")

        connection = sqlite3.connect(f"{database_path.as_uri()}?mode=ro&immutable=1", uri=True)
        connection.row_factory = sqlite3.Row
        published = ExperimentStore(database_path)
        published.connection = connection
        try:
            published_history = published.list_workload_experiments(run_spec.fingerprint())
            published_integrity = (
                published._connection().execute("PRAGMA integrity_check").fetchone()
            )
            if published.schema_version() != SCHEMA_VERSION or published_history != history:
                raise RunBundleV3ReplayError("Published SQLite history is inconsistent.")
            if [
                step.to_payload() for step in _steps_from_history(run_spec, published_history)
            ] != replayed_payload:
                raise ReplayBeliefMismatchError("Published SQLite lineage is inconsistent.")
            if published_integrity is None or str(published_integrity[0]) != "ok":
                raise RunBundleV3ReplayError("Published SQLite integrity check failed.")
        finally:
            connection.close()
            published.connection = None

        final_verification = verify_run_bundle_v3(bundle_directory)
        if final_verification.bundle_sha256 != verification.bundle_sha256:
            raise RunBundleV3ReplayError("Replay modified the source RunBundle v3.")
        history_sha256 = _sha256(
            _canonical_json_bytes([_history_payload(record) for record in history])
        )
        result = RunBundleV3ReplayResult(
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
            callable_execution_count=0,
            command_execution_count=0,
            equivalent=True,
        )
        os.close(descriptor)
        descriptor = None
        if not _remove_owned_replay_database(temporary_path, expected_identity=database_identity):
            raise RunBundleV3ReplayError("Replay temporary database could not be removed.")
        temporary_path = None
        _require_exact_replay_destination_inventory(
            destination,
            expected_directory_identity=destination_identity,
            expected_database_identity=database_identity,
        )
        _close_directory_guard(destination_guard)
        destination_guard = None
        success = True
        return result
    except (
        RunBundleV3Error,
        ReplayPolicyUnavailableError,
        ReplayDecisionMismatchError,
        ReplayRationaleMismatchError,
    ):
        raise
    except Exception as exc:
        raise RunBundleV3ReplayError("Recorded-observation v3 replay failed.") from exc
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


def _require_exact_replay_destination_inventory(
    destination: Path,
    *,
    expected_directory_identity: tuple[int, int],
    expected_database_identity: tuple[int, int],
) -> None:
    """Fail closed unless the guarded replay root contains only its owned database."""

    _require_directory_identity(
        destination,
        expected_identity=expected_directory_identity,
        label="Replay destination",
    )
    try:
        with os.scandir(destination) as scanner:
            entries = list(scanner)
    except OSError as exc:
        raise RunBundleV3ReplayError("Replay destination inventory could not be read.") from exc
    if len(entries) != 1 or entries[0].name != _REPLAY_DATABASE_NAME:
        raise RunBundleV3ReplayError(
            "Replay destination inventory must contain exactly replay.sqlite3."
        )
    _require_replay_database_identity(
        destination / _REPLAY_DATABASE_NAME,
        expected_identity=expected_database_identity,
    )
    _require_directory_identity(
        destination,
        expected_identity=expected_directory_identity,
        label="Replay destination",
    )


def _build_run_bundle_v3(trace: CompletedWorkloadRunTraceV3) -> RunBundleV3:
    if type(trace) is not CompletedWorkloadRunTraceV3:
        raise RunBundleV3ValidationError("trace must be an exact CompletedWorkloadRunTraceV3.")
    steps = [step.to_payload() for step in trace.steps]
    run_spec_bytes = trace.run_spec.to_canonical_bytes()
    run_spec_payload = _decode_canonical_document(run_spec_bytes)
    if type(run_spec_payload) is not dict:
        raise AssertionError("Canonical RunSpec v3 is not a JSON object.")
    run_spec_sha256 = trace.run_spec.fingerprint()
    steps_sha256 = _sha256(_canonical_json_bytes(steps))
    terminal = _terminal_summary_payload(
        trace.run_spec, steps, stop_reason=trace.stop_reason, steps_sha256=steps_sha256
    )
    _validate_stop_reason(
        trace.stop_reason,
        completed_steps=len(steps),
        total_cost=cast(float, terminal["total_cost"]),
        run_spec=trace.run_spec,
    )
    sections = {
        "run_spec": run_spec_sha256,
        "steps": steps_sha256,
        "terminal_summary": _sha256(_canonical_json_bytes(terminal)),
    }
    payload: dict[str, object] = {
        "schema_version": _SCHEMA,
        "artifact_role": _ARTIFACT_ROLE,
        "replay_contract": _REPLAY_CONTRACT,
        "run_spec": run_spec_payload,
        "run_spec_sha256": run_spec_sha256,
        "producer": _producer_payload(),
        "steps": steps,
        "terminal_summary": terminal,
        "section_sha256": sections,
        "root_member_count": 2,
    }
    encoded = _canonical_json_bytes(payload)
    return _validated_bundle_v3(payload, encoded)


def _validated_bundle_v3(payload: object, encoded: bytes) -> RunBundleV3:
    top = _required_object(payload, _TOP_LEVEL_KEYS, "RunBundle v3")
    _reject_hidden_truth(top)
    _reject_absolute_paths(top, field_name="RunBundle v3")
    if top["schema_version"] != _SCHEMA:
        raise RunBundleVersionMismatchError("Expected rde-core-run-bundle/v3.")
    if top["artifact_role"] != _ARTIFACT_ROLE or top["replay_contract"] != _REPLAY_CONTRACT:
        raise RunBundleV3ValidationError("RunBundle v3 role or replay contract is invalid.")
    if type(top["root_member_count"]) is not int or top["root_member_count"] != 2:
        raise RunBundleV3ValidationError("RunBundle v3 root_member_count must be exactly 2.")

    producer = _required_object(top["producer"], _PRODUCER_KEYS, "producer")
    if any(type(value) is not str or not value for value in producer.values()):
        raise RunBundleV3ValidationError("Every producer field must be a nonempty string.")
    run_spec_payload = _required_object(top["run_spec"], None, "run_spec")
    if run_spec_payload.get("schema") != RUN_SPEC_V3_SCHEMA:
        raise RunBundleVersionMismatchError("RunBundle v3 embeds only rde-core-run-spec/v3.")
    try:
        run_spec = RunSpecV3.from_canonical_bytes(_canonical_json_bytes(run_spec_payload))
    except RunBundleVersionMismatchError:
        raise
    except (TypeError, ValueError) as exc:
        raise RunBundleV3ValidationError("Embedded RunSpecV3 is invalid.") from exc
    run_spec_sha256 = _required_digest(top["run_spec_sha256"], "run_spec_sha256")
    if run_spec_sha256 != run_spec.fingerprint():
        raise RunBundleV3ValidationError("Embedded RunSpecV3 SHA-256 does not match.")

    raw_sections = _required_object(top["section_sha256"], _SECTION_KEYS, "section_sha256")
    sections = {
        key: _required_digest(raw_sections[key], f"section_sha256.{key}")
        for key in sorted(_SECTION_KEYS)
    }
    if sections["run_spec"] != run_spec_sha256:
        raise RunBundleV3ValidationError("RunSpec v3 section SHA-256 does not match.")
    raw_steps = top["steps"]
    if type(raw_steps) is not list:
        raise RunBundleV3ValidationError("RunBundle v3 steps must be a JSON array.")
    history: list[CompletedWorkloadExperiment] = []
    steps: list[RunBundleStepV3] = []
    previous_cost = 0.0
    for index, raw_step in enumerate(raw_steps):
        step, record = _validate_step(
            raw_step,
            expected_index=index,
            run_spec=run_spec,
            history=history,
            previous_cost=previous_cost,
        )
        steps.append(step)
        history.append(record)
        previous_cost = step.cumulative_cost
    if len(steps) > run_spec.experiment_count_budget:
        raise RunBundleV3ValidationError("RunBundle v3 steps exceed the experiment budget.")
    steps_sha256 = _sha256(_canonical_json_bytes(raw_steps))
    if sections["steps"] != steps_sha256:
        raise RunBundleV3ValidationError("Steps section SHA-256 does not match.")
    terminal = _validate_terminal_summary(
        top["terminal_summary"], steps=steps, run_spec=run_spec, steps_sha256=steps_sha256
    )
    if sections["terminal_summary"] != _sha256(_canonical_json_bytes(terminal)):
        raise RunBundleV3ValidationError("Terminal section SHA-256 does not match.")
    if _canonical_json_bytes(top) != encoded:
        raise RunBundleV3ValidationError("RunBundle v3 is not exact canonical JSON.")
    return RunBundleV3._from_validated(
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
    run_spec: RunSpecV3,
    history: Sequence[CompletedWorkloadExperiment],
    previous_cost: float,
) -> tuple[RunBundleStepV3, CompletedWorkloadExperiment]:
    raw = _required_object(value, _STEP_KEYS, f"steps[{expected_index}]")
    if run_spec.cost_budget is not None and previous_cost >= run_spec.cost_budget:
        raise RunBundleV3ValidationError("RunBundle v3 continues after cost exhaustion.")
    step = RunBundleStepV3(
        step_index=cast(int, raw["step_index"]),
        selected_candidate_id=cast(str, raw["selected_candidate_id"]),
        decision=cast(dict[str, object], raw["decision"]),
        rationale=cast(dict[str, object], raw["rationale"]),
        observation=cast(dict[str, object], raw["observation"]),
        belief_lineage=cast(list[dict[str, object]], raw["belief_lineage"]),
        cumulative_cost=cast(float, raw["cumulative_cost"]),
    )
    if step.step_index != expected_index:
        raise RunBundleV3ValidationError("RunBundle v3 step indices must be contiguous.")
    if step.selected_candidate_id in {item.candidate.candidate_id for item in history}:
        raise RunBundleV3ValidationError("RunBundle v3 selects a candidate more than once.")
    selection = _selection_for_v3(run_spec, history)
    _compare_selection(step, selection)
    observation = step.observation
    normalized = NormalizedObservation(
        objective_value=cast(float, observation["objective_value"]),
        cost=cast(float, observation["cost"]),
    )
    expected_cost = previous_cost + normalized.cost
    if not math.isfinite(expected_cost) or step.cumulative_cost != expected_cost:
        raise RunBundleV3ValidationError("RunBundle v3 cumulative cost is inconsistent.")
    if run_spec.cost_budget is not None and step.cumulative_cost > run_spec.cost_budget:
        raise RunBundleV3ValidationError("RunBundle v3 exceeds the cost budget.")
    record = CompletedWorkloadExperiment(
        run_spec_fingerprint=run_spec.fingerprint(),
        candidate=selection.candidate,
        policy_id=run_spec.policy_id,
        observation=normalized,
        created_at=_REPLAY_CREATED_AT,
    )
    expected_lineage = _lineage_for_record(run_spec, history, record)
    if _canonical_json_bytes(expected_lineage) != _canonical_json_bytes(
        [dict(item) for item in step.belief_lineage]
    ):
        raise ReplayBeliefMismatchError(f"Belief lineage mismatch at step {expected_index}.")
    return step, record


def _compare_selection(step: RunBundleStepV3, selection: _PolicySelectionV3) -> None:
    if step.selected_candidate_id != selection.candidate.candidate_id:
        raise ReplayDecisionMismatchError(f"Policy selection mismatch at step {step.step_index}.")
    if (
        _policy_identity(dict(step.decision)) == INFORMATION_GAIN_TABLE_POLICY_ID
        and step.decision["selected_information_gain_bits"]
        != selection.decision["selected_information_gain_bits"]
    ):
        raise ReplayInformationGainScoreMismatchError(
            f"Information-gain score mismatch at step {step.step_index}."
        )
    if _canonical_json_bytes(dict(step.decision)) != _canonical_json_bytes(
        dict(selection.decision)
    ):
        raise ReplayDecisionMismatchError(f"Decision payload mismatch at step {step.step_index}.")
    if _canonical_json_bytes(dict(step.rationale)) != _canonical_json_bytes(
        dict(selection.rationale)
    ):
        raise ReplayRationaleMismatchError(f"Rationale payload mismatch at step {step.step_index}.")


def _compare_rebuilt_step(recorded: RunBundleStepV3, rebuilt: RunBundleStepV3) -> None:
    if [dict(item) for item in recorded.belief_lineage] != [
        dict(item) for item in rebuilt.belief_lineage
    ]:
        raise ReplayBeliefMismatchError(f"Belief lineage mismatch at step {recorded.step_index}.")
    if _canonical_json_bytes(recorded.to_payload()) != _canonical_json_bytes(rebuilt.to_payload()):
        raise RunBundleV3ReplayError(f"Rebuilt step mismatch at step {recorded.step_index}.")


def _steps_from_history(
    run_spec: RunSpecV3, history: Sequence[CompletedWorkloadExperiment]
) -> list[RunBundleStepV3]:
    prefix: list[CompletedWorkloadExperiment] = []
    steps: list[RunBundleStepV3] = []
    cumulative = 0.0
    for record in history:
        step = _run_bundle_step_v3_from_completion(
            run_spec=run_spec,
            record=record,
            completed_history=prefix,
            cumulative_cost=cumulative,
        )
        steps.append(step)
        prefix.append(record)
        cumulative = step.cumulative_cost
    return steps


def _validate_terminal_summary(
    value: object,
    *,
    steps: Sequence[RunBundleStepV3],
    run_spec: RunSpecV3,
    steps_sha256: str,
) -> dict[str, object]:
    summary = _required_object(value, _TERMINAL_KEYS, "terminal_summary")
    if type(summary["completed_steps"]) is not int or summary["completed_steps"] != len(steps):
        raise RunBundleV3ValidationError("Terminal completed_steps does not match.")
    selected_ids = [step.selected_candidate_id for step in steps]
    if summary["selected_candidate_ids"] != selected_ids:
        raise RunBundleV3ValidationError("Terminal selected sequence does not match.")
    expected_total = steps[-1].cumulative_cost if steps else 0.0
    total = _finite_nonnegative_float(summary["total_cost"], "terminal_summary.total_cost")
    if total != expected_total:
        raise RunBundleV3ValidationError("Terminal total_cost does not match.")
    stop_reason = _required_nonempty_string(summary["stop_reason"], "stop_reason")
    if stop_reason not in _STOP_REASONS:
        raise RunBundleV3ValidationError("Terminal stop_reason is unsupported.")
    _validate_stop_reason(
        cast(StopReasonV3, stop_reason),
        completed_steps=len(steps),
        total_cost=total,
        run_spec=run_spec,
    )
    expected_fingerprint = _final_belief_fingerprint(run_spec, steps)
    if summary["final_belief_fingerprint"] != expected_fingerprint:
        raise ReplayBeliefMismatchError("Terminal final belief fingerprint differs.")
    if (
        _required_digest(summary["decision_history_sha256"], "decision_history_sha256")
        != steps_sha256
    ):
        raise RunBundleV3ValidationError("Terminal history SHA-256 does not match.")
    return summary


def _validate_stop_reason(
    stop_reason: StopReasonV3,
    *,
    completed_steps: int,
    total_cost: float,
    run_spec: RunSpecV3,
) -> None:
    if (
        stop_reason == "experiment_budget_exhausted"
        and completed_steps != run_spec.experiment_count_budget
    ):
        raise RunBundleV3ValidationError(
            "experiment_budget_exhausted requires the exact experiment budget."
        )
    if stop_reason == "cost_budget_exhausted" and (
        run_spec.cost_budget is None or total_cost < run_spec.cost_budget
    ):
        raise RunBundleV3ValidationError("cost_budget_exhausted requires a reached cost budget.")
    if stop_reason == "candidate_space_exhausted" and completed_steps != len(run_spec.candidates):
        raise RunBundleV3ValidationError(
            "candidate_space_exhausted requires every candidate to be completed."
        )


def _validate_v2_closed_payloads(
    *,
    step_index: int,
    selected_candidate_id: str,
    decision: dict[str, object],
    rationale: dict[str, object],
) -> None:
    policy_id = decision["policy_id"]
    if policy_id not in (RANDOM_POLICY_ID, GREEDY_PRIOR_POLICY_ID):
        raise RunBundleV3ValidationError("Decision policy identity is unsupported.")
    for key in (
        "policy_id",
        "selected_candidate_id",
        "selected_prior_utility",
        "eligible_candidate_count",
        "tie_break",
    ):
        if rationale[key] != decision[key]:
            raise RunBundleV3ValidationError(f"Decision/rationale field {key!r} differs.")
    if decision["selected_candidate_id"] != selected_candidate_id:
        raise RunBundleV3ValidationError("Decision candidate does not match its step.")
    _validate_candidate_context(step_index, decision, rationale)
    if decision["tie_break"] != RUNSPEC_CANDIDATE_ORDER:
        raise RunBundleV3ValidationError("Decision tie_break is unsupported.")
    if policy_id == RANDOM_POLICY_ID:
        if (
            type(decision["policy_seed"]) is not int
            or decision["selected_prior_utility"] is not None
        ):
            raise RunBundleV3ValidationError("random decision payload is invalid.")
        if rationale["selection_rule"] != _RANDOM_SELECTION_RULE:
            raise RunBundleV3ValidationError("Random rationale selection rule is invalid.")
    else:
        if decision["policy_seed"] is not None:
            raise RunBundleV3ValidationError("greedy_prior requires a null policy seed.")
        _utility_number(decision["selected_prior_utility"])
        if rationale["selection_rule"] != _GREEDY_SELECTION_RULE:
            raise RunBundleV3ValidationError("greedy_prior rationale rule is invalid.")


def _validate_information_gain_closed_payloads(
    *,
    step_index: int,
    selected_candidate_id: str,
    decision: dict[str, object],
    rationale: dict[str, object],
    lineage: dict[str, object],
) -> None:
    if decision["policy_identity"] != INFORMATION_GAIN_TABLE_POLICY_ID:
        raise RunBundleV3ValidationError("Information-gain decision identity is invalid.")
    for key in _INFORMATION_GAIN_DECISION_KEYS:
        if rationale[key] != decision[key]:
            raise RunBundleV3ValidationError(f"Decision/rationale field {key!r} differs.")
    if decision["selected_candidate_id"] != selected_candidate_id:
        raise RunBundleV3ValidationError("Decision candidate does not match its step.")
    _validate_candidate_context(step_index, decision, rationale)
    if decision["tie_break"] != RUNSPEC_CANDIDATE_ORDER:
        raise RunBundleV3ValidationError("Information-gain tie_break is unsupported.")
    _required_digest(decision["current_belief_fingerprint"], "current_belief_fingerprint")
    _required_digest(decision["evidence_model_fingerprint"], "evidence_model_fingerprint")
    _validate_fixed_information_gain_score(decision["selected_information_gain_bits"])
    if rationale["selection_rule"] != _INFORMATION_GAIN_SELECTION_RULE:
        raise RunBundleV3ValidationError("Information-gain rationale rule is invalid.")
    if lineage["step_index"] != step_index or lineage["candidate_id"] != selected_candidate_id:
        raise RunBundleV3ValidationError("Belief lineage does not bind its exact step.")
    _required_nonempty_string(lineage["outcome_id"], "outcome_id")
    _validate_integer_weights(lineage["weights_before"], "weights_before")
    _validate_integer_weights(lineage["weights_after"], "weights_after")
    before = _required_digest(lineage["belief_fingerprint_before"], "belief_fingerprint_before")
    _required_digest(lineage["belief_fingerprint_after"], "belief_fingerprint_after")
    if before != decision["current_belief_fingerprint"]:
        raise RunBundleV3ValidationError("Decision does not bind lineage belief-before identity.")


def _validate_candidate_context(
    step_index: int, decision: Mapping[str, object], rationale: Mapping[str, object]
) -> None:
    eligible_count = decision["eligible_candidate_count"]
    if type(eligible_count) is not int or eligible_count <= 0:
        raise RunBundleV3ValidationError("eligible_candidate_count must be positive.")
    eligible_ids = rationale["eligible_candidate_ids"]
    completed_ids = rationale["completed_candidate_ids"]
    if type(eligible_ids) is not list or any(type(item) is not str for item in eligible_ids):
        raise RunBundleV3ValidationError("eligible_candidate_ids must be a string array.")
    if type(completed_ids) is not list or any(type(item) is not str for item in completed_ids):
        raise RunBundleV3ValidationError("completed_candidate_ids must be a string array.")
    if len(eligible_ids) != eligible_count or len(completed_ids) != step_index:
        raise RunBundleV3ValidationError("Rationale candidate counts are inconsistent.")
    if len(set(eligible_ids)) != len(eligible_ids) or len(set(completed_ids)) != len(completed_ids):
        raise RunBundleV3ValidationError("Rationale candidate lists contain duplicates.")
    if set(eligible_ids).intersection(completed_ids):
        raise RunBundleV3ValidationError("Rationale candidate sets overlap.")
    if decision["selected_candidate_id"] not in eligible_ids:
        raise RunBundleV3ValidationError("Selected candidate is not eligible.")


def _terminal_summary_payload(
    run_spec: RunSpecV3,
    steps: Sequence[Mapping[str, object]],
    *,
    stop_reason: StopReasonV3,
    steps_sha256: str,
) -> dict[str, object]:
    typed_steps = [
        RunBundleStepV3(
            step_index=cast(int, step["step_index"]),
            selected_candidate_id=cast(str, step["selected_candidate_id"]),
            decision=cast(dict[str, object], step["decision"]),
            rationale=cast(dict[str, object], step["rationale"]),
            observation=cast(dict[str, object], step["observation"]),
            belief_lineage=cast(list[dict[str, object]], step["belief_lineage"]),
            cumulative_cost=cast(float, step["cumulative_cost"]),
        )
        for step in steps
    ]
    return {
        "completed_steps": len(steps),
        "selected_candidate_ids": [cast(str, step["selected_candidate_id"]) for step in steps],
        "total_cost": typed_steps[-1].cumulative_cost if typed_steps else 0.0,
        "stop_reason": stop_reason,
        "final_belief_fingerprint": _final_belief_fingerprint(run_spec, typed_steps),
        "decision_history_sha256": steps_sha256,
    }


def _final_belief_fingerprint(run_spec: RunSpecV3, steps: Sequence[RunBundleStepV3]) -> str | None:
    if run_spec.policy_id != INFORMATION_GAIN_TABLE_POLICY_ID:
        return None
    if steps:
        lineage = steps[-1].belief_lineage
        if len(lineage) != 1:
            raise ReplayBeliefMismatchError("Final information-gain step lacks one lineage record.")
        return _required_digest(lineage[0]["belief_fingerprint_after"], "final_belief_fingerprint")
    details = TableInformationGainPolicy(run_spec).selection_details(())
    return _required_digest(details.current_belief_fingerprint, "initial_belief_fingerprint")


def _observation_payload(
    candidate_id: str, observation: NormalizedObservation
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "objective_value": observation.objective_value,
        "cost": observation.cost,
    }


def _history_payload(record: CompletedWorkloadExperiment) -> dict[str, object]:
    return {
        "run_spec_fingerprint": record.run_spec_fingerprint,
        "candidate_id": record.candidate.candidate_id,
        "candidate_parameters": dict(record.candidate.parameters),
        "policy_id": record.policy_id,
        "observation": _observation_payload(record.candidate.candidate_id, record.observation),
        "created_at": record.created_at,
    }


def _producer_payload() -> dict[str, object]:
    try:
        package_version = metadata.version(_DIST_NAME)
    except metadata.PackageNotFoundError:
        package_version = "0+unknown"
    return {
        "package_name": _DIST_NAME,
        "package_version": package_version,
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
    }


def _decode_canonical_document(encoded: bytes) -> object:
    if type(encoded) is not bytes or not encoded.endswith(b"\n"):
        raise RunBundleV3ValidationError("Canonical document must be bytes ending in one LF.")
    if encoded.endswith(b"\n\n") or b"\r" in encoded:
        raise RunBundleV3ValidationError("Canonical document has invalid line endings.")
    try:
        value = cast(
            object,
            json.loads(
                encoded.decode("utf-8"),
                object_pairs_hook=_object_without_duplicate_keys,
                parse_constant=_reject_nonfinite_json_constant,
            ),
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise RunBundleV3ValidationError("Document is not strict canonical UTF-8 JSON.") from exc
    if _canonical_json_bytes(value) != encoded:
        raise RunBundleV3ValidationError("Document is not exact canonical JSON.")
    return value


def _required_object(
    value: object, expected_keys: frozenset[str] | None, field_name: str
) -> dict[str, object]:
    if type(value) is not dict:
        raise RunBundleV3ValidationError(f"{field_name} must be a JSON object.")
    result = cast(dict[str, object], value)
    if expected_keys is not None and frozenset(result) != expected_keys:
        raise RunBundleV3ValidationError(f"{field_name} has missing or unknown fields.")
    return result


def _required_nonempty_string(value: object, field_name: str) -> str:
    if type(value) is not str or not value:
        raise RunBundleV3ValidationError(f"{field_name} must be a nonempty string.")
    return value


def _required_digest(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RunBundleV3ValidationError(f"{field_name} must be a lowercase SHA-256 digest.")
    return value


def _finite_nonnegative_float(value: object, field_name: str) -> float:
    if (
        type(value) is not float
        or not math.isfinite(value)
        or value < 0.0
        or _is_negative_zero(value)
    ):
        raise RunBundleV3ValidationError(f"{field_name} must be an exact nonnegative float.")
    return value


def _utility_number(value: object) -> UtilityNumber:
    if type(value) is int:
        return value
    if type(value) is float and math.isfinite(value) and not _is_negative_zero(value):
        return value
    raise RunBundleV3ValidationError("selected_prior_utility is not canonical.")


def _validate_fixed_information_gain_score(value: object) -> str:
    if type(value) is not str:
        raise RunBundleV3ValidationError("Information-gain score must be a fixed-point string.")
    integer, separator, fraction = value.partition(".")
    if (
        separator != "."
        or not integer
        or not integer.isdigit()
        or len(fraction) != 30
        or not fraction.isdigit()
    ):
        raise RunBundleV3ValidationError(
            "Information-gain score must have exactly 30 fractional decimal places."
        )
    return value


def _validate_integer_weights(value: object, field_name: str) -> tuple[int, ...]:
    if (
        type(value) is not list
        or not value
        or any(type(item) is not int or item < 0 for item in value)
    ):
        raise RunBundleV3ValidationError(
            f"{field_name} must be a nonempty array of nonnegative exact integers."
        )
    if not any(cast(list[int], value)):
        raise RunBundleV3ValidationError(f"{field_name} cannot be all zero.")
    return tuple(cast(list[int], value))


def _policy_identity(decision: Mapping[str, object]) -> str:
    if "policy_identity" in decision:
        return _required_nonempty_string(decision["policy_identity"], "policy_identity")
    if "policy_id" in decision:
        return _required_nonempty_string(decision["policy_id"], "policy_id")
    raise RunBundleV3ValidationError("Decision has no policy identity.")


def _reject_hidden_truth(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if type(key) is not str:
                raise RunBundleV3ValidationError("Canonical object keys must be strings.")
            normalized = "".join(character for character in key.casefold() if character.isalnum())
            if normalized in _HIDDEN_TRUTH_KEYS:
                raise RunBundleV3ValidationError("RunBundle v3 contains hidden-truth data.")
            _reject_hidden_truth(child)
    elif type(value) in (list, tuple):
        for child in cast(Sequence[object], value):
            _reject_hidden_truth(child)


def _reject_absolute_paths(value: object, *, field_name: str) -> None:
    if isinstance(value, Mapping):
        for child in value.values():
            _reject_absolute_paths(child, field_name=field_name)
    elif type(value) in (list, tuple):
        for child in cast(Sequence[object], value):
            _reject_absolute_paths(child, field_name=field_name)
    elif type(value) is str and (
        PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute()
    ):
        raise RunBundleV3ValidationError(f"{field_name} contains an absolute path.")


def _json_object_copy(encoded: str) -> dict[str, object]:
    value = cast(object, json.loads(encoded))
    if type(value) is not dict:
        raise AssertionError("Stored canonical value is not a JSON object.")
    return cast(dict[str, object], value)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_negative_zero(value: float) -> bool:
    return value == 0.0 and math.copysign(1.0, value) < 0.0
