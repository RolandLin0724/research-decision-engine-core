from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from typing import Any, cast

import pytest

from research_decision_engine.policy_contracts import (
    GREEDY_PRIOR_POLICY_ID,
    REPLAY_CONTRACT_V1,
    REPLAY_CONTRACT_V2,
    RUN_BUNDLE_V1_SCHEMA,
    RUN_BUNDLE_V2_SCHEMA,
    RUN_SPEC_V1_SCHEMA,
    RUN_SPEC_V2_SCHEMA,
    DeterministicPolicySeedError,
    ExtraCandidateUtilityError,
    InvalidCandidateUtilityError,
    InvalidPolicyTieBreakError,
    MissingCandidateUtilityError,
    NonfiniteUtilityError,
    PolicyConfigurationError,
    RunSpecVersionMismatchError,
    UnsupportedPolicyForSchemaError,
    UnsupportedPolicyIdentityError,
    policy_contract_for_schema,
    policy_identity_contract,
    supported_policy_identities,
)
from research_decision_engine.run_spec import CandidateSpec, RunSpec
from research_decision_engine.run_spec_v2 import RunSpecV2


def _candidates() -> list[CandidateSpec]:
    return [
        CandidateSpec("candidate-b", {"x": 2}),
        CandidateSpec("candidate-a", {"x": 1}),
    ]


def _spec(
    *,
    policy_id: str = GREEDY_PRIOR_POLICY_ID,
    policy_config: Mapping[str, object] | None = None,
    policy_seed: int | None = None,
    candidates: list[CandidateSpec] | tuple[CandidateSpec, ...] | None = None,
    tie_break: Any = "runspec_candidate_order",
) -> RunSpecV2:
    actual_candidates = _candidates() if candidates is None else candidates
    if policy_config is None:
        policy_config = {
            "utility_by_candidate_id": {"candidate-b": 2, "candidate-a": 1.5},
            "tie_break": "runspec_candidate_order",
        }
    return RunSpecV2(
        candidates=actual_candidates,
        policy_id=policy_id,
        policy_config=policy_config,
        policy_seed=policy_seed,
        experiment_count_budget=len(actual_candidates),
        cost_budget=4.0,
        adapter_id="python-score",
        adapter_version="1",
        objective_name="quality",
        objective_direction="maximize",
        tie_break=cast(Any, tie_break),
    )


def _random_v1() -> RunSpec:
    return RunSpec(
        candidates=[CandidateSpec("candidate-a", {})],
        policy_id="random",
        policy_config={},
        policy_seed=7,
        experiment_count_budget=1,
        adapter_id="adapter",
        adapter_version="1",
        objective_name="quality",
        objective_direction="maximize",
    )


def _canonical(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def test_policy_introspection_is_frozen_and_exact_by_schema() -> None:
    v1 = policy_contract_for_schema(RUN_SPEC_V1_SCHEMA)
    v2 = policy_contract_for_schema(RUN_SPEC_V2_SCHEMA)

    assert v1.run_bundle_schema == RUN_BUNDLE_V1_SCHEMA
    assert v1.replay_contract == REPLAY_CONTRACT_V1
    assert v1.supported_policy_ids == ("random",)
    assert v2.run_bundle_schema == RUN_BUNDLE_V2_SCHEMA
    assert v2.replay_contract == REPLAY_CONTRACT_V2
    assert supported_policy_identities(RUN_SPEC_V2_SCHEMA) == ("random", "greedy_prior")
    assert policy_identity_contract(RUN_SPEC_V2_SCHEMA, "greedy_prior").seed_requirement == (
        "forbidden"
    )
    with pytest.raises(FrozenInstanceError):
        cast(Any, v2).run_bundle_schema = "changed"
    with pytest.raises(UnsupportedPolicyForSchemaError):
        policy_identity_contract(RUN_SPEC_V1_SCHEMA, "greedy_prior")
    with pytest.raises(UnsupportedPolicyForSchemaError):
        policy_identity_contract(RUN_SPEC_V2_SCHEMA, "greedy")
    with pytest.raises(UnsupportedPolicyIdentityError):
        policy_identity_contract(RUN_SPEC_V2_SCHEMA, "module.Class")


def test_run_spec_v2_construction_rejects_every_nonstatic_policy_identity() -> None:
    with pytest.raises(UnsupportedPolicyForSchemaError):
        _spec(policy_id="greedy")
    with pytest.raises(UnsupportedPolicyIdentityError):
        _spec(policy_id="module.Class")


def test_run_spec_v2_random_preserves_explicit_seed_contract() -> None:
    spec = _spec(policy_id="random", policy_config={}, policy_seed=20260804)

    assert spec.schema == RUN_SPEC_V2_SCHEMA
    assert spec.policy_id == "random"
    assert spec.policy_config == {}
    assert spec.policy_seed == 20260804
    assert spec.tie_break == "runspec_candidate_order"
    payload = json.loads(spec.to_canonical_bytes())
    assert payload["policy"] == {"config": {}, "id": "random", "seed": 20260804}


@pytest.mark.parametrize(
    ("config", "seed", "error"),
    [
        ({"unknown": 1}, 7, PolicyConfigurationError),
        ({}, None, PolicyConfigurationError),
        ({}, True, PolicyConfigurationError),
    ],
)
def test_run_spec_v2_random_rejects_noncontract_configuration(
    config: dict[str, object], seed: object, error: type[Exception]
) -> None:
    with pytest.raises(error):
        _spec(
            policy_id="random",
            policy_config=config,
            policy_seed=cast(Any, seed),
        )


def test_run_spec_v2_greedy_prior_is_complete_seedless_and_type_preserving() -> None:
    spec = _spec()

    assert spec.schema == RUN_SPEC_V2_SCHEMA
    assert spec.policy_id == "greedy_prior"
    assert spec.policy_seed is None
    config = cast(dict[str, Any], spec.policy_config)
    utilities = cast(dict[str, Any], config["utility_by_candidate_id"])
    assert utilities == {"candidate-a": 1.5, "candidate-b": 2}
    assert type(utilities["candidate-b"]) is int
    assert type(utilities["candidate-a"]) is float
    payload = json.loads(spec.to_canonical_bytes())
    assert payload["policy"]["seed"] is None
    assert payload["policy"]["config"]["tie_break"] == "runspec_candidate_order"


@pytest.mark.parametrize(
    ("utilities", "error"),
    [
        ({"candidate-b": 2}, MissingCandidateUtilityError),
        (
            {"candidate-b": 2, "candidate-a": 1, "candidate-c": 0},
            ExtraCandidateUtilityError,
        ),
        ({"candidate-b": 2, "candidate-a": True}, InvalidCandidateUtilityError),
        ({"candidate-b": 2, "candidate-a": "1"}, InvalidCandidateUtilityError),
        ({"candidate-b": 2, "candidate-a": 2**63}, InvalidCandidateUtilityError),
        ({"candidate-b": 2, "candidate-a": float("nan")}, NonfiniteUtilityError),
        ({"candidate-b": 2, "candidate-a": float("inf")}, NonfiniteUtilityError),
        ({"candidate-b": 2, "candidate-a": float("-inf")}, NonfiniteUtilityError),
    ],
)
def test_run_spec_v2_rejects_invalid_utility_map(
    utilities: dict[str, object], error: type[Exception]
) -> None:
    with pytest.raises(error):
        _spec(
            policy_config={
                "utility_by_candidate_id": utilities,
                "tie_break": "runspec_candidate_order",
            }
        )


def test_run_spec_v2_requires_map_tie_break_and_forbids_greedy_seed() -> None:
    with pytest.raises(MissingCandidateUtilityError):
        _spec(policy_config={"tie_break": "runspec_candidate_order"})
    with pytest.raises(InvalidPolicyTieBreakError):
        _spec(
            policy_config={
                "utility_by_candidate_id": {"candidate-b": 2, "candidate-a": 1},
                "tie_break": "candidate-order",
            }
        )
    with pytest.raises(InvalidPolicyTieBreakError):
        _spec(tie_break="candidate-order")
    with pytest.raises(DeterministicPolicySeedError):
        _spec(policy_seed=7)


def test_run_spec_v2_isolates_caller_mutation() -> None:
    candidate = CandidateSpec("candidate-b", {"nested": {"values": [1, 2]}})
    candidates = [candidate, CandidateSpec("candidate-a", {})]
    utility_map: dict[str, object] = {"candidate-b": 2, "candidate-a": 1}
    config = {
        "utility_by_candidate_id": utility_map,
        "tie_break": "runspec_candidate_order",
    }
    spec = _spec(candidates=candidates, policy_config=config)
    before = spec.to_canonical_bytes()

    utility_map["candidate-b"] = -99
    utility_map["candidate-c"] = 100
    candidates.reverse()
    detached = cast(dict[str, Any], spec.policy_config)
    cast(dict[str, Any], detached["utility_by_candidate_id"])["candidate-b"] = -100
    object.__setattr__(candidate, "candidate_id", "mutated")

    assert spec.to_canonical_bytes() == before
    assert tuple(item.candidate_id for item in spec.candidates) == (
        "candidate-b",
        "candidate-a",
    )


def test_candidate_order_is_identity_but_utility_map_order_is_not() -> None:
    forward_map = {"candidate-b": 2, "candidate-a": 1}
    reverse_map = {"candidate-a": 1, "candidate-b": 2}
    forward = _spec(
        policy_config={
            "utility_by_candidate_id": forward_map,
            "tie_break": "runspec_candidate_order",
        }
    )
    same = _spec(
        policy_config={
            "tie_break": "runspec_candidate_order",
            "utility_by_candidate_id": reverse_map,
        }
    )
    reverse_candidates = _spec(candidates=list(reversed(_candidates())))

    assert forward.to_canonical_bytes() == same.to_canonical_bytes()
    assert forward.fingerprint() == same.fingerprint()
    assert forward.to_canonical_bytes() != reverse_candidates.to_canonical_bytes()
    assert forward.fingerprint() != reverse_candidates.fingerprint()


def test_integer_and_float_utility_identity_remains_distinct() -> None:
    integer = _spec(
        policy_config={
            "utility_by_candidate_id": {"candidate-b": 2, "candidate-a": 1},
            "tie_break": "runspec_candidate_order",
        }
    )
    floating = _spec(
        policy_config={
            "utility_by_candidate_id": {"candidate-b": 2.0, "candidate-a": 1},
            "tie_break": "runspec_candidate_order",
        }
    )

    assert integer.to_canonical_bytes() != floating.to_canonical_bytes()
    assert integer.fingerprint() != floating.fingerprint()
    assert b'"candidate-b":2}' in integer.to_canonical_bytes()
    assert b'"candidate-b":2.0}' in floating.to_canonical_bytes()


def test_run_spec_v2_canonical_round_trip_and_fingerprint_are_exact() -> None:
    spec = _spec()
    encoded = spec.to_canonical_bytes()
    decoded = RunSpecV2.from_canonical_bytes(encoded)

    assert decoded == spec
    assert decoded.to_canonical_bytes() == encoded
    assert decoded.fingerprint() == hashlib.sha256(encoded).hexdigest()
    assert decoded.fingerprint() == spec.fingerprint()


def test_run_spec_v2_decoder_rejects_duplicate_unknown_and_noncanonical_content() -> None:
    encoded = _spec().to_canonical_bytes()
    duplicate_top = encoded.replace(
        b'"schema":"rde-core-run-spec/v2"',
        b'"schema":"rde-core-run-spec/v2","schema":"rde-core-run-spec/v2"',
    )
    duplicate_utility = encoded.replace(
        b'"candidate-a":1.5', b'"candidate-a":1.5,"candidate-a":1.5'
    )
    for duplicate in (duplicate_top, duplicate_utility):
        with pytest.raises(ValueError, match="strict UTF-8 JSON"):
            RunSpecV2.from_canonical_bytes(duplicate)

    payload = json.loads(encoded)
    payload["policy"]["config"]["metadata"] = "forbidden"
    with pytest.raises(PolicyConfigurationError):
        RunSpecV2.from_canonical_bytes(_canonical(payload))

    for noncanonical in (encoded.removesuffix(b"\n"), encoded + b"\n"):
        with pytest.raises(ValueError, match="not canonical"):
            RunSpecV2.from_canonical_bytes(noncanonical)


def test_v1_and_v2_are_strictly_separate_without_silent_upgrade() -> None:
    v1 = _random_v1()
    with pytest.raises(RunSpecVersionMismatchError):
        RunSpecV2.from_canonical_bytes(v1.to_canonical_bytes())
    with pytest.raises(ValueError, match="Unsupported RunSpec schema"):
        RunSpec.from_canonical_bytes(
            _spec(policy_id="random", policy_config={}, policy_seed=7).to_canonical_bytes()
        )
    with pytest.raises(ValueError, match="only the current Core random policy"):
        RunSpec(
            candidates=[CandidateSpec("candidate-a", {})],
            policy_id="greedy_prior",
            policy_config={},
            policy_seed=7,
            experiment_count_budget=1,
            adapter_id="adapter",
            adapter_version="1",
            objective_name="quality",
            objective_direction="maximize",
        )

    v1_bytes = v1.to_canonical_bytes()
    assert RunSpec.from_canonical_bytes(v1_bytes).to_canonical_bytes() == v1_bytes
