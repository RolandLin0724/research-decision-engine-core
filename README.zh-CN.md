# Research Decision Engine Core

[English](README.md) | 简体中文

## RDE Core 是什么

Research Decision Engine Core（简称 RDE Core）是一个本地 Python 研究核心，用于在有限候选集合上进行有界的序贯
实验选择。它将确定性的内置策略、可信的 workload adapter、本地 SQLite 历史以及
可验证、可 replay 的 RunBundle 组合在一起。

## 项目状态与开发方式

Research Decision Engine Core 仍是一个实验性、预发布项目。

这个项目是我全程以 Vibe Coding 的方式开发的。也就是说，我在设计、编码、
测试和文档过程中持续使用了 AI 工具。我做出了最终选择，也检查了工作结果，
但项目中仍然可能存在错误和未经充分验证的假设。

RDE Core 目前还没有在真实生产环境中运行过，也没有经过大量真实用户或大量
真实工作负载的验证。现有证据主要来自自动化测试、可重复构建和 CI 检查。
这些检查很有帮助，但不能代替真实环境中的长期使用。

请把 RDE Core 当作研究软件使用。建议先从小规模、非关键、可回滚的任务开始，
并自行检查输入、输出和相关假设。不要把它作为高风险决策的唯一依据。

欢迎提交清楚的问题报告、修正和实际使用反馈。

## 它不是什么

RDE Core 不是托管服务、Web UI、GPU 或集群执行系统、持续学习训练器，也不是
通用插件宿主。它不证明实验具有科学有效性，也不属于独立治理的 RDE Assurance
产品轨道。

## 当前状态

- **已发布的候选版本：** 当前已发布的候选版本是 `1.0.0rc5`。它是 release
  candidate，而不是最终的 RDE Core v1.0 版本。
- **RC API 冻结：** 公共 API 已针对 release candidate 阶段冻结，并受 RDE 1.x
  兼容性合同保护。
- **先前私有候选：** `1.0.0rc4` 在从面向发布的表面移除私有源提交引用后于
  公开发布前被取代。其私有、未发布证据仅在外部私有证据中保留。
- **发布状态：** 净化的产品仓库已经公开。tag `v1.0.0rc5` 与对应的 GitHub
  prerelease 均已存在，`research-decision-engine` 分发包的 `1.0.0rc5` 版本也已
  位于 PyPI 上。
- **私有验证来源：** 精确的私有提交与工作流身份仅保留在外部私有证据中；
  公开软件包不对其编码。
- 该 Core CI 结果不是 RDE Assurance 批准，也不是生产就绪批准。

## 项目链接

- [PyPI 项目](https://pypi.org/project/research-decision-engine/)
- [PyPI 1.0.0rc5](https://pypi.org/project/research-decision-engine/1.0.0rc5/)
- [源代码仓库](https://github.com/RolandLin0724/research-decision-engine-core)
- [GitHub prerelease v1.0.0rc5](https://github.com/RolandLin0724/research-decision-engine-core/releases/tag/v1.0.0rc5)

## 环境要求

- CPython 3.12
- `uv`
- 通过 Python 标准库访问的本地 SQLite；无需数据库服务器
- 无必需的云服务
- 无必需的 GPU

## 安装

从 PyPI 安装已发布的候选版本：

```console
pip install research-decision-engine==1.0.0rc5
```

分发包名称是 `research-decision-engine`，导入包是 `research_decision_engine`，
命令行工具是 `rde`。请不要改用名称相近的其他软件包。由于目前只发布了 release
candidate，直接执行 `pip install research-decision-engine` 在未启用预发布版本时
不会解析到任何版本。

从净化产品仓库的 checkout 进行开发的贡献者请改为安装锁定环境：

```console
git clone https://github.com/RolandLin0724/research-decision-engine-core.git
cd research-decision-engine-core
uv sync --locked
```

永久保留的审计仓库仍为私有仓库，使用或开发 RDE Core 都不需要它。

## 首次运行

确认已安装的命令及其子命令：

```console
rde --help
```

创建本地 SQLite 历史，并请求一个建议实验：

```console
rde --db history.sqlite3 init
rde --db history.sqlite3 suggest
```

两条命令都输出 JSON。`init` 报告数据库已初始化，`suggest` 报告下一个候选及其
参数。任何数据都不会离开本机。

## 十分钟 Quickstart

安装后，创建一个新的空工作目录：

```console
mkdir quickstart
cd quickstart
```

将以下内容保存为 `quickstart.py`：

```python
from pathlib import Path

from research_decision_engine import (
    CandidateSpec,
    NormalizedObservation,
    PythonFunctionAdapter,
    RunSpecV3,
    export_run_bundle_v3,
    replay_run_bundle_v3,
    run_workload_trace_v3,
    verify_run_bundle_v3,
)
from research_decision_engine.storage import ExperimentStore

calls = {"count": 0}


def score(candidate: CandidateSpec) -> NormalizedObservation:
    calls["count"] += 1
    x = float(candidate.parameters["x"])
    return NormalizedObservation(
        objective_value=-(x - 2.0) ** 2,
        cost=0.25,
    )


candidates = [
    CandidateSpec("point-1", {"x": 1.0}),
    CandidateSpec("point-2", {"x": 2.0}),
    CandidateSpec("point-3", {"x": 3.0}),
]

adapter = PythonFunctionAdapter(
    score,
    adapter_id="quickstart.python",
    adapter_version="1",
)

run_spec = RunSpecV3(
    candidates=candidates,
    policy_id="random",
    policy_config={},
    policy_seed=17,
    experiment_count_budget=2,
    cost_budget=1.0,
    adapter_id="quickstart.python",
    adapter_version="1",
    objective_name="score",
    objective_direction="maximize",
)

database = Path("history.sqlite3")
with ExperimentStore(database) as store:
    store.init_schema()
    trace = run_workload_trace_v3(
        store,
        run_spec=run_spec,
        adapter=adapter,
    )
    history = store.list_workload_experiments(run_spec.fingerprint())

assert database.is_file()
assert len(history) == calls["count"] == len(trace.steps) == 2

bundle_directory = Path("run-bundle")
exported = export_run_bundle_v3(bundle_directory, trace=trace)
verified = verify_run_bundle_v3(bundle_directory)

assert exported.valid is True
assert verified.valid is True
assert verified.bundle_sha256 == exported.bundle_sha256

before_replay = calls["count"]
replay_directory = Path("replay")
replay_directory.mkdir()
assert not any(replay_directory.iterdir())

replayed = replay_run_bundle_v3(bundle_directory, replay_directory)

assert calls["count"] == before_replay
assert replayed.adapter_execution_count == 0
assert replayed.callable_execution_count == 0
assert replayed.command_execution_count == 0
assert replayed.equivalent is True
assert (replay_directory / "replay.sqlite3").is_file()

print(f"RunSpec: {run_spec.schema}")
print(f"Candidates executed: {verified.selected_candidate_ids}")
print(f"SQLite: {database}")
print(f"RunBundle verified: {verified.valid}")
print(f"Replay equivalent: {replayed.equivalent}")
print(f"Replay callable executions: {replayed.callable_execution_count}")
```

在该目录下，使用已安装 RDE Core 的解释器运行：

```console
python quickstart.py
```

从仓库 checkout 开发的贡献者可以改为在锁定环境中运行：

```console
uv run --locked python quickstart.py
```

最后几行应确认 `RunBundle verified: True`、`Replay equivalent: True` 和
`Replay callable executions: 0`。该目录现在包含 `history.sqlite3`、由两个文件组成的
`run-bundle/`，以及 `replay/replay.sqlite3`。

初始运行会调用 `score` 两次。随后 replay 使用记录的 observations，在新的 SQLite
状态中重建并检查决策历史；它**不会**再次调用 `score` 或任何其他 workload callable。

该示例有意设计为在一个工作目录中只运行一次。如需再次运行，请换用另一个新的空
目录。

## 支持的合同摘要

| RunSpec / RunBundle | 支持的策略 |
| --- | --- |
| v1 | `random` |
| v2 | `random`, `greedy_prior` |
| v3 | `random`, `greedy_prior`, `information_gain_table` |

需要完整三策略集合的新实验应使用 v3。V1 和 v2 仍受 RDE 1.x 兼容性合同支持；
Core 不会静默升级或降级这些 artifacts。

## 会持久化什么

SQLite 历史以 RunSpec fingerprint 为键保存已完成的 workload records。导出的
RunBundle 携带完整的版本化 replay record，其中包括：

- RunSpec identity
- candidate decisions
- observations
- rationales
- 适用时的 belief lineage
- 每一步及累计 cost
- terminal summary

## 信任边界

- `PythonFunctionAdapter` 在当前 Python 进程中执行用户提供的 Python callable；
  该 callable 必须可信。
- Core 不声称会沙箱化恶意 Python，并且该 adapter 不提供安全隔离。
- Replay 使用记录的 observations 并检查静态 decisions；它不会调用 workload
  callable、调用 adapter 或执行 command。
- RDE Core 与 RDE Assurance 是独立的产品轨道。Core 结果不会产生任何 Assurance
  authority 或 approval。

## 许可证

RDE Core 采用 Apache License 2.0。
详见 [LICENSE](LICENSE)。

公开项目身份：RolandLin0724。

## 安全与隐私

- [安全政策与漏洞报告](SECURITY.zh-CN.md)
- [隐私与 secret 发布门](docs/zh-CN/privacy-release-gate.md)

已完成的当前树与历史隐私审计不授权直接公开转换永久私有仓库。在每一项私有准备
门禁通过并由 operator 明确授权 visibility change 之后，净化的产品仓库已经公开。
Private Vulnerability Reporting 已启用并已验证。tag `v1.0.0rc5`、GitHub
prerelease 以及 `1.0.0rc5` 的 PyPI 发布均在这些门禁通过之后完成。

## 后续阅读

- [变更日志](CHANGELOG.zh-CN.md)
- [RDE Core v1 兼容性合同](CORE_V1_COMPATIBILITY.zh-CN.md)
- 1.0.0rc5 发布说明保存在本仓库的 `docs/release-notes/1.0.0rc5.md`，并被有意
  排除在 121-member source distribution 之外。
- [1.0.0rc3 历史说明（已被取代的私有候选 / 尚未发布）](docs/zh-CN/release-notes/1.0.0rc3.md)
- [RDE Core v1 测试说明](TESTING.md)
- [PythonFunctionAdapter 使用指南](docs/zh-CN/python-function-adapter.md)
- [CommandAdapter 使用指南](docs/zh-CN/command-adapter.md)
- [RunSpec 使用指南](docs/zh-CN/run-spec.md)
- [RunBundle 使用指南](docs/zh-CN/run-bundle.md)
- [Replay 使用指南](docs/zh-CN/replay.md)
- [故障排查](docs/zh-CN/troubleshooting.md)
- [常见问题](docs/zh-CN/faq.md)
