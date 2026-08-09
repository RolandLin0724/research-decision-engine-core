from __future__ import annotations

import hashlib
import json
import math
import statistics
import struct
from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from functools import cache
from pathlib import Path
from typing import Any, cast

import pytest

import research_decision_engine.benchmarks.broader_artifact_graph as artifact_graph_module
import research_decision_engine.benchmarks.broader_artifacts as artifact_module
import research_decision_engine.benchmarks.broader_assembly as assembly_module
from research_decision_engine.benchmarks.broader_artifact_graph import (
    CanonicalArtifactGraph,
    decode_and_validate_artifacts,
    decode_and_validate_audited_artifacts,
    decode_and_validate_prefinal_artifacts,
    validate_artifact_graph,
)
from research_decision_engine.benchmarks.broader_artifacts import (
    ARM_RUN_FIELDS,
    CALIBRATION_FIELD_ORDER,
    CALIBRATION_FIELDS,
    METRIC_SET_FIELDS,
    ArtifactValidationError,
    artifact_contracts,
    serialize_json_artifact,
    serialize_jsonl_artifact,
    validate_canonical_event_row,
    validate_canonical_rows,
    validate_comparison_record,
    validate_oracle_record,
    validate_resampling_record,
)
from research_decision_engine.benchmarks.broader_assembly import (
    assemble_prefinalization_artifacts,
    finalize_validation_artifacts,
)
from research_decision_engine.benchmarks.broader_audits import FinalizationAuthorization
from research_decision_engine.benchmarks.broader_conformance import (
    CONFORMANCE_PROFILE,
    DiagnosticConformanceFixture,
)
from research_decision_engine.benchmarks.broader_protocol import (
    canonical_json_bytes,
    f64,
    protocol_hash,
)
from research_decision_engine.benchmarks.broader_runner import (
    BroaderArmRun,
    reconstruct_complete_calibration_claim,
)
from tests.test_broader_oracle_support import ConformanceOracleSupport


@pytest.fixture(scope="module")
def conformance_graph(
    tmp_path_factory: pytest.TempPathFactory,
    conformance_oracle_support: ConformanceOracleSupport,
) -> CanonicalArtifactGraph:
    target = tmp_path_factory.mktemp("conformance-graph") / "canonical"
    plan, operational, authorization = conformance_oracle_support.payloads(target)
    artifacts = finalize_validation_artifacts(
        target,
        plan,
        operational,
        authorization,
        profile=CONFORMANCE_PROFILE,
    )
    return decode_and_validate_artifacts(
        artifacts,
        artifact_contracts(),
        profile=CONFORMANCE_PROFILE,
    )


def _valid_calibration_record() -> dict[str, object]:
    return {
        "sigma_estimate_id": "sigma-estimate/calibration-prefix/world/1000/group-00",
        "calibration_prefix_id": "calibration-prefix/world/1000/group-00",
        "world_id": "world",
        "seed": 1000,
        "comparison_group_id": "group-00",
        "effect_ids": [f"effect/{index}" for index in range(5)],
        "replication_ids": [f"replication/{index}" for index in range(5)],
        "source_candidate_pairs": [
            [f"candidate/{2 * index}", f"candidate/{2 * index + 1}"] for index in range(5)
        ],
        "source_oracle_key_ids": [f"oracle-key/{index}" for index in range(10)],
        "effect_values": [f64(float(index)) for index in range(5)],
        "sample_count": 5,
        "sample_mean": f64(2.0),
        "sample_standard_deviation": f64(1.0),
        "sigma_floor": f64(0.05),
        "estimated_sigma": f64(1.0),
        "target_belief_model_id": "replicated_noise_calibrated_gaussian",
        "target_comparison_group_id": "group-00",
        "target_intervention_arms": ["adam", "sgd"],
        "physical_cost": f64(10.0),
        "deployment_cost": f64(10.0),
        "deployed_run_ids": [f"run/{index}" for index in range(6)],
        "deployed_lineage_ids": [f"lineage/run/{index}" for index in range(6)],
        "scientific_belief_updated": False,
    }


@cache
def _minimal_calibration_runs() -> tuple[BroaderArmRun, ...]:
    from research_decision_engine.benchmarks.broader_oracle import ObservationAuthority
    from research_decision_engine.benchmarks.broader_runner import arm_spec, run_arm
    from research_decision_engine.benchmarks.broader_worlds import BUDGETS, WORLDS_BY_ID

    world = WORLDS_BY_ID["g_adam_lmh"]
    return tuple(
        run_arm(
            arm=arm_spec(arm_id),
            world=world.public,
            seed=9000,
            budget_id=budget_id,
            budget=budget,
            authority=ObservationAuthority(world=world, seed=9000),
        )
        for budget_id, budget in BUDGETS
        for arm_id in (
            "fixed_ig",
            "calibrated_ig",
            "fixed_lookahead",
            "calibrated_lookahead",
        )
    )


@cache
def _minimal_calibration_graph_rows() -> tuple[
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
]:
    from research_decision_engine.benchmarks.broader_projection import (
        _calibration_rows,
        _oracle_rows,
        _run_and_event_rows,
    )

    runs = _minimal_calibration_runs()
    run_rows, event_rows = _run_and_event_rows(runs)
    return _calibration_rows(runs), run_rows, _oracle_rows(runs), event_rows


def test_all_13_artifact_contracts_have_frozen_order_and_versions() -> None:
    contracts = artifact_contracts()
    assert tuple((item.filename, item.schema_version) for item in contracts) == (
        ("protocol_snapshot.json", "protocol-snapshot/v4"),
        ("world_definitions.json", "world-definitions/v2"),
        ("arm_runs.jsonl", "arm-run/v2"),
        ("oracle_provenance.jsonl", "oracle-provenance/v3"),
        ("calibration_estimates.jsonl", "calibration-estimate/v2"),
        ("trajectory_events.jsonl", "trajectory-event/v3"),
        ("comparisons.jsonl", "comparison/v3"),
        ("contrast_results.csv", "contrast-result/v3"),
        ("resampling_audit.jsonl", "resampling-audit/v2"),
        ("gate_evaluations.json", "gate-evaluation/v5"),
        ("audit_results.json", "audit-result/v3"),
        ("run_manifest.json", "run-manifest/v3"),
        ("recommendation.json", "recommendation/v4"),
    )
    assert len(contracts) == 13
    assert tuple(item.order for item in contracts) == tuple(range(1, 14))
    assert contracts[0].filename == "protocol_snapshot.json"
    assert contracts[-1].filename == "recommendation.json"
    assert len({item.schema_version for item in contracts}) == 13
    assert all(item.record_contract is not None for item in contracts)


@pytest.mark.artifact5
def test_calibration_artifact_restores_exact_frozen_schema_and_bytes(
    conformance_graph: CanonicalArtifactGraph,
) -> None:
    rows = cast(
        tuple[dict[str, object], ...],
        conformance_graph.artifact("calibration_estimates.jsonl").scientific,
    )
    assert rows
    frozen_fields = (
        "sigma_estimate_id",
        "calibration_prefix_id",
        "world_id",
        "seed",
        "comparison_group_id",
        "effect_ids",
        "replication_ids",
        "source_candidate_pairs",
        "source_oracle_key_ids",
        "effect_values",
        "sample_count",
        "sample_mean",
        "sample_standard_deviation",
        "sigma_floor",
        "estimated_sigma",
        "target_belief_model_id",
        "target_comparison_group_id",
        "target_intervention_arms",
        "physical_cost",
        "deployment_cost",
        "deployed_run_ids",
        "deployed_lineage_ids",
        "scientific_belief_updated",
    )
    assert frozen_fields == CALIBRATION_FIELD_ORDER
    assert frozenset(frozen_fields) == CALIBRATION_FIELDS
    assert len(rows[0]) == 23
    assert set(rows[0]) == set(frozen_fields)
    contract = next(
        item for item in artifact_contracts() if item.filename == "calibration_estimates.jsonl"
    )
    assert contract.schema_version == "calibration-estimate/v2"
    validate_canonical_rows(contract, [rows[0]])
    first = serialize_jsonl_artifact(
        schema_version=contract.schema_version,
        source_design_sha256="0" * 64,
        rows=[rows[0]],
    )
    second = serialize_jsonl_artifact(
        schema_version=contract.schema_version,
        source_design_sha256="0" * 64,
        rows=[deepcopy(rows[0])],
    )
    assert first == second
    assert json.loads(first.splitlines()[1]) == rows[0]
    serialized_pairs = json.loads(
        first.splitlines()[1],
        object_pairs_hook=lambda pairs: pairs,
    )
    serialized_fields = tuple(cast(str, key) for key, _ in serialized_pairs)
    assert serialized_fields == tuple(
        sorted(frozen_fields, key=lambda field: field.encode("utf-8"))
    )
    assert serialized_fields != CALIBRATION_FIELD_ORDER


@pytest.mark.artifact5
def test_calibration_artifact_has_a_golden_canonical_serialization_hash() -> None:
    content = serialize_jsonl_artifact(
        schema_version="calibration-estimate/v2",
        source_design_sha256="0" * 64,
        rows=[_valid_calibration_record()],
    )
    assert hashlib.sha256(content).hexdigest() == (
        "c5db811d319683b15a227cae5f973f03af70cc0bf0feebd399d7b3d2f669e613"
    )


@pytest.mark.actual_state_provenance
def test_manifest_false_clean_reaches_operational_graph_guard(
    conformance_graph: CanonicalArtifactGraph,
    tmp_path: Path,
) -> None:
    manifest = conformance_graph.artifact("run_manifest.json")
    operational = dict(manifest.operational)
    operational["implementation_tree_clean"] = False
    mutated_manifest = replace(manifest, operational=operational)
    mutated_graph = replace(
        conformance_graph,
        artifacts=tuple(
            mutated_manifest if artifact is manifest else artifact
            for artifact in conformance_graph.artifacts
        ),
    )
    with pytest.raises(ArtifactValidationError) as captured:
        artifact_graph_module._validate_operational_finalization_fields(mutated_graph)
    assert type(captured.value).__name__ == "ArtifactValidationError"
    assert str(captured.value) == ("Manifest requires an actually clean implementation tree.")
    assert not (tmp_path / "canonical").exists()


@pytest.mark.artifact5
@pytest.mark.parametrize(
    "field",
    (
        "source_effect_ids",
        "source_sequence_cutoff",
        "raw_sample_standard_deviation",
        "ddof",
        "estimator_version",
        "belief_model_id",
        "lineage_id",
        "provenance_sha256",
    ),
)
def test_calibration_artifact_rejects_each_undeclared_field(
    field: str,
    conformance_graph: CanonicalArtifactGraph,
) -> None:
    row = deepcopy(
        cast(
            tuple[dict[str, object], ...],
            conformance_graph.artifact("calibration_estimates.jsonl").scientific,
        )[0]
    )
    row[field] = "forbidden"
    contract = next(
        item for item in artifact_contracts() if item.filename == "calibration_estimates.jsonl"
    )
    with pytest.raises(ArtifactValidationError) as captured:
        validate_canonical_rows(contract, [row])
    assert type(captured.value).__name__ == "ArtifactValidationError"
    assert str(captured.value) == (
        "calibration_estimates.jsonl[0] fields differ from contract; "
        f"missing=[], extra=['{field}']."
    )


@pytest.mark.artifact5
def test_calibration_artifact_rejects_an_arbitrary_unknown_24th_field() -> None:
    row = _valid_calibration_record()
    row["future_extension"] = "forbidden"
    contract = next(
        item for item in artifact_contracts() if item.filename == "calibration_estimates.jsonl"
    )
    with pytest.raises(ArtifactValidationError) as captured:
        validate_canonical_rows(contract, [row])
    assert type(captured.value).__name__ == "ArtifactValidationError"
    assert str(captured.value) == (
        "calibration_estimates.jsonl[0] fields differ from contract; "
        "missing=[], extra=['future_extension']."
    )


@pytest.mark.artifact5
@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("effect_ids", tuple(f"effect/{index}" for index in range(5))),
        ("replication_ids", tuple(f"replication/{index}" for index in range(5))),
        ("source_candidate_pairs", tuple([["candidate/0", "candidate/1"]] * 5)),
        ("source_oracle_key_ids", tuple(f"oracle-key/{index}" for index in range(10))),
        ("effect_values", tuple(f64(float(index)) for index in range(5))),
        ("target_intervention_arms", ("adam", "sgd")),
        ("deployed_run_ids", tuple(f"run/{index}" for index in range(6))),
        ("deployed_lineage_ids", tuple(f"lineage/run/{index}" for index in range(6))),
        ("effect_ids", ["effect/0"] * 4),
        ("effect_ids", ["effect/0"] * 5),
        ("effect_ids", [0, "effect/1", "effect/2", "effect/3", "effect/4"]),
        ("replication_ids", ["replication/0"] * 4),
        ("replication_ids", ["replication/0"] * 5),
        ("source_candidate_pairs", [["candidate/0", "candidate/1"]] * 4),
        (
            "source_candidate_pairs",
            [
                ["candidate/0"],
                *[[f"candidate/{2 * i}", f"candidate/{2 * i + 1}"] for i in range(1, 5)],
            ],
        ),
        (
            "source_candidate_pairs",
            [
                [0, "candidate/1"],
                *[[f"candidate/{2 * i}", f"candidate/{2 * i + 1}"] for i in range(1, 5)],
            ],
        ),
        ("source_candidate_pairs", [["candidate/0", "candidate/1"]] * 5),
        ("source_oracle_key_ids", ["oracle-key/0"] * 9),
        ("source_oracle_key_ids", ["oracle-key/0"] * 10),
        ("effect_values", [f64(0.0)] * 4),
        ("effect_values", ["0.0", *[f64(float(index)) for index in range(1, 5)]]),
        ("effect_values", [0.0, *[f64(float(index)) for index in range(1, 5)]]),
        ("target_intervention_arms", ["sgd", "adam"]),
        ("deployed_run_ids", ["run/0"] * 5),
        ("deployed_run_ids", ["run/0"] * 6),
        ("deployed_lineage_ids", ["lineage/run/0"] * 5),
        ("deployed_lineage_ids", ["lineage/run/0"] * 6),
        ("sample_count", 4),
        ("sigma_floor", f64(0.06)),
        ("target_belief_model_id", "fixed_sigma_gaussian"),
        ("target_comparison_group_id", "group-01"),
        ("scientific_belief_updated", True),
    ),
)
def test_calibration_frozen_reader_rejects_malformed_type_or_cardinality(
    field: str, replacement: object
) -> None:
    row = _valid_calibration_record()
    row[field] = deepcopy(replacement)
    contract = next(
        item for item in artifact_contracts() if item.filename == "calibration_estimates.jsonl"
    )
    with pytest.raises(ArtifactValidationError):
        validate_canonical_rows(contract, [row])


@pytest.mark.artifact5
@pytest.mark.sigma_reconstruction
@pytest.mark.parametrize(
    "field",
    CALIBRATION_FIELD_ORDER,
)
def test_calibration_artifact_rejects_each_complete_sigma_claim_mutation(
    field: str,
) -> None:
    from research_decision_engine.benchmarks.broader_artifact_graph import (
        _validate_calibration,
    )

    source_rows, run_rows, oracle_rows, event_rows = _minimal_calibration_graph_rows()
    rows = deepcopy(list(source_rows))
    row = rows[0]
    if field == "seed" or field == "sample_count":
        row[field] = cast(int, row[field]) + 1
    elif field in {
        "sample_mean",
        "sample_standard_deviation",
        "sigma_floor",
        "estimated_sigma",
        "physical_cost",
        "deployment_cost",
    }:
        row[field] = f64(99.0)
    elif field == "effect_values":
        values = cast(list[object], row[field])
        row[field] = [f64(99.0), *values[1:]]
    elif field == "target_belief_model_id":
        row[field] = "fixed_sigma_gaussian"
    elif field == "scientific_belief_updated":
        row[field] = True
    elif isinstance(row[field], list):
        row[field] = list(reversed(cast(list[object], row[field])))
    else:
        row[field] = f"{row[field]}/changed"

    with pytest.raises(ArtifactValidationError):
        _validate_calibration(tuple(rows), run_rows, oracle_rows, event_rows)


@pytest.mark.artifact5
@pytest.mark.sigma_reconstruction
@pytest.mark.parametrize("mutation", ("population_ddof", "coherent_effect_order"))
def test_calibration_semantic_mutations_reach_independent_reconstruction_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    from research_decision_engine.benchmarks.broader_artifact_graph import (
        _validate_calibration,
    )

    source_rows, run_rows, oracle_rows, event_rows = _minimal_calibration_graph_rows()
    rows = deepcopy(list(source_rows))
    row = rows[0]
    if mutation == "population_ddof":
        values = [
            struct.unpack(">d", bytes.fromhex(value[4:]))[0]
            for value in cast(list[str], row["effect_values"])
        ]
        mean = math.fsum(values) / len(values)
        population_sd = math.sqrt(math.fsum((value - mean) ** 2 for value in values) / len(values))
        row["sample_standard_deviation"] = f64(population_sd)
        row["estimated_sigma"] = f64(max(population_sd, 0.05))
    else:
        for field in (
            "effect_ids",
            "replication_ids",
            "source_candidate_pairs",
            "effect_values",
        ):
            row[field] = list(reversed(cast(list[object], row[field])))
        key_ids = cast(list[object], row["source_oracle_key_ids"])
        key_pairs = [key_ids[index : index + 2] for index in range(0, len(key_ids), 2)]
        row["source_oracle_key_ids"] = [key for pair in reversed(key_pairs) for key in pair]

    reconstruction_called = False
    original = reconstruct_complete_calibration_claim

    def record_reconstruction(*args: object, **kwargs: object) -> object:
        nonlocal reconstruction_called
        reconstruction_called = True
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        artifact_graph_module,
        "reconstruct_complete_calibration_claim",
        record_reconstruction,
    )
    with pytest.raises(ArtifactValidationError) as captured:
        _validate_calibration(tuple(rows), run_rows, oracle_rows, event_rows)
    assert type(captured.value).__name__ == "ArtifactValidationError"
    assert str(captured.value) == (
        "Persisted calibration estimate differs from independent reconstruction."
    )
    assert reconstruction_called is True
    assert not (tmp_path / "canonical").exists()


@pytest.mark.artifact5
def test_calibration_projection_is_order_independent_and_owns_full_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_decision_engine.benchmarks.broader_projection as projection_module
    from research_decision_engine.benchmarks.broader_projection import (
        _calibration_rows,
        _run_and_event_rows,
    )
    from research_decision_engine.benchmarks.broader_runner import (
        CalibrationDeploymentBinding,
        RunProvenanceError,
    )
    from research_decision_engine.benchmarks.broader_worlds import WORLDS_BY_ID

    projection_runs = _minimal_calibration_runs()
    input_orders = (
        projection_runs,
        tuple(reversed(projection_runs)),
        (*projection_runs[2::3], *projection_runs[0::3], *projection_runs[1::3]),
        (*projection_runs[1::2], *projection_runs[0::2]),
    )
    projected = tuple(_calibration_rows(order) for order in input_orders)
    forward = projected[0]
    assert all(rows == forward for rows in projected[1:])
    assert all(tuple(row) == CALIBRATION_FIELD_ORDER for row in forward)
    run_lineages = {item.run_id: item.lineage.lineage_id for item in projection_runs}
    for row in forward:
        deployed_runs = cast(list[str], row["deployed_run_ids"])
        deployed_lineages = cast(list[str], row["deployed_lineage_ids"])
        assert len(deployed_runs) == len(set(deployed_runs)) == 6
        assert deployed_lineages == [run_lineages[run_id] for run_id in deployed_runs]
        effect_values = [
            struct.unpack(">d", bytes.fromhex(value[4:]))[0]
            for value in cast(list[str], row["effect_values"])
        ]
        sample_sd = struct.unpack(
            ">d", bytes.fromhex(cast(str, row["sample_standard_deviation"])[4:])
        )[0]
        assert sample_sd == statistics.stdev(effect_values)
    first_bytes = serialize_jsonl_artifact(
        schema_version="calibration-estimate/v2",
        source_design_sha256="0" * 64,
        rows=forward,
    )
    serialized = tuple(
        serialize_jsonl_artifact(
            schema_version="calibration-estimate/v2",
            source_design_sha256="0" * 64,
            rows=rows,
        )
        for rows in projected
    )
    assert all(content == first_bytes for content in serialized)

    run_and_event_rows = _run_and_event_rows(projection_runs)
    monkeypatch.setattr(
        projection_module,
        "WORLDS_BY_ID",
        dict(reversed(tuple(WORLDS_BY_ID.items()))),
    )
    assert _calibration_rows(tuple(reversed(projection_runs))) == forward
    assert _run_and_event_rows(tuple(reversed(projection_runs))) == run_and_event_rows

    anchor = next(item for item in projection_runs if item.calibration is not None)
    shared_runs = tuple(
        item
        for item in projection_runs
        if item.world_id == anchor.world_id and item.seed == anchor.seed
    )
    calibrated = tuple(item for item in shared_runs if item.calibration is not None)
    assert len(calibrated) == 6
    bindings = tuple(
        CalibrationDeploymentBinding(
            run_id=run.run_id,
            lineage_id=run.lineage.lineage_id,
            world_id=run.world_id,
            seed=run.seed,
            budget_id=run.budget_id,
            arm_id=run.arm.arm_id,
            belief_model_id=run.arm.belief_model_id,
            calibration_prefix_ids=tuple(
                estimate.calibration_prefix_id for estimate in run.calibration.estimates
            ),
        )
        for run in calibrated
        if run.calibration is not None
    )
    first_calibration = calibrated[0].calibration
    assert first_calibration is not None
    group_id = first_calibration.estimates[0].comparison_group_id
    observations = {
        run.run_id: run.calibration.estimates[0].observations
        for run in calibrated
        if run.calibration is not None
    }
    baseline_claim = reconstruct_complete_calibration_claim(
        world_id=anchor.world_id,
        seed=anchor.seed,
        comparison_group_id=group_id,
        deployment_bindings=bindings,
        recorded_observations_by_run=observations,
    )
    with pytest.raises(RunProvenanceError, match="complete six-run protocol vector"):
        reconstruct_complete_calibration_claim(
            world_id=anchor.world_id,
            seed=anchor.seed,
            comparison_group_id=group_id,
            deployment_bindings=bindings[:-1],
        )
    with pytest.raises(RunProvenanceError, match="complete six-run protocol vector"):
        reconstruct_complete_calibration_claim(
            world_id=anchor.world_id,
            seed=anchor.seed,
            comparison_group_id=group_id,
            deployment_bindings=(*bindings[:-1], bindings[0]),
        )
    crossed_lineage = replace(bindings[0], lineage_id="lineage/foreign-run")
    with pytest.raises(RunProvenanceError, match="binding differs from the protocol"):
        reconstruct_complete_calibration_claim(
            world_id=anchor.world_id,
            seed=anchor.seed,
            comparison_group_id=group_id,
            deployment_bindings=(crossed_lineage, *bindings[1:]),
        )
    worker_orders = (
        (2, 5, 0, 4, 1, 3),
        (4, 1, 5, 0, 3, 2),
    )
    observation_orders = (
        (3, 0, 5, 1, 4, 2),
        (1, 4, 2, 5, 0, 3),
    )
    for worker_order, observation_order in zip(worker_orders, observation_orders, strict=True):
        reconstructed = reconstruct_complete_calibration_claim(
            world_id=anchor.world_id,
            seed=anchor.seed,
            comparison_group_id=group_id,
            deployment_bindings=tuple(bindings[index] for index in worker_order),
            recorded_observations_by_run={
                calibrated[index].run_id: observations[calibrated[index].run_id]
                for index in observation_order
            },
        )
        assert reconstructed == baseline_claim
        assert reconstructed.artifact_row() == baseline_claim.artifact_row()

    import research_decision_engine.benchmarks.broader_runner as runner_module

    original_reconstruction = runner_module.reconstruct_calibration_sources
    divergent_run_id = baseline_claim.deployed_run_ids[-1]

    def divergent_worker(**kwargs: object) -> object:
        reconstructed = original_reconstruction(**kwargs)  # type: ignore[arg-type]
        if kwargs["run_id"] == divergent_run_id:
            return replace(reconstructed, sample_mean=reconstructed.sample_mean + 1.0)
        return reconstructed

    monkeypatch.setattr(runner_module, "reconstruct_calibration_sources", divergent_worker)
    with pytest.raises(
        RunProvenanceError,
        match="sources differ across the shared deployment vector",
    ):
        reconstruct_complete_calibration_claim(
            world_id=anchor.world_id,
            seed=anchor.seed,
            comparison_group_id=group_id,
            deployment_bindings=bindings,
            recorded_observations_by_run=observations,
        )


@pytest.mark.oracle_reconstruction
def test_coherent_calibration_source_rewrite_fails_oracle_reobservation(
    conformance_graph: CanonicalArtifactGraph,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = _graph_scientific_claims(conformance_graph)
    calibration_rows = deepcopy(
        list(cast(tuple[dict[str, object], ...], payloads["calibration_estimates.jsonl"]))
    )
    oracle_rows = deepcopy(
        list(cast(tuple[dict[str, object], ...], payloads["oracle_provenance.jsonl"]))
    )
    calibration = calibration_rows[0]
    source_ids = cast(list[str], calibration["source_oracle_key_ids"])
    source_rows = {
        row["oracle_key_id"]: row
        for row in oracle_rows
        if row["record_type"] == "oracle_key" and row["oracle_key_id"] in source_ids
    }

    def decode(value: object) -> float:
        assert isinstance(value, str)
        return float(struct.unpack(">d", bytes.fromhex(value[4:]))[0])

    changed_source_id = source_ids[0]
    changed_source = source_rows[changed_source_id]
    changed_source["revealed_observation"] = f64(
        decode(changed_source["revealed_observation"]) + 1.0
    )
    changed_source["outcome_digest"] = protocol_hash(
        "revealed_outcome/v1",
        {
            "oracle_key_id": changed_source["oracle_key_id"],
            "revealed_observation": changed_source["revealed_observation"],
        },
    )
    affected_calibrations = 0
    for current in calibration_rows:
        current_source_ids = cast(list[str], current["source_oracle_key_ids"])
        if changed_source_id not in current_source_ids:
            continue
        affected_calibrations += 1
        source_position = current_source_ids.index(changed_source_id)
        effect_position = source_position // 2
        left_id, right_id = current_source_ids[2 * effect_position : 2 * effect_position + 2]
        values = [decode(value) for value in cast(list[object], current["effect_values"])]
        values[effect_position] = round(
            decode(source_rows[left_id]["revealed_observation"])
            - decode(source_rows[right_id]["revealed_observation"]),
            12,
        )
        sample_sd = statistics.stdev(values)
        current["effect_values"] = [f64(value) for value in values]
        current["sample_mean"] = f64(statistics.mean(values))
        current["sample_standard_deviation"] = f64(sample_sd)
        current["estimated_sigma"] = f64(max(sample_sd, 0.05))
    assert affected_calibrations > 0

    arm_rows = list(cast(tuple[dict[str, object], ...], payloads["arm_runs.jsonl"]))
    lineage_by_run = {cast(str, row["run_id"]): row["lineage_id"] for row in arm_rows}
    for current in calibration_rows:
        deployed_runs = cast(list[str], current["deployed_run_ids"])
        deployed_lineages = cast(list[str], current["deployed_lineage_ids"])
        deployment_pairs = list(zip(deployed_runs, deployed_lineages, strict=True))
        rotated_pairs = (*deployment_pairs[1:], deployment_pairs[0])
        current["deployed_run_ids"] = [run_id for run_id, _ in rotated_pairs]
        current["deployed_lineage_ids"] = [lineage_id for _, lineage_id in rotated_pairs]
        assert current["deployed_run_ids"] != deployed_runs
        assert all(lineage_by_run[run_id] == lineage_id for run_id, lineage_id in rotated_pairs)
    event_rows = deepcopy(
        list(cast(tuple[dict[str, object], ...], payloads["trajectory_events.jsonl"]))
    )
    # Mutate an ordinary event ownership field, then update both its provenance and the
    # owning run's trajectory hash. The later event-ownership validator would reject this
    # foreign lineage, but the independent Oracle check must reject the source rewrite first.
    changed_event = event_rows[0]
    changed_event_payload = _event_payload(changed_event)
    owning_run_id = cast(str, changed_event_payload["run_id"])
    owning_run = next(row for row in arm_rows if row["run_id"] == owning_run_id)
    original_event_lineage = cast(str, changed_event_payload["belief_lineage_id"])
    foreign_event_lineage = next(
        cast(str, row["lineage_id"]) for row in arm_rows if row["run_id"] != owning_run_id
    )
    changed_event_payload["belief_lineage_id"] = foreign_event_lineage
    old_event_provenance = changed_event["provenance_sha256"]
    _rehash_event(changed_event)
    assert foreign_event_lineage != original_event_lineage
    assert changed_event["provenance_sha256"] != old_event_provenance

    event_by_id = {cast(str, _event_payload(row)["event_id"]): row for row in event_rows}
    owned_events = [event_by_id[event_id] for event_id in cast(list[str], owning_run["event_ids"])]
    owning_run["trajectory_sha256"] = protocol_hash(
        "trajectory/v1",
        {
            "run_id": owning_run_id,
            "ordered_decisions_sha256": owning_run["ordered_decisions_sha256"],
            "ordered_real_event_ids": [_event_payload(row)["event_id"] for row in owned_events],
            "ordered_event_provenance_sha256": [row["provenance_sha256"] for row in owned_events],
            "terminal_reason": owning_run["terminal_reason"],
            "reconciliation_sha256": owning_run["reconciliation_sha256"],
        },
    )
    payloads["arm_runs.jsonl"] = tuple(arm_rows)
    payloads["calibration_estimates.jsonl"] = tuple(calibration_rows)
    payloads["oracle_provenance.jsonl"] = tuple(oracle_rows)
    payloads["trajectory_events.jsonl"] = tuple(event_rows)

    mutated_graph = _replace_graph_scientific(conformance_graph, payloads)
    source_design_sha256 = cast(
        str,
        json.loads(conformance_graph.artifact("oracle_provenance.jsonl").content.splitlines()[0])[
            "source_design_sha256"
        ],
    )
    replacements: dict[str, tuple[bytes, bytes]] = {}
    for filename, rows in (
        ("arm_runs.jsonl", arm_rows),
        ("oracle_provenance.jsonl", oracle_rows),
        ("calibration_estimates.jsonl", calibration_rows),
        ("trajectory_events.jsonl", event_rows),
    ):
        contract = conformance_graph.artifact(filename).contract
        content = serialize_jsonl_artifact(
            schema_version=contract.schema_version,
            source_design_sha256=source_design_sha256,
            rows=rows,
        )
        scientific_payload = b"".join(content.splitlines(keepends=True)[1:])
        metadata = json.loads(content.splitlines()[0])
        assert (
            metadata["scientific_payload_sha256"] == hashlib.sha256(scientific_payload).hexdigest()
        )
        replacements[filename] = (content, scientific_payload)
    mutated_graph = replace(
        mutated_graph,
        artifacts=tuple(
            replace(
                item,
                content=replacements[item.contract.filename][0],
                scientific_payload=replacements[item.contract.filename][1],
            )
            if item.contract.filename in replacements
            else item
            for item in mutated_graph.artifacts
        ),
    )

    # Recompute the ordinary artifact hash maps and downstream content bindings too. The
    # mutation must reach Oracle reconstruction, never stop at a stale generic envelope.
    audit = mutated_graph.artifact("audit_results.json")
    audit_operational = deepcopy(dict(audit.operational))
    audit_operational["artifact_content_sha256"] = {
        item.contract.filename: item.content_sha256 for item in mutated_graph.artifacts[:10]
    }
    audit_operational["artifact_scientific_payload_sha256"] = {
        item.contract.filename: item.scientific_payload_sha256
        for item in mutated_graph.artifacts[:10]
    }
    audit_content = serialize_json_artifact(
        schema_version=audit.contract.schema_version,
        source_design_sha256=source_design_sha256,
        scientific_fields=cast(dict[str, object], audit.scientific),
        operational_fields=audit_operational,
    )
    mutated_graph = _replace_decoded_artifact(
        mutated_graph,
        "audit_results.json",
        operational=audit_operational,
        content=audit_content,
    )
    manifest = mutated_graph.artifact("run_manifest.json")
    manifest_operational = deepcopy(dict(manifest.operational))
    manifest_operational["artifact_content_sha256"] = {
        item.contract.filename: item.content_sha256 for item in mutated_graph.artifacts[:11]
    }
    manifest_operational["artifact_scientific_payload_sha256"] = {
        item.contract.filename: item.scientific_payload_sha256
        for item in mutated_graph.artifacts[:11]
    }
    manifest_content = serialize_json_artifact(
        schema_version=manifest.contract.schema_version,
        source_design_sha256=source_design_sha256,
        scientific_fields=cast(dict[str, object], manifest.scientific),
        operational_fields=manifest_operational,
    )
    mutated_graph = _replace_decoded_artifact(
        mutated_graph,
        "run_manifest.json",
        operational=manifest_operational,
        content=manifest_content,
    )
    recommendation = mutated_graph.artifact("recommendation.json")
    recommendation_operational = deepcopy(dict(recommendation.operational))
    recommendation_operational["run_manifest_content_sha256"] = mutated_graph.artifact(
        "run_manifest.json"
    ).content_sha256
    recommendation_content = serialize_json_artifact(
        schema_version=recommendation.contract.schema_version,
        source_design_sha256=source_design_sha256,
        scientific_fields=cast(dict[str, object], recommendation.scientific),
        operational_fields=recommendation_operational,
    )
    mutated_graph = _replace_decoded_artifact(
        mutated_graph,
        "recommendation.json",
        operational=recommendation_operational,
        content=recommendation_content,
    )

    downstream_validators_called: list[str] = []

    def forbidden_calibration_validation(*args: object, **kwargs: object) -> None:
        del args, kwargs
        downstream_validators_called.append("calibration")
        raise AssertionError("calibration validation must follow Oracle re-observation")

    def forbidden_event_validation(*args: object, **kwargs: object) -> None:
        del args, kwargs
        downstream_validators_called.append("events")
        raise AssertionError("event validation must follow Oracle re-observation")

    monkeypatch.setattr(
        artifact_graph_module,
        "_validate_calibration",
        forbidden_calibration_validation,
    )
    monkeypatch.setattr(
        artifact_graph_module,
        "_validate_events",
        forbidden_event_validation,
    )
    with pytest.raises(ArtifactValidationError) as captured:
        validate_artifact_graph(mutated_graph)
    assert type(captured.value).__name__ == "ArtifactValidationError"
    assert str(captured.value) == ("Oracle source observation does not reproduce independently.")
    assert downstream_validators_called == []


@pytest.mark.artifact5
@pytest.mark.sigma_reconstruction
def test_calibration_graph_derives_strictly_prior_cutoff_from_event_history() -> None:
    from research_decision_engine.benchmarks.broader_artifact_graph import (
        _validate_calibration,
    )

    calibration_rows, run_rows, oracle_rows, source_events = _minimal_calibration_graph_rows()
    event_rows = deepcopy(list(source_events))
    shifted_run_id = cast(list[str], calibration_rows[0]["deployed_run_ids"])[0]
    for event_row in event_rows:
        event_payload = cast(dict[str, object], event_row["event_payload"])
        if event_payload["run_id"] == shifted_run_id:
            event_payload["sequence"] = cast(int, event_payload["sequence"]) + 1
    with pytest.raises(ArtifactValidationError) as captured:
        _validate_calibration(calibration_rows, run_rows, oracle_rows, event_rows)
    assert str(captured.value) == (
        "Calibration sources are not strictly prior to trajectory evidence."
    )


@pytest.mark.artifact5
@pytest.mark.sigma_reconstruction
def test_event_sigma_relations_allow_only_the_applicable_artifact5_estimate() -> None:
    from research_decision_engine.benchmarks.broader_artifact_graph import _validate_events
    from research_decision_engine.benchmarks.broader_protocol import load_protocol_snapshot
    from research_decision_engine.benchmarks.broader_worlds import CANDIDATES_BY_ID, GROUP_IDS

    calibration_rows, run_rows, oracle_rows, event_rows = _minimal_calibration_graph_rows()
    objective_only = next(
        cast(dict[str, object], row["event_payload"])
        for row in event_rows
        if (payload := cast(dict[str, object], row["event_payload"]))["event_type"] == "experiment"
        and str(payload["arm_id"]).startswith("calibrated_")
        and CANDIDATES_BY_ID[cast(str, payload["candidate_id"])].comparison_group_id
        not in GROUP_IDS
    )
    assert objective_only["sigma_estimate_id"] is None
    _validate_events(
        event_rows,
        run_rows,
        oracle_rows,
        calibration_rows,
        load_protocol_snapshot(),
    )


@pytest.mark.artifact5
@pytest.mark.sigma_reconstruction
@pytest.mark.parametrize(
    ("mutation", "expected_message"),
    (
        (
            "fixed_group_sigma",
            "Event singular sigma nullability differs from its arm and comparison group.",
        ),
        (
            "calibrated_objective_sigma",
            "Event singular sigma nullability differs from its arm and comparison group.",
        ),
        (
            "calibrated_group_missing",
            "Event singular sigma nullability differs from its arm and comparison group.",
        ),
        (
            "calibrated_evidence_missing",
            "Event singular sigma nullability differs from its arm and comparison group.",
        ),
        (
            "calibrated_update_missing",
            "Event singular sigma nullability differs from its arm and comparison group.",
        ),
        (
            "wrong_group",
            "Event sigma estimate differs from its owning run or applicable group.",
        ),
        (
            "foreign_world",
            "Event sigma estimate differs from its owning run or applicable group.",
        ),
        (
            "foreign_seed",
            "Event sigma estimate differs from its owning run or applicable group.",
        ),
        (
            "foreign_prefix",
            "Event sigma estimate differs from its owning run or applicable group.",
        ),
        (
            "evidence_group_rewrite",
            "Evidence comparison group differs from its source experiments.",
        ),
    ),
)
def test_event_sigma_relationship_mutations_reach_graph_validation(
    mutation: str,
    expected_message: str,
) -> None:
    from research_decision_engine.benchmarks.broader_artifact_graph import _validate_events
    from research_decision_engine.benchmarks.broader_protocol import load_protocol_snapshot
    from research_decision_engine.benchmarks.broader_worlds import CANDIDATES_BY_ID, GROUP_IDS

    source_calibration, run_rows, oracle_rows, source_events = _minimal_calibration_graph_rows()
    calibration_rows = deepcopy(list(source_calibration))
    event_rows = deepcopy(list(source_events))

    def event_payload(
        *,
        calibrated: bool,
        event_type: str,
        grouped_experiment: bool = False,
        objective_experiment: bool = False,
    ) -> dict[str, object]:
        for row in event_rows:
            payload = cast(dict[str, object], row["event_payload"])
            if payload["event_type"] != event_type:
                continue
            if str(payload["arm_id"]).startswith("calibrated_") != calibrated:
                continue
            if grouped_experiment:
                candidate = CANDIDATES_BY_ID[cast(str, payload["candidate_id"])]
                if candidate.comparison_group_id not in GROUP_IDS:
                    continue
            if objective_experiment:
                candidate = CANDIDATES_BY_ID[cast(str, payload["candidate_id"])]
                if candidate.comparison_group_id in GROUP_IDS:
                    continue
            return payload
        raise AssertionError("The minimal graph lacks the requested event variant.")

    if mutation == "fixed_group_sigma":
        payload = event_payload(
            calibrated=False,
            event_type="experiment",
            grouped_experiment=True,
        )
        group_id = CANDIDATES_BY_ID[cast(str, payload["candidate_id"])].comparison_group_id
        payload["sigma_estimate_id"] = next(
            row["sigma_estimate_id"]
            for row in calibration_rows
            if row["comparison_group_id"] == group_id
        )
    elif mutation == "calibrated_objective_sigma":
        payload = event_payload(
            calibrated=True,
            event_type="experiment",
            objective_experiment=True,
        )
        candidate = CANDIDATES_BY_ID[cast(str, payload["candidate_id"])]
        assert candidate.comparison_group_id not in GROUP_IDS
        payload["sigma_estimate_id"] = calibration_rows[0]["sigma_estimate_id"]
    elif mutation == "calibrated_group_missing":
        payload = event_payload(
            calibrated=True,
            event_type="experiment",
            grouped_experiment=True,
        )
        payload["sigma_estimate_id"] = None
    elif mutation == "calibrated_evidence_missing":
        payload = event_payload(calibrated=True, event_type="evidence")
        payload["sigma_estimate_id"] = None
    elif mutation == "calibrated_update_missing":
        payload = event_payload(calibrated=True, event_type="belief_update")
        payload["sigma_estimate_id"] = None
    elif mutation == "evidence_group_rewrite":
        payload = event_payload(calibrated=True, event_type="evidence")
        specific = cast(dict[str, object], payload["event_specific_payload"])
        original_group = cast(str, specific["comparison_group_id"])
        replacement_sigma = next(
            row for row in calibration_rows if row["comparison_group_id"] != original_group
        )
        specific["comparison_group_id"] = replacement_sigma["comparison_group_id"]
        payload["sigma_estimate_id"] = replacement_sigma["sigma_estimate_id"]
    else:
        payload = event_payload(
            calibrated=True,
            event_type="experiment",
            grouped_experiment=True,
        )
        candidate_group = CANDIDATES_BY_ID[cast(str, payload["candidate_id"])].comparison_group_id
        original_sigma = next(
            row for row in calibration_rows if row["comparison_group_id"] == candidate_group
        )
        if mutation == "wrong_group":
            payload["sigma_estimate_id"] = next(
                row["sigma_estimate_id"]
                for row in calibration_rows
                if row["comparison_group_id"] != candidate_group
            )
        else:
            foreign = deepcopy(original_sigma)
            foreign["sigma_estimate_id"] = f"{foreign['sigma_estimate_id']}/{mutation}"
            if mutation == "foreign_world":
                foreign["world_id"] = "foreign-world"
                foreign["calibration_prefix_id"] = (
                    f"{foreign['calibration_prefix_id']}/foreign-world"
                )
            elif mutation == "foreign_seed":
                foreign["seed"] = cast(int, foreign["seed"]) + 1
                foreign["calibration_prefix_id"] = (
                    f"{foreign['calibration_prefix_id']}/foreign-seed"
                )
            else:
                foreign["calibration_prefix_id"] = f"{foreign['calibration_prefix_id']}/foreign"
            calibration_rows.append(foreign)
            payload["sigma_estimate_id"] = foreign["sigma_estimate_id"]
    mutated_row = next(
        row
        for row in event_rows
        if cast(dict[str, object], row["event_payload"])["event_id"] == payload["event_id"]
    )
    _rehash_event(mutated_row)
    with pytest.raises(ArtifactValidationError) as captured:
        _validate_events(
            event_rows,
            run_rows,
            oracle_rows,
            calibration_rows,
            load_protocol_snapshot(),
        )
    assert type(captured.value).__name__ == "ArtifactValidationError"
    assert str(captured.value) == expected_message


def test_tagged_artifact_unions_reject_unknown_or_conflicting_fields() -> None:
    with pytest.raises(ArtifactValidationError, match="Unknown oracle"):
        validate_oracle_record({"record_type": "peek"})
    with pytest.raises(ArtifactValidationError, match="Unknown comparison"):
        validate_comparison_record({"record_type": "other"})
    with pytest.raises(ArtifactValidationError, match="Unknown resampling"):
        validate_resampling_record({"record_type": "method"})


def test_arm_run_contract_rejects_unknown_and_duplicate_primary_keys() -> None:
    contract = next(item for item in artifact_contracts() if item.filename == "arm_runs.jsonl")
    metrics: dict[str, object] = {
        "true_probability": f64(1.0 / 3.0),
        "top_scientific_hypothesis_id": "optimizer.adam-advantage",
        "top_probability": f64(1.0 / 3.0),
        "prediction_correct": True,
        "confidently_wrong": False,
        "nll": f64(1.0),
        "brier": f64(2.0 / 3.0),
        "posterior_entropy": f64(1.584962500721156),
        "conditional_brier_efficiency": None,
        "end_to_end_brier_efficiency": None,
        "decision_cost": f64(0.0),
        "calibration_cost": f64(0.0),
        "required_total_cost": f64(0.0),
        "physical_cost_share": f64(0.0),
        "best_observed_objective": None,
        "matched_pairs": 0,
        "redundant_selected": 0,
        "irrelevant_selected": 0,
        "outcome_experiments_completed": 0,
        "setup_actions_completed": 0,
        "budget_exhausted": True,
        "terminal_reason": "budget_exhausted",
    }
    probabilities = {
        "optimizer.adam-advantage": f64(1.0 / 3.0),
        "optimizer.no-consistent-advantage": f64(1.0 / 3.0),
        "optimizer.sgd-advantage": f64(1.0 / 3.0),
    }
    row: dict[str, object] = {
        "run_id": "run:valid",
        "comparison_id": "comparison:valid",
        "arm_id": "fixed_ig",
        "world_id": "h_adam_low",
        "seed": 1000,
        "budget_id": "budget-2.25",
        "budget": f64(2.25),
        "policy_id": "information_gain",
        "belief_model_id": "fixed_sigma_gaussian",
        "lineage_id": "lineage/run:valid",
        "store_id": "store/run:valid",
        "initial_probabilities": probabilities,
        "final_probabilities": probabilities,
        "scientific_hypothesis_id": "optimizer.adam-advantage",
        "metrics": metrics,
        "decision_ids": [],
        "event_ids": ["event/run:valid/0001/terminal"],
        "calibration_prefix_ids": [],
        "run_status": "complete",
        "terminal_reason": "budget_exhausted",
        "ordered_decisions_sha256": "0" * 64,
        "reconciliation_sha256": "1" * 64,
        "trajectory_sha256": "2" * 64,
    }
    assert set(row) == set(ARM_RUN_FIELDS)
    assert set(metrics) == set(METRIC_SET_FIELDS)

    validate_canonical_rows(contract, (row,))
    with pytest.raises(ArtifactValidationError, match="Duplicate run_id"):
        validate_canonical_rows(contract, (row, row))
    row["extra"] = "forbidden"
    with pytest.raises(ArtifactValidationError, match="fields differ"):
        validate_canonical_rows(contract, (row,))


def test_canonical_event_union_validates_payload_hash_and_nullability() -> None:
    payload = {
        "schema_version": "canonical-event-payload/v1",
        "event_type": "terminal",
        "event_id": "event/run:valid/0001/terminal",
        "run_id": "run:valid",
        "sequence": 1,
        "comparison_id": "comparison:valid",
        "world_id": "h_adam_low",
        "seed": 1000,
        "budget_id": "budget-2.25",
        "arm_id": "fixed_ig",
        "policy_id": "information_gain",
        "controller_stage_id": "CONTROLLER-STAGE-TERMINATION",
        "candidate_id": None,
        "public_state_sha256": None,
        "ordered_decisions_sha256": "0" * 64,
        "eligibility_state_sha256": None,
        "belief_lineage_id": "lineage/run:valid",
        "sigma_estimate_id": None,
        "cost_before": f64(2.0),
        "cost_after": f64(2.0),
        "status": "complete",
        "terminal_reason": "budget_exhausted",
        "integrity_audit_id": None,
        "event_specific_payload": {
            "final_belief_state_id": "belief-state/run:valid/0001",
            "remaining_budget": f64(0.25),
            "completed_candidate_ids": ["g00-adam-r1", "g00-sgd-r1"],
            "unexecuted_candidate_ids": [],
            "publicly_feasible_candidate_ids": [],
            "affordable_candidate_ids": [],
            "decision_cost": f64(2.0),
            "calibration_cost": f64(0.0),
            "required_total_cost": f64(2.0),
        },
    }
    provenance = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    row = {"event_payload": payload, "provenance_sha256": provenance}

    validate_canonical_event_row(row)
    specific = cast(dict[str, object], payload["event_specific_payload"])
    specific["physical_cost_share"] = f64(2.0)
    with pytest.raises(ArtifactValidationError, match="specialization fields"):
        validate_canonical_event_row(
            {
                "event_payload": payload,
                "provenance_sha256": hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
            }
        )
    specific.pop("physical_cost_share")
    row["provenance_sha256"] = "1" * 64
    with pytest.raises(ArtifactValidationError, match="provenance"):
        validate_canonical_event_row(row)


def test_unrestricted_low_level_finalizer_was_removed() -> None:
    assert not hasattr(artifact_module, "ImmutableArtifactDirectory")


def test_prefinalization_rejects_structurally_incomplete_claims(
    diagnostic_conformance_fixture: DiagnosticConformanceFixture,
) -> None:
    fixture = diagnostic_conformance_fixture
    plan = fixture.finalization_plan
    operational = fixture.operational
    scientific = plan.prefinalization.scientific_claims()
    scientific["arm_runs.jsonl"] = ()

    with pytest.raises(ArtifactValidationError):
        assemble_prefinalization_artifacts(
            scientific,
            operational,
            profile=CONFORMANCE_PROFILE,
        )


def test_all_13_populated_artifacts_validate_and_finalize_immutably(
    tmp_path: Path,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "canonical"
    plan, operational, authorization = conformance_oracle_support.payloads(target)
    contracts = artifact_contracts()
    artifacts = finalize_validation_artifacts(
        target,
        plan,
        operational,
        authorization,
        contracts=contracts,
        profile=CONFORMANCE_PROFILE,
    )
    graph = decode_and_validate_artifacts(
        artifacts,
        contracts,
        profile=CONFORMANCE_PROFILE,
    )

    assert tuple(artifacts) == tuple(contract.filename for contract in contracts)
    assert len(graph.artifacts) == 13
    assert (
        len(cast(tuple[object, ...], graph.artifact("arm_runs.jsonl").scientific))
        == CONFORMANCE_PROFILE.arm_runs
    )
    assert (
        len(cast(tuple[object, ...], graph.artifact("comparisons.jsonl").scientific))
        == CONFORMANCE_PROFILE.comparisons
    )
    assert len(cast(tuple[object, ...], graph.artifact("contrast_results.csv").scientific)) == 122

    assert {path.name for path in target.iterdir()} == set(artifacts)
    assert all(
        (target / filename).read_bytes() == content for filename, content in artifacts.items()
    )
    with pytest.raises(ValueError, match="forged, stale, copied, or already consumed"):
        finalize_validation_artifacts(
            target,
            plan,
            operational,
            authorization,
            contracts=contracts,
            profile=CONFORMANCE_PROFILE,
        )


def test_staged_graphs_exist_only_at_their_frozen_lifecycle_points(
    diagnostic_conformance_fixture: DiagnosticConformanceFixture,
) -> None:
    fixture = diagnostic_conformance_fixture
    plan = fixture.finalization_plan
    operational = fixture.operational
    prefinal = decode_and_validate_prefinal_artifacts(
        plan.prefinalization.artifact_mapping(),
        artifact_contracts()[:9],
        profile=CONFORMANCE_PROFILE,
    )
    audited_artifacts = assembly_module._assemble_audited_artifact_bytes(
        plan,
        operational,
        artifact_contracts(),
        CONFORMANCE_PROFILE,
    )
    audited = decode_and_validate_audited_artifacts(
        audited_artifacts,
        artifact_contracts()[:11],
        profile=CONFORMANCE_PROFILE,
    )

    assert len(prefinal.artifacts) == 9
    assert len(audited.artifacts) == 11
    assert "gate_evaluations.json" not in plan.prefinalization.artifact_mapping()
    assert "run_manifest.json" not in plan.scientific_claims()
    assert "recommendation.json" not in plan.scientific_claims()
    assert "run_manifest.json" not in audited_artifacts
    assert "recommendation.json" not in audited_artifacts


def test_finalization_promotes_1_through_11_then_creates_manifest_and_recommendation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "canonical"
    plan, operational, authorization = conformance_oracle_support.payloads(target)
    publications: list[tuple[str, str]] = []
    original_publish = cast(Any, assembly_module._publish_claimed_canonical_entry)

    def recording_publish(
        directory: Path,
        staging: Path,
        destination: Path,
        **kwargs: object,
    ) -> None:
        publications.append((staging.name, destination.name))
        original_publish(directory, staging, destination, **kwargs)

    monkeypatch.setattr(
        assembly_module,
        "_publish_claimed_canonical_entry",
        recording_publish,
    )
    finalize_validation_artifacts(
        target,
        plan,
        operational,
        authorization,
        profile=CONFORMANCE_PROFILE,
    )

    assert [destination for _, destination in publications[-3:]] == [
        "canonical",
        "run_manifest.json",
        "recommendation.json",
    ]
    assert publications[-3][0].startswith(".canonical.artifacts-1-11.")
    assert publications[-3][0].endswith(".incomplete")
    assert publications[-2][0].startswith(".run_manifest.json.")
    assert publications[-1][0].startswith(".recommendation.json.")


def test_rehashed_caller_supplied_pass_audits_cannot_bypass_authorization(
    tmp_path: Path,
    conformance_oracle_support: ConformanceOracleSupport,
) -> None:
    target = tmp_path / "canonical"
    plan, operational, authorization = conformance_oracle_support.payloads(target)
    forged_audit = deepcopy(plan.post_audit.audit_results)
    rows = cast(list[dict[str, object]], forged_audit["audits"])
    for row in rows:
        row["observed"] = "caller-supplied PASS assertion"
        row["audit_detail_sha256"] = protocol_hash(
            "audit_detail/v1",
            {
                "audit_id": row["audit_id"],
                "expected": row["expected"],
                "observed": row["observed"],
            },
        )
    forged_plan = replace(
        plan,
        post_audit=replace(plan.post_audit, audit_results=forged_audit),
    )

    with pytest.raises(ValueError, match="context does not match"):
        finalize_validation_artifacts(
            target,
            forged_plan,
            operational,
            authorization,
            profile=CONFORMANCE_PROFILE,
        )


def test_invalid_authorization_emits_only_noncanonical_failure(
    tmp_path: Path,
    diagnostic_conformance_fixture: DiagnosticConformanceFixture,
) -> None:
    target = tmp_path / "invalid" / "canonical"
    fixture = diagnostic_conformance_fixture

    with pytest.raises(ValueError, match="exact issued capability"):
        finalize_validation_artifacts(
            target,
            fixture.finalization_plan,
            fixture.operational,
            cast(FinalizationAuthorization, object()),
            profile=CONFORMANCE_PROFILE,
        )

    assert not target.exists()
    failure = target.parent / "validation_failure.json"
    assert failure.is_file()
    document = json.loads(failure.read_bytes())
    assert set(document) == {
        "schema_version",
        "phase",
        "error_code",
        "path",
        "message",
        "context",
        "details_sha256",
    }
    assert document["schema_version"] == "validation-failure/v1"
    details = {key: document[key] for key in ("phase", "error_code", "path", "message", "context")}
    assert document["details_sha256"] == protocol_hash("validation_failure_details/v1", details)
    assert not (target.parent / "run_manifest.json").exists()
    assert not (target.parent / "recommendation.json").exists()


@pytest.mark.parametrize(
    "filename",
    tuple(contract.filename for contract in artifact_contracts()),
)
def test_each_canonical_artifact_rejects_a_contract_specific_mutation(
    filename: str, conformance_graph: CanonicalArtifactGraph
) -> None:
    mutated = _graph_scientific_claims(conformance_graph)
    _mutate_artifact_payload(mutated, filename)

    with pytest.raises(ArtifactValidationError):
        validate_artifact_graph(_replace_graph_scientific(conformance_graph, mutated))


@pytest.mark.parametrize(
    "mutation",
    (
        "terminal_without_action",
        "evidence_without_sources",
        "belief_update_without_evidence",
        "cost_mismatch",
        "broken_lineage",
        "inconsistent_gate",
        "inconsistent_gate_operand",
        "contradictory_integrity_gate",
        "inconsistent_recommendation",
        "inconsistent_resampling_statistic",
        "inconsistent_holm_row",
    ),
)
def test_complete_graph_rejects_cross_artifact_semantic_mutations(
    mutation: str, conformance_graph: CanonicalArtifactGraph
) -> None:
    mutated = _graph_scientific_claims(conformance_graph)
    mutators: dict[str, Callable[[dict[str, object]], None]] = {
        "terminal_without_action": _terminal_without_action,
        "evidence_without_sources": _evidence_without_sources,
        "belief_update_without_evidence": _belief_update_without_evidence,
        "cost_mismatch": _cost_mismatch,
        "broken_lineage": _broken_lineage,
        "inconsistent_gate": _inconsistent_gate,
        "inconsistent_gate_operand": _inconsistent_gate_operand,
        "contradictory_integrity_gate": _contradictory_integrity_gate,
        "inconsistent_recommendation": _inconsistent_recommendation,
        "inconsistent_resampling_statistic": _inconsistent_resampling_statistic,
        "inconsistent_holm_row": _inconsistent_holm_row,
    }
    mutators[mutation](mutated)
    with pytest.raises(ArtifactValidationError):
        validate_artifact_graph(_replace_graph_scientific(conformance_graph, mutated))


@pytest.mark.parametrize(
    "mutation",
    ("downgrade_estimable", "upgrade_nonestimable", "wrong_resampling_failure"),
)
def test_derivation_first_validation_rejects_stored_status_control(
    mutation: str,
    conformance_graph: CanonicalArtifactGraph,
) -> None:
    filename = "contrast_results.csv"
    rows = deepcopy(
        list(
            cast(
                tuple[dict[str, object], ...],
                conformance_graph.artifact(filename).scientific,
            )
        )
    )
    if mutation == "downgrade_estimable":
        row = next(item for item in rows if item["result_status"] == "ESTIMATED")
        row.update(
            result_status="INCONCLUSIVE",
            estimability_status="not_estimable",
            estimate=None,
            ci_low=None,
            ci_high=None,
            test_statistic=None,
            permutation_count=None,
            extreme_count=None,
            p_raw=None,
            p_adjusted=None,
            holm_rank=None,
        )
    elif mutation == "upgrade_nonestimable":
        row = next(item for item in rows if item["result_status"] == "INCONCLUSIVE")
        row.update(
            result_status="ESTIMATED",
            estimability_status="estimated",
            estimate=f64(0.0),
            ci_low=f64(0.0),
            ci_high=f64(0.0),
            test_statistic=f64(0.0),
            permutation_count=4,
            extreme_count=0,
            p_raw=f64(0.2),
            p_adjusted=f64(1.0),
            holm_rank=1,
        )
    else:
        filename = "resampling_audit.jsonl"
        rows = deepcopy(
            list(
                cast(
                    tuple[dict[str, object], ...],
                    conformance_graph.artifact(filename).scientific,
                )
            )
        )
        row = next(item for item in rows if item["result_status"] == "null")
        row["failure_code"] = "stream_failure"

    with pytest.raises(ArtifactValidationError):
        validate_artifact_graph(_replace_graph_rows(conformance_graph, filename, tuple(rows)))


def _graph_scientific_claims(graph: CanonicalArtifactGraph) -> dict[str, object]:
    return {item.contract.filename: deepcopy(item.scientific) for item in graph.artifacts}


def _replace_graph_scientific(
    graph: CanonicalArtifactGraph, scientific: dict[str, object]
) -> CanonicalArtifactGraph:
    return replace(
        graph,
        artifacts=tuple(
            replace(item, scientific=scientific[item.contract.filename]) for item in graph.artifacts
        ),
    )


def _replace_graph_rows(
    graph: CanonicalArtifactGraph,
    filename: str,
    rows: tuple[dict[str, object], ...],
) -> CanonicalArtifactGraph:
    return replace(
        graph,
        artifacts=tuple(
            replace(item, scientific=rows) if item.contract.filename == filename else item
            for item in graph.artifacts
        ),
    )


def _replace_decoded_artifact(
    graph: CanonicalArtifactGraph,
    filename: str,
    *,
    operational: dict[str, object],
    content: bytes,
) -> CanonicalArtifactGraph:
    return replace(
        graph,
        artifacts=tuple(
            replace(
                item,
                operational=operational,
                content=content,
                scientific_payload=canonical_json_bytes(
                    cast(dict[str, object], item.scientific), final_lf=True
                ),
            )
            if item.contract.filename == filename
            else item
            for item in graph.artifacts
        ),
    )


def _event_rows(payloads: dict[str, object]) -> list[dict[str, object]]:
    rows = list(cast(tuple[dict[str, object], ...], payloads["trajectory_events.jsonl"]))
    payloads["trajectory_events.jsonl"] = tuple(rows)
    return rows


def _event_payload(row: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], row["event_payload"])


def _rehash_event(row: dict[str, object]) -> None:
    row["provenance_sha256"] = hashlib.sha256(canonical_json_bytes(_event_payload(row))).hexdigest()


def _terminal_without_action(payloads: dict[str, object]) -> None:
    row = next(
        item
        for item in _event_rows(payloads)
        if _event_payload(item)["event_type"] == "terminal"
        and cast(
            list[object],
            cast(dict[str, object], _event_payload(item)["event_specific_payload"])[
                "unexecuted_candidate_ids"
            ],
        )
    )
    specific = cast(dict[str, object], _event_payload(row)["event_specific_payload"])
    unexecuted = cast(list[object], specific["unexecuted_candidate_ids"])
    completed = cast(list[object], specific["completed_candidate_ids"])
    completed.append(unexecuted.pop(0))
    _rehash_event(row)


def _evidence_without_sources(payloads: dict[str, object]) -> None:
    row = next(
        item for item in _event_rows(payloads) if _event_payload(item)["event_type"] == "evidence"
    )
    cast(dict[str, object], _event_payload(row)["event_specific_payload"])[
        "source_experiment_ids"
    ] = []
    _rehash_event(row)


def _belief_update_without_evidence(payloads: dict[str, object]) -> None:
    row = next(
        item
        for item in _event_rows(payloads)
        if _event_payload(item)["event_type"] == "belief_update"
    )
    cast(dict[str, object], _event_payload(row)["event_specific_payload"])["evidence_id"] = (
        "event/unknown/0001/evidence"
    )
    _rehash_event(row)


def _cost_mismatch(payloads: dict[str, object]) -> None:
    row = next(
        item for item in _event_rows(payloads) if _event_payload(item)["event_type"] == "experiment"
    )
    cast(dict[str, object], _event_payload(row)["event_specific_payload"])["cost"] = f64(99.0)
    _rehash_event(row)


def _broken_lineage(payloads: dict[str, object]) -> None:
    row = _event_rows(payloads)[0]
    _event_payload(row)["belief_lineage_id"] = "lineage/foreign"
    _rehash_event(row)


def _inconsistent_gate(payloads: dict[str, object]) -> None:
    document = cast(dict[str, object], payloads["gate_evaluations.json"])
    gate = cast(list[dict[str, object]], document["gates"])[0]
    gate["gate_status"] = "FAIL"
    cast(list[dict[str, object]], gate["conditions"])[0]["gate_status_result"] = "FAIL"


def _inconsistent_gate_operand(payloads: dict[str, object]) -> None:
    document = cast(dict[str, object], payloads["gate_evaluations.json"])
    gate = cast(list[dict[str, object]], document["gates"])[0]
    condition = cast(list[dict[str, object]], gate["conditions"])[0]
    observed = cast(list[dict[str, object]], condition["observed_values"])[0]
    observed["gate_status_value"] = "FAIL"


def _contradictory_integrity_gate(payloads: dict[str, object]) -> None:
    document = cast(dict[str, object], payloads["gate_evaluations.json"])
    gate = next(
        item
        for item in cast(list[dict[str, object]], document["gates"])
        if item["gate_id"] == "G-INTEGRITY"
    )
    gate["gate_status"] = "FAIL"
    cast(list[dict[str, object]], gate["conditions"])[0]["gate_status_result"] = "FAIL"


def _inconsistent_recommendation(payloads: dict[str, object]) -> None:
    cast(dict[str, object], payloads["recommendation.json"])["recommendation"] = (
        "B_TARGETED_CONTROLLER_MODIFICATION"
    )


def _inconsistent_resampling_statistic(payloads: dict[str, object]) -> None:
    rows = list(cast(tuple[dict[str, object], ...], payloads["resampling_audit.jsonl"]))
    row = next(
        item
        for item in rows
        if item["record_type"] == "bootstrap" and item["result_status"] == "valid"
    )
    row["replicate_estimate"] = f64(123.0)
    payloads["resampling_audit.jsonl"] = tuple(rows)


def _inconsistent_holm_row(payloads: dict[str, object]) -> None:
    rows = list(cast(tuple[dict[str, object], ...], payloads["contrast_results.csv"]))
    row = next(item for item in rows if item["holm_member"] and item["p_adjusted"] is not None)
    row["p_adjusted"] = f64(0.999)
    payloads["contrast_results.csv"] = tuple(rows)


def _mutate_artifact_payload(payloads: dict[str, object], filename: str) -> None:
    if filename == "protocol_snapshot.json":
        cast(dict[str, object], payloads[filename]).pop("formula_registry")
    elif filename == "world_definitions.json":
        document = cast(dict[str, object], payloads[filename])
        cast(list[object], document["candidate_catalog"]).pop()
    elif filename == "arm_runs.jsonl":
        rows = list(cast(tuple[dict[str, object], ...], payloads[filename]))
        rows.append(deepcopy(rows[0]))
        payloads[filename] = tuple(rows)
    elif filename == "oracle_provenance.jsonl":
        rows = list(cast(tuple[dict[str, object], ...], payloads[filename]))
        rows.pop(0)
        payloads[filename] = tuple(rows)
    elif filename == "calibration_estimates.jsonl":
        rows = list(cast(tuple[dict[str, object], ...], payloads[filename]))
        rows[0]["sigma_estimate_id"] = "sigma-estimate/unknown"
        payloads[filename] = tuple(rows)
    elif filename == "trajectory_events.jsonl":
        rows = list(cast(tuple[dict[str, object], ...], payloads[filename]))
        rows[0]["provenance_sha256"] = "0" * 64
        payloads[filename] = tuple(rows)
    elif filename == "comparisons.jsonl":
        rows = list(cast(tuple[dict[str, object], ...], payloads[filename]))
        rows[0]["fixed_run_id"] = "run/unknown"
        payloads[filename] = tuple(rows)
    elif filename == "contrast_results.csv":
        rows = list(cast(tuple[dict[str, object], ...], payloads[filename]))
        rows[0]["metric_id"] = "unknown_metric"
        payloads[filename] = tuple(rows)
    elif filename == "resampling_audit.jsonl":
        rows = list(cast(tuple[dict[str, object], ...], payloads[filename]))
        rows[0]["seed"] = cast(int, rows[0]["seed"]) + 1
        payloads[filename] = tuple(rows)
    elif filename == "gate_evaluations.json":
        document = cast(dict[str, object], payloads[filename])
        cast(list[dict[str, object]], document["gates"])[0]["gate_id"] = "G-UNKNOWN"
    elif filename == "audit_results.json":
        document = cast(dict[str, object], payloads[filename])
        cast(list[dict[str, object]], document["audits"])[0]["status"] = "UNKNOWN"
    elif filename == "run_manifest.json":
        document = cast(dict[str, object], payloads[filename])
        cast(dict[str, object], document["observed_counts"])["arm_runs"] = 11
    elif filename == "recommendation.json":
        cast(dict[str, object], payloads[filename])["branch_id"] = "BRANCH-UNKNOWN"
    else:
        raise AssertionError(f"No negative contract mutation is defined for {filename}.")
