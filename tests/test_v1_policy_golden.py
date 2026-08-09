from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

# This private import is limited to freezing otherwise environment-derived
# producer provenance. Product construction and assertions use the public API.
import research_decision_engine.run_bundle as run_bundle_module
from research_decision_engine import (
    CandidateSpec,
    CompletedWorkloadRunTrace,
    RunBundleStep,
    RunSpec,
    export_run_bundle,
)

RUN_SPEC_V1_SHA256 = "59f05ad31d582e3330cbcfd789544273c7a6501519fb74b66600752ab2d168aa"
RUN_BUNDLE_V1_SHA256 = "146d83589e673aee90629f5192c1d4f355db30b5f90fa429b397cd8b313febde"
RUN_BUNDLE_V1_STEPS_SHA256 = "1d0da392270aa6bddeb6e137d8e4d767b2d34efe25b5bce8865ace6b00ad615e"
RUN_BUNDLE_V1_TERMINAL_SHA256 = "c09881b2ced053afb95b7c9d938835af4d911f8b9e0476aca0c761c20242f833"
RUN_BUNDLE_V1_BYTE_COUNT = 2360

RUN_SPEC_V1_CANONICAL_BYTES = (
    '{"adapter":{"id":"portable-python-score","version":"1"},'
    '"budget":{"cost":2.0,"experiment_count":2},'
    '"candidates":[{"candidate_id":"candidate-a","parameters":'
    '{"label":"alpha","x":1.0}},{"candidate_id":"candidate-b",'
    '"parameters":{"label":"beta","x":2.0}},{"candidate_id":"候选-c",'
    '"parameters":{"label":"gamma","x":3.0}}],'
    '"objective":{"direction":"maximize","name":"quality"},'
    '"policy":{"config":{},"id":"random","seed":11},'
    '"schema":"rde-core-run-spec/v1","tie_break":"candidate-order"}\n'
).encode()

FIXED_PRODUCER = {
    "package_name": "research-decision-engine",
    "package_version": "0.1.0",
    "python_implementation": "CPython",
    "python_version": "3.12.13",
}


def _v1_run_spec(*, policy_id: str = "random") -> RunSpec:
    return RunSpec(
        candidates=[
            CandidateSpec("candidate-a", {"x": 1.0, "label": "alpha"}),
            CandidateSpec("candidate-b", {"x": 2.0, "label": "beta"}),
            CandidateSpec("候选-c", {"x": 3.0, "label": "gamma"}),
        ],
        policy_id=policy_id,
        policy_config={},
        policy_seed=11,
        experiment_count_budget=2,
        cost_budget=2.0,
        adapter_id="portable-python-score",
        adapter_version="1",
        objective_name="quality",
        objective_direction="maximize",
        tie_break="candidate-order",
    )


def _v1_trace(spec: RunSpec) -> CompletedWorkloadRunTrace:
    return CompletedWorkloadRunTrace(
        run_spec=spec,
        steps=[
            RunBundleStep(
                step_index=0,
                selected_candidate_id="candidate-b",
                decision={
                    "policy_config": {},
                    "policy_id": "random",
                    "policy_seed": 11,
                    "selected_candidate_id": "candidate-b",
                },
                rationale={
                    "available_candidate_ids": [
                        "candidate-a",
                        "candidate-b",
                        "候选-c",
                    ],
                    "completed_candidate_ids": [],
                    "selection_rule": "random-choice-over-remaining-candidates/v1",
                },
                observation={
                    "candidate_id": "candidate-b",
                    "objective_value": 20.0,
                    "cost": 0.25,
                },
                belief_lineage=[],
                cumulative_cost=0.25,
            ),
            RunBundleStep(
                step_index=1,
                selected_candidate_id="候选-c",
                decision={
                    "policy_config": {},
                    "policy_id": "random",
                    "policy_seed": 11,
                    "selected_candidate_id": "候选-c",
                },
                rationale={
                    "available_candidate_ids": ["candidate-a", "候选-c"],
                    "completed_candidate_ids": ["candidate-b"],
                    "selection_rule": "random-choice-over-remaining-candidates/v1",
                },
                observation={
                    "candidate_id": "候选-c",
                    "objective_value": 30.0,
                    "cost": 0.5,
                },
                belief_lineage=[],
                cumulative_cost=0.75,
            ),
        ],
        stop_reason="experiment_budget_exhausted",
    )


def test_run_spec_v1_canonical_bytes_and_policy_contract_are_golden() -> None:
    spec = _v1_run_spec()

    assert len(RUN_SPEC_V1_CANONICAL_BYTES) == 484
    assert spec.to_canonical_bytes() == RUN_SPEC_V1_CANONICAL_BYTES
    assert spec.fingerprint() == RUN_SPEC_V1_SHA256
    assert hashlib.sha256(RUN_SPEC_V1_CANONICAL_BYTES).hexdigest() == RUN_SPEC_V1_SHA256

    for unsupported_policy in ("greedy", "greedy_prior"):
        with pytest.raises(ValueError, match="v1 supports only.*random"):
            _v1_run_spec(policy_id=unsupported_policy)


def test_run_bundle_v1_canonical_hashes_and_sidecar_are_golden(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        run_bundle_module,
        "_producer_payload",
        lambda: dict(FIXED_PRODUCER),
    )
    destination = tmp_path / "v1-golden"

    result = export_run_bundle(destination, trace=_v1_trace(_v1_run_spec()))
    encoded = (destination / "run-bundle.json").read_bytes()
    sidecar = (destination / "run-bundle.json.sha256").read_bytes()

    assert result.valid is True
    assert result.bundle.to_canonical_bytes() == encoded
    assert dict(result.bundle.producer) == FIXED_PRODUCER
    assert len(encoded) == RUN_BUNDLE_V1_BYTE_COUNT
    assert result.bundle_sha256 == RUN_BUNDLE_V1_SHA256
    assert hashlib.sha256(encoded).hexdigest() == RUN_BUNDLE_V1_SHA256
    assert result.run_spec_sha256 == RUN_SPEC_V1_SHA256
    assert result.steps_sha256 == RUN_BUNDLE_V1_STEPS_SHA256
    assert result.terminal_summary_sha256 == RUN_BUNDLE_V1_TERMINAL_SHA256
    assert sidecar == f"{RUN_BUNDLE_V1_SHA256}\n".encode("ascii")
    assert len(sidecar) == 65
