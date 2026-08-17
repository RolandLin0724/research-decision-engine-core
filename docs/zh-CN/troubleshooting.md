# 故障排查

[English](../troubleshooting.md) | 简体中文

本指南用于诊断受支持的 RDE Core v1 表面，同时不削弱其 fail-closed 合同。在尝试
全新的一次性复现之前，请保留原始数据库、RunBundle、异常和经清理的诊断上下文。
不要为了让失败消失而修改实现文件、schema、hash 或 artifact member。

## Python 与安装

### 确认工具链

RDE Core 冻结的解释器合同是 CPython 3.12（`>=3.12,<3.13`）。请先确认解释器和
`uv`，再诊断 package：

```console
python --version
uv --version
```

不同的 Python minor version 不在当前合同内。从 PyPI 安装应使用
`pip install research-decision-engine==1.0.0rc5`；`rde` 是命令行命令而不是分发包
名称，因此无关的 `pip install rde` 或名称相似的 package 会安装到别的软件。若要
排查仓库 checkout，请在仓库根目录使用已提交的 lockfile：

```console
git status --short
git diff -- pyproject.toml uv.lock
uv sync --locked
```

如果 `uv sync --locked` 失败，请先确认当前位于预期 checkout、Python 为 3.12、
`uv --version` 可用，并且 `pyproject.toml` 与 `uv.lock` 没有本地修改。然后检查最先
报告的 filesystem、cache、network 或 package-resolution 错误。不要仅为了压下失败
而重新生成或编辑 `uv.lock`、移除约束或切换为未锁定的 sync。

### 确认实际导入的内容

混淆 source checkout 和 installed wheel 可能表现为 API 故障。请用运行失败程序的
同一个解释器执行：

```console
uv run --locked python -c "import research_decision_engine as rde; print(rde.__version__); print(rde.__file__)"
uv run --locked python -c "from importlib.metadata import version; print(version('research-decision-engine'))"
uv run --locked rde --help
```

打印的 module path 表明已加载 module 的位置。distribution version 和 module path
回答不同问题；请同时记录。在 source checkout 之外，请使用已安装环境的 `python` 和
`rde`，不要加上只适用于 project 的 `uv run --locked` wrapper。

## Import 与公共 API 错误

只有冻结 public API manifest 中列出的 imports 才在 RDE 1.x 兼容线内保持稳定。
Manifest 包括 package-root imports，以及明确的
`research_decision_engine.storage.ExperimentStore` 和
`research_decision_engine.storage.SCHEMA_VERSION` imports。某个 helper 能从另一个
module 导入，并不表示它是公共 API。

遇到 `ImportError` 或缺失 symbol 时：

1. 记录精确 import statement 和公共错误；
2. 按上文确认已加载的 module path 和 distribution version；
3. 对照 [Core v1 兼容性合同](../../CORE_V1_COMPATIBILITY.md)和 public manifest；
4. 检查是否有名为 `research_decision_engine` 的本地文件或目录遮蔽 installed package；
5. 先在 clean installed wheel 中复现，再断定公共 symbol 缺失。

不要通过导入私有 normalization、filesystem、policy-factory 或 decoding helper 来绕过
缺失的公共 import。

## SQLite 数据库问题

最新及新数据库 schema 为 v6。已知旧 schema v1 到 v5 会逐版本迁移。每条迁移边各有
自己的原子 transaction；中断的边回滚后，后续 `init_schema()` 调用可以从最后一个已
提交版本继续。

这不表示每个受损数据库都能修复。负数或未知的未来 `PRAGMA user_version`、声明版本与
schema objects 不符、非规范 tables 或 triggers、integrity check 失败以及 foreign-key
失败都会被拒绝。不支持自动 downgrade。

如果数据库无法打开或初始化：

1. 停止写入，并在进一步检查前制作 byte-for-byte 备份；
2. 保留原始异常和报告的 schema version；
3. 不要编辑 `PRAGMA user_version`、删除 tables、重建 triggers 或手工修改 schema SQL；
4. 在新的一次性目录中，用 `ExperimentStore(Path("diagnostic.sqlite3"))` 初始化新数据库，
   调用 `init_schema()`，并确认 `schema_version() == SCHEMA_VERSION == 6`；
5. 如果一次性数据库成功，则调查保留的旧数据库；如果它也失败，则改查解释器、安装、
   filesystem 和 permissions。

将一次性数据库与真实历史分开。全新数据库初始化成功并不会验证或修复原始数据库。

## RunSpec 验证问题

首先精确匹配 schema、policy 和 seed：

| RunSpec | 支持的 policies | Seed 规则 |
| --- | --- | --- |
| v1 | `random` | signed 64-bit integer |
| v2 | `random`, `greedy_prior` | `random` 使用 signed 64-bit integer；`greedy_prior` 使用 `None` |
| v3 | `random`, `greedy_prior`, `information_gain_table` | `random` 使用 signed 64-bit integer；确定性 policies 使用 `None` |

公共 policy lookup 使用 `UnsupportedRunSpecSchemaError`、
`UnsupportedPolicyIdentityError` 和 `UnsupportedPolicyForSchemaError` 报告封闭的
schema/policy 失败。对于 v2/v3 验证，类型或范围错误的 random seed 使用
`PolicyConfigurationError`；确定性 policy 上非 `None` 的 seed 使用
`DeterministicPolicySeedError`；显式无效的 top-level tie-break，或者确定性 policy
configuration 中缺失或无效的 tie-break，使用 `InvalidPolicyTieBreakError`。Canonical
bytes 中缺失 top-level field 会产生普通 `ValueError`。Codec 行为因版本而异：v2/v3 的
wrong-schema bytes 使用 `RunSpecVersionMismatchError`，而 v1 decoder 把 wrong-schema、
policy 或 tie-break 情况报告为普通 `ValueError`。

对于 `greedy_prior`，`utility_by_candidate_id` 必须恰好一次列出每个 candidate。
`MissingCandidateUtilityError`、`ExtraCandidateUtilityError`、
`InvalidCandidateUtilityError` 和 `NonfiniteUtilityError` 分别区分缺失、额外、无效和
非有限值。Observations 不会更新这张静态 map。

对于 `information_gain_table`，应验证完整且由用户声明的
`FiniteTableEvidenceModel`：hypothesis 与 outcome identities、正 prior weights、严格有序的
thresholds、与 objective 匹配的 observation metric、candidate/hypothesis/outcome keys、
非负整数 likelihood weights 以及精确 likelihood row total。公共
`EvidenceModelError`、`InformationGainContractError` 及其 manifest 列出的 leaf errors
报告这些失败。Core 不会学习或修复 likelihood table。

所有 RunSpec decoders 都拒绝未知、缺失、重复或版本错误的 fields 以及非规范 bytes。
Candidate ordering 带有身份语义：调整 candidates 顺序会改变 canonical bytes 和
fingerprint，也可能改变 tie-breaking 或 seeded selection。完整合同见
[RunSpec 使用指南](run-spec.md)。

## Adapter 问题

### PythonFunctionAdapter

Callable 或其显式 normalizer 抛出的普通 exception 会变为 `WorkloadAdapterError`，原始
exception 保存在 `__cause__` 中。返回值不是精确 `NormalizedObservation`，或其
objective value 或 cost 无效，也会抛出 `WorkloadAdapterError`。

该 adapter 不提供 timeout、retry、subprocess、sandbox 或 isolation。请显式传入输入和
seed，并避免 current time、hidden global state、未声明文件和可变外部状态，以保持
callable 的确定性。Replay 使用记录的 observation，绝不会再次调用 callable。参见
[PythonFunctionAdapter 使用指南](python-function-adapter.md)。

### CommandAdapter

使用公共 error type 定位边界：

| Error | 含义 |
| --- | --- |
| `CommandBuildError` | builder 抛错、返回错误类型或产生无效 invocation |
| `CommandExitError` | direct child 返回非零 exit code |
| `CommandTimeoutError` | direct child 超过 `timeout_seconds`；不保证 descendant cleanup |
| `CommandOutputError` | stdout/stderr 大小、UTF-8、canonical JSON、normalized-observation 或 output-I/O 失败 |
| `CommandAdapterError` | 普通 process-start/wait 失败，或作为 primary failure 的 temporary-output/cleanup 失败 |

`Exception` hierarchy 之外的 execution-time `BaseException` 会在 best-effort cleanup
后原样重新抛出。当另一个 failure 已在传播时，cleanup errors 会被抑制，因此不会替换
原始诊断。

`argv` 是显式的非空 tuple，每个 member 都是一个已分离的 argument。执行始终使用
`shell=False`；shell quoting 和 metacharacters 不会被解释。对于可移植的 Python child，
使用 `sys.executable`，避免 PowerShell、`cmd.exe`、Bash 或 `/bin/sh` 特有 quoting。
配置的 stdout 和 stderr 大小是在进程退出后检查的拒绝阈值，而不是实时 stream 或 disk
cap。成功的 stdout 精确包含一个 canonical UTF-8 observation object 和一个 LF。

Replay 既不接收 builder，也不接收 invocation，并且绝不启动 command。参见
[CommandAdapter 使用指南](command-adapter.md)。

## RunBundle export 问题

Destination 必须是 `pathlib.Path` 实例，其 parent 必须已经是普通目录。Destination
不能以任何形式存在。在不改变 artifact 合同的前提下检查 parent write permissions 和
可用空间。

Export 会拒绝 symlink、junction 或 reparse ancestry、非目录 parent、destination race、
被替换的 physical identity、alias 和非预期 link count。不要绕过这些检查、改经其他
linked path 解析，或预先创建 destination。`RunBundleValidationError`、
`RunBundleV2ValidationError` 或 `RunBundleV3ValidationError` 报告对应版本的验证边界。

Export 写入并验证一个临时 sibling，随后在不替换现有 destination 的情况下发布，并验证
已发布 artifact。Windows 绑定 directory handles 和 physical identities；Linux 使用原子的
exclusive no-replace rename。这些是当前已支持的平台合同，不是通用 macOS 或 POSIX
保证，也不承诺防住每一种同账户 namespace race 或 crash。

如果 export 失败，请保留原始 trace 和 exception；只在确认 identity 后删除任务拥有的
一次性失败输出；选择新的未使用 destination，并从可信 trace 重试。参见
[RunBundle 使用指南](run-bundle.md)。

## Verify 失败

以下情况以及其他合同冲突都会导致 verification fail closed：

- 缺失、格式错误或不匹配的 65-byte SHA-256 sidecar；
- 格式错误或非规范 JSON、未知 fields 或不受支持的 schema；
- RunSpec fingerprint 或 version binding mismatch；
- RunSpec、steps 或 terminal-summary section hash mismatch；
- 不一致的 candidate、decision、rationale、observation、cost、belief 或 terminal semantics；
- 新增、移除、重命名、多个 hard link 指向或非 regular 的 member；
- 改变的 root/member physical identity，或 symlink、junction、reparse、ancestor substitution。

Physical inventory、stable-read 和 sidecar 失败使用
`RunBundleVerificationError`、`RunBundleV2VerificationError` 或
`RunBundleV3VerificationError`。V1/v2 还会把 decoded canonical/schema 失败包装进对应
verification error；v3 对这些 decoded validation 失败保留
`RunBundleV3ValidationError`。Version 和 semantic mismatch 可能暴露各自独立的公共
error families。

不要编辑原 bundle、替换 hashes、删除 sidecar 后继续使用，或削弱 identity 与 ancestry
检查。保留失败 bundle 作为 evidence，不要将它用于 replay，并从可信的已记录 run 导出
新 bundle。被篡改的 bundle 必须继续被拒绝。

## Replay 问题

使用与 v1、v2 或 v3 bundle 精确匹配的 replay function。Destination 必须是一个现有
普通 parent 下尚不存在的 child，或者现有的普通且完全空的目录。Replay 绝不与已有状态
合并。

`RunBundleReplayError`、`RunBundleV2ReplayError` 和 `RunBundleV3ReplayError` 覆盖各自
的一般 destination、persistence、integrity 和 terminal 失败。Wrong-version replay input
会包装进匹配的 versioned replay error；直接 v2/v3 verification 则可能暴露
`RunBundleVersionMismatchError`。V1 还会把不可用 policy 或 decision/rationale mismatch
包装进 `RunBundleReplayError`。V2 直接暴露 `ReplayPolicyUnavailableError`、
`ReplayDecisionMismatchError` 和 `ReplayRationaleMismatchError`。V3 直接暴露这些 errors，
还可能抛出 `ReplayBeliefMismatchError` 或 `ReplayInformationGainScoreMismatchError`。

Replay 使用已验证、已记录的 observations。它不调用 Python callable、adapter、command
builder、command、plugin 或外部 workload。它不是 container 或 environment 重建，也不
证明今天的外部 workload 会产生相同 observation。参见 [Replay 使用指南](replay.md)。

## 隐私与 secrets

RDE Core 不会自动保护用户提供的 callable 或 command 可访问的 secrets。不要把 secret
values 放进 candidate parameters 或 metadata、RunSpec、stdout observation、RunBundle、
error log、诊断复现或示例。不要向 issue 上传真实 API key 或 token。

通过环境变量传递 secret，并不保证 child output、error handling、process inspection 或
周边 logs 是安全的。用户负责 secret 的创建、访问、轮换、生命周期和撤销。Replay 使用
记录的 observations，因此不需要原 workload secret。RDE Core 不是 secret manager。

<a id="getting-useful-diagnostic-information"></a>

## 获取有用的诊断信息

有用且经过清理的报告可以包括：

- Python version 和 operating system；
- package version，以及执行使用 source checkout 还是 installed wheel；
- 公共 error class 和最小化、经过清理的 reproduction；
- SQLite schema/version identifier、RunSpec schema、RunBundle schema 和 policy ID；
- 失败发生在 construction、execution、export、verify 还是 replay；
- 对于 verify/replay，在不包含私有 artifact 内容的情况下说明失败 step category。

不要提供 API key、token、私有数据库、私有 RunBundle、未清理的本地路径、私有 CI log、
个人 email address 或其他含 secret 的内容。将原始私有 evidence 保存在本地，只分享复现
公共合同失败所需的最少已脱敏事实。

## 相关指南

- [常见问题](faq.md)
- [PythonFunctionAdapter 使用指南](python-function-adapter.md)
- [CommandAdapter 使用指南](command-adapter.md)
- [RunSpec 使用指南](run-spec.md)
- [RunBundle 使用指南](run-bundle.md)
- [Replay 使用指南](replay.md)
