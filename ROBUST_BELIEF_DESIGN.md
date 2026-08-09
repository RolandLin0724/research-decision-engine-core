# Likelihood Model Adequacy and Robust Belief Revision

Status: design only  
Proposed milestone: `robust-belief-revision/v1`  
Baseline likelihood: `fixed_sigma_gaussian`  
Proposed likelihood: `replicated_noise_calibrated_gaussian`

This document designs a narrow test of whether replicated matched experiments can
calibrate evidence reliability and reduce confidently wrong conclusions. It does not
change the scientific hypotheses, experiment-selection policies, planning horizons, or
frozen benchmark results.

## 1. Problem Definition

The current engine treats an observed matched optimizer effect as evidence about three
competing hypotheses. Bayesian normalization is internally coherent, but its result is
only as reliable as the likelihood model. A posterior can become sharply concentrated
around the wrong hypothesis when the assumed observation distribution is too narrow.
Lower entropy then means only that the model is more certain under its assumptions. It
does not mean that those assumptions are adequate or that the conclusion is correct.

The frozen 100-seed evaluation demonstrates this distinction. The current hypothesis
models use a Gaussian evidence standard deviation of `0.05`, while the adverse-noise
world generates each arm observation with standard deviation `0.20`. The resulting
matched-effect variation can be larger still because a matched effect is a difference of
two arm observations. The evaluation recorded 257 runs in which posterior entropy fell
while probability assigned to the true hypothesis worsened. Short-budget lookahead was
confidently wrong in 27 percent of adverse-noise runs. These are model-adequacy failures,
not evidence that Bayesian updating or lookahead is intrinsically invalid.

Four kinds of uncertainty must remain distinct:

- **Aleatoric uncertainty** is irreducible variation in observed matched effects under
  repeated execution of the same public experimental design. This milestone estimates
  that variation from replicated matched effects.
- **Epistemic uncertainty** is uncertainty over the three optimizer-effect hypotheses.
  It is represented by the belief-state probabilities and is what evidence updates.
- **Likelihood misspecification** occurs when the distribution used for
  `p(evidence | hypothesis)` does not describe the observed evidence-generating process.
  An underestimated observation standard deviation `sigma`, and therefore an
  underestimated likelihood variance `sigma^2`, converts ordinary noisy outcomes into
  extreme likelihood ratios and false confidence.
- **Planning uncertainty** concerns future observations, feasible action sequences,
  delayed evidence, and costs. It is represented by expected branches in the decision
  policies. It is not a substitute for aleatoric or epistemic uncertainty.

The research question for this milestone is:

> Can a deterministic, prequential estimate of observation standard deviation `sigma`,
> derived only from prior replicated matched effects, improve posterior calibration and
> reduce confidently wrong conclusions while preserving useful learning in the existing
> delayed-information worlds?

The result may be negative. In particular, sparse replications, heterogeneous noise, or
a misspecified hypothesis family may leave the calibrated model no better than the fixed
baseline.

## 2. Frozen Baseline

`fixed_sigma_gaussian` is the unchanged baseline. For hypothesis `h`, observed matched
effect `d`, predicted effect mean `mu_h`, and fixed standard deviation
`sigma_fixed = 0.05`, its likelihood is:

```text
p_fixed(d | h) = Normal(d; mu_h, 0.05^2)
```

The three means remain the current values:

| Hypothesis | Predicted matched effect |
| --- | ---: |
| Adam advantage | `+0.10` |
| No consistent advantage | `0.00` |
| SGD advantage | `-0.10` |

The implementation locations that define this baseline are currently:

- `optimizer_effect.py`: hypothesis IDs, means, and
  `PREDICTED_EFFECT_STANDARD_DEVIATION = 0.05`.
- `reasoning.py`: Gaussian density and Bayesian normalization.
- `decision.py`: discretized Gaussian predictive outcomes used by one-step information
  gain.
- `lookahead.py`: the same predictive outcomes inside the fixed two-step recursion.

The baseline name, parameter, update behavior, policy versions, and saved
`paired-evaluation-v1-100-seeds` artifacts are frozen. This milestone must not rewrite,
relabel, regenerate in place, or retroactively reinterpret those results. New runs must
use a new evaluation version and output directory. `fixed_sigma_gaussian` remains the
runtime default until every acceptance gate in Section 8 passes.

## 3. Proposed Noise-Calibrated Model

The only alternative in this milestone is
`replicated_noise_calibrated_gaussian/v1`. It keeps the same three hypothesis means and
the same Bayesian update. It replaces only the matched-effect observation standard
deviation with a deterministic estimate of repeatability for the relevant public
comparison group.

### Evidence used to estimate observation standard deviation

For replication `r`, define the matched optimizer effect as:

```text
d_r = observed_value(adam, r) - observed_value(sgd, r)
```

Observation standard deviation is estimated from prior matched effects in the same
noise-estimation group. A noise-estimation group is identified by:

```text
(experiment family,
 comparison-group ID,
 controlled-variable fingerprint,
 intervention variable)
```

The replication identifier is deliberately excluded from this group key and included in
each observation key. Effects from different controls or public comparison groups are
not pooled in version 1. The estimator operates on matched effects, not on raw arm
outcomes, because the belief likelihood is defined over the Adam-minus-SGD comparison.
This also avoids assuming independence or equal observation variance between the two
arms.

### Terminology and units

Let the matched effect have unit `U`, the same unit as the observed objective
difference. Hypothesis means, `sample_mean`, `sample_standard_deviation`,
`sigma_fixed`, `sigma_floor`, and `estimated_sigma` all have unit `U`.
`sample_variance`, `variance_floor`, and likelihood or predictive variances have unit
`U^2`. The model estimates `sigma` in unit `U`; it does not directly estimate a variance.
The numeric value `0.05` is always a standard deviation in this document. Its squared
variance is `0.0025`.

### Deterministic estimator

Let `D_<t = (d_1, ..., d_n)` be the ordered effects that were completed and eligible
strictly before evidence `d_t` is updated. With `n >= 5`, calculate the ordinary sample
standard deviation with Bessel correction (`ddof = 1`):

```text
sample_mean               = sum(d_i) / n
sample_variance           = sum((d_i - sample_mean)^2) / (n - 1)
sample_standard_deviation = sqrt(sample_variance)
estimated_sigma           = max(sample_standard_deviation, sigma_floor)
sigma_floor               = 0.05
variance_floor            = sigma_floor^2 = 0.0025
```

`estimated_sigma` is the model parameter. `sample_variance` is only an intermediate
calculation in squared matched-effect units. The declared minimum is exactly five prior
valid matched-effect observations in the same public comparison group. The current
evidence is observation `n + 1`; it is not included in `D_<t`.

The declared standard-deviation floor is `sigma_floor = 0.05`, equal to the frozen
baseline `sigma`. Its corresponding variance floor is `variance_floor = 0.0025`. The
calibrated model can become less confident than the baseline but never more confident
solely because replicated effects happen to have a small sample standard deviation.
There is no upper bound on `estimated_sigma`. A large finite sample standard deviation is
scientific information that evidence is unreliable under this comparison group; capping
`estimated_sigma` would recreate false precision.

### Cold-start behavior

Before five prior valid matched effects exist, the model uses the frozen baseline
`sigma_t = 0.05` and records `sigma_source = baseline_fallback` and
`fallback_reason = insufficient_prior_matched_effects`. This is not a calibrated
estimate. Evidence is still updated, so this milestone does not add an abstention or
evidence-buffering policy. Consequently, early overconfidence remains a known risk and
is part of the evaluation.

Once the five-observation minimum is reached, `estimated_sigma` is recomputed before each
new belief update from only the strictly earlier eligible effects. It is immutable for
that update. After the real update completes, the current effect may become eligible for
future estimates, but it can never contribute to the likelihood used for its own update.

### Deterministic calibration-only prefix

The paired benchmark always supplies the five required prior effects through a
calibration-only prefix. For every unique
`(world_id, evaluation_seed, comparison_group_key)`, the evaluator generates exactly five
valid calibration matched effects before any decision-phase experiment or belief update.
The prefix key excludes policy, budget, and belief model, so the exact same five
calibration observations are reused by both budgets, all four policies, and both belief
models for that world, evaluation seed, and public comparison group.

Calibration prefix records use a dedicated `calibration` namespace. Their candidate,
experiment, replication, matched-effect, and cost identities cannot collide with or mark
complete any decision-phase candidate. The five prefix effects have five distinct
replication IDs and five distinct pair-level calibration seeds. Calibration seed keys use
the `calibration` namespace, while all decision-phase seed keys use the `decision`
namespace; the two key spaces are disjoint by construction.

The five effects are inputs only to the sample-standard-deviation calculation. They are
not `Evidence`, never appear in a belief state's evidence lineage, never produce a belief
update, and never support or contradict any hypothesis. Both belief-model lineages remain
at the declared uniform scientific prior after the prefix. The fixed-sigma lineage
receives references to the same calibration records for pairing and audit but does not
use them in its likelihood.

This protocol deliberately isolates likelihood calibration from hypothesis learning.
Calibration observations contain no hidden-hypothesis ID, true-effect field, benchmark
noise label, or evaluator correctness label. The estimator centers the five observed
matched effects around their sample mean and exposes only the resulting sigma snapshot
and its provenance to the calibrated likelihood. Policies and belief updaters cannot read
the individual calibration effects or their sample mean as scientific signal.

Exactly five valid prefix effects therefore exist strictly before the first calibrated
decision-phase evidence update in every public comparison group. The first calibrated
decision-phase update uses those five effects and is active immediately; it does not use
the current decision evidence in its own sigma estimate.

### Leakage prevention

The estimator may read only public design metadata, successful experiment records,
calibration matched-effect records, eligible prior decision-phase matched effects,
evidence creation order, and prior sigma-estimate provenance. It
must not read:

- hidden true hypothesis or true optimizer effect;
- benchmark noise parameters or noise labels;
- future candidate outcomes;
- the current matched effect before its sigma estimate is frozen;
- correctness, Brier score, NLL, calibration error, or confidently-wrong labels.

Ordering is by persisted evidence sequence, with stable evidence ID as a defensive tie
breaker. Wall-clock time alone is not used because equal or externally supplied
timestamps could make ordering ambiguous. The current evidence ID must appear explicitly
in the estimate provenance as excluded.

The strict-before rule applies identically in normal operation, benchmark evaluation,
and hypothetical planner simulation. A likelihood for simulated evidence at branch time
`t` may use only eligible matched effects represented in the simulated state strictly
before `t`. The simulated current evidence outcome is never used to estimate the
`sigma_t` that scores that same outcome. Simulated effects and sigma estimates remain
immutable, in memory, and outside SQLite.

For this milestone, planning uses the real sigma snapshot available at the start of a
decision. The one-step and two-step algorithms do not simulate future sigma learning.
That snapshot may contain the five calibration effects and eligible decision-phase
replications completed strictly before the real decision. All hypothetical branches use
the fixed predecision snapshot. A hypothetical current outcome and every later branch
outcome are excluded from the sigma used to score that outcome. After the first real
experiment, receding-horizon planning recomputes from persisted real state. This
preserves the existing planning recursion and prevents hypothetical or current evidence
from entering its own likelihood.

## 4. Replicated Evidence Contract

The existing public structural eligibility contract permits one Adam arm and one SGD arm
per comparison group. Replication therefore needs an explicit application-level contract
rather than an exception hidden in policy or benchmark code.

### Public identities

Each replicated execution declares:

- `comparison_group_key`: experiment family, comparison-group ID, controlled-variable
  fingerprint, and intervention variable;
- `replication_id`: optional stable public identifier for one matched execution;
- `intervention_arm`: exactly `adam` or `sgd`;
- `replication_seed`: optional declared deterministic pair-level seed;
- source experiment ID and completion status.

At least one of `replication_id` or `replication_seed` is required. Define the public
`replication_token = (replication_id, replication_seed)`, retaining `None` for an
undeclared component. A matched replication key is
`(comparison_group_key, replication_token)`. The two arms in one matched replication
share this key. Every replication in the same public comparison group has a distinct
token, so at least one of its declared seed or replication ID is distinct. Candidate IDs
may remain globally unique, but they are not a substitute for replication identity.

### Valid replication

Two experiments form one valid replicated matched effect only when all conditions hold:

1. Both completed successfully and have complete provenance.
2. Their experiment family, comparison-group ID, controlled variables, and intervention
   variable are identical.
3. Their intervention arms are complementary, with exactly one Adam and one SGD arm.
4. Their public `replication_token` is identical within the pair.
5. No third successful arm competes for the same matched replication key.
6. Their declared replication seed or replication ID distinguishes the replication from
   every other replication in the same public comparison group.
7. Neither source arm nor the matched source pair has already been consumed to derive a
   matched effect in the same phase and namespace.

Failed, cancelled, partial, ambiguous, or outcome-dependent pairings do not count. A
single experiment never estimates an optimizer effect and never contributes to a
matched-effect sample-standard-deviation calculation.

### Calibration replication and seed coupling

Each calibration matched effect uses one public replication ID shared by its Adam and SGD
arms. The two arms also share the same comparison-group key, controlled-variable
fingerprint, pair-level calibration seed, and shared-stochastic-factor key. Arm-specific
observation noise remains independent.

For calibration replication `r`, deterministic randomness is keyed as follows:

```text
shared_key(r) = key("calibration", world_id, evaluation_seed,
                    comparison_group_key, replication_id, replication_seed,
                    "shared")

adam_noise_key(r) = key("calibration", world_id, evaluation_seed,
                        comparison_group_key, replication_id, replication_seed,
                        "noise", "adam")

sgd_noise_key(r) = key("calibration", world_id, evaluation_seed,
                       comparison_group_key, replication_id, replication_seed,
                       "noise", "sgd")
```

Both arms use `shared_key(r)` for shared stochastic factors. The Adam and SGD
observation-noise draws use their distinct arm keys and are independent deterministic
draws. They must not receive identical observation noise. This pairing can cancel shared
nuisance variation without artificially cancelling arm-specific noise.

The observation structure is:

```text
y_adam,r = mean_adam + shared_nuisance(shared_key(r))
           + arm_noise(adam_noise_key(r))

y_sgd,r  = mean_sgd + shared_nuisance(shared_key(r))
           + arm_noise(sgd_noise_key(r))
```

`key(...)` uses the existing versioned SHA-256-based deterministic benchmark keying and
standard-normal transform. Every key component is serialized in provenance. The two
arm-noise keys are distinct inputs to independent draws even though both arms share the
same declared experimental seed for shared factors.

The calibrated `estimated_sigma` is the standard deviation of the resulting matched
effect `d_r = y_adam,r - y_sgd,r`. It is not the standard deviation of either individual
arm. If each independent arm-noise term has variance `v_arm`, the arm-noise contribution
to matched-effect variance is `2 * v_arm`; shared nuisance terms cancel only to the extent
defined by the paired world. All sigma values in the calibrated likelihood remain in
matched-effect units `U`.

The calibration prefix has exactly five distinct replication IDs. Each produces exactly
two successful arms and one immutable calibration matched-effect record. An arm can
belong to only one calibration replication, and a pair can be derived only once. The
resulting immutable matched-effect record may be referenced by later sigma estimates; that
reference is not re-pairing or re-consuming the source experiments.

### Grouping and duplicate prevention

The observed effect is grouped under the public comparison-group key, while evidence
identity is derived from the sorted source experiment IDs, replication key, and
derivation version.
The following uniqueness rules are required:

- one calibration matched-effect record per calibration source pair;
- zero scientific evidence records per calibration source pair;
- one decision-phase evidence record per decision-phase source pair;
- one completed arm per `(comparison_group_key, replication_token, intervention_arm)`;
- one matched effect per `(comparison_group_key, replication_token)`;
- one belief update per `(belief_model_id, lineage_id, evidence_id)`;
- one source inclusion per `(sigma_estimate_id, source_matched_effect_id)`.

An earlier decision-evidence item may play two traceable roles: it may already have
updated its lineage's belief state, and it may later serve as a prior source for a future
sigma estimate. That is not a calibration-only record or a second belief update, but it is
an empirical-Bayes dependency and must be visible in provenance. The current evidence is
never among the sources for its own sigma estimate.

Calibration matched effects have only the noise-estimation role. Their separate namespace
and record type make it invalid to attach them to a scientific belief update.

## 5. Belief Update Semantics

For current matched effect `d_t`, hypothesis mean `mu_h`, and effective standard
deviation `sigma_t`, the proposed likelihood is:

```text
L_t(h) = p(d_t | h, sigma_t)
       = 1 / (sqrt(2*pi) * sigma_t)
         * exp(-(d_t - mu_h)^2 / (2 * sigma_t^2))
```

The posterior remains:

```text
log_weight_t(h) = log posterior_<t(h) + log L_t(h)
posterior_t(h)   = exp(log_weight_t(h) - logsumexp_h(log_weight_t(h)))
```

Using log weights for the new model avoids underflow for extreme residuals. The result
must be finite, non-negative, and normalized to one within the existing numerical
tolerance. A non-finite observation, mean, sample standard deviation, `estimated_sigma`,
likelihood variance `estimated_sigma^2`, log likelihood, or normalization constant is an
explicit failed update. The engine must leave the prior state current and must not
persist a partial update.

The likelihood parameter and its squared variance are:

```text
sigma_t          = estimated_sigma
                 = max(sample_standard_deviation, 0.05)
likelihood_variance_t = sigma_t^2
variance_floor       = 0.05^2 = 0.0025
```

Under fewer than five strictly prior valid replications, `sigma_t = 0.05` and the event
is explicitly labeled as a baseline fallback. When the raw sample standard deviation is
unexpectedly large, the model does not clamp it downward. The hypothesis likelihoods
become more similar, so the observation causes a smaller belief change. The large
`estimated_sigma` also contributes to model-adequacy diagnostics. This behavior is
conservative about the existing three hypotheses, but it does not prove that any of them
is adequate.

Every sigma estimate requires this provenance:

- stable estimate ID and `replicated-noise-calibrated-sigma/v1` version;
- calibrated belief-model ID, lineage ID, and public comparison-group key;
- ordered calibration matched-effect IDs and any eligible prior decision-evidence IDs;
- exact source experiment IDs, replication IDs, pair-level seeds, and phase namespaces;
- exact source count, ordering rule, and strict pre-update sequence cutoff;
- current evidence ID explicitly excluded;
- sample mean, `ddof = 1`, raw sample standard deviation, applied
  `sigma_floor = 0.05`, and final `estimated_sigma`;
- `calibrated` or `baseline_fallback` status and any fallback reason;
- creation time and source-code version.

Every belief update additionally records the sigma-estimate ID, likelihood-model ID,
effective `sigma_t`, likelihood variance `sigma_t^2`, per-hypothesis log likelihood and
likelihood, prior weight, posterior probability, normalization method, source evidence,
and before/after belief-state IDs. A stored explanation must therefore reconstruct:

```text
experiments -> matched effect -> prior replication effects -> sigma estimate
            -> per-hypothesis likelihoods -> posterior
```

For a prefix source, the chain begins with calibration experiments and ends at the sigma
estimate; it has no edge to scientific `Evidence` or a belief update.

### Isolated parallel belief-model lineages

The benchmark maintains exactly two isolated lineages:

- `fixed_sigma_gaussian`
- `replicated_noise_calibrated_gaussian`

Both lineages reference the same real decision-phase experiment records and the same
derived scientific evidence records in the same chronological order. They begin from
separate but numerically identical uniform-prior belief states. Each belief state and
belief update carries both an explicit `belief_model_id` and a stable `lineage_id` derived
from the benchmark condition and model identity.

The lineages maintain separate belief states, belief updates, likelihood calculations,
model-adequacy diagnostics, sequence numbers, and provenance. The fixed lineage always
uses `sigma = 0.05`. The calibrated lineage uses its own eligible sigma snapshot. Neither
lineage may read the other lineage's posterior probabilities, diagnostics, likelihoods,
updates, or current-state pointer. Shared experiment, decision-evidence, calibration, and
cost records are immutable inputs, not shared epistemic state.

Calibration matched effects are visible only to the sigma-estimation boundary and audit
queries. They are not part of either lineage's scientific evidence set. Consequently,
after all five prefix effects are persisted, both lineages still hold the declared prior
and have zero scientific belief updates.

## 6. Model Adequacy Diagnostics

Model adequacy is evaluated prequentially. Each diagnostic scores a real matched effect
against the predictive distribution frozen before that effect was incorporated. No
diagnostic may rescore an observation using parameters estimated from that same
observation.

Adequacy diagnostics are computed separately inside each belief-model lineage from
decision-phase scientific evidence only. Calibration-prefix effects estimate sigma but do
not count as historical predictive residuals, posterior predictive checks, or evidence.
One lineage's diagnostics are never inputs to the other lineage.

For pre-update belief probabilities `b_<t(h)`, define the posterior predictive mixture:

```text
p_pred(d_t) = sum_h b_<t(h) * Normal(d_t; mu_h, sigma_t^2)
```

The system records these diagnostics:

### Posterior predictive checks

Compute the deterministic predictive CDF value `u_t = F_pred(d_t)` and two-sided tail
probability `2 * min(u_t, 1 - u_t)`. Report predictive quantiles and whether the effect
falls inside the 50, 80, and 95 percent central predictive intervals. No Monte Carlo
simulation is required for the three-component Gaussian mixture; quantiles can be found
by deterministic bounded bisection.

### Standardized residuals

Report the mixture-moment residual:

```text
mu_pred = sum_h b_<t(h) * mu_h
var_pred = sigma_t^2 + sum_h b_<t(h) * (mu_h - mu_pred)^2
z_t = (d_t - mu_pred) / sqrt(var_pred)
```

Also retain per-hypothesis residuals `(d_t - mu_h) / sigma_t` for traceability. Because
the predictive distribution is a mixture, `z_t` is a scale diagnostic rather than a
claim that the residual itself is exactly standard normal.

### Empirical coverage

Across prequential checks, report observed coverage at 50, 80, and 95 percent together
with Wilson 95 percent intervals. Coverage is stratified by public comparison group, world,
policy, belief model, and noise condition where sample size permits. Aggregation must not
hide a severely inadequate group behind well-behaved groups.

### Predictive log likelihood

Record `log p_pred(d_t)` before every update and cumulative and mean prequential log
likelihood. Compare the calibrated and baseline models on paired evidence streams. Higher
predictive log likelihood is better, but this metric alone does not establish calibrated
hypothesis probabilities.

### Calibration error and confidently-wrong rate

In benchmark evaluation only, retain the frozen definitions:

- top-label expected calibration error with ten equal-width confidence bins;
- multiclass Brier score;
- NLL of the hidden true hypothesis;
- confidently wrong when the stable top hypothesis is not truth and its posterior is at
  least `0.80`.

These diagnostics require hidden truth and therefore belong exclusively to the evaluator.
They must not be available to the belief model, policies, planner context, runtime model
status, or sigma estimator.

### Adequacy status

The truth-free runtime status has exactly three serialized values:

- `adequate`
- `uncertain`
- `appears_misspecified`

For the latest eligible prequential observation, define:

```text
tail_alarm_t = posterior_predictive_tail_probability_t < 0.05
residual_outlier_t = abs(standardized_residual_t) > 3.0
repeated_residual_alarm_t
  = count(residual_outlier in the last up to 5 eligible observations) >= 2
diagnostics_disagree_t = tail_alarm_t != residual_outlier_t
```

The rolling residual window contains the latest five eligible observations when five or
more exist, and all eligible observations when fewer than five exist. Classification uses
this deterministic precedence:

1. `appears_misspecified` if `tail_alarm_t` or `repeated_residual_alarm_t` is true.
2. Otherwise, `uncertain` if fewer than 10 historical predictive residuals exist or
   `diagnostics_disagree_t` is true.
3. Otherwise, `adequate`.

With no eligible predictive residual, both alarms are unevaluable and the state is
`uncertain` by rule 2.

An alarm therefore takes precedence over the small-sample `uncertain` state. One isolated
standardized residual beyond `3.0` with tail probability at least `0.05` is a diagnostic
disagreement and remains `uncertain`; two such residual outliers among the last five
eligible observations trigger `appears_misspecified`. A posterior predictive tail
probability exactly equal to `0.05` does not cross the strict threshold, and an absolute
standardized residual exactly equal to `3.0` is not an outlier.

Empirical coverage, predictive log likelihood, Brier score, NLL, and calibration error
remain reported diagnostics but do not add hidden classification thresholds in version
1. Truth-dependent metrics are evaluator-only and can never determine the operational
adequacy state. These are predeclared first-version rules to be tested, not universal
scientific constants. Any threshold or precedence change creates a new diagnostic
version.

## 7. Evaluation Protocol

The comparison is frozen in advance to exactly two belief models:

1. `fixed_sigma_gaussian`
2. `replicated_noise_calibrated_gaussian`

Exactly the existing four policies are evaluated without algorithm or policy-version
changes:

1. `random`
2. `greedy`
3. `information_gain`
4. `lookahead_information_gain`

The two belief models receive the same three hypotheses, numerically identical uniform
priors, public candidates, costs, replication identities, calibration observations, and
decision-phase observations. Only the likelihood model and resulting isolated belief
lineage differ.

For each `(world, evaluation_seed, budget, policy)` condition, the existing policy runs
exactly once. The current default `fixed_sigma_gaussian` lineage is the decision-stream
controller: it supplies the belief state used by belief-aware policy calls and therefore
determines the real candidate sequence. After each real experiment, the same immutable
decision-phase experiment and evidence records are delivered in the same order to both
lineages. The calibrated lineage is a shadow scientific-reasoning lineage in this
evaluation and cannot alter candidate selection.

This fixed-stream design isolates belief-model adequacy. It does not estimate the
closed-loop effect of letting calibrated beliefs change future decisions. Random, greedy,
one-step information gain, and two-step lookahead retain their current algorithms,
versions, budgets, feasibility rules, and tie breaking. The policy name still determines
which shared stream is produced, but the two belief models never receive different
decision observations within that policy condition.

The current four research worlds remain the scientific conditions:

- delayed information;
- no optimizer advantage;
- adverse noisy observations;
- asymmetric experiment costs.

Before each decision stream begins, the deterministic calibration-only prefix supplies
five valid prior matched effects for every public comparison group. Prefix observations
are keyed only by world, evaluation seed, and public comparison group, so both budgets,
all policies, and both belief models receive byte-identical calibration inputs. The old
two-pair decision candidate set and all frozen version 1 outputs remain unchanged
historical artifacts. Calibration-only candidates use a separate namespace and cannot
remove or block decision candidates.

Run both belief models on the same 100-seed schedule. Reuse the exact budgets from the
completed paired evaluation:

- short budget: `2.25` cost units;
- large budget: `4.50` cost units.

These budgets are frozen before calibrated-model results exist and must not be enlarged,
reduced, or replaced after those results are inspected. Calibration cost is outside these
decision budgets but is never omitted from reporting.

The evaluator may access the hidden true hypothesis and truth-dependent scores only after
all policy decisions and both lineage updates for a run are complete. Hidden truth is
absent from calibration generation interfaces, sigma estimation, policy inputs, belief
updates, and model-adequacy diagnostics.

### Calibration and decision cost ledgers

Every run exposes two disjoint ledger views. Decision entries belong to that run;
calibration entries are referenced from the shared prefix ledger:

```text
calibration_cost = sum of costs for all calibration-prefix arm executions
decision_cost    = sum of costs for all real decision-phase experiments
combined_total_cost = calibration_cost + decision_cost
```

The prefix executes five two-arm matched replications for each public comparison group.
Each calibration arm is priced by the same deterministic public cost function as its
corresponding decision design, but its record is written only to the calibration ledger.
Calibration cost does not consume or reduce the `2.25` or `4.50` decision budget.
Decision-phase experiments write only to the decision ledger. A database constraint and
ledger audit must reject any record assigned to both ledgers.

`calibration_cost` is incurred to make the calibrated model operational. Ledger entries
are recorded once per `(world_id, evaluation_seed, comparison_group_key)` prefix and are
referenced, not duplicated, by policy, budget, and lineage runs. Each run reports the
full prefix cost attributable to a standalone calibrated deployment. Suite-level physical
cost deduplicates shared prefix IDs before summing. The fixed model does not require that
prefix in deployment. Reports therefore show all of:

```text
decision_cost
calibration_cost
combined_total_cost = calibration_cost + decision_cost
fixed_model_required_cost = decision_cost
calibrated_model_required_cost = combined_total_cost
```

Decision-phase scientific efficiency uses only `decision_cost` and answers how beliefs
changed while both models consumed the same decision stream. End-to-end calibrated
efficiency uses `combined_total_cost`. For entropy reduction, for example:

```text
decision_phase_efficiency
  = (initial_entropy - final_entropy) / decision_cost

calibrated_end_to_end_efficiency
  = (initial_entropy - final_entropy) / combined_total_cost
```

Zero-cost denominators are reported as undefined, never coerced. A calibrated model may
improve belief accuracy and calibration while remaining unattractive after calibration
cost is included. No report may claim end-to-end cost improvement from decision-phase
efficiency alone.

Predeclare the candidate design, calibration prefix, seed keys, both cost ledgers,
estimator settings, lineage IDs, diagnostic version, and output hashes before the full
run.

### Primary evaluation metrics

- Negative log probability of the true hypothesis:
  `-log(max(p(true), 1e-300))`.
- Multiclass Brier score against the true hypothesis.
- Confidently-wrong rate under the frozen `0.80` definition.
- Top-label calibration error under the frozen ten-bin definition.

### Secondary metrics

- final true-hypothesis probability;
- final posterior entropy;
- 0.80 and 0.95 threshold-reaching rates and costs;
- matched replications and matched evidence completed;
- calibration cost, decision cost, and combined total cost;
- decision-phase and end-to-end scientific efficiency;
- predictive log likelihood and empirical coverage diagnostics.

Entropy and ECE are descriptive in this milestone. Higher entropy is not automatically
safer, and lower entropy is not automatically better. Acceptance is based only on the
mathematically explicit gates in Section 8, not on entropy direction or an undeclared
diagnostic threshold.

For every metric, report per-world, per-budget, and per-policy means, medians, standard
deviations, and deterministic 95 percent paired percentile-bootstrap intervals with
10,000 resamples and a fixed bootstrap seed. Report paired differences as
`calibrated - fixed`. Do not pool worlds for the primary conclusion.
The fixed-stream lineage replay described above is the primary protocol, not an ablation.
It prevents policy-induced data acquisition from confounding this belief-model adequacy
comparison.

The evaluator alone receives hidden truth. The policy-isolation audit must reject truth,
world noise parameters, truth labels, and evaluator metrics in model and policy
interfaces. Full deterministic replays and observation-schedule fingerprints are hard
requirements.

## 8. Acceptance Gates

The calibrated model is accepted only if every gate in this section passes. Define:

```text
M_fixed = fixed_sigma_gaussian
M_cal   = replicated_noise_calibrated_gaussian
P       = {random, greedy, information_gain, lookahead_information_gain}
B       = {short = 2.25, large = 4.50}
S       = the frozen 100-seed schedule

mean_x(M, W)
  = (1 / (|P| * |B| * |S|))
    * sum over policy p, budget b, seed s of x(M, W, p, b, s)

Delta_x(W) = mean_x(M_cal, W) - mean_x(M_fixed, W)
```

Every policy-budget cell has the same 100 seeds, so this is both a run-level mean and an
equal-weight macro-average of the eight policy-budget cell means. No world is pooled into
another world's acceptance result.

The metrics are:

```text
CW = 1 if max_h posterior(h) >= 0.80 and the stable top hypothesis is not truth,
     otherwise 0

NLL = -ln(max(posterior(true_hypothesis), 1e-300))

Brier = sum_h (posterior(h) - 1[h = true_hypothesis])^2

TrueProbability = posterior(true_hypothesis)
```

The performance gates are exactly:

1. **Adverse-noise confidently-wrong rate:**
   `Delta_CW(adverse_noisy_observations) <= -0.10`. The calibrated rate must be at
   least 10 percentage points lower than the fixed-sigma rate.
2. **Adverse-noise mean NLL:**
   `Delta_NLL(adverse_noisy_observations) < 0`.
3. **Adverse-noise mean Brier score:**
   `Delta_Brier(adverse_noisy_observations) < 0`.
4. **Delayed-information true-hypothesis probability:**
   `Delta_TrueProbability(delayed_information) >= -0.02`. The calibrated model may
   regress by no more than `0.02` on average.
5. **Delayed-information confidently-wrong rate:**
   `Delta_CW(delayed_information) <= 0`. It may not increase.

For every metric difference used above, report a deterministic paired 95 percent
percentile-bootstrap confidence interval with 10,000 resamples. Report both the aggregate
interval used by the gate table and every policy-budget cell interval. Aggregate
resampling uses the seed as a paired block containing all eight policy-budget outcomes;
cell intervals resample paired seeds within that cell. The intervals are mandatory
uncertainty reports. The declared point-estimate inequalities above are the acceptance
rules; an interval is not silently converted into an additional gate.

Every acceptance table also reports decision cost, calibration cost, combined total cost,
decision-phase scientific efficiency, and calibrated end-to-end scientific efficiency.
These cost fields are mandatory disclosures rather than an undeclared sixth performance
gate. Passing the five performance gates establishes scientific-correctness adequacy for
this benchmark. It does not establish that the calibrated model is attractive in total
cost.

The hard audit gates are:

1. Exactly five valid calibration matched effects exist in every public comparison group
   before the first calibrated decision-phase update.
2. Both belief lineages remain at the declared prior with zero scientific updates after
   calibration and before the first decision-phase evidence.
3. Deterministic calibration and decision replays match after excluding declared
   wall-clock metadata.
4. Hidden truth, hidden effect, benchmark noise parameters and labels, future
   observations, and evaluator correctness labels are absent from calibration records
   exposed to reasoning, sigma estimation, updater, planner, and policy interfaces.
5. Every sigma estimate and belief update is reconstructable from exact persisted source
   records and provenance, while calibration matched effects have no scientific-evidence
   or belief-update links.
6. The current evidence is excluded from its own sigma estimate in real execution,
   benchmark evaluation, and hypothetical simulation.
7. Calibration and decision ledgers are disjoint, reconcile to combined total cost, and
   preserve the frozen decision budgets.
8. Both lineages consume the same decision evidence stream, carry explicit model and
   lineage IDs, and pass cross-lineage read-contamination tests.
9. Calibration replication identity, independent arm-noise, matched-pair consumption,
   and one-update-per-model-and-evidence uniqueness checks pass.
10. `fixed_sigma_gaussian` reproduces its frozen behavior and existing artifacts remain
    unchanged.

If any performance gate, confidence-interval reporting requirement, determinism audit,
leakage audit, or provenance audit fails, `fixed_sigma_gaussian` remains the default. The
model is not accepted merely because entropy rises or falls, and no gate may be weakened
after calibrated-model results are observed. Even if every scientific gate passes, the
report must state separately whether calibration cost makes deployment unattractive; it
must not turn a decision-phase efficiency result into an end-to-end cost claim.

## 9. Risks and Failure Modes

### Too few replications

The benchmark prefix guarantees five prior effects before the first decision update, so a
fallback in a paired run is an invariant failure. Outside the benchmark, the model still
uses the fixed-sigma fallback when fewer than five prior effects exist. Report source
count, fallback status, and activation time in every context.

### Biased sigma estimates

Five calibration effects may not represent decision-phase noise, and later
policy-selected replications may also be unrepresentative. Detect this with fixed-prefix
replay, seed-stratified estimates, leave-one-out influence diagnostics, and comparison of
prefix and decision-phase residual distributions. Do not adapt the prefix after results.

### Heterogeneous noise across experiment groups

Group-local estimation avoids inappropriate pooling but may leave each group data-poor.
Detect heterogeneity by reporting per-group `estimated_sigma` values and prequential
residual and coverage diagnostics. Version 1 must not silently pool public comparison
groups to improve sample size.

### Sigma inflation hiding real effects

A large `estimated_sigma`, and therefore a large likelihood variance
`estimated_sigma^2`, may prevent false confidence but also suppress legitimate learning.
Detect this through NLL, Brier, true-hypothesis probability, threshold-reaching rates,
and power in low-noise Adam- and SGD-advantage worlds. No upper sigma cap is introduced
merely to restore confidence.

### Repeated use of the same evidence

An effect can accidentally be paired twice, update a lineage twice, or appear twice in a
sigma estimate. Enforce database uniqueness constraints and test exact source sets.
Calibration use and belief-update use are separate roles and must both be recorded.

### Planner changes which data becomes available

The primary evaluation prevents this confound by using the fixed-sigma lineage to control
one shared decision stream. It therefore cannot establish how calibrated beliefs would
change closed-loop policy behavior. Any later closed-loop evaluation is a separate
milestone and must not be mixed into the frozen adequacy results.

### False confidence under remaining misspecification

A Gaussian with an estimated observation standard deviation still cannot represent skew,
heavy tails, multimodal effects, correlated replications, or a missing hypothesis. Detect
this through predictive tails, empirical coverage, residual patterns, NLL, Brier, and
confidently-wrong examples. An `adequate` status is provisional evidence, not proof.

### Empirical-Bayes dependence

The five prefix effects estimate sigma without updating beliefs, which isolates initial
calibration from hypothesis learning. Eligible prior decision evidence may later update a
belief and become a source for a future sigma estimate, so some sequential
empirical-Bayes dependence remains. The strict-before rule prevents direct self-use but
not all dependence; preserve the full source chronology for audit.

### Hidden calibration cost

Separating the ledgers can tempt reports to show only the frozen decision budget. Detect
this with reconciliation tests requiring
`combined_total_cost = calibration_cost + decision_cost` and by emitting both
decision-phase and end-to-end efficiency in every result. A missing calibration-cost
field invalidates the report.

### Cross-lineage contamination

Shared experiment and evidence records can accidentally lead one model to read the other
model's posterior, update, or diagnostic. Detect this with model-scoped keys, foreign-key
constraints, sentinel values that fail on cross-lineage access, and replay tests in which
the order of lineage evaluation is reversed without changing either result.

## 10. Explicit Non-Goals

This milestone does not include:

- Student-t or other heavy-tailed likelihoods;
- unknown-hypothesis or autonomous hypothesis generation;
- abstention, evidence rejection, or stop-for-uncertainty policies;
- planning horizons longer than two;
- new decision policies or planners;
- changes to random, greedy, one-step information gain, or two-step lookahead algorithms;
- LLM integration or LLM-based model diagnosis;
- real PPO or other real training-system integration;
- a web UI;
- automatic likelihood-model selection;
- hierarchical sigma estimation, arm-specific variance models, or online change-point
  detection;
- retroactive reprocessing of existing user experiment history;
- production distributed execution or cloud orchestration.

These may become future research questions. Adding any of them now would make it unclear
whether calibration changed because replicated sigma estimation worked.

## 11. Implementation Plan

The smallest testable implementation is divided into six milestones.

### Milestone 1: Versioned belief-model interface

- Add a narrow likelihood-model abstraction that returns hypothesis means, an effective
  observation standard deviation `sigma`, model version, and provenance snapshot for a
  public comparison group.
- Implement `fixed_sigma_gaussian` as an adapter around the current exact behavior.
- Keep it as the default and prove byte-equivalent likelihoods, posteriors, EIG values,
  and planner decisions on existing fixtures.
- Add `replicated_noise_calibrated_gaussian` alongside it; do not add another alternative.
- Require `belief_model_id` and `lineage_id` on every model-scoped state, update,
  likelihood calculation, and diagnostic interface.

Likely files added: `belief_models.py`, `noise_calibration.py`.  
Likely files modified: `reasoning.py`, `optimizer_effect.py`, and narrowly parameterized
likelihood entry points in `decision.py` and `lookahead.py`. The information-gain formulas,
lookahead recursion, budgets, action ranking, and tie breaking remain stable.

### Milestone 2: Calibration prefix, replication identity, and eligibility

- Add deterministic calibration-group and five-replication prefix builders using disjoint
  calibration seed keys, shared pair-level factors, and independent arm-noise keys.
- Extend public experiment design with stable phase, replication, and pair-level seed
  identities.
- Add a replication-aware matched-evidence contract beside the current one.
- Generate each calibration matched effect exactly once, expose it only to the sigma
  estimator, and prove that beliefs remain at the prior.
- Keep calibration candidates in a namespace disjoint from decision candidates.
- Preserve all current non-replicated eligibility behavior and tests.

Likely files modified: `evidence_eligibility.py`, application evidence derivation in
`optimizer_effect.py`, and experiment/design dataclasses. Candidate IDs remain unique so
existing experiment history is not destroyed.

### Milestone 3: Provenance and additive storage

Advance the SQLite schema additively from version 4. Expected additions are:

- `calibration_groups`: world/evaluation-seed/public-group identity and prefix version;
- `calibration_replications`: five distinct replication IDs, pair-level seeds, arm source
  IDs, completion state, and full keyed-randomness provenance;
- `calibration_matched_effects`: one immutable Adam-minus-SGD effect per calibration pair,
  with no foreign key to scientific evidence;
- `sigma_estimates`: estimator/model version, lineage ID, public comparison-group key,
  cutoff sequence, sample count, sample mean, raw sample standard deviation,
  `sigma_floor`, final `estimated_sigma`, status, and creation metadata;
- `sigma_estimate_sources`: ordered links to calibration matched effects and eligible
  prior decision-phase evidence;
- `calibration_cost_entries` and `decision_cost_entries`: disjoint immutable ledger rows
  whose sums reconcile to combined total cost;
- `belief_model_lineages`: explicit model and lineage identities plus current-state
  pointers;
- model and lineage IDs on belief states, belief updates, likelihood calculations, and
  model-adequacy diagnostics;
- `model_adequacy_diagnostics`: prequential predictive scores, residuals, coverage flags,
  status, and diagnostic version.

Do not rewrite or delete existing tables. Existing rows are labeled logically as
`fixed_sigma_gaussian` without recalculating them. The first implementation supports both
required lineages in parallel. Shared experiment and decision-evidence rows are allowed;
all epistemic state is model- and lineage-scoped. Calibration matched effects must be
unrepresentable as scientific evidence.

### Milestone 4: Diagnostics

- Add deterministic predictive CDF, interval, residual, coverage, and log-score
  calculations.
- Persist one diagnostic event per real pre-update evidence score.
- Produce the tri-valued adequacy status from truth-free diagnostics only.
- Add evaluator-only NLL, Brier, ECE, and confidently-wrong reporting with strict interface
  isolation.

### Milestone 5: Replicated paired benchmark

- Version the deterministic five-effect calibration prefix for the four existing research
  worlds without changing decision candidate sets or budgets.
- Generate one fixed-sigma-controlled decision stream per world, seed, budget, and policy,
  then replay the same real decision evidence into both isolated lineages.
- Run the complete `2 belief models x 4 policies x 4 worlds x 2 budgets x 100 seeds`
  matrix with fixed 10,000-resample paired bootstrap intervals.
- Write to a new versioned output directory and retain the frozen evaluation unchanged.
- Include action traces, sigma-calibration activation traces, baseline-fallback rates,
  diagnostics, failure cases, both cost ledgers, lineage-isolation audits, and
  fairness/leakage audits.
- Report belief accuracy and calibration separately from decision cost, calibration cost,
  combined total cost, and both efficiency views.

### Milestone 6: Acceptance review

- Evaluate the preregistered gates without tuning after results are visible.
- Keep `fixed_sigma_gaussian` as default regardless of implementation completion.
- Recommend a later default switch only if every hard gate and performance gate passes.
- Record a negative or mixed result as a valid research result and identify which gate
  failed.

Required tests before acceptance include:

- exact baseline likelihood and posterior regression tests;
- sample-standard-deviation, Bessel-correction, sigma-floor, minimum-count, and
  large-sigma tests;
- exactly-five-prefix, prior-preservation, namespace-isolation, and calibration-not-
  evidence tests;
- shared-factor and independent-arm-noise deterministic seed tests;
- chronological current-evidence exclusion and future-observation leakage tests;
- valid/invalid replication grouping and duplicate-prevention tests;
- deterministic estimate and update replay tests;
- normalized finite posterior and log-space underflow tests;
- complete sigma-estimate and belief provenance reconstruction tests;
- disjoint calibration/decision ledger and total-cost reconciliation tests;
- parallel-lineage isolation, reversed-evaluation-order, and shared-evidence tests;
- truth-free estimator, updater, diagnostic, and policy-interface audits;
- planner recursion and four-policy regression tests;
- empirical-coverage, residual, predictive-log-likelihood, ECE, Brier, NLL, and
  confidently-wrong metric tests;
- paired observation schedule and JSON/CSV/report output tests;
- one end-to-end calibration prefix to sigma estimate to shared decision evidence to two
  isolated posteriors to cost-and-provenance explanation workflow.

## 12. Frozen Constants, Protocol Rules, and Remaining Questions

### Consolidated freeze table

Every scientific, statistical, seeding, pairing, cost, lineage, persistence, and
acceptance rule for this milestone is consolidated below. Values and semantics must not be
tuned after calibrated-model outcomes are inspected.

| Concern | Frozen value or rule | Precise meaning |
| --- | --- | --- |
| Belief models | `fixed_sigma_gaussian`, `replicated_noise_calibrated_gaussian` | The complete model set; exactly two models. |
| Calibrated model version | `replicated_noise_calibrated_gaussian/v1` | First and only calibrated likelihood model in this milestone. |
| Belief lineages | one isolated lineage per belief model | Exactly two parallel scientific lineages. |
| Lineage identity | explicit `belief_model_id` and `lineage_id` | Required on every belief state, update, likelihood calculation, diagnostic, and current-state pointer. |
| Initial prior | `1/3` per hypothesis | Both lineages start from separate, numerically identical uniform priors. |
| Hypothesis means | Adam `+0.10`, none `0.00`, SGD `-0.10` | Means of the matched-effect likelihood in matched-effect units `U`. |
| Baseline observation standard deviation | `sigma_fixed = 0.05` | Frozen matched-effect Gaussian `sigma` used by `fixed_sigma_gaussian`. |
| Standard-deviation floor | `sigma_floor = 0.05` | Lower bound applied to the raw matched-effect sample standard deviation. |
| Variance floor | `variance_floor = 0.0025` | `sigma_floor^2` in `U^2`; it is not the estimated model parameter. |
| Sigma units | matched-effect unit `U` | `estimated_sigma` is the standard deviation of Adam-minus-SGD effects, not an individual arm. |
| Sample-standard-deviation correction | `ddof = 1` | Ordinary sample standard deviation with Bessel correction. |
| Calibrated sigma formula | `max(sample_standard_deviation, 0.05)` | Final `estimated_sigma`; there is no upper sigma cap. |
| Minimum prior effects | exactly `5` | Five valid matched effects in the same public comparison group must exist strictly before a calibrated decision-evidence update. |
| Benchmark activation | active on the first decision-phase evidence | The five-effect calibration prefix exists before decision time; benchmark fallback is an invariant failure. |
| General cold-start sigma | `0.05` | Outside the benchmark, use and record baseline fallback until five prior valid effects exist. |
| Sigma-estimation scope | same public comparison group and controlled-variable fingerprint | No cross-group pooling in version 1. |
| Sequential source set at time `t` | five prefix effects plus eligible decision effects from times `< t` | Evidence at `t` and all later evidence are excluded. |
| Current-evidence exclusion | mandatory in real, benchmark, and simulated updates | Current evidence never estimates the sigma used for its own likelihood. |
| Planner simulation | immutable predecision sigma snapshot | Hypothetical current and future branch outcomes never enter that snapshot. |
| Calibration prefix scope | one prefix per `(world_id, evaluation_seed, comparison_group_key)` | Policy, budget, and belief model are excluded from the prefix key. |
| Calibration effect count | exactly `5` per prefix | Every public comparison group receives five valid prior matched effects. |
| Prefix sharing | byte-identical observations across both budgets, all policies, and both models | No policy or model receives a different calibration sample for the same prefix key. |
| Calibration namespace | dedicated `calibration` namespace | Calibration IDs cannot collide with decision-phase identities. |
| Decision namespace | dedicated `decision` namespace | Decision candidates and seeds remain separate from calibration. |
| Calibration candidates | never remove or block decision candidates | Prefix completion does not mark a decision candidate completed. |
| Calibration seed separation | calibration and decision key spaces are disjoint | No calibration seed is reused as a decision-phase seed. |
| Calibration replication IDs | exactly five distinct IDs per prefix | One distinct ID for each calibration matched effect. |
| Pair-level seed | one distinct declared calibration seed per replication | Both arms in that replication share it for shared stochastic factors. |
| Shared pair structure | same replication ID, group, controls, complementary arms, and pair-level seed | Required for every Adam/SGD calibration pair. |
| Shared stochastic factors | same deterministic `shared_key` for both arms | Paired design may cancel shared nuisance variation. |
| Arm observation noise | independent deterministic Adam and SGD draws | Keys include the arm; identical arm-noise draws are forbidden. |
| Randomness derivation | explicit stable keyed seeds only | No implicit RNG, hidden seed, or process-order dependence. |
| Random primitive | existing versioned SHA-256 keying and standard-normal transform | Full key material is persisted for exact replay. |
| Calibration completion | two successful arms with complete provenance | Failed, partial, ambiguous, or untraceable pairs are invalid. |
| Calibration reuse | no arm or pair is derived twice | An immutable derived effect may be referenced by later sigma estimates without re-pairing. |
| Calibration role | noise estimation only | Calibration effects never support or contradict a hypothesis. |
| Calibration evidence boundary | calibration matched effects are not scientific `Evidence` | They have no belief-state evidence edge and produce no belief update. |
| Prior preservation | zero scientific updates before decision phase | Both lineages remain exactly at the declared prior after calibration. |
| Calibration truth isolation | no truth ID, true effect, benchmark label, or correctness field exposed | Centered observed effects estimate sigma; policies and belief updaters cannot read their mean as hypothesis signal. |
| Decision evidence | one shared immutable chronological stream per policy condition | Both lineages consume exactly the same experiments and evidence. |
| Decision-stream controller | the existing policy using the `fixed_sigma_gaussian` lineage | The calibrated lineage is shadow-only and cannot change decisions in this adequacy evaluation. |
| Policy set | `random`, `greedy`, `information_gain`, `lookahead_information_gain` | Existing algorithms and versions remain unchanged. |
| Cross-lineage reads | forbidden | A lineage cannot read the other's posterior, likelihoods, updates, diagnostics, or current-state pointer. |
| Shared records | experiments, decision evidence, calibration records, and costs only | Shared immutable observations are allowed; epistemic state is never shared. |
| Calibration ledger | `calibration_cost` | Contains only calibration-prefix arm costs. |
| Decision ledger | `decision_cost` | Contains only real decision-phase experiment costs. |
| Ledger disjointness | one cost entry belongs to exactly one ledger | Double assignment or cross-ledger spending is invalid. |
| Calibration pricing | same deterministic public cost function as corresponding decision design | Calibration cost is real and fully reproducible. |
| Decision budgets | short `2.25`, large `4.50` | Exact frozen budgets; calibration cost does not consume them. |
| Combined cost | `combined_total_cost = calibration_cost + decision_cost` | Required reconciliation identity. |
| Prefix cost storage | one ledger entry set per prefix key | Policy, budget, and lineage runs reference shared entries rather than duplicating physical cost. |
| Run-level calibration attribution | full referenced prefix cost | Represents standalone calibrated deployment cost. |
| Suite-level calibration cost | deduplicated by prefix ID | Prevents shared calibration work from being counted repeatedly as physical execution. |
| Fixed required cost | `decision_cost` | Fixed sigma does not require calibration for deployment. |
| Calibrated required cost | `combined_total_cost` | End-to-end calibrated cost includes its prefix. |
| Decision-phase efficiency | scientific progress divided by `decision_cost` | Isolates learning on the shared decision stream. |
| Calibrated end-to-end efficiency | scientific progress divided by `combined_total_cost` | Required before any end-to-end cost claim. |
| Cost interpretation | scientific gates and cost attractiveness reported separately | Scientific correctness can pass while total cost remains unattractive. |
| Persisted calibration records | calibration groups, replications, matched effects, and source arms | Separate from scientific evidence tables. |
| Persisted model records | sigma estimates, sigma sources, lineages, model-scoped beliefs, updates, likelihoods, and diagnostics | Complete lineage and estimation provenance. |
| Persisted cost records | separate calibration and decision ledger entries | Both ledgers and their reconciled total are mandatory. |
| Adequacy states | `adequate`, `uncertain`, `appears_misspecified` | Complete serialized truth-free state set. |
| Adequacy residual source | decision-phase evidence only | Prefix effects estimate sigma but do not count as predictive residuals. |
| Adequacy history requirement | `10` residuals | Minimum count for `adequate` when no alarm or disagreement exists. |
| Predictive tail alarm | tail probability `< 0.05` | Strict inequality; equality does not alarm. |
| Residual outlier | `abs(z) > 3.0` | Strict inequality; equality does not count. |
| Repeated residual alarm | at least `2` outliers in the last up to `5` eligible observations | Rolling truth-free alarm rule. |
| Predictive interval levels | `50%`, `80%`, `95%` | Truth-free empirical-coverage diagnostics. |
| Evaluation seed schedule | seeds `0` through `99` | The same 100 paired decision seeds used by the completed evaluation. |
| Research worlds | delayed information, no optimizer advantage, adverse noisy observations, asymmetric experiment costs | Existing four scientific conditions. |
| Evaluator-only world effects | delayed `+0.12`, no advantage `0.00`, adverse `+0.12`, asymmetric `-0.12` | Hidden effects used only after decisions and updates complete. |
| Evaluator-only arm observation sigmas | delayed `0.005`, no advantage `0.03`, adverse `0.20`, asymmetric `0.03` | Hidden per-arm world parameters; never estimator or policy input. |
| Truth access timing | after all decisions and both lineage updates complete | Evaluator-only scoring boundary. |
| Confidence level | `95%` | Required paired interval level. |
| Bootstrap resamples | `10,000` | Deterministic paired percentile bootstrap. |
| Bootstrap seed | `20,260,710` | Existing frozen paired-evaluation bootstrap seed. |
| Confidently-wrong threshold | `0.80` | Maximum posterior at or above this value in a non-true top hypothesis. |
| NLL probability floor | `1e-300` | Numerical floor inside the natural logarithm. |
| Calibration bins | `10` | Equal-width top-label ECE bins, reported as a diagnostic. |
| Required cost reporting | decision, calibration, combined total, fixed required, calibrated required | No cost ledger may be omitted from acceptance output. |
| Required efficiency reporting | decision-phase and calibrated end-to-end | No end-to-end claim may rely only on decision cost. |
| Adverse-noise CW gate | `Delta_CW <= -0.10` | At least a 10-percentage-point calibrated-model reduction. |
| Adverse-noise NLL gate | `Delta_NLL < 0` | Calibrated mean NLL must be lower. |
| Adverse-noise Brier gate | `Delta_Brier < 0` | Calibrated mean Brier score must be lower. |
| Delayed-information probability gate | `Delta_TrueProbability >= -0.02` | Average true-hypothesis probability regression may not exceed `0.02`. |
| Delayed-information CW gate | `Delta_CW <= 0` | Confidently-wrong rate may not increase. |
| Confidence-interval reporting | aggregate and every policy-budget cell | Every gate metric includes a paired 95 percent interval. |
| Default rule | any failed gate or audit keeps `fixed_sigma_gaussian` default | Passing science gates still requires separate total-cost interpretation. |
| Scope exclusions | no Student-t, automatic selection, unknown hypotheses, abstention, new planners, or LLM components | Exactly the declared two-model adequacy milestone. |

### Final design audit assertions

The implementation and paired evaluation must make all six assertions mechanically
testable from persisted records:

1. Every public comparison group has exactly five valid prefix effects before its first
   calibrated decision update.
2. Both scientific lineages remain at the declared prior with zero updates after the
   prefix and before decision evidence.
3. Calibration-facing reasoning records contain no hidden truth or benchmark labels, and
   calibration effects have no scientific-evidence links.
4. Calibration and decision ledgers are disjoint and reconcile exactly to combined total
   cost without reducing either frozen decision budget.
5. Both lineages consume the same decision evidence but cannot read or mutate one
   another's epistemic records.
6. Every stored and reported sigma is in matched-effect units `U`; every variance is in
   squared units `U^2`.

### Remaining unresolved questions

None. No unresolved scientific, statistical, seeding, replication, cost-accounting,
lineage, persistence, or benchmark-pairing question blocks implementation or the paired
evaluation. Implementation-local class names, SQL index names, and report formatting may
follow repository conventions only when they preserve every rule in the table above.
