from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, fields
from typing import Any, cast

import pytest

from research_decision_engine import (
    CandidateSpec,
    CompletedWorkloadExperiment,
    NormalizedObservation,
    RunSpec,
)


def _spec(
    *,
    candidates: list[CandidateSpec] | tuple[CandidateSpec, ...] | None = None,
    experiment_count_budget: int = 1,
    cost_budget: float | None = None,
) -> RunSpec:
    return RunSpec(
        candidates=(
            [CandidateSpec("candidate-a", {"x": 1.0})] if candidates is None else candidates
        ),
        policy_id="random",
        policy_config={},
        policy_seed=7,
        experiment_count_budget=experiment_count_budget,
        cost_budget=cost_budget,
        adapter_id="python-score",
        adapter_version="1",
        objective_name="quality",
        objective_direction="maximize",
        tie_break="candidate-order",
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


def test_run_spec_valid_construction_is_immutable_and_ordered() -> None:
    candidates = [
        CandidateSpec("candidate-b", {"x": 2}),
        CandidateSpec("candidate-a", {"x": 1}),
    ]
    spec = _spec(candidates=candidates, experiment_count_budget=2, cost_budget=4.0)

    assert spec.schema == "rde-core-run-spec/v1"
    assert tuple(candidate.candidate_id for candidate in spec.candidates) == (
        "candidate-b",
        "candidate-a",
    )
    assert spec.policy_config == {}
    assert spec.cost_budget == 4.0
    with pytest.raises(FrozenInstanceError):
        cast(Any, spec).policy_seed = 99
    with pytest.raises(FrozenInstanceError):
        cast(Any, spec.candidates[0]).candidate_id = "changed"


def test_run_spec_rejects_empty_duplicate_and_invalid_candidate_sets() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        _spec(candidates=[])
    with pytest.raises(ValueError, match="must be unique"):
        _spec(
            candidates=[CandidateSpec("duplicate", {}), CandidateSpec("duplicate", {})],
            experiment_count_budget=2,
        )
    with pytest.raises(ValueError, match="nonempty"):
        CandidateSpec("", {})
    with pytest.raises(TypeError, match="list or tuple"):
        _spec(candidates=cast(Any, {CandidateSpec("candidate-a", {})}))


def test_run_spec_literal_fields_require_exact_strings() -> None:
    class EqualsEveryString:
        def __eq__(self, other: object) -> bool:
            return True

    with pytest.raises(ValueError, match="objective_direction"):
        RunSpec(
            candidates=[CandidateSpec("candidate-a", {})],
            policy_id="random",
            policy_config={},
            policy_seed=1,
            experiment_count_budget=1,
            adapter_id="adapter",
            adapter_version="1",
            objective_name="score",
            objective_direction=cast(Any, EqualsEveryString()),
        )
    with pytest.raises(ValueError, match="tie_break"):
        RunSpec(
            candidates=[CandidateSpec("candidate-a", {})],
            policy_id="random",
            policy_config={},
            policy_seed=1,
            experiment_count_budget=1,
            adapter_id="adapter",
            adapter_version="1",
            objective_name="score",
            objective_direction="maximize",
            tie_break=cast(Any, EqualsEveryString()),
        )


@pytest.mark.parametrize("budget", [0, -1, True, 2])
def test_run_spec_rejects_invalid_experiment_count_budget(budget: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _spec(experiment_count_budget=cast(Any, budget))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_run_spec_and_observation_reject_nonfinite_values(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        CandidateSpec("candidate-a", {"nested": [value]})
    with pytest.raises(ValueError, match="finite"):
        _spec(cost_budget=value)
    with pytest.raises(ValueError, match="finite"):
        NormalizedObservation(value)


def test_run_spec_canonical_bytes_use_the_exact_recipe_and_fingerprint() -> None:
    spec = _spec(candidates=[CandidateSpec("候选-b", {"z": [1, {"β": -0.0}], "a": True})])
    expected = (
        '{"adapter":{"id":"python-score","version":"1"},'
        '"budget":{"cost":null,"experiment_count":1},'
        '"candidates":[{"candidate_id":"候选-b","parameters":'
        '{"a":true,"z":[1,{"β":0.0}]}}],'
        '"objective":{"direction":"maximize","name":"quality"},'
        '"policy":{"config":{},"id":"random","seed":7},'
        '"schema":"rde-core-run-spec/v1","tie_break":"candidate-order"}\n'
    ).encode()

    assert spec.to_canonical_bytes() == expected
    assert spec.to_canonical_bytes().endswith(b"\n")
    assert not spec.to_canonical_bytes().endswith(b"\n\n")
    assert spec.fingerprint() == hashlib.sha256(expected).hexdigest()


def test_run_spec_round_trip_is_exact_and_rejects_unknown_or_unsupported_fields() -> None:
    spec = _spec(cost_budget=2.5)
    encoded = spec.to_canonical_bytes()

    decoded = RunSpec.from_canonical_bytes(encoded)
    assert decoded == spec
    assert decoded.to_canonical_bytes() == encoded
    assert decoded.fingerprint() == spec.fingerprint()

    payload = json.loads(encoded)
    payload["unknown"] = None
    with pytest.raises(ValueError, match="fields differ"):
        RunSpec.from_canonical_bytes(_canonical(payload))

    del payload["unknown"]
    payload["schema"] = "rde-core-run-spec/v2"
    with pytest.raises(ValueError, match="Unsupported RunSpec schema"):
        RunSpec.from_canonical_bytes(_canonical(payload))

    payload["schema"] = spec.schema
    payload["candidates"][0]["future_truth"] = 0.99
    with pytest.raises(ValueError, match="violates the v1 contract"):
        RunSpec.from_canonical_bytes(_canonical(payload))


def test_run_spec_decoder_rejects_duplicate_keys_and_noncanonical_bytes() -> None:
    encoded = _spec().to_canonical_bytes()
    duplicate = encoded.replace(
        b'"schema":"rde-core-run-spec/v1"',
        b'"schema":"rde-core-run-spec/v1","schema":"rde-core-run-spec/v1"',
    )
    with pytest.raises(ValueError, match="strict UTF-8 JSON"):
        RunSpec.from_canonical_bytes(duplicate)

    payload = json.loads(encoded)
    noncanonical = (
        b"\xef\xbb\xbf" + encoded,
        encoded.removesuffix(b"\n"),
        encoded + b"\n",
        json.dumps(payload, ensure_ascii=True, indent=2).encode() + b"\n",
    )
    for candidate in noncanonical:
        with pytest.raises(ValueError):
            RunSpec.from_canonical_bytes(candidate)


def test_candidate_order_changes_identity_but_mapping_order_does_not() -> None:
    first = CandidateSpec("candidate-a", {"b": 2, "a": 1})
    same = CandidateSpec("candidate-a", {"a": 1, "b": 2})
    second = CandidateSpec("candidate-b", {"x": 3})

    assert first == same
    assert (
        _spec(candidates=[first]).to_canonical_bytes()
        == _spec(candidates=[same]).to_canonical_bytes()
    )
    forward = _spec(candidates=[first, second], experiment_count_budget=2)
    reverse = _spec(candidates=[second, first], experiment_count_budget=2)
    assert forward != reverse
    assert forward.to_canonical_bytes() != reverse.to_canonical_bytes()
    assert forward.fingerprint() != reverse.fingerprint()


def test_candidate_parameter_identity_is_type_sensitive_and_normalizes_negative_zero() -> None:
    boolean = CandidateSpec("candidate-a", {"x": True})
    integer = CandidateSpec("candidate-a", {"x": 1})
    floating = CandidateSpec("candidate-a", {"x": 1.0})
    negative_zero = CandidateSpec("candidate-a", {"x": -0.0})
    positive_zero = CandidateSpec("candidate-a", {"x": 0.0})

    assert len({boolean, integer, floating}) == 3
    assert negative_zero == positive_zero
    assert (
        _spec(candidates=[negative_zero]).to_canonical_bytes()
        == _spec(candidates=[positive_zero]).to_canonical_bytes()
    )


def test_candidate_and_runspec_isolate_all_caller_mutation() -> None:
    nested = {"outer": {"values": [1, 2]}}
    candidate = CandidateSpec("candidate-a", nested)
    candidates = [candidate]
    spec = _spec(candidates=candidates)
    before = spec.to_canonical_bytes()

    cast(dict[str, Any], nested["outer"])["values"].append(3)
    candidates.append(CandidateSpec("candidate-b", {}))
    detached = cast(dict[str, Any], candidate.parameters)
    cast(list[int], cast(dict[str, Any], detached["outer"])["values"]).append(4)
    object.__setattr__(candidate, "candidate_id", "mutated-after-runspec-construction")

    assert spec.to_canonical_bytes() == before
    assert spec.candidates[0].candidate_id == "candidate-a"
    assert spec.candidates[0].parameters == {"outer": {"values": [1, 2]}}
    assert candidate.candidate_id == "mutated-after-runspec-construction"


def test_json_boundary_rejects_cycles_bad_keys_and_unsupported_objects() -> None:
    empty_strings = CandidateSpec("candidate-a", {"": "", "nested": [""]})
    assert empty_strings.parameters == {"": "", "nested": [""]}

    cycle: list[object] = []
    cycle.append(cycle)
    with pytest.raises(ValueError, match="cycle"):
        CandidateSpec("candidate-a", {"cycle": cycle})
    with pytest.raises(TypeError, match="keys must be strings"):
        CandidateSpec("candidate-a", cast(Any, {1: "not-a-string-key"}))
    with pytest.raises(TypeError, match="unsupported type"):
        CandidateSpec("candidate-a", {"set": {1, 2}})
    with pytest.raises(ValueError, match="valid UTF-8"):
        CandidateSpec("candidate-a", {"bad": "\ud800"})


def test_public_records_and_canonical_payload_have_no_hidden_truth_field() -> None:
    public_records = (CandidateSpec, NormalizedObservation, RunSpec, CompletedWorkloadExperiment)
    assert all(
        "true_value" not in {field.name for field in fields(record)} for record in public_records
    )
    spec = _spec()
    assert b"true_value" not in spec.to_canonical_bytes()
    assert not hasattr(spec.candidates[0], "true_value")
    assert not hasattr(NormalizedObservation(1.0), "true_value")
