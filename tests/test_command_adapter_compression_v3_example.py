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
from examples.command_adapter_compression.run_v3_example import (
    HYPOTHESIS_CODEC,
    INFORMATION_GAIN_HYPOTHESIS_IDS,
    INFORMATION_GAIN_LIKELIHOOD_ROW_TOTAL,
    INFORMATION_GAIN_OBSERVATION_METRIC,
    INFORMATION_GAIN_OUTCOME_IDS,
    INFORMATION_GAIN_OUTCOME_THRESHOLDS,
    INFORMATION_GAIN_PRIOR_WEIGHTS,
    MATCHING_LIKELIHOOD_WEIGHTS,
    NONMATCHING_LIKELIHOOD_WEIGHTS,
    V3_RANDOM_POLICY_SEED,
    build_information_gain_evidence_model,
)

EXAMPLE_ROOT = Path(__file__).parents[1] / "examples" / "command_adapter_compression"


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
            str(EXAMPLE_ROOT / "run_v3_example.py"),
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


def test_v3_evidence_model_is_the_exact_fixed_24_by_3_by_3_table() -> None:
    candidates = build_candidates()
    model = build_information_gain_evidence_model(candidates)
    payload = model.to_payload()

    assert len(candidates) == 24
    assert len({candidate.candidate_id for candidate in candidates}) == 24
    assert (
        model.hypothesis_ids
        == INFORMATION_GAIN_HYPOTHESIS_IDS
        == (
            "gzip_dominant",
            "bz2_dominant",
            "lzma_dominant",
        )
    )
    assert (
        dict(model.prior_weight_by_hypothesis)
        == INFORMATION_GAIN_PRIOR_WEIGHTS
        == {
            "gzip_dominant": 1,
            "bz2_dominant": 1,
            "lzma_dominant": 1,
        }
    )
    assert model.observation_metric == INFORMATION_GAIN_OBSERVATION_METRIC == "compression_ratio"
    assert model.outcome_ids == INFORMATION_GAIN_OUTCOME_IDS == ("low", "medium", "high")
    assert model.outcome_thresholds == INFORMATION_GAIN_OUTCOME_THRESHOLDS == (2.0, 3.0)
    assert model.likelihood_row_total == INFORMATION_GAIN_LIKELIHOOD_ROW_TOTAL == 20
    assert frozenset(payload) == frozenset(
        {
            "hypothesis_ids",
            "prior_weight_by_hypothesis",
            "observation_metric",
            "outcome_ids",
            "outcome_thresholds",
            "likelihood_row_total",
            "likelihood_weight_by_candidate_id",
        }
    )
    assert len(model.likelihood_weight_by_candidate_id) == 24
    for candidate in candidates:
        codec = candidate.parameters["codec"]
        for hypothesis_id in INFORMATION_GAIN_HYPOTHESIS_IDS:
            expected = (
                MATCHING_LIKELIHOOD_WEIGHTS
                if codec == HYPOTHESIS_CODEC[hypothesis_id]
                else NONMATCHING_LIKELIHOOD_WEIGHTS
            )
            assert (
                dict(model.likelihood_weight_by_candidate_id[candidate.candidate_id][hypothesis_id])
                == expected
            )
    assert CORPUS_BYTE_COUNT == 145_258
    assert CORPUS_SHA256 == "b23ded0b042d8ccf288f3b4a255becec15c78f039b360d6a4529af24815d65ca"


@pytest.mark.parametrize(
    ("policy_id", "expected_seed"),
    [
        ("random", V3_RANDOM_POLICY_SEED),
        ("greedy_prior", None),
        ("information_gain_table", None),
    ],
)
def test_v3_cpu_policy_interrupts_resumes_finishes_and_replays_without_commands(
    tmp_path: Path,
    policy_id: str,
    expected_seed: int | None,
) -> None:
    output = tmp_path / policy_id
    payload = _run_cli(output, policy_id, cwd=tmp_path)
    candidate_ids = {candidate.candidate_id for candidate in build_candidates()}
    selected = payload["selected_candidate_ids"]

    assert payload["run_spec_schema"] == "rde-core-run-spec/v3"
    assert payload["bundle_schema"] == "rde-core-run-bundle/v3"
    assert payload["replay_contract"] == "RECORDED_OBSERVATION_DECISION_REPLAY_V3"
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
    assert payload["belief_lineage_equal"] is True
    assert payload["adaptive_likelihood_updates_enabled"] is False
    assert payload["dynamic_policy_loading_enabled"] is False
    assert payload["hidden_truth_exposure_count"] == 0
    assert type(selected) is list
    assert len(selected) == len(set(selected)) == 8
    assert set(selected) <= candidate_ids
    assert type(payload["best_observed_objective"]) is float
    assert payload["best_observed_objective"] > 0.0
    assert type(payload["total_cost"]) is float
    assert payload["total_cost"] > 0.0
    for digest_key in (
        "run_spec_fingerprint",
        "bundle_sha256",
        "steps_sha256",
        "terminal_summary_sha256",
    ):
        assert len(str(payload[digest_key])) == 64

    if policy_id == "information_gain_table":
        assert len(str(payload["evidence_model_fingerprint"])) == 64
        assert payload["evidence_model"] == build_information_gain_evidence_model().to_payload()
        assert payload["policy_semantic_classification"] == (
            "USER_DECLARED_FINITE_HYPOTHESIS_OUTCOME_LIKELIHOOD_TABLE"
        )
    else:
        assert payload["evidence_model"] is None
        assert payload["evidence_model_fingerprint"] is None

    assert (output / "original.sqlite3").is_file()
    assert (output / "run-bundle" / "run-bundle.json").is_file()
    sidecar = output / "run-bundle" / "run-bundle.json.sha256"
    assert sidecar.is_file()
    assert len(sidecar.read_bytes()) == 65
    assert (output / "replay" / "replay.sqlite3").is_file()
    assert (output / "command-count.txt").read_text(encoding="ascii") == "8\n"


def test_second_independent_information_gain_run_is_fully_deterministic(
    tmp_path: Path,
) -> None:
    first = _run_cli(tmp_path / "first-information-gain", "information_gain_table", cwd=tmp_path)
    second = _run_cli(tmp_path / "second-information-gain", "information_gain_table", cwd=tmp_path)

    for key in (
        "selected_candidate_ids",
        "run_spec_fingerprint",
        "evidence_model_fingerprint",
        "bundle_sha256",
        "steps_sha256",
        "terminal_summary_sha256",
        "best_observed_objective",
        "total_cost",
    ):
        assert first[key] == second[key]
    assert first["original_command_count"] == second["original_command_count"] == 8
    assert first["replay_command_count"] == second["replay_command_count"] == 0
    assert first["replay_adapter_execution_count"] == second["replay_adapter_execution_count"] == 0
    assert (
        first["replay_reported_command_execution_count"]
        == (second["replay_reported_command_execution_count"])
        == 0
    )
