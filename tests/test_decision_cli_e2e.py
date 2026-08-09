from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

from research_decision_engine.storage import ExperimentStore


def test_belief_guided_suggestion_cli_workflow(tmp_path: Path) -> None:
    db_path = tmp_path / "belief-guided.sqlite"

    _run_cli(db_path, "init")
    first = _run_cli(db_path, "run", "--policy", "greedy")
    seed_for_cand_001 = next(
        seed for seed in range(10_000) if random.Random(seed).randrange(71) == 0
    )
    second = _run_cli(
        db_path,
        "run",
        "--policy",
        "random",
        "--seed",
        str(seed_for_cand_001),
    )
    seed_for_cand_006 = next(
        seed for seed in range(10_000) if random.Random(seed).randrange(70) == 4
    )
    third = _run_cli(
        db_path,
        "run",
        "--policy",
        "random",
        "--seed",
        str(seed_for_cand_006),
    )
    suggestion = _run_cli(db_path, "suggest", "--policy", "information_gain")
    explanation = _run_cli(db_path, "explain-suggestion")

    assert first["candidate_id"] == "cand-000"
    assert second["candidate_id"] == "cand-001"
    assert third["candidate_id"] == "cand-006"
    assert suggestion["candidate_id"] == "cand-007"
    assert suggestion["expected_information_gain"] > 0.0
    assert suggestion["fallback_reason"] is None
    assert explanation["suggestion_id"] == suggestion["suggestion_id"]
    assert explanation["candidate_suggested"]["candidate_id"] == "cand-007"
    assert len(explanation["competing_hypotheses"]) == 3
    assert explanation["score_breakdown"]["expected_information_gain_bits"] > 0.0
    assert len(explanation["top_competing_alternatives"]) == 3

    with ExperimentStore(db_path) as store:
        store.init_schema()
        traces = store.list_decision_traces()
        assert len(traces) == 1
        assert traces[0].suggestion_id == suggestion["suggestion_id"]
        assert traces[0].belief_state_id == explanation["belief_state_id"]


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
