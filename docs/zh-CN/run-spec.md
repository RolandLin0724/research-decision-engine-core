# RunSpec 使用指南

[English](../run-spec.md) | 简体中文

`RunSpec` 是一次有界 Core 运行不可变的规范输入合同。它绑定有序候选集合、
策略身份及完整策略配置、策略使用 seed 时的策略 seed、实验次数预算和可选的
成本预算、目标名称与方向，以及声明的 adapter/workload ID 和版本。选择
`information_gain_table` 时，RunSpec v3 还会绑定有限证据模型。它的 SHA-256
fingerprint 是所有这些输入的可移植身份。

Adapter 身份是调用方声明的兼容性身份。RunSpec 不包含 Python callable 字节、
命令字节、环境、容器、外部数据或科学真值，也不计算这些内容的哈希。

## 公共导入与版本矩阵

请从 package root 使用带版本的记录：

```text
from research_decision_engine import CandidateSpec, FiniteTableEvidenceModel, RunSpec, RunSpecV2, RunSpecV3
```

冻结的版本矩阵如下：

| 记录 | Schema | 支持的策略 | Seed 合同 | 匹配的 bundle 与 replay |
| --- | --- | --- | --- | --- |
| `RunSpec` (v1) | `rde-core-run-spec/v1` | `random` | 必需的有符号 64 位整数 | RunBundle v1 / `RECORDED_OBSERVATION_DECISION_REPLAY_V1` |
| `RunSpecV2` | `rde-core-run-spec/v2` | `random`, `greedy_prior` | `random` 使用整数；`greedy_prior` 使用 `None` | RunBundle v2 / `RECORDED_OBSERVATION_DECISION_REPLAY_V2` |
| `RunSpecV3` | `rde-core-run-spec/v3` | `random`, `greedy_prior`, `information_gain_table` | `random` 使用整数；确定性策略使用 `None` | RunBundle v3 / `RECORDED_OBSERVATION_DECISION_REPLAY_V3` |

需要完整三策略集合的新实验应使用 v3。V1 和 v2 仍受 RDE 1.x 兼容性合同支持。
每个 decoder 只接受其精确 schema：不存在静默升级或降级，policy/schema 或
seed/policy 不匹配时会 fail closed。

## 共享身份字段

每个版本都绑定：

- 由唯一且非空的精确 `CandidateSpec` 记录组成的非空有序序列；
- 一个受支持的策略 ID、其封闭配置对象以及其 seed 合同；
- 大于零且不超过候选数量的实验次数预算；
- 可选的、有限且大于零的成本预算；
- 非空的 adapter ID 和 adapter 版本字符串；
- 非空的目标名称，以及精确为 `maximize` 或 `minimize` 的目标方向；
- 该版本固定的候选顺序 tie-break 字面值。

候选参数和配置值必须是受支持的规范 JSON 值。候选顺序具有语义：它参与
fingerprint，也参与选择行为。对象键的插入顺序不具有语义，因为规范 JSON
会对对象键排序。

## `random`

精确的公共策略身份是 `random`，公共合同将其归类为带 seed 的无放回随机选择。
它的 `policy_config` 精确为空对象，seed 是精确的有符号 64 位整数。V1 使用固定的
RunSpec tie-break 字面值 `candidate-order`；v2 和 v3 使用
`runspec_candidate_order`。

每次选择时，Core 按照精确的 RunSpec 顺序组成剩余候选列表，从声明的 seed
构造确定性的 Python 随机源，并从这个有序剩余列表中选择。Seed 只控制策略选择；
它不会为 adapter 代码、外部命令或 workload 设定 seed，也不会约束这些内容。

因此，要复现一次选择，需要相同的 RunSpec 版本和字节、相同的有序已完成候选
前缀，以及受支持的 RDE 1.x 与 CPython 3.12 合同。这不意味着外部 workload
会复现其 observation。改变候选顺序会改变身份，也可能改变选择。

## `greedy_prior`

精确的公共身份是 `greedy_prior`。它在 v2 和 v3 中可用，是静态、truth-free 的
先验效用策略。其配置精确包含以下键：

```text
{
    "utility_by_candidate_id": {
        "candidate-a": 10,
        "candidate-b": 20,
        "candidate-c": 20
    },
    "tie_break": "runspec_candidate_order"
}
```

`utility_by_candidate_id` 必须精确包含每个 RunSpec 候选 ID 一次，不能缺失或
增加 ID。每个值都是有限的 JSON 整数或浮点数；不存在默认值。完整的规范化 map
是 RunSpec 身份的一部分。调用方的 map 会被复制，因此调用方后续的修改无法改变
RunSpec。

在每一步中，已完成的候选会被排除，选择声明效用最高的合格候选；精确相同时，
按 RunSpec 顺序选择最早的合格候选。声明效用较高者始终胜出；
`objective_direction` 不会将其反转。Observation 永远不会更新效用 map。这些值
是调用方在运行前作出的声明，不是学习得到的 prediction、posterior belief、
observed superiority 或隐藏 benchmark 真值。

## `information_gain_table`

精确的公共身份是 `information_gain_table`，且只在 v3 中可用。它的 seed 必须为
`None`，其配置精确包含一个 `evidence_model` payload 和
`"tie_break": "runspec_candidate_order"`。

公共不可变 `FiniteTableEvidenceModel` 绑定：

- 有序、非空且唯一的 hypothesis ID，以及每个 hypothesis 的一个正整数 prior
  weight；
- 与外层 RunSpec 目标名称相同的 observation metric；
- 至少两个有序且唯一的 outcome ID，以及数量少一个、有限且严格递增的
  threshold；
- 一个正整数 likelihood row total；
- 完整的 candidate × hypothesis × outcome 非负整数 weight 表，其中每一行都列出
  每个 outcome，且总和等于 row total。

模型的 candidate 键必须与 RunSpec 候选 ID 精确相同。对于 threshold
`t[0] ... t[n-2]`，outcome 分区为：

```text
outcome[0]      metric < t[0]
outcome[i]      t[i-1] <= metric < t[i]
outcome[n-1]    metric >= t[n-2]
```

有序 prior weight 是初始的精确信念。候选 `c` 产生分类后的 outcome `o` 后，
每个 hypothesis weight 都乘以 `(c, hypothesis, o)` 对应的声明 likelihood
weight。全零结果会 fail closed；否则所有结果 weight 都除以其最大公约数。
承载信念身份的是这些精确的有序整数，而不是浮点 posterior probability。

选择从当前精确 weight 和固定表计算期望 Shannon information gain。数值合同使用
precision 为 50、舍入模式为 `ROUND_HALF_EVEN` 的局部 `decimal.Decimal`
context，将自然对数 entropy 转换为 bit，并且只把最终 score 量化到 `1e-30`。
最大 score 胜出；精确相同时，选择 RunSpec 中最早的合格候选。

这是用户声明的有限模型 trust boundary。Core 不会学习 likelihood table、推断
hypothesis、对模型进行科学校准、预测目标质量，或证实模型为真。

## 验证与公共类型化错误

普通的记录形状违规使用 `TypeError` 或 `ValueError`，包括无效候选记录、重复候选
ID、无效预算、adapter/objective 身份、目标方向或非规范的 decoded 字节。

策略合同失败使用公共 `PolicyContractError` 子类：

- `UnsupportedRunSpecSchemaError`、`UnsupportedPolicyIdentityError` 和
  `UnsupportedPolicyForSchemaError` 拒绝不受支持的版本/策略组合；
- `PolicyConfigurationError` 及其 seed、utility-map、numeric 和 tie-break 子类
  拒绝开放、不完整或无效的策略配置；
- `RunSpecVersionMismatchError` 拒绝 v2/v3 codec 收到的错误版本字节；v1 codec
  将其错误 schema 情形报告为普通 `ValueError`；
- `InformationGainContractError` 和 `EvidenceModelError` family 拒绝无效的
  hypothesis、prior、outcome、threshold、likelihood row、metric、数值合同、
  belief 或不可能 evidence。

当应用程序需要处理这些错误时，请从 `research_decision_engine` 导入。精确的 leaf
type 列在公共 API manifest 中；内部规范化 helper 不属于公共 surface。

## 规范身份

`to_canonical_bytes()` 输出紧凑、键已排序的严格 UTF-8 JSON，不含 BOM 或回车符，
并且精确包含一个结尾 LF。`fingerprint()` 是这些精确字节的小写 SHA-256 hex
digest。`from_canonical_bytes()` 只接受精确版本和精确规范编码；重复、缺失或未知
字段、非有限数字、不受支持的 schema、替代空白以及其他 alias 都会 fail closed。

输入会被复制并规范化为不可变记录，mapping property 返回分离的值。构造完成后，
修改调用方持有的候选参数、策略 map 或 evidence table，无法改变规范字节或
fingerprint。Candidate、hypothesis 和 outcome array 的顺序仍然承载身份。
配置即使看起来等价，只要仍存在 schema、顺序、数值类型、seed、预算、adapter、
objective 或模型差异，就可能具有不同 fingerprint；规范化有意消除的差异（例如
对象键插入顺序）则不会造成不同 fingerprint。

## 完整的可运行 RunSpec v3 示例

安装 wheel 后，在 disposable directory 中开始，将以下精确程序保存为
`run_spec_example.py`，并运行 `python run_spec_example.py`。它使用最简单且诚实的
v3 策略构造三个候选，输出 schema 身份与 fingerprint，完成规范 round trip，
证明确定性和 seed 变化对身份的影响，并且绝不会构造或执行 workload。

```python
from research_decision_engine import CandidateSpec, RunSpecV3

workload_execution_count = 0

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
    adapter_id="guide.recorded-workload",
    adapter_version="1",
    objective_name="score",
    objective_direction="maximize",
)

canonical = run_spec.to_canonical_bytes()
round_tripped = RunSpecV3.from_canonical_bytes(canonical)

assert run_spec.schema == "rde-core-run-spec/v3"
assert canonical.endswith(b"\n")
assert round_tripped.to_canonical_bytes() == canonical
assert round_tripped.fingerprint() == run_spec.fingerprint()
assert RunSpecV3.from_canonical_bytes(canonical).fingerprint() == run_spec.fingerprint()

changed = RunSpecV3(
    candidates=candidates,
    policy_id="random",
    policy_config={},
    policy_seed=18,
    experiment_count_budget=2,
    cost_budget=1.0,
    adapter_id="guide.recorded-workload",
    adapter_version="1",
    objective_name="score",
    objective_direction="maximize",
)

assert changed.fingerprint() != run_spec.fingerprint()
assert workload_execution_count == 0

print(f"Schema: {run_spec.schema}")
print(f"Fingerprint: {run_spec.fingerprint()}")
print(f"Changed fingerprint: {changed.fingerprint()}")
print("Canonical round trip: PASS")
print(f"Workload executions: {workload_execution_count}")
```

Fingerprint 标识声明的决策输入。它不是签名、加密、保密机制、科学有效性结论或
RDE Assurance 批准。
