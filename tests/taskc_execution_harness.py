from __future__ import annotations

from dataclasses import dataclass

from research_decision_engine.benchmarks.broader_execution import (
    ActualExecutorAttestation,
    execute_deterministic_map,
)


@dataclass(frozen=True, slots=True)
class TaskCResult:
    job_id: int
    value: int


def result_for(job: int) -> TaskCResult:
    return TaskCResult(job_id=job, value=100 + 7 * job)


def execute_fixture(
    jobs: tuple[int, ...] = (1, 3, 5),
    *,
    worker_count: int = 1,
    result_order: str = "input_order",
    execution_purpose: str = "diagnostic",
) -> tuple[tuple[TaskCResult, ...], ActualExecutorAttestation]:
    return execute_deterministic_map(
        result_for,
        jobs,
        worker_count=worker_count,
        executor_kind="serial" if worker_count == 1 else "thread_pool",
        result_order=result_order,  # type: ignore[arg-type]
        execution_purpose=execution_purpose,  # type: ignore[arg-type]
    )
