# 为 RDE Core 做贡献

[English](CONTRIBUTING.md) | 简体中文

RDE Core 仍处于预发布阶段。当前规范开发仓库是私有仓库。本指南适用于现阶段经
授权的协作者，也适用于未来经过净化的公开产品仓库中的贡献者。目前不存在公开的
v1.0 发行版。

## 贡献之前

- 阅读 [README](../README.md)（另有[简体中文版](../README.zh-CN.md)）、
  [Security Policy](../SECURITY.md)（另有[简体中文版](../SECURITY.zh-CN.md)）
  以及与改动相关的用户指南。
- 不要在公开 issue 中报告疑似安全漏洞。请遵循 Security Policy 中的私密报告
  说明。
- 不要在 issue、pull request、test、fixture、log 或 example 中包含 API keys、
  tokens、私人数据或原始审计证据。
- 确认改动应属于 RDE Core，而不是 RDE Continual Learning、RDE Assurance 或
  外部 extension。
- 不要因为内部 module 可以 import 就认为它属于 public API。

## 开发环境

使用 CPython 3.12 和 `uv` 0.11.32。使用“必需的本地检查”一节列出的同步命令创建
锁定的开发环境。

不要为这个预发布源代码树记录或依赖 PyPI 安装方式。command、documentation、
test 和 reproduction 不得包含本地绝对路径。

## 贡献类型

适合提交的窄范围贡献示例包括：

- bug 修复；
- portability 修复；
- documentation 更正；
- 保留现有 test nodes 和 contracts 的 test 改进；
- 有证据支持的窄范围 performance 修复；
- 冻结 public contract 范围内的 adapter 改进；以及
- compatibility 和 migration 修复。

实现下列改动之前，必须先创建 issue 并取得 design agreement：

- 新增 public API symbols；
- 新增 RunSpec 或 RunBundle schema versions；
- 新增 policies；
- SQLite schema changes；
- 新增 adapters 或 executor models；
- 移除或重命名 public symbols；
- 更改 replay semantics；或
- 更改 privacy、security 或 packaging boundaries。

提交或讨论 proposal 并不承诺它会被接受或实现。

## Public compatibility boundaries

- 112 个 public symbols 已针对 release candidate (RC) 冻结。
- 内部对象可以 import 并不构成 compatibility promise。
- RunSpec 和 RunBundle v1、v2、v3 继续受支持。
- schema 绝不能被静默 upgrade 或 downgrade。
- SQLite migrations 必须保持逐步 atomic 且 resumable。
- 不得随意重新生成 canonical fixtures。
- Replay 必须使用已记录的 observations，且不得执行原始 workload。
- 精确的 public errors、signatures 和 data fields 需要 compatibility review。

## 必需的本地检查

从仓库根目录运行完整的本地 gate：

```powershell
uv lock --check
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy .
uv run pytest
uv run python -m research_decision_engine.core_release_check
uv build
```

focused tests 可在开发期间提供帮助，但不能替代这个完整 gate。

## Tests 和确定性证据

- 不要删除任何 opening test node。
- 不要使用 `skip` 或 `xfail` 隐藏缺陷。
- 保持 test collection 确定性。
- 当行为可能因平台而异时，提供相关的 Windows 和 Linux portability evidence。
- 为报告的缺陷新增或指出一个 test reproduction。
- 不要削弱 fail-closed behavior。
- 保持 replay workload execution count 为零。

## Packaging boundary

- build backend 是 `uv_build` 0.11.32。
- 已批准的 normalized source distribution (sdist) 包含 121 个 members：
  91 个 package members、27 个 public-document members 和 3 个
  build/licensing members。
- 私有 development material 以及私有 audit、recovery 和 RDE Assurance
  evidence 均被排除。
- `.github` community-health files 仅属于仓库，并从 sdist 中排除。

121-member count 是当前 release contract，并非对每个未来版本的承诺。对该数量的
任何更改都需要显式 release-contract review。

## 文档

如果改动影响用户可见行为或安全性，请以相同语义更新相应的英文和简体中文文档。
Code identifiers、schema IDs 和 error classes 不翻译。

## 隐私与安全

遵循根目录的 [Security Policy](../SECURITY.md) 及其
[简体中文版本](../SECURITY.zh-CN.md)。贡献和公开讨论必须排除：

- API keys、tokens 和 credentials；
- 私人电子邮箱地址；
- 并非有意公开的法律身份；
- 本地绝对路径；
- 真实的私人数据库；
- 私人 RunBundles；
- 未脱敏的 CI logs；以及
- 原始 review 或 recovery evidence。

## Pull requests

pull request 必须：

- 只包含一个连贯改动，并给出清晰理由；
- 在适用时链接 issue；
- 明确说明 compatibility impact；
- 列出实际运行的精确 tests；
- 说明 documentation impact 以及 privacy 或 security impact；
- 避免无关的 formatting churn；
- 避免提交生成的 build artifacts；以及
- 保持可评审，且本指南不强制要求 force-push。

## 许可与来源

仓库代码采用 Apache-2.0 许可。你必须有权提交 contribution 中的全部 code、
documentation、data 和 fixtures。请标明 third-party material 的 provenance，并
确认其 license 兼容。目前未配置 Contributor License Agreement (CLA) 或
Developer Certificate of Origin (DCO) automation。提交 contribution 并不授权
纳入 proprietary 或 confidential material。

本指南不提供法律建议。
