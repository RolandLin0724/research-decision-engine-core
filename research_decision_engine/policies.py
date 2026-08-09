"""Decision policies for the first milestone."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence, Set
from typing import Protocol

from research_decision_engine.types import Candidate, ExperimentRecord


class DecisionPolicy(Protocol):
    name: str

    def select(self, candidates: list[Candidate], history: list[ExperimentRecord]) -> Candidate:
        """Select the next candidate to evaluate."""


class _CandidateIdentity(Protocol):
    @property
    def candidate_id(self) -> str:
        """Return the stable candidate identity."""


class RandomPolicy:
    name = "random"

    def __init__(self, seed: int) -> None:
        self._random = random.Random(seed)

    def select(self, candidates: list[Candidate], history: list[ExperimentRecord]) -> Candidate:
        return _select_random_available(
            candidates,
            {record.candidate.candidate_id for record in history},
            self._random,
        )


class GreedyPredictedPerformancePolicy:
    name = "greedy"

    def select(self, candidates: list[Candidate], history: list[ExperimentRecord]) -> Candidate:
        available = _available_candidates(candidates, history)
        if not available:
            raise ValueError("No available candidates remain.")
        if not history:
            return available[0]
        return max(
            available,
            key=lambda candidate: (self._predict(candidate, history), candidate.candidate_id),
        )

    def _predict(self, candidate: Candidate, history: list[ExperimentRecord]) -> float:
        weighted_total = 0.0
        weight_total = 0.0
        for record in history:
            distance = _feature_distance(candidate, record.candidate)
            weight = 1.0 / (distance + 0.001)
            weighted_total += weight * record.observed_value
            weight_total += weight
        return weighted_total / weight_total


def build_policy(policy_name: str, seed: int) -> DecisionPolicy:
    if policy_name == "random":
        return RandomPolicy(seed=seed)
    if policy_name == "greedy":
        return GreedyPredictedPerformancePolicy()
    raise ValueError(f"Unknown policy: {policy_name}")


def _available_candidates(
    candidates: list[Candidate], history: list[ExperimentRecord]
) -> list[Candidate]:
    completed = {record.candidate.candidate_id for record in history}
    return [candidate for candidate in candidates if candidate.candidate_id not in completed]


def _select_random_available[CandidateT: _CandidateIdentity](
    candidates: Sequence[CandidateT],
    completed_candidate_ids: Set[str],
    random_source: random.Random,
) -> CandidateT:
    """Select by current RandomPolicy semantics without exposing history records."""

    available = [
        candidate
        for candidate in candidates
        if candidate.candidate_id not in completed_candidate_ids
    ]
    if not available:
        raise ValueError("No available candidates remain.")
    return random_source.choice(available)


def _feature_distance(left: Candidate, right: Candidate) -> float:
    lr = math.log10(left.learning_rate) - math.log10(right.learning_rate)
    reg = math.log10(left.regularization) - math.log10(right.regularization)
    width = (left.model_width - right.model_width) / 96.0
    optimizer = 0.0 if left.optimizer == right.optimizer else 1.0
    return math.sqrt(lr * lr + reg * reg + width * width + optimizer * optimizer)
