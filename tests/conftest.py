from __future__ import annotations

from collections.abc import Iterator
from typing import NoReturn

import pytest

from research_decision_engine.benchmarks.broader_conformance import (
    DiagnosticConformanceFixture,
)
from tests.test_broader_oracle_support import (
    FixtureConformanceOracleSupport,
)


@pytest.fixture(scope="session")
def conformance_oracle_support() -> NoReturn:
    """Production P2 authority is never minted by pytest fixtures."""

    pytest.skip("production Oracle authority is unavailable to test and fixture issuers")


@pytest.fixture(scope="session")
def fixture_conformance_oracle_support() -> Iterator[FixtureConformanceOracleSupport]:
    support = FixtureConformanceOracleSupport.issue()
    try:
        yield support
    finally:
        support.close()


@pytest.fixture(scope="session")
def diagnostic_conformance_fixture(
    fixture_conformance_oracle_support: FixtureConformanceOracleSupport,
) -> DiagnosticConformanceFixture:
    return fixture_conformance_oracle_support.diagnostic_fixture()
