"""Frozen broader-replication orchestration without implicit full-study execution."""

from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from research_decision_engine.benchmarks.broader_execution import (
    _FULL_STUDY_EXECUTION_KEY,
    ActualExecutorAttestation,
    _require_issued_result_batch,
    execute_deterministic_map,
    validate_executor_attestation,
)
from research_decision_engine.benchmarks.broader_oracle import (
    ObservationAuthority,
    OracleEvidenceBinding,
)
from research_decision_engine.benchmarks.broader_protocol import (
    ARMS,
    FULL_SEEDS,
    FrozenArm,
    load_protocol_snapshot,
)
from research_decision_engine.benchmarks.broader_runner import (
    ArmMetrics,
    BroaderArmRun,
    evaluate_arm,
    run_arm,
    validate_recorded_calibrations,
)
from research_decision_engine.benchmarks.broader_statistics import (
    BootstrapReplicate,
    HolmInput,
    HolmResult,
    ResamplingEstimand,
    SignFlipReplicate,
    assert_executor_completeness,
    execute_formula,
    execute_gate,
)
from research_decision_engine.benchmarks.broader_worlds import (
    BUDGETS,
    GROUP_IDS,
    WORLDS,
    WORLDS_BY_ID,
)

EVALUATION_ID: Final = "broader-closed-loop-replication/v1"


@dataclass(frozen=True, slots=True)
class StudyRunSpec:
    world_id: str
    seed: int
    budget_id: str
    budget: float
    arm: FrozenArm


@dataclass(frozen=True, slots=True)
class ComparisonSpec:
    policy_id: str
    world_id: str
    seed: int
    budget_id: str
    budget: float
    fixed_arm_id: str
    calibrated_arm_id: str


@dataclass(frozen=True, slots=True)
class CalibrationSpec:
    world_id: str
    seed: int
    comparison_group_id: str


@dataclass(frozen=True, slots=True)
class ResamplingSpec:
    record_type: Literal["bootstrap", "sign_flip"]
    contrast_id: str
    replicate_index: int


@dataclass(frozen=True, slots=True)
class PairedRunResult:
    comparison_id: str
    policy_id: str
    world_id: str
    seed: int
    budget_id: str
    budget: float
    fixed_run: BroaderArmRun
    calibrated_run: BroaderArmRun
    fixed_metrics: ArmMetrics
    calibrated_metrics: ArmMetrics
    outcome_label: Literal["helped", "hurt", "mixed", "nondivergent"]


@dataclass(frozen=True, slots=True)
class AttestedStudyExecution:
    """Opaque orchestration result retaining exact full-study executor authority."""

    results: tuple[BroaderArmRun, ...]
    executor_attestation: ActualExecutorAttestation
    execution_authority: OracleEvidenceBinding | None
    production_full_study: bool

    def __len__(self) -> int:
        return len(self.results)


_ISSUED_STUDY_EXECUTIONS: dict[int, AttestedStudyExecution] = {}


class FrozenStudyOrchestrator:
    """The sole lazy executor for the predeclared 36,864-trajectory matrix."""

    def iter_run_specs(self) -> Iterator[StudyRunSpec]:
        for world in WORLDS:
            for seed in FULL_SEEDS:
                for budget_id, budget in BUDGETS:
                    for arm in ARMS:
                        yield StudyRunSpec(world.public.world_id, seed, budget_id, budget, arm)

    def iter_comparison_specs(self) -> Iterator[ComparisonSpec]:
        arm_pairs = (
            ("information_gain", "fixed_ig", "calibrated_ig"),
            (
                "lookahead_information_gain",
                "fixed_lookahead",
                "calibrated_lookahead",
            ),
        )
        for policy_id, fixed_arm_id, calibrated_arm_id in arm_pairs:
            for world in WORLDS:
                for seed in FULL_SEEDS:
                    for budget_id, budget in BUDGETS:
                        yield ComparisonSpec(
                            policy_id,
                            world.public.world_id,
                            seed,
                            budget_id,
                            budget,
                            fixed_arm_id,
                            calibrated_arm_id,
                        )

    def iter_calibration_specs(self) -> Iterator[CalibrationSpec]:
        for world in WORLDS:
            for seed in FULL_SEEDS:
                for group_id in GROUP_IDS:
                    yield CalibrationSpec(world.public.world_id, seed, group_id)

    def execute_run(self, specification: StudyRunSpec) -> BroaderArmRun:
        world = WORLDS_BY_ID[specification.world_id]
        return run_arm(
            arm=specification.arm,
            world=world.public,
            seed=specification.seed,
            budget_id=specification.budget_id,
            budget=specification.budget,
            authority=ObservationAuthority(world=world, seed=specification.seed),
        )

    def execute_specs(
        self,
        specifications: Iterable[StudyRunSpec],
        *,
        worker_count: int = 1,
    ) -> AttestedStudyExecution:
        """Execute an explicit diagnostic subset that cannot become full-study authority."""

        jobs = tuple(specifications)
        results, attestation = execute_deterministic_map(
            self.execute_run,
            jobs,
            worker_count=worker_count,
            executor_kind="serial" if worker_count == 1 else "thread_pool",
            result_order="input_order",
            execution_purpose="diagnostic",
        )
        validate_executor_attestation(
            attestation,
            results=results,
            expected_purpose="diagnostic",
            require_trust_domain="fixture",
        )
        execution = AttestedStudyExecution(results, attestation, None, False)
        _ISSUED_STUDY_EXECUTIONS[id(execution)] = execution
        return execution

    def execute_full_study(
        self,
        *,
        oracle_evidence_binding: OracleEvidenceBinding,
        worker_count: int = 1,
    ) -> AttestedStudyExecution:
        """Execute only the exact frozen 36,864-run population under production authority."""

        if type(oracle_evidence_binding) is not OracleEvidenceBinding:
            raise TypeError("Full-study execution requires exact Oracle production authority.")
        jobs = tuple(self.iter_run_specs())
        if len(jobs) != 36_864:
            raise ValueError("Full-study execution requires the exact frozen run population.")
        results, attestation = execute_deterministic_map(
            self.execute_run,
            jobs,
            worker_count=worker_count,
            executor_kind="serial" if worker_count == 1 else "thread_pool",
            result_order="input_order",
            execution_authority=oracle_evidence_binding,
            execution_purpose="full_study",
            _full_study_execution_key=_FULL_STUDY_EXECUTION_KEY,
        )
        validate_executor_attestation(
            attestation,
            results=results,
            execution_authority=oracle_evidence_binding,
            expected_purpose="full_study",
            expected_validation_run_id=oracle_evidence_binding.validation_run_identity,
            expected_evidence_bundle_identity=oracle_evidence_binding.evidence_bundle_identity,
            require_trust_domain="production",
        )
        execution = AttestedStudyExecution(
            results,
            attestation,
            oracle_evidence_binding,
            True,
        )
        _ISSUED_STUDY_EXECUTIONS[id(execution)] = execution
        return execution

    def validate_population_shape(self) -> None:
        if sum(1 for _ in self.iter_run_specs()) != 36_864:
            raise ValueError("Frozen run-spec population does not contain 36,864 rows.")
        if sum(1 for _ in self.iter_comparison_specs()) != 18_432:
            raise ValueError("Frozen paired population does not contain 18,432 rows.")
        if sum(1 for _ in self.iter_calibration_specs()) != 9_216:
            raise ValueError("Frozen calibration population does not contain 9,216 rows.")


def _require_full_study_execution(execution: AttestedStudyExecution) -> tuple[BroaderArmRun, ...]:
    if (
        type(execution) is not AttestedStudyExecution
        or _ISSUED_STUDY_EXECUTIONS.get(id(execution)) is not execution
        or not execution.production_full_study
        or type(execution.execution_authority) is not OracleEvidenceBinding
    ):
        raise ValueError("Scientific consumption requires exact-issued full-study execution.")
    authority = execution.execution_authority
    _require_issued_result_batch(
        execution.results,
        expected_purposes=("full_study",),
        require_trust_domain="production",
    )
    validate_executor_attestation(
        execution.executor_attestation,
        results=execution.results,
        execution_authority=authority,
        expected_purpose="full_study",
        expected_validation_run_id=authority.validation_run_identity,
        expected_evidence_bundle_identity=authority.evidence_bundle_identity,
        require_trust_domain="production",
    )
    return execution.results


def pair_completed_runs(execution: AttestedStudyExecution) -> tuple[PairedRunResult, ...]:
    """Create evaluator rows only from exact-issued production full-study results."""

    return _pair_completed_runs_validated(_require_full_study_execution(execution))


def _pair_completed_runs_validated(
    runs: Sequence[BroaderArmRun],
) -> tuple[PairedRunResult, ...]:
    """Pair a result batch whose exact executor boundary was already checked by its caller."""

    validate_recorded_calibrations(runs)
    grouped: dict[str, list[BroaderArmRun]] = {}
    for run in runs:
        grouped.setdefault(run.comparison_id, []).append(run)
    results: list[PairedRunResult] = []
    for comparison_id in sorted(grouped, key=lambda item: item.encode("utf-8")):
        pair = grouped[comparison_id]
        if len(pair) != 2:
            raise ValueError(f"Comparison {comparison_id} does not have exactly two arms.")
        fixed = next((item for item in pair if item.arm.arm_id.startswith("fixed_")), None)
        calibrated = next(
            (item for item in pair if item.arm.arm_id.startswith("calibrated_")), None
        )
        if fixed is None or calibrated is None:
            raise ValueError(f"Comparison {comparison_id} lacks fixed/calibrated ownership.")
        if (
            fixed.world_id,
            fixed.seed,
            fixed.budget_id,
            fixed.budget,
            fixed.arm.policy_id,
        ) != (
            calibrated.world_id,
            calibrated.seed,
            calibrated.budget_id,
            calibrated.budget,
            calibrated.arm.policy_id,
        ):
            raise ValueError(f"Comparison {comparison_id} has mismatched paired conditions.")
        truth = WORLDS_BY_ID[fixed.world_id].hidden.scientific_hypothesis_id
        fixed_metrics = evaluate_arm(fixed, truth)
        calibrated_metrics = evaluate_arm(calibrated, truth)
        outcome = _outcome_label(fixed, calibrated, fixed_metrics, calibrated_metrics)
        results.append(
            PairedRunResult(
                comparison_id,
                fixed.arm.policy_id,
                fixed.world_id,
                fixed.seed,
                fixed.budget_id,
                fixed.budget,
                fixed,
                calibrated,
                fixed_metrics,
                calibrated_metrics,
                outcome,
            )
        )
    return tuple(results)


class FrozenAnalysisOrchestrator:
    """Registry-owned contrast, resampling, Holm, gate, and branch execution surface."""

    def __init__(self) -> None:
        assert_executor_completeness()
        self._snapshot = load_protocol_snapshot()

    def contrast_ids(self) -> tuple[str, ...]:
        return (
            self._snapshot.registry("confirmatory").ids("contrast_id")
            + self._snapshot.registry("decision").ids("contrast_id")
            + self._snapshot.registry("descriptive").ids("contrast_id")
        )

    def iter_resampling_specs(self) -> Iterator[ResamplingSpec]:
        confirmatory = self._snapshot.registry("confirmatory").records()
        for row in confirmatory:
            for replicate_index in range(10_000):
                yield ResamplingSpec("bootstrap", row["contrast_id"], replicate_index)
        for row in confirmatory:
            if row["holm_member"] != "true":
                continue
            for replicate_index in range(10_000):
                yield ResamplingSpec("sign_flip", row["contrast_id"], replicate_index)

    def resampling_counts(self) -> tuple[int, int, int]:
        bootstrap = 66 * 10_000
        sign_flip = 64 * 10_000
        return bootstrap, sign_flip, bootstrap + sign_flip

    def execute_resampling_spec(
        self,
        specification: ResamplingSpec,
        *,
        estimand: ResamplingEstimand,
        observed_statistic: float = 0.0,
    ) -> BootstrapReplicate | SignFlipReplicate:
        if specification.record_type == "bootstrap":
            result = execute_formula(
                "bootstrap_10000",
                {
                    "contrast_id": specification.contrast_id,
                    "replicate_index": specification.replicate_index,
                    "ordered_128_seed_blocks": FULL_SEEDS,
                    "estimand_formula_id": estimand,
                },
            )
            if not isinstance(result, BootstrapReplicate):
                raise TypeError("Bootstrap executor returned the wrong frozen result type.")
            return result
        result = execute_formula(
            "signflip_10000",
            {
                "contrast_id": specification.contrast_id,
                "replicate_index": specification.replicate_index,
                "ordered_paired_seed_blocks": FULL_SEEDS,
                "observed_statistic": observed_statistic,
                "estimand_formula_id": estimand,
            },
        )
        if not isinstance(result, SignFlipReplicate):
            raise TypeError("Sign-flip executor returned the wrong frozen result type.")
        return result

    def execute_holm(self, inputs: Sequence[HolmInput]) -> tuple[HolmResult, ...]:
        identifiers = self._snapshot.registry("statistical_hypothesis").ids(
            "statistical_hypothesis_id"
        )
        p_raw = {item.statistical_hypothesis_id: item.p_raw for item in inputs}
        result = execute_formula(
            "HOLM-64",
            OrderedDict(
                (
                    ("ordered_64_statistical_hypothesis_ids", identifiers),
                    ("p_raw", p_raw),
                    ("statistical_hypothesis_order", identifiers),
                )
            ),
        )
        return tuple(result)  # type: ignore[arg-type]

    def execute_gate(self, gate_id: str, operands: Mapping[str, object]) -> object:
        return execute_gate(gate_id, operands)

    def analyze(
        self,
        execution: AttestedStudyExecution,
        *,
        bootstrap_replicates: int = 10_000,
        sign_flip_replicates: int = 10_000,
    ) -> object:
        from research_decision_engine.benchmarks.broader_analysis import (
            ProductionAnalysisConfig,
            analyze_trajectories,
        )

        runs = _require_full_study_execution(execution)
        return analyze_trajectories(
            runs,
            config=ProductionAnalysisConfig(
                bootstrap_replicates=bootstrap_replicates,
                sign_flip_replicates=sign_flip_replicates,
            ),
        )

    def validate_declared_counts(self) -> None:
        if len(self.contrast_ids()) != 122:
            raise ValueError("Frozen analysis does not contain 122 contrast plans.")
        if self.resampling_counts() != (660_000, 640_000, 1_300_000):
            raise ValueError("Frozen resampling counts changed.")
        if len(self._snapshot.statistical_hypotheses) != 64:
            raise ValueError("HOLM-64 membership changed.")


def _outcome_label(
    fixed: BroaderArmRun,
    calibrated: BroaderArmRun,
    fixed_metrics: ArmMetrics,
    calibrated_metrics: ArmMetrics,
) -> Literal["helped", "hurt", "mixed", "nondivergent"]:
    if fixed.selected_candidate_ids == calibrated.selected_candidate_ids:
        return "nondivergent"
    tolerance = 1e-12
    if (
        fixed_metrics.nll - calibrated_metrics.nll > tolerance
        and fixed_metrics.brier - calibrated_metrics.brier > tolerance
    ):
        return "helped"
    if (
        calibrated_metrics.nll - fixed_metrics.nll > tolerance
        and calibrated_metrics.brier - fixed_metrics.brier > tolerance
    ):
        return "hurt"
    return "mixed"


def validate_orchestration_contracts() -> None:
    study = FrozenStudyOrchestrator()
    study.validate_population_shape()
    analysis = FrozenAnalysisOrchestrator()
    analysis.validate_declared_counts()
    if not math.isclose(sum(value for _, value in BUDGETS), 13.5, abs_tol=0.0):
        raise ValueError("Frozen budget ledger changed.")
