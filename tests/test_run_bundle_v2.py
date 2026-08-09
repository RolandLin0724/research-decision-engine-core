from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any, cast

import pytest

from research_decision_engine.generic_policies import PriorGreedyPolicy
from research_decision_engine.policies import _select_random_available
from research_decision_engine.policy_contracts import (
    REPLAY_CONTRACT_V2,
    RUN_BUNDLE_V2_SCHEMA,
    RUN_SPEC_V2_SCHEMA,
    RUNSPEC_CANDIDATE_ORDER,
    RunBundleVersionMismatchError,
)
from research_decision_engine.run_bundle_v2 import (
    CompletedWorkloadRunTraceV2,
    RunBundleV2ValidationError,
    RunBundleV2VerificationError,
    _run_bundle_step_v2_from_completion,
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


def _spec(policy_id: str) -> RunSpecV2:
    candidates = (
        CandidateSpec("true_value", {"rank": 0}),
        CandidateSpec("beta", {"rank": 1}),
        CandidateSpec("gamma", {"rank": 2}),
    )
    if policy_id == "random":
        config: dict[str, object] = {}
        seed: int | None = 20260804
    else:
        config = {
            "utility_by_candidate_id": {"true_value": 9, "beta": 9, "gamma": 1},
            "tie_break": RUNSPEC_CANDIDATE_ORDER,
        }
        seed = None
    return RunSpecV2(
        candidates=candidates,
        policy_id=policy_id,
        policy_config=config,
        policy_seed=seed,
        experiment_count_budget=2,
        adapter_id="tests.recorded-only",
        adapter_version="1",
        objective_name="score",
        objective_direction="maximize",
    )


def _selected(spec: RunSpecV2, completed: set[str]) -> CandidateSpec:
    if spec.policy_id == "greedy_prior":
        return PriorGreedyPolicy(spec).select(completed)
    assert type(spec.policy_seed) is int
    return _select_random_available(
        spec.candidates,
        completed,
        random.Random(spec.policy_seed),
    )


def _trace(spec: RunSpecV2) -> CompletedWorkloadRunTraceV2:
    completed: list[str] = []
    cumulative_cost = 0.0
    steps = []
    for index in range(spec.experiment_count_budget):
        candidate = _selected(spec, set(completed))
        record = CompletedWorkloadExperiment(
            run_spec_fingerprint=spec.fingerprint(),
            candidate=candidate,
            policy_id=spec.policy_id,
            observation=NormalizedObservation(float(index + 1), 1.0),
            created_at="2026-08-04T00:00:00+00:00",
        )
        step = _run_bundle_step_v2_from_completion(
            run_spec=spec,
            record=record,
            completed_candidate_ids=completed,
            cumulative_cost=cumulative_cost,
        )
        steps.append(step)
        completed.append(candidate.candidate_id)
        cumulative_cost = step.cumulative_cost
    return CompletedWorkloadRunTraceV2(
        run_spec=spec,
        steps=steps,
        stop_reason="experiment_budget_exhausted",
    )


def _resign(directory: Path, payload: dict[str, Any]) -> None:
    encoded = _canonical(payload)
    (directory / "run-bundle.json").write_bytes(encoded)
    (directory / "run-bundle.json.sha256").write_bytes(
        hashlib.sha256(encoded).hexdigest().encode("ascii") + b"\n"
    )


@pytest.mark.parametrize("policy_id", ["random", "greedy_prior"])
def test_v2_export_has_exact_schema_layout_and_static_policy_binding(
    tmp_path: Path, policy_id: str
) -> None:
    spec = _spec(policy_id)
    destination = tmp_path / policy_id
    result = export_run_bundle_v2(destination, trace=_trace(spec))

    assert {item.name for item in destination.iterdir()} == {
        "run-bundle.json",
        "run-bundle.json.sha256",
    }
    assert (destination / "run-bundle.json.sha256").stat().st_size == 65
    assert result.valid is True
    assert result.bundle.schema_version == RUN_BUNDLE_V2_SCHEMA
    assert result.bundle.replay_contract == REPLAY_CONTRACT_V2
    assert result.bundle.run_spec.schema == RUN_SPEC_V2_SCHEMA
    assert result.bundle.run_spec == spec
    assert verify_run_bundle_v2(destination).bundle_sha256 == result.bundle_sha256

    for step in result.bundle.steps:
        assert step.decision["policy_id"] == policy_id
        assert step.rationale["policy_id"] == policy_id
        assert step.decision["selected_candidate_id"] == step.selected_candidate_id
        assert step.rationale["selected_candidate_id"] == step.selected_candidate_id
        assert step.decision["tie_break"] == RUNSPEC_CANDIDATE_ORDER
        assert step.rationale["tie_break"] == RUNSPEC_CANDIDATE_ORDER
        assert step.decision["eligible_candidate_count"] == len(
            cast(list[object], step.rationale["eligible_candidate_ids"])
        )
    if policy_id == "greedy_prior":
        assert result.selected_candidate_ids == ("true_value", "beta")
        assert [step.decision["selected_prior_utility"] for step in result.bundle.steps] == [
            9,
            9,
        ]
    else:
        assert all(step.decision["selected_prior_utility"] is None for step in result.bundle.steps)


def test_v2_schema_aware_truth_scan_exempts_only_utility_candidate_ids(
    tmp_path: Path,
) -> None:
    valid = _spec("greedy_prior")
    export_run_bundle_v2(tmp_path / "valid", trace=_trace(valid))

    invalid = RunSpecV2(
        candidates=(CandidateSpec("candidate", {"hidden_truth": 7}),),
        policy_id="greedy_prior",
        policy_config={
            "utility_by_candidate_id": {"candidate": 1},
            "tie_break": RUNSPEC_CANDIDATE_ORDER,
        },
        policy_seed=None,
        experiment_count_budget=1,
        adapter_id="tests.recorded-only",
        adapter_version="1",
        objective_name="score",
        objective_direction="maximize",
    )
    trace = CompletedWorkloadRunTraceV2(
        run_spec=invalid,
        steps=(),
        stop_reason="stopped_by_caller",
    )
    with pytest.raises(RunBundleV2ValidationError, match="hidden-truth"):
        export_run_bundle_v2(tmp_path / "invalid", trace=trace)


def test_v2_verify_rejects_resigned_utility_tampering(tmp_path: Path) -> None:
    destination = tmp_path / "bundle"
    export_run_bundle_v2(destination, trace=_trace(_spec("greedy_prior")))
    payload = cast(
        dict[str, Any],
        json.loads((destination / "run-bundle.json").read_text(encoding="utf-8")),
    )
    utility_map = payload["run_spec"]["policy"]["config"]["utility_by_candidate_id"]
    utility_map["gamma"] = 100
    run_spec_bytes = _canonical(payload["run_spec"])
    run_spec_sha256 = hashlib.sha256(run_spec_bytes).hexdigest()
    payload["run_spec_sha256"] = run_spec_sha256
    payload["section_sha256"]["run_spec"] = run_spec_sha256
    _resign(destination, payload)

    with pytest.raises(RunBundleV2VerificationError):
        verify_run_bundle_v2(destination)


def test_v2_verify_rejects_fully_resigned_selected_candidate_tampering(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "bundle"
    export_run_bundle_v2(destination, trace=_trace(_spec("greedy_prior")))
    payload = cast(
        dict[str, Any],
        json.loads((destination / "run-bundle.json").read_text(encoding="utf-8")),
    )
    first = payload["steps"][0]
    first["selected_candidate_id"] = "gamma"
    first["decision"]["selected_candidate_id"] = "gamma"
    first["decision"]["selected_prior_utility"] = 1
    first["rationale"]["selected_candidate_id"] = "gamma"
    first["rationale"]["selected_prior_utility"] = 1
    first["observation"]["candidate_id"] = "gamma"
    payload["terminal_summary"]["selected_candidate_ids"][0] = "gamma"

    steps_sha256 = hashlib.sha256(_canonical(payload["steps"])).hexdigest()
    payload["section_sha256"]["steps"] = steps_sha256
    payload["terminal_summary"]["decision_history_sha256"] = steps_sha256
    payload["section_sha256"]["terminal_summary"] = hashlib.sha256(
        _canonical(payload["terminal_summary"])
    ).hexdigest()
    _resign(destination, payload)

    with pytest.raises(RunBundleV2VerificationError):
        verify_run_bundle_v2(destination)


def test_v2_rejects_v1_runspec_and_bundle_schema_alias(tmp_path: Path) -> None:
    v1 = RunSpec(
        candidates=(CandidateSpec("only", {}),),
        policy_id="random",
        policy_config={},
        policy_seed=1,
        experiment_count_budget=1,
        adapter_id="tests",
        adapter_version="1",
        objective_name="score",
        objective_direction="maximize",
    )
    with pytest.raises(RunBundleVersionMismatchError):
        CompletedWorkloadRunTraceV2(
            run_spec=cast(Any, v1),
            steps=(),
            stop_reason="stopped_by_caller",
        )

    destination = tmp_path / "bundle"
    export_run_bundle_v2(destination, trace=_trace(_spec("random")))
    payload = cast(
        dict[str, Any],
        json.loads((destination / "run-bundle.json").read_text(encoding="utf-8")),
    )
    payload["schema_version"] = "rde-core-run-bundle/v1"
    _resign(destination, payload)
    with pytest.raises(RunBundleVersionMismatchError):
        verify_run_bundle_v2(destination)
