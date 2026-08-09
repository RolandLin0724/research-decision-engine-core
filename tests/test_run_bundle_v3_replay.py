from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

import research_decision_engine.run_bundle_v3 as run_bundle_v3_module
from research_decision_engine.adapters import PythonFunctionAdapter
from research_decision_engine.command_adapter import CommandAdapter
from research_decision_engine.information_gain_table import FiniteTableEvidenceModel
from research_decision_engine.run_bundle import (
    _remove_owned_replay_database as _original_remove_owned_replay_database,
)
from research_decision_engine.run_bundle_v3 import (
    CompletedWorkloadRunTraceV3,
    RunBundleV3ReplayError,
    _run_bundle_step_v3_from_completion,
    _selection_for_v3,
    _steps_from_history,
    export_run_bundle_v3,
    replay_run_bundle_v3,
)
from research_decision_engine.run_spec import (
    CandidateSpec,
    CompletedWorkloadExperiment,
    NormalizedObservation,
)
from research_decision_engine.run_spec_v3 import RunSpecV3
from research_decision_engine.storage import SCHEMA_VERSION, ExperimentStore

POLICY_IDS = ("random", "greedy_prior", "information_gain_table")


def _spec(policy_id: str) -> RunSpecV3:
    candidates = (
        CandidateSpec("first", {"rank": 0}),
        CandidateSpec("second", {"rank": 1}),
        CandidateSpec("third", {"rank": 2}),
    )
    if policy_id == "random":
        config: dict[str, object] = {}
        seed: int | None = 20260804
    elif policy_id == "greedy_prior":
        config = {
            "utility_by_candidate_id": {"first": 1, "second": 5, "third": 3},
            "tie_break": "runspec_candidate_order",
        }
        seed = None
    else:
        model = FiniteTableEvidenceModel(
            hypothesis_ids=("left", "right"),
            prior_weight_by_hypothesis={"left": 1, "right": 1},
            observation_metric="score",
            outcome_ids=("low", "high"),
            outcome_thresholds=(0.5,),
            likelihood_row_total=10,
            likelihood_weight_by_candidate_id={
                "first": {
                    "left": {"low": 9, "high": 1},
                    "right": {"low": 1, "high": 9},
                },
                "second": {
                    "left": {"low": 8, "high": 2},
                    "right": {"low": 2, "high": 8},
                },
                "third": {
                    "left": {"low": 5, "high": 5},
                    "right": {"low": 5, "high": 5},
                },
            },
        )
        config = {
            "evidence_model": model.to_payload(),
            "tie_break": "runspec_candidate_order",
        }
        seed = None
    return RunSpecV3(
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


def _trace(spec: RunSpecV3) -> CompletedWorkloadRunTraceV3:
    history: list[CompletedWorkloadExperiment] = []
    steps = []
    cumulative_cost = 0.0
    for index in range(spec.experiment_count_budget):
        selection = _selection_for_v3(spec, history)
        record = CompletedWorkloadExperiment(
            run_spec_fingerprint=spec.fingerprint(),
            candidate=selection.candidate,
            policy_id=spec.policy_id,
            observation=NormalizedObservation(0.2 if index == 0 else 0.8, cost=0.5),
            created_at="2026-08-04T00:00:00+00:00",
        )
        step = _run_bundle_step_v3_from_completion(
            run_spec=spec,
            record=record,
            completed_history=history,
            cumulative_cost=cumulative_cost,
        )
        history.append(record)
        steps.append(step)
        cumulative_cost = step.cumulative_cost
    return CompletedWorkloadRunTraceV3(
        run_spec=spec,
        steps=steps,
        stop_reason="experiment_budget_exhausted",
    )


@pytest.mark.parametrize("policy_id", POLICY_IDS)
def test_v3_empty_directory_replay_is_exact_and_executes_nothing(
    policy_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec(policy_id)
    bundle_directory = tmp_path / f"{policy_id}-bundle"
    verification = export_run_bundle_v3(bundle_directory, trace=_trace(spec))
    opening_document = (bundle_directory / "run-bundle.json").read_bytes()
    opening_sidecar = (bundle_directory / "run-bundle.json.sha256").read_bytes()
    counters = {"python": 0, "command_adapter": 0, "run": 0, "popen": 0}

    def forbidden_python(*args: object, **kwargs: object) -> NormalizedObservation:
        del args, kwargs
        counters["python"] += 1
        raise AssertionError("Replay must not call PythonFunctionAdapter.")

    def forbidden_command_adapter(*args: object, **kwargs: object) -> NormalizedObservation:
        del args, kwargs
        counters["command_adapter"] += 1
        raise AssertionError("Replay must not call CommandAdapter.")

    def forbidden_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        del args, kwargs
        counters["run"] += 1
        raise AssertionError("Replay must not call subprocess.run.")

    def forbidden_popen(*args: object, **kwargs: object) -> object:
        del args, kwargs
        counters["popen"] += 1
        raise AssertionError("Replay must not call subprocess.Popen.")

    monkeypatch.setattr(PythonFunctionAdapter, "evaluate", forbidden_python)
    monkeypatch.setattr(CommandAdapter, "evaluate", forbidden_command_adapter)
    monkeypatch.setattr(subprocess, "run", forbidden_run)
    monkeypatch.setattr(subprocess, "Popen", forbidden_popen)

    destination = tmp_path / f"{policy_id}-replay"
    result = replay_run_bundle_v3(bundle_directory, destination)

    assert result.equivalent is True
    assert result.replay_contract == "RECORDED_OBSERVATION_DECISION_REPLAY_V3"
    assert result.bundle_sha256 == verification.bundle_sha256
    assert result.run_spec_sha256 == spec.fingerprint()
    assert result.adapter_execution_count == 0
    assert result.callable_execution_count == 0
    assert result.command_execution_count == 0
    assert counters == {"python": 0, "command_adapter": 0, "run": 0, "popen": 0}
    assert {item.name for item in destination.iterdir()} == {"replay.sqlite3"}
    assert (bundle_directory / "run-bundle.json").read_bytes() == opening_document
    assert (bundle_directory / "run-bundle.json.sha256").read_bytes() == opening_sidecar

    with ExperimentStore(destination / "replay.sqlite3") as store:
        assert store.schema_version() == SCHEMA_VERSION == 6
        history = store.list_workload_experiments(spec.fingerprint())
        rebuilt_steps = _steps_from_history(spec, history)
    assert tuple(record.candidate.candidate_id for record in history) == (
        result.selected_candidate_ids
    )
    assert [step.to_payload() for step in rebuilt_steps] == [
        step.to_payload() for step in verification.bundle.steps
    ]
    assert [step.belief_lineage for step in rebuilt_steps] == [
        step.belief_lineage for step in verification.bundle.steps
    ]


def test_v3_replay_rejects_tampered_sidecar_before_destination_creation(
    tmp_path: Path,
) -> None:
    bundle_directory = tmp_path / "bundle"
    export_run_bundle_v3(bundle_directory, trace=_trace(_spec("information_gain_table")))
    (bundle_directory / "run-bundle.json.sha256").write_bytes(b"0" * 64 + b"\n")
    destination = tmp_path / "replay"

    with pytest.raises(RunBundleV3ReplayError, match="verification"):
        replay_run_bundle_v3(bundle_directory, destination)
    assert not destination.exists()


def test_v3_replay_requires_empty_destination_and_preserves_foreign_content(
    tmp_path: Path,
) -> None:
    bundle_directory = tmp_path / "bundle"
    export_run_bundle_v3(bundle_directory, trace=_trace(_spec("random")))
    destination = tmp_path / "replay"
    destination.mkdir()
    marker = destination / "caller-owned"
    marker.write_text("preserve", encoding="utf-8")

    with pytest.raises(RunBundleV3ReplayError, match="empty"):
        replay_run_bundle_v3(bundle_directory, destination)
    assert marker.read_text(encoding="utf-8") == "preserve"


def test_v3_replay_rechecks_exact_destination_inventory_before_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_directory = tmp_path / "bundle"
    export_run_bundle_v3(bundle_directory, trace=_trace(_spec("random")))
    destination = tmp_path / "replay"
    injected = False

    def remove_then_inject(path: Path, *, expected_identity: tuple[int, int]) -> bool:
        nonlocal injected
        removed = _original_remove_owned_replay_database(path, expected_identity=expected_identity)
        if removed and not injected and path.name.startswith(".replay.sqlite3.tmp-"):
            (destination / "concurrent-foreign-file").write_text("preserve", encoding="utf-8")
            injected = True
        return removed

    monkeypatch.setattr(
        run_bundle_v3_module,
        "_remove_owned_replay_database",
        remove_then_inject,
    )
    with pytest.raises(RunBundleV3ReplayError, match="inventory"):
        replay_run_bundle_v3(bundle_directory, destination)

    assert injected is True
    assert (destination / "concurrent-foreign-file").read_text(encoding="utf-8") == "preserve"
    assert not (destination / "replay.sqlite3").exists()


def test_v3_replay_reports_hashes_from_verified_source(tmp_path: Path) -> None:
    spec = _spec("greedy_prior")
    bundle_directory = tmp_path / "bundle"
    verification = export_run_bundle_v3(bundle_directory, trace=_trace(spec))
    result = replay_run_bundle_v3(bundle_directory, tmp_path / "replay")

    assert (
        result.bundle_sha256
        == hashlib.sha256((bundle_directory / "run-bundle.json").read_bytes()).hexdigest()
    )
    assert result.steps_sha256 == verification.steps_sha256
    assert result.terminal_summary_sha256 == verification.terminal_summary_sha256
