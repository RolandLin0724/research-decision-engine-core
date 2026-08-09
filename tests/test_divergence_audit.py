from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

import pytest

from research_decision_engine.belief_models import (
    CALIBRATED_SIGMA_MODEL_ID,
    FIXED_SIGMA_MODEL_ID,
)
from research_decision_engine.benchmarks.divergence_audit import (
    AUDIT_SCHEMA_VERSION,
    FROZEN_OUTPUT_FILENAMES,
    AccessLedger,
    AuditedDivergenceCase,
    CandidateRecord,
    CompatibilityAccumulator,
    ContextReplay,
    DivergenceAuditError,
    DivergenceAuditResult,
    DivergencePair,
    EvaluatorOutcome,
    ReadOnlyScoringAdapter,
    RecordedPredictionSnapshot,
    SequenceSummary,
    TruthFreeDivergenceCase,
    _classify_mechanisms,
    _edit_distance,
    _harm_bootstrap_intervals,
    _harm_concentration_rows,
    _mechanism_condition_rows,
    _mechanism_summary_rows,
    _score_decomposition_rows,
    _sequence_rows,
    _stable_hash,
    discover_divergence_pairs_from_rows,
    shapley_score_decomposition,
)
from research_decision_engine.benchmarks.divergence_reporting import (
    write_divergence_outputs,
)
from research_decision_engine.evidence_eligibility import (
    PublicExperimentDesign,
    default_public_design,
)
from research_decision_engine.optimizer_effect import optimizer_effect_hypotheses
from research_decision_engine.types import Candidate


def _candidate(candidate_id: str, learning_rate: float, optimizer: str) -> Candidate:
    return Candidate(
        candidate_id=candidate_id,
        learning_rate=learning_rate,
        regularization=0.001,
        model_width=32,
        optimizer=optimizer,
    )


def _fixture_candidates() -> tuple[CandidateRecord, ...]:
    first_adam = _candidate("pair-a-adam", 0.01, "adam")
    first_sgd = _candidate("pair-a-sgd", 0.01, "sgd")
    second_adam = _candidate("pair-b-adam", 0.02, "adam")
    second_sgd = _candidate("pair-b-sgd", 0.02, "sgd")
    decoy = _candidate("decoy", 0.1, "sgd")
    decoy_default = default_public_design(decoy)
    decoy_design = PublicExperimentDesign(
        candidate_id=decoy.candidate_id,
        experiment_family="objective-only",
        comparison_group_id=decoy_default.comparison_group_id,
        controlled_variables=decoy_default.controlled_variables,
        intervention_variable="optimizer",
        intervention_arm="sgd",
    )
    return (
        CandidateRecord(first_adam, 1.0, default_public_design(first_adam)),
        CandidateRecord(first_sgd, 1.0, default_public_design(first_sgd)),
        CandidateRecord(second_adam, 1.0, default_public_design(second_adam)),
        CandidateRecord(second_sgd, 1.0, default_public_design(second_sgd)),
        CandidateRecord(decoy, 0.5, decoy_design),
    )


def _snapshots(
    candidates: tuple[CandidateRecord, ...], *, model_id: str, sigmas: tuple[float, ...]
) -> tuple[RecordedPredictionSnapshot, ...]:
    groups = sorted(
        {
            item.public_design.comparison_group_id
            for item in candidates
            if item.public_design.experiment_family == "optimizer-effect"
        }
    )
    hypotheses = sorted(optimizer_effect_hypotheses(), key=lambda item: item.hypothesis_id)
    means = tuple(
        (item.hypothesis_id, float(item.prediction_model.parameters()["mean"]))
        for item in hypotheses
    )
    return tuple(
        RecordedPredictionSnapshot(
            snapshot_id=f"snapshot-{model_id}-{index}",
            belief_model_id=model_id,
            belief_model_version=f"{model_id}/v1",
            lineage_id=f"lineage-{model_id}",
            belief_state_id=f"belief-{model_id}",
            comparison_group_id=group,
            estimated_sigma=sigmas[index],
            sigma_status="fixed" if model_id == FIXED_SIGMA_MODEL_ID else "calibrated",
            source_effect_ids=() if model_id == FIXED_SIGMA_MODEL_ID else (f"effect-{index}",),
            means=means,
            standard_deviations=tuple((item.hypothesis_id, sigmas[index]) for item in hypotheses),
        )
        for index, group in enumerate(groups)
    )


def _fixture_case() -> AuditedDivergenceCase:
    candidates = _fixture_candidates()
    hypothesis_ids = tuple(
        item.hypothesis_id
        for item in sorted(optimizer_effect_hypotheses(), key=lambda item: item.hypothesis_id)
    )
    posterior = (1.0 / 3.0,) * 3
    fixed_snapshots = _snapshots(candidates, model_id=FIXED_SIGMA_MODEL_ID, sigmas=(0.05, 0.05))
    adapter = ReadOnlyScoringAdapter(candidates=candidates, completed_experiments=(), max_cost=2.0)
    fixed_replay = adapter.replay(
        context="FF",
        hypothesis_ids=hypothesis_ids,
        posterior_probabilities=posterior,
        snapshots=fixed_snapshots,
    )
    fixed_group = fixed_replay.winner.comparison_group_id
    calibrated_sigmas = tuple(
        0.20 if item.comparison_group_id == fixed_group else 0.10 for item in fixed_snapshots
    )
    calibrated_snapshots = _snapshots(
        candidates,
        model_id=CALIBRATED_SIGMA_MODEL_ID,
        sigmas=calibrated_sigmas,
    )
    replays: dict[str, ContextReplay] = {
        "FF": fixed_replay,
        "CF": adapter.replay(
            context="CF",
            hypothesis_ids=hypothesis_ids,
            posterior_probabilities=posterior,
            snapshots=fixed_snapshots,
        ),
        "FC": adapter.replay(
            context="FC",
            hypothesis_ids=hypothesis_ids,
            posterior_probabilities=posterior,
            snapshots=calibrated_snapshots,
        ),
        "CC": adapter.replay(
            context="CC",
            hypothesis_ids=hypothesis_ids,
            posterior_probabilities=posterior,
            snapshots=calibrated_snapshots,
        ),
    }
    fixed_selected = replays["FF"].winner.candidate_id
    calibrated_selected = replays["CC"].winner.candidate_id
    assert fixed_selected != calibrated_selected
    fixed_complement = fixed_selected.replace("adam", "sgd")
    calibrated_complement = calibrated_selected.replace("adam", "sgd")
    decomposition = shapley_score_decomposition(
        replays=replays,
        fixed_candidate_id=fixed_selected,
        calibrated_candidate_id=calibrated_selected,
    )
    sequence = SequenceSummary(
        fixed_sequence=(fixed_selected, fixed_complement),
        calibrated_sequence=(calibrated_selected, calibrated_complement),
        fixed_action_effects=("opens_pair", "completes_pair"),
        calibrated_action_effects=("opens_pair", "completes_pair"),
        fixed_pair_events=(),
        calibrated_pair_events=(),
        fixed_first_evidence_step=2,
        calibrated_first_evidence_step=2,
        fixed_first_evidence_cost=2.0,
        calibrated_first_evidence_cost=2.0,
        fixed_cost_before_first_evidence=1.0,
        calibrated_cost_before_first_evidence=1.0,
        fixed_remaining_budget_after_first_evidence=0.0,
        calibrated_remaining_budget_after_first_evidence=0.0,
        fixed_evidence_count=1,
        calibrated_evidence_count=1,
        fixed_evidence_order=("fixed-evidence",),
        calibrated_evidence_order=("calibrated-evidence",),
        fixed_sigma_source_order=((),),
        calibrated_sigma_source_order=(("calibration-effect",),),
        fixed_final_set=tuple(sorted((fixed_selected, fixed_complement))),
        calibrated_final_set=tuple(sorted((calibrated_selected, calibrated_complement))),
        intersection=(),
        union=tuple(
            sorted(
                (
                    fixed_selected,
                    fixed_complement,
                    calibrated_selected,
                    calibrated_complement,
                )
            )
        ),
        set_relation="DISJOINT",
        jaccard_similarity=0.0,
        order_similarity=0.0,
        sequence_edit_distance=2,
        fixed_commitment_step=None,
        calibrated_commitment_step=None,
        calibrated_delayed_commitment=False,
        pair_completion_delay=None,
        budget_crowd_out=None,
        fixed_decision_cost=2.0,
        calibrated_decision_cost=2.0,
        fixed_stop_reason="decision_budget_exhausted",
        calibrated_stop_reason="decision_budget_exhausted",
    )
    classification = _classify_mechanisms(
        replays=replays,
        decomposition=decomposition,
        sequence=sequence,
        fixed_selected=fixed_selected,
        calibrated_selected=calibrated_selected,
        compatibility_passed=True,
    )
    pair = DivergencePair(
        divergence_id="divergence-fixture",
        case_id="case-fixture",
        world_id="fixture-world",
        seed=0,
        budget_label="short",
        policy="lookahead_information_gain",
        fixed_run_id="fixed-run",
        calibrated_run_id="calibrated-run",
        common_prefix_length=0,
        first_divergence_step=1,
        fixed_sequence=sequence.fixed_sequence,
        calibrated_sequence=sequence.calibrated_sequence,
    )
    truth_free = TruthFreeDivergenceCase(
        pair=pair,
        oracle_version="selected-only-common-randomness/v1",
        commitment_id="commitment-fixture",
        budget=2.0,
        public_initial_fingerprint="public-fixture",
        fixed_belief_state_id="fixed-belief",
        calibrated_belief_state_id="calibrated-belief",
        fixed_lineage_id="fixed-lineage",
        calibrated_lineage_id="calibrated-lineage",
        fixed_posterior=tuple(zip(hypothesis_ids, posterior, strict=True)),
        calibrated_posterior=tuple(zip(hypothesis_ids, posterior, strict=True)),
        fixed_snapshots=fixed_snapshots,
        calibrated_snapshots=calibrated_snapshots,
        candidates=candidates,
        replays=tuple(replays[key] for key in ("FF", "CF", "FC", "CC")),
        decomposition=decomposition,
        sequence=sequence,
        classification=classification,
        compatibility_passed=True,
        compatibility_check_ids=("fixed-decision", "calibrated-decision"),
    )
    differences = {
        "negative_log_true_hypothesis_probability": 0.2,
        "final_brier_score": 0.1,
        "final_true_hypothesis_probability": -0.1,
        "final_posterior_entropy": 0.2,
        "confidently_wrong": 1,
        "prediction_correct": -1,
        "reached_sustained_80_confidence": -1,
        "reached_sustained_95_confidence": 0,
        "matched_evidence_pairs_completed": 0.0,
        "redundant_experiments_selected": 0.0,
        "decision_cost": 0.0,
        "calibration_cost": 1.0,
        "required_total_cost": 1.0,
        "best_observed_objective": 0.0,
    }
    evaluator = EvaluatorOutcome(
        divergence_id=pair.divergence_id,
        outcome_label="hurt",
        hidden_true_hypothesis="optimizer.adam-advantage",
        fixed_metrics={},
        calibrated_metrics={},
        metric_differences=differences,
    )
    return AuditedDivergenceCase(
        truth_free=truth_free,
        truth_free_sha256=_stable_hash(truth_free.to_dict()),
        evaluator_only=evaluator,
    )


def _protocol() -> dict[str, object]:
    return {"worlds": {"configurations": [{"world_id": "fixture-world"}]}}


def test_exactly_189_divergent_pairs_are_discovered() -> None:
    rows = []
    for seed in range(189):
        for model_id, candidate_id in (
            (FIXED_SIGMA_MODEL_ID, "fixed-candidate"),
            (CALIBRATED_SIGMA_MODEL_ID, "calibrated-candidate"),
        ):
            rows.append(
                {
                    "run_id": f"run-{seed}-{model_id}",
                    "world_id": f"world-{seed}",
                    "evaluation_seed": seed,
                    "budget_label": "short",
                    "policy": "lookahead_information_gain",
                    "belief_model_id": model_id,
                    "arm_id": f"arm-{model_id}",
                    "step": 1,
                    "selected_candidate_id": candidate_id,
                }
            )
    pairs = discover_divergence_pairs_from_rows(rows, expected_count=189)
    assert len(pairs) == 189
    assert all(item.first_divergence_step == 1 for item in pairs)


def test_evaluator_files_are_locked_until_classification_closes(tmp_path: Path) -> None:
    ledger = AccessLedger()
    with pytest.raises(DivergenceAuditError, match="before Pass A closes"):
        ledger.record(tmp_path / "per_run_results.jsonl", stage="B")
    ledger.close_pass_a("a" * 64)
    ledger.record(tmp_path / "per_run_results.jsonl", stage="B")
    assert ledger.pass_b_files == ["per_run_results.jsonl"]
    assert "outcome_label" not in {item.name for item in fields(TruthFreeDivergenceCase)}


def test_scoring_adapter_has_no_truth_or_oracle_interface() -> None:
    adapter = ReadOnlyScoringAdapter(
        candidates=_fixture_candidates(), completed_experiments=(), max_cost=2.0
    )
    assert not hasattr(adapter, "hidden_true_hypothesis")
    assert not hasattr(adapter, "potential_outcomes")
    assert not hasattr(adapter, "reveal_selected")
    assert not hasattr(adapter, "observe")


def test_four_context_replay_and_shapley_are_deterministic() -> None:
    case = _fixture_case().truth_free
    first = case.replay("CC")
    adapter = ReadOnlyScoringAdapter(
        candidates=case.candidates, completed_experiments=(), max_cost=case.budget
    )
    hypothesis_ids = tuple(item for item, _ in case.calibrated_posterior)
    posterior = tuple(value for _, value in case.calibrated_posterior)
    second = adapter.replay(
        context="CC",
        hypothesis_ids=hypothesis_ids,
        posterior_probabilities=posterior,
        snapshots=case.calibrated_snapshots,
    )
    assert first == second
    assert first.winner.candidate_id == case.pair.calibrated_sequence[0]
    assert case.decomposition["reconciliation_error"] <= 1e-12
    assert case.decomposition["temporal_reconciliation_error"] <= 1e-12


def test_mechanism_priority_and_exactly_one_primary_label() -> None:
    case = _fixture_case().truth_free
    replays: dict[str, ContextReplay] = {item.context: item for item in case.replays}
    planted = _classify_mechanisms(
        replays=replays,
        decomposition=case.decomposition,
        sequence=case.sequence,
        fixed_selected=case.pair.fixed_sequence[0],
        calibrated_selected=case.pair.calibrated_sequence[0],
        compatibility_passed=False,
    )
    assert planted.primary_mechanism == "PLANNER_MODEL_MISMATCH"
    assert planted.primary_mechanism not in planted.contributing_mechanisms
    assert len([planted.primary_mechanism]) == 1


def test_sequence_metrics_and_harm_bootstrap_are_deterministic() -> None:
    case = _fixture_case()
    assert _edit_distance(("a", "b"), ("b", "a")) == 2
    assert case.truth_free.sequence.set_relation == "DISJOINT"

    def selector(item: AuditedDivergenceCase) -> bool:
        return item.truth_free.pair.world_id == "fixture-world"

    first = _harm_bootstrap_intervals(
        cases=(case,), in_stratum=selector, key=("fixture",), resamples=60
    )
    second = _harm_bootstrap_intervals(
        cases=(case,), in_stratum=selector, key=("fixture",), resamples=60
    )
    assert first == second


def test_compatibility_accumulator_detects_planted_mismatch() -> None:
    checks = CompatibilityAccumulator()
    checks.record("plan_aggregation", "trace-good", True)
    checks.record(
        "plan_aggregation",
        "trace-bad",
        False,
        expected=0.5,
        observed=0.4,
        error=0.1,
    )
    payload = checks.to_dict(
        source_checks={
            "all_frozen_source_hashes_match": True,
            "all_frozen_design_hashes_match": True,
            "no_embedded_fixed_sigma_in_scoring_paths": True,
        }
    )
    assert payload["overall_status"] == "FAIL"
    assert not checks.case_passed(("trace-bad",))


def test_divergence_audit_artifact_smoke(tmp_path: Path) -> None:
    case = _fixture_case()
    cases = (case,)
    protocol = _protocol()
    result = DivergenceAuditResult(
        input_directory=tmp_path / "frozen-input",
        repository_root=tmp_path,
        generated_at="2026-01-01T00:00:00+00:00",
        bootstrap_resamples=60,
        cases=cases,
        mechanism_summary_rows=_mechanism_summary_rows(cases, resamples=60),
        mechanism_condition_rows=_mechanism_condition_rows(cases, protocol),
        score_rows=_score_decomposition_rows(cases),
        sequence_rows=_sequence_rows(cases),
        harm_rows=_harm_concentration_rows(cases, protocol, resamples=60),
        compatibility={"overall_status": "PASS", "checks": [], "source_checks": {}},
        audit_checks={
            "all_prewrite_acceptance_checks_passed": True,
            "recommendation_rule": {"rule": "fixture"},
        },
        recommendation="Run the next frozen study.",
        source_artifact_hashes=(),
        design_hashes=(),
        access_ledger={"forbidden_files_accessed": []},
        staging_sha256="a" * 64,
        extracted_truth_free_sha256="a" * 64,
    )
    output = tmp_path / "divergence-audit-smoke"
    paths = write_divergence_outputs(result, output)
    assert set(paths) == set(FROZEN_OUTPUT_FILENAMES)
    assert {item.name for item in output.iterdir()} == set(FROZEN_OUTPUT_FILENAMES)
    manifest = json.loads(paths["divergence_manifest.json"].read_text(encoding="utf-8"))
    assert manifest["case_count"] == 1
    assert manifest["output_schema_version"] == AUDIT_SCHEMA_VERSION
    assert sum(1 for _ in paths["divergence_cases.jsonl"].open(encoding="utf-8")) == 1
