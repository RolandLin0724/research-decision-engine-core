from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any, cast

import pytest

from research_decision_engine import (
    CandidateSpec,
    NormalizedObservation,
    PythonFunctionAdapter,
    WorkloadAdapter,
    WorkloadAdapterError,
)


def test_python_function_adapter_has_stable_declared_identity_and_protocol_shape() -> None:
    adapter = PythonFunctionAdapter(
        lambda candidate: NormalizedObservation(cast(float, candidate.parameters["x"])),
        adapter_id="trusted-score",
        adapter_version="2026-08-03",
    )
    structural_adapter: WorkloadAdapter = adapter

    assert structural_adapter.adapter_id == "trusted-score"
    assert structural_adapter.adapter_version == "2026-08-03"
    assert "lambda" not in repr(adapter)
    with pytest.raises(FrozenInstanceError):
        cast(Any, adapter).adapter_id = "changed"


def test_python_function_adapter_calls_once_with_only_exact_truth_free_candidate() -> None:
    calls: list[CandidateSpec] = []

    def workload(candidate: CandidateSpec) -> NormalizedObservation:
        calls.append(candidate)
        assert type(candidate) is CandidateSpec
        assert set(candidate.parameters) == {"x"}
        assert not hasattr(candidate, "true_value")
        return NormalizedObservation(objective_value=3.5, cost=0.25)

    candidate = CandidateSpec("candidate-a", {"x": 3.5})
    adapter = PythonFunctionAdapter(
        workload,
        adapter_id="trusted-score",
        adapter_version="1",
    )

    assert adapter.evaluate(candidate) == NormalizedObservation(3.5, 0.25)
    assert calls == [candidate]


def test_python_function_adapter_uses_one_explicit_normalizer_without_coercion() -> None:
    function_calls = 0
    normalizer_calls = 0

    def workload(candidate: CandidateSpec) -> object:
        nonlocal function_calls
        function_calls += 1
        return {"score": candidate.parameters["x"]}

    def normalize(raw: object) -> NormalizedObservation:
        nonlocal normalizer_calls
        normalizer_calls += 1
        mapping = cast(dict[str, object], raw)
        return NormalizedObservation(cast(float, mapping["score"]))

    adapter = PythonFunctionAdapter(
        workload,
        normalizer=normalize,
        adapter_id="mapping-score",
        adapter_version="1",
    )

    assert adapter.evaluate(CandidateSpec("candidate-a", {"x": 2.0})) == (
        NormalizedObservation(2.0)
    )
    assert function_calls == 1
    assert normalizer_calls == 1


@pytest.mark.parametrize("result", [1.0, {"objective_value": 1.0}, (1.0, 0.0)])
def test_python_function_adapter_rejects_implicit_result_coercion(result: object) -> None:
    adapter = PythonFunctionAdapter(
        lambda candidate: result,
        adapter_id="invalid-result",
        adapter_version="1",
    )

    with pytest.raises(WorkloadAdapterError, match="exact NormalizedObservation"):
        adapter.evaluate(CandidateSpec("candidate-a", {}))


def test_python_function_adapter_revalidates_an_exact_observation_instance() -> None:
    tampered = NormalizedObservation(1.0, 0.25)
    object.__setattr__(tampered, "objective_value", float("nan"))
    object.__setattr__(tampered, "cost", -1.0)
    adapter = PythonFunctionAdapter(
        lambda candidate: tampered,
        adapter_id="tampered-observation",
        adapter_version="1",
    )

    with pytest.raises(WorkloadAdapterError, match="invalid NormalizedObservation") as raised:
        adapter.evaluate(CandidateSpec("candidate-a", {}))
    assert isinstance(raised.value.__cause__, ValueError)


def test_python_function_adapter_wraps_an_uninitialized_exact_observation() -> None:
    forged = object.__new__(NormalizedObservation)
    adapter = PythonFunctionAdapter(
        lambda candidate: forged,
        adapter_id="missing-observation-fields",
        adapter_version="1",
    )

    with pytest.raises(WorkloadAdapterError, match="invalid NormalizedObservation") as raised:
        adapter.evaluate(CandidateSpec("candidate-a", {}))
    assert isinstance(raised.value.__cause__, AttributeError)


def test_python_function_adapter_wraps_ordinary_failure_and_preserves_cause() -> None:
    failure = ValueError("user failure")
    calls = 0

    def workload(candidate: CandidateSpec) -> NormalizedObservation:
        nonlocal calls
        calls += 1
        raise failure

    adapter = PythonFunctionAdapter(
        workload,
        adapter_id="failing-score",
        adapter_version="1",
    )

    with pytest.raises(WorkloadAdapterError) as raised:
        adapter.evaluate(CandidateSpec("candidate-a", {}))
    assert raised.value.__cause__ is failure
    assert calls == 1


@pytest.mark.parametrize("failure_type", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_python_function_adapter_does_not_swallow_base_exceptions(
    failure_type: type[BaseException],
) -> None:
    def workload(candidate: CandidateSpec) -> NormalizedObservation:
        raise failure_type()

    adapter = PythonFunctionAdapter(
        workload,
        adapter_id="base-exception",
        adapter_version="1",
    )

    with pytest.raises(failure_type):
        adapter.evaluate(CandidateSpec("candidate-a", {}))


def test_python_function_adapter_never_retries_and_is_deterministic_when_callable_is() -> None:
    calls = 0

    def workload(candidate: CandidateSpec) -> NormalizedObservation:
        nonlocal calls
        calls += 1
        return NormalizedObservation(cast(float, candidate.parameters["x"]) * 2.0)

    adapter = PythonFunctionAdapter(
        workload,
        adapter_id="deterministic-score",
        adapter_version="1",
    )
    candidate = CandidateSpec("candidate-a", {"x": 1.5})

    assert adapter.evaluate(candidate) == NormalizedObservation(3.0)
    assert adapter.evaluate(candidate) == NormalizedObservation(3.0)
    assert calls == 2


def test_python_function_adapter_rejects_candidate_subclass_before_user_code() -> None:
    class CandidateSubclass(CandidateSpec):
        pass

    calls = 0

    def workload(candidate: CandidateSpec) -> NormalizedObservation:
        nonlocal calls
        calls += 1
        return NormalizedObservation(1.0)

    adapter = PythonFunctionAdapter(
        workload,
        adapter_id="exact-boundary",
        adapter_version="1",
    )
    lookalike = CandidateSubclass("candidate-a", {})

    with pytest.raises(TypeError, match="exact CandidateSpec"):
        adapter.evaluate(lookalike)
    assert calls == 0
