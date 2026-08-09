from __future__ import annotations

import pytest

from research_decision_engine.benchmarks.broader_oracle import (
    ObservationAuthority,
    OracleError,
    authorize_observation,
    decision_key,
    reobserve_authorized_observation,
    transform_key,
)
from research_decision_engine.benchmarks.broader_protocol import (
    EXPECTED_ORACLE_DOMAIN_SHA256,
)
from research_decision_engine.benchmarks.broader_worlds import WORLDS_BY_ID

pytestmark = pytest.mark.oracle_reconstruction


def test_frozen_oracle_vector_and_declared_full_digest() -> None:
    key = decision_key(
        world_id="h_adam_low",
        seed=1000,
        candidate_id="g00-adam-r1",
        replication_id="decision-group-00-r0001",
    )
    transformed = transform_key(key)
    assert transformed.digest_hex == (
        "d96a43ec5c695e119e591ed29b6d700d2a05e8aeb7b3facc233839b9beaf01c4"
    )
    assert transformed.u_string == "0.84927773018390462222981796003296039998531341552734375"
    assert transformed.z_string == "1.033340588445414672561538110996"
    assert EXPECTED_ORACLE_DOMAIN_SHA256 == (
        "0452652278d2670ac11f923a6919cae923b2baf88d2ea9b0356a5d4923dc706c"
    )


def test_selected_only_common_randomness_across_arms() -> None:
    world = WORLDS_BY_ID["h_adam_low"]
    first = ObservationAuthority(world=world, seed=9000)
    second = ObservationAuthority(world=world, seed=9000)
    first_interface = first.selected_only_interface()
    second_interface = second.selected_only_interface()
    first_authorization = authorize_observation(
        run_id="run:first",
        source_id="decision/run:first/0001",
        candidate_id="g00-adam-r1",
        kind="decision",
    )
    second_authorization = authorize_observation(
        run_id="run:second",
        source_id="decision/run:second/0001",
        candidate_id="g00-adam-r1",
        kind="decision",
    )

    left = first_interface.observe_selected(first_authorization)
    right = second_interface.observe_selected(second_authorization)

    assert left.revealed_observation == right.revealed_observation
    assert left.oracle_key_id == right.oracle_key_id
    assert left.digest == right.digest
    assert not hasattr(first_interface, "peek")
    assert not hasattr(first_interface, "enumerate")
    assert not hasattr(first_interface, "potential_outcomes")


def test_authorized_observation_can_be_independently_reobserved() -> None:
    world = WORLDS_BY_ID["h_adam_low"]
    authorization = authorize_observation(
        run_id="run:reobserve",
        source_id="decision/run:reobserve/0001",
        candidate_id="g00-adam-r1",
        kind="decision",
    )
    recorded = (
        ObservationAuthority(world=world, seed=9000)
        .selected_only_interface()
        .observe_selected(authorization)
    )
    reconstructed = reobserve_authorized_observation(
        world_id=world.public.world_id,
        seed=9000,
        authorization=authorization,
    )
    assert reconstructed == recorded


def test_authorization_is_single_use_and_setup_has_no_outcome() -> None:
    world = WORLDS_BY_ID["d3_adam"]
    authority = ObservationAuthority(world=world, seed=9000)
    interface = authority.selected_only_interface()
    authorization = authorize_observation(
        run_id="run:single",
        source_id="decision/run:single/0001",
        candidate_id="g00-adam-r1",
        kind="decision",
    )
    interface.observe_selected(authorization)
    with pytest.raises(OracleError, match="only once"):
        interface.observe_selected(authorization)

    setup = authorize_observation(
        run_id="run:setup",
        source_id="decision/run:setup/0001",
        candidate_id="g00-setup-r1",
        kind="decision",
    )
    with pytest.raises(OracleError, match="never invoke"):
        ObservationAuthority(world=world, seed=9000).selected_only_interface().observe_selected(
            setup
        )
