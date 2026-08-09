from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from research_decision_engine.belief_models import (
    CALIBRATED_SIGMA_MODEL_ID,
    MatchedEffectObservation,
    belief_models,
    initial_model_lineage,
)
from research_decision_engine.benchmarks.robust_reporting import OUTPUT_FILENAMES
from research_decision_engine.benchmarks.worlds import (
    build_benchmark_world,
    paired_evaluation_worlds,
)
from research_decision_engine.calibration import build_calibration_prefix
from research_decision_engine.optimizer_effect import synchronize_optimizer_reasoning
from research_decision_engine.robust_storage import RobustBeliefStore
from research_decision_engine.storage import ExperimentStore
from research_decision_engine.types import ExperimentRecord


def test_robust_belief_persistence_and_cli_inspection_workflow(tmp_path: Path) -> None:
    db_path = tmp_path / "robust.sqlite"
    estimate_id = _populate_robust_database(db_path)

    calibration = _run_json_cli(db_path, "calibration-history")
    estimates = _run_json_cli(db_path, "sigma-estimates")
    lineages = _run_json_cli(db_path, "belief-lineages")
    explanation = _run_json_cli(db_path, "explain-sigma-estimate", estimate_id)
    adequacy = _run_json_cli(db_path, "model-adequacy")

    assert len(calibration["matched_effects"]) == 10
    assert calibration["cost_ledger"]["calibration_cost"] > 0.0
    assert calibration["cost_ledger"]["decision_cost"] > 0.0
    assert len(estimates) == 2
    assert len(lineages) == 2
    assert all(item["sequence"] == 1 for item in lineages)
    assert explanation["belief_model_id"] == CALIBRATED_SIGMA_MODEL_ID
    assert explanation["sample_count"] == 5
    assert len(explanation["sources"]) == 5
    assert explanation["raw_sample_standard_deviation"] is not None
    assert explanation["sigma_floor"] == 0.05
    assert explanation["estimated_sigma"] >= 0.05
    assert explanation["cutoff_sequence"] == 1
    assert explanation["diagnostic"]["adequacy_state"] in {
        "adequate",
        "uncertain",
        "appears_misspecified",
    }
    assert len(adequacy) == 2


def test_robust_belief_evaluation_cli_smoke(tmp_path: Path) -> None:
    output_directory = tmp_path / "robust-belief-evaluation-v1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_decision_engine.cli",
            "evaluate-beliefs",
            "--seeds",
            "0",
            "--bootstrap-resamples",
            "20",
            "--output-directory",
            str(output_directory),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    manifest = json.loads((output_directory / "run_manifest.json").read_text(encoding="utf-8"))
    gates = json.loads((output_directory / "ACCEPTANCE_GATES.json").read_text(encoding="utf-8"))
    assert "all hard audits passed: True" in result.stdout
    assert manifest["run_count"] == 64
    assert len(gates["performance_gates"]) == 5
    assert {item.name for item in output_directory.iterdir()} == set(OUTPUT_FILENAMES)


def _populate_robust_database(db_path: Path) -> str:
    config = paired_evaluation_worlds()[2]
    design, world = build_benchmark_world(config, seed=9)
    prefix = build_calibration_prefix(
        world_id=config.world_id,
        evaluation_seed=9,
        designs=design.evidence_eligibility().designs,
        candidates={item.candidate_id: item for item in design.candidates},
        cost=design.cost,
        observe_pair=world.observe_calibration_pair,
        created_at="t0",
    )
    calibrated_estimate_id = ""
    with ExperimentStore(db_path) as store:
        store.init_schema()
        robust = RobustBeliefStore(store)
        robust.add_calibration_prefix(prefix)
        records = []
        for candidate in design.candidates:
            if candidate.candidate_id not in {"pair-00-sgd", "pair-00-adam"}:
                continue
            records.append(
                store.add_record(
                    ExperimentRecord(
                        record_id=None,
                        candidate=candidate,
                        policy="test",
                        observed_value=world.observe(candidate),
                        true_value=world.observe(candidate),
                        cost=design.cost(candidate),
                        created_at=f"t-{candidate.candidate_id}",
                    )
                )
            )
        synchronize_optimizer_reasoning(store, eligibility=design.evidence_eligibility())
        evidence = store.list_evidence()[0]
        history = tuple(
            MatchedEffectObservation.from_calibration(item) for item in prefix.matched_effects
        )
        for model in belief_models():
            lineage = initial_model_lineage(model, lineage_key="cli", created_at="t0")
            robust.add_lineage(lineage)
            _, update, _ = model.update(
                lineage=lineage,
                evidence=evidence,
                effect_history=history,
                diagnostic_history=(),
            )
            robust.add_model_update(update, effect_history=history)
            if model.model_id == CALIBRATED_SIGMA_MODEL_ID:
                calibrated_estimate_id = update.sigma_estimate.estimate_id
        for record in records:
            robust.add_decision_cost(run_id="cli", record=record)
    return calibrated_estimate_id


def _run_json_cli(db_path: Path, *args: str) -> Any:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_decision_engine.cli",
            "--db",
            str(db_path),
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)
