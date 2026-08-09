"""Versioned, truth-free workload records for the Core execution path."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, cast

_JSON_INT_MIN = -(2**63)
_JSON_INT_MAX = 2**63 - 1
_RUN_SPEC_SCHEMA = "rde-core-run-spec/v1"
_RUN_SPEC_KEYS = frozenset(
    {"adapter", "budget", "candidates", "objective", "policy", "schema", "tie_break"}
)


def _validated_string(value: object, *, field_name: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{field_name} must be a nonempty string.")
    return _validated_json_string(value, field_name=field_name)


def _validated_json_string(value: object, *, field_name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} must contain valid UTF-8 text.") from exc
    return value


def _normalized_integer(value: object, *, field_name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an integer, not a boolean or coercible value.")
    if not _JSON_INT_MIN <= value <= _JSON_INT_MAX:
        raise ValueError(f"{field_name} must fit in a signed 64-bit integer.")
    return value


def _normalized_real(value: object, *, field_name: str) -> float:
    if type(value) not in (int, float):
        raise TypeError(f"{field_name} must be a real number, not a boolean or coercible value.")
    if type(value) is int:
        _normalized_integer(value, field_name=field_name)
    normalized = float(cast(int | float, value))
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite.")
    return 0.0 if normalized == 0.0 else normalized


def _normalized_json(value: object, *, active: set[int], field_name: str) -> object:
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        return _normalized_integer(value, field_name=field_name)
    if type(value) is float:
        normalized = _normalized_real(value, field_name=field_name)
        return normalized
    if type(value) is str:
        return _validated_json_string(value, field_name=field_name)

    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise ValueError(f"{field_name} must not contain a reference cycle.")
        active.add(identity)
        try:
            normalized_mapping: dict[str, object] = {}
            for key, item in cast(Mapping[object, object], value).items():
                if type(key) is not str:
                    raise TypeError(f"{field_name} keys must be strings.")
                validated_key = _validated_json_string(key, field_name=f"{field_name} key")
                normalized_mapping[validated_key] = _normalized_json(
                    item,
                    active=active,
                    field_name=f"{field_name}[{validated_key!r}]",
                )
            return normalized_mapping
        finally:
            active.remove(identity)

    if type(value) in (list, tuple):
        identity = id(value)
        if identity in active:
            raise ValueError(f"{field_name} must not contain a reference cycle.")
        active.add(identity)
        try:
            sequence = cast(list[object] | tuple[object, ...], value)
            return [
                _normalized_json(
                    item,
                    active=active,
                    field_name=f"{field_name}[{index}]",
                )
                for index, item in enumerate(sequence)
            ]
        finally:
            active.remove(identity)

    raise TypeError(
        f"{field_name} contains unsupported type {type(value).__name__!r}; "
        "only canonical JSON values are accepted."
    )


def _normalized_json_object(value: object, *, field_name: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping with string keys.")
    normalized = _normalized_json(value, active=set(), field_name=field_name)
    if type(normalized) is not dict:
        raise AssertionError("JSON object normalization returned a non-object.")
    return cast(dict[str, object], normalized)


def _canonical_json_text(payload: object) -> str:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise ValueError("Content cannot be represented as canonical UTF-8 JSON.") from exc


def _canonical_json_bytes(payload: object) -> bytes:
    """Encode one canonical JSON value with the Core-wide final LF."""

    return _canonical_json_text(payload).encode("utf-8") + b"\n"


@dataclass(frozen=True, slots=True, init=False)
class CandidateSpec:
    """An immutable candidate identity and JSON-compatible, truth-free parameter map.

    Parameter objects are deeply copied and normalized at construction. Mapping key
    order is not semantic, while array order is. Signed 64-bit integers and finite
    floats are accepted; negative zero is normalized to positive zero.
    """

    candidate_id: str
    _parameters_json: str = field(repr=False)

    def __init__(self, candidate_id: str, parameters: Mapping[str, object]) -> None:
        normalized_id = _validated_string(candidate_id, field_name="candidate_id")
        normalized_parameters = _normalized_json_object(parameters, field_name="parameters")
        object.__setattr__(self, "candidate_id", normalized_id)
        object.__setattr__(
            self,
            "_parameters_json",
            _canonical_json_text(normalized_parameters),
        )

    @property
    def parameters(self) -> Mapping[str, object]:
        """Return a detached copy of the normalized parameter map."""

        return self._parameters_payload()

    def _parameters_payload(self) -> dict[str, object]:
        payload = cast(object, json.loads(self._parameters_json))
        if type(payload) is not dict:
            raise AssertionError("Stored candidate parameters are not a JSON object.")
        return cast(dict[str, object], payload)


@dataclass(frozen=True, slots=True, init=False)
class NormalizedObservation:
    """A finite objective value and nonnegative execution cost from a workload."""

    objective_value: float
    cost: float

    def __init__(self, objective_value: float, cost: float = 0.0) -> None:
        normalized_value = _normalized_real(objective_value, field_name="objective_value")
        normalized_cost = _normalized_real(cost, field_name="cost")
        if normalized_cost < 0.0:
            raise ValueError("cost must be nonnegative.")
        object.__setattr__(self, "objective_value", normalized_value)
        object.__setattr__(self, "cost", normalized_cost)


@dataclass(frozen=True, slots=True, init=False)
class RunSpec:
    """Canonical Core v1 input for one finite, truth-free workload run.

    The v1 generic execution path deliberately supports the existing ``random``
    policy only. Its complete configuration is an empty object plus an explicit
    seed. Candidate order is semantic because it determines seeded random indices.
    """

    schema: Literal["rde-core-run-spec/v1"]
    candidates: tuple[CandidateSpec, ...]
    policy_id: str
    _policy_config_json: str = field(repr=False)
    policy_seed: int
    experiment_count_budget: int
    cost_budget: float | None
    adapter_id: str
    adapter_version: str
    objective_name: str
    objective_direction: Literal["maximize", "minimize"]
    tie_break: Literal["candidate-order"]

    def __init__(
        self,
        *,
        candidates: Sequence[CandidateSpec],
        policy_id: str,
        policy_config: Mapping[str, object],
        policy_seed: int,
        experiment_count_budget: int,
        cost_budget: float | None = None,
        adapter_id: str,
        adapter_version: str,
        objective_name: str,
        objective_direction: Literal["maximize", "minimize"],
        tie_break: Literal["candidate-order"] = "candidate-order",
    ) -> None:
        if type(candidates) not in (list, tuple):
            raise TypeError("candidates must be a finite ordered list or tuple.")
        input_candidates = tuple(candidates)
        if not input_candidates:
            raise ValueError("candidates must not be empty.")
        if any(type(candidate) is not CandidateSpec for candidate in input_candidates):
            raise TypeError("Every candidate must be an exact CandidateSpec.")
        try:
            normalized_candidates = tuple(
                CandidateSpec(candidate.candidate_id, candidate.parameters)
                for candidate in input_candidates
            )
        except AttributeError as exc:
            raise TypeError("Every candidate must be a valid exact CandidateSpec.") from exc
        candidate_ids = tuple(candidate.candidate_id for candidate in normalized_candidates)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("Candidate IDs must be unique.")

        normalized_policy_id = _validated_string(policy_id, field_name="policy_id")
        if normalized_policy_id != "random":
            raise ValueError("RunSpec v1 supports only the current Core random policy.")
        normalized_policy_config = _normalized_json_object(
            policy_config, field_name="policy_config"
        )
        if normalized_policy_config:
            raise ValueError("The random policy configuration must be empty; use policy_seed.")
        normalized_seed = _normalized_integer(policy_seed, field_name="policy_seed")

        normalized_count = _normalized_integer(
            experiment_count_budget, field_name="experiment_count_budget"
        )
        if normalized_count <= 0:
            raise ValueError("experiment_count_budget must be positive.")
        if normalized_count > len(normalized_candidates):
            raise ValueError("experiment_count_budget cannot exceed the candidate count.")

        normalized_cost_budget = (
            None if cost_budget is None else _normalized_real(cost_budget, field_name="cost_budget")
        )
        if normalized_cost_budget is not None and normalized_cost_budget <= 0.0:
            raise ValueError("cost_budget must be positive when supplied.")

        normalized_adapter_id = _validated_string(adapter_id, field_name="adapter_id")
        normalized_adapter_version = _validated_string(
            adapter_version, field_name="adapter_version"
        )
        normalized_objective_name = _validated_string(objective_name, field_name="objective_name")
        if type(objective_direction) is not str or objective_direction not in (
            "maximize",
            "minimize",
        ):
            raise ValueError("objective_direction must be 'maximize' or 'minimize'.")
        if type(tie_break) is not str or tie_break != "candidate-order":
            raise ValueError("RunSpec v1 tie_break must be 'candidate-order'.")

        object.__setattr__(self, "schema", _RUN_SPEC_SCHEMA)
        object.__setattr__(self, "candidates", normalized_candidates)
        object.__setattr__(self, "policy_id", normalized_policy_id)
        object.__setattr__(
            self,
            "_policy_config_json",
            _canonical_json_text(normalized_policy_config),
        )
        object.__setattr__(self, "policy_seed", normalized_seed)
        object.__setattr__(self, "experiment_count_budget", normalized_count)
        object.__setattr__(self, "cost_budget", normalized_cost_budget)
        object.__setattr__(self, "adapter_id", normalized_adapter_id)
        object.__setattr__(self, "adapter_version", normalized_adapter_version)
        object.__setattr__(self, "objective_name", normalized_objective_name)
        object.__setattr__(self, "objective_direction", objective_direction)
        object.__setattr__(self, "tie_break", tie_break)

    @property
    def policy_config(self) -> Mapping[str, object]:
        """Return a detached copy of the complete policy configuration."""

        payload = cast(object, json.loads(self._policy_config_json))
        if type(payload) is not dict:
            raise AssertionError("Stored policy configuration is not a JSON object.")
        return cast(dict[str, object], payload)

    def to_canonical_bytes(self) -> bytes:
        """Serialize with the exact Core v1 canonical JSON recipe and one final LF."""

        payload = {
            "adapter": {"id": self.adapter_id, "version": self.adapter_version},
            "budget": {
                "cost": self.cost_budget,
                "experiment_count": self.experiment_count_budget,
            },
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "parameters": candidate._parameters_payload(),
                }
                for candidate in self.candidates
            ],
            "objective": {
                "direction": self.objective_direction,
                "name": self.objective_name,
            },
            "policy": {
                "config": dict(self.policy_config),
                "id": self.policy_id,
                "seed": self.policy_seed,
            },
            "schema": _RUN_SPEC_SCHEMA,
            "tie_break": self.tie_break,
        }
        return _canonical_json_bytes(payload)

    def fingerprint(self) -> str:
        """Return SHA-256 of the exact canonical RunSpec bytes."""

        return hashlib.sha256(self.to_canonical_bytes()).hexdigest()

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> RunSpec:
        """Decode exact canonical bytes, rejecting aliases and unknown fields."""

        if type(encoded) is not bytes:
            raise TypeError("encoded RunSpec must be exact bytes.")
        try:
            text = encoded.decode("utf-8")
            payload = cast(
                object,
                json.loads(
                    text,
                    object_pairs_hook=_object_without_duplicate_keys,
                    parse_constant=_reject_nonfinite_json_constant,
                ),
            )
        except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise ValueError("RunSpec is not strict UTF-8 JSON.") from exc

        top = _required_object(payload, expected_keys=_RUN_SPEC_KEYS, field_name="RunSpec")
        if top["schema"] != _RUN_SPEC_SCHEMA:
            raise ValueError(f"Unsupported RunSpec schema: {top['schema']!r}.")

        candidate_payloads = top["candidates"]
        if type(candidate_payloads) is not list:
            raise ValueError("RunSpec candidates must be a JSON array.")
        candidates: list[CandidateSpec] = []
        try:
            for index, candidate_payload in enumerate(candidate_payloads):
                candidate_object = _required_object(
                    candidate_payload,
                    expected_keys=frozenset({"candidate_id", "parameters"}),
                    field_name=f"candidates[{index}]",
                )
                parameters = candidate_object["parameters"]
                if type(parameters) is not dict:
                    raise ValueError(f"candidates[{index}].parameters must be an object.")
                candidates.append(
                    CandidateSpec(
                        candidate_id=cast(str, candidate_object["candidate_id"]),
                        parameters=cast(dict[str, object], parameters),
                    )
                )

            policy = _required_object(
                top["policy"],
                expected_keys=frozenset({"config", "id", "seed"}),
                field_name="policy",
            )
            if type(policy["config"]) is not dict:
                raise ValueError("policy.config must be an object.")
            budget = _required_object(
                top["budget"],
                expected_keys=frozenset({"cost", "experiment_count"}),
                field_name="budget",
            )
            adapter = _required_object(
                top["adapter"],
                expected_keys=frozenset({"id", "version"}),
                field_name="adapter",
            )
            objective = _required_object(
                top["objective"],
                expected_keys=frozenset({"direction", "name"}),
                field_name="objective",
            )
            spec = cls(
                candidates=candidates,
                policy_id=cast(str, policy["id"]),
                policy_config=cast(dict[str, object], policy["config"]),
                policy_seed=cast(int, policy["seed"]),
                experiment_count_budget=cast(int, budget["experiment_count"]),
                cost_budget=cast(float | None, budget["cost"]),
                adapter_id=cast(str, adapter["id"]),
                adapter_version=cast(str, adapter["version"]),
                objective_name=cast(str, objective["name"]),
                objective_direction=cast(Literal["maximize", "minimize"], objective["direction"]),
                tie_break=cast(Literal["candidate-order"], top["tie_break"]),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("RunSpec content violates the v1 contract.") from exc

        if spec.to_canonical_bytes() != encoded:
            raise ValueError("RunSpec bytes are valid JSON but are not canonical.")
        return spec


@dataclass(frozen=True, slots=True)
class CompletedWorkloadExperiment:
    """A persisted truth-free workload completion projection.

    The fingerprint binds the external RunSpec input. The complete RunSpec is not
    persisted in this slice and will instead belong to a future portable RunBundle.
    """

    run_spec_fingerprint: str
    candidate: CandidateSpec
    policy_id: str
    observation: NormalizedObservation
    created_at: str

    def __post_init__(self) -> None:
        fingerprint = self.run_spec_fingerprint
        if (
            type(fingerprint) is not str
            or len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
        ):
            raise ValueError("run_spec_fingerprint must be a lowercase SHA-256 hex digest.")
        if type(self.candidate) is not CandidateSpec:
            raise TypeError("candidate must be an exact CandidateSpec.")
        _validated_string(self.policy_id, field_name="policy_id")
        if type(self.observation) is not NormalizedObservation:
            raise TypeError("observation must be an exact NormalizedObservation.")
        created_at = _validated_string(self.created_at, field_name="created_at")
        try:
            parsed = datetime.fromisoformat(created_at)
        except ValueError as exc:
            raise ValueError("created_at must be an ISO-8601 timestamp.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("created_at must include an explicit UTC offset.")


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key!r}.")
        result[key] = value
    return result


def _reject_nonfinite_json_constant(value: str) -> object:
    raise ValueError(f"Non-finite JSON constant is forbidden: {value}.")


def _required_object(
    value: object, *, expected_keys: frozenset[str], field_name: str
) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError(f"{field_name} must be a JSON object.")
    result = cast(dict[str, object], value)
    actual_keys = frozenset(result)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        unknown = sorted(actual_keys - expected_keys)
        raise ValueError(f"{field_name} fields differ; missing={missing}, unknown={unknown}.")
    return result
