# PythonFunctionAdapter 使用指南

[English](../python-function-adapter.md) | 简体中文

`PythonFunctionAdapter` 将现有 Python callable 接入有界的 RDE Core 实验循环。
当 workload 是可在当前进程中本地运行的可信 Python 代码、实验候选集有限，并且
每个 callable 结果都能规范化为一个 RDE observation 时，应使用该 adapter。

## 公共 imports

本指南使用的冻结公共 imports 为：

```text
from research_decision_engine import CandidateSpec, NormalizedObservation, PythonFunctionAdapter, WorkloadAdapterError
from research_decision_engine.storage import ExperimentStore
```

可运行示例还从 package 根目录 import 公共的 v3 run、bundle、verification 和 replay
函数。

## 精确 callable 合同

公共构造函数和 evaluate 签名为：

```text
PythonFunctionAdapter(
    function: Callable[[CandidateSpec], object],
    *,
    adapter_id: str,
    adapter_version: str,
    normalizer: Callable[[object], NormalizedObservation] | None = None,
)

adapter.evaluate(candidate: CandidateSpec) -> NormalizedObservation
```

`function` 只接收一个精确类型的 `CandidateSpec`。其 `candidate_id` 是声明的非空
候选身份；其 `parameters` property 是 detached mapping，包含构造 candidate 时提供并
规范化后的 canonical JSON-compatible 参数。候选专属值通过这些参数进入 callable；
adapter 不会添加 hidden truth、execution context 或其他参数。

每次 evaluation 调用 callable 一次。未提供 `normalizer` 时，callable 必须返回精确
类型的 `NormalizedObservation`。提供 `normalizer` 时，callable 可以返回其他对象，
adapter 会调用显式 normalizer 一次；normalizer 必须返回精确类型的
`NormalizedObservation`。number、mapping 或 tuple 不会被隐式转换。

`NormalizedObservation` 恰好支持以下 observation 值：

- `objective_value`：精确的 built-in `int` 或 `float`，不包括 `bool`、可强制转换
  对象或非 built-in numeric objects；integer input 必须在 signed 64-bit 范围内，
  该值必须有限，并会规范化为 `float`；
- `cost`：使用相同的精确 numeric input types 和 integer bound，必须有限且非负，
  会规范化为 `float`；省略时默认值为 `0.0`。

adapter 会重新验证两个字段，并返回一个新的精确 observation。observation 没有
metadata 字段，也没有任意 metrics mapping。`objective_name` 和
`objective_direction` 属于 `RunSpec`；它们不会为 adapter 结果增加字段。如果
workload 产生更丰富的对象，显式 normalizer 可以选择一个 objective 和一个 cost，
但不能附加额外 observation metadata。

adapter ID 和 version 是 caller 的显式声明，并且必须与 `RunSpec` 中的对应值匹配。
它们不会从函数名、source path、representation 或内存地址推断。

## 错误与执行行为

- 不可调用的 function 或 normalizer、无效 adapter identity，或非精确类型的
  `CandidateSpec` 会在适用情况下于 workload 执行前以 `TypeError` 或 `ValueError`
  失败。
- callable 或 normalizer 抛出的普通 `Exception` 会转换为 `WorkloadAdapterError`，
  原始异常保留在 `__cause__` 中。
- 非精确类型的 `NormalizedObservation` 结果，或字段重新验证失败的结果，会引发
  `WorkloadAdapterError`。
- `KeyboardInterrupt`、`SystemExit`、`GeneratorExit` 和 `Exception` hierarchy
  之外的其他 `BaseException` subclasses 不会被包装。
- 每次 `evaluate` 只尝试一次。该 adapter 不提供自动 retry、timeout、subprocess
  boundary 或 recovery policy。

## 确定性与信任边界

通过 candidate parameters 传入全部 workload 输入；任何随机 workload 都使用显式
seed；不要依赖当前时间或隐藏的全局状态。不要把临时 absolute path、内存地址或不
稳定的对象 representation 写入返回值。保持 callable 与其声明的 adapter version
一致，使 version 变化反映有意义的 workload 兼容性变化。

`PythonFunctionAdapter` 在当前 Python 进程中执行用户提供的 Python。它不是恶意
代码沙箱。callable 拥有该进程可用的全部权限和能力，并且可以修改进程或文件系统
状态。只能使用可信代码。

RunBundle replay 是 recorded-observation decision replay。它不会接收 callable，也
不会再次调用 adapter 或 workload。

## 完整可运行示例

安装 wheel 后，从一个新的空工作目录开始，将以下精确程序保存为
`python_adapter_example.py`，然后运行 `python python_adapter_example.py`。英文和
中文指南有意使用完全相同的程序。

```python
from pathlib import Path

from research_decision_engine import (
    CandidateSpec,
    NormalizedObservation,
    PythonFunctionAdapter,
    RunSpecV3,
    export_run_bundle_v3,
    replay_run_bundle_v3,
    run_workload_trace_v3,
    verify_run_bundle_v3,
)
from research_decision_engine.storage import ExperimentStore

call_count = 0


def score(candidate: CandidateSpec) -> NormalizedObservation:
    global call_count
    call_count += 1
    value = candidate.parameters["x"]
    if type(value) not in (int, float):
        raise TypeError("x must be numeric")
    x = float(value)
    return NormalizedObservation(
        objective_value=-(x - 2.0) ** 2,
        cost=0.25,
    )


candidates = [
    CandidateSpec("point-1", {"x": 1.0}),
    CandidateSpec("point-2", {"x": 2.0}),
    CandidateSpec("point-3", {"x": 3.0}),
]

run_spec = RunSpecV3(
    candidates=candidates,
    policy_id="random",
    policy_config={},
    policy_seed=17,
    experiment_count_budget=2,
    cost_budget=1.0,
    adapter_id="guide.python-function",
    adapter_version="1",
    objective_name="score",
    objective_direction="maximize",
)
adapter = PythonFunctionAdapter(
    score,
    adapter_id=run_spec.adapter_id,
    adapter_version=run_spec.adapter_version,
)

database = Path("history.sqlite3")
with ExperimentStore(database) as store:
    store.init_schema()
    trace = run_workload_trace_v3(
        store,
        run_spec=run_spec,
        adapter=adapter,
    )
    history = store.list_workload_experiments(run_spec.fingerprint())

assert database.is_file()
assert len(history) == len(trace.steps) == call_count == 2
for record in history:
    print(
        f"Observation {record.candidate.candidate_id}: "
        f"objective_value={record.observation.objective_value}, "
        f"cost={record.observation.cost}"
    )

bundle_directory = Path("run-bundle")
exported = export_run_bundle_v3(bundle_directory, trace=trace)
verified = verify_run_bundle_v3(bundle_directory)
assert exported.valid is True
assert verified.valid is True
assert verified.bundle_sha256 == exported.bundle_sha256

calls_before_replay = call_count
replay_directory = Path("replay")
replay_directory.mkdir()
assert not any(replay_directory.iterdir())
replayed = replay_run_bundle_v3(bundle_directory, replay_directory)

assert call_count == calls_before_replay
assert replayed.adapter_execution_count == 0
assert replayed.callable_execution_count == 0
assert replayed.command_execution_count == 0
assert replayed.equivalent is True
assert (replay_directory / "replay.sqlite3").is_file()

print(f"SQLite created: {database.is_file()}")
print(f"RunBundle verified: {verified.valid}")
print(f"Replay equivalent: {replayed.equivalent}")
print(f"Replay callable executions: {replayed.callable_execution_count}")
```

初始 run 会执行三个候选中的两个，并打印两个持久化 observations。export 会创建
由两个文件组成的 RunBundle，verification 必须报告 `True`；replay 会在之前为空的
`replay` 目录中写入新的 SQLite 状态。replay 的最终 callable execution count 必须
为 `0`。
