# RunSpec guide

English | [简体中文](zh-CN/run-spec.md)

`RunSpec` is the immutable, canonical input contract for one bounded Core run. It
binds the ordered candidate set, policy identity and complete policy configuration,
the policy seed when the policy uses one, experiment-count and optional cost
budgets, objective name and direction, and the declared adapter/workload ID and
version. RunSpec v3 also binds the finite evidence model when
`information_gain_table` is selected. Its SHA-256 fingerprint is the portable
identity for all of those inputs.

The adapter identity is a caller-declared compatibility identity. A RunSpec does
not contain or hash Python callable bytes, command bytes, an environment, a
container, external data, or scientific truth.

## Public imports and version matrix

Use the versioned records from the package root:

```text
from research_decision_engine import CandidateSpec, FiniteTableEvidenceModel, RunSpec, RunSpecV2, RunSpecV3
```

The frozen version matrix is:

| Record | Schema | Supported policies | Seed contract | Matching bundle and replay |
| --- | --- | --- | --- | --- |
| `RunSpec` (v1) | `rde-core-run-spec/v1` | `random` | required signed 64-bit integer | RunBundle v1 / `RECORDED_OBSERVATION_DECISION_REPLAY_V1` |
| `RunSpecV2` | `rde-core-run-spec/v2` | `random`, `greedy_prior` | integer for `random`; `None` for `greedy_prior` | RunBundle v2 / `RECORDED_OBSERVATION_DECISION_REPLAY_V2` |
| `RunSpecV3` | `rde-core-run-spec/v3` | `random`, `greedy_prior`, `information_gain_table` | integer for `random`; `None` for deterministic policies | RunBundle v3 / `RECORDED_OBSERVATION_DECISION_REPLAY_V3` |

Use v3 for a new experiment that needs the complete three-policy set. V1 and v2
remain supported by the RDE 1.x compatibility contract. Each decoder accepts only
its exact schema: there is no silent upgrade or downgrade, and a policy/schema or
seed/policy mismatch fails closed.

## Shared identity fields

Every version binds:

- a nonempty ordered sequence of unique exact `CandidateSpec` records;
- one supported policy ID, its closed configuration object, and its seed contract;
- a positive experiment-count budget no larger than the candidate count;
- an optional finite, positive cost budget;
- nonempty adapter ID and adapter version strings;
- a nonempty objective name and an objective direction of exactly `maximize` or
  `minimize`;
- the version's fixed candidate-order tie-break literal.

Candidate parameters and configuration values must be supported canonical JSON
values. Candidate order is semantic: it participates in the fingerprint and in
selection behavior. Object-key insertion order is not semantic because canonical
JSON sorts object keys.

## `random`

The exact public policy identity is `random`, classified by the public contract as
seeded random selection without replacement. Its `policy_config` is exactly an
empty object and its seed is an exact signed 64-bit integer. V1 uses the fixed
RunSpec tie-break literal `candidate-order`; v2 and v3 use
`runspec_candidate_order`.

At each selection, Core forms the remaining candidates in exact RunSpec order,
constructs the deterministic Python random source from the declared seed, and
chooses from that ordered remaining list. The seed controls policy selection only;
it does not seed or constrain adapter code, external commands, or the workload.

Reproducing a selection therefore requires the same RunSpec version and bytes, the
same ordered completed-candidate prefix, and the supported RDE 1.x and CPython 3.12
contract. It does not imply that an external workload will reproduce its
observation. Changing candidate order changes identity and may change selection.

## `greedy_prior`

The exact public identity is `greedy_prior`. It is available in v2 and v3 and is a
static, truth-free prior-utility policy. Its configuration has exactly these keys:

```text
{
    "utility_by_candidate_id": {
        "candidate-a": 10,
        "candidate-b": 20,
        "candidate-c": 20
    },
    "tie_break": "runspec_candidate_order"
}
```

`utility_by_candidate_id` must contain every RunSpec candidate ID exactly once,
with neither missing nor extra IDs. Every value is a finite JSON integer or float;
there is no default. The complete normalized map is part of RunSpec identity.
Caller mappings are copied, so later caller mutation cannot change the RunSpec.

At every step, completed candidates are excluded, the eligible candidate with the
highest declared utility is selected, and an exact tie is resolved by the earliest
eligible candidate in RunSpec order. Higher declared utility always wins;
`objective_direction` does not invert it. Observations never update the utility
map. The values are caller declarations made before the run, not learned
predictions, posterior beliefs, observed superiority, or hidden benchmark truth.

## `information_gain_table`

The exact public identity is `information_gain_table`, available only in v3. Its
seed must be `None`, and its configuration contains exactly an `evidence_model`
payload and `"tie_break": "runspec_candidate_order"`.

The public immutable `FiniteTableEvidenceModel` binds:

- ordered, nonempty, unique hypothesis IDs and one positive integer prior weight
  for every hypothesis;
- an observation metric equal to the enclosing RunSpec objective name;
- at least two ordered, unique outcome IDs and one fewer finite, strictly increasing
  thresholds;
- one positive integer likelihood-row total;
- the complete candidate × hypothesis × outcome table of nonnegative integer
  weights, with every row naming every outcome and summing to the row total.

The model's candidate keys must exactly equal the RunSpec candidate IDs. For
thresholds `t[0] ... t[n-2]`, the outcome partition is:

```text
outcome[0]      metric < t[0]
outcome[i]      t[i-1] <= metric < t[i]
outcome[n-1]    metric >= t[n-2]
```

The ordered prior weights are the initial exact belief. After candidate `c`
produces classified outcome `o`, each hypothesis weight is multiplied by the
declared likelihood weight for `(c, hypothesis, o)`. An all-zero result fails
closed; otherwise all resulting weights are divided by their greatest common
divisor. The exact ordered integers, not floating-point posterior probabilities,
carry belief identity.

Selection computes expected Shannon information gain from the current exact
weights and the fixed table. The numeric contract uses a local `decimal.Decimal`
context with precision 50 and `ROUND_HALF_EVEN`, converts natural-log entropy to
bits, and quantizes only the final score to `1e-30`. The greatest score wins; an
exact tie selects the earliest eligible RunSpec candidate.

This is a user-declared finite model trust boundary. Core does not learn the
likelihood table, infer hypotheses, scientifically calibrate the model, predict
objective quality, or establish that the model is true.

## Validation and public typed errors

Ordinary record-shape violations use `TypeError` or `ValueError`, including invalid
candidate records, duplicate candidate IDs, invalid budgets, adapter/objective
identity, objective direction, or noncanonical decoded bytes.

Policy contract failures use public `PolicyContractError` subclasses:

- `UnsupportedRunSpecSchemaError`, `UnsupportedPolicyIdentityError`, and
  `UnsupportedPolicyForSchemaError` reject unsupported version/policy combinations;
- `PolicyConfigurationError` and its seed, utility-map, numeric, and tie-break
  subclasses reject open, incomplete, or invalid policy configuration;
- `RunSpecVersionMismatchError` rejects wrong-version bytes in the v2/v3 codecs;
  the v1 codec reports its wrong-schema case as ordinary `ValueError`;
- `InformationGainContractError` and `EvidenceModelError` families reject invalid
  hypotheses, priors, outcomes, thresholds, likelihood rows, metrics, numeric
  contract, beliefs, or impossible evidence.

Import these errors from `research_decision_engine` when an application needs to
handle them. The exact leaf types are listed in the public API manifest; internal
normalization helpers are not a public surface.

## Canonical identity

`to_canonical_bytes()` emits compact, sorted-key, strict UTF-8 JSON with no BOM or
carriage return and exactly one final LF. `fingerprint()` is the lowercase SHA-256
hex digest of exactly those bytes. `from_canonical_bytes()` accepts only the exact
version and exact canonical encoding; duplicate, missing, or unknown fields,
nonfinite numbers, unsupported schemas, alternate whitespace, and other aliases
fail closed.

Inputs are copied and normalized into immutable records, and mapping properties
return detached values. Mutating caller-owned candidate parameters, policy maps, or
evidence tables after construction cannot change the canonical bytes or
fingerprint. Candidate, hypothesis, and outcome array order remains identity-bearing.
Configurations that merely look equivalent but retain a schema, order, numeric
type, seed, budget, adapter, objective, or model difference can therefore have
different fingerprints; differences canonicalization intentionally erases, such as
object-key insertion order, do not.

## Complete runnable RunSpec v3 example

Install the wheel, start in a disposable directory, save this exact program as
`run_spec_example.py`, and run `python run_spec_example.py`. It constructs three
candidates with the simplest honest v3 policy, prints schema identity and
fingerprints, completes a canonical round trip, proves determinism and a changed
seed's identity effect, and never constructs or executes a workload.

```python
from research_decision_engine import CandidateSpec, RunSpecV3

workload_execution_count = 0

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
    adapter_id="guide.recorded-workload",
    adapter_version="1",
    objective_name="score",
    objective_direction="maximize",
)

canonical = run_spec.to_canonical_bytes()
round_tripped = RunSpecV3.from_canonical_bytes(canonical)

assert run_spec.schema == "rde-core-run-spec/v3"
assert canonical.endswith(b"\n")
assert round_tripped.to_canonical_bytes() == canonical
assert round_tripped.fingerprint() == run_spec.fingerprint()
assert RunSpecV3.from_canonical_bytes(canonical).fingerprint() == run_spec.fingerprint()

changed = RunSpecV3(
    candidates=candidates,
    policy_id="random",
    policy_config={},
    policy_seed=18,
    experiment_count_budget=2,
    cost_budget=1.0,
    adapter_id="guide.recorded-workload",
    adapter_version="1",
    objective_name="score",
    objective_direction="maximize",
)

assert changed.fingerprint() != run_spec.fingerprint()
assert workload_execution_count == 0

print(f"Schema: {run_spec.schema}")
print(f"Fingerprint: {run_spec.fingerprint()}")
print(f"Changed fingerprint: {changed.fingerprint()}")
print("Canonical round trip: PASS")
print(f"Workload executions: {workload_execution_count}")
```

The fingerprint identifies the declared decision input. It is not a signature,
encryption, confidentiality mechanism, scientific-validity finding, or RDE
Assurance approval.
