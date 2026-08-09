# Frozen Divergence-Mechanism Audit

Status: design only  
Audit version: `divergence-mechanism-audit/v1`  
Input evaluation: `closed-loop-belief-control-evaluation/v1`  
Frozen population: all 189 divergent fixed-versus-calibrated run pairs  
Proposed output directory: `divergence-audit-v1-189-cases`

This document freezes a read-only mechanism audit. It does not authorize a policy,
belief-model, likelihood, planner, benchmark, budget, trajectory, or acceptance-gate
change. The scientific result may be that no stable mechanism explains the observed
harm. That result is preferable to assigning a convenient post hoc story.

The completed closed-loop evaluation is the immutable study population. It contains
3,200 primary runs and 1,600 fixed-versus-calibrated pairs. Exactly 189 pairs diverged;
the existing evaluator-only outcome labels are 68 helped, 118 hurt, and 3 mixed. All 189
first divergences occurred at decision step 1 under `lookahead_information_gain`. These
facts define audit coverage but do not enter truth-free mechanism classification.

## 1. Unit of Analysis

One divergence case is exactly one fixed/calibrated pair sharing:

```text
(evaluation_version,
 world_id,
 evaluation_seed,
 budget_label,
 policy,
 public candidate-set commitment,
 public initial-condition fingerprint,
 potential-outcome oracle version)
```

The fixed member uses `fixed_sigma_gaussian`; the calibrated member uses
`replicated_noise_calibrated_gaussian`. The pair must have a non-null
`first_divergence_step` in `divergence_events.jsonl`. The stable audit case ID is a
versioned SHA-256 digest of the audit version, both run IDs, and the original divergence
ID. No pair is sampled, dropped, duplicated, or weighted according to its final outcome.

The inclusion audit must reproduce exactly 189 cases and these frozen condition counts:

- 84 in `adverse_noisy_observations`;
- 55 in `asymmetric_experiment_costs`;
- 50 in `no_optimizer_advantage`;
- 0 in `delayed_information`;
- 95 under the large budget and 94 under the short budget; and
- 189 under `lookahead_information_gain`, with no divergent `information_gain` case.

These are completeness assertions, not subgroup hypotheses or permission to omit empty
conditions.

For each case, the audit reconstructs and records the following before any truth label is
joined:

| Concern | Required record |
| --- | --- |
| Pair identity | Both run, arm, lineage, belief-model, policy, world, seed, budget, commitment, and divergence IDs. |
| Divergence point | First divergence step, common-prefix length, both decision-trace IDs, and whether either arm stopped. |
| Public history | Ordered real experiment IDs and candidate specifications through the shared prefix, public designs, observations already earned by both arms, evidence IDs, consumed-pair state, cumulative cost, and completed-state fingerprint. |
| Beliefs | Both pre-divergence belief-state IDs, parent lineage, posterior probabilities, entropy, evidence sequence, and update provenance. |
| Prediction model | Every comparison-group snapshot ID, model/version, estimated sigma, sigma status, source-effect IDs, hypothesis means, and prediction version. |
| Candidate state | Identical feasible first-candidate set, public designs, intervention arms, comparison groups, controlled-variable fingerprints, costs, and candidate-set fingerprint. |
| Scores | Every candidate's immediate EIG, delayed EIG, total two-step EIG, expected terminal entropy, expected total cost, EIG per expected cost, branch feasibility, ranking tuple, rank, and ranking reason under both active controllers. |
| Selected action | Both selected candidate IDs, action effects, comparison groups, costs, scores, and tie-breaking stage. |
| Subsequent sequence | Every later real selected candidate, pair opening/completion, real evidence update, model-specific sigma, posterior, cost, stop reason, and final selected set. |
| Truth-free final state | Final posterior, entropy, commitment timing, evidence count, matched-pair count, decision cost, calibration cost, required total cost, and budget exhaustion. |

Only after the truth-free case record and its SHA-256 are frozen may evaluator fields be
joined to add final NLL, Brier score, true-hypothesis probability, correctness,
confidently-wrong status, threshold correctness, best objective, and the existing
`helped`, `hurt`, `mixed`, or `tied` label.

The audit is observational. A mechanism label means that a predeclared structural or
numerical pattern is present in the recorded case. It is not automatically a causal
claim about what would have happened under an unexecuted action.

## 2. Frozen Mechanism Taxonomy

The taxonomy is frozen to the twelve labels below. No implementation may add, rename,
split, or merge a label after evaluator outcomes are joined.

The numerical comparison tolerance is exactly:

```text
tau = 1e-12
```

This is the existing positive-information and comparison tolerance. "Tied" or "nearly
tied" means absolute difference at most `tau`; no empirical percentile or result-aware
threshold is allowed.

### Decision-score mechanisms

**SCORE_FLATTENING**

The calibrated sigma schedule compresses the range of feasible first-action total-EIG
scores and participates in changing the winner. The predicate is true only when:

```text
score_range_calibrated < score_range_fixed - tau
and a sigma-only crossed replay changes the winner
```

where score range is `max(total_EIG) - min(total_EIG)` over the identical feasible
first-action set. Compression without a winner change is recorded as a diagnostic, not
this mechanism.

**BELIEF_STATE_REORDERING**

Changing only the posterior from the fixed state to the calibrated state, while holding
the complete fixed group-sigma schedule constant, changes the first-action winner. If a
sigma-only replay does not change the winner, belief is the sole crossed-replay driver.
If belief and sigma can each change the winner, both are contributing mechanisms and the
larger absolute Shapley margin contribution determines the primary numerical mechanism;
an exact tie uses the frozen label order in this section.

**GROUP_SIGMA_REORDERING**

Changing only the group-specific sigma schedule from fixed to calibrated, while holding
the posterior constant, changes the winner, and the `SCORE_FLATTENING` predicate is
false. This separates relative reordering caused by unequal comparison-group sigmas from
global score compression.

**BELIEF_SIGMA_INTERACTION**

The active fixed and calibrated contexts select different winners, but neither a
belief-only nor a sigma-only crossed replay changes the fixed winner. The joint crossed
context does. The non-additive interaction term must exceed `tau` in absolute value.

**COST_TIEBREAK_CHANGE**

At least one active controller has two or more leading first actions whose total EIGs
are within `tau`, and the recorded winner is resolved at a later frozen ranking stage:

1. lower expected total cost;
2. greater total EIG per expected cost; or
3. stable lexicographic candidate ID.

The output names the exact stage. A mere difference in cost is not this mechanism when
total EIG already determines the winner.

### Experimental-sequence mechanisms

**PAIR_COMPLETION_DELAY**

At the shared pre-divergence state, at least one valid matched pair is open. The fixed
action completes an open pair, while the calibrated action does not complete that same
pair. The calibrated trajectory completes it at a later real step or never completes it.
The delay is measured in experiment steps and decision cost. No outcome value is used.

**PAIR_OPENER_CHANGE**

Both divergent first actions have public effect `opens_pair`, and their public
comparison-group IDs differ. The two groups must be distinguished solely by experiment
family, controlled-variable fingerprint, intervention variable, and intervention arm.

**SAME_SET_DIFFERENT_ORDER**

The two final selected-candidate sets are exactly equal, but their ordered candidate-ID
sequences differ. The record also states whether evidence order, per-update sigma source
sets, or commitment timing differs. Set equality alone does not imply equivalent
scientific updates because the calibrated estimator is prequential.

**BUDGET_CROWD_OUT**

A truth-free, structurally informative candidate or pair that appears in the fixed final
set is absent from the calibrated final set, was feasible in the shared pre-divergence
state, and becomes infeasible in every later calibrated recorded state because its cost
exceeds remaining budget. "Structurally informative" means that the candidate completes
an already-open valid pair, or that it and its public complement jointly fit before the
divergence but no longer jointly fit afterward. This establishes a budget-path
association; it does not assert that an unexecuted candidate would have produced helpful
evidence.

**CONSERVATIVE_NONCOMMITMENT**

Using only posterior traces, the fixed arm reaches top-hypothesis probability at least
`0.80` earlier than the calibrated arm, and the calibrated arm either reaches it later or
ends below `0.80`. Correctness is deliberately absent from this predicate. Evaluator
truth later determines whether delayed or avoided commitment helped or hurt.

### Validity and residual mechanisms

**PLANNER_MODEL_MISMATCH**

One or more compatibility checks in Section 9 fail for the case: active posterior,
group sigma, branch outcome probabilities, hypothetical posterior, EIG, expected cost,
ranking, or explanation cannot be reproduced from the recorded model and frozen
algorithm. A mismatch is an audit finding, not permission to repair the result.

**NO_STABLE_MECHANISM**

Every preceding predicate is false after a complete, reproducible decomposition. The
case record must include the false predicate and evidence for every excluded category.
Missing or corrupt required data is an audit failure, not `NO_STABLE_MECHANISM`.

### Primary and contributing labels

Every case has exactly one `primary_mechanism` and zero or more
`contributing_mechanisms`. All true predicates are retained. The primary label is chosen
without evaluator truth by this deterministic precedence:

1. `PLANNER_MODEL_MISMATCH`;
2. the numerical winner-changing mechanism among `SCORE_FLATTENING`,
   `BELIEF_STATE_REORDERING`, `GROUP_SIGMA_REORDERING`, and
   `BELIEF_SIGMA_INTERACTION`, using the crossed-replay rules above;
3. `COST_TIEBREAK_CHANGE`;
4. `PAIR_COMPLETION_DELAY`;
5. `PAIR_OPENER_CHANGE`;
6. `BUDGET_CROWD_OUT`;
7. `SAME_SET_DIFFERENT_ORDER`;
8. `CONSERVATIVE_NONCOMMITMENT`; and
9. `NO_STABLE_MECHANISM`.

If both belief-only and sigma-only changes independently flip the winner, compare their
absolute Shapley contributions to the calibrated-winner-versus-fixed-winner margin.
Greater magnitude wins; equality within `tau` uses `SCORE_FLATTENING`, then
`BELIEF_STATE_REORDERING`, then `GROUP_SIGMA_REORDERING`. The non-primary true labels are
contributing mechanisms. Free-form notes may explain a case but can never create another
category.

For interpretation, the audit also reports two noncategorical axes:

- `winner_change_driver`: belief, sigma, joint interaction, ranking stage, or unresolved;
- `sequence_consequence`: same order, same set/different order, partial overlap, or
  disjoint sets.

These axes do not replace the frozen mechanism labels.

## 3. Truth-Safe Classification

Classification is a two-pass process with a hard serialization boundary.

### Pass A: operational mechanism classification

Pass A may read only:

- `run_manifest.json` and `protocol_snapshot.json` for versions, hashes, budgets, and
  frozen constants;
- `potential_outcome_commitments.jsonl` for commitment identity and hashes, never values;
- `decision_traces.jsonl` for recorded beliefs, snapshots, candidates, scores, branches,
  feasibility, ranking, and explanation;
- `evidence_belief_traces.jsonl` for earned real experiments, evidence, updates,
  posterior traces, sigma estimates, and costs;
- `calibration_prefixes.jsonl` only at the sigma-provenance verifier boundary; and
- the public source modules whose hashes are frozen in the input manifest.

Pass A must not open or import:

- `potential_outcomes.jsonl`;
- evaluator-only blocks from `per_run_results.jsonl` or `per_run_results.csv`;
- truth columns from `threshold_results.csv`;
- `failure_cases.jsonl`;
- hidden world configuration fields;
- final NLL, Brier, correctness, true-hypothesis probability, confidently-wrong labels,
  or the existing helped/hurt label.

The classifier writes a truth-free case record, a per-case score-decomposition hash, and
one complete canonical truth-free staging stream. The stream is closed and hashed before
Pass B starts. It is an ephemeral audit workspace file, not an additional published
artifact. The implementation must expose separate data types and functions for Pass A;
an evaluator label must be structurally unrepresentable in a classifier input.

### Pass B: evaluator labeling and summaries

Pass B joins by immutable run and divergence IDs. It may read:

- the existing evaluator-only block in `divergence_events.jsonl`;
- final truth-dependent metrics from `per_run_results.jsonl` and
  `threshold_results.csv`; and
- the frozen `correctness_effect` definition already used by the closed-loop evaluation.

Pass B cannot alter any Pass-A mechanism field. It appends only evaluator fields and
summary strata. The manifest records the staging-stream hash and the hash obtained by
extracting the truth-free payloads from final `divergence_cases.jsonl`; the hashes must
match. The staging stream is then removed so that Section 11 remains the exact published
artifact set.

The evaluator-only fields are exactly:

- hidden true hypothesis;
- true optimizer effect and benchmark observation noise, when included for descriptive
  world labeling;
- final NLL and Brier score;
- final true-hypothesis probability and rank;
- prediction correctness and confidently-wrong status;
- correct sustained `0.80` and `0.95` crossings and their costs;
- best observed objective when used as the frozen secondary metric; and
- `helped`, `hurt`, `mixed`, or `tied` outcome label.

Truth-dependent fields may describe whether a truth-free mechanism was beneficial. They
may not determine whether the mechanism occurred or whether it is primary.

## 4. Score Decomposition

The decomposition uses the exact shared public state immediately before the first
divergent decision. The common-prefix audit must prove identical earned observations,
completed candidate designs, public eligibility state, candidate set, costs, budget, and
oracle commitment. Fixed and calibrated belief states and sigma snapshots may differ.

For every feasible first candidate `c`, record:

```text
I0(c) = immediate information gain
I2(c) = expected total two-step information gain
ID(c) = I2(c) - I0(c)               # delayed/future contribution
T(c)  = expected terminal entropy
C(c)  = expected total cost
R(c)  = I2(c) / C(c), or 0 under the frozen implementation rule
```

The active first-action ranking remains exactly:

```text
greater I2,
then lower C,
then greater R,
then lexicographically smaller candidate ID.
```

Cost is not subtracted from EIG. The audit must preserve this lexicographic semantics and
must not reinterpret `R` as the primary utility.

### Four crossed score contexts

Let `bF` and `bC` be the recorded fixed and calibrated posteriors. Let `sF(g)` and
`sC(g)` be the recorded fixed and calibrated sigma for public comparison group `g`.
Using the same public history, candidate set, cost map, eligibility contract, grid, and
budget, recompute all candidates under:

| Context | Posterior | Group-sigma schedule |
| --- | --- | --- |
| `FF` | `bF` | `sF` |
| `CF` | `bC` | `sF` |
| `FC` | `bF` | `sC` |
| `CC` | `bC` | `sC` |

`FF` must reproduce the stored fixed ranking and `CC` the stored calibrated ranking.
`CF` and `FC` are score-only diagnostic crossings. They do not execute a candidate,
generate an observation, update a belief, or create a new trajectory.

For the fixed winner `f` and calibrated winner `c`, define the total-EIG ranking margin
in context `XY` as:

```text
m_XY = I2_XY(c) - I2_XY(f)
```

The two-factor Shapley decomposition is:

```text
belief_contribution
  = 0.5 * ((m_CF - m_FF) + (m_CC - m_FC))

sigma_contribution
  = 0.5 * ((m_FC - m_FF) + (m_CC - m_CF))

belief_sigma_interaction
  = m_CC - m_CF - m_FC + m_FF
```

The two Shapley contributions must sum to `m_CC - m_FF` within `tau`. The raw
interaction is reported because Shapley allocation otherwise hides non-additivity.

### Temporal, cost, feasibility, and tie components

For each context, decompose the candidate-pair margin into:

```text
immediate_margin_XY = I0_XY(c) - I0_XY(f)
future_margin_XY    = ID_XY(c) - ID_XY(f)
total_margin_XY     = immediate_margin_XY + future_margin_XY
```

The change from `FF` to `CC` in immediate and future margins must sum to the total-margin
change. This identifies whether an immediate evidence branch or contingent second-step
value changed the ranking.

Cost contribution is recorded separately as the fixed and calibrated differences in
first cost, expected total cost, and EIG per expected cost. The audit identifies the
first lexicographic ranking stage that distinguishes `f` and `c` in each context.

Budget-feasibility contribution records, for every candidate and every retained branch:

- first-action feasibility under remaining budget;
- feasible second-action IDs;
- branch total cost and hard-budget result;
- whether `STOP` was selected;
- candidates removed only by cost, duplicate, consumed-pair, or structural rules; and
- whether fixed and calibrated winner sets differ before scoring.

Because public state and costs must be identical at first divergence, a difference in
first-action feasibility is a hard audit failure. Branch-specific second choices may
differ because their predictive posteriors differ.

Tie contribution records exact equality within `tau`, the winning stage, and the stable
candidate-ID ordering. The stored ranking reason must agree with the recomputed stage.

The scorer must reproduce every stored candidate aggregate and selected branch within
`tau`, every branch probability and posterior within `1e-12`, and every winner exactly.
It then recomputes losing-candidate branch trees from frozen inputs because the current
artifact stores their aggregate scores but not their full branch trees. Reconstructed
branches are audit calculations and are written only to `score_decomposition.csv`.

## 5. Sequence Analysis

For each arm, the audit reconstructs an ordered event ledger:

```text
decision -> selected experiment -> earned observation -> pair state
         -> optional evidence -> optional belief update -> cost debit
```

For every real step, it records candidate ID, comparison group, intervention arm,
controlled-variable fingerprint, action effect, experiment cost, cumulative cost,
remaining budget, new evidence IDs, posterior, posterior entropy, sigma estimate, and
commitment state.

The sequence comparison must report:

- both complete selected-candidate sequences;
- pair opening and completion step for every public comparison group;
- first real evidence step and cumulative decision cost, or explicit `none`;
- number and order of real evidence updates;
- cost before first evidence;
- remaining decision budget immediately after first evidence;
- final candidate sets and their intersection and union;
- matched-pair count, redundant selection count, stop reason, and budget exhaustion; and
- per-evidence sigma schedule and exact prior source-effect IDs.

Final-set relation is exactly one of:

- `SAME_SET_DIFFERENT_ORDER`: sets equal and sequences differ;
- `PARTIAL_OVERLAP`: intersection nonempty and sets unequal; or
- `DISJOINT`: intersection empty.

The frozen completeness check expects 90 same-set/different-order cases, 5 partial
overlaps, and 94 disjoint sets. These counts verify extraction only; they are not
mechanism assignments.

For same-set cases, evidence events are matched by public comparison-group structure and
source candidate designs, not arm-local experiment IDs. The audit records whether the
same observed matched effects were applied in a different order, whether each effect saw
a different strictly-prior sigma source set, and whether final posteriors differ. This is
an order-sensitivity association, not a replay under a reordered trajectory.

## 6. Counterfactual Replay Restrictions

The audit may perform only deterministic score replay at a recorded predecision state.
Allowed operations are:

- reconstruct the recorded public candidate and completed-history objects;
- substitute the recorded `bF` or `bC` posterior and recorded `sF` or `sC` group-sigma
  schedule into the existing pure Gaussian EIG and two-step scoring kernels;
- recompute branch probabilities, temporary posteriors, branch-contingent second-action
  scores, aggregate EIG, costs, and the frozen ranking tuple; and
- verify stored explanations and provenance.

The audit must not:

- query, enumerate, or deserialize an unselected potential outcome;
- call the selected-only observation oracle;
- generate a new random draw or observation;
- replace a recorded action and continue the runner;
- derive evidence from a hypothetical experiment;
- persist a hypothetical belief, update, experiment, evidence item, or cost;
- change sigma, a posterior, budget, candidate, world, policy, utility, tolerance, grid,
  or tie rule outside the four recorded crossed contexts;
- optimize, tune, or fit any parameter; or
- overwrite any closed-loop artifact.

`CF` and `FC` answer which recorded input component changes a score at one frozen state.
They do not answer what later observations or outcomes would have occurred. Statements
such as "budget crowd-out is associated with losing a feasible evidence path" are
permitted. Statements such as "the omitted experiment would have corrected the belief"
require an intervention and are prohibited.

## 7. Required Summaries

All summaries use the complete 189-case population. Counts always include an explicit
denominator. Primary-mechanism summaries form a partition; any-role summaries may
overlap because contributing mechanisms are retained. Empty condition cells are emitted
with count zero rather than omitted.

The audit must produce these predeclared views:

1. primary- and any-role mechanism count and proportion among all cases;
2. the same mechanism frequencies separately among the evaluator-labeled `helped`,
   `hurt`, and `mixed` cases;
3. mechanism frequencies by world, budget label, and policy, including the empty
   `information_gain` and `delayed_information` divergence cells;
4. mean and median paired change, calibrated minus fixed, in NLL, Brier score,
   true-hypothesis probability, posterior entropy, confidently-wrong indicator,
   correct-confidence threshold indicators, matched pairs, and redundant selections;
5. mean and median paired change in decision cost, calibration cost, and required total
   cost by mechanism;
6. first-divergence-step count and proportion; and
7. final candidate-set relation, Jaccard overlap, common-prefix length, and sequence
   edit distance overall and by mechanism.

Best observed objective is reported in a separate, explicitly secondary column. It is
never combined with the scientific metrics or used to assign a mechanism.

For uncertainty summaries, the unit of resampling is the evaluation seed, not an
individual case. A deterministic paired block bootstrap draws 100 seed blocks with
replacement, retaining every eligible case and both arms for each drawn seed. It uses
10,000 replicates, master seed `20260710`, and metric-specific keyed substreams formed
from the master seed, artifact name, condition key, mechanism, and metric. The 95%
interval is the percentile interval from the 2.5th and 97.5th percentiles. The point
estimate always comes from the original complete population. If a bootstrap replicate
has no observation for a requested subgroup, that replicate is excluded for that cell;
the number of usable replicates is reported. Cells with fewer than 50 usable replicates
receive no interval and are marked `insufficient_resamples`. No p-value or statistical-
significance claim is produced.

## 8. Harm Concentration Analysis

The harm analysis starts with all 118 evaluator-labeled harmful divergences. It must not
filter cases by a mechanism discovered after joining outcomes. Concentration is assessed
against all 189 divergent cases, not against all 1,600 paired runs; therefore its scope
is explicitly conditional on divergence.

Categorical strata are frozen as:

- world, budget, and policy;
- fixed and calibrated first-action public effect: opens pair, completes pair, or
  neither;
- matched-pair state before divergence: no open pair, one open pair, or multiple open
  pairs;
- near-budget exhaustion, defined as remaining decision budget at most 25% of the
  original decision budget;
- structural budget pressure, defined as no evidence-producing action or complete
  public opener-plus-complement sequence fitting the remaining budget;
- final set relation: same set/different order, partial overlap, or disjoint; and
- every primary mechanism and every any-role mechanism.

Continuous strata use only these frozen bins:

| Quantity | Frozen bins |
| --- | --- |
| Active calibrated sigma ratio, `sigma / 0.05` | `[1, 2)`, `[2, 4)`, `[4, 8)`, `[8, infinity)` |
| Calibrated pre-divergence entropy in bits | `[0, 0.25)`, `[0.25, 0.75)`, `[0.75, 1.25)`, `[1.25, log2(3) + tau]` |
| Remaining-budget fraction | `[0, 0.25]`, `(0.25, 0.50]`, `(0.50, 0.75]`, `(0.75, 1.00]` |

When a decision uses several comparison-group sigmas, the sigma stratum is based on the
selected calibrated candidate's group sigma; the full group-sigma vector remains in the
case record. No data-dependent bin is permitted.

For every stratum, report:

- `divergent_count` and `harm_count`;
- harmful-case share: harms in the stratum divided by 118;
- conditional harm rate: harms in the stratum divided by divergent cases in the
  stratum;
- concentration lift: harmful-case share divided by the stratum's share of all 189
  divergences;
- risk difference in harm rate versus the complement; and
- risk ratio versus the complement.

The seed-block bootstrap in Section 7 supplies 95% intervals for harmful-case share,
conditional harm rate, lift, risk difference, and risk ratio. A zero denominator yields
`undefined`; no continuity correction or pseudocount is added. Continuous quantities
also receive truth-safe pre-outcome distribution summaries and evaluator-stage mean and
median differences between harmful and nonharmful divergent cases. This analysis is
descriptive and multiplicity-aware: it reports all predeclared cells and makes no
confirmatory significance claim.

## 9. Planner-Belief Compatibility Audit

Compatibility is checked for every real decision in both arms of all 189 cases, not only
the first divergent decision. Every feasible first candidate and every stored selected-
plan branch is checked. Losing-candidate branch trees may be reconstructed only through
the frozen score replay allowed in Section 6.

The divergence population contains no `information_gain` case. To audit that required
code path rather than infer from an empty cell, the compatibility audit also checks every
recorded decision from the 1,600 fixed and calibrated `information_gain` arms in the
source evaluation. Those checks appear only in `planner_compatibility_audit.json`; they
do not enlarge the 189-case mechanism population or enter harm summaries.

The audit performs these exact checks:

1. **Lineage identity:** the policy input belief-state ID, model ID, lineage ID, and
   posterior equal the arm's latest real persisted state.
2. **Sigma provenance:** fixed snapshots use exactly `sigma = 0.05` with no calibration
   sources; calibrated snapshots reproduce the strictly-prior, group-local source IDs,
   sample count, Bessel-corrected sample standard deviation, floor, and final sigma.
3. **Prediction bundle:** hypothesis IDs, means, sigmas, comparison-group IDs, and
   prediction version in every candidate score equal the active snapshot.
4. **One-step scoring:** outcome-bin probabilities, branch posteriors, entropies, and EIG
   reproduce from the active posterior and candidate-group snapshot.
5. **Pair opener semantics:** a first action that only opens a pair has exactly one
   `NO_EVIDENCE_YET` branch, probability one, unchanged posterior, and zero immediate
   EIG.
6. **Pair completion semantics:** a completing action uses the active model's Gaussian
   evidence distribution, normalized branch probabilities, and model-specific temporary
   posterior in every branch.
7. **Conditional second step:** each branch's second action is selected from that
   branch's feasible public state and uses that second action's comparison-group sigma,
   not the first action's sigma or a fixed default.
8. **Hypothetical lineage:** temporary posteriors retain the active hypothesis order and
   model semantics, normalize within `tau`, and are absent from real belief, evidence,
   and experiment persistence.
9. **Plan aggregation:** expected terminal entropy, immediate and delayed EIG, expected
   total EIG, expected cost, and EIG per expected cost reproduce within `tau`.
10. **Budget semantics:** every branch remains within the recorded hard remaining
    budget; `STOP` appears exactly when no positive-EIG feasible second action is chosen.
11. **Ranking and explanation:** the recorded winner, ranking reasons, alternatives,
    and prose rationale agree with greater EIG, lower cost, greater EIG per cost, and
    lexicographic ID in that exact order.
12. **Fixed-arm regression:** fixed-model scores reproduce the previously recorded
    fixed traces byte-for-byte after canonical serialization where the artifact contract
    requires exact equality.
13. **Embedded-assumption scan:** static and dynamic call-path inspection finds no
    planner component that substitutes `0.05`, a fixed-model posterior, or another
    group's sigma while scoring a calibrated arm.

Each check emits `PASS` or `FAIL`, checked record IDs, expected and observed canonical
values, maximum absolute numerical error, and source-code symbol and hash. A single
failure marks the affected case with `PLANNER_MODEL_MISMATCH`; it is reported, not
repaired. Missing evidence needed for a check is an audit failure rather than an implied
pass.

## 10. Acceptance Criteria for the Audit

The audit is accepted only when all of these conditions hold:

1. exactly 189 unique paired cases are present and the frozen world, budget, policy, set-
   overlap, and outcome-label counts reconcile with the source artifacts;
2. every case has exactly one primary mechanism and complete truth-free machine-readable
   predicate evidence for all twelve labels;
3. every true contributing mechanism and every excluded predicate is retained;
4. the truth-free case payload is classified and hashed before evaluator-only fields are
   joined;
5. every active and crossed score decomposition reproduces its candidate ranking and
   every recorded active selected score within `tau`;
6. all planner-belief compatibility checks complete and every failure is surfaced as
   `PLANNER_MODEL_MISMATCH`;
7. two clean executions produce byte-identical canonical case classifications and
   summary values, excluding declared report-generation timestamps;
8. oracle access, potential-outcome enumeration, observation generation, trajectory
   mutation, and writes to experiment SQLite stores remain zero;
9. hashes of policy, belief-model, likelihood, benchmark, design, source evaluation, and
   pre-existing evaluation artifacts remain unchanged;
10. all ten output artifacts in Section 11 validate against their declared schemas and
    reconcile counts and costs; and
11. unresolved or unclassifiable cases are honestly assigned
    `NO_STABLE_MECHANISM` only after a complete decomposition.

Failure of any condition makes the audit `INCOMPLETE`. An incomplete audit must still
emit diagnostics, but it must not declare a dominant harmful mechanism or make an
algorithm-change recommendation.

## 11. Outputs

The audit writes exactly the following files into a new, versioned, non-overwriting
directory such as `divergence-audit-v1-189-cases/`:

| Artifact | Frozen contents |
| --- | --- |
| `divergence_manifest.json` | Audit and input versions, source and output hashes, repository revision, constants, allowlists, population reconciliation, run command, dependency versions, timestamp, schema versions, and acceptance status. |
| `divergence_cases.jsonl` | One canonical full case per line: truth-free payload and hash, evaluator-only payload, all mechanism predicates, primary and contributors, score references, sequence references, and audit status. |
| `divergence_cases.csv` | One flat row per case with identifiers, divergence state, primary/contributing labels, selected actions, overlap, final metric and cost deltas, evaluator label, and truth-safe hash. |
| `mechanism_summary.csv` | Primary and any-role frequencies overall and by helped/hurt/mixed label, scientific-metric deltas, cost deltas, and seed-block intervals. |
| `mechanism_by_condition.csv` | Complete mechanism grid by world, budget, policy, and evaluator outcome, including zero-count cells and denominators. |
| `score_decomposition.csv` | One row per case, context, and candidate pair with posterior and sigma inputs, crossed scores, immediate/delayed contributions, Shapley margins, feasibility, cost, ranking stage, and reproduction error. |
| `sequence_comparison.csv` | One row per case with both candidate sequences, pair events, first evidence, evidence order, sigma-source order, costs, overlap metrics, set relation, and stop reasons. |
| `harm_concentration.csv` | Every predeclared stratum, counts, harm share/rate, lift, risk difference/ratio, usable bootstrap replicates, and 95% intervals. |
| `planner_compatibility_audit.json` | Every Section 9 check, record coverage, canonical expected/observed values, numerical errors, source symbols and hashes, failures, and global PASS/FAIL. |
| `DIVERGENCE_AUDIT_REPORT.md` | Human-readable protocol, reconciliation, mechanism results, score and sequence findings, harm concentration, compatibility findings, limitations, audit acceptance, and exactly one next-milestone recommendation. |

JSON uses sorted keys and explicit schema/version fields. JSONL order is stable by world,
seed, budget, policy, and case ID. CSV uses a fixed documented column order and stable
row ordering. Floating-point serialization uses the repository's canonical round-trip
representation; display rounding is report-only. Timestamps may occur only in the
manifest and report metadata and are excluded from determinism hashes.

No SQLite schema addition is required. The audit reads immutable artifacts and writes
evaluation artifacts only. It must never edit or overwrite the source closed-loop or
robust-belief evaluation directories.

## 12. Final Decision Rule

The report must recommend exactly one next milestone. It first verifies audit acceptance
and then uses only the 118 evaluator-labeled harmful cases.

For each nonresidual mechanism, compute its any-role prevalence among harmful cases and
the paired seed-block bootstrap distribution of the prevalence difference from every
other mechanism. A mechanism is the **dominant measured harmful mechanism** only when:

```text
harmful-case prevalence >= 0.40
and the lower bound of its 95% interval versus the runner-up is > 0
```

The runner-up is the other mechanism with greatest harmful-case prevalence; ties use
the frozen taxonomy order. This dominance test is descriptive and predeclared, not a
claim that the mechanism caused harm. A planner compatibility failure overrides the
prevalence rule because the recorded controller would not match its declared algorithm.

The recommendation is selected by this exhaustive mapping:

| Audit result | Exactly one recommended milestone |
| --- | --- |
| Audit incomplete | Repair or reconstruct the divergence-audit instrumentation, then rerun the same frozen audit. |
| Any `PLANNER_MODEL_MISMATCH` | Correct the planner-belief compatibility defect and replay the unchanged frozen closed-loop protocol. |
| Dominant `BUDGET_CROWD_OUT` | Evaluate a predeclared cost-aware decision revision against the frozen controllers. |
| Dominant `CONSERVATIVE_NONCOMMITMENT` | Run a commitment-and-stopping study without changing the belief model. |
| Dominant `SCORE_FLATTENING` or `GROUP_SIGMA_REORDERING` | Run a calibrated-sigma acquisition-sensitivity study focused on candidate-score compression and group-relative ranking. |
| Dominant `BELIEF_STATE_REORDERING` | Run a posterior-sensitivity experiment-selection study. |
| Dominant `BELIEF_SIGMA_INTERACTION` | Run a joint belief-likelihood planner-compatibility study. |
| Dominant `PAIR_COMPLETION_DELAY` | Evaluate a predeclared matched-pair completion sequencing rule. |
| Dominant `PAIR_OPENER_CHANGE` | Evaluate comparison-group opener selection under the unchanged two-step horizon. |
| Dominant `SAME_SET_DIFFERENT_ORDER` | Run a prequential evidence-order sensitivity study. |
| Dominant `COST_TIEBREAK_CHANGE` | Run a deterministic tie-break robustness study. |
| No mechanism meets dominance, including dominant residual uncertainty | Replicate the closed-loop evaluation on a broader predeclared seed and world set before changing an algorithm. |

If more than one row appears applicable, the first applicable row in the table wins,
except that among dominant-mechanism rows only the single mechanism satisfying the
strict runner-up rule can apply. The report may discuss other findings but must contain
one and only one `recommended_next_milestone` value. It must not implement it.

## 13. Non-Goals

This milestone does not:

- modify a policy, planner, belief model, likelihood, sigma estimator, utility,
  planning horizon, tie-break, acceptance gate, budget, benchmark world, candidate set,
  oracle, or recorded trajectory;
- generate observations, new policy trajectories, interventions, or causal estimates;
- add a planner, abstention mechanism, unknown hypothesis, model-selection mechanism,
  PPO integration, LLM integration, web UI, cloud service, or production orchestration;
- tune thresholds, bins, bootstrap settings, mechanism predicates, or taxonomy labels
  after evaluator outcomes are joined;
- repair a discovered compatibility defect;
- use best objective as a substitute for scientific correctness; or
- claim that information gain, low entropy, or a mechanism association is scientific
  value or causation.

## 14. Final Design Review

### Frozen definitions and constants

The twelve mechanism labels are:

```text
SCORE_FLATTENING
BELIEF_STATE_REORDERING
GROUP_SIGMA_REORDERING
BELIEF_SIGMA_INTERACTION
COST_TIEBREAK_CHANGE
PAIR_COMPLETION_DELAY
PAIR_OPENER_CHANGE
SAME_SET_DIFFERENT_ORDER
BUDGET_CROWD_OUT
CONSERVATIVE_NONCOMMITMENT
PLANNER_MODEL_MISMATCH
NO_STABLE_MECHANISM
```

Their exact predicates and primary-label precedence are frozen in Section 2. The exact
classification flow is:

1. reconcile the 189 cases and reconstruct both arms from immutable artifacts;
2. build the Section 1 truth-free record from the Section 3 allowlist;
3. run all compatibility checks and four-context score decompositions;
4. evaluate all twelve predicates, retain every true predicate, and choose one primary
   label using Section 2 precedence;
5. canonicalize and hash the truth-free classification;
6. join evaluator-only outcomes and compute summaries and concentration statistics;
7. verify acceptance criteria; and
8. apply the Section 12 rule once to emit exactly one recommendation.

| Constant | Frozen value |
| --- | --- |
| Audit version | `divergence-mechanism-audit/v1` |
| Input evaluation | `closed-loop-belief-control-evaluation/v1` |
| Case population | 189 divergent pairs |
| Harm population | 118 evaluator-labeled harmful pairs |
| Numerical tolerance `tau` | `1e-12` |
| Commitment threshold | `0.80` top-hypothesis probability |
| Fixed sigma | `0.05` |
| Bootstrap unit | Evaluation seed block |
| Bootstrap replicates | 10,000 |
| Bootstrap master seed | `20260710` |
| Confidence interval | 2.5th/97.5th percentile, 95% |
| Minimum usable bootstrap replicates | 50 |
| Near-budget threshold | Remaining budget at most 25% of original decision budget |
| Dominance prevalence | At least 0.40 of harmful cases |
| Dominance separation | Lower 95% bound versus runner-up greater than 0 |
| Sigma-ratio bins | `[1,2)`, `[2,4)`, `[4,8)`, `[8,infinity)` |
| Entropy bins, bits | `[0,.25)`, `[.25,.75)`, `[.75,1.25)`, `[1.25,log2(3)+tau]` |

### Evaluator-only fields

The following fields are forbidden until the truth-free payload and classification hash
are finalized:

- hidden true hypothesis and hidden world effect parameters;
- evaluator truth labels and expected objective surfaces;
- true-hypothesis rank and probability;
- NLL, Brier score, calibration error, correctness, and confidently-wrong indicator;
- correct-confidence threshold success and cost;
- helped, hurt, mixed, or tied divergence outcome;
- evaluator-only best-objective comparison; and
- any unselected or counterfactual potential outcome.

### Remaining unresolved questions

No unresolved question may alter the population, taxonomy, predicates, precedence,
inputs, crossed replay, summaries, bins, uncertainty method, compatibility checks,
acceptance criteria, or recommendation rule after outcomes are inspected. The remaining
engineering questions are non-scientific and have frozen defaults:

- **Streaming implementation:** process the large decision-trace JSONL in stable case
  order rather than loading it wholly into memory.
- **Canonical schema location:** define schemas beside the audit implementation and
  record their SHA-256 hashes in the manifest.
- **Report rendering:** generate Markdown directly from machine-readable summaries;
  formatting must not feed back into calculations.

### Implementation blockers

There is no scientific-design blocker. The repository records selected-plan branch trees
and sufficient public state to reproduce active scores. Losing-candidate branches are
not all persisted in full, so implementation requires a read-only adapter over the
existing pure scoring kernels to reconstruct them under the four allowed crossed
contexts. That adapter must expose no oracle or persistence capability and must pass the
Section 9 fixed-arm regression checks before classification. This is an engineering
prerequisite, not permission to modify planner or belief-model behavior.

Implementation must also stream the roughly 220 MB decision-trace artifact, preserve all
source artifact hashes, and write only the ten versioned files in Section 11. No new
dependency, database migration, policy change, or design-document change is required.
