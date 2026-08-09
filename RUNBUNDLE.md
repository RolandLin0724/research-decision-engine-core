# Versioned portable RunBundle replay

`RunBundle` is the Core portable artifact for replaying a decision process against
observations recorded by one completed generic workload run. The immutable v1
contract remains `rde-core-run-bundle/v1` with
`RECORDED_OBSERVATION_DECISION_REPLAY_V1` and an embedded random-only RunSpec v1.
The parallel v2 contract is `rde-core-run-bundle/v2` with
`RECORDED_OBSERVATION_DECISION_REPLAY_V2` and an embedded RunSpec v2 supporting
exactly `random` and `greedy_prior`. Both use artifact role
`portable_recorded_observation_run_bundle`. RunBundle v3 adds
`rde-core-run-bundle/v3` with `RECORDED_OBSERVATION_DECISION_REPLAY_V3` and an
embedded RunSpec v3 supporting exactly `random`, `greedy_prior`, and
`information_gain_table`; it retains the same artifact role.

Version binding is strict. A v1 bundle rejects RunSpec v2, a v2 bundle rejects
RunSpec v1, and every v3 bundle requires exactly RunSpec v3. No codec silently
translates, upgrades, rewrites, or normalizes another version. Existing v1 and
v2 bundle bytes, sidecars, section hashes, verification behavior, and replay
behavior remain unchanged.

This is recorded-observation decision replay. Replay recomputes policy selection,
decision and rationale payloads, injects the recorded normalized observations,
reapplies the applicable state and persistence operations, and checks the terminal
summary. It does not rerun an external workload, import or invoke a user callable,
or reconstruct callable source bytes.

## Physical artifact

A materialized v1, v2, or v3 bundle is one directory with exactly two ordinary files
and no subdirectories or other entries:

```text
run-bundle/
|-- run-bundle.json
`-- run-bundle.json.sha256
```

Symlinks, junctions, reparse substitutes, path aliases, reparse ancestors, and
extra members are rejected. `run-bundle.json.sha256` is exactly 65 bytes:

```text
<64 lowercase SHA-256 hex characters><LF>
```

That digest is `SHA256(exact run-bundle.json bytes)`. The full document hash is
external because embedding it in `run-bundle.json` would be self-referential.

The JSON document has exactly these ten top-level fields:

```text
schema_version
artifact_role
replay_contract
run_spec
run_spec_sha256
producer
steps
terminal_summary
section_sha256
root_member_count
```

`root_member_count` is `2`. `producer` contains exactly `package_name`,
`package_version`, `python_implementation`, and `python_version`. It never carries
a host name, user name, process ID, clock value, UUID, working directory, absolute
source path, callable representation, or object address. Producer data is
provenance, not executable code.

## Canonical JSON and hashes

All three RunSpec and RunBundle versions use the same canonical JSON
byte rule:

```python
json.dumps(
    payload,
    ensure_ascii=False,
    allow_nan=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8") + b"\n"
```

The decoder requires strict canonical UTF-8: no BOM, carriage return, missing
final LF, duplicate key, unknown or missing field, nonfinite number, or
noncanonical spelling is accepted.

`run_spec` is the exact decoded canonical `RunSpec` payload.
`run_spec_sha256` is the public `RunSpec.fingerprint()`, which is the SHA-256 of
the exact canonical RunSpec bytes. `section_sha256` contains exactly:

- `run_spec`: equal to `run_spec_sha256`;
- `steps`: `SHA256(canonical_json_bytes(steps))`;
- `terminal_summary`:
  `SHA256(canonical_json_bytes(terminal_summary))`.

The external sidecar, rather than `section_sha256`, identifies the complete
`run-bundle.json` document.

## Step and terminal schemas

Step order is semantic. Each step has exactly seven fields:

```text
step_index
selected_candidate_id
decision
rationale
observation
belief_lineage
cumulative_cost
```

Indices start at zero and are contiguous. Candidate identities must belong to the
embedded RunSpec; the selected identity must agree across the step, decision, and
observation. Costs are finite, nonnegative, and nondecreasing cumulatively.
`belief_lineage` is empty for v1 random, both v2 policies, and v3 random or
greedy-prior. Each v3 `information_gain_table` step contains exactly one lineage
entry binding its step and candidate, classified outcome, exact ordered integer
weights before and after GCD reduction, and both belief fingerprints. The
artifact rejects hidden benchmark truth, arbitrary Python objects, absolute
filesystem paths, and local `file:` URIs in fields where paths are not part of
the public schema.

For the v1 path, `decision` contains exactly `policy_config`, `policy_id`,
`policy_seed`, and `selected_candidate_id`. `rationale` contains exactly
`available_candidate_ids`, `completed_candidate_ids`, and `selection_rule`, whose
v1 literal is `random-choice-over-remaining-candidates/v1`. `observation` contains
exactly `candidate_id`, `objective_value`, and `cost`.

`terminal_summary` has exactly:

```text
completed_steps
selected_candidate_ids
total_cost
stop_reason
final_belief_fingerprint
decision_history_sha256
```

The counts, ordered selections, final cost, and steps digest must agree with the
steps. The v1 random path records `final_belief_fingerprint` as null.
The finite v1 stop-reason set is `completed`, `experiment_budget_exhausted`,
`cost_budget_exhausted`, `candidate_space_exhausted`, and `stopped_by_caller`.

## Public API

The deliberate package-root imports are:

```python
from research_decision_engine import (
    CompletedWorkloadRunTrace,
    RunBundle,
    RunBundleError,
    RunBundleReplayError,
    RunBundleReplayResult,
    RunBundleStep,
    RunBundleValidationError,
    RunBundleVerificationError,
    RunBundleVerificationResult,
    export_run_bundle,
    replay_run_bundle,
    run_workload_trace,
    verify_run_bundle,
)
```

Capture one explicitly bounded, completed generic run while it executes:

```python
trace = run_workload_trace(store, run_spec=run_spec, adapter=adapter)
```

`CompletedWorkloadRunTrace` retains immutable `RunBundleStep` records containing
the exact decision, rationale, normalized observation, belief lineage, and
cumulative cost captured around every persisted step, plus the terminal stop
reason. Capture requires an empty history for that RunSpec, so it cannot silently
mix a prior run into the export source.

Export that exact trace:

```python
result: RunBundleVerificationResult = export_run_bundle(
    destination,
    trace=trace,
)
```

The destination must not exist. Export constructs a temporary sibling on the same
volume, writes and validates exactly two files, atomically renames the directory,
then reopens and verifies it. It does not invoke an adapter or callable and never
exports an unbounded SQLite database. It validates the captured trace against the
embedded RunSpec and static policy before publication; it does not reconstruct a
decision trace later from arbitrary database rows. On Windows, publication,
verification ancestry, and interruption cleanup are handle- and physical-identity
bound; on POSIX, publication uses an exclusive no-replace rename. This slice does
not claim broader cross-platform release evidence against an actively racing
same-account namespace adversary.

Verify an existing artifact without changing it:

```python
verification: RunBundleVerificationResult = verify_run_bundle(bundle_directory)
```

A successful immutable result reports `valid`, the outer and three section
digests, the step count, ordered candidate IDs, and the decoded immutable bundle.
Malformed artifacts consistently raise `RunBundleVerificationError`; verification
does not execute an adapter, access SQLite, or consult a network.

Replay into a new or existing empty directory:

```python
replay: RunBundleReplayResult = replay_run_bundle(bundle_directory, destination_directory)
```

Replay verifies first, creates fresh `replay.sqlite3` state, recomputes each
selection, decision, and rationale, injects each recorded observation, checks
lineage and cumulative cost, compares the canonical terminal summary, and reopens
SQLite to check its history and integrity. On the validated Windows path, the
temporary database descriptor and destination-directory identity remain bound
throughout replay so cleanup cannot delete a foreign replacement. The
destination-independent immutable result includes all identity hashes, history
identity, ordered selections, schema version, and `equivalent=True`.

`RunBundleError` is the common typed base. `RunBundleValidationError` covers
construction/export contract violations, `RunBundleVerificationError` covers
strict artifact failures, and `RunBundleReplayError` covers verified-input replay
failures such as unsupported policy identity or recomputation mismatch.

## RunBundle v2 decision replay

RunBundle v2 preserves the exact two-file physical layout, canonical UTF-8 JSON,
one final LF, 65-byte lowercase sidecar, three section hashes, atomic no-clobber
export, read-only verification, tamper detection, and empty-directory replay
properties of v1. It does not reuse the v1 schema or replay literal.

The deliberate package-root API is version-explicit:

```python
from research_decision_engine import (
    CompletedWorkloadRunTraceV2,
    RunBundleV2,
    RunBundleV2ReplayResult,
    RunBundleV2VerificationResult,
    export_run_bundle_v2,
    replay_run_bundle_v2,
    verify_run_bundle_v2,
)
```

For v2 `random`, replay reconstructs the same seeded selection without replacement
from the ordered candidate list and explicit seed. For v2 `greedy_prior`, replay
reconstructs `PriorGreedyPolicy` solely from the ordered RunSpec candidate list,
the complete canonical `utility_by_candidate_id` map, the exact
`runspec_candidate_order` tie-break literal, and completed candidate IDs. The
canonical greedy decision and rationale bind the policy identity, selected
candidate ID, selected prior utility, eligible-candidate count, and tie-break
rule. They state only that the selected candidate had the highest declared prior
utility among eligible candidates; they do not claim predicted accuracy,
compression ratio, posterior belief, information gain, or future knowledge.

The v2 replay factory is a finite static mapping containing only `random` and
`greedy_prior`. An artifact cannot supply a module path, class path, entry point,
import string, registry URL, source bytes, or callable. Unsupported identities,
RunSpec/RunBundle version mismatches, unavailable replay policies, and decision or
rationale mismatches fail closed through typed errors.

Export, verification, and replay never execute `PythonFunctionAdapter`,
`CommandAdapter`, a command builder, external process, or user callable. Replay
injects only the recorded normalized observations after recomputing and checking
each decision and rationale. The real CPU v2 random and greedy-prior bundles both
use command counters to prove replay command execution count is zero.

## RunBundle v3 exact-belief replay

RunBundle v3 preserves the v1/v2 two-file physical layout, canonical UTF-8 JSON,
one final LF, 65-byte lowercase sidecar, three section hashes, atomic no-clobber
export, read-only verification, tamper detection, and empty-directory replay.
Its version-explicit package-root API is:

```python
from research_decision_engine import (
    CompletedWorkloadRunTraceV3,
    RunBundleV3,
    RunBundleV3ReplayResult,
    RunBundleV3VerificationResult,
    export_run_bundle_v3,
    replay_run_bundle_v3,
    verify_run_bundle_v3,
)
```

V3 reconstructs exactly three policies through one finite static mapping. Random
and greedy-prior preserve their v2 selection, decision, and rationale semantics.
For `information_gain_table`, the decision canonically binds the policy identity,
selected candidate, fixed-30-place information-gain score, eligible count,
current exact-belief fingerprint, evidence-model fingerprint, and
`runspec_candidate_order`. The rationale repeats those identity-bearing details
and adds only closed eligibility, completed-history, and selection-rule fields.

For each information-gain step, replay reclassifies the recorded normalized
objective under the embedded thresholds, replays the integer multiplication and
GCD reduction, recomputes the Decimal score under precision 50 with
`ROUND_HALF_EVEN`, checks the `1e-30` quantization and 30-place serialization,
and compares the exact decision, rationale, lineage, cumulative cost, and
terminal final-belief fingerprint. Model, prior, threshold, likelihood,
observation, score, lineage, decision, rationale, and version tampering fail
closed even when an attacker replaces outer digests with a new self-consistent
document hash.

The replay factory accepts no artifact-provided import string, module or class
path, entry point, source code, scorer, callable likelihood, registry, or URL.
Replay never invokes `PythonFunctionAdapter`, `CommandAdapter`, a workload
callable, command builder, `subprocess`, or external command. Successful
`RunBundleV3ReplayResult` reports adapter, callable, and command execution counts
of exactly zero.

SQLite schema 6 is unchanged. The RunSpec fingerprint binds the complete finite
model and all semantic orders, while the existing workload table preserves the
ordered candidate observations and costs from which replay deterministically
rebuilds every lineage entry. No migration or duplicate belief table is needed.

## RunSpec, policy support, and trust boundary

The embedded `RunSpec` is the complete portable decision input and is bound by its
public fingerprint. V1 reconstructs only `random`, with an empty policy
configuration and explicit seed. V2 reconstructs exactly `random` and
`greedy_prior` under their closed versioned contracts. V3 reconstructs those two
policies plus `information_gain_table` from its embedded closed evidence-model
payload. Candidate order remains semantic. Replay never dynamically imports a
policy or module named by the artifact and does not provide a plugin registry.

The original run may use `PythonFunctionAdapter`, whose callable is trusted,
in-process user code without a sandbox, subprocess boundary, timeout, or retry.
The callable executes only during that original run. It is not stored in the
bundle and is neither required nor called by export, verification, or replay.

SHA-256 integrity does not establish that recorded observations are scientifically
true, independently attested, or safe to trust; anyone able to replace both files
can create a new self-consistent bundle. Replay proves the deterministic Core
decision process given those recorded observations. Compatibility also depends on
the exact supported schema, policy semantics, and package/interpreter behavior;
unknown schemas and unsupported policies fail closed.

## Deliberate limits and future work

The additive v2 and v3 slices leave the v1 schema, two-file layout, random-policy
semantics, and replay contract unchanged. Original execution may use one trusted
local direct child, but no bundle version binds command or environment identity,
reproduces the raw external workload, replays a callable or command, provides
descendant process-tree isolation, exports arbitrary historical SQLite state, or
migrates between schema versions. CLI export/verify/replay UX remains future
work. See `COMMAND_ADAPTER.md` for the separate process contract and offline
real-CPU versioned-policy comparison.

RDE Assurance remains paused and separate. A bundle directory is not an Assurance
review root, creates no S-stage or downstream authority, and does not approve a
scientific protocol. The v3 real CPU example compares `random`, `greedy_prior`,
and `information_gain_table` descriptively and supplies the generic
information-gain product-integration bridge. It does not establish policy
superiority, scientific calibration, cross-platform release evidence, or Core v1
release readiness.

Run the offline example from any working directory in an environment where this
package is installed:

```console
python C:/path/to/research-decision-engine-core-v1/examples/run_bundle_replay.py
```
