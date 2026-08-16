# Research Decision Engine Core (RDE Core) v1 compatibility contract

[简体中文](CORE_V1_COMPATIBILITY.zh-CN.md)

This document defines the human-readable compatibility policy for contract
`RDE_CORE_PUBLIC_API_V1`. The machine-readable authority is
`research_decision_engine/core-public-api-v1.json`. The declared public surface is
`BACKWARD_COMPATIBLE` throughout RDE 1.x on CPython `>=3.12,<3.13` for the supported
Windows and Linux platforms. Older Python versions and Python 3.13 are not promised.

Research Decision Engine Core is the product display brand, and RDE Core is its
short name. The Python distribution remains `research-decision-engine`, the import
package remains `research_decision_engine`, and the CLI remains `rde`.

This is a compatibility contract, not a release-readiness claim. Local validation
and a configured workflow do not prove that remote CI passed, and neither creates
RDE Assurance authority.

The current private candidate is `1.0.0rc5`. It remains experimental and
pre-release: real production use and broad user or workload validation are not yet
established. The sanitized product repository is public; no public repository
release, GitHub Prerelease, tag, GitHub Release, or PyPI publication has occurred.

## Public Python imports

The freeze covers exactly 110 package-root exports. Each name below is imported as
`from research_decision_engine import <name>` and has stability
`STABLE_THROUGH_RDE_1_X`:

```text
CandidateSpec
CommandAdapter
CommandAdapterError
CommandBuildError
CommandExitError
CommandInvocation
CommandOutputError
CommandTimeoutError
CompletedWorkloadExperiment
CompletedWorkloadRunTrace
CompletedWorkloadRunTraceV2
CompletedWorkloadRunTraceV3
DeterministicPolicySeedError
EmptyOrDuplicateHypothesisSetError
EvidenceModelDecodeError
EvidenceModelError
ExtraCandidateUtilityError
FiniteTableEvidenceModel
INFORMATION_GAIN_NUMERIC_CONTRACT
ImpossibleEvidenceError
InformationGainBeliefLineage
InformationGainContractError
InformationGainNumericContract
InvalidCandidateUtilityError
InvalidInformationGainBeliefError
InvalidLikelihoodWeightError
InvalidOutcomeSetError
InvalidPolicyTieBreakError
InvalidThresholdCountError
InvalidThresholdError
InvalidThresholdOrderError
LikelihoodCandidateKeyMismatchError
LikelihoodHypothesisKeyMismatchError
LikelihoodOutcomeKeyMismatchError
LikelihoodRowTotalMismatchError
MissingCandidateUtilityError
MissingObservationMetricError
NonfiniteObservationMetricError
NonfiniteUtilityError
NonpositivePriorWeightError
NormalizedObservation
ObservationMetricError
PolicyConfigurationError
PolicyContractError
PriorGreedyPolicy
PriorKeyMismatchError
PythonFunctionAdapter
ReplayBeliefMismatchError
ReplayDecisionMismatchError
ReplayInformationGainScoreMismatchError
ReplayPolicyUnavailableError
ReplayRationaleMismatchError
RunBundle
RunBundleError
RunBundleReplayError
RunBundleReplayResult
RunBundleStep
RunBundleStepV2
RunBundleStepV3
RunBundleV2
RunBundleV2Error
RunBundleV2ReplayError
RunBundleV2ReplayResult
RunBundleV2ValidationError
RunBundleV2VerificationError
RunBundleV2VerificationResult
RunBundleV3
RunBundleV3Error
RunBundleV3ReplayError
RunBundleV3ReplayResult
RunBundleV3ValidationError
RunBundleV3VerificationError
RunBundleV3VerificationResult
RunBundleValidationError
RunBundleVerificationError
RunBundleVerificationResult
RunBundleVersionMismatchError
RunSpec
RunSpecV2
RunSpecV3
RunSpecVersionMismatchError
TableInformationGainPolicy
UnsupportedInformationGainNumericContractError
UnsupportedPolicyForSchemaError
UnsupportedPolicyIdentityError
UnsupportedRunSpecSchemaError
WorkloadAdapter
WorkloadAdapterError
__version__
export_run_bundle
export_run_bundle_v2
export_run_bundle_v3
policy_contract_for_schema
policy_identity_contract
replay_run_bundle
replay_run_bundle_v2
replay_run_bundle_v3
resume_workload_trace
resume_workload_trace_v2
resume_workload_trace_v3
run_workload_experiment
run_workload_experiment_v2
run_workload_experiment_v3
run_workload_trace
run_workload_trace_v2
run_workload_trace_v3
supported_policy_identities
verify_run_bundle
verify_run_bundle_v2
verify_run_bundle_v3
```

SQLite is a deliberate public boundary used by the package-root runner functions.
These two additional submodule imports are stable through RDE 1.x, bringing the
manifest to exactly 112 public-symbol entries:

```python
from research_decision_engine.storage import ExperimentStore, SCHEMA_VERSION
```

These 112 manifest-listed symbols, and only these symbols, form the frozen public
API. Their documented signatures, public fields, and typed-error families are
compatibility-bearing under this RC contract.

`research_decision_engine.__version__` is a stable public symbol through RDE 1.x:
its import path remains available, its type remains `str`, and its value always
equals the active installed distribution version. The value therefore changes
between candidates or releases. Synchronizing it from `0.1.0` to `1.0.0rc1`, then
advancing the private candidate to `1.0.0rc2`, and then to `1.0.0rc3` after the
failed RC2 committed-blob portability check, then to `1.0.0rc4` after correcting
the Private Vulnerability Reporting publication sequence, and then to `1.0.0rc5`
after removing private-source commit references from release-facing bytes, records
distribution identity; it is not an API removal or an incompatible semantic
reinterpretation.
No other public constant receives an exception permitting its value to change.

For `ExperimentStore`, the deliberate public method boundary is `init_schema()`,
`schema_version()`, `add_workload_experiment()`, and
`list_workload_experiments()`, together with construction and context-manager use.
Other storage methods and every migration helper remain outside this freeze.

The manifest is exhaustive. Importability, a name without a leading underscore,
or use by an implementation module does not independently make a symbol public.
The `rde` console command remains the documented CLI entry point, mapped to
`research_decision_engine.cli:main`; its supported behavior is tested separately
from the Python import list.

## Stability classifications

Every importable symbol is treated as one of these classes:

- `CORE_V1_PUBLIC`: only imports enumerated by the public API manifest. Their
  documented signatures or immutable record fields, typed-error families, and
  semantics remain compatible through RDE 1.x.
- `CORE_V1_INTERNAL`: implementation details such as migration helpers, private
  codecs, runner and CLI helpers, mutable factories, filesystem helpers, and test
  support. They can change without deprecation even when direct import happens to
  work.
- `CORE_EXPERIMENTAL`: `closed_loop` and other opt-in, non-manifest Core research
  or benchmark membership outside the broader-replication/Assurance track. These
  surfaces may change or be removed without the Core public deprecation process.
- `ASSURANCE_EXPERIMENTAL`: `research_decision_engine.benchmarks.broader_*`, P4,
  protocol, review-controller, and related Assurance surfaces. They are outside RDE
  Core, remain separately governed, and are never promoted by a Core test or CI
  result.
- `DEPRECATED_CANDIDATE`: a public import explicitly placed on the deprecation
  path. The initial v1 freeze has no such entries.

### Compatibility and deprecation policy

Within RDE 1.x, a stable import path remains importable; immutable public record
fields are not removed, renamed, reordered, or retyped; required parameters are not
reinterpreted; typed error families remain available; truth-free boundaries and
replay non-execution remain intact; and frozen artifact versions are not
reinterpreted.

A stable API can be deprecated only with an explicit documentation entry and a
runtime `DeprecationWarning`. The deprecated API remains functional and compatible
for the rest of RDE 1.x. Removal, an incompatible signature or field change, or a
semantic reinterpretation requires the next major version. Additive APIs may be
introduced in 1.x only when they do not weaken an existing closed schema or change
canonical bytes. Artifact schema versions v1, v2, and v3 remain supported for the
entire 1.x line even if a newer schema is recommended.

## RunSpec, RunBundle, policy, and replay compatibility

The supported matrix is closed and version-matched:

| Version | RunSpec schema | Supported policies | RunBundle schema | Replay contract |
| --- | --- | --- | --- | --- |
| v1 | `rde-core-run-spec/v1` | `random` | `rde-core-run-bundle/v1` | `RECORDED_OBSERVATION_DECISION_REPLAY_V1` |
| v2 | `rde-core-run-spec/v2` | `random`, `greedy_prior` | `rde-core-run-bundle/v2` | `RECORDED_OBSERVATION_DECISION_REPLAY_V2` |
| v3 | `rde-core-run-spec/v3` | `random`, `greedy_prior`, `information_gain_table` | `rde-core-run-bundle/v3` | `RECORDED_OBSERVATION_DECISION_REPLAY_V3` |

V3 is recommended for new runs that need the complete three-policy set. V1 and v2
remain readable and supported through RDE 1.x.

Version separation is strict. Canonical bytes, fingerprints, sidecars, decision and
rationale records, belief lineage, and terminal summaries retain their versioned
meaning. Candidate ordering and canonical RunSpec/RunBundle identity are
compatibility-bearing; reordering candidates or changing canonical identity is not a
compatible rewrite. Core never silently upgrades or downgrades a RunSpec or
RunBundle, and verification never rewrites one. Unknown schema/policy combinations
fail closed. Unknown schemas, duplicate keys, and unknown or missing fields also
fail closed.

Replay is version-matched for v1, v2, and v3 and uses the observations recorded in
the corresponding RunBundle. It uses only the finite built-in policy mapping;
arbitrary import-path or plugin loading is unsupported. Replay does not dynamically
import a policy, call an adapter, invoke a Python callable, or execute a command.
Successful replay workload-execution counts are therefore zero.

## SQLite schema v6

`research_decision_engine.storage.SCHEMA_VERSION` is `6`. A new empty database is
initialized to v6. Versions v1 through v5 are supported legacy schemas, and the
forward graph is:

```text
0 -> 1 -> 2 -> 3 -> 4 -> 5 -> 6
```

| SQLite rule | Frozen contract |
| --- | --- |
| Latest schema | `V6` |
| New-database terminal schema | `V6` |
| Supported legacy schemas | `V1`, `V2`, `V3`, `V4`, `V5` |
| Migration model | `PER_VERSION_STEP_ATOMIC_AND_RESUMABLE` |
| V5 role | `SUPPORTED_LEGACY_SCHEMA_AND_RETRY_CHECKPOINT`; `NOT_LATEST_SCHEMA` |
| Downgrade | `NOT_SUPPORTED` |
| Unknown future schema | `REJECT_BEFORE_MUTATION` |

Version 0 is an initialization state, accepted only for an empty database or the
exact supported unversioned legacy shape. V5 is a supported legacy schema and a
valid failure/retry checkpoint; it is not the latest schema.

Supported legacy migrations advance exactly one version at a time.
Each edge is owned by one `BEGIN IMMEDIATE` transaction that includes schema/data
mutation, postcondition validation, `PRAGMA user_version`, final validation, and
commit. The model is `PER_VERSION_STEP_ATOMIC_AND_RESUMABLE`: a failed current edge
rolls back to its exact source schema and data, while earlier successfully committed
edges remain committed. Reopening and retrying resumes from the last committed
version. Opening v6 is an idempotent no-op.

The existing `5 -> 6` edge has semantic role
`EXISTING_RUNSPEC_PERSISTENCE_MIGRATION` and one schema mutation: it creates the
exact `workload_experiments` table. That table persists completed workload records
keyed by the externally supplied RunSpec SHA-256 fingerprint; it does not persist
the full RunSpec document. Every existing v5 table and row is preserved; the edge
does not reinterpret or rewrite v5 decisions, observations, beliefs, or calibration
history. Because there is only one schema mutation, the fault-probe labels "after
first schema mutation", "after a middle mutation", and "after final schema/data
mutation" all identify the same mutation boundary; they are not evidence of three
different mutations.

Downgrade is not supported. A negative, unknown future, or schema/version-mismatched
database fails closed and is rejected before mutation. No automatic v6-to-v5
conversion is attempted.
Back up important databases before starting a migration.

## Packaging and supported platforms

The wheel is pure Python. The normalized source-distribution contract contains
exactly 121 members. The bilingual RC5 notes are repository-tracked publication-gate
records and are not source-distribution members:

| Source-distribution class | Members |
| --- | ---: |
| Package | 91 |
| Public documentation | 27 |
| Build/licensing | 3 |

The canonical fixtures and required package data remain part of the distribution
contract. `.github` community-health files are repository-only and excluded from
the source distribution.

The 91 package members include existing importable
`research_decision_engine.benchmarks.broader_*` experimental modules. Those modules
remain `ASSURANCE_EXPERIMENTAL` and outside the Core public API. The exclusion claim
is limited to private or raw audit, recovery, history, and Assurance evidence or
material; it does not claim that every Assurance-related experimental module is
absent.

Windows and Linux are CI-backed platforms for CPython 3.12. No claim is made that
macOS is CI-backed.

## Release checker and CI

Run the offline release checker from the repository root:

```console
python -m research_decision_engine.core_release_check
```

It checks the canonical public manifest, live and installed imports and signatures,
absence of Assurance exports, version/policy matrices, canonical fixture hashes,
SQLite v6 and the migration rollback/retry matrix through `5 -> 6`, Core test
membership, the static policy mapping, fixture path hygiene, and required package
data. It performs no network access and executes no external user workload. Its
machine result is canonical JSON and must be byte-identical across repeated runs.
The committed node streams normalize seven fixed path-rejection parameter displays
to distinct semantic labels before comparison. This preserves every test identity
without embedding Windows, POSIX, or file-URI path literals in canonical fixtures.

`.github/workflows/core-v1.yml` configures the same Core release gates on Windows
and Linux with Python 3.12 for pushes and pull requests. The workflow has read-only
repository contents permission and runs the release checker, Ruff, mypy,
deterministic collection, the Core tests, builds and clean-wheel checks, fixtures,
migration probes, replay smoke tests, adapters, and the v3 three-policy example.

A green Core workflow means only that the configured Core contract checks passed on
the tested commit and matrix. It does not run or approve broader-replication,
Package-L/Package-P, P4, candidate restoration, or other RDE Assurance work; it does
not establish scientific validity, production readiness, release readiness, or
PyPI/GitHub publication authority. Committing the workflow configures CI but is not
evidence that remote Windows or Linux CI has run or passed.

## Compatibility limits

The following boundaries are distinct:

- **Public API compatibility** covers only manifest-listed imports and their frozen
  signatures, public fields, typed-error families, and documented semantics.
- **Artifact-schema compatibility** covers the closed, version-matched RunSpec and
  RunBundle schemas, candidate ordering, and canonical artifact identity.
- **SQLite migration compatibility** covers the supported forward, stepwise,
  atomic, and resumable migrations through schema v6; it does not include downgrade
  or unknown future schemas.
- **Deterministic replay compatibility** covers version-matched decisions from
  recorded observations without workload execution; it does not recreate the
  original external environment.
- **Scientific validity** is not established by an API, artifact, migration, replay,
  test, or CI compatibility result.
- **OS and user-workload behavior** depends on the user's callable, command,
  filesystem, tools, and environment. Windows/Linux Core CI does not guarantee every
  user workload and makes no macOS CI claim.

Compatibility does not prove scientific correctness.

## Relationship to other RDE tracks

RDE Core runs independently: neither RDE Continual Learning nor RDE Assurance is a
runtime, test, or packaging dependency. Continual Learning is a separate future
product track that may consume stable Core interfaces but cannot change this
contract implicitly. RDE Assurance remains paused, preserved, and separately
authorized. Core tests and CI create no Assurance authority, S-stage transition,
review seal, Package-L/Package-P approval, or candidate-restoration permission.

The compatibility freeze closes a bounded Core contract only. C6 is
`CLOSED_FOR_RC`; C7 is `PARTIALLY_CLOSED`. This document advances neither state, and
RDE Core v1 remains `NOT_READY`.
