from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

import research_decision_engine.benchmarks.broader_smoke as smoke_module
from research_decision_engine.benchmarks.broader_audits import SmokeAuditContext, evaluate_audit
from research_decision_engine.benchmarks.broader_conformance import ProductionConformanceFixture
from research_decision_engine.benchmarks.broader_oracle import (
    OracleConformanceResult,
    OracleEvidenceBinding,
)
from research_decision_engine.benchmarks.broader_protocol import ARMS, load_protocol_snapshot
from research_decision_engine.benchmarks.broader_smoke import execute_validation_pass


def test_independent_small_replay_is_byte_identical() -> None:
    first = execute_validation_pass(
        world_ids=("h_adam_low",),
        seeds=(9000,),
        budgets=(("budget-2.25", 2.25),),
        expected_count=4,
    )
    replay = execute_validation_pass(
        world_ids=("h_adam_low",),
        seeds=(9000,),
        budgets=(("budget-2.25", 2.25),),
        arm_order=tuple(reversed(ARMS)),
        worker_count=2,
        expected_count=4,
    )

    assert len(first.runs) == 4
    assert len(replay.runs) == 4
    assert all(left is not right for left, right in zip(first.runs, replay.runs, strict=True))
    assert first.deterministic_payload == replay.deterministic_payload


def test_missing_oracle_execution_fails_the_a04_smoke_audit() -> None:
    context = SmokeAuditContext(
        runs=(),
        replay_runs=(),
        first_payload=b"[]\n",
        replay_payload=b"[]\n",
        historical_before=(),
        historical_after=(),
    )

    assert context.oracle_conformance_result is None
    assert context.oracle_evidence_binding is None
    assert evaluate_audit("A04-ORACLE-ISOLATION", context).status == "FAIL"


def test_production_fixture_evidence_records_bounded_validation_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_ids = load_protocol_snapshot().registry("audit").ids("audit_id")
    fixture = cast(
        ProductionConformanceFixture,
        SimpleNamespace(
            runs=tuple(range(252)),
            replay_runs=tuple(range(252)),
            audits=tuple(
                SimpleNamespace(audit_id=audit_id, status="PASS") for audit_id in audit_ids
            ),
            early_optimizer_rejection_verified=True,
        ),
    )
    monkeypatch.setattr(smoke_module, "_truth_free_projection", lambda run: {"run": run})
    monkeypatch.setattr(
        smoke_module,
        "_validated_oracle_evidence",
        lambda result, binding: (117_952, "0" * 64),
    )

    evidence = smoke_module._production_fixture_evidence(
        fixture,
        canonical_artifact_count=13,
        expected_artifact_count=13,
        oracle_result=cast(OracleConformanceResult, object()),
        oracle_binding=cast(OracleEvidenceBinding, object()),
    )

    assert evidence.validation_only
    assert evidence.trajectory_count == evidence.replay_trajectory_count == 252
    assert evidence.deterministic_replay_equal
    assert evidence.audit_statuses == tuple((audit_id, "PASS") for audit_id in audit_ids)
    assert evidence.all_audits_passed
    assert evidence.canonical_artifact_count == 13
    assert evidence.finalization_succeeded
    assert evidence.early_optimizer_rejection_verified
    assert evidence.success


@pytest.mark.parametrize("attack", ("replay", "audit", "finalization"))
def test_production_fixture_evidence_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    audit_ids = load_protocol_snapshot().registry("audit").ids("audit_id")
    replay_runs = tuple(range(252))
    statuses = ["PASS"] * len(audit_ids)
    artifact_count = 13
    if attack == "replay":
        replay_runs = tuple(reversed(replay_runs))
    elif attack == "audit":
        statuses[-1] = "FAIL"
    else:
        artifact_count = 12
    fixture = cast(
        ProductionConformanceFixture,
        SimpleNamespace(
            runs=tuple(range(252)),
            replay_runs=replay_runs,
            audits=tuple(
                SimpleNamespace(audit_id=audit_id, status=status)
                for audit_id, status in zip(audit_ids, statuses, strict=True)
            ),
            early_optimizer_rejection_verified=True,
        ),
    )
    monkeypatch.setattr(smoke_module, "_truth_free_projection", lambda run: {"run": run})
    monkeypatch.setattr(
        smoke_module,
        "_validated_oracle_evidence",
        lambda result, binding: (117_952, "0" * 64),
    )

    evidence = smoke_module._production_fixture_evidence(
        fixture,
        canonical_artifact_count=artifact_count,
        expected_artifact_count=13,
        oracle_result=cast(OracleConformanceResult, object()),
        oracle_binding=cast(OracleEvidenceBinding, object()),
    )

    assert not evidence.success
