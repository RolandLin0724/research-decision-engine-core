from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from research_decision_engine.benchmarks.closed_loop_reporting import OUTPUT_FILENAMES


def test_closed_loop_evaluation_cli_smoke(tmp_path: Path) -> None:
    output_directory = tmp_path / "closed-loop-evaluation-v1-smoke"
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_decision_engine.cli",
            "evaluate-closed-loop",
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
    gates = json.loads((output_directory / "ACCEPTANCE_GATES.json").read_text(encoding="utf-8"))
    assert "hard audits passed: True" in process.stdout
    assert "verdict: smoke_only" in process.stdout
    assert manifest["run_count"] == 32
    assert manifest["full_frozen_matrix"] is False
    assert gates["calibrated_closed_loop_control_accepted"] is False
    assert {item.name for item in output_directory.iterdir()} == set(OUTPUT_FILENAMES)
