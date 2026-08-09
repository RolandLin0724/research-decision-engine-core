"""Runner functions connecting policy, world, and storage."""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from research_decision_engine.adapters import WorkloadAdapter, WorkloadAdapterError
from research_decision_engine.decision import (
    INFORMATION_GAIN_POLICY,
    DecisionTrace,
    InformationGainPolicy,
)
from research_decision_engine.evidence_eligibility import (
    OptimizerEvidenceEligibilityContract,
)
from research_decision_engine.generic_policies import PriorGreedyPolicy
from research_decision_engine.information_gain_table import TableInformationGainPolicy
from research_decision_engine.lookahead import (
    LOOKAHEAD_INFORMATION_GAIN_POLICY,
    LookaheadInformationGainPolicy,
    LookaheadPlanTrace,
)
from research_decision_engine.optimizer_effect import synchronize_optimizer_reasoning
from research_decision_engine.policies import _select_random_available, build_policy
from research_decision_engine.policy_contracts import (
    GREEDY_PRIOR_POLICY_ID,
    INFORMATION_GAIN_TABLE_POLICY_ID,
    RANDOM_POLICY_ID,
)
from research_decision_engine.run_bundle import (
    CompletedWorkloadRunTrace,
    RunBundleStep,
    StopReason,
    _run_bundle_step_from_completion,
)
from research_decision_engine.run_spec import (
    CandidateSpec,
    CompletedWorkloadExperiment,
    NormalizedObservation,
    RunSpec,
)
from research_decision_engine.run_spec_v2 import RunSpecV2
from research_decision_engine.run_spec_v3 import RunSpecV3
from research_decision_engine.storage import ExperimentStore
from research_decision_engine.types import Candidate, ExperimentRecord
from research_decision_engine.world import DeterministicSyntheticWorld

if TYPE_CHECKING:
    from research_decision_engine.run_bundle_v2 import (
        CompletedWorkloadRunTraceV2,
        RunBundleStepV2,
    )
    from research_decision_engine.run_bundle_v3 import (
        CompletedWorkloadRunTraceV3,
        RunBundleStepV3,
    )


def suggest_next(
    store: ExperimentStore,
    *,
    policy_name: str,
    seed: int,
    max_cost: float | None = None,
) -> Candidate:
    if policy_name == INFORMATION_GAIN_POLICY:
        return suggest_information_gain(store, max_cost=max_cost).candidate
    if policy_name == LOOKAHEAD_INFORMATION_GAIN_POLICY:
        return suggest_lookahead_information_gain(store, max_cost=max_cost).candidate
    world = DeterministicSyntheticWorld()
    policy = build_policy(policy_name, seed)
    return policy.select(world.candidates(), store.list_records())


def suggest_information_gain(
    store: ExperimentStore, *, max_cost: float | None = None
) -> DecisionTrace:
    """Create and persist one belief-guided suggestion."""

    world = DeterministicSyntheticWorld()
    candidates = world.candidates()
    eligibility = OptimizerEvidenceEligibilityContract.from_candidates(candidates)
    synchronize_optimizer_reasoning(store, eligibility=eligibility)
    belief_state = store.current_belief_state()
    if belief_state is None:
        raise RuntimeError("Optimizer-effect beliefs are not initialized.")
    effective_max_cost = (
        max(world.cost(candidate) for candidate in candidates) if max_cost is None else max_cost
    )
    trace = InformationGainPolicy().decide(
        candidates=candidates,
        completed_experiments=store.list_completed_experiments(),
        hypotheses=tuple(store.list_hypotheses()),
        belief_state=belief_state,
        cost=world.cost,
        max_cost=effective_max_cost,
        created_at=datetime.now(UTC).isoformat(),
        eligibility=eligibility,
    )
    return store.add_decision_trace(trace)


def suggest_lookahead_information_gain(
    store: ExperimentStore, *, max_cost: float | None = None
) -> LookaheadPlanTrace:
    """Create and persist one real first-action two-step plan trace."""

    world = DeterministicSyntheticWorld()
    candidates = world.candidates()
    eligibility = OptimizerEvidenceEligibilityContract.from_candidates(candidates)
    synchronize_optimizer_reasoning(store, eligibility=eligibility)
    belief_state = store.current_belief_state()
    if belief_state is None:
        raise RuntimeError("Optimizer-effect beliefs are not initialized.")
    effective_max_cost = (
        max(world.cost(candidate) for candidate in candidates) if max_cost is None else max_cost
    )
    trace = LookaheadInformationGainPolicy().decide(
        candidates=candidates,
        completed_experiments=store.list_completed_experiments(),
        hypotheses=tuple(store.list_hypotheses()),
        belief_state=belief_state,
        eligibility=eligibility,
        cost=world.cost,
        max_cost=effective_max_cost,
        created_at=datetime.now(UTC).isoformat(),
    )
    return store.add_lookahead_plan_trace(trace)


def run_next(
    store: ExperimentStore,
    *,
    policy_name: str,
    seed: int,
    max_cost: float | None = None,
) -> ExperimentRecord:
    world = DeterministicSyntheticWorld()
    candidate = suggest_next(
        store,
        policy_name=policy_name,
        seed=seed,
        max_cost=max_cost,
    )
    observed_value, true_value, cost = world.evaluate(candidate)
    record = ExperimentRecord.new(
        candidate=candidate,
        policy=policy_name,
        observed_value=observed_value,
        true_value=true_value,
        cost=cost,
    )
    stored_record = store.add_record(record)
    synchronize_optimizer_reasoning(store)
    return stored_record


def run_workload_experiment(
    store: ExperimentStore,
    *,
    run_spec: RunSpec,
    adapter: WorkloadAdapter,
) -> CompletedWorkloadExperiment:
    """Select, evaluate, and persist one truth-free RunSpec candidate.

    Cost is reported by the adapter, so a supplied cost budget is checked both
    before execution and again before persistence. This in-process slice cannot
    reserve unknown cost or undo user-code side effects when an observation would
    exceed the remaining budget.
    """

    if type(run_spec) is not RunSpec:
        raise TypeError("run_spec must be an exact RunSpec.")
    adapter_id = adapter.adapter_id
    adapter_version = adapter.adapter_version
    if (adapter_id, adapter_version) != (run_spec.adapter_id, run_spec.adapter_version):
        raise ValueError("Adapter identity/version does not match the RunSpec.")

    fingerprint = run_spec.fingerprint()
    history = store.list_workload_experiments(fingerprint)
    candidates_by_id = {candidate.candidate_id: candidate for candidate in run_spec.candidates}
    for record in history:
        expected_candidate = candidates_by_id.get(record.candidate.candidate_id)
        if record.policy_id != run_spec.policy_id or record.candidate != expected_candidate:
            raise RuntimeError("Persisted workload history is inconsistent with the RunSpec.")

    if len(history) >= run_spec.experiment_count_budget:
        raise RuntimeError("RunSpec experiment-count budget is exhausted.")
    spent_cost = sum(record.observation.cost for record in history)
    if run_spec.cost_budget is not None and spent_cost >= run_spec.cost_budget:
        raise RuntimeError("RunSpec cost budget is exhausted.")

    completed_candidate_ids = {record.candidate.candidate_id for record in history}
    candidate = _select_random_available(
        run_spec.candidates,
        completed_candidate_ids,
        random.Random(run_spec.policy_seed),
    )
    observation = adapter.evaluate(candidate)
    if type(observation) is not NormalizedObservation:
        raise WorkloadAdapterError("Workload adapters must return an exact NormalizedObservation.")
    if run_spec.cost_budget is not None and spent_cost + observation.cost > run_spec.cost_budget:
        raise RuntimeError("Observation cost would exceed the RunSpec cost budget.")

    record = CompletedWorkloadExperiment(
        run_spec_fingerprint=fingerprint,
        candidate=candidate,
        policy_id=run_spec.policy_id,
        observation=observation,
        created_at=datetime.now(UTC).isoformat(),
    )
    return store.add_workload_experiment(record)


def run_workload_trace(
    store: ExperimentStore,
    *,
    run_spec: RunSpec,
    adapter: WorkloadAdapter,
) -> CompletedWorkloadRunTrace:
    """Execute and capture one exact bounded RunSpec workload trace.

    The trace starts from an empty history for this RunSpec and retains the
    decision, rationale, normalized observation, lineage, and cumulative cost
    at every persisted step. It terminates at the first Core budget boundary.
    """

    if type(run_spec) is not RunSpec:
        raise TypeError("run_spec must be an exact RunSpec.")
    if store.list_workload_experiments(run_spec.fingerprint()):
        raise RuntimeError("Workload trace capture requires an empty RunSpec history.")

    return _continue_workload_trace(
        store,
        run_spec=run_spec,
        adapter=adapter,
        steps=[],
        completed_candidate_ids=[],
        cumulative_cost=0.0,
    )


def resume_workload_trace(
    store: ExperimentStore,
    *,
    run_spec: RunSpec,
    adapter: WorkloadAdapter,
    expected_run_spec_fingerprint: str,
) -> CompletedWorkloadRunTrace:
    """Validate a persisted prefix and complete its exact RunSpec trace.

    Resume is explicitly bound to the caller-retained opening RunSpec fingerprint.
    It rejects an empty or incompatible history and reconstructs every persisted
    prefix step under the current static policy before executing the adapter again.
    """

    if type(run_spec) is not RunSpec:
        raise TypeError("run_spec must be an exact RunSpec.")
    if type(expected_run_spec_fingerprint) is not str:
        raise TypeError("expected_run_spec_fingerprint must be a string.")
    if len(expected_run_spec_fingerprint) != 64 or any(
        character not in "0123456789abcdef" for character in expected_run_spec_fingerprint
    ):
        raise ValueError("expected_run_spec_fingerprint must be a lowercase SHA-256 hex digest.")

    fingerprint = run_spec.fingerprint()
    if fingerprint != expected_run_spec_fingerprint:
        raise ValueError("RunSpec fingerprint does not match the expected resume identity.")
    if (adapter.adapter_id, adapter.adapter_version) != (
        run_spec.adapter_id,
        run_spec.adapter_version,
    ):
        raise ValueError("Adapter identity/version does not match the RunSpec.")

    history = store.list_workload_experiments(expected_run_spec_fingerprint)
    if not history:
        raise RuntimeError("Workload trace resume requires an existing exact RunSpec history.")
    if len(history) > run_spec.experiment_count_budget:
        raise RuntimeError("Persisted workload history exceeds the RunSpec experiment budget.")

    steps: list[RunBundleStep] = []
    completed_candidate_ids: list[str] = []
    cumulative_cost = 0.0
    for record in history:
        step = _run_bundle_step_from_completion(
            run_spec=run_spec,
            record=record,
            completed_candidate_ids=completed_candidate_ids,
            cumulative_cost=cumulative_cost,
        )
        steps.append(step)
        completed_candidate_ids.append(step.selected_candidate_id)
        cumulative_cost = step.cumulative_cost

    return _continue_workload_trace(
        store,
        run_spec=run_spec,
        adapter=adapter,
        steps=steps,
        completed_candidate_ids=completed_candidate_ids,
        cumulative_cost=cumulative_cost,
    )


def _continue_workload_trace(
    store: ExperimentStore,
    *,
    run_spec: RunSpec,
    adapter: WorkloadAdapter,
    steps: list[RunBundleStep],
    completed_candidate_ids: list[str],
    cumulative_cost: float,
) -> CompletedWorkloadRunTrace:
    stop_reason: StopReason
    while True:
        if len(steps) >= run_spec.experiment_count_budget:
            stop_reason = "experiment_budget_exhausted"
            break
        if run_spec.cost_budget is not None and cumulative_cost >= run_spec.cost_budget:
            stop_reason = "cost_budget_exhausted"
            break
        if len(completed_candidate_ids) >= len(run_spec.candidates):
            stop_reason = "candidate_space_exhausted"
            break

        record = run_workload_experiment(store, run_spec=run_spec, adapter=adapter)
        step = _run_bundle_step_from_completion(
            run_spec=run_spec,
            record=record,
            completed_candidate_ids=completed_candidate_ids,
            cumulative_cost=cumulative_cost,
        )
        steps.append(step)
        completed_candidate_ids.append(step.selected_candidate_id)
        cumulative_cost = step.cumulative_cost

    return CompletedWorkloadRunTrace(
        run_spec=run_spec,
        steps=steps,
        stop_reason=stop_reason,
    )


def run_workload_experiment_v2(
    store: ExperimentStore,
    *,
    run_spec: RunSpecV2,
    adapter: WorkloadAdapter,
) -> CompletedWorkloadExperiment:
    """Select, evaluate, and persist one exact RunSpec v2 candidate."""

    if type(run_spec) is not RunSpecV2:
        raise TypeError("run_spec must be an exact RunSpecV2.")
    if (adapter.adapter_id, adapter.adapter_version) != (
        run_spec.adapter_id,
        run_spec.adapter_version,
    ):
        raise ValueError("Adapter identity/version does not match the RunSpec.")

    fingerprint = run_spec.fingerprint()
    history = store.list_workload_experiments(fingerprint)
    candidates_by_id = {candidate.candidate_id: candidate for candidate in run_spec.candidates}
    for record in history:
        expected_candidate = candidates_by_id.get(record.candidate.candidate_id)
        if record.policy_id != run_spec.policy_id or record.candidate != expected_candidate:
            raise RuntimeError("Persisted workload history is inconsistent with the RunSpec.")

    if len(history) >= run_spec.experiment_count_budget:
        raise RuntimeError("RunSpec experiment-count budget is exhausted.")
    spent_cost = sum(record.observation.cost for record in history)
    if run_spec.cost_budget is not None and spent_cost >= run_spec.cost_budget:
        raise RuntimeError("RunSpec cost budget is exhausted.")

    completed_candidate_ids = {record.candidate.candidate_id for record in history}
    if run_spec.policy_id == "random":
        if type(run_spec.policy_seed) is not int:
            raise AssertionError("Validated random RunSpec v2 lacks its seed.")
        candidate = _select_random_available(
            run_spec.candidates,
            completed_candidate_ids,
            random.Random(run_spec.policy_seed),
        )
    elif run_spec.policy_id == "greedy_prior":
        candidate = PriorGreedyPolicy(run_spec).select(completed_candidate_ids)
    else:
        raise AssertionError("Validated RunSpec v2 contains an unsupported policy.")

    observation = adapter.evaluate(candidate)
    if type(observation) is not NormalizedObservation:
        raise WorkloadAdapterError("Workload adapters must return an exact NormalizedObservation.")
    if run_spec.cost_budget is not None and spent_cost + observation.cost > run_spec.cost_budget:
        raise RuntimeError("Observation cost would exceed the RunSpec cost budget.")

    record = CompletedWorkloadExperiment(
        run_spec_fingerprint=fingerprint,
        candidate=candidate,
        policy_id=run_spec.policy_id,
        observation=observation,
        created_at=datetime.now(UTC).isoformat(),
    )
    return store.add_workload_experiment(record)


def run_workload_trace_v2(
    store: ExperimentStore,
    *,
    run_spec: RunSpecV2,
    adapter: WorkloadAdapter,
) -> CompletedWorkloadRunTraceV2:
    """Execute and capture a new exact bounded RunSpec v2 workload trace."""

    if type(run_spec) is not RunSpecV2:
        raise TypeError("run_spec must be an exact RunSpecV2.")
    if store.list_workload_experiments(run_spec.fingerprint()):
        raise RuntimeError("Workload trace capture requires an empty RunSpec history.")
    return _continue_workload_trace_v2(
        store,
        run_spec=run_spec,
        adapter=adapter,
        steps=[],
        completed_candidate_ids=[],
        cumulative_cost=0.0,
    )


def resume_workload_trace_v2(
    store: ExperimentStore,
    *,
    run_spec: RunSpecV2,
    adapter: WorkloadAdapter,
    expected_run_spec_fingerprint: str,
) -> CompletedWorkloadRunTraceV2:
    """Validate a persisted v2 prefix and complete its exact static-policy trace."""

    from research_decision_engine.run_bundle_v2 import (
        _run_bundle_step_v2_from_completion,
    )

    if type(run_spec) is not RunSpecV2:
        raise TypeError("run_spec must be an exact RunSpecV2.")
    if type(expected_run_spec_fingerprint) is not str:
        raise TypeError("expected_run_spec_fingerprint must be a string.")
    if len(expected_run_spec_fingerprint) != 64 or any(
        character not in "0123456789abcdef" for character in expected_run_spec_fingerprint
    ):
        raise ValueError("expected_run_spec_fingerprint must be a lowercase SHA-256 hex digest.")

    fingerprint = run_spec.fingerprint()
    if fingerprint != expected_run_spec_fingerprint:
        raise ValueError("RunSpec fingerprint does not match the expected resume identity.")
    if (adapter.adapter_id, adapter.adapter_version) != (
        run_spec.adapter_id,
        run_spec.adapter_version,
    ):
        raise ValueError("Adapter identity/version does not match the RunSpec.")

    history = store.list_workload_experiments(expected_run_spec_fingerprint)
    if not history:
        raise RuntimeError("Workload trace resume requires an existing exact RunSpec history.")
    if len(history) > run_spec.experiment_count_budget:
        raise RuntimeError("Persisted workload history exceeds the RunSpec experiment budget.")

    steps: list[RunBundleStepV2] = []
    completed_candidate_ids: list[str] = []
    cumulative_cost = 0.0
    for record in history:
        step = _run_bundle_step_v2_from_completion(
            run_spec=run_spec,
            record=record,
            completed_candidate_ids=completed_candidate_ids,
            cumulative_cost=cumulative_cost,
        )
        steps.append(step)
        completed_candidate_ids.append(step.selected_candidate_id)
        cumulative_cost = step.cumulative_cost

    return _continue_workload_trace_v2(
        store,
        run_spec=run_spec,
        adapter=adapter,
        steps=steps,
        completed_candidate_ids=completed_candidate_ids,
        cumulative_cost=cumulative_cost,
    )


def _continue_workload_trace_v2(
    store: ExperimentStore,
    *,
    run_spec: RunSpecV2,
    adapter: WorkloadAdapter,
    steps: list[RunBundleStepV2],
    completed_candidate_ids: list[str],
    cumulative_cost: float,
) -> CompletedWorkloadRunTraceV2:
    from research_decision_engine.run_bundle_v2 import (
        CompletedWorkloadRunTraceV2,
        _run_bundle_step_v2_from_completion,
    )

    stop_reason: StopReason
    while True:
        if len(steps) >= run_spec.experiment_count_budget:
            stop_reason = "experiment_budget_exhausted"
            break
        if run_spec.cost_budget is not None and cumulative_cost >= run_spec.cost_budget:
            stop_reason = "cost_budget_exhausted"
            break
        if len(completed_candidate_ids) >= len(run_spec.candidates):
            stop_reason = "candidate_space_exhausted"
            break

        record = run_workload_experiment_v2(store, run_spec=run_spec, adapter=adapter)
        step = _run_bundle_step_v2_from_completion(
            run_spec=run_spec,
            record=record,
            completed_candidate_ids=completed_candidate_ids,
            cumulative_cost=cumulative_cost,
        )
        steps.append(step)
        completed_candidate_ids.append(step.selected_candidate_id)
        cumulative_cost = step.cumulative_cost

    return CompletedWorkloadRunTraceV2(
        run_spec=run_spec,
        steps=steps,
        stop_reason=stop_reason,
    )


def _select_workload_candidate_v3(
    run_spec: RunSpecV3,
    history: list[CompletedWorkloadExperiment],
) -> CandidateSpec:
    """Apply one finite v3 policy without executing a workload."""

    completed_ids = {record.candidate.candidate_id for record in history}
    if run_spec.policy_id == RANDOM_POLICY_ID:
        if type(run_spec.policy_seed) is not int:
            raise AssertionError("Validated random RunSpec v3 lacks its seed.")
        return _select_random_available(
            run_spec.candidates,
            completed_ids,
            random.Random(run_spec.policy_seed),
        )
    if run_spec.policy_id == GREEDY_PRIOR_POLICY_ID:
        raw_utilities = run_spec.policy_config["utility_by_candidate_id"]
        if type(raw_utilities) is not dict:
            raise AssertionError("Validated greedy_prior v3 lacks its utility map.")
        utilities = cast(dict[str, int | float], raw_utilities)
        selected: CandidateSpec | None = None
        selected_utility: int | float | None = None
        for candidate in run_spec.candidates:
            if candidate.candidate_id in completed_ids:
                continue
            utility = utilities[candidate.candidate_id]
            if selected is None or selected_utility is None or utility > selected_utility:
                selected = candidate
                selected_utility = utility
        if selected is None:
            raise ValueError("No available candidates remain.")
        return CandidateSpec(selected.candidate_id, selected.parameters)
    if run_spec.policy_id == INFORMATION_GAIN_TABLE_POLICY_ID:
        return TableInformationGainPolicy(run_spec).select(history)
    raise AssertionError("Validated RunSpec v3 contains an unsupported policy.")


def run_workload_experiment_v3(
    store: ExperimentStore,
    *,
    run_spec: RunSpecV3,
    adapter: WorkloadAdapter,
) -> CompletedWorkloadExperiment:
    """Select, execute, and persist one exact RunSpec v3 completion."""

    if type(run_spec) is not RunSpecV3:
        raise TypeError("run_spec must be an exact RunSpecV3.")
    if (adapter.adapter_id, adapter.adapter_version) != (
        run_spec.adapter_id,
        run_spec.adapter_version,
    ):
        raise ValueError("Adapter identity/version does not match the RunSpec.")

    fingerprint = run_spec.fingerprint()
    history = store.list_workload_experiments(fingerprint)
    candidates_by_id = {candidate.candidate_id: candidate for candidate in run_spec.candidates}
    for record in history:
        expected_candidate = candidates_by_id.get(record.candidate.candidate_id)
        if (
            record.run_spec_fingerprint != fingerprint
            or record.policy_id != run_spec.policy_id
            or record.candidate != expected_candidate
        ):
            raise RuntimeError("Persisted workload history is inconsistent with the RunSpec.")

    if len(history) >= run_spec.experiment_count_budget:
        raise RuntimeError("RunSpec experiment-count budget is exhausted.")
    spent_cost = sum(record.observation.cost for record in history)
    if run_spec.cost_budget is not None and spent_cost >= run_spec.cost_budget:
        raise RuntimeError("RunSpec cost budget is exhausted.")

    candidate = _select_workload_candidate_v3(run_spec, history)
    observation = adapter.evaluate(candidate)
    if type(observation) is not NormalizedObservation:
        raise WorkloadAdapterError("Workload adapters must return an exact NormalizedObservation.")
    if run_spec.cost_budget is not None and spent_cost + observation.cost > run_spec.cost_budget:
        raise RuntimeError("Observation cost would exceed the RunSpec cost budget.")

    record = CompletedWorkloadExperiment(
        run_spec_fingerprint=fingerprint,
        candidate=candidate,
        policy_id=run_spec.policy_id,
        observation=observation,
        created_at=datetime.now(UTC).isoformat(),
    )
    return store.add_workload_experiment(record)


def run_workload_trace_v3(
    store: ExperimentStore,
    *,
    run_spec: RunSpecV3,
    adapter: WorkloadAdapter,
) -> CompletedWorkloadRunTraceV3:
    """Execute and capture a new exact bounded RunSpec v3 trace."""

    if type(run_spec) is not RunSpecV3:
        raise TypeError("run_spec must be an exact RunSpecV3.")
    if store.list_workload_experiments(run_spec.fingerprint()):
        raise RuntimeError("Workload trace capture requires an empty RunSpec history.")
    return _continue_workload_trace_v3(
        store,
        run_spec=run_spec,
        adapter=adapter,
        steps=[],
        completed_history=[],
        cumulative_cost=0.0,
    )


def resume_workload_trace_v3(
    store: ExperimentStore,
    *,
    run_spec: RunSpecV3,
    adapter: WorkloadAdapter,
    expected_run_spec_fingerprint: str,
    expected_evidence_model_fingerprint: str | None = None,
) -> CompletedWorkloadRunTraceV3:
    """Validate an exact persisted v3 prefix before executing remaining work."""

    from research_decision_engine.run_bundle_v3 import _run_bundle_step_v3_from_completion

    if type(run_spec) is not RunSpecV3:
        raise TypeError("run_spec must be an exact RunSpecV3.")
    if type(expected_run_spec_fingerprint) is not str:
        raise TypeError("expected_run_spec_fingerprint must be a string.")
    if len(expected_run_spec_fingerprint) != 64 or any(
        character not in "0123456789abcdef" for character in expected_run_spec_fingerprint
    ):
        raise ValueError("expected_run_spec_fingerprint must be a lowercase SHA-256 hex digest.")
    if run_spec.fingerprint() != expected_run_spec_fingerprint:
        raise ValueError("RunSpec fingerprint does not match the expected resume identity.")

    evidence_model = run_spec.evidence_model
    if run_spec.policy_id == INFORMATION_GAIN_TABLE_POLICY_ID:
        if type(expected_evidence_model_fingerprint) is not str:
            raise TypeError("information_gain_table resume requires an evidence-model fingerprint.")
        if (
            len(expected_evidence_model_fingerprint) != 64
            or any(
                character not in "0123456789abcdef"
                for character in expected_evidence_model_fingerprint
            )
            or evidence_model is None
            or evidence_model.fingerprint() != expected_evidence_model_fingerprint
        ):
            raise ValueError("Evidence-model fingerprint does not match the resume identity.")
    elif expected_evidence_model_fingerprint is not None:
        raise ValueError("Only information_gain_table has an evidence-model resume identity.")

    if (adapter.adapter_id, adapter.adapter_version) != (
        run_spec.adapter_id,
        run_spec.adapter_version,
    ):
        raise ValueError("Adapter identity/version does not match the RunSpec.")

    history = store.list_workload_experiments(expected_run_spec_fingerprint)
    if not history:
        raise RuntimeError("Workload trace resume requires an existing exact RunSpec history.")
    if len(history) > run_spec.experiment_count_budget:
        raise RuntimeError("Persisted workload history exceeds the RunSpec experiment budget.")

    steps: list[RunBundleStepV3] = []
    completed_history: list[CompletedWorkloadExperiment] = []
    cumulative_cost = 0.0
    for record in history:
        step = _run_bundle_step_v3_from_completion(
            run_spec=run_spec,
            record=record,
            completed_history=completed_history,
            cumulative_cost=cumulative_cost,
        )
        steps.append(step)
        completed_history.append(record)
        cumulative_cost = step.cumulative_cost

    return _continue_workload_trace_v3(
        store,
        run_spec=run_spec,
        adapter=adapter,
        steps=steps,
        completed_history=completed_history,
        cumulative_cost=cumulative_cost,
    )


def _continue_workload_trace_v3(
    store: ExperimentStore,
    *,
    run_spec: RunSpecV3,
    adapter: WorkloadAdapter,
    steps: list[RunBundleStepV3],
    completed_history: list[CompletedWorkloadExperiment],
    cumulative_cost: float,
) -> CompletedWorkloadRunTraceV3:
    from research_decision_engine.run_bundle_v3 import (
        CompletedWorkloadRunTraceV3,
        _run_bundle_step_v3_from_completion,
    )

    stop_reason: StopReason
    while True:
        if len(steps) >= run_spec.experiment_count_budget:
            stop_reason = "experiment_budget_exhausted"
            break
        if run_spec.cost_budget is not None and cumulative_cost >= run_spec.cost_budget:
            stop_reason = "cost_budget_exhausted"
            break
        if len(completed_history) >= len(run_spec.candidates):
            stop_reason = "candidate_space_exhausted"
            break

        record = run_workload_experiment_v3(store, run_spec=run_spec, adapter=adapter)
        step = _run_bundle_step_v3_from_completion(
            run_spec=run_spec,
            record=record,
            completed_history=completed_history,
            cumulative_cost=cumulative_cost,
        )
        steps.append(step)
        completed_history.append(record)
        cumulative_cost = step.cumulative_cost

    return CompletedWorkloadRunTraceV3(
        run_spec=run_spec,
        steps=steps,
        stop_reason=stop_reason,
    )
