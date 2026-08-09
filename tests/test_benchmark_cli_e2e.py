from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path


def test_benchmark_cli_compares_all_existing_policies(tmp_path: Path) -> None:
    output_directory = tmp_path / "benchmark-output"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_decision_engine.cli",
            "benchmark",
            "--world",
            "adam_low_noise_symmetric",
            "--seeds",
            "0",
            "--budget",
            "3",
            "--policy",
            "random",
            "greedy",
            "information_gain",
            "--output-directory",
            str(output_directory),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    json_path = output_directory / "benchmark_results.json"
    parsed = json.loads(json_path.read_text(encoding="utf-8"))
    with (output_directory / "benchmark_runs.csv").open(newline="", encoding="utf-8") as handle:
        run_rows = list(csv.DictReader(handle))

    assert "Scientific progress" in result.stdout
    assert "Objective optimization" in result.stdout
    assert set(parsed["policies"]) == {"random", "greedy", "information_gain"}
    assert len(parsed["runs"]) == 3
    assert {row["policy"] for row in run_rows} == {
        "random",
        "greedy",
        "information_gain",
    }
    assert (output_directory / "benchmark_traces.csv").is_file()
    assert (output_directory / "benchmark_aggregates.csv").is_file()
