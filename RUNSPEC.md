# Versioned Core RunSpec and workload adapters

`RunSpec` remains the immutable, truth-free input contract for the original
generic Core workload path. Its schema is `rde-core-run-spec/v1`; it remains
strictly `random`-only and retains its exact canonical bytes, explicit seed, and
`candidate-order` tie semantics. `RunSpecV2` is a parallel contract with schema
`rde-core-run-spec/v2`. It supports exactly `random` and `greedy_prior`; it does
not silently decode, normalize, or upgrade a v1 artifact. `RunSpecV3` adds the
parallel `rde-core-run-spec/v3` contract. It supports exactly `random`,
`greedy_prior`, and `information_gain_table`; neither earlier decoder accepts or
upgrades the v3 policy or schema.

The versioned policy contract is finite:

| RunSpec schema | Supported policies | RunBundle schema | Replay contract |
| --- | --- | --- | --- |
| `rde-core-run-spec/v1` | `random` | `rde-core-run-bundle/v1` | `RECORDED_OBSERVATION_DECISION_REPLAY_V1` |
| `rde-core-run-spec/v2` | `random`, `greedy_prior` | `rde-core-run-bundle/v2` | `RECORDED_OBSERVATION_DECISION_REPLAY_V2` |
| `rde-core-run-spec/v3` | `random`, `greedy_prior`, `information_gain_table` | `rde-core-run-bundle/v3` | `RECORDED_OBSERVATION_DECISION_REPLAY_V3` |

In v2, `random` still has an empty policy configuration and requires an explicit
signed-64-bit seed. `greedy_prior` is deterministic: its seed is exactly null at
the byte level and `None` at the Python API. A non-null seed is rejected rather
than ignored.

In v3, `random` and `greedy_prior` retain those exact v2 selection semantics;
only their explicit schema identity changes. `information_gain_table` is also
deterministic and requires a null seed. Its policy configuration contains
exactly `evidence_model` and `tie_break`, with the latter fixed to
`runspec_candidate_order`. There is no implicit or inferred evidence model.

The canonical identity is the SHA-256 digest of exactly:

```python
json.dumps(
    payload,
    ensure_ascii=False,
    allow_nan=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8") + b"\n"
```

Candidate array order is semantic and is never sorted. Object key insertion order
is not semantic. Inputs are deeply copied, JSON object keys must be strings,
integers must fit signed 64-bit range, floats must be finite, and negative zero is
normalized to positive zero. The strict decoder rejects unknown fields, duplicate
JSON keys, unsupported schemas, and valid-but-noncanonical JSON encodings.

All new stable names have one documented import surface: the package root.
`CandidateSpec` contains only a candidate ID and normalized parameter map;
`NormalizedObservation` contains a finite objective value and nonnegative cost.
Neither record has a benchmark `true_value` field.

```python
from research_decision_engine import (
    CandidateSpec,
    CompletedWorkloadExperiment,
    FiniteTableEvidenceModel,
    NormalizedObservation,
    PriorGreedyPolicy,
    PythonFunctionAdapter,
    RunSpec,
    RunSpecV2,
    RunSpecV3,
    TableInformationGainPolicy,
    WorkloadAdapter,
    WorkloadAdapterError,
    policy_contract_for_schema,
    resume_workload_trace_v2,
    resume_workload_trace_v3,
    run_workload_experiment,
    run_workload_experiment_v2,
    run_workload_experiment_v3,
    supported_policy_identities,
)
```

Implementation modules are not a second documented import surface.

## Generic prior-utility greedy policy

`PriorGreedyPolicy` has public identity `greedy_prior` and semantic
classification `STATIC_TRUTH_FREE_PRIOR_UTILITY_GREEDY`. Its canonical v2 policy
configuration contains exactly:

```python
policy_config={
    "utility_by_candidate_id": {
        "candidate-a": 10,
        "candidate-b": 20,
    },
    "tie_break": "runspec_candidate_order",
}
```

`utility_by_candidate_id` must cover every RunSpec candidate ID exactly once,
with no missing or additional ID. Every utility is a finite JSON number;
booleans, NaN, infinities, nested metadata, and arbitrary objects are rejected.
There is no default utility. Caller-owned mappings are copied so later mutation
cannot change RunSpec identity. Utility-map insertion order is not semantic;
canonical JSON key sorting determines bytes. Candidate array order remains
semantic.

At each step `PriorGreedyPolicy` excludes completed candidate IDs, selects the
eligible candidate with the highest declared prior utility, and resolves equal
utilities by the earliest candidate in the exact ordered RunSpec candidate list.
Higher utility always means more desirable; objective direction does not invert
the declared utility. The policy does not interpret candidate parameters, train
or update a model, read objective values, execute an adapter or command, consult
the filesystem, network, environment, or clock, or load a scorer or plugin. Its
only changing input is the set of completed candidate IDs. Exhaustion uses the
existing `candidate_space_exhausted` terminal semantics, subject to the existing
runner ordering for experiment and cost budgets.

The public introspection functions `policy_contract_for_schema`,
`supported_policy_identities`, and `policy_identity_contract` report the exact
schema, policy, bundle, replay, configuration, and seed contracts. Unsupported
schemas, identities, schema-policy combinations, incomplete utility maps,
nonfinite utilities, invalid tie breaks, and deterministic-policy seeds fail
through typed `PolicyContractError` subclasses.

This generic policy is not the existing synthetic
`GreedyPredictedPerformancePolicy`. The synthetic policy and its public import are
preserved unchanged for the benchmark-specific `Candidate` and
`ExperimentRecord` model. Its learning-rate, regularization, model-width, and
optimizer assumptions are not added to `CandidateSpec`, and there is no alias or
automatic conversion between synthetic `greedy` and generic `greedy_prior`.

The utility map is truth-free structurally: it is declared before workload
execution, fixed for the run, and contains no observations or hidden adapter
data. RDE cannot prove that a caller did not manually copy private truth into the
numbers. That provenance remains a caller trust boundary; utilities must not be
described as predictions, posterior beliefs, or observed superiority.

## Generic finite-table information gain

`TableInformationGainPolicy` has public identity `information_gain_table` and
semantic classification
`USER_DECLARED_FINITE_HYPOTHESIS_OUTCOME_LIKELIHOOD_TABLE`. It is available only
through RunSpec v3. Its immutable `FiniteTableEvidenceModel` canonical payload
contains exactly:

```text
hypothesis_ids
prior_weight_by_hypothesis
observation_metric
outcome_ids
outcome_thresholds
likelihood_row_total
likelihood_weight_by_candidate_id
```

Hypothesis and outcome order are semantic. Priors are positive integers, and
declared and derived information-gain integers use the documented 12,000-bit
safety bound. Arithmetic inside that bound remains exact. The candidate keys
must exactly equal the enclosing RunSpec candidate IDs; every hypothesis row
names every outcome, contains nonnegative integer weights, and sums to the common
positive `likelihood_row_total`. Thresholds are finite,
strictly increasing, and define lower-inclusive and upper-exclusive interior
intervals. The model metric must equal the RunSpec objective name. Missing,
Boolean, NaN, or infinite observations fail closed. Caller mappings are copied
and recursively frozen, and the model contains no callable or benchmark truth.

The authoritative belief is the ordered exact integer weight tuple aligned with
`hypothesis_ids`. It begins at the declared prior. After candidate `c` produces
classified outcome `o`, each weight is multiplied by the fixed table entry
`likelihood[c][h][o]`; an all-zero result is rejected, and every other result is
divided by its greatest common divisor. The belief fingerprint binds the belief
schema, ordered hypothesis IDs, and exact weights. Binary floating-point
posterior probabilities are never the identity-bearing state.

Candidate scoring derives probabilities from those exact integers in a local
`decimal.Decimal` context with precision 50 and `ROUND_HALF_EVEN`. Shannon
entropy uses `Decimal.ln`, converts to bits by dividing by `Decimal(2).ln()`, and
quantizes only the final expected-information-gain score to `1e-30`. Quantized
scores are compared directly, with no epsilon or random perturbation. Exact ties
select the earliest eligible RunSpec candidate, and the selected score is
serialized with exactly 30 fractional digits.

The table is fixed for the complete run. The policy reconstructs belief only by
replaying completed normalized observations in order; it does not inspect an
unselected outcome, candidate parameter meaning, workload adapter, filesystem,
network, environment, or clock. This is user-model-conditioned information gain,
not Bayesian optimization, objective prediction, scientific calibration, or a
claim that the declared hypotheses are true. See `INFORMATION_GAIN_TABLE.md` for
the complete public model, numeric, lineage, and trust-boundary contract.

## Temporary, offline example

This complete example uses no network, GPU, external data, protected repository,
or hidden benchmark truth:

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from research_decision_engine import (
    CandidateSpec,
    NormalizedObservation,
    PythonFunctionAdapter,
    RunSpec,
    run_workload_experiment,
)
from research_decision_engine.storage import ExperimentStore


def score(candidate: CandidateSpec) -> NormalizedObservation:
    # This explicit conversion belongs to trusted user code, not the adapter.
    x = float(candidate.parameters["x"])
    return NormalizedObservation(objective_value=-(x - 2.0) ** 2, cost=0.25)


spec = RunSpec(
    candidates=[
        CandidateSpec("point-1", {"x": 1.0}),
        CandidateSpec("point-2", {"x": 2.0}),
        CandidateSpec("point-3", {"x": 3.0}),
    ],
    policy_id="random",
    policy_config={},
    policy_seed=17,
    experiment_count_budget=2,
    cost_budget=1.0,
    adapter_id="local-quadratic",
    adapter_version="1",
    objective_name="quadratic-score",
    objective_direction="maximize",
    tie_break="candidate-order",
)
adapter = PythonFunctionAdapter(
    score,
    adapter_id="local-quadratic",
    adapter_version="1",
)

with TemporaryDirectory() as directory:
    database = Path(directory) / "history.sqlite"
    with ExperimentStore(database) as store:
        store.init_schema()
        run_workload_experiment(store, run_spec=spec, adapter=adapter)
        run_workload_experiment(store, run_spec=spec, adapter=adapter)

    with ExperimentStore(database) as reopened:
        reopened.init_schema()
        history = reopened.list_workload_experiments(spec.fingerprint())

    assert len(history) == 2
    assert all(not hasattr(item.candidate, "true_value") for item in history)
    print(spec.fingerprint(), [item.candidate.candidate_id for item in history])
```

The existing synthetic `rde init`, `rde suggest`, `rde run`, history, and reasoning
paths remain separate and unchanged.

## Trust boundary and current limitations

`PythonFunctionAdapter` calls trusted user code exactly once in the current
process. Without an explicit constructor-supplied normalizer, the callable must
return an exact `NormalizedObservation`; arbitrary objects are never broadly
coerced. Ordinary exceptions become `WorkloadAdapterError` with the original
exception as `__cause__`. `KeyboardInterrupt`, `SystemExit`, `GeneratorExit`, and
other `BaseException` subclasses are not caught.

The adapter provides no retry, timeout, asynchronous execution, subprocess,
sandbox, security isolation, or idempotency guarantee. The adapter itself neither
accesses nor assumes a network, filesystem, or particular environment; trusted user
code may do so. Determinism depends on the callable and explicit inputs. Adapter ID
and version are user-declared compatibility identities; they are not inferred from
`repr`, memory addresses, or code locations. The RunSpec does not bind callable
source bytes.

SQLite schema v6 adds a separate `workload_experiments` table so the generic path
never fabricates the old synthetic table's required `true_value`. Rows bind the
external RunSpec fingerprint, but the full RunSpec remains an execution input. A
reported cost is known only after user code returns, so the in-process runner can
reject an over-budget observation before insertion but cannot undo user-code side
effects or reserve unknown cost in advance.

The local store is not a tamper-evident RunBundle, and concurrent runners do not
provide cross-process exactly-once execution. SQLite uniqueness prevents a second
completion row for the same candidate and RunSpec, but competing user callables may
already have run before that conflict is observed.

RunSpec v3 requires no SQLite migration. Its fingerprint binds the complete
finite evidence model, candidate and hypothesis order, prior, thresholds,
likelihood table, and tie-break. Schema v6 already preserves the ordered
candidate completions, normalized objective values, and costs needed to rebuild
and verify the exact integer belief lineage before resumed execution.

The additive `CommandAdapter` and versioned portable RunBundle slices leave
RunSpec v1 and all of its random-policy canonical semantics unchanged. RunSpec v2
and v3 bind their complete policy configurations but, like v1, bind only adapter
ID and version—not callable or executable bytes, builder source, the full
environment, OS image, or external data. See `COMMAND_ADAPTER.md` and
`RUNBUNDLE.md` for their separate process and recorded-observation replay
contracts. Generic information gain is available only through the explicit
finite v3 model; no likelihood or evidence model is invented by Core. Complete
Core API freeze remains open, Core v1 is not release-ready, and this work creates
no Assurance approval.
