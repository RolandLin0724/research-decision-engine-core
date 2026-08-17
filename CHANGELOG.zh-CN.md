# 变更日志

[English](CHANGELOG.md) | 简体中文

Research Decision Engine Core（简称 RDE Core）处于预发布阶段。

- **已发布候选：** `1.0.0rc5`
- **公开发布：** `RELEASE_CANDIDATE_ONLY`
- **先前私有候选：** `1.0.0rc4`，在从面向发布的表面移除私有源提交引用后于
  公开发布前被取代

净化的产品仓库已经公开。标签 `v1.0.0rc5` 与对应的 GitHub prerelease 均已存在，
软件包也已以 `1.0.0rc5` 版本位于 PyPI 上。本变更日志描述的是已发布的 release
candidate，而不是最终的 v1.0 版本。

## [1.0.0rc5] - 2026-08-17

### Added（新增）

- 新增版本化的 RunSpec 与 RunBundle 合同：v1 支持 `random`；v2 支持
  `random` 和 `greedy_prior`；v3 支持 `random`、`greedy_prior` 和
  `information_gain_table`。
- 新增用于可信本地工作负载的 `PythonFunctionAdapter` 与 `CommandAdapter`。
- 新增基于 SQLite 的执行历史，并支持中断与恢复。
- 新增 RunBundle 导出和只读验证，以及使用已记录 observations 的版本匹配
  replay。
- 新增双语用户文档、Windows 与 Linux CI，以及仓库内的社区 issue 和
  pull-request 模板。

### Changed（变更）

- 将公开产品展示品牌对齐为 Research Decision Engine Core，简称为 RDE Core。
  Python 分发包仍为 `research-decision-engine`，导入包仍为
  `research_decision_engine`，CLI 仍为 `rde`。
- 将 RC 公共 API 合同冻结为清单中列出的恰好 112 个符号。内部模块或名称即使
  可以导入，也不会仅因此成为公共 API。
- 将最新 SQLite schema 推进至 v6，同时保留受支持的逐版本旧 schema 迁移。
- 将构建后端统一为 `uv_build==0.11.32`。
- 明确面向未来公共产品的净化 source-distribution 边界；私有开发材料以及私有
  或原始的审计、恢复、历史和 Assurance 证据或材料均排除在外。

### Fixed（修复）

- 将 `DESIGN.md`、`PLAN.md` 和 `SPEC.md` 的 frozen digest 绑定到其 exact
  committed LF blob bytes。文档 blob、算法行为和 schema 均未改变；路径专用的
  `.gitattributes` 规则现在会在 Windows 和 Linux 上保留 LF checkout 表示。
- 使每个受支持的 SQLite 迁移步骤保持原子性，并可在中断后从最后提交的 schema
  恢复。
- 使 Markdown checkout 的行尾在 Windows 与 Linux 之间可移植。
- 改善 Windows API 类型在 Linux 上进行软件包检查与导入时的可移植性。
- 改善 RunBundle identity 与 ancestry 在受支持的 Windows 和 Linux 工作流之间的
  可移植性。
- 使兼容性检查感知 producer metadata，从而让调用方按照自身声明比较相应的
  identity-bearing sections。
- 从面向发布的文档、运行时 metadata、测试、wheel 与 source distribution 中移除
  私有源提交身份。公开语义 role token 是互不相同的非 Git 标识符；实际 Git 读取
  仅使用单独捕获的实现提交。

### Security（安全）

- 确立 Apache-2.0 许可和双语安全策略。
- 记录 fail-closed 的隐私与 secret 门禁；任何未来公开发布之前都必须通过该门禁，
  且该门禁尚未授权公开可见或发布。
- 修正 publication-security 顺序，使其符合 GitHub 实际的公开仓库 Private
  Vulnerability Reporting 能力：operator 明确授权先于公开可见；随后立即启用并
  验证 Private Vulnerability Reporting；任何 tag、GitHub Prerelease、PyPI 上传
  或 release announcement 之前，必须通过公开安全、CI 与隐私门禁。公开 security
  issue 仍禁止用于漏洞报告。
- 对未知 schema、不受支持的 policy identity、格式错误的 artifact 和 identity
  不匹配实行 fail-closed 的 RunBundle identity 检查。
- 保持 replay 不执行工作负载：它使用已记录的 observations，且不会调用 Python
  callable、adapter 或 command。
- 明确 adapter 位于可信本地进程边界，并不是针对恶意代码的 sandbox。

### Packaging（打包）

- 将规范化 source distribution 定义为恰好 121 个成员：91 个软件包成员、27 个
  公共文档成员和 3 个构建/许可成员。RC5 说明是仓库内的 publication-gate 记录，
  不属于 sdist 成员。
- `.gitignore`、`.gitattributes`、`.github/**` 社区健康文件、`tests/**`，以及
  私有开发材料和私有或原始的审计、恢复、历史和 Assurance 证据或材料均不进入
  source distribution。仅属于仓库的贡献指南不会进入归档。
- 新增对 wheel、source distribution、仅从解压后的 source distribution 重建的
  wheel、干净安装和已安装 metadata 的验证。
- 通过将软件包版本从 `0.1.0` 同步为 `1.0.0rc1`，建立了先前私有候选。
- 因公开产品品牌和发布 metadata 对齐改变了 wheel 与 sdist 字节，将当前私有
  候选从 `1.0.0rc1` 推进到 `1.0.0rc2`。算法、存储和 schema 行为均未改变。
  公开发布保持 `NONE`，标签保持 `NONE`，GitHub Release 保持 `NONE`，PyPI
  状态保持 `NOT_PUBLISHED`。
- 在 RC2 未通过跨平台 release-contract 验证后，将当前私有候选从
  `1.0.0rc2` 推进到 `1.0.0rc3`。RC3 从 exact committed LF blob bytes 派生
  三个 frozen design-document hash。RC2 制品继续作为失败的私有证据保留；
  算法和 schema 均未改变，也未创建标签、GitHub Release 或 PyPI 发布。
- 因修正后的 publication-security 顺序改变了打包文档和分发制品字节，将当前
  私有候选从 `1.0.0rc3` 推进到 `1.0.0rc4`。RC3 在公开发布前被取代。产品运行时
  算法、schema 和公共 API 符号均未改变；只有
  `research_decision_engine.__version__.value` 改变。仓库 visibility 保持
  `PRIVATE`，tag 保持 `NONE`，GitHub Release 保持 `NONE`，PyPI 保持
  `NOT_PUBLISHED`。
- 因移除私有源提交引用改变了 wheel 与 source-distribution 字节，将当前私有候选
  从 `1.0.0rc4` 推进到 `1.0.0rc5`。精确私有来源仅保留在外部私有证据中。
  公共 API 符号、SQLite schema、RunSpec/RunBundle/replay 合同和生产决策算法均
  未改变；只有 `research_decision_engine.__version__.value` 改变。仓库
  visibility 保持 `PRIVATE`，tag 保持 `NONE`，GitHub Release 保持 `NONE`，
  PyPI 保持 `NOT_PUBLISHED`。
- 将 `1.0.0rc5` 以标签 `v1.0.0rc5`、GitHub prerelease 以及恰好两个 PyPI 分发文件
  的形式发布；上传通过 GitHub OIDC Trusted Publishing 完成，带有 digital
  attestations，且未使用 API token。本节前面各条中给出的 `Repository visibility`、
  `tag`、`GitHub Release` 与 `PyPI` 取值记录的是每次候选推进时的状态，属于历史
  记录，并非当前状态。

### Documentation（文档）

- 新增双语 Quickstart；Python-function 与 command-adapter 指南；RunSpec、
  RunBundle 与 replay 指南；以及 Troubleshooting 和 FAQ 页面。
- 新增双语贡献指南，以及 issue 和 pull-request 模板。
- 新增双语兼容性文档，以及私有、尚未发布的 RC 候选文档。保留的 RC3 说明现已
  明确 RC3 是被取代且从未发布的私有候选；从未发布的 RC1、失败的 RC2 和被
  取代的 RC3 证据仍保留在私有历史和不可变制品中。
- 新增语义对应的英文与简体中文说明：项目仍为实验性预发布项目，通过 Vibe
  Coding 工作流开发，整个开发过程使用了 AI 工具，并且尚未在真实生产环境中
  运行过。
- 新增双语 `1.0.0rc5` 说明，用于私有、尚未发布且来源安全的候选。
