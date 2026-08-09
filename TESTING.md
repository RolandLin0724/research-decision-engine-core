# Testing RDE Core v1

The frozen RDE 1.x public-import, artifact-version, and SQLite migration policies
are defined in `CORE_V1_COMPATIBILITY.md`; the canonical machine-readable import
surface is `research_decision_engine/core-public-api-v1.json`.

The default test gate from the repository root is:

```console
uv sync --frozen
uv run python -m pytest
```

The isolated baseline established 83 tests. The RunSpec/adapter vertical slice
preserved every one of those node IDs and established the 123-test opening baseline
for the RunBundle work. The focused RunBundle export, integrity, and
empty-directory replay tests now extend that Core gate.
The CommandAdapter and original random CPU slice established the 327-node opening
baseline for policy versioning. The v2 work preserved those nodes and established
the 381-node opening baseline for v3. The v3 work preserved those nodes, and the
later focused suites and SQLite atomicity repair established the 541-node opening
baseline for this compatibility and CI slice. This slice must preserve all 541
opening node IDs and add focused tests without skip, xfail, or silent manifest
removal.
The exact positive list of test modules is tracked in `tests/core_v1_pytest.txt`;
`pyproject.toml` passes that manifest to pytest and disables repository
`conftest.py` loading. The gate covers the deterministic worlds and ordinary
policies, local runner and CLI workflows, SQLite storage and migrations, the
truth-free RunSpec/adapter path, evidence and belief updates, decision rationale,
information gain, fixed lookahead, robust belief/calibration behavior, and ordinary
persistence and reopen behavior. `tests/test_run_bundle.py` covers the canonical
two-file artifact, export, verification, and tamper rejection;
`tests/test_run_bundle_replay.py` covers decision-process replay into fresh SQLite
state without invoking the workload callable.
`tests/test_command_invocation.py` and `tests/test_command_adapter.py` cover the
immutable no-shell invocation, direct-child process, strict stdout, bounded stderr,
environment, typed-error, timeout, termination, kill, and reap contracts.
`tests/test_workload_resume.py` covers fingerprint-bound reconstruction of a
persisted prefix without weakening the existing empty-history trace API.
`tests/test_command_adapter_compression_example.py` covers the fixed corpus,
exact 24-candidate space, deterministic codec round trips, explicit random seed,
four-step interruption, eight-step completion, RunBundle verification, and zero
command execution during empty-directory replay.
`tests/test_v1_policy_golden.py` freezes representative RunSpec v1 canonical bytes
and fingerprint, RunBundle v1 document and section hashes, the 65-byte sidecar,
and continued v1 rejection of `greedy` and `greedy_prior`. The v2 policy tests
cover exact schema separation, random and prior-greedy configuration, complete
finite utility maps, caller-mutation isolation, RunSpec-order tie resolution,
completed-candidate exclusion, deterministic rationale, and candidate-space
exhaustion. V2 RunBundle tests cover strict same-version binding, both static
policy identities, decision/rationale equivalence, tamper rejection, and zero
adapter or command execution during replay.

The v3-focused modules cover the complete new contract:

- `tests/test_finite_table_evidence_model.py` covers the exact seven-field model,
  closed candidate/hypothesis/outcome tables, threshold classification,
  immutability, canonical codec, fingerprint, and typed failures;
- `tests/test_information_gain_table_numeric.py` covers exact integer belief
  multiplication and GCD reduction, impossible evidence, Decimal precision 50,
  `ROUND_HALF_EVEN`, `Decimal.ln`, isolation from ambient exponent/trap settings,
  final `1e-30` quantization, fixed 30-place serialization, and no-epsilon ties;
- `tests/test_table_information_gain_policy.py` covers history-order replay,
  completed-candidate exclusion, RunSpec-order tie-breaking, deterministic
  decision/rationale metadata, and model-fingerprint binding;
- `tests/test_run_spec_v3.py` covers all three exact policy configurations,
  strict v1/v2/v3 separation, candidate and observation-metric binding, and
  canonical round trips;
- `tests/test_workload_v3_resume.py` covers prefix verification and exact belief
  reconstruction before any resumed adapter execution;
- `tests/test_run_bundle_v3.py` covers three-policy export, read-only verification,
  semantic tamper rejection, exact score and lineage replay, and zero adapter,
  callable, or command execution during empty-directory replay.

These modules belong in the explicit Core manifest. Focused debugging can bypass
the manifest without loading repository `conftest.py`:

```console
uv run python -m pytest -o addopts= --noconftest -p no:cacheprovider tests/test_run_spec_v3.py
```

## SQLite migration transaction contract

The frozen latest SQLite schema in this checkout is version 6. The transactionality
contract covers the complete `0 -> 1 -> 2 -> 3 -> 4 -> 5 -> 6` graph. Versions v1
through v5 are supported legacy schemas; v5 is a valid retry checkpoint but is not
the latest schema. The `5 -> 6` edge adds only the `workload_experiments` table. It
persists the RunSpec fingerprint with completed workload records, not the full
RunSpec document. Because this edge has exactly one schema mutation, the first,
middle, and final mutation fault-probe labels exercise the same mutation boundary.

`ExperimentStore.init_schema()` is the sole migration transaction owner. It rejects
an active caller transaction, opens one `BEGIN IMMEDIATE` transaction per version
edge, runs every schema or data statement, validates the target schema, advances
`user_version`, validates again, and commits. Schema changes and `user_version`
therefore commit together. Known tables and triggers are checked against the frozen
canonical `sqlite_schema` definitions before and after each edge. Any exception or
process interruption during an edge rolls that edge back to its exact source schema
and version; retry after reopen is supported. In a multi-edge upgrade, earlier
successful edges stay committed, so a later failure resumes from the last complete
version rather than restarting the whole chain.

Migration is forward-only. A current-version database is idempotent, downgrade is
not attempted, and negative, future, or schema/version-mismatched states fail closed
without mutation. Version 0 is accepted only for an empty new database or the exact
legacy unversioned `experiments` schema. Migrations remain additive and local to
SQLite; this contract does not add schema redesign, cross-database coordination, or
whole-chain all-or-nothing rollback.

## Core compatibility release gate

The deterministic offline compatibility check is:

```console
uv run python -m research_decision_engine.core_release_check
```

Run it twice when preparing release evidence and require byte-identical canonical
JSON results. It validates the frozen manifest and imports, public signatures and
immutable fields, schema/version and policy matrices, canonical fixtures, Core test
membership, SQLite v1-to-v6 success and rollback/retry behavior, future-version
rejection, static policy loading, fixture hygiene, and package data. It performs no
network access or external user-workload execution.

The configured `.github/workflows/core-v1.yml` matrix runs the Core release gates on
Windows and Linux with Python 3.12. Configuration is not proof of remote CI passage.
A green Core gate is limited to Core: it does not run Assurance or Continual
Learning, creates no Assurance authority, and does not by itself establish Core v1
release readiness.

Broader-replication and Assurance tests, together with the frozen closed-loop
evaluation tests, are tracked separately in `tests/experimental_pytest.txt`. Run
that opt-in suite explicitly with:

```console
uv run python -m pytest -o addopts= -p no:cacheprovider "@tests/experimental_pytest.txt"
```

The closed-loop tests remain experimental because their frozen byte-level protocol
checks are checkout-line-ending-sensitive and require ignored historical artifact
directories. Overriding `addopts` restores the experimental suite's repository
`conftest.py`; its existing import-time failures therefore remain visible. The
opt-in suite is preserved, but it is not part of the Core v1 release gate and is not
required to pass here. Exclusion does not mean deletion, passage, or approval. A
passing Core gate creates no Assurance authority, does not approve the scientific
protocols, and does not establish Core v1 release readiness.

The executable offline example creates all runtime files under a disposable
temporary directory, so its behavior does not depend on the current working
directory:

```console
uv run python examples/run_bundle_replay.py
```

See `RUNBUNDLE.md` for the exact v1, v2, and v3 RunBundle schemas, canonical
hashing rules, public API, recorded-observation trust boundary, and replay limits.

The versioned real CPU CommandAdapter example writes exclusively to its required
caller-owned output directory:

```console
uv run python -B examples/command_adapter_compression/run_example.py --output-dir <empty-directory>
uv run python -B examples/command_adapter_compression/run_v2_example.py --policy random --output-dir <empty-random-v2-directory>
uv run python -B examples/command_adapter_compression/run_v2_example.py --policy greedy_prior --output-dir <empty-greedy-v2-directory>
uv run python -B examples/command_adapter_compression/run_v3_example.py --policy random --output-dir <empty-random-v3-directory>
uv run python -B examples/command_adapter_compression/run_v3_example.py --policy greedy_prior --output-dir <empty-greedy-v3-directory>
uv run python -B examples/command_adapter_compression/run_v3_example.py --policy information_gain_table --output-dir <empty-information-gain-v3-directory>
```

The original v1 random compatibility path remains unchanged. Under v2, separate
`random` and `greedy_prior` runs each execute four steps, close and reopen SQLite,
resume to eight steps, export and verify a bundle, and replay into an empty
directory with command count zero. A second independent greedy-prior execution
must produce the same deterministic policy order. Results compare observed
outcomes descriptively and do not assert policy superiority.

Under v3, separate `random`, `greedy_prior`, and `information_gain_table` runs
use the unchanged corpus and exact 24-candidate set. Each interrupts after step
four, reopens SQLite schema 6, resumes to eight steps, exports and verifies a v3
bundle, and replays into an empty directory. The information-gain run additionally
checks exact outcome classification, integer belief lineage, model and belief
fingerprints, and fixed-30-place scores. Every v3 replay reports zero adapter,
callable, and command execution, and the external command counter remains zero.
The finite likelihood table is a fixed heuristic demonstration model, not a
learned or scientifically calibrated model.

See `RUNSPEC.md`, `RUNBUNDLE.md`, and `COMMAND_ADAPTER.md` for the exact versioned
policy, process, output, error, resume, truth-free, and replay non-execution
contracts. The generic information-gain real-workload bridge is versioned only
through v3; v1 and v2 behavior and golden artifacts remain unchanged.
