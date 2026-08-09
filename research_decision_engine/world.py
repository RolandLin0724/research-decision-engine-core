"""Deterministic synthetic experimental world."""

from __future__ import annotations

import hashlib
import math

from research_decision_engine.types import Candidate


class DeterministicSyntheticWorld:
    """A small finite world with a hidden, deterministic response surface."""

    def candidates(self) -> list[Candidate]:
        learning_rates = [0.001, 0.003, 0.01, 0.03]
        regularizations = [0.0001, 0.001, 0.01]
        widths = [32, 64, 128]
        optimizers = ["sgd", "adam"]

        candidates: list[Candidate] = []
        index = 0
        for learning_rate in learning_rates:
            for regularization in regularizations:
                for model_width in widths:
                    for optimizer in optimizers:
                        candidates.append(
                            Candidate(
                                candidate_id=f"cand-{index:03d}",
                                learning_rate=learning_rate,
                                regularization=regularization,
                                model_width=model_width,
                                optimizer=optimizer,
                            )
                        )
                        index += 1
        return candidates

    def evaluate(self, candidate: Candidate) -> tuple[float, float, float]:
        """Return observed value, true value, and synthetic compute cost."""

        true_value = self.true_value(candidate)
        observed_value = true_value + self._noise(candidate.candidate_id)
        cost = self.cost(candidate)
        return observed_value, true_value, cost

    def true_value(self, candidate: Candidate) -> float:
        lr_score = 1.0 - abs(math.log10(candidate.learning_rate) - math.log10(0.01)) / 2.0
        reg_score = 1.0 - abs(math.log10(candidate.regularization) - math.log10(0.001)) / 2.0
        width_score = 1.0 - abs(candidate.model_width - 96) / 96.0
        optimizer_bonus = 0.08 if candidate.optimizer == "adam" else 0.0
        interaction = (
            0.05 if candidate.optimizer == "adam" and candidate.learning_rate <= 0.01 else -0.02
        )
        return round(
            0.45 * lr_score + 0.25 * reg_score + 0.22 * width_score + optimizer_bonus + interaction,
            6,
        )

    def cost(self, candidate: Candidate) -> float:
        optimizer_cost = 1.2 if candidate.optimizer == "adam" else 1.0
        return round((candidate.model_width / 32.0) * optimizer_cost, 6)

    def _noise(self, candidate_id: str) -> float:
        digest = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) % 1001
        return round((bucket / 1000.0 - 0.5) * 0.02, 6)
