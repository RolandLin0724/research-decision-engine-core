"""Run one v3 compression trace with a finite static replay policy."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from research_decision_engine.command_adapter import CommandAdapter, CommandInvocation
from research_decision_engine.information_gain_table import FiniteTableEvidenceModel
from research_decision_engine.policy_contracts import (
    GREEDY_PRIOR_POLICY_ID,
    INFORMATION_GAIN_TABLE_CLASSIFICATION,
    INFORMATION_GAIN_TABLE_POLICY_ID,
    PRIOR_GREEDY_CLASSIFICATION,
    RANDOM_POLICY_ID,
    REPLAY_CONTRACT_V3,
    RUN_BUNDLE_V3_SCHEMA,
    RUN_SPEC_V3_SCHEMA,
    RUNSPEC_CANDIDATE_ORDER,
    UtilityNumber,
)
from research_decision_engine.run_bundle_v3 import (
    export_run_bundle_v3,
    replay_run_bundle_v3,
    verify_run_bundle_v3,
)
from research_decision_engine.run_spec import CandidateSpec
from research_decision_engine.run_spec_v3 import RunSpecV3
from research_decision_engine.runner import (
    resume_workload_trace_v3,
    run_workload_experiment_v3,
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
    from examples.command_adapter_compression.run_v2_example import (
        PRIOR_UTILITY_FORMULA,
        build_prior_utility_map,
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
        from .run_v2_example import PRIOR_UTILITY_FORMULA, build_prior_utility_map
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
        from run_v2_example import PRIOR_UTILITY_FORMULA, build_prior_utility_map

type PolicyIdV3 = Literal["random", "greedy_prior", "information_gain_table"]

V3_RANDOM_POLICY_SEED = 20260804
INFORMATION_GAIN_HYPOTHESIS_IDS = (
    "gzip_dominant",
    "bz2_dominant",
    "lzma_dominant",
)
INFORMATION_GAIN_PRIOR_WEIGHTS = {
    "gzip_dominant": 1,
    "bz2_dominant": 1,
    "lzma_dominant": 1,
}
INFORMATION_GAIN_OBSERVATION_METRIC = "compression_ratio"
INFORMATION_GAIN_OUTCOME_IDS = ("low", "medium", "high")
INFORMATION_GAIN_OUTCOME_THRESHOLDS = (2.0, 3.0)
INFORMATION_GAIN_LIKELIHOOD_ROW_TOTAL = 20
MATCHING_LIKELIHOOD_WEIGHTS = {"low": 1, "medium": 5, "high": 14}
NONMATCHING_LIKELIHOOD_WEIGHTS = {"low": 10, "medium": 7, "high": 3}
HYPOTHESIS_CODEC = {
    "gzip_dominant": "gzip",
    "bz2_dominant": "bz2",
    "lzma_dominant": "lzma",
}


@dataclass(frozen=True, slots=True)
class CompressionExampleV3Result:
    output_directory: Path
    policy_id: PolicyIdV3
    run_spec_fingerprint: str
    evidence_model_fingerprint: str | None
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


def build_information_gain_evidence_model(
    candidates: Sequence[CandidateSpec] | None = None,
    *,
    observation_metric: str = INFORMATION_GAIN_OBSERVATION_METRIC,
) -> FiniteTableEvidenceModel:
    """Build the explicit 24 x 3 x 3 project-authored demonstration table."""

    candidate_sequence = build_candidates() if candidates is None else tuple(candidates)
    if len(candidate_sequence) != 24:
        raise ValueError("The compression evidence model requires exactly 24 candidates.")

    likelihood: dict[str, dict[str, dict[str, int]]] = {}
    for candidate in candidate_sequence:
        if type(candidate) is not CandidateSpec:
            raise TypeError("Every compression candidate must be an exact CandidateSpec.")
        parameters = dict(candidate.parameters)
        if set(parameters) != {"chunk_mode", "codec", "level"}:
            raise ValueError("Compression candidate fields differ from the frozen example.")
        codec = parameters["codec"]
        if type(codec) is not str or codec not in ("gzip", "bz2", "lzma"):
            raise ValueError("Compression candidate codec differs from the frozen example.")
        likelihood[candidate.candidate_id] = {
            hypothesis_id: dict(
                MATCHING_LIKELIHOOD_WEIGHTS
                if codec == HYPOTHESIS_CODEC[hypothesis_id]
                else NONMATCHING_LIKELIHOOD_WEIGHTS
            )
            for hypothesis_id in INFORMATION_GAIN_HYPOTHESIS_IDS
        }

    model = FiniteTableEvidenceModel(
        hypothesis_ids=INFORMATION_GAIN_HYPOTHESIS_IDS,
        prior_weight_by_hypothesis=INFORMATION_GAIN_PRIOR_WEIGHTS,
        observation_metric=observation_metric,
        outcome_ids=INFORMATION_GAIN_OUTCOME_IDS,
        outcome_thresholds=INFORMATION_GAIN_OUTCOME_THRESHOLDS,
        likelihood_row_total=INFORMATION_GAIN_LIKELIHOOD_ROW_TOTAL,
        likelihood_weight_by_candidate_id=likelihood,
    )
    model.validate_candidate_ids(tuple(candidate.candidate_id for candidate in candidate_sequence))
    return model


def build_run_spec_v3(
    policy_id: PolicyIdV3,
    *,
    objective_name: str = INFORMATION_GAIN_OBSERVATION_METRIC,
) -> RunSpecV3:
    """Build one exact v3 RunSpec without changing either earlier schema."""

    candidates = build_candidates()
    if policy_id == RANDOM_POLICY_ID:
        policy_config: Mapping[str, object] = {}
        policy_seed: int | None = V3_RANDOM_POLICY_SEED
    elif policy_id == GREEDY_PRIOR_POLICY_ID:
        policy_config = {
            "utility_by_candidate_id": build_prior_utility_map(candidates),
            "tie_break": RUNSPEC_CANDIDATE_ORDER,
        }
        policy_seed = None
    elif policy_id == INFORMATION_GAIN_TABLE_POLICY_ID:
        model = build_information_gain_evidence_model(
            candidates,
            observation_metric=objective_name,
        )
        policy_config = {
            "evidence_model": model.to_payload(),
            "tie_break": RUNSPEC_CANDIDATE_ORDER,
        }
        policy_seed = None
    else:
        raise ValueError("v3 compression policy identity is unsupported.")

    return RunSpecV3(
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


def run_v3_example(
    output_directory: Path,
    *,
    policy_id: PolicyIdV3,
    python_executable: str = sys.executable,
) -> CompressionExampleV3Result:
    """Execute four steps, reopen, finish, export, verify, and replay without work."""

    root = _prepare_output_directory(output_directory)
    database_path = root / "original.sqlite3"
    counter_file = root / "command-count.txt"
    bundle_directory = root / "run-bundle"
    replay_directory = root / "replay"
    run_spec = build_run_spec_v3(policy_id)
    evidence_model = run_spec.evidence_model
    evidence_model_fingerprint = (
        evidence_model.fingerprint() if evidence_model is not None else None
    )

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
            run_workload_experiment_v3(store, run_spec=run_spec, adapter=adapter)
        assert len(store.list_workload_experiments(fingerprint)) == INTERRUPTION_STEP

    resume_mismatch_rejected = False
    with ExperimentStore(database_path) as reopened:
        assert reopened.schema_version() == SCHEMA_VERSION
        count_before_mismatch = _read_counter(counter_file)
        mismatched_run_spec = build_run_spec_v3(
            policy_id,
            objective_name="different_compression_ratio",
        )
        assert mismatched_run_spec.fingerprint() != fingerprint
        try:
            resume_workload_trace_v3(
                reopened,
                run_spec=mismatched_run_spec,
                adapter=adapter,
                expected_run_spec_fingerprint=fingerprint,
                expected_evidence_model_fingerprint=evidence_model_fingerprint,
            )
        except ValueError:
            resume_mismatch_rejected = True
        else:
            raise AssertionError("Mismatched v3 resume identity did not fail closed.")
        assert _read_counter(counter_file) == count_before_mismatch
        trace = resume_workload_trace_v3(
            reopened,
            run_spec=run_spec,
            adapter=adapter,
            expected_run_spec_fingerprint=fingerprint,
            expected_evidence_model_fingerprint=evidence_model_fingerprint,
        )
        original_history = reopened.list_workload_experiments(fingerprint)

    assert len(trace.steps) == len(original_history) == EXPERIMENT_BUDGET
    assert trace.stop_reason == "experiment_budget_exhausted"
    original_command_count = _read_counter(counter_file)
    assert original_command_count == EXPERIMENT_BUDGET

    exported = export_run_bundle_v3(bundle_directory, trace=trace)
    verified = verify_run_bundle_v3(bundle_directory)
    assert exported == verified
    assert verified.valid is True
    assert verified.bundle.run_spec == run_spec
    assert verified.bundle.steps == trace.steps

    replay_count_before = _read_counter(counter_file)
    replay = replay_run_bundle_v3(bundle_directory, replay_directory)
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
    replay_command_count = _read_counter(counter_file) - replay_count_before
    assert replay_command_count == 0

    objective_values = tuple(record.observation.objective_value for record in original_history)
    result = CompressionExampleV3Result(
        output_directory=root,
        policy_id=policy_id,
        run_spec_fingerprint=fingerprint,
        evidence_model_fingerprint=evidence_model_fingerprint,
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
    model_payload = evidence_model.to_payload() if evidence_model is not None else None
    payload = {
        "adaptive_likelihood_updates_enabled": False,
        "best_observed_objective": result.best_observed_objective,
        "belief_lineage_equal": True,
        "budget": EXPERIMENT_BUDGET,
        "bundle_schema": RUN_BUNDLE_V3_SCHEMA,
        "bundle_sha256": result.bundle_sha256,
        "bundle_verified": result.bundle_verified,
        "candidate_count": len(run_spec.candidates),
        "corpus_bytes": CORPUS_BYTE_COUNT,
        "corpus_provenance": CORPUS_PROVENANCE,
        "corpus_sha256": CORPUS_SHA256,
        "dynamic_policy_loading_enabled": False,
        "evidence_model": model_payload,
        "evidence_model_fingerprint": result.evidence_model_fingerprint,
        "example_name": EXAMPLE_NAME,
        "hidden_truth_exposure_count": 0,
        "interruption_resume": True,
        "interruption_step": INTERRUPTION_STEP,
        "original_command_count": result.original_command_count,
        "policy_id": result.policy_id,
        "policy_seed": run_spec.policy_seed,
        "policy_semantic_classification": (
            INFORMATION_GAIN_TABLE_CLASSIFICATION
            if policy_id == INFORMATION_GAIN_TABLE_POLICY_ID
            else PRIOR_GREEDY_CLASSIFICATION
            if policy_id == GREEDY_PRIOR_POLICY_ID
            else "SEEDED_RANDOM_WITHOUT_REPLACEMENT"
        ),
        "prior_utility_by_candidate_id": prior_map,
        "prior_utility_formula": (
            PRIOR_UTILITY_FORMULA if policy_id == GREEDY_PRIOR_POLICY_ID else None
        ),
        "replay_adapter_execution_count": result.replay_adapter_execution_count,
        "replay_command_count": result.replay_command_count,
        "replay_contract": REPLAY_CONTRACT_V3,
        "replay_equivalent": result.replay_equivalent,
        "replay_reported_command_execution_count": result.replay_reported_command_execution_count,
        "resume_mismatch_rejected": result.resume_mismatch_rejected,
        "run_spec_fingerprint": result.run_spec_fingerprint,
        "run_spec_schema": RUN_SPEC_V3_SCHEMA,
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
        "--policy",
        choices=(RANDOM_POLICY_ID, GREEDY_PRIOR_POLICY_ID, INFORMATION_GAIN_TABLE_POLICY_ID),
        required=True,
    )
    args = parser.parse_args(argv)
    run_v3_example(args.output_dir, policy_id=cast(PolicyIdV3, args.policy))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
