"""Acyclic assembly of the 13 frozen canonical artifacts."""

from __future__ import annotations

import csv
import ctypes
import errno
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from research_decision_engine.benchmarks.broader_artifact_graph import (
    FROZEN_ARTIFACT_PROFILE,
    TS_PATTERN,
    ArtifactCardinalityProfile,
    CanonicalArtifactGraph,
    decode_and_validate_artifacts,
    decode_and_validate_audited_artifacts,
    decode_and_validate_manifest_artifacts,
    decode_and_validate_prefinal_artifacts,
)
from research_decision_engine.benchmarks.broader_artifacts import (
    ArtifactContract,
    ArtifactValidationError,
    RecordContract,
    TaggedRecordContract,
    artifact_contracts,
    serialize_csv_artifact,
    serialize_json_artifact,
    serialize_jsonl_artifact,
)
from research_decision_engine.benchmarks.broader_audits import (
    FINALIZATION_AUTHORIZATION_VERSION,
    PROTECTED_HASHES,
    ConsumedFinalizationAuthorization,
    FinalizationAuditCertificate,
    FinalizationAuthorization,
    IntegrityAuditResult,
    advance_finalization_receipt,
    claim_finalization_receipt_writer,
    claimed_finalization_receipt_binding,
    complete_finalization_receipt,
    consume_finalization_authorization,
    finalization_audit_results,
    finalization_plan_binding_sha256,
    finalization_receipt_audit_results,
    finalization_receipt_binding,
    historical_hash_map,
    invalidate_finalization_receipt,
    invalidate_unconsumed_finalization_authorization,
    publish_finalization_receipt_writer,
    seal_finalization_authorization,
)
from research_decision_engine.benchmarks.broader_execution import (
    ActualExecutorAttestation,
    ExecutionPurpose,
    ExecutorTrustDomain,
    _IssuedAttestation,
    _require_issued_result_batch,
    executor_attestation_payload,
    executor_provenance_payload,
    validate_executor_attestation,
)
from research_decision_engine.benchmarks.broader_projection import (
    PostAuditScientificPayloads,
    _require_issued_post_audit_payloads,
    _require_issued_prefinalization_payloads,
    derive_manifest_scientific_payload,
    derive_recommendation_scientific_payload,
    merged_scientific_claims,
    recommendation_scientific_payload_identity,
)
from research_decision_engine.benchmarks.broader_protocol import (
    PROTOCOL_CHECKPOINT,
    PUBLIC_PROVENANCE_ROLE_TOKENS,
    SOURCE_CHECKPOINT,
    canonical_json_bytes,
    load_protocol_snapshot,
    protocol_hash,
    repository_root,
)


@dataclass(frozen=True, slots=True)
class AssemblyOperationalProvenance:
    protocol: Mapping[str, object]
    historical_before_sha256: Mapping[str, str]
    historical_after_sha256: Mapping[str, str]
    implementation_commit: str
    implementation_tree_sha256: str
    implementation_diff_sha256: str
    implementation_tree_clean: bool
    started_at: str
    completed_at: str
    dependency_versions: Mapping[str, str]
    machine: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class _IssuedOperationalProvenance:
    operational: AssemblyOperationalProvenance
    canonical_bytes: bytes
    sha256: str
    executor_attestation: ActualExecutorAttestation
    execution: _IssuedAttestation
    consumed_results: tuple[object, ...]
    execution_authority: object | None
    execution_purpose: ExecutionPurpose


@dataclass(frozen=True, slots=True)
class _IssuedLifecycleArtifacts:
    artifacts: Mapping[str, bytes]
    execution: _IssuedAttestation
    artifact_sha256: tuple[tuple[str, str], ...]


_ISSUED_OPERATIONAL_PROVENANCE: dict[int, _IssuedOperationalProvenance] = {}
_ISSUED_LIFECYCLE_ARTIFACTS: dict[int, _IssuedLifecycleArtifacts] = {}
_FINALIZATION_BINDING_ATTESTATION_KEY = object()
CANONICAL_OUTPUT_DIRECTORY = "broader-replication-v1-128-seeds"
CANONICAL_FINALIZATION_SCOPE = "canonical"
VALIDATION_FINALIZATION_SCOPE = "validation_only"
CANONICAL_CREATE_ONCE_ERROR = "CANONICAL_CREATE_ONCE"
SUPERSEDED_CANONICAL_FINALIZATION_ERROR = (
    "Canonical publication must use the superseding attempt-ledger lifecycle coordinator."
)


class CanonicalCreateOnceError(ArtifactValidationError):
    """Raised when atomic exclusive publication observes an existing destination."""

    error_code = CANONICAL_CREATE_ONCE_ERROR


_FINALIZATION_BINDING_FIELDS = frozenset(
    {
        "authorization_version",
        "finalization_scope",
        "lifecycle_phase",
        "canonical_output_directory",
        "artifact_contract_registry_sha256",
        "artifact_cardinality_profile",
        "design_checkpoint",
        "source_design_sha256",
        "source_checkpoint_identity",
        "implementation_tree_sha256",
        "implementation_diff_sha256",
        "operational_provenance_sha256",
        "operational_provenance",
        "actual_finalization_state",
        "study_identity",
        "ordered_run_identity_sha256",
        "scientific_payload_sha256",
        "artifact_content_sha256",
        "audit_certificate_plan_sha256",
        "g_integrity",
        "provisional_decision",
    }
)


class _FinalizationBindingAttestation:
    """Identity-only proof that assembly completed every pre-seal check."""

    __slots__ = ()

    def __new__(
        cls,
        construction_key: object | None = None,
    ) -> _FinalizationBindingAttestation:
        if construction_key is not _FINALIZATION_BINDING_ATTESTATION_KEY:
            raise TypeError("Finalization binding attestations are issued only by assembly.")
        return super().__new__(cls)

    def __copy__(self) -> None:
        raise TypeError("Finalization binding attestations cannot be copied.")

    def __deepcopy__(self, memo: object) -> None:
        del memo
        raise TypeError("Finalization binding attestations cannot be deep-copied.")


_ISSUED_FINALIZATION_BINDING_ATTESTATIONS: dict[_FinalizationBindingAttestation, bytes] = {}


def reconstruct_actual_operational_provenance(
    executor_attestation: ActualExecutorAttestation,
    *,
    consumed_results: Sequence[object],
    execution_authority: object | None = None,
    execution_purpose: ExecutionPurpose,
) -> AssemblyOperationalProvenance:
    """Construct manifest provenance from the repository and running interpreter."""

    attestation_payload = executor_attestation_payload(executor_attestation)
    validate_executor_attestation(
        executor_attestation,
        results=consumed_results,
        execution_authority=execution_authority,
        expected_purpose=execution_purpose,
        require_trust_domain=cast(ExecutorTrustDomain, attestation_payload["trust_domain"]),
    )
    execution = _require_issued_result_batch(
        consumed_results,
        expected_purposes=(execution_purpose,),
        require_trust_domain=cast(ExecutorTrustDomain, attestation_payload["trust_domain"]),
    )
    if execution.attestation is not executor_attestation or execution.authority is not (
        execution_authority
    ):
        raise ArtifactValidationError(
            "Operational provenance belongs to another exact executor result batch."
        )
    started_at = cast(str, attestation_payload["execution_started_at"])
    actual = _reconstruct_actual_finalization_state(
        executor_attestation=executor_attestation,
    )
    _require_executor_matches_actual_state(attestation_payload, actual)
    completed_at = cast(str, attestation_payload["execution_completed_at"])
    operational = AssemblyOperationalProvenance(
        protocol=cast(Mapping[str, object], actual["protocol"]),
        historical_before_sha256=cast(Mapping[str, str], actual["historical_source_sha256"]),
        historical_after_sha256=cast(Mapping[str, str], actual["historical_source_sha256"]),
        implementation_commit=cast(str, actual["implementation_commit"]),
        implementation_tree_sha256=cast(str, actual["implementation_tree_sha256"]),
        implementation_diff_sha256=cast(str, actual["implementation_diff_sha256"]),
        implementation_tree_clean=cast(bool, actual["implementation_tree_clean"]),
        started_at=started_at,
        completed_at=completed_at,
        dependency_versions=cast(Mapping[str, str], actual["dependency_versions"]),
        machine=cast(Mapping[str, str], actual["machine"]),
    )
    canonical_bytes = _operational_provenance_bytes(operational)
    _ISSUED_OPERATIONAL_PROVENANCE[id(operational)] = _IssuedOperationalProvenance(
        operational=operational,
        canonical_bytes=canonical_bytes,
        sha256=hashlib.sha256(canonical_bytes).hexdigest(),
        executor_attestation=executor_attestation,
        execution=execution,
        consumed_results=execution.returned_results,
        execution_authority=execution_authority,
        execution_purpose=execution_purpose,
    )
    return operational


def _require_executor_matches_actual_state(
    attestation: Mapping[str, object],
    actual: Mapping[str, object],
) -> None:
    """Reject provenance reconstructed from a checkout other than the execution checkout."""

    expected = {
        "implementation_commit": attestation["implementation_commit"],
        "implementation_tree_sha256": attestation["implementation_tree_sha256"],
        "implementation_diff_sha256": attestation["implementation_diff_sha256"],
        "dependency_lock_sha256": attestation["dependency_lock_sha256"],
    }
    if any(actual.get(field) != value for field, value in expected.items()):
        raise ArtifactValidationError(
            "Operational provenance checkout differs from the exact executor implementation."
        )
    machine = actual.get("machine")
    if (
        attestation.get("protocol_checkpoint") != PROTOCOL_CHECKPOINT
        or not isinstance(machine, Mapping)
        or machine.get("executor_runtime_identity") != attestation.get("runtime_identity")
        or machine.get("executor_implementation_identity")
        != attestation.get("executor_implementation_identity")
    ):
        raise ArtifactValidationError(
            "Operational provenance protocol or runtime differs from the exact executor."
        )


def _reconstruct_actual_finalization_state(
    canonical_target: Path | None = None,
    *,
    transient_paths: Sequence[Path] = (),
    authorized_output_directory: bool = False,
    executor_attestation: ActualExecutorAttestation,
) -> dict[str, object]:
    """Authoritatively reconstruct Git, source, dependency, and runtime identity."""

    root = repository_root().resolve(strict=True)
    git = _resolve_git_executable()
    top_level = Path(_git_text(git, root, "rev-parse", "--show-toplevel")).resolve(strict=True)
    if top_level != root:
        raise ArtifactValidationError("Git repository root differs from the implementation root.")

    implementation_commit = _git_text(git, root, "rev-parse", "--verify", "HEAD^{commit}")
    if (
        re.fullmatch(r"[0-9a-f]{40}", implementation_commit) is None
        or implementation_commit in PUBLIC_PROVENANCE_ROLE_TOKENS
    ):
        raise ArtifactValidationError("Actual implementation commit is not GIT40.")
    checkpoint_tree = _git_tree(git, root, implementation_commit)
    working_tree = _working_implementation_tree(git, root)
    implementation_tree_sha256 = _implementation_tree_identity(working_tree)
    implementation_diff_sha256 = _implementation_diff_identity(
        git,
        root,
        checkpoint_tree,
        working_tree,
        source_checkpoint=implementation_commit,
    )

    excluded_paths = (
        (canonical_target,) if canonical_target is not None and authorized_output_directory else ()
    ) + tuple(transient_paths)
    exclusions: list[str] = []
    for excluded_path in excluded_paths:
        resolved_target = excluded_path.resolve(strict=False)
        try:
            relative_target = resolved_target.relative_to(root).as_posix()
        except ValueError:
            continue
        else:
            exclusions.extend((f":(exclude){relative_target}", f":(exclude){relative_target}/**"))
    status_arguments = ["status", "--porcelain=v1", "-z", "--untracked-files=all"]
    if exclusions:
        status_arguments.extend(("--", ".", *exclusions))
    status = _git_bytes(git, root, *status_arguments)
    implementation_worktree_sha256 = _worktree_identity(root, status)

    design_oid = _git_text(
        git,
        root,
        "rev-parse",
        f"{implementation_commit}:BROADER_REPLICATION_DESIGN.md",
    )
    design_bytes = (root / "BROADER_REPLICATION_DESIGN.md").read_bytes()
    checkpoint_design = _git_blob_bytes(git, root, design_oid)
    source_design_sha256 = hashlib.sha256(design_bytes).hexdigest()
    protected = {
        relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for relative in sorted(PROTECTED_HASHES, key=lambda item: item.encode("utf-8"))
    }
    dependency_lock_sha256 = hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest()
    historical = dict(historical_hash_map(root))
    git_version = _git_text(git, root, "--version")
    machine = _actual_runtime_machine(executor_attestation)
    dependency_versions = {
        "git": git_version,
        "python": platform.python_version(),
        "uv_lock_sha256": dependency_lock_sha256,
    }
    protocol = {
        "design_checkpoint_commit": SOURCE_CHECKPOINT,
        "design_git_blob_oid": design_oid,
        "protected_source_sha256": protected,
    }
    return {
        "repository_root": root.as_posix(),
        "normalized_output_directory": (
            _normalized_output_directory(canonical_target)
            if canonical_target is not None
            else "none"
        ),
        "implementation_commit": implementation_commit,
        "implementation_tree_sha256": implementation_tree_sha256,
        "implementation_diff_sha256": implementation_diff_sha256,
        "implementation_tree_clean": status == b"",
        "implementation_worktree_sha256": implementation_worktree_sha256,
        "design_checkpoint_commit": SOURCE_CHECKPOINT,
        "design_git_blob_oid": design_oid,
        "design_matches_checkpoint": design_bytes == checkpoint_design,
        "source_design_sha256": source_design_sha256,
        "protected_source_sha256": protected,
        "protected_source_matches": protected == dict(PROTECTED_HASHES),
        "dependency_lock_sha256": dependency_lock_sha256,
        "historical_source_sha256": historical,
        "dependency_versions": dependency_versions,
        "machine": machine,
        "protocol": protocol,
        "git_executable": git.resolve(strict=True).as_posix(),
    }


def _actual_runtime_machine(
    executor_attestation: ActualExecutorAttestation,
) -> dict[str, str]:
    """Derive interpreter, platform, and actual executor identity without caller claims."""

    executable = Path(sys.executable).resolve(strict=True)
    build_number, build_date = platform.python_build()
    machine = {
        "architecture": platform.machine(),
        "platform": platform.platform(),
        "python_build_date": build_date,
        "python_build_number": build_number,
        "python_cache_tag": sys.implementation.cache_tag or "none",
        "python_compiler": platform.python_compiler(),
        "python_executable": executable.as_posix(),
        "python_executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "system": platform.system(),
    }
    machine.update(executor_provenance_payload(executor_attestation))
    return machine


def _resolve_git_executable() -> Path:
    discovered = shutil.which("git")
    candidates = [Path(discovered)] if discovered is not None else []
    if os.name == "nt":
        for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(variable)
            if base is None:
                continue
            root = Path(base)
            candidates.extend(
                (
                    root / "Git" / "cmd" / "git.exe",
                    root / "Programs" / "Git" / "cmd" / "git.exe",
                )
            )
        runtime_root = Path.home() / ".cache" / "codex-runtimes"
        if runtime_root.is_dir():
            candidates.extend(sorted(runtime_root.glob("*/dependencies/native/git/cmd/git.exe")))
    else:
        candidates.extend((Path("/usr/bin/git"), Path("/usr/local/bin/git")))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve(strict=True)
    raise ArtifactValidationError("Git executable is unavailable for actual-state reconstruction.")


def _git_bytes(git: Path, root: Path, *arguments: str, input_bytes: bytes | None = None) -> bytes:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    completed = subprocess.run(
        [os.fspath(git), "-c", "core.quotepath=false", "-C", os.fspath(root), *arguments],
        check=False,
        input=input_bytes,
        capture_output=True,
        env=environment,
        timeout=30,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ArtifactValidationError(f"Git actual-state reconstruction failed: {detail}")
    return completed.stdout


def _git_text(git: Path, root: Path, *arguments: str) -> str:
    return _git_bytes(git, root, *arguments).decode("utf-8").strip()


def _git_tree(git: Path, root: Path, revision: str) -> dict[str, tuple[str, bytes]]:
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None or revision in PUBLIC_PROVENANCE_ROLE_TOKENS:
        raise ArtifactValidationError("Git tree revision is not a captured implementation commit.")
    output = _git_bytes(git, root, "ls-tree", "-r", "-z", "--full-tree", revision)
    entries: list[tuple[str, str, str]] = []
    for raw in output.split(b"\0"):
        if not raw:
            continue
        metadata, encoded_path = raw.split(b"\t", 1)
        mode, object_type, oid = metadata.decode("ascii").split(" ", 2)
        path = encoded_path.decode("utf-8")
        if object_type != "blob" or not _implementation_path(path):
            continue
        entries.append((path, mode, oid))
    blobs = _git_blob_map(git, root, tuple(oid for _, _, oid in entries))
    return {path: (mode, blobs[oid]) for path, mode, oid in entries}


def _git_blob_map(git: Path, root: Path, oids: tuple[str, ...]) -> dict[str, bytes]:
    if not oids:
        return {}
    output = _git_bytes(
        git,
        root,
        "cat-file",
        "--batch",
        input_bytes=("\n".join(oids) + "\n").encode("ascii"),
    )
    position = 0
    blobs: dict[str, bytes] = {}
    for expected_oid in oids:
        line_end = output.index(b"\n", position)
        header = output[position:line_end].decode("ascii")
        oid, object_type, encoded_size = header.split(" ", 2)
        if oid != expected_oid or object_type != "blob":
            raise ArtifactValidationError("Git cat-file returned an unexpected object.")
        size = int(encoded_size)
        start = line_end + 1
        end = start + size
        blobs[oid] = output[start:end]
        if output[end : end + 1] != b"\n":
            raise ArtifactValidationError("Git cat-file output is malformed.")
        position = end + 1
    if position != len(output):
        raise ArtifactValidationError("Git cat-file returned trailing output.")
    return blobs


def _git_blob_bytes(git: Path, root: Path, oid: str) -> bytes:
    return _git_blob_map(git, root, (oid,))[oid]


def _implementation_path(path: str) -> bool:
    return path in {"pyproject.toml", "uv.lock"} or (
        path.endswith(".py")
        and (path.startswith("research_decision_engine/") or path.startswith("tests/"))
    )


def _implementation_tree_identity(tree: Mapping[str, tuple[str, bytes]]) -> str:
    rows = (
        {
            "path": path,
            "git_mode": tree[path][0],
            "byte_length": len(tree[path][1]),
            "file_sha256": hashlib.sha256(tree[path][1]).hexdigest(),
        }
        for path in sorted(
            (item for item in tree if _implementation_path(item)),
            key=lambda item: item.encode("utf-8"),
        )
    )
    payload = b"".join(canonical_json_bytes(row, final_lf=True) for row in rows)
    return hashlib.sha256(payload).hexdigest()


def _working_implementation_tree(git: Path, root: Path) -> dict[str, tuple[str, bytes]]:
    stage_output = _git_bytes(
        git,
        root,
        "ls-files",
        "--stage",
        "-z",
        "--",
        "pyproject.toml",
        "uv.lock",
        "research_decision_engine",
        "tests",
    )
    modes: dict[str, str] = {}
    for raw in stage_output.split(b"\0"):
        if not raw:
            continue
        metadata, encoded_path = raw.split(b"\t", 1)
        mode, _, stage = metadata.decode("ascii").split(" ", 2)
        if stage == "0":
            modes[encoded_path.decode("utf-8")] = mode
    paths_output = _git_bytes(
        git,
        root,
        "ls-files",
        "-z",
        "--cached",
        "--",
        "pyproject.toml",
        "uv.lock",
        "research_decision_engine",
        "tests",
    )
    tree: dict[str, tuple[str, bytes]] = {}
    for encoded_path in paths_output.split(b"\0"):
        if not encoded_path:
            continue
        relative = encoded_path.decode("utf-8")
        if not _implementation_path(relative):
            continue
        path = root / relative
        if path.is_symlink():
            content = os.readlink(path).encode("utf-8")
            mode = modes.get(relative, "120000")
        elif path.is_file():
            content = path.read_bytes()
            default_mode = (
                "100755" if os.name != "nt" and bool(path.stat().st_mode & 0o111) else "100644"
            )
            mode = modes.get(relative, default_mode)
        else:
            continue
        tree[relative] = (mode, content)
    return tree


def _implementation_diff_identity(
    git: Path,
    root: Path,
    old_tree: Mapping[str, tuple[str, bytes]],
    new_tree: Mapping[str, tuple[str, bytes]],
    *,
    source_checkpoint: str,
) -> str:
    if (
        re.fullmatch(r"[0-9a-f]{40}", source_checkpoint) is None
        or source_checkpoint in PUBLIC_PROVENANCE_ROLE_TOKENS
    ):
        raise ArtifactValidationError("Git diff revision is not a captured implementation commit.")
    output = _git_bytes(
        git,
        root,
        "diff",
        "--name-status",
        "-z",
        "-M",
        source_checkpoint,
        "--",
        "pyproject.toml",
        "uv.lock",
        "research_decision_engine",
        "tests",
    )
    parts = output.split(b"\0")
    index = 0
    changes: list[tuple[str, str, str | None, str | None]] = []
    while index < len(parts) and parts[index]:
        encoded_status = parts[index].decode("ascii")
        index += 1
        if encoded_status.startswith("R"):
            old_path = parts[index].decode("utf-8")
            new_path = parts[index + 1].decode("utf-8")
            index += 2
            if _implementation_path(old_path) or _implementation_path(new_path):
                changes.append((f"{old_path}->{new_path}", "renamed", old_path, new_path))
            continue
        path = parts[index].decode("utf-8")
        index += 1
        if not _implementation_path(path):
            continue
        status = {"A": "added", "D": "deleted", "M": "modified"}.get(encoded_status[0], "modified")
        changes.append(
            (
                path,
                status,
                path if status != "added" else None,
                path if status != "deleted" else None,
            )
        )

    rows: list[dict[str, object]] = []
    for change_path, change_status, previous_path, current_path in sorted(
        changes,
        key=lambda item: item[0].encode("utf-8"),
    ):
        old = old_tree.get(previous_path) if previous_path is not None else None
        new = new_tree.get(current_path) if current_path is not None else None
        rows.append(
            {
                "path": change_path,
                "status": change_status,
                "old_git_mode": old[0] if old is not None else None,
                "new_git_mode": new[0] if new is not None else None,
                "old_byte_length": len(old[1]) if old is not None else None,
                "new_byte_length": len(new[1]) if new is not None else None,
                "old_sha256": hashlib.sha256(old[1]).hexdigest() if old is not None else None,
                "new_sha256": hashlib.sha256(new[1]).hexdigest() if new is not None else None,
            }
        )
    payload = b"".join(canonical_json_bytes(row, final_lf=True) for row in rows)
    return hashlib.sha256(payload).hexdigest()


def _worktree_identity(root: Path, status: bytes) -> str:
    parts = status.split(b"\0")
    paths: set[str] = set()
    index = 0
    while index < len(parts) and parts[index]:
        entry = parts[index]
        index += 1
        if len(entry) < 4:
            raise ArtifactValidationError("Git porcelain status is malformed.")
        code = entry[:2].decode("ascii")
        paths.add(entry[3:].decode("utf-8"))
        if "R" in code or "C" in code:
            paths.add(parts[index].decode("utf-8"))
            index += 1
    rows: list[dict[str, object]] = []
    for relative in sorted(paths, key=lambda item: item.encode("utf-8")):
        path = root / relative
        if path.is_symlink():
            content = os.readlink(path).encode("utf-8")
            kind = "symlink"
        elif path.is_file():
            content = path.read_bytes()
            kind = "file"
        else:
            content = b""
            kind = "missing"
        rows.append(
            {
                "path": relative,
                "kind": kind,
                "byte_length": len(content) if kind != "missing" else None,
                "file_sha256": hashlib.sha256(content).hexdigest() if kind != "missing" else None,
            }
        )
    payload = {"porcelain_v1_z_hex": status.hex(), "changed_paths": rows}
    return hashlib.sha256(canonical_json_bytes(payload, final_lf=True)).hexdigest()


@dataclass(frozen=True, slots=True)
class PrefinalizationArtifactSet:
    """Validated temporary artifacts 1-9, before gates or audit claims exist."""

    artifacts: tuple[tuple[str, bytes], ...]
    contracts: tuple[ArtifactContract, ...]
    profile: ArtifactCardinalityProfile
    graph: CanonicalArtifactGraph
    operational_provenance_sha256: str

    def artifact_mapping(self) -> dict[str, bytes]:
        return dict(self.artifacts)

    def revalidated_graph(self) -> CanonicalArtifactGraph:
        return decode_and_validate_prefinal_artifacts(
            self.artifact_mapping(),
            self.contracts,
            profile=self.profile,
        )

    def scientific_claims(self) -> dict[str, object]:
        graph = self.revalidated_graph()
        return {artifact.contract.filename: artifact.scientific for artifact in graph.artifacts}


@dataclass(frozen=True, slots=True)
class _PrefinalizationArtifactBinding:
    prefinalization: PrefinalizationArtifactSet
    operational: AssemblyOperationalProvenance
    scientific: Mapping[str, object]


_ISSUED_PREFINALIZATION_ARTIFACT_SETS: dict[int, _PrefinalizationArtifactBinding] = {}


def _issued_operational_for_prefinalization(
    prefinalization: PrefinalizationArtifactSet,
) -> AssemblyOperationalProvenance:
    record = _ISSUED_PREFINALIZATION_ARTIFACT_SETS.get(id(prefinalization))
    if record is None or record.prefinalization is not prefinalization:
        raise ArtifactValidationError(
            "Prefinal artifact set was not issued by exact prefinalization assembly."
        )
    operational = record.operational
    _require_exact_issued_operational_provenance(operational)
    return operational


def _issued_scientific_for_prefinalization(
    prefinalization: PrefinalizationArtifactSet,
) -> Mapping[str, object]:
    """Return the exact scientific projection serialized into a prefinal set."""

    record = _ISSUED_PREFINALIZATION_ARTIFACT_SETS.get(id(prefinalization))
    if record is None or record.prefinalization is not prefinalization:
        raise ArtifactValidationError(
            "Prefinal artifact set was not issued by exact prefinalization assembly."
        )
    return record.scientific


def _require_exact_prefinalization_operational_provenance(
    prefinalization: PrefinalizationArtifactSet,
    operational: AssemblyOperationalProvenance,
) -> None:
    """Require the exact assembled prefinal set and exact provenance used to issue it."""

    issued_operational = _issued_operational_for_prefinalization(prefinalization)
    if issued_operational is not operational:
        raise ArtifactValidationError(
            "Prefinal artifacts differ from their exact issued operational provenance."
        )
    if prefinalization.operational_provenance_sha256 != (
        _operational_provenance_sha256(operational)
    ):
        raise ArtifactValidationError(
            "Prefinal artifacts differ from their exact issued operational provenance."
        )


@dataclass(frozen=True, slots=True)
class CanonicalFinalizationPlan:
    """Forward-only input produced after A16, without manifest or recommendation."""

    prefinalization: PrefinalizationArtifactSet
    post_audit: PostAuditScientificPayloads

    def scientific_claims(self) -> dict[str, object]:
        return deepcopy(
            merged_scientific_claims(self.prefinalization.scientific_claims(), self.post_audit)
        )


def assemble_prefinalization_artifacts(
    scientific: Mapping[str, object],
    operational: AssemblyOperationalProvenance,
    *,
    contracts: Sequence[ArtifactContract] | None = None,
    profile: ArtifactCardinalityProfile = FROZEN_ARTIFACT_PROFILE,
) -> PrefinalizationArtifactSet:
    """Serialize and substantively validate temporary artifacts 1-9."""

    if type(
        operational
    ) is not AssemblyOperationalProvenance or not _is_exact_issued_operational_provenance(
        operational
    ):
        raise ArtifactValidationError(
            "Prefinalization requires exact operational provenance issued by reconstruction."
        )
    operational_execution = _require_operational_execution_binding(operational)
    try:
        projection_execution = _require_issued_prefinalization_payloads(scientific)
    except ValueError as error:
        raise ArtifactValidationError(str(error)) from error
    if projection_execution is not operational_execution:
        raise ArtifactValidationError(
            "Scientific payloads and operational provenance belong to different executions."
        )
    frozen_contracts = tuple(contracts or artifact_contracts())
    prefinal_contracts = frozen_contracts[:9]
    expected_names = tuple(contract.filename for contract in prefinal_contracts)
    if tuple(scientific) != expected_names:
        raise ArtifactValidationError(
            "Prefinalization requires scientific payloads for exactly artifacts 1-9."
        )
    source_hash = load_protocol_snapshot().source_design_sha256
    artifacts = {
        contract.filename: _serialize(
            contract,
            scientific[contract.filename],
            source_hash=source_hash,
            operational=(
                operational.protocol if contract.filename == "protocol_snapshot.json" else {}
            ),
        )
        for contract in prefinal_contracts
    }
    graph = decode_and_validate_prefinal_artifacts(
        artifacts,
        prefinal_contracts,
        profile=profile,
    )
    prefinalization = PrefinalizationArtifactSet(
        artifacts=tuple(artifacts.items()),
        contracts=prefinal_contracts,
        profile=profile,
        graph=graph,
        operational_provenance_sha256=_operational_provenance_sha256(operational),
    )
    _ISSUED_PREFINALIZATION_ARTIFACT_SETS[id(prefinalization)] = _PrefinalizationArtifactBinding(
        prefinalization, operational, scientific
    )
    return prefinalization


def assemble_audited_scientific_artifacts(
    plan: CanonicalFinalizationPlan,
    operational: AssemblyOperationalProvenance,
    audit_results: Sequence[IntegrityAuditResult],
    *,
    contracts: Sequence[ArtifactContract] | None = None,
    profile: ArtifactCardinalityProfile = FROZEN_ARTIFACT_PROFILE,
) -> dict[str, bytes]:
    """Assemble and validate only scientific artifacts 1-11 after A16."""

    if not isinstance(plan, CanonicalFinalizationPlan):
        raise ArtifactValidationError("Scientific assembly requires a staged finalization plan.")
    _require_exact_prefinalization_operational_provenance(plan.prefinalization, operational)
    operational_execution = _require_operational_execution_binding(operational)
    prefinalization_scientific = _issued_scientific_for_prefinalization(plan.prefinalization)
    try:
        post_audit_execution = _require_issued_post_audit_payloads(
            plan.post_audit,
            prefinalization=prefinalization_scientific,
            audit_results=audit_results,
        )
    except ValueError as error:
        raise ArtifactValidationError(str(error)) from error
    if post_audit_execution is not operational_execution:
        raise ArtifactValidationError(
            "Post-audit payloads and operational provenance belong to different executions."
        )
    frozen_contracts = tuple(contracts or artifact_contracts())
    _require_frozen_contracts(frozen_contracts, expected_count=13)
    if tuple(plan.prefinalization.contracts) != frozen_contracts[:9]:
        raise ArtifactValidationError("Prefinal artifact contracts differ from the final set.")
    if plan.prefinalization.profile != profile:
        raise ArtifactValidationError("Prefinal and final artifact profiles differ.")
    if plan.prefinalization.operational_provenance_sha256 != (
        _operational_provenance_sha256(operational)
    ):
        raise ArtifactValidationError(
            "Prefinal artifacts differ from the supplied operational provenance."
        )
    scientific = plan.scientific_claims()
    _validate_finalization_authorization(scientific, audit_results)
    artifacts = _assemble_audited_artifact_bytes(
        plan,
        operational,
        frozen_contracts,
        profile,
    )
    _ISSUED_LIFECYCLE_ARTIFACTS[id(artifacts)] = _IssuedLifecycleArtifacts(
        artifacts=artifacts,
        execution=operational_execution,
        artifact_sha256=tuple(
            (name, hashlib.sha256(content).hexdigest()) for name, content in artifacts.items()
        ),
    )
    return artifacts


def _assemble_audited_artifact_bytes(
    plan: CanonicalFinalizationPlan,
    operational: AssemblyOperationalProvenance,
    contracts: Sequence[ArtifactContract],
    profile: ArtifactCardinalityProfile,
) -> dict[str, bytes]:
    """Deterministically serialize artifacts 1-11 for binding and promotion."""

    _require_exact_prefinalization_operational_provenance(plan.prefinalization, operational)
    frozen_contracts = tuple(contracts)
    _require_frozen_contracts(frozen_contracts, expected_count=13)
    if tuple(plan.prefinalization.contracts) != frozen_contracts[:9]:
        raise ArtifactValidationError("Prefinal artifact contracts differ from the final set.")
    if plan.prefinalization.profile != profile:
        raise ArtifactValidationError("Prefinal and final artifact profiles differ.")
    if plan.prefinalization.operational_provenance_sha256 != (
        _operational_provenance_sha256(operational)
    ):
        raise ArtifactValidationError(
            "Prefinal artifacts differ from the supplied operational provenance."
        )
    scientific = plan.scientific_claims()
    authorization_names = tuple(contract.filename for contract in frozen_contracts[:11])
    if tuple(scientific) != authorization_names:
        raise ArtifactValidationError(
            "Final assembly authorization requires exact artifacts 1-11 claims."
        )
    source_hash = load_protocol_snapshot().source_design_sha256
    artifacts = plan.prefinalization.artifact_mapping()

    gate_contract = frozen_contracts[9]
    if gate_contract.filename != "gate_evaluations.json":
        raise ArtifactValidationError("Frozen artifact 10 is not the gate artifact.")
    artifacts[gate_contract.filename] = _serialize(
        gate_contract,
        scientific[gate_contract.filename],
        source_hash=source_hash,
        operational={},
    )
    first_ten_names = tuple(contract.filename for contract in frozen_contracts[:10])

    audit_contract = frozen_contracts[10]
    if audit_contract.filename != "audit_results.json":
        raise ArtifactValidationError("Frozen artifact 11 is not the audit artifact.")
    audit_operational = {
        "artifact_content_sha256": {
            name: hashlib.sha256(artifacts[name]).hexdigest() for name in first_ten_names
        },
        "artifact_scientific_payload_sha256": {
            name: _scientific_payload_hash(
                next(item for item in frozen_contracts if item.filename == name),
                scientific[name],
                source_hash,
            )
            for name in first_ten_names
        },
        "historical_before_sha256": dict(operational.historical_before_sha256),
        "historical_after_sha256": dict(operational.historical_after_sha256),
    }
    artifacts[audit_contract.filename] = _serialize(
        audit_contract,
        scientific[audit_contract.filename],
        source_hash=source_hash,
        operational=audit_operational,
    )

    first_eleven_names = tuple(contract.filename for contract in frozen_contracts[:11])
    first_eleven = {name: artifacts[name] for name in first_eleven_names}
    decode_and_validate_audited_artifacts(
        first_eleven,
        frozen_contracts[:11],
        profile=profile,
    )
    return first_eleven


def authorize_canonical_finalization(
    target: Path,
    plan: CanonicalFinalizationPlan,
    operational: AssemblyOperationalProvenance,
    certificate: FinalizationAuditCertificate,
    *,
    contracts: Sequence[ArtifactContract] | None = None,
    profile: ArtifactCardinalityProfile = FROZEN_ARTIFACT_PROFILE,
) -> FinalizationAuthorization:
    """Reject the superseded no-ledger canonical authorization path.

    Task B freezes the lifecycle authority while Task C remains responsible for wiring
    the scientific producer into it.  Validation-only finalization remains isolated and
    available below; this legacy canonical entry must not create a P1 graph without an
    amended attempt ledger.
    """

    del target, plan, operational, certificate, contracts, profile
    raise ArtifactValidationError(SUPERSEDED_CANONICAL_FINALIZATION_ERROR)


def authorize_validation_finalization(
    target: Path,
    plan: CanonicalFinalizationPlan,
    operational: AssemblyOperationalProvenance,
    certificate: FinalizationAuditCertificate,
    *,
    contracts: Sequence[ArtifactContract] | None = None,
    profile: ArtifactCardinalityProfile,
) -> FinalizationAuthorization:
    """Seal a validation-only artifact lifecycle that cannot target canonical output."""

    return _authorize_finalization(
        target,
        plan,
        operational,
        certificate,
        contracts=contracts,
        profile=profile,
        finalization_scope=VALIDATION_FINALIZATION_SCOPE,
    )


def _authorize_finalization(
    target: Path,
    plan: CanonicalFinalizationPlan,
    operational: AssemblyOperationalProvenance,
    certificate: FinalizationAuditCertificate,
    *,
    contracts: Sequence[ArtifactContract] | None,
    profile: ArtifactCardinalityProfile,
    finalization_scope: str,
) -> FinalizationAuthorization:
    frozen_contracts = tuple(contracts or artifact_contracts())
    _require_finalization_context(
        target,
        frozen_contracts,
        profile,
        finalization_scope=finalization_scope,
    )
    issued_plan_operational = _issued_operational_for_prefinalization(plan.prefinalization)
    executor_attestation = _issued_executor_for_operational(issued_plan_operational)
    actual_state = _reconstruct_actual_finalization_state(
        target,
        executor_attestation=executor_attestation,
    )
    _require_actual_operational_provenance(
        operational,
        actual_state,
        finalization_scope=finalization_scope,
    )
    audit_results = finalization_audit_results(certificate)
    authorized_artifacts = assemble_audited_scientific_artifacts(
        plan,
        operational,
        audit_results,
        contracts=frozen_contracts,
        profile=profile,
    )
    binding = _finalization_binding(
        target,
        plan,
        operational,
        frozen_contracts,
        profile=profile,
        finalization_scope=finalization_scope,
        actual_state=actual_state,
        authorized_artifacts=authorized_artifacts,
    )
    attestation = _issue_checked_finalization_binding_attestation(
        target,
        plan,
        operational,
        certificate,
        frozen_contracts,
        profile,
        finalization_scope=finalization_scope,
        binding=binding,
    )
    try:
        return seal_finalization_authorization(
            certificate,
            binding,
            binding_attestation=attestation,
        )
    finally:
        _ISSUED_FINALIZATION_BINDING_ATTESTATIONS.pop(attestation, None)


def finalize_canonical_artifacts(
    target: Path,
    plan: CanonicalFinalizationPlan,
    operational: AssemblyOperationalProvenance,
    authorization: FinalizationAuthorization,
    *,
    contracts: Sequence[ArtifactContract] | None = None,
    profile: ArtifactCardinalityProfile = FROZEN_ARTIFACT_PROFILE,
) -> dict[str, bytes]:
    """Reject the superseded canonical writer before any filesystem mutation."""

    del target, plan, operational, authorization, contracts, profile
    raise ArtifactValidationError(SUPERSEDED_CANONICAL_FINALIZATION_ERROR)


def finalize_validation_artifacts(
    target: Path,
    plan: CanonicalFinalizationPlan,
    operational: AssemblyOperationalProvenance,
    authorization: FinalizationAuthorization,
    *,
    contracts: Sequence[ArtifactContract] | None = None,
    profile: ArtifactCardinalityProfile,
) -> dict[str, bytes]:
    """Persist a validation-only graph under a validation-scoped receipt."""

    return _finalize_artifacts(
        target,
        plan,
        operational,
        authorization,
        contracts=contracts,
        profile=profile,
        finalization_scope=VALIDATION_FINALIZATION_SCOPE,
    )


def _finalize_artifacts(
    target: Path,
    plan: CanonicalFinalizationPlan,
    operational: AssemblyOperationalProvenance,
    authorization: FinalizationAuthorization,
    *,
    contracts: Sequence[ArtifactContract] | None,
    profile: ArtifactCardinalityProfile,
    finalization_scope: str,
) -> dict[str, bytes]:
    frozen_contracts = tuple(contracts or artifact_contracts())
    try:
        _require_finalization_context(
            target,
            frozen_contracts,
            profile,
            finalization_scope=finalization_scope,
        )
        return _promote_authorized_artifacts(
            target,
            plan,
            operational,
            authorization,
            contracts=frozen_contracts,
            profile=profile,
            finalization_scope=finalization_scope,
        )
    except (ArtifactValidationError, ValueError, TypeError, OSError) as exc:
        _emit_validation_failure(target, exc)
        raise


def _promote_authorized_artifacts(
    target: Path,
    plan: CanonicalFinalizationPlan,
    operational: AssemblyOperationalProvenance,
    authorization: FinalizationAuthorization,
    *,
    contracts: tuple[ArtifactContract, ...],
    profile: ArtifactCardinalityProfile,
    finalization_scope: str,
) -> dict[str, bytes]:
    """Consume authorization, then perform the sole forward-only disk lifecycle."""

    try:
        binding = _finalization_binding(
            target,
            plan,
            operational,
            contracts,
            profile=profile,
            finalization_scope=finalization_scope,
        )
    except Exception as error:
        invalidate_unconsumed_finalization_authorization(authorization)
        raise ValueError(
            "Finalization capability context does not match its sealed binding."
        ) from error
    receipt: ConsumedFinalizationAuthorization | None = None
    try:
        receipt = consume_finalization_authorization(authorization, binding)
        audit_results = finalization_receipt_audit_results(
            receipt,
            expected_phase="authorization_consumed",
        )
        scientific_artifacts = assemble_audited_scientific_artifacts(
            plan,
            operational,
            audit_results,
            contracts=contracts,
            profile=profile,
        )
        _promote_scientific_artifacts(
            target,
            scientific_artifacts,
            contracts[:11],
            profile,
            receipt=receipt,
        )
        promoted_names = tuple(contract.filename for contract in contracts[:11])
        promoted = _read_exact_artifacts(target, promoted_names)
        decode_and_validate_audited_artifacts(promoted, contracts[:11], profile=profile)
        advance_finalization_receipt(
            receipt,
            expected_phase="authorization_consumed",
            next_phase="scientific_artifacts_promoted",
        )

        manifest_bytes = _derive_manifest_from_promoted_artifacts(
            target,
            receipt,
            contracts,
            profile,
        )
        _atomic_create(
            target,
            "run_manifest.json",
            manifest_bytes,
            receipt=receipt,
            contracts=contracts,
            profile=profile,
        )
        first_twelve = _read_exact_artifacts(
            target,
            tuple(contract.filename for contract in contracts[:12]),
        )
        decode_and_validate_manifest_artifacts(
            first_twelve,
            contracts[:12],
            profile=profile,
        )
        advance_finalization_receipt(
            receipt,
            expected_phase="scientific_artifacts_promoted",
            next_phase="manifest_persisted",
        )

        recommendation_bytes = _derive_recommendation_from_persisted_manifest(
            target,
            receipt,
            contracts,
            profile,
        )
        _verify_constructed_recommendation_commitment(
            target,
            recommendation_bytes,
            receipt,
            contracts,
            profile,
        )
        _atomic_create(
            target,
            "recommendation.json",
            recommendation_bytes,
            receipt=receipt,
            contracts=contracts,
            profile=profile,
        )
        advance_finalization_receipt(
            receipt,
            expected_phase="manifest_persisted",
            next_phase="recommendation_persisted",
        )
        persisted = _read_exact_artifacts(
            target,
            tuple(contract.filename for contract in contracts),
        )
        decode_and_validate_artifacts(persisted, contracts, profile=profile)
        complete_finalization_receipt(receipt)
        receipt = None
        return persisted
    finally:
        if receipt is not None:
            invalidate_finalization_receipt(receipt)


def _require_exact_finalization_binding_fields(binding: Mapping[str, object]) -> None:
    actual = frozenset(binding)
    if actual != _FINALIZATION_BINDING_FIELDS:
        raise ArtifactValidationError(
            "Finalization binding fields differ; "
            f"missing={sorted(_FINALIZATION_BINDING_FIELDS - actual)}, "
            f"extra={sorted(actual - _FINALIZATION_BINDING_FIELDS)}."
        )


def _issue_checked_finalization_binding_attestation(
    target: Path,
    plan: CanonicalFinalizationPlan,
    operational: AssemblyOperationalProvenance,
    certificate: FinalizationAuditCertificate,
    contracts: Sequence[ArtifactContract],
    profile: ArtifactCardinalityProfile,
    *,
    finalization_scope: str,
    binding: Mapping[str, object],
) -> _FinalizationBindingAttestation:
    """Repeat every trusted check, then attest exactly one binding for sealing."""

    frozen_contracts = tuple(contracts)
    _require_finalization_context(
        target,
        frozen_contracts,
        profile,
        finalization_scope=finalization_scope,
    )
    issued_plan_operational = _issued_operational_for_prefinalization(plan.prefinalization)
    executor_attestation = _issued_executor_for_operational(issued_plan_operational)
    actual_state = _reconstruct_actual_finalization_state(
        target,
        executor_attestation=executor_attestation,
    )
    _require_actual_operational_provenance(
        operational,
        actual_state,
        finalization_scope=finalization_scope,
    )
    audit_results = finalization_audit_results(certificate)
    authorized_artifacts = assemble_audited_scientific_artifacts(
        plan,
        operational,
        audit_results,
        contracts=frozen_contracts,
        profile=profile,
    )
    expected = _finalization_binding(
        target,
        plan,
        operational,
        frozen_contracts,
        profile=profile,
        finalization_scope=finalization_scope,
        actual_state=actual_state,
        authorized_artifacts=authorized_artifacts,
    )
    _require_exact_finalization_binding_fields(binding)
    if dict(binding) != expected:
        raise ArtifactValidationError(
            "Finalization binding differs from the fully checked assembly context."
        )
    attestation = _FinalizationBindingAttestation(_FINALIZATION_BINDING_ATTESTATION_KEY)
    _ISSUED_FINALIZATION_BINDING_ATTESTATIONS[attestation] = canonical_json_bytes(
        dict(binding),
        final_lf=True,
    )
    return attestation


def _consume_finalization_binding_attestation(
    attestation: object,
    binding: Mapping[str, object],
) -> None:
    """Consume one exact assembly-issued attestation before public sealing."""

    if type(attestation) is not _FinalizationBindingAttestation:
        raise ValueError("Finalization sealing requires an exact issued binding attestation.")
    expected = _ISSUED_FINALIZATION_BINDING_ATTESTATIONS.pop(attestation, None)
    if expected is None:
        raise ValueError("Finalization binding attestation is forged, stale, or already used.")
    _require_exact_finalization_binding_fields(binding)
    observed = canonical_json_bytes(dict(binding), final_lf=True)
    if observed != expected:
        raise ValueError("Finalization binding differs from its checked attestation.")


def _finalization_binding(
    target: Path,
    plan: CanonicalFinalizationPlan,
    operational: AssemblyOperationalProvenance,
    contracts: Sequence[ArtifactContract],
    *,
    profile: ArtifactCardinalityProfile,
    finalization_scope: str,
    actual_state: Mapping[str, object] | None = None,
    authorized_artifacts: Mapping[str, bytes] | None = None,
) -> dict[str, object]:
    """Recompute every context value sealed into the single-use capability."""

    if type(plan) is not CanonicalFinalizationPlan:
        raise ArtifactValidationError("Finalization binding requires a staged plan.")
    _require_exact_prefinalization_operational_provenance(plan.prefinalization, operational)
    if plan.prefinalization.operational_provenance_sha256 != (
        _operational_provenance_sha256(operational)
    ):
        raise ArtifactValidationError(
            "Finalization plan differs from its prefinal operational provenance."
        )
    _require_finalization_context(
        target,
        contracts,
        profile,
        finalization_scope=finalization_scope,
    )
    scientific = plan.scientific_claims()
    expected_names = tuple(contract.filename for contract in contracts[:11])
    if tuple(scientific) != expected_names:
        raise ArtifactValidationError("Finalization binding requires exact artifacts 1-11.")
    source_hash = load_protocol_snapshot().source_design_sha256
    scientific_hashes = {
        contract.filename: _scientific_payload_hash(
            contract,
            scientific[contract.filename],
            source_hash,
        )
        for contract in contracts[:11]
    }
    bound_artifacts = dict(
        authorized_artifacts
        or _assemble_audited_artifact_bytes(plan, operational, contracts, profile)
    )
    if tuple(bound_artifacts) != expected_names:
        raise ArtifactValidationError(
            "Finalization binding requires exact artifact bytes for artifacts 1-11."
        )
    content_hashes = {
        name: hashlib.sha256(bound_artifacts[name]).hexdigest() for name in expected_names
    }
    gate = cast(Mapping[str, object], scientific["gate_evaluations.json"])
    gate_rows = cast(Sequence[Mapping[str, object]], gate.get("gates", ()))
    integrity = next(
        (row.get("gate_status") for row in gate_rows if row.get("gate_id") == "G-INTEGRITY"),
        None,
    )
    run_rows = cast(Sequence[Mapping[str, object]], scientific["arm_runs.jsonl"])
    operational_payload = _operational_provenance_payload(operational)
    actual = dict(
        actual_state
        or _reconstruct_actual_finalization_state(
            target,
            executor_attestation=_issued_executor_for_operational(operational),
        )
    )
    return {
        "authorization_version": FINALIZATION_AUTHORIZATION_VERSION,
        "finalization_scope": finalization_scope,
        "lifecycle_phase": "ready_to_promote_scientific_artifacts",
        "canonical_output_directory": actual["normalized_output_directory"],
        "artifact_contract_registry_sha256": _artifact_contract_registry_sha256(),
        "artifact_cardinality_profile": _artifact_profile_payload(profile),
        "design_checkpoint": operational.protocol.get("design_checkpoint_commit"),
        "source_design_sha256": source_hash,
        "source_checkpoint_identity": SOURCE_CHECKPOINT,
        "implementation_tree_sha256": operational.implementation_tree_sha256,
        "implementation_diff_sha256": operational.implementation_diff_sha256,
        "operational_provenance_sha256": _operational_provenance_sha256(operational),
        "operational_provenance": operational_payload,
        "actual_finalization_state": actual,
        "study_identity": gate.get("evaluation_id"),
        "ordered_run_identity_sha256": hashlib.sha256(
            canonical_json_bytes(
                [row.get("run_id") for row in run_rows],
                final_lf=True,
            )
        ).hexdigest(),
        "scientific_payload_sha256": scientific_hashes,
        "artifact_content_sha256": content_hashes,
        "audit_certificate_plan_sha256": finalization_plan_binding_sha256(
            scientific,
            profile,
        ),
        "g_integrity": integrity,
        "provisional_decision": {
            "branch_id": gate.get("final_branch_id"),
            "branch_trace": gate.get("final_branch_trace"),
            "gate_status": gate.get("final_gate_status"),
            "recommendation": gate.get("recommendation"),
        },
    }


def _operational_provenance_payload(
    operational: AssemblyOperationalProvenance,
) -> dict[str, object]:
    return {
        "protocol": dict(operational.protocol),
        "historical_before_sha256": dict(operational.historical_before_sha256),
        "historical_after_sha256": dict(operational.historical_after_sha256),
        "implementation_commit": operational.implementation_commit,
        "implementation_tree_sha256": operational.implementation_tree_sha256,
        "implementation_diff_sha256": operational.implementation_diff_sha256,
        "implementation_tree_clean": operational.implementation_tree_clean,
        "started_at": operational.started_at,
        "completed_at": operational.completed_at,
        "dependency_versions": dict(operational.dependency_versions),
        "machine": dict(operational.machine),
    }


def _operational_provenance_sha256(
    operational: AssemblyOperationalProvenance,
) -> str:
    return hashlib.sha256(_operational_provenance_bytes(operational)).hexdigest()


def _operational_provenance_bytes(
    operational: AssemblyOperationalProvenance,
) -> bytes:
    return canonical_json_bytes(_operational_provenance_payload(operational), final_lf=True)


def _is_exact_issued_operational_provenance(
    operational: AssemblyOperationalProvenance,
) -> bool:
    issued = _ISSUED_OPERATIONAL_PROVENANCE.get(id(operational))
    if issued is None or issued.operational is not operational:
        return False
    try:
        canonical_bytes = _operational_provenance_bytes(operational)
        return (
            issued.canonical_bytes == canonical_bytes
            and issued.sha256 == hashlib.sha256(canonical_bytes).hexdigest()
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _require_exact_issued_operational_provenance(
    operational: AssemblyOperationalProvenance,
) -> _IssuedOperationalProvenance:
    issued = _ISSUED_OPERATIONAL_PROVENANCE.get(id(operational))
    if issued is None or issued.operational is not operational:
        raise ArtifactValidationError(
            "Operational provenance was not issued by actual-state reconstruction."
        )
    if not _is_exact_issued_operational_provenance(operational):
        raise ArtifactValidationError(
            "Operational provenance differs from the exact bytes issued by "
            "actual-state reconstruction."
        )
    return issued


def _require_operational_execution_binding(
    operational: AssemblyOperationalProvenance,
) -> _IssuedAttestation:
    issued = _require_exact_issued_operational_provenance(operational)
    execution = _require_issued_result_batch(
        issued.consumed_results,
        expected_purposes=(issued.execution_purpose,),
    )
    if (
        execution is not issued.execution
        or execution.attestation is not issued.executor_attestation
        or execution.authority is not issued.execution_authority
    ):
        raise ArtifactValidationError(
            "Operational provenance executor/result authority is stale or cross-bound."
        )
    return execution


def _require_lifecycle_execution_binding(
    artifacts: Mapping[str, bytes],
) -> _IssuedLifecycleArtifacts:
    """Bind canonical lifecycle preparation to exact-issued full-study artifact bytes."""

    issued = _ISSUED_LIFECYCLE_ARTIFACTS.get(id(artifacts))
    observed_hashes = tuple(
        (name, hashlib.sha256(content).hexdigest()) for name, content in artifacts.items()
    )
    if (
        issued is None
        or issued.artifacts is not artifacts
        or issued.artifact_sha256 != observed_hashes
    ):
        raise ArtifactValidationError(
            "Lifecycle preparation requires exact-issued executor-bound artifacts 1-11."
        )
    execution = _require_issued_result_batch(
        issued.execution.returned_results,
        expected_purposes=("full_study",),
        require_trust_domain="production",
    )
    if execution is not issued.execution:
        raise ArtifactValidationError("Lifecycle artifacts belong to stale executor authority.")
    return issued


def _revalidate_lifecycle_execution_binding(
    binding: object,
    artifacts: Mapping[str, bytes] | None = None,
) -> None:
    if type(binding) is not _IssuedLifecycleArtifacts:
        raise ArtifactValidationError("Lifecycle artifact/executor binding is forged or copied.")
    issued = binding
    registered = _ISSUED_LIFECYCLE_ARTIFACTS.get(id(issued.artifacts))
    source_hashes = tuple(
        (name, hashlib.sha256(content).hexdigest()) for name, content in issued.artifacts.items()
    )
    observed_hashes = (
        tuple((name, hashlib.sha256(content).hexdigest()) for name, content in artifacts.items())
        if artifacts is not None
        else issued.artifact_sha256
    )
    if (
        registered is not issued
        or registered.artifacts is not issued.artifacts
        or source_hashes != issued.artifact_sha256
        or observed_hashes != issued.artifact_sha256
    ):
        raise ArtifactValidationError(
            "Lifecycle artifact bundle is stale, changed, copied, or cross-bound."
        )
    execution = issued.execution
    current = _require_issued_result_batch(
        execution.returned_results,
        expected_purposes=("full_study",),
        require_trust_domain="production",
    )
    if current is not execution:
        raise ArtifactValidationError("Lifecycle executor binding is stale or cross-bound.")


def _validate_lifecycle_manifest_execution_binding(content: bytes, binding: object) -> None:
    _revalidate_lifecycle_execution_binding(binding)
    execution = cast(_IssuedLifecycleArtifacts, binding).execution
    try:
        value = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ArtifactValidationError(
            "Lifecycle manifest executor binding is unreadable."
        ) from error
    if not isinstance(value, Mapping) or not isinstance(value.get("machine"), Mapping):
        raise ArtifactValidationError("Lifecycle manifest lacks executor operational provenance.")
    machine = cast(Mapping[str, object], value["machine"])
    expected_machine = executor_provenance_payload(execution.attestation)
    if any(machine.get(field) != expected for field, expected in expected_machine.items()):
        raise ArtifactValidationError(
            "Lifecycle manifest belongs to another executor result batch."
        )
    observation = execution.observation
    expected = {
        "implementation_commit": observation.implementation_commit,
        "implementation_tree_sha256": observation.implementation_tree_sha256,
        "implementation_diff_sha256": observation.implementation_diff_sha256,
        "started_at": observation.execution_started_at,
        "completed_at": observation.execution_completed_at,
    }
    if any(value.get(field) != expected_value for field, expected_value in expected.items()):
        raise ArtifactValidationError("Lifecycle manifest executor/runtime binding differs.")


def _require_actual_operational_provenance(
    operational: AssemblyOperationalProvenance,
    actual: Mapping[str, object],
    *,
    finalization_scope: str,
) -> None:
    if actual.get("design_matches_checkpoint") is not True:
        raise ArtifactValidationError("The working design bytes differ from the frozen Git blob.")
    if actual.get("protected_source_matches") is not True:
        raise ArtifactValidationError("A protected source hash differs from the freeze.")
    _require_clean_actual_state(actual)
    if finalization_scope == CANONICAL_FINALIZATION_SCOPE and (
        operational.implementation_tree_clean is not True
    ):
        raise ArtifactValidationError(
            "Canonical finalization requires clean issued operational provenance."
        )
    snapshot = load_protocol_snapshot()
    if actual.get("source_design_sha256") != snapshot.source_design_sha256:
        raise ArtifactValidationError("Actual design identity differs from the protocol snapshot.")
    for field, value in (
        ("started_at", operational.started_at),
        ("completed_at", operational.completed_at),
    ):
        if TS_PATTERN.fullmatch(value) is None:
            raise ArtifactValidationError(
                f"Caller operational provenance {field} is not canonical."
            )
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
        except ValueError as error:
            raise ArtifactValidationError(
                f"Caller operational provenance {field} is not a real timestamp."
            ) from error
    if operational.completed_at < operational.started_at:
        raise ArtifactValidationError("Caller operational completion precedes its start.")
    expected_protocol = cast(Mapping[str, object], actual["protocol"])
    comparisons = (
        ("protocol", dict(operational.protocol), dict(expected_protocol)),
        (
            "implementation_commit",
            operational.implementation_commit,
            actual["implementation_commit"],
        ),
        (
            "implementation_tree_sha256",
            operational.implementation_tree_sha256,
            actual["implementation_tree_sha256"],
        ),
        (
            "implementation_diff_sha256",
            operational.implementation_diff_sha256,
            actual["implementation_diff_sha256"],
        ),
        (
            "implementation_tree_clean",
            operational.implementation_tree_clean,
            actual["implementation_tree_clean"],
        ),
        (
            "historical_before_sha256",
            dict(operational.historical_before_sha256),
            dict(cast(Mapping[str, str], actual["historical_source_sha256"])),
        ),
        (
            "historical_after_sha256",
            dict(operational.historical_after_sha256),
            dict(cast(Mapping[str, str], actual["historical_source_sha256"])),
        ),
        (
            "dependency_versions",
            dict(operational.dependency_versions),
            dict(cast(Mapping[str, str], actual["dependency_versions"])),
        ),
        (
            "machine",
            dict(operational.machine),
            dict(cast(Mapping[str, str], actual["machine"])),
        ),
    )
    for field, observed, expected in comparisons:
        if observed != expected:
            raise ArtifactValidationError(
                f"Caller operational provenance {field} differs from actual state."
            )
    _require_exact_issued_operational_provenance(operational)
    _issued_executor_for_operational(operational)


def _require_clean_actual_state(
    actual: Mapping[str, object],
) -> None:
    if actual.get("implementation_tree_clean") is not True:
        raise ArtifactValidationError("Finalization requires an actually clean Git working tree.")


def _issued_executor_for_operational(
    operational: AssemblyOperationalProvenance,
) -> ActualExecutorAttestation:
    execution = _require_operational_execution_binding(operational)
    issued = _require_exact_issued_operational_provenance(operational)
    attestation = issued.executor_attestation
    if execution.attestation is not attestation:
        raise ArtifactValidationError("Operational provenance executor authority changed.")
    executor_provenance_payload(attestation)
    return attestation


def _record_contract_payload(
    contract: RecordContract | TaggedRecordContract,
) -> dict[str, object]:
    if isinstance(contract, RecordContract):
        return {
            "kind": "record",
            "required_fields": sorted(contract.required_fields),
            "nullable_fields": sorted(contract.nullable_fields),
            "primary_key": contract.primary_key,
        }
    return {
        "kind": "tagged",
        "discriminator": contract.discriminator,
        "variants": [
            {"literal": literal, "contract": _record_contract_payload(variant)}
            for literal, variant in contract.variants
        ],
        "primary_key": contract.primary_key,
    }


def _artifact_contract_registry_payload() -> list[dict[str, object]]:
    return [
        {
            "order": contract.order,
            "filename": contract.filename,
            "schema_version": contract.schema_version,
            "format": contract.format,
            "primary_key": contract.primary_key,
            "row_order": contract.row_order,
            "record_contract": _record_contract_payload(contract.record_contract),
        }
        for contract in artifact_contracts()
    ]


def _artifact_contract_registry_sha256() -> str:
    return hashlib.sha256(
        canonical_json_bytes(_artifact_contract_registry_payload(), final_lf=True)
    ).hexdigest()


def _artifact_profile_payload(profile: ArtifactCardinalityProfile) -> dict[str, object]:
    return {
        "arm_runs": profile.arm_runs,
        "comparisons": profile.comparisons,
        "calibration_estimates": profile.calibration_estimates,
        "bootstrap_rows": profile.bootstrap_rows,
        "sign_flip_rows": profile.sign_flip_rows,
        "bootstrap_replicates_per_contrast": profile.bootstrap_replicates_per_contrast,
        "sign_flip_replicates_per_hypothesis": profile.sign_flip_replicates_per_hypothesis,
        "canonical": profile.canonical,
    }


def _require_frozen_contracts(
    contracts: Sequence[ArtifactContract],
    *,
    expected_count: int,
) -> None:
    observed = tuple(contracts)
    expected = artifact_contracts()[:expected_count]
    if len(observed) != expected_count or observed != expected:
        raise ArtifactValidationError(
            "Artifact contracts differ structurally from the frozen registry."
        )


def _require_finalization_context(
    target: Path,
    contracts: Sequence[ArtifactContract],
    profile: ArtifactCardinalityProfile,
    *,
    finalization_scope: str,
) -> None:
    _require_frozen_contracts(contracts, expected_count=13)
    canonical_target = _normalized_output_directory(repository_root() / CANONICAL_OUTPUT_DIRECTORY)
    observed_target = _normalized_output_directory(target)
    if finalization_scope == CANONICAL_FINALIZATION_SCOPE:
        if profile != FROZEN_ARTIFACT_PROFILE or profile.canonical is not True:
            raise ArtifactValidationError(
                "Canonical finalization requires the exact frozen artifact profile."
            )
        if observed_target != canonical_target:
            raise ArtifactValidationError(
                "Canonical finalization requires the exact frozen output directory."
            )
        return
    if finalization_scope == VALIDATION_FINALIZATION_SCOPE:
        if profile.canonical is not False:
            raise ArtifactValidationError(
                "Validation-only finalization requires a noncanonical artifact profile."
            )
        if _is_reserved_lifecycle_family_path(observed_target, canonical_target):
            raise ArtifactValidationError(
                "Validation-only finalization cannot target the frozen lifecycle family."
            )
        return
    raise ArtifactValidationError("Finalization scope is unknown.")


def _normalized_output_directory(target: Path) -> str:
    absolute = os.path.normcase(os.fspath(target.resolve(strict=False)))
    return Path(absolute).as_posix()


def _is_reserved_lifecycle_family_path(observed: str, canonical: str) -> bool:
    """Keep the validation-only writer outside every Task-B-owned namespace."""

    observed_path = Path(observed)
    canonical_path = Path(canonical)
    try:
        relative = observed_path.relative_to(canonical_path.parent)
    except ValueError:
        return False
    if not relative.parts:
        return False
    root_name = os.path.normcase(relative.parts[0])
    canonical_name = os.path.normcase(canonical_path.name)
    return (
        root_name == canonical_name
        or root_name.startswith(canonical_name + os.path.normcase(".retry-"))
        or root_name.startswith(canonical_name + os.path.normcase(".rde-"))
    )


def _validated_writer_binding(
    receipt: ConsumedFinalizationAuthorization,
    target: Path,
    *,
    expected_phase: str,
    contracts: Sequence[ArtifactContract],
    profile: ArtifactCardinalityProfile,
    writer_claimed: bool = False,
    transient_paths: Sequence[Path] = (),
) -> dict[str, object]:
    _require_frozen_contracts(contracts, expected_count=len(contracts))
    binding = (
        claimed_finalization_receipt_binding(receipt, expected_phase=expected_phase)
        if writer_claimed
        else finalization_receipt_binding(receipt, expected_phase=expected_phase)
    )
    _require_exact_finalization_binding_fields(binding)
    if binding.get("authorization_version") != FINALIZATION_AUTHORIZATION_VERSION:
        raise ArtifactValidationError("Canonical writer receipt version differs.")
    if binding.get("canonical_output_directory") != _normalized_output_directory(target):
        raise ArtifactValidationError("Canonical writer target differs from the receipt binding.")
    finalization_scope = binding.get("finalization_scope")
    if not isinstance(finalization_scope, str):
        raise ArtifactValidationError("Canonical writer receipt lacks finalization scope.")
    _require_finalization_context(
        target,
        artifact_contracts(),
        profile,
        finalization_scope=finalization_scope,
    )
    if binding.get("artifact_contract_registry_sha256") != (_artifact_contract_registry_sha256()):
        raise ArtifactValidationError("Canonical writer contract registry differs.")
    if binding.get("artifact_cardinality_profile") != _artifact_profile_payload(profile):
        raise ArtifactValidationError("Canonical writer artifact profile differs.")
    _validate_binding_static_semantics(binding)
    issued_operational = _require_issued_operational_binding(binding)
    _require_current_actual_state(
        binding,
        target,
        transient_paths=transient_paths,
        operational=issued_operational,
        authorized_output_directory=(expected_phase != "authorization_consumed"),
    )
    return binding


def _validate_binding_static_semantics(binding: Mapping[str, object]) -> None:
    actual = binding.get("actual_finalization_state")
    if not isinstance(actual, Mapping):
        raise ArtifactValidationError("Canonical writer receipt lacks actual-state provenance.")
    protocol = actual.get("protocol")
    if not isinstance(protocol, Mapping):
        raise ArtifactValidationError("Canonical writer actual state lacks protocol provenance.")
    expected = {
        "design_checkpoint": protocol.get("design_checkpoint_commit"),
        "source_design_sha256": actual.get("source_design_sha256"),
        "source_checkpoint_identity": SOURCE_CHECKPOINT,
        "implementation_tree_sha256": actual.get("implementation_tree_sha256"),
        "implementation_diff_sha256": actual.get("implementation_diff_sha256"),
    }
    for field, value in expected.items():
        if binding.get(field) != value:
            raise ArtifactValidationError(
                f"Canonical writer binding {field} differs from trusted actual state."
            )
    if actual.get("normalized_output_directory") != binding.get("canonical_output_directory"):
        raise ArtifactValidationError(
            "Canonical writer normalized output directory differs from trusted actual state."
        )
    finalization_scope = binding.get("finalization_scope")
    if not isinstance(finalization_scope, str):
        raise ArtifactValidationError("Canonical writer receipt lacks finalization scope.")
    _require_clean_actual_state(actual)


def _require_issued_operational_binding(
    binding: Mapping[str, object],
) -> AssemblyOperationalProvenance:
    payload = binding.get("operational_provenance")
    if not isinstance(payload, Mapping):
        raise ArtifactValidationError("Canonical writer receipt lacks operational provenance.")
    for identity, issued in tuple(_ISSUED_OPERATIONAL_PROVENANCE.items()):
        operational = issued.operational
        if (
            _ISSUED_OPERATIONAL_PROVENANCE.get(identity) is issued
            and _is_exact_issued_operational_provenance(operational)
            and dict(payload) == _operational_provenance_payload(operational)
            and binding.get("operational_provenance_sha256")
            == _operational_provenance_sha256(operational)
        ):
            _issued_executor_for_operational(operational)
            return operational
    raise ArtifactValidationError(
        "Canonical writer operational provenance was not issued by reconstruction."
    )


def _require_current_actual_state(
    binding: Mapping[str, object],
    target: Path,
    *,
    transient_paths: Sequence[Path] = (),
    operational: AssemblyOperationalProvenance | None = None,
    authorized_output_directory: bool = False,
) -> None:
    bound_actual = binding.get("actual_finalization_state")
    if not isinstance(bound_actual, Mapping):
        raise ArtifactValidationError("Canonical writer receipt lacks actual-state provenance.")
    issued_operational = operational or _require_issued_operational_binding(binding)
    actual = _reconstruct_actual_finalization_state(
        target,
        transient_paths=transient_paths,
        authorized_output_directory=authorized_output_directory,
        executor_attestation=_issued_executor_for_operational(issued_operational),
    )
    if actual.get("design_matches_checkpoint") is not True:
        raise ArtifactValidationError("Canonical writer observed changed frozen design bytes.")
    if actual.get("protected_source_matches") is not True:
        raise ArtifactValidationError("Canonical writer observed changed protected source.")
    finalization_scope = binding.get("finalization_scope")
    if not isinstance(finalization_scope, str):
        raise ArtifactValidationError("Canonical writer receipt lacks finalization scope.")
    _require_clean_actual_state(actual)
    if dict(bound_actual) != actual:
        raise ArtifactValidationError("Actual Git or runtime state changed after authorization.")
    if binding.get("implementation_tree_sha256") != actual["implementation_tree_sha256"]:
        raise ArtifactValidationError("Writer implementation tree differs from its receipt.")
    if binding.get("implementation_diff_sha256") != actual["implementation_diff_sha256"]:
        raise ArtifactValidationError("Writer implementation diff differs from its receipt.")


def _validate_promoted_graph_binding(
    graph: CanonicalArtifactGraph,
    binding: Mapping[str, object],
    receipt: ConsumedFinalizationAuthorization,
    *,
    expected_phase: str,
) -> None:
    audits = finalization_receipt_audit_results(receipt, expected_phase=expected_phase)
    scientific = {artifact.contract.filename: artifact.scientific for artifact in graph.artifacts}
    _validate_finalization_authorization(scientific, audits)
    if finalization_plan_binding_sha256(scientific, graph.profile) != binding.get(
        "audit_certificate_plan_sha256"
    ):
        raise ArtifactValidationError(
            "Canonical writer plan or profile differs from its audited certificate."
        )
    expected_hashes = binding.get("scientific_payload_sha256")
    if not isinstance(expected_hashes, Mapping):
        raise ArtifactValidationError("Canonical writer receipt lacks scientific identities.")
    observed_hashes = {
        artifact.contract.filename: artifact.scientific_payload_sha256
        for artifact in graph.artifacts
    }
    if observed_hashes != dict(expected_hashes):
        raise ArtifactValidationError(
            "Canonical writer scientific payload differs from its receipt."
        )
    _validate_authorized_content_hashes(graph, binding)
    gate = cast(Mapping[str, object], graph.artifact("gate_evaluations.json").scientific)
    if gate.get("evaluation_id") != binding.get("study_identity"):
        raise ArtifactValidationError("Canonical writer study identity differs from its receipt.")
    run_rows = cast(Sequence[Mapping[str, object]], scientific["arm_runs.jsonl"])
    ordered_run_identity = hashlib.sha256(
        canonical_json_bytes(
            [row.get("run_id") for row in run_rows],
            final_lf=True,
        )
    ).hexdigest()
    if ordered_run_identity != binding.get("ordered_run_identity_sha256"):
        raise ArtifactValidationError("Canonical writer run identity differs from its receipt.")
    gate_rows = cast(Sequence[Mapping[str, object]], gate.get("gates", ()))
    integrity = next(
        (row.get("gate_status") for row in gate_rows if row.get("gate_id") == "G-INTEGRITY"),
        None,
    )
    if integrity != binding.get("g_integrity"):
        raise ArtifactValidationError("Canonical writer G-INTEGRITY differs from its receipt.")
    decision = {
        "branch_id": gate.get("final_branch_id"),
        "branch_trace": gate.get("final_branch_trace"),
        "gate_status": gate.get("final_gate_status"),
        "recommendation": gate.get("recommendation"),
    }
    if decision != binding.get("provisional_decision"):
        raise ArtifactValidationError(
            "Canonical writer provisional decision differs from its receipt."
        )
    actual = cast(Mapping[str, object], binding["actual_finalization_state"])
    protocol_operational = graph.artifact("protocol_snapshot.json").operational
    if protocol_operational != dict(cast(Mapping[str, object], actual["protocol"])):
        raise ArtifactValidationError("Canonical writer source identity differs from actual state.")
    trusted = cast(Mapping[str, object], binding["operational_provenance"])
    audit_operational = graph.artifact("audit_results.json").operational
    for field in ("historical_before_sha256", "historical_after_sha256"):
        if audit_operational[field] != trusted[field]:
            raise ArtifactValidationError(
                f"Canonical writer {field} differs from the authorized provenance."
            )


def _validate_authorized_content_hashes(
    graph: CanonicalArtifactGraph,
    binding: Mapping[str, object],
) -> None:
    expected_content_hashes = binding.get("artifact_content_sha256")
    if not isinstance(expected_content_hashes, Mapping):
        raise ArtifactValidationError("Canonical writer receipt lacks content identities.")
    observed_content_hashes = {
        artifact.contract.filename: artifact.content_sha256 for artifact in graph.artifacts[:11]
    }
    if observed_content_hashes != dict(expected_content_hashes):
        raise ArtifactValidationError(
            "Canonical writer artifact bytes differ from the authorization-time bytes."
        )


def _validate_manifest_operational_binding(
    graph: CanonicalArtifactGraph,
    binding: Mapping[str, object],
) -> None:
    actual = cast(Mapping[str, object], binding["actual_finalization_state"])
    trusted = cast(Mapping[str, object], binding["operational_provenance"])
    operational = graph.artifact("run_manifest.json").operational
    expected = {
        "implementation_commit": actual["implementation_commit"],
        "implementation_tree_sha256": actual["implementation_tree_sha256"],
        "implementation_diff_sha256": actual["implementation_diff_sha256"],
        "implementation_tree_clean": actual["implementation_tree_clean"],
        "started_at": trusted["started_at"],
        "completed_at": trusted["completed_at"],
        "dependency_versions": actual["dependency_versions"],
        "machine": actual["machine"],
    }
    for field, value in expected.items():
        if operational[field] != value:
            raise ArtifactValidationError(
                f"Manifest {field} differs from trusted actual-state provenance."
            )


def _validate_atomic_content(
    target: Path,
    filename: str,
    content: bytes,
    binding: Mapping[str, object],
    contracts: Sequence[ArtifactContract],
    profile: ArtifactCardinalityProfile,
    transient_paths: Sequence[Path] = (),
) -> None:
    if not isinstance(content, bytes):
        raise ArtifactValidationError("Canonical atomic content must be exact bytes.")
    if filename == "run_manifest.json":
        names = tuple(contract.filename for contract in contracts[:11])
        persisted = _read_exact_artifacts(target, names, transient_paths=transient_paths)
        audited = decode_and_validate_audited_artifacts(
            persisted,
            contracts[:11],
            profile=profile,
        )
        receipt_hashes = binding.get("scientific_payload_sha256")
        if not isinstance(receipt_hashes, Mapping) or {
            artifact.contract.filename: artifact.scientific_payload_sha256
            for artifact in audited.artifacts
        } != dict(receipt_hashes):
            raise ArtifactValidationError("Manifest writer input differs from its receipt.")
        _validate_authorized_content_hashes(audited, binding)
        persisted[filename] = content
        graph = decode_and_validate_manifest_artifacts(
            persisted,
            contracts[:12],
            profile=profile,
        )
        _validate_manifest_operational_binding(graph, binding)
        return
    names = tuple(contract.filename for contract in contracts[:12])
    persisted = _read_exact_artifacts(target, names, transient_paths=transient_paths)
    persisted[filename] = content
    graph = decode_and_validate_artifacts(persisted, contracts, profile=profile)
    receipt_hashes = binding.get("scientific_payload_sha256")
    if not isinstance(receipt_hashes, Mapping) or {
        artifact.contract.filename: artifact.scientific_payload_sha256
        for artifact in graph.artifacts[:11]
    } != dict(receipt_hashes):
        raise ArtifactValidationError("Recommendation writer input differs from its receipt.")
    _validate_authorized_content_hashes(graph, binding)
    gate = cast(Mapping[str, object], graph.artifact("gate_evaluations.json").scientific)
    if gate.get("evaluation_id") != binding.get("study_identity"):
        raise ArtifactValidationError("Recommendation writer study differs from its receipt.")
    _validate_manifest_operational_binding(graph, binding)


def _promote_scientific_artifacts(
    target: Path,
    artifacts: Mapping[str, bytes],
    contracts: Sequence[ArtifactContract],
    profile: ArtifactCardinalityProfile,
    *,
    receipt: ConsumedFinalizationAuthorization,
) -> None:
    _require_frozen_contracts(contracts, expected_count=11)
    binding = _validated_writer_binding(
        receipt,
        target,
        expected_phase="authorization_consumed",
        contracts=contracts,
        profile=profile,
    )
    expected_names = tuple(contract.filename for contract in contracts)
    if tuple(artifacts) != expected_names:
        raise ArtifactValidationError("Scientific promotion requires exact artifacts 1-11.")
    graph = decode_and_validate_audited_artifacts(artifacts, contracts, profile=profile)
    _validate_promoted_graph_binding(
        graph,
        binding,
        receipt,
        expected_phase="authorization_consumed",
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    claim_finalization_receipt_writer(receipt, expected_phase="authorization_consumed")
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{target.name}.artifacts-1-11.",
            suffix=".incomplete",
            dir=target.parent,
        )
    )
    try:
        for name in expected_names:
            (staging / name).write_bytes(artifacts[name])
        staged = _read_exact_artifacts(staging, expected_names)
        if staged != dict(artifacts):
            raise ArtifactValidationError(
                "Reopened staged scientific bytes differ before promotion."
            )
        staged_graph = decode_and_validate_audited_artifacts(staged, contracts, profile=profile)
        _validate_promoted_graph_binding(
            staged_graph,
            binding,
            receipt,
            expected_phase="authorization_consumed",
        )
        _publish_claimed_canonical_entry(
            target,
            staging,
            target,
            receipt=receipt,
            expected_phase="authorization_consumed",
            contracts=contracts,
            profile=profile,
            expected_artifacts=artifacts,
        )
    except Exception:
        _remove_incomplete_entry(staging)
        raise


def _derive_manifest_from_promoted_artifacts(
    target: Path,
    receipt: ConsumedFinalizationAuthorization,
    contracts: Sequence[ArtifactContract],
    profile: ArtifactCardinalityProfile,
) -> bytes:
    _require_frozen_contracts(contracts, expected_count=13)
    binding = _validated_writer_binding(
        receipt,
        target,
        expected_phase="scientific_artifacts_promoted",
        contracts=contracts,
        profile=profile,
    )
    if not target.is_dir() or (target / "run_manifest.json").exists():
        raise ArtifactValidationError("Manifest construction requires promoted artifacts only.")
    names = tuple(contract.filename for contract in contracts[:11])
    promoted = _read_exact_artifacts(target, names)
    graph = decode_and_validate_audited_artifacts(promoted, contracts[:11], profile=profile)
    _validate_promoted_graph_binding(
        graph,
        binding,
        receipt,
        expected_phase="scientific_artifacts_promoted",
    )
    promoted_scientific = {
        artifact.contract.filename: artifact.scientific for artifact in graph.artifacts
    }
    manifest_scientific = derive_manifest_scientific_payload(promoted_scientific)
    artifact_content_sha256, artifact_scientific_payload_sha256 = _promoted_artifact_hashes(graph)
    gate = cast(Mapping[str, object], promoted_scientific["gate_evaluations.json"])
    recommendation_identity = recommendation_scientific_payload_identity(gate)
    audit_operational = graph.artifact("audit_results.json").operational
    trusted_operational = cast(
        Mapping[str, object],
        binding["operational_provenance"],
    )
    actual = cast(Mapping[str, object], binding["actual_finalization_state"])
    manifest_operational = {
        "implementation_commit": actual["implementation_commit"],
        "implementation_tree_sha256": actual["implementation_tree_sha256"],
        "implementation_diff_sha256": actual["implementation_diff_sha256"],
        "implementation_tree_clean": actual["implementation_tree_clean"],
        "started_at": trusted_operational["started_at"],
        "completed_at": trusted_operational["completed_at"],
        "dependency_versions": dict(cast(Mapping[str, str], actual["dependency_versions"])),
        "machine": dict(cast(Mapping[str, str], actual["machine"])),
        "artifact_content_sha256": artifact_content_sha256,
        "artifact_scientific_payload_sha256": artifact_scientific_payload_sha256,
        "historical_before_sha256": dict(
            cast(Mapping[str, str], audit_operational["historical_before_sha256"])
        ),
        "historical_after_sha256": dict(
            cast(Mapping[str, str], audit_operational["historical_after_sha256"])
        ),
        "recommendation_scientific_payload_sha256": recommendation_identity,
    }
    return _serialize(
        contracts[11],
        manifest_scientific,
        source_hash=load_protocol_snapshot().source_design_sha256,
        operational=manifest_operational,
    )


def _promoted_artifact_hashes(
    graph: CanonicalArtifactGraph,
) -> tuple[dict[str, str], dict[str, str]]:
    """Derive manifest identities only from decoded, reopened artifacts 1-11."""

    return (
        {artifact.contract.filename: artifact.content_sha256 for artifact in graph.artifacts},
        {
            artifact.contract.filename: artifact.scientific_payload_sha256
            for artifact in graph.artifacts
        },
    )


def _derive_recommendation_from_persisted_manifest(
    target: Path,
    receipt: ConsumedFinalizationAuthorization,
    contracts: Sequence[ArtifactContract],
    profile: ArtifactCardinalityProfile,
) -> bytes:
    _require_frozen_contracts(contracts, expected_count=13)
    binding = _validated_writer_binding(
        receipt,
        target,
        expected_phase="manifest_persisted",
        contracts=contracts,
        profile=profile,
    )
    if not target.is_dir() or not (target / "run_manifest.json").is_file():
        raise ArtifactValidationError("Recommendation construction requires a persisted manifest.")
    if (target / "recommendation.json").exists():
        raise ArtifactValidationError("Recommendation already exists before final construction.")
    names = tuple(contract.filename for contract in contracts[:12])
    persisted = _read_exact_artifacts(target, names)
    graph = decode_and_validate_manifest_artifacts(persisted, contracts[:12], profile=profile)
    _validate_authorized_content_hashes(graph, binding)
    _validate_manifest_operational_binding(graph, binding)
    gate = cast(
        Mapping[str, object],
        graph.artifact("gate_evaluations.json").scientific,
    )
    recommendation_scientific = derive_recommendation_scientific_payload(gate)
    return _serialize(
        contracts[12],
        recommendation_scientific,
        source_hash=load_protocol_snapshot().source_design_sha256,
        operational={
            "run_manifest_content_sha256": graph.artifact("run_manifest.json").content_sha256
        },
    )


def _verify_constructed_recommendation_commitment(
    target: Path,
    recommendation: bytes,
    receipt: ConsumedFinalizationAuthorization,
    contracts: Sequence[ArtifactContract],
    profile: ArtifactCardinalityProfile,
) -> None:
    """Verify constructed recommendation bytes against the persisted manifest commitment."""

    _require_frozen_contracts(contracts, expected_count=13)
    binding = _validated_writer_binding(
        receipt,
        target,
        expected_phase="manifest_persisted",
        contracts=contracts,
        profile=profile,
    )
    names = tuple(contract.filename for contract in contracts[:12])
    proposed = _read_exact_artifacts(target, names)
    proposed[contracts[12].filename] = recommendation
    graph = decode_and_validate_artifacts(proposed, contracts, profile=profile)
    _validate_authorized_content_hashes(graph, binding)
    _validate_manifest_operational_binding(graph, binding)
    expected_identity = cast(
        str,
        graph.artifact("run_manifest.json").operational["recommendation_scientific_payload_sha256"],
    )
    observed_identity = graph.artifact("recommendation.json").scientific_payload_sha256
    if observed_identity != expected_identity:
        raise ArtifactValidationError(
            "Constructed recommendation differs from the persisted manifest commitment."
        )


def _atomic_create(
    target: Path,
    filename: str,
    content: bytes,
    *,
    receipt: ConsumedFinalizationAuthorization,
    contracts: Sequence[ArtifactContract],
    profile: ArtifactCardinalityProfile,
) -> None:
    _require_frozen_contracts(contracts, expected_count=13)
    phase_by_filename = {
        "run_manifest.json": "scientific_artifacts_promoted",
        "recommendation.json": "manifest_persisted",
    }
    expected_phase = phase_by_filename.get(filename)
    if expected_phase is None:
        raise ArtifactValidationError("Atomic canonical creation requires a frozen final artifact.")
    binding = _validated_writer_binding(
        receipt,
        target,
        expected_phase=expected_phase,
        contracts=contracts,
        profile=profile,
    )
    destination = target / filename
    _validate_atomic_content(
        target,
        filename,
        content,
        binding,
        contracts,
        profile,
        transient_paths=(destination,),
    )
    claim_finalization_receipt_writer(receipt, expected_phase=expected_phase)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{filename}.",
        suffix=".incomplete",
        dir=target,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.is_symlink() or not temporary.is_file():
            raise ArtifactValidationError(
                "Canonical staging entry is not an ordinary regular file."
            )
        reopened = temporary.read_bytes()
        if reopened != content:
            raise ArtifactValidationError(
                "Reopened canonical staging bytes differ before creation."
            )
        _validate_atomic_content(
            target,
            filename,
            reopened,
            binding,
            contracts,
            profile,
            transient_paths=(temporary, destination),
        )
        _publish_claimed_canonical_entry(
            target,
            temporary,
            destination,
            receipt=receipt,
            expected_phase=expected_phase,
            contracts=contracts,
            profile=profile,
            expected_content=content,
        )
    except Exception:
        with suppress(OSError):
            os.close(descriptor)
        _remove_incomplete_entry(temporary)
        raise


def _publish_claimed_canonical_entry(
    target: Path,
    staging: Path,
    destination: Path,
    *,
    receipt: ConsumedFinalizationAuthorization,
    expected_phase: str,
    contracts: Sequence[ArtifactContract],
    profile: ArtifactCardinalityProfile,
    expected_content: bytes | None = None,
    expected_artifacts: Mapping[str, bytes] | None = None,
) -> None:
    """Lowest canonical writer: validate a claimed receipt and publish without clobber."""

    binding = _validated_writer_binding(
        receipt,
        target,
        expected_phase=expected_phase,
        contracts=contracts,
        profile=profile,
        writer_claimed=True,
        transient_paths=(staging, destination),
    )
    if os.path.lexists(destination):
        raise CanonicalCreateOnceError(
            f"{CANONICAL_CREATE_ONCE_ERROR}: canonical destination already exists: {destination}"
        )
    file_publication = expected_content is not None and expected_artifacts is None
    directory_publication = expected_content is None and expected_artifacts is not None
    if file_publication:
        if destination.parent != target or staging.is_symlink() or not staging.is_file():
            raise ArtifactValidationError(
                "Canonical file staging entry changed before publication."
            )
        reopened = staging.read_bytes()
        if reopened != expected_content:
            raise ArtifactValidationError(
                "Canonical file staging bytes changed before publication."
            )
        _validate_atomic_content(
            target,
            destination.name,
            reopened,
            binding,
            contracts,
            profile,
            transient_paths=(staging, destination),
        )
    elif directory_publication:
        if destination != target or staging.is_symlink() or not staging.is_dir():
            raise ArtifactValidationError(
                "Scientific staging entry changed before directory publication."
            )
        expected_names = tuple(contract.filename for contract in contracts)
        reopened_artifacts = _read_exact_artifacts(staging, expected_names)
        if reopened_artifacts != dict(expected_artifacts or {}):
            raise ArtifactValidationError(
                "Reopened staged scientific bytes differ before publication."
            )
        staged_graph = decode_and_validate_audited_artifacts(
            reopened_artifacts,
            contracts,
            profile=profile,
        )
        _validate_promoted_graph_binding(
            staged_graph,
            binding,
            receipt,
            expected_phase=expected_phase,
        )
    else:
        raise ArtifactValidationError("Canonical publication requires exactly one entry kind.")

    _require_current_actual_state(
        binding,
        target,
        transient_paths=(staging, destination),
        authorized_output_directory=(expected_phase != "authorization_consumed"),
    )
    try:
        if os.name == "nt":
            os.rename(staging, destination)
        elif sys.platform.startswith("linux"):
            library = ctypes.CDLL(None, use_errno=True)
            renameat2 = library.renameat2
            renameat2.argtypes = (
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            )
            renameat2.restype = ctypes.c_int
            result = renameat2(
                -100,
                os.fsencode(staging),
                -100,
                os.fsencode(destination),
                1,
            )
            if result != 0:
                error_number = ctypes.get_errno()
                raise OSError(error_number, os.strerror(error_number), destination)
        elif sys.platform == "darwin":
            library = ctypes.CDLL(None, use_errno=True)
            renamex_np = library.renamex_np
            renamex_np.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
            renamex_np.restype = ctypes.c_int
            result = renamex_np(os.fsencode(staging), os.fsencode(destination), 4)
            if result != 0:
                error_number = ctypes.get_errno()
                raise OSError(error_number, os.strerror(error_number), destination)
        else:
            raise OSError(
                errno.ENOTSUP,
                "Atomic exclusive canonical publication is unsupported on this platform.",
                destination,
            )
    except OSError as error:
        if error.errno in {errno.EEXIST, errno.ENOTEMPTY} or os.path.lexists(destination):
            raise CanonicalCreateOnceError(
                f"{CANONICAL_CREATE_ONCE_ERROR}: canonical destination already exists: "
                f"{destination}"
            ) from error
        raise ArtifactValidationError(
            f"Atomic exclusive canonical publication failed: {error}"
        ) from error

    if file_publication:
        if destination.is_symlink() or not destination.is_file():
            raise ArtifactValidationError("Published canonical file is not an ordinary file.")
        if destination.read_bytes() != expected_content:
            raise ArtifactValidationError("Published canonical file bytes differ from staging.")
    else:
        if destination.is_symlink() or not destination.is_dir():
            raise ArtifactValidationError("Published canonical directory is not ordinary.")
        published = _read_exact_artifacts(
            destination,
            tuple(contract.filename for contract in contracts),
        )
        if published != dict(expected_artifacts or {}):
            raise ArtifactValidationError("Published scientific artifacts differ from staging.")
        decode_and_validate_audited_artifacts(published, contracts, profile=profile)
    publish_finalization_receipt_writer(receipt, expected_phase=expected_phase)


def _remove_incomplete_entry(path: Path) -> None:
    if not os.path.lexists(path):
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    if path.is_dir():
        for child in path.iterdir():
            if child.is_symlink() or child.is_file():
                child.unlink()
            else:
                raise ArtifactValidationError(
                    "Canonical staging cleanup encountered an unexpected nested directory."
                )
        path.rmdir()


def _read_exact_artifacts(
    target: Path,
    names: Sequence[str],
    *,
    transient_paths: Sequence[Path] = (),
) -> dict[str, bytes]:
    expected = set(names)
    transient = {path.resolve(strict=False) for path in transient_paths}
    entries = tuple(
        path for path in target.iterdir() if path.resolve(strict=False) not in transient
    )
    invalid = sorted(path.name for path in entries if path.is_symlink() or not path.is_file())
    if invalid:
        raise ArtifactValidationError(
            f"Canonical stage contains non-regular or symlink entries: {invalid}"
        )
    observed = {path.name for path in entries}
    unexpected = observed - expected
    if unexpected:
        raise ArtifactValidationError(
            f"Canonical stage contains unexpected artifacts: {sorted(unexpected)}"
        )
    missing = tuple(name for name in names if not (target / name).is_file())
    if missing:
        raise ArtifactValidationError(f"Canonical stage lacks required artifacts: {missing}")
    return {name: (target / name).read_bytes() for name in names}


def _emit_validation_failure(
    target: Path,
    error: Exception,
) -> None:
    """Emit noncanonical failure evidence without creating the canonical directory."""

    target.parent.mkdir(parents=True, exist_ok=True)
    failure_path = target.parent / "validation_failure.json"
    if failure_path.exists():
        return
    details: dict[str, object] = {
        "phase": "canonical-finalization",
        "error_code": getattr(error, "error_code", type(error).__name__),
        "path": target.as_posix(),
        "message": str(error),
        "context": {"canonical_finalization": "prohibited"},
    }
    payload = {
        "schema_version": "validation-failure/v1",
        **details,
        "details_sha256": protocol_hash("validation_failure_details/v1", details),
    }
    temporary = failure_path.with_suffix(".json.tmp")
    temporary.write_bytes(canonical_json_bytes(payload, final_lf=True))
    temporary.replace(failure_path)


def _validate_finalization_authorization(
    scientific: Mapping[str, object],
    audit_results: Sequence[IntegrityAuditResult],
) -> None:
    """Bind canonical finalization to the complete executed audit sequence."""

    specifications = load_protocol_snapshot().registry("audit").records()
    expected_ids = tuple(item["audit_id"] for item in specifications)
    actual_ids = tuple(item.audit_id for item in audit_results)
    if actual_ids != expected_ids:
        raise ArtifactValidationError(
            "Canonical finalization requires A01 through A16 in frozen order."
        )
    if any(item.status != "PASS" for item in audit_results):
        raise ArtifactValidationError(
            "Failed or unresolved audits prohibit canonical finalization."
        )
    document = scientific.get("audit_results.json")
    if not isinstance(document, Mapping):
        raise ArtifactValidationError(
            "Canonical finalization requires the executed audit artifact."
        )
    rows = document.get("audits")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ArtifactValidationError("Canonical finalization audit rows are malformed.")
    expected_rows = tuple(
        {
            "audit_id": specification["audit_id"],
            "audit_order": int(specification["audit_order"]),
            "expected": specification["requirement"],
            "observed": result.observed,
            "status": result.status,
            "audit_detail_sha256": protocol_hash(
                "audit_detail/v1",
                {
                    "audit_id": specification["audit_id"],
                    "expected": specification["requirement"],
                    "observed": result.observed,
                },
            ),
        }
        for specification, result in zip(specifications, audit_results, strict=True)
    )
    actual_rows = tuple(cast(Sequence[Mapping[str, object]], rows))
    if actual_rows != expected_rows:
        raise ArtifactValidationError("Stored audit claims differ from the executed audit results.")
    if document.get("all_passed") is not True:
        raise ArtifactValidationError("Canonical finalization requires all_passed=true.")


def _serialize(
    contract: ArtifactContract,
    scientific: object,
    *,
    source_hash: str,
    operational: Mapping[str, object],
) -> bytes:
    if contract.format == "JSON":
        if not isinstance(scientific, Mapping):
            raise TypeError(f"{contract.filename} scientific payload must be an object.")
        return serialize_json_artifact(
            schema_version=contract.schema_version,
            source_design_sha256=source_hash,
            scientific_fields=cast(Mapping[str, object], scientific),
            operational_fields=operational,
        )
    if not isinstance(scientific, Sequence) or isinstance(scientific, (str, bytes)):
        raise TypeError(f"{contract.filename} scientific payload must be ordered rows.")
    rows = cast(Sequence[Mapping[str, object]], scientific)
    if contract.format == "JSONL":
        return serialize_jsonl_artifact(
            schema_version=contract.schema_version,
            source_design_sha256=source_hash,
            rows=rows,
        )
    return serialize_csv_artifact(
        schema_version=contract.schema_version,
        source_design_sha256=source_hash,
        rows=rows,
    )


def _scientific_payload_hash(
    contract: ArtifactContract, scientific: object, source_hash: str
) -> str:
    temporary = _serialize(
        contract,
        scientific,
        source_hash=source_hash,
        operational=(
            {
                field: _placeholder_operational(field)
                for field in _operational_fields(contract.filename)
            }
            if contract.format == "JSON"
            else {}
        ),
    )
    if contract.format == "JSON":
        document = cast(dict[str, object], json.loads(temporary))
        return cast(str, document["scientific_payload_sha256"])
    first_line = temporary.splitlines()[0]
    if contract.format == "JSONL":
        metadata = cast(dict[str, object], json.loads(first_line))
        return cast(str, metadata["scientific_payload_sha256"])
    row = next(csv.DictReader(io.StringIO(temporary.decode("utf-8"))))
    return row["scientific_payload_sha256"]


def _operational_fields(filename: str) -> frozenset[str]:
    from research_decision_engine.benchmarks.broader_artifact_graph import OPERATIONAL_FIELDS

    return OPERATIONAL_FIELDS.get(filename, frozenset())


def _placeholder_operational(field: str) -> object:
    if field.endswith("_sha256"):
        return "0" * 64
    if field in {"design_checkpoint_commit", "design_git_blob_oid", "implementation_commit"}:
        return "0" * 40
    if field.endswith("_clean"):
        return True
    if field.endswith("_at"):
        return "2000-01-01T00:00:00.000000Z"
    return {}
