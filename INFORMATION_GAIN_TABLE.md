# Generic finite-table information gain

RDE Core exposes `information_gain_table` only through RunSpec v3 and RunBundle
v3. RunSpec v1 remains random-only. RunSpec v2 remains limited to `random` and
`greedy_prior`. A v1 or v2 decoder never upgrades an artifact and rejects the v3
policy.

This policy is not Bayesian optimization. It does not predict objective quality,
fit a model, learn likelihoods, inspect unselected outcomes, or establish
scientific truth. It selects the next candidate that has the greatest expected
Shannon information gain under one complete likelihood table declared by the
user before the run.

## FiniteTableEvidenceModel

`FiniteTableEvidenceModel` is immutable and contains no callable or benchmark
truth. Its canonical payload has exactly these fields:

- `hypothesis_ids`: a nonempty ordered set of unique nonempty strings;
- `prior_weight_by_hypothesis`: one positive integer per hypothesis;
- `observation_metric`: the single normalized metric used for classification;
- `outcome_ids`: at least two ordered unique outcome labels;
- `outcome_thresholds`: one fewer finite, strictly increasing threshold;
- `likelihood_row_total`: one positive integer shared by every row;
- `likelihood_weight_by_candidate_id`: the complete candidate x hypothesis x
  outcome table of nonnegative integer weights.

The candidate keys must exactly match the enclosing RunSpec v3 candidates. Each
hypothesis row must name every outcome and sum to `likelihood_row_total`.
Mappings are copied and recursively frozen. Integer inputs and intermediate
belief weights are protected by the documented implementation bit-length safety
bound; arithmetic inside that bound is exact and is not truncated to 64 bits.

The evidence-model fingerprint is the lowercase SHA-256 digest of its canonical
sorted-key compact UTF-8 JSON bytes with one final LF. It binds the complete
table, hypothesis and outcome order, prior, thresholds, metric, and row total.

For thresholds `t[0] ... t[n-2]`, classification is:

```text
outcome[0]      metric < t[0]
outcome[i]      t[i-1] <= metric < t[i]
outcome[n-1]    metric >= t[n-2]
```

The named metric must be present exactly once and be a finite, non-Boolean
number. RunSpec v3 requires the model's `observation_metric` to equal the
RunSpec's `objective.name`, which makes the existing scalar
`NormalizedObservation.objective_value` unambiguous without changing v1 or v2.

## Exact belief identity

The authoritative belief is an ordered tuple of nonnegative Python integers
aligned with `hypothesis_ids`. Initial weights are the declared prior weights.
For candidate `c`, classified outcome `o`, and hypothesis `h`:

```text
next[h] = current[h] * likelihood[c][h][o]
```

An all-zero result is impossible evidence and fails closed. Otherwise all values
are divided by their greatest common divisor. No binary floating-point posterior
is persisted as identity. The belief fingerprint binds the belief schema,
ordered hypothesis IDs, and exact integer weights.

Every completed `information_gain_table` step records one immutable lineage
entry containing the step index, candidate, classified outcome, weights before
and after, and both belief fingerprints. Random and greedy-prior steps retain an
empty lineage.

## Deterministic numeric contract

Candidate scoring uses only the current exact weights and the fixed table. Ratios
are converted inside a fresh, fully specified `decimal.Decimal` context with
precision 50 and `ROUND_HALF_EVEN`; ambient precision, exponent limits, flags,
and traps are not inherited. Entropy uses `Decimal.ln`; conversion to bits divides by
`Decimal(2).ln()`. Expected information gain is current entropy minus the
outcome-probability-weighted posterior entropy.

Only the final score is quantized, to `Decimal("1e-30")` with
`ROUND_HALF_EVEN`. Quantized scores are compared directly without epsilon or
random perturbation. An exact tie selects the earliest eligible RunSpec
candidate. The selected score is serialized in fixed-point form with exactly 30
fractional digits.

## RunSpec v3 and replay

RunSpec v3 supports exactly:

| Policy | Configuration | Seed |
| --- | --- | --- |
| `random` | empty object | required integer |
| `greedy_prior` | complete utility map plus `runspec_candidate_order` | null |
| `information_gain_table` | complete evidence-model payload plus `runspec_candidate_order` | null |

Random and greedy-prior retain their v2 selection semantics. The schema identity
is the only version-level difference for those policies.

RunBundle v3 retains the two-file canonical layout, section hashes, 65-byte
sidecar, atomic no-replace export, strict read-only verification, and tamper
detection. `RECORDED_OBSERVATION_DECISION_REPLAY_V3` reconstructs one of the
three policies through a finite static mapping. It cannot load a module, class,
entry point, scorer, likelihood callable, source file, or registry URL.

Replay uses only the embedded RunSpec and recorded observations. It recomputes
candidate selection, the information-gain score, outcome classification, exact
integer lineage, cumulative cost, section hashes, and terminal summary into a
new empty-directory SQLite database. It never invokes `PythonFunctionAdapter`,
`CommandAdapter`, a callable workload, or an external command.

SQLite schema 6 remains sufficient: the RunSpec fingerprint binds the full
model and all semantic orders, while the workload table preserves ordered
candidate observations and costs. Resume replays this prefix and verifies the
RunSpec and evidence-model fingerprints before any remaining adapter execution.

## Compression demonstration model

The real CPU compression example uses the unchanged committed corpus and 24
gzip, bz2, and lzma candidates. Its ordered hypotheses are `gzip_dominant`,
`bz2_dominant`, and `lzma_dominant`, each with prior weight 1. It classifies
`compression_ratio` as `low`, `medium`, or `high` at thresholds 2.0 and 3.0.
Every likelihood row totals 20. A candidate matching a hypothesis codec uses
weights `(1, 5, 14)`; a nonmatching candidate uses `(10, 7, 3)`.

This table is a project-authored demonstration prior. It is not fitted from the
example observations and is not scientifically calibrated. Descriptive outcomes
from random, greedy-prior, and finite-table information gain do not establish
that any policy is generally superior.
