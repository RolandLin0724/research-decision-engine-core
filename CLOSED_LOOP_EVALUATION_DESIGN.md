# Closed-Loop Belief-Control Evaluation

Status: predeclared design only  
Evaluation version: `closed-loop-belief-control-evaluation/v1`  
Primary comparison: calibrated minus fixed within an unchanged decision policy

This document freezes a closed-loop evaluation of the accepted
`replicated_noise_calibrated_gaussian` belief model. It does not authorize a new
belief model, likelihood family, policy, planner, world, or planning horizon. The
evaluation changes only which existing belief lineage supplies the posterior and
prediction model used by an existing policy.

The completed robust-belief evaluation was a shadow replay. A fixed-sigma lineage
controlled every real experiment, and both belief models interpreted the same evidence
afterward. That design isolated likelihood adequacy and showed materially better NLL,
Brier score, calibration, and confidently-wrong behavior under adverse noise. It did not
test whether calibrated beliefs cause different experiments to be selected or whether
any resulting benefit justifies the calibration cost.

## 1. Research Question And Frozen Algorithms

### Research question

The precise research question is:

> Does allowing the accepted replicated-noise-calibrated belief lineage to control the
> existing information-gain and two-step lookahead policies improve end-to-end scientific
> correctness and efficiency after calibration cost is included?

The primary hypothesis is that calibrated control reduces confidently wrong conclusions
and proper-scoring-rule loss in the adverse-noise world, while preserving scientific
correctness in delayed-information worlds and avoiding an unacceptable increase in real
decision cost.

The null hypothesis is that calibrated control offers no reproducible closed-loop
advantage. Differences may be zero, adverse, too costly, caused by trajectory divergence,
or too uncertain to support promotion. A result in which calibration improves correctness
but fails calibration-inclusive efficiency is a negative result for end-to-end promotion,
not a reason to alter the gates.

### Frozen algorithms

The following algorithms and semantics are immutable for this evaluation:

| Component | Frozen identity or behavior |
| --- | --- |
| Fixed belief model | `fixed_sigma_gaussian`, version `fixed-sigma-gaussian/v1`, `sigma = 0.05` |
| Calibrated belief model | `replicated_noise_calibrated_gaussian`, version `replicated-noise-calibrated-gaussian/v1` |
| Calibrated estimator | Ordinary matched-effect sample standard deviation, `ddof = 1`, minimum five strictly prior effects, `sigma_floor = 0.05` |
| One-step policy | `information_gain`, version `information-gain-policy/v1` |
| Two-step policy | `lookahead_information_gain`, version `lookahead-information-gain-policy/v1` |
| Information calculation | `discretized-gaussian-mutual-information/v1` |
| Lookahead utility | `two-step-total-entropy-reduction/v1` |
| Lookahead horizon | Exactly two experiments; execute only the first and replan from real state |
| Hypothesis family | Adam advantage, no consistent advantage, SGD advantage |
| Hypothesis means | `+0.10`, `0.00`, `-0.10` matched-effect units |
| Prior | Uniform, exactly `1/3` per hypothesis |
| Evidence contract | Successful public-structure-matched complementary Adam/SGD pairs only |
| Worlds | The four existing paired-evaluation worlds, unchanged |

The Gaussian density, Bayesian normalization, discretized outcome grid, candidate
feasibility rules, duplicate rules, evidence eligibility, cost functions, ranking,
fallback behavior, deterministic tie-breaking, and planner recursion are frozen. No
parameter may be tuned after a closed-loop result is inspected.

Random and greedy remain unchanged repository baselines, but they are not rerun in this
evaluation. Their actions do not depend on a scientific belief model, so duplicating them
under both models would not answer the causal question. Their existing frozen benchmark
results may be shown as clearly labeled historical context only. They do not enter the
new matrix, pooled estimates, confidence intervals, or acceptance gates.

## 2. Experimental Arms And Closed-Loop Semantics

### Primary arms

The evaluation contains exactly four primary arms:

| Arm ID | Belief controller | Existing policy |
| --- | --- | --- |
| `fixed_information_gain` | `fixed_sigma_gaussian` | `information_gain` |
| `calibrated_information_gain` | `replicated_noise_calibrated_gaussian` | `information_gain` |
| `fixed_lookahead_information_gain` | `fixed_sigma_gaussian` | `lookahead_information_gain` |
| `calibrated_lookahead_information_gain` | `replicated_noise_calibrated_gaussian` | `lookahead_information_gain` |

The primary causal contrasts are:

```text
calibrated_information_gain - fixed_information_gain
calibrated_lookahead_information_gain - fixed_lookahead_information_gain
```

Comparing information gain with lookahead remains secondary because it changes policy as
well as belief controller.

### Arm isolation

Each arm owns a separate immutable scientific lineage and a separate real execution
history. An arm may not read or mutate another arm's state. Each arm has its own:

- belief-lineage ID and current-state pointer;
- model-specific belief states, updates, likelihood calculations, sigma snapshots, and
  adequacy diagnostics;
- experiment records and completed-candidate set;
- evidence records and consumed-pair set;
- decision or plan traces and ranked alternatives;
- remaining decision budget and decision-cost ledger; and
- stop reason and threshold-crossing history.

No experiment, evidence, posterior, decision trace, budget debit, or simulated planner
state is shared between arms. The only shared objects are immutable public world design,
the evaluator-private potential-outcome schedule, and the calibrated arms' references to
the same calibration-prefix records. Sharing those records does not share epistemic state.

The implementation should use a distinct in-memory `ExperimentStore` or an equivalently
isolated arm state for every run. A shared SQLite current-state pointer is forbidden. No
new persistent schema is required for the benchmark; machine-readable evaluation
artifacts are the system of record for this study.

### Exact closed-loop cycle

For each arm, the evaluator performs this cycle until no feasible candidate remains:

1. Read only that arm's completed experiments, evidence history, current belief state,
   model-specific effect history, remaining decision budget, and public candidate design.
2. Freeze a truth-free prediction snapshot for every public optimizer comparison group.
3. Invoke the unchanged policy with the arm's current posterior and the appropriate
   prediction snapshot.
4. Record the complete real decision trace before revealing the selected observation.
5. Ask the evaluator-private observation oracle for the selected candidate only.
6. Append one real experiment and debit only that arm's decision ledger.
7. Derive scientific evidence only if the new experiment completes a valid, unapplied
   matched pair in that arm's history.
8. If evidence exists, apply exactly one model-specific Bayesian update and diagnostic.
9. Make that real matched effect eligible only for later calibrated sigma estimates.
10. Recompute from persisted real state at the next decision. Never execute a hypothetical
    second action merely because it appeared in a lookahead branch.

### Group-specific prediction adapter

The calibrated estimator is public-comparison-group-specific, while the current policy
entry point accepts one hypothesis tuple. This design resolves that implementation
constraint now.

Before each policy call, a truth-free adapter creates one immutable prediction snapshot
per public comparison group. A snapshot contains the same three hypothesis IDs, statements,
means, and current arm posterior, but uses that group's model-authorized sigma:

```text
fixed arm:       sigma(group) = 0.05
calibrated arm:  sigma(group) = max(stdev(prior eligible effects in group), 0.05)
```

The calibrated source set is the frozen five-effect prefix for that group plus eligible
real decision effects from strictly earlier update sequences in the same arm. It excludes
the current evidence, future evidence, simulated evidence, other arms' evidence, and all
other public groups.

The adapter supplies the snapshot associated with the matched pair whose evidence a
candidate can create:

- A one-step pair closer is scored by the unchanged EIG kernel using its pair's snapshot.
- A one-step opener still has zero immediate EIG. Existing fallback behavior is unchanged.
- A lookahead first action that closes group A uses group A's snapshot for its branches.
- A lookahead opener whose second action can close group B uses group B's snapshot at that
  second evidence-producing node.
- If a branch can later close a different group, that node uses the different group's
  predecision snapshot and the branch posterior produced by earlier simulated evidence.

Every group snapshot is frozen for the entire policy call. Hypothetical outcomes do not
update sigma anywhere in the two-step tree. Real execution then replans and rebuilds all
snapshots from the new real state. This is the sequential exclusion rule already frozen in
`ROBUST_BELIEF_DESIGN.md`.

This adapter is not a new policy or likelihood. It calls the exact existing Gaussian EIG
kernel and two-step recursion with model-specific inputs. Fixed-sigma regression fixtures
must remain bit-for-bit identical. The adapter has its own version,
`candidate-group-prediction-adapter/v1`, recorded on every decision trace.

## 3. Common Randomness And Potential Outcomes

### Potential-outcomes schedule

For each `(world_id, evaluation_seed)`, the evaluator privately materializes the observed
value for every public decision candidate before any arm selects an experiment. It uses
the existing world implementation without modification:

```text
Y(world, seed, candidate)
  = round(base_objective(candidate)
          + hidden_optimizer_intervention(world, candidate)
          + observation_sigma(world)
            * stable_standard_normal(
                f"{world_id}|{seed}|{candidate_design_key(candidate)}"),
          12)
```

`candidate_design_key` is exactly:

```text
(learning_rate, regularization, model_width, optimizer)
```

The standard-normal transform remains the existing SHA-256 and Box-Muller primitive. The
world's hidden true hypothesis, true optimizer effect, irrelevant-candidate behavior, and
observation sigma remain evaluator-only. Candidate cost is the existing deterministic
public cost and is not random.

The same potential-outcome table is reused by all four arms and both budgets for a given
world and seed. Whenever two arms select the same candidate design, they receive exactly
the same observed value, regardless of decision step or prior trajectory. Different arms
may select different candidates and therefore reveal different subsets of the table.

### Commitment and revelation boundary

Before the first arm runs, the evaluator writes a deterministic commitment containing:

- benchmark, world, keying, and observation-generator versions;
- world ID and evaluation seed;
- stable public candidate IDs and design fingerprints;
- a SHA-256 hash of the canonical full potential-outcome table; and
- a SHA-256 hash of the calibrated prefix for every public group.

The policy receives neither the table nor its hash-to-value mapping. The runner, not the
policy, calls a narrow observation oracle after a candidate has been selected and the
decision trace has been frozen. The oracle accepts exactly one selected candidate ID,
returns its committed value, and records the access. It offers no enumeration, lookup of
unselected candidates, best-value query, noise query, or truth query.

The full potential-outcome table may be written to an evaluator-only audit artifact only
after all four arms for that world and seed are complete. That artifact is never reopened
by a policy run. Tests must use a sentinel oracle that raises if a policy, reasoner,
belief model, sigma estimator, or planner requests an unselected outcome.

### Why common random numbers help

Common random numbers induce positive covariance when arms select overlapping candidates.
The noise contribution for an overlapping candidate cancels exactly in a paired arm
comparison instead of appearing as two independent draws. Even after trajectories
diverge, both runs remain defined on the same complete stochastic world, so a seed-level
difference compares two controllers under one potential-outcome schedule.

Common randomness does not make differing evidence streams item-wise paired. After
divergence, each arm observes a selected subset. Primary analysis must compare complete
arm outcomes by paired seed and must not condition on candidate overlap, because doing so
would select on a consequence of the controller. Candidate-overlap analysis is diagnostic
only.

### Randomness namespaces

Decision and calibration key spaces remain disjoint:

```text
decision outcomes:    existing world/seed/candidate design key
calibration outcomes: calibration namespace, world, evaluation seed,
                      public group, replication ID, replication seed,
                      shared or arm-noise suffix
bootstrap resampling: bootstrap seed 20,260,710 plus comparison key
```

No arm may create an additional observation seed. Arm ID, belief model, policy, budget,
decision step, and run order are deliberately absent from the decision outcome key.

## 4. Calibration Protocol And Cost Interpretations

### Frozen prefix

Every calibrated arm receives the frozen calibration-only prefix from
`ROBUST_BELIEF_DESIGN.md`:

- exactly five valid matched effects per public optimizer comparison group;
- one distinct replication ID and pair-level seed per effect;
- shared deterministic stochastic factors within a pair;
- independent deterministic Adam and SGD arm-noise draws;
- complete arm and matched-effect provenance;
- calibration namespace disjoint from decision candidates and seeds; and
- no scientific evidence edge or belief update.

For a fixed `(world_id, evaluation_seed, comparison_group)`, both calibrated policies and
both budgets reference byte-identical prefix observations. Policy, budget, belief model,
and arm ID are excluded from the prefix identity. Each calibrated arm nonetheless starts
with its own uniform belief state and its own later sigma-estimate and update records.

The fixed arms do not receive the prefix records, source effects, sample mean, estimated
sigma, or adequacy diagnostics as policy inputs. They begin at the same uniform scientific
prior and always use `sigma = 0.05`. They incur zero calibration cost. The evaluator may
retain the prefix commitment for pairing and audit, but the fixed arm has no reference to
it in its reasoning trace.

The calibrated policy does not receive raw prefix effects or their mean. It receives only
the group-specific prediction snapshots produced by the approved estimator, including the
final sigma and versioned provenance. Calibration effects remain noise-estimation records,
not evidence about which optimizer hypothesis is correct.

### Cost ledgers

Every run reports disjoint ledgers:

```text
calibration_cost
decision_cost
required_total_cost = calibration_cost + decision_cost
```

For fixed arms:

```text
calibration_cost = 0
required_total_cost = decision_cost
```

For calibrated arms, the full standalone prefix cost is attributed to every run. Under the
current designs it is `20.00` cost units in delayed-information, no-advantage, and
adverse-noise worlds, and `36.25` in the asymmetric-cost world. These values are frozen
expected reconciliation totals, not budget debits.

Calibration cost never reduces the short `2.25` or large `4.50` decision budget. It is
still mandatory in every end-to-end efficiency calculation. Suite-level physical cost
deduplicates prefix IDs because the same prefix is reused across policies and budgets.
Run-level cost attributes the full prefix because it represents a standalone deployment.
Both views must be reported and never combined without labels.

### Two efficiency interpretations

Conditional efficiency asks how well the controller used its decision budget after
calibration was already available:

```text
conditional_nll_efficiency
  = (ln(3) - final_NLL) / decision_cost

conditional_brier_efficiency
  = ((2/3) - final_Brier) / decision_cost
```

End-to-end efficiency charges the model's required total cost:

```text
end_to_end_nll_efficiency
  = (ln(3) - final_NLL) / required_total_cost

end_to_end_brier_efficiency
  = ((2/3) - final_Brier) / required_total_cost
```

The numerators are proper-score gains from the uniform prior. They may be negative when a
run becomes worse than the prior. Higher is better. A zero denominator is reported as
undefined and is a cost-audit failure for the primary matrix; it is never coerced to zero.

Entropy reduction per decision cost and per required total cost is also reported, but it
is descriptive because lower entropy can reflect confidently wrong belief. No acceptance
gate treats entropy reduction alone as scientific correctness.

## 5. Primary Metrics

Metrics are calculated separately for every arm, world, seed, budget, policy, and real
experiment step. Scientific correctness, resource use, decision behavior, and objective
optimization remain distinct.

### Scientific correctness and calibration

Let `p_true` be the final posterior assigned to evaluator truth and let `h_top` be the
lexicographically first hypothesis among exact maximum-probability ties.

| Metric | Frozen definition |
| --- | --- |
| Confidently wrong | `1` when `max_h p(h) >= 0.80` and `h_top` is not truth; otherwise `0` |
| NLL | `-ln(max(p_true, 1e-300))` |
| Multiclass Brier score | `sum_h (p(h) - 1[h is truth])^2` |
| Calibration error | Top-label ECE with ten equal-width confidence bins, recomputed at each aggregate scope |
| True-hypothesis probability | Final `p_true` |
| Posterior entropy | `-sum_h p(h) log2 p(h)` in bits |
| True-hypothesis rank | One plus the number of hypotheses with probability strictly greater than `p_true + 1e-15` |

NLL, Brier score, confidently-wrong rate, and ECE are the primary correctness metrics.
True probability and entropy explain how they changed but cannot override a failed proper
score or confidently-wrong gate.

### Correct confidence thresholds

Thresholds are `0.80` and `0.95`. A run has a sustained correct crossing at threshold
`q` when there is an earliest real experiment step `t` such that:

```text
p_t(true) >= q
and p_j(true) >= q for every later evidence-state checkpoint j through run end.
```

Experiment steps that produce no evidence retain the same posterior and remain in the
trace. Report:

- probability of a sustained `0.80` crossing;
- probability of a sustained `0.95` crossing;
- first sustained experiment count and decision cost;
- first sustained required total cost, adding prefix cost only for calibrated arms; and
- reversal count for every nonsustained earlier crossing.

Crossing time and cost are summarized only among runs that cross, with the conditioning
label visible. Failures are not assigned the budget, infinity, or another artificial
crossing time. Success-rate differences use all paired runs.

### Resource and execution metrics

- real decision cost;
- calibration cost;
- required total cost;
- suite-level deduplicated physical calibration cost;
- budget exhaustion indicator and stop reason;
- experiments completed;
- valid matched evidence pairs completed;
- evaluator-labeled redundant experiments selected;
- completed-candidate and duplicate-pair rejection counts; and
- conditional and end-to-end NLL, Brier, and entropy efficiencies.

### Secondary objective metric

Best observed objective remains a secondary optimization metric. It never enters a
belief update, policy score, decision ranking, divergence judgment, or acceptance gate.
Its purpose is to show whether scientific correctness and ordinary objective optimization
move in different directions.

## 6. Decision-Divergence Analysis

Trajectory divergence is the mechanism under study, not a nuisance to remove. Divergence
is analyzed within the fixed/calibrated pair for the same policy, world, seed, and budget.

### Frozen divergence events

For each paired run, report:

- whether the first selected candidate differs;
- the longest exact common prefix of selected candidate IDs;
- first divergence decision index;
- fixed and calibrated candidates and costs at first divergence;
- whether one arm stopped while the other continued;
- total candidate-set overlap and trajectory Jaccard similarity;
- cumulative decision-cost difference at first divergence and run end; and
- the paired final differences in NLL, Brier, true probability, entropy, confidence
  correctness, matched pairs, redundancy, and best objective.

At every decision index before and at first divergence, preserve each arm's own:

- belief-state and lineage IDs;
- posterior probabilities and entropy;
- prediction-snapshot IDs and group sigmas;
- completed-state and candidate-set fingerprints;
- remaining budget;
- ranked candidates, scores, feasibility assessments, and tie reasons; and
- for lookahead, complete summarized branch tree and selected contingent second actions.

The first action is compared from identical experiment histories and uniform beliefs,
though model prediction snapshots may differ. Later actions may be compared by decision
index, but their histories and belief states may already differ. Later action differences
are therefore descriptive trajectory comparisons, not matched decisions at an identical
state.

### Did divergence help?

The primary answer comes from the full paired run difference, not from conditioning on
overlap or on a favorable divergence type. Report paired outcomes stratified by:

- no divergence versus any divergence;
- first-action divergence versus later-only divergence;
- fixed candidate and calibrated candidate at first divergence;
- world, budget, and policy; and
- whether calibrated final NLL and Brier are both better, both worse, or mixed.

These strata are explanatory and cannot create a new acceptance subgroup. In particular,
the evaluator must not discard seeds where calibrated control chose a different candidate
or analyze only experiments both arms happened to select.

### Excessive caution and commitment

A commitment event occurs when any top hypothesis reaches posterior probability `0.80`.
Record whether it is correct, its first and sustained step, its decision and total cost,
and any later reversal. Excessive caution diagnostics include:

- reduction in sustained correct `0.80` and `0.95` crossing rates;
- increase in experiment or decision cost to a correct sustained crossing;
- increased rate of ending with `max_h p(h) < 0.80`;
- lower confidently-wrong rate accompanied by worse NLL or Brier score; and
- selecting additional experiments without improving proper scores.

Lower confidence is beneficial when it avoids unsupported certainty and harmful when it
merely delays a well-supported correct conclusion. Both cases must be shown.

### Planner-model mismatch diagnostic

For every real evidence item, record the predecision group sigma, the planned evidence-bin
probability containing the observation, prequential log likelihood, and actual posterior
update. Compare predicted bin frequencies with observed evidence by model and group. This
diagnoses a mismatch between calibrated belief revision and the policy's predictive
branches without changing either algorithm. A mismatch is reported as a failure case; it
does not trigger an automatic model or planner switch.

## 7. Acceptance Gates

### Pairing notation

For model-sensitive policy `a`, world `w`, budget `b`, seed `s`, and metric `x`, define:

```text
D_x(a, w, b, s)
  = x(calibrated, a, w, b, s) - x(fixed, a, w, b, s)
```

Lower is better for confidently wrong, NLL, Brier, ECE, entropy, decision cost,
redundancy, and exhaustion. Higher is better for true probability, correct threshold
rates, matched pairs, and all score-gain efficiencies.

An adverse-world or delayed-world pooled seed block is the equal-weight mean of the four
within-seed cells formed by two policies and two budgets. A global pooled seed block is
the equal-weight mean of all sixteen cells formed by four worlds, two policies, and two
budgets. The point estimate is the mean of the 100 seed blocks. Confidence intervals use
the frozen paired bootstrap in Section 8.

ECE is nonlinear. Its point difference and every bootstrap replicate are computed by
rebuilding the fixed and calibrated ECE from the resampled seed blocks; per-run ECE values
are never invented or averaged.

### Hard validity gates

All hard gates must pass before performance is considered:

1. Model, estimator, policy, utility, world, candidate, cost, evidence, metric, and adapter
   source hashes and versions match the frozen manifest.
2. Hidden truth, true effects, world noise, evaluator redundancy labels, future outcomes,
   and unselected potential outcomes are absent from all policy, planner, model, updater,
   and sigma-estimator inputs.
3. Potential-outcome commitments precede arm execution, every selected overlap returns an
   identical observation, and observation-oracle access logs contain selected candidates
   only.
4. Every arm has an isolated experiment history, evidence stream, belief lineage,
   decision trace, and budget ledger. Reversing arm execution order leaves all results
   unchanged.
5. Every calibrated group has exactly five valid prefix effects before its first decision,
   calibration produces zero scientific updates, and fixed arms cannot access prefix data.
6. Current, future, simulated, cross-group, and cross-arm effects never enter a sigma
   snapshot. Every estimate and update is reconstructable from exact source IDs.
7. Every real selected candidate is feasible, every lookahead branch respects the hard
   decision budget, no completed candidate or consumed pair is reused, and simulated state
   never enters real storage.
8. Calibration and decision ledgers are disjoint and reconcile exactly. All calibrated
   runs report full standalone prefix cost and all suite reports deduplicate physical
   prefixes by ID.
9. Identical inputs produce byte-equivalent arm traces after excluding declared wall-clock
   metadata. Fixed-sigma policy fixtures remain bit-for-bit identical to current behavior.
10. Every required paired 95 percent interval, divergence record, failure case, output hash,
    and audit result is present. Missing or undefined gate data fails acceptance.

### Performance gates

`U95` and `L95` denote upper and lower paired 95 percent interval bounds. All inequalities
below are conjunctive. They are not universal scientific constants; they are frozen
decision criteria for this synthetic evaluation.

1. **Adverse-noise confidently-wrong reduction**

   ```text
   mean(D_CW_adverse) <= -0.10
   U95(D_CW_adverse) < 0
   mean(D_CW) <= 0.02 in every adverse policy-budget cell
   ```

2. **Adverse-noise proper scores and calibration**

   ```text
   mean(D_NLL_adverse) < 0       and U95(D_NLL_adverse) < 0
   mean(D_Brier_adverse) < 0     and U95(D_Brier_adverse) < 0
   mean(D_ECE_adverse) < 0       and U95(D_ECE_adverse) <= 0
   ```

3. **Delayed-information scientific non-regression**

   ```text
   mean(D_TrueProbability_delayed) >= -0.02
   L95(D_TrueProbability_delayed) >= -0.05
   mean(D_NLL_delayed) <= 0.05    and U95(D_NLL_delayed) <= 0.10
   mean(D_Brier_delayed) <= 0.02  and U95(D_Brier_delayed) <= 0.04
   mean(D_CW_delayed) <= 0
   D_sustained_0.80_rate_delayed >= -0.05
   D_sustained_0.95_rate_delayed >= -0.05
   ```

4. **Other-world non-regression**

   In each of `no_optimizer_advantage` and `asymmetric_experiment_costs`, first pooled
   across budgets and then checked separately for both policies:

   ```text
   mean(D_NLL) <= 0.05
   mean(D_Brier) <= 0.02
   mean(D_CW) <= 0.02
   mean(D_ECE) <= 0.05
   ```

5. **Decision-cost and exhaustion control**

   For every world-policy-budget cell with budget `B`:

   ```text
   mean(D_DecisionCost) <= 0.10 * B
   U95(D_DecisionCost) <= 0.20 * B
   mean(D_BudgetExhaustionRate) <= 0.05
   ```

   No individual run may exceed `B`. Calibration cost is excluded from this feasibility
   gate and included in Gate 7.

6. **Conditional scientific efficiency under adverse noise**

   ```text
   mean(D_conditional_nll_efficiency_adverse) > 0
   L95(D_conditional_nll_efficiency_adverse) > 0
   mean(D_conditional_brier_efficiency_adverse) > 0
   L95(D_conditional_brier_efficiency_adverse) > 0
   ```

7. **Calibration-inclusive end-to-end efficiency**

   Under adverse noise:

   ```text
   mean(D_end_to_end_nll_efficiency_adverse) > 0
   L95(D_end_to_end_nll_efficiency_adverse) > 0
   mean(D_end_to_end_brier_efficiency_adverse) > 0
   L95(D_end_to_end_brier_efficiency_adverse) > 0
   ```

   Across all worlds with equal world, policy, and budget weights:

   ```text
   mean(D_end_to_end_nll_efficiency_global) >= 0
   L95(D_end_to_end_nll_efficiency_global) >= 0
   mean(D_end_to_end_brier_efficiency_global) >= 0
   L95(D_end_to_end_brier_efficiency_global) >= 0
   ```

   This global gate is deliberately not guaranteed by the shadow results. Calibration can
   improve belief correctness yet remain too expensive for broad end-to-end promotion.

### Verdict rules

Promote calibrated closed-loop control for this prototype only if every hard gate and
every performance gate passes. If scientific-correctness gates pass but Gate 7 fails, the
verdict is `scientifically_improved_but_not_end_to_end_efficient`; calibrated closed-loop
control is not promoted. If any other performance gate fails, the verdict is
`closed_loop_acceptance_failed`. A negative verdict is final for this evaluation version
and may not be changed by selecting a favorable policy, budget, seed subset, or divergence
stratum after results are visible.

## 8. Paired Evaluation Design

### Matrix

The primary matrix is:

```text
4 primary arms
x 4 existing worlds
x 2 budgets
x 100 seeds
= 3,200 closed-loop runs
```

Seeds are exactly `0` through `99`. Budgets are exactly short `2.25` and large `4.50`.
The worlds are exactly:

- `delayed_information`;
- `no_optimizer_advantage`;
- `adverse_noisy_observations`; and
- `asymmetric_experiment_costs`.

No smoke-test result may alter this matrix. A five-seed smoke run using seeds `0` through
`4` is allowed only to validate correctness, outputs, and runtime. It cannot support a
research claim or change a constant.

### What remains paired after divergence

Within one policy, the fixed and calibrated arms remain paired at the run level by:

- world and hidden world parameters;
- evaluation seed and full potential-outcome schedule;
- public candidates, candidate ordering, structural eligibility, and costs;
- initial uniform prior and empty decision history;
- decision budget and stopping rules;
- policy code, version, ranking, tie-breaking, and planning horizon; and
- metric and evaluator code.

They differ only in model-specific sigma, resulting posterior lineage, and the downstream
trajectory caused by those beliefs. That is the treatment contrast.

Candidate-level outcomes are exactly paired only for candidates selected by both arms.
Evidence items, experiment counts, and decision indexes are not forced into pairs after
trajectory divergence. Outcome-level pairing is preserved through the common potential
schedule: each complete arm outcome is a deterministic function of the same seed-level
world. Primary inference uses paired complete-run differences, not independent-sample
tests and not overlap-only observations.

### Statistical summaries

For every arm, world, budget, and policy, report count, mean, median, sample standard
deviation, and a 95 percent interval. For every fixed/calibrated contrast, report:

- mean and median paired difference;
- sample standard deviation of paired differences;
- deterministic paired 95 percent percentile-bootstrap interval;
- wins, ties, and losses under the metric's declared direction;
- paired standardized mean difference when difference variance is nonzero; and
- number of valid paired observations.

Use exactly `10,000` bootstrap resamples and bootstrap seed `20,260,710`. A cell interval
resamples its 100 paired seeds. Pooled world intervals resample one seed block containing
both policies and both budgets. Global intervals resample one seed block containing all
four worlds, both policies, and both budgets. ECE is recomputed within every bootstrap
replicate. Optional threshold times and costs are summarized only among explicitly labeled
paired-success subsets; threshold success-rate intervals use all 100 paired seeds.

All gate intervals are mandatory. Secondary comparisons are reported without claiming
statistical significance. No seed filtering, outlier removal, variance-based policy
selection, or multiple-comparison family may be defined after results. The acceptance
rule is an intersection of predeclared gates, so no p-value correction is used to rescue a
failed gate. Any later exploratory p-values must be labeled exploratory and use Holm
correction within their declared family.

### Truth boundary

Policies, planners, belief models, sigma estimators, evidence extraction, and stopping
logic finish before truth-dependent scoring begins. The evaluator may then use hidden
truth to calculate correctness metrics and may release the committed potential-outcome
table for audit. Neither truth nor released counterfactuals may be fed back into any run.

## 9. Risks And Detection Methods

| Risk | Consequence | Predeclared detection or control |
| --- | --- | --- |
| Trajectory divergence | Arms no longer share item-wise evidence, making naive observation-level tests invalid. | Use complete-run seed pairing, record common prefixes and first divergence, and prohibit overlap-conditioned primary inference. |
| Selection bias | Analyzing only shared candidates or completed pairs can favor one controller. | Include every scheduled run in intent-to-treat arm comparisons; label all divergence strata exploratory. |
| Calibration cost overwhelms benefit | Correctness may improve while standalone deployment becomes inefficient. | Report decision and prefix costs separately; require both adverse and global end-to-end proper-score efficiency gates. |
| Over-conservative decisions | Lower confidently-wrong rate may come from refusing justified commitment. | Report sustained correct crossings, noncommitment, reversals, NLL, Brier, and cost to correct confidence; enforce delayed-world gates. |
| Planner belief-model mismatch | Calibrated updates may disagree with predictive branches used for planning. | Use group-specific snapshots with the unchanged Gaussian kernel; record planned bin probabilities and prequential residual diagnostics. |
| Counterfactual-outcome leakage | A controller could choose candidates using outcomes it never earned. | Private post-decision observation oracle, pre-run commitments, access logs, sentinel tests, and policy-interface source audit. |
| Reuse of calibration information | Prefix effects could update beliefs, mark candidates complete, or be charged repeatedly. | Separate namespace and record type, zero prefix belief updates, decision-candidate isolation, source-ID audit, and physical/run-level cost reconciliation. |
| Limited hypothesis space | All three hypotheses may be wrong, so calibrated uncertainty can still be misleading. | Report predictive adequacy, confidently wrong cases, residuals, and coverage; do not generalize beyond the three-hypothesis synthetic world. |
| Group-specific sigma variability | Ranking could depend on five-sample estimator noise rather than meaningful reliability. | Record every group estimate, source effect, and ranking change; compare estimate dispersion across seeds without post hoc pooling. |
| Candidate-order artifacts | Fallback or exact ties may drive divergence. | Freeze IDs/order, retain lexicographic ties, and report whether first divergence arose from a strict score difference or a tie. |
| Run-order contamination | A prior arm could mutate shared state or consume a potential outcome. | Isolated stores, immutable oracle table, normal and reversed arm-order replays, and byte-equivalence checks. |
| Transient threshold confidence | An arm may cross a threshold and later reverse. | Use sustained crossings for primary threshold metrics and report every transient crossing separately. |

Common random numbers reduce sampling variance; they do not eliminate selection effects,
model misspecification, finite-seed uncertainty, or the cost of learning sigma.

## 10. Outputs And Audits

### Versioned output directory

Write a new directory such as `closed-loop-evaluation-v1-100-seeds`. Refuse to overwrite
an existing required artifact. No existing robust-belief or lookahead output may be
modified.

The required artifact set is:

| File | Required contents |
| --- | --- |
| `protocol_snapshot.json` | Every frozen constant, arm, gate, formula, source hash, and output schema version |
| `run_manifest.json` | Evaluation version, dependencies, worlds, seeds, budgets, code hash, run matrix, prefix catalog, audits, and hashes of every other output |
| `potential_outcome_commitments.jsonl` | Pre-execution world/seed candidate-set and canonical-table hashes |
| `potential_outcomes.jsonl` | Evaluator-only full candidate outcomes released after all arms complete, with key provenance |
| `calibration_prefixes.jsonl` | Prefix/group/replication/arm/effect identities, estimates, costs, and provenance |
| `per_run_results.jsonl` | Complete nested run result and metric trace |
| `per_run_results.csv` | Flat run-level metrics suitable for later analysis |
| `decision_traces.jsonl` | Every real decision or plan, model snapshot, ranked alternatives, budget, and selected candidate |
| `evidence_belief_traces.jsonl` | Real experiments, evidence, sigma estimates, diagnostics, updates, and posterior sequence by arm |
| `divergence_events.jsonl` | Complete first-divergence and trajectory comparison records |
| `divergence_events.csv` | Flat divergence metrics and paired final consequences |
| `aggregate_results.csv` | Mean, median, standard deviation, interval, run count, threshold success, and exhaustion by arm/world/budget/policy |
| `paired_closed_loop_comparisons.csv` | Every calibrated-minus-fixed paired estimate, CI, win/tie/loss, and effect size |
| `calibration_results.csv` | ECE, accuracy, confidence, confidently-wrong rate, NLL, and Brier by declared scope |
| `threshold_results.csv` | Sustained and transient crossings, reversals, decision cost, and total cost |
| `adequacy_diagnostics.csv` | Predictive tails, standardized residuals, log likelihood, coverage, alarms, and adequacy state |
| `cost_accounting.csv` | Disjoint prefix and decision ledgers, run-attributed cost, deduplicated physical cost, and reconciliation |
| `failure_cases.jsonl` | Confidently wrong, proper-score regression, excessive caution, mismatch, and audit failure cases |
| `ACCEPTANCE_GATES.json` | Every hard and performance inequality, point estimate, interval, result, and final verdict |
| `CLOSED_LOOP_EVALUATION_REPORT.md` | Human-readable protocol, results, divergences, costs, failures, gates, and limitations |

Potential outcomes and truth-dependent fields must be marked `evaluator_only` in their
schemas. Decision and belief traces must contain no such field. The manifest records
dependency versions, SQLite schema version, Python version, policy and model versions,
candidate and observation commitments, and SHA-256 hashes for reproducibility.

### Mandatory audits

1. **Algorithm freeze:** compare policy, model, estimator, likelihood, utility, world, and
   metric source hashes with `protocol_snapshot.json`; run fixed-policy regression fixtures.
2. **Matrix completeness:** assert exactly 3,200 unique primary runs and one fixed/calibrated
   pair per policy, world, budget, and seed.
3. **Potential-outcome commitment:** regenerate every table, verify its pre-run hash, and
   confirm exact selected-candidate agreement across overlapping trajectories.
4. **No counterfactual access:** inspect oracle logs and sentinel tests; only selected
   candidate IDs may be requested before evaluator release.
5. **Truth isolation:** inspect signatures, serialized operational records, imports, and
   sentinel truth objects for forbidden fields or access.
6. **Arm isolation:** reverse arm execution order and verify byte-equivalent traces after
   excluding declared timestamps; assert no cross-arm state or record IDs in inputs.
7. **Calibration boundary:** verify five effects per group, zero prefix evidence/updates,
   fixed-arm prefix invisibility, calibrated source IDs, and current-evidence exclusion.
8. **Policy-model adapter:** independently recompute every candidate EIG or branch from the
   recorded group snapshot; fixed-sigma decisions must reproduce current outputs exactly.
9. **Planning integrity:** verify branch normalization, group-specific sigma selection,
   branch-wise budget feasibility, execute-first-only semantics, and zero simulated writes.
10. **Evidence integrity:** rederive every real evidence value from its two source
    experiments, prevent duplicate pair consumption, and reconstruct every posterior.
11. **Cost integrity:** reconcile calibration, decision, required total, physical prefix,
    threshold, and efficiency denominators; reject cross-ledger entries.
12. **Statistics:** independently recompute all run metrics, ECE bins, paired differences,
    seed-block bootstraps, gate intervals, and verdict inequalities.
13. **Artifact integrity:** validate JSON/JSONL/CSV schemas, row counts, foreign IDs,
    ordering, output hashes, source-tree hash, and overwrite protection.

No gate is evaluated if a hard audit fails. Audit failure is not converted into missing
data, a fallback candidate, or a favorable performance result.

## 11. Non-Goals

This evaluation explicitly excludes:

- implementation in this design milestone;
- a new belief model or likelihood family;
- Student-t or mixture likelihoods;
- automatic model selection or model switching;
- abstention or a none-of-the-above hypothesis;
- unknown or autonomous hypothesis generation;
- a new policy, planner, utility, acquisition function, or longer horizon;
- changes to random, greedy, information gain, or lookahead behavior;
- LLM reasoning, summarization, or agents;
- PPO or real-training integration;
- a web or other user interface;
- cloud execution, distributed orchestration, or external experiment tracking;
- a knowledge graph or generic search framework; and
- claims about domains beyond the current synthetic optimizer-effect benchmark.

The evaluation does not use potential outcomes to retrospectively choose a better action,
repair a trajectory, estimate an oracle policy, or train a controller.

## 12. Final Review

### Frozen constants

| Concern | Frozen value or rule |
| --- | --- |
| Evaluation version | `closed-loop-belief-control-evaluation/v1` |
| Primary arms | Exactly the four arms in Section 2 |
| Context baselines | Random and greedy not rerun; historical context only |
| Models | `fixed_sigma_gaussian`, `replicated_noise_calibrated_gaussian` |
| Policy versions | `information-gain-policy/v1`, `lookahead-information-gain-policy/v1` |
| Prediction adapter | `candidate-group-prediction-adapter/v1` |
| Hypotheses | Adam advantage, no consistent advantage, SGD advantage |
| Prior | `1/3`, `1/3`, `1/3` |
| Predicted means | `+0.10`, `0.00`, `-0.10` |
| Fixed sigma | `0.05` matched-effect units |
| Calibrated sigma | `max(sample stdev with ddof=1, 0.05)` |
| Minimum calibration sample | Exactly five strictly prior matched effects per public group |
| Prefix role | Sigma estimation only; zero scientific belief updates |
| Prefix scope | World, evaluation seed, public comparison group; excludes policy and budget |
| Standard prefix cost | `20.00` in delayed, no-advantage, and adverse worlds |
| Asymmetric prefix cost | `36.25` |
| Decision budgets | Short `2.25`, large `4.50` |
| Seeds | Integers `0` through `99` |
| Worlds | The four IDs in Section 8, with current candidates, truth, noise, and costs unchanged |
| Matrix size | Exactly 3,200 primary runs |
| Decision outcome key | Exact existing world ID, seed, and candidate-design-key material |
| Candidate outcome sharing | Same committed value for every arm selecting the same design |
| Outcome revelation | Selected candidate only, after decision trace is frozen |
| EIG grid | `[-0.40, 0.40]`, step `0.01`, plus two unbounded tails; 82 bins |
| Positive-information tolerance | `1e-12` |
| Information horizon | One experiment |
| Lookahead horizon | Two experiments, branch-conditional second action, execute first only |
| Lookahead primary ranking | Greater total EIG, lower expected total cost, greater EIG per expected cost, lexicographic candidate ID |
| One-step positive-EIG ranking | Greater immediate EIG, lower candidate cost, lexicographic candidate ID |
| One-step fallback | Lowest cost, then lexicographic candidate ID |
| Confidence thresholds | Sustained `0.80` and `0.95` correct probability |
| Confidently-wrong threshold | Top confidence at least `0.80` in a non-true hypothesis |
| NLL floor | `1e-300` |
| ECE | Ten equal-width top-label bins |
| Confidence level | `95%` |
| Bootstrap | `10,000` paired percentile resamples, seed `20,260,710` |
| Required cost, fixed | Decision cost only |
| Required cost, calibrated | Full prefix cost plus decision cost |
| Primary pairing | Calibrated minus fixed within the same unchanged policy |
| Truth access | Evaluator only, after every arm is complete |
| Output overwrite | Forbidden |
| Acceptance | Every hard gate and every Section 7 performance gate must pass |

The hidden world constants remain the current values and are evaluator-only:

| World | True hypothesis | True effect | Per-arm observation sigma | Public decision design |
| --- | --- | ---: | ---: | --- |
| `delayed_information` | Adam advantage | `+0.12` | `0.005` | Objective-only decoy plus two symmetric matched pairs |
| `no_optimizer_advantage` | No advantage | `0.00` | `0.03` | Objective-only decoy plus two symmetric matched pairs |
| `adverse_noisy_observations` | Adam advantage | `+0.12` | `0.20` | Objective-only decoy plus two symmetric matched pairs |
| `asymmetric_experiment_costs` | SGD advantage | `-0.12` | `0.03` | Three matched pairs with asymmetric costs, including the current cheap-opener trap |

### Exact acceptance inequalities

The authoritative inequalities are Section 7. In compact form, acceptance requires:

- adverse pooled confidently-wrong delta at most `-0.10`, with upper CI below zero;
- adverse pooled NLL, Brier, and ECE deltas below zero with nonpositive required upper
  bounds;
- delayed true-probability regression no worse than `0.02`, bounded proper-score
  regressions, no confidently-wrong increase, and threshold-rate regression no worse than
  five percentage points;
- bounded NLL, Brier, confidently-wrong, and ECE regressions in no-advantage and
  asymmetric worlds;
- every cell's decision-cost increase at most `10%` of budget in the mean and `20%` at
  the upper CI, with exhaustion-rate increase at most five percentage points;
- positive adverse conditional NLL and Brier efficiency differences with lower CIs above
  zero; and
- nonnegative global plus positive adverse calibration-inclusive NLL and Brier efficiency
  differences, with lower CIs at or above zero.

No subset, secondary metric, divergence stratum, or historical shadow result can replace
one of these inequalities.

### Unresolved design questions

None. The arms, controller inputs, candidate-group sigma behavior, common-random-number
protocol, calibration attribution, metrics, divergence rules, pairing, bootstrap,
acceptance inequalities, outputs, and audits are frozen. No result-dependent choice
remains open.

### Implementation blockers

There is no scientific or protocol blocker. Two known engineering prerequisites must be
completed exactly as specified before the evaluation can run:

1. The current policy entry points assume one candidate-independent hypothesis tuple. A
   truth-free candidate-group prediction adapter must supply the frozen group snapshot at
   every evidence-producing scoring node. It may not alter formulas, ranking, tie-breaking,
   horizons, or fixed-sigma outputs.
2. The current benchmark runner hardwires one legacy fixed-sigma reasoning stream. A new
   evaluation-only arm runner must isolate histories, lineages, evidence, decisions, and
   ledgers while querying the shared private potential-outcome oracle only after selection.

These prerequisites are implementation work, not permission to revisit the evaluation
design. If either cannot preserve the frozen regression and isolation tests, implementation
is blocked and no benchmark result is valid.

The repository is ready for that narrow implementation milestone once reviewed. This
document does not implement it.
