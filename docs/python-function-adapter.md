# PythonFunctionAdapter guide

English | [简体中文](zh-CN/python-function-adapter.md)

`PythonFunctionAdapter` connects an existing Python callable to the bounded RDE
Core experiment loop. Use it when the workload is trusted Python code that can run
locally in the current process, the experiment candidates are finite, and each
callable result can be normalized to one RDE observation.

## Public imports

The frozen public imports used by this guide are:

```text
from research_decision_engine import CandidateSpec, NormalizedObservation, PythonFunctionAdapter, WorkloadAdapterError
from research_decision_engine.storage import ExperimentStore
```

The runnable example also imports the public v3 run, bundle, verification, and
replay functions from the package root.

## Exact callable contract

The public constructor and evaluation signatures are:

```text
PythonFunctionAdapter(
    function: Callable[[CandidateSpec], object],
    *,
    adapter_id: str,
    adapter_version: str,
    normalizer: Callable[[object], NormalizedObservation] | None = None,
)

adapter.evaluate(candidate: CandidateSpec) -> NormalizedObservation
```

`function` receives exactly one exact `CandidateSpec`. Its `candidate_id` is the
declared nonempty candidate identity. Its `parameters` property is a detached
mapping containing the canonical JSON-compatible parameters supplied when the
candidate was constructed. Those parameters are how candidate-specific values
enter the callable; the adapter does not add hidden truth, an execution context,
or other arguments.

The callable is invoked once for each evaluation. With no `normalizer`, it must
return an exact `NormalizedObservation`. With a `normalizer`, the callable may
return another object and the adapter invokes the explicit normalizer once; the
normalizer must return an exact `NormalizedObservation`. There is no implicit
conversion from a number, mapping, or tuple.

`NormalizedObservation` supports exactly these observation values:

- `objective_value`: an exact built-in `int` or `float`, excluding `bool` and
  coercible or non-built-in numeric objects; an integer input must fit the signed
  64-bit range, the value must be finite, and it is normalized to `float`;
- `cost`: the same exact numeric input types and integer bound, finite and
  nonnegative, normalized to `float`, and defaulting to `0.0` when omitted.

The adapter revalidates both fields and returns a fresh exact observation. The
observation has no metadata field and no arbitrary metrics map. `objective_name`
and `objective_direction` belong to the `RunSpec`; they do not add fields to an
adapter result. If a workload produces a richer object, an explicit normalizer can
select one objective and one cost, but it cannot attach extra observation metadata.

The adapter ID and version are explicit caller declarations. They must match the
corresponding `RunSpec` values. They are not inferred from the function name,
source path, representation, or memory address.

## Errors and execution behavior

- A non-callable function or normalizer, an invalid adapter identity, or a
  non-exact `CandidateSpec` fails with `TypeError` or `ValueError` before workload
  execution as applicable.
- An ordinary `Exception` raised by the callable or normalizer is converted to
  `WorkloadAdapterError`, with the original exception retained as `__cause__`.
- A result that is not an exact `NormalizedObservation`, or one that fails field
  revalidation, raises `WorkloadAdapterError`.
- `KeyboardInterrupt`, `SystemExit`, `GeneratorExit`, and other `BaseException`
  subclasses outside the `Exception` hierarchy are not wrapped.
- Each call to `evaluate` performs one attempt. The adapter provides no automatic
  retry, timeout, subprocess boundary, or recovery policy.

## Determinism and trust boundary

Pass every workload input through the candidate parameters, use an explicit seed
for any stochastic workload, and avoid current time and hidden global state. Do not
put temporary absolute paths, memory addresses, or unstable object
representations in returned values. Keep the callable and its declared adapter
version aligned so a version change reflects a meaningful workload compatibility
change.

`PythonFunctionAdapter` executes user-provided Python in the current Python
process. It is not a malicious-code sandbox. The callable has every permission and
capability available to that process and can mutate process or filesystem state.
Only use trusted code.

RunBundle replay is recorded-observation decision replay. It receives no callable
and does not invoke the adapter or workload again.

## Complete runnable example

Install the wheel, start in a new empty working directory, save this exact program
as `python_adapter_example.py`, and run `python python_adapter_example.py`. The
English and Chinese guides intentionally contain the same program.

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

call_count = 0


def score(candidate: CandidateSpec) -> NormalizedObservation:
    global call_count
    call_count += 1
    value = candidate.parameters["x"]
    if type(value) not in (int, float):
        raise TypeError("x must be numeric")
    x = float(value)
    return NormalizedObservation(
        objective_value=-(x - 2.0) ** 2,
        cost=0.25,
    )


candidates = [
    CandidateSpec("point-1", {"x": 1.0}),
    CandidateSpec("point-2", {"x": 2.0}),
    CandidateSpec("point-3", {"x": 3.0}),
]

run_spec = RunSpecV3(
    candidates=candidates,
    policy_id="random",
    policy_config={},
    policy_seed=17,
    experiment_count_budget=2,
    cost_budget=1.0,
    adapter_id="guide.python-function",
    adapter_version="1",
    objective_name="score",
    objective_direction="maximize",
)
adapter = PythonFunctionAdapter(
    score,
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
assert len(history) == len(trace.steps) == call_count == 2
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

calls_before_replay = call_count
replay_directory = Path("replay")
replay_directory.mkdir()
assert not any(replay_directory.iterdir())
replayed = replay_run_bundle_v3(bundle_directory, replay_directory)

assert call_count == calls_before_replay
assert replayed.adapter_execution_count == 0
assert replayed.callable_execution_count == 0
assert replayed.command_execution_count == 0
assert replayed.equivalent is True
assert (replay_directory / "replay.sqlite3").is_file()

print(f"SQLite created: {database.is_file()}")
print(f"RunBundle verified: {verified.valid}")
print(f"Replay equivalent: {replayed.equivalent}")
print(f"Replay callable executions: {replayed.callable_execution_count}")
```

The initial run executes two of the three candidates and prints both persisted
observations. Export creates a two-file RunBundle, verification must report
`True`, and replay writes fresh SQLite state in the previously empty `replay`
directory. The final callable execution count must be `0` for replay.
