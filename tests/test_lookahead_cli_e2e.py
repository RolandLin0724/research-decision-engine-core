from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from research_decision_engine.storage import ExperimentStore


def test_delayed_information_cli_executes_first_action_and_replans(tmp_path: Path) -> None:
    db_path = tmp_path / "lookahead.sqlite"

    _run_cli(db_path, "init")
    first_suggestion = _run_cli(
        db_path,
        "suggest",
        "--policy",
        "lookahead_information_gain",
        "--max-cost",
        "2.2",
    )
    first_explanation = _run_cli(db_path, "explain-plan")
    first_run = _run_cli(
        db_path,
        "run",
        "--policy",
        "lookahead_information_gain",
        "--max-cost",
        "2.2",
    )
    second_suggestion = _run_cli(
        db_path,
        "suggest",
        "--policy",
        "lookahead_information_gain",
        "--max-cost",
        "1.2",
    )
    second_explanation = _run_cli(db_path, "explain-plan")

    assert first_suggestion["candidate_id"] == "cand-000"
    assert first_suggestion["first_action_effect"] == "opens_pair"
    assert first_suggestion["immediate_information_gain"] == 0.0
    assert first_suggestion["expected_two_step_information_gain"] > 0.0
    assert first_explanation["possible_evidence_branches"][0]["label"] == ("NO_EVIDENCE_YET")
    assert (
        first_explanation["possible_evidence_branches"][0]["second_action"]["candidate_id"]
        == "cand-001"
    )
    assert first_run["candidate_id"] == "cand-000"
    assert second_suggestion["candidate_id"] == "cand-001"
    assert second_suggestion["first_action_effect"] == "completes_pair"
    assert second_suggestion["immediate_information_gain"] > 0.0
    assert len(second_explanation["possible_evidence_branches"]) == 82
    assert second_explanation["real_belief_state_provenance"]["sequence"] == 0
    assert "Only selected_first_experiment" in second_explanation["execution_semantics"]

    with ExperimentStore(db_path) as store:
        store.init_schema()
        assert len(store.list_records()) == 1
        assert store.list_evidence() == []
        assert store.list_belief_updates() == []
        assert len(store.list_lookahead_plan_traces()) == 2


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
