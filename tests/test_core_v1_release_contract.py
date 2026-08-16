from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import tomllib
import types
import unicodedata
import zipfile
from collections.abc import Callable, Mapping
from email import policy
from email.message import Message
from email.parser import BytesParser
from importlib import metadata as importlib_metadata
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import cast
from urllib.parse import unquote, urlsplit

import pytest

import research_decision_engine
from research_decision_engine import (
    RunSpec,
    RunSpecV2,
    RunSpecV3,
    replay_run_bundle,
    replay_run_bundle_v2,
    replay_run_bundle_v3,
    verify_run_bundle,
    verify_run_bundle_v2,
    verify_run_bundle_v3,
)
from research_decision_engine.core_contract import (
    CorePublicApiManifestError,
    build_public_api_manifest,
    canonical_json_bytes,
    load_public_api_manifest,
    parse_public_api_manifest_bytes,
    resolve_import_path,
    verify_packaged_manifest_matches_live,
)
from research_decision_engine.core_fixtures import (
    FIXTURE_DIRECTORY,
    build_expected_fixture_files,
    build_fixture_manifest,
    load_fixture_manifest,
    verify_packaged_fixtures,
)
from research_decision_engine.core_release_check import (
    canonical_release_check_json,
    execute_release_checks,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "research-decision-engine"
PACKAGE_VERSION = "1.0.0rc5"
PUBLIC_PROJECT_IDENTITY = "RolandLin0724"
LICENSE_EXPRESSION = "Apache-2.0"
LICENSE_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
DIST_INFO = f"research_decision_engine-{PACKAGE_VERSION}.dist-info"
SDIST_ROOT = f"research_decision_engine-{PACKAGE_VERSION}"
UV_VERSION = "0.11.32"
UV_BUILD_REQUIREMENT = f"uv_build=={UV_VERSION}"
UV_LOCK_NORMALIZED_SHA256 = "7d34b9c652e388fe46930ac4352aaad8836f1d91ac8f76b5f5a2987e3446b0f2"
OPENING_UV_LOCK_NORMALIZED_SHA256 = (
    "0442838ed0f5dfeb225825400a084701b6dbc0b622d0529cc3e1525fd0a4abe5"
)
# Frozen from the candidate package tree; only Python source EOLs are normalized.
CANDIDATE_PACKAGE_NORMALIZED_TREE_SHA256 = (
    "795dcdebf8396e99493293109d31a2dac5861c49683b88a9653a8660302e2761"
)
PUBLIC_API_MANIFEST_SHA256 = "b6a16f25ede5060d08674bc22baf0282e92cceb15569384e6e3be93a190bfad0"
OPENING_PUBLIC_API_MANIFEST_SHA256 = (
    "637eb71743b32a08276bd80243967c7c009eb898abacebda7c9281e0bd2d44f5"
)
FIXTURE_MANIFEST_SHA256 = "aaa19ca680c449e956ad08caab8358a4cd1f17d71bb41ebbffde942ad071b626"
OPENING_FIXTURE_MANIFEST_SHA256 = "40f924d79f8713b89285fd45ebf9dbaae5cbd0e43a8ab085db362ed10e4377f6"
PROTECTED_DOCUMENT_BLOB_CONTRACT = {
    "DESIGN.md": {
        "mode": "100644",
        "oid": "38e79b83ee1f9ee06511d2127bba7a380f65863f",
        "byte_count": 29001,
        "sha256": "c3b562e8d58c7cbbd469f9dff6d4766430d2515e8443cd896d766eadf8634bad",
        "crlf_sha256": "d91b9d377011d1d99a8c40c107d8d153b081d0a06989e0a5c7145ef0c5bf3ef7",
    },
    "PLAN.md": {
        "mode": "100644",
        "oid": "3652b975528a6bd8cace6f9ce93e059748d23319",
        "byte_count": 5833,
        "sha256": "255b527b0b087ed99bf2718b71adf0a9541047161bc420cecf73f3a87a56f26d",
        "crlf_sha256": "e8eccc3b84acec80e543762580152659fab192a96537abde7aac3d14beb6f3f3",
    },
    "SPEC.md": {
        "mode": "100644",
        "oid": "be40b9ad2d6628b32e0263c3a1828b4ccc56b9b7",
        "byte_count": 9763,
        "sha256": "37368a5b557b8918cd1576f8370d69b867b9ecc3319439e6fcf92cdd1e91b7f2",
        "crlf_sha256": "0562db29a10d087519511a1cba0e70006b6cce0fb6df54ac95a05cfa1ca4f4e6",
    },
}
EXPECTED_FROZEN_SOURCE_SHA256 = {
    "research_decision_engine/policies.py": (
        "98c0ecf1528287bc36797e3e14d46d9f28dee8982ac59b6795067c34599ed366"
    ),
    "research_decision_engine/decision.py": (
        "1c028f7544ca59196844e8a6c550a786bb60ca90bfa87a779442359ca750f6d6"
    ),
    "research_decision_engine/lookahead.py": (
        "a039c5b4ad8a5fed303465f10109285c6a46b84226c277550fa49a2df2dbb629"
    ),
    "research_decision_engine/reasoning.py": (
        "d0bdccb3d3bbbbce24db285f45fb26027f07056962d55ebc11d536e1a47456ff"
    ),
    "research_decision_engine/optimizer_effect.py": (
        "724505faef2a86e0564aa62108b116020a77f6876dbc9468ebcd199d0cd65de7"
    ),
    "research_decision_engine/evidence_eligibility.py": (
        "ac58eb1f08b0f90b23c177c6ff1262ab2871c18fd6bf22dbe0fab2904ead44fe"
    ),
    "research_decision_engine/belief_models.py": (
        "2b022592c6c7cb5ce52de69e27fc05dc806369aceef339a466669d5d462b78a3"
    ),
    "research_decision_engine/calibration.py": (
        "18702a0772ceab15aad3a02ecc8e11503cf11958f5b12bbca3e833f8e0d115fd"
    ),
    "research_decision_engine/benchmarks/worlds.py": (
        "377bedbe41ff97fe6a5c12232f6c9d2a9d1793868c253cfb837dc77f2f2215a5"
    ),
    "research_decision_engine/benchmarks/paired_evaluation.py": (
        "c901d00e1f08b9ab92cef00a4e3e34dc7b74999cc7459677eaa08f925c51f2c4"
    ),
}
EXPECTED_FROZEN_DESIGN_SHA256 = {
    "AGENTS.md": "c37b098c9239e7deae5d6f0fe04f001618de0abab5a4c7df68ebf63fa94e9649",
    "SPEC.md": PROTECTED_DOCUMENT_BLOB_CONTRACT["SPEC.md"]["sha256"],
    "PLAN.md": PROTECTED_DOCUMENT_BLOB_CONTRACT["PLAN.md"]["sha256"],
    "DESIGN.md": PROTECTED_DOCUMENT_BLOB_CONTRACT["DESIGN.md"]["sha256"],
    "LOOKAHEAD_DESIGN.md": "2df72c43c9fc1880b805ca789816eba271126a118b91a5394b5463d2d076cc5c",
    "ROBUST_BELIEF_DESIGN.md": "8cffeffeeac79ada7dcb66eb3b96bb418b60eec55fa90a485a514a9abe893666",
    "CLOSED_LOOP_EVALUATION_DESIGN.md": (
        "b418981fcd8df7993652d5cc7495a4066aabc2ea64e5559e565f95866544da3d"
    ),
}
PUBLIC_DOCUMENT_LINK_EDGE_COUNT = 80
PUBLIC_DOCUMENT_LINK_EDGE_SHA256 = (
    "1987483050a6de073c457234fef72ca8abf1091287f01dee2c154eb3e575ee44"
)
PUBLIC_PACKAGE_PATHS = frozenset(
    {
        "research_decision_engine/__init__.py",
        "research_decision_engine/adapters.py",
        "research_decision_engine/belief_models.py",
        "research_decision_engine/benchmarks/__init__.py",
        "research_decision_engine/benchmarks/broader_analysis.py",
        "research_decision_engine/benchmarks/broader_artifact_graph.py",
        "research_decision_engine/benchmarks/broader_artifacts.py",
        "research_decision_engine/benchmarks/broader_assembly.py",
        "research_decision_engine/benchmarks/broader_audits.py",
        "research_decision_engine/benchmarks/broader_calibration_evidence.py",
        "research_decision_engine/benchmarks/broader_calibration_history.py",
        "research_decision_engine/benchmarks/broader_calibration_selector_replay.py",
        "research_decision_engine/benchmarks/broader_conformance.py",
        "research_decision_engine/benchmarks/broader_execution.py",
        "research_decision_engine/benchmarks/broader_lifecycle.py",
        "research_decision_engine/benchmarks/broader_lifecycle_io.py",
        "research_decision_engine/benchmarks/broader_lifecycle_records.py",
        "research_decision_engine/benchmarks/broader_oracle.py",
        "research_decision_engine/benchmarks/broader_pipeline.py",
        "research_decision_engine/benchmarks/broader_projection.py",
        "research_decision_engine/benchmarks/broader_protocol.py",
        "research_decision_engine/benchmarks/broader_returned_run.py",
        "research_decision_engine/benchmarks/broader_runner.py",
        "research_decision_engine/benchmarks/broader_smoke.py",
        "research_decision_engine/benchmarks/broader_statistics.py",
        "research_decision_engine/benchmarks/broader_validation.py",
        "research_decision_engine/benchmarks/broader_validation_evidence.py",
        "research_decision_engine/benchmarks/broader_worlds.py",
        "research_decision_engine/benchmarks/closed_loop_evaluation.py",
        "research_decision_engine/benchmarks/closed_loop_reporting.py",
        "research_decision_engine/benchmarks/divergence_audit.py",
        "research_decision_engine/benchmarks/divergence_reporting.py",
        "research_decision_engine/benchmarks/evaluation.py",
        "research_decision_engine/benchmarks/paired_evaluation.py",
        "research_decision_engine/benchmarks/paired_reporting.py",
        "research_decision_engine/benchmarks/reporting.py",
        "research_decision_engine/benchmarks/robust_evaluation.py",
        "research_decision_engine/benchmarks/robust_reporting.py",
        "research_decision_engine/benchmarks/worlds.py",
        "research_decision_engine/calibration.py",
        "research_decision_engine/cli.py",
        "research_decision_engine/closed_loop.py",
        "research_decision_engine/command_adapter.py",
        "research_decision_engine/core-fixtures-v1/belief-lineage-v3.json",
        "research_decision_engine/core-fixtures-v1/core-opening-nodeids.txt",
        "research_decision_engine/core-fixtures-v1/core-test-nodeids.txt",
        "research_decision_engine/core-fixtures-v1/decisions-rationales-v1.json",
        "research_decision_engine/core-fixtures-v1/evidence-model-fingerprint-v1.json",
        "research_decision_engine/core-fixtures-v1/evidence-model-v1.json",
        "research_decision_engine/core-fixtures-v1/fixture-manifest.json",
        "research_decision_engine/core-fixtures-v1/public-api-manifest.json",
        "research_decision_engine/core-fixtures-v1/replay-terminal-summaries-v1.json",
        "research_decision_engine/core-fixtures-v1/run-bundle-v1/run-bundle.json",
        "research_decision_engine/core-fixtures-v1/run-bundle-v1/run-bundle.json.sha256",
        "research_decision_engine/core-fixtures-v1/run-bundle-v2/run-bundle.json",
        "research_decision_engine/core-fixtures-v1/run-bundle-v2/run-bundle.json.sha256",
        "research_decision_engine/core-fixtures-v1/run-bundle-v3/run-bundle.json",
        "research_decision_engine/core-fixtures-v1/run-bundle-v3/run-bundle.json.sha256",
        "research_decision_engine/core-fixtures-v1/run-spec-v1.json",
        "research_decision_engine/core-fixtures-v1/run-spec-v2.json",
        "research_decision_engine/core-fixtures-v1/run-spec-v3.json",
        "research_decision_engine/core-fixtures-v1/sqlite-schema-v1.json",
        "research_decision_engine/core-fixtures-v1/sqlite-schema-v2.json",
        "research_decision_engine/core-fixtures-v1/sqlite-schema-v3.json",
        "research_decision_engine/core-fixtures-v1/sqlite-schema-v4.json",
        "research_decision_engine/core-fixtures-v1/sqlite-schema-v5.json",
        "research_decision_engine/core-fixtures-v1/sqlite-schema-v6.json",
        "research_decision_engine/core-public-api-v1.json",
        "research_decision_engine/core_contract.py",
        "research_decision_engine/core_fixtures.py",
        "research_decision_engine/core_release_check.py",
        "research_decision_engine/decision.py",
        "research_decision_engine/evidence_eligibility.py",
        "research_decision_engine/generic_policies.py",
        "research_decision_engine/information_gain_table.py",
        "research_decision_engine/lookahead.py",
        "research_decision_engine/optimizer_effect.py",
        "research_decision_engine/policies.py",
        "research_decision_engine/policy_contracts.py",
        "research_decision_engine/reasoning.py",
        "research_decision_engine/robust_storage.py",
        "research_decision_engine/run_bundle.py",
        "research_decision_engine/run_bundle_v2.py",
        "research_decision_engine/run_bundle_v3.py",
        "research_decision_engine/run_spec.py",
        "research_decision_engine/run_spec_v2.py",
        "research_decision_engine/run_spec_v3.py",
        "research_decision_engine/runner.py",
        "research_decision_engine/storage.py",
        "research_decision_engine/types.py",
        "research_decision_engine/world.py",
    }
)
PROHIBITED_LEGAL_NAME_CASEFOLD_SHA256 = (
    "b1cd1b7cf7b7a244489bc921c80adefac0781a4785a8dc17e277c0dbf7e236ec"
)
PROHIBITED_LEGAL_NAME_CHARACTER_COUNT = 4
PUBLIC_DOCUMENT_PATHS = frozenset(
    {
        "CHANGELOG.md",
        "CHANGELOG.zh-CN.md",
        "CORE_V1_COMPATIBILITY.md",
        "CORE_V1_COMPATIBILITY.zh-CN.md",
        "README.md",
        "README.zh-CN.md",
        "SECURITY.md",
        "SECURITY.zh-CN.md",
        "TESTING.md",
        "docs/command-adapter.md",
        "docs/faq.md",
        "docs/privacy-release-gate.md",
        "docs/python-function-adapter.md",
        "docs/replay.md",
        "docs/release-notes/1.0.0rc3.md",
        "docs/run-bundle.md",
        "docs/run-spec.md",
        "docs/troubleshooting.md",
        "docs/zh-CN/command-adapter.md",
        "docs/zh-CN/faq.md",
        "docs/zh-CN/privacy-release-gate.md",
        "docs/zh-CN/python-function-adapter.md",
        "docs/zh-CN/replay.md",
        "docs/zh-CN/release-notes/1.0.0rc3.md",
        "docs/zh-CN/run-bundle.md",
        "docs/zh-CN/run-spec.md",
        "docs/zh-CN/troubleshooting.md",
    }
)
UV_BUILD_SOURCE_INCLUDE = (
    "CHANGELOG.md",
    "CHANGELOG.zh-CN.md",
    "CORE_V1_COMPATIBILITY.md",
    "CORE_V1_COMPATIBILITY.zh-CN.md",
    "README.zh-CN.md",
    "SECURITY.md",
    "SECURITY.zh-CN.md",
    "TESTING.md",
    "docs/command-adapter.md",
    "docs/faq.md",
    "docs/privacy-release-gate.md",
    "docs/python-function-adapter.md",
    "docs/replay.md",
    "docs/release-notes/1.0.0rc3.md",
    "docs/run-bundle.md",
    "docs/run-spec.md",
    "docs/troubleshooting.md",
    "docs/zh-CN/command-adapter.md",
    "docs/zh-CN/faq.md",
    "docs/zh-CN/privacy-release-gate.md",
    "docs/zh-CN/python-function-adapter.md",
    "docs/zh-CN/replay.md",
    "docs/zh-CN/release-notes/1.0.0rc3.md",
    "docs/zh-CN/run-bundle.md",
    "docs/zh-CN/run-spec.md",
    "docs/zh-CN/troubleshooting.md",
)
UV_BUILD_SOURCE_EXCLUDE = ("/.gitignore",)
SDIST_BUILD_METADATA_PATHS = frozenset({"LICENSE", "PKG-INFO", "pyproject.toml"})
C7_NEW_PUBLIC_DOCUMENT_PATHS = frozenset(
    {
        "CHANGELOG.md",
        "CHANGELOG.zh-CN.md",
        "CORE_V1_COMPATIBILITY.zh-CN.md",
        "docs/release-notes/1.0.0rc3.md",
        "docs/zh-CN/release-notes/1.0.0rc3.md",
    }
)
RC5_NEW_PUBLIC_DOCUMENT_PATHS = frozenset(
    {
        "docs/release-notes/1.0.0rc5.md",
        "docs/zh-CN/release-notes/1.0.0rc5.md",
    }
)
RC5_CHANGED_MARKDOWN_PATHS = frozenset(
    {
        "CHANGELOG.md",
        "CHANGELOG.zh-CN.md",
        "CORE_V1_COMPATIBILITY.md",
        "CORE_V1_COMPATIBILITY.zh-CN.md",
        "README.md",
        "README.zh-CN.md",
        "docs/release-notes/1.0.0rc3.md",
        "docs/release-notes/1.0.0rc5.md",
        "docs/zh-CN/release-notes/1.0.0rc3.md",
        "docs/zh-CN/release-notes/1.0.0rc5.md",
    }
)
RC4_POLICY_PATHS = (
    "SECURITY.md",
    "SECURITY.zh-CN.md",
    "docs/privacy-release-gate.md",
    "docs/zh-CN/privacy-release-gate.md",
)
RC5_AUTHORIZED_CHANGED_PATHS = (
    ".gitattributes",
    "BROADER_REPLICATION_DESIGN.md",
    "BROADER_REPLICATION_LIFECYCLE_DIAGNOSTIC_AMENDMENT.md",
    "BROADER_REPLICATION_LIFECYCLE_DIAGNOSTIC_DECISION.md",
    "BROADER_REPLICATION_STAGE2_ORDER_RESOLUTION_AMENDMENT.md",
    "BROADER_REPLICATION_VALIDATION_EVIDENCE_BINDING_AMENDMENT.md",
    "CHANGELOG.md",
    "CHANGELOG.zh-CN.md",
    "CORE_V1_COMPATIBILITY.md",
    "CORE_V1_COMPATIBILITY.zh-CN.md",
    "README.md",
    "README.zh-CN.md",
    "docs/release-notes/1.0.0rc3.md",
    "docs/release-notes/1.0.0rc5.md",
    "docs/zh-CN/release-notes/1.0.0rc3.md",
    "docs/zh-CN/release-notes/1.0.0rc5.md",
    "pyproject.toml",
    "research_decision_engine/__init__.py",
    "research_decision_engine/benchmarks/broader_assembly.py",
    "research_decision_engine/benchmarks/broader_execution.py",
    "research_decision_engine/benchmarks/broader_lifecycle.py",
    "research_decision_engine/benchmarks/broader_oracle.py",
    "research_decision_engine/benchmarks/broader_protocol.py",
    "research_decision_engine/benchmarks/broader_validation.py",
    "research_decision_engine/benchmarks/broader_validation_evidence.py",
    "research_decision_engine/core-fixtures-v1/fixture-manifest.json",
    "research_decision_engine/core-fixtures-v1/public-api-manifest.json",
    "research_decision_engine/core-public-api-v1.json",
    "tests/p2_calibration_evidence_architecture_guard.py",
    "tests/test_broader_checkpoint_split.py",
    "tests/test_broader_lifecycle_records.py",
    "tests/test_broader_p2_calibration_evidence_architecture.py",
    "tests/test_broader_p2_execution_evidence_foundations.py",
    "tests/test_broader_p2_executor_attestation.py",
    "tests/test_broader_p2_result_aggregates.py",
    "tests/test_core_v1_release_contract.py",
    "tests/test_public_api.py",
    "tests/test_v1_v2_v3_compatibility.py",
    "uv.lock",
)
RC5_INTERNAL_ONLY_REMEDIATION_PATHS = (
    "BROADER_REPLICATION_LIFECYCLE_DIAGNOSTIC_AMENDMENT.md",
    "BROADER_REPLICATION_LIFECYCLE_DIAGNOSTIC_DECISION.md",
    "BROADER_REPLICATION_STAGE2_ORDER_RESOLUTION_AMENDMENT.md",
    "BROADER_REPLICATION_VALIDATION_EVIDENCE_BINDING_AMENDMENT.md",
)
RC5_PRODUCT_APPLICABLE_REMEDIATION_PATHS = tuple(
    path for path in RC5_AUTHORIZED_CHANGED_PATHS if path not in RC5_INTERNAL_ONLY_REMEDIATION_PATHS
)
RC5_INTERNAL_EXCLUDE_PATHS = (
    "BROADER_REPLICATION_LIFECYCLE_DIAGNOSTIC_AMENDMENT.md",
    "BROADER_REPLICATION_LIFECYCLE_DIAGNOSTIC_DECISION.md",
    "BROADER_REPLICATION_STAGE2F_P3_REPLAY_AUTHORITY_AMENDMENT.md",
    "BROADER_REPLICATION_STAGE2F_P4_PUBLIC_SURFACE_TRANSITION_AMENDMENT.md",
    "BROADER_REPLICATION_STAGE2_ORDER_RESOLUTION_AMENDMENT.md",
    "BROADER_REPLICATION_V1_TRUST_BOUNDARY_AMENDMENT.md",
    "BROADER_REPLICATION_VALIDATION_EVIDENCE_BINDING_AMENDMENT.md",
    "broader-replication-smoke-v2/smoke_validation.json",
    "divergence-audit-v1-189-cases/DIVERGENCE_AUDIT_REPORT.md",
    "divergence-audit-v1-189-cases/divergence_cases.csv",
    "divergence-audit-v1-189-cases/divergence_cases.jsonl",
    "divergence-audit-v1-189-cases/harm_concentration.csv",
    "divergence-audit-v1-189-cases/mechanism_by_condition.csv",
    "divergence-audit-v1-189-cases/mechanism_summary.csv",
    "divergence-audit-v1-189-cases/planner_compatibility_audit.json",
    "divergence-audit-v1-189-cases/score_decomposition.csv",
    "divergence-audit-v1-189-cases/sequence_comparison.csv",
)
RC5_SOURCE_TRACKED_PATH_COUNT = 296
RC5_PRODUCT_TRACKED_PATH_COUNT = 279
RC5_SOURCE_PATH_SET_SHA256 = "26eb1c07dcc691af4e602709f75aca916d5eb1f88892cc6d6da26c45ce93529a"
RC5_PRODUCT_PATH_SET_SHA256 = "33cbb31c21938660788b3abc77ab7125e9ea42101659daafe8037955b24950d5"
RC5_SANITIZED_PRODUCT_ROOT_OID = "80244e7a1652e62937f789c243aac829be167cbd"
RC5_SELF_HOSTING_REPAIR_PATH = "tests/test_core_v1_release_contract.py"
RC6_GOVERNANCE_PARENT_OID = "b67a2a49f673d8ffc8ec463f50d49d022d5f5b29"
RC6_GOVERNANCE_ANCESTRY_LENGTH = 3
RC6_GOVERNANCE_CHANGED_PATHS = (
    ".github/workflows/core-v1.yml",
    "CHANGELOG.md",
    "CHANGELOG.zh-CN.md",
    "CORE_V1_COMPATIBILITY.md",
    "CORE_V1_COMPATIBILITY.zh-CN.md",
    "README.md",
    "README.zh-CN.md",
    "SECURITY.md",
    "SECURITY.zh-CN.md",
    "docs/privacy-release-gate.md",
    "docs/release-notes/1.0.0rc5.md",
    "docs/zh-CN/privacy-release-gate.md",
    "docs/zh-CN/release-notes/1.0.0rc5.md",
    "tests/test_core_v1_ci_workflow.py",
    "tests/test_core_v1_release_contract.py",
)
RC6_GOVERNANCE_FROZEN_PAYLOAD_ROOTS = (
    "LICENSE",
    "pyproject.toml",
    "research_decision_engine/",
    "uv.lock",
)
PUBLIC_PROVENANCE_ROLE_TOKEN_SCHEMA = "rde-core-public-provenance-role-token/v1"
PUBLIC_PROVENANCE_ROLE_TOKEN_NAMESPACE = "RDE_CORE_PUBLIC_PROVENANCE_ROLE_V1"
PUBLIC_PROVENANCE_ROLE_TOKENS = {
    "EVIDENCE_CONTRACT": "cbeea072ed39697e2cd42ca571685faed5f6ead8",
    "PROTOCOL": "89c0b4fadba33b9fd9a257b43eacf476b7779d59",
    "SOURCE_DESIGN": "ebd1591c7332544c8f991a34ef3936f2e048ca16",
}
PUBLIC_PROVENANCE_GIT_CONSUMER_PATHS = (
    "research_decision_engine/benchmarks/broader_assembly.py",
    "research_decision_engine/benchmarks/broader_execution.py",
    "research_decision_engine/benchmarks/broader_lifecycle.py",
    "research_decision_engine/benchmarks/broader_oracle.py",
    "research_decision_engine/benchmarks/broader_validation.py",
)
CI_NODEID_SCRATCH_PATHS = (
    ".core-v1-nodeids-1.txt",
    ".core-v1-nodeids-2.txt",
)
CORE_TEST_NODEIDS_PATH = "research_decision_engine/core-fixtures-v1/core-test-nodeids.txt"
C7_PUBLIC_BRAND_PATHS = (
    "DESIGN.md",
    "PLAN.md",
    "SPEC.md",
    "research_decision_engine/__init__.py",
    "research_decision_engine/benchmarks/__init__.py",
    "research_decision_engine/benchmarks/closed_loop_evaluation.py",
    "research_decision_engine/benchmarks/reporting.py",
    "research_decision_engine/cli.py",
)
WHEEL_ENTRY_POINTS = b"[console_scripts]\nrde = research_decision_engine.cli:main\n\n"
ZERO_PRIVACY_COUNTS = {
    "credential_values": 0,
    "legal_name": 0,
    "private_absolute_paths": 0,
    "private_email": 0,
    "raw_private_evidence_paths": 0,
}
COMMUNITY_HEALTH_PATHS = frozenset(
    {
        ".github/CONTRIBUTING.md",
        ".github/CONTRIBUTING.zh-CN.md",
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/ISSUE_TEMPLATE/documentation.md",
        ".github/ISSUE_TEMPLATE/feature_request.md",
        ".github/pull_request_template.md",
    }
)
ISSUE_TEMPLATE_PATHS = frozenset(
    {
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/ISSUE_TEMPLATE/documentation.md",
        ".github/ISSUE_TEMPLATE/feature_request.md",
    }
)
ISSUE_TEMPLATE_FRONTMATTER_KEYS = frozenset({"name", "about", "title", "labels", "assignees"})
CORE_WORKFLOW_PATH = ".github/workflows/core-v1.yml"
CORE_WORKFLOW_SHA256 = "b48afbd078a5e9869c9c4e7d820d7bdfea798c7863c2be2d77bab12d3b1320ac"
CONTRIBUTING_COMMANDS = (
    "uv lock --check",
    "uv sync --locked",
    "uv run ruff format --check .",
    "uv run ruff check .",
    "uv run mypy .",
    "uv run pytest",
    "uv run python -m research_decision_engine.core_release_check",
    "uv build",
)
CONTRIBUTING_SHARED_IDENTIFIERS = (
    "RDE Core",
    "RDE Continual Learning",
    "RDE Assurance",
    "RunSpec",
    "RunBundle",
    "SQLite",
    "replay",
    "uv_build",
    "Apache-2.0",
    "CLA",
    "DCO",
    "112",
    "121",
    "27",
    "v1",
    "v2",
    "v3",
)


def _normalized_payload_manifest_sha256(payloads: Mapping[str, bytes]) -> str:
    canonical = b"".join(
        relative_path.encode("utf-8")
        + b"\0"
        + hashlib.sha256(
            payloads[relative_path].replace(b"\r\n", b"\n")
            if PurePosixPath(relative_path).suffix == ".py"
            else payloads[relative_path]
        )
        .hexdigest()
        .encode("ascii")
        + b"\n"
        for relative_path in sorted(payloads)
    )
    return hashlib.sha256(canonical).hexdigest()


def _package_payloads(root: Path) -> dict[str, bytes]:
    package_root = root / "research_decision_engine"
    assert package_root.is_dir()
    payloads = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in package_root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.relative_to(package_root).parts
        and path.suffix.casefold() != ".pyc"
    }
    _assert_exact_path_inventory(frozenset(payloads), PUBLIC_PACKAGE_PATHS, "package")
    assert len(payloads) == 91
    assert _normalized_payload_manifest_sha256(payloads) == CANDIDATE_PACKAGE_NORMALIZED_TREE_SHA256
    return payloads


def _release_facing_paths() -> tuple[Path, ...]:
    _package_payloads(REPOSITORY_ROOT)
    relative_paths = frozenset(
        {
            *PUBLIC_PACKAGE_PATHS,
            *PUBLIC_DOCUMENT_PATHS,
            "LICENSE",
            "pyproject.toml",
        }
    )
    assert len(relative_paths) == 120
    paths = tuple(REPOSITORY_ROOT / relative_path for relative_path in sorted(relative_paths))
    assert all(path.is_file() for path in paths)
    assert len(paths) == len(set(paths))
    return paths


def _privacy_byte_views(payload: bytes) -> tuple[bytes, ...]:
    views = [payload]
    for offset in (0, 1):
        offset_payload = payload[offset:]
        paired_payload = offset_payload[: len(offset_payload) - (len(offset_payload) % 2)]
        for encoding in ("utf-16-le", "utf-16-be"):
            decoded = paired_payload.decode(encoding, errors="ignore").encode("utf-8")
            if decoded not in views:
                views.append(decoded)
    return tuple(views)


def _count_prohibited_legal_name(views: tuple[bytes, ...]) -> int:
    normalized_views = tuple(
        unicodedata.normalize("NFC", view.decode("utf-8", errors="ignore")).casefold()
        for view in views
    )

    count = 0
    for normalized in normalized_views:
        for token in re.findall(r"\w+", normalized, flags=re.UNICODE):
            for index in range(len(token) - PROHIBITED_LEGAL_NAME_CHARACTER_COUNT + 1):
                candidate = token[index : index + PROHIBITED_LEGAL_NAME_CHARACTER_COUNT]
                if (
                    hashlib.sha256(candidate.encode("utf-8")).hexdigest()
                    == PROHIBITED_LEGAL_NAME_CASEFOLD_SHA256
                ):
                    count += 1
    return count


def _privacy_scan_counts(payloads: Mapping[str, bytes]) -> dict[str, int]:
    credential_value_patterns = (
        re.compile(rb"AKIA[0-9A-Z]{16}"),
        re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
        re.compile(rb"github_pat_[A-Za-z0-9_]{20,}"),
        re.compile(rb"sk-[A-Za-z0-9]{20,}"),
        re.compile(rb"xox[baprs]-[A-Za-z0-9-]{10,}"),
        re.compile(rb"AIza[0-9A-Za-z_-]{20,}"),
        re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
        re.compile(rb"authorization\s*:\s*(?:bearer|basic)\s+\S+", re.IGNORECASE),
    )
    private_email = re.compile(
        rb"(?<![A-Z0-9._%+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
        re.IGNORECASE,
    )
    sensitive_assignments = (
        re.compile(
            rb"\b(?:api[_ -]?key|access[_ -]?token|auth[_ -]?token|password|passwd|secret|"
            rb"client[_ -]?secret)\b[\"']?[ \t]*[:=][ \t]*[\"']"
            rb"(?!example\b|placeholder\b|redacted\b|none\b|null\b)[^\"'\r\n]{4,}[\"']",
            re.IGNORECASE,
        ),
        re.compile(
            rb"\b(?:api[_ -]?key|access[_ -]?token|auth[_ -]?token|password|passwd|secret|"
            rb"client[_ -]?secret)\b[\"']?[ \t]*[:=][ \t]*(?![\"'])"
            rb"(?!(?:example|placeholder|redacted|none|null)\b)[^\s#,}\]]{4,}",
            re.IGNORECASE,
        ),
    )
    unc_private_path_pattern = (
        rb"(?<![:\\/])(?:"
        + rb"\\\\"
        + rb"|//)[^\\/\s()\[\]{}]+[\\/]+(?:"
        + rb"(?:Users|home|profiles)[\\/]+[^\\/\s()\[\]{}]+"
        + rb"|[^\\/\s()\[\]{}]+[\\/]+(?:Users|home|profiles)"
        + rb"[\\/]+[^\\/\s()\[\]{}]+)(?:[\\/]|\b)"
    )
    private_absolute_paths = (
        re.compile(rb"(?<![A-Z0-9])[A-Z]:[\\/]+Users[\\/]+", re.IGNORECASE),
        re.compile(unc_private_path_pattern, re.IGNORECASE),
        re.compile(rb"/mnt/[A-Z]/Users/[A-Z0-9._-]+(?:/|\b)", re.IGNORECASE),
        re.compile(rb"/home/[A-Za-z0-9._-]+(?:/|\b)"),
        re.compile(rb"/Users/[A-Za-z0-9._-]+(?:/|\b)"),
    )
    private_root_needles: set[bytes] = set()
    for variable in ("USERPROFILE", "HOME"):
        raw_root = os.environ.get(variable)
        if raw_root is None:
            continue
        private_root = raw_root.strip().rstrip("\\/")
        if len(private_root) < 4 or not Path(private_root).is_absolute():
            continue
        private_root_needles.update(
            {
                private_root.replace("\\", "/").casefold().encode("utf-8"),
                private_root.replace("/", "\\").casefold().encode("utf-8"),
            }
        )
    raw_evidence_fragments = (
        b"rde-" + b"core-v1-" + b"baseline",
        b"rde-" + b"recovery",
        b"rde-" + b"continuity",
        b"repository" + b".json",
        b"temp_clone" + b"_token",
    )
    git_auth_helper_pattern = re.compile(b"credential" + rb"[-_ ]helper", re.IGNORECASE)

    counts = dict(ZERO_PRIVACY_COUNTS)
    for payload in payloads.values():
        views = _privacy_byte_views(payload)
        counts["credential_values"] += sum(
            len(pattern.findall(view)) for view in views for pattern in credential_value_patterns
        ) + sum(len(pattern.findall(view)) for view in views for pattern in sensitive_assignments)
        counts["private_email"] += sum(len(private_email.findall(view)) for view in views)
        counts["legal_name"] += _count_prohibited_legal_name(views)
        counts["private_absolute_paths"] += sum(
            len(pattern.findall(view)) for view in views for pattern in private_absolute_paths
        ) + sum(view.lower().count(needle) for view in views for needle in private_root_needles)
        counts["raw_private_evidence_paths"] += sum(
            view.lower().count(fragment) for view in views for fragment in raw_evidence_fragments
        ) + sum(len(git_auth_helper_pattern.findall(view)) for view in views)
    return counts


def _assert_privacy_scan_clean(payloads: Mapping[str, bytes]) -> None:
    assert _privacy_scan_counts(payloads) == ZERO_PRIVACY_COUNTS


def _assert_private_checkout_absent(payloads: Mapping[str, bytes]) -> None:
    checkout = str(REPOSITORY_ROOT.resolve())
    assert len(checkout) > 3
    needles = {
        checkout.replace("\\", "/").casefold().encode("utf-8"),
        checkout.replace("/", "\\").casefold().encode("utf-8"),
    }
    for payload in payloads.values():
        folded = payload.lower()
        assert all(needle not in folded for needle in needles), (
            "private checkout disclosure detected"
        )


def _markdown_anchor_ids(path: Path) -> frozenset[str]:
    markdown = path.read_text(encoding="utf-8")
    anchors = set(
        re.findall(
            r"<a\b[^>]*\b(?:id|name)\s*=\s*[\"']([^\"']+)[\"'][^>]*>",
            markdown,
            flags=re.IGNORECASE,
        )
    )
    heading_counts: dict[str, int] = {}
    for line in markdown.splitlines():
        match = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match is None:
            continue
        heading = re.sub(r"<[^>]+>", "", match.group(1))
        slug = re.sub(r"[^\w\s-]", "", heading, flags=re.UNICODE).strip().casefold()
        slug = re.sub(r"\s+", "-", slug)
        if not slug:
            continue
        duplicate_index = heading_counts.get(slug, 0)
        heading_counts[slug] = duplicate_index + 1
        anchors.add(slug if duplicate_index == 0 else f"{slug}-{duplicate_index}")
    return frozenset(anchors)


def _local_markdown_link_targets(path: Path, root: Path) -> frozenset[Path]:
    markdown = path.read_text(encoding="utf-8")
    root_resolved = root.resolve()
    targets: set[Path] = set()
    for match in re.finditer(r"(?<!!)\[[^]]+\]\(([^)]+)\)", markdown):
        raw_destination = match.group(1).strip()
        if raw_destination.startswith("<"):
            closing_bracket = raw_destination.find(">")
            assert closing_bracket > 1, path
            destination = raw_destination[1:closing_bracket]
        else:
            destination = raw_destination.split(maxsplit=1)[0]
        parsed = urlsplit(destination)
        if parsed.scheme or parsed.netloc:
            continue
        assert not parsed.query, path
        relative_path = unquote(parsed.path, errors="strict")
        resolved = (path.parent / relative_path).resolve() if relative_path else path.resolve()
        assert resolved.is_relative_to(root_resolved), path
        assert resolved.is_file(), path
        if parsed.fragment:
            assert unquote(parsed.fragment, errors="strict") in _markdown_anchor_ids(resolved), path
        if relative_path:
            targets.add(resolved)
    return frozenset(targets)


def _assert_markdown_links_resolve(path: Path, root: Path = REPOSITORY_ROOT) -> None:
    _local_markdown_link_targets(path, root)


def _strict_markdown_text(path: Path) -> str:
    payload = path.read_bytes()
    assert payload
    assert not payload.startswith(b"\xef\xbb\xbf"), path
    assert b"\0" not in payload, path
    assert b"\r" not in payload, path
    assert payload.endswith(b"\n"), path
    assert not payload.endswith(b"\n\n"), path
    text = payload.decode("utf-8", errors="strict")
    assert text.encode("utf-8") == payload, path
    assert all(line.rstrip(" \t") == line for line in text.splitlines()), path

    open_fence: tuple[str, int] | None = None
    for line in text.splitlines():
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence is None:
            continue
        marker = fence.group(1)
        suffix = fence.group(2)
        if open_fence is None:
            open_fence = (marker[0], len(marker))
        elif marker[0] == open_fence[0] and len(marker) >= open_fence[1]:
            assert not suffix.strip(), path
            open_fence = None
    assert open_fence is None, path
    return text


def _frontmatter_scalar(raw_value: str, path: Path) -> str:
    raw_value = raw_value.strip()
    if not raw_value:
        return ""
    if raw_value.startswith('"'):
        value = json.loads(raw_value)
        assert isinstance(value, str), path
        return value
    if raw_value.startswith("'"):
        assert len(raw_value) >= 2 and raw_value.endswith("'"), path
        return raw_value[1:-1].replace("''", "'")
    assert not raw_value.startswith(("[", "{", "&", "*", "!", "|", ">")), path
    return raw_value


def _markdown_frontmatter(text: str, path: Path) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    assert lines and lines[0] == "---", path
    try:
        closing_index = lines.index("---", 1)
    except ValueError:
        raise AssertionError(f"unterminated issue-template frontmatter: {path.name}") from None

    fields: dict[str, str] = {}
    for line in lines[1:closing_index]:
        match = re.fullmatch(r"([a-z][a-z0-9_-]*):[ \t]*(.*)", line)
        assert match is not None, path
        key = match.group(1)
        assert key not in fields, path
        fields[key] = _frontmatter_scalar(match.group(2), path)
    assert frozenset(fields) == ISSUE_TEMPLATE_FRONTMATTER_KEYS, path
    assert closing_index == len(ISSUE_TEMPLATE_FRONTMATTER_KEYS) + 1, path
    assert fields["name"].strip(), path
    assert fields["about"].strip(), path
    assert fields["labels"] == "", path
    assert fields["assignees"] == "", path
    return fields, "\n".join(lines[closing_index + 1 :])


def _unchecked_markdown_checkboxes(text: str) -> tuple[str, ...]:
    checkboxes: list[str] = []
    current: list[str] | None = None
    for line in text.splitlines():
        match = re.match(r"^\s*-\s*\[ \]\s+(.+?)\s*$", line)
        if match is not None:
            if current is not None:
                checkboxes.append(" ".join(current).casefold())
            current = [match.group(1).strip()]
        elif current is not None and re.match(r"^\s{2,}\S", line):
            current.append(line.strip())
        elif current is not None:
            checkboxes.append(" ".join(current).casefold())
            current = None
    if current is not None:
        checkboxes.append(" ".join(current).casefold())
    return tuple(checkboxes)


def _assert_issue_template_contract(path: Path, text: str) -> None:
    fields, body = _markdown_frontmatter(text, path)
    display_text = " ".join((fields["name"], fields["about"], body))
    assert re.search(r"[A-Za-z]", display_text), path
    assert re.search(r"[\u3400-\u9fff]", display_text), path

    security_path = (REPOSITORY_ROOT / "SECURITY.md").resolve()
    assert security_path in _local_markdown_link_targets(path, REPOSITORY_ROOT), path
    checkboxes = _unchecked_markdown_checkboxes(body)
    assert checkboxes, path
    assert any(
        "security" in checkbox and ("not" in checkbox or "不是" in checkbox or "不应" in checkbox)
        for checkbox in checkboxes
    ), path
    assert any(
        "private" in checkbox
        and any(marker in checkbox for marker in ("api key", "credential", "secret", "token"))
        for checkbox in checkboxes
    ), path

    normalized_body = " ".join(body.casefold().split())
    body_marker_groups: dict[str, tuple[tuple[str, ...], ...]] = {
        "bug_report.md": (
            ("affected public api", "command"),
            ("package version", "exact commit"),
            ("source checkout", "installed wheel"),
            ("operating system",),
            ("python version",),
            ("minimal sanitized reproduction",),
            ("steps to reproduce",),
            ("expected result",),
            ("actual result",),
            ("public exception class",),
            ("sqlite", "runspec", "runbundle", "replay", "adapter"),
            ("relevant tests already run",),
        ),
        "feature_request.md": (
            ("problem statement",),
            ("real user scenario",),
            ("why this belongs in rde core",),
            ("alternatives considered",),
            ("public api",),
            ("runspec", "runbundle"),
            ("sqlite",),
            ("replay",),
            ("compatibility",),
            ("portability",),
            ("documentation",),
            ("external adapter", "separate package"),
        ),
        "documentation.md": (
            ("affected file or page",),
            ("english", "simplified chinese", "both"),
            ("inaccurate or unclear statement",),
            ("expected correction",),
            ("runnable example",),
            ("link", "anchor"),
            ("security", "trust-boundary"),
            ("sanitized reproduction",),
        ),
    }
    checkbox_marker_groups: dict[str, tuple[tuple[str, ...], ...]] = {
        "bug_report.md": (
            ("not a security vulnerability",),
            ("api key", "token", "credential", "private", "runbundle", "absolute path"),
            ("python 3.12", "otherwise"),
            ("searched existing issues",),
        ),
        "feature_request.md": (
            ("not reporting a security vulnerability",),
            ("secret", "private data"),
            ("gpu", "cluster", "web ui", "continual learning", "assurance"),
            ("backward compatibility",),
        ),
        "documentation.md": (
            ("credential", "private data"),
            ("both language versions",),
            ("not a private security report",),
        ),
    }
    assert path.name in body_marker_groups
    assert path.name in checkbox_marker_groups
    for markers in body_marker_groups[path.name]:
        assert all(marker in normalized_body for marker in markers), (path, markers)
    for markers in checkbox_marker_groups[path.name]:
        assert any(all(marker in checkbox for marker in markers) for checkbox in checkboxes), (
            path,
            markers,
        )


def _assert_contributing_guides_contract(
    community_text: Mapping[str, str],
) -> None:
    english_path = REPOSITORY_ROOT / ".github/CONTRIBUTING.md"
    chinese_path = REPOSITORY_ROOT / ".github/CONTRIBUTING.zh-CN.md"
    security_path = (REPOSITORY_ROOT / "SECURITY.md").resolve()
    english = community_text[english_path.relative_to(REPOSITORY_ROOT).as_posix()]
    chinese = community_text[chinese_path.relative_to(REPOSITORY_ROOT).as_posix()]

    english_targets = _local_markdown_link_targets(english_path, REPOSITORY_ROOT)
    chinese_targets = _local_markdown_link_targets(chinese_path, REPOSITORY_ROOT)
    assert chinese_path.resolve() in english_targets
    assert english_path.resolve() in chinese_targets
    assert security_path in english_targets
    assert security_path in chinese_targets
    assert "CONTRIBUTING.zh-CN.md" in "\n".join(english.splitlines()[:12])
    assert "CONTRIBUTING.md" in "\n".join(chinese.splitlines()[:12])

    documented_commands = tuple(
        frozenset(command for command in CONTRIBUTING_COMMANDS if command in text)
        for text in (english, chinese)
    )
    assert documented_commands == (
        frozenset(CONTRIBUTING_COMMANDS),
        frozenset(CONTRIBUTING_COMMANDS),
    )
    documented_identifiers = tuple(
        frozenset(
            identifier
            for identifier in CONTRIBUTING_SHARED_IDENTIFIERS
            if identifier in " ".join(text.split())
        )
        for text in (english, chinese)
    )
    assert documented_identifiers == (
        frozenset(CONTRIBUTING_SHARED_IDENTIFIERS),
        frozenset(CONTRIBUTING_SHARED_IDENTIFIERS),
    )
    assert "pre-release" in english.casefold()
    assert "预发布" in chinese
    assert "private" in english.casefold()
    assert "私有" in chinese
    assert all(marker in english for marker in ("API key", "token", "credential"))
    assert all(marker in chinese for marker in ("API key", "token", "credential"))
    english_sections = tuple(line for line in english.splitlines() if line.startswith("## "))
    chinese_sections = tuple(line for line in chinese.splitlines() if line.startswith("## "))
    assert len(english_sections) == len(chinese_sections)
    assert len(english_sections) >= 10
    assert (
        "121 members: 91 package members, 27 public-document members, and 3 "
        "build/licensing members." in " ".join(english.split())
    )
    assert (
        "121 个 members： 91 个 package members、27 个 public-document members 和 3 个 "
        "build/licensing members。" in " ".join(chinese.split())
    )
    assert (
        ".github` community-health files are repository-only and are excluded from the sdist"
        in (" ".join(english.split()))
    )
    assert ".github` community-health files 仅属于仓库，并从 sdist 中排除" in (
        " ".join(chinese.split())
    )
    assert "121-member count is the current release contract" in " ".join(english.split())
    assert "121-member count 是当前 release contract" in " ".join(chinese.split())
    assert "116-member" not in english
    assert "116-member" not in chinese


def _assert_shared_markers(texts: tuple[str, str], markers: frozenset[str]) -> None:
    for text in texts:
        assert all(marker in text for marker in markers)


GIT_TOPOLOGY_ENVIRONMENT_NAMES = frozenset(
    {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CEILING_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_DISCOVERY_ACROSS_FILESYSTEM",
        "GIT_GRAFT_FILE",
        "GIT_INDEX_FILE",
        "GIT_NAMESPACE",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_OBJECT_DIRECTORY",
        "GIT_QUARANTINE_PATH",
        "GIT_REPLACE_REF_BASE",
        "GIT_SHALLOW_FILE",
        "GIT_WORK_TREE",
    }
)


def _git_output(cwd: Path, *arguments: str, environment: Mapping[str, str] | None = None) -> bytes:
    command_environment = dict(os.environ if environment is None else environment)
    for name in tuple(command_environment):
        if name in GIT_TOPOLOGY_ENVIRONMENT_NAMES or name.startswith("GIT_CONFIG_"):
            del command_environment[name]
    completed = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        env=command_environment,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, f"git command failed: {arguments!r}"
    return completed.stdout


def _path_set_sha256(paths: set[str]) -> str:
    return hashlib.sha256(
        b"".join(path.encode("utf-8", errors="strict") + b"\0" for path in sorted(paths))
    ).hexdigest()


def _governance_frozen_payload_paths(paths: set[str]) -> set[str]:
    return {
        path
        for path in paths
        if any(
            path == root or path.startswith(root) for root in RC6_GOVERNANCE_FROZEN_PAYLOAD_ROOTS
        )
    }


def _path_entry_exists(path: Path) -> bool:
    return os.path.lexists(path)


def _path_entry_is_redirect(path: Path) -> bool:
    if path.is_symlink() or path.is_junction():
        return True
    if not path.is_dir():
        return False
    for directory, directory_names, file_names in os.walk(path, followlinks=False):
        directory_path = Path(directory)
        for name in (*directory_names, *file_names):
            entry = directory_path / name
            if entry.is_symlink() or entry.is_junction():
                return True
    return False


def _release_document_committed_candidate_paths(
    repository: Path,
    *,
    git_output: Callable[..., bytes],
    path_entry_exists: Callable[[Path], bool] = _path_entry_exists,
    path_entry_is_redirect: Callable[[Path], bool] = _path_entry_is_redirect,
) -> tuple[str, set[str], set[str]]:
    def strict_oid(payload: bytes) -> str:
        match = re.fullmatch(rb"([0-9a-f]{40})\n", payload)
        assert match is not None
        return match.group(1).decode("ascii")

    def strict_path(payload: bytes) -> Path:
        assert payload.endswith(b"\n") and payload.count(b"\n") == 1
        path = Path(payload[:-1].decode("utf-8", errors="strict"))
        assert path.is_absolute()
        return path

    def parse_identity(header: bytes, kind: bytes) -> tuple[bytes, bytes]:
        match = re.fullmatch(
            kind + rb" ([^<>\r\n]+) <([^<>\r\n]+)> [0-9]+ [+-][0-9]{4}",
            header,
        )
        assert match is not None
        name, email = match.groups()
        assert name == name.strip() and email == email.strip()
        return name, email

    def parse_commit(oid: str) -> tuple[str, tuple[str, ...], tuple[bytes, bytes], bytes]:
        assert git_output(repository, "cat-file", "-t", oid) == b"commit\n"
        commit_payload = git_output(repository, "cat-file", "commit", oid)
        header_payload, separator, message = commit_payload.partition(b"\n\n")
        assert separator == b"\n\n"
        header_lines = header_payload.splitlines()
        assert header_lines
        tree_lines = [line for line in header_lines if line.startswith(b"tree")]
        assert len(tree_lines) == 1
        tree_match = re.fullmatch(rb"tree ([0-9a-f]{40})", tree_lines[0])
        assert tree_match is not None
        tree_oid = tree_match.group(1).decode("ascii")
        if tree_oid in PUBLIC_PROVENANCE_ROLE_TOKENS.values():
            raise AssertionError("public provenance role token cannot identify a tree")
        parent_oids: list[str] = []
        for line in header_lines:
            if line == b"parent" or line.startswith(b"parent "):
                parent_match = re.fullmatch(rb"parent ([0-9a-f]{40})", line)
                assert parent_match is not None
                parent_oids.append(parent_match.group(1).decode("ascii"))
        author_lines = [line for line in header_lines if line.startswith(b"author")]
        committer_lines = [line for line in header_lines if line.startswith(b"committer")]
        assert len(author_lines) == 1 and len(committer_lines) == 1
        assert len(header_lines) == 3 + len(parent_oids)
        author_identity = parse_identity(author_lines[0], b"author")
        committer_identity = parse_identity(committer_lines[0], b"committer")
        if author_identity != committer_identity:
            raise AssertionError("commit author and committer identity differ")
        assert len(parent_oids) == len(set(parent_oids))
        return tree_oid, tuple(parent_oids), author_identity, message

    assert git_output(repository, "rev-parse", "--is-shallow-repository") == b"false\n"
    assert git_output(repository, "replace", "-l") == b""
    git_dir = strict_path(
        git_output(repository, "rev-parse", "--path-format=absolute", "--git-dir")
    )
    common_dir = strict_path(
        git_output(repository, "rev-parse", "--path-format=absolute", "--git-common-dir")
    )
    objects_dir = strict_path(
        git_output(repository, "rev-parse", "--path-format=absolute", "--git-path", "objects")
    )
    grafts_path = strict_path(
        git_output(repository, "rev-parse", "--path-format=absolute", "--git-path", "info/grafts")
    )
    alternates_path = strict_path(
        git_output(
            repository,
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "objects/info/alternates",
        )
    )
    shallow_path = strict_path(
        git_output(repository, "rev-parse", "--path-format=absolute", "--git-path", "shallow")
    )
    assert os.path.normcase(os.path.abspath(git_dir)) == os.path.normcase(
        os.path.abspath(common_dir)
    )
    expected_objects_dir = common_dir / "objects"
    assert os.path.normcase(os.path.abspath(objects_dir)) == os.path.normcase(
        os.path.abspath(expected_objects_dir)
    )
    assert objects_dir.resolve().parent == common_dir.resolve()
    assert not path_entry_is_redirect(common_dir)
    assert not path_entry_is_redirect(objects_dir)
    assert not path_entry_exists(grafts_path)
    assert not path_entry_exists(alternates_path)
    assert not path_entry_exists(shallow_path)

    raw_head_oid = strict_oid(git_output(repository, "rev-parse", "--verify", "HEAD"))
    head_oid = strict_oid(git_output(repository, "rev-parse", "--verify", "HEAD^{commit}"))
    assert raw_head_oid == head_oid
    if head_oid in PUBLIC_PROVENANCE_ROLE_TOKENS.values():
        raise AssertionError("public provenance role token cannot identify HEAD")

    ancestry_payload = git_output(repository, "rev-list", "--parents", "--topo-order", head_oid)
    assert ancestry_payload.endswith(b"\n")
    ancestry_lines = ancestry_payload[:-1].split(b"\n")
    assert ancestry_lines and all(ancestry_lines)
    ancestry: list[tuple[str, tuple[str, ...]]] = []
    for line in ancestry_lines:
        match = re.fullmatch(rb"([0-9a-f]{40}(?: [0-9a-f]{40})*)", line)
        assert match is not None
        fields = match.group(1).decode("ascii").split(" ")
        oid, listed_parents = fields[0], tuple(fields[1:])
        if oid in PUBLIC_PROVENANCE_ROLE_TOKENS.values() or any(
            parent in PUBLIC_PROVENANCE_ROLE_TOKENS.values() for parent in listed_parents
        ):
            raise AssertionError("public provenance role token cannot enter Git ancestry")
        ancestry.append((oid, listed_parents))
    assert ancestry[0][0] == head_oid
    assert len({oid for oid, _parents in ancestry}) == len(ancestry)
    for index, (_oid, listed_parents) in enumerate(ancestry):
        expected_parents = () if index == len(ancestry) - 1 else (ancestry[index + 1][0],)
        assert listed_parents == expected_parents
    root_oid = ancestry[-1][0]
    roots_payload = git_output(repository, "rev-list", "--max-parents=0", head_oid)
    assert roots_payload == root_oid.encode("ascii") + b"\n"
    assert git_output(repository, "rev-list", "--count", head_oid) == (
        f"{len(ancestry)}\n".encode("ascii")
    )

    commit_contracts: dict[str, tuple[str, tuple[str, ...], tuple[bytes, bytes], bytes]] = {}
    tree_paths_by_commit: dict[str, set[str]] = {}
    for oid, listed_parents in ancestry:
        contract = parse_commit(oid)
        if contract[1] != listed_parents:
            raise AssertionError("commit parent headers disagree with complete ancestry")
        commit_contracts[oid] = contract
        tree_paths_by_commit[oid] = _nul_terminated_git_paths(
            git_output(
                repository,
                "ls-tree",
                "-r",
                "--full-tree",
                "--name-only",
                "-z",
                oid,
            )
        )

    tree_paths = tree_paths_by_commit[head_oid]
    parent_oids = ancestry[0][1]
    changed_paths: set[str] = set()
    if parent_oids:
        changed_paths = _nul_terminated_git_paths(
            git_output(
                repository,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                "-z",
                parent_oids[0],
                head_oid,
            )
        )

    if root_oid != RC5_SANITIZED_PRODUCT_ROOT_OID:
        assert len(parent_oids) == 1
        assert changed_paths
        assert len(tree_paths) == RC5_SOURCE_TRACKED_PATH_COUNT
        assert _path_set_sha256(tree_paths) == RC5_SOURCE_PATH_SET_SHA256
        assert set(RC5_AUTHORIZED_CHANGED_PATHS) <= tree_paths
        assert set(RC5_INTERNAL_ONLY_REMEDIATION_PATHS) <= tree_paths
        assert set(RC5_INTERNAL_EXCLUDE_PATHS) <= tree_paths
        return "FULL_PRIVATE_SOURCE_ONE_PARENT", tree_paths, changed_paths

    root_tree_paths = tree_paths_by_commit[root_oid]
    assert len(root_tree_paths) == RC5_PRODUCT_TRACKED_PATH_COUNT
    assert _path_set_sha256(root_tree_paths) == RC5_PRODUCT_PATH_SET_SHA256
    assert set(RC5_PRODUCT_APPLICABLE_REMEDIATION_PATHS) <= root_tree_paths
    assert set(RC5_INTERNAL_ONLY_REMEDIATION_PATHS).isdisjoint(root_tree_paths)
    assert set(RC5_INTERNAL_EXCLUDE_PATHS).isdisjoint(root_tree_paths)
    introduction_payload = git_output(
        repository,
        "diff-tree",
        "--root",
        "--no-commit-id",
        "--name-status",
        "-r",
        "-z",
        root_oid,
    )
    assert introduction_payload.endswith(b"\0")
    introduction_fields = introduction_payload[:-1].split(b"\0")
    assert introduction_fields and len(introduction_fields) % 2 == 0
    assert all(status == b"A" for status in introduction_fields[0::2])
    introduced_paths = [
        payload.decode("utf-8", errors="strict") for payload in introduction_fields[1::2]
    ]
    assert all(introduced_paths)
    assert len(introduced_paths) == len(set(introduced_paths))
    assert set(introduced_paths) == root_tree_paths

    root_identity = commit_contracts[root_oid][2]
    root_name, root_email = root_identity
    assert root_name
    assert (
        re.fullmatch(
            rb"(?:[0-9]+\+)?[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?"
            rb"@users\.noreply\.github\.com",
            root_email,
            flags=re.IGNORECASE,
        )
        is not None
    )
    for oid, _listed_parents in ancestry:
        _tree_oid, _parents, identity, message = commit_contracts[oid]
        if identity != root_identity:
            raise AssertionError("public descendant identity differs from sanitized root")
        if _privacy_scan_counts({"public-commit-message": message}) != ZERO_PRIVACY_COUNTS:
            raise AssertionError("public commit message privacy contract failed")
        if re.search(rb"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", message) is not None:
            raise AssertionError("public commit message contains a raw Git identity")
        if re.search(rb"\bPSC-[0-9]{2}\b", message) is not None:
            raise AssertionError("public commit message contains a controlled-source label")
        public_tree_paths = tree_paths_by_commit[oid]
        assert set(RC5_PRODUCT_APPLICABLE_REMEDIATION_PATHS) <= public_tree_paths
        assert set(RC5_INTERNAL_ONLY_REMEDIATION_PATHS).isdisjoint(public_tree_paths)
        assert set(RC5_INTERNAL_EXCLUDE_PATHS).isdisjoint(public_tree_paths)
    if len(ancestry) > 1:
        ancestry_changed_paths = _nul_terminated_git_paths(
            git_output(
                repository,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                "-z",
                root_oid,
                head_oid,
            )
        )
        if len(ancestry) == 2 and tree_paths == root_tree_paths:
            assert ancestry_changed_paths in (set(), {RC5_SELF_HOSTING_REPAIR_PATH})
        else:
            assert ancestry_changed_paths
    if changed_paths:
        _assert_privacy_scan_clean(
            {
                "public-descendant-paths": b"\0".join(
                    path.encode("utf-8", errors="strict") for path in sorted(changed_paths)
                )
            }
        )

    if head_oid == root_oid:
        assert len(ancestry) == 1 and not parent_oids
        return "SANITIZED_PRODUCT_ZERO_PARENT_ROOT", tree_paths, set()
    assert parent_oids
    if (
        len(ancestry) == RC6_GOVERNANCE_ANCESTRY_LENGTH
        and parent_oids[0] == RC6_GOVERNANCE_PARENT_OID
        and changed_paths
        and changed_paths <= set(RC6_GOVERNANCE_CHANGED_PATHS)
        and tree_paths == tree_paths_by_commit[parent_oids[0]]
        and changed_paths.isdisjoint(_governance_frozen_payload_paths(tree_paths))
    ):
        return "PUBLIC_GOVERNANCE_LINEAR_DESCENDANT", tree_paths, changed_paths
    return "SANITIZED_PRODUCT_LINEAR_DESCENDANT", tree_paths, changed_paths


def _nul_terminated_git_paths(payload: bytes) -> set[str]:
    if not payload:
        return set()
    assert payload.endswith(b"\0")
    encoded_paths = payload[:-1].split(b"\0")
    assert encoded_paths and all(encoded_paths)
    paths = [path.decode("utf-8", errors="strict") for path in encoded_paths]
    assert len(paths) == len(set(paths))
    for path in paths:
        pure_path = PurePosixPath(path)
        assert not pure_path.is_absolute()
        assert pure_path.parts
        assert all(part not in ("", ".", "..") for part in pure_path.parts)
        assert "\\" not in path
    return set(paths)


def _release_document_worktree_candidate_paths(
    repository: Path,
    *,
    git_output: Callable[..., bytes],
) -> tuple[set[str], set[str]]:
    unstaged_paths = _nul_terminated_git_paths(
        git_output(repository, "diff", "--name-only", "-z", "HEAD", "--")
    )
    staged_paths = _nul_terminated_git_paths(
        git_output(repository, "diff", "--cached", "--name-only", "-z", "--")
    )
    untracked_paths = _nul_terminated_git_paths(
        git_output(repository, "ls-files", "--others", "--exclude-standard", "-z")
    )
    candidate_paths = unstaged_paths | staged_paths | untracked_paths
    scratch_paths = set(CI_NODEID_SCRATCH_PATHS)

    assert all(PurePosixPath(path).parts == (path,) for path in CI_NODEID_SCRATCH_PATHS)
    if not scratch_paths <= untracked_paths:
        return candidate_paths, set()
    if scratch_paths & (unstaged_paths | staged_paths):
        return candidate_paths, set()
    if git_output(
        repository,
        "ls-files",
        "--cached",
        "-z",
        "--",
        *CI_NODEID_SCRATCH_PATHS,
    ):
        return candidate_paths, set()
    if git_output(
        repository,
        "ls-tree",
        "-r",
        "--name-only",
        "-z",
        "HEAD",
        "--",
        *CI_NODEID_SCRATCH_PATHS,
    ):
        return candidate_paths, set()

    scratch_entries = [repository / path for path in CI_NODEID_SCRATCH_PATHS]
    scratch_stats = [entry.lstat() for entry in scratch_entries]
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    for entry, entry_stat in zip(scratch_entries, scratch_stats, strict=True):
        if entry.is_symlink() or not stat.S_ISREG(entry_stat.st_mode):
            return candidate_paths, set()
        if getattr(entry_stat, "st_file_attributes", 0) & reparse_flag:
            return candidate_paths, set()

    fixture_entry = git_output(repository, "ls-tree", "HEAD", "--", CORE_TEST_NODEIDS_PATH)
    fixture_match = re.fullmatch(rb"100644 blob ([0-9a-f]{40})\t(.+)\n", fixture_entry)
    assert fixture_match is not None
    fixture_oid, fixture_path = fixture_match.groups()
    assert fixture_path.decode("utf-8", errors="strict") == CORE_TEST_NODEIDS_PATH
    expected_payload = git_output(repository, "cat-file", "blob", fixture_oid.decode("ascii"))
    assert expected_payload
    expected_text = expected_payload.decode("utf-8", errors="strict")
    assert expected_text.encode("utf-8") == expected_payload
    assert not expected_payload.startswith(b"\xef\xbb\xbf")
    assert b"\0" not in expected_payload
    assert b"\r" not in expected_payload
    assert expected_payload.endswith(b"\n")
    assert not expected_payload.endswith(b"\n\n")
    expected_lines = expected_text.splitlines()
    assert expected_lines and all(expected_lines)
    assert len(expected_lines) == len(set(expected_lines))
    assert expected_text == "\n".join(expected_lines) + "\n"

    scratch_payloads = [entry.read_bytes() for entry in scratch_entries]
    if any(payload != expected_payload for payload in scratch_payloads):
        return candidate_paths, set()
    for entry, before in zip(scratch_entries, scratch_stats, strict=True):
        after = entry.lstat()
        stable_fields = ("st_mode", "st_ino", "st_dev", "st_size", "st_mtime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
            return candidate_paths, set()
        if getattr(after, "st_file_attributes", 0) & reparse_flag:
            return candidate_paths, set()
    return candidate_paths - scratch_paths, scratch_paths


def _assert_disposable_lf_checkouts(
    tmp_path: Path,
    committed_payloads: Mapping[str, bytes],
) -> None:
    source = tmp_path / "eol-contract-source"
    source.mkdir()
    _git_output(source, "init", "--quiet")
    _git_output(source, "config", "core.autocrlf", "false")
    (source / ".gitattributes").write_bytes((REPOSITORY_ROOT / ".gitattributes").read_bytes())
    for relative_path, payload in committed_payloads.items():
        (source / relative_path).write_bytes(payload)
    _git_output(source, "add", ".gitattributes", *sorted(committed_payloads))
    identity_environment = os.environ.copy()
    identity_environment.update(
        {
            "GIT_AUTHOR_NAME": "Checkout Contract",
            "GIT_AUTHOR_EMAIL": "checkout-contract" + chr(64) + "example.invalid",
            "GIT_COMMITTER_NAME": "Checkout Contract",
            "GIT_COMMITTER_EMAIL": "checkout-contract" + chr(64) + "example.invalid",
        }
    )
    _git_output(
        source, "commit", "--quiet", "-m", "checkout contract", environment=identity_environment
    )

    for autocrlf in ("true", "false"):
        checkout = tmp_path / f"autocrlf-{autocrlf}"
        _git_output(tmp_path, "clone", "--quiet", "--no-checkout", str(source), str(checkout))
        _git_output(checkout, "config", "core.autocrlf", autocrlf)
        _git_output(checkout, "checkout", "--quiet", "--force", "HEAD")
        for relative_path, committed_payload in committed_payloads.items():
            checkout_payload = (checkout / relative_path).read_bytes()
            assert checkout_payload == committed_payload
            assert b"\r" not in checkout_payload
            assert checkout_payload.endswith(b"\n")


def _assert_no_affirmative_release_or_capability_claim(texts: Mapping[str, str]) -> None:
    prohibited_phrases = (
        "rde core v1.0 is released",
        "rde core 1.0 is released",
        "1.0.0rc1 is released",
        "1.0.0rc2 is released",
        "1.0.0rc3 is released",
        "1.0.0rc4 is released",
        "1.0.0rc5 is released",
        "rde core is production ready",
        "rde core is production-ready",
        "rde core is scientifically validated",
        "rde core is available on pypi",
        "the repository is public",
        "a public repository is available",
        "rde assurance approved",
        "continual learning is included",
        "gpu executor is available",
        "cluster executor is available",
        "rde core v1.0 已发布",
        "rde core 1.0 已发布",
        "1.0.0rc1 已发布",
        "1.0.0rc2 已发布",
        "1.0.0rc3 已发布",
        "1.0.0rc4 已发布",
        "1.0.0rc5 已发布",
        "rde core 已达到生产就绪",
        "rde core 已通过科学验证",
        "rde core 可从 pypi 获取",
        "公开仓库已可用",
        "已获 rde assurance 批准",
        "rde core 包含 continual learning",
        "提供 gpu executor",
        "提供 cluster executor",
    )
    for path, text in texts.items():
        normalized = " ".join(text.casefold().split())
        assert all(phrase not in normalized for phrase in prohibited_phrases), path


def _assert_rc5_public_provenance_role_token_contract() -> None:
    from research_decision_engine.benchmarks.broader_protocol import (
        PROTOCOL_CHECKPOINT,
        SOURCE_DESIGN_CHECKPOINT,
    )
    from research_decision_engine.benchmarks.broader_protocol import (
        PUBLIC_PROVENANCE_ROLE_TOKEN_NAMESPACE as implementation_namespace,
    )
    from research_decision_engine.benchmarks.broader_protocol import (
        PUBLIC_PROVENANCE_ROLE_TOKEN_SCHEMA as implementation_schema,
    )
    from research_decision_engine.benchmarks.broader_protocol import (
        PUBLIC_PROVENANCE_ROLE_TOKENS as implementation_tokens,
    )

    assert implementation_schema == PUBLIC_PROVENANCE_ROLE_TOKEN_SCHEMA
    assert implementation_namespace == PUBLIC_PROVENANCE_ROLE_TOKEN_NAMESPACE
    evidence_contract_preimage = b"RDE_CORE_PUBLIC_PROVENANCE_ROLE_V1\0EVIDENCE_CONTRACT\0"
    evidence_contract_checkpoint = hashlib.sha256(evidence_contract_preimage).hexdigest()[:40]
    validation_evidence_source = (
        REPOSITORY_ROOT / "research_decision_engine/benchmarks/broader_validation_evidence.py"
    ).read_text(encoding="utf-8")
    assert (
        "EVIDENCE_CONTRACT_CHECKPOINT: Final = hashlib.sha256(\n"
        '    b"RDE_CORE_PUBLIC_PROVENANCE_ROLE_V1\\0EVIDENCE_CONTRACT\\0"\n'
        ").hexdigest()[:40]" in validation_evidence_source
    )
    observed_tokens = {
        "EVIDENCE_CONTRACT": evidence_contract_checkpoint,
        "PROTOCOL": PROTOCOL_CHECKPOINT,
        "SOURCE_DESIGN": SOURCE_DESIGN_CHECKPOINT,
    }
    assert observed_tokens == PUBLIC_PROVENANCE_ROLE_TOKENS
    assert implementation_tokens == frozenset(PUBLIC_PROVENANCE_ROLE_TOKENS.values())
    namespace = PUBLIC_PROVENANCE_ROLE_TOKEN_NAMESPACE.encode("ascii")
    for role_name, token in PUBLIC_PROVENANCE_ROLE_TOKENS.items():
        preimage = namespace + b"\0" + role_name.encode("ascii") + b"\0"
        assert hashlib.sha256(preimage).hexdigest()[:40] == token
        assert re.fullmatch(r"[0-9a-f]{40}", token) is not None
    assert len(set(PUBLIC_PROVENANCE_ROLE_TOKENS.values())) == 3

    object_output = _git_output(
        REPOSITORY_ROOT,
        "cat-file",
        "--batch-check=%(objectname)",
        "--batch-all-objects",
    )
    object_ids = frozenset(object_output.decode("ascii").splitlines())
    assert object_ids.isdisjoint(PUBLIC_PROVENANCE_ROLE_TOKENS.values())

    git_helper_names = {
        "_git_blob_bytes",
        "_git_blob_map",
        "_git_bytes",
        "_git_output",
        "_git_text",
        "_git_tree",
        "_head_tree_rows",
        "_implementation_diff_identity",
    }
    forbidden_names = {
        "EVIDENCE_CONTRACT_CHECKPOINT",
        "PROTOCOL_CHECKPOINT",
        "PUBLIC_PROVENANCE_ROLE_TOKENS",
        "SOURCE_CHECKPOINT",
        "SOURCE_DESIGN_CHECKPOINT",
    }
    for relative_path in PUBLIC_PROVENANCE_GIT_CONSUMER_PATHS:
        source = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
        assert source.count('"HEAD^{commit}"') == 1
        module = ast.parse(source, filename=relative_path)
        for call in (node for node in ast.walk(module) if isinstance(node, ast.Call)):
            function = call.func
            helper_name = (
                function.id
                if isinstance(function, ast.Name)
                else function.attr
                if isinstance(function, ast.Attribute)
                else None
            )
            if helper_name not in git_helper_names:
                continue
            call_arguments = ast.dump(
                ast.Tuple(
                    elts=[*call.args, *(item.value for item in call.keywords)],
                    ctx=ast.Load(),
                ),
                include_attributes=False,
            )
            assert forbidden_names.isdisjoint(
                node.id
                for argument in [*call.args, *(item.value for item in call.keywords)]
                for node in ast.walk(argument)
                if isinstance(node, ast.Name)
            ), relative_path
            assert all(
                token not in call_arguments for token in PUBLIC_PROVENANCE_ROLE_TOKENS.values()
            )


def _assert_c7_release_document_contract(tmp_path: Path) -> None:
    assert len(C7_NEW_PUBLIC_DOCUMENT_PATHS) == 5
    assert C7_NEW_PUBLIC_DOCUMENT_PATHS <= PUBLIC_DOCUMENT_PATHS
    assert frozenset(UV_BUILD_SOURCE_INCLUDE) >= C7_NEW_PUBLIC_DOCUMENT_PATHS
    assert _expected_sdist_file_members() >= C7_NEW_PUBLIC_DOCUMENT_PATHS
    assert len(RC5_NEW_PUBLIC_DOCUMENT_PATHS) == 2
    assert RC5_NEW_PUBLIC_DOCUMENT_PATHS.isdisjoint(PUBLIC_DOCUMENT_PATHS)
    assert RC5_NEW_PUBLIC_DOCUMENT_PATHS.isdisjoint(UV_BUILD_SOURCE_INCLUDE)
    assert RC5_NEW_PUBLIC_DOCUMENT_PATHS.isdisjoint(_expected_sdist_file_members())
    assert len(PUBLIC_DOCUMENT_PATHS) == 27
    assert len(RC5_CHANGED_MARKDOWN_PATHS) == 10
    assert len(RC4_POLICY_PATHS) == 4
    assert len(RC5_AUTHORIZED_CHANGED_PATHS) == 39
    assert len(RC5_PRODUCT_APPLICABLE_REMEDIATION_PATHS) == 35
    assert len(RC5_INTERNAL_ONLY_REMEDIATION_PATHS) == 4
    assert len(RC5_INTERNAL_EXCLUDE_PATHS) == 17
    assert len(RC6_GOVERNANCE_CHANGED_PATHS) == 15
    assert tuple(sorted(RC6_GOVERNANCE_CHANGED_PATHS)) == RC6_GOVERNANCE_CHANGED_PATHS
    assert len(set(RC6_GOVERNANCE_CHANGED_PATHS)) == len(RC6_GOVERNANCE_CHANGED_PATHS)
    assert tuple(sorted(RC6_GOVERNANCE_FROZEN_PAYLOAD_ROOTS)) == RC6_GOVERNANCE_FROZEN_PAYLOAD_ROOTS
    assert not _governance_frozen_payload_paths(set(RC6_GOVERNANCE_CHANGED_PATHS))
    assert RC6_GOVERNANCE_ANCESTRY_LENGTH == 3
    assert re.fullmatch(r"[0-9a-f]{40}", RC6_GOVERNANCE_PARENT_OID) is not None
    assert RC6_GOVERNANCE_PARENT_OID != RC5_SANITIZED_PRODUCT_ROOT_OID
    assert RC6_GOVERNANCE_PARENT_OID not in PUBLIC_PROVENANCE_ROLE_TOKENS.values()
    assert RC5_SELF_HOSTING_REPAIR_PATH in RC6_GOVERNANCE_CHANGED_PATHS
    assert RC5_SOURCE_TRACKED_PATH_COUNT - RC5_PRODUCT_TRACKED_PATH_COUNT == 17
    assert CI_NODEID_SCRATCH_PATHS == (
        ".core-v1-nodeids-1.txt",
        ".core-v1-nodeids-2.txt",
    )
    assert tuple(sorted(RC4_POLICY_PATHS)) == RC4_POLICY_PATHS
    assert tuple(sorted(RC5_AUTHORIZED_CHANGED_PATHS)) == RC5_AUTHORIZED_CHANGED_PATHS
    assert (
        tuple(sorted(RC5_PRODUCT_APPLICABLE_REMEDIATION_PATHS))
        == RC5_PRODUCT_APPLICABLE_REMEDIATION_PATHS
    )
    assert tuple(sorted(RC5_INTERNAL_ONLY_REMEDIATION_PATHS)) == RC5_INTERNAL_ONLY_REMEDIATION_PATHS
    assert tuple(sorted(RC5_INTERNAL_EXCLUDE_PATHS)) == RC5_INTERNAL_EXCLUDE_PATHS
    assert set(RC5_PRODUCT_APPLICABLE_REMEDIATION_PATHS).isdisjoint(
        RC5_INTERNAL_ONLY_REMEDIATION_PATHS
    )
    assert set(RC5_PRODUCT_APPLICABLE_REMEDIATION_PATHS) | set(
        RC5_INTERNAL_ONLY_REMEDIATION_PATHS
    ) == set(RC5_AUTHORIZED_CHANGED_PATHS)
    assert set(RC5_INTERNAL_ONLY_REMEDIATION_PATHS) <= set(RC5_INTERNAL_EXCLUDE_PATHS)
    assert all(
        (REPOSITORY_ROOT / path).is_file() for path in RC5_PRODUCT_APPLICABLE_REMEDIATION_PATHS
    )
    assert not (REPOSITORY_ROOT / "docs/release-notes/1.0.0rc4.md").exists()
    assert not (REPOSITORY_ROOT / "docs/zh-CN/release-notes/1.0.0rc4.md").exists()
    assert all((REPOSITORY_ROOT / path).is_file() for path in RC5_NEW_PUBLIC_DOCUMENT_PATHS)
    assert len(C7_PUBLIC_BRAND_PATHS) == 8
    assert tuple(sorted(C7_PUBLIC_BRAND_PATHS)) == C7_PUBLIC_BRAND_PATHS

    brand_text = {
        relative_path: (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
        for relative_path in C7_PUBLIC_BRAND_PATHS
    }
    assert brand_text["DESIGN.md"].splitlines()[0] == (
        "# Research Reasoning Architecture and Research Decision Engine Core"
    )
    assert brand_text["PLAN.md"].splitlines()[0] == (
        "# Research Decision Engine Core Implementation Plan"
    )
    assert brand_text["SPEC.md"].splitlines()[0] == (
        "# Research Decision Engine Core Specification"
    )
    assert (
        "Research Decision Engine Core benchmark:"
        in brand_text["research_decision_engine/benchmarks/reporting.py"]
    )
    assert (
        'description="Research Decision Engine Core"'
        in brand_text["research_decision_engine/cli.py"]
    )
    for relative_path, text in brand_text.items():
        assert "Research-Decision-Engine Core" not in text, relative_path
        assert re.search(r"Research Decision Engine(?! Core)", text) is None, relative_path

    from research_decision_engine.benchmarks.closed_loop_evaluation import (
        FROZEN_DESIGN_SHA256,
        FROZEN_SOURCE_SHA256,
        _file_hash_matches,
    )

    assert FROZEN_DESIGN_SHA256 == EXPECTED_FROZEN_DESIGN_SHA256
    assert FROZEN_SOURCE_SHA256 == EXPECTED_FROZEN_SOURCE_SHA256
    committed_payloads: dict[str, bytes] = {}
    for relative_path, expected in PROTECTED_DOCUMENT_BLOB_CONTRACT.items():
        entry = _git_output(REPOSITORY_ROOT, "ls-tree", "HEAD", "--", relative_path)
        match = re.fullmatch(rb"([0-7]{6}) blob ([0-9a-f]{40})\t(.+)\n", entry)
        assert match is not None
        mode, oid, entry_path = match.groups()
        assert mode.decode("ascii") == expected["mode"]
        assert oid.decode("ascii") == expected["oid"]
        assert entry_path.decode("utf-8") == relative_path
        committed_payload = _git_output(
            REPOSITORY_ROOT, "cat-file", "blob", cast(str, expected["oid"])
        )
        committed_payloads[relative_path] = committed_payload
        assert len(committed_payload) == expected["byte_count"]
        assert hashlib.sha256(committed_payload).hexdigest() == expected["sha256"]
        assert expected["sha256"] == FROZEN_DESIGN_SHA256[relative_path]
        assert expected["sha256"] != expected["crlf_sha256"]
        assert b"\r" not in committed_payload
        assert committed_payload.endswith(b"\n")
        assert (REPOSITORY_ROOT / relative_path).read_bytes() == committed_payload

    exact_root = tmp_path / "exact-committed-documents"
    crlf_root = tmp_path / "crlf-altered-documents"
    exact_root.mkdir()
    crlf_root.mkdir()
    expected_document_hashes = {
        relative_path: cast(str, contract["sha256"])
        for relative_path, contract in PROTECTED_DOCUMENT_BLOB_CONTRACT.items()
    }
    for relative_path, committed_payload in committed_payloads.items():
        (exact_root / relative_path).write_bytes(committed_payload)
        (crlf_root / relative_path).write_bytes(committed_payload.replace(b"\n", b"\r\n"))
    assert _file_hash_matches(exact_root, expected_document_hashes)
    assert not _file_hash_matches(crlf_root, expected_document_hashes)
    assert "subprocess" not in _file_hash_matches.__code__.co_names
    assert "git" not in _file_hash_matches.__code__.co_names
    _assert_disposable_lf_checkouts(tmp_path, committed_payloads)

    commit_model, tracked_paths, committed_candidate_paths = (
        _release_document_committed_candidate_paths(
            REPOSITORY_ROOT,
            git_output=_git_output,
        )
    )
    substantive_candidate_paths, validated_scratch_paths = (
        _release_document_worktree_candidate_paths(
            REPOSITORY_ROOT,
            git_output=_git_output,
        )
    )
    assert validated_scratch_paths in (set(), set(CI_NODEID_SCRATCH_PATHS))
    source_remediation_paths = set(RC5_AUTHORIZED_CHANGED_PATHS)
    repair_paths = {RC5_SELF_HOSTING_REPAIR_PATH}
    if commit_model == "FULL_PRIVATE_SOURCE_ONE_PARENT":
        assert len(tracked_paths) == RC5_SOURCE_TRACKED_PATH_COUNT
        assert all((REPOSITORY_ROOT / path).is_file() for path in RC5_INTERNAL_EXCLUDE_PATHS)
        if substantive_candidate_paths:
            assert substantive_candidate_paths == repair_paths
            assert committed_candidate_paths == source_remediation_paths
        else:
            assert committed_candidate_paths in (source_remediation_paths, repair_paths)
    elif commit_model == "SANITIZED_PRODUCT_ZERO_PARENT_ROOT":
        assert len(tracked_paths) == RC5_PRODUCT_TRACKED_PATH_COUNT
        assert committed_candidate_paths == set()
        assert substantive_candidate_paths in (set(), repair_paths)
        assert all(not (REPOSITORY_ROOT / path).exists() for path in RC5_INTERNAL_EXCLUDE_PATHS)
    elif commit_model == "PUBLIC_GOVERNANCE_LINEAR_DESCENDANT":
        assert len(tracked_paths) == RC5_PRODUCT_TRACKED_PATH_COUNT
        assert committed_candidate_paths == set(RC6_GOVERNANCE_CHANGED_PATHS)
        assert substantive_candidate_paths == set()
        assert all(not (REPOSITORY_ROOT / path).exists() for path in RC5_INTERNAL_EXCLUDE_PATHS)
    else:
        assert commit_model == "SANITIZED_PRODUCT_LINEAR_DESCENDANT"
        assert len(tracked_paths) == RC5_PRODUCT_TRACKED_PATH_COUNT
        assert committed_candidate_paths in (set(), repair_paths)
        assert substantive_candidate_paths in (set(), set(RC6_GOVERNANCE_CHANGED_PATHS))
        assert all(not (REPOSITORY_ROOT / path).exists() for path in RC5_INTERNAL_EXCLUDE_PATHS)
    assert set(PROTECTED_DOCUMENT_BLOB_CONTRACT).isdisjoint(source_remediation_paths)
    _assert_rc5_public_provenance_role_token_contract()

    scripted_child_one_oid = "1" * 40
    scripted_child_two_oid = "2" * 40
    scripted_second_parent_oid = "3" * 40
    scripted_private_head_oid = "4" * 40
    scripted_private_root_oid = "5" * 40
    scripted_unrelated_root_oid = "6" * 40
    internal_exclude_paths = set(RC5_INTERNAL_EXCLUDE_PATHS)
    if commit_model == "FULL_PRIVATE_SOURCE_ONE_PARENT":
        scripted_source_paths = set(tracked_paths)
        scripted_product_paths = scripted_source_paths - internal_exclude_paths
    else:
        scripted_product_paths = set(tracked_paths)
        scripted_source_paths = scripted_product_paths | internal_exclude_paths
    assert len(scripted_source_paths) == RC5_SOURCE_TRACKED_PATH_COUNT
    assert len(scripted_product_paths) == RC5_PRODUCT_TRACKED_PATH_COUNT
    assert _path_set_sha256(scripted_source_paths) == RC5_SOURCE_PATH_SET_SHA256
    assert _path_set_sha256(scripted_product_paths) == RC5_PRODUCT_PATH_SET_SHA256
    assert scripted_source_paths - scripted_product_paths == internal_exclude_paths

    def encoded_paths(paths: set[str]) -> bytes:
        return b"".join(path.encode("utf-8", errors="strict") + b"\0" for path in sorted(paths))

    scripted_git_dir = (tmp_path / ".git").absolute()
    scripted_objects_dir = scripted_git_dir / "objects"
    scripted_grafts_path = scripted_git_dir / "info/grafts"
    scripted_alternates_path = scripted_objects_dir / "info/alternates"
    scripted_shallow_path = scripted_git_dir / "shallow"
    scripted_public_name = b"Synthetic Product Identity"
    scripted_public_email = b"synthetic-audit" + b"@" + b"users.noreply.github.com"

    def encoded_path(path: Path) -> bytes:
        return str(path).encode("utf-8", errors="strict") + b"\n"

    def scripted_commit_payload(
        oid: str,
        parent_oids: tuple[str, ...],
        *,
        message: bytes = b"scripted commit\n",
        identity: tuple[bytes, bytes] | None = None,
    ) -> bytes:
        name, email = identity or (scripted_public_name, scripted_public_email)
        tree_oid = hashlib.sha256(("tree:" + oid).encode("ascii")).hexdigest()[:40]
        parent_headers = b"".join(
            b"parent " + parent_oid.encode("ascii") + b"\n" for parent_oid in parent_oids
        )
        return b"".join(
            (
                b"tree " + tree_oid.encode("ascii") + b"\n",
                parent_headers,
                b"author " + name + b" <" + email + b"> 0 +0000\n",
                b"committer " + name + b" <" + email + b"> 0 +0000\n\n",
                message,
            )
        )

    def scripted_responses(
        chain: tuple[tuple[str, tuple[str, ...], set[str]], ...],
        *,
        changed_paths: set[str] | None = None,
        messages: Mapping[str, bytes] | None = None,
        identities: Mapping[str, tuple[bytes, bytes]] | None = None,
    ) -> dict[tuple[str, ...], bytes]:
        assert chain
        head_oid = chain[0][0]
        root_oid = chain[-1][0]
        message_map = {} if messages is None else dict(messages)
        identity_map = {} if identities is None else dict(identities)
        responses = {
            ("rev-parse", "--is-shallow-repository"): b"false\n",
            ("replace", "-l"): b"",
            ("rev-parse", "--path-format=absolute", "--git-dir"): encoded_path(scripted_git_dir),
            ("rev-parse", "--path-format=absolute", "--git-common-dir"): encoded_path(
                scripted_git_dir
            ),
            ("rev-parse", "--path-format=absolute", "--git-path", "objects"): encoded_path(
                scripted_objects_dir
            ),
            ("rev-parse", "--path-format=absolute", "--git-path", "info/grafts"): encoded_path(
                scripted_grafts_path
            ),
            (
                "rev-parse",
                "--path-format=absolute",
                "--git-path",
                "objects/info/alternates",
            ): encoded_path(scripted_alternates_path),
            ("rev-parse", "--path-format=absolute", "--git-path", "shallow"): encoded_path(
                scripted_shallow_path
            ),
            ("rev-parse", "--verify", "HEAD"): f"{head_oid}\n".encode("ascii"),
            ("rev-parse", "--verify", "HEAD^{commit}"): f"{head_oid}\n".encode("ascii"),
            ("rev-list", "--parents", "--topo-order", head_oid): b"".join(
                (oid + "".join(f" {parent_oid}" for parent_oid in parent_oids) + "\n").encode(
                    "ascii"
                )
                for oid, parent_oids, _paths in chain
            ),
            ("rev-list", "--max-parents=0", head_oid): f"{root_oid}\n".encode("ascii"),
            ("rev-list", "--count", head_oid): f"{len(chain)}\n".encode("ascii"),
        }
        for oid, parent_oids, repository_paths in chain:
            responses[("cat-file", "-t", oid)] = b"commit\n"
            responses[("cat-file", "commit", oid)] = scripted_commit_payload(
                oid,
                parent_oids,
                message=message_map.get(oid, b"scripted commit\n"),
                identity=identity_map.get(oid),
            )
            responses[
                (
                    "ls-tree",
                    "-r",
                    "--full-tree",
                    "--name-only",
                    "-z",
                    oid,
                )
            ] = encoded_paths(repository_paths)
        head_parents = chain[0][1]
        if head_parents:
            responses[
                (
                    "diff-tree",
                    "--no-commit-id",
                    "--name-only",
                    "-r",
                    "-z",
                    head_parents[0],
                    head_oid,
                )
            ] = encoded_paths(repair_paths if changed_paths is None else changed_paths)
        if root_oid == RC5_SANITIZED_PRODUCT_ROOT_OID:
            root_paths = chain[-1][2]
            if len(chain) > 1:
                responses[
                    (
                        "diff-tree",
                        "--no-commit-id",
                        "--name-only",
                        "-r",
                        "-z",
                        root_oid,
                        head_oid,
                    )
                ] = encoded_paths(repair_paths if changed_paths is None else changed_paths)
            responses[
                (
                    "diff-tree",
                    "--root",
                    "--no-commit-id",
                    "--name-status",
                    "-r",
                    "-z",
                    root_oid,
                )
            ] = b"".join(
                b"A\0" + path.encode("utf-8", errors="strict") + b"\0"
                for path in sorted(root_paths)
            )
        return responses

    all_scripted_calls: list[tuple[str, ...]] = []

    def run_script(
        responses: Mapping[tuple[str, ...], bytes],
        *,
        fail_on: tuple[str, ...] | None = None,
        existing_paths: frozenset[Path] = frozenset(),
        redirected_paths: frozenset[Path] = frozenset(),
    ) -> tuple[tuple[str, set[str], set[str]], list[tuple[str, ...]]]:
        calls: list[tuple[str, ...]] = []

        def scripted_git_output(
            _cwd: Path,
            *arguments: str,
            **keyword_arguments: object,
        ) -> bytes:
            assert not keyword_arguments
            calls.append(arguments)
            all_scripted_calls.append(arguments)
            if arguments == fail_on:
                raise RuntimeError("scripted arbitrary Git error")
            assert arguments in responses
            return responses[arguments]

        result = _release_document_committed_candidate_paths(
            tmp_path,
            git_output=scripted_git_output,
            path_entry_exists=lambda path: path in existing_paths,
            path_entry_is_redirect=lambda path: path in redirected_paths,
        )
        return result, calls

    # 1. The exact full private source child is accepted.
    current_source_responses = scripted_responses(
        (
            (
                scripted_private_head_oid,
                (scripted_private_root_oid,),
                scripted_source_paths,
            ),
            (scripted_private_root_oid, (), scripted_source_paths),
        ),
        changed_paths=source_remediation_paths,
    )
    (current_source_model, current_source_tree, current_source_changes), child_calls = run_script(
        current_source_responses
    )
    assert current_source_model == "FULL_PRIVATE_SOURCE_ONE_PARENT"
    assert current_source_tree == scripted_source_paths
    assert current_source_changes == source_remediation_paths
    assert child_calls[-1] == (
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "-r",
        "-z",
        scripted_private_root_oid,
        scripted_private_head_oid,
    )

    # 2. The exact sanitized zero-parent product root is accepted.
    root_chain = ((RC5_SANITIZED_PRODUCT_ROOT_OID, (), scripted_product_paths),)
    root_responses = scripted_responses(root_chain)
    (root_model, root_tree, root_changes), root_calls = run_script(root_responses)
    assert root_model == "SANITIZED_PRODUCT_ZERO_PARENT_ROOT"
    assert root_tree == scripted_product_paths
    assert root_changes == set()
    assert (
        "diff-tree",
        "--root",
        "--no-commit-id",
        "--name-status",
        "-r",
        "-z",
        RC5_SANITIZED_PRODUCT_ROOT_OID,
    ) in root_calls

    # 3. One ordinary same-tree public child is accepted.
    one_child_chain = (
        (scripted_child_one_oid, (RC5_SANITIZED_PRODUCT_ROOT_OID,), scripted_product_paths),
        *root_chain,
    )
    one_child_responses = scripted_responses(one_child_chain, changed_paths=set())
    (one_child_model, one_child_tree, one_child_changes), _one_child_calls = run_script(
        one_child_responses
    )
    assert one_child_model == "SANITIZED_PRODUCT_LINEAR_DESCENDANT"
    assert one_child_tree == scripted_product_paths
    assert one_child_changes == set()

    # 4. One changed public child is accepted.
    changed_child_responses = scripted_responses(one_child_chain, changed_paths=repair_paths)
    (changed_child_model, _changed_child_tree, changed_child_paths), _changed_child_calls = (
        run_script(changed_child_responses)
    )
    assert changed_child_model == "SANITIZED_PRODUCT_LINEAR_DESCENDANT"
    assert changed_child_paths == repair_paths

    # 5. Two successive ordinary public children are accepted without a depth limit.
    two_child_chain = (
        (scripted_child_two_oid, (scripted_child_one_oid,), scripted_product_paths),
        *one_child_chain,
    )
    two_child_responses = scripted_responses(two_child_chain, changed_paths=repair_paths)
    (two_child_model, two_child_tree, two_child_changes), _two_child_calls = run_script(
        two_child_responses
    )
    assert two_child_model == "SANITIZED_PRODUCT_LINEAR_DESCENDANT"
    assert two_child_tree == scripted_product_paths
    assert two_child_changes == repair_paths

    # 6. A product root containing one internal-only path fails closed.
    product_plus_internal_only = scripted_product_paths | {RC5_INTERNAL_ONLY_REMEDIATION_PATHS[0]}
    with pytest.raises(AssertionError):
        run_script(
            scripted_responses(((RC5_SANITIZED_PRODUCT_ROOT_OID, (), product_plus_internal_only),))
        )

    # 7. A product root missing one product-applicable path fails closed.
    product_missing_applicable = scripted_product_paths - {
        RC5_PRODUCT_APPLICABLE_REMEDIATION_PATHS[0]
    }
    with pytest.raises(AssertionError):
        run_script(
            scripted_responses(((RC5_SANITIZED_PRODUCT_ROOT_OID, (), product_missing_applicable),))
        )

    # 8. A public descendant containing one internal-only path fails closed.
    descendant_plus_internal = scripted_product_paths | {RC5_INTERNAL_EXCLUDE_PATHS[0]}
    with pytest.raises(AssertionError):
        run_script(
            scripted_responses(
                (
                    (
                        scripted_child_one_oid,
                        (RC5_SANITIZED_PRODUCT_ROOT_OID,),
                        descendant_plus_internal,
                    ),
                    *root_chain,
                ),
                changed_paths={RC5_INTERNAL_EXCLUDE_PATHS[0]},
            )
        )

    # 9. A source child missing one internal-only path fails closed.
    source_missing_internal_only = scripted_source_paths - {RC5_INTERNAL_ONLY_REMEDIATION_PATHS[0]}
    with pytest.raises(AssertionError):
        run_script(
            scripted_responses(
                (
                    (
                        scripted_private_head_oid,
                        (scripted_private_root_oid,),
                        source_missing_internal_only,
                    ),
                    (scripted_private_root_oid, (), source_missing_internal_only),
                )
            )
        )

    # 10. A source child with the wrong total path partition fails closed.
    replaceable_source_paths = (
        scripted_source_paths - source_remediation_paths - internal_exclude_paths
    )
    assert replaceable_source_paths
    replaced_source_path = sorted(replaceable_source_paths)[0]
    wrong_source_partition = (scripted_source_paths - {replaced_source_path}) | {
        "unexpected/source-partition-path.txt"
    }
    with pytest.raises(AssertionError):
        run_script(
            scripted_responses(
                (
                    (
                        scripted_private_head_oid,
                        (scripted_private_root_oid,),
                        wrong_source_partition,
                    ),
                    (scripted_private_root_oid, (), wrong_source_partition),
                )
            )
        )

    # 11. An explicitly shallow repository fails closed before ancestry interpretation.
    shallow_responses = dict(one_child_responses)
    shallow_responses[("rev-parse", "--is-shallow-repository")] = b"true\n"
    with pytest.raises(AssertionError):
        run_script(shallow_responses)

    # 12. Incomplete ancestry fails closed even if the shallow flag is false.
    incomplete_responses = dict(one_child_responses)
    incomplete_responses[("rev-list", "--parents", "--topo-order", scripted_child_one_oid)] = (
        f"{scripted_child_one_oid} {RC5_SANITIZED_PRODUCT_ROOT_OID}\n".encode("ascii")
    )
    with pytest.raises(AssertionError):
        run_script(incomplete_responses)

    # 13. A merge at HEAD fails closed.
    merge_responses = dict(one_child_responses)
    merge_responses[("rev-list", "--parents", "--topo-order", scripted_child_one_oid)] = (
        f"{scripted_child_one_oid} {RC5_SANITIZED_PRODUCT_ROOT_OID} "
        f"{scripted_second_parent_oid}\n"
        f"{RC5_SANITIZED_PRODUCT_ROOT_OID}\n"
        f"{scripted_second_parent_oid}\n"
    ).encode("ascii")
    with pytest.raises(AssertionError):
        run_script(merge_responses)

    # 14. A merge hidden below HEAD also fails closed.
    inner_merge_responses = dict(two_child_responses)
    inner_merge_responses[("rev-list", "--parents", "--topo-order", scripted_child_two_oid)] = (
        f"{scripted_child_two_oid} {scripted_child_one_oid}\n"
        f"{scripted_child_one_oid} {RC5_SANITIZED_PRODUCT_ROOT_OID} "
        f"{scripted_second_parent_oid}\n"
        f"{RC5_SANITIZED_PRODUCT_ROOT_OID}\n"
        f"{scripted_second_parent_oid}\n"
    ).encode("ascii")
    with pytest.raises(AssertionError):
        run_script(inner_merge_responses)

    # 15. Missing, unborn, or non-commit HEAD fails closed.
    state_only_responses: dict[tuple[str, ...], bytes] = {
        key: value
        for key, value in root_responses.items()
        if key
        in {
            ("rev-parse", "--is-shallow-repository"),
            ("replace", "-l"),
            ("rev-parse", "--path-format=absolute", "--git-dir"),
            ("rev-parse", "--path-format=absolute", "--git-common-dir"),
            ("rev-parse", "--path-format=absolute", "--git-path", "objects"),
            ("rev-parse", "--path-format=absolute", "--git-path", "info/grafts"),
            (
                "rev-parse",
                "--path-format=absolute",
                "--git-path",
                "objects/info/alternates",
            ),
            ("rev-parse", "--path-format=absolute", "--git-path", "shallow"),
        }
    }
    with pytest.raises(AssertionError):
        run_script(state_only_responses)

    unborn_responses = dict(root_responses)
    unborn_responses[("rev-parse", "--verify", "HEAD")] = b"HEAD\n"
    with pytest.raises(AssertionError):
        run_script(unborn_responses)

    non_commit_responses = dict(root_responses)
    non_commit_responses[("cat-file", "-t", RC5_SANITIZED_PRODUCT_ROOT_OID)] = b"blob\n"
    with pytest.raises(AssertionError):
        run_script(non_commit_responses)

    # 16. An arbitrary Git error fails closed.
    arbitrary_git_error_call = (
        "ls-tree",
        "-r",
        "--full-tree",
        "--name-only",
        "-z",
        RC5_SANITIZED_PRODUCT_ROOT_OID,
    )
    with pytest.raises(RuntimeError, match="scripted arbitrary Git error"):
        run_script(root_responses, fail_on=arbitrary_git_error_call)

    # 17. Replace refs, grafts, alternates, and a redirected object store fail closed.
    replace_responses = dict(root_responses)
    replace_responses[("replace", "-l")] = b"refs/replace/synthetic\n"
    with pytest.raises(AssertionError):
        run_script(replace_responses)
    with pytest.raises(AssertionError):
        run_script(root_responses, existing_paths=frozenset({scripted_grafts_path}))
    with pytest.raises(AssertionError):
        run_script(root_responses, existing_paths=frozenset({scripted_alternates_path}))
    with pytest.raises(AssertionError):
        run_script(root_responses, redirected_paths=frozenset({scripted_objects_dir}))
    alternate_store_responses = dict(root_responses)
    alternate_store_responses[("rev-parse", "--path-format=absolute", "--git-path", "objects")] = (
        encoded_path((tmp_path / "external-object-store").absolute())
    )
    with pytest.raises(AssertionError):
        run_script(alternate_store_responses)

    # 18. An unrelated or ambiguous root fails closed even with the product path set.
    unrelated_root_responses = scripted_responses(
        ((scripted_unrelated_root_oid, (), scripted_product_paths),)
    )
    with pytest.raises(AssertionError):
        run_script(unrelated_root_responses)
    multiple_root_responses = dict(one_child_responses)
    multiple_root_responses[("rev-list", "--max-parents=0", scripted_child_one_oid)] = (
        f"{RC5_SANITIZED_PRODUCT_ROOT_OID}\n{scripted_unrelated_root_oid}\n".encode("ascii")
    )
    with pytest.raises(AssertionError):
        run_script(multiple_root_responses)

    # 19. Controlled-source recurrence and non-public descendant identities fail closed.
    psc_message = b"controlled-source " + b"PSC" + b"-01\n"
    psc_responses = scripted_responses(
        root_chain,
        messages={RC5_SANITIZED_PRODUCT_ROOT_OID: psc_message},
    )
    with pytest.raises(AssertionError):
        run_script(psc_responses)
    private_email = b"synthetic-private" + b"@" + b"example.invalid"
    private_email_responses = scripted_responses(
        one_child_chain,
        identities={scripted_child_one_oid: (scripted_public_name, private_email)},
    )
    with pytest.raises(AssertionError):
        run_script(private_email_responses)
    private_identity_responses = scripted_responses(
        one_child_chain,
        identities={scripted_child_one_oid: (b"Different Identity", scripted_public_email)},
    )
    with pytest.raises(AssertionError):
        run_script(private_identity_responses)

    # 20. No frozen public-provenance role token is accepted or supplied to Git.
    scripted_role_token = next(iter(PUBLIC_PROVENANCE_ROLE_TOKENS.values()))
    role_token_responses = dict(state_only_responses)
    role_token_responses[("rev-parse", "--verify", "HEAD")] = (
        scripted_role_token.encode("ascii") + b"\n"
    )
    role_token_responses[("rev-parse", "--verify", "HEAD^{commit}")] = (
        scripted_role_token.encode("ascii") + b"\n"
    )
    with pytest.raises(AssertionError):
        run_script(role_token_responses)
    role_token_tree_responses = dict(root_responses)
    role_token_tree_responses[("cat-file", "commit", RC5_SANITIZED_PRODUCT_ROOT_OID)] = (
        b"tree "
        + scripted_role_token.encode("ascii")
        + b"\n"
        + b"author "
        + scripted_public_name
        + b" <"
        + scripted_public_email
        + b"> 0 +0000\n"
        + b"committer "
        + scripted_public_name
        + b" <"
        + scripted_public_email
        + b"> 0 +0000\n\nscripted commit\n"
    )
    with pytest.raises(AssertionError):
        run_script(role_token_tree_responses)
    role_token_occurrences = sum(
        argument.count(token)
        for arguments in all_scripted_calls
        for argument in arguments
        for token in PUBLIC_PROVENANCE_ROLE_TOKENS.values()
    )
    assert role_token_occurrences == 0

    # 21. The exact post-D020 governance descendant is accepted as its own class.
    governance_chain = (
        (
            scripted_child_two_oid,
            (RC6_GOVERNANCE_PARENT_OID,),
            scripted_product_paths,
        ),
        (
            RC6_GOVERNANCE_PARENT_OID,
            (RC5_SANITIZED_PRODUCT_ROOT_OID,),
            scripted_product_paths,
        ),
        *root_chain,
    )
    governance_changes = set(RC6_GOVERNANCE_CHANGED_PATHS)
    (governance_model, governance_tree, governance_paths), _governance_calls = run_script(
        scripted_responses(governance_chain, changed_paths=governance_changes)
    )
    assert governance_model == "PUBLIC_GOVERNANCE_LINEAR_DESCENDANT"
    assert governance_tree == scripted_product_paths
    assert governance_paths == governance_changes

    # 22. A governance-shaped child of any other parent is not the governance class.
    wrong_parent_chain = (
        (scripted_child_two_oid, (scripted_child_one_oid,), scripted_product_paths),
        *one_child_chain,
    )
    (wrong_parent_model, _wrong_parent_tree, _wrong_parent_paths), _wrong_parent_calls = run_script(
        scripted_responses(wrong_parent_chain, changed_paths=governance_changes)
    )
    assert wrong_parent_model == "SANITIZED_PRODUCT_LINEAR_DESCENDANT"

    # 23. A later descendant of the governance commit is not the governance class.
    later_descendant_chain = (
        (scripted_child_one_oid, (scripted_child_two_oid,), scripted_product_paths),
        *governance_chain,
    )
    (later_model, _later_tree, _later_paths), _later_calls = run_script(
        scripted_responses(later_descendant_chain, changed_paths=governance_changes)
    )
    assert later_model == "SANITIZED_PRODUCT_LINEAR_DESCENDANT"

    # 24. A changed path outside the governance allowlist is not the governance class.
    outside_allowlist = governance_changes | {
        next(iter(sorted(_governance_frozen_payload_paths(scripted_product_paths))))
    }
    (outside_model, _outside_tree, outside_paths), _outside_calls = run_script(
        scripted_responses(governance_chain, changed_paths=outside_allowlist)
    )
    assert outside_model == "SANITIZED_PRODUCT_LINEAR_DESCENDANT"
    assert outside_paths == outside_allowlist

    # 25. An empty-diff descendant at governance depth still fails closed.
    with pytest.raises(AssertionError):
        run_script(scripted_responses(governance_chain, changed_paths=set()))

    # 26. A governance-shaped commit whose tree gains an internal path fails closed.
    with pytest.raises(AssertionError):
        run_script(
            scripted_responses(
                (
                    (
                        scripted_child_two_oid,
                        (RC6_GOVERNANCE_PARENT_OID,),
                        scripted_product_paths | {RC5_INTERNAL_EXCLUDE_PATHS[0]},
                    ),
                    *governance_chain[1:],
                ),
                changed_paths=governance_changes,
            )
        )

    changed_text = {
        relative_path: _strict_markdown_text(REPOSITORY_ROOT / relative_path)
        for relative_path in sorted(RC5_CHANGED_MARKDOWN_PATHS)
    }
    for relative_path in sorted(RC5_CHANGED_MARKDOWN_PATHS):
        _assert_markdown_links_resolve(REPOSITORY_ROOT / relative_path)

    attributes_path = REPOSITORY_ROOT / ".gitattributes"
    attributes_payload = attributes_path.read_bytes()
    assert attributes_payload.endswith(b"\n")
    assert not attributes_payload.endswith(b"\n\n")
    attributes = attributes_payload.decode("utf-8", errors="strict")
    for relative_path in sorted(RC5_CHANGED_MARKDOWN_PATHS):
        assert attributes.splitlines().count(f"{relative_path} text eol=lf") == 1
    for relative_path in PROTECTED_DOCUMENT_BLOB_CONTRACT:
        assert attributes.splitlines().count(f"{relative_path} text eol=lf") == 1
    assert "*.md text eol=lf" not in attributes

    c7_privacy_payloads = {
        **{
            relative_path: (REPOSITORY_ROOT / relative_path).read_bytes()
            for relative_path in RC5_CHANGED_MARKDOWN_PATHS
        },
        ".gitattributes": attributes_payload,
        "BROADER_REPLICATION_DESIGN.md": (
            REPOSITORY_ROOT / "BROADER_REPLICATION_DESIGN.md"
        ).read_bytes(),
    }
    _assert_private_checkout_absent(c7_privacy_payloads)
    _assert_privacy_scan_clean(c7_privacy_payloads)
    _assert_no_affirmative_release_or_capability_claim(changed_text)

    changelog = changed_text["CHANGELOG.md"]
    changelog_zh = changed_text["CHANGELOG.zh-CN.md"]
    for text in (changelog, changelog_zh):
        assert re.findall(r"^## \[([^]]+)\]$", text, flags=re.MULTILINE) == ["Unreleased"]
        assert "## [1.0.0rc1]" not in text
        assert "## [1.0.0rc2]" not in text
        assert "## [1.0.0rc3]" not in text
        assert "## [1.0.0rc4]" not in text
        assert "## [1.0.0rc5]" not in text
    assert "**Active private candidate:** `1.0.0rc5`" in changelog
    assert "**Public release:** `NONE`" in changelog
    assert (
        "**Prior private candidate:** `1.0.0rc4`, which was superseded before publication "
        "when private-source commit references were removed from release-facing surfaces"
        in " ".join(changelog.split())
    )
    assert "**当前私有候选：** `1.0.0rc5`" in changelog_zh
    assert "**公开发布：** `NONE`" in changelog_zh
    assert (
        "**先前私有候选：** `1.0.0rc4`，在从面向发布的表面移除私有源提交引用后于 "
        "公开发布前被取代" in " ".join(changelog_zh.split())
    )
    assert tuple(
        line.removeprefix("### ") for line in changelog.splitlines() if line.startswith("### ")
    ) == ("Added", "Changed", "Fixed", "Security", "Packaging", "Documentation")
    assert tuple(
        line.removeprefix("### ") for line in changelog_zh.splitlines() if line.startswith("### ")
    ) == (
        "Added（新增）",
        "Changed（变更）",
        "Fixed（修复）",
        "Security（安全）",
        "Packaging（打包）",
        "Documentation（文档）",
    )
    _assert_shared_markers(
        (changelog, changelog_zh),
        frozenset(
            {
                "0.1.0",
                "1.0.0rc1",
                "1.0.0rc2",
                "1.0.0rc3",
                "1.0.0rc4",
                "1.0.0rc5",
                "Research Decision Engine Core",
                "research-decision-engine",
                "research_decision_engine",
                "112",
                "121",
                "91",
                "27",
                "3",
                "Apache-2.0",
                "CommandAdapter",
                "PythonFunctionAdapter",
                "RunBundle",
                "RunSpec",
                "SQLite",
                "Windows",
                "Linux",
                ".github/**",
                ".gitattributes",
                ".gitignore",
                "greedy_prior",
                "information_gain_table",
                "random",
                "tests/**",
                "uv_build==0.11.32",
                "v6",
            }
        ),
    )

    compatibility = changed_text["CORE_V1_COMPATIBILITY.md"]
    compatibility_zh = changed_text["CORE_V1_COMPATIBILITY.zh-CN.md"]
    assert len([line for line in compatibility.splitlines() if line.startswith("## ")]) == len(
        [line for line in compatibility_zh.splitlines() if line.startswith("## ")]
    )
    _assert_shared_markers(
        (compatibility, compatibility_zh),
        frozenset(
            {
                ">=3.12,<3.13",
                "112",
                "121",
                "91",
                "27",
                "3",
                "BACKWARD_COMPATIBLE",
                "DEPRECATED_CANDIDATE",
                "ExperimentStore",
                "PER_VERSION_STEP_ATOMIC_AND_RESUMABLE",
                "RDE_CORE_PUBLIC_API_V1",
                "RECORDED_OBSERVATION_DECISION_REPLAY_V1",
                "RECORDED_OBSERVATION_DECISION_REPLAY_V2",
                "RECORDED_OBSERVATION_DECISION_REPLAY_V3",
                "SCHEMA_VERSION",
                "STABLE_THROUGH_RDE_1_X",
                "__version__",
                "0.1.0",
                "1.0.0rc1",
                "1.0.0rc2",
                "1.0.0rc3",
                "1.0.0rc4",
                "1.0.0rc5",
                "Research Decision Engine Core",
                "research-decision-engine",
                "research_decision_engine",
                "str",
                "Windows",
                "Linux",
                "macOS",
                ".github",
                "greedy_prior",
                "information_gain_table",
                "random",
                "rde-core-run-bundle/v1",
                "rde-core-run-bundle/v2",
                "rde-core-run-bundle/v3",
                "rde-core-run-spec/v1",
                "rde-core-run-spec/v2",
                "rde-core-run-spec/v3",
                "v6",
            }
        ),
    )
    assert "its value always equals the active installed distribution version" in " ".join(
        compatibility.split()
    )
    assert "其值始终等于当前已安装分发包的版本" in " ".join(compatibility_zh.split())
    assert "No other public constant receives an exception" in " ".join(compatibility.split())
    assert "其他任何公开常量均不因此获得" in " ".join(compatibility_zh.split())

    release_notes = changed_text["docs/release-notes/1.0.0rc3.md"]
    release_notes_zh = changed_text["docs/zh-CN/release-notes/1.0.0rc3.md"]
    assert not (REPOSITORY_ROOT / "docs/release-notes/1.0.0rc1.md").exists()
    assert not (REPOSITORY_ROOT / "docs/zh-CN/release-notes/1.0.0rc1.md").exists()
    assert release_notes.splitlines()[0] == "# PRIVATE RC CANDIDATE — NOT PUBLISHED"
    assert release_notes_zh.splitlines()[0] == "# 私有 RC 候选 — 尚未发布"
    assert tuple(
        line.removeprefix("## ") for line in release_notes.splitlines() if line.startswith("## ")
    ) == (
        "Status",
        "What RDE Core is",
        "Highlights",
        "Supported contracts",
        "Installation during private RC preparation",
        "Upgrade and SQLite migration notes",
        "RunBundle verification and replay behavior",
        "Security and trust boundaries",
        "Known limitations",
        "Current verification scope",
        "Remaining release blockers",
        "Feedback expectations for a future RC",
    )
    assert tuple(
        line.removeprefix("## ") for line in release_notes_zh.splitlines() if line.startswith("## ")
    ) == (
        "状态",
        "RDE Core 是什么",
        "亮点",
        "支持的合同",
        "私有 RC 准备期间的安装",
        "升级与 SQLite 迁移说明",
        "RunBundle 验证与回放行为",
        "安全与信任边界",
        "已知限制",
        "当前验证范围",
        "剩余发布阻塞项",
        "对未来 RC 的反馈期望",
    )
    _assert_shared_markers(
        (release_notes, release_notes_zh),
        frozenset(
            {
                ">=3.12,<3.13",
                "0.1.0",
                "1.0.0rc1",
                "1.0.0rc2",
                "1.0.0rc3",
                "1.0.0rc4",
                "Research Decision Engine Core",
                "112",
                "121",
                "91",
                "27",
                "3",
                "575",
                "Apache-2.0",
                "CPython 3.12",
                "CommandAdapter",
                "Continual Learning",
                "GitHub Release",
                "PyPI",
                "PythonFunctionAdapter",
                "RDE Assurance",
                "RunBundle",
                "SQLite",
                "Web UI",
                "Windows",
                "Linux",
                "macOS",
                ".github",
                "greedy_prior",
                "information_gain_table",
                "random",
                "uv sync --locked",
                "v6",
            }
        ),
    )
    assert "**Package version:** `1.0.0rc3`" in release_notes
    assert (
        "**Prior private candidate:** 1.0.0rc2 failed cross-platform release-contract "
        "validation and was superseded before public publication" in release_notes
    )
    assert (
        "**Reason for candidate advance:** frozen design-document hashes are now derived "
        "from exact committed LF blob bytes" in release_notes
    )
    assert "**Algorithm/storage/schema behavior change:** `NO`" in release_notes
    assert (
        "**Candidate disposition:** `SUPERSEDED_BY_PRIVATE_1.0.0rc4_BEFORE_PUBLICATION`"
        in release_notes
    )
    assert (
        "**Supersession reason:** the Private Vulnerability Reporting publication "
        "sequence was corrected, changing packaged policy documentation and distribution bytes"
        in release_notes
    )
    assert "**Sanitized product repository:** `ESTABLISHED_PRIVATE`" in release_notes
    assert "**Tag:** `NONE`" in release_notes
    assert "**GitHub Release:** `NONE`" in release_notes
    assert "**PyPI:** `NOT_PUBLISHED`" in release_notes
    assert "**软件包版本：** `1.0.0rc3`" in release_notes_zh
    assert "**候选状态：** `SUPERSEDED_BY_PRIVATE_1.0.0rc4_BEFORE_PUBLICATION`" in release_notes_zh
    assert "**净化产品仓库：** `ESTABLISHED_PRIVATE`" in release_notes_zh
    assert "**标签：** `NONE`" in release_notes_zh
    assert "**GitHub Release：** `NONE`" in release_notes_zh
    assert "**PyPI：** `NOT_PUBLISHED`" in release_notes_zh
    assert re.search(r"\bpip(?:3)?\s+install\b", release_notes, flags=re.IGNORECASE) is None
    assert re.search(r"\bpip(?:3)?\s+install\b", release_notes_zh, flags=re.IGNORECASE) is None
    assert re.search(r"\b20\d{2}-\d{2}-\d{2}\b", release_notes) is None
    assert re.search(r"\b20\d{2}-\d{2}-\d{2}\b", release_notes_zh) is None

    rc5_notes = changed_text["docs/release-notes/1.0.0rc5.md"]
    rc5_notes_zh = changed_text["docs/zh-CN/release-notes/1.0.0rc5.md"]
    assert rc5_notes.splitlines()[0] == "# RC CANDIDATE — NOT PUBLISHED"
    assert rc5_notes_zh.splitlines()[0] == "# RC 候选 — 尚未发布"
    assert tuple(
        line.removeprefix("## ") for line in rc5_notes.splitlines() if line.startswith("## ")
    ) == (
        "Status",
        "Provenance remediation",
        "Compatibility",
        "Verification boundary",
        "Remaining publication gates",
    )
    assert tuple(
        line.removeprefix("## ") for line in rc5_notes_zh.splitlines() if line.startswith("## ")
    ) == ("状态", "来源修复", "兼容性", "验证边界", "剩余发布门禁")
    _assert_shared_markers(
        (rc5_notes, rc5_notes_zh),
        frozenset(
            {
                ">=3.12,<3.13",
                "1.0.0rc4",
                "1.0.0rc5",
                "112",
                "575",
                "EVIDENCE_CONTRACT",
                "PROTOCOL",
                "SOURCE_DESIGN",
                "GitHub Release",
                "PyPI",
                "RunBundle",
                "RunSpec",
                "SQLite",
                "Windows",
                "Linux",
                "v6",
            }
        ),
    )
    assert "**Package version:** `1.0.0rc5`" in rc5_notes
    assert "**Candidate state:** `RC_CANDIDATE_NOT_PUBLISHED`" in rc5_notes
    assert "**Public visibility:** `YES`" in rc5_notes
    assert "**软件包版本：** `1.0.0rc5`" in rc5_notes_zh
    assert "**候选状态：** `RC_CANDIDATE_NOT_PUBLISHED`" in rc5_notes_zh
    assert "**公开可见：** `YES`" in rc5_notes_zh
    assert re.search(r"\bpip(?:3)?\s+install\b", rc5_notes, flags=re.IGNORECASE) is None
    assert re.search(r"\bpip(?:3)?\s+install\b", rc5_notes_zh, flags=re.IGNORECASE) is None
    assert re.search(r"\b20\d{2}-\d{2}-\d{2}\b", rc5_notes) is None
    assert re.search(r"\b20\d{2}-\d{2}-\d{2}\b", rc5_notes_zh) is None

    english_blockers = (
        "sanitized product repository remains private",
        "Private Vulnerability Reporting is not enabled in the private state",
        "Public Windows/Linux CI",
        "release tag has not been created",
        "GitHub Release has not been created",
        "has not been published to PyPI",
    )
    chinese_blockers = (
        "净化的产品仓库仍为私有",
        "私有状态下未启用 Private Vulnerability Reporting",
        "公开状态下的 Windows/Linux CI",
        "尚未创建发布标签",
        "尚未创建 GitHub Release",
        "尚未将包发布到 PyPI",
    )
    assert all(marker in release_notes for marker in english_blockers)
    assert all(marker in release_notes_zh for marker in chinese_blockers)
    assert "full-history privacy audit" in release_notes
    assert "完整历史隐私审计已经完成" in release_notes_zh

    readme = changed_text["README.md"]
    readme_zh = changed_text["README.zh-CN.md"]
    english_disclosure = """## Project status and development approach

Research Decision Engine Core is an experimental, pre-release project.

I built this project through a vibe-coding workflow. This means that I used AI
tools throughout the design, coding, testing, and documentation. I made the
final choices and reviewed the work, but mistakes and untested assumptions may
still remain.

RDE Core has not yet been used in a real production environment. It has not
been tested by a broad range of users or with a broad range of real workloads.
Most of the current evidence comes from automated tests, reproducible builds,
and CI checks. These checks are useful, but they do not replace long-term use
in real environments.

Please treat RDE Core as research software. Start with small, non-critical, and
reversible workloads. Review the inputs, outputs, and assumptions yourself. Do
not use it as the only basis for high-stakes decisions.

Clear bug reports, corrections, and practical feedback are welcome."""
    chinese_disclosure = """## 项目状态与开发方式

Research Decision Engine Core 仍是一个实验性、预发布项目。

这个项目是我全程以 Vibe Coding 的方式开发的。也就是说，我在设计、编码、
测试和文档过程中持续使用了 AI 工具。我做出了最终选择，也检查了工作结果，
但项目中仍然可能存在错误和未经充分验证的假设。

RDE Core 目前还没有在真实生产环境中运行过，也没有经过大量真实用户或大量
真实工作负载的验证。现有证据主要来自自动化测试、可重复构建和 CI 检查。
这些检查很有帮助，但不能代替真实环境中的长期使用。

请把 RDE Core 当作研究软件使用。建议先从小规模、非关键、可回滚的任务开始，
并自行检查输入、输出和相关假设。不要把它作为高风险决策的唯一依据。

欢迎提交清楚的问题报告、修正和实际使用反馈。"""
    assert readme.count(english_disclosure) == 1
    assert readme_zh.count(chinese_disclosure) == 1
    assert (
        readme.index("## What RDE Core is")
        < readme.index(english_disclosure)
        < readme.index("## What it is not")
        < readme.index("## Ten-minute Quickstart")
    )
    assert (
        readme_zh.index("## RDE Core 是什么")
        < readme_zh.index(chinese_disclosure)
        < readme_zh.index("## 它不是什么")
        < readme_zh.index("## 十分钟 Quickstart")
    )
    english_disclosure_facts = (
        "experimental, pre-release",
        "vibe-coding workflow",
        "design, coding, testing, and documentation",
        "I made the final choices and reviewed the work",
        "mistakes and untested assumptions",
        "real production environment",
        "broad range of users",
        "broad range of real workloads",
        "automated tests, reproducible builds, and CI checks",
        "do not replace long-term use in real environments",
        "small, non-critical, and reversible workloads",
        "Review the inputs, outputs, and assumptions yourself",
        "not use it as the only basis for high-stakes decisions",
    )
    chinese_disclosure_facts = (
        "实验性、预发布",
        "Vibe Coding",
        "设计、编码、 测试和文档",
        "我做出了最终选择，也检查了工作结果",
        "错误和未经充分验证的假设",
        "真实生产环境",
        "大量真实用户",
        "大量 真实工作负载",
        "自动化测试、可重复构建和 CI 检查",
        "不能代替真实环境中的长期使用",
        "小规模、非关键、可回滚",
        "自行检查输入、输出和相关假设",
        "不要把它作为高风险决策的唯一依据",
    )
    normalized_english_disclosure = " ".join(english_disclosure.split())
    normalized_chinese_disclosure = " ".join(chinese_disclosure.split())
    assert all(fact in normalized_english_disclosure for fact in english_disclosure_facts)
    assert all(fact in normalized_chinese_disclosure for fact in chinese_disclosure_facts)
    prohibited_promotional_phrases = (
        "production ready",
        "battle tested",
        "enterprise grade",
        "industry leading",
        "fully validated",
        "scientifically proven",
        "scientifically validated",
        "completely secure",
        "fully secure",
        "error free",
        "guaranteed",
        "risk free",
        "ready for critical infrastructure",
        "proven in production",
        "widely adopted",
        "trusted by users",
    )
    assert all(phrase not in readme.casefold() for phrase in prohibited_promotional_phrases)
    assert "[Changelog](CHANGELOG.md)" in readme
    assert "[RDE Core v1 compatibility contract](CORE_V1_COMPATIBILITY.md)" in readme
    assert (
        "1.0.0rc5 private candidate notes are retained only in the private repository "
        "and are intentionally outside the 121-member source distribution."
        in " ".join(readme.split())
    )
    assert "](docs/release-notes/1.0.0rc5.md)" not in readme
    assert (
        "[1.0.0rc3 historical notes (Superseded private candidate / Not published)]"
        "(docs/release-notes/1.0.0rc3.md)" in readme
    )
    assert "[变更日志](CHANGELOG.zh-CN.md)" in readme_zh
    assert "[RDE Core v1 兼容性合同](CORE_V1_COMPATIBILITY.zh-CN.md)" in readme_zh
    assert (
        "1.0.0rc5 私有候选说明仅保留在私有仓库中，并被有意排除在 121-member source "
        "distribution 之外。" in " ".join(readme_zh.split())
    )
    assert "](docs/zh-CN/release-notes/1.0.0rc5.md)" not in readme_zh
    assert (
        "[1.0.0rc3 历史说明（已被取代的私有候选 / 尚未发布）]"
        "(docs/zh-CN/release-notes/1.0.0rc3.md)" in readme_zh
    )
    assert "active private candidate is `1.0.0rc5`" in " ".join(readme.split())
    assert "当前私有候选版本是 `1.0.0rc5`" in " ".join(readme_zh.split())
    assert "sanitized product repository is public" in " ".join(readme.split()).casefold()
    assert "净化的产品仓库已经公开" in " ".join(readme_zh.split())
    assert (
        "[README project-status and development disclosure]"
        "(../../README.md#project-status-and-development-approach)" in release_notes
    )
    assert (
        "[README 中的项目状态与开发方式说明]"
        "(../../../README.zh-CN.md#项目状态与开发方式)" in release_notes_zh
    )

    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert cast(dict[str, object], pyproject["project"])["version"] == PACKAGE_VERSION
    public_manifest = load_public_api_manifest()
    assert len(cast(list[dict[str, object]], public_manifest["public_symbols"])) == 112
    schema_families = {
        cast(str, entry["family"]): tuple(cast(list[str], entry["schemas"]))
        for entry in cast(list[dict[str, object]], public_manifest["schema_families"])
    }
    assert schema_families == {
        "RunBundle": (
            "rde-core-run-bundle/v1",
            "rde-core-run-bundle/v2",
            "rde-core-run-bundle/v3",
        ),
        "RunSpec": (
            "rde-core-run-spec/v1",
            "rde-core-run-spec/v2",
            "rde-core-run-spec/v3",
        ),
        "replay": (
            "RECORDED_OBSERVATION_DECISION_REPLAY_V1",
            "RECORDED_OBSERVATION_DECISION_REPLAY_V2",
            "RECORDED_OBSERVATION_DECISION_REPLAY_V3",
        ),
    }
    policy_matrix = {
        cast(str, entry["policy_id"]): tuple(cast(list[str], entry["run_spec_schemas"]))
        for entry in cast(list[dict[str, object]], public_manifest["supported_policies"])
    }
    assert policy_matrix == {
        "greedy_prior": ("rde-core-run-spec/v2", "rde-core-run-spec/v3"),
        "information_gain_table": ("rde-core-run-spec/v3",),
        "random": (
            "rde-core-run-spec/v1",
            "rde-core-run-spec/v2",
            "rde-core-run-spec/v3",
        ),
    }


def _assert_pull_request_template_contract(text: str) -> None:
    required_headings = (
        "Summary / 摘要",
        "Related issue / 关联 Issue",
        "Change classification / 变更分类",
        "Contract impact / 合同影响",
        "Verification / 验证",
        "Privacy and provenance / 隐私与来源",
        "Compatibility / 兼容性",
        "Documentation / 文档",
    )
    assert all(heading in text for heading in required_headings)
    checkboxes = _unchecked_markdown_checkboxes(text)
    assert checkboxes
    for command in CONTRIBUTING_COMMANDS:
        assert any(command.casefold() in checkbox for checkbox in checkboxes), command
    assert any("windows" in checkbox and "linux" in checkbox for checkbox in checkboxes)

    classification_markers = (
        "bug fix",
        "documentation",
        "test",
        "portability",
        "performance",
        "packaging or release",
        "public api, schema, or storage",
        "other",
    )
    for marker in classification_markers:
        assert any(marker in checkbox for checkbox in checkboxes), marker

    privacy_marker_groups = (
        ("secret", "token", "credential"),
        ("private email", "legal identity"),
        ("absolute path",),
        ("private database", "runbundle"),
        ("audit", "recovery"),
        ("third-party", "provenance", "license"),
        ("build", "cache", "virtual-environment"),
    )
    for markers in privacy_marker_groups:
        assert any(all(marker in checkbox for marker in markers) for checkbox in checkboxes), (
            markers
        )

    contract_marker_groups = (
        ("public api",),
        ("runspec", "runbundle"),
        ("replay",),
        ("sqlite",),
        ("adapters", "policies"),
        ("packaging", "sdist"),
        ("privacy", "security"),
        ("bilingual documentation",),
    )
    normalized = " ".join(text.casefold().split())
    assert all(
        all(marker in normalized for marker in markers) for markers in contract_marker_groups
    )
    assert "n/a" in normalized and "explanation" in normalized
    assert re.search(r"\b(?:closes|fixes|resolves)\s+#", text, flags=re.IGNORECASE) is None


def _assert_community_health_release_contract() -> None:
    github_root = REPOSITORY_ROOT / ".github"
    actual_github_files = frozenset(
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in github_root.rglob("*")
        if path.is_file()
    )
    _assert_exact_path_inventory(
        actual_github_files,
        COMMUNITY_HEALTH_PATHS | {CORE_WORKFLOW_PATH},
        "GitHub community-health",
    )
    assert len(COMMUNITY_HEALTH_PATHS) == 6

    community_text: dict[str, str] = {}
    community_payloads: dict[str, bytes] = {}
    for relative_path in sorted(COMMUNITY_HEALTH_PATHS):
        path = REPOSITORY_ROOT / relative_path
        assert path.is_file()
        community_text[relative_path] = _strict_markdown_text(path)
        community_payloads[relative_path] = path.read_bytes()
        _assert_markdown_links_resolve(path)

    _assert_contributing_guides_contract(community_text)
    for relative_path in sorted(ISSUE_TEMPLATE_PATHS):
        _assert_issue_template_contract(
            REPOSITORY_ROOT / relative_path, community_text[relative_path]
        )
    _assert_pull_request_template_contract(community_text[".github/pull_request_template.md"])

    prohibited_community_paths = (
        "CODE_OF_CONDUCT.md",
        "SUPPORT.md",
        ".github/CODE_OF_CONDUCT.md",
        ".github/SUPPORT.md",
    )
    assert all(
        not (REPOSITORY_ROOT / relative_path).exists()
        for relative_path in prohibited_community_paths
    )
    issue_template_names = {
        path.name.casefold()
        for path in (REPOSITORY_ROOT / ".github/ISSUE_TEMPLATE").rglob("*")
        if path.is_file()
    }
    assert not any("security" in name or "vulnerability" in name for name in issue_template_names)

    workflow_payload = (REPOSITORY_ROOT / CORE_WORKFLOW_PATH).read_bytes()
    assert hashlib.sha256(workflow_payload).hexdigest() == CORE_WORKFLOW_SHA256

    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = cast(dict[str, object], pyproject["project"])
    assert project["version"] == PACKAGE_VERSION == "1.0.0rc5"
    assert cast(dict[str, object], pyproject["build-system"]) == {
        "requires": [UV_BUILD_REQUIREMENT],
        "build-backend": "uv_build",
    }
    expected_sdist_members = _expected_sdist_file_members()
    assert len(expected_sdist_members) == 121
    assert ".gitignore" not in expected_sdist_members
    assert COMMUNITY_HEALTH_PATHS.isdisjoint(expected_sdist_members)

    public_manifest = load_public_api_manifest()
    assert len(cast(list[dict[str, object]], public_manifest["public_symbols"])) == 112
    fixture_manifest_path = (
        REPOSITORY_ROOT / "research_decision_engine/core-fixtures-v1/fixture-manifest.json"
    )
    assert hashlib.sha256(fixture_manifest_path.read_bytes()).hexdigest() == FIXTURE_MANIFEST_SHA256
    fixture_manifest = verify_packaged_fixtures()
    assert len(cast(list[dict[str, object]], fixture_manifest["fixtures"])) == 23

    privacy_payloads = {
        **community_payloads,
        "release-contract-test-source": Path(__file__).read_bytes(),
    }
    _assert_private_checkout_absent(privacy_payloads)
    _assert_privacy_scan_clean(privacy_payloads)


def _public_document_link_edges(root: Path) -> frozenset[tuple[str, str]]:
    root_resolved = root.resolve()
    edges = {
        (source, target.relative_to(root_resolved).as_posix())
        for source in PUBLIC_DOCUMENT_PATHS
        for target in _local_markdown_link_targets(root / source, root)
    }
    canonical = b"".join(
        source.encode("utf-8") + b"\0" + target.encode("utf-8") + b"\n"
        for source, target in sorted(edges)
    )
    assert len(edges) == PUBLIC_DOCUMENT_LINK_EDGE_COUNT
    assert hashlib.sha256(canonical).hexdigest() == PUBLIC_DOCUMENT_LINK_EDGE_SHA256
    return frozenset(edges)


def _public_document_link_closure(root: Path) -> frozenset[str]:
    starting_paths = {"README.md", "README.zh-CN.md"}
    pending = [root / relative_path for relative_path in sorted(starting_paths)]
    closure: set[Path] = set()
    while pending:
        path = pending.pop(0).resolve()
        if path in closure:
            continue
        assert path.is_file()
        closure.add(path)
        for target in _local_markdown_link_targets(path, root):
            if target.suffix.casefold() == ".md" and target not in closure:
                pending.append(target)
    return frozenset(path.relative_to(root.resolve()).as_posix() for path in closure)


def _expected_sdist_file_members() -> frozenset[str]:
    members = frozenset(
        {*PUBLIC_DOCUMENT_PATHS, *PUBLIC_PACKAGE_PATHS, *SDIST_BUILD_METADATA_PATHS}
    )
    assert len(PUBLIC_PACKAGE_PATHS) == 91
    assert len(PUBLIC_DOCUMENT_PATHS) == 27
    assert len(SDIST_BUILD_METADATA_PATHS) == 3
    assert len(members) == 121
    assert ".gitignore" not in members
    return members


def _assert_exact_path_inventory(
    actual: frozenset[str], expected: frozenset[str], label: str
) -> None:
    if actual != expected:
        raise AssertionError(
            f"{label} inventory mismatch: expected_count={len(expected)}, "
            f"actual_count={len(actual)}, missing_count={len(expected - actual)}, "
            f"unexpected_count={len(actual - expected)}"
        )


def _assert_package_payloads_equal(
    actual: Mapping[str, bytes], expected: Mapping[str, bytes], label: str
) -> None:
    _assert_exact_path_inventory(frozenset(actual), frozenset(expected), label)
    mismatch_count = sum(actual[path] != expected[path] for path in expected)
    if mismatch_count:
        raise AssertionError(f"{label} byte mismatch: mismatch_count={mismatch_count}")


def _archive_text_payload(value: str) -> bytes:
    return value.encode("utf-8", errors="surrogatepass")


def _gzip_header_payloads(sdist: Path) -> dict[str, bytes]:
    raw = sdist.read_bytes()
    assert len(raw) >= 10
    assert raw[:3] == b"\x1f\x8b\x08"
    flags = raw[3]
    assert flags & 0xE0 == 0
    offset = 10
    payloads: dict[str, bytes] = {}

    if flags & 0x04:
        assert offset + 2 <= len(raw)
        extra_length = int.from_bytes(raw[offset : offset + 2], "little")
        offset += 2
        assert offset + extra_length <= len(raw)
        payloads["gzip-extra"] = raw[offset : offset + extra_length]
        offset += extra_length

    for flag, label in ((0x08, "gzip-filename"), (0x10, "gzip-comment")):
        if flags & flag:
            terminator = raw.find(b"\0", offset)
            assert terminator >= offset
            payloads[label] = raw[offset:terminator]
            offset = terminator + 1

    if flags & 0x02:
        assert offset + 2 <= len(raw)
        offset += 2
    assert offset < len(raw)
    return payloads


def _read_sdist_payloads(sdist: Path) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    archive_metadata_payloads = _gzip_header_payloads(sdist)
    expected_members = _expected_sdist_file_members()
    permitted_directories = {
        PurePosixPath(*parts[:index]).as_posix()
        for path in expected_members
        for parts in (PurePosixPath(path).parts,)
        for index in range(1, len(parts))
    }
    archive_member_names: set[str] = set()
    with tarfile.open(sdist, "r:gz") as archive:
        for pax_index, (key, value) in enumerate(archive.pax_headers.items()):
            archive_metadata_payloads[f"tar-global-pax-{pax_index}-key"] = _archive_text_payload(
                key
            )
            archive_metadata_payloads[f"tar-global-pax-{pax_index}-value"] = _archive_text_payload(
                value
            )
        for member_index, member in enumerate(archive.getmembers()):
            archive_metadata_payloads[f"tar-{member_index}-name"] = _archive_text_payload(
                member.name
            )
            archive_metadata_payloads[f"tar-{member_index}-linkname"] = _archive_text_payload(
                member.linkname
            )
            archive_metadata_payloads[f"tar-{member_index}-uname"] = _archive_text_payload(
                member.uname
            )
            archive_metadata_payloads[f"tar-{member_index}-gname"] = _archive_text_payload(
                member.gname
            )
            for pax_index, (key, value) in enumerate(member.pax_headers.items()):
                archive_metadata_payloads[f"tar-{member_index}-pax-{pax_index}-key"] = (
                    _archive_text_payload(key)
                )
                archive_metadata_payloads[f"tar-{member_index}-pax-{pax_index}-value"] = (
                    _archive_text_payload(value)
                )
            member_path = PurePosixPath(member.name)
            if member_path.as_posix() in archive_member_names:
                raise AssertionError("duplicate sdist archive member")
            archive_member_names.add(member_path.as_posix())
            if (
                member_path.is_absolute()
                or ".." in member_path.parts
                or not member_path.parts
                or member_path.parts[0] != SDIST_ROOT
            ):
                raise AssertionError("invalid sdist archive member path")
            if len(member_path.parts) == 1:
                if not member.isdir():
                    raise AssertionError("invalid sdist root archive member type")
                continue
            relative_path = PurePosixPath(*member_path.parts[1:]).as_posix()
            if member.isdir():
                if relative_path not in permitted_directories:
                    raise AssertionError("unexpected sdist directory member")
                continue
            if not member.isfile():
                raise AssertionError("unexpected sdist non-regular member")
            if relative_path in payloads:
                raise AssertionError("duplicate sdist regular member")
            extracted = archive.extractfile(member)
            assert extracted is not None
            payloads[relative_path] = extracted.read()

    _assert_private_checkout_absent(archive_metadata_payloads)
    _assert_privacy_scan_clean(archive_metadata_payloads)
    _assert_exact_path_inventory(frozenset(payloads), expected_members, "sdist")
    assert len(payloads) == 121
    assert frozenset(payloads) & PUBLIC_PACKAGE_PATHS == PUBLIC_PACKAGE_PATHS
    assert frozenset(payloads) & PUBLIC_DOCUMENT_PATHS == PUBLIC_DOCUMENT_PATHS
    assert frozenset(payloads) & SDIST_BUILD_METADATA_PATHS == SDIST_BUILD_METADATA_PATHS
    assert ".gitignore" not in payloads
    assert {
        "LICENSE",
        "PKG-INFO",
        "README.md",
        "README.zh-CN.md",
        "SECURITY.md",
        "SECURITY.zh-CN.md",
        "pyproject.toml",
        "research_decision_engine/__init__.py",
        "research_decision_engine/core-public-api-v1.json",
        "research_decision_engine/core-fixtures-v1/fixture-manifest.json",
    } <= expected_members
    assert expected_members >= PUBLIC_DOCUMENT_PATHS

    generated_members = {"PKG-INFO"}
    source_mismatch_count = sum(
        payloads[relative_path] != (REPOSITORY_ROOT / relative_path).read_bytes()
        for relative_path in expected_members - generated_members
    )
    if source_mismatch_count:
        raise AssertionError(f"sdist source byte mismatch: mismatch_count={source_mismatch_count}")
    package_payloads = {path: payloads[path] for path in PUBLIC_PACKAGE_PATHS}
    assert (
        _normalized_payload_manifest_sha256(package_payloads)
        == CANDIDATE_PACKAGE_NORMALIZED_TREE_SHA256
    )

    forbidden_prefixes = (
        ".git/",
        ".github/",
        ".venv/",
        "build/",
        "dist/",
        "tests/",
        "examples/",
        "__pycache__/",
        ".pytest_cache/",
        ".mypy_cache/",
        ".ruff_cache/",
        "broader-replication-smoke-v2/",
        "divergence-audit-v1-189-cases/",
        "rde-" + "core-v1-" + "baseline/",
        "rde-" + "recovery/",
        "rde-" + "continuity/",
    )
    forbidden_exact = {
        "AGENTS.md",
        "DESIGN.md",
        "PLAN.md",
        "SPEC.md",
        ".gitattributes",
        ".gitignore",
        "uv.lock",
    }
    assert not any(
        path in forbidden_exact
        or path.startswith(forbidden_prefixes)
        or PurePosixPath(path).name.startswith("BROADER_REPLICATION_")
        or PurePosixPath(path).suffix.casefold() in {".patch", ".diff"}
        for path in payloads
    )
    assert not any(
        fragment in path.casefold()
        for path in payloads
        for fragment in (
            "repository" + ".json",
            "temp_clone" + "_token",
            "credential" + "-helper",
        )
    )
    _assert_private_checkout_absent(payloads)
    _assert_privacy_scan_clean(payloads)
    return payloads


def _extract_sdist(sdist: Path, destination: Path) -> Path:
    destination.mkdir()
    with tarfile.open(sdist, "r:gz") as archive:
        archive.extractall(destination, filter="data")
    extracted_root = destination / SDIST_ROOT
    assert extracted_root.is_dir()
    assert _public_document_link_closure(extracted_root) == PUBLIC_DOCUMENT_PATHS
    _public_document_link_edges(extracted_root)
    for relative_path in PUBLIC_DOCUMENT_PATHS:
        _assert_markdown_links_resolve(extracted_root / relative_path, extracted_root)
    extracted_payloads = {
        path.relative_to(extracted_root).as_posix(): path.read_bytes()
        for path in extracted_root.rglob("*")
        if path.is_file()
    }
    _assert_exact_path_inventory(
        frozenset(extracted_payloads), _expected_sdist_file_members(), "extracted sdist"
    )
    _assert_private_checkout_absent(extracted_payloads)
    _assert_privacy_scan_clean(extracted_payloads)
    return extracted_root


def _metadata_projection(message: Message) -> dict[str, tuple[str, ...]]:
    fields = (
        "Metadata-Version",
        "Name",
        "Version",
        "Requires-Python",
        "Requires-Dist",
        "License-Expression",
        "License-File",
        "Author",
        "Author-email",
        "Maintainer",
        "Maintainer-email",
    )
    return {field: tuple(message.get_all(field) or ()) for field in fields}


def _assert_wheel_distribution_contract(wheel: Path, license_bytes: bytes) -> dict[str, object]:
    wheel_metadata_path = f"{DIST_INFO}/METADATA"
    wheel_contract_path = f"{DIST_INFO}/WHEEL"
    wheel_entry_points_path = f"{DIST_INFO}/entry_points.txt"
    wheel_license_path = f"{DIST_INFO}/licenses/LICENSE"
    wheel_record_path = f"{DIST_INFO}/RECORD"
    auxiliary_paths = frozenset(
        {
            wheel_metadata_path,
            wheel_contract_path,
            wheel_entry_points_path,
            wheel_license_path,
            wheel_record_path,
        }
    )
    expected_regular_members = PUBLIC_PACKAGE_PATHS | auxiliary_paths
    permitted_directories = {
        PurePosixPath(*parts[:index]).as_posix()
        for path in expected_regular_members
        for parts in (PurePosixPath(path).parts,)
        for index in range(1, len(parts))
    }
    with zipfile.ZipFile(wheel) as archive:
        payloads: dict[str, bytes] = {}
        archive_metadata_payloads = {"zip-archive-comment": archive.comment}
        archive_member_names: set[str] = set()
        for member_index, member in enumerate(archive.infolist()):
            member_path = PurePosixPath(member.filename)
            if member_path.as_posix() in archive_member_names:
                raise AssertionError("duplicate wheel archive member")
            archive_member_names.add(member_path.as_posix())
            archive_metadata_payloads[f"zip-{member_index}-filename"] = _archive_text_payload(
                member.filename
            )
            archive_metadata_payloads[f"zip-{member_index}-comment"] = member.comment
            archive_metadata_payloads[f"zip-{member_index}-extra"] = member.extra
            if member_path.is_absolute() or ".." in member_path.parts:
                raise AssertionError("invalid wheel archive member path")
            if member.is_dir():
                if (
                    member.filename.rstrip("/") != member_path.as_posix()
                    or member_path.as_posix() not in permitted_directories
                ):
                    raise AssertionError("unexpected wheel directory member")
                continue
            if member.filename != member_path.as_posix():
                raise AssertionError("invalid wheel regular member path")
            payloads[member_path.as_posix()] = archive.read(member)

    _assert_private_checkout_absent(archive_metadata_payloads)
    _assert_privacy_scan_clean(archive_metadata_payloads)
    _assert_exact_path_inventory(frozenset(payloads), expected_regular_members, "wheel")
    _assert_private_checkout_absent(payloads)
    _assert_privacy_scan_clean(payloads)
    package_payloads = {path: payloads[path] for path in PUBLIC_PACKAGE_PATHS}
    _assert_package_payloads_equal(
        package_payloads, _package_payloads(REPOSITORY_ROOT), "wheel package"
    )
    assert (
        _normalized_payload_manifest_sha256(package_payloads)
        == CANDIDATE_PACKAGE_NORMALIZED_TREE_SHA256
    )
    assert payloads[wheel_license_path] == license_bytes
    assert payloads[wheel_entry_points_path] == WHEEL_ENTRY_POINTS

    metadata = _metadata_message(payloads[wheel_metadata_path])
    _assert_distribution_metadata(metadata)
    wheel_metadata = _metadata_message(payloads[wheel_contract_path])
    assert wheel_metadata.get_all("Wheel-Version") == ["1.0"]
    assert wheel_metadata.get_all("Generator") == [f"uv {UV_VERSION}"]
    assert wheel_metadata.get_all("Root-Is-Purelib") == ["true"]
    assert wheel_metadata.get_all("Tag") == ["py3-none-any"]

    return {
        "entry_points": payloads[wheel_entry_points_path],
        "metadata": _metadata_projection(metadata),
        "package_manifest": _normalized_payload_manifest_sha256(package_payloads),
        "wheel": {
            "Root-Is-Purelib": tuple(wheel_metadata.get_all("Root-Is-Purelib") or ()),
            "Tag": tuple(wheel_metadata.get_all("Tag") or ()),
            "Wheel-Version": tuple(wheel_metadata.get_all("Wheel-Version") or ()),
        },
    }


def _assert_security_privacy_release_contract() -> None:
    security_path = REPOSITORY_ROOT / "SECURITY.md"
    security_zh_path = REPOSITORY_ROOT / "SECURITY.zh-CN.md"
    privacy_path = REPOSITORY_ROOT / "docs/privacy-release-gate.md"
    privacy_zh_path = REPOSITORY_ROOT / "docs/zh-CN/privacy-release-gate.md"
    required_paths = (security_path, security_zh_path, privacy_path, privacy_zh_path)
    assert all(path.is_file() for path in required_paths)

    security = security_path.read_text(encoding="utf-8")
    security_zh = security_zh_path.read_text(encoding="utf-8")
    privacy = privacy_path.read_text(encoding="utf-8")
    privacy_zh = privacy_zh_path.read_text(encoding="utf-8")
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    readme_zh = (REPOSITORY_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    security_normalized = " ".join(security.split())
    security_zh_normalized = " ".join(security_zh.split())
    privacy_normalized = " ".join(privacy.split())
    privacy_zh_normalized = " ".join(privacy_zh.split())

    assert "[简体中文](SECURITY.zh-CN.md)" in security
    assert "[English](SECURITY.md)" in security_zh
    assert "[简体中文](zh-CN/privacy-release-gate.md)" in privacy
    assert "[English](../privacy-release-gate.md)" in privacy_zh
    assert "[Security policy and vulnerability reporting](SECURITY.md)" in readme
    assert "[Privacy and secret release gate](docs/privacy-release-gate.md)" in readme
    assert "[安全政策与漏洞报告](SECURITY.zh-CN.md)" in readme_zh
    assert "[隐私与 secret 发布门](docs/zh-CN/privacy-release-gate.md)" in readme_zh

    for path in (
        REPOSITORY_ROOT / "README.md",
        REPOSITORY_ROOT / "README.zh-CN.md",
        security_path,
        security_zh_path,
        *(path for path in (REPOSITORY_ROOT / "docs").rglob("*.md")),
    ):
        _assert_markdown_links_resolve(path)

    assert "No public RDE Core release is currently supported." in security_normalized
    assert "目前没有受支持的 RDE Core 公开发行版。" in security_zh_normalized
    assert (
        "Do not open a public issue for a suspected security vulnerability." in security_normalized
    )
    assert "不要为疑似安全漏洞创建公开 issue。" in security_zh_normalized
    assert (
        "GitHub Private Vulnerability Reporting is the active external reporting channel"
        in security_normalized
    )
    assert "是有效的外部报告渠道" in security_zh_normalized
    assert "No response-time or resolution SLA is promised" in security_normalized
    assert "不承诺响应时间或解决时限 SLA" in security_zh_normalized

    parity_terms = (
        "PythonFunctionAdapter",
        "CommandAdapter",
        "RunBundle",
        "SQLite",
        "RDE Assurance",
        "GitHub Private Vulnerability Reporting",
        "Report a vulnerability",
        "CI PASS",
    )
    assert all(
        term in security_normalized and term in security_zh_normalized for term in parity_terms
    )
    assert security.count("## ") == security_zh.count("## ") == 6

    english_release_model_rows = (
        "| Private canonical development/audit repository | "
        "`RolandLin0724/research-decision-engine` |",
        "| Visibility | `PRIVATE_PERMANENT` |",
        "| Public product repository | `SEPARATE_SANITIZED_REPOSITORY` |",
        "| Public history | `ONE_NEW_ROOT_COMMIT_FROM_AN_EXACT_REVIEWED_TREE` |",
        "| Private Git history | `NOT_COPIED` |",
        "| Private refs/stashes/reflogs | `NOT_COPIED` |",
        "| Raw review/recovery/audit evidence | `NOT_COPIED` |",
        "| Public author | `RolandLin0724` |",
        "| Public author email | GitHub noreply only |",
        "| Legal name | `NOT_PUBLISHED` |",
    )
    chinese_release_model_rows = (
        "| 私有规范开发与审计仓库 | `RolandLin0724/research-decision-engine` |",
        "| Visibility | `PRIVATE_PERMANENT` |",
        "| 公开产品仓库 | `SEPARATE_SANITIZED_REPOSITORY` |",
        "| 公开历史 | `ONE_NEW_ROOT_COMMIT_FROM_AN_EXACT_REVIEWED_TREE` |",
        "| 私有 Git 历史 | `NOT_COPIED` |",
        "| 私有 refs/stashes/reflogs | `NOT_COPIED` |",
        "| 原始 review/recovery/audit evidence | `NOT_COPIED` |",
        "| 公开作者 | `RolandLin0724` |",
        "| 公开作者邮箱 | 仅使用 GitHub noreply 地址 |",
        "| 法定姓名 | `NOT_PUBLISHED` |",
    )
    english_current_status_rows = (
        "| Current task | `PUBLIC_RC6_GOVERNANCE_AND_CI_ALIGNMENT` |",
        "| Full Git-history privacy audit | `COMPLETED_WITH_INCREMENTAL_EXTENSION` |",
        "| Credential rotation/revocation | `COMPLETED_EXTERNALLY_OPERATOR_ATTESTED` |",
        "| Sanitized product repository | `ESTABLISHED_PUBLIC` |",
        "| Repository visibility | `PUBLIC` |",
        "| Repository visibility change | `AUTHORIZED_AND_COMPLETED` |",
        "| Private Vulnerability Reporting | `ENABLED_AND_VERIFIED` |",
        "| Tag / GitHub Release / PyPI | `NONE / NONE / NOT_PUBLISHED` |",
    )
    chinese_current_status_rows = (
        "| 当前任务 | `PUBLIC_RC6_GOVERNANCE_AND_CI_ALIGNMENT` |",
        "| Full Git-history privacy audit | `COMPLETED_WITH_INCREMENTAL_EXTENSION` |",
        "| Credential rotation/revocation | `COMPLETED_EXTERNALLY_OPERATOR_ATTESTED` |",
        "| Sanitized product repository | `ESTABLISHED_PUBLIC` |",
        "| Repository visibility | `PUBLIC` |",
        "| Repository visibility change | `AUTHORIZED_AND_COMPLETED` |",
        "| Private Vulnerability Reporting | `ENABLED_AND_VERIFIED` |",
        "| Tag / GitHub Release / PyPI | `NONE / NONE / NOT_PUBLISHED` |",
    )
    assert all(row in privacy for row in english_release_model_rows)
    assert all(row in privacy_zh for row in chinese_release_model_rows)
    assert all(row in privacy for row in english_current_status_rows)
    assert all(row in privacy_zh for row in chinese_current_status_rows)
    assert "| Credential rotation | `NOT_RUN` |" not in privacy
    assert "| Credential rotation | `NOT_RUN` |" not in privacy_zh
    assert "Revoke or rotate every previously exposed credential" in privacy_normalized
    assert "撤销或轮换每一项曾经暴露的 credential" in privacy_zh_normalized
    sequence = (
        "S0_PRIVATE_PREPARATION",
        "S1_OPERATOR_PUBLIC_VISIBILITY_AUTHORIZATION",
        "S2_VISIBILITY_PRIVATE_TO_PUBLIC",
        "S3_IMMEDIATELY_ENABLE_PRIVATE_VULNERABILITY_REPORTING",
        "S4_VERIFY_PRIVATE_VULNERABILITY_REPORTING_ACTIVE",
        "S5_ENABLE_OR_VERIFY_PUBLIC_SECRET_SCANNING_AND_PUSH_PROTECTION",
        "S6_ENABLE_OR_VERIFY_PUBLIC_CODE_SCANNING_WHEN_AVAILABLE",
        "S7_ACTIVATE_OR_VERIFY_MAIN_BRANCH_RULES",
        "S8_RUN_PUBLIC_STATE_WINDOWS_AND_LINUX_CI",
        "S9_RUN_PUBLIC_REPOSITORY_LOG_ARTIFACT_AND_PRIVACY_AUDIT",
        "S10_AUTHORIZE_TAG_AND_GITHUB_PRERELEASE",
        "S11_OPTIONAL_SEPARATE_PYPI_RC_AUTHORIZATION",
    )
    for text in (privacy, privacy_zh):
        assert all(text.count(item) == 1 for item in sequence)
        assert tuple(text.index(item) for item in sequence) == tuple(
            sorted(text.index(item) for item in sequence)
        )
    assert (
        "The repository became public only after every private-state preparation gate passed."
        in security_normalized
    )
    assert (
        "That change from private to public required explicit operator authorization and "
        "received it." in security_normalized
    )
    assert (
        "GitHub Private Vulnerability Reporting is enabled and its active state is verified."
        in security_normalized
    )
    assert (
        "Immediately after an authorized public visibility change, it must be enabled and its "
        "active state verified." in security_normalized
    )
    assert (
        "Private Vulnerability Reporting must be verified before any tag, GitHub Release, "
        "GitHub Prerelease, PyPI upload, or release announcement." in security_normalized
    )
    assert (
        "After public visibility, Windows and Linux CI and the complete privacy and security "
        "audit must pass again before any release action." in security_normalized
    )
    assert "Public issues remain forbidden for vulnerability disclosure" in security_normalized
    assert "在每一项私有状态准备门禁通过之后，仓库已经公开" in security_zh_normalized
    assert (
        "将仓库从私有改为公开需要 operator 明确授权，并且已经获得该授权" in security_zh_normalized
    )
    assert (
        "GitHub Private Vulnerability Reporting 已启用，并已验证其处于 active 状态"
        in security_zh_normalized
    )
    assert (
        "获得授权并改为公开后，必须立即启用该功能并验证其处于 active 状态" in security_zh_normalized
    )
    assert "在 Private Vulnerability Reporting 验证通过之前，不得创建 tag" in security_zh_normalized
    assert (
        "仓库公开后，必须重新通过 Windows 与 Linux CI 以及完整的隐私和安全审计"
        in security_zh_normalized
    )
    assert "公开 issue 始终禁止用于漏洞披露" in security_zh_normalized
    assert "no tag, GitHub Release, GitHub Prerelease, PyPI upload" in privacy_normalized
    assert "不得创建 tag、GitHub Release、 GitHub Prerelease" in privacy_zh_normalized
    assert "Public issues must never be used" in privacy_normalized
    assert "公开 issue 始终禁止用于披露疑似漏洞" in privacy_zh_normalized
    assert "Enable GitHub private vulnerability reporting before public visibility" not in privacy
    assert "公开可见之前启用 GitHub private vulnerability reporting" not in privacy_zh
    assert "Before a sanitized public snapshot becomes public" not in security
    assert "sanitized public snapshot 公开之前" not in security_zh
    assert "external operator attestation" in privacy_normalized
    assert "外部 operator attestation" in privacy_zh_normalized
    assert "did not inspect a credential value" in privacy_normalized
    assert "没有检查 credential value" in privacy_zh_normalized

    public_identity_lines = (
        "Public project identity: RolandLin0724.",
        "公开项目身份：RolandLin0724。",
        "| Public author | `RolandLin0724` |",
        "| 公开作者 | `RolandLin0724` |",
    )
    combined = "\n".join((readme, readme_zh, privacy, privacy_zh))
    assert all(line in combined for line in public_identity_lines)
    assert _public_document_link_closure(REPOSITORY_ROOT) == PUBLIC_DOCUMENT_PATHS
    _public_document_link_edges(REPOSITORY_ROOT)

    release_facing_payloads = {
        path.relative_to(REPOSITORY_ROOT).as_posix(): path.read_bytes()
        for path in _release_facing_paths()
    }
    test_source_payloads = {"release-contract-test-source": Path(__file__).read_bytes()}
    _assert_private_checkout_absent(test_source_payloads)
    _assert_privacy_scan_clean(test_source_payloads)
    _assert_private_checkout_absent(release_facing_payloads)
    _assert_privacy_scan_clean(release_facing_payloads)


def _fixture_bytes(path: str) -> bytes:
    return (
        resources.files("research_decision_engine")
        .joinpath(FIXTURE_DIRECTORY, *path.split("/"))
        .read_bytes()
    )


def _materialize_bundle(version: int, destination: Path) -> None:
    destination.mkdir()
    for member in ("run-bundle.json", "run-bundle.json.sha256"):
        (destination / member).write_bytes(_fixture_bytes(f"run-bundle-v{version}/{member}"))


def _metadata_message(raw: bytes) -> Message:
    return BytesParser(policy=policy.compat32).parsebytes(raw)


def _assert_distribution_metadata(message: Message) -> None:
    assert message.get_all("Metadata-Version") == ["2.4"]
    assert message.get_all("Name") == [PACKAGE_NAME]
    assert message.get_all("Version") == [PACKAGE_VERSION]
    requires_python = message.get_all("Requires-Python")
    assert requires_python is not None and len(requires_python) == 1
    assert {term.strip() for term in requires_python[0].split(",")} == {">=3.12", "<3.13"}
    assert message.get_all("Requires-Dist") is None
    assert message.get_all("License-Expression") == [LICENSE_EXPRESSION]
    assert message.get_all("License-File") == ["LICENSE"]
    assert message.get_all("Author") == [PUBLIC_PROJECT_IDENTITY]
    assert message.get_all("Author-email") is None
    assert message.get_all("Maintainer") is None
    assert message.get_all("Maintainer-email") is None
    assert message.get_all("License") is None
    assert not any(
        value.startswith("License ::") for value in (message.get_all("Classifier") or [])
    )


def _run_uv(arguments: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    uv_executable = os.environ.get("UV") or "uv"
    try:
        completed = subprocess.run(
            [uv_executable, *arguments],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AssertionError(f"uv subprocess failed: {type(error).__name__}") from None
    assert completed.returncode == 0, (
        f"uv subprocess failed with return code {completed.returncode}"
    )
    return completed


def _run_isolated(arguments: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    environment["PYTHONNOUSERSITE"] = "1"
    try:
        completed = subprocess.run(
            arguments,
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AssertionError(f"isolated subprocess failed: {type(error).__name__}") from None
    assert completed.returncode == 0, (
        f"isolated subprocess failed with return code {completed.returncode}"
    )
    return completed


def _neutral_temporary_parent() -> str:
    candidates = (
        os.environ.get("RUNNER_TEMP"),
        os.environ.get("TMPDIR"),
        os.environ.get("TEMP"),
        os.environ.get("TMP"),
        f"{os.environ.get('SYSTEMDRIVE', 'C:')}\\" if os.name == "nt" else "/tmp",
    )
    for raw_candidate in candidates:
        if raw_candidate is None:
            continue
        candidate = Path(raw_candidate)
        if not candidate.is_dir():
            continue
        if _privacy_scan_counts({"temporary-parent": str(candidate).encode("utf-8")}) != (
            ZERO_PRIVACY_COUNTS
        ):
            continue
        try:
            with tempfile.TemporaryDirectory(prefix="rde-core-write-probe-", dir=candidate):
                pass
        except OSError:
            continue
        return str(candidate)
    raise AssertionError("no writable privacy-neutral temporary parent")


def _assert_clean_install_contract(
    wheel: Path, license_bytes: bytes, label: str
) -> dict[str, tuple[str, ...]]:
    assert label in {"direct", "sdist-rebuilt"}
    with tempfile.TemporaryDirectory(
        prefix=f"rde-core-{label}-install-", dir=_neutral_temporary_parent()
    ) as neutral_directory:
        neutral_root = Path(neutral_directory)
        neutral_wheel = neutral_root / wheel.name
        shutil.copy2(wheel, neutral_wheel)
        virtual_environment = neutral_root / "venv"
        _run_uv(["venv", "--python", "3.12", str(virtual_environment)], neutral_root)
        installed_python = (
            virtual_environment / "Scripts/python.exe"
            if os.name == "nt"
            else virtual_environment / "bin/python"
        )
        _run_uv(
            [
                "pip",
                "install",
                "--python",
                str(installed_python),
                "--no-deps",
                str(neutral_wheel),
            ],
            neutral_root,
        )
        environment_paths_result = _run_isolated(
            [
                str(installed_python),
                "-c",
                (
                    "import json, sysconfig; "
                    "print(json.dumps({'purelib': sysconfig.get_path('purelib'), "
                    "'scripts': sysconfig.get_path('scripts')}, sort_keys=True))"
                ),
            ],
            neutral_root,
        )
        _assert_privacy_scan_clean(
            {
                "environment-paths-stdout": environment_paths_result.stdout.encode("utf-8"),
                "environment-paths-stderr": environment_paths_result.stderr.encode("utf-8"),
            }
        )
        try:
            environment_paths = cast(dict[str, str], json.loads(environment_paths_result.stdout))
        except json.JSONDecodeError:
            raise AssertionError("installed environment emitted invalid path JSON") from None
        site_packages = Path(environment_paths["purelib"])
        script_directory = Path(environment_paths["scripts"])
        if not site_packages.resolve().is_relative_to(virtual_environment.resolve()):
            raise AssertionError("installed purelib escaped the isolated environment")
        if not script_directory.resolve().is_relative_to(virtual_environment.resolve()):
            raise AssertionError("installed scripts escaped the isolated environment")
        initial_installed_files = tuple(
            path
            for path in (*site_packages.rglob("*"), *script_directory.glob("rde*"))
            if path.is_file()
        )
        initial_installed_payloads = {
            path.relative_to(virtual_environment).as_posix(): path.read_bytes()
            for path in initial_installed_files
        }
        _assert_private_checkout_absent(initial_installed_payloads)
        _assert_privacy_scan_clean(initial_installed_payloads)
        distributions = tuple(
            distribution
            for distribution in importlib_metadata.distributions(path=[str(site_packages)])
            if distribution.metadata["Name"] == PACKAGE_NAME
        )
        assert len(distributions) == 1
        installed_metadata = cast(Message, distributions[0].metadata)
        _assert_distribution_metadata(installed_metadata)
        installed_license = site_packages / DIST_INFO / "licenses" / "LICENSE"
        assert installed_license.read_bytes() == license_bytes
        _assert_package_payloads_equal(
            _package_payloads(site_packages),
            _package_payloads(REPOSITORY_ROOT),
            "installed package",
        )

        installed_contract = _run_isolated(
            [
                str(installed_python),
                "-c",
                (
                    "import sys; from importlib import metadata; from pathlib import Path; "
                    "import research_decision_engine; "
                    "from research_decision_engine.core_contract import "
                    "load_public_api_manifest, resolve_import_path; "
                    "from research_decision_engine.core_fixtures import "
                    "verify_packaged_fixtures; "
                    "package_file = research_decision_engine.__file__; "
                    "assert package_file is not None; "
                    "assert Path(package_file).resolve().is_relative_to("
                    "Path(sys.prefix).resolve()); "
                    f"assert research_decision_engine.__version__ == "
                    f"metadata.version({PACKAGE_NAME!r}) == {PACKAGE_VERSION!r}; "
                    "symbols = load_public_api_manifest()['public_symbols']; "
                    "assert len(symbols) == 112; "
                    "assert all(resolve_import_path(entry['import_path']) is not None "
                    "for entry in symbols); "
                    "fixtures = verify_packaged_fixtures(); "
                    "assert fixtures['schema_version'] == "
                    "'rde-core-canonical-fixture-manifest/v1'; "
                    "assert len(fixtures['fixtures']) == 23"
                ),
            ],
            neutral_root,
        )
        installed_contract_outputs = {
            "installed-contract-stdout": installed_contract.stdout.encode("utf-8"),
            "installed-contract-stderr": installed_contract.stderr.encode("utf-8"),
        }
        _assert_private_checkout_absent(installed_contract_outputs)
        _assert_privacy_scan_clean(installed_contract_outputs)
        if installed_contract.stdout:
            raise AssertionError("installed contract emitted unexpected stdout")

        installed_release_check = _run_isolated(
            [
                str(installed_python),
                "-m",
                "research_decision_engine.core_release_check",
                "--installed",
            ],
            neutral_root,
        )
        installed_release_outputs = {
            "installed-release-check-stdout": installed_release_check.stdout.encode("utf-8"),
            "installed-release-check-stderr": installed_release_check.stderr.encode("utf-8"),
        }
        _assert_private_checkout_absent(installed_release_outputs)
        _assert_privacy_scan_clean(installed_release_outputs)
        try:
            release_result = cast(dict[str, object], json.loads(installed_release_check.stdout))
        except json.JSONDecodeError:
            raise AssertionError("installed release check emitted invalid JSON") from None
        release_checks = release_result.get("checks")
        if release_result.get("overall") != "PASS" or not isinstance(release_checks, list):
            raise AssertionError("installed release check did not pass")
        if len(release_checks) != 10:
            raise AssertionError("installed release check count mismatch")

        installed_cli = script_directory / ("rde.exe" if os.name == "nt" else "rde")
        assert installed_cli.is_file()
        cli_help = _run_isolated([str(installed_cli), "--help"], neutral_root)
        cli_outputs = {
            "installed-cli-stdout": cli_help.stdout.encode("utf-8"),
            "installed-cli-stderr": cli_help.stderr.encode("utf-8"),
        }
        _assert_private_checkout_absent(cli_outputs)
        _assert_privacy_scan_clean(cli_outputs)
        if "usage: rde" not in cli_help.stdout.casefold():
            raise AssertionError("installed CLI help contract mismatch")
        if "Research Decision Engine Core" not in cli_help.stdout:
            raise AssertionError("installed CLI product brand mismatch")

        installed_files = tuple(
            path
            for path in (*site_packages.rglob("*"), *script_directory.glob("rde*"))
            if path.is_file()
        )
        assert any(path.suffix.casefold() == ".pyc" for path in installed_files)
        installed_payloads = {
            path.relative_to(virtual_environment).as_posix(): path.read_bytes()
            for path in installed_files
        }
        _assert_private_checkout_absent(installed_payloads)
        _assert_privacy_scan_clean(installed_payloads)
        return _metadata_projection(installed_metadata)


def _assert_license_distribution_contract(tmp_path: Path) -> None:
    license_path = REPOSITORY_ROOT / "LICENSE"
    assert license_path.is_file()
    license_bytes = license_path.read_bytes()
    assert len(license_bytes) == 11_358
    assert hashlib.sha256(license_bytes).hexdigest() == LICENSE_SHA256
    assert license_bytes.decode("utf-8").encode("utf-8") == license_bytes
    assert not license_bytes.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in license_bytes
    assert license_bytes.count(b"\n") == 202
    assert license_bytes.endswith(b"\n")
    assert not license_bytes.endswith(b"\n\n")

    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = cast(dict[str, object], pyproject["project"])
    authors = cast(list[dict[str, str]], project["authors"])
    assert project["name"] == PACKAGE_NAME
    assert project["description"] == (
        "Research Decision Engine Core: a compact research prototype for sequential synthetic "
        "experiment decisions."
    )
    assert (
        project["version"]
        == research_decision_engine.__version__
        == importlib_metadata.version(PACKAGE_NAME)
        == PACKAGE_VERSION
    )
    assert project["readme"] == "README.md"
    assert project["license"] == LICENSE_EXPRESSION
    assert project["license-files"] == ["LICENSE"]
    assert project["requires-python"] == ">=3.12,<3.13"
    assert project["dependencies"] == []
    assert cast(dict[str, str], project["scripts"]) == {"rde": "research_decision_engine.cli:main"}
    assert authors == [{"name": PUBLIC_PROJECT_IDENTITY}]
    assert all("email" not in author for author in authors)
    assert "maintainers" not in project
    assert "classifiers" not in project
    assert not (REPOSITORY_ROOT / "NOTICE").exists()
    assert cast(dict[str, object], pyproject["build-system"]) == {
        "requires": [UV_BUILD_REQUIREMENT],
        "build-backend": "uv_build",
    }
    tool = cast(dict[str, object], pyproject["tool"])
    assert "hatch" not in tool
    uv_configuration = cast(dict[str, object], tool["uv"])
    assert set(uv_configuration) == {"build-backend", "build-constraint-dependencies"}
    assert uv_configuration["build-constraint-dependencies"] == [UV_BUILD_REQUIREMENT]
    uv_build_configuration = cast(dict[str, object], uv_configuration["build-backend"])
    assert set(uv_build_configuration) == {
        "module-name",
        "module-root",
        "source-exclude",
        "source-include",
    }
    assert uv_build_configuration["module-name"] == "research_decision_engine"
    assert uv_build_configuration["module-root"] == ""
    assert tuple(cast(list[str], uv_build_configuration["source-include"])) == (
        UV_BUILD_SOURCE_INCLUDE
    )
    assert tuple(cast(list[str], uv_build_configuration["source-exclude"])) == (
        UV_BUILD_SOURCE_EXCLUDE
    )

    uv_version = _run_uv(["--version"], REPOSITORY_ROOT).stdout.split()
    assert uv_version[:2] == ["uv", UV_VERSION]
    lock_path = REPOSITORY_ROOT / "uv.lock"
    lock_bytes = lock_path.read_bytes()
    normalized_lock_bytes = lock_bytes.replace(b"\r\n", b"\n")
    assert hashlib.sha256(normalized_lock_bytes).hexdigest() == UV_LOCK_NORMALIZED_SHA256
    candidate_root_version = f'version = "{PACKAGE_VERSION}"\n'.encode("ascii")
    opening_root_version = b'version = "0.1.0"\n'
    assert normalized_lock_bytes.count(candidate_root_version) == 1
    assert opening_root_version not in normalized_lock_bytes
    reconstructed_opening_lock = normalized_lock_bytes.replace(
        candidate_root_version,
        opening_root_version,
        1,
    )
    assert (
        hashlib.sha256(reconstructed_opening_lock).hexdigest() == OPENING_UV_LOCK_NORMALIZED_SHA256
    )
    lock = tomllib.loads(lock_bytes.decode("utf-8"))
    assert lock["version"] == 1
    assert lock["revision"] == 3
    assert lock["requires-python"] == "==3.12.*"
    manifest = cast(dict[str, object], lock["manifest"])
    assert manifest["build-constraints"] == [{"name": "uv-build", "specifier": "==0.11.32"}]
    locked_packages = cast(list[dict[str, object]], lock["package"])
    assert {cast(str, package["name"]) for package in locked_packages} == {
        "ast-serialize",
        "colorama",
        "iniconfig",
        "librt",
        "mypy",
        "mypy-extensions",
        "packaging",
        "pathspec",
        "pluggy",
        "pygments",
        "pytest",
        "research-decision-engine",
        "ruff",
        "typing-extensions",
    }
    assert not {
        "flit-core",
        "hatchling",
        "pdm-backend",
        "poetry-core",
        "setuptools",
        "uv-build",
        "uv_build",
    } & {cast(str, package["name"]) for package in locked_packages}
    root_packages = [package for package in locked_packages if package["name"] == PACKAGE_NAME]
    assert len(root_packages) == 1
    assert root_packages[0]["version"] == PACKAGE_VERSION
    _run_uv(["lock", "--check"], REPOSITORY_ROOT)

    english_block = (
        "## License\n\n"
        "RDE Core is licensed under the Apache License, Version 2.0.\n"
        "See [LICENSE](LICENSE).\n\n"
        "Public project identity: RolandLin0724.\n"
    )
    chinese_block = (
        "## 许可证\n\n"
        "RDE Core 采用 Apache License 2.0。\n"
        "详见 [LICENSE](LICENSE)。\n\n"
        "公开项目身份：RolandLin0724。\n"
    )
    assert (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8").count(english_block) == 1
    assert (REPOSITORY_ROOT / "README.zh-CN.md").read_text(encoding="utf-8").count(
        chinese_block
    ) == 1

    for relative_path in (
        "research_decision_engine/core-public-api-v1.json",
        "research_decision_engine/core-fixtures-v1/public-api-manifest.json",
    ):
        assert (
            hashlib.sha256((REPOSITORY_ROOT / relative_path).read_bytes()).hexdigest()
            == PUBLIC_API_MANIFEST_SHA256
        )
    assert (
        hashlib.sha256(
            (
                REPOSITORY_ROOT / "research_decision_engine/core-fixtures-v1/fixture-manifest.json"
            ).read_bytes()
        ).hexdigest()
        == FIXTURE_MANIFEST_SHA256
    )

    build_directory = tmp_path / "dist"
    build_directory.mkdir()
    _run_uv(
        ["build", "--sdist", "--wheel", "--out-dir", str(build_directory)],
        REPOSITORY_ROOT,
    )
    wheel = build_directory / f"{SDIST_ROOT}-py3-none-any.whl"
    sdist = build_directory / f"{SDIST_ROOT}.tar.gz"
    assert wheel.is_file()
    assert sdist.is_file()

    direct_wheel_contract = _assert_wheel_distribution_contract(wheel, license_bytes)

    sdist_payloads = _read_sdist_payloads(sdist)
    assert len(sdist_payloads) == 121
    assert ".gitignore" not in sdist_payloads
    assert COMMUNITY_HEALTH_PATHS.isdisjoint(sdist_payloads)
    assert sdist_payloads["LICENSE"] == license_bytes
    _assert_distribution_metadata(_metadata_message(sdist_payloads["PKG-INFO"]))

    rebuilt_wheels: list[Path] = []
    rebuilt_contracts: list[dict[str, object]] = []
    for attempt in (1, 2):
        extracted_root = _extract_sdist(sdist, tmp_path / f"extracted-{attempt}")
        rebuilt_directory = tmp_path / f"rebuilt-dist-{attempt}"
        rebuilt_directory.mkdir()
        _run_uv(
            ["build", "--wheel", "--out-dir", str(rebuilt_directory)],
            extracted_root,
        )
        rebuilt_wheel = rebuilt_directory / f"{SDIST_ROOT}-py3-none-any.whl"
        assert rebuilt_wheel.is_file()
        rebuilt_wheels.append(rebuilt_wheel)
        rebuilt_contracts.append(_assert_wheel_distribution_contract(rebuilt_wheel, license_bytes))

    assert rebuilt_contracts == [direct_wheel_contract, direct_wheel_contract]
    direct_install_contract = _assert_clean_install_contract(wheel, license_bytes, "direct")
    rebuilt_install_contract = _assert_clean_install_contract(
        rebuilt_wheels[0], license_bytes, "sdist-rebuilt"
    )
    assert direct_install_contract == rebuilt_install_contract


def test_frozen_public_api_manifest_is_exact_live_surface() -> None:
    packaged = load_public_api_manifest()
    package_manifest_bytes = (
        REPOSITORY_ROOT / "research_decision_engine/core-public-api-v1.json"
    ).read_bytes()
    fixture_manifest_bytes = (
        REPOSITORY_ROOT / "research_decision_engine/core-fixtures-v1/public-api-manifest.json"
    ).read_bytes()

    assert packaged == verify_packaged_manifest_matches_live()
    assert packaged == build_public_api_manifest() == build_public_api_manifest()
    assert package_manifest_bytes == fixture_manifest_bytes == canonical_json_bytes(packaged)
    assert package_manifest_bytes == (
        resources.files("research_decision_engine").joinpath("core-public-api-v1.json").read_bytes()
    )
    assert hashlib.sha256(package_manifest_bytes).hexdigest() == PUBLIC_API_MANIFEST_SHA256

    symbols = cast(list[dict[str, object]], packaged["public_symbols"])
    import_paths = tuple(cast(str, entry["import_path"]) for entry in symbols)
    root_paths = {f"research_decision_engine.{name}" for name in research_decision_engine.__all__}
    assert len(symbols) == len(import_paths) == len(set(import_paths)) == 112
    assert import_paths == tuple(sorted(import_paths))
    assert len(root_paths) == 110
    assert set(import_paths) - root_paths == {
        "research_decision_engine.storage.ExperimentStore",
        "research_decision_engine.storage.SCHEMA_VERSION",
    }
    assert not any("assurance" in path.casefold() for path in import_paths)
    assert all(resolve_import_path(path) is not None for path in import_paths)
    root_extras = {
        name: value
        for name, value in vars(research_decision_engine).items()
        if not name.startswith("_") and name not in research_decision_engine.__all__
    }
    assert root_extras
    assert all(isinstance(value, types.ModuleType) for value in root_extras.values())

    by_path = {cast(str, entry["import_path"]): entry for entry in symbols}
    version_entry = by_path["research_decision_engine.__version__"]
    assert version_entry == {
        "import_path": "research_decision_engine.__version__",
        "introduced_contract": "RDE_CORE_PUBLIC_API_V1",
        "kind": "constant",
        "signature_or_fields": "value_type=str;value='1.0.0rc5'",
        "stability": "STABLE_THROUGH_RDE_1_X",
    }
    opening_manifest = cast(dict[str, object], json.loads(canonical_json_bytes(packaged)))
    opening_symbols = cast(list[dict[str, object]], opening_manifest["public_symbols"])
    opening_version_entries = [
        entry
        for entry in opening_symbols
        if entry["import_path"] == "research_decision_engine.__version__"
    ]
    assert len(opening_version_entries) == 1
    opening_version_entries[0]["signature_or_fields"] = "value_type=str;value='0.1.0'"
    assert (
        hashlib.sha256(canonical_json_bytes(opening_manifest)).hexdigest()
        == OPENING_PUBLIC_API_MANIFEST_SHA256
    )
    assert "public_properties=parameters" in cast(
        str, by_path["research_decision_engine.CandidateSpec"]["signature_or_fields"]
    )
    assert "public_properties=producer" in cast(
        str, by_path["research_decision_engine.RunBundle"]["signature_or_fields"]
    )
    assert "public_methods=evaluate" in cast(
        str, by_path["research_decision_engine.WorkloadAdapter"]["signature_or_fields"]
    )
    error_families = {
        cast(str, family["family"]): set(cast(list[str], family["members"]))
        for family in cast(list[dict[str, object]], packaged["typed_error_families"])
    }
    assert error_families["CommandAdapterError"] < error_families["WorkloadAdapterError"]
    assert error_families["InformationGainContractError"] < error_families["PolicyContractError"]


@pytest.mark.parametrize("case", ["bom", "duplicate", "unknown", "whitespace"])
def test_public_api_manifest_strictly_rejects_malformed_bytes(case: str) -> None:
    manifest = load_public_api_manifest()
    raw = canonical_json_bytes(manifest)
    if case == "bom":
        malformed = b"\xef\xbb\xbf" + raw
    elif case == "duplicate":
        malformed = raw[:-2] + b',"schema_version":"rde-core-public-api-manifest/v1"}\n'
    elif case == "unknown":
        with_unknown = dict(manifest)
        with_unknown["future"] = None
        malformed = canonical_json_bytes(with_unknown)
    else:
        malformed = b" " + raw

    with pytest.raises(CorePublicApiManifestError):
        parse_public_api_manifest_bytes(malformed)


def test_canonical_fixture_generation_and_packaged_verification_are_exact() -> None:
    generated = build_expected_fixture_files()
    regenerated = build_expected_fixture_files()
    manifest = verify_packaged_fixtures()
    loaded_manifest = load_fixture_manifest()

    assert generated == regenerated
    assert manifest == loaded_manifest
    entries = cast(list[dict[str, object]], manifest["fixtures"])
    packaged_paths = {cast(str, entry["path"]) for entry in entries}
    assert set(generated) < packaged_paths
    assert packaged_paths - set(generated) == {
        "core-opening-nodeids.txt",
        "core-test-nodeids.txt",
    }
    all_files = {path: _fixture_bytes(path) for path in packaged_paths}
    assert build_fixture_manifest(all_files) == manifest
    fixture_manifest_bytes = (
        REPOSITORY_ROOT / "research_decision_engine" / FIXTURE_DIRECTORY / "fixture-manifest.json"
    ).read_bytes()
    assert hashlib.sha256(fixture_manifest_bytes).hexdigest() == FIXTURE_MANIFEST_SHA256
    public_entries = [entry for entry in entries if entry["path"] == "public-api-manifest.json"]
    assert public_entries == [
        {
            "byte_count": 59838,
            "path": "public-api-manifest.json",
            "schema": "rde-core-public-api-manifest/v1",
            "semantic_role": "public_api_manifest",
            "sha256": PUBLIC_API_MANIFEST_SHA256,
        }
    ]
    opening_manifest = cast(dict[str, object], json.loads(canonical_json_bytes(manifest)))
    opening_entries = cast(list[dict[str, object]], opening_manifest["fixtures"])
    opening_public_entries = [
        entry for entry in opening_entries if entry["path"] == "public-api-manifest.json"
    ]
    assert len(opening_public_entries) == 1
    opening_public_entries[0]["byte_count"] = 59835
    opening_public_entries[0]["sha256"] = OPENING_PUBLIC_API_MANIFEST_SHA256
    assert (
        hashlib.sha256(canonical_json_bytes(opening_manifest)).hexdigest()
        == OPENING_FIXTURE_MANIFEST_SHA256
    )


def test_runspec_fixtures_are_strict_canonical_and_version_separated() -> None:
    spec_v1 = RunSpec.from_canonical_bytes(_fixture_bytes("run-spec-v1.json"))
    spec_v2 = RunSpecV2.from_canonical_bytes(_fixture_bytes("run-spec-v2.json"))
    spec_v3 = RunSpecV3.from_canonical_bytes(_fixture_bytes("run-spec-v3.json"))

    assert spec_v1.schema == "rde-core-run-spec/v1"
    assert spec_v2.schema == "rde-core-run-spec/v2"
    assert spec_v3.schema == "rde-core-run-spec/v3"
    assert spec_v1.to_canonical_bytes() == _fixture_bytes("run-spec-v1.json")
    assert spec_v2.to_canonical_bytes() == _fixture_bytes("run-spec-v2.json")
    assert spec_v3.to_canonical_bytes() == _fixture_bytes("run-spec-v3.json")


@pytest.mark.parametrize("version", [1, 2, 3])
def test_bundle_fixtures_verify_and_replay_without_workload_execution(
    version: int, tmp_path: Path
) -> None:
    bundle = tmp_path / f"bundle-v{version}"
    replay = tmp_path / f"replay-v{version}"
    _materialize_bundle(version, bundle)
    document = (bundle / "run-bundle.json").read_bytes()
    sidecar = (bundle / "run-bundle.json.sha256").read_bytes()
    payload = cast(dict[str, object], json.loads(document))
    producer = cast(dict[str, object], payload["producer"])
    assert producer["package_version"] == "0.1.0"
    assert sidecar == hashlib.sha256(document).hexdigest().encode("ascii") + b"\n"

    if version == 1:
        verification = verify_run_bundle(bundle)
        result = replay_run_bundle(bundle, replay)
        assert verification.valid is True
        assert result.equivalent is True
        assert result.sqlite_schema_version == 6
        assert result.step_count == len(verification.bundle.steps)
        terminal_summary = dict(verification.bundle.terminal_summary)
    elif version == 2:
        verification_v2 = verify_run_bundle_v2(bundle)
        result_v2 = replay_run_bundle_v2(bundle, replay)
        assert verification_v2.valid is True
        assert result_v2.equivalent is True
        assert result_v2.sqlite_schema_version == 6
        assert result_v2.step_count == len(verification_v2.bundle.steps)
        assert result_v2.adapter_execution_count == 0
        assert result_v2.command_execution_count == 0
        terminal_summary = dict(verification_v2.bundle.terminal_summary)
    else:
        verification_v3 = verify_run_bundle_v3(bundle)
        result_v3 = replay_run_bundle_v3(bundle, replay)
        assert verification_v3.valid is True
        assert result_v3.equivalent is True
        assert result_v3.sqlite_schema_version == 6
        assert result_v3.step_count == len(verification_v3.bundle.steps)
        assert result_v3.adapter_execution_count == 0
        assert result_v3.callable_execution_count == 0
        assert result_v3.command_execution_count == 0
        terminal_summary = dict(verification_v3.bundle.terminal_summary)

    terminal_summaries = cast(
        dict[str, object], json.loads(_fixture_bytes("replay-terminal-summaries-v1.json"))
    )
    assert terminal_summary == terminal_summaries[f"v{version}"]


def test_release_checker_aggregation_is_deterministic_for_pass_and_failure(
    tmp_path: Path,
) -> None:
    def passing() -> Mapping[str, object]:
        return {"stable": True, "versions": [1, 2, 3]}

    passing_checks = (("deterministic", passing),)
    first_pass = execute_release_checks(passing_checks)
    second_pass = execute_release_checks(passing_checks)

    assert first_pass == second_pass
    assert first_pass["overall"] == "PASS"
    assert canonical_release_check_json(first_pass) == canonical_release_check_json(second_pass)
    assert canonical_release_check_json(first_pass).endswith(b"\n")
    assert json.loads(canonical_release_check_json(first_pass)) == first_pass

    class InjectedFailure(RuntimeError):
        pass

    def failing() -> Mapping[str, object]:
        raise InjectedFailure("deterministic injected failure")

    failing_checks = (
        ("before", passing),
        ("injected", failing),
        ("after", passing),
    )
    first_failure = execute_release_checks(failing_checks)
    second_failure = execute_release_checks(failing_checks)

    assert first_failure == second_failure
    assert first_failure["overall"] == "FAIL"
    failure_results = cast(list[dict[str, object]], first_failure["checks"])
    assert [result["status"] for result in failure_results] == ["PASS", "FAIL", "PASS"]
    assert failure_results[1]["details"] == {
        "error_type": "InjectedFailure",
        "error": "deterministic injected failure",
    }
    assert canonical_release_check_json(first_failure) == canonical_release_check_json(
        second_failure
    )

    complete = execute_release_checks()
    assert complete["overall"] == "PASS"
    assert all(
        result["status"] == "PASS" for result in cast(list[dict[str, object]], complete["checks"])
    )
    _assert_community_health_release_contract()
    _assert_security_privacy_release_contract()
    _assert_c7_release_document_contract(tmp_path)
    _assert_license_distribution_contract(tmp_path)
