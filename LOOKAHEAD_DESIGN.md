# Two-Step, Cost-Aware Experimental Planner

Status: design proposal only. This document does not authorize implementation and does not
assume that two-step lookahead will outperform the current policies.

## 1. Research Question

The precise research question is:

> Does two-step lookahead improve scientific efficiency over one-step expected information gain
> when useful evidence is delayed?

Here, scientific efficiency means reduction in uncertainty over the fixed optimizer-effect
hypotheses per unit of experimental cost. It does not mean best objective value, number of runs,
or fluency of an explanation.

### Primary hypothesis

On predeclared worlds where no currently feasible single experiment produces evidence, but a
feasible two-experiment sequence completes a valid matched pair, a two-step, cost-aware planner
will achieve greater posterior-entropy reduction per unit cost than the current one-step
`information_gain` policy under the same cumulative budget.

### Null hypothesis

After controlling for cost, seed, candidate set, initial history, and hidden world, two-step
lookahead provides no reproducible improvement over one-step expected information gain. Any
observed difference is zero, adverse, or attributable to candidate ordering, tie-breaking,
benchmark leakage, model misspecification, or sampling variation.

### Conditions under which lookahead should help

- Evidence requires a matched pair and neither member has been completed.
- At least two actions remain and the complete pair fits the remaining budget.
- Choosing an irrelevant or infeasible opener first can consume enough budget to prevent a useful
  pair from being completed.
- Candidate order and individual candidate cost do not conveniently make the one-step fallback
  open the best pair by accident.
- The hypothesis likelihood model is sufficiently aligned with the evidence-generating world for
  entropy reduction to track learning about the true hypothesis.
- Candidate feasibility and evidence eligibility are available without hidden benchmark truth.

### Conditions under which lookahead should not help

- A currently feasible experiment already completes an informative matched pair.
- Fewer than two experiments can fit the remaining budget.
- All feasible openers lead to equivalent pairs at equivalent total cost.
- The current deterministic fallback already opens the best pair.
- The posterior has no material reducible uncertainty.
- Every two-step sequence has zero expected information, excessive cost, or only inadmissible
  evidence.
- Observation noise or likelihood misspecification makes the planned evidence unreliable.

### Evidence that would falsify the proposed benefit

The proposed benefit is falsified for this prototype if, on a sufficiently seeded and paired
delayed-information benchmark, lookahead does not improve entropy reduction per unit cost over
one-step EIG, the improvement disappears under candidate-ID permutations, or any gain requires
hidden truth. Material regression in matched-pair completion, calibration, or final entropy in
worlds where one-step EIG is already sufficient would also count against adoption. A negative
result is valid research output, not an implementation failure.

## 2. Current Failure Mode

### Implemented decision path

The relevant path is:

1. `runner.suggest_information_gain` in `research_decision_engine/runner.py` synchronizes current
   reasoning, reads the current `BeliefState`, and invokes `InformationGainPolicy.decide`.
2. `InformationGainPolicy.decide` in `research_decision_engine/decision.py:163` computes one
   candidate-independent estimate with `expected_information_gain` at line 300.
3. `_new_matched_counterpart` at line 445 reports whether a candidate closes exactly one
   currently open optimizer pair. Completed candidates and already completed pair designs are
   excluded.
4. A closer receives the full matched-evidence EIG. An opener is assigned exactly `0.0` at line
   208 and its expected posterior entropy remains the current entropy.
5. If no candidate has positive immediate EIG, `_add_ranking_reasons` at line 467 supports a
   lowest-cost, then candidate-ID fallback. No future action is represented.
6. After a real run, `synchronize_optimizer_reasoning` in
   `research_decision_engine/optimizer_effect.py:89` calls `_matched_experiment_pairs` at line 119.
   Only a completed SGD/Adam pair with equal controls becomes `Evidence`; a single result does not.
7. `BayesianBeliefUpdater.update` in `research_decision_engine/reasoning.py:355` updates the
   posterior only after that evidence exists.
8. The benchmark adapter `_select_candidate` in
   `research_decision_engine/benchmarks/evaluation.py:576` calls the same policy afresh at each
   step with only the current state and remaining budget.

### Why an opener has zero immediate EIG

The three hypotheses predict a distribution for an observed optimizer difference, not for an
absolute result from one optimizer. Before the opposite optimizer has run at identical controls,
there is no observed difference, no admissible causal comparison, no `Evidence`, and therefore no
posterior transition. For a one-action horizon,

```text
H(current belief) - E[H(belief after opener)] = 0.
```

This behavior is scientifically sound when the question is strictly, "What can this one run teach
us now?" Treating the single result as optimizer-effect evidence would violate the matched-control
rule and confound optimizer with the uncontrolled baseline objective.

It becomes harmful when the actual decision is, "Which first run should reserve the option to
produce evidence within the remaining budget?" A zero-EIG opener may be the necessary first half
of the only informative sequence. The current fallback can instead spend budget on an unmatched,
too-expensive-to-close, or scientifically irrelevant design.

### Source of the limitation

The limitation is shared across three layers:

- **Policy:** candidate scoring has a one-action horizon and binary semantics: full EIG for an
  immediate closer, zero for an opener. It has no experimental-state transition or contingent
  second action.
- **Evidence model:** optimizer-effect evidence correctly requires two runs. The model supplies a
  Gaussian distribution for the final difference but no hypothesis-conditioned distribution for
  a single absolute observation. This creates real delayed information and limits legitimate
  first-step branching.
- **Benchmark:** the current worlds contain matched pairs, but they do not isolate the failure.
  Cheap, low-ID `cand-000` is an informative opener, and `cand-001` is its counterpart. Irrelevant
  candidates have later IDs. Thus the deterministic fallback often behaves like a two-step policy
  accidentally.

### What the latest benchmark does and does not show

The latest saved benchmark contains 36 runs: four worlds, three seeds, three policies, and a cost
budget of 8. The aggregate means are:

| Policy | Final entropy | True-hypothesis probability | Matched pairs | Redundant runs | Best observed objective |
| --- | ---: | ---: | ---: | ---: | ---: |
| random | 0.3394 | 0.9109 | 1.25 | 0.6667 | 0.9416 |
| greedy | 0.6444 | 0.7644 | 0.8333 | 0.6667 | 0.9875 |
| information_gain | 0.0907 | 0.9827 | 3.50 | 0.0000 | 0.8901 |

These are descriptive results from only three seeds per world; no significance test was run.
They show that current `information_gain` performed well on the existing scientific metrics and
less well on objective optimization. They do not test the lookahead hypothesis.

In every symmetric-cost run, `information_gain` began `cand-000` (no evidence), `cand-001`
(evidence), then repeated that opener/closer pattern. In every asymmetric-cost run it likewise
began `cand-000`, `cand-001`. Its complete sequence was invariant across seeds within each cost
mode. The first selection was the lowest-cost, lowest-ID fallback, not a positive-EIG decision.
The current benchmark therefore masks the myopia instead of measuring it.

## 3. Formal Planning Problem

Let the fixed hypothesis set be `H = {h_adam, h_none, h_sgd}` and let `b(h)` be the current
posterior probability. Define entropy in bits as

```text
Entropy(b) = -sum_h b(h) * log2(b(h)).
```

### State and action

The experimental state is

```text
x = (completed designs, open matched-pair controls, consumed pairs,
     current belief-state ID, remaining budget).
```

This is a planning projection, not a replacement for persisted experiments or beliefs. A
candidate action `a` is one uncompleted, domain-admissible experiment specification with finite
non-negative cost `c(a)`. It is feasible only if it fits the remaining budget and does not repeat
a completed candidate or complete a pair whose evidence has already been consumed.

### Outcomes and transitions

If `a` completes a pair, its evidence outcome `z` is a discretized optimizer difference. For bin
`z`, hypothesis `h` assigns mass `m_h(z)`. The predictive mixture and temporary posterior are

```text
q(z)       = sum_h b(h) * m_h(z)
b_z(h)     = b(h) * m_h(z) / q(z), when q(z) > 0.
```

If `a` only opens a pair, the planning outcome is the singleton `NO_EVIDENCE_YET` with probability
one and `b_z = b`. The real absolute objective is still observed after execution, but the current
hypothesis model provides no valid `p(single result | h)`. The planner must not invent one.

The first transition adds the simulated candidate specification to a temporary completed set,
debits its cost, and, only for a pair-closing outcome, marks that pair consumed and creates a
temporary posterior. No simulated object is evidence and no transition is persistent.

For each first-outcome branch, feasible second actions are recomputed from the branch state and
branch-wise remaining budget. `STOP` is an explicit zero-cost, zero-information second action.
The hard budget applies to every nonzero-probability branch:

```text
c(a1) + c(a2(z1)) <= remaining_budget.
```

### Information and cost quantities

For first action `a1`:

```text
IG_immediate(a1)
  = Entropy(b0) - sum_z1 q1(z1) * Entropy(b1[z1]).

IG_delayed(a2 | z1)
  = Entropy(b1[z1])
    - sum_z2 q2(z2 | z1, a2) * Entropy(b2[z1, z2]).

IG_total(a1, contingent a2)
  = IG_immediate(a1)
    + sum_z1 q1(z1) * IG_delayed(a2(z1) | z1)
  = Entropy(b0) - E[Entropy(b_terminal)].

Cost_total
  = c(a1) + sum_z1 q1(z1) * c(a2(z1)).
```

Immediate information is evidence available after the first run. Delayed information is
available only after the selected second run. Total EIG is their non-duplicative sum. Sequence
cost is separate from all three.

### Primary utility

The proposed primary utility is expected entropy reduction per expected cost, subject to the hard
branch-wise budget:

```text
PlanningUtility = IG_total / Cost_total.
```

All experiment costs in the current domain are positive. A nonpositive or invalid denominator is
an error. A plan with no positive EIG is not made attractive by low cost; it receives utility
zero and uses the existing explicit fallback semantics if an experiment must still be suggested.

This utility is appropriate because it leaves the scientific target unchanged: uncertainty over
the same three hypotheses. Cost affects efficiency and feasibility, not the definition of
evidence, belief, or scientific truth. It is parameter-free, directly testable, and aligned with
the proposed primary benchmark metric. Its known weakness is that a ratio can prefer a small,
cheap gain over a larger total gain. Final entropy and matched-pair completion must therefore
remain co-primary diagnostics, and the cost-unaware ablation is mandatory.

Because branch-contingent actions share one ratio denominator, selecting each branch by a local
ratio is not generally exact. For a fixed `a1`, the finite optimum can be found with a small,
deterministic fractional-programming loop. At trial ratio `rho`, each branch independently chooses
the second action maximizing

```text
IG_delayed(a2 | z1) - rho * c(a2).
```

The resulting aggregate `IG_total / Cost_total` becomes the next `rho`; iteration stops when the
selected contingent plan is unchanged or the residual is within a declared tolerance. The loop
must have a deterministic iteration cap and fail explicitly if it does not converge. This is a
fixed two-step calculation, not a generic search framework.

### Reasonable alternative utilities

1. **Maximum total EIG under a hard budget, then lowest cost.** This preserves the current EIG
   objective most directly and makes branch optimization additive, but it can spend much more for
   negligible extra information.
2. **Net value:** `IG_total - lambda * Cost_total`. This is additive and easy to optimize, but
   `lambda` is a scientific-objective tradeoff that must be justified, versioned, and ablated. It
   must never be hidden in code.
3. **Minimum expected terminal entropy with lexicographic cost.** This is equivalent to maximum
   total EIG for a fixed initial belief, with cost used only for feasibility and ties. It measures
   learning but not cost efficiency.

Objective performance must not enter any of these utilities during this milestone.

## 4. Exact Two-Step Calculation

For each feasible first-step candidate `a1`, calculate the plan as follows.

1. **Enumerate first outcomes.** If `a1` closes a valid pair, use every discretized evidence bin,
   including tail bins. If it opens a pair, use one `NO_EVIDENCE_YET` branch with probability one.
2. **Calculate predictive probabilities.** For evidence bin `z`, compute each hypothesis mass and
   the posterior-weighted mixture `q(z)`. Normalize the complete mixture explicitly.
3. **Construct temporary beliefs.** Apply bin-mass Bayes updates for positive-probability evidence
   branches. Preserve the current belief unchanged for the no-evidence branch.
4. **Derive experimental state.** Add `a1` to an immutable simulated completed set, debit `c(a1)`,
   record whether a pair is now open or consumed, and retain a parent-state fingerprint.
5. **Enumerate second actions.** Re-run duplicate, completed-pair, control, evidence-eligibility,
   and branch-wise budget checks. Include `STOP`.
6. **Evaluate second-step EIG.** For a second action that closes a pair, compute EIG using the
   temporary branch posterior. An opener or `STOP` has zero EIG within the two-step horizon.
7. **Choose the best second action per branch.** The choice is conditional on the observed first
   evidence outcome. Optimize the shared cost-normalized utility exactly with the deterministic
   finite ratio loop described above. For a first-step opener there is only one no-evidence branch,
   so the second action is naturally fixed until the real first run is observed.
8. **Aggregate branch values.** Sum immediate EIG and predictive-probability-weighted second-step
   EIG. Independently aggregate expected cost and expected terminal entropy.
9. **Apply cost.** Reject any plan that exceeds budget in any retained branch. Divide total EIG by
   expected total cost only after both are computed. Never divide per-step EIG and add the ratios.
10. **Rank first actions.** Rank by utility, then greater total EIG, lower worst-case sequence cost,
    lower expected cost, and stable candidate ID. Comparisons within the declared numerical
    tolerance are ties.

Only `a1` is suggested for real execution. The contingent `a2` mapping is an explanation of option
value, not a commitment. After the real first experiment and any real evidence update, the engine
replans from persistent state. This prevents a discretized planning branch from overriding the
exact posterior produced by an actual observed comparison.

## 5. Invariants

An implementation is invalid unless all of the following hold.

1. Hidden benchmark truth, true optimizer effect, evaluator redundancy labels, and future noisy
   observations are absent from every planner input.
2. A simulated state is immutable and can never mutate an `ExperimentStore`, real history,
   current belief state, budget ledger, or caller-owned collection.
3. Simulated observations, evidence, belief states, and belief updates are never written to
   SQLite. At most the final real plan trace may be persisted after selection.
4. Hypothesis-conditioned bin masses and predictive branch probabilities are finite,
   non-negative, and normalized within the reasoning tolerance.
5. Every temporary posterior is finite, non-negative, covers exactly the competing hypotheses,
   and sums to one within tolerance.
6. The hard remaining budget is respected in every positive-probability branch, not merely in
   expectation.
7. A completed candidate, duplicate design prohibited by current rules, or already consumed
   matched pair is never suggested or simulated as new evidence.
8. A matched pair contributes at most one evidence event in any simulated lineage. Immediate and
   delayed EIG cannot count the same event twice.
9. Existing `random`, `greedy`, and `information_gain` behavior, ordering, versions, persistence,
   and CLI semantics remain unchanged.
10. Identical candidate order, history, beliefs, costs, budget, model versions, grid, and seed
    produce byte-equivalent plan structure and the same selected candidate.
11. Every real plan records the input belief-state ID, candidate-set fingerprint, completed-state
    fingerprint, budget and costs, model and grid versions, utility version, ranked first actions,
    retained branch probabilities, contingent second actions, and fallback reason.
12. An unmatched single experiment remains an observation, not optimizer-effect evidence.
13. Planner-visible evidence eligibility is a domain rule. It may not be inferred from hidden
    world behavior or evaluator labels.
14. Invalid probability, entropy, cost, or convergence states fail explicitly rather than
    silently falling back to a candidate.

## 6. Numerical Design

### Reuse of the current EIG calculation

`expected_information_gain` currently builds Gaussian bin masses using CDF differences over
`[-0.40, 0.40]` at step `0.01`, with two unbounded tail bins. This produces 82 bins. The same
mass calculation, posterior mixture, and entropy kernel can be reused for every evidence-producing
node in the two-step tree. Reuse should be through a pure, tested numerical interface; the current
one-step policy's outputs must remain bit-for-bit stable.

The current model is candidate-independent: all valid matched pairs use means `+0.10`, `0.00`,
and `-0.10` with standard deviation `0.05`. Two-step planning must not pretend that controls,
benchmark noise level, or cost alter these distributions unless a later, explicit model version
adds that capability.

### Approximation and safeguards

- The calculation is exact for the quantized evidence variable, not for a continuous observation.
  Quantization generally understates continuous mutual information. Tail aggregation and coarse
  bins can also hide outcome-dependent second choices.
- Each hypothesis mass vector is normalized with `math.fsum`. The predictive mixture is then
  normalized once more before aggregation. Renormalization factors are recorded in diagnostics.
- A branch with exactly zero predictive mass is omitted. Tiny positive branches are retained for
  utility; the existing explanatory threshold must not become an unstated planning-pruning rule.
- For each positive branch, posterior weights are divided by an `fsum` normalization constant and
  validated with the same probability tolerance as real beliefs.
- Entropy is bounded to `[0, log2(number_of_hypotheses)]`. A value outside that range by more than
  tolerance is an error; only a tiny floating-point excursion may be clamped.
- Expected information gain below zero by more than tolerance is an error. A tiny negative value
  from cancellation is clamped to zero.
- Floating-point ties use one declared absolute tolerance, proposed as `1e-12`. Ties then use total
  EIG, worst-case cost, expected cost, and candidate ID in that order. Branch second-action ties use
  the same rule.
- Fractional-utility iteration records every `rho`, residual, and selected branch action. Stable
  choices terminate the loop even if two floating-point ratios differ below tolerance.

### Numerical validation tests

- Every hypothesis mass vector, branch mixture, and temporary posterior sums to one.
- One-step EIG computed through the shared kernel exactly matches current fixtures.
- A hand-calculated two-hypothesis, two-bin fixture matches total EIG and contingent actions.
- Grid steps `0.02`, `0.01`, and `0.005` show convergence on fixed beliefs without changing
  feasibility or provenance.
- Extreme posteriors such as `(1, 0, 0)` and near-degenerate posteriors produce finite entropy and
  no spurious positive plan.
- Tail-heavy Gaussian fixtures retain all probability and never create negative bin mass.
- Candidate permutations and repeated runs produce identical scores after stable-ID sorting.
- Fractional optimization matches exhaustive contingent-plan enumeration on tiny fixtures.

## 7. Computational Complexity

Let:

- `N1` be the number of feasible first-step candidates;
- `N2` be the maximum number of feasible second-step candidates in a branch;
- `H` be the number of hypotheses; and
- `M` be the number of evidence bins.

One EIG calculation costs `O(H * M)` time. If a first action opens a pair, it has one no-evidence
branch and costs `O(N2 * H * M)` to evaluate. If it closes a pair, it has up to `M` first branches,
each with up to `N2` second candidates, for `O(N2 * H * M^2)` time. Across first actions, the
worst-case time is

```text
O(K * N1 * N2 * H * M^2),
```

where `K` is the small deterministic number of ratio-optimization iterations. With the current
prototype (`H = 3`, `M = 82`, and at most 16 benchmark candidates), this is millions of simple
numeric operations per full decision, not an open-ended search.

A streaming implementation needs `O(H * M + N2)` working space plus retained top-plan
diagnostics. Materializing every branch and score would use `O(N1 * N2 * H * M^2)` space and is
unnecessary.

Computation grows too quickly if the candidate set, observation grid, or horizon is generalized.
Only these minimal deterministic controls are justified now:

- cache Gaussian bin-mass vectors by hypothesis-model and grid version;
- cache EIG by normalized posterior tuple and model/grid version;
- cache counterpart and feasibility results by simulated completed-state fingerprint;
- stream first-outcome branches while retaining only required explanation summaries;
- deduplicate calculations for identical candidate designs while preserving distinct IDs for
  ranking and provenance; and
- keep horizon exactly two and omit only exactly zero-probability branches.

Arbitrary-depth planning, Monte Carlo tree search, and a generic POMDP solver are outside scope.

## 8. Benchmark Design

The existing benchmark must remain available unchanged. A separate versioned delayed-information
suite should add the following small worlds. All hidden truths remain evaluator-only. "Publicly
inadmissible" means a domain rule visible without truth; "latent irrelevant" means a deliberately
misspecified stress case that the planner cannot identify in advance.

| World | Initial state, candidates, budget | Truth and noise | Intended test |
| --- | --- | --- | --- |
| `delayed_tight_pair` | Empty history; one valid pair at cost `1 + 1`, one cheaper unmatched opener at `0.5`; budget `2` | Adam advantage, low noise | The useful opener has zero immediate EIG; spending first on the decoy prevents pair completion. |
| `delayed_asymmetric_trap` | Empty history; pair A costs `0.25 + 2.5` and cannot fit; pair B costs `1 + 1`; budget `2.25` | SGD advantage, medium noise | Cost and experiment order matter: the cheapest opener belongs to an infeasible sequence. |
| `irrelevant_openers` | Empty history; several publicly inadmissible or unmatched cheap openers plus one valid `1 + 1` pair; budget `2` | No advantage, low noise | Lookahead should ignore structurally zero-value openers without seeing truth. |
| `one_step_closer_available` | One real unmatched SGD run is preloaded; its Adam counterpart costs `1`; budget `1` | Adam advantage, low noise | Immediate EIG is sufficient; lookahead has no second-step advantage. |
| `natural_fallback_succeeds` | Empty history; two equivalent adjacent pairs, all costs `1`; budget `2` | SGD advantage, low noise | Lowest-cost/ID fallback already opens a useful pair, mirroring the current suite. |
| `conditional_stop` | Two valid pairs are pre-opened; two closers fit, but one decisive first result may leave negligible uncertainty | Adam advantage, medium noise | Test conditional second action versus fixed advance commitment, including `STOP`. |
| `high_noise_expensive_pair` | Empty history; one valid pair costs `1.5 + 1.5`; cheaper objective-oriented candidates do not form evidence; budget `3` | No advantage, high noise outside the fixed model's comfort range | Lookahead may be actively worse through cost and overconfident noisy evidence. |
| `latent_irrelevant_pair` | Empty history; one cheap pair is operationally admissible but its effect is unrelated to the target, plus one costlier valid pair; tight budget | Adam advantage, medium noise | Detect model misspecification and benchmark-artifact exploitation; avoidance is not expected without a public relevance signal. |

The preloaded run in `one_step_closer_available` is generated before policy comparison and is
identical for every policy. It produces no initial evidence, so all policies receive the same
initial belief. Candidate IDs and list order should be permuted in companion variants while
preserving designs and costs.

### Expected policy behavior

These are hypotheses to test, not guaranteed outcomes.

| World | random | greedy | information_gain | two-step lookahead |
| --- | --- | --- | --- | --- |
| `delayed_tight_pair` | Sometimes completes the pair by chance; high variance. | May pursue a high predicted objective and miss the pair. | Likely takes the cheapest zero-EIG decoy, then cannot close. | Should choose a valid opener whose counterpart fits and complete one pair. |
| `delayed_asymmetric_trap` | Sometimes spends budget on the infeasible cheap sequence. | May prefer whichever opener resembles high observations. | Lowest-cost fallback is expected to enter pair A and strand the budget. | Should compare sequence costs and enter pair B. |
| `irrelevant_openers` | Often wastes one of two actions. | No reliable reason to complete the valid pair. | Tie-breaking is expected to favor a cheap opener. | Should assign zero two-step value to publicly inadmissible or unmatchable openers. |
| `one_step_closer_available` | May or may not select the closer. | Depends on predicted objective. | Should select the positive immediate-EIG closer. | Should select the same closer; no material gain is expected. |
| `natural_fallback_succeeds` | Sometimes completes a pair. | Outcome-dependent. | Should open and then close the first pair through fallback and immediate EIG. | Should behave equivalently after cost normalization. |
| `conditional_stop` | Does not plan conditionally. | Does not plan conditionally. | Chooses one closer at a time and replans only after execution. | May precompute `STOP` for decisive branches and a second closer for ambiguous branches; real execution still replans. |
| `high_noise_expensive_pair` | May conserve or waste cost by chance. | May obtain a better objective but little evidence. | May or may not open the expensive pair depending on fallback. | May aggressively buy misleading evidence and can be worse on calibration and cost. |
| `latent_irrelevant_pair` | Mixed behavior. | Objective-driven and not reliably scientific. | Can treat the latent-irrelevant pair as valid evidence if completed. | Can prefer the cheap wrong pair because the model says it is informative; this is an expected failure signal. |

## 9. Evaluation Protocol

Every comparison uses the same hidden world, seed, initial belief, initial experiment history,
candidate specifications, candidate ordering, costs, and budget. The planner receives none of the
hidden truth fields. The primary paired contrast is two-step lookahead minus the unchanged
one-step `information_gain` policy. Random and greedy remain contextual baselines.

### Scientific-progress metrics

- final posterior entropy;
- entropy reduction per unit cost, defined as
  `(initial_entropy - current_entropy) / cumulative_cost`, not the current residual-entropy-per-cost
  field;
- probability assigned to the true hypothesis;
- sustained 0.80 and 0.95 confidence crossing, defined as the earliest step at which the true
  hypothesis probability reaches the threshold and remains at or above it through the run;
- matched informative pairs completed;
- redundant experiments selected; and
- total experimental cost.

Calibration and true-hypothesis rank remain important diagnostics. "Matched informative pairs"
is an evaluator metric; operational reasoning must not use that label. Best observed objective is
reported separately as a secondary optimization metric and never enters planner utility.

### Seed and statistical protocol

- **Smoke test:** 5 seeds per world and policy, used only for correctness, runtime, and output
  inspection. No inferential claim is permitted.
- **Larger benchmark:** 100 predeclared seeds per world and policy. Seeds are paired across policies
  and must not be selected after viewing results.
- **Confidence intervals:** deterministic 10,000-resample percentile bootstrap intervals over
  paired seed-level differences, reported at 95%. World-level aggregate intervals resample paired
  `(world, seed)` blocks.
- **Paired comparison:** report mean and median paired differences between lookahead and one-step
  EIG. Preserve each seed's common noisy world rather than treating policy runs as independent.
- **Effect sizes:** report relative change in entropy reduction per cost, paired standardized mean
  difference `mean(delta) / sd(delta)` when variance is nonzero, median paired difference, and the
  fraction of paired runs won, tied, and lost.
- **Threshold outcomes:** report paired success-count differences and paired time/cost differences
  only among clearly labeled comparable runs. Do not impute an arbitrary crossing time for
  failures.
- **Multiple comparisons:** predeclare entropy reduction per cost on delayed worlds as the single
  primary endpoint. Other metrics and per-world contrasts are secondary. If p-values are later
  added, use Holm correction within each declared comparison family; unadjusted intervals must be
  labeled exploratory.

No statistical significance claim should be made from the smoke test or the current three-seed
outputs.

## 10. Ablation Plan

| Ablation | Comparison | Conclusion enabled |
| --- | --- | --- |
| One-step vs two-step | Same EIG model, feasibility, utility family, and tie rules; vary only horizon | Whether delayed option value, rather than another policy change, causes improvement. |
| Cost-aware vs cost-unaware | `IG_total / Cost_total` versus maximum `IG_total` under the same hard budget | Whether gains depend on accounting for sequence cost or merely completing more pairs. |
| Conditional vs fixed second step | Branch-specific `a2(z1)` versus one `a2` chosen before `z1` | Whether adaptivity to first evidence adds value beyond committing to a two-run sequence. |
| Observation discretization | Grid steps `0.02`, `0.01`, `0.005` with identical tails | Whether ranking and conclusions are numerical artifacts of the 0.01 grid. |
| Noise level | Low, medium, high with unchanged policy-visible model unless explicitly versioned | Whether lookahead is robust or becomes overconfident under noisy evidence. |
| Budget | Just below pair cost, exactly pair cost, and one extra candidate cost above it | Whether advantage appears only at a hand-picked budget boundary. |
| Cost symmetry | Equal pair costs versus optimizer- and pair-asymmetric costs | Whether cost awareness avoids cheap-opener traps and expensive sequences. |

The ablation suite must be specified before the larger benchmark is run. Results should be
reported even when they weaken the primary hypothesis.

## 11. Failure Modes and Risks

| Risk | Detection method or test |
| --- | --- |
| Overfitting to synthetic worlds | Hold out world configurations, permute IDs/order, vary controls and budgets, and report performance on untuned seeds. |
| Double-counting evidence | Give every simulated pair a lineage key; assert at most one update per key and verify `IG_total = initial entropy - expected terminal entropy`. |
| Belief overconfidence | Track Brier calibration, entropy, sustained threshold reversals, and contradictory high-noise fixtures. |
| Misspecified hypothesis model | Compare predicted bin frequencies with evaluator observations, run latent-irrelevant and high-noise stress worlds, and report posterior predictive mismatch. |
| Delays longer than two steps | Include a diagnostic world requiring three actions and verify the planner fails or returns zero value honestly rather than implying completeness. Do not extend the horizon in this milestone. |
| High computational cost | Count scored nodes, bins, cache hits, and ratio iterations; enforce a deterministic node ceiling for the fixed prototype configuration. |
| Informative but scientifically irrelevant experiments | Require a versioned public evidence-eligibility rule and separately test latent irrelevance that the policy cannot know. Report objective alignment, not just entropy. |
| Exploiting benchmark artifacts | Repeat runs after candidate-ID and list-order permutations and after swapping equivalent control labels. Equivalent designs should remain equivalent. |
| Leakage of hidden truth | Construct planner contexts with no truth fields, use sentinel truth values that raise on access, and inspect serialized plan provenance for forbidden fields. |
| Confusing information gain with scientific value | Keep the hypothesis family and research objective explicit, report best objective separately, and reject claims that entropy reduction establishes broader scientific importance. |

## 12. Implementation Boundary

The smallest milestone that can test the research hypothesis is an opt-in, benchmark-only,
pure two-step planner. It should not replace `rde suggest`, alter existing policies, or add
general planning infrastructure.

### Files likely to be added

- `research_decision_engine/lookahead.py`: immutable simulated-state, branch, plan, and score
  dataclasses plus the fixed two-step optimizer-effect planner.
- `research_decision_engine/benchmarks/lookahead_worlds.py`: only the versioned delayed-information
  worlds and truth-free public designs.
- `research_decision_engine/benchmarks/lookahead_evaluation.py`: paired comparison using existing
  metrics and output conventions without changing the default benchmark suite.
- `tests/test_lookahead.py`: numerical, invariant, feasibility, determinism, and delayed-opener
  unit tests.
- `tests/test_lookahead_benchmark.py`: paired smoke benchmark, permutation checks, and negative
  worlds.

### Files likely to be modified

- `research_decision_engine/decision.py`, only if needed to expose the existing discretized
  Gaussian outcome kernel as a pure shared interface. Current one-step outputs must remain exact.
- `research_decision_engine/benchmarks/evaluation.py`, only if a small public metric helper is
  needed; existing `BENCHMARK_POLICIES` and default behavior should remain stable.
- No CLI file is required for the benchmark-only milestone.

### Interfaces that remain stable

- `RandomPolicy`, `GreedyPredictedPerformancePolicy`, and `InformationGainPolicy`;
- `expected_information_gain` and current one-step ranking behavior;
- `Hypothesis`, `Evidence`, `BeliefState`, and `BayesianBeliefUpdater`;
- `ExperimentStore`, schema version 3, and all current CLI commands; and
- the current benchmark suite and its saved-output schema.

### Database additions

No database migration is required for the benchmark-only milestone. Simulated branches must never
be persisted, and benchmark plan traces can live in versioned JSON output. If a later reviewed
milestone exposes lookahead through `rde suggest`, a new additive schema version will be required
for real plan metadata and contingent branch summaries. It must not overload current one-step
decision rows or store simulated evidence as real evidence.

### Tests required before acceptance

- A zero-immediate-EIG opener receives positive delayed value only when a feasible counterpart
  exists within the second step.
- A cheaper opener whose pair exceeds budget loses to a feasible sequence.
- First-branch probabilities and every temporary posterior normalize.
- Immediate plus delayed EIG equals initial minus expected terminal entropy.
- Conditional and fixed plans match when only one second action is feasible.
- Duplicate candidates and consumed pairs are excluded in all branches.
- Planner scoring leaves SQLite row counts and current belief state unchanged.
- Planner context has no hidden truth and sentinel truth cannot be accessed.
- Identical inputs and candidate permutations produce deterministic, equivalent plans.
- Tiny exhaustive fixtures validate the cost-ratio optimizer.
- Existing random, greedy, information-gain, reasoning, storage, CLI, and benchmark tests remain
  unchanged and pass.
- A five-seed delayed-world smoke run emits complete per-plan provenance and paired metrics.

No web UI, LLM, cloud service, arbitrary-depth planner, generic search API, or unrelated product
feature belongs in this milestone.

## 13. Acceptance and Rejection Criteria

Correctness gates apply before research performance is considered:

- all invariants and numerical tests pass;
- all existing policy outputs remain unchanged on fixed fixtures;
- no hidden-truth access or persistent simulation write is possible;
- every real first action is feasible and reproducible; and
- every retained branch respects budget and has complete provenance.

After the smoke test, freeze worlds, utility version, seeds, metrics, and margins. On the
100-seed paired benchmark, accept the planner as useful for this prototype only if all of these
hold:

1. In the predeclared delayed-information world family, mean entropy reduction per unit cost is
   at least 10% greater than one-step EIG and the 95% paired bootstrap interval for the absolute
   difference is entirely above zero.
2. Final posterior entropy is lower in the same family, with a positive win rate in a majority of
   paired runs; the benefit is not solely more cost consumption.
3. More valid informative pairs are completed without an increase in redundant selections.
4. In worlds where one-step EIG is sufficient, the upper 95% paired interval for lookahead's final
   entropy regression is below `0.03` bits and entropy-reduction-per-cost regression is below 5%.
5. Results survive candidate-ID/list-order permutations and both symmetric and asymmetric costs.
6. Total cost never exceeds budget, and the hidden-truth isolation tests pass.

Reject or defer the planner if any correctness gate fails, if the primary delayed-world interval
includes zero or favors one-step EIG, if improvement disappears after cost normalization, if it
materially regresses no-delay worlds, if calibration worsens substantially under declared noise
conditions, or if gains depend on leaked truth or candidate-ID artifacts. Also reject the chosen
primary utility if its benefit vanishes under the cost-aware ablations while a simpler constrained
one-step rule performs equivalently.

A rejected hypothesis is acceptable and informative. It would show that two-step option value is
too small, too fragile, or inadequately modeled in this setting, and it would argue against adding
planner complexity.

## 14. Open Questions

1. **What is publicly evidence-eligible?** The current application treats every matched optimizer
   pair as exchangeable evidence, while the benchmark has evaluator-only irrelevant candidates.
   A truth-free domain contract must distinguish structural inadmissibility from latent model
   misspecification before avoidance of "irrelevant" openers can be an acceptance criterion.
2. **Is entropy reduction per expected cost the approved research objective?** It is the proposed
   primary utility, but its preference for cheap partial learning is substantive. Approving it, or
   selecting the constrained-total-EIG alternative, is a product and research decision.
3. **Is deterministic fractional optimization acceptable for the prototype?** It gives an exact
   conditional ratio plan, but adds more numerical machinery than an additive utility. The tiny
   exhaustive validation test is mandatory if retained.
4. **Should a single absolute observation ever affect belief or the second action?** The current
   hypotheses define only optimizer-difference likelihoods, so this design correctly uses one
   no-evidence branch for an opener. Conditional response to absolute values would require a new,
   explicit generative model and is outside this milestone.
5. **What is the stopping rule?** `STOP` is needed to avoid buying negligible second-step
   information. The positive-EIG tolerance is proposed as numerical, not a scientific value
   threshold; any larger threshold would need objective-level justification.
6. **Should planning use bin-event posteriors while real updates use point-density likelihoods?**
   Replanning after execution limits the discrepancy, but the approximation and its provenance
   need explicit acceptance.
7. **How should preloaded unmatched experiments be represented in benchmark provenance?** They
   must be identical across policies, exclude evaluator truth, and not consume the compared run's
   budget unless that accounting choice is predeclared.
8. **What constitutes a material calibration regression?** Acceptance specifies entropy margins
   but a numeric Brier-calibration margin should be frozen before the larger benchmark.
9. **When should real plan persistence be added?** Benchmark JSON is enough to test the research
   hypothesis. CLI and SQLite integration should wait until the planner itself is accepted.
10. **Is two steps the scientifically relevant delay?** It is sufficient for the current matched
    optimizer comparison. A negative result must not be generalized to domains whose evidence
    requires longer protocols.

The repository is technically capable of hosting the benchmark-only milestone, but implementation
should remain blocked until questions 1 and 2 are explicitly resolved: the planner-visible
evidence-eligibility contract and the primary cost/scientific-utility rule cannot be inferred from
the current code without silently changing the research objective.
