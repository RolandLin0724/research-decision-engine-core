# Research Reasoning Architecture and Research Decision Engine Core

## 1. Architectural Positioning

The project has two layers with a one-way dependency.

### Research Reasoning Architecture

Research Reasoning Architecture is the general, domain-independent framework for
representing scientific reasoning over time. It defines the meanings and relationships of
hypotheses, experiments, observations, evidence, belief states, decisions, objectives,
budgets, and memory. It also defines the provenance and versioning requirements that make a
reasoning trace reproducible and auditable.

This layer is an architecture and set of contracts, not a scientific domain, optimizer, or
standalone product. It does not prescribe how a hypothesis must be encoded, which statistical
model must update a belief, or which utility function must choose an experiment.

### RDE Core

RDE Core is the first concrete application built on top of Research Reasoning Architecture. Its
responsibility is narrower: given the current research state, available experiments, and limited
time, compute, and experimental budget, choose what to do next and record why.

The current synthetic machine-learning benchmark is an initial RDE Core domain. It
provides cheap experiments, controlled observations, hidden benchmark truth, and deterministic
replay so that decision policies can be compared. Machine-learning parameter spaces and
synthetic objectives are application details, not assumptions of the general architecture.

The dependency direction is strict: RDE Core may depend on Research Reasoning Architecture, but
the general architecture must not depend on RDE Core. Research
Memory, Research Planner, Research Simulator, and Research Auditor can later reuse the same
architecture without inheriting machine-learning or optimization semantics.

## 2. Core Scientific Loop

The core loop is:

**Hypothesis -> Experiment -> Evidence -> Belief Update -> Decision -> Next Experiment**

This is a cycle of versioned state transitions, not a pipeline that turns data directly into
truth. Each stage preserves its inputs by reference and produces an auditable output. Branches,
competing hypotheses, inconclusive evidence, stopping decisions, and revised objectives are all
valid outcomes.

| Stage | Purpose | Information entering | Information leaving |
| --- | --- | --- | --- |
| Hypothesis | State a scoped, testable claim and the observations expected if it is more or less credible. | Research objective, prior memory, domain assumptions, existing beliefs, and unresolved questions. | A versioned hypothesis, its scope and assumptions, testable predictions, relevant alternatives, and initial uncertainty. |
| Experiment | Create and execute a controlled intervention or measurement that can bear on one or more hypotheses. | Target hypotheses, predicted evidence patterns, design choices, feasibility constraints, prior decision, and available budget. | A registered plan, an immutable account of what actually ran, raw observations, incurred cost, and any deviations from the plan. |
| Evidence | Interpret observations in relation to hypotheses without declaring them to be knowledge or truth. | Experiment record, raw observations, measurement quality, context, and a declared domain-specific interpretation rule. | Traceable evidence items that support, challenge, distinguish, or fail to distinguish hypotheses, with strength, uncertainty, and caveats. |
| Belief Update | Revise the current epistemic state using admissible evidence and an explicit update rule. | Previous belief-state version, new evidence, dependency assumptions, and the chosen update method. | A new belief-state version, the change from the prior state, remaining uncertainty, and a reproducible update rationale. |
| Decision | Commit to an action, defer, or stop in light of scientific goals and resource constraints. | Current beliefs, research objective, candidate actions, expected scientific value, risks, and remaining budget. | A decision record naming the selected action or stopping outcome, considered alternatives, expected cost and value, uncertainty, and reasons. |
| Next Experiment | Materialize an experiment decision and begin the next loop iteration. | Decision record, selected design, execution constraints, and budget reservation. | A new experiment identity, its target hypotheses, its predeclared plan, and reserved resources. No evidence exists until it is executed and interpreted. |

The separations in this loop are substantive. An experiment produces observations. An evidence
rule gives those observations meaning relative to a claim. A belief update combines evidence
with a prior state. A decision uses beliefs but also incorporates objectives, costs, risk, and
stopping criteria. None of these transformations should be implicit.

## 3. Core Abstractions

### Hypothesis

- **Responsibility:** Represent a scoped and falsifiable claim about the world, including the
  conditions under which it applies and the observable consequences that could distinguish it
  from alternatives.
- **Inputs:** Research question, objective, domain vocabulary, assumptions, prior memory,
  competing explanations, and a proposed set of predictions.
- **Outputs:** Stable hypothesis identity, immutable version, scope, assumptions, predictions,
  relationships to alternatives, and references to the evidence and beliefs that concern it.
- **Invariants:** Identity is stable across revisions; each version is immutable; scope and
  assumptions are explicit; at least one observation can bear on the claim; status is not part
  of the claim's text; revision creates a new version instead of rewriting history.
- **Failure modes:** A claim is vague or unfalsifiable; assumptions remain hidden; the claim is
  rewritten after seeing results; alternatives are omitted; different claims share an identity;
  a hypothesis is treated as true merely because it is active.

### Experiment

- **Responsibility:** Represent a planned intervention or measurement and the corresponding
  execution, while preserving the distinction between what was intended and what occurred.
- **Inputs:** Target hypotheses, design variables, controls, measurement protocol, expected
  evidence, feasibility constraints, decision reference, and budget estimate.
- **Outputs:** Stable experiment identity, predeclared plan, execution status, actual conditions,
  raw observations, deviations, artifacts, and actual resource cost.
- **Invariants:** The plan is fixed before its outcomes are interpreted; planned and actual
  conditions remain distinguishable; repeated executions receive distinct execution identities;
  every observation retains its experiment provenance; cancellation and failure are valid
  outcomes rather than missing history.
- **Failure modes:** Outcome-aware redesign is recorded as if predeclared; failed runs disappear;
  materially different conditions reuse one identity; measurements lack units or context;
  execution cost is not recorded; a candidate configuration is confused with an executed run.

### Evidence

- **Responsibility:** Express how one or more observations bear on one or more hypotheses under a
  declared interpretation rule.
- **Inputs:** Raw observations, experiment provenance, measurement quality, relevant controls,
  domain assumptions, and an evidence-extraction or likelihood rule.
- **Outputs:** Evidence identity, source experiment references, affected hypotheses, direction or
  discriminating effect, strength, uncertainty, caveats, and interpretation-rule version.
- **Invariants:** Evidence is traceable to exact experiments and observations; raw data is not
  overwritten by interpretation; inconclusive or conflicting evidence is representable;
  evaluator-only truth is never operational evidence; the same evidence item is not counted
  twice in one belief lineage.
- **Failure modes:** Evidence is detached from provenance; correlation is double-counted as
  independent support; a result is cherry-picked; measurement quality is ignored; benchmark
  truth leaks into reasoning; an interpretation is presented as a raw observation.

### Belief State

- **Responsibility:** Represent the current, explicitly uncertain and revisable epistemic state
  over hypotheses and other research claims.
- **Inputs:** Previous belief-state version, admissible evidence, update-rule version, dependency
  assumptions, and declared priors or initial state.
- **Outputs:** A new immutable belief-state version, belief values with defined semantics,
  uncertainty, evidence lineage, deltas from the prior state, and unresolved conflicts.
- **Invariants:** Uncertainty is explicit; the representation semantics are declared; the state is
  internally coherent under those semantics; unknown and inconclusive states are allowed;
  updates never mutate prior versions; every change can be reconstructed from its prior state
  and evidence.
- **Failure modes:** Confidence is stored without meaning; beliefs collapse prematurely to binary
  truth; contradictory evidence cannot revise a conclusion; evidence is double-counted; a prior
  or update rule is hidden; incomparable hypotheses are incorrectly normalized together.

### Reasoner

- **Responsibility:** Apply declared reasoning procedures to produce belief updates and decision
  proposals from the current research state. The Reasoner owns transformation logic, not truth,
  experiment execution, or durable memory.
- **Inputs:** Research objective, hypotheses, evidence, belief state, candidate experiments,
  budget, constraints, domain adapters, procedure configuration, and explicit random seed when
  stochastic behavior is allowed.
- **Outputs:** Proposed belief updates, ranked or filtered actions, decision recommendations,
  reasons, assumptions, and diagnostics sufficient for replay.
- **Invariants:** Identical inputs and seed produce identical outputs; only declared inputs are
  used; reasons refer to actual evidence, objectives, and constraints; inference is separate from
  execution; procedure and model versions are recorded.
- **Failure modes:** Hidden state changes the result; a reason is generated after the decision and
  does not explain it; benchmark truth or future data leaks in; domain assumptions masquerade as
  general logic; an opaque score has no declared meaning; stochastic output cannot be replayed.

### Decision

- **Responsibility:** Record an auditable commitment to an action, deferral, or stop condition at a
  particular research-state snapshot.
- **Inputs:** Current belief state, research objective, candidate actions, expected epistemic and
  practical value, uncertainty, risk, constraints, and remaining budget.
- **Outputs:** Selected action or explicit non-action, alternatives considered, feasibility and
  cost assessment, expected value, reason, uncertainty, and references to the exact input state.
- **Invariants:** The selected action is feasible when issued; a stop or defer decision is valid;
  reasons and alternatives are retained; hindsight cannot rewrite the original decision;
  decision identity and input-state references are stable.
- **Failure modes:** A suggestion has no rationale; constraints or budget are ignored; alternatives
  are silently discarded; a decision is rationalized using later evidence; the decision record
  contains only a score whose semantics cannot be inspected.

### Research Memory

- **Responsibility:** Preserve the durable, queryable lineage of scientific entities and events so
  that a research state and its reasoning can be reconstructed.
- **Inputs:** Hypothesis versions, experiment plans and executions, observations, evidence,
  belief-state versions, objectives, budgets, decisions, artifacts, and provenance metadata.
- **Outputs:** Point-in-time snapshots, ordered histories, lineage queries, evidence chains,
  reproducibility records, and audit views.
- **Invariants:** Raw observations, interpretations, beliefs, and decisions remain distinct;
  corrections supersede rather than erase; identities and timestamps are stable; simulated and
  empirical records are clearly labeled; every derived item retains upstream references.
- **Failure modes:** Memory becomes an unstructured log dump; history is mutable; provenance is
  lost during import; schema changes destroy meaning; the state behind a decision cannot be
  reconstructed; simulated output is presented as empirical evidence.

### Research Objective

- **Responsibility:** Define what progress means for the current research effort, including
  epistemic goals, practical goals, tradeoffs, risk tolerance, and stopping conditions.
- **Inputs:** Scientific question, stakeholder intent, success and failure criteria, utility
  dimensions, acceptable risk, time horizon, and constraints.
- **Outputs:** A versioned objective against which experiments and decisions can be evaluated,
  including priorities, tradeoff rules, and stopping criteria.
- **Invariants:** The objective is explicit and versioned; it may be multi-objective or
  lexicographic rather than scalar; metric proxies are distinguished from the underlying goal;
  an objective change does not retroactively change the reasons for past decisions.
- **Failure modes:** A convenient metric silently replaces the scientific goal; priorities are
  hidden; goals move after results are seen; incompatible goals are collapsed without a tradeoff
  rule; no condition permits stopping.

### Experimental Budget

- **Responsibility:** Represent finite resources and determine which experiments are feasible now
  and over the intended research horizon.
- **Inputs:** Resource allocation, time, compute, money, sample or material limits, safety or risk
  limits, per-experiment estimates, reservations, and actual usage.
- **Outputs:** Remaining resources by unit, feasible candidate set, reservations, actual debits,
  forecast uncertainty, and budget violations.
- **Invariants:** Units and accounting horizon are explicit; estimates and actual costs are
  distinct; reserved or spent resources cannot be spent twice; hard and soft limits are labeled;
  uncertainty in cost estimates is representable.
- **Failure modes:** Experiment count is treated as the only cost; units are mixed; overhead is
  omitted; reservations race or double-spend; a suggested experiment cannot fit the budget;
  uncertain cost is treated as exact.

## 4. Architecture Boundaries

Research Reasoning Architecture owns scientific semantics and contracts. RDE Core owns one
application of those contracts.

| Concern | General Research Reasoning Architecture | RDE Core |
| --- | --- | --- |
| Scientific state | Domain-neutral identities, relationships, versions, and lifecycle semantics for the core abstractions. | Concrete hypotheses, candidate experiments, observations, and decisions for sequential experiment selection. |
| Reasoning | Contracts for evidence interpretation, belief update, rationale, uncertainty, and replay. | Specific selection policies, predictive models, scoring rules, tie-breaking, and application configuration. |
| Objective and budget | General semantics for multi-dimensional objectives, feasibility, accounting, and stopping. | Experiment-count and synthetic compute budgets plus the policy-comparison objective used by the benchmark. |
| Execution | A boundary between planned experiment, actual execution, and resulting observations. | The deterministic synthetic world and its candidate evaluation behavior. |
| Memory | Provenance, lineage, immutability, correction, and snapshot requirements. | SQLite storage, application schemas, and CLI history queries. |
| Evaluation | Requirements that reasoning and decisions be auditable and reproducible. | Best-result curves, regret, duplicate avoidance, policy comparison, and synthetic compute cost. |
| Domain adaptation | Extension points through which a domain defines claims, measurements, evidence rules, feasibility, and costs. | Machine-learning parameter encoding, optimizer categories, response surfaces, distance functions, and observation interpretation. |

The general architecture must not contain reinforcement-learning concepts such as agents,
rewards, policies, actions, or Markov states as foundational assumptions. It must not contain
hyperparameter-optimization concepts such as model parameters, trials, or search spaces as
universal scientific entities. It must not assume a particular likelihood model, acquisition
function, experimental method, data modality, or scientific domain.

Those techniques may be used behind a general interface when an application chooses them. For
example, an RDE Core policy may use Bayesian optimization, but that does not make Bayesian
optimization part of the architecture. A biology adapter may define assay-specific evidence,
but assay semantics do not enter the core. The core defines the obligations of an update or a
decision; the application and domain define how to satisfy them.

## 5. First Application: RDE Core

RDE Core asks: given current evidence and beliefs, which feasible experiment
should be run next to make the most useful progress under a limited budget? In the first
benchmark, "useful progress" is intentionally narrow and measurable, but the application should
eventually support objectives beyond finding the largest scalar result, including discrimination
between hypotheses, uncertainty reduction, robustness, replication, and falsification.

### Mapping the current prototype

| Current prototype element | General-architecture role | Current limitation |
| --- | --- | --- |
| Candidate configuration | Proposed experiment design. | It is not yet a registered Experiment with target hypotheses, plan, or execution identity. |
| `DeterministicSyntheticWorld` | Experimental environment and Research Simulator for benchmark execution. | Its hidden true value is evaluator-only and must never become Reasoner input. |
| Observed value | Raw observation from an executed experiment. | It has not yet been interpreted into explicit Evidence. |
| True value | Benchmark-only truth used for evaluation and regret. | It is not evidence and must remain outside operational history supplied to policies or belief updates. |
| Synthetic cost | Actual debit against an Experimental Budget. | The current loop records cost but does not yet model reservation, feasibility, or remaining budget as a first-class state. |
| `ExperimentRecord` | A compact record of experiment design, execution result, and cost. | It currently compresses concepts that the architecture keeps logically distinct. |
| SQLite experiment history | Initial storage mechanism for Research Memory. | It stores runs, but not hypothesis versions, evidence lineage, belief states, objectives, or decision rationales. |
| Random policy | A Reasoner/decision-policy baseline with no substantive belief model. | It establishes comparison behavior but does not perform scientific inference. |
| Greedy predicted-performance policy | A Reasoner/decision-policy baseline using implicit predictions. | Its predictive state is not an explicit, versioned Belief State and its suggestion is not a complete Decision record. |
| `rde suggest` | A partial Decision operation. | It returns a candidate but not the full reason, alternatives, expected cost/value, and input-state references. |
| `rde run` | Experiment execution followed by a memory append. | Evidence extraction and belief update are not yet represented. |
| Explicit seeds | Reproducibility metadata for world and policy behavior. | Seeds must eventually be attached to the complete reasoning trace, not only execution calls. |

This mapping is deliberately honest: the current milestone is a deterministic experiment-selection
prototype, not yet a complete implementation of Research Reasoning Architecture.

### Distinction from neighboring systems

- **Experiment tracking** records runs, parameters, metrics, and artifacts. RDE Core may rely on
  such records, but it adds structured hypotheses, evidence, beliefs, resource
  constraints, and reasoned next-action decisions. Storage is supporting infrastructure, not its
  defining capability.
- **Bayesian optimization** is a particular family of surrogate and acquisition methods for
  optimizing a black-box objective. It can be one RDE Core policy. RDE Core is
  the policy-independent reasoning and evaluation application, and it can pursue epistemic goals
  that are not equivalent to scalar maximization.
- **Hyperparameter search** searches configurations for a model-training procedure. The synthetic
  benchmark currently resembles that domain because it is cheap and measurable, but the Decision
  Engine's abstraction is an experiment bearing on hypotheses, not a parameter trial.
- **AutoML** attempts to construct a high-performing machine-learning pipeline. RDE Core neither
  assembles production pipelines nor automates deployment; it studies and records
  decisions about what experiment to perform next.
- **LLM summarization** converts research logs into prose. RDE Core requires
  structured provenance, explicit update rules, measurable policies, and replayable reasons.
  Fluent explanation is not a substitute for evidence or decision logic, and an LLM is not part
  of the core policy in this stage.

## 6. Future Applications

The same core abstractions support applications with different primary responsibilities.

### Research Memory

Research Memory would operationalize the Research Memory abstraction as the durable scientific
system of record. It would ingest and connect hypothesis versions, experiment plans and results,
evidence, belief updates, decisions, objectives, and artifacts. Its main capabilities would be
lineage, retrieval, state reconstruction, and provenance-preserving correction, not next-action
selection.

### Research Planner

Research Planner would turn objectives and unresolved hypotheses into a constrained sequence or
dependency graph of proposed experiments. It would reuse Hypothesis, Experiment, Research
Objective, Experimental Budget, Belief State, and Decision. Unlike RDE Core's
immediate next choice, it would focus on multi-step dependencies, prerequisites, contingencies,
and explicit replanning points.

### Research Simulator

Research Simulator would evaluate possible experiments and research trajectories against an
explicit model of an experimental world. It would reuse Experiment, Evidence, Belief State,
Reasoner, Decision, Objective, and Budget to compare counterfactual paths or test decision rules.
All simulated observations and evidence would remain labeled as simulated so they could not be
mistaken for empirical findings.

### Research Auditor

Research Auditor would inspect a research trace for unsupported claims, missing provenance,
double-counted or leaked evidence, inconsistent belief updates, objective drift, budget
violations, irreproducible decisions, and discrepancies between planned and executed experiments.
It would reuse every core abstraction but would validate their invariants rather than choose the
next experiment.

These applications can share identities and records without becoming one monolithic system. A
Planner can propose an Experiment, RDE Core can select it, a Memory can preserve it, a
Simulator can evaluate a counterfactual version, and an Auditor can verify the resulting trace.

## 7. Design Principles

1. **Experiments are observations, not knowledge.** An experimental result must pass through an
   explicit evidence interpretation and belief update before it can affect a scientific claim.
2. **Evidence must be traceable to experiments.** Every evidence item must identify the exact
   observations, executions, interpretation rule, and assumptions from which it was derived.
3. **Scientific layers must remain distinct.** Raw observations, evidence, beliefs, objectives,
   and decisions must never be collapsed into one generic result or score.
4. **Beliefs must be revisable.** New or contradictory evidence must be able to change a belief,
   and prior belief-state versions must remain available for audit.
5. **Uncertainty must be explicit.** Unknown, ambiguous, conflicting, and poorly measured states
   are first-class outcomes; absence of uncertainty metadata must never imply certainty.
6. **Decisions must include reasons.** Every action, deferral, and stop decision must reference
   the beliefs, evidence, objective, alternatives, constraints, and budget state that justified it.
7. **Scientific progress is not identical to objective maximization.** Learning, falsification,
   replication, robustness, risk reduction, and discovery can matter even when a scalar metric
   does not improve.
8. **Domain-specific logic must remain outside the general reasoning core.** Domain vocabulary,
   measurement semantics, likelihoods, feasibility rules, and utility models enter through
   explicit adapters or applications.
9. **Reasoning must be replayable without privileged information.** Procedures, versions, inputs,
   and seeds must reproduce results, and evaluator-only or future information must never leak
   into operational reasoning.
10. **Objectives and budgets must be first-class and versioned.** Constraints, tradeoffs, and
    resource accounting must be visible at decision time; later changes must not rewrite the
    meaning of earlier decisions.

## 8. Non-Goals

At this stage, the architecture is not trying to become:

- a web dashboard or visual experiment-management product;
- an LLM agent or an LLM-based core reasoner;
- a cloud execution or orchestration platform;
- an autonomous paper-writing or publication system;
- a multi-agent research environment;
- a production-scale distributed-training system;
- a replacement for domain scientists, peer review, or research governance;
- a universal scientific ontology or a claim that one belief representation fits every domain;
- a production experiment tracker, laboratory information-management system, or artifact store;
- a complete causal-inference, theorem-proving, or automated-discovery framework.

The immediate goal is to establish small, precise semantics for traceable scientific state and to
test them in a deterministic synthetic application.

## 9. Concrete Next Milestone

### Versioned belief update for one matched-experiment question

Introduce one explicit, application-level scientific question into the existing synthetic world:
across otherwise matched candidate configurations, which optimizer shows a consistent practical
advantage?

Use three competing hypotheses:

- Adam has a consistent practical advantage.
- Neither optimizer has a consistent practical advantage.
- SGD has a consistent practical advantage.

A matched pair consists of two completed experiments with identical learning rate,
regularization, and model width, differing only in optimizer. Their observed-value difference is
classified as Adam-win, practical-tie, or SGD-win using a predeclared practical-effect threshold.
The resulting Evidence item references both experiment records and never uses the world's hidden
true values.

Begin from an explicit uniform belief over the three hypotheses. Apply a fixed, documented
likelihood model to each new matched-pair evidence item:

| Hypothesis | Adam-win evidence | Tie evidence | SGD-win evidence |
| --- | ---: | ---: | ---: |
| Adam advantage | 0.70 | 0.20 | 0.10 |
| No consistent advantage | 0.20 | 0.60 | 0.20 |
| SGD advantage | 0.10 | 0.20 | 0.70 |

Each update creates a new immutable Belief State with references to its prior state, consumed
evidence, update-rule version, normalized belief values, uncertainty, and a concise deterministic
rationale. The likelihood values are benchmark assumptions and must be recorded as such; they are
not hidden truths. This is Bayesian belief updating, not Bayesian optimization.

The application-specific matched-pair and outcome classification logic belongs in RDE Core. The
generic requirements for hypothesis identity, evidence provenance,
versioned belief updates, and replay belong in Research Reasoning Architecture.

The milestone is intentionally limited:

- Do not change random or greedy experiment selection.
- Do not use beliefs to choose experiments yet.
- Do not add Bayesian optimization, information-gain selection, an LLM, or a user interface.
- Do not generalize beyond this one fixed hypothesis family until the provenance and update
  semantics are tested.

Exit criteria are deterministic and inspectable: identical experiment history produces identical
evidence and belief versions; every evidence item links to both source experiments; an evidence
item cannot be consumed twice in one lineage; known fixtures produce exact expected updates;
opposing evidence can revise prior confidence; and hidden benchmark truth is absent from every
Reasoner input. This adds the first genuine evidence-to-belief capability while keeping the
current next-experiment policies unchanged.
