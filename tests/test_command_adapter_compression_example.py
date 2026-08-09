from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from examples.command_adapter_compression.corpus_data import (
    CORPUS_BYTE_COUNT,
    CORPUS_PATH,
    CORPUS_SHA256,
    load_corpus,
)
from examples.command_adapter_compression.run_example import (
    EXPERIMENT_BUDGET,
    INTERRUPTION_STEP,
    RANDOM_POLICY_ID,
    RANDOM_POLICY_SEED,
    build_candidates,
)
from examples.command_adapter_compression.workload import CHUNK_MODES, CODECS, LEVELS

EXAMPLE_ROOT = Path(__file__).parents[1] / "examples" / "command_adapter_compression"


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        + b"\n"
    )


def test_candidate_space_and_committed_corpus_are_exact() -> None:
    candidates = build_candidates()
    assert len(candidates) == 24
    assert len({candidate.candidate_id for candidate in candidates}) == 24
    assert {
        (
            candidate.parameters["codec"],
            candidate.parameters["level"],
            candidate.parameters["chunk_mode"],
        )
        for candidate in candidates
    } == {(codec, level, mode) for codec in CODECS for level in LEVELS for mode in CHUNK_MODES}
    assert RANDOM_POLICY_ID == "random"
    assert RANDOM_POLICY_SEED == 1729
    assert EXPERIMENT_BUDGET == 8
    assert INTERRUPTION_STEP == 4
    corpus = load_corpus()
    assert CORPUS_PATH.is_file()
    assert len(corpus) == CORPUS_BYTE_COUNT == 145_258
    assert len(corpus) > 64 * 1024
    assert hashlib.sha256(corpus).hexdigest() == CORPUS_SHA256


def test_all_24_workloads_round_trip_and_emit_strict_deterministic_json(tmp_path: Path) -> None:
    workload = EXAMPLE_ROOT / "workload.py"
    counter = tmp_path / "counter.txt"
    outputs: dict[str, bytes] = {}
    for candidate in build_candidates():
        parameters = candidate.parameters
        command = [
            sys.executable,
            str(workload),
            "--codec",
            str(parameters["codec"]),
            "--level",
            str(parameters["level"]),
            "--chunk-mode",
            str(parameters["chunk_mode"]),
            "--counter-file",
            str(counter),
        ]
        completed = subprocess.run(command, cwd=tmp_path, capture_output=True, check=True)
        assert completed.stdout.endswith(b"\n")
        assert not completed.stdout.endswith(b"\n\n")
        assert b"\r" not in completed.stdout
        assert not completed.stdout.startswith(b"\xef\xbb\xbf")
        payload = json.loads(completed.stdout)
        assert set(payload) == {"cost", "objective_value"}
        assert completed.stdout == _canonical_json_bytes(payload)
        assert payload["cost"] > 0.0
        assert payload["objective_value"] > 0.0
        assert completed.stderr
        outputs[candidate.candidate_id] = completed.stdout

    first = build_candidates()[0]
    parameters = first.parameters
    repeated = subprocess.run(
        [
            sys.executable,
            str(workload),
            "--codec",
            str(parameters["codec"]),
            "--level",
            str(parameters["level"]),
            "--chunk-mode",
            str(parameters["chunk_mode"]),
            "--counter-file",
            str(counter),
        ],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    assert repeated.stdout == outputs[first.candidate_id]
    assert counter.read_text(encoding="ascii") == "25\n"


def test_cli_interrupts_resumes_and_replays_without_executing_commands(tmp_path: Path) -> None:
    output = tmp_path / "caller-output"
    completed = subprocess.run(
        [
            sys.executable,
            str(EXAMPLE_ROOT / "run_example.py"),
            "--output-dir",
            str(output),
        ],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    assert completed.stderr == b""
    payload = json.loads(completed.stdout)
    assert completed.stdout == _canonical_json_bytes(payload)
    assert payload["candidate_count"] == 24
    assert payload["policy_id"] == "random"
    assert payload["policy_seed"] == 1729
    assert payload["budget"] == 8
    assert payload["interruption_step"] == 4
    assert payload["resume_mismatch_rejected"] is True
    assert payload["original_command_count"] == 8
    assert payload["replay_command_count"] == 0
    assert payload["replay_equivalent"] is True
    assert len(payload["selected_candidate_ids"]) == 8
    assert (output / "original.sqlite3").is_file()
    assert (output / "run-bundle" / "run-bundle.json").is_file()
    assert (output / "replay" / "replay.sqlite3").is_file()
    assert (output / "command-count.txt").read_text(encoding="ascii") == "8\n"
    assert (output / "example-results.json").read_bytes() == completed.stdout
