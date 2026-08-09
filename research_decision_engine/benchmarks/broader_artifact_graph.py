"""Executable validation for staged and complete canonical artifact graphs."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, cast

from research_decision_engine.belief_models import CALIBRATED_SIGMA_MODEL_ID
from research_decision_engine.benchmarks.broader_artifacts import (
    AUDIT_RESULT_FIELDS,
    CONTRAST_HEADER,
    ENVELOPE_FIELDS,
    GATE_EVALUATION_FIELDS,
    METRIC_SET_FIELDS,
    RECOMMENDATION_FIELDS,
    RUN_MANIFEST_FIELDS,
    ArtifactContract,
    ArtifactValidationError,
    artifact_contracts,
    build_protocol_snapshot_payload,
    build_world_definitions_payload,
    validate_canonical_rows,
    validate_sha256,
)
from research_decision_engine.benchmarks.broader_calibration_history import (
    CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
)
from research_decision_engine.benchmarks.broader_oracle import (
    CALIBRATION_NAMESPACE,
    DECISION_NAMESPACE,
    OracleError,
    RevealedObservation,
    authorize_observation,
    calibration_key,
    decision_key,
    reobserve_authorized_observation,
    transform_key,
)
from research_decision_engine.benchmarks.broader_protocol import (
    ARMS,
    FULL_SEEDS,
    PROTOCOL_CHECKPOINT,
    PROTOCOL_VERSION,
    SOURCE_DESIGN_CHECKPOINT,
    ProtocolSnapshot,
    canonical_json_bytes,
    design_path,
    f64,
    load_protocol_snapshot,
    protocol_hash,
    runtime_id,
)
from research_decision_engine.benchmarks.broader_runner import (
    CalibrationDeploymentBinding,
    comparison_identity,
    reconstruct_complete_calibration_claim,
    run_identity,
)
from research_decision_engine.benchmarks.broader_statistics import (
    ActionabilityBlock,
    ActionabilityComposite,
    ActionabilityResult,
    ActionPartition,
    ActionTuple,
    BranchDecision,
    ComparisonRateRow,
    ContrastInference,
    DecisionBoolean,
    EstimandDataset,
    GateStatus,
    HolmInput,
    OutcomeRow,
    PairedMetricRow,
    PairedProbabilityRow,
    ResamplingEstimand,
    VetoResult,
    assert_executor_completeness,
    b_authorized,
    bootstrap_replicate,
    bootstrap_seed,
    bootstrap_seed_ids,
    execute_formula,
    final_decision,
    holm_64,
    partition_action_tuples,
    sampled_seed_ids_sha256,
    sign_flip_replicate,
    sign_flip_seed,
    sign_flip_vector,
    sign_vector_sha256,
    unique_actionable_mechanism,
)
from research_decision_engine.benchmarks.broader_worlds import (
    BUDGETS,
    CANDIDATES_BY_ID,
    GROUP_IDS,
    WORLDS,
    WORLDS_BY_ID,
)

EVALUATION_ID: Final = PROTOCOL_VERSION
DECIMAL53_PATTERN: Final = re.compile(r"\d\.\d{53}\Z")
DECIMAL30_PATTERN: Final = re.compile(r"-?\d+\.\d{30}\Z")
HEX_PATTERN: Final = re.compile(r"(?:[0-9a-f]{2})*\Z")
TS_PATTERN: Final = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z")
TRUSTED_ARTIFACT_CHECKPOINTS: Final = frozenset({SOURCE_DESIGN_CHECKPOINT, PROTOCOL_CHECKPOINT})


@dataclass(frozen=True, slots=True)
class ArtifactCardinalityProfile:
    """Count contract; canonical finalization always uses ``frozen``."""

    arm_runs: int = 36_864
    comparisons: int = 18_432
    calibration_estimates: int = 9_216
    bootstrap_rows: int = 660_000
    sign_flip_rows: int = 640_000
    bootstrap_replicates_per_contrast: int = 10_000
    sign_flip_replicates_per_hypothesis: int = 10_000
    canonical: bool = True

    @classmethod
    def conformance_fixture(
        cls,
        *,
        arm_runs: int,
        comparisons: int,
        calibration_estimates: int,
        bootstrap_replicates: int = 1,
        sign_flip_replicates: int = 1,
    ) -> ArtifactCardinalityProfile:
        return cls(
            arm_runs=arm_runs,
            comparisons=comparisons,
            calibration_estimates=calibration_estimates,
            bootstrap_rows=66 * bootstrap_replicates,
            sign_flip_rows=64 * sign_flip_replicates,
            bootstrap_replicates_per_contrast=bootstrap_replicates,
            sign_flip_replicates_per_hypothesis=sign_flip_replicates,
            canonical=False,
        )


FROZEN_ARTIFACT_PROFILE: Final = ArtifactCardinalityProfile()
PREFINAL_ARTIFACT_NAMES: Final = (
    "protocol_snapshot.json",
    "world_definitions.json",
    "arm_runs.jsonl",
    "oracle_provenance.jsonl",
    "calibration_estimates.jsonl",
    "trajectory_events.jsonl",
    "comparisons.jsonl",
    "contrast_results.csv",
    "resampling_audit.jsonl",
)
AUDITED_ARTIFACT_NAMES: Final = (
    *PREFINAL_ARTIFACT_NAMES,
    "gate_evaluations.json",
    "audit_results.json",
)
MANIFEST_ARTIFACT_NAMES: Final = (*AUDITED_ARTIFACT_NAMES, "run_manifest.json")


@dataclass(frozen=True, slots=True)
class DecodedArtifact:
    contract: ArtifactContract
    scientific: object
    operational: Mapping[str, object]
    content: bytes
    scientific_payload: bytes

    @property
    def scientific_payload_sha256(self) -> str:
        return hashlib.sha256(self.scientific_payload).hexdigest()

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True, slots=True)
class CanonicalArtifactGraph:
    artifacts: tuple[DecodedArtifact, ...]
    profile: ArtifactCardinalityProfile
    source_checkpoint_identifier: str = PROTOCOL_CHECKPOINT

    def artifact(self, filename: str) -> DecodedArtifact:
        for artifact in self.artifacts:
            if artifact.contract.filename == filename:
                return artifact
        raise ArtifactValidationError(f"Canonical graph lacks {filename}.")


OPERATIONAL_FIELDS: Final[dict[str, frozenset[str]]] = {
    "protocol_snapshot.json": frozenset(
        {"design_checkpoint_commit", "design_git_blob_oid", "protected_source_sha256"}
    ),
    "world_definitions.json": frozenset(),
    "gate_evaluations.json": frozenset(),
    "audit_results.json": frozenset(
        {
            "artifact_content_sha256",
            "artifact_scientific_payload_sha256",
            "historical_before_sha256",
            "historical_after_sha256",
        }
    ),
    "run_manifest.json": frozenset(
        {
            "implementation_commit",
            "implementation_tree_sha256",
            "implementation_diff_sha256",
            "implementation_tree_clean",
            "started_at",
            "completed_at",
            "dependency_versions",
            "machine",
            "artifact_content_sha256",
            "artifact_scientific_payload_sha256",
            "historical_before_sha256",
            "historical_after_sha256",
            "recommendation_scientific_payload_sha256",
        }
    ),
    "recommendation.json": frozenset({"run_manifest_content_sha256"}),
}


def _require_trusted_artifact_checkpoint(expected_checkpoint: str) -> None:
    if expected_checkpoint not in TRUSTED_ARTIFACT_CHECKPOINTS:
        raise ArtifactValidationError("Artifact checkpoint contract is not trusted.")


def _require_graph_checkpoint(
    graph: CanonicalArtifactGraph,
    expected_checkpoint: str,
) -> None:
    _require_trusted_artifact_checkpoint(expected_checkpoint)
    if graph.source_checkpoint_identifier != expected_checkpoint:
        raise ArtifactValidationError("Artifact graph checkpoint contract differs.")


def decode_and_validate_artifacts(
    artifacts: Mapping[str, bytes],
    contracts: Sequence[ArtifactContract],
    *,
    profile: ArtifactCardinalityProfile = FROZEN_ARTIFACT_PROFILE,
    expected_checkpoint: str = PROTOCOL_CHECKPOINT,
) -> CanonicalArtifactGraph:
    _require_trusted_artifact_checkpoint(expected_checkpoint)
    frozen_contracts = artifact_contracts()
    if tuple(contracts) != frozen_contracts:
        raise ArtifactValidationError(
            "Canonical artifact contracts differ structurally from the frozen registry."
        )
    expected = tuple(contract.filename for contract in contracts)
    if tuple(artifacts) != expected:
        raise ArtifactValidationError("Canonical artifacts are missing, extra, or out of order.")
    decoded = tuple(
        _decode_artifact(
            contract,
            artifacts[contract.filename],
            expected_checkpoint=expected_checkpoint,
        )
        for contract in contracts
    )
    graph = CanonicalArtifactGraph(decoded, profile, expected_checkpoint)
    validate_artifact_graph(graph, expected_checkpoint=expected_checkpoint)
    return graph


def decode_and_validate_prefinal_artifacts(
    artifacts: Mapping[str, bytes],
    contracts: Sequence[ArtifactContract],
    *,
    profile: ArtifactCardinalityProfile = FROZEN_ARTIFACT_PROFILE,
    expected_checkpoint: str = PROTOCOL_CHECKPOINT,
) -> CanonicalArtifactGraph:
    """Decode and validate temporary artifacts 1 through 9 before A01-A15."""

    graph = _decode_staged_artifacts(
        artifacts,
        contracts,
        expected_names=PREFINAL_ARTIFACT_NAMES,
        profile=profile,
        expected_checkpoint=expected_checkpoint,
    )
    validate_prefinal_artifact_graph(graph, expected_checkpoint=expected_checkpoint)
    return graph


def decode_and_validate_audited_artifacts(
    artifacts: Mapping[str, bytes],
    contracts: Sequence[ArtifactContract],
    *,
    profile: ArtifactCardinalityProfile = FROZEN_ARTIFACT_PROFILE,
    expected_checkpoint: str = PROTOCOL_CHECKPOINT,
) -> CanonicalArtifactGraph:
    """Decode and validate artifacts 1 through 11 after A16."""

    graph = _decode_staged_artifacts(
        artifacts,
        contracts,
        expected_names=AUDITED_ARTIFACT_NAMES,
        profile=profile,
        expected_checkpoint=expected_checkpoint,
    )
    validate_audited_artifact_graph(graph, expected_checkpoint=expected_checkpoint)
    return graph


def decode_and_validate_manifest_artifacts(
    artifacts: Mapping[str, bytes],
    contracts: Sequence[ArtifactContract],
    *,
    profile: ArtifactCardinalityProfile = FROZEN_ARTIFACT_PROFILE,
    expected_checkpoint: str = PROTOCOL_CHECKPOINT,
) -> CanonicalArtifactGraph:
    """Decode and validate artifacts 1-12 before recommendation creation."""

    graph = _decode_staged_artifacts(
        artifacts,
        contracts,
        expected_names=MANIFEST_ARTIFACT_NAMES,
        profile=profile,
        expected_checkpoint=expected_checkpoint,
    )
    validate_manifest_artifact_graph(graph, expected_checkpoint=expected_checkpoint)
    return graph


def _decode_staged_artifacts(
    artifacts: Mapping[str, bytes],
    contracts: Sequence[ArtifactContract],
    *,
    expected_names: tuple[str, ...],
    profile: ArtifactCardinalityProfile,
    expected_checkpoint: str,
) -> CanonicalArtifactGraph:
    _require_trusted_artifact_checkpoint(expected_checkpoint)
    if tuple(artifacts) != expected_names:
        raise ArtifactValidationError("Staged artifacts are missing, extra, or out of order.")
    frozen_prefix = artifact_contracts()[: len(expected_names)]
    if tuple(contracts) != frozen_prefix:
        raise ArtifactValidationError(
            "Staged artifact contracts differ structurally from the frozen registry prefix."
        )
    return CanonicalArtifactGraph(
        tuple(
            _decode_artifact(
                contract,
                artifacts[contract.filename],
                expected_checkpoint=expected_checkpoint,
            )
            for contract in contracts
        ),
        profile,
        expected_checkpoint,
    )


def validate_artifact_graph(
    graph: CanonicalArtifactGraph,
    *,
    expected_checkpoint: str = PROTOCOL_CHECKPOINT,
) -> None:
    """Validate schemas, hashes, counts, order, PKs, FKs, and finalization bindings."""

    _require_graph_checkpoint(graph, expected_checkpoint)
    snapshot = load_protocol_snapshot()
    assert_executor_completeness()
    _validate_protocol_snapshot(graph, snapshot)
    _validate_world_definitions(graph, snapshot)
    _validate_dynamic_graph(graph, snapshot)
    _validate_analysis_graph(graph, snapshot)
    _validate_finalization_graph(graph, snapshot)


def validate_prefinal_artifact_graph(
    graph: CanonicalArtifactGraph,
    *,
    expected_checkpoint: str = PROTOCOL_CHECKPOINT,
) -> None:
    """Validate all claims available before gates, audits, manifest, or recommendation."""

    _require_graph_checkpoint(graph, expected_checkpoint)
    if tuple(item.contract.filename for item in graph.artifacts) != PREFINAL_ARTIFACT_NAMES:
        raise ArtifactValidationError("Prefinal artifact graph is not exactly artifacts 1-9.")
    snapshot = load_protocol_snapshot()
    assert_executor_completeness()
    _validate_protocol_snapshot(graph, snapshot)
    _validate_world_definitions(graph, snapshot)
    _validate_dynamic_graph(graph, snapshot)
    _validate_prefinal_analysis_graph(graph, snapshot)


def validate_audited_artifact_graph(
    graph: CanonicalArtifactGraph,
    *,
    expected_checkpoint: str = PROTOCOL_CHECKPOINT,
) -> None:
    """Validate artifacts 1-11 before manifest and recommendation creation."""

    _require_graph_checkpoint(graph, expected_checkpoint)
    if tuple(item.contract.filename for item in graph.artifacts) != AUDITED_ARTIFACT_NAMES:
        raise ArtifactValidationError("Audited artifact graph is not exactly artifacts 1-11.")
    snapshot = load_protocol_snapshot()
    assert_executor_completeness()
    _validate_protocol_snapshot(graph, snapshot)
    _validate_world_definitions(graph, snapshot)
    _validate_dynamic_graph(graph, snapshot)
    _validate_analysis_graph(graph, snapshot)


def validate_manifest_artifact_graph(
    graph: CanonicalArtifactGraph,
    *,
    expected_checkpoint: str = PROTOCOL_CHECKPOINT,
) -> None:
    """Validate promoted scientific artifacts plus the persisted manifest."""

    _require_graph_checkpoint(graph, expected_checkpoint)
    if tuple(item.contract.filename for item in graph.artifacts) != MANIFEST_ARTIFACT_NAMES:
        raise ArtifactValidationError("Manifest artifact graph is not exactly artifacts 1-12.")
    audited = CanonicalArtifactGraph(
        graph.artifacts[:11],
        graph.profile,
        graph.source_checkpoint_identifier,
    )
    validate_audited_artifact_graph(audited, expected_checkpoint=expected_checkpoint)
    _validate_manifest_graph(graph, load_protocol_snapshot())


def validate_available_artifact_graph(
    graph: CanonicalArtifactGraph,
    *,
    expected_checkpoint: str = PROTOCOL_CHECKPOINT,
) -> None:
    """Dispatch validation without treating an intentionally staged graph as complete."""

    _require_graph_checkpoint(graph, expected_checkpoint)
    names = tuple(item.contract.filename for item in graph.artifacts)
    if names == PREFINAL_ARTIFACT_NAMES:
        validate_prefinal_artifact_graph(graph, expected_checkpoint=expected_checkpoint)
    elif names == AUDITED_ARTIFACT_NAMES:
        validate_audited_artifact_graph(graph, expected_checkpoint=expected_checkpoint)
    elif names == MANIFEST_ARTIFACT_NAMES:
        validate_manifest_artifact_graph(graph, expected_checkpoint=expected_checkpoint)
    else:
        validate_artifact_graph(graph, expected_checkpoint=expected_checkpoint)


def _decode_artifact(
    contract: ArtifactContract,
    content: bytes,
    *,
    expected_checkpoint: str,
) -> DecodedArtifact:
    if not content.endswith(b"\n"):
        raise ArtifactValidationError(f"{contract.filename} lacks the required final LF.")
    if content.startswith(b"\xef\xbb\xbf"):
        raise ArtifactValidationError(f"{contract.filename} contains a UTF-8 BOM.")
    if contract.format == "JSON":
        return _decode_json(contract, content, expected_checkpoint=expected_checkpoint)
    if contract.format == "JSONL":
        return _decode_jsonl(contract, content, expected_checkpoint=expected_checkpoint)
    if contract.format == "CSV":
        return _decode_csv(contract, content, expected_checkpoint=expected_checkpoint)
    raise ArtifactValidationError(f"{contract.filename} has an unknown artifact format.")


def _decode_json(
    contract: ArtifactContract,
    content: bytes,
    *,
    expected_checkpoint: str,
) -> DecodedArtifact:
    document = _json_object(content, contract.filename)
    if canonical_json_bytes(document, final_lf=True) != content:
        raise ArtifactValidationError(f"{contract.filename} is not canonical JSON.")
    operational_fields = OPERATIONAL_FIELDS.get(contract.filename, frozenset())
    scientific_fields = contract.record_contract.required_fields
    expected_fields = frozenset(ENVELOPE_FIELDS) | scientific_fields | operational_fields
    if frozenset(document) != expected_fields:
        raise ArtifactValidationError(f"{contract.filename} top-level fields differ.")
    _validate_envelope(document, contract, expected_checkpoint=expected_checkpoint)
    scientific = {field: document[field] for field in scientific_fields}
    operational = {field: document[field] for field in operational_fields}
    contract.record_contract.validate(scientific, path=contract.filename)
    scientific_payload = canonical_json_bytes(scientific, final_lf=True)
    if document["scientific_payload_sha256"] != hashlib.sha256(scientific_payload).hexdigest():
        raise ArtifactValidationError(f"{contract.filename} scientific payload hash differs.")
    return DecodedArtifact(contract, scientific, operational, content, scientific_payload)


def _decode_jsonl(
    contract: ArtifactContract,
    content: bytes,
    *,
    expected_checkpoint: str,
) -> DecodedArtifact:
    lines = content.splitlines(keepends=True)
    if len(lines) < 2:
        raise ArtifactValidationError(f"{contract.filename} has no populated data rows.")
    metadata = _json_object(lines[0], f"{contract.filename}.metadata")
    if frozenset(metadata) != frozenset(ENVELOPE_FIELDS):
        raise ArtifactValidationError(f"{contract.filename} metadata fields differ.")
    _validate_envelope(metadata, contract, expected_checkpoint=expected_checkpoint)
    rows: list[dict[str, object]] = []
    for index, line in enumerate(lines[1:]):
        row = _json_object(line, f"{contract.filename}[{index}]")
        if canonical_json_bytes(row, final_lf=True) != line:
            raise ArtifactValidationError(f"{contract.filename}[{index}] is not canonical JSONL.")
        rows.append(row)
    scientific_payload = b"".join(lines[1:])
    if metadata["scientific_payload_sha256"] != hashlib.sha256(scientific_payload).hexdigest():
        raise ArtifactValidationError(f"{contract.filename} scientific payload hash differs.")
    validate_canonical_rows(contract, rows)
    return DecodedArtifact(contract, tuple(rows), {}, content, scientific_payload)


def _decode_csv(
    contract: ArtifactContract,
    content: bytes,
    *,
    expected_checkpoint: str,
) -> DecodedArtifact:
    text = content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != CONTRAST_HEADER:
        raise ArtifactValidationError("contrast_results.csv header differs from the freeze.")
    raw_rows = list(reader)
    if not raw_rows:
        raise ArtifactValidationError("contrast_results.csv has no populated rows.")
    envelope: dict[str, str] | None = None
    rows: list[dict[str, object]] = []
    for index, raw in enumerate(raw_rows):
        current = {field: cast(str, raw[field]) for field in ENVELOPE_FIELDS}
        if envelope is None:
            envelope = current
        elif current != envelope:
            raise ArtifactValidationError("CSV envelope fields are not identical in every row.")
        rows.append(_decode_contrast_row(raw, index))
    assert envelope is not None
    _validate_envelope(envelope, contract, expected_checkpoint=expected_checkpoint)
    scientific_header = CONTRAST_HEADER[len(ENVELOPE_FIELDS) :]
    scientific_payload = _encode_csv(scientific_header, rows)
    if envelope["scientific_payload_sha256"] != hashlib.sha256(scientific_payload).hexdigest():
        raise ArtifactValidationError("contrast_results.csv scientific payload hash differs.")
    rebuilt = _encode_csv(CONTRAST_HEADER, tuple({**envelope, **row} for row in rows))
    if rebuilt != content:
        raise ArtifactValidationError("contrast_results.csv is not canonically serialized.")
    validate_canonical_rows(contract, rows)
    return DecodedArtifact(contract, tuple(rows), {}, content, scientific_payload)


def _validate_envelope(
    document: Mapping[str, object],
    contract: ArtifactContract,
    *,
    expected_checkpoint: str,
) -> None:
    _require_trusted_artifact_checkpoint(expected_checkpoint)
    if document.get("schema_version") != contract.schema_version:
        raise ArtifactValidationError(f"{contract.filename} schema version differs.")
    if document.get("protocol_version") != PROTOCOL_VERSION:
        raise ArtifactValidationError(f"{contract.filename} protocol version differs.")
    snapshot = load_protocol_snapshot()
    if document.get("source_design_sha256") != snapshot.source_design_sha256:
        raise ArtifactValidationError(f"{contract.filename} design hash differs.")
    if document.get("source_checkpoint_identifier") != expected_checkpoint:
        raise ArtifactValidationError(f"{contract.filename} checkpoint differs.")
    validate_sha256(document.get("scientific_payload_sha256"), "scientific_payload_sha256")


def _validate_protocol_snapshot(graph: CanonicalArtifactGraph, snapshot: ProtocolSnapshot) -> None:
    artifact = graph.artifact("protocol_snapshot.json")
    scientific = _mapping(artifact.scientific, "protocol_snapshot.json")
    if scientific != build_protocol_snapshot_payload(snapshot):
        raise ArtifactValidationError(
            "protocol_snapshot.json is not the literal frozen projection."
        )
    operational = artifact.operational
    if operational["design_checkpoint_commit"] != SOURCE_DESIGN_CHECKPOINT:
        raise ArtifactValidationError("Protocol design checkpoint commitment differs.")
    for field in ("design_checkpoint_commit", "design_git_blob_oid"):
        value = operational[field]
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
            raise ArtifactValidationError(f"protocol_snapshot.json.{field} is not GIT40.")
    design_bytes = design_path().read_bytes()
    expected_blob = hashlib.sha1(
        f"blob {len(design_bytes)}\0".encode("ascii") + design_bytes,
        usedforsecurity=False,
    ).hexdigest()
    if operational["design_git_blob_oid"] != expected_blob:
        raise ArtifactValidationError("Protocol design Git blob OID differs.")
    protected = _mapping(operational["protected_source_sha256"], "protected_source_sha256")
    if len(protected) != 13:
        raise ArtifactValidationError("Protected source map does not have 13 files.")
    for value in protected.values():
        validate_sha256(value, "protected_source_sha256 value")


def _validate_world_definitions(graph: CanonicalArtifactGraph, snapshot: ProtocolSnapshot) -> None:
    scientific = _mapping(
        graph.artifact("world_definitions.json").scientific, "world_definitions.json"
    )
    if scientific != build_world_definitions_payload():
        raise ArtifactValidationError("world_definitions.json differs from the frozen worlds.")
    if len(cast(list[object], scientific["worlds"])) != 24:
        raise ArtifactValidationError("world_definitions.json does not contain 24 worlds.")
    if len(cast(list[object], scientific["candidate_catalog"])) != 11:
        raise ArtifactValidationError("Candidate catalog does not contain 11 literal rows.")
    if len(cast(list[object], scientific["cost_catalogs"])) != 3:
        raise ArtifactValidationError("Cost catalog count differs from the freeze.")
    if len(snapshot.registry("budget").rows) != 3:
        raise ArtifactValidationError("Budget registry count differs from the freeze.")


def _validate_dynamic_graph(graph: CanonicalArtifactGraph, snapshot: ProtocolSnapshot) -> None:
    runs = _rows(graph, "arm_runs.jsonl")
    oracle = _rows(graph, "oracle_provenance.jsonl")
    calibration = _rows(graph, "calibration_estimates.jsonl")
    events = _rows(graph, "trajectory_events.jsonl")
    comparisons = _rows(graph, "comparisons.jsonl")
    profile = graph.profile
    _require_count("arm runs", runs, profile.arm_runs)
    _require_count("comparisons", comparisons, profile.comparisons)
    _require_count("calibration estimates", calibration, profile.calibration_estimates)
    _validate_runs(runs, events, comparisons, calibration, snapshot, profile)
    _validate_oracle(oracle, runs, events, calibration)
    _validate_calibration(calibration, runs, oracle, events)
    _validate_events(events, runs, oracle, calibration, snapshot)
    _validate_comparisons(comparisons, runs, events, snapshot)


def _validate_runs(
    runs: Sequence[Mapping[str, object]],
    events: Sequence[Mapping[str, object]],
    comparisons: Sequence[Mapping[str, object]],
    calibration: Sequence[Mapping[str, object]],
    snapshot: ProtocolSnapshot,
    profile: ArtifactCardinalityProfile,
) -> None:
    world_order = {world.public.world_id: index for index, world in enumerate(WORLDS)}
    budget_order = {identifier: index for index, (identifier, _) in enumerate(BUDGETS)}
    arm_by_id = {arm.arm_id: arm for arm in ARMS}
    truth_by_world = {
        world.public.world_id: world.hidden.scientific_hypothesis_id for world in WORLDS
    }
    expected_order = sorted(
        runs,
        key=lambda row: (
            world_order[cast(str, row["world_id"])],
            cast(int, row["seed"]),
            budget_order[cast(str, row["budget_id"])],
            arm_by_id[cast(str, row["arm_id"])].arm_order,
        ),
    )
    if list(runs) != expected_order:
        raise ArtifactValidationError("arm_runs.jsonl row order differs from B.2.")
    _unique(runs, ("run_id",), "arm run PK")
    _unique(runs, ("arm_id", "world_id", "seed", "budget_id"), "arm run alternate key")
    _unique(runs, ("lineage_id",), "lineage")
    _unique(runs, ("store_id",), "store")
    comparison_ids = {cast(str, row["comparison_id"]) for row in comparisons}
    calibration_ids = {cast(str, row["calibration_prefix_id"]) for row in calibration}
    event_by_id = {_event_id(row): row for row in events}
    for row in runs:
        arm_id = cast(str, row["arm_id"])
        world_id = cast(str, row["world_id"])
        seed = cast(int, row["seed"])
        budget_id = cast(str, row["budget_id"])
        budget = _f64_value(row["budget"])
        arm = arm_by_id.get(arm_id)
        if arm is None:
            raise ArtifactValidationError("Arm run references an unknown frozen arm.")
        if row["policy_id"] != arm.policy_id or row["belief_model_id"] != arm.belief_model_id:
            raise ArtifactValidationError("Arm run policy/model does not match arm registry.")
        if row["run_id"] != run_identity(
            arm_id=arm_id, world_id=world_id, seed=seed, budget=budget
        ):
            raise ArtifactValidationError("Arm run ID preimage does not reproduce.")
        expected_comparison = comparison_identity(
            policy_id=arm.policy_id, world_id=world_id, seed=seed, budget=budget
        )
        if row["comparison_id"] != expected_comparison or expected_comparison not in comparison_ids:
            raise ArtifactValidationError("Arm run comparison FK does not resolve.")
        if dict(BUDGETS).get(budget_id) != budget:
            raise ArtifactValidationError("Arm run budget ID/value differs.")
        if row["scientific_hypothesis_id"] != truth_by_world.get(world_id):
            raise ArtifactValidationError("Arm run evaluator truth does not match its world.")
        if row["lineage_id"] != f"lineage/{row['run_id']}":
            raise ArtifactValidationError("Arm run lineage template differs.")
        if row["store_id"] != f"store/{row['run_id']}":
            raise ArtifactValidationError("Arm run store template differs.")
        if row["run_status"] != "complete" or row["terminal_reason"] == "integrity_abort":
            raise ArtifactValidationError("Invalid run entered canonical arm rows.")
        prefixes = _list(row["calibration_prefix_ids"], "calibration_prefix_ids")
        if arm_id.startswith("fixed_"):
            if prefixes or _f64_value(_mapping(row["metrics"], "metrics")["calibration_cost"]):
                raise ArtifactValidationError("Fixed arm has calibration provenance.")
        elif len(prefixes) != 3 or any(item not in calibration_ids for item in prefixes):
            raise ArtifactValidationError("Calibrated arm prefix FKs differ.")
        event_ids = _list(row["event_ids"], "event_ids")
        if any(item not in event_by_id for item in event_ids):
            raise ArtifactValidationError("Arm run event FK does not resolve.")
        owned_events = [event_by_id[cast(str, item)] for item in event_ids]
        if sum(_event_type(item) == "terminal" for item in owned_events) != 1:
            raise ArtifactValidationError("Arm run does not contain exactly one terminal event.")
        if _event_type(owned_events[-1]) != "terminal":
            raise ArtifactValidationError("Arm run terminal event is not last.")
        _validate_run_scientific_values(row, owned_events, truth_by_world[world_id])
        decisions = _list(row["decision_ids"], "decision_ids")
        expected_decision_hash = protocol_hash(
            "ordered_decisions/v1", {"run_id": row["run_id"], "decision_ids": decisions}
        )
        if row["ordered_decisions_sha256"] != expected_decision_hash:
            raise ArtifactValidationError("Arm run ordered-decision hash differs.")
        _validate_run_hashes(row, owned_events)
    if profile.canonical and {cast(int, row["seed"]) for row in runs} != set(FULL_SEEDS):
        raise ArtifactValidationError("Canonical arm rows do not cover all 128 frozen seeds.")


def _validate_run_scientific_values(
    run: Mapping[str, object],
    events: Sequence[Mapping[str, object]],
    true_hypothesis_id: str,
) -> None:
    _validate_probability_map(run["initial_probabilities"], "initial probabilities")
    _validate_probability_map(run["final_probabilities"], "final probabilities")
    posterior_raw = _mapping(run["final_probabilities"], "final probabilities")
    posterior = {key: _f64_value(value) for key, value in posterior_raw.items()}
    metrics = _mapping(run["metrics"], "metrics")
    if set(metrics) != set(METRIC_SET_FIELDS):
        raise ArtifactValidationError("MetricSet fields differ.")
    f64_fields = (
        "true_probability",
        "top_probability",
        "nll",
        "brier",
        "posterior_entropy",
        "decision_cost",
        "calibration_cost",
        "required_total_cost",
        "physical_cost_share",
    )
    values = {field: _f64_value(metrics[field]) for field in f64_fields}
    for field in (
        "conditional_brier_efficiency",
        "end_to_end_brier_efficiency",
        "best_observed_objective",
    ):
        if metrics[field] is not None:
            _f64_value(metrics[field])
    for field in ("prediction_correct", "confidently_wrong", "budget_exhausted"):
        if not isinstance(metrics[field], bool):
            raise ArtifactValidationError(f"MetricSet {field} is not BOOL.")
    for field in (
        "matched_pairs",
        "redundant_selected",
        "irrelevant_selected",
        "outcome_experiments_completed",
        "setup_actions_completed",
    ):
        count = metrics[field]
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ArtifactValidationError(f"MetricSet {field} is not a nonnegative I64.")
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
    expected_scalars = {
        "true_probability": true_probability,
        "top_probability": top_probability,
        "nll": -math.log(max(true_probability, 1e-15)),
        "brier": brier,
        "posterior_entropy": entropy,
    }
    if any(
        not math.isclose(values[field], expected, rel_tol=0.0, abs_tol=1e-12)
        for field, expected in expected_scalars.items()
    ):
        raise ArtifactValidationError("MetricSet belief-quality values do not reproduce.")
    if (
        metrics["top_scientific_hypothesis_id"] != top_id
        or metrics["prediction_correct"] != (top_id == true_hypothesis_id)
        or metrics["confidently_wrong"]
        != (top_probability >= 0.80 and top_id != true_hypothesis_id)
    ):
        raise ArtifactValidationError("MetricSet top-hypothesis fields do not reproduce.")
    payloads = tuple(_event_payload(item) for item in events)
    if tuple(cast(int, item["sequence"]) for item in payloads) != tuple(
        range(1, len(payloads) + 1)
    ):
        raise ArtifactValidationError("Run event sequence is not contiguous from one.")
    decision_ids = [
        _mapping(item["event_specific_payload"], "decision payload")["decision_id"]
        for item in payloads
        if item["event_type"] == "decision"
    ]
    if _list(run["decision_ids"], "decision IDs") != decision_ids:
        raise ArtifactValidationError("Arm run decision IDs differ from decision events.")
    setup_events = tuple(item for item in payloads if item["event_type"] == "setup")
    experiment_events = tuple(item for item in payloads if item["event_type"] == "experiment")
    evidence_events = tuple(item for item in payloads if item["event_type"] == "evidence")
    selected_candidates = [
        cast(str, item["candidate_id"])
        for item in payloads
        if item["event_type"] in {"setup", "experiment"}
    ]
    objectives = [
        _f64_value(_mapping(item["event_specific_payload"], "experiment")["observed_objective"])
        for item in experiment_events
    ]
    expected_counts = {
        "matched_pairs": len(evidence_events),
        "redundant_selected": selected_candidates.count("redundant-objective-r1"),
        "irrelevant_selected": selected_candidates.count("irrelevant-objective-r1"),
        "outcome_experiments_completed": len(experiment_events),
        "setup_actions_completed": len(setup_events),
    }
    if any(metrics[field] != expected for field, expected in expected_counts.items()):
        raise ArtifactValidationError("MetricSet event counts do not reconcile.")
    best_objective = max(objectives) if objectives else None
    if best_objective is None:
        if metrics["best_observed_objective"] is not None:
            raise ArtifactValidationError("MetricSet best objective should be null.")
    elif not math.isclose(
        _f64_value(metrics["best_observed_objective"]), best_objective, abs_tol=1e-12
    ):
        raise ArtifactValidationError("MetricSet best objective does not reproduce.")
    required_cost = values["decision_cost"] + values["calibration_cost"]
    calibrated = run["belief_model_id"] == "replicated_noise_calibrated_gaussian"
    physical_cost = (
        values["decision_cost"] + values["calibration_cost"] / 6.0
        if calibrated
        else values["decision_cost"]
    )
    if not math.isclose(values["required_total_cost"], required_cost, abs_tol=1e-12):
        raise ArtifactValidationError("MetricSet required total cost does not reconcile.")
    if not math.isclose(values["physical_cost_share"], physical_cost, abs_tol=1e-12):
        raise ArtifactValidationError("MetricSet physical cost share does not reconcile.")
    _validate_efficiency(
        metrics["conditional_brier_efficiency"],
        ((2.0 / 3.0) - brier) / values["decision_cost"] if values["decision_cost"] > 0.0 else None,
        "conditional",
    )
    _validate_efficiency(
        metrics["end_to_end_brier_efficiency"],
        ((2.0 / 3.0) - brier) / required_cost if required_cost > 0.0 else None,
        "end-to-end",
    )
    terminal = payloads[-1]
    specific = _mapping(terminal["event_specific_payload"], "TerminalPayload")
    if (
        terminal["terminal_reason"] != run["terminal_reason"]
        or metrics["terminal_reason"] != run["terminal_reason"]
        or metrics["budget_exhausted"] != (run["terminal_reason"] == "budget_exhausted")
    ):
        raise ArtifactValidationError("Run terminal reason does not reconcile.")
    for field in ("decision_cost", "calibration_cost", "required_total_cost"):
        if not math.isclose(_f64_value(specific[field]), values[field], abs_tol=1e-12):
            raise ArtifactValidationError("Terminal cost does not reconcile with MetricSet.")
    completed = _list(specific["completed_candidate_ids"], "completed candidates")
    unexecuted = _list(specific["unexecuted_candidate_ids"], "unexecuted candidates")
    world = next(item.public for item in WORLDS if item.public.world_id == run["world_id"])
    if (
        completed != selected_candidates
        or len(completed) != len(set(completed))
        or len(unexecuted) != len(set(unexecuted))
        or set(completed).intersection(unexecuted)
        or set(completed).union(unexecuted) != set(world.candidate_ids)
    ):
        raise ArtifactValidationError("Terminal candidate partition differs from the world.")
    feasible = _list(specific["publicly_feasible_candidate_ids"], "terminal feasible candidates")
    affordable = _list(specific["affordable_candidate_ids"], "terminal affordable candidates")
    if not set(affordable).issubset(feasible) or not set(feasible).issubset(unexecuted):
        raise ArtifactValidationError("Terminal feasibility sets do not reconcile.")
    if run["terminal_reason"] == "candidate_space_exhausted" and feasible:
        raise ArtifactValidationError("Candidate-space exhaustion retained a feasible candidate.")
    if run["terminal_reason"] == "budget_exhausted" and (not feasible or affordable):
        raise ArtifactValidationError("Budget exhaustion feasibility state differs.")


def _validate_efficiency(observed: object, expected: float | None, label: str) -> None:
    if expected is None:
        if observed is not None:
            raise ArtifactValidationError(f"MetricSet {label} efficiency should be null.")
        return
    if observed is None or not math.isclose(_f64_value(observed), expected, abs_tol=1e-12):
        raise ArtifactValidationError(f"MetricSet {label} efficiency does not reproduce.")


def _validate_run_hashes(run: Mapping[str, object], events: Sequence[Mapping[str, object]]) -> None:
    event_costs: list[dict[str, object]] = []
    provenance: list[str] = []
    for row in events:
        payload = _event_payload(row)
        provenance.append(cast(str, row["provenance_sha256"]))
        if payload["event_type"] in {"setup", "experiment"}:
            specific = _mapping(payload["event_specific_payload"], "event payload")
            event_costs.append(
                {
                    "event_id": payload["event_id"],
                    "record_type": payload["event_type"],
                    "cost": specific["cost"],
                    "cumulative_decision_cost": specific["cumulative_decision_cost"],
                }
            )
    metrics = _mapping(run["metrics"], "metrics")
    reconciliation = protocol_hash(
        "cost_reconciliation/v1",
        {
            "run_id": run["run_id"],
            "ordered_event_costs": event_costs,
            "decision_cost": metrics["decision_cost"],
            "calibration_prefix_ids": _list(run["calibration_prefix_ids"], "prefixes"),
            "calibration_cost": metrics["calibration_cost"],
            "required_total_cost": metrics["required_total_cost"],
            "physical_cost_share": metrics["physical_cost_share"],
        },
    )
    if run["reconciliation_sha256"] != reconciliation:
        raise ArtifactValidationError("Arm run cost reconciliation hash differs.")
    trajectory = protocol_hash(
        "trajectory/v1",
        {
            "run_id": run["run_id"],
            "ordered_decisions_sha256": run["ordered_decisions_sha256"],
            "ordered_real_event_ids": [_event_id(item) for item in events],
            "ordered_event_provenance_sha256": provenance,
            "terminal_reason": run["terminal_reason"],
            "reconciliation_sha256": reconciliation,
        },
    )
    if run["trajectory_sha256"] != trajectory:
        raise ArtifactValidationError("Arm run trajectory hash differs.")


def _validate_oracle(
    rows: Sequence[Mapping[str, object]],
    runs: Sequence[Mapping[str, object]],
    events: Sequence[Mapping[str, object]],
    calibration: Sequence[Mapping[str, object]],
) -> None:
    keys = tuple(row for row in rows if row["record_type"] == "oracle_key")
    uses = tuple(row for row in rows if row["record_type"] == "oracle_use")
    if tuple(rows) != (*keys, *uses):
        raise ArtifactValidationError("Oracle key rows do not precede all use rows.")
    _unique(keys, ("oracle_key_id",), "oracle key")
    _unique(
        keys,
        (
            "namespace",
            "world_id",
            "seed",
            "candidate_id",
            "replication_id",
        ),
        "oracle key tuple",
    )
    _unique(uses, ("oracle_use_id",), "oracle use")
    _unique(uses, ("authorization_id", "oracle_key_id", "run_id"), "oracle use tuple")
    expected_key_order = sorted(
        keys,
        key=lambda row: tuple(
            _utf8_key(row[field])
            for field in ("namespace", "world_id", "seed", "candidate_id", "replication_id")
        ),
    )
    expected_use_order = sorted(
        uses,
        key=lambda row: tuple(
            _utf8_key(row[field]) for field in ("oracle_key_id", "run_id", "use_kind")
        ),
    )
    if list(keys) != expected_key_order or list(uses) != expected_use_order:
        raise ArtifactValidationError("Oracle provenance row ordering differs.")
    key_by_id = {cast(str, row["oracle_key_id"]): row for row in keys}
    run_by_id = {cast(str, row["run_id"]): row for row in runs}
    decision_by_id = {
        cast(str, _mapping(payload["event_specific_payload"], "decision payload")["decision_id"]): (
            payload
        )
        for row in events
        if (payload := _event_payload(row))["event_type"] == "decision"
    }
    prefix_ids = {cast(str, row["calibration_prefix_id"]) for row in calibration}
    for row in keys:
        key_fields = tuple(cast(str, item) for item in _list(row["key_fields"], "key_fields"))
        if row["serialized_key_hex"] != canonical_json_bytes(list(key_fields)).hex():
            raise ArtifactValidationError("Oracle serialized key bytes differ.")
        transformed = transform_key(key_fields)
        if row["digest"] != transformed.digest_hex or row["u"] != transformed.u_string:
            raise ArtifactValidationError("Oracle transform digest or u differs.")
        if row["z"] != transformed.z_string:
            raise ArtifactValidationError("Oracle transform z differs.")
        if row["oracle_key_id"] != runtime_id(
            "oracle-key", "oracle_key_id/v1", {"key_fields": list(key_fields)}
        ):
            raise ArtifactValidationError("Oracle key ID preimage differs.")
        expected_outcome = protocol_hash(
            "revealed_outcome/v1",
            {
                "oracle_key_id": row["oracle_key_id"],
                "revealed_observation": row["revealed_observation"],
            },
        )
        if row["outcome_digest"] != expected_outcome:
            raise ArtifactValidationError("Oracle revealed-outcome hash differs.")
        if row["namespace"] == DECISION_NAMESPACE:
            expected = decision_key(
                world_id=cast(str, row["world_id"]),
                seed=cast(int, row["seed"]),
                candidate_id=cast(str, row["candidate_id"]),
                replication_id=cast(str, row["replication_id"]),
            )
        elif row["namespace"] == CALIBRATION_NAMESPACE:
            expected = calibration_key(
                world_id=cast(str, row["world_id"]),
                seed=cast(int, row["seed"]),
                comparison_group_id=cast(str, row["comparison_group_id"]),
                intervention_arm=cast(str, row["intervention_arm"]),
                replication_id=cast(str, row["replication_id"]),
            )
        else:
            raise ArtifactValidationError("Oracle key has an unknown namespace.")
        if key_fields != expected:
            raise ArtifactValidationError("Oracle canonical key fields differ.")
    for row in uses:
        key = key_by_id.get(cast(str, row["oracle_key_id"]))
        run = run_by_id.get(cast(str, row["run_id"]))
        if key is None or run is None or row["arm_id"] != run["arm_id"]:
            raise ArtifactValidationError("Oracle use key/run/arm FK does not resolve.")
        if key["world_id"] != run["world_id"] or key["seed"] != run["seed"]:
            raise ArtifactValidationError("Oracle use crosses its run world or seed.")
        if row["use_kind"] == "decision":
            decision = decision_by_id.get(cast(str, row["decision_id"]))
            if (
                decision is None
                or row["calibration_prefix_id"] is not None
                or decision["run_id"] != row["run_id"]
                or decision["candidate_id"] != key["candidate_id"]
            ):
                raise ArtifactValidationError("Decision oracle use has invalid source FKs.")
            source_id = cast(str, row["decision_id"])
        elif row["use_kind"] == "calibration":
            expected_prefix = (
                f"calibration-prefix/{key['world_id']}/{key['seed']}/{key['comparison_group_id']}"
            )
            if (
                row["decision_id"] is not None
                or row["calibration_prefix_id"] not in prefix_ids
                or row["calibration_prefix_id"] != expected_prefix
            ):
                raise ArtifactValidationError("Calibration oracle use has invalid source FKs.")
            source_id = f"{expected_prefix}/{key['candidate_id']}"
        else:
            raise ArtifactValidationError("Oracle use kind is not frozen.")
        authorization = authorize_observation(
            run_id=cast(str, row["run_id"]),
            source_id=source_id,
            candidate_id=cast(str, key["candidate_id"]),
            kind=row["use_kind"],
        )
        try:
            expected_observation = reobserve_authorized_observation(
                world_id=cast(str, key["world_id"]),
                seed=cast(int, key["seed"]),
                authorization=authorization,
            )
        except OracleError as error:
            raise ArtifactValidationError(
                "Oracle use cannot be regenerated from the frozen namespace."
            ) from error
        if row["authorization_id"] != authorization.authorization_id:
            raise ArtifactValidationError("Oracle use authorization preimage differs.")
        if row["oracle_use_id"] != expected_observation.oracle_use_id:
            raise ArtifactValidationError("Oracle use ID template differs.")
        if not _oracle_key_matches_reobservation(key, expected_observation):
            raise ArtifactValidationError(
                "Oracle source observation does not reproduce independently."
            )
    use_counts = Counter(cast(str, row["oracle_key_id"]) for row in uses)
    for key_id, key in key_by_id.items():
        if key["namespace"] == CALIBRATION_NAMESPACE and use_counts[key_id] != 6:
            raise ArtifactValidationError("A calibration oracle key does not have six uses.")
        if use_counts[key_id] < 1:
            raise ArtifactValidationError("An oracle key exists without a selected use.")


def _oracle_key_matches_reobservation(
    row: Mapping[str, object], expected: RevealedObservation
) -> bool:
    expected_row: dict[str, object] = {
        "record_type": "oracle_key",
        "oracle_key_id": expected.oracle_key_id,
        "namespace": expected.namespace,
        "world_id": expected.world_id,
        "seed": expected.seed,
        "candidate_id": expected.candidate_id,
        "comparison_group_id": expected.comparison_group_id,
        "intervention_arm": expected.intervention_arm,
        "replication_id": expected.replication_id,
        "key_fields": list(expected.key_fields),
        "serialized_key_hex": expected.serialized_key_hex,
        "digest": expected.digest,
        "u": expected.u,
        "z": expected.z,
        "revealed_observation": f64(expected.revealed_observation),
        "outcome_digest": expected.outcome_digest,
    }
    return dict(row) == expected_row


def _validate_calibration(
    rows: Sequence[Mapping[str, object]],
    runs: Sequence[Mapping[str, object]],
    oracle: Sequence[Mapping[str, object]],
    events: Sequence[Mapping[str, object]],
) -> None:
    _unique(rows, ("sigma_estimate_id",), "sigma estimate")
    _unique(rows, ("calibration_prefix_id",), "calibration prefix")
    _unique(rows, ("world_id", "seed", "comparison_group_id"), "calibration group")
    if any(row["comparison_group_id"] not in GROUP_IDS for row in rows):
        raise ArtifactValidationError("Calibration estimate has an unknown comparison group.")
    expected = sorted(
        rows,
        key=lambda row: (
            _world_index(cast(str, row["world_id"])),
            cast(int, row["seed"]),
            GROUP_IDS.index(cast(str, row["comparison_group_id"])),
        ),
    )
    if list(rows) != expected:
        raise ArtifactValidationError("Calibration estimates are out of frozen order.")
    key_by_id = {
        cast(str, row["oracle_key_id"]): row for row in oracle if row["record_type"] == "oracle_key"
    }
    use_by_id = {
        cast(str, row["oracle_use_id"]): row for row in oracle if row["record_type"] == "oracle_use"
    }
    event_sequences: dict[str, list[int]] = defaultdict(list)
    for event in events:
        payload = _event_payload(event)
        event_sequences[cast(str, payload["run_id"])].append(cast(int, payload["sequence"]))
    for row in rows:
        world_id = cast(str, row["world_id"])
        seed = cast(int, row["seed"])
        group_id = cast(str, row["comparison_group_id"])
        relevant_runs = tuple(
            run
            for run in runs
            if run["world_id"] == world_id
            and run["seed"] == seed
            and run["belief_model_id"] == CALIBRATED_SIGMA_MODEL_ID
        )
        bindings = tuple(
            CalibrationDeploymentBinding(
                run_id=cast(str, run["run_id"]),
                lineage_id=cast(str, run["lineage_id"]),
                world_id=cast(str, run["world_id"]),
                seed=cast(int, run["seed"]),
                budget_id=cast(str, run["budget_id"]),
                arm_id=cast(str, run["arm_id"]),
                belief_model_id=cast(str, run["belief_model_id"]),
                calibration_prefix_ids=tuple(
                    cast(str, item)
                    for item in _list(run["calibration_prefix_ids"], "calibration prefixes")
                ),
            )
            for run in relevant_runs
        )
        try:
            claim = reconstruct_complete_calibration_claim(
                world_id=world_id,
                seed=seed,
                comparison_group_id=group_id,
                deployment_bindings=bindings,
            )
        except (KeyError, ValueError) as error:
            raise ArtifactValidationError(
                "Calibration claim cannot be reconstructed from the frozen graph."
            ) from error
        if dict(row) != claim.artifact_row():
            raise ArtifactValidationError(
                "Persisted calibration estimate differs from independent reconstruction."
            )
        binding_by_run = {item.run_id: item for item in bindings}
        prefix_id = claim.sources.calibration_prefix_id
        for run_id, sources in claim.sources_by_run:
            sequences = event_sequences.get(run_id, [])
            derived_cutoff = min(sequences) if sequences else None
            if derived_cutoff != CALIBRATION_SOURCE_SEQUENCE_CUTOFF or any(
                effect.available_sequence >= CALIBRATION_SOURCE_SEQUENCE_CUTOFF
                for effect in sources.effects
            ):
                raise ArtifactValidationError(
                    "Calibration sources are not strictly prior to trajectory evidence."
                )
            binding = binding_by_run[run_id]
            for observation in sources.observations:
                stored_key = key_by_id.get(observation.oracle_key_id)
                if stored_key is None or not _oracle_key_matches_reobservation(
                    stored_key, observation
                ):
                    raise ArtifactValidationError(
                        "Calibration source key does not match deterministic Oracle re-observation."
                    )
                stored_use = use_by_id.get(observation.oracle_use_id)
                expected_use = {
                    "record_type": "oracle_use",
                    "oracle_use_id": observation.oracle_use_id,
                    "oracle_key_id": observation.oracle_key_id,
                    "run_id": run_id,
                    "arm_id": binding.arm_id,
                    "use_kind": "calibration",
                    "authorization_id": observation.authorization_id,
                    "decision_id": None,
                    "calibration_prefix_id": prefix_id,
                }
                if stored_use is None or dict(stored_use) != expected_use:
                    raise ArtifactValidationError(
                        "Calibration source authorization/use relation differs."
                    )


def _validate_events(
    rows: Sequence[Mapping[str, object]],
    runs: Sequence[Mapping[str, object]],
    oracle: Sequence[Mapping[str, object]],
    calibration: Sequence[Mapping[str, object]],
    snapshot: ProtocolSnapshot,
) -> None:
    _unique(tuple(_event_payload(row) for row in rows), ("event_id",), "event")
    _unique(
        tuple(_event_payload(row) for row in rows),
        ("run_id", "sequence", "event_type"),
        "event alternate key",
    )
    run_by_id = {cast(str, row["run_id"]): row for row in runs}
    oracle_keys = {
        cast(str, row["oracle_key_id"]) for row in oracle if row["record_type"] == "oracle_key"
    }
    oracle_uses = {
        cast(str, row["oracle_use_id"]) for row in oracle if row["record_type"] == "oracle_use"
    }
    calibration_by_id = {cast(str, row["sigma_estimate_id"]): row for row in calibration}
    calibration_by_prefix = {cast(str, row["calibration_prefix_id"]): row for row in calibration}
    event_type_order = {
        "decision": 0,
        "setup": 1,
        "experiment": 2,
        "evidence": 3,
        "belief_update": 4,
        "terminal": 5,
    }
    expected = sorted(
        rows,
        key=lambda row: (
            cast(str, _event_payload(row)["run_id"]),
            cast(int, _event_payload(row)["sequence"]),
            event_type_order[cast(str, _event_payload(row)["event_type"])],
            cast(str, _event_payload(row)["event_id"]),
        ),
    )
    if list(rows) != expected:
        raise ArtifactValidationError("Trajectory event rows are out of frozen order.")
    event_payload_by_id = {_event_id(row): _event_payload(row) for row in rows}
    for row in rows:
        payload = _event_payload(row)
        run = run_by_id.get(cast(str, payload["run_id"]))
        if run is None:
            raise ArtifactValidationError("Event run FK does not resolve.")
        for field in (
            "comparison_id",
            "world_id",
            "seed",
            "budget_id",
            "arm_id",
            "policy_id",
        ):
            if payload[field] != run[field]:
                raise ArtifactValidationError(f"Event {field} differs from its owning run.")
        if payload["belief_lineage_id"] != run["lineage_id"]:
            raise ArtifactValidationError("Event lineage differs from its owning run.")
        expected_event_id = (
            f"event/{payload['run_id']}/{cast(int, payload['sequence']):04d}/"
            f"{payload['event_type']}"
        )
        if payload["event_id"] != expected_event_id:
            raise ArtifactValidationError("Event ID template differs.")
        specific = _mapping(payload["event_specific_payload"], "event payload")
        event_type = cast(str, payload["event_type"])
        if event_type == "experiment" and (
            specific["oracle_key_id"] not in oracle_keys
            or specific["oracle_use_id"] not in oracle_uses
        ):
            raise ArtifactValidationError("Experiment oracle FK does not resolve.")
        if event_type == "evidence":
            source_ids = _list(specific["source_experiment_ids"], "source experiments")
            if len(source_ids) != 2 or len(set(source_ids)) != 2:
                raise ArtifactValidationError(
                    "Evidence does not reference exactly two experiments."
                )
            for experiment_id in source_ids:
                source = event_payload_by_id.get(cast(str, experiment_id))
                if (
                    source is None
                    or source["event_type"] != "experiment"
                    or cast(int, source["sequence"]) >= cast(int, payload["sequence"])
                ):
                    raise ArtifactValidationError("Evidence source experiment FK does not resolve.")
                source_candidate = CANDIDATES_BY_ID.get(cast(str, source["candidate_id"]))
                if (
                    source_candidate is None
                    or source_candidate.comparison_group_id != specific["comparison_group_id"]
                ):
                    raise ArtifactValidationError(
                        "Evidence comparison group differs from its source experiments."
                    )
        if event_type == "belief_update":
            evidence = event_payload_by_id.get(cast(str, specific["evidence_id"]))
            if (
                evidence is None
                or evidence["event_type"] != "evidence"
                or cast(int, evidence["sequence"]) >= cast(int, payload["sequence"])
            ):
                raise ArtifactValidationError("Belief update evidence FK does not resolve.")
        sigma_id = payload["sigma_estimate_id"]
        calibrated = run["belief_model_id"] == CALIBRATED_SIGMA_MODEL_ID
        expected_group: str | None = None
        if event_type == "experiment":
            candidate = CANDIDATES_BY_ID.get(cast(str, payload["candidate_id"]))
            if candidate is None:
                raise ArtifactValidationError("Experiment candidate does not resolve.")
            if candidate.comparison_group_id in GROUP_IDS:
                expected_group = candidate.comparison_group_id
        elif event_type == "evidence":
            expected_group = cast(str, specific["comparison_group_id"])
        elif event_type == "belief_update":
            expected_group = cast(
                str,
                _mapping(
                    cast(Mapping[str, object], evidence)["event_specific_payload"],
                    "evidence payload",
                )["comparison_group_id"],
            )
        if expected_group is not None and expected_group not in GROUP_IDS:
            raise ArtifactValidationError("Event comparison group is not frozen.")
        sigma_required = calibrated and expected_group is not None
        if (sigma_id is not None) != sigma_required:
            raise ArtifactValidationError(
                "Event singular sigma nullability differs from its arm and comparison group."
            )
        if sigma_id is not None:
            sigma = calibration_by_id.get(cast(str, sigma_id))
            if sigma is None:
                raise ArtifactValidationError("Event sigma-estimate FK does not resolve.")
            expected_prefix = f"calibration-prefix/{run['world_id']}/{run['seed']}/{expected_group}"
            run_prefixes = _list(run["calibration_prefix_ids"], "run calibration prefixes")
            if (
                sigma["world_id"] != run["world_id"]
                or sigma["seed"] != run["seed"]
                or sigma["comparison_group_id"] != expected_group
                or sigma["target_comparison_group_id"] != expected_group
                or sigma["calibration_prefix_id"] != expected_prefix
                or expected_prefix not in run_prefixes
            ):
                raise ArtifactValidationError(
                    "Event sigma estimate differs from its owning run or applicable group."
                )
        if event_type == "decision":
            _validate_decision_payload(specific, payload, run, snapshot)
            active = _list(specific["active_sigma_estimate_ids"], "active sigma IDs")
            expected_active = [
                calibration_by_prefix[cast(str, prefix_id)]["sigma_estimate_id"]
                for prefix_id in _list(run["calibration_prefix_ids"], "run calibration prefixes")
                if cast(str, prefix_id) in calibration_by_prefix
            ]
            if active != expected_active:
                raise ArtifactValidationError(
                    "Decision active sigma estimates differ from its owning run."
                )
    for run_id in run_by_id:
        owned = tuple(
            _event_payload(row) for row in rows if _event_payload(row)["run_id"] == run_id
        )
        decisions = tuple(item for item in owned if item["event_type"] == "decision")
        actions = tuple(item for item in owned if item["event_type"] in {"setup", "experiment"})
        if len(decisions) != len(actions):
            raise ArtifactValidationError("Decision/action event cardinality differs.")
        for decision, action in zip(decisions, actions, strict=True):
            decision_specific = _mapping(decision["event_specific_payload"], "decision payload")
            action_specific = _mapping(action["event_specific_payload"], "action payload")
            if (
                decision_specific["decision_id"] != action_specific["decision_id"]
                or decision_specific["selected_candidate_id"] != action["candidate_id"]
                or decision["candidate_id"] != action["candidate_id"]
            ):
                raise ArtifactValidationError("Decision/action provenance does not reconcile.")
        evidence_ids = {
            cast(str, _mapping(item["event_specific_payload"], "evidence")["evidence_id"])
            for item in owned
            if item["event_type"] == "evidence"
        }
        update_ids = [
            cast(str, _mapping(item["event_specific_payload"], "update")["evidence_id"])
            for item in owned
            if item["event_type"] == "belief_update"
        ]
        evidence_event_ids = {
            cast(str, item["event_id"]) for item in owned if item["event_type"] == "evidence"
        }
        if len(update_ids) != len(evidence_ids) or set(update_ids) != evidence_event_ids:
            raise ArtifactValidationError("Evidence/belief-update chronology is not one-to-one.")


def _validate_decision_payload(
    specific: Mapping[str, object],
    common: Mapping[str, object],
    run: Mapping[str, object],
    snapshot: ProtocolSnapshot,
) -> None:
    scores = _list(specific["candidate_scores"], "candidate_scores")
    ranks: list[int] = []
    candidate_ids: list[str] = []
    for raw in scores:
        score = _mapping(raw, "CandidateScore")
        required = {
            "candidate_id",
            "public_effect",
            "immediate_eig",
            "expected_total_eig",
            "expected_cost",
            "eig_per_cost",
            "rank",
            "ranking_reason",
        }
        if set(score) != required:
            raise ArtifactValidationError("CandidateScore fields differ.")
        candidate_ids.append(cast(str, score["candidate_id"]))
        ranks.append(cast(int, score["rank"]))
        for field in ("immediate_eig", "expected_total_eig", "expected_cost", "eig_per_cost"):
            _f64_value(score[field])
    if len(candidate_ids) != len(set(candidate_ids)) or ranks != list(range(1, len(ranks) + 1)):
        raise ArtifactValidationError("Candidate score uniqueness/rank order differs.")
    branches = _list(specific["planning_branch_tree"], "planning_branch_tree")
    branch_ids: set[str] = set()
    probability = 0.0
    for raw in branches:
        branch = _mapping(raw, "PlanningBranchTrace")
        required = {
            "planning_branch_id",
            "label",
            "probability",
            "evidence_lower",
            "evidence_upper",
            "posterior",
            "posterior_entropy",
            "second_candidate_id",
            "second_public_effect",
            "second_eig",
            "second_cost",
            "terminal_entropy",
            "total_cost",
            "budget_feasible",
        }
        if set(branch) != required:
            raise ArtifactValidationError("PlanningBranchTrace fields differ.")
        branch_id = cast(str, branch["planning_branch_id"])
        if branch_id in branch_ids:
            raise ArtifactValidationError("Planning branch ID is duplicated within a decision.")
        branch_ids.add(branch_id)
        probability += _f64_value(branch["probability"])
        _validate_probability_map(branch["posterior"], "planning posterior")
    if branches and not math.isclose(probability, 1.0, abs_tol=1e-12):
        raise ArtifactValidationError("Planning branch probabilities do not normalize.")
    if specific["selected_candidate_id"] != common["candidate_id"]:
        raise ArtifactValidationError("Selected decision candidate differs from common event.")
    active = _list(specific["active_sigma_estimate_ids"], "active sigma IDs")
    fixed = run["belief_model_id"] == "fixed_sigma_gaussian"
    if (
        fixed != (specific["fixed_sigma"] is not None)
        or (fixed and active)
        or (not fixed and len(active) != 3)
    ):
        raise ArtifactValidationError("Decision sigma-model provenance differs.")
    if specific["tie_break_order"] != [
        "greater_expected_total_information_gain",
        "lower_expected_total_cost",
        "greater_information_gain_per_expected_cost",
        "stable_lexicographic_candidate_id",
    ]:
        raise ArtifactValidationError("Decision tie-break order differs from the freeze.")


def _validate_comparisons(
    rows: Sequence[Mapping[str, object]],
    runs: Sequence[Mapping[str, object]],
    events: Sequence[Mapping[str, object]],
    snapshot: ProtocolSnapshot,
) -> None:
    _unique(rows, ("comparison_id",), "comparison")
    _unique(rows, ("policy_id", "world_id", "seed", "budget_id"), "comparison tuple")
    policy_order = {"information_gain": 0, "lookahead_information_gain": 1}
    expected = sorted(
        rows,
        key=lambda row: (
            policy_order[cast(str, row["policy_id"])],
            _world_index(cast(str, row["world_id"])),
            cast(int, row["seed"]),
            dict(BUDGETS)[cast(str, row["budget_id"])],
        ),
    )
    if list(rows) != expected:
        raise ArtifactValidationError("Comparison rows are out of frozen order.")
    run_by_id = {cast(str, row["run_id"]): row for row in runs}
    candidate_sequence_by_run: dict[str, list[object]] = {}
    event_payloads_by_run: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for event in events:
        payload = _event_payload(event)
        event_payloads_by_run[cast(str, payload["run_id"])].append(payload)
        if payload["event_type"] != "decision":
            continue
        specific = _mapping(payload["event_specific_payload"], "decision payload")
        candidate_sequence_by_run.setdefault(cast(str, payload["run_id"]), []).append(
            specific["selected_candidate_id"]
        )
    mechanisms = set(snapshot.registry("mechanism").ids("mechanism_id"))
    actionable = tuple(
        row["mechanism_id"]
        for row in snapshot.registry("mechanism").records()
        if row["actionable"] == "true"
    )
    for row in rows:
        fixed = run_by_id.get(cast(str, row["fixed_run_id"]))
        calibrated = run_by_id.get(cast(str, row["calibrated_run_id"]))
        if fixed is None or calibrated is None or fixed is calibrated:
            raise ArtifactValidationError("Comparison run FKs do not resolve distinctly.")
        for run in (fixed, calibrated):
            for field in ("comparison_id", "policy_id", "world_id", "seed", "budget_id", "budget"):
                if run[field] != row[field]:
                    raise ArtifactValidationError("Comparison condition differs from a paired run.")
        if (
            fixed["belief_model_id"] != "fixed_sigma_gaussian"
            or calibrated["belief_model_id"] != "replicated_noise_calibrated_gaussian"
        ):
            raise ArtifactValidationError("Comparison fixed/calibrated model ownership differs.")
        fixed_metrics = _mapping(fixed["metrics"], "fixed metrics")
        calibrated_metrics = _mapping(calibrated["metrics"], "calibrated metrics")
        for field, comparison_field in (
            ("nll", "nll_difference"),
            ("brier", "brier_difference"),
            ("decision_cost", "decision_cost_difference"),
        ):
            expected_difference = _f64_value(calibrated_metrics[field]) - _f64_value(
                fixed_metrics[field]
            )
            if not math.isclose(
                _f64_value(row[comparison_field]), expected_difference, abs_tol=1e-12
            ):
                raise ArtifactValidationError("Comparison metric difference does not reproduce.")
        if row["fixed_sequence"] != candidate_sequence_by_run.get(cast(str, fixed["run_id"]), []):
            raise ArtifactValidationError("Fixed comparison sequence differs from run events.")
        if row["calibrated_sequence"] != candidate_sequence_by_run.get(
            cast(str, calibrated["run_id"]), []
        ):
            raise ArtifactValidationError("Calibrated comparison sequence differs from run events.")
        if row["record_type"] == "nondivergent":
            if (
                row["fixed_sequence"] != row["calibrated_sequence"]
                or row["outcome_label"] != "nondivergent"
            ):
                raise ArtifactValidationError("Nondivergent comparison has divergent sequences.")
            continue
        fixed_sequence = _list(row["fixed_sequence"], "fixed comparison sequence")
        calibrated_sequence = _list(row["calibrated_sequence"], "calibrated comparison sequence")
        first_index = next(
            (
                index
                for index, (left, right) in enumerate(
                    zip(fixed_sequence, calibrated_sequence, strict=False)
                )
                if left != right
            ),
            min(len(fixed_sequence), len(calibrated_sequence)),
        )
        first_step = first_index + 1
        fixed_candidate = fixed_sequence[first_index] if first_index < len(fixed_sequence) else None
        calibrated_candidate = (
            calibrated_sequence[first_index] if first_index < len(calibrated_sequence) else None
        )
        sequence_class = (
            "same_experiment_set_different_order"
            if set(fixed_sequence) == set(calibrated_sequence)
            else "different_experiment_set"
        )
        if (
            row["first_divergence_step"] != first_step
            or row["fixed_candidate_id"] != fixed_candidate
            or row["calibrated_candidate_id"] != calibrated_candidate
            or row["first_action_divergent"] != (first_step == 1)
            or row["sequence_class"] != sequence_class
        ):
            raise ArtifactValidationError(
                "Comparison divergence location or sequence class does not reproduce."
            )
        _validate_pre_divergence_snapshot(
            _mapping(row["pre_divergence_fixed_belief"], "fixed pre-divergence belief"),
            fixed,
            event_payloads_by_run[cast(str, fixed["run_id"])],
            first_step,
        )
        _validate_pre_divergence_snapshot(
            _mapping(
                row["pre_divergence_calibrated_belief"],
                "calibrated pre-divergence belief",
            ),
            calibrated,
            event_payloads_by_run[cast(str, calibrated["run_id"])],
            first_step,
        )
        if row["outcome_label"] not in {"helped", "hurt", "mixed"}:
            raise ArtifactValidationError("Divergent comparison outcome label differs.")
        nll_difference = _f64_value(row["nll_difference"])
        brier_difference = _f64_value(row["brier_difference"])
        expected_outcome = (
            "helped"
            if nll_difference < -1e-12 and brier_difference < -1e-12
            else "hurt"
            if nll_difference > 1e-12 and brier_difference > 1e-12
            else "mixed"
        )
        if row["outcome_label"] != expected_outcome:
            raise ArtifactValidationError("Divergent outcome label does not reproduce.")
        predicate_results = _mapping(row["predicate_results"], "predicate_results")
        if set(predicate_results) != set(actionable):
            raise ArtifactValidationError("Comparison predicate map order or ownership differs.")
        if not all(isinstance(value, bool) for value in predicate_results.values()):
            raise ArtifactValidationError("Comparison predicate results must be BOOL.")
        if row["primary_mechanism_id"] not in mechanisms:
            raise ArtifactValidationError("Comparison primary mechanism does not resolve.")
        contributing = _list(row["contributing_mechanism_ids"], "contributing mechanisms")
        if len(contributing) != len(set(contributing)) or any(
            item not in mechanisms for item in contributing
        ):
            raise ArtifactValidationError("Comparison contributing mechanisms differ.")
        hash_payload = {
            "comparison_id": row["comparison_id"],
            "policy_id": row["policy_id"],
            "first_divergence_step": row["first_divergence_step"],
            "fixed_candidate_id": row["fixed_candidate_id"],
            "calibrated_candidate_id": row["calibrated_candidate_id"],
            "fixed_sequence": row["fixed_sequence"],
            "calibrated_sequence": row["calibrated_sequence"],
            "first_action_divergent": row["first_action_divergent"],
            "sequence_class": row["sequence_class"],
            "predicate_results": row["predicate_results"],
            "primary_mechanism_id": row["primary_mechanism_id"],
            "contributing_mechanism_ids": row["contributing_mechanism_ids"],
            "controller_stage_id": row["controller_stage_id"],
        }
        if row["mechanism_row_without_outcome_sha256"] != protocol_hash(
            "truth_free_mechanism_row/v1", hash_payload
        ):
            raise ArtifactValidationError("Truth-free mechanism-row hash differs.")


def _validate_pre_divergence_snapshot(
    stored: Mapping[str, object],
    run: Mapping[str, object],
    events: Sequence[Mapping[str, object]],
    first_divergence_step: int,
) -> None:
    probabilities = _mapping(run["initial_probabilities"], "initial probabilities")
    target_state_id: object | None = None
    for event in events:
        specific = _mapping(event["event_specific_payload"], "event payload")
        if event["event_type"] == "decision":
            if specific["step"] == first_divergence_step:
                target_state_id = specific["belief_state_id"]
                break
        elif event["event_type"] == "belief_update":
            belief_after = _mapping(specific["belief_after"], "belief after")
            probabilities = _mapping(belief_after["probabilities"], "belief-after probabilities")
    if target_state_id is None:
        terminal = next(
            (item for item in reversed(events) if item["event_type"] == "terminal"), None
        )
        if terminal is None:
            raise ArtifactValidationError("Divergence step has no source state event.")
        target_state_id = _mapping(terminal["event_specific_payload"], "terminal payload")[
            "final_belief_state_id"
        ]
        probabilities = _mapping(run["final_probabilities"], "final probabilities")
    numeric = {key: _f64_value(value) for key, value in probabilities.items()}
    entropy = -math.fsum(
        probability * math.log2(probability)
        for probability in numeric.values()
        if probability > 0.0
    )
    if (
        stored["belief_state_id"] != target_state_id
        or stored["lineage_id"] != run["lineage_id"]
        or stored["sequence"] != first_divergence_step - 1
        or _mapping(stored["probabilities"], "stored probabilities") != probabilities
        or not math.isclose(
            _f64_value(stored["posterior_entropy"]), entropy, rel_tol=0.0, abs_tol=1e-12
        )
    ):
        raise ArtifactValidationError("Pre-divergence belief snapshot does not reproduce.")


def _validate_analysis_graph(graph: CanonicalArtifactGraph, snapshot: ProtocolSnapshot) -> None:
    contrasts = _rows(graph, "contrast_results.csv")
    resampling = _rows(graph, "resampling_audit.jsonl")
    gate_payload = _mapping(
        graph.artifact("gate_evaluations.json").scientific, "gate_evaluations.json"
    )
    _validate_contrasts(contrasts, snapshot)
    _validate_resampling(resampling, snapshot, graph.profile)
    _validate_raw_resampling_statistics(graph, contrasts, resampling, snapshot)
    _validate_resampling_aggregation(contrasts, resampling, snapshot, graph.profile)
    _validate_gate_payload(gate_payload, snapshot)
    _recompute_gate_graph(graph, snapshot, contrasts, gate_payload)


def _validate_prefinal_analysis_graph(
    graph: CanonicalArtifactGraph, snapshot: ProtocolSnapshot
) -> None:
    contrasts = _rows(graph, "contrast_results.csv")
    resampling = _rows(graph, "resampling_audit.jsonl")
    _validate_contrasts(contrasts, snapshot)
    _validate_resampling(resampling, snapshot, graph.profile)
    _validate_raw_resampling_statistics(graph, contrasts, resampling, snapshot)
    _validate_resampling_aggregation(contrasts, resampling, snapshot, graph.profile)


def _recompute_gate_graph(
    graph: CanonicalArtifactGraph,
    snapshot: ProtocolSnapshot,
    contrasts: Sequence[Mapping[str, object]],
    payload: Mapping[str, object],
) -> None:
    """Rebuild every gate and the final decision from upstream canonical rows."""

    contrast_by_id = {cast(str, row["contrast_id"]): row for row in contrasts}
    comparisons = _rows(graph, "comparisons.jsonl")
    audit_payload = _mapping(graph.artifact("audit_results.json").scientific, "audit_results.json")
    audit_statuses: dict[str, GateStatus] = {}
    for raw in _list(audit_payload["audits"], "audits"):
        row = _mapping(raw, "AuditResult")
        try:
            status = GateStatus(cast(str, row["status"]))
        except ValueError as error:
            raise ArtifactValidationError("Audit status is not frozen.") from error
        audit_statuses[cast(str, row["audit_id"])] = status
    gate_rows = tuple(_mapping(raw, "GateEvaluation") for raw in _list(payload["gates"], "gates"))
    outputs: dict[str, object] = {}
    vetoes = _recompute_vetoes(payload, snapshot, contrast_by_id)
    actionability: ActionabilityResult | None = None
    partition: ActionPartition | None = None

    for gate in gate_rows:
        gate_id = cast(str, gate["gate_id"])
        formula_id = cast(str, gate["formula_id"])
        condition = _first_condition(gate)
        raw_operand_ids = tuple(
            cast(str, item) for item in _list(condition["ordered_operand_ids"], "gate operand IDs")
        )
        values: dict[str, object]
        if formula_id == "F-INTEGRITY":
            values = dict(audit_statuses)
        elif formula_id == "F-CORE":
            values = {
                "COUNT-ARM-RUNS": len(_rows(graph, "arm_runs.jsonl")),
                "COUNT-COMPARISONS": len(comparisons),
                "COUNT-SIGMA-ROWS": len(_rows(graph, "calibration_estimates.jsonl")),
                "COUNT-CONTRAST-ROWS": len(contrasts),
                "FK-ALL": True,
            }
        elif formula_id == "F-CAL":
            semantic = (
                "policy_nll",
                "policy_brier",
                "policy_ece",
                "policy_confidently_wrong",
                "policy_true_probability",
            )
            values = {
                name: _contrast_inference(contrast_by_id[contrast_id])
                for name, contrast_id in zip(semantic, raw_operand_ids, strict=True)
            }
        elif formula_id == "F-AND":
            values = {
                "ordered_gate_status_operands": tuple(
                    _gate_output_status(outputs[operand_id]) for operand_id in raw_operand_ids
                )
            }
        elif formula_id == "F-HARD-SAFETY":
            values = {
                contrast_id: _contrast_inference(contrast_by_id[contrast_id])
                for contrast_id in raw_operand_ids
            }
        elif formula_id == "F-CTRL":
            by_metric = {
                cast(str, contrast_by_id[contrast_id]["metric_id"]): _contrast_inference(
                    contrast_by_id[contrast_id]
                )
                for contrast_id in raw_operand_ids
                if contrast_id.startswith("BR-")
            }
            values = {
                "policy_nll": by_metric["nll"],
                "policy_brier": by_metric["brier"],
                "policy_true_probability": by_metric["true_probability"],
                "policy_confidently_wrong": by_metric["confidently_wrong"],
                "policy_helped_minus_hurt": by_metric["harm_risk"],
                "policy_conditional_efficiency": by_metric["conditional_brier_efficiency"],
                "policy_end_to_end_efficiency": by_metric["end_to_end_brier_efficiency"],
                "G-HARD-SAFETY": _gate_output_status(outputs["G-HARD-SAFETY"]),
            }
        elif formula_id == "F-CONCENTRATION":
            item = contrast_by_id[raw_operand_ids[0]]
            values = {
                "target_divergent_count": item["n_present"],
                "comparator_divergent_count": item["n_absent"],
                "contrast_estimate": _optional_f64_value(item["estimate"]),
                "ci_low": _optional_f64_value(item["ci_low"]),
                "p_adjusted": _optional_f64_value(item["p_adjusted"]),
            }
        elif formula_id == "F-DOMINANCE":
            item = contrast_by_id[raw_operand_ids[0]]
            policy_id = (
                "information_gain" if gate_id.endswith("-IG") else "lookahead_information_gain"
            )
            classifiable = tuple(
                row
                for row in comparisons
                if row["policy_id"] == policy_id and row["record_type"] == "divergent"
            )
            primary = Counter(cast(str, row["primary_mechanism_id"]) for row in classifiable)
            denominator = len(classifiable)
            values = {
                "classifiable_count": denominator,
                "combined_primary_share": _optional_f64_value(item["estimate"]),
                "ci_low": _optional_f64_value(item["ci_low"]),
                "score_flattening_share": (
                    primary["SCORE_FLATTENING"] / denominator if denominator else None
                ),
                "group_sigma_reordering_share": (
                    primary["GROUP_SIGMA_REORDERING"] / denominator if denominator else None
                ),
            }
        elif formula_id == "F-ORDER":
            item = contrast_by_id[raw_operand_ids[0]]
            values = {
                "present_count": item["n_present"],
                "absent_count": item["n_absent"],
                "contrast_estimate": _optional_f64_value(item["estimate"]),
                "ci_low": _optional_f64_value(item["ci_low"]),
                "p_adjusted": _optional_f64_value(item["p_adjusted"]),
            }
        elif formula_id == "F-ACTION":
            decision_row = contrast_by_id[raw_operand_ids[0]]
            source_row = contrast_by_id[raw_operand_ids[1]]
            decision_specification = next(
                row for row in snapshot.registry("decision").records() if row["gate_id"] == gate_id
            )
            source_specification = next(
                row
                for row in snapshot.registry("confirmatory").records()
                if row["contrast_id"] == decision_specification["source_contrast_id"]
            )
            mechanism_id = _artifact_mechanism_for(source_specification, snapshot)
            actionable_mechanisms = tuple(
                row["mechanism_id"]
                for row in snapshot.registry("mechanism").records()
                if row["actionable"] == "true"
            )
            source = _contrast_inference(source_row)
            blocks = _actionability_blocks_from_condition(condition)
            _validate_actionability_block_derivations(condition, source.estimate)
            n_present = cast(int | None, source_row["n_present"]) or 0
            n_absent = cast(int | None, source_row["n_absent"]) or 0
            total = n_present + n_absent
            composite = ActionabilityComposite(
                source,
                cast(int | None, source_row["n_present"]),
                cast(int | None, source_row["n_absent"]),
                _optional_f64_value(source_row["present_weight"]),
                _optional_f64_value(source_row["absent_weight"]),
                n_present / total if total else None,
                blocks,
            )
            copied_fields = (
                "n_present",
                "n_absent",
                "present_weight",
                "absent_weight",
                "left_value",
                "right_value",
                "left_denominator",
                "right_denominator",
                "estimate",
                "result_status",
                "estimability_status",
            )
            if any(decision_row[field] != source_row[field] for field in copied_fields):
                raise ArtifactValidationError(
                    "Decision contrast does not reproduce its source row."
                )
            values = {
                "decision_contrast": composite,
                "source_confirmatory_contrast": source,
                "five_actionability_blocks": blocks,
                "mechanism_allowlist": mechanism_id in actionable_mechanisms,
                "truth_free_provenance": all(
                    row["record_type"] == "nondivergent"
                    or (
                        row["primary_mechanism_id"] is not None
                        and row["mechanism_row_without_outcome_sha256"] is not None
                    )
                    for row in comparisons
                ),
            }
        elif formula_id == "F-ACTION-COMPLETE":
            values = {
                "ordered_20_action_gate_statuses": tuple(
                    _gate_output_status(outputs[item]) for item in raw_operand_ids
                )
            }
        elif formula_id == "F-CONTROLLER-CHANGE":
            values = {item: _gate_output_status(outputs[item]) for item in raw_operand_ids}
        elif formula_id == "F-VETO-COMPLETE":
            if actionability is None:
                raise ArtifactValidationError("Veto gate precedes actionability output.")
            values = {
                "P_RAW": actionability.p_raw,
                "ordered_20_veto_evaluations": vetoes,
            }
        elif formula_id == "F-UNIQUE-MECHANISM":
            if partition is None:
                raise ArtifactValidationError("Unique-mechanism gate precedes veto partition.")
            values = {"P": partition.surviving_tuples, "VETO_COMPLETE": partition.veto_complete}
        elif formula_id == "F-B-AUTHORIZATION":
            if actionability is None or partition is None:
                raise ArtifactValidationError("B authorization lacks actionability or partition.")
            values = {
                "CONTROLLER_CHANGE_NEEDED": cast(DecisionBoolean, outputs["G-CONTROLLER-CHANGE"]),
                "ACTIONABILITY_COMPLETE": actionability.actionability_complete,
                "VETO_COMPLETE": partition.veto_complete,
                "P_RAW": actionability.p_raw,
                "ordered_20_veto_evaluations": vetoes,
                "P": partition.surviving_tuples,
                "UNIQUE_ACTIONABLE_MECHANISM": cast(
                    DecisionBoolean, outputs["G-UNIQUE-ACTIONABLE-MECHANISM"]
                ),
            }
        elif formula_id == "F-PPO":
            if partition is None:
                raise ArtifactValidationError("PPO gate precedes veto partition.")
            values = {
                "G-INTEGRITY": _gate_output_status(outputs["G-INTEGRITY"]),
                "G-CORE": _gate_output_status(outputs["G-CORE"]),
                "G-CAL-BOTH": _gate_output_status(outputs["G-CAL-BOTH"]),
                "G-CTRL-BOTH": _gate_output_status(outputs["G-CTRL-BOTH"]),
                "G-HARD-SAFETY": _gate_output_status(outputs["G-HARD-SAFETY"]),
                "G-ACTIONABILITY-COMPLETE": _gate_output_status(
                    outputs["G-ACTIONABILITY-COMPLETE"]
                ),
                "VETO_COMPLETE": partition.veto_complete,
                "P": partition.surviving_tuples,
                "CONTROLLER_CHANGE_NEEDED": cast(DecisionBoolean, outputs["G-CONTROLLER-CHANGE"]),
            }
        elif formula_id == "F-DECISION-TABLE":
            if partition is None:
                raise ArtifactValidationError("Final gate precedes veto partition.")
            values = {
                "G-B-AUTHORIZATION": _gate_output_status(outputs["G-B-AUTHORIZATION"]),
                "B_AUTHORIZED": cast(DecisionBoolean, outputs["G-B-AUTHORIZATION"]),
                "VETO_COMPLETE": partition.veto_complete,
                "CONTROLLER_CHANGE_NEEDED": cast(DecisionBoolean, outputs["G-CONTROLLER-CHANGE"]),
                "PPO_ELIGIBLE": cast(DecisionBoolean, outputs["G-PPO"]),
                "ordered_branch_registry": snapshot.registry("branch").records(),
            }
        else:
            raise ArtifactValidationError(f"Gate {gate_id} uses unsupported formula {formula_id}.")

        output = _execute_exact_formula(snapshot, formula_id, values)
        outputs[gate_id] = output
        recomputed_status = _gate_output_status(output)
        if gate["gate_status"] != recomputed_status.value:
            raise ArtifactValidationError(f"Gate {gate_id} status disagrees with recomputation.")
        for raw_condition in _list(gate["conditions"], "gate conditions"):
            stored_condition = _mapping(raw_condition, "GateConditionEvaluation")
            if stored_condition["gate_status_result"] is not None and (
                stored_condition["gate_status_result"] != recomputed_status.value
            ):
                raise ArtifactValidationError(
                    f"Gate {gate_id} condition status disagrees with recomputation."
                )
        if isinstance(output, ActionabilityResult):
            actionability = output
        if formula_id == "F-VETO-COMPLETE":
            partition = cast(
                ActionPartition,
                _execute_exact_formula(
                    snapshot,
                    "F-P",
                    {
                        "P_RAW": cast(ActionabilityResult, actionability).p_raw,
                        "ordered_20_veto_evaluations": vetoes,
                    },
                ),
            )

    _compare_recomputed_decision_payload(payload, outputs, actionability, partition)
    _validate_gate_operand_rows(
        graph,
        snapshot,
        gate_rows,
        contrasts=contrast_by_id,
        comparisons=comparisons,
        audit_statuses=audit_statuses,
        outputs=outputs,
        actionability=cast(ActionabilityResult, actionability),
        partition=cast(ActionPartition, partition),
        vetoes=vetoes,
    )


def _execute_exact_formula(
    snapshot: ProtocolSnapshot, formula_id: str, values: Mapping[str, object]
) -> object:
    specification = next(
        row for row in snapshot.registry("formula").records() if row["formula_id"] == formula_id
    )
    ordered_ids = tuple(specification["ordered_operand_ids"].split(";"))
    if set(values) != set(ordered_ids):
        raise ArtifactValidationError(
            f"Formula {formula_id} reconstruction has missing or unknown semantic operands."
        )
    return execute_formula(formula_id, {item: values[item] for item in ordered_ids})


def _first_condition(gate: Mapping[str, object]) -> Mapping[str, object]:
    conditions = _list(gate["conditions"], "gate conditions")
    if not conditions:
        raise ArtifactValidationError("Gate lacks its first frozen condition.")
    return _mapping(conditions[0], "GateConditionEvaluation")


def _contrast_inference(row: Mapping[str, object]) -> ContrastInference:
    status = cast(str, row["result_status"])
    return ContrastInference(
        _optional_f64_value(row["estimate"]),
        _optional_f64_value(row["ci_low"]),
        _optional_f64_value(row["ci_high"]),
        _optional_f64_value(row["p_adjusted"]),
        cast(Literal["ESTIMATED", "INCONCLUSIVE"], status),
    )


def _optional_f64_value(value: object) -> float | None:
    return None if value is None else _f64_value(value)


def _gate_output_status(output: object) -> GateStatus:
    if isinstance(output, GateStatus):
        return output
    if isinstance(output, DecisionBoolean):
        return output.status
    if isinstance(output, ActionabilityResult):
        return output.actionability_complete.status
    if isinstance(output, BranchDecision):
        return output.gate_status
    raise ArtifactValidationError("Recomputed gate produced an unsupported output type.")


def _actionability_blocks_from_condition(
    condition: Mapping[str, object],
) -> tuple[ActionabilityBlock, ...]:
    return tuple(
        ActionabilityBlock(
            cast(str, row["population_id"]),
            cast(int, row["n_divergent"]),
            cast(int, row["n_present"]),
            cast(int, row["n_absent"]),
            _optional_f64_value(row["estimate"]),
            cast(Literal["estimated", "not_estimable"], row["estimability_status"]),
        )
        for raw in _list(condition["block_results"], "actionability blocks")
        if (row := _mapping(raw, "ActionabilityBlockResult"))
    )


def _validate_actionability_block_derivations(
    condition: Mapping[str, object], pooled_estimate: float | None
) -> None:
    for raw in _list(condition["block_results"], "actionability blocks"):
        row = _mapping(raw, "ActionabilityBlockResult")
        estimate = _optional_f64_value(row["estimate"])
        support = (
            cast(int, row["n_divergent"]) >= 20
            and cast(int, row["n_present"]) >= 5
            and cast(int, row["n_absent"]) >= 5
        )
        same = (
            estimate * pooled_estimate > 0.0
            if estimate is not None and pooled_estimate not in {None, 0.0}
            else None
        )
        opposite = (
            estimate * pooled_estimate < 0.0 and abs(estimate) >= 0.10
            if estimate is not None and pooled_estimate is not None
            else None
        )
        expected_resolution = (
            "resolved" if row["estimability_status"] == "estimated" else "inconclusive"
        )
        if (
            row["support_predicate_passed"] != support
            or row["same_direction_predicate_passed"] != same
            or row["opposite_direction_predicate_passed"] != opposite
            or row["resolution_status"] != expected_resolution
        ):
            raise ArtifactValidationError(
                "Actionability block predicates disagree with their source values."
            )


def _validate_gate_operand_rows(
    graph: CanonicalArtifactGraph,
    snapshot: ProtocolSnapshot,
    gates: Sequence[Mapping[str, object]],
    *,
    contrasts: Mapping[str, Mapping[str, object]],
    comparisons: Sequence[Mapping[str, object]],
    audit_statuses: Mapping[str, GateStatus],
    outputs: Mapping[str, object],
    actionability: ActionabilityResult,
    partition: ActionPartition,
    vetoes: Sequence[VetoResult],
) -> None:
    count_values: dict[str, object] = {
        "COUNT-ARM-RUNS": len(_rows(graph, "arm_runs.jsonl")),
        "COUNT-COMPARISONS": len(comparisons),
        "COUNT-SIGMA-ROWS": len(_rows(graph, "calibration_estimates.jsonl")),
        "COUNT-CONTRAST-ROWS": len(contrasts),
        "FK-ALL": True,
    }
    for scope, policy_id in (
        ("IG", "information_gain"),
        ("LA", "lookahead_information_gain"),
    ):
        divergent = tuple(
            row
            for row in comparisons
            if row["policy_id"] == policy_id and row["record_type"] == "divergent"
        )
        count_values[f"COUNT-PRIMARY-SF-{scope}"] = float(
            sum(row["primary_mechanism_id"] == "SCORE_FLATTENING" for row in divergent)
        )
        count_values[f"COUNT-PRIMARY-GSR-{scope}"] = float(
            sum(row["primary_mechanism_id"] == "GROUP_SIGMA_REORDERING" for row in divergent)
        )
    decision_symbols: dict[str, DecisionBoolean] = {
        "ACTIONABILITY_COMPLETE": actionability.actionability_complete,
        "VETO_COMPLETE": partition.veto_complete,
        "CONTROLLER_CHANGE_NEEDED": cast(DecisionBoolean, outputs["G-CONTROLLER-CHANGE"]),
        "UNIQUE_ACTIONABLE_MECHANISM": cast(
            DecisionBoolean, outputs["G-UNIQUE-ACTIONABLE-MECHANISM"]
        ),
        "PPO_ELIGIBLE": cast(DecisionBoolean, outputs["G-PPO"]),
        "B_AUTHORIZED": cast(DecisionBoolean, outputs["G-B-AUTHORIZATION"]),
    }
    final = cast(BranchDecision, outputs["G-FINAL"])
    branch_ids = snapshot.registry("branch").ids("branch_id")
    branch_by_condition = {
        f"G-FINAL/C{index:02d}": branch_id for index, branch_id in enumerate(branch_ids, 1)
    }
    branch_matches = dict(final.branch_matches)
    for gate in gates:
        for raw_condition in _list(gate["conditions"], "gate conditions"):
            condition = _mapping(raw_condition, "GateConditionEvaluation")
            for raw_observed in _list(condition["observed_values"], "observed values"):
                observed = _mapping(raw_observed, "GateObservedValue")
                operand = cast(str, observed["operand_id"])
                if operand in contrasts:
                    _require_observed_value(
                        observed,
                        "contrast_status",
                        "contrast_status_value",
                        contrasts[operand]["result_status"],
                    )
                elif operand in outputs:
                    _require_observed_value(
                        observed,
                        "gate_status",
                        "gate_status_value",
                        _gate_output_status(outputs[operand]).value,
                    )
                elif operand in audit_statuses:
                    _require_observed_value(
                        observed,
                        "gate_status",
                        "gate_status_value",
                        audit_statuses[operand].value,
                    )
                elif operand in count_values:
                    value = count_values[operand]
                    if isinstance(value, bool):
                        _require_observed_value(observed, "boolean", "boolean_value", value)
                    elif isinstance(value, int):
                        _require_observed_value(observed, "integer", "integer_value", value)
                    else:
                        _require_observed_value(
                            observed, "scalar", "scalar_value", f64(cast(float, value))
                        )
                elif operand == "P_RAW":
                    _require_observed_actions(observed, actionability.p_raw)
                elif operand == "P":
                    _require_observed_actions(observed, partition.surviving_tuples)
                elif operand.startswith("V") and operand[1:].isdigit():
                    _require_observed_value(
                        observed,
                        "veto_status",
                        "veto_status_value",
                        vetoes[int(operand[1:]) - 1].veto_status,
                    )
                elif operand in decision_symbols:
                    _require_observed_value(
                        observed,
                        "gate_status",
                        "gate_status_value",
                        decision_symbols[operand].status.value,
                    )
                elif operand in branch_by_condition:
                    _require_observed_value(
                        observed,
                        "branch_match_status",
                        "branch_match_status_value",
                        branch_matches[branch_by_condition[operand]],
                    )
                else:
                    raise ArtifactValidationError(
                        f"Gate operand {operand} has no canonical upstream owner."
                    )


def _require_observed_value(
    observed: Mapping[str, object], value_type: str, field: str, expected: object
) -> None:
    if observed["value_type"] != value_type or observed[field] != expected:
        raise ArtifactValidationError("Gate observed operand disagrees with its source row.")


def _require_observed_actions(
    observed: Mapping[str, object], expected: Sequence[ActionTuple]
) -> None:
    if observed["value_type"] != "tuple_set" or _action_tuples(
        observed["tuple_set_value"], "observed tuple set"
    ) != tuple(_action_tuple_fields(item) for item in expected):
        raise ArtifactValidationError("Gate observed tuple set disagrees with its source output.")


def _recompute_vetoes(
    payload: Mapping[str, object],
    snapshot: ProtocolSnapshot,
    contrasts: Mapping[str, Mapping[str, object]],
) -> tuple[VetoResult, ...]:
    stored_rows = tuple(
        _mapping(raw, "VetoEvaluation")
        for raw in _list(payload["veto_evaluations"], "veto evaluations")
    )
    results: list[VetoResult] = []
    for specification, stored in zip(snapshot.registry("veto").records(), stored_rows, strict=True):
        source = ActionTuple(
            specification["policy_scope"],
            specification["mechanism_id"],
            specification["decision_contrast_id"],
            specification["own_confirmatory_contrast_id"],
        )
        own = contrasts[specification["own_confirmatory_contrast_id"]]
        other = contrasts[specification["required_veto_contrast_id"]]
        support_resolved = other["result_status"] == "ESTIMATED"
        values = {
            "source_tuple": source,
            "required_veto_contrast_id": specification["required_veto_contrast_id"],
            "own_effect": _optional_f64_value(own["estimate"]),
            "other_policy_effect": _optional_f64_value(other["estimate"]),
            "other_policy_ci": (
                _optional_f64_value(other["ci_low"]),
                _optional_f64_value(other["ci_high"]),
            ),
            "other_policy_holm_p": _optional_f64_value(other["p_adjusted"]),
            "support_counts": {"resolved": support_resolved},
        }
        result = cast(str, _execute_exact_formula(snapshot, "F-VETO", values))
        if stored["veto_status"] != result:
            raise ArtifactValidationError("Stored veto status disagrees with F-VETO.")
        expected_source = (
            source.policy_scope,
            source.mechanism_id,
            source.decision_contrast_id,
            source.confirmatory_contrast_id,
        )
        if _action_tuple(stored["source_tuple"], "veto source") != expected_source:
            raise ArtifactValidationError("Stored veto source differs from its registry owner.")
        if (
            stored["required_veto_contrast_id"] != specification["required_veto_contrast_id"]
            or stored["support_resolved"] != support_resolved
            or stored["present_count"] != (other["n_present"] or 0)
            or stored["absent_count"] != (other["n_absent"] or 0)
            or stored["other_contrast_status"] != other["result_status"]
        ):
            raise ArtifactValidationError("Stored veto provenance differs from source contrasts.")
        own_effect = cast(float | None, values["own_effect"])
        other_effect = cast(float | None, values["other_policy_effect"])
        other_ci = cast(tuple[float | None, float | None], values["other_policy_ci"])
        other_p = cast(float | None, values["other_policy_holm_p"])
        expected_opposite = (
            own_effect * other_effect < 0.0
            if own_effect is not None and other_effect is not None
            else None
        )
        expected_threshold = abs(other_effect) >= 0.15 if other_effect is not None else None
        expected_ci = (
            other_ci[1] < 0.0 or other_ci[0] > 0.0
            if other_ci[0] is not None and other_ci[1] is not None
            else None
        )
        expected_holm = other_p < 0.05 if other_p is not None else None
        if (
            not _same_optional_float(_optional_f64_value(stored["own_effect"]), own_effect)
            or not _same_optional_float(_optional_f64_value(stored["other_effect"]), other_effect)
            or stored["opposite_sign"] != expected_opposite
            or stored["effect_threshold_passed"] != expected_threshold
            or stored["ci_condition_passed"] != expected_ci
            or stored["holm_condition_passed"] != expected_holm
        ):
            raise ArtifactValidationError("Stored veto diagnostics disagree with F-VETO inputs.")
        results.append(
            VetoResult(
                source,
                cast(Literal["VETOED", "NOT_VETOED", "INCONCLUSIVE"], result),
            )
        )
    return tuple(results)


def _compare_recomputed_decision_payload(
    payload: Mapping[str, object],
    outputs: Mapping[str, object],
    actionability: ActionabilityResult | None,
    partition: ActionPartition | None,
) -> None:
    if actionability is None or partition is None:
        raise ArtifactValidationError("Gate graph lacks actionability or veto partition output.")
    if _action_tuples(payload["P_RAW"], "P_RAW") != tuple(
        _action_tuple_fields(item) for item in actionability.p_raw
    ):
        raise ArtifactValidationError("Stored P_RAW disagrees with F-ACTION-COMPLETE.")
    if _action_tuples(payload["P"], "P") != tuple(
        _action_tuple_fields(item) for item in partition.surviving_tuples
    ) or _action_tuples(payload["VETOED_TUPLES"], "VETOED_TUPLES") != tuple(
        _action_tuple_fields(item) for item in partition.vetoed_tuples
    ):
        raise ArtifactValidationError("Stored action partition disagrees with F-P.")
    symbols = {
        "ACTIONABILITY_COMPLETE": actionability.actionability_complete,
        "VETO_COMPLETE": partition.veto_complete,
        "CONTROLLER_CHANGE_NEEDED": outputs["G-CONTROLLER-CHANGE"],
        "UNIQUE_ACTIONABLE_MECHANISM": outputs["G-UNIQUE-ACTIONABLE-MECHANISM"],
        "PPO_ELIGIBLE": outputs["G-PPO"],
        "B_AUTHORIZED": outputs["G-B-AUTHORIZATION"],
    }
    for symbol, output in symbols.items():
        expected = cast(DecisionBoolean, output)
        stored = _mapping(payload[symbol], symbol)
        if (
            stored["value"] != expected.value
            or stored["resolution_status"] != expected.resolution_status
            or tuple(_list(stored["source_ids"], f"{symbol} source IDs")) != expected.source_ids
        ):
            raise ArtifactValidationError(f"Stored {symbol} disagrees with its formula output.")
    decision = cast(BranchDecision, outputs["G-FINAL"])
    if (
        payload["final_branch_id"] != decision.branch_id
        or payload["recommendation"] != decision.recommendation
        or payload["final_gate_status"] != decision.gate_status.value
    ):
        raise ArtifactValidationError("Stored recommendation disagrees with F-DECISION-TABLE.")


def _action_tuple_fields(item: ActionTuple) -> tuple[str, str, str, str]:
    return (
        item.policy_scope,
        item.mechanism_id,
        item.decision_contrast_id,
        item.confirmatory_contrast_id,
    )


def _validate_contrasts(rows: Sequence[Mapping[str, object]], snapshot: ProtocolSnapshot) -> None:
    if len(rows) != 122:
        raise ArtifactValidationError("contrast_results.csv must contain exactly 122 rows.")
    registry = (
        snapshot.registry("confirmatory").records()
        + snapshot.registry("decision").records()
        + snapshot.registry("descriptive").records()
    )
    expected_ids = tuple(row["contrast_id"] for row in registry)
    if tuple(cast(str, row["contrast_id"]) for row in rows) != expected_ids:
        raise ArtifactValidationError("Contrast rows differ from BR-C/BR-J/BR-D order.")
    _unique(rows, ("contrast_id",), "contrast")
    hypotheses = set(snapshot.registry("statistical_hypothesis").ids("statistical_hypothesis_id"))
    for row, specification in zip(rows, registry, strict=True):
        for field in (
            "analysis_class",
            "research_question_id",
            "policy_scope",
            "population_scope",
            "metric_id",
            "estimand_id",
            "source_contrast_id",
            "statistical_hypothesis_id",
        ):
            expected = None if specification[field] == "null" else specification[field]
            if row[field] != expected:
                raise ArtifactValidationError(f"Contrast {row['contrast_id']} {field} differs.")
        if row["holm_member"] != (specification["holm_member"] == "true"):
            raise ArtifactValidationError("Contrast Holm membership differs.")
        counts = _mapping(row["missingness_counts"], "MissingnessCounts")
        required_counts = {
            "n_total_pairs",
            "n_complete_pairs",
            "n_fixed_missing_only",
            "n_calibrated_missing_only",
            "n_both_missing",
        }
        if set(counts) != required_counts or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in counts.values()
        ):
            raise ArtifactValidationError("Contrast missingness counts are invalid.")
        if (
            cast(int, counts["n_complete_pairs"])
            + cast(int, counts["n_fixed_missing_only"])
            + cast(int, counts["n_calibrated_missing_only"])
            + cast(int, counts["n_both_missing"])
            != counts["n_total_pairs"]
        ):
            raise ArtifactValidationError("Contrast missingness partitions do not reconcile.")
        estimated = row["result_status"] == "ESTIMATED"
        if row["result_status"] not in {"ESTIMATED", "INCONCLUSIVE"} or row[
            "estimability_status"
        ] not in {"estimated", "not_estimable"}:
            raise ArtifactValidationError("Contrast status enum differs.")
        if estimated != (row["estimability_status"] == "estimated"):
            raise ArtifactValidationError("Contrast result and estimability status disagree.")
        for field in (
            "n_present",
            "n_absent",
            "usable_bootstrap_replicates",
            "permutation_count",
            "extreme_count",
            "holm_rank",
        ):
            value = row[field]
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                raise ArtifactValidationError(f"Contrast {field} is not a nonnegative I64.")
        for field in (
            "present_weight",
            "absent_weight",
            "left_value",
            "right_value",
            "left_denominator",
            "right_denominator",
            "estimate",
            "ci_low",
            "ci_high",
            "test_statistic",
            "p_raw",
            "p_adjusted",
        ):
            if row[field] is not None:
                value = _f64_value(row[field])
                if field in {"p_raw", "p_adjusted"} and not 0.0 <= value <= 1.0:
                    raise ArtifactValidationError(f"Contrast {field} is outside [0,1].")
        analysis_class = cast(str, row["analysis_class"])
        inferential_fields = (
            "estimate",
            "ci_low",
            "ci_high",
            "test_statistic",
            "permutation_count",
            "extreme_count",
            "p_raw",
            "p_adjusted",
            "holm_rank",
        )
        if not estimated and any(row[field] is not None for field in inferential_fields):
            raise ArtifactValidationError("Inconclusive contrast retained inferential values.")
        if estimated and row["estimate"] is None:
            raise ArtifactValidationError("Estimated contrast lacks an estimate.")
        if analysis_class == "decision_operand" and (
            row["source_contrast_id"] is None
            or any(
                row[field] is not None
                for field in (
                    "test_statistic",
                    "permutation_count",
                    "extreme_count",
                    "p_raw",
                    "p_adjusted",
                    "holm_rank",
                )
            )
            or row["usable_bootstrap_replicates"] != 0
        ):
            raise ArtifactValidationError("Decision contrast inferential fields differ.")
        if analysis_class == "descriptive" and (
            any(
                row[field] is not None
                for field in (
                    "ci_low",
                    "ci_high",
                    "test_statistic",
                    "permutation_count",
                    "extreme_count",
                    "p_raw",
                    "p_adjusted",
                    "holm_rank",
                )
            )
            or row["usable_bootstrap_replicates"] != 0
        ):
            raise ArtifactValidationError("Descriptive contrast inferential fields differ.")
        if (
            row["statistical_hypothesis_id"] is not None
            and row["statistical_hypothesis_id"] not in hypotheses
        ):
            raise ArtifactValidationError("Contrast statistical hypothesis FK does not resolve.")


def _validate_resampling(
    rows: Sequence[Mapping[str, object]],
    snapshot: ProtocolSnapshot,
    profile: ArtifactCardinalityProfile,
) -> None:
    bootstrap = tuple(row for row in rows if row["record_type"] == "bootstrap")
    signs = tuple(row for row in rows if row["record_type"] == "sign_flip")
    if tuple(rows) != (*bootstrap, *signs):
        raise ArtifactValidationError("Bootstrap rows do not precede sign-flip rows.")
    _require_count("bootstrap rows", bootstrap, profile.bootstrap_rows)
    _require_count("sign-flip rows", signs, profile.sign_flip_rows)
    _unique(rows, ("resample_id",), "resample")
    _unique(rows, ("contrast_id", "record_type", "replicate_index"), "resample tuple")
    confirmatory = snapshot.registry("confirmatory").records()
    bootstrap_ids = tuple(row["contrast_id"] for row in confirmatory)
    sign_ids = tuple(row["contrast_id"] for row in confirmatory if row["holm_member"] == "true")
    _validate_resampling_variant(
        bootstrap,
        "bootstrap",
        bootstrap_ids,
        profile.bootstrap_replicates_per_contrast,
    )
    _validate_resampling_variant(
        signs,
        "sign_flip",
        sign_ids,
        profile.sign_flip_replicates_per_hypothesis,
    )


def _validate_resampling_variant(
    rows: Sequence[Mapping[str, object]],
    record_type: str,
    ordered_contrast_ids: Sequence[str],
    replicates: int,
) -> None:
    expected_order = [
        (contrast_id, replicate_index)
        for contrast_id in ordered_contrast_ids
        for replicate_index in range(replicates)
    ]
    observed_order = [
        (cast(str, row["contrast_id"]), cast(int, row["replicate_index"])) for row in rows
    ]
    if observed_order != expected_order:
        raise ArtifactValidationError(f"{record_type} row order/count differs.")
    for row in rows:
        contrast_id = cast(str, row["contrast_id"])
        replicate_index = cast(int, row["replicate_index"])
        expected_id = f"resample/{contrast_id}/{record_type}/{replicate_index:05d}"
        if row["resample_id"] != expected_id:
            raise ArtifactValidationError("Resample ID template differs.")
        if record_type == "bootstrap":
            preimage, digest, seed = bootstrap_seed(contrast_id, replicate_index)
            stream = bootstrap_seed_ids(contrast_id, replicate_index)
            if row["sampled_seed_ids_sha256"] != sampled_seed_ids_sha256(
                contrast_id, replicate_index, stream
            ):
                raise ArtifactValidationError("Bootstrap sampled-seed digest differs.")
        else:
            preimage, digest, seed = sign_flip_seed(contrast_id, replicate_index)
            stream = sign_flip_vector(contrast_id, replicate_index)
            if row["sign_vector_sha256"] != sign_vector_sha256(
                contrast_id, replicate_index, stream
            ):
                raise ArtifactValidationError("Sign-flip vector digest differs.")
        if (
            row["seed_preimage_utf8_hex"] != preimage.hex()
            or row["seed_digest"] != digest.hex()
            or row["seed"] != seed
            or row["sampled_position_count"] != 128
            or row["completion_status"] != "complete"
        ):
            raise ArtifactValidationError("Resampling seed/stream provenance differs.")
        valid = row["result_status"] == "valid"
        result = (
            row["replicate_estimate"] if record_type == "bootstrap" else row["replicate_statistic"]
        )
        if valid:
            if row["failure_code"] is not None or result is None:
                raise ArtifactValidationError("Valid resampling row has invalid nullability.")
            if record_type == "sign_flip" and row["extreme"] is None:
                raise ArtifactValidationError("Valid sign-flip row lacks extreme flag.")
        else:
            allowed = {
                "insufficient_complete_cases",
                "zero_denominator",
                "nonfinite_result",
                "stream_failure",
            }
            if row["failure_code"] not in allowed or result is not None:
                raise ArtifactValidationError("Null resampling row has invalid failure provenance.")
            if record_type == "sign_flip" and row["extreme"] is not None:
                raise ArtifactValidationError("Null sign-flip row has an extreme flag.")


def _validate_raw_resampling_statistics(
    graph: CanonicalArtifactGraph,
    contrasts: Sequence[Mapping[str, object]],
    rows: Sequence[Mapping[str, object]],
    snapshot: ProtocolSnapshot,
) -> None:
    """Recompute every supplied resample from paired artifact rows and frozen streams."""

    runs = {cast(str, row["run_id"]): row for row in _rows(graph, "arm_runs.jsonl")}
    comparisons = _rows(graph, "comparisons.jsonl")
    contrast_by_id = {cast(str, row["contrast_id"]): row for row in contrasts}
    specifications = {
        row["contrast_id"]: row for row in snapshot.registry("confirmatory").records()
    }
    datasets = {
        contrast_id: _artifact_estimand_dataset(specification, comparisons, runs, snapshot)
        for contrast_id, specification in specifications.items()
    }
    derived_estimates = {
        contrast_id: (
            raw_estimate
            if _derived_missingness_passes(
                datasets[contrast_id], _derived_contrast_metadata(datasets[contrast_id])
            )
            else None
        )
        for contrast_id, specification in specifications.items()
        for raw_estimate in (
            ResamplingEstimand(
                specification["estimand_id"], datasets[contrast_id]
            ).evaluate_bootstrap(FULL_SEEDS),
        )
    }
    resampling_by_contrast: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        resampling_by_contrast[cast(str, row["contrast_id"])].append(row)

    for contrast_id, specification in specifications.items():
        _validate_derived_contrast(
            contrast_by_id[contrast_id],
            specification,
            datasets[contrast_id],
            tuple(resampling_by_contrast[contrast_id]),
            snapshot,
        )
    for specification in snapshot.registry("descriptive").records():
        dataset = _artifact_estimand_dataset(specification, comparisons, runs, snapshot)
        _validate_derived_contrast(
            contrast_by_id[specification["contrast_id"]],
            specification,
            dataset,
            (),
            snapshot,
        )
    for specification in snapshot.registry("decision").records():
        stored = contrast_by_id[specification["contrast_id"]]
        source = contrast_by_id[specification["source_contrast_id"]]
        copied_fields = (
            "missingness_counts",
            "n_present",
            "n_absent",
            "present_weight",
            "absent_weight",
            "left_value",
            "right_value",
            "left_denominator",
            "right_denominator",
            "estimate",
            "result_status",
            "estimability_status",
        )
        if any(stored[field] != source[field] for field in copied_fields):
            raise ArtifactValidationError(
                f"Decision contrast {stored['contrast_id']} disagrees with its derived source row."
            )
    for row in rows:
        contrast_id = cast(str, row["contrast_id"])
        replicate_index = cast(int, row["replicate_index"])
        estimand = ResamplingEstimand(
            specifications[contrast_id]["estimand_id"], datasets[contrast_id]
        )
        if row["record_type"] == "bootstrap":
            expected_bootstrap = bootstrap_replicate(
                contrast_id, replicate_index, estimand.evaluate_bootstrap
            )
            expected = expected_bootstrap.estimate
            if (
                row["resample_id"] != f"resample/{contrast_id}/bootstrap/{replicate_index:05d}"
                or row["seed_preimage_utf8_hex"] != expected_bootstrap.seed_preimage.hex()
                or row["seed_digest"] != expected_bootstrap.seed_digest.hex()
                or row["seed"] != expected_bootstrap.seed
                or row["sampled_position_count"] != len(expected_bootstrap.sampled_seed_ids)
                or row["sampled_seed_ids_sha256"]
                != sampled_seed_ids_sha256(
                    contrast_id, replicate_index, expected_bootstrap.sampled_seed_ids
                )
                or row["completion_status"] != "complete"
                or not _same_optional_float(
                    _optional_f64_value(row["replicate_estimate"]), expected
                )
                or row["failure_code"] != expected_bootstrap.failure_code
                or row["result_status"] != ("valid" if expected is not None else "null")
            ):
                raise ArtifactValidationError(
                    "Bootstrap statistic, status, or exact failure cause disagrees with raw rows."
                )
        else:
            expected_sign_flip = sign_flip_replicate(
                contrast_id,
                replicate_index,
                derived_estimates[contrast_id] or 0.0,
                estimand.evaluate_sign_flip,
            )
            expected = expected_sign_flip.statistic
            if (
                row["resample_id"] != f"resample/{contrast_id}/sign_flip/{replicate_index:05d}"
                or row["seed_preimage_utf8_hex"] != expected_sign_flip.seed_preimage.hex()
                or row["seed_digest"] != expected_sign_flip.seed_digest.hex()
                or row["seed"] != expected_sign_flip.seed
                or row["sampled_position_count"] != len(expected_sign_flip.signs)
                or row["sign_vector_sha256"]
                != sign_vector_sha256(contrast_id, replicate_index, expected_sign_flip.signs)
                or row["completion_status"] != "complete"
                or not _same_optional_float(
                    _optional_f64_value(row["replicate_statistic"]), expected
                )
                or row["failure_code"] != expected_sign_flip.failure_code
                or row["result_status"] != ("valid" if expected is not None else "null")
            ):
                raise ArtifactValidationError(
                    "Sign-flip statistic, status, or exact failure cause disagrees with raw rows."
                )
            if row["extreme"] != expected_sign_flip.extreme:
                raise ArtifactValidationError(
                    "Sign-flip extreme flag disagrees with the raw statistic."
                )


def _validate_derived_contrast(
    stored: Mapping[str, object],
    specification: Mapping[str, str],
    dataset: EstimandDataset,
    resampling: Sequence[Mapping[str, object]],
    snapshot: ProtocolSnapshot,
) -> None:
    """Derive every scientific contrast claim before comparing the stored row."""

    raw_estimate = ResamplingEstimand(specification["estimand_id"], dataset).evaluate_bootstrap(
        FULL_SEEDS
    )
    expected_metadata = _derived_contrast_metadata(dataset)
    estimate = raw_estimate if _derived_missingness_passes(dataset, expected_metadata) else None
    for field, expected in expected_metadata.items():
        observed = stored[field]
        if isinstance(expected, float):
            if not _same_optional_float(_optional_f64_value(observed), expected):
                raise ArtifactValidationError(
                    f"Contrast {stored['contrast_id']} {field} disagrees with raw paired rows."
                )
        elif observed != expected:
            raise ArtifactValidationError(
                f"Contrast {stored['contrast_id']} {field} disagrees with raw paired rows."
            )

    analysis_class = specification["analysis_class"]
    if analysis_class == "descriptive":
        expected_status = "ESTIMATED" if estimate is not None else "INCONCLUSIVE"
        usable_bootstrap = 0
        ci_low = None
        ci_high = None
    else:
        bootstrap_rows = tuple(row for row in resampling if row["record_type"] == "bootstrap")
        valid_bootstrap = sorted(
            _f64_value(row["replicate_estimate"])
            for row in bootstrap_rows
            if row["result_status"] == "valid"
        )
        usable_bootstrap = len(valid_bootstrap)
        required = math.ceil(0.95 * len(bootstrap_rows))
        bootstrap_supported = bool(bootstrap_rows) and usable_bootstrap >= required
        signs = tuple(row for row in resampling if row["record_type"] == "sign_flip")
        signs_supported = specification["holm_member"] != "true" or (
            bool(signs) and all(row["result_status"] == "valid" for row in signs)
        )
        expected_status = (
            "ESTIMATED"
            if estimate is not None and bootstrap_supported and signs_supported
            else "INCONCLUSIVE"
        )
        if expected_status == "ESTIMATED":
            ci_low = valid_bootstrap[math.ceil(0.025 * usable_bootstrap) - 1]
            ci_high = valid_bootstrap[math.ceil(0.975 * usable_bootstrap) - 1]
        else:
            ci_low = None
            ci_high = None

    if (
        stored["result_status"] != expected_status
        or stored["estimability_status"]
        != ("estimated" if expected_status == "ESTIMATED" else "not_estimable")
        or stored["usable_bootstrap_replicates"] != usable_bootstrap
        or not _same_optional_float(
            _optional_f64_value(stored["estimate"]),
            estimate if expected_status == "ESTIMATED" else None,
        )
        or not _same_optional_float(_optional_f64_value(stored["ci_low"]), ci_low)
        or not _same_optional_float(_optional_f64_value(stored["ci_high"]), ci_high)
    ):
        raise ArtifactValidationError(
            f"Contrast {stored['contrast_id']} stored status or inference "
            "disagrees with derivation."
        )
    if analysis_class.startswith("confirmatory_"):
        expected_statistic = estimate if expected_status == "ESTIMATED" else None
        if not _same_optional_float(
            _optional_f64_value(stored["test_statistic"]), expected_statistic
        ):
            raise ArtifactValidationError("Contrast test statistic disagrees with derivation.")
    if specification["holm_member"] == "true" and expected_status == "ESTIMATED":
        sign_rows = tuple(row for row in resampling if row["record_type"] == "sign_flip")
        extreme_count = sum(cast(bool, row["extreme"]) for row in sign_rows)
        p_raw = (1 + extreme_count) / (len(sign_rows) + 1)
        if (
            stored["permutation_count"] != len(sign_rows)
            or stored["extreme_count"] != extreme_count
            or not _same_optional_float(_optional_f64_value(stored["p_raw"]), p_raw)
        ):
            raise ArtifactValidationError("Contrast permutation result disagrees with derivation.")
    elif any(
        stored[field] is not None for field in ("permutation_count", "extreme_count", "p_raw")
    ):
        raise ArtifactValidationError("Non-estimable contrast retained permutation claims.")


def _derived_contrast_metadata(dataset: EstimandDataset) -> dict[str, object]:
    counts = {
        "n_total_pairs": 0,
        "n_complete_pairs": 0,
        "n_fixed_missing_only": 0,
        "n_calibrated_missing_only": 0,
        "n_both_missing": 0,
    }
    result: dict[str, object] = {
        "missingness_counts": counts,
        "n_present": None,
        "n_absent": None,
        "present_weight": None,
        "absent_weight": None,
        "left_value": None,
        "right_value": None,
        "left_denominator": None,
        "right_denominator": None,
    }
    if dataset.estimand_id == "calibrated_minus_fixed":
        rows = dataset.paired_metric_rows
        complete = tuple(
            row for row in rows if row.fixed_value is not None and row.calibrated_value is not None
        )
        counts.update(
            n_total_pairs=len(rows),
            n_complete_pairs=len(complete),
            n_fixed_missing_only=sum(
                row.fixed_value is None and row.calibrated_value is not None for row in rows
            ),
            n_calibrated_missing_only=sum(
                row.fixed_value is not None and row.calibrated_value is None for row in rows
            ),
            n_both_missing=sum(
                row.fixed_value is None and row.calibrated_value is None for row in rows
            ),
        )
        denominator = math.fsum(row.weight for row in complete)
        result.update(left_denominator=denominator, right_denominator=denominator)
        return result
    if dataset.estimand_id == "helped_minus_hurt":
        relevant = tuple(
            row for row in dataset.outcome_rows if row.divergent and row.outcome_label is not None
        )
        total = sum(row.outcome_label in {"helped", "hurt", "mixed"} for row in relevant)
        counts.update(n_total_pairs=total, n_complete_pairs=total)
        denominator = math.fsum(
            row.weight for row in relevant if row.outcome_label in {"helped", "hurt"}
        )
        result.update(left_denominator=denominator, right_denominator=denominator)
        return result
    if dataset.estimand_id in {"conditional_harm_difference", "sequence_harm_difference"}:
        right = dataset.right_outcome_rows
        left = dataset.left_outcome_rows
        right_count = sum(row.outcome_label in {"helped", "hurt"} for row in right)
        left_count = sum(row.outcome_label in {"helped", "hurt"} for row in left)
        total = right_count + left_count
        counts.update(n_total_pairs=total, n_complete_pairs=total)
        right_den = math.fsum(
            row.weight for row in right if row.outcome_label in {"helped", "hurt"}
        )
        left_den = math.fsum(row.weight for row in left if row.outcome_label in {"helped", "hurt"})
        result.update(
            n_present=right_count,
            n_absent=left_count,
            present_weight=right_den,
            absent_weight=left_den,
            left_denominator=left_den,
            right_denominator=right_den,
        )
        return result
    if dataset.estimand_id == "mechanism_harm_difference":
        present = dataset.present_outcome_rows
        absent = dataset.absent_outcome_rows
        mixed = sum(row.outcome_label == "mixed" for row in (*present, *absent))
        unresolved = sum(row.outcome_label is None for row in (*present, *absent))
        counts.update(n_total_pairs=mixed + unresolved, n_complete_pairs=mixed + unresolved)
        present_den = math.fsum(
            row.weight for row in present if row.outcome_label in {"helped", "hurt"}
        )
        absent_den = math.fsum(
            row.weight for row in absent if row.outcome_label in {"helped", "hurt"}
        )
        result.update(
            n_present=len(present),
            n_absent=len(absent),
            present_weight=present_den,
            absent_weight=absent_den,
            left_denominator=absent_den,
            right_denominator=present_den,
        )
        return result
    if dataset.estimand_id == "combined_primary_share":
        total = len(dataset.classifiable_rows)
        counts.update(n_total_pairs=total, n_complete_pairs=total)
        denominator = math.fsum(row.weight for row in dataset.classifiable_rows)
        result.update(left_denominator=denominator, right_denominator=denominator)
        return result
    if dataset.estimand_id == "divergence_rate_difference":
        target = dataset.target_rate_rows
        comparator = dataset.comparator_rate_rows
        total = len(target) + len(comparator)
        counts.update(n_total_pairs=total, n_complete_pairs=total)
        target_den = math.fsum(row.weight for row in target)
        comparator_den = math.fsum(row.weight for row in comparator)
        result.update(left_denominator=comparator_den, right_denominator=target_den)
        return result
    raise ArtifactValidationError(f"Unsupported estimand derivation: {dataset.estimand_id}")


def _derived_missingness_passes(dataset: EstimandDataset, metadata: Mapping[str, object]) -> bool:
    left_denominator = cast(float | None, metadata["left_denominator"])
    right_denominator = cast(float | None, metadata["right_denominator"])
    if dataset.estimand_id == "calibrated_minus_fixed":
        complete = tuple(
            row
            for row in dataset.paired_metric_rows
            if row.fixed_value is not None and row.calibrated_value is not None
        )
        return (
            bool(left_denominator and left_denominator > 0.0)
            and len({row.seed for row in complete}) >= 20
        )
    if dataset.estimand_id == "helped_minus_hurt":
        labels = Counter(row.outcome_label for row in dataset.outcome_rows if row.divergent)
        return (
            bool(left_denominator and left_denominator > 0.0)
            and labels["helped"] >= 20
            and labels["hurt"] >= 20
        )
    if dataset.estimand_id in {"conditional_harm_difference", "sequence_harm_difference"}:
        right = sum(row.outcome_label in {"helped", "hurt"} for row in dataset.right_outcome_rows)
        left = sum(row.outcome_label in {"helped", "hurt"} for row in dataset.left_outcome_rows)
        minimum = 30 if dataset.estimand_id == "sequence_harm_difference" else 20
        return (
            bool(left_denominator and left_denominator > 0.0)
            and bool(right_denominator and right_denominator > 0.0)
            and left >= minimum
            and right >= minimum
        )
    if dataset.estimand_id == "mechanism_harm_difference":
        rows = (*dataset.present_outcome_rows, *dataset.absent_outcome_rows)
        complete_seeds = {row.seed for row in rows if row.outcome_label in {"helped", "hurt"}}
        return (
            bool(left_denominator and left_denominator > 0.0)
            and bool(right_denominator and right_denominator > 0.0)
            and len(complete_seeds) >= 20
        )
    if dataset.estimand_id == "combined_primary_share":
        return (
            bool(left_denominator and left_denominator > 0.0)
            and len(dataset.classifiable_rows) >= 30
        )
    if dataset.estimand_id == "divergence_rate_difference":
        target_divergent = sum(bool(row.divergent) for row in dataset.target_rate_rows)
        comparator_divergent = sum(bool(row.divergent) for row in dataset.comparator_rate_rows)
        return (
            bool(left_denominator and left_denominator > 0.0)
            and bool(right_denominator and right_denominator > 0.0)
            and target_divergent >= 20
            and comparator_divergent >= 20
        )
    raise ArtifactValidationError(f"Unsupported missingness derivation: {dataset.estimand_id}")


def _artifact_estimand_dataset(
    specification: Mapping[str, str],
    comparisons: Sequence[Mapping[str, object]],
    runs: Mapping[str, Mapping[str, object]],
    snapshot: ProtocolSnapshot,
) -> EstimandDataset:
    eligible = tuple(
        row for row in comparisons if _artifact_comparison_eligible(specification, row)
    )
    metric_rows: list[PairedMetricRow] = []
    probability_rows: list[PairedProbabilityRow] = []
    outcome_rows: list[OutcomeRow] = []
    rate_rows: list[ComparisonRateRow] = []
    for row in eligible:
        fixed = runs[cast(str, row["fixed_run_id"])]
        calibrated = runs[cast(str, row["calibrated_run_id"])]
        fixed_metrics = _mapping(fixed["metrics"], "fixed metrics")
        calibrated_metrics = _mapping(calibrated["metrics"], "calibrated metrics")
        weight = _artifact_population_weight(
            specification["population_scope"], cast(str, row["world_id"])
        )
        comparison_id = cast(str, row["comparison_id"])
        seed = cast(int, row["seed"])
        metric_rows.append(
            PairedMetricRow(
                comparison_id,
                seed,
                weight,
                _artifact_metric_value(fixed_metrics, specification["metric_id"]),
                _artifact_metric_value(calibrated_metrics, specification["metric_id"]),
            )
        )
        probability_rows.append(
            PairedProbabilityRow(
                comparison_id,
                seed,
                weight,
                _f64_value(fixed_metrics["top_probability"]),
                cast(bool, fixed_metrics["prediction_correct"]),
                _f64_value(calibrated_metrics["top_probability"]),
                cast(bool, calibrated_metrics["prediction_correct"]),
            )
        )
        divergent = row["record_type"] == "divergent"
        outcome_rows.append(
            OutcomeRow(
                comparison_id,
                seed,
                weight,
                cast(str, row["outcome_label"]),
                divergent,
                cast(str | None, row.get("primary_mechanism_id")),
            )
        )
        rate_rows.append(
            ComparisonRateRow(
                comparison_id,
                seed,
                weight,
                bool(row.get("first_action_divergent"))
                if specification["metric_id"] == "first_action_divergence"
                else divergent,
            )
        )

    estimand_id = specification["estimand_id"]
    base = EstimandDataset(estimand_id, specification["metric_id"])
    if estimand_id == "calibrated_minus_fixed":
        return EstimandDataset(
            estimand_id,
            specification["metric_id"],
            paired_metric_rows=tuple(metric_rows),
            paired_probability_rows=tuple(probability_rows),
        )
    if estimand_id == "helped_minus_hurt":
        return EstimandDataset(
            estimand_id, specification["metric_id"], outcome_rows=tuple(outcome_rows)
        )
    if estimand_id in {"conditional_harm_difference", "sequence_harm_difference"}:
        right: list[OutcomeRow] = []
        left: list[OutcomeRow] = []
        by_id = {cast(str, row["comparison_id"]): row for row in eligible}
        for outcome in outcome_rows:
            comparison = by_id[outcome.comparison_id]
            if estimand_id == "sequence_harm_difference":
                is_right = comparison.get("sequence_class") == "same_experiment_set_different_order"
            elif "ASYM" in specification["population_scope"]:
                is_right = cast(str, comparison["world_id"]).startswith("c_")
            else:
                is_right = comparison["budget_id"] != "budget-2.25"
            (right if is_right else left).append(outcome)
        return EstimandDataset(
            estimand_id,
            specification["metric_id"],
            right_outcome_rows=tuple(right),
            left_outcome_rows=tuple(left),
        )
    if estimand_id == "mechanism_harm_difference":
        mechanism = _artifact_mechanism_for(specification, snapshot)
        present = tuple(
            row for row in outcome_rows if row.divergent and row.primary_mechanism_id == mechanism
        )
        absent = tuple(
            row for row in outcome_rows if row.divergent and row.primary_mechanism_id != mechanism
        )
        return EstimandDataset(
            estimand_id,
            specification["metric_id"],
            present_outcome_rows=present,
            absent_outcome_rows=absent,
        )
    if estimand_id == "combined_primary_share":
        return EstimandDataset(
            estimand_id,
            specification["metric_id"],
            classifiable_rows=tuple(
                row
                for row in outcome_rows
                if row.divergent and row.primary_mechanism_id is not None
            ),
        )
    if estimand_id == "divergence_rate_difference":
        target: list[ComparisonRateRow] = []
        comparator: list[ComparisonRateRow] = []
        by_id = {cast(str, row["comparison_id"]): row for row in eligible}
        for rate in rate_rows:
            comparison = by_id[rate.comparison_id]
            is_target = (
                cast(str, comparison["world_id"]).startswith("c_")
                if "ASYM" in specification["population_scope"]
                else comparison["budget_id"] != "budget-2.25"
            )
            (target if is_target else comparator).append(rate)
        return EstimandDataset(
            estimand_id,
            specification["metric_id"],
            target_rate_rows=tuple(target),
            comparator_rate_rows=tuple(comparator),
        )
    return base


def _artifact_comparison_eligible(
    specification: Mapping[str, str], row: Mapping[str, object]
) -> bool:
    expected_policy = {
        "IG": "information_gain",
        "LA": "lookahead_information_gain",
    }[specification["policy_scope"]]
    if row["policy_id"] != expected_policy:
        return False
    return _artifact_world_in_population(
        specification["population_scope"], cast(str, row["world_id"])
    )


def _artifact_world_in_population(population: str, world_id: str) -> bool:
    world = WORLDS_BY_ID[world_id].public
    if "PRIMARY" in population or "BUDGET" in population or "SAMESET" in population:
        return True
    if "HIGH" in population:
        return world_id in {"h_adam_high", "h_null_high", "h_sgd_high"}
    if "ASYM" in population:
        return world_id in {
            "c_adam_a",
            "c_sgd_a",
            "c_adam_b",
            "c_sgd_b",
            "d2_adam",
            "d2_sgd",
        }
    if "BLOCK" in population:
        block = {
            "HOM": "homogeneous",
            "WEAK": "weak_effect",
            "HET": "heterogeneous_noise",
            "COST": "asymmetric_cost",
            "DELAY": "delay",
        }[population.rsplit("-", 1)[-1]]
        return world.block == block
    return world.block == "heterogeneous_noise" if "HET" in population else False


def _artifact_population_weight(population: str, world_id: str) -> float:
    truth = WORLDS_BY_ID[world_id].hidden.scientific_hypothesis_id
    eligible_worlds = tuple(
        world
        for world in WORLDS_BY_ID.values()
        if _artifact_world_in_population(population, world.public.world_id)
        and world.hidden.scientific_hypothesis_id == truth
    )
    truths = {
        world.hidden.scientific_hypothesis_id
        for world in WORLDS_BY_ID.values()
        if _artifact_world_in_population(population, world.public.world_id)
    }
    if not eligible_worlds or not truths:
        return 0.0
    return 1.0 / (len(truths) * len(eligible_worlds) * len(BUDGETS) * len(FULL_SEEDS))


def _artifact_metric_value(metrics: Mapping[str, object], metric_id: str) -> float | None:
    if metric_id in {
        "first_action_divergence",
        "any_divergence",
        "harm_risk",
        "combined_numerical_share",
        "ece",
    }:
        return None
    field = {
        "true_probability": "true_probability",
        "confidently_wrong": "confidently_wrong",
    }.get(metric_id, metric_id)
    value = metrics[field]
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    return _f64_value(value)


def _artifact_mechanism_for(specification: Mapping[str, str], snapshot: ProtocolSnapshot) -> str:
    hypothesis_id = specification["statistical_hypothesis_id"]
    for mechanism_id in snapshot.registry("mechanism").ids("mechanism_id"):
        if hypothesis_id.endswith(mechanism_id):
            return mechanism_id
    source_id = specification["source_contrast_id"]
    source = next(
        row
        for row in snapshot.registry("confirmatory").records()
        if row["contrast_id"] == source_id
    )
    return _artifact_mechanism_for(source, snapshot)


def _same_optional_float(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)


def _validate_resampling_aggregation(
    contrasts: Sequence[Mapping[str, object]],
    resampling: Sequence[Mapping[str, object]],
    snapshot: ProtocolSnapshot,
    profile: ArtifactCardinalityProfile,
) -> None:
    by_contrast = {cast(str, row["contrast_id"]): row for row in contrasts}
    bootstrap = tuple(row for row in resampling if row["record_type"] == "bootstrap")
    signs = tuple(row for row in resampling if row["record_type"] == "sign_flip")
    confirmatory = snapshot.registry("confirmatory").records()
    bootstrap_replicates = profile.bootstrap_replicates_per_contrast
    for contrast_index, specification in enumerate(confirmatory):
        contrast_id = specification["contrast_id"]
        contrast = by_contrast[contrast_id]
        start = contrast_index * bootstrap_replicates
        rows = bootstrap[start : start + bootstrap_replicates]
        estimates = sorted(
            _f64_value(row["replicate_estimate"]) for row in rows if row["result_status"] == "valid"
        )
        if contrast["usable_bootstrap_replicates"] != len(estimates):
            raise ArtifactValidationError("Contrast usable bootstrap count does not reconcile.")
        required = math.ceil(0.95 * bootstrap_replicates)
        if len(estimates) < required:
            if contrast["result_status"] != "INCONCLUSIVE":
                raise ArtifactValidationError(
                    "Under-supported bootstrap contrast is not inconclusive."
                )
        elif contrast["result_status"] == "ESTIMATED":
            lower_index = math.ceil(0.025 * len(estimates)) - 1
            upper_index = math.ceil(0.975 * len(estimates)) - 1
            if not (
                math.isclose(_f64_value(contrast["ci_low"]), estimates[lower_index], abs_tol=1e-12)
                and math.isclose(
                    _f64_value(contrast["ci_high"]), estimates[upper_index], abs_tol=1e-12
                )
            ):
                raise ArtifactValidationError("Contrast bootstrap percentile interval differs.")
    holm_specs = tuple(row for row in confirmatory if row["holm_member"] == "true")
    sign_replicates = profile.sign_flip_replicates_per_hypothesis
    holm_inputs: list[HolmInput] = []
    for contrast_index, specification in enumerate(holm_specs):
        contrast = by_contrast[specification["contrast_id"]]
        start = contrast_index * sign_replicates
        rows = signs[start : start + sign_replicates]
        valid = all(row["result_status"] == "valid" for row in rows)
        if valid and contrast["result_status"] == "ESTIMATED":
            extreme_count = sum(cast(bool, row["extreme"]) for row in rows)
            expected_p = (1 + extreme_count) / (sign_replicates + 1)
            if (
                contrast["permutation_count"] != sign_replicates
                or contrast["extreme_count"] != extreme_count
                or not math.isclose(_f64_value(contrast["p_raw"]), expected_p, abs_tol=1e-12)
            ):
                raise ArtifactValidationError("Contrast sign-flip aggregation differs.")
            raw_p = expected_p
            estimable = True
        else:
            if any(
                contrast[field] is not None
                for field in (
                    "permutation_count",
                    "extreme_count",
                    "p_raw",
                    "p_adjusted",
                    "holm_rank",
                )
            ):
                raise ArtifactValidationError("Inconclusive sign-flip contrast retained results.")
            raw_p = None
            estimable = False
        holm_inputs.append(HolmInput(specification["statistical_hypothesis_id"], raw_p, estimable))
    holm_results = holm_64(holm_inputs)
    for result, specification in zip(holm_results, holm_specs, strict=True):
        contrast = by_contrast[specification["contrast_id"]]
        if result.result_status == "ESTIMATED" and (
            not math.isclose(
                _f64_value(contrast["p_adjusted"]), cast(float, result.p_adjusted), abs_tol=1e-12
            )
            or contrast["holm_rank"] != result.holm_rank
        ):
            raise ArtifactValidationError("Contrast HOLM-64 result differs.")


def _validate_gate_payload(payload: Mapping[str, object], snapshot: ProtocolSnapshot) -> None:
    if set(payload) != set(GATE_EVALUATION_FIELDS):
        raise ArtifactValidationError("gate_evaluations.json fields differ.")
    if payload["evaluation_id"] != EVALUATION_ID:
        raise ArtifactValidationError("Gate evaluation ID differs.")
    gates = _list(payload["gates"], "gates")
    vetoes = _list(payload["veto_evaluations"], "veto_evaluations")
    if len(gates) != 44 or len(vetoes) != 20:
        raise ArtifactValidationError("Gate/veto row counts differ.")
    gate_registry = snapshot.registry("gate").records()
    formula_by_id = {row["formula_id"]: row for row in snapshot.registry("formula").records()}
    condition_registry = {
        row["condition_id"]: row for row in snapshot.registry("gate_condition").records()
    }
    seen_conditions: list[str] = []
    for raw, specification in zip(gates, gate_registry, strict=True):
        gate = _mapping(raw, "GateEvaluation")
        required = {
            "gate_id",
            "gate_sha256",
            "gate_order",
            "formula_id",
            "formula_sha256",
            "conditions",
            "gate_status",
        }
        if set(gate) != required:
            raise ArtifactValidationError("GateEvaluation fields differ.")
        if (
            gate["gate_id"] != specification["gate_id"]
            or gate["formula_id"] != specification["formula_id"]
        ):
            raise ArtifactValidationError("Gate registry ownership differs.")
        if gate["gate_order"] != int(specification["gate_order"]):
            raise ArtifactValidationError("Gate order differs.")
        if gate["gate_sha256"] != _registry_hash_from_payload(
            snapshot, "gate", gate["gate_id"], "gate_sha256"
        ):
            raise ArtifactValidationError("Gate content SHA differs.")
        if gate["gate_status"] not in {"PASS", "FAIL", "INCONCLUSIVE"}:
            raise ArtifactValidationError("Gate status is not frozen.")
        conditions = _list(gate["conditions"], "conditions")
        for raw_condition in conditions:
            condition = _mapping(raw_condition, "GateConditionEvaluation")
            _validate_condition(condition, condition_registry, gate)
            seen_conditions.append(cast(str, condition["condition_id"]))
        formula_id = gate["formula_id"]
        if not isinstance(formula_id, str) or formula_id not in formula_by_id:
            raise ArtifactValidationError("Gate formula FK does not resolve.")
        if gate["formula_sha256"] != _registry_hash_from_payload(
            snapshot, "formula", formula_id, "formula_sha256"
        ):
            raise ArtifactValidationError("Gate formula SHA differs.")
    expected_conditions = snapshot.registry("gate_condition").ids("condition_id")
    if tuple(seen_conditions) != expected_conditions:
        raise ArtifactValidationError(
            "Gate condition rows are missing, duplicate, or out of order."
        )
    p_raw = _action_tuples(payload["P_RAW"], "P_RAW")
    p = _action_tuples(payload["P"], "P")
    vetoed = _action_tuples(payload["VETOED_TUPLES"], "VETOED_TUPLES")
    _validate_veto_rows(vetoes, p_raw, snapshot)
    if set(p).intersection(vetoed) or not set(p).union(vetoed).issubset(set(p_raw)):
        raise ArtifactValidationError("Gate action partitions do not reconcile.")
    _validate_decision_state(payload, gates, vetoes, p_raw, p, vetoed)
    final_gate = _mapping(gates[-1], "G-FINAL")
    branch_trace = _mapping(payload["final_branch_trace"], "final_branch_trace")
    if not (
        final_gate["gate_id"] == "G-FINAL"
        and final_gate["gate_status"] == payload["final_gate_status"]
        and branch_trace["gate_status"] == payload["final_gate_status"]
    ):
        raise ArtifactValidationError("G-FINAL and branch gate statuses differ.")
    branch_registry = {row["branch_id"]: row for row in snapshot.registry("branch").records()}
    branch = branch_registry.get(cast(str, payload["final_branch_id"]))
    if branch is None or branch["final_output"] != payload["recommendation"]:
        raise ArtifactValidationError("Final branch/recommendation does not resolve.")
    _validate_branch_trace(branch_trace, branch, payload)


def _validate_condition(
    condition: Mapping[str, object],
    registry: Mapping[str, Mapping[str, str]],
    gate: Mapping[str, object],
) -> None:
    required = {
        "condition_id",
        "condition_sha256",
        "condition_order",
        "gate_id",
        "ordered_operand_ids",
        "quantifier",
        "observed_values",
        "block_results",
        "resolution_status",
        "gate_status_result",
        "branch_match_status_result",
    }
    if set(condition) != required:
        raise ArtifactValidationError("GateConditionEvaluation fields differ.")
    specification = registry.get(cast(str, condition["condition_id"]))
    if specification is None or condition["gate_id"] != gate["gate_id"]:
        raise ArtifactValidationError("Gate condition owner does not resolve.")
    if condition["condition_sha256"] != _registry_hash_from_payload(
        load_protocol_snapshot(),
        "gate_condition",
        cast(str, condition["condition_id"]),
        "condition_sha256",
    ):
        raise ArtifactValidationError("Gate condition content SHA differs.")
    if (
        condition["condition_order"] != int(specification["condition_order"])
        or condition["quantifier"] != specification["quantifier"]
    ):
        raise ArtifactValidationError("Gate condition order or quantifier differs.")
    operands = specification["ordered_operand_ids"].split(";")
    if condition["ordered_operand_ids"] != operands:
        raise ArtifactValidationError("Gate condition operand order differs.")
    observed = _list(condition["observed_values"], "observed_values")
    if [cast(str, _mapping(item, "observed value")["operand_id"]) for item in observed] != operands:
        raise ArtifactValidationError("Observed gate operand order differs.")
    for item in observed:
        _validate_gate_observed_value(_mapping(item, "GateObservedValue"))
    _validate_actionability_blocks(condition, operands, gate)
    gate_result = condition["gate_status_result"]
    branch_result = condition["branch_match_status_result"]
    if (gate_result is None) == (branch_result is None):
        raise ArtifactValidationError("Gate condition must have exactly one typed result.")
    if specification["result_enum"] == "gate_status":
        if branch_result is not None or gate_result not in {"PASS", "FAIL", "INCONCLUSIVE"}:
            raise ArtifactValidationError("Gate condition result enum differs.")
    elif specification["result_enum"] == "branch_match_status":
        if gate_result is not None or branch_result not in {"MATCH", "NO_MATCH", "INCONCLUSIVE"}:
            raise ArtifactValidationError("Branch condition result enum differs.")
    else:
        raise ArtifactValidationError("Gate condition registry has an unknown result enum.")
    if condition["resolution_status"] not in {"resolved", "inconclusive"}:
        raise ArtifactValidationError("Gate condition resolution status differs.")


def _validate_gate_observed_value(value: Mapping[str, object]) -> None:
    required = {
        "operand_id",
        "value_type",
        "boolean_value",
        "integer_value",
        "scalar_value",
        "gate_status_value",
        "contrast_status_value",
        "tuple_set_value",
        "veto_status_value",
        "branch_match_status_value",
    }
    if set(value) != required:
        raise ArtifactValidationError("GateObservedValue fields differ.")
    mapping = {
        "boolean": "boolean_value",
        "integer": "integer_value",
        "scalar": "scalar_value",
        "gate_status": "gate_status_value",
        "contrast_status": "contrast_status_value",
        "tuple_set": "tuple_set_value",
        "veto_status": "veto_status_value",
        "branch_match_status": "branch_match_status_value",
    }
    selected = mapping.get(cast(str, value["value_type"]))
    if selected is None:
        raise ArtifactValidationError("GateObservedValue has an unknown value_type.")
    non_null = [field for field in mapping.values() if value[field] is not None]
    if non_null != [selected]:
        raise ArtifactValidationError("GateObservedValue has conflicting typed fields.")
    selected_value = value[selected]
    if selected == "boolean_value" and not isinstance(selected_value, bool):
        raise ArtifactValidationError("GateObservedValue BOOL is malformed.")
    if selected == "integer_value" and (
        not isinstance(selected_value, int) or isinstance(selected_value, bool)
    ):
        raise ArtifactValidationError("GateObservedValue I64 is malformed.")
    if selected == "scalar_value":
        _f64_value(selected_value)
    enum_values = {
        "gate_status_value": {"PASS", "FAIL", "INCONCLUSIVE"},
        "contrast_status_value": {"ESTIMATED", "INCONCLUSIVE"},
        "veto_status_value": {"VETOED", "NOT_VETOED", "INCONCLUSIVE"},
        "branch_match_status_value": {"MATCH", "NO_MATCH", "INCONCLUSIVE"},
    }
    if selected in enum_values and selected_value not in enum_values[selected]:
        raise ArtifactValidationError("GateObservedValue enum is malformed.")
    if selected == "tuple_set_value":
        tuples = _action_tuples(selected_value, "GateObservedValue tuple set")
        if len(tuples) != len(set(tuples)):
            raise ArtifactValidationError("GateObservedValue tuple set is duplicated.")


def _validate_actionability_blocks(
    condition: Mapping[str, object], operands: Sequence[str], gate: Mapping[str, object]
) -> None:
    rows = _list(condition["block_results"], "block_results")
    formula_id = gate["formula_id"]
    if formula_id != "F-ACTION":
        if rows:
            raise ArtifactValidationError("Only F-ACTION may contain block results.")
        return
    policy = "IG" if cast(str, gate["gate_id"]).startswith("G-ACT-IG-") else "LA"
    expected_populations = tuple(
        f"POP-BLOCK-{policy}-{suffix}" for suffix in ("HOM", "WEAK", "HET", "COST", "DELAY")
    )
    if len(rows) != 5:
        raise ArtifactValidationError("F-ACTION must preserve five block results.")
    required = {
        "population_id",
        "operand_contrast_ids",
        "required",
        "n_divergent",
        "n_present",
        "n_absent",
        "estimate",
        "estimability_status",
        "support_predicate_passed",
        "same_direction_predicate_passed",
        "opposite_direction_predicate_passed",
        "resolution_status",
    }
    for raw, population_id in zip(rows, expected_populations, strict=True):
        row = _mapping(raw, "ActionabilityBlockResult")
        if set(row) != required or row["population_id"] != population_id:
            raise ArtifactValidationError("Actionability block schema or population order differs.")
        if _list(row["operand_contrast_ids"], "block operand contrasts") != list(operands):
            raise ArtifactValidationError("Actionability block contrast provenance differs.")
        if row["required"] is not True or row["estimability_status"] not in {
            "estimated",
            "not_estimable",
        }:
            raise ArtifactValidationError("Actionability block requirement/status differs.")
        for field in ("n_divergent", "n_present", "n_absent"):
            count = row[field]
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ArtifactValidationError("Actionability block count is malformed.")
        if row["estimate"] is not None:
            _f64_value(row["estimate"])
        for field in (
            "support_predicate_passed",
            "same_direction_predicate_passed",
            "opposite_direction_predicate_passed",
        ):
            if row[field] is not None and not isinstance(row[field], bool):
                raise ArtifactValidationError("Actionability block predicate is malformed.")
        if row["resolution_status"] not in {"resolved", "inconclusive"}:
            raise ArtifactValidationError("Actionability block resolution differs.")


def _validate_veto_rows(
    rows: Sequence[object], p_raw: Sequence[tuple[str, str, str, str]], snapshot: ProtocolSnapshot
) -> None:
    registry = snapshot.registry("veto").records()
    if len(rows) != len(registry):
        raise ArtifactValidationError("Veto row count differs.")
    for raw, specification in zip(rows, registry, strict=True):
        row = _mapping(raw, "VetoEvaluation")
        required = {
            "veto_id",
            "veto_sha256",
            "source_tuple",
            "required_veto_contrast_id",
            "support_resolved",
            "present_count",
            "absent_count",
            "other_contrast_status",
            "own_effect",
            "other_effect",
            "opposite_sign",
            "effect_threshold_passed",
            "ci_condition_passed",
            "holm_condition_passed",
            "veto_status",
        }
        if set(row) != required or row["veto_id"] != specification["veto_id"]:
            raise ArtifactValidationError("VetoEvaluation schema or order differs.")
        if row["veto_sha256"] != _registry_hash_from_payload(
            snapshot, "veto", row["veto_id"], "veto_sha256"
        ):
            raise ArtifactValidationError("Veto content SHA differs.")
        if row["required_veto_contrast_id"] != specification["required_veto_contrast_id"]:
            raise ArtifactValidationError("Veto contrast FK differs from its registry row.")
        source = _action_tuple(row["source_tuple"], "source_tuple")
        expected_source = (
            specification["policy_scope"],
            specification["mechanism_id"],
            specification["decision_contrast_id"],
            specification["own_confirmatory_contrast_id"],
        )
        if source != expected_source:
            raise ArtifactValidationError("Veto source tuple differs from its registry row.")
        if source in p_raw and row["veto_status"] not in {
            "VETOED",
            "NOT_VETOED",
            "INCONCLUSIVE",
        }:
            raise ArtifactValidationError("P_RAW tuple lacks a valid veto status.")


def _validate_decision_state(
    payload: Mapping[str, object],
    gates: Sequence[object],
    veto_rows: Sequence[object],
    p_raw: Sequence[tuple[str, str, str, str]],
    p: Sequence[tuple[str, str, str, str]],
    vetoed: Sequence[tuple[str, str, str, str]],
) -> None:
    if len(p_raw) != len(set(p_raw)) or len(p) != len(set(p)) or len(vetoed) != len(set(vetoed)):
        raise ArtifactValidationError("Action tuple sets contain duplicates.")
    actions = tuple(ActionTuple(*item) for item in p_raw)
    veto_by_source: dict[ActionTuple, list[VetoResult]] = {}
    for raw in veto_rows:
        row = _mapping(raw, "VetoEvaluation")
        source = ActionTuple(*_action_tuple(row["source_tuple"], "source_tuple"))
        if source in actions:
            veto_by_source.setdefault(source, []).append(
                VetoResult(source, cast(str, row["veto_status"]))  # type: ignore[arg-type]
            )
    if any(len(veto_by_source.get(action, ())) != 1 for action in actions):
        raise ArtifactValidationError("Every P_RAW tuple must have exactly one veto evaluation.")
    veto_results = tuple(veto_by_source[action][0] for action in actions)
    partition = partition_action_tuples(actions, veto_results)
    if tuple(ActionTuple(*item) for item in p) != partition.surviving_tuples:
        raise ArtifactValidationError("P differs from the normative veto partition.")
    if tuple(ActionTuple(*item) for item in vetoed) != partition.vetoed_tuples:
        raise ArtifactValidationError("VETOED_TUPLES differs from the normative veto partition.")
    booleans = {
        field: _decision_boolean(payload[field], field)
        for field in (
            "ACTIONABILITY_COMPLETE",
            "VETO_COMPLETE",
            "CONTROLLER_CHANGE_NEEDED",
            "UNIQUE_ACTIONABLE_MECHANISM",
            "PPO_ELIGIBLE",
            "B_AUTHORIZED",
        )
    }
    if booleans["VETO_COMPLETE"].status is not partition.veto_complete.status:
        raise ArtifactValidationError("VETO_COMPLETE differs from F-VETO-COMPLETE.")
    unique = unique_actionable_mechanism(partition)
    if booleans["UNIQUE_ACTIONABLE_MECHANISM"].status is not unique.status:
        raise ArtifactValidationError(
            "UNIQUE_ACTIONABLE_MECHANISM differs from F-UNIQUE-MECHANISM."
        )
    authorization = b_authorized(
        controller_change_needed=booleans["CONTROLLER_CHANGE_NEEDED"],
        actionability_complete=booleans["ACTIONABILITY_COMPLETE"],
        partition=partition,
        unique_mechanism=booleans["UNIQUE_ACTIONABLE_MECHANISM"],
    )
    if booleans["B_AUTHORIZED"].status is not authorization.status:
        raise ArtifactValidationError("B_AUTHORIZED differs from F-B-AUTHORIZATION.")
    gate_by_id = {
        cast(str, _mapping(item, "GateEvaluation")["gate_id"]): _mapping(item, "GateEvaluation")
        for item in gates
    }
    gate_bindings = {
        "ACTIONABILITY_COMPLETE": "G-ACTIONABILITY-COMPLETE",
        "VETO_COMPLETE": "G-VETO-COMPLETE",
        "CONTROLLER_CHANGE_NEEDED": "G-CONTROLLER-CHANGE",
        "UNIQUE_ACTIONABLE_MECHANISM": "G-UNIQUE-ACTIONABLE-MECHANISM",
        "PPO_ELIGIBLE": "G-PPO",
        "B_AUTHORIZED": "G-B-AUTHORIZATION",
    }
    for field, gate_id in gate_bindings.items():
        if booleans[field].status.value != gate_by_id[gate_id]["gate_status"]:
            raise ArtifactValidationError(f"{field} differs from its owning gate status.")
    mechanisms = {item.mechanism_id for item in partition.surviving_tuples}
    expected_mechanism = next(iter(mechanisms)) if unique.status is GateStatus.PASS else None
    if payload["unique_mechanism_id"] != expected_mechanism:
        raise ArtifactValidationError("Unique mechanism value differs from P.")
    decision = final_decision(
        g_b_authorization=GateStatus(cast(str, gate_by_id["G-B-AUTHORIZATION"]["gate_status"])),
        b_authorization=booleans["B_AUTHORIZED"],
        veto_complete=booleans["VETO_COMPLETE"],
        controller_change_needed=booleans["CONTROLLER_CHANGE_NEEDED"],
        ppo_eligible=booleans["PPO_ELIGIBLE"],
    )
    if (
        payload["final_branch_id"] != decision.branch_id
        or payload["recommendation"] != decision.recommendation
        or payload["final_gate_status"] != decision.gate_status.value
    ):
        raise ArtifactValidationError("Final branch differs from F-DECISION-TABLE.")


def _decision_boolean(value: object, path: str) -> DecisionBoolean:
    row = _mapping(value, path)
    if set(row) != {"value", "resolution_status", "source_ids"}:
        raise ArtifactValidationError(f"{path} DecisionBoolean fields differ.")
    resolution = row["resolution_status"]
    raw_value = row["value"]
    if resolution == "resolved":
        if not isinstance(raw_value, bool):
            raise ArtifactValidationError(f"{path} resolved value is not BOOL.")
    elif resolution == "inconclusive":
        if raw_value is not None:
            raise ArtifactValidationError(f"{path} inconclusive value is non-null.")
    else:
        raise ArtifactValidationError(f"{path} resolution status differs.")
    source_ids = _list(row["source_ids"], f"{path} source IDs")
    if (
        not source_ids
        or len(source_ids) != len(set(source_ids))
        or not all(isinstance(item, str) and item for item in source_ids)
    ):
        raise ArtifactValidationError(f"{path} source IDs are invalid.")
    status = (
        GateStatus.INCONCLUSIVE
        if resolution == "inconclusive"
        else GateStatus.PASS
        if raw_value
        else GateStatus.FAIL
    )
    return DecisionBoolean.from_status(status, *(cast(str, source_id) for source_id in source_ids))


def _validate_branch_trace(
    trace: Mapping[str, object], branch: Mapping[str, str], payload: Mapping[str, object]
) -> None:
    required = {
        "branch_id",
        "ordered_condition_ids_evaluated",
        "first_decisive_condition_id",
        "final_output",
        "required_operand_statuses",
        "unreachable_condition_behavior",
        "condition_results",
        "gate_status",
    }
    if set(trace) != required:
        raise ArtifactValidationError("BranchTrace fields differ.")
    expected_conditions = branch["ordered_condition_ids"].split(";")
    if (
        trace["branch_id"] != branch["branch_id"]
        or trace["ordered_condition_ids_evaluated"] != expected_conditions
        or trace["first_decisive_condition_id"] != branch["first_decisive_condition_id"]
        or trace["final_output"] != branch["final_output"]
        or trace["required_operand_statuses"] != branch["required_operand_statuses"]
        or trace["unreachable_condition_behavior"] != branch["unreachable_condition_behavior"]
        or trace["gate_status"] != payload["final_gate_status"]
        or payload["decision_precedence"] != int(branch["branch_order"])
    ):
        raise ArtifactValidationError("BranchTrace differs from its literal registry row.")
    results = _list(trace["condition_results"], "BranchTrace condition results")
    if len(results) != len(expected_conditions) or any(
        item not in {"MATCH", "NO_MATCH", "INCONCLUSIVE"} for item in results
    ):
        raise ArtifactValidationError("BranchTrace condition results differ.")
    decisive_index = expected_conditions.index(branch["first_decisive_condition_id"])
    if results[decisive_index] != "MATCH" or any(
        result == "MATCH" for result in results[:decisive_index]
    ):
        raise ArtifactValidationError("BranchTrace decisive condition differs.")


def _validate_finalization_graph(graph: CanonicalArtifactGraph, snapshot: ProtocolSnapshot) -> None:
    _validate_manifest_graph(graph, snapshot)
    _validate_recommendation_graph(graph, snapshot)


def _validate_manifest_graph(graph: CanonicalArtifactGraph, snapshot: ProtocolSnapshot) -> None:
    audits = _mapping(graph.artifact("audit_results.json").scientific, "audit_results")
    manifest = _mapping(graph.artifact("run_manifest.json").scientific, "run_manifest")
    if set(audits) != set(AUDIT_RESULT_FIELDS):
        raise ArtifactValidationError("audit_results.json fields differ.")
    audit_rows = _list(audits["audits"], "audits")
    registry = snapshot.registry("audit").records()
    if len(audit_rows) != 16:
        raise ArtifactValidationError("Canonical audit artifact does not contain 16 rows.")
    for raw, specification in zip(audit_rows, registry, strict=True):
        row = _mapping(raw, "AuditResult")
        if set(row) != {
            "audit_id",
            "audit_order",
            "expected",
            "observed",
            "status",
            "audit_detail_sha256",
        }:
            raise ArtifactValidationError("AuditResult fields differ.")
        if (
            row["audit_id"] != specification["audit_id"]
            or row["audit_order"] != int(specification["audit_order"])
            or row["expected"] != specification["requirement"]
            or row["status"] != "PASS"
            or not isinstance(row["observed"], str)
            or not row["observed"]
        ):
            raise ArtifactValidationError("Canonical audit row is not the frozen PASS result.")
        expected_hash = protocol_hash(
            "audit_detail/v1",
            {
                "audit_id": row["audit_id"],
                "expected": row["expected"],
                "observed": row["observed"],
            },
        )
        if row["audit_detail_sha256"] != expected_hash:
            raise ArtifactValidationError("Audit detail hash differs.")
    if audits["all_passed"] is not True:
        raise ArtifactValidationError("Canonical audit artifact is not all-pass.")
    if set(manifest) != set(RUN_MANIFEST_FIELDS) or manifest["status"] != "complete":
        raise ArtifactValidationError("run_manifest.json scientific fields differ.")
    if manifest["evaluation_id"] != EVALUATION_ID:
        raise ArtifactValidationError("Manifest evaluation ID differs.")
    gate = _mapping(graph.artifact("gate_evaluations.json").scientific, "gate")
    # Local import avoids the projection -> audits -> graph import cycle while preserving one
    # authoritative recommendation-commitment implementation for creation and validation.
    from research_decision_engine.benchmarks.broader_projection import (
        recommendation_scientific_payload_identity,
    )

    expected_recommendation_identity = recommendation_scientific_payload_identity(gate)
    if (
        graph.artifact("run_manifest.json").operational["recommendation_scientific_payload_sha256"]
        != expected_recommendation_identity
    ):
        raise ArtifactValidationError(
            "Manifest recommendation commitment does not derive from the reopened gate."
        )
    _validate_manifest_counts(graph, manifest)
    _validate_operational_finalization_fields(graph)
    _validate_artifact_hash_maps(graph)


def _validate_recommendation_graph(
    graph: CanonicalArtifactGraph, snapshot: ProtocolSnapshot
) -> None:
    del snapshot
    recommendation = _mapping(graph.artifact("recommendation.json").scientific, "recommendation")
    gate = _mapping(graph.artifact("gate_evaluations.json").scientific, "gate")
    if recommendation["evaluation_id"] != EVALUATION_ID:
        raise ArtifactValidationError("Recommendation evaluation ID differs.")
    if set(recommendation) != set(RECOMMENDATION_FIELDS):
        raise ArtifactValidationError("recommendation.json fields differ.")
    if recommendation["integrity_status"] != "PASS":
        raise ArtifactValidationError("Recommendation integrity status is not PASS.")
    if (
        recommendation["gate_evaluation_scientific_payload_sha256"]
        != graph.artifact("gate_evaluations.json").scientific_payload_sha256
    ):
        raise ArtifactValidationError("Recommendation gate payload binding differs.")
    for left, right in (
        ("recommendation", "recommendation"),
        ("decision_precedence", "decision_precedence"),
        ("branch_id", "final_branch_id"),
        ("branch_trace", "final_branch_trace"),
        ("gate_status", "final_gate_status"),
        ("unique_mechanism_id", "unique_mechanism_id"),
    ):
        if recommendation[left] != gate[right]:
            raise ArtifactValidationError(f"Recommendation {left} differs from gate artifact.")
    surviving = _action_tuples(gate["P"], "P")
    expected_scopes = []
    if gate["final_branch_id"] == "BRANCH-B":
        expected_scopes = list(dict.fromkeys(item[0] for item in surviving))
        if recommendation["unique_mechanism_id"] is None:
            raise ArtifactValidationError("Branch B recommendation lacks its mechanism.")
    elif recommendation["unique_mechanism_id"] is not None:
        raise ArtifactValidationError("A/C/D recommendation contains a mechanism.")
    if recommendation["authorized_policy_scopes"] != expected_scopes:
        raise ArtifactValidationError("Recommendation policy scopes differ from surviving P.")
    manifest_artifact = graph.artifact("run_manifest.json")
    if graph.artifact("recommendation.json").operational["run_manifest_content_sha256"] != (
        manifest_artifact.content_sha256
    ):
        raise ArtifactValidationError("Recommendation manifest binding differs.")
    if (
        manifest_artifact.operational["recommendation_scientific_payload_sha256"]
        != graph.artifact("recommendation.json").scientific_payload_sha256
    ):
        raise ArtifactValidationError("Manifest recommendation payload binding differs.")


def _validate_manifest_counts(
    graph: CanonicalArtifactGraph, manifest: Mapping[str, object]
) -> None:
    expected = _mapping(manifest["expected_counts"], "expected_counts")
    frozen = {
        "arm_runs": 36_864,
        "fixed_calibrated_comparisons": 18_432,
        "calibration_estimates": 9_216,
        "calibration_effects": 46_080,
        "calibration_observations": 92_160,
        "calibration_oracle_use_rows": 552_960,
        "oracle_conformance_keys": 117_952,
        "confirmatory_contrasts": 66,
        "holm_hypotheses": 64,
        "decision_contrasts": 20,
        "descriptive_contrasts": 36,
        "contrast_rows": 122,
        "bootstrap_rows": 660_000,
        "sign_flip_rows": 640_000,
        "total_resampling_rows": 1_300_000,
        "count_symbol_registry_rows": 9,
        "decision_symbol_registry_rows": 9,
        "formula_registry_rows": 43,
        "gate_condition_registry_rows": 66,
        "gate_rows": 44,
        "branch_registry_rows": 4,
        "controller_stage_registry_rows": 6,
        "budget_registry_rows": 3,
        "audit_rows": 16,
        "canonical_artifacts": 13,
    }
    if expected != frozen:
        raise ArtifactValidationError("Manifest expected counts differ from the freeze.")
    observed = _mapping(manifest["observed_counts"], "observed_counts")
    required_observed = {
        "arm_runs": len(_rows(graph, "arm_runs.jsonl")),
        "fixed_calibrated_comparisons": len(_rows(graph, "comparisons.jsonl")),
        "calibration_estimates": len(_rows(graph, "calibration_estimates.jsonl")),
        "contrast_rows": len(_rows(graph, "contrast_results.csv")),
        "bootstrap_rows": sum(
            row["record_type"] == "bootstrap" for row in _rows(graph, "resampling_audit.jsonl")
        ),
        "sign_flip_rows": sum(
            row["record_type"] == "sign_flip" for row in _rows(graph, "resampling_audit.jsonl")
        ),
        "decision_events": sum(
            _event_type(row) == "decision" for row in _rows(graph, "trajectory_events.jsonl")
        ),
        "trajectory_events": len(_rows(graph, "trajectory_events.jsonl")),
        "selected_oracle_uses": sum(
            row["record_type"] == "oracle_use" for row in _rows(graph, "oracle_provenance.jsonl")
        ),
    }
    if set(observed) != set(required_observed):
        raise ArtifactValidationError("Manifest observed-count key universe differs.")
    for key, value in required_observed.items():
        if observed.get(key) != value:
            raise ArtifactValidationError(f"Manifest observed count {key} does not reconcile.")
    schema_version = manifest["database_schema_version"]
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version < 0
    ):
        raise ArtifactValidationError("Manifest database schema version is not a nonnegative I64.")


def _validate_operational_finalization_fields(graph: CanonicalArtifactGraph) -> None:
    audits = graph.artifact("audit_results.json").operational
    manifest = graph.artifact("run_manifest.json").operational
    for field in ("implementation_commit",):
        value = manifest[field]
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
            raise ArtifactValidationError(f"Manifest {field} is not GIT40.")
    for field in ("implementation_tree_sha256", "implementation_diff_sha256"):
        validate_sha256(manifest[field], f"Manifest {field}")
    if not isinstance(manifest["implementation_tree_clean"], bool):
        raise ArtifactValidationError("Manifest implementation_tree_clean is not BOOL.")
    if manifest["implementation_tree_clean"] is not True:
        raise ArtifactValidationError("Manifest requires an actually clean implementation tree.")
    for field in ("started_at", "completed_at"):
        value = manifest[field]
        if not isinstance(value, str) or TS_PATTERN.fullmatch(value) is None:
            raise ArtifactValidationError(f"Manifest {field} is not canonical TS.")
    if cast(str, manifest["completed_at"]) < cast(str, manifest["started_at"]):
        raise ArtifactValidationError("Manifest completion precedes its start time.")
    for field in ("dependency_versions", "machine"):
        values = _mapping(manifest[field], f"Manifest {field}")
        if not values or tuple(values) != tuple(
            sorted(values, key=lambda item: item.encode("utf-8"))
        ):
            raise ArtifactValidationError(f"Manifest {field} key ordering differs.")
        if not all(
            isinstance(key, str) and isinstance(value, str) for key, value in values.items()
        ):
            raise ArtifactValidationError(f"Manifest {field} entries are not strings.")
    audit_before = _validated_sha_map(audits["historical_before_sha256"], "audit before")
    audit_after = _validated_sha_map(audits["historical_after_sha256"], "audit after")
    manifest_before = _validated_sha_map(manifest["historical_before_sha256"], "manifest before")
    manifest_after = _validated_sha_map(manifest["historical_after_sha256"], "manifest after")
    if not audit_before or not (audit_before == audit_after == manifest_before == manifest_after):
        raise ArtifactValidationError("Historical finalization hash maps differ.")


def _validated_sha_map(value: object, path: str) -> dict[str, object]:
    mapping = _mapping(value, path)
    if tuple(mapping) != tuple(sorted(mapping, key=lambda item: item.encode("utf-8"))):
        raise ArtifactValidationError(f"{path} key ordering differs.")
    for key, digest in mapping.items():
        if not isinstance(key, str) or not key:
            raise ArtifactValidationError(f"{path} contains an invalid key.")
        validate_sha256(digest, path)
    return dict(mapping)


def _validate_artifact_hash_maps(graph: CanonicalArtifactGraph) -> None:
    audits = graph.artifact("audit_results.json")
    manifest = graph.artifact("run_manifest.json")
    audit_content = _mapping(audits.operational["artifact_content_sha256"], "audit content hashes")
    audit_payload = _mapping(
        audits.operational["artifact_scientific_payload_sha256"], "audit payload hashes"
    )
    manifest_content = _mapping(
        manifest.operational["artifact_content_sha256"], "manifest content hashes"
    )
    manifest_payload = _mapping(
        manifest.operational["artifact_scientific_payload_sha256"], "manifest payload hashes"
    )
    first_ten = graph.artifacts[:10]
    first_eleven = graph.artifacts[:11]
    if audit_content != {item.contract.filename: item.content_sha256 for item in first_ten}:
        raise ArtifactValidationError("Audit artifact content hash map differs.")
    if audit_payload != {
        item.contract.filename: item.scientific_payload_sha256 for item in first_ten
    }:
        raise ArtifactValidationError("Audit scientific-payload hash map differs.")
    if manifest_content != {item.contract.filename: item.content_sha256 for item in first_eleven}:
        raise ArtifactValidationError("Manifest artifact content hash map differs.")
    if manifest_payload != {
        item.contract.filename: item.scientific_payload_sha256 for item in first_eleven
    }:
        raise ArtifactValidationError("Manifest scientific-payload hash map differs.")


def _decode_contrast_row(raw: Mapping[str, str | None], index: int) -> dict[str, object]:
    row: dict[str, object] = {}
    json_fields = {"missingness_counts"}
    bool_fields = {"holm_member"}
    integer_fields = {
        "n_present",
        "n_absent",
        "usable_bootstrap_replicates",
        "permutation_count",
        "extreme_count",
        "holm_rank",
    }
    nullable_fields = {
        "source_contrast_id",
        "n_present",
        "n_absent",
        "present_weight",
        "absent_weight",
        "left_value",
        "right_value",
        "left_denominator",
        "right_denominator",
        "estimate",
        "ci_low",
        "ci_high",
        "test_statistic",
        "permutation_count",
        "extreme_count",
        "p_raw",
        "p_adjusted",
        "holm_rank",
        "statistical_hypothesis_id",
    }
    for field in CONTRAST_HEADER[len(ENVELOPE_FIELDS) :]:
        value = raw.get(field)
        if value is None:
            raise ArtifactValidationError(f"contrast_results.csv[{index}].{field} is missing.")
        if value == "" and field in nullable_fields:
            row[field] = None
        elif field in json_fields:
            try:
                row[field] = json.loads(value)
            except json.JSONDecodeError as error:
                raise ArtifactValidationError("Contrast JSON cell is malformed.") from error
        elif field in bool_fields:
            if value not in {"true", "false"}:
                raise ArtifactValidationError("Contrast BOOL cell is malformed.")
            row[field] = value == "true"
        elif field in integer_fields:
            try:
                row[field] = int(value)
            except ValueError as error:
                raise ArtifactValidationError("Contrast I64 cell is malformed.") from error
        else:
            row[field] = value
    return row


def _encode_csv(header: Sequence[str], rows: Sequence[Mapping[str, object]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=header, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        rendered: dict[str, object] = {}
        for key in header:
            value = row[key]
            if isinstance(value, (dict, list, tuple)):
                rendered[key] = json.dumps(value, sort_keys=True, separators=(",", ":"))
            elif isinstance(value, bool):
                rendered[key] = "true" if value else "false"
            elif value is None:
                rendered[key] = ""
            else:
                rendered[key] = value
        writer.writerow(rendered)
    return output.getvalue().encode("utf-8")


def _json_object(content: bytes, path: str) -> dict[str, object]:
    try:
        decoded = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArtifactValidationError(f"{path} is not valid UTF-8 JSON.") from error
    if not isinstance(decoded, dict):
        raise ArtifactValidationError(f"{path} must be a JSON object.")
    return cast(dict[str, object], decoded)


def _rows(graph: CanonicalArtifactGraph, filename: str) -> tuple[Mapping[str, object], ...]:
    value = graph.artifact(filename).scientific
    if not isinstance(value, tuple) or not all(isinstance(item, Mapping) for item in value):
        raise ArtifactValidationError(f"{filename} did not decode to ordered rows.")
    return cast(tuple[Mapping[str, object], ...], value)


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ArtifactValidationError(f"{path} must be an object.")
    return cast(Mapping[str, object], value)


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise ArtifactValidationError(f"{path} must be an ordered list.")
    return value


def _unique(rows: Sequence[Mapping[str, object]], fields: Sequence[str], label: str) -> None:
    keys = [tuple(row[field] for field in fields) for row in rows]
    if len(keys) != len(set(keys)):
        raise ArtifactValidationError(f"Duplicate {label} key.")


def _require_count(label: str, rows: Sequence[object], expected: int) -> None:
    if len(rows) != expected:
        raise ArtifactValidationError(f"{label} count is {len(rows)}; expected {expected}.")


def _event_payload(row: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping(row["event_payload"], "CanonicalEventPayload")


def _event_id(row: Mapping[str, object]) -> str:
    return cast(str, _event_payload(row)["event_id"])


def _event_type(row: Mapping[str, object]) -> str:
    return cast(str, _event_payload(row)["event_type"])


def _f64_value(value: object) -> float:
    if not isinstance(value, str) or re.fullmatch(r"f64:[0-9a-f]{16}", value) is None:
        raise ArtifactValidationError("Expected canonical F64.")
    import struct

    result = cast(float, struct.unpack(">d", bytes.fromhex(value[4:]))[0])
    if not math.isfinite(result) or (result == 0.0 and value != f64(0.0)):
        raise ArtifactValidationError("F64 is nonfinite or negative zero.")
    return result


def _validate_probability_map(value: object, path: str) -> None:
    probabilities = _mapping(value, path)
    expected = {
        "optimizer.adam-advantage",
        "optimizer.no-consistent-advantage",
        "optimizer.sgd-advantage",
    }
    if set(probabilities) != expected:
        raise ArtifactValidationError(f"{path} hypothesis keys differ.")
    values = [_f64_value(item) for item in probabilities.values()]
    if any(item < 0.0 for item in values) or not math.isclose(
        math.fsum(values), 1.0, abs_tol=1e-12
    ):
        raise ArtifactValidationError(f"{path} does not contain normalized probabilities.")


def _action_tuple(value: object, path: str) -> tuple[str, str, str, str]:
    row = _mapping(value, path)
    fields = (
        "policy_scope",
        "mechanism_id",
        "decision_contrast_id",
        "confirmatory_contrast_id",
    )
    if set(row) != set(fields):
        raise ArtifactValidationError(f"{path} ActionTuple fields differ.")
    return tuple(cast(str, row[field]) for field in fields)  # type: ignore[return-value]


def _action_tuples(value: object, path: str) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(_action_tuple(item, path) for item in _list(value, path))


def _world_index(world_id: str) -> int:
    for index, world in enumerate(WORLDS):
        if world.public.world_id == world_id:
            return index
    raise ArtifactValidationError(f"Unknown world ID {world_id}.")


def _utf8_key(value: object) -> bytes:
    return str(value).encode("utf-8")


def _registry_hash_from_payload(
    snapshot: ProtocolSnapshot, registry_name: str, identifier: str, hash_field: str
) -> str:
    payload = build_protocol_snapshot_payload(snapshot)
    key = f"{registry_name}_registry"
    rows = cast(list[dict[str, object]], payload[key])
    id_fields = {
        "formula": "formula_id",
        "gate": "gate_id",
        "gate_condition": "condition_id",
        "veto": "veto_id",
    }
    for row in rows:
        if row[id_fields[registry_name]] == identifier:
            return cast(str, row[hash_field])
    raise ArtifactValidationError(f"Registry hash owner {identifier} is missing.")
