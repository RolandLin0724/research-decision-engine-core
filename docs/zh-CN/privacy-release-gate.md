# 隐私与 Secret 发布门

[English](../privacy-release-gate.md) | 简体中文

本文记录公开发布的强制门槛政策。在每一项私有状态准备门禁通过并由 operator
明确授权 visibility change 之后，净化的产品仓库已经公开。随后，下文 `S0` 至
`S11` 的顺序针对 `1.0.0rc5` release candidate 已完整执行完毕。

政策正文保持不变，继续作为今后任何发布操作的标准要求。只有文末的当前状态表格
描述当前状态。

## 冻结的发布模型

| 字段 | 必需值 |
| --- | --- |
| 私有规范开发与审计仓库 | `RolandLin0724/research-decision-engine` |
| Visibility | `PRIVATE_PERMANENT` |
| 公开产品仓库 | `SEPARATE_SANITIZED_REPOSITORY` |
| 公开历史 | `ONE_NEW_ROOT_COMMIT_FROM_AN_EXACT_REVIEWED_TREE` |
| 私有 Git 历史 | `NOT_COPIED` |
| 私有 refs/stashes/reflogs | `NOT_COPIED` |
| 原始 review/recovery/audit evidence | `NOT_COPIED` |
| 公开作者 | `RolandLin0724` |
| 公开作者邮箱 | 仅使用 GitHub noreply 地址 |
| 法定姓名 | `NOT_PUBLISHED` |

私有规范仓库永久保持私有并保留完整审计历史。未来公开产品仓库是单独的 sanitized
repository，不是对私有仓库进行 visibility change。

## 强制私有准备门禁与发布顺序

任何未来仓库变为公开仓库前，必须独立验证以下全部要求：

- 在私有证据中记录精确的私有 RC source commit 和 tree。
- 按精确的已审查 Git tree 导出，不复制 `.git`。
- 建立允许进入 public snapshot 的明确文件 allowlist。
- 对完整 public snapshot 执行完整 secret scan 并通过。
- 对完整 public snapshot 执行完整 absolute-path and identity scan 并通过。
- 排除全部原始 CI、review、recovery 和 audit evidence。
- 确认不存在任何 API keys、tokens、credentials 和 authorization values。
- 发布前撤销或轮换每一项曾经暴露的 credential。
- 以 `RolandLin0724` 和 GitHub 提供的 noreply 地址创建 public commit。
- 确认不存在法定姓名和私人邮箱。
- 包含 Apache-2.0 `LICENSE`。
- 包含 `SECURITY.md`。
- 从精确的已审查 tree 创建一个全新的 root commit 作为 public snapshot。
- 在每一项私有状态准备门禁通过并由 operator 明确授权 visibility transition
  之前，保持净化的产品仓库私有。
- 不重写 private audit repository 的 Git 历史。
- private-to-public source 与 tree mapping 只保留在 private evidence 中。

上述私有状态准备门禁通过后，发布顺序必须严格执行并保持 fail closed：

1. `S0_PRIVATE_PREPARATION`：完成并验证上述每一项私有状态准备门禁。
2. `S1_OPERATOR_PUBLIC_VISIBILITY_AUTHORIZATION`：获得 operator 对
   private-to-public visibility transition 的明确授权。
3. `S2_VISIBILITY_PRIVATE_TO_PUBLIC`：将净化的产品仓库从私有改为公开。
4. `S3_IMMEDIATELY_ENABLE_PRIVATE_VULNERABILITY_REPORTING`：立即启用 GitHub
   Private Vulnerability Reporting。
5. `S4_VERIFY_PRIVATE_VULNERABILITY_REPORTING_ACTIVE`：验证 Private
   Vulnerability Reporting 处于 active 状态。
6. `S5_ENABLE_OR_VERIFY_PUBLIC_SECRET_SCANNING_AND_PUSH_PROTECTION`：启用或
   验证公开 secret scanning 和 repository push protection。
7. `S6_ENABLE_OR_VERIFY_PUBLIC_CODE_SCANNING_WHEN_AVAILABLE`：在公开 code
   scanning 可用时启用或验证该功能。
8. `S7_ACTIVATE_OR_VERIFY_MAIN_BRANCH_RULES`：激活或验证公开发布门禁所需的
   main-branch rules。
9. `S8_RUN_PUBLIC_STATE_WINDOWS_AND_LINUX_CI`：在公开 commit 上重新运行
   Windows 与 Linux CI 并通过，再重新构建 wheel 与 sdist，使 installed API 与
   文档检查通过。
10. `S9_RUN_PUBLIC_REPOSITORY_LOG_ARTIFACT_AND_PRIVACY_AUDIT`：完成公开仓库的
    日志、制品、隐私和安全审计。
11. `S10_AUTHORIZE_TAG_AND_GITHUB_PRERELEASE`：只有此后，单独的 operator
    授权才可考虑 tag 或 GitHub Prerelease。
12. `S11_OPTIONAL_SEPARATE_PYPI_RC_AUTHORIZATION`：任何可选的 PyPI RC 上传都
    需要之后另行授权。

GitHub Private Vulnerability Reporting 已启用并已验证其处于 active 状态。从
visibility 变为公开到验证其 active 状态之前，不得创建 tag、GitHub Release、
GitHub Prerelease，不得上传 PyPI，也不得发布 release announcement。公开 issue
始终禁止用于披露疑似漏洞。

禁止将 private history、refs、stashes、reflogs、raw evidence 或 recovery material
复制到 public repository。任何 release report 都不得包含 secret 或 credential
values。

## 当前状态

| 项目 | 状态 |
| --- | --- |
| 当前任务 | `POST_RELEASE_DOCUMENTATION_MAINTENANCE` |
| Full Git-history privacy audit | `COMPLETED_WITH_INCREMENTAL_EXTENSION` |
| Credential rotation/revocation | `COMPLETED_EXTERNALLY_OPERATOR_ATTESTED` |
| Sanitized product repository | `ESTABLISHED_PUBLIC` |
| Repository visibility | `PUBLIC` |
| Repository visibility change | `AUTHORIZED_AND_COMPLETED` |
| Private Vulnerability Reporting | `ENABLED_AND_VERIFIED` |
| Tag / GitHub Release / PyPI | `v1.0.0rc5 / PRERELEASE / PUBLISHED_1.0.0rc5` |

credential response status 来自外部 operator attestation。本任务没有执行或独立证明
server-side revocation，也没有检查 credential value。当前 release-facing scan 明确
比 full Git-history privacy audit 范围更窄。已建立的私有产品仓库及其审计不授权
公开发布或 repository visibility change。
