# RunBundle 使用指南

[English](../run-bundle.md) | 简体中文

RunBundle 是一次已经记录且边界明确的 RDE Core 运行所对应的可移植制品。
它保存验证和重放冻结决策过程所需的输入与证据。它不是任意代码、Python
环境、容器、操作系统镜像、完整机器快照，也不是任意 SQLite 历史的导出。

## 公共 API 与版本矩阵

必须使用与已完成 trace 和 RunSpec 精确匹配的版本：

| RunBundle | 内嵌 RunSpec | Replay contract | Export / verify |
| --- | --- | --- | --- |
| `rde-core-run-bundle/v1` | `rde-core-run-spec/v1` | `RECORDED_OBSERVATION_DECISION_REPLAY_V1` | `export_run_bundle` / `verify_run_bundle` |
| `rde-core-run-bundle/v2` | `rde-core-run-spec/v2` | `RECORDED_OBSERVATION_DECISION_REPLAY_V2` | `export_run_bundle_v2` / `verify_run_bundle_v2` |
| `rde-core-run-bundle/v3` | `rde-core-run-spec/v3` | `RECORDED_OBSERVATION_DECISION_REPLAY_V3` | `export_run_bundle_v3` / `verify_run_bundle_v3` |

各版本的公共签名在结构上相互对应：

```text
export_run_bundle_v3(destination: Path, *, trace: CompletedWorkloadRunTraceV3) -> RunBundleV3VerificationResult
verify_run_bundle_v3(bundle_directory: Path) -> RunBundleV3VerificationResult
```

V1 仅支持 `random`；v2 支持 `random` 和 `greedy_prior`；v3 在此基础上
还支持 `information_gain_table`。Bundle、RunSpec、policy 与 replay 版本之间
采用封闭绑定。不存在静默迁移、升级、降级或重新解释。

## 精确物理布局

当前每个 bundle 版本都是一个普通目录，其中恰好包含两个互不别名、链接
计数恰好为 1 的普通文件，不允许存在任何其他成员：

```text
run-bundle/
├── run-bundle.json
└── run-bundle.json.sha256
```

`run-bundle.json` 是紧凑、按键排序的严格 UTF-8 规范 JSON，不含 BOM 或
回车符，并且末尾恰好有一个 LF。`run-bundle.json.sha256` 恰好由
`SHA256(run-bundle.json)` 的 64 个小写十六进制字符和随后一个 LF 组成，
总计 65 字节。JSON 字段 `root_member_count` 必须恰好为 `2`。

## Bundle 内容

规范 JSON 根对象恰好包含：

```text
artifact_role
producer
replay_contract
root_member_count
run_spec
run_spec_sha256
schema_version
section_sha256
steps
terminal_summary
```

`artifact_role` 为 `portable_recorded_observation_run_bundle`。`run_spec` 是
同版本完整的内嵌规范 RunSpec，`run_spec_sha256` 是其公共 fingerprint。

每个有序 step 恰好包含：

```text
step_index
selected_candidate_id
decision
rationale
observation
belief_lineage
cumulative_cost
```

索引从零开始且必须连续。所选 candidate 必须在 step、decision 和规范化
observation 中保持一致。V2/v3 rationale 会直接重复该 selected ID，因此必须
一致；v1 rationale 不含 selected-ID 字段，而是绑定 available 与 completed 的
选择上下文。Decision 与 rationale 携带封闭的、特定 policy 的选择记录。
Observation 携带 candidate ID、有限 objective 值以及有限非负 cost。系统会
依据有序 observation 和预算检查累计 cost。

对于 v1、v2 的两种 policy，以及 v3 的 `random` 和 `greedy_prior`，
`belief_lineage` 均为空。v3 的每个 `information_gain_table` step 都携带
恰好一个 lineage 条目，用于绑定 step 与 candidate、分类后的 outcome、
GCD 约分前后的有序权重，以及前后两个 belief fingerprint。

`terminal_summary` 包含已完成 step 数、有序所选 ID、总 cost、有限集合中的
停止原因、适用时的最终 belief fingerprint，以及 decision history hash。
`section_sha256` 恰好包含 RunSpec、steps 和 terminal summary 的 hash。
Sidecar 则单独绑定完整的外层 JSON 文档。

## 导出

导出以匹配版本的 `run_workload_trace`、`run_workload_trace_v2` 或
`run_workload_trace_v3` 调用所返回的精确不可变已完成 trace 为起点。Trace
捕获要求该 RunSpec 的历史为空，并在有界运行进行期间记录每个 decision、
rationale、observation、lineage 条目、累计 cost 和最终停止原因。导出会
依据内嵌 RunSpec 与静态 policy 验证 trace。它不会调用 adapter 或 workload，
也不会事后从任意数据库行重新构造 trace。

目标参数必须是 `pathlib.Path` 实例，而不是字符串或任意 path-like 对象；
其父目录和祖先路径必须已经是普通、非链接、非 reparse 的目录，且目标本身
不得以任何形式存在。如果目标已经存在，导出会抛出对应版本的
`RunBundle...ValidationError`，并且不会覆盖或合并目标。

导出会在同一卷创建临时同级目录，以独占方式写入两个新成员，验证临时
bundle，以不替换方式发布目录，随后重新打开并验证已发布制品。在 Windows
上，发布与验证会绑定目录 handle 和物理身份。在 Linux 上，发布使用该
平台的原子、独占、不替换 rename。规范内容可在受支持的 Windows 与 Linux
合同之间移植，而原子命名空间机制取决于平台；这并不是针对所有同账户
主动竞态命名空间攻击者的更广泛保证，也不代表通用 POSIX/macOS 支持或
崩溃持久性保证。

请使用已安装的发行包。解析 producer 元数据是导出的一部分；v1/v2 要求
存在已安装的包元数据，而 v3 仅在该元数据不可用时将 package version
记录为 `0+unknown`。

## 验证

验证是只读操作，并且只有全部检查通过后才返回不可变结果。它会检查：

- 根路径是预期的普通目录，并且恰好包含两个指定的普通文件；
- 在两次读取的整个过程中，根路径祖先以及根路径/成员的物理身份保持稳定；
- 精确的 65 字节 sidecar 与完整 JSON 字节匹配；
- JSON 是严格规范 UTF-8，具有精确封闭的 schema、role、replay contract
  和 producer 字段，且不存在未知、缺失、重复、非有限、隐藏真值或被禁止
  的绝对路径值；
- 内嵌 RunSpec 使用匹配版本，能够规范解码，并与 `run_spec_sha256` 匹配；
- RunSpec、有序 steps 与 terminal summary 分别匹配三个 section hash；
- step 索引、成员/candidate 身份、policy decision、rationale、observation、
  cost、belief lineage、预算、停止原因和 terminal summary，在内嵌 RunSpec
  与冻结静态 policy 下内部一致；
- 验证期间两个成员和源根路径均未发生变化。

成功结果公开 `valid=True`、外层 bundle SHA、三个 section SHA、step 数、
有序所选 ID，以及解码后的不可变 bundle。验证不会访问 SQLite、网络、
adapter、callable、command builder 或外部 workload。

这些 hash 为提交给验证器的文件提供完整性检查与篡改检测。它们不是数字
签名、签名者身份、第三方 attestation、加密或保密机制。任何能够同时替换
两个文件的人都可以构造另一个自洽制品。

## 篡改检测与公共错误

构造和导出合同失败使用 `RunBundleValidationError`、
`RunBundleV2ValidationError` 或 `RunBundleV3ValidationError`。在直接验证期间，
v1/v2 会把已解码 canonical/schema 失败包装为对应的
`RunBundle...VerificationError`，而 v3 对这些失败保留
`RunBundleV3ValidationError`。所有版本的物理清单、稳定读取及 sidecar 失败都
使用对应的 `RunBundle...VerificationError`。封闭版本或语义不匹配则
可能改为公开 `RunBundleVersionMismatchError`、`ReplayDecisionMismatchError`、
`ReplayRationaleMismatchError` 或 v3 belief/score mismatch 错误。Replay
使用单独的版本化 replay-error 家族。这些名称都是 package-root 公共导入；
版本化基类分别为 `RunBundleError`、`RunBundleV2Error` 和
`RunBundleV3Error`。因此，只捕获某个版本的 verification 基类并不能穷尽
所有语义或版本失败。

篡改任一成员、增加或删除成员、更改规范 JSON 或 section 内容，或者在验证
期间替换文件，都会以 fail-closed 方式失败。下面的示例会复制有效 bundle，
并更改副本中一个非敏感的 sidecar 字节，绝不会更改原始有效 bundle。

## Producer 元数据与稳定 section

`producer` 恰好包含 `package_name`、`package_version`、
`python_implementation` 和 `python_version`。Python 版本值包含 patch version。
验证会检查封闭的非空字符串结构，但不要求 producer 值与当前解释器匹配。
Producer 元数据是 `run-bundle.json` 的一部分，因此 producer payload 不同
的两个合法导出可能具有不同的外层 bundle SHA-256。不要预期 Python patch
或 producer version 变化后外层 SHA 仍然相等。

单独存储的 `run_spec`、`steps` 和 `terminal_summary` section hash 独立于
producer 元数据，绑定各自携带身份的规范 payload。应比较与身份声明相对应
的 section；不要删除或重写 producer 元数据来制造外层 SHA 相等。

## 完整导出、验证与一次性篡改示例

安装 wheel，在新的临时目录中开始，将以下精确程序保存为
`run_bundle_example.py`，然后运行 `python run_bundle_example.py`。英文与
中文指南有意包含完全相同的程序。

```python
from pathlib import Path
from shutil import copytree

from research_decision_engine import (
    CandidateSpec,
    NormalizedObservation,
    PythonFunctionAdapter,
    RunBundleV3VerificationError,
    RunSpecV3,
    export_run_bundle_v3,
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
    adapter_id="guide.bundle-workload",
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

assert workload_execution_count == len(trace.steps) == 2
calls_before_export = workload_execution_count

bundle_directory = Path("valid-run-bundle")
exported = export_run_bundle_v3(bundle_directory, trace=trace)
verified = verify_run_bundle_v3(bundle_directory)

assert workload_execution_count == calls_before_export
assert exported.valid is True
assert verified.valid is True
assert verified.bundle_sha256 == exported.bundle_sha256
assert sorted(path.name for path in bundle_directory.iterdir()) == [
    "run-bundle.json",
    "run-bundle.json.sha256",
]

tampered_directory = Path("tampered-run-bundle")
copytree(bundle_directory, tampered_directory)
tampered_sidecar = tampered_directory / "run-bundle.json.sha256"
sidecar_bytes = bytearray(tampered_sidecar.read_bytes())
sidecar_bytes[0] = ord("0") if sidecar_bytes[0] != ord("0") else ord("1")
tampered_sidecar.write_bytes(sidecar_bytes)

tampered_rejected = False
try:
    verify_run_bundle_v3(tampered_directory)
except RunBundleV3VerificationError:
    tampered_rejected = True

assert tampered_rejected is True
original_after_tamper = verify_run_bundle_v3(bundle_directory)
assert original_after_tamper.bundle_sha256 == verified.bundle_sha256

print(f"Bundle schema: {verified.bundle.schema_version}")
print(f"Bundle SHA-256: {verified.bundle_sha256}")
print(f"Selected candidates: {verified.selected_candidate_ids}")
print("Valid bundle verification: PASS")
print("Tampered copy rejected: PASS")
print("Original bundle remains valid: PASS")
```

完成后，请删除整个临时工作目录。有效 bundle 与篡改 bundle 有意使用不同
名称，因此篡改演示绝不会编辑源制品。
