"""Controlled fixture construction kept outside the production lifecycle API."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol
from unittest.mock import patch

import research_decision_engine.benchmarks.broader_lifecycle as lifecycle
from research_decision_engine.benchmarks.broader_lifecycle import (
    AttemptAuthority,
    ImplementationIdentity,
    LifecycleReader,
)


class GraphValidator(Protocol):
    def validate_11(self, artifacts: Mapping[str, bytes]) -> None: ...

    def validate_12(self, artifacts: Mapping[str, bytes]) -> None: ...

    def validate_13(self, artifacts: Mapping[str, bytes]) -> None: ...

    def validate_historical(self, artifacts: Mapping[str, bytes]) -> None: ...


def controlled_reader(
    primary_target: Path,
    graph_validator: GraphValidator,
    identity: ImplementationIdentity,
) -> LifecycleReader:
    """Construct an immutable production reader under scoped test-owned dependencies."""

    if primary_target.name != lifecycle.PRIMARY_TARGET_NAME:
        raise ValueError("The controlled reader must retain the frozen primary target name.")
    with (
        patch.object(lifecycle, "repository_root", return_value=primary_target.parent),
        patch.object(lifecycle, "FrozenGraphValidator", return_value=graph_validator),
        patch.object(
            lifecycle,
            "reconstruct_implementation_identity",
            return_value=identity,
        ),
    ):
        return LifecycleReader()


def controlled_authority(
    primary_target: Path,
    graph_validator: GraphValidator,
    identity: ImplementationIdentity,
) -> AttemptAuthority:
    """Construct an immutable production authority under scoped test dependencies."""

    if primary_target.name != lifecycle.PRIMARY_TARGET_NAME:
        raise ValueError("The controlled authority must retain the frozen primary target name.")
    with (
        patch.object(lifecycle, "repository_root", return_value=primary_target.parent),
        patch.object(lifecycle, "FrozenGraphValidator", return_value=graph_validator),
        patch.object(
            lifecycle,
            "reconstruct_implementation_identity",
            return_value=identity,
        ),
        patch.object(
            lifecycle,
            "_require_executor_bound_artifacts",
            side_effect=lambda artifacts: ("controlled-executor-binding", id(artifacts)),
        ),
        patch.object(lifecycle, "_revalidate_executor_binding", return_value=None),
        patch.object(lifecycle, "_validate_manifest_executor_binding", return_value=None),
    ):
        return AttemptAuthority()


__all__ = ["GraphValidator", "controlled_authority", "controlled_reader"]
