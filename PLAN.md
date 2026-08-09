# Research Decision Engine Core Implementation Plan

## Milestone 1: Project Skeleton

Goal: create a minimal typed Python package without implementing policy complexity.

Tasks:

- Add package structure under `research_decision_engine/`.
- Add `pyproject.toml` with Python version, dependencies, formatting, typing, and test configuration.
- Define core dataclasses and protocols in `types.py` and policy/surrogate base modules.
- Add a small test suite that imports the package and validates basic type construction.

Exit criteria:

- `pytest` runs.
- Package imports cleanly.
- Core interfaces are documented with short docstrings.

## Milestone 2: Synthetic Benchmark Core

Goal: make seeded synthetic experimental worlds available for cheap evaluation.

Tasks:

- Implement deterministic candidate generation for mixed continuous, integer, and categorical spaces.
- Implement at least two synthetic worlds:
  - smooth unimodal objective,
  - multi-modal objective with noise.
- Implement synthetic compute-cost functions.
- Add a benchmark suite object that combines candidates, worlds, seeds, and budgets.
- Add tests for determinism and finite candidate-space behavior.

Exit criteria:

- The same seeds always generate the same candidates and objective values.
- The true best candidate is computable by the evaluator.
- Costs and observations are recorded consistently.

## Milestone 3: Evaluation Runner and Metrics

Goal: run a policy sequentially in a world and compute comparable metrics.

Tasks:

- Implement the runner loop:
  - ask policy for next candidate,
  - validate budget and duplicate constraints,
  - evaluate world,
  - append observation,
  - update metrics.
- Implement metrics:
  - best result found per experiment,
  - regret,
  - information gained per experiment placeholder/estimator,
  - duplicate experiments avoided or attempted,
  - cumulative compute cost.
- Add JSONL trace output and summary JSON/CSV output.
- Add tests with tiny hand-built worlds where expected metrics are known.

Exit criteria:

- A full run can be reproduced from config and seeds.
- Metrics are correct on simple fixtures.
- Duplicate candidate attempts are handled deterministically.

## Milestone 4: Simple Baseline Policies

Goal: establish non-Bayesian baselines.

Tasks:

- Implement random selection.
- Implement a simple surrogate abstraction.
- Implement greedy predicted performance using a basic surrogate.
- Implement uncertainty sampling using uncertainty from an ensemble or probabilistic model.
- Add tests that policies select valid candidates and are reproducible.

Exit criteria:

- Random, greedy, and uncertainty policies run on every benchmark world.
- Policies respect completed-candidate and budget constraints.
- Policy outputs are deterministic for fixed seeds.

## Milestone 5: Bayesian Optimization Baseline

Goal: add a standard optimization baseline for comparison.

Tasks:

- Implement Bayesian optimization over the finite candidate set.
- Start with a simple acquisition function such as expected improvement or upper confidence bound.
- Use the existing surrogate interface.
- Add tests for acquisition ranking on controlled predictions.

Exit criteria:

- Bayesian optimization runs through the same runner as other policies.
- Acquisition behavior is testable independently.
- Results are comparable in the same metric reports.

## Milestone 6: Information-Gain Policy

Goal: add the research-focused decision policy.

Tasks:

- Define the first practical information-gain estimator:
  - average predictive variance reduction,
  - entropy reduction over the believed best candidate,
  - or another documented approximation.
- Implement information-gain candidate selection over the finite candidate set.
- Record estimator-specific diagnostics for analysis.
- Add tests on small cases where uncertainty reduction is predictable.

Exit criteria:

- Information-gain selection is explicit, documented, and reproducible.
- The estimator can be compared with uncertainty sampling and Bayesian optimization.
- Diagnostics explain why a candidate was selected.

## Milestone 7: Benchmark Comparison Script

Goal: make policy comparison easy to run locally.

Tasks:

- Add a CLI or script for running all baseline policies across a benchmark suite.
- Save run traces and summary metrics under a configurable output directory.
- Generate simple static plots or tabular summaries from saved results.
- Add a smoke test with a very small suite.

Exit criteria:

- One command runs the benchmark suite.
- Outputs include per-step curves and final aggregate metrics.
- Re-running with the same config produces the same results.

## Milestone 8: Review and Tightening

Goal: keep version 1 small, clear, and ready for iteration.

Tasks:

- Review public interfaces for unnecessary abstraction.
- Add missing type annotations.
- Add documentation for benchmark assumptions and metric definitions.
- Confirm no web interface or LLM decision policy has been introduced.
- Identify the smallest next research extension after version 1.

Exit criteria:

- Tests, formatting, and typing pass.
- The system remains understandable as a research prototype.
- Future work is separated from version 1 requirements.

## Suggested Initial Dependencies

- `numpy` for numeric operations and random generation.
- `scipy` if needed for probability utilities.
- `scikit-learn` for simple surrogate models.
- `pandas` for tabular reports.
- `pytest` for tests.
- `mypy` or `pyright` for type checking.
- `ruff` for linting and formatting.

Dependencies should remain minimal until a milestone clearly needs more.

## Non-Goals Before Review

- No web interface.
- No LLM-based policy.
- No real model training jobs.
- No distributed execution.
- No database requirement.
- No production experiment tracking service.
