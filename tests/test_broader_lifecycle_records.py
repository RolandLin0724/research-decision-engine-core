from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest

from research_decision_engine.benchmarks.broader_lifecycle_io import (
    canonical_json_bytes,
    canonical_ledger_bytes,
)
from research_decision_engine.benchmarks.broader_lifecycle_records import (
    ARTIFACT_FILENAMES,
    FAILURE_COMPATIBILITY_MATRIX,
    LEDGER_FINAL_NAMES,
    PROTOCOL_CHECKPOINT,
    SOURCE_DESIGN_CHECKPOINT,
    ArtifactHash,
    AttemptRecord,
    BindingEnvelope,
    FailedTransition,
    FailureErrorCode,
    FailurePhase,
    FailureRecord,
    InventoryEntry,
    InventoryNamespace,
    LedgerPredecessor,
    LifecycleRecordError,
    M11Record,
    M12Record,
    M13Record,
    MFRecord,
    RetryKind,
    RetryTerminalResult,
    build_attempt_record,
    build_failure_record,
    build_m11_record,
    build_m12_record,
    build_m13_record,
    build_mf_record,
    envelope_for_record,
    failure_details_sha256,
    make_binding_envelope,
    record_bytes,
    record_sha256,
    record_to_value,
    validate_record,
)

PUB_A = "publication-" + "a" * 64
PUB_B = "publication-" + "b" * 64
AUTH_A = "authorization-attempt-" + "c" * 64
AUTH_B = "authorization-attempt-" + "d" * 64
TARGET = "/trusted/broader-replication-v1-128-seeds"
RX_TARGET = f"/trusted/broader-replication-v1-128-seeds.retry-{PUB_B}"
GIT = "e" * 40
TREE = "f" * 64
DIFF = "0" * 64


def _envelope(
    name: str,
    *,
    target: str = TARGET,
    publication_id: str = PUB_A,
    authorization_attempt_id: str = AUTH_A,
) -> BindingEnvelope:
    return make_binding_envelope(
        name,
        canonical_target=target,
        publication_id=publication_id,
        implementation_commit=GIT,
        implementation_tree_sha256=TREE,
        implementation_diff_sha256=DIFF,
        authorization_attempt_id=authorization_attempt_id,
    )


def _artifacts(count: int) -> tuple[ArtifactHash, ...]:
    return tuple(
        ArtifactHash(order, filename, f"{order:064x}")
        for order, filename in enumerate(ARTIFACT_FILENAMES[:count], 1)
    )


def _attempt_bytes() -> bytes:
    return build_attempt_record(_envelope("attempt.json"), _artifacts(11))


def _attempt_inventory(attempt_sha256: str) -> tuple[InventoryEntry, ...]:
    return (InventoryEntry(InventoryNamespace.LEDGER, "attempt.json", attempt_sha256),)


@pytest.mark.taskb_ledger
def test_frozen_constants_and_immutable_value_types() -> None:
    assert PROTOCOL_CHECKPOINT == "89c0b4fadba33b9fd9a257b43eacf476b7779d59"
    assert SOURCE_DESIGN_CHECKPOINT == "ebd1591c7332544c8f991a34ef3936f2e048ca16"
    assert {
        "attempt.json",
        "M11",
        "M12",
        "M13",
        "MF",
        "failure.json",
    } == LEDGER_FINAL_NAMES
    artifact = _artifacts(1)[0]
    with pytest.raises(FrozenInstanceError):
        artifact.filename = "changed"  # type: ignore[misc]


@pytest.mark.taskb_ledger
def test_attempt_is_exact_canonical_flat_object() -> None:
    data = _attempt_bytes()
    assert data.endswith(b"\n")
    assert not data.endswith(b"\n\n")
    assert b'"protocol_checkpoint":"89c0b4fadba33b9fd9a257b43eacf476b7779d59"' in data
    assert b'"retry_kind":null' in data
    record = validate_record("attempt.json", data)
    assert isinstance(record, AttemptRecord)
    assert record.envelope.canonical_target == TARGET
    assert record_bytes(record) == data
    assert record_sha256(record) == hashlib.sha256(data).hexdigest()
    assert set(record_to_value(record)) == {
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


@pytest.mark.taskb_ledger
def test_all_marker_schemas_construct_and_validate() -> None:
    attempt_data = _attempt_bytes()
    attempt = validate_record("attempt.json", attempt_data)
    assert isinstance(attempt, AttemptRecord)

    m11_data = build_m11_record(
        envelope_for_record(attempt.envelope, "M11"),
        attempt_sha256=hashlib.sha256(attempt_data).hexdigest(),
        artifacts_1_11=_artifacts(11),
    )
    m11 = validate_record("M11", m11_data, attempt.envelope)
    assert isinstance(m11, M11Record)

    m12_data = build_m12_record(
        envelope_for_record(attempt.envelope, "M12"),
        m11_sha256=record_sha256(m11),
        manifest_byte_sha256="1" * 64,
    )
    m12 = validate_record("M12", m12_data, attempt.envelope)
    assert isinstance(m12, M12Record)
    assert m12.manifest_filename == "run_manifest.json"

    m13_data = build_m13_record(
        envelope_for_record(attempt.envelope, "M13"),
        m12_sha256=record_sha256(m12),
        recommendation_byte_sha256="2" * 64,
    )
    m13 = validate_record("M13", m13_data, attempt.envelope)
    assert isinstance(m13, M13Record)
    assert m13.recommendation_filename == "recommendation.json"

    mf_data = build_mf_record(
        envelope_for_record(attempt.envelope, "MF"),
        m13_sha256=record_sha256(m13),
        artifacts_1_13=_artifacts(13),
    )
    mf = validate_record("MF", mf_data, attempt.envelope)
    assert isinstance(mf, MFRecord)
    assert mf.graph_validation == "PASS"


@pytest.mark.taskb_ledger
@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda value: value.update({"unexpected": "x"}), "UNKNOWN_FIELD"),
        (lambda value: value.pop("authorization_attempt_id"), "MISSING_FIELD"),
        (
            lambda value: value["intended_artifacts_1_11"][0].update({"extra": 1}),
            "UNKNOWN_FIELD",
        ),
        (
            lambda value: value["intended_artifacts_1_11"][0].update({"order": True}),
            "FIELD_TYPE",
        ),
    ],
)
def test_unknown_missing_nested_and_wrong_type_rejection(mutation: object, code: str) -> None:
    value = json.loads(_attempt_bytes())
    assert isinstance(value, dict)
    callable_mutation = mutation
    assert callable(callable_mutation)
    callable_mutation(value)
    with pytest.raises(LifecycleRecordError) as raised:
        validate_record("attempt.json", canonical_ledger_bytes(value))
    assert raised.value.code == code


@pytest.mark.taskb_ledger
def test_noncanonical_duplicate_float_null_and_nonobject_rejection() -> None:
    valid = _attempt_bytes()
    with pytest.raises(LifecycleRecordError, match="canonical"):
        validate_record("attempt.json", b" " + valid)
    duplicate = valid.replace(b'"kind":"ATTEMPT",', b'"kind":"ATTEMPT","kind":"ATTEMPT",', 1)
    with pytest.raises(LifecycleRecordError):
        validate_record("attempt.json", duplicate)
    value = json.loads(valid)
    value["intended_artifacts_1_11"][0]["order"] = 1.0
    with pytest.raises(LifecycleRecordError):
        validate_record("attempt.json", json.dumps(value, separators=(",", ":")).encode() + b"\n")
    m12_value = record_to_value(
        M12Record(_envelope("M12"), "1" * 64, "run_manifest.json", "2" * 64)
    )
    m12_value["manifest_filename"] = None
    with pytest.raises(LifecycleRecordError) as null_error:
        validate_record("M12", canonical_ledger_bytes(m12_value))
    assert null_error.value.code == "FIELD_TYPE"
    with pytest.raises(LifecycleRecordError):
        validate_record("M12", canonical_json_bytes([]) + b"\n")


@pytest.mark.taskb_ledger
def test_selected_attempt_binding_context_is_required() -> None:
    m12_data = build_m12_record(
        _envelope("M12"), m11_sha256="1" * 64, manifest_byte_sha256="2" * 64
    )
    other = _envelope("attempt.json", publication_id=PUB_B, authorization_attempt_id=AUTH_B)
    with pytest.raises(LifecycleRecordError) as raised:
        validate_record("M12", m12_data, other)
    assert raised.value.code == "BINDING_MISMATCH"


@pytest.mark.taskb_ledger
def test_retry_tuple_shapes_and_target_relations() -> None:
    source_attempt_hash = "1" * 64
    source_failure_hash = "2" * 64
    r1 = build_attempt_record(
        _envelope("attempt.json", publication_id=PUB_B, authorization_attempt_id=AUTH_B),
        _artifacts(11),
        retry_kind=RetryKind.R1,
        retry_of_publication_id=PUB_A,
        retry_source_canonical_target=TARGET,
        retry_source_authorization_attempt_id=AUTH_A,
        retry_source_attempt_sha256=source_attempt_hash,
        retry_source_failure_sha256=source_failure_hash,
        retry_source_terminal_result=RetryTerminalResult.ABORTED_BEFORE_PUBLICATION,
        retry_authorization_id=AUTH_B,
    )
    assert isinstance(validate_record("attempt.json", r1), AttemptRecord)

    rx = build_attempt_record(
        _envelope(
            "attempt.json",
            target=RX_TARGET,
            publication_id=PUB_B,
            authorization_attempt_id=AUTH_B,
        ),
        _artifacts(11),
        retry_kind=RetryKind.RX,
        retry_of_publication_id=PUB_A,
        retry_source_canonical_target=TARGET,
        retry_source_authorization_attempt_id=AUTH_A,
        retry_source_attempt_sha256=source_attempt_hash,
        retry_source_failure_sha256=None,
        retry_source_terminal_result=(RetryTerminalResult.PARTIAL_SCIENTIFIC_PUBLICATION_INVALID),
        retry_authorization_id=AUTH_B,
    )
    assert isinstance(validate_record("attempt.json", rx), AttemptRecord)

    with pytest.raises(LifecycleRecordError, match="all-null"):
        build_attempt_record(
            _envelope("attempt.json"),
            _artifacts(11),
            retry_of_publication_id=PUB_B,
        )
    with pytest.raises(LifecycleRecordError, match="source failure"):
        build_attempt_record(
            _envelope("attempt.json", publication_id=PUB_B, authorization_attempt_id=AUTH_B),
            _artifacts(11),
            retry_kind=RetryKind.R1,
            retry_of_publication_id=PUB_A,
            retry_source_canonical_target=TARGET,
            retry_source_authorization_attempt_id=AUTH_A,
            retry_source_attempt_sha256=source_attempt_hash,
            retry_source_failure_sha256=None,
            retry_source_terminal_result=RetryTerminalResult.ABORTED_BEFORE_PUBLICATION,
            retry_authorization_id=AUTH_B,
        )
    with pytest.raises(LifecycleRecordError, match="derived"):
        build_attempt_record(
            _envelope(
                "attempt.json",
                target=f"/trusted/broader-replication-v1-128-seeds.retry-{PUB_A}",
                publication_id=PUB_B,
                authorization_attempt_id=AUTH_B,
            ),
            _artifacts(11),
            retry_kind=RetryKind.RX,
            retry_of_publication_id=PUB_A,
            retry_source_canonical_target=TARGET,
            retry_source_authorization_attempt_id=AUTH_A,
            retry_source_attempt_sha256=source_attempt_hash,
            retry_source_failure_sha256=None,
            retry_source_terminal_result=(RetryTerminalResult.MANIFEST_PUBLISHED_INCOMPLETE),
            retry_authorization_id=AUTH_B,
        )


@pytest.mark.taskb_diagnostic
def test_failure_enums_and_compatibility_matrix_are_closed() -> None:
    assert tuple(phase.value for phase in FailurePhase) == (
        "ATTEMPT",
        "ARTIFACTS_1_11",
        "M11",
        "MANIFEST",
        "M12",
        "RECOMMENDATION",
        "M13",
        "GRAPH_VALIDATION",
        "MF",
        "RECOVERY",
    )
    assert len(tuple(FailureErrorCode)) == 15
    assert len(FAILURE_COMPATIBILITY_MATRIX) == 24
    assert all(rule.allowed_error_codes for rule in FAILURE_COMPATIBILITY_MATRIX)


@pytest.mark.taskb_diagnostic
def test_failure_record_exact_details_hash_and_deterministic_bytes() -> None:
    attempt_data = _attempt_bytes()
    attempt_sha256 = hashlib.sha256(attempt_data).hexdigest()
    envelope = _envelope("failure.json")
    inventory = _attempt_inventory(attempt_sha256)
    first = build_failure_record(
        envelope,
        phase=FailurePhase.ATTEMPT,
        failed_transition=FailedTransition.INSTALL_ATTEMPT,
        error_code=FailureErrorCode.IO_DIRECTORY_FSYNC,
        predecessor_filename=LedgerPredecessor.ATTEMPT,
        predecessor_sha256=attempt_sha256,
        observed_inventory=inventory,
    )
    second = build_failure_record(
        envelope,
        phase=FailurePhase.ATTEMPT,
        failed_transition=FailedTransition.INSTALL_ATTEMPT,
        error_code=FailureErrorCode.IO_DIRECTORY_FSYNC,
        predecessor_filename=LedgerPredecessor.ATTEMPT,
        predecessor_sha256=attempt_sha256,
        observed_inventory=inventory,
    )
    assert first == second
    record = validate_record("failure.json", first, _envelope("attempt.json"))
    assert isinstance(record, FailureRecord)
    details = {
        "study_id": envelope.study_id,
        "canonical_target": envelope.canonical_target,
        "publication_id": envelope.publication_id,
        "source_design_checkpoint": envelope.source_design_checkpoint,
        "protocol_checkpoint": envelope.protocol_checkpoint,
        "implementation_commit": envelope.implementation_commit,
        "implementation_tree_sha256": envelope.implementation_tree_sha256,
        "implementation_diff_sha256": envelope.implementation_diff_sha256,
        "authorization_attempt_id": envelope.authorization_attempt_id,
        "phase": "ATTEMPT",
        "failed_transition": "INSTALL_ATTEMPT",
        "error_code": "IO_DIRECTORY_FSYNC",
        "predecessor_filename": "attempt.json",
        "predecessor_sha256": attempt_sha256,
        "observed_inventory": [
            {
                "namespace": "ledger",
                "filename": "attempt.json",
                "byte_sha256": attempt_sha256,
            }
        ],
    }
    independent_preimage = json.dumps(
        ["rde.broader.lifecycle.failure-details/v1", details],
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    expected = hashlib.sha256(independent_preimage).hexdigest()
    assert record.details_sha256 == expected
    assert record.details_sha256 == failure_details_sha256(
        envelope=envelope,
        phase=record.phase,
        failed_transition=record.failed_transition,
        error_code=record.error_code,
        predecessor_filename=record.predecessor_filename,
        predecessor_sha256=record.predecessor_sha256,
        observed_inventory=record.observed_inventory,
    )


@pytest.mark.taskb_diagnostic
def test_failure_compatibility_inventory_predecessor_and_details_fail_closed() -> None:
    attempt_sha256 = hashlib.sha256(_attempt_bytes()).hexdigest()
    envelope = _envelope("failure.json")
    inventory = _attempt_inventory(attempt_sha256)
    with pytest.raises(LifecycleRecordError) as incompatible:
        build_failure_record(
            envelope,
            phase=FailurePhase.ATTEMPT,
            failed_transition=FailedTransition.INSTALL_ATTEMPT,
            error_code=FailureErrorCode.IO_STAGE_WRITE,
            predecessor_filename=LedgerPredecessor.ATTEMPT,
            predecessor_sha256=attempt_sha256,
            observed_inventory=inventory,
        )
    assert incompatible.value.code == "FAILURE_COMPATIBILITY"

    with pytest.raises(LifecycleRecordError, match="hash"):
        build_failure_record(
            envelope,
            phase=FailurePhase.ATTEMPT,
            failed_transition=FailedTransition.INSTALL_ATTEMPT,
            error_code=FailureErrorCode.IO_DIRECTORY_FSYNC,
            predecessor_filename=LedgerPredecessor.ATTEMPT,
            predecessor_sha256="9" * 64,
            observed_inventory=inventory,
        )

    valid = build_failure_record(
        envelope,
        phase=FailurePhase.ATTEMPT,
        failed_transition=FailedTransition.INSTALL_ATTEMPT,
        error_code=FailureErrorCode.IO_DIRECTORY_FSYNC,
        predecessor_filename=LedgerPredecessor.ATTEMPT,
        predecessor_sha256=attempt_sha256,
        observed_inventory=inventory,
    )
    value = json.loads(valid)
    value["details_sha256"] = "9" * 64
    with pytest.raises(LifecycleRecordError) as bad_details:
        validate_record("failure.json", canonical_ledger_bytes(value))
    assert bad_details.value.code == "DETAILS_HASH"


@pytest.mark.taskb_diagnostic
def test_recovery_failure_requires_exact_recovered_prefix_transition() -> None:
    attempt_sha256 = hashlib.sha256(_attempt_bytes()).hexdigest()
    inventory = _attempt_inventory(attempt_sha256)
    data = build_failure_record(
        _envelope("failure.json"),
        phase=FailurePhase.RECOVERY,
        failed_transition=FailedTransition.ATTEMPT_TO_ARTIFACTS_1_11,
        error_code=FailureErrorCode.RECOVERY_ABANDONED,
        predecessor_filename=LedgerPredecessor.ATTEMPT,
        predecessor_sha256=attempt_sha256,
        observed_inventory=inventory,
    )
    assert isinstance(validate_record("failure.json", data), FailureRecord)
    with pytest.raises(LifecycleRecordError) as raised:
        build_failure_record(
            _envelope("failure.json"),
            phase=FailurePhase.RECOVERY,
            failed_transition=FailedTransition.M11_TO_MANIFEST,
            error_code=FailureErrorCode.RECOVERY_ABANDONED,
            predecessor_filename=LedgerPredecessor.ATTEMPT,
            predecessor_sha256=attempt_sha256,
            observed_inventory=inventory,
        )
    assert raised.value.code == "FAILURE_COMPATIBILITY"
