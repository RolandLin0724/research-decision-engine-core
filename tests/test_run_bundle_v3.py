from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from research_decision_engine.information_gain_table import FiniteTableEvidenceModel
from research_decision_engine.policy_contracts import (
    ReplayDecisionMismatchError,
    ReplayRationaleMismatchError,
    RunBundleVersionMismatchError,
)
from research_decision_engine.run_bundle_v3 import (
    _SUPPORTED_POLICY_FACTORIES_V3,
    CompletedWorkloadRunTraceV3,
    ReplayBeliefMismatchError,
    ReplayInformationGainScoreMismatchError,
    RunBundleV3ValidationError,
    _run_bundle_step_v3_from_completion,
    _selection_for_v3,
    export_run_bundle_v3,
    replay_run_bundle_v3,
    verify_run_bundle_v3,
)
from research_decision_engine.run_spec import (
    CandidateSpec,
    CompletedWorkloadExperiment,
    NormalizedObservation,
    _canonical_json_bytes,
)
from research_decision_engine.run_spec_v3 import RunSpecV3

POLICY_IDS = ("random", "greedy_prior", "information_gain_table")
IG_DECISION_KEYS = {
    "policy_identity",
    "selected_candidate_id",
    "selected_information_gain_bits",
    "eligible_candidate_count",
    "current_belief_fingerprint",
    "evidence_model_fingerprint",
    "tie_break",
}
V2_DECISION_KEYS = {
    "policy_id",
    "policy_seed",
    "selected_candidate_id",
    "selected_prior_utility",
    "eligible_candidate_count",
    "tie_break",
}


def _candidates() -> tuple[CandidateSpec, ...]:
    return (
        CandidateSpec("first", {"rank": 0}),
        CandidateSpec("second", {"rank": 1}),
        CandidateSpec("third", {"rank": 2}),
    )


def _evidence_model() -> FiniteTableEvidenceModel:
    return FiniteTableEvidenceModel(
        hypothesis_ids=("left", "right"),
        prior_weight_by_hypothesis={"left": 1, "right": 1},
        observation_metric="score",
        outcome_ids=("low", "high"),
        outcome_thresholds=(0.5,),
        likelihood_row_total=10,
        likelihood_weight_by_candidate_id={
            "first": {
                "left": {"low": 9, "high": 1},
                "right": {"low": 1, "high": 9},
            },
            "second": {
                "left": {"low": 8, "high": 2},
                "right": {"low": 2, "high": 8},
            },
            "third": {
                "left": {"low": 5, "high": 5},
                "right": {"low": 5, "high": 5},
            },
        },
    )


def _spec(policy_id: str) -> RunSpecV3:
    if policy_id == "random":
        config: dict[str, object] = {}
        seed: int | None = 20260804
    elif policy_id == "greedy_prior":
        config = {
            "utility_by_candidate_id": {"first": 1, "second": 5, "third": 3},
            "tie_break": "runspec_candidate_order",
        }
        seed = None
    else:
        config = {
            "evidence_model": _evidence_model().to_payload(),
            "tie_break": "runspec_candidate_order",
        }
        seed = None
    return RunSpecV3(
        candidates=_candidates(),
        policy_id=policy_id,
        policy_config=config,
        policy_seed=seed,
        experiment_count_budget=2,
        adapter_id="tests.must-not-execute",
        adapter_version="1",
        objective_name="score",
        objective_direction="maximize",
    )


def _trace(spec: RunSpecV3) -> CompletedWorkloadRunTraceV3:
    history: list[CompletedWorkloadExperiment] = []
    steps = []
    cumulative_cost = 0.0
    for index in range(spec.experiment_count_budget):
        selection = _selection_for_v3(spec, history)
        record = CompletedWorkloadExperiment(
            run_spec_fingerprint=spec.fingerprint(),
            candidate=selection.candidate,
            policy_id=spec.policy_id,
            observation=NormalizedObservation(0.2 if index == 0 else 0.8, cost=0.5),
            created_at="2026-08-04T00:00:00+00:00",
        )
        step = _run_bundle_step_v3_from_completion(
            run_spec=spec,
            record=record,
            completed_history=history,
            cumulative_cost=cumulative_cost,
        )
        history.append(record)
        steps.append(step)
        cumulative_cost = step.cumulative_cost
    return CompletedWorkloadRunTraceV3(
        run_spec=spec,
        steps=steps,
        stop_reason="experiment_budget_exhausted",
    )


@pytest.mark.parametrize("policy_id", POLICY_IDS)
def test_v3_export_and_read_only_verify_are_exact(policy_id: str, tmp_path: Path) -> None:
    spec = _spec(policy_id)
    destination = tmp_path / f"{policy_id}-bundle"
    exported = export_run_bundle_v3(destination, trace=_trace(spec))
    opening_document = (destination / "run-bundle.json").read_bytes()
    opening_sidecar = (destination / "run-bundle.json.sha256").read_bytes()

    verified = verify_run_bundle_v3(destination)

    assert exported == verified
    assert verified.valid is True
    assert verified.bundle.schema_version == "rde-core-run-bundle/v3"
    assert verified.bundle.replay_contract == "RECORDED_OBSERVATION_DECISION_REPLAY_V3"
    assert verified.bundle.run_spec == spec
    assert {item.name for item in destination.iterdir()} == {
        "run-bundle.json",
        "run-bundle.json.sha256",
    }
    assert opening_document.endswith(b"\n") and not opening_document.endswith(b"\n\n")
    assert opening_sidecar == hashlib.sha256(opening_document).hexdigest().encode() + b"\n"
    assert len(opening_sidecar) == 65
    assert (destination / "run-bundle.json").read_bytes() == opening_document
    assert (destination / "run-bundle.json.sha256").read_bytes() == opening_sidecar

    for step in verified.bundle.steps:
        if policy_id == "information_gain_table":
            assert set(step.decision) == IG_DECISION_KEYS
            assert len(step.belief_lineage) == 1
            score = step.decision["selected_information_gain_bits"]
            assert type(score) is str and score.count(".") == 1
            assert len(score.split(".")[1]) == 30
        else:
            assert set(step.decision) == V2_DECISION_KEYS
            assert step.belief_lineage == ()
    final_fingerprint = verified.bundle.terminal_summary["final_belief_fingerprint"]
    assert (final_fingerprint is not None) is (policy_id == "information_gain_table")


def test_v3_static_factory_is_closed_and_immutable() -> None:
    assert type(_SUPPORTED_POLICY_FACTORIES_V3) is MappingProxyType
    assert tuple(_SUPPORTED_POLICY_FACTORIES_V3) == POLICY_IDS
    with pytest.raises(TypeError):
        _SUPPORTED_POLICY_FACTORIES_V3["dynamic"] = lambda spec, history: None  # type: ignore[index]


def _rewrite_bundle(bundle_directory: Path, mutate: object) -> None:
    path = bundle_directory / "run-bundle.json"
    payload = json.loads(path.read_bytes())
    assert callable(mutate)
    mutate(payload)
    encoded = _canonical_json_bytes(payload)
    path.write_bytes(encoded)
    (bundle_directory / "run-bundle.json.sha256").write_bytes(
        hashlib.sha256(encoded).hexdigest().encode("ascii") + b"\n"
    )


def test_v3_verify_rejects_rehashed_information_gain_score_tamper(tmp_path: Path) -> None:
    destination = tmp_path / "bundle"
    export_run_bundle_v3(destination, trace=_trace(_spec("information_gain_table")))

    def mutate(payload: dict[str, object]) -> None:
        steps = payload["steps"]
        assert type(steps) is list and type(steps[0]) is dict
        decision = steps[0]["decision"]
        assert type(decision) is dict
        decision["selected_information_gain_bits"] = "0.000000000000000000000000000001"
        rationale = steps[0]["rationale"]
        assert type(rationale) is dict
        rationale["selected_information_gain_bits"] = "0.000000000000000000000000000001"

    _rewrite_bundle(destination, mutate)
    with pytest.raises(ReplayInformationGainScoreMismatchError):
        verify_run_bundle_v3(destination)


def test_v3_verify_rejects_rehashed_belief_lineage_tamper(tmp_path: Path) -> None:
    destination = tmp_path / "bundle"
    export_run_bundle_v3(destination, trace=_trace(_spec("information_gain_table")))

    def mutate(payload: dict[str, object]) -> None:
        steps = payload["steps"]
        assert type(steps) is list and type(steps[0]) is dict
        lineage = steps[0]["belief_lineage"]
        assert type(lineage) is list and type(lineage[0]) is dict
        weights = lineage[0]["weights_after"]
        assert type(weights) is list and type(weights[0]) is int
        weights[0] += 1

    _rewrite_bundle(destination, mutate)
    with pytest.raises(ReplayBeliefMismatchError):
        verify_run_bundle_v3(destination)


@pytest.mark.parametrize(
    ("field", "error_type"),
    [
        ("score", ReplayInformationGainScoreMismatchError),
        ("belief", ReplayBeliefMismatchError),
        ("decision", ReplayDecisionMismatchError),
        ("rationale", ReplayRationaleMismatchError),
    ],
)
def test_public_v3_replay_preserves_typed_mismatch_errors(
    field: str,
    error_type: type[Exception],
    tmp_path: Path,
) -> None:
    bundle = tmp_path / f"{field}-bundle"
    export_run_bundle_v3(bundle, trace=_trace(_spec("information_gain_table")))

    def mutate(payload: dict[str, object]) -> None:
        steps = payload["steps"]
        assert type(steps) is list and type(steps[0]) is dict
        decision = steps[0]["decision"]
        rationale = steps[0]["rationale"]
        lineage_items = steps[0]["belief_lineage"]
        assert type(decision) is dict and type(rationale) is dict
        assert type(lineage_items) is list and type(lineage_items[0]) is dict
        if field == "score":
            replacement: object = "0.000000000000000000000000000001"
            decision["selected_information_gain_bits"] = replacement
            rationale["selected_information_gain_bits"] = replacement
        elif field == "belief":
            weights = lineage_items[0]["weights_after"]
            assert type(weights) is list and type(weights[0]) is int
            weights[0] += 1
        elif field == "decision":
            replacement = "0" * 64
            decision["current_belief_fingerprint"] = replacement
            rationale["current_belief_fingerprint"] = replacement
            lineage_items[0]["belief_fingerprint_before"] = replacement
        else:
            eligible = rationale["eligible_candidate_ids"]
            assert type(eligible) is list
            eligible.reverse()

    _rewrite_bundle(bundle, mutate)
    replay_destination = tmp_path / f"{field}-replay"
    with pytest.raises(error_type):
        replay_run_bundle_v3(bundle, replay_destination)
    assert not replay_destination.exists()


@pytest.mark.parametrize("field", ["prior", "threshold", "likelihood", "observation"])
def test_v3_verify_rejects_rehashed_semantic_tamper(field: str, tmp_path: Path) -> None:
    destination = tmp_path / "bundle"
    export_run_bundle_v3(destination, trace=_trace(_spec("information_gain_table")))

    def mutate(payload: dict[str, object]) -> None:
        run_spec = payload["run_spec"]
        assert type(run_spec) is dict
        policy = run_spec["policy"]
        assert type(policy) is dict
        config = policy["config"]
        assert type(config) is dict
        model = config["evidence_model"]
        assert type(model) is dict
        if field == "prior":
            prior = model["prior_weight_by_hypothesis"]
            assert type(prior) is dict
            prior["left"] = 2
        elif field == "threshold":
            model["outcome_thresholds"] = [0.4]
        elif field == "likelihood":
            table = model["likelihood_weight_by_candidate_id"]
            assert type(table) is dict
            candidate = table["first"]
            assert type(candidate) is dict
            hypothesis = candidate["left"]
            assert type(hypothesis) is dict
            hypothesis["low"], hypothesis["high"] = 8, 2
        else:
            steps = payload["steps"]
            assert type(steps) is list and type(steps[0]) is dict
            observation = steps[0]["observation"]
            assert type(observation) is dict
            observation["objective_value"] = 0.8

    _rewrite_bundle(destination, mutate)
    with pytest.raises((RunBundleV3ValidationError, ReplayBeliefMismatchError)):
        verify_run_bundle_v3(destination)


def test_v3_strict_version_separation_rejects_bundle_and_runspec_v2(tmp_path: Path) -> None:
    for target in ("bundle", "runspec"):
        destination = tmp_path / target
        export_run_bundle_v3(destination, trace=_trace(_spec("random")))

        def mutate(payload: dict[str, object], target: str = target) -> None:
            if target == "bundle":
                payload["schema_version"] = "rde-core-run-bundle/v2"
            else:
                run_spec = payload["run_spec"]
                assert type(run_spec) is dict
                run_spec["schema"] = "rde-core-run-spec/v2"

        _rewrite_bundle(destination, mutate)
        with pytest.raises(RunBundleVersionMismatchError):
            verify_run_bundle_v3(destination)


def test_v3_export_refuses_existing_destination(tmp_path: Path) -> None:
    destination = tmp_path / "existing"
    destination.mkdir()
    marker = destination / "caller-owned"
    marker.write_text("preserve", encoding="utf-8")
    with pytest.raises(RunBundleV3ValidationError, match="must not already exist"):
        export_run_bundle_v3(destination, trace=_trace(_spec("random")))
    assert marker.read_text(encoding="utf-8") == "preserve"
