from __future__ import annotations

import hashlib
import json
import platform
import random
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import cast

import pytest

import research_decision_engine
import research_decision_engine.run_bundle as run_bundle_module
import research_decision_engine.run_bundle_v2 as run_bundle_v2_module
import research_decision_engine.run_bundle_v3 as run_bundle_v3_module
from examples.command_adapter_compression.run_v2_example import PolicyIdV2, build_run_spec_v2
from research_decision_engine.generic_policies import PriorGreedyPolicy
from research_decision_engine.policies import _select_random_available
from research_decision_engine.policy_contracts import (
    INFORMATION_GAIN_TABLE_POLICY_ID,
    RUNSPEC_CANDIDATE_ORDER,
    RunBundleVersionMismatchError,
    UnsupportedPolicyForSchemaError,
)
from research_decision_engine.run_bundle import (
    RunBundleVerificationError,
    export_run_bundle,
    verify_run_bundle,
)
from research_decision_engine.run_bundle_v2 import (
    CompletedWorkloadRunTraceV2,
    RunBundleV2VerificationError,
    export_run_bundle_v2,
    verify_run_bundle_v2,
)
from research_decision_engine.run_spec import (
    CandidateSpec,
    CompletedWorkloadExperiment,
    NormalizedObservation,
    RunSpec,
)
from research_decision_engine.run_spec_v2 import RunSpecV2
from research_decision_engine.run_spec_v3 import RunSpecV3
from research_decision_engine.runner import _select_workload_candidate_v3
from tests.test_command_adapter_compression_v2_example import (
    GREEDY_TOP_EIGHT,
    RANDOM_SELECTED_EIGHT,
)
from tests.test_command_adapter_compression_v2_example import (
    _run_cli as _run_v2_cli,
)
from tests.test_run_bundle_v3 import _spec as _v3_spec
from tests.test_run_bundle_v3 import _trace as _v3_trace
from tests.test_v1_policy_golden import (
    FIXED_PRODUCER,
    RUN_BUNDLE_V1_BYTE_COUNT,
    RUN_BUNDLE_V1_SHA256,
    RUN_BUNDLE_V1_STEPS_SHA256,
    RUN_BUNDLE_V1_TERMINAL_SHA256,
    RUN_SPEC_V1_CANONICAL_BYTES,
    RUN_SPEC_V1_SHA256,
    _v1_run_spec,
    _v1_trace,
)

_V2_GOLDEN = {
    "random": {
        "run_spec": "0ca27c6e1d86e2a45cd40184eea6ce185eba6852afec906bf0aab0e718d53c3f",
        "bundle": "de8474a4bb74db706d21da25f15a4884333ed6b37d9f17b593497eeb7d497193",
        "steps": "e4d0eafcc1871947dfd6f8c9eec810cedf1557d7a3ff14653d3ae0f407e17ea8",
        "terminal": "fb10b5bf1e00edd536e550af3841786b563e89c58359ae574259d0b1ecc7b1ea",
    },
    "greedy_prior": {
        "run_spec": "e4765589a35b9e448f283de294ea0ed152b9d3d20edc728482443787d99634ab",
        "bundle": "002a436d86044538491c85ccd2990f43cddb018fc7ff26da0238e574c5d3bce8",
        "steps": "5edcda462ee7ce73f6fd3d0ff17df2e602aa325f924b76788f200870ad1cef24",
        "terminal": "b3070f53ee6dc39378c8036716d0633a49cedb4746a03c9091890d262eaada56",
    },
}


def _canonical(payload: object) -> bytes:
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


def test_v1_runspec_and_runbundle_remain_exact_golden_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _v1_run_spec()
    assert spec.to_canonical_bytes() == RUN_SPEC_V1_CANONICAL_BYTES
    assert spec.fingerprint() == RUN_SPEC_V1_SHA256
    assert hashlib.sha256(spec.to_canonical_bytes()).hexdigest() == RUN_SPEC_V1_SHA256

    monkeypatch.setattr(run_bundle_module, "_producer_payload", lambda: dict(FIXED_PRODUCER))
    destination = tmp_path / "v1"
    exported = export_run_bundle(destination, trace=_v1_trace(spec))
    encoded = (destination / "run-bundle.json").read_bytes()
    sidecar = (destination / "run-bundle.json.sha256").read_bytes()

    assert len(encoded) == RUN_BUNDLE_V1_BYTE_COUNT
    assert exported.bundle.to_canonical_bytes() == encoded
    assert exported.bundle_sha256 == hashlib.sha256(encoded).hexdigest() == RUN_BUNDLE_V1_SHA256
    assert exported.run_spec_sha256 == RUN_SPEC_V1_SHA256
    assert exported.steps_sha256 == RUN_BUNDLE_V1_STEPS_SHA256
    assert exported.terminal_summary_sha256 == RUN_BUNDLE_V1_TERMINAL_SHA256
    assert sidecar == f"{RUN_BUNDLE_V1_SHA256}\n".encode("ascii")
    assert len(sidecar) == 65
    assert verify_run_bundle(destination).bundle_sha256 == RUN_BUNDLE_V1_SHA256
    assert exported.selected_candidate_ids == ("candidate-b", "候选-c")


@pytest.mark.parametrize(
    ("policy_id", "expected_order"),
    [
        ("random", RANDOM_SELECTED_EIGHT),
        ("greedy_prior", GREEDY_TOP_EIGHT),
    ],
)
def test_v2_runspec_bundle_sections_sidecar_and_behavior_remain_golden(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    policy_id: str,
    expected_order: list[str],
) -> None:
    expected = _V2_GOLDEN[policy_id]
    spec = build_run_spec_v2(cast(PolicyIdV2, policy_id))
    spec_bytes = spec.to_canonical_bytes()
    assert RunSpecV2.from_canonical_bytes(spec_bytes).to_canonical_bytes() == spec_bytes
    assert spec.fingerprint() == hashlib.sha256(spec_bytes).hexdigest() == expected["run_spec"]

    destination = tmp_path / policy_id
    result = _run_v2_cli(destination, policy_id, cwd=tmp_path)
    encoded = (destination / "run-bundle" / "run-bundle.json").read_bytes()
    sidecar = (destination / "run-bundle" / "run-bundle.json.sha256").read_bytes()
    bundle_payload = json.loads(encoded)

    assert encoded == _canonical(bundle_payload)
    actual_bundle_sha256 = hashlib.sha256(encoded).hexdigest()
    assert actual_bundle_sha256 == result["bundle_sha256"]
    assert result["run_spec_fingerprint"] == expected["run_spec"]
    assert result["steps_sha256"] == expected["steps"]
    assert result["terminal_summary_sha256"] == expected["terminal"]
    assert bundle_payload["section_sha256"] == {
        "run_spec": expected["run_spec"],
        "steps": expected["steps"],
        "terminal_summary": expected["terminal"],
    }
    assert bundle_payload["producer"] == {
        "package_name": "research-decision-engine",
        "package_version": research_decision_engine.__version__,
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
    }
    assert (
        bundle_payload["producer"]["package_version"]
        == importlib_metadata.version("research-decision-engine")
        == "1.0.0rc5"
    )
    assert sidecar == f"{actual_bundle_sha256}\n".encode("ascii")
    assert len(sidecar) == 65
    assert result["selected_candidate_ids"] == expected_order
    assert result["bundle_verified"] is True
    assert result["replay_equivalent"] is True
    assert result["replay_command_count"] == 0

    golden_payload = json.loads(encoded)
    golden_payload["producer"]["package_version"] = "0.1.0"
    golden_payload["producer"]["python_version"] = "3.12.13"
    assert hashlib.sha256(_canonical(golden_payload)).hexdigest() == expected["bundle"]

    verified = verify_run_bundle_v2(destination / "run-bundle")
    assert verified.bundle_sha256 == actual_bundle_sha256
    assert verified.bundle.terminal_summary["stop_reason"] == "experiment_budget_exhausted"
    trace = CompletedWorkloadRunTraceV2(
        run_spec=verified.bundle.run_spec,
        steps=verified.bundle.steps,
        stop_reason="experiment_budget_exhausted",
    )
    alternate_producer = dict(verified.bundle.producer)
    alternate_producer["package_version"] = "0.1.0"
    monkeypatch.setattr(
        run_bundle_v2_module,
        "_producer_payload",
        lambda: dict(alternate_producer),
    )
    variant_destination = tmp_path / f"{policy_id}-producer-variant"
    variant = export_run_bundle_v2(variant_destination, trace=trace)
    variant_encoded = (variant_destination / "run-bundle.json").read_bytes()
    variant_sidecar = (variant_destination / "run-bundle.json.sha256").read_bytes()
    variant_payload = json.loads(variant_encoded)

    assert variant_encoded == _canonical(variant_payload)
    assert variant.bundle_sha256 == hashlib.sha256(variant_encoded).hexdigest()
    assert variant.bundle_sha256 != actual_bundle_sha256
    assert variant_sidecar == f"{variant.bundle_sha256}\n".encode("ascii")
    assert len(variant_sidecar) == 65
    assert verify_run_bundle_v2(variant_destination).bundle_sha256 == variant.bundle_sha256
    assert variant.run_spec_sha256 == verified.run_spec_sha256 == expected["run_spec"]
    assert variant.steps_sha256 == verified.steps_sha256 == expected["steps"]
    assert (
        variant.terminal_summary_sha256 == verified.terminal_summary_sha256 == expected["terminal"]
    )
    assert variant_payload["producer"] == alternate_producer
    assert (
        variant_payload["producer"]["package_version"]
        != bundle_payload["producer"]["package_version"]
    )
    baseline_without_producer = dict(bundle_payload)
    variant_without_producer = dict(variant_payload)
    del baseline_without_producer["producer"]
    del variant_without_producer["producer"]
    assert variant_without_producer == baseline_without_producer
    assert (
        variant.selected_candidate_ids == verified.selected_candidate_ids == tuple(expected_order)
    )
    assert variant.bundle.run_spec == verified.bundle.run_spec
    assert variant.bundle.steps == verified.bundle.steps
    assert dict(variant.bundle.terminal_summary) == dict(verified.bundle.terminal_summary)
    assert dict(variant.bundle.section_sha256) == dict(verified.bundle.section_sha256)


def test_v1_v2_reject_information_gain_and_all_runspec_decoders_remain_separate() -> None:
    candidate = CandidateSpec("candidate", {})
    with pytest.raises(ValueError, match="v1 supports only.*random"):
        RunSpec(
            candidates=(candidate,),
            policy_id=INFORMATION_GAIN_TABLE_POLICY_ID,
            policy_config={},
            policy_seed=1,
            experiment_count_budget=1,
            adapter_id="adapter",
            adapter_version="1",
            objective_name="score",
            objective_direction="maximize",
        )
    with pytest.raises(UnsupportedPolicyForSchemaError):
        RunSpecV2(
            candidates=(candidate,),
            policy_id=INFORMATION_GAIN_TABLE_POLICY_ID,
            policy_config={},
            policy_seed=None,
            experiment_count_budget=1,
            adapter_id="adapter",
            adapter_version="1",
            objective_name="score",
            objective_direction="maximize",
        )

    v1 = _v1_run_spec().to_canonical_bytes()
    v2 = build_run_spec_v2("random").to_canonical_bytes()
    v3 = RunSpecV3(
        candidates=(candidate,),
        policy_id="random",
        policy_config={},
        policy_seed=7,
        experiment_count_budget=1,
        adapter_id="adapter",
        adapter_version="1",
        objective_name="score",
        objective_direction="maximize",
    ).to_canonical_bytes()
    assert RunSpec.from_canonical_bytes(v1).to_canonical_bytes() == v1
    assert RunSpecV2.from_canonical_bytes(v2).to_canonical_bytes() == v2
    assert RunSpecV3.from_canonical_bytes(v3).to_canonical_bytes() == v3
    for decoder, foreign in (
        (RunSpec.from_canonical_bytes, v2),
        (RunSpec.from_canonical_bytes, v3),
        (RunSpecV2.from_canonical_bytes, v1),
        (RunSpecV2.from_canonical_bytes, v3),
        (RunSpecV3.from_canonical_bytes, v1),
        (RunSpecV3.from_canonical_bytes, v2),
    ):
        with pytest.raises(ValueError):
            decoder(foreign)


def test_v1_and_v2_bundle_verifiers_do_not_silently_cross_versions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_v1_producer = run_bundle_module._producer_payload
    monkeypatch.setattr(run_bundle_module, "_producer_payload", lambda: dict(FIXED_PRODUCER))
    v1_directory = tmp_path / "v1"
    export_run_bundle(v1_directory, trace=_v1_trace(_v1_run_spec()))
    v2_output = tmp_path / "v2-output"
    _run_v2_cli(v2_output, "random", cwd=tmp_path)
    v2_directory = v2_output / "run-bundle"

    with pytest.raises(RunBundleVerificationError):
        verify_run_bundle(v2_directory)
    with pytest.raises((RunBundleV2VerificationError, RunBundleVersionMismatchError)):
        verify_run_bundle_v2(v1_directory)

    monkeypatch.setattr(run_bundle_module, "_producer_payload", active_v1_producer)
    active_v1_directory = tmp_path / "active-v1"
    active_v1 = export_run_bundle(
        active_v1_directory,
        trace=_v1_trace(_v1_run_spec()),
    )
    active_v3_directory = tmp_path / "active-v3"
    active_v3 = run_bundle_v3_module.export_run_bundle_v3(
        active_v3_directory,
        trace=_v3_trace(_v3_spec("random")),
    )
    active_v2 = verify_run_bundle_v2(v2_directory)
    active_version = importlib_metadata.version("research-decision-engine")
    assert active_version == research_decision_engine.__version__ == "1.0.0rc5"
    assert active_v1.bundle.producer["package_version"] == active_version
    assert active_v2.bundle.producer["package_version"] == active_version
    assert active_v3.bundle.producer["package_version"] == active_version
    assert verify_run_bundle(active_v1_directory).bundle_sha256 == active_v1.bundle_sha256
    assert (
        run_bundle_v3_module.verify_run_bundle_v3(active_v3_directory).bundle_sha256
        == active_v3.bundle_sha256
    )
    replay_v3 = run_bundle_v3_module.replay_run_bundle_v3(
        active_v3_directory,
        tmp_path / "active-v3-replay",
    )
    assert replay_v3.adapter_execution_count == 0
    assert replay_v3.callable_execution_count == 0
    assert replay_v3.command_execution_count == 0


@pytest.mark.parametrize(
    ("policy_id", "config", "seed"),
    [
        ("random", {}, 20260804),
        (
            "greedy_prior",
            {
                "utility_by_candidate_id": {"c0": 7, "c1": 7, "c2": 3, "c3": 1},
                "tie_break": RUNSPEC_CANDIDATE_ORDER,
            },
            None,
        ),
    ],
)
def test_v3_random_and_greedy_selection_sequences_equal_v2(
    policy_id: str,
    config: dict[str, object],
    seed: int | None,
) -> None:
    candidates = tuple(CandidateSpec(f"c{index}", {"index": index}) for index in range(4))
    common = {
        "candidates": candidates,
        "policy_id": policy_id,
        "policy_config": config,
        "policy_seed": seed,
        "experiment_count_budget": 4,
        "adapter_id": "adapter",
        "adapter_version": "1",
        "objective_name": "score",
        "objective_direction": "maximize",
    }
    v2 = RunSpecV2(**common)  # type: ignore[arg-type]
    v3 = RunSpecV3(**common)  # type: ignore[arg-type]
    completed_ids: set[str] = set()
    v3_history: list[CompletedWorkloadExperiment] = []
    v2_order: list[str] = []
    v3_order: list[str] = []
    for step in range(4):
        if policy_id == "random":
            assert type(v2.policy_seed) is int
            selected_v2 = _select_random_available(
                v2.candidates,
                completed_ids,
                random.Random(v2.policy_seed),
            )
        else:
            selected_v2 = PriorGreedyPolicy(v2).select(completed_ids)
        selected_v3 = _select_workload_candidate_v3(v3, v3_history)
        assert selected_v3.candidate_id == selected_v2.candidate_id
        v2_order.append(selected_v2.candidate_id)
        v3_order.append(selected_v3.candidate_id)
        completed_ids.add(selected_v2.candidate_id)
        v3_history.append(
            CompletedWorkloadExperiment(
                run_spec_fingerprint=v3.fingerprint(),
                candidate=selected_v3,
                policy_id=policy_id,
                observation=NormalizedObservation(float(step), 0.0),
                created_at="2026-08-04T00:00:00+00:00",
            )
        )

    assert v3_order == v2_order
