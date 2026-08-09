from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from examples.command_adapter_compression.corpus_data import (
    CORPUS_BYTE_COUNT,
    CORPUS_SHA256,
)
from examples.command_adapter_compression.run_example import build_candidates
from examples.command_adapter_compression.run_v2_example import (
    PRIOR_UTILITY_FORMULA,
    V2_RANDOM_POLICY_SEED,
    build_prior_utility_map,
)

EXAMPLE_ROOT = Path(__file__).parents[1] / "examples" / "command_adapter_compression"
GREEDY_TOP_EIGHT = [
    "lzma-level-9-single-stream",
    "lzma-level-9-fixed-64-kib-members",
    "lzma-level-6-single-stream",
    "lzma-level-6-fixed-64-kib-members",
    "lzma-level-3-single-stream",
    "lzma-level-3-fixed-64-kib-members",
    "lzma-level-1-single-stream",
    "lzma-level-1-fixed-64-kib-members",
]
RANDOM_SELECTED_EIGHT = [
    "gzip-level-9-fixed-64-kib-members",
    "bz2-level-1-single-stream",
    "bz2-level-1-fixed-64-kib-members",
    "bz2-level-3-single-stream",
    "bz2-level-3-fixed-64-kib-members",
    "bz2-level-6-single-stream",
    "bz2-level-6-fixed-64-kib-members",
    "bz2-level-9-single-stream",
]


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _run_cli(output: Path, policy_id: str, *, cwd: Path) -> dict[str, object]:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            str(EXAMPLE_ROOT / "run_v2_example.py"),
            "--output-dir",
            str(output),
            "--policy",
            policy_id,
        ],
        cwd=cwd,
        env=environment,
        capture_output=True,
        check=True,
        timeout=180.0,
    )
    assert completed.stderr == b""
    payload = json.loads(completed.stdout)
    assert type(payload) is dict
    assert completed.stdout == _canonical_json_bytes(payload)
    assert (output / "example-results.json").read_bytes() == completed.stdout
    return payload


def test_parameter_only_prior_formula_is_exact_complete_and_unique() -> None:
    candidates = build_candidates()
    utilities = build_prior_utility_map(candidates)

    assert len(candidates) == len(utilities) == len(set(utilities.values())) == 24
    assert PRIOR_UTILITY_FORMULA == "codec_base + level * 10 + single_stream_component"
    assert utilities["gzip-level-1-fixed-64-kib-members"] == 1010
    assert utilities["gzip-level-1-single-stream"] == 1011
    assert utilities["bz2-level-9-fixed-64-kib-members"] == 2090
    assert utilities["lzma-level-9-single-stream"] == 3091
    assert tuple(
        candidate_id
        for candidate_id, _ in sorted(utilities.items(), key=lambda item: item[1], reverse=True)[:8]
    ) == tuple(GREEDY_TOP_EIGHT)
    assert CORPUS_BYTE_COUNT == 145_258
    assert CORPUS_SHA256 == "b23ded0b042d8ccf288f3b4a255becec15c78f039b360d6a4529af24815d65ca"


@pytest.mark.parametrize(
    ("policy_id", "expected_order", "expected_seed"),
    [
        ("random", RANDOM_SELECTED_EIGHT, V2_RANDOM_POLICY_SEED),
        ("greedy_prior", GREEDY_TOP_EIGHT, None),
    ],
)
def test_v2_cli_interrupts_resumes_exports_and_replays_without_commands(
    tmp_path: Path,
    policy_id: str,
    expected_order: list[str],
    expected_seed: int | None,
) -> None:
    output = tmp_path / policy_id
    payload = _run_cli(output, policy_id, cwd=tmp_path)

    assert payload["run_spec_schema"] == "rde-core-run-spec/v2"
    assert payload["bundle_schema"] == "rde-core-run-bundle/v2"
    assert payload["replay_contract"] == "RECORDED_OBSERVATION_DECISION_REPLAY_V2"
    assert payload["candidate_count"] == 24
    assert payload["policy_id"] == policy_id
    assert payload["policy_seed"] == expected_seed
    assert payload["budget"] == 8
    assert payload["interruption_step"] == 4
    assert payload["interruption_resume"] is True
    assert payload["resume_mismatch_rejected"] is True
    assert payload["bundle_verified"] is True
    assert payload["original_command_count"] == 8
    assert payload["replay_command_count"] == 0
    assert payload["replay_adapter_execution_count"] == 0
    assert payload["replay_reported_command_execution_count"] == 0
    assert payload["replay_equivalent"] is True
    assert payload["adaptive_score_updates_enabled"] is False
    assert payload["selected_candidate_ids"] == expected_order
    assert type(payload["best_observed_objective"]) is float
    assert payload["best_observed_objective"] > 0.0
    assert type(payload["total_cost"]) is float
    assert payload["total_cost"] > 0.0
    assert len(str(payload["run_spec_fingerprint"])) == 64
    assert len(str(payload["bundle_sha256"])) == 64
    assert len(str(payload["steps_sha256"])) == 64
    assert len(str(payload["terminal_summary_sha256"])) == 64
    if policy_id == "greedy_prior":
        utility_map = payload["prior_utility_by_candidate_id"]
        assert type(utility_map) is dict
        assert len(utility_map) == len(set(utility_map.values())) == 24
        assert payload["prior_utility_formula"] == PRIOR_UTILITY_FORMULA
        assert payload["policy_semantic_classification"] == (
            "STATIC_TRUTH_FREE_PRIOR_UTILITY_GREEDY"
        )
    else:
        assert payload["prior_utility_by_candidate_id"] is None
        assert payload["prior_utility_formula"] is None

    assert (output / "original.sqlite3").is_file()
    assert (output / "run-bundle" / "run-bundle.json").is_file()
    sidecar = output / "run-bundle" / "run-bundle.json.sha256"
    assert sidecar.is_file()
    assert len(sidecar.read_bytes()) == 65
    assert (output / "replay" / "replay.sqlite3").is_file()
    assert (output / "command-count.txt").read_text(encoding="ascii") == "8\n"


def test_second_independent_greedy_run_is_byte_and_selection_deterministic(
    tmp_path: Path,
) -> None:
    first = _run_cli(tmp_path / "first-greedy", "greedy_prior", cwd=tmp_path)
    second = _run_cli(tmp_path / "second-greedy", "greedy_prior", cwd=tmp_path)

    assert first["selected_candidate_ids"] == second["selected_candidate_ids"] == (GREEDY_TOP_EIGHT)
    assert first["run_spec_fingerprint"] == second["run_spec_fingerprint"]
    assert first["bundle_sha256"] == second["bundle_sha256"]
    assert first["steps_sha256"] == second["steps_sha256"]
    assert first["terminal_summary_sha256"] == second["terminal_summary_sha256"]
    assert first["best_observed_objective"] == second["best_observed_objective"]
    assert first["total_cost"] == second["total_cost"]
    assert first["original_command_count"] == second["original_command_count"] == 8
    assert first["replay_command_count"] == second["replay_command_count"] == 0
