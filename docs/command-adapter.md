# CommandAdapter guide

English | [简体中文](zh-CN/command-adapter.md)

`CommandAdapter` connects a trusted local executable to the bounded RDE Core
experiment loop. Use it for a Python child process, compiled program, or scientific
command-line tool when one explicit invocation can turn a finite candidate into
the current normalized observation on stdout.

## Public imports

The frozen public imports for the adapter and its typed errors are:

```text
from research_decision_engine import CommandAdapter, CommandAdapterError, CommandBuildError, CommandExitError, CommandInvocation, CommandOutputError, CommandTimeoutError
```

The runnable example also uses `CandidateSpec`, the public v3 run and RunBundle
functions from the package root, and
`research_decision_engine.storage.ExperimentStore`.

The current `rde` CLI has no CommandAdapter configuration command. Construct and
run this adapter through the Python API.

## Exact builder and invocation contract

The public signatures are:

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

Every `CommandInvocation` argument is required; there are no public defaults. The
trusted in-process builder receives one exact `CandidateSpec`, is called once, and
must return one exact `CommandInvocation`. The adapter does not expand candidate
fields automatically. The unrestricted trusted builder explicitly reads
`candidate.candidate_id` and/or `candidate.parameters` and constructs any
invocation field; the example validates `x` and places it in `argv`.

The invocation fields have these boundaries:

- `argv` is a nonempty exact tuple of strings. The executable is `argv[0]`, and
  each later tuple member is one already-separated argument. Empty executable
  names and NUL characters are rejected.
- `cwd` is an existing `pathlib.Path` or `None`; it is checked again before the
  child starts.
- `environment_overrides` contains only string keys and values and is copied into
  an immutable invocation. With `inherit_environment=True`, the current
  environment is copied and then overlaid. With `False`, the child receives only
  the overrides. On Windows, each override first removes inherited keys that match
  it under `casefold()`; on Linux, differently cased environment keys remain
  distinct.
- `timeout_seconds` is finite and strictly positive. `max_stdout_bytes` and
  `max_stderr_bytes` are strictly positive exact integers.

There is no public shell, stdin, encoding, retry, process-tree, container, or
remote-worker option. Stdout encoding is fixed by the observation contract below;
stderr remains bytes.

## Direct execution: `shell=False`

The adapter passes the tuple directly to a local child process with:

```text
shell=False
stdin=subprocess.DEVNULL
```

Do not pass an entire shell command as one string, and do not embed shell quoting.
For example, use `(sys.executable, "workload.py", "--level", "3")`, not
`("python workload.py --level 3",)`. Shell metacharacters have no special meaning;
they are argument data.

Stdout and stderr are redirected to task-owned regular files outside the
repository. After the child exits, their byte sizes are checked before their
contents are read. The configured sizes are rejection thresholds, not live stream
or disk-usage caps. The adapter performs no automatic retry.

## Exact stdout observation

A successful child must write exactly one canonical UTF-8 JSON object followed by
one LF. For example, the complete stdout bytes are the UTF-8 encoding of:

```json
{"cost":0.25,"objective_value":1.5}
```

followed by `\n`.

The two keys are exact and in canonical sorted order. `objective_value` must be one
finite real scalar; `cost` must be one finite, nonnegative real scalar. Integral
values must use canonical float spelling such as `1.0`, not `1`. A BOM, CR,
missing or extra LF, whitespace, duplicate or unknown key, metadata, prefix,
suffix, NaN, Infinity, negative zero, negative cost, or alternative numeric
encoding is rejected.
The `RunSpec.objective_name` does not change the stdout key.

Use `json.dumps` with `ensure_ascii=False`, `allow_nan=False`, `sort_keys=True`,
and `separators=(",", ":")`, then write the encoded bytes and one `b"\n"` through
`sys.stdout.buffer`.

Stderr is not part of the observation. It may contain bounded diagnostic bytes on
success. On a nonzero exit, `CommandExitError.stderr_excerpt` exposes at most the
first 4096 bytes and reports whether it was truncated. Do not write secrets to
argv, stdout, or stderr, and do not treat this excerpt behavior as secret
management. RDE does not automatically protect API keys.

## Typed errors

- Invalid constructor fields raise `TypeError` or `ValueError` directly.
- An ordinary builder exception, a wrong builder result type, or an invalid
  rebuilt invocation raises `CommandBuildError` with the cause preserved.
- An ordinary process-start or wait failure, or a temporary-output or cleanup
  failure when it is the primary failure, raises the broad `CommandAdapterError`.
- An execution-time `BaseException` outside the `Exception` hierarchy is re-raised
  unchanged after best-effort cleanup. A cleanup exception is suppressed while a
  different failure is already propagating, so it does not replace the original.
- A timeout raises `CommandTimeoutError`. It exposes the configured timeout,
  whether the direct child was reaped, and the fact that descendant process-tree
  cleanup is not guaranteed.
- A nonzero return code raises `CommandExitError`, exposing `return_code`, the
  bounded stderr excerpt, and its truncation flag. Output-size rejection takes
  precedence when captured output is oversized.
- Output failures raise `CommandOutputError`. Its current `reason` values are
  `oversized_stdout`, `oversized_stderr`, `encoding_violation`, `malformed_json`,
  `invalid_normalized_observation`, and `output_io_failure`; it also exposes the
  applicable stream and byte counts.

`KeyboardInterrupt`, `SystemExit`, `GeneratorExit`, and other `BaseException`
subclasses outside the `Exception` hierarchy from the builder are also not wrapped.

## Portability and trust boundary

For Windows and Linux portability, use `sys.executable` for a Python child, one
tuple member per argument, `pathlib.Path`, and exact byte output. Avoid PowerShell,
`cmd.exe`, Bash, `/bin/sh`, shell-specific quoting, and platform-specific paths.

`CommandAdapter` executes the specified local program with the permissions of the
current user account. Neither the builder nor the command is sandboxed or
containerized. Timeout handling attempts to terminate, kill, and reap the direct
child with bounded waits; cleanup of descendant processes is not guaranteed. The
API makes no process-tree, container, cluster, GPU, or remote-worker guarantee.

RunSpec binds the declared adapter ID and version, not the executable bytes,
builder source, inherited environment, operating system, external files, or child
descendants. Pin those inputs externally and update the declared version when
compatibility changes. With environment inheritance enabled, the child can read
the current environment; disable it when a minimal explicit environment is
appropriate.

RunBundle replay uses recorded observations. It receives no builder or command and
does not start a child process.

## Complete cross-platform runnable example

Install the wheel, start in a new empty working directory, save this exact program
as `command_adapter_example.py`, and run `python command_adapter_example.py`. It
creates a small Python child script for this run and invokes it through
`sys.executable`; it does not use a shell. The English and Chinese guides
intentionally contain the same program.

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

The initial run starts the child twice, persists two observations in SQLite, and
exports and verifies the RunBundle. Replay starts from the explicitly empty
`replay` directory, reconstructs fresh SQLite state, and must leave the external
counter unchanged while reporting `Replay command executions: 0`.
