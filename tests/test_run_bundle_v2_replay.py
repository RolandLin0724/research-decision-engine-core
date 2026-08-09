from __future__ import annotations

import random
import subprocess
from pathlib import Path

import pytest

from research_decision_engine.generic_policies import PriorGreedyPolicy
from research_decision_engine.policies import _select_random_available
from research_decision_engine.policy_contracts import RUNSPEC_CANDIDATE_ORDER
from research_decision_engine.run_bundle_v2 import (
    CompletedWorkloadRunTraceV2,
    RunBundleV2ReplayError,
    _run_bundle_step_v2_from_completion,
    export_run_bundle_v2,
    replay_run_bundle_v2,
)
from research_decision_engine.run_spec import (
    CandidateSpec,
    CompletedWorkloadExperiment,
    NormalizedObservation,
)
from research_decision_engine.run_spec_v2 import RunSpecV2
from research_decision_engine.storage import ExperimentStore


def _spec(policy_id: str) -> RunSpecV2:
    candidates = (
        CandidateSpec("first", {"rank": 0}),
        CandidateSpec("second", {"rank": 1}),
        CandidateSpec("third", {"rank": 2}),
    )
    if policy_id == "random":
        config: dict[str, object] = {}
        seed: int | None = 20260804
    else:
        config = {
            "utility_by_candidate_id": {"first": 1, "second": 5, "third": 3},
            "tie_break": RUNSPEC_CANDIDATE_ORDER,
        }
        seed = None
    return RunSpecV2(
        candidates=candidates,
        policy_id=policy_id,
        policy_config=config,
        policy_seed=seed,
        experiment_count_budget=2,
        adapter_id="tests.must-not-execute",
        adapter_version="1",
        objective_name="score",
        objective_direction="maximize",
    )


def _select(spec: RunSpecV2, completed: set[str]) -> CandidateSpec:
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
        candidate = _select(spec, set(completed))
        record = CompletedWorkloadExperiment(
            run_spec_fingerprint=spec.fingerprint(),
            candidate=candidate,
            policy_id=spec.policy_id,
            observation=NormalizedObservation(10.0 + index, 0.5),
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


@pytest.mark.parametrize("policy_id", ["random", "greedy_prior"])
def test_v2_empty_directory_replay_is_equivalent_and_executes_no_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    policy_id: str,
) -> None:
    spec = _spec(policy_id)
    bundle_directory = tmp_path / f"{policy_id}-bundle"
    verification = export_run_bundle_v2(bundle_directory, trace=_trace(spec))
    opening_document = (bundle_directory / "run-bundle.json").read_bytes()
    opening_sidecar = (bundle_directory / "run-bundle.json.sha256").read_bytes()
    command_calls = 0

    def forbidden_command(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        del args, kwargs
        nonlocal command_calls
        command_calls += 1
        raise AssertionError("Replay must not execute a command.")

    monkeypatch.setattr(subprocess, "run", forbidden_command)
    destination = tmp_path / f"{policy_id}-replay"
    result = replay_run_bundle_v2(bundle_directory, destination)

    assert result.equivalent is True
    assert result.replay_contract == "RECORDED_OBSERVATION_DECISION_REPLAY_V2"
    assert result.bundle_sha256 == verification.bundle_sha256
    assert result.selected_candidate_ids == verification.selected_candidate_ids
    assert result.adapter_execution_count == 0
    assert result.command_execution_count == 0
    assert command_calls == 0
    assert {item.name for item in destination.iterdir()} == {"replay.sqlite3"}
    assert (bundle_directory / "run-bundle.json").read_bytes() == opening_document
    assert (bundle_directory / "run-bundle.json.sha256").read_bytes() == opening_sidecar

    with ExperimentStore(destination / "replay.sqlite3") as store:
        store.init_schema()
        history = store.list_workload_experiments(spec.fingerprint())
    assert tuple(record.candidate.candidate_id for record in history) == (
        result.selected_candidate_ids
    )
    assert all(record.policy_id == policy_id for record in history)


def test_v2_replay_rejects_tampered_sidecar_without_creating_destination(
    tmp_path: Path,
) -> None:
    bundle_directory = tmp_path / "bundle"
    export_run_bundle_v2(bundle_directory, trace=_trace(_spec("greedy_prior")))
    (bundle_directory / "run-bundle.json.sha256").write_bytes(b"0" * 64 + b"\n")
    destination = tmp_path / "replay"

    with pytest.raises(RunBundleV2ReplayError):
        replay_run_bundle_v2(bundle_directory, destination)
    assert not destination.exists()


def test_v2_replay_requires_an_empty_destination(tmp_path: Path) -> None:
    bundle_directory = tmp_path / "bundle"
    export_run_bundle_v2(bundle_directory, trace=_trace(_spec("random")))
    destination = tmp_path / "replay"
    destination.mkdir()
    marker = destination / "owned-by-caller"
    marker.write_text("preserve", encoding="utf-8")

    with pytest.raises(RunBundleV2ReplayError, match="empty"):
        replay_run_bundle_v2(bundle_directory, destination)
    assert marker.read_text(encoding="utf-8") == "preserve"
