# 常见问题

[English](../faq.md) | 简体中文

## RDE Core 是什么？

RDE Core 是一个本地 Python 研究核心，用于在有限 candidate set 上进行有界的序贯实验
选择。它组合了确定性的内置 policies、可信 workload adapters、本地 SQLite history，
以及版本化的 RunSpec、RunBundle、verification 和 recorded-observation replay 合同。

## RDE Core 不是什么？

它不是 hosted service、Web UI、GPU 或 cluster executor、continual-learning trainer、
通用 plugin host、security sandbox、scientific-validity authority，也不是独立治理的
RDE Assurance 产品轨道。

## 它现在正式成为 RDE Core v1.0 了吗？

没有。公共 API 已针对 release-candidate 准备阶段冻结，但 RDE Core 仍是 pre-release，
尚未达到 release-ready。C6 文档完成并不建立后续 release readiness。

## 它需要 GPU 吗？

不需要 GPU，而且当前 Core 不提供 GPU executor。这并不限制可信的用户 workload 在
Core executor 表面之外可以使用什么。

## 它需要云服务吗？

不需要强制云服务。实验历史使用本地 SQLite，不需要 database server。

## 支持哪些 Python 版本？

冻结的 Core v1 合同支持 CPython 3.12（`>=3.12,<3.13`）。不要因为某次偶然的本地运行
就推断它支持其他 Python minor version。

## 新实验应该使用哪个 RunSpec 和 RunBundle 版本？

当新实验需要完整三策略集合时使用 v3。V1 和 v2 在 RDE 1.x 兼容线内继续受支持，但
版本是精确绑定的：RunSpec、RunBundle、verifier 和 replay function 必须匹配。

## `random`、`greedy_prior` 和 `information_gain_table` 有何区别？

| Policy | 当前行为 |
| --- | --- |
| `random` | 在保持 RunSpec 顺序的剩余 candidates 上进行 seeded selection without replacement |
| `greedy_prior` | 选择用户声明的最高静态 candidate utility，精确相等时由 RunSpec 顺序打破平局 |
| `information_gain_table` | 根据用户声明的有限 hypothesis/outcome/likelihood model 和当前精确 belief，按确定性的 expected information gain 选择 |

V1 支持 `random`；v2 增加 `greedy_prior`；v3 增加
`information_gain_table`。

## `information_gain_table` 会自动学习 likelihood model 吗？

不会。用户显式声明 hypotheses、prior weights、outcome partition 和完整的
candidate-by-hypothesis-by-outcome likelihood table。Core 根据记录的 observations
更新精确 belief weights；它不会学习或科学验证该 model。

## `greedy_prior` 会根据 observations 更新吗？

不会。它的 utility map 是静态的调用方声明。Observations 不会更新它。

## Replay 会重新运行我的 Python function 或 command 吗？

不会。Replay 不接收 callable、command builder 或 command。它使用已验证 RunBundle 中
已经记录的 observations，重新计算 Core decision 合同。

## RunBundle 是 container、virtual machine 或完整 environment snapshot 吗？

不是。它不保留 operating system、Python environment、executable、dependency set、
hardware device、network service、任意 file 或 external data。

## RunBundle hash 是 digital signature 或 encryption 吗？

不是。SHA-256 绑定提交给 verifier 的 bytes，用于 integrity checking。它不识别 signer、
不提供 third-party attestation、不加密内容，也不提供 confidentiality。能替换两个 bundle
members 的人可以构造另一个内部自洽的 artifact。

## Verify PASS 能证明科学结论正确吗？

不能。Verification 检查 artifact structure、hashes、冻结的 version bindings 和内部
decision semantics。它不证明 workload、model、observation 或科学结论为真。

## PythonFunctionAdapter 或 CommandAdapter 是 security sandbox 吗？

不是。`PythonFunctionAdapter` 在当前 process 中运行可信 code。
`CommandAdapter` 用 `shell=False` 启动可信 direct child，但它不是 sandbox 或 container，
也不保证 descendant process-tree cleanup。

## 可以动态加载任意 policy plugin 吗？

不可以。当前 Core policy 和 replay factories 是有限、静态且版本化的。Artifact 不能选择
任意 module、class、callable、registry、entry point 或 URL。

## SQLite migration 会自动 downgrade 数据库吗？

不会。已知旧 schemas 会逐个原子 version step 向前迁移到 v6。不支持 downgrade 和未知的
未来 schemas。

## RDE Core 依赖 RDE Assurance 吗？

不依赖。它们是独立的产品轨道。Core 运行不需要 Assurance。

## Core CI PASS 等于 RDE Assurance approval 吗？

不等于。Core CI 通过既不是 Assurance approval，也不证明用户 workload 或科学结论正确。

## RDE Continual Learning 已包含在 Core 中吗？

没有。Continual Learning 不属于当前 RDE Core v1 表面。

## 可以在真实实验中使用 RDE Core 吗？

已建立的 adapters 可以连接可信的本地 Python 或 command workloads，但 Core 仍是
pre-release。用户必须验证自己的 domain model、workload、observations、operating
procedures 和 safety boundaries；Core 不会替用户执行这些科学或运行验证。

## 应该怎样报告 bug？

请遵循[经过清理的最小复现指南](troubleshooting.md#getting-useful-diagnostic-information)。
可以包含公共 version 和 error 信息，但不要在报告中放入私有数据库、bundles、paths、
logs 或 secrets。

## 可以把 API key 放入 RunSpec 或 RunBundle 吗？

不应该。不要把 secret values 放入 candidate parameters、RunSpec content、observations、
RunBundles、示例或诊断 logs。RDE Core 不是 secret manager，只使用环境变量也不会自动让
周边 output 变得安全。

## 当前可以从 PyPI 安装 package 吗？

当前 pre-release Core 没有声称或授权受支持的 PyPI 安装。请使用 README 中描述的、
经授权的 source-checkout 安装；不要改用名称相似的 package。

## 在哪里可以了解更多？

- [故障排查](troubleshooting.md)
- [PythonFunctionAdapter 使用指南](python-function-adapter.md)
- [CommandAdapter 使用指南](command-adapter.md)
- [RunSpec 使用指南](run-spec.md)
- [RunBundle 使用指南](run-bundle.md)
- [Replay 使用指南](replay.md)
