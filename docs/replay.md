# Recorded-observation replay guide

English | [简体中文](zh-CN/replay.md)

Recorded-observation replay re-executes the frozen Core decision contract against
observations already stored in a verified RunBundle. It rebuilds policy selection,
decision and rationale construction, exact belief updates when applicable, SQLite
persistence, cumulative costs, and terminal-summary derivation, then requires the
rebuilt semantics to equal the artifact.

## What replay does not execute

Replay receives no workload adapter, callable, command builder, command, or plugin.
The execution boundary is exact:

```text
PythonFunctionAdapter callable: NOT EXECUTED
CommandAdapter command:         NOT EXECUTED
external workload:              NOT EXECUTED
```

The original run executes the trusted workload and records normalized observations.
Replay injects only those observations after recomputing and checking the decision
for each step.

## Version handling and static policy factories

Call the replay function that matches the bundle exactly:

| RunBundle / RunSpec | Replay function and contract | Static policies |
| --- | --- | --- |
| v1 / v1 | `replay_run_bundle` / `RECORDED_OBSERVATION_DECISION_REPLAY_V1` | `random` |
| v2 / v2 | `replay_run_bundle_v2` / `RECORDED_OBSERVATION_DECISION_REPLAY_V2` | `random`, `greedy_prior` |
| v3 / v3 | `replay_run_bundle_v3` / `RECORDED_OBSERVATION_DECISION_REPLAY_V3` | `random`, `greedy_prior`, `information_gain_table` |

Each replay path uses a finite built-in static mapping. The artifact cannot name an
arbitrary Python module, import path, class, entry point, source file, callable,
scorer, likelihood function, plugin, registry, or URL. An unknown schema, wrong
RunSpec/RunBundle pairing, unsupported policy, unavailable static replay policy, or
policy/version mismatch fails closed; no version is silently upgraded or downgraded.

## Inputs and destination contract

The public v3 signature is representative:

```text
replay_run_bundle_v3(bundle_directory: Path, destination_directory: Path) -> RunBundleV3ReplayResult
```

Both arguments must be `pathlib.Path` instances, not strings or arbitrary path-like
objects. `bundle_directory` names an existing valid two-file RunBundle. Replay
invokes the matching strict verifier before any destination work and verifies the
source again before success. A bad artifact becomes a versioned replay failure;
replay does not repair it. Each verification call rejects linked or reparse source
ancestry and binds the source root/member identities for that call; replay does not
hold one source guard continuously between the two calls.

`destination_directory` names either a nonexistent child of an existing plain
parent directory or an existing plain, completely empty directory. Replay rejects
a nonempty directory and never merges with prior state. Every existing destination
ancestor is checked as an ordinary non-link, non-reparse directory. Replay binds
the physical identity of the destination root it creates or opens; it does not
claim continuous physical-identity binding for every ancestor.
An ordinary successful replay publishes:

```text
replay.sqlite3
```

Every version builds a temporary SQLite database inside the destination, validates
it, and publishes `replay.sqlite3` without replacement through a hard-link operation
that does not follow symlinks. It removes the temporary name and requires the
published database to remain the same plain, non-reparse, single-link regular file.
The new database uses the current public schema. Replay publishes it only after
rebuilding all steps, reopening the temporary database, checking schema, history
reconstruction, and `PRAGMA integrity_check`, and binding the destination and
database physical identities. V3 additionally requires the final destination
inventory to contain exactly that one database; do not infer that extra inventory
recheck for v1/v2.

## Recomputed and verified semantics

For every ordered bundle step, replay:

1. reconstructs the matching static policy from the embedded RunSpec;
2. selects from the exact RunSpec candidate order after excluding completed IDs;
3. rebuilds and exactly compares the policy-specific decision and rationale;
4. creates a normalized observation from the recorded objective value and cost;
5. for v3 `information_gain_table`, reclassifies the observation, recomputes exact
   integer belief lineage and fingerprints, and recomputes the quantized information
   gain score;
6. checks cumulative cost and the version-specific step fields, then persists the
   completed workload record to fresh SQLite state. V3 additionally rebuilds and
   compares the complete canonical step.

After all steps, replay derives and compares the complete terminal summary,
including selected candidate order, total cost, stop reason, decision-history hash,
and final belief fingerprint where applicable. Every version reopens SQLite and
checks its schema, persisted history, and integrity. V3 additionally reconstructs
the ordered steps from that reopened history. Success therefore verifies candidate
order, decisions, rationales, recorded observations, costs, belief lineage,
terminal result, source bundle stability, and replay equivalence under the matching
versioned contract.

Only `replay.sqlite3` is published. Decisions, rationales, lineage, and terminal
summary are recomputed and checked against the source bundle; replay does not emit a
second bundle or a separate environment snapshot.

## Results and public errors

Every version returns its replay contract, outer and section hashes, replay-history
hash, step count, ordered selected IDs, SQLite schema version, and
`equivalent=True`. V1 has no public execution-count fields. V2 additionally reports
`adapter_execution_count == 0` and `command_execution_count == 0`. V3 reports all
of the following:

```text
adapter_execution_count == 0
callable_execution_count == 0
command_execution_count == 0
```

General input, destination, persistence, integrity, and terminal failures use
`RunBundleReplayError`, `RunBundleV2ReplayError`, or `RunBundleV3ReplayError`.
The public fail-closed diagnostics also include `ReplayPolicyUnavailableError`,
`ReplayDecisionMismatchError`, `ReplayRationaleMismatchError`, and, for v3,
`ReplayBeliefMismatchError` and `ReplayInformationGainScoreMismatchError`.
Verification and version errors retain their separate public families where the
exact call path exposes them. The common mismatch errors derive from
`PolicyContractError`, so catching only the versioned replay-error class is not an
exhaustive catch for v2/v3.

## Trust boundary

Replay is not a virtual machine or container reproduction. It does not restore an
operating system, Python environment, executable, dependency, file, network service,
hardware device, external data, randomness inside workload code, or any other
software environment. It does not prove that the original workload was truthful or
that running it later would yield the same observation.

Replay proves the deterministic Core decision process only for the recorded
observations and frozen versioned contracts presented in a valid bundle. SHA-256 is
integrity checking, not a signature, confidentiality, encryption, or independent
attestation. Replay creates no RDE Assurance authority, approval, or scientific
validity finding.

## Complete empty-directory replay example

Install the wheel, start in a new disposable directory, save this exact program as
`replay_example.py`, and run `python replay_example.py`. It first creates and
exports a valid bundle, resets an explicit workload execution counter, replays into
a new empty directory, reopens the replay SQLite database, compares semantic
records, and proves the counter remains zero. The English and Chinese guides
intentionally contain the same program.

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

workload_execution_count = 0


def score(candidate: CandidateSpec) -> NormalizedObservation:
    global workload_execution_count
    workload_execution_count += 1
    value = candidate.parameters["x"]
    if type(value) not in (int, float):
        raise TypeError("x must be numeric")
    x = float(value)
    return NormalizedObservation(
        objective_value=-(x - 2.0) ** 2,
        cost=0.25,
    )


candidates = (
    CandidateSpec("point-1", {"x": 1.0}),
    CandidateSpec("point-2", {"x": 2.0}),
    CandidateSpec("point-3", {"x": 3.0}),
)
run_spec = RunSpecV3(
    candidates=candidates,
    policy_id="random",
    policy_config={},
    policy_seed=17,
    experiment_count_budget=2,
    cost_budget=1.0,
    adapter_id="guide.replay-workload",
    adapter_version="1",
    objective_name="score",
    objective_direction="maximize",
)
adapter = PythonFunctionAdapter(
    score,
    adapter_id=run_spec.adapter_id,
    adapter_version=run_spec.adapter_version,
)

source_database = Path("source-history.sqlite3")
with ExperimentStore(source_database) as store:
    store.init_schema()
    trace = run_workload_trace_v3(
        store,
        run_spec=run_spec,
        adapter=adapter,
    )
    source_history = store.list_workload_experiments(run_spec.fingerprint())

assert workload_execution_count == len(trace.steps) == 2

bundle_directory = Path("valid-run-bundle")
export_run_bundle_v3(bundle_directory, trace=trace)
verified = verify_run_bundle_v3(bundle_directory)
assert verified.valid is True

del adapter
source_database.unlink()
assert not source_database.exists()
workload_execution_count = 0
replay_directory = Path("replay-output")
replay_directory.mkdir()
assert not any(replay_directory.iterdir())

replayed = replay_run_bundle_v3(bundle_directory, replay_directory)

assert workload_execution_count == 0
assert replayed.adapter_execution_count == 0
assert replayed.callable_execution_count == 0
assert replayed.command_execution_count == 0
assert replayed.equivalent is True
assert replayed.bundle_sha256 == verified.bundle_sha256
assert replayed.run_spec_sha256 == verified.run_spec_sha256
assert replayed.steps_sha256 == verified.steps_sha256
assert replayed.terminal_summary_sha256 == verified.terminal_summary_sha256

replay_database = replay_directory / "replay.sqlite3"
assert replay_database.is_file()
with ExperimentStore(replay_database) as replay_store:
    replay_history = replay_store.list_workload_experiments(run_spec.fingerprint())
    replay_schema_version = replay_store.schema_version()


def semantic_records(records: object) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            record.candidate.candidate_id,
            record.policy_id,
            record.observation.objective_value,
            record.observation.cost,
        )
        for record in records
    )


assert semantic_records(replay_history) == semantic_records(source_history)
assert tuple(record.candidate.candidate_id for record in replay_history) == (
    replayed.selected_candidate_ids
)
assert replay_schema_version == replayed.sqlite_schema_version

terminal = verified.bundle.terminal_summary
assert replayed.step_count == terminal["completed_steps"] == len(replay_history)
assert list(replayed.selected_candidate_ids) == terminal["selected_candidate_ids"]
assert sum((record.observation.cost for record in replay_history), 0.0) == terminal["total_cost"]
assert terminal["decision_history_sha256"] == verified.steps_sha256

print(f"Replay contract: {replayed.replay_contract}")
print(f"Selected candidates: {replayed.selected_candidate_ids}")
print(f"SQLite schema: {replay_schema_version}")
print(f"Replay equivalent: {replayed.equivalent}")
print(f"Replay workload executions: {workload_execution_count}")
```

The timestamp stored for replay persistence is deterministic replay metadata and is
not compared with the original run's wall-clock timestamp in this semantic example.
Delete the whole disposable working directory when finished.
