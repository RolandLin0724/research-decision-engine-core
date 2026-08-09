from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path


def test_paired_evaluation_cli_smoke(tmp_path: Path) -> None:
    output_directory = tmp_path / "paired-evaluation-v1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_decision_engine.cli",
            "evaluate",
            "--seeds",
            "0",
            "--bootstrap-resamples",
            "20",
            "--output-directory",
            str(output_directory),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    manifest = json.loads((output_directory / "run_manifest.json").read_text(encoding="utf-8"))
    with (output_directory / "per_run_results.csv").open(newline="", encoding="utf-8") as handle:
        run_rows = list(csv.DictReader(handle))

    assert "Fairness and leakage audit: PASSED" in result.stdout
    assert manifest["paired_seed_count"] == 1
    assert manifest["run_count"] == 32
    assert len(run_rows) == 32
    assert {row["policy"] for row in run_rows} == {
        "random",
        "greedy",
        "information_gain",
        "lookahead_information_gain",
    }
    assert {path.name for path in output_directory.iterdir()} == {
        "run_manifest.json",
        "per_run_results.jsonl",
        "per_run_results.csv",
        "aggregate_results.csv",
        "paired_comparisons.csv",
        "calibration_results.csv",
        "failure_cases.jsonl",
        "EVALUATION_REPORT.md",
    }
