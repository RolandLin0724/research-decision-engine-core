"""Capability-free replay of the frozen calibration-history selection.

The caller supplies observations reconstructed through the pure S6 formula and
the already admitted frozen group context.  This module performs only the pure
history validation and identity construction used by S10.9; it issues no Oracle
authority and consults no live registry.
"""

from __future__ import annotations

import hashlib
import statistics
from typing import TYPE_CHECKING

from research_decision_engine.belief_models import SIGMA_FLOOR, MatchedEffectObservation
from research_decision_engine.benchmarks.broader_calibration_history import (
    CALIBRATION_ELIGIBILITY_BASIS,
    CALIBRATION_SELECTION_VERSION,
    CALIBRATION_SIGMA_DDOF,
    CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
    CalibrationHistorySelection,
    RunProvenanceError,
    _validate_effects,
    _validate_observations,
)
from research_decision_engine.benchmarks.broader_oracle import CALIBRATION_NAMESPACE
from research_decision_engine.benchmarks.broader_protocol import (
    PROTOCOL_VERSION,
    canonical_json_bytes,
    f64,
    protocol_hash,
)

if TYPE_CHECKING:
    from research_decision_engine.benchmarks.broader_oracle import RevealedObservation


def raw_effect_sha256(effect: MatchedEffectObservation) -> str:
    """Return the selector's exact raw digest of one canonical effect payload."""

    return hashlib.sha256(canonical_json_bytes(effect.to_dict(), final_lf=True)).hexdigest()


def replay_calibration_history_selection(
    *,
    run_id: str,
    world_id: str,
    seed: int,
    comparison_group_id: str,
    group_index: int,
    expected_observations: tuple[RevealedObservation, ...],
    expected_effects: tuple[MatchedEffectObservation, ...],
    physical_cost: float,
    recorded_observations: tuple[RevealedObservation, ...] | None = None,
    recorded_effects: tuple[MatchedEffectObservation, ...] | None = None,
    source_sequence_cutoff: int = CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
) -> CalibrationHistorySelection:
    """Replay the pure selector tail from reconstructed immutable inputs.

    Frozen world/group admission and pure S6 observation reconstruction precede
    this call.  The remaining validation, canonical ordering, raw effect digests,
    and selection identity are byte-for-byte equivalents of the production
    selector and deliberately omit run-local authority from the result.
    """

    if source_sequence_cutoff != CALIBRATION_SOURCE_SEQUENCE_CUTOFF:
        raise RunProvenanceError(
            "Calibration history cutoff differs from the frozen sequence boundary.",
            error_code="CALIBRATION_CUTOFF_MISMATCH",
            validation_layer="calibration_history_selector",
        )
    if not run_id.strip():
        raise RunProvenanceError(
            "Calibration run identity is empty.",
            error_code="CALIBRATION_STUDY_BINDING_MISMATCH",
            validation_layer="calibration_history_selector",
        )

    observations = _validate_observations(expected_observations, recorded_observations)
    effects = _validate_effects(
        expected_effects,
        recorded_effects,
        comparison_group_id=comparison_group_id,
        source_sequence_cutoff=source_sequence_cutoff,
    )
    candidate_pairs = tuple(
        (
            f"cal-{group_index:02d}-adam-r{replication_index:04d}",
            f"cal-{group_index:02d}-sgd-r{replication_index:04d}",
        )
        for replication_index in range(1, 6)
    )
    replication_ids = tuple(
        f"calibration-{group_index:02d}-r{replication_index:04d}"
        for replication_index in range(1, 6)
    )
    values = tuple(item.observed_effect for item in effects)
    sample_mean = statistics.mean(values)
    sample_sd = statistics.stdev(values)
    effect_payloads = tuple(raw_effect_sha256(item) for item in effects)
    observation_identities = tuple(
        (item.oracle_key_id, item.outcome_digest) for item in observations
    )
    identity_values = {
        "study_id": PROTOCOL_VERSION,
        "world_id": world_id,
        "seed": seed,
        "namespace": CALIBRATION_NAMESPACE,
        "comparison_group_id": comparison_group_id,
        "target_comparison_group_id": comparison_group_id,
        "source_sequence_cutoff": source_sequence_cutoff,
        "source_effect_ids": [item.effect_id for item in effects],
        "source_effect_payload_sha256": list(effect_payloads),
        "source_observation_identities": [list(item) for item in observation_identities],
        "source_oracle_key_ids": [item.oracle_key_id for item in observations],
        "source_candidate_pairs": [list(item) for item in candidate_pairs],
        "source_replication_ids": list(replication_ids),
        "effect_values": [f64(item) for item in values],
        "sample_count": len(effects),
        "sample_mean": f64(sample_mean),
        "sample_standard_deviation": f64(sample_sd),
        "ddof": CALIBRATION_SIGMA_DDOF,
        "sigma_floor": f64(SIGMA_FLOOR),
        "estimated_sigma": f64(max(sample_sd, SIGMA_FLOOR)),
        "eligibility_basis": CALIBRATION_ELIGIBILITY_BASIS,
    }
    return CalibrationHistorySelection(
        study_id=PROTOCOL_VERSION,
        world_id=world_id,
        seed=seed,
        namespace=CALIBRATION_NAMESPACE,
        comparison_group_id=comparison_group_id,
        target_comparison_group_id=comparison_group_id,
        source_sequence_cutoff=source_sequence_cutoff,
        source_effect_ids=tuple(item.effect_id for item in effects),
        source_effect_payload_sha256=effect_payloads,
        source_observation_identities=observation_identities,
        source_oracle_key_ids=tuple(item.oracle_key_id for item in observations),
        source_candidate_pairs=candidate_pairs,
        source_replication_ids=replication_ids,
        effect_values=values,
        sample_count=len(effects),
        sample_mean=sample_mean,
        sample_standard_deviation=sample_sd,
        ddof=CALIBRATION_SIGMA_DDOF,
        sigma_floor=SIGMA_FLOOR,
        estimated_sigma=max(sample_sd, SIGMA_FLOOR),
        physical_cost=physical_cost,
        eligibility_basis=CALIBRATION_ELIGIBILITY_BASIS,
        current_observation_excluded=True,
        current_effect_excluded=True,
        future_history_excluded=True,
        effects=effects,
        observations=observations,
        selection_identity=protocol_hash(CALIBRATION_SELECTION_VERSION, identity_values),
    )
