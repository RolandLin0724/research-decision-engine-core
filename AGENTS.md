# AGENTS.md

## Repository Architecture

This repository contains a compact Python 3.12 research prototype for sequential experiment selection.

- `research_decision_engine/types.py` defines immutable experiment dataclasses.
- `research_decision_engine/world.py` defines the deterministic synthetic benchmark world.
- `research_decision_engine/policies.py` contains the implemented decision policies.
- `research_decision_engine/storage.py` stores experiment history in SQLite.
- `research_decision_engine/runner.py` connects storage, policies, and the world.
- `research_decision_engine/cli.py` exposes the `rde` command.
- `tests/` contains unit tests and one end-to-end CLI smoke test.
- `SPEC.md` and `PLAN.md` are planning documents and should not be edited casually.

## Coding Rules

- Keep the implementation typed, deterministic, and easy to inspect.
- Prefer standard-library code unless a dependency is clearly justified.
- Do not add a web interface, LLM integration, cloud service, or external experiment tracker.
- Do not implement Bayesian optimization or information-gain policies until explicitly requested.
- Keep SQLite as the local persistence layer for experiment history.
- Preserve deterministic behavior by threading explicit seeds through stochastic code.
- Use dataclasses for experiment records unless a future task explicitly asks for Pydantic.

## Validation Commands

Run these commands before reporting completion:

```powershell
uv sync
uv run ruff format --check .
uv run ruff check .
uv run mypy .
uv run pytest
```

## Boundaries For Future Codex Tasks

- Future tasks may extend benchmark worlds, candidate spaces, metrics, and policies.
- Future tasks should keep policy behavior reproducible and test-covered.
- Do not modify `SPEC.md` or `PLAN.md` unless a concrete inconsistency blocks implementation; explain the inconsistency first.
- Do not introduce production experiment tracking, distributed execution, or UI work before the core research loop is reviewed.
