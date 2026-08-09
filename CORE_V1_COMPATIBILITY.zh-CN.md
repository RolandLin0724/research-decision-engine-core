# Research Decision Engine Core（RDE Core）v1 兼容性合同

[English](CORE_V1_COMPATIBILITY.md)

本文档定义合同 `RDE_CORE_PUBLIC_API_V1` 的人类可读兼容性政策。机器可读的
权威来源是 `research_decision_engine/core-public-api-v1.json`。在受支持的
Windows 和 Linux 平台上，已声明的公开接口在 RDE 1.x 全程对 CPython
`>=3.12,<3.13` 保持 `BACKWARD_COMPATIBLE`。不承诺支持更早的 Python
版本或 Python 3.13。

Research Decision Engine Core 是产品展示品牌，RDE Core 是简称。Python 分发包
仍为 `research-decision-engine`，导入包仍为 `research_decision_engine`，CLI
仍为 `rde`。

这是一份兼容性合同，而非发布就绪声明。本地验证和已配置的工作流不能证明
远程 CI 已通过，二者也都不会创建 RDE Assurance 权限。

当前私有候选为 `1.0.0rc5`。项目仍为实验性预发布状态，真实生产使用和广泛的
用户或 workload 验证尚未确立。净化的产品仓库仍为私有；尚未执行公开仓库发布，
也未创建 GitHub Prerelease、tag、GitHub Release 或 PyPI 发布。

## 公开 Python 导入

冻结范围恰好涵盖 110 个包根导出。下列每个名称均以
`from research_decision_engine import <name>` 导入，并具有稳定性
`STABLE_THROUGH_RDE_1_X`：

```text
CandidateSpec
CommandAdapter
CommandAdapterError
CommandBuildError
CommandExitError
CommandInvocation
CommandOutputError
CommandTimeoutError
CompletedWorkloadExperiment
CompletedWorkloadRunTrace
CompletedWorkloadRunTraceV2
CompletedWorkloadRunTraceV3
DeterministicPolicySeedError
EmptyOrDuplicateHypothesisSetError
EvidenceModelDecodeError
EvidenceModelError
ExtraCandidateUtilityError
FiniteTableEvidenceModel
INFORMATION_GAIN_NUMERIC_CONTRACT
ImpossibleEvidenceError
InformationGainBeliefLineage
InformationGainContractError
InformationGainNumericContract
InvalidCandidateUtilityError
InvalidInformationGainBeliefError
InvalidLikelihoodWeightError
InvalidOutcomeSetError
InvalidPolicyTieBreakError
InvalidThresholdCountError
InvalidThresholdError
InvalidThresholdOrderError
LikelihoodCandidateKeyMismatchError
LikelihoodHypothesisKeyMismatchError
LikelihoodOutcomeKeyMismatchError
LikelihoodRowTotalMismatchError
MissingCandidateUtilityError
MissingObservationMetricError
NonfiniteObservationMetricError
NonfiniteUtilityError
NonpositivePriorWeightError
NormalizedObservation
ObservationMetricError
PolicyConfigurationError
PolicyContractError
PriorGreedyPolicy
PriorKeyMismatchError
PythonFunctionAdapter
ReplayBeliefMismatchError
ReplayDecisionMismatchError
ReplayInformationGainScoreMismatchError
ReplayPolicyUnavailableError
ReplayRationaleMismatchError
RunBundle
RunBundleError
RunBundleReplayError
RunBundleReplayResult
RunBundleStep
RunBundleStepV2
RunBundleStepV3
RunBundleV2
RunBundleV2Error
RunBundleV2ReplayError
RunBundleV2ReplayResult
RunBundleV2ValidationError
RunBundleV2VerificationError
RunBundleV2VerificationResult
RunBundleV3
RunBundleV3Error
RunBundleV3ReplayError
RunBundleV3ReplayResult
RunBundleV3ValidationError
RunBundleV3VerificationError
RunBundleV3VerificationResult
RunBundleValidationError
RunBundleVerificationError
RunBundleVerificationResult
RunBundleVersionMismatchError
RunSpec
RunSpecV2
RunSpecV3
RunSpecVersionMismatchError
TableInformationGainPolicy
UnsupportedInformationGainNumericContractError
UnsupportedPolicyForSchemaError
UnsupportedPolicyIdentityError
UnsupportedRunSpecSchemaError
WorkloadAdapter
WorkloadAdapterError
__version__
export_run_bundle
export_run_bundle_v2
export_run_bundle_v3
policy_contract_for_schema
policy_identity_contract
replay_run_bundle
replay_run_bundle_v2
replay_run_bundle_v3
resume_workload_trace
resume_workload_trace_v2
resume_workload_trace_v3
run_workload_experiment
run_workload_experiment_v2
run_workload_experiment_v3
run_workload_trace
run_workload_trace_v2
run_workload_trace_v3
supported_policy_identities
verify_run_bundle
verify_run_bundle_v2
verify_run_bundle_v3
```

SQLite 是包根 runner 函数所使用的一个有意设置的公开边界。以下两个额外的
子模块导入在 RDE 1.x 全程保持稳定，使清单总数达到恰好 112 个公开符号条目：

```python
from research_decision_engine.storage import ExperimentStore, SCHEMA_VERSION
```

这 112 个清单所列符号且仅有这些符号构成冻结的公开 API。在本 RC 合同下，
其文档化签名、公开字段和类型化错误族均承载兼容性。

`research_decision_engine.__version__` 在 RDE 1.x 全程是稳定的公开符号：其导入
路径保持可用，类型保持为 `str`，并且其值始终等于当前已安装分发包的版本。因此，
该值会随不同候选或发布而变化。将其从 `0.1.0` 同步为 `1.0.0rc1`，再将私有
候选推进至 `1.0.0rc2`，并在 RC2 committed-blob 可移植性检查失败后推进至
`1.0.0rc3`，再在修正 Private Vulnerability Reporting 发布顺序后推进至
`1.0.0rc4`，随后在从面向发布的字节中移除私有源提交引用后推进至
`1.0.0rc5`，是记录分发包身份，并非移除 API，也不是不兼容的语义重解释。
其他任何公开常量均不因此获得允许改变其值的例外。

对 `ExperimentStore` 而言，刻意设定的公开方法边界为 `init_schema()`、
`schema_version()`、`add_workload_experiment()` 和
`list_workload_experiments()`，以及构造和上下文管理器用法。其他存储方法和
所有迁移辅助函数均不在此冻结范围内。

该清单是穷尽式的。可导入、名称不以下划线开头或被实现模块使用，都不会独立
使某个符号成为公开符号。`rde` 控制台命令仍是文档化的 CLI 入口点，映射到
`research_decision_engine.cli:main`；其受支持行为与 Python 导入列表分开
测试。

## 稳定性分类

每个可导入符号均被归入以下类别之一：

- `CORE_V1_PUBLIC`：仅指公开 API 清单枚举的导入。其文档化签名或不可变记录
  字段、类型化错误族和语义在 RDE 1.x 全程保持兼容。
- `CORE_V1_INTERNAL`：迁移辅助函数、私有编解码器、runner 和 CLI 辅助函数、
  可变工厂、文件系统辅助函数以及测试支持等实现细节。即使直接导入碰巧有效，
  它们也可在不弃用的情况下更改。
- `CORE_EXPERIMENTAL`：`closed_loop` 以及 broader-replication/Assurance
  轨道之外的其他选择加入式、非清单 Core 研究或基准成员。这些接口可在不走
  Core 公开弃用流程的情况下更改或移除。
- `ASSURANCE_EXPERIMENTAL`：
  `research_decision_engine.benchmarks.broader_*`、P4、protocol、
  review-controller 及相关 Assurance 接口。它们位于 RDE Core 之外，仍受
  单独治理，且绝不会因 Core 测试或 CI 结果而晋升。
- `DEPRECATED_CANDIDATE`：已明确进入弃用路径的公开导入。初始 v1 冻结中没有
  此类条目。

### 兼容性和弃用政策

在 RDE 1.x 内，稳定导入路径保持可导入；不可变公开记录字段不会被移除、
重命名、重排或重新定型；必需参数不会被重新解释；类型化错误族保持可用；
truth-free 边界和 replay 不执行行为保持不变；冻结的制品版本不会被重新解释。

稳定 API 只有在有明确文档条目并于运行时发出 `DeprecationWarning` 时才能
弃用。被弃用的 API 在 RDE 1.x 余下期间保持可用且兼容。移除、不兼容的签名
或字段变更，或语义重新解释，均需等到下一个主版本。只有在不削弱现有封闭
schema 或不改变规范字节的情况下，才可在 1.x 中引入增量 API。即使建议使用
更新的 schema，制品 schema v1、v2 和 v3 也会在整个 1.x 系列中保持受支持。

## RunSpec、RunBundle、policy 和 replay 兼容性

受支持的矩阵是封闭且版本匹配的：

| 版本 | RunSpec schema | 受支持 policy | RunBundle schema | Replay 合同 |
| --- | --- | --- | --- | --- |
| v1 | `rde-core-run-spec/v1` | `random` | `rde-core-run-bundle/v1` | `RECORDED_OBSERVATION_DECISION_REPLAY_V1` |
| v2 | `rde-core-run-spec/v2` | `random`, `greedy_prior` | `rde-core-run-bundle/v2` | `RECORDED_OBSERVATION_DECISION_REPLAY_V2` |
| v3 | `rde-core-run-spec/v3` | `random`, `greedy_prior`, `information_gain_table` | `rde-core-run-bundle/v3` | `RECORDED_OBSERVATION_DECISION_REPLAY_V3` |

对于需要完整三 policy 集合的新运行，建议使用 V3。V1 和 v2 在整个 RDE 1.x
中仍可读取且受支持。

版本分离是严格的。规范字节、指纹、sidecar、决策与理由记录、belief lineage
和终止摘要保持其版本化含义。候选项顺序和规范 RunSpec/RunBundle 身份承载
兼容性；候选项重排或规范身份变更不属于兼容性重写。Core 从不静默升级或
降级 RunSpec 或 RunBundle，验证也绝不会重写它们。未知 schema/policy 组合
会以 fail-closed 方式失败。未知 schema、重复键以及未知或缺失字段同样会以
fail-closed 方式失败。

Replay 对 v1、v2 和 v3 进行版本匹配，并使用相应 RunBundle 中记录的观测。
它只使用有限的内置 policy 映射；不支持任意导入路径或插件加载。Replay 不会
动态导入 policy、调用 adapter、调用 Python callable 或执行命令。因此，
成功 replay 的工作负载执行计数为零。

## SQLite schema v6

`research_decision_engine.storage.SCHEMA_VERSION` 为 `6`。新的空数据库会
初始化为 v6。v1 至 v5 是受支持的旧 schema，前向图为：

```text
0 -> 1 -> 2 -> 3 -> 4 -> 5 -> 6
```

| SQLite 规则 | 冻结合同 |
| --- | --- |
| 最新 schema | `V6` |
| 新数据库终止 schema | `V6` |
| 受支持的旧 schema | `V1`, `V2`, `V3`, `V4`, `V5` |
| 迁移模型 | `PER_VERSION_STEP_ATOMIC_AND_RESUMABLE` |
| V5 角色 | `SUPPORTED_LEGACY_SCHEMA_AND_RETRY_CHECKPOINT`; `NOT_LATEST_SCHEMA` |
| 降级 | `NOT_SUPPORTED` |
| 未知未来 schema | `REJECT_BEFORE_MUTATION` |

版本 0 是一种初始化状态，仅空数据库或精确受支持的无版本旧形态可接受它。
V5 是受支持的旧 schema 和有效的失败/重试检查点；它不是最新 schema。

受支持的旧 schema 迁移每次恰好前进一个版本。
每条边由一个 `BEGIN IMMEDIATE` 事务负责，该事务包括 schema/数据变更、
后置条件验证、`PRAGMA user_version`、最终验证和提交。该模型为
`PER_VERSION_STEP_ATOMIC_AND_RESUMABLE`：当前边失败会回滚到该边精确的
源 schema 和数据，而此前已成功提交的边保持已提交。重新打开并重试时，会从
最后提交的版本继续。打开 v6 是幂等的空操作。

现有 `5 -> 6` 边的语义角色为 `EXISTING_RUNSPEC_PERSISTENCE_MIGRATION`，
且只有一个 schema 变更：创建精确的 `workload_experiments` 表。该表按外部
提供的 RunSpec SHA-256 指纹键控并持久化已完成工作负载记录；它不持久化完整
RunSpec 文档。每个现有 v5 表和行都予以保留；该边不重新解释或重写 v5
决策、观测、belief 或 calibration history。由于只有一个 schema 变更，
故障探针标签“第一次 schema 变更之后”“中间变更之后”和“最终 schema/数据
变更之后”都标识同一个变更边界；它们不是存在三个不同变更的证据。

不支持降级。负版本、未知未来版本或 schema/版本不匹配的数据库会以
fail-closed 方式失败，并在变更前被拒绝。不会尝试自动进行 v6 到 v5 的转换。
在开始迁移前，应备份重要数据库。

## 打包和受支持平台

wheel 为纯 Python。规范化 source distribution 合同恰好包含 121 个成员。双语 RC5
说明是仓库内的 publication-gate 记录，不属于 source distribution 成员：

| Source distribution 类别 | 成员数 |
| --- | ---: |
| 包 | 91 |
| 公开文档 | 27 |
| 构建/许可 | 3 |

规范 fixture 和所需 package data 仍是分发合同的一部分。`.github` 社区健康
文件仅属于仓库，并排除在 source distribution 之外。

这 91 个包成员包括现有可导入的
`research_decision_engine.benchmarks.broader_*` 实验模块。这些模块仍为
`ASSURANCE_EXPERIMENTAL`，位于 Core 公开 API 之外。排除声明仅限私有或原始
审计、恢复、历史和 Assurance 证据或材料；它并不声称每个 Assurance 相关
实验模块都不存在。

Windows 和 Linux 是由 CPython 3.12 CI 支持的平台。不声称 macOS 由 CI
支持。

## 发布检查器和 CI

从仓库根目录运行离线发布检查器：

```console
python -m research_decision_engine.core_release_check
```

它检查规范公开清单、实时及已安装导入和签名、Assurance 导出不存在、
版本/policy 矩阵、规范 fixture 哈希、SQLite v6 及直至 `5 -> 6` 的迁移
回滚/重试矩阵、Core 测试成员、静态 policy 映射、fixture 路径卫生以及所需
package data。它不进行网络访问，也不执行外部用户工作负载。其机器结果是
规范 JSON，并且重复运行的结果必须逐字节相同。已提交的节点流在比较前将
七个固定路径拒绝参数显示规范化为不同的语义标签。这保留了每个测试身份，
同时不会在规范 fixture 中嵌入 Windows、POSIX 或文件 URI 路径字面量。

`.github/workflows/core-v1.yml` 在 Windows 和 Linux 上为 push 和 pull
request 配置相同的 Core 发布门禁，使用 Python 3.12。该工作流对仓库内容
只有只读权限，并运行发布检查器、Ruff、mypy、确定性 collection、Core
测试、构建和 clean-wheel 检查、fixture、迁移探针、replay smoke test、
adapter 以及 v3 三 policy 示例。

绿色 Core 工作流仅表示配置的 Core 合同检查在被测提交和矩阵上通过。它不会
运行或批准 broader-replication、Package-L/Package-P、P4、候选项恢复或
其他 RDE Assurance 工作；它不确立科学有效性、生产就绪、发布就绪或
PyPI/GitHub 发布权限。提交该工作流只是配置 CI，并不证明远程 Windows 或
Linux CI 已运行或通过。

## 兼容性限制

以下边界彼此不同：

- **公开 API 兼容性**仅涵盖清单所列导入及其冻结签名、公开字段、类型化错误
  族和文档化语义。
- **制品 schema 兼容性**涵盖封闭、版本匹配的 RunSpec 和 RunBundle
  schema、候选项顺序和规范制品身份。
- **SQLite 迁移兼容性**涵盖直至 schema v6 的受支持前向、逐步、原子且可
  恢复迁移；不涵盖降级或未知未来 schema。
- **确定性 replay 兼容性**涵盖根据记录观测进行版本匹配且不执行工作负载的
  决策；它不重建原始外部环境。
- **科学有效性**不会由 API、制品、迁移、replay、测试或 CI 兼容性结果确立。
- **操作系统和用户工作负载行为**取决于用户的 callable、命令、文件系统、
  工具和环境。Windows/Linux Core CI 不保证每个用户工作负载，也不作
  macOS CI 声明。

兼容性不能证明科学正确性。

## 与其他 RDE 轨道的关系

RDE Core 独立运行：RDE Continual Learning 和 RDE Assurance 均不是其
运行时、测试或打包依赖项。Continual Learning 是单独的未来产品轨道，可以
使用稳定的 Core 接口，但不能隐式更改本合同。RDE Assurance 仍处于暂停、
保留和单独授权状态。Core 测试和 CI 不会创建 Assurance 权限、S 阶段迁移、
review seal、Package-L/Package-P 批准或候选项恢复许可。

兼容性冻结只关闭一个有界 Core 合同。C6 为 `CLOSED_FOR_RC`；C7 为
`PARTIALLY_CLOSED`。本文档不会推进任一状态，RDE Core v1 仍为
`NOT_READY`。
