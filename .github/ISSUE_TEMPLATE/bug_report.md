---
name: Bug report / Bug 报告
about: Report a reproducible RDE Core defect / 报告可复现的 RDE Core 缺陷
title: ""
labels: ""
assignees: ""
---

# Bug report / Bug 报告

Suspected security vulnerabilities do not belong in public issues. Follow the
private reporting instructions in [SECURITY.md](../../SECURITY.md) or its
[Simplified Chinese counterpart](../../SECURITY.zh-CN.md).

疑似安全漏洞不得通过公开 issue 报告。请遵循
[SECURITY.md](../../SECURITY.md) 或其
[简体中文版本](../../SECURITY.zh-CN.md)中的私密报告说明。

## Required confirmations / 必需确认

- [ ] This is not a security vulnerability. / 这不是安全漏洞。
- [ ] No API key, token, credential, private email, private database, private
      RunBundle, raw audit evidence, or unredacted absolute path is included. /
      未包含 API key、token、credential、私人电子邮箱、私人数据库、私人
      RunBundle、原始审计证据或未脱敏的绝对路径。
- [ ] The issue reproduces in a supported Python 3.12 environment, or I clearly
      state otherwise below. / 此问题可在受支持的 Python 3.12 环境中复现，或我已在
      下方明确说明例外情况。
- [ ] I searched existing issues. / 我已搜索现有 issues。

## Affected surface / 受影响范围

**Affected public API or command / 受影响的 public API 或 command**

<!-- Name the exact public API or command. / 请写出精确的 public API 或 command。 -->

**Package version or exact commit / package version 或精确 commit**

<!-- Provide a version or commit identifier. / 请提供 version 或 commit 标识符。 -->

**Execution source / 执行来源**

<!-- State whether this is a source checkout or installed wheel. / 请说明是 source checkout 还是 installed wheel。 -->

**Operating system / 操作系统**

**Python version / Python 版本**

## Minimal sanitized reproduction / 最小化脱敏复现

<!-- Include only the minimum sanitized code or data needed to reproduce the defect. / 只包含复现缺陷所需的最少脱敏 code 或 data。 -->

## Steps to reproduce / 复现步骤

1.
2.
3.

## Expected result / 预期结果

## Actual result / 实际结果

## Public exception class / Public exception class

<!-- Name the public exception class, if one was raised. / 如果抛出了 public exception class，请写出名称。 -->

## Contract areas involved / 涉及的合同范围

State whether SQLite, RunSpec, RunBundle, replay, or adapter behavior is
involved. / 请说明是否涉及 SQLite、RunSpec、RunBundle、replay 或 adapter
behavior。

## Relevant tests already run / 已运行的相关 tests

<!-- List exact commands and results. / 请列出精确 commands 和结果。 -->
