"""Run the random-policy CommandAdapter compression vertical slice."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from research_decision_engine import (
    CandidateSpec,
    CommandAdapter,
    CommandInvocation,
    CompletedWorkloadExperiment,
    RunSpec,
    export_run_bundle,
    replay_run_bundle,
    resume_workload_trace,
    run_workload_experiment,
    verify_run_bundle,
)
from research_decision_engine.storage import SCHEMA_VERSION, ExperimentStore

if TYPE_CHECKING:
    from examples.command_adapter_compression.corpus_data import (
        CORPUS_BYTE_COUNT,
        CORPUS_PROVENANCE,
        CORPUS_SHA256,
    )
    from examples.command_adapter_compression.workload import CHUNK_MODES, CODECS, LEVELS
else:
    if __package__:
        from .corpus_data import CORPUS_BYTE_COUNT, CORPUS_PROVENANCE, CORPUS_SHA256
        from .workload import CHUNK_MODES, CODECS, LEVELS
    else:
        from corpus_data import CORPUS_BYTE_COUNT, CORPUS_PROVENANCE, CORPUS_SHA256
        from workload import CHUNK_MODES, CODECS, LEVELS

EXAMPLE_NAME = "Command Adapter Compression Tuning"
RANDOM_POLICY_ID = "random"
RANDOM_POLICY_SEED = 1729
EXPERIMENT_BUDGET = 8
INTERRUPTION_STEP = 4
ADAPTER_ID = "command-adapter-compression"
ADAPTER_VERSION = "1"
EXAMPLE_ROOT = Path(__file__).resolve().parent
WORKLOAD_PATH = EXAMPLE_ROOT / "workload.py"


@dataclass(frozen=True, slots=True)
class CompressionExampleResult:
    output_directory: Path
    run_spec_fingerprint: str
    selected_candidate_ids: tuple[str, ...]
    bundle_sha256: str
    steps_sha256: str
    terminal_summary_sha256: str
    original_command_count: int
    replay_command_count: int
    resume_mismatch_rejected: bool
    replay_equivalent: bool


def build_candidates() -> tuple[CandidateSpec, ...]:
    """Return the exact ordered 3 x 4 x 2 truth-free candidate space."""

    return tuple(
        CandidateSpec(
            f"{codec}-level-{level}-{chunk_mode.replace('_', '-')}",
            {"chunk_mode": chunk_mode, "codec": codec, "level": level},
        )
        for codec in CODECS
        for level in LEVELS
        for chunk_mode in CHUNK_MODES
    )


def build_run_spec(*, objective_name: str = "compression_ratio") -> RunSpec:
    return RunSpec(
        candidates=build_candidates(),
        policy_id=RANDOM_POLICY_ID,
        policy_config={},
        policy_seed=RANDOM_POLICY_SEED,
        experiment_count_budget=EXPERIMENT_BUDGET,
        adapter_id=ADAPTER_ID,
        adapter_version=ADAPTER_VERSION,
        objective_name=objective_name,
        objective_direction="maximize",
    )


def build_command_invocation(
    candidate: CandidateSpec,
    *,
    counter_file: Path,
    python_executable: str = sys.executable,
) -> CommandInvocation:
    """Map only the public truth-free candidate to one direct-child invocation."""

    if type(candidate) is not CandidateSpec:
        raise TypeError("candidate must be an exact CandidateSpec")
    parameters = dict(candidate.parameters)
    if set(parameters) != {"chunk_mode", "codec", "level"}:
        raise ValueError("compression candidate fields differ")
    codec = parameters["codec"]
    level = parameters["level"]
    chunk_mode = parameters["chunk_mode"]
    if type(codec) is not str or codec not in CODECS:
        raise ValueError("unsupported codec")
    if type(level) is not int or level not in LEVELS:
        raise ValueError("unsupported compression level")
    if type(chunk_mode) is not str or chunk_mode not in CHUNK_MODES:
        raise ValueError("unsupported chunk mode")
    return CommandInvocation(
        argv=(
            python_executable,
            str(WORKLOAD_PATH),
            "--codec",
            codec,
            "--level",
            str(level),
            "--chunk-mode",
            chunk_mode,
            "--counter-file",
            str(counter_file),
        ),
        cwd=EXAMPLE_ROOT,
        environment_overrides={"PYTHONHASHSEED": "0"},
        inherit_environment=True,
        timeout_seconds=30.0,
        max_stdout_bytes=4096,
        max_stderr_bytes=8192,
    )


def _read_counter(path: Path) -> int:
    text = path.read_text(encoding="ascii")
    if not text.endswith("\n") or not text[:-1].isdigit():
        raise RuntimeError("Command counter is malformed.")
    return int(text[:-1])


def _prepare_output_directory(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.exists():
        if not resolved.is_dir() or any(resolved.iterdir()):
            raise ValueError("output directory must be absent or an empty directory")
    else:
        resolved.mkdir(parents=True)
    return resolved


def _history_semantics(
    history: Sequence[CompletedWorkloadExperiment],
) -> list[tuple[object, object, object]]:
    return [(record.candidate, record.policy_id, record.observation) for record in history]


def run_example(
    output_directory: Path,
    *,
    python_executable: str = sys.executable,
) -> CompressionExampleResult:
    root = _prepare_output_directory(output_directory)
    database_path = root / "original.sqlite3"
    counter_file = root / "command-count.txt"
    bundle_directory = root / "run-bundle"
    replay_directory = root / "replay"
    run_spec = build_run_spec()

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
            run_workload_experiment(store, run_spec=run_spec, adapter=adapter)
        assert len(store.list_workload_experiments(fingerprint)) == INTERRUPTION_STEP

    resume_mismatch_rejected = False
    with ExperimentStore(database_path) as reopened:
        assert reopened.schema_version() == SCHEMA_VERSION
        count_before_mismatch = _read_counter(counter_file)
        mismatched_run_spec = build_run_spec(objective_name="different_compression_ratio")
        assert mismatched_run_spec.fingerprint() != fingerprint
        try:
            resume_workload_trace(
                reopened,
                run_spec=mismatched_run_spec,
                adapter=adapter,
                expected_run_spec_fingerprint=fingerprint,
            )
        except ValueError:
            resume_mismatch_rejected = True
        else:
            raise AssertionError("mismatched resume fingerprint did not fail closed")
        assert _read_counter(counter_file) == count_before_mismatch
        trace = resume_workload_trace(
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
    exported = export_run_bundle(bundle_directory, trace=trace)
    verified = verify_run_bundle(bundle_directory)
    assert exported == verified
    assert verified.bundle.run_spec == run_spec
    assert verified.bundle.steps == trace.steps

    replay_count_before = _read_counter(counter_file)
    replay = replay_run_bundle(bundle_directory, replay_directory)
    assert replay.equivalent is True
    assert replay.bundle_sha256 == verified.bundle_sha256
    assert replay.run_spec_sha256 == fingerprint
    assert replay.steps_sha256 == verified.steps_sha256
    assert replay.terminal_summary_sha256 == verified.terminal_summary_sha256

    with ExperimentStore(replay_directory / "replay.sqlite3") as replay_store:
        assert replay_store.schema_version() == SCHEMA_VERSION
        replay_history = replay_store.list_workload_experiments(fingerprint)
        replay_trace = resume_workload_trace(
            replay_store,
            run_spec=run_spec,
            adapter=adapter,
            expected_run_spec_fingerprint=fingerprint,
        )
    assert _history_semantics(replay_history) == _history_semantics(original_history)
    assert replay_trace == trace
    replay_count_after = _read_counter(counter_file)
    replay_command_count = replay_count_after - replay_count_before
    assert replay_command_count == 0

    result = CompressionExampleResult(
        output_directory=root,
        run_spec_fingerprint=fingerprint,
        selected_candidate_ids=tuple(step.selected_candidate_id for step in trace.steps),
        bundle_sha256=verified.bundle_sha256,
        steps_sha256=verified.steps_sha256,
        terminal_summary_sha256=verified.terminal_summary_sha256,
        original_command_count=original_command_count,
        replay_command_count=replay_command_count,
        resume_mismatch_rejected=resume_mismatch_rejected,
        replay_equivalent=replay.equivalent,
    )
    payload = {
        "budget": EXPERIMENT_BUDGET,
        "bundle_sha256": result.bundle_sha256,
        "candidate_count": len(run_spec.candidates),
        "corpus_bytes": CORPUS_BYTE_COUNT,
        "corpus_provenance": CORPUS_PROVENANCE,
        "corpus_sha256": CORPUS_SHA256,
        "example_name": EXAMPLE_NAME,
        "interruption_step": INTERRUPTION_STEP,
        "original_command_count": result.original_command_count,
        "policy_id": run_spec.policy_id,
        "policy_seed": run_spec.policy_seed,
        "replay_command_count": result.replay_command_count,
        "replay_equivalent": result.replay_equivalent,
        "resume_mismatch_rejected": result.resume_mismatch_rejected,
        "run_spec_fingerprint": result.run_spec_fingerprint,
        "selected_candidate_ids": list(result.selected_candidate_ids),
        "sqlite_schema_version": SCHEMA_VERSION,
        "steps_sha256": result.steps_sha256,
        "terminal_summary_sha256": result.terminal_summary_sha256,
    }
    encoded = (
        json.dumps(
            payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
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
    args = parser.parse_args(argv)
    run_example(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
