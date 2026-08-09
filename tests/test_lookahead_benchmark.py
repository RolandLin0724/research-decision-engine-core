from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from research_decision_engine.benchmarks.evaluation import (
    ALL_BENCHMARK_POLICIES,
    run_benchmark_condition,
    run_benchmark_suite,
)
from research_decision_engine.benchmarks.worlds import (
    benchmark_worlds,
    build_benchmark_world,
    lookahead_benchmark_world_ids,
)

GENERATED_AT = "2026-01-01T00:00:00+00:00"


def test_lookahead_stress_worlds_cover_required_conditions() -> None:
    assert set(lookahead_benchmark_world_ids()) == {
        "delayed_information",
        "no_optimizer_advantage",
        "adverse_noisy_observations",
        "asymmetric_experiment_costs",
    }
    configs = benchmark_worlds(lookahead_benchmark_world_ids())

    assert {item.true_optimizer_effect for item in configs} >= {-0.12, 0.0, 0.12}
    assert {item.noise_level for item in configs} == {"low", "medium", "high"}
    assert {item.cost_mode for item in configs} == {"symmetric", "asymmetric"}

    delayed = next(item for item in configs if item.world_id == "delayed_information")
    design, _ = build_benchmark_world(delayed, seed=0)
    contract = design.evidence_eligibility()
    decoy = next(item for item in design.candidates if item.candidate_id == "decoy-objective")
    assert contract.assess_candidate(decoy, []).effect == "ineligible"
    assert {item.candidate_id for item in design.candidates} == {
        "decoy-objective",
        "useful-sgd",
        "useful-adam",
    }


def test_delayed_world_exposes_one_step_failure_and_lookahead_value() -> None:
    config = benchmark_worlds(("delayed_information",))[0]

    one_step = run_benchmark_condition(
        world_config=config,
        policy="information_gain",
        seed=0,
        budget=2.25,
        generated_at=GENERATED_AT,
    )
    lookahead = run_benchmark_condition(
        world_config=config,
        policy="lookahead_information_gain",
        seed=0,
        budget=2.25,
        generated_at=GENERATED_AT,
    )

    assert one_step.scientific_metrics.matched_evidence_pairs_completed == 0
    assert lookahead.scientific_metrics.matched_evidence_pairs_completed == 1
    assert lookahead.scientific_metrics.final_posterior_entropy < (
        one_step.scientific_metrics.final_posterior_entropy
    )
    assert one_step.trace[0].candidate_id == "decoy-objective"
    assert lookahead.trace[0].candidate_id in {"useful-adam", "useful-sgd"}


def test_all_four_policies_share_initial_conditions() -> None:
    report = run_benchmark_suite(
        world_ids=("delayed_information",),
        policies=ALL_BENCHMARK_POLICIES,
        seeds=(4,),
        budget=2.25,
        generated_at=GENERATED_AT,
    )

    assert len(report.runs) == 4
    assert len({item.initial_condition_fingerprint for item in report.runs}) == 1
    assert len({item.initial_belief_probabilities for item in report.runs}) == 1


def test_four_policy_benchmark_cli_smoke(tmp_path: Path) -> None:
    output_directory = tmp_path / "lookahead-benchmark"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_decision_engine.cli",
            "benchmark",
            "--world",
            "delayed_information",
            "--seeds",
            "0",
            "--budget",
            "2.25",
            "--policy",
            *ALL_BENCHMARK_POLICIES,
            "--output-directory",
            str(output_directory),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    parsed = json.loads((output_directory / "benchmark_results.json").read_text(encoding="utf-8"))

    assert "lookahead_information_gain" in result.stdout
    assert tuple(parsed["policies"]) == ALL_BENCHMARK_POLICIES
    assert len(parsed["runs"]) == 4
    assert (output_directory / "benchmark_traces.csv").is_file()
