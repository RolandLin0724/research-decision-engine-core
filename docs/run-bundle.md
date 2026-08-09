# RunBundle guide

English | [简体中文](zh-CN/run-bundle.md)

A RunBundle is the portable artifact for one already recorded, bounded RDE Core
run. It preserves the inputs and evidence needed to verify and replay the frozen
decision process. It is not arbitrary code, a Python environment, a container,
an operating-system image, a complete machine snapshot, or an export of arbitrary
SQLite history.

## Public API and version matrix

Use the version that matches the completed trace and RunSpec exactly:

| RunBundle | Embedded RunSpec | Replay contract | Export / verify |
| --- | --- | --- | --- |
| `rde-core-run-bundle/v1` | `rde-core-run-spec/v1` | `RECORDED_OBSERVATION_DECISION_REPLAY_V1` | `export_run_bundle` / `verify_run_bundle` |
| `rde-core-run-bundle/v2` | `rde-core-run-spec/v2` | `RECORDED_OBSERVATION_DECISION_REPLAY_V2` | `export_run_bundle_v2` / `verify_run_bundle_v2` |
| `rde-core-run-bundle/v3` | `rde-core-run-spec/v3` | `RECORDED_OBSERVATION_DECISION_REPLAY_V3` | `export_run_bundle_v3` / `verify_run_bundle_v3` |

The versioned public signatures are structurally parallel:

```text
export_run_bundle_v3(destination: Path, *, trace: CompletedWorkloadRunTraceV3) -> RunBundleV3VerificationResult
verify_run_bundle_v3(bundle_directory: Path) -> RunBundleV3VerificationResult
```

V1 supports only `random`; v2 supports `random` and `greedy_prior`; v3 supports
those policies plus `information_gain_table`. Bundle, RunSpec, policy, and replay
versions are closed bindings. There is no silent migration, upgrade, downgrade, or
reinterpretation.

## Exact physical layout

Every current bundle version is one plain directory with exactly two unaliased,
single-link plain regular files and no additional member:

```text
run-bundle/
├── run-bundle.json
└── run-bundle.json.sha256
```

`run-bundle.json` is compact, sorted-key, strict UTF-8 canonical JSON with no BOM
or carriage return and exactly one final LF. `run-bundle.json.sha256` is exactly the
64 lowercase hexadecimal characters of `SHA256(run-bundle.json)`, followed by one
LF: 65 bytes total. The JSON field `root_member_count` is exactly `2`.

## Bundle contents

The canonical JSON root contains exactly:

```text
artifact_role
producer
replay_contract
root_member_count
run_spec
run_spec_sha256
schema_version
section_sha256
steps
terminal_summary
```

`artifact_role` is `portable_recorded_observation_run_bundle`. `run_spec` is the
complete embedded canonical RunSpec for the same version, and `run_spec_sha256` is
its public fingerprint.

Each ordered step contains exactly:

```text
step_index
selected_candidate_id
decision
rationale
observation
belief_lineage
cumulative_cost
```

Indices start at zero and are contiguous. The selected candidate must agree across
the step, decision, and normalized observation. V2/v3 rationales directly repeat
that selected ID and must agree; the v1 rationale instead binds the available and
completed selection context without a selected-ID field. Decisions and rationales
carry the closed policy-specific selection record. Observations carry candidate ID,
finite objective value, and finite nonnegative cost. Cumulative cost is checked
against the ordered observations and budget.

`belief_lineage` is empty for v1, for both v2 policies, and for v3 `random` and
`greedy_prior`. Each v3 `information_gain_table` step carries one exact lineage
entry binding the step and candidate, classified outcome, ordered weights before and
after GCD reduction, and both belief fingerprints.

`terminal_summary` contains completed-step count, ordered selected IDs, total cost,
the finite stop reason, final belief fingerprint when applicable, and the decision
history hash. `section_sha256` contains exactly the RunSpec, steps, and terminal
summary hashes. The sidecar separately binds the complete outer JSON document.

## Export

Export starts from the exact immutable completed trace returned by the matching
`run_workload_trace`, `run_workload_trace_v2`, or `run_workload_trace_v3` call. Trace
capture requires empty history for that RunSpec and records every decision,
rationale, observation, lineage entry, cumulative cost, and terminal stop reason as
the bounded run proceeds. Export validates the trace against its embedded RunSpec
and static policy. It does not call an adapter or workload and does not reconstruct
a trace later from arbitrary database rows.

The destination argument must be a `pathlib.Path` instance, not a string or
arbitrary path-like object; its parent and ancestry must already be ordinary
non-link, non-reparse directories, and the destination itself must not exist in any
form. If it already exists, export raises the versioned
`RunBundle...ValidationError` and does not overwrite or merge it.

Export creates a temporary sibling on the same volume, writes both exclusive new
members, verifies the temporary bundle, publishes the directory with no replacement,
and then reopens and verifies the published artifact. On Windows, publication and
verification bind directory handles and physical identities. On Linux, publication
uses the platform's atomic exclusive no-replace rename. Canonical content is portable across the
supported Windows and Linux contracts, while atomic namespace mechanics are
platform-specific; this is not a broader guarantee against every actively racing
same-account namespace adversary, generic POSIX/macOS support, or crash durability.

Use an installed distribution. Producer metadata resolution is part of export;
v1/v2 require installed package metadata, while v3 records package version
`0+unknown` only when that metadata is unavailable.

## Verify

Verification is read-only and returns an immutable result only after every check
passes. It checks:

- the root is the expected plain directory with exactly the two named plain files;
- root ancestry and root/member physical identities remain stable throughout both
  reads;
- the exact 65-byte sidecar matches the complete JSON bytes;
- JSON is strict canonical UTF-8 with the exact closed schema, role, replay contract,
  producer fields, and no unknown, missing, duplicate, nonfinite, hidden-truth, or
  forbidden absolute-path values;
- the embedded RunSpec uses the matching version, decodes canonically, and matches
  `run_spec_sha256`;
- the RunSpec, ordered steps, and terminal summary match all three section hashes;
- step indices, member/candidate identities, policy decisions, rationales,
  observations, costs, belief lineage, budgets, stop reason, and terminal summary
  are internally consistent with the embedded RunSpec and frozen static policy;
- neither member nor the source root changed during verification.

A successful result exposes `valid=True`, the outer bundle SHA, the three section
SHAs, step count, ordered selected IDs, and the decoded immutable bundle. Verification
does not access SQLite, a network, an adapter, callable, command builder, or external
workload.

The hashes provide integrity and tamper detection for the files presented to the
verifier. They are not a digital signature, signer identity, third-party
attestation, encryption, or confidentiality. Anyone able to replace both files can
construct a different self-consistent artifact.

## Tamper detection and public errors

Construction and export contract failures use `RunBundleValidationError`,
`RunBundleV2ValidationError`, or `RunBundleV3ValidationError`. During direct
verification, v1/v2 wrap decoded canonical/schema failures in their corresponding
`RunBundle...VerificationError`, while v3 preserves
`RunBundleV3ValidationError` for those failures. Physical inventory, stable-read,
and sidecar failures use the corresponding `RunBundle...VerificationError` in all
versions. Closed version or semantic mismatches can instead surface public
`RunBundleVersionMismatchError`, `ReplayDecisionMismatchError`,
`ReplayRationaleMismatchError`, or the v3 belief/score mismatch errors. Replay uses
a separate versioned replay-error family. These names are public package-root
imports; the versioned base classes are `RunBundleError`, `RunBundleV2Error`, and
`RunBundleV3Error`. Catching only a versioned verification base is therefore not an
exhaustive catch for every semantic or version failure.

Tampering with either member, adding or removing a member, changing canonical JSON
or section content, or replacing a file during verification fails closed. The
example below copies the valid bundle and changes one non-sensitive sidecar byte.
It never changes the original valid bundle.

## Producer metadata and stable sections

`producer` contains exactly `package_name`, `package_version`,
`python_implementation`, and `python_version`. The Python value includes the patch
version. Verification checks the closed nonempty-string shape but does not require
the producer values to match the current interpreter. Producer metadata is part of
`run-bundle.json`, so two legitimate exports with different producer payloads may
have different outer bundle SHA-256 values. Do not expect equal outer SHAs across
Python patch or producer-version changes.

The separately stored `run_spec`, `steps`, and `terminal_summary` section hashes
bind their identity-bearing canonical payloads independently of producer metadata.
Compare the section appropriate to the identity claim; do not erase or rewrite
producer metadata to manufacture outer-SHA equality.

## Complete export, verify, and disposable tamper example

Install the wheel, start in a new disposable directory, save this exact program as
`run_bundle_example.py`, and run `python run_bundle_example.py`. The English and
Chinese guides intentionally contain the same program.

```python
from pathlib import Path
from shutil import copytree

from research_decision_engine import (
    CandidateSpec,
    NormalizedObservation,
    PythonFunctionAdapter,
    RunBundleV3VerificationError,
    RunSpecV3,
    export_run_bundle_v3,
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
    adapter_id="guide.bundle-workload",
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

assert workload_execution_count == len(trace.steps) == 2
calls_before_export = workload_execution_count

bundle_directory = Path("valid-run-bundle")
exported = export_run_bundle_v3(bundle_directory, trace=trace)
verified = verify_run_bundle_v3(bundle_directory)

assert workload_execution_count == calls_before_export
assert exported.valid is True
assert verified.valid is True
assert verified.bundle_sha256 == exported.bundle_sha256
assert sorted(path.name for path in bundle_directory.iterdir()) == [
    "run-bundle.json",
    "run-bundle.json.sha256",
]

tampered_directory = Path("tampered-run-bundle")
copytree(bundle_directory, tampered_directory)
tampered_sidecar = tampered_directory / "run-bundle.json.sha256"
sidecar_bytes = bytearray(tampered_sidecar.read_bytes())
sidecar_bytes[0] = ord("0") if sidecar_bytes[0] != ord("0") else ord("1")
tampered_sidecar.write_bytes(sidecar_bytes)

tampered_rejected = False
try:
    verify_run_bundle_v3(tampered_directory)
except RunBundleV3VerificationError:
    tampered_rejected = True

assert tampered_rejected is True
original_after_tamper = verify_run_bundle_v3(bundle_directory)
assert original_after_tamper.bundle_sha256 == verified.bundle_sha256

print(f"Bundle schema: {verified.bundle.schema_version}")
print(f"Bundle SHA-256: {verified.bundle_sha256}")
print(f"Selected candidates: {verified.selected_candidate_ids}")
print("Valid bundle verification: PASS")
print("Tampered copy rejected: PASS")
print("Original bundle remains valid: PASS")
```

Delete the whole disposable working directory when finished. The valid and
tampered bundle names are intentionally separate so the tamper demonstration never
edits the source artifact.
