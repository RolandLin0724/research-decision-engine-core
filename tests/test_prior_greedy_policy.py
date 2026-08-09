from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any, cast

import pytest

from research_decision_engine.generic_policies import PriorGreedyPolicy
from research_decision_engine.policy_contracts import (
    PRIOR_GREEDY_CLASSIFICATION,
    PolicyConfigurationError,
    PolicyContractError,
    UnsupportedPolicyForSchemaError,
)
from research_decision_engine.run_spec import CandidateSpec
from research_decision_engine.run_spec_v2 import RunSpecV2


def _spec(
    *,
    candidates: list[CandidateSpec] | None = None,
    utilities: Mapping[str, object] | None = None,
    objective_direction: str = "maximize",
) -> RunSpecV2:
    actual_candidates = (
        [
            CandidateSpec("candidate-a", {"declared_parameter": -100}),
            CandidateSpec("candidate-b", {"declared_parameter": 0}),
            CandidateSpec("candidate-c", {"declared_parameter": 100}),
        ]
        if candidates is None
        else candidates
    )
    actual_utilities = (
        {"candidate-a": 1, "candidate-b": 3.0, "candidate-c": 2} if utilities is None else utilities
    )
    return RunSpecV2(
        candidates=actual_candidates,
        policy_id="greedy_prior",
        policy_config={
            "utility_by_candidate_id": actual_utilities,
            "tie_break": "runspec_candidate_order",
        },
        policy_seed=None,
        experiment_count_budget=len(actual_candidates),
        adapter_id="adapter",
        adapter_version="1",
        objective_name="quality",
        objective_direction=cast(Any, objective_direction),
    )


def test_prior_greedy_public_identity_and_narrow_input_surface_are_exact() -> None:
    policy = PriorGreedyPolicy(_spec())

    assert policy.name == "greedy_prior"
    assert policy.semantic_classification == PRIOR_GREEDY_CLASSIFICATION
    assert policy.tie_break == "runspec_candidate_order"
    assert tuple(inspect.signature(PriorGreedyPolicy).parameters) == ("run_spec",)
    assert tuple(inspect.signature(PriorGreedyPolicy.select).parameters) == (
        "self",
        "completed_candidate_ids",
    )


def test_prior_greedy_selects_deterministic_maximum_without_history() -> None:
    policy = PriorGreedyPolicy(_spec())

    assert policy.select(set()).candidate_id == "candidate-b"
    assert policy.select(frozenset()).candidate_id == "candidate-b"
    assert policy.select([]).candidate_id == "candidate-b"
    assert policy.prior_utility("candidate-b") == 3.0


def test_prior_greedy_uses_exact_runspec_order_for_utility_ties() -> None:
    candidates = [
        CandidateSpec("candidate-c", {"ignored": 3}),
        CandidateSpec("candidate-a", {"ignored": 1}),
        CandidateSpec("candidate-b", {"ignored": 2}),
    ]
    utilities = {"candidate-a": 10, "candidate-b": 9, "candidate-c": 10}
    policy = PriorGreedyPolicy(_spec(candidates=candidates, utilities=utilities))

    assert policy.select(set()).candidate_id == "candidate-c"
    assert policy.select({"candidate-c"}).candidate_id == "candidate-a"


def test_completed_candidates_are_excluded_and_never_selected_twice() -> None:
    policy = PriorGreedyPolicy(_spec())
    completed: set[str] = set()
    selected: list[str] = []

    for _ in range(3):
        candidate = policy.select(completed)
        assert candidate.candidate_id not in completed
        completed.add(candidate.candidate_id)
        selected.append(candidate.candidate_id)

    assert selected == ["candidate-b", "candidate-c", "candidate-a"]
    assert len(selected) == len(set(selected))
    with pytest.raises(ValueError, match="No available candidates remain"):
        policy.select(completed)


def test_selection_ignores_candidate_parameters_objective_direction_and_completion_order() -> None:
    utilities = {"candidate-a": 1, "candidate-b": 3, "candidate-c": 2}
    first = PriorGreedyPolicy(_spec(utilities=utilities, objective_direction="maximize"))
    changed_parameters = [
        CandidateSpec("candidate-a", {"arbitrary": 999999}),
        CandidateSpec("candidate-b", {"arbitrary": -999999}),
        CandidateSpec("candidate-c", {"arbitrary": 0}),
    ]
    second = PriorGreedyPolicy(
        _spec(
            candidates=changed_parameters,
            utilities=utilities,
            objective_direction="minimize",
        )
    )

    assert first.select(["candidate-b"]).candidate_id == "candidate-c"
    assert first.select(["candidate-b", "candidate-c"]).candidate_id == "candidate-a"
    assert first.select(["candidate-c", "candidate-b"]).candidate_id == "candidate-a"
    assert second.select(["candidate-b"]).candidate_id == "candidate-c"


def test_selection_metadata_is_closed_deterministic_and_truth_free() -> None:
    policy = PriorGreedyPolicy(_spec())
    expected = {
        "policy_id": "greedy_prior",
        "selected_candidate_id": "candidate-c",
        "selected_prior_utility": 2,
        "eligible_candidate_count": 2,
        "tie_break": "runspec_candidate_order",
    }

    assert policy.selection_metadata({"candidate-b"}) == expected
    assert policy.selection_metadata({"candidate-b"}) == expected
    assert "observation" not in expected
    assert "true_value" not in expected
    assert "predicted" not in expected


def test_policy_isolates_runspec_config_properties_and_returned_candidate_mutation() -> None:
    spec = _spec()
    policy = PriorGreedyPolicy(spec)
    before = policy.selection_metadata(set())

    detached = cast(dict[str, Any], policy.utility_by_candidate_id)
    detached["candidate-b"] = -100
    object.__setattr__(spec, "_policy_config_json", "{}")
    selected = policy.select(set())
    object.__setattr__(selected, "candidate_id", "mutated")

    assert policy.selection_metadata(set()) == before
    assert policy.select(set()).candidate_id == "candidate-b"


def test_prior_greedy_rejects_wrong_runspec_policy_and_invalid_completed_ids() -> None:
    greedy = PriorGreedyPolicy(_spec())
    random_spec = RunSpecV2(
        candidates=[CandidateSpec("candidate-a", {})],
        policy_id="random",
        policy_config={},
        policy_seed=1,
        experiment_count_budget=1,
        adapter_id="adapter",
        adapter_version="1",
        objective_name="quality",
        objective_direction="maximize",
    )

    with pytest.raises(UnsupportedPolicyForSchemaError):
        PriorGreedyPolicy(random_spec)
    with pytest.raises(TypeError, match="exact RunSpecV2"):
        PriorGreedyPolicy(cast(Any, object()))
    with pytest.raises(PolicyContractError):
        greedy.select({"unknown-candidate"})
    with pytest.raises(TypeError, match="exact string"):
        greedy.select(cast(Any, {1}))


def test_prior_greedy_constructor_revalidates_canonical_config_fail_closed() -> None:
    spec = _spec()
    object.__setattr__(spec, "_policy_config_json", '{"tie_break":"runspec_candidate_order"}')

    with pytest.raises(PolicyConfigurationError):
        PriorGreedyPolicy(spec)
