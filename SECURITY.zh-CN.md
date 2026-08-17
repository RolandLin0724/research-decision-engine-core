# 安全政策

[English](SECURITY.md) | 简体中文

## 支持的版本

`1.0.0rc5` 是唯一已发布的 RDE Core 版本。它作为 release candidate 获得尽力而为的
安全修复；目前还没有受支持的 RDE Core 正式发行版。

修复基于公开 main 分支的最新精确提交准备。旧的私有开发提交不是受支持的发行线。
package version `0.1.0` 和 `1.0.0rc1` 都不是已发布且受支持的发行版。

已发布的 release candidate 不附带响应时限承诺，也不附带长期支持承诺。

## 报告漏洞

- 不要为疑似安全漏洞创建公开 issue。
- 不要在任何报告中包含 secrets、credentials、私人数据库或私人 RunBundles。
- 本仓库已经公开，GitHub Private Vulnerability Reporting 是有效的外部报告渠道。
- 在每一项私有状态准备门禁通过之后，仓库已经公开。将仓库从私有改为公开需要
  operator 明确授权，并且已经获得该授权。
- GitHub Private Vulnerability Reporting 已启用，并已验证其处于 active 状态。
  获得授权并改为公开后，必须立即启用该功能并验证其处于 active 状态。验证通过
  后，请使用仓库私有的 **Report a vulnerability** 流程。
- 在 Private Vulnerability Reporting 验证通过之前，不得创建 tag、GitHub
  Release、GitHub Prerelease，不得上传 PyPI，也不得发布 release announcement。
  从仓库变为公开到验证通过的短暂间隔内，同样禁止这些操作。
- 上述前置条件在 `1.0.0rc5` 发布之前已经满足：验证先于 tag `v1.0.0rc5`、GitHub
  prerelease 与 PyPI 上传完成。以上要求对今后每一次发布操作继续有效。
- 仓库公开后，必须重新通过 Windows 与 Linux CI 以及完整的隐私和安全审计，
  才能执行任何发布操作。
- 本政策不公布个人电子邮箱地址。
- 预发布准备期间不承诺响应时间或解决时限 SLA。

不要尝试通过公开 issue 或臆想存在的 GitHub 私信功能报告漏洞。

## 应提供的信息

只提供复现和评估问题所必需的 sanitized 信息：

- 受影响的 public API 或 command；
- package 或 repository version，或者精确 commit；
- Python version；
- operating system；
- 安全影响；
- 最小化的 sanitized reproduction；
- 问题影响 source checkout 还是 installed wheel；
- 任何相关的 public exception class；以及
- 已知时提供建议的 mitigation。

绝对不要包含：

- API keys、tokens、credentials 或 authorization headers；
- 私人 database rows 或私人 RunBundle contents；
- 个人电子邮箱地址；
- 未脱敏的绝对路径；或
- 含有 credentials 的原始 CI logs。

## 安全边界

- `PythonFunctionAdapter` 在当前 Python 进程中执行用户提供的 Python 代码。
- `CommandAdapter` 执行本地子程序。
- 两种 adapter 都不是恶意代码沙箱。用户 workload 使用当前账户和进程可用的权限
  运行。
- Replay 使用记录的 observations，不会重新执行 Python callables 或 commands。
- RunBundle hashes 能检测受支持形式的篡改，但不提供 encryption、confidentiality
  或 digital signature。
- SQLite files 和 RunBundles 可能包含用户提供的 metadata 与 observations。
- RDE Core 不是 secret manager。
- RDE Core 不会创建 RDE Assurance authority。
- CI PASS 不能证明科学有效性，也不能证明用户 workload 的安全性。

adapter 有意执行受信任的本地代码，并不意味着真正的逃逸、validation bypass、
privilege boundary bypass 或 unintended execution path 不在范围内。

## 协调披露

在漏洞分诊和修复期间，应对漏洞细节保密。维护者可以请求 sanitized
reproduction。公开披露应等到已有修复或 mitigation 后再进行。目前没有
bug-bounty program，也没有 guaranteed compensation program。

公开 issue 始终禁止用于漏洞披露，包括获得授权改为公开后、Private
Vulnerability Reporting 验证通过前的短暂间隔。

## 不在范围内

以下情况本身不在范围内：

- 仅存在于恶意的用户提供 callable 或 command 代码中的漏洞；
- 已被攻陷的本地 operating system 或 Python interpreter；
- 不受支持的 Python versions；
- 仅以预期 scientific performance 为依据的主张；以及
- 用户主动写入 RunSpec、metadata、standard output、SQLite 或 RunBundle 的
  secrets。

即使涉及用户提供的代码，只要报告证明了真正的 RDE Core boundary bypass，仍然
属于安全报告范围。
