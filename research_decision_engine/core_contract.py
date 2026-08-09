"""Internal machinery for the frozen RDE Core v1 public API contract."""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import json
from collections.abc import Mapping, Sequence
from importlib import resources
from typing import Any, cast

PUBLIC_API_MANIFEST_RESOURCE = "core-public-api-v1.json"
PUBLIC_API_MANIFEST_SCHEMA = "rde-core-public-api-manifest/v1"
PUBLIC_API_CONTRACT_NAME = "RDE_CORE_PUBLIC_API_V1"
PUBLIC_API_STABILITY = "STABLE_THROUGH_RDE_1_X"

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "contract_name",
        "distribution_name",
        "package_import_root",
        "python_requires",
        "supported_platforms",
        "public_symbols",
        "schema_families",
        "supported_policies",
        "supported_adapters",
        "sqlite_contract",
        "typed_error_families",
        "compatibility_rules",
    }
)
_PUBLIC_SYMBOL_KEYS = frozenset(
    {"import_path", "kind", "signature_or_fields", "stability", "introduced_contract"}
)
_SCHEMA_FAMILY_KEYS = frozenset(
    {"family", "schemas", "support", "recommended_schema", "compatibility_contract"}
)
_POLICY_KEYS = frozenset(
    {
        "policy_id",
        "public_import_path",
        "run_spec_schemas",
        "semantic_classification",
        "dynamic_loading",
    }
)
_ADAPTER_KEYS = frozenset({"adapter_id", "public_import_path", "execution_model", "stability"})
_SQLITE_KEYS = frozenset(
    {
        "latest_schema",
        "new_database_schema",
        "supported_legacy_schemas",
        "migration_edges",
        "migration_model",
        "downgrade_supported",
    }
)
_ERROR_FAMILY_KEYS = frozenset({"family", "members", "stability"})
_COMPATIBILITY_KEYS = frozenset(
    {
        "python_api",
        "immutable_public_record_fields",
        "required_parameter_semantics",
        "truth_free_boundaries",
        "replay_executes_workload",
        "public_typed_error_families",
        "artifact_version_reinterpretation",
        "silent_schema_upgrade",
        "silent_schema_downgrade",
        "unknown_schema_or_fields",
        "recommended_new_run_schema",
        "dynamic_policy_loading",
        "namespace_classifications",
        "cli_entry_point",
    }
)
_NAMESPACE_CLASSIFICATION_KEYS = frozenset({"classification", "scope", "stability_contract"})


class CorePublicApiManifestError(ValueError):
    """The packaged Core public API manifest is malformed or noncanonical."""


def canonical_json_bytes(value: object) -> bytes:
    """Return the repository's exact canonical JSON representation."""

    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CorePublicApiManifestError(f"Duplicate JSON key: {key!r}.")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> object:
    raise CorePublicApiManifestError(f"Nonfinite JSON constant is forbidden: {value}.")


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise CorePublicApiManifestError(f"{context} must be a JSON object.")
    return value


def _sequence(value: object, context: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise CorePublicApiManifestError(f"{context} must be a JSON array.")
    return value


def _require_exact_keys(
    value: Mapping[str, object], expected: frozenset[str], context: str
) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise CorePublicApiManifestError(
            f"{context} fields differ from the frozen schema; "
            f"missing={missing!r}, unknown={unknown!r}."
        )


def _require_string(value: object, context: str) -> str:
    if type(value) is not str or not value:
        raise CorePublicApiManifestError(f"{context} must be a nonempty string.")
    return value


def _require_string_list(value: object, context: str) -> tuple[str, ...]:
    items = _sequence(value, context)
    strings = tuple(_require_string(item, f"{context} item") for item in items)
    if len(strings) != len(set(strings)):
        raise CorePublicApiManifestError(f"{context} contains a duplicate value.")
    return strings


def _validate_manifest_shape(value: Mapping[str, object]) -> None:
    _require_exact_keys(value, _TOP_LEVEL_KEYS, "manifest")
    if value["schema_version"] != PUBLIC_API_MANIFEST_SCHEMA:
        raise CorePublicApiManifestError("Unsupported public API manifest schema.")
    if value["contract_name"] != PUBLIC_API_CONTRACT_NAME:
        raise CorePublicApiManifestError("Unexpected public API contract name.")
    if value["distribution_name"] != "research-decision-engine":
        raise CorePublicApiManifestError("Unexpected distribution name.")
    if value["package_import_root"] != "research_decision_engine":
        raise CorePublicApiManifestError("Unexpected package import root.")
    if value["python_requires"] != ">=3.12,<3.13":
        raise CorePublicApiManifestError("Unexpected Python compatibility contract.")
    if value["supported_platforms"] != ["linux", "windows"]:
        raise CorePublicApiManifestError("Unexpected supported-platform matrix.")

    symbol_paths: list[str] = []
    for index, raw_entry in enumerate(_sequence(value["public_symbols"], "public_symbols")):
        entry = _mapping(raw_entry, f"public_symbols[{index}]")
        _require_exact_keys(entry, _PUBLIC_SYMBOL_KEYS, f"public_symbols[{index}]")
        symbol_paths.append(
            _require_string(entry["import_path"], f"public_symbols[{index}].import_path")
        )
        _require_string(entry["kind"], f"public_symbols[{index}].kind")
        _require_string(
            entry["signature_or_fields"],
            f"public_symbols[{index}].signature_or_fields",
        )
        if entry["stability"] != PUBLIC_API_STABILITY:
            raise CorePublicApiManifestError("A public symbol has an unstable contract.")
        if entry["introduced_contract"] != PUBLIC_API_CONTRACT_NAME:
            raise CorePublicApiManifestError(
                "A public symbol has an unknown introduction contract."
            )
    if symbol_paths != sorted(symbol_paths) or len(symbol_paths) != len(set(symbol_paths)):
        raise CorePublicApiManifestError("public_symbols must be uniquely sorted by import_path.")

    for index, raw_entry in enumerate(_sequence(value["schema_families"], "schema_families")):
        entry = _mapping(raw_entry, f"schema_families[{index}]")
        _require_exact_keys(entry, _SCHEMA_FAMILY_KEYS, f"schema_families[{index}]")
        _require_string(entry["family"], f"schema_families[{index}].family")
        _require_string_list(entry["schemas"], f"schema_families[{index}].schemas")
        _require_string(entry["support"], f"schema_families[{index}].support")
        _require_string(entry["recommended_schema"], f"schema_families[{index}].recommended_schema")
        _require_string(
            entry["compatibility_contract"],
            f"schema_families[{index}].compatibility_contract",
        )

    for index, raw_entry in enumerate(_sequence(value["supported_policies"], "supported_policies")):
        entry = _mapping(raw_entry, f"supported_policies[{index}]")
        _require_exact_keys(entry, _POLICY_KEYS, f"supported_policies[{index}]")
        _require_string(entry["policy_id"], f"supported_policies[{index}].policy_id")
        import_path = entry["public_import_path"]
        if import_path is not None:
            _require_string(import_path, f"supported_policies[{index}].public_import_path")
        _require_string_list(
            entry["run_spec_schemas"], f"supported_policies[{index}].run_spec_schemas"
        )
        _require_string(
            entry["semantic_classification"],
            f"supported_policies[{index}].semantic_classification",
        )
        if entry["dynamic_loading"] is not False:
            raise CorePublicApiManifestError("Dynamic policy loading is forbidden.")

    for index, raw_entry in enumerate(_sequence(value["supported_adapters"], "supported_adapters")):
        entry = _mapping(raw_entry, f"supported_adapters[{index}]")
        _require_exact_keys(entry, _ADAPTER_KEYS, f"supported_adapters[{index}]")
        _require_string(entry["adapter_id"], f"supported_adapters[{index}].adapter_id")
        _require_string(
            entry["public_import_path"], f"supported_adapters[{index}].public_import_path"
        )
        _require_string(entry["execution_model"], f"supported_adapters[{index}].execution_model")
        if entry["stability"] != PUBLIC_API_STABILITY:
            raise CorePublicApiManifestError("A supported adapter has an unstable contract.")

    sqlite_contract = _mapping(value["sqlite_contract"], "sqlite_contract")
    _require_exact_keys(sqlite_contract, _SQLITE_KEYS, "sqlite_contract")
    expected_sqlite = {
        "latest_schema": 6,
        "new_database_schema": 6,
        "supported_legacy_schemas": [1, 2, 3, 4, 5],
        "migration_edges": ["1->2", "2->3", "3->4", "4->5", "5->6"],
        "migration_model": "PER_VERSION_STEP_ATOMIC_AND_RESUMABLE",
        "downgrade_supported": False,
    }
    if dict(sqlite_contract) != expected_sqlite:
        raise CorePublicApiManifestError("SQLite compatibility contract differs from v6.")

    error_families: list[str] = []
    for index, raw_entry in enumerate(
        _sequence(value["typed_error_families"], "typed_error_families")
    ):
        entry = _mapping(raw_entry, f"typed_error_families[{index}]")
        _require_exact_keys(entry, _ERROR_FAMILY_KEYS, f"typed_error_families[{index}]")
        error_families.append(
            _require_string(entry["family"], f"typed_error_families[{index}].family")
        )
        members = _require_string_list(entry["members"], f"typed_error_families[{index}].members")
        if members != tuple(sorted(set(members))):
            raise CorePublicApiManifestError(
                "Typed error members must be uniquely sorted within each catch family."
            )
        if entry["stability"] != PUBLIC_API_STABILITY:
            raise CorePublicApiManifestError("A typed error family has an unstable contract.")
    if error_families != sorted(error_families) or len(error_families) != len(set(error_families)):
        raise CorePublicApiManifestError("Typed error families must be uniquely sorted.")

    compatibility = _mapping(value["compatibility_rules"], "compatibility_rules")
    _require_exact_keys(compatibility, _COMPATIBILITY_KEYS, "compatibility_rules")
    for index, raw_entry in enumerate(
        _sequence(compatibility["namespace_classifications"], "namespace_classifications")
    ):
        entry = _mapping(raw_entry, f"namespace_classifications[{index}]")
        _require_exact_keys(
            entry, _NAMESPACE_CLASSIFICATION_KEYS, f"namespace_classifications[{index}]"
        )
        for key in _NAMESPACE_CLASSIFICATION_KEYS:
            _require_string(entry[key], f"namespace_classifications[{index}].{key}")


def parse_public_api_manifest_bytes(raw: bytes) -> dict[str, object]:
    """Strictly decode, shape-check, and canonicalize manifest bytes."""

    if raw.startswith(b"\xef\xbb\xbf"):
        raise CorePublicApiManifestError("A UTF-8 BOM is forbidden.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CorePublicApiManifestError("Manifest is not strict UTF-8.") from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except (json.JSONDecodeError, CorePublicApiManifestError) as error:
        if isinstance(error, CorePublicApiManifestError):
            raise
        raise CorePublicApiManifestError("Manifest is not strict JSON.") from error
    manifest = dict(_mapping(value, "manifest"))
    _validate_manifest_shape(manifest)
    if raw != canonical_json_bytes(manifest):
        raise CorePublicApiManifestError("Manifest bytes are not canonical JSON with one LF.")
    return manifest


def load_public_api_manifest() -> dict[str, object]:
    """Load the packaged manifest through importlib.resources."""

    raw = (
        resources.files("research_decision_engine")
        .joinpath(PUBLIC_API_MANIFEST_RESOURCE)
        .read_bytes()
    )
    return parse_public_api_manifest_bytes(raw)


def resolve_import_path(import_path: str) -> object:
    """Resolve one frozen import path without a dynamic registry."""

    parts = import_path.split(".")
    for boundary in range(len(parts), 0, -1):
        module_name = ".".join(parts[:boundary])
        try:
            value: object = importlib.import_module(module_name)
        except ModuleNotFoundError as error:
            if error.name != module_name:
                raise
            continue
        for attribute in parts[boundary:]:
            value = getattr(value, attribute)
        return value
    raise ImportError(f"Cannot resolve public import path {import_path!r}.")


def _safe_signature(value: object) -> str:
    try:
        return str(inspect.signature(cast(Any, value)))
    except (TypeError, ValueError):
        return "<no-public-constructor-signature>"


def _annotation_text(value: object) -> str:
    if type(value) is str:
        return value
    return inspect.formatannotation(value)


def _public_property_contracts(value: type[object]) -> list[str]:
    contracts: list[str] = []
    for name, member in inspect.getmembers(value):
        if name.startswith("_") or not isinstance(member, property):
            continue
        signature = "<unreadable>" if member.fget is None else _safe_signature(member.fget)
        contracts.append(f"{name}{signature}")
    return contracts


def _public_method_contracts(value: type[object]) -> list[str]:
    contracts: list[str] = []
    for name, member in inspect.getmembers(value):
        if name.startswith("_") or not (inspect.isfunction(member) or inspect.ismethod(member)):
            continue
        module = getattr(member, "__module__", "") or ""
        if module.startswith("research_decision_engine"):
            contracts.append(f"{name}{_safe_signature(member)}")
    return contracts


def _signature_or_fields(import_path: str, value: object) -> str:
    if inspect.isclass(value):
        value_type = cast(type[object], value)
        bases = ",".join(f"{base.__module__}.{base.__qualname__}" for base in value_type.__bases__)
        parts = [f"signature{_safe_signature(value)}", f"bases={bases}"]
        if dataclasses.is_dataclass(value):
            public_fields = [
                f"{field.name}:{_annotation_text(field.type)}"
                for field in dataclasses.fields(value)
                if not field.name.startswith("_")
            ]
            frozen = bool(cast(Any, value).__dataclass_params__.frozen)
            slotted = hasattr(value, "__slots__")
            parts.extend(
                (
                    f"public_fields={','.join(public_fields)}",
                    f"frozen={str(frozen).lower()}",
                    f"slots={str(slotted).lower()}",
                )
            )
        properties = _public_property_contracts(value_type)
        if import_path == "research_decision_engine.storage.ExperimentStore":
            method_names = (
                "__enter__",
                "__exit__",
                "add_workload_experiment",
                "init_schema",
                "list_workload_experiments",
                "schema_version",
            )
            methods = [
                f"{name}{_safe_signature(getattr(value_type, name))}" for name in method_names
            ]
        else:
            methods = _public_method_contracts(value_type)
        parts.extend(
            (
                f"public_properties={'|'.join(properties)}",
                f"public_methods={'|'.join(methods)}",
            )
        )
        return ";".join(parts)
    if inspect.isfunction(value):
        return f"signature{_safe_signature(value)}"
    if import_path.endswith(".INFORMATION_GAIN_NUMERIC_CONTRACT"):
        payload = value.to_payload()  # type: ignore[attr-defined]
        return f"value={canonical_json_bytes(payload).decode('utf-8').rstrip()}"
    return f"value_type={type(value).__name__};value={value!r}"


def _symbol_kind(value: object) -> str:
    if inspect.isclass(value):
        if issubclass(value, BaseException):
            return "typed_error"
        if dataclasses.is_dataclass(value):
            return "immutable_record"
        if bool(getattr(value, "_is_protocol", False)):
            return "protocol"
        return "class"
    if inspect.isfunction(value):
        return "function"
    return "constant"


def _public_import_paths() -> tuple[str, ...]:
    package = importlib.import_module("research_decision_engine")
    root_paths = tuple(f"research_decision_engine.{name}" for name in package.__all__)
    direct_paths = (
        "research_decision_engine.storage.ExperimentStore",
        "research_decision_engine.storage.SCHEMA_VERSION",
    )
    paths = tuple(sorted((*root_paths, *direct_paths)))
    if len(paths) != 112 or len(paths) != len(set(paths)):
        raise RuntimeError("The frozen Core v1 public import inventory is not exactly 112 symbols.")
    return paths


def public_symbol_entries() -> list[dict[str, object]]:
    """Describe the exact live public surface in deterministic order."""

    return [
        {
            "import_path": import_path,
            "kind": _symbol_kind(value),
            "signature_or_fields": _signature_or_fields(import_path, value),
            "stability": PUBLIC_API_STABILITY,
            "introduced_contract": PUBLIC_API_CONTRACT_NAME,
        }
        for import_path in _public_import_paths()
        for value in (resolve_import_path(import_path),)
    ]


def _typed_error_families(
    public_symbols: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    error_paths = tuple(
        str(entry["import_path"]) for entry in public_symbols if entry["kind"] == "typed_error"
    )
    family_roots = (
        "CommandAdapterError",
        "InformationGainContractError",
        "PolicyContractError",
        "RunBundleError",
        "RunBundleV2Error",
        "RunBundleV3Error",
        "WorkloadAdapterError",
    )
    families: dict[str, list[str]] = {root: [] for root in family_roots}
    root_classes = {
        root: resolve_import_path(f"research_decision_engine.{root}") for root in family_roots
    }
    for import_path in error_paths:
        error_class = resolve_import_path(import_path)
        assert inspect.isclass(error_class) and issubclass(error_class, BaseException)
        assigned = False
        for family in family_roots:
            root_class = root_classes[family]
            assert inspect.isclass(root_class)
            if issubclass(error_class, root_class):
                families[family].append(import_path)
                assigned = True
        if not assigned:
            raise RuntimeError(f"Unclassified public typed error {import_path}.")
    return [
        {
            "family": family,
            "members": sorted(members),
            "stability": PUBLIC_API_STABILITY,
        }
        for family, members in sorted(families.items())
        if members
    ]


def build_public_api_manifest() -> dict[str, object]:
    """Build the expected manifest from live source and frozen semantic decisions."""

    public_symbols = public_symbol_entries()
    return {
        "schema_version": PUBLIC_API_MANIFEST_SCHEMA,
        "contract_name": PUBLIC_API_CONTRACT_NAME,
        "distribution_name": "research-decision-engine",
        "package_import_root": "research_decision_engine",
        "python_requires": ">=3.12,<3.13",
        "supported_platforms": ["linux", "windows"],
        "public_symbols": public_symbols,
        "schema_families": [
            {
                "family": "RunBundle",
                "schemas": [
                    "rde-core-run-bundle/v1",
                    "rde-core-run-bundle/v2",
                    "rde-core-run-bundle/v3",
                ],
                "support": "SUPPORTED_THROUGH_RDE_1_X",
                "recommended_schema": "rde-core-run-bundle/v3",
                "compatibility_contract": "FROZEN_CANONICAL_BYTES_NO_REINTERPRETATION",
            },
            {
                "family": "RunSpec",
                "schemas": [
                    "rde-core-run-spec/v1",
                    "rde-core-run-spec/v2",
                    "rde-core-run-spec/v3",
                ],
                "support": "SUPPORTED_THROUGH_RDE_1_X",
                "recommended_schema": "rde-core-run-spec/v3",
                "compatibility_contract": "FROZEN_CANONICAL_BYTES_NO_REINTERPRETATION",
            },
            {
                "family": "replay",
                "schemas": [
                    "RECORDED_OBSERVATION_DECISION_REPLAY_V1",
                    "RECORDED_OBSERVATION_DECISION_REPLAY_V2",
                    "RECORDED_OBSERVATION_DECISION_REPLAY_V3",
                ],
                "support": "SUPPORTED_THROUGH_RDE_1_X",
                "recommended_schema": "RECORDED_OBSERVATION_DECISION_REPLAY_V3",
                "compatibility_contract": "RECORDED_ONLY_ZERO_WORKLOAD_EXECUTION",
            },
        ],
        "supported_policies": [
            {
                "policy_id": "greedy_prior",
                "public_import_path": "research_decision_engine.PriorGreedyPolicy",
                "run_spec_schemas": ["rde-core-run-spec/v2", "rde-core-run-spec/v3"],
                "semantic_classification": "STATIC_TRUTH_FREE_PRIOR_UTILITY_GREEDY",
                "dynamic_loading": False,
            },
            {
                "policy_id": "information_gain_table",
                "public_import_path": "research_decision_engine.TableInformationGainPolicy",
                "run_spec_schemas": ["rde-core-run-spec/v3"],
                "semantic_classification": (
                    "USER_DECLARED_FINITE_HYPOTHESIS_OUTCOME_LIKELIHOOD_TABLE"
                ),
                "dynamic_loading": False,
            },
            {
                "policy_id": "random",
                "public_import_path": None,
                "run_spec_schemas": [
                    "rde-core-run-spec/v1",
                    "rde-core-run-spec/v2",
                    "rde-core-run-spec/v3",
                ],
                "semantic_classification": "SEEDED_RANDOM_WITHOUT_REPLACEMENT",
                "dynamic_loading": False,
            },
        ],
        "supported_adapters": [
            {
                "adapter_id": "command",
                "public_import_path": "research_decision_engine.CommandAdapter",
                "execution_model": "DIRECT_CHILD_PROCESS_SHELL_FALSE_NOT_A_SANDBOX",
                "stability": PUBLIC_API_STABILITY,
            },
            {
                "adapter_id": "python_function",
                "public_import_path": "research_decision_engine.PythonFunctionAdapter",
                "execution_model": "TRUSTED_SAME_PROCESS_CALLABLE",
                "stability": PUBLIC_API_STABILITY,
            },
            {
                "adapter_id": "workload_protocol",
                "public_import_path": "research_decision_engine.WorkloadAdapter",
                "execution_model": "STRUCTURAL_TRUTH_FREE_EVALUATION_PROTOCOL",
                "stability": PUBLIC_API_STABILITY,
            },
        ],
        "sqlite_contract": {
            "latest_schema": 6,
            "new_database_schema": 6,
            "supported_legacy_schemas": [1, 2, 3, 4, 5],
            "migration_edges": ["1->2", "2->3", "3->4", "4->5", "5->6"],
            "migration_model": "PER_VERSION_STEP_ATOMIC_AND_RESUMABLE",
            "downgrade_supported": False,
        },
        "typed_error_families": _typed_error_families(public_symbols),
        "compatibility_rules": {
            "python_api": "BACKWARD_COMPATIBLE",
            "immutable_public_record_fields": "NO_REMOVE_RENAME_OR_RETYPE_THROUGH_RDE_1_X",
            "required_parameter_semantics": "NO_REINTERPRETATION_THROUGH_RDE_1_X",
            "truth_free_boundaries": "PRESERVED",
            "replay_executes_workload": False,
            "public_typed_error_families": "PRESERVED_THROUGH_RDE_1_X",
            "artifact_version_reinterpretation": False,
            "silent_schema_upgrade": False,
            "silent_schema_downgrade": False,
            "unknown_schema_or_fields": "FAIL_CLOSED",
            "recommended_new_run_schema": "V3",
            "dynamic_policy_loading": False,
            "namespace_classifications": [
                {
                    "classification": "ASSURANCE_EXPERIMENTAL",
                    "scope": "research_decision_engine.benchmarks.broader_*",
                    "stability_contract": "NOT_CORE_V1_PUBLIC",
                },
                {
                    "classification": "CORE_EXPERIMENTAL",
                    "scope": "closed_loop and opt-in experimental membership",
                    "stability_contract": "NOT_CORE_V1_PUBLIC",
                },
                {
                    "classification": "CORE_V1_INTERNAL",
                    "scope": "implementation names absent from public_symbols",
                    "stability_contract": "NO_COMPATIBILITY_PROMISE",
                },
                {
                    "classification": "CORE_V1_PUBLIC",
                    "scope": "exact public_symbols inventory",
                    "stability_contract": PUBLIC_API_STABILITY,
                },
                {
                    "classification": "DEPRECATED_CANDIDATE",
                    "scope": "none at contract establishment",
                    "stability_contract": "EMPTY_SET",
                },
            ],
            "cli_entry_point": "rde=research_decision_engine.cli:main",
        },
    }


def verify_packaged_manifest_matches_live() -> dict[str, object]:
    """Return the manifest after exact live-source equivalence verification."""

    manifest = load_public_api_manifest()
    expected = build_public_api_manifest()
    if manifest != expected:
        raise CorePublicApiManifestError("Packaged manifest differs from the live public API.")
    return manifest
