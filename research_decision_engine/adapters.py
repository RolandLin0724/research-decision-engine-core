"""Trusted in-process workload adapters for the Core v1 generic path."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from research_decision_engine.run_spec import (
    CandidateSpec,
    NormalizedObservation,
    _validated_string,
)


class WorkloadAdapterError(RuntimeError):
    """An ordinary callable or normalization failure at the workload boundary."""


class WorkloadAdapter(Protocol):
    """Structural contract for evaluating one exact truth-free candidate."""

    @property
    def adapter_id(self) -> str:
        """Return the user-declared stable adapter identity."""

    @property
    def adapter_version(self) -> str:
        """Return the user-declared compatibility version."""

    def evaluate(self, candidate: CandidateSpec) -> NormalizedObservation:
        """Evaluate exactly one truth-free candidate and normalize its observation."""


@dataclass(frozen=True, slots=True, init=False)
class PythonFunctionAdapter:
    """Run a trusted Python callable once in the current process.

    This adapter offers no timeout, retry, subprocess, sandbox, or security
    isolation. Adapter identity and version are explicit user declarations; they
    are never inferred from a callable representation, memory address, or source
    location.
    """

    adapter_id: str
    adapter_version: str
    _function: Callable[[CandidateSpec], object] = field(repr=False, compare=False)
    _normalizer: Callable[[object], NormalizedObservation] | None = field(repr=False, compare=False)

    def __init__(
        self,
        function: Callable[[CandidateSpec], object],
        *,
        adapter_id: str,
        adapter_version: str,
        normalizer: Callable[[object], NormalizedObservation] | None = None,
    ) -> None:
        if not callable(function):
            raise TypeError("function must be callable.")
        if normalizer is not None and not callable(normalizer):
            raise TypeError("normalizer must be callable when supplied.")
        object.__setattr__(
            self, "adapter_id", _validated_string(adapter_id, field_name="adapter_id")
        )
        object.__setattr__(
            self,
            "adapter_version",
            _validated_string(adapter_version, field_name="adapter_version"),
        )
        object.__setattr__(self, "_function", function)
        object.__setattr__(self, "_normalizer", normalizer)

    def evaluate(self, candidate: CandidateSpec) -> NormalizedObservation:
        """Invoke the callable once, wrapping only ordinary ``Exception`` failures."""

        if type(candidate) is not CandidateSpec:
            raise TypeError("candidate must be an exact CandidateSpec.")
        try:
            raw_result = self._function(candidate)
            observation = raw_result if self._normalizer is None else self._normalizer(raw_result)
        except Exception as exc:
            raise WorkloadAdapterError(
                f"Adapter {self.adapter_id!r} version {self.adapter_version!r} failed."
            ) from exc
        if type(observation) is not NormalizedObservation:
            raise WorkloadAdapterError(
                "Python function adapters must return an exact NormalizedObservation "
                "or use an explicit normalizer that does."
            )
        try:
            return NormalizedObservation(
                objective_value=observation.objective_value,
                cost=observation.cost,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise WorkloadAdapterError(
                "Python function adapter returned an invalid NormalizedObservation."
            ) from exc
