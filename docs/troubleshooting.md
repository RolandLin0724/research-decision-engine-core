# Troubleshooting

English | [简体中文](zh-CN/troubleshooting.md)

This guide diagnoses the supported RDE Core v1 surface without weakening its
fail-closed contracts. Preserve the original database, RunBundle, exception, and
sanitized diagnostic context before trying a fresh disposable reproduction. Do not
change implementation files, schemas, hashes, or artifact members to make a failure
disappear.

## Python and installation

### Confirm the toolchain

RDE Core's frozen interpreter contract is CPython 3.12 (`>=3.12,<3.13`). Confirm the
interpreter and `uv` before diagnosing the package:

```console
python --version
uv --version
```

A different Python minor version is outside the current contract. No PyPI
publication is claimed or authorized by this pre-release documentation, so use the
authorized private source checkout rather than an unrelated `pip install rde` or
similarly named package. Use the repository's committed lockfile from its root:

```console
git status --short
git diff -- pyproject.toml uv.lock
uv sync --locked
```

If `uv sync --locked` fails, first confirm that you are in the intended checkout,
that Python is 3.12, that `uv --version` works, and that `pyproject.toml` and
`uv.lock` have not been locally changed. Then check the first reported filesystem,
cache, network, or package-resolution error. Do not regenerate or edit `uv.lock`,
remove constraints, or switch to an unlocked sync merely to suppress the failure.

### Confirm what is actually imported

Source-checkout and installed-wheel confusion can look like an API failure. Run the
following with the same interpreter that runs the failing program:

```console
uv run --locked python -c "import research_decision_engine as rde; print(rde.__version__); print(rde.__file__)"
uv run --locked python -c "from importlib.metadata import version; print(version('research-decision-engine'))"
uv run --locked rde --help
```

The printed module path identifies the loaded module location. The distribution
version and module path answer different questions; record both. Outside a source
checkout, use the installed environment's `python` and `rde` rather than adding a
project-only `uv run --locked` wrapper.

## Import and public API errors

Only imports listed in the frozen public API manifest are stable through the RDE
1.x compatibility line. The manifest includes package-root imports and the explicit
`research_decision_engine.storage.ExperimentStore` and
`research_decision_engine.storage.SCHEMA_VERSION` imports. A helper inside another
module may happen to be importable without being public.

For an `ImportError` or missing symbol:

1. record the exact import statement and public error;
2. confirm the loaded module path and distribution version as shown above;
3. compare the import with the [Core v1 compatibility contract](../CORE_V1_COMPATIBILITY.md)
   and public manifest;
4. check for a local file or directory named `research_decision_engine` that could
   shadow the installed package;
5. reproduce from a clean installed wheel before concluding that the public symbol
   is missing.

Do not work around a missing public import by importing a private normalization,
filesystem, policy-factory, or decoding helper.

## SQLite database problems

The latest and new-database schema is v6. Known legacy schemas v1 through v5 are
migrated one version at a time. Each migration edge has its own atomic transaction;
after an interrupted edge rolls back, a later `init_schema()` call can resume from
the last committed version.

This does not mean that every damaged database is repairable. A negative or unknown
future `PRAGMA user_version`, a declared version whose schema objects do not match,
noncanonical tables or triggers, failed integrity checks, and foreign-key failures
are rejected. Automatic downgrade is not supported.

If a database cannot be opened or initialized:

1. stop writing to it and make a byte-for-byte backup before further inspection;
2. preserve the original exception and reported schema version;
3. do not edit `PRAGMA user_version`, delete tables, recreate triggers, or manually
   patch schema SQL;
4. in a new disposable directory, initialize a new database with
   `ExperimentStore(Path("diagnostic.sqlite3"))`, call `init_schema()`, and confirm
   `schema_version() == SCHEMA_VERSION == 6`;
5. if the disposable database succeeds, investigate the preserved legacy database;
   if it fails too, investigate the interpreter, installation, filesystem, and
   permissions instead.

Keep the disposable database separate from real history. Successful initialization
of a fresh database does not validate or repair the original one.

## RunSpec validation problems

First match schema, policy, and seed exactly:

| RunSpec | Supported policies | Seed rule |
| --- | --- | --- |
| v1 | `random` | signed 64-bit integer |
| v2 | `random`, `greedy_prior` | signed 64-bit integer for `random`; `None` for `greedy_prior` |
| v3 | `random`, `greedy_prior`, `information_gain_table` | signed 64-bit integer for `random`; `None` for deterministic policies |

Public policy lookup uses `UnsupportedRunSpecSchemaError`,
`UnsupportedPolicyIdentityError`, and `UnsupportedPolicyForSchemaError` for closed
schema/policy failures. For v2/v3 validation, a random seed with the wrong type or
range uses `PolicyConfigurationError`; a non-`None` seed on a deterministic policy
uses `DeterministicPolicySeedError`; and an explicitly invalid top-level tie-break,
or a missing/invalid deterministic-policy configuration tie-break, uses
`InvalidPolicyTieBreakError`. A missing top-level field in canonical bytes is an
ordinary `ValueError`. Codec behavior is version-specific: v2/v3 wrong-schema bytes
use `RunSpecVersionMismatchError`, while the v1 decoder reports its wrong-schema,
policy, or tie-break cases as ordinary `ValueError`.

For `greedy_prior`, `utility_by_candidate_id` must name every candidate exactly
once. `MissingCandidateUtilityError`, `ExtraCandidateUtilityError`,
`InvalidCandidateUtilityError`, and `NonfiniteUtilityError` distinguish missing,
extra, invalid, and nonfinite values. Observations do not update this static map.

For `information_gain_table`, validate the complete user-declared
`FiniteTableEvidenceModel`: hypothesis and outcome identities, positive prior
weights, strictly ordered thresholds, the objective-matching observation metric,
candidate/hypothesis/outcome keys, nonnegative integer likelihood weights, and the
exact likelihood row total. Public `EvidenceModelError`,
`InformationGainContractError`, and their manifest-listed leaf errors report these
failures. Core does not learn or repair the likelihood table.

All RunSpec decoders reject unknown, missing, duplicate, or wrong-version fields and
noncanonical bytes. Candidate ordering is identity-bearing: reordering candidates
changes canonical bytes and the fingerprint and can change tie-breaking or seeded
selection. See the [RunSpec guide](run-spec.md) for the complete contract.

## Adapter problems

### PythonFunctionAdapter

An ordinary exception raised by the callable or its explicit normalizer becomes
`WorkloadAdapterError` with the original exception as `__cause__`. A return that is
not an exact `NormalizedObservation`, or whose objective value or cost is invalid,
also raises `WorkloadAdapterError`.

The adapter supplies no timeout, retry, subprocess, sandbox, or isolation. Make the
callable deterministic by passing inputs and seeds explicitly and avoiding current
time, hidden global state, undeclared files, and mutable external state. Replay uses
the recorded observation and never invokes the callable again. See the
[PythonFunctionAdapter guide](python-function-adapter.md).

### CommandAdapter

Use the public error type to locate the boundary:

| Error | Meaning |
| --- | --- |
| `CommandBuildError` | the builder raised, returned the wrong type, or produced an invalid invocation |
| `CommandExitError` | the direct child returned a nonzero exit code |
| `CommandTimeoutError` | the direct child exceeded `timeout_seconds`; descendant cleanup is not guaranteed |
| `CommandOutputError` | stdout/stderr size, UTF-8, canonical JSON, normalized-observation, or output-I/O failure |
| `CommandAdapterError` | an ordinary process-start/wait failure, or a primary temporary-output/cleanup failure |

An execution-time `BaseException` outside the `Exception` hierarchy is re-raised
unchanged after best-effort cleanup. Cleanup errors are suppressed while a different
failure is already propagating, so they do not replace the original diagnostic.

`argv` is an explicit nonempty tuple with one already-separated argument per member.
Execution always uses `shell=False`; shell quoting and metacharacters are not
interpreted. For a portable Python child, use `sys.executable` and avoid
PowerShell-, `cmd.exe`-, Bash-, or `/bin/sh`-specific quoting. The configured stdout
and stderr sizes are rejection thresholds checked after exit, not live stream or
disk caps. A successful stdout is exactly one canonical UTF-8 observation object
and one LF.

Replay receives neither the builder nor the invocation and never starts the
command. See the [CommandAdapter guide](command-adapter.md).

## RunBundle export problems

The destination must be a `pathlib.Path` instance whose parent already exists as an
ordinary directory. The destination must not exist in any form. Check parent write
permissions and available space without changing the artifact contract.

Export rejects symlink, junction, or reparse ancestry, non-directory parents,
destination races, replaced physical identities, aliases, and unexpected link
counts. Do not bypass these checks, resolve through an alternate linked path, or
pre-create the destination. `RunBundleValidationError`,
`RunBundleV2ValidationError`, or `RunBundleV3ValidationError` reports the matching
version's validation boundary.

Export writes and verifies a temporary sibling, then publishes without replacing an
existing destination and verifies the published artifact. Windows binds directory
handles and physical identities; Linux uses an atomic exclusive no-replace rename.
These are the currently supported platform contracts, not a generic macOS or POSIX
guarantee and not a promise against every same-account namespace race or crash.

If export fails, preserve the original trace and exception, remove only disposable
task-owned failed output after confirming its identity, choose a new unused
destination, and retry from the trusted trace. See the [RunBundle guide](run-bundle.md).

## Verify failures

Verification fails closed for, among other conditions:

- a missing, malformed, or mismatched 65-byte SHA-256 sidecar;
- malformed or noncanonical JSON, unknown fields, or an unsupported schema;
- RunSpec fingerprint or version binding mismatch;
- RunSpec, steps, or terminal-summary section hash mismatch;
- inconsistent candidate, decision, rationale, observation, cost, belief, or
  terminal semantics;
- an added, removed, renamed, multiply linked, or non-regular member;
- a changed root/member physical identity, or symlink, junction, reparse, or
  ancestor substitution.

Physical inventory, stable-read, and sidecar failures use
`RunBundleVerificationError`, `RunBundleV2VerificationError`, or
`RunBundleV3VerificationError`. V1/v2 also wrap decoded canonical/schema failures in
their verification errors; v3 preserves `RunBundleV3ValidationError` for those
decoded validation failures. Version and semantic mismatches may expose their
separate public error families.

Do not edit the original bundle, replace hashes, delete the sidecar and continue, or
weaken identity and ancestry checks. Preserve the failed bundle as evidence, keep it
out of replay, and export a new bundle from a trusted recorded run. A tampered bundle
must remain rejected.

## Replay problems

Use the replay function that exactly matches the v1, v2, or v3 bundle. The
destination must be either a nonexistent child of an existing plain parent or an
existing plain, completely empty directory. Replay never merges with existing
state.

`RunBundleReplayError`, `RunBundleV2ReplayError`, and `RunBundleV3ReplayError` cover
their general destination, persistence, integrity, and terminal failures. A
wrong-version replay input is wrapped in the matching versioned replay error; direct
v2/v3 verification may instead expose `RunBundleVersionMismatchError`. V1 also wraps
an unavailable policy or decision/rationale mismatch in `RunBundleReplayError`.
V2 directly exposes `ReplayPolicyUnavailableError`, `ReplayDecisionMismatchError`,
and `ReplayRationaleMismatchError`. V3 directly exposes those errors and can also
raise `ReplayBeliefMismatchError` or `ReplayInformationGainScoreMismatchError`.

Replay consumes verified recorded observations. It does not invoke a Python
callable, adapter, command builder, command, plugin, or external workload. It is not
a container or environment reconstruction and does not prove that today's external
workload would produce the same observation. See the [replay guide](replay.md).

## Privacy and secrets

RDE Core does not automatically protect secrets available to a user-supplied
callable or command. Do not place secret values in candidate parameters or metadata,
a RunSpec, stdout observation, RunBundle, error log, diagnostic reproduction, or
example. Do not upload a real API key or token to an issue.

Passing a secret through an environment variable does not guarantee that child
output, error handling, process inspection, or surrounding logs are safe. Users are
responsible for secret creation, access, rotation, lifetime, and revocation. Replay
does not need the original workload secret because it consumes recorded
observations. RDE Core is not a secret manager.

<a id="getting-useful-diagnostic-information"></a>

## Getting useful diagnostic information

A useful sanitized report can include:

- Python version and operating system;
- package version and whether execution used a source checkout or installed wheel;
- the public error class and a minimal sanitized reproduction;
- SQLite schema/version identifier, RunSpec schema, RunBundle schema, and policy ID;
- whether the failure occurred during construction, execution, export, verify, or
  replay;
- for verify/replay, the failing step category without private artifact content.

Do not provide an API key, token, private database, private RunBundle, unredacted
local path, private CI log, personal email address, or other secret-bearing content.
Keep the original private evidence locally and share only the minimum redacted facts
needed to reproduce the public contract failure.

## Related guides

- [FAQ](faq.md)
- [PythonFunctionAdapter guide](python-function-adapter.md)
- [CommandAdapter guide](command-adapter.md)
- [RunSpec guide](run-spec.md)
- [RunBundle guide](run-bundle.md)
- [Replay guide](replay.md)
