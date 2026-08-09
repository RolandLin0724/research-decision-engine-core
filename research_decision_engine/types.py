"""Core dataclasses for experiment decisions and records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class Candidate:
    """A synthetic experiment configuration."""

    candidate_id: str
    learning_rate: float
    regularization: float
    model_width: int
    optimizer: str

    def params(self) -> dict[str, int | float | str]:
        return {
            "learning_rate": self.learning_rate,
            "regularization": self.regularization,
            "model_width": self.model_width,
            "optimizer": self.optimizer,
        }


@dataclass(frozen=True, slots=True)
class ExperimentRecord:
    """A completed experiment record stored in SQLite."""

    record_id: int | None
    candidate: Candidate
    policy: str
    observed_value: float
    true_value: float
    cost: float
    created_at: str

    @classmethod
    def new(
        cls,
        *,
        candidate: Candidate,
        policy: str,
        observed_value: float,
        true_value: float,
        cost: float,
    ) -> ExperimentRecord:
        return cls(
            record_id=None,
            candidate=candidate,
            policy=policy,
            observed_value=observed_value,
            true_value=true_value,
            cost=cost,
            created_at=datetime.now(UTC).isoformat(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "candidate_id": self.candidate.candidate_id,
            "policy": self.policy,
            "observed_value": self.observed_value,
            "true_value": self.true_value,
            "cost": self.cost,
            "created_at": self.created_at,
            "params": self.candidate.params(),
        }


@dataclass(frozen=True, slots=True)
class CompletedExperiment:
    """A successful experiment projection that excludes benchmark-only truth."""

    record_id: int
    candidate: Candidate
    observed_value: float
    created_at: str
