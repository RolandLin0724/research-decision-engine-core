from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from functools import cache

from research_decision_engine.belief_models import MatchedEffectObservation
from research_decision_engine.benchmarks.broader_artifacts import serialize_jsonl_artifact
from research_decision_engine.benchmarks.broader_calibration_history import (
    CalibrationHistorySelection,
    select_calibration_history,
)
from research_decision_engine.benchmarks.broader_oracle import ObservationAuthority
from research_decision_engine.benchmarks.broader_projection import _calibration_rows
from research_decision_engine.benchmarks.broader_runner import (
    BroaderArmRun,
    arm_spec,
    run_arm,
)
from research_decision_engine.benchmarks.broader_worlds import (
    BUDGETS,
    GROUP_IDS,
    WORLDS_BY_ID,
)

WORLD_ID = "h_adam_low"
SEED = 9000


@cache
def calibrated_run(
    arm_id: str = "calibrated_ig",
    budget_id: str = "budget-2.25",
    budget: float = 2.25,
) -> BroaderArmRun:
    world = WORLDS_BY_ID[WORLD_ID]
    return run_arm(
        arm=arm_spec(arm_id),
        world=world.public,
        seed=SEED,
        budget_id=budget_id,
        budget=budget,
        authority=ObservationAuthority(world=world, seed=SEED),
    )


@cache
def calibrated_deployment_runs() -> tuple[BroaderArmRun, ...]:
    return tuple(
        calibrated_run(arm_id, budget_id, budget)
        for budget_id, budget in BUDGETS
        for arm_id in ("calibrated_ig", "calibrated_lookahead")
    )


def selection_for_run(
    run: BroaderArmRun,
    comparison_group_id: str = GROUP_IDS[0],
) -> CalibrationHistorySelection:
    assert run.calibration is not None
    estimate = next(
        item
        for item in run.calibration.estimates
        if item.comparison_group_id == comparison_group_id
    )
    return select_calibration_history(
        run_id=run.run_id,
        world_id=run.world_id,
        seed=run.seed,
        comparison_group_id=comparison_group_id,
        recorded_observations=estimate.observations,
        recorded_effects=run.effect_history,
    )


def unrelated_effect(
    run: BroaderArmRun,
    *,
    case_id: str,
    comparison_group_id: str,
    available_sequence: int,
) -> MatchedEffectObservation:
    assert run.calibration is not None
    template = run.calibration.effects[0]
    return replace(
        template,
        effect_id=f"unrelated-effect/{case_id}",
        comparison_group_id=comparison_group_id,
        available_sequence=available_sequence,
        source_kind="decision",
        source_ids=(f"unrelated-left/{case_id}", f"unrelated-right/{case_id}"),
    )


def replace_deployment_run(
    runs: Sequence[BroaderArmRun], replacement: BroaderArmRun
) -> tuple[BroaderArmRun, ...]:
    return tuple(replacement if run.run_id == replacement.run_id else run for run in runs)


def artifact5_bytes(runs: Sequence[BroaderArmRun]) -> bytes:
    return serialize_jsonl_artifact(
        schema_version="calibration-estimate/v2",
        source_design_sha256="0" * 64,
        rows=_calibration_rows(runs),
    )
