from __future__ import annotations

from research_decision_engine.benchmarks.broader_artifacts import (
    artifact_contracts,
    build_protocol_snapshot_payload,
    build_world_definitions_payload,
)
from research_decision_engine.benchmarks.broader_protocol import (
    FULL_SEEDS,
    SMOKE_SEEDS,
    load_protocol_snapshot,
)
from research_decision_engine.benchmarks.broader_worlds import (
    BUDGETS,
    WORLDS,
    WORLDS_BY_ID,
    PublicFeasibilityState,
    validate_worlds,
)


def test_complete_literal_protocol_snapshot() -> None:
    snapshot = load_protocol_snapshot()

    assert snapshot.source_design_sha256 == (
        "be51026bfb6de003110df5760ed4a60eb9d4cb8cec2001e097ebc4c3bd1acbaf"
    )
    expected_counts = {
        "confirmatory": 66,
        "decision": 20,
        "descriptive": 36,
        "veto": 20,
        "statistical_hypothesis": 64,
        "formula": 43,
        "gate_condition": 66,
        "gate": 44,
        "audit": 16,
        "artifact": 13,
        "enum": 33,
    }
    for registry_name, expected in expected_counts.items():
        assert len(snapshot.registry(registry_name).rows) == expected
    assert len(FULL_SEEDS) == 128
    assert tuple(range(1000, 1128)) == FULL_SEEDS
    assert tuple(range(9000, 9004)) == SMOKE_SEEDS


def test_every_formula_is_literal_ordered_and_complete() -> None:
    formulas = load_protocol_snapshot().registry("formula").records()

    assert tuple(int(row["formula_order"]) for row in formulas) == tuple(range(1, 44))
    assert len({row["formula_id"] for row in formulas}) == 43
    for row in formulas:
        assert all(value for value in row.values())
    assert next(row for row in formulas if row["formula_id"] == "F-B-AUTHORIZATION")[
        "exact_operator"
    ].startswith("Dedicated three-valued precedence")


def test_protocol_and_world_artifact_projections_are_complete() -> None:
    protocol = build_protocol_snapshot_payload()
    worlds = build_world_definitions_payload()

    for key, expected in (
        ("confirmatory_contrast_registry", 66),
        ("decision_contrast_registry", 20),
        ("descriptive_contrast_registry", 36),
        ("formula_registry", 43),
        ("gate_condition_registry", 66),
        ("enum_registry", 33),
        ("artifact_registry", 13),
    ):
        value = protocol[key]
        assert isinstance(value, list)
        assert len(value) == expected
    assert len(artifact_contracts()) == 13
    candidate_catalog = worlds["candidate_catalog"]
    world_registry = worlds["worlds"]
    assert isinstance(candidate_catalog, list)
    assert isinstance(world_registry, list)
    assert len(candidate_catalog) == 11
    assert len(world_registry) == 24


def test_frozen_worlds_and_depth_three_public_transition() -> None:
    validate_worlds()

    assert len(WORLDS) == 24
    assert len(BUDGETS) == 3
    world = WORLDS_BY_ID["d3_adam"].public
    state = PublicFeasibilityState(world)
    assert state.publicly_feasible_candidate_ids() == (
        "g00-setup-r1",
        "g01-setup-r1",
        "g02-setup-r1",
        "irrelevant-objective-r1",
        "redundant-objective-r1",
    )

    after_setup = state.complete("g01-setup-r1")
    assert after_setup.publicly_feasible_candidate_ids() == (
        "g00-setup-r1",
        "g02-setup-r1",
        "g01-adam-r1",
        "g01-sgd-r1",
        "irrelevant-objective-r1",
        "redundant-objective-r1",
    )
    assert state.publicly_feasible_candidate_ids() != after_setup.publicly_feasible_candidate_ids()
