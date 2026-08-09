# Recorded-observation replay 使用指南

[English](../replay.md) | 简体中文

Recorded-observation replay（已记录观测回放）针对已经存储在通过验证的
RunBundle 中的观测，重新执行冻结的 Core 决策合同。它会重建策略选择、决策与
理由构造、适用时的精确信念更新、SQLite 持久化、累计成本和终止摘要推导，然后
要求重建后的语义与制品相等。

## Replay 不会执行的内容

Replay 不接收工作负载适配器、可调用对象、命令构建器、命令或插件。执行边界
是精确的：

```text
PythonFunctionAdapter callable: NOT EXECUTED
CommandAdapter command:         NOT EXECUTED
external workload:              NOT EXECUTED
```

原始运行会执行受信任的工作负载并记录规范化观测。Replay 只会在重新计算并检查
每一步的决策后，注入这些观测。

## 版本处理与静态策略工厂

调用与 bundle 版本精确匹配的 replay 函数：

| RunBundle / RunSpec | Replay 函数与合同 | 静态策略 |
| --- | --- | --- |
| v1 / v1 | `replay_run_bundle` / `RECORDED_OBSERVATION_DECISION_REPLAY_V1` | `random` |
| v2 / v2 | `replay_run_bundle_v2` / `RECORDED_OBSERVATION_DECISION_REPLAY_V2` | `random`, `greedy_prior` |
| v3 / v3 | `replay_run_bundle_v3` / `RECORDED_OBSERVATION_DECISION_REPLAY_V3` | `random`, `greedy_prior`, `information_gain_table` |

每条 replay 路径都使用有限的内置静态映射。制品不能指定任意 Python 模块、
导入路径、类、入口点、源文件、可调用对象、评分器、似然函数、插件、注册表或
URL。未知 schema、错误的 RunSpec/RunBundle 配对、不受支持的策略、不可用的
静态 replay 策略或策略/版本不匹配都会以失败关闭；任何版本都不会被静默升级
或降级。

## 输入与目标目录合同

公共 v3 签名具有代表性：

```text
replay_run_bundle_v3(bundle_directory: Path, destination_directory: Path) -> RunBundleV3ReplayResult
```

两个参数都必须是 `pathlib.Path` 实例，而不是字符串或任意 path-like 对象。
`bundle_directory` 指向一个现有且有效的双文件 RunBundle。Replay 会在进行任何
目标目录操作之前调用与版本匹配的严格验证器，并在成功之前再次验证源。无效
制品会成为版本化 replay 失败；replay 不会修复它。每次 verification call 都会拒绝
linked 或 reparse source ancestry，并在该次调用期间绑定 source root/member identities；
replay 不会在两次调用之间持续持有同一个 source guard。

`destination_directory` 指向以下两者之一：现有普通父目录下尚不存在的子项，
或现有的普通且完全为空的目录。
Replay 会拒绝非空目录，并且绝不会与先前状态合并。每个现有 destination ancestor
都会按普通、非链接、非 reparse 目录检查。Replay 会绑定其创建或打开的 destination
root 的 physical identity；它不声称会持续绑定每个 ancestor 的 physical identity。
普通的成功 replay 会发布：

```text
replay.sqlite3
```

每个版本都会在目标目录内构建临时 SQLite 数据库、验证它，再通过不跟随 symlink 的
hard-link operation 无替换地发布 `replay.sqlite3`。它会移除临时名称，并要求已发布
数据库保持为同一个普通、非 reparse、single-link regular file。新数据库使用当前的
公共 schema。只有在重建所有步骤、重新打开临时数据库、检查 schema、历史记录重建
结果与 `PRAGMA integrity_check`，并绑定目标目录和数据库的物理身份后，replay 才会
发布它。V3 还要求最终目标目录清单精确地只包含这一个数据库；不要把这个额外清单
recheck 推断到 v1/v2。

## 重新计算并验证的语义

对于 bundle 中按顺序排列的每个步骤，replay 会：

1. 根据嵌入的 RunSpec 重建与其匹配的静态策略；
2. 排除已完成的 ID 后，按照精确的 RunSpec 候选项顺序进行选择；
3. 重建策略特有的决策与理由并进行精确比较；
4. 根据记录的目标值与成本创建规范化观测；
5. 对于 v3 `information_gain_table`，重新分类观测，重新计算精确的整数信念沿袭与
   指纹，并重新计算量化的信息增益分数；
6. 检查累计成本与版本特有的 step 字段，然后将已完成的 workload record
   持久化到全新的 SQLite 状态中。V3 还会重建并比较完整的 canonical step。

完成所有步骤后，replay 会推导并比较完整的终止摘要，其中包括已选候选项顺序、
总成本、停止原因、决策历史哈希，以及适用时的最终信念指纹。每个版本都会重新
打开 SQLite，并检查 schema、持久化 history 与完整性。V3 还会从重开的 history
重建有序 steps。因此，成功会在匹配的版本化合同下验证候选项顺序、决策、理由、
已记录观测、成本、信念沿袭、终止结果、源 bundle 稳定性和 replay 等价性。

只会发布 `replay.sqlite3`。决策、理由、沿袭和终止摘要都会被重新计算，并与源
bundle 核对；replay 不会发出第二个 bundle，也不会另行发出环境快照。

## 结果与公共错误

每个版本都会返回它的 replay 合同、外层哈希与各分区哈希、replay 历史哈希、
步骤数、有序的已选 ID、SQLite schema 版本，以及 `equivalent=True`。V1 没有
公共执行计数字段。V2 还会报告 `adapter_execution_count == 0` 和
`command_execution_count == 0`。V3 会报告以下全部内容：

```text
adapter_execution_count == 0
callable_execution_count == 0
command_execution_count == 0
```

一般输入、目标目录、持久化、完整性和终止失败会使用 `RunBundleReplayError`、
`RunBundleV2ReplayError` 或 `RunBundleV3ReplayError`。公共的失败关闭诊断还包括
`ReplayPolicyUnavailableError`、`ReplayDecisionMismatchError`、
`ReplayRationaleMismatchError`，以及 v3 的 `ReplayBeliefMismatchError` 和
`ReplayInformationGainScoreMismatchError`。在具体调用路径暴露验证与版本错误的
情况下，这些错误会保留各自独立的公共错误族。常见的 mismatch 错误派生自
`PolicyContractError`，因此仅捕获版本化 replay-error 类并不能穷尽捕获 v2/v3
的所有错误。

## 信任边界

Replay 不是虚拟机或容器复现。它不会还原操作系统、Python 环境、可执行文件、
依赖项、文件、网络服务、硬件设备、外部数据、工作负载代码内部的随机性或任何
其他软件环境。它不会证明原始工作负载所报告的内容真实可信，也不会证明以后
运行该工作负载能产生相同观测。

Replay 只会针对有效 bundle 中提供的已记录观测和冻结的版本化合同，证明
Core 决策过程的确定性。SHA-256 用于完整性检查，而不是签名、保密、加密或独立
证明。Replay 不会创建任何 RDE Assurance 权限、批准或科学有效性认定。

## 完整的空目录 replay 示例

安装 wheel，从一个新的可丢弃目录开始，将以下精确程序保存为
`replay_example.py`，然后运行 `python replay_example.py`。它首先创建并导出一个
有效 bundle，重置显式的工作负载执行计数器，replay 到一个新的空目录，重新
打开 replay SQLite 数据库，比较语义记录，并证明计数器仍为零。英文和中文指南
有意包含完全相同的程序。

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

workload_execution_count = 0


def score(candidate: CandidateSpec) -> NormalizedObservation:
    global workload_execution_count
    workload_execution_count += 1
    value = candidate.parameters["x"]
    if type(value) not in (int, float):
        raise TypeError("x must be numeric")
    x = float(value)
    return NormalizedObservation(
        objective_value=-(x - 2.0) ** 2,
        cost=0.25,
    )


candidates = (
    CandidateSpec("point-1", {"x": 1.0}),
    CandidateSpec("point-2", {"x": 2.0}),
    CandidateSpec("point-3", {"x": 3.0}),
)
run_spec = RunSpecV3(
    candidates=candidates,
    policy_id="random",
    policy_config={},
    policy_seed=17,
    experiment_count_budget=2,
    cost_budget=1.0,
    adapter_id="guide.replay-workload",
    adapter_version="1",
    objective_name="score",
    objective_direction="maximize",
)
adapter = PythonFunctionAdapter(
    score,
    adapter_id=run_spec.adapter_id,
    adapter_version=run_spec.adapter_version,
)

source_database = Path("source-history.sqlite3")
with ExperimentStore(source_database) as store:
    store.init_schema()
    trace = run_workload_trace_v3(
        store,
        run_spec=run_spec,
        adapter=adapter,
    )
    source_history = store.list_workload_experiments(run_spec.fingerprint())

assert workload_execution_count == len(trace.steps) == 2

bundle_directory = Path("valid-run-bundle")
export_run_bundle_v3(bundle_directory, trace=trace)
verified = verify_run_bundle_v3(bundle_directory)
assert verified.valid is True

del adapter
source_database.unlink()
assert not source_database.exists()
workload_execution_count = 0
replay_directory = Path("replay-output")
replay_directory.mkdir()
assert not any(replay_directory.iterdir())

replayed = replay_run_bundle_v3(bundle_directory, replay_directory)

assert workload_execution_count == 0
assert replayed.adapter_execution_count == 0
assert replayed.callable_execution_count == 0
assert replayed.command_execution_count == 0
assert replayed.equivalent is True
assert replayed.bundle_sha256 == verified.bundle_sha256
assert replayed.run_spec_sha256 == verified.run_spec_sha256
assert replayed.steps_sha256 == verified.steps_sha256
assert replayed.terminal_summary_sha256 == verified.terminal_summary_sha256

replay_database = replay_directory / "replay.sqlite3"
assert replay_database.is_file()
with ExperimentStore(replay_database) as replay_store:
    replay_history = replay_store.list_workload_experiments(run_spec.fingerprint())
    replay_schema_version = replay_store.schema_version()


def semantic_records(records: object) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            record.candidate.candidate_id,
            record.policy_id,
            record.observation.objective_value,
            record.observation.cost,
        )
        for record in records
    )


assert semantic_records(replay_history) == semantic_records(source_history)
assert tuple(record.candidate.candidate_id for record in replay_history) == (
    replayed.selected_candidate_ids
)
assert replay_schema_version == replayed.sqlite_schema_version

terminal = verified.bundle.terminal_summary
assert replayed.step_count == terminal["completed_steps"] == len(replay_history)
assert list(replayed.selected_candidate_ids) == terminal["selected_candidate_ids"]
assert sum((record.observation.cost for record in replay_history), 0.0) == terminal["total_cost"]
assert terminal["decision_history_sha256"] == verified.steps_sha256

print(f"Replay contract: {replayed.replay_contract}")
print(f"Selected candidates: {replayed.selected_candidate_ids}")
print(f"SQLite schema: {replay_schema_version}")
print(f"Replay equivalent: {replayed.equivalent}")
print(f"Replay workload executions: {workload_execution_count}")
```

Replay 持久化中存储的时间戳是确定性的 replay 元数据，在此语义示例中不会将其
与原始运行的墙上时钟时间戳进行比较。完成后，请删除整个可丢弃工作目录。
