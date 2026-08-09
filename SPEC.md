# Research Decision Engine Core Specification

## Purpose

RDE Core is a small, reproducible research prototype for deciding which synthetic machine-learning experiment to run next under a limited compute budget.

The first version is not an experiment tracker, dashboard, AutoML system, or LLM summarizer. It is a decision-policy evaluation harness: given previous experiment results and a finite budget, it compares strategies for choosing the next experiment in a controlled synthetic world.

## Core Research Question

Can a decision policy use prior experimental outcomes to select future experiments more efficiently than simple baselines, as measured by best result found, regret, information gained, duplicate avoidance, and compute cost?

## Scope

Version 1 is limited to synthetic machine-learning experiments where the true objective is cheap to evaluate and reproducible. Each experiment is represented by a candidate configuration from a bounded search space. Running an experiment queries an unknown synthetic objective and returns a noisy result plus a compute cost.

The system should:

- Generate deterministic synthetic benchmark worlds from seeds.
- Define a finite or sampled experiment candidate space.
- Run sequential decision policies under a compute or experiment-count budget.
- Record all decisions, observations, model states, and metrics needed for offline evaluation.
- Compare multiple baseline policies on identical benchmark worlds.
- Be typed, testable, and small enough to understand end to end.

The system should not:

- Build a web interface.
- Use an LLM as the core decision policy.
- Run real machine-learning training jobs.
- Optimize arbitrary user code.
- Provide production experiment tracking.

## What This Is Not

### Experiment Tracking

Experiment tracking records what was run, with parameters, artifacts, metrics, and metadata. RDE Core may store run records, but tracking is supporting infrastructure, not the main product. The central behavior is choosing the next experiment, not cataloging past experiments.

### Hyperparameter Optimization

Hyperparameter optimization usually searches for the best configuration of a known model-training procedure. This project studies experiment selection as a broader sequential decision problem. Hyperparameter-like spaces are used in version 1 only because they provide a convenient synthetic domain.

### Bayesian Optimization

Bayesian optimization is one decision policy family, typically using a surrogate model and an acquisition function such as expected improvement or upper confidence bound. RDE Core should include Bayesian optimization as a baseline, but the project is the benchmark harness and policy comparison framework, not a synonym for Bayesian optimization.

### AutoML

AutoML attempts to automatically produce high-performing machine-learning pipelines, often including model selection, preprocessing, ensembling, and deployment-oriented concerns. This project does not attempt to generate production models. It evaluates next-experiment decision policies in synthetic worlds.

### Generic LLM Experiment Summarization

LLM experiment summarization turns experiment logs into prose insights. RDE Core does not use an LLM to summarize results or choose actions in version 1. The core decision policies are explicit algorithms with measurable behavior and reproducible outputs.

## Minimal Benchmark

The benchmark represents an experimental world as an unknown synthetic objective:

```text
f_world(x) -> observed_result
```

Where:

- `x` is an experiment candidate, such as a vector of continuous, integer, or categorical parameters.
- `f_world` is deterministic given a world seed, candidate, and optional observation-noise seed.
- The true noiseless value is available only to the benchmark evaluator, not to the decision policy.
- The observed value may include controlled noise.
- Each candidate has an associated compute cost.

### Candidate Space

Version 1 should begin with a finite candidate set generated from a seeded sampler. A finite set makes duplicate detection, regret, information gain approximation, and test assertions straightforward.

Initial candidate dimensions:

- `learning_rate`: continuous log-scaled value.
- `regularization`: continuous log-scaled value.
- `model_width`: integer or ordinal value.
- `optimizer`: categorical value.
- `dataset_variant`: categorical value.

### Synthetic Worlds

Each world should define a hidden response surface over candidates. Useful first worlds:

- Smooth unimodal objective.
- Multi-modal objective with local optima.
- Objective with irrelevant dimensions.
- Objective with categorical interactions.
- Noisy objective.
- Cost-sensitive objective where expensive candidates are not always better.

A benchmark suite is a list of world definitions and seeds. Policies are evaluated across the same suite.

## Decision Policies

All policies expose a shared interface:

```text
select_next(history, candidates, budget_state) -> candidate
```

Policies cannot select candidates that are already completed unless explicitly configured to allow repeats for noise estimation.

### Random Selection

Selects uniformly at random from available candidates that fit the remaining budget. This establishes the minimum useful baseline.

### Greedy Predicted Performance

Fits or updates a surrogate model from observed results, predicts performance for untried candidates, and selects the candidate with the best predicted mean result. This tests exploitation without explicit uncertainty handling.

### Uncertainty Sampling

Uses a surrogate model with uncertainty estimates and selects the untried candidate with highest predictive uncertainty. This tests exploration without direct reward optimization.

### Bayesian Optimization

Uses a probabilistic surrogate model and an acquisition function such as expected improvement or upper confidence bound. This tests a standard optimization-oriented sequential decision baseline.

### Information-Gain-Based Selection

Selects the candidate expected to reduce uncertainty about the experimental world or the identity/value of the best candidate. In version 1, this can be approximated with a surrogate ensemble, posterior samples, or variance reduction over the finite candidate set.

## Evaluation Metrics

Metrics are computed per policy, world, seed, and experiment step.

### Best Result Found Per Experiment

The incumbent best observed or noiseless benchmark value after each experiment. This is the main anytime-performance curve.

### Regret

Difference between the true best achievable value in the finite candidate set and the best true value found so far:

```text
regret_t = true_best_value - best_true_value_found_by_t
```

For minimization worlds, use the corresponding sign convention consistently.

### Information Gained Per Experiment

Estimated reduction in uncertainty after each observation. Version 1 may report:

- Change in average predictive variance across candidates.
- Change in entropy over which candidate is believed to be best.
- Approximate mutual information when supported by the surrogate.

The exact estimator must be documented per policy or evaluator.

### Duplicate Experiments Avoided

Count and rate of avoided repeated candidates compared with policies or settings that allow duplicate proposals. In the default benchmark, duplicate completed candidates should be disallowed, and attempted duplicates should be recorded as policy errors or repaired by a deterministic fallback.

### Compute Cost

Total and cumulative compute cost consumed. Cost can be synthetic, such as a deterministic function of candidate dimensions plus optional noise. Evaluation should report both experiment count and cost-normalized progress.

## Python Architecture

The code should be organized as a small typed package:

```text
research_decision_engine/
  __init__.py
  benchmarks/
    candidates.py
    worlds.py
    suite.py
  policies/
    base.py
    random.py
    greedy.py
    uncertainty.py
    bayes_opt.py
    information_gain.py
  surrogate/
    base.py
    sklearn_models.py
    ensembles.py
  evaluation/
    runner.py
    metrics.py
    reports.py
  storage/
    schema.py
    jsonl.py
  config.py
  types.py
tests/
```

### Key Types

- `Candidate`: immutable experiment configuration with stable identifier.
- `Observation`: candidate id, observed value, true benchmark value, noise, cost, and step.
- `ExperimentHistory`: ordered observations plus helper methods.
- `BudgetState`: remaining experiment count and compute budget.
- `SyntheticWorld`: evaluates candidates and exposes benchmark-only true values.
- `DecisionPolicy`: typed protocol for selecting the next candidate.
- `SurrogateModel`: typed protocol for fit, predict, and uncertainty.
- `RunResult`: complete policy-world trajectory and metrics.

### Reproducibility

Every stochastic component must accept an explicit seed or random generator. Benchmark results should be reproducible from:

- Benchmark suite name.
- World seed.
- Candidate seed.
- Policy name and policy seed.
- Budget configuration.

### Testing Strategy

Initial tests should cover:

- Candidate generation is deterministic.
- Synthetic worlds are deterministic for fixed seeds.
- Policies do not select completed candidates by default.
- Runner respects experiment and compute budgets.
- Metrics match known small examples.
- Baseline runs are reproducible.

## Initial Deliverables

Version 1 should produce command-line or script-level outputs only:

- JSONL run traces.
- Summary CSV or JSON metrics.
- Optional static plots generated from saved results.

No web interface should be built until the core benchmark and decision policies are working and reviewed.
