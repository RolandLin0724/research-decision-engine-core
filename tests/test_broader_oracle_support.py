"""Test-only small Oracle evidence for bounded diagnostic conformance builders."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from pathlib import Path

import research_decision_engine.benchmarks.broader_conformance as conformance_module
import research_decision_engine.benchmarks.broader_oracle as oracle_module
from research_decision_engine.benchmarks.broader_assembly import (
    AssemblyOperationalProvenance,
    CanonicalFinalizationPlan,
)
from research_decision_engine.benchmarks.broader_audits import (
    FinalizationAuditCertificate,
    FinalizationAuthorization,
)
from research_decision_engine.benchmarks.broader_conformance import (
    DiagnosticConformanceFixture,
    ProductionConformanceFixture,
)
from research_decision_engine.benchmarks.broader_oracle import (
    OracleConformanceResult,
    OracleEvidenceBinding,
    OracleFixtureBinding,
    OracleFixtureEvidence,
    OracleFixtureResult,
    close_oracle_evidence_binding,
    decision_key,
    transform_key,
)
from research_decision_engine.benchmarks.broader_protocol import (
    canonical_json_bytes,
    protocol_hash,
)

_FIXTURE_PARTITION_COUNTS = (("tiny", 1),)


@dataclass(frozen=True, slots=True)
class FixtureConformanceOracleSupport:
    """Diagnostic-only fixture evidence that cannot issue finalization capability."""

    result: OracleFixtureResult
    binding: OracleFixtureBinding
    fixture_evidence: OracleFixtureEvidence
    expected_sha256: str

    @classmethod
    def issue(cls) -> FixtureConformanceOracleSupport:
        nonce = secrets.token_hex(32)
        validation_run_identity = protocol_hash(
            "test_conformance_validation_run/v1",
            {"nonce": nonce},
        )
        binding = oracle_module._begin_oracle_fixture_binding(
            validation_run_identity=validation_run_identity,
            evidence_bundle_identity=protocol_hash(
                "test_conformance_evidence_bundle/v1",
                {"nonce": nonce, "validation_run_identity": validation_run_identity},
            ),
        )
        try:
            partitions = _fixture_partitions()
            expected_sha256 = _fixture_digest(partitions)
            fixture_evidence = oracle_module._issue_oracle_conformance_fixture(
                binding=binding,
                partitions=partitions,
                expected_key_count=1,
                expected_unique_key_count=1,
                expected_partition_counts=_FIXTURE_PARTITION_COUNTS,
                expected_sha256=expected_sha256,
            )
            result = fixture_evidence.result
        except Exception:
            oracle_module._close_oracle_fixture_binding(binding)
            raise
        return cls(
            result=result,
            binding=binding,
            fixture_evidence=fixture_evidence,
            expected_sha256=expected_sha256,
        )

    def diagnostic_fixture(self) -> DiagnosticConformanceFixture:
        """Return bounded diagnostic data for this exact fixture evidence."""

        return conformance_module._build_diagnostic_conformance_fixture(
            oracle_fixture_evidence=self.fixture_evidence,
        )

    def close(self) -> None:
        oracle_module._close_oracle_fixture_binding(self.binding)


@dataclass(frozen=True, slots=True)
class ConformanceOracleSupport:
    """Real production Oracle evidence for tests that exercise finalization authority."""

    result: OracleConformanceResult
    binding: OracleEvidenceBinding

    @classmethod
    def from_executed(
        cls,
        *,
        result: OracleConformanceResult,
        binding: OracleEvidenceBinding,
    ) -> ConformanceOracleSupport:
        """Wrap explicit caller-executed production evidence without running an audit."""

        oracle_module.validate_oracle_conformance_result(result, binding=binding)
        return cls(result=result, binding=binding)

    def production_fixture(self) -> ProductionConformanceFixture:
        return conformance_module.build_production_fixture(
            oracle_conformance_result=self.result,
            oracle_evidence_binding=self.binding,
        )

    def payloads(
        self,
        target: Path,
    ) -> tuple[
        CanonicalFinalizationPlan,
        AssemblyOperationalProvenance,
        FinalizationAuthorization,
    ]:
        return conformance_module.build_conformance_payloads(
            target,
            oracle_conformance_result=self.result,
            oracle_evidence_binding=self.binding,
            fixture=self.production_fixture(),
        )

    def audited_plan(
        self,
    ) -> tuple[
        CanonicalFinalizationPlan,
        AssemblyOperationalProvenance,
        FinalizationAuditCertificate,
    ]:
        return conformance_module._build_audited_conformance_plan(
            oracle_conformance_result=self.result,
            oracle_evidence_binding=self.binding,
            fixture=self.production_fixture(),
        )

    def close(self) -> None:
        close_oracle_evidence_binding(self.binding)


def _fixture_partitions() -> tuple[tuple[str, tuple[tuple[str, ...], ...]], ...]:
    return (
        (
            "tiny",
            (
                decision_key(
                    world_id="h_adam_low",
                    seed=9000,
                    candidate_id="g00-adam-r1",
                    replication_id="decision-group-00-r0001",
                ),
            ),
        ),
    )


def _fixture_digest(
    partitions: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...],
) -> str:
    digest = hashlib.sha256()
    for _, keys in partitions:
        for key in keys:
            transformed = transform_key(key)
            digest.update(
                canonical_json_bytes(
                    (
                        key[0],
                        transformed.serialized_key.hex(),
                        transformed.digest_hex,
                        transformed.u_string,
                        transformed.z_string,
                    ),
                    final_lf=True,
                )
            )
    return digest.hexdigest()
