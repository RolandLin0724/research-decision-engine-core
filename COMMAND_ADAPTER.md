# Core CommandAdapter and versioned-policy CPU example

`CommandAdapter` evaluates one exact, truth-free `CandidateSpec` by starting one
trusted local direct child process. It is the subprocess counterpart to
`PythonFunctionAdapter`. The original `rde-core-run-spec/v1`,
`rde-core-run-bundle/v1`, `RECORDED_OBSERVATION_DECISION_REPLAY_V1`, and
random-only semantics remain byte-for-byte compatible. The parallel v2 RunSpec,
RunBundle, and replay contracts add exact `random` and `greedy_prior` policy
support without changing the adapter trust model. The parallel v3 contracts add
`information_gain_table` alongside those two policies without changing command
construction, process execution, normalized stdout, timeout, or error semantics.

The stable package-root imports are:

```python
from research_decision_engine import (
    CommandAdapter,
    CommandAdapterError,
    CommandBuildError,
    CommandExitError,
    CommandInvocation,
    CommandOutputError,
    CommandTimeoutError,
    resume_workload_trace,
)
```

## Invocation and builder contract

`CommandInvocation` is an immutable value with these semantic fields:

- `argv: tuple[str, ...]`
- `cwd: pathlib.Path | None`
- `environment_overrides: Mapping[str, str]`
- `inherit_environment: bool`
- `timeout_seconds: float`
- `max_stdout_bytes: int`
- `max_stderr_bytes: int`

The argv is already split. The adapter never parses a command string, interprets
quotes or shell grammar, or exposes a shell-mode option. The executable is
nonempty, every argv and environment string is NUL-free, the optional cwd is an
existing directory, the timeout is finite and positive, and both output limits
are positive integers. Mutable environment input is copied and frozen; its values
are excluded from the invocation representation and from default error text.

The trusted in-process command builder receives only the exact public
`CandidateSpec`, is called once, and must return an exact `CommandInvocation`.
Ordinary builder failures become `CommandBuildError` with the original exception
as `__cause__`. `KeyboardInterrupt`, `SystemExit`, `GeneratorExit`, and other
`BaseException` subclasses are not swallowed. Adapter ID and version are explicit
user declarations; callable representation, source path, and object address are
not identity.

## Direct-process and output contract

The execution model is `TRUSTED_LOCAL_DIRECT_CHILD_PROCESS_V1`. The adapter uses
`shell=False`, redirects stdout and stderr to task-owned regular files in a
validated system temporary directory outside the containing repository, waits
for the explicit timeout, and creates no retry. It checks file sizes before
reading exact bytes and attempts cleanup on every success and failure path;
ordinary cleanup failures are typed adapter errors and do not replace a timeout
error already in flight.

Direct child timeout handling: `SUPPORTED`.

On timeout the adapter terminates the direct child, waits for a bounded grace
period, kills it if needed, and makes one bounded reap attempt. The timeout error
records whether the direct child was reaped. Descendant process-tree cleanup:
`NOT_GUARANTEED_IN_COMMAND_ADAPTER_V1`. This is not a sandbox and does not make an
untrusted or malicious command safe.

Successful stdout is exactly the canonical UTF-8 form of the current public
normalized-observation schema, with one final LF:

```json
{"cost":0.25,"objective_value":1.5}
```

There is no BOM, CR, prefix, suffix, duplicate or unknown field, hidden truth,
NaN, Infinity, extra whitespace, or alternative numeric encoding. Diagnostics
belong on stderr; bounded stderr may be empty or nonempty on success. The adapter
never searches arbitrary log text for an embedded JSON object.

`CommandAdapterError` is the stable broad boundary. `CommandBuildError` identifies
builder failure; `CommandTimeoutError` exposes the timeout, direct-child reap
result, and the false process-tree guarantee; `CommandExitError` exposes the
return code and an explicitly bounded stderr excerpt; and `CommandOutputError`
exposes a stable reason plus stream and byte-count metadata. No error dumps the
inherited environment or returns a partial observation.

Environment inheritance is explicit. With `inherit_environment=True`, a copied
current environment is overlaid by the invocation overrides. With `False`, the
child receives only those overrides. RunSpec binds the adapter ID and version but
does not bind executable bytes, builder source, inherited environment, OS image,
external data, or the command's descendants. Those remain reproducibility limits.

## Command Adapter Compression Tuning

The offline example under `examples/command_adapter_compression` compresses and
decompresses a fixed project-authored corpus with exactly 24 candidates:

- codec: `gzip`, `bz2`, `lzma`
- level: `1`, `3`, `6`, `9`
- chunk mode: `single_stream`, `fixed_64_kib_members`

It maximizes `compression_ratio = corpus_bytes / compressed_bytes`, proves exact
round-trip equality, fixes gzip `mtime=0`, and reports a deterministic documented
CPU-work proxy rather than wall-clock duration. The original v1 compatibility run
remains `random` with seed `1729`, empty configuration, and unchanged fixtures.

The v2 comparison runs the same exact 24 candidates under `random` and
`greedy_prior`, each with an experiment budget of eight and interruption after
four completed steps. V2 random uses seed `20260804`. `greedy_prior` has no seed
and uses this complete project-authored prior utility, computed only from candidate
parameters before workload execution:

```text
codec_base: gzip=1000, bz2=2000, lzma=3000
level_component: level * 10
chunk_component: single_stream=1, fixed_64_kib_members=0
prior_utility: codec_base + level_component + chunk_component
```

Thus gzip level 1 fixed is `1010`, gzip level 1 single is `1011`, and lzma level
9 single is `3091`. All 24 values are present and unique. They remain fixed after
observations arrive. This is a truth-free heuristic prior, not hidden corpus
truth, a learned score, or a claim that compression ratio is predicted accurately.

The v3 comparison reuses the exact corpus, 24 candidates, budgets, workload, and
adapter. Its `random` and `greedy_prior` policies retain their v2 selection
semantics. `information_gain_table` uses one fixed project-authored
`FiniteTableEvidenceModel` declared before execution:

```text
hypotheses: gzip_dominant, bz2_dominant, lzma_dominant
prior weights: 1, 1, 1
observation metric: compression_ratio
outcomes: low, medium, high
thresholds: 2.0, 3.0
likelihood row total: 20
matching-codec row: 1, 5, 14
nonmatching-codec row: 10, 7, 3
tie break: runspec_candidate_order
```

The complete candidate x hypothesis x outcome table is embedded in RunSpec v3
and never learned or changed from observations. It is a heuristic compression
demonstration model, not hidden corpus truth or a scientific calibration. The
policy ranks candidates by expected Shannon information gain under this declared
model, not by predicted compression quality.

The caller supplies an empty output directory:

```console
uv run python -B examples/command_adapter_compression/run_example.py --output-dir <directory>
uv run python -B examples/command_adapter_compression/run_v2_example.py --policy random --output-dir <random-v2-directory>
uv run python -B examples/command_adapter_compression/run_v2_example.py --policy greedy_prior --output-dir <greedy-v2-directory>
uv run python -B examples/command_adapter_compression/run_v3_example.py --policy random --output-dir <random-v3-directory>
uv run python -B examples/command_adapter_compression/run_v3_example.py --policy greedy_prior --output-dir <greedy-v3-directory>
uv run python -B examples/command_adapter_compression/run_v3_example.py --policy information_gain_table --output-dir <information-gain-v3-directory>
```

Each v2 policy uses a separate SQLite run. The lifecycle executes four steps,
closes every RDE and SQLite object, reopens, checks the exact RunSpec v2
fingerprint and policy configuration, then completes four more steps. Resume
validates the persisted prefix before any new adapter evaluation; a different
utility map, candidate order, policy, or fingerprint fails before command
execution. Each completed trace is exported as RunBundle v2, verified, and
replayed into a separate empty directory. Replay injects recorded observations
and never receives or invokes the adapter, builder, or external command. The
example reopens replay SQLite and compares selection order, decisions, rationales,
observations, cumulative costs, belief lineage, terminal summary, and section
hashes. Command counters remain unchanged across both replays.

Each v3 policy likewise uses a separate SQLite schema-6 run. The lifecycle
executes four steps, closes and reopens every RDE and SQLite object, verifies the
exact RunSpec v3 fingerprint and policy configuration, and completes four more
steps. No migration is required: the fingerprint binds the complete finite model
and the existing workload rows preserve the ordered normalized observations
needed to reconstruct exact belief state.

Each eight-step trace is exported as RunBundle v3, verified read-only, and
replayed into a separate empty directory. V3 replay uses a finite static policy
factory and receives no adapter, builder, executable, callable, module path, or
registry. It recomputes decision and rationale payloads for all three policies;
for information gain it also recomputes threshold classification, exact integer
weight multiplication and GCD reduction, Decimal-50 scores quantized to `1e-30`,
fixed 30-place score text, model and belief fingerprints, and every lineage
entry. Adapter, callable, reported command, and external command-counter
execution counts are all zero during replay.

Running the script with a clean environment whose Python contains only the built
wheel exercises the installed public API; the script and fixed corpus remain
ordinary example inputs and no file is written into site-packages.

The three-policy output is descriptive. It does not claim that any policy is
generally superior, predict future outcomes, validate the user-declared model, or
establish cross-platform CI passage. The v3 bridge demonstrates product
integration, not scientific superiority. The example does not make Core v1
release-ready or create Assurance approval, and v1/v2 artifacts and behavior
remain unchanged.
