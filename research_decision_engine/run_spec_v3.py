"""Canonical RunSpec v3 with three finite static policy contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, cast

from research_decision_engine.policy_contracts import (
    INFORMATION_GAIN_TABLE_POLICY_ID,
    RUN_SPEC_V3_SCHEMA,
    RUNSPEC_CANDIDATE_ORDER,
    InvalidPolicyTieBreakError,
    PolicyConfigurationError,
    PolicyContractError,
    RunSpecVersionMismatchError,
    _normalized_v3_policy,
)
from research_decision_engine.run_spec import (
    CandidateSpec,
    _canonical_json_bytes,
    _canonical_json_text,
    _normalized_integer,
    _normalized_real,
    _object_without_duplicate_keys,
    _reject_nonfinite_json_constant,
    _required_object,
    _validated_string,
)

if TYPE_CHECKING:
    from research_decision_engine.information_gain_table import FiniteTableEvidenceModel

_RUN_SPEC_V3_KEYS = frozenset(
    {"adapter", "budget", "candidates", "objective", "policy", "schema", "tie_break"}
)


@dataclass(frozen=True, slots=True, init=False)
class RunSpecV3:
    """Immutable canonical Core v3 input for one generic workload run.

    Version 3 supports exactly ``random``, ``greedy_prior``, and
    ``information_gain_table``. The first two preserve their v2 policy semantics.
    The information-gain policy requires a complete explicit finite evidence model.
    """

    schema: Literal["rde-core-run-spec/v3"]
    candidates: tuple[CandidateSpec, ...]
    policy_id: Literal["random", "greedy_prior", "information_gain_table"]
    _policy_config_json: str = field(repr=False)
    policy_seed: int | None
    experiment_count_budget: int
    cost_budget: float | None
    adapter_id: str
    adapter_version: str
    objective_name: str
    objective_direction: Literal["maximize", "minimize"]
    tie_break: Literal["runspec_candidate_order"]

    def __init__(
        self,
        *,
        candidates: Sequence[CandidateSpec],
        policy_id: str,
        policy_config: Mapping[str, object],
        policy_seed: int | None = None,
        experiment_count_budget: int,
        cost_budget: float | None = None,
        adapter_id: str,
        adapter_version: str,
        objective_name: str,
        objective_direction: Literal["maximize", "minimize"],
        tie_break: Literal["runspec_candidate_order"] = RUNSPEC_CANDIDATE_ORDER,
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

        if type(tie_break) is not str or tie_break != RUNSPEC_CANDIDATE_ORDER:
            raise InvalidPolicyTieBreakError(
                "RunSpec v3 tie_break must be 'runspec_candidate_order'."
            )
        normalized_policy_config, normalized_seed = _normalized_v3_policy(
            candidate_ids=candidate_ids,
            policy_id=policy_id,
            policy_config=policy_config,
            policy_seed=policy_seed,
        )

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

        if policy_id == INFORMATION_GAIN_TABLE_POLICY_ID:
            from research_decision_engine.information_gain_table import FiniteTableEvidenceModel

            evidence_model = FiniteTableEvidenceModel.from_payload(
                normalized_policy_config["evidence_model"]
            )
            if evidence_model.observation_metric != normalized_objective_name:
                raise PolicyConfigurationError(
                    "information_gain_table observation_metric must equal objective_name."
                )

        object.__setattr__(self, "schema", RUN_SPEC_V3_SCHEMA)
        object.__setattr__(self, "candidates", normalized_candidates)
        object.__setattr__(self, "policy_id", policy_id)
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
        object.__setattr__(self, "tie_break", RUNSPEC_CANDIDATE_ORDER)

    @property
    def policy_config(self) -> Mapping[str, object]:
        """Return a detached copy of the complete normalized policy configuration."""

        payload = cast(object, json.loads(self._policy_config_json))
        if type(payload) is not dict:
            raise AssertionError("Stored policy configuration is not a JSON object.")
        return cast(dict[str, object], payload)

    @property
    def evidence_model(self) -> FiniteTableEvidenceModel | None:
        """Return the detached finite model for information_gain_table, otherwise null."""

        if self.policy_id != INFORMATION_GAIN_TABLE_POLICY_ID:
            return None
        from research_decision_engine.information_gain_table import FiniteTableEvidenceModel

        config = self.policy_config
        model = FiniteTableEvidenceModel.from_payload(
            cast(Mapping[str, object], config["evidence_model"])
        )
        model.validate_candidate_ids(tuple(candidate.candidate_id for candidate in self.candidates))
        return model

    def to_canonical_bytes(self) -> bytes:
        """Serialize with the Core canonical JSON recipe and one final LF."""

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
            "schema": RUN_SPEC_V3_SCHEMA,
            "tie_break": self.tie_break,
        }
        return _canonical_json_bytes(payload)

    def fingerprint(self) -> str:
        """Return SHA-256 of the exact canonical RunSpec v3 bytes."""

        return hashlib.sha256(self.to_canonical_bytes()).hexdigest()

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> RunSpecV3:
        """Decode exact canonical v3 bytes, rejecting aliases and unknown fields."""

        if type(encoded) is not bytes:
            raise TypeError("encoded RunSpec v3 must be exact bytes.")
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
            raise ValueError("RunSpec v3 is not strict UTF-8 JSON.") from exc

        top = _required_object(payload, expected_keys=_RUN_SPEC_V3_KEYS, field_name="RunSpec v3")
        if top["schema"] != RUN_SPEC_V3_SCHEMA:
            raise RunSpecVersionMismatchError(
                "RunSpecV3 requires the exact rde-core-run-spec/v3 schema."
            )

        candidate_payloads = top["candidates"]
        if type(candidate_payloads) is not list:
            raise ValueError("RunSpec v3 candidates must be a JSON array.")
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
                policy_seed=cast(int | None, policy["seed"]),
                experiment_count_budget=cast(int, budget["experiment_count"]),
                cost_budget=cast(float | None, budget["cost"]),
                adapter_id=cast(str, adapter["id"]),
                adapter_version=cast(str, adapter["version"]),
                objective_name=cast(str, objective["name"]),
                objective_direction=cast(Literal["maximize", "minimize"], objective["direction"]),
                tie_break=cast(Literal["runspec_candidate_order"], top["tie_break"]),
            )
        except PolicyContractError:
            raise
        except (TypeError, ValueError) as exc:
            raise ValueError("RunSpec content violates the v3 contract.") from exc

        if spec.to_canonical_bytes() != encoded:
            raise ValueError("RunSpec v3 bytes are valid JSON but are not canonical.")
        return spec
