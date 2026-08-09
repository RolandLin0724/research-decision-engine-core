"""Offline RunBundle export, verification, and empty-directory replay example."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from research_decision_engine import (
    CandidateSpec,
    NormalizedObservation,
    PythonFunctionAdapter,
    RunSpec,
    export_run_bundle,
    replay_run_bundle,
    run_workload_trace,
    verify_run_bundle,
)
from research_decision_engine.storage import ExperimentStore


def main() -> None:
    """Create one original run, export it, and replay it without its callable."""

    workload_calls = 0

    def score(candidate: CandidateSpec) -> NormalizedObservation:
        nonlocal workload_calls
        workload_calls += 1
        value = candidate.parameters["x"]
        if type(value) not in (int, float):
            raise TypeError("x must be numeric")
        numeric_value = cast(int | float, value)
        return NormalizedObservation(objective_value=float(numeric_value) ** 2, cost=0.25)

    run_spec = RunSpec(
        candidates=[
            CandidateSpec("small", {"x": 1.0}),
            CandidateSpec("medium", {"x": 2.0}),
            CandidateSpec("large", {"x": 3.0}),
        ],
        policy_id="random",
        policy_config={},
        policy_seed=17,
        experiment_count_budget=3,
        cost_budget=1.0,
        adapter_id="offline-square",
        adapter_version="1",
        objective_name="squared_value",
        objective_direction="maximize",
    )
    adapter = PythonFunctionAdapter(
        score,
        adapter_id=run_spec.adapter_id,
        adapter_version=run_spec.adapter_version,
    )

    with TemporaryDirectory(prefix="rde-run-bundle-example-") as temporary:
        root = Path(temporary)
        original_database = root / "original.sqlite3"
        bundle_directory = root / "run-bundle"
        replay_a_directory = root / "replay-a"
        replay_b_directory = root / "replay-b"

        with ExperimentStore(original_database) as store:
            store.init_schema()
            trace = run_workload_trace(store, run_spec=run_spec, adapter=adapter)

        exported = export_run_bundle(
            bundle_directory,
            trace=trace,
        )
        verified = verify_run_bundle(bundle_directory)
        assert exported.bundle_sha256 == verified.bundle_sha256
        assert verified.run_spec_sha256 == run_spec.fingerprint()
        assert verified.selected_candidate_ids == tuple(
            step.selected_candidate_id for step in trace.steps
        )
        assert workload_calls == run_spec.experiment_count_budget

        original_call_count = workload_calls
        del adapter, score
        original_database.unlink()
        replay_a_directory.mkdir()
        replay_b_directory.mkdir()

        replay_a = replay_run_bundle(bundle_directory, replay_a_directory)
        replay_b = replay_run_bundle(bundle_directory, replay_b_directory)

        assert workload_calls == original_call_count
        assert replay_a == replay_b
        assert replay_a.equivalent
        assert replay_a.bundle_sha256 == verified.bundle_sha256
        assert replay_a.selected_candidate_ids == verified.selected_candidate_ids
        assert (replay_a_directory / "replay.sqlite3").is_file()
        assert (replay_b_directory / "replay.sqlite3").is_file()

        print(f"RUN_BUNDLE_SHA256={verified.bundle_sha256}")
        print(f"RUN_SPEC_SHA256={verified.run_spec_sha256}")
        print(f"STEPS_SHA256={verified.steps_sha256}")
        print(f"TERMINAL_SUMMARY_SHA256={verified.terminal_summary_sha256}")
        print(f"SELECTED_CANDIDATES={','.join(verified.selected_candidate_ids)}")
        print(f"REPLAY_EQUIVALENT={replay_a.equivalent}")
        print(f"REPLAY_WORKLOAD_CALLS={workload_calls - original_call_count}")


if __name__ == "__main__":
    main()
