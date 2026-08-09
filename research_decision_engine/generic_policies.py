"""Finite static policies for versioned generic Core workloads."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import ClassVar, Literal, cast

from research_decision_engine.policy_contracts import (
    GREEDY_PRIOR_POLICY_ID,
    PRIOR_GREEDY_CLASSIFICATION,
    RUNSPEC_CANDIDATE_ORDER,
    PolicyContractError,
    UnsupportedPolicyForSchemaError,
    UtilityNumber,
    _normalized_v2_policy,
)
from research_decision_engine.run_spec import CandidateSpec
from research_decision_engine.run_spec_v2 import RunSpecV2


@dataclass(frozen=True, slots=True, init=False)
class PriorGreedyPolicy:
    """Select the highest fixed declared utility, breaking ties by RunSpec order.

    The policy receives no observations, adapters, scorer callables, or candidate
    parameter interpretation surface. Its only changing input is the collection
    of completed candidate IDs. Declared utilities are copied from the canonical
    RunSpec v2 configuration and never updated.
    """

    name: ClassVar[Literal["greedy_prior"]] = "greedy_prior"
    semantic_classification: ClassVar[Literal["STATIC_TRUTH_FREE_PRIOR_UTILITY_GREEDY"]] = (
        "STATIC_TRUTH_FREE_PRIOR_UTILITY_GREEDY"
    )
    tie_break: ClassVar[Literal["runspec_candidate_order"]] = "runspec_candidate_order"

    _candidates: tuple[CandidateSpec, ...] = field(repr=False)
    _utility_items: tuple[tuple[str, UtilityNumber], ...] = field(repr=False)
    _candidate_ids: frozenset[str] = field(repr=False)

    def __init__(self, run_spec: RunSpecV2) -> None:
        if type(run_spec) is not RunSpecV2:
            raise TypeError("run_spec must be an exact RunSpecV2.")
        if run_spec.policy_id != GREEDY_PRIOR_POLICY_ID:
            raise UnsupportedPolicyForSchemaError(
                "PriorGreedyPolicy requires a greedy_prior RunSpec v2."
            )

        candidates = tuple(
            CandidateSpec(candidate.candidate_id, candidate.parameters)
            for candidate in run_spec.candidates
        )
        candidate_ids = tuple(candidate.candidate_id for candidate in candidates)
        normalized_config, normalized_seed = _normalized_v2_policy(
            candidate_ids=candidate_ids,
            policy_id=run_spec.policy_id,
            policy_config=run_spec.policy_config,
            policy_seed=run_spec.policy_seed,
        )
        if normalized_seed is not None:
            raise AssertionError("greedy_prior validation produced a random seed.")
        raw_utilities = normalized_config["utility_by_candidate_id"]
        if type(raw_utilities) is not dict:
            raise AssertionError("greedy_prior validation produced a non-object utility map.")
        utilities = cast(dict[str, UtilityNumber], raw_utilities)

        object.__setattr__(self, "_candidates", candidates)
        object.__setattr__(
            self,
            "_utility_items",
            tuple((candidate_id, utilities[candidate_id]) for candidate_id in candidate_ids),
        )
        object.__setattr__(self, "_candidate_ids", frozenset(candidate_ids))

    @property
    def utility_by_candidate_id(self) -> Mapping[str, UtilityNumber]:
        """Return a detached utility map in exact RunSpec candidate order."""

        return dict(self._utility_items)

    def prior_utility(self, candidate_id: str) -> UtilityNumber:
        """Return the fixed declared utility for one RunSpec candidate ID."""

        if type(candidate_id) is not str or not candidate_id:
            raise TypeError("candidate_id must be a nonempty exact string.")
        for known_id, utility in self._utility_items:
            if candidate_id == known_id:
                return utility
        raise KeyError("candidate_id is not present in the RunSpec.")

    def select(self, completed_candidate_ids: Collection[str]) -> CandidateSpec:
        """Select one eligible candidate without observing outcomes or executing work."""

        candidate, _ = self._select_with_eligible_count(completed_candidate_ids)
        return candidate

    def selection_metadata(self, completed_candidate_ids: Collection[str]) -> Mapping[str, object]:
        """Return the smallest closed deterministic decision/rationale binding."""

        candidate, eligible_count = self._select_with_eligible_count(completed_candidate_ids)
        return {
            "policy_id": GREEDY_PRIOR_POLICY_ID,
            "selected_candidate_id": candidate.candidate_id,
            "selected_prior_utility": self.prior_utility(candidate.candidate_id),
            "eligible_candidate_count": eligible_count,
            "tie_break": RUNSPEC_CANDIDATE_ORDER,
        }

    def _select_with_eligible_count(
        self, completed_candidate_ids: Collection[str]
    ) -> tuple[CandidateSpec, int]:
        if type(completed_candidate_ids) is str or not isinstance(
            completed_candidate_ids, Collection
        ):
            raise TypeError("completed_candidate_ids must be a finite collection of strings.")
        completed_items = tuple(completed_candidate_ids)
        if any(type(candidate_id) is not str for candidate_id in completed_items):
            raise TypeError("Every completed candidate ID must be an exact string.")
        completed = frozenset(completed_items)
        if not completed <= self._candidate_ids:
            raise PolicyContractError(
                "Completed candidate IDs must belong to the exact RunSpec candidate set."
            )

        utilities = dict(self._utility_items)
        selected: CandidateSpec | None = None
        selected_utility: UtilityNumber | None = None
        eligible_count = 0
        for candidate in self._candidates:
            if candidate.candidate_id in completed:
                continue
            eligible_count += 1
            utility = utilities[candidate.candidate_id]
            if selected is None or selected_utility is None or utility > selected_utility:
                selected = candidate
                selected_utility = utility

        if selected is None:
            raise ValueError("No available candidates remain.")
        return CandidateSpec(selected.candidate_id, selected.parameters), eligible_count


assert PriorGreedyPolicy.name == GREEDY_PRIOR_POLICY_ID
assert PriorGreedyPolicy.semantic_classification == PRIOR_GREEDY_CLASSIFICATION
assert PriorGreedyPolicy.tie_break == RUNSPEC_CANDIDATE_ORDER
