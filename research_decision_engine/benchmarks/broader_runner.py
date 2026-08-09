"""Isolated closed-loop runner for the frozen broader-replication protocol."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final, Literal

from research_decision_engine.belief_models import (
    CALIBRATED_SIGMA_MODEL_ID,
    FIXED_SIGMA_MODEL_ID,
    SIGMA_FLOOR,
    BeliefModelLineage,
    MatchedEffectObservation,
    ModelAdequacyDiagnostic,
    ModelBeliefState,
    ModelBeliefUpdate,
    belief_model,
)
from research_decision_engine.benchmarks.broader_calibration_history import (
    CALIBRATION_SIGMA_DDOF,
    CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
    CalibrationHistorySelection,
    RunProvenanceError,
    expected_calibration_effect,
    select_calibration_history,
)
from research_decision_engine.benchmarks.broader_oracle import (
    CALIBRATION_NAMESPACE,
    DECISION_NAMESPACE,
    ObservationAuthority,
    OracleError,
    RevealedObservation,
    authorize_observation,
    reobserve_authorized_observation,
)
from research_decision_engine.benchmarks.broader_protocol import (
    ARMS,
    FrozenArm,
    canonical_json_bytes,
    f64,
    protocol_hash,
    runtime_id,
)
from research_decision_engine.benchmarks.broader_worlds import (
    BUDGETS,
    CANDIDATE_CATALOG,
    CANDIDATES_BY_ID,
    GROUP_IDS,
    WORLDS_BY_ID,
    CandidateDefinition,
    PublicFeasibilityState,
    PublicWorldDefinition,
    candidate_costs,
    evidence_eligibility_contract,
    validate_worlds,
)
from research_decision_engine.closed_loop import (
    CandidateGroupPredictionAdapter,
    build_candidate_group_prediction_adapter,
    decide_information_gain_with_adapter,
    decide_lookahead_with_adapter,
)
from research_decision_engine.decision import (
    INFORMATION_GAIN_POLICY_VERSION,
    DecisionTrace,
    InformationGainPolicy,
)
from research_decision_engine.lookahead import (
    LOOKAHEAD_INFORMATION_GAIN_POLICY_VERSION,
    LookaheadInformationGainPolicy,
    LookaheadPlanTrace,
)
from research_decision_engine.optimizer_effect import (
    evidence_from_matched_pair,
    optimizer_effect_hypotheses,
)
from research_decision_engine.reasoning import BeliefState, Evidence, ReasoningError
from research_decision_engine.types import Candidate, CompletedExperiment

type TerminalReason = Literal["candidate_space_exhausted", "budget_exhausted", "integrity_abort"]
type PolicyTrace = DecisionTrace | LookaheadPlanTrace

__all__ = ["RunProvenanceError", "select_calibration_history"]

RUNNER_VERSION: Final = "broader-isolated-arm-runner/v1"
CREATED_AT: Final = "2000-01-01T00:00:00.000000Z"
CALIBRATION_SIGMA_PROVENANCE_VERSION: Final = "broader-calibration-sigma-estimate/v1"


@dataclass(frozen=True, slots=True)
class CalibrationGroupEstimate:
    sigma_estimate_id: str
    calibration_prefix_id: str
    comparison_group_id: str
    source_effect_ids: tuple[str, ...]
    source_sequence_cutoff: int
    sample_count: int
    sample_mean: float
    raw_sample_standard_deviation: float
    ddof: int
    sigma_floor: float
    estimated_sigma: float
    belief_model_id: str
    lineage_id: str
    provenance_sha256: str
    effects: tuple[MatchedEffectObservation, ...]
    observations: tuple[RevealedObservation, ...]
    physical_cost: float


@dataclass(frozen=True, slots=True)
class CalibrationDeployment:
    estimates: tuple[CalibrationGroupEstimate, ...]
    effects: tuple[MatchedEffectObservation, ...]
    observations: tuple[RevealedObservation, ...]
    cost: float


@dataclass(frozen=True, slots=True)
class CalibrationSourceReconstruction:
    """Oracle-derived, canonical sources for one frozen five-effect prefix."""

    sigma_estimate_id: str
    calibration_prefix_id: str
    world_id: str
    seed: int
    comparison_group_id: str
    effect_ids: tuple[str, ...]
    replication_ids: tuple[str, ...]
    source_candidate_pairs: tuple[tuple[str, str], ...]
    source_oracle_key_ids: tuple[str, ...]
    effect_values: tuple[float, ...]
    sample_count: int
    sample_mean: float
    sample_standard_deviation: float
    sigma_floor: float
    estimated_sigma: float
    physical_cost: float
    effects: tuple[MatchedEffectObservation, ...]
    observations: tuple[RevealedObservation, ...]
    selection: CalibrationHistorySelection

    def scientific_identity(self) -> tuple[object, ...]:
        """Return the run-independent prefix identity shared by all six deployments."""

        return (
            self.sigma_estimate_id,
            self.calibration_prefix_id,
            self.world_id,
            self.seed,
            self.comparison_group_id,
            self.effect_ids,
            self.replication_ids,
            self.source_candidate_pairs,
            self.source_oracle_key_ids,
            self.effect_values,
            self.sample_count,
            self.sample_mean,
            self.sample_standard_deviation,
            self.sigma_floor,
            self.estimated_sigma,
            self.physical_cost,
            self.effects,
            self.selection.scientific_identity(),
        )


@dataclass(frozen=True, slots=True)
class CalibrationDeploymentBinding:
    """Frozen run/lineage relation used to derive the full deployment vector."""

    run_id: str
    lineage_id: str
    world_id: str
    seed: int
    budget_id: str
    arm_id: str
    belief_model_id: str
    calibration_prefix_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReconstructedCalibrationClaim:
    """Complete Artifact 5 claim plus its nonpersisted frozen semantics.

    Route A reconstruction contract for the eight removed row fields:
    ``source_effect_ids`` -> ordered ``effect_ids``; ``source_sequence_cutoff`` -> canonical
    run/event chronology; ``raw_sample_standard_deviation`` ->
    ``sample_standard_deviation``; ``ddof`` -> frozen estimator rule (1). The concrete
    estimator is proved from its five-effect algorithm and bound through protected-source and
    implementation-tree provenance; there is no frozen estimator-version registry row.
    ``belief_model_id`` -> ``target_belief_model_id``; ``lineage_id`` -> the complete
    ``deployed_lineage_ids`` from arm-run relations; ``provenance_sha256`` -> the common
    envelope, authorization, artifact graph, manifest, run-record, and lineage relations
    (never an Artifact 5 row field).
    """

    sources: CalibrationSourceReconstruction
    deployed_run_ids: tuple[str, ...]
    deployed_lineage_ids: tuple[str, ...]
    sources_by_run: tuple[tuple[str, CalibrationSourceReconstruction], ...]

    @property
    def source_sequence_cutoff(self) -> int:
        # Frozen chronology makes calibration effects available at sequence zero and the
        # first decision/event boundary one; this semantic is reconstructed, never persisted.
        return CALIBRATION_SOURCE_SEQUENCE_CUTOFF

    @property
    def ddof(self) -> int:
        return CALIBRATION_SIGMA_DDOF

    @property
    def target_belief_model_id(self) -> str:
        return CALIBRATED_SIGMA_MODEL_ID

    def artifact_row(self) -> dict[str, object]:
        """Project exactly the frozen 23 fields in their declaration order."""

        source = self.sources
        return {
            "sigma_estimate_id": source.sigma_estimate_id,
            "calibration_prefix_id": source.calibration_prefix_id,
            "world_id": source.world_id,
            "seed": source.seed,
            "comparison_group_id": source.comparison_group_id,
            "effect_ids": list(source.effect_ids),
            "replication_ids": list(source.replication_ids),
            "source_candidate_pairs": [list(item) for item in source.source_candidate_pairs],
            "source_oracle_key_ids": list(source.source_oracle_key_ids),
            "effect_values": [f64(item) for item in source.effect_values],
            "sample_count": source.sample_count,
            "sample_mean": f64(source.sample_mean),
            "sample_standard_deviation": f64(source.sample_standard_deviation),
            "sigma_floor": f64(source.sigma_floor),
            "estimated_sigma": f64(source.estimated_sigma),
            "target_belief_model_id": self.target_belief_model_id,
            "target_comparison_group_id": source.comparison_group_id,
            "target_intervention_arms": ["adam", "sgd"],
            "physical_cost": f64(source.physical_cost),
            "deployment_cost": f64(source.physical_cost),
            "deployed_run_ids": list(self.deployed_run_ids),
            "deployed_lineage_ids": list(self.deployed_lineage_ids),
            "scientific_belief_updated": False,
        }


@dataclass(frozen=True, slots=True)
class ArmDecision:
    decision_id: str
    step: int
    selected_candidate_id: str
    remaining_budget: float
    belief_state_id: str
    public_feasible_candidate_ids: tuple[str, ...]
    affordable_candidate_ids: tuple[str, ...]
    policy_trace: PolicyTrace
    fixed_policy_regression_match: bool


@dataclass(frozen=True, slots=True)
class ArmAction:
    step: int
    candidate_id: str
    role: str
    cost: float
    cumulative_decision_cost: float
    decision_id: str
    observed_objective: float | None
    oracle_observation: RevealedObservation | None
    new_evidence_ids: tuple[str, ...]
    posterior_probabilities: tuple[tuple[str, float], ...]


@dataclass(frozen=True, slots=True)
class BroaderArmRun:
    run_id: str
    comparison_id: str
    arm: FrozenArm
    world_id: str
    seed: int
    budget_id: str
    budget: float
    lineage: BeliefModelLineage
    initial_probabilities: tuple[tuple[str, float], ...]
    decisions: tuple[ArmDecision, ...]
    actions: tuple[ArmAction, ...]
    completed_experiments: tuple[CompletedExperiment, ...]
    evidence: tuple[Evidence, ...]
    updates: tuple[ModelBeliefUpdate, ...]
    diagnostics: tuple[ModelAdequacyDiagnostic, ...]
    effect_history: tuple[MatchedEffectObservation, ...]
    calibration: CalibrationDeployment | None
    decision_cost: float
    calibration_cost: float
    terminal_reason: TerminalReason
    run_status: Literal["complete", "invalid"]

    @property
    def selected_candidate_ids(self) -> tuple[str, ...]:
        return tuple(item.candidate_id for item in self.actions)

    @property
    def final_probabilities(self) -> tuple[tuple[str, float], ...]:
        return tuple(sorted(self.lineage.current_state.state.posterior_map().items()))


@dataclass(frozen=True, slots=True)
class ArmMetrics:
    true_probability: float
    top_scientific_hypothesis_id: str
    top_probability: float
    prediction_correct: bool
    confidently_wrong: bool
    nll: float
    brier: float
    posterior_entropy: float
    conditional_brier_efficiency: float | None
    end_to_end_brier_efficiency: float | None
    decision_cost: float
    calibration_cost: float
    required_total_cost: float
    physical_cost_share: float
    best_observed_objective: float | None
    matched_pairs: int
    redundant_selected: int
    irrelevant_selected: int
    outcome_experiments_completed: int
    setup_actions_completed: int
    budget_exhausted: bool
    terminal_reason: TerminalReason


def arm_spec(arm_id: str) -> FrozenArm:
    for arm in ARMS:
        if arm.arm_id == arm_id:
            return arm
    raise ValueError(f"Unknown broader-replication arm: {arm_id}")


def run_identity(*, arm_id: str, world_id: str, seed: int, budget: float) -> str:
    return runtime_id(
        "run",
        "run_id/v1",
        {"arm_id": arm_id, "budget": f64(budget), "seed": seed, "world_id": world_id},
    )


def comparison_identity(*, policy_id: str, world_id: str, seed: int, budget: float) -> str:
    return runtime_id(
        "comparison",
        "comparison_id/v1",
        {
            "budget": f64(budget),
            "policy_id": policy_id,
            "seed": seed,
            "world_id": world_id,
        },
    )


def initial_lineage_for(*, arm: FrozenArm, run_id: str) -> BeliefModelLineage:
    """Construct the sole valid untouched lineage that may be supplied to a run."""

    model = belief_model(arm.belief_model_id)
    return _initial_lineage(model.model_id, model.model_version, run_id)


def run_arm(
    *,
    arm: FrozenArm,
    world: PublicWorldDefinition,
    seed: int,
    budget_id: str,
    budget: float,
    authority: ObservationAuthority | None = None,
    decision_authority: ObservationAuthority | None = None,
    calibration_authority: ObservationAuthority | None = None,
    initial_lineage: BeliefModelLineage | None = None,
    candidate_catalog: Sequence[CandidateDefinition] | None = None,
    cost_table: Mapping[str, float] | None = None,
) -> BroaderArmRun:
    """Execute one arm using only its own public state, history, and lineage."""

    resolved_decision_authority, resolved_calibration_authority = _resolve_authorities(
        authority=authority,
        decision_authority=decision_authority,
        calibration_authority=calibration_authority,
    )
    run_id = run_identity(arm_id=arm.arm_id, world_id=world.world_id, seed=seed, budget=budget)
    _validate_run_preflight(
        arm=arm,
        world=world,
        seed=seed,
        budget_id=budget_id,
        budget=budget,
        decision_authority=resolved_decision_authority,
        calibration_authority=resolved_calibration_authority,
        run_id=run_id,
        initial_lineage=initial_lineage,
        candidate_catalog=candidate_catalog,
        cost_table=cost_table,
    )
    comparison_id = comparison_identity(
        policy_id=arm.policy_id,
        world_id=world.world_id,
        seed=seed,
        budget=budget,
    )
    model = belief_model(arm.belief_model_id)
    lineage = initial_lineage or initial_lineage_for(arm=arm, run_id=run_id)
    validate_lineage_binding(lineage=lineage, arm=arm, run_id=run_id)
    initial_probabilities = tuple(sorted(lineage.current_state.state.posterior_map().items()))
    calibration = (
        build_calibration_deployment(
            run_id=run_id,
            lineage_id=lineage.lineage_id,
            world=world,
            seed=seed,
            authority=resolved_calibration_authority,
        )
        if arm.belief_model_id == CALIBRATED_SIGMA_MODEL_ID
        else None
    )
    if arm.belief_model_id == FIXED_SIGMA_MODEL_ID and calibration is not None:
        raise ReasoningError("Fixed arms cannot receive calibration effects.")
    effect_history = list(calibration.effects if calibration else ())
    calibration_cost = calibration.cost if calibration else 0.0
    costs = dict(cost_table) if cost_table is not None else candidate_costs(world)
    eligibility = evidence_eligibility_contract()
    public_state = PublicFeasibilityState(world)
    completed: list[CompletedExperiment] = []
    decisions: list[ArmDecision] = []
    actions: list[ArmAction] = []
    evidence_items: list[Evidence] = []
    updates: list[ModelBeliefUpdate] = []
    diagnostics: list[ModelAdequacyDiagnostic] = []
    applied_pairs: set[tuple[int, ...]] = set()
    decision_cost = 0.0
    terminal_reason: TerminalReason

    while True:
        unexecuted_public = public_state.publicly_feasible_candidate_ids()
        remaining = budget - decision_cost
        affordable = tuple(
            candidate_id for candidate_id in unexecuted_public if costs[candidate_id] <= remaining
        )
        if not affordable:
            terminal_reason = terminal_reason_for(
                unexecuted_public,
                affordable,
                integrity_failure=False,
            )
            break
        adapter = build_candidate_group_prediction_adapter(
            model=model,
            lineage=lineage,
            effect_history=tuple(effect_history),
            evidence_eligibility=eligibility,
        )
        step = len(actions) + 1
        decision_id = f"decision/{run_id}/{step:04d}"
        candidates = tuple(CANDIDATES_BY_ID[item].candidate for item in affordable)
        trace = _decide(
            arm=arm,
            adapter=adapter,
            lineage=lineage,
            candidates=candidates,
            completed=tuple(completed),
            costs=costs,
            remaining_budget=remaining,
            decision_id=decision_id,
        )
        selected = trace.candidate
        if selected.candidate_id not in affordable:
            raise ReasoningError("Policy selected a candidate outside public affordability.")
        fixed_match = _fixed_policy_match(
            arm=arm,
            adapter=adapter,
            lineage=lineage,
            candidates=candidates,
            completed=tuple(completed),
            costs=costs,
            remaining_budget=remaining,
            decision_id=decision_id,
            adapted=trace,
        )
        decisions.append(
            ArmDecision(
                decision_id=decision_id,
                step=step,
                selected_candidate_id=selected.candidate_id,
                remaining_budget=remaining,
                belief_state_id=lineage.current_state.state.belief_state_id,
                public_feasible_candidate_ids=unexecuted_public,
                affordable_candidate_ids=affordable,
                policy_trace=trace,
                fixed_policy_regression_match=fixed_match,
            )
        )
        definition = CANDIDATES_BY_ID[selected.candidate_id]
        cost = costs[selected.candidate_id]
        decision_cost += cost
        public_state = public_state.complete(selected.candidate_id)
        observation: RevealedObservation | None = None
        observed: float | None = None
        new_evidence: list[str] = []
        if definition.role != "setup":
            authorization = authorize_observation(
                run_id=run_id,
                source_id=decision_id,
                candidate_id=selected.candidate_id,
                kind="decision",
            )
            observation = resolved_decision_authority.selected_only_interface().observe_selected(
                authorization
            )
            _validate_revealed_observation(
                observation,
                run_id=run_id,
                source_id=decision_id,
                world_id=world.world_id,
                seed=seed,
                candidate_id=selected.candidate_id,
                namespace=DECISION_NAMESPACE,
            )
            observed = observation.revealed_observation
            completed_item = CompletedExperiment(
                record_id=_experiment_record_id(run_id, step),
                candidate=selected,
                observed_value=observed,
                created_at=f"{CREATED_AT}#experiment:{step:04d}",
            )
            completed.append(completed_item)
            for pair in eligibility.valid_unapplied_pairs(
                completed,
                applied_source_pairs=frozenset(applied_pairs),
            ):
                evidence = evidence_from_matched_pair(pair, eligibility)
                lineage, update, current_effect = model.update(
                    lineage=lineage,
                    evidence=evidence,
                    effect_history=tuple(effect_history),
                    diagnostic_history=tuple(diagnostics),
                )
                validate_lineage_binding(lineage=lineage, arm=arm, run_id=run_id)
                evidence_items.append(evidence)
                updates.append(update)
                diagnostics.append(update.diagnostic)
                effect_history.append(current_effect)
                applied_pairs.add(pair.source_experiment_ids)
                new_evidence.append(evidence.evidence_id)
        posterior = tuple(sorted(lineage.current_state.state.posterior_map().items()))
        actions.append(
            ArmAction(
                step=step,
                candidate_id=selected.candidate_id,
                role=definition.role,
                cost=cost,
                cumulative_decision_cost=decision_cost,
                decision_id=decision_id,
                observed_objective=observed,
                oracle_observation=observation,
                new_evidence_ids=tuple(new_evidence),
                posterior_probabilities=posterior,
            )
        )
        if decision_cost > budget:
            raise ReasoningError("A real action exceeded the hard decision budget.")

    return BroaderArmRun(
        run_id=run_id,
        comparison_id=comparison_id,
        arm=arm,
        world_id=world.world_id,
        seed=seed,
        budget_id=budget_id,
        budget=budget,
        lineage=lineage,
        initial_probabilities=initial_probabilities,
        decisions=tuple(decisions),
        actions=tuple(actions),
        completed_experiments=tuple(completed),
        evidence=tuple(evidence_items),
        updates=tuple(updates),
        diagnostics=tuple(diagnostics),
        effect_history=tuple(effect_history),
        calibration=calibration,
        decision_cost=decision_cost,
        calibration_cost=calibration_cost,
        terminal_reason=terminal_reason,
        run_status="complete",
    )


def reconstruct_calibration_sources(
    *,
    run_id: str,
    world_id: str,
    seed: int,
    comparison_group_id: str,
    recorded_observations: Sequence[RevealedObservation] | None = None,
    recorded_effects: Sequence[MatchedEffectObservation] | None = None,
) -> CalibrationSourceReconstruction:
    """Delegate Oracle reconstruction and history selection to the sole authority."""

    selection = select_calibration_history(
        run_id=run_id,
        world_id=world_id,
        seed=seed,
        comparison_group_id=comparison_group_id,
        recorded_observations=recorded_observations,
        recorded_effects=recorded_effects,
    )
    prefix_id = f"calibration-prefix/{world_id}/{seed}/{comparison_group_id}"
    return CalibrationSourceReconstruction(
        sigma_estimate_id=f"sigma-estimate/{prefix_id}",
        calibration_prefix_id=prefix_id,
        world_id=world_id,
        seed=seed,
        comparison_group_id=comparison_group_id,
        effect_ids=selection.source_effect_ids,
        replication_ids=selection.source_replication_ids,
        source_candidate_pairs=selection.source_candidate_pairs,
        source_oracle_key_ids=selection.source_oracle_key_ids,
        effect_values=selection.effect_values,
        sample_count=selection.sample_count,
        sample_mean=selection.sample_mean,
        sample_standard_deviation=selection.sample_standard_deviation,
        sigma_floor=selection.sigma_floor,
        estimated_sigma=selection.estimated_sigma,
        physical_cost=selection.physical_cost,
        effects=selection.effects,
        observations=selection.observations,
        selection=selection,
    )


def reconstruct_complete_calibration_claim(
    *,
    world_id: str,
    seed: int,
    comparison_group_id: str,
    deployment_bindings: Sequence[CalibrationDeploymentBinding],
    recorded_observations_by_run: Mapping[str, Sequence[RevealedObservation]] | None = None,
) -> ReconstructedCalibrationClaim:
    """Derive one prefix claim and its full six-run deployment from frozen registries."""

    expected_prefixes = tuple(
        f"calibration-prefix/{world_id}/{seed}/{group_id}" for group_id in GROUP_IDS
    )
    expected_arms = tuple(arm for arm in ARMS if arm.belief_model_id == CALIBRATED_SIGMA_MODEL_ID)
    budget_order = {budget_id: index for index, (budget_id, _) in enumerate(BUDGETS)}
    arm_order = {arm.arm_id: arm.arm_order for arm in expected_arms}
    expected_targets = {
        (budget_id, arm.arm_id) for budget_id, _ in BUDGETS for arm in expected_arms
    }
    actual_targets = {(item.budget_id, item.arm_id) for item in deployment_bindings}
    if (
        len(deployment_bindings) != 6
        or len({item.run_id for item in deployment_bindings}) != 6
        or len({item.lineage_id for item in deployment_bindings}) != 6
        or actual_targets != expected_targets
    ):
        raise RunProvenanceError(
            "Calibration deployment is not the complete six-run protocol vector."
        )
    ordered = tuple(
        sorted(
            deployment_bindings,
            key=lambda item: (budget_order[item.budget_id], arm_order[item.arm_id]),
        )
    )
    for binding in ordered:
        if (
            binding.world_id != world_id
            or binding.seed != seed
            or binding.belief_model_id != CALIBRATED_SIGMA_MODEL_ID
            or binding.lineage_id != f"lineage/{binding.run_id}"
            or binding.calibration_prefix_ids != expected_prefixes
        ):
            raise RunProvenanceError("Calibration deployment binding differs from the protocol.")
    if recorded_observations_by_run is not None and set(recorded_observations_by_run) != {
        item.run_id for item in ordered
    }:
        raise RunProvenanceError("Recorded calibration observations do not cover every deployment.")

    reconstructed: list[tuple[str, CalibrationSourceReconstruction]] = []
    for binding in ordered:
        sources = reconstruct_calibration_sources(
            run_id=binding.run_id,
            world_id=world_id,
            seed=seed,
            comparison_group_id=comparison_group_id,
            recorded_observations=(
                recorded_observations_by_run[binding.run_id]
                if recorded_observations_by_run is not None
                else None
            ),
        )
        reconstructed.append((binding.run_id, sources))
    identities = {item.scientific_identity() for _, item in reconstructed}
    if len(identities) != 1:
        raise RunProvenanceError(
            "Calibration prefix sources differ across the shared deployment vector."
        )
    # Every run-independent source field was compared across all six canonical targets above;
    # selecting the first protocol-ordered reconstruction here does not assign ownership.
    sources = reconstructed[0][1]
    return ReconstructedCalibrationClaim(
        sources=sources,
        deployed_run_ids=tuple(item.run_id for item in ordered),
        deployed_lineage_ids=tuple(item.lineage_id for item in ordered),
        sources_by_run=tuple(reconstructed),
    )


def calibration_sigma_provenance_sha256(
    *,
    sigma_estimate_id: str,
    calibration_prefix_id: str,
    comparison_group_id: str,
    source_effect_ids: tuple[str, ...],
    source_sequence_cutoff: int,
    sample_count: int,
    sample_mean: float,
    raw_sample_standard_deviation: float,
    ddof: int,
    sigma_floor: float,
    estimated_sigma: float,
    belief_model_id: str,
    lineage_id: str,
    effects: tuple[MatchedEffectObservation, ...],
) -> str:
    """Hash the complete ordered estimate and source-effect provenance."""

    source_effect_payload_sha256 = [
        hashlib.sha256(canonical_json_bytes(item.to_dict(), final_lf=True)).hexdigest()
        for item in effects
    ]
    return protocol_hash(
        CALIBRATION_SIGMA_PROVENANCE_VERSION,
        {
            "sigma_estimate_id": sigma_estimate_id,
            "calibration_prefix_id": calibration_prefix_id,
            "comparison_group_id": comparison_group_id,
            "source_effect_ids": list(source_effect_ids),
            "source_effect_payload_sha256": source_effect_payload_sha256,
            "source_sequence_cutoff": source_sequence_cutoff,
            "sample_count": sample_count,
            "sample_mean": f64(sample_mean),
            "raw_sample_standard_deviation": f64(raw_sample_standard_deviation),
            "ddof": ddof,
            "sigma_floor": f64(sigma_floor),
            "estimated_sigma": f64(estimated_sigma),
            "belief_model_id": belief_model_id,
            "lineage_id": lineage_id,
        },
    )


def build_calibration_deployment(
    *,
    run_id: str,
    lineage_id: str,
    world: PublicWorldDefinition,
    seed: int,
    authority: ObservationAuthority,
) -> CalibrationDeployment:
    """Create three isolated five-effect prefixes without updating scientific beliefs."""

    estimates: list[CalibrationGroupEstimate] = []
    all_effects: list[MatchedEffectObservation] = []
    all_observations: list[RevealedObservation] = []
    for group_index, group_id in enumerate(GROUP_IDS):
        prefix_id = f"calibration-prefix/{world.world_id}/{seed}/{group_id}"
        effects: list[MatchedEffectObservation] = []
        observations: list[RevealedObservation] = []
        for replication_index in range(1, 6):
            arm_observations: dict[str, RevealedObservation] = {}
            for arm_name in ("adam", "sgd"):
                candidate_id = f"cal-{group_index:02d}-{arm_name}-r{replication_index:04d}"
                source_id = f"{prefix_id}/{candidate_id}"
                authorization = authorize_observation(
                    run_id=run_id,
                    source_id=source_id,
                    candidate_id=candidate_id,
                    kind="calibration",
                )
                arm_observations[arm_name] = authority.selected_only_interface().observe_selected(
                    authorization
                )
                _validate_revealed_observation(
                    arm_observations[arm_name],
                    run_id=run_id,
                    source_id=source_id,
                    world_id=world.world_id,
                    seed=seed,
                    candidate_id=candidate_id,
                    namespace=CALIBRATION_NAMESPACE,
                )
                observations.append(arm_observations[arm_name])
            effect = expected_calibration_effect(
                prefix_id=prefix_id,
                world_id=world.world_id,
                comparison_group_id=group_id,
                group_index=group_index,
                replication_index=replication_index,
                observed_effect=round(
                    arm_observations["adam"].revealed_observation
                    - arm_observations["sgd"].revealed_observation,
                    12,
                ),
            )
            effects.append(effect)
        reconstructed = reconstruct_calibration_sources(
            run_id=run_id,
            world_id=world.world_id,
            seed=seed,
            comparison_group_id=group_id,
            recorded_observations=observations,
        )
        if tuple(effects) != reconstructed.effects:
            raise RunProvenanceError(
                "Generated calibration effects differ from independent Oracle reconstruction."
            )
        sample_mean = reconstructed.sample_mean
        sample_sd = reconstructed.sample_standard_deviation
        physical_cost = reconstructed.physical_cost
        source_effect_ids = reconstructed.effect_ids
        sigma_estimate_id = reconstructed.sigma_estimate_id
        provenance_sha256 = calibration_sigma_provenance_sha256(
            sigma_estimate_id=sigma_estimate_id,
            calibration_prefix_id=prefix_id,
            comparison_group_id=group_id,
            source_effect_ids=source_effect_ids,
            source_sequence_cutoff=CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
            sample_count=len(effects),
            sample_mean=sample_mean,
            raw_sample_standard_deviation=sample_sd,
            ddof=CALIBRATION_SIGMA_DDOF,
            sigma_floor=SIGMA_FLOOR,
            estimated_sigma=max(sample_sd, SIGMA_FLOOR),
            belief_model_id=CALIBRATED_SIGMA_MODEL_ID,
            lineage_id=lineage_id,
            effects=reconstructed.effects,
        )
        estimate = CalibrationGroupEstimate(
            sigma_estimate_id=sigma_estimate_id,
            calibration_prefix_id=prefix_id,
            comparison_group_id=group_id,
            source_effect_ids=source_effect_ids,
            source_sequence_cutoff=CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
            sample_count=reconstructed.sample_count,
            sample_mean=sample_mean,
            raw_sample_standard_deviation=sample_sd,
            ddof=CALIBRATION_SIGMA_DDOF,
            sigma_floor=SIGMA_FLOOR,
            estimated_sigma=max(sample_sd, SIGMA_FLOOR),
            belief_model_id=CALIBRATED_SIGMA_MODEL_ID,
            lineage_id=lineage_id,
            provenance_sha256=provenance_sha256,
            effects=reconstructed.effects,
            observations=tuple(observations),
            physical_cost=physical_cost,
        )
        estimates.append(estimate)
        all_effects.extend(reconstructed.effects)
        all_observations.extend(observations)
    return CalibrationDeployment(
        estimates=tuple(estimates),
        effects=tuple(all_effects),
        observations=tuple(all_observations),
        cost=math.fsum(item.physical_cost for item in estimates),
    )


def evaluate_arm(run: BroaderArmRun, true_hypothesis_id: str) -> ArmMetrics:
    validate_recorded_calibration(run)
    posterior = dict(run.final_probabilities)
    true_probability = posterior[true_hypothesis_id]
    top_id, top_probability = min(posterior.items(), key=lambda item: (-item[1], item[0]))
    brier = math.fsum(
        (probability - float(hypothesis_id == true_hypothesis_id)) ** 2
        for hypothesis_id, probability in posterior.items()
    )
    entropy = -math.fsum(
        probability * math.log2(probability)
        for probability in posterior.values()
        if probability > 0.0
    )
    required_cost = run.decision_cost + run.calibration_cost
    objectives = tuple(
        action.observed_objective for action in run.actions if action.observed_objective is not None
    )
    return ArmMetrics(
        true_probability=true_probability,
        top_scientific_hypothesis_id=top_id,
        top_probability=top_probability,
        prediction_correct=top_id == true_hypothesis_id,
        confidently_wrong=top_probability >= 0.80 and top_id != true_hypothesis_id,
        nll=-math.log(max(true_probability, 1e-15)),
        brier=brier,
        posterior_entropy=entropy,
        conditional_brier_efficiency=(
            ((2.0 / 3.0) - brier) / run.decision_cost if run.decision_cost > 0.0 else None
        ),
        end_to_end_brier_efficiency=(
            ((2.0 / 3.0) - brier) / required_cost if required_cost > 0.0 else None
        ),
        decision_cost=run.decision_cost,
        calibration_cost=run.calibration_cost,
        required_total_cost=required_cost,
        physical_cost_share=(
            run.decision_cost + run.calibration_cost / 6.0
            if run.arm.belief_model_id == CALIBRATED_SIGMA_MODEL_ID
            else run.decision_cost
        ),
        best_observed_objective=max(objectives) if objectives else None,
        matched_pairs=len(run.evidence),
        redundant_selected=sum(
            item.candidate_id == "redundant-objective-r1" for item in run.actions
        ),
        irrelevant_selected=sum(
            item.candidate_id == "irrelevant-objective-r1" for item in run.actions
        ),
        outcome_experiments_completed=sum(item.role != "setup" for item in run.actions),
        setup_actions_completed=sum(item.role == "setup" for item in run.actions),
        budget_exhausted=run.terminal_reason == "budget_exhausted",
        terminal_reason=run.terminal_reason,
    )


def terminal_reason_for(
    unexecuted_public: tuple[str, ...],
    affordable: tuple[str, ...],
    *,
    integrity_failure: bool,
) -> TerminalReason:
    if integrity_failure:
        return "integrity_abort"
    if affordable:
        raise ValueError("A terminal reason cannot be assigned while an action is affordable.")
    return "candidate_space_exhausted" if not unexecuted_public else "budget_exhausted"


def validate_lineage_binding(*, lineage: BeliefModelLineage, arm: FrozenArm, run_id: str) -> None:
    """Fail loudly when a scientific belief lineage crosses an arm boundary."""

    if lineage.lineage_id != f"lineage/{run_id}" or lineage.lineage_key != run_id:
        raise RunProvenanceError("Belief lineage identity does not belong to the run.")
    if lineage.belief_model_id != arm.belief_model_id:
        raise RunProvenanceError("Belief lineage model does not match the frozen arm.")
    if lineage.current_state.lineage_id != lineage.lineage_id:
        raise RunProvenanceError("Current belief state belongs to a different lineage.")
    if lineage.current_state.belief_model_id != arm.belief_model_id:
        raise RunProvenanceError("Current belief state model does not match the frozen arm.")


def _validate_recorded_calibration(
    run: BroaderArmRun,
) -> tuple[tuple[MatchedEffectObservation, ...], tuple[CalibrationHistorySelection, ...]]:
    """Re-observe once and return canonical effects plus their selector results."""

    if run.arm.belief_model_id == FIXED_SIGMA_MODEL_ID:
        if run.calibration is not None or run.calibration_cost != 0.0:
            raise RunProvenanceError("Fixed arm consumed a calibration deployment.")
        if any(item.source_kind == "calibration" for item in run.effect_history):
            raise RunProvenanceError("Fixed arm effect history contains calibration data.")
        return (), ()
    if run.arm.belief_model_id != CALIBRATED_SIGMA_MODEL_ID:
        raise RunProvenanceError("Run uses an unknown frozen belief model.")
    calibration = run.calibration
    if calibration is None or len(calibration.estimates) != len(GROUP_IDS):
        raise RunProvenanceError("Calibrated arm lacks the three frozen group estimates.")
    if tuple(item.comparison_group_id for item in calibration.estimates) != GROUP_IDS:
        raise RunProvenanceError("Calibration estimates differ from frozen group order.")

    expected_effects: list[MatchedEffectObservation] = []
    expected_observations: list[RevealedObservation] = []
    selections: list[CalibrationHistorySelection] = []
    reconstructed_sources: list[CalibrationSourceReconstruction] = []
    for group_index, estimate in enumerate(calibration.estimates):
        group_id = GROUP_IDS[group_index]
        expected_prefix = f"calibration-prefix/{run.world_id}/{run.seed}/{group_id}"
        if (
            estimate.calibration_prefix_id != expected_prefix
            or estimate.sigma_estimate_id != f"sigma-estimate/{expected_prefix}"
            or len(estimate.effects) != 5
            or len(estimate.observations) != 10
        ):
            raise RunProvenanceError("Calibration identity or replication cardinality differs.")
        sources = reconstruct_calibration_sources(
            run_id=run.run_id,
            world_id=run.world_id,
            seed=run.seed,
            comparison_group_id=group_id,
            recorded_observations=estimate.observations,
            recorded_effects=run.effect_history,
        )
        reconstructed_sources.append(sources)
        selections.append(sources.selection)
        expected_group_effects = sources.effects
        recorded_group_effects = {item.effect_id: item for item in estimate.effects}
        if len(recorded_group_effects) != len(estimate.effects) or recorded_group_effects != {
            item.effect_id: item for item in expected_group_effects
        }:
            raise RunProvenanceError("Calibration source effects or provenance do not reproduce.")
        expected_provenance = calibration_sigma_provenance_sha256(
            sigma_estimate_id=sources.sigma_estimate_id,
            calibration_prefix_id=expected_prefix,
            comparison_group_id=group_id,
            source_effect_ids=sources.effect_ids,
            source_sequence_cutoff=CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
            sample_count=sources.sample_count,
            sample_mean=sources.sample_mean,
            raw_sample_standard_deviation=sources.sample_standard_deviation,
            ddof=CALIBRATION_SIGMA_DDOF,
            sigma_floor=sources.sigma_floor,
            estimated_sigma=sources.estimated_sigma,
            belief_model_id=CALIBRATED_SIGMA_MODEL_ID,
            lineage_id=run.lineage.lineage_id,
            effects=expected_group_effects,
        )
        if (
            estimate.source_effect_ids != sources.effect_ids
            or estimate.source_sequence_cutoff != CALIBRATION_SOURCE_SEQUENCE_CUTOFF
            or estimate.sample_count != sources.sample_count
            or f64(estimate.sample_mean) != f64(sources.sample_mean)
            or f64(estimate.raw_sample_standard_deviation) != f64(sources.sample_standard_deviation)
            or estimate.ddof != CALIBRATION_SIGMA_DDOF
            or f64(estimate.sigma_floor) != f64(sources.sigma_floor)
            or f64(estimate.estimated_sigma) != f64(sources.estimated_sigma)
            or estimate.belief_model_id != CALIBRATED_SIGMA_MODEL_ID
            or estimate.lineage_id != run.lineage.lineage_id
            or estimate.provenance_sha256 != expected_provenance
            or f64(estimate.physical_cost) != f64(sources.physical_cost)
        ):
            raise RunProvenanceError("Complete recorded calibration estimate does not reproduce.")
        expected_effects.extend(expected_group_effects)
        expected_observations.extend(sources.observations)

    expected_effect_tuple = tuple(expected_effects)
    if len(calibration.effects) != len(expected_effect_tuple):
        raise RunProvenanceError("Calibration deployment effect population differs.")
    recorded_effect_ids = tuple(item.effect_id for item in calibration.effects)
    expected_effect_ids = tuple(item.effect_id for item in expected_effect_tuple)
    if len(frozenset(recorded_effect_ids)) != len(recorded_effect_ids) or len(
        frozenset(expected_effect_ids)
    ) != len(expected_effect_ids):
        raise RunProvenanceError("Calibration deployment effect population differs.")
    if recorded_effect_ids != expected_effect_ids:
        raise RunProvenanceError("Calibration deployment effect ordering differs.")
    if any(
        recorded != expected
        for recorded, expected in zip(
            calibration.effects,
            expected_effect_tuple,
            strict=True,
        )
    ):
        raise RunProvenanceError("Calibration deployment effect population differs.")

    expected_observation_tuple = tuple(expected_observations)
    if len(calibration.observations) != len(expected_observation_tuple):
        raise RunProvenanceError("Calibration deployment observation population differs.")
    recorded_observation_ids = tuple(item.oracle_use_id for item in calibration.observations)
    expected_observation_ids = tuple(item.oracle_use_id for item in expected_observation_tuple)
    if len(frozenset(recorded_observation_ids)) != len(recorded_observation_ids) or len(
        frozenset(expected_observation_ids)
    ) != len(expected_observation_ids):
        raise RunProvenanceError("Calibration deployment observation population differs.")
    if recorded_observation_ids != expected_observation_ids:
        raise RunProvenanceError("Calibration deployment observation ordering differs.")
    if any(
        recorded != expected
        for recorded, expected in zip(
            calibration.observations,
            expected_observation_tuple,
            strict=True,
        )
    ):
        raise RunProvenanceError("Calibration deployment observation population differs.")
    expected_cost = math.fsum(item.physical_cost for item in reconstructed_sources)
    if f64(calibration.cost) != f64(expected_cost) or f64(run.calibration_cost) != f64(
        expected_cost
    ):
        raise RunProvenanceError("Calibration deployment cost does not reconcile.")
    return tuple(expected_effects), tuple(selections)


def validate_recorded_calibration(run: BroaderArmRun) -> tuple[MatchedEffectObservation, ...]:
    """Return the exact canonical calibration effects safe for scientific consumers."""

    effects, _ = _validate_recorded_calibration(run)
    return effects


def validated_calibration_history_selections(
    run: BroaderArmRun,
) -> tuple[CalibrationHistorySelection, ...]:
    """Expose the exact immutable selector results used by every run-level consumer."""

    _, selections = _validate_recorded_calibration(run)
    return selections


def _validated_effect_history(run: BroaderArmRun) -> tuple[MatchedEffectObservation, ...]:
    """Build canonical history without assuming any persisted raw prefix."""

    validated_calibration_effects = validate_recorded_calibration(run)
    effect_ids = tuple(item.effect_id for item in run.effect_history)
    if len(set(effect_ids)) != len(effect_ids):
        raise RunProvenanceError(
            "Planner effect history contains a duplicate effect ID.",
            error_code="CALIBRATION_DUPLICATE_EFFECT_ID",
            validation_layer="calibration_history_consumer",
        )
    expected_decision_effects = tuple(
        MatchedEffectObservation.from_decision(
            update.evidence,
            available_sequence=update.sigma_estimate.cutoff_sequence,
        )
        for update in run.updates
    )
    recorded_decisions = {
        item.effect_id: item for item in run.effect_history if item.source_kind == "decision"
    }
    for expected in expected_decision_effects:
        if recorded_decisions.get(expected.effect_id) != expected:
            raise RunProvenanceError(
                "Planner decision-effect history does not reproduce from recorded updates.",
                error_code="DECISION_EFFECT_HISTORY_MISMATCH",
                validation_layer="calibration_history_consumer",
            )
    return (*validated_calibration_effects, *expected_decision_effects)


def validate_recorded_calibrations(runs: Sequence[BroaderArmRun]) -> None:
    """Reject any invalid calibration before a collection can produce scientific output."""

    for run in runs:
        validate_recorded_calibration(run)


def replay_decisions(run: BroaderArmRun) -> tuple[PolicyTrace, ...]:
    """Recompute every recorded decision from only that run's persisted public inputs."""

    replay_effect_history = _validated_effect_history(run)
    model = belief_model(run.arm.belief_model_id)
    costs = candidate_costs(WORLDS_BY_ID[run.world_id].public)
    eligibility = evidence_eligibility_contract()
    public_state = PublicFeasibilityState(WORLDS_BY_ID[run.world_id].public)
    completed_count = 0
    decision_cost = 0.0
    replayed: list[PolicyTrace] = []
    states: dict[str, ModelBeliefState] = {
        run.lineage.current_state.state.belief_state_id: run.lineage.current_state
    }
    for update in run.updates:
        states[update.state_before.state.belief_state_id] = update.state_before
        states[update.posterior_state.state.belief_state_id] = update.posterior_state

    for index, decision in enumerate(run.decisions):
        if index >= len(run.actions):
            raise RunProvenanceError("A recorded decision has no real action.")
        expected_public = public_state.publicly_feasible_candidate_ids()
        remaining = run.budget - decision_cost
        expected_affordable = tuple(
            candidate_id for candidate_id in expected_public if costs[candidate_id] <= remaining
        )
        if (
            decision.public_feasible_candidate_ids != expected_public
            or decision.affordable_candidate_ids != expected_affordable
            or not math.isclose(decision.remaining_budget, remaining, abs_tol=1e-12)
        ):
            raise RunProvenanceError("Recorded public candidate state does not reproduce.")
        try:
            current_state = states[decision.belief_state_id]
        except KeyError as error:
            raise RunProvenanceError("Decision belief state is absent from its lineage.") from error
        lineage = replace(run.lineage, current_state=current_state)
        effect_history = tuple(
            item
            for item in replay_effect_history
            if item.available_sequence <= current_state.state.sequence
        )
        adapter = build_candidate_group_prediction_adapter(
            model=model,
            lineage=lineage,
            effect_history=effect_history,
            evidence_eligibility=eligibility,
        )
        candidates = tuple(CANDIDATES_BY_ID[item].candidate for item in expected_affordable)
        completed = run.completed_experiments[:completed_count]
        trace = _decide(
            arm=run.arm,
            adapter=adapter,
            lineage=lineage,
            candidates=candidates,
            completed=completed,
            costs=costs,
            remaining_budget=remaining,
            decision_id=decision.decision_id,
        )
        if trace.to_dict() != decision.policy_trace.to_dict():
            raise RunProvenanceError("Recorded planner scores, ranking, or trace do not reproduce.")
        if trace.candidate.candidate_id != decision.selected_candidate_id:
            raise RunProvenanceError("Recorded selected candidate does not reproduce.")
        action = run.actions[index]
        if (
            action.decision_id != decision.decision_id
            or action.candidate_id != decision.selected_candidate_id
        ):
            raise RunProvenanceError("Decision/action selection provenance differs.")
        replayed.append(trace)
        public_state = public_state.complete(action.candidate_id)
        decision_cost += action.cost
        if action.role != "setup":
            completed_count += 1
    if len(run.actions) != len(run.decisions):
        raise RunProvenanceError("Decision/action cardinality differs during replay.")
    return tuple(replayed)


def crossed_decision_traces(
    fixed: BroaderArmRun, calibrated: BroaderArmRun, *, zero_based_step: int
) -> dict[str, PolicyTrace]:
    """Recompute FF/CF/FC/CC truth-free score contexts at one common-prefix step."""

    fixed_effect_history = _validated_effect_history(fixed)
    calibrated_effect_history = _validated_effect_history(calibrated)
    if fixed.arm.policy_id != calibrated.arm.policy_id:
        raise RunProvenanceError("Crossed replay requires one common policy.")
    if (
        fixed.selected_candidate_ids[:zero_based_step]
        != calibrated.selected_candidate_ids[:zero_based_step]
    ):
        raise RunProvenanceError("Crossed replay step is not preceded by a common action prefix.")
    fixed_decision = fixed.decisions[zero_based_step]
    calibrated_decision = calibrated.decisions[zero_based_step]
    if (
        fixed_decision.affordable_candidate_ids != calibrated_decision.affordable_candidate_ids
        or not math.isclose(
            fixed_decision.remaining_budget,
            calibrated_decision.remaining_budget,
            abs_tol=1e-12,
        )
    ):
        raise RunProvenanceError("Crossed replay public candidate state differs before divergence.")
    completed_count = sum(action.role != "setup" for action in fixed.actions[:zero_based_step])
    completed = fixed.completed_experiments[:completed_count]
    costs = candidate_costs(WORLDS_BY_ID[fixed.world_id].public)
    candidates = tuple(
        CANDIDATES_BY_ID[item].candidate for item in fixed_decision.affordable_candidate_ids
    )
    eligibility = evidence_eligibility_contract()
    contexts = {
        "FF": (fixed, fixed, fixed_effect_history),
        "CF": (calibrated, fixed, fixed_effect_history),
        "FC": (fixed, calibrated, calibrated_effect_history),
        "CC": (calibrated, calibrated, calibrated_effect_history),
    }
    traces: dict[str, PolicyTrace] = {}
    for context, (belief_source, sigma_source, validated_sigma_effect_history) in contexts.items():
        belief_state = _model_state_for_decision(
            belief_source, belief_source.decisions[zero_based_step].belief_state_id
        )
        sigma_state = _model_state_for_decision(
            sigma_source, sigma_source.decisions[zero_based_step].belief_state_id
        )
        sigma_model = belief_model(sigma_source.arm.belief_model_id)
        lineage_id = f"crossed-lineage/{fixed.comparison_id}/{zero_based_step + 1}/{context}"
        crossed_state = ModelBeliefState(
            belief_model_id=sigma_model.model_id,
            belief_model_version=sigma_model.model_version,
            lineage_id=lineage_id,
            state=belief_state.state,
        )
        crossed_lineage = BeliefModelLineage(
            lineage_id=lineage_id,
            belief_model_id=sigma_model.model_id,
            belief_model_version=sigma_model.model_version,
            lineage_key=lineage_id,
            current_state=crossed_state,
            created_at=CREATED_AT,
        )
        effect_history = tuple(
            item
            for item in validated_sigma_effect_history
            if item.available_sequence <= sigma_state.state.sequence
        )
        adapter = build_candidate_group_prediction_adapter(
            model=sigma_model,
            lineage=crossed_lineage,
            effect_history=effect_history,
            evidence_eligibility=eligibility,
        )
        traces[context] = _decide(
            arm=belief_source.arm,
            adapter=adapter,
            lineage=crossed_lineage,
            candidates=candidates,
            completed=completed,
            costs=costs,
            remaining_budget=fixed_decision.remaining_budget,
            decision_id=f"crossed-decision/{fixed.comparison_id}/{zero_based_step + 1}/{context}",
        )
    return traces


def _model_state_for_decision(run: BroaderArmRun, belief_state_id: str) -> ModelBeliefState:
    states = {run.lineage.current_state.state.belief_state_id: run.lineage.current_state}
    for update in run.updates:
        states[update.state_before.state.belief_state_id] = update.state_before
        states[update.posterior_state.state.belief_state_id] = update.posterior_state
    try:
        return states[belief_state_id]
    except KeyError as error:
        raise RunProvenanceError("Decision belief state is absent from its lineage.") from error


def _validate_run_preflight(
    *,
    arm: FrozenArm,
    world: PublicWorldDefinition,
    seed: int,
    budget_id: str,
    budget: float,
    decision_authority: ObservationAuthority,
    calibration_authority: ObservationAuthority,
    run_id: str,
    initial_lineage: BeliefModelLineage | None,
    candidate_catalog: Sequence[CandidateDefinition] | None,
    cost_table: Mapping[str, float] | None,
) -> None:
    validate_worlds()
    try:
        frozen_arm = arm_spec(arm.arm_id)
    except ValueError as error:
        raise RunProvenanceError(str(error)) from error
    if arm != frozen_arm:
        raise RunProvenanceError("Arm, policy, or belief-model binding differs from the freeze.")
    try:
        frozen_world = WORLDS_BY_ID[world.world_id]
    except KeyError as error:
        raise RunProvenanceError("Run references an unknown frozen world.") from error
    if world != frozen_world.public:
        raise RunProvenanceError("Complete public world parameters differ from the freeze.")
    frozen_budgets = dict(BUDGETS)
    if budget_id not in world.budget_ids or budget_id not in frozen_budgets:
        raise RunProvenanceError("Budget ID is not feasible in the frozen world.")
    if frozen_budgets[budget_id] != budget:
        raise RunProvenanceError("Budget ID and binary64 value disagree.")
    frozen_costs = candidate_costs(world)
    if set(frozen_costs) != set(CANDIDATES_BY_ID):
        raise RunProvenanceError("Candidate cost table does not cover the frozen catalog exactly.")
    if candidate_catalog is not None and tuple(candidate_catalog) != CANDIDATE_CATALOG:
        raise RunProvenanceError("Supplied candidate catalog differs from the frozen catalog.")
    if cost_table is not None and dict(cost_table) != frozen_costs:
        raise RunProvenanceError("Supplied candidate cost table differs from the frozen world.")
    if initial_lineage is not None:
        validate_lineage_binding(lineage=initial_lineage, arm=arm, run_id=run_id)
        state = initial_lineage.current_state.state
        if state.sequence != 0 or state.evidence_ids:
            raise RunProvenanceError("Supplied initial lineage is not an untouched prior.")
    try:
        decision_authority.assert_bound_to(world=frozen_world, seed=seed)
        if calibration_authority is not decision_authority:
            calibration_authority.assert_bound_to(world=frozen_world, seed=seed)
    except OracleError as error:
        raise RunProvenanceError(str(error)) from error


def _resolve_authorities(
    *,
    authority: ObservationAuthority | None,
    decision_authority: ObservationAuthority | None,
    calibration_authority: ObservationAuthority | None,
) -> tuple[ObservationAuthority, ObservationAuthority]:
    if authority is not None and (
        (decision_authority is not None and decision_authority is not authority)
        or (calibration_authority is not None and calibration_authority is not authority)
    ):
        raise RunProvenanceError(
            "Legacy authority cannot disagree with explicit decision or calibration authority."
        )
    decision = decision_authority or authority
    calibration = calibration_authority or authority or decision
    if decision is None or calibration is None:
        raise RunProvenanceError("Decision and calibration observation authorities are required.")
    return decision, calibration


def _validate_revealed_observation(
    observation: RevealedObservation,
    *,
    run_id: str,
    source_id: str,
    world_id: str,
    seed: int,
    candidate_id: str,
    namespace: str,
) -> None:
    kind = "calibration" if namespace == CALIBRATION_NAMESPACE else "decision"
    expected = authorize_observation(
        run_id=run_id,
        source_id=source_id,
        candidate_id=candidate_id,
        kind=kind,
    )
    try:
        reconstructed = reobserve_authorized_observation(
            world_id=world_id,
            seed=seed,
            authorization=expected,
        )
    except OracleError as error:
        raise RunProvenanceError("Frozen Oracle re-observation failed.") from error
    if observation != reconstructed or reconstructed.namespace != namespace:
        raise RunProvenanceError(
            "Revealed observation does not reproduce from its authorization and frozen Oracle."
        )


def _initial_lineage(model_id: str, model_version: str, run_id: str) -> BeliefModelLineage:
    hypotheses = tuple(sorted(optimizer_effect_hypotheses(), key=lambda item: item.hypothesis_id))
    hypothesis_ids = tuple(item.hypothesis_id for item in hypotheses)
    probabilities = tuple(item.prior_probability for item in hypotheses)
    lineage_id = f"lineage/{run_id}"
    belief_state = BeliefState(
        belief_state_id=f"belief-state/{run_id}/0000",
        hypothesis_ids=hypothesis_ids,
        prior_probabilities=probabilities,
        posterior_probabilities=probabilities,
        evidence_ids=(),
        sequence=0,
        created_at=CREATED_AT,
    )
    state = ModelBeliefState(
        belief_model_id=model_id,
        belief_model_version=model_version,
        lineage_id=lineage_id,
        state=belief_state,
    )
    return BeliefModelLineage(
        lineage_id=lineage_id,
        belief_model_id=model_id,
        belief_model_version=model_version,
        lineage_key=run_id,
        current_state=state,
        created_at=CREATED_AT,
    )


def _decide(
    *,
    arm: FrozenArm,
    adapter: CandidateGroupPredictionAdapter,
    lineage: BeliefModelLineage,
    candidates: tuple[Candidate, ...],
    completed: tuple[CompletedExperiment, ...],
    costs: dict[str, float],
    remaining_budget: float,
    decision_id: str,
) -> PolicyTrace:
    created_at = f"{CREATED_AT}#{decision_id}"
    if arm.policy_id == "information_gain":
        return decide_information_gain_with_adapter(
            adapter=adapter,
            lineage=lineage,
            candidates=candidates,
            completed_experiments=completed,
            candidate_costs=costs,
            max_cost=remaining_budget,
            created_at=created_at,
        )
    return decide_lookahead_with_adapter(
        adapter=adapter,
        lineage=lineage,
        candidates=candidates,
        completed_experiments=completed,
        candidate_costs=costs,
        max_cost=remaining_budget,
        created_at=created_at,
    )


def _fixed_policy_match(
    *,
    arm: FrozenArm,
    adapter: CandidateGroupPredictionAdapter,
    lineage: BeliefModelLineage,
    candidates: tuple[Candidate, ...],
    completed: tuple[CompletedExperiment, ...],
    costs: dict[str, float],
    remaining_budget: float,
    decision_id: str,
    adapted: PolicyTrace,
) -> bool:
    if arm.belief_model_id != FIXED_SIGMA_MODEL_ID:
        return True
    created_at = f"{CREATED_AT}#{decision_id}"
    hypotheses = adapter.canonical_snapshot().hypotheses
    if arm.policy_id == "information_gain":
        base: PolicyTrace = InformationGainPolicy().decide(
            candidates=list(candidates),
            completed_experiments=list(completed),
            hypotheses=hypotheses,
            belief_state=lineage.current_state.state,
            cost=lambda candidate: costs[candidate.candidate_id],
            max_cost=remaining_budget,
            created_at=created_at,
            eligibility=adapter.evidence_eligibility,
        )
    else:
        base = LookaheadInformationGainPolicy().decide(
            candidates=list(candidates),
            completed_experiments=list(completed),
            hypotheses=hypotheses,
            belief_state=lineage.current_state.state,
            eligibility=adapter.evidence_eligibility,
            cost=lambda candidate: costs[candidate.candidate_id],
            max_cost=remaining_budget,
            created_at=created_at,
        )
    if adapted.to_dict() != base.to_dict():
        raise ReasoningError("Fixed-model adapter changed the frozen policy behavior.")
    return True


def _experiment_record_id(run_id: str, step: int) -> int:
    digest = hashlib.sha256(run_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:6], "big") * 100 + step


def policy_version(arm: FrozenArm) -> str:
    return (
        INFORMATION_GAIN_POLICY_VERSION
        if arm.policy_id == "information_gain"
        else LOOKAHEAD_INFORMATION_GAIN_POLICY_VERSION
    )
