"""Pure Stage-2F P3 calibration prerequisite and selector-replay evidence.

This module owns only the frozen 3o.1 through 3o.5.1 surface.  Its four public
projections and three public identities are run-independent data.  The private
bundle validators consume already validated predecessor identities, returned
run rows, and immutable scientific records; they issue no authority, execute
no workload, and perform no persistence or evidence I/O.
"""

from __future__ import annotations

from dataclasses import dataclass as _dataclass
from typing import TYPE_CHECKING as _TYPE_CHECKING
from typing import Final as _Final
from typing import Literal as _Literal
from typing import NoReturn as _NoReturn

from research_decision_engine.belief_models import (
    MatchedEffectObservation as _MatchedEffectObservation,
)
from research_decision_engine.benchmarks.broader_protocol import (
    PROTOCOL_VERSION as _FROZEN_STUDY,
)
from research_decision_engine.benchmarks.broader_protocol import (
    canonical_json_bytes as _canonical_json_bytes,
)
from research_decision_engine.benchmarks.broader_protocol import (
    f64 as _f64,
)
from research_decision_engine.benchmarks.broader_protocol import (
    protocol_hash as _protocol_hash,
)
from research_decision_engine.benchmarks.broader_protocol import (
    runtime_id as _runtime_id,
)
from research_decision_engine.benchmarks.broader_worlds import (
    BenchmarkWorld as _BenchmarkWorld,
)
from research_decision_engine.benchmarks.broader_worlds import (
    HiddenWorldParameters as _HiddenWorldParameters,
)
from research_decision_engine.benchmarks.broader_worlds import (
    PublicWorldDefinition as _PublicWorldDefinition,
)
from research_decision_engine.benchmarks.broader_worlds import (
    hidden_arm_mean as _hidden_arm_mean,
)
from research_decision_engine.benchmarks.broader_worlds import (
    hidden_observation_sigma as _hidden_observation_sigma,
)

if _TYPE_CHECKING:
    from research_decision_engine.benchmarks.broader_calibration_history import (
        CalibrationHistorySelection as _CalibrationHistorySelection,
    )
    from research_decision_engine.benchmarks.broader_execution import (
        ReturnedResultsProjection as _ReturnedResultsProjection,
    )
    from research_decision_engine.benchmarks.broader_oracle import (
        RevealedObservation as _RevealedObservation,
    )
    from research_decision_engine.benchmarks.broader_returned_run import (
        ReturnedRunProjection as _ReturnedRunProjection,
    )
    from research_decision_engine.benchmarks.broader_returned_run import (
        RunMatchedEffectProjection as _RunMatchedEffectProjection,
    )
    from research_decision_engine.benchmarks.broader_returned_run import (
        RunObservationAuthorizationProjection as _RunObservationAuthorizationProjection,
    )

_CANDIDATE_PAIR_SCHEMA: _Final = "broader-replication-calibration-candidate-pair/v1"
_STRICT_CHRONOLOGY_SCHEMA: _Final = "broader-replication-calibration-chronology/v1"
_SOURCE_OBSERVATION_SCHEMA: _Final = "broader-replication-calibration-source-observation/v1"
_CALIBRATION_NAMESPACE: _Final = "rde.broader.calibration-outcome/v1"
_STUDY: _Final = "broader-closed-loop-replication/v1"
_ORACLE_NAMESPACE: _Final = "broader_selected_only_oracle/v1"
_SOURCE_SEQUENCE_CUTOFF: _Final = 1
_PAIR_ARM_ORDER: _Final = ("adam", "sgd")
_REPLICATIONS: _Final = (1, 2, 3, 4, 5)

_ROLE_ORDER: _Final = (
    "primary_smoke",
    "altered_order_replay",
    "fixture_primary",
    "fixture_replay",
)
_SMOKE_WORLD_IDS: _Final = (
    "h_adam_low",
    "h_null_high",
    "w_sgd_medium",
    "g_adam_lmh",
    "g_null_hml",
    "c_sgd_a",
    "d2_null",
    "d3_adam",
)
_SMOKE_SEEDS: _Final = (9000, 9001, 9002, 9003)
_GROUP_IDS: _Final = ("group-00", "group-01", "group-02")
_FIXTURE_WORLD_SEEDS: _Final = (
    (
        "g_sgd_hml",
        (
            1000,
            1001,
            1002,
            1003,
            1004,
            1005,
            1006,
            1007,
            1008,
            1009,
            1010,
            1011,
            1012,
            1013,
            1014,
            1015,
            1016,
            1017,
            1018,
            1019,
        ),
    ),
    ("d3_adam", (1000,)),
)

_SMOKE_COORDINATES: _Final = tuple(
    (role, world_id, seed, comparison_group_id)
    for role in _ROLE_ORDER[:2]
    for world_id in _SMOKE_WORLD_IDS
    for seed in _SMOKE_SEEDS
    for comparison_group_id in _GROUP_IDS
)
_FIXTURE_COORDINATES: _Final = tuple(
    (role, world_id, seed, comparison_group_id)
    for role in _ROLE_ORDER[2:]
    for world_id, seeds in _FIXTURE_WORLD_SEEDS
    for seed in seeds
    for comparison_group_id in _GROUP_IDS
)
_CANONICAL_SELECTION_COORDINATES: _Final = _SMOKE_COORDINATES + _FIXTURE_COORDINATES
_CANONICAL_SELECTION_COUNT: _Final = 318

_PAIR_FIELDS: _Final = (
    "adam_candidate_id",
    "comparison_group_id",
    "replication_id",
    "schema_version",
    "sgd_candidate_id",
    "world_id",
)
_CHRONOLOGY_FIELDS: _Final = (
    "current_effect_excluded",
    "current_observation_excluded",
    "effect_available_sequences",
    "future_history_excluded",
    "schema_version",
    "source_sequence_cutoff",
)
_SOURCE_OBSERVATION_FIELDS: _Final = (
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
_SCIENTIFIC_SELECTION_FIELDS: _Final = (
    "comparison_group_id",
    "ddof",
    "effect_values",
    "eligibility_basis",
    "estimated_sigma",
    "namespace",
    "sample_count",
    "sample_mean",
    "sample_standard_deviation",
    "seed",
    "sigma_floor",
    "source_candidate_pairs",
    "source_effect_ids",
    "source_effect_payload_sha256",
    "source_observation_identities",
    "source_oracle_key_ids",
    "source_replication_ids",
    "source_sequence_cutoff",
    "study_id",
    "target_comparison_group_id",
    "world_id",
)
_ID_INITIAL: _Final = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
_ID_REMAINDER: _Final = _ID_INITIAL + "._:/-"
_LOWER_HEX: _Final = "0123456789abcdef"
_I64_MIN: _Final = -(1 << 63)
_I64_MAX: _Final = (1 << 63) - 1

_PREDICATE_PATHS: _Final = (
    "calibration/3o.1.0/execution_attestation_binding",
    "calibration/3o.1.1/pair_candidate",
    "calibration/3o.1.2/study",
    "calibration/3o.1.3/scope",
    "calibration/3o.1.4/replication",
    "calibration/3o.1.5/effect",
    "calibration/3o.1.6/chronology",
)
_P2_PREDICATE_PATHS: _Final = (
    "calibration/3o.2.0/oracle_binding",
    "calibration/3o.2.1/oracle_key",
    "calibration/3o.3.1/outcome",
    "calibration/3o.4.1/source_observation",
)
_P3_PREDICATE_PATH: _Final = "calibration/3o.5.1/selector_result"


@_dataclass(frozen=True, slots=True)
class CalibrationCandidatePairProjection:
    adam_candidate_id: str
    comparison_group_id: str
    replication_id: str
    schema_version: _Literal["broader-replication-calibration-candidate-pair/v1"]
    sgd_candidate_id: str
    world_id: str

    def __post_init__(self) -> None:
        _calibration_candidate_pair_mapping(self)


@_dataclass(frozen=True, slots=True)
class StrictChronologyProjection:
    current_effect_excluded: _Literal[True]
    current_observation_excluded: _Literal[True]
    effect_available_sequences: tuple[int, int, int, int, int]
    future_history_excluded: _Literal[True]
    schema_version: _Literal["broader-replication-calibration-chronology/v1"]
    source_sequence_cutoff: _Literal[1]

    def __post_init__(self) -> None:
        _strict_chronology_mapping(self)


@_dataclass(frozen=True, slots=True)
class CalibrationSourceObservationProjection:
    candidate_id: str
    comparison_group_id: str
    digest: str
    intervention_arm: _Literal["adam", "sgd"]
    key_fields: tuple[str, ...]
    namespace: _Literal["rde.broader.calibration-outcome/v1"]
    oracle_key_id: str
    outcome_digest: str
    replication_id: str
    revealed_observation: str
    schema_version: _Literal["broader-replication-calibration-source-observation/v1"]
    seed: int
    serialized_key_hex: str
    u: str
    world_id: str
    z: str

    def __post_init__(self) -> None:
        _calibration_source_observation_mapping(self)


@_dataclass(frozen=True, slots=True)
class ScientificCalibrationSelectionProjection:
    comparison_group_id: str
    ddof: int
    effect_values: tuple[str, ...]
    eligibility_basis: str
    estimated_sigma: str
    namespace: str
    sample_count: int
    sample_mean: str
    sample_standard_deviation: str
    seed: int
    sigma_floor: str
    source_candidate_pairs: tuple[tuple[str, str], ...]
    source_effect_ids: tuple[str, ...]
    source_effect_payload_sha256: tuple[str, ...]
    source_observation_identities: tuple[tuple[str, str], ...]
    source_oracle_key_ids: tuple[str, ...]
    source_replication_ids: tuple[str, ...]
    source_sequence_cutoff: int
    study_id: str
    target_comparison_group_id: str
    world_id: str

    def __post_init__(self) -> None:
        _scientific_calibration_selection_mapping(self)


type _EffectEvidence = tuple[
    str,
    bytes,
    str,
    _RunMatchedEffectProjection,
]
type _SelectionEvidence = tuple[
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
    tuple[tuple[str, str], ...],
    tuple[CalibrationCandidatePairProjection, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[int, int, int, int, int],
    tuple[str, ...],
    _CalibrationHistorySelection,
    tuple[_EffectEvidence, ...],
    StrictChronologyProjection,
    str,
]
type _ExecutionAttestationPairs = tuple[
    tuple[str, str],
    tuple[str, str],
    tuple[str, str],
    tuple[str, str],
]
type _AttestedSpecificationIds = tuple[str, str, str, str]
type _PredicateFailure = tuple[str, str]
type _ValidationFailure = tuple[str, str, int, str]
type _PredicateCounts = tuple[int, int, int, int, int, int, int]
type _ValidationOutcome = tuple[_ValidationFailure | None, _PredicateCounts]
type _OracleImplementationRelation = tuple[str, str]
type _OraclePredecessor = tuple[
    str,
    str,
    _OracleImplementationRelation,
    str,
    str,
    str,
    int,
    str,
    tuple[tuple[str, str], ...],
    tuple[str, ...],
    _BenchmarkWorld,
]
type _SourceObservationEvidence = tuple[
    CalibrationSourceObservationProjection,
    str,
]
type _P2SelectionEvidence = tuple[
    _OraclePredecessor,
    tuple[_SourceObservationEvidence, ...],
]
type _P2PredicateCounts = tuple[int, int, int, int]
type _P2AllPredicateCounts = tuple[
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
]
type _P2ValidationOutcome = tuple[_ValidationFailure | None, _P2AllPredicateCounts]


@_dataclass(frozen=True, slots=True)
class _P3SelectionInput:
    returned_result_id: str
    returned_run_projection: _ReturnedRunProjection
    submitted_job_id: str
    selector_result_projection: ScientificCalibrationSelectionProjection
    selector_result_identity: str


type _P3AllPredicateCounts = tuple[
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
]
type _P3ValidationOutcome = tuple[_ValidationFailure | None, _P3AllPredicateCounts]


def _reject(path: str, detail: str) -> _NoReturn:
    raise ValueError(f"{path}: {detail}")


def _exact_id(value: object, path: str) -> str:
    if type(value) is not str or not value or value[0] not in _ID_INITIAL:
        _reject(path, "expected exact protocol ID")
    for character in value[1:]:
        if character not in _ID_REMAINDER:
            _reject(path, "expected exact protocol ID")
    return value


def _exact_h64(value: object, path: str) -> str:
    if type(value) is not str or len(value) != 64:
        _reject(path, "expected exact lowercase H64")
    for character in value:
        if character not in _LOWER_HEX:
            _reject(path, "expected exact lowercase H64")
    return value


def _exact_i64(value: object, path: str) -> int:
    if type(value) is not int or not _I64_MIN <= value <= _I64_MAX:
        _reject(path, "expected exact signed I64")
    return value


def _exact_nfc_string(value: object, path: str) -> str:
    import unicodedata as _unicodedata

    if type(value) is not str:
        _reject(path, "expected exact NFC string")
    for character in value:
        if 0xD800 <= ord(character) <= 0xDFFF:
            _reject(path, "expected exact NFC string")
    if _unicodedata.normalize("NFC", value) != value:
        _reject(path, "expected exact NFC string")
    return value


def _closed_mapping(
    value: object,
    fields: tuple[str, ...],
    path: str,
) -> dict[str, object]:
    if type(value) is not dict:
        _reject(path, "expected exact built-in mapping")
    if tuple(value) != fields:
        _reject(path, "mapping fields are missing, extra, or reordered")
    return value


def _calibration_candidate_pair_mapping(
    projection: object,
) -> dict[str, object]:
    if type(projection) is not CalibrationCandidatePairProjection:
        _reject("candidate_pair", "expected exact CalibrationCandidatePairProjection")
    adam_candidate_id = _exact_id(
        projection.adam_candidate_id,
        "candidate_pair.adam_candidate_id",
    )
    comparison_group_id = _exact_id(
        projection.comparison_group_id,
        "candidate_pair.comparison_group_id",
    )
    replication_id = _exact_id(
        projection.replication_id,
        "candidate_pair.replication_id",
    )
    if (
        type(projection.schema_version) is not str
        or projection.schema_version != _CANDIDATE_PAIR_SCHEMA
    ):
        _reject("candidate_pair.schema_version", "schema literal differs")
    sgd_candidate_id = _exact_id(
        projection.sgd_candidate_id,
        "candidate_pair.sgd_candidate_id",
    )
    world_id = _exact_id(projection.world_id, "candidate_pair.world_id")
    return {
        "adam_candidate_id": adam_candidate_id,
        "comparison_group_id": comparison_group_id,
        "replication_id": replication_id,
        "schema_version": _CANDIDATE_PAIR_SCHEMA,
        "sgd_candidate_id": sgd_candidate_id,
        "world_id": world_id,
    }


def _decode_calibration_candidate_pair_projection(
    value: object,
) -> CalibrationCandidatePairProjection:
    mapping = _closed_mapping(value, _PAIR_FIELDS, "candidate_pair")
    adam_candidate_id = _exact_id(
        mapping["adam_candidate_id"],
        "candidate_pair.adam_candidate_id",
    )
    comparison_group_id = _exact_id(
        mapping["comparison_group_id"],
        "candidate_pair.comparison_group_id",
    )
    replication_id = _exact_id(
        mapping["replication_id"],
        "candidate_pair.replication_id",
    )
    schema_version = mapping["schema_version"]
    if type(schema_version) is not str or schema_version != _CANDIDATE_PAIR_SCHEMA:
        _reject("candidate_pair.schema_version", "schema literal differs")
    sgd_candidate_id = _exact_id(
        mapping["sgd_candidate_id"],
        "candidate_pair.sgd_candidate_id",
    )
    world_id = _exact_id(mapping["world_id"], "candidate_pair.world_id")
    return CalibrationCandidatePairProjection(
        adam_candidate_id=adam_candidate_id,
        comparison_group_id=comparison_group_id,
        replication_id=replication_id,
        schema_version=_CANDIDATE_PAIR_SCHEMA,
        sgd_candidate_id=sgd_candidate_id,
        world_id=world_id,
    )


def _calibration_candidate_pair_preimage(
    projection: CalibrationCandidatePairProjection,
) -> dict[str, object]:
    mapping = _calibration_candidate_pair_mapping(projection)
    decoded = _decode_calibration_candidate_pair_projection(mapping)
    if decoded != projection:
        _reject("candidate_pair", "projection does not exactly reconstruct")
    return mapping


def calibration_candidate_pair_id(
    projection: CalibrationCandidatePairProjection,
) -> str:
    return _protocol_hash(
        "validation_evidence_calibration_candidate_pair/v1",
        _calibration_candidate_pair_preimage(projection),
    )


def _strict_chronology_mapping(projection: object) -> dict[str, object]:
    if type(projection) is not StrictChronologyProjection:
        _reject("strict_chronology", "expected exact StrictChronologyProjection")
    if type(projection.current_effect_excluded) is not bool:
        _reject(
            "strict_chronology.current_effect_excluded",
            "expected exact Boolean",
        )
    if projection.current_effect_excluded is not True:
        _reject(
            "strict_chronology.current_effect_excluded",
            "expected literal true",
        )
    if type(projection.current_observation_excluded) is not bool:
        _reject(
            "strict_chronology.current_observation_excluded",
            "expected exact Boolean",
        )
    if projection.current_observation_excluded is not True:
        _reject(
            "strict_chronology.current_observation_excluded",
            "expected literal true",
        )
    sequences = projection.effect_available_sequences
    if type(sequences) is not tuple or len(sequences) != 5:
        _reject(
            "strict_chronology.effect_available_sequences",
            "expected exact five-item tuple",
        )
    for sequence in sequences:
        if type(sequence) is not int or sequence != 0:
            _reject(
                "strict_chronology.effect_available_sequences",
                "expected five exact integer zeros",
            )
    if type(projection.future_history_excluded) is not bool:
        _reject(
            "strict_chronology.future_history_excluded",
            "expected exact Boolean",
        )
    if projection.future_history_excluded is not True:
        _reject(
            "strict_chronology.future_history_excluded",
            "expected literal true",
        )
    if (
        type(projection.schema_version) is not str
        or projection.schema_version != _STRICT_CHRONOLOGY_SCHEMA
    ):
        _reject("strict_chronology.schema_version", "schema literal differs")
    if (
        type(projection.source_sequence_cutoff) is not int
        or projection.source_sequence_cutoff != _SOURCE_SEQUENCE_CUTOFF
    ):
        _reject(
            "strict_chronology.source_sequence_cutoff",
            "expected exact integer cutoff 1",
        )
    return {
        "current_effect_excluded": True,
        "current_observation_excluded": True,
        "effect_available_sequences": sequences,
        "future_history_excluded": True,
        "schema_version": _STRICT_CHRONOLOGY_SCHEMA,
        "source_sequence_cutoff": _SOURCE_SEQUENCE_CUTOFF,
    }


def _decode_strict_chronology_projection(
    value: object,
) -> StrictChronologyProjection:
    mapping = _closed_mapping(value, _CHRONOLOGY_FIELDS, "strict_chronology")
    current_effect_excluded = mapping["current_effect_excluded"]
    if type(current_effect_excluded) is not bool or current_effect_excluded is not True:
        _reject(
            "strict_chronology.current_effect_excluded",
            "expected literal true",
        )
    current_observation_excluded = mapping["current_observation_excluded"]
    if type(current_observation_excluded) is not bool or current_observation_excluded is not True:
        _reject(
            "strict_chronology.current_observation_excluded",
            "expected literal true",
        )
    sequences = mapping["effect_available_sequences"]
    if type(sequences) is not tuple or len(sequences) != 5:
        _reject(
            "strict_chronology.effect_available_sequences",
            "expected exact five-item tuple",
        )
    for sequence in sequences:
        if type(sequence) is not int or sequence != 0:
            _reject(
                "strict_chronology.effect_available_sequences",
                "expected five exact integer zeros",
            )
    future_history_excluded = mapping["future_history_excluded"]
    if type(future_history_excluded) is not bool or future_history_excluded is not True:
        _reject(
            "strict_chronology.future_history_excluded",
            "expected literal true",
        )
    schema_version = mapping["schema_version"]
    if type(schema_version) is not str or schema_version != _STRICT_CHRONOLOGY_SCHEMA:
        _reject("strict_chronology.schema_version", "schema literal differs")
    source_sequence_cutoff = mapping["source_sequence_cutoff"]
    if type(source_sequence_cutoff) is not int or source_sequence_cutoff != _SOURCE_SEQUENCE_CUTOFF:
        _reject(
            "strict_chronology.source_sequence_cutoff",
            "expected exact integer cutoff 1",
        )
    return StrictChronologyProjection(
        current_effect_excluded=True,
        current_observation_excluded=True,
        effect_available_sequences=sequences,
        future_history_excluded=True,
        schema_version=_STRICT_CHRONOLOGY_SCHEMA,
        source_sequence_cutoff=1,
    )


def _strict_chronology_preimage(
    projection: StrictChronologyProjection,
) -> dict[str, object]:
    mapping = _strict_chronology_mapping(projection)
    decoded = _decode_strict_chronology_projection(mapping)
    if decoded != projection:
        _reject("strict_chronology", "projection does not exactly reconstruct")
    return mapping


def strict_chronology_id(projection: StrictChronologyProjection) -> str:
    return _protocol_hash(
        "validation_evidence_calibration_chronology/v1",
        _strict_chronology_preimage(projection),
    )


def _exact_ascii_string(value: object, path: str) -> str:
    if type(value) is not str or not value:
        _reject(path, "expected exact non-empty ASCII string")
    for character in value:
        if character > "\x7f":
            _reject(path, "expected exact non-empty ASCII string")
    return value


def _exact_oracle_key_id(value: object, path: str) -> str:
    if type(value) is not str or value[:11] != "oracle-key:":
        _reject(path, "expected exact Oracle key identity")
    _exact_h64(value[len("oracle-key:") :], path)
    return value


def _exact_hex_bytes(value: object, path: str) -> str:
    if type(value) is not str or not value or len(value) % 2 != 0:
        _reject(path, "expected exact non-empty lowercase HEXBYTES")
    for character in value:
        if character not in _LOWER_HEX:
            _reject(path, "expected exact non-empty lowercase HEXBYTES")
    return value


def _exact_f64_string(value: object, path: str) -> str:
    if type(value) is not str or len(value) != 20 or value[:4] != "f64:":
        _reject(path, "expected exact canonical F64")
    for character in value[4:]:
        if character not in _LOWER_HEX:
            _reject(path, "expected exact canonical F64")
    if value == "f64:8000000000000000" or (value[4] in "7f" and value[5:7] == "ff"):
        _reject(path, "expected finite canonical F64")
    return value


def _exact_decimal_string(
    value: object,
    path: str,
    *,
    fractional_digits: int,
    unit_interval: bool,
) -> str:
    if type(value) is not str or not value:
        _reject(path, "expected exact canonical decimal string")
    negative = value[0] == "-"
    first_digit = 1 if negative else 0
    dot_index = len(value) - fractional_digits - 1
    if (
        dot_index <= first_digit
        or value[dot_index] != "."
        or len(value) - dot_index - 1 != fractional_digits
    ):
        _reject(path, "expected exact canonical decimal string")
    whole = value[first_digit:dot_index]
    fractional = value[dot_index + 1 :]
    for character in whole:
        if character not in "0123456789":
            _reject(path, "expected exact canonical decimal string")
    fractional_nonzero = False
    for character in fractional:
        if character not in "0123456789":
            _reject(path, "expected exact canonical decimal string")
        if character != "0":
            fractional_nonzero = True
    if len(whole) > 1 and whole[0] == "0":
        _reject(path, "expected exact canonical decimal string")
    whole_nonzero = False
    for character in whole:
        if character != "0":
            whole_nonzero = True
    if unit_interval:
        if negative or whole != "0" or not fractional_nonzero:
            _reject(path, "expected exact open-unit-interval decimal")
    elif negative and not whole_nonzero and not fractional_nonzero:
        _reject(path, "negative zero is not canonical")
    return value


def _lower_hex_bytes(value: object, path: str) -> str:
    if type(value) is not bytes or not value:
        _reject(path, "expected exact non-empty built-in bytes")
    encoded = ""
    for byte in value:
        encoded += _LOWER_HEX[byte >> 4]
        encoded += _LOWER_HEX[byte & 15]
    return encoded


def _source_mapping(
    value: object,
) -> dict[str, object]:
    path = "source_observation"
    if type(value) is not dict or len(value) != len(_SOURCE_OBSERVATION_FIELDS):
        _reject(path, "expected exact closed built-in mapping")
    keys = tuple(value)
    for key in keys:
        if type(key) is not str:
            _reject(path, "mapping keys must be exact built-in strings")
    if keys != _SOURCE_OBSERVATION_FIELDS:
        _reject(path, "mapping fields are missing, extra, or reordered")
    return value


def _source_arm(value: object) -> _Literal["adam", "sgd"]:
    if type(value) is not str:
        _reject("source_observation.intervention_arm", "arm literal differs")
    if value == "adam":
        return "adam"
    if value == "sgd":
        return "sgd"
    _reject("source_observation.intervention_arm", "arm literal differs")


def _source_key_fields(value: object) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) != 8:
        _reject("source_observation.key_fields", "expected exact eight-item tuple")
    for field in value:
        _exact_ascii_string(field, "source_observation.key_fields")
    return value


def _source_namespace(value: object) -> _Literal["rde.broader.calibration-outcome/v1"]:
    if type(value) is not str or value != _CALIBRATION_NAMESPACE:
        _reject("source_observation.namespace", "namespace literal differs")
    return "rde.broader.calibration-outcome/v1"


def _source_schema(
    value: object,
) -> _Literal["broader-replication-calibration-source-observation/v1"]:
    if type(value) is not str or value != _SOURCE_OBSERVATION_SCHEMA:
        _reject("source_observation.schema_version", "schema literal differs")
    return "broader-replication-calibration-source-observation/v1"


def _source_seed(value: object) -> int:
    if type(value) is not int or not -(1 << 63) <= value <= (1 << 63) - 1:
        _reject("source_observation.seed", "expected exact I64")
    return value


def _calibration_source_observation_mapping(
    projection: object,
) -> dict[str, object]:
    if type(projection) is not CalibrationSourceObservationProjection:
        _reject(
            "source_observation",
            "expected exact CalibrationSourceObservationProjection",
        )
    return {
        "candidate_id": _exact_id(projection.candidate_id, "source_observation.candidate_id"),
        "comparison_group_id": _exact_id(
            projection.comparison_group_id,
            "source_observation.comparison_group_id",
        ),
        "digest": _exact_h64(projection.digest, "source_observation.digest"),
        "intervention_arm": _source_arm(projection.intervention_arm),
        "key_fields": _source_key_fields(projection.key_fields),
        "namespace": _source_namespace(projection.namespace),
        "oracle_key_id": _exact_oracle_key_id(
            projection.oracle_key_id,
            "source_observation.oracle_key_id",
        ),
        "outcome_digest": _exact_h64(
            projection.outcome_digest,
            "source_observation.outcome_digest",
        ),
        "replication_id": _exact_id(
            projection.replication_id,
            "source_observation.replication_id",
        ),
        "revealed_observation": _exact_f64_string(
            projection.revealed_observation,
            "source_observation.revealed_observation",
        ),
        "schema_version": _source_schema(projection.schema_version),
        "seed": _source_seed(projection.seed),
        "serialized_key_hex": _exact_hex_bytes(
            projection.serialized_key_hex,
            "source_observation.serialized_key_hex",
        ),
        "u": _exact_decimal_string(
            projection.u,
            "source_observation.u",
            fractional_digits=53,
            unit_interval=True,
        ),
        "world_id": _exact_id(projection.world_id, "source_observation.world_id"),
        "z": _exact_decimal_string(
            projection.z,
            "source_observation.z",
            fractional_digits=30,
            unit_interval=False,
        ),
    }


def _decode_calibration_source_observation_projection(
    value: object,
) -> CalibrationSourceObservationProjection:
    mapping = _source_mapping(value)
    return CalibrationSourceObservationProjection(
        candidate_id=_exact_id(mapping["candidate_id"], "source_observation.candidate_id"),
        comparison_group_id=_exact_id(
            mapping["comparison_group_id"],
            "source_observation.comparison_group_id",
        ),
        digest=_exact_h64(mapping["digest"], "source_observation.digest"),
        intervention_arm=_source_arm(mapping["intervention_arm"]),
        key_fields=_source_key_fields(mapping["key_fields"]),
        namespace=_source_namespace(mapping["namespace"]),
        oracle_key_id=_exact_oracle_key_id(
            mapping["oracle_key_id"],
            "source_observation.oracle_key_id",
        ),
        outcome_digest=_exact_h64(
            mapping["outcome_digest"],
            "source_observation.outcome_digest",
        ),
        replication_id=_exact_id(
            mapping["replication_id"],
            "source_observation.replication_id",
        ),
        revealed_observation=_exact_f64_string(
            mapping["revealed_observation"],
            "source_observation.revealed_observation",
        ),
        schema_version=_source_schema(mapping["schema_version"]),
        seed=_source_seed(mapping["seed"]),
        serialized_key_hex=_exact_hex_bytes(
            mapping["serialized_key_hex"],
            "source_observation.serialized_key_hex",
        ),
        u=_exact_decimal_string(
            mapping["u"],
            "source_observation.u",
            fractional_digits=53,
            unit_interval=True,
        ),
        world_id=_exact_id(mapping["world_id"], "source_observation.world_id"),
        z=_exact_decimal_string(
            mapping["z"],
            "source_observation.z",
            fractional_digits=30,
            unit_interval=False,
        ),
    )


def _scientific_calibration_selection_mapping(
    projection: object,
) -> dict[str, object]:
    if type(projection) is not ScientificCalibrationSelectionProjection:
        _reject(
            "scientific_selection",
            "expected exact ScientificCalibrationSelectionProjection",
        )
    comparison_group_id = _exact_id(
        projection.comparison_group_id,
        "scientific_selection.comparison_group_id",
    )
    ddof = _exact_i64(projection.ddof, "scientific_selection.ddof")
    effect_values = projection.effect_values
    if type(effect_values) is not tuple or len(effect_values) != 5:
        _reject(
            "scientific_selection.effect_values",
            "expected exact five-item tuple",
        )
    for index in range(5):
        _exact_f64_string(
            effect_values[index],
            f"scientific_selection.effect_values[{index}]",
        )
    eligibility_basis = _exact_nfc_string(
        projection.eligibility_basis,
        "scientific_selection.eligibility_basis",
    )
    estimated_sigma = _exact_f64_string(
        projection.estimated_sigma,
        "scientific_selection.estimated_sigma",
    )
    namespace = _exact_id(
        projection.namespace,
        "scientific_selection.namespace",
    )
    sample_count = _exact_i64(
        projection.sample_count,
        "scientific_selection.sample_count",
    )
    sample_mean = _exact_f64_string(
        projection.sample_mean,
        "scientific_selection.sample_mean",
    )
    sample_standard_deviation = _exact_f64_string(
        projection.sample_standard_deviation,
        "scientific_selection.sample_standard_deviation",
    )
    seed = _exact_i64(projection.seed, "scientific_selection.seed")
    sigma_floor = _exact_f64_string(
        projection.sigma_floor,
        "scientific_selection.sigma_floor",
    )
    source_candidate_pairs = projection.source_candidate_pairs
    if type(source_candidate_pairs) is not tuple or len(source_candidate_pairs) != 5:
        _reject(
            "scientific_selection.source_candidate_pairs",
            "expected exact five-item tuple",
        )
    for index in range(5):
        pair = source_candidate_pairs[index]
        if type(pair) is not tuple or len(pair) != 2:
            _reject(
                f"scientific_selection.source_candidate_pairs[{index}]",
                "expected exact two-item tuple",
            )
        _exact_id(
            pair[0],
            f"scientific_selection.source_candidate_pairs[{index}][0]",
        )
        _exact_id(
            pair[1],
            f"scientific_selection.source_candidate_pairs[{index}][1]",
        )
    source_effect_ids = projection.source_effect_ids
    if type(source_effect_ids) is not tuple or len(source_effect_ids) != 5:
        _reject(
            "scientific_selection.source_effect_ids",
            "expected exact five-item tuple",
        )
    for index in range(5):
        _exact_id(
            source_effect_ids[index],
            f"scientific_selection.source_effect_ids[{index}]",
        )
    source_effect_payload_sha256 = projection.source_effect_payload_sha256
    if type(source_effect_payload_sha256) is not tuple or len(source_effect_payload_sha256) != 5:
        _reject(
            "scientific_selection.source_effect_payload_sha256",
            "expected exact five-item tuple",
        )
    for index in range(5):
        _exact_h64(
            source_effect_payload_sha256[index],
            f"scientific_selection.source_effect_payload_sha256[{index}]",
        )
    source_observation_identities = projection.source_observation_identities
    if type(source_observation_identities) is not tuple or len(source_observation_identities) != 10:
        _reject(
            "scientific_selection.source_observation_identities",
            "expected exact ten-item tuple",
        )
    for index in range(10):
        pair = source_observation_identities[index]
        if type(pair) is not tuple or len(pair) != 2:
            _reject(
                f"scientific_selection.source_observation_identities[{index}]",
                "expected exact two-item tuple",
            )
        _exact_id(
            pair[0],
            f"scientific_selection.source_observation_identities[{index}][0]",
        )
        _exact_h64(
            pair[1],
            f"scientific_selection.source_observation_identities[{index}][1]",
        )
    source_oracle_key_ids = projection.source_oracle_key_ids
    if type(source_oracle_key_ids) is not tuple or len(source_oracle_key_ids) != 10:
        _reject(
            "scientific_selection.source_oracle_key_ids",
            "expected exact ten-item tuple",
        )
    for index in range(10):
        _exact_id(
            source_oracle_key_ids[index],
            f"scientific_selection.source_oracle_key_ids[{index}]",
        )
    source_replication_ids = projection.source_replication_ids
    if type(source_replication_ids) is not tuple or len(source_replication_ids) != 5:
        _reject(
            "scientific_selection.source_replication_ids",
            "expected exact five-item tuple",
        )
    for index in range(5):
        _exact_id(
            source_replication_ids[index],
            f"scientific_selection.source_replication_ids[{index}]",
        )
    source_sequence_cutoff = _exact_i64(
        projection.source_sequence_cutoff,
        "scientific_selection.source_sequence_cutoff",
    )
    if source_sequence_cutoff != 1:
        _reject(
            "scientific_selection.source_sequence_cutoff",
            "expected exact integer cutoff 1",
        )
    study_id = _exact_id(
        projection.study_id,
        "scientific_selection.study_id",
    )
    target_comparison_group_id = _exact_id(
        projection.target_comparison_group_id,
        "scientific_selection.target_comparison_group_id",
    )
    world_id = _exact_id(
        projection.world_id,
        "scientific_selection.world_id",
    )
    return {
        "comparison_group_id": comparison_group_id,
        "ddof": ddof,
        "effect_values": [item for item in effect_values],
        "eligibility_basis": eligibility_basis,
        "estimated_sigma": estimated_sigma,
        "namespace": namespace,
        "sample_count": sample_count,
        "sample_mean": sample_mean,
        "sample_standard_deviation": sample_standard_deviation,
        "seed": seed,
        "sigma_floor": sigma_floor,
        "source_candidate_pairs": [[pair[0], pair[1]] for pair in source_candidate_pairs],
        "source_effect_ids": [item for item in source_effect_ids],
        "source_effect_payload_sha256": [item for item in source_effect_payload_sha256],
        "source_observation_identities": [
            [pair[0], pair[1]] for pair in source_observation_identities
        ],
        "source_oracle_key_ids": [item for item in source_oracle_key_ids],
        "source_replication_ids": [item for item in source_replication_ids],
        "source_sequence_cutoff": source_sequence_cutoff,
        "study_id": study_id,
        "target_comparison_group_id": target_comparison_group_id,
        "world_id": world_id,
    }


def _decode_scientific_calibration_selection_projection(
    value: object,
) -> ScientificCalibrationSelectionProjection:
    if type(value) is not dict:
        _reject("scientific_selection", "expected exact built-in mapping")
    raw_keys = tuple(dict.keys(value))
    if len(raw_keys) != len(_SCIENTIFIC_SELECTION_FIELDS):
        _reject(
            "scientific_selection",
            "mapping fields are missing, extra, or reordered",
        )
    for key in raw_keys:
        if type(key) is not str:
            _reject(
                "scientific_selection",
                "mapping fields are missing, extra, or reordered",
            )
    mapping = _closed_mapping(
        value,
        _SCIENTIFIC_SELECTION_FIELDS,
        "scientific_selection",
    )

    comparison_group_id = _exact_id(
        mapping["comparison_group_id"],
        "scientific_selection.comparison_group_id",
    )
    ddof = _exact_i64(mapping["ddof"], "scientific_selection.ddof")
    raw_effect_values = mapping["effect_values"]
    if type(raw_effect_values) is not list or len(raw_effect_values) != 5:
        _reject(
            "scientific_selection.effect_values",
            "expected exact five-item list",
        )
    effect_values: tuple[str, ...] = ()
    for index in range(5):
        effect_values = (
            *effect_values,
            _exact_f64_string(
                raw_effect_values[index],
                f"scientific_selection.effect_values[{index}]",
            ),
        )
    eligibility_basis = _exact_nfc_string(
        mapping["eligibility_basis"],
        "scientific_selection.eligibility_basis",
    )
    estimated_sigma = _exact_f64_string(
        mapping["estimated_sigma"],
        "scientific_selection.estimated_sigma",
    )
    namespace = _exact_id(mapping["namespace"], "scientific_selection.namespace")
    sample_count = _exact_i64(
        mapping["sample_count"],
        "scientific_selection.sample_count",
    )
    sample_mean = _exact_f64_string(
        mapping["sample_mean"],
        "scientific_selection.sample_mean",
    )
    sample_standard_deviation = _exact_f64_string(
        mapping["sample_standard_deviation"],
        "scientific_selection.sample_standard_deviation",
    )
    seed = _exact_i64(mapping["seed"], "scientific_selection.seed")
    sigma_floor = _exact_f64_string(
        mapping["sigma_floor"],
        "scientific_selection.sigma_floor",
    )
    raw_candidate_pairs = mapping["source_candidate_pairs"]
    if type(raw_candidate_pairs) is not list or len(raw_candidate_pairs) != 5:
        _reject(
            "scientific_selection.source_candidate_pairs",
            "expected exact five-item list",
        )
    source_candidate_pairs: tuple[tuple[str, str], ...] = ()
    for index in range(5):
        pair = raw_candidate_pairs[index]
        if type(pair) is not list or len(pair) != 2:
            _reject(
                f"scientific_selection.source_candidate_pairs[{index}]",
                "expected exact two-item list",
            )
        source_candidate_pairs = (
            *source_candidate_pairs,
            (
                _exact_id(
                    pair[0],
                    f"scientific_selection.source_candidate_pairs[{index}][0]",
                ),
                _exact_id(
                    pair[1],
                    f"scientific_selection.source_candidate_pairs[{index}][1]",
                ),
            ),
        )
    raw_effect_ids = mapping["source_effect_ids"]
    if type(raw_effect_ids) is not list or len(raw_effect_ids) != 5:
        _reject(
            "scientific_selection.source_effect_ids",
            "expected exact five-item list",
        )
    source_effect_ids: tuple[str, ...] = ()
    for index in range(5):
        source_effect_ids = (
            *source_effect_ids,
            _exact_id(
                raw_effect_ids[index],
                f"scientific_selection.source_effect_ids[{index}]",
            ),
        )
    raw_effect_digests = mapping["source_effect_payload_sha256"]
    if type(raw_effect_digests) is not list or len(raw_effect_digests) != 5:
        _reject(
            "scientific_selection.source_effect_payload_sha256",
            "expected exact five-item list",
        )
    source_effect_payload_sha256: tuple[str, ...] = ()
    for index in range(5):
        source_effect_payload_sha256 = (
            *source_effect_payload_sha256,
            _exact_h64(
                raw_effect_digests[index],
                f"scientific_selection.source_effect_payload_sha256[{index}]",
            ),
        )
    raw_observation_identities = mapping["source_observation_identities"]
    if type(raw_observation_identities) is not list or len(raw_observation_identities) != 10:
        _reject(
            "scientific_selection.source_observation_identities",
            "expected exact ten-item list",
        )
    source_observation_identities: tuple[tuple[str, str], ...] = ()
    for index in range(10):
        pair = raw_observation_identities[index]
        if type(pair) is not list or len(pair) != 2:
            _reject(
                f"scientific_selection.source_observation_identities[{index}]",
                "expected exact two-item list",
            )
        source_observation_identities = (
            *source_observation_identities,
            (
                _exact_id(
                    pair[0],
                    f"scientific_selection.source_observation_identities[{index}][0]",
                ),
                _exact_h64(
                    pair[1],
                    f"scientific_selection.source_observation_identities[{index}][1]",
                ),
            ),
        )
    raw_oracle_key_ids = mapping["source_oracle_key_ids"]
    if type(raw_oracle_key_ids) is not list or len(raw_oracle_key_ids) != 10:
        _reject(
            "scientific_selection.source_oracle_key_ids",
            "expected exact ten-item list",
        )
    source_oracle_key_ids: tuple[str, ...] = ()
    for index in range(10):
        source_oracle_key_ids = (
            *source_oracle_key_ids,
            _exact_id(
                raw_oracle_key_ids[index],
                f"scientific_selection.source_oracle_key_ids[{index}]",
            ),
        )
    raw_replication_ids = mapping["source_replication_ids"]
    if type(raw_replication_ids) is not list or len(raw_replication_ids) != 5:
        _reject(
            "scientific_selection.source_replication_ids",
            "expected exact five-item list",
        )
    source_replication_ids: tuple[str, ...] = ()
    for index in range(5):
        source_replication_ids = (
            *source_replication_ids,
            _exact_id(
                raw_replication_ids[index],
                f"scientific_selection.source_replication_ids[{index}]",
            ),
        )
    source_sequence_cutoff = _exact_i64(
        mapping["source_sequence_cutoff"],
        "scientific_selection.source_sequence_cutoff",
    )
    if source_sequence_cutoff != 1:
        _reject(
            "scientific_selection.source_sequence_cutoff",
            "expected exact integer cutoff 1",
        )
    study_id = _exact_id(mapping["study_id"], "scientific_selection.study_id")
    target_comparison_group_id = _exact_id(
        mapping["target_comparison_group_id"],
        "scientific_selection.target_comparison_group_id",
    )
    world_id = _exact_id(mapping["world_id"], "scientific_selection.world_id")
    return ScientificCalibrationSelectionProjection(
        comparison_group_id=comparison_group_id,
        ddof=ddof,
        effect_values=effect_values,
        eligibility_basis=eligibility_basis,
        estimated_sigma=estimated_sigma,
        namespace=namespace,
        sample_count=sample_count,
        sample_mean=sample_mean,
        sample_standard_deviation=sample_standard_deviation,
        seed=seed,
        sigma_floor=sigma_floor,
        source_candidate_pairs=source_candidate_pairs,
        source_effect_ids=source_effect_ids,
        source_effect_payload_sha256=source_effect_payload_sha256,
        source_observation_identities=source_observation_identities,
        source_oracle_key_ids=source_oracle_key_ids,
        source_replication_ids=source_replication_ids,
        source_sequence_cutoff=source_sequence_cutoff,
        study_id=study_id,
        target_comparison_group_id=target_comparison_group_id,
        world_id=world_id,
    )


def _source_observation_preimage(
    projection: CalibrationSourceObservationProjection,
) -> dict[str, object]:
    mapping = _calibration_source_observation_mapping(projection)
    decoded = _decode_calibration_source_observation_projection(mapping)
    if decoded != projection:
        _reject("source_observation", "projection does not exactly reconstruct")
    return mapping


def source_observation_identity(
    projection: CalibrationSourceObservationProjection,
) -> str:
    return _protocol_hash(
        "validation_evidence_calibration_source_observation/v1",
        _source_observation_preimage(projection),
    )


def _oracle_key_id(key_fields):  # type: ignore[no-untyped-def]
    return _runtime_id(
        "oracle-key",
        "oracle_key_id/v1",
        {"key_fields": key_fields},
    )


def _outcome_digest(  # type: ignore[no-untyped-def]
    oracle_key_id,
    revealed_observation,
):
    return _protocol_hash(
        "revealed_outcome/v1",
        {
            "oracle_key_id": oracle_key_id,
            "revealed_observation": revealed_observation,
        },
    )


def _source_observation_matches(
    projection: CalibrationSourceObservationProjection,
    carried_source_observation_identity: str,
) -> bool:
    return source_observation_identity(projection) == carried_source_observation_identity


def _effect_payload_sha256(effect: _MatchedEffectObservation) -> str:
    from research_decision_engine.benchmarks.broader_calibration_selector_replay import (
        raw_effect_sha256 as _raw_effect_sha256,
    )

    return _raw_effect_sha256(effect)


def _effect_projection_mapping(
    projection: object,
) -> dict[str, object]:
    from research_decision_engine.benchmarks.broader_returned_run import (
        RunMatchedEffectProjection as _RunMatchedEffectProjection,
    )

    if type(projection) is not _RunMatchedEffectProjection:
        _reject("source_effect.effect_projection", "expected exact effect projection")
    provenance = projection.provenance
    details = provenance.details
    if type(details) is not tuple:
        _reject(
            "source_effect.effect_projection.provenance.details",
            "expected exact tuple",
        )
    encoded_details: tuple[object, ...] = ()
    for pair in details:
        if type(pair) is not tuple or len(pair) != 2 or type(pair[0]) is not str:
            _reject(
                "source_effect.effect_projection.provenance.details",
                "expected exact ordered pairs",
            )
        projected_value = pair[1]
        encoded_details = (
            *encoded_details,
            [
                pair[0],
                {
                    "kind": projected_value.kind,
                    "value": projected_value.value,
                },
            ],
        )
    if type(projection.source_ids) is not tuple:
        _reject(
            "source_effect.effect_projection.source_ids",
            "expected exact tuple",
        )
    return {
        "available_sequence": projection.available_sequence,
        "comparison_group_id": projection.comparison_group_id,
        "created_at": projection.created_at,
        "effect_id": projection.effect_id,
        "observed_effect": projection.observed_effect,
        "provenance": {
            "details": [item for item in encoded_details],
            "method": provenance.method,
            "version": provenance.version,
        },
        "source_ids": [source_id for source_id in projection.source_ids],
        "source_kind": projection.source_kind,
    }


def _projection_matches_effect(
    projection: object,
    effect: object,
) -> bool:
    from research_decision_engine.benchmarks.broader_returned_run import (
        RunMatchedEffectProjection as _RunMatchedEffectProjection,
    )

    if (
        type(projection) is not _RunMatchedEffectProjection
        or type(effect) is not _MatchedEffectObservation
    ):
        return False
    try:
        observed_effect = _f64(effect.observed_effect)
    except (AttributeError, TypeError, ValueError):
        return False
    if (
        projection.available_sequence != effect.available_sequence
        or projection.comparison_group_id != effect.comparison_group_id
        or projection.created_at != effect.created_at
        or projection.effect_id != effect.effect_id
        or projection.observed_effect != observed_effect
        or projection.source_ids != effect.source_ids
        or projection.source_kind != effect.source_kind
        or projection.provenance.method != effect.provenance.method
        or projection.provenance.version != effect.provenance.version
    ):
        return False
    raw_details = effect.provenance.details
    projected_details = projection.provenance.details
    if (
        type(raw_details) is not tuple
        or type(projected_details) is not tuple
        or len(raw_details) != len(projected_details)
    ):
        return False
    for index in range(len(raw_details)):
        raw_pair = raw_details[index]
        projected_pair = projected_details[index]
        if (
            type(raw_pair) is not tuple
            or len(raw_pair) != 2
            or type(projected_pair) is not tuple
            or len(projected_pair) != 2
            or raw_pair[0] != projected_pair[0]
        ):
            return False
        raw_value = raw_pair[1]
        projected_value = projected_pair[1]
        expected_kind: str
        expected_value: object
        if raw_value is None:
            expected_kind, expected_value = "null", None
        elif type(raw_value) is bool:
            expected_kind, expected_value = "bool", raw_value
        elif type(raw_value) is int:
            expected_kind, expected_value = "i64", raw_value
        elif type(raw_value) is float:
            try:
                expected_kind, expected_value = "f64", _f64(raw_value)
            except ValueError:
                return False
        elif type(raw_value) is str:
            expected_kind, expected_value = "string", raw_value
        else:
            return False
        if projected_value.kind != expected_kind or projected_value.value != expected_value:
            return False
    return True


def _effect_replication_id(effect: object) -> str | None:
    if type(effect) is not _MatchedEffectObservation:
        return None
    details = effect.provenance.details
    if type(details) is not tuple:
        return None
    found: str | None = None
    for pair in details:
        if type(pair) is tuple and len(pair) == 2 and pair[0] == "replication_id":
            if found is not None or type(pair[1]) is not str:
                return None
            found = pair[1]
    return found


def _selection_shape(value: object) -> bool:
    return type(value) is tuple and len(value) == 20


def _coordinate_detail(index: int, detail: str) -> str:
    if 0 <= index < _CANONICAL_SELECTION_COUNT:
        role, world_id, seed, comparison_group_id = _CANONICAL_SELECTION_COORDINATES[index]
        return f"selection[{index}] {role}/{world_id}/{seed}/{comparison_group_id}: {detail}"
    return f"selection[{index}]: {detail}"


def _pair_failure(detail: str) -> _PredicateFailure:
    return "CALIBRATION_CANDIDATE_PAIR_MISMATCH", detail


def _study_failure(detail: str) -> _PredicateFailure:
    return "CALIBRATION_STUDY_MISMATCH", detail


def _scope_failure(detail: str) -> _PredicateFailure:
    return "CALIBRATION_SCOPE_MISMATCH", detail


def _replication_failure(detail: str) -> _PredicateFailure:
    return "CALIBRATION_REPLICATION_MISMATCH", detail


def _effect_failure(detail: str) -> _PredicateFailure:
    return "CALIBRATION_SOURCE_EFFECT_ORDER_MISMATCH", detail


def _chronology_failure(detail: str) -> _PredicateFailure:
    return "CALIBRATION_CHRONOLOGY_ID_MISMATCH", detail


def _role_index(role: object) -> int | None:
    if type(role) is not str:
        return None
    for index in range(len(_ROLE_ORDER)):
        if role == _ROLE_ORDER[index]:
            return index
    return None


def _group_index(comparison_group_id: object) -> int | None:
    if type(comparison_group_id) is not str:
        return None
    for index in range(len(_GROUP_IDS)):
        if comparison_group_id == _GROUP_IDS[index]:
            return index
    return None


def _predicate_3o_1_0(
    selection: _SelectionEvidence,
    expected_pairs: _ExecutionAttestationPairs,
    attested_specification_ids: _AttestedSpecificationIds,
) -> _PredicateFailure | None:
    (
        role,
        _position,
        _world_id,
        _seed,
        _comparison_group_id,
        _calibration_namespace,
        _calibration_prefix_id,
        execution_specification_id,
        executor_attestation_id,
        _study_occurrences,
        _ordered_candidate_pairs,
        _ordered_candidate_pair_projections,
        _ordered_candidate_pair_ids,
        _ordered_replication_ids,
        _replication_ranks,
        _ordered_source_effect_ids,
        _selector_result,
        _ordered_source_effects,
        _strict_chronology,
        _carried_strict_chronology_id,
    ) = selection
    role_index = _role_index(role)
    if (
        role_index is None
        or type(expected_pairs) is not tuple
        or len(expected_pairs) != 4
        or type(attested_specification_ids) is not tuple
        or len(attested_specification_ids) != 4
    ):
        return (
            "CALIBRATION_EXECUTION_ATTESTATION_PAIR_MISMATCH",
            "predecessor execution/attestation anchors are malformed",
        )
    expected_pair = expected_pairs[role_index]
    if type(expected_pair) is not tuple or len(expected_pair) != 2:
        return (
            "CALIBRATION_EXECUTION_ATTESTATION_PAIR_MISMATCH",
            "expected enclosing pair is malformed",
        )
    expected_specification_id, expected_attestation_id = expected_pair
    try:
        _exact_h64(expected_specification_id, "expected_specification_id")
        _exact_h64(expected_attestation_id, "expected_attestation_id")
        _exact_h64(
            attested_specification_ids[role_index],
            "attested_specification_id",
        )
    except ValueError:
        return (
            "CALIBRATION_EXECUTION_ATTESTATION_PAIR_MISMATCH",
            "expected enclosing pair is not an exact Stage-2E identity pair",
        )
    try:
        carried_specification_id = _exact_h64(
            execution_specification_id,
            "execution_specification_id",
        )
        specification_differs = carried_specification_id != expected_specification_id
    except ValueError:
        specification_differs = True
    try:
        carried_attestation_id = _exact_h64(
            executor_attestation_id,
            "executor_attestation_id",
        )
        attestation_differs = carried_attestation_id != expected_attestation_id
    except ValueError:
        attestation_differs = True
    if specification_differs and not attestation_differs:
        return (
            "CALIBRATION_EXECUTION_SPECIFICATION_MISMATCH",
            "execution specification differs while attestation matches",
        )
    if not specification_differs and attestation_differs:
        return (
            "CALIBRATION_EXECUTOR_ATTESTATION_MISMATCH",
            "executor attestation differs while specification matches",
        )
    if (
        specification_differs
        or attestation_differs
        or attested_specification_ids[role_index] != expected_specification_id
    ):
        return (
            "CALIBRATION_EXECUTION_ATTESTATION_PAIR_MISMATCH",
            "named identities do not form the exact enclosing pair",
        )
    return None


def _predicate_3o_1_1(
    selection: _SelectionEvidence,
) -> _PredicateFailure | None:
    from research_decision_engine.benchmarks.broader_calibration_history import (
        CalibrationHistorySelection as _CalibrationHistorySelection,
    )
    from research_decision_engine.benchmarks.broader_oracle import (
        _parse_calibration_candidate,
    )

    (
        _role,
        _position,
        world_id,
        _seed,
        comparison_group_id,
        _calibration_namespace,
        _calibration_prefix_id,
        _execution_specification_id,
        _executor_attestation_id,
        _study_occurrences,
        ordered_candidate_pairs,
        ordered_candidate_pair_projections,
        ordered_candidate_pair_ids,
        _ordered_replication_ids,
        _replication_ranks,
        _ordered_source_effect_ids,
        selector_result,
        _ordered_source_effects,
        _strict_chronology,
        _carried_strict_chronology_id,
    ) = selection
    if (
        type(selector_result) is not _CalibrationHistorySelection
        or type(ordered_candidate_pairs) is not tuple
        or len(ordered_candidate_pairs) != 5
        or type(selector_result.source_candidate_pairs) is not tuple
        or len(selector_result.source_candidate_pairs) != 5
        or type(ordered_candidate_pair_projections) is not tuple
        or len(ordered_candidate_pair_projections) != 5
        or type(ordered_candidate_pair_ids) is not tuple
        or len(ordered_candidate_pair_ids) != 5
    ):
        return _pair_failure("candidate-pair counts or selector sequence differ")
    for pair_index in range(5):
        pair = ordered_candidate_pairs[pair_index]
        selector_pair = selector_result.source_candidate_pairs[pair_index]
        if (
            type(pair) is not tuple
            or len(pair) != 2
            or type(selector_pair) is not tuple
            or len(selector_pair) != 2
        ):
            return _pair_failure(f"pair[{pair_index}] is not an exact ordered pair")
        adam_candidate_id, sgd_candidate_id = pair
        selector_adam_candidate_id, selector_sgd_candidate_id = selector_pair
        try:
            _exact_id(adam_candidate_id, "adam_candidate_id")
            _exact_id(sgd_candidate_id, "sgd_candidate_id")
            _exact_id(selector_adam_candidate_id, "selector_adam_candidate_id")
            _exact_id(selector_sgd_candidate_id, "selector_sgd_candidate_id")
            adam_parsed = _parse_calibration_candidate(adam_candidate_id)
            sgd_parsed = _parse_calibration_candidate(sgd_candidate_id)
        except (AttributeError, TypeError, ValueError):
            return _pair_failure(f"pair[{pair_index}] candidate parsing failed")
        replication_rank = pair_index + 1
        group_index = _group_index(comparison_group_id)
        if group_index is None:
            return _pair_failure("comparison group is outside the frozen group order")
        expected_adam = f"cal-{group_index:02d}-adam-r{replication_rank:04d}"
        expected_sgd = f"cal-{group_index:02d}-sgd-r{replication_rank:04d}"
        expected_replication_id = f"calibration-{group_index:02d}-r{replication_rank:04d}"
        if (
            adam_candidate_id != expected_adam
            or sgd_candidate_id != expected_sgd
            or selector_pair != pair
            or adam_parsed != (comparison_group_id, _PAIR_ARM_ORDER[0], expected_replication_id)
            or sgd_parsed != (comparison_group_id, _PAIR_ARM_ORDER[1], expected_replication_id)
        ):
            return _pair_failure(
                f"pair[{pair_index}] group, arm, replication, or canonical ID differs"
            )
        try:
            expected_projection = CalibrationCandidatePairProjection(
                adam_candidate_id=adam_candidate_id,
                comparison_group_id=comparison_group_id,
                replication_id=expected_replication_id,
                schema_version=_CANDIDATE_PAIR_SCHEMA,
                sgd_candidate_id=sgd_candidate_id,
                world_id=world_id,
            )
            carried_projection = ordered_candidate_pair_projections[pair_index]
            carried_mapping = _calibration_candidate_pair_mapping(carried_projection)
            decoded = _decode_calibration_candidate_pair_projection(carried_mapping)
        except ValueError:
            return _pair_failure(f"pair[{pair_index}] projection is malformed")
        if decoded != carried_projection or carried_projection != expected_projection:
            return _pair_failure(f"pair[{pair_index}] projection differs")
        try:
            carried_id = _exact_h64(
                ordered_candidate_pair_ids[pair_index],
                "ordered_candidate_pair_id",
            )
            expected_id = calibration_candidate_pair_id(expected_projection)
        except ValueError:
            return _pair_failure(f"pair[{pair_index}] identity is malformed")
        if carried_id != expected_id:
            return _pair_failure(f"pair[{pair_index}] identity differs")
    return None


def _predicate_3o_1_2(
    selection: _SelectionEvidence,
) -> _PredicateFailure | None:
    from research_decision_engine.benchmarks.broader_calibration_history import (
        CalibrationHistorySelection as _CalibrationHistorySelection,
    )

    (
        _role,
        _position,
        _world_id,
        _seed,
        _comparison_group_id,
        _calibration_namespace,
        _calibration_prefix_id,
        _execution_specification_id,
        _executor_attestation_id,
        study_occurrences,
        _ordered_candidate_pairs,
        _ordered_candidate_pair_projections,
        _ordered_candidate_pair_ids,
        _ordered_replication_ids,
        _replication_ranks,
        _ordered_source_effect_ids,
        selector_result,
        _ordered_source_effects,
        _strict_chronology,
        _carried_strict_chronology_id,
    ) = selection
    if (
        _FROZEN_STUDY != _STUDY
        or type(study_occurrences) is not tuple
        or len(study_occurrences) != 3
        or type(selector_result) is not _CalibrationHistorySelection
    ):
        return _study_failure("study predecessor occurrences are malformed")
    authority_study, execution_study, smoke_study = study_occurrences
    if (
        type(authority_study) is not str
        or authority_study != _STUDY
        or type(execution_study) is not str
        or execution_study != _STUDY
        or type(selector_result.study_id) is not str
        or selector_result.study_id != _STUDY
        or type(smoke_study) is not str
        or smoke_study != _STUDY
    ):
        return _study_failure("authority, execution, selector, or smoke study differs")
    return None


def _predicate_3o_1_3(
    selection: _SelectionEvidence,
    canonical_index: int,
) -> _PredicateFailure | None:
    from research_decision_engine.benchmarks.broader_calibration_history import (
        CalibrationHistorySelection as _CalibrationHistorySelection,
    )
    from research_decision_engine.benchmarks.broader_oracle import (
        CALIBRATION_NAMESPACE as _FROZEN_CALIBRATION_NAMESPACE,
    )

    (
        role,
        position,
        world_id,
        seed,
        comparison_group_id,
        calibration_namespace,
        _calibration_prefix_id,
        _execution_specification_id,
        _executor_attestation_id,
        _study_occurrences,
        _ordered_candidate_pairs,
        ordered_candidate_pair_projections,
        _ordered_candidate_pair_ids,
        _ordered_replication_ids,
        _replication_ranks,
        _ordered_source_effect_ids,
        selector_result,
        _ordered_source_effects,
        _strict_chronology,
        _carried_strict_chronology_id,
    ) = selection
    if (
        _FROZEN_CALIBRATION_NAMESPACE != _CALIBRATION_NAMESPACE
        or type(selector_result) is not _CalibrationHistorySelection
        or type(calibration_namespace) is not str
        or calibration_namespace != _CALIBRATION_NAMESPACE
        or type(selector_result.namespace) is not str
        or selector_result.namespace != _CALIBRATION_NAMESPACE
    ):
        return _scope_failure("calibration namespace differs")
    if (
        type(comparison_group_id) is not str
        or type(selector_result.comparison_group_id) is not str
        or selector_result.comparison_group_id != comparison_group_id
        or type(selector_result.target_comparison_group_id) is not str
        or selector_result.target_comparison_group_id != comparison_group_id
        or type(ordered_candidate_pair_projections) is not tuple
        or len(ordered_candidate_pair_projections) != 5
        or type(selector_result.effects) is not tuple
        or len(selector_result.effects) != 5
    ):
        return _scope_failure("comparison-group scope is malformed")
    for pair_index in range(5):
        pair_projection = ordered_candidate_pair_projections[pair_index]
        if (
            type(pair_projection) is not CalibrationCandidatePairProjection
            or pair_projection.comparison_group_id != comparison_group_id
        ):
            return _scope_failure(f"candidate pair[{pair_index}] comparison group differs")
    for effect_index in range(5):
        effect = selector_result.effects[effect_index]
        if (
            type(effect) is not _MatchedEffectObservation
            or type(effect.comparison_group_id) is not str
            or effect.comparison_group_id != comparison_group_id
        ):
            return _scope_failure(f"source effect[{effect_index}] comparison group differs")
    if (
        type(seed) is not int
        or type(selector_result.seed) is not int
        or selector_result.seed != seed
    ):
        return _scope_failure("execution or selector seed differs")
    if (
        type(world_id) is not str
        or type(selector_result.world_id) is not str
        or selector_result.world_id != world_id
    ):
        return _scope_failure("execution or selector world differs")
    for pair_index in range(5):
        if ordered_candidate_pair_projections[pair_index].world_id != world_id:
            return _scope_failure(f"candidate pair[{pair_index}] world differs")
    for effect_index in range(5):
        effect = selector_result.effects[effect_index]
        if type(effect) is not _MatchedEffectObservation:
            return _scope_failure(f"source effect[{effect_index}] is malformed")
        details = effect.provenance.details
        found_world: str | None = None
        if type(details) is tuple:
            for pair in details:
                if (
                    type(pair) is tuple
                    and len(pair) == 2
                    and pair[0] == "world_id"
                    and type(pair[1]) is str
                ):
                    found_world = pair[1] if found_world is None else ""
        if found_world != world_id:
            return _scope_failure(f"source effect[{effect_index}] world differs")
    if (
        canonical_index >= len(_CANONICAL_SELECTION_COORDINATES)
        or type(position) is not int
        or position != canonical_index
        or (role, world_id, seed, comparison_group_id)
        != _CANONICAL_SELECTION_COORDINATES[canonical_index]
    ):
        return _scope_failure("canonical role/world/seed/group position differs")
    return None


def _predicate_3o_1_4(
    selection: _SelectionEvidence,
) -> _PredicateFailure | None:
    from research_decision_engine.benchmarks.broader_calibration_history import (
        CalibrationHistorySelection as _CalibrationHistorySelection,
    )
    from research_decision_engine.benchmarks.broader_oracle import (
        RevealedObservation as _RevealedObservation,
    )

    (
        _role,
        _position,
        _world_id,
        _seed,
        _comparison_group_id,
        _calibration_namespace,
        _calibration_prefix_id,
        _execution_specification_id,
        _executor_attestation_id,
        _study_occurrences,
        _ordered_candidate_pairs,
        ordered_candidate_pair_projections,
        _ordered_candidate_pair_ids,
        ordered_replication_ids,
        replication_ranks,
        _ordered_source_effect_ids,
        selector_result,
        _ordered_source_effects,
        _strict_chronology,
        _carried_strict_chronology_id,
    ) = selection
    if (
        type(selector_result) is not _CalibrationHistorySelection
        or type(ordered_replication_ids) is not tuple
        or len(ordered_replication_ids) != 5
        or type(selector_result.source_replication_ids) is not tuple
        or len(selector_result.source_replication_ids) != 5
        or type(replication_ranks) is not tuple
        or len(replication_ranks) != 5
        or type(ordered_candidate_pair_projections) is not tuple
        or len(ordered_candidate_pair_projections) != 5
        or type(selector_result.observations) is not tuple
        or len(selector_result.observations) != 10
        or type(selector_result.effects) is not tuple
        or len(selector_result.effects) != 5
    ):
        return _replication_failure("replication counts or selector sequence differ")
    for pair_index in range(5):
        rank = replication_ranks[pair_index]
        if type(rank) is not int or rank != _REPLICATIONS[pair_index]:
            return _replication_failure(
                f"replication rank[{pair_index}] is not exact integer {pair_index + 1}"
            )
        replication_id = ordered_replication_ids[pair_index]
        selector_replication_id = selector_result.source_replication_ids[pair_index]
        try:
            _exact_id(replication_id, "ordered_replication_id")
            _exact_id(selector_replication_id, "selector_replication_id")
        except ValueError:
            return _replication_failure(f"replication ID[{pair_index}] is not an exact ID")
        if replication_id != selector_replication_id:
            return _replication_failure(f"replication ID occurrence[{pair_index}] differs")
        pair_projection = ordered_candidate_pair_projections[pair_index]
        adam_observation = selector_result.observations[pair_index * 2]
        sgd_observation = selector_result.observations[pair_index * 2 + 1]
        selector_effect = selector_result.effects[pair_index]
        if (
            type(pair_projection) is not CalibrationCandidatePairProjection
            or pair_projection.replication_id != replication_id
            or type(adam_observation) is not _RevealedObservation
            or type(adam_observation.replication_id) is not str
            or adam_observation.replication_id != replication_id
            or type(sgd_observation) is not _RevealedObservation
            or type(sgd_observation.replication_id) is not str
            or sgd_observation.replication_id != replication_id
            or _effect_replication_id(selector_effect) != replication_id
        ):
            return _replication_failure(
                f"pair/observation/effect replication[{pair_index}] differs"
            )
    return None


def _predicate_3o_1_5(
    selection: _SelectionEvidence,
) -> _PredicateFailure | None:
    from research_decision_engine.benchmarks.broader_calibration_history import (
        CalibrationHistorySelection as _CalibrationHistorySelection,
    )
    from research_decision_engine.benchmarks.broader_calibration_history import (
        expected_calibration_effect as _expected_calibration_effect,
    )
    from research_decision_engine.benchmarks.broader_oracle import (
        RevealedObservation as _RevealedObservation,
    )
    from research_decision_engine.benchmarks.broader_returned_run import (
        decode_run_matched_effect_projection as _decode_run_matched_effect_projection,
    )

    (
        _role,
        _position,
        world_id,
        _seed,
        comparison_group_id,
        _calibration_namespace,
        calibration_prefix_id,
        _execution_specification_id,
        _executor_attestation_id,
        _study_occurrences,
        _ordered_candidate_pairs,
        _ordered_candidate_pair_projections,
        _ordered_candidate_pair_ids,
        _ordered_replication_ids,
        _replication_ranks,
        ordered_source_effect_ids,
        selector_result,
        ordered_source_effects,
        _strict_chronology,
        _carried_strict_chronology_id,
    ) = selection
    if (
        type(selector_result) is not _CalibrationHistorySelection
        or type(calibration_prefix_id) is not str
        or type(ordered_source_effect_ids) is not tuple
        or len(ordered_source_effect_ids) != 5
        or type(ordered_source_effects) is not tuple
        or len(ordered_source_effects) != 5
        or type(selector_result.source_effect_ids) is not tuple
        or len(selector_result.source_effect_ids) != 5
        or type(selector_result.source_effect_payload_sha256) is not tuple
        or len(selector_result.source_effect_payload_sha256) != 5
        or type(selector_result.effect_values) is not tuple
        or len(selector_result.effect_values) != 5
        or type(selector_result.effects) is not tuple
        or len(selector_result.effects) != 5
        or type(selector_result.observations) is not tuple
        or len(selector_result.observations) != 10
    ):
        return _effect_failure("source-effect counts are not exactly five")
    group_index = _group_index(comparison_group_id)
    if group_index is None:
        return _effect_failure("comparison group is outside the frozen group order")
    for effect_index in range(5):
        effect_id = ordered_source_effect_ids[effect_index]
        try:
            _exact_id(effect_id, "ordered_source_effect_id")
        except ValueError:
            return _effect_failure(f"source effect ID[{effect_index}] is malformed")
        if effect_id in ordered_source_effect_ids[:effect_index]:
            return _effect_failure(f"source effect ID[{effect_index}] is duplicated")
        record = ordered_source_effects[effect_index]
        if type(record) is not tuple or len(record) != 4:
            return _effect_failure(f"source effect[{effect_index}] record is malformed")
        (
            record_effect_id,
            payload_bytes,
            payload_sha256,
            carried_projection,
        ) = record
        selector_effect_id = selector_result.source_effect_ids[effect_index]
        try:
            _exact_id(record_effect_id, "source_effect.effect_id")
            _exact_id(selector_effect_id, "selector.source_effect_id")
        except ValueError:
            return _effect_failure(f"source effect ID occurrence[{effect_index}] is malformed")
        if effect_id != record_effect_id or effect_id != selector_effect_id:
            return _effect_failure(f"source effect ID occurrence[{effect_index}] differs")
        if (
            type(payload_bytes) is not bytes
            or len(payload_bytes) < 1
            or payload_bytes[-1] != 10
            or len(payload_bytes) > 1
            and payload_bytes[-2] == 10
        ):
            return _effect_failure(
                f"source effect payload[{effect_index}] lacks exactly one final LF"
            )
        adam_observation = selector_result.observations[effect_index * 2]
        sgd_observation = selector_result.observations[effect_index * 2 + 1]
        if (
            type(adam_observation) is not _RevealedObservation
            or type(sgd_observation) is not _RevealedObservation
            or type(adam_observation.revealed_observation) is not float
            or type(sgd_observation.revealed_observation) is not float
        ):
            return _effect_failure(
                f"source observations[{effect_index}] are not exact binary64 values"
            )
        try:
            observed_effect = round(
                adam_observation.revealed_observation - sgd_observation.revealed_observation,
                12,
            )
            expected_effect = _expected_calibration_effect(
                prefix_id=calibration_prefix_id,
                world_id=world_id,
                comparison_group_id=comparison_group_id,
                group_index=group_index,
                replication_index=effect_index + 1,
                observed_effect=observed_effect,
            )
            expected_payload = _canonical_json_bytes(
                expected_effect.to_dict(),
                final_lf=True,
            )
        except (AttributeError, TypeError, ValueError):
            return _effect_failure(f"source effect[{effect_index}] canonical reconstruction failed")
        if payload_bytes != expected_payload:
            return _effect_failure(f"source effect payload bytes[{effect_index}] differ")
        try:
            recomputed_digest = _effect_payload_sha256(expected_effect)
            _exact_h64(payload_sha256, "source_effect.effect_payload_sha256")
            _exact_h64(
                selector_result.source_effect_payload_sha256[effect_index],
                "selector.source_effect_payload_sha256",
            )
        except (AttributeError, TypeError, ValueError):
            return _effect_failure(f"source effect raw digest[{effect_index}] is malformed")
        if (
            payload_sha256 != recomputed_digest
            or selector_result.source_effect_payload_sha256[effect_index] != recomputed_digest
        ):
            return _effect_failure(f"source effect raw digest[{effect_index}] differs")
        selector_effect = selector_result.effects[effect_index]
        try:
            decoded_projection = _decode_run_matched_effect_projection(
                _effect_projection_mapping(carried_projection)
            )
        except (AttributeError, TypeError, ValueError):
            return _effect_failure(f"source effect projection[{effect_index}] differs")
        if (
            decoded_projection != carried_projection
            or not _projection_matches_effect(decoded_projection, expected_effect)
            or type(selector_effect) is not _MatchedEffectObservation
            or selector_effect != expected_effect
        ):
            return _effect_failure(f"source effect projection[{effect_index}] differs")
        if (
            effect_id != decoded_projection.effect_id
            or record_effect_id != decoded_projection.effect_id
            or selector_effect_id != decoded_projection.effect_id
        ):
            return _effect_failure(f"source effect ID occurrence[{effect_index}] differs")
        if type(selector_result.effect_values[effect_index]) is not float:
            return _effect_failure(f"source effect value[{effect_index}] is not exact F64")
        try:
            expected_f64 = _f64(expected_effect.observed_effect)
            selector_f64 = _f64(selector_result.effect_values[effect_index])
        except (TypeError, ValueError):
            return _effect_failure(f"source effect value[{effect_index}] is not exact F64")
        if decoded_projection.observed_effect != expected_f64 or selector_f64 != expected_f64:
            return _effect_failure(f"source effect value[{effect_index}] differs")
    return None


def _predicate_3o_1_6(
    selection: _SelectionEvidence,
) -> _PredicateFailure | None:
    from research_decision_engine.benchmarks.broader_calibration_history import (
        CALIBRATION_SOURCE_SEQUENCE_CUTOFF as _FROZEN_SOURCE_SEQUENCE_CUTOFF,
    )
    from research_decision_engine.benchmarks.broader_calibration_history import (
        CalibrationHistorySelection as _CalibrationHistorySelection,
    )
    from research_decision_engine.benchmarks.broader_returned_run import (
        RunMatchedEffectProjection as _RunMatchedEffectProjection,
    )

    (
        _role,
        _position,
        _world_id,
        _seed,
        _comparison_group_id,
        _calibration_namespace,
        _calibration_prefix_id,
        _execution_specification_id,
        _executor_attestation_id,
        _study_occurrences,
        _ordered_candidate_pairs,
        _ordered_candidate_pair_projections,
        _ordered_candidate_pair_ids,
        _ordered_replication_ids,
        _replication_ranks,
        _ordered_source_effect_ids,
        selector_result,
        ordered_source_effects,
        strict_chronology,
        carried_strict_chronology_id,
    ) = selection
    if type(strict_chronology) is not StrictChronologyProjection:
        return _chronology_failure("chronology projection type differs")
    if strict_chronology.current_effect_excluded is not True:
        return _chronology_failure("current effect exclusion differs")
    if strict_chronology.current_observation_excluded is not True:
        return _chronology_failure("current observation exclusion differs")
    if (
        type(strict_chronology.effect_available_sequences) is not tuple
        or strict_chronology.effect_available_sequences != (0, 0, 0, 0, 0)
        or type(strict_chronology.effect_available_sequences[0]) is not int
        or type(strict_chronology.effect_available_sequences[1]) is not int
        or type(strict_chronology.effect_available_sequences[2]) is not int
        or type(strict_chronology.effect_available_sequences[3]) is not int
        or type(strict_chronology.effect_available_sequences[4]) is not int
    ):
        return _chronology_failure("effect available-sequence tuple differs")
    if strict_chronology.future_history_excluded is not True:
        return _chronology_failure("future-history exclusion differs")
    if (
        type(strict_chronology.schema_version) is not str
        or strict_chronology.schema_version != _STRICT_CHRONOLOGY_SCHEMA
    ):
        return _chronology_failure("chronology schema differs")
    if (
        type(strict_chronology.source_sequence_cutoff) is not int
        or strict_chronology.source_sequence_cutoff != 1
    ):
        return _chronology_failure("source-sequence cutoff differs")
    if (
        type(selector_result) is not _CalibrationHistorySelection
        or type(ordered_source_effects) is not tuple
        or len(ordered_source_effects) != 5
    ):
        return _chronology_failure("chronology predecessors are malformed")
    for effect_index in range(5):
        record = ordered_source_effects[effect_index]
        if (
            type(record) is not tuple
            or len(record) != 4
            or type(record[3]) is not _RunMatchedEffectProjection
        ):
            return _chronology_failure(
                f"source effect[{effect_index}] chronology carrier is malformed"
            )
    sequences: tuple[int, int, int, int, int] = (
        ordered_source_effects[0][3].available_sequence,
        ordered_source_effects[1][3].available_sequence,
        ordered_source_effects[2][3].available_sequence,
        ordered_source_effects[3][3].available_sequence,
        ordered_source_effects[4][3].available_sequence,
    )
    if (
        type(selector_result.current_effect_excluded) is not bool
        or selector_result.current_effect_excluded is not True
        or type(selector_result.current_observation_excluded) is not bool
        or selector_result.current_observation_excluded is not True
        or type(selector_result.future_history_excluded) is not bool
        or selector_result.future_history_excluded is not True
        or type(selector_result.source_sequence_cutoff) is not int
        or selector_result.source_sequence_cutoff != _SOURCE_SEQUENCE_CUTOFF
        or _FROZEN_SOURCE_SEQUENCE_CUTOFF != _SOURCE_SEQUENCE_CUTOFF
        or strict_chronology.effect_available_sequences != sequences
    ):
        return _chronology_failure("chronology field or source-effect relation differs")
    try:
        carried_id = _exact_h64(
            carried_strict_chronology_id,
            "strict_chronology_id",
        )
        expected_id = strict_chronology_id(strict_chronology)
    except ValueError:
        return _chronology_failure("chronology identity is malformed")
    if carried_id != expected_id:
        return _chronology_failure("chronology identity differs")
    return None


def _outcome(
    failure: _PredicateFailure,
    predicate_index: int,
    selection_index: int,
    counts: _PredicateCounts,
) -> _ValidationOutcome:
    return (
        (
            failure[0],
            _PREDICATE_PATHS[predicate_index],
            selection_index,
            _coordinate_detail(selection_index, failure[1]),
        ),
        counts,
    )


def _validate_stage2f_p1(
    *,
    selections: tuple[_SelectionEvidence, ...],
    expected_execution_attestation_pairs: _ExecutionAttestationPairs,
    attested_execution_specification_ids: _AttestedSpecificationIds,
) -> _ValidationOutcome:
    """Validate frozen 3o.1 in predicate-family-major order.

    The returned count tuple records attempted selections for predicates
    3o.1.0 through 3o.1.6.  It is deterministic test evidence for the strict
    stop boundary and is not a persisted protocol record.
    """

    failure: _PredicateFailure | None
    if type(selections) is not tuple or len(selections) != _CANONICAL_SELECTION_COUNT:
        failure = _scope_failure("canonical selection count is not exactly 318")
        return _outcome(failure, 3, 0, (0, 0, 0, 0, 0, 0, 0))
    count_0 = 0
    for index in range(_CANONICAL_SELECTION_COUNT):
        count_0 += 1
        if not _selection_shape(selections[index]):
            failure = (
                "CALIBRATION_EXECUTION_ATTESTATION_PAIR_MISMATCH",
                "selection input is not the exact immutable P1 tuple",
            )
            return _outcome(failure, 0, index, (count_0, 0, 0, 0, 0, 0, 0))
        failure = _predicate_3o_1_0(
            selections[index],
            expected_execution_attestation_pairs,
            attested_execution_specification_ids,
        )
        if failure is not None:
            return _outcome(failure, 0, index, (count_0, 0, 0, 0, 0, 0, 0))

    count_1 = 0
    for index in range(_CANONICAL_SELECTION_COUNT):
        count_1 += 1
        failure = _predicate_3o_1_1(selections[index])
        if failure is not None:
            return _outcome(
                failure,
                1,
                index,
                (count_0, count_1, 0, 0, 0, 0, 0),
            )

    count_2 = 0
    for index in range(_CANONICAL_SELECTION_COUNT):
        count_2 += 1
        failure = _predicate_3o_1_2(selections[index])
        if failure is not None:
            return _outcome(
                failure,
                2,
                index,
                (count_0, count_1, count_2, 0, 0, 0, 0),
            )

    count_3 = 0
    for index in range(_CANONICAL_SELECTION_COUNT):
        count_3 += 1
        failure = _predicate_3o_1_3(selections[index], index)
        if failure is not None:
            return _outcome(
                failure,
                3,
                index,
                (count_0, count_1, count_2, count_3, 0, 0, 0),
            )

    count_4 = 0
    for index in range(_CANONICAL_SELECTION_COUNT):
        count_4 += 1
        failure = _predicate_3o_1_4(selections[index])
        if failure is not None:
            return _outcome(
                failure,
                4,
                index,
                (count_0, count_1, count_2, count_3, count_4, 0, 0),
            )

    count_5 = 0
    for index in range(_CANONICAL_SELECTION_COUNT):
        count_5 += 1
        failure = _predicate_3o_1_5(selections[index])
        if failure is not None:
            return _outcome(
                failure,
                5,
                index,
                (count_0, count_1, count_2, count_3, count_4, count_5, 0),
            )

    count_6 = 0
    for index in range(_CANONICAL_SELECTION_COUNT):
        count_6 += 1
        failure = _predicate_3o_1_6(selections[index])
        if failure is not None:
            return _outcome(
                failure,
                6,
                index,
                (
                    count_0,
                    count_1,
                    count_2,
                    count_3,
                    count_4,
                    count_5,
                    count_6,
                ),
            )
    return (
        None,
        (
            count_0,
            count_1,
            count_2,
            count_3,
            count_4,
            count_5,
            count_6,
        ),
    )


def _oracle_binding_failure(detail: str) -> _PredicateFailure:
    return "CALIBRATION_ORACLE_BINDING_MISMATCH", detail


def _oracle_key_failure(detail: str) -> _PredicateFailure:
    return "CALIBRATION_ORACLE_KEY_ID_MISMATCH", detail


def _outcome_failure(detail: str) -> _PredicateFailure:
    return "CALIBRATION_OUTCOME_DIGEST_MISMATCH", detail


def _source_observation_failure(detail: str) -> _PredicateFailure:
    return "CALIBRATION_SOURCE_OBSERVATION_ID_MISMATCH", detail


def _first_source_mismatch(
    projection: object,
    expected: CalibrationSourceObservationProjection,
) -> str | None:
    projection = _require_exact_source_observation_object(projection)
    if type(projection.candidate_id) is not str or projection.candidate_id != expected.candidate_id:
        return "candidate_id"
    if (
        type(projection.comparison_group_id) is not str
        or projection.comparison_group_id != expected.comparison_group_id
    ):
        return "comparison_group_id"
    if type(projection.digest) is not str or projection.digest != expected.digest:
        return "digest"
    if (
        type(projection.intervention_arm) is not str
        or projection.intervention_arm != expected.intervention_arm
    ):
        return "intervention_arm"
    try:
        key_fields = _source_key_fields(projection.key_fields)
    except ValueError:
        return "key_fields"
    if key_fields != expected.key_fields:
        return "key_fields"
    if type(projection.namespace) is not str or projection.namespace != expected.namespace:
        return "namespace"
    if (
        type(projection.oracle_key_id) is not str
        or projection.oracle_key_id != expected.oracle_key_id
    ):
        return "oracle_key_id"
    if (
        type(projection.outcome_digest) is not str
        or projection.outcome_digest != expected.outcome_digest
    ):
        return "outcome_digest"
    if (
        type(projection.replication_id) is not str
        or projection.replication_id != expected.replication_id
    ):
        return "replication_id"
    if (
        type(projection.revealed_observation) is not str
        or projection.revealed_observation != expected.revealed_observation
    ):
        return "revealed_observation"
    if (
        type(projection.schema_version) is not str
        or projection.schema_version != expected.schema_version
    ):
        return "schema_version"
    if type(projection.seed) is not int or projection.seed != expected.seed:
        return "seed"
    if (
        type(projection.serialized_key_hex) is not str
        or projection.serialized_key_hex != expected.serialized_key_hex
    ):
        return "serialized_key_hex"
    if type(projection.u) is not str or projection.u != expected.u:
        return "u"
    if type(projection.world_id) is not str or projection.world_id != expected.world_id:
        return "world_id"
    if type(projection.z) is not str or projection.z != expected.z:
        return "z"
    return None


def _p2_selection_shape(value: object) -> bool:
    return type(value) is tuple and len(value) == 2


def _oracle_predecessor_shape(value: object) -> bool:
    return type(value) is tuple and len(value) == 11


def _exact_frozen_world(
    value: object,
    world_id: str,
    ordered_candidate_pairs: tuple[tuple[str, str], ...],
) -> _BenchmarkWorld:
    """Reject capability-bearing or malformed substitutes before hidden helpers."""

    if type(value) is not _BenchmarkWorld:
        _reject("oracle_predecessor.world", "expected exact frozen BenchmarkWorld")
    try:
        public = value.public
        hidden = value.hidden
    except AttributeError:
        _reject("oracle_predecessor.world", "frozen world slots are incomplete")
    if type(public) is not _PublicWorldDefinition or type(hidden) is not _HiddenWorldParameters:
        _reject("oracle_predecessor.world", "frozen world component type differs")
    try:
        public_sequences = (
            public.candidate_ids,
            public.initial_feasible_candidate_ids,
            public.setup_candidate_ids,
            public.comparison_group_ids,
            public.budget_ids,
        )
    except AttributeError:
        _reject("oracle_predecessor.world", "frozen world slots are incomplete")
    if (
        type(world_id) is not str
        or type(public.world_id) is not str
        or public.world_id != world_id
        or type(public.block) is not str
        or type(public.cost_catalog_id) is not str
        or type(public.depth) is not int
        or public.depth not in (2, 3)
    ):
        _reject("oracle_predecessor.world", "public frozen-world relation differs")
    for sequence in public_sequences:
        if type(sequence) is not tuple:
            _reject("oracle_predecessor.world", "public frozen-world sequence type differs")
        for item in sequence:
            if type(item) is not str:
                _reject("oracle_predecessor.world", "public frozen-world item type differs")
    if public.comparison_group_ids != _GROUP_IDS or not public.candidate_ids:
        _reject("oracle_predecessor.world", "public frozen-world catalog differs")
    if type(ordered_candidate_pairs) is not tuple or len(ordered_candidate_pairs) != 5:
        _reject("oracle_predecessor.world", "P1 candidate-pair relation differs")
    if (
        type(hidden.scientific_hypothesis_id) is not str
        or type(hidden.effect_size) is not float
        or not 0.0 <= hidden.effect_size <= 1.0
        or type(hidden.group_sigmas) is not tuple
        or len(hidden.group_sigmas) != 3
    ):
        _reject("oracle_predecessor.world", "hidden frozen-world relation differs")
    for group_index in range(3):
        sigma_item = hidden.group_sigmas[group_index]
        if (
            type(sigma_item) is not tuple
            or len(sigma_item) != 2
            or type(sigma_item[0]) is not str
            or sigma_item[0] != _GROUP_IDS[group_index]
            or type(sigma_item[1]) is not float
            or not 0.0 < sigma_item[1] <= 1.0
        ):
            _reject("oracle_predecessor.world", "hidden frozen-world sigma relation differs")
    return value


def _matching_h64(left: object, right: object) -> bool:
    try:
        return _exact_h64(left, "oracle_predecessor") == _exact_h64(
            right,
            "oracle_predecessor",
        )
    except ValueError:
        return False


def _oracle_implementation(value: object) -> _OracleImplementationRelation | None:
    if (
        type(value) is not tuple
        or len(value) != 2
        or type(value[0]) is not str
        or value[0] != _ORACLE_NAMESPACE
        or not _matching_h64(value[1], value[1])
    ):
        return None
    return value


def _candidate_pair_scope(value: object) -> tuple[tuple[str, str], ...] | None:
    if type(value) is not tuple or len(value) != 5:
        return None
    for pair in value:
        if (
            type(pair) is not tuple
            or len(pair) != 2
            or type(pair[0]) is not str
            or type(pair[1]) is not str
        ):
            return None
    return value


def _replication_scope(value: object) -> tuple[str, ...] | None:
    if type(value) is not tuple or len(value) != 5:
        return None
    for replication_id in value:
        if type(replication_id) is not str:
            return None
    return value


def _predicate_3o_2_0(
    selection: _SelectionEvidence,
    p2_selection: _P2SelectionEvidence,
    expected_predecessor: _OraclePredecessor,
) -> _PredicateFailure | None:
    from research_decision_engine.benchmarks.broader_calibration_history import (
        CalibrationHistorySelection as _CalibrationHistorySelection,
    )
    from research_decision_engine.benchmarks.broader_oracle import (
        ORACLE_VERSION as _FROZEN_ORACLE_NAMESPACE,
    )

    if not _p2_selection_shape(p2_selection):
        return _oracle_binding_failure("P2 selection evidence is malformed")
    carried = p2_selection[0]
    if not _oracle_predecessor_shape(carried) or not _oracle_predecessor_shape(
        expected_predecessor
    ):
        return _oracle_binding_failure("Oracle predecessor relation is malformed")
    if not _matching_h64(carried[0], expected_predecessor[0]):
        return _oracle_binding_failure("current Oracle execution identity differs")
    if not _matching_h64(carried[1], expected_predecessor[1]):
        return _oracle_binding_failure("current Oracle binding identity differs")
    carried_implementation = _oracle_implementation(carried[2])
    expected_implementation = _oracle_implementation(expected_predecessor[2])
    if (
        carried_implementation is None
        or expected_implementation is None
        or carried_implementation != expected_implementation
        or _FROZEN_ORACLE_NAMESPACE != _ORACLE_NAMESPACE
    ):
        return _oracle_binding_failure("Oracle implementation relation differs")

    world_id, seed, comparison_group_id = selection[2], selection[3], selection[4]
    calibration_namespace, study_occurrences = selection[5], selection[9]
    ordered_candidate_pairs, ordered_replication_ids = selection[10], selection[13]
    selector_result = selection[16]
    if (
        type(carried[3]) is not str
        or carried[3] != _STUDY
        or type(expected_predecessor[3]) is not str
        or expected_predecessor[3] != _STUDY
        or type(study_occurrences) is not tuple
        or len(study_occurrences) != 3
        or type(selector_result) is not _CalibrationHistorySelection
        or selector_result.study_id != _STUDY
    ):
        return _oracle_binding_failure("Oracle predecessor study relation differs")
    if (
        type(carried[4]) is not str
        or carried[4] != _CALIBRATION_NAMESPACE
        or type(expected_predecessor[4]) is not str
        or expected_predecessor[4] != _CALIBRATION_NAMESPACE
        or type(calibration_namespace) is not str
        or calibration_namespace != _CALIBRATION_NAMESPACE
    ):
        return _oracle_binding_failure("Oracle predecessor namespace relation differs")
    for position, selected, expected_type, label in (
        (5, world_id, str, "world"),
        (6, seed, int, "seed"),
        (7, comparison_group_id, str, "comparison group"),
    ):
        if (
            type(selected) is not expected_type
            or type(carried[position]) is not expected_type
            or type(expected_predecessor[position]) is not expected_type
            or carried[position] != selected
            or expected_predecessor[position] != selected
        ):
            return _oracle_binding_failure(f"Oracle predecessor {label} relation differs")
    carried_pairs = _candidate_pair_scope(carried[8])
    expected_pairs = _candidate_pair_scope(expected_predecessor[8])
    selection_pairs = _candidate_pair_scope(ordered_candidate_pairs)
    if (
        carried_pairs is None
        or expected_pairs is None
        or selection_pairs is None
        or carried_pairs != expected_pairs
        or carried_pairs != selection_pairs
    ):
        return _oracle_binding_failure("Oracle predecessor candidate pairs differ")
    carried_replications = _replication_scope(carried[9])
    expected_replications = _replication_scope(expected_predecessor[9])
    selection_replications = _replication_scope(ordered_replication_ids)
    if (
        carried_replications is None
        or expected_replications is None
        or selection_replications is None
        or carried_replications != expected_replications
        or carried_replications != selection_replications
    ):
        return _oracle_binding_failure("Oracle predecessor replications differ")
    if carried[10] is not expected_predecessor[10]:
        return _oracle_binding_failure("Oracle predecessor frozen-world relation differs")
    try:
        _exact_frozen_world(
            expected_predecessor[10],
            world_id,
            ordered_candidate_pairs,
        )
    except (AttributeError, TypeError, ValueError):
        return _oracle_binding_failure("Oracle predecessor frozen-world relation differs")
    return None


def _source_evidence_at(
    p2_selection: _P2SelectionEvidence,
    observation_index: int,
) -> tuple[object, object] | None:
    if not _p2_selection_shape(p2_selection):
        return None
    source_observations = p2_selection[1]
    if type(source_observations) is not tuple or observation_index >= len(source_observations):
        return None
    evidence = source_observations[observation_index]
    if type(evidence) is not tuple or len(evidence) != 2:
        return None
    return evidence


def _require_exact_source_observation_object(
    value: object,
) -> CalibrationSourceObservationProjection:
    if type(value) is not CalibrationSourceObservationProjection:
        _reject(
            "source_observation",
            "expected exact CalibrationSourceObservationProjection",
        )
    return value


def _validate_source_observation_key_surface(
    value: object,
) -> tuple[CalibrationSourceObservationProjection, tuple[str, ...], str]:
    projection = _require_exact_source_observation_object(value)
    key_fields = _source_key_fields(projection.key_fields)
    oracle_key_id = _exact_oracle_key_id(
        projection.oracle_key_id,
        "source_observation.oracle_key_id",
    )
    return projection, key_fields, oracle_key_id


def _validate_source_observation_outcome_surface(
    value: object,
) -> tuple[CalibrationSourceObservationProjection, str, str]:
    projection = _require_exact_source_observation_object(value)
    revealed_observation = _exact_f64_string(
        projection.revealed_observation,
        "source_observation.revealed_observation",
    )
    outcome_digest = _exact_h64(
        projection.outcome_digest,
        "source_observation.outcome_digest",
    )
    return projection, revealed_observation, outcome_digest


def _validate_complete_source_observation_surface(
    value: object,
) -> dict[str, object]:
    projection = _require_exact_source_observation_object(value)
    mapping = _calibration_source_observation_mapping(projection)
    decoded = _decode_calibration_source_observation_projection(mapping)
    if decoded != projection:
        _reject("source_observation", "projection does not exactly reconstruct")
    return mapping


def _expected_source_coordinate(
    selection: _SelectionEvidence,
    observation_index: int,
) -> tuple[
    str,
    int,
    str,
    _Literal["adam", "sgd"],
    str,
    str,
    tuple[str, ...],
]:
    from research_decision_engine.benchmarks.broader_oracle import (
        _parse_calibration_candidate,
    )
    from research_decision_engine.benchmarks.broader_oracle import (
        calibration_key as _calibration_key,
    )

    world_id, seed, comparison_group_id = selection[2], selection[3], selection[4]
    ordered_candidate_pairs, ordered_replication_ids = selection[10], selection[13]
    pair_index, arm_index = observation_index // 2, observation_index % 2
    expected_arm: _Literal["adam", "sgd"] = "adam" if arm_index == 0 else "sgd"
    pair = ordered_candidate_pairs[pair_index]
    if type(pair) is not tuple or len(pair) != 2:
        _reject("source_observation", "validated P1 candidate pair is malformed")
    candidate_id, replication_id = pair[arm_index], ordered_replication_ids[pair_index]
    if (
        type(world_id) is not str
        or type(seed) is not int
        or type(comparison_group_id) is not str
        or type(candidate_id) is not str
        or type(replication_id) is not str
    ):
        _reject("source_observation", "validated P1 source coordinate is malformed")
    parsed = _parse_calibration_candidate(candidate_id)
    if parsed != (comparison_group_id, expected_arm, replication_id):
        _reject("source_observation", "validated P1 pair/arm/replication differs")
    key_fields = _calibration_key(
        world_id=world_id,
        seed=seed,
        comparison_group_id=comparison_group_id,
        intervention_arm=expected_arm,
        replication_id=replication_id,
        namespace=_CALIBRATION_NAMESPACE,
    )
    return (
        world_id,
        seed,
        comparison_group_id,
        expected_arm,
        candidate_id,
        replication_id,
        key_fields,
    )


def _predicate_3o_2_1(
    selection: _SelectionEvidence,
    p2_selection: _P2SelectionEvidence,
) -> _PredicateFailure | None:
    from research_decision_engine.benchmarks.broader_calibration_history import (
        CalibrationHistorySelection as _CalibrationHistorySelection,
    )

    if (
        not _p2_selection_shape(p2_selection)
        or type(p2_selection[1]) is not tuple
        or len(p2_selection[1]) != 10
    ):
        return _oracle_key_failure("ordered source-observation count is not exactly ten")
    selector_result = selection[16]
    if (
        type(selector_result) is not _CalibrationHistorySelection
        or type(selector_result.source_oracle_key_ids) is not tuple
        or len(selector_result.source_oracle_key_ids) != 10
    ):
        return _oracle_key_failure("selector source_oracle_key_ids count is not exactly ten")
    if (
        type(selector_result.source_observation_identities) is not tuple
        or len(selector_result.source_observation_identities) != 10
    ):
        return _oracle_key_failure(
            "selector source_observation_identities count is not exactly ten"
        )

    for observation_index in range(10):
        evidence = _source_evidence_at(p2_selection, observation_index)
        if evidence is None:
            return _oracle_key_failure(
                f"source observation[{observation_index}] occurrence is malformed"
            )
        try:
            projection, key_fields, projection_oracle_key_id = (
                _validate_source_observation_key_surface(evidence[0])
            )
        except (AttributeError, TypeError, ValueError):
            return _oracle_key_failure(
                f"source observation[{observation_index}] key surface is malformed"
            )
        try:
            expected_key_fields = _expected_source_coordinate(
                selection,
                observation_index,
            )[6]
        except (AttributeError, TypeError, ValueError):
            return _oracle_key_failure(
                f"source observation[{observation_index}] key reconstruction failed"
            )
        for field_index in range(8):
            if key_fields[field_index] != expected_key_fields[field_index]:
                return _oracle_key_failure(
                    f"source observation[{observation_index}] key_fields[{field_index}] differs"
                )
        selector_pair = selector_result.source_observation_identities[observation_index]
        if type(selector_pair) is not tuple or len(selector_pair) != 2:
            return _oracle_key_failure(
                f"selector source identity pair[{observation_index}] is malformed"
            )
        actual_oracle_key_ids: tuple[tuple[str, str], ...] = ()
        for label, occurrence in (
            ("projection", projection_oracle_key_id),
            ("selector", selector_result.source_oracle_key_ids[observation_index]),
            ("paired", selector_pair[0]),
        ):
            try:
                actual_oracle_key_id = _exact_oracle_key_id(
                    occurrence,
                    f"{label}.oracle_key_id",
                )
            except ValueError:
                return _oracle_key_failure(
                    f"source observation[{observation_index}] {label} Oracle key is malformed"
                )
            actual_oracle_key_ids = (
                *actual_oracle_key_ids,
                (label, actual_oracle_key_id),
            )
        try:
            expected_oracle_key_id = _oracle_key_id(  # type: ignore[no-untyped-call]
                expected_key_fields
            )
        except (AttributeError, TypeError, ValueError):
            return _oracle_key_failure(
                f"source observation[{observation_index}] Oracle key identity is malformed"
            )
        for label, actual_oracle_key_id in actual_oracle_key_ids:
            if actual_oracle_key_id != expected_oracle_key_id:
                return _oracle_key_failure(
                    f"source observation[{observation_index}] {label} Oracle key differs"
                )
    return None


def _expected_observation_f64(
    selection: _SelectionEvidence,
    observation_index: int,
    world: _BenchmarkWorld,
) -> str:
    from research_decision_engine.benchmarks.broader_oracle import (
        transform_key as _transform_key,
    )

    (
        _world_id,
        _seed,
        comparison_group_id,
        expected_arm,
        _candidate_id,
        _replication_id,
        key_fields,
    ) = _expected_source_coordinate(selection, observation_index)
    base_candidate_id = f"g{comparison_group_id[-2:]}-{expected_arm}-r1"
    transform = _transform_key(key_fields)
    observed = _hidden_arm_mean(
        world,
        base_candidate_id,
    ) + (
        _hidden_observation_sigma(
            world,
            base_candidate_id,
        )
        * transform.z
    )
    return _f64(observed)


def _predicate_3o_3_1(
    selection: _SelectionEvidence,
    p2_selection: _P2SelectionEvidence,
    expected_predecessor: _OraclePredecessor,
) -> _PredicateFailure | None:
    from research_decision_engine.benchmarks.broader_calibration_history import (
        CalibrationHistorySelection as _CalibrationHistorySelection,
    )

    selector_result = selection[16]
    if (
        type(selector_result) is not _CalibrationHistorySelection
        or type(selector_result.source_observation_identities) is not tuple
        or len(selector_result.source_observation_identities) != 10
        or not _p2_selection_shape(p2_selection)
        or type(p2_selection[1]) is not tuple
        or len(p2_selection[1]) != 10
        or not _oracle_predecessor_shape(expected_predecessor)
    ):
        return _outcome_failure("validated outcome predecessors are malformed")
    try:
        world = _exact_frozen_world(
            expected_predecessor[10],
            selection[2],
            selection[10],
        )
    except (AttributeError, TypeError, ValueError):
        return _outcome_failure("validated frozen-world predecessor is malformed")
    for observation_index in range(10):
        evidence = _source_evidence_at(p2_selection, observation_index)
        if evidence is None:
            return _outcome_failure(
                f"source observation[{observation_index}] occurrence is malformed"
            )
        try:
            projection, revealed_observation, projection_outcome_digest = (
                _validate_source_observation_outcome_surface(evidence[0])
            )
        except (AttributeError, TypeError, ValueError):
            return _outcome_failure(
                f"source observation[{observation_index}] outcome surface is malformed"
            )
        try:
            expected_f64 = _expected_observation_f64(
                selection,
                observation_index,
                world,
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            return _outcome_failure(
                f"source observation[{observation_index}] pure reconstruction failed"
            )
        if revealed_observation != expected_f64:
            return _outcome_failure(
                f"source observation[{observation_index}] F64 observation differs"
            )
        selector_pair = selector_result.source_observation_identities[observation_index]
        if type(selector_pair) is not tuple or len(selector_pair) != 2:
            return _outcome_failure(
                f"selector source identity pair[{observation_index}] is malformed"
            )
        try:
            expected_key_fields = _expected_source_coordinate(
                selection,
                observation_index,
            )[6]
            expected_oracle_key_id = _oracle_key_id(  # type: ignore[no-untyped-call]
                expected_key_fields
            )
            expected_digest = _outcome_digest(  # type: ignore[no-untyped-call]
                expected_oracle_key_id,
                expected_f64,
            )
        except (AttributeError, TypeError, ValueError):
            return _outcome_failure(
                f"source observation[{observation_index}] outcome digest is malformed"
            )
        for label, occurrence in (
            ("projection", projection_outcome_digest),
            ("selector", selector_pair[1]),
        ):
            try:
                actual_digest = _exact_h64(occurrence, f"{label}.outcome_digest")
            except ValueError:
                return _outcome_failure(
                    f"source observation[{observation_index}] {label} outcome digest is malformed"
                )
            if actual_digest != expected_digest:
                return _outcome_failure(
                    f"source observation[{observation_index}] {label} outcome digest differs"
                )
    return None


def _predicate_3o_4_1(
    selection: _SelectionEvidence,
    p2_selection: _P2SelectionEvidence,
    expected_predecessor: _OraclePredecessor,
) -> _PredicateFailure | None:
    from research_decision_engine.benchmarks.broader_oracle import (
        transform_key as _transform_key,
    )

    if not _p2_selection_shape(p2_selection):
        return _source_observation_failure("P2 selection evidence is malformed")
    source_observations = p2_selection[1]
    if (
        type(source_observations) is not tuple
        or len(source_observations) != 10
        or not _oracle_predecessor_shape(expected_predecessor)
    ):
        return _source_observation_failure("ordered source-observation count is not exactly ten")
    try:
        world = _exact_frozen_world(
            expected_predecessor[10],
            selection[2],
            selection[10],
        )
    except (AttributeError, TypeError, ValueError):
        return _source_observation_failure("validated frozen-world predecessor is malformed")
    identities: tuple[str, ...] = ()
    for observation_index in range(10):
        evidence = _source_evidence_at(p2_selection, observation_index)
        if evidence is None:
            return _source_observation_failure(
                f"source observation[{observation_index}] occurrence is malformed"
            )
        carried_identity = evidence[1]
        try:
            (
                world_id,
                seed,
                comparison_group_id,
                expected_arm,
                expected_candidate_id,
                expected_replication_id,
                expected_key_fields,
            ) = _expected_source_coordinate(selection, observation_index)
            transform = _transform_key(expected_key_fields)
            serialized_key_hex = _lower_hex_bytes(
                transform.serialized_key,
                "source_observation.serialized_key",
            )
            expected_oracle_key_id = _oracle_key_id(  # type: ignore[no-untyped-call]
                expected_key_fields
            )
            expected_f64 = _expected_observation_f64(
                selection,
                observation_index,
                world,
            )
            expected_outcome_digest = _outcome_digest(  # type: ignore[no-untyped-call]
                expected_oracle_key_id,
                expected_f64,
            )
            expected_projection = CalibrationSourceObservationProjection(
                candidate_id=expected_candidate_id,
                comparison_group_id=comparison_group_id,
                digest=transform.digest_hex,
                intervention_arm=expected_arm,
                key_fields=expected_key_fields,
                namespace=_CALIBRATION_NAMESPACE,
                oracle_key_id=expected_oracle_key_id,
                outcome_digest=expected_outcome_digest,
                replication_id=expected_replication_id,
                revealed_observation=expected_f64,
                schema_version=_SOURCE_OBSERVATION_SCHEMA,
                seed=seed,
                serialized_key_hex=serialized_key_hex,
                u=transform.u_string,
                world_id=world_id,
                z=transform.z_string,
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            return _source_observation_failure(
                f"source observation[{observation_index}] trusted reconstruction failed"
            )
        try:
            mismatch = _first_source_mismatch(evidence[0], expected_projection)
        except (AttributeError, TypeError, ValueError):
            return _source_observation_failure(
                f"source observation[{observation_index}] exact projection type differs"
            )
        if mismatch is not None:
            return _source_observation_failure(
                f"source observation[{observation_index}] {mismatch} differs"
            )
        projection = _require_exact_source_observation_object(evidence[0])
        try:
            _validate_complete_source_observation_surface(projection)
        except (AttributeError, TypeError, ValueError):
            return _source_observation_failure(
                f"source observation[{observation_index}] strict reconstruction failed"
            )
        try:
            carried_identity = _exact_h64(
                carried_identity,
                "source_observation_identity",
            )
            identity_matches = _source_observation_matches(
                projection,
                carried_identity,
            )
        except (AttributeError, TypeError, ValueError):
            return _source_observation_failure(
                f"source observation[{observation_index}] identity is malformed"
            )
        if not identity_matches:
            return _source_observation_failure(
                f"source observation[{observation_index}] identity differs"
            )
        identities = (*identities, carried_identity)
    for observation_index in range(10):
        for earlier_index in range(observation_index):
            if identities[observation_index] == identities[earlier_index]:
                return _source_observation_failure(
                    f"source observation identity[{observation_index}] is duplicated"
                )
    return None


def _p2_outcome(
    failure: _PredicateFailure,
    predicate_index: int,
    selection_index: int,
    p1_counts: _PredicateCounts,
    p2_counts: _P2PredicateCounts,
) -> _P2ValidationOutcome:
    return (
        (
            failure[0],
            _P2_PREDICATE_PATHS[predicate_index],
            selection_index,
            _coordinate_detail(selection_index, failure[1]),
        ),
        (*p1_counts, *p2_counts),
    )


def _validate_stage2f_p2(
    *,
    selections: tuple[_SelectionEvidence, ...],
    expected_execution_attestation_pairs: _ExecutionAttestationPairs,
    attested_execution_specification_ids: _AttestedSpecificationIds,
    p2_selections: tuple[_P2SelectionEvidence, ...],
    expected_predecessors: tuple[_OraclePredecessor, ...],
) -> _P2ValidationOutcome:
    """Validate frozen 3o.1 through 3o.4 in global family-major order."""

    p1_failure, p1_counts = _validate_stage2f_p1(
        selections=selections,
        expected_execution_attestation_pairs=expected_execution_attestation_pairs,
        attested_execution_specification_ids=attested_execution_specification_ids,
    )
    if p1_failure is not None:
        return p1_failure, (*p1_counts, 0, 0, 0, 0)
    if (
        type(p2_selections) is not tuple
        or len(p2_selections) != _CANONICAL_SELECTION_COUNT
        or type(expected_predecessors) is not tuple
        or len(expected_predecessors) != _CANONICAL_SELECTION_COUNT
    ):
        return _p2_outcome(
            _oracle_binding_failure(
                "canonical P2 selection or Oracle predecessor count is not exactly 318"
            ),
            0,
            0,
            p1_counts,
            (0, 0, 0, 0),
        )

    count_0 = 0
    for index in range(_CANONICAL_SELECTION_COUNT):
        count_0 += 1
        if failure := _predicate_3o_2_0(
            selections[index],
            p2_selections[index],
            expected_predecessors[index],
        ):
            return _p2_outcome(failure, 0, index, p1_counts, (count_0, 0, 0, 0))

    count_1 = 0
    for index in range(_CANONICAL_SELECTION_COUNT):
        count_1 += 1
        if failure := _predicate_3o_2_1(
            selections[index],
            p2_selections[index],
        ):
            return _p2_outcome(failure, 1, index, p1_counts, (count_0, count_1, 0, 0))

    count_2 = 0
    for index in range(_CANONICAL_SELECTION_COUNT):
        count_2 += 1
        if failure := _predicate_3o_3_1(
            selections[index],
            p2_selections[index],
            expected_predecessors[index],
        ):
            return _p2_outcome(failure, 2, index, p1_counts, (count_0, count_1, count_2, 0))

    count_3 = 0
    for index in range(_CANONICAL_SELECTION_COUNT):
        count_3 += 1
        if failure := _predicate_3o_4_1(
            selections[index],
            p2_selections[index],
            expected_predecessors[index],
        ):
            return _p2_outcome(failure, 3, index, p1_counts, (count_0, count_1, count_2, count_3))
    return None, (*p1_counts, count_0, count_1, count_2, count_3)


def _selector_result_failure(detail: str) -> _PredicateFailure:
    return "CALIBRATION_SELECTOR_RESULT_ID_MISMATCH", detail


def _first_effect_mismatch(
    actual: object,
    expected: _MatchedEffectObservation,
) -> str | None:
    if type(actual) is not _MatchedEffectObservation:
        return "type"
    if type(actual.effect_id) is not str or actual.effect_id != expected.effect_id:
        return "effect_id"
    if (
        type(actual.comparison_group_id) is not str
        or actual.comparison_group_id != expected.comparison_group_id
    ):
        return "comparison_group_id"
    if (
        type(actual.observed_effect) is not float
        or actual.observed_effect != expected.observed_effect
    ):
        return "observed_effect"
    if (
        type(actual.available_sequence) is not int
        or actual.available_sequence != expected.available_sequence
    ):
        return "available_sequence"
    if type(actual.source_kind) is not str or actual.source_kind != expected.source_kind:
        return "source_kind"
    if type(actual.source_ids) is not tuple or len(actual.source_ids) != 2:
        return "source_ids"
    for index in range(2):
        if (
            type(actual.source_ids[index]) is not str
            or actual.source_ids[index] != expected.source_ids[index]
        ):
            return f"source_ids[{index}]"
    if type(actual.created_at) is not str or actual.created_at != expected.created_at:
        return "created_at"
    actual_provenance = actual.provenance
    expected_provenance = expected.provenance
    if type(actual_provenance) is not type(expected_provenance):
        return "provenance.type"
    if (
        type(actual_provenance.method) is not str
        or actual_provenance.method != expected_provenance.method
    ):
        return "provenance.method"
    if (
        type(actual_provenance.version) is not str
        or actual_provenance.version != expected_provenance.version
    ):
        return "provenance.version"
    actual_details = actual_provenance.details
    expected_details = expected_provenance.details
    if type(actual_details) is not tuple or len(actual_details) != len(expected_details):
        return "provenance.details"
    for index in range(len(expected_details)):
        actual_pair = actual_details[index]
        expected_pair = expected_details[index]
        if type(actual_pair) is not tuple or len(actual_pair) != 2:
            return f"provenance.details[{index}]"
        if type(actual_pair[0]) is not str or actual_pair[0] != expected_pair[0]:
            return f"provenance.details[{index}][0]"
        if type(actual_pair[1]) is not type(expected_pair[1]):
            return f"provenance.details[{index}][1]"
        if actual_pair[1] != expected_pair[1]:
            return f"provenance.details[{index}][1]"
    return None


def _first_run_effect_mismatch(
    actual: object,
    expected: _MatchedEffectObservation,
) -> str | None:
    from research_decision_engine.benchmarks.broader_returned_run import (
        ProvenanceValueProjection as _ProvenanceValueProjection,
    )
    from research_decision_engine.benchmarks.broader_returned_run import (
        RunMatchedEffectProjection as _RunMatchedEffectProjection,
    )
    from research_decision_engine.benchmarks.broader_returned_run import (
        RunProvenanceProjection as _RunProvenanceProjection,
    )

    if type(actual) is not _RunMatchedEffectProjection:
        return "type"
    if type(actual.effect_id) is not str or actual.effect_id != expected.effect_id:
        return "effect_id"
    if (
        type(actual.comparison_group_id) is not str
        or actual.comparison_group_id != expected.comparison_group_id
    ):
        return "comparison_group_id"
    if type(actual.observed_effect) is not str:
        return "observed_effect"
    try:
        expected_observed_effect = _f64(expected.observed_effect)
    except ValueError:
        return "observed_effect"
    if actual.observed_effect != expected_observed_effect:
        return "observed_effect"
    if (
        type(actual.available_sequence) is not int
        or actual.available_sequence != expected.available_sequence
    ):
        return "available_sequence"
    if type(actual.source_kind) is not str or actual.source_kind != expected.source_kind:
        return "source_kind"
    if type(actual.source_ids) is not tuple or len(actual.source_ids) != len(expected.source_ids):
        return "source_ids"
    for index in range(len(expected.source_ids)):
        if (
            type(actual.source_ids[index]) is not str
            or actual.source_ids[index] != expected.source_ids[index]
        ):
            return f"source_ids[{index}]"
    if type(actual.created_at) is not str or actual.created_at != expected.created_at:
        return "created_at"
    actual_provenance = actual.provenance
    expected_provenance = expected.provenance
    if type(actual_provenance) is not _RunProvenanceProjection:
        return "provenance.type"
    if (
        type(actual_provenance.method) is not str
        or actual_provenance.method != expected_provenance.method
    ):
        return "provenance.method"
    if (
        type(actual_provenance.version) is not str
        or actual_provenance.version != expected_provenance.version
    ):
        return "provenance.version"
    actual_details = actual_provenance.details
    expected_details = expected_provenance.details
    if type(actual_details) is not tuple or len(actual_details) != len(expected_details):
        return "provenance.details"
    for index in range(len(expected_details)):
        actual_pair = actual_details[index]
        expected_pair = expected_details[index]
        if type(actual_pair) is not tuple or len(actual_pair) != 2:
            return f"provenance.details[{index}]"
        if type(actual_pair[0]) is not str or actual_pair[0] != expected_pair[0]:
            return f"provenance.details[{index}][0]"
        actual_value = actual_pair[1]
        if type(actual_value) is not _ProvenanceValueProjection:
            return f"provenance.details[{index}][1].type"
        expected_raw_value = expected_pair[1]
        expected_kind: str
        expected_value: object
        if expected_raw_value is None:
            expected_kind, expected_value = "null", None
        elif type(expected_raw_value) is bool:
            expected_kind, expected_value = "bool", expected_raw_value
        elif type(expected_raw_value) is int:
            expected_kind, expected_value = "i64", expected_raw_value
        elif type(expected_raw_value) is float:
            try:
                expected_value = _f64(expected_raw_value)
            except ValueError:
                return f"provenance.details[{index}][1].value"
            expected_kind = "f64"
        elif type(expected_raw_value) is str:
            expected_kind, expected_value = "string", expected_raw_value
        else:
            return f"provenance.details[{index}][1].value"
        if type(actual_value.kind) is not str or actual_value.kind != expected_kind:
            return f"provenance.details[{index}][1].kind"
        if expected_value is None:
            if actual_value.value is not None:
                return f"provenance.details[{index}][1].value"
        elif (
            type(actual_value.value) is not type(expected_value)
            or actual_value.value != expected_value
        ):
            return f"provenance.details[{index}][1].value"
    return None


def _first_observation_mismatch(
    actual: object,
    expected: _RevealedObservation,
) -> str | None:
    from research_decision_engine.benchmarks.broader_oracle import (
        RevealedObservation as _RevealedObservation,
    )

    if type(actual) is not _RevealedObservation:
        return "type"
    if type(actual.oracle_key_id) is not str or actual.oracle_key_id != expected.oracle_key_id:
        return "oracle_key_id"
    if type(actual.oracle_use_id) is not str or actual.oracle_use_id != expected.oracle_use_id:
        return "oracle_use_id"
    if (
        type(actual.authorization_id) is not str
        or actual.authorization_id != expected.authorization_id
    ):
        return "authorization_id"
    if type(actual.namespace) is not str or actual.namespace != expected.namespace:
        return "namespace"
    if type(actual.world_id) is not str or actual.world_id != expected.world_id:
        return "world_id"
    if type(actual.seed) is not int or actual.seed != expected.seed:
        return "seed"
    if type(actual.candidate_id) is not str or actual.candidate_id != expected.candidate_id:
        return "candidate_id"
    if (
        type(actual.comparison_group_id) is not str
        or actual.comparison_group_id != expected.comparison_group_id
    ):
        return "comparison_group_id"
    if (
        type(actual.intervention_arm) is not str
        or actual.intervention_arm != expected.intervention_arm
    ):
        return "intervention_arm"
    if type(actual.replication_id) is not str or actual.replication_id != expected.replication_id:
        return "replication_id"
    if type(actual.key_fields) is not tuple or len(actual.key_fields) != len(expected.key_fields):
        return "key_fields"
    for index in range(len(expected.key_fields)):
        if (
            type(actual.key_fields[index]) is not str
            or actual.key_fields[index] != expected.key_fields[index]
        ):
            return f"key_fields[{index}]"
    if (
        type(actual.serialized_key_hex) is not str
        or actual.serialized_key_hex != expected.serialized_key_hex
    ):
        return "serialized_key_hex"
    if type(actual.digest) is not str or actual.digest != expected.digest:
        return "digest"
    if type(actual.u) is not str or actual.u != expected.u:
        return "u"
    if type(actual.z) is not str or actual.z != expected.z:
        return "z"
    if (
        type(actual.revealed_observation) is not float
        or actual.revealed_observation != expected.revealed_observation
    ):
        return "revealed_observation"
    if type(actual.outcome_digest) is not str or actual.outcome_digest != expected.outcome_digest:
        return "outcome_digest"
    return None


def _first_run_observation_mismatch(
    actual: object,
    expected_authorization: _RunObservationAuthorizationProjection,
    expected: _RevealedObservation,
) -> str | None:
    from research_decision_engine.benchmarks.broader_returned_run import (
        RunObservationAuthorizationProjection as _RunObservationAuthorizationProjection,
    )
    from research_decision_engine.benchmarks.broader_returned_run import (
        RunRevealedObservationProjection as _RunRevealedObservationProjection,
    )

    if type(actual) is not _RunRevealedObservationProjection:
        return "type"
    authorization = actual.authorization
    if type(authorization) is not _RunObservationAuthorizationProjection:
        return "authorization.type"
    if (
        type(authorization.candidate_id) is not str
        or authorization.candidate_id != expected_authorization.candidate_id
    ):
        return "authorization.candidate_id"
    if type(authorization.kind) is not str or authorization.kind != expected_authorization.kind:
        return "authorization.kind"
    if (
        type(authorization.run_id) is not str
        or authorization.run_id != expected_authorization.run_id
    ):
        return "authorization.run_id"
    if (
        type(authorization.source_id) is not str
        or authorization.source_id != expected_authorization.source_id
    ):
        return "authorization.source_id"
    if (
        type(actual.authorization_id) is not str
        or actual.authorization_id != expected.authorization_id
    ):
        return "authorization_id"
    if type(actual.candidate_id) is not str or actual.candidate_id != expected.candidate_id:
        return "candidate_id"
    if (
        type(actual.comparison_group_id) is not str
        or actual.comparison_group_id != expected.comparison_group_id
    ):
        return "comparison_group_id"
    if type(actual.digest) is not str or actual.digest != expected.digest:
        return "digest"
    if (
        type(actual.intervention_arm) is not str
        or actual.intervention_arm != expected.intervention_arm
    ):
        return "intervention_arm"
    if type(actual.key_fields) is not tuple or len(actual.key_fields) != len(expected.key_fields):
        return "key_fields"
    for index in range(len(expected.key_fields)):
        if (
            type(actual.key_fields[index]) is not str
            or actual.key_fields[index] != expected.key_fields[index]
        ):
            return f"key_fields[{index}]"
    if type(actual.namespace) is not str or actual.namespace != expected.namespace:
        return "namespace"
    if type(actual.oracle_key_id) is not str or actual.oracle_key_id != expected.oracle_key_id:
        return "oracle_key_id"
    if type(actual.oracle_use_id) is not str or actual.oracle_use_id != expected.oracle_use_id:
        return "oracle_use_id"
    if type(actual.outcome_digest) is not str or actual.outcome_digest != expected.outcome_digest:
        return "outcome_digest"
    if type(actual.replication_id) is not str or actual.replication_id != expected.replication_id:
        return "replication_id"
    if type(actual.revealed_observation) is not str or actual.revealed_observation != _f64(
        expected.revealed_observation
    ):
        return "revealed_observation"
    if type(actual.seed) is not int or actual.seed != expected.seed:
        return "seed"
    if (
        type(actual.serialized_key_hex) is not str
        or actual.serialized_key_hex != expected.serialized_key_hex
    ):
        return "serialized_key_hex"
    if type(actual.u) is not str or actual.u != expected.u:
        return "u"
    if type(actual.world_id) is not str or actual.world_id != expected.world_id:
        return "world_id"
    if type(actual.z) is not str or actual.z != expected.z:
        return "z"
    return None


def _first_history_nonidentity_mismatch(
    actual: object,
    expected: ScientificCalibrationSelectionProjection,
    expected_effects: tuple[_MatchedEffectObservation, ...],
    expected_observations: tuple[_RevealedObservation, ...],
    physical_cost: float,
) -> str | None:
    from research_decision_engine.benchmarks.broader_calibration_history import (
        CalibrationHistorySelection as _CalibrationHistorySelection,
    )

    if type(actual) is not _CalibrationHistorySelection:
        return "type"
    if type(actual.study_id) is not str or actual.study_id != expected.study_id:
        return "study_id"
    if type(actual.world_id) is not str or actual.world_id != expected.world_id:
        return "world_id"
    if type(actual.seed) is not int or actual.seed != expected.seed:
        return "seed"
    if type(actual.namespace) is not str or actual.namespace != expected.namespace:
        return "namespace"
    if (
        type(actual.comparison_group_id) is not str
        or actual.comparison_group_id != expected.comparison_group_id
    ):
        return "comparison_group_id"
    if (
        type(actual.target_comparison_group_id) is not str
        or actual.target_comparison_group_id != expected.target_comparison_group_id
    ):
        return "target_comparison_group_id"
    if (
        type(actual.source_sequence_cutoff) is not int
        or actual.source_sequence_cutoff != expected.source_sequence_cutoff
    ):
        return "source_sequence_cutoff"
    if type(actual.source_effect_ids) is not tuple or len(actual.source_effect_ids) != 5:
        return "source_effect_ids"
    for index in range(5):
        if (
            type(actual.source_effect_ids[index]) is not str
            or actual.source_effect_ids[index] != expected.source_effect_ids[index]
        ):
            return f"source_effect_ids[{index}]"
    if (
        type(actual.source_effect_payload_sha256) is not tuple
        or len(actual.source_effect_payload_sha256) != 5
    ):
        return "source_effect_payload_sha256"
    for index in range(5):
        if (
            type(actual.source_effect_payload_sha256[index]) is not str
            or actual.source_effect_payload_sha256[index]
            != expected.source_effect_payload_sha256[index]
        ):
            return f"source_effect_payload_sha256[{index}]"
    if (
        type(actual.source_observation_identities) is not tuple
        or len(actual.source_observation_identities) != 10
    ):
        return "source_observation_identities"
    for index in range(10):
        pair = actual.source_observation_identities[index]
        expected_pair = expected.source_observation_identities[index]
        if type(pair) is not tuple or len(pair) != 2:
            return f"source_observation_identities[{index}]"
        if type(pair[0]) is not str or pair[0] != expected_pair[0]:
            return f"source_observation_identities[{index}][0]"
        if type(pair[1]) is not str or pair[1] != expected_pair[1]:
            return f"source_observation_identities[{index}][1]"
    if type(actual.source_oracle_key_ids) is not tuple or len(actual.source_oracle_key_ids) != 10:
        return "source_oracle_key_ids"
    for index in range(10):
        if (
            type(actual.source_oracle_key_ids[index]) is not str
            or actual.source_oracle_key_ids[index] != expected.source_oracle_key_ids[index]
        ):
            return f"source_oracle_key_ids[{index}]"
    if type(actual.source_candidate_pairs) is not tuple or len(actual.source_candidate_pairs) != 5:
        return "source_candidate_pairs"
    for index in range(5):
        pair = actual.source_candidate_pairs[index]
        expected_pair = expected.source_candidate_pairs[index]
        if type(pair) is not tuple or len(pair) != 2:
            return f"source_candidate_pairs[{index}]"
        for arm_index in range(2):
            if type(pair[arm_index]) is not str or pair[arm_index] != expected_pair[arm_index]:
                return f"source_candidate_pairs[{index}][{arm_index}]"
    if type(actual.source_replication_ids) is not tuple or len(actual.source_replication_ids) != 5:
        return "source_replication_ids"
    for index in range(5):
        if (
            type(actual.source_replication_ids[index]) is not str
            or actual.source_replication_ids[index] != expected.source_replication_ids[index]
        ):
            return f"source_replication_ids[{index}]"
    if type(actual.effect_values) is not tuple or len(actual.effect_values) != 5:
        return "effect_values"
    for index in range(5):
        if type(actual.effect_values[index]) is not float:
            return f"effect_values[{index}]"
        try:
            actual_effect_value = _f64(actual.effect_values[index])
        except ValueError:
            return f"effect_values[{index}]"
        if actual_effect_value != expected.effect_values[index]:
            return f"effect_values[{index}]"
    if type(actual.sample_count) is not int or actual.sample_count != expected.sample_count:
        return "sample_count"
    if type(actual.sample_mean) is not float:
        return "sample_mean"
    try:
        actual_sample_mean = _f64(actual.sample_mean)
    except ValueError:
        return "sample_mean"
    if actual_sample_mean != expected.sample_mean:
        return "sample_mean"
    if type(actual.sample_standard_deviation) is not float:
        return "sample_standard_deviation"
    try:
        actual_sample_standard_deviation = _f64(actual.sample_standard_deviation)
    except ValueError:
        return "sample_standard_deviation"
    if actual_sample_standard_deviation != expected.sample_standard_deviation:
        return "sample_standard_deviation"
    if type(actual.ddof) is not int or actual.ddof != expected.ddof:
        return "ddof"
    if type(actual.sigma_floor) is not float:
        return "sigma_floor"
    try:
        actual_sigma_floor = _f64(actual.sigma_floor)
    except ValueError:
        return "sigma_floor"
    if actual_sigma_floor != expected.sigma_floor:
        return "sigma_floor"
    if type(actual.estimated_sigma) is not float:
        return "estimated_sigma"
    try:
        actual_estimated_sigma = _f64(actual.estimated_sigma)
    except ValueError:
        return "estimated_sigma"
    if actual_estimated_sigma != expected.estimated_sigma:
        return "estimated_sigma"
    if type(actual.physical_cost) is not float:
        return "physical_cost"
    try:
        actual_physical_cost = _f64(actual.physical_cost)
    except ValueError:
        return "physical_cost"
    if actual_physical_cost != _f64(physical_cost):
        return "physical_cost"
    if (
        type(actual.eligibility_basis) is not str
        or actual.eligibility_basis != expected.eligibility_basis
    ):
        return "eligibility_basis"
    if (
        type(actual.current_observation_excluded) is not bool
        or actual.current_observation_excluded is not True
    ):
        return "current_observation_excluded"
    if (
        type(actual.current_effect_excluded) is not bool
        or actual.current_effect_excluded is not True
    ):
        return "current_effect_excluded"
    if (
        type(actual.future_history_excluded) is not bool
        or actual.future_history_excluded is not True
    ):
        return "future_history_excluded"
    if type(actual.effects) is not tuple or len(actual.effects) != 5:
        return "effects"
    for index in range(5):
        mismatch = _first_effect_mismatch(actual.effects[index], expected_effects[index])
        if mismatch is not None:
            return f"effects[{index}].{mismatch}"
    if type(actual.observations) is not tuple or len(actual.observations) != 10:
        return "observations"
    for index in range(10):
        mismatch = _first_observation_mismatch(
            actual.observations[index],
            expected_observations[index],
        )
        if mismatch is not None:
            return f"observations[{index}].{mismatch}"
    return None


def _first_scientific_projection_mismatch(
    actual: object,
    expected: ScientificCalibrationSelectionProjection,
) -> str | None:
    if type(actual) is not ScientificCalibrationSelectionProjection:
        return "type"
    if (
        type(actual.comparison_group_id) is not str
        or actual.comparison_group_id != expected.comparison_group_id
    ):
        return "comparison_group_id"
    if type(actual.ddof) is not int or actual.ddof != expected.ddof:
        return "ddof"
    if type(actual.effect_values) is not tuple or len(actual.effect_values) != 5:
        return "effect_values"
    for index in range(5):
        if (
            type(actual.effect_values[index]) is not str
            or actual.effect_values[index] != expected.effect_values[index]
        ):
            return f"effect_values[{index}]"
    if (
        type(actual.eligibility_basis) is not str
        or actual.eligibility_basis != expected.eligibility_basis
    ):
        return "eligibility_basis"
    if (
        type(actual.estimated_sigma) is not str
        or actual.estimated_sigma != expected.estimated_sigma
    ):
        return "estimated_sigma"
    if type(actual.namespace) is not str or actual.namespace != expected.namespace:
        return "namespace"
    if type(actual.sample_count) is not int or actual.sample_count != expected.sample_count:
        return "sample_count"
    if type(actual.sample_mean) is not str or actual.sample_mean != expected.sample_mean:
        return "sample_mean"
    if (
        type(actual.sample_standard_deviation) is not str
        or actual.sample_standard_deviation != expected.sample_standard_deviation
    ):
        return "sample_standard_deviation"
    if type(actual.seed) is not int or actual.seed != expected.seed:
        return "seed"
    if type(actual.sigma_floor) is not str or actual.sigma_floor != expected.sigma_floor:
        return "sigma_floor"
    if type(actual.source_candidate_pairs) is not tuple or len(actual.source_candidate_pairs) != 5:
        return "source_candidate_pairs"
    for index in range(5):
        pair = actual.source_candidate_pairs[index]
        expected_pair = expected.source_candidate_pairs[index]
        if type(pair) is not tuple or len(pair) != 2:
            return f"source_candidate_pairs[{index}]"
        for arm_index in range(2):
            if type(pair[arm_index]) is not str or pair[arm_index] != expected_pair[arm_index]:
                return f"source_candidate_pairs[{index}][{arm_index}]"
    if type(actual.source_effect_ids) is not tuple or len(actual.source_effect_ids) != 5:
        return "source_effect_ids"
    for index in range(5):
        if (
            type(actual.source_effect_ids[index]) is not str
            or actual.source_effect_ids[index] != expected.source_effect_ids[index]
        ):
            return f"source_effect_ids[{index}]"
    if (
        type(actual.source_effect_payload_sha256) is not tuple
        or len(actual.source_effect_payload_sha256) != 5
    ):
        return "source_effect_payload_sha256"
    for index in range(5):
        if (
            type(actual.source_effect_payload_sha256[index]) is not str
            or actual.source_effect_payload_sha256[index]
            != expected.source_effect_payload_sha256[index]
        ):
            return f"source_effect_payload_sha256[{index}]"
    if (
        type(actual.source_observation_identities) is not tuple
        or len(actual.source_observation_identities) != 10
    ):
        return "source_observation_identities"
    for index in range(10):
        pair = actual.source_observation_identities[index]
        expected_pair = expected.source_observation_identities[index]
        if type(pair) is not tuple or len(pair) != 2:
            return f"source_observation_identities[{index}]"
        for pair_index in range(2):
            if type(pair[pair_index]) is not str or pair[pair_index] != expected_pair[pair_index]:
                return f"source_observation_identities[{index}][{pair_index}]"
    if type(actual.source_oracle_key_ids) is not tuple or len(actual.source_oracle_key_ids) != 10:
        return "source_oracle_key_ids"
    for index in range(10):
        if (
            type(actual.source_oracle_key_ids[index]) is not str
            or actual.source_oracle_key_ids[index] != expected.source_oracle_key_ids[index]
        ):
            return f"source_oracle_key_ids[{index}]"
    if type(actual.source_replication_ids) is not tuple or len(actual.source_replication_ids) != 5:
        return "source_replication_ids"
    for index in range(5):
        if (
            type(actual.source_replication_ids[index]) is not str
            or actual.source_replication_ids[index] != expected.source_replication_ids[index]
        ):
            return f"source_replication_ids[{index}]"
    if (
        type(actual.source_sequence_cutoff) is not int
        or actual.source_sequence_cutoff != expected.source_sequence_cutoff
    ):
        return "source_sequence_cutoff"
    if type(actual.study_id) is not str or actual.study_id != expected.study_id:
        return "study_id"
    if (
        type(actual.target_comparison_group_id) is not str
        or actual.target_comparison_group_id != expected.target_comparison_group_id
    ):
        return "target_comparison_group_id"
    if type(actual.world_id) is not str or actual.world_id != expected.world_id:
        return "world_id"
    return None


def _predicate_3o_5_1(
    selection: _SelectionEvidence,
    p2_selection: _P2SelectionEvidence,
    expected_predecessor: _OraclePredecessor,
    expected_execution_attestation_pairs: _ExecutionAttestationPairs,
    attested_execution_specification_ids: _AttestedSpecificationIds,
    validated_returned_results_by_role: tuple[
        _ReturnedResultsProjection,
        _ReturnedResultsProjection,
        _ReturnedResultsProjection,
        _ReturnedResultsProjection,
    ],
    p3_input: _P3SelectionInput,
    selection_index: int,
) -> _PredicateFailure | None:
    import hashlib as _hashlib
    import statistics as _statistics

    from research_decision_engine.belief_models import (
        SIGMA_FLOOR as _SIGMA_FLOOR,
    )
    from research_decision_engine.benchmarks.broader_calibration_history import (
        CALIBRATION_ELIGIBILITY_BASIS as _CALIBRATION_ELIGIBILITY_BASIS,
    )
    from research_decision_engine.benchmarks.broader_calibration_history import (
        CALIBRATION_SIGMA_DDOF as _CALIBRATION_SIGMA_DDOF,
    )
    from research_decision_engine.benchmarks.broader_calibration_history import (
        CALIBRATION_SOURCE_SEQUENCE_CUTOFF as _CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
    )
    from research_decision_engine.benchmarks.broader_calibration_history import (
        RunProvenanceError as _RunProvenanceError,
    )
    from research_decision_engine.benchmarks.broader_calibration_history import (
        expected_calibration_effect as _expected_calibration_effect,
    )
    from research_decision_engine.benchmarks.broader_calibration_selector_replay import (
        replay_calibration_history_selection as _replay_calibration_history_selection,
    )
    from research_decision_engine.benchmarks.broader_execution import (
        ReturnedResultsProjection as _ReturnedResultsProjection,
    )
    from research_decision_engine.benchmarks.broader_oracle import (
        RevealedObservation as _RevealedObservation,
    )
    from research_decision_engine.benchmarks.broader_oracle import (
        transform_key as _transform_key,
    )
    from research_decision_engine.benchmarks.broader_returned_run import (
        ReturnedRunProjection as _ReturnedRunProjection,
    )
    from research_decision_engine.benchmarks.broader_returned_run import (
        RunCalibrationEstimateProjection as _RunCalibrationEstimateProjection,
    )
    from research_decision_engine.benchmarks.broader_returned_run import (
        RunCalibrationProjection as _RunCalibrationProjection,
    )
    from research_decision_engine.benchmarks.broader_returned_run import (
        RunMatchedEffectProjection as _RunMatchedEffectProjection,
    )
    from research_decision_engine.benchmarks.broader_returned_run import (
        RunObservationAuthorizationProjection as _RunObservationAuthorizationProjection,
    )
    from research_decision_engine.benchmarks.broader_returned_run import (
        reconstruct_matched_effect as _reconstruct_matched_effect,
    )
    from research_decision_engine.benchmarks.broader_worlds import (
        WORLDS_BY_ID as _WORLDS_BY_ID,
    )
    from research_decision_engine.benchmarks.broader_worlds import (
        candidate_costs as _candidate_costs,
    )

    if (
        type(selection_index) is not int
        or not 0 <= selection_index < _CANONICAL_SELECTION_COUNT
        or type(p3_input) is not _P3SelectionInput
    ):
        return _selector_result_failure("P3 input shape or coordinate is malformed")
    role, world_id, seed, comparison_group_id = _CANONICAL_SELECTION_COORDINATES[selection_index]
    if (
        selection[0] != role
        or selection[1] != selection_index
        or selection[2] != world_id
        or selection[3] != seed
        or selection[4] != comparison_group_id
    ):
        return _selector_result_failure("canonical selection coordinate differs")
    role_index = _role_index(role)
    if role_index is None:
        return _selector_result_failure("canonical role is unknown")
    expected_pair = expected_execution_attestation_pairs[role_index]
    if (
        type(expected_pair) is not tuple
        or len(expected_pair) != 2
        or type(expected_pair[0]) is not str
        or type(expected_pair[1]) is not str
        or selection[7] != expected_pair[0]
        or selection[8] != expected_pair[1]
        or attested_execution_specification_ids[role_index] != expected_pair[0]
    ):
        return _selector_result_failure("role-owned execution relation differs")
    role_results = validated_returned_results_by_role[role_index]
    if (
        type(role_results) is not _ReturnedResultsProjection
        or type(role_results.execution_specification_id) is not str
        or role_results.execution_specification_id != expected_pair[0]
        or type(role_results.results_in_submission_order) is not tuple
    ):
        return _selector_result_failure("role-owned returned-results aggregate differs")

    matching_rows: tuple[tuple[str, _ReturnedRunProjection, str], ...] = ()
    for row_index in range(len(role_results.results_in_submission_order)):
        row = role_results.results_in_submission_order[row_index]
        if type(row) is not tuple or len(row) != 3:
            return _selector_result_failure(
                f"role-owned returned-result row[{row_index}] is malformed"
            )
        returned_result_id_value, returned_run, submitted_job_id_value = row
        if (
            type(returned_result_id_value) is not str
            or type(returned_run) is not _ReturnedRunProjection
            or type(submitted_job_id_value) is not str
            or type(returned_run.world_id) is not str
            or type(returned_run.seed) is not int
            or type(returned_run.budget_id) is not str
            or type(returned_run.budget) is not str
            or type(returned_run.arm) is not tuple
            or len(returned_run.arm) != 4
        ):
            return _selector_result_failure(
                f"role-owned returned-result row[{row_index}] is malformed"
            )
        arm = returned_run.arm
        if (
            type(arm[0]) is not str
            or type(arm[1]) is not int
            or type(arm[2]) is not str
            or type(arm[3]) is not str
        ):
            return _selector_result_failure(
                f"role-owned returned-result row[{row_index}] arm is malformed"
            )
        if (
            returned_run.world_id == world_id
            and returned_run.seed == seed
            and returned_run.budget_id == "budget-2.25"
            and returned_run.budget == "f64:4002000000000000"
            and arm[0] == "calibrated_ig"
            and arm[1] == 2
            and arm[2] == "replicated_noise_calibrated_gaussian"
            and arm[3] == "information_gain"
        ):
            matching_rows = (
                *matching_rows,
                (
                    returned_result_id_value,
                    returned_run,
                    submitted_job_id_value,
                ),
            )
    if len(matching_rows) != 1:
        return _selector_result_failure("role-owned replay witness is missing or not unique")
    witness_row = matching_rows[0]
    returned_result_id_value, witness, submitted_job_id_value = witness_row
    mapping_occurrences = 0
    if type(role_results.job_result_mapping) is not tuple:
        return _selector_result_failure("role-owned job/result mapping is malformed")
    for mapping_index in range(len(role_results.job_result_mapping)):
        mapping_pair = role_results.job_result_mapping[mapping_index]
        if (
            type(mapping_pair) is not tuple
            or len(mapping_pair) != 2
            or type(mapping_pair[0]) is not str
            or type(mapping_pair[1]) is not str
        ):
            return _selector_result_failure(
                f"role-owned job/result mapping[{mapping_index}] is malformed"
            )
        if mapping_pair == (submitted_job_id_value, returned_result_id_value):
            mapping_occurrences += 1
    if mapping_occurrences != 1:
        return _selector_result_failure("role-owned replay witness row is not mapped")
    try:
        checked_returned_result_id = _exact_h64(
            p3_input.returned_result_id,
            "p3_input.returned_result_id",
        )
        checked_submitted_job_id = _exact_h64(
            p3_input.submitted_job_id,
            "p3_input.submitted_job_id",
        )
    except ValueError:
        return _selector_result_failure("carried replay witness row identity is malformed")
    if (
        checked_returned_result_id != returned_result_id_value
        or checked_submitted_job_id != submitted_job_id_value
        or p3_input.returned_run_projection is not witness
    ):
        return _selector_result_failure("carried replay witness is not the exact role-owned row")
    replay_run_id = witness.run_id
    if type(replay_run_id) is not str or not replay_run_id.strip():
        return _selector_result_failure("role-owned replay run ID is malformed")

    group_index = _group_index(comparison_group_id)
    calibration = witness.calibration
    if (
        group_index is None
        or type(calibration) is not _RunCalibrationProjection
        or type(calibration.estimates) is not tuple
        or len(calibration.estimates) != 3
    ):
        return _selector_result_failure("witness Calibration estimate scope differs")
    estimate = calibration.estimates[group_index]
    if (
        type(estimate) is not _RunCalibrationEstimateProjection
        or type(estimate.comparison_group_id) is not str
        or estimate.comparison_group_id != comparison_group_id
        or type(estimate.calibration_prefix_id) is not str
        or estimate.calibration_prefix_id != selection[6]
        or type(estimate.observations) is not tuple
        or len(estimate.observations) != 10
        or type(estimate.effects) is not tuple
        or len(estimate.effects) != 5
        or type(calibration.observations) is not tuple
        or len(calibration.observations) != 30
        or type(calibration.effects) is not tuple
        or len(calibration.effects) != 15
    ):
        return _selector_result_failure("witness Calibration estimate relation differs")

    try:
        world = _exact_frozen_world(
            expected_predecessor[10],
            world_id,
            selection[10],
        )
    except (AttributeError, TypeError, ValueError):
        return _selector_result_failure("validated frozen-world predecessor is malformed")
    expected_observations: tuple[_RevealedObservation, ...] = ()
    recorded_observations: tuple[_RevealedObservation, ...] = ()
    for observation_index in range(10):
        try:
            (
                expected_world_id,
                expected_seed,
                expected_group_id,
                expected_arm,
                expected_candidate_id,
                expected_replication_id,
                expected_key_fields,
            ) = _expected_source_coordinate(selection, observation_index)
            transform = _transform_key(expected_key_fields)
            base_candidate_id = f"g{group_index:02d}-{expected_arm}-r1"
            revealed_observation = _hidden_arm_mean(
                world,
                base_candidate_id,
            ) + (
                _hidden_observation_sigma(
                    world,
                    base_candidate_id,
                )
                * transform.z
            )
            revealed_f64 = _f64(revealed_observation)
            expected_oracle_key_id = _oracle_key_id(  # type: ignore[no-untyped-call]
                expected_key_fields
            )
            expected_outcome_digest = _outcome_digest(  # type: ignore[no-untyped-call]
                expected_oracle_key_id,
                revealed_f64,
            )
            expected_source_projection = CalibrationSourceObservationProjection(
                candidate_id=expected_candidate_id,
                comparison_group_id=expected_group_id,
                digest=transform.digest_hex,
                intervention_arm=expected_arm,
                key_fields=expected_key_fields,
                namespace=_CALIBRATION_NAMESPACE,
                oracle_key_id=expected_oracle_key_id,
                outcome_digest=expected_outcome_digest,
                replication_id=expected_replication_id,
                revealed_observation=revealed_f64,
                schema_version=_SOURCE_OBSERVATION_SCHEMA,
                seed=expected_seed,
                serialized_key_hex=transform.serialized_key.hex(),
                u=transform.u_string,
                world_id=expected_world_id,
                z=transform.z_string,
            )
            source_evidence = _source_evidence_at(p2_selection, observation_index)
            if source_evidence is None:
                raise ValueError("missing P2 source occurrence")
            source_mismatch = _first_source_mismatch(
                source_evidence[0],
                expected_source_projection,
            )
            if source_mismatch is not None:
                raise ValueError(source_mismatch)
            source_id = f"{selection[6]}/{expected_candidate_id}"
            expected_authorization = _RunObservationAuthorizationProjection(
                candidate_id=expected_candidate_id,
                kind="calibration",
                run_id=replay_run_id,
                source_id=source_id,
            )
            expected_authorization_id = _runtime_id(
                "authorization",
                "authorization_id/v1",
                {
                    "candidate_id": expected_candidate_id,
                    "kind": "calibration",
                    "run_id": replay_run_id,
                    "source_id": source_id,
                },
            )
            expected_oracle_use_id = (
                f"oracle-use/{expected_authorization_id}/{expected_oracle_key_id}"
            )
            expected_observation = _RevealedObservation(
                oracle_key_id=expected_oracle_key_id,
                oracle_use_id=expected_oracle_use_id,
                authorization_id=expected_authorization_id,
                namespace=_CALIBRATION_NAMESPACE,
                world_id=expected_world_id,
                seed=expected_seed,
                candidate_id=expected_candidate_id,
                comparison_group_id=expected_group_id,
                intervention_arm=expected_arm,
                replication_id=expected_replication_id,
                key_fields=expected_key_fields,
                serialized_key_hex=transform.serialized_key.hex(),
                digest=transform.digest_hex,
                u=transform.u_string,
                z=transform.z_string,
                revealed_observation=revealed_observation,
                outcome_digest=expected_outcome_digest,
            )
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            return _selector_result_failure(
                f"observation[{observation_index}] independent reconstruction failed"
            )
        witness_observation = estimate.observations[observation_index]
        run_mismatch = _first_run_observation_mismatch(
            witness_observation,
            expected_authorization,
            expected_observation,
        )
        if run_mismatch is not None:
            return _selector_result_failure(
                f"observation[{observation_index}].{run_mismatch} differs"
            )
        calibration_observation = calibration.observations[group_index * 10 + observation_index]
        calibration_mismatch = _first_run_observation_mismatch(
            calibration_observation,
            expected_authorization,
            expected_observation,
        )
        if calibration_mismatch is not None:
            return _selector_result_failure(
                "role-owned returned-run observation occurrence "
                f"[{observation_index}].{calibration_mismatch} differs"
            )
        expected_observations = (*expected_observations, expected_observation)
        recorded_observations = (
            *recorded_observations,
            _RevealedObservation(
                oracle_key_id=witness_observation.oracle_key_id,
                oracle_use_id=witness_observation.oracle_use_id,
                authorization_id=witness_observation.authorization_id,
                namespace=witness_observation.namespace,
                world_id=witness_observation.world_id,
                seed=witness_observation.seed,
                candidate_id=witness_observation.candidate_id,
                comparison_group_id=witness_observation.comparison_group_id,
                intervention_arm=witness_observation.intervention_arm,
                replication_id=witness_observation.replication_id,
                key_fields=witness_observation.key_fields,
                serialized_key_hex=witness_observation.serialized_key_hex,
                digest=witness_observation.digest,
                u=witness_observation.u,
                z=witness_observation.z,
                revealed_observation=expected_observation.revealed_observation,
                outcome_digest=witness_observation.outcome_digest,
            ),
        )

    if (
        type(witness.effect_history) is not tuple
        or type(witness.updates) is not tuple
        or len(witness.effect_history) != 15 + len(witness.updates)
    ):
        return _selector_result_failure("complete recorded effect history differs")
    expected_effects: tuple[_MatchedEffectObservation, ...] = ()
    effect_payload_sha256_values: tuple[str, ...] = ()
    for effect_index in range(5):
        replication_index = effect_index + 1
        observed_effect = round(
            expected_observations[2 * effect_index].revealed_observation
            - expected_observations[2 * effect_index + 1].revealed_observation,
            12,
        )
        expected_effect = _expected_calibration_effect(
            prefix_id=selection[6],
            world_id=world_id,
            comparison_group_id=comparison_group_id,
            group_index=group_index,
            replication_index=replication_index,
            observed_effect=observed_effect,
        )
        effect_payload_bytes = _canonical_json_bytes(
            expected_effect.to_dict(),
            final_lf=True,
        )
        effect_payload_sha256 = _hashlib.sha256(effect_payload_bytes).hexdigest()
        effect_evidence = selection[17][effect_index]
        if (
            type(effect_evidence) is not tuple
            or len(effect_evidence) != 4
            or type(effect_evidence[0]) is not str
            or effect_evidence[0] != expected_effect.effect_id
            or type(effect_evidence[1]) is not bytes
            or effect_evidence[1] != effect_payload_bytes
            or type(effect_evidence[2]) is not str
            or effect_evidence[2] != effect_payload_sha256
        ):
            return _selector_result_failure(f"effect[{effect_index}] P1 source evidence differs")
        if _first_run_effect_mismatch(effect_evidence[3], expected_effect) is not None:
            return _selector_result_failure(f"effect[{effect_index}] P1 source evidence differs")
        if (
            _first_run_effect_mismatch(
                estimate.effects[effect_index],
                expected_effect,
            )
            is not None
        ):
            return _selector_result_failure(
                f"effect[{effect_index}] witness estimate occurrence differs"
            )
        if (
            _first_run_effect_mismatch(
                calibration.effects[group_index * 5 + effect_index],
                expected_effect,
            )
            is not None
        ):
            return _selector_result_failure(
                f"effect[{effect_index}] returned-run Calibration occurrence differs"
            )
        history_occurrences = 0
        for history_projection in witness.effect_history:
            if _first_run_effect_mismatch(history_projection, expected_effect) is None:
                history_occurrences += 1
        if history_occurrences != 1:
            return _selector_result_failure(
                f"effect[{effect_index}] returned-run history occurrence is not unique"
            )
        expected_effects = (*expected_effects, expected_effect)
        effect_payload_sha256_values = (
            *effect_payload_sha256_values,
            effect_payload_sha256,
        )

    recorded_effects: tuple[_MatchedEffectObservation, ...] = ()
    for history_index in range(len(witness.effect_history)):
        history_projection = witness.effect_history[history_index]
        if type(history_projection) is not _RunMatchedEffectProjection:
            return _selector_result_failure(
                f"recorded effect[{history_index}] projection type differs"
            )
        try:
            recorded_effect = _reconstruct_matched_effect(history_projection)
        except (AttributeError, TypeError, ValueError):
            return _selector_result_failure(
                f"recorded effect[{history_index}] reconstruction failed"
            )
        recorded_effects = (*recorded_effects, recorded_effect)

    costs = _candidate_costs(_WORLDS_BY_ID[world_id].public)
    physical_cost = 5.0 * (
        costs[f"g{group_index:02d}-adam-r1"] + costs[f"g{group_index:02d}-sgd-r1"]
    )
    if type(estimate.physical_cost) is not str or estimate.physical_cost != _f64(physical_cost):
        return _selector_result_failure("witness estimate physical_cost differs")
    effect_values = tuple(effect.observed_effect for effect in expected_effects)
    sample_mean = _statistics.mean(effect_values)
    sample_standard_deviation = _statistics.stdev(effect_values)
    estimated_sigma = max(sample_standard_deviation, _SIGMA_FLOOR)
    expected_projection = ScientificCalibrationSelectionProjection(
        comparison_group_id=comparison_group_id,
        ddof=_CALIBRATION_SIGMA_DDOF,
        effect_values=tuple(_f64(value) for value in effect_values),
        eligibility_basis=_CALIBRATION_ELIGIBILITY_BASIS,
        estimated_sigma=_f64(estimated_sigma),
        namespace=_CALIBRATION_NAMESPACE,
        sample_count=len(expected_effects),
        sample_mean=_f64(sample_mean),
        sample_standard_deviation=_f64(sample_standard_deviation),
        seed=seed,
        sigma_floor=_f64(_SIGMA_FLOOR),
        source_candidate_pairs=selection[10],
        source_effect_ids=tuple(effect.effect_id for effect in expected_effects),
        source_effect_payload_sha256=effect_payload_sha256_values,
        source_observation_identities=tuple(
            (observation.oracle_key_id, observation.outcome_digest)
            for observation in expected_observations
        ),
        source_oracle_key_ids=tuple(
            observation.oracle_key_id for observation in expected_observations
        ),
        source_replication_ids=selection[13],
        source_sequence_cutoff=_CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
        study_id=_FROZEN_STUDY,
        target_comparison_group_id=comparison_group_id,
        world_id=world_id,
    )
    if (
        type(estimate.belief_model_id) is not str
        or estimate.belief_model_id != "replicated_noise_calibrated_gaussian"
        or type(estimate.ddof) is not int
        or estimate.ddof != expected_projection.ddof
        or type(estimate.estimated_sigma) is not str
        or estimate.estimated_sigma != expected_projection.estimated_sigma
        or type(estimate.raw_sample_standard_deviation) is not str
        or estimate.raw_sample_standard_deviation != expected_projection.sample_standard_deviation
        or type(estimate.sample_count) is not int
        or estimate.sample_count != expected_projection.sample_count
        or type(estimate.sample_mean) is not str
        or estimate.sample_mean != expected_projection.sample_mean
        or type(estimate.sigma_floor) is not str
        or estimate.sigma_floor != expected_projection.sigma_floor
        or type(estimate.source_effect_ids) is not tuple
        or len(estimate.source_effect_ids) != len(expected_projection.source_effect_ids)
    ):
        return _selector_result_failure("witness Calibration estimate scientific relation differs")
    for source_effect_index in range(len(expected_projection.source_effect_ids)):
        if (
            type(estimate.source_effect_ids[source_effect_index]) is not str
            or estimate.source_effect_ids[source_effect_index]
            != expected_projection.source_effect_ids[source_effect_index]
        ):
            return _selector_result_failure(
                "witness Calibration estimate scientific relation differs"
            )
    if (
        type(estimate.source_sequence_cutoff) is not int
        or estimate.source_sequence_cutoff != expected_projection.source_sequence_cutoff
    ):
        return _selector_result_failure("witness Calibration estimate scientific relation differs")

    try:
        actual_helper_result = _replay_calibration_history_selection(
            run_id=replay_run_id,
            world_id=world_id,
            seed=seed,
            comparison_group_id=comparison_group_id,
            group_index=group_index,
            expected_observations=expected_observations,
            expected_effects=expected_effects,
            physical_cost=physical_cost,
            recorded_observations=recorded_observations,
            recorded_effects=recorded_effects,
            source_sequence_cutoff=_CALIBRATION_SOURCE_SEQUENCE_CUTOFF,
        )
    except _RunProvenanceError:
        return _selector_result_failure("replay helper rejected run-local provenance")

    helper_mismatch = _first_history_nonidentity_mismatch(
        actual_helper_result,
        expected_projection,
        expected_effects,
        expected_observations,
        physical_cost,
    )
    if helper_mismatch is not None:
        return _selector_result_failure(f"helper.{helper_mismatch} differs")
    historical_selection = selection[16]
    historical_mismatch = _first_history_nonidentity_mismatch(
        historical_selection,
        expected_projection,
        expected_effects,
        expected_observations,
        physical_cost,
    )
    if historical_mismatch is not None:
        return _selector_result_failure(f"historical.{historical_mismatch} differs")
    carried_projection = p3_input.selector_result_projection
    projection_mismatch = _first_scientific_projection_mismatch(
        carried_projection,
        expected_projection,
    )
    if projection_mismatch is not None:
        return _selector_result_failure(f"projection.{projection_mismatch} differs")
    try:
        trusted_projection_mapping = _scientific_calibration_selection_mapping(carried_projection)
        decoded_projection = _decode_scientific_calibration_selection_projection(
            trusted_projection_mapping
        )
    except (AttributeError, TypeError, ValueError):
        return _selector_result_failure("projection strict reconstruction failed")
    if decoded_projection != expected_projection:
        return _selector_result_failure("projection strict reconstruction differs")

    expected_selector_result_identity = _protocol_hash(
        "broader-calibration-history-selection/v1",
        {
            "comparison_group_id": expected_projection.comparison_group_id,
            "ddof": expected_projection.ddof,
            "effect_values": list(expected_projection.effect_values),
            "eligibility_basis": expected_projection.eligibility_basis,
            "estimated_sigma": expected_projection.estimated_sigma,
            "namespace": expected_projection.namespace,
            "sample_count": expected_projection.sample_count,
            "sample_mean": expected_projection.sample_mean,
            "sample_standard_deviation": (expected_projection.sample_standard_deviation),
            "seed": expected_projection.seed,
            "sigma_floor": expected_projection.sigma_floor,
            "source_candidate_pairs": [
                list(pair) for pair in expected_projection.source_candidate_pairs
            ],
            "source_effect_ids": list(expected_projection.source_effect_ids),
            "source_effect_payload_sha256": list(expected_projection.source_effect_payload_sha256),
            "source_observation_identities": [
                list(pair) for pair in expected_projection.source_observation_identities
            ],
            "source_oracle_key_ids": list(expected_projection.source_oracle_key_ids),
            "source_replication_ids": list(expected_projection.source_replication_ids),
            "source_sequence_cutoff": (expected_projection.source_sequence_cutoff),
            "study_id": expected_projection.study_id,
            "target_comparison_group_id": (expected_projection.target_comparison_group_id),
            "world_id": expected_projection.world_id,
        },
    )
    try:
        helper_identity = _exact_h64(
            actual_helper_result.selection_identity,
            "helper.selection_identity",
        )
    except ValueError:
        return _selector_result_failure("helper.selection_identity is malformed")
    if helper_identity != expected_selector_result_identity:
        return _selector_result_failure("helper.selection_identity differs")
    try:
        historical_identity = _exact_h64(
            historical_selection.selection_identity,
            "historical.selection_identity",
        )
    except ValueError:
        return _selector_result_failure("historical.selection_identity is malformed")
    if historical_identity != expected_selector_result_identity:
        return _selector_result_failure("historical.selection_identity differs")
    try:
        explicit_identity = _exact_h64(
            p3_input.selector_result_identity,
            "p3_input.selector_result_identity",
        )
    except ValueError:
        return _selector_result_failure("explicit selector_result_identity is malformed")
    if explicit_identity != expected_selector_result_identity:
        return _selector_result_failure("explicit selector_result_identity differs")
    return None


def _p3_outcome(
    failure: _PredicateFailure,
    selection_index: int,
    p2_counts: _P2AllPredicateCounts,
    p3_count: int,
) -> _P3ValidationOutcome:
    return (
        (
            failure[0],
            _P3_PREDICATE_PATH,
            selection_index,
            _coordinate_detail(selection_index, failure[1]),
        ),
        (*p2_counts, p3_count),
    )


def _validate_stage2f_p3(
    *,
    selections: tuple[_SelectionEvidence, ...],
    expected_execution_attestation_pairs: _ExecutionAttestationPairs,
    attested_execution_specification_ids: _AttestedSpecificationIds,
    p2_selections: tuple[_P2SelectionEvidence, ...],
    expected_predecessors: tuple[_OraclePredecessor, ...],
    validated_returned_results_by_role: tuple[
        _ReturnedResultsProjection,
        _ReturnedResultsProjection,
        _ReturnedResultsProjection,
        _ReturnedResultsProjection,
    ],
    p3_inputs: tuple[_P3SelectionInput, ...],
) -> _P3ValidationOutcome:
    """Validate frozen 3o.1 through 3o.5.1 in global family-major order."""

    p2_failure, p2_counts = _validate_stage2f_p2(
        selections=selections,
        expected_execution_attestation_pairs=expected_execution_attestation_pairs,
        attested_execution_specification_ids=attested_execution_specification_ids,
        p2_selections=p2_selections,
        expected_predecessors=expected_predecessors,
    )
    if p2_failure is not None:
        return p2_failure, (*p2_counts, 0)
    if (
        type(validated_returned_results_by_role) is not tuple
        or len(validated_returned_results_by_role) != 4
        or type(p3_inputs) is not tuple
        or len(p3_inputs) != _CANONICAL_SELECTION_COUNT
    ):
        return _p3_outcome(
            _selector_result_failure("canonical P3 input or role aggregate count differs"),
            0,
            p2_counts,
            0,
        )
    p3_count = 0
    for selection_index in range(_CANONICAL_SELECTION_COUNT):
        p3_count += 1
        failure = _predicate_3o_5_1(
            selections[selection_index],
            p2_selections[selection_index],
            expected_predecessors[selection_index],
            expected_execution_attestation_pairs,
            attested_execution_specification_ids,
            validated_returned_results_by_role,
            p3_inputs[selection_index],
            selection_index,
        )
        if failure is not None:
            return _p3_outcome(
                failure,
                selection_index,
                p2_counts,
                p3_count,
            )
    return None, (*p2_counts, p3_count)
