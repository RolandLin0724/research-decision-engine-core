# CommandAdapter 使用指南

[English](../command-adapter.md) | 简体中文

`CommandAdapter` 将可信的本地 executable 接入有界的 RDE Core 实验循环。当
Python child process、编译程序或科学 command-line tool 能通过一次显式调用，把
有限候选转换为当前 stdout normalized observation 时，应使用该 adapter。

## 公共 imports

adapter 及其 typed errors 的冻结公共 imports 为：

```text
from research_decision_engine import CommandAdapter, CommandAdapterError, CommandBuildError, CommandExitError, CommandInvocation, CommandOutputError, CommandTimeoutError
```

可运行示例还会使用 package 根目录中的 `CandidateSpec`、公共 v3 run 和 RunBundle
函数，以及 `research_decision_engine.storage.ExperimentStore`。

当前 `rde` CLI 没有 CommandAdapter 配置命令。请通过 Python API 构造并运行该
adapter。

## 精确 builder 与 invocation 合同

公共签名为：

```text
CommandAdapter(
    command_builder: Callable[[CandidateSpec], CommandInvocation],
    *,
    adapter_id: str,
    adapter_version: str,
)

CommandInvocation(
    *,
    argv: tuple[str, ...],
    cwd: Path | None,
    environment_overrides: Mapping[str, str],
    inherit_environment: bool,
    timeout_seconds: float,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
)

adapter.evaluate(candidate: CandidateSpec) -> NormalizedObservation
```

每个 `CommandInvocation` 参数都是必填参数；公共 API 没有默认值。可信的 in-process
builder 接收一个精确类型的 `CandidateSpec`，只调用一次，并且必须返回一个精确
类型的 `CommandInvocation`。adapter 不会自动展开 candidate fields。不受限制的可信
builder 会显式读取 `candidate.candidate_id` 和/或 `candidate.parameters` 并构造任意
invocation field；本示例会验证 `x` 并将其放入 `argv`。

invocation fields 的边界如下：

- `argv` 是非空的精确 string tuple。executable 是 `argv[0]`；后续每个 tuple member
  都是一个已经分隔好的参数。空 executable name 和 NUL 字符会被拒绝。
- `cwd` 是现有的 `pathlib.Path` 或 `None`；child 启动前会再次检查。
- `environment_overrides` 仅包含 string keys 和 values，并会被复制进 immutable
  invocation。`inherit_environment=True` 时，先复制当前 environment 再覆盖；为
  `False` 时，child 只接收 overrides。在 Windows 上，每个 override 会先移除按
  `casefold()` 与它匹配的 inherited keys；在 Linux 上，不同大小写的 environment
  keys 保持为不同 keys。
- `timeout_seconds` 必须有限且严格为正；`max_stdout_bytes` 和
  `max_stderr_bytes` 必须是严格为正的精确 integers。

公共 API 没有 shell、stdin、encoding、retry、process-tree、container 或
remote-worker 参数。stdout encoding 由下述 observation 合同固定；stderr 保持为
bytes。

## 直接执行：`shell=False`

adapter 使用以下设置把 tuple 直接传给本地 child process：

```text
shell=False
stdin=subprocess.DEVNULL
```

不要把一整条 shell command 作为一个 string 传入，也不要嵌入 shell quoting。例如
应使用 `(sys.executable, "workload.py", "--level", "3")`，而不是
`("python workload.py --level 3",)`。shell metacharacters 没有特殊含义，只是参数
数据。

stdout 和 stderr 会重定向到 repository 外由 task 所有的 regular files。child
退出后，先检查 byte sizes，再读取内容。配置的 sizes 是拒绝阈值，不是 live stream
或 disk-usage caps。adapter 不会自动 retry。

## 精确 stdout observation

成功的 child 必须只写一个 canonical UTF-8 JSON object，后跟一个 LF。例如，完整
stdout bytes 是以下内容的 UTF-8 编码：

```json
{"cost":0.25,"objective_value":1.5}
```

后跟 `\n`。

两个 keys 必须精确，并按 canonical 顺序排列。`objective_value` 必须是一个有限实数
标量；`cost` 必须是一个有限、非负实数标量。整数值必须使用 `1.0` 这样的
canonical float 表示，不能使用 `1`。BOM、CR、缺失或额外 LF、whitespace、重复或
未知 key、metadata、prefix、suffix、NaN、Infinity、negative zero、负 cost 或其他
numeric encoding 都会被拒绝。`RunSpec.objective_name` 不会改变 stdout key。

使用 `json.dumps`，并设置 `ensure_ascii=False`、`allow_nan=False`、
`sort_keys=True` 和 `separators=(",", ":")`；随后通过 `sys.stdout.buffer` 写入
encoded bytes 和一个 `b"\n"`。

stderr 不是 observation 的一部分。成功时可以包含有界的 diagnostic bytes。非零
退出时，`CommandExitError.stderr_excerpt` 最多公开前 4096 bytes，并报告是否被
截断。不要把 secrets 写入 argv、stdout 或 stderr，也不要把这种 excerpt 行为视为
secret management。RDE 不会自动保护 API keys。

## Typed errors

- 无效 constructor fields 会直接引发 `TypeError` 或 `ValueError`。
- 普通 builder exception、错误的 builder result type，或无效的 rebuilt invocation
  会引发 `CommandBuildError`，并保留 cause。
- 普通 process-start 或 wait failure，以及作为 primary failure 的 temporary-output 或
  cleanup failure，会引发较宽泛的 `CommandAdapterError`。
- `Exception` hierarchy 之外的 execution-time `BaseException` 会在 best-effort cleanup
  后原样重新抛出。当另一个 failure 已在传播时，cleanup exception 会被抑制，因此不会
  替换原始 failure。
- timeout 会引发 `CommandTimeoutError`。它公开所配置的 timeout、direct child 是否
  已 reap，以及 descendant process-tree cleanup 不受保证这一事实。
- 非零 return code 会引发 `CommandExitError`，公开 `return_code`、有界 stderr
  excerpt 和 truncation flag。captured output 过大时，output-size rejection 优先。
- output failure 会引发 `CommandOutputError`。其当前 `reason` 值包括
  `oversized_stdout`、`oversized_stderr`、`encoding_violation`、`malformed_json`、
  `invalid_normalized_observation` 和 `output_io_failure`；它还公开适用的 stream 和
  byte counts。

builder 抛出的 `KeyboardInterrupt`、`SystemExit`、`GeneratorExit` 和
`Exception` hierarchy 之外的其他 `BaseException` subclasses 同样不会被包装。

## 可移植性与信任边界

为了兼容 Windows 和 Linux，Python child 应使用 `sys.executable`，每个参数使用一
个 tuple member，路径使用 `pathlib.Path`，并写入精确 bytes。避免 PowerShell、
`cmd.exe`、Bash、`/bin/sh`、shell-specific quoting 和 platform-specific paths。

`CommandAdapter` 使用当前用户账户的权限执行指定的本地程序。builder 和 command
均未被沙箱化或容器化。timeout handling 会尝试通过 bounded waits 终止、kill 和
reap direct child；descendant processes 的 cleanup 不受保证。API 不保证
process-tree、container、cluster、GPU 或 remote-worker 能力。

RunSpec 绑定声明的 adapter ID 和 version，不绑定 executable bytes、builder source、
继承的 environment、operating system、external files 或 child descendants。请在外部
固定这些输入，并在兼容性变化时更新声明的 version。启用 environment inheritance
时，child 可以读取当前 environment；适合最小显式 environment 时应将其禁用。

RunBundle replay 使用记录的 observations。它不会接收 builder 或 command，也不会
启动 child process。

## 完整跨平台可运行示例

安装 wheel 后，从一个新的空工作目录开始，将以下精确程序保存为
`command_adapter_example.py`，然后运行 `python command_adapter_example.py`。程序
会为本次 run 创建一个小型 Python child script，并通过 `sys.executable` 调用；它
不使用 shell。英文和中文指南有意使用完全相同的程序。

```python
import sys
from pathlib import Path

from research_decision_engine import (
    CandidateSpec,
    CommandAdapter,
    CommandInvocation,
    RunSpecV3,
    export_run_bundle_v3,
    replay_run_bundle_v3,
    run_workload_trace_v3,
    verify_run_bundle_v3,
)
from research_decision_engine.storage import ExperimentStore

CHILD_SOURCE = r"""from __future__ import annotations

import json
import sys
from pathlib import Path

value = float(sys.argv[1])
counter_path = Path(sys.argv[2])
if counter_path.exists():
    counter_text = counter_path.read_text(encoding="ascii")
    if not counter_text.endswith("\n") or not counter_text[:-1].isdigit():
        raise RuntimeError("command counter is malformed")
    count = int(counter_text[:-1])
else:
    count = 0
counter_path.write_text(f"{count + 1}\n", encoding="ascii", newline="\n")

objective_value = -(value - 2.0) ** 2
if objective_value == 0.0:
    objective_value = 0.0
observation = {
    "cost": 0.25,
    "objective_value": objective_value,
}
encoded = (
    json.dumps(
        observation,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    + b"\n"
)
sys.stdout.buffer.write(encoded)
sys.stdout.buffer.flush()
"""


def read_counter(path: Path) -> int:
    text = path.read_text(encoding="ascii")
    if not text.endswith("\n") or not text[:-1].isdigit():
        raise RuntimeError("command counter is malformed")
    return int(text[:-1])


working_directory = Path.cwd()
child_script = working_directory / "workload_child.py"
counter_file = working_directory / "command-count.txt"
child_script.write_text(CHILD_SOURCE, encoding="utf-8", newline="\n")

candidates = [
    CandidateSpec("point-1", {"x": 1.0}),
    CandidateSpec("point-2", {"x": 2.0}),
    CandidateSpec("point-3", {"x": 3.0}),
]


def build_command(candidate: CandidateSpec) -> CommandInvocation:
    parameters = candidate.parameters
    if set(parameters) != {"x"}:
        raise ValueError("candidate parameters must contain only x")
    value = parameters["x"]
    if type(value) not in (int, float):
        raise TypeError("x must be numeric")
    return CommandInvocation(
        argv=(
            sys.executable,
            str(child_script),
            repr(float(value)),
            str(counter_file),
        ),
        cwd=working_directory,
        environment_overrides={},
        inherit_environment=False,
        timeout_seconds=10.0,
        max_stdout_bytes=1024,
        max_stderr_bytes=1024,
    )


run_spec = RunSpecV3(
    candidates=candidates,
    policy_id="random",
    policy_config={},
    policy_seed=17,
    experiment_count_budget=2,
    cost_budget=1.0,
    adapter_id="guide.command",
    adapter_version="1",
    objective_name="score",
    objective_direction="maximize",
)
adapter = CommandAdapter(
    build_command,
    adapter_id=run_spec.adapter_id,
    adapter_version=run_spec.adapter_version,
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
assert len(history) == len(trace.steps) == read_counter(counter_file) == 2
for record in history:
    print(
        f"Observation {record.candidate.candidate_id}: "
        f"objective_value={record.observation.objective_value}, "
        f"cost={record.observation.cost}"
    )

bundle_directory = Path("run-bundle")
exported = export_run_bundle_v3(bundle_directory, trace=trace)
verified = verify_run_bundle_v3(bundle_directory)
assert exported.valid is True
assert verified.valid is True
assert verified.bundle_sha256 == exported.bundle_sha256

commands_before_replay = read_counter(counter_file)
replay_directory = Path("replay")
replay_directory.mkdir()
assert not any(replay_directory.iterdir())
replayed = replay_run_bundle_v3(bundle_directory, replay_directory)

assert read_counter(counter_file) == commands_before_replay
assert replayed.adapter_execution_count == 0
assert replayed.callable_execution_count == 0
assert replayed.command_execution_count == 0
assert replayed.equivalent is True
assert (replay_directory / "replay.sqlite3").is_file()

print(f"SQLite created: {database.is_file()}")
print(f"RunBundle verified: {verified.valid}")
print(f"Replay equivalent: {replayed.equivalent}")
print(f"Replay command executions: {replayed.command_execution_count}")
```

初始 run 会启动 child 两次，将两个 observations 持久化到 SQLite，并 export 和
verify RunBundle。replay 从显式为空的 `replay` 目录开始，重建新的 SQLite 状态，
必须保持外部 counter 不变，并报告 `Replay command executions: 0`。
