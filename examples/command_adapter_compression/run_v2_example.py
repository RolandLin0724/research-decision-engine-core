"""Run one v2 random or prior-greedy CommandAdapter compression trace."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from research_decision_engine.command_adapter import CommandAdapter, CommandInvocation
from research_decision_engine.policy_contracts import (
    GREEDY_PRIOR_POLICY_ID,
    PRIOR_GREEDY_CLASSIFICATION,
    RANDOM_POLICY_ID,
    REPLAY_CONTRACT_V2,
    RUN_BUNDLE_V2_SCHEMA,
    RUN_SPEC_V2_SCHEMA,
    RUNSPEC_CANDIDATE_ORDER,
    UtilityNumber,
)
from research_decision_engine.run_bundle_v2 import (
    export_run_bundle_v2,
    replay_run_bundle_v2,
    verify_run_bundle_v2,
)
from research_decision_engine.run_spec import CandidateSpec
from research_decision_engine.run_spec_v2 import RunSpecV2
from research_decision_engine.runner import (
    resume_workload_trace_v2,
    run_workload_experiment_v2,
)
from research_decision_engine.storage import SCHEMA_VERSION, ExperimentStore

if TYPE_CHECKING:
    from examples.command_adapter_compression.corpus_data import (
        CORPUS_BYTE_COUNT,
        CORPUS_PROVENANCE,
        CORPUS_SHA256,
    )
    from examples.command_adapter_compression.run_example import (
        ADAPTER_ID,
        ADAPTER_VERSION,
        EXAMPLE_NAME,
        EXPERIMENT_BUDGET,
        INTERRUPTION_STEP,
        _history_semantics,
        _prepare_output_directory,
        _read_counter,
        build_candidates,
        build_command_invocation,
    )
else:
    if __package__:
        from .corpus_data import CORPUS_BYTE_COUNT, CORPUS_PROVENANCE, CORPUS_SHA256
        from .run_example import (
            ADAPTER_ID,
            ADAPTER_VERSION,
            EXAMPLE_NAME,
            EXPERIMENT_BUDGET,
            INTERRUPTION_STEP,
            _history_semantics,
            _prepare_output_directory,
            _read_counter,
            build_candidates,
            build_command_invocation,
        )
    else:
        from corpus_data import CORPUS_BYTE_COUNT, CORPUS_PROVENANCE, CORPUS_SHA256
        from run_example import (
            ADAPTER_ID,
            ADAPTER_VERSION,
            EXAMPLE_NAME,
            EXPERIMENT_BUDGET,
            INTERRUPTION_STEP,
            _history_semantics,
            _prepare_output_directory,
            _read_counter,
            build_candidates,
            build_command_invocation,
        )

type PolicyIdV2 = Literal["random", "greedy_prior"]

V2_RANDOM_POLICY_SEED = 20260804
CODEC_BASE_BY_ID = {"gzip": 1000, "bz2": 2000, "lzma": 3000}
PRIOR_UTILITY_FORMULA = "codec_base + level * 10 + single_stream_component"


@dataclass(frozen=True, slots=True)
class CompressionExampleV2Result:
    output_directory: Path
    policy_id: PolicyIdV2
    run_spec_fingerprint: str
    selected_candidate_ids: tuple[str, ...]
    best_observed_objective: float
    total_cost: float
    bundle_sha256: str
    steps_sha256: str
    terminal_summary_sha256: str
    bundle_verified: bool
    original_command_count: int
    replay_command_count: int
    replay_adapter_execution_count: int
    replay_reported_command_execution_count: int
    resume_mismatch_rejected: bool
    replay_equivalent: bool


def build_prior_utility_map(
    candidates: Sequence[CandidateSpec] | None = None,
) -> dict[str, int]:
    """Build the exact project-authored parameter-only prior for all 24 candidates."""

    candidate_sequence = build_candidates() if candidates is None else tuple(candidates)
    if len(candidate_sequence) != 24:
        raise ValueError("The compression v2 prior requires the exact 24-candidate space.")

    utilities: dict[str, int] = {}
    for candidate in candidate_sequence:
        if type(candidate) is not CandidateSpec:
            raise TypeError("Every compression candidate must be an exact CandidateSpec.")
        parameters = dict(candidate.parameters)
        if set(parameters) != {"chunk_mode", "codec", "level"}:
            raise ValueError("Compression candidate fields differ from the frozen example.")
        codec = parameters["codec"]
        level = parameters["level"]
        chunk_mode = parameters["chunk_mode"]
        if type(codec) is not str or codec not in CODEC_BASE_BY_ID:
            raise ValueError("Compression candidate codec differs from the frozen example.")
        if type(level) is not int or level not in (1, 3, 6, 9):
            raise ValueError("Compression candidate level differs from the frozen example.")
        if type(chunk_mode) is not str or chunk_mode not in (
            "single_stream",
            "fixed_64_kib_members",
        ):
            raise ValueError("Compression candidate chunk mode differs from the frozen example.")
        chunk_component = 1 if chunk_mode == "single_stream" else 0
        utilities[candidate.candidate_id] = CODEC_BASE_BY_ID[codec] + level * 10 + chunk_component

    if len(utilities) != 24:
        raise ValueError("Compression candidate IDs must be unique.")
    if len(set(utilities.values())) != 24:
        raise AssertionError("The frozen compression prior must contain 24 unique utilities.")
    return utilities


def build_run_spec_v2(
    policy_id: PolicyIdV2,
    *,
    objective_name: str = "compression_ratio",
) -> RunSpecV2:
    """Build one exact v2 RunSpec without changing the original v1 fixture."""

    candidates = build_candidates()
    if policy_id == RANDOM_POLICY_ID:
        policy_config: Mapping[str, object] = {}
        policy_seed: int | None = V2_RANDOM_POLICY_SEED
    elif policy_id == GREEDY_PRIOR_POLICY_ID:
        policy_config = {
            "utility_by_candidate_id": build_prior_utility_map(candidates),
            "tie_break": RUNSPEC_CANDIDATE_ORDER,
        }
        policy_seed = None
    else:
        raise ValueError("v2 compression policy must be 'random' or 'greedy_prior'.")

    return RunSpecV2(
        candidates=candidates,
        policy_id=policy_id,
        policy_config=policy_config,
        policy_seed=policy_seed,
        experiment_count_budget=EXPERIMENT_BUDGET,
        adapter_id=ADAPTER_ID,
        adapter_version=ADAPTER_VERSION,
        objective_name=objective_name,
        objective_direction="maximize",
    )


def run_v2_example(
    output_directory: Path,
    *,
    policy_id: PolicyIdV2,
    python_executable: str = sys.executable,
) -> CompressionExampleV2Result:
    """Execute four steps, reopen and finish, then verify and replay without an adapter."""

    root = _prepare_output_directory(output_directory)
    database_path = root / "original.sqlite3"
    counter_file = root / "command-count.txt"
    bundle_directory = root / "run-bundle"
    replay_directory = root / "replay"
    run_spec = build_run_spec_v2(policy_id)

    def builder(candidate: CandidateSpec) -> CommandInvocation:
        return build_command_invocation(
            candidate,
            counter_file=counter_file,
            python_executable=python_executable,
        )

    adapter = CommandAdapter(
        builder,
        adapter_id=run_spec.adapter_id,
        adapter_version=run_spec.adapter_version,
    )
    fingerprint = run_spec.fingerprint()

    with ExperimentStore(database_path) as store:
        store.init_schema()
        for _ in range(INTERRUPTION_STEP):
            run_workload_experiment_v2(store, run_spec=run_spec, adapter=adapter)
        assert len(store.list_workload_experiments(fingerprint)) == INTERRUPTION_STEP

    resume_mismatch_rejected = False
    with ExperimentStore(database_path) as reopened:
        assert reopened.schema_version() == SCHEMA_VERSION
        count_before_mismatch = _read_counter(counter_file)
        mismatched_run_spec = build_run_spec_v2(
            policy_id, objective_name="different_compression_ratio"
        )
        assert mismatched_run_spec.fingerprint() != fingerprint
        try:
            resume_workload_trace_v2(
                reopened,
                run_spec=mismatched_run_spec,
                adapter=adapter,
                expected_run_spec_fingerprint=fingerprint,
            )
        except ValueError:
            resume_mismatch_rejected = True
        else:
            raise AssertionError("Mismatched v2 resume identity did not fail closed.")
        assert _read_counter(counter_file) == count_before_mismatch
        trace = resume_workload_trace_v2(
            reopened,
            run_spec=run_spec,
            adapter=adapter,
            expected_run_spec_fingerprint=fingerprint,
        )
        original_history = reopened.list_workload_experiments(fingerprint)

    assert len(trace.steps) == len(original_history) == EXPERIMENT_BUDGET
    assert trace.stop_reason == "experiment_budget_exhausted"
    original_command_count = _read_counter(counter_file)
    assert original_command_count == EXPERIMENT_BUDGET

    exported = export_run_bundle_v2(bundle_directory, trace=trace)
    verified = verify_run_bundle_v2(bundle_directory)
    assert exported == verified
    assert verified.valid is True
    assert verified.bundle.run_spec == run_spec
    assert verified.bundle.steps == trace.steps

    replay_count_before = _read_counter(counter_file)
    replay = replay_run_bundle_v2(bundle_directory, replay_directory)
    assert replay.equivalent is True
    assert replay.bundle_sha256 == verified.bundle_sha256
    assert replay.run_spec_sha256 == fingerprint
    assert replay.steps_sha256 == verified.steps_sha256
    assert replay.terminal_summary_sha256 == verified.terminal_summary_sha256
    assert replay.adapter_execution_count == 0
    assert replay.command_execution_count == 0

    with ExperimentStore(replay_directory / "replay.sqlite3") as replay_store:
        assert replay_store.schema_version() == SCHEMA_VERSION
        replay_history = replay_store.list_workload_experiments(fingerprint)
    assert _history_semantics(replay_history) == _history_semantics(original_history)
    replay_count_after = _read_counter(counter_file)
    replay_command_count = replay_count_after - replay_count_before
    assert replay_command_count == 0

    objective_values = tuple(record.observation.objective_value for record in original_history)
    result = CompressionExampleV2Result(
        output_directory=root,
        policy_id=policy_id,
        run_spec_fingerprint=fingerprint,
        selected_candidate_ids=tuple(step.selected_candidate_id for step in trace.steps),
        best_observed_objective=max(objective_values),
        total_cost=trace.steps[-1].cumulative_cost,
        bundle_sha256=verified.bundle_sha256,
        steps_sha256=verified.steps_sha256,
        terminal_summary_sha256=verified.terminal_summary_sha256,
        bundle_verified=verified.valid,
        original_command_count=original_command_count,
        replay_command_count=replay_command_count,
        replay_adapter_execution_count=replay.adapter_execution_count,
        replay_reported_command_execution_count=replay.command_execution_count,
        resume_mismatch_rejected=resume_mismatch_rejected,
        replay_equivalent=replay.equivalent,
    )
    prior_map: Mapping[str, UtilityNumber] | None = (
        cast(Mapping[str, UtilityNumber], run_spec.policy_config["utility_by_candidate_id"])
        if policy_id == GREEDY_PRIOR_POLICY_ID
        else None
    )
    payload = {
        "adaptive_score_updates_enabled": False,
        "best_observed_objective": result.best_observed_objective,
        "budget": EXPERIMENT_BUDGET,
        "bundle_schema": RUN_BUNDLE_V2_SCHEMA,
        "bundle_sha256": result.bundle_sha256,
        "bundle_verified": result.bundle_verified,
        "candidate_count": len(run_spec.candidates),
        "corpus_bytes": CORPUS_BYTE_COUNT,
        "corpus_provenance": CORPUS_PROVENANCE,
        "corpus_sha256": CORPUS_SHA256,
        "example_name": EXAMPLE_NAME,
        "interruption_step": INTERRUPTION_STEP,
        "interruption_resume": True,
        "original_command_count": result.original_command_count,
        "policy_id": result.policy_id,
        "policy_seed": run_spec.policy_seed,
        "policy_semantic_classification": (
            PRIOR_GREEDY_CLASSIFICATION
            if policy_id == GREEDY_PRIOR_POLICY_ID
            else "SEEDED_RANDOM_WITHOUT_REPLACEMENT"
        ),
        "prior_utility_by_candidate_id": prior_map,
        "prior_utility_formula": (
            PRIOR_UTILITY_FORMULA if policy_id == GREEDY_PRIOR_POLICY_ID else None
        ),
        "replay_adapter_execution_count": result.replay_adapter_execution_count,
        "replay_command_count": result.replay_command_count,
        "replay_contract": REPLAY_CONTRACT_V2,
        "replay_equivalent": result.replay_equivalent,
        "replay_reported_command_execution_count": (result.replay_reported_command_execution_count),
        "resume_mismatch_rejected": result.resume_mismatch_rejected,
        "run_spec_fingerprint": result.run_spec_fingerprint,
        "run_spec_schema": RUN_SPEC_V2_SCHEMA,
        "selected_candidate_ids": list(result.selected_candidate_ids),
        "sqlite_schema_version": SCHEMA_VERSION,
        "steps_sha256": result.steps_sha256,
        "terminal_summary_sha256": result.terminal_summary_sha256,
        "total_cost": result.total_cost,
    }
    encoded = (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    (root / "example-results.json").write_text(encoded, encoding="utf-8", newline="\n")
    sys.stdout.buffer.write(encoded.encode("utf-8"))
    sys.stdout.buffer.flush()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--policy", choices=(RANDOM_POLICY_ID, GREEDY_PRIOR_POLICY_ID), required=True
    )
    args = parser.parse_args(argv)
    run_v2_example(args.output_dir, policy_id=cast(PolicyIdV2, args.policy))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
