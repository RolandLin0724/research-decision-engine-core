from __future__ import annotations

import hashlib
import json
import os
import random
import re
import stat
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast

import pytest

# This module import is intentionally limited to publication/storage seam fault
# injection. Product construction and assertions use the public root API below.
import research_decision_engine.run_bundle as run_bundle_module
from research_decision_engine import (
    CandidateSpec,
    CompletedWorkloadExperiment,
    CompletedWorkloadRunTrace,
    NormalizedObservation,
    PythonFunctionAdapter,
    RunBundleStep,
    RunBundleValidationError,
    RunBundleVerificationError,
    RunBundleVerificationResult,
    RunSpec,
    export_run_bundle,
    verify_run_bundle,
)

TOP_LEVEL_FIELDS = {
    "schema_version",
    "artifact_role",
    "replay_contract",
    "run_spec",
    "run_spec_sha256",
    "producer",
    "steps",
    "terminal_summary",
    "section_sha256",
    "root_member_count",
}
STEP_FIELDS = {
    "step_index",
    "selected_candidate_id",
    "decision",
    "rationale",
    "observation",
    "belief_lineage",
    "cumulative_cost",
}
TERMINAL_FIELDS = {
    "completed_steps",
    "selected_candidate_ids",
    "total_cost",
    "stop_reason",
    "final_belief_fingerprint",
    "decision_history_sha256",
}

ExportedBundle = tuple[
    Path,
    RunSpec,
    tuple[CompletedWorkloadExperiment, ...],
    RunBundleVerificationResult,
]
PayloadMutation = Callable[[dict[str, Any]], None]


def _canonical(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _spec() -> RunSpec:
    return RunSpec(
        candidates=[
            CandidateSpec("candidate-a", {"x": 1.0, "label": "alpha"}),
            CandidateSpec("candidate-b", {"x": 2.0, "label": "beta"}),
            CandidateSpec("候选-c", {"x": 3.0, "label": "gamma"}),
        ],
        policy_id="random",
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


def _completed_run(spec: RunSpec) -> tuple[CompletedWorkloadExperiment, ...]:
    completed_ids: set[str] = set()
    records: list[CompletedWorkloadExperiment] = []
    costs = (0.25, 0.5)
    for index, cost in enumerate(costs):
        available = [
            candidate
            for candidate in spec.candidates
            if candidate.candidate_id not in completed_ids
        ]
        candidate = random.Random(spec.policy_seed).choice(available)
        records.append(
            CompletedWorkloadExperiment(
                run_spec_fingerprint=spec.fingerprint(),
                candidate=candidate,
                policy_id=spec.policy_id,
                observation=NormalizedObservation(
                    objective_value=cast(float, candidate.parameters["x"]) * 10.0,
                    cost=cost,
                ),
                created_at=f"2026-08-03T00:00:0{index}+00:00",
            )
        )
        completed_ids.add(candidate.candidate_id)
    return tuple(records)


def _trace(
    spec: RunSpec,
    completed_run: tuple[CompletedWorkloadExperiment, ...] | None = None,
    *,
    stop_reason: str = "experiment_budget_exhausted",
) -> CompletedWorkloadRunTrace:
    records = _completed_run(spec) if completed_run is None else completed_run
    completed_ids: list[str] = []
    cumulative_cost = 0.0
    steps: list[RunBundleStep] = []
    for index, record in enumerate(records):
        available_ids = [
            candidate.candidate_id
            for candidate in spec.candidates
            if candidate.candidate_id not in completed_ids
        ]
        cumulative_cost += record.observation.cost
        selected_id = record.candidate.candidate_id
        steps.append(
            RunBundleStep(
                step_index=index,
                selected_candidate_id=selected_id,
                decision={
                    "policy_config": dict(spec.policy_config),
                    "policy_id": spec.policy_id,
                    "policy_seed": spec.policy_seed,
                    "selected_candidate_id": selected_id,
                },
                rationale={
                    "available_candidate_ids": available_ids,
                    "completed_candidate_ids": list(completed_ids),
                    "selection_rule": "random-choice-over-remaining-candidates/v1",
                },
                observation={
                    "candidate_id": selected_id,
                    "objective_value": record.observation.objective_value,
                    "cost": record.observation.cost,
                },
                belief_lineage=[],
                cumulative_cost=cumulative_cost,
            )
        )
        completed_ids.append(selected_id)
    return CompletedWorkloadRunTrace(
        run_spec=spec,
        steps=steps,
        stop_reason=cast(Any, stop_reason),
    )


def _export(directory: Path, name: str = "bundle") -> ExportedBundle:
    spec = _spec()
    completed_run = _completed_run(spec)
    bundle_directory = directory / name
    result = export_run_bundle(
        bundle_directory,
        trace=_trace(spec, completed_run),
    )
    return bundle_directory, spec, completed_run, result


@pytest.fixture
def exported_bundle(tmp_path: Path) -> ExportedBundle:
    return _export(tmp_path)


def _payload(bundle_directory: Path) -> dict[str, Any]:
    value = cast(object, json.loads((bundle_directory / "run-bundle.json").read_bytes()))
    assert type(value) is dict
    return cast(dict[str, Any], value)


def _write_document_and_sidecar(bundle_directory: Path, encoded: bytes) -> None:
    (bundle_directory / "run-bundle.json").write_bytes(encoded)
    (bundle_directory / "run-bundle.json.sha256").write_bytes(
        hashlib.sha256(encoded).hexdigest().encode("ascii") + b"\n"
    )


def _mutate_and_resign(bundle_directory: Path, mutation: PayloadMutation) -> None:
    payload = _payload(bundle_directory)
    mutation(payload)
    _write_document_and_sidecar(bundle_directory, _canonical(payload))


def _resign_all_sections(payload: dict[str, Any]) -> None:
    run_spec_sha256 = hashlib.sha256(_canonical(payload["run_spec"])).hexdigest()
    steps_sha256 = hashlib.sha256(_canonical(payload["steps"])).hexdigest()
    payload["run_spec_sha256"] = run_spec_sha256
    payload["section_sha256"]["run_spec"] = run_spec_sha256
    payload["section_sha256"]["steps"] = steps_sha256
    payload["terminal_summary"]["decision_history_sha256"] = steps_sha256
    payload["section_sha256"]["terminal_summary"] = hashlib.sha256(
        _canonical(payload["terminal_summary"])
    ).hexdigest()


def _all_strings(value: object) -> Iterator[str]:
    if type(value) is str:
        yield value
    elif type(value) is dict:
        for key, item in cast(dict[str, object], value).items():
            yield key
            yield from _all_strings(item)
    elif type(value) is list:
        for item in cast(list[object], value):
            yield from _all_strings(item)


def _different_digest(current: str) -> str:
    replacement = "0" if current[0] != "0" else "1"
    return replacement + current[1:]


def test_run_bundle_step_valid_construction_is_immutable_and_detached() -> None:
    decision: dict[str, object] = {
        "policy_config": {},
        "policy_id": "random",
        "policy_seed": 11,
        "selected_candidate_id": "candidate-a",
    }
    rationale: dict[str, object] = {
        "available_candidate_ids": ["candidate-a"],
        "completed_candidate_ids": [],
        "selection_rule": "random-choice-over-remaining-candidates/v1",
    }
    observation: dict[str, object] = {
        "candidate_id": "candidate-a",
        "objective_value": 10.0,
        "cost": 0.25,
    }
    step = RunBundleStep(
        step_index=0,
        selected_candidate_id="candidate-a",
        decision=decision,
        rationale=rationale,
        observation=observation,
        belief_lineage=[],
        cumulative_cost=0.25,
    )

    decision["policy_seed"] = 999
    cast(list[str], rationale["available_candidate_ids"]).append("mutated")
    observation["objective_value"] = -1.0
    detached = cast(dict[str, object], step.decision)
    detached["policy_seed"] = -1

    assert set(step.to_payload()) == STEP_FIELDS
    assert step.decision["policy_seed"] == 11
    assert step.rationale["available_candidate_ids"] == ["candidate-a"]
    assert step.observation["objective_value"] == 10.0
    assert step.belief_lineage == ()
    with pytest.raises(FrozenInstanceError):
        cast(Any, step).cumulative_cost = 9.0


def test_completed_workload_run_trace_is_immutable_and_retains_exact_steps() -> None:
    spec = _spec()
    trace = _trace(spec)

    assert trace.run_spec is spec
    assert type(trace.steps) is tuple
    assert len(trace.steps) == 2
    assert trace.stop_reason == "experiment_budget_exhausted"
    assert trace.steps[0].rationale["completed_candidate_ids"] == []
    assert trace.steps[1].rationale["completed_candidate_ids"] == [
        trace.steps[0].selected_candidate_id
    ]
    with pytest.raises(FrozenInstanceError):
        cast(Any, trace).stop_reason = "completed"


def test_export_constructs_exact_canonical_schemas_and_round_trips(
    exported_bundle: ExportedBundle,
) -> None:
    bundle_directory, spec, _completed, result = exported_bundle
    encoded = (bundle_directory / "run-bundle.json").read_bytes()
    payload = _payload(bundle_directory)

    assert result.valid is True
    assert result.bundle.to_canonical_bytes() == encoded == _canonical(payload)
    assert result.bundle.schema_version == "rde-core-run-bundle/v1"
    assert result.bundle.artifact_role == "portable_recorded_observation_run_bundle"
    assert result.bundle.replay_contract == "RECORDED_OBSERVATION_DECISION_REPLAY_V1"
    assert result.bundle.root_member_count == payload["root_member_count"] == 2
    assert set(payload) == TOP_LEVEL_FIELDS
    assert len(payload) == 10
    assert len(payload["steps"]) == 2
    assert all(set(step) == STEP_FIELDS and len(step) == 7 for step in payload["steps"])
    assert set(payload["terminal_summary"]) == TERMINAL_FIELDS
    assert len(payload["terminal_summary"]) == 6
    assert set(payload["producer"]) == {
        "package_name",
        "package_version",
        "python_implementation",
        "python_version",
    }
    assert set(payload["section_sha256"]) == {
        "run_spec",
        "steps",
        "terminal_summary",
    }
    assert all(
        set(step["decision"])
        == {"policy_config", "policy_id", "policy_seed", "selected_candidate_id"}
        for step in payload["steps"]
    )
    assert all(
        set(step["rationale"])
        == {"available_candidate_ids", "completed_candidate_ids", "selection_rule"}
        for step in payload["steps"]
    )
    assert all(
        set(step["observation"]) == {"candidate_id", "objective_value", "cost"}
        for step in payload["steps"]
    )

    embedded_spec_bytes = _canonical(payload["run_spec"])
    assert RunSpec.from_canonical_bytes(embedded_spec_bytes) == spec == result.bundle.run_spec
    assert embedded_spec_bytes == spec.to_canonical_bytes()
    assert payload["run_spec_sha256"] == spec.fingerprint() == result.run_spec_sha256
    assert payload["section_sha256"]["run_spec"] == spec.fingerprint()
    assert (
        payload["section_sha256"]["steps"]
        == hashlib.sha256(_canonical(payload["steps"])).hexdigest()
    )
    assert (
        payload["section_sha256"]["terminal_summary"]
        == hashlib.sha256(_canonical(payload["terminal_summary"])).hexdigest()
    )
    assert payload["terminal_summary"]["decision_history_sha256"] == result.steps_sha256
    assert result.selected_candidate_ids == tuple(
        step["selected_candidate_id"] for step in payload["steps"]
    )

    with pytest.raises(FrozenInstanceError):
        cast(Any, result).valid = False
    with pytest.raises(FrozenInstanceError):
        cast(Any, result.bundle).schema_version = "changed"
    with pytest.raises(FrozenInstanceError):
        cast(Any, result.bundle.steps[0]).step_index = 99
    detached_terminal = cast(dict[str, object], result.bundle.terminal_summary)
    detached_terminal["completed_steps"] = 99
    detached_decision = cast(dict[str, object], result.bundle.steps[0].decision)
    detached_decision["policy_seed"] = 99
    assert result.bundle.terminal_summary["completed_steps"] == 2
    assert result.bundle.steps[0].decision["policy_seed"] == spec.policy_seed


def test_two_exports_are_byte_deterministic_and_have_exact_physical_layout(
    tmp_path: Path,
) -> None:
    spec = _spec()
    completed_run = _completed_run(spec)
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_result = export_run_bundle(
        first,
        trace=_trace(spec, completed_run),
    )
    second_result = export_run_bundle(
        second,
        trace=_trace(spec, completed_run),
    )

    first_members = sorted(path.name for path in first.iterdir())
    assert first_members == ["run-bundle.json", "run-bundle.json.sha256"]
    assert sorted(path.name for path in second.iterdir()) == first_members
    for directory in (first, second):
        for member in directory.iterdir():
            status = member.lstat()
            assert stat.S_ISREG(status.st_mode)
            assert not member.is_symlink()
        sidecar = (directory / "run-bundle.json.sha256").read_bytes()
        encoded = (directory / "run-bundle.json").read_bytes()
        assert len(sidecar) == 65
        assert re.fullmatch(rb"[0-9a-f]{64}\n", sidecar)
        assert sidecar == hashlib.sha256(encoded).hexdigest().encode("ascii") + b"\n"

    assert (first / "run-bundle.json").read_bytes() == (second / "run-bundle.json").read_bytes()
    assert (first / "run-bundle.json.sha256").read_bytes() == (
        second / "run-bundle.json.sha256"
    ).read_bytes()
    assert first_result.bundle_sha256 == second_result.bundle_sha256
    assert first_result == verify_run_bundle(first)
    assert second_result == verify_run_bundle(second)


def test_zero_step_bundle_uses_exact_zero_terminal_summary(tmp_path: Path) -> None:
    spec = _spec()
    destination = tmp_path / "zero-step"

    result = export_run_bundle(
        destination,
        trace=_trace(spec, (), stop_reason="stopped_by_caller"),
    )

    assert result.step_count == 0
    assert result.selected_candidate_ids == ()
    assert result.bundle.steps == ()
    assert dict(result.bundle.terminal_summary) == {
        "completed_steps": 0,
        "selected_candidate_ids": [],
        "total_cost": 0.0,
        "stop_reason": "stopped_by_caller",
        "final_belief_fingerprint": None,
        "decision_history_sha256": result.steps_sha256,
    }
    assert verify_run_bundle(destination) == result


def test_export_does_not_execute_or_serialize_the_python_adapter(tmp_path: Path) -> None:
    spec = _spec()
    calls = 0
    absolute_marker = str((tmp_path / "callable-source.py").resolve())
    callable_marker = f"CALLABLE-REPR<{absolute_marker}>@0xDEADBEEF"

    class TrappingCallable:
        def __repr__(self) -> str:
            return callable_marker

        def __call__(self, candidate: CandidateSpec) -> NormalizedObservation:
            nonlocal calls
            calls += 1
            raise AssertionError(f"export executed adapter for {candidate.candidate_id}")

    adapter = PythonFunctionAdapter(
        TrappingCallable(),
        adapter_id=spec.adapter_id,
        adapter_version=spec.adapter_version,
    )
    assert adapter.adapter_id == spec.adapter_id

    bundle_directory = tmp_path / "no-adapter-execution"
    export_run_bundle(
        bundle_directory,
        trace=_trace(spec),
    )
    strings = tuple(_all_strings(_payload(bundle_directory)))

    assert calls == 0
    assert callable_marker not in strings
    assert absolute_marker not in strings
    assert not any("0xDEADBEEF" in value for value in strings)
    assert not any(str(tmp_path.resolve()) in value for value in strings)


def _mutate_schema(payload: dict[str, Any], case: str) -> None:
    if case == "top_unknown":
        payload["future"] = None
    elif case == "top_missing":
        payload.pop("producer")
    elif case == "producer_unknown":
        payload["producer"]["hostname"] = "forbidden"
    elif case == "producer_missing":
        payload["producer"].pop("python_version")
    elif case == "section_unknown":
        payload["section_sha256"]["future"] = "0" * 64
    elif case == "section_missing":
        payload["section_sha256"].pop("steps")
    elif case == "step_unknown":
        payload["steps"][0]["future"] = None
    elif case == "step_missing":
        payload["steps"][0].pop("rationale")
    elif case == "decision_unknown":
        payload["steps"][0]["decision"]["future"] = None
    elif case == "decision_missing":
        payload["steps"][0]["decision"].pop("policy_seed")
    elif case == "rationale_unknown":
        payload["steps"][0]["rationale"]["future"] = None
    elif case == "rationale_missing":
        payload["steps"][0]["rationale"].pop("selection_rule")
    elif case == "observation_unknown":
        payload["steps"][0]["observation"]["future"] = None
    elif case == "observation_missing":
        payload["steps"][0]["observation"].pop("cost")
    elif case == "terminal_unknown":
        payload["terminal_summary"]["future"] = None
    elif case == "terminal_missing":
        payload["terminal_summary"].pop("stop_reason")
    elif case == "run_spec_unknown":
        payload["run_spec"]["future"] = None
    elif case == "run_spec_missing":
        payload["run_spec"].pop("objective")
    else:
        raise AssertionError(f"unknown schema mutation case: {case}")


@pytest.mark.parametrize(
    "case",
    [
        "top_unknown",
        "top_missing",
        "producer_unknown",
        "producer_missing",
        "section_unknown",
        "section_missing",
        "step_unknown",
        "step_missing",
        "decision_unknown",
        "decision_missing",
        "rationale_unknown",
        "rationale_missing",
        "observation_unknown",
        "observation_missing",
        "terminal_unknown",
        "terminal_missing",
        "run_spec_unknown",
        "run_spec_missing",
    ],
)
def test_verify_rejects_unknown_and_missing_schema_fields(
    exported_bundle: ExportedBundle, case: str
) -> None:
    bundle_directory = exported_bundle[0]
    _mutate_and_resign(bundle_directory, lambda payload: _mutate_schema(payload, case))

    with pytest.raises(RunBundleVerificationError):
        verify_run_bundle(bundle_directory)


def test_verify_rejects_unknown_schema_version(exported_bundle: ExportedBundle) -> None:
    bundle_directory = exported_bundle[0]
    _mutate_and_resign(
        bundle_directory,
        lambda payload: payload.__setitem__("schema_version", "rde-core-run-bundle/v2"),
    )

    with pytest.raises(RunBundleVerificationError):
        verify_run_bundle(bundle_directory)


@pytest.mark.parametrize(
    "case",
    [
        "non_utf8",
        "bom",
        "cr",
        "missing_lf",
        "duplicate_key",
        "nan",
        "infinity",
        "negative_infinity",
    ],
)
def test_verify_rejects_noncanonical_or_nonfinite_document_bytes(
    exported_bundle: ExportedBundle, case: str
) -> None:
    bundle_directory = exported_bundle[0]
    original = (bundle_directory / "run-bundle.json").read_bytes()
    if case == "non_utf8":
        tampered = b"\xff" + original
    elif case == "bom":
        tampered = b"\xef\xbb\xbf" + original
    elif case == "cr":
        tampered = original[:-1] + b"\r\n"
    elif case == "missing_lf":
        tampered = original.removesuffix(b"\n")
    elif case == "duplicate_key":
        tampered = original.replace(
            b'"root_member_count":2',
            b'"root_member_count":2,"root_member_count":2',
            1,
        )
    elif case in {"nan", "infinity", "negative_infinity"}:
        replacement = {
            "nan": b"NaN",
            "infinity": b"Infinity",
            "negative_infinity": b"-Infinity",
        }[case]
        tampered, replacements = re.subn(
            rb'("objective_value":)-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?',
            rb"\1" + replacement,
            original,
            count=1,
        )
        assert replacements == 1
    else:
        raise AssertionError(f"unknown byte mutation case: {case}")
    assert tampered != original
    _write_document_and_sidecar(bundle_directory, tampered)

    with pytest.raises(RunBundleVerificationError):
        verify_run_bundle(bundle_directory)


@pytest.mark.parametrize("hidden_key", ["true-value", "trueValue", "groundTruth"])
def test_verify_rejects_hidden_truth_even_when_outer_sidecar_is_resigned(
    exported_bundle: ExportedBundle, hidden_key: str
) -> None:
    bundle_directory = exported_bundle[0]

    def add_hidden_truth(payload: dict[str, Any]) -> None:
        payload["run_spec"]["candidates"][0]["parameters"][hidden_key] = 99.0

    _mutate_and_resign(bundle_directory, add_hidden_truth)
    with pytest.raises(RunBundleVerificationError) as raised:
        verify_run_bundle(bundle_directory)

    assert raised.value.__cause__ is not None
    assert "hidden-truth" in str(raised.value.__cause__)


def test_verify_rejects_absolute_producer_path(exported_bundle: ExportedBundle) -> None:
    bundle_directory = exported_bundle[0]
    absolute_path = str((bundle_directory.parent / "source.py").resolve())

    def add_absolute_path(payload: dict[str, Any]) -> None:
        payload["producer"]["package_name"] = absolute_path

    _mutate_and_resign(bundle_directory, add_absolute_path)
    with pytest.raises(RunBundleVerificationError):
        verify_run_bundle(bundle_directory)


@pytest.mark.parametrize("section", ["run_spec", "steps", "terminal_summary"])
def test_verify_rejects_section_hash_tampering(
    exported_bundle: ExportedBundle, section: str
) -> None:
    bundle_directory = exported_bundle[0]

    def tamper_hash(payload: dict[str, Any]) -> None:
        current = cast(str, payload["section_sha256"][section])
        payload["section_sha256"][section] = _different_digest(current)

    _mutate_and_resign(bundle_directory, tamper_hash)
    with pytest.raises(RunBundleVerificationError):
        verify_run_bundle(bundle_directory)


@pytest.mark.parametrize(
    "target",
    [
        "run_spec_sha256",
        "section_run_spec",
        "section_steps",
        "section_terminal",
        "decision_history_sha256",
    ],
)
@pytest.mark.parametrize("malformed", ["A" * 64, "g" * 64, "0" * 63])
def test_verify_rejects_malformed_internal_digest_syntax(
    exported_bundle: ExportedBundle, target: str, malformed: str
) -> None:
    bundle_directory = exported_bundle[0]

    def tamper_digest(payload: dict[str, Any]) -> None:
        if target == "run_spec_sha256":
            payload["run_spec_sha256"] = malformed
        elif target == "section_run_spec":
            payload["section_sha256"]["run_spec"] = malformed
        elif target == "section_steps":
            payload["section_sha256"]["steps"] = malformed
        elif target == "section_terminal":
            payload["section_sha256"]["terminal_summary"] = malformed
        elif target == "decision_history_sha256":
            payload["terminal_summary"]["decision_history_sha256"] = malformed
        else:
            raise AssertionError(f"unknown digest target: {target}")

    _mutate_and_resign(bundle_directory, tamper_digest)
    with pytest.raises(RunBundleVerificationError):
        verify_run_bundle(bundle_directory)


def _tamper_section_content(payload: dict[str, Any], section: str) -> None:
    if section == "run_spec":
        payload["run_spec"]["objective"]["name"] = "tampered-quality"
    elif section == "decision":
        payload["steps"][0]["decision"]["policy_seed"] += 1
    elif section == "rationale":
        payload["steps"][0]["rationale"]["selection_rule"] = "tampered-rule/v1"
    elif section == "observation":
        payload["steps"][0]["observation"]["objective_value"] += 1.0
    elif section == "lineage":
        payload["steps"][0]["belief_lineage"] = [{"fingerprint": "0" * 64}]
    elif section == "terminal":
        payload["terminal_summary"]["stop_reason"] = "completed"
    else:
        raise AssertionError(f"unknown content section: {section}")


@pytest.mark.parametrize(
    "section", ["run_spec", "decision", "rationale", "observation", "lineage", "terminal"]
)
def test_verify_rejects_resigned_section_content_tampering(
    exported_bundle: ExportedBundle, section: str
) -> None:
    bundle_directory = exported_bundle[0]
    _mutate_and_resign(bundle_directory, lambda payload: _tamper_section_content(payload, section))

    with pytest.raises(RunBundleVerificationError):
        verify_run_bundle(bundle_directory)


@pytest.mark.parametrize(
    "case",
    ["uppercase", "missing_lf", "crlf", "double_lf", "nonhex", "mismatch"],
)
def test_verify_rejects_malformed_or_tampered_sidecar(
    exported_bundle: ExportedBundle, case: str
) -> None:
    bundle_directory = exported_bundle[0]
    encoded = (bundle_directory / "run-bundle.json").read_bytes()
    digest = hashlib.sha256(encoded).hexdigest().encode("ascii")
    if case == "uppercase":
        sidecar = digest.upper() + b"\n"
    elif case == "missing_lf":
        sidecar = digest
    elif case == "crlf":
        sidecar = digest + b"\r\n"
    elif case == "double_lf":
        sidecar = digest + b"\n\n"
    elif case == "nonhex":
        sidecar = b"g" * 64 + b"\n"
    elif case == "mismatch":
        sidecar = b"0" * 64 + b"\n"
    else:
        raise AssertionError(f"unknown sidecar mutation case: {case}")
    assert sidecar != digest + b"\n"
    (bundle_directory / "run-bundle.json.sha256").write_bytes(sidecar)

    with pytest.raises(RunBundleVerificationError):
        verify_run_bundle(bundle_directory)


def test_verify_rejects_an_extra_root_member(exported_bundle: ExportedBundle) -> None:
    bundle_directory = exported_bundle[0]
    (bundle_directory / "unexpected.txt").write_bytes(b"third member\n")

    with pytest.raises(RunBundleVerificationError):
        verify_run_bundle(bundle_directory)


def test_verify_rejects_root_file_member_directory_and_hardlink_alias(tmp_path: Path) -> None:
    root_file = tmp_path / "root-file"
    root_file.write_bytes(b"not a directory\n")
    with pytest.raises(RunBundleVerificationError):
        verify_run_bundle(root_file)

    member_directory_bundle = _export(tmp_path, "member-directory")[0]
    sidecar = member_directory_bundle / "run-bundle.json.sha256"
    sidecar.unlink()
    sidecar.mkdir()
    with pytest.raises(RunBundleVerificationError):
        verify_run_bundle(member_directory_bundle)

    hardlink_bundle = _export(tmp_path, "hardlink-alias")[0]
    hardlink_sidecar = hardlink_bundle / "run-bundle.json.sha256"
    hardlink_sidecar.unlink()
    hardlink_sidecar.hardlink_to(hardlink_bundle / "run-bundle.json")
    with pytest.raises(RunBundleVerificationError):
        verify_run_bundle(hardlink_bundle)


def test_verify_rejects_missing_member_and_reparse_substitutes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing_member_bundle = _export(tmp_path, "missing-member")[0]
    (missing_member_bundle / "run-bundle.json.sha256").unlink()
    with pytest.raises(RunBundleVerificationError):
        verify_run_bundle(missing_member_bundle)

    reparse_member_bundle = _export(tmp_path, "reparse-member")[0]
    original_is_reparse = run_bundle_module._is_reparse

    def mark_sidecar_as_reparse(path: Path, status: object = None) -> bool:
        if path.name == "run-bundle.json.sha256":
            return True
        return original_is_reparse(path, cast(Any, status))

    monkeypatch.setattr(run_bundle_module, "_is_reparse", mark_sidecar_as_reparse)
    with pytest.raises(RunBundleVerificationError):
        verify_run_bundle(reparse_member_bundle)


def test_verify_rejects_a_fully_resigned_policy_selection_deviation(
    exported_bundle: ExportedBundle,
) -> None:
    bundle_directory = exported_bundle[0]

    def change_first_selection(payload: dict[str, Any]) -> None:
        recorded_ids = [step["selected_candidate_id"] for step in payload["steps"]]
        replacement = next(
            candidate["candidate_id"]
            for candidate in payload["run_spec"]["candidates"]
            if candidate["candidate_id"] not in recorded_ids
        )
        first = payload["steps"][0]
        first["selected_candidate_id"] = replacement
        first["decision"]["selected_candidate_id"] = replacement
        first["observation"]["candidate_id"] = replacement
        payload["terminal_summary"]["selected_candidate_ids"][0] = replacement
        _resign_all_sections(payload)

    _mutate_and_resign(bundle_directory, change_first_selection)
    with pytest.raises(RunBundleVerificationError):
        verify_run_bundle(bundle_directory)


def _mutate_step(payload: dict[str, Any], case: str) -> None:
    steps = payload["steps"]
    if case == "noncontiguous_index":
        steps[0]["step_index"] = 1
    elif case == "duplicate_index":
        steps[1]["step_index"] = steps[0]["step_index"]
    elif case == "duplicate_candidate":
        steps[1]["selected_candidate_id"] = steps[0]["selected_candidate_id"]
    elif case == "unknown_candidate":
        steps[0]["selected_candidate_id"] = "unknown-candidate"
    elif case == "decision_candidate_mismatch":
        selected = steps[0]["selected_candidate_id"]
        steps[0]["decision"]["selected_candidate_id"] = next(
            item["candidate_id"]
            for item in payload["run_spec"]["candidates"]
            if item["candidate_id"] != selected
        )
    elif case == "observation_candidate_mismatch":
        selected = steps[0]["selected_candidate_id"]
        steps[0]["observation"]["candidate_id"] = next(
            item["candidate_id"]
            for item in payload["run_spec"]["candidates"]
            if item["candidate_id"] != selected
        )
    elif case == "selected_sequence_mismatch":
        steps[0]["rationale"]["available_candidate_ids"].reverse()
    elif case == "decreasing_cost":
        steps[1]["cumulative_cost"] = steps[0]["cumulative_cost"] - 0.125
    else:
        raise AssertionError(f"unknown step mutation case: {case}")


@pytest.mark.parametrize(
    "case",
    [
        "noncontiguous_index",
        "duplicate_index",
        "duplicate_candidate",
        "unknown_candidate",
        "decision_candidate_mismatch",
        "observation_candidate_mismatch",
        "selected_sequence_mismatch",
        "decreasing_cost",
    ],
)
def test_verify_rejects_step_index_candidate_and_cost_inconsistencies(
    exported_bundle: ExportedBundle, case: str
) -> None:
    bundle_directory = exported_bundle[0]
    _mutate_and_resign(bundle_directory, lambda payload: _mutate_step(payload, case))

    with pytest.raises(RunBundleVerificationError):
        verify_run_bundle(bundle_directory)


def _mutate_terminal(payload: dict[str, Any], case: str) -> None:
    summary = payload["terminal_summary"]
    if case == "completed_steps":
        summary["completed_steps"] += 1
    elif case == "selected_candidate_ids":
        summary["selected_candidate_ids"].reverse()
    elif case == "total_cost":
        summary["total_cost"] += 0.125
    elif case == "unknown_stop_reason":
        summary["stop_reason"] = "timed_out"
    elif case == "inapplicable_stop_reason":
        summary["stop_reason"] = "candidate_space_exhausted"
    elif case == "final_belief_fingerprint":
        summary["final_belief_fingerprint"] = "0" * 64
    elif case == "decision_history_sha256":
        summary["decision_history_sha256"] = "0" * 64
    else:
        raise AssertionError(f"unknown terminal mutation case: {case}")


@pytest.mark.parametrize(
    "case",
    [
        "completed_steps",
        "selected_candidate_ids",
        "total_cost",
        "unknown_stop_reason",
        "inapplicable_stop_reason",
        "final_belief_fingerprint",
        "decision_history_sha256",
    ],
)
def test_verify_rejects_terminal_summary_mismatches(
    exported_bundle: ExportedBundle, case: str
) -> None:
    bundle_directory = exported_bundle[0]
    _mutate_and_resign(bundle_directory, lambda payload: _mutate_terminal(payload, case))

    with pytest.raises(RunBundleVerificationError):
        verify_run_bundle(bundle_directory)


@pytest.mark.parametrize("destination_kind", ["directory", "file"])
def test_export_rejects_an_existing_destination_without_modifying_it(
    tmp_path: Path, destination_kind: str
) -> None:
    destination = tmp_path / "already-exists"
    if destination_kind == "directory":
        destination.mkdir()
        sentinel = destination / "sentinel.txt"
        sentinel.write_bytes(b"preserve me\n")
    else:
        destination.write_bytes(b"preserve me\n")
        sentinel = destination
    before = sentinel.read_bytes()

    spec = _spec()
    with pytest.raises(RunBundleValidationError, match="must not already exist"):
        export_run_bundle(
            destination,
            trace=_trace(spec),
        )

    assert sentinel.read_bytes() == before
    assert list(tmp_path.glob(".already-exists.tmp-*")) == []


def test_export_atomic_rename_failure_removes_only_its_temporary_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "atomic"
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_bytes(b"preserve me\n")
    spec = _spec()

    def fail_rename(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected atomic rename failure")

    monkeypatch.setattr(run_bundle_module, "_publish_directory_no_replace", fail_rename)
    with pytest.raises(RunBundleValidationError, match="failed without publication") as raised:
        export_run_bundle(
            destination,
            trace=_trace(spec),
        )

    assert isinstance(raised.value.__cause__, OSError)
    assert not destination.exists()
    assert list(tmp_path.glob(".atomic.tmp-*")) == []
    assert unrelated.read_bytes() == b"preserve me\n"


def test_export_keyboard_interrupt_removes_all_owned_temporary_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "interrupted-export"
    original_write = run_bundle_module._write_new_file
    writes = 0

    def interrupt_after_first_write(
        path: Path,
        content: bytes,
        *,
        owned_member_identities: dict[str, tuple[int, int]],
    ) -> None:
        nonlocal writes
        original_write(
            path,
            content,
            owned_member_identities=owned_member_identities,
        )
        writes += 1
        if writes == 1:
            raise KeyboardInterrupt

    monkeypatch.setattr(run_bundle_module, "_write_new_file", interrupt_after_first_write)
    with pytest.raises(KeyboardInterrupt):
        export_run_bundle(destination, trace=_trace(_spec()))

    assert writes == 1
    assert not destination.exists()
    assert list(tmp_path.glob(".interrupted-export.tmp-*")) == []


def test_export_postpublication_verification_failure_removes_owned_final_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "postpublication-failure"
    spec = _spec()
    original_verify = run_bundle_module.verify_run_bundle
    verification_calls = 0

    def fail_second_verification(path: Path) -> RunBundleVerificationResult:
        nonlocal verification_calls
        verification_calls += 1
        if verification_calls == 1:
            return original_verify(path)
        raise RunBundleVerificationError("injected postpublication failure")

    monkeypatch.setattr(run_bundle_module, "verify_run_bundle", fail_second_verification)
    with pytest.raises(RunBundleVerificationError, match="injected postpublication"):
        export_run_bundle(
            destination,
            trace=_trace(spec),
        )

    assert verification_calls == 2
    assert not destination.exists()
    assert list(tmp_path.glob(".postpublication-failure.tmp-*")) == []


def test_export_no_clobber_preserves_a_destination_that_appears_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "publication-race"
    original_verify = run_bundle_module.verify_run_bundle
    calls = 0

    def create_competing_destination(path: Path) -> RunBundleVerificationResult:
        nonlocal calls
        result = original_verify(path)
        calls += 1
        if calls == 1:
            destination.mkdir()
            (destination / "operator-owned.txt").write_bytes(b"preserve me\n")
        return result

    monkeypatch.setattr(run_bundle_module, "verify_run_bundle", create_competing_destination)
    with pytest.raises(RunBundleValidationError, match="appeared before publication"):
        export_run_bundle(destination, trace=_trace(_spec()))

    assert (destination / "operator-owned.txt").read_bytes() == b"preserve me\n"
    assert list(tmp_path.glob(".publication-race.tmp-*")) == []


def test_export_failure_removes_owned_members_but_preserves_injected_foreign_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "foreign-entry-race"
    original_verify = run_bundle_module.verify_run_bundle
    calls = 0

    def inject_after_publication(path: Path) -> RunBundleVerificationResult:
        nonlocal calls
        calls += 1
        if calls == 2:
            (path / "operator-owned.txt").write_bytes(b"preserve me\n")
            raise RunBundleVerificationError("injected foreign entry")
        return original_verify(path)

    monkeypatch.setattr(run_bundle_module, "verify_run_bundle", inject_after_publication)
    with pytest.raises(RunBundleVerificationError, match="injected foreign entry"):
        export_run_bundle(destination, trace=_trace(_spec()))

    assert sorted(path.name for path in destination.iterdir()) == ["operator-owned.txt"]
    assert (destination / "operator-owned.txt").read_bytes() == b"preserve me\n"
    assert list(tmp_path.glob(".foreign-entry-race.tmp-*")) == []


@pytest.mark.parametrize(
    "absolute_value",
    [
        r"C:\temp\secret.dat",
        r"\temp\secret.dat",
        r"C:temp\secret.dat",
        "/tmp/secret.dat",
        "file:///C:/temp/secret.dat",
        "file:///tmp/secret.dat",
        "file://server/share/secret.dat",
    ],
)
def test_export_rejects_machine_local_paths_from_bundle_identity(
    tmp_path: Path, absolute_value: str
) -> None:
    spec = RunSpec(
        candidates=[
            CandidateSpec("candidate-a", {"input": absolute_value, "x": 1.0}),
            CandidateSpec("candidate-b", {"input": "portable.dat", "x": 2.0}),
        ],
        policy_id="random",
        policy_config={},
        policy_seed=11,
        experiment_count_budget=1,
        adapter_id="portable-python-score",
        adapter_version="1",
        objective_name="quality",
        objective_direction="maximize",
    )
    destination = tmp_path / "absolute-path-bundle"

    with pytest.raises(RunBundleValidationError, match="absolute path"):
        export_run_bundle(
            destination,
            trace=_trace(spec, _completed_run(spec)[:1]),
        )
    assert not destination.exists()


def test_verify_rejects_a_bundle_reached_through_a_reparse_ancestor(tmp_path: Path) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    bundle_directory = _export(real_parent, "bundle")[0]
    alias_parent = tmp_path / "alias-parent"
    if os.name == "nt":
        created = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(alias_parent), str(real_parent)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert created.returncode == 0, created.stderr
        assert alias_parent.is_junction()
    else:
        alias_parent.symlink_to(real_parent, target_is_directory=True)
        assert alias_parent.is_symlink()

    with pytest.raises(RunBundleVerificationError, match="must not traverse"):
        verify_run_bundle(alias_parent / bundle_directory.name)


def test_export_rejects_a_step_after_the_cost_budget_is_exhausted(tmp_path: Path) -> None:
    spec = RunSpec(
        candidates=_spec().candidates,
        policy_id="random",
        policy_config={},
        policy_seed=11,
        experiment_count_budget=2,
        cost_budget=0.25,
        adapter_id="portable-python-score",
        adapter_version="1",
        objective_name="quality",
        objective_direction="maximize",
    )
    first, second = _completed_run(spec)
    second = CompletedWorkloadExperiment(
        run_spec_fingerprint=spec.fingerprint(),
        candidate=second.candidate,
        policy_id=spec.policy_id,
        observation=NormalizedObservation(second.observation.objective_value, cost=0.0),
        created_at=second.created_at,
    )
    destination = tmp_path / "continued-after-cost-budget"

    with pytest.raises(RunBundleValidationError, match="continues after"):
        export_run_bundle(
            destination,
            trace=_trace(spec, (first, second)),
        )
    assert not destination.exists()


@pytest.mark.parametrize("case", ["exceeds_budget", "continues_after_exhaustion"])
def test_verify_rejects_fully_resigned_cost_budget_violations(
    exported_bundle: ExportedBundle, case: str
) -> None:
    bundle_directory = exported_bundle[0]

    def violate_cost_budget(payload: dict[str, Any]) -> None:
        if case == "exceeds_budget":
            payload["run_spec"]["budget"]["cost"] = 0.5
        elif case == "continues_after_exhaustion":
            payload["run_spec"]["budget"]["cost"] = 0.25
            payload["steps"][1]["observation"]["cost"] = 0.0
            payload["steps"][1]["cumulative_cost"] = 0.25
            payload["terminal_summary"]["total_cost"] = 0.25
        else:
            raise AssertionError(f"unknown cost-budget case: {case}")
        _resign_all_sections(payload)

    _mutate_and_resign(bundle_directory, violate_cost_budget)
    with pytest.raises(RunBundleVerificationError, match="strict verification"):
        verify_run_bundle(bundle_directory)


def test_verify_is_read_only_and_does_not_create_or_open_sqlite(
    exported_bundle: ExportedBundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_directory = exported_bundle[0]
    before = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_size)
        for path in bundle_directory.iterdir()
    }

    class ForbiddenExperimentStore:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("verify_run_bundle attempted to open SQLite")

    def forbidden_evaluate(
        _adapter: PythonFunctionAdapter, _candidate: CandidateSpec
    ) -> NormalizedObservation:
        raise AssertionError("verify_run_bundle attempted to execute an adapter")

    monkeypatch.setattr(run_bundle_module, "ExperimentStore", ForbiddenExperimentStore)
    monkeypatch.setattr(PythonFunctionAdapter, "evaluate", forbidden_evaluate)
    result = verify_run_bundle(bundle_directory)

    after = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_size)
        for path in bundle_directory.iterdir()
    }
    assert result.valid is True
    assert after == before
    assert sorted(after) == ["run-bundle.json", "run-bundle.json.sha256"]
    assert list(bundle_directory.parent.rglob("*.sqlite*")) == []


def test_verify_rejects_same_byte_member_replacement_between_inventory_passes(
    exported_bundle: ExportedBundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_directory = exported_bundle[0]
    sidecar = bundle_directory / "run-bundle.json.sha256"
    sidecar_bytes = sidecar.read_bytes()
    original_inventory = run_bundle_module._strict_bundle_inventory
    original_close_member_guards = run_bundle_module._close_posix_member_guards
    inventory_calls = 0
    closed_member_descriptors: list[int] = []

    def replace_before_final_inventory(root: Path) -> dict[str, Path]:
        nonlocal inventory_calls
        inventory_calls += 1
        if inventory_calls == 2:
            sidecar.unlink()
            sidecar.write_bytes(sidecar_bytes)
        return original_inventory(root)

    def record_closed_member_guards(
        guards: tuple[run_bundle_module._PosixMemberGuard, ...],
    ) -> None:
        closed_member_descriptors.extend(guard.descriptor for guard in guards)
        original_close_member_guards(guards)

    monkeypatch.setattr(
        run_bundle_module,
        "_strict_bundle_inventory",
        replace_before_final_inventory,
    )
    monkeypatch.setattr(
        run_bundle_module,
        "_close_posix_member_guards",
        record_closed_member_guards,
    )
    with pytest.raises(RunBundleVerificationError, match="member identity changed"):
        verify_run_bundle(bundle_directory)

    assert inventory_calls == 2
    if os.name == "nt":
        assert closed_member_descriptors == []
    else:
        assert len(closed_member_descriptors) == 2
        for descriptor in closed_member_descriptors:
            with pytest.raises(OSError):
                os.fstat(descriptor)


def test_verify_binds_final_reads_to_the_opening_member_identity(
    exported_bundle: ExportedBundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_directory = exported_bundle[0]
    original_read = run_bundle_module._read_stable_member
    read_calls = 0

    def replace_before_final_sidecar_read(
        path: Path,
        *,
        expected_identity: tuple[int, int],
        posix_guard: run_bundle_module._PosixMemberGuard | None = None,
    ) -> bytes:
        nonlocal read_calls
        read_calls += 1
        if read_calls == 4:
            same_bytes = path.read_bytes()
            path.unlink()
            path.write_bytes(same_bytes)
        return original_read(
            path,
            expected_identity=expected_identity,
            posix_guard=posix_guard,
        )

    monkeypatch.setattr(
        run_bundle_module,
        "_read_stable_member",
        replace_before_final_sidecar_read,
    )
    with pytest.raises(RunBundleVerificationError, match="member identity changed"):
        verify_run_bundle(bundle_directory)

    assert read_calls == 4


def test_verify_rechecks_reparse_ancestry_after_final_member_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = tmp_path / "identity-container"
    container.mkdir()
    bundle_directory = _export(container, "bundle")[0]
    moved_container = tmp_path / "identity-container-moved"
    original_read = run_bundle_module._read_stable_member
    read_calls = 0
    ancestry_swapped = False
    ancestry_swap_blocked = False

    def swap_ancestor_after_final_read(
        path: Path,
        *,
        expected_identity: tuple[int, int],
        posix_guard: run_bundle_module._PosixMemberGuard | None = None,
    ) -> bytes:
        nonlocal read_calls, ancestry_swapped, ancestry_swap_blocked
        content = original_read(
            path,
            expected_identity=expected_identity,
            posix_guard=posix_guard,
        )
        read_calls += 1
        if read_calls == 4:
            try:
                container.rename(moved_container)
            except OSError:
                ancestry_swap_blocked = True
                return content
            if os.name == "nt":
                created = subprocess.run(
                    ["cmd.exe", "/d", "/c", "mklink", "/J", str(container), str(moved_container)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                assert created.returncode == 0, created.stderr
            else:
                container.symlink_to(moved_container, target_is_directory=True)
            ancestry_swapped = True
        return content

    monkeypatch.setattr(run_bundle_module, "_read_stable_member", swap_ancestor_after_final_read)
    try:
        try:
            result = verify_run_bundle(bundle_directory)
        except RunBundleVerificationError as exc:
            assert ancestry_swapped is True
            assert "must not traverse" in str(exc) or "ancestry changed" in str(exc)
        else:
            assert result.valid is True
            assert ancestry_swap_blocked is True
    finally:
        if ancestry_swapped:
            if container.is_symlink():
                container.unlink()
            else:
                container.rmdir()
            moved_container.rename(container)

    assert read_calls == 4


def test_export_close_failure_after_successful_rename_rolls_back_final(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "close-failure"
    original_close = run_bundle_module._close_directory_guard
    original_publish = run_bundle_module._publish_directory_no_replace
    publication_guard: object | None = None
    injected = False

    def capture_publication_guard(
        source: Path,
        published_destination: Path,
        *,
        expected_identity: tuple[int, int],
    ) -> object:
        nonlocal publication_guard
        publication_guard = original_publish(
            source,
            published_destination,
            expected_identity=expected_identity,
        )
        return publication_guard

    def close_then_raise(guard: object) -> None:
        nonlocal injected
        try:
            original_close(cast(Any, guard))
        finally:
            if guard is publication_guard and not injected:
                injected = True
                raise OSError("injected close failure after publication")

    monkeypatch.setattr(
        run_bundle_module,
        "_publish_directory_no_replace",
        capture_publication_guard,
    )
    monkeypatch.setattr(run_bundle_module, "_close_directory_guard", close_then_raise)
    with pytest.raises(RunBundleValidationError, match="failed after publication"):
        export_run_bundle(destination, trace=_trace(_spec()))

    assert injected is True
    assert not destination.exists()
    assert list(tmp_path.glob(".close-failure.tmp-*")) == []


@pytest.mark.skipif(os.name != "nt", reason="exercises the Windows native handle guard")
def test_directory_guard_closes_on_baseexception_during_acquisition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "guarded"
    directory.mkdir()
    expected_identity = run_bundle_module._physical_identity(directory.lstat())
    original_open = run_bundle_module._open_windows_directory_handle
    opened_handles: list[int] = []

    def record_open(path: Path, *, desired_access: int, share_mode: int) -> int:
        handle = original_open(
            path,
            desired_access=desired_access,
            share_mode=share_mode,
        )
        opened_handles.append(handle)
        return handle

    def interrupt_identity(_handle: int) -> tuple[int, int]:
        raise KeyboardInterrupt

    monkeypatch.setattr(run_bundle_module, "_open_windows_directory_handle", record_open)
    monkeypatch.setattr(run_bundle_module, "_windows_directory_handle_identity", interrupt_identity)
    with pytest.raises(KeyboardInterrupt):
        run_bundle_module._open_directory_guard(
            directory,
            expected_identity=expected_identity,
        )

    assert len(opened_handles) == 1
    with pytest.raises(OSError):
        run_bundle_module._close_windows_handle(opened_handles[0])


@pytest.mark.skipif(os.name != "nt", reason="exercises Windows handle-targeted deletion")
def test_handle_cleanup_never_deletes_a_foreign_path_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned = tmp_path / "owned.txt"
    owned.write_bytes(b"owned\n")
    expected_identity = run_bundle_module._physical_identity(owned.lstat())
    foreign = tmp_path / "foreign.txt"
    foreign_bytes = b"operator owned\n"
    foreign.write_bytes(foreign_bytes)
    original_information = run_bundle_module._windows_handle_information
    replaced = False
    replacement_blocked = False

    def replace_after_handle_binding(handle: int) -> tuple[tuple[int, int], int, int]:
        nonlocal replaced, replacement_blocked
        information = original_information(handle)
        if not replaced and not replacement_blocked:
            try:
                os.replace(foreign, owned)
            except OSError:
                replacement_blocked = True
            else:
                replaced = True
        return information

    monkeypatch.setattr(
        run_bundle_module,
        "_windows_handle_information",
        replace_after_handle_binding,
    )
    run_bundle_module._remove_owned_replay_database(
        owned,
        expected_identity=expected_identity,
    )

    assert replaced is not replacement_blocked
    if replaced:
        assert owned.read_bytes() == foreign_bytes
    else:
        assert not owned.exists()
        assert foreign.read_bytes() == foreign_bytes


@pytest.mark.skipif(os.name != "nt", reason="exercises Windows volume-bound identity")
def test_windows_cleanup_rejects_a_same_index_identity_from_another_volume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned = tmp_path / "owned-volume-bound.txt"
    owned_bytes = b"owned but volume bound\n"
    owned.write_bytes(owned_bytes)
    expected_identity = run_bundle_module._physical_identity(owned.lstat())
    original_information = run_bundle_module._windows_handle_information

    def report_other_volume(handle: int) -> tuple[tuple[int, int], int, int]:
        identity, attributes, links = original_information(handle)
        return ((identity[0] ^ 1, identity[1]), attributes, links)

    monkeypatch.setattr(
        run_bundle_module,
        "_windows_handle_information",
        report_other_volume,
    )
    removed = run_bundle_module._remove_owned_replay_database(
        owned,
        expected_identity=expected_identity,
    )

    assert removed is False
    assert owned.read_bytes() == owned_bytes


def test_ancestry_guard_blocks_or_detects_an_alias_swap(tmp_path: Path) -> None:
    container = tmp_path / "snapshot-container"
    bundle = container / "bundle"
    bundle.mkdir(parents=True)
    moved_container = tmp_path / "snapshot-container-moved"
    swapped = False
    blocked = False
    guard = run_bundle_module._open_ancestry_guard(bundle, label="RunBundle root")
    try:
        try:
            container.rename(moved_container)
        except OSError:
            blocked = True
        else:
            if os.name == "nt":
                created = subprocess.run(
                    ["cmd.exe", "/d", "/c", "mklink", "/J", str(container), str(moved_container)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                assert created.returncode == 0, created.stderr
            else:
                container.symlink_to(moved_container, target_is_directory=True)
            swapped = True
            with pytest.raises(RunBundleVerificationError, match="ancestry changed"):
                run_bundle_module._require_ancestry_guard(guard, label="RunBundle root")
    finally:
        run_bundle_module._close_ancestry_guard(guard)
        if swapped:
            if container.is_symlink():
                container.unlink()
            else:
                container.rmdir()
            moved_container.rename(container)

    assert blocked is not swapped
    if os.name == "nt":
        assert blocked is True


@pytest.mark.skipif(os.name != "nt", reason="exercises Windows immediate unlink semantics")
def test_windows_owned_cleanup_does_not_depend_on_the_disposition_handle_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned = tmp_path / "owned-close-pending.txt"
    owned.write_bytes(b"owned\n")
    expected_identity = run_bundle_module._physical_identity(owned.lstat())
    original_close = run_bundle_module._close_windows_handle
    leaked_handles: list[int] = []

    def leave_handle_open(handle: int) -> None:
        leaked_handles.append(handle)
        raise OSError("injected persistent CloseHandle failure")

    monkeypatch.setattr(run_bundle_module, "_close_windows_handle", leave_handle_open)
    try:
        removed = run_bundle_module._remove_owned_replay_database(
            owned,
            expected_identity=expected_identity,
        )
        assert removed is False
        assert os.path.lexists(owned)
    finally:
        for handle in leaked_handles:
            original_close(handle)
    assert not os.path.lexists(owned)
