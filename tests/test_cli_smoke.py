import json
import subprocess
import sys
from pathlib import Path


def test_cli_end_to_end_smoke(tmp_path: Path) -> None:
    db_path = tmp_path / "rde.sqlite"

    init_result = subprocess.run(
        [sys.executable, "-m", "research_decision_engine.cli", "--db", str(db_path), "init"],
        check=True,
        capture_output=True,
        text=True,
    )
    suggest_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_decision_engine.cli",
            "--db",
            str(db_path),
            "suggest",
            "--policy",
            "greedy",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    run_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_decision_engine.cli",
            "--db",
            str(db_path),
            "run",
            "--policy",
            "greedy",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    history_result = subprocess.run(
        [sys.executable, "-m", "research_decision_engine.cli", "--db", str(db_path), "history"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(init_result.stdout)["status"] == "initialized"
    assert json.loads(suggest_result.stdout)["candidate_id"] == "cand-000"
    assert json.loads(run_result.stdout)["candidate_id"] == "cand-000"
    assert len(json.loads(history_result.stdout)) == 1
