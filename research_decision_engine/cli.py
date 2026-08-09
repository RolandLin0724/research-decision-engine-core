"""Command-line interface for Research Decision Engine Core."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

from research_decision_engine.benchmarks.closed_loop_evaluation import (
    CLOSED_LOOP_BOOTSTRAP_RESAMPLES,
    CLOSED_LOOP_DEFAULT_SEEDS,
    run_closed_loop_evaluation,
)
from research_decision_engine.benchmarks.closed_loop_reporting import (
    render_closed_loop_terminal_summary,
    write_closed_loop_outputs,
)
from research_decision_engine.benchmarks.evaluation import (
    ALL_BENCHMARK_POLICIES,
    BENCHMARK_POLICIES,
    DEFAULT_BENCHMARK_BUDGET,
    DEFAULT_BENCHMARK_SEEDS,
    run_benchmark_suite,
)
from research_decision_engine.benchmarks.paired_evaluation import (
    DEFAULT_BOOTSTRAP_RESAMPLES,
    DEFAULT_LARGE_BUDGET,
    DEFAULT_PAIRED_SEEDS,
    DEFAULT_SHORT_BUDGET,
    run_paired_evaluation,
)
from research_decision_engine.benchmarks.paired_reporting import (
    render_evaluation_terminal_summary,
    write_paired_evaluation_outputs,
)
from research_decision_engine.benchmarks.reporting import (
    render_terminal_summary,
    write_benchmark_outputs,
)
from research_decision_engine.benchmarks.robust_evaluation import (
    ROBUST_BOOTSTRAP_RESAMPLES,
    ROBUST_DEFAULT_SEEDS,
    run_robust_belief_evaluation,
)
from research_decision_engine.benchmarks.robust_reporting import (
    render_robust_terminal_summary,
    write_robust_belief_outputs,
)
from research_decision_engine.benchmarks.worlds import (
    all_benchmark_world_ids,
    benchmark_world_ids,
)
from research_decision_engine.decision import INFORMATION_GAIN_POLICY, DecisionTrace
from research_decision_engine.lookahead import (
    LOOKAHEAD_INFORMATION_GAIN_POLICY,
    LookaheadPlanTrace,
)
from research_decision_engine.optimizer_effect import synchronize_optimizer_reasoning
from research_decision_engine.robust_storage import RobustBeliefStore
from research_decision_engine.runner import (
    run_next,
    suggest_information_gain,
    suggest_lookahead_information_gain,
    suggest_next,
)
from research_decision_engine.storage import ExperimentStore


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "benchmark":
        benchmark_report = run_benchmark_suite(
            world_ids=tuple(args.world),
            policies=tuple(args.policy),
            seeds=tuple(args.seeds),
            budget=args.budget,
        )
        benchmark_paths = write_benchmark_outputs(benchmark_report, args.output_directory)
        print(render_terminal_summary(benchmark_report, benchmark_paths))
        return

    if args.command == "evaluate":
        seeds = tuple(args.seeds) if args.seeds is not None else tuple(range(args.seed_count))
        evaluation_report = run_paired_evaluation(
            seeds=seeds,
            short_budget=args.short_budget,
            large_budget=args.large_budget,
            bootstrap_resamples=args.bootstrap_resamples,
        )
        evaluation_paths = write_paired_evaluation_outputs(evaluation_report, args.output_directory)
        print(render_evaluation_terminal_summary(evaluation_report, evaluation_paths))
        return

    if args.command == "evaluate-beliefs":
        seeds = tuple(args.seeds) if args.seeds is not None else tuple(range(args.seed_count))
        robust_result = run_robust_belief_evaluation(
            seeds=seeds,
            generated_at=datetime.now(UTC).isoformat(),
            bootstrap_resamples=args.bootstrap_resamples,
        )
        robust_paths = write_robust_belief_outputs(
            robust_result,
            args.output_directory,
        )
        print(render_robust_terminal_summary(robust_result, robust_paths))
        return

    if args.command == "evaluate-closed-loop":
        seeds = tuple(args.seeds) if args.seeds is not None else tuple(range(args.seed_count))
        closed_loop_result = run_closed_loop_evaluation(
            seeds=seeds,
            generated_at=datetime.now(UTC).isoformat(),
            bootstrap_resamples=args.bootstrap_resamples,
        )
        closed_loop_paths = write_closed_loop_outputs(
            closed_loop_result,
            args.output_directory,
        )
        print(render_closed_loop_terminal_summary(closed_loop_result, closed_loop_paths))
        return

    db_path = Path(args.db)

    with ExperimentStore(db_path) as store:
        store.init_schema()
        synchronize_optimizer_reasoning(store)
        if args.command == "init":
            print(json.dumps({"db": str(db_path), "status": "initialized"}, sort_keys=True))
            return
        if args.command == "suggest":
            if args.policy == INFORMATION_GAIN_POLICY:
                trace = suggest_information_gain(store, max_cost=args.max_cost)
                print(json.dumps(_suggestion_summary(trace), indent=2, sort_keys=True))
                return
            if args.policy == LOOKAHEAD_INFORMATION_GAIN_POLICY:
                plan = suggest_lookahead_information_gain(store, max_cost=args.max_cost)
                print(json.dumps(_lookahead_summary(plan), indent=2, sort_keys=True))
                return
            candidate = suggest_next(
                store,
                policy_name=args.policy,
                seed=args.seed,
                max_cost=args.max_cost,
            )
            print(
                json.dumps(
                    {"candidate_id": candidate.candidate_id, "params": candidate.params()},
                    sort_keys=True,
                )
            )
            return
        if args.command == "run":
            record = run_next(
                store,
                policy_name=args.policy,
                seed=args.seed,
                max_cost=args.max_cost,
            )
            print(json.dumps(record.to_dict(), sort_keys=True))
            return
        if args.command == "history":
            records = [record.to_dict() for record in store.list_records()]
            print(json.dumps(records, indent=2, sort_keys=True))
            return
        if args.command == "beliefs":
            print(json.dumps(_beliefs_payload(store), indent=2, sort_keys=True))
            return
        if args.command == "evidence":
            print(json.dumps(_evidence_payload(store), indent=2, sort_keys=True))
            return
        if args.command == "explain-belief-update":
            try:
                payload = _belief_update_payload(store, args.update_id)
            except KeyError as error:
                _die(str(error))
            print(json.dumps(payload, indent=2, sort_keys=True))
            return
        if args.command == "explain-suggestion":
            latest_trace = store.latest_decision_trace()
            if latest_trace is None:
                _die("No belief-guided suggestion has been recorded.")
            print(
                json.dumps(_suggestion_explanation(store, latest_trace), indent=2, sort_keys=True)
            )
            return
        if args.command == "explain-plan":
            latest_plan = store.latest_lookahead_plan_trace()
            if latest_plan is None:
                _die("No two-step lookahead plan has been recorded.")
            print(json.dumps(_plan_explanation(store, latest_plan), indent=2, sort_keys=True))
            return
        robust_store = RobustBeliefStore(store)
        if args.command == "calibration-history":
            print(
                json.dumps(
                    {
                        "matched_effects": robust_store.calibration_history(),
                        "cost_ledger": robust_store.cost_summary(),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return
        if args.command == "sigma-estimates":
            print(json.dumps(robust_store.sigma_estimates(), indent=2, sort_keys=True))
            return
        if args.command == "belief-lineages":
            print(
                json.dumps(
                    _decode_json_fields(
                        robust_store.belief_lineages(),
                        ("posterior_probabilities_json",),
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
            return
        if args.command == "explain-sigma-estimate":
            sigma_payload = robust_store.explain_sigma_estimate(args.estimate_id)
            if sigma_payload is None:
                _die(f"Unknown sigma estimate: {args.estimate_id}")
            print(
                json.dumps(
                    _decode_json_object(
                        sigma_payload,
                        (
                            "provenance_json",
                            "details_json",
                            "decision_evidence_provenance_json",
                            "calibration_effect_provenance_json",
                        ),
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
            return
        if args.command == "model-adequacy":
            print(json.dumps(robust_store.model_adequacy(), indent=2, sort_keys=True))
            return

    _die(f"Unhandled command: {args.command}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rde", description="Research Decision Engine Core")
    parser.add_argument(
        "--db", default="rde.sqlite", help="Path to the SQLite experiment database."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize the SQLite experiment database.")

    suggest = subparsers.add_parser("suggest", help="Suggest the next experiment.")
    _add_policy_args(suggest)

    run = subparsers.add_parser("run", help="Suggest, evaluate, and record one experiment.")
    _add_policy_args(run)

    subparsers.add_parser("history", help="Print experiment history as JSON.")
    subparsers.add_parser("beliefs", help="Print current optimizer-effect beliefs.")
    subparsers.add_parser("evidence", help="Print matched-experiment evidence.")

    explain = subparsers.add_parser(
        "explain-belief-update", help="Explain one persisted Bayesian belief update."
    )
    explain.add_argument("update_id", help="Stable belief-update ID to explain.")

    subparsers.add_parser(
        "explain-suggestion", help="Explain the latest persisted belief-guided suggestion."
    )
    subparsers.add_parser(
        "explain-plan", help="Explain the latest persisted two-step lookahead plan."
    )
    subparsers.add_parser(
        "calibration-history",
        help="Inspect calibration-only matched effects and their cost ledger.",
    )
    subparsers.add_parser(
        "sigma-estimates", help="Inspect model-scoped standard-deviation estimates."
    )
    subparsers.add_parser(
        "belief-lineages", help="Inspect isolated model-specific belief lineages."
    )
    explain_sigma = subparsers.add_parser(
        "explain-sigma-estimate",
        help="Explain one persisted standard-deviation estimate and its sources.",
    )
    explain_sigma.add_argument("estimate_id", help="Stable sigma-estimate ID to explain.")
    subparsers.add_parser(
        "model-adequacy", help="Inspect truth-free prequential adequacy diagnostics."
    )

    benchmark = subparsers.add_parser(
        "benchmark", help="Compare supported experiment-selection policies."
    )
    benchmark.add_argument(
        "--seeds",
        nargs="+",
        type=int,
        default=list(DEFAULT_BENCHMARK_SEEDS),
        help="One or more deterministic benchmark seeds.",
    )
    benchmark.add_argument(
        "--budget",
        type=float,
        default=DEFAULT_BENCHMARK_BUDGET,
        help="Cumulative experimental cost budget for every run.",
    )
    benchmark.add_argument(
        "--world",
        nargs="+",
        choices=all_benchmark_world_ids(),
        default=list(benchmark_world_ids()),
        help="One or more benchmark world IDs.",
    )
    benchmark.add_argument(
        "--policy",
        nargs="+",
        choices=ALL_BENCHMARK_POLICIES,
        default=list(BENCHMARK_POLICIES),
        help="One or more existing policies to compare.",
    )
    benchmark.add_argument(
        "--output-directory",
        type=Path,
        default=Path("benchmark-results"),
        help="Directory for JSON and CSV benchmark results.",
    )

    evaluate = subparsers.add_parser(
        "evaluate",
        help="Run the rigorous paired four-policy lookahead evaluation.",
    )
    seed_group = evaluate.add_mutually_exclusive_group()
    seed_group.add_argument(
        "--seeds",
        nargs="+",
        type=int,
        default=None,
        help="Explicit paired seed schedule.",
    )
    seed_group.add_argument(
        "--seed-count",
        type=int,
        default=len(DEFAULT_PAIRED_SEEDS),
        help="Use seeds from zero through seed-count minus one.",
    )
    evaluate.add_argument(
        "--short-budget",
        type=float,
        default=DEFAULT_SHORT_BUDGET,
    )
    evaluate.add_argument(
        "--large-budget",
        type=float,
        default=DEFAULT_LARGE_BUDGET,
    )
    evaluate.add_argument(
        "--bootstrap-resamples",
        type=int,
        default=DEFAULT_BOOTSTRAP_RESAMPLES,
    )
    evaluate.add_argument(
        "--output-directory",
        type=Path,
        default=Path("paired-evaluation-v1"),
        help="Versioned directory for paired evaluation artifacts.",
    )

    robust_evaluate = subparsers.add_parser(
        "evaluate-beliefs",
        help="Run the frozen paired evaluation of the two belief models.",
    )
    robust_seed_group = robust_evaluate.add_mutually_exclusive_group()
    robust_seed_group.add_argument(
        "--seeds",
        nargs="+",
        type=int,
        default=None,
        help="Explicit paired seed schedule.",
    )
    robust_seed_group.add_argument(
        "--seed-count",
        type=int,
        default=len(ROBUST_DEFAULT_SEEDS),
        help="Use seeds from zero through seed-count minus one.",
    )
    robust_evaluate.add_argument(
        "--bootstrap-resamples",
        type=int,
        default=ROBUST_BOOTSTRAP_RESAMPLES,
    )
    robust_evaluate.add_argument(
        "--output-directory",
        type=Path,
        default=Path("robust-belief-evaluation-v1"),
        help="New versioned directory for robust-belief evaluation artifacts.",
    )

    closed_loop_evaluate = subparsers.add_parser(
        "evaluate-closed-loop",
        help="Run the frozen four-arm closed-loop belief-control evaluation.",
    )
    closed_loop_seed_group = closed_loop_evaluate.add_mutually_exclusive_group()
    closed_loop_seed_group.add_argument(
        "--seeds",
        nargs="+",
        type=int,
        default=None,
        help="Explicit paired seed schedule; full evaluation uses 0 through 99.",
    )
    closed_loop_seed_group.add_argument(
        "--seed-count",
        type=int,
        default=len(CLOSED_LOOP_DEFAULT_SEEDS),
        help="Use seeds from zero through seed-count minus one.",
    )
    closed_loop_evaluate.add_argument(
        "--bootstrap-resamples",
        type=int,
        default=CLOSED_LOOP_BOOTSTRAP_RESAMPLES,
    )
    closed_loop_evaluate.add_argument(
        "--output-directory",
        type=Path,
        default=Path("closed-loop-evaluation-v1-100-seeds"),
        help="New versioned directory for closed-loop evaluation artifacts.",
    )
    return parser


def _add_policy_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--policy",
        choices=[
            "random",
            "greedy",
            INFORMATION_GAIN_POLICY,
            LOOKAHEAD_INFORMATION_GAIN_POLICY,
        ],
        default="random",
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--max-cost",
        type=float,
        default=None,
        help="Current decision budget for belief-guided policies.",
    )


def _beliefs_payload(store: ExperimentStore) -> dict[str, object]:
    current = store.current_belief_state()
    if current is None:
        raise RuntimeError("Optimizer-effect beliefs are not initialized.")
    supporting_counts = store.supporting_evidence_counts()
    hypotheses = [
        {
            "hypothesis_id": hypothesis.hypothesis_id,
            "statement": hypothesis.statement,
            "prior_probability": hypothesis.prior_probability,
            "current_posterior_probability": current.posterior_for(hypothesis.hypothesis_id),
            "supporting_evidence_count": supporting_counts[hypothesis.hypothesis_id],
        }
        for hypothesis in store.list_hypotheses()
    ]
    return {
        "belief_state_id": current.belief_state_id,
        "evidence_count": len(current.evidence_ids),
        "hypotheses": hypotheses,
    }


def _evidence_payload(store: ExperimentStore) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for evidence in store.list_evidence():
        item = evidence.to_dict()
        item["belief_update_id"] = store.update_id_for_evidence(evidence.evidence_id)
        payload.append(item)
    return payload


def _belief_update_payload(store: ExperimentStore, update_id: str) -> dict[str, object]:
    update = store.get_belief_update(update_id)
    hypotheses = {item.hypothesis_id: item for item in store.list_hypotheses()}
    source_experiments = []
    for source_id in update.evidence.source_experiment_ids:
        record = store.get_record(source_id)
        source_experiments.append(
            {
                "experiment_id": source_id,
                "candidate_id": record.candidate.candidate_id,
                "params": record.candidate.params(),
                "policy": record.policy,
                "observed_value": record.observed_value,
                "created_at": record.created_at,
            }
        )

    calculations = []
    for item in update.likelihoods:
        hypothesis = hypotheses[item.hypothesis_id]
        calculations.append(
            {
                **item.to_dict(),
                "statement": hypothesis.statement,
                "predicted_evidence_distribution": {
                    "type": hypothesis.prediction_model.model_type,
                    "version": hypothesis.prediction_model.version,
                    "parameters": hypothesis.prediction_model.parameters(),
                },
                "weight_calculation": (
                    f"{item.prior_for_update!r} * {item.likelihood!r} "
                    f"= {item.unnormalized_weight!r}"
                ),
            }
        )

    return {
        "update_id": update.update_id,
        "update_rule_version": update.update_rule_version,
        "created_at": update.created_at,
        "belief_state_before": update.belief_state_before.to_dict(),
        "evidence": update.evidence.to_dict(),
        "source_experiments": source_experiments,
        "likelihood_calculations": calculations,
        "normalization_constant": update.normalization_constant,
        "normalization_formula": "posterior = unnormalized_weight / normalization_constant",
        "posterior_belief_state": update.posterior_belief_state.to_dict(),
        "provenance": update.provenance.to_dict(),
    }


def _suggestion_summary(trace: DecisionTrace) -> dict[str, object]:
    return {
        "suggestion_id": trace.suggestion_id,
        "policy": trace.policy,
        "candidate_id": trace.candidate.candidate_id,
        "params": trace.candidate.params(),
        "expected_information_gain": trace.selected.expected_information_gain,
        "fallback_reason": trace.fallback_reason,
    }


def _suggestion_explanation(store: ExperimentStore, trace: DecisionTrace) -> dict[str, object]:
    belief_state = store.get_belief_state(trace.belief_state_id)
    alternatives = [item.to_dict() for item in trace.ranked_candidates[1:4]]
    return {
        "suggestion_id": trace.suggestion_id,
        "policy": trace.policy,
        "policy_version": trace.policy_version,
        "created_at": trace.created_at,
        "candidate_suggested": trace.selected.to_dict(),
        "score_breakdown": {
            "prior_entropy_bits": trace.selected.prior_entropy,
            "expected_posterior_entropy_bits": trace.selected.expected_posterior_entropy,
            "expected_information_gain_bits": trace.selected.expected_information_gain,
        },
        "belief_state_id": trace.belief_state_id,
        "current_hypothesis_probabilities": belief_state.posterior_map(),
        "competing_hypotheses": [item.to_dict() for item in trace.hypotheses],
        "budget": {
            "max_next_experiment_cost": trace.max_cost,
            "selected_candidate_cost": trace.selected.estimated_cost,
            "feasible": trace.selected.estimated_cost <= trace.max_cost,
        },
        "fallback_reason": trace.fallback_reason,
        "decision_rationale": trace.rationale,
        "top_competing_alternatives": alternatives,
        "provenance": trace.provenance.to_dict(),
    }


def _lookahead_summary(trace: LookaheadPlanTrace) -> dict[str, object]:
    return {
        "plan_id": trace.plan_id,
        "policy": trace.policy,
        "candidate_id": trace.candidate.candidate_id,
        "params": trace.candidate.params(),
        "first_action_effect": trace.selected.action_effect,
        "immediate_information_gain": trace.selected.immediate_information_gain,
        "expected_two_step_information_gain": (trace.selected.expected_total_information_gain),
        "expected_total_cost": trace.selected.expected_total_cost,
        "information_gain_per_expected_cost": (trace.selected.information_gain_per_expected_cost),
        "fallback_reason": trace.fallback_reason,
    }


def _plan_explanation(store: ExperimentStore, trace: LookaheadPlanTrace) -> dict[str, object]:
    payload = trace.to_dict()
    payload["real_belief_state_provenance"] = store.get_belief_state(
        trace.belief_state_id
    ).to_dict()
    payload["execution_semantics"] = (
        "Only selected_first_experiment is returned for execution; the branch-specific second "
        "actions are hypothetical and the engine replans from real persisted state afterward."
    )
    return payload


def _die(message: str) -> NoReturn:
    raise SystemExit(message)


def _decode_json_fields(
    rows: list[dict[str, object]], fields: tuple[str, ...]
) -> list[dict[str, object]]:
    return [_decode_json_object(row, fields) for row in rows]


def _decode_json_object(payload: dict[str, object], fields: tuple[str, ...]) -> dict[str, object]:
    decoded = dict(payload)
    for field in fields:
        value = decoded.get(field)
        if isinstance(value, str):
            decoded[field.removesuffix("_json")] = json.loads(value)
            del decoded[field]
    sources = decoded.get("sources")
    if isinstance(sources, list):
        decoded["sources"] = [
            _decode_json_object(item, fields) if isinstance(item, dict) else item
            for item in sources
        ]
    diagnostic = decoded.get("diagnostic")
    if isinstance(diagnostic, dict):
        decoded["diagnostic"] = _decode_json_object(diagnostic, fields)
    return decoded


if __name__ == "__main__":
    main()
