from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


def test_matched_experiment_belief_update_cli_workflow(tmp_path: Path) -> None:
    db_path = tmp_path / "reasoning.sqlite"

    init = _run_cli(db_path, "init")
    first_run = _run_cli(db_path, "run", "--policy", "greedy")

    seed_for_first_available = next(
        seed for seed in range(10_000) if random.Random(seed).randrange(71) == 0
    )
    second_run = _run_cli(
        db_path,
        "run",
        "--policy",
        "random",
        "--seed",
        str(seed_for_first_available),
    )
    evidence = _run_cli(db_path, "evidence")
    beliefs = _run_cli(db_path, "beliefs")

    assert init["status"] == "initialized"
    assert first_run["candidate_id"] == "cand-000"
    assert second_run["candidate_id"] == "cand-001"
    assert len(evidence) == 1
    assert evidence[0]["source_experiment_ids"] == [1, 2]

    update_id = evidence[0]["belief_update_id"]
    explanation = _run_cli(db_path, "explain-belief-update", update_id)

    assert explanation["update_id"] == update_id
    assert len(explanation["source_experiments"]) == 2
    assert all("true_value" not in item for item in explanation["source_experiments"])
    assert len(explanation["likelihood_calculations"]) == 3
    assert sum(
        explanation["posterior_belief_state"]["posterior_probabilities"].values()
    ) == pytest.approx(1.0)
    assert beliefs["evidence_count"] == 1
    assert sum(item["supporting_evidence_count"] for item in beliefs["hypotheses"]) == 1


def _run_cli(db_path: Path, *args: str) -> Any:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_decision_engine.cli",
            "--db",
            str(db_path),
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)
