"""Stage-2F P3 pure calibration-selector replay semantic contract tests."""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
from collections import namedtuple
from collections.abc import Callable
from dataclasses import FrozenInstanceError, fields
from dataclasses import replace as dataclass_replace
from typing import Any, Literal, cast, get_type_hints

import pytest

from research_decision_engine.belief_models import MatchedEffectObservation
from research_decision_engine.benchmarks import broader_calibration_evidence as evidence
from research_decision_engine.benchmarks import (
    broader_calibration_selector_replay as selector_replay,
)
from research_decision_engine.benchmarks.broader_calibration_evidence import (
    ScientificCalibrationSelectionProjection,
    _decode_scientific_calibration_selection_projection,
    _scientific_calibration_selection_mapping,
)
from research_decision_engine.benchmarks.broader_calibration_history import (
    CalibrationHistorySelection,
    RunProvenanceError,
)
from research_decision_engine.benchmarks.broader_calibration_selector_replay import (
    replay_calibration_history_selection,
)
from research_decision_engine.benchmarks.broader_oracle import (
    CALIBRATION_NAMESPACE,
    RevealedObservation,
    calibration_key,
    transform_key,
)
from research_decision_engine.benchmarks.broader_protocol import (
    canonical_json_bytes,
    f64,
    protocol_hash,
    runtime_id,
)
from research_decision_engine.benchmarks.broader_returned_run import (
    ReturnedRunProjection,
    RunObservationAuthorizationProjection,
    RunRevealedObservationProjection,
)
from research_decision_engine.benchmarks.broader_worlds import (
    GROUP_IDS,
    WORLDS_BY_ID,
    candidate_costs,
    hidden_arm_mean,
    hidden_observation_sigma,
)
from research_decision_engine.reasoning import Provenance
from tests import p2_calibration_evidence_harness as harness

type Bundle = harness.P3ValidBundle
type Selection = harness.SelectionEvidence
type P2Selection = harness.P2SelectionEvidence
type P3Input = evidence._P3SelectionInput
type ReturnedResultsByRole = harness.ReturnedResultsByRole

_P3_CODE = "CALIBRATION_SELECTOR_RESULT_ID_MISMATCH"
_P3_PATH = "calibration/3o.5.1/selector_result"
_SELECTION_DOMAIN = "broader-calibration-history-selection/v1"
_FIXED_COORDINATE = ("primary_smoke", "h_adam_low", 9000, "group-00")
_FIXED_RUN_ID = "p3-witness/primary_smoke/h_adam_low/9000"
_FIXED_RETURNED_RESULT_ID = "47d400a20eb4b0eb3c2376a39fc866e79deafb3c86ec3ea422023f3c8fbb642b"
_FIXED_SUBMITTED_JOB_ID = "d3eff9e7cc7e39f6b705306a4b587211b473674293269b14f1b7dd967d6662ab"
_FIXED_IDENTITY = "1233abf97595dbd4bc01a3de7fe5ec0fa19ff8903ed5ff24c1f31c3cdb30e7b3"
_FIXED_ELIGIBILITY = (
    "exact frozen calibration namespace, world, seed, public comparison group, "
    "adam/sgd candidate pair, common replication, and availability sequence < 1"
)
_PROJECTION_FIELDS = (
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
_HISTORY_FIELDS = (
    "study_id",
    "world_id",
    "seed",
    "namespace",
    "comparison_group_id",
    "target_comparison_group_id",
    "source_sequence_cutoff",
    "source_effect_ids",
    "source_effect_payload_sha256",
    "source_observation_identities",
    "source_oracle_key_ids",
    "source_candidate_pairs",
    "source_replication_ids",
    "effect_values",
    "sample_count",
    "sample_mean",
    "sample_standard_deviation",
    "ddof",
    "sigma_floor",
    "estimated_sigma",
    "physical_cost",
    "eligibility_basis",
    "current_observation_excluded",
    "current_effect_excluded",
    "future_history_excluded",
    "effects",
    "observations",
    "selection_identity",
)
_REPLAY_KEYWORDS = (
    "run_id",
    "world_id",
    "seed",
    "comparison_group_id",
    "group_index",
    "expected_observations",
    "expected_effects",
    "physical_cost",
    "recorded_observations",
    "recorded_effects",
    "source_sequence_cutoff",
)
_OBSERVATION_FIELDS = (
    "oracle_key_id",
    "oracle_use_id",
    "authorization_id",
    "namespace",
    "world_id",
    "seed",
    "candidate_id",
    "comparison_group_id",
    "intervention_arm",
    "replication_id",
    "key_fields",
    "serialized_key_hex",
    "digest",
    "u",
    "z",
    "revealed_observation",
    "outcome_digest",
)
_EFFECT_FIELDS = (
    "effect_id",
    "comparison_group_id",
    "observed_effect",
    "available_sequence",
    "source_kind",
    "source_ids",
    "created_at",
    "provenance",
)
_FIXED_EFFECT_VALUES = (
    0.130804277077,
    0.088449984473,
    0.131450514832,
    0.095058300561,
    0.083784054071,
)
_FIXED_EFFECT_IDS = (
    "calibration-effect/calibration-prefix/h_adam_low/9000/group-00/calibration-00-r0001",
    "calibration-effect/calibration-prefix/h_adam_low/9000/group-00/calibration-00-r0002",
    "calibration-effect/calibration-prefix/h_adam_low/9000/group-00/calibration-00-r0003",
    "calibration-effect/calibration-prefix/h_adam_low/9000/group-00/calibration-00-r0004",
    "calibration-effect/calibration-prefix/h_adam_low/9000/group-00/calibration-00-r0005",
)
_FIXED_RAW_EFFECT_SHA256 = (
    "712c02f7e5681358167512c7f769eea8318bab6ed70ab4b2f021c5d2be3ee664",
    "358f14eb861c6b016d2ae48afeed77c9f1279679c8c206d553b2fa7b7f53a0f9",
    "6b38ce4ce695d3b38bf298a145223227830c819babdbc897e1ae251501399c11",
    "42effc6c677f9923eac8f27d1f40abb6283969c5d6c7ecc9868983d55e839c3f",
    "f4aad6c13fa947007f35f0561fb3492341bb7752039cb367e9644f4d3d53286c",
)
_FIXED_AUTHORIZATION_IDS = (
    "authorization:d7e0e5be794dc5e1d3d313f48f8dc1c8977bcf9134fb886aca7f7737e2934c22",
    "authorization:591d50b1632b7ecd50f18069815310e8470c2ac6fc3721ecb58020ecd93ee5d2",
    "authorization:0a4708bd369de40ea30b6b144810624af220d56e4907ec4781e5b75a9e8eec93",
    "authorization:16d0c7aa9e10566732e891352295783b49ab3c72ffbf304a9fbaa2a69f1cb533",
    "authorization:60bbcc0cf95a2ff16779dea07d46535c9843f24fd31517fd6b99439c2ce5c131",
    "authorization:b5e035839af94ac99dd4eff57f2075a1dfa56cffe2506fbf74f3219e30ba2291",
    "authorization:31bbd241d3c595d9a7f34975b20cdf8a2ab6cd8ebd5395c7eb8077353cb33f44",
    "authorization:efb820e7faaff63d069f63612012765f7706163ae73decf7218427c1bb6ee273",
    "authorization:a5e715034abe91f9decd4d203c95fb4a766c0491caeaf8c9b5178f3e06998af4",
    "authorization:60a9e03c650b4683b21d80ca3555a8848eaefefe26df99e561de0bfce9efd503",
)
_FIXED_ORACLE_USE_IDS = (
    "oracle-use/authorization:d7e0e5be794dc5e1d3d313f48f8dc1c8977bcf9134fb886aca7f7737e2934c22/oracle-key:ff24f37902c59ec5b15238a3148da85a534e43f5016d417bf2669e41666dd3b5",
    "oracle-use/authorization:591d50b1632b7ecd50f18069815310e8470c2ac6fc3721ecb58020ecd93ee5d2/oracle-key:8bfb0d09aad15aca6e082788857c491b170ebba38c01499e34aa2f455d65560d",
    "oracle-use/authorization:0a4708bd369de40ea30b6b144810624af220d56e4907ec4781e5b75a9e8eec93/oracle-key:bf2df369f8012ae8908f51a1f66550d2b8452063fb875e74ee91d7c186fb0f4c",
    "oracle-use/authorization:16d0c7aa9e10566732e891352295783b49ab3c72ffbf304a9fbaa2a69f1cb533/oracle-key:f97c0e1e896ae6ec7a128a2d0d29ac3befe22ad84e8eb550673a7b53f82ff728",
    "oracle-use/authorization:60bbcc0cf95a2ff16779dea07d46535c9843f24fd31517fd6b99439c2ce5c131/oracle-key:55cfac0574b8c79feda1a0b268c1d5fff761d3da66e15db3be383a23693df9e9",
    "oracle-use/authorization:b5e035839af94ac99dd4eff57f2075a1dfa56cffe2506fbf74f3219e30ba2291/oracle-key:d0afd48529e262ff2d20a7ce6ef4728ba05a499c7b9e0033ccac0b2a9f76274a",
    "oracle-use/authorization:31bbd241d3c595d9a7f34975b20cdf8a2ab6cd8ebd5395c7eb8077353cb33f44/oracle-key:c7031acfb6a7ce463f1d8627a5b0df87de8512cba349ae5cc54238638d9bf748",
    "oracle-use/authorization:efb820e7faaff63d069f63612012765f7706163ae73decf7218427c1bb6ee273/oracle-key:16c4fb9a27f7f44284b3b638c4ed758b00e8522a947c7c2c27fe982acc7cc5c5",
    "oracle-use/authorization:a5e715034abe91f9decd4d203c95fb4a766c0491caeaf8c9b5178f3e06998af4/oracle-key:136ff4b3eb2d482806b3667897bf5f089d6af3d90496dc907139e476b9a202e1",
    "oracle-use/authorization:60a9e03c650b4683b21d80ca3555a8848eaefefe26df99e561de0bfce9efd503/oracle-key:84673a8c3e2b5c3cee9e441512f3f84fae6b1653faea3b8abe76abe402fef709",
)

# Complete literal 21-field A preimage.  It was derived once from the
# test-owned formulas and is never generated by replay or either validator.
_FIXED_A_MAPPING: dict[str, object] = {
    "comparison_group_id": "group-00",
    "ddof": 1,
    "effect_values": [
        "f64:3fc0be31ce1c7f62",
        "f64:3fb6a4a87ea4ab8f",
        "f64:3fc0d35ed71f7678",
        "f64:3fb855bda41f7203",
        "f64:3fb572df2c294711",
    ],
    "eligibility_basis": _FIXED_ELIGIBILITY,
    "estimated_sigma": "f64:3fa999999999999a",
    "namespace": "rde.broader.calibration-outcome/v1",
    "sample_count": 5,
    "sample_mean": "f64:3fbb1ce151e11011",
    "sample_standard_deviation": "f64:3f97edb8f12bfcb4",
    "seed": 9000,
    "sigma_floor": "f64:3fa999999999999a",
    "source_candidate_pairs": [
        ["cal-00-adam-r0001", "cal-00-sgd-r0001"],
        ["cal-00-adam-r0002", "cal-00-sgd-r0002"],
        ["cal-00-adam-r0003", "cal-00-sgd-r0003"],
        ["cal-00-adam-r0004", "cal-00-sgd-r0004"],
        ["cal-00-adam-r0005", "cal-00-sgd-r0005"],
    ],
    "source_effect_ids": list(_FIXED_EFFECT_IDS),
    "source_effect_payload_sha256": list(_FIXED_RAW_EFFECT_SHA256),
    "source_observation_identities": [
        [
            "oracle-key:ff24f37902c59ec5b15238a3148da85a534e43f5016d417bf2669e41666dd3b5",
            "9693b57f4ef37ad5cf70346d3b29ccb3e3e45471bbd7701d83f4d829c28f048c",
        ],
        [
            "oracle-key:8bfb0d09aad15aca6e082788857c491b170ebba38c01499e34aa2f455d65560d",
            "ae9501f2112e60ce3dc8c09839bb4c5781168c2132a0a813860263091a7976aa",
        ],
        [
            "oracle-key:bf2df369f8012ae8908f51a1f66550d2b8452063fb875e74ee91d7c186fb0f4c",
            "2996852520062fdc8da6a35dc3274a4a88c1c8ec8ae294f01a615121d1dec663",
        ],
        [
            "oracle-key:f97c0e1e896ae6ec7a128a2d0d29ac3befe22ad84e8eb550673a7b53f82ff728",
            "dbb77431aabdc21a8c8c44d1ee30753f1270bddf3251c1f1622e9ceffdfea300",
        ],
        [
            "oracle-key:55cfac0574b8c79feda1a0b268c1d5fff761d3da66e15db3be383a23693df9e9",
            "3b3a4dd35ffcfc4a08588cb920bff14eb33ab74ade4f829d744150824d1b34ec",
        ],
        [
            "oracle-key:d0afd48529e262ff2d20a7ce6ef4728ba05a499c7b9e0033ccac0b2a9f76274a",
            "b39890bb7580438356e8efb9f292ff587fd4cc7e3b1348e81619fff351064ea1",
        ],
        [
            "oracle-key:c7031acfb6a7ce463f1d8627a5b0df87de8512cba349ae5cc54238638d9bf748",
            "8a9d0f9095a8403814c554e112ba87af92a5f83b8a6170f96b0610c9586ece29",
        ],
        [
            "oracle-key:16c4fb9a27f7f44284b3b638c4ed758b00e8522a947c7c2c27fe982acc7cc5c5",
            "74b8b8d6790640bc8698a4d0c81dd17beb5c6a398ec523bca96114400022b3f2",
        ],
        [
            "oracle-key:136ff4b3eb2d482806b3667897bf5f089d6af3d90496dc907139e476b9a202e1",
            "6bcf9470f9b908012a29ded02879efeaf0ac7d890f1ebe21edb9f59a15b701e6",
        ],
        [
            "oracle-key:84673a8c3e2b5c3cee9e441512f3f84fae6b1653faea3b8abe76abe402fef709",
            "c39d5f7b036a4133ae2fc56d45944c7681fb8bc7b2e2da7c722603d051db7783",
        ],
    ],
    "source_oracle_key_ids": [
        "oracle-key:ff24f37902c59ec5b15238a3148da85a534e43f5016d417bf2669e41666dd3b5",
        "oracle-key:8bfb0d09aad15aca6e082788857c491b170ebba38c01499e34aa2f455d65560d",
        "oracle-key:bf2df369f8012ae8908f51a1f66550d2b8452063fb875e74ee91d7c186fb0f4c",
        "oracle-key:f97c0e1e896ae6ec7a128a2d0d29ac3befe22ad84e8eb550673a7b53f82ff728",
        "oracle-key:55cfac0574b8c79feda1a0b268c1d5fff761d3da66e15db3be383a23693df9e9",
        "oracle-key:d0afd48529e262ff2d20a7ce6ef4728ba05a499c7b9e0033ccac0b2a9f76274a",
        "oracle-key:c7031acfb6a7ce463f1d8627a5b0df87de8512cba349ae5cc54238638d9bf748",
        "oracle-key:16c4fb9a27f7f44284b3b638c4ed758b00e8522a947c7c2c27fe982acc7cc5c5",
        "oracle-key:136ff4b3eb2d482806b3667897bf5f089d6af3d90496dc907139e476b9a202e1",
        "oracle-key:84673a8c3e2b5c3cee9e441512f3f84fae6b1653faea3b8abe76abe402fef709",
    ],
    "source_replication_ids": [
        "calibration-00-r0001",
        "calibration-00-r0002",
        "calibration-00-r0003",
        "calibration-00-r0004",
        "calibration-00-r0005",
    ],
    "source_sequence_cutoff": 1,
    "study_id": "broader-closed-loop-replication/v1",
    "target_comparison_group_id": "group-00",
    "world_id": "h_adam_low",
}

# Fields 1-25 and 28 of the fixed complete helper vector.  Fields 26 and 27
# are independently reconstructed below and inserted in declaration order.
_FIXED_HELPER_SCALARS: dict[str, object] = {
    "study_id": "broader-closed-loop-replication/v1",
    "world_id": "h_adam_low",
    "seed": 9000,
    "namespace": "rde.broader.calibration-outcome/v1",
    "comparison_group_id": "group-00",
    "target_comparison_group_id": "group-00",
    "source_sequence_cutoff": 1,
    "source_effect_ids": _FIXED_EFFECT_IDS,
    "source_effect_payload_sha256": _FIXED_RAW_EFFECT_SHA256,
    "source_observation_identities": tuple(
        tuple(pair)
        for pair in cast(list[list[str]], _FIXED_A_MAPPING["source_observation_identities"])
    ),
    "source_oracle_key_ids": tuple(cast(list[str], _FIXED_A_MAPPING["source_oracle_key_ids"])),
    "source_candidate_pairs": tuple(
        tuple(pair) for pair in cast(list[list[str]], _FIXED_A_MAPPING["source_candidate_pairs"])
    ),
    "source_replication_ids": tuple(cast(list[str], _FIXED_A_MAPPING["source_replication_ids"])),
    "effect_values": _FIXED_EFFECT_VALUES,
    "sample_count": 5,
    "sample_mean": 0.10590942620279999,
    "sample_standard_deviation": 0.023367776603660587,
    "ddof": 1,
    "sigma_floor": 0.05,
    "estimated_sigma": 0.05,
    "physical_cost": 10.0,
    "eligibility_basis": _FIXED_ELIGIBILITY,
    "current_observation_excluded": True,
    "current_effect_excluded": True,
    "future_history_excluded": True,
    "selection_identity": _FIXED_IDENTITY,
}


class _Text(str):
    pass


class _Mapping(dict[str, object]):
    pass


class _ProjectionSubclass(ScientificCalibrationSelectionProjection):
    pass


class _Trap:
    calls = 0

    def __getattr__(self, name: str) -> object:
        type(self).calls += 1
        raise AssertionError(name)

    def __iter__(self) -> Any:
        type(self).calls += 1
        raise AssertionError("iter")

    def __eq__(self, other: object) -> bool:
        type(self).calls += 1
        raise AssertionError("eq")

    def __bool__(self) -> bool:
        type(self).calls += 1
        raise AssertionError("bool")


_ProjectionTuple = namedtuple(
    "_ProjectionTuple",
    (
        "comparison_group_id ddof effect_values eligibility_basis estimated_sigma "
        "namespace sample_count sample_mean sample_standard_deviation seed sigma_floor "
        "source_candidate_pairs source_effect_ids source_effect_payload_sha256 "
        "source_observation_identities source_oracle_key_ids source_replication_ids "
        "source_sequence_cutoff study_id target_comparison_group_id world_id"
    ),
)


@pytest.fixture(scope="module")
def p3_bundle() -> Bundle:
    return harness.build_valid_p3_bundle()


@pytest.fixture(scope="module")
def fixed_projection() -> ScientificCalibrationSelectionProjection:
    return _decode_scientific_calibration_selection_projection(
        {
            **_FIXED_A_MAPPING,
            "effect_values": list(cast(list[str], _FIXED_A_MAPPING["effect_values"])),
            "source_candidate_pairs": [
                list(pair)
                for pair in cast(
                    list[list[str]],
                    _FIXED_A_MAPPING["source_candidate_pairs"],
                )
            ],
            "source_effect_ids": list(cast(list[str], _FIXED_A_MAPPING["source_effect_ids"])),
            "source_effect_payload_sha256": list(
                cast(list[str], _FIXED_A_MAPPING["source_effect_payload_sha256"])
            ),
            "source_observation_identities": [
                list(pair)
                for pair in cast(
                    list[list[str]],
                    _FIXED_A_MAPPING["source_observation_identities"],
                )
            ],
            "source_oracle_key_ids": list(
                cast(list[str], _FIXED_A_MAPPING["source_oracle_key_ids"])
            ),
            "source_replication_ids": list(
                cast(list[str], _FIXED_A_MAPPING["source_replication_ids"])
            ),
        }
    )


def _alternate_h64(value: str) -> str:
    return "1" * 64 if value == "0" * 64 else "0" * 64


def _at[T](values: tuple[T, ...], index: int, value: T) -> tuple[T, ...]:
    return (*values[:index], value, *values[index + 1 :])


def _scope(
    bundle: Bundle,
    index: int = 0,
) -> tuple[Selection, P2Selection, harness.OraclePredecessor, P3Input]:
    return bundle[0][index], bundle[3][index], bundle[4][index], bundle[6][index]


def _predicate(
    bundle: Bundle,
    *,
    index: int = 0,
    selection: Selection | None = None,
    returned_results: ReturnedResultsByRole | None = None,
    p3_input: P3Input | None = None,
) -> evidence._PredicateFailure | None:
    valid_selection, p2_selection, predecessor, valid_p3_input = _scope(bundle, index)
    return evidence._predicate_3o_5_1(
        valid_selection if selection is None else selection,
        p2_selection,
        predecessor,
        bundle[1],
        bundle[2],
        bundle[5] if returned_results is None else returned_results,
        valid_p3_input if p3_input is None else p3_input,
        index,
    )


def _validate(
    bundle: Bundle,
    *,
    selections: tuple[Selection, ...] | None = None,
    p2_selections: tuple[P2Selection, ...] | None = None,
    predecessors: tuple[harness.OraclePredecessor, ...] | None = None,
    returned_results: ReturnedResultsByRole | None = None,
    p3_inputs: tuple[P3Input, ...] | None = None,
) -> evidence._P3ValidationOutcome:
    return evidence._validate_stage2f_p3(
        selections=bundle[0] if selections is None else selections,
        expected_execution_attestation_pairs=bundle[1],
        attested_execution_specification_ids=bundle[2],
        p2_selections=bundle[3] if p2_selections is None else p2_selections,
        expected_predecessors=bundle[4] if predecessors is None else predecessors,
        validated_returned_results_by_role=(
            bundle[5] if returned_results is None else returned_results
        ),
        p3_inputs=bundle[6] if p3_inputs is None else p3_inputs,
    )


def _unsafe_projection(
    projection: ScientificCalibrationSelectionProjection,
    **changes: object,
) -> ScientificCalibrationSelectionProjection:
    result = object.__new__(ScientificCalibrationSelectionProjection)
    for field in fields(ScientificCalibrationSelectionProjection):
        object.__setattr__(
            result,
            field.name,
            changes.get(field.name, getattr(projection, field.name)),
        )
    return result


def _unsafe_subclass(
    projection: ScientificCalibrationSelectionProjection,
) -> ScientificCalibrationSelectionProjection:
    result = object.__new__(_ProjectionSubclass)
    for field in fields(ScientificCalibrationSelectionProjection):
        object.__setattr__(result, field.name, getattr(projection, field.name))
    return cast(ScientificCalibrationSelectionProjection, result)


def _replace_history(
    history: CalibrationHistorySelection,
    **changes: object,
) -> CalibrationHistorySelection:
    replace_call = cast(Callable[..., CalibrationHistorySelection], dataclass_replace)
    return replace_call(history, **changes)


def _replace_p3_input(
    p3_input: P3Input,
    **changes: object,
) -> P3Input:
    replace_call = cast(Callable[..., P3Input], dataclass_replace)
    return replace_call(p3_input, **changes)


def _copy_preimage() -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in _FIXED_A_MAPPING.items():
        if type(value) is list:
            result[key] = [
                list(item) if type(item) is list else item for item in cast(list[object], value)
            ]
        else:
            result[key] = value
    return result


def _changed_preimage(field_name: str) -> dict[str, object]:
    mapping = _copy_preimage()
    replacements: dict[str, object] = {
        "comparison_group_id": "group-01",
        "ddof": 2,
        "eligibility_basis": "different frozen eligibility basis",
        "estimated_sigma": "f64:3fb999999999999a",
        "namespace": "rde.broader.calibration-outcome/v2",
        "sample_count": 4,
        "sample_mean": "f64:0000000000000000",
        "sample_standard_deviation": "f64:0000000000000000",
        "seed": 9001,
        "sigma_floor": "f64:3fb999999999999a",
        "source_sequence_cutoff": 0,
        "study_id": "different-study/v1",
        "target_comparison_group_id": "group-01",
        "world_id": "d2_null",
    }
    if field_name == "effect_values":
        values = cast(list[str], mapping[field_name])
        mapping[field_name] = ["f64:0000000000000000", *values[1:]]
    elif field_name == "source_candidate_pairs":
        candidate_pairs = cast(list[list[str]], mapping[field_name])
        mapping[field_name] = [
            ["cal-00-adam-r9999", candidate_pairs[0][1]],
            *candidate_pairs[1:],
        ]
    elif field_name == "source_effect_ids":
        values = cast(list[str], mapping[field_name])
        mapping[field_name] = ["calibration-effect/different", *values[1:]]
    elif field_name == "source_effect_payload_sha256":
        values = cast(list[str], mapping[field_name])
        mapping[field_name] = [_alternate_h64(values[0]), *values[1:]]
    elif field_name == "source_observation_identities":
        observation_identities = cast(list[list[str]], mapping[field_name])
        mapping[field_name] = [
            [
                observation_identities[0][0],
                _alternate_h64(observation_identities[0][1]),
            ],
            *observation_identities[1:],
        ]
    elif field_name == "source_oracle_key_ids":
        oracle_key_ids = cast(list[str], mapping[field_name])
        mapping[field_name] = [f"oracle-key:{'0' * 64}", *oracle_key_ids[1:]]
    elif field_name == "source_replication_ids":
        replication_ids = cast(list[str], mapping[field_name])
        mapping[field_name] = ["calibration-00-r9999", *replication_ids[1:]]
    else:
        mapping[field_name] = replacements[field_name]
    return mapping


def test_scientific_projection_and_private_input_surfaces_are_exact(
    p3_bundle: Bundle,
) -> None:
    projection = p3_bundle[6][0].selector_result_projection
    expected_hints = {
        "comparison_group_id": str,
        "ddof": int,
        "effect_values": tuple[str, ...],
        "eligibility_basis": str,
        "estimated_sigma": str,
        "namespace": str,
        "sample_count": int,
        "sample_mean": str,
        "sample_standard_deviation": str,
        "seed": int,
        "sigma_floor": str,
        "source_candidate_pairs": tuple[tuple[str, str], ...],
        "source_effect_ids": tuple[str, ...],
        "source_effect_payload_sha256": tuple[str, ...],
        "source_observation_identities": tuple[tuple[str, str], ...],
        "source_oracle_key_ids": tuple[str, ...],
        "source_replication_ids": tuple[str, ...],
        "source_sequence_cutoff": int,
        "study_id": str,
        "target_comparison_group_id": str,
        "world_id": str,
    }
    assert ScientificCalibrationSelectionProjection.__bases__ == (object,)
    assert tuple(field.name for field in fields(ScientificCalibrationSelectionProjection)) == (
        _PROJECTION_FIELDS
    )
    assert get_type_hints(ScientificCalibrationSelectionProjection) == expected_hints
    assert ScientificCalibrationSelectionProjection.__slots__ == _PROJECTION_FIELDS
    assert "__dict__" not in ScientificCalibrationSelectionProjection.__slots__
    with pytest.raises(FrozenInstanceError):
        projection.seed = 1  # type: ignore[misc]

    p3_type = type(p3_bundle[6][0])
    assert p3_type.__name__ == "_P3SelectionInput"
    assert tuple(field.name for field in fields(p3_type)) == harness.P3_INPUT_FIELD_NAMES
    assert p3_type.__slots__ == harness.P3_INPUT_FIELD_NAMES
    assert "__dict__" not in p3_type.__slots__
    with pytest.raises(FrozenInstanceError):
        p3_bundle[6][0].submitted_job_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "case",
    ("missing", "extra", "reordered", "mapping-subclass", "list", "hostile"),
    ids=(
        "missing-field",
        "extra-field",
        "same-fields-reordered",
        "mapping-subclass",
        "non-mapping-list",
        "hostile-object",
    ),
)
def test_decoder_rejects_nonclosed_mapping_shapes_without_hooks(
    case: str,
    fixed_projection: ScientificCalibrationSelectionProjection,
) -> None:
    mapping = harness.scientific_selection_mapping(fixed_projection)
    values: dict[str, object] = {
        "missing": dict(tuple(mapping.items())[:-1]),
        "extra": {**mapping, "extra": "x"},
        "reordered": dict(reversed(tuple(mapping.items()))),
        "mapping-subclass": _Mapping(mapping),
        "list": list(mapping.items()),
        "hostile": _Trap(),
    }
    _Trap.calls = 0
    with pytest.raises(ValueError):
        _decode_scientific_calibration_selection_projection(values[case])
    if case == "hostile":
        assert _Trap.calls == 0


@pytest.mark.parametrize(
    "case",
    (
        "effect-values",
        "candidate-pairs-outer",
        "candidate-pair-inner",
        "observation-identities-outer",
        "observation-identity-inner",
    ),
    ids=(
        "effect-values-must-be-list",
        "candidate-pairs-must-be-list",
        "candidate-pair-must-be-list",
        "observation-identities-must-be-list",
        "observation-identity-must-be-list",
    ),
)
def test_decoder_requires_exact_closed_list_wire_forms(
    case: str,
    fixed_projection: ScientificCalibrationSelectionProjection,
) -> None:
    checks: list[tuple[str, dict[str, object], bool, int | None]] = []
    if case == "effect-values":
        for field_name in (
            "effect_values",
            "source_effect_ids",
            "source_effect_payload_sha256",
            "source_oracle_key_ids",
            "source_replication_ids",
        ):
            mapping = harness.scientific_selection_mapping(fixed_projection)
            mapping[field_name] = tuple(cast(list[object], mapping[field_name]))
            checks.append((f"{field_name}-must-be-list", mapping, False, None))
        for label, seed, accepted in (
            ("i64-minimum", -(1 << 63), True),
            ("i64-maximum", (1 << 63) - 1, True),
            ("i64-underflow", -(1 << 63) - 1, False),
            ("i64-overflow", 1 << 63, False),
        ):
            mapping = harness.scientific_selection_mapping(fixed_projection)
            mapping["seed"] = seed
            checks.append((label, mapping, accepted, seed if accepted else None))
        for label, encoded in (
            ("f64-positive-infinity", "f64:7ff0000000000000"),
            ("f64-negative-infinity", "f64:fff0000000000000"),
            ("f64-nan", "f64:7ff8000000000000"),
        ):
            mapping = harness.scientific_selection_mapping(fixed_projection)
            mapping["sample_mean"] = encoded
            checks.append((label, mapping, False, None))
    elif case == "candidate-pairs-outer":
        mapping = harness.scientific_selection_mapping(fixed_projection)
        mapping["source_candidate_pairs"] = tuple(
            cast(list[list[str]], mapping["source_candidate_pairs"])
        )
        checks.append(("candidate-pairs-outer-must-be-list", mapping, False, None))
    elif case == "candidate-pair-inner":
        mapping = harness.scientific_selection_mapping(fixed_projection)
        pairs = cast(list[list[str]], mapping["source_candidate_pairs"])
        mapping["source_candidate_pairs"] = [tuple(pairs[0]), *pairs[1:]]
        checks.append(("candidate-pair-must-be-list", mapping, False, None))
    elif case == "observation-identities-outer":
        mapping = harness.scientific_selection_mapping(fixed_projection)
        mapping["source_observation_identities"] = tuple(
            cast(list[list[str]], mapping["source_observation_identities"])
        )
        checks.append(("observation-identities-outer-must-be-list", mapping, False, None))
    else:
        mapping = harness.scientific_selection_mapping(fixed_projection)
        identities = cast(list[list[str]], mapping["source_observation_identities"])
        mapping["source_observation_identities"] = [
            tuple(identities[0]),
            *identities[1:],
        ]
        checks.append(("observation-identity-must-be-list", mapping, False, None))
    failures: list[str] = []
    for label, mapping, accepted, expected_seed in checks:
        try:
            decoded = _decode_scientific_calibration_selection_projection(mapping)
        except ValueError:
            if accepted:
                failures.append(f"{label}: rejected")
        except Exception as error:
            failures.append(f"{label}: wrong exception {type(error).__name__}: {error}")
        else:
            if not accepted:
                failures.append(f"{label}: accepted")
            elif decoded.seed != expected_seed:
                failures.append(
                    f"{label}: decoded seed {decoded.seed!r}, expected {expected_seed!r}"
                )
    assert failures == []


@pytest.mark.parametrize(
    "case",
    ("tuple-closure", "nested-closure", "bool-int", "hash-case", "text-boundary"),
    ids=(
        "tuple-fields-are-exact",
        "nested-tuples-are-exact",
        "bool-is-not-i64",
        "hash-is-lowercase",
        "nfc-and-exact-text",
    ),
)
def test_projection_constructor_rejects_every_closed_runtime_violation(
    case: str,
    fixed_projection: ScientificCalibrationSelectionProjection,
) -> None:
    projection = fixed_projection
    bad: dict[str, tuple[tuple[str, object], ...]] = {
        "tuple-closure": (
            ("effect_values", list(projection.effect_values)),
            ("source_effect_ids", list(projection.source_effect_ids)),
        ),
        "nested-closure": (
            (
                "source_candidate_pairs",
                (
                    list(projection.source_candidate_pairs[0]),
                    *projection.source_candidate_pairs[1:],
                ),
            ),
            (
                "source_observation_identities",
                (
                    list(projection.source_observation_identities[0]),
                    *projection.source_observation_identities[1:],
                ),
            ),
        ),
        "bool-int": (("seed", True), ("source_sequence_cutoff", True)),
        "hash-case": (
            (
                "source_effect_payload_sha256",
                (
                    projection.source_effect_payload_sha256[0].upper(),
                    *projection.source_effect_payload_sha256[1:],
                ),
            ),
        ),
        "text-boundary": (
            ("comparison_group_id", _Text(projection.comparison_group_id)),
            ("eligibility_basis", "cafe\u0301"),
            ("eligibility_basis", "\ud800"),
            ("sample_mean", 0.0),
        ),
    }
    failures: list[str] = []
    for field_name, value in bad[case]:
        try:
            harness.replace_scientific_selection_projection(
                projection,
                **{field_name: value},
            )
        except ValueError:
            continue
        failures.append(field_name)
    assert failures == []


def test_projection_mapping_and_decoder_boundaries_execute_no_caller_hooks(
    fixed_projection: ScientificCalibrationSelectionProjection,
) -> None:
    projection = fixed_projection
    named = _ProjectionTuple(*(getattr(projection, name) for name in _PROJECTION_FIELDS))
    _Trap.calls = 0
    for hostile in (
        _unsafe_subclass(projection),
        _Trap(),
        harness.scientific_selection_mapping(projection),
        named,
    ):
        with pytest.raises(ValueError):
            _scientific_calibration_selection_mapping(cast(Any, hostile))
    mapping = harness.scientific_selection_mapping(projection)
    values = cast(list[object], mapping["effect_values"])
    mapping["effect_values"] = [_Trap(), *values[1:]]
    with pytest.raises(ValueError):
        _decode_scientific_calibration_selection_projection(mapping)
    assert _Trap.calls == 0


def test_complete_literal_21_field_preimage_has_the_frozen_known_identity(
    fixed_projection: ScientificCalibrationSelectionProjection,
) -> None:
    assert tuple(_FIXED_A_MAPPING) == _PROJECTION_FIELDS
    assert harness.scientific_selection_mapping(fixed_projection) == _FIXED_A_MAPPING
    assert protocol_hash(_SELECTION_DOMAIN, _FIXED_A_MAPPING) == _FIXED_IDENTITY


@pytest.mark.parametrize(
    "field_name",
    _PROJECTION_FIELDS,
    ids=tuple(f"identity-sensitive-{name}" for name in _PROJECTION_FIELDS),
)
def test_every_scientific_projection_field_is_identity_sensitive(
    field_name: str,
) -> None:
    assert protocol_hash(_SELECTION_DOMAIN, _changed_preimage(field_name)) != _FIXED_IDENTITY


def _independent_expected_science(
    bundle: Bundle,
) -> tuple[
    tuple[RevealedObservation, ...],
    tuple[MatchedEffectObservation, ...],
]:
    selection, _p2_selection, _predecessor, p3_input = _scope(bundle)
    world_id = selection[harness.WORLD_ID_INDEX]
    seed = selection[harness.SEED_INDEX]
    comparison_group_id = selection[harness.COMPARISON_GROUP_ID_INDEX]
    group_index = GROUP_IDS.index(comparison_group_id)
    prefix_id = selection[harness.CALIBRATION_PREFIX_ID_INDEX]
    world = WORLDS_BY_ID[world_id]
    candidate_pairs = selection[harness.ORDERED_CANDIDATE_PAIRS_INDEX]
    replication_ids = selection[harness.ORDERED_REPLICATION_IDS_INDEX]
    observations: list[RevealedObservation] = []
    for observation_index in range(10):
        pair_index, arm_index = divmod(observation_index, 2)
        arm: Literal["adam", "sgd"] = "adam" if arm_index == 0 else "sgd"
        candidate_id = candidate_pairs[pair_index][arm_index]
        replication_id = replication_ids[pair_index]
        key_fields = calibration_key(
            world_id=world_id,
            seed=seed,
            comparison_group_id=comparison_group_id,
            intervention_arm=arm,
            replication_id=replication_id,
            namespace=CALIBRATION_NAMESPACE,
        )
        transform = transform_key(key_fields)
        base_candidate_id = f"g{group_index:02d}-{arm}-r1"
        revealed_observation = hidden_arm_mean(
            world,
            base_candidate_id,
        ) + (hidden_observation_sigma(world, base_candidate_id) * transform.z)
        oracle_key_id = runtime_id(
            "oracle-key",
            "oracle_key_id/v1",
            {"key_fields": list(key_fields)},
        )
        authorization_id = runtime_id(
            "authorization",
            "authorization_id/v1",
            {
                "candidate_id": candidate_id,
                "kind": "calibration",
                "run_id": p3_input.returned_run_projection.run_id,
                "source_id": f"{prefix_id}/{candidate_id}",
            },
        )
        outcome_digest = protocol_hash(
            "revealed_outcome/v1",
            {
                "oracle_key_id": oracle_key_id,
                "revealed_observation": f64(revealed_observation),
            },
        )
        observations.append(
            RevealedObservation(
                oracle_key_id=oracle_key_id,
                oracle_use_id=f"oracle-use/{authorization_id}/{oracle_key_id}",
                authorization_id=authorization_id,
                namespace=CALIBRATION_NAMESPACE,
                world_id=world_id,
                seed=seed,
                candidate_id=candidate_id,
                comparison_group_id=comparison_group_id,
                intervention_arm=arm,
                replication_id=replication_id,
                key_fields=key_fields,
                serialized_key_hex=transform.serialized_key.hex(),
                digest=transform.digest_hex,
                u=transform.u_string,
                z=transform.z_string,
                revealed_observation=revealed_observation,
                outcome_digest=outcome_digest,
            )
        )

    effects: list[MatchedEffectObservation] = []
    for effect_index in range(5):
        replication_index = effect_index + 1
        replication_id = replication_ids[effect_index]
        effect_value = round(
            observations[2 * effect_index].revealed_observation
            - observations[2 * effect_index + 1].revealed_observation,
            12,
        )
        effects.append(
            MatchedEffectObservation(
                effect_id=f"calibration-effect/{prefix_id}/{replication_id}",
                comparison_group_id=comparison_group_id,
                observed_effect=effect_value,
                available_sequence=0,
                source_kind="calibration",
                source_ids=candidate_pairs[effect_index],
                created_at=(
                    f"2000-01-01T00:00:00.000000Z#calibration:{group_index}:{replication_index}"
                ),
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
        )
    return tuple(observations), tuple(effects)


def _assert_run_observation(
    actual: RunRevealedObservationProjection,
    expected: RevealedObservation,
    run_id: str,
    prefix_id: str,
) -> None:
    expected_authorization = RunObservationAuthorizationProjection(
        candidate_id=expected.candidate_id,
        kind="calibration",
        run_id=run_id,
        source_id=f"{prefix_id}/{expected.candidate_id}",
    )
    assert actual.authorization == expected_authorization
    assert actual.authorization_id == expected.authorization_id
    assert actual.candidate_id == expected.candidate_id
    assert actual.comparison_group_id == expected.comparison_group_id
    assert actual.digest == expected.digest
    assert actual.intervention_arm == expected.intervention_arm
    assert actual.key_fields == expected.key_fields
    assert actual.namespace == expected.namespace
    assert actual.oracle_key_id == expected.oracle_key_id
    assert actual.oracle_use_id == expected.oracle_use_id
    assert actual.outcome_digest == expected.outcome_digest
    assert actual.replication_id == expected.replication_id
    assert actual.revealed_observation == f64(expected.revealed_observation)
    assert actual.seed == expected.seed
    assert actual.serialized_key_hex == expected.serialized_key_hex
    assert actual.u == expected.u
    assert actual.world_id == expected.world_id
    assert actual.z == expected.z


def test_fixed_witness_observation_effect_and_complete_helper_vectors(
    p3_bundle: Bundle,
) -> None:
    selection, p2_selection, _predecessor, p3_input = _scope(p3_bundle)
    run = p3_input.returned_run_projection
    assert run.calibration is not None
    estimate = run.calibration.estimates[0]
    history = selection[harness.SELECTOR_RESULT_INDEX]
    expected_observations, expected_effects = _independent_expected_science(p3_bundle)

    assert harness.CANONICAL_COORDINATES[0] == _FIXED_COORDINATE
    assert run.run_id == _FIXED_RUN_ID
    assert p3_input.returned_result_id == _FIXED_RETURNED_RESULT_ID
    assert p3_input.submitted_job_id == _FIXED_SUBMITTED_JOB_ID
    assert tuple(field.name for field in fields(RevealedObservation)) == _OBSERVATION_FIELDS
    assert tuple(field.name for field in fields(MatchedEffectObservation)) == _EFFECT_FIELDS
    assert tuple(field.name for field in fields(CalibrationHistorySelection)) == _HISTORY_FIELDS

    assert tuple(item.authorization_id for item in expected_observations) == (
        _FIXED_AUTHORIZATION_IDS
    )
    assert tuple(item.oracle_use_id for item in expected_observations) == (_FIXED_ORACLE_USE_IDS)
    assert tuple(item.effect_id for item in expected_effects) == _FIXED_EFFECT_IDS
    assert tuple(item.observed_effect for item in expected_effects) == _FIXED_EFFECT_VALUES
    assert (
        tuple(
            hashlib.sha256(canonical_json_bytes(item.to_dict(), final_lf=True)).hexdigest()
            for item in expected_effects
        )
        == _FIXED_RAW_EFFECT_SHA256
    )

    assert history.observations == expected_observations
    assert history.effects == expected_effects
    assert tuple(item.authorization_id for item in estimate.observations) == (
        _FIXED_AUTHORIZATION_IDS
    )
    assert tuple(item.oracle_use_id for item in estimate.observations) == (_FIXED_ORACLE_USE_IDS)
    assert tuple(
        (item.candidate_id, item.intervention_arm, item.replication_id)
        for item in expected_observations
    ) == tuple(
        (
            f"cal-00-{'adam' if index % 2 == 0 else 'sgd'}-r{index // 2 + 1:04d}",
            "adam" if index % 2 == 0 else "sgd",
            f"calibration-00-r{index // 2 + 1:04d}",
        )
        for index in range(10)
    )

    prefix_id = selection[harness.CALIBRATION_PREFIX_ID_INDEX]
    for index in range(10):
        _assert_run_observation(
            estimate.observations[index],
            expected_observations[index],
            run.run_id,
            prefix_id,
        )
        source_projection = p2_selection[harness.P2_ORDERED_SOURCE_OBSERVATIONS_INDEX][index][0]
        expected = expected_observations[index]
        assert source_projection.candidate_id == expected.candidate_id
        assert source_projection.comparison_group_id == expected.comparison_group_id
        assert source_projection.digest == expected.digest
        assert source_projection.intervention_arm == expected.intervention_arm
        assert source_projection.key_fields == expected.key_fields
        assert source_projection.namespace == expected.namespace
        assert source_projection.oracle_key_id == expected.oracle_key_id
        assert source_projection.outcome_digest == expected.outcome_digest
        assert source_projection.replication_id == expected.replication_id
        assert source_projection.revealed_observation == f64(expected.revealed_observation)
        assert source_projection.seed == expected.seed
        assert source_projection.serialized_key_hex == expected.serialized_key_hex
        assert source_projection.u == expected.u
        assert source_projection.world_id == expected.world_id
        assert source_projection.z == expected.z

    fixed_helper: dict[str, object] = {}
    for field_name in _HISTORY_FIELDS:
        if field_name == "effects":
            fixed_helper[field_name] = expected_effects
        elif field_name == "observations":
            fixed_helper[field_name] = expected_observations
        else:
            fixed_helper[field_name] = _FIXED_HELPER_SCALARS[field_name]
    assert tuple(fixed_helper) == _HISTORY_FIELDS
    assert {
        field_name: getattr(history, field_name) for field_name in _HISTORY_FIELDS
    } == fixed_helper

    scientific_mapping = harness.scientific_selection_mapping(p3_input.selector_result_projection)
    for excluded in (
        "run_id",
        "authorization",
        "authorization_id",
        "oracle_use_id",
        "physical_cost",
    ):
        assert excluded not in scientific_mapping


def _capture_once(
    bundle: Bundle,
    monkeypatch: pytest.MonkeyPatch,
    *,
    index: int = 0,
) -> dict[str, object]:
    captured: dict[str, object] = {}

    def spy(**kwargs: object) -> CalibrationHistorySelection:
        captured.update(kwargs)
        replay_call = cast(
            Callable[..., CalibrationHistorySelection],
            replay_calibration_history_selection,
        )
        return replay_call(**kwargs)

    monkeypatch.setattr(selector_replay, "replay_calibration_history_selection", spy)
    assert _predicate(bundle, index=index) is None
    return captured


def _call_replay(arguments: dict[str, object]) -> CalibrationHistorySelection:
    replay_call = cast(
        Callable[..., CalibrationHistorySelection],
        replay_calibration_history_selection,
    )
    return replay_call(**arguments)


def test_minimal_direct_predicate_executes_exactly_one_pure_replay(
    p3_bundle: Bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def spy(**kwargs: object) -> CalibrationHistorySelection:
        calls.append(dict(kwargs))
        replay_call = cast(
            Callable[..., CalibrationHistorySelection],
            replay_calibration_history_selection,
        )
        return replay_call(**kwargs)

    monkeypatch.setattr(selector_replay, "replay_calibration_history_selection", spy)
    assert _predicate(p3_bundle) is None
    assert len(calls) == 1
    assert tuple(calls[0]) == _REPLAY_KEYWORDS


def test_full_validator_executes_exactly_318_replays(
    p3_bundle: Bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def spy(**kwargs: object) -> CalibrationHistorySelection:
        nonlocal calls
        calls += 1
        replay_call = cast(
            Callable[..., CalibrationHistorySelection],
            replay_calibration_history_selection,
        )
        return replay_call(**kwargs)

    monkeypatch.setattr(selector_replay, "replay_calibration_history_selection", spy)
    assert _validate(p3_bundle) == (None, (318,) * 12)
    assert calls == 318


@pytest.mark.parametrize(
    "case",
    ("fixed-arm-boundary", "p1-failure", "p2-failure"),
    ids=("fixed-arm-zero-replay", "p1-failure-zero-replay", "p2-failure-zero-replay"),
)
def test_non_p3_and_earlier_failure_boundaries_execute_zero_replays(
    case: str,
    p3_bundle: Bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def forbidden(**kwargs: object) -> CalibrationHistorySelection:
        nonlocal calls
        calls += 1
        raise AssertionError("replay entered before the P3 calibrated-selection boundary")

    monkeypatch.setattr(selector_replay, "replay_calibration_history_selection", forbidden)
    if case == "fixed-arm-boundary":
        # Fixed-arm selections have no P3 input; their exact terminal control is
        # the predecessor validator, which must never enter calibrated replay.
        outcome = evidence._validate_stage2f_p2(
            selections=p3_bundle[0],
            expected_execution_attestation_pairs=p3_bundle[1],
            attested_execution_specification_ids=p3_bundle[2],
            p2_selections=p3_bundle[3],
            expected_predecessors=p3_bundle[4],
        )
        assert outcome == (None, (318,) * 11)
    elif case == "p1-failure":
        selections = harness.mutate_selection(
            p3_bundle[0],
            0,
            harness.POSITION_INDEX,
            1,
        )
        failure, counts = _validate(p3_bundle, selections=selections)
        assert failure is not None
        assert failure[1].startswith("calibration/3o.1.")
        assert counts[-1] == 0
    else:
        p2 = p3_bundle[3][-1]
        source_evidence = p2[harness.P2_ORDERED_SOURCE_OBSERVATIONS_INDEX]
        first_projection, first_identity = source_evidence[0]
        changed_sources = harness.replace_source_evidence_at(
            source_evidence,
            0,
            (first_projection, _alternate_h64(first_identity)),
        )
        changed_p2 = harness.replace_p2_selection_field(
            p2,
            harness.P2_ORDERED_SOURCE_OBSERVATIONS_INDEX,
            changed_sources,
        )
        p2_selections = harness.replace_p2_selection(
            p3_bundle[3],
            len(p3_bundle[3]) - 1,
            changed_p2,
        )
        first_p3_input = p3_bundle[6][0]
        early_projection = first_p3_input.selector_result_projection
        p3_inputs = harness.replace_p3_input_at(
            p3_bundle[6],
            0,
            _replace_p3_input(
                first_p3_input,
                selector_result_projection=_unsafe_projection(
                    early_projection,
                    sample_count=early_projection.sample_count - 1,
                ),
            ),
        )
        failure, counts = _validate(
            p3_bundle,
            p2_selections=p2_selections,
            p3_inputs=p3_inputs,
        )
        assert failure is not None
        assert failure[1] == "calibration/3o.4.1/source_observation"
        assert failure[2] == len(p3_bundle[3]) - 1
        assert counts[-1] == 0
    assert calls == 0


def _replace_role(
    returned_results: ReturnedResultsByRole,
    role_index: int,
    replacement: object,
) -> ReturnedResultsByRole:
    return harness.replace_returned_results_role(
        returned_results,
        role_index,
        cast(Any, replacement),
    )


def _replace_witness_run(
    bundle: Bundle,
    run: ReturnedRunProjection,
) -> tuple[ReturnedResultsByRole, P3Input]:
    p3_input = bundle[6][0]
    aggregate = bundle[5][0]
    replacement_row = (
        p3_input.returned_result_id,
        run,
        p3_input.submitted_job_id,
    )
    replacement_aggregate = harness.replace_returned_result_row(
        aggregate,
        0,
        replacement_row,
    )
    return (
        _replace_role(bundle[5], 0, replacement_aggregate),
        _replace_p3_input(p3_input, returned_run_projection=run),
    )


@pytest.mark.parametrize(
    "case",
    ("duplicate", "cross-role", "run-id-authority", "exact-row-binding"),
    ids=(
        "witness-must-be-unique",
        "cross-role-substitution",
        "run-id-comes-from-row",
        "row-must-be-exact-object",
    ),
)
def test_role_owned_witness_authority_fails_before_replay(
    case: str,
    p3_bundle: Bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def forbidden(**kwargs: object) -> CalibrationHistorySelection:
        nonlocal calls
        calls += 1
        raise AssertionError("invalid witness reached replay")

    monkeypatch.setattr(selector_replay, "replay_calibration_history_selection", forbidden)
    returned_results = p3_bundle[5]
    p3_input = p3_bundle[6][0]
    if case == "duplicate":
        aggregate = returned_results[0]
        row = aggregate.results_in_submission_order[0]
        replace_call = cast(Callable[..., object], dataclass_replace)
        duplicate = replace_call(
            aggregate,
            results_in_submission_order=(*aggregate.results_in_submission_order, row),
            job_result_mapping=(
                *aggregate.job_result_mapping,
                (row[2], row[0]),
            ),
        )
        returned_results = _replace_role(returned_results, 0, duplicate)
        expected_detail = "role-owned replay witness is missing or not unique"
    elif case == "cross-role":
        p3_input = p3_bundle[6][96]
        expected_detail = "carried replay witness is not the exact role-owned row"
    elif case == "run-id-authority":
        run = dataclass_replace(
            p3_input.returned_run_projection,
            run_id="p3-witness/forged-run-id",
        )
        returned_results, p3_input = _replace_witness_run(p3_bundle, run)
        expected_detail = "observation[0].authorization.run_id differs"
    else:
        copied_run = dataclass_replace(p3_input.returned_run_projection)
        p3_input = _replace_p3_input(
            p3_input,
            returned_run_projection=copied_run,
        )
        expected_detail = "carried replay witness is not the exact role-owned row"
    assert _predicate(
        p3_bundle,
        returned_results=returned_results,
        p3_input=p3_input,
    ) == (_P3_CODE, expected_detail)
    assert calls == 0


def _corrupt_witness_occurrences(
    bundle: Bundle,
    case: str,
) -> tuple[tuple[str, ReturnedResultsByRole, P3Input, str], ...]:
    run = bundle[6][0].returned_run_projection
    calibration = run.calibration
    assert calibration is not None
    estimate = calibration.estimates[0]
    replace_call = cast(Callable[..., Any], dataclass_replace)

    def bind_estimate(
        *,
        observations: object = estimate.observations,
        effects: object = estimate.effects,
    ) -> tuple[ReturnedResultsByRole, P3Input]:
        replacement_estimate = replace_call(
            estimate,
            observations=observations,
            effects=effects,
        )
        replacement_calibration = replace_call(
            calibration,
            estimates=_at(calibration.estimates, 0, replacement_estimate),
        )
        return _replace_witness_run(
            bundle,
            replace_call(run, calibration=replacement_calibration),
        )

    observations = estimate.observations
    if case == "authorization-id":
        returned_results, p3_input = bind_estimate(
            observations=_at(
                observations,
                0,
                dataclass_replace(
                    observations[0],
                    authorization_id=f"authorization:{'0' * 64}",
                ),
            )
        )
        return (
            (
                case,
                returned_results,
                p3_input,
                "observation[0].authorization_id",
            ),
        )
    if case == "oracle-use-id":
        returned_results, p3_input = bind_estimate(
            observations=_at(
                observations,
                0,
                dataclass_replace(
                    observations[0],
                    oracle_use_id=(
                        f"oracle-use/authorization:{'0' * 64}/{observations[0].oracle_key_id}"
                    ),
                ),
            )
        )
        return (
            (
                case,
                returned_results,
                p3_input,
                "observation[0].oracle_use_id",
            ),
        )
    occurrences: list[tuple[str, ReturnedResultsByRole, P3Input, str]] = []
    if case == "observation-order":
        first_observation = observations[0]
        for field in fields(first_observation):
            returned_results, p3_input = bind_estimate(
                observations=_at(
                    observations,
                    0,
                    replace_call(
                        first_observation,
                        **{field.name: cast(Any, _Trap())},
                    ),
                )
            )
            detail = (
                "observation[0].authorization.type"
                if field.name == "authorization"
                else f"observation[0].{field.name}"
            )
            occurrences.append(
                (
                    f"observation-field-{field.name}",
                    returned_results,
                    p3_input,
                    detail,
                )
            )
        authorization = first_observation.authorization
        for field in fields(authorization):
            changed_authorization = replace_call(
                authorization,
                **{field.name: cast(Any, _Trap())},
            )
            returned_results, p3_input = bind_estimate(
                observations=_at(
                    observations,
                    0,
                    replace_call(
                        first_observation,
                        authorization=changed_authorization,
                    ),
                )
            )
            occurrences.append(
                (
                    f"authorization-field-{field.name}",
                    returned_results,
                    p3_input,
                    f"observation[0].authorization.{field.name}",
                )
            )
        returned_results, p3_input = bind_estimate(observations=tuple(reversed(observations)))
        occurrences.append(
            (
                "observation-order",
                returned_results,
                p3_input,
                "observation[0].authorization.candidate_id",
            )
        )
        return tuple(occurrences)

    effects = estimate.effects
    first_effect = effects[0]

    def add_effect(
        label: str,
        changed_effect: object,
    ) -> None:
        returned_results, p3_input = bind_estimate(effects=_at(effects, 0, changed_effect))
        occurrences.append(
            (
                label,
                returned_results,
                p3_input,
                "effect[0] witness estimate occurrence",
            )
        )

    for field in fields(first_effect):
        add_effect(
            f"effect-field-{field.name}",
            replace_call(first_effect, **{field.name: cast(Any, _Trap())}),
        )
    add_effect(
        "effect-available-sequence-bool",
        replace_call(first_effect, available_sequence=cast(Any, False)),
    )
    add_effect(
        "effect-source-ids-list",
        replace_call(first_effect, source_ids=list(first_effect.source_ids)),
    )
    add_effect(
        "effect-source-ids-hostile-element",
        replace_call(
            first_effect,
            source_ids=(_Trap(), *first_effect.source_ids[1:]),
        ),
    )
    provenance = first_effect.provenance
    for field in fields(provenance):
        add_effect(
            f"effect-provenance-field-{field.name}",
            replace_call(
                first_effect,
                provenance=replace_call(
                    provenance,
                    **{field.name: cast(Any, _Trap())},
                ),
            ),
        )
    first_pair = provenance.details[0]
    first_value = first_pair[1]
    add_effect(
        "effect-provenance-details-list",
        replace_call(
            first_effect,
            provenance=replace_call(provenance, details=list(provenance.details)),
        ),
    )
    add_effect(
        "effect-provenance-detail-pair-list",
        replace_call(
            first_effect,
            provenance=replace_call(
                provenance,
                details=([first_pair[0], first_pair[1]], *provenance.details[1:]),
            ),
        ),
    )
    add_effect(
        "effect-provenance-detail-key-hostile",
        replace_call(
            first_effect,
            provenance=replace_call(
                provenance,
                details=((_Trap(), first_value), *provenance.details[1:]),
            ),
        ),
    )
    add_effect(
        "effect-provenance-detail-value-hostile",
        replace_call(
            first_effect,
            provenance=replace_call(
                provenance,
                details=((first_pair[0], _Trap()), *provenance.details[1:]),
            ),
        ),
    )
    for field_name in ("kind", "value"):
        add_effect(
            f"effect-provenance-value-{field_name}-hostile",
            replace_call(
                first_effect,
                provenance=replace_call(
                    provenance,
                    details=(
                        (
                            first_pair[0],
                            replace_call(
                                first_value,
                                **{field_name: cast(Any, _Trap())},
                            ),
                        ),
                        *provenance.details[1:],
                    ),
                ),
            ),
        )
    returned_results, p3_input = bind_estimate(effects=tuple(reversed(effects)))
    occurrences.append(
        (
            "effect-order",
            returned_results,
            p3_input,
            "effect[0] witness estimate occurrence",
        )
    )
    return tuple(occurrences)


@pytest.mark.parametrize(
    "case",
    ("authorization-id", "oracle-use-id", "observation-order", "effect-order"),
    ids=(
        "authorization-id-reconstruction",
        "oracle-use-id-reconstruction",
        "pair-major-observation-order",
        "replication-major-effect-order",
    ),
)
def test_complete_run_local_observation_and_effect_occurrences_are_checked(
    case: str,
    p3_bundle: Bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def forbidden(**kwargs: object) -> CalibrationHistorySelection:
        nonlocal calls
        calls += 1
        raise AssertionError("corrupt run-local occurrence reached replay")

    monkeypatch.setattr(selector_replay, "replay_calibration_history_selection", forbidden)
    failures: list[str] = []
    _Trap.calls = 0
    for label, returned_results, p3_input, expected_fragment in _corrupt_witness_occurrences(
        p3_bundle, case
    ):
        trap_calls_before = _Trap.calls
        try:
            failure = _predicate(
                p3_bundle,
                returned_results=returned_results,
                p3_input=p3_input,
            )
        except Exception as exc:
            failures.append(f"{label}: raised {exc!r}")
            continue
        if _Trap.calls != trap_calls_before:
            failures.append(f"{label}: invoked {_Trap.calls - trap_calls_before} hostile hooks")
        if failure is None or failure[0] != _P3_CODE or expected_fragment not in failure[1]:
            failures.append(f"{label}: {failure!r}")
    assert failures == []
    assert calls == 0
    assert _Trap.calls == 0


@pytest.mark.parametrize(
    "group_index",
    (0, 1, 2),
    ids=("group-00", "group-01", "group-02"),
)
def test_replay_receives_exact_eleven_keywords_group_index_and_physical_cost(
    group_index: int,
    p3_bundle: Bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = _capture_once(p3_bundle, monkeypatch, index=group_index)
    p3_input = p3_bundle[6][group_index]
    run = p3_input.returned_run_projection
    assert run.calibration is not None
    estimate = run.calibration.estimates[group_index]
    costs = candidate_costs(WORLDS_BY_ID[run.world_id].public)
    physical_cost = 5.0 * (
        costs[f"g{group_index:02d}-adam-r1"] + costs[f"g{group_index:02d}-sgd-r1"]
    )
    assert tuple(arguments) == _REPLAY_KEYWORDS
    assert arguments["run_id"] == run.run_id
    assert arguments["world_id"] == run.world_id
    assert arguments["seed"] == run.seed
    assert arguments["comparison_group_id"] == GROUP_IDS[group_index]
    assert arguments["group_index"] == group_index
    assert arguments["physical_cost"] == physical_cost
    replay_physical_cost = arguments["physical_cost"]
    assert type(replay_physical_cost) is float
    assert f64(replay_physical_cost) == estimate.physical_cost
    assert arguments["source_sequence_cutoff"] == 1
    recorded_observations = cast(
        tuple[RevealedObservation, ...],
        arguments["recorded_observations"],
    )
    recorded_effects = cast(
        tuple[MatchedEffectObservation, ...],
        arguments["recorded_effects"],
    )
    assert len(recorded_observations) == 10
    assert tuple(item.candidate_id for item in recorded_observations) == tuple(
        item.candidate_id for item in estimate.observations
    )
    assert len(recorded_effects) == 15 + len(run.updates)
    assert tuple(item.effect_id for item in recorded_effects) == tuple(
        item.effect_id for item in run.effect_history
    )


def test_recorded_history_benign_filtering_controls_are_accepted(
    p3_bundle: Bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = _capture_once(p3_bundle, monkeypatch)
    expected = p3_bundle[0][0][harness.SELECTOR_RESULT_INDEX]
    observations = cast(
        tuple[RevealedObservation, ...],
        arguments["recorded_observations"],
    )
    effects = cast(
        tuple[MatchedEffectObservation, ...],
        arguments["recorded_effects"],
    )
    expected_effects = cast(
        tuple[MatchedEffectObservation, ...],
        arguments["expected_effects"],
    )
    extra_unrelated = dataclass_replace(
        expected_effects[0],
        effect_id="calibration-effect/unrelated-group-control",
        comparison_group_id="group-01",
    )
    extra_post_cutoff = dataclass_replace(
        expected_effects[0],
        effect_id="calibration-effect/post-cutoff-control",
        available_sequence=1,
    )
    cases = {
        "reordered-observations": {
            **arguments,
            "recorded_observations": tuple(reversed(observations)),
        },
        "reordered-effects": {
            **arguments,
            "recorded_effects": tuple(reversed(effects)),
        },
        "unrelated-group-extra": {
            **arguments,
            "recorded_effects": (*effects, extra_unrelated),
        },
        "post-cutoff-target-extra": {
            **arguments,
            "recorded_effects": (*effects, extra_post_cutoff),
        },
    }
    failures: list[str] = []
    for name, case_arguments in cases.items():
        try:
            if _call_replay(case_arguments) != expected:
                failures.append(f"{name}: result differs")
        except Exception as error:  # deliberate all-case batch evaluation
            failures.append(f"{name}: {type(error).__name__}: {error}")
    assert failures == []


def test_recorded_history_missing_duplicate_mutated_and_cross_run_controls_reject(
    p3_bundle: Bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = _capture_once(p3_bundle, monkeypatch)
    observations = cast(
        tuple[RevealedObservation, ...],
        arguments["recorded_observations"],
    )
    effects = cast(
        tuple[MatchedEffectObservation, ...],
        arguments["recorded_effects"],
    )
    expected_effects = cast(
        tuple[MatchedEffectObservation, ...],
        arguments["expected_effects"],
    )
    cases = {
        "missing-observation": {
            **arguments,
            "recorded_observations": observations[:-1],
        },
        "duplicate-observation": {
            **arguments,
            "recorded_observations": (*observations[:-1], observations[0]),
        },
        "mutated-observation": {
            **arguments,
            "recorded_observations": _at(
                observations,
                0,
                dataclass_replace(
                    observations[0],
                    revealed_observation=observations[0].revealed_observation + 1.0,
                ),
            ),
        },
        "cross-run-observation": {
            **arguments,
            "recorded_observations": _at(
                observations,
                0,
                dataclass_replace(
                    observations[0],
                    authorization_id=f"authorization:{'0' * 64}",
                ),
            ),
        },
        "missing-effect": {
            **arguments,
            "recorded_effects": tuple(
                item for item in effects if item.effect_id != expected_effects[0].effect_id
            ),
        },
        "duplicate-effect": {
            **arguments,
            "recorded_effects": (*effects, effects[0]),
        },
        "mutated-effect": {
            **arguments,
            "recorded_effects": tuple(
                dataclass_replace(
                    item,
                    observed_effect=item.observed_effect + 1.0,
                )
                if item.effect_id == expected_effects[0].effect_id
                else item
                for item in effects
            ),
        },
        "extra-pre-cutoff-target-effect": {
            **arguments,
            "recorded_effects": (
                *effects,
                dataclass_replace(
                    expected_effects[0],
                    effect_id="calibration-effect/extra-pre-cutoff-control",
                ),
            ),
        },
    }
    failures: list[str] = []
    for name, case_arguments in cases.items():
        try:
            _call_replay(case_arguments)
        except RunProvenanceError:
            continue
        except Exception as error:  # deliberate all-case batch evaluation
            failures.append(f"{name}: wrong exception {type(error).__name__}: {error}")
        else:
            failures.append(f"{name}: accepted")
    assert failures == []


@pytest.mark.parametrize(
    "case",
    ("run-provenance", "unrelated-exception"),
    ids=("RunProvenanceError-normalized", "no-broad-exception-catch"),
)
def test_replay_exception_boundary_is_exact(
    case: str,
    p3_bundle: Bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(**kwargs: object) -> CalibrationHistorySelection:
        del kwargs
        if case == "run-provenance":
            raise RunProvenanceError("rejected")
        raise TypeError("implementation defect")

    monkeypatch.setattr(selector_replay, "replay_calibration_history_selection", fail)
    if case == "run-provenance":
        assert _predicate(p3_bundle) == (
            _P3_CODE,
            "replay helper rejected run-local provenance",
        )
    else:
        with pytest.raises(TypeError, match="implementation defect"):
            _predicate(p3_bundle)


def _history_mutations(
    history: CalibrationHistorySelection,
) -> tuple[tuple[str, object], ...]:
    return (
        (
            "effect_values",
            (float("nan"), *history.effect_values[1:]),
        ),
        ("estimated_sigma", float("nan")),
        ("sample_mean", float("nan")),
        ("sample_mean", float("inf")),
        ("sample_mean", float("-inf")),
        ("sample_standard_deviation", float("inf")),
        ("sigma_floor", float("-inf")),
        ("ddof", True),
        ("source_sequence_cutoff", True),
        ("sample_count", float(history.sample_count)),
        ("current_observation_excluded", 1),
        ("current_effect_excluded", 1),
        ("future_history_excluded", 1),
        ("effect_values", list(history.effect_values)),
        ("source_effect_ids", list(history.source_effect_ids)),
        (
            "source_effect_payload_sha256",
            list(history.source_effect_payload_sha256),
        ),
        (
            "source_observation_identities",
            list(history.source_observation_identities),
        ),
        ("source_oracle_key_ids", list(history.source_oracle_key_ids)),
        ("source_candidate_pairs", list(history.source_candidate_pairs)),
        ("source_replication_ids", list(history.source_replication_ids)),
        ("effects", list(history.effects)),
        ("observations", list(history.observations)),
        ("study_id", "different-study/v1"),
        ("world_id", "d2_null"),
        ("seed", 9001),
        ("namespace", "rde.broader.calibration-outcome/v2"),
        ("comparison_group_id", "group-01"),
        ("target_comparison_group_id", "group-01"),
        ("source_sequence_cutoff", 0),
        (
            "source_effect_ids",
            ("calibration-effect/different", *history.source_effect_ids[1:]),
        ),
        (
            "source_effect_payload_sha256",
            (
                _alternate_h64(history.source_effect_payload_sha256[0]),
                *history.source_effect_payload_sha256[1:],
            ),
        ),
        (
            "source_observation_identities",
            (
                (
                    history.source_observation_identities[0][0],
                    _alternate_h64(history.source_observation_identities[0][1]),
                ),
                *history.source_observation_identities[1:],
            ),
        ),
        (
            "source_oracle_key_ids",
            (f"oracle-key:{'0' * 64}", *history.source_oracle_key_ids[1:]),
        ),
        (
            "source_candidate_pairs",
            (
                ("cal-00-adam-r9999", history.source_candidate_pairs[0][1]),
                *history.source_candidate_pairs[1:],
            ),
        ),
        (
            "source_replication_ids",
            ("calibration-00-r9999", *history.source_replication_ids[1:]),
        ),
        ("effect_values", (0.0, *history.effect_values[1:])),
        ("sample_count", 4),
        ("sample_mean", history.sample_mean + 1.0),
        (
            "sample_standard_deviation",
            history.sample_standard_deviation + 1.0,
        ),
        ("ddof", 2),
        ("sigma_floor", history.sigma_floor + 1.0),
        ("estimated_sigma", history.estimated_sigma + 1.0),
        ("physical_cost", history.physical_cost + 1.0),
        ("eligibility_basis", "different eligibility"),
        ("current_observation_excluded", False),
        ("current_effect_excluded", False),
        ("future_history_excluded", False),
        ("effects", tuple(reversed(history.effects))),
        ("observations", tuple(reversed(history.observations))),
    )


def _projection_mutations(
    projection: ScientificCalibrationSelectionProjection,
) -> tuple[tuple[str, object], ...]:
    return (
        ("comparison_group_id", "group-01"),
        ("ddof", 2),
        ("effect_values", ("f64:0000000000000000", *projection.effect_values[1:])),
        ("eligibility_basis", "different eligibility"),
        ("estimated_sigma", "f64:0000000000000000"),
        ("namespace", "rde.broader.calibration-outcome/v2"),
        ("sample_count", 4),
        ("sample_mean", "f64:0000000000000000"),
        ("sample_standard_deviation", "f64:0000000000000000"),
        ("seed", 9001),
        ("sigma_floor", "f64:3fb999999999999a"),
        (
            "source_candidate_pairs",
            (
                ("cal-00-adam-r9999", projection.source_candidate_pairs[0][1]),
                *projection.source_candidate_pairs[1:],
            ),
        ),
        (
            "source_effect_ids",
            ("calibration-effect/different", *projection.source_effect_ids[1:]),
        ),
        (
            "source_effect_payload_sha256",
            (
                _alternate_h64(projection.source_effect_payload_sha256[0]),
                *projection.source_effect_payload_sha256[1:],
            ),
        ),
        (
            "source_observation_identities",
            (
                (
                    projection.source_observation_identities[0][0],
                    _alternate_h64(projection.source_observation_identities[0][1]),
                ),
                *projection.source_observation_identities[1:],
            ),
        ),
        (
            "source_oracle_key_ids",
            (f"oracle-key:{'0' * 64}", *projection.source_oracle_key_ids[1:]),
        ),
        (
            "source_replication_ids",
            ("calibration-00-r9999", *projection.source_replication_ids[1:]),
        ),
        ("source_sequence_cutoff", 0),
        ("study_id", "different-study/v1"),
        ("target_comparison_group_id", "group-01"),
        ("world_id", "d2_null"),
    )


@pytest.mark.parametrize(
    "authority",
    ("helper", "historical", "projection"),
    ids=("B-fields-1-through-27", "H-fields-1-through-27", "C-fields-1-through-21"),
)
def test_complete_helper_historical_and_projection_field_matrices(
    authority: str,
    p3_bundle: Bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection, _p2, _predecessor, p3_input = _scope(p3_bundle)
    history = selection[harness.SELECTOR_RESULT_INDEX]
    projection = p3_input.selector_result_projection
    mutations = (
        _projection_mutations(projection)
        if authority == "projection"
        else _history_mutations(history)
    )
    failures: list[str] = []
    for field_name, value in mutations:
        calls = 0
        helper_result = (
            _replace_history(history, **{field_name: value}) if authority == "helper" else history
        )

        def replay(
            _helper_result: CalibrationHistorySelection = helper_result,
            **kwargs: object,
        ) -> CalibrationHistorySelection:
            nonlocal calls
            del kwargs
            calls += 1
            return _helper_result

        monkeypatch.setattr(
            selector_replay,
            "replay_calibration_history_selection",
            replay,
        )
        changed_selection = selection
        changed_input = p3_input
        if authority == "historical":
            changed_selection = harness.with_selector_result(
                selection,
                _replace_history(history, **{field_name: value}),
            )
        elif authority == "projection":
            changed_input = _replace_p3_input(
                p3_input,
                selector_result_projection=_unsafe_projection(
                    projection,
                    **{field_name: value},
                ),
            )
        try:
            outcome = _predicate(
                p3_bundle,
                selection=changed_selection,
                p3_input=changed_input,
            )
            expected_prefix = f"{authority}.{field_name}"
            if (
                outcome is None
                or outcome[0] != _P3_CODE
                or not outcome[1].startswith(expected_prefix)
                or calls != 1
            ):
                failures.append(
                    f"{field_name}: outcome={outcome!r}, calls={calls}, "
                    f"expected-prefix={expected_prefix!r}"
                )
        except Exception as error:  # deliberate all-case batch evaluation
            failures.append(f"{field_name}: {type(error).__name__}: {error}")
    assert failures == []


def test_identity_last_compound_precedence_is_B_then_H_then_C_then_B_H_D(
    p3_bundle: Bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection, _p2, _predecessor, p3_input = _scope(p3_bundle)
    history = selection[harness.SELECTOR_RESULT_INDEX]
    projection = p3_input.selector_result_projection
    wrong_identity = _alternate_h64(_FIXED_IDENTITY)
    cases = (
        (
            "B-nonidentity",
            _replace_history(
                history,
                sample_mean=history.sample_mean + 1.0,
                selection_identity=wrong_identity,
            ),
            harness.with_selector_result(
                selection,
                _replace_history(history, selection_identity=wrong_identity),
            ),
            _replace_p3_input(
                p3_input,
                selector_result_identity=wrong_identity,
            ),
            "helper.sample_mean",
        ),
        (
            "H-nonidentity",
            _replace_history(history, selection_identity=wrong_identity),
            harness.with_selector_result(
                selection,
                _replace_history(
                    history,
                    sample_mean=history.sample_mean + 1.0,
                    selection_identity=wrong_identity,
                ),
            ),
            _replace_p3_input(
                p3_input,
                selector_result_identity=wrong_identity,
            ),
            "historical.sample_mean",
        ),
        (
            "C-nonidentity",
            _replace_history(history, selection_identity=wrong_identity),
            harness.with_selector_result(
                selection,
                _replace_history(history, selection_identity=wrong_identity),
            ),
            _replace_p3_input(
                p3_input,
                selector_result_projection=_unsafe_projection(
                    projection,
                    sample_mean="f64:0000000000000000",
                ),
                selector_result_identity=wrong_identity,
            ),
            "projection.sample_mean",
        ),
        (
            "B-identity",
            _replace_history(history, selection_identity=wrong_identity),
            harness.with_selector_result(
                selection,
                _replace_history(history, selection_identity=wrong_identity),
            ),
            _replace_p3_input(p3_input, selector_result_identity=wrong_identity),
            "helper.selection_identity",
        ),
        (
            "H-identity",
            history,
            harness.with_selector_result(
                selection,
                _replace_history(history, selection_identity=wrong_identity),
            ),
            _replace_p3_input(p3_input, selector_result_identity=wrong_identity),
            "historical.selection_identity",
        ),
        (
            "D-identity",
            history,
            selection,
            _replace_p3_input(p3_input, selector_result_identity=wrong_identity),
            "explicit selector_result_identity",
        ),
    )
    failures: list[str] = []
    for name, helper_result, changed_selection, changed_input, expected_detail in cases:
        calls = 0

        def replay(
            _helper_result: CalibrationHistorySelection = helper_result,
            **kwargs: object,
        ) -> CalibrationHistorySelection:
            nonlocal calls
            del kwargs
            calls += 1
            return _helper_result

        monkeypatch.setattr(
            selector_replay,
            "replay_calibration_history_selection",
            replay,
        )
        try:
            outcome = _predicate(
                p3_bundle,
                selection=changed_selection,
                p3_input=changed_input,
            )
            if (
                outcome is None
                or outcome[0] != _P3_CODE
                or not outcome[1].startswith(expected_detail)
                or calls != 1
            ):
                failures.append(f"{name}: outcome={outcome!r}, calls={calls}")
        except Exception as error:  # deliberate all-case batch evaluation
            failures.append(f"{name}: {type(error).__name__}: {error}")
    assert failures == []


def test_A_B_C_H_D_E_anti_circularity_matrix(
    p3_bundle: Bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection, _p2, _predecessor, p3_input = _scope(p3_bundle)
    history = selection[harness.SELECTOR_RESULT_INDEX]
    projection = p3_input.selector_result_projection
    alternate_projection = _unsafe_projection(
        projection,
        sample_mean="f64:0000000000000000",
    )
    alternate_mapping = harness.scientific_selection_mapping(alternate_projection)
    alternate_identity = protocol_hash(_SELECTION_DOMAIN, alternate_mapping)
    cases = (
        (
            "B-H-C-D-cannot-supply-A",
            _replace_history(
                history,
                sample_mean=0.0,
                selection_identity=alternate_identity,
            ),
            harness.with_selector_result(
                selection,
                _replace_history(
                    history,
                    sample_mean=0.0,
                    selection_identity=alternate_identity,
                ),
            ),
            _replace_p3_input(
                p3_input,
                selector_result_projection=alternate_projection,
                selector_result_identity=alternate_identity,
            ),
            "helper.sample_mean",
        ),
        (
            "carried-identities-cannot-supply-E",
            _replace_history(history, selection_identity=alternate_identity),
            harness.with_selector_result(
                selection,
                _replace_history(history, selection_identity=alternate_identity),
            ),
            _replace_p3_input(
                p3_input,
                selector_result_identity=alternate_identity,
            ),
            "helper.selection_identity",
        ),
        (
            "C-and-D-cannot-supply-A-or-E",
            history,
            selection,
            _replace_p3_input(
                p3_input,
                selector_result_projection=alternate_projection,
                selector_result_identity=alternate_identity,
            ),
            "projection.sample_mean",
        ),
        (
            "D-alone-cannot-supply-E",
            history,
            selection,
            _replace_p3_input(
                p3_input,
                selector_result_identity=alternate_identity,
            ),
            "explicit selector_result_identity",
        ),
    )
    failures: list[str] = []
    for name, helper_result, changed_selection, changed_input, expected_detail in cases:

        def replay(
            _helper_result: CalibrationHistorySelection = helper_result,
            **kwargs: object,
        ) -> CalibrationHistorySelection:
            del kwargs
            return _helper_result

        monkeypatch.setattr(
            selector_replay,
            "replay_calibration_history_selection",
            replay,
        )
        try:
            outcome = _predicate(
                p3_bundle,
                selection=changed_selection,
                p3_input=changed_input,
            )
            if (
                outcome is None
                or outcome[0] != _P3_CODE
                or not outcome[1].startswith(expected_detail)
            ):
                failures.append(f"{name}: outcome={outcome!r}")
        except Exception as error:  # deliberate all-case batch evaluation
            failures.append(f"{name}: {type(error).__name__}: {error}")
    assert failures == []


def test_full_validator_reports_earliest_canonical_p3_coordinate_and_stops(
    p3_bundle: Bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def spy(**kwargs: object) -> CalibrationHistorySelection:
        nonlocal calls
        calls += 1
        replay_call = cast(
            Callable[..., CalibrationHistorySelection],
            replay_calibration_history_selection,
        )
        return replay_call(**kwargs)

    monkeypatch.setattr(selector_replay, "replay_calibration_history_selection", spy)
    p3_inputs = p3_bundle[6]
    for index in (7, 8):
        projection = p3_inputs[index].selector_result_projection
        p3_inputs = harness.replace_p3_input_at(
            p3_inputs,
            index,
            _replace_p3_input(
                p3_inputs[index],
                selector_result_projection=_unsafe_projection(
                    projection,
                    sample_count=4,
                ),
            ),
        )
    failure, counts = _validate(p3_bundle, p3_inputs=p3_inputs)
    assert failure is not None
    assert failure[:3] == (_P3_CODE, _P3_PATH, 7)
    role, world_id, seed, group_id = harness.CANONICAL_COORDINATES[7]
    assert failure[3].startswith(f"selection[7] {role}/{world_id}/{seed}/{group_id}: ")
    assert "projection.sample_count" in failure[3]
    assert counts == (*(318 for _ in range(11)), 8)
    assert calls == 8


def test_p3_failure_never_enters_P4_reader_or_later_stage_sentinels(
    p3_bundle: Bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    later_calls: list[str] = []
    identity_hash_calls: list[str] = []
    protocol_hash_call = cast(Callable[..., str], protocol_hash)

    def later_stage(*args: object, **kwargs: object) -> None:
        del args, kwargs
        later_calls.append("entered")
        raise AssertionError("later stage entered")

    def forbidden_identity_hash(
        domain: object,
        *args: object,
        **kwargs: object,
    ) -> str:
        if domain == _SELECTION_DOMAIN:
            identity_hash_calls.append("entered")
            raise AssertionError("identity hashing entered after a projection mismatch")
        return protocol_hash_call(domain, *args, **kwargs)

    later_surface_names = (
        "_validate_stage2f_p4",
        "_predicate_3p",
        "Reader",
        "_persist_calibration_evidence",
        "_emit_calibration_evidence",
        "_run_workload",
        "_live_oracle",
    )
    unexpected_surfaces = tuple(name for name in later_surface_names if hasattr(evidence, name))
    assert unexpected_surfaces == ()
    for name in later_surface_names:
        monkeypatch.setattr(evidence, name, later_stage, raising=False)
    monkeypatch.setattr(evidence, "_protocol_hash", forbidden_identity_hash)
    projection = p3_bundle[6][0].selector_result_projection
    changed_input = _replace_p3_input(
        p3_bundle[6][0],
        selector_result_projection=_unsafe_projection(
            projection,
            sample_count=projection.sample_count - 1,
        ),
    )
    p3_inputs = harness.replace_p3_input_at(p3_bundle[6], 0, changed_input)
    failure, counts = _validate(p3_bundle, p3_inputs=p3_inputs)
    assert failure is not None
    assert failure[:3] == (_P3_CODE, _P3_PATH, 0)
    assert counts == (*(318 for _ in range(11)), 1)
    assert identity_hash_calls == []
    assert later_calls == []
