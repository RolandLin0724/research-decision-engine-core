"""Closed immutable records for the superseding broader-replication lifecycle.

This module owns only record values, canonical construction, and byte validation.  It
does not inspect the filesystem, publish a final name, issue an authorization, select a
publication, or classify a lifecycle.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum, unique
from types import MappingProxyType
from typing import Final, NoReturn, cast

from research_decision_engine.benchmarks.broader_lifecycle_io import (
    CanonicalLedgerError,
    canonical_json_bytes,
    canonical_ledger_bytes,
    parse_canonical_ledger_bytes,
    raw_sha256,
)
from research_decision_engine.benchmarks.broader_protocol import (
    PROTOCOL_CHECKPOINT,
    PROTOCOL_VERSION,
    SOURCE_DESIGN_CHECKPOINT,
)

STUDY_ID: Final = PROTOCOL_VERSION
P0: Final = SOURCE_DESIGN_CHECKPOINT
P1: Final = PROTOCOL_CHECKPOINT

PRIMARY_TARGET_BASENAME: Final = "broader-replication-v1-128-seeds"
LEDGER_FINAL_NAMES: Final = frozenset({"attempt.json", "M11", "M12", "M13", "MF", "failure.json"})
LEDGER_LIFECYCLE_ORDER: Final = (
    "attempt.json",
    "M11",
    "M12",
    "M13",
    "MF",
)
CANONICAL_ARTIFACT_FILENAMES: Final = (
    "protocol_snapshot.json",
    "world_definitions.json",
    "arm_runs.jsonl",
    "oracle_provenance.jsonl",
    "calibration_estimates.jsonl",
    "trajectory_events.jsonl",
    "comparisons.jsonl",
    "contrast_results.csv",
    "resampling_audit.jsonl",
    "gate_evaluations.json",
    "audit_results.json",
    "run_manifest.json",
    "recommendation.json",
)
ARTIFACT_FILENAMES: Final = CANONICAL_ARTIFACT_FILENAMES
ARTIFACT_1_11_FILENAMES: Final = CANONICAL_ARTIFACT_FILENAMES[:11]

GIT40_PATTERN: Final = re.compile(r"[0-9a-f]{40}\Z")
SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}\Z")
PUBLICATION_ID_PATTERN: Final = re.compile(r"publication-[0-9a-f]{64}\Z")
AUTHORIZATION_ATTEMPT_ID_PATTERN: Final = re.compile(r"authorization-attempt-[0-9a-f]{64}\Z")

RECORD_SCHEMA_KIND: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        "attempt.json": ("broader-replication-attempt/v1", "ATTEMPT"),
        "M11": ("broader-replication-m11/v1", "M11"),
        "M12": ("broader-replication-m12/v1", "M12"),
        "M13": ("broader-replication-m13/v1", "M13"),
        "MF": ("broader-replication-mf/v1", "MF"),
        "failure.json": ("broader-replication-failure/v1", "FAILURE"),
    }
)

ENVELOPE_FIELDS: Final = frozenset(
    {
        "schema_version",
        "kind",
        "study_id",
        "canonical_target",
        "publication_id",
        "source_design_checkpoint",
        "protocol_checkpoint",
        "implementation_commit",
        "implementation_tree_sha256",
        "implementation_diff_sha256",
        "authorization_attempt_id",
    }
)
ATTEMPT_FIELDS: Final = ENVELOPE_FIELDS | {
    "intended_artifacts_1_11",
    "retry_kind",
    "retry_of_publication_id",
    "retry_source_canonical_target",
    "retry_source_authorization_attempt_id",
    "retry_source_attempt_sha256",
    "retry_source_failure_sha256",
    "retry_source_terminal_result",
    "retry_authorization_id",
}
M11_FIELDS: Final = ENVELOPE_FIELDS | {"attempt_sha256", "artifacts_1_11"}
M12_FIELDS: Final = ENVELOPE_FIELDS | {
    "m11_sha256",
    "manifest_filename",
    "manifest_byte_sha256",
}
M13_FIELDS: Final = ENVELOPE_FIELDS | {
    "m12_sha256",
    "recommendation_filename",
    "recommendation_byte_sha256",
}
MF_FIELDS: Final = ENVELOPE_FIELDS | {
    "m13_sha256",
    "artifacts_1_13",
    "graph_validation",
}
FAILURE_FIELDS: Final = ENVELOPE_FIELDS | {
    "phase",
    "failed_transition",
    "error_code",
    "predecessor_filename",
    "predecessor_sha256",
    "observed_inventory",
    "details_sha256",
}
RECORD_FIELDS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "attempt.json": frozenset(ATTEMPT_FIELDS),
        "M11": frozenset(M11_FIELDS),
        "M12": frozenset(M12_FIELDS),
        "M13": frozenset(M13_FIELDS),
        "MF": frozenset(MF_FIELDS),
        "failure.json": frozenset(FAILURE_FIELDS),
    }
)


class LifecycleRecordError(ValueError):
    """A selected ledger record violates the closed record contract."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@unique
class RetryKind(StrEnum):
    R1 = "R1"
    RX = "RX"


@unique
class RetryTerminalResult(StrEnum):
    ABORTED_BEFORE_PUBLICATION = "ABORTED_BEFORE_PUBLICATION"
    PARTIAL_SCIENTIFIC_PUBLICATION_INVALID = "PARTIAL_SCIENTIFIC_PUBLICATION_INVALID"
    MANIFEST_PUBLISHED_INCOMPLETE = "MANIFEST_PUBLISHED_INCOMPLETE"
    RECOMMENDATION_PUBLISHED_NOT_FINALIZED = "RECOMMENDATION_PUBLISHED_NOT_FINALIZED"
    INVALID = "INVALID"


@unique
class InventoryNamespace(StrEnum):
    LEDGER = "ledger"
    CANONICAL = "canonical"


@unique
class FailurePhase(StrEnum):
    ATTEMPT = "ATTEMPT"
    ARTIFACTS_1_11 = "ARTIFACTS_1_11"
    M11 = "M11"
    MANIFEST = "MANIFEST"
    M12 = "M12"
    RECOMMENDATION = "RECOMMENDATION"
    M13 = "M13"
    GRAPH_VALIDATION = "GRAPH_VALIDATION"
    MF = "MF"
    RECOVERY = "RECOVERY"


@unique
class FailedTransition(StrEnum):
    INSTALL_ATTEMPT = "INSTALL_ATTEMPT"
    ATTEMPT_TO_ARTIFACTS_1_11 = "ATTEMPT_TO_ARTIFACTS_1_11"
    ARTIFACTS_1_11_TO_M11 = "ARTIFACTS_1_11_TO_M11"
    M11_TO_MANIFEST = "M11_TO_MANIFEST"
    MANIFEST_TO_M12 = "MANIFEST_TO_M12"
    M12_TO_RECOMMENDATION = "M12_TO_RECOMMENDATION"
    RECOMMENDATION_TO_M13 = "RECOMMENDATION_TO_M13"
    M13_TO_GRAPH_VALIDATION = "M13_TO_GRAPH_VALIDATION"
    GRAPH_VALIDATION_TO_MF = "GRAPH_VALIDATION_TO_MF"


@unique
class FailureErrorCode(StrEnum):
    IO_STAGE_WRITE = "IO_STAGE_WRITE"
    IO_STAGE_FLUSH = "IO_STAGE_FLUSH"
    IO_STAGE_FILE_FSYNC = "IO_STAGE_FILE_FSYNC"
    IO_NO_REPLACE_INSTALL = "IO_NO_REPLACE_INSTALL"
    IO_FINAL_READBACK = "IO_FINAL_READBACK"
    IO_DIRECTORY_FSYNC = "IO_DIRECTORY_FSYNC"
    IO_PARENT_DIRECTORY_FSYNC = "IO_PARENT_DIRECTORY_FSYNC"
    NAMESPACE_TARGET = "NAMESPACE_TARGET"
    NAMESPACE_OBJECT_TYPE = "NAMESPACE_OBJECT_TYPE"
    NAMESPACE_UNEXPECTED_ENTRY = "NAMESPACE_UNEXPECTED_ENTRY"
    NAMESPACE_EXISTING_FINAL = "NAMESPACE_EXISTING_FINAL"
    VALIDATION_STAGED_BYTES = "VALIDATION_STAGED_BYTES"
    VALIDATION_GRAPH = "VALIDATION_GRAPH"
    RECOVERY_ABANDONED = "RECOVERY_ABANDONED"
    INTERNAL_INVARIANT = "INTERNAL_INVARIANT"


@unique
class LedgerPredecessor(StrEnum):
    ATTEMPT = "attempt.json"
    M11 = "M11"
    M12 = "M12"
    M13 = "M13"


@unique
class InventoryVariant(StrEnum):
    ATTEMPT_ONLY = "A"
    ARTIFACT_SUBSET = "A+g"
    ARTIFACTS_1_11 = "A+G"
    THROUGH_M11 = "THROUGH_M11"
    THROUGH_MANIFEST = "THROUGH_MANIFEST"
    THROUGH_M12 = "THROUGH_M12"
    THROUGH_RECOMMENDATION = "THROUGH_RECOMMENDATION"
    THROUGH_M13 = "THROUGH_M13"


PREINSTALL_ERROR_CODES: Final = frozenset(
    {
        FailureErrorCode.NAMESPACE_TARGET,
        FailureErrorCode.NAMESPACE_OBJECT_TYPE,
        FailureErrorCode.NAMESPACE_UNEXPECTED_ENTRY,
        FailureErrorCode.IO_STAGE_WRITE,
        FailureErrorCode.IO_STAGE_FLUSH,
        FailureErrorCode.IO_STAGE_FILE_FSYNC,
        FailureErrorCode.VALIDATION_STAGED_BYTES,
        FailureErrorCode.IO_NO_REPLACE_INSTALL,
        FailureErrorCode.INTERNAL_INVARIANT,
    }
)
POSTINSTALL_ERROR_CODES: Final = frozenset(
    {
        FailureErrorCode.IO_FINAL_READBACK,
        FailureErrorCode.IO_DIRECTORY_FSYNC,
        FailureErrorCode.IO_PARENT_DIRECTORY_FSYNC,
        FailureErrorCode.INTERNAL_INVARIANT,
    }
)
POSTINSTALL_OR_EXISTING_ERROR_CODES: Final = POSTINSTALL_ERROR_CODES | {
    FailureErrorCode.NAMESPACE_EXISTING_FINAL
}
SUBSET_SURVIVOR_ERROR_CODES: Final = frozenset(
    {FailureErrorCode.INTERNAL_INVARIANT, FailureErrorCode.NAMESPACE_EXISTING_FINAL}
)
GRAPH_ONLY_ERROR_CODES: Final = frozenset(
    {
        FailureErrorCode.IO_FINAL_READBACK,
        FailureErrorCode.VALIDATION_GRAPH,
        FailureErrorCode.INTERNAL_INVARIANT,
    }
)
RECOVERY_ONLY_ERROR_CODES: Final = frozenset({FailureErrorCode.RECOVERY_ABANDONED})


@dataclass(frozen=True, slots=True)
class FailureCompatibilityRule:
    phase: FailurePhase
    transition: FailedTransition
    inventory_variant: InventoryVariant
    predecessor: LedgerPredecessor
    allowed_error_codes: frozenset[FailureErrorCode]


FAILURE_COMPATIBILITY_MATRIX: Final = (
    FailureCompatibilityRule(
        FailurePhase.ATTEMPT,
        FailedTransition.INSTALL_ATTEMPT,
        InventoryVariant.ATTEMPT_ONLY,
        LedgerPredecessor.ATTEMPT,
        POSTINSTALL_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.ARTIFACTS_1_11,
        FailedTransition.ATTEMPT_TO_ARTIFACTS_1_11,
        InventoryVariant.ATTEMPT_ONLY,
        LedgerPredecessor.ATTEMPT,
        PREINSTALL_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.ARTIFACTS_1_11,
        FailedTransition.ATTEMPT_TO_ARTIFACTS_1_11,
        InventoryVariant.ARTIFACT_SUBSET,
        LedgerPredecessor.ATTEMPT,
        SUBSET_SURVIVOR_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.ARTIFACTS_1_11,
        FailedTransition.ATTEMPT_TO_ARTIFACTS_1_11,
        InventoryVariant.ARTIFACTS_1_11,
        LedgerPredecessor.ATTEMPT,
        POSTINSTALL_OR_EXISTING_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.M11,
        FailedTransition.ARTIFACTS_1_11_TO_M11,
        InventoryVariant.ARTIFACTS_1_11,
        LedgerPredecessor.ATTEMPT,
        PREINSTALL_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.M11,
        FailedTransition.ARTIFACTS_1_11_TO_M11,
        InventoryVariant.THROUGH_M11,
        LedgerPredecessor.M11,
        POSTINSTALL_OR_EXISTING_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.MANIFEST,
        FailedTransition.M11_TO_MANIFEST,
        InventoryVariant.THROUGH_M11,
        LedgerPredecessor.M11,
        PREINSTALL_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.MANIFEST,
        FailedTransition.M11_TO_MANIFEST,
        InventoryVariant.THROUGH_MANIFEST,
        LedgerPredecessor.M11,
        POSTINSTALL_OR_EXISTING_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.M12,
        FailedTransition.MANIFEST_TO_M12,
        InventoryVariant.THROUGH_MANIFEST,
        LedgerPredecessor.M11,
        PREINSTALL_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.M12,
        FailedTransition.MANIFEST_TO_M12,
        InventoryVariant.THROUGH_M12,
        LedgerPredecessor.M12,
        POSTINSTALL_OR_EXISTING_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.RECOMMENDATION,
        FailedTransition.M12_TO_RECOMMENDATION,
        InventoryVariant.THROUGH_M12,
        LedgerPredecessor.M12,
        PREINSTALL_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.RECOMMENDATION,
        FailedTransition.M12_TO_RECOMMENDATION,
        InventoryVariant.THROUGH_RECOMMENDATION,
        LedgerPredecessor.M12,
        POSTINSTALL_OR_EXISTING_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.M13,
        FailedTransition.RECOMMENDATION_TO_M13,
        InventoryVariant.THROUGH_RECOMMENDATION,
        LedgerPredecessor.M12,
        PREINSTALL_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.M13,
        FailedTransition.RECOMMENDATION_TO_M13,
        InventoryVariant.THROUGH_M13,
        LedgerPredecessor.M13,
        POSTINSTALL_OR_EXISTING_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.GRAPH_VALIDATION,
        FailedTransition.M13_TO_GRAPH_VALIDATION,
        InventoryVariant.THROUGH_M13,
        LedgerPredecessor.M13,
        GRAPH_ONLY_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.MF,
        FailedTransition.GRAPH_VALIDATION_TO_MF,
        InventoryVariant.THROUGH_M13,
        LedgerPredecessor.M13,
        PREINSTALL_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.RECOVERY,
        FailedTransition.ATTEMPT_TO_ARTIFACTS_1_11,
        InventoryVariant.ATTEMPT_ONLY,
        LedgerPredecessor.ATTEMPT,
        RECOVERY_ONLY_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.RECOVERY,
        FailedTransition.ARTIFACTS_1_11_TO_M11,
        InventoryVariant.ARTIFACT_SUBSET,
        LedgerPredecessor.ATTEMPT,
        RECOVERY_ONLY_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.RECOVERY,
        FailedTransition.ARTIFACTS_1_11_TO_M11,
        InventoryVariant.ARTIFACTS_1_11,
        LedgerPredecessor.ATTEMPT,
        RECOVERY_ONLY_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.RECOVERY,
        FailedTransition.M11_TO_MANIFEST,
        InventoryVariant.THROUGH_M11,
        LedgerPredecessor.M11,
        RECOVERY_ONLY_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.RECOVERY,
        FailedTransition.MANIFEST_TO_M12,
        InventoryVariant.THROUGH_MANIFEST,
        LedgerPredecessor.M11,
        RECOVERY_ONLY_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.RECOVERY,
        FailedTransition.M12_TO_RECOMMENDATION,
        InventoryVariant.THROUGH_M12,
        LedgerPredecessor.M12,
        RECOVERY_ONLY_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.RECOVERY,
        FailedTransition.RECOMMENDATION_TO_M13,
        InventoryVariant.THROUGH_RECOMMENDATION,
        LedgerPredecessor.M12,
        RECOVERY_ONLY_ERROR_CODES,
    ),
    FailureCompatibilityRule(
        FailurePhase.RECOVERY,
        FailedTransition.M13_TO_GRAPH_VALIDATION,
        InventoryVariant.THROUGH_M13,
        LedgerPredecessor.M13,
        RECOVERY_ONLY_ERROR_CODES,
    ),
)


def _fail(code: str, message: str) -> NoReturn:
    raise LifecycleRecordError(code, message)


def _require_string(value: object, field: str) -> str:
    if type(value) is not str:
        _fail("FIELD_TYPE", f"{field} must be a JSON string.")
    result = value
    if unicodedata.normalize("NFC", result) != result:
        _fail("FIELD_VALUE", f"{field} must be NFC.")
    return result


def _require_optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field)


def _require_sha256(value: object, field: str) -> str:
    result = _require_string(value, field)
    if SHA256_PATTERN.fullmatch(result) is None:
        _fail("FIELD_VALUE", f"{field} must be lowercase SHA256.")
    return result


def _require_optional_sha256(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _require_sha256(value, field)


def _require_publication_id(value: object, field: str = "publication_id") -> str:
    result = _require_string(value, field)
    if PUBLICATION_ID_PATTERN.fullmatch(result) is None:
        _fail("FIELD_VALUE", f"{field} must be PUBLICATION_ID.")
    return result


def _require_optional_publication_id(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _require_publication_id(value, field)


def _require_authorization_id(value: object, field: str) -> str:
    result = _require_string(value, field)
    if AUTHORIZATION_ATTEMPT_ID_PATTERN.fullmatch(result) is None:
        _fail("FIELD_VALUE", f"{field} must be AUTHORIZATION_ATTEMPT_ID.")
    return result


def _require_optional_authorization_id(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _require_authorization_id(value, field)


def _require_exact_fields(value: Mapping[str, object], fields: frozenset[str]) -> None:
    actual = frozenset(value)
    missing = fields - actual
    if missing:
        _fail("MISSING_FIELD", f"Missing fields: {','.join(sorted(missing))}.")
    extra = actual - fields
    if extra:
        _fail("UNKNOWN_FIELD", f"Unknown fields: {','.join(sorted(extra))}.")


def _require_object(value: object, field: str) -> dict[str, object]:
    if type(value) is not dict:
        _fail("FIELD_TYPE", f"{field} must be a JSON object.")
    return cast(dict[str, object], value)


def _require_array(value: object, field: str) -> list[object]:
    if type(value) is not list:
        _fail("FIELD_TYPE", f"{field} must be a JSON array.")
    return cast(list[object], value)


def _require_enum[E: StrEnum](enum_type: type[E], value: object, field: str) -> E:
    text = _require_string(value, field)
    try:
        return enum_type(text)
    except ValueError:
        _fail("FIELD_VALUE", f"{field} has a value outside its closed enumeration.")


def _split_target(value: str, field: str) -> tuple[str, str]:
    _require_string(value, field)
    if not value or "\\" in value or value.endswith("/"):
        _fail("FIELD_VALUE", f"{field} is not a canonical target string.")
    if any(ord(character) <= 0x1F for character in value):
        _fail("FIELD_VALUE", f"{field} contains a control character.")
    if not value.startswith("/") and re.match(r"[A-Za-z]:/", value) is None:
        _fail("FIELD_VALUE", f"{field} must be an absolute canonical path.")
    parent, separator, leaf = value.rpartition("/")
    if not separator or not leaf:
        _fail("FIELD_VALUE", f"{field} has no target leaf.")
    components = value.replace("//", "/").split("/")
    if any(component in {".", ".."} for component in components):
        _fail("FIELD_VALUE", f"{field} contains a forbidden path component.")
    if leaf != PRIMARY_TARGET_BASENAME:
        prefix = f"{PRIMARY_TARGET_BASENAME}.retry-"
        if not leaf.startswith(prefix):
            _fail("FIELD_VALUE", f"{field} is outside the closed target family.")
        _require_publication_id(leaf.removeprefix(prefix), f"{field} retry publication")
    return (parent or "/", leaf)


def _require_envelope_for(envelope: BindingEnvelope, record_name: str) -> None:
    schema_kind = RECORD_SCHEMA_KIND.get(record_name)
    if schema_kind is None:
        _fail("UNKNOWN_RECORD_NAME", f"{record_name!r} is not a permitted ledger final.")
    if (envelope.schema_version, envelope.kind) != schema_kind:
        _fail("FIELD_VALUE", f"Envelope schema/kind do not match {record_name}.")


@dataclass(frozen=True, slots=True)
class BindingEnvelope:
    schema_version: str
    kind: str
    study_id: str
    canonical_target: str
    publication_id: str
    source_design_checkpoint: str
    protocol_checkpoint: str
    implementation_commit: str
    implementation_tree_sha256: str
    implementation_diff_sha256: str
    authorization_attempt_id: str

    def __post_init__(self) -> None:
        _require_string(self.schema_version, "schema_version")
        _require_string(self.kind, "kind")
        if (self.schema_version, self.kind) not in RECORD_SCHEMA_KIND.values():
            _fail("FIELD_VALUE", "schema_version/kind is not a supported record pair.")
        if self.study_id != STUDY_ID:
            _fail("BINDING_MISMATCH", "study_id does not equal the frozen study.")
        _split_target(self.canonical_target, "canonical_target")
        _require_publication_id(self.publication_id)
        if self.source_design_checkpoint != SOURCE_DESIGN_CHECKPOINT:
            _fail(
                "BINDING_MISMATCH",
                "source_design_checkpoint does not equal the historical checkpoint.",
            )
        if self.protocol_checkpoint != PROTOCOL_CHECKPOINT:
            _fail(
                "BINDING_MISMATCH",
                "protocol_checkpoint does not equal the superseding checkpoint.",
            )
        if GIT40_PATTERN.fullmatch(self.implementation_commit) is None:
            _fail("FIELD_VALUE", "implementation_commit must be GIT40.")
        _require_sha256(self.implementation_tree_sha256, "implementation_tree_sha256")
        _require_sha256(self.implementation_diff_sha256, "implementation_diff_sha256")
        _require_authorization_id(self.authorization_attempt_id, "authorization_attempt_id")


@dataclass(frozen=True, slots=True)
class ArtifactHash:
    order: int
    filename: str
    byte_sha256: str

    def __post_init__(self) -> None:
        if type(self.order) is not int or not 1 <= self.order <= 13:
            _fail("FIELD_VALUE", "ArtifactHash.order must be an artifact order from 1 to 13.")
        if self.filename != CANONICAL_ARTIFACT_FILENAMES[self.order - 1]:
            _fail("FIELD_VALUE", "ArtifactHash filename does not match its frozen order.")
        _require_sha256(self.byte_sha256, "ArtifactHash.byte_sha256")


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    namespace: InventoryNamespace
    filename: str
    byte_sha256: str

    def __post_init__(self) -> None:
        if type(self.namespace) is not InventoryNamespace:
            _fail("FIELD_TYPE", "InventoryEntry.namespace must be InventoryNamespace.")
        _require_string(self.filename, "InventoryEntry.filename")
        if self.namespace is InventoryNamespace.LEDGER:
            if self.filename not in {"attempt.json", "M11", "M12", "M13"}:
                _fail("FIELD_VALUE", "Inventory ledger filename is not observable in a failure.")
        elif self.filename not in CANONICAL_ARTIFACT_FILENAMES:
            _fail("FIELD_VALUE", "Inventory canonical filename is not frozen.")
        _require_sha256(self.byte_sha256, "InventoryEntry.byte_sha256")


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    envelope: BindingEnvelope
    intended_artifacts_1_11: tuple[ArtifactHash, ...]
    retry_kind: RetryKind | None
    retry_of_publication_id: str | None
    retry_source_canonical_target: str | None
    retry_source_authorization_attempt_id: str | None
    retry_source_attempt_sha256: str | None
    retry_source_failure_sha256: str | None
    retry_source_terminal_result: RetryTerminalResult | None
    retry_authorization_id: str | None

    def __post_init__(self) -> None:
        _require_envelope_for(self.envelope, "attempt.json")
        _require_artifact_sequence(self.intended_artifacts_1_11, 11)
        _validate_retry_tuple_structure(self)


@dataclass(frozen=True, slots=True)
class M11Record:
    envelope: BindingEnvelope
    attempt_sha256: str
    artifacts_1_11: tuple[ArtifactHash, ...]

    def __post_init__(self) -> None:
        _require_envelope_for(self.envelope, "M11")
        _require_sha256(self.attempt_sha256, "attempt_sha256")
        _require_artifact_sequence(self.artifacts_1_11, 11)


@dataclass(frozen=True, slots=True)
class M12Record:
    envelope: BindingEnvelope
    m11_sha256: str
    manifest_filename: str
    manifest_byte_sha256: str

    def __post_init__(self) -> None:
        _require_envelope_for(self.envelope, "M12")
        _require_sha256(self.m11_sha256, "m11_sha256")
        if self.manifest_filename != "run_manifest.json":
            _fail("FIELD_VALUE", "manifest_filename must be run_manifest.json.")
        _require_sha256(self.manifest_byte_sha256, "manifest_byte_sha256")


@dataclass(frozen=True, slots=True)
class M13Record:
    envelope: BindingEnvelope
    m12_sha256: str
    recommendation_filename: str
    recommendation_byte_sha256: str

    def __post_init__(self) -> None:
        _require_envelope_for(self.envelope, "M13")
        _require_sha256(self.m12_sha256, "m12_sha256")
        if self.recommendation_filename != "recommendation.json":
            _fail("FIELD_VALUE", "recommendation_filename must be recommendation.json.")
        _require_sha256(self.recommendation_byte_sha256, "recommendation_byte_sha256")


@dataclass(frozen=True, slots=True)
class MFRecord:
    envelope: BindingEnvelope
    m13_sha256: str
    artifacts_1_13: tuple[ArtifactHash, ...]
    graph_validation: str

    def __post_init__(self) -> None:
        _require_envelope_for(self.envelope, "MF")
        _require_sha256(self.m13_sha256, "m13_sha256")
        _require_artifact_sequence(self.artifacts_1_13, 13)
        if self.graph_validation != "PASS":
            _fail("FIELD_VALUE", 'graph_validation must be exactly "PASS".')


@dataclass(frozen=True, slots=True)
class FailureRecord:
    envelope: BindingEnvelope
    phase: FailurePhase
    failed_transition: FailedTransition
    error_code: FailureErrorCode
    predecessor_filename: LedgerPredecessor
    predecessor_sha256: str
    observed_inventory: tuple[InventoryEntry, ...]
    details_sha256: str

    def __post_init__(self) -> None:
        _require_envelope_for(self.envelope, "failure.json")
        if type(self.phase) is not FailurePhase:
            _fail("FIELD_TYPE", "phase must be FailurePhase.")
        if type(self.failed_transition) is not FailedTransition:
            _fail("FIELD_TYPE", "failed_transition must be FailedTransition.")
        if type(self.error_code) is not FailureErrorCode:
            _fail("FIELD_TYPE", "error_code must be FailureErrorCode.")
        if type(self.predecessor_filename) is not LedgerPredecessor:
            _fail("FIELD_TYPE", "predecessor_filename must be LedgerPredecessor.")
        _require_sha256(self.predecessor_sha256, "predecessor_sha256")
        _failure_inventory_variant(self.observed_inventory)
        _validate_failure_compatibility(self)
        _require_sha256(self.details_sha256, "details_sha256")
        expected = failure_details_sha256(
            envelope=self.envelope,
            phase=self.phase,
            failed_transition=self.failed_transition,
            error_code=self.error_code,
            predecessor_filename=self.predecessor_filename,
            predecessor_sha256=self.predecessor_sha256,
            observed_inventory=self.observed_inventory,
        )
        if self.details_sha256 != expected:
            _fail("DETAILS_HASH", "details_sha256 does not match the frozen preimage.")


LedgerRecord = AttemptRecord | M11Record | M12Record | M13Record | MFRecord | FailureRecord


def _require_artifact_sequence(values: tuple[ArtifactHash, ...], final_order: int) -> None:
    if type(values) is not tuple:
        _fail("FIELD_TYPE", "Artifact hash lists must be immutable tuples internally.")
    if len(values) != final_order:
        _fail("FIELD_VALUE", f"Artifact hash list must contain exact orders 1..{final_order}.")
    for expected_order, value in enumerate(values, start=1):
        if type(value) is not ArtifactHash or value.order != expected_order:
            _fail("FIELD_VALUE", f"Artifact hash list must contain exact orders 1..{final_order}.")


def _validate_retry_tuple_structure(record: AttemptRecord) -> None:
    nullable_values = (
        record.retry_of_publication_id,
        record.retry_source_canonical_target,
        record.retry_source_authorization_attempt_id,
        record.retry_source_attempt_sha256,
        record.retry_source_failure_sha256,
        record.retry_source_terminal_result,
        record.retry_authorization_id,
    )
    if record.retry_kind is None:
        if any(value is not None for value in nullable_values):
            _fail("RETRY_TUPLE", "A non-retry attempt requires an all-null retry tuple.")
        return
    if type(record.retry_kind) is not RetryKind:
        _fail("FIELD_TYPE", "retry_kind must be RetryKind or null.")
    required = (
        record.retry_of_publication_id,
        record.retry_source_canonical_target,
        record.retry_source_authorization_attempt_id,
        record.retry_source_attempt_sha256,
        record.retry_source_terminal_result,
        record.retry_authorization_id,
    )
    if any(value is None for value in required):
        _fail("RETRY_TUPLE", "A retry requires a complete non-null source tuple.")
    _require_publication_id(record.retry_of_publication_id, "retry_of_publication_id")
    source_target = cast(str, record.retry_source_canonical_target)
    _split_target(source_target, "retry_source_canonical_target")
    _require_authorization_id(
        record.retry_source_authorization_attempt_id,
        "retry_source_authorization_attempt_id",
    )
    _require_sha256(record.retry_source_attempt_sha256, "retry_source_attempt_sha256")
    if record.retry_source_failure_sha256 is not None:
        _require_sha256(record.retry_source_failure_sha256, "retry_source_failure_sha256")
    if type(record.retry_source_terminal_result) is not RetryTerminalResult:
        _fail("FIELD_TYPE", "retry_source_terminal_result must be a closed terminal result.")
    _require_authorization_id(record.retry_authorization_id, "retry_authorization_id")


def validate_attempt_retry_semantics(record: AttemptRecord) -> None:
    """Validate retry placement/lineage semantics after reader allegation precedence."""

    source_authorization_id = record.retry_source_authorization_attempt_id
    retry_authorization_id = record.retry_authorization_id
    source_publication_id = record.retry_of_publication_id
    source_target = record.retry_source_canonical_target
    _, target_leaf = _split_target(record.envelope.canonical_target, "canonical_target")
    if record.retry_kind is None:
        if target_leaf != PRIMARY_TARGET_BASENAME:
            _fail("RETRY_TUPLE", "An all-null attempt must bind PRIMARY_TARGET.")
        return
    if (
        source_authorization_id is None
        or retry_authorization_id is None
        or source_publication_id is None
        or source_target is None
    ):
        _fail("RETRY_TUPLE", "A retry requires a complete non-null source tuple.")
    source_parent, _ = _split_target(source_target, "retry_source_canonical_target")
    target_parent, target_leaf = _split_target(record.envelope.canonical_target, "canonical_target")
    if retry_authorization_id != record.envelope.authorization_attempt_id:
        _fail("RETRY_TUPLE", "retry_authorization_id must equal authorization_attempt_id.")
    if source_authorization_id == record.envelope.authorization_attempt_id:
        _fail("RETRY_TUPLE", "A retry must use a fresh authorization identity.")
    if source_publication_id == record.envelope.publication_id:
        _fail("RETRY_TUPLE", "A retry publication cannot refer to itself.")
    if record.retry_kind is RetryKind.R1:
        if record.retry_source_failure_sha256 is None:
            _fail("RETRY_TUPLE", "R1 requires a source failure hash.")
        if (
            record.retry_source_terminal_result
            is not RetryTerminalResult.ABORTED_BEFORE_PUBLICATION
        ):
            _fail("RETRY_TUPLE", "R1 requires an aborted-before-publication source.")
        if record.envelope.canonical_target != source_target:
            _fail("RETRY_TUPLE", "R1 requires exact same-target placement.")
    else:
        if target_parent != source_parent or record.envelope.canonical_target == source_target:
            _fail("RETRY_TUPLE", "RX requires a distinct sibling target.")
        expected_leaf = f"{PRIMARY_TARGET_BASENAME}.retry-{record.envelope.publication_id}"
        if target_leaf != expected_leaf:
            _fail("RETRY_TUPLE", "RX target must be derived from the new publication_id.")


def _failure_inventory_variant(values: tuple[InventoryEntry, ...]) -> InventoryVariant:
    if type(values) is not tuple or not values:
        _fail("INVENTORY", "observed_inventory must be a nonempty immutable tuple.")
    if any(type(value) is not InventoryEntry for value in values):
        _fail("INVENTORY", "observed_inventory contains an invalid entry.")
    pairs = tuple((entry.namespace, entry.filename) for entry in values)
    if len(set(pairs)) != len(pairs):
        _fail("INVENTORY", "observed_inventory contains a duplicate entry.")
    if pairs[0] != (InventoryNamespace.LEDGER, "attempt.json"):
        _fail("INVENTORY", "observed_inventory must begin with attempt.json.")

    cursor = 1
    artifact_orders: list[int] = []
    while cursor < len(values) and values[cursor].namespace is InventoryNamespace.CANONICAL:
        filename = values[cursor].filename
        if filename not in ARTIFACT_1_11_FILENAMES:
            break
        order = ARTIFACT_1_11_FILENAMES.index(filename) + 1
        artifact_orders.append(order)
        cursor += 1
    if artifact_orders != sorted(artifact_orders):
        _fail("INVENTORY", "Artifacts 1-11 are not in frozen order.")
    if cursor == len(values):
        if not artifact_orders:
            return InventoryVariant.ATTEMPT_ONLY
        if len(artifact_orders) < 11:
            return InventoryVariant.ARTIFACT_SUBSET
        if artifact_orders == list(range(1, 12)):
            return InventoryVariant.ARTIFACTS_1_11
        _fail("INVENTORY", "The complete Artifacts 1-11 inventory is malformed.")
    if artifact_orders != list(range(1, 12)):
        _fail("INVENTORY", "A later lifecycle final requires all Artifacts 1-11.")

    suffixes = (
        (((InventoryNamespace.LEDGER, "M11"),), InventoryVariant.THROUGH_M11),
        (
            (
                (InventoryNamespace.LEDGER, "M11"),
                (InventoryNamespace.CANONICAL, "run_manifest.json"),
            ),
            InventoryVariant.THROUGH_MANIFEST,
        ),
        (
            (
                (InventoryNamespace.LEDGER, "M11"),
                (InventoryNamespace.CANONICAL, "run_manifest.json"),
                (InventoryNamespace.LEDGER, "M12"),
            ),
            InventoryVariant.THROUGH_M12,
        ),
        (
            (
                (InventoryNamespace.LEDGER, "M11"),
                (InventoryNamespace.CANONICAL, "run_manifest.json"),
                (InventoryNamespace.LEDGER, "M12"),
                (InventoryNamespace.CANONICAL, "recommendation.json"),
            ),
            InventoryVariant.THROUGH_RECOMMENDATION,
        ),
        (
            (
                (InventoryNamespace.LEDGER, "M11"),
                (InventoryNamespace.CANONICAL, "run_manifest.json"),
                (InventoryNamespace.LEDGER, "M12"),
                (InventoryNamespace.CANONICAL, "recommendation.json"),
                (InventoryNamespace.LEDGER, "M13"),
            ),
            InventoryVariant.THROUGH_M13,
        ),
    )
    observed_suffix = pairs[cursor:]
    for suffix, variant in suffixes:
        if observed_suffix == suffix:
            return variant
    _fail("INVENTORY", "observed_inventory is not one frozen lifecycle variant.")


def _validate_failure_compatibility(record: FailureRecord) -> None:
    variant = _failure_inventory_variant(record.observed_inventory)
    rules = (
        rule
        for rule in FAILURE_COMPATIBILITY_MATRIX
        if rule.phase is record.phase
        and rule.transition is record.failed_transition
        and rule.inventory_variant is variant
        and rule.predecessor is record.predecessor_filename
    )
    rule = next(rules, None)
    if rule is None or record.error_code not in rule.allowed_error_codes:
        _fail(
            "FAILURE_COMPATIBILITY",
            "phase/transition/predecessor/inventory/error tuple is not frozen.",
        )
    predecessor_entries = tuple(
        entry
        for entry in record.observed_inventory
        if entry.namespace is InventoryNamespace.LEDGER
        and entry.filename == record.predecessor_filename.value
    )
    if len(predecessor_entries) != 1:
        _fail("FAILURE_COMPATIBILITY", "Failure predecessor is absent or ambiguous.")
    if predecessor_entries[0].byte_sha256 != record.predecessor_sha256:
        _fail("FAILURE_COMPATIBILITY", "Failure predecessor hash does not match inventory.")


def make_binding_envelope(
    record_name: str,
    *,
    canonical_target: str,
    publication_id: str,
    implementation_commit: str,
    implementation_tree_sha256: str,
    implementation_diff_sha256: str,
    authorization_attempt_id: str,
) -> BindingEnvelope:
    """Construct a binding envelope with every protocol constant pinned."""

    schema_kind = RECORD_SCHEMA_KIND.get(record_name)
    if schema_kind is None:
        _fail("UNKNOWN_RECORD_NAME", f"{record_name!r} is not a permitted ledger final.")
    return BindingEnvelope(
        schema_version=schema_kind[0],
        kind=schema_kind[1],
        study_id=STUDY_ID,
        canonical_target=canonical_target,
        publication_id=publication_id,
        source_design_checkpoint=SOURCE_DESIGN_CHECKPOINT,
        protocol_checkpoint=PROTOCOL_CHECKPOINT,
        implementation_commit=implementation_commit,
        implementation_tree_sha256=implementation_tree_sha256,
        implementation_diff_sha256=implementation_diff_sha256,
        authorization_attempt_id=authorization_attempt_id,
    )


def envelope_for_record(envelope: BindingEnvelope, record_name: str) -> BindingEnvelope:
    """Copy one attempt binding context into another record's schema/kind envelope."""

    return make_binding_envelope(
        record_name,
        canonical_target=envelope.canonical_target,
        publication_id=envelope.publication_id,
        implementation_commit=envelope.implementation_commit,
        implementation_tree_sha256=envelope.implementation_tree_sha256,
        implementation_diff_sha256=envelope.implementation_diff_sha256,
        authorization_attempt_id=envelope.authorization_attempt_id,
    )


def _envelope_value(envelope: BindingEnvelope) -> dict[str, object]:
    return {
        "schema_version": envelope.schema_version,
        "kind": envelope.kind,
        "study_id": envelope.study_id,
        "canonical_target": envelope.canonical_target,
        "publication_id": envelope.publication_id,
        "source_design_checkpoint": envelope.source_design_checkpoint,
        "protocol_checkpoint": envelope.protocol_checkpoint,
        "implementation_commit": envelope.implementation_commit,
        "implementation_tree_sha256": envelope.implementation_tree_sha256,
        "implementation_diff_sha256": envelope.implementation_diff_sha256,
        "authorization_attempt_id": envelope.authorization_attempt_id,
    }


def _artifact_value(value: ArtifactHash) -> dict[str, object]:
    return {"order": value.order, "filename": value.filename, "byte_sha256": value.byte_sha256}


def _inventory_value(value: InventoryEntry) -> dict[str, object]:
    return {
        "namespace": value.namespace.value,
        "filename": value.filename,
        "byte_sha256": value.byte_sha256,
    }


def record_to_value(record: LedgerRecord) -> dict[str, object]:
    """Return the exact flat JSON object for an immutable ledger record."""

    value = _envelope_value(record.envelope)
    if isinstance(record, AttemptRecord):
        value.update(
            {
                "intended_artifacts_1_11": [
                    _artifact_value(item) for item in record.intended_artifacts_1_11
                ],
                "retry_kind": None if record.retry_kind is None else record.retry_kind.value,
                "retry_of_publication_id": record.retry_of_publication_id,
                "retry_source_canonical_target": record.retry_source_canonical_target,
                "retry_source_authorization_attempt_id": (
                    record.retry_source_authorization_attempt_id
                ),
                "retry_source_attempt_sha256": record.retry_source_attempt_sha256,
                "retry_source_failure_sha256": record.retry_source_failure_sha256,
                "retry_source_terminal_result": (
                    None
                    if record.retry_source_terminal_result is None
                    else record.retry_source_terminal_result.value
                ),
                "retry_authorization_id": record.retry_authorization_id,
            }
        )
    elif isinstance(record, M11Record):
        value.update(
            {
                "attempt_sha256": record.attempt_sha256,
                "artifacts_1_11": [_artifact_value(item) for item in record.artifacts_1_11],
            }
        )
    elif isinstance(record, M12Record):
        value.update(
            {
                "m11_sha256": record.m11_sha256,
                "manifest_filename": record.manifest_filename,
                "manifest_byte_sha256": record.manifest_byte_sha256,
            }
        )
    elif isinstance(record, M13Record):
        value.update(
            {
                "m12_sha256": record.m12_sha256,
                "recommendation_filename": record.recommendation_filename,
                "recommendation_byte_sha256": record.recommendation_byte_sha256,
            }
        )
    elif isinstance(record, MFRecord):
        value.update(
            {
                "m13_sha256": record.m13_sha256,
                "artifacts_1_13": [_artifact_value(item) for item in record.artifacts_1_13],
                "graph_validation": record.graph_validation,
            }
        )
    else:
        value.update(
            {
                "phase": record.phase.value,
                "failed_transition": record.failed_transition.value,
                "error_code": record.error_code.value,
                "predecessor_filename": record.predecessor_filename.value,
                "predecessor_sha256": record.predecessor_sha256,
                "observed_inventory": [
                    _inventory_value(item) for item in record.observed_inventory
                ],
                "details_sha256": record.details_sha256,
            }
        )
    return value


def record_bytes(record: LedgerRecord) -> bytes:
    """Serialize a validated record with the one canonical terminal LF."""

    if isinstance(record, AttemptRecord):
        validate_attempt_retry_semantics(record)
    return canonical_ledger_bytes(record_to_value(record))


def record_sha256(record: LedgerRecord) -> str:
    """Hash complete canonical record bytes, including the terminal LF."""

    return raw_sha256(record_bytes(record))


def build_attempt_record(
    envelope: BindingEnvelope,
    intended_artifacts_1_11: Sequence[ArtifactHash],
    *,
    retry_kind: RetryKind | None = None,
    retry_of_publication_id: str | None = None,
    retry_source_canonical_target: str | None = None,
    retry_source_authorization_attempt_id: str | None = None,
    retry_source_attempt_sha256: str | None = None,
    retry_source_failure_sha256: str | None = None,
    retry_source_terminal_result: RetryTerminalResult | None = None,
    retry_authorization_id: str | None = None,
) -> bytes:
    return record_bytes(
        AttemptRecord(
            envelope=envelope,
            intended_artifacts_1_11=tuple(intended_artifacts_1_11),
            retry_kind=retry_kind,
            retry_of_publication_id=retry_of_publication_id,
            retry_source_canonical_target=retry_source_canonical_target,
            retry_source_authorization_attempt_id=retry_source_authorization_attempt_id,
            retry_source_attempt_sha256=retry_source_attempt_sha256,
            retry_source_failure_sha256=retry_source_failure_sha256,
            retry_source_terminal_result=retry_source_terminal_result,
            retry_authorization_id=retry_authorization_id,
        )
    )


def build_m11_record(
    envelope: BindingEnvelope,
    *,
    attempt_sha256: str,
    artifacts_1_11: Sequence[ArtifactHash],
) -> bytes:
    return record_bytes(M11Record(envelope, attempt_sha256, tuple(artifacts_1_11)))


def build_m12_record(
    envelope: BindingEnvelope, *, m11_sha256: str, manifest_byte_sha256: str
) -> bytes:
    return record_bytes(M12Record(envelope, m11_sha256, "run_manifest.json", manifest_byte_sha256))


def build_m13_record(
    envelope: BindingEnvelope, *, m12_sha256: str, recommendation_byte_sha256: str
) -> bytes:
    return record_bytes(
        M13Record(envelope, m12_sha256, "recommendation.json", recommendation_byte_sha256)
    )


def build_mf_record(
    envelope: BindingEnvelope,
    *,
    m13_sha256: str,
    artifacts_1_13: Sequence[ArtifactHash],
) -> bytes:
    return record_bytes(MFRecord(envelope, m13_sha256, tuple(artifacts_1_13), "PASS"))


def failure_details_sha256(
    *,
    envelope: BindingEnvelope,
    phase: FailurePhase,
    failed_transition: FailedTransition,
    error_code: FailureErrorCode,
    predecessor_filename: LedgerPredecessor,
    predecessor_sha256: str,
    observed_inventory: Sequence[InventoryEntry],
) -> str:
    """Compute the exact no-LF failure-details domain hash."""

    details: dict[str, object] = {
        "study_id": envelope.study_id,
        "canonical_target": envelope.canonical_target,
        "publication_id": envelope.publication_id,
        "source_design_checkpoint": envelope.source_design_checkpoint,
        "protocol_checkpoint": envelope.protocol_checkpoint,
        "implementation_commit": envelope.implementation_commit,
        "implementation_tree_sha256": envelope.implementation_tree_sha256,
        "implementation_diff_sha256": envelope.implementation_diff_sha256,
        "authorization_attempt_id": envelope.authorization_attempt_id,
        "phase": phase.value,
        "failed_transition": failed_transition.value,
        "error_code": error_code.value,
        "predecessor_filename": predecessor_filename.value,
        "predecessor_sha256": predecessor_sha256,
        "observed_inventory": [_inventory_value(item) for item in observed_inventory],
    }
    preimage = canonical_json_bytes(["rde.broader.lifecycle.failure-details/v1", details])
    return raw_sha256(preimage)


def build_failure_record(
    envelope: BindingEnvelope,
    *,
    phase: FailurePhase,
    failed_transition: FailedTransition,
    error_code: FailureErrorCode,
    predecessor_filename: LedgerPredecessor,
    predecessor_sha256: str,
    observed_inventory: Sequence[InventoryEntry],
) -> bytes:
    inventory = tuple(observed_inventory)
    details_sha256 = failure_details_sha256(
        envelope=envelope,
        phase=phase,
        failed_transition=failed_transition,
        error_code=error_code,
        predecessor_filename=predecessor_filename,
        predecessor_sha256=predecessor_sha256,
        observed_inventory=inventory,
    )
    return record_bytes(
        FailureRecord(
            envelope=envelope,
            phase=phase,
            failed_transition=failed_transition,
            error_code=error_code,
            predecessor_filename=predecessor_filename,
            predecessor_sha256=predecessor_sha256,
            observed_inventory=inventory,
            details_sha256=details_sha256,
        )
    )


def _parse_envelope(value: Mapping[str, object]) -> BindingEnvelope:
    return BindingEnvelope(
        schema_version=_require_string(value["schema_version"], "schema_version"),
        kind=_require_string(value["kind"], "kind"),
        study_id=_require_string(value["study_id"], "study_id"),
        canonical_target=_require_string(value["canonical_target"], "canonical_target"),
        publication_id=_require_publication_id(value["publication_id"]),
        source_design_checkpoint=_require_string(
            value["source_design_checkpoint"], "source_design_checkpoint"
        ),
        protocol_checkpoint=_require_string(value["protocol_checkpoint"], "protocol_checkpoint"),
        implementation_commit=_require_string(
            value["implementation_commit"], "implementation_commit"
        ),
        implementation_tree_sha256=_require_sha256(
            value["implementation_tree_sha256"], "implementation_tree_sha256"
        ),
        implementation_diff_sha256=_require_sha256(
            value["implementation_diff_sha256"], "implementation_diff_sha256"
        ),
        authorization_attempt_id=_require_authorization_id(
            value["authorization_attempt_id"], "authorization_attempt_id"
        ),
    )


def _parse_artifact(value: object, field: str) -> ArtifactHash:
    item = _require_object(value, field)
    _require_exact_fields(item, frozenset({"order", "filename", "byte_sha256"}))
    order = item["order"]
    if type(order) is not int:
        _fail("FIELD_TYPE", f"{field}.order must be a JSON integer.")
    return ArtifactHash(
        order=order,
        filename=_require_string(item["filename"], f"{field}.filename"),
        byte_sha256=_require_sha256(item["byte_sha256"], f"{field}.byte_sha256"),
    )


def _parse_artifacts(value: object, field: str) -> tuple[ArtifactHash, ...]:
    return tuple(
        _parse_artifact(item, f"{field}[{index}]")
        for index, item in enumerate(_require_array(value, field))
    )


def _parse_inventory(value: object) -> tuple[InventoryEntry, ...]:
    result: list[InventoryEntry] = []
    for index, raw_item in enumerate(_require_array(value, "observed_inventory")):
        field = f"observed_inventory[{index}]"
        item = _require_object(raw_item, field)
        _require_exact_fields(item, frozenset({"namespace", "filename", "byte_sha256"}))
        result.append(
            InventoryEntry(
                namespace=_require_enum(
                    InventoryNamespace, item["namespace"], f"{field}.namespace"
                ),
                filename=_require_string(item["filename"], f"{field}.filename"),
                byte_sha256=_require_sha256(item["byte_sha256"], f"{field}.byte_sha256"),
            )
        )
    return tuple(result)


def _optional_enum[E: StrEnum](enum_type: type[E], value: object, field: str) -> E | None:
    if value is None:
        return None
    return _require_enum(enum_type, value, field)


def _binding_context(envelope: BindingEnvelope) -> tuple[str, ...]:
    return (
        envelope.study_id,
        envelope.canonical_target,
        envelope.publication_id,
        envelope.source_design_checkpoint,
        envelope.protocol_checkpoint,
        envelope.implementation_commit,
        envelope.implementation_tree_sha256,
        envelope.implementation_diff_sha256,
        envelope.authorization_attempt_id,
    )


def validate_record(
    name: str,
    data: bytes,
    expected_envelope: BindingEnvelope | None = None,
    *,
    defer_attempt_retry_semantics: bool = False,
) -> LedgerRecord:
    """Parse one exact selected final and reject every noncanonical or open variant."""

    fields = RECORD_FIELDS.get(name)
    if fields is None:
        _fail("UNKNOWN_RECORD_NAME", f"{name!r} is not a permitted ledger final.")
    try:
        value = parse_canonical_ledger_bytes(data)
    except CanonicalLedgerError as exc:
        raise LifecycleRecordError("MALFORMED_RECORD", str(exc)) from exc
    _require_exact_fields(value, fields)
    envelope = _parse_envelope(value)
    _require_envelope_for(envelope, name)
    if expected_envelope is not None and _binding_context(envelope) != _binding_context(
        expected_envelope
    ):
        _fail("BINDING_MISMATCH", "Record binding envelope differs from the selected attempt.")

    if name == "attempt.json":
        attempt_record = AttemptRecord(
            envelope=envelope,
            intended_artifacts_1_11=_parse_artifacts(
                value["intended_artifacts_1_11"], "intended_artifacts_1_11"
            ),
            retry_kind=_optional_enum(RetryKind, value["retry_kind"], "retry_kind"),
            retry_of_publication_id=_require_optional_publication_id(
                value["retry_of_publication_id"], "retry_of_publication_id"
            ),
            retry_source_canonical_target=_require_optional_string(
                value["retry_source_canonical_target"], "retry_source_canonical_target"
            ),
            retry_source_authorization_attempt_id=_require_optional_authorization_id(
                value["retry_source_authorization_attempt_id"],
                "retry_source_authorization_attempt_id",
            ),
            retry_source_attempt_sha256=_require_optional_sha256(
                value["retry_source_attempt_sha256"], "retry_source_attempt_sha256"
            ),
            retry_source_failure_sha256=_require_optional_sha256(
                value["retry_source_failure_sha256"], "retry_source_failure_sha256"
            ),
            retry_source_terminal_result=_optional_enum(
                RetryTerminalResult,
                value["retry_source_terminal_result"],
                "retry_source_terminal_result",
            ),
            retry_authorization_id=_require_optional_authorization_id(
                value["retry_authorization_id"], "retry_authorization_id"
            ),
        )
        if not defer_attempt_retry_semantics:
            validate_attempt_retry_semantics(attempt_record)
        record: LedgerRecord = attempt_record
    elif name == "M11":
        record = M11Record(
            envelope=envelope,
            attempt_sha256=_require_sha256(value["attempt_sha256"], "attempt_sha256"),
            artifacts_1_11=_parse_artifacts(value["artifacts_1_11"], "artifacts_1_11"),
        )
    elif name == "M12":
        record = M12Record(
            envelope=envelope,
            m11_sha256=_require_sha256(value["m11_sha256"], "m11_sha256"),
            manifest_filename=_require_string(value["manifest_filename"], "manifest_filename"),
            manifest_byte_sha256=_require_sha256(
                value["manifest_byte_sha256"], "manifest_byte_sha256"
            ),
        )
    elif name == "M13":
        record = M13Record(
            envelope=envelope,
            m12_sha256=_require_sha256(value["m12_sha256"], "m12_sha256"),
            recommendation_filename=_require_string(
                value["recommendation_filename"], "recommendation_filename"
            ),
            recommendation_byte_sha256=_require_sha256(
                value["recommendation_byte_sha256"], "recommendation_byte_sha256"
            ),
        )
    elif name == "MF":
        record = MFRecord(
            envelope=envelope,
            m13_sha256=_require_sha256(value["m13_sha256"], "m13_sha256"),
            artifacts_1_13=_parse_artifacts(value["artifacts_1_13"], "artifacts_1_13"),
            graph_validation=_require_string(value["graph_validation"], "graph_validation"),
        )
    else:
        record = FailureRecord(
            envelope=envelope,
            phase=_require_enum(FailurePhase, value["phase"], "phase"),
            failed_transition=_require_enum(
                FailedTransition, value["failed_transition"], "failed_transition"
            ),
            error_code=_require_enum(FailureErrorCode, value["error_code"], "error_code"),
            predecessor_filename=_require_enum(
                LedgerPredecessor, value["predecessor_filename"], "predecessor_filename"
            ),
            predecessor_sha256=_require_sha256(value["predecessor_sha256"], "predecessor_sha256"),
            observed_inventory=_parse_inventory(value["observed_inventory"]),
            details_sha256=_require_sha256(value["details_sha256"], "details_sha256"),
        )
    return record


__all__ = [
    "ARTIFACT_1_11_FILENAMES",
    "ARTIFACT_FILENAMES",
    "AUTHORIZATION_ATTEMPT_ID_PATTERN",
    "ArtifactHash",
    "AttemptRecord",
    "BindingEnvelope",
    "CANONICAL_ARTIFACT_FILENAMES",
    "ENVELOPE_FIELDS",
    "FAILURE_COMPATIBILITY_MATRIX",
    "FAILURE_FIELDS",
    "FailureCompatibilityRule",
    "FailureErrorCode",
    "FailurePhase",
    "FailureRecord",
    "GIT40_PATTERN",
    "InventoryEntry",
    "InventoryNamespace",
    "InventoryVariant",
    "LEDGER_FINAL_NAMES",
    "LEDGER_LIFECYCLE_ORDER",
    "LedgerPredecessor",
    "LedgerRecord",
    "LifecycleRecordError",
    "M11Record",
    "M12Record",
    "M13Record",
    "MFRecord",
    "P0",
    "P1",
    "PRIMARY_TARGET_BASENAME",
    "PROTOCOL_CHECKPOINT",
    "PUBLICATION_ID_PATTERN",
    "RECORD_FIELDS",
    "RECORD_SCHEMA_KIND",
    "RetryKind",
    "RetryTerminalResult",
    "SHA256_PATTERN",
    "SOURCE_DESIGN_CHECKPOINT",
    "STUDY_ID",
    "FailedTransition",
    "build_attempt_record",
    "build_failure_record",
    "build_m11_record",
    "build_m12_record",
    "build_m13_record",
    "build_mf_record",
    "envelope_for_record",
    "failure_details_sha256",
    "make_binding_envelope",
    "record_bytes",
    "record_sha256",
    "record_to_value",
    "validate_attempt_retry_semantics",
    "validate_record",
]
