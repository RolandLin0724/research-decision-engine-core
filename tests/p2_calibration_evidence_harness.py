"""Deterministic test-owned Stage-2F P1, P2, and P3 calibration fixtures.

The harness constructs immutable scientific records directly.  It never calls
the production calibration selector, a live Oracle, a workload, persistence, or
an evidence writer.  Raw effect payload SHA-256 values are deliberately
recomputed here with ``hashlib`` rather than delegated to production.
"""

from __future__ import annotations

import hashlib
import math
import statistics
from collections.abc import Callable
from dataclasses import replace as dataclass_replace
from typing import Final, Literal, cast

from research_decision_engine.belief_models import (
    SIGMA_FLOOR,
    MatchedEffectObservation,
)
from research_decision_engine.benchmarks.broader_calibration_evidence import (
    CalibrationCandidatePairProjection,
    CalibrationSourceObservationProjection,
    ScientificCalibrationSelectionProjection,
    StrictChronologyProjection,
    _P3SelectionInput,
)
from research_decision_engine.benchmarks.broader_calibration_history import (
    CALIBRATION_ELIGIBILITY_BASIS,
    CALIBRATION_SIGMA_DDOF,
    CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
    CalibrationHistorySelection,
    expected_calibration_effect,
)
from research_decision_engine.benchmarks.broader_conformance import (
    CONFORMANCE_DEPTH_THREE_SEEDS,
    CONFORMANCE_DEPTH_THREE_WORLD_ID,
    CONFORMANCE_SEEDS,
    CONFORMANCE_WORLD_ID,
)
from research_decision_engine.benchmarks.broader_execution import (
    ReturnedResultsProjection,
)
from research_decision_engine.benchmarks.broader_oracle import (
    CALIBRATION_NAMESPACE,
    ORACLE_VERSION,
    RevealedObservation,
    calibration_key,
    transform_key,
)
from research_decision_engine.benchmarks.broader_protocol import (
    PROTOCOL_CHECKPOINT,
    PROTOCOL_VERSION,
    SMOKE_SEEDS,
    SMOKE_WORLD_IDS,
    canonical_json_bytes,
    f64,
    protocol_hash,
    runtime_id,
)
from research_decision_engine.benchmarks.broader_returned_run import (
    ReturnedRunProjection,
    RunBeliefStateProjection,
    RunCalibrationEstimateProjection,
    RunCalibrationProjection,
    RunLineageProjection,
    RunMatchedEffectProjection,
    RunModelBeliefStateProjection,
    RunObservationAuthorizationProjection,
    RunRevealedObservationProjection,
    project_matched_effect,
)
from research_decision_engine.benchmarks.broader_validation_evidence import (
    FileProjection,
    ImplementationProjection,
    InterpreterIdentityProjection,
    PlatformIdentityProjection,
    RuntimeProjection,
)
from research_decision_engine.benchmarks.broader_worlds import (
    GROUP_IDS,
    WORLDS_BY_ID,
    BenchmarkWorld,
    candidate_costs,
    hidden_arm_mean,
    hidden_observation_sigma,
)

type ExecutionRole = Literal[
    "primary_smoke",
    "altered_order_replay",
    "fixture_primary",
    "fixture_replay",
]
type SelectionCoordinate = tuple[ExecutionRole, str, int, str]
type CandidatePair = tuple[str, str]
type ReplicationRanks = tuple[int, int, int, int, int]
type EffectEvidence = tuple[str, bytes, str, RunMatchedEffectProjection]
type SelectionEvidence = tuple[
    str,
    int,
    str,
    int,
    str,
    str,
    str,
    str,
    str,
    tuple[str, str, str],
    tuple[CandidatePair, ...],
    tuple[CalibrationCandidatePairProjection, ...],
    tuple[str, ...],
    tuple[str, ...],
    ReplicationRanks,
    tuple[str, ...],
    CalibrationHistorySelection,
    tuple[EffectEvidence, ...],
    StrictChronologyProjection,
    str,
]
type ExecutionAttestationPairs = tuple[
    tuple[str, str],
    tuple[str, str],
    tuple[str, str],
    tuple[str, str],
]
type AttestedSpecificationIds = tuple[str, str, str, str]
type ValidBundle = tuple[
    tuple[SelectionEvidence, ...],
    ExecutionAttestationPairs,
    AttestedSpecificationIds,
]
type OracleImplementationRelation = tuple[str, str]
type OraclePredecessor = tuple[
    str,
    str,
    OracleImplementationRelation,
    str,
    str,
    str,
    int,
    str,
    tuple[CandidatePair, ...],
    tuple[str, ...],
    BenchmarkWorld,
]
type SourceObservationEvidence = tuple[
    CalibrationSourceObservationProjection,
    str,
]
type P2SelectionEvidence = tuple[
    OraclePredecessor,
    tuple[SourceObservationEvidence, ...],
]
type P2ValidBundle = tuple[
    tuple[SelectionEvidence, ...],
    ExecutionAttestationPairs,
    AttestedSpecificationIds,
    tuple[P2SelectionEvidence, ...],
    tuple[OraclePredecessor, ...],
]
type ReturnedResultsByRole = tuple[
    ReturnedResultsProjection,
    ReturnedResultsProjection,
    ReturnedResultsProjection,
    ReturnedResultsProjection,
]
type P3ReturnedResultRow = tuple[str, ReturnedRunProjection, str]
type P3ValidBundle = tuple[
    tuple[SelectionEvidence, ...],
    ExecutionAttestationPairs,
    AttestedSpecificationIds,
    tuple[P2SelectionEvidence, ...],
    tuple[OraclePredecessor, ...],
    ReturnedResultsByRole,
    tuple[_P3SelectionInput, ...],
]
type _ScopeFixture = tuple[
    str,
    tuple[CandidatePair, ...],
    tuple[CalibrationCandidatePairProjection, ...],
    tuple[str, ...],
    tuple[str, ...],
    ReplicationRanks,
    tuple[str, ...],
    CalibrationHistorySelection,
    tuple[EffectEvidence, ...],
]
type _P2ScopeFixture = tuple[
    CalibrationHistorySelection,
    tuple[str, ...],
    tuple[EffectEvidence, ...],
    tuple[SourceObservationEvidence, ...],
]
type _P3GroupFixture = tuple[
    CalibrationHistorySelection,
    ScientificCalibrationSelectionProjection,
    RunCalibrationEstimateProjection,
]
type _P3WitnessFixture = tuple[
    str,
    ReturnedRunProjection,
    str,
    tuple[_P3GroupFixture, _P3GroupFixture, _P3GroupFixture],
]

CANDIDATE_PAIR_SCHEMA: Final = "broader-replication-calibration-candidate-pair/v1"
STRICT_CHRONOLOGY_SCHEMA: Final = "broader-replication-calibration-chronology/v1"
CANDIDATE_PAIR_ID_DOMAIN: Final = "validation_evidence_calibration_candidate_pair/v1"
STRICT_CHRONOLOGY_ID_DOMAIN: Final = "validation_evidence_calibration_chronology/v1"
SOURCE_OBSERVATION_SCHEMA: Final = "broader-replication-calibration-source-observation/v1"
SOURCE_OBSERVATION_ID_DOMAIN: Final = "validation_evidence_calibration_source_observation/v1"
SCIENTIFIC_SELECTION_ID_DOMAIN: Final = "broader-calibration-history-selection/v1"
P3_WITNESS_BUDGET_ID: Final = "budget-2.25"
P3_WITNESS_BUDGET: Final = "f64:4002000000000000"
P3_WITNESS_ARM: Final = (
    "calibrated_ig",
    2,
    "replicated_noise_calibrated_gaussian",
    "information_gain",
)
P3_RETURNED_RUN_SCHEMA: Final = "broader-replication-returned-run/v1"
P3_RETURNED_RESULTS_SCHEMA: Final = "broader-replication-returned-results/v1"
REPLICATION_RANKS: Final[ReplicationRanks] = (1, 2, 3, 4, 5)
P2_ARM_ORDER: Final[tuple[Literal["adam", "sgd"], Literal["adam", "sgd"]]] = (
    "adam",
    "sgd",
)
ROLE_ORDER: Final[tuple[ExecutionRole, ...]] = (
    "primary_smoke",
    "altered_order_replay",
    "fixture_primary",
    "fixture_replay",
)
ROLE_COUNTS: Final[tuple[tuple[ExecutionRole, int], ...]] = (
    ("primary_smoke", 96),
    ("altered_order_replay", 96),
    ("fixture_primary", 63),
    ("fixture_replay", 63),
)
ROLE_PARTITIONS: Final[tuple[tuple[ExecutionRole, int, int], ...]] = (
    ("primary_smoke", 0, 96),
    ("altered_order_replay", 96, 192),
    ("fixture_primary", 192, 255),
    ("fixture_replay", 255, 318),
)

SMOKE_COORDINATES: Final[tuple[SelectionCoordinate, ...]] = tuple(
    (role, world_id, seed, comparison_group_id)
    for role in ROLE_ORDER[:2]
    for world_id in SMOKE_WORLD_IDS
    for seed in SMOKE_SEEDS
    for comparison_group_id in GROUP_IDS
)
FIXTURE_WORLD_SEEDS: Final = (
    (CONFORMANCE_WORLD_ID, CONFORMANCE_SEEDS),
    (CONFORMANCE_DEPTH_THREE_WORLD_ID, CONFORMANCE_DEPTH_THREE_SEEDS),
)
FIXTURE_COORDINATES: Final[tuple[SelectionCoordinate, ...]] = tuple(
    (role, world_id, seed, comparison_group_id)
    for role in ROLE_ORDER[2:]
    for world_id, seeds in FIXTURE_WORLD_SEEDS
    for seed in seeds
    for comparison_group_id in GROUP_IDS
)
CANONICAL_COORDINATES: Final[tuple[SelectionCoordinate, ...]] = (
    SMOKE_COORDINATES + FIXTURE_COORDINATES
)
CANONICAL_SELECTION_COUNT: Final = 318

SELECTION_FIELD_NAMES: Final = (
    "role",
    "position",
    "world_id",
    "seed",
    "comparison_group_id",
    "calibration_namespace",
    "calibration_prefix_id",
    "execution_specification_id",
    "executor_attestation_id",
    "study_occurrences",
    "ordered_candidate_pairs",
    "ordered_candidate_pair_projections",
    "ordered_candidate_pair_ids",
    "ordered_replication_ids",
    "replication_ranks",
    "ordered_source_effect_ids",
    "selector_result",
    "ordered_source_effects",
    "strict_chronology",
    "strict_chronology_id",
)
ROLE_INDEX: Final = 0
POSITION_INDEX: Final = 1
WORLD_ID_INDEX: Final = 2
SEED_INDEX: Final = 3
COMPARISON_GROUP_ID_INDEX: Final = 4
CALIBRATION_NAMESPACE_INDEX: Final = 5
CALIBRATION_PREFIX_ID_INDEX: Final = 6
EXECUTION_SPECIFICATION_ID_INDEX: Final = 7
EXECUTOR_ATTESTATION_ID_INDEX: Final = 8
STUDY_OCCURRENCES_INDEX: Final = 9
ORDERED_CANDIDATE_PAIRS_INDEX: Final = 10
ORDERED_CANDIDATE_PAIR_PROJECTIONS_INDEX: Final = 11
ORDERED_CANDIDATE_PAIR_IDS_INDEX: Final = 12
ORDERED_REPLICATION_IDS_INDEX: Final = 13
REPLICATION_RANKS_INDEX: Final = 14
ORDERED_SOURCE_EFFECT_IDS_INDEX: Final = 15
SELECTOR_RESULT_INDEX: Final = 16
ORDERED_SOURCE_EFFECTS_INDEX: Final = 17
STRICT_CHRONOLOGY_INDEX: Final = 18
STRICT_CHRONOLOGY_ID_INDEX: Final = 19

EFFECT_EVIDENCE_FIELD_NAMES: Final = (
    "effect_id",
    "payload_bytes",
    "payload_sha256",
    "projection",
)
EFFECT_ID_INDEX: Final = 0
EFFECT_PAYLOAD_BYTES_INDEX: Final = 1
EFFECT_PAYLOAD_SHA256_INDEX: Final = 2
EFFECT_PROJECTION_INDEX: Final = 3

SOURCE_OBSERVATION_FIELD_NAMES: Final = (
    "candidate_id",
    "comparison_group_id",
    "digest",
    "intervention_arm",
    "key_fields",
    "namespace",
    "oracle_key_id",
    "outcome_digest",
    "replication_id",
    "revealed_observation",
    "schema_version",
    "seed",
    "serialized_key_hex",
    "u",
    "world_id",
    "z",
)
P2_ORDERED_SOURCE_OBSERVATIONS_INDEX: Final = 1

P3_INPUT_FIELD_NAMES: Final = (
    "returned_result_id",
    "returned_run_projection",
    "submitted_job_id",
    "selector_result_projection",
    "selector_result_identity",
)


def _test_h64(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _predecessor_pairs() -> ExecutionAttestationPairs:
    pairs: list[tuple[str, str]] = []
    for role in ROLE_ORDER:
        specification_id = protocol_hash(
            "validation_evidence_execution_specification/v1",
            {
                "fixture": "stage2f-p1-harness",
                "role": role,
            },
        )
        attestation_id = protocol_hash(
            "validation_evidence_executor_attestation/v1",
            {
                "execution_specification_id": specification_id,
                "fixture": "stage2f-p1-harness",
                "role": role,
            },
        )
        pairs.append((specification_id, attestation_id))
    return cast(ExecutionAttestationPairs, tuple(pairs))


def _observation(
    *,
    world_id: str,
    seed: int,
    comparison_group_id: str,
    group_index: int,
    replication_index: int,
    intervention_arm: Literal["adam", "sgd"],
    revealed_observation: float,
) -> RevealedObservation:
    candidate_id = f"cal-{group_index:02d}-{intervention_arm}-r{replication_index:04d}"
    replication_id = f"calibration-{group_index:02d}-r{replication_index:04d}"
    run_id = f"p1-harness/{world_id}/{seed}/{comparison_group_id}"
    prefix_id = f"calibration-prefix/{world_id}/{seed}/{comparison_group_id}"
    source_id = f"{prefix_id}/{candidate_id}"
    authorization_id = runtime_id(
        "authorization",
        "authorization_id/v1",
        {
            "candidate_id": candidate_id,
            "kind": "calibration",
            "run_id": run_id,
            "source_id": source_id,
        },
    )
    key_fields = (
        CALIBRATION_NAMESPACE,
        PROTOCOL_VERSION,
        "calibration",
        world_id,
        str(seed),
        comparison_group_id,
        intervention_arm,
        replication_id,
    )
    oracle_key_id = runtime_id(
        "oracle-key",
        "oracle_key_id/v1",
        {"key_fields": list(key_fields)},
    )
    serialized_key = canonical_json_bytes(list(key_fields))
    outcome_digest = protocol_hash(
        "revealed_outcome/v1",
        {
            "oracle_key_id": oracle_key_id,
            "revealed_observation": f64(revealed_observation),
        },
    )
    return RevealedObservation(
        oracle_key_id=oracle_key_id,
        oracle_use_id=f"oracle-use/{authorization_id}/{oracle_key_id}",
        authorization_id=authorization_id,
        namespace=CALIBRATION_NAMESPACE,
        world_id=world_id,
        seed=seed,
        candidate_id=candidate_id,
        comparison_group_id=comparison_group_id,
        intervention_arm=intervention_arm,
        replication_id=replication_id,
        key_fields=key_fields,
        serialized_key_hex=serialized_key.hex(),
        digest=hashlib.sha256(serialized_key).hexdigest(),
        u="0.5",
        z="0.0",
        revealed_observation=revealed_observation,
        outcome_digest=outcome_digest,
    )


def _build_scope_fixture(
    *,
    world_id: str,
    seed: int,
    comparison_group_id: str,
) -> _ScopeFixture:
    group_index = GROUP_IDS.index(comparison_group_id)
    prefix_id = f"calibration-prefix/{world_id}/{seed}/{comparison_group_id}"
    candidate_pairs: list[CandidatePair] = []
    pair_projections: list[CalibrationCandidatePairProjection] = []
    pair_ids: list[str] = []
    replication_ids: list[str] = []
    effect_ids: list[str] = []
    effect_values: list[float] = []
    observations: list[RevealedObservation] = []
    effects = []
    effect_evidence: list[EffectEvidence] = []

    for replication_index in REPLICATION_RANKS:
        replication_id = f"calibration-{group_index:02d}-r{replication_index:04d}"
        adam_candidate_id = f"cal-{group_index:02d}-adam-r{replication_index:04d}"
        sgd_candidate_id = f"cal-{group_index:02d}-sgd-r{replication_index:04d}"
        pair = (adam_candidate_id, sgd_candidate_id)
        pair_projection = CalibrationCandidatePairProjection(
            adam_candidate_id=adam_candidate_id,
            comparison_group_id=comparison_group_id,
            replication_id=replication_id,
            schema_version=CANDIDATE_PAIR_SCHEMA,
            sgd_candidate_id=sgd_candidate_id,
            world_id=world_id,
        )
        candidate_pairs.append(pair)
        pair_projections.append(pair_projection)
        pair_ids.append(expected_candidate_pair_id(pair_projection))
        replication_ids.append(replication_id)

        expected_value = replication_index / 8.0 + group_index / 64.0
        sgd_value = group_index / 128.0
        adam_value = sgd_value + expected_value
        adam_observation = _observation(
            world_id=world_id,
            seed=seed,
            comparison_group_id=comparison_group_id,
            group_index=group_index,
            replication_index=replication_index,
            intervention_arm="adam",
            revealed_observation=adam_value,
        )
        sgd_observation = _observation(
            world_id=world_id,
            seed=seed,
            comparison_group_id=comparison_group_id,
            group_index=group_index,
            replication_index=replication_index,
            intervention_arm="sgd",
            revealed_observation=sgd_value,
        )
        observations.extend((adam_observation, sgd_observation))
        observed_effect = round(
            adam_observation.revealed_observation - sgd_observation.revealed_observation,
            12,
        )
        effect = expected_calibration_effect(
            prefix_id=prefix_id,
            world_id=world_id,
            comparison_group_id=comparison_group_id,
            group_index=group_index,
            replication_index=replication_index,
            observed_effect=observed_effect,
        )
        payload_bytes = canonical_json_bytes(effect.to_dict(), final_lf=True)
        payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
        projection = project_matched_effect(effect)
        effects.append(effect)
        effect_ids.append(effect.effect_id)
        effect_values.append(effect.observed_effect)
        effect_evidence.append(
            (
                effect.effect_id,
                payload_bytes,
                payload_sha256,
                projection,
            )
        )

    effect_tuple = tuple(effects)
    observation_tuple = tuple(observations)
    pair_tuple = tuple(candidate_pairs)
    replication_tuple = tuple(replication_ids)
    effect_id_tuple = tuple(effect_ids)
    digest_tuple = cast(
        tuple[str, ...],
        tuple(item[EFFECT_PAYLOAD_SHA256_INDEX] for item in effect_evidence),
    )
    value_tuple = tuple(effect_values)
    selector_result = CalibrationHistorySelection(
        study_id=PROTOCOL_VERSION,
        world_id=world_id,
        seed=seed,
        namespace=CALIBRATION_NAMESPACE,
        comparison_group_id=comparison_group_id,
        target_comparison_group_id=comparison_group_id,
        source_sequence_cutoff=CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
        source_effect_ids=effect_id_tuple,
        source_effect_payload_sha256=digest_tuple,
        # P2 owns Oracle/source-observation identity lists.  Empty values make
        # accidental P2 validation during P1 immediately visible in tests.
        source_observation_identities=(),
        source_oracle_key_ids=(),
        source_candidate_pairs=pair_tuple,
        source_replication_ids=replication_tuple,
        effect_values=value_tuple,
        # P3 owns scientific summary and selector identity fields.  These
        # deterministic sentinels are intentionally not valid P3 output.
        sample_count=0,
        sample_mean=0.0,
        sample_standard_deviation=0.0,
        ddof=0,
        sigma_floor=0.0,
        estimated_sigma=0.0,
        physical_cost=0.0,
        eligibility_basis="stage2f-p1-inert",
        current_observation_excluded=True,
        current_effect_excluded=True,
        future_history_excluded=True,
        effects=effect_tuple,
        observations=observation_tuple,
        selection_identity=_test_h64(f"inert-selector/{world_id}/{seed}/{comparison_group_id}"),
    )
    return (
        prefix_id,
        pair_tuple,
        tuple(pair_projections),
        tuple(pair_ids),
        replication_tuple,
        REPLICATION_RANKS,
        effect_id_tuple,
        selector_result,
        tuple(effect_evidence),
    )


def build_valid_bundle() -> ValidBundle:
    """Build a fresh, direct-constructor canonical 318-selection P1 bundle."""

    expected_pairs = _predecessor_pairs()
    attested_specification_ids: AttestedSpecificationIds = (
        expected_pairs[0][0],
        expected_pairs[1][0],
        expected_pairs[2][0],
        expected_pairs[3][0],
    )
    chronology = StrictChronologyProjection(
        current_effect_excluded=True,
        current_observation_excluded=True,
        effect_available_sequences=(0, 0, 0, 0, 0),
        future_history_excluded=True,
        schema_version=STRICT_CHRONOLOGY_SCHEMA,
        source_sequence_cutoff=1,
    )
    chronology_identity = expected_strict_chronology_id(chronology)
    scopes: dict[tuple[str, int, str], _ScopeFixture] = {}
    selections: list[SelectionEvidence] = []

    for position in range(len(CANONICAL_COORDINATES)):
        role, world_id, seed, comparison_group_id = CANONICAL_COORDINATES[position]
        scope_key = (world_id, seed, comparison_group_id)
        scope = scopes.get(scope_key)
        if scope is None:
            scope = _build_scope_fixture(
                world_id=world_id,
                seed=seed,
                comparison_group_id=comparison_group_id,
            )
            scopes[scope_key] = scope
        (
            prefix_id,
            candidate_pairs,
            pair_projections,
            pair_ids,
            replication_ids,
            replication_ranks,
            effect_ids,
            selector_result,
            effect_evidence,
        ) = scope
        role_index = ROLE_ORDER.index(role)
        execution_specification_id, executor_attestation_id = expected_pairs[role_index]
        selections.append(
            (
                role,
                position,
                world_id,
                seed,
                comparison_group_id,
                CALIBRATION_NAMESPACE,
                prefix_id,
                execution_specification_id,
                executor_attestation_id,
                (PROTOCOL_VERSION, PROTOCOL_VERSION, PROTOCOL_VERSION),
                candidate_pairs,
                pair_projections,
                pair_ids,
                replication_ids,
                replication_ranks,
                effect_ids,
                selector_result,
                effect_evidence,
                chronology,
                chronology_identity,
            )
        )

    return (
        tuple(selections),
        expected_pairs,
        attested_specification_ids,
    )


def candidate_pair_mapping(
    projection: CalibrationCandidatePairProjection,
) -> dict[str, object]:
    """Return the exact declaration-order mapping expected by the P1 decoder."""

    return {
        "adam_candidate_id": projection.adam_candidate_id,
        "comparison_group_id": projection.comparison_group_id,
        "replication_id": projection.replication_id,
        "schema_version": projection.schema_version,
        "sgd_candidate_id": projection.sgd_candidate_id,
        "world_id": projection.world_id,
    }


def strict_chronology_mapping(
    projection: StrictChronologyProjection,
) -> dict[str, object]:
    """Return the exact declaration-order mapping expected by the P1 decoder."""

    return {
        "current_effect_excluded": projection.current_effect_excluded,
        "current_observation_excluded": projection.current_observation_excluded,
        "effect_available_sequences": projection.effect_available_sequences,
        "future_history_excluded": projection.future_history_excluded,
        "schema_version": projection.schema_version,
        "source_sequence_cutoff": projection.source_sequence_cutoff,
    }


def expected_candidate_pair_id(
    projection: CalibrationCandidatePairProjection,
) -> str:
    """Calculate a carried pair ID from the test-owned frozen mapping."""

    return protocol_hash(CANDIDATE_PAIR_ID_DOMAIN, candidate_pair_mapping(projection))


def expected_strict_chronology_id(
    projection: StrictChronologyProjection,
) -> str:
    """Calculate a carried chronology ID from the test-owned frozen mapping."""

    return protocol_hash(STRICT_CHRONOLOGY_ID_DOMAIN, strict_chronology_mapping(projection))


def replace_selection_field(
    selection: SelectionEvidence,
    field_index: int,
    value: object,
) -> SelectionEvidence:
    """Return one selection with exactly one top-level tuple field replaced."""

    if not 0 <= field_index < len(SELECTION_FIELD_NAMES):
        raise IndexError("selection field index is outside the frozen 20-field tuple")
    return cast(
        SelectionEvidence,
        (*selection[:field_index], value, *selection[field_index + 1 :]),
    )


def replace_bundle_selection(
    selections: tuple[SelectionEvidence, ...],
    selection_index: int,
    selection: SelectionEvidence,
) -> tuple[SelectionEvidence, ...]:
    """Return a canonical selection tuple with one occurrence replaced."""

    if not 0 <= selection_index < len(selections):
        raise IndexError("selection index is outside the supplied bundle")
    return (
        *selections[:selection_index],
        selection,
        *selections[selection_index + 1 :],
    )


def mutate_selection(
    selections: tuple[SelectionEvidence, ...],
    selection_index: int,
    field_index: int,
    value: object,
) -> tuple[SelectionEvidence, ...]:
    """Replace one field of one selection without mutating shared fixtures."""

    changed = replace_selection_field(
        selections[selection_index],
        field_index,
        value,
    )
    return replace_bundle_selection(selections, selection_index, changed)


def replace_effect_evidence_field(
    effect_evidence: EffectEvidence,
    field_index: int,
    value: object,
) -> EffectEvidence:
    """Return one exact four-field effect wrapper with one value replaced."""

    if not 0 <= field_index < len(EFFECT_EVIDENCE_FIELD_NAMES):
        raise IndexError("effect-evidence field index is outside the four-field tuple")
    return cast(
        EffectEvidence,
        (
            *effect_evidence[:field_index],
            value,
            *effect_evidence[field_index + 1 :],
        ),
    )


def replace_effect_evidence_at(
    effect_evidence: tuple[EffectEvidence, ...],
    effect_index: int,
    replacement: EffectEvidence,
) -> tuple[EffectEvidence, ...]:
    """Return a five-effect tuple with one occurrence replaced."""

    if not 0 <= effect_index < len(effect_evidence):
        raise IndexError("effect index is outside the supplied effect tuple")
    return (
        *effect_evidence[:effect_index],
        replacement,
        *effect_evidence[effect_index + 1 :],
    )


def replace_selector_result(
    selector_result: CalibrationHistorySelection,
    **changes: object,
) -> CalibrationHistorySelection:
    """Copy the frozen selector result while changing named test fields."""

    replace_call = cast(
        Callable[..., CalibrationHistorySelection],
        dataclass_replace,
    )
    return replace_call(selector_result, **changes)


def with_selector_result(
    selection: SelectionEvidence,
    selector_result: CalibrationHistorySelection,
) -> SelectionEvidence:
    """Return a selection carrying a replacement selector result."""

    return replace_selection_field(
        selection,
        SELECTOR_RESULT_INDEX,
        selector_result,
    )


def with_effect_evidence(
    selection: SelectionEvidence,
    effect_evidence: tuple[EffectEvidence, ...],
) -> SelectionEvidence:
    """Return a selection carrying replacement ordered source-effect wrappers."""

    return replace_selection_field(
        selection,
        ORDERED_SOURCE_EFFECTS_INDEX,
        effect_evidence,
    )


_CACHED_VALID_BUNDLE: Final[ValidBundle] = build_valid_bundle()


def valid_bundle() -> ValidBundle:
    """Return the safely reusable immutable canonical bundle."""

    return _CACHED_VALID_BUNDLE


def source_observation_mapping(
    projection: CalibrationSourceObservationProjection,
) -> dict[str, object]:
    return {
        "candidate_id": projection.candidate_id,
        "comparison_group_id": projection.comparison_group_id,
        "digest": projection.digest,
        "intervention_arm": projection.intervention_arm,
        "key_fields": projection.key_fields,
        "namespace": projection.namespace,
        "oracle_key_id": projection.oracle_key_id,
        "outcome_digest": projection.outcome_digest,
        "replication_id": projection.replication_id,
        "revealed_observation": projection.revealed_observation,
        "schema_version": projection.schema_version,
        "seed": projection.seed,
        "serialized_key_hex": projection.serialized_key_hex,
        "u": projection.u,
        "world_id": projection.world_id,
        "z": projection.z,
    }


def expected_source_observation_identity(
    projection: CalibrationSourceObservationProjection,
) -> str:
    return protocol_hash(
        SOURCE_OBSERVATION_ID_DOMAIN,
        source_observation_mapping(projection),
    )


def _build_p2_scope_fixture(selection: SelectionEvidence) -> _P2ScopeFixture:
    world_id = selection[WORLD_ID_INDEX]
    seed = selection[SEED_INDEX]
    comparison_group_id = selection[COMPARISON_GROUP_ID_INDEX]
    prefix_id = selection[CALIBRATION_PREFIX_ID_INDEX]
    ordered_candidate_pairs = selection[ORDERED_CANDIDATE_PAIRS_INDEX]
    ordered_replication_ids = selection[ORDERED_REPLICATION_IDS_INDEX]
    original_selector_result = selection[SELECTOR_RESULT_INDEX]
    world = WORLDS_BY_ID[world_id]
    group_index = GROUP_IDS.index(comparison_group_id)
    run_id = f"p2-harness/{world_id}/{seed}/{comparison_group_id}"

    observations: list[RevealedObservation] = []
    source_evidence: list[SourceObservationEvidence] = []
    oracle_key_ids: list[str] = []
    key_outcome_pairs: list[tuple[str, str]] = []
    effects = []
    effect_ids: list[str] = []
    effect_values: list[float] = []
    effect_evidence: list[EffectEvidence] = []

    for pair_index in range(5):
        pair_observations: list[RevealedObservation] = []
        replication_id = ordered_replication_ids[pair_index]
        candidate_pair = ordered_candidate_pairs[pair_index]
        for arm_index, intervention_arm in enumerate(P2_ARM_ORDER):
            candidate_id = candidate_pair[arm_index]
            key_fields = calibration_key(
                world_id=world_id,
                seed=seed,
                comparison_group_id=comparison_group_id,
                intervention_arm=intervention_arm,
                replication_id=replication_id,
                namespace=CALIBRATION_NAMESPACE,
            )
            transform = transform_key(key_fields)
            base_candidate_id = f"g{group_index:02d}-{intervention_arm}-r1"
            observed = hidden_arm_mean(world, base_candidate_id) + (
                hidden_observation_sigma(world, base_candidate_id) * transform.z
            )
            revealed_f64 = f64(observed)
            oracle_key_id = runtime_id(
                "oracle-key",
                "oracle_key_id/v1",
                {"key_fields": list(key_fields)},
            )
            outcome_digest = protocol_hash(
                "revealed_outcome/v1",
                {
                    "oracle_key_id": oracle_key_id,
                    "revealed_observation": revealed_f64,
                },
            )
            projection = CalibrationSourceObservationProjection(
                candidate_id=candidate_id,
                comparison_group_id=comparison_group_id,
                digest=transform.digest_hex,
                intervention_arm=intervention_arm,
                key_fields=key_fields,
                namespace=CALIBRATION_NAMESPACE,
                oracle_key_id=oracle_key_id,
                outcome_digest=outcome_digest,
                replication_id=replication_id,
                revealed_observation=revealed_f64,
                schema_version=SOURCE_OBSERVATION_SCHEMA,
                seed=seed,
                serialized_key_hex=transform.serialized_key.hex(),
                u=transform.u_string,
                world_id=world_id,
                z=transform.z_string,
            )
            source_identity = expected_source_observation_identity(projection)
            authorization_id = runtime_id(
                "authorization",
                "authorization_id/v1",
                {
                    "candidate_id": candidate_id,
                    "kind": "calibration",
                    "run_id": run_id,
                    "source_id": f"{prefix_id}/{candidate_id}",
                },
            )
            observation = RevealedObservation(
                oracle_key_id=oracle_key_id,
                oracle_use_id=f"oracle-use/{authorization_id}/{oracle_key_id}",
                authorization_id=authorization_id,
                namespace=CALIBRATION_NAMESPACE,
                world_id=world_id,
                seed=seed,
                candidate_id=candidate_id,
                comparison_group_id=comparison_group_id,
                intervention_arm=intervention_arm,
                replication_id=replication_id,
                key_fields=key_fields,
                serialized_key_hex=transform.serialized_key.hex(),
                digest=transform.digest_hex,
                u=transform.u_string,
                z=transform.z_string,
                revealed_observation=observed,
                outcome_digest=outcome_digest,
            )
            observations.append(observation)
            pair_observations.append(observation)
            source_evidence.append((projection, source_identity))
            oracle_key_ids.append(oracle_key_id)
            key_outcome_pairs.append((oracle_key_id, outcome_digest))

        observed_effect = round(
            pair_observations[0].revealed_observation - pair_observations[1].revealed_observation,
            12,
        )
        effect = expected_calibration_effect(
            prefix_id=prefix_id,
            world_id=world_id,
            comparison_group_id=comparison_group_id,
            group_index=group_index,
            replication_index=pair_index + 1,
            observed_effect=observed_effect,
        )
        payload_bytes = canonical_json_bytes(effect.to_dict(), final_lf=True)
        payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
        effects.append(effect)
        effect_ids.append(effect.effect_id)
        effect_values.append(effect.observed_effect)
        effect_evidence.append(
            (
                effect.effect_id,
                payload_bytes,
                payload_sha256,
                project_matched_effect(effect),
            )
        )

    selector_result = replace_selector_result(
        original_selector_result,
        source_effect_ids=tuple(effect_ids),
        source_effect_payload_sha256=tuple(
            item[EFFECT_PAYLOAD_SHA256_INDEX] for item in effect_evidence
        ),
        source_observation_identities=tuple(key_outcome_pairs),
        source_oracle_key_ids=tuple(oracle_key_ids),
        effect_values=tuple(effect_values),
        effects=tuple(effects),
        observations=tuple(observations),
    )
    return (
        selector_result,
        tuple(effect_ids),
        tuple(effect_evidence),
        tuple(source_evidence),
    )


def _oracle_predecessor(
    selection: SelectionEvidence,
) -> OraclePredecessor:
    world_id = selection[WORLD_ID_INDEX]
    seed = selection[SEED_INDEX]
    comparison_group_id = selection[COMPARISON_GROUP_ID_INDEX]
    coordinate = {
        "comparison_group_id": comparison_group_id,
        "position": selection[POSITION_INDEX],
        "role": selection[ROLE_INDEX],
        "seed": seed,
        "world_id": world_id,
    }
    oracle_execution_id = protocol_hash(
        "stage2f-p2-test-oracle-execution/v1",
        coordinate,
    )
    oracle_binding_id = protocol_hash(
        "stage2f-p2-test-oracle-binding/v1",
        {
            "oracle_execution_id": oracle_execution_id,
            **coordinate,
        },
    )
    return (
        oracle_execution_id,
        oracle_binding_id,
        (ORACLE_VERSION, _test_h64("stage2f-p2-test-oracle-implementation")),
        PROTOCOL_VERSION,
        CALIBRATION_NAMESPACE,
        world_id,
        seed,
        comparison_group_id,
        selection[ORDERED_CANDIDATE_PAIRS_INDEX],
        selection[ORDERED_REPLICATION_IDS_INDEX],
        WORLDS_BY_ID[world_id],
    )


def build_valid_p2_bundle() -> P2ValidBundle:
    """Build the immutable canonical 318-selection P2 Oracle-evidence bundle."""

    selections, expected_pairs, attested_specification_ids = _CACHED_VALID_BUNDLE
    p2_scopes: dict[tuple[str, int, str], _P2ScopeFixture] = {}
    p2_selections: list[P2SelectionEvidence] = []
    expected_predecessors: list[OraclePredecessor] = []
    upgraded_selections: list[SelectionEvidence] = []

    for selection in selections:
        scope_key = (
            selection[WORLD_ID_INDEX],
            selection[SEED_INDEX],
            selection[COMPARISON_GROUP_ID_INDEX],
        )
        scope = p2_scopes.get(scope_key)
        if scope is None:
            scope = _build_p2_scope_fixture(selection)
            p2_scopes[scope_key] = scope
        selector_result, effect_ids, effect_evidence, source_evidence = scope
        upgraded = with_effect_evidence(
            replace_selection_field(
                with_selector_result(selection, selector_result),
                ORDERED_SOURCE_EFFECT_IDS_INDEX,
                effect_ids,
            ),
            effect_evidence,
        )
        predecessor = _oracle_predecessor(upgraded)
        upgraded_selections.append(upgraded)
        p2_selections.append((predecessor, source_evidence))
        expected_predecessors.append(predecessor)

    return (
        tuple(upgraded_selections),
        expected_pairs,
        attested_specification_ids,
        tuple(p2_selections),
        tuple(expected_predecessors),
    )


def replace_p2_selection_field(
    p2_selection: P2SelectionEvidence,
    field_index: int,
    value: object,
) -> P2SelectionEvidence:
    if not 0 <= field_index < len(p2_selection):
        raise IndexError("P2 selection field index is outside the two-field tuple")
    return cast(
        P2SelectionEvidence,
        (*p2_selection[:field_index], value, *p2_selection[field_index + 1 :]),
    )


def replace_p2_selection(
    p2_selections: tuple[P2SelectionEvidence, ...],
    selection_index: int,
    replacement: P2SelectionEvidence,
) -> tuple[P2SelectionEvidence, ...]:
    if not 0 <= selection_index < len(p2_selections):
        raise IndexError("P2 selection index is outside the supplied bundle")
    return (
        *p2_selections[:selection_index],
        replacement,
        *p2_selections[selection_index + 1 :],
    )


def replace_oracle_predecessor_field(
    predecessor: OraclePredecessor,
    field_index: int,
    value: object,
) -> OraclePredecessor:
    if not 0 <= field_index < len(predecessor):
        raise IndexError("Oracle predecessor field index is outside the frozen tuple")
    return cast(
        OraclePredecessor,
        (*predecessor[:field_index], value, *predecessor[field_index + 1 :]),
    )


def replace_source_observation_field(
    projection: CalibrationSourceObservationProjection,
    field_name: str,
    value: object,
) -> CalibrationSourceObservationProjection:
    if field_name not in SOURCE_OBSERVATION_FIELD_NAMES:
        raise KeyError("unknown P2 source-observation field")
    replace_call = cast(
        Callable[..., CalibrationSourceObservationProjection],
        dataclass_replace,
    )
    return replace_call(projection, **{field_name: value})


def replace_source_evidence_at(
    source_evidence: tuple[SourceObservationEvidence, ...],
    observation_index: int,
    replacement: SourceObservationEvidence,
) -> tuple[SourceObservationEvidence, ...]:
    if not 0 <= observation_index < len(source_evidence):
        raise IndexError("source-observation index is outside the supplied tuple")
    return (
        *source_evidence[:observation_index],
        replacement,
        *source_evidence[observation_index + 1 :],
    )


def valid_p2_bundle() -> P2ValidBundle:
    return build_valid_p2_bundle()


def scientific_selection_mapping(
    projection: ScientificCalibrationSelectionProjection,
) -> dict[str, object]:
    """Return the independent test-owned 21-field selector preimage."""

    return {
        "comparison_group_id": projection.comparison_group_id,
        "ddof": projection.ddof,
        "effect_values": list(projection.effect_values),
        "eligibility_basis": projection.eligibility_basis,
        "estimated_sigma": projection.estimated_sigma,
        "namespace": projection.namespace,
        "sample_count": projection.sample_count,
        "sample_mean": projection.sample_mean,
        "sample_standard_deviation": projection.sample_standard_deviation,
        "seed": projection.seed,
        "sigma_floor": projection.sigma_floor,
        "source_candidate_pairs": [list(pair) for pair in projection.source_candidate_pairs],
        "source_effect_ids": list(projection.source_effect_ids),
        "source_effect_payload_sha256": list(projection.source_effect_payload_sha256),
        "source_observation_identities": [
            list(pair) for pair in projection.source_observation_identities
        ],
        "source_oracle_key_ids": list(projection.source_oracle_key_ids),
        "source_replication_ids": list(projection.source_replication_ids),
        "source_sequence_cutoff": projection.source_sequence_cutoff,
        "study_id": projection.study_id,
        "target_comparison_group_id": projection.target_comparison_group_id,
        "world_id": projection.world_id,
    }


def expected_selector_result_identity(
    projection: ScientificCalibrationSelectionProjection,
) -> str:
    """Hash the independent exact scientific projection through the frozen domain."""

    return protocol_hash(
        SCIENTIFIC_SELECTION_ID_DOMAIN,
        scientific_selection_mapping(projection),
    )


def _p3_physical_cost(world_id: str, group_index: int) -> float:
    costs = candidate_costs(WORLDS_BY_ID[world_id].public)
    return 5.0 * (costs[f"g{group_index:02d}-adam-r1"] + costs[f"g{group_index:02d}-sgd-r1"])


def _p3_observations(
    *,
    selection: SelectionEvidence,
    p2_selection: P2SelectionEvidence,
    run_id: str,
) -> tuple[
    tuple[RevealedObservation, ...],
    tuple[RunRevealedObservationProjection, ...],
]:
    world_id = selection[WORLD_ID_INDEX]
    seed = selection[SEED_INDEX]
    comparison_group_id = selection[COMPARISON_GROUP_ID_INDEX]
    prefix_id = selection[CALIBRATION_PREFIX_ID_INDEX]
    candidate_pairs = selection[ORDERED_CANDIDATE_PAIRS_INDEX]
    replication_ids = selection[ORDERED_REPLICATION_IDS_INDEX]
    source_evidence = p2_selection[P2_ORDERED_SOURCE_OBSERVATIONS_INDEX]
    world = WORLDS_BY_ID[world_id]
    group_index = GROUP_IDS.index(comparison_group_id)
    observations: list[RevealedObservation] = []
    returned_observations: list[RunRevealedObservationProjection] = []

    for observation_index in range(10):
        pair_index, arm_index = divmod(observation_index, 2)
        intervention_arm: Literal["adam", "sgd"] = "adam" if arm_index == 0 else "sgd"
        candidate_id = candidate_pairs[pair_index][arm_index]
        replication_id = replication_ids[pair_index]
        key_fields = calibration_key(
            world_id=world_id,
            seed=seed,
            comparison_group_id=comparison_group_id,
            intervention_arm=intervention_arm,
            replication_id=replication_id,
            namespace=CALIBRATION_NAMESPACE,
        )
        transform = transform_key(key_fields)
        base_candidate_id = f"g{group_index:02d}-{intervention_arm}-r1"
        revealed_observation = hidden_arm_mean(
            world,
            base_candidate_id,
        ) + (hidden_observation_sigma(world, base_candidate_id) * transform.z)
        revealed_f64 = f64(revealed_observation)
        oracle_key_id = runtime_id(
            "oracle-key",
            "oracle_key_id/v1",
            {"key_fields": list(key_fields)},
        )
        outcome_digest = protocol_hash(
            "revealed_outcome/v1",
            {
                "oracle_key_id": oracle_key_id,
                "revealed_observation": revealed_f64,
            },
        )
        source_projection = source_evidence[observation_index][0]
        expected_source_projection = CalibrationSourceObservationProjection(
            candidate_id=candidate_id,
            comparison_group_id=comparison_group_id,
            digest=transform.digest_hex,
            intervention_arm=intervention_arm,
            key_fields=key_fields,
            namespace=CALIBRATION_NAMESPACE,
            oracle_key_id=oracle_key_id,
            outcome_digest=outcome_digest,
            replication_id=replication_id,
            revealed_observation=revealed_f64,
            schema_version=SOURCE_OBSERVATION_SCHEMA,
            seed=seed,
            serialized_key_hex=transform.serialized_key.hex(),
            u=transform.u_string,
            world_id=world_id,
            z=transform.z_string,
        )
        if source_projection != expected_source_projection or source_evidence[observation_index][
            1
        ] != expected_source_observation_identity(expected_source_projection):
            raise AssertionError(
                "validated P2 source observation differs from the independent P3 fixture"
            )

        source_id = f"{prefix_id}/{candidate_id}"
        authorization_id = runtime_id(
            "authorization",
            "authorization_id/v1",
            {
                "candidate_id": candidate_id,
                "kind": "calibration",
                "run_id": run_id,
                "source_id": source_id,
            },
        )
        oracle_use_id = f"oracle-use/{authorization_id}/{oracle_key_id}"
        authorization = RunObservationAuthorizationProjection(
            candidate_id=candidate_id,
            kind="calibration",
            run_id=run_id,
            source_id=source_id,
        )
        observation = RevealedObservation(
            oracle_key_id=oracle_key_id,
            oracle_use_id=oracle_use_id,
            authorization_id=authorization_id,
            namespace=CALIBRATION_NAMESPACE,
            world_id=world_id,
            seed=seed,
            candidate_id=candidate_id,
            comparison_group_id=comparison_group_id,
            intervention_arm=intervention_arm,
            replication_id=replication_id,
            key_fields=key_fields,
            serialized_key_hex=transform.serialized_key.hex(),
            digest=transform.digest_hex,
            u=transform.u_string,
            z=transform.z_string,
            revealed_observation=revealed_observation,
            outcome_digest=outcome_digest,
        )
        observations.append(observation)
        returned_observations.append(
            RunRevealedObservationProjection(
                authorization=authorization,
                authorization_id=authorization_id,
                candidate_id=candidate_id,
                comparison_group_id=comparison_group_id,
                digest=transform.digest_hex,
                intervention_arm=intervention_arm,
                key_fields=key_fields,
                namespace=CALIBRATION_NAMESPACE,
                oracle_key_id=oracle_key_id,
                oracle_use_id=oracle_use_id,
                outcome_digest=outcome_digest,
                replication_id=replication_id,
                revealed_observation=revealed_f64,
                seed=seed,
                serialized_key_hex=transform.serialized_key.hex(),
                u=transform.u_string,
                world_id=world_id,
                z=transform.z_string,
            )
        )

    return tuple(observations), tuple(returned_observations)


def _p3_group_fixture(
    *,
    selection: SelectionEvidence,
    p2_selection: P2SelectionEvidence,
    run_id: str,
    lineage_id: str,
) -> _P3GroupFixture:
    world_id = selection[WORLD_ID_INDEX]
    seed = selection[SEED_INDEX]
    comparison_group_id = selection[COMPARISON_GROUP_ID_INDEX]
    prefix_id = selection[CALIBRATION_PREFIX_ID_INDEX]
    group_index = GROUP_IDS.index(comparison_group_id)
    observations, returned_observations = _p3_observations(
        selection=selection,
        p2_selection=p2_selection,
        run_id=run_id,
    )
    effects: list[MatchedEffectObservation] = []
    effect_projections: list[RunMatchedEffectProjection] = []
    payload_digests: list[str] = []

    for replication_index in REPLICATION_RANKS:
        observation_offset = 2 * (replication_index - 1)
        observed_effect = round(
            observations[observation_offset].revealed_observation
            - observations[observation_offset + 1].revealed_observation,
            12,
        )
        effect = expected_calibration_effect(
            prefix_id=prefix_id,
            world_id=world_id,
            comparison_group_id=comparison_group_id,
            group_index=group_index,
            replication_index=replication_index,
            observed_effect=observed_effect,
        )
        payload = canonical_json_bytes(effect.to_dict(), final_lf=True)
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        effect_projection = project_matched_effect(effect)
        p1_effect = selection[ORDERED_SOURCE_EFFECTS_INDEX][replication_index - 1]
        if (
            p1_effect[EFFECT_ID_INDEX] != effect.effect_id
            or p1_effect[EFFECT_PAYLOAD_BYTES_INDEX] != payload
            or p1_effect[EFFECT_PAYLOAD_SHA256_INDEX] != payload_sha256
            or p1_effect[EFFECT_PROJECTION_INDEX] != effect_projection
        ):
            raise AssertionError("validated P1 effect differs from the independent P3 fixture")
        effects.append(effect)
        effect_projections.append(effect_projection)
        payload_digests.append(payload_sha256)

    effect_tuple = tuple(effects)
    effect_values = tuple(effect.observed_effect for effect in effect_tuple)
    sample_mean = statistics.mean(effect_values)
    sample_standard_deviation = statistics.stdev(effect_values)
    estimated_sigma = max(sample_standard_deviation, SIGMA_FLOOR)
    physical_cost = _p3_physical_cost(world_id, group_index)
    source_effect_ids = tuple(effect.effect_id for effect in effect_tuple)
    source_observation_identities = tuple(
        (observation.oracle_key_id, observation.outcome_digest) for observation in observations
    )
    source_oracle_key_ids = tuple(observation.oracle_key_id for observation in observations)
    scientific_projection = ScientificCalibrationSelectionProjection(
        comparison_group_id=comparison_group_id,
        ddof=CALIBRATION_SIGMA_DDOF,
        effect_values=tuple(f64(value) for value in effect_values),
        eligibility_basis=CALIBRATION_ELIGIBILITY_BASIS,
        estimated_sigma=f64(estimated_sigma),
        namespace=CALIBRATION_NAMESPACE,
        sample_count=len(effect_tuple),
        sample_mean=f64(sample_mean),
        sample_standard_deviation=f64(sample_standard_deviation),
        seed=seed,
        sigma_floor=f64(SIGMA_FLOOR),
        source_candidate_pairs=selection[ORDERED_CANDIDATE_PAIRS_INDEX],
        source_effect_ids=source_effect_ids,
        source_effect_payload_sha256=tuple(payload_digests),
        source_observation_identities=source_observation_identities,
        source_oracle_key_ids=source_oracle_key_ids,
        source_replication_ids=selection[ORDERED_REPLICATION_IDS_INDEX],
        source_sequence_cutoff=CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
        study_id=PROTOCOL_VERSION,
        target_comparison_group_id=comparison_group_id,
        world_id=world_id,
    )
    selector_result_identity = expected_selector_result_identity(scientific_projection)
    historical_selection = CalibrationHistorySelection(
        study_id=PROTOCOL_VERSION,
        world_id=world_id,
        seed=seed,
        namespace=CALIBRATION_NAMESPACE,
        comparison_group_id=comparison_group_id,
        target_comparison_group_id=comparison_group_id,
        source_sequence_cutoff=CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
        source_effect_ids=source_effect_ids,
        source_effect_payload_sha256=tuple(payload_digests),
        source_observation_identities=source_observation_identities,
        source_oracle_key_ids=source_oracle_key_ids,
        source_candidate_pairs=selection[ORDERED_CANDIDATE_PAIRS_INDEX],
        source_replication_ids=selection[ORDERED_REPLICATION_IDS_INDEX],
        effect_values=effect_values,
        sample_count=len(effect_tuple),
        sample_mean=sample_mean,
        sample_standard_deviation=sample_standard_deviation,
        ddof=CALIBRATION_SIGMA_DDOF,
        sigma_floor=SIGMA_FLOOR,
        estimated_sigma=estimated_sigma,
        physical_cost=physical_cost,
        eligibility_basis=CALIBRATION_ELIGIBILITY_BASIS,
        current_observation_excluded=True,
        current_effect_excluded=True,
        future_history_excluded=True,
        effects=effect_tuple,
        observations=observations,
        selection_identity=selector_result_identity,
    )
    estimate = RunCalibrationEstimateProjection(
        belief_model_id=P3_WITNESS_ARM[2],
        calibration_prefix_id=prefix_id,
        comparison_group_id=comparison_group_id,
        ddof=CALIBRATION_SIGMA_DDOF,
        effects=tuple(effect_projections),
        estimated_sigma=f64(estimated_sigma),
        lineage_id=lineage_id,
        observations=returned_observations,
        physical_cost=f64(physical_cost),
        provenance_sha256=_test_h64(f"p3-estimate-provenance/{run_id}/{comparison_group_id}"),
        raw_sample_standard_deviation=f64(sample_standard_deviation),
        sample_count=len(effect_tuple),
        sample_mean=f64(sample_mean),
        sigma_estimate_id=f"sigma-estimate/{run_id}/{comparison_group_id}",
        sigma_floor=f64(SIGMA_FLOOR),
        source_effect_ids=source_effect_ids,
        source_sequence_cutoff=CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
    )
    return historical_selection, scientific_projection, estimate


def _p3_lineage(
    *,
    run_id: str,
    lineage_id: str,
) -> RunLineageProjection:
    hypothesis_ids = ("hypothesis-adam", "hypothesis-null", "hypothesis-sgd")
    probabilities = (0.34, 0.33, 0.33)
    state = RunBeliefStateProjection(
        belief_state_id=f"belief-state/{run_id}/initial",
        created_at="2000-01-01T00:00:00.000000Z#p3-fixture",
        evidence_ids=(),
        hypothesis_ids=hypothesis_ids,
        parent_belief_state_id=None,
        posterior_probabilities=tuple(f64(value) for value in probabilities),
        prior_probabilities=tuple(f64(value) for value in probabilities),
        sequence=0,
    )
    current_state = RunModelBeliefStateProjection(
        belief_model_id=P3_WITNESS_ARM[2],
        belief_model_version="replicated-noise-calibrated-gaussian/v1",
        lineage_id=lineage_id,
        state=state,
    )
    return RunLineageProjection(
        belief_model_id=P3_WITNESS_ARM[2],
        belief_model_version="replicated-noise-calibrated-gaussian/v1",
        created_at="2000-01-01T00:00:00.000000Z#p3-fixture",
        current_state=current_state,
        lineage_id=lineage_id,
        lineage_key=f"lineage-key/{run_id}",
    )


def _p3_witness_fixture(
    *,
    selections: tuple[SelectionEvidence, SelectionEvidence, SelectionEvidence],
    p2_selections: tuple[
        P2SelectionEvidence,
        P2SelectionEvidence,
        P2SelectionEvidence,
    ],
) -> _P3WitnessFixture:
    role = cast(ExecutionRole, selections[0][ROLE_INDEX])
    world_id = selections[0][WORLD_ID_INDEX]
    seed = selections[0][SEED_INDEX]
    if (
        tuple(selection[ROLE_INDEX] for selection in selections) != (role, role, role)
        or tuple(selection[WORLD_ID_INDEX] for selection in selections)
        != (world_id, world_id, world_id)
        or tuple(selection[SEED_INDEX] for selection in selections) != (seed, seed, seed)
        or tuple(selection[COMPARISON_GROUP_ID_INDEX] for selection in selections) != GROUP_IDS
    ):
        raise AssertionError("P3 witness fixture did not receive one canonical group triple")

    run_id = f"p3-witness/{role}/{world_id}/{seed}"
    lineage_id = f"lineage/{run_id}"
    group_fixtures = cast(
        tuple[_P3GroupFixture, _P3GroupFixture, _P3GroupFixture],
        tuple(
            _p3_group_fixture(
                selection=selections[group_index],
                p2_selection=p2_selections[group_index],
                run_id=run_id,
                lineage_id=lineage_id,
            )
            for group_index in range(3)
        ),
    )
    estimates = tuple(group_fixture[2] for group_fixture in group_fixtures)
    calibration_effects = tuple(effect for estimate in estimates for effect in estimate.effects)
    calibration_observations = tuple(
        observation for estimate in estimates for observation in estimate.observations
    )
    calibration_cost = math.fsum(
        _p3_physical_cost(world_id, group_index) for group_index in range(3)
    )
    calibration = RunCalibrationProjection(
        cost=f64(calibration_cost),
        effects=calibration_effects,
        estimates=estimates,
        observations=calibration_observations,
    )
    initial_probabilities = (
        ("hypothesis-adam", f64(0.34)),
        ("hypothesis-null", f64(0.33)),
        ("hypothesis-sgd", f64(0.33)),
    )
    returned_run = ReturnedRunProjection(
        actions=(),
        arm=P3_WITNESS_ARM,
        budget=P3_WITNESS_BUDGET,
        budget_id=P3_WITNESS_BUDGET_ID,
        calibration=calibration,
        calibration_cost=f64(calibration_cost),
        comparison_id=_test_h64(f"p3-comparison/{role}/{world_id}/{seed}"),
        completed_experiments=(),
        decision_cost=f64(0.0),
        decisions=(),
        diagnostics=(),
        effect_history=calibration_effects,
        evidence=(),
        initial_probabilities=initial_probabilities,
        lineage=_p3_lineage(run_id=run_id, lineage_id=lineage_id),
        run_id=run_id,
        run_status="complete",
        schema_version=P3_RETURNED_RUN_SCHEMA,
        seed=seed,
        terminal_reason="p3_fixture_complete",
        updates=(),
        world_id=world_id,
    )
    submitted_job_id = protocol_hash(
        "stage2f-p3-test-submitted-job/v1",
        {
            "arm_id": P3_WITNESS_ARM[0],
            "arm_order": P3_WITNESS_ARM[1],
            "budget": P3_WITNESS_BUDGET,
            "budget_id": P3_WITNESS_BUDGET_ID,
            "role": role,
            "seed": seed,
            "world_id": world_id,
        },
    )
    returned_result_id = protocol_hash(
        "stage2f-p3-test-returned-result/v1",
        {
            "role": role,
            "run_id": run_id,
            "submitted_job_id": submitted_job_id,
        },
    )
    return (
        returned_result_id,
        returned_run,
        submitted_job_id,
        group_fixtures,
    )


def _p3_implementation() -> ImplementationProjection:
    return ImplementationProjection(
        dependency_lock_sha256=_test_h64("p3-fixture/dependency-lock"),
        implementation_commit="5" * 40,
        implementation_diff_sha256=_test_h64("p3-fixture/implementation-diff"),
        implementation_tree_sha256=_test_h64("p3-fixture/implementation-tree"),
        source_bundle_sha256=_test_h64("p3-fixture/source-bundle"),
        test_bundle_sha256=_test_h64("p3-fixture/test-bundle"),
    )


def _p3_runtime(role: ExecutionRole) -> RuntimeProjection:
    executable = FileProjection(
        byte_count=1,
        path=f"p3-fixture/{role}/python.exe",
        sha256=_test_h64(f"p3-fixture/{role}/python"),
    )
    interpreter_identity = InterpreterIdentityProjection(
        cache_tag="cpython-312",
        compiler="p3-fixture",
        executable_path=executable.path,
        executable_sha256=executable.sha256,
        implementation="CPython",
        python_version="3.12.0",
    )
    platform_identity = PlatformIdentityProjection(
        machine="AMD64",
        platform="p3-fixture",
        release="p3-fixture",
        system="Windows",
        version="p3-fixture",
    )
    return RuntimeProjection(
        base_interpreter=executable,
        interpreter=executable,
        interpreter_identity=interpreter_identity,
        interpreter_identity_sha256=_test_h64(f"p3-fixture/{role}/interpreter-identity"),
        platform_identity=platform_identity,
        platform_identity_sha256=_test_h64(f"p3-fixture/{role}/platform-identity"),
        python_build_date="2000-01-01",
        python_build_number="p3-fixture",
    )


def _p3_returned_results(
    *,
    role: ExecutionRole,
    execution_specification_id: str,
    rows: tuple[P3ReturnedResultRow, ...],
) -> ReturnedResultsProjection:
    role_execution_id = _test_h64(f"p3-fixture/{role}/execution")
    return ReturnedResultsProjection(
        execution_completion_id=_test_h64(f"p3-fixture/{role}/execution-completion"),
        execution_id=role_execution_id,
        execution_specification_id=execution_specification_id,
        execution_status="success",
        implementation=_p3_implementation(),
        job_result_mapping=tuple(
            (submitted_job_id, returned_result_id)
            for returned_result_id, _projection, submitted_job_id in rows
        ),
        oracle_binding_id=_test_h64(f"p3-fixture/{role}/oracle-binding"),
        oracle_execution_id=_test_h64(f"p3-fixture/{role}/oracle-execution"),
        protocol_checkpoint=PROTOCOL_CHECKPOINT,
        results_in_submission_order=rows,
        runtime=_p3_runtime(role),
        runtime_identity=_test_h64(f"p3-fixture/{role}/runtime-identity"),
        schema_version=P3_RETURNED_RESULTS_SCHEMA,
        study_id=PROTOCOL_VERSION,
        validation_authority_id=_test_h64(f"p3-fixture/{role}/validation-authority"),
        validation_run_id=f"p3-validation-run/{role}",
    )


def build_valid_p3_bundle() -> P3ValidBundle:
    """Build a fresh canonical P3 bundle without replay or live capabilities."""

    (
        p2_selections_input,
        expected_pairs,
        attested_specification_ids,
        p2_selections,
        expected_predecessors,
    ) = build_valid_p2_bundle()
    role_rows: list[list[P3ReturnedResultRow]] = [[], [], [], []]
    witnesses: dict[tuple[str, str, int], _P3WitnessFixture] = {}

    for selection_index in range(0, CANONICAL_SELECTION_COUNT, 3):
        group_selections = cast(
            tuple[SelectionEvidence, SelectionEvidence, SelectionEvidence],
            p2_selections_input[selection_index : selection_index + 3],
        )
        group_p2_selections = cast(
            tuple[
                P2SelectionEvidence,
                P2SelectionEvidence,
                P2SelectionEvidence,
            ],
            p2_selections[selection_index : selection_index + 3],
        )
        witness = _p3_witness_fixture(
            selections=group_selections,
            p2_selections=group_p2_selections,
        )
        role = group_selections[0][ROLE_INDEX]
        world_id = group_selections[0][WORLD_ID_INDEX]
        seed = group_selections[0][SEED_INDEX]
        role_index = ROLE_ORDER.index(cast(ExecutionRole, role))
        witness_key = (role, world_id, seed)
        if witness_key in witnesses:
            raise AssertionError("P3 witness coordinate is duplicated")
        witnesses[witness_key] = witness
        role_rows[role_index].append((witness[0], witness[1], witness[2]))

    returned_results_by_role = cast(
        ReturnedResultsByRole,
        tuple(
            _p3_returned_results(
                role=role,
                execution_specification_id=expected_pairs[role_index][0],
                rows=tuple(role_rows[role_index]),
            )
            for role_index, role in enumerate(ROLE_ORDER)
        ),
    )
    if (
        sum(len(aggregate.results_in_submission_order) for aggregate in returned_results_by_role)
        != 106
    ):
        raise AssertionError("P3 fixture must contain exactly 106 role-owned witness rows")

    selections: list[SelectionEvidence] = []
    p3_inputs: list[_P3SelectionInput] = []
    for selection_index in range(CANONICAL_SELECTION_COUNT):
        selection = p2_selections_input[selection_index]
        role = selection[ROLE_INDEX]
        world_id = selection[WORLD_ID_INDEX]
        seed = selection[SEED_INDEX]
        comparison_group_id = selection[COMPARISON_GROUP_ID_INDEX]
        group_index = GROUP_IDS.index(comparison_group_id)
        witness = witnesses[(role, world_id, seed)]
        historical_selection, scientific_projection, _estimate = witness[3][group_index]
        selections.append(with_selector_result(selection, historical_selection))
        p3_inputs.append(
            _P3SelectionInput(
                returned_result_id=witness[0],
                returned_run_projection=witness[1],
                submitted_job_id=witness[2],
                selector_result_projection=scientific_projection,
                selector_result_identity=expected_selector_result_identity(scientific_projection),
            )
        )

    return (
        tuple(selections),
        expected_pairs,
        attested_specification_ids,
        p2_selections,
        expected_predecessors,
        returned_results_by_role,
        tuple(p3_inputs),
    )


def replace_scientific_selection_projection(
    projection: ScientificCalibrationSelectionProjection,
    **changes: object,
) -> ScientificCalibrationSelectionProjection:
    unknown = tuple(
        field_name
        for field_name in changes
        if field_name not in scientific_selection_mapping(projection)
    )
    if unknown:
        raise KeyError(f"unknown scientific selection field: {unknown[0]}")
    replace_call = cast(
        Callable[..., ScientificCalibrationSelectionProjection],
        dataclass_replace,
    )
    return replace_call(projection, **changes)


def replace_p3_input_at(
    p3_inputs: tuple[_P3SelectionInput, ...],
    selection_index: int,
    replacement: _P3SelectionInput,
) -> tuple[_P3SelectionInput, ...]:
    if not 0 <= selection_index < len(p3_inputs):
        raise IndexError("P3 selection index is outside the supplied tuple")
    return (
        *p3_inputs[:selection_index],
        replacement,
        *p3_inputs[selection_index + 1 :],
    )


def replace_returned_result_row(
    aggregate: ReturnedResultsProjection,
    row_index: int,
    replacement: P3ReturnedResultRow,
) -> ReturnedResultsProjection:
    rows = aggregate.results_in_submission_order
    if not 0 <= row_index < len(rows):
        raise IndexError("returned-result row index is outside the role aggregate")
    replacement_rows = (
        *rows[:row_index],
        replacement,
        *rows[row_index + 1 :],
    )
    replace_call = cast(
        Callable[..., ReturnedResultsProjection],
        dataclass_replace,
    )
    return replace_call(
        aggregate,
        results_in_submission_order=replacement_rows,
        job_result_mapping=tuple(
            (submitted_job_id, returned_result_id)
            for returned_result_id, _projection, submitted_job_id in replacement_rows
        ),
    )


def replace_returned_results_role(
    returned_results_by_role: ReturnedResultsByRole,
    role_index: int,
    replacement: ReturnedResultsProjection,
) -> ReturnedResultsByRole:
    if not 0 <= role_index < len(returned_results_by_role):
        raise IndexError("returned-results role index is outside the four-role tuple")
    return cast(
        ReturnedResultsByRole,
        (
            *returned_results_by_role[:role_index],
            replacement,
            *returned_results_by_role[role_index + 1 :],
        ),
    )
