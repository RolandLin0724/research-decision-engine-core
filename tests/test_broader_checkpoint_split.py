from __future__ import annotations

import ast
import csv
import hashlib
import inspect
import io
import json
import re
import shutil
import subprocess
import textwrap

import pytest

import research_decision_engine.benchmarks.broader_artifact_graph as artifact_graph_module
import research_decision_engine.benchmarks.broader_assembly as broader_assembly
import research_decision_engine.benchmarks.broader_execution as broader_execution
import research_decision_engine.benchmarks.broader_lifecycle as broader_lifecycle
import research_decision_engine.benchmarks.broader_oracle as broader_oracle
import research_decision_engine.benchmarks.broader_validation as broader_validation
from research_decision_engine.benchmarks.broader_artifact_graph import (
    FROZEN_ARTIFACT_PROFILE,
    CanonicalArtifactGraph,
)
from research_decision_engine.benchmarks.broader_artifacts import (
    ArtifactValidationError,
    artifact_contracts,
    build_protocol_snapshot_payload,
    build_world_definitions_payload,
    serialize_csv_artifact,
    serialize_json_artifact,
    serialize_jsonl_artifact,
)
from research_decision_engine.benchmarks.broader_audits import PROTECTED_HASHES
from research_decision_engine.benchmarks.broader_protocol import (
    PROTOCOL_CHECKPOINT,
    PUBLIC_PROVENANCE_ROLE_TOKEN_NAMESPACE,
    PUBLIC_PROVENANCE_ROLE_TOKEN_SCHEMA,
    SOURCE_CHECKPOINT,
    SOURCE_DESIGN_CHECKPOINT,
    _public_provenance_role_token,
    canonical_json_bytes,
    design_path,
    load_protocol_snapshot,
    repository_root,
)
from research_decision_engine.benchmarks.broader_validation_evidence import (
    EVIDENCE_CONTRACT_CHECKPOINT,
)


@pytest.mark.taskb_checkpoint
def test_protocol_and_source_design_checkpoints_are_distinct_and_frozen() -> None:
    assert SOURCE_DESIGN_CHECKPOINT == "ebd1591c7332544c8f991a34ef3936f2e048ca16"
    assert SOURCE_CHECKPOINT == SOURCE_DESIGN_CHECKPOINT
    assert PROTOCOL_CHECKPOINT == "89c0b4fadba33b9fd9a257b43eacf476b7779d59"
    assert EVIDENCE_CONTRACT_CHECKPOINT == "cbeea072ed39697e2cd42ca571685faed5f6ead8"
    assert PUBLIC_PROVENANCE_ROLE_TOKEN_SCHEMA == "rde-core-public-provenance-role-token/v1"
    assert PUBLIC_PROVENANCE_ROLE_TOKEN_NAMESPACE == "RDE_CORE_PUBLIC_PROVENANCE_ROLE_V1"

    expected_tokens = {
        "EVIDENCE_CONTRACT": EVIDENCE_CONTRACT_CHECKPOINT,
        "PROTOCOL": PROTOCOL_CHECKPOINT,
        "SOURCE_DESIGN": SOURCE_DESIGN_CHECKPOINT,
    }
    assert {
        role: _public_provenance_role_token(role) for role in expected_tokens
    } == expected_tokens
    assert len(set(expected_tokens.values())) == 3
    assert all(re.fullmatch(r"[0-9a-f]{40}", token) for token in expected_tokens.values())

    git = shutil.which("git")
    assert git is not None
    inventory = subprocess.run(
        [git, "cat-file", "--batch-check=%(objectname)", "--batch-all-objects"],
        cwd=repository_root(),
        check=True,
        capture_output=True,
        text=True,
        encoding="ascii",
    ).stdout.splitlines()
    object_ids = set(inventory)
    assert object_ids
    assert set(expected_tokens.values()).isdisjoint(object_ids)

    consumers = (
        (broader_assembly._reconstruct_actual_finalization_state, "implementation_commit"),
        (broader_execution._current_execution_environment, "implementation_commit"),
        (broader_lifecycle.reconstruct_implementation_identity, "commit"),
        (broader_oracle._current_oracle_identities, "implementation_commit"),
        (broader_validation._current_validation_identities, "implementation_commit"),
    )
    forbidden_names = {
        "EVIDENCE_CONTRACT_CHECKPOINT",
        "PROTOCOL_CHECKPOINT",
        "SOURCE_CHECKPOINT",
        "SOURCE_DESIGN_CHECKPOINT",
    }
    git_helpers = {
        "_git_blob_bytes",
        "_git_bytes",
        "_git_text",
        "_git_tree",
        "_head_tree_rows",
        "_implementation_diff_identity",
    }
    for consumer, captured_name in consumers:
        tree = ast.parse(textwrap.dedent(inspect.getsource(consumer)))
        captured_from_head = False
        captured_used_for_git_read = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = node.value
                if value is None:
                    continue
                if any(
                    isinstance(target, ast.Name) and target.id == captured_name
                    for target in targets
                ):
                    constants = {
                        part.value
                        for part in ast.walk(value)
                        if isinstance(part, ast.Constant) and isinstance(part.value, str)
                    }
                    captured_from_head |= {"rev-parse", "--verify", "HEAD^{commit}"} <= constants
            if not isinstance(node, ast.Call):
                continue
            helper = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            if helper not in git_helpers:
                continue
            call_nodes = tuple(ast.walk(node))
            call_names = {part.id for part in call_nodes if isinstance(part, ast.Name)}
            call_strings = {
                part.value
                for part in call_nodes
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            }
            assert forbidden_names.isdisjoint(call_names)
            assert set(expected_tokens.values()).isdisjoint(call_strings)
            captured_used_for_git_read |= captured_name in call_names
        assert captured_from_head
        assert captured_used_for_git_read


@pytest.mark.taskb_checkpoint
def test_all_amended_artifact_serializers_emit_p1() -> None:
    source_design_sha256 = "0" * 64
    json_bytes = serialize_json_artifact(
        schema_version="checkpoint-test/v1",
        source_design_sha256=source_design_sha256,
        scientific_fields={"value": "json"},
    )
    jsonl_bytes = serialize_jsonl_artifact(
        schema_version="checkpoint-test/v1",
        source_design_sha256=source_design_sha256,
        rows=({"value": "jsonl"},),
    )
    csv_bytes = serialize_csv_artifact(
        schema_version="checkpoint-test/v1",
        source_design_sha256=source_design_sha256,
        rows=({},),
    )

    assert json.loads(json_bytes)["source_checkpoint_identifier"] == PROTOCOL_CHECKPOINT
    assert (
        json.loads(jsonl_bytes.splitlines()[0])["source_checkpoint_identifier"]
        == PROTOCOL_CHECKPOINT
    )
    csv_row = next(csv.DictReader(io.StringIO(csv_bytes.decode("utf-8"), newline="")))
    assert csv_row["source_checkpoint_identifier"] == PROTOCOL_CHECKPOINT


@pytest.mark.taskb_checkpoint
def test_decoder_defaults_to_p1_and_accepts_only_trusted_historical_p0() -> None:
    snapshot = load_protocol_snapshot()
    contract = artifact_contracts()[1]
    amended = serialize_json_artifact(
        schema_version=contract.schema_version,
        source_design_sha256=snapshot.source_design_sha256,
        scientific_fields=build_world_definitions_payload(),
    )

    artifact_graph_module._decode_artifact(
        contract,
        amended,
        expected_checkpoint=PROTOCOL_CHECKPOINT,
    )
    with pytest.raises(ArtifactValidationError, match="checkpoint differs"):
        artifact_graph_module._decode_artifact(
            contract,
            amended,
            expected_checkpoint=SOURCE_DESIGN_CHECKPOINT,
        )

    historical_document = json.loads(amended)
    historical_document["source_checkpoint_identifier"] = SOURCE_DESIGN_CHECKPOINT
    historical = canonical_json_bytes(
        historical_document,
        final_lf=True,
    )
    artifact_graph_module._decode_artifact(
        contract,
        historical,
        expected_checkpoint=SOURCE_DESIGN_CHECKPOINT,
    )
    with pytest.raises(ArtifactValidationError, match="checkpoint differs"):
        artifact_graph_module._decode_artifact(
            contract,
            historical,
            expected_checkpoint=PROTOCOL_CHECKPOINT,
        )
    with pytest.raises(ArtifactValidationError, match="not trusted"):
        artifact_graph_module._decode_artifact(
            contract,
            amended,
            expected_checkpoint="0" * 40,
        )


@pytest.mark.taskb_checkpoint
def test_protocol_snapshot_keeps_original_design_commit_under_p1_metadata() -> None:
    snapshot = load_protocol_snapshot()
    contract = artifact_contracts()[0]
    design_bytes = design_path().read_bytes()
    design_blob_oid = hashlib.sha1(
        f"blob {len(design_bytes)}\0".encode("ascii") + design_bytes,
        usedforsecurity=False,
    ).hexdigest()
    content = serialize_json_artifact(
        schema_version=contract.schema_version,
        source_design_sha256=snapshot.source_design_sha256,
        scientific_fields=build_protocol_snapshot_payload(snapshot),
        operational_fields={
            "design_checkpoint_commit": SOURCE_DESIGN_CHECKPOINT,
            "design_git_blob_oid": design_blob_oid,
            "protected_source_sha256": dict(PROTECTED_HASHES),
        },
    )
    decoded = artifact_graph_module._decode_artifact(
        contract,
        content,
        expected_checkpoint=PROTOCOL_CHECKPOINT,
    )
    graph = CanonicalArtifactGraph(
        (decoded,),
        FROZEN_ARTIFACT_PROFILE,
        PROTOCOL_CHECKPOINT,
    )

    artifact_graph_module._validate_protocol_snapshot(graph, snapshot)
    assert decoded.operational["design_checkpoint_commit"] == SOURCE_DESIGN_CHECKPOINT
