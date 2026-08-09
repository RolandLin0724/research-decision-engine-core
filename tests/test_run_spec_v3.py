from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, cast

import pytest

from research_decision_engine.information_gain_table import FiniteTableEvidenceModel
from research_decision_engine.policy_contracts import (
    INFORMATION_GAIN_TABLE_CLASSIFICATION,
    INFORMATION_GAIN_TABLE_POLICY_ID,
    REPLAY_CONTRACT_V1,
    REPLAY_CONTRACT_V2,
    REPLAY_CONTRACT_V3,
    RUN_BUNDLE_V1_SCHEMA,
    RUN_BUNDLE_V2_SCHEMA,
    RUN_BUNDLE_V3_SCHEMA,
    RUN_SPEC_V1_SCHEMA,
    RUN_SPEC_V2_SCHEMA,
    RUN_SPEC_V3_SCHEMA,
    DeterministicPolicySeedError,
    InvalidPolicyTieBreakError,
    PolicyConfigurationError,
    RunSpecVersionMismatchError,
    UnsupportedPolicyForSchemaError,
    policy_contract_for_schema,
    policy_identity_contract,
    supported_policy_identities,
)
from research_decision_engine.run_spec import CandidateSpec, RunSpec
from research_decision_engine.run_spec_v2 import RunSpecV2
from research_decision_engine.run_spec_v3 import RunSpecV3


def _candidates() -> list[CandidateSpec]:
    return [
        CandidateSpec("candidate-b", {"x": 2}),
        CandidateSpec("candidate-a", {"x": 1}),
    ]


def _evidence_payload() -> dict[str, object]:
    return {
        "hypothesis_ids": ["h-left", "h-right"],
        "prior_weight_by_hypothesis": {"h-left": 1, "h-right": 1},
        "observation_metric": "quality",
        "outcome_ids": ["low", "high"],
        "outcome_thresholds": [0.0],
        "likelihood_row_total": 10,
        "likelihood_weight_by_candidate_id": {
            "candidate-b": {
                "h-left": {"low": 9, "high": 1},
                "h-right": {"low": 1, "high": 9},
            },
            "candidate-a": {
                "h-left": {"low": 5, "high": 5},
                "h-right": {"low": 5, "high": 5},
            },
        },
    }


def _spec(
    *,
    policy_id: str = "information_gain_table",
    policy_config: Mapping[str, object] | None = None,
    policy_seed: int | None = None,
    objective_name: str = "quality",
    candidates: list[CandidateSpec] | tuple[CandidateSpec, ...] | None = None,
    tie_break: Any = "runspec_candidate_order",
) -> RunSpecV3:
    actual_candidates = _candidates() if candidates is None else candidates
    if policy_config is None:
        policy_config = {
            "evidence_model": _evidence_payload(),
            "tie_break": "runspec_candidate_order",
        }
    return RunSpecV3(
        candidates=actual_candidates,
        policy_id=policy_id,
        policy_config=policy_config,
        policy_seed=policy_seed,
        experiment_count_budget=len(actual_candidates),
        cost_budget=4.0,
        adapter_id="python-score",
        adapter_version="1",
        objective_name=objective_name,
        objective_direction="maximize",
        tie_break=cast(Any, tie_break),
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


def test_policy_introspection_adds_only_the_exact_v3_contract() -> None:
    v1 = policy_contract_for_schema(RUN_SPEC_V1_SCHEMA)
    v2 = policy_contract_for_schema(RUN_SPEC_V2_SCHEMA)
    v3 = policy_contract_for_schema(RUN_SPEC_V3_SCHEMA)

    assert (v1.run_bundle_schema, v1.replay_contract, v1.supported_policy_ids) == (
        RUN_BUNDLE_V1_SCHEMA,
        REPLAY_CONTRACT_V1,
        ("random",),
    )
    assert (v2.run_bundle_schema, v2.replay_contract, v2.supported_policy_ids) == (
        RUN_BUNDLE_V2_SCHEMA,
        REPLAY_CONTRACT_V2,
        ("random", "greedy_prior"),
    )
    assert (v3.run_bundle_schema, v3.replay_contract, v3.supported_policy_ids) == (
        RUN_BUNDLE_V3_SCHEMA,
        REPLAY_CONTRACT_V3,
        ("random", "greedy_prior", "information_gain_table"),
    )
    assert supported_policy_identities(RUN_SPEC_V3_SCHEMA) == v3.supported_policy_ids
    identity = policy_identity_contract(RUN_SPEC_V3_SCHEMA, INFORMATION_GAIN_TABLE_POLICY_ID)
    assert (
        identity.semantic_classification,
        identity.required_config_fields,
        identity.seed_requirement,
    ) == (
        INFORMATION_GAIN_TABLE_CLASSIFICATION,
        ("evidence_model", "tie_break"),
        "forbidden",
    )


def test_information_gain_table_is_known_but_fails_closed_for_v1_and_v2() -> None:
    for schema in (RUN_SPEC_V1_SCHEMA, RUN_SPEC_V2_SCHEMA):
        with pytest.raises(UnsupportedPolicyForSchemaError):
            policy_identity_contract(schema, INFORMATION_GAIN_TABLE_POLICY_ID)

    with pytest.raises(ValueError, match="v1 supports only.*random"):
        RunSpec(
            candidates=[CandidateSpec("candidate", {})],
            policy_id=INFORMATION_GAIN_TABLE_POLICY_ID,
            policy_config={},
            policy_seed=1,
            experiment_count_budget=1,
            adapter_id="adapter",
            adapter_version="1",
            objective_name="quality",
            objective_direction="maximize",
        )
    with pytest.raises(UnsupportedPolicyForSchemaError):
        RunSpecV2(
            candidates=[CandidateSpec("candidate", {})],
            policy_id=INFORMATION_GAIN_TABLE_POLICY_ID,
            policy_config={},
            policy_seed=None,
            experiment_count_budget=1,
            adapter_id="adapter",
            adapter_version="1",
            objective_name="quality",
            objective_direction="maximize",
        )


def test_v3_random_and_greedy_preserve_exact_v2_policy_semantics() -> None:
    cases: tuple[tuple[str, dict[str, object], int | None], ...] = (
        ("random", {}, 17),
        (
            "greedy_prior",
            {
                "utility_by_candidate_id": {"candidate-b": 2, "candidate-a": 1.5},
                "tie_break": "runspec_candidate_order",
            },
            None,
        ),
    )
    for policy_id, config, seed in cases:
        v2 = RunSpecV2(
            candidates=_candidates(),
            policy_id=policy_id,
            policy_config=config,
            policy_seed=seed,
            experiment_count_budget=2,
            cost_budget=4.0,
            adapter_id="python-score",
            adapter_version="1",
            objective_name="quality",
            objective_direction="maximize",
        )
        v3 = _spec(policy_id=policy_id, policy_config=config, policy_seed=seed)
        expected_v3_bytes = v2.to_canonical_bytes().replace(
            b'"schema":"rde-core-run-spec/v2"',
            b'"schema":"rde-core-run-spec/v3"',
        )

        assert v3.policy_config == v2.policy_config
        assert v3.policy_seed == v2.policy_seed
        assert v3.evidence_model is None
        assert v3.to_canonical_bytes() == expected_v3_bytes


def test_v3_information_gain_config_is_exact_seedless_and_model_bound() -> None:
    spec = _spec()
    model = spec.evidence_model

    assert spec.schema == RUN_SPEC_V3_SCHEMA
    assert spec.policy_id == INFORMATION_GAIN_TABLE_POLICY_ID
    assert spec.policy_seed is None
    assert model is not None
    assert type(model) is FiniteTableEvidenceModel
    assert model.observation_metric == spec.objective_name == "quality"
    assert cast(dict[str, Any], spec.policy_config) == {
        "evidence_model": model.to_payload(),
        "tie_break": "runspec_candidate_order",
    }
    assert spec.evidence_model is not model
    assert spec.evidence_model is not None
    assert spec.evidence_model.fingerprint() == model.fingerprint()


def test_v3_information_gain_rejects_config_seed_candidate_and_metric_mismatches() -> None:
    with pytest.raises(PolicyConfigurationError, match="explicit evidence_model"):
        _spec(policy_config={"tie_break": "runspec_candidate_order"})
    with pytest.raises(InvalidPolicyTieBreakError):
        _spec(policy_config={"evidence_model": _evidence_payload()})
    with pytest.raises(PolicyConfigurationError, match="unknown fields"):
        _spec(
            policy_config={
                "evidence_model": _evidence_payload(),
                "tie_break": "runspec_candidate_order",
                "metadata": "forbidden",
            }
        )
    with pytest.raises(InvalidPolicyTieBreakError):
        _spec(
            policy_config={
                "evidence_model": _evidence_payload(),
                "tie_break": "candidate-order",
            }
        )
    with pytest.raises(DeterministicPolicySeedError):
        _spec(policy_seed=7)

    missing_candidate = _evidence_payload()
    cast(dict[str, Any], missing_candidate["likelihood_weight_by_candidate_id"]).pop("candidate-a")
    with pytest.raises(ValueError):
        _spec(
            policy_config={
                "evidence_model": missing_candidate,
                "tie_break": "runspec_candidate_order",
            }
        )
    with pytest.raises(PolicyConfigurationError, match="observation_metric.*objective_name"):
        _spec(objective_name="different_metric")
    with pytest.raises(InvalidPolicyTieBreakError):
        _spec(tie_break="candidate-order")


def test_v3_information_gain_isolates_caller_model_mutation() -> None:
    model_payload = _evidence_payload()
    config = {
        "evidence_model": model_payload,
        "tie_break": "runspec_candidate_order",
    }
    spec = _spec(policy_config=config)
    before = spec.to_canonical_bytes()

    cast(dict[str, Any], model_payload["prior_weight_by_hypothesis"])["h-left"] = 999
    cast(dict[str, Any], model_payload["likelihood_weight_by_candidate_id"]).clear()
    cast(dict[str, Any], spec.policy_config)["evidence_model"] = {}

    assert spec.to_canonical_bytes() == before
    assert spec.evidence_model is not None
    assert spec.evidence_model.to_payload() == _evidence_payload()


def test_v3_canonical_round_trip_fingerprint_and_order_identity_are_exact() -> None:
    spec = _spec()
    encoded = spec.to_canonical_bytes()
    decoded = RunSpecV3.from_canonical_bytes(encoded)

    assert decoded == spec
    assert decoded.to_canonical_bytes() == encoded
    assert decoded.fingerprint() == hashlib.sha256(encoded).hexdigest()
    assert decoded.evidence_model is not None
    assert spec.evidence_model is not None
    assert decoded.evidence_model.fingerprint() == spec.evidence_model.fingerprint()

    reversed_candidates = _spec(candidates=tuple(reversed(_candidates())))
    assert reversed_candidates.to_canonical_bytes() != encoded
    assert reversed_candidates.fingerprint() != spec.fingerprint()


def test_v3_decoder_rejects_duplicates_unknown_fields_and_noncanonical_content() -> None:
    encoded = _spec().to_canonical_bytes()
    duplicate_top = encoded.replace(
        b'"schema":"rde-core-run-spec/v3"',
        b'"schema":"rde-core-run-spec/v3","schema":"rde-core-run-spec/v3"',
    )
    with pytest.raises(ValueError, match="strict UTF-8 JSON"):
        RunSpecV3.from_canonical_bytes(duplicate_top)

    payload = json.loads(encoded)
    payload["policy"]["config"]["metadata"] = "forbidden"
    with pytest.raises(PolicyConfigurationError):
        RunSpecV3.from_canonical_bytes(_canonical(payload))

    for noncanonical in (encoded.removesuffix(b"\n"), encoded + b"\n"):
        with pytest.raises(ValueError, match="not canonical"):
            RunSpecV3.from_canonical_bytes(noncanonical)


def test_v1_v2_v3_decoders_are_strictly_separate_without_silent_upgrade() -> None:
    v1 = RunSpec(
        candidates=[CandidateSpec("candidate", {})],
        policy_id="random",
        policy_config={},
        policy_seed=7,
        experiment_count_budget=1,
        adapter_id="adapter",
        adapter_version="1",
        objective_name="quality",
        objective_direction="maximize",
    )
    v2 = RunSpecV2(
        candidates=[CandidateSpec("candidate", {})],
        policy_id="random",
        policy_config={},
        policy_seed=7,
        experiment_count_budget=1,
        adapter_id="adapter",
        adapter_version="1",
        objective_name="quality",
        objective_direction="maximize",
    )
    v3 = _spec(policy_id="random", policy_config={}, policy_seed=7)

    for encoded in (v1.to_canonical_bytes(), v2.to_canonical_bytes()):
        with pytest.raises(RunSpecVersionMismatchError):
            RunSpecV3.from_canonical_bytes(encoded)
    with pytest.raises(RunSpecVersionMismatchError):
        RunSpecV2.from_canonical_bytes(v3.to_canonical_bytes())
    with pytest.raises(ValueError, match="Unsupported RunSpec schema"):
        RunSpec.from_canonical_bytes(v3.to_canonical_bytes())
