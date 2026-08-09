"""Authoritative calibrated-sigma source-history selection.

This module owns the one benchmark-layer selector that turns the frozen Oracle
population and an optional persisted history into the exact five matched effects
permitted to cross the calibrated-sigma boundary.  Protected scientific code may
still perform its frozen local ordering, but it receives only this validated,
canonical population from benchmark orchestration.
"""

from __future__ import annotations

import hashlib
import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from research_decision_engine.belief_models import SIGMA_FLOOR, MatchedEffectObservation
from research_decision_engine.benchmarks.broader_oracle import (
    CALIBRATION_NAMESPACE,
    OracleError,
    RevealedObservation,
    authorize_observation,
    reobserve_authorized_observation,
)
from research_decision_engine.benchmarks.broader_protocol import (
    PROTOCOL_VERSION,
    canonical_json_bytes,
    f64,
    protocol_hash,
)
from research_decision_engine.benchmarks.broader_worlds import (
    GROUP_IDS,
    WORLDS_BY_ID,
    candidate_costs,
)
from research_decision_engine.reasoning import Provenance

CALIBRATION_SOURCE_SEQUENCE_CUTOFF: Final = 1
CALIBRATION_SIGMA_DDOF: Final = 1
CALIBRATION_SELECTION_VERSION: Final = "broader-calibration-history-selection/v1"
CALIBRATION_ELIGIBILITY_BASIS: Final = (
    "exact frozen calibration namespace, world, seed, public comparison group, "
    "adam/sgd candidate pair, common replication, and availability sequence < 1"
)


class RunProvenanceError(ValueError):
    """Fail-closed benchmark provenance error with a stable validation boundary."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "RUN_PROVENANCE_INVALID",
        validation_layer: str = "runner_provenance",
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.validation_layer = validation_layer
        self.scoring_entered = False
        self.scientific_output_entered = False


@dataclass(frozen=True, slots=True)
class CalibrationHistorySelection:
    """Immutable exact five-effect result returned by the sole selector."""

    study_id: str
    world_id: str
    seed: int
    namespace: str
    comparison_group_id: str
    target_comparison_group_id: str
    source_sequence_cutoff: int
    source_effect_ids: tuple[str, ...]
    source_effect_payload_sha256: tuple[str, ...]
    source_observation_identities: tuple[tuple[str, str], ...]
    source_oracle_key_ids: tuple[str, ...]
    source_candidate_pairs: tuple[tuple[str, str], ...]
    source_replication_ids: tuple[str, ...]
    effect_values: tuple[float, ...]
    sample_count: int
    sample_mean: float
    sample_standard_deviation: float
    ddof: int
    sigma_floor: float
    estimated_sigma: float
    physical_cost: float
    eligibility_basis: str
    current_observation_excluded: bool
    current_effect_excluded: bool
    future_history_excluded: bool
    effects: tuple[MatchedEffectObservation, ...]
    observations: tuple[RevealedObservation, ...]
    selection_identity: str

    def scientific_identity(self) -> tuple[object, ...]:
        """Run-independent identity consumed by reconstruction and projection."""

        return (
            self.study_id,
            self.world_id,
            self.seed,
            self.namespace,
            self.comparison_group_id,
            self.target_comparison_group_id,
            self.source_sequence_cutoff,
            self.source_effect_ids,
            self.source_effect_payload_sha256,
            self.source_observation_identities,
            self.source_oracle_key_ids,
            self.source_candidate_pairs,
            self.source_replication_ids,
            self.effect_values,
            self.sample_count,
            self.sample_mean,
            self.sample_standard_deviation,
            self.ddof,
            self.sigma_floor,
            self.estimated_sigma,
            self.physical_cost,
            self.eligibility_basis,
            self.selection_identity,
        )


def expected_calibration_effect(
    *,
    prefix_id: str,
    world_id: str,
    comparison_group_id: str,
    group_index: int,
    replication_index: int,
    observed_effect: float,
) -> MatchedEffectObservation:
    """Reconstruct one frozen calibration effect from its public sources."""

    replication_id = f"calibration-{group_index:02d}-r{replication_index:04d}"
    return MatchedEffectObservation(
        effect_id=f"calibration-effect/{prefix_id}/{replication_id}",
        comparison_group_id=comparison_group_id,
        observed_effect=observed_effect,
        available_sequence=0,
        source_kind="calibration",
        source_ids=(
            f"cal-{group_index:02d}-adam-r{replication_index:04d}",
            f"cal-{group_index:02d}-sgd-r{replication_index:04d}",
        ),
        created_at=f"2000-01-01T00:00:00.000000Z#calibration:{group_index}:{replication_index}",
        provenance=Provenance.create(
            method="broader-replication-calibration-effect",
            version="broader-calibration-effect/v1",
            details={
                "comparison_group_id": comparison_group_id,
                "replication_id": replication_id,
                "scientific_evidence": False,
                "world_id": world_id,
            },
        ),
    )


def select_calibration_history(
    *,
    run_id: str,
    world_id: str,
    seed: int,
    comparison_group_id: str,
    recorded_observations: Sequence[RevealedObservation] | None = None,
    recorded_effects: Sequence[MatchedEffectObservation] | None = None,
    source_sequence_cutoff: int = CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
) -> CalibrationHistorySelection:
    """Return the exact canonical five-effect prefix or reject before scoring.

    Persisted ordering never assigns eligibility.  Expected candidate pairs and
    replication ranks come from the frozen registries, observations are regenerated
    through the Oracle, and relevant persisted objects must match those regenerated
    objects exactly.  Later/current effects and effects from other groups cannot enter
    the result; an additional pre-cutoff target-group effect is rejected as ambiguous.
    """

    if source_sequence_cutoff != CALIBRATION_SOURCE_SEQUENCE_CUTOFF:
        _fail(
            "CALIBRATION_CUTOFF_MISMATCH",
            "Calibration history cutoff differs from the frozen sequence boundary.",
        )
    try:
        group_index = GROUP_IDS.index(comparison_group_id)
        world = WORLDS_BY_ID[world_id].public
    except (KeyError, ValueError) as error:
        raise RunProvenanceError(
            "Calibration source world or group is not frozen.",
            error_code="CALIBRATION_SCOPE_MISMATCH",
            validation_layer="calibration_history_selector",
        ) from error
    if not run_id.strip():
        _fail("CALIBRATION_STUDY_BINDING_MISMATCH", "Calibration run identity is empty.")

    prefix_id = f"calibration-prefix/{world_id}/{seed}/{comparison_group_id}"
    expected_observations: list[RevealedObservation] = []
    replication_ids: list[str] = []
    candidate_pairs: list[tuple[str, str]] = []
    for replication_index in range(1, 6):
        replication_id = f"calibration-{group_index:02d}-r{replication_index:04d}"
        replication_ids.append(replication_id)
        pair: list[str] = []
        for arm_name in ("adam", "sgd"):
            candidate_id = f"cal-{group_index:02d}-{arm_name}-r{replication_index:04d}"
            pair.append(candidate_id)
            authorization = authorize_observation(
                run_id=run_id,
                source_id=f"{prefix_id}/{candidate_id}",
                candidate_id=candidate_id,
                kind="calibration",
            )
            try:
                observation = reobserve_authorized_observation(
                    world_id=world_id,
                    seed=seed,
                    authorization=authorization,
                )
            except OracleError as error:
                raise RunProvenanceError(
                    "Frozen Oracle could not reconstruct a calibration source observation.",
                    error_code="CALIBRATION_ORACLE_RECONSTRUCTION_FAILED",
                    validation_layer="calibration_history_selector",
                ) from error
            expected_observations.append(observation)
        candidate_pairs.append((pair[0], pair[1]))

    observations = _validate_observations(expected_observations, recorded_observations)
    expected_effects = tuple(
        expected_calibration_effect(
            prefix_id=prefix_id,
            world_id=world_id,
            comparison_group_id=comparison_group_id,
            group_index=group_index,
            replication_index=replication_index,
            observed_effect=round(
                observations[2 * (replication_index - 1)].revealed_observation
                - observations[2 * (replication_index - 1) + 1].revealed_observation,
                12,
            ),
        )
        for replication_index in range(1, 6)
    )
    effects = _validate_effects(
        expected_effects,
        recorded_effects,
        comparison_group_id=comparison_group_id,
        source_sequence_cutoff=source_sequence_cutoff,
    )
    values = tuple(item.observed_effect for item in effects)
    sample_mean = statistics.mean(values)
    sample_sd = statistics.stdev(values)
    costs = candidate_costs(world)
    physical_cost = 5.0 * (
        costs[f"g{group_index:02d}-adam-r1"] + costs[f"g{group_index:02d}-sgd-r1"]
    )
    effect_payloads = tuple(
        hashlib.sha256(canonical_json_bytes(item.to_dict(), final_lf=True)).hexdigest()
        for item in effects
    )
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
        "source_replication_ids": replication_ids,
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
        source_candidate_pairs=tuple(candidate_pairs),
        source_replication_ids=tuple(replication_ids),
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


def _validate_observations(
    expected: Sequence[RevealedObservation],
    recorded: Sequence[RevealedObservation] | None,
) -> tuple[RevealedObservation, ...]:
    canonical = tuple(expected)
    if recorded is None:
        return canonical
    observed = tuple(recorded)
    if len(observed) != len(canonical):
        _fail(
            "CALIBRATION_SOURCE_OBSERVATION_COUNT_MISMATCH",
            "Calibration observations do not contain the exact ten-source population.",
        )
    candidate_ids = tuple(item.candidate_id for item in observed)
    oracle_key_ids = tuple(item.oracle_key_id for item in observed)
    oracle_use_ids = tuple(item.oracle_use_id for item in observed)
    if (
        len(set(candidate_ids)) != len(candidate_ids)
        or len(set(oracle_key_ids)) != len(oracle_key_ids)
        or len(set(oracle_use_ids)) != len(oracle_use_ids)
    ):
        _fail(
            "CALIBRATION_DUPLICATE_SOURCE_OBSERVATION",
            "Calibration source observations contain a duplicate identity.",
        )
    expected_by_candidate = {item.candidate_id: item for item in canonical}
    if set(candidate_ids) != set(expected_by_candidate):
        _fail(
            "CALIBRATION_CANDIDATE_PAIR_MISMATCH",
            "Calibration source candidates differ from the frozen candidate pairs.",
        )
    observed_by_candidate = {item.candidate_id: item for item in observed}
    for expected_item in canonical:
        item = observed_by_candidate[expected_item.candidate_id]
        if item.namespace != expected_item.namespace:
            _fail("CALIBRATION_NAMESPACE_MISMATCH", "Calibration namespace differs.")
        if item.world_id != expected_item.world_id:
            _fail("CALIBRATION_WORLD_MISMATCH", "Calibration source world differs.")
        if item.seed != expected_item.seed:
            _fail("CALIBRATION_SEED_MISMATCH", "Calibration source seed differs.")
        if item.comparison_group_id != expected_item.comparison_group_id:
            _fail("CALIBRATION_GROUP_MISMATCH", "Calibration comparison group differs.")
        if item.replication_id != expected_item.replication_id:
            _fail("CALIBRATION_REPLICATION_MISMATCH", "Calibration replication differs.")
        if not math.isclose(
            item.revealed_observation,
            expected_item.revealed_observation,
            rel_tol=0.0,
            abs_tol=0.0,
        ):
            _fail("CALIBRATION_EFFECT_VALUE_MISMATCH", "Calibration observation value differs.")
        if item != expected_item:
            _fail(
                "CALIBRATION_ORACLE_IDENTITY_MISMATCH",
                "Calibration source observation does not reproduce from the frozen Oracle.",
            )
    return canonical


def _validate_effects(
    expected: Sequence[MatchedEffectObservation],
    recorded: Sequence[MatchedEffectObservation] | None,
    *,
    comparison_group_id: str,
    source_sequence_cutoff: int,
) -> tuple[MatchedEffectObservation, ...]:
    canonical = tuple(expected)
    if recorded is None:
        return canonical
    observed = tuple(recorded)
    ids = tuple(item.effect_id for item in observed)
    if len(set(ids)) != len(ids):
        _fail(
            "CALIBRATION_DUPLICATE_EFFECT_ID", "Calibration history contains a duplicate effect ID."
        )
    expected_by_id = {item.effect_id: item for item in canonical}
    observed_by_id = {item.effect_id: item for item in observed if item.effect_id in expected_by_id}
    if set(observed_by_id) != set(expected_by_id):
        _fail(
            "CALIBRATION_MISSING_ELIGIBLE_EFFECT", "Calibration history lacks an eligible effect."
        )
    for effect_id, expected_item in expected_by_id.items():
        item = observed_by_id[effect_id]
        if item.comparison_group_id != expected_item.comparison_group_id:
            _fail("CALIBRATION_GROUP_MISMATCH", "Calibration effect comparison group differs.")
        if item.available_sequence != expected_item.available_sequence:
            _fail("CALIBRATION_CHRONOLOGY_MISMATCH", "Calibration effect chronology differs.")
        if item.source_kind != expected_item.source_kind:
            _fail("CALIBRATION_INELIGIBLE_EFFECT", "Calibration effect source kind is ineligible.")
        if item.source_ids != expected_item.source_ids:
            _fail(
                "CALIBRATION_CANDIDATE_PAIR_MISMATCH", "Calibration effect candidate pair differs."
            )
        if not math.isclose(
            item.observed_effect,
            expected_item.observed_effect,
            rel_tol=0.0,
            abs_tol=0.0,
        ):
            _fail("CALIBRATION_EFFECT_VALUE_MISMATCH", "Calibration matched-effect value differs.")
        details = item.provenance.details_dict()
        expected_details = expected_item.provenance.details_dict()
        if details.get("replication_id") != expected_details.get("replication_id"):
            _fail("CALIBRATION_REPLICATION_MISMATCH", "Calibration effect replication differs.")
        if details.get("world_id") != expected_details.get("world_id"):
            _fail("CALIBRATION_WORLD_MISMATCH", "Calibration effect world differs.")
        if details.get("comparison_group_id") != expected_details.get("comparison_group_id"):
            _fail("CALIBRATION_GROUP_MISMATCH", "Calibration effect provenance group differs.")
        if item != expected_item:
            _fail(
                "CALIBRATION_EFFECT_PROVENANCE_MISMATCH",
                "Calibration source effect or provenance does not reproduce.",
            )
    extra_eligible = tuple(
        item.effect_id
        for item in observed
        if item.effect_id not in expected_by_id
        and item.comparison_group_id == comparison_group_id
        and item.available_sequence < source_sequence_cutoff
    )
    if extra_eligible:
        _fail(
            "CALIBRATION_EXTRA_ELIGIBLE_EFFECT",
            "Calibration history contains an additional eligible target-group effect.",
        )
    return canonical


def _fail(error_code: str, message: str) -> None:
    raise RunProvenanceError(
        message,
        error_code=error_code,
        validation_layer="calibration_history_selector",
    )
