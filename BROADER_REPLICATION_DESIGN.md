# Broader Closed-Loop Replication Protocol

Status: pre-implementation, outcome-blind protocol freeze candidate  
Protocol version: `broader-closed-loop-replication/v1`

This document defines a prospective replication of closed-loop belief-guided experiment
selection. It is a design artifact only. It does not change a policy, belief model,
likelihood, evidence rule, world outcome, planning horizon, or prior scientific result.

The protocol keeps the frozen scientific matrix:

```text
4 arms * 128 seeds * 24 worlds * 3 budgets = 36,864 trajectories
```

It replaces the previous generated analysis grid with three small, explicit contrast
registries. No smoke or full-run result may alter a registry, threshold, world, seed,
budget, gate, or decision branch.

## 1. Scope and Frozen Scientific Matrix

### 1.1 Comparison arms

The four arms are unchanged:

| arm_id | belief_model_id | policy_id |
| --- | --- | --- |
| `fixed_ig` | `fixed_sigma_gaussian` | `information_gain` |
| `calibrated_ig` | `replicated_noise_calibrated_gaussian` | `information_gain` |
| `fixed_lookahead` | `fixed_sigma_gaussian` | `lookahead_information_gain` |
| `calibrated_lookahead` | `replicated_noise_calibrated_gaussian` | `lookahead_information_gain` |

Random and greedy are not replication arms. The existing information-gain and horizon-two
lookahead algorithms remain byte-for-byte unchanged. Fixed and calibrated arms are paired
within policy, world, budget, and seed.

Each trajectory has an isolated belief lineage, experiment history, evidence stream,
decision trace, planner trace, calibration ledger, decision ledger, and store. An arm may
read only its own persisted public state and, for calibrated arms, its own immutable
calibration-prefix references.

### 1.2 Seeds, worlds, budgets, and counts

- Full seeds are the 128 integers `1000..1127`, inclusive, in ascending order.
- Smoke seeds are `9000,9001,9002,9003`; they never enter scientific artifacts.
- Worlds are the 24 literal rows in Section 8.4.
- Decision budgets are `2.25`, `4.50`, and `6.75`.
- Fixed/calibrated trajectory comparisons are
  `2 policies * 128 seeds * 24 worlds * 3 budgets = 18,432`.
- Calibration effects are
  `128 seeds * 24 worlds * 3 groups * 5 replications = 46,080`.
- Calibration observations are `46,080 * 2 arms = 92,160`.
- Smoke trajectories are `4 seeds * 8 worlds * 3 budgets * 4 arms = 384`.

The no-whitespace UTF-8 JSON array `[1000,1001,...,1127]`, without a trailing LF, has
SHA-256 `28ee6854626047a99bd2e1538d200aabccd89a0d77870db011d7aa0d0b4f6093`.
The full seeds are disjoint from every prior scientific seed in `0..99` and from the smoke
seeds.

### 1.3 Immutable boundaries

This protocol does not permit:

- a new policy, belief model, likelihood family, planner horizon, or evidence rule;
- hidden-truth, hidden-parameter, future-outcome, or unselected-outcome access by a policy;
- post-result changes to worlds, metrics, populations, contrasts, gates, or thresholds;
- a web UI, LLM integration, PPO integration, cloud service, or automatic model selection;
- implementation-time contrast or analysis-cell generation; or
- promotion of calibrated control without a separate prospective controller evaluation.

### 1.4 Deterministic trajectory termination

After every completed real action, derive these ordered sets from the recorded public state:

```text
U = unexecuted candidates that are publicly feasible without considering cost
A = candidates in U whose recorded cost is <= remaining decision budget
```

Both sets follow frozen candidate-catalog order. Remaining decision budget is the original
binary64 budget minus real action costs in chronological order; affordability uses the exact
binary64 `<=` comparison and no hidden state. If `A` is nonempty, the next policy decision is
required. If `A` is empty, terminal reason is assigned by this exhaustive precedence:

```text
candidate_space_exhausted  iff U is empty
budget_exhausted           iff U is nonempty and A is empty
integrity_abort            iff an integrity failure occurs at any time
```

`integrity_abort` takes precedence, makes the trajectory invalid, excludes it from every
scientific population, fails the study directory, and permits only the noncanonical failure
artifact. Termination uses only recorded public state, completed actions, costs, and
remaining budget. There is no generic or confidence-based stopping condition.
For a valid canonical run, `budget_exhausted` in `MetricSet` is true exactly when
`terminal_reason=budget_exhausted` and false for `candidate_space_exhausted`.

## 2. Research Questions and Exact Interpretation

Every question below has one fixed interpretation. The union of the three contrast
registries in Appendix A is the authoritative question-to-estimand mapping.

### 2.1 RQ1A: pooled belief quality

`RQ1A_POOLED_BELIEF_QUALITY` asks whether calibrated-minus-fixed NLL, Brier, ECE, and
confidently-wrong rate improve in the primary truth-balanced population for both policies,
while true-hypothesis probability does not regress beyond the existing `0.02` margin.

This is confirmatory. `G-CAL-IG`, `G-CAL-LA`, and `G-CAL-BOTH` provide its only allowed
interpretation. High-noise and heterogeneous-noise claims are not implied by this pooled
gate.

### 2.2 RQ1B: pooled closed-loop control

`RQ1B_POOLED_CONTROL` asks whether calibrated control satisfies the existing pooled
closed-loop benefit conditions separately for both policies: proper-score improvement,
true-probability improvement, no confidently-wrong increase, more helped than hurt
divergences, improved conditional and end-to-end Brier efficiency, and no hard safety
regression.

This is confirmatory. `G-CTRL-IG`, `G-CTRL-LA`, `G-CTRL-BOTH`, and `G-HARD-SAFETY` are its
only interpretation.

### 2.3 RQ1C: noisy-stratum replication

`RQ1C_NOISE_STRATA` reports calibrated-minus-fixed NLL, Brier, ECE, confidently-wrong rate,
and true-hypothesis probability in exactly two predeclared strata:

- homogeneous high noise: `h_adam_high,h_null_high,h_sgd_high`; and
- heterogeneous noise: all six `g_*_lmh` and `g_*_hml` worlds.

These are descriptive replication analyses. They report counts, denominators, point
estimates, and estimability only. They do not receive confidence intervals, p-values, or an
A/B/C/D role.

### 2.4 RQ2A: divergence-frequency concentration

`RQ2A_DIVERGENCE_FREQUENCY` has two descriptive estimands per policy:

```text
first_action_divergence_rate = weighted first-action-divergent pairs / weighted all pairs
any_divergence_rate          = weighted ever-divergent pairs / weighted all pairs
```

For cost concentration, the reported difference is asymmetric-cost worlds minus matched
symmetric `d2_adam,d2_sgd` worlds. For budget concentration, it is the equally weighted
`4.50,6.75` rate minus the `2.25` rate. These point estimates do not affect A/B/C/D.

### 2.5 RQ2B: harm conditional on divergence

`RQ2B_CONDITIONAL_HARM` asks, separately by policy, whether harmful outcomes among
divergent pairs are concentrated by asymmetric cost and by larger budgets. The estimator is

```text
harm_rate(S) = sum(i in S, divergent) w_i * I[outcome_i = hurt]
               / sum(i in S, divergent) w_i

conditional_harm_difference = harm_rate(target) - harm_rate(comparator)
```

The asymmetric target/comparator and larger-budget target/comparator are exactly those in
Section 5.2. `G-RQ2-COST-IG`, `G-RQ2-BUDGET-IG`, `G-RQ2-COST-LA`, and
`G-RQ2-BUDGET-LA` are confirmatory, but do not affect A/B/C/D.

### 2.6 RQ3: numerical-mechanism dominance

`RQ3_NUMERICAL_DOMINANCE` asks separately by policy whether the combined truth-free
primary-label share of `SCORE_FLATTENING` and `GROUP_SIGMA_REORDERING` is at least `0.70`,
its 95% lower bound is at least `0.60`, each individual share is at least `0.10`, and at
least 30 classifiable divergent pairs exist. `G-RQ3-IG` and `G-RQ3-LA` are confirmatory
threshold gates without a null-hypothesis p-value. They do not affect A/B/C/D.

### 2.7 RQ4: order-harm association

`RQ4_ORDER_HARM` asks separately by policy whether same-set/different-order divergent pairs
have harmful risk at least `0.10` above all other divergent pairs, with at least 30 cases on
each side, a 95% lower bound above zero, and Holm-adjusted `p < 0.05`. `G-RQ4-IG` and
`G-RQ4-LA` are confirmatory. The result is associational and does not affect A/B/C/D.

### 2.8 RQ5: actionable separator

`RQ5_ACTIONABLE_SEPARATOR` asks whether exactly one frozen, truth-free primary mechanism
is an actionable helped-versus-hurt separator after policy-specific testing and the frozen
opposite-direction veto. It is evaluated only through the 20 actionability rows, 20 veto
rows, and decision procedure in Sections 6 and 7.

### 2.9 Literal question mapping

The following JSON array is literal protocol data and is stored byte-for-byte, in this
order, as `research_question_registry`. Empty arrays mean no member. No range, wildcard,
prefix match, or implementation-time expansion is permitted.

```json
[
  {
    "research_question_id":"RQ1A_POOLED_BELIEF_QUALITY",
    "estimand_ids":["calibrated_minus_fixed"],
    "contrast_ids":["BR-C001","BR-C002","BR-C003","BR-C004","BR-C005","BR-C006","BR-C007","BR-C008","BR-C009","BR-C010"],
    "statistical_hypothesis_ids":["BQ.IG.NLL","BQ.IG.BRIER","BQ.IG.ECE","BQ.IG.CONFIDENTLY_WRONG","BQ.IG.TRUE_PROBABILITY","BQ.LA.NLL","BQ.LA.BRIER","BQ.LA.ECE","BQ.LA.CONFIDENTLY_WRONG","BQ.LA.TRUE_PROBABILITY"],
    "gate_ids":["G-CAL-IG","G-CAL-LA","G-CAL-BOTH"],
    "descriptive_only_ids":[],
    "decision_uses":["CONTROLLER_CHANGE_NEEDED","PPO_ELIGIBLE"]
  },
  {
    "research_question_id":"RQ1B_POOLED_CONTROL",
    "estimand_ids":["calibrated_minus_fixed","helped_minus_hurt"],
    "contrast_ids":["BR-C001","BR-C002","BR-C004","BR-C005","BR-C006","BR-C007","BR-C009","BR-C010","BR-C011","BR-C012","BR-C013","BR-C014","BR-C015","BR-C016","BR-C047","BR-C048","BR-C049","BR-C050","BR-C051","BR-C052","BR-C053","BR-C054","BR-C055","BR-C056","BR-C057","BR-C058","BR-C059","BR-C060","BR-C061","BR-C062","BR-C063","BR-C064","BR-C065","BR-C066"],
    "statistical_hypothesis_ids":["BQ.IG.NLL","BQ.IG.BRIER","BQ.IG.CONFIDENTLY_WRONG","BQ.IG.TRUE_PROBABILITY","BQ.LA.NLL","BQ.LA.BRIER","BQ.LA.CONFIDENTLY_WRONG","BQ.LA.TRUE_PROBABILITY","CB.IG.HELPED_MINUS_HURT","CB.IG.CONDITIONAL_BRIER_EFFICIENCY","CB.IG.END_TO_END_BRIER_EFFICIENCY","CB.LA.HELPED_MINUS_HURT","CB.LA.CONDITIONAL_BRIER_EFFICIENCY","CB.LA.END_TO_END_BRIER_EFFICIENCY","BS.IG.HOMOGENEOUS.CW","BS.IG.HOMOGENEOUS.BRIER","BS.IG.WEAK_EFFECT.CW","BS.IG.WEAK_EFFECT.BRIER","BS.IG.HETEROGENEOUS.CW","BS.IG.HETEROGENEOUS.BRIER","BS.IG.ASYMMETRIC_COST.CW","BS.IG.ASYMMETRIC_COST.BRIER","BS.IG.DELAY.CW","BS.IG.DELAY.BRIER","BS.LA.HOMOGENEOUS.CW","BS.LA.HOMOGENEOUS.BRIER","BS.LA.WEAK_EFFECT.CW","BS.LA.WEAK_EFFECT.BRIER","BS.LA.HETEROGENEOUS.CW","BS.LA.HETEROGENEOUS.BRIER","BS.LA.ASYMMETRIC_COST.CW","BS.LA.ASYMMETRIC_COST.BRIER","BS.LA.DELAY.CW","BS.LA.DELAY.BRIER"],
    "gate_ids":["G-CTRL-IG","G-CTRL-LA","G-CTRL-BOTH","G-HARD-SAFETY"],
    "descriptive_only_ids":[],
    "decision_uses":["CONTROLLER_CHANGE_NEEDED","PPO_ELIGIBLE"]
  },
  {
    "research_question_id":"RQ1C_NOISE_STRATA",
    "estimand_ids":["calibrated_minus_fixed"],
    "contrast_ids":["BR-D001","BR-D002","BR-D003","BR-D004","BR-D005","BR-D006","BR-D007","BR-D008","BR-D009","BR-D010","BR-D011","BR-D012","BR-D013","BR-D014","BR-D015","BR-D016","BR-D017","BR-D018","BR-D019","BR-D020"],
    "statistical_hypothesis_ids":[],"gate_ids":[],
    "descriptive_only_ids":["BR-D001","BR-D002","BR-D003","BR-D004","BR-D005","BR-D006","BR-D007","BR-D008","BR-D009","BR-D010","BR-D011","BR-D012","BR-D013","BR-D014","BR-D015","BR-D016","BR-D017","BR-D018","BR-D019","BR-D020"],
    "decision_uses":[]
  },
  {
    "research_question_id":"RQ2A_DIVERGENCE_FREQUENCY",
    "estimand_ids":["divergence_rate_difference"],
    "contrast_ids":["BR-D021","BR-D022","BR-D023","BR-D024","BR-D025","BR-D026","BR-D027","BR-D028"],
    "statistical_hypothesis_ids":[],"gate_ids":[],
    "descriptive_only_ids":["BR-D021","BR-D022","BR-D023","BR-D024","BR-D025","BR-D026","BR-D027","BR-D028"],
    "decision_uses":[]
  },
  {
    "research_question_id":"RQ2B_CONDITIONAL_HARM",
    "estimand_ids":["conditional_harm_difference"],
    "contrast_ids":["BR-C017","BR-C018","BR-C019","BR-C020"],
    "statistical_hypothesis_ids":["CC.IG.ASYMMETRIC_COST","CC.IG.LARGER_BUDGET","CC.LA.ASYMMETRIC_COST","CC.LA.LARGER_BUDGET"],
    "gate_ids":["G-RQ2-COST-IG","G-RQ2-BUDGET-IG","G-RQ2-COST-LA","G-RQ2-BUDGET-LA"],
    "descriptive_only_ids":[],"decision_uses":[]
  },
  {
    "research_question_id":"RQ3_NUMERICAL_DOMINANCE",
    "estimand_ids":["combined_primary_share"],"contrast_ids":["BR-C067","BR-C068"],
    "statistical_hypothesis_ids":[],"gate_ids":["G-RQ3-IG","G-RQ3-LA"],
    "descriptive_only_ids":[],"decision_uses":[]
  },
  {
    "research_question_id":"RQ4_ORDER_HARM",
    "estimand_ids":["sequence_harm_difference"],"contrast_ids":["BR-C021","BR-C022"],
    "statistical_hypothesis_ids":["SA.IG.SAME_SET_DIFFERENT_ORDER","SA.LA.SAME_SET_DIFFERENT_ORDER"],
    "gate_ids":["G-RQ4-IG","G-RQ4-LA"],"descriptive_only_ids":[],"decision_uses":[]
  },
  {
    "research_question_id":"RQ5_ACTIONABLE_SEPARATOR",
    "estimand_ids":["mechanism_harm_difference","actionability_composite"],
    "contrast_ids":["BR-C023","BR-C024","BR-C025","BR-C026","BR-C027","BR-C028","BR-C029","BR-C030","BR-C031","BR-C032","BR-C034","BR-C035","BR-C036","BR-C037","BR-C038","BR-C039","BR-C040","BR-C041","BR-C042","BR-C043","BR-C044","BR-C046","BR-J001","BR-J002","BR-J003","BR-J004","BR-J005","BR-J006","BR-J007","BR-J008","BR-J009","BR-J010","BR-J011","BR-J012","BR-J013","BR-J014","BR-J015","BR-J016","BR-J017","BR-J018","BR-J019","BR-J020"],
    "statistical_hypothesis_ids":["MS.IG.SCORE_FLATTENING","MS.IG.BELIEF_STATE_REORDERING","MS.IG.GROUP_SIGMA_REORDERING","MS.IG.BELIEF_SIGMA_INTERACTION","MS.IG.COST_TIEBREAK_CHANGE","MS.IG.PAIR_COMPLETION_DELAY","MS.IG.PAIR_OPENER_CHANGE","MS.IG.SAME_SET_DIFFERENT_ORDER","MS.IG.BUDGET_CROWD_OUT","MS.IG.CONSERVATIVE_NONCOMMITMENT","MS.IG.NO_STABLE_MECHANISM","MS.LA.SCORE_FLATTENING","MS.LA.BELIEF_STATE_REORDERING","MS.LA.GROUP_SIGMA_REORDERING","MS.LA.BELIEF_SIGMA_INTERACTION","MS.LA.COST_TIEBREAK_CHANGE","MS.LA.PAIR_COMPLETION_DELAY","MS.LA.PAIR_OPENER_CHANGE","MS.LA.SAME_SET_DIFFERENT_ORDER","MS.LA.BUDGET_CROWD_OUT","MS.LA.CONSERVATIVE_NONCOMMITMENT","MS.LA.NO_STABLE_MECHANISM"],
    "gate_ids":["G-ACT-IG-SCORE_FLATTENING","G-ACT-IG-BELIEF_STATE_REORDERING","G-ACT-IG-GROUP_SIGMA_REORDERING","G-ACT-IG-BELIEF_SIGMA_INTERACTION","G-ACT-IG-COST_TIEBREAK_CHANGE","G-ACT-IG-PAIR_COMPLETION_DELAY","G-ACT-IG-PAIR_OPENER_CHANGE","G-ACT-IG-SAME_SET_DIFFERENT_ORDER","G-ACT-IG-BUDGET_CROWD_OUT","G-ACT-IG-CONSERVATIVE_NONCOMMITMENT","G-ACT-LA-SCORE_FLATTENING","G-ACT-LA-BELIEF_STATE_REORDERING","G-ACT-LA-GROUP_SIGMA_REORDERING","G-ACT-LA-BELIEF_SIGMA_INTERACTION","G-ACT-LA-COST_TIEBREAK_CHANGE","G-ACT-LA-PAIR_COMPLETION_DELAY","G-ACT-LA-PAIR_OPENER_CHANGE","G-ACT-LA-SAME_SET_DIFFERENT_ORDER","G-ACT-LA-BUDGET_CROWD_OUT","G-ACT-LA-CONSERVATIVE_NONCOMMITMENT","G-ACTIONABILITY-COMPLETE"],
    "descriptive_only_ids":[],
    "decision_uses":["P_RAW","VETOED_TUPLES","P","UNIQUE_ACTIONABLE_MECHANISM","B_DESIGN_ONE_MODIFICATION","C_NO_STABLE_MECHANISM"]
  },
  {
    "research_question_id":"REPORT_COSTS","estimand_ids":["calibrated_minus_fixed"],
    "contrast_ids":["BR-D029","BR-D030","BR-D031","BR-D032","BR-D033","BR-D034"],
    "statistical_hypothesis_ids":[],"gate_ids":[],
    "descriptive_only_ids":["BR-D029","BR-D030","BR-D031","BR-D032","BR-D033","BR-D034"],"decision_uses":[]
  },
  {
    "research_question_id":"REPORT_OBJECTIVE","estimand_ids":["calibrated_minus_fixed"],
    "contrast_ids":["BR-D035","BR-D036"],"statistical_hypothesis_ids":[],"gate_ids":[],
    "descriptive_only_ids":["BR-D035","BR-D036"],"decision_uses":[]
  }
]
```

## 3. Metrics and Outcome Labels

### 3.1 Scientific metrics

Let `p` be the final posterior, `h_star` evaluator-only truth, and `epsilon=1e-15` for
scoring only.

| metric_id | exact definition | favorable direction |
| --- | --- | --- |
| `true_probability` | `p(h_star)` | higher |
| `confidently_wrong` | `1` iff `max(p)>=0.80` and stable top ID is not `h_star` | lower |
| `nll` | `-ln(max(p(h_star),epsilon))` | lower |
| `brier` | `sum_h (p(h)-I[h=h_star])^2` | lower |
| `ece` | weighted top-label ECE in ten bins, rebuilt from raw paired predictions | lower |
| `posterior_entropy` | `-sum_h p(h)*log2(p(h))`, with `0*log2(0)=0` | lower |
| `conditional_brier_efficiency` | `((2/3)-brier)/decision_cost` | higher |
| `end_to_end_brier_efficiency` | `((2/3)-brier)/required_total_cost` | higher |
| `decision_cost` | ordered sum of real decision and setup costs | lower |
| `calibration_cost` | zero for fixed; ordered prefix deployment cost for calibrated | lower |
| `required_total_cost` | `decision_cost+calibration_cost` in that order | lower |
| `best_observed_objective` | maximum selected non-setup objective, or null | higher |
| `first_action_divergence` | paired sequence differs at action one | lower |
| `any_divergence` | paired ordered sequences differ anywhere | lower |
| `harm_risk` | weighted `hurt` indicator among divergent pairs | lower |
| `combined_numerical_share` | primary SF or GSR label among classifiable divergences | higher |

Top-hypothesis ties use stable scientific hypothesis ID. ECE edges are
`[0.0,0.1,...,1.0]`; bins are left-closed/right-open except the final bin includes `1.0`.
Empty bins contribute zero.

### 3.2 Pair labels

With `tau=1e-12`:

- `helped`: calibrated NLL and Brier are both lower than fixed by more than `tau`;
- `hurt`: both are higher by more than `tau`;
- `mixed`: neither joint condition holds; and
- `nondivergent`: ordered candidate sequences are identical.

Help, harm, and scientific correctness are evaluator-stage labels. They are never policy or
truth-free-classifier inputs.

### 3.3 Cost accounting

Each calibrated run references three five-effect prefixes. A prefix is physically generated
once per `(world,seed,comparison_group)` and reused by two policies and three budgets.
Deployment calibration cost is charged to every calibrated run. Physical study cost counts
each prefix once and each selected decision action once. A calibrated run's physical cost
share is `decision_cost + calibration_cost/6`; a fixed run's share is `decision_cost`.

## 4. Missingness, Estimability, and Weighting

### 4.1 Paired complete cases

Every contrast records:

```text
n_total_pairs
n_complete_pairs
n_fixed_missing_only
n_calibrated_missing_only
n_both_missing
```

A pair contributes to a nullable metric only when both members have defined values. Missing
values are never replaced by zero. The five counts must partition `n_total_pairs`.

Support, zero-denominator handling, and resulting field nullability are defined only by the
owning Appendix A.8 `MISS-*` formula row. A zero weighted denominator is preserved as zero
before that formula is evaluated; it is never replaced by a raw row count or imputed value.

For ECE, a complete pair supplies both complete raw top-label prediction rows; ECE is rebuilt
after every resample. For non-null metrics the missing-only counts are zero unless a run
failed, in which case the same rule applies.

For a derived pair estimand with no single-arm scalar, `n_complete_pairs` counts pairs with
every required joint label or classification; both one-sided missing counts are zero, and
`n_both_missing=n_total_pairs-n_complete_pairs`. Thus the five fields still partition the
population without pretending a missing joint label belongs to one arm.

### 4.2 Population weights

Seeds always have equal weight. The primary population gives Adam, null, and SGD truths
weight `1/3`, worlds within truth equal weight, and budgets equal weight. World-block
populations give represented truths equal weight, worlds within truth equal weight, and
budgets equal weight. Target/comparator rates retain these case weights after subsetting.

The exact population registry is:

```text
population_id|policy_scope|eligible rows|weighting
POP-PRIMARY-IG|information_gain|all 24 worlds;all 3 budgets|truth 1/3;world within truth;budget 1/3;seed equal
POP-PRIMARY-LA|lookahead_information_gain|all 24 worlds;all 3 budgets|truth 1/3;world within truth;budget 1/3;seed equal
POP-ASYM-IG|information_gain|target c_adam_a,c_sgd_a,c_adam_b,c_sgd_b;comparator d2_adam,d2_sgd;all budgets|Adam/SGD 1/2;cost_a/cost_b 1/2 in target;budget 1/3;seed equal
POP-ASYM-LA|lookahead_information_gain|same worlds and budgets as POP-ASYM-IG|same weights
POP-BUDGET-IG|information_gain|all worlds;target budgets 4.50,6.75;comparator 2.25|primary truth/world weights;target budgets 1/2;seed equal
POP-BUDGET-LA|lookahead_information_gain|same rows as POP-BUDGET-IG|same weights
POP-SAMESET-IG|information_gain|all divergent pairs;present same set different order;absent every other divergence|primary weights retained
POP-SAMESET-LA|lookahead_information_gain|same definition|primary weights retained
POP-BLOCK-IG-HOM|information_gain|homogeneous block;all budgets|represented truth;world;budget;seed equal
POP-BLOCK-IG-WEAK|information_gain|weak_effect block;all budgets|represented truth;world;budget;seed equal
POP-BLOCK-IG-HET|information_gain|heterogeneous_noise block;all budgets|represented truth;world;budget;seed equal
POP-BLOCK-IG-COST|information_gain|asymmetric_cost block;all budgets|represented truth;world;budget;seed equal
POP-BLOCK-IG-DELAY|information_gain|delay block;all budgets|represented truth;world;budget;seed equal
POP-BLOCK-LA-HOM|lookahead_information_gain|homogeneous block;all budgets|represented truth;world;budget;seed equal
POP-BLOCK-LA-WEAK|lookahead_information_gain|weak_effect block;all budgets|represented truth;world;budget;seed equal
POP-BLOCK-LA-HET|lookahead_information_gain|heterogeneous_noise block;all budgets|represented truth;world;budget;seed equal
POP-BLOCK-LA-COST|lookahead_information_gain|asymmetric_cost block;all budgets|represented truth;world;budget;seed equal
POP-BLOCK-LA-DELAY|lookahead_information_gain|delay block;all budgets|represented truth;world;budget;seed equal
POP-HIGH-IG|information_gain|h_adam_high,h_null_high,h_sgd_high;all budgets|truth 1/3;budget 1/3;seed equal
POP-HIGH-LA|lookahead_information_gain|same rows as POP-HIGH-IG|same weights
POP-HET-IG|information_gain|all six g_*_lmh/g_*_hml worlds;all budgets|truth 1/3;orientation 1/2;budget 1/3;seed equal
POP-HET-LA|lookahead_information_gain|same rows as POP-HET-IG|same weights
```

No other inferential population or interaction exists.

The ordered actionability-block registries are literal:

```json
{
  "IG":["POP-BLOCK-IG-HOM","POP-BLOCK-IG-WEAK","POP-BLOCK-IG-HET","POP-BLOCK-IG-COST","POP-BLOCK-IG-DELAY"],
  "LA":["POP-BLOCK-LA-HOM","POP-BLOCK-LA-WEAK","POP-BLOCK-LA-HET","POP-BLOCK-LA-COST","POP-BLOCK-LA-DELAY"]
}
```

For every policy-mechanism actionability tuple, all five corresponding block results are
stored in this order. Each result uses only its named population's weighting rule. The five
effects are never averaged, pooled, or reweighted together.

## 5. Normative Statistical And Registry Definitions

### 5.1 Sole authority and exact operand bindings

This section, the literal formula rows in Appendix A.8, the literal gate-condition rows in
Appendix A.9, and the binding rows below are the sole machine-binding source of truth for
statistical and registry semantics. Appendix A.8 is incorporated into this section by
normative reference: each `formula_id` has exactly one mathematical definition, in that
literal A.8 row. Appendix A.9 likewise has exactly one executable predicate per
`condition_id`. Every other section may only cite those IDs and may not restate, specialize,
or replace their mathematics. A second nonidentical definition is a fatal A13 and A15
failure.

The nonduplicative authority index is:

```text
concept|sole normative formula or registry authority
sign-flip procedure|signflip_10000
bootstrap procedure|bootstrap_10000
Holm family|HOLM-64
weighted denominator family|DEN-PAIRED;DEN-DIVERGENT;DEN-TWO-DIVERGENT-RATES;DEN-PRESENT-ABSENT;DEN-CLASSIFIABLE;DEN-ALL-PAIRS
helped-minus-hurt numerator|NUM-HELP-HURT
mechanism support|MISS-MECHANISM20
three-valued AND|F-AND
three-valued OR|F-HARD-SAFETY
Branch B authorization|F-B-AUTHORIZATION;G-B-AUTHORIZATION/C01
final gate status and branch selection|F-DECISION-TABLE;G-FINAL
resampling discriminator and row contract|resample_record_type;Appendix B.3 artifact 9
gate-status field and enum|gate_status;Appendix B.1 BranchTrace;Appendix B.3 artifacts 10 and 13
```

All formula-local operands below are paths in the owning contrast evaluation, not global
registry IDs. The following binding registry is exhaustive: every one of the 122 contrast
IDs appears exactly once, and the ordered operands are passed unchanged to the named A.8
formula rows.

```text
numerator_formula_id|denominator_formula_id|missingness_formula_id|literal_contrast_ids|ordered_numerator_operands|ordered_denominator_operands
NUM-CMF|DEN-PAIRED|MISS-PAIR20|BR-C001;BR-C002;BR-C004;BR-C005;BR-C006;BR-C007;BR-C009;BR-C010;BR-C012;BR-C013;BR-C015;BR-C016;BR-C047;BR-C048;BR-C049;BR-C050;BR-C051;BR-C052;BR-C053;BR-C054;BR-C055;BR-C056;BR-C057;BR-C058;BR-C059;BR-C060;BR-C061;BR-C062;BR-C063;BR-C064;BR-C065;BR-C066;BR-D001;BR-D002;BR-D004;BR-D005;BR-D006;BR-D007;BR-D009;BR-D010;BR-D011;BR-D012;BR-D014;BR-D015;BR-D016;BR-D017;BR-D019;BR-D020;BR-D029;BR-D030;BR-D031;BR-D032;BR-D033;BR-D034;BR-D035;BR-D036|paired_rows;metric_id;seed_block_weights|paired_rows;complete_pair_indicator;seed_block_weights
NUM-ECE|DEN-PAIRED|MISS-PAIR20|BR-C003;BR-C008;BR-D003;BR-D008;BR-D013;BR-D018|paired_probability_rows;ece_bin_edges;seed_block_weights|paired_probability_rows;complete_pair_indicator;seed_block_weights
NUM-HELP-HURT|DEN-DIVERGENT|MISS-DIVERGENT20|BR-C011;BR-C014|divergent_outcome_rows;seed_block_weights;helped_label;hurt_label;mixed_label|divergent_outcome_rows;seed_block_weights;helped_label;hurt_label
NUM-HARM-RIGHT-LEFT|DEN-TWO-DIVERGENT-RATES|MISS-TWO-RATES20|BR-C017;BR-C018;BR-C019;BR-C020|target_divergent_rows;comparator_divergent_rows;seed_block_weights;helped_label;hurt_label|target_divergent_rows;comparator_divergent_rows;seed_block_weights;helped_label;hurt_label
NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-SEQUENCE30|BR-C021;BR-C022|sequence_present_rows;sequence_absent_rows;seed_block_weights;helped_label;hurt_label|sequence_present_rows;sequence_absent_rows;seed_block_weights;helped_label;hurt_label
NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|BR-C023;BR-C024;BR-C025;BR-C026;BR-C027;BR-C028;BR-C029;BR-C030;BR-C031;BR-C032;BR-C034;BR-C035;BR-C036;BR-C037;BR-C038;BR-C039;BR-C040;BR-C041;BR-C042;BR-C043;BR-C044;BR-C046|mechanism_present_rows;mechanism_absent_rows;seed_block_weights;helped_label;hurt_label|mechanism_present_rows;mechanism_absent_rows;seed_block_weights;helped_label;hurt_label
NUM-COMBINED-SHARE|DEN-CLASSIFIABLE|MISS-DOMINANCE30|BR-C067;BR-C068|weighted_classifiable_denominator;COUNT-PRIMARY-SF-IG;COUNT-PRIMARY-GSR-IG;COUNT-PRIMARY-SF-LA;COUNT-PRIMARY-GSR-LA|classifiable_divergences;seed_block_weights
NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|BR-J001;BR-J002;BR-J003;BR-J004;BR-J005;BR-J006;BR-J007;BR-J008;BR-J009;BR-J010;BR-J011;BR-J012;BR-J013;BR-J014;BR-J015;BR-J016;BR-J017;BR-J018;BR-J019;BR-J020|decision_contrast_rows;five_block_rows;source_confirmatory_row|mechanism_present_rows;mechanism_absent_rows;seed_block_weights;helped_label;hurt_label
NUM-DIVERGENCE-RD|DEN-ALL-PAIRS|MISS-PAIR20|BR-D021;BR-D022;BR-D023;BR-D024;BR-D025;BR-D026;BR-D027;BR-D028|target_pairs;comparator_pairs;seed_block_weights|comparison_rows;seed_block_weights
```

The `MISS-MECHANISM20` support binding is also exhaustive and applies only to the 22 literal
contrast IDs in its row above. For each such `contrast_id`, its exact local operands are:

```text
helped_support_operands = <contrast_id>.weighted_present_helped_sum;<contrast_id>.weighted_absent_helped_sum
hurt_support_operands = <contrast_id>.weighted_present_hurt_sum;<contrast_id>.weighted_absent_hurt_sum
weighted_denominator_operands = <contrast_id>.weighted_present_helped_sum+<contrast_id>.weighted_present_hurt_sum;<contrast_id>.weighted_absent_helped_sum+<contrast_id>.weighted_absent_hurt_sum
seed_block_operand = <contrast_id>.n_complete_seed_blocks
mixed_case_treatment = exclude from helped sums, hurt sums, weighted denominators, and n_complete_seed_blocks; retain in descriptive comparison provenance
complete_case_treatment = include only rows with a complete divergent outcome label and complete truth-free primary-mechanism label; a complete seed block is a full-study seed ID with positive complete-case present and absent weighted denominators in that contrast
null_propagation = exclude and count unresolved rows; if either weighted denominator is nonpositive, n_complete_seed_blocks is below 20, or a required operand is null, set estimate, interval, and p fields null and set result_status INCONCLUSIVE and estimability_status not_estimable
```

No helped, hurt, present, or absent raw-case minimum is implied by `MISS-MECHANISM20`.
Its only support threshold is the `20` complete-seed-block predicate in formula row
`MISS-MECHANISM20`. Formula row `MISS-DIVERGENT20`, which is bound only to `BR-C011` and
`BR-C014`, separately retains its literal 20-helped and 20-hurt raw-case requirement.

### 5.2 Threshold and three-valued-logic ownership

All unchanged confirmatory thresholds are defined only in formula rows `F-CAL`, `F-CTRL`,
`F-HARD-SAFETY`, `F-CONCENTRATION`, `F-DOMINANCE`, `F-ORDER`, and `F-ACTION`. Universal
three-valued AND semantics are defined only by `F-AND`; universal three-valued OR semantics
are defined only by `F-HARD-SAFETY`. Compound formulas cite those reductions except
`F-B-AUTHORIZATION`, whose sole dedicated inconclusive-first precedence is defined in its
A.8 row. Missing, nonfinite, zero-denominator, or under-supported atomic operands first
become `INCONCLUSIVE`; the owning three-valued formula then determines the compound result.
No unresolved operand is converted to `PASS` or `FAIL`.

### 5.3 Sign-flip and Holm ownership

Formula row `signflip_10000` is the sole definition of the sign-flip seed preimage, stream,
label swap, statistic, inclusive-extreme rule, and raw p-value. Formula row `HOLM-64` is the
sole definition of the one ordered 64-member family, non-estimable-member treatment,
tie-breaking, and adjusted p-values. `contrast_id` is the sole resampling identity. No
per-seed digest-bit procedure, UTF-8 hypothesis-ID sort, or null-member exclusion is valid.

### 5.4 Bootstrap ownership and frozen workload

Formula row `bootstrap_10000` is the sole definition of bootstrap seed derivation,
SplitMix64 sampling, valid/null replicate handling, and percentile intervals. Only the 66
literal confirmatory contrasts are bootstrapped; decision rows reuse their source and
descriptive rows are not resampled.

```text
bootstrap: 66 * 10,000 = 660,000 replicates = 84,480,000 sampled positions
sign flip: 64 * 10,000 = 640,000 replicates = 81,920,000 sign positions
total resampling rows = 1,300,000
total sampled/sign positions = 166,400,000
```

Every row uses the single `resampling_audit.jsonl` schema and `record_type` discriminator in
Appendix B. No alternate resampling definition or artifact field is permitted.

## 6. Mechanisms, Actionability, and Veto

### 6.1 Frozen mechanism semantics

The eleven valid-study truth-free primary labels, in order, are:

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
NO_STABLE_MECHANISM
```

`mechanism_present` means primary-label equality only. Contributing and any-label views are
not registered and cannot affect a result. The actionability allowlist is the first ten
labels. `NO_STABLE_MECHANISM` is not actionable.

Truth-free classification is finalized and hashed before evaluator truth, help/hurt labels,
or correctness metrics are joined.

`PLANNER_MODEL_MISMATCH` is not a scientific mechanism ID. Planner replay recomputes every
recorded decision from that decision's recorded public state using the recorded policy,
belief lineage, belief model and sigma target, candidate set, costs, and remaining budget.
The selected candidate must match exactly; candidate ordering and all recorded EIG, expected
cost, branch probability, branch posterior, and tie-break score fields must agree within the
frozen `1e-12` numerical tolerance.
Any missing replay input, score mismatch, rank mismatch, or selected-candidate mismatch sets
`terminal_reason=integrity_abort`, fails `A09-PLANNER-AND-EVIDENCE`, and invalidates the
entire study directory. Such diagnostics exist only in the audit failure context and never
enter a mechanism registry, comparison row, contrast, Holm family, or scientific report.

### 6.2 Actionability result for one tuple

The eligible universe is the 20 literal `BR-J` rows in Appendix A.3. Formula `F-ACTION` is
the sole tuple predicate, including every threshold, block-support operand, provenance
check, and three-valued reduction. Formula `F-ACTION-COMPLETE` alone constructs `P_RAW` and
`ACTIONABILITY_COMPLETE`. This section does not restate either formula.

### 6.3 Opposite-direction veto

Appendix A.4 contains all 20 possible veto rows. Their sole predicate is formula
`F-VETO`. Every tuple in `P_RAW` has exactly one required `veto_status`: `VETOED`,
`NOT_VETOED`, or `INCONCLUSIVE`. Decision symbols are computed only by
`F-VETO-COMPLETE`, `F-P`, `F-UNIQUE-MECHANISM`, and `F-B-AUTHORIZATION`; this section adds
no alternate predicate.

`P` contains only tuples whose `veto_status` is `NOT_VETOED`. `VETOED` tuples enter only
`VETOED_TUPLES`; `INCONCLUSIVE` tuples enter neither set. If any veto required by `P_RAW` is
`INCONCLUSIVE`, `VETO_COMPLETE` is inconclusive and the Branch B evaluations of
`P_NONEMPTY`, distinct-mechanism count, and every other `P`-derived predicate are also
`INCONCLUSIVE`, even when the materialized `P` list is empty. They are not `FAIL`.
`F-B-AUTHORIZATION` therefore returns `INCONCLUSIVE` before evaluating any resolved-failure
condition. Only after every required veto and authorization operand is resolved may an empty
`P` or another failed condition make `B_AUTHORIZED` fail.

## 7. Exhaustive A/B/C/D Decision Procedure

### 7.1 Resolved booleans

Every named boolean is stored as `{value:BOOL?,resolution_status:resolved|inconclusive}`.
For gate-facing language, resolved true is `PASS`, resolved false is `FAIL`, and an
inconclusive boolean has `value=null` and is `INCONCLUSIVE`. Formula rows
`F-CONTROLLER-CHANGE`, `F-PPO`, and `F-B-AUTHORIZATION` are the sole definitions of those
booleans. `F-B-AUTHORIZATION` uses its dedicated inconclusive-first precedence rather than
ordinary `F-AND`.

### 7.2 Sole decision table

The literal ordered branch registry in Appendix A.6 and formula `F-DECISION-TABLE` are the
sole decision table. No prose condition is executable. Branch B matches only when
`B_AUTHORIZED=PASS`. When `CONTROLLER_CHANGE_NEEDED=PASS`, Branch C matches whenever
`B_AUTHORIZED` is `FAIL` or `INCONCLUSIVE`. An inconclusive actionability or veto operand
therefore makes B impossible without being converted to false. `G-FINAL` records
`gate_status` under `F-DECISION-TABLE`, and its branch trace preserves every unresolved
predecessor. No output changes the controller in this study.

## 8. Frozen Worlds and Oracle

### 8.1 Public candidate catalog

Controlled fingerprints are parsed from these decimal strings once with Python 3.12
binary64 semantics:

| fingerprint_id | controlled fingerprint |
| --- | --- |
| `cf-g00` | `[["learning_rate","0.001"],["model_width",64],["regularization","0"]]` |
| `cf-g01` | `[["learning_rate","0.003"],["model_width",128],["regularization","0.01"]]` |
| `cf-g02` | `[["learning_rate","0.01"],["model_width",256],["regularization","0.05"]]` |
| `cf-objective-only` | `[["learning_rate","0.02"],["model_width",32],["regularization","0.10"]]` |

| candidate_id | family | comparison_group | controls | intervention | replication_id | role |
| --- | --- | --- | --- | --- | --- | --- |
| `g00-adam-r1` | `optimizer-effect` | `group-00` | `cf-g00` | `optimizer=adam` | `decision-group-00-r0001` | `optimizer_arm` |
| `g00-sgd-r1` | `optimizer-effect` | `group-00` | `cf-g00` | `optimizer=sgd` | `decision-group-00-r0001` | `optimizer_arm` |
| `g01-adam-r1` | `optimizer-effect` | `group-01` | `cf-g01` | `optimizer=adam` | `decision-group-01-r0001` | `optimizer_arm` |
| `g01-sgd-r1` | `optimizer-effect` | `group-01` | `cf-g01` | `optimizer=sgd` | `decision-group-01-r0001` | `optimizer_arm` |
| `g02-adam-r1` | `optimizer-effect` | `group-02` | `cf-g02` | `optimizer=adam` | `decision-group-02-r0001` | `optimizer_arm` |
| `g02-sgd-r1` | `optimizer-effect` | `group-02` | `cf-g02` | `optimizer=sgd` | `decision-group-02-r0001` | `optimizer_arm` |
| `g00-setup-r1` | `optimizer-setup` | `setup-group-00` | `cf-g00` | `setup=enable` | `setup-group-00-r0001` | `setup` |
| `g01-setup-r1` | `optimizer-setup` | `setup-group-01` | `cf-g01` | `setup=enable` | `setup-group-01-r0001` | `setup` |
| `g02-setup-r1` | `optimizer-setup` | `setup-group-02` | `cf-g02` | `setup=enable` | `setup-group-02-r0001` | `setup` |
| `irrelevant-objective-r1` | `objective-only` | `objective-only-00` | `cf-objective-only` | `none=irrelevant` | `irrelevant-r0001` | `irrelevant` |
| `redundant-objective-r1` | `objective-only` | `objective-only-00` | `cf-objective-only` | `none=redundant` | `redundant-r0001` | `redundant` |

The optimizer evidence intervention variable is exactly `optimizer`, with complementary
arms `adam` and `sgd`. Setup and objective-only candidates fail optimizer evidence
eligibility.

Depth-two `candidate_ids` and initial feasible IDs, in order, are the six optimizer arms
shown above followed by `irrelevant-objective-r1,redundant-objective-r1`. Depth-three
`candidate_ids` are the three setup rows, the six optimizer rows, then the two objective
rows; its initial feasible IDs are the three setup rows followed by the two objective rows.
Every world has comparison groups `group-00,group-01,group-02` and all three budgets.

### 8.2 Costs and calibration candidates

| cost_catalog_id | g00 Adam/SGD | g01 Adam/SGD | g02 Adam/SGD | setup | irrelevant | redundant |
| --- | --- | --- | --- | ---: | ---: | ---: |
| `cost-symmetric/v1` | `1.00/1.00` | `1.00/1.00` | `1.00/1.00` | `0.25` | `0.50` | `0.75` |
| `cost-a/v1` | `0.50/1.00` | `1.00/1.00` | `1.25/1.75` | `0.25` | `0.50` | `0.75` |
| `cost-b/v1` | `1.75/1.25` | `1.00/1.00` | `1.00/0.50` | `0.25` | `0.50` | `0.75` |

Calibration candidate IDs are
`cal-{group_index}-{arm}-r{replication_index:04d}` for groups `00,01,02`, arms
`adam,sgd`, and replications `0001..0005`. Complementary arms share replication ID
`calibration-{group_index}-r{replication_index:04d}`. Calibration candidates are never
decision candidates. Their costs equal corresponding optimizer-arm costs.

Calibrated arms receive exactly five completed matched effects per group. The ordinary
sample standard deviation uses `ddof=1`; `estimated_sigma=max(sample_sd,0.05)`. Prefix
effects never update scientific beliefs. Fixed arms cannot read prefixes or estimated
sigmas. Both models begin decision time at the same uniform scientific prior.

### 8.3 World generator

Group midpoints are `group-00=0.55`, `group-01=0.60`, and `group-02=0.65`. For effect
magnitude `e`:

```text
Adam truth: mu_adam=m+e/2; mu_sgd=m-e/2
Null truth: mu_adam=m;     mu_sgd=m
SGD truth:  mu_adam=m-e/2; mu_sgd=m+e/2
```

Optimizer and calibration observations are `mu_arm + sigma_group*z`. Matched effect is
always `observed_adam-observed_sgd`. Irrelevant and redundant candidates have hidden mean
`0.60` and sigma equal to the numeric median group sigma; they have distinct oracle keys.
Setup has no objective and invokes no oracle.

### 8.4 Exact worlds

| world_id | block | scientific_hypothesis_id | effect_size | group sigmas g00/g01/g02 | cost catalog | depth |
| --- | --- | --- | ---: | --- | --- | ---: |
| `h_adam_low` | homogeneous | `optimizer.adam-advantage` | `0.12` | `0.02/0.02/0.02` | `cost-symmetric/v1` | 2 |
| `h_null_low` | homogeneous | `optimizer.no-consistent-advantage` | `0.00` | `0.02/0.02/0.02` | `cost-symmetric/v1` | 2 |
| `h_sgd_low` | homogeneous | `optimizer.sgd-advantage` | `0.12` | `0.02/0.02/0.02` | `cost-symmetric/v1` | 2 |
| `h_adam_high` | homogeneous | `optimizer.adam-advantage` | `0.12` | `0.20/0.20/0.20` | `cost-symmetric/v1` | 2 |
| `h_null_high` | homogeneous | `optimizer.no-consistent-advantage` | `0.00` | `0.20/0.20/0.20` | `cost-symmetric/v1` | 2 |
| `h_sgd_high` | homogeneous | `optimizer.sgd-advantage` | `0.12` | `0.20/0.20/0.20` | `cost-symmetric/v1` | 2 |
| `w_adam_medium` | weak_effect | `optimizer.adam-advantage` | `0.04` | `0.05/0.05/0.05` | `cost-symmetric/v1` | 2 |
| `w_sgd_medium` | weak_effect | `optimizer.sgd-advantage` | `0.04` | `0.05/0.05/0.05` | `cost-symmetric/v1` | 2 |
| `g_adam_lmh` | heterogeneous_noise | `optimizer.adam-advantage` | `0.12` | `0.02/0.10/0.20` | `cost-symmetric/v1` | 2 |
| `g_null_lmh` | heterogeneous_noise | `optimizer.no-consistent-advantage` | `0.00` | `0.02/0.10/0.20` | `cost-symmetric/v1` | 2 |
| `g_sgd_lmh` | heterogeneous_noise | `optimizer.sgd-advantage` | `0.12` | `0.02/0.10/0.20` | `cost-symmetric/v1` | 2 |
| `g_adam_hml` | heterogeneous_noise | `optimizer.adam-advantage` | `0.12` | `0.20/0.10/0.02` | `cost-symmetric/v1` | 2 |
| `g_null_hml` | heterogeneous_noise | `optimizer.no-consistent-advantage` | `0.00` | `0.20/0.10/0.02` | `cost-symmetric/v1` | 2 |
| `g_sgd_hml` | heterogeneous_noise | `optimizer.sgd-advantage` | `0.12` | `0.20/0.10/0.02` | `cost-symmetric/v1` | 2 |
| `c_adam_a` | asymmetric_cost | `optimizer.adam-advantage` | `0.12` | `0.05/0.05/0.05` | `cost-a/v1` | 2 |
| `c_sgd_a` | asymmetric_cost | `optimizer.sgd-advantage` | `0.12` | `0.05/0.05/0.05` | `cost-a/v1` | 2 |
| `c_adam_b` | asymmetric_cost | `optimizer.adam-advantage` | `0.12` | `0.05/0.05/0.05` | `cost-b/v1` | 2 |
| `c_sgd_b` | asymmetric_cost | `optimizer.sgd-advantage` | `0.12` | `0.05/0.05/0.05` | `cost-b/v1` | 2 |
| `d2_adam` | delay | `optimizer.adam-advantage` | `0.12` | `0.05/0.05/0.05` | `cost-symmetric/v1` | 2 |
| `d2_null` | delay | `optimizer.no-consistent-advantage` | `0.00` | `0.05/0.05/0.05` | `cost-symmetric/v1` | 2 |
| `d2_sgd` | delay | `optimizer.sgd-advantage` | `0.12` | `0.05/0.05/0.05` | `cost-symmetric/v1` | 2 |
| `d3_adam` | delay | `optimizer.adam-advantage` | `0.12` | `0.05/0.05/0.05` | `cost-symmetric/v1` | 3 |
| `d3_null` | delay | `optimizer.no-consistent-advantage` | `0.00` | `0.05/0.05/0.05` | `cost-symmetric/v1` | 3 |
| `d3_sgd` | delay | `optimizer.sgd-advantage` | `0.12` | `0.05/0.05/0.05` | `cost-symmetric/v1` | 3 |

Truth margins are Adam/null/SGD `9/6/9`; cost margins symmetric/cost_a/cost_b `20/2/2`;
depth margins depth-two/depth-three `21/3`. This is a fractional contrast design, not a
factorial design. Unsupported interactions are not reported.

Budget compatibility is constructive: a symmetric depth-two pair costs `2.00`, the
cheapest asymmetric pair costs `1.50`, and a depth-three setup plus pair costs `2.25`.
Every world therefore has an informative feasible path under every declared budget.

### 8.5 Depth-three public adapter

Initially, a depth-three world exposes three setup and two objective-only candidates. A
successful setup costs `0.25`, invokes no oracle, creates no evidence, and unlocks only its
group's Adam and SGD candidates at the next real decision. Candidate addition depends only
on public setup completion. The policy replans from persisted state with its unchanged
horizon. Simulated setup does not unlock a real candidate or persist a hypothetical state.

### 8.6 Selected-only oracle

Decision keys are:

```text
["rde.broader.decision-outcome/v1","broader-closed-loop-replication/v1",
 "broader_selected_only_oracle/v1",world_id,base10_seed,candidate_id,
 decision_replication_id]
```

Calibration keys are:

```text
["rde.broader.calibration-outcome/v1","broader-closed-loop-replication/v1",
 "broader_selected_only_oracle/v1",world_id,base10_seed,comparison_group_id,
 intervention_arm,calibration_replication_id]
```

Arrays use UTF-8 canonical JSON without whitespace or trailing LF. Compute SHA-256,
`q64=int.from_bytes(digest[0:8],"big")`, `k=q64>>12`, and exact
`u=(2*k+1)/2**53` under a fresh Decimal context:

```text
prec=80; rounding=ROUND_HALF_EVEN; Emin=-999999; Emax=999999; capitals=1; clamp=0
traps: InvalidOperation,DivisionByZero,Overflow,FloatOperation=true
traps: Underflow,Subnormal,Inexact,Rounded,Clamped=false
all flags cleared before each key
```

The frozen Acklam approximation uses no Newton refinement:

```text
p_low=Decimal("0.02425"); p_high=Decimal("0.97575")
a=[-39.69683028665376,220.9460984245205,-275.9285104469687,
   138.3577518672690,-30.66479806614716,2.506628277459239]
b=[-54.47609879822406,161.5858368580409,-155.6989798598866,
   66.80131188771972,-13.28068155288572]
c=[-0.007784894002430293,-0.3223964580411365,-2.400758277161838,
   -2.549732539343734,4.374664141464968,2.938163982698783]
d=[0.007784695709041462,0.3224671290700398,2.445134137142996,
   3.754408661907416]
P(v,C)=(((((C0*v+C1)*v+C2)*v+C3)*v+C4)*v+C5)
Q(v,D)=((((D0*v+D1)*v+D2)*v+D3)*v+1)
if u<p_low: q=sqrt(-2*ln(u)); z=P(q,c)/Q(q,d)
elif u<=p_high:
    q=u-0.5; r=q*q
    z=(((((a0*r+a1)*r+a2)*r+a3)*r+a4)*r+a5)*q \
      /(((((b0*r+b1)*r+b2)*r+b3)*r+b4)*r+1)
else: q=sqrt(-2*ln(1-u)); z=-(P(q,c)/Q(q,d))
```

Every coefficient is constructed from the displayed decimal string. Quantize `u` to
exponent `1E-53` and format exactly 53 fractional digits. Quantize `z` once to exponent
`1E-30`, normalize negative zero, and format exactly 30 fractional digits. Both use
`ROUND_HALF_EVEN`. Convert only the canonical `z` string to CPython
`>=3.12.0,<3.13.0` IEEE-754 binary64 for world evaluation, in the parenthesized order
`float(mu)+(float(sigma)*z_binary64)`. Binary `log`, binary `sqrt`, FMA, and extended
precision are prohibited.

The complete truth-free conformance domain is unchanged:

```text
full decision keys     24*128*8             = 24,576
full calibration keys  24*128*3*2*5         = 92,160
smoke keys             8*4*8 + 8*4*3*2*5   = 1,216
total                                          117,952
```

Enumeration order is full decision, full calibration, smoke decision, smoke calibration;
within each partition it is world-table order, ascending seed, the six optimizer candidates
then irrelevant and redundant for decision keys, and group, arm `adam,sgd`, replication
`0001..0005` for calibration keys. Setup has no key. For each key, append one canonical
JSON line `[namespace,serialized_key_hex,digest_hex,u_string,z_string]`, then hash the
concatenation. Its frozen digest is
`0452652278d2670ac11f923a6919cae923b2baf88d2ea9b0356a5d4923dc706c`.
Conformance values are never persisted or exposed. Policy-facing oracle access has only
`observe_selected`; it has no enumerate, list, peek, bulk, or counterfactual method.

## 9. Reproducibility, Hashing, and Source Freeze

### 9.1 Common metadata envelope

Every canonical artifact has exactly these five metadata fields, in this order for CSV and
as top-level fields for JSON:

```text
schema_version:ID
protocol_version:ID
source_design_sha256:SHA256
source_checkpoint_identifier:GIT40
scientific_payload_sha256:SHA256
```

There is no four-field variant. JSONL line one is one metadata record; data begin at line
two. The canonical registry contains no Markdown artifact; the optional report uses the
noncanonical provenance comment defined in Appendix B.

### 9.2 Canonical serialization

JSON is UTF-8 without BOM, sorted keys, separators `,` and `:`, no insignificant
whitespace, lowercase literals, and one final LF. JSONL uses one canonical object per line.
CSV is UTF-8, RFC 4180, comma-delimited, exact header, LF endings, and canonical JSON in
list/map cells. Markdown is UTF-8 with LF endings. Arrays preserve declared order.

`F64` artifact values are strings `f64:` plus 16 lowercase hexadecimal big-endian IEEE-754
bits. Values must be finite; negative zero is normalized. IDs match
`[A-Za-z0-9][A-Za-z0-9._:/-]*`.

Define:

```text
H(namespace,payload)=SHA256(canonical_json(["rde.broader.hash/v3",namespace,payload]))
```

Here `canonical_json` uses the JSON rules above but has no final LF. Every object contains
exactly the listed fields; canonical key order is UTF-8 byte order. Arrays retain the stated
semantic order. Null is the JSON token `null`. Every numeric preimage value is an `I64`,
`U64`, or canonical `F64` string; decimal display text never enters a hash unless its type is
explicitly `STRING`.

Registry identifiers are literal human-readable IDs only. For each registry, the table or
typed schema freezes an ordered field list excluding its own hash field. Its integrity field
has this complete preimage:

```text
<entity>_sha256 = H("registry_content/v1",{
  "schema_version":"registry-content/v1",
  "entity_type":ID,
  "literal_id":ID,
  "ordered_field_names":LIST<ID>,
  "field_values":LIST<STRING|ID|I64|F64|BOOL|LIST<ID>|null>
})
```

`ordered_field_names` is exactly the registry header order with its `*_sha256` field removed;
`field_values` has the same length and positional values with no coercion or omitted null.
This applies to question, scientific-hypothesis, statistical-hypothesis, metric, estimand,
mechanism, population, count-symbol, decision-symbol, predicate, budget, contrast, veto,
formula, gate-condition, gate, audit, controller-stage, branch, artifact, and enum records.
`condition_id` is only `gate_id + "/C" + two_digit_ordinal`. There is no hash-derived gate,
condition, audit, or contrast ID and no `/ctx` convention.

Exactly four runtime identities are hash-derived. Each is `prefix:` plus the complete digest:

```text
run_id = "run:" + H("run_id/v1",{
  "arm_id":ID,"budget":F64,"seed":I64,"world_id":ID
})
comparison_id = "comparison:" + H("comparison_id/v1",{
  "budget":F64,"policy_id":policy_id,"seed":I64,"world_id":ID
})
authorization_id = "authorization:" + H("authorization_id/v1",{
  "candidate_id":ID,"kind":"calibration"|"decision","run_id":ID,"source_id":ID
})
oracle_key_id = "oracle-key:" + H("oracle_key_id/v1",{
  "key_fields":LIST<STRING>
})
```

All other runtime IDs are literal deterministic templates:

```text
evaluation_id = broader-closed-loop-replication/v1
lineage_id = lineage/{run_id}
store_id = store/{run_id}
calibration_prefix_id = calibration-prefix/{world_id}/{base10(seed)}/{comparison_group_id}
sigma_estimate_id = sigma-estimate/{calibration_prefix_id}
calibration_effect_id = calibration-effect/{calibration_prefix_id}/{replication_id}
oracle_use_id = oracle-use/{authorization_id}/{oracle_key_id}
decision_id = decision/{run_id}/{step:04d}
setup_completion_id = setup-completion/{run_id}/{step:04d}/{candidate_id}
experiment_id = experiment/{run_id}/{step:04d}/{candidate_id}
evidence_id = evidence/{run_id}/{sequence:04d}
belief_state_id = belief-state/{run_id}/{sequence:04d}
belief_update_id = belief-update/{run_id}/{sequence:04d}
event_id = event/{run_id}/{sequence:04d}/{event_type}
planning_branch_id = planning-branch/{decision_id}/no-evidence-yet
  or planning-branch/{decision_id}/evidence-bin-{bin_index:03d}, bin_index 000..081
resample_id = resample/{contrast_id}/{record_type}/{replicate_index:05d}
```

The exact derived hashes and their complete payload schemas are:

```text
outcome_digest = H("revealed_outcome/v1",{
  "oracle_key_id":ID,"revealed_observation":F64
})

ordered_decisions_sha256 = H("ordered_decisions/v1",{
  "run_id":ID,"decision_ids":LIST<ID>
})

eligibility_state_sha256 = H("eligibility_state/v1",{
  "run_id":ID,"step":I64,"completed_candidate_ids":LIST<ID>,
  "unexecuted_candidate_ids":LIST<ID>,"publicly_feasible_candidate_ids":LIST<ID>,
  "affordable_candidate_ids":LIST<ID>,"remaining_budget":F64
})

public_state_sha256 = H("public_state/v1",{
  "run_id":ID,"step":I64,"belief_state_id":ID,"lineage_id":ID,
  "eligibility_state_sha256":SHA256,"remaining_budget":F64
})

mechanism_row_without_outcome_sha256 = H("truth_free_mechanism_row/v1",{
  "comparison_id":ID,"policy_id":policy_id,"first_divergence_step":I64,
  "fixed_candidate_id":ID,"calibrated_candidate_id":ID,
  "fixed_sequence":LIST<ID>,"calibrated_sequence":LIST<ID>,
  "first_action_divergent":BOOL,"sequence_class":sequence_class,
  "predicate_results":MAP<mechanism_id,BOOL>,"primary_mechanism_id":mechanism_id,
  "contributing_mechanism_ids":LIST<mechanism_id>,"controller_stage_id":ID?
})

CanonicalEventPayload={
  "schema_version":"canonical-event-payload/v1",
  "event_type":event_type,
  "event_id":ID,
  "run_id":ID,
  "sequence":I64,
  "comparison_id":ID,
  "world_id":ID,
  "seed":I64,
  "budget_id":ID,
  "arm_id":ID,
  "policy_id":policy_id,
  "controller_stage_id":ID,
  "candidate_id":ID?,
  "public_state_sha256":SHA256?,
  "ordered_decisions_sha256":SHA256,
  "eligibility_state_sha256":SHA256?,
  "belief_lineage_id":ID,
  "sigma_estimate_id":ID?,
  "cost_before":F64,
  "cost_after":F64,
  "status":run_status,
  "terminal_reason":terminal_reason?,
  "integrity_audit_id":ID?,
  "event_specific_payload":DecisionPayload|SetupPayload|ExperimentPayload|EvidencePayload|BeliefUpdatePayload|TerminalPayload
}

DecisionPayload={
  "decision_id":ID,"step":I64,"belief_model_id":belief_model_id,
  "belief_state_id":ID,"active_sigma_estimate_ids":LIST<ID>,"fixed_sigma":F64?,
  "remaining_budget":F64,"completed_candidate_ids":LIST<ID>,
  "unexecuted_candidate_ids":LIST<ID>,"publicly_feasible_candidate_ids":LIST<ID>,
  "affordable_candidate_ids":LIST<ID>,"selected_candidate_id":ID,
  "candidate_scores":LIST<CandidateScore>,"planning_branch_tree":LIST<PlanningBranchTrace>,
  "fallback_reason":STRING?,"tie_break_order":LIST<ID>
}
SetupPayload={"decision_id":ID,"setup_completion_id":ID,"cost":F64,"cumulative_decision_cost":F64}
ExperimentPayload={
  "decision_id":ID,"experiment_id":ID,"observed_objective":F64,"cost":F64,
  "cumulative_decision_cost":F64,"oracle_key_id":ID,"oracle_use_id":ID
}
EvidencePayload={
  "evidence_id":ID,"source_experiment_ids":LIST<ID>,"comparison_group_id":ID,
  "observed_effect":F64
}
BeliefUpdatePayload={
  "belief_update_id":ID,"evidence_id":ID,"fixed_sigma":F64?,
  "belief_before":BeliefSnapshot,"likelihoods":MAP<scientific_hypothesis_id,F64>,
  "belief_after":BeliefSnapshot,"update_rule_version":ID
}
TerminalPayload={
  "final_belief_state_id":ID,"remaining_budget":F64,
  "completed_candidate_ids":LIST<ID>,"unexecuted_candidate_ids":LIST<ID>,
  "publicly_feasible_candidate_ids":LIST<ID>,"affordable_candidate_ids":LIST<ID>,
  "decision_cost":F64,"calibration_cost":F64,"required_total_cost":F64
}

provenance_sha256 = SHA256(UTF8(canonical_json(CanonicalEventPayload)))

reconciliation_sha256 = H("cost_reconciliation/v1",{
  "run_id":ID,
  "ordered_event_costs":LIST<{"event_id":ID,"record_type":"setup"|"experiment",
    "cost":F64,"cumulative_decision_cost":F64}>,
  "decision_cost":F64,"calibration_prefix_ids":LIST<ID>,"calibration_cost":F64,
  "required_total_cost":F64,"physical_cost_share":F64
})

trajectory_sha256 = H("trajectory/v1",{
  "run_id":ID,"ordered_decisions_sha256":SHA256,
  "ordered_real_event_ids":LIST<ID>,"ordered_event_provenance_sha256":LIST<SHA256>,
  "terminal_reason":terminal_reason,"reconciliation_sha256":SHA256
})

audit_detail_sha256 = H("audit_detail/v1",{
  "audit_id":ID,"expected":STRING,"observed":STRING
})

details_sha256 = H("validation_failure_details/v1",{
  "phase":ID,"error_code":ID,"path":STRING,"message":STRING,
  "context":MAP<STRING,STRING>
})

sampled_seed_ids_sha256 = H("sampled_seed_ids/v1",{
  "contrast_id":ID,"replicate_index":I64,"sampled_seed_ids":LIST<I64>
})

sign_vector_sha256 = H("sign_vector/v1",{
  "contrast_id":ID,"replicate_index":I64,"ordered_signs_by_seed":LIST<I64>
})
```

The canonical event union above has this exhaustive presence contract. "Group sigma" means
`sigma_estimate_id` is required for a calibrated event tied to one comparison group and null
for its fixed-arm counterpart. Decision and terminal events instead describe multiple active
groups and therefore require the common singular field to be null.
Every common field not listed as nullable or forbidden is required. A forbidden common field
is present as JSON null so the canonical preimage always has the same common key set;
event-specific keys belonging to another payload variant are absent.

| event type | required specialization | nullable common/payload fields | forbidden fields | exact controller stage |
| --- | --- | --- | --- | --- |
| `decision` | `candidate_id`, public and eligibility hashes, `DecisionPayload`; selected candidate equals common candidate; active sigma list is empty for fixed and has the run's three group estimates for calibrated | payload `fixed_sigma` is non-null only for fixed; `fallback_reason` | common singular sigma, non-null terminal reason or integrity audit, every non-decision payload key | `CONTROLLER-STAGE-SELECTION` |
| `setup` | `candidate_id`, `SetupPayload`; `cost_after=cost_before+cost` | none | singular sigma, public and eligibility hashes, terminal reason, integrity audit, every non-setup payload key | `CONTROLLER-STAGE-EXECUTION` |
| `experiment` | `candidate_id`, `ExperimentPayload`; `cost_after=cost_before+cost`; group sigma for calibrated | singular sigma for fixed only | public and eligibility hashes, terminal reason, integrity audit, every non-experiment payload key | `CONTROLLER-STAGE-EXECUTION` |
| `evidence` | `EvidencePayload`; `cost_after=cost_before`; group sigma for calibrated | singular sigma for fixed only | candidate, public and eligibility hashes, terminal reason, integrity audit, every non-evidence payload key | `CONTROLLER-STAGE-EVIDENCE` |
| `belief_update` | `BeliefUpdatePayload`; `cost_after=cost_before`; group sigma for calibrated | singular sigma for fixed only; payload `fixed_sigma` is non-null only for fixed | candidate, public and eligibility hashes, terminal reason, integrity audit, every non-update payload key | `CONTROLLER-STAGE-BELIEF-UPDATE` |
| `terminal` | terminal reason and `TerminalPayload`; `cost_after=cost_before` | none | singular sigma, candidate, public and eligibility hashes, integrity audit in canonical output, every non-terminal payload key | `CONTROLLER-STAGE-TERMINATION` |

Canonical event status is always `complete`. Temporary validation state may contain only a
terminal event with `status=invalid`, `terminal_reason=integrity_abort`, and a non-null
`integrity_audit_id`; that event is forbidden from canonical artifacts and prevents
finalization. For every event the run, comparison, world, seed, budget, arm, policy, lineage,
and ordered-decision values must equal their owning `arm_runs.jsonl` record. There is no
default, omitted common field, alternate payload, or implementation-defined extension.

Candidate and event lists above use candidate-catalog and chronological order respectively;
they are never sorted after construction. The comparison field
`mechanism_row_without_outcome_sha256` stores exactly the hash defined above. Every listed hash is independently
recomputed during validation; no payload name is shorthand for an implementation-defined
object.

`source_design_sha256` is raw SHA-256 of exact committed design bytes.
`scientific_payload_sha256` is raw SHA-256 of the exact canonical scientific-payload bytes
defined in Appendix B.4. Scientific payloads omit only the five-field envelope and fields
explicitly marked operational in Appendix B.

### 9.3 Historical immutability universe

The before/after historical maps cover every regular file recursively under exactly:

```text
benchmark-validation-output/
lookahead-benchmark-validation-output/
paired-evaluation-v1-100-seeds/
robust-belief-evaluation-v1-100-seeds/
robust-belief-evaluation-v1-100-seeds-accepted/
closed-loop-evaluation-v1-100-seeds/
divergence-audit-v1-189-cases/
```

Map keys are NFC-normalized forward-slash paths `root-name/relative/path`, sorted by UTF-8
bytes. Values are SHA-256 of exact file bytes. Symlinks, junctions, reparse points, missing
roots, duplicate normalized paths, key-set changes, or digest changes fail validation.

### 9.4 Protected source provenance

Exact private pre-implementation provenance is retained only in external private
evidence. Public artifacts use stable semantic role tokens that do not identify a
Git object, repository ancestry, or private source revision.

| protected file | SHA-256 |
| --- | --- |
| `research_decision_engine/policies.py` | `98c0ecf1528287bc36797e3e14d46d9f28dee8982ac59b6795067c34599ed366` |
| `research_decision_engine/decision.py` | `1c028f7544ca59196844e8a6c550a786bb60ca90bfa87a779442359ca750f6d6` |
| `research_decision_engine/lookahead.py` | `a039c5b4ad8a5fed303465f10109285c6a46b84226c277550fa49a2df2dbb629` |
| `research_decision_engine/reasoning.py` | `d0bdccb3d3bbbbce24db285f45fb26027f07056962d55ebc11d536e1a47456ff` |
| `research_decision_engine/optimizer_effect.py` | `724505faef2a86e0564aa62108b116020a77f6876dbc9468ebcd199d0cd65de7` |
| `research_decision_engine/evidence_eligibility.py` | `ac58eb1f08b0f90b23c177c6ff1262ab2871c18fd6bf22dbe0fab2904ead44fe` |
| `research_decision_engine/belief_models.py` | `2b022592c6c7cb5ce52de69e27fc05dc806369aceef339a466669d5d462b78a3` |
| `research_decision_engine/calibration.py` | `18702a0772ceab15aad3a02ecc8e11503cf11958f5b12bbca3e833f8e0d115fd` |
| `research_decision_engine/closed_loop.py` | `1007aa226bec060470b1a347b0a5e9caa07e6e3d5bf13e1ae2e345f1790ec80d` |
| `research_decision_engine/benchmarks/worlds.py` | `377bedbe41ff97fe6a5c12232f6c9d2a9d1793868c253cfb837dc77f2f2215a5` |
| `research_decision_engine/benchmarks/paired_evaluation.py` | `c901d00e1f08b9ab92cef00a4e3e34dc7b74999cc7459677eaa08f925c51f2c4` |
| `research_decision_engine/benchmarks/closed_loop_evaluation.py` | `4ff9752aaafd039ab1d0a574988fdc23212a3022f9dc8e1517ec72c09a556bbb` |
| `research_decision_engine/benchmarks/divergence_audit.py` | `bdec5399324d48d84a8534ceeb377b9315056737b0da6ddd559444f6c86ba97b` |

Implementation must not change a protected byte. The future clean implementation commit,
implementation-tree hash, and implementation-diff hash are recorded prospectively before
smoke. This design document is committed before implementation; its commit and blob ID are
the source checkpoint identifier and design source commitment.

`implementation_tree_sha256` is raw SHA-256 of the concatenation of canonical JSON rows,
each followed by one LF, for
`{path,git_mode,byte_length,file_sha256}` for `pyproject.toml`, `uv.lock`, every tracked
`.py` path under `research_decision_engine/`, and every tracked `.py` path under `tests/`,
sorted by UTF-8 path bytes. `implementation_diff_sha256` is raw SHA-256 of the same LF-ended
canonical JSONL construction over rows
`{path,status,old_git_mode,new_git_mode,old_byte_length,new_byte_length,old_sha256,
new_sha256}` for the clean implementation commit versus the committed design checkpoint,
sorted by path; unavailable sides are null and status is
`added|modified|deleted|renamed`. A rename path is `old_path->new_path`. The manifest stores
both full digests and the full implementation commit.

## 10. Integrity Audits and Smoke

### 10.1 Audit registry

The 16 audits are literal protocol data:

```text
audit_order|audit_id|requirement
01|A01-SEEDS|full/smoke schedules exact, unique, disjoint, and digest-correct
02|A02-WORLDS|24 literal worlds, candidates, mirrors, costs, budgets, and generator exact
03|A03-TRUTH-ISOLATION|policy-facing types contain no truth, hidden sigma/effect, or evaluator labels
04|A04-ORACLE-ISOLATION|selected-only access; no enumeration; 117,952-key conformance digest exact
05|A05-COMMON-RANDOMNESS|same selected world/seed/candidate gives identical observation across arms/budgets
06|A06-DETERMINISM|replay scientific payloads are byte-identical across worker count and arm order
07|A07-ARM-ISOLATION|lineages, stores, histories, evidence, decisions, and ledgers never cross arms
08|A08-CALIBRATION-SEPARATION|prefix effects do not update beliefs; fixed arms cannot read prefixes
09|A09-PLANNER-AND-EVIDENCE|exact planner replay, selected-candidate and score agreement within 1e-12, matched eligibility, duplicate prevention, truth-free classification order, and no hypothetical persistence
10|A10-COSTS|decision, calibration, required-total, physical-share, and threshold-free cost fields reconcile
11|A11-SOURCE-FREEZE|all protected policy, likelihood, planner, eligibility, and taxonomy hashes match
12|A12-MATRIX|36,864 runs, 18,432 comparisons, 46,080 effects, 92,160 calibration observations complete
13|A13-REGISTRIES|all literal question scientific and statistical hypothesis metric estimand mechanism population count symbol decision symbol predicate budget contrast veto formula gate condition gate audit controller stage branch artifact and enum rows exact with every nonlocal ID resolving once
14|A14-HISTORICAL|historical before/after key universes and digests match
15|A15-RESAMPLING|66 bootstrap and 64 sign-flip streams use sole contrast-ID formulas and sole record_type schema; all seeds preimages rows counts statuses failure codes CIs p-values and HOLM-64 arithmetic are exact
16|A16-FINALIZATION|the provisional in-memory decision follows F-DECISION-TABLE and the literal branch registry; every referenced gate operand and gate_status exists; F-B-AUTHORIZATION applies its dedicated inconclusive-first precedence so any required authorization or veto operand that is INCONCLUSIVE makes B_AUTHORIZED INCONCLUSIVE before P emptiness or another P-derived predicate can be evaluated as FAIL; Branch B is selected only for B_AUTHORIZED PASS; when CONTROLLER_CHANGE_NEEDED is PASS and B_AUTHORIZED is FAIL or INCONCLUSIVE Branch C is selected; G-FINAL final branch trace and recommendation gate_status agree; no unresolved operand is treated as PASS or FAIL
```

No audit can be waived. A scientific result directory exists only when every audit passes.

### 10.2 Smoke stage

Smoke uses the four smoke seeds, all arms and budgets, and exactly:

```text
h_adam_low,h_null_high,w_sgd_medium,g_adam_lmh,
g_null_hml,c_sgd_a,d2_null,d3_adam
```

Smoke verifies implementation invariants only. It cannot report comparative scientific
metrics and cannot alter a world, registry, metric, threshold, seed, budget, or gate. A
smoke defect may be repaired only while all frozen scientific definitions remain unchanged.

## 11. Immutable Finalization

The final directory is exactly `broader-replication-v1-128-seeds/` and must not already
exist. Temporary files and `validation_failure.json` are outside that directory.

Canonical artifacts are never rewritten after finalization:

1. Write temporary data artifacts 1 through 9 and construct gate/audit payloads in memory
   without an A16 row, `G-INTEGRITY`, manifest, or recommendation.
2. Validate every schema, registry, count, FK, uniqueness rule, order, statistic,
   scientific-payload hash, content hash, audit A01 through A15, historical map, and
   cross-reference. Stop immediately if any of A01 through A15 fails.
3. With A01 through A15 passed, compute the provisional A/B/C/D decision entirely in memory
   from all non-integrity gate operands and Section 7 precedence, using provisional integrity
   value `PASS`. This value is local to A16 and is not yet a `G-INTEGRITY` row.
4. Run A16 only against that provisional decision: verify `F-DECISION-TABLE`, existence of
   every referenced gate operand and `gate_status`, and the dedicated
   `F-B-AUTHORIZATION` precedence. Any required authorization or veto operand that is
   `INCONCLUSIVE` must make `B_AUTHORIZED=INCONCLUSIVE` before `P` emptiness or another
   `P`-derived predicate can become `FAIL`; Branch B requires `B_AUTHORIZED=PASS`, while
   `CONTROLLER_CHANGE_NEEDED=PASS` with `B_AUTHORIZED=FAIL` or `INCONCLUSIVE` selects
   Branch C. A16 also verifies equality of the provisional `G-FINAL.gate_status` and
   branch-trace `gate_status`, and that no unresolved operand was treated as `PASS` or
   `FAIL`. A16 never reads or validates a recommendation or manifest.
5. If A16 passes, materialize its audit row, set `G-INTEGRITY=PASS`, recompute the final gate
   row, and require its branch and `gate_status` to equal the provisional decision
   byte-for-byte. This is a
   forward assertion, not iteration. On any audit failure or
   `integrity_abort`, write only a noncanonical sibling `validation_failure.json` with fields
   `schema_version,phase,error_code,path,message,context,details_sha256`; exit nonzero; do
   not create a final manifest or recommendation and do not promote canonical artifacts.
6. On success, finalize temporary gate and audit artifacts 10 and 11 exactly once, validate
   their hashes, atomically promote canonical artifacts 1 through 11, and freeze the
   recommendation scientific payload in memory without its manifest-binding field.
7. Atomically create `run_manifest.json` from the already-frozen artifact and recommendation
   scientific-payload hashes.
8. Atomically create `recommendation.json` last with the already-validated provisional
   decision, matching `gate_status`, and `integrity_status=PASS`; it references the manifest
   content hash.
9. Optionally generate the noncanonical Markdown report after recommendation creation.

A post-finalization mismatch invalidates the entire directory and returns nonzero. It writes
an external diagnostic only; it never changes a canonical artifact, gate, report, manifest,
or recommendation.

No fixed-point iteration is permitted. The dependency order is scientific artifacts,
A01-A15, provisional decision, A16, `G-INTEGRITY`, promotion, manifest, recommendation, and
optional report. No canonical hash depends on a later canonical artifact.

## 12. Runtime and Limitations

The trajectory matrix remains the dominant storage cost. The reduced resampling plan is an
engineering estimate of 45-180 minutes on one contemporary desktop CPU, or 15-60 minutes
with deterministic bounded parallelism. Plan for 5-8 GB of free disk and under 2 GB peak
memory with streamed traces and resampling rows. Smoke must report throughput, but cannot
change the matrix.

This remains a synthetic, three-hypothesis study. The worlds are a fractional stress design,
not a probability sample. Mechanism and sequence analyses are associational. Five
calibration effects may be inadequate under heavy noise. Horizon two cannot characterize
arbitrary delayed information. Eligibility for a PPO pilot is not evidence of real PPO
efficacy.

## Appendix A. Literal Analysis Registries

### A.1 Registry schema

The following three `|`-delimited registries are machine-readable protocol data. There is
no escaping because values contain no `|`. `null` is literal null. Every row contains:

```text
contrast_id|analysis_class|research_question_id|policy_scope|population_scope|metric_id|
estimand_id|paired_unit|eligibility_rule|numerator|denominator|missingness_rule|direction|
ci_method|permutation_method|statistical_hypothesis_id|holm_member|gate_id|decision_use|
source_contrast_id
```

Allowed analysis classes are `confirmatory_holm`, `confirmatory_threshold`,
`decision_operand`, and `descriptive`. Policy scope is `IG` or `LA`. `paired_unit` is always
`seed_block`. Decision-use lists are semicolon-delimited ordered IDs or `null`.

### A.2 Confirmatory registry: 66 rows

```text
contrast_id|analysis_class|research_question_id|policy_scope|population_scope|metric_id|estimand_id|paired_unit|eligibility_rule|numerator|denominator|missingness_rule|direction|ci_method|permutation_method|statistical_hypothesis_id|holm_member|gate_id|decision_use|source_contrast_id
BR-C001|confirmatory_holm|RQ1A_POOLED_BELIEF_QUALITY|IG|POP-PRIMARY-IG|nll|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BQ.IG.NLL|true|G-CAL-IG|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C002|confirmatory_holm|RQ1A_POOLED_BELIEF_QUALITY|IG|POP-PRIMARY-IG|brier|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BQ.IG.BRIER|true|G-CAL-IG|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C003|confirmatory_holm|RQ1A_POOLED_BELIEF_QUALITY|IG|POP-PRIMARY-IG|ece|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-ECE|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BQ.IG.ECE|true|G-CAL-IG|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C004|confirmatory_holm|RQ1A_POOLED_BELIEF_QUALITY|IG|POP-PRIMARY-IG|confidently_wrong|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BQ.IG.CONFIDENTLY_WRONG|true|G-CAL-IG|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C005|confirmatory_holm|RQ1A_POOLED_BELIEF_QUALITY|IG|POP-PRIMARY-IG|true_probability|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|higher|bootstrap_10000|signflip_10000|BQ.IG.TRUE_PROBABILITY|true|G-CAL-IG|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C006|confirmatory_holm|RQ1A_POOLED_BELIEF_QUALITY|LA|POP-PRIMARY-LA|nll|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BQ.LA.NLL|true|G-CAL-LA|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C007|confirmatory_holm|RQ1A_POOLED_BELIEF_QUALITY|LA|POP-PRIMARY-LA|brier|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BQ.LA.BRIER|true|G-CAL-LA|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C008|confirmatory_holm|RQ1A_POOLED_BELIEF_QUALITY|LA|POP-PRIMARY-LA|ece|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-ECE|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BQ.LA.ECE|true|G-CAL-LA|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C009|confirmatory_holm|RQ1A_POOLED_BELIEF_QUALITY|LA|POP-PRIMARY-LA|confidently_wrong|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BQ.LA.CONFIDENTLY_WRONG|true|G-CAL-LA|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C010|confirmatory_holm|RQ1A_POOLED_BELIEF_QUALITY|LA|POP-PRIMARY-LA|true_probability|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|higher|bootstrap_10000|signflip_10000|BQ.LA.TRUE_PROBABILITY|true|G-CAL-LA|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C011|confirmatory_holm|RQ1B_POOLED_CONTROL|IG|POP-PRIMARY-IG|harm_risk|helped_minus_hurt|seed_block|EL-DIVERGENT|NUM-HELP-HURT|DEN-DIVERGENT|MISS-DIVERGENT20|higher|bootstrap_10000|signflip_10000|CB.IG.HELPED_MINUS_HURT|true|G-CTRL-IG|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C012|confirmatory_holm|RQ1B_POOLED_CONTROL|IG|POP-PRIMARY-IG|conditional_brier_efficiency|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|higher|bootstrap_10000|signflip_10000|CB.IG.CONDITIONAL_BRIER_EFFICIENCY|true|G-CTRL-IG|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C013|confirmatory_holm|RQ1B_POOLED_CONTROL|IG|POP-PRIMARY-IG|end_to_end_brier_efficiency|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|higher|bootstrap_10000|signflip_10000|CB.IG.END_TO_END_BRIER_EFFICIENCY|true|G-CTRL-IG|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C014|confirmatory_holm|RQ1B_POOLED_CONTROL|LA|POP-PRIMARY-LA|harm_risk|helped_minus_hurt|seed_block|EL-DIVERGENT|NUM-HELP-HURT|DEN-DIVERGENT|MISS-DIVERGENT20|higher|bootstrap_10000|signflip_10000|CB.LA.HELPED_MINUS_HURT|true|G-CTRL-LA|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C015|confirmatory_holm|RQ1B_POOLED_CONTROL|LA|POP-PRIMARY-LA|conditional_brier_efficiency|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|higher|bootstrap_10000|signflip_10000|CB.LA.CONDITIONAL_BRIER_EFFICIENCY|true|G-CTRL-LA|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C016|confirmatory_holm|RQ1B_POOLED_CONTROL|LA|POP-PRIMARY-LA|end_to_end_brier_efficiency|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|higher|bootstrap_10000|signflip_10000|CB.LA.END_TO_END_BRIER_EFFICIENCY|true|G-CTRL-LA|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C017|confirmatory_holm|RQ2B_CONDITIONAL_HARM|IG|POP-ASYM-IG|harm_risk|conditional_harm_difference|seed_block|EL-DIVERGENT|NUM-HARM-RIGHT-LEFT|DEN-TWO-DIVERGENT-RATES|MISS-TWO-RATES20|positive|bootstrap_10000|signflip_10000|CC.IG.ASYMMETRIC_COST|true|G-RQ2-COST-IG|null|null
BR-C018|confirmatory_holm|RQ2B_CONDITIONAL_HARM|IG|POP-BUDGET-IG|harm_risk|conditional_harm_difference|seed_block|EL-DIVERGENT|NUM-HARM-RIGHT-LEFT|DEN-TWO-DIVERGENT-RATES|MISS-TWO-RATES20|positive|bootstrap_10000|signflip_10000|CC.IG.LARGER_BUDGET|true|G-RQ2-BUDGET-IG|null|null
BR-C019|confirmatory_holm|RQ2B_CONDITIONAL_HARM|LA|POP-ASYM-LA|harm_risk|conditional_harm_difference|seed_block|EL-DIVERGENT|NUM-HARM-RIGHT-LEFT|DEN-TWO-DIVERGENT-RATES|MISS-TWO-RATES20|positive|bootstrap_10000|signflip_10000|CC.LA.ASYMMETRIC_COST|true|G-RQ2-COST-LA|null|null
BR-C020|confirmatory_holm|RQ2B_CONDITIONAL_HARM|LA|POP-BUDGET-LA|harm_risk|conditional_harm_difference|seed_block|EL-DIVERGENT|NUM-HARM-RIGHT-LEFT|DEN-TWO-DIVERGENT-RATES|MISS-TWO-RATES20|positive|bootstrap_10000|signflip_10000|CC.LA.LARGER_BUDGET|true|G-RQ2-BUDGET-LA|null|null
BR-C021|confirmatory_holm|RQ4_ORDER_HARM|IG|POP-SAMESET-IG|harm_risk|sequence_harm_difference|seed_block|EL-SEQUENCE|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-SEQUENCE30|positive|bootstrap_10000|signflip_10000|SA.IG.SAME_SET_DIFFERENT_ORDER|true|G-RQ4-IG|null|null
BR-C022|confirmatory_holm|RQ4_ORDER_HARM|LA|POP-SAMESET-LA|harm_risk|sequence_harm_difference|seed_block|EL-SEQUENCE|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-SEQUENCE30|positive|bootstrap_10000|signflip_10000|SA.LA.SAME_SET_DIFFERENT_ORDER|true|G-RQ4-LA|null|null
BR-C023|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.IG.SCORE_FLATTENING|true|G-ACT-IG-SCORE_FLATTENING|P_RAW;VETOED_TUPLES|null
BR-C024|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.IG.BELIEF_STATE_REORDERING|true|G-ACT-IG-BELIEF_STATE_REORDERING|P_RAW;VETOED_TUPLES|null
BR-C025|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.IG.GROUP_SIGMA_REORDERING|true|G-ACT-IG-GROUP_SIGMA_REORDERING|P_RAW;VETOED_TUPLES|null
BR-C026|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.IG.BELIEF_SIGMA_INTERACTION|true|G-ACT-IG-BELIEF_SIGMA_INTERACTION|P_RAW;VETOED_TUPLES|null
BR-C027|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.IG.COST_TIEBREAK_CHANGE|true|G-ACT-IG-COST_TIEBREAK_CHANGE|P_RAW;VETOED_TUPLES|null
BR-C028|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.IG.PAIR_COMPLETION_DELAY|true|G-ACT-IG-PAIR_COMPLETION_DELAY|P_RAW;VETOED_TUPLES|null
BR-C029|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.IG.PAIR_OPENER_CHANGE|true|G-ACT-IG-PAIR_OPENER_CHANGE|P_RAW;VETOED_TUPLES|null
BR-C030|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.IG.SAME_SET_DIFFERENT_ORDER|true|G-ACT-IG-SAME_SET_DIFFERENT_ORDER|P_RAW;VETOED_TUPLES|null
BR-C031|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.IG.BUDGET_CROWD_OUT|true|G-ACT-IG-BUDGET_CROWD_OUT|P_RAW;VETOED_TUPLES|null
BR-C032|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.IG.CONSERVATIVE_NONCOMMITMENT|true|G-ACT-IG-CONSERVATIVE_NONCOMMITMENT|P_RAW;VETOED_TUPLES|null
BR-C034|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.IG.NO_STABLE_MECHANISM|true|null|null|null
BR-C035|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.LA.SCORE_FLATTENING|true|G-ACT-LA-SCORE_FLATTENING|P_RAW;VETOED_TUPLES|null
BR-C036|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.LA.BELIEF_STATE_REORDERING|true|G-ACT-LA-BELIEF_STATE_REORDERING|P_RAW;VETOED_TUPLES|null
BR-C037|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.LA.GROUP_SIGMA_REORDERING|true|G-ACT-LA-GROUP_SIGMA_REORDERING|P_RAW;VETOED_TUPLES|null
BR-C038|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.LA.BELIEF_SIGMA_INTERACTION|true|G-ACT-LA-BELIEF_SIGMA_INTERACTION|P_RAW;VETOED_TUPLES|null
BR-C039|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.LA.COST_TIEBREAK_CHANGE|true|G-ACT-LA-COST_TIEBREAK_CHANGE|P_RAW;VETOED_TUPLES|null
BR-C040|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.LA.PAIR_COMPLETION_DELAY|true|G-ACT-LA-PAIR_COMPLETION_DELAY|P_RAW;VETOED_TUPLES|null
BR-C041|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.LA.PAIR_OPENER_CHANGE|true|G-ACT-LA-PAIR_OPENER_CHANGE|P_RAW;VETOED_TUPLES|null
BR-C042|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.LA.SAME_SET_DIFFERENT_ORDER|true|G-ACT-LA-SAME_SET_DIFFERENT_ORDER|P_RAW;VETOED_TUPLES|null
BR-C043|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.LA.BUDGET_CROWD_OUT|true|G-ACT-LA-BUDGET_CROWD_OUT|P_RAW;VETOED_TUPLES|null
BR-C044|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.LA.CONSERVATIVE_NONCOMMITMENT|true|G-ACT-LA-CONSERVATIVE_NONCOMMITMENT|P_RAW;VETOED_TUPLES|null
BR-C046|confirmatory_holm|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|mechanism_harm_difference|seed_block|EL-MECHANISM|NUM-HARM-PRESENT-ABSENT|DEN-PRESENT-ABSENT|MISS-MECHANISM20|two_sided|bootstrap_10000|signflip_10000|MS.LA.NO_STABLE_MECHANISM|true|null|null|null
BR-C047|confirmatory_holm|RQ1B_POOLED_CONTROL|IG|POP-BLOCK-IG-HOM|confidently_wrong|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BS.IG.HOMOGENEOUS.CW|true|G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C048|confirmatory_holm|RQ1B_POOLED_CONTROL|IG|POP-BLOCK-IG-HOM|brier|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BS.IG.HOMOGENEOUS.BRIER|true|G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C049|confirmatory_holm|RQ1B_POOLED_CONTROL|IG|POP-BLOCK-IG-WEAK|confidently_wrong|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BS.IG.WEAK_EFFECT.CW|true|G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C050|confirmatory_holm|RQ1B_POOLED_CONTROL|IG|POP-BLOCK-IG-WEAK|brier|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BS.IG.WEAK_EFFECT.BRIER|true|G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C051|confirmatory_holm|RQ1B_POOLED_CONTROL|IG|POP-BLOCK-IG-HET|confidently_wrong|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BS.IG.HETEROGENEOUS.CW|true|G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C052|confirmatory_holm|RQ1B_POOLED_CONTROL|IG|POP-BLOCK-IG-HET|brier|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BS.IG.HETEROGENEOUS.BRIER|true|G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C053|confirmatory_holm|RQ1B_POOLED_CONTROL|IG|POP-BLOCK-IG-COST|confidently_wrong|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BS.IG.ASYMMETRIC_COST.CW|true|G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C054|confirmatory_holm|RQ1B_POOLED_CONTROL|IG|POP-BLOCK-IG-COST|brier|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BS.IG.ASYMMETRIC_COST.BRIER|true|G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C055|confirmatory_holm|RQ1B_POOLED_CONTROL|IG|POP-BLOCK-IG-DELAY|confidently_wrong|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BS.IG.DELAY.CW|true|G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C056|confirmatory_holm|RQ1B_POOLED_CONTROL|IG|POP-BLOCK-IG-DELAY|brier|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BS.IG.DELAY.BRIER|true|G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C057|confirmatory_holm|RQ1B_POOLED_CONTROL|LA|POP-BLOCK-LA-HOM|confidently_wrong|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BS.LA.HOMOGENEOUS.CW|true|G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C058|confirmatory_holm|RQ1B_POOLED_CONTROL|LA|POP-BLOCK-LA-HOM|brier|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BS.LA.HOMOGENEOUS.BRIER|true|G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C059|confirmatory_holm|RQ1B_POOLED_CONTROL|LA|POP-BLOCK-LA-WEAK|confidently_wrong|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BS.LA.WEAK_EFFECT.CW|true|G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C060|confirmatory_holm|RQ1B_POOLED_CONTROL|LA|POP-BLOCK-LA-WEAK|brier|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BS.LA.WEAK_EFFECT.BRIER|true|G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C061|confirmatory_holm|RQ1B_POOLED_CONTROL|LA|POP-BLOCK-LA-HET|confidently_wrong|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BS.LA.HETEROGENEOUS.CW|true|G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C062|confirmatory_holm|RQ1B_POOLED_CONTROL|LA|POP-BLOCK-LA-HET|brier|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BS.LA.HETEROGENEOUS.BRIER|true|G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C063|confirmatory_holm|RQ1B_POOLED_CONTROL|LA|POP-BLOCK-LA-COST|confidently_wrong|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BS.LA.ASYMMETRIC_COST.CW|true|G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C064|confirmatory_holm|RQ1B_POOLED_CONTROL|LA|POP-BLOCK-LA-COST|brier|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BS.LA.ASYMMETRIC_COST.BRIER|true|G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C065|confirmatory_holm|RQ1B_POOLED_CONTROL|LA|POP-BLOCK-LA-DELAY|confidently_wrong|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BS.LA.DELAY.CW|true|G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C066|confirmatory_holm|RQ1B_POOLED_CONTROL|LA|POP-BLOCK-LA-DELAY|brier|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|bootstrap_10000|signflip_10000|BS.LA.DELAY.BRIER|true|G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|null
BR-C067|confirmatory_threshold|RQ3_NUMERICAL_DOMINANCE|IG|POP-PRIMARY-IG|combined_numerical_share|combined_primary_share|seed_block|EL-CLASSIFIABLE|NUM-COMBINED-SHARE|DEN-CLASSIFIABLE|MISS-DOMINANCE30|higher|bootstrap_10000|none|null|false|G-RQ3-IG|null|null
BR-C068|confirmatory_threshold|RQ3_NUMERICAL_DOMINANCE|LA|POP-PRIMARY-LA|combined_numerical_share|combined_primary_share|seed_block|EL-CLASSIFIABLE|NUM-COMBINED-SHARE|DEN-CLASSIFIABLE|MISS-DOMINANCE30|higher|bootstrap_10000|none|null|false|G-RQ3-LA|null|null
```

### A.3 Decision registry: 20 rows

Each row reuses the estimate, interval, and Holm result from `source_contrast_id`; it does
not launch another resample.

```text
contrast_id|analysis_class|research_question_id|policy_scope|population_scope|metric_id|estimand_id|paired_unit|eligibility_rule|numerator|denominator|missingness_rule|direction|ci_method|permutation_method|statistical_hypothesis_id|holm_member|gate_id|decision_use|source_contrast_id
BR-J001|decision_operand|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|actionability_composite|seed_block|EL-ACTIONABILITY|NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|two_sided|reuse_source|reuse_source|null|false|G-ACT-IG-SCORE_FLATTENING|P_RAW;ACTIONABILITY_COMPLETE|BR-C023
BR-J002|decision_operand|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|actionability_composite|seed_block|EL-ACTIONABILITY|NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|two_sided|reuse_source|reuse_source|null|false|G-ACT-IG-BELIEF_STATE_REORDERING|P_RAW;ACTIONABILITY_COMPLETE|BR-C024
BR-J003|decision_operand|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|actionability_composite|seed_block|EL-ACTIONABILITY|NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|two_sided|reuse_source|reuse_source|null|false|G-ACT-IG-GROUP_SIGMA_REORDERING|P_RAW;ACTIONABILITY_COMPLETE|BR-C025
BR-J004|decision_operand|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|actionability_composite|seed_block|EL-ACTIONABILITY|NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|two_sided|reuse_source|reuse_source|null|false|G-ACT-IG-BELIEF_SIGMA_INTERACTION|P_RAW;ACTIONABILITY_COMPLETE|BR-C026
BR-J005|decision_operand|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|actionability_composite|seed_block|EL-ACTIONABILITY|NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|two_sided|reuse_source|reuse_source|null|false|G-ACT-IG-COST_TIEBREAK_CHANGE|P_RAW;ACTIONABILITY_COMPLETE|BR-C027
BR-J006|decision_operand|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|actionability_composite|seed_block|EL-ACTIONABILITY|NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|two_sided|reuse_source|reuse_source|null|false|G-ACT-IG-PAIR_COMPLETION_DELAY|P_RAW;ACTIONABILITY_COMPLETE|BR-C028
BR-J007|decision_operand|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|actionability_composite|seed_block|EL-ACTIONABILITY|NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|two_sided|reuse_source|reuse_source|null|false|G-ACT-IG-PAIR_OPENER_CHANGE|P_RAW;ACTIONABILITY_COMPLETE|BR-C029
BR-J008|decision_operand|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|actionability_composite|seed_block|EL-ACTIONABILITY|NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|two_sided|reuse_source|reuse_source|null|false|G-ACT-IG-SAME_SET_DIFFERENT_ORDER|P_RAW;ACTIONABILITY_COMPLETE|BR-C030
BR-J009|decision_operand|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|actionability_composite|seed_block|EL-ACTIONABILITY|NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|two_sided|reuse_source|reuse_source|null|false|G-ACT-IG-BUDGET_CROWD_OUT|P_RAW;ACTIONABILITY_COMPLETE|BR-C031
BR-J010|decision_operand|RQ5_ACTIONABLE_SEPARATOR|IG|POP-PRIMARY-IG|harm_risk|actionability_composite|seed_block|EL-ACTIONABILITY|NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|two_sided|reuse_source|reuse_source|null|false|G-ACT-IG-CONSERVATIVE_NONCOMMITMENT|P_RAW;ACTIONABILITY_COMPLETE|BR-C032
BR-J011|decision_operand|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|actionability_composite|seed_block|EL-ACTIONABILITY|NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|two_sided|reuse_source|reuse_source|null|false|G-ACT-LA-SCORE_FLATTENING|P_RAW;ACTIONABILITY_COMPLETE|BR-C035
BR-J012|decision_operand|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|actionability_composite|seed_block|EL-ACTIONABILITY|NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|two_sided|reuse_source|reuse_source|null|false|G-ACT-LA-BELIEF_STATE_REORDERING|P_RAW;ACTIONABILITY_COMPLETE|BR-C036
BR-J013|decision_operand|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|actionability_composite|seed_block|EL-ACTIONABILITY|NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|two_sided|reuse_source|reuse_source|null|false|G-ACT-LA-GROUP_SIGMA_REORDERING|P_RAW;ACTIONABILITY_COMPLETE|BR-C037
BR-J014|decision_operand|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|actionability_composite|seed_block|EL-ACTIONABILITY|NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|two_sided|reuse_source|reuse_source|null|false|G-ACT-LA-BELIEF_SIGMA_INTERACTION|P_RAW;ACTIONABILITY_COMPLETE|BR-C038
BR-J015|decision_operand|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|actionability_composite|seed_block|EL-ACTIONABILITY|NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|two_sided|reuse_source|reuse_source|null|false|G-ACT-LA-COST_TIEBREAK_CHANGE|P_RAW;ACTIONABILITY_COMPLETE|BR-C039
BR-J016|decision_operand|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|actionability_composite|seed_block|EL-ACTIONABILITY|NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|two_sided|reuse_source|reuse_source|null|false|G-ACT-LA-PAIR_COMPLETION_DELAY|P_RAW;ACTIONABILITY_COMPLETE|BR-C040
BR-J017|decision_operand|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|actionability_composite|seed_block|EL-ACTIONABILITY|NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|two_sided|reuse_source|reuse_source|null|false|G-ACT-LA-PAIR_OPENER_CHANGE|P_RAW;ACTIONABILITY_COMPLETE|BR-C041
BR-J018|decision_operand|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|actionability_composite|seed_block|EL-ACTIONABILITY|NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|two_sided|reuse_source|reuse_source|null|false|G-ACT-LA-SAME_SET_DIFFERENT_ORDER|P_RAW;ACTIONABILITY_COMPLETE|BR-C042
BR-J019|decision_operand|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|actionability_composite|seed_block|EL-ACTIONABILITY|NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|two_sided|reuse_source|reuse_source|null|false|G-ACT-LA-BUDGET_CROWD_OUT|P_RAW;ACTIONABILITY_COMPLETE|BR-C043
BR-J020|decision_operand|RQ5_ACTIONABLE_SEPARATOR|LA|POP-PRIMARY-LA|harm_risk|actionability_composite|seed_block|EL-ACTIONABILITY|NUM-ACTIONABILITY|DEN-PRESENT-ABSENT|MISS-ACTION25|two_sided|reuse_source|reuse_source|null|false|G-ACT-LA-CONSERVATIVE_NONCOMMITMENT|P_RAW;ACTIONABILITY_COMPLETE|BR-C044
```

### A.4 Veto registry: 20 rows

```text
veto_id|formula_id|decision_contrast_id|policy_scope|mechanism_id|population_scope|own_confirmatory_contrast_id|required_veto_contrast_id|support_rule|effect_threshold|ci_rule|holm_rule
V001|F-VETO|BR-J001|IG|SCORE_FLATTENING|POP-PRIMARY-IG|BR-C023|BR-C035|present>=25;absent>=25|abs(effect)>=0.15 and opposite sign|interval wholly opposite zero|p_adjusted<0.05
V002|F-VETO|BR-J002|IG|BELIEF_STATE_REORDERING|POP-PRIMARY-IG|BR-C024|BR-C036|present>=25;absent>=25|abs(effect)>=0.15 and opposite sign|interval wholly opposite zero|p_adjusted<0.05
V003|F-VETO|BR-J003|IG|GROUP_SIGMA_REORDERING|POP-PRIMARY-IG|BR-C025|BR-C037|present>=25;absent>=25|abs(effect)>=0.15 and opposite sign|interval wholly opposite zero|p_adjusted<0.05
V004|F-VETO|BR-J004|IG|BELIEF_SIGMA_INTERACTION|POP-PRIMARY-IG|BR-C026|BR-C038|present>=25;absent>=25|abs(effect)>=0.15 and opposite sign|interval wholly opposite zero|p_adjusted<0.05
V005|F-VETO|BR-J005|IG|COST_TIEBREAK_CHANGE|POP-PRIMARY-IG|BR-C027|BR-C039|present>=25;absent>=25|abs(effect)>=0.15 and opposite sign|interval wholly opposite zero|p_adjusted<0.05
V006|F-VETO|BR-J006|IG|PAIR_COMPLETION_DELAY|POP-PRIMARY-IG|BR-C028|BR-C040|present>=25;absent>=25|abs(effect)>=0.15 and opposite sign|interval wholly opposite zero|p_adjusted<0.05
V007|F-VETO|BR-J007|IG|PAIR_OPENER_CHANGE|POP-PRIMARY-IG|BR-C029|BR-C041|present>=25;absent>=25|abs(effect)>=0.15 and opposite sign|interval wholly opposite zero|p_adjusted<0.05
V008|F-VETO|BR-J008|IG|SAME_SET_DIFFERENT_ORDER|POP-PRIMARY-IG|BR-C030|BR-C042|present>=25;absent>=25|abs(effect)>=0.15 and opposite sign|interval wholly opposite zero|p_adjusted<0.05
V009|F-VETO|BR-J009|IG|BUDGET_CROWD_OUT|POP-PRIMARY-IG|BR-C031|BR-C043|present>=25;absent>=25|abs(effect)>=0.15 and opposite sign|interval wholly opposite zero|p_adjusted<0.05
V010|F-VETO|BR-J010|IG|CONSERVATIVE_NONCOMMITMENT|POP-PRIMARY-IG|BR-C032|BR-C044|present>=25;absent>=25|abs(effect)>=0.15 and opposite sign|interval wholly opposite zero|p_adjusted<0.05
V011|F-VETO|BR-J011|LA|SCORE_FLATTENING|POP-PRIMARY-LA|BR-C035|BR-C023|present>=25;absent>=25|abs(effect)>=0.15 and opposite sign|interval wholly opposite zero|p_adjusted<0.05
V012|F-VETO|BR-J012|LA|BELIEF_STATE_REORDERING|POP-PRIMARY-LA|BR-C036|BR-C024|present>=25;absent>=25|abs(effect)>=0.15 and opposite sign|interval wholly opposite zero|p_adjusted<0.05
V013|F-VETO|BR-J013|LA|GROUP_SIGMA_REORDERING|POP-PRIMARY-LA|BR-C037|BR-C025|present>=25;absent>=25|abs(effect)>=0.15 and opposite sign|interval wholly opposite zero|p_adjusted<0.05
V014|F-VETO|BR-J014|LA|BELIEF_SIGMA_INTERACTION|POP-PRIMARY-LA|BR-C038|BR-C026|present>=25;absent>=25|abs(effect)>=0.15 and opposite sign|interval wholly opposite zero|p_adjusted<0.05
V015|F-VETO|BR-J015|LA|COST_TIEBREAK_CHANGE|POP-PRIMARY-LA|BR-C039|BR-C027|present>=25;absent>=25|abs(effect)>=0.15 and opposite sign|interval wholly opposite zero|p_adjusted<0.05
V016|F-VETO|BR-J016|LA|PAIR_COMPLETION_DELAY|POP-PRIMARY-LA|BR-C040|BR-C028|present>=25;absent>=25|abs(effect)>=0.15 and opposite sign|interval wholly opposite zero|p_adjusted<0.05
V017|F-VETO|BR-J017|LA|PAIR_OPENER_CHANGE|POP-PRIMARY-LA|BR-C041|BR-C029|present>=25;absent>=25|abs(effect)>=0.15 and opposite sign|interval wholly opposite zero|p_adjusted<0.05
V018|F-VETO|BR-J018|LA|SAME_SET_DIFFERENT_ORDER|POP-PRIMARY-LA|BR-C042|BR-C030|present>=25;absent>=25|abs(effect)>=0.15 and opposite sign|interval wholly opposite zero|p_adjusted<0.05
V019|F-VETO|BR-J019|LA|BUDGET_CROWD_OUT|POP-PRIMARY-LA|BR-C043|BR-C031|present>=25;absent>=25|abs(effect)>=0.15 and opposite sign|interval wholly opposite zero|p_adjusted<0.05
V020|F-VETO|BR-J020|LA|CONSERVATIVE_NONCOMMITMENT|POP-PRIMARY-LA|BR-C044|BR-C032|present>=25;absent>=25|abs(effect)>=0.15 and opposite sign|interval wholly opposite zero|p_adjusted<0.05
```

### A.5 Descriptive registry: 36 rows

All rows use `ci_method=none`, `permutation_method=none`, `holm_member=false`,
`gate_id=null`, and `decision_use=null`.

```text
contrast_id|analysis_class|research_question_id|policy_scope|population_scope|metric_id|estimand_id|paired_unit|eligibility_rule|numerator|denominator|missingness_rule|direction|ci_method|permutation_method|statistical_hypothesis_id|holm_member|gate_id|decision_use|source_contrast_id
BR-D001|descriptive|RQ1C_NOISE_STRATA|IG|POP-HIGH-IG|nll|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D002|descriptive|RQ1C_NOISE_STRATA|IG|POP-HIGH-IG|brier|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D003|descriptive|RQ1C_NOISE_STRATA|IG|POP-HIGH-IG|ece|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-ECE|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D004|descriptive|RQ1C_NOISE_STRATA|IG|POP-HIGH-IG|confidently_wrong|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D005|descriptive|RQ1C_NOISE_STRATA|IG|POP-HIGH-IG|true_probability|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|higher|none|none|null|false|null|null|null
BR-D006|descriptive|RQ1C_NOISE_STRATA|LA|POP-HIGH-LA|nll|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D007|descriptive|RQ1C_NOISE_STRATA|LA|POP-HIGH-LA|brier|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D008|descriptive|RQ1C_NOISE_STRATA|LA|POP-HIGH-LA|ece|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-ECE|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D009|descriptive|RQ1C_NOISE_STRATA|LA|POP-HIGH-LA|confidently_wrong|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D010|descriptive|RQ1C_NOISE_STRATA|LA|POP-HIGH-LA|true_probability|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|higher|none|none|null|false|null|null|null
BR-D011|descriptive|RQ1C_NOISE_STRATA|IG|POP-HET-IG|nll|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D012|descriptive|RQ1C_NOISE_STRATA|IG|POP-HET-IG|brier|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D013|descriptive|RQ1C_NOISE_STRATA|IG|POP-HET-IG|ece|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-ECE|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D014|descriptive|RQ1C_NOISE_STRATA|IG|POP-HET-IG|confidently_wrong|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D015|descriptive|RQ1C_NOISE_STRATA|IG|POP-HET-IG|true_probability|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|higher|none|none|null|false|null|null|null
BR-D016|descriptive|RQ1C_NOISE_STRATA|LA|POP-HET-LA|nll|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D017|descriptive|RQ1C_NOISE_STRATA|LA|POP-HET-LA|brier|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D018|descriptive|RQ1C_NOISE_STRATA|LA|POP-HET-LA|ece|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-ECE|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D019|descriptive|RQ1C_NOISE_STRATA|LA|POP-HET-LA|confidently_wrong|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D020|descriptive|RQ1C_NOISE_STRATA|LA|POP-HET-LA|true_probability|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|higher|none|none|null|false|null|null|null
BR-D021|descriptive|RQ2A_DIVERGENCE_FREQUENCY|IG|POP-ASYM-IG|first_action_divergence|divergence_rate_difference|seed_block|EL-PAIRED|NUM-DIVERGENCE-RD|DEN-ALL-PAIRS|MISS-PAIR20|none|none|none|null|false|null|null|null
BR-D022|descriptive|RQ2A_DIVERGENCE_FREQUENCY|IG|POP-ASYM-IG|any_divergence|divergence_rate_difference|seed_block|EL-PAIRED|NUM-DIVERGENCE-RD|DEN-ALL-PAIRS|MISS-PAIR20|none|none|none|null|false|null|null|null
BR-D023|descriptive|RQ2A_DIVERGENCE_FREQUENCY|LA|POP-ASYM-LA|first_action_divergence|divergence_rate_difference|seed_block|EL-PAIRED|NUM-DIVERGENCE-RD|DEN-ALL-PAIRS|MISS-PAIR20|none|none|none|null|false|null|null|null
BR-D024|descriptive|RQ2A_DIVERGENCE_FREQUENCY|LA|POP-ASYM-LA|any_divergence|divergence_rate_difference|seed_block|EL-PAIRED|NUM-DIVERGENCE-RD|DEN-ALL-PAIRS|MISS-PAIR20|none|none|none|null|false|null|null|null
BR-D025|descriptive|RQ2A_DIVERGENCE_FREQUENCY|IG|POP-BUDGET-IG|first_action_divergence|divergence_rate_difference|seed_block|EL-PAIRED|NUM-DIVERGENCE-RD|DEN-ALL-PAIRS|MISS-PAIR20|none|none|none|null|false|null|null|null
BR-D026|descriptive|RQ2A_DIVERGENCE_FREQUENCY|IG|POP-BUDGET-IG|any_divergence|divergence_rate_difference|seed_block|EL-PAIRED|NUM-DIVERGENCE-RD|DEN-ALL-PAIRS|MISS-PAIR20|none|none|none|null|false|null|null|null
BR-D027|descriptive|RQ2A_DIVERGENCE_FREQUENCY|LA|POP-BUDGET-LA|first_action_divergence|divergence_rate_difference|seed_block|EL-PAIRED|NUM-DIVERGENCE-RD|DEN-ALL-PAIRS|MISS-PAIR20|none|none|none|null|false|null|null|null
BR-D028|descriptive|RQ2A_DIVERGENCE_FREQUENCY|LA|POP-BUDGET-LA|any_divergence|divergence_rate_difference|seed_block|EL-PAIRED|NUM-DIVERGENCE-RD|DEN-ALL-PAIRS|MISS-PAIR20|none|none|none|null|false|null|null|null
BR-D029|descriptive|REPORT_COSTS|IG|POP-PRIMARY-IG|decision_cost|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D030|descriptive|REPORT_COSTS|IG|POP-PRIMARY-IG|calibration_cost|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D031|descriptive|REPORT_COSTS|IG|POP-PRIMARY-IG|required_total_cost|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D032|descriptive|REPORT_COSTS|LA|POP-PRIMARY-LA|decision_cost|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D033|descriptive|REPORT_COSTS|LA|POP-PRIMARY-LA|calibration_cost|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D034|descriptive|REPORT_COSTS|LA|POP-PRIMARY-LA|required_total_cost|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|lower|none|none|null|false|null|null|null
BR-D035|descriptive|REPORT_OBJECTIVE|IG|POP-PRIMARY-IG|best_observed_objective|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|higher|none|none|null|false|null|null|null
BR-D036|descriptive|REPORT_OBJECTIVE|LA|POP-PRIMARY-LA|best_observed_objective|calibrated_minus_fixed|seed_block|EL-PAIRED|NUM-CMF|DEN-PAIRED|MISS-PAIR20|higher|none|none|null|false|null|null|null
```

### A.6 Literal supporting registries

The constants map in `protocol_snapshot.json` contains exactly:

```text
protocol_version=broader-closed-loop-replication/v1
output_directory=broader-replication-v1-128-seeds/
full_seed_first=1000
full_seed_last=1127
full_seed_count=128
smoke_seed_count=4
world_count=24
budget_count=3
arm_count=4
arm_run_count=36864
comparison_count=18432
calibration_effect_count=46080
calibration_observation_count=92160
fixed_sigma=0.05
sigma_floor=0.05
calibration_effects_per_group=5
planning_horizon=2
confidence_threshold=0.80
numeric_tolerance=1e-12
scoring_epsilon=1e-15
minimum_complete_pairs=20
actionability_present_minimum=25
actionability_absent_minimum=25
eligible_block_divergent_minimum=20
eligible_block_present_minimum=5
eligible_block_absent_minimum=5
eligible_block_count_minimum=4
sequence_side_minimum=30
dominance_classifiable_minimum=30
dominance_point_threshold=0.70
dominance_lower_ci_threshold=0.60
dominance_individual_share_minimum=0.10
concentration_effect_threshold=0.10
actionability_effect_threshold=0.15
bootstrap_replicates=10000
minimum_usable_bootstrap_replicates=9500
sign_flip_replicates=10000
holm_family_size=64
holm_alpha=0.05
confirmatory_contrast_count=66
decision_contrast_count=20
descriptive_contrast_count=36
total_contrast_count=122
canonical_artifact_count=13
audit_count=16
count_symbol_registry_count=9
decision_symbol_registry_count=9
formula_registry_count=43
gate_condition_registry_count=66
gate_registry_count=44
predicate_registry_count=7
branch_registry_count=4
controller_stage_registry_count=6
budget_registry_count=3
enum_registry_count=33
holm_formula_id=HOLM-64
oracle_domain_count=117952
oracle_domain_expected_sha256=0452652278d2670ac11f923a6919cae923b2baf88d2ea9b0356a5d4923dc706c
```

ECE bin edges are the separate ordered constant list
`[0.0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0]`. Full seeds, smoke seeds, budgets,
arms, mechanisms, and worlds are stored in their ordered registries rather than duplicated
inside the scalar constants map.

Scientific hypotheses are the following literal ordered registry:

```text
hypothesis_order|scientific_hypothesis_id|statement
1|optimizer.adam-advantage|Adam has a positive matched optimizer effect
2|optimizer.no-consistent-advantage|The matched optimizer effect is centered at zero
3|optimizer.sgd-advantage|SGD has a positive matched optimizer effect
```

Statistical hypotheses are the following literal ordered records. Their explicit contrast
IDs are authoritative; missing historical IDs are never inferred or renumbered:

```json
[{"order":1,"statistical_hypothesis_id":"BQ.IG.NLL","contrast_id":"BR-C001"},{"order":2,"statistical_hypothesis_id":"BQ.IG.BRIER","contrast_id":"BR-C002"},{"order":3,"statistical_hypothesis_id":"BQ.IG.ECE","contrast_id":"BR-C003"},{"order":4,"statistical_hypothesis_id":"BQ.IG.CONFIDENTLY_WRONG","contrast_id":"BR-C004"},{"order":5,"statistical_hypothesis_id":"BQ.IG.TRUE_PROBABILITY","contrast_id":"BR-C005"},{"order":6,"statistical_hypothesis_id":"BQ.LA.NLL","contrast_id":"BR-C006"},{"order":7,"statistical_hypothesis_id":"BQ.LA.BRIER","contrast_id":"BR-C007"},{"order":8,"statistical_hypothesis_id":"BQ.LA.ECE","contrast_id":"BR-C008"},{"order":9,"statistical_hypothesis_id":"BQ.LA.CONFIDENTLY_WRONG","contrast_id":"BR-C009"},{"order":10,"statistical_hypothesis_id":"BQ.LA.TRUE_PROBABILITY","contrast_id":"BR-C010"},{"order":11,"statistical_hypothesis_id":"CB.IG.HELPED_MINUS_HURT","contrast_id":"BR-C011"},{"order":12,"statistical_hypothesis_id":"CB.IG.CONDITIONAL_BRIER_EFFICIENCY","contrast_id":"BR-C012"},{"order":13,"statistical_hypothesis_id":"CB.IG.END_TO_END_BRIER_EFFICIENCY","contrast_id":"BR-C013"},{"order":14,"statistical_hypothesis_id":"CB.LA.HELPED_MINUS_HURT","contrast_id":"BR-C014"},{"order":15,"statistical_hypothesis_id":"CB.LA.CONDITIONAL_BRIER_EFFICIENCY","contrast_id":"BR-C015"},{"order":16,"statistical_hypothesis_id":"CB.LA.END_TO_END_BRIER_EFFICIENCY","contrast_id":"BR-C016"},{"order":17,"statistical_hypothesis_id":"CC.IG.ASYMMETRIC_COST","contrast_id":"BR-C017"},{"order":18,"statistical_hypothesis_id":"CC.IG.LARGER_BUDGET","contrast_id":"BR-C018"},{"order":19,"statistical_hypothesis_id":"CC.LA.ASYMMETRIC_COST","contrast_id":"BR-C019"},{"order":20,"statistical_hypothesis_id":"CC.LA.LARGER_BUDGET","contrast_id":"BR-C020"},{"order":21,"statistical_hypothesis_id":"SA.IG.SAME_SET_DIFFERENT_ORDER","contrast_id":"BR-C021"},{"order":22,"statistical_hypothesis_id":"SA.LA.SAME_SET_DIFFERENT_ORDER","contrast_id":"BR-C022"},{"order":23,"statistical_hypothesis_id":"MS.IG.SCORE_FLATTENING","contrast_id":"BR-C023"},{"order":24,"statistical_hypothesis_id":"MS.IG.BELIEF_STATE_REORDERING","contrast_id":"BR-C024"},{"order":25,"statistical_hypothesis_id":"MS.IG.GROUP_SIGMA_REORDERING","contrast_id":"BR-C025"},{"order":26,"statistical_hypothesis_id":"MS.IG.BELIEF_SIGMA_INTERACTION","contrast_id":"BR-C026"},{"order":27,"statistical_hypothesis_id":"MS.IG.COST_TIEBREAK_CHANGE","contrast_id":"BR-C027"},{"order":28,"statistical_hypothesis_id":"MS.IG.PAIR_COMPLETION_DELAY","contrast_id":"BR-C028"},{"order":29,"statistical_hypothesis_id":"MS.IG.PAIR_OPENER_CHANGE","contrast_id":"BR-C029"},{"order":30,"statistical_hypothesis_id":"MS.IG.SAME_SET_DIFFERENT_ORDER","contrast_id":"BR-C030"},{"order":31,"statistical_hypothesis_id":"MS.IG.BUDGET_CROWD_OUT","contrast_id":"BR-C031"},{"order":32,"statistical_hypothesis_id":"MS.IG.CONSERVATIVE_NONCOMMITMENT","contrast_id":"BR-C032"},{"order":33,"statistical_hypothesis_id":"MS.IG.NO_STABLE_MECHANISM","contrast_id":"BR-C034"},{"order":34,"statistical_hypothesis_id":"MS.LA.SCORE_FLATTENING","contrast_id":"BR-C035"},{"order":35,"statistical_hypothesis_id":"MS.LA.BELIEF_STATE_REORDERING","contrast_id":"BR-C036"},{"order":36,"statistical_hypothesis_id":"MS.LA.GROUP_SIGMA_REORDERING","contrast_id":"BR-C037"},{"order":37,"statistical_hypothesis_id":"MS.LA.BELIEF_SIGMA_INTERACTION","contrast_id":"BR-C038"},{"order":38,"statistical_hypothesis_id":"MS.LA.COST_TIEBREAK_CHANGE","contrast_id":"BR-C039"},{"order":39,"statistical_hypothesis_id":"MS.LA.PAIR_COMPLETION_DELAY","contrast_id":"BR-C040"},{"order":40,"statistical_hypothesis_id":"MS.LA.PAIR_OPENER_CHANGE","contrast_id":"BR-C041"},{"order":41,"statistical_hypothesis_id":"MS.LA.SAME_SET_DIFFERENT_ORDER","contrast_id":"BR-C042"},{"order":42,"statistical_hypothesis_id":"MS.LA.BUDGET_CROWD_OUT","contrast_id":"BR-C043"},{"order":43,"statistical_hypothesis_id":"MS.LA.CONSERVATIVE_NONCOMMITMENT","contrast_id":"BR-C044"},{"order":44,"statistical_hypothesis_id":"MS.LA.NO_STABLE_MECHANISM","contrast_id":"BR-C046"},{"order":45,"statistical_hypothesis_id":"BS.IG.HOMOGENEOUS.CW","contrast_id":"BR-C047"},{"order":46,"statistical_hypothesis_id":"BS.IG.HOMOGENEOUS.BRIER","contrast_id":"BR-C048"},{"order":47,"statistical_hypothesis_id":"BS.IG.WEAK_EFFECT.CW","contrast_id":"BR-C049"},{"order":48,"statistical_hypothesis_id":"BS.IG.WEAK_EFFECT.BRIER","contrast_id":"BR-C050"},{"order":49,"statistical_hypothesis_id":"BS.IG.HETEROGENEOUS.CW","contrast_id":"BR-C051"},{"order":50,"statistical_hypothesis_id":"BS.IG.HETEROGENEOUS.BRIER","contrast_id":"BR-C052"},{"order":51,"statistical_hypothesis_id":"BS.IG.ASYMMETRIC_COST.CW","contrast_id":"BR-C053"},{"order":52,"statistical_hypothesis_id":"BS.IG.ASYMMETRIC_COST.BRIER","contrast_id":"BR-C054"},{"order":53,"statistical_hypothesis_id":"BS.IG.DELAY.CW","contrast_id":"BR-C055"},{"order":54,"statistical_hypothesis_id":"BS.IG.DELAY.BRIER","contrast_id":"BR-C056"},{"order":55,"statistical_hypothesis_id":"BS.LA.HOMOGENEOUS.CW","contrast_id":"BR-C057"},{"order":56,"statistical_hypothesis_id":"BS.LA.HOMOGENEOUS.BRIER","contrast_id":"BR-C058"},{"order":57,"statistical_hypothesis_id":"BS.LA.WEAK_EFFECT.CW","contrast_id":"BR-C059"},{"order":58,"statistical_hypothesis_id":"BS.LA.WEAK_EFFECT.BRIER","contrast_id":"BR-C060"},{"order":59,"statistical_hypothesis_id":"BS.LA.HETEROGENEOUS.CW","contrast_id":"BR-C061"},{"order":60,"statistical_hypothesis_id":"BS.LA.HETEROGENEOUS.BRIER","contrast_id":"BR-C062"},{"order":61,"statistical_hypothesis_id":"BS.LA.ASYMMETRIC_COST.CW","contrast_id":"BR-C063"},{"order":62,"statistical_hypothesis_id":"BS.LA.ASYMMETRIC_COST.BRIER","contrast_id":"BR-C064"},{"order":63,"statistical_hypothesis_id":"BS.LA.DELAY.CW","contrast_id":"BR-C065"},{"order":64,"statistical_hypothesis_id":"BS.LA.DELAY.BRIER","contrast_id":"BR-C066"}]
```

Every statistical hypothesis occurs once in A.2 and nowhere else. The literal metric
registry is:

```text
metric_order|metric_id|definition|direction
1|true_probability|final posterior probability assigned to evaluator-only truth|higher
2|confidently_wrong|one iff top probability is at least 0.80 and stable top ID is not truth|lower
3|nll|negative natural log of max true_probability and 1e-15|lower
4|brier|sum over hypotheses of squared probability minus truth indicator|lower
5|ece|weighted ten-bin top-label expected calibration error|lower
6|posterior_entropy|negative sum p times log2 p with zero term zero|lower
7|conditional_brier_efficiency|two-thirds minus brier divided by decision_cost|higher
8|end_to_end_brier_efficiency|two-thirds minus brier divided by required_total_cost|higher
9|decision_cost|chronological sum of real decision and setup costs|lower
10|calibration_cost|zero for fixed and deployed prefix cost for calibrated|lower
11|required_total_cost|decision_cost plus calibration_cost|lower
12|best_observed_objective|maximum selected non-setup objective or null|higher
13|first_action_divergence|one iff paired sequences differ at action one|lower
14|any_divergence|one iff paired ordered sequences differ anywhere|lower
15|harm_risk|weighted hurt indicator among divergent comparisons|lower
16|combined_numerical_share|primary SCORE_FLATTENING or GROUP_SIGMA_REORDERING share|higher
```

The literal estimand registry is:

```text
estimand_order|estimand_id|definition
1|calibrated_minus_fixed|weighted calibrated value minus weighted fixed value
2|helped_minus_hurt|NUM-HELP-HURT
3|conditional_harm_difference|target divergent harm rate minus comparator divergent harm rate
4|mechanism_harm_difference|primary-mechanism-present harm rate minus absent harm rate
5|sequence_harm_difference|same-set-different-order harm rate minus other-divergence harm rate
6|combined_primary_share|share of classifiable divergences with primary SF or GSR label
7|divergence_rate_difference|target divergence rate minus comparator divergence rate
8|actionability_composite|pooled mechanism effect plus support stability CI and Holm predicates
```

The literal mechanism registry is:

```text
mechanism_order|mechanism_id|actionable
1|SCORE_FLATTENING|true
2|BELIEF_STATE_REORDERING|true
3|GROUP_SIGMA_REORDERING|true
4|BELIEF_SIGMA_INTERACTION|true
5|COST_TIEBREAK_CHANGE|true
6|PAIR_COMPLETION_DELAY|true
7|PAIR_OPENER_CHANGE|true
8|SAME_SET_DIFFERENT_ORDER|true
9|BUDGET_CROWD_OUT|true
10|CONSERVATIVE_NONCOMMITMENT|true
11|NO_STABLE_MECHANISM|false
```

The literal count-symbol registry has nine rows:

```text
symbol_order|symbol_id|value_type|definition
1|COUNT-ARM-RUNS|I64|canonical arm_runs row count equals 36864
2|COUNT-COMPARISONS|I64|canonical comparisons row count equals 18432
3|COUNT-SIGMA-ROWS|I64|canonical calibration_estimates row count equals 9216
4|COUNT-CONTRAST-ROWS|I64|canonical contrast_results row count equals 122
5|FK-ALL|BOOL|every required foreign key alternate key schema invariant and positive required pooled denominator validates
6|COUNT-PRIMARY-SF-IG|F64|literal POP-PRIMARY-IG weighted sum of classifiable divergences with primary SCORE_FLATTENING
7|COUNT-PRIMARY-GSR-IG|F64|literal POP-PRIMARY-IG weighted sum of classifiable divergences with primary GROUP_SIGMA_REORDERING
8|COUNT-PRIMARY-SF-LA|F64|literal POP-PRIMARY-LA weighted sum of classifiable divergences with primary SCORE_FLATTENING
9|COUNT-PRIMARY-GSR-LA|F64|literal POP-PRIMARY-LA weighted sum of classifiable divergences with primary GROUP_SIGMA_REORDERING
```

The literal decision-symbol registry has nine rows:

```text
symbol_order|symbol_id|value_type|producer_formula_id
1|ACTIONABILITY_COMPLETE|DecisionBoolean|F-ACTION-COMPLETE
2|P_RAW|LIST<ActionTuple>|F-ACTION-COMPLETE
3|VETOED_TUPLES|LIST<ActionTuple>|F-P
4|VETO_COMPLETE|DecisionBoolean|F-VETO-COMPLETE
5|P|LIST<ActionTuple>|F-P
6|UNIQUE_ACTIONABLE_MECHANISM|DecisionBoolean|F-UNIQUE-MECHANISM
7|CONTROLLER_CHANGE_NEEDED|DecisionBoolean|F-CONTROLLER-CHANGE
8|PPO_ELIGIBLE|DecisionBoolean|F-PPO
9|B_AUTHORIZED|DecisionBoolean|F-B-AUTHORIZATION
```

The literal predicate registry has seven rows:

```text
predicate_order|predicate_id|exact predicate
1|SIGN-SAME-NONZERO|required estimate has pooled estimate nonzero sign
2|SIGN-OPPOSITE-ABS-010|required estimate has opposite sign and absolute value at least 0.10
3|EFFECT-ABS-015|absolute pooled estimate is at least 0.15
4|CI-EXCLUDES-ZERO|95 percent interval is wholly below or wholly above zero
5|HOLM-LT-005|Holm-adjusted p is strictly below 0.05
6|SUPPORT-ACTION-BLOCK|n_divergent at least 20 and n_present and n_absent at least 5
7|SUPPORT-ACTION-POOLED|n_present and n_absent at least 25 and at least four required blocks
```

The literal budget registry is:

```text
budget_order|budget_id|budget
1|budget-2.25|2.25
2|budget-4.50|4.50
3|budget-6.75|6.75
```

The literal controller-stage registry, in execution order, is:

```text
stage_order|controller_stage_id|allowed_event_types
1|CONTROLLER-STAGE-SUGGESTION|decision
2|CONTROLLER-STAGE-SELECTION|decision
3|CONTROLLER-STAGE-EXECUTION|setup;experiment
4|CONTROLLER-STAGE-EVIDENCE|evidence
5|CONTROLLER-STAGE-BELIEF-UPDATE|belief_update
6|CONTROLLER-STAGE-TERMINATION|terminal
```

These six IDs are the complete ordered controller-stage universe. Persisted decision events
use `CONTROLLER-STAGE-SELECTION`; `CONTROLLER-STAGE-SUGGESTION` identifies score-generation
divergence in `comparisons.jsonl`. No other event/stage pairing is valid.

The literal A/B/C/D branch registry is:

```text
branch_order|branch_id|ordered_condition_ids|first_decisive_condition_id|final_output|required_operand_statuses|unreachable_condition_behavior
1|BRANCH-B|G-FINAL/C01|G-FINAL/C01|B_DESIGN_ONE_MODIFICATION|B_AUTHORIZED resolved true;VETO_COMPLETE resolved true;G-B-AUTHORIZATION gate_status PASS|any unresolved authorization or veto input makes C01 INCONCLUSIVE and branch does not match
2|BRANCH-C|G-FINAL/C01;G-FINAL/C02|G-FINAL/C02|C_NO_STABLE_MECHANISM|C01 is NO_MATCH or INCONCLUSIVE; CONTROLLER_CHANGE_NEEDED resolved true; B_AUTHORIZED is FAIL or INCONCLUSIVE|an INCONCLUSIVE B authorization is preserved and cannot block C when controller change is resolved true
3|BRANCH-D|G-FINAL/C01;G-FINAL/C02;G-FINAL/C03|G-FINAL/C03|D_REAL_PPO_PILOT|C01 and C02 not MATCH and CONTROLLER_CHANGE_NEEDED resolved false and PPO_ELIGIBLE resolved true|any unresolved PPO operand makes C03 INCONCLUSIVE and branch does not match
4|BRANCH-A|G-FINAL/C01;G-FINAL/C02;G-FINAL/C03;G-FINAL/C04|G-FINAL/C04|A_RETAIN_CURRENT|C01 C02 and C03 do not match|C04 is exhaustive default and records unresolved predecessors
```

Identifier namespaces are disjoint and every protocol symbol resolves to exactly one row in
the question, scientific-hypothesis, statistical-hypothesis, metric, estimand, mechanism,
population, contrast, count-symbol, decision-symbol, predicate, formula, condition, gate,
veto, audit, artifact, enum, controller-stage, budget, or branch registry.

The literal enum registry is:

```text
enum_order|enum_id|ordered_values
1|policy_scope|IG;LA
2|policy_id|information_gain;lookahead_information_gain
3|belief_model_id|fixed_sigma_gaussian;replicated_noise_calibrated_gaussian
4|gate_status|PASS;FAIL;INCONCLUSIVE
5|contrast_status|ESTIMATED;INCONCLUSIVE
6|veto_status|VETOED;NOT_VETOED;INCONCLUSIVE
7|estimability_status|estimated;not_estimable
8|resolution_status|resolved;inconclusive
9|analysis_class|confirmatory_holm;confirmatory_threshold;decision_operand;descriptive
10|direction|lower;higher;positive;two_sided;none
11|recommendation|A_RETAIN_CURRENT;B_DESIGN_ONE_MODIFICATION;C_NO_STABLE_MECHANISM;D_REAL_PPO_PILOT
12|outcome_label|helped;hurt;mixed;nondivergent
13|sequence_class|same_order;same_set_different_order;partial_overlap;disjoint
14|resample_completion_status|complete;failed
15|run_status|complete;invalid
16|terminal_reason|candidate_space_exhausted;budget_exhausted;integrity_abort
17|quantifier|ALL;ANY
18|branch_match_status|MATCH;NO_MATCH;INCONCLUSIVE
19|candidate_role|optimizer_arm;setup;irrelevant;redundant
20|public_effect|opens_pair;completes_pair;ineligible;stop
21|oracle_use_kind|calibration;decision
22|event_type|decision;setup;experiment;evidence;belief_update;terminal
23|oracle_record_type|oracle_key;oracle_use
24|comparison_record_type|nondivergent;divergent
25|resample_record_type|bootstrap;sign_flip
26|gate_value_type|boolean;integer;scalar;gate_status;contrast_status;tuple_set;veto_status;branch_match_status
27|gate_operator|eq;ne;lt;le;gt;ge;is_true;is_false;is_empty;is_resolved;has_one_distinct_mechanism;all_resolved;evaluate_formula
28|artifact_format|JSON;JSONL;CSV
29|paired_unit|seed_block
30|eligibility_rule|EL-PAIRED;EL-DIVERGENT;EL-SEQUENCE;EL-MECHANISM;EL-CLASSIFIABLE;EL-ACTIONABILITY
31|method_mode|reuse_source;none
32|resample_result_status|valid;null
33|resample_failure_code|insufficient_complete_cases;zero_denominator;nonfinite_result;stream_failure
```

Only `run_status=complete` and the first two terminal reasons may occur in canonical
scientific artifacts. `run_status=invalid` and `integrity_abort` occur only in temporary
validation state and `validation_failure.json`; their presence prohibits finalization.

### A.7 Gate registry: 44 rows

Gate conditions are evaluated in listed gate order. Each atomic predicate yields `PASS`,
`FAIL`, or `INCONCLUSIVE`; compound status is reduced by `F-AND` or the OR semantics in
`F-HARD-SAFETY`, except that `F-B-AUTHORIZATION` uses its literal inconclusive-first
precedence. No appendix prose supplies a competing missing-value default.

```text
gate_order|gate_id|formula_id|required sources|decision use
01|G-INTEGRITY|F-INTEGRITY|A01-SEEDS;A02-WORLDS;A03-TRUTH-ISOLATION;A04-ORACLE-ISOLATION;A05-COMMON-RANDOMNESS;A06-DETERMINISM;A07-ARM-ISOLATION;A08-CALIBRATION-SEPARATION;A09-PLANNER-AND-EVIDENCE;A10-COSTS;A11-SOURCE-FREEZE;A12-MATRIX;A13-REGISTRIES;A14-HISTORICAL;A15-RESAMPLING;A16-FINALIZATION|finalization prerequisite
02|G-CORE|F-CORE|COUNT-ARM-RUNS;COUNT-COMPARISONS;COUNT-SIGMA-ROWS;COUNT-CONTRAST-ROWS;FK-ALL|all decisions
03|G-CAL-IG|F-CAL|BR-C001;BR-C002;BR-C003;BR-C004;BR-C005|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE
04|G-CAL-LA|F-CAL|BR-C006;BR-C007;BR-C008;BR-C009;BR-C010|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE
05|G-CAL-BOTH|F-AND|G-CAL-IG;G-CAL-LA|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE
06|G-HARD-SAFETY|F-HARD-SAFETY|BR-C047;BR-C048;BR-C049;BR-C050;BR-C051;BR-C052;BR-C053;BR-C054;BR-C055;BR-C056;BR-C057;BR-C058;BR-C059;BR-C060;BR-C061;BR-C062;BR-C063;BR-C064;BR-C065;BR-C066|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE
07|G-CTRL-IG|F-CTRL|BR-C001;BR-C002;BR-C004;BR-C005;BR-C011;BR-C012;BR-C013;G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE
08|G-CTRL-LA|F-CTRL|BR-C006;BR-C007;BR-C009;BR-C010;BR-C014;BR-C015;BR-C016;G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE
09|G-CTRL-BOTH|F-AND|G-CTRL-IG;G-CTRL-LA|CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE
10|G-RQ2-COST-IG|F-CONCENTRATION|BR-C017|RQ2B only
11|G-RQ2-BUDGET-IG|F-CONCENTRATION|BR-C018|RQ2B only
12|G-RQ2-COST-LA|F-CONCENTRATION|BR-C019|RQ2B only
13|G-RQ2-BUDGET-LA|F-CONCENTRATION|BR-C020|RQ2B only
14|G-RQ3-IG|F-DOMINANCE|BR-C067;COUNT-PRIMARY-SF-IG;COUNT-PRIMARY-GSR-IG|RQ3 only
15|G-RQ3-LA|F-DOMINANCE|BR-C068;COUNT-PRIMARY-SF-LA;COUNT-PRIMARY-GSR-LA|RQ3 only
16|G-RQ4-IG|F-ORDER|BR-C021|RQ4 only
17|G-RQ4-LA|F-ORDER|BR-C022|RQ4 only
18|G-ACT-IG-SCORE_FLATTENING|F-ACTION|BR-J001;BR-C023|P_RAW
19|G-ACT-IG-BELIEF_STATE_REORDERING|F-ACTION|BR-J002;BR-C024|P_RAW
20|G-ACT-IG-GROUP_SIGMA_REORDERING|F-ACTION|BR-J003;BR-C025|P_RAW
21|G-ACT-IG-BELIEF_SIGMA_INTERACTION|F-ACTION|BR-J004;BR-C026|P_RAW
22|G-ACT-IG-COST_TIEBREAK_CHANGE|F-ACTION|BR-J005;BR-C027|P_RAW
23|G-ACT-IG-PAIR_COMPLETION_DELAY|F-ACTION|BR-J006;BR-C028|P_RAW
24|G-ACT-IG-PAIR_OPENER_CHANGE|F-ACTION|BR-J007;BR-C029|P_RAW
25|G-ACT-IG-SAME_SET_DIFFERENT_ORDER|F-ACTION|BR-J008;BR-C030|P_RAW
26|G-ACT-IG-BUDGET_CROWD_OUT|F-ACTION|BR-J009;BR-C031|P_RAW
27|G-ACT-IG-CONSERVATIVE_NONCOMMITMENT|F-ACTION|BR-J010;BR-C032|P_RAW
28|G-ACT-LA-SCORE_FLATTENING|F-ACTION|BR-J011;BR-C035|P_RAW
29|G-ACT-LA-BELIEF_STATE_REORDERING|F-ACTION|BR-J012;BR-C036|P_RAW
30|G-ACT-LA-GROUP_SIGMA_REORDERING|F-ACTION|BR-J013;BR-C037|P_RAW
31|G-ACT-LA-BELIEF_SIGMA_INTERACTION|F-ACTION|BR-J014;BR-C038|P_RAW
32|G-ACT-LA-COST_TIEBREAK_CHANGE|F-ACTION|BR-J015;BR-C039|P_RAW
33|G-ACT-LA-PAIR_COMPLETION_DELAY|F-ACTION|BR-J016;BR-C040|P_RAW
34|G-ACT-LA-PAIR_OPENER_CHANGE|F-ACTION|BR-J017;BR-C041|P_RAW
35|G-ACT-LA-SAME_SET_DIFFERENT_ORDER|F-ACTION|BR-J018;BR-C042|P_RAW
36|G-ACT-LA-BUDGET_CROWD_OUT|F-ACTION|BR-J019;BR-C043|P_RAW
37|G-ACT-LA-CONSERVATIVE_NONCOMMITMENT|F-ACTION|BR-J020;BR-C044|P_RAW
38|G-ACTIONABILITY-COMPLETE|F-ACTION-COMPLETE|G-ACT-IG-SCORE_FLATTENING;G-ACT-IG-BELIEF_STATE_REORDERING;G-ACT-IG-GROUP_SIGMA_REORDERING;G-ACT-IG-BELIEF_SIGMA_INTERACTION;G-ACT-IG-COST_TIEBREAK_CHANGE;G-ACT-IG-PAIR_COMPLETION_DELAY;G-ACT-IG-PAIR_OPENER_CHANGE;G-ACT-IG-SAME_SET_DIFFERENT_ORDER;G-ACT-IG-BUDGET_CROWD_OUT;G-ACT-IG-CONSERVATIVE_NONCOMMITMENT;G-ACT-LA-SCORE_FLATTENING;G-ACT-LA-BELIEF_STATE_REORDERING;G-ACT-LA-GROUP_SIGMA_REORDERING;G-ACT-LA-BELIEF_SIGMA_INTERACTION;G-ACT-LA-COST_TIEBREAK_CHANGE;G-ACT-LA-PAIR_COMPLETION_DELAY;G-ACT-LA-PAIR_OPENER_CHANGE;G-ACT-LA-SAME_SET_DIFFERENT_ORDER;G-ACT-LA-BUDGET_CROWD_OUT;G-ACT-LA-CONSERVATIVE_NONCOMMITMENT|ACTIONABILITY_COMPLETE
39|G-CONTROLLER-CHANGE|F-CONTROLLER-CHANGE|G-INTEGRITY;G-CORE;G-CAL-BOTH;G-CTRL-BOTH;G-HARD-SAFETY|CONTROLLER_CHANGE_NEEDED
40|G-VETO-COMPLETE|F-VETO-COMPLETE|P_RAW;V001;V002;V003;V004;V005;V006;V007;V008;V009;V010;V011;V012;V013;V014;V015;V016;V017;V018;V019;V020|VETO_COMPLETE
41|G-UNIQUE-ACTIONABLE-MECHANISM|F-UNIQUE-MECHANISM|P;VETO_COMPLETE|UNIQUE_ACTIONABLE_MECHANISM
42|G-B-AUTHORIZATION|F-B-AUTHORIZATION|CONTROLLER_CHANGE_NEEDED;ACTIONABILITY_COMPLETE;VETO_COMPLETE;P_RAW;V001;V002;V003;V004;V005;V006;V007;V008;V009;V010;V011;V012;V013;V014;V015;V016;V017;V018;V019;V020;P;UNIQUE_ACTIONABLE_MECHANISM|B_AUTHORIZED
43|G-PPO|F-PPO|G-INTEGRITY;G-CORE;G-CAL-BOTH;G-CTRL-BOTH;G-HARD-SAFETY;G-ACTIONABILITY-COMPLETE;VETO_COMPLETE;P|PPO_ELIGIBLE
44|G-FINAL|F-DECISION-TABLE|G-B-AUTHORIZATION;B_AUTHORIZED;VETO_COMPLETE;CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|recommendation and gate_status
```

Appendix A.7 is an index only. Every gate resolves its `formula_id` to the sole literal
row in Appendix A.8 and every condition to the sole literal row in Appendix A.9. Formula
mathematics, thresholds, three-valued reductions, and internal predicate steps are not
restated here. A13 rejects any implementation-derived or duplicate definition.

### A.8 Literal formula registry: 43 rows

The following table is complete and authoritative. Each row is serialized verbatim in
`protocol_snapshot.json`; no additional formula may be constructed. `formula_sha256` is
the Section 9.2 content hash of the row excluding that hash field.

```text
formula_order|formula_id|ordered_operand_ids|exact_operator|evaluation_order|null_propagation|inconclusive_propagation|comparison_boundary_behavior|output_type
01|NUM-CMF|paired_rows;metric_id;seed_block_weights|For each complete pair compute calibrated metric minus fixed metric then compute the declared seed-block weighted arithmetic mean|pair rows in comparison_id order then seed blocks in seed order then population aggregate|Exclude a pair only when either arm metric is null and pass its partition to the row missingness formula|Return INCONCLUSIVE when the attached missingness formula is not PASS|No threshold comparison; preserve exact zero|F64
02|NUM-ECE|paired_probability_rows;ece_bin_edges;seed_block_weights|Reconstruct fixed and calibrated ten-bin ECE separately from raw paired probability rows then return calibrated ECE minus fixed ECE|comparison_id order then bins from left-closed right-open with final bin right-closed then seed-block weighted aggregate|Exclude a pair only when either probability vector is null and pass its partition to MISS-PAIR20|Return INCONCLUSIVE when MISS-PAIR20 is not PASS|Bin boundaries use the upper bin except confidence 1.0 uses the final bin; preserve exact zero|F64
03|NUM-HELP-HURT|divergent_outcome_rows;seed_block_weights;helped_label;hurt_label;mixed_label|Let H be the sum of the literal seed-block weights over complete divergent rows whose outcome equals helped_label and let R be the corresponding weighted sum for hurt_label; return H minus R exactly; do not divide or normalize; exclude mixed_label and nondivergent rows|comparison_id order then seed-block order then H followed by R|Null outcome labels are excluded and counted as unresolved|Return INCONCLUSIVE unless MISS-DIVERGENT20 is PASS|Label equality is literal; exact zero is retained|F64
04|NUM-HARM-RIGHT-LEFT|right_population_rows;left_population_rows;seed_block_weights|Weighted hurt rate among helped-plus-hurt rows in right population minus the corresponding weighted hurt rate in left population|right and left populations independently in comparison_id order then subtract|Null outcome labels are excluded and counted unresolved|Return INCONCLUSIVE unless MISS-TWO-RATES20 is PASS|Population membership follows literal population predicates; exact zero is retained|F64
05|NUM-HARM-PRESENT-ABSENT|mechanism_present_rows;mechanism_absent_rows;seed_block_weights|Weighted hurt rate among helped-plus-hurt rows with primary mechanism present minus the corresponding rate with it absent|present and absent independently in comparison_id order then subtract|Mixed null and nondivergent rows are excluded|Return INCONCLUSIVE unless the owning missingness formula is PASS|Primary mechanism equality is literal; contributing labels do not count as present|F64
06|NUM-COMBINED-SHARE|weighted_classifiable_denominator;COUNT-PRIMARY-SF-IG;COUNT-PRIMARY-GSR-IG;COUNT-PRIMARY-SF-LA;COUNT-PRIMARY-GSR-LA|For the requested policy add its two literal weighted primary-mechanism sums and divide once by the DEN-CLASSIFIABLE weighted denominator|select policy weighted sums then add numerator then divide once|A null primary mechanism is unclassifiable and excluded from numerator and denominator|Return INCONCLUSIVE unless MISS-DOMINANCE30 is PASS|No raw count substitutes for a weighted sum; shares equal to thresholds satisfy inclusive comparisons|F64
07|NUM-DIVERGENCE-RD|target_pairs;comparator_pairs;seed_block_weights|Weighted divergent share in target population minus weighted divergent share in comparator population|compute each population share from comparison_id ordered rows then subtract|Null comparison class is unresolved and excluded|Return INCONCLUSIVE unless MISS-TWO-RATES20 is PASS|Divergent is exact record_type divergent|F64
08|NUM-ACTIONABILITY|decision_contrast_rows;five_block_rows;source_confirmatory_row|Copy pooled mechanism-present minus absent harm estimate and its interval from the source contrast and retain the five unpooled block estimates and support counts|source row first then blocks in homogeneous weak_effect heterogeneous_noise asymmetric_cost delay order|Any missing required source or count propagates null|Return INCONCLUSIVE unless MISS-ACTION25 is PASS|Absolute effect equal to 0.15 and prevalence equal to 0.10 or 0.90 pass inclusive boundaries|ActionabilityComposite
09|DEN-PAIRED|paired_rows;complete_pair_indicator;seed_block_weights|Return the sum of the literal seed-block weights over paired rows whose complete_pair_indicator is true|comparison_id order then seed-block order|A row incomplete on either arm is excluded and increments its exact missingness partition|A nonpositive weighted sum or MISS-PAIR20 not PASS makes the owning contrast INCONCLUSIVE|No raw row count substitutes for the weighted sum; exact zero is encoded before missingness propagation|F64
10|DEN-DIVERGENT|divergent_outcome_rows;seed_block_weights;helped_label;hurt_label|Return the sum of the literal seed-block weights over complete divergent rows whose outcome equals helped_label or hurt_label; mixed and nondivergent rows are excluded|comparison_id order then seed-block order|Null outcomes are excluded and counted unresolved|A nonpositive weighted sum or MISS-DIVERGENT20 not PASS makes the owning contrast INCONCLUSIVE|No raw row count substitutes for the weighted sum|F64
11|DEN-TWO-DIVERGENT-RATES|target_divergent_rows;comparator_divergent_rows;seed_block_weights;helped_label;hurt_label|Return the ordered pair of literal weighted helped-or-hurt sums for target and comparator populations|target comparison_id order then comparator comparison_id order then seed-block order within each|Mixed null and nondivergent rows are excluded and counted in their declared partitions|A nonpositive side or MISS-TWO-RATES20 not PASS makes the owning contrast INCONCLUSIVE|No raw row count substitutes for either weighted sum|Pair<F64,F64>
12|DEN-PRESENT-ABSENT|present_rows;absent_rows;seed_block_weights;helped_label;hurt_label|Return the ordered pair of literal weighted helped-or-hurt sums for the declared present and absent populations|present comparison_id order then absent comparison_id order then seed-block order within each|Mixed null and nondivergent rows are excluded and counted in their declared partitions|A nonpositive side or owning missingness formula not PASS makes the contrast INCONCLUSIVE|No raw row count substitutes for either weighted sum|Pair<F64,F64>
13|DEN-CLASSIFIABLE|classifiable_divergences;seed_block_weights|Return the sum of the literal seed-block weights over divergent rows with one complete truth-free primary mechanism ID|comparison_id order then seed-block order|A null primary mechanism is excluded and counted unclassifiable|A nonpositive weighted sum or MISS-DOMINANCE30 not PASS makes the owning contrast INCONCLUSIVE|No raw row count substitutes for the weighted sum|F64
14|DEN-ALL-PAIRS|comparison_rows;seed_block_weights|Return the sum of the literal seed-block weights over every fixed-calibrated comparison in the contrast population|comparison_id order then seed-block order|A missing canonical comparison is an integrity failure|Missing population rows fail integrity rather than becoming a statistical zero|No raw row count substitutes for the weighted sum|F64
15|MISS-PAIR20|n_complete_pairs;n_fixed_missing_only;n_calibrated_missing_only;n_both_missing;n_total_pairs;weighted_paired_denominator;n_complete_seed_blocks|First require the five pair partitions to sum exactly to n_total_pairs or fail integrity; return PASS only when weighted_paired_denominator is strictly positive and n_complete_seed_blocks is at least 20; a complete seed block is a distinct full-study seed ID with at least one complete eligible paired row and positive weighted contribution; otherwise return INCONCLUSIVE|validate partition then weighted denominator then complete-seed-block count|Any missing required operand returns INCONCLUSIVE|Under-support and zero denominator propagate INCONCLUSIVE to estimate interval and test|Positive is strict; 20 complete seed blocks passes and 19 is INCONCLUSIVE|gate_status
16|MISS-DIVERGENT20|n_helped;n_hurt;n_mixed;n_unresolved;weighted_divergent_denominator|Return PASS only when weighted_divergent_denominator is strictly positive n_helped is at least 20 and n_hurt is at least 20 in the exact policy-population cell; mixed and unresolved rows are recorded but excluded from numerator denominator and both support counts; otherwise return INCONCLUSIVE|validate provenance counts then weighted denominator then helped then hurt|Any missing required operand returns INCONCLUSIVE|Under-support and zero denominator propagate INCONCLUSIVE to estimate interval and test|Positive is strict; each raw count boundary 20 passes and 19 is INCONCLUSIVE|gate_status
17|MISS-TWO-RATES20|weighted_target_denominator;weighted_comparator_denominator;n_target_divergent_raw;n_comparator_divergent_raw|Return PASS only when both weighted denominators are strictly positive and both exact raw divergent support counts are at least 20; otherwise return INCONCLUSIVE|target weighted denominator then comparator weighted denominator then target raw count then comparator raw count|Any missing required operand returns INCONCLUSIVE|Under-support and zero denominator propagate INCONCLUSIVE to estimate interval and test|Positive is strict; each raw count boundary 20 passes and 19 is INCONCLUSIVE|gate_status
18|MISS-SEQUENCE30|weighted_same_set_different_order_denominator;weighted_other_divergence_denominator;n_same_set_different_order_raw;n_other_divergence_raw|Return PASS only when both weighted sequence denominators are strictly positive and both exact raw support counts are at least 30; otherwise return INCONCLUSIVE|named sequence weighted denominator then comparator weighted denominator then named raw count then comparator raw count|Any missing required operand returns INCONCLUSIVE|Under-support and zero denominator propagate INCONCLUSIVE to estimate interval and test|Positive is strict; each raw count boundary 30 passes and 29 is INCONCLUSIVE|gate_status
19|MISS-MECHANISM20|weighted_present_helped_sum;weighted_present_hurt_sum;weighted_absent_helped_sum;weighted_absent_hurt_sum;n_complete_seed_blocks;n_mixed;n_unresolved|Let weighted_present_denominator equal weighted_present_helped_sum plus weighted_present_hurt_sum and weighted_absent_denominator equal weighted_absent_helped_sum plus weighted_absent_hurt_sum; return PASS only when both denominators are strictly positive and n_complete_seed_blocks is at least 20; otherwise return INCONCLUSIVE; mixed and unresolved rows are excluded from all four sums and from n_complete_seed_blocks but remain provenance counts|four weighted sums in listed order then the complete-seed-block count then provenance counts|Any null required operand returns INCONCLUSIVE|INCONCLUSIVE propagates to estimate interval raw p adjusted p result_status and estimability_status|Positive means strictly greater than zero; 20 complete seed blocks passes and 19 is INCONCLUSIVE; there is no raw helped hurt present or absent case minimum|gate_status
20|MISS-DOMINANCE30|weighted_classifiable_denominator;n_classifiable_raw|Return PASS only when the weighted classifiable denominator is strictly positive and the exact raw classifiable count is at least 30; otherwise return INCONCLUSIVE|weighted denominator then raw count|Any missing required operand returns INCONCLUSIVE|Under-support and zero denominator propagate INCONCLUSIVE to the threshold contrast|Positive is strict; raw count 30 passes and 29 is INCONCLUSIVE|gate_status
21|MISS-ACTION25|weighted_present_denominator;weighted_absent_denominator;n_present_raw;n_absent_raw;five_block_support_counts|Return PASS only when both weighted denominators are strictly positive both exact raw counts are at least 25 and at least four frozen blocks each have raw n_divergent at least 20 n_present at least 5 and n_absent at least 5; otherwise return INCONCLUSIVE|pooled weighted denominators then pooled raw counts then blocks in frozen order|Any missing pooled or block operand returns INCONCLUSIVE|Under-support and zero denominator propagate INCONCLUSIVE to the action gate and ACTIONABILITY_COMPLETE|Positive is strict; all raw count thresholds are inclusive|gate_status
22|bootstrap_10000|contrast_id;replicate_index;ordered_128_seed_blocks;estimand_formula_id|Let r5 be replicate_index as exactly five zero-padded ASCII decimal digits from 00000 through 09999; encode without whitespace or trailing LF the UTF-8 JSON array ["rde.broader.bootstrap/v2","broader-closed-loop-replication/v1",contrast_id,r5]; SHA-256 those bytes and interpret the first 8 digest bytes, bytes 0 through 7, as one unsigned big-endian U64 bootstrap seed; initialize state to that seed and for each of exactly 128 sampled positions apply state equals state plus 0x9e3779b97f4a7c15 modulo 2^64 then z equals state then z equals ((z xor (z right-shift 30)) times 0xbf58476d1ce4e5b9) modulo 2^64 then z equals ((z xor (z right-shift 27)) times 0x94d049bb133111eb) modulo 2^64 then z equals z xor (z right-shift 31); use the frozen unbiased INDEX128 result z bitand 0x7f and select seed ID 1000 plus that index; rebuild the complete registered estimand; let R be the number of valid finite replicate estimates after excluding and counting null replicates; when R is at least 9500 sort valid estimates ascending and use zero-based lower index ceil(0.025 times R) minus 1 and upper index ceil(0.975 times R) minus 1 with no interpolation; for R equal 10000 the indices are 249 and 9749|replicate_index ascending then sampled_position 0 through 127; estimand rows retain their formula order|A null replicate is stored with null result and a declared failure code and is excluded from R|R below 9500 makes the contrast INCONCLUSIVE; no alternate seed stream or quantile rule is permitted|replicate_index endpoints are inclusive; INDEX128 is unbiased because the domain size 128 divides 2^64; order-statistic indices are zero-based|BootstrapResult
23|signflip_10000|contrast_id;replicate_index;ordered_paired_seed_blocks;observed_statistic;estimand_formula_id|Let r5 be replicate_index as exactly five zero-padded ASCII decimal digits from 00000 through 09999; concatenate the UTF-8 bytes of broader-replication/v1 then U+007C then sign-flip then U+007C then contrast_id then U+007C then r5; SHA-256 those bytes and interpret the first 8 digest bytes, bytes 0 through 7, as one unsigned big-endian U64 initial state; for each paired seed block in frozen seed-block order apply the same SplitMix64 state transition and z mixing constants declared in bootstrap_10000 then consume exactly z bitand 1; bit 0 retains fixed and calibrated arm labels and bit 1 swaps them; no per-seed SHA-256 operation exists; rebuild the full estimand for each branch including raw-row ECE reconstruction and frozen-denominator risk-difference numerators; let E count replicates whose absolute statistic is greater than or equal to the absolute observed statistic and set p_raw to (1 plus E) divided by 10001|replicate_index 00000 through 09999 then one low-order bit per paired seed block in frozen order|A noncomputable replicate stores null statistic and extreme plus a declared failure code|Any noncomputable required replicate makes the hypothesis INCONCLUSIVE; no alternate sign stream is permitted|All tests are two-sided; absolute-value ties are extreme; bit semantics and replicate endpoints are inclusive exactly as stated|SignFlipResult
24|HOLM-64|ordered_64_statistical_hypothesis_ids;p_raw;statistical_hypothesis_order|Use all 64 literal ordered statistical hypotheses as one family; for arithmetic assign p_for_holm equal to p_raw when estimable and 1.0 when non-estimable; never remove a member and retain an estimable raw p-value equal to 1.0 normally; sort by p_for_holm ascending with the literal statistical_hypothesis_order as the sole tie-break; for sorted one-based rank j compute q_j equal to min(1,max over k from 1 through j of ((64 minus k plus 1) times p_for_holm_k)); map q back to literal registry order for estimable members; a non-estimable member keeps stored p_raw and p_adjusted null and result status INCONCLUSIVE even though its arithmetic p_for_holm is 1.0|construct all 64 entries in frozen order then stable rank by numeric p_for_holm and literal order then cumulative maximum then registry-order projection|Null p_raw contributes arithmetic 1.0 but stored p fields stay null|Arithmetic membership never changes INCONCLUSIVE to FAIL or PASS; dependent gates see the stored null|No member exclusion and no UTF-8 ID sorting; rejection requires stored adjusted p strictly below 0.05|HolmResult
25|F-INTEGRITY|A01-SEEDS;A02-WORLDS;A03-TRUTH-ISOLATION;A04-ORACLE-ISOLATION;A05-COMMON-RANDOMNESS;A06-DETERMINISM;A07-ARM-ISOLATION;A08-CALIBRATION-SEPARATION;A09-PLANNER-AND-EVIDENCE;A10-COSTS;A11-SOURCE-FREEZE;A12-MATRIX;A13-REGISTRIES;A14-HISTORICAL;A15-RESAMPLING;A16-FINALIZATION|Convert each audit result to PASS FAIL or INCONCLUSIVE and reduce the 16 statuses with F-AND|audit registry order|A missing audit result is INCONCLUSIVE|Use F-AND exactly; a FAIL is never masked by an INCONCLUSIVE|No numeric boundary|gate_status
26|F-CORE|COUNT-ARM-RUNS;COUNT-COMPARISONS;COUNT-SIGMA-ROWS;COUNT-CONTRAST-ROWS;FK-ALL|Create five atomic statuses for equality to 36864 18432 9216 and 122 respectively and for FK-ALL true then reduce them with F-AND|listed operand order|A missing operand creates an INCONCLUSIVE atomic status|Use F-AND exactly|Integer equality is exact|gate_status
27|F-CAL|policy_nll;policy_brier;policy_ece;policy_confidently_wrong;policy_true_probability|Create atomic statuses for NLL Brier and ECE estimate below zero ci_high below zero and Holm p below 0.05; confidently_wrong estimate at most -0.05 ci_high below zero and Holm p below 0.05; true_probability ci_low at least -0.02; reduce every atomic status with F-AND|NLL then Brier then ECE then confidently_wrong then true_probability|A null required statistic creates an INCONCLUSIVE atomic status|Use F-AND exactly|Strict and inclusive boundaries are exactly as stated|gate_status
28|F-AND|ordered_gate_status_operands|Universal three-valued AND: return FAIL when any operand is FAIL; return PASS only when every operand is PASS; otherwise return INCONCLUSIVE|literal ordered operands from left to right|A missing operand is INCONCLUSIVE before reduction|An INCONCLUSIVE operand is never converted to PASS or FAIL; a coexisting FAIL still determines FAIL|No numeric boundary|gate_status
29|F-HARD-SAFETY|BR-C047;BR-C048;BR-C049;BR-C050;BR-C051;BR-C052;BR-C053;BR-C054;BR-C055;BR-C056;BR-C057;BR-C058;BR-C059;BR-C060;BR-C061;BR-C062;BR-C063;BR-C064;BR-C065;BR-C066|For each contrast create PASS when estimate is at least 0.05 ci_low is above zero and Holm p is below 0.05; create FAIL when the contrast is complete and that conjunction is false; otherwise create INCONCLUSIVE; universal three-valued OR returns PASS when any operand is PASS returns FAIL only when every operand is FAIL and otherwise returns INCONCLUSIVE|contrast registry order|A null or incomplete contrast creates an INCONCLUSIVE atomic status|An INCONCLUSIVE operand is never converted to PASS or FAIL; a coexisting PASS still determines PASS|Estimate uses inclusive 0.05; CI and p use strict boundaries|gate_status
30|F-CTRL|policy_nll;policy_brier;policy_true_probability;policy_confidently_wrong;policy_helped_minus_hurt;policy_conditional_efficiency;policy_end_to_end_efficiency;G-HARD-SAFETY|Create atomic statuses for NLL and Brier estimate and ci_high below zero and Holm p below 0.05; true_probability estimate at least 0.02 ci_low above zero and Holm p below 0.05; confidently_wrong estimate and ci_high at most zero; helped_minus_hurt and both efficiencies estimate and ci_low above zero and Holm p below 0.05; and G-HARD-SAFETY equal FAIL; reduce every atomic status with F-AND|listed operand order|A null required value creates an INCONCLUSIVE atomic status|Use F-AND exactly|Inclusive only for true_probability estimate 0.02 and confidently_wrong zero; all other stated inequalities strict|gate_status
31|F-CONCENTRATION|target_divergent_count;comparator_divergent_count;contrast_estimate;ci_low;p_adjusted|Create atomic statuses for both counts at least 20 estimate at least 0.10 ci_low above zero and adjusted p below 0.05 then reduce them with F-AND|listed operand order|A null creates an INCONCLUSIVE atomic status|Use F-AND exactly|Counts and estimate inclusive; CI and p strict|gate_status
32|F-DOMINANCE|classifiable_count;combined_primary_share;ci_low;score_flattening_share;group_sigma_reordering_share|Create atomic statuses for count at least 30 combined share at least 0.70 ci_low at least 0.60 and each named share at least 0.10 then reduce them with F-AND|listed operand order|A null creates an INCONCLUSIVE atomic status|Use F-AND exactly|All boundaries inclusive|gate_status
33|F-ORDER|present_count;absent_count;contrast_estimate;ci_low;p_adjusted|Create atomic statuses for both counts at least 30 estimate at least 0.10 ci_low above zero and adjusted p below 0.05 then reduce them with F-AND|listed operand order|A null creates an INCONCLUSIVE atomic status|Use F-AND exactly|Counts and estimate inclusive; CI and p strict|gate_status
34|F-ACTION|decision_contrast;source_confirmatory_contrast;five_actionability_blocks;mechanism_allowlist;truth_free_provenance|Create atomic statuses for source ESTIMATED; pooled present and absent each at least 25; prevalence between 0.10 and 0.90 inclusive; absolute estimate at least 0.15; CI excluding zero; source Holm p below 0.05; at least four frozen blocks with n_divergent at least 20 and present and absent at least 5; every eligible block having the pooled nonzero sign and no opposite-sign absolute estimate at least 0.10; provenance true; and allowlist true; reduce every required atomic status with F-AND|pooled predicates in stated order then five blocks in frozen order then provenance then allowlist|A missing required pooled or eligible-block operand creates an INCONCLUSIVE atomic status|Use F-AND exactly; an inconclusive result is excluded from P_RAW and leaves ACTIONABILITY_COMPLETE unresolved through F-ACTION-COMPLETE|Inclusive 0.10 0.90 0.15 and count boundaries; strict CI exclusion and p boundary|gate_status
35|F-ACTION-COMPLETE|ordered_20_action_gate_statuses|P_RAW is the ordered ActionTuple list for PASS statuses; ACTIONABILITY_COMPLETE is resolved true only when every status is PASS or FAIL and is otherwise an inconclusive DecisionBoolean with null value|action gate order 18 through 37|A missing status is INCONCLUSIVE|An INCONCLUSIVE action gate is never converted to false; it is excluded from P_RAW and leaves ACTIONABILITY_COMPLETE inconclusive|No numeric boundary|ActionabilityResult
36|F-VETO|source_tuple;required_veto_contrast_id;own_effect;other_policy_effect;other_policy_ci;other_policy_holm_p;support_counts|VETOED iff supported other-policy effect has opposite sign to own effect absolute magnitude at least 0.15 CI excludes zero and Holm p below 0.05; NOT_VETOED iff every required operand resolves and predicate is false; otherwise INCONCLUSIVE|support then signs then magnitude then CI then Holm|Any missing or under-supported operand yields INCONCLUSIVE|INCONCLUSIVE is neither VETOED nor NOT_VETOED|Magnitude 0.15 passes; CI exclusion and p below 0.05 are strict|veto_status
37|F-VETO-COMPLETE|P_RAW;ordered_20_veto_evaluations|VETO_COMPLETE is a resolved true DecisionBoolean only when every tuple in P_RAW has exactly one matching veto_status equal to VETOED or NOT_VETOED; if any required matching status is INCONCLUSIVE or missing VETO_COMPLETE is an inconclusive DecisionBoolean with null value|P_RAW policy-mechanism order then matching veto ID|A missing matching veto row is INCONCLUSIVE|An INCONCLUSIVE veto is never converted to false and cannot authorize B|No numeric boundary|DecisionBoolean
38|F-P|P_RAW;ordered_20_veto_evaluations|VETOED_TUPLES is the ordered subset of P_RAW with VETOED status; P is the ordered subset of P_RAW with NOT_VETOED status; INCONCLUSIVE tuples occur in neither subset; when VETO_COMPLETE is INCONCLUSIVE the materialized P list remains this resolved subset but formula-local P_NONEMPTY distinct-mechanism count and every other P-derived Branch B predicate each have evaluation status INCONCLUSIVE rather than FAIL; only when VETO_COMPLETE is PASS does P_NONEMPTY become PASS for a nonempty P or FAIL for an empty P|P_RAW policy-mechanism order then veto completeness then P-derived predicate statuses|A missing matching veto row acts as INCONCLUSIVE|INCONCLUSIVE excludes the tuple from P leaves VETO_COMPLETE inconclusive and prevents P emptiness from becoming FAIL|Status equality is literal; no unresolved veto is inferred from list shape|ActionSetPartition
39|F-UNIQUE-MECHANISM|P;VETO_COMPLETE|First inspect VETO_COMPLETE; when it is INCONCLUSIVE return an inconclusive DecisionBoolean without evaluating P emptiness or distinct-mechanism count; when it is PASS return resolved true exactly when P contains one distinct mechanism_id and every P tuple has NOT_VETOED status and return resolved false otherwise|veto completeness before P contents then statuses then distinct mechanism count|A missing operand returns an inconclusive DecisionBoolean|An inconclusive veto dominates P emptiness and is neither true nor false|Distinct mechanism count exactly one passes after veto completeness is PASS|DecisionBoolean
40|F-CONTROLLER-CHANGE|G-INTEGRITY;G-CORE;G-CAL-BOTH;G-CTRL-BOTH;G-HARD-SAFETY|Create atomic statuses for G-INTEGRITY PASS G-CORE PASS G-CAL-BOTH PASS and the nested OR of G-CTRL-BOTH FAIL with G-HARD-SAFETY PASS; reduce the nested OR with the universal OR semantics in F-HARD-SAFETY and the outer conjunction with F-AND; map PASS to resolved true FAIL to resolved false and INCONCLUSIVE to an inconclusive DecisionBoolean|listed gate order|A missing status creates an INCONCLUSIVE atomic status|Use the cited three-valued reductions exactly|Boolean equality is exact|DecisionBoolean
41|F-PPO|G-INTEGRITY;G-CORE;G-CAL-BOTH;G-CTRL-BOTH;G-HARD-SAFETY;G-ACTIONABILITY-COMPLETE;VETO_COMPLETE;P;CONTROLLER_CHANGE_NEEDED|Create atomic statuses for integrity core calibration and controller gates PASS hard safety FAIL actionability and veto completeness resolved true P empty and controller change resolved false; reduce them with F-AND; map PASS to resolved true FAIL to resolved false and INCONCLUSIVE to an inconclusive DecisionBoolean|listed operand order|A missing or inconclusive operand creates an INCONCLUSIVE atomic status|Use F-AND exactly; an inconclusive result cannot authorize D|Empty means zero tuples exactly|DecisionBoolean
42|F-B-AUTHORIZATION|CONTROLLER_CHANGE_NEEDED;ACTIONABILITY_COMPLETE;VETO_COMPLETE;P_RAW;ordered_20_veto_evaluations;P;UNIQUE_ACTIONABLE_MECHANISM|Dedicated three-valued precedence: first require exactly one matching veto_status for every tuple in P_RAW and inspect every required veto and authorization operand; if any required veto_status or any of CONTROLLER_CHANGE_NEEDED ACTIONABILITY_COMPLETE VETO_COMPLETE or UNIQUE_ACTIONABLE_MECHANISM is missing or INCONCLUSIVE return an inconclusive DecisionBoolean with null value and do not evaluate P_NONEMPTY distinct-mechanism count or any other P-derived predicate as FAIL; otherwise return resolved true only when CONTROLLER_CHANGE_NEEDED is PASS ACTIONABILITY_COMPLETE is PASS VETO_COMPLETE is PASS P contains exactly one distinct mechanism every surviving P tuple has NOT_VETOED status and UNIQUE_ACTIONABLE_MECHANISM is PASS; otherwise return resolved false|P_RAW policy-mechanism order and matching veto statuses first then authorization resolution statuses then only if all are resolved evaluate P contents and pass-fail conditions|Any missing required authorization or veto operand returns INCONCLUSIVE before resolved-failure evaluation|INCONCLUSIVE has strict precedence over every FAIL candidate; this formula does not use ordinary F-AND and P emptiness cannot mask an unresolved veto|PASS means resolved true FAIL means resolved false and INCONCLUSIVE means null value with inconclusive resolution|DecisionBoolean
43|F-DECISION-TABLE|G-B-AUTHORIZATION;B_AUTHORIZED;VETO_COMPLETE;CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE;ordered_branch_registry|Evaluate the four literal Appendix A.6 branches in frozen order and choose exactly the first MATCH; B can match only when G-B-AUTHORIZATION is PASS B_AUTHORIZED is PASS and VETO_COMPLETE is PASS; C matches when controller change is PASS and B_AUTHORIZED is FAIL or INCONCLUSIVE; D can match only when controller change is FAIL and PPO eligibility is PASS; A is the exhaustive default after the prior three do not match; set G-FINAL gate_status PASS only when exactly one branch is selected and its BranchTrace preserves every operand and unresolved state set FAIL for zero or multiple selected branches or a trace contradiction and set INCONCLUSIVE only when a required registry or condition record is absent|BRANCH-B then BRANCH-C then BRANCH-D then BRANCH-A|A missing condition record makes G-FINAL gate_status INCONCLUSIVE and prohibits finalization|Branch C preserves an INCONCLUSIVE B authorization rather than converting it; selecting A likewise preserves unresolved predecessors; A16 verifies all statuses|PASS and FAIL for DecisionBoolean operands use the Section 7.1 mapping|DecisionResult
```

### A.9 Literal gate-condition registry: 66 rows

This is the complete condition universe. A gate may evaluate only these rows, in this order.
No implementation may expand internal formula predicates into additional conditions.
`condition_sha256` is the Section 9.2 content hash of the row excluding that hash field.

```text
condition_order|condition_id|gate_id|ordered_operand_ids|quantifier|predicate|expected_or_threshold|unresolved_behavior|result_enum
01|G-INTEGRITY/C01|G-INTEGRITY|A01-SEEDS;A02-WORLDS;A03-TRUTH-ISOLATION;A04-ORACLE-ISOLATION;A05-COMMON-RANDOMNESS;A06-DETERMINISM;A07-ARM-ISOLATION;A08-CALIBRATION-SEPARATION;A09-PLANNER-AND-EVIDENCE;A10-COSTS;A11-SOURCE-FREEZE;A12-MATRIX;A13-REGISTRIES;A14-HISTORICAL;A15-RESAMPLING;A16-FINALIZATION|ALL|evaluate F-INTEGRITY using its literal operator|F-INTEGRITY output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
02|G-CORE/C01|G-CORE|COUNT-ARM-RUNS;COUNT-COMPARISONS;COUNT-SIGMA-ROWS;COUNT-CONTRAST-ROWS;FK-ALL|ALL|evaluate F-CORE using its literal operator|F-CORE output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
03|G-CAL-IG/C01|G-CAL-IG|BR-C001;BR-C002;BR-C003;BR-C004;BR-C005|ALL|evaluate F-CAL using its literal operator|F-CAL output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
04|G-CAL-LA/C01|G-CAL-LA|BR-C006;BR-C007;BR-C008;BR-C009;BR-C010|ALL|evaluate F-CAL using its literal operator|F-CAL output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
05|G-CAL-BOTH/C01|G-CAL-BOTH|G-CAL-IG;G-CAL-LA|ALL|evaluate F-AND using its literal operator|F-AND output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
06|G-HARD-SAFETY/C01|G-HARD-SAFETY|BR-C047;BR-C048;BR-C049;BR-C050;BR-C051;BR-C052;BR-C053;BR-C054;BR-C055;BR-C056;BR-C057;BR-C058;BR-C059;BR-C060;BR-C061;BR-C062;BR-C063;BR-C064;BR-C065;BR-C066|ANY|evaluate F-HARD-SAFETY using its literal operator|F-HARD-SAFETY output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
07|G-CTRL-IG/C01|G-CTRL-IG|BR-C001;BR-C002;BR-C004;BR-C005;BR-C011;BR-C012;BR-C013;G-HARD-SAFETY|ALL|evaluate F-CTRL using its literal operator|F-CTRL output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
08|G-CTRL-LA/C01|G-CTRL-LA|BR-C006;BR-C007;BR-C009;BR-C010;BR-C014;BR-C015;BR-C016;G-HARD-SAFETY|ALL|evaluate F-CTRL using its literal operator|F-CTRL output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
09|G-CTRL-BOTH/C01|G-CTRL-BOTH|G-CTRL-IG;G-CTRL-LA|ALL|evaluate F-AND using its literal operator|F-AND output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
10|G-RQ2-COST-IG/C01|G-RQ2-COST-IG|BR-C017|ALL|evaluate F-CONCENTRATION using its literal operator|F-CONCENTRATION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
11|G-RQ2-BUDGET-IG/C01|G-RQ2-BUDGET-IG|BR-C018|ALL|evaluate F-CONCENTRATION using its literal operator|F-CONCENTRATION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
12|G-RQ2-COST-LA/C01|G-RQ2-COST-LA|BR-C019|ALL|evaluate F-CONCENTRATION using its literal operator|F-CONCENTRATION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
13|G-RQ2-BUDGET-LA/C01|G-RQ2-BUDGET-LA|BR-C020|ALL|evaluate F-CONCENTRATION using its literal operator|F-CONCENTRATION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
14|G-RQ3-IG/C01|G-RQ3-IG|BR-C067;COUNT-PRIMARY-SF-IG;COUNT-PRIMARY-GSR-IG|ALL|evaluate F-DOMINANCE using its literal operator|F-DOMINANCE output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
15|G-RQ3-LA/C01|G-RQ3-LA|BR-C068;COUNT-PRIMARY-SF-LA;COUNT-PRIMARY-GSR-LA|ALL|evaluate F-DOMINANCE using its literal operator|F-DOMINANCE output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
16|G-RQ4-IG/C01|G-RQ4-IG|BR-C021|ALL|evaluate F-ORDER using its literal operator|F-ORDER output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
17|G-RQ4-LA/C01|G-RQ4-LA|BR-C022|ALL|evaluate F-ORDER using its literal operator|F-ORDER output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
18|G-ACT-IG-SCORE_FLATTENING/C01|G-ACT-IG-SCORE_FLATTENING|BR-J001;BR-C023|ALL|evaluate F-ACTION using its literal operator|F-ACTION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
19|G-ACT-IG-BELIEF_STATE_REORDERING/C01|G-ACT-IG-BELIEF_STATE_REORDERING|BR-J002;BR-C024|ALL|evaluate F-ACTION using its literal operator|F-ACTION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
20|G-ACT-IG-GROUP_SIGMA_REORDERING/C01|G-ACT-IG-GROUP_SIGMA_REORDERING|BR-J003;BR-C025|ALL|evaluate F-ACTION using its literal operator|F-ACTION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
21|G-ACT-IG-BELIEF_SIGMA_INTERACTION/C01|G-ACT-IG-BELIEF_SIGMA_INTERACTION|BR-J004;BR-C026|ALL|evaluate F-ACTION using its literal operator|F-ACTION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
22|G-ACT-IG-COST_TIEBREAK_CHANGE/C01|G-ACT-IG-COST_TIEBREAK_CHANGE|BR-J005;BR-C027|ALL|evaluate F-ACTION using its literal operator|F-ACTION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
23|G-ACT-IG-PAIR_COMPLETION_DELAY/C01|G-ACT-IG-PAIR_COMPLETION_DELAY|BR-J006;BR-C028|ALL|evaluate F-ACTION using its literal operator|F-ACTION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
24|G-ACT-IG-PAIR_OPENER_CHANGE/C01|G-ACT-IG-PAIR_OPENER_CHANGE|BR-J007;BR-C029|ALL|evaluate F-ACTION using its literal operator|F-ACTION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
25|G-ACT-IG-SAME_SET_DIFFERENT_ORDER/C01|G-ACT-IG-SAME_SET_DIFFERENT_ORDER|BR-J008;BR-C030|ALL|evaluate F-ACTION using its literal operator|F-ACTION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
26|G-ACT-IG-BUDGET_CROWD_OUT/C01|G-ACT-IG-BUDGET_CROWD_OUT|BR-J009;BR-C031|ALL|evaluate F-ACTION using its literal operator|F-ACTION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
27|G-ACT-IG-CONSERVATIVE_NONCOMMITMENT/C01|G-ACT-IG-CONSERVATIVE_NONCOMMITMENT|BR-J010;BR-C032|ALL|evaluate F-ACTION using its literal operator|F-ACTION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
28|G-ACT-LA-SCORE_FLATTENING/C01|G-ACT-LA-SCORE_FLATTENING|BR-J011;BR-C035|ALL|evaluate F-ACTION using its literal operator|F-ACTION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
29|G-ACT-LA-BELIEF_STATE_REORDERING/C01|G-ACT-LA-BELIEF_STATE_REORDERING|BR-J012;BR-C036|ALL|evaluate F-ACTION using its literal operator|F-ACTION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
30|G-ACT-LA-GROUP_SIGMA_REORDERING/C01|G-ACT-LA-GROUP_SIGMA_REORDERING|BR-J013;BR-C037|ALL|evaluate F-ACTION using its literal operator|F-ACTION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
31|G-ACT-LA-BELIEF_SIGMA_INTERACTION/C01|G-ACT-LA-BELIEF_SIGMA_INTERACTION|BR-J014;BR-C038|ALL|evaluate F-ACTION using its literal operator|F-ACTION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
32|G-ACT-LA-COST_TIEBREAK_CHANGE/C01|G-ACT-LA-COST_TIEBREAK_CHANGE|BR-J015;BR-C039|ALL|evaluate F-ACTION using its literal operator|F-ACTION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
33|G-ACT-LA-PAIR_COMPLETION_DELAY/C01|G-ACT-LA-PAIR_COMPLETION_DELAY|BR-J016;BR-C040|ALL|evaluate F-ACTION using its literal operator|F-ACTION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
34|G-ACT-LA-PAIR_OPENER_CHANGE/C01|G-ACT-LA-PAIR_OPENER_CHANGE|BR-J017;BR-C041|ALL|evaluate F-ACTION using its literal operator|F-ACTION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
35|G-ACT-LA-SAME_SET_DIFFERENT_ORDER/C01|G-ACT-LA-SAME_SET_DIFFERENT_ORDER|BR-J018;BR-C042|ALL|evaluate F-ACTION using its literal operator|F-ACTION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
36|G-ACT-LA-BUDGET_CROWD_OUT/C01|G-ACT-LA-BUDGET_CROWD_OUT|BR-J019;BR-C043|ALL|evaluate F-ACTION using its literal operator|F-ACTION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
37|G-ACT-LA-CONSERVATIVE_NONCOMMITMENT/C01|G-ACT-LA-CONSERVATIVE_NONCOMMITMENT|BR-J020;BR-C044|ALL|evaluate F-ACTION using its literal operator|F-ACTION output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
38|G-ACTIONABILITY-COMPLETE/C01|G-ACTIONABILITY-COMPLETE|G-ACT-IG-SCORE_FLATTENING;G-ACT-IG-BELIEF_STATE_REORDERING;G-ACT-IG-GROUP_SIGMA_REORDERING;G-ACT-IG-BELIEF_SIGMA_INTERACTION;G-ACT-IG-COST_TIEBREAK_CHANGE;G-ACT-IG-PAIR_COMPLETION_DELAY;G-ACT-IG-PAIR_OPENER_CHANGE;G-ACT-IG-SAME_SET_DIFFERENT_ORDER;G-ACT-IG-BUDGET_CROWD_OUT;G-ACT-IG-CONSERVATIVE_NONCOMMITMENT;G-ACT-LA-SCORE_FLATTENING;G-ACT-LA-BELIEF_STATE_REORDERING;G-ACT-LA-GROUP_SIGMA_REORDERING;G-ACT-LA-BELIEF_SIGMA_INTERACTION;G-ACT-LA-COST_TIEBREAK_CHANGE;G-ACT-LA-PAIR_COMPLETION_DELAY;G-ACT-LA-PAIR_OPENER_CHANGE;G-ACT-LA-SAME_SET_DIFFERENT_ORDER;G-ACT-LA-BUDGET_CROWD_OUT;G-ACT-LA-CONSERVATIVE_NONCOMMITMENT|ALL|evaluate F-ACTION-COMPLETE using its literal operator|F-ACTION-COMPLETE output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
39|G-CONTROLLER-CHANGE/C01|G-CONTROLLER-CHANGE|G-INTEGRITY;G-CORE;G-CAL-BOTH;G-CTRL-BOTH;G-HARD-SAFETY|ALL|evaluate F-CONTROLLER-CHANGE using its literal operator|F-CONTROLLER-CHANGE output equals PASS or resolved true as typed|any formula-level null or INCONCLUSIVE produces gate_status INCONCLUSIVE|gate_status
40|G-VETO-COMPLETE/C01|G-VETO-COMPLETE|P_RAW;V001|ALL|if V001 source_tuple is absent from P_RAW return PASS; otherwise require V001 veto_status to equal VETOED or NOT_VETOED|tuple absent from P_RAW or tuple-specific veto_status resolved|missing V001 or veto_status INCONCLUSIVE for a tuple in P_RAW returns gate_status INCONCLUSIVE and leaves VETO_COMPLETE an inconclusive DecisionBoolean|gate_status
41|G-VETO-COMPLETE/C02|G-VETO-COMPLETE|P_RAW;V002|ALL|if V002 source_tuple is absent from P_RAW return PASS; otherwise require V002 veto_status to equal VETOED or NOT_VETOED|tuple absent from P_RAW or tuple-specific veto_status resolved|missing V002 or veto_status INCONCLUSIVE for a tuple in P_RAW returns gate_status INCONCLUSIVE and leaves VETO_COMPLETE an inconclusive DecisionBoolean|gate_status
42|G-VETO-COMPLETE/C03|G-VETO-COMPLETE|P_RAW;V003|ALL|if V003 source_tuple is absent from P_RAW return PASS; otherwise require V003 veto_status to equal VETOED or NOT_VETOED|tuple absent from P_RAW or tuple-specific veto_status resolved|missing V003 or veto_status INCONCLUSIVE for a tuple in P_RAW returns gate_status INCONCLUSIVE and leaves VETO_COMPLETE an inconclusive DecisionBoolean|gate_status
43|G-VETO-COMPLETE/C04|G-VETO-COMPLETE|P_RAW;V004|ALL|if V004 source_tuple is absent from P_RAW return PASS; otherwise require V004 veto_status to equal VETOED or NOT_VETOED|tuple absent from P_RAW or tuple-specific veto_status resolved|missing V004 or veto_status INCONCLUSIVE for a tuple in P_RAW returns gate_status INCONCLUSIVE and leaves VETO_COMPLETE an inconclusive DecisionBoolean|gate_status
44|G-VETO-COMPLETE/C05|G-VETO-COMPLETE|P_RAW;V005|ALL|if V005 source_tuple is absent from P_RAW return PASS; otherwise require V005 veto_status to equal VETOED or NOT_VETOED|tuple absent from P_RAW or tuple-specific veto_status resolved|missing V005 or veto_status INCONCLUSIVE for a tuple in P_RAW returns gate_status INCONCLUSIVE and leaves VETO_COMPLETE an inconclusive DecisionBoolean|gate_status
45|G-VETO-COMPLETE/C06|G-VETO-COMPLETE|P_RAW;V006|ALL|if V006 source_tuple is absent from P_RAW return PASS; otherwise require V006 veto_status to equal VETOED or NOT_VETOED|tuple absent from P_RAW or tuple-specific veto_status resolved|missing V006 or veto_status INCONCLUSIVE for a tuple in P_RAW returns gate_status INCONCLUSIVE and leaves VETO_COMPLETE an inconclusive DecisionBoolean|gate_status
46|G-VETO-COMPLETE/C07|G-VETO-COMPLETE|P_RAW;V007|ALL|if V007 source_tuple is absent from P_RAW return PASS; otherwise require V007 veto_status to equal VETOED or NOT_VETOED|tuple absent from P_RAW or tuple-specific veto_status resolved|missing V007 or veto_status INCONCLUSIVE for a tuple in P_RAW returns gate_status INCONCLUSIVE and leaves VETO_COMPLETE an inconclusive DecisionBoolean|gate_status
47|G-VETO-COMPLETE/C08|G-VETO-COMPLETE|P_RAW;V008|ALL|if V008 source_tuple is absent from P_RAW return PASS; otherwise require V008 veto_status to equal VETOED or NOT_VETOED|tuple absent from P_RAW or tuple-specific veto_status resolved|missing V008 or veto_status INCONCLUSIVE for a tuple in P_RAW returns gate_status INCONCLUSIVE and leaves VETO_COMPLETE an inconclusive DecisionBoolean|gate_status
48|G-VETO-COMPLETE/C09|G-VETO-COMPLETE|P_RAW;V009|ALL|if V009 source_tuple is absent from P_RAW return PASS; otherwise require V009 veto_status to equal VETOED or NOT_VETOED|tuple absent from P_RAW or tuple-specific veto_status resolved|missing V009 or veto_status INCONCLUSIVE for a tuple in P_RAW returns gate_status INCONCLUSIVE and leaves VETO_COMPLETE an inconclusive DecisionBoolean|gate_status
49|G-VETO-COMPLETE/C10|G-VETO-COMPLETE|P_RAW;V010|ALL|if V010 source_tuple is absent from P_RAW return PASS; otherwise require V010 veto_status to equal VETOED or NOT_VETOED|tuple absent from P_RAW or tuple-specific veto_status resolved|missing V010 or veto_status INCONCLUSIVE for a tuple in P_RAW returns gate_status INCONCLUSIVE and leaves VETO_COMPLETE an inconclusive DecisionBoolean|gate_status
50|G-VETO-COMPLETE/C11|G-VETO-COMPLETE|P_RAW;V011|ALL|if V011 source_tuple is absent from P_RAW return PASS; otherwise require V011 veto_status to equal VETOED or NOT_VETOED|tuple absent from P_RAW or tuple-specific veto_status resolved|missing V011 or veto_status INCONCLUSIVE for a tuple in P_RAW returns gate_status INCONCLUSIVE and leaves VETO_COMPLETE an inconclusive DecisionBoolean|gate_status
51|G-VETO-COMPLETE/C12|G-VETO-COMPLETE|P_RAW;V012|ALL|if V012 source_tuple is absent from P_RAW return PASS; otherwise require V012 veto_status to equal VETOED or NOT_VETOED|tuple absent from P_RAW or tuple-specific veto_status resolved|missing V012 or veto_status INCONCLUSIVE for a tuple in P_RAW returns gate_status INCONCLUSIVE and leaves VETO_COMPLETE an inconclusive DecisionBoolean|gate_status
52|G-VETO-COMPLETE/C13|G-VETO-COMPLETE|P_RAW;V013|ALL|if V013 source_tuple is absent from P_RAW return PASS; otherwise require V013 veto_status to equal VETOED or NOT_VETOED|tuple absent from P_RAW or tuple-specific veto_status resolved|missing V013 or veto_status INCONCLUSIVE for a tuple in P_RAW returns gate_status INCONCLUSIVE and leaves VETO_COMPLETE an inconclusive DecisionBoolean|gate_status
53|G-VETO-COMPLETE/C14|G-VETO-COMPLETE|P_RAW;V014|ALL|if V014 source_tuple is absent from P_RAW return PASS; otherwise require V014 veto_status to equal VETOED or NOT_VETOED|tuple absent from P_RAW or tuple-specific veto_status resolved|missing V014 or veto_status INCONCLUSIVE for a tuple in P_RAW returns gate_status INCONCLUSIVE and leaves VETO_COMPLETE an inconclusive DecisionBoolean|gate_status
54|G-VETO-COMPLETE/C15|G-VETO-COMPLETE|P_RAW;V015|ALL|if V015 source_tuple is absent from P_RAW return PASS; otherwise require V015 veto_status to equal VETOED or NOT_VETOED|tuple absent from P_RAW or tuple-specific veto_status resolved|missing V015 or veto_status INCONCLUSIVE for a tuple in P_RAW returns gate_status INCONCLUSIVE and leaves VETO_COMPLETE an inconclusive DecisionBoolean|gate_status
55|G-VETO-COMPLETE/C16|G-VETO-COMPLETE|P_RAW;V016|ALL|if V016 source_tuple is absent from P_RAW return PASS; otherwise require V016 veto_status to equal VETOED or NOT_VETOED|tuple absent from P_RAW or tuple-specific veto_status resolved|missing V016 or veto_status INCONCLUSIVE for a tuple in P_RAW returns gate_status INCONCLUSIVE and leaves VETO_COMPLETE an inconclusive DecisionBoolean|gate_status
56|G-VETO-COMPLETE/C17|G-VETO-COMPLETE|P_RAW;V017|ALL|if V017 source_tuple is absent from P_RAW return PASS; otherwise require V017 veto_status to equal VETOED or NOT_VETOED|tuple absent from P_RAW or tuple-specific veto_status resolved|missing V017 or veto_status INCONCLUSIVE for a tuple in P_RAW returns gate_status INCONCLUSIVE and leaves VETO_COMPLETE an inconclusive DecisionBoolean|gate_status
57|G-VETO-COMPLETE/C18|G-VETO-COMPLETE|P_RAW;V018|ALL|if V018 source_tuple is absent from P_RAW return PASS; otherwise require V018 veto_status to equal VETOED or NOT_VETOED|tuple absent from P_RAW or tuple-specific veto_status resolved|missing V018 or veto_status INCONCLUSIVE for a tuple in P_RAW returns gate_status INCONCLUSIVE and leaves VETO_COMPLETE an inconclusive DecisionBoolean|gate_status
58|G-VETO-COMPLETE/C19|G-VETO-COMPLETE|P_RAW;V019|ALL|if V019 source_tuple is absent from P_RAW return PASS; otherwise require V019 veto_status to equal VETOED or NOT_VETOED|tuple absent from P_RAW or tuple-specific veto_status resolved|missing V019 or veto_status INCONCLUSIVE for a tuple in P_RAW returns gate_status INCONCLUSIVE and leaves VETO_COMPLETE an inconclusive DecisionBoolean|gate_status
59|G-VETO-COMPLETE/C20|G-VETO-COMPLETE|P_RAW;V020|ALL|if V020 source_tuple is absent from P_RAW return PASS; otherwise require V020 veto_status to equal VETOED or NOT_VETOED|tuple absent from P_RAW or tuple-specific veto_status resolved|missing V020 or veto_status INCONCLUSIVE for a tuple in P_RAW returns gate_status INCONCLUSIVE and leaves VETO_COMPLETE an inconclusive DecisionBoolean|gate_status
60|G-UNIQUE-ACTIONABLE-MECHANISM/C01|G-UNIQUE-ACTIONABLE-MECHANISM|P;VETO_COMPLETE|ALL|evaluate F-UNIQUE-MECHANISM using its literal operator|resolved true|any unresolved operand returns gate_status INCONCLUSIVE|gate_status
61|G-B-AUTHORIZATION/C01|G-B-AUTHORIZATION|CONTROLLER_CHANGE_NEEDED;ACTIONABILITY_COMPLETE;VETO_COMPLETE;P_RAW;V001;V002;V003;V004;V005;V006;V007;V008;V009;V010;V011;V012;V013;V014;V015;V016;V017;V018;V019;V020;P;UNIQUE_ACTIONABLE_MECHANISM|ALL|evaluate the dedicated precedence in F-B-AUTHORIZATION; ALL denotes required operand enumeration and not F-AND; map its resolved true resolved false or inconclusive DecisionBoolean to PASS FAIL or INCONCLUSIVE respectively|resolved true|any required authorization or veto INCONCLUSIVE makes this condition INCONCLUSIVE before P_NONEMPTY or another P-derived predicate can fail; Branch B cannot match|gate_status
62|G-PPO/C01|G-PPO|G-INTEGRITY;G-CORE;G-CAL-BOTH;G-CTRL-BOTH;G-HARD-SAFETY;G-ACTIONABILITY-COMPLETE;VETO_COMPLETE;P;CONTROLLER_CHANGE_NEEDED|ALL|evaluate F-PPO using its literal operator|resolved true|any unresolved operand returns gate_status INCONCLUSIVE and PPO_ELIGIBLE is not true|gate_status
63|G-FINAL/C01|G-FINAL|G-B-AUTHORIZATION;B_AUTHORIZED;VETO_COMPLETE|ALL|match BRANCH-B iff G-B-AUTHORIZATION gate_status is PASS B_AUTHORIZED is resolved true and VETO_COMPLETE is resolved true|true|any unresolved authorization or veto operand is INCONCLUSIVE and cannot match|branch_match_status
64|G-FINAL/C02|G-FINAL|G-FINAL/C01;CONTROLLER_CHANGE_NEEDED;B_AUTHORIZED|ALL|match BRANCH-C iff C01 is NO_MATCH or INCONCLUSIVE CONTROLLER_CHANGE_NEEDED is PASS and B_AUTHORIZED is FAIL or INCONCLUSIVE|true|an INCONCLUSIVE B_AUTHORIZED is an explicit Branch C input and remains INCONCLUSIVE in the trace; an INCONCLUSIVE controller-change operand makes this condition INCONCLUSIVE|branch_match_status
65|G-FINAL/C03|G-FINAL|G-FINAL/C01;G-FINAL/C02;CONTROLLER_CHANGE_NEEDED;PPO_ELIGIBLE|ALL|match BRANCH-D iff C01 and C02 are not MATCH CONTROLLER_CHANGE_NEEDED is resolved false and PPO_ELIGIBLE is resolved true|true|any unresolved required operand is INCONCLUSIVE and cannot match|branch_match_status
66|G-FINAL/C04|G-FINAL|G-FINAL/C01;G-FINAL/C02;G-FINAL/C03|ALL|match BRANCH-A iff none of C01 C02 or C03 is MATCH|true|always MATCH after three prior nonmatches and record their unresolved statuses|branch_match_status
```

## Appendix B. Reduced Artifact Contract

### B.1 Schema language and shared records

Types are exact:

```text
ID = nonempty ASCII matching [A-Za-z0-9][A-Za-z0-9._:/-]*
STRING = NFC Unicode string
SHA256 = 64 lowercase hex characters
GIT40 = 40 lowercase hex characters
I64 = signed 64-bit JSON integer
U64 = unsigned 64-bit JSON integer
BOOL = JSON boolean
F64 = f64: plus 16 lowercase hex characters
TS = UTC RFC3339 YYYY-MM-DDTHH:MM:SS.ffffffZ
LIST<T> = ordered JSON array
MAP<K,V> = JSON object with unique UTF-8-byte-sorted keys
T? = T or null
DECIMAL53 = one digit, decimal point, exactly 53 fractional digits
DECIMAL30 = optional minus, one or more integer digits, decimal point, exactly 30 fractional digits
```

Shared records:

```text
CandidateSpec={
  candidate_id:ID,family:ID,comparison_group_id:ID,controlled_fingerprint:LIST<LIST<STRING|I64|F64>>,
  intervention_variable:ID,intervention_arm:ID,replication_id:ID,
  role:optimizer_arm|setup|irrelevant|redundant
}

BeliefSnapshot={
  belief_state_id:ID,lineage_id:ID,sequence:I64,
  probabilities:MAP<scientific_hypothesis_id,F64>,posterior_entropy:F64
}

CandidateScore={
  candidate_id:ID,public_effect:opens_pair|completes_pair|ineligible|stop,
  immediate_eig:F64,expected_total_eig:F64,expected_cost:F64,eig_per_cost:F64,
  rank:I64,ranking_reason:STRING
}

PlanningBranchTrace={
  planning_branch_id:ID,label:ID,probability:F64,evidence_lower:F64?,evidence_upper:F64?,
  posterior:MAP<scientific_hypothesis_id,F64>,posterior_entropy:F64,
  second_candidate_id:ID?,second_public_effect:opens_pair|completes_pair|ineligible|stop,
  second_eig:F64,second_cost:F64,terminal_entropy:F64,total_cost:F64,budget_feasible:BOOL
}

ControllerStageSpec={
  stage_order:I64,controller_stage_id:ID,allowed_event_types:LIST<event_type>,
  controller_stage_sha256:SHA256
}

DecisionBranchSpec={
  branch_order:I64,branch_id:ID,ordered_condition_ids:LIST<ID>,
  first_decisive_condition_id:ID,final_output:recommendation,
  required_operand_statuses:STRING,unreachable_condition_behavior:STRING,
  branch_sha256:SHA256
}

BranchTrace={
  branch_id:ID,ordered_condition_ids_evaluated:LIST<ID>,
  first_decisive_condition_id:ID,final_output:recommendation,
  required_operand_statuses:STRING,unreachable_condition_behavior:STRING,
  condition_results:LIST<branch_match_status>,gate_status:gate_status
}

MetricSet={
  true_probability:F64,top_scientific_hypothesis_id:scientific_hypothesis_id,
  top_probability:F64,prediction_correct:BOOL,confidently_wrong:BOOL,nll:F64,brier:F64,
  posterior_entropy:F64,conditional_brier_efficiency:F64?,
  end_to_end_brier_efficiency:F64?,decision_cost:F64,calibration_cost:F64,
  required_total_cost:F64,physical_cost_share:F64,best_observed_objective:F64?,
  matched_pairs:I64,redundant_selected:I64,irrelevant_selected:I64,
  outcome_experiments_completed:I64,setup_actions_completed:I64,budget_exhausted:BOOL,
  terminal_reason:terminal_reason
}

MissingnessCounts={
  n_total_pairs:I64,n_complete_pairs:I64,n_fixed_missing_only:I64,
  n_calibrated_missing_only:I64,n_both_missing:I64
}

ActionTuple={
  policy_scope:policy_scope,mechanism_id:mechanism_id,
  decision_contrast_id:ID,confirmatory_contrast_id:ID
}

DecisionBoolean={value:BOOL?,resolution_status:resolution_status,source_ids:LIST<ID>}

ActionabilityBlockResult={
  population_id:ID,operand_contrast_ids:LIST<ID>,required:BOOL,n_divergent:I64,
  n_present:I64,n_absent:I64,estimate:F64?,estimability_status:estimability_status,
  support_predicate_passed:BOOL,same_direction_predicate_passed:BOOL?,
  opposite_direction_predicate_passed:BOOL?,resolution_status:resolution_status
}

FormulaSpec={
  formula_order:I64,formula_id:ID,ordered_operand_ids:LIST<ID>,exact_operator:STRING,
  evaluation_order:STRING,null_propagation:STRING,inconclusive_propagation:STRING,
  comparison_boundary_behavior:STRING,output_type:STRING,formula_sha256:SHA256
}

GateConditionSpec={
  condition_order:I64,condition_id:ID,gate_id:ID,ordered_operand_ids:LIST<ID>,
  quantifier:ALL|ANY,predicate:STRING,expected_or_threshold:STRING,
  unresolved_behavior:STRING,result_enum:ID,condition_sha256:SHA256
}
```

No undeclared field is permitted. Every non-null `F64` must be finite. Every probability
map contains exactly the three scientific hypotheses, each value nonnegative, and sums to
one within `1e-12`.

### B.2 Canonical artifact registry: 13 artifacts

```text
order|filename|schema_version|format|primary key or singleton|row order
01|protocol_snapshot.json|protocol-snapshot/v4|JSON|singleton protocol_version|singleton
02|world_definitions.json|world-definitions/v2|JSON|singleton protocol_version|world registry order
03|arm_runs.jsonl|arm-run/v2|JSONL|run_id|(world_id,seed,budget,arm_id)
04|oracle_provenance.jsonl|oracle-provenance/v3|JSONL|oracle_key_id or oracle_use_id|key rows then use rows; declared tuple orders
05|calibration_estimates.jsonl|calibration-estimate/v2|JSONL|sigma_estimate_id|(world_id,seed,comparison_group_id)
06|trajectory_events.jsonl|trajectory-event/v3|JSONL|event_id|(run_id,sequence,event_type_order,event_id)
07|comparisons.jsonl|comparison/v3|JSONL|comparison_id|(policy_id,world_id,seed,budget)
08|contrast_results.csv|contrast-result/v3|CSV|contrast_id|BR-C then BR-J then BR-D numeric order
09|resampling_audit.jsonl|resampling-audit/v2|JSONL|resample_id|(record_type enum order,contrast_id,replicate_index)
10|gate_evaluations.json|gate-evaluation/v5|JSON|singleton evaluation_id|gate order
11|audit_results.json|audit-result/v3|JSON|singleton evaluation_id|audit order
12|run_manifest.json|run-manifest/v3|JSON|singleton evaluation_id|singleton
13|recommendation.json|recommendation/v4|JSON|singleton evaluation_id|created last
```

All artifacts use the Section 9.1 envelope. JSONL has one metadata line followed by data
rows. CSV repeats identical envelope fields in every row. Duplicate primary keys, missing
FKs, unknown fields, enum violations, nonfinite values, incorrect ordering, or count
mismatches are fatal validation errors. The optional Markdown report is not canonical and is
not part of this registry or count.

### B.3 Exact artifact schemas

#### 1. `protocol_snapshot.json`

Scientific fields:

```text
constants:MAP<ID,STRING|I64|F64|BOOL>
arms:LIST<{arm_order:I64,arm_id:ID,belief_model_id:ID,policy_id:ID}>
full_seeds:LIST<I64>
smoke_seeds:LIST<I64>
budget_registry:LIST<{budget_order:I64,budget_id:ID,budget:F64,budget_sha256:SHA256}>
ece_bin_edges:LIST<F64>
research_question_registry:LIST<{research_question_id:ID,question_sha256:SHA256,
  estimand_ids:LIST<ID>,contrast_ids:LIST<ID>,statistical_hypothesis_ids:LIST<ID>,
  gate_ids:LIST<ID>,descriptive_only_ids:LIST<ID>,decision_uses:LIST<ID>}>
scientific_hypothesis_registry:LIST<{hypothesis_order:I64,scientific_hypothesis_id:ID,
  statement:STRING,scientific_hypothesis_sha256:SHA256}>
statistical_hypothesis_registry:LIST<{order:I64,statistical_hypothesis_id:ID,
  contrast_id:ID,statistical_hypothesis_sha256:SHA256}>
metric_registry:LIST<{metric_order:I64,metric_id:ID,definition:STRING,
  direction:direction,metric_sha256:SHA256}>
estimand_registry:LIST<{estimand_order:I64,estimand_id:ID,definition:STRING,
  estimand_sha256:SHA256}>
mechanism_registry:LIST<{mechanism_order:I64,mechanism_id:ID,actionable:BOOL,
  mechanism_sha256:SHA256}>
population_registry:LIST<{population_id:ID,policy_scope:policy_scope,
  eligible_rows_rule:STRING,weighting_rule:STRING,population_sha256:SHA256}>
count_symbol_registry:LIST<{symbol_order:I64,symbol_id:ID,value_type:STRING,
  definition:STRING,count_symbol_sha256:SHA256}>
decision_symbol_registry:LIST<{symbol_order:I64,symbol_id:ID,value_type:STRING,
  producer_formula_id:ID,decision_symbol_sha256:SHA256}>
predicate_registry:LIST<{predicate_order:I64,predicate_id:ID,exact_predicate:STRING,
  predicate_sha256:SHA256}>
confirmatory_contrast_registry:LIST<ContrastSpec>
decision_contrast_registry:LIST<ContrastSpec>
descriptive_contrast_registry:LIST<ContrastSpec>
veto_registry:LIST<VetoSpec>
formula_registry:LIST<FormulaSpec>
gate_condition_registry:LIST<GateConditionSpec>
gate_registry:LIST<{gate_order:I64,gate_id:ID,gate_sha256:SHA256,formula_id:ID,
  required_source_ids:LIST<ID>,decision_use:STRING}>
audit_registry:LIST<{audit_order:I64,audit_id:ID,audit_sha256:SHA256,requirement:STRING}>
controller_stage_registry:LIST<ControllerStageSpec>
branch_registry:LIST<DecisionBranchSpec>
artifact_registry:LIST<{order:I64,filename:ID,schema_version:ID,format:ID,
  primary_key:STRING,row_order:STRING,artifact_sha256:SHA256}>
enum_registry:LIST<{enum_order:I64,enum_id:ID,ordered_values:LIST<ID>,
  enum_sha256:SHA256}>
schema_versions:MAP<ID,ID>
oracle_transform_version:ID
oracle_domain_count:I64
oracle_domain_expected_sha256:SHA256
oracle_conformance_generator:{
  generator_version:ID,decision_key_fields:LIST<ID>,calibration_key_fields:LIST<ID>,
  decimal_context:MAP<ID,STRING>,acklam_coefficients:MAP<ID,LIST<STRING>>,
  enumeration_partitions:LIST<ID>,canonical_line_fields:LIST<ID>,
  domain_count:I64,expected_sha256:SHA256
}
```

`ContrastSpec` is exactly:

```text
ContrastSpec={contrast_id:ID,contrast_sha256:SHA256,analysis_class:analysis_class,research_question_id:ID,
 policy_scope:policy_scope,population_scope:ID,metric_id:metric_id,
 estimand_id:estimand_id,paired_unit:paired_unit,eligibility_rule:eligibility_rule,
 numerator:formula_id,denominator:formula_id,missingness_rule:formula_id,
 direction:direction,ci_method:formula_id|method_mode,
 permutation_method:formula_id|method_mode,statistical_hypothesis_id:statistical_hypothesis_id?,
 holm_member:BOOL,gate_id:ID?,decision_use:LIST<ID>,source_contrast_id:ID?}

VetoSpec={veto_id:ID,veto_sha256:SHA256,formula_id:ID,decision_contrast_id:ID,policy_scope:policy_scope,
 mechanism_id:mechanism_id,population_scope:ID,own_confirmatory_contrast_id:ID,
 required_veto_contrast_id:ID,support_rule:STRING,effect_threshold:STRING,
 ci_rule:STRING,holm_rule:STRING}
```

The semicolon-delimited decision-use cells in A.2-A.5 become ordered JSON lists; literal
`null` becomes an empty list only for `decision_use` and remains JSON null for nullable ID
fields. Formula-local names such as `paired_rows` are typed positional bindings declared by
their formula row's `ordered_operand_ids`; they are not protocol IDs and cannot be referenced
outside that row. Every nonlocal ID in an operand list must resolve to exactly one snapshot
registry row. Operational fields excluded from scientific payload are
`design_checkpoint_commit:GIT40`, `design_git_blob_oid:GIT40`, and
`protected_source_sha256:MAP<ID,SHA256>`. Every registry in this document must appear
byte-equivalently; extra or missing rows fail A13. A13 also requires exactly 9 count symbols,
9 decision symbols, 43 formulas, 66 conditions, 44 gates, 3 budgets, 6 controller stages,
4 decision branches, 16 audits, 13 artifacts, and 31 enum rows; every ID reference must have exactly one
owner and duplicate ownership is fatal.

`schema_versions` is exactly the 13-entry filename-to-`schema_version` projection of the B.2
artifact registry in artifact order; no independent or extra version key is permitted.

`oracle_conformance_generator` is the exact machine-readable transcription of Section 8.6:
its two key-field arrays use the displayed key order; its Decimal map stores every context
setting and trap; coefficient arrays store the displayed decimal strings; partitions are
`["full_decision","full_calibration","smoke_decision","smoke_calibration"]`; canonical
line fields are `["namespace","serialized_key_hex","digest_hex","u_string","z_string"]`;
domain count is `117952`; and expected digest is
`0452652278d2670ac11f923a6919cae923b2baf88d2ea9b0356a5d4923dc706c`. This generator and
digest replace an unspecified sampled test-vector list and cover the full conformance domain.

#### 2. `world_definitions.json`

Scientific fields:

```text
candidate_catalog:LIST<CandidateSpec>
cost_catalogs:MAP<ID,MAP<ID,F64>>
midpoint_map:MAP<ID,F64>
worlds:LIST<{
  world_id:ID,block:ID,scientific_hypothesis_id:scientific_hypothesis_id,
  effect_size:F64,group_sigmas:MAP<ID,F64>,cost_catalog_id:ID,depth:I64,
  candidate_ids:LIST<ID>,initial_feasible_candidate_ids:LIST<ID>,
  setup_candidate_ids:LIST<ID>,comparison_group_ids:LIST<ID>,budget_ids:LIST<ID>
}>
world_registry_sha256:SHA256
```

World order is Section 8.4. `world_registry_sha256=H("world_registry",{candidate_catalog,
cost_catalogs,midpoint_map,worlds})`. IDs and costs must resolve to Sections 8.1-8.2.

#### 3. `arm_runs.jsonl`

Every data row has exactly:

```text
run_id:ID,comparison_id:ID,arm_id:ID,world_id:ID,seed:I64,budget_id:ID,budget:F64,
policy_id:policy_id,
belief_model_id:belief_model_id,lineage_id:ID,store_id:ID,
initial_probabilities:MAP<scientific_hypothesis_id,F64>,
final_probabilities:MAP<scientific_hypothesis_id,F64>,
scientific_hypothesis_id:scientific_hypothesis_id,metrics:MetricSet,
decision_ids:LIST<ID>,event_ids:LIST<ID>,calibration_prefix_ids:LIST<ID>,
run_status:run_status,terminal_reason:terminal_reason,ordered_decisions_sha256:SHA256,
reconciliation_sha256:SHA256,trajectory_sha256:SHA256
```

Exactly 36,864 rows. Lists preserve real chronological order. Fixed rows have no calibration
prefixes and zero calibration cost; calibrated rows have exactly three prefix IDs. Every
lineage and store ID is unique to one run. Canonical rows require `run_status=complete` and
forbid `terminal_reason=integrity_abort`.

#### 4. `oracle_provenance.jsonl`

Tagged row schemas are disjoint:

```text
OracleKeyRow={record_type:"oracle_key",oracle_key_id:ID,namespace:ID,world_id:ID,
 seed:I64,candidate_id:ID,comparison_group_id:ID?,intervention_arm:ID?,replication_id:ID,
 key_fields:LIST<STRING>,serialized_key_hex:STRING,digest:SHA256,u:DECIMAL53,z:DECIMAL30,
 revealed_observation:F64,outcome_digest:SHA256}

OracleUseRow={record_type:"oracle_use",oracle_use_id:ID,oracle_key_id:ID,run_id:ID,
 arm_id:ID,use_kind:calibration|decision,authorization_id:ID,decision_id:ID?,
 calibration_prefix_id:ID?}
```

Decision use requires non-null decision and null prefix; calibration use requires null
decision and non-null prefix. One key row exists only for a revealed observation. One
calibration key has six use rows; a decision key has one use per run that selected it.
All key rows precede all use rows. Key order is
`(namespace,world_id,seed,candidate_id,replication_id)`; use order is
`(oracle_key_id,run_id,use_kind)`. Policies receive no artifact handle.

#### 5. `calibration_estimates.jsonl`

Every row persists the previously dangling estimation target:

```text
sigma_estimate_id:ID,calibration_prefix_id:ID,world_id:ID,seed:I64,
comparison_group_id:ID,effect_ids:LIST<ID>,replication_ids:LIST<ID>,
source_candidate_pairs:LIST<LIST<ID>>,source_oracle_key_ids:LIST<ID>,
effect_values:LIST<F64>,sample_count:I64,sample_mean:F64,
sample_standard_deviation:F64,sigma_floor:F64,estimated_sigma:F64,
target_belief_model_id:belief_model_id,target_comparison_group_id:ID,
target_intervention_arms:LIST<ID>,physical_cost:F64,deployment_cost:F64,
deployed_run_ids:LIST<ID>,deployed_lineage_ids:LIST<ID>,
scientific_belief_updated:BOOL
```

Exactly 9,216 rows. Each row has five effects, five distinct replication IDs, ten candidates,
ten oracle keys, six deployed runs, `sample_count=5`, `sigma_floor=0.05`, and
`scientific_belief_updated=false`. Target model is
`replicated_noise_calibrated_gaussian`, target group equals `comparison_group_id`, target
arms are exactly `["adam","sgd"]`, and each deployed lineage corresponds positionally to
its deployed run. `sigma_estimate_id` is the FK target used by updates.

#### 6. `trajectory_events.jsonl`

Every data row is exactly:

```text
CanonicalEventRow={event_payload:CanonicalEventPayload,provenance_sha256:SHA256}
```

`event_payload` is the complete Section 9.2 canonical object with the exact variant,
required/nullable/forbidden-field table, controller-stage assignment, and payload schema
declared there. The stored `provenance_sha256` is the raw SHA-256 specified there and is not
part of its own preimage. Fixed rows have null `sigma_estimate_id`; calibrated experiment,
evidence, and update rows resolve it to the applicable comparison-group estimate, while the
other calibrated event types follow the explicit null rule above. Planning branches exist only inside a
decision payload's `planning_branch_tree`; they never become setup, experiment, evidence, or
belief-update events. Event type order is exactly
`decision,setup,experiment,evidence,belief_update,terminal`. The four public candidate lists
use candidate-catalog order and permit exact eligibility and planner replay.

#### 7. `comparisons.jsonl`

The sole paired-comparison identity is `comparison_id`; `pair_id` does not exist. The exact
shared record is:

```text
ComparisonShared={
  comparison_id:ID,policy_id:policy_id,world_id:ID,seed:I64,budget_id:ID,budget:F64,
  fixed_run_id:ID,calibrated_run_id:ID,fixed_sequence:LIST<ID>,
  calibrated_sequence:LIST<ID>,nll_difference:F64,brier_difference:F64,
  decision_cost_difference:F64
}

NondivergentComparison={record_type:"nondivergent",ComparisonShared,
  outcome_label:"nondivergent"}

DivergentComparison={record_type:"divergent",ComparisonShared,
  first_divergence_step:I64,fixed_candidate_id:ID,calibrated_candidate_id:ID,
  pre_divergence_fixed_belief:BeliefSnapshot,
  pre_divergence_calibrated_belief:BeliefSnapshot,
  first_action_divergent:BOOL,sequence_class:sequence_class,
  predicate_results:MAP<mechanism_id,BOOL>,primary_mechanism_id:mechanism_id,
  contributing_mechanism_ids:LIST<mechanism_id>,controller_stage_id:ID?,
  mechanism_row_without_outcome_sha256:SHA256,outcome_label:helped|hurt|mixed
}
```

Exactly 18,432 rows. The truth-free mechanism row and its hash are finalized before outcome
label, evaluator truth, or metric differences are joined. Nondivergent rows cannot carry any
divergence, belief, mechanism, predicate, classification-hash, or evaluator outcome field
other than literal `outcome_label="nondivergent"`.

#### 8. `contrast_results.csv`

Exact header after the five envelope columns:

```text
contrast_id,analysis_class,research_question_id,policy_scope,population_scope,metric_id,estimand_id,source_contrast_id,missingness_counts,n_present,n_absent,present_weight,absent_weight,left_value,right_value,left_denominator,right_denominator,estimate,ci_low,ci_high,usable_bootstrap_replicates,test_statistic,permutation_count,extreme_count,p_raw,p_adjusted,holm_rank,statistical_hypothesis_id,holm_member,result_status,estimability_status
```

Exact types are:

```text
contrast_id:ID,analysis_class:analysis_class,research_question_id:ID,
policy_scope:policy_scope,population_scope:ID,metric_id:metric_id,
estimand_id:estimand_id,source_contrast_id:ID?,missingness_counts:MissingnessCounts,
n_present:I64?,n_absent:I64?,present_weight:F64?,absent_weight:F64?,
left_value:F64?,right_value:F64?,left_denominator:F64?,right_denominator:F64?,
estimate:F64?,ci_low:F64?,ci_high:F64?,usable_bootstrap_replicates:I64,
test_statistic:F64?,permutation_count:I64?,extreme_count:I64?,p_raw:F64?,
p_adjusted:F64?,holm_rank:I64?,statistical_hypothesis_id:statistical_hypothesis_id?,
holm_member:BOOL,result_status:contrast_status,estimability_status:estimability_status
```

Exactly 122 rows exist: 66 confirmatory, 20 decision, 36 descriptive. Fields not applicable
to a row are null, never zero; actual zero counts and denominators use encoded zero. A
descriptive row has null CI/test/p/rank fields and bootstrap count zero. A decision row
copies estimate and CI from its source, has null test/p/rank fields, and bootstrap count
zero; its gate reads the source Holm fields. Non-estimable rows follow Section 4.1. For Holm
rows, permutation count is 10,000 when estimable. Threshold-only confirmatory rows have
null test/p/rank fields but retain their bootstrap count.

#### 9. `resampling_audit.jsonl`

Tagged variants share one discriminator and one key contract. The discriminator field is
typed `record_type:resample_record_type`; each variant fixes it to the literal enum value
shown:

```text
BootstrapRow={record_type:"bootstrap",resample_id:ID,contrast_id:ID,
 replicate_index:I64,seed_preimage_utf8_hex:STRING,seed_digest:SHA256,seed:U64,
 sampled_position_count:I64,completion_status:resample_completion_status,
 result_status:resample_result_status,failure_code:resample_failure_code?,
 sampled_seed_ids_sha256:SHA256,replicate_estimate:F64?}

SignFlipRow={record_type:"sign_flip",resample_id:ID,contrast_id:ID,
 replicate_index:I64,seed_preimage_utf8_hex:STRING,seed_digest:SHA256,seed:U64,
 sampled_position_count:I64,completion_status:resample_completion_status,
 result_status:resample_result_status,failure_code:resample_failure_code?,
 sign_vector_sha256:SHA256,replicate_statistic:F64?,extreme:BOOL?}
```

`resample_id` is the primary key and is exactly the Section 9.2 template using
`record_type`. The alternate key is `(contrast_id,record_type,replicate_index)`. Rows are
ordered first by `resample_record_type` enum order (`bootstrap`, then `sign_flip`), then
`contrast_id`, then `replicate_index`; duplicate primary or alternate keys fail.

For every row, `replicate_index` is an integer from 0 through 9999, its zero-padded text in
the owning formula is therefore `00000` through `09999`, and `seed` is the unsigned
big-endian first-eight-byte SHA-256 value defined by that formula. `seed_preimage_utf8_hex`
is lowercase hex of the complete formula-defined preimage bytes, and `seed_digest` is their
SHA-256. In canonical rows `sampled_position_count` is exactly 128 for both variants.
Bootstrap positions are sampled seed indices; sign-flip positions are the 128 ordered paired
seed blocks.

`completion_status="complete"` means the entire 128-position stream was generated.
`completion_status="failed"` is permitted only in temporary validation state with
`sampled_position_count` from 0 through 127, a variant digest over exactly that generated
prefix, `result_status="null"`, and `failure_code="stream_failure"`; it is a fatal A15 failure
and can never enter a canonical artifact. `result_status="valid"` requires
`completion_status="complete"`, a null `failure_code`, a finite non-null variant result, and
non-null `extreme` for sign flips.
`result_status="null"` requires null variant result and `extreme`, plus exactly one non-null
failure code. A completed statistical-null row may use only
`insufficient_complete_cases`, `zero_denominator`, or `nonfinite_result`. No other
nullability combination is valid.

Exactly 660,000 bootstrap rows precede exactly 640,000 sign-flip rows. Any failed stream,
wrong sampled-position count, seed mismatch, digest mismatch, ordering error, unknown field,
or count mismatch is fatal. Statistical null rows are counted and propagated only by
`bootstrap_10000` or `signflip_10000`; they never silently become valid results.

#### 10. `gate_evaluations.json`

Scientific fields:

```text
evaluation_id:ID
gates:LIST<GateEvaluation>
P_RAW:LIST<ActionTuple>
veto_evaluations:LIST<VetoEvaluation>
VETOED_TUPLES:LIST<ActionTuple>
P:LIST<ActionTuple>
ACTIONABILITY_COMPLETE:DecisionBoolean
VETO_COMPLETE:DecisionBoolean
CONTROLLER_CHANGE_NEEDED:DecisionBoolean
UNIQUE_ACTIONABLE_MECHANISM:DecisionBoolean
unique_mechanism_id:mechanism_id?
PPO_ELIGIBLE:DecisionBoolean
B_AUTHORIZED:DecisionBoolean
final_branch_id:ID
final_branch_trace:BranchTrace
final_gate_status:gate_status
recommendation:recommendation
decision_precedence:I64
```

Nested records are exact:

```text
GateEvaluation={gate_id:ID,gate_sha256:SHA256,gate_order:I64,formula_id:ID,
 formula_sha256:SHA256,conditions:LIST<GateConditionEvaluation>,gate_status:gate_status}

GateObservedValue={operand_id:ID,value_type:gate_value_type,
 boolean_value:BOOL?,integer_value:I64?,scalar_value:F64?,gate_status_value:gate_status?,
 contrast_status_value:contrast_status?,tuple_set_value:LIST<ActionTuple>?,
 veto_status_value:veto_status?,branch_match_status_value:branch_match_status?}

GateConditionEvaluation={condition_id:ID,condition_sha256:SHA256,condition_order:I64,
 gate_id:ID,ordered_operand_ids:LIST<ID>,quantifier:ALL|ANY,
 observed_values:LIST<GateObservedValue>,block_results:LIST<ActionabilityBlockResult>,
 resolution_status:resolution_status,gate_status_result:gate_status?,
 branch_match_status_result:branch_match_status?}

VetoEvaluation={veto_id:ID,veto_sha256:SHA256,source_tuple:ActionTuple,
 required_veto_contrast_id:ID,
 support_resolved:BOOL,present_count:I64,absent_count:I64,
 other_contrast_status:contrast_status,own_effect:F64?,other_effect:F64?,opposite_sign:BOOL?,
 effect_threshold_passed:BOOL?,ci_condition_passed:BOOL?,holm_condition_passed:BOOL?,
 veto_status:veto_status}
```

For each `GateObservedValue`, exactly the one value field named by `value_type` is non-null.
Observed values follow the condition registry's operand order exactly.
`block_results` is nonempty only for `F-ACTION`, contains exactly the policy's five literal
population IDs in Section 4.2 order, and preserves every unpooled point estimate and support
decision. Exactly one of the two condition-result fields is non-null, as selected by the
literal condition's `result_enum`. A `GateEvaluation.gate_status` is `INCONCLUSIVE` exactly
when its A.8 formula says so; no runtime default exists. The `G-FINAL` row's `gate_status`
equals `final_gate_status` and `final_branch_trace.gate_status`. Sets use policy then
mechanism order. There are
exactly 44 gates, 66 condition evaluations, and 20 veto evaluations. Every tuple in `P_RAW`
has one matching veto evaluation and `required_veto_contrast_id`; an `INCONCLUSIVE` veto is
excluded from `P` and leaves `VETO_COMPLETE` inconclusive.
Every action set is structured; strings cannot encode tuple membership.

#### 11. `audit_results.json`

Scientific fields:

```text
evaluation_id:ID
audits:LIST<{audit_id:ID,audit_order:I64,expected:STRING,observed:STRING,
 status:PASS|FAIL,audit_detail_sha256:SHA256}>
all_passed:BOOL
```

Operational provenance fields excluded from scientific payload are
`artifact_content_sha256:MAP<ID,SHA256>`,
`artifact_scientific_payload_sha256:MAP<ID,SHA256>`,
`historical_before_sha256:MAP<ID,SHA256>`, and
`historical_after_sha256:MAP<ID,SHA256>`. The two artifact maps contain artifacts 1 through
10 only, avoiding any report/audit cycle. Exactly 16 audits occur in Section 10.1 order.
For each row, `expected` is byte-identical to its Section 10.1 requirement text and
`observed` is exactly `PASS` or `FAIL`; detailed failure context belongs only in the
noncanonical validation failure artifact. A canonical directory therefore contains 16
`PASS` rows.

#### Optional derived `BROADER_REPLICATION_REPORT.md` (noncanonical)

If generated, the first line is:

```text
<!-- schema_version=broader-replication-report/v3 protocol_version=broader-closed-loop-replication/v1 source_design_sha256={SHA256} source_checkpoint_identifier={GIT40} canonical_record=false -->
```

Required level-two headings, in order:

```text
Protocol
Integrity Audits
RQ1 Pooled Belief Quality
RQ1 Pooled Closed-Loop Control
RQ1 Noise-Stratum Descriptions
RQ2 Divergence Frequency
RQ2 Conditional Harm
RQ3 Numerical Mechanisms
RQ4 Sequence Association
RQ5 Actionability and Vetoes
Costs and Objective Performance
A/B/C/D Decision
Negative Results
Limitations
Artifact Hashes
```

Every numeric claim references a canonical `contrast_id`, `gate_id`, or artifact primary
key. The report performs no independent calculation and is generated only after canonical
finalization. It is optional, has no scientific payload hash, is absent from the canonical
artifact registry and manifest hash maps, and is excluded from cross-implementation byte
equality. Its absence, prose, formatting, or byte differences cannot affect any gate,
integrity result, or A/B/C/D recommendation.

#### 12. `run_manifest.json`

Scientific fields are `evaluation_id:ID,status:"complete",expected_counts:MAP<ID,I64>,
observed_counts:MAP<ID,I64>,database_schema_version:I64`. Operational fields are
`implementation_commit:GIT40,implementation_tree_sha256:SHA256,
implementation_diff_sha256:SHA256,implementation_tree_clean:BOOL,started_at:TS,
completed_at:TS,dependency_versions:MAP<ID,STRING>,machine:MAP<ID,STRING>,
artifact_content_sha256:MAP<ID,SHA256>,artifact_scientific_payload_sha256:MAP<ID,SHA256>,
historical_before_sha256:MAP<ID,SHA256>,historical_after_sha256:MAP<ID,SHA256>,
recommendation_scientific_payload_sha256:SHA256`.

The artifact hash maps contain artifacts 1 through 11 only. The manifest has no self-hash
field and is never rewritten. `expected_counts` contains exactly:

```text
arm_runs=36864
fixed_calibrated_comparisons=18432
calibration_estimates=9216
calibration_effects=46080
calibration_observations=92160
calibration_oracle_use_rows=552960
oracle_conformance_keys=117952
confirmatory_contrasts=66
holm_hypotheses=64
decision_contrasts=20
descriptive_contrasts=36
contrast_rows=122
bootstrap_rows=660000
sign_flip_rows=640000
total_resampling_rows=1300000
count_symbol_registry_rows=9
decision_symbol_registry_rows=9
formula_registry_rows=43
gate_condition_registry_rows=66
gate_rows=44
branch_registry_rows=4
controller_stage_registry_rows=6
budget_registry_rows=3
audit_rows=16
canonical_artifacts=13
```

Dynamic decision, event, and selected-oracle-use counts are stored in `observed_counts` and
must reconcile exactly to the chronological trace FKs; they have no predeclared numeric
value.

#### 13. `recommendation.json`

Created last with scientific fields:

```text
evaluation_id:ID
recommendation:recommendation
decision_precedence:I64
branch_id:ID
branch_trace:BranchTrace
gate_status:gate_status
integrity_status:"PASS"
gate_evaluation_scientific_payload_sha256:SHA256
unique_mechanism_id:mechanism_id?
authorized_policy_scopes:LIST<policy_scope>
```

Operational field `run_manifest_content_sha256:SHA256` binds it to the immutable manifest.
For B, mechanism is non-null and scopes equal surviving `P` scopes; for A/C/D, mechanism is
null and scopes are empty. `gate_status` equals the `G-FINAL` row, `final_gate_status`, and
`branch_trace.gate_status`. `branch_id`, trace, recommendation, precedence, mechanism, and
scopes must match `gate_evaluations.json` exactly. Every recommendation therefore references
exactly one literal A.6 branch ID; an implementation-generated branch string is invalid.

### B.4 Scientific payload and validation rules

For JSON, scientific payload is canonical JSON containing only fields declared scientific.
For JSONL, it is the ordered data rows without metadata. For CSV, it is the exact header and
rows after removing five envelope columns. The optional report has no canonical scientific
payload. Operational fields above are the only exclusions from canonical artifacts.

Payload hashes are computed independently before envelopes are attached. An artifact content
hash is raw SHA-256 over its complete finalized byte sequence, including metadata envelope
and final LF. Cross-artifact hashes never enter another
artifact's scientific payload. The manifest records already-finalized artifacts 1-11; the
recommendation binds to the manifest without requiring a rewrite.

### B.5 Canonical foreign keys, uniqueness, and validation

The following is the complete relational contract. `->` names the sole FK target. A list FK
applies to every element. IDs not listed as FKs are either the row's primary key, a literal
registry ID, or a deterministic structural ID defined in Section 9.2.

| artifact | literal primary key | complete FKs and registry ownership | nested uniqueness and ordering | allowed missing references | validation failure |
| --- | --- | --- | --- | --- | --- |
| `protocol_snapshot.json` | singleton `protocol_version` | questions -> estimands, contrasts, statistical hypotheses, gates; statistical hypotheses -> confirmatory contrasts; decision symbols -> formulas; contrasts -> questions, populations, metrics, estimands, formulas, statistical hypotheses, gates, source contrasts, paired-unit, eligibility, and method enums; vetoes -> formulas, contrasts, populations, mechanisms; formulas -> nonlocal registry operands; conditions -> gates and nonlocal operands; gates -> formulas and conditions; controller stages -> event-type enum; branches -> conditions and recommendation enum; artifacts -> format enum; all owners are the literal snapshot registries | every literal ID is globally unique across registries and every content SHA unique within its registry; all declared order fields are unique contiguous integers; counts are exactly 9 count symbols, 9 decision symbols, 43 formulas, 66 conditions, 44 gates, 3 budgets, 6 stages, 4 branches, 16 audits, 13 artifacts, and 33 enums | formula-local positional bindings only; no unresolved nonlocal FK | fatal A13 registry failure; write only noncanonical validation failure and prohibit finalization |
| `world_definitions.json` | singleton `protocol_version` | candidate role -> candidate-role enum; world candidate/setup/group IDs -> its catalogs; cost ID -> cost catalog; hypothesis -> snapshot scientific hypotheses; budget IDs -> snapshot budgets | candidate, world, cost-catalog, fingerprint, comparison-group, and replication IDs unique in their declared scopes; exact Section 8 order | nullable candidate group/arm fields only where CandidateSpec role permits | fatal A02/A13 failure; no canonical output |
| `arm_runs.jsonl` | `run_id` | comparison -> comparisons; arm, policy, belief model, budget, status, terminal reason -> snapshot registries/enums; world -> worlds; truth label -> scientific hypotheses; decision/event IDs -> trajectory; calibration prefixes -> calibration estimates | unique `(arm_id,world_id,seed,budget_id)`, `lineage_id`, and `store_id`; decision and event lists chronological; prefix list group order; exactly one terminal event | empty calibration-prefix list for fixed arms only; no missing FK | fatal A07/A10/A12 failure; row and evaluation are invalid |
| `oracle_provenance.jsonl` | tagged `oracle_key_id` or `oracle_use_id` | key world/candidate/group -> worlds/catalog; use key -> key row; use run/arm -> arm run; decision -> decision event; prefix -> calibration estimate; use kind -> enum | unique key tuple and unique `(authorization_id,oracle_key_id,run_id)`; one use row per authorization; keys then uses in B.2 order | key group/arm only where key namespace permits; exactly one of decision or prefix by use kind | fatal A04/A05 failure; no policy-visible handle and no canonical output |
| `calibration_estimates.jsonl` | `sigma_estimate_id` | prefix world/group/candidates -> world catalogs; oracle keys -> key rows; deployed runs/lineages -> arm runs and their lineages | unique prefix and `(world_id,seed,comparison_group_id)`; exactly five unique effects/replications; positional candidate pairs, keys, runs, and lineages | none | fatal A08/A10 failure; calibrated runs invalid |
| `trajectory_events.jsonl` | `event_id` | common run/comparison/world/budget/arm/policy/stage -> owning rows/registries; candidate -> world catalog; decision -> decision payload; oracle key/use -> oracle rows; evidence sources -> experiment events in same run; update evidence -> evidence event; sigma -> calibration estimate; beliefs/lineage -> same arm run | unique `(run_id,sequence,event_type)`; unique structural decision/setup/experiment/evidence/update IDs; unique `(decision_id,planning_branch_id)`; one terminal event last; event order and stage/type compatibility exact | only Section 9.2 typed nulls; fixed sigma FK null and calibrated sigma FK required where declared | fatal payload, provenance, FK, duplicate, or stage failure; row and evaluation invalid |
| `comparisons.jsonl` | `comparison_id` | fixed/calibrated runs -> arm runs carrying same comparison; world -> worlds; policy/budget -> snapshot; beliefs/lineages -> referenced runs; mechanisms/stage -> snapshot registries | unique `(policy_id,world_id,seed,budget_id)`; fixed and calibrated run IDs distinct; sequences chronological; predicate map has each actionable mechanism once in mechanism order | divergence-only fields absent on nondivergent rows; controller stage nullable only when no stage classification exists | fatal A07/A13 failure; comparison invalid |
| `contrast_results.csv` | `contrast_id` | row -> exactly one snapshot contrast; question/population/metric/estimand/statistical hypothesis/source contrast -> snapshot registries | exactly 122 rows in C, J, D order; missingness partitions reconcile; one row per contrast and no extra row | only B.3 status-governed null fields; no missing FK | fatal A13/A15 failure; gates cannot run |
| `resampling_audit.jsonl` | `resample_id` | bootstrap `contrast_id` -> one of 66 confirmatory contrast rows; sign-flip `contrast_id` -> one of 64 `holm_member=true` confirmatory rows; `record_type`, `completion_status`, `result_status`, and `failure_code` -> their sole snapshot enums; seed and stream fields -> the contrast's `bootstrap_10000` or `signflip_10000` formula | unique `(contrast_id,record_type,replicate_index)`; record-type enum order then contrast ID then replicate index; exactly 660000 bootstrap rows then 640000 sign-flip rows; exactly 128 sampled positions per row | result fields null only when `result_status="null"` and `failure_code` is non-null; `failure_code` null only when `result_status="valid"`; no seed, digest, key, count, or discriminator is nullable | failed completion, seed/preimage/digest mismatch, wrong count/order, invalid nullability, unknown discriminator, or other contract failure is fatal A15; statistical-null rows propagate through their sole formula and canonical finalization still requires A15 PASS |
| `gate_evaluations.json` | singleton `evaluation_id` | gate/formula/condition/veto/branch IDs -> snapshot; observed operands -> contrasts, gates, audits, count symbols, decision symbols, vetoes, or prior final conditions; action tuples -> J/C contrasts and mechanisms; every gate-valued field -> sole `gate_status` enum | 44 unique gates in order; exactly 66 unique condition IDs; 20 unique veto IDs; one veto per eligible tuple; sets policy/mechanism ordered; one literal branch trace; `G-FINAL.gate_status`, `final_gate_status`, and `final_branch_trace.gate_status` identical | only typed unresolved values; unresolved FK is never allowed; B-only unique mechanism may be null outside B | fatal A13 or decision-contract failure; recommendation cannot be created |
| `audit_results.json` | singleton `evaluation_id` | audit IDs -> snapshot audits; artifact map keys -> artifact registry | exactly 16 audits in order; artifact maps exactly artifacts 1-10; historical maps exact Section 9.3 universes | none in canonical PASS output | any FAIL prevents finalization; failure detail is noncanonical only |
| `run_manifest.json` | singleton `evaluation_id` | evaluation -> snapshot; artifact map keys -> artifacts 1-11; count keys -> count symbols or exact B.3 expected-count keys | every expected key occurs once; observed dynamic IDs/counts reconcile to source rows; maps UTF-8 key ordered | none | fatal A16 failure; manifest and recommendation are not created |
| `recommendation.json` | singleton `evaluation_id` | evaluation -> immutable manifest/snapshot; gate payload hash and `gate_status` -> `G-FINAL` in gate artifact; branch -> branch registry; trace conditions -> condition registry; mechanism/policy scopes -> registries | exactly one branch and trace; branch output equals recommendation; recommendation `gate_status`, trace `gate_status`, and `G-FINAL.gate_status` identical; B scopes are unique and ordered; created once and last | mechanism null and scopes empty for A/C/D only | any mismatch is fatal A13/A16 failure; canonical artifacts are never rewritten |

Enum ownership is exclusive to `protocol_snapshot.json`: every enum-typed field resolves to
one `enum_registry` record, and literal tagged values such as record types are closed by
their schema. No artifact may define or extend an enum locally.

Event nullability is exactly the Section 9.2 `CanonicalEventPayload` table: all common keys
are present, forbidden common keys are JSON null, and keys from another event-specific
payload are absent. A row validates against exactly one of the six payload schemas. The same
closed tagged-union rule applies to oracle, comparison, and resampling rows.

A13 performs an exhaustive symbol-resolution pass before any row-level analysis. It visits
every count-symbol reference, decision-symbol reference, formula ID, condition ID, branch ID,
and controller-stage ID in canonical order; each must resolve to one and only one owner row.
Zero or multiple owners is a fatal FK error. Formula-local positional bindings are checked
against their owning formula row and cannot escape that scope.

All canonical row ordering is the exact B.2 ordering after FK resolution. Unknown fields,
missing fields, an unresolved FK, duplicate primary or alternate key, wrong nested order,
enum violation, invalid null, count mismatch, nonfinite value, registry-SHA mismatch,
payload-hash mismatch, reconciliation mismatch, or post-finalization byte mismatch fails
validation. Failure writes only the Section 11 noncanonical artifact and prohibits creation
or rewriting of every canonical artifact.

## Appendix C. Closure Ledger

Every blocker from all four read-only audits is represented exactly once. All thresholds and
scientific-matrix flags remain `no`: no arm, seed, world, budget, outcome generator, policy,
belief model, or numerical scientific threshold changed. A row may be `CLOSED` only when its
referenced contract is present in this document; any `OPEN` row would prohibit freezing.

```text
blocker_id|source_audit_number|original_ambiguity|final_resolution|affected_ids|verification_section|threshold_changed|scientific_matrix_changed|status
A1-01|1|trajectory arithmetic implicit|all products frozen in Section 1.2|MATRIX-COUNTS|1.2|no|no|CLOSED
A1-02|1|prior seed overlap not enumerated|exact 1000..1127 list digest and disjoint schedules|FULL-SEEDS;SMOKE-SEEDS|1.2|no|no|CLOSED
A1-03|1|group baseline did not determine arm means|symmetric midpoint equations frozen|WORLD-GENERATOR|8.3|no|no|CLOSED
A1-04|1|candidate controls and replications incomplete|literal candidate and calibration catalogs frozen|CANDIDATE-CATALOG|8.1-8.2|no|no|CLOSED
A1-05|1|oracle byte and normal conversion open|exact Decimal transform enumeration and digest frozen|ORACLE-CONFORMANCE|8.6|no|no|CLOSED
A1-06|1|world suite described as globally balanced|fractional margins and supported scopes explicit|WORLD-REGISTRY|8.4|no|no|CLOSED
A1-07|1|asymmetric comparator unmatched|only cost worlds versus matched d2 Adam and SGD comparators|POP-ASYM-IG;POP-ASYM-LA|4.2|no|no|CLOSED
A1-08|1|weighting appeared to impute missing cells|unregistered interactions removed and literal populations retained|POPULATION-REGISTRY|4.2|no|no|CLOSED
A1-09|1|opposite effect lacked boundary|existing 0.10 and 0.15 boundaries explicit|F-ACTION;V001-V020|5.2;6.2-6.3|no|no|CLOSED
A1-10|1|supported block undefined|literal five-block lists and 20 5 5 support frozen|ACTIONABILITY-BLOCKS|4.2;6.2;A.7-A.9|no|no|CLOSED
A1-11|1|controller-stage actionability used judgment|ten-item truth-free allowlist frozen|MECHANISM-REGISTRY|6.1;A.6|no|no|CLOSED
A1-12|1|Holm grouping ambiguous|HOLM-64 retains all 64 ordered members including non-estimable members with arithmetic p_for_holm 1.0 stored INCONCLUSIVE status and literal-order ties; no member exclusion or UTF-8 ID sort remains|HOLM-64;STATISTICAL-HYPOTHESIS-REGISTRY|5.3;A.6;A.8;10.1 A15|no|no|CLOSED
A1-13|1|sign-flip details incomplete|signflip_10000 alone freezes the contrast-ID pipe-delimited preimage first-eight-byte big-endian seed SplitMix64 low-bit stream label semantics inclusive absolute test and no per-seed digest alternative|signflip_10000;resampling_audit.jsonl|5.3;A.8 formula 23;B.3 artifact 9;10.1 A15|no|no|CLOSED
A1-14|1|ECE permuted after aggregation|raw paired rows swapped and ECE rebuilt|BQ.IG.ECE;BQ.LA.ECE|5.3;A.8|no|no|CLOSED
A1-15|1|bootstrap generator and percentile open|bootstrap_10000 alone freezes the contrast-ID JSON preimage first-eight-byte big-endian seed SplitMix64 INDEX128 stream valid-replicate R quantiles zero-based indices null exclusion and 9500 support rule|bootstrap_10000;resampling_audit.jsonl|5.4;A.8 formula 22;B.3 artifact 9;10.1 A15|no|no|CLOSED
A1-16|1|CI and p-value roles conflated|CI and Holm predicates stored separately|GATE-CONDITION-REGISTRY|A.8-A.9;B.3|no|no|CLOSED
A1-17|1|interpretation outcomes overlapped|one exhaustive first-match decision table selects B only for B_AUTHORIZED PASS and selects C when controller change is needed and B_AUTHORIZED is FAIL or INCONCLUSIVE|G-FINAL|7.2;A.6;A.8 formula 43;A.9|no|no|CLOSED
A1-18|1|depth three appeared to change horizon|public real-state adapter only|DEPTH-THREE-ADAPTER|8.5|no|no|CLOSED
A1-19|1|artifact schemas incomplete|13 canonical typed schemas complete canonical event variants and six-column relational appendix|CANONICAL-ARTIFACT-REGISTRY|B.1-B.5|no|no|CLOSED
A1-20|1|source checkpoint undefined|protected commit and 13 file hashes exact|SOURCE-FREEZE|9.4|no|no|CLOSED
A1-21|1|self-hash cycle|manifest and recommendation use one-way binding|FINALIZATION|11;B.4|no|no|CLOSED
A1-22|1|runtime choices could reopen science|worker order operational and scientific payload invariant|A06-DETERMINISM|10.1;12|no|no|CLOSED
A2-01|2|policy pooling in mechanism gates|all mechanism and action rows policy-specific|BR-J001-BR-J020|A.2-A.4|no|no|CLOSED
A2-02|2|primary versus contributing presence open|primary equality only and other views excluded|MECHANISM-PRESENCE|6.1;A.6|no|no|CLOSED
A2-03|2|valid contrast universe and salts open|122 literal contrast rows and contrast-ID resampling identity|CONTRAST-REGISTRY|A.1-A.5|no|no|CLOSED
A2-04|2|353-cell grid incomplete|grid removed and 22 literal populations retained|POPULATION-REGISTRY|4.2|no|no|CLOSED
A2-05|2|identifier namespaces overloaded|literal registry IDs four hash-derived runtime IDs and deterministic structural templates separated|ID-SYSTEM|9.2;A.6-A.9|no|no|CLOSED
A2-06|2|undefined rates could become zero|complete-case and zero-denominator rule exact|MISSINGNESS|4.1;A.8|no|no|CLOSED
A2-07|2|one oracle row lost multiple uses|normalized oracle key and use rows|oracle_provenance.jsonl|B.3.4;B.5|no|no|CLOSED
A2-08|2|ID and provenance preimages missing|v3 exact ID preimages complete canonical event preimage and content hashes frozen|HASH-REGISTRY|9.2;B.3.6|no|no|CLOSED
A2-09|2|payload and audit finalization circular|forward A01-A16 finalization with no iteration|A16-FINALIZATION|11|no|no|CLOSED
A2-10|2|normal transform platform-dependent|Decimal Acklam and full-domain digest exact|ORACLE-CONFORMANCE|8.6|no|no|CLOSED
A2-11|2|aggregate schema could not represent scopes|one result row per literal contrast|contrast_results.csv|B.3.8|no|no|CLOSED
A2-12|2|design and source commitments incomplete|committed design SHA blob and protected hashes required|SOURCE-COMMITMENTS|9.4;B.3.1|no|no|CLOSED
A3-01|3|RQ wording exceeded gates|RQ1 and RQ2 split into literal confirmatory and descriptive questions|RESEARCH-QUESTION-REGISTRY|2.1-2.9|no|no|CLOSED
A3-02|3|one passing mechanism plus inconclusive alternative could yield B|F-B-AUTHORIZATION gives any required inconclusive authorization or veto operand strict precedence over P emptiness and all P-derived failures so B_AUTHORIZED remains INCONCLUSIVE and Branch B cannot match|G-ACTIONABILITY-COMPLETE;F-B-AUTHORIZATION|6.2-6.3;7;A.7-A.9|no|no|CLOSED
A3-03|3|veto support and weighting undefined|20 literal mirrored veto rows give every P_RAW tuple exactly one VETOED NOT_VETOED or INCONCLUSIVE status; P retains only NOT_VETOED tuples and F-B-AUTHORIZATION preserves any required inconclusive veto|V001-V020;F-VETO-COMPLETE;F-P;F-B-AUTHORIZATION|6.3;A.4;A.8-A.9|no|no|CLOSED
A3-04|3|under-support was both FAIL and INCONCLUSIVE|all missing and under-support is INCONCLUSIVE|MISSINGNESS|4.1;5.1;A.8|no|no|CLOSED
A3-05|3|nullable paired metrics lacked a rule|five complete-case counts and no zero imputation|MissingnessCounts|4.1;B.3.8|no|no|CLOSED
A3-06|3|generated grid was not materializable|replaced by 122 literal rows|CONTRAST-REGISTRY|A.1-A.5|no|no|CLOSED
A3-07|3|snapshot lacked registries and sets were strings|protocol snapshot contains all literal registries including 43 sole formula rows 66 sole condition rows 33 enums stages and branches; gate artifact uses structured action sets and gate_status through G-FINAL and BranchTrace|protocol_snapshot.json;gate_evaluations.json;F-DECISION-TABLE|5;A.6-A.9;B.1;B.3 artifacts 1 and 10|no|no|CLOSED
A3-08|3|sigma target event nullability details hash and history incomplete|targets lineages tagged variants hashes and universe exact|calibration_estimates.jsonl;trajectory_events.jsonl|9.2-9.4;B.3.5-B.3.6|no|no|CLOSED
A3-09|3|resampling seed and status lacked artifact|1.30M-row resampling audit uses only record_type and stores exact preimage digest U64 seed sampled-position count completion status valid-or-null result status and closed failure code|resampling_audit.jsonl;bootstrap_10000;signflip_10000|5.3-5.4;A.8 formulas 22-23;B.2;B.3 artifact 9;B.5|no|no|CLOSED
A3-10|3|failure handling rewrote outputs|failure noncanonical and canonical bytes immutable|FINALIZATION|11|no|no|CLOSED
A3-11|3|seed identities and metadata envelope conflicted|contrast-only resampling identity and one envelope|RESAMPLING;METADATA|5.3-5.4;9.1|no|no|CLOSED
A3-12|3|bootstrap workload implausible|66 bootstraps and 84.48M sampled positions|BOOTSTRAP-PROTOCOL|5.4;12|no|no|CLOSED
A4-01|4|undefined frozen stopping outcome|public feasible and affordable sets plus three terminal reasons frozen|TERMINATION;terminal_reason|1.4;B.3.3;B.3.6|no|no|CLOSED
A4-02|4|planner mismatch mixed with scientific mechanisms|planner replay is A09 integrity-only and BR-C033 BR-C045 removed|A09-PLANNER-AND-EVIDENCE;BR-C033;BR-C045|6.1;10.1|no|no|CLOSED
A4-03|4|MISS-DIVERGENT20 support ambiguous|BR-C011 and BR-C014 require 20 helped and 20 hurt|MISS-DIVERGENT20;BR-C011;BR-C014|5.1;A.2;A.8|no|no|CLOSED
A4-04|4|five actionability blocks and compound predicate implicit|literal population lists unpooled block records and predicate fields frozen|ACTIONABILITY-BLOCKS;GateCondition|4.2;6.2;A.8-A.9;B.3.10|no|no|CLOSED
A4-05|4|research-question mappings used ranges and wildcards|ten literal ordered mapping records frozen|research_question_registry|2.9;B.3.1|no|no|CLOSED
A4-06|4|registry IDs conflicted with hash-derived IDs|registry IDs are literal while runtime and content hashes use separate exact fields|ID-SYSTEM|9.2;A.6-A.9|no|no|CLOSED
A4-07|4|comparison reconciliation and named hash payloads incomplete|comparison ID reconciliation and complete six-variant canonical event hash payloads are exact|comparison_id;reconciliation_sha256;HASH-REGISTRY|9.2;B.3.6|no|no|CLOSED
A4-08|4|artifact FK types uniqueness and sigma lineage incomplete|all 13 schemas have complete B.5 keys FKs types enum ownership ordering uniqueness nullability and fatal behavior; resampling uses only record_type with complete seed and result provenance and gate artifacts use only gate_status|CANONICAL-ARTIFACT-REGISTRY;resampling_audit.jsonl;gate_evaluations.json|B.1-B.5;A.8 formulas 22-24 and 43|no|no|CLOSED
A4-09|4|free Markdown was canonical|report optional derived and excluded from equality and decisions|BROADER_REPLICATION_REPORT.md|B.3 optional report;B.4|no|no|CLOSED
A4-10|4|A16 depended on recommendation it validated|acyclic finalization computes an in-memory F-DECISION-TABLE result; A16 verifies the dedicated inconclusive-first F-B-AUTHORIZATION rule all gate_status and BranchTrace fields before G-INTEGRITY manifest and immutable recommendation are materialized without reading a later artifact|A16-FINALIZATION;G-INTEGRITY;G-FINAL;F-B-AUTHORIZATION;F-DECISION-TABLE|10.1 A16;11;A.8 formulas 42-43;B.3 artifacts 10 and 13|no|no|CLOSED
A4-11|4|closure rows lacked explicit status|57-row nine-field ledger with verification sections and CLOSED or OPEN status|CLOSURE-LEDGER|Appendix C|no|no|CLOSED
```

## Final Protocol Status

- Files modified by this closure pass: `BROADER_REPLICATION_DESIGN.md` only.
- Arms: 4.
- Full seeds: 128, exactly `1000..1127`.
- Worlds: 24.
- Budgets: 3.
- Arm trajectories: 36,864.
- Fixed/calibrated comparisons: 18,432.
- Calibration effects and observations: 46,080 and 92,160.
- Smoke trajectories: 384.
- Oracle conformance keys: 117,952.
- Confirmatory statistical hypotheses: 64 in one Holm family.
- Confirmatory contrasts: 66, including two threshold-only RQ3 contrasts.
- Decision contrasts: 20.
- Descriptive contrasts: 36.
- Total literal contrast rows: 122.
- Veto completeness: required for B; every `P_RAW` tuple has exactly one status, `P`
  contains only `NOT_VETOED` tuples, and any required `INCONCLUSIVE` veto makes
  `B_AUTHORIZED=INCONCLUSIVE` before `P` emptiness or another `P`-derived predicate can
  become `FAIL`. Branch B is impossible in that state; when controller change is needed,
  Branch C is selected.
- Literal registries added by closure: 9 count symbols, 9 decision symbols, 43 formulas,
  66 gate conditions, 44 gates, 4 A/B/C/D branches, and 6 controller stages.
- Canonical artifacts: 13 machine-readable files; Markdown is optional and noncanonical.
- Mandatory audits: 16.
- Bootstrap replicates: 660,000.
- Sign-flip replicates: 640,000.
- Total resampling rows: 1,300,000.
- Estimated runtime: 45-180 minutes single desktop CPU; 15-60 minutes deterministic
  bounded parallel execution; 5-8 GB free disk.
- Scientific blockers: all closed prospectively.
- Statistical blockers: all closed prospectively.
- Reproducibility blockers: all closed prospectively.
- Canonical provenance: every real event hashes the complete typed six-variant event payload;
  no prose `event_content` or implementation-defined preimage remains.
- Relational contract: all 13 artifacts have explicit keys, FKs, ownership, nested
  uniqueness, allowed missing references, and fatal validation behavior.
- Symbol resolution: every nonlocal count, decision, formula, condition, gate, veto, branch,
  controller-stage, audit, contrast, hypothesis, metric, estimand, mechanism, artifact, and
  enum ID resolves to exactly one literal owner row.
- Operational concerns only: implementation effort, deterministic parallel throughput,
  temporary disk headroom, committing this design checkpoint, and output-directory exclusion
  from version control.
- Outcome status: no smoke or scientific replication result was generated.
- Closure status: all 57 ledger rows are `CLOSED`; ready for one final read-only freeze audit.
