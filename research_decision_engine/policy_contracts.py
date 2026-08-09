"""Frozen public policy/version contracts for generic Core workloads."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, cast

RUN_SPEC_V1_SCHEMA: Final = "rde-core-run-spec/v1"
RUN_SPEC_V2_SCHEMA: Final = "rde-core-run-spec/v2"
RUN_SPEC_V3_SCHEMA: Final = "rde-core-run-spec/v3"
RUN_BUNDLE_V1_SCHEMA: Final = "rde-core-run-bundle/v1"
RUN_BUNDLE_V2_SCHEMA: Final = "rde-core-run-bundle/v2"
RUN_BUNDLE_V3_SCHEMA: Final = "rde-core-run-bundle/v3"
REPLAY_CONTRACT_V1: Final = "RECORDED_OBSERVATION_DECISION_REPLAY_V1"
REPLAY_CONTRACT_V2: Final = "RECORDED_OBSERVATION_DECISION_REPLAY_V2"
REPLAY_CONTRACT_V3: Final = "RECORDED_OBSERVATION_DECISION_REPLAY_V3"

RANDOM_POLICY_ID: Final = "random"
GREEDY_PRIOR_POLICY_ID: Final = "greedy_prior"
INFORMATION_GAIN_TABLE_POLICY_ID: Final = "information_gain_table"
RUNSPEC_CANDIDATE_ORDER: Final = "runspec_candidate_order"
PRIOR_GREEDY_CLASSIFICATION: Final = "STATIC_TRUTH_FREE_PRIOR_UTILITY_GREEDY"
INFORMATION_GAIN_TABLE_CLASSIFICATION: Final = (
    "USER_DECLARED_FINITE_HYPOTHESIS_OUTCOME_LIKELIHOOD_TABLE"
)

_JSON_INT_MIN: Final = -(2**63)
_JSON_INT_MAX: Final = 2**63 - 1
_KNOWN_POLICY_IDENTITIES: Final = frozenset(
    {
        RANDOM_POLICY_ID,
        GREEDY_PRIOR_POLICY_ID,
        INFORMATION_GAIN_TABLE_POLICY_ID,
        "greedy",
    }
)

type UtilityNumber = int | float
type SeedRequirement = Literal["required", "forbidden"]


class PolicyContractError(ValueError):
    """Base class for generic policy schema and configuration failures."""


class UnsupportedRunSpecSchemaError(PolicyContractError):
    """A policy query or decoder named an unsupported RunSpec schema."""


class UnsupportedPolicyIdentityError(PolicyContractError):
    """A policy identity is not in the finite generic policy set."""


class UnsupportedPolicyForSchemaError(PolicyContractError):
    """A known policy identity is unavailable for the requested schema."""


class PolicyConfigurationError(PolicyContractError):
    """A policy configuration does not have its exact closed shape."""


class MissingCandidateUtilityError(PolicyConfigurationError):
    """The greedy prior-utility map omits one or more RunSpec candidates."""


class ExtraCandidateUtilityError(PolicyConfigurationError):
    """The greedy prior-utility map names IDs outside the RunSpec candidates."""


class InvalidCandidateUtilityError(PolicyConfigurationError):
    """A declared candidate utility is not a canonical JSON number."""


class NonfiniteUtilityError(InvalidCandidateUtilityError):
    """A declared candidate utility is NaN or infinite."""


class InvalidPolicyTieBreakError(PolicyConfigurationError):
    """A policy tie-break value differs from its exact contract literal."""


class DeterministicPolicySeedError(PolicyConfigurationError):
    """A deterministic policy was supplied a meaningless random seed."""


class RunSpecVersionMismatchError(PolicyContractError):
    """An operation received a RunSpec from the wrong schema version."""


class RunBundleVersionMismatchError(PolicyContractError):
    """A RunBundle and its embedded RunSpec use different schema versions."""


class ReplayPolicyUnavailableError(PolicyContractError):
    """Static replay cannot reconstruct the recorded policy identity."""


class ReplayDecisionMismatchError(PolicyContractError):
    """A reconstructed replay decision differs from the recorded decision."""


class ReplayRationaleMismatchError(PolicyContractError):
    """A reconstructed replay rationale differs from the recorded rationale."""


@dataclass(frozen=True, slots=True)
class PolicyVersionContract:
    """Immutable policy, bundle, and replay capabilities for one RunSpec schema."""

    run_spec_schema: str
    run_bundle_schema: str
    replay_contract: str
    supported_policy_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PolicyIdentityContract:
    """Immutable closed configuration contract for one policy identity."""

    policy_id: str
    semantic_classification: str
    required_config_fields: tuple[str, ...]
    seed_requirement: SeedRequirement


_V1_CONTRACT: Final = PolicyVersionContract(
    run_spec_schema=RUN_SPEC_V1_SCHEMA,
    run_bundle_schema=RUN_BUNDLE_V1_SCHEMA,
    replay_contract=REPLAY_CONTRACT_V1,
    supported_policy_ids=(RANDOM_POLICY_ID,),
)
_V2_CONTRACT: Final = PolicyVersionContract(
    run_spec_schema=RUN_SPEC_V2_SCHEMA,
    run_bundle_schema=RUN_BUNDLE_V2_SCHEMA,
    replay_contract=REPLAY_CONTRACT_V2,
    supported_policy_ids=(RANDOM_POLICY_ID, GREEDY_PRIOR_POLICY_ID),
)
_V3_CONTRACT: Final = PolicyVersionContract(
    run_spec_schema=RUN_SPEC_V3_SCHEMA,
    run_bundle_schema=RUN_BUNDLE_V3_SCHEMA,
    replay_contract=REPLAY_CONTRACT_V3,
    supported_policy_ids=(
        RANDOM_POLICY_ID,
        GREEDY_PRIOR_POLICY_ID,
        INFORMATION_GAIN_TABLE_POLICY_ID,
    ),
)
_RANDOM_CONTRACT: Final = PolicyIdentityContract(
    policy_id=RANDOM_POLICY_ID,
    semantic_classification="SEEDED_RANDOM_WITHOUT_REPLACEMENT",
    required_config_fields=(),
    seed_requirement="required",
)
_PRIOR_GREEDY_CONTRACT: Final = PolicyIdentityContract(
    policy_id=GREEDY_PRIOR_POLICY_ID,
    semantic_classification=PRIOR_GREEDY_CLASSIFICATION,
    required_config_fields=("utility_by_candidate_id", "tie_break"),
    seed_requirement="forbidden",
)
_INFORMATION_GAIN_TABLE_CONTRACT: Final = PolicyIdentityContract(
    policy_id=INFORMATION_GAIN_TABLE_POLICY_ID,
    semantic_classification=INFORMATION_GAIN_TABLE_CLASSIFICATION,
    required_config_fields=("evidence_model", "tie_break"),
    seed_requirement="forbidden",
)


def policy_contract_for_schema(run_spec_schema: str) -> PolicyVersionContract:
    """Return the immutable generic policy contract for an exact RunSpec schema."""

    if type(run_spec_schema) is not str:
        raise UnsupportedRunSpecSchemaError("RunSpec schema must be an exact string.")
    if run_spec_schema == RUN_SPEC_V1_SCHEMA:
        return _V1_CONTRACT
    if run_spec_schema == RUN_SPEC_V2_SCHEMA:
        return _V2_CONTRACT
    if run_spec_schema == RUN_SPEC_V3_SCHEMA:
        return _V3_CONTRACT
    raise UnsupportedRunSpecSchemaError("The RunSpec schema is not supported.")


def supported_policy_identities(run_spec_schema: str) -> tuple[str, ...]:
    """Return the finite ordered policy identities supported by a schema."""

    return policy_contract_for_schema(run_spec_schema).supported_policy_ids


def policy_identity_contract(run_spec_schema: str, policy_id: str) -> PolicyIdentityContract:
    """Return one immutable policy definition after checking schema support."""

    version_contract = policy_contract_for_schema(run_spec_schema)
    if type(policy_id) is not str or not policy_id:
        raise UnsupportedPolicyIdentityError("Policy identity must be a nonempty exact string.")
    if policy_id not in _KNOWN_POLICY_IDENTITIES:
        raise UnsupportedPolicyIdentityError("The policy identity is not supported.")
    if policy_id not in version_contract.supported_policy_ids:
        raise UnsupportedPolicyForSchemaError(
            "The policy identity is not supported by this RunSpec schema."
        )
    if policy_id == RANDOM_POLICY_ID:
        return _RANDOM_CONTRACT
    if policy_id == GREEDY_PRIOR_POLICY_ID:
        return _PRIOR_GREEDY_CONTRACT
    if policy_id == INFORMATION_GAIN_TABLE_POLICY_ID:
        return _INFORMATION_GAIN_TABLE_CONTRACT
    raise AssertionError("A supported policy identity lacks a frozen contract.")


def _normalized_v2_policy(
    *,
    candidate_ids: Sequence[str],
    policy_id: str,
    policy_config: Mapping[str, object],
    policy_seed: object,
) -> tuple[dict[str, object], int | None]:
    """Validate and detach one exact v2 policy configuration."""

    normalized_candidate_ids = _validated_candidate_ids(candidate_ids)
    identity = policy_identity_contract(RUN_SPEC_V2_SCHEMA, policy_id)
    config = _closed_mapping(policy_config, field_name="policy_config")

    if identity.policy_id == RANDOM_POLICY_ID:
        if config:
            raise PolicyConfigurationError("The random policy configuration must be empty.")
        if type(policy_seed) is not int:
            raise PolicyConfigurationError(
                "The random policy seed must be an integer, not a boolean or coercible value."
            )
        if not _JSON_INT_MIN <= policy_seed <= _JSON_INT_MAX:
            raise PolicyConfigurationError(
                "The random policy seed must fit in a signed 64-bit integer."
            )
        return {}, policy_seed

    if policy_seed is not None:
        raise DeterministicPolicySeedError("greedy_prior forbids a random seed; use null.")

    expected_config_keys = frozenset(identity.required_config_fields)
    actual_config_keys = frozenset(config)
    if actual_config_keys != expected_config_keys:
        if "utility_by_candidate_id" not in actual_config_keys:
            raise MissingCandidateUtilityError(
                "greedy_prior requires a complete utility_by_candidate_id map."
            )
        if "tie_break" not in actual_config_keys:
            raise InvalidPolicyTieBreakError(
                "greedy_prior requires the exact tie_break configuration field."
            )
        raise PolicyConfigurationError("greedy_prior configuration contains unknown fields.")

    tie_break = config["tie_break"]
    if type(tie_break) is not str or tie_break != RUNSPEC_CANDIDATE_ORDER:
        raise InvalidPolicyTieBreakError(
            "greedy_prior tie_break must be 'runspec_candidate_order'."
        )

    raw_utility_map = config["utility_by_candidate_id"]
    utility_map = _closed_mapping(raw_utility_map, field_name="utility_by_candidate_id")
    candidate_id_set = frozenset(normalized_candidate_ids)
    utility_id_set = frozenset(utility_map)
    missing_count = len(candidate_id_set - utility_id_set)
    if missing_count:
        raise MissingCandidateUtilityError(
            f"utility_by_candidate_id is missing {missing_count} candidate ID(s)."
        )
    extra_count = len(utility_id_set - candidate_id_set)
    if extra_count:
        raise ExtraCandidateUtilityError(
            f"utility_by_candidate_id contains {extra_count} extra candidate ID(s)."
        )

    normalized_utility_map = {
        candidate_id: _normalized_utility(utility_map[candidate_id])
        for candidate_id in normalized_candidate_ids
    }
    return {
        "utility_by_candidate_id": normalized_utility_map,
        "tie_break": RUNSPEC_CANDIDATE_ORDER,
    }, None


def _normalized_v3_policy(
    *,
    candidate_ids: Sequence[str],
    policy_id: str,
    policy_config: Mapping[str, object],
    policy_seed: object,
) -> tuple[dict[str, object], int | None]:
    """Validate and detach one exact v3 policy configuration."""

    normalized_candidate_ids = _validated_candidate_ids(candidate_ids)
    identity = policy_identity_contract(RUN_SPEC_V3_SCHEMA, policy_id)
    if identity.policy_id in (RANDOM_POLICY_ID, GREEDY_PRIOR_POLICY_ID):
        return _normalized_v2_policy(
            candidate_ids=normalized_candidate_ids,
            policy_id=policy_id,
            policy_config=policy_config,
            policy_seed=policy_seed,
        )

    if identity.policy_id != INFORMATION_GAIN_TABLE_POLICY_ID:
        raise AssertionError("A supported v3 policy lacks a frozen configuration contract.")
    if policy_seed is not None:
        raise DeterministicPolicySeedError(
            "information_gain_table forbids a random seed; use null."
        )

    config = _closed_mapping(policy_config, field_name="policy_config")
    expected_config_keys = frozenset(identity.required_config_fields)
    actual_config_keys = frozenset(config)
    if actual_config_keys != expected_config_keys:
        if "evidence_model" not in actual_config_keys:
            raise PolicyConfigurationError(
                "information_gain_table requires an explicit evidence_model."
            )
        if "tie_break" not in actual_config_keys:
            raise InvalidPolicyTieBreakError(
                "information_gain_table requires the exact tie_break configuration field."
            )
        raise PolicyConfigurationError(
            "information_gain_table configuration contains unknown fields."
        )

    tie_break = config["tie_break"]
    if type(tie_break) is not str or tie_break != RUNSPEC_CANDIDATE_ORDER:
        raise InvalidPolicyTieBreakError(
            "information_gain_table tie_break must be 'runspec_candidate_order'."
        )

    # Local import keeps the finite evidence-model implementation independent of
    # the frozen policy-version registry while still validating the public payload.
    from research_decision_engine.information_gain_table import FiniteTableEvidenceModel

    evidence_model = FiniteTableEvidenceModel.from_payload(
        _closed_mapping(config["evidence_model"], field_name="evidence_model")
    )
    evidence_model.validate_candidate_ids(normalized_candidate_ids)
    return {
        "evidence_model": evidence_model.to_payload(),
        "tie_break": RUNSPEC_CANDIDATE_ORDER,
    }, None


def _validated_candidate_ids(candidate_ids: Sequence[str]) -> tuple[str, ...]:
    if type(candidate_ids) not in (list, tuple):
        raise PolicyConfigurationError("Candidate IDs must be a finite ordered list or tuple.")
    normalized = tuple(candidate_ids)
    if not normalized:
        raise PolicyConfigurationError("Candidate IDs must not be empty.")
    if any(type(candidate_id) is not str or not candidate_id for candidate_id in normalized):
        raise PolicyConfigurationError("Every candidate ID must be a nonempty exact string.")
    if len(normalized) != len(set(normalized)):
        raise PolicyConfigurationError("Candidate IDs must be unique.")
    return normalized


def _closed_mapping(value: object, *, field_name: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise PolicyConfigurationError(f"{field_name} must be a JSON object.")
    items = tuple(cast(Mapping[object, object], value).items())
    if any(type(key) is not str for key, _ in items):
        raise PolicyConfigurationError(f"{field_name} keys must be exact strings.")
    keys = tuple(cast(str, key) for key, _ in items)
    if len(keys) != len(set(keys)):
        raise PolicyConfigurationError(f"{field_name} contains duplicate keys.")
    return {cast(str, key): item for key, item in items}


def _normalized_utility(value: object) -> UtilityNumber:
    if type(value) is int:
        if not _JSON_INT_MIN <= value <= _JSON_INT_MAX:
            raise InvalidCandidateUtilityError(
                "Candidate utility integers must fit in a signed 64-bit integer."
            )
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise NonfiniteUtilityError("Candidate utilities must be finite.")
        return 0.0 if value == 0.0 else value
    raise InvalidCandidateUtilityError(
        "Candidate utilities must be JSON numbers, not booleans or coercible values."
    )
