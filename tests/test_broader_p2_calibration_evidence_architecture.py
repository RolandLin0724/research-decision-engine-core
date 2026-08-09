"""Adversarial C0 tests for the test-owned Stage-2F architecture boundary."""
# ruff: noqa: E501, UP014

from __future__ import annotations

import ast
import hashlib
import importlib.machinery
import inspect
import time
import tracemalloc
from collections import namedtuple
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Literal, NamedTuple, cast

import pytest

from tests import p2_calibration_evidence_architecture_guard as architecture
from tests import p2_returned_run_architecture_guard as qualified

_PRODUCTION_ROOT = Path(__file__).resolve().parents[1] / "research_decision_engine"
_BENCHMARKS = _PRODUCTION_ROOT / "benchmarks"
_HARNESS_PATH = Path(__file__).with_name("p2_calibration_evidence_harness.py")


class Case(NamedTuple):
    id: str
    source: str
    expected: str


class Mutation(NamedTuple):
    id: str
    mutate: Callable[[str], str]
    expected: architecture.Finding


class LogicalCase(NamedTuple):
    id: str
    source: str
    expected: frozenset[architecture.Finding]
    exact: bool = False


class BatchResult(NamedTuple):
    case_ids: tuple[str, ...]
    executed_ids: tuple[str, ...]
    observed: tuple[tuple[str, tuple[architecture.Finding, ...]], ...]
    missing: tuple[tuple[str, tuple[architecture.Finding, ...]], ...]
    unexpected: tuple[tuple[str, tuple[architecture.Finding, ...]], ...]
    exceptions: tuple[tuple[str, str], ...]


class SourceMatrixCase(NamedTuple):
    id: str
    manifest: architecture.PhaseManifest
    source: str
    expected: frozenset[architecture.Finding]
    exact: bool
    source_line: int
    callable_provenance: str
    active_repository: bool = False


class MetadataCase(NamedTuple):
    id: str
    requirement: object


# fmt: off
_HOOK_NAMES = ("split", "__str__", "__getattr__", "__iter__", "__len__", "__getitem__", "__eq__", "__ne__", "__hash__", "__bool__", "__call__")
# fmt: on


class HostileMetadata:
    def __init__(self, truth: bool = True) -> None:
        self.truth = truth
        self.counts = dict.fromkeys(_HOOK_NAMES, 0)

    def _hit(self, name: str) -> None:
        self.counts[name] += 1

    def split(self, *_args: object, **_kwargs: object) -> list[str]:
        self._hit("split")
        return []

    def __str__(self) -> str:
        self._hit("__str__")
        return "0|Name|exact|direct|unrelated-local|0|none|"

    def __getattr__(self, _name: str) -> HostileMetadata:
        self._hit("__getattr__")
        return self

    def __iter__(self) -> Iterable[object]:
        self._hit("__iter__")
        return iter(())

    def __len__(self) -> int:
        self._hit("__len__")
        return 1

    def __getitem__(self, _key: object) -> HostileMetadata:
        self._hit("__getitem__")
        return self

    def __eq__(self, _other: object) -> bool:
        self._hit("__eq__")
        return True

    def __ne__(self, _other: object) -> bool:
        self._hit("__ne__")
        return False

    def __hash__(self) -> int:
        self._hit("__hash__")
        return 1

    def __bool__(self) -> bool:
        self._hit("__bool__")
        return self.truth

    def __call__(self, *_args: object, **_kwargs: object) -> HostileMetadata:
        self._hit("__call__")
        return self


class HostileCodecString(str):
    counts: dict[str, int]

    def __new__(cls, value: str) -> HostileCodecString:
        instance = super().__new__(cls, value)
        instance.counts = dict.fromkeys(_HOOK_NAMES, 0)
        return instance

    def split(self, *_args: object, **_kwargs: object) -> list[str]:
        self.counts["split"] += 1
        return ["hostile"]

    def __str__(self) -> str:
        self.counts["__str__"] += 1
        return super().__str__()


# fmt: off
CallShapeMatrixCase = NamedTuple("CallShapeMatrixCase", [("id", str), ("manifest", architecture.PhaseManifest), ("source", str), ("requirements", tuple[architecture.RequiredCall, ...]), ("expected_matches", tuple[bool, ...]), ("expected", frozenset[architecture.Finding]), ("exact", bool), ("resolved_targets", tuple[str, ...]), ("argument_binding_results", tuple[str, ...]), ("finding", architecture.Finding | None)])
# fmt: on


def _evaluate_batch(
    cases: tuple[LogicalCase, ...],
    evaluate: Callable[[str], Iterable[architecture.Finding]],
) -> BatchResult:
    case_ids = tuple(case.id for case in cases)
    duplicates = tuple(
        sorted(case_id for case_id in frozenset(case_ids) if case_ids.count(case_id) > 1)
    )
    if duplicates:
        raise AssertionError(f"duplicate logical case IDs: {', '.join(duplicates)}")

    executed: list[str] = []
    recorded: list[tuple[str, tuple[architecture.Finding, ...]]] = []
    missing: list[tuple[str, tuple[architecture.Finding, ...]]] = []
    unexpected: list[tuple[str, tuple[architecture.Finding, ...]]] = []
    exceptions: list[tuple[str, str]] = []
    for case in cases:
        executed.append(case.id)
        try:
            observed = frozenset(evaluate(case.source))
        except Exception as error:  # noqa: BLE001 - an analyzer case must not mask later cases
            recorded.append((case.id, ()))
            exceptions.append((case.id, f"{type(error).__name__}: {error}"))
            continue
        recorded.append((case.id, tuple(sorted(observed))))
        absent = tuple(sorted(case.expected - observed))
        extra = tuple(sorted(observed - case.expected)) if case.exact else ()
        if absent:
            missing.append((case.id, absent))
        if extra:
            unexpected.append((case.id, extra))
    return BatchResult(
        case_ids,
        tuple(executed),
        tuple(recorded),
        tuple(missing),
        tuple(unexpected),
        tuple(exceptions),
    )


def _assert_batch(result: BatchResult) -> None:
    failures = (
        *(f"{case_id}: missing {findings!r}" for case_id, findings in result.missing),
        *(f"{case_id}: unexpected {findings!r}" for case_id, findings in result.unexpected),
        *(f"{case_id}: raised {error}" for case_id, error in result.exceptions),
    )
    recorded_ids = tuple(case_id for case_id, _ in result.observed)
    assert (
        result.executed_ids == result.case_ids and recorded_ids == result.case_ids and not failures
    ), "\n".join(failures)


def _production_sources() -> dict[str, str]:
    sources = {}
    for path in _PRODUCTION_ROOT.rglob("*.py"):
        parts = path.relative_to(_PRODUCTION_ROOT).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        module = ".".join(("research_decision_engine", *parts))
        sources[module] = path.read_text(encoding="utf-8")
    return sources


# fmt: off
_P2_PRODUCTION_TOP_LEVEL_NAMES = architecture._names("CalibrationSourceObservationProjection _SOURCE_OBSERVATION_SCHEMA _ORACLE_NAMESPACE _SOURCE_OBSERVATION_FIELDS _P2_PREDICATE_PATHS _OracleImplementationRelation _OraclePredecessor _SourceObservationEvidence _P2SelectionEvidence _P2PredicateCounts _P2AllPredicateCounts _P2ValidationOutcome _exact_ascii_string _exact_oracle_key_id _exact_hex_bytes _exact_f64_string _exact_decimal_string _lower_hex_bytes _source_mapping _source_arm _source_key_fields _source_namespace _source_schema _source_seed _calibration_source_observation_mapping _decode_calibration_source_observation_projection _source_observation_preimage source_observation_identity _oracle_key_id _outcome_digest _source_observation_matches _oracle_binding_failure _oracle_key_failure _outcome_failure _source_observation_failure _p2_selection_shape _oracle_predecessor_shape _matching_h64 _oracle_implementation _candidate_pair_scope _replication_scope _exact_frozen_world _predicate_3o_2_0 _source_evidence_at _require_exact_source_observation_object _validate_source_observation_key_surface _validate_source_observation_outcome_surface _validate_complete_source_observation_surface _expected_source_coordinate _predicate_3o_2_1 _expected_observation_f64 _predicate_3o_3_1 _first_source_mismatch _predicate_3o_4_1 _p2_outcome _validate_stage2f_p2")
_P2_PRODUCTION_IMPORT_NAMES = architecture._names("BenchmarkWorld HiddenWorldParameters ORACLE_VERSION PublicWorldDefinition calibration_key hidden_arm_mean hidden_observation_sigma runtime_id transform_key")
_P3_PRODUCTION_TOP_LEVEL_NAMES = architecture._names("_SCIENTIFIC_SELECTION_FIELDS _I64_MIN _I64_MAX _P3_PREDICATE_PATH ScientificCalibrationSelectionProjection _P3SelectionInput _P3AllPredicateCounts _P3ValidationOutcome _exact_i64 _exact_nfc_string _scientific_calibration_selection_mapping _decode_scientific_calibration_selection_projection _selector_result_failure _first_effect_mismatch _first_run_effect_mismatch _first_observation_mismatch _first_run_observation_mismatch _first_history_nonidentity_mismatch _first_scientific_projection_mismatch _predicate_3o_5_1 _p3_outcome _validate_stage2f_p3")
_P3_PRODUCTION_IMPORT_NAMES = architecture._names("SIGMA_FLOOR CALIBRATION_ELIGIBILITY_BASIS CALIBRATION_SIGMA_DDOF CALIBRATION_SOURCE_SEQUENCE_CUTOFF RunProvenanceError expected_calibration_effect replay_calibration_history_selection ReturnedResultsProjection RevealedObservation ProvenanceValueProjection ReturnedRunProjection RunCalibrationEstimateProjection RunCalibrationProjection RunMatchedEffectProjection RunObservationAuthorizationProjection RunProvenanceProjection RunRevealedObservationProjection reconstruct_matched_effect WORLDS_BY_ID candidate_costs")
_P3_PRODUCTION_IMPORT_MODULES = architecture._names("hashlib statistics unicodedata")
# fmt: on


def _without_top_level_surface(
    source: str,
    *,
    names: frozenset[str],
    import_names: frozenset[str],
    import_modules: frozenset[str] = frozenset(),
) -> str:
    tree = ast.parse(source)
    dropped_lines: set[int] = set()
    for node in tree.body:
        name: str | None = None
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        elif isinstance(node, ast.Assign):
            assigned_names = tuple(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
            if len(assigned_names) == 1:
                name = assigned_names[0]
        elif isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
            name = node.name.id
        remove = (
            name in names
            or isinstance(node, ast.Import)
            and any(item.name in import_modules for item in node.names)
            or isinstance(node, ast.ImportFrom)
            and any(item.name in import_names for item in node.names)
        )
        if not remove:
            continue
        decorators = (
            node.decorator_list
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            else ()
        )
        first_line = min((decorator.lineno for decorator in decorators), default=node.lineno)
        dropped_lines.update(range(first_line, (node.end_lineno or node.lineno) + 1))
    return "".join(
        line
        for line_number, line in enumerate(source.splitlines(keepends=True), start=1)
        if line_number not in dropped_lines
    )


def _active_p2_source() -> str:
    """Project the active append-only module back to its approved P2 surface."""

    source = (_BENCHMARKS / "broader_calibration_evidence.py").read_text(encoding="utf-8")
    projected = _without_top_level_surface(
        source,
        names=_P3_PRODUCTION_TOP_LEVEL_NAMES,
        import_names=_P3_PRODUCTION_IMPORT_NAMES,
        import_modules=_P3_PRODUCTION_IMPORT_MODULES,
    )
    type_checking_import = (
        "    from research_decision_engine.benchmarks.broader_returned_run import (\n"
        "        RunMatchedEffectProjection as _RunMatchedEffectProjection,\n"
        "    )\n"
    )
    anchor = (
        "    from research_decision_engine.benchmarks.broader_calibration_history import (\n"
        "        CalibrationHistorySelection as _CalibrationHistorySelection,\n"
        "    )\n"
    )
    assert anchor in projected
    return projected.replace(anchor, anchor + type_checking_import, 1)


def _historical_p1_source() -> str:
    """Project the active append-only module back to its approved P1 surface."""

    return _without_top_level_surface(
        _active_p2_source(),
        names=_P2_PRODUCTION_TOP_LEVEL_NAMES,
        import_names=_P2_PRODUCTION_IMPORT_NAMES,
    )


def _historical_p1_harness_source() -> str:
    """Return the approved P1 harness body without the append-only P2 fixture."""

    source = _HARNESS_PATH.read_text(encoding="utf-8")
    marker = "\ndef source_observation_mapping("
    marker_index = source.index(marker)
    return source[:marker_index].replace("    _P3SelectionInput,\n", "") + "\n"


def _active_p2_harness_source() -> str:
    """Project the append-only harness back to its approved P2 fixture surface."""

    source = _HARNESS_PATH.read_text(encoding="utf-8")
    marker = "\ndef _p3_physical_cost("
    marker_index = source.index(marker)
    return source[:marker_index].replace("    _P3SelectionInput,\n", "") + "\n"


def _scientific_identity_mapping_lines(indent: str) -> list[str]:
    list_fields = {
        "effect_values",
        "source_effect_ids",
        "source_effect_payload_sha256",
        "source_oracle_key_ids",
        "source_replication_ids",
    }
    pair_fields = {"source_candidate_pairs", "source_observation_identities"}
    lines = [f"{indent}{{"]
    for field in architecture.PROJECTION_FIELDS["ScientificCalibrationSelectionProjection"]:
        if field in list_fields:
            expression = f"list(expected_projection.{field})"
        elif field in pair_fields:
            expression = f"[list(pair) for pair in expected_projection.{field}]"
        else:
            expression = f"expected_projection.{field}"
        lines.append(f'{indent}    "{field}": {expression},')
    lines.append(f"{indent}}},")
    return lines


# fmt: off
def _future_source(manifest: architecture.PhaseManifest) -> str:
    schemas, domains = dict(manifest.schemas), dict(manifest.identity_domains)
    lines = f'from research_decision_engine.belief_models import MatchedEffectObservation as _MatchedEffectObservation\nfrom {architecture._REPLAY} import raw_effect_sha256 as _raw_effect_sha256\nfrom research_decision_engine.benchmarks.broader_protocol import protocol_hash as _protocol_hash\n_CALIBRATION_NAMESPACE = "rde.broader.calibration-outcome/v1"\n_STUDY = "broader-closed-loop-replication/v1"\n_ORACLE_NAMESPACE = "broader_selected_only_oracle/v1"\n_PROTOCOL_CHECKPOINT = "89c0b4fadba33b9fd9a257b43eacf476b7779d59"\n_EVIDENCE_CONTRACT_CHECKPOINT = "cbeea072ed39697e2cd42ca571685faed5f6ead8"\n_SOURCE_SEQUENCE_CUTOFF = 1\n_PAIR_ARM_ORDER = ("adam", "sgd")\n_REPLICATIONS = (1, 2, 3, 4, 5)\ndef _effect_payload_sha256(effect: _MatchedEffectObservation):\n    return _raw_effect_sha256(effect)'.splitlines()
    if manifest.phase in {"P2", "P3", "P4"}:
        protocol_line = next(index for index, line in enumerate(lines) if "protocol_hash as _protocol_hash" in line)
        lines[protocol_line] = lines[protocol_line].replace("protocol_hash as _protocol_hash", "protocol_hash as _protocol_hash, runtime_id as _runtime_id")
    if manifest.phase in {"P3", "P4"}:
        lines.insert(1, f"from {architecture._REPLAY} import replay_calibration_history_selection as _replay_calibration_history_selection")
        lines += ["_CALIBRATION_SOURCE_SEQUENCE_CUTOFF = 1"]
    if manifest.phase == "P1":
        lines[0:0] = ["from dataclasses import dataclass as _dataclass", "from typing import Literal as _Literal"]
        lines += ["@_dataclass(frozen=True, slots=True)", "class CalibrationCandidatePairProjection:", "    adam_candidate_id: str", "    comparison_group_id: str", "    replication_id: str", f"    schema_version: _Literal[{schemas['CalibrationCandidatePairProjection']!r}]", "    sgd_candidate_id: str", "    world_id: str", "    def __post_init__(self) -> None:", "        _calibration_candidate_pair_mapping(self)", "@_dataclass(frozen=True, slots=True)", "class StrictChronologyProjection:", "    current_effect_excluded: _Literal[True]", "    current_observation_excluded: _Literal[True]", "    effect_available_sequences: tuple[int, int, int, int, int]", "    future_history_excluded: _Literal[True]", f"    schema_version: _Literal[{schemas['StrictChronologyProjection']!r}]", "    source_sequence_cutoff: _Literal[1]", "    def __post_init__(self) -> None:", "        _strict_chronology_mapping(self)", "def _calibration_candidate_pair_mapping(projection):", "    return {}", "def _decode_calibration_candidate_pair_projection(mapping):", "    return mapping", "def _calibration_candidate_pair_preimage(projection: CalibrationCandidatePairProjection) -> dict[str, object]:", "    mapping = _calibration_candidate_pair_mapping(projection)", "    decoded = _decode_calibration_candidate_pair_projection(mapping)", "    if decoded != projection:", "        pass", "    return mapping", "def _strict_chronology_mapping(projection):", "    return {}", "def _decode_strict_chronology_projection(mapping):", "    return mapping", "def _strict_chronology_preimage(projection: StrictChronologyProjection) -> dict[str, object]:", "    mapping = _strict_chronology_mapping(projection)", "    decoded = _decode_strict_chronology_projection(mapping)", "    if decoded != projection:", "        pass", "    return mapping", "def calibration_candidate_pair_id(projection: CalibrationCandidatePairProjection) -> str:", f"    return _protocol_hash({domains['calibration_candidate_pair_id']!r}, _calibration_candidate_pair_preimage(projection))", "def strict_chronology_id(projection: StrictChronologyProjection) -> str:", f"    return _protocol_hash({domains['strict_chronology_id']!r}, _strict_chronology_preimage(projection))"]
    else:
        for name in sorted(manifest.projection_classes):
            lines += [f"class {name}:", *(f"    {field}: object" if field != "schema_version" else f"    schema_version = {schemas[name]!r}" for field in architecture.PROJECTION_FIELDS[name])]
        for name in sorted(manifest.identity_functions):
            lines += [f"def {name}(projection):", f"    return _protocol_hash({domains[name]!r}, projection)"]
    if manifest.phase in {"P2", "P3", "P4"}:
        lines += ["def _oracle_key_id(key_fields):", "    return _runtime_id('oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})", "def _outcome_digest(oracle_key_id, revealed_observation):", "    return _protocol_hash('revealed_outcome/v1', {'oracle_key_id': oracle_key_id, 'revealed_observation': revealed_observation})", "def _source_observation_matches(projection: CalibrationSourceObservationProjection, carried_source_observation_identity: str):", "    return source_observation_identity(projection) == carried_source_observation_identity"]
    if manifest.phase in {"P3", "P4"}:
        replay_names = ("replay_run_id", "world_id", "seed", "comparison_group_id", "group_index", "expected_observations", "expected_effects", "physical_cost", "recorded_observations", "recorded_effects", "expected_projection")
        lines += ["", f"def _predicate_3o_5_1({', '.join(replay_names)}):", "    actual_helper_result = _replay_calibration_history_selection(", "        run_id=replay_run_id,", *(f"        {name}={name}," for name in replay_names[1:-1]), "        source_sequence_cutoff=_CALIBRATION_SOURCE_SEQUENCE_CUTOFF,", "    )", "    expected_selector_result_identity = _protocol_hash(", f"        {domains['selection_identity']!r},", *_scientific_identity_mapping_lines("        "), "    )", "    return (actual_helper_result, expected_selector_result_identity)"]
    return "\n".join(lines) + "\n"
# fmt: on


# fmt: off
def _required_call(name: str) -> architecture.RequiredCall:
    return next(requirement for requirement in architecture.REQUIRED_CALLS if requirement.name == name)


def _low_level_required_call_matches(source: str, requirement: architecture.RequiredCall) -> frozenset[architecture.RequiredCallMatch]:
    tree = ast.parse(source)
    analysis = qualified.analyze_qualified_symbols(source, module_name=architecture.CANONICAL_MODULE)
    return architecture._required_call_matches(tree, analysis, requirement)


def _with_positional_expression(requirement: architecture.RequiredCall, index: int, expression: architecture.ExpressionConstraint) -> architecture.RequiredCall:
    positional = list(requirement.call_shape.positional)
    positional[index] = expression
    return requirement._replace(call_shape=requirement.call_shape._replace(positional=tuple(positional)))


def _fresh_call_shape_source(manifest: architecture.PhaseManifest) -> str:
    domains, fixed = dict(manifest.identity_domains), dict(architecture.FUTURE_FIXED_LITERALS)
    lines = ["from research_decision_engine.belief_models import MatchedEffectObservation as _MatrixMatchedEffectObservation", f"from {architecture._REPLAY} import raw_effect_sha256 as _matrix_raw_effect_sha256", f"from {architecture._PROTOCOL} import protocol_hash as _matrix_protocol_hash", f"from {architecture._PROTOCOL} import runtime_id as _matrix_runtime_id", *([f"from {architecture._REPLAY} import replay_calibration_history_selection as _matrix_replay"] if manifest.phase == "P3" else []), *(f"{binding} = {fixed[key]!r}" for binding, key in (("_REPLICATIONS", "replications"), ("_PAIR_ARM_ORDER", "pair_arm_order"), ("_SOURCE_SEQUENCE_CUTOFF", "source_sequence_cutoff"), ("_EVIDENCE_CONTRACT_CHECKPOINT", "evidence_contract_checkpoint"), ("_PROTOCOL_CHECKPOINT", "protocol_checkpoint"), ("_ORACLE_NAMESPACE", "oracle_namespace"), ("_STUDY", "study"), ("_CALIBRATION_NAMESPACE", "calibration_namespace"))), "", "def _matrix_effect_payload_sha256(effect: _MatrixMatchedEffectObservation):", "    return _matrix_raw_effect_sha256(effect)"]
    lines += [line for name, schema in manifest.schemas for line in ("", f"class {name}:", *(f"    schema_version = {schema!r}" if field == "schema_version" else f"    {field}: object" for field in architecture.PROJECTION_FIELDS[name]))]
    lines += [line for name, domain in manifest.identity_domains if name in manifest.identity_functions for line in ("", f"def {name}(projection):", f"    return _matrix_protocol_hash({domain!r}, projection)")]
    lines += ["", "def _oracle_key_id(key_fields):", "    return _matrix_runtime_id('oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})", "", "def _outcome_digest(oracle_key_id, revealed_observation):", "    return _matrix_protocol_hash('revealed_outcome/v1', {'oracle_key_id': oracle_key_id, 'revealed_observation': revealed_observation})", "", "def _source_observation_matches(projection: CalibrationSourceObservationProjection, carried_source_observation_identity: str):", "    return source_observation_identity(projection) == carried_source_observation_identity"]
    if manifest.phase == "P3":
        replay_names = ("replay_run_id", "world_id", "seed", "comparison_group_id", "group_index", "expected_observations", "expected_effects", "physical_cost", "recorded_observations", "recorded_effects", "expected_projection")
        lines += ["_CALIBRATION_SOURCE_SEQUENCE_CUTOFF = 1", "", f"def _predicate_3o_5_1({', '.join(replay_names)}):", "    actual_helper_result = _matrix_replay(", "        run_id=replay_run_id,", *(f"        {name}={name}," for name in replay_names[1:-1]), "        source_sequence_cutoff=_CALIBRATION_SOURCE_SEQUENCE_CUTOFF,", "    )", "    expected_selector_result_identity = _matrix_protocol_hash(", f"        {domains['selection_identity']!r},", *_scientific_identity_mapping_lines("        "), "    )", "    return (actual_helper_result, expected_selector_result_identity)"]
    return "\n".join(lines) + "\n"


def _p3_identity_call(
    *,
    target: str = "_matrix_protocol_hash",
    result: str = "expected_selector_result_identity",
) -> str:
    return "\n".join(
        (
            f"    {result} = {target}(",
            f"        {architecture._SELECTION_IDENTITY_DOMAIN!r},",
            *_scientific_identity_mapping_lines("        "),
            "    )",
        )
    )


def _p3_replay_call(
    *,
    target: str = "_matrix_replay",
    result: str = "actual_helper_result",
) -> str:
    names = (
        "replay_run_id",
        "world_id",
        "seed",
        "comparison_group_id",
        "group_index",
        "expected_observations",
        "expected_effects",
        "physical_cost",
        "recorded_observations",
        "recorded_effects",
    )
    return "\n".join(
        (
            f"    {result} = {target}(",
            "        run_id=replay_run_id,",
            *(f"        {name}={name}," for name in names[1:]),
            "        source_sequence_cutoff=_CALIBRATION_SOURCE_SEQUENCE_CUTOFF,",
            "    )",
        )
    )


def _owner_resolved_target(source: str, requirement: architecture.RequiredCall) -> str:
    analysis = qualified.analyze_qualified_symbols(source, module_name=architecture.CANONICAL_MODULE)
    owner_calls = tuple(call for call in analysis.calls if call.scope == (requirement.owner,))
    calls = (
        tuple(call for call in owner_calls if requirement.qualified_target in call.targets)
        if requirement.owner == "_predicate_3o_5_1"
        else owner_calls
    )
    targets = frozenset(target for call in calls for target in call.targets) if calls else frozenset()
    return "<none>" if not owner_calls else "<unresolved>" if not calls else "|".join(sorted(targets)) if targets else "<unresolved>"
# fmt: on


def _with_call_shape(
    requirement: architecture.RequiredCall, shape: object
) -> architecture.RequiredCall:
    return requirement._replace(call_shape=cast(architecture.CallShape, shape))


# fmt: off
def _top_level_metadata_cases() -> tuple[MetadataCase, ...]:
    oracle = _required_call("oracle_key_id")
    shape = oracle.call_shape
    shape_proxy_type = namedtuple("CallShapeProxy", architecture.CallShape._fields)  # type: ignore[misc]
    missing_type = namedtuple("CallShapeMissingValidationOnly", architecture.CallShape._fields[:-1])  # type: ignore[misc]
    extra_type = namedtuple("CallShapeExtraField", (*architecture.CallShape._fields, "extra"))  # type: ignore[misc]
    required_proxy_type = namedtuple("RequiredCallProxy", architecture.RequiredCall._fields)  # type: ignore[misc]
    call_shape_subclass = type("CallShapeSubclass", (architecture.CallShape,), {})
    exact_short_shape = tuple.__new__(architecture.CallShape, tuple(shape)[:-1])
    exact_extra_shape = tuple.__new__(architecture.CallShape, (*tuple(shape), "extra"))
    exact_short_requirement = tuple.__new__(architecture.RequiredCall, tuple(oracle)[:-1])
    exact_extra_requirement = tuple.__new__(architecture.RequiredCall, (*tuple(oracle), "extra"))
    return (
        MetadataCase("metadata-top-01-none-call-shape", _with_call_shape(oracle, None)),
        MetadataCase("metadata-top-02-arbitrary-truthy-object", _with_call_shape(oracle, HostileMetadata())),
        MetadataCase("metadata-top-03-arbitrary-falsey-object", _with_call_shape(oracle, HostileMetadata(False))),
        MetadataCase("metadata-top-04-plain-tuple", _with_call_shape(oracle, tuple(shape))),
        MetadataCase("metadata-top-05-named-tuple-proxy", _with_call_shape(oracle, shape_proxy_type(*shape))),  # type: ignore[call-arg]
        MetadataCase("metadata-top-06-missing-validation-only", _with_call_shape(oracle, missing_type(*shape[:-1]))),  # type: ignore[call-arg]
        MetadataCase("metadata-top-07-extra-field", _with_call_shape(oracle, extra_type(*shape, "extra"))),  # type: ignore[call-arg]
        MetadataCase("metadata-top-08-call-shape-subclass", _with_call_shape(oracle, call_shape_subclass(*shape))),
        MetadataCase("metadata-top-09-exact-call-shape-short-record", _with_call_shape(oracle, exact_short_shape)),
        MetadataCase("metadata-top-10-exact-call-shape-extra-record", _with_call_shape(oracle, exact_extra_shape)),
        MetadataCase("metadata-top-11-required-call-named-tuple-proxy", required_proxy_type(*oracle)),  # type: ignore[call-arg]
        MetadataCase("metadata-top-12-arbitrary-required-call-object", HostileMetadata()),
        MetadataCase("metadata-top-13-exact-required-call-short-record", exact_short_requirement),
        MetadataCase("metadata-top-14-exact-required-call-extra-record", exact_extra_requirement),
    )


def _nested_metadata_cases() -> tuple[MetadataCase, ...]:
    oracle = _required_call("oracle_key_id")
    outcome = _required_call("outcome_digest")
    source_identity = _required_call("source_observation_identity")
    expression_subclass = type("ExpressionConstraintSubclass", (architecture.ExpressionConstraint,), {})
    parameter_subclass = type("ParameterConstraintSubclass", (architecture.ParameterConstraint,), {})
    keyword_subclass = type("KeywordConstraintSubclass", (architecture.KeywordConstraint,), {})
    expression_proxy_type = namedtuple("ExpressionConstraintProxy", architecture.ExpressionConstraint._fields)  # type: ignore[misc]
    string_subclass = type("MetadataStringSubclass", (str,), {})
    valid_keywords = (
        architecture.KeywordConstraint("left", architecture.ExpressionConstraint("parameter", 0)),
        architecture.KeywordConstraint("right", architecture.ExpressionConstraint("parameter", 1)),
    )

    def shape_case(case_id: str, requirement: architecture.RequiredCall = oracle, **changes: object) -> MetadataCase:
        return MetadataCase(case_id, _with_call_shape(requirement, requirement.call_shape._replace(**changes)))  # type: ignore[arg-type]

    return (
        shape_case("metadata-nested-01-validation-only-int-1", validation_only=1),
        shape_case("metadata-nested-02-validation-only-int-0", validation_only=0),
        shape_case("metadata-nested-03-callable-validation-only", validation_only=lambda: True),
        shape_case("metadata-nested-04-string-validation-only", validation_only="true"),
        shape_case("metadata-nested-05-wrong-expression-object", positional=(object(), *oracle.call_shape.positional[1:])),
        shape_case("metadata-nested-06-wrong-result-object", result_kind=object()),
        shape_case("metadata-nested-07-wrong-binding-object", target_binding=object()),
        shape_case("metadata-nested-08-unknown-expression-kind", positional=(architecture.ExpressionConstraint(cast(architecture.ExpressionKind, "unknown-expression"), "oracle-key"), *oracle.call_shape.positional[1:])),
        shape_case("metadata-nested-09-unknown-result-kind", result_kind=cast(architecture.ResultKind, "unknown-result")),
        shape_case("metadata-nested-10-unknown-binding-kind", target_binding=cast(architecture.TargetBindingKind, "unknown-binding")),
        shape_case("metadata-nested-11-mutable-parameter-list", parameters=list(oracle.call_shape.parameters)),
        shape_case("metadata-nested-12-mutable-positional-list", positional=list(oracle.call_shape.positional)),
        shape_case("metadata-nested-13-mutable-keyword-list", requirement=outcome, positional=(), keywords=list(valid_keywords)),
        shape_case("metadata-nested-14-mutable-keyword-dict", requirement=outcome, positional=(), keywords={keyword.name: keyword for keyword in valid_keywords}),
        shape_case("metadata-nested-15-duplicate-parameter-names", parameters=(architecture.ParameterConstraint("key_fields", None), architecture.ParameterConstraint("key_fields", None)), positional=(architecture.ExpressionConstraint("parameter", 0), architecture.ExpressionConstraint("parameter", 1))),
        shape_case("metadata-nested-16-duplicate-keyword-names", requirement=outcome, positional=(), keywords=(architecture.KeywordConstraint("payload", architecture.ExpressionConstraint("parameter", 0)), architecture.KeywordConstraint("payload", architecture.ExpressionConstraint("parameter", 1)))),
        shape_case("metadata-nested-17-positional-keyword-conflict", requirement=outcome, positional=(architecture.ExpressionConstraint("parameter", 0),), keywords=(architecture.KeywordConstraint("left", architecture.ExpressionConstraint("parameter", 0)), architecture.KeywordConstraint("right", architecture.ExpressionConstraint("parameter", 1)))),
        shape_case("metadata-nested-18-wrong-alias-policy", target_binding=cast(architecture.TargetBindingKind, "borrowed-import")),
        shape_case("metadata-nested-19-wrong-comparison-field-type", requirement=source_identity, compared_parameter="1"),
        shape_case("metadata-nested-20-unsupported-nested-entry", positional=(*oracle.call_shape.positional[:-1], architecture.ExpressionConstraint("ordered-parameter-dict", (object(),)))),  # type: ignore[arg-type]
        shape_case("metadata-nested-21-expression-subclass", positional=(expression_subclass(*oracle.call_shape.positional[0]), *oracle.call_shape.positional[1:])),
        shape_case("metadata-nested-22-expression-proxy", positional=(expression_proxy_type(*oracle.call_shape.positional[0]), *oracle.call_shape.positional[1:])),  # type: ignore[call-arg]
        shape_case("metadata-nested-23-parameter-subclass", parameters=(parameter_subclass(*oracle.call_shape.parameters[0]),)),
        shape_case("metadata-nested-24-keyword-subclass", requirement=outcome, positional=(), keywords=(keyword_subclass(*valid_keywords[0]), valid_keywords[1])),
        shape_case("metadata-nested-25-mutable-ordered-value-list", positional=(*oracle.call_shape.positional[:-1], architecture.ExpressionConstraint("ordered-parameter-dict", [("key_fields", 0)]))),  # type: ignore[arg-type]
        shape_case("metadata-nested-26-mutable-ordered-entry-list", positional=(*oracle.call_shape.positional[:-1], architecture.ExpressionConstraint("ordered-parameter-dict", (["key_fields", 0],)))),  # type: ignore[arg-type]
        shape_case("metadata-nested-27-duplicate-ordered-keys", positional=(*oracle.call_shape.positional[:-1], architecture.ExpressionConstraint("ordered-parameter-dict", (("key_fields", 0), ("key_fields", 0))))),
        shape_case("metadata-nested-28-ordered-key-index-mismatch", requirement=outcome, positional=(outcome.call_shape.positional[0], architecture.ExpressionConstraint("ordered-parameter-dict", (("oracle_key_id", 1), ("revealed_observation", 0))))),
        shape_case("metadata-nested-29-literal-float", positional=(architecture.ExpressionConstraint("literal", cast(architecture.ExpressionValue, 1.0)), *oracle.call_shape.positional[1:])),
        shape_case("metadata-nested-30-literal-bool", positional=(architecture.ExpressionConstraint("literal", True), *oracle.call_shape.positional[1:])),
        shape_case("metadata-nested-31-parameter-bool-index", requirement=source_identity, positional=(architecture.ExpressionConstraint("parameter", True),)),
        shape_case("metadata-nested-32-comparison-out-of-range", requirement=source_identity, compared_parameter=2),
        shape_case("metadata-nested-33-comparison-negative-index", requirement=source_identity, compared_parameter=-1),
        shape_case("metadata-nested-34-recomputed-comparison", compared_parameter=0),
        shape_case("metadata-nested-35-empty-parameters", parameters=()),
        shape_case("metadata-nested-36-empty-arguments", positional=(), keywords=()),
        shape_case("metadata-nested-37-empty-parameter-name", parameters=(architecture.ParameterConstraint("", None),)),
        shape_case("metadata-nested-38-result-string-subclass", result_kind=string_subclass("recomputed-value")),
        shape_case("metadata-nested-39-binding-string-subclass", target_binding=string_subclass("private-import")),
        MetadataCase("metadata-nested-40-phase-string-subclass", oracle._replace(phase=string_subclass("P2"))),
    )


def _hostile_metadata_cases() -> tuple[tuple[MetadataCase, ...], tuple[HostileMetadata, ...]]:
    oracle = _required_call("oracle_key_id")
    probes = tuple(HostileMetadata() for _ in range(9))
    whole, shape, validation, expression, result, binding, parameters, positional, keywords = probes
    cases = (
        MetadataCase("metadata-hostile-01-required-call", whole),
        MetadataCase("metadata-hostile-02-complete-call-shape", _with_call_shape(oracle, shape)),
        MetadataCase("metadata-hostile-03-validation-only", _with_call_shape(oracle, oracle.call_shape._replace(validation_only=validation))),  # type: ignore[arg-type]
        MetadataCase("metadata-hostile-04-expression-constraint", _with_call_shape(oracle, oracle.call_shape._replace(positional=(expression, *oracle.call_shape.positional[1:])))),  # type: ignore[arg-type]
        MetadataCase("metadata-hostile-05-result-constraint", _with_call_shape(oracle, oracle.call_shape._replace(result_kind=result))),  # type: ignore[arg-type]
        MetadataCase("metadata-hostile-06-binding-constraint", _with_call_shape(oracle, oracle.call_shape._replace(target_binding=binding))),  # type: ignore[arg-type]
        MetadataCase("metadata-hostile-07-parameter-container", _with_call_shape(oracle, oracle.call_shape._replace(parameters=parameters))),  # type: ignore[arg-type]
        MetadataCase("metadata-hostile-08-positional-container", _with_call_shape(oracle, oracle.call_shape._replace(positional=positional))),  # type: ignore[arg-type]
        MetadataCase("metadata-hostile-09-keyword-container", _with_call_shape(oracle, oracle.call_shape._replace(keywords=keywords))),  # type: ignore[arg-type]
    )
    return cases, probes
# fmt: on


# fmt: off
_CANONICAL_METADATA_LOGICAL_IDS = ("metadata-canonical-01-list-manifest", "metadata-canonical-02-empty-manifest", "metadata-canonical-03-duplicate-owner-target", "metadata-canonical-04-mutable-nested-container", "metadata-canonical-05-validation-only-false", "metadata-canonical-06-hostile-entry")
_METADATA_ARCHITECTURE_MUTATION_IDS = ("metadata-architecture-01-remove-top-level-validation", "metadata-architecture-02-use-isinstance", "metadata-architecture-03-truthy-validation-only", "metadata-architecture-04-default-missing-field", "metadata-architecture-05-accept-list-container", "metadata-architecture-06-ignore-unknown-kind", "metadata-architecture-07-catch-all-return-true", "metadata-architecture-08-catch-all-weaken", "metadata-architecture-09-attribute-before-type", "metadata-architecture-10-target-specific-branch")
# fmt: on


# fmt: off
def _metadata_logical_ids() -> tuple[str, ...]:
    hostile_cases, _probes = _hostile_metadata_cases()
    return (*(case.id for cases in (_top_level_metadata_cases(), _nested_metadata_cases(), hostile_cases) for case in cases), *_CANONICAL_METADATA_LOGICAL_IDS, *_METADATA_ARCHITECTURE_MUTATION_IDS)
# fmt: on


def _assert_malformed_metadata_cases(cases: tuple[MetadataCase, ...]) -> None:
    source = _fresh_call_shape_source(architecture.P2_MANIFEST)
    tree = ast.parse(source)
    analysis = qualified.analyze_qualified_symbols(
        source, module_name=architecture.CANONICAL_MODULE
    )
    canonical_public = architecture.future_source_findings(source, architecture.P2_MANIFEST)
    executed: list[str] = []
    failures: list[str] = []
    for case in cases:
        executed.append(case.id)
        try:
            valid = architecture._required_call_metadata_is_valid(case.requirement)
            matched = architecture._required_call_matches(tree, analysis, case.requirement)
            equivalent = architecture._equivalent_validation_call_matches(
                tree, analysis, case.requirement
            )
            public = architecture.future_source_findings(source, architecture.P2_MANIFEST)
        except Exception as error:  # noqa: BLE001 - every case must execute
            failures.append(f"{case.id}: raised {type(error).__name__}: {error}")
            continue
        if valid or matched or equivalent or public != canonical_public:
            failures.append(
                f"{case.id}: valid={valid!r}; matched={matched!r}; "
                f"equivalent={equivalent!r}; public={public!r}"
            )
    case_ids = tuple(case.id for case in cases)
    assert (
        executed == list(case_ids) and len(case_ids) == len(frozenset(case_ids)) and not failures
    ), "\n".join(failures)


def _source_matrix_case(
    case_id: str,
    manifest: architecture.PhaseManifest,
    source: str,
    expected: tuple[architecture.Finding, ...] = (),
    exact: bool = False,
    line_fragment: str = "",
    callable_provenance: str = "<none>",
    active_repository: bool = False,
) -> SourceMatrixCase:
    source_line = _line_of(source, line_fragment) if source and line_fragment else 1
    return SourceMatrixCase(
        case_id,
        manifest,
        source,
        frozenset(expected),
        exact,
        source_line,
        callable_provenance,
        active_repository,
    )


def _fresh_source_matrix() -> tuple[SourceMatrixCase, ...]:
    p1 = _future_source(architecture.P1_MANIFEST)
    p2 = _future_source(architecture.P2_MANIFEST)
    p3 = _future_source(architecture.P3_MANIFEST)
    p4 = _future_source(architecture.P4_MANIFEST)
    protocol_runtime = f"{architecture._PROTOCOL}.runtime_id"
    protocol_hash = f"{architecture._PROTOCOL}.protocol_hash"
    source_identity = f"{architecture.CANONICAL_MODULE}.source_observation_identity"
    selection_identity = f"{architecture._PROTOCOL}.protocol_hash"

    # fmt: off
    oracle_relation = "def _oracle_key_id(key_fields):\n    return _runtime_id('oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})"
    outcome_relation = "def _outcome_digest(oracle_key_id, revealed_observation):\n    return _protocol_hash('revealed_outcome/v1', {'oracle_key_id': oracle_key_id, 'revealed_observation': revealed_observation})"
    source_relation = "def _source_observation_matches(projection: CalibrationSourceObservationProjection, carried_source_observation_identity: str):\n    return source_observation_identity(projection) == carried_source_observation_identity"
    selection_relation = "\n".join(("    expected_selector_result_identity = _protocol_hash(", f"        {dict(architecture.P3_MANIFEST.identity_domains)['selection_identity']!r},", *_scientific_identity_mapping_lines("        "), "    )"))
    # fmt: on

    def launder_relation(source: str, exact_owner: str, bad_owner: str, exact_other: str) -> str:
        return source.replace(exact_owner, bad_owner) + f"\n{exact_other}\n"

    # fmt: off
    protocol_alias = p1.replace("protocol_hash as _protocol_hash", "protocol_hash as _hash").replace("_protocol_hash(", "_hash(")
    private_helper = p1 + "\ndef _private_helper(value):\n    return value\n"
    benign_comment = p1 + "\n# validation_evidence_calibration_selection/v1 is future planning text.\n"
    benign_docstring = p1 + '\ndef _domain_docstring():\n    """validation_evidence_calibration_selection/v1 is future planning text."""\n    return None\n'
    benign_explanation = p1 + '\ndef _domain_explanation():\n    explanation = "validation_evidence_calibration_selection/v1 is future planning text."\n    return None\n'
    benign_data = p1 + '\ndef _domain_data():\n    payload = {"note": "validation_evidence_calibration_selection/v1"}\n    return None\n'
    benign_sigma_alias = p1.replace("from research_decision_engine.benchmarks.broader_protocol", "from research_decision_engine.belief_models import SIGMA_FLOOR as _SIGMA_FLOOR\nfrom research_decision_engine.benchmarks.broader_protocol") + "\n_X = _SIGMA_FLOOR\n"
    benign_protocol_version_alias = p1.replace("protocol_hash as _protocol_hash", "PROTOCOL_VERSION as _PROTOCOL_VERSION, protocol_hash as _protocol_hash") + "\n_X = _PROTOCOL_VERSION\n"
    authoritative_domain = p1 + "\n_CALIBRATION_CANDIDATE_PAIR_ID_DOMAIN = 'validation_evidence_calibration_candidate_pair/v1'\n"

    swapped = _swap_projection_fields(p4, "CalibrationCandidatePairProjection", 0, 1)
    bool_cutoff = p1.replace("_SOURCE_SEQUENCE_CUTOFF = 1", "_SOURCE_SEQUENCE_CUTOFF = True")
    bool_replication = p1.replace("_REPLICATIONS = (1, 2, 3, 4, 5)", "_REPLICATIONS = (True, 2, 3, 4, 5)")
    missing_oracle = p2.replace("    return _runtime_id('oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})", "    return key_fields")
    missing_outcome = p2.replace("    return _protocol_hash('revealed_outcome/v1', {'oracle_key_id': oracle_key_id, 'revealed_observation': revealed_observation})", "    return revealed_observation")
    missing_source_identity = p2.replace("    return source_observation_identity(projection) == carried_source_observation_identity", "    return carried_source_observation_identity == carried_source_observation_identity")
    wrong_oracle_order = p2.replace("_runtime_id('oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})", "_runtime_id('oracle_key_id/v1', 'oracle-key', {'key_fields': key_fields})")
    caller_precomputed_oracle = p2.replace("def _oracle_key_id(key_fields):\n    return _runtime_id('oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})", "def _oracle_key_id(key_fields, precomputed_oracle_key_id):\n    return precomputed_oracle_key_id")
    wrapped_oracle = p2.replace("    return _runtime_id('oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})", "    return _oracle_key_wrapper(key_fields)") + "\ndef _oracle_key_wrapper(key_fields):\n    value = _runtime_id('oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})\n    return value\n"
    wrong_outcome_order = p2.replace("{'oracle_key_id': oracle_key_id, 'revealed_observation': revealed_observation}", "{'revealed_observation': revealed_observation, 'oracle_key_id': oracle_key_id}")
    wrong_source_input = p2.replace("source_observation_identity(projection) == carried_source_observation_identity", "source_observation_identity(carried_source_observation_identity) == carried_source_observation_identity")
    framed_oracle = p2.replace("_runtime_id('oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})", "_protocol_hash('oracle-key/oracle_key_id/v1', {'key_fields': key_fields})")
    local_hash = p1.replace("from research_decision_engine.benchmarks.broader_protocol import protocol_hash as _protocol_hash", "def _hash(domain, payload):\n    return domain").replace("_protocol_hash(", "_hash(")
    hashlib_source = p1 + "\nimport hashlib\n\ndef _extra_digest(value):\n    return hashlib.sha256(value)\n"
    selection_wrapper = p3 + "\ndef selector_result_identity(expected_projection):\n" + "\n".join(("    return _protocol_hash(", f"        {dict(architecture.P3_MANIFEST.identity_domains)['selection_identity']!r},", *_scientific_identity_mapping_lines("        "), "    )")) + "\n"
    second_selector_identity = p3 + "\ndef scientific_calibration_selection_id(projection):\n    return _protocol_hash('second-selector/v1', projection)\n"
    renamed_aggregate = p4 + "\nclass _FinalCalibrationAggregate:\n    pass\n"
    private_class = p4 + "\nclass _PrivateHelper:\n    pass\n"
    reader_surface = p4 + "\nfrom research_decision_engine.benchmarks.broader_lifecycle import Reader as _Reader\n"
    evidence_surface = p4 + "\nfrom research_decision_engine.benchmarks.broader_validation_evidence import write_evidence as _write_evidence\n"
    workload_surface = p4 + "\nfrom research_decision_engine.benchmarks.broader_runner import run_arm as _run_arm\n\ndef _run_workload():\n    return _run_arm()\n"
    live_module_alias = p4 + "\nimport research_decision_engine.benchmarks.broader_runner as _runner\n\ndef _run_module_alias():\n    return _runner.run_arm()\n"
    live_two_hop_alias = p4 + "\nfrom research_decision_engine.benchmarks.broader_runner import run_arm as _run_arm\n_first = _run_arm\n_second = _first\n\ndef _run_two_hop():\n    return _second()\n"
    live_getattr = p4 + "\nimport research_decision_engine.benchmarks.broader_runner as _runner\n\ndef _run_getattr():\n    return getattr(_runner, 'run_arm')()\n"
    wrong_domain = p1.replace("return _protocol_hash('validation_evidence_calibration_candidate_pair/v1', _calibration_candidate_pair_preimage(projection))", "return _protocol_hash('validation_evidence_calibration_candidate_pair/v2', _calibration_candidate_pair_preimage(projection))")
    active_p1 = p1
    alternate_selection_alias = p3.replace("protocol_hash as _protocol_hash", "protocol_hash as _approved_protocol_hash").replace("_protocol_hash(", "_approved_protocol_hash(")
    private_class_alias = p4 + "\n_PrivateHelper = object\n"
    private_int_class_alias = p4 + "\n_PrivateHelper = int\n"
    private_exception_class_alias = p4 + "\n_PrivateHelper = ValueError\n"

    relation_bypasses = (
        ("matrix-oracle-owner-precomputed-exact-decoy", architecture.P2_MANIFEST, launder_relation(p2, oracle_relation, "def _oracle_key_id(key_fields, caller_oracle_key_id):\n    return caller_oracle_key_id", oracle_relation.replace("_oracle_key_id", "_oracle_key_decoy")), protocol_runtime, "caller_oracle_key_id"),
        ("matrix-outcome-owner-precomputed-exact-decoy", architecture.P2_MANIFEST, launder_relation(p2, outcome_relation, "def _outcome_digest(oracle_key_id, revealed_observation, caller_outcome_digest):\n    return caller_outcome_digest", outcome_relation.replace("_outcome_digest", "_outcome_digest_decoy")), protocol_hash, "caller_outcome_digest"),
        ("matrix-source-owner-precomputed-exact-decoy", architecture.P2_MANIFEST, launder_relation(p2, source_relation, "def _source_observation_matches(projection: CalibrationSourceObservationProjection, carried_source_observation_identity: str):\n    return carried_source_observation_identity == carried_source_observation_identity", source_relation.replace("_source_observation_matches", "_source_observation_decoy")), source_identity, "carried_source_observation_identity == carried"),
        ("matrix-p3-owner-precomputed-exact-decoy", architecture.P3_MANIFEST, launder_relation(p3, selection_relation, "    expected_selector_result_identity = p3_input.selector_result_identity", "def _selection_identity_decoy(expected_projection):\n" + selection_relation.replace("    expected_selector_result_identity =", "    decoy_identity =", 1) + "\n    return decoy_identity"), selection_identity, "p3_input.selector_result_identity"),
        ("matrix-oracle-owner-delegates-exact-wrapper", architecture.P2_MANIFEST, launder_relation(p2, oracle_relation, "def _oracle_key_id(key_fields):\n    return _oracle_key_wrapper(key_fields)", oracle_relation.replace("_oracle_key_id", "_oracle_key_wrapper")), protocol_runtime, "return _oracle_key_wrapper"),
        ("matrix-outcome-owner-delegates-exact-wrapper", architecture.P2_MANIFEST, launder_relation(p2, outcome_relation, "def _outcome_digest(oracle_key_id, revealed_observation):\n    return _outcome_digest_wrapper(oracle_key_id, revealed_observation)", outcome_relation.replace("_outcome_digest", "_outcome_digest_wrapper")), protocol_hash, "return _outcome_digest_wrapper"),
        ("matrix-source-owner-delegates-exact-wrapper", architecture.P2_MANIFEST, launder_relation(p2, source_relation, "def _source_observation_matches(projection: CalibrationSourceObservationProjection, carried_source_observation_identity: str):\n    return _source_observation_wrapper(projection, carried_source_observation_identity)", source_relation.replace("_source_observation_matches", "_source_observation_wrapper")), source_identity, "return _source_observation_wrapper"),
        ("matrix-p3-owner-delegates-exact-wrapper", architecture.P3_MANIFEST, launder_relation(p3, selection_relation, "    expected_selector_result_identity = _selection_identity_wrapper(expected_projection)", "def _selection_identity_wrapper(expected_projection):\n" + selection_relation.replace("    expected_selector_result_identity =", "    wrapped_identity =", 1) + "\n    return wrapped_identity"), selection_identity, "_selection_identity_wrapper(expected_projection)"),
    )
    selector_domain_bypasses = (
        ("matrix-renamed-private-selector-domain", p3 + "\n_SCIENTIFIC_CALIBRATION_SELECTION_IDENTITY_DOMAIN = 'broader-calibration-history-selection/v2'\n", "_SCIENTIFIC_CALIBRATION_SELECTION_IDENTITY_DOMAIN"),
        ("matrix-second-private-selector-domain", p3 + "\n_SECOND_SELECTION_IDENTITY_DOMAIN = 'broader-calibration-history-selection/v2'\n", "_SECOND_SELECTION_IDENTITY_DOMAIN"),
        ("matrix-aliased-wrong-selector-domain", p3 + "\n_WRONG_SELECTOR_DOMAIN = 'broader-calibration-history-selection/v2'\n_SECOND_SELECTION_IDENTITY_DOMAIN = _WRONG_SELECTOR_DOMAIN\n", "_SECOND_SELECTION_IDENTITY_DOMAIN = _WRONG"),
        ("matrix-composed-wrong-selector-domain", p3 + "\n_SECOND_SELECTION_IDENTITY_DOMAIN = 'broader-calibration-' + 'history-selection/v2'\n", "_SECOND_SELECTION_IDENTITY_DOMAIN = 'broader"),
        ("matrix-selector-domain-alias-suffix", p3 + "\n_SELECTION_IDENTITY_DOMAIN_ALIAS = 'broader-calibration-history-selection/v2'\n", "_SELECTION_IDENTITY_DOMAIN_ALIAS"),
        ("matrix-identity-manifest-domain", p3 + "\n_IDENTITY_MANIFEST = {'selection_identity': 'broader-calibration-history-selection/v2'}\n", "_IDENTITY_MANIFEST"),
        ("matrix-identity-tuple-manifest-domain", p3 + "\n_IDENTITY_MANIFEST = (('selection_identity', 'broader-calibration-history-selection/v2'),)\n", "_IDENTITY_MANIFEST"),
        ("matrix-conditional-selector-domain", p3 + "\nif True:\n    _SECOND_SELECTION_IDENTITY_DOMAIN = 'broader-calibration-history-selection/v2'\n", "_SECOND_SELECTION_IDENTITY_DOMAIN"),
        ("matrix-conditional-identity-manifest", p3 + "\nif True:\n    _IDENTITY_MANIFEST = {'selection_identity': 'broader-calibration-history-selection/v2'}\n", "_IDENTITY_MANIFEST"),
        ("matrix-destructured-selector-domain", p3 + "\n(_SECOND_SELECTION_IDENTITY_DOMAIN,) = ('broader-calibration-history-selection/v2',)\n", "_SECOND_SELECTION_IDENTITY_DOMAIN"),
        ("matrix-destructured-identity-manifest", p3 + "\n(_IDENTITY_MANIFEST,) = ((('selection_identity', 'broader-calibration-history-selection/v2'),),)\n", "_IDENTITY_MANIFEST"),
        ("matrix-match-selector-domain", p3 + "\nmatch 'broader-calibration-history-selection/v2':\n    case _SECOND_SELECTION_IDENTITY_DOMAIN:\n        pass\n", "_SECOND_SELECTION_IDENTITY_DOMAIN"),
        ("matrix-pair-sequence-data-manifest", p3 + "\n_DATA_MANIFEST = (('selection_identity', 'broader-calibration-history-selection/v2'),)\n", "_DATA_MANIFEST"),
    )
    # fmt: on

    make, finding = _source_matrix_case, architecture.Finding
    # fmt: off
    return (
        make("matrix-c0-exact-absence", architecture.C0_MANIFEST, "", exact=True, active_repository=True),
        *(make(f"matrix-{manifest.phase.lower()}-exact", manifest, source, exact=True, line_fragment="_PROTOCOL_CHECKPOINT", callable_provenance=architecture.CANONICAL_MODULE) for manifest, source in ((architecture.P1_MANIFEST, p1), (architecture.P2_MANIFEST, p2), (architecture.P3_MANIFEST, p3), (architecture.P4_MANIFEST, p4))),
        make("matrix-exact-authoritative-domain", architecture.P1_MANIFEST, authoritative_domain, exact=True, line_fragment="_CALIBRATION_CANDIDATE_PAIR_ID_DOMAIN", callable_provenance="<identity-domain-authority>"),
        make("matrix-protocol-hash-alias", architecture.P1_MANIFEST, protocol_alias, exact=True, line_fragment="_hash(", callable_provenance=protocol_hash),
        make("matrix-p3-selection-identity-alternate-private-alias", architecture.P3_MANIFEST, alternate_selection_alias, exact=True, line_fragment="_approved_protocol_hash(", callable_provenance=selection_identity),
        make("matrix-benign-private-helper", architecture.P1_MANIFEST, private_helper, exact=True, line_fragment="def _private_helper", callable_provenance=f"{architecture.CANONICAL_MODULE}._private_helper"),
        *(make(case_id, architecture.P1_MANIFEST, source, exact=True, line_fragment=fragment, callable_provenance="<non-authority-text>") for case_id, source, fragment in (("matrix-benign-domain-comment", benign_comment, "future planning text"), ("matrix-benign-domain-docstring", benign_docstring, "future planning text"), ("matrix-benign-domain-explanation", benign_explanation, "explanation ="), ("matrix-benign-domain-data", benign_data, "payload ="), ("matrix-benign-identity-manifest-note", p1 + "\n_FUTURE_IDENTITY_MANIFEST_NOTE = {'note': 'broader-calibration-history-selection/v2'}\n", "_FUTURE_IDENTITY_MANIFEST_NOTE"), ("matrix-benign-domain-alias-note", p1 + "\n_SELECTION_IDENTITY_DOMAIN_ALIAS_NOTE = 'broader-calibration-history-selection/v2'\n", "_SELECTION_IDENTITY_DOMAIN_ALIAS_NOTE"))),
        make("matrix-benign-sigma-constant-alias", architecture.P1_MANIFEST, benign_sigma_alias, exact=True, line_fragment="_X = _SIGMA_FLOOR", callable_provenance="research_decision_engine.belief_models.SIGMA_FLOOR"),
        make("matrix-benign-protocol-version-alias", architecture.P1_MANIFEST, benign_protocol_version_alias, exact=True, line_fragment="_X = _PROTOCOL_VERSION", callable_provenance=f"{architecture._PROTOCOL}.PROTOCOL_VERSION"),
        *(make(f"matrix-benign-builtin-{case_id}", architecture.P1_MANIFEST, p1 + f"\n_X = {name}\n", exact=True, line_fragment=f"_X = {name}", callable_provenance=f"builtins.{name}") for case_id, name in (("function-alias", "len"), ("constant-alias", "NotImplemented"))),
        make("matrix-active-c0-p1-surface", architecture.C0_MANIFEST, active_p1, (finding("c0-production-module-present", architecture.CANONICAL_MODULE),), line_fragment="class CalibrationCandidatePairProjection", callable_provenance=architecture.CANONICAL_MODULE, active_repository=True),
        make("matrix-swapped-fields", architecture.P4_MANIFEST, swapped, (finding("projection-field-surface", "CalibrationCandidatePairProjection"),), line_fragment="class CalibrationCandidatePairProjection", callable_provenance=f"{architecture.CANONICAL_MODULE}.CalibrationCandidatePairProjection"),
        make("matrix-bool-cutoff", architecture.P1_MANIFEST, bool_cutoff, (finding("fixed-literal", "source_sequence_cutoff"),), line_fragment="_SOURCE_SEQUENCE_CUTOFF = True", callable_provenance="<literal>"),
        make("matrix-bool-replication", architecture.P1_MANIFEST, bool_replication, (finding("fixed-literal", "replications"),), line_fragment="_REPLICATIONS = (True", callable_provenance="<literal>"),
        *(make(case_id, architecture.P2_MANIFEST, source, (finding("required-pure-helper", target),), line_fragment=fragment, callable_provenance=target) for case_id, source, target, fragment in (
            ("matrix-missing-oracle-recomputation", missing_oracle, protocol_runtime, "return key_fields"),
            ("matrix-missing-outcome-recomputation", missing_outcome, protocol_hash, "return revealed_observation"),
            ("matrix-missing-source-identity-recomputation", missing_source_identity, source_identity, "carried_source_observation_identity == carried"),
            ("matrix-wrong-oracle-argument-order", wrong_oracle_order, protocol_runtime, "_runtime_id('oracle_key_id/v1'"),
            ("matrix-caller-precomputed-oracle", caller_precomputed_oracle, protocol_runtime, "precomputed_oracle_key_id"),
            ("matrix-wrapped-oracle-recomputation", wrapped_oracle, protocol_runtime, "def _oracle_key_wrapper"),
            ("matrix-wrong-outcome-field-order", wrong_outcome_order, protocol_hash, "'revealed_observation': revealed_observation"),
            ("matrix-wrong-source-identity-input", wrong_source_input, source_identity, "source_observation_identity(carried"),
            ("matrix-framed-oracle-substitution", framed_oracle, protocol_runtime, "_protocol_hash('oracle-key/oracle_key_id/v1'"),
        )),
        *(make(case_id, manifest, source, (finding("required-pure-helper", target),), line_fragment=fragment, callable_provenance=target) for case_id, manifest, source, target, fragment in relation_bypasses),
        *(make(f"matrix-async-{case_id}", manifest, _future_source(manifest).replace(f"def {owner}", f"async def {owner}"), (finding("required-pure-helper", target),), line_fragment=f"async def {owner}", callable_provenance=target) for case_id, manifest, owner, target in (("oracle-relation", architecture.P2_MANIFEST, "_oracle_key_id", protocol_runtime), ("outcome-relation", architecture.P2_MANIFEST, "_outcome_digest", protocol_hash), ("source-relation", architecture.P2_MANIFEST, "_source_observation_matches", source_identity), ("selection-relation", architecture.P3_MANIFEST, "_predicate_3o_5_1", selection_identity))),
        make("matrix-local-hash-implementation", architecture.P1_MANIFEST, local_hash, (finding("second-hash-algebra", "_hash"),), line_fragment="def _hash", callable_provenance=f"{architecture.CANONICAL_MODULE}._hash"),
        make("matrix-hashlib", architecture.P1_MANIFEST, hashlib_source, (finding("forbidden-import", "hashlib"),), line_fragment="import hashlib", callable_provenance="hashlib.sha256"),
        make("matrix-selection-identity-wrapper", architecture.P3_MANIFEST, selection_wrapper, (finding("premature-identity-alias", "selector_result_identity"),), line_fragment="def selector_result_identity", callable_provenance=f"{architecture.CANONICAL_MODULE}.selector_result_identity"),
        make("matrix-second-selector-identity", architecture.P3_MANIFEST, second_selector_identity, (finding("premature-identity-alias", "scientific_calibration_selection_id"),), line_fragment="def scientific_calibration_selection_id", callable_provenance=f"{architecture.CANONICAL_MODULE}.scientific_calibration_selection_id"),
        *(make(case_id, architecture.P3_MANIFEST, source, (finding("identity-domain-set", "P3"),), line_fragment=fragment, callable_provenance="<identity-domain-authority>") for case_id, source, fragment in selector_domain_bypasses),
        *(make(case_id, architecture.P4_MANIFEST, source, (finding("top-level-class-surface", "P4"),), line_fragment=fragment, callable_provenance=f"{architecture.CANONICAL_MODULE}.{fragment.split()[-1].rstrip(':')}") for case_id, source, fragment in (("matrix-renamed-final-aggregate", renamed_aggregate, "class _FinalCalibrationAggregate:"), ("matrix-unmanifested-private-class", private_class, "class _PrivateHelper:"))),
        make("matrix-private-class-object-alias", architecture.P4_MANIFEST, private_class_alias, (finding("top-level-class-surface", "P4"),), line_fragment="_PrivateHelper = object", callable_provenance="builtins.object"),
        make("matrix-private-class-int-alias", architecture.P4_MANIFEST, private_int_class_alias, (finding("top-level-class-surface", "P4"),), line_fragment="_PrivateHelper = int", callable_provenance="builtins.int"),
        make("matrix-private-class-exception-alias", architecture.P4_MANIFEST, private_exception_class_alias, (finding("top-level-class-surface", "P4"),), line_fragment="_PrivateHelper = ValueError", callable_provenance="builtins.ValueError"),
        *(make(f"matrix-private-class-{case_id}", architecture.P4_MANIFEST, p4 + suffix, (finding("top-level-class-surface", "P4"),), line_fragment=fragment, callable_provenance="builtins.ValueError") for case_id, suffix, fragment in (("walrus-alias", "\nif (_PrivateHelper := ValueError):\n    pass\n", "_PrivateHelper :="), ("loop-alias", "\nfor _PrivateHelper in (ValueError,):\n    pass\n", "for _PrivateHelper"), ("match-alias", "\nmatch ValueError:\n    case _PrivateHelper:\n        pass\n", "case _PrivateHelper"))),
        make("matrix-private-class-helper-factory", architecture.P4_MANIFEST, p4 + "\ndef _class_factory():\n    return ValueError\n_PrivateHelper = _class_factory()\n", (finding("top-level-class-surface", "P4"),), line_fragment="_PrivateHelper = _class_factory()", callable_provenance=f"{architecture.CANONICAL_MODULE}._class_factory"),
        make("matrix-benign-value-helper-factory", architecture.P4_MANIFEST, p4 + "\ndef _value_factory():\n    return 1\n_X = _value_factory()\n", exact=True, line_fragment="_X = _value_factory()", callable_provenance=f"{architecture.CANONICAL_MODULE}._value_factory"),
        *(make(f"matrix-private-class-{case_id}", architecture.P4_MANIFEST, p4 + suffix, (finding("top-level-class-surface", "P4"),), line_fragment=fragment, callable_provenance=provenance) for case_id, suffix, fragment, provenance in (("local-derived-factory", "\ndef _class_factory():\n    _value = object\n    return _value\n_PrivateHelper = _class_factory()\n", "_PrivateHelper = _class_factory()", f"{architecture.CANONICAL_MODULE}._class_factory"), ("identity-passthrough", "\ndef _identity(value):\n    return value\n_PrivateHelper = _identity(ValueError)\n", "_PrivateHelper = _identity", f"{architecture.CANONICAL_MODULE}._identity"), ("max-selector", "\n_PrivateHelper = max((object,))\n", "_PrivateHelper = max", "builtins.max"), ("min-selector", "\n_PrivateHelper = min((ValueError,))\n", "_PrivateHelper = min", "builtins.min"))),
        *(make(f"matrix-benign-class-metadata-{case_id}", architecture.P4_MANIFEST, p4 + suffix, exact=True, line_fragment=fragment, callable_provenance=provenance) for case_id, suffix, fragment, provenance in (("attribute", "\n_X = object.__name__\n", "_X = object.__name__", "builtins.object.__name__"), ("factory", "\ndef _value_factory():\n    return object.__name__\n_X = _value_factory()\n", "_X = _value_factory()", f"{architecture.CANONICAL_MODULE}._value_factory"))),
        make("matrix-reader-surface", architecture.P4_MANIFEST, reader_surface, (finding("forbidden-import", "research_decision_engine.benchmarks.broader_lifecycle"),), line_fragment="import Reader as _Reader", callable_provenance="research_decision_engine.benchmarks.broader_lifecycle.Reader"),
        make("matrix-evidence-surface", architecture.P4_MANIFEST, evidence_surface, (finding("forbidden-import", "research_decision_engine.benchmarks.broader_validation_evidence"),), line_fragment="import write_evidence", callable_provenance="research_decision_engine.benchmarks.broader_validation_evidence.write_evidence"),
        make("matrix-workload-surface", architecture.P4_MANIFEST, workload_surface, (finding("forbidden-sensitive-call", "_run_arm"),), line_fragment="return _run_arm()", callable_provenance="research_decision_engine.benchmarks.broader_runner.run_arm"),
        make("matrix-live-module-alias", architecture.P4_MANIFEST, live_module_alias, (finding("whole-module-import", "research_decision_engine.benchmarks.broader_runner"),), line_fragment="import research_decision_engine.benchmarks.broader_runner", callable_provenance="research_decision_engine.benchmarks.broader_runner.run_arm"),
        make("matrix-live-two-hop-alias", architecture.P4_MANIFEST, live_two_hop_alias, (finding("forbidden-sensitive-call", "_second"),), line_fragment="return _second()", callable_provenance="research_decision_engine.benchmarks.broader_runner.run_arm"),
        make("matrix-live-getattr", architecture.P4_MANIFEST, live_getattr, (finding("forbidden-sensitive-call", "getattr"),), line_fragment="return getattr", callable_provenance="builtins.getattr"),
        make("matrix-wrong-domain-in-identity-call", architecture.P1_MANIFEST, wrong_domain, (finding("identity-domain", "calibration_candidate_pair_id"),), line_fragment="validation_evidence_calibration_candidate_pair/v2", callable_provenance=protocol_hash),
    )
    # fmt: on


# fmt: off
def _fresh_call_shape_matrix() -> tuple[CallShapeMatrixCase, ...]:
    oracle, outcome = _required_call("oracle_key_id"), _required_call("outcome_digest")
    source_identity, replay, selection = _required_call("source_observation_identity"), _required_call("calibration_selector_replay"), _required_call("selection_identity")
    p2, p3 = _fresh_call_shape_source(architecture.P2_MANIFEST), _fresh_call_shape_source(architecture.P3_MANIFEST)
    missing = cast(Callable[[architecture.RequiredCall], architecture.Finding], lambda requirement: architecture.Finding("required-pure-helper", requirement.qualified_target))
    oracle_call = "_matrix_runtime_id('oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})"
    outcome_call = "_matrix_protocol_hash('revealed_outcome/v1', {'oracle_key_id': oracle_key_id, 'revealed_observation': revealed_observation})"
    source_call = "source_observation_identity(projection) == carried_source_observation_identity"
    selection_call = _p3_identity_call()

    changed_oracle = _with_positional_expression(oracle, 0, architecture.ExpressionConstraint("literal", "matrix-oracle-key"))
    changed_oracle_source = p2.replace("'oracle-key'", "'matrix-oracle-key'", 1)
    unsupported_expression = _with_positional_expression(oracle, 0, architecture.ExpressionConstraint(cast(architecture.ExpressionKind, "unsupported-expression"), "oracle-key"))
    unsupported_result = outcome._replace(call_shape=outcome.call_shape._replace(result_kind=cast(architecture.ResultKind, "unsupported-result")))
    source_override = changed_oracle_source + "\n_REQUIRED_CALLS = ()\n_PHASE_MANIFEST = 'P4'\n"
    make = CallShapeMatrixCase
    return (
        make("call-shape-01-exact-p2", architecture.P2_MANIFEST, p2, (oracle, outcome, source_identity), (True, True, True), frozenset(), True, (oracle.qualified_target, outcome.qualified_target, source_identity.qualified_target), ("exact-positional", "exact-positional", "exact-positional"), None),
        make("call-shape-02-p2-missing-oracle", architecture.P2_MANIFEST, p2.replace(f"return {oracle_call}", "return key_fields"), (oracle,), (False,), frozenset({missing(oracle)}), False, ("<none>",), ("absent",), missing(oracle)),
        make("call-shape-03-p2-missing-outcome", architecture.P2_MANIFEST, p2.replace(f"return {outcome_call}", "return revealed_observation"), (outcome,), (False,), frozenset({missing(outcome)}), False, ("<none>",), ("absent",), missing(outcome)),
        make("call-shape-04-p2-missing-source-observation", architecture.P2_MANIFEST, p2.replace(f"return {source_call}", "return carried_source_observation_identity == carried_source_observation_identity"), (source_identity,), (False,), frozenset({missing(source_identity)}), False, ("<none>",), ("absent",), missing(source_identity)),
        make("call-shape-05-p2-wrong-positional-source", architecture.P2_MANIFEST, p2.replace(oracle_call, "_matrix_runtime_id(key_fields, 'oracle_key_id/v1', {'key_fields': key_fields})"), (oracle,), (False,), frozenset({missing(oracle)}), False, (oracle.qualified_target,), ("wrong-positional-expression",), missing(oracle)),
        make("call-shape-06-p2-wrong-keyword-binding", architecture.P2_MANIFEST, p2.replace(outcome_call, "_matrix_protocol_hash(domain='revealed_outcome/v1', payload={'oracle_key_id': oracle_key_id, 'revealed_observation': revealed_observation})"), (outcome,), (False,), frozenset({missing(outcome)}), False, (outcome.qualified_target,), ("wrong-keyword-binding",), missing(outcome)),
        make("call-shape-07-p2-reordered-inputs", architecture.P2_MANIFEST, p2.replace("{'oracle_key_id': oracle_key_id, 'revealed_observation': revealed_observation}", "{'revealed_observation': revealed_observation, 'oracle_key_id': oracle_key_id}"), (outcome,), (False,), frozenset({missing(outcome)}), False, (outcome.qualified_target,), ("wrong-ordered-inputs",), missing(outcome)),
        make("call-shape-08-p2-approved-private-alias", architecture.P2_MANIFEST, p2.replace("_matrix_runtime_id", "_approved_runtime_alias").replace("_matrix_protocol_hash", "_approved_hash_alias"), (oracle, outcome), (True, True), frozenset(), True, (oracle.qualified_target, outcome.qualified_target), ("exact-private-alias", "exact-private-alias"), None),
        make("call-shape-09-p2-wrapper", architecture.P2_MANIFEST, p2.replace(f"return {oracle_call}", "return _oracle_manifest_wrapper(key_fields)") + f"\ndef _oracle_manifest_wrapper(key_fields):\n return {oracle_call}\n", (oracle,), (False,), frozenset({missing(oracle)}), False, (f"{architecture.CANONICAL_MODULE}._oracle_manifest_wrapper",), ("wrapper",), missing(oracle)),
        make("call-shape-10-p2-unresolved-target", architecture.P2_MANIFEST, p2.replace("_matrix_runtime_id('oracle-key'", "_unresolved_runtime_id('oracle-key'"), (oracle,), (False,), frozenset({missing(oracle)}), False, ("<unresolved>",), ("unresolved",), missing(oracle)),
        make("call-shape-11-exact-p3-selection", architecture.P3_MANIFEST, p3, (replay, selection), (True, True), frozenset(), True, (replay.qualified_target, selection.qualified_target), ("exact-keywords", "exact-21-field-preimage"), None),
        make("call-shape-12-p3-wrong-projection", architecture.P3_MANIFEST, p3.replace('"world_id": expected_projection.world_id', '"world_id": actual_helper_result.world_id', 1), (selection,), (False,), frozenset({missing(selection)}), False, (selection.qualified_target,), ("helper-supplies-projection",), missing(selection)),
        make("call-shape-13-p3-copied-identity", architecture.P3_MANIFEST, p3.replace(selection_call, "    expected_selector_result_identity = p3_input.selector_result_identity", 1), (selection,), (False,), frozenset({missing(selection)}), False, ("<unresolved>",), ("copied-carried-value",), missing(selection)),
        make("call-shape-14-p3-approved-private-alias", architecture.P3_MANIFEST, p3.replace("protocol_hash as _matrix_protocol_hash", "protocol_hash as _approved_selection_alias").replace("_matrix_protocol_hash(", "_approved_selection_alias("), (selection,), (True,), frozenset(), True, (selection.qualified_target,), ("exact-private-alias",), None),
        make("call-shape-15-p3-wrapper", architecture.P3_MANIFEST, p3.replace(selection_call, "    expected_selector_result_identity = _selection_manifest_wrapper(expected_projection)", 1) + "\ndef _selection_manifest_wrapper(expected_projection):\n" + _p3_identity_call(result="wrapped_identity") + "\n    return wrapped_identity\n", (selection,), (False,), frozenset({missing(selection)}), False, ("<unresolved>",), ("wrapper",), missing(selection)),
        make("call-shape-16-mutated-supported-shape", architecture.P2_MANIFEST, p2, (changed_oracle,), (False,), frozenset(), True, (oracle.qualified_target,), ("canonical-source-mutated-shape",), None),
        make("call-shape-17-unsupported-shape-kind", architecture.P2_MANIFEST, p2, (unsupported_result, unsupported_expression), (False, False), frozenset(), True, (outcome.qualified_target, oracle.qualified_target), ("unsupported-result", "unsupported-expression"), None),
        make("call-shape-18-public-requirement-injection", architecture.P2_MANIFEST, changed_oracle_source, (changed_oracle,), (True,), frozenset({missing(oracle)}), False, (oracle.qualified_target,), ("test-owned-wrong-shape",), missing(oracle)),
        make("call-shape-19-source-phase-manifest-override", architecture.P2_MANIFEST, source_override, (oracle,), (False,), frozenset({missing(oracle)}), False, (oracle.qualified_target,), ("source-override-ignored",), missing(oracle)),
        make("call-shape-20-exact-c0-absence", architecture.C0_MANIFEST, "", (), (), frozenset(), True, (), (), None),
    )
# fmt: on


# fmt: off
def test_fresh_negative_and_benign_source_matrix_is_complete() -> None:
    source_cases, call_shape_cases = _fresh_source_matrix(), _fresh_call_shape_matrix()
    cases: tuple[SourceMatrixCase | CallShapeMatrixCase, ...] = (*source_cases, *call_shape_cases)
    case_by_id: dict[str, SourceMatrixCase | CallShapeMatrixCase] = {case.id: case for case in cases}
    logical_cases = tuple(LogicalCase(case.id, case.id, case.expected, case.exact) for case in cases)

    def evaluate(case_id: str) -> tuple[architecture.Finding, ...]:
        case = case_by_id[case_id]
        if isinstance(case, CallShapeMatrixCase):
            observed_matches = tuple(bool(_low_level_required_call_matches(case.source, requirement)) for requirement in case.requirements)
            observed_targets = tuple(_owner_resolved_target(case.source, requirement) for requirement in case.requirements)
            if observed_matches != case.expected_matches or observed_targets != case.resolved_targets:
                raise AssertionError(f"call-shape metadata mismatch: matches={observed_matches!r}; targets={observed_targets!r}")
        if isinstance(case, CallShapeMatrixCase) and case.manifest.phase == "C0" or isinstance(case, SourceMatrixCase) and case.active_repository:
            sources = {} if not case.source else {architecture.CANONICAL_MODULE: case.source}
            return architecture.repository_findings(sources, case.manifest)
        return architecture.future_source_findings(case.source, case.manifest)

    result = _evaluate_batch(logical_cases, evaluate)
    source_ids, call_shape_ids = tuple(case.id for case in source_cases), tuple(case.id for case in call_shape_cases)
    retained_ids = (*_supplementary_logical_ids(), *source_ids)
    logical_ids = (*retained_ids, *call_shape_ids)
    metadata_ids = _metadata_logical_ids()
    updated_logical_ids = (*logical_ids, *metadata_ids)
    source_metadata_is_complete = all(case.id.startswith("matrix-") and case.manifest.phase in {"C0", "P1", "P2", "P3", "P4"} and case.source_line >= 1 and bool(case.callable_provenance) for case in source_cases)
    call_shape_metadata_is_complete = not any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "_future_source" for call in ast.walk(ast.parse(inspect.getsource(_fresh_call_shape_source)))) and all(case.id.startswith("call-shape-") and case.manifest.phase in {"C0", "P1", "P2", "P3", "P4"} and len(case.requirements) == len(case.expected_matches) == len(case.resolved_targets) == len(case.argument_binding_results) and all(requirement.call_shape for requirement in case.requirements) and all(case.argument_binding_results) and (case.finding is None or case.finding in case.expected) for case in call_shape_cases)
    assert len(source_cases) == 84 and len(call_shape_cases) == 20 and len(logical_ids) == len(frozenset(logical_ids)) == 284 and not frozenset(call_shape_ids) & frozenset(retained_ids) and hashlib.sha256("\n".join(retained_ids).encode()).hexdigest().upper() == "D7A2D70C382FEA2C1692274FB8591AA5FF0CF157EEA02F2F40C45EF6B404CEF8" and hashlib.sha256("\n".join(logical_ids).encode()).hexdigest().upper() == "0A416CC0D25DBF9BB9808A46A2D041D27772DE0C4438F2B71774E3755CE30AAD" and len(metadata_ids) == len(frozenset(metadata_ids)) == 79 and not frozenset(metadata_ids) & frozenset(logical_ids) and len(updated_logical_ids) == len(frozenset(updated_logical_ids)) == 363 and hashlib.sha256("\n".join(updated_logical_ids).encode()).hexdigest().upper() == "14F61FBB47407DEE08C20AD0BBD2ACD99395FA7B1AF92233DCA81E9CBE551905" and source_metadata_is_complete and call_shape_metadata_is_complete
    _assert_batch(result)
# fmt: on


def _replace(old: str, new: str) -> Callable[[str], str]:
    return lambda source: source.replace(old, new)


def _supplementary_logical_ids() -> tuple[str, ...]:
    owner_ids = tuple(
        logical_id for cases in _OWNER_ISOLATED.values() for logical_id, _, _ in cases
    )
    c0_ids = tuple(logical.id for cases in _ISOLATED_C0.values() for logical in cases)
    future_ids = tuple(logical.id for cases in _ISOLATED_FUTURE.values() for logical in cases)
    return (*owner_ids, *c0_ids, *future_ids)


def test_supplementary_logical_case_ids_are_globally_unique() -> None:
    logical_ids = _supplementary_logical_ids()
    assert len(logical_ids) == 180 and len(frozenset(logical_ids)) == 180


def test_duplicate_logical_ids_fail_before_batch_evaluation() -> None:
    duplicate = architecture.Finding("duplicate-control", "expected")
    cases = (
        LogicalCase("duplicate-id", "first", frozenset({duplicate})),
        LogicalCase("duplicate-id", "second", frozenset({duplicate})),
    )
    executed: list[str] = []

    def evaluate(source: str) -> tuple[architecture.Finding, ...]:
        executed.append(source)
        return ()

    with pytest.raises(AssertionError, match="duplicate logical case IDs: duplicate-id"):
        _evaluate_batch(cases, evaluate)
    assert executed == []


def test_supplementary_batch_evaluates_every_case_after_multiple_failures() -> None:
    expected = architecture.Finding("batch-control", "expected")
    unexpected = architecture.Finding("batch-control", "unexpected")
    cases = (
        LogicalCase("missing-first", "missing", frozenset({expected}), exact=True),
        LogicalCase("unexpected-second", "unexpected", frozenset(), exact=True),
        LogicalCase("exception-third", "exception", frozenset({expected}), exact=True),
        LogicalCase("passing-final", "passing", frozenset({expected}), exact=True),
    )
    executed: list[str] = []

    def evaluate(source: str) -> tuple[architecture.Finding, ...]:
        executed.append(source)
        if source == "exception":
            raise ValueError("recorded control exception")
        if source == "unexpected":
            return (unexpected,)
        if source == "passing":
            return (expected,)
        return ()

    result = _evaluate_batch(cases, evaluate)
    assert (
        result.executed_ids == tuple(case.id for case in cases)
        and tuple(case_id for case_id, _ in result.observed) == tuple(case.id for case in cases)
        and executed == [case.source for case in cases]
        and result.missing == (("missing-first", (expected,)),)
        and result.unexpected == (("unexpected-second", (unexpected,)),)
        and result.exceptions == (("exception-third", "ValueError: recorded control exception"),)
    )


@pytest.mark.parametrize(
    ("class_name", "left_index", "right_index"),
    (
        ("CalibrationCandidatePairProjection", 0, 1),
        ("CalibrationSourceObservationProjection", 7, 8),
        ("CalibrationSelectionProjection", -2, -1),
    ),
    ids=("first-two-fields", "interior-fields", "final-two-fields"),
)
def test_reordered_projection_fields_are_rejected(
    class_name: str, left_index: int, right_index: int
) -> None:
    source = _swap_projection_fields(
        _future_source(architecture.P4_MANIFEST),
        class_name,
        left_index,
        right_index,
    )
    assert architecture.Finding(
        "projection-field-surface", class_name
    ) in architecture.future_source_findings(source, architecture.P4_MANIFEST)


_STRICT_LITERAL_CASES = (
    Mutation(
        "bool-cutoff",
        _replace("_SOURCE_SEQUENCE_CUTOFF = 1", "_SOURCE_SEQUENCE_CUTOFF = True"),
        architecture.Finding("fixed-literal", "source_sequence_cutoff"),
    ),
    Mutation(
        "bool-replication",
        _replace(
            "_REPLICATIONS = (1, 2, 3, 4, 5)",
            "_REPLICATIONS = (True, 2, 3, 4, 5)",
        ),
        architecture.Finding("fixed-literal", "replications"),
    ),
    Mutation(
        "int-float-cutoff",
        _replace("_SOURCE_SEQUENCE_CUTOFF = 1", "_SOURCE_SEQUENCE_CUTOFF = 1.0"),
        architecture.Finding("fixed-literal", "source_sequence_cutoff"),
    ),
    Mutation(
        "tuple-list-replications",
        _replace(
            "_REPLICATIONS = (1, 2, 3, 4, 5)",
            "_REPLICATIONS = [1, 2, 3, 4, 5]",
        ),
        architecture.Finding("fixed-literal", "replications"),
    ),
    Mutation(
        "reordered-replications",
        _replace(
            "_REPLICATIONS = (1, 2, 3, 4, 5)",
            "_REPLICATIONS = (2, 1, 3, 4, 5)",
        ),
        architecture.Finding("fixed-literal", "replications"),
    ),
    Mutation(
        "bytes-string-namespace",
        _replace(
            '_CALIBRATION_NAMESPACE = "rde.broader.calibration-outcome/v1"',
            "_CALIBRATION_NAMESPACE = b'rde.broader.calibration-outcome/v1'",
        ),
        architecture.Finding("fixed-literal", "calibration_namespace"),
    ),
)


@pytest.mark.parametrize(
    "case", _STRICT_LITERAL_CASES, ids=[case.id for case in _STRICT_LITERAL_CASES]
)
def test_fixed_literals_use_exact_type_and_order(case: Mutation) -> None:
    source = case.mutate(_future_source(architecture.P1_MANIFEST))
    assert case.expected in architecture.future_source_findings(source, architecture.P1_MANIFEST)


_P2_REQUIRED_RECOMPUTATION_CASES = (
    Mutation(
        "missing-oracle-key-recomputation",
        _replace(
            "    return _runtime_id('oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})",
            "    return key_fields",
        ),
        architecture.Finding("required-pure-helper", f"{architecture._PROTOCOL}.runtime_id"),
    ),
    Mutation(
        "missing-outcome-digest-recomputation",
        _replace(
            "    return _protocol_hash('revealed_outcome/v1', {'oracle_key_id': oracle_key_id, 'revealed_observation': revealed_observation})",
            "    return revealed_observation",
        ),
        architecture.Finding("required-pure-helper", f"{architecture._PROTOCOL}.protocol_hash"),
    ),
    Mutation(
        "missing-source-observation-recomputation",
        _replace(
            "    return source_observation_identity(projection) == carried_source_observation_identity",
            "    return carried_source_observation_identity == carried_source_observation_identity",
        ),
        architecture.Finding(
            "required-pure-helper",
            f"{architecture.CANONICAL_MODULE}.source_observation_identity",
        ),
    ),
)


@pytest.mark.parametrize(
    "case",
    _P2_REQUIRED_RECOMPUTATION_CASES,
    ids=[case.id for case in _P2_REQUIRED_RECOMPUTATION_CASES],
)
def test_p2_requires_each_exact_recomputation(case: Mutation) -> None:
    source = case.mutate(_future_source(architecture.P2_MANIFEST))
    assert case.expected in architecture.future_source_findings(source, architecture.P2_MANIFEST)


# fmt: off
LinkageSpec = NamedTuple("LinkageSpec", [("name", str), ("manifest", architecture.PhaseManifest), ("exact", str), ("changed", str), ("argument_index", int), ("expression", architecture.ExpressionConstraint), ("wrong_binding", str), ("wrong_target", str), ("alias_old", str), ("alias_new", str), ("alias_append", str), ("alias_expected", bool), ("wrapper_call", str), ("wrapper_definition", str), ("unresolved", str)])


def _linkage_specs() -> tuple[LinkageSpec, ...]:
    return (
        LinkageSpec("oracle_key_id", architecture.P2_MANIFEST, "_matrix_runtime_id('oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})", "_matrix_runtime_id('family-oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})", 0, architecture.ExpressionConstraint("literal", "family-oracle-key"), "_matrix_runtime_id(kind='oracle-key', version='oracle_key_id/v1', payload={'key_fields': key_fields})", "_matrix_protocol_hash('oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})", "_matrix_runtime_id", "_family_runtime_identity", "", True, "_family_oracle_wrapper(key_fields)", "\ndef _family_oracle_wrapper(key_fields):\n return _matrix_runtime_id('oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})\n", "_dynamic_runtime_identity('oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})"),
        LinkageSpec("outcome_digest", architecture.P2_MANIFEST, "_matrix_protocol_hash('revealed_outcome/v1', {'oracle_key_id': oracle_key_id, 'revealed_observation': revealed_observation})", "_matrix_protocol_hash('revealed_outcome/v1', {'revealed_observation': revealed_observation, 'oracle_key_id': oracle_key_id})", 1, architecture.ExpressionConstraint("ordered-parameter-dict", (("revealed_observation", 1), ("oracle_key_id", 0))), "_matrix_protocol_hash(domain='revealed_outcome/v1', payload={'oracle_key_id': oracle_key_id, 'revealed_observation': revealed_observation})", "_matrix_runtime_id('revealed_outcome/v1', {'oracle_key_id': oracle_key_id, 'revealed_observation': revealed_observation})", "_matrix_protocol_hash", "_family_protocol_hash", "", True, "_family_outcome_wrapper(oracle_key_id, revealed_observation)", "\ndef _family_outcome_wrapper(oracle_key_id, revealed_observation):\n return _matrix_protocol_hash('revealed_outcome/v1', {'oracle_key_id': oracle_key_id, 'revealed_observation': revealed_observation})\n", "_dynamic_protocol_hash('revealed_outcome/v1', {'oracle_key_id': oracle_key_id, 'revealed_observation': revealed_observation})"),
        LinkageSpec("source_observation_identity", architecture.P2_MANIFEST, "source_observation_identity(projection)", "source_observation_identity(carried_source_observation_identity)", 0, architecture.ExpressionConstraint("parameter", 1), "source_observation_identity(projection=projection)", "_matrix_protocol_hash(projection)", "source_observation_identity(projection)", "_source_identity_alias(projection)", "\n_source_identity_alias = source_observation_identity\n", False, "_family_source_wrapper(projection)", "\ndef _family_source_wrapper(projection):\n return source_observation_identity(projection)\n", "_dynamic_source_identity(projection)"),
    )


def _assert_required_call_metadata_authority(name: str) -> None:
    spec = next(item for item in _linkage_specs() if item.name == name)
    requirement, source = _required_call(name), _fresh_call_shape_source(spec.manifest)
    changed = _with_positional_expression(requirement, spec.argument_index, spec.expression)
    missing = architecture.Finding("required-pure-helper", requirement.qualified_target)
    variants = tuple(source.replace(spec.exact, replacement) + suffix for replacement, suffix in ((spec.changed, ""), (spec.wrong_binding, ""), (spec.wrong_target, ""), (spec.alias_new if spec.alias_old == spec.exact else spec.exact, spec.alias_append), (spec.wrapper_call, spec.wrapper_definition), (spec.unresolved, "")))
    if spec.alias_old != spec.exact:
        variants = (*variants[:3], source.replace(spec.alias_old, spec.alias_new), *variants[4:])
    observations = (bool(_low_level_required_call_matches(source, requirement)), bool(_low_level_required_call_matches(source, changed)), bool(_low_level_required_call_matches(variants[0], changed)), missing in architecture.future_source_findings(variants[0], spec.manifest), *(bool(_low_level_required_call_matches(candidate, requirement)) for candidate in variants[1:]))
    assert observations == (True, False, True, True, False, False, spec.alias_expected, False, False)
# fmt: on


def test_oracle_key_required_call_metadata_is_authoritative() -> None:
    _assert_required_call_metadata_authority("oracle_key_id")


def test_outcome_digest_required_call_metadata_is_authoritative() -> None:
    _assert_required_call_metadata_authority("outcome_digest")


def test_source_observation_required_call_metadata_is_authoritative() -> None:
    _assert_required_call_metadata_authority("source_observation_identity")


def test_selection_identity_required_call_metadata_is_authoritative() -> None:
    requirement = _required_call("selection_identity")
    source = _fresh_call_shape_source(architecture.P3_MANIFEST)
    exact_call = _p3_identity_call()
    missing = architecture.Finding("required-pure-helper", requirement.qualified_target)
    wrong_domain = source.replace(
        architecture._SELECTION_IDENTITY_DOMAIN,
        "broader-calibration-history-selection/v2",
        1,
    )
    incomplete_mapping = source.replace(
        '        "world_id": expected_projection.world_id,\n',
        "",
        1,
    )
    copied_carried = source.replace(
        exact_call,
        "    expected_selector_result_identity = p3_input.selector_result_identity",
        1,
    )
    private_alias = source.replace(
        "protocol_hash as _matrix_protocol_hash",
        "protocol_hash as _approved_protocol_hash",
    ).replace("_matrix_protocol_hash(", "_approved_protocol_hash(")
    wrapper = (
        source.replace(
            exact_call,
            "    expected_selector_result_identity = _selection_identity_wrapper(expected_projection)",
            1,
        )
        + "\ndef _selection_identity_wrapper(expected_projection):\n"
        + _p3_identity_call(result="wrapped_identity")
        + "\n    return wrapped_identity\n"
    )
    observations = (
        bool(_low_level_required_call_matches(source, requirement)),
        missing in architecture.future_source_findings(wrong_domain, architecture.P3_MANIFEST),
        missing
        in architecture.future_source_findings(incomplete_mapping, architecture.P3_MANIFEST),
        missing in architecture.future_source_findings(copied_carried, architecture.P3_MANIFEST),
        bool(_low_level_required_call_matches(private_alias, requirement)),
        missing in architecture.future_source_findings(wrapper, architecture.P3_MANIFEST),
    )
    assert observations == (True, True, True, True, True, True)


def test_active_p3_replay_required_call_metadata_is_authoritative() -> None:
    requirement = _required_call("calibration_selector_replay")
    source = _fresh_call_shape_source(architecture.P3_MANIFEST)
    exact_call = _p3_replay_call()
    missing = architecture.Finding("required-pure-helper", requirement.qualified_target)
    top_level_replay_import = (
        f"from {architecture._REPLAY} import "
        "replay_calibration_history_selection as _matrix_replay\n"
    )
    predicate_signature = next(
        line for line in source.splitlines() if line.startswith("def _predicate_3o_5_1(")
    )

    def local_replay_import(
        *,
        alias: str = "_replay_calibration_history_selection",
        placement: Literal["direct", "nested", "dynamic", "unbound", "late"] = "direct",
    ) -> str:
        candidate = source.replace(top_level_replay_import, "", 1).replace(
            "_matrix_replay(", f"{alias}("
        )
        if placement == "direct":
            addition = (
                f"    from {architecture._REPLAY} import "
                f"replay_calibration_history_selection as {alias}\n"
            )
        elif placement == "nested":
            addition = (
                "    if True:\n"
                f"        from {architecture._REPLAY} import "
                f"replay_calibration_history_selection as {alias}\n"
            )
        elif placement == "dynamic":
            addition = (
                f"    {alias} = __import__({architecture._REPLAY!r}, "
                "fromlist=('replay_calibration_history_selection',)"
                ").replay_calibration_history_selection\n"
            )
        else:
            addition = ""
        candidate = candidate.replace(
            f"{predicate_signature}\n",
            f"{predicate_signature}\n{addition}",
            1,
        )
        if placement == "late":
            candidate = candidate.replace(
                "    expected_selector_result_identity =",
                f"    from {architecture._REPLAY} import "
                f"replay_calibration_history_selection as {alias}\n"
                "    expected_selector_result_identity =",
                1,
            )
        return candidate

    omitted_recorded = source.replace(
        "        recorded_observations=recorded_observations,\n",
        "",
        1,
    )
    wrong_binding = source.replace(
        "        run_id=replay_run_id,",
        "        run_id=world_id,",
        1,
    )
    discarded = source.replace(
        exact_call,
        exact_call.replace("    actual_helper_result = ", "    ", 1),
        1,
    )
    wrapper = (
        source.replace(
            exact_call,
            "    actual_helper_result = _replay_wrapper()",
            1,
        )
        + "\ndef _replay_wrapper():\n"
        + _p3_replay_call(result="wrapped_result")
        + "\n    return wrapped_result\n"
    )
    private_alias = source.replace(
        "replay_calibration_history_selection as _matrix_replay",
        "replay_calibration_history_selection as _approved_replay",
    ).replace("_matrix_replay(", "_approved_replay(")
    observations = (
        bool(_low_level_required_call_matches(source, requirement)),
        missing in architecture.future_source_findings(omitted_recorded, architecture.P3_MANIFEST),
        missing in architecture.future_source_findings(wrong_binding, architecture.P3_MANIFEST),
        missing in architecture.future_source_findings(discarded, architecture.P3_MANIFEST),
        missing in architecture.future_source_findings(wrapper, architecture.P3_MANIFEST),
        bool(_low_level_required_call_matches(private_alias, requirement)),
        bool(_low_level_required_call_matches(local_replay_import(), requirement)),
        bool(
            _low_level_required_call_matches(
                local_replay_import(alias="_local_replay"), requirement
            )
        ),
        bool(
            _low_level_required_call_matches(local_replay_import(placement="nested"), requirement)
        ),
        bool(
            _low_level_required_call_matches(local_replay_import(placement="dynamic"), requirement)
        ),
        bool(
            _low_level_required_call_matches(local_replay_import(placement="unbound"), requirement)
        ),
        bool(_low_level_required_call_matches(local_replay_import(placement="late"), requirement)),
    )
    assert observations == (
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        False,
        False,
        False,
        False,
        False,
    )


# fmt: off
def test_required_call_shape_split_authority_reproducer_is_closed() -> None:
    observations = []
    for requirement in architecture.REQUIRED_CALLS:
        source = _fresh_call_shape_source(architecture.P2_MANIFEST if requirement.phase == "P2" else architecture.P3_MANIFEST)
        unsupported = requirement._replace(call_shape=requirement.call_shape._replace(result_kind=cast(architecture.ResultKind, "unsupported-result-kind")))
        observations.append((requirement.name, bool(_low_level_required_call_matches(source, requirement)), bool(_low_level_required_call_matches(source, unsupported))))
    assert observations == [("oracle_key_id", True, False), ("outcome_digest", True, False), ("source_observation_identity", True, False), ("calibration_selector_replay", True, False), ("selection_identity", True, False)]


def test_supplied_requirement_matcher_is_separate_from_canonical_phase_checker() -> None:
    canonical = _required_call("oracle_key_id")
    supplied = _with_positional_expression(canonical, 0, architecture.ExpressionConstraint("literal", "test-owned-oracle-key"))
    source = _fresh_call_shape_source(architecture.P2_MANIFEST).replace("'oracle-key'", "'test-owned-oracle-key'", 1)
    source_override = source + "\n_REQUIRED_CALLS = (supplied,)\n_PHASE = 'P4'\n"
    missing = architecture.Finding("required-pure-helper", canonical.qualified_target)
    public_checker = cast(Callable[..., object], architecture.future_source_findings)
    observed = (bool(_low_level_required_call_matches(source, supplied)), missing in architecture.future_source_findings(source, architecture.P2_MANIFEST), missing in architecture.future_source_findings(source_override, architecture.P2_MANIFEST), tuple(inspect.signature(architecture.future_source_findings).parameters), tuple(inspect.signature(architecture._canonical_required_call_matches).parameters))
    with pytest.raises(TypeError):
        public_checker(source, architecture.P2_MANIFEST, supplied)
    assert observed == (True, True, True, ("source", "manifest"), ("tree", "manifest", "analysis"))


def test_projection_manifest_has_no_dead_derived_lookup() -> None:
    source = Path(architecture.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    occurrences = tuple(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "PROJECTION_MANIFEST_BY_NAME"
    )
    assert (
        not hasattr(architecture, "PROJECTION_MANIFEST_BY_NAME")
        and occurrences == ()
    )


def test_required_call_matcher_has_one_declarative_authority() -> None:
    source = Path(architecture.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    matcher, active = functions["_required_call_matches"], functions["_active_required_calls"]
    interpreter, equivalent, target_binding = functions["_call_shape_matches_in_owner"], functions["_equivalent_validation_call_matches"], functions["_target_binding_matches"]
    canonical, public, public_entry, manifest_checker = functions["_canonical_required_call_matches"], functions["_future_source_findings_with_session"], functions["future_source_findings"], functions["_manifest_findings"]
    import_checkers = (functions["_approved_required_call_import"], functions["_approved_required_call_binding"])

    def match_values(function_name: str) -> tuple[str, ...]:
        return tuple(node.value.value for node in ast.walk(functions[function_name]) if isinstance(node, ast.MatchValue) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str))

    def called_names(node: ast.AST) -> tuple[str, ...]:
        return tuple(call.func.id for call in ast.walk(node) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name))

    required_assignment = next(node for node in tree.body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "REQUIRED_CALLS")
    assignment_end = required_assignment.end_lineno or required_assignment.lineno
    literal_locations = tuple(node.lineno for node in ast.walk(tree) if isinstance(node, ast.Constant) and node.value in {"oracle-key", "oracle_key_id/v1", "revealed_outcome/v1"})
    target_constant_names = {"_RUNTIME_ID_TARGET", "_PROTOCOL_HASH_TARGET", "_SOURCE_OBSERVATION_ID_TARGET", "_REPLAY_TARGET"}
    required_call_assignments = {target.id: node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign)) for target in (tuple(node.targets) if isinstance(node, ast.Assign) else (node.target,)) if isinstance(target, ast.Name) and "REQUIRED_CALL" in target.id}
    argument_name_tuples = {("key_fields",), ("oracle_key_id", "revealed_observation"), ("projection", "carried_source_observation_identity")}
    duplicated_argument_tuples = tuple(node.lineno for node in ast.walk(tree) if isinstance(node, (ast.Tuple, ast.List)) and all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in node.elts) and tuple(item.value if isinstance(item, ast.Constant) and isinstance(item.value, str) else "" for item in node.elts) in argument_name_tuples and not required_assignment.lineno <= node.lineno <= assignment_end)
    matcher_shape_loads = tuple(node for node in ast.walk(matcher) if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "requirement" and node.attr == "call_shape" and isinstance(node.ctx, ast.Load))
    matcher_name_dispatch = tuple(node for function in (matcher, interpreter, target_binding) for node in ast.walk(function) if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "requirement" and node.attr == "name")

    shapes_supported = all((requirement.call_shape.positional or requirement.call_shape.keywords) and requirement.call_shape.validation_only and requirement.call_shape.result_kind in architecture._SUPPORTED_RESULT_KINDS and requirement.call_shape.target_binding in architecture._SUPPORTED_TARGET_BINDINGS and all(expression.kind in architecture._SUPPORTED_EXPRESSION_KINDS for expression in requirement.call_shape.positional) and all(keyword.expression.kind in architecture._SUPPORTED_EXPRESSION_KINDS for keyword in requirement.call_shape.keywords) for requirement in architecture.REQUIRED_CALLS)
    checks = (
        bool(matcher_shape_loads) and not matcher_name_dispatch,
        not {node.id for function in (matcher, interpreter, target_binding) for node in ast.walk(function) if isinstance(node, ast.Name)} & target_constant_names,
        match_values("_expression_matches") == architecture._SUPPORTED_EXPRESSION_KINDS,
        match_values("_result_matches") == architecture._SUPPORTED_RESULT_KINDS,
        match_values("_target_binding_matches") == architecture._SUPPORTED_TARGET_BINDINGS,
        shapes_supported and all(required_assignment.lineno <= lineno <= assignment_end for lineno in literal_locations) and not duplicated_argument_tuples,
        set(required_call_assignments) == {"REQUIRED_CALLS", "_PHASE_REQUIRED_CALLS"} and any(isinstance(node, ast.Name) and node.id == "REQUIRED_CALLS" for node in ast.walk(required_call_assignments["_PHASE_REQUIRED_CALLS"])) and any(isinstance(node, ast.Name) and node.id == "REQUIRED_CALLS" for node in ast.walk(active)),
        "_required_call_matches" in called_names(canonical) and "_call_shape_matches_in_owner" in called_names(matcher) and "_call_shape_matches_in_owner" in called_names(equivalent) and "_canonical_required_call_matches" in called_names(public) and "_equivalent_validation_call_matches" in called_names(public) and "_future_source_findings_with_session" in called_names(public_entry) and "_required_call_matches" not in called_names(manifest_checker) and not any(isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "_replace" and isinstance(call.func.value, ast.Name) and call.func.value.id == "requirement" for call in ast.walk(tree)),
        all(any(isinstance(node, ast.Attribute) and node.attr == "call_shape" for node in ast.walk(checker)) for checker in import_checkers),
        all(required_assignment.lineno <= call.lineno <= assignment_end for call in ast.walk(tree) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "RequiredCall"),
    )
    assert all(checks)
# fmt: on


# fmt: off
def _metadata_validation_architecture_findings(source: str) -> frozenset[str]:
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    validator = functions["_required_call_metadata_is_valid"]
    gates = (functions["_required_call_matches"], functions["_call_shape_matches_in_owner"], functions["_equivalent_validation_call_matches"])
    findings: set[str] = set()
    exact_compares = tuple(node for node in ast.walk(validator) if isinstance(node, ast.Compare) and isinstance(node.left, ast.Call) and isinstance(node.left.func, ast.Name) and node.left.func.id == "type" and len(node.left.args) == 1 and len(node.ops) == len(node.comparators) == 1 and isinstance(node.ops[0], (ast.Is, ast.IsNot)) and isinstance(node.comparators[0], ast.Name))
    exact_checks: dict[str, set[str]] = {}
    for node in exact_compares:
        comparator = cast(ast.Name, node.comparators[0])
        left = cast(ast.Call, node.left)
        exact_checks.setdefault(comparator.id, set()).add(ast.unparse(left.args[0]))
    for class_name, finding in (("RequiredCall", "exact-required-call"), ("CallShape", "exact-call-shape"), ("ParameterConstraint", "exact-parameter-constraint"), ("ExpressionConstraint", "exact-expression-constraint"), ("KeywordConstraint", "exact-keyword-constraint")):
        findings.update((finding,) if class_name not in exact_checks else ())
    findings.update(("exact-validation-only-bool",) if "validation_only" not in exact_checks.get("bool", set()) else ())
    findings.update(("exact-frozen-containers",) if not {"parameters", "positional", "keywords", "value.value", "entry"} <= exact_checks.get("tuple", set()) else ())
    supported = {node.comparators[0].id for node in ast.walk(validator) if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1 and isinstance(node.ops[0], ast.NotIn) and isinstance(node.comparators[0], ast.Name)}
    findings.update(("supported-kinds-fail-closed",) if not {"_SUPPORTED_EXPRESSION_KINDS", "_SUPPORTED_RESULT_KINDS", "_SUPPORTED_TARGET_BINDINGS"} <= supported else ())
    nested = {node.name: node for node in validator.body if isinstance(node, ast.FunctionDef)}

    def starts_exact(node: ast.FunctionDef | ast.AsyncFunctionDef, class_name: str) -> bool:
        first = next((statement for statement in node.body if not isinstance(statement, (ast.Expr, ast.FunctionDef))), None)
        return bool(isinstance(first, ast.If) and any(isinstance(item, ast.Compare) and isinstance(item.left, ast.Call) and isinstance(item.left.func, ast.Name) and item.left.func.id == "type" and any(isinstance(comparator, ast.Name) and comparator.id == class_name for comparator in item.comparators) for item in ast.walk(first.test)))

    exact_order = starts_exact(validator, "RequiredCall") and starts_exact(nested["parameter_is_valid"], "ParameterConstraint") and starts_exact(nested["expression_is_valid"], "ExpressionConstraint") and starts_exact(nested["keyword_is_valid"], "KeywordConstraint")
    findings.update(("exact-type-before-attributes",) if not exact_order else ())
    findings.update(("metadata-validation-first",) if any(not gate.body or not isinstance(gate.body[0], ast.If) or not any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "_required_call_metadata_is_valid" for call in ast.walk(gate.body[0].test)) for gate in gates) else ())
    equivalent = functions["_equivalent_validation_call_matches"]
    findings.update(("no-validation-only-truthiness",) if not any(isinstance(node, ast.Compare) and isinstance(node.left, ast.Attribute) and node.left.attr == "validation_only" and any(isinstance(op, ast.Is) for op in node.ops) and any(isinstance(comparator, ast.Constant) and comparator.value is True for comparator in node.comparators) for node in ast.walk(equivalent)) else ())
    relevant = (validator, *gates)
    findings.update(("no-reflective-field-default",) if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"getattr", "hasattr"} for function in relevant for node in ast.walk(function)) else ())
    findings.update(("no-isinstance-metadata-policy",) if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "isinstance" for node in ast.walk(validator)) else ())
    findings.update(("no-broad-metadata-exception",) if any(isinstance(node, ast.ExceptHandler) and (node.type is None or isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}) for function in relevant for node in ast.walk(function)) else ())
    target_literals = {"oracle_key_id", "outcome_digest", "source_observation_identity", "selection_identity"}
    findings.update(("no-target-specific-shape-authority",) if any(isinstance(node, ast.Constant) and node.value in target_literals for function in (validator, functions["_call_shape_matches_in_owner"], functions["_target_binding_matches"]) for node in ast.walk(function)) else ())
    return frozenset(findings)
# fmt: on


def _replace_metadata_architecture_source(source: str, old: str, new: str) -> str:
    assert source.count(old) >= 1
    return source.replace(old, new, 1)


# fmt: off
def _metadata_architecture_mutations(source: str) -> tuple[tuple[str, str, str], ...]:
    first_gate = "    if not _required_call_metadata_is_valid(requirement):\n        return frozenset()\n"
    exact_requirement = "    if type(requirement) is not RequiredCall or len(requirement) != 5:\n        return False\n"
    docstring = '    """Validate one exact, closed, immutable required-call metadata graph."""\n'
    def replace(old: str, new: str) -> str:
        return _replace_metadata_architecture_source(source, old, new)
    return (
        (_METADATA_ARCHITECTURE_MUTATION_IDS[0], replace(first_gate, ""), "metadata-validation-first"),
        (_METADATA_ARCHITECTURE_MUTATION_IDS[1], replace("type(requirement) is not RequiredCall", "not isinstance(requirement, RequiredCall)"), "exact-required-call"),
        (_METADATA_ARCHITECTURE_MUTATION_IDS[2], replace("or type(validation_only) is not bool", "or not validation_only"), "exact-validation-only-bool"),
        (_METADATA_ARCHITECTURE_MUTATION_IDS[3], replace(exact_requirement, '    _shape = getattr(requirement, "call_shape", None)\n' + exact_requirement), "no-reflective-field-default"),
        (_METADATA_ARCHITECTURE_MUTATION_IDS[4], replace("type(parameters) is not tuple", "not isinstance(parameters, (tuple, list))"), "exact-frozen-containers"),
        (_METADATA_ARCHITECTURE_MUTATION_IDS[5], replace("\n        or result_kind not in _SUPPORTED_RESULT_KINDS", ""), "supported-kinds-fail-closed"),
        (_METADATA_ARCHITECTURE_MUTATION_IDS[6], replace(docstring, docstring + "    try:\n        return True\n    except Exception:\n        return True\n"), "no-broad-metadata-exception"),
        (_METADATA_ARCHITECTURE_MUTATION_IDS[7], replace(first_gate, "    try:\n        _required_call_metadata_is_valid(requirement)\n    except Exception:\n        return _call_shape_matches_in_owner(\n            tree, analysis, requirement, requirement.owner\n        )\n" + first_gate), "no-broad-metadata-exception"),
        (_METADATA_ARCHITECTURE_MUTATION_IDS[8], replace(exact_requirement, "    _shape = requirement.call_shape\n" + exact_requirement), "exact-type-before-attributes"),
        (_METADATA_ARCHITECTURE_MUTATION_IDS[9], replace("    if (\n        type(requirement.phase) is not str", '    if requirement.name == "oracle_key_id":\n        return True\n    if (\n        type(requirement.phase) is not str'), "no-target-specific-shape-authority"),
    )
# fmt: on


# fmt: off
def test_required_call_closed_metadata_schema_accepts_canonical_manifest() -> None:
    canonical = architecture.REQUIRED_CALLS
    false_validation = canonical[0]._replace(call_shape=canonical[0].call_shape._replace(validation_only=False))
    assert type(canonical) is tuple and len(canonical) == 5 and architecture._call_metadata_manifest_findings() == () and all(type(requirement) is architecture.RequiredCall and type(requirement.call_shape) is architecture.CallShape and architecture._required_call_metadata_is_valid(requirement) and type(requirement.call_shape.parameters) is tuple and type(requirement.call_shape.positional) is tuple and type(requirement.call_shape.keywords) is tuple for requirement in canonical) and architecture._required_call_metadata_is_valid(false_validation)
# fmt: on


def test_malformed_top_level_required_call_metadata_fails_closed() -> None:
    _assert_malformed_metadata_cases(_top_level_metadata_cases())


def test_malformed_nested_required_call_metadata_fails_closed() -> None:
    _assert_malformed_metadata_cases(_nested_metadata_cases())


def test_hostile_metadata_hooks_are_never_executed() -> None:
    cases, probes = _hostile_metadata_cases()
    _assert_malformed_metadata_cases(cases)
    assert all(probe.counts == dict.fromkeys(_HOOK_NAMES, 0) for probe in probes)


def test_canonical_required_call_manifest_self_validation_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = architecture.REQUIRED_CALLS
    hostile = HostileMetadata()
    mutable = canonical[0]._replace(
        call_shape=canonical[0].call_shape._replace(
            positional=list(canonical[0].call_shape.positional)  # type: ignore[arg-type]
        )
    )
    false_validation = canonical[0]._replace(
        call_shape=canonical[0].call_shape._replace(validation_only=False)
    )
    variants = (
        (
            _CANONICAL_METADATA_LOGICAL_IDS[0],
            list(canonical),
            (architecture.Finding("invalid-required-call-metadata", "REQUIRED_CALLS"),),
        ),
        (
            _CANONICAL_METADATA_LOGICAL_IDS[1],
            (),
            (architecture.Finding("invalid-required-call-metadata", "REQUIRED_CALLS:empty"),),
        ),
        (
            _CANONICAL_METADATA_LOGICAL_IDS[2],
            (canonical[0], canonical[0], *canonical[2:]),
            (architecture.Finding("duplicate-required-call-metadata", "REQUIRED_CALLS[1]"),),
        ),
        (
            _CANONICAL_METADATA_LOGICAL_IDS[3],
            (mutable, *canonical[1:]),
            (architecture.Finding("invalid-required-call-metadata", "REQUIRED_CALLS[0]"),),
        ),
        (
            _CANONICAL_METADATA_LOGICAL_IDS[4],
            (false_validation, *canonical[1:]),
            (architecture.Finding("invalid-required-call-metadata", "REQUIRED_CALLS[0]"),),
        ),
        (
            _CANONICAL_METADATA_LOGICAL_IDS[5],
            (hostile, *canonical[1:]),
            (architecture.Finding("invalid-required-call-metadata", "REQUIRED_CALLS[0]"),),
        ),
    )
    source = _fresh_call_shape_source(architecture.P2_MANIFEST)
    executed: list[str] = []
    failures: list[str] = []
    for case_id, value, expected in variants:
        executed.append(case_id)
        monkeypatch.setattr(architecture, "REQUIRED_CALLS", value)
        try:
            observed = architecture._call_metadata_manifest_findings()
            public = architecture.future_source_findings(source, architecture.P2_MANIFEST)
            repository = architecture.repository_findings({}, architecture.C0_MANIFEST)
        except Exception as error:  # noqa: BLE001 - every case must execute
            failures.append(f"{case_id}: raised {type(error).__name__}: {error}")
        else:
            if observed != expected or public != expected or repository != expected:
                failures.append(
                    f"{case_id}: observed={observed!r}; public={public!r}; "
                    f"repository={repository!r}"
                )
        monkeypatch.setattr(architecture, "REQUIRED_CALLS", canonical)
    assert (
        executed == list(_CANONICAL_METADATA_LOGICAL_IDS)
        and hostile.counts == dict.fromkeys(_HOOK_NAMES, 0)
        and not failures
    ), "\n".join(failures)


def test_invalid_metadata_never_reaches_shape_interpretation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hostile_cases, _probes = _hostile_metadata_cases()
    cases = (
        *_top_level_metadata_cases(),
        *_nested_metadata_cases(),
        *hostile_cases,
    )
    source = _fresh_call_shape_source(architecture.P2_MANIFEST)
    tree = ast.parse(source)
    analysis = qualified.analyze_qualified_symbols(
        source, module_name=architecture.CANONICAL_MODULE
    )
    interpreted: list[object] = []
    original = architecture._call_shape_matches_in_owner

    def forbidden_interpreter(
        _tree: ast.Module,
        _analysis: qualified.QualifiedSymbolAnalysis,
        requirement: object,
        _owner_name: object,
    ) -> frozenset[architecture.RequiredCallMatch]:
        interpreted.append(requirement)
        return frozenset()

    monkeypatch.setattr(architecture, "_call_shape_matches_in_owner", forbidden_interpreter)
    observations = tuple(
        (
            case.id,
            architecture._required_call_matches(tree, analysis, case.requirement),
            architecture._equivalent_validation_call_matches(tree, analysis, case.requirement),
        )
        for case in cases
    )
    monkeypatch.setattr(architecture, "_call_shape_matches_in_owner", original)
    assert (
        all(not matched and not equivalent for _, matched, equivalent in observations)
        and not interpreted
        and architecture.future_source_findings(source, architecture.P2_MANIFEST) == ()
    )


def test_required_call_metadata_validation_architecture_is_closed() -> None:
    source = Path(architecture.__file__).read_text(encoding="utf-8")
    assert _metadata_validation_architecture_findings(source) == frozenset()


def test_required_call_metadata_validation_mutations_are_detected() -> None:
    source = Path(architecture.__file__).read_text(encoding="utf-8")
    mutations = _metadata_architecture_mutations(source)
    executed: list[str] = []
    failures: list[str] = []
    for case_id, mutated, expected in mutations:
        executed.append(case_id)
        try:
            findings = _metadata_validation_architecture_findings(mutated)
        except Exception as error:  # noqa: BLE001 - every mutation must execute
            failures.append(f"{case_id}: raised {type(error).__name__}: {error}")
            continue
        if expected not in findings:
            failures.append(f"{case_id}: missing {expected!r} in {sorted(findings)!r}")
    assert (
        executed == list(_METADATA_ARCHITECTURE_MUTATION_IDS)
        and len(executed) == len(frozenset(executed))
        and not failures
    ), "\n".join(failures)


def test_exact_protocol_hash_import_alias_is_accepted() -> None:
    source = _future_source(architecture.P1_MANIFEST)
    source = source.replace("protocol_hash as _protocol_hash", "protocol_hash as _hash").replace(
        "_protocol_hash(", "_hash("
    )
    assert architecture.future_source_findings(source, architecture.P1_MANIFEST) == ()


def test_exact_p3_selection_identity_recomputation_is_accepted() -> None:
    source = _future_source(architecture.P3_MANIFEST)
    assert (
        "expected_selector_result_identity = _protocol_hash(" in source
        and "recorded_observations=recorded_observations" in source
        and "recorded_effects=recorded_effects" in source
        and "selection_identity as" not in source
    )
    assert architecture.future_source_findings(source, architecture.P3_MANIFEST) == ()


def test_benign_explanatory_identity_domain_string_is_accepted() -> None:
    source = _future_source(architecture.P1_MANIFEST)
    source += (
        "\ndef _explain_future_domain():\n"
        '    """validation_evidence_calibration_selection/v1 is reserved for a '
        'future checkpoint."""\n'
        "    return None\n"
    )
    assert architecture.future_source_findings(source, architecture.P1_MANIFEST) == ()


def test_renamed_later_stage_aggregate_is_rejected() -> None:
    source = (
        _future_source(architecture.P4_MANIFEST) + "\nclass _FinalCalibrationAggregate:\n    pass\n"
    )
    assert architecture.Finding(
        "top-level-class-surface", architecture.P4_MANIFEST.phase
    ) in architecture.future_source_findings(source, architecture.P4_MANIFEST)


def _codes(source: str) -> frozenset[str]:
    findings = architecture.future_source_findings(source, architecture.P4_MANIFEST)
    return frozenset(item.code for item in findings)


def _findings(source: str) -> frozenset[architecture.Finding]:
    return frozenset(architecture.future_source_findings(source, architecture.P4_MANIFEST))


def _append(addition: str) -> Callable[[str], str]:
    return lambda source: source + addition


def _swap_projection_fields(source: str, class_name: str, left_index: int, right_index: int) -> str:
    fields = architecture.PROJECTION_FIELDS[class_name]
    lines = source.splitlines()
    class_index = lines.index(f"class {class_name}:")
    positions: dict[str, int] = {}
    for index in range(class_index + 1, len(lines)):
        line = lines[index]
        if line and not line.startswith((" ", "\t")):
            break
        field = line.strip().split(":", 1)[0].split("=", 1)[0].strip()
        if field in fields:
            positions[field] = index
    left, right = fields[left_index], fields[right_index]
    lines[positions[left]], lines[positions[right]] = (
        lines[positions[right]],
        lines[positions[left]],
    )
    return "\n".join(lines) + "\n"


def _line_of(source: str, fragment: str) -> int:
    return next(
        line_number
        for line_number, line in enumerate(source.splitlines(), start=1)
        if fragment in line
    )


def _caller_mutation(source: str) -> str:
    source = source.replace(
        "def calibration_selection_id(projection):",
        "def calibration_selection_id(projection, validator: ObservationAuthority, identity_factory, validator_map, *args, **kwargs):",
    )
    source = source.replace(
        "return _protocol_hash('validation_evidence_calibration_selection/v1', projection)",
        "validator(projection)\n    identity_factory(projection)\n    validator_map(projection)\n    return _protocol_hash('validation_evidence_calibration_selection/v1', projection)",
    )
    return source + "\ndef _dispatch(stage_name):\n return _handlers[stage_name]()"


def _assert_isolated(group: str) -> None:
    pristine = _future_source(architecture.P4_MANIFEST)
    cases = tuple(
        LogicalCase(logical.id, logical.mutate(pristine), frozenset({logical.expected}))
        for logical in _ISOLATED_FUTURE.get(group, ())
    )
    _assert_batch(_evaluate_batch(cases, _findings))


def _remove_top_level_definition(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(
        item
        for item in tree.body
        if isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name == name
    )
    start = min((decorator.lineno for decorator in node.decorator_list), default=node.lineno)
    lines = source.splitlines(keepends=True)
    return "".join((*lines[: start - 1], *lines[cast(int, node.end_lineno) :]))


# fmt: off
def _p1_caller_factory(source: str) -> str:
    old = "    projection: CalibrationCandidatePairProjection,\n) -> str:"
    new = "    projection: CalibrationCandidatePairProjection,\n    validator_factory,\n) -> str:"
    assert old in source
    return source.replace(old, new, 1)


def _p1_effect_binding_block(source: str) -> str:
    start = source.index("        if (\n            effect_id != decoded_projection.effect_id\n")
    end = source.index("        if type(selector_result.effect_values[effect_index]) is not float:", start)
    return source[start:end]


def _replace_p1_effect_binding(source: str, replacement: str) -> str:
    block = _p1_effect_binding_block(source)
    return source.replace(block, replacement, 1)


def _remove_p1_effect_binding(source: str) -> str:
    return _replace_p1_effect_binding(source, "")


def _carried_only_p1_effect_binding(source: str) -> str:
    return _replace_p1_effect_binding(source, "        if effect_id != record_effect_id or effect_id != selector_effect_id:\n" '            return _effect_failure(f"source effect ID occurrence[{effect_index}] differs")\n')


def _one_occurrence_p1_effect_binding(source: str) -> str:
    return _replace_p1_effect_binding(source, "        if effect_id != decoded_projection.effect_id:\n" '            return _effect_failure(f"source effect ID occurrence[{effect_index}] differs")\n')


def _expected_id_p1_effect_binding(source: str) -> str:
    block = _p1_effect_binding_block(source)
    return source.replace(block, block.replace("decoded_projection.effect_id", "expected_effect.effect_id"), 1)


def _and_p1_effect_binding(source: str) -> str:
    block = _p1_effect_binding_block(source)
    return source.replace(block, block.replace("\n            or ", "\n            and "), 1)


def _qualified_p1_effect_decoder(source: str) -> str:
    old = "decoded_projection = _decode_run_matched_effect_projection("
    new = "decoded_projection = decoy._decode_run_matched_effect_projection("
    assert old in source
    return source.replace(old, new, 1)


def _qualified_p1_effect_mapper(source: str) -> str:
    block = _p1_effect_binding_block(source)
    old = "_effect_projection_mapping(carried_projection)"
    assert old in source and old not in block
    return source.replace(old, "decoy._effect_projection_mapping(carried_projection)", 1)


def _qualified_p1_effect_failure(source: str) -> str:
    block = _p1_effect_binding_block(source)
    replacement = block.replace("return _effect_failure(", "return decoy._effect_failure(", 1)
    assert replacement != block
    return source.replace(block, replacement, 1)


def _p1_effect_binding_after_value(source: str) -> str:
    block = _p1_effect_binding_block(source)
    source = source.replace(block, "", 1)
    anchor = "        if decoded_projection.observed_effect != expected_f64 or selector_f64 != expected_f64:\n" '            return _effect_failure(f"source effect value[{effect_index}] differs")\n'
    assert anchor in source
    return source.replace(anchor, anchor + block, 1)


def _late_p1_effect_binding(source: str) -> str:
    source = _remove_p1_effect_binding(source)
    anchor = "    return None\n\n\ndef _outcome("
    late_block = "    if (\n        effect_id != decoded_projection.effect_id\n        or record_effect_id != decoded_projection.effect_id\n        or selector_effect_id != decoded_projection.effect_id\n    ):\n" '        return _effect_failure("late decoded effect ID mismatch")\n'
    assert anchor in source
    return source.replace(anchor, late_block + anchor, 1)


def _sorted_p1_effect_binding(source: str) -> str:
    block = _p1_effect_binding_block(source)
    return source.replace(block, block.replace("effect_id != decoded_projection.effect_id", "sorted((effect_id,))[0] != decoded_projection.effect_id", 1), 1)


def _set_p1_effect_binding(source: str) -> str:
    block = _p1_effect_binding_block(source)
    return source.replace(block, block.replace("effect_id != decoded_projection.effect_id", "tuple(set((effect_id,)))[0] != decoded_projection.effect_id", 1), 1)


def _substitute_p1_effect_authority(source: str, authority: str) -> str:
    block = _p1_effect_binding_block(source)
    return source.replace(block, block.replace("decoded_projection.effect_id", authority), 1)


def _continue_after_p1_effect_mismatch(source: str) -> str:
    block = _p1_effect_binding_block(source)
    return source.replace(block, block.replace('            return _effect_failure(f"source effect ID occurrence[{effect_index}] differs")', "            continue"), 1)


def _swap_p1_chronology_blocks(
    source: str,
    first_anchor: str,
    second_anchor: str,
    after_second_anchor: str,
) -> str:
    first = source.index(first_anchor)
    second = source.index(second_anchor, first)
    after_second = source.index(after_second_anchor, second)
    return (
        source[:first] + source[second:after_second] + source[first:second] + source[after_second:]
    )


def _chronology_relation_before_fields(source: str) -> str:
    anchor = "    ) = selection\n"
    relation = (
        "    if selector_result.source_sequence_cutoff != 1:\n"
        '        return _chronology_failure("premature relation")\n'
    )
    function_start = source.index("def _predicate_3o_1_6(")
    insertion = source.index(anchor, function_start) + len(anchor)
    return source[:insertion] + relation + source[insertion:]


def _chronology_identity_before_relation(source: str) -> str:
    anchor = "    if (\n        type(selector_result) is not _CalibrationHistorySelection\n"
    function_start = source.index("def _predicate_3o_1_6(")
    insertion = source.index(anchor, function_start)
    return (
        source[:insertion]
        + "    _premature_identity = strict_chronology_id(strict_chronology)\n"
        + source[insertion:]
    )


def _chronology_qualified_identity(source: str) -> str:
    function_start = source.index("def _predicate_3o_1_6(")
    old = "expected_id = strict_chronology_id(strict_chronology)"
    replacement = "expected_id = decoy.strict_chronology_id(strict_chronology)"
    identity_start = source.index(old, function_start)
    return source[:identity_start] + source[identity_start:].replace(old, replacement, 1)


def _chronology_swap_first_fields(source: str) -> str:
    return _swap_p1_chronology_blocks(
        source,
        "    if strict_chronology.current_effect_excluded is not True:\n",
        "    if strict_chronology.current_observation_excluded is not True:\n",
        "    if (\n        type(strict_chronology.effect_available_sequences) is not tuple\n",
    )


def _chronology_cutoff_before_schema(source: str) -> str:
    return _swap_p1_chronology_blocks(
        source,
        "    if (\n        type(strict_chronology.schema_version) is not str\n",
        "    if (\n        type(strict_chronology.source_sequence_cutoff) is not int\n",
        "    if (\n        type(selector_result) is not _CalibrationHistorySelection\n",
    )


def _chronology_broad_equality(source: str) -> str:
    start = source.index("    if strict_chronology.current_effect_excluded is not True:\n")
    end = source.index(
        "    if (\n        type(selector_result) is not _CalibrationHistorySelection\n",
        start,
    )
    replacement = (
        "    if strict_chronology != strict_chronology:\n"
        '        return _chronology_failure("chronology differs")\n'
    )
    return source[:start] + replacement + source[end:]


def _harness_import(source: str, name: str, alias: str | None = None) -> str:
    anchor = "    StrictChronologyProjection,\n"
    imported = f"    {name}{f' as {alias}' if alias else ''},\n"
    assert anchor in source
    return source.replace(anchor, anchor + imported, 1)


def _harness_pair_helper_call(source: str) -> str:
    source = _harness_import(source, "calibration_candidate_pair_id")
    return source.replace(
        "pair_ids.append(expected_candidate_pair_id(pair_projection))",
        "pair_ids.append(calibration_candidate_pair_id(pair_projection))",
        1,
    )


def _harness_chronology_helper_call(source: str) -> str:
    source = _harness_import(source, "strict_chronology_id")
    return source.replace(
        "chronology_identity = expected_strict_chronology_id(chronology)",
        "chronology_identity = strict_chronology_id(chronology)",
        1,
    )


def _harness_private_helper_call(source: str, name: str) -> str:
    source = _harness_import(source, name)
    return source + f"\ndef _private_production_helper_call(value):\n    return {name}(value)\n"


def _harness_qualified_import(source: str) -> str:
    anchor = "from research_decision_engine.benchmarks.broader_calibration_evidence import (\n"
    qualified_import = (
        "from research_decision_engine.benchmarks import "
        "broader_calibration_evidence as production_evidence\n"
    )
    assert anchor in source
    return source.replace(anchor, qualified_import + anchor, 1)


def _harness_qualified_helper_call(source: str, name: str) -> str:
    source = _harness_qualified_import(source)
    return (
        source + "\ndef _qualified_production_helper_call(value):\n"
        f"    return production_evidence.{name}(value)\n"
    )


def _harness_assigned_helper_alias_call(source: str, name: str) -> str:
    source = _harness_qualified_import(source)
    return (
        source + f"\n_assigned_production_helper = production_evidence.{name}\n"
        "def _assigned_production_helper_call(value):\n"
        "    return _assigned_production_helper(value)\n"
    )


def _harness_production_validation_expectation(source: str) -> str:
    source = _harness_import(
        source,
        "_validate_stage2f_p1",
        "_production_validate",
    )
    return (
        source + "\n_EXPECTED_FROM_PRODUCTION = _production_validate("
        "selections=(), expected_execution_attestation_pairs=(), "
        "attested_execution_specification_ids=())\n"
    )


def _harness_production_output_as_expected(source: str) -> str:
    source = _harness_import(
        source,
        "_validate_stage2f_p1",
        "_production_validate",
    )
    return (
        source + "\ndef _bad_expected():\n"
        "    expected = _production_validate("
        "selections=(), expected_execution_attestation_pairs=(), "
        "attested_execution_specification_ids=())\n"
        "    return expected\n"
    )


# fmt: off
def _insert_before_validator_line(source: str, anchor: str, addition: str) -> str:
    assert source.count(anchor) == 1
    return source.replace(anchor, addition + anchor, 1)

def _p1_hidden_family_6_preflight(source: str) -> str:
    source = _insert_before_validator_line(source, "    count_0 = 0\n", "    _schedule_family_6_preflight(selections[0])\n")
    return source + "\ndef _schedule_family_6_preflight(selection):\n    return _predicate_3o_1_6(selection)\n"

def _p1_inter_family_helper(source: str, *, anchor: str, name: str, body: str = "    return None\n") -> str:
    source = _insert_before_validator_line(source, anchor, f"    {name}()\n")
    return source + f"\ndef {name}() -> None:\n{body}"

def _p1_failure_caught_and_continued(source: str) -> str:
    original = "        failure = _predicate_3o_1_3(selections[index], index)\n        if failure is not None:\n"
    replacement = "        try:\n            failure = _predicate_3o_1_3(selections[index], index)\n        except Exception:\n            failure = None\n        if failure is not None:\n"
    assert source.count(original) == 1
    return source.replace(original, replacement, 1)

def _swap_p1_validator_predicates(source: str, left: int, right: int) -> str:
    left_call, right_call, marker = f"failure = _predicate_3o_1_{left}(", f"failure = _predicate_3o_1_{right}(", f"failure = _schedule_swap_{left}_{right}("
    assert source.count(left_call) == source.count(right_call) == 1
    return source.replace(left_call, marker, 1).replace(right_call, left_call, 1).replace(marker, right_call, 1)

def _conditional_p1_family_3(source: str) -> str:
    call = "        failure = _predicate_3o_1_3(selections[index], index)\n"
    assert source.count(call) == 1
    return source.replace(call, "        if selections:\n            failure = _predicate_3o_1_3(selections[index], index)\n        else:\n            failure = None\n", 1)

def _insert_p1_family_5_body(source: str, addition: str) -> str:
    anchor = "def _predicate_3o_1_5(\n    selection: _SelectionEvidence,\n) -> _PredicateFailure | None:\n"
    assert source.count(anchor) == 1
    return source.replace(anchor, anchor + addition, 1)

def _extra_chronology_helper_inside_p1_family_6(source: str) -> str:
    anchor = "def _predicate_3o_1_6(\n    selection: _SelectionEvidence,\n) -> _PredicateFailure | None:\n"
    assert source.count(anchor) == 1
    return source.replace(anchor, anchor + "    _schedule_extra_chronology(selection[-2])\n", 1) + "\ndef _schedule_extra_chronology(projection):\n    return _strict_chronology_mapping(projection)\n"

def _p1_p2_before_family_6(source: str) -> str:
    return _insert_before_validator_line(source, "    count_6 = 0\n", "    _source_observation_matches(None, None)\n") + "\ndef _source_observation_matches(projection, carried_identity):\n    return projection is carried_identity\n"

def _p1_p2_inside_family_5(source: str) -> str:
    return _insert_p1_family_5_body(source, "    _source_observation_matches(None, None)\n") + "\ndef _source_observation_matches(projection, carried_identity):\n    return projection is carried_identity\n"

def _p1_p2_decoder_before_family_6(source: str) -> str:
    return _insert_before_validator_line(source, "    count_6 = 0\n", "    _decode_calibration_source_observation_projection(None)\n") + "\ndef _decode_calibration_source_observation_projection(projection):\n    return projection\n"

def _p1_predicates_per_selection(source: str) -> str:
    start_marker, end_marker = "    count_0 = 0\n", "    return (\n        None,\n"
    start, end = source.index(start_marker), source.index(end_marker, source.index(start_marker))
    replacement = "    for index in range(_CANONICAL_SELECTION_COUNT):\n        _predicate_3o_1_0(\n            selections[index],\n            expected_execution_attestation_pairs,\n            attested_execution_specification_ids,\n        )\n        _predicate_3o_1_1(selections[index])\n        _predicate_3o_1_2(selections[index])\n        _predicate_3o_1_3(selections[index], index)\n        _predicate_3o_1_4(selections[index])\n        _predicate_3o_1_5(selections[index])\n        _predicate_3o_1_6(selections[index])\n    count_0 = count_1 = count_2 = count_3 = count_4 = count_5 = count_6 = 0\n"
    return source[:start] + replacement + source[end:]

def _harness_qualified_alias(source: str, addition: str) -> str:
    return _harness_qualified_import(source) + addition

_ACTIVE_P1_CASES = (
    Mutation("active-p1-wrong-owner", lambda source: source, architecture.Finding("wrong-module-owner", f"{architecture._EXECUTION}:CalibrationCandidatePairProjection")),
    Mutation("active-p1-extra-class", _append("\nclass _UnexpectedProjection:\n    pass\n"), architecture.Finding("top-level-class-surface", "P1")),
    Mutation("active-p1-missing-class", lambda source: _remove_top_level_definition(source, "StrictChronologyProjection"), architecture.Finding("top-level-class-surface", "P1")),
    Mutation("active-p1-class-alias", _append("\n_PairAlias = CalibrationCandidatePairProjection\n"), architecture.Finding("stage2f-assignment-alias", "_PairAlias")),
    Mutation("active-p1-identity-alias", _append("\n_pair_identity_alias = calibration_candidate_pair_id\n"), architecture.Finding("stage2f-assignment-alias", "_pair_identity_alias")),
    Mutation("active-p1-wrong-schema", _replace("broader-replication-calibration-candidate-pair/v1", "broader-replication-calibration-candidate-pair/v2"), architecture.Finding("schema-literal", "CalibrationCandidatePairProjection")),
    Mutation("active-p1-wrong-domain", _replace("validation_evidence_calibration_candidate_pair/v1", "validation_evidence_calibration_candidate_pair/v2"), architecture.Finding("identity-domain", "calibration_candidate_pair_id")),
    Mutation("active-p1-extra-identity", _append("\ndef calibration_selection_id(projection):\n    return _protocol_hash('validation_evidence_calibration_selection/v1', projection)\n"), architecture.Finding("public-function-surface", "P1")),
    Mutation("active-p1-public-validator", _append("\ndef validate_stage2f_calibration_evidence():\n    return None\n"), architecture.Finding("public-function-surface", "P1")),
    Mutation("active-p1-premature-p2-surface", _append("\nclass CalibrationSourceObservationProjection:\n    pass\n"), architecture.Finding("top-level-class-surface", "P1")),
    Mutation("active-p1-live-helper-import-call", _append(f"\nfrom {architecture._ORACLE} import authorize_observation as _authorize_observation\ndef _live_call():\n    return _authorize_observation()\n"), architecture.Finding("forbidden-sensitive-call", "_authorize_observation")),
    Mutation("active-p1-reader-persistence-evidence-surface", _append("\nfrom research_decision_engine.benchmarks.broader_validation_evidence import write_evidence as _write_evidence\n"), architecture.Finding("forbidden-import", "research_decision_engine.benchmarks.broader_validation_evidence")),
    Mutation("active-p1-dynamic-export", _append("\n__all__ = ('CalibrationCandidatePairProjection',)\n"), architecture.Finding("dynamic-export-surface", "__all__")),
    Mutation("active-p1-second-hash-algebra", _append("\nimport hashlib\ndef _other_hash(payload):\n    return hashlib.sha256(payload)\n"), architecture.Finding("second-hash-algebra", "hashlib.sha256")),
    Mutation("active-p1-raw-sha-replaced-by-framed-hash", _replace("return _raw_effect_sha256(effect)", "return _protocol_hash('raw/v1', effect)"), architecture.Finding("nonidentity-protocol-hash", "_effect_payload_sha256")),
    Mutation("active-p1-caller-validator-factory", _p1_caller_factory, architecture.Finding("caller-authority-parameter", "calibration_candidate_pair_id:validator_factory")),
    Mutation("active-p1-p2-p3-p4-leakage", _append("\nclass ScientificCalibrationSelectionProjection:\n    pass\nclass CalibrationSelectionProjection:\n    pass\ndef source_observation_identity(projection):\n    return projection\n"), architecture.Finding("top-level-class-surface", "P1")),
    Mutation("active-p1-effect-remove-decoded-comparison", _remove_p1_effect_binding, architecture.Finding("p1-effect-id-binding", "complete-decoded-relation")),
    Mutation("active-p1-effect-carried-only-comparison", _carried_only_p1_effect_binding, architecture.Finding("p1-effect-id-binding", "complete-decoded-relation")),
    Mutation("active-p1-effect-one-carried-occurrence", _one_occurrence_p1_effect_binding, architecture.Finding("p1-effect-id-binding", "ordered_source_effects.effect_id")),
    Mutation("active-p1-effect-expected-not-decoded", _expected_id_p1_effect_binding, architecture.Finding("p1-effect-id-binding", "complete-decoded-relation")),
    Mutation("active-p1-effect-and-relation", _and_p1_effect_binding, architecture.Finding("p1-effect-id-binding", "complete-decoded-relation")),
    Mutation("active-p1-effect-qualified-decoder-decoy", _qualified_p1_effect_decoder, architecture.Finding("p1-effect-id-binding", "strict-decode")),
    Mutation("active-p1-effect-qualified-mapper-decoy", _qualified_p1_effect_mapper, architecture.Finding("p1-effect-id-binding", "complete-projection-decode")),
    Mutation("active-p1-effect-qualified-failure-decoy", _qualified_p1_effect_failure, architecture.Finding("p1-effect-id-binding", "stop-on-mismatch")),
    Mutation("active-p1-effect-relation-after-value", _p1_effect_binding_after_value, architecture.Finding("p1-effect-id-binding", "relation-before-value")),
    Mutation("active-p1-effect-decoded-after-chronology", _late_p1_effect_binding, architecture.Finding("p1-effect-id-binding", "complete-decoded-relation")),
    Mutation("active-p1-effect-sort-before-comparison", _sorted_p1_effect_binding, architecture.Finding("p1-effect-id-binding", "no-sort")),
    Mutation("active-p1-effect-set-before-comparison", _set_p1_effect_binding, architecture.Finding("p1-effect-id-binding", "no-set")),
    Mutation("active-p1-effect-digest-substitute", lambda source: _substitute_p1_effect_authority(source, "payload_sha256"), architecture.Finding("p1-effect-id-binding", "complete-decoded-relation")),
    Mutation("active-p1-effect-value-substitute", lambda source: _substitute_p1_effect_authority(source, "decoded_projection.observed_effect"), architecture.Finding("p1-effect-id-binding", "complete-decoded-relation")),
    Mutation("active-p1-effect-catch-and-continue", _continue_after_p1_effect_mismatch, architecture.Finding("p1-effect-id-binding", "stop-on-mismatch")),
    Mutation("active-p1-chronology-relation-before-fields", _chronology_relation_before_fields, architecture.Finding("p1-chronology-order", "relation-after-fields")),
    Mutation("active-p1-chronology-identity-before-relation", _chronology_identity_before_relation, architecture.Finding("p1-chronology-order", "identity-last")),
    Mutation("active-p1-chronology-qualified-identity-decoy", _chronology_qualified_identity, architecture.Finding("p1-chronology-order", "identity-last")),
    Mutation("active-p1-chronology-field-order-swap", _chronology_swap_first_fields, architecture.Finding("p1-chronology-order", "declaration-order")),
    Mutation("active-p1-chronology-cutoff-before-schema", _chronology_cutoff_before_schema, architecture.Finding("p1-chronology-order", "declaration-order")),
    Mutation("active-p1-chronology-broad-equality", _chronology_broad_equality, architecture.Finding("p1-chronology-order", "current_effect_excluded")),
    Mutation("active-p1-chronology-hidden-extra-mapper", _extra_chronology_helper_inside_p1_family_6, architecture.Finding("p1-validator-chronology", "_strict_chronology_mapping")),
)
_HARNESS_CASES = (
    Mutation("harness-import-pair-identity-helper", lambda source: _harness_import(source, "calibration_candidate_pair_id"), architecture.Finding("harness-production-identity-helper", "calibration_candidate_pair_id")),
    Mutation("harness-import-chronology-identity-helper", lambda source: _harness_import(source, "strict_chronology_id"), architecture.Finding("harness-production-identity-helper", "strict_chronology_id")),
    Mutation("harness-call-production-pair-helper", _harness_pair_helper_call, architecture.Finding("harness-production-identity-helper-call", "calibration_candidate_pair_id")),
    Mutation("harness-call-production-chronology-helper", _harness_chronology_helper_call, architecture.Finding("harness-production-identity-helper-call", "strict_chronology_id")),
    Mutation("harness-import-private-mapper", lambda source: _harness_import(source, "_strict_chronology_mapping"), architecture.Finding("harness-private-production-helper", "_strict_chronology_mapping")),
    Mutation("harness-import-private-decoder", lambda source: _harness_import(source, "_decode_strict_chronology_projection"), architecture.Finding("harness-private-production-helper", "_decode_strict_chronology_projection")),
    Mutation("harness-call-private-mapper", lambda source: _harness_private_helper_call(source, "_strict_chronology_mapping"), architecture.Finding("harness-private-production-helper-call", "_strict_chronology_mapping")),
    Mutation("harness-call-private-decoder", lambda source: _harness_private_helper_call(source, "_decode_strict_chronology_projection"), architecture.Finding("harness-private-production-helper-call", "_decode_strict_chronology_projection")),
    Mutation("harness-qualified-pair-helper", lambda source: _harness_qualified_helper_call(source, "calibration_candidate_pair_id"), architecture.Finding("harness-production-identity-helper-call", "calibration_candidate_pair_id")),
    Mutation("harness-qualified-chronology-helper", lambda source: _harness_qualified_helper_call(source, "strict_chronology_id"), architecture.Finding("harness-production-identity-helper-call", "strict_chronology_id")),
    Mutation("harness-qualified-private-mapper", lambda source: _harness_qualified_helper_call(source, "_strict_chronology_mapping"), architecture.Finding("harness-private-production-helper-call", "_strict_chronology_mapping")),
    Mutation("harness-qualified-private-decoder", lambda source: _harness_qualified_helper_call(source, "_decode_strict_chronology_projection"), architecture.Finding("harness-private-production-helper-call", "_decode_strict_chronology_projection")),
    Mutation("harness-assigned-pair-helper-alias", lambda source: _harness_assigned_helper_alias_call(source, "calibration_candidate_pair_id"), architecture.Finding("harness-production-identity-helper-call", "calibration_candidate_pair_id")),
    Mutation("harness-assigned-chronology-helper-alias", lambda source: _harness_assigned_helper_alias_call(source, "strict_chronology_id"), architecture.Finding("harness-production-identity-helper-call", "strict_chronology_id")),
    Mutation("harness-derived-expected-from-production", _harness_production_validation_expectation, architecture.Finding("harness-production-derived-expectation", "_validate_stage2f_p1")),
    Mutation("harness-production-output-is-expected", _harness_production_output_as_expected, architecture.Finding("harness-production-output-as-expected", "expected")),
    Mutation("harness-second-full-p1-validator", _append("\ndef _check_bundle(selections):\n    predicates = (_predicate_3o_1_0, _predicate_3o_1_1, _predicate_3o_1_2, _predicate_3o_1_3, _predicate_3o_1_4, _predicate_3o_1_5, _predicate_3o_1_6)\n    return tuple(predicate(selection) for predicate in predicates for selection in selections)\n"), architecture.Finding("harness-competing-p1-validator", "_check_bundle")),
    Mutation("harness-second-318-selection-engine", _append("\ndef _second_engine():\n    for predicate_index in range(7):\n        for selection_index in range(318):\n            yield predicate_index, selection_index\n"), architecture.Finding("harness-second-predicate-engine", "_second_engine")),
    Mutation("harness-second-enumerated-predicate-engine", _append("\ndef _enumerated_engine(selections):\n    predicates = (_predicate_3o_1_0, _predicate_3o_1_1, _predicate_3o_1_2, _predicate_3o_1_3, _predicate_3o_1_4, _predicate_3o_1_5, _predicate_3o_1_6)\n    for predicate_index, predicate in enumerate(predicates):\n        for selection_index, selection in enumerate(selections):\n            yield predicate_index, selection_index, predicate(selection)\n"), architecture.Finding("harness-second-predicate-engine", "_enumerated_engine")),
)
_P1_SCHEDULE_CASES = (
    Mutation("schedule-family-6-before-family-0", lambda source: _insert_before_validator_line(source, "    count_0 = 0\n", "    _predicate_3o_1_6(selections[0])\n"), architecture.Finding("p1-validator-schedule", "family-6-count")),
    Mutation("schedule-family-6-hidden-helper-preflight", _p1_hidden_family_6_preflight, architecture.Finding("p1-validator-schedule", "hidden-helper")),
    Mutation("schedule-family-6-nested-helper-preflight", lambda source: _insert_before_validator_line(source, "    count_0 = 0\n", "    def nested_family_6_preflight(selection):\n        return _predicate_3o_1_6(selection)\n    nested_family_6_preflight(selections[0])\n"), architecture.Finding("p1-validator-schedule", "helper-propagation")),
    Mutation("schedule-family-6-one-hop-alias-preflight", lambda source: _insert_before_validator_line(source, "    count_0 = 0\n", "    family_6_alias = _predicate_3o_1_6\n    family_6_alias(selections[0])\n"), architecture.Finding("p1-validator-schedule", "predicate-alias")),
    Mutation("schedule-family-6-two-hop-alias-preflight", lambda source: _insert_before_validator_line(source, "    count_0 = 0\n", "    family_6_alias = _predicate_3o_1_6\n    family_6_alias_2 = family_6_alias\n    family_6_alias_2(selections[0])\n"), architecture.Finding("p1-validator-schedule", "predicate-alias")),
    Mutation("schedule-swap-family-0-and-family-1", lambda source: _swap_p1_validator_predicates(source, 0, 1), architecture.Finding("p1-validator-schedule", "family-order")),
    Mutation("schedule-swap-family-5-and-family-6", lambda source: _swap_p1_validator_predicates(source, 5, 6), architecture.Finding("p1-validator-schedule", "family-order")),
    Mutation("schedule-duplicate-family-6", _replace("        failure = _predicate_3o_1_6(selections[index])\n", "        failure = _predicate_3o_1_6(selections[index])\n        _predicate_3o_1_6(selections[index])\n"), architecture.Finding("p1-validator-schedule", "family-6-count")),
    Mutation("schedule-omit-family-4", _replace("        failure = _predicate_3o_1_4(selections[index])\n", "        failure = None\n"), architecture.Finding("p1-validator-schedule", "family-4-count")),
    Mutation("schedule-family-3-conditional", _conditional_p1_family_3, architecture.Finding("p1-validator-schedule", "family-3-loop")),
    Mutation("schedule-family-3-continue-before-call", _replace("        failure = _predicate_3o_1_3(selections[index], index)\n", "        if index == 0:\n            continue\n        failure = _predicate_3o_1_3(selections[index], index)\n"), architecture.Finding("p1-validator-schedule", "family-3-loop")),
    Mutation("schedule-family-3-break-after-call", _replace("        failure = _predicate_3o_1_3(selections[index], index)\n", "        failure = _predicate_3o_1_3(selections[index], index)\n        if index == 0:\n            break\n"), architecture.Finding("p1-validator-schedule", "family-3-loop")),
    Mutation("schedule-shadow-builtins-range", lambda source: _insert_before_validator_line(source, "    count_0 = 0\n", "    range = tuple\n"), architecture.Finding("p1-validator-schedule", "range-authority")),
    Mutation("schedule-rebind-selection-count", _append("\n_CANONICAL_SELECTION_COUNT = 0\n"), architecture.Finding("p1-validator-schedule", "selection-count-authority")),
    Mutation("schedule-import-rebind-selection-count", _append("\nfrom typing import Final as _CANONICAL_SELECTION_COUNT\n"), architecture.Finding("p1-validator-schedule", "selection-count-authority")),
    Mutation("schedule-definition-rebind-selection-count", _append("\ndef _CANONICAL_SELECTION_COUNT():\n    return 0\n"), architecture.Finding("p1-validator-schedule", "selection-count-authority")),
    Mutation("schedule-early-return-before-family-0", lambda source: _insert_before_validator_line(source, "    count_0 = 0\n", "    if selections:\n        return (None, (0, 0, 0, 0, 0, 0, 0))\n"), architecture.Finding("p1-validator-schedule", "entry-skeleton")),
    Mutation("schedule-precondition-always-returns", _replace("    if type(selections) is not tuple or len(selections) != _CANONICAL_SELECTION_COUNT:\n", "    if True:\n"), architecture.Finding("p1-validator-schedule", "entry-skeleton")),
    Mutation("schedule-chronology-identity-before-family-6", lambda source: _insert_before_validator_line(source, "    count_6 = 0\n", "    strict_chronology_id(selections[0].strict_chronology)\n"), architecture.Finding("p1-validator-chronology", "strict_chronology_id")),
    Mutation("schedule-chronology-mapper-before-family-6", lambda source: _insert_before_validator_line(source, "    count_6 = 0\n", "    _strict_chronology_mapping(selections[0].strict_chronology)\n"), architecture.Finding("p1-validator-chronology", "_strict_chronology_mapping")),
    Mutation("schedule-family-6-inside-family-5", lambda source: _insert_p1_family_5_body(source, "    _predicate_3o_1_6(selection)\n"), architecture.Finding("p1-validator-schedule", "family-6-count")),
    Mutation("schedule-chronology-identity-inside-family-5", lambda source: _insert_p1_family_5_body(source, "    strict_chronology_id(selection[-2])\n"), architecture.Finding("p1-validator-chronology", "strict_chronology_id")),
    Mutation("schedule-chronology-mapper-inside-family-5", lambda source: _insert_p1_family_5_body(source, "    _strict_chronology_mapping(selection[-2])\n"), architecture.Finding("p1-validator-chronology", "_strict_chronology_mapping")),
    Mutation("schedule-p2-helper-before-family-6", _p1_p2_before_family_6, architecture.Finding("p1-validator-p2", "_source_observation_matches")),
    Mutation("schedule-p2-helper-inside-family-5", _p1_p2_inside_family_5, architecture.Finding("p1-validator-p2", "_source_observation_matches")),
    Mutation("schedule-p2-decoder-before-family-6", _p1_p2_decoder_before_family_6, architecture.Finding("p1-validator-p2", "_decode_calibration_source_observation_projection")),
    Mutation("schedule-callable-tuple-dispatch", lambda source: _insert_before_validator_line(source, "    count_0 = 0\n", "    predicate_schedule = (_predicate_3o_1_0, _predicate_3o_1_1, _predicate_3o_1_2, _predicate_3o_1_3, _predicate_3o_1_4, _predicate_3o_1_5, _predicate_3o_1_6)\n    predicate_schedule[-1](selections[0])\n"), architecture.Finding("p1-validator-schedule", "dynamic-dispatch")),
    Mutation("schedule-mapping-dispatch", lambda source: _insert_before_validator_line(source, "    count_0 = 0\n", "    predicate_schedule = {'late': _predicate_3o_1_6}\n    predicate_schedule['late'](selections[0])\n"), architecture.Finding("p1-validator-schedule", "dynamic-dispatch")),
    Mutation("schedule-predicates-inside-selection-loop", _p1_predicates_per_selection, architecture.Finding("p1-validator-schedule", "predicate-family-major")),
    Mutation("schedule-helper-returning-family-6-callable", lambda source: _p1_inter_family_helper(source, anchor="    count_1 = 0\n", name="_return_family_6_callable", body="    return _predicate_3o_1_6\n"), architecture.Finding("p1-validator-schedule", "dynamic-dispatch")),
    Mutation("schedule-helper-hidden-chronology-identity", lambda source: _p1_inter_family_helper(source, anchor="    count_6 = 0\n", name="_early_chronology_identity", body="    strict_chronology_id(None)\n    return None\n"), architecture.Finding("p1-validator-chronology", "strict_chronology_id")),
    Mutation("schedule-helper-hidden-chronology-mapper", lambda source: _p1_inter_family_helper(source, anchor="    count_6 = 0\n", name="_early_chronology_mapper", body="    _strict_chronology_mapping(None)\n    return None\n"), architecture.Finding("p1-validator-chronology", "_strict_chronology_mapping")),
    Mutation("schedule-unresolved-helper-between-families", lambda source: _insert_before_validator_line(source, "    count_2 = 0\n", "    _unresolved_schedule_helper()\n"), architecture.Finding("p1-validator-schedule", "dynamic-dispatch")),
    Mutation("schedule-failure-caught-and-continued", _p1_failure_caught_and_continued, architecture.Finding("p1-validator-schedule", "family-3-loop")),
)
_P1_BENIGN_SCHEDULE_CASES = (
    ("schedule-benign-helper-between-family-0-and-family-1", lambda source: _p1_inter_family_helper(source, anchor="    count_1 = 0\n", name="_neutral_between_0_and_1")),
    ("schedule-benign-helper-between-family-5-and-family-6", lambda source: _p1_inter_family_helper(source, anchor="    count_6 = 0\n", name="_neutral_between_5_and_6")),
    ("schedule-benign-inert-assignment-between-families", lambda source: _insert_before_validator_line(source, "    count_3 = 0\n", "    neutral_schedule_note = ('fixture', 3)\n")),
    ("schedule-benign-helper-after-family-6", lambda source: _p1_inter_family_helper(source, anchor="    return (\n        None,\n", name="_neutral_after_family_6")),
    ("schedule-benign-comment-and-docstring-change", lambda source: _insert_before_validator_line(source.replace("Validate frozen 3o.1 in predicate-family-major order.", "Validate the frozen family-major schedule.", 1), "    count_4 = 0\n", "    # Proven-neutral schedule comment.\n")),
)
_HARNESS_ALIAS_CASES = (
    Mutation("harness-alias-pair-identity-direct-qualified", lambda source: _harness_qualified_alias(source, "\npair_identity_alias = production_evidence.calibration_candidate_pair_id\n"), architecture.Finding("harness-forbidden-production-alias", "calibration_candidate_pair_id")),
    Mutation("harness-alias-chronology-identity-direct-qualified", lambda source: _harness_qualified_alias(source, "\nchronology_identity_alias = production_evidence.strict_chronology_id\n"), architecture.Finding("harness-forbidden-production-alias", "strict_chronology_id")),
    Mutation("harness-alias-pair-mapper-direct-qualified", lambda source: _harness_qualified_alias(source, "\npair_mapper_alias = production_evidence._calibration_candidate_pair_mapping\n"), architecture.Finding("harness-forbidden-production-alias", "_calibration_candidate_pair_mapping")),
    Mutation("harness-alias-chronology-mapper-direct-qualified", lambda source: _harness_qualified_alias(source, "\nchronology_mapper_alias = production_evidence._strict_chronology_mapping\n"), architecture.Finding("harness-forbidden-production-alias", "_strict_chronology_mapping")),
    Mutation("harness-alias-pair-decoder-direct-qualified", lambda source: _harness_qualified_alias(source, "\npair_decoder_alias = production_evidence._decode_calibration_candidate_pair_projection\n"), architecture.Finding("harness-forbidden-production-alias", "_decode_calibration_candidate_pair_projection")),
    Mutation("harness-alias-chronology-decoder-direct-qualified", lambda source: _harness_qualified_alias(source, "\nchronology_decoder_alias = production_evidence._decode_strict_chronology_projection\n"), architecture.Finding("harness-forbidden-production-alias", "_decode_strict_chronology_projection")),
    Mutation("harness-alias-imported-module", lambda source: source + "\nfrom research_decision_engine.benchmarks import broader_calibration_evidence as imported_production_evidence\nimported_module_alias = imported_production_evidence.strict_chronology_id\n", architecture.Finding("harness-forbidden-production-alias", "strict_chronology_id")),
    Mutation("harness-alias-from-import-as", lambda source: source + f"\nfrom {architecture.CANONICAL_MODULE} import _calibration_candidate_pair_mapping as imported_pair_mapper\n", architecture.Finding("harness-forbidden-production-alias", "_calibration_candidate_pair_mapping")),
    Mutation("harness-alias-one-hop", lambda source: _harness_qualified_alias(source, "\nfirst_alias = production_evidence.strict_chronology_id\nsecond_alias = first_alias\n"), architecture.Finding("harness-forbidden-production-alias", "strict_chronology_id")),
    Mutation("harness-alias-two-hop", lambda source: _harness_qualified_alias(source, "\nfirst_alias = production_evidence.strict_chronology_id\nsecond_alias = first_alias\nthird_alias = second_alias\n"), architecture.Finding("harness-forbidden-production-alias", "strict_chronology_id")),
    Mutation("harness-alias-annotated-assignment", lambda source: _harness_qualified_alias(source, "\nannotated_alias: object = production_evidence.calibration_candidate_pair_id\n"), architecture.Finding("harness-forbidden-production-alias", "calibration_candidate_pair_id")),
    Mutation("harness-alias-tuple-container", lambda source: _harness_qualified_alias(source, "\ntuple_aliases = (production_evidence.strict_chronology_id,)\n"), architecture.Finding("harness-forbidden-production-alias", "strict_chronology_id")),
    Mutation("harness-alias-list-container", lambda source: _harness_qualified_alias(source, "\nlist_aliases = [production_evidence._strict_chronology_mapping]\n"), architecture.Finding("harness-forbidden-production-alias", "_strict_chronology_mapping")),
    Mutation("harness-alias-destructuring-assignment", lambda source: _harness_qualified_alias(source, "\n(destructured_alias,) = (production_evidence._decode_strict_chronology_projection,)\n"), architecture.Finding("harness-forbidden-production-alias", "_decode_strict_chronology_projection")),
    Mutation("harness-alias-walrus-assignment", lambda source: _harness_qualified_alias(source, "\nif (walrus_alias := production_evidence.calibration_candidate_pair_id):\n    pass\n"), architecture.Finding("harness-forbidden-production-alias", "calibration_candidate_pair_id")),
    Mutation("harness-alias-class-attribute", lambda source: _harness_qualified_alias(source, "\nclass ForbiddenAliasHolder:\n    chronology_alias = production_evidence.strict_chronology_id\n"), architecture.Finding("harness-forbidden-production-alias", "strict_chronology_id")),
    Mutation("harness-alias-module-all-export", lambda source: _harness_qualified_alias(source, "\nexported_alias = production_evidence._strict_chronology_mapping\n__all__ = ('exported_alias',)\n"), architecture.Finding("harness-forbidden-production-alias", "_strict_chronology_mapping")),
    Mutation("harness-alias-function-default", lambda source: _harness_qualified_alias(source, "\ndef forbidden_default(alias=production_evidence._decode_calibration_candidate_pair_projection):\n    return alias\n"), architecture.Finding("harness-forbidden-production-alias", "_decode_calibration_candidate_pair_projection")),
    Mutation("harness-alias-mapping-container", lambda source: _harness_qualified_alias(source, "\nmapping_aliases = {'pair': production_evidence._calibration_candidate_pair_mapping}\n"), architecture.Finding("harness-forbidden-production-alias", "_calibration_candidate_pair_mapping")),
    Mutation("harness-alias-helper-returned", lambda source: _harness_qualified_alias(source, "\ndef return_forbidden_alias():\n    return production_evidence._decode_strict_chronology_projection\nhelper_returned_alias = return_forbidden_alias()\n"), architecture.Finding("harness-forbidden-production-alias", "_decode_strict_chronology_projection")),
    Mutation("harness-alias-created-never-called", lambda source: _harness_qualified_alias(source, "\nnever_called_forbidden_alias = production_evidence.calibration_candidate_pair_id\n"), architecture.Finding("harness-forbidden-production-alias", "calibration_candidate_pair_id")),
    Mutation("harness-alias-unresolved-sensitive-member", lambda source: _harness_qualified_alias(source, "\ndef unresolved_sensitive_alias(helper_name):\n    return getattr(\n        production_evidence,\n        helper_name,\n    )\n"), architecture.Finding("harness-unresolved-production-alias", "getattr")),
    Mutation("harness-alias-star-import", lambda source: source + f"\nfrom {architecture.CANONICAL_MODULE} import *\n", architecture.Finding("harness-unresolved-production-alias", "star-import")),
    Mutation("harness-alias-dynamic-production-import", lambda source: source + f"\ndynamic_production = __import__('{architecture.CANONICAL_MODULE}', fromlist=('strict_chronology_id',))\ndynamic_alias = getattr(dynamic_production, 'strict_chronology_id')\n", architecture.Finding("harness-unresolved-production-alias", "__import__")),
    Mutation("harness-alias-concatenated-dynamic-import", lambda source: source + "\nproduction_module_name = 'research_decision_engine.benchmarks.broader_' + 'calibration_evidence'\ndynamic_production = __import__(production_module_name, fromlist=('strict_chronology_id',))\ndynamic_alias = getattr(dynamic_production, 'strict_chronology_id')\n", architecture.Finding("harness-unresolved-production-alias", "__import__")),
    Mutation("harness-alias-helper-dynamic-member", lambda source: _harness_qualified_alias(source, "\ndef dynamic_member(module, member_name):\n    return getattr(module, member_name)\nhelper_dynamic_alias = dynamic_member(production_evidence, 'strict_chronology_id')\n"), architecture.Finding("harness-unresolved-production-alias", "getattr")),
    Mutation("harness-alias-projection-globals-namespace", _append("\nprojection_globals_alias = CalibrationCandidatePairProjection.__init__.__globals__['calibration_candidate_pair_id']\n"), architecture.Finding("harness-unresolved-production-alias", "dynamic-namespace")),
    Mutation("harness-alias-helper-parameter-identity", lambda source: _harness_qualified_alias(source, "\ndef extract_identity(module):\n    return module.strict_chronology_id\nparameter_identity_alias = extract_identity(production_evidence)\n"), architecture.Finding("harness-unresolved-production-alias", "parameter_identity_alias")),
    Mutation("harness-alias-helper-parameter-identity-multiline-call", lambda source: _harness_qualified_alias(source, "\ndef extract_multiline_identity(module):\n    return module.strict_chronology_id\nmultiline_parameter_identity_alias = extract_multiline_identity(\n    production_evidence,\n)\n"), architecture.Finding("harness-unresolved-production-alias", "multiline_parameter_identity_alias")),
    Mutation("harness-alias-helper-default-decoder", lambda source: _harness_qualified_alias(source, "\ndef extract_default_decoder(module=production_evidence):\n    return module._decode_calibration_candidate_pair_projection\ndefault_decoder_alias = extract_default_decoder()\n"), architecture.Finding("harness-unresolved-production-alias", "default_decoder_alias")),
    Mutation("harness-alias-helper-default-decoder-multiline-default", lambda source: _harness_qualified_alias(source, "\ndef extract_multiline_default_decoder(\n    module=production_evidence,\n):\n    return module._decode_calibration_candidate_pair_projection\nmultiline_default_decoder_alias = extract_multiline_default_decoder()\n"), architecture.Finding("harness-unresolved-production-alias", "multiline_default_decoder_alias")),
    Mutation("harness-alias-helper-two-hop-pass-through", lambda source: _harness_qualified_alias(source, "\ndef pass_production_module(module):\n    return module\ndef extract_passed_decoder(module):\n    return module._decode_strict_chronology_projection\npassed_production_module = pass_production_module(production_evidence)\npassed_decoder_alias = extract_passed_decoder(passed_production_module)\n"), architecture.Finding("harness-unresolved-production-alias", "passed_production_module")),
    Mutation("harness-alias-helper-parameter-mapper", lambda source: _harness_qualified_alias(source, "\ndef extract_mapper(module):\n    return module._calibration_candidate_pair_mapping\nparameter_mapper_alias = extract_mapper(production_evidence)\n"), architecture.Finding("harness-unresolved-production-alias", "parameter_mapper_alias")),
    Mutation("harness-alias-helper-attrgetter-substitution", lambda source: _harness_qualified_alias(source, "\nfrom operator import attrgetter as helper_attrgetter\ndef extract_member(module, member):\n    return helper_attrgetter(member)(module)\nattrgetter_alias = extract_member(production_evidence, '_strict_chronology_mapping')\n"), architecture.Finding("harness-unresolved-production-alias", "attrgetter_alias")),
    Mutation("harness-alias-helper-attrgetter-named-member", lambda source: _harness_qualified_alias(source, "\nfrom operator import attrgetter as helper_attrgetter\ndef extract_named_member(module, member):\n    return helper_attrgetter(member)(module)\nmember_name = 'strict_chronology_id'\nnamed_attrgetter_alias = extract_named_member(production_evidence, member_name)\n"), architecture.Finding("harness-unresolved-production-alias", "named_attrgetter_alias")),
    Mutation("harness-alias-helper-split-attrgetter", lambda source: _harness_qualified_alias(source, "\nfrom operator import attrgetter as helper_attrgetter\ndef extract_split_member(module, member):\n    getter = helper_attrgetter(member)\n    return getter(module)\nsplit_attrgetter_alias = extract_split_member(production_evidence, 'strict_chronology_id')\n"), architecture.Finding("harness-unresolved-production-alias", "split_attrgetter_alias")),
    Mutation("harness-alias-helper-module-attrgetter", lambda source: _harness_qualified_alias(source, "\nfrom operator import attrgetter as helper_attrgetter\nmodule_getter = helper_attrgetter('strict_chronology_id')\ndef extract_module_member(module):\n    return module_getter(module)\nmodule_attrgetter_alias = extract_module_member(production_evidence)\n"), architecture.Finding("harness-unresolved-production-alias", "module_attrgetter_alias")),
    Mutation("harness-alias-helper-function-alias", lambda source: _harness_qualified_alias(source, "\ndef extract_aliased_helper(module):\n    return module._strict_chronology_mapping\nextract_helper_alias = extract_aliased_helper\nfunction_alias_result = extract_helper_alias(production_evidence)\n"), architecture.Finding("harness-unresolved-production-alias", "function_alias_result")),
)
_HARNESS_BENIGN_ALIAS_CASES = (
    ("harness-benign-projection-class-imports", lambda source: source + f"\nfrom {architecture.CANONICAL_MODULE} import CalibrationCandidatePairProjection as FixturePairProjection, StrictChronologyProjection as FixtureChronologyProjection\nfrom research_decision_engine.benchmarks import broader_calibration_evidence as fixture_production_evidence\nQualifiedFixturePairProjection = fixture_production_evidence.CalibrationCandidatePairProjection\n"),
    ("harness-benign-exact-projection-instance", _append("\nfixture_pair_projection = CalibrationCandidatePairProjection(adam_candidate_id='adam', comparison_group_id='group', replication_id='1', schema_version='broader-replication-calibration-candidate-pair/v1', sgd_candidate_id='sgd', world_id='world')\n")),
    ("harness-benign-generic-protocol-hash", _append("\nindependent_fixture_identity = protocol_hash('fixture-expectation/v1', {'fixture': 'independent'})\n")),
    ("harness-benign-similar-local-helper", _append("\ndef local_strict_chronology_identity(value):\n    return ('fixture-only', value)\ndef import_module(label):\n    return label\ndef getattr(owner, name):\n    return (owner, name)\nlocal_identity_alias = local_strict_chronology_identity\nlocal_import_control = import_module('fixture.module')\nlocal_getattr_control = getattr(object(), 'fixture')\n")),
    ("harness-benign-local-holder-helper", _append("\nclass LocalIdentityHolder:\n    strict_chronology_id = object()\ndef extract_local_identity(module):\n    return module.strict_chronology_id\nlocal_holder_alias = extract_local_identity(LocalIdentityHolder)\n")),
    ("harness-benign-local-holder-attrgetter", _append("\nfrom operator import attrgetter as local_attrgetter\nclass LocalFixtureHolder:\n    fixture_value = object()\ndef extract_local_member(module, member):\n    return local_attrgetter(member)(module)\nlocal_member_alias = extract_local_member(LocalFixtureHolder, 'fixture_value')\n")),
    ("harness-benign-local-holder-split-attrgetter", _append("\nfrom operator import attrgetter as local_attrgetter\nclass LocalSplitHolder:\n    fixture_value = object()\ndef extract_local_split_member(module, member):\n    getter = local_attrgetter(member)\n    return getter(module)\nlocal_split_alias = extract_local_split_member(LocalSplitHolder, 'fixture_value')\n")),
)
_HARNESS_SUPPLEMENTARY_ALIAS_CASES = (
    Mutation("harness-alias-nested-function", lambda source: _harness_qualified_alias(source, "\ndef outer_alias_scope():\n    def nested_alias():\n        return production_evidence.strict_chronology_id\n    return nested_alias\n"), architecture.Finding("harness-forbidden-production-alias", "strict_chronology_id")),
    Mutation("harness-alias-statically-resolved-closure-return", lambda source: _harness_qualified_alias(source, "\ndef make_alias_closure(module):\n    def extract_alias():\n        return module._strict_chronology_mapping\n    return extract_alias\nclosure_factory = make_alias_closure(production_evidence)\nclosure_alias = closure_factory()\n"), architecture.Finding("harness-unresolved-production-alias", "closure_factory")),
)
_HARNESS_SUPPLEMENTARY_BENIGN_CONTROLS = (
    ("harness-benign-private-protocol-hash-alias", _append("\nfrom research_decision_engine.benchmarks.broader_protocol import protocol_hash as _fixture_protocol_hash\nprivate_fixture_identity = _fixture_protocol_hash('fixture-private/v1', {'fixture': 1})\n")),
    ("harness-benign-test-owned-ordered-mapping", _append("\nfixture_ordered_mapping = {'first': 'strict_chronology_id', 'second': '_strict_chronology_mapping'}\n")),
    ("harness-benign-symbol-name-strings", _append("\nfixture_symbol_names = 'calibration_candidate_pair_id strict_chronology_id'\n")),
    ("harness-benign-fixed-vector-constants", _append("\nfixture_identity_vectors = ('PAIR-FIXTURE-1', 'CHRONOLOGY-FIXTURE-1')\n")),
    ("harness-benign-unrelated-noop-helper", _append("\ndef _fixture_noop_helper():\n    return None\nfixture_noop_result = _fixture_noop_helper()\n")),
    ("harness-benign-projection-type-container", _append("\nfixture_projection_types = (CalibrationCandidatePairProjection, StrictChronologyProjection)\n")),
    ("harness-benign-multiline-local-helper-call", _append("\nclass MultilineLocalHolder:\n    fixture_value = object()\ndef extract_multiline_local(module):\n    return module.fixture_value\nmultiline_local_alias = extract_multiline_local(\n    MultilineLocalHolder,\n)\n")),
)
# fmt: on


# fmt: off
_POSSIBLE_MODULE_PREFIX = """from research_decision_engine.benchmarks import broader_calibration_evidence as production
class LocalAuditOwner:
    strict_chronology_id = object()
    _strict_chronology_mapping = object()
    _decode_strict_chronology_projection = object()
"""
_FORBIDDEN_IDENTITY = architecture.Finding("harness-forbidden-production-alias", "strict_chronology_id")

def _possible_source(body: str) -> str:
    return _POSSIBLE_MODULE_PREFIX + body

_POSSIBLE_PRODUCTION_JOIN_CASES = (
    LogicalCase("possible-production-helper-branch-join", _possible_source("def audit_owner(flag):\n    if flag:\n        owner = production\n    else:\n        owner = LocalAuditOwner()\n    return owner\nescaped = audit_owner(unknown_flag).strict_chronology_id\n"), frozenset({_FORBIDDEN_IDENTITY})),
    LogicalCase("possible-production-first-return-branch", _possible_source("def audit_owner(flag):\n    if flag:\n        return production\n    return LocalAuditOwner()\nescaped = audit_owner(unknown_flag).strict_chronology_id\n"), frozenset({_FORBIDDEN_IDENTITY})),
    LogicalCase("possible-production-second-return-branch", _possible_source("def audit_owner(flag):\n    if flag:\n        return LocalAuditOwner()\n    return production\nescaped = audit_owner(unknown_flag).strict_chronology_id\n"), frozenset({_FORBIDDEN_IDENTITY})),
    LogicalCase("possible-production-two-helper-hops", _possible_source("def inner_owner(flag):\n    return production if flag else LocalAuditOwner()\ndef middle_owner(flag):\n    return inner_owner(flag)\ndef outer_owner(flag):\n    return middle_owner(flag)\nescaped = outer_owner(unknown_flag).strict_chronology_id\n"), frozenset({_FORBIDDEN_IDENTITY})),
    LogicalCase("possible-production-nested-helper-return", _possible_source("def inner_owner(flag):\n    return production if flag else LocalAuditOwner()\ndef outer_owner(flag):\n    return inner_owner(flag)\nescaped = outer_owner(unknown_flag).strict_chronology_id\n"), frozenset({_FORBIDDEN_IDENTITY})),
)

_POSSIBLE_PRODUCTION_OTHER_CASES = (
    LogicalCase("possible-production-helper-local-module-alias", _possible_source("production_alias = production\ndef audit_owner(flag):\n    return production_alias if flag else LocalAuditOwner()\nescaped = audit_owner(unknown_flag).strict_chronology_id\n"), frozenset({_FORBIDDEN_IDENTITY})),
    LogicalCase("possible-production-conditional-expression", _possible_source("def audit_owner(flag):\n    return production if flag else LocalAuditOwner()\nescaped = audit_owner(unknown_flag).strict_chronology_id\n"), frozenset({_FORBIDDEN_IDENTITY})),
    LogicalCase("possible-production-closure-return", _possible_source("def outer_owner(flag):\n    def audit_owner():\n        return production if flag else LocalAuditOwner()\n    return audit_owner()\nescaped = outer_owner(unknown_flag).strict_chronology_id\n"), frozenset({_FORBIDDEN_IDENTITY})),
    LogicalCase("possible-production-forbidden-identity-attribute", _possible_source("def audit_owner(flag):\n    return production if flag else LocalAuditOwner()\nescaped = audit_owner(unknown_flag).strict_chronology_id\n"), frozenset({_FORBIDDEN_IDENTITY})),
    LogicalCase("possible-production-forbidden-mapper-attribute", _possible_source("def audit_owner(flag):\n    return production if flag else LocalAuditOwner()\nescaped = audit_owner(unknown_flag)._strict_chronology_mapping\n"), frozenset({architecture.Finding("harness-forbidden-production-alias", "_strict_chronology_mapping")})),
    LogicalCase("possible-production-forbidden-decoder-attribute", _possible_source("def audit_owner(flag):\n    return production if flag else LocalAuditOwner()\nescaped = audit_owner(unknown_flag)._decode_strict_chronology_projection\n"), frozenset({architecture.Finding("harness-forbidden-production-alias", "_decode_strict_chronology_projection")})),
    LogicalCase("possible-production-dynamic-attribute", _possible_source("def audit_owner(flag):\n    return production if flag else LocalAuditOwner()\nescaped = getattr(audit_owner(unknown_flag), dynamic_name)\n"), frozenset({architecture.Finding("harness-unresolved-production-alias", "getattr")})),
    LogicalCase("exact-production-dynamic-attribute", _possible_source("escaped = getattr(production, dynamic_name)\n"), frozenset({architecture.Finding("harness-unresolved-production-alias", "getattr")})),
    LogicalCase("dynamic-import-production-module", f"escaped = __import__({architecture.CANONICAL_MODULE!r})\n", frozenset({architecture.Finding("harness-unresolved-production-alias", "__import__")})),
    LogicalCase("production-module-bounded-tuple-retrieval", _possible_source("owners = (production, LocalAuditOwner())\nescaped = owners[unknown_index].strict_chronology_id\n"), frozenset({_FORBIDDEN_IDENTITY})),
    LogicalCase("possible-production-assigned-never-dereferenced", _possible_source("def audit_owner(flag):\n    return production if flag else LocalAuditOwner()\nescaped = audit_owner(unknown_flag)\n"), frozenset(), True),
    LogicalCase("unrelated-local-branch-join", """
class FirstLocal:
    strict_chronology_id = object()
class SecondLocal:
    strict_chronology_id = object()
def audit_owner(flag):
    return FirstLocal() if flag else SecondLocal()
escaped = getattr(audit_owner(unknown_flag), dynamic_name)
""", frozenset(), True),
    LogicalCase("exact-allowed-production-projection-class", _possible_source("escaped = production.CalibrationCandidatePairProjection\n"), frozenset(), True),
)

_UNRELATED_DYNAMIC_BENIGN_CASES = (
    LogicalCase("unrelated-dynamic-exact-local-instance", "class Local:\n    value = object()\nowner = Local()\nescaped = getattr(owner, dynamic_name)\n", frozenset(), True),
    LogicalCase("unrelated-dynamic-local-immutable-record", "from typing import NamedTuple\nclass LocalRecord(NamedTuple):\n    value: int\nowner = LocalRecord(1)\nescaped = getattr(owner, dynamic_name)\n", frozenset(), True),
    LogicalCase("unrelated-dynamic-two-local-return-types", "class FirstLocal:\n    pass\nclass SecondLocal:\n    pass\ndef owner(flag):\n    return FirstLocal() if flag else SecondLocal()\nescaped = getattr(owner(unknown_flag), dynamic_name)\n", frozenset(), True),
    LogicalCase("unrelated-dynamic-local-method-call", "class Local:\n    def method(self):\n        return None\nowner = Local()\nescaped = getattr(owner, dynamic_name)()\n", frozenset(), True),
    LogicalCase("unrelated-dynamic-callable-in-local-mapping", "def local_callable():\n    return None\ncallables = {'local': local_callable}\nescaped = callables[dynamic_key]()\n", frozenset(), True),
    LogicalCase("unrelated-local-function-forbidden-spelling", "def strict_chronology_id(value):\n    return value\nescaped = strict_chronology_id(None)\n", frozenset(), True),
    LogicalCase("unrelated-local-object-mapper-spelling", "class Local:\n    _strict_chronology_mapping = object()\nescaped = Local()._strict_chronology_mapping\n", frozenset(), True),
    LogicalCase("unrelated-nonproduction-module-object", "import importlib\nimport math as unrelated_module\nsafe_module = importlib.import_module(name='math')\nescaped = getattr(unrelated_module, dynamic_name)\n", frozenset(), True),
    LogicalCase("unrelated-unresolved-local-never-sensitive", "local_value = unresolved_local\nescaped = local_value\n", frozenset(), True),
)

_FAIL_CLOSED_PRODUCTION_DYNAMIC_CASES = (
    LogicalCase("fail-closed-exact-production-dynamic-getattr", _POSSIBLE_MODULE_PREFIX + "escaped = getattr(production, dynamic_name)\n", frozenset({architecture.Finding("harness-unresolved-production-alias", "getattr")})),
    LogicalCase("fail-closed-possible-production-dynamic-getattr", _POSSIBLE_MODULE_PREFIX + "def owner(flag):\n    return production if flag else LocalAuditOwner()\nescaped = getattr(owner(unknown_flag), dynamic_name)\ncalled = owner(unknown_flag)()\n", frozenset({architecture.Finding("harness-unresolved-production-alias", "getattr"), architecture.Finding("harness-unresolved-production-alias", "dynamic-call")})),
    LogicalCase("fail-closed-builtin-production-import", f"escaped = __import__({architecture.CANONICAL_MODULE!r})\n", frozenset({architecture.Finding("harness-unresolved-production-alias", "__import__")})),
    LogicalCase("fail-closed-importlib-production-import", f"import importlib\nescaped = importlib.import_module(name={architecture.CANONICAL_MODULE!r})\n", frozenset({architecture.Finding("harness-unresolved-production-alias", "import_module")})),
    LogicalCase("fail-closed-production-wildcard-import", f"from {architecture.CANONICAL_MODULE} import *\n", frozenset({architecture.Finding("harness-unresolved-production-alias", "star-import")})),
    LogicalCase("fail-closed-forbidden-helper-unknown-container-retrieval", f"from {architecture.CANONICAL_MODULE} import strict_chronology_id as forbidden\ndef local(value):\n    return value\nhelpers = (forbidden, local)\nescaped = helpers[unknown_index]\n", frozenset({_FORBIDDEN_IDENTITY})),
    LogicalCase("fail-closed-forbidden-helper-branch-return", f"from {architecture.CANONICAL_MODULE} import strict_chronology_id as forbidden\ndef local(value):\n    return value\ndef choose(flag):\n    return forbidden if flag else local\nescaped = choose(unknown_flag)\n", frozenset({_FORBIDDEN_IDENTITY})),
    LogicalCase("fail-closed-forbidden-helper-closure-return", f"from {architecture.CANONICAL_MODULE} import strict_chronology_id as forbidden\ndef local(value):\n    return value\ndef outer(flag):\n    def choose():\n        return forbidden if flag else local\n    return choose()\nescaped = outer(unknown_flag)\n", frozenset({_FORBIDDEN_IDENTITY})),
    LogicalCase("fail-closed-forbidden-helper-mixed-callable-sequence", f"from {architecture.CANONICAL_MODULE} import strict_chronology_id as forbidden\ndef local(value):\n    return value\nhelpers = (forbidden, local)\nescaped = helpers[unknown_index](None)\n", frozenset({_FORBIDDEN_IDENTITY})),
)

_UNRELATED_REFLECTION_CASES = (
    LogicalCase("unrelated-reflection-local-class-dict", "class Local:\n    value = 1\nnamespace = Local.__dict__\n", frozenset(), True),
    LogicalCase("unrelated-reflection-local-instance-class-dict", "class Local:\n    value = 1\nlocal_instance = Local()\nnamespace = local_instance.__class__.__dict__\n", frozenset(), True),
    LogicalCase("unrelated-reflection-math-dict", "import math\nnamespace = math.__dict__\n", frozenset(), True),
    LogicalCase("unrelated-reflection-json-dict", "import json\nnamespace = json.__dict__\n", frozenset(), True),
    LogicalCase("unrelated-reflection-local-function-globals", "def local_function():\n    return None\nnamespace = local_function.__globals__\n", frozenset(), True),
    LogicalCase("unrelated-reflection-local-method-globals", "class Local:\n    def method(self):\n        return None\nnamespace = Local.method.__globals__\n", frozenset(), True),
    LogicalCase("unrelated-reflection-vars-local-class", "class Local:\n    value = 1\nnamespace = vars(Local)\n", frozenset(), True),
    LogicalCase("unrelated-reflection-vars-local-instance", "class Local:\n    value = 1\nlocal_instance = Local()\nnamespace = vars(local_instance)\n", frozenset(), True),
    LogicalCase("unrelated-reflection-getattr-local-class", "class Local:\n    value = 1\nescaped = getattr(Local, dynamic_name)\n", frozenset(), True),
    LogicalCase("unrelated-reflection-getattr-math", "import math\nescaped = getattr(math, dynamic_name)\n", frozenset(), True),
    LogicalCase("unrelated-reflection-hasattr-local-instance", "class Local:\n    value = 1\nlocal_instance = Local()\nescaped = hasattr(local_instance, dynamic_name)\n", frozenset(), True),
    LogicalCase("unrelated-reflection-helper-local-alternatives", "class First:\n    pass\nclass Second:\n    pass\ndef owner(flag):\n    return First if flag else Second\nnamespace = vars(owner(unknown_flag))\n", frozenset(), True),
    LogicalCase("unrelated-reflection-dynamic-local-callable", "def local_callable():\n    return None\ncallables = {'local': local_callable}\nescaped = callables[dynamic_key]()\n", frozenset(), True),
    LogicalCase("unrelated-reflection-unresolved-local", "local_value = unresolved_local\nescaped = getattr(local_value, dynamic_name)\n", frozenset(), True),
)

_PRODUCTION_REFLECTION_CASES = (
    LogicalCase("production-reflection-module-dict", _POSSIBLE_MODULE_PREFIX + "namespace = production.__dict__\n", frozenset({architecture.Finding("harness-unresolved-production-alias", "dynamic-namespace")})),
    LogicalCase("production-reflection-possible-module-dict", _POSSIBLE_MODULE_PREFIX + "def owner(flag):\n    return production if flag else LocalAuditOwner\nnamespace = owner(unknown_flag).__dict__\n", frozenset({architecture.Finding("harness-unresolved-production-alias", "dynamic-namespace")})),
    LogicalCase("production-reflection-helper-globals", f"from {architecture.CANONICAL_MODULE} import strict_chronology_id as helper\nnamespace = helper.__globals__\n", frozenset({_FORBIDDEN_IDENTITY})),
    LogicalCase("production-reflection-possible-helper-globals", f"from {architecture.CANONICAL_MODULE} import strict_chronology_id as helper\ndef local(value):\n    return value\ndef owner(flag):\n    return helper if flag else local\nnamespace = owner(unknown_flag).__globals__\n", frozenset({_FORBIDDEN_IDENTITY})),
    LogicalCase("production-reflection-vars-module", _POSSIBLE_MODULE_PREFIX + "namespace = vars(production)\n", frozenset({architecture.Finding("harness-unresolved-production-alias", "vars")})),
    LogicalCase("production-reflection-getattr-module", _POSSIBLE_MODULE_PREFIX + "escaped = getattr(production, dynamic_name)\n", frozenset({architecture.Finding("harness-unresolved-production-alias", "getattr")})),
    LogicalCase("production-reflection-getattr-possible-module", _POSSIBLE_MODULE_PREFIX + "def owner(flag):\n    return production if flag else LocalAuditOwner\nescaped = getattr(owner(unknown_flag), dynamic_name)\n", frozenset({architecture.Finding("harness-unresolved-production-alias", "getattr")})),
    LogicalCase("production-reflection-hasattr-module", _POSSIBLE_MODULE_PREFIX + "escaped = hasattr(production, dynamic_name)\n", frozenset({architecture.Finding("harness-unresolved-production-alias", "hasattr")})),
    *_FAIL_CLOSED_PRODUCTION_DYNAMIC_CASES[2:],
)

def _overflow_source(width: int, *, prefix: str = "", suffix: str = "") -> str:
    return prefix + "class Local:\n    value = 1\n" + "".join(f"local_{index:03d} = Local.value\n" for index in range(width)) + suffix

_OVERFLOW_CASES = (
    LogicalCase("overflow-unrelated-300-bindings", _overflow_source(300), frozenset(), True),
    LogicalCase("overflow-unrelated-600-bindings", _overflow_source(600), frozenset(), True),
    LogicalCase("overflow-unrelated-600-with-reflection", _overflow_source(600, suffix="namespace = Local.__dict__\n"), frozenset(), True),
    LogicalCase("overflow-unrelated-600-with-allowed-projection", _overflow_source(600, prefix=f"from {architecture.CANONICAL_MODULE} import CalibrationCandidatePairProjection\n", suffix="FixtureProjection = CalibrationCandidatePairProjection\n"), frozenset(), True),
    LogicalCase("overflow-sensitive-600-with-forbidden-helper", _overflow_source(600, prefix=f"from {architecture.CANONICAL_MODULE} import strict_chronology_id as forbidden\n"), frozenset({_FORBIDDEN_IDENTITY, architecture.Finding("harness-unresolved-production-alias", "span-correlation-limit")})),
    LogicalCase("overflow-sensitive-600-with-possible-module", _overflow_source(600, prefix="from research_decision_engine.benchmarks import broader_calibration_evidence as production\n", suffix="def owner(flag):\n    return production if flag else Local\npossible_owner = owner(unknown_flag)\n"), frozenset({architecture.Finding("harness-unresolved-production-alias", "span-correlation-limit")})),
    LogicalCase("overflow-sensitive-600-with-container", _overflow_source(600, prefix=f"from {architecture.CANONICAL_MODULE} import strict_chronology_id as forbidden\n", suffix="helpers = (forbidden, Local.value)\nescaped = helpers[unknown_index]\n"), frozenset({_FORBIDDEN_IDENTITY, architecture.Finding("harness-unresolved-production-alias", "span-correlation-limit")})),
    LogicalCase("overflow-sensitive-after-helper-return", _overflow_source(600, prefix="from research_decision_engine.benchmarks import broader_calibration_evidence as production\n", suffix="def owner(flag):\n    return production if flag else Local\nescaped = owner(unknown_flag)\n"), frozenset({architecture.Finding("harness-unresolved-production-alias", "span-correlation-limit")})),
    LogicalCase("overflow-unrelated-600-with-math", _overflow_source(600, prefix="import math\n", suffix="unrelated_module = math\n"), frozenset(), True),
)
# fmt: on


def _mutate_guard_function_reference(
    source: str,
    function_name: str,
    old: str,
    new: str,
) -> str:
    block = _guard_source_function_block(source, function_name)
    assert block.count(old) == 1
    return source.replace(block, block.replace(old, new, 1), 1)


def _replace_guard_once(source: str, old: str, new: str) -> str:
    assert old in source
    return source.replace(old, new, 1)


def _remove_guard_forbidden_inventory_member(source: str) -> str:
    start = source.index("_HARNESS_FORBIDDEN_PRODUCTION_TARGETS =")
    end = source.index("# fmt: on", start)
    block = source[start:end]
    member = '        "_decode_strict_chronology_projection",\n'
    assert block.count(member) == 1
    return source[:start] + block.replace(member, "", 1) + source[end:]


# fmt: off
def _guard_origin_policy_rows(tree: ast.Module) -> dict[str, tuple[bool, bool]] | None:
    assignments = tuple(node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign)) and any(
        isinstance(target, ast.Name) and target.id == "_ORIGIN_CLASS_POLICIES"
        for target in (tuple(node.targets) if isinstance(node, ast.Assign) else (node.target,))
    ))
    if len(assignments) != 1:
        return None
    value = assignments[0].value
    if not isinstance(value, ast.Call) or ast.unparse(value.func) != "MappingProxyType" or len(value.args) != 1 or value.keywords or not isinstance(value.args[0], ast.Dict):
        return None
    rows: dict[str, tuple[bool, bool]] = {}
    for key, policy in zip(value.args[0].keys, value.args[0].values, strict=True):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str) or not isinstance(policy, ast.Call) or ast.unparse(policy.func) != "OriginClassPolicy" or len(policy.args) != 2 or policy.keywords or not all(
            isinstance(argument, ast.Constant) and type(argument.value) is bool for argument in policy.args
        ):
            return None
        rows[key.value] = cast(tuple[bool, bool], tuple(cast(ast.Constant, argument).value for argument in policy.args))
    return rows


def _guard_wire_schema_fields(tree: ast.Module) -> tuple[str, ...] | None:
    assignments = tuple(node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign)) and any(
        isinstance(target, ast.Name) and target.id == "_PROJECTED_PROVENANCE_WIRE_FIELDS"
        for target in (tuple(node.targets) if isinstance(node, ast.Assign) else (node.target,))
    ))
    if len(assignments) != 1 or not isinstance(assignments[0].value, ast.Tuple):
        return None
    values = assignments[0].value.elts
    if not all(isinstance(value, ast.Constant) and type(value.value) is str for value in values):
        return None
    return tuple(cast(str, cast(ast.Constant, value).value) for value in values)


def _guard_source_function_block(source: str, name: str) -> str:
    start = source.index(f"def {name}(")
    ends = tuple(index for marker in ("\ndef ", "\nclass ") if (index := source.find(marker, start + 1)) >= 0)
    return source[start : min(ends, default=len(source))]


def _retention_reachability_maintenance_findings(source: str, tree: ast.Module | None = None, functions: dict[str, str] | None = None) -> tuple[architecture.Finding, ...]:
    focused = tree is None
    if focused:
        policy_tree = ast.parse(source[source.index("class OriginClassPolicy(NamedTuple):") : source.index("class ProjectedProvenance(NamedTuple):")])
        names = (
            "_retain_projected_origin",
            "_production_reachable_origin",
            "_projected_provenance_is_consistent",
            "_canonical_production_origin_findings",
            "_encoded_projected_provenance",
            "_canonical_production_origins",
        )
        functions = {name: _guard_source_function_block(source, name) for name in names}
    else:
        policy_tree = cast(ast.Module, tree)
    if functions is None:
        lines = source.splitlines(keepends=True)
        functions = {node.name: "".join(lines[node.lineno - 1 : node.end_lineno or node.lineno]) for node in cast(ast.Module, tree).body if isinstance(node, ast.FunctionDef)}
    rows = _guard_origin_policy_rows(policy_tree)
    retention = functions.get("_retain_projected_origin", "")
    reachability = functions.get("_production_reachable_origin", "")
    consistency = functions.get("_projected_provenance_is_consistent", "")
    projector = functions.get("_canonical_production_origin_findings", "")
    encoder = functions.get("_encoded_projected_provenance", "")
    decoder = functions.get("_canonical_production_origins", "")
    selector_start = projector.find("    def has_retained_authority_origin(")
    selector = projector[selector_start : projector.find("\n    facts:", selector_start)] if selector_start >= 0 else ""
    assignment_names = set() if focused else {
        target.id
        for node in cast(ast.Module, tree).body
        for target in (tuple(node.targets) if isinstance(node, ast.Assign) else (node.target,) if isinstance(node, ast.AnnAssign) else ())
        if isinstance(target, ast.Name)
    }
    details: set[str] = set()
    if source.count("class OriginClassPolicy(NamedTuple):") != 1 or source.count("_ORIGIN_CLASS_POLICIES: Final = MappingProxyType(") != 1:
        details.add("origin-policy-authority")
    if rows is None or "allowed-production-projection-class" not in rows:
        details.add("origin-policy-authority")
    else:
        if rows["allowed-production-projection-class"][0] is not True:
            details.add("allowed-projection-retention")
        if rows["allowed-production-projection-class"][1] is not False:
            details.add("allowed-projection-reachability")
    if ".retain_fact is True" not in retention or ".production_reachable" in retention or "_retain_projected_origin(classified)" not in selector or ".production_reachable" in selector or "_production_reachable_origin(" in selector:
        details.add("retention-reachability-separation")
    if ".production_reachable is True" not in reachability or ".retain_fact" in reachability:
        details.add("origin-policy-consumption")
    if "_projected_provenance_is_consistent(fact)" not in encoder or "_projected_provenance_is_consistent(fact)" not in decoder or "type(fact.production_reachable) is not bool" not in consistency or 'fact.certainty != "limited"' not in consistency or 'return fact.limit_class == "none"' not in consistency:
        details.add("fact-consistency-validation")
    if 'fact.limit_class == "unrelated"' not in consistency or "return fact.production_reachable is False" not in consistency:
        details.add("unrelated-limit-consistency")
    if 'fact.limit_class == "production-sensitive"' not in consistency or "return fact.production_reachable is True" not in consistency:
        details.add("sensitive-limit-consistency")
    if '"allowed-production-projection-class"' in consistency:
        details.add("allowed-direct-consistency")
    if "fact._replace(" in decoder or "bool(fact.production_reachable)" in decoder:
        details.add("contradiction-normalization")
    if "production_reachable = bool(reachable_origins)" not in projector or "and not retained_origins" in projector:
        details.add("join-sensitive-preservation")
    if "production_reachable = bool(retained_origins)" in projector:
        details.add("join-unrelated-stability")
    if "_RETAINED_ORIGIN_CLASSES =" in source or any(
        name != "_ORIGIN_CLASS_POLICIES" and "origin" in name.lower() and "retain" in name.lower()
        for name in assignment_names
    ):
        details.add("second-retention-authority")
    if "_SENSITIVE_ORIGIN_CLASSES =" in source or any(
        name != "_ORIGIN_CLASS_POLICIES"
        and "origin" in name.lower()
        and ("reachable" in name.lower() or "sensitive" in name.lower())
        for name in assignment_names
    ):
        details.add("second-sensitivity-authority")
    if "fact.origin_class !=" in decoder or "or fact.origin_class ==" in decoder:
        details.add("origin-consistency-bypass")
    return tuple(architecture.Finding("guard-maintainability", detail) for detail in sorted(details))


def _codec_maintenance_findings(
    source: str,
    tree: ast.Module | None = None,
    functions: dict[str, ast.FunctionDef] | None = None,
) -> tuple[architecture.Finding, ...]:
    tree = ast.parse(source) if tree is None else tree
    functions = (
        {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        if functions is None
        else functions
    )
    lines = source.splitlines(keepends=True)
    blocks = {name: "".join(lines[node.lineno - 1 : node.end_lineno or node.lineno]) for name, node in functions.items()}
    decoder_node = functions.get("_canonical_production_origins")
    encoder_node = functions.get("_encoded_projected_provenance")
    decoder = blocks.get("_canonical_production_origins", "")
    encoder = blocks.get("_encoded_projected_provenance", "")
    consistency = blocks.get("_projected_provenance_is_consistent", "")
    qualified_origin = blocks.get("_projected_qualified_origin_is_valid", "")
    details: set[str] = set()
    expected_fields = ("col_offset", "node_kind", "certainty", "relation", "origin_class", "production_reachable", "limit_class", "qualified_origin")
    if _guard_wire_schema_fields(tree) != expected_fields:
        details.add("codec-wire-schema-authority")
    schema_names = {
        target.id
        for node in tree.body
        for target in (tuple(node.targets) if isinstance(node, ast.Assign) else (node.target,) if isinstance(node, ast.AnnAssign) else ())
        if isinstance(target, ast.Name)
        and "PROJECTED_PROVENANCE" in target.id
        and "WIRE" in target.id
        and ("FIELD" in target.id or "SCHEMA" in target.id)
    }
    if schema_names != {"_PROJECTED_PROVENANCE_WIRE_FIELDS"}:
        details.add("codec-second-wire-schema")
    split_calls = [] if decoder_node is None else [
        node for node in ast.walk(decoder_node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "split"
    ]
    decoder_nodes = tuple(ast.walk(decoder_node)) if decoder_node is not None else ()
    exact_type_lines = [] if decoder_node is None else [
        node.lineno for node in ast.walk(decoder_node)
        if isinstance(node, ast.Compare) and ast.unparse(node) == "type(symbol) is not str"
    ]
    if len(split_calls) != 1 or len(exact_type_lines) != 1 or exact_type_lines[0] >= (split_calls[0].lineno if split_calls else 0):
        details.add("codec-exact-string-type")
    if len(split_calls) != 1 or len(split_calls[0].args) != 1 or split_calls[0].keywords:
        details.add("codec-split-maxsplit")
    if "len(parts) != len(_PROJECTED_PROVENANCE_WIRE_FIELDS)" not in decoder:
        details.add("codec-exact-arity")
    if any(isinstance(node, ast.AugAssign) and "parts" in ast.unparse(node) or isinstance(node, ast.Subscript) and ".split(" in ast.unparse(node) for node in decoder_nodes) or ".extend(" in decoder:
        details.add("codec-arity-normalization")
    constructor = decoder.find("fact = ProjectedProvenance(")
    wire_validation = decoder.find("_projected_provenance_wire_fields_are_valid(fields)")
    consistency_validation = decoder.find("if not _projected_provenance_is_consistent(fact):")
    if min(constructor, wire_validation) < 0 or wire_validation > constructor:
        details.add("codec-field-validation-order")
    if constructor < 0 or consistency_validation < constructor or "if False" in decoder:
        details.add("codec-consistency-validation")
    if not encoder_node or not encoder_node.body or not isinstance(encoder_node.body[0], ast.If) or "_projected_provenance_is_consistent(fact)" not in ast.unparse(encoder_node.body[0].test):
        details.add("codec-encoder-prevalidation")
    origin_validation = consistency.find("fact.origin_class not in _PROJECTED_ORIGIN_CLASSES")
    policy_lookup = consistency.find("_origin_class_policy(")
    if origin_validation < 0:
        details.add("codec-closed-origin")
    if policy_lookup < 0 or origin_validation < 0 or policy_lookup < origin_validation:
        details.add("codec-policy-before-validation")
    if "_ORIGIN_CLASS_POLICIES.get(" in consistency:
        details.add("codec-origin-default")
    if "_PROJECTED_PROVENANCE_WIRE_SEPARATOR in value" not in qualified_origin:
        details.add("codec-qualified-origin-delimiter")
    if source.count("def _malformed_projected_provenance(") != 1 or "_malformed_projected_provenance(lineno)" not in encoder or "_malformed_projected_provenance(" not in decoder:
        details.add("codec-fail-closed-authority")
    codec_functions = tuple(node for name, node in functions.items() if name in {"_encoded_projected_provenance", "_canonical_production_origins"} or "codec" in name)
    if any(isinstance(node, ast.Try) and node.handlers for function in codec_functions for node in ast.walk(function)):
        details.add("codec-broad-exception")
    if "fact._replace(" in decoder or "bool(fact.production_reachable)" in decoder:
        details.add("contradiction-normalization")
    if "_CURRENT_COMMIT" in source or "git rev-parse" in source or "ebd1591c7332544c8f991a34ef3936f2e048ca16" in source:
        details.add("codec-source-exemption")
    return tuple(architecture.Finding("guard-maintainability", detail) for detail in sorted(details))


def _guard_maintenance_findings(source: str) -> tuple[architecture.Finding, ...]:
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    lines = source.splitlines(keepends=True)
    blocks = {name: "".join(lines[node.lineno - 1 : node.end_lineno or node.lineno]) for name, node in functions.items()}
    details = {
        finding.detail
        for finding in _retention_reachability_maintenance_findings(
            source,
            tree,
            blocks,
        )
    }
    details.update(
        finding.detail
        for finding in _codec_maintenance_findings(source, tree, functions)
    )
    schedule = "\n".join(block for name, block in blocks.items() if "p1" in name and ("schedule" in name or "entry" in name))
    details.update(detail for detail, present in (
        ("schedule-statement-count", "len(validator.body)" in schedule),
        ("schedule-fixed-offset", "validator.body[" in schedule),
        ("neutral-helper-classification", "_p1_neutral_helper_reason(" not in blocks.get("_p1_neutral_statement_reason", "")),
        ("module-lru-cache", "lru_cache" in source),
    ) if present)
    persistent_analyzers: set[str] = set()
    for node in tree.body:
        targets = tuple(node.targets) if isinstance(node, ast.Assign) else (node.target,) if isinstance(node, ast.AnnAssign) else ()
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        names = {target.id for target in targets if isinstance(target, ast.Name)}
        if any(("cache" in name.lower() or "session" in name.lower()) and isinstance(value, (ast.Dict, ast.List, ast.Set)) for name in names):
            details.add("module-mutable-cache")
        if isinstance(value, ast.Call) and ast.unparse(value.func) == "_AnalysisSession":
            details.add("persistent-analysis-session")
            persistent_analyzers.update(names)
    harness = "\n".join(block for name, block in blocks.items() if "harness" in name)
    inventory_start = source.index("_HARNESS_FORBIDDEN_PRODUCTION_TARGETS =")
    inventory = source[inventory_start : source.index("# fmt: on", inventory_start)]
    adapter = blocks.get("_harness_unresolved_local_aliases", "")
    projector = blocks.get("_canonical_production_origin_findings", "")
    decoder = blocks.get("_canonical_production_origins", "")
    classifier = blocks.get("_harness_provenance_attributions", "")
    sensitivity = blocks.get("_production_sensitive_provenance", "")
    neutral = blocks.get("_p1_inert_literal", "")
    neutral_width_names = {target.id for node in tree.body for target in (tuple(node.targets) if isinstance(node, ast.Assign) else (node.target,) if isinstance(node, ast.AnnAssign) else ()) if isinstance(target, ast.Name) and "neutral" in target.id.lower() and ("width" in target.id.lower() or "bound" in target.id.lower())}
    persistent_analyzer_helper = bool(persistent_analyzers) and any(isinstance(node, ast.Return) and (isinstance(node.value, ast.Name) and node.value.id in persistent_analyzers or isinstance(node.value, ast.Call) and ast.unparse(node.value.func) == "_AnalysisSession") for function in functions.values() for node in ast.walk(function))
    analyzer_classes = tuple(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_OwnedQualifiedSymbolAnalyzer")
    direct_analyzers = tuple(node for node in ast.walk(tree) if isinstance(node, ast.Call) and ast.unparse(node.func) == "qualified._QualifiedSymbolAnalyzer")
    source_analyzer = functions.get("_source_analysis")
    analyzer_constructions = () if source_analyzer is None else tuple(node for node in ast.walk(source_analyzer) if isinstance(node, ast.Call) and ast.unparse(node.func) == "analyzer_type")
    single_canonical_analyzer = len(analyzer_classes) == len(analyzer_constructions) == 1 and tuple(map(ast.unparse, analyzer_classes[0].bases)) == ("qualified._QualifiedSymbolAnalyzer",) and not direct_analyzers
    session_classes = tuple(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_AnalysisSession")
    source_methods = () if len(session_classes) != 1 else tuple(node for node in session_classes[0].body if isinstance(node, ast.FunctionDef) and node.name == "source_analysis")
    session_source_calls = () if len(source_methods) != 1 else tuple(node for node in ast.walk(source_methods[0]) if isinstance(node, ast.Call) and ast.unparse(node.func) == "_source_analysis")
    invocation_local_analysis = len(session_source_calls) == 1 and all(blocks.get(name, "").count("_AnalysisSession(") == 1 for name in ("_active_p1_internal_findings", "future_source_findings", "harness_findings", "repository_findings"))
    details.update(detail for detail, present in (
        ("persistent-analyzer-helper", persistent_analyzer_helper),
        ("duplicate-assignment-propagation", "range(len(assignments)" in harness or "range(len(functions)" in harness),
        ("duplicate-helper-return-propagation", any("helper_alias_targets" in name or "helper_return" in name for name in functions if "harness" in name)),
        ("unbounded-value-provenance", "_harness_value_provenance(child)" in harness and "ast.iter_child_nodes" in harness),
        ("forbidden-inventory", any(name not in inventory for name in ("calibration_candidate_pair_id", "strict_chronology_id", "_calibration_candidate_pair_mapping", "_strict_chronology_mapping", "_decode_calibration_candidate_pair_projection", "_decode_strict_chronology_projection"))),
        ("unresolved-provenance", ".sensitive_unresolved" not in adapter),
        ("source-fingerprint", "\nimport hashlib\n" in source or "hashlib.sha256(source" in source),
        ("analysis-session-ownership", not invocation_local_analysis),
        ("canonical-direct-origins", "for origin in value.direct_origins" not in projector),
        ("first-origin-only", "[:1]" in projector),
        ("second-origin-only", "[-1:]" in projector or "[1:2]" in projector),
        ("helper-return-origin", "or isinstance(node, ast.Call)" in projector),
        ("possible-origin-certainty", 'else "possible"' not in projector or "len(value.direct_origins) == 1" not in projector or '"|possible|" in finding.symbol' in decoder),
        ("canonical-flow-authority", "analyzer.flow_node_values.get(id(node))" not in projector),
        ("second-provenance-analyzer", not single_canonical_analyzer or any("module_provenance_analyzer" in name or "helper_return_provenance" in name for name in functions)),
        ("unrelated-dynamic-conversion", 'dynamic_finding.code == "dynamic-call"' in harness),
        ("production-dynamic-gate", "for fact in callable_facts\n                if _production_sensitive_provenance(fact)" not in classifier),
        ("possible-dynamic-fail-closed", "if not reflection_facts:" not in classifier),
        ("second-dynamic-classifier", any(name.startswith("_harness_dynamic") and name != "_harness_provenance_attributions" for name in functions)),
        ("projected-provenance-schema", source.count("class ProjectedProvenance(NamedTuple):") != 1 or any(field not in source[source.index("class ProjectedProvenance(NamedTuple):"):source.index("def _production_sensitive_provenance")] for field in ("certainty:", "relation:", "origin_class:", "production_reachable:", "limit_class:", "qualified_origin:"))),
        ("allowed-projection-origin", 'return "allowed-production-projection-class"' not in projector),
        ("local-unresolved-distinction", projector.count('"unresolved-local"') < 3),
        ("no-fact-production-promotion", "if not facts:" in classifier),
        ("namespace-production-gate", "and receiver_facts:" not in classifier),
        ("dict-production-gate", 'node.attr == "__dict__" or' in classifier),
        ("globals-production-gate", 'node.attr == "__globals__" or' in classifier),
        ("receiver-production-gate", "if False and node.attr" in classifier),
        ("limit-sensitivity-policy", 'production_reachable,\n            "production-sensitive",' in projector),
        ("sensitive-limit-preservation", 'production_reachable,\n            "unrelated",' in projector),
        ("overflow-production-monotonicity", "if False" in projector),
        ("production-sensitivity-authority", source.count("def _production_sensitive_provenance(") != 1 or "_production_reachable_origin(fact.origin_class)" not in sensitivity),
        ("second-reflection-classifier", any("reflection_classifier" in name for name in functions)),
        ("second-overflow-classifier", any("overflow_classifier" in name for name in functions)),
        ("neutral-canonical-width", "qualified._MAX_ABSTRACT_CONTAINER_WIDTH" not in neutral),
        ("neutral-bounded-width", "len(node.elts) <=" not in neutral),
        ("neutral-immutable-only", "isinstance(node, ast.Tuple)" not in neutral or "ast.List" in neutral),
        ("neutral-narrow-bound", "<= 32" in neutral),
        ("second-neutral-width-authority", bool(neutral_width_names)),
    ) if present)
    return tuple(architecture.Finding("guard-maintainability", detail) for detail in sorted(details))

def _owned_dataflow_maintenance_findings(source: str) -> tuple[architecture.Finding, ...]:
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    bindings = {target.id: node for node in tree.body for target in (tuple(node.targets) if isinstance(node, ast.Assign) else (node.target,) if isinstance(node, ast.AnnAssign) else ()) if isinstance(target, ast.Name)}
    details: set[str] = set()
    expected_slots = ("key_fields", "projection_oracle_key", "selector_oracle_key", "paired_oracle_key", "revealed_observation", "projection_outcome_digest", "selector_outcome_digest")
    operation_binding = bindings.get("P2OwnedOperations")
    operation_value = operation_binding.value if isinstance(operation_binding, (ast.Assign, ast.AnnAssign)) else None
    operation_rows = operation_value.args[1].elts if isinstance(operation_value, ast.Call) and len(operation_value.args) == 2 and isinstance(operation_value.args[1], ast.List) else ()
    fields = tuple(row.elts[0].value for row in operation_rows if isinstance(row, ast.Tuple) and len(row.elts) == 2 and isinstance(row.elts[0], ast.Constant) and type(row.elts[0].value) is str)
    details.update(f"missing-{slot.replace('_', '-')}" for slot in expected_slots if slot not in fields)
    manifest = bindings.get("OWNED_OPERATION_MANIFEST")
    manifest_value = manifest.value if isinstance(manifest, (ast.Assign, ast.AnnAssign)) else None
    if fields != expected_slots or not isinstance(manifest_value, ast.Call) or ast.unparse(manifest_value.func) != "OwnedDataflowManifest": details.add("closed-operation-inventory")  # noqa: E701
    items = functions.get("_owned_operation_items")
    item_returns = () if items is None else tuple(node for node in ast.walk(items) if isinstance(node, ast.Return))
    if len(item_returns) != 1 or isinstance(item_returns[0].value, ast.Subscript): details.add("all-occurrences-required")  # noqa: E701
    checker = functions.get("_p2_owned_dataflow_findings")
    checker_text = "" if checker is None else ast.unparse(checker)
    checker_calls = set() if checker is None else {ast.unparse(node.func) for node in ast.walk(checker) if isinstance(node, ast.Call)}
    checker_attributes = set() if checker is None else {ast.unparse(node) for node in ast.walk(checker) if isinstance(node, ast.Attribute)}
    checker_names = set() if checker is None else {node.id for node in ast.walk(checker) if isinstance(node, ast.Name)}
    comparison_loops = () if checker is None else tuple(node for node in ast.walk(checker) if isinstance(node, ast.For) and ast.unparse(node.iter) == "facts.owned_expressions" and any(isinstance(candidate, ast.Compare) for candidate in ast.walk(node)))
    if checker is None or len(comparison_loops) != 1 or not {"facts.owned_controls", "facts.owned_expressions"} <= checker_attributes or not {"carrier_marker", "producer_marker"} <= checker_names: details.add("no-presence-only-fallback")  # noqa: E701
    if "left.markers & all_producer_markers" not in checker_text: details.add("reject-self-comparison")  # noqa: E701
    if "right.markers & all_carrier_markers" not in checker_text: details.add("reject-carried-to-carried")  # noqa: E701
    if not {"left.unresolved", "right.unresolved"} <= checker_attributes: details.add("unresolved-fails-closed")  # noqa: E701
    if "ast.parse" in checker_calls: details.add("no-parse-per-operation")  # noqa: E701
    if checker_calls & {"_source_analysis", "_qualified_analysis"}: details.add("no-analysis-per-operation")  # noqa: E701
    if "ast.walk" in checker_calls: details.add("canonical-expression-index")  # noqa: E701
    if checker is not None and any(isinstance(node, ast.Compare) and any(isinstance(item, ast.Attribute) and item.attr == "source_text" for item in ast.walk(node)) for node in ast.walk(checker)): details.add("no-source-fingerprint")  # noqa: E701
    if any("OWNERSHIP" in name and name != "OWNED_OPERATION_MANIFEST" for name in bindings): details.add("single-ownership-table")  # noqa: E701
    if any("DATAFLOW" in name and "TABLE" in name for name in bindings): details.add("single-dataflow-table")  # noqa: E701
    if any(("OWNED" in name or "DATAFLOW" in name) and "CACHE" in name for name in bindings): details.add("no-module-result-cache")  # noqa: E701
    return tuple(architecture.Finding("guard-owned-dataflow-maintainability", detail) for detail in sorted(details))
def _mutate_owned_checker_terms(source: str, specs: tuple[tuple[str, str], ...]) -> str:
    for old, new in specs: source = _mutate_guard_function_reference(source, "_p2_owned_dataflow_findings", old, new)  # noqa: E701
    return source
def _limit_owned_operation_items(source: str) -> str: return _mutate_guard_function_reference(source, "_owned_operation_items", "return tuple(zip(OWNED_OPERATION_MANIFEST.operations._fields, OWNED_OPERATION_MANIFEST.operations, strict=True))", "return tuple(zip(OWNED_OPERATION_MANIFEST.operations._fields, OWNED_OPERATION_MANIFEST.operations, strict=True))[:1]")
def _insert_owned_operation_statement(source: str, statement: str) -> str: return _mutate_guard_function_reference(source, "_p2_owned_dataflow_findings", "    for slot, edge in _owned_operation_items():\n        detail", f"    for slot, edge in _owned_operation_items():\n        {statement}\n        detail")
_OWNED_DATAFLOW_MAINTENANCE_CASES = (
    Mutation("guard-owned-presence-only-fallback", lambda source: _mutate_guard_function_reference(source, "_p2_owned_dataflow_findings", "for expression in facts.owned_expressions:", "for expression in ():"), architecture.Finding("guard-owned-dataflow-maintainability", "no-presence-only-fallback")),
    Mutation("guard-owned-accept-self-comparison", lambda source: _mutate_owned_checker_terms(source, (("carrier_marker not in left.markers", "False"), ("left.markers & all_producer_markers", "False"))), architecture.Finding("guard-owned-dataflow-maintainability", "reject-self-comparison")),
    Mutation("guard-owned-accept-carried-to-carried", lambda source: _mutate_owned_checker_terms(source, (("producer_marker not in right.markers", "False"), ("right.markers & all_carrier_markers", "False"))), architecture.Finding("guard-owned-dataflow-maintainability", "reject-carried-to-carried")),
    Mutation("guard-owned-require-only-one-occurrence", _limit_owned_operation_items, architecture.Finding("guard-owned-dataflow-maintainability", "all-occurrences-required")),
    Mutation("guard-owned-skip-selector-key-occurrence", lambda source: _replace_guard_once(source, '("selector_oracle_key", OwnedEdge), ', ""), architecture.Finding("guard-owned-dataflow-maintainability", "missing-selector-oracle-key")),
    Mutation("guard-owned-skip-paired-key-occurrence", lambda source: _replace_guard_once(source, '("paired_oracle_key", OwnedEdge), ', ""), architecture.Finding("guard-owned-dataflow-maintainability", "missing-paired-oracle-key")),
    Mutation("guard-owned-skip-projection-digest-occurrence", lambda source: _replace_guard_once(source, '("projection_outcome_digest", OwnedEdge), ', ""), architecture.Finding("guard-owned-dataflow-maintainability", "missing-projection-outcome-digest")),
    Mutation("guard-owned-skip-revealed-observation", lambda source: _replace_guard_once(source, '("revealed_observation", OwnedEdge), ', ""), architecture.Finding("guard-owned-dataflow-maintainability", "missing-revealed-observation")),
    Mutation("guard-owned-add-second-ownership-table", lambda source: source + "\n_SECOND_P2_OWNERSHIP_TABLE = ()\n", architecture.Finding("guard-owned-dataflow-maintainability", "single-ownership-table")),
    Mutation("guard-owned-add-second-dataflow-table", lambda source: source + "\n_SECOND_P2_DATAFLOW_TABLE = ()\n", architecture.Finding("guard-owned-dataflow-maintainability", "single-dataflow-table")),
    Mutation("guard-owned-parse-once-per-manifest-row", lambda source: _insert_owned_operation_statement(source, "ast.parse(facts.analysis.source_text)"), architecture.Finding("guard-owned-dataflow-maintainability", "no-parse-per-operation")),
    Mutation("guard-owned-analyze-once-per-operation", lambda source: _insert_owned_operation_statement(source, "_source_analysis(facts.analysis.source_text, module_name=CANONICAL_MODULE)"), architecture.Finding("guard-owned-dataflow-maintainability", "no-analysis-per-operation")),
    Mutation("guard-owned-add-module-result-cache", lambda source: source + "\n_OWNED_DATAFLOW_RESULT_CACHE = {}\n", architecture.Finding("guard-owned-dataflow-maintainability", "no-module-result-cache")),
    Mutation("guard-owned-special-case-source-hash", lambda source: _insert_p2_statement(source, "_p2_owned_dataflow_findings", "if hash(facts.analysis.source_text) == 0:\n    return set()"), architecture.Finding("guard-owned-dataflow-maintainability", "no-source-fingerprint")),
    Mutation("guard-owned-accept-unresolved-sensitive-flow", lambda source: _mutate_owned_checker_terms(source, (("left.unresolved", "False"), ("right.unresolved", "False"))), architecture.Finding("guard-owned-dataflow-maintainability", "unresolved-fails-closed")),
    Mutation("guard-owned-bypass-canonical-expression-index", lambda source: _mutate_guard_function_reference(source, "_p2_owned_dataflow_findings", "for expression in facts.owned_expressions:", "for expression in (facts.owned_expressions if slot != 'key_fields' else tuple(node for node in ast.walk(facts.tree) if isinstance(node, ast.expr))):"), architecture.Finding("guard-owned-dataflow-maintainability", "canonical-expression-index")),
)

_GUARD_MAINTENANCE_CASES = (
    Mutation("guard-restore-exact-entry-body-length", lambda source: source + "\ndef _p1_schedule_exact_entry_length(validator):\n    return len(validator.body) == 18\n", architecture.Finding("guard-maintainability", "schedule-statement-count")),
    Mutation("guard-restore-fixed-entry-offset", lambda source: source + "\ndef _p1_schedule_fixed_entry_offset(validator):\n    return validator.body[4]\n", architecture.Finding("guard-maintainability", "schedule-fixed-offset")),
    Mutation("guard-reject-every-inter-family-helper", lambda source: _mutate_guard_function_reference(source, "_p1_neutral_statement_reason", "_p1_neutral_helper_reason(", "_p1_reject_every_helper("), architecture.Finding("guard-maintainability", "neutral-helper-classification")),
    Mutation("guard-add-module-lru-cache", lambda source: source + "\nfrom functools import lru_cache\n@lru_cache(maxsize=1)\ndef _cached_guard(source):\n    return source\n", architecture.Finding("guard-maintainability", "module-lru-cache")),
    Mutation("guard-add-module-dict-cache", lambda source: source + "\n_analysis_cache = {}\n", architecture.Finding("guard-maintainability", "module-mutable-cache")),
    Mutation("guard-add-persistent-analysis-singleton", lambda source: source + "\n_ANALYSIS_SESSION = _AnalysisSession()\n", architecture.Finding("guard-maintainability", "persistent-analysis-session")),
    Mutation("guard-restore-assignment-propagation-loop", lambda source: source + "\ndef _harness_assignment_propagation(assignments):\n    for _ in range(len(assignments) + 1):\n        pass\n", architecture.Finding("guard-maintainability", "duplicate-assignment-propagation")),
    Mutation("guard-restore-helper-return-scanner", lambda source: source + "\ndef _harness_helper_return_scanner(tree):\n    return tuple(node for node in ast.walk(tree) if isinstance(node, ast.Return))\n", architecture.Finding("guard-maintainability", "duplicate-helper-return-propagation")),
    Mutation("guard-add-unbounded-recursive-value-scan", lambda source: source + "\ndef _harness_value_provenance(node):\n    return tuple(_harness_value_provenance(child) for child in ast.iter_child_nodes(node))\n", architecture.Finding("guard-maintainability", "unbounded-value-provenance")),
    Mutation("guard-bypass-one-forbidden-symbol", _remove_guard_forbidden_inventory_member, architecture.Finding("guard-maintainability", "forbidden-inventory")),
    Mutation("guard-special-case-current-source-hash", lambda source: source + "\nimport hashlib\ndef _guard_source_fingerprint(source):\n    return hashlib.sha256(source.encode()).hexdigest()\n", architecture.Finding("guard-maintainability", "source-fingerprint")),
    Mutation("guard-ignore-unresolved-sensitive-provenance", lambda source: _mutate_guard_function_reference(source, "_harness_unresolved_local_aliases", "call.sensitive_unresolved", "call.dynamic"), architecture.Finding("guard-maintainability", "unresolved-provenance")),
)

_PROVENANCE_BOUND_GUARD_MUTATIONS = (
    Mutation("guard-drop-production-module-branch-origins", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origin_findings", "for origin in value.direct_origins", "for origin in frozenset()"), architecture.Finding("guard-maintainability", "canonical-direct-origins")),
    Mutation("guard-keep-only-first-branch-origin", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origin_findings", "for origin in value.direct_origins", "for origin in tuple(sorted(value.direct_origins))[:1]"), architecture.Finding("guard-maintainability", "first-origin-only")),
    Mutation("guard-keep-only-second-branch-origin", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origin_findings", "for origin in value.direct_origins", "for origin in tuple(sorted(value.direct_origins))[-1:]"), architecture.Finding("guard-maintainability", "second-origin-only")),
    Mutation("guard-drop-module-origin-at-helper-return", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origin_findings", "if not isinstance(node, ast.expr):", "if not isinstance(node, ast.expr) or isinstance(node, ast.Call):"), architecture.Finding("guard-maintainability", "helper-return-origin")),
    Mutation("guard-treat-possible-production-as-unrelated-unknown", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origins", "if finding.code != _CANONICAL_PRODUCTION_ORIGIN_CODE:", 'if finding.code != _CANONICAL_PRODUCTION_ORIGIN_CODE or "|possible|" in finding.symbol:'), architecture.Finding("guard-maintainability", "possible-origin-certainty")),
    Mutation("guard-convert-every-dynamic-call-to-production-alias", lambda source: _mutate_guard_function_reference(source, "harness_findings", '    identity_helpers = {"calibration_candidate_pair_id", "strict_chronology_id"}\n', '    for dynamic_finding in analysis.findings:\n        if dynamic_finding.code == "dynamic-call":\n            findings.add(Finding("harness-unresolved-production-alias", dynamic_finding.symbol))\n    identity_helpers = {"calibration_candidate_pair_id", "strict_chronology_id"}\n'), architecture.Finding("guard-maintainability", "unrelated-dynamic-conversion")),
    Mutation("guard-ignore-dynamic-call-production-provenance", lambda source: _mutate_guard_function_reference(source, "_harness_provenance_attributions", "for fact in callable_facts\n                if _production_sensitive_provenance(fact)", "for fact in callable_facts\n                if False"), architecture.Finding("guard-maintainability", "production-dynamic-gate")),
    Mutation("guard-accept-dynamic-getattr-on-possible-production", lambda source: _mutate_guard_function_reference(source, "_harness_provenance_attributions", "if not reflection_facts:", "if True:"), architecture.Finding("guard-maintainability", "possible-dynamic-fail-closed")),
    Mutation("guard-hard-code-neutral-width-32", lambda source: _mutate_guard_function_reference(source, "_p1_inert_literal", "qualified._MAX_ABSTRACT_CONTAINER_WIDTH", "32"), architecture.Finding("guard-maintainability", "neutral-canonical-width")),
    Mutation("guard-use-second-neutral-width-constant", lambda source: _mutate_guard_function_reference(source, "_p1_inert_literal", "qualified._MAX_ABSTRACT_CONTAINER_WIDTH", "_P1_NEUTRAL_WIDTH") + "\n_P1_NEUTRAL_WIDTH = 256\n", architecture.Finding("guard-maintainability", "second-neutral-width-authority")),
    Mutation("guard-make-neutral-width-unbounded", lambda source: _mutate_guard_function_reference(source, "_p1_inert_literal", "and len(node.elts) <= qualified._MAX_ABSTRACT_CONTAINER_WIDTH", "and True"), architecture.Finding("guard-maintainability", "neutral-bounded-width")),
    Mutation("guard-accept-mutable-list-as-inert", lambda source: _mutate_guard_function_reference(source, "_p1_inert_literal", "isinstance(node, ast.Tuple)", "isinstance(node, (ast.Tuple, ast.List))"), architecture.Finding("guard-maintainability", "neutral-immutable-only")),
    Mutation("guard-bypass-canonical-flow-for-module-origins", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origin_findings", "analyzer.flow_node_values.get(id(node))", "qualified.ResolvedValue()"), architecture.Finding("guard-maintainability", "canonical-flow-authority")),
    Mutation("guard-add-second-module-provenance-analyzer", lambda source: source + "\ndef _harness_module_provenance_analyzer(source):\n    return qualified._QualifiedSymbolAnalyzer(source, HARNESS_MODULE).analysis()\n", architecture.Finding("guard-maintainability", "second-provenance-analyzer")),
    Mutation("guard-add-second-dynamic-call-classifier", lambda source: source + "\ndef _harness_dynamic_call_classifier(analysis):\n    return tuple(item for item in analysis.findings if item.code == 'dynamic-call')\n", architecture.Finding("guard-maintainability", "second-dynamic-classifier")),
)

_PROVENANCE_CLASSIFICATION_MUTATIONS = (
    Mutation("guard-collapse-allowed-projection-into-production", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origin_findings", 'return "allowed-production-projection-class"', 'return "canonical-production-module"'), architecture.Finding("guard-maintainability", "allowed-projection-origin")),
    Mutation("guard-drop-allowed-projection-facts", lambda source: _replace_guard_once(source, '"allowed-production-projection-class": OriginClassPolicy(True, False)', '"allowed-production-projection-class": OriginClassPolicy(False, False)'), architecture.Finding("guard-maintainability", "allowed-projection-retention")),
    Mutation("guard-collapse-unrelated-and-unresolved-local", lambda source: _replace_guard_once(source, 'else "unresolved-local"', 'else "unrelated-local"'), architecture.Finding("guard-maintainability", "local-unresolved-distinction")),
    Mutation("guard-promote-every-no-fact-site", lambda source: _mutate_guard_function_reference(source, "_harness_provenance_attributions", "facts = _canonical_production_origins(analysis)", 'facts = _canonical_production_origins(analysis)\n    if not facts:\n        return (HarnessProvenanceAttribution(Finding("harness-unresolved-production-alias", "no-fact"), 1, CANONICAL_MODULE, "possible", "analysis:no-fact"),)'), architecture.Finding("guard-maintainability", "no-fact-production-promotion")),
    Mutation("guard-promote-every-namespace-attribute", lambda source: _mutate_guard_function_reference(source, "_harness_provenance_attributions", "if node.attr in qualified._DYNAMIC_NAMESPACE_ATTRIBUTES and receiver_facts:", "if node.attr in qualified._DYNAMIC_NAMESPACE_ATTRIBUTES:"), architecture.Finding("guard-maintainability", "namespace-production-gate")),
    Mutation("guard-promote-every-dict-attribute", lambda source: _mutate_guard_function_reference(source, "_harness_provenance_attributions", "if node.attr in qualified._DYNAMIC_NAMESPACE_ATTRIBUTES and receiver_facts:", 'if node.attr == "__dict__" or (node.attr in qualified._DYNAMIC_NAMESPACE_ATTRIBUTES and receiver_facts):'), architecture.Finding("guard-maintainability", "dict-production-gate")),
    Mutation("guard-promote-every-globals-attribute", lambda source: _mutate_guard_function_reference(source, "_harness_provenance_attributions", "if node.attr in qualified._DYNAMIC_NAMESPACE_ATTRIBUTES and receiver_facts:", 'if node.attr == "__globals__" or (node.attr in qualified._DYNAMIC_NAMESPACE_ATTRIBUTES and receiver_facts):'), architecture.Finding("guard-maintainability", "globals-production-gate")),
    Mutation("guard-promote-every-dynamic-call", lambda source: _mutate_guard_function_reference(source, "harness_findings", '    identity_helpers = {"calibration_candidate_pair_id", "strict_chronology_id"}\n', '    for dynamic_finding in analysis.findings:\n        if dynamic_finding.code == "dynamic-call":\n            findings.add(Finding("harness-unresolved-production-alias", dynamic_finding.symbol))\n    identity_helpers = {"calibration_candidate_pair_id", "strict_chronology_id"}\n'), architecture.Finding("guard-maintainability", "unrelated-dynamic-conversion")),
    Mutation("guard-ignore-production-receiver-at-namespace", lambda source: _mutate_guard_function_reference(source, "_harness_provenance_attributions", "if node.attr in qualified._DYNAMIC_NAMESPACE_ATTRIBUTES and receiver_facts:", "if False and node.attr in qualified._DYNAMIC_NAMESPACE_ATTRIBUTES and receiver_facts:"), architecture.Finding("guard-maintainability", "receiver-production-gate")),
    Mutation("guard-convert-every-limit-to-sensitive", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origin_findings", '            production_reachable,\n            "production-sensitive" if production_reachable else "unrelated",', '            production_reachable,\n            "production-sensitive",'), architecture.Finding("guard-maintainability", "limit-sensitivity-policy")),
    Mutation("guard-convert-sensitive-limit-to-unrelated", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origin_findings", '            production_reachable,\n            "production-sensitive" if production_reachable else "unrelated",', '            production_reachable,\n            "unrelated",'), architecture.Finding("guard-maintainability", "sensitive-limit-preservation")),
    Mutation("guard-drop-production-sensitivity-on-overflow", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origin_findings", "fact.production_reachable is True", "False"), architecture.Finding("guard-maintainability", "overflow-production-monotonicity")),
    Mutation("guard-add-second-reflection-classifier", lambda source: source + "\ndef _harness_reflection_classifier(tree):\n    return tuple(node for node in ast.walk(tree) if isinstance(node, ast.Attribute))\n", architecture.Finding("guard-maintainability", "second-reflection-classifier")),
    Mutation("guard-add-second-overflow-classifier", lambda source: source + "\ndef _harness_overflow_classifier(tree):\n    return len(tree.body) > qualified._MAX_ABSTRACT_STRUCTURE_NODES\n", architecture.Finding("guard-maintainability", "second-overflow-classifier")),
    Mutation("guard-bypass-canonical-facts-for-one-helper", _remove_guard_forbidden_inventory_member, architecture.Finding("guard-maintainability", "forbidden-inventory")),
    Mutation("guard-special-case-committed-source", lambda source: source + "\nimport hashlib\ndef _guard_source_fingerprint(source):\n    return hashlib.sha256(source.encode()).hexdigest()\n", architecture.Finding("guard-maintainability", "source-fingerprint")),
)

_RETENTION_REACHABILITY_GUARD_MUTATIONS = (
    Mutation("guard-add-allowed-projection-to-sensitive-policy", lambda source: _replace_guard_once(source, '"allowed-production-projection-class": OriginClassPolicy(True, False)', '"allowed-production-projection-class": OriginClassPolicy(True, True)'), architecture.Finding("guard-maintainability", "allowed-projection-reachability")),
    Mutation("guard-use-reachability-for-retention", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origin_findings", "_retain_projected_origin(classified) and classified not in", "_production_reachable_origin(classified) and classified not in"), architecture.Finding("guard-maintainability", "retention-reachability-separation")),
    Mutation("guard-use-retention-for-reachability", lambda source: _mutate_guard_function_reference(source, "_production_reachable_origin", ".production_reachable is True", ".retain_fact is True"), architecture.Finding("guard-maintainability", "origin-policy-consumption")),
    Mutation("guard-accept-unrelated-reachable-limit", lambda source: _mutate_guard_function_reference(source, "_projected_provenance_is_consistent", "return fact.production_reachable is False", "return True"), architecture.Finding("guard-maintainability", "unrelated-limit-consistency")),
    Mutation("guard-accept-sensitive-unreachable-limit", lambda source: _mutate_guard_function_reference(source, "_projected_provenance_is_consistent", "return fact.production_reachable is True", "return True"), architecture.Finding("guard-maintainability", "sensitive-limit-consistency")),
    Mutation("guard-accept-reachable-allowed-projection", lambda source: _mutate_guard_function_reference(source, "_projected_provenance_is_consistent", "    if type(fact.production_reachable) is not bool:", '    if fact.origin_class == "allowed-production-projection-class":\n        return True\n    if type(fact.production_reachable) is not bool:'), architecture.Finding("guard-maintainability", "allowed-direct-consistency")),
    Mutation("guard-normalize-contradictory-provenance", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origins", "        if not _projected_provenance_is_consistent(fact):", "        fact = fact._replace(production_reachable=bool(fact.production_reachable))\n        if not _projected_provenance_is_consistent(fact):"), architecture.Finding("guard-maintainability", "contradiction-normalization")),
    Mutation("guard-drop-sensitive-allowed-production-join", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origin_findings", "        production_reachable = bool(reachable_origins)\n        if value.reachability_overflow:", "        production_reachable = bool(reachable_origins) and not retained_origins\n        if value.reachability_overflow:"), architecture.Finding("guard-maintainability", "join-sensitive-preservation")),
    Mutation("guard-promote-allowed-local-join", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origin_findings", "        production_reachable = bool(reachable_origins)\n        if value.reachability_overflow:", "        production_reachable = bool(retained_origins)\n        if value.reachability_overflow:"), architecture.Finding("guard-maintainability", "join-unrelated-stability")),
    Mutation("guard-add-second-retention-policy-table", lambda source: source + '\n_RETAINED_ORIGIN_CLASSES = frozenset({"allowed-production-projection-class"})\n', architecture.Finding("guard-maintainability", "second-retention-authority")),
    Mutation("guard-add-second-sensitivity-policy-table", lambda source: source + '\n_SENSITIVE_ORIGIN_CLASSES = frozenset({"canonical-production-module"})\n', architecture.Finding("guard-maintainability", "second-sensitivity-authority")),
    Mutation("guard-bypass-consistency-for-one-origin", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origins", "        if not _projected_provenance_is_consistent(fact):", '        if fact.origin_class != "unrelated-local" and not _projected_provenance_is_consistent(fact):'), architecture.Finding("guard-maintainability", "origin-consistency-bypass")),
)

_CODEC_GUARD_MUTATIONS = (
    Mutation("codec-restore-split-seven", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origins", "parts = symbol.split(_PROJECTED_PROVENANCE_WIRE_SEPARATOR)", "parts = symbol.split(_PROJECTED_PROVENANCE_WIRE_SEPARATOR, 7)"), architecture.Finding("guard-maintainability", "codec-split-maxsplit")),
    Mutation("codec-use-derived-maxsplit", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origins", "parts = symbol.split(_PROJECTED_PROVENANCE_WIRE_SEPARATOR)", "parts = symbol.split(_PROJECTED_PROVENANCE_WIRE_SEPARATOR, len(_PROJECTED_PROVENANCE_WIRE_FIELDS) - 1)"), architecture.Finding("guard-maintainability", "codec-split-maxsplit")),
    Mutation("codec-use-isinstance-string", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origins", "if type(symbol) is not str:", "if not isinstance(symbol, str):"), architecture.Finding("guard-maintainability", "codec-exact-string-type")),
    Mutation("codec-split-before-exact-type", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origins", "        if type(symbol) is not str:\n            return fail_closed(finding.lineno)\n        parts = symbol.split(_PROJECTED_PROVENANCE_WIRE_SEPARATOR)", "        parts = symbol.split(_PROJECTED_PROVENANCE_WIRE_SEPARATOR)\n        if type(symbol) is not str:\n            return fail_closed(finding.lineno)"), architecture.Finding("guard-maintainability", "codec-exact-string-type")),
    Mutation("codec-truncate-extra-fields", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origins", "parts = symbol.split(_PROJECTED_PROVENANCE_WIRE_SEPARATOR)", "parts = symbol.split(_PROJECTED_PROVENANCE_WIRE_SEPARATOR)[:len(_PROJECTED_PROVENANCE_WIRE_FIELDS)]"), architecture.Finding("guard-maintainability", "codec-arity-normalization")),
    Mutation("codec-pad-missing-fields", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origins", "        parts = symbol.split(_PROJECTED_PROVENANCE_WIRE_SEPARATOR)\n", "        parts = symbol.split(_PROJECTED_PROVENANCE_WIRE_SEPARATOR)\n        parts += [\"\"] * (len(_PROJECTED_PROVENANCE_WIRE_FIELDS) - len(parts))\n"), architecture.Finding("guard-maintainability", "codec-arity-normalization")),
    Mutation("codec-ignore-unknown-origin", lambda source: _mutate_guard_function_reference(source, "_projected_provenance_is_consistent", "if type(fact.origin_class) is not str or fact.origin_class not in _PROJECTED_ORIGIN_CLASSES:", "if type(fact.origin_class) is not str:"), architecture.Finding("guard-maintainability", "codec-closed-origin")),
    Mutation("codec-default-unknown-origin-local", lambda source: _mutate_guard_function_reference(source, "_projected_provenance_is_consistent", "_origin_class_policy(\n        fact.origin_class\n    )", "_ORIGIN_CLASS_POLICIES.get(\n        fact.origin_class, OriginClassPolicy(True, False)\n    )"), architecture.Finding("guard-maintainability", "codec-origin-default")),
    Mutation("codec-index-policy-before-validation", lambda source: _mutate_guard_function_reference(source, "_projected_provenance_is_consistent", "    if type(fact) is not ProjectedProvenance:", "    _origin_class_policy(fact.origin_class)\n    if type(fact) is not ProjectedProvenance:"), architecture.Finding("guard-maintainability", "codec-policy-before-validation")),
    Mutation("codec-catch-keyerror-as-allowed", lambda source: source + "\ndef _codec_keyerror_fallback(fact):\n    try:\n        return _origin_class_policy(fact.origin_class)\n    except KeyError:\n        return ProjectedProvenance(1, 0, 'Name', 'exact', 'direct', 'allowed-production-projection-class', False, 'none', CANONICAL_MODULE)\n", architecture.Finding("guard-maintainability", "codec-broad-exception")),
    Mutation("codec-bypass-decoder-consistency", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origins", "if not _projected_provenance_is_consistent(fact):", "if False and not _projected_provenance_is_consistent(fact):"), architecture.Finding("guard-maintainability", "codec-consistency-validation")),
    Mutation("codec-accept-qualified-delimiter", lambda source: _mutate_guard_function_reference(source, "_projected_qualified_origin_is_valid", "if _PROJECTED_PROVENANCE_WIRE_SEPARATOR in value:", "if False:"), architecture.Finding("guard-maintainability", "codec-qualified-origin-delimiter")),
    Mutation("codec-normalize-contradictory-fact", lambda source: _mutate_guard_function_reference(source, "_canonical_production_origins", "        if not _projected_provenance_is_consistent(fact):", "        fact = fact._replace(production_reachable=bool(fact.production_reachable))\n        if not _projected_provenance_is_consistent(fact):"), architecture.Finding("guard-maintainability", "contradiction-normalization")),
    Mutation("codec-add-decoder-field-table", lambda source: source + "\n_PROJECTED_PROVENANCE_DECODER_WIRE_FIELDS = _PROJECTED_PROVENANCE_WIRE_FIELDS\n", architecture.Finding("guard-maintainability", "codec-second-wire-schema")),
    Mutation("codec-add-encoder-field-table", lambda source: source + "\n_PROJECTED_PROVENANCE_ENCODER_WIRE_FIELDS = _PROJECTED_PROVENANCE_WIRE_FIELDS\n", architecture.Finding("guard-maintainability", "codec-second-wire-schema")),
    Mutation("codec-special-case-current-commit", lambda source: source + "\n_CURRENT_COMMIT = 'ebd1591c7332544c8f991a34ef3936f2e048ca16'\n", architecture.Finding("guard-maintainability", "codec-source-exemption")),
)
# fmt: on


# fmt: off
_FOCUSED_P2_PROJECTION_SOURCE = '@_dataclass(frozen=True, slots=True)\nclass CalibrationSourceObservationProjection:\n    candidate_id: str\n    comparison_group_id: str\n    digest: str\n    intervention_arm: _Literal["adam", "sgd"]\n    key_fields: tuple[str, ...]\n    namespace: _Literal["rde.broader.calibration-outcome/v1"]\n    oracle_key_id: str\n    outcome_digest: str\n    replication_id: str\n    revealed_observation: str\n    schema_version: _Literal["broader-replication-calibration-source-observation/v1"]\n    seed: int\n    serialized_key_hex: str\n    u: str\n    world_id: str\n    z: str\n\n    def __post_init__(self) -> None:\n        _calibration_source_observation_mapping(self)\n'
_FOCUSED_P2_IDENTITY_SOURCE = 'def _calibration_source_observation_mapping(projection):\n    return projection\n\ndef _decode_calibration_source_observation_projection(mapping):\n    return mapping\n\ndef _source_observation_preimage(\n    projection: CalibrationSourceObservationProjection,\n) -> dict[str, object]:\n    mapping = _calibration_source_observation_mapping(projection)\n    decoded = _decode_calibration_source_observation_projection(mapping)\n    if decoded != projection:\n        _reject("source_observation", "projection does not exactly reconstruct")\n    return mapping\n\ndef source_observation_identity(\n    projection: CalibrationSourceObservationProjection,\n) -> str:\n    return _protocol_hash(\n        "validation_evidence_calibration_source_observation/v1",\n        _source_observation_preimage(projection),\n    )\n'
_FOCUSED_P2_SCHEDULE_SOURCE = 'def _validate_stage2f_p2(\n    *,\n    selections,\n    expected_execution_attestation_pairs,\n    attested_execution_specification_ids,\n    p2_selections,\n    expected_predecessors,\n):\n    p1_failure, p1_counts = _validate_stage2f_p1(\n        selections=selections,\n        expected_execution_attestation_pairs=expected_execution_attestation_pairs,\n        attested_execution_specification_ids=attested_execution_specification_ids,\n    )\n    count_0 = 0\n    for index in range(_CANONICAL_SELECTION_COUNT):\n        count_0 += 1\n        if failure := _predicate_3o_2_0(\n            selections[index], p2_selections[index], expected_predecessors[index]\n        ):\n            return failure\n    count_1 = 0\n    for index in range(_CANONICAL_SELECTION_COUNT):\n        count_1 += 1\n        if failure := _predicate_3o_2_1(\n            selections[index], p2_selections[index]\n        ):\n            return failure\n    count_2 = 0\n    for index in range(_CANONICAL_SELECTION_COUNT):\n        count_2 += 1\n        if failure := _predicate_3o_3_1(\n            selections[index], p2_selections[index], expected_predecessors[index]\n        ):\n            return failure\n    count_3 = 0\n    for index in range(_CANONICAL_SELECTION_COUNT):\n        count_3 += 1\n        if failure := _predicate_3o_4_1(\n            selections[index], p2_selections[index], expected_predecessors[index]\n        ):\n            return failure\n    return None\n'
_FOCUSED_P2_SCHEDULE_SOURCE = _FOCUSED_P2_SCHEDULE_SOURCE.replace("            return failure", "            return _p2_outcome(failure, 0, index, p1_counts, (count_0, 0, 0, 0))", 1).replace("            return failure", "            return _p2_outcome(failure, 1, index, p1_counts, (count_0, count_1, 0, 0))", 1).replace("            return failure", "            return _p2_outcome(failure, 2, index, p1_counts, (count_0, count_1, count_2, 0))", 1).replace("            return failure", "            return _p2_outcome(failure, 3, index, p1_counts, (count_0, count_1, count_2, count_3))", 1).replace("    count_0 = 0", "    if p1_failure is not None:\n        return p1_failure, (*p1_counts, 0, 0, 0, 0)\n    if type(p2_selections) is not tuple or len(p2_selections) != _CANONICAL_SELECTION_COUNT or type(expected_predecessors) is not tuple or len(expected_predecessors) != _CANONICAL_SELECTION_COUNT:\n        return _p2_outcome(_oracle_binding_failure('canonical P2 selection or Oracle predecessor count is not exactly 318'), 0, 0, p1_counts, (0, 0, 0, 0))\n    count_0 = 0").replace("    return None\n", "    return None, (*p1_counts, count_0, count_1, count_2, count_3)\n", 1) + "\ndef _predicate_3o_2_0(selection, p2_selection, expected_predecessor): return None\ndef _predicate_3o_2_1(selection, p2_selection): return None\ndef _predicate_3o_3_1(selection, p2_selection, expected_predecessor): return None\ndef _predicate_3o_4_1(selection, p2_selection, expected_predecessor): return None\n"
_FOCUSED_P2_PURE_HELPER_SOURCE = 'def _focused_required_pure_helpers(value):\n    _parse_calibration_candidate(value)\n    _calibration_key(value)\n    _transform_key(value)\n    _f64(value)\n    _hidden_arm_mean(value)\n    _hidden_observation_sigma(value)\n'
_FOCUSED_P2_FAILURE_SOURCE = '_P2_PREDICATE_PATHS = (\n    "calibration/3o.2.0/oracle_binding",\n    "calibration/3o.2.1/oracle_key",\n    "calibration/3o.3.1/outcome",\n    "calibration/3o.4.1/source_observation",\n)\n\ndef _oracle_binding_failure(detail):\n    return "CALIBRATION_ORACLE_BINDING_MISMATCH", detail\n\ndef _oracle_key_failure(detail):\n    return "CALIBRATION_ORACLE_KEY_ID_MISMATCH", detail\n\ndef _outcome_failure(detail):\n    return "CALIBRATION_OUTCOME_DIGEST_MISMATCH", detail\n\ndef _source_observation_failure(detail):\n    return "CALIBRATION_SOURCE_OBSERVATION_ID_MISMATCH", detail\n'
_FOCUSED_P2_PERFORMANCE_SOURCE = 'def _calibration_source_observation_mapping(projection):\n    return projection\n\ndef _decode_calibration_source_observation_projection(mapping):\n    return mapping\n\ndef _source_observation_preimage(\n    projection: CalibrationSourceObservationProjection,\n) -> dict[str, object]:\n    mapping = _calibration_source_observation_mapping(projection)\n    decoded = _decode_calibration_source_observation_projection(mapping)\n    if decoded != projection:\n        _reject("source_observation", "projection does not exactly reconstruct")\n    return mapping\n\ndef source_observation_identity(\n    projection: CalibrationSourceObservationProjection,\n) -> str:\n    return _protocol_hash(\n        "validation_evidence_calibration_source_observation/v1",\n        _source_observation_preimage(projection),\n    )\n\ndef _validate_complete_source_observation_surface(\n    value: object,\n) -> dict[str, object]:\n    projection = _require_exact_source_observation_object(value)\n    mapping = _calibration_source_observation_mapping(projection)\n    decoded = _decode_calibration_source_observation_projection(mapping)\n    if decoded != projection:\n        _reject("source_observation", "projection does not exactly reconstruct")\n    return mapping\n'
def _focused_p1_schedule_source() -> str:
    source = _historical_p1_source(); tree = ast.parse(source); functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}  # noqa: E702
    reachable = {"_predicate_3o_1_5", "_predicate_3o_1_6"}
    while True:
        before = frozenset(reachable)
        reachable.update(call.func.id for name in before for call in ast.walk(functions[name]) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in functions)
        if reachable == set(before): break  # noqa: E701
    parts = ["from typing import Final as _Final", "_CANONICAL_SELECTION_COUNT: _Final = 318", *(f"def _predicate_3o_1_{index}(*args): return None" for index in range(5)), *(ast.get_source_segment(source, node) for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in reachable), "def _outcome(*args): return args", ast.get_source_segment(source, functions["_validate_stage2f_p1"])]
    assert all(part is not None for part in parts)
    return "\n\n".join(cast(str, part) for part in parts) + "\n"
_FOCUSED_P1_SCHEDULE_SOURCE = _focused_p1_schedule_source()
_P1_FOCUSED_MANIFEST_CASE_IDS = frozenset({"active-p1-extra-class", "active-p1-missing-class", "active-p1-class-alias", "active-p1-identity-alias", "active-p1-wrong-schema", "active-p1-wrong-domain", "active-p1-extra-identity", "active-p1-public-validator", "active-p1-premature-p2-surface", "active-p1-live-helper-import-call", "active-p1-reader-persistence-evidence-surface", "active-p1-dynamic-export", "active-p1-second-hash-algebra", "active-p1-raw-sha-replaced-by-framed-hash", "active-p1-p2-p3-p4-leakage"})
def _focused_p1_schedule_findings(source: str) -> set[architecture.Finding]: facts = architecture._AnalysisSession().source_analysis(source, module_name=architecture.CANONICAL_MODULE); return architecture._active_p1_schedule_findings(facts.tree, facts.analysis)  # noqa: E702
_FOCUSED_P2_OWNED_SOURCE = '@_dataclass(frozen=True, slots=True)\nclass CalibrationSourceObservationProjection:\n    candidate_id: str\n    comparison_group_id: str\n    digest: str\n    intervention_arm: _Literal["adam", "sgd"]\n    key_fields: tuple[str, ...]\n    namespace: _Literal["rde.broader.calibration-outcome/v1"]\n    oracle_key_id: str\n    outcome_digest: str\n    replication_id: str\n    revealed_observation: str\n    schema_version: _Literal["broader-replication-calibration-source-observation/v1"]\n    seed: int\n    serialized_key_hex: str\n    u: str\n    world_id: str\n    z: str\n\n    def __post_init__(self) -> None:\n        _calibration_source_observation_mapping(self)\ndef _calibration_source_observation_mapping(projection):\n    return projection\n\ndef _decode_calibration_source_observation_projection(mapping):\n    return mapping\n\ndef _source_observation_preimage(\n    projection: CalibrationSourceObservationProjection,\n) -> dict[str, object]:\n    mapping = _calibration_source_observation_mapping(projection)\n    decoded = _decode_calibration_source_observation_projection(mapping)\n    if decoded != projection:\n        _reject("source_observation", "projection does not exactly reconstruct")\n    return mapping\n\ndef source_observation_identity(\n    projection: CalibrationSourceObservationProjection,\n) -> str:\n    return _protocol_hash(\n        "validation_evidence_calibration_source_observation/v1",\n        _source_observation_preimage(projection),\n    )\n\ndef _validate_complete_source_observation_surface(\n    value: object,\n) -> dict[str, object]:\n    projection = _require_exact_source_observation_object(value)\n    mapping = _calibration_source_observation_mapping(projection)\n    decoded = _decode_calibration_source_observation_projection(mapping)\n    if decoded != projection:\n        _reject("source_observation", "projection does not exactly reconstruct")\n    return mapping\n\ndef _require_exact_source_observation_object(value): return value\n\ndef _source_key_fields(value): return value\n\ndef _exact_oracle_key_id(value, label): return value\n\ndef _exact_f64_string(value, label): return value\n\ndef _exact_h64(value, label): return value\n\ndef _p2_selection_shape(value): return True\n\ndef _oracle_predecessor_shape(value): return True\n\ndef _source_evidence_at(p2_selection, observation_index):\n    return p2_selection[1][observation_index]\n\ndef _expected_source_coordinate(selection, observation_index):\n    return selection, observation_index\n\ndef _exact_frozen_world(value, world_id, seed): return value\n\ndef _oracle_key_id(key_fields): return key_fields\n\ndef _expected_observation_f64(selection, observation_index, world): return selection, observation_index, world\n\ndef _outcome_digest(oracle_key_id, observation): return oracle_key_id, observation\n\ndef _oracle_key_failure(detail):\n    return "CALIBRATION_ORACLE_KEY_ID_MISMATCH", detail\n\ndef _outcome_failure(detail):\n    return "CALIBRATION_OUTCOME_DIGEST_MISMATCH", detail\n\ndef _validate_source_observation_key_surface(\n    value,\n):\n    projection = _require_exact_source_observation_object(value)\n    key_fields = _source_key_fields(projection.key_fields)\n    oracle_key_id = _exact_oracle_key_id(\n        projection.oracle_key_id,\n        "source_observation.oracle_key_id",\n    )\n    return projection, key_fields, oracle_key_id\n\ndef _validate_source_observation_outcome_surface(\n    value,\n):\n    projection = _require_exact_source_observation_object(value)\n    revealed_observation = _exact_f64_string(\n        projection.revealed_observation,\n        "source_observation.revealed_observation",\n    )\n    outcome_digest = _exact_h64(\n        projection.outcome_digest,\n        "source_observation.outcome_digest",\n    )\n    return projection, revealed_observation, outcome_digest\n\ndef _predicate_3o_2_1(\n    selection,\n    p2_selection,\n):\n    selector_result = selection[16]\n    for observation_index in range(10):\n        evidence = _source_evidence_at(p2_selection, observation_index)\n        try:\n            projection, key_fields, projection_oracle_key_id = (\n                _validate_source_observation_key_surface(evidence[0])\n            )\n        except (AttributeError, TypeError, ValueError):\n            return _oracle_key_failure(\n                f"source observation[{observation_index}] key surface is malformed"\n            )\n        try:\n            expected_key_fields = _expected_source_coordinate(\n                selection,\n                observation_index,\n            )[6]\n        except (AttributeError, TypeError, ValueError):\n            return _oracle_key_failure(\n                f"source observation[{observation_index}] key reconstruction failed"\n            )\n        for field_index in range(8):\n            if key_fields[field_index] != expected_key_fields[field_index]:\n                return _oracle_key_failure(\n                    f"source observation[{observation_index}] "\n                    f"key_fields[{field_index}] differs"\n                )\n        selector_pair = selector_result.source_observation_identities[\n            observation_index\n        ]\n        actual_oracle_key_ids = ()\n        for label, occurrence in (\n            ("projection", projection_oracle_key_id),\n            ("selector", selector_result.source_oracle_key_ids[observation_index]),\n            ("paired", selector_pair[0]),\n        ):\n            try:\n                actual_oracle_key_id = _exact_oracle_key_id(\n                    occurrence,\n                    f"{label}.oracle_key_id",\n                )\n            except ValueError:\n                return _oracle_key_failure(\n                    f"source observation[{observation_index}] "\n                    f"{label} Oracle key is malformed"\n                )\n            actual_oracle_key_ids = (\n                *actual_oracle_key_ids,\n                (label, actual_oracle_key_id),\n            )\n        try:\n            expected_oracle_key_id = _oracle_key_id(  # type: ignore[no-untyped-call]\n                expected_key_fields\n            )\n        except (AttributeError, TypeError, ValueError):\n            return _oracle_key_failure(\n                f"source observation[{observation_index}] "\n                "Oracle key identity is malformed"\n            )\n        for label, actual_oracle_key_id in actual_oracle_key_ids:\n            if actual_oracle_key_id != expected_oracle_key_id:\n                return _oracle_key_failure(\n                    f"source observation[{observation_index}] "\n                    f"{label} Oracle key differs"\n                )\n    return None\n\ndef _predicate_3o_3_1(\n    selection,\n    p2_selection,\n    expected_predecessor,\n):\n    selector_result = selection[16]\n    world = _exact_frozen_world(\n        expected_predecessor[10],\n        selection[2],\n        selection[10],\n    )\n    for observation_index in range(10):\n        evidence = _source_evidence_at(p2_selection, observation_index)\n        try:\n            projection, revealed_observation, projection_outcome_digest = (\n                _validate_source_observation_outcome_surface(evidence[0])\n            )\n        except (AttributeError, TypeError, ValueError):\n            return _outcome_failure(\n                f"source observation[{observation_index}] outcome surface is malformed"\n            )\n        try:\n            expected_f64 = _expected_observation_f64(\n                selection,\n                observation_index,\n                world,\n            )\n        except (AttributeError, KeyError, TypeError, ValueError):\n            return _outcome_failure(\n                f"source observation[{observation_index}] pure reconstruction failed"\n            )\n        if revealed_observation != expected_f64:\n            return _outcome_failure(\n                f"source observation[{observation_index}] F64 observation differs"\n            )\n        selector_pair = selector_result.source_observation_identities[\n            observation_index\n        ]\n        try:\n            expected_key_fields = _expected_source_coordinate(\n                selection,\n                observation_index,\n            )[6]\n            expected_oracle_key_id = _oracle_key_id(  # type: ignore[no-untyped-call]\n                expected_key_fields\n            )\n            expected_digest = _outcome_digest(  # type: ignore[no-untyped-call]\n                expected_oracle_key_id,\n                expected_f64,\n            )\n        except (AttributeError, TypeError, ValueError):\n            return _outcome_failure(\n                f"source observation[{observation_index}] outcome digest is malformed"\n            )\n        for label, occurrence in (\n            ("projection", projection_outcome_digest),\n            ("selector", selector_pair[1]),\n        ):\n            try:\n                actual_digest = _exact_h64(\n                    occurrence,\n                    f"{label}.outcome_digest",\n                )\n            except ValueError:\n                return _outcome_failure(\n                    f"source observation[{observation_index}] "\n                    f"{label} outcome digest is malformed"\n                )\n            if actual_digest != expected_digest:\n                return _outcome_failure(\n                    f"source observation[{observation_index}] "\n                    f"{label} outcome digest differs"\n                )\n    return None\n\ndef _validate_stage2f_p1(**kwargs): return None, ()\n\ndef _p2_outcome(*args): return args\n\ndef _predicate_3o_2_0(*args): return None\n\ndef _predicate_3o_4_1(*args):\n    _validate_complete_source_observation_surface(args[1][1][0][0])\n    return None\n\ndef _validate_stage2f_p2(\n    *,\n    selections,\n    expected_execution_attestation_pairs,\n    attested_execution_specification_ids,\n    p2_selections,\n    expected_predecessors,\n):\n    p1_failure, p1_counts = _validate_stage2f_p1(\n        selections=selections,\n        expected_execution_attestation_pairs=expected_execution_attestation_pairs,\n        attested_execution_specification_ids=attested_execution_specification_ids,\n    )\n    if p1_failure is not None:\n        return p1_failure, (*p1_counts, 0, 0, 0, 0)\n    count_0 = 0\n    for index in range(_CANONICAL_SELECTION_COUNT):\n        count_0 += 1\n        if failure := _predicate_3o_2_0(\n            selections[index], p2_selections[index], expected_predecessors[index]\n        ):\n            return _p2_outcome(\n                failure, 0, index, p1_counts, (count_0, 0, 0, 0)\n            )\n    count_1 = 0\n    for index in range(_CANONICAL_SELECTION_COUNT):\n        count_1 += 1\n        if failure := _predicate_3o_2_1(\n            selections[index], p2_selections[index]\n        ):\n            return _p2_outcome(\n                failure, 1, index, p1_counts, (count_0, count_1, 0, 0)\n            )\n    count_2 = 0\n    for index in range(_CANONICAL_SELECTION_COUNT):\n        count_2 += 1\n        if failure := _predicate_3o_3_1(\n            selections[index],\n            p2_selections[index],\n            expected_predecessors[index],\n        ):\n            return _p2_outcome(\n                failure, 2, index, p1_counts, (count_0, count_1, count_2, 0)\n            )\n    count_3 = 0\n    for index in range(_CANONICAL_SELECTION_COUNT):\n        count_3 += 1\n        if failure := _predicate_3o_4_1(\n            selections[index],\n            p2_selections[index],\n            expected_predecessors[index],\n        ):\n            return _p2_outcome(\n                failure,\n                3,\n                index,\n                p1_counts,\n                (count_0, count_1, count_2, count_3),\n            )\n    return None, (*p1_counts, count_0, count_1, count_2, count_3)\n'

_FOCUSED_P2_ORDER_SOURCE = '@_dataclass(frozen=True, slots=True)\nclass CalibrationSourceObservationProjection:\n    candidate_id: str\n    comparison_group_id: str\n    digest: str\n    intervention_arm: _Literal["adam", "sgd"]\n    key_fields: tuple[str, ...]\n    namespace: _Literal["rde.broader.calibration-outcome/v1"]\n    oracle_key_id: str\n    outcome_digest: str\n    replication_id: str\n    revealed_observation: str\n    schema_version: _Literal["broader-replication-calibration-source-observation/v1"]\n    seed: int\n    serialized_key_hex: str\n    u: str\n    world_id: str\n    z: str\n\n    def __post_init__(self) -> None:\n        _calibration_source_observation_mapping(self)\n\ndef _require_exact_source_observation_object(value): return value\n\ndef _source_key_fields(value): return value\n\ndef _source_observation_failure(detail):\n    return "failure", detail\n\ndef _validate_complete_source_observation_surface(value): return None\n\ndef _exact_h64(value, field): return value\n\ndef _source_observation_matches(projection, carried_identity): return True\n\ndef source_observation_identity(value): return "identity"\n\ndef _first_source_mismatch(\n    projection: object,\n    expected: CalibrationSourceObservationProjection,\n) -> str | None:\n    projection = _require_exact_source_observation_object(projection)\n    if type(projection.candidate_id) is not str or projection.candidate_id != expected.candidate_id:\n        return "candidate_id"\n    if (\n        type(projection.comparison_group_id) is not str\n        or projection.comparison_group_id != expected.comparison_group_id\n    ):\n        return "comparison_group_id"\n    if type(projection.digest) is not str or projection.digest != expected.digest:\n        return "digest"\n    if (\n        type(projection.intervention_arm) is not str\n        or projection.intervention_arm != expected.intervention_arm\n    ):\n        return "intervention_arm"\n    try:\n        key_fields = _source_key_fields(projection.key_fields)\n    except ValueError:\n        return "key_fields"\n    if key_fields != expected.key_fields:\n        return "key_fields"\n    if type(projection.namespace) is not str or projection.namespace != expected.namespace:\n        return "namespace"\n    if (\n        type(projection.oracle_key_id) is not str\n        or projection.oracle_key_id != expected.oracle_key_id\n    ):\n        return "oracle_key_id"\n    if (\n        type(projection.outcome_digest) is not str\n        or projection.outcome_digest != expected.outcome_digest\n    ):\n        return "outcome_digest"\n    if (\n        type(projection.replication_id) is not str\n        or projection.replication_id != expected.replication_id\n    ):\n        return "replication_id"\n    if (\n        type(projection.revealed_observation) is not str\n        or projection.revealed_observation != expected.revealed_observation\n    ):\n        return "revealed_observation"\n    if (\n        type(projection.schema_version) is not str\n        or projection.schema_version != expected.schema_version\n    ):\n        return "schema_version"\n    if type(projection.seed) is not int or projection.seed != expected.seed:\n        return "seed"\n    if (\n        type(projection.serialized_key_hex) is not str\n        or projection.serialized_key_hex != expected.serialized_key_hex\n    ):\n        return "serialized_key_hex"\n    if type(projection.u) is not str or projection.u != expected.u:\n        return "u"\n    if type(projection.world_id) is not str or projection.world_id != expected.world_id:\n        return "world_id"\n    if type(projection.z) is not str or projection.z != expected.z:\n        return "z"\n    return None\n\ndef _predicate_3o_4_1(selection, p2_selection, expected_predecessor):\n    identities: tuple[str, ...] = ()\n    for observation_index in range(10):\n        evidence = p2_selection[observation_index]\n        carried_identity = evidence[1]\n        expected_projection = evidence[0]\n        try:\n            mismatch = _first_source_mismatch(evidence[0], expected_projection)\n        except (AttributeError, TypeError, ValueError):\n            return _source_observation_failure(\n                f"source observation[{observation_index}] exact projection type differs"\n            )\n        if mismatch is not None:\n            return _source_observation_failure(\n                f"source observation[{observation_index}] {mismatch} differs"\n            )\n        projection = evidence[0]\n        try:\n            _validate_complete_source_observation_surface(projection)\n        except (AttributeError, TypeError, ValueError):\n            return _source_observation_failure(\n                f"source observation[{observation_index}] strict reconstruction failed"\n            )\n        try:\n            carried_identity = _exact_h64(\n                carried_identity,\n                "source_observation_identity",\n            )\n            identity_matches = _source_observation_matches(\n                projection,\n                carried_identity,\n            )\n        except (AttributeError, TypeError, ValueError):\n            return _source_observation_failure(\n                f"source observation[{observation_index}] identity is malformed"\n            )\n        if not identity_matches:\n            return _source_observation_failure(\n                f"source observation[{observation_index}] identity differs"\n            )\n        identities = (*identities, carried_identity)\n    for observation_index in range(10):\n        for earlier_index in range(observation_index):\n            if identities[observation_index] == identities[earlier_index]:\n                return _source_observation_failure(\n                    f"source observation identity[{observation_index}] is duplicated"\n                )\n    return None\n'
_FOCUSED_P2_OWNED_SOURCE = ('from research_decision_engine.benchmarks.broader_protocol import protocol_hash as _protocol_hash, runtime_id as _runtime_id\n_P2_PREDICATE_PATHS = ("calibration/3o.2.0/oracle_binding", "calibration/3o.2.1/oracle_key", "calibration/3o.3.1/outcome", "calibration/3o.4.1/source_observation")\ndef _coordinate_detail(index, detail): return detail\n' + _FOCUSED_P2_OWNED_SOURCE).replace("def _oracle_key_id(key_fields): return key_fields", 'def _oracle_key_id(key_fields):\n    return _runtime_id("oracle-key", "oracle_key_id/v1", {"key_fields": key_fields})').replace("def _expected_observation_f64(selection, observation_index, world): return selection, observation_index, world", 'def _expected_observation_f64(selection, observation_index, world):\n    from research_decision_engine.benchmarks.broader_oracle import transform_key as _transform_key\n    (_world_id, _seed, comparison_group_id, expected_arm, _candidate_id, _replication_id, key_fields) = _expected_source_coordinate(selection, observation_index)\n    base_candidate_id = f"g{comparison_group_id[-2:]}-{expected_arm}-r1"\n    transform = _transform_key(key_fields)\n    observed = _hidden_arm_mean(world, base_candidate_id) + _hidden_observation_sigma(world, base_candidate_id) * transform.z\n    return _f64(observed)').replace("def _outcome_digest(oracle_key_id, observation): return oracle_key_id, observation", 'def _outcome_digest(oracle_key_id, revealed_observation):\n    return _protocol_hash("revealed_outcome/v1", {"oracle_key_id": oracle_key_id, "revealed_observation": revealed_observation})').replace("def _p2_outcome(*args): return args", "def _p2_outcome(failure, predicate_index, selection_index, p1_counts, p2_counts):\n    return ((failure[0], _P2_PREDICATE_PATHS[predicate_index], selection_index, _coordinate_detail(selection_index, failure[1])), (*p1_counts, *p2_counts))").replace("def _predicate_3o_2_0(*args): return None", "def _predicate_3o_2_0(selection, p2_selection, expected_predecessor): return None").replace("def _predicate_3o_4_1(*args):\n    _validate_complete_source_observation_surface(args[1][1][0][0])", "def _predicate_3o_4_1(selection, p2_selection, expected_predecessor):\n    _validate_complete_source_observation_surface(p2_selection[1][0][0])").replace("    count_0 = 0", "    if type(p2_selections) is not tuple or len(p2_selections) != _CANONICAL_SELECTION_COUNT or type(expected_predecessors) is not tuple or len(expected_predecessors) != _CANONICAL_SELECTION_COUNT:\n        return _p2_outcome(_oracle_binding_failure('canonical P2 selection or Oracle predecessor count is not exactly 318'), 0, 0, p1_counts, (0, 0, 0, 0))\n    count_0 = 0")
# fmt: off
def _focused_p2_owned_owner_source(owner: str) -> str:
    tree = ast.parse(_FOCUSED_P2_OWNED_SOURCE); functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}  # noqa: E702
    required = {owner}
    while True:
        prior = set(required)
        required.update(call.func.id for caller in tuple(required) for call in ast.walk(functions[caller]) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in functions)
        if required == prior: break  # noqa: E701
    selected = (node for node in tree.body if isinstance(node, ast.ImportFrom) or (isinstance(node, (ast.Assign, ast.AnnAssign)) and any(isinstance(target, ast.Name) and target.id == "_P2_PREDICATE_PATHS" for target in (node.targets if isinstance(node, ast.Assign) else (node.target,)))) or (isinstance(node, ast.FunctionDef) and node.name in required | {"_p2_outcome", "_coordinate_detail"}))
    return "\n\n".join(segment for node in selected if (segment := ast.get_source_segment(_FOCUSED_P2_OWNED_SOURCE, node)) is not None) + "\n\ndef _validate_stage2f_p2():\n    _predicate_3o_2_0()\n    _predicate_3o_2_1()\n    _predicate_3o_3_1()\n    _predicate_3o_4_1()\n"
_FOCUSED_P21_OWNED_SOURCE = _focused_p2_owned_owner_source("_predicate_3o_2_1")
_FOCUSED_P31_OWNED_SOURCE = _focused_p2_owned_owner_source("_predicate_3o_3_1")
def _p2_mutations(code: str, detail: str, specs: tuple[tuple[str, str, str], ...]) -> tuple[Mutation, ...]:
    return tuple(
        Mutation(case_id, _replace(old, new), architecture.Finding(code, detail))
        for case_id, old, new in specs
    )
def _insert_p2_statement(source: str, owner: str, statement: str) -> str:
    function = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == owner)
    lines = source.splitlines(keepends=True)
    insertion = "".join(f"{' ' * (function.col_offset + 4)}{line}\n" for line in statement.splitlines())
    lines[function.body[0].lineno - 1 : function.body[0].lineno - 1] = [insertion]
    return "".join(lines)
def _p2_comparison_span(source: str, field: str) -> tuple[int, int]:
    function = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "_first_source_mismatch")
    matches = tuple(statement for statement in function.body if any(isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "projection" and node.attr == field for node in ast.walk(statement)))
    assert len(matches) == 1
    statement = matches[0]
    assert statement.end_lineno is not None and statement.end_col_offset is not None
    lines = source.splitlines(keepends=True)
    return (sum(map(len, lines[: statement.lineno - 1])) + statement.col_offset, sum(map(len, lines[: statement.end_lineno - 1])) + statement.end_col_offset)
def _swap_p2_comparisons(source: str, first: str, second: str) -> str:
    first_span, second_span = _p2_comparison_span(source, first), _p2_comparison_span(source, second)
    replacements = ((*first_span, source[slice(*second_span)]), (*second_span, source[slice(*first_span)]))
    for start, end, replacement in sorted(replacements, reverse=True):
        source = source[:start] + replacement + source[end:]
    return source
def _omit_p2_comparison(source: str, field: str) -> str:
    start, end = _p2_comparison_span(source, field)
    return source[:start] + source[end:]

def _duplicate_p2_comparison(source: str, field: str) -> str:
    start, end = _p2_comparison_span(source, field)
    block = source[start:end]
    return source[:start] + block + "\n    " + block + source[end:]
def _alias_p2_comparison_precedence(source: str) -> str:
    candidate_span, serialized_span = _p2_comparison_span(source, "candidate_id"), _p2_comparison_span(source, "serialized_key_hex")
    replacements = ((*candidate_span, "candidate_value = projection.candidate_id"), (*serialized_span, 'serialized_value = projection.serialized_key_hex\n    if type(serialized_value) is not str or serialized_value != expected.serialized_key_hex:\n        return "serialized_key_hex"\n    if type(candidate_value) is not str or candidate_value != expected.candidate_id:\n        return "candidate_id"'))
    for start, end, replacement in sorted(replacements, reverse=True):
        source = source[:start] + replacement + source[end:]
    return source
_P2_KEY_COMPARISON = '            if key_fields[field_index] != expected_key_fields[field_index]:\n                return _oracle_key_failure(\n                    f"source observation[{observation_index}] "\n                    f"key_fields[{field_index}] differs"\n                )'
_P2_OBSERVATION_COMPARISON = '        if revealed_observation != expected_f64:\n            return _outcome_failure(\n                f"source observation[{observation_index}] F64 observation differs"\n            )'
_P2_OBSERVATION_RECOMPUTATION = '            expected_f64 = _expected_observation_f64(\n                selection,\n                observation_index,\n                world,\n            )'
_P2_ORACLE_RECOMPUTATION = '            expected_oracle_key_id = _oracle_key_id(  # type: ignore[no-untyped-call]\n                expected_key_fields\n            )'
_P2_DIGEST_RECOMPUTATION = '            expected_digest = _outcome_digest(  # type: ignore[no-untyped-call]\n                expected_oracle_key_id,\n                expected_f64,\n            )'
_P2_ORACLE_COMPARISON = '            if actual_oracle_key_id != expected_oracle_key_id:\n                return _oracle_key_failure(\n                    f"source observation[{observation_index}] "\n                    f"{label} Oracle key differs"\n                )'
def _p2_owned_finding(detail: str) -> architecture.Finding: return architecture.Finding("p2-owned-dataflow", detail)
def _p2_owned_case(case_id: str, owner: str, old: str, new: str, detail: str) -> Mutation: return Mutation(case_id, lambda source: _mutate_guard_function_reference(source, owner, old, new), _p2_owned_finding(detail))
def _p2_discard_expected_key_fields(source: str) -> str: source = _mutate_guard_function_reference(source, "_predicate_3o_2_1", "            expected_key_fields = _expected_source_coordinate(", "            discarded_expected_key_fields = _expected_source_coordinate("); return _mutate_guard_function_reference(source, "_predicate_3o_2_1", "        for field_index in range(8):", "        expected_key_fields = key_fields\n        for field_index in range(8):")  # noqa: E702
def _p2_discard_expected_observation(source: str) -> str: source = _mutate_guard_function_reference(source, "_predicate_3o_3_1", "            expected_f64 = _expected_observation_f64(", "            discarded_expected_f64 = _expected_observation_f64("); return _mutate_guard_function_reference(source, "_predicate_3o_3_1", "        if revealed_observation != expected_f64:", "        expected_f64 = revealed_observation\n        if revealed_observation != expected_f64:")  # noqa: E702
def _p2_dead_owned_comparison(source: str) -> str: source = _mutate_guard_function_reference(source, "_predicate_3o_2_1", _P2_KEY_COMPARISON, "            pass"); return source + "\n\ndef _p2_dead_owned_comparison(actual, expected):\n    if actual != expected:\n        return _oracle_key_failure('dead key mismatch')\n"  # noqa: E702
def _p2_conditional_carried_key_alias(source: str) -> str: source = _mutate_guard_function_reference(source, "_predicate_3o_2_1", "        actual_oracle_key_ids = ()", "        if selector_result:\n            selector_oracle_key_id = selector_result.source_oracle_key_ids[observation_index]\n        actual_oracle_key_ids = ()"); return _mutate_guard_function_reference(source, "_predicate_3o_2_1", '            ("selector", selector_result.source_oracle_key_ids[observation_index]),', '            ("selector", selector_oracle_key_id),')  # noqa: E702
def _p2_alias_producer_arguments(source: str) -> str: return _mutate_guard_function_reference(source, "_predicate_3o_2_1", "            expected_key_fields = _expected_source_coordinate(\n                selection,\n                observation_index,\n            )[6]", "            coordinate_producer = _expected_source_coordinate\n            producer_selection = selection\n            producer_observation_index = observation_index\n            expected_key_fields = coordinate_producer(\n                producer_selection,\n                producer_observation_index,\n            )[6]")
def _p2_private_oracle_key_producer(source: str) -> str: source = _mutate_guard_function_reference(source, "_predicate_3o_2_1", "_oracle_key_id(  # type: ignore[no-untyped-call]", "_p2_oracle_key_id(  # type: ignore[no-untyped-call]"); return source + "\n\ndef _p2_oracle_key_id(key_fields):\n    return _oracle_key_id(key_fields)\n"  # noqa: E702
def _p2_filtered_comparison_helper(source: str) -> str: source = _mutate_guard_function_reference(source, "_predicate_3o_2_1", "            if actual_oracle_key_id != expected_oracle_key_id:", "            if _p2_filtered_owned_differs(label, actual_oracle_key_id, expected_oracle_key_id):"); return source + '\n\ndef _p2_filtered_owned_differs(label, actual, expected):\n    if label == "projection":\n        return actual != expected\n    return False\n'  # noqa: E702
def _p2_swallowed_comparison_helper(source: str) -> str: source = _mutate_guard_function_reference(source, "_predicate_3o_2_1", "key_fields[field_index] != expected_key_fields[field_index]", "_p2_swallowed_owned_differs(key_fields[field_index], expected_key_fields[field_index])"); return source + "\n\ndef _p2_swallowed_owned_differs(actual, expected):\n    try:\n        return actual != expected\n    except Exception:\n        return False\n"  # noqa: E702
def _p2_reverse_digest_group(source: str) -> str: source = _mutate_guard_function_reference(source, "_predicate_3o_3_1", "        for label, occurrence in (\n", "        for label, occurrence in reversed((\n"); return _mutate_guard_function_reference(source, "_predicate_3o_3_1", '            ("selector", selector_pair[1]),\n        ):\n', '            ("selector", selector_pair[1]),\n        )):\n')  # noqa: E702
def _p2_transformed_comparison_helper(source: str, returned: str) -> str: source = _mutate_guard_function_reference(source, "_predicate_3o_2_1", "key_fields[field_index] != expected_key_fields[field_index]", "_p2_wrapped_differs(key_fields[field_index], expected_key_fields[field_index])"); return f"def _p2_inner_differs(actual, expected):\n    return actual != expected\n\ndef _p2_wrapped_differs(actual, expected):\n    return {returned}\n\n" + source  # noqa: E702
def _p2_cross_paired_dead_helper(source: str) -> str: source = _mutate_guard_function_reference(source, "_predicate_3o_2_1", "key_fields[field_index] != expected_key_fields[field_index]", "_p2_pair(key_fields[field_index], expected_key_fields[field_index])"); return "def _p2_dead_differs(actual, expected):\n    return actual != expected\n\ndef _p2_pair(actual, expected):\n    if False:\n        _p2_dead_differs(actual, expected)\n    return (actual, expected)\n\n" + source  # noqa: E702
def _p2_replace_owner_all(source: str, owner: str, old: str, new: str) -> str: block = _guard_source_function_block(source, owner); assert old in block; return source.replace(block, block.replace(old, new), 1)  # noqa: E702
def _p2_empty_loop_comparison(source: str, owner: str, block: str) -> str: indentation = " " * (len(block) - len(block.lstrip())); nested = "\n".join("    " + line for line in block.splitlines()); return _mutate_guard_function_reference(source, owner, block, f"{indentation}for _ in ():\n{nested}")  # noqa: E702
_P21_KEY_FIELDS = "_predicate_3o_2_1:key-fields"
_P21_PROJECTION_KEY = "_predicate_3o_2_1:projection-oracle-key"
_P21_SELECTOR_KEY = "_predicate_3o_2_1:selector-oracle-key"
_P21_PAIRED_KEY = "_predicate_3o_2_1:paired-oracle-key"
_P31_OBSERVATION = "_predicate_3o_3_1:revealed-observation"
_P31_PROJECTION_DIGEST = "_predicate_3o_3_1:projection-outcome-digest"
_P31_SELECTOR_DIGEST = "_predicate_3o_3_1:selector-outcome-digest"
_ACTIVE_P2_OWNED_DATAFLOW_CASES = (
    Mutation("inherited-p1-validator-rebound", lambda source: source + "\n_validate_stage2f_p1 = lambda **kwargs: (None, (0, 0, 0, 0, 0, 0, 0))\n", architecture.Finding("p2-owned-function-authority", "_validate_stage2f_p1")), Mutation("oracle-binding-failure-code-drift", lambda source: source.replace("CALIBRATION_ORACLE_BINDING_MISMATCH", "CALIBRATION_ORACLE_KEY_ID_MISMATCH", 1), architecture.Finding("p2-owned-function-authority", "_oracle_binding_failure")), Mutation("source-observation-failure-code-drift", lambda source: source.replace("CALIBRATION_SOURCE_OBSERVATION_ID_MISMATCH", "CALIBRATION_OUTCOME_DIGEST_MISMATCH", 1), architecture.Finding("p2-owned-function-authority", "_source_observation_failure")), Mutation("reject-final-binding-rebound", lambda source: source + "\n_reject = lambda *args, **kwargs: None\n", architecture.Finding("p2-owned-function-authority", "_reject")), Mutation("ascii-validator-body-drift", lambda source: _insert_p2_statement(source, "_exact_ascii_string", "return value"), architecture.Finding("p2-owned-function-authority", "_exact_ascii_string")),
    _p2_owned_case("bypass-key-fields-comparison", "_predicate_3o_2_1", _P2_KEY_COMPARISON, "            if False:\n                pass", _P21_KEY_FIELDS), _p2_owned_case("key-fields-expected-self-comparison", "_predicate_3o_2_1", "key_fields[field_index] != expected_key_fields[field_index]", "expected_key_fields[field_index] != expected_key_fields[field_index]", _P21_KEY_FIELDS),
    _p2_owned_case("key-fields-carried-self-comparison", "_predicate_3o_2_1", "key_fields[field_index] != expected_key_fields[field_index]", "key_fields[field_index] != key_fields[field_index]", _P21_KEY_FIELDS), Mutation("expected-key-fields-reconstructed-but-discarded", _p2_discard_expected_key_fields, _p2_owned_finding(_P21_KEY_FIELDS)),
    _p2_owned_case("bypass-selector-oracle-key-occurrence", "_predicate_3o_2_1", '            ("selector", selector_result.source_oracle_key_ids[observation_index]),', '            ("selector", projection_oracle_key_id),', _P21_SELECTOR_KEY), _p2_owned_case("selector-oracle-key-occurrence-omitted", "_predicate_3o_2_1", '            ("selector", selector_result.source_oracle_key_ids[observation_index]),\n', "", _P21_SELECTOR_KEY),
    _p2_owned_case("bypass-paired-oracle-key-occurrence", "_predicate_3o_2_1", '            ("paired", selector_pair[0]),', '            ("paired", projection_oracle_key_id),', _P21_PAIRED_KEY), _p2_owned_case("paired-oracle-key-occurrence-omitted", "_predicate_3o_2_1", '            ("paired", selector_pair[0]),\n', "", _P21_PAIRED_KEY),
    _p2_owned_case("only-one-oracle-key-occurrence-checked", "_predicate_3o_2_1", '            ("selector", selector_result.source_oracle_key_ids[observation_index]),\n            ("paired", selector_pair[0]),\n', "", _P21_SELECTOR_KEY), _p2_owned_case("oracle-key-recomputation-result-discarded", "_predicate_3o_2_1", _P2_ORACLE_RECOMPUTATION, "            _oracle_key_id(expected_key_fields)\n            expected_oracle_key_id = projection_oracle_key_id", _P21_PROJECTION_KEY),
    Mutation("oracle-key-recomputation-after-comparisons", lambda source: _mutate_guard_function_reference(_mutate_guard_function_reference(source, "_predicate_3o_2_1", _P2_ORACLE_RECOMPUTATION, "            expected_oracle_key_id = projection_oracle_key_id"), "_predicate_3o_2_1", "    return None", "    _late_oracle_key_id = _oracle_key_id(expected_key_fields)\n    return None"), _p2_owned_finding(_P21_PROJECTION_KEY)), _p2_owned_case("bypass-revealed-observation-comparison", "_predicate_3o_3_1", _P2_OBSERVATION_COMPARISON, "        if False:\n            pass", _P31_OBSERVATION),
    _p2_owned_case("revealed-observation-self-comparison", "_predicate_3o_3_1", "revealed_observation != expected_f64", "revealed_observation != revealed_observation", _P31_OBSERVATION), Mutation("reconstructed-observation-discarded", _p2_discard_expected_observation, _p2_owned_finding(_P31_OBSERVATION)),
    _p2_owned_case("revealed-observation-compared-to-selector-carried-value", "_predicate_3o_3_1", "revealed_observation != expected_f64", "revealed_observation != selector_result.source_observation_identities[observation_index][1]", _P31_OBSERVATION), _p2_owned_case("bypass-projection-outcome-digest-occurrence", "_predicate_3o_3_1", '            ("projection", projection_outcome_digest),', '            ("projection", selector_pair[1]),', _P31_PROJECTION_DIGEST),
    _p2_owned_case("projection-outcome-digest-occurrence-omitted", "_predicate_3o_3_1", '            ("projection", projection_outcome_digest),\n', "", _P31_PROJECTION_DIGEST), _p2_owned_case("selector-outcome-digest-occurrence-omitted", "_predicate_3o_3_1", '            ("selector", selector_pair[1]),\n', "", _P31_SELECTOR_DIGEST),
    _p2_owned_case("only-one-outcome-digest-occurrence-checked", "_predicate_3o_3_1", '            ("selector", selector_pair[1]),\n', "", _P31_SELECTOR_DIGEST), _p2_owned_case("projection-outcome-digest-compared-to-selector-digest", "_predicate_3o_3_1", '            ("projection", projection_outcome_digest),', '            ("projection", selector_pair[1]),', _P31_PROJECTION_DIGEST),
    _p2_owned_case("recomputed-outcome-digest-discarded", "_predicate_3o_3_1", _P2_DIGEST_RECOMPUTATION, "            _outcome_digest(expected_oracle_key_id, expected_f64)\n            expected_digest = projection_outcome_digest", _P31_PROJECTION_DIGEST), _p2_owned_case("wrong-outcome-digest-domain", "_predicate_3o_3_1", "                expected_oracle_key_id,\n                expected_f64,", "                expected_f64,\n                expected_oracle_key_id,", _P31_PROJECTION_DIGEST),
    _p2_owned_case("required-comparison-unreachable-branch", "_predicate_3o_2_1", _P2_KEY_COMPARISON, "            if False:\n                if key_fields[field_index] != expected_key_fields[field_index]:\n                    return _oracle_key_failure('unreachable key mismatch')", _P21_KEY_FIELDS), _p2_owned_case("comparison-after-successful-return", "_predicate_3o_2_1", _P2_KEY_COMPARISON, "            return None\n" + _P2_KEY_COMPARISON, _P21_KEY_FIELDS),
    _p2_owned_case("required-comparison-boolean-ignored", "_predicate_3o_2_1", _P2_KEY_COMPARISON, "            key_fields[field_index] != expected_key_fields[field_index]", _P21_KEY_FIELDS), Mutation("required-comparison-dead-private-helper", _p2_dead_owned_comparison, _p2_owned_finding(_P21_KEY_FIELDS)),
    _p2_owned_case("unresolved-expected-value-alias", "_predicate_3o_2_1", "key_fields[field_index] != expected_key_fields[field_index]", "key_fields[field_index] != unresolved_expected_key_fields[field_index]", _P21_KEY_FIELDS), _p2_owned_case("dynamic-owned-comparison-dispatch", "_predicate_3o_2_1", _P2_KEY_COMPARISON, "            comparators = (lambda left, right: left != right,)\n            if comparators[dynamic_index](key_fields[field_index], expected_key_fields[field_index]):\n                return _oracle_key_failure('dynamic key mismatch')", _P21_KEY_FIELDS),
    _p2_owned_case("catch-and-continue-after-owned-mismatch", "_predicate_3o_2_1", _P2_KEY_COMPARISON, "            try:\n                if key_fields[field_index] != expected_key_fields[field_index]:\n                    raise ValueError('key mismatch')\n            except ValueError:\n                pass", _P21_KEY_FIELDS), _p2_owned_case("short-circuit-owned-comparison", "_predicate_3o_2_1", "if key_fields[field_index] != expected_key_fields[field_index]:", "if skip_owned_comparison and key_fields[field_index] != expected_key_fields[field_index]:", _P21_KEY_FIELDS),
    _p2_owned_case("key-fields-fixed-expected-index", "_predicate_3o_2_1", "key_fields[field_index] != expected_key_fields[field_index]", "key_fields[field_index] != expected_key_fields[0]", _P21_KEY_FIELDS), _p2_owned_case("oracle-key-first-actual-only", "_predicate_3o_2_1", "for label, actual_oracle_key_id in actual_oracle_key_ids:", "for label, actual_oracle_key_id in (actual_oracle_key_ids[0],):", _P21_SELECTOR_KEY),
    _p2_owned_case("oracle-key-label-filter-continue", "_predicate_3o_2_1", "for label, actual_oracle_key_id in actual_oracle_key_ids:", 'for label, actual_oracle_key_id in actual_oracle_key_ids:\n            if label != "projection":\n                continue', _P21_SELECTOR_KEY), _p2_owned_case("outcome-digest-label-filter-continue", "_predicate_3o_3_1", "        ):\n            try:\n                actual_digest = _exact_h64(", '        ):\n            if label != "projection":\n                continue\n            try:\n                actual_digest = _exact_h64(', _P31_SELECTOR_DIGEST),
    _p2_owned_case("oracle-key-conditional-producer-assignment", "_predicate_3o_2_1", _P2_ORACLE_RECOMPUTATION, "            if selector_result:\n                expected_oracle_key_id = _oracle_key_id(  # type: ignore[no-untyped-call]\n                    expected_key_fields\n                )", _P21_PROJECTION_KEY), Mutation("selector-key-conditional-carried-alias", _p2_conditional_carried_key_alias, _p2_owned_finding(_P21_SELECTOR_KEY)),
    _p2_owned_case("oracle-key-global-producer-mutation", "_predicate_3o_2_1", _P2_ORACLE_RECOMPUTATION, '            globals()["_oracle_key_id"] = lambda key_fields: ""\n' + _P2_ORACLE_RECOMPUTATION, _P21_PROJECTION_KEY), _p2_owned_case("oracle-key-qualified-code-mutation", "_predicate_3o_2_1", _P2_ORACLE_RECOMPUTATION, '            _oracle_key_id.__code__ = (lambda key_fields: "").__code__\n' + _P2_ORACLE_RECOMPUTATION, _P21_PROJECTION_KEY), Mutation("oracle-key-reachable-helper-global-mutation", lambda source: _p2_private_oracle_key_producer(source).replace("def _p2_oracle_key_id(key_fields):\n    return _oracle_key_id(key_fields)", 'def _p2_oracle_key_id(key_fields):\n    globals()["_oracle_key_id"] = lambda fields: ""\n    return _oracle_key_id(key_fields)'), _p2_owned_finding(_P21_PROJECTION_KEY)), Mutation("oracle-key-module-code-mutation", lambda source: source + '\n_oracle_key_id.__code__ = (lambda fields: "").__code__\n', _p2_owned_finding(_P21_PROJECTION_KEY)),
    _p2_owned_case("oracle-key-comparison-projection-only-branch", "_predicate_3o_2_1", _P2_ORACLE_COMPARISON, '            if label == "projection":\n                if actual_oracle_key_id != expected_oracle_key_id:\n                    return _oracle_key_failure(\n                        f"source observation[{observation_index}] "\n                        f"{label} Oracle key differs"\n                    )', _P21_SELECTOR_KEY), _p2_owned_case("key-fields-exception-fallback", "_predicate_3o_2_1", '        except (AttributeError, TypeError, ValueError):\n            return _oracle_key_failure(\n                f"source observation[{observation_index}] key reconstruction failed"\n            )', '        except (AttributeError, TypeError, ValueError):\n            expected_key_fields = ("",) * 8', _P21_KEY_FIELDS),
    _p2_owned_case("oracle-key-exception-fallback", "_predicate_3o_2_1", '        except (AttributeError, TypeError, ValueError):\n            return _oracle_key_failure(\n                f"source observation[{observation_index}] "\n                "Oracle key identity is malformed"\n            )', '        except (AttributeError, TypeError, ValueError):\n            expected_oracle_key_id = ""', _P21_PROJECTION_KEY), _p2_owned_case("observation-exception-fallback", "_predicate_3o_3_1", '        except (AttributeError, KeyError, TypeError, ValueError):\n            return _outcome_failure(\n                f"source observation[{observation_index}] pure reconstruction failed"\n            )', '        except (AttributeError, KeyError, TypeError, ValueError):\n            expected_f64 = "0x0.0p+0"', _P31_OBSERVATION),
    _p2_owned_case("oracle-key-conditional-expression-fallback", "_predicate_3o_2_1", _P2_ORACLE_RECOMPUTATION, '            expected_oracle_key_id = _oracle_key_id(expected_key_fields) if selector_result else ""', _P21_PROJECTION_KEY), _p2_owned_case("oracle-key-empty-loop-producer", "_predicate_3o_2_1", _P2_ORACLE_RECOMPUTATION, '            expected_oracle_key_id = ""\n            for _ in ():\n                expected_oracle_key_id = _oracle_key_id(expected_key_fields)', _P21_PROJECTION_KEY),
    _p2_owned_case("oracle-key-body-only-loop-producer", "_predicate_3o_2_1", _P2_ORACLE_RECOMPUTATION, '            for _ in maybe_values:\n                expected_oracle_key_id = _oracle_key_id(expected_key_fields)', _P21_PROJECTION_KEY), _p2_owned_case("key-fields-comparison-empty-loop", "_predicate_3o_2_1", _P2_KEY_COMPARISON, "            while False:\n                if key_fields[field_index] != expected_key_fields[field_index]:\n                    return _oracle_key_failure('unreachable key mismatch')", _P21_KEY_FIELDS),
    Mutation("oracle-key-filtered-comparison-helper", _p2_filtered_comparison_helper, _p2_owned_finding(_P21_SELECTOR_KEY)), Mutation("key-fields-swallowed-comparison-helper", _p2_swallowed_comparison_helper, _p2_owned_finding(_P21_KEY_FIELDS)),
    _p2_owned_case("oracle-key-transformed-producer", "_predicate_3o_2_1", _P2_ORACLE_RECOMPUTATION, '            expected_oracle_key_id = _oracle_key_id(expected_key_fields) + "x"', _P21_PROJECTION_KEY), _p2_owned_case("oracle-key-compared-producer", "_predicate_3o_2_1", _P2_ORACLE_RECOMPUTATION, '            expected_oracle_key_id = _oracle_key_id(expected_key_fields) == "x"', _P21_PROJECTION_KEY),
    _p2_owned_case("observation-formatted-producer", "_predicate_3o_3_1", _P2_OBSERVATION_RECOMPUTATION, _P2_OBSERVATION_RECOMPUTATION + '\n            expected_f64 = f"{expected_f64}x"', _P31_OBSERVATION), _p2_owned_case("observation-wrapped-producer", "_predicate_3o_3_1", _P2_OBSERVATION_RECOMPUTATION, _P2_OBSERVATION_RECOMPUTATION + "\n            expected_f64 = str(expected_f64)", _P31_OBSERVATION),
    _p2_owned_case("digest-transformed-producer", "_predicate_3o_3_1", _P2_DIGEST_RECOMPUTATION, '            expected_digest = _outcome_digest(expected_oracle_key_id, expected_f64) + "x"', _P31_PROJECTION_DIGEST), _p2_owned_case("key-fields-transformed-carrier", "_predicate_3o_2_1", "            if key_fields[field_index] != expected_key_fields[field_index]:", "            transformed_key = key_fields[field_index] * 0 + key_fields[0]\n            if transformed_key != expected_key_fields[field_index]:", _P21_KEY_FIELDS),
    _p2_owned_case("oracle-key-transformed-carrier", "_predicate_3o_2_1", "            if actual_oracle_key_id != expected_oracle_key_id:", "            transformed_key = actual_oracle_key_id * 0 + projection_oracle_key_id\n            if transformed_key != expected_oracle_key_id:", _P21_SELECTOR_KEY), _p2_owned_case("observation-transformed-carrier", "_predicate_3o_3_1", "        if revealed_observation != expected_f64:", '        transformed_observation = revealed_observation * 0 + "0x0.0p+0"\n        if transformed_observation != expected_f64:', _P31_OBSERVATION),
    _p2_owned_case("digest-transformed-carrier", "_predicate_3o_3_1", "            if actual_digest != expected_digest:", "            transformed_digest = actual_digest * 0 + projection_outcome_digest\n            if transformed_digest != expected_digest:", _P31_SELECTOR_DIGEST), _p2_owned_case("key-fields-wrong-range", "_predicate_3o_2_1", "        for field_index in range(8):", "        for field_index in range(1):", _P21_KEY_FIELDS),
    _p2_owned_case("key-fields-index-overwritten-by-singleton-loop", "_predicate_3o_2_1", _P2_KEY_COMPARISON, "            for field_index in (0,):\n                pass\n" + _P2_KEY_COMPARISON, _P21_KEY_FIELDS), _p2_owned_case("key-fields-index-overwritten-by-mixed-loop", "_predicate_3o_2_1", _P2_KEY_COMPARISON, "            for field_index in (field_index, 0):\n                pass\n" + _P2_KEY_COMPARISON, _P21_KEY_FIELDS),
    _p2_owned_case("oracle-occurrences-wrong-range", "_predicate_3o_2_1", "    for observation_index in range(10):", "    for observation_index in range(1):", _P21_PROJECTION_KEY), _p2_owned_case("outcome-occurrences-wrong-range", "_predicate_3o_3_1", "    for observation_index in range(10):", "    for observation_index in range(1):", _P31_OBSERVATION),
    _p2_owned_case("oracle-observation-index-overwritten", "_predicate_3o_2_1", "        evidence = _source_evidence_at(p2_selection, observation_index)", "        for observation_index in (0,):\n            pass\n        evidence = _source_evidence_at(p2_selection, observation_index)", _P21_KEY_FIELDS), _p2_owned_case("outcome-observation-index-overwritten", "_predicate_3o_3_1", "        evidence = _source_evidence_at(p2_selection, observation_index)", "        for observation_index in (0,):\n            pass\n        evidence = _source_evidence_at(p2_selection, observation_index)", _P31_OBSERVATION),
    _p2_owned_case("oracle-group-reversed", "_predicate_3o_2_1", "        for label, actual_oracle_key_id in actual_oracle_key_ids:", "        for label, actual_oracle_key_id in reversed(actual_oracle_key_ids):", _P21_SELECTOR_KEY), Mutation("digest-group-reversed", _p2_reverse_digest_group, _p2_owned_finding(_P31_SELECTOR_DIGEST)),
    _p2_owned_case("oracle-key-loop-reverse-overwrite", "_predicate_3o_2_1", _P2_ORACLE_RECOMPUTATION, _P2_ORACLE_RECOMPUTATION + '\n            for _ in maybe_values:\n                expected_oracle_key_id = ""', _P21_PROJECTION_KEY), _p2_owned_case("oracle-key-nonempty-loop-body-overwrite", "_predicate_3o_2_1", _P2_ORACLE_RECOMPUTATION, _P2_ORACLE_RECOMPUTATION + '\n            for _ in (0,):\n                expected_oracle_key_id = ""', _P21_PROJECTION_KEY),
    _p2_owned_case("oracle-key-nonempty-loop-target-overwrite", "_predicate_3o_2_1", _P2_ORACLE_RECOMPUTATION, _P2_ORACLE_RECOMPUTATION + '\n            for expected_oracle_key_id in ("",):\n                pass', _P21_PROJECTION_KEY), _p2_owned_case("observation-nonempty-loop-target-overwrite", "_predicate_3o_3_1", _P2_OBSERVATION_RECOMPUTATION, _P2_OBSERVATION_RECOMPUTATION + '\n            for expected_f64 in ("0x0.0p+0",):\n                pass', _P31_OBSERVATION),
    _p2_owned_case("revealed-observation-nonempty-loop-target-overwrite", "_predicate_3o_3_1", "        if revealed_observation != expected_f64:", '        for revealed_observation in ("0x0.0p+0",):\n            pass\n        if revealed_observation != expected_f64:', _P31_OBSERVATION), _p2_owned_case("oracle-key-nonlocal-overwrite", "_predicate_3o_2_1", _P2_ORACLE_RECOMPUTATION, _P2_ORACLE_RECOMPUTATION + '\n            def overwrite_expected():\n                nonlocal expected_oracle_key_id\n                expected_oracle_key_id = ""\n            overwrite_expected()', _P21_PROJECTION_KEY),
    _p2_owned_case("revealed-observation-nonlocal-overwrite", "_predicate_3o_3_1", "        if revealed_observation != expected_f64:", '        def overwrite_revealed():\n            nonlocal revealed_observation\n            revealed_observation = "0x0.0p+0"\n        overwrite_revealed()\n        if revealed_observation != expected_f64:', _P31_OBSERVATION), _p2_owned_case("oracle-key-augassign-laundering", "_predicate_3o_2_1", _P2_ORACLE_RECOMPUTATION, _P2_ORACLE_RECOMPUTATION + '\n            expected_oracle_key_id += ""', _P21_PROJECTION_KEY),
    _p2_owned_case("oracle-key-tuple-carrier-laundering", "_predicate_3o_2_1", "selector_result.source_oracle_key_ids[observation_index]),", "(selector_result.source_oracle_key_ids[observation_index],)[0]),", _P21_SELECTOR_KEY), _p2_owned_case("oracle-key-list-producer-laundering", "_predicate_3o_2_1", _P2_ORACLE_RECOMPUTATION, _P2_ORACLE_RECOMPUTATION + "\n            expected_oracle_key_id = [expected_oracle_key_id][0]", _P21_PROJECTION_KEY),
    _p2_owned_case("oracle-group-aliased-reversed", "_predicate_3o_2_1", "        for label, actual_oracle_key_id in actual_oracle_key_ids:", "        aliased_oracle_keys = reversed(actual_oracle_key_ids)\n        for label, actual_oracle_key_id in aliased_oracle_keys:", _P21_SELECTOR_KEY), _p2_owned_case("oracle-group-aliased-sorted", "_predicate_3o_2_1", "        for label, actual_oracle_key_id in actual_oracle_key_ids:", "        aliased_oracle_keys = sorted(actual_oracle_key_ids)\n        for label, actual_oracle_key_id in aliased_oracle_keys:", _P21_SELECTOR_KEY),
    _p2_owned_case("oracle-group-filtered", "_predicate_3o_2_1", "        for label, actual_oracle_key_id in actual_oracle_key_ids:", '        aliased_oracle_keys = filter(lambda item: item[0] == "projection", actual_oracle_key_ids)\n        for label, actual_oracle_key_id in aliased_oracle_keys:', _P21_SELECTOR_KEY), _p2_owned_case("oracle-group-preconsumed-iterator", "_predicate_3o_2_1", "        for label, actual_oracle_key_id in actual_oracle_key_ids:", "        aliased_oracle_keys = iter(actual_oracle_key_ids)\n        next(aliased_oracle_keys)\n        for label, actual_oracle_key_id in aliased_oracle_keys:", _P21_SELECTOR_KEY),
    _p2_owned_case("oracle-group-mapped-substitution", "_predicate_3o_2_1", "        for label, actual_oracle_key_id in actual_oracle_key_ids:", '        aliased_oracle_keys = map(lambda item: ("projection", projection_oracle_key_id), actual_oracle_key_ids)\n        for label, actual_oracle_key_id in aliased_oracle_keys:', _P21_SELECTOR_KEY), _p2_owned_case("oracle-group-generator-filter", "_predicate_3o_2_1", "        for label, actual_oracle_key_id in actual_oracle_key_ids:", '        aliased_oracle_keys = (item for item in actual_oracle_key_ids if item[0] == "projection")\n        for label, actual_oracle_key_id in aliased_oracle_keys:', _P21_SELECTOR_KEY),
    _p2_owned_case("oracle-group-accumulator-filter-continue", "_predicate_3o_2_1", "        ):\n            try:\n                actual_oracle_key_id = _exact_oracle_key_id(", '        ):\n            if label != "projection":\n                continue\n            try:\n                actual_oracle_key_id = _exact_oracle_key_id(', _P21_SELECTOR_KEY), _p2_owned_case("oracle-group-accumulator-break", "_predicate_3o_2_1", "                (label, actual_oracle_key_id),\n            )", "                (label, actual_oracle_key_id),\n            )\n            break", _P21_SELECTOR_KEY),
    Mutation("oracle-key-module-default-mutation", lambda source: source + '\ndef _unrelated_default(_=setattr(_oracle_key_id, "__code__", (lambda fields: "").__code__)):\n    return None\n', _p2_owned_finding(_P21_PROJECTION_KEY)), Mutation("oracle-key-module-decorator-mutation", lambda source: source + '\ndef _mutating_decorator(function):\n    _oracle_key_id.__code__ = (lambda fields: "").__code__\n    return function\n@_mutating_decorator\ndef _unrelated_decorated():\n    return None\n', _p2_owned_finding(_P21_PROJECTION_KEY)), Mutation("oracle-key-module-base-mutation", lambda source: source + '\ndef _mutating_base():\n    _oracle_key_id.__code__ = (lambda fields: "").__code__\n    return object\nclass _UnrelatedBase(_mutating_base()):\n    pass\n', _p2_owned_finding(_P21_PROJECTION_KEY)), Mutation("oracle-key-module-class-body-mutation", lambda source: source + '\ndef _mutating_class_body():\n    _oracle_key_id.__code__ = (lambda fields: "").__code__\n    return 1\nclass _UnrelatedClass:\n    value = _mutating_class_body()\n', _p2_owned_finding(_P21_PROJECTION_KEY)), Mutation("oracle-key-conditional-return-laundering", lambda source: 'def _launder(value):\n    if value:\n        return ""\n    return value\n\n' + _mutate_guard_function_reference(source, "_predicate_3o_2_1", _P2_ORACLE_RECOMPUTATION, _P2_ORACLE_RECOMPUTATION + "\n            expected_oracle_key_id = _launder(expected_oracle_key_id)"), _p2_owned_finding(_P21_PROJECTION_KEY)), Mutation("oracle-carrier-conditional-return-laundering", lambda source: 'def _launder(value):\n    if value:\n        return ""\n    return value\n\n' + _mutate_guard_function_reference(source, "_predicate_3o_2_1", "            if actual_oracle_key_id != expected_oracle_key_id:", "            actual_oracle_key_id = _launder(actual_oracle_key_id)\n            if actual_oracle_key_id != expected_oracle_key_id:"), _p2_owned_finding(_P21_SELECTOR_KEY)), Mutation("oracle-key-finally-return-laundering", lambda source: 'def _launder(value):\n    try:\n        return value\n    finally:\n        return ""\n\n' + _mutate_guard_function_reference(source, "_predicate_3o_2_1", _P2_ORACLE_RECOMPUTATION, _P2_ORACLE_RECOMPUTATION + "\n            expected_oracle_key_id = _launder(expected_oracle_key_id)"), _p2_owned_finding(_P21_PROJECTION_KEY)), Mutation("oracle-carrier-finally-return-laundering", lambda source: 'def _launder(value):\n    try:\n        return value\n    finally:\n        return ""\n\n' + _mutate_guard_function_reference(source, "_predicate_3o_2_1", "            if actual_oracle_key_id != expected_oracle_key_id:", "            actual_oracle_key_id = _launder(actual_oracle_key_id)\n            if actual_oracle_key_id != expected_oracle_key_id:"), _p2_owned_finding(_P21_SELECTOR_KEY)),
    Mutation("required-comparison-negated-private-helper", lambda source: _p2_transformed_comparison_helper(source, "not _p2_inner_differs(actual, expected)"), _p2_owned_finding(_P21_KEY_FIELDS)), Mutation("required-comparison-and-false-private-helper", lambda source: _p2_transformed_comparison_helper(source, "_p2_inner_differs(actual, expected) and False"), _p2_owned_finding(_P21_KEY_FIELDS)),
    Mutation("required-comparison-cross-paired-dead-helper", _p2_cross_paired_dead_helper, _p2_owned_finding(_P21_KEY_FIELDS)), _p2_owned_case("oracle-group-boolop-empty", "_predicate_3o_2_1", "        for label, actual_oracle_key_id in actual_oracle_key_ids:", "        actual_oracle_key_ids = actual_oracle_key_ids and ()\n        for label, actual_oracle_key_id in actual_oracle_key_ids:", _P21_SELECTOR_KEY),
    _p2_owned_case("oracle-group-conditional-join", "_predicate_3o_2_1", "        for label, actual_oracle_key_id in actual_oracle_key_ids:", "        if selector_result is None:\n            selected_group = actual_oracle_key_ids\n        else:\n            selected_group = ()\n        for label, actual_oracle_key_id in selected_group:", _P21_SELECTOR_KEY), _p2_owned_case("oracle-group-try-join", "_predicate_3o_2_1", "        for label, actual_oracle_key_id in actual_oracle_key_ids:", "        try:\n            1 / 0\n            selected_group = actual_oracle_key_ids\n        except ZeroDivisionError:\n            selected_group = ()\n        for label, actual_oracle_key_id in selected_group:", _P21_SELECTOR_KEY),
    _p2_owned_case("oracle-group-empty-loop-alias", "_predicate_3o_2_1", "        for label, actual_oracle_key_id in actual_oracle_key_ids:", "        selected_group = ()\n        for _ in ():\n            selected_group = actual_oracle_key_ids\n        for label, actual_oracle_key_id in selected_group:", _P21_SELECTOR_KEY), _p2_owned_case("oracle-group-nonempty-loop-rebind", "_predicate_3o_2_1", "        for label, actual_oracle_key_id in actual_oracle_key_ids:", "        selected_group = actual_oracle_key_ids\n        for selected_group in ((),):\n            pass\n        for label, actual_oracle_key_id in selected_group:", _P21_SELECTOR_KEY),
    _p2_owned_case("oracle-group-augassign-empty", "_predicate_3o_2_1", "        for label, actual_oracle_key_id in actual_oracle_key_ids:", "        actual_oracle_key_ids *= 0\n        for label, actual_oracle_key_id in actual_oracle_key_ids:", _P21_SELECTOR_KEY), _p2_owned_case("oracle-group-boolop-payload-substitution", "_predicate_3o_2_1", "                (label, actual_oracle_key_id),", "                (label, actual_oracle_key_id and projection_oracle_key_id),", _P21_SELECTOR_KEY),
    _p2_owned_case("oracle-group-ifexp-payload-substitution", "_predicate_3o_2_1", "                (label, actual_oracle_key_id),", '                (label, actual_oracle_key_id if label == "projection" else projection_oracle_key_id),', _P21_SELECTOR_KEY), Mutation("key-fields-comparison-empty-for", lambda source: _p2_empty_loop_comparison(source, "_predicate_3o_2_1", _P2_KEY_COMPARISON), _p2_owned_finding(_P21_KEY_FIELDS)),
    Mutation("oracle-group-comparison-empty-for", lambda source: _p2_empty_loop_comparison(source, "_predicate_3o_2_1", _P2_ORACLE_COMPARISON), _p2_owned_finding(_P21_SELECTOR_KEY)), Mutation("observation-comparison-empty-for", lambda source: _p2_empty_loop_comparison(source, "_predicate_3o_3_1", _P2_OBSERVATION_COMPARISON), _p2_owned_finding(_P31_OBSERVATION)),
    Mutation("digest-group-comparison-empty-for", lambda source: _p2_empty_loop_comparison(source, "_predicate_3o_3_1", '            if actual_digest != expected_digest:\n                return _outcome_failure(\n                    f"source observation[{observation_index}] "\n                    f"{label} outcome digest differs"\n                )'), _p2_owned_finding(_P31_SELECTOR_DIGEST)), _p2_owned_case("key-fields-range-break", "_predicate_3o_2_1", _P2_KEY_COMPARISON, _P2_KEY_COMPARISON + "\n            break", _P21_KEY_FIELDS),
    _p2_owned_case("oracle-observation-range-break", "_predicate_3o_2_1", "    return None", "        break\n    return None", _P21_PROJECTION_KEY), _p2_owned_case("outcome-observation-range-break", "_predicate_3o_3_1", "    return None", "        break\n    return None", _P31_OBSERVATION), _p2_owned_case("carrier-exact-validator-bypassed", "_validate_source_observation_key_surface", "    key_fields = _source_key_fields(projection.key_fields)", "    key_fields = projection.key_fields", _P21_KEY_FIELDS), _p2_owned_case("owned-predicate-dead-yield", "_predicate_3o_2_1", "    return None", "    yield None\n    return None", _P21_KEY_FIELDS), Mutation("nested-field-index-cross-correlation", lambda source: _mutate_guard_function_reference(source, "_predicate_3o_2_1", _P2_KEY_COMPARISON, '            for other_field_index in range(8):\n                if key_fields[field_index] != expected_key_fields[other_field_index]:\n                    return _oracle_key_failure("nested field mismatch")'), _p2_owned_finding(_P21_KEY_FIELDS)), Mutation("nested-observation-index-cross-correlation", lambda source: _mutate_guard_function_reference(source, "_predicate_3o_3_1", _P2_OBSERVATION_RECOMPUTATION, '            for other_observation_index in range(10):\n                expected_f64 = _expected_observation_f64(selection, other_observation_index, world)'), _p2_owned_finding(_P31_OBSERVATION)), _p2_owned_case("owned-failure-helper-falsey", "_oracle_key_failure", '    return "CALIBRATION_ORACLE_KEY_ID_MISMATCH", detail', "    return None", _P21_KEY_FIELDS), Mutation("decorated-p2-outcome", lambda source: source.replace("def _p2_outcome(failure, predicate_index, selection_index, p1_counts, p2_counts):", "@staticmethod\ndef _p2_outcome(failure, predicate_index, selection_index, p1_counts, p2_counts):", 1), _p2_owned_finding(_P21_KEY_FIELDS)), Mutation("schedule-predicate-result-swallowed", lambda source: _mutate_guard_function_reference(source, "_validate_stage2f_p2", "        if failure := _predicate_3o_2_1(\n            selections[index], p2_selections[index]\n        ):", "        if (failure := _predicate_3o_2_1(\n            selections[index], p2_selections[index]\n        )) and False:"), architecture.Finding("p2-schedule", "predicate-family-major")), Mutation("schedule-predicate-arguments-crossed", lambda source: _mutate_guard_function_reference(source, "_validate_stage2f_p2", "        if failure := _predicate_3o_2_1(\n            selections[index], p2_selections[index]\n        ):", "        if failure := _predicate_3o_2_1(\n            p2_selections[index], selections[index]\n        ):"), architecture.Finding("p2-schedule", "predicate-family-major")), Mutation("producer-oracle-signature-drift", lambda source: source.replace("def _oracle_key_id(key_fields):", "def _oracle_key_id(key_fields, trap=None):", 1), architecture.Finding("p2-owned-function-authority", "_oracle_key_id")), Mutation("producer-coordinate-body-drift", lambda source: _insert_p2_statement(source, "_expected_source_coordinate", "return selection[0]"), architecture.Finding("p2-owned-function-authority", "_expected_source_coordinate")), Mutation("final-owned-binding-rebound", lambda source: source + "\n_p2_outcome = lambda *args: None\n", architecture.Finding("p2-owned-function-authority", "_p2_outcome")), Mutation("conditional-owned-binding-rebound", lambda source: source + "\nif _condition:\n    _p2_outcome = lambda *args: None\n", architecture.Finding("p2-owned-function-authority", "_p2_outcome")), Mutation("final-owned-binding-deleted", lambda source: source + "\ndel _p2_outcome\n", architecture.Finding("p2-owned-function-authority", "_p2_outcome")), Mutation("schedule-loop-target-shadows-live-parameter", lambda source: source.replace("for index in range(_CANONICAL_SELECTION_COUNT):\n        count_0", "for selections in range(_CANONICAL_SELECTION_COUNT):\n        count_0", 1), architecture.Finding("p2-schedule", "predicate-family-major")), Mutation("schedule-walrus-target-shadows-live-count", lambda source: source.replace("if failure := _predicate_3o_2_1(", "if p1_counts := _predicate_3o_2_1(", 1), architecture.Finding("p2-schedule", "predicate-family-major")), Mutation("schedule-dispatch-selection-index-corrupted", lambda source: source.replace("_p2_outcome(failure, 1, index, p1_counts", "_p2_outcome(failure, 1, selections, p1_counts", 1), architecture.Finding("p2-schedule", "predicate-family-major")), Mutation("schedule-predicate-signature-drift", lambda source: source.replace("def _predicate_3o_2_1(selection, p2_selection):", "def _predicate_3o_2_1(selection, p2_selection, trap=None):", 1), architecture.Finding("p2-schedule", "predicate-family-major")), Mutation("schedule-validator-signature-drift", lambda source: source.replace("    expected_predecessors,\n):", "    expected_predecessors,\n    trap=None,\n):", 1), architecture.Finding("p2-schedule", "predicate-family-major")), Mutation("schedule-trailing-raise-before-success", lambda source: source.replace("    return None, (*p1_counts, count_0, count_1, count_2, count_3)", "    raise RuntimeError\n    return None, (*p1_counts, count_0, count_1, count_2, count_3)", 1), architecture.Finding("p2-schedule", "predicate-family-major")), Mutation("owned-predicate-trailing-while", lambda source: _mutate_guard_function_reference(source, "_predicate_3o_2_1", "    return None", "    while True:\n        pass\n    return None"), _p2_owned_finding(_P21_KEY_FIELDS)), Mutation("owned-module-abrupt-raise", lambda source: "raise RuntimeError\n" + source, _p2_owned_finding(_P21_KEY_FIELDS)), _p2_owned_case("owned-failure-detail-trap", "_predicate_3o_2_1", '                    f"source observation[{observation_index}] "\n                    f"key_fields[{field_index}] differs"', "                    1 / 0", _P21_KEY_FIELDS), _p2_owned_case("owned-validator-label-trap", "_predicate_3o_2_1", '                    f"{label}.oracle_key_id",', "                    1 / 0,", _P21_SELECTOR_KEY),
)
def _p2_owned_private_helper(source: str) -> str:
    source = _mutate_guard_function_reference(source, "_predicate_3o_2_1", "key_fields[field_index] != expected_key_fields[field_index]", "_p2_owned_differs(key_fields[field_index], expected_key_fields[field_index])")
    return "def _p2_owned_differs_inner(actual, expected):\n    return actual != expected\n\ndef _p2_owned_differs(actual, expected):\n    return _p2_owned_differs_inner(actual, expected)\n\n" + source
def _p2_owned_alias(source: str, *, hops: int) -> str:
    aliases = "        expected_1 = expected_key_fields\n"
    expected = "expected_1"
    if hops == 2:
        aliases += "        expected_2 = expected_1\n"
        expected = "expected_2"
    source = _mutate_guard_function_reference(source, "_predicate_3o_2_1", "        for field_index in range(8):", aliases + "        for field_index in range(8):")
    return _mutate_guard_function_reference(source, "_predicate_3o_2_1", "expected_key_fields[field_index]", f"{expected}[field_index]")
_ACTIVE_P2_OWNED_DATAFLOW_BENIGN_CASES = (
    ("valid-private-helper-comparison", _p2_owned_private_helper),
    ("valid-one-hop-expected-value-alias", lambda source: _p2_owned_alias(source, hops=1)),
    ("valid-two-hop-expected-value-alias", lambda source: _p2_owned_alias(source, hops=2)),
    ("unrelated-local-comparisons", lambda source: _insert_p2_statement(source, "_predicate_3o_2_1", "unrelated_left = 1\nunrelated_right = 2\n_ = unrelated_left != unrelated_right")),
    ("comments-docstrings-inert-statements", lambda source: _insert_p2_statement(source, "_predicate_3o_2_1", '"owned-dataflow inert statement"\npass')),
    ("allowed-stage-local-temporary", lambda source: _mutate_guard_function_reference(source, "_predicate_3o_2_1", "        for field_index in range(8):", "        stage_local_expected = expected_key_fields\n        _ = stage_local_expected\n        for field_index in range(8):")),
    ("valid-aliased-producer-call-arguments", _p2_alias_producer_arguments),
    ("valid-private-helper-oracle-key-producer", _p2_private_oracle_key_producer),
    ("valid-field-index-alpha-renaming", lambda source: _p2_replace_owner_all(source, "_predicate_3o_2_1", "field_index", "position")),
    ("valid-observation-index-alpha-renaming", lambda source: _p2_replace_owner_all(source, "_predicate_3o_2_1", "observation_index", "source_index")),
    ("valid-oracle-group-augassign-noop", lambda source: _mutate_guard_function_reference(source, "_predicate_3o_2_1", "        for label, actual_oracle_key_id in actual_oracle_key_ids:", "        actual_oracle_key_ids += ()\n        for label, actual_oracle_key_id in actual_oracle_key_ids:")),
)


_ACTIVE_P2_PROJECTION_CASES = _p2_mutations("p2-source-projection-shape", "CalibrationSourceObservationProjection", (
    ("source-projection-not-frozen", "@_dataclass(frozen=True, slots=True)\nclass CalibrationSourceObservationProjection:", "@_dataclass(frozen=False, slots=True)\nclass CalibrationSourceObservationProjection:"),
    ("source-projection-not-slotted", "@_dataclass(frozen=True, slots=True)\nclass CalibrationSourceObservationProjection:", "@_dataclass(frozen=True, slots=False)\nclass CalibrationSourceObservationProjection:"),
    ("source-projection-fields-reordered", "    candidate_id: str\n    comparison_group_id: str", "    comparison_group_id: str\n    candidate_id: str"),
    ("source-projection-extra-field", "    z: str\n\n    def __post_init__", "    z: str\n    extra: str\n\n    def __post_init__"),
))
_ACTIVE_P2_IDENTITY_CASES = _p2_mutations("p2-source-identity", "preimage", (
    ("source-identity-wrong-domain", '"validation_evidence_calibration_source_observation/v1",\n        _source_observation_preimage(projection),', '"validation_evidence_calibration_source_observation/v2",\n        _source_observation_preimage(projection),'),
    ("source-identity-bypasses-preimage", "_source_observation_preimage(projection),", "projection,"),
    ("source-preimage-bypasses-mapper", "mapping = _calibration_source_observation_mapping(projection)", "mapping = _source_mapping(projection)"),
    ("source-preimage-bypasses-decoder", "decoded = _decode_calibration_source_observation_projection(mapping)", "decoded = projection"),
))
_ACTIVE_P2_SCHEDULE_CASES = _p2_mutations("p2-schedule", "predicate-family-major", (
    ("schedule-first-family-replaced", "failure := _predicate_3o_2_0(", "failure := _predicate_3o_2_1("),
    ("schedule-second-family-replaced", "failure := _predicate_3o_2_1(", "failure := _predicate_3o_3_1("),
    ("schedule-third-family-replaced", "failure := _predicate_3o_3_1(", "failure := _predicate_3o_4_1("),
    ("schedule-noncanonical-first-range", "for index in range(_CANONICAL_SELECTION_COUNT):\n        count_0", "for index in range(317):\n        count_0"),
    ("schedule-removes-p1-predecessor", "p1_failure, p1_counts = _validate_stage2f_p1(", "p1_failure, p1_counts = _missing_stage2f_p1("),
))
_ACTIVE_P2_FAILURE_SURFACE_CASES = (
    *_p2_mutations("p2-failure-paths", "ordered-paths", (("wrong-p2-failure-path", '"calibration/3o.3.1/outcome"', '"calibration/3o.3.2/outcome"'),)),
    *_p2_mutations("p2-failure-codes", "complete-set", (("missing-p2-failure-code", '"CALIBRATION_OUTCOME_DIGEST_MISMATCH"', '"CALIBRATION_OUTCOME_MISMATCH"'),)),
)

def _p2_pure_helper_mutation(local_name: str, qualified_target: str) -> Mutation:
    old = f"{local_name}("
    return Mutation(f"required-pure-helper-{local_name.lstrip('_')}", lambda source: source.replace(old, f"_missing_{old[1:]}"), architecture.Finding("p2-required-pure-helper", qualified_target))

_ACTIVE_P2_PURE_HELPER_CASES = tuple(_p2_pure_helper_mutation(local, target) for local, target in (
    ("_parse_calibration_candidate", f"{architecture._ORACLE}._parse_calibration_candidate"),
    ("_calibration_key", f"{architecture._ORACLE}.calibration_key"),
    ("_transform_key", f"{architecture._ORACLE}.transform_key"),
    ("_f64", f"{architecture._PROTOCOL}.f64"),
    ("_hidden_arm_mean", f"{architecture._WORLDS}.hidden_arm_mean"),
    ("_hidden_observation_sigma", f"{architecture._WORLDS}.hidden_observation_sigma"),
))
_ACTIVE_P2_OWNERSHIP_CASES = (
    Mutation("ownership-3o21-direct-complete-decoder", lambda source: _insert_p2_statement(source, "_predicate_3o_2_1", "_decode_calibration_source_observation_projection(p2_selection[1][0][0])"), architecture.Finding("p2-predicate-ownership", "_predicate_3o_2_1:_decode_calibration_source_observation_projection")),
    Mutation("ownership-3o21-helper-complete-decoder", lambda source: _insert_p2_statement(source, "_predicate_3o_2_1", "def complete(value: object) -> object:\n    return _decode_calibration_source_observation_projection(value)\ncomplete(p2_selection[1][0][0])"), architecture.Finding("p2-predicate-ownership", "_predicate_3o_2_1:_decode_calibration_source_observation_projection")),
    Mutation("ownership-3o21-one-hop-decoder-alias", lambda source: _insert_p2_statement(source, "_predicate_3o_2_1", "decoder = _decode_calibration_source_observation_projection\ndecoder(p2_selection[1][0][0])"), architecture.Finding("p2-predicate-ownership", "_predicate_3o_2_1:_decode_calibration_source_observation_projection")),
    Mutation("ownership-3o21-two-hop-decoder-alias", lambda source: _insert_p2_statement(source, "_predicate_3o_2_1", "decoder = _decode_calibration_source_observation_projection\nalias = decoder\nalias(p2_selection[1][0][0])"), architecture.Finding("p2-predicate-ownership", "_predicate_3o_2_1:_decode_calibration_source_observation_projection")),
    Mutation("ownership-3o31-direct-complete-decoder", lambda source: _insert_p2_statement(source, "_predicate_3o_3_1", "_decode_calibration_source_observation_projection(p2_selection[1][0][0])"), architecture.Finding("p2-predicate-ownership", "_predicate_3o_3_1:_decode_calibration_source_observation_projection")),
    Mutation("ownership-3o21-serialized-key-hex", lambda source: _insert_p2_statement(source, "_predicate_3o_2_1", "projection = _require_exact_source_observation_object(p2_selection[1][0][0])\nprojection.serialized_key_hex"), architecture.Finding("p2-predicate-ownership", "_predicate_3o_2_1:serialized_key_hex")),
    Mutation("ownership-3o21-seed", lambda source: _insert_p2_statement(source, "_predicate_3o_2_1", "_p2_later_field(evidence[0])") + "\n\ndef _p2_later_field(value: object) -> object:\n    checked = _require_exact_source_observation_object(value)\n    return checked.seed\n", architecture.Finding("p2-predicate-ownership", "_predicate_3o_2_1:seed")),
    Mutation("ownership-3o21-narrow-helper-seed", lambda source: _insert_p2_statement(source, "_predicate_3o_2_1", "_p2_later_narrow_field(p2_selection[1][0][0])") + "\n\ndef _p2_later_narrow_field(value: object) -> object:\n    result = _validate_source_observation_key_surface(value)\n    checked = result[0]\n    return checked.seed\n", architecture.Finding("p2-predicate-ownership", "_predicate_3o_2_1:seed")),
    Mutation("ownership-3o21-getattr-seed", lambda source: _insert_p2_statement(source, "_predicate_3o_2_1", "_p2_dynamic_later_field(p2_selection[1][0][0])") + "\n\ndef _p2_dynamic_later_field(value: object) -> object:\n    return getattr(value, 'seed')\n", architecture.Finding("p2-predicate-ownership", "_predicate_3o_2_1:dynamic-field-access")),
    Mutation("ownership-3o31-schema-version", lambda source: _insert_p2_statement(source, "_predicate_3o_3_1", "projection = _require_exact_source_observation_object(p2_selection[1][0][0])\nprojection.schema_version"), architecture.Finding("p2-predicate-ownership", "_predicate_3o_3_1:schema_version")),
    Mutation("ownership-3o21-source-identity", lambda source: _insert_p2_statement(source, "_predicate_3o_2_1", "source_observation_identity(p2_selection[1][0][0])"), architecture.Finding("p2-predicate-ownership", "_predicate_3o_2_1:source_observation_identity")),
    Mutation("ownership-3o31-source-identity", lambda source: _insert_p2_statement(source, "_predicate_3o_3_1", "source_observation_identity(p2_selection[1][0][0])"), architecture.Finding("p2-predicate-ownership", "_predicate_3o_3_1:source_observation_identity")),
    Mutation("ownership-3o21-full-projection-equality", lambda source: _insert_p2_statement(source, "_predicate_3o_2_1", "left_projection = _require_exact_source_observation_object(p2_selection[1][0][0])\nright_projection = _require_exact_source_observation_object(p2_selection[1][0][0])\nif left_projection == right_projection:\n    pass"), architecture.Finding("p2-predicate-ownership", "_predicate_3o_2_1:full-projection-equality")),
    Mutation("ownership-3o31-invokes-3o41", lambda source: _insert_p2_statement(source, "_predicate_3o_3_1", "_predicate_3o_4_1(selection, p2_selection, expected_predecessor)"), architecture.Finding("p2-predicate-ownership", "_predicate_3o_3_1:_predicate_3o_4_1")),
    Mutation("ownership-global-complete-preflight", lambda source: _insert_p2_statement(source, "_validate_stage2f_p2", "_p2_global_preflight(p2_selections[0][1][0][0])") + "\n\ndef _p2_global_preflight(value: object) -> object:\n    return _validate_complete_source_observation_surface(value)\n", architecture.Finding("p2-predicate-ownership", "_validate_stage2f_p2:preflight")),
    Mutation("ownership-early-error-relabel", lambda source: _insert_p2_statement(source, "_predicate_3o_2_1", "try:\n    _decode_calibration_source_observation_projection(p2_selection[1][0][0])\nexcept ValueError:\n    return _oracle_key_failure('relabel')"), architecture.Finding("p2-predicate-ownership", "_predicate_3o_2_1:error-relabel")),
)
_ACTIVE_P2_ORDER_CASES = (
    Mutation("order-serialized-key-before-candidate", _alias_p2_comparison_precedence, architecture.Finding("p2-source-comparison-order", "declaration-order")),
    Mutation("order-adjacent-group-digest-swap", lambda source: _swap_p2_comparisons(source, "comparison_group_id", "digest"), architecture.Finding("p2-source-comparison-order", "declaration-order")),
    Mutation("order-omit-z-comparison", lambda source: _omit_p2_comparison(source, "z"), architecture.Finding("p2-source-comparison-order", "declaration-order")),
    Mutation("order-duplicate-u-comparison", lambda source: _duplicate_p2_comparison(source, "u"), architecture.Finding("p2-source-comparison-order", "declaration-order")),
    Mutation("order-identity-before-complete-comparison", lambda source: _mutate_guard_function_reference(source, "_predicate_3o_4_1", "            mismatch = _first_source_mismatch(evidence[0], expected_projection)", "            _p2_early_identity(evidence[0])\n            mismatch = _first_source_mismatch(evidence[0], expected_projection)") + "\n\ndef _p2_early_identity(value: CalibrationSourceObservationProjection) -> str:\n    return source_observation_identity(value)\n", architecture.Finding("p2-source-comparison-order", "declaration-order")),
    Mutation("order-uniqueness-before-ten-identities", lambda source: _mutate_guard_function_reference(source, "_predicate_3o_4_1", "        identities = (*identities, carried_identity)", "        identities = (*identities, carried_identity)\n        seen = identities\n        if len(set(seen)) != len(seen):\n            return _source_observation_failure('early duplicate')"), architecture.Finding("p2-source-comparison-order", "declaration-order")),
    Mutation("order-broad-equality-replaces-comparison", lambda source: _replace_guard_once(source, "            mismatch = _first_source_mismatch(evidence[0], expected_projection)", "            projection = _require_exact_source_observation_object(evidence[0])\n            mismatch = None if projection == expected_projection else 'projection'"), architecture.Finding("p2-source-comparison-order", "declaration-order")),
    Mutation("order-dynamic-field-dispatch", lambda source: _insert_p2_statement(source, "_first_source_mismatch", "field_name = projection.key_fields[0]\ngetattr(projection, field_name)"), architecture.Finding("p2-source-comparison-order", "declaration-order")),
    Mutation("order-dictionary-iteration", lambda source: _insert_p2_statement(source, "_first_source_mismatch", "for field_name in {'candidate_id': 0}:\n    _ = field_name"), architecture.Finding("p2-source-comparison-order", "declaration-order")),
    Mutation("order-source-controlled-iteration", lambda source: _insert_p2_statement(source, "_first_source_mismatch", "for field_name in projection.key_fields:\n    _ = field_name"), architecture.Finding("p2-source-comparison-order", "declaration-order")),
    Mutation("order-first-mismatch-early-success", lambda source: _insert_p2_statement(source, "_first_source_mismatch", "return None"), architecture.Finding("p2-source-comparison-order", "declaration-order")),
    Mutation("order-candidate-false-and-decoy", lambda source: _mutate_guard_function_reference(source, "_first_source_mismatch", "type(projection.candidate_id) is not str or projection.candidate_id != expected.candidate_id", "False and (type(projection.candidate_id) is not str or projection.candidate_id != expected.candidate_id)"), architecture.Finding("p2-source-comparison-order", "declaration-order")),
    Mutation("order-3o41-comparison-wrong-argument", lambda source: _mutate_guard_function_reference(source, "_predicate_3o_4_1", "_first_source_mismatch(evidence[0], expected_projection)", "_first_source_mismatch(expected_projection, expected_projection)"), architecture.Finding("p2-source-comparison-order", "declaration-order")),
)
_ACTIVE_P2_PERFORMANCE_CASES = (
    Mutation("performance-process-global-identity-cache", lambda source: source + "\n_SOURCE_IDENTITY_CACHE = dict()\n", architecture.Finding("p2-performance-invariant", "cold-minimal")),
    Mutation("performance-hard-coded-valid-identity", lambda source: _insert_p2_statement(source, "source_observation_identity", "return 'ad3fde45e1a22867d68f381eac353e0074f2bb0a27858781d574b506782d1c4b'"), architecture.Finding("p2-performance-invariant", "cold-minimal")),
    Mutation("performance-mutable-module-fixture", lambda source: source + "\n_SOURCE_OBSERVATION_FIXTURE = list()\n", architecture.Finding("p2-performance-invariant", "cold-minimal")),
    Mutation("performance-import-time-bundle-construction", lambda source: source + "\ndef _make_items():\n    return tuple(range(318))\n_IMPORT_ITEMS = _make_items()\n", architecture.Finding("p2-performance-invariant", "cold-minimal")),
    Mutation("performance-import-time-oracle-world-enumeration", lambda source: source + "\nimport research_decision_engine.benchmarks.broader_oracle as delayed_oracle\n_IMPORT_WORLD = delayed_oracle.enumerate_worlds()\n", architecture.Finding("p2-performance-invariant", "cold-minimal")),
    Mutation("performance-environment-sensitive-import", lambda source: source + "\nimport os\n_IMPORT_CHOICE = os.getenv('RDE_IMPORT_CHOICE')\n", architecture.Finding("p2-performance-invariant", "cold-minimal")),
    Mutation("performance-source-controlled-dynamic-import", lambda source: source + "\n_IMPORTED = __import__(_module_name)\n", architecture.Finding("p2-performance-invariant", "cold-minimal")),
    Mutation("performance-skip-strict-complete-decoder", lambda source: _mutate_guard_function_reference(source, "_validate_complete_source_observation_surface", "    mapping = _calibration_source_observation_mapping(projection)\n    decoded = _decode_calibration_source_observation_projection(mapping)\n    if decoded != projection:\n        _reject(\"source_observation\", \"projection does not exactly reconstruct\")\n    return mapping", "    return {}"), architecture.Finding("p2-performance-invariant", "cold-minimal")),
)
_ACTIVE_P2_OPERATION_CASES = (
    Mutation("ownership-3o21-missing-oracle-key-recompute", lambda source: _mutate_guard_function_reference(source, "_predicate_3o_2_1", "_oracle_key_id(  # type: ignore[no-untyped-call]", "_missing_oracle_key_id(  # type: ignore[no-untyped-call]"), architecture.Finding("p2-predicate-ownership", "_predicate_3o_2_1:oracle-key-recompute")),
    Mutation("ownership-3o31-missing-selected-only-reconstruction", lambda source: _mutate_guard_function_reference(source, "_predicate_3o_3_1", "expected_f64 = _expected_observation_f64(", "expected_f64 = _missing_expected_observation_f64("), architecture.Finding("p2-predicate-ownership", "_predicate_3o_3_1:selected-only-reconstruction")),
    Mutation("ownership-3o31-missing-outcome-digest-recompute", lambda source: _mutate_guard_function_reference(source, "_predicate_3o_3_1", "expected_digest = _outcome_digest(", "expected_digest = _missing_outcome_digest("), architecture.Finding("p2-predicate-ownership", "_predicate_3o_3_1:outcome-digest-recompute")),
    Mutation("ownership-3o21-early-success", lambda source: _insert_p2_statement(source, "_predicate_3o_2_1", "return None"), architecture.Finding("p2-predicate-ownership", "_predicate_3o_2_1:control-flow")),
)
# fmt: on


def test_active_p2_repository_surface_is_exact_and_bounded() -> None:
    started = time.perf_counter()
    sources = _production_sources()
    sources[architecture.CANONICAL_MODULE] = _active_p2_source()
    findings = architecture.repository_findings(sources, architecture.P2_MANIFEST)
    runtime = time.perf_counter() - started
    assert findings == ()
    assert runtime < 60.0


def test_active_p2_internal_contract_is_exact() -> None:
    focused = tuple((case_id, frozenset(case.expected for case in cases if case.expected.code != "p2-owned-function-authority") & architecture._active_p2_internal_findings(source)) for case_id, source, cases in (("projection", _FOCUSED_P2_PROJECTION_SOURCE, _ACTIVE_P2_PROJECTION_CASES), ("identity", _FOCUSED_P2_IDENTITY_SOURCE, _ACTIVE_P2_IDENTITY_CASES), ("schedule", _FOCUSED_P2_SCHEDULE_SOURCE, _ACTIVE_P2_SCHEDULE_CASES), ("pure-helper", _FOCUSED_P2_PURE_HELPER_SOURCE, _ACTIVE_P2_PURE_HELPER_CASES), ("failure", _FOCUSED_P2_FAILURE_SOURCE, _ACTIVE_P2_FAILURE_SURFACE_CASES), ("owned", _FOCUSED_P2_OWNED_SOURCE, (*_ACTIVE_P2_OWNERSHIP_CASES, *_ACTIVE_P2_OPERATION_CASES, *_ACTIVE_P2_OWNED_DATAFLOW_CASES)), ("order", _FOCUSED_P2_ORDER_SOURCE, _ACTIVE_P2_ORDER_CASES), ("performance", _FOCUSED_P2_PERFORMANCE_SOURCE, _ACTIVE_P2_PERFORMANCE_CASES)))  # fmt: skip
    assert all(not overlap for _case_id, overlap in focused), focused


def test_active_p2_harness_is_fixture_only_and_identity_independent() -> None:
    source = _active_p2_harness_source()
    assert architecture.harness_findings(source) == ()


def _p2_case_is_attributed(case: Mutation, source: str) -> bool:
    return case.expected in architecture._active_p2_internal_findings(case.mutate(source))


def _p2_owned_dataflow_findings(source: str) -> set[architecture.Finding]:
    facts = architecture._AnalysisSession().source_analysis(source, module_name=architecture.CANONICAL_MODULE, owned=True)  # fmt: skip
    return architecture._p2_owned_dataflow_findings(facts)


# fmt: off
@pytest.mark.parametrize("case", _ACTIVE_P2_PROJECTION_CASES, ids=[case.id for case in _ACTIVE_P2_PROJECTION_CASES])
def test_active_p2_source_projection_violation_is_attributed(case: Mutation) -> None:
    assert _p2_case_is_attributed(case, _FOCUSED_P2_PROJECTION_SOURCE)

@pytest.mark.parametrize("case", _ACTIVE_P2_IDENTITY_CASES, ids=[case.id for case in _ACTIVE_P2_IDENTITY_CASES])
def test_active_p2_source_identity_violation_is_attributed(case: Mutation) -> None:
    assert _p2_case_is_attributed(case, _FOCUSED_P2_IDENTITY_SOURCE)

@pytest.mark.parametrize("case", _ACTIVE_P2_SCHEDULE_CASES, ids=[case.id for case in _ACTIVE_P2_SCHEDULE_CASES])
def test_active_p2_schedule_violation_is_attributed(case: Mutation) -> None:
    assert _p2_case_is_attributed(case, _FOCUSED_P2_SCHEDULE_SOURCE)

@pytest.mark.parametrize("case", _ACTIVE_P2_PURE_HELPER_CASES, ids=[case.id for case in _ACTIVE_P2_PURE_HELPER_CASES])
def test_active_p2_pure_helper_violation_is_attributed(case: Mutation) -> None:
    assert _p2_case_is_attributed(case, _FOCUSED_P2_PURE_HELPER_SOURCE)

@pytest.mark.parametrize("case", _ACTIVE_P2_FAILURE_SURFACE_CASES, ids=[case.id for case in _ACTIVE_P2_FAILURE_SURFACE_CASES])
def test_active_p2_failure_surface_violation_is_attributed(case: Mutation) -> None:
    assert _p2_case_is_attributed(case, _FOCUSED_P2_FAILURE_SOURCE)

@pytest.mark.parametrize("case", _ACTIVE_P2_OWNERSHIP_CASES, ids=[case.id for case in _ACTIVE_P2_OWNERSHIP_CASES])
def test_active_p2_predicate_ownership_violation_is_attributed(case: Mutation) -> None:
    assert _p2_case_is_attributed(case, _FOCUSED_P21_OWNED_SOURCE if case.id in {"ownership-3o21-helper-complete-decoder", "ownership-3o21-serialized-key-hex", "ownership-3o21-seed", "ownership-3o21-narrow-helper-seed", "ownership-3o21-getattr-seed", "ownership-3o21-full-projection-equality"} else _FOCUSED_P31_OWNED_SOURCE if case.id == "ownership-3o31-schema-version" else _FOCUSED_P2_OWNED_SOURCE)

@pytest.mark.parametrize("case", _ACTIVE_P2_OPERATION_CASES, ids=[case.id for case in _ACTIVE_P2_OPERATION_CASES])
def test_active_p2_owned_operation_violation_is_attributed(case: Mutation) -> None:
    assert _p2_case_is_attributed(case, _FOCUSED_P2_OWNED_SOURCE)

@pytest.mark.parametrize("case", _ACTIVE_P2_ORDER_CASES, ids=[case.id for case in _ACTIVE_P2_ORDER_CASES])
def test_active_p2_source_order_violation_is_attributed(case: Mutation) -> None:
    assert _p2_case_is_attributed(case, _FOCUSED_P2_ORDER_SOURCE)

@pytest.mark.parametrize("case", _ACTIVE_P2_PERFORMANCE_CASES, ids=[case.id for case in _ACTIVE_P2_PERFORMANCE_CASES])
def test_active_p2_performance_violation_is_attributed(case: Mutation) -> None:
    assert _p2_case_is_attributed(case, _FOCUSED_P2_PERFORMANCE_SOURCE)
@pytest.mark.parametrize("case", _ACTIVE_P2_OWNED_DATAFLOW_CASES, ids=[case.id for case in _ACTIVE_P2_OWNED_DATAFLOW_CASES])
def test_active_p2_owned_dataflow_violation_is_independently_attributed(case: Mutation) -> None: source = _guard_source_function_block(_active_p2_source(), case.expected.detail) if case.expected.code == "p2-owned-function-authority" else _FOCUSED_P2_SCHEDULE_SOURCE if case.expected.code == "p2-schedule" else _FOCUSED_P21_OWNED_SOURCE if case.expected.detail.startswith("_predicate_3o_2_1:") else _FOCUSED_P31_OWNED_SOURCE; mutated = case.mutate(source); facts = architecture._AnalysisSession().source_analysis(mutated, module_name=architecture.CANONICAL_MODULE, owned=True) if case.expected.code == "p2-owned-function-authority" else None; assert case.expected in (architecture._p2_owned_function_authority_findings(facts) | architecture._p2_owned_terminal_authority_findings(facts) if facts is not None else architecture._active_p2_internal_findings(mutated) if case.expected.code == "p2-schedule" else _p2_owned_dataflow_findings(mutated))  # noqa: E702
@pytest.mark.parametrize(("case_id", "mutate"), _ACTIVE_P2_OWNED_DATAFLOW_BENIGN_CASES, ids=[case_id for case_id, _mutate in _ACTIVE_P2_OWNED_DATAFLOW_BENIGN_CASES])
def test_active_p2_owned_dataflow_benign_control_is_accepted(case_id: str, mutate: Callable[[str], str]) -> None:
    assert case_id.startswith(("valid-", "unrelated-", "comments-", "allowed-"))
    assert not {finding for finding in _p2_owned_dataflow_findings(mutate(_FOCUSED_P21_OWNED_SOURCE)) if finding.detail.startswith("_predicate_3o_2_1:")}
# fmt: on


def test_active_p2_has_no_p3_or_p4_surface() -> None:
    tree = ast.parse(_active_p2_source())
    names = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    later_names = (
        architecture.P4_MANIFEST.projection_classes - architecture.P2_MANIFEST.projection_classes
    ) | (architecture.P4_MANIFEST.identity_functions - architecture.P2_MANIFEST.identity_functions)
    assert not names & later_names
    assert "_validate_stage2f_p3" not in names
    assert "_validate_stage2f_p4" not in names


def test_active_p2_architecture_node_ledger_is_exact() -> None:
    assert (
        5
        + sum(
            map(
                len,
                (
                    _ACTIVE_P2_PROJECTION_CASES,
                    _ACTIVE_P2_IDENTITY_CASES,
                    _ACTIVE_P2_SCHEDULE_CASES,
                    _ACTIVE_P2_PURE_HELPER_CASES,
                    _ACTIVE_P2_FAILURE_SURFACE_CASES,
                    _ACTIVE_P2_OWNERSHIP_CASES,
                    _ACTIVE_P2_OPERATION_CASES,
                    _ACTIVE_P2_ORDER_CASES,
                    _ACTIVE_P2_PERFORMANCE_CASES,
                ),
            )
        )
        == 67
    )
    assert 67 + len(_ACTIVE_P2_OWNED_DATAFLOW_CASES) + len(_ACTIVE_P2_OWNED_DATAFLOW_BENIGN_CASES) + len(_OWNED_DATAFLOW_MAINTENANCE_CASES) == 234  # fmt: skip


def _active_p3_source() -> str:
    return (_BENCHMARKS / "broader_calibration_evidence.py").read_text(encoding="utf-8")


def _p3_top_level_segment(name: str) -> str:
    source = _active_p3_source()
    node = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name == name
    )
    segment = ast.get_source_segment(source, node)
    assert segment is not None
    decorators = node.decorator_list
    if decorators:
        first_line = min(decorator.lineno for decorator in decorators)
        lines = source.splitlines()
        segment = "\n".join(lines[first_line - 1 : (node.end_lineno or node.lineno)])
    return segment + "\n"


def _swap_once(source: str, first: str, second: str) -> str:
    marker = "__P3_ARCHITECTURE_SWAP__"
    assert marker not in source and first in source and second in source
    return source.replace(first, marker, 1).replace(second, first, 1).replace(marker, second, 1)


def _swap_all(source: str, first: str, second: str) -> str:
    marker = "__P3_ARCHITECTURE_SWAP_ALL__"
    assert marker not in source and first in source and second in source
    return source.replace(first, marker).replace(second, first).replace(marker, second)


def _replace_p3_assignment(source: str, name: str, expression: str) -> str:
    function = cast(ast.FunctionDef, ast.parse(source).body[0])
    assignment = next(
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == name
    )
    assert assignment.end_lineno is not None
    lines = source.splitlines(keepends=True)
    indent = " " * assignment.col_offset
    lines[assignment.lineno - 1 : assignment.end_lineno] = [f"{indent}{name} = {expression}\n"]
    return "".join(lines)


def _move_p3_assignment_before(source: str, name: str, anchor: str) -> str:
    function = cast(ast.FunctionDef, ast.parse(source).body[0])
    assignments = {
        target.id: node
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance((target := node.targets[0]), ast.Name)
        and node.end_lineno is not None
    }
    moved, destination = assignments[name], assignments[anchor]
    assert moved.lineno > destination.lineno and moved.end_lineno is not None
    lines = source.splitlines(keepends=True)
    block = lines[moved.lineno - 1 : moved.end_lineno]
    del lines[moved.lineno - 1 : moved.end_lineno]
    lines[destination.lineno - 1 : destination.lineno - 1] = block
    return "".join(lines)


_P3_PROJECTION_SOURCE = (
    "from dataclasses import dataclass as _dataclass\n\n"
    + _p3_top_level_segment("ScientificCalibrationSelectionProjection")
    + "\ndef _scientific_calibration_selection_mapping(value):\n    return value\n"
)
_P3_INPUT_SOURCE = (
    "from dataclasses import dataclass as _dataclass\n\n"
    "class _ReturnedRunProjection:\n    pass\n\n"
    "class ScientificCalibrationSelectionProjection:\n    pass\n\n"
    + _p3_top_level_segment("_P3SelectionInput")
)
_P3_CODEC_SOURCE = (
    _p3_top_level_segment("_scientific_calibration_selection_mapping")
    + "\n"
    + _p3_top_level_segment("_decode_scientific_calibration_selection_projection")
)
_P3_PREDICATE_SOURCE = _p3_top_level_segment("_predicate_3o_5_1")
_P3_SCHEDULE_SOURCE = (
    "def _validate_stage2f_p2(**kwargs):\n    return None\n\n"
    "def _predicate_3o_5_1(*args):\n    return None\n\n"
    + _p3_top_level_segment("_validate_stage2f_p3")
)


def _p3_projection_shape_is_exact(source: str) -> bool:
    facts = architecture._AnalysisSession().source_analysis(
        source, module_name=architecture.CANONICAL_MODULE
    )
    class_node = next(
        (
            node
            for node in facts.tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "ScientificCalibrationSelectionProjection"
        ),
        None,
    )
    return bool(
        class_node is not None
        and architecture._p1_projection_shape_is_exact(class_node, facts.analysis)
    )


def _p3_input_shape_is_exact(source: str) -> bool:
    facts = architecture._AnalysisSession().source_analysis(
        source, module_name=architecture.CANONICAL_MODULE
    )
    class_node = next(
        (
            node
            for node in facts.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "_P3SelectionInput"
        ),
        None,
    )
    return architecture._p3_private_input_is_exact(class_node, facts.analysis)


def _p3_codec_is_exact(source: str) -> bool:
    functions = {
        node.name: node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)
    }
    return architecture._p3_projection_codec_is_exact(functions)


def _p3_predicate(source: str) -> ast.FunctionDef:
    function = ast.parse(source).body[0]
    assert isinstance(function, ast.FunctionDef)
    return function


def _p3_identity_matches(predicate: ast.FunctionDef) -> frozenset[architecture.RequiredCallMatch]:
    calls = tuple(node for node in ast.walk(predicate) if isinstance(node, ast.Call))
    replay = next(
        call
        for call in calls
        if architecture._call_leaf(call) == "_replay_calibration_history_selection"
    )
    identity = next(call for call in calls if architecture._call_leaf(call) == "_protocol_hash")
    return frozenset(
        {
            architecture.RequiredCallMatch(
                _required_call("calibration_selector_replay"),
                replay.lineno,
                ast.unparse(replay.func),
            ),
            architecture.RequiredCallMatch(
                _required_call("selection_identity"),
                identity.lineno,
                ast.unparse(identity.func),
            ),
        }
    )


def _p3_identity_order_is_exact(source: str) -> bool:
    predicate = _p3_predicate(source)
    return architecture._p3_validation_and_identity_is_exact(
        predicate, _p3_identity_matches(predicate)
    )


def _p3_schedule_is_exact(source: str) -> bool:
    facts = architecture._AnalysisSession().source_analysis(
        source,
        module_name=architecture.CANONICAL_MODULE,
        owned=True,
    )
    return architecture._p3_schedule_is_exact(dict(facts.functions), facts.analysis)


# fmt: off
_ACTIVE_P3_PROJECTION_MUTATIONS = (
    ("p3-projection-missing", lambda source: source.replace("class ScientificCalibrationSelectionProjection:", "class MissingScientificProjection:", 1)),
    ("p3-projection-field-order", lambda source: _swap_once(source, "    comparison_group_id: str", "    ddof: int")),
    ("p3-projection-added-schema", lambda source: source.replace("    def __post_init__", "    schema_version: str\n\n    def __post_init__", 1)),
    ("p3-projection-wrong-annotation", lambda source: source.replace("    ddof: int", "    ddof: bool", 1)),
    ("p3-projection-subclassed", lambda source: source.replace("class ScientificCalibrationSelectionProjection:", "class ScientificCalibrationSelectionProjection(object):", 1)),
    ("p3-projection-dynamic-decorator", lambda source: source.replace("@_dataclass(frozen=True, slots=True)", "@_dataclass(frozen=False, slots=True)", 1)),
)
_ACTIVE_P3_INPUT_MUTATIONS = (
    ("p3-input-missing-returned-result-id", lambda source: source.replace("    returned_result_id: str\n", "", 1)),
    ("p3-input-missing-submitted-job-id", lambda source: source.replace("    submitted_job_id: str\n", "", 1)),
    ("p3-input-field-order", lambda source: _swap_once(source, "    returned_result_id: str", "    returned_run_projection: _ReturnedRunProjection")),
    ("p3-input-wrong-projection-type", lambda source: source.replace("    returned_run_projection: _ReturnedRunProjection", "    returned_run_projection: object", 1)),
    ("p3-input-added-run-id", lambda source: source.replace("    returned_result_id: str", "    returned_result_id: str\n    run_id: str", 1)),
)
_ACTIVE_P3_CODEC_MUTATIONS = (
    ("p3-codec-omit-mapping-field", lambda source: source.replace('        "world_id": world_id,\n', "", 1)),
    ("p3-codec-reorder-mapping-fields", lambda source: _swap_once(source, '        "comparison_group_id": comparison_group_id,', '        "ddof": ddof,')),
    ("p3-codec-reorder-decoder-fields", lambda source: _swap_once(source, "        comparison_group_id=comparison_group_id,", "        ddof=ddof,")),
    ("p3-codec-skip-closed-decoder", lambda source: source.replace("mapping = _closed_mapping(", "mapping = _open_mapping(", 1)),
    ("p3-codec-generic-dict-coercion", lambda source: source.replace("    if type(value) is not dict:", "    value = dict(value)\n    if type(value) is not dict:", 1)),
)
_ACTIVE_P3_WITNESS_MUTATIONS = (
    ("p3-witness-wrong-budget", lambda source: source.replace('"budget-2.25"', '"budget-2.50"', 1)),
    ("p3-witness-wrong-arm", lambda source: source.replace('"calibrated_ig"', '"fixed_adam"', 1)),
    ("p3-witness-cross-role", lambda source: source.replace("validated_returned_results_by_role[role_index]", "validated_returned_results_by_role[0]", 1)),
    ("p3-witness-invented-run-id", lambda source: source.replace("replay_run_id = witness.run_id", "replay_run_id = 'validation-run'", 1)),
    ("p3-witness-delivery-order", lambda source: source.replace("results_in_submission_order", "results_in_delivery_order")),
    ("p3-witness-missing-row-binding", lambda source: source.replace("p3_input.returned_run_projection is not witness", "False", 1)),
    ("p3-witness-missing-job-mapping", lambda source: source.replace("mapping_occurrences != 1", "False", 1)),
)
_ACTIVE_P3_RECONSTRUCTION_MUTATIONS = (
    ("p3-reconstruction-skip-authorization", lambda source: source.replace("_RunObservationAuthorizationProjection(", "_SkippedAuthorization(", 1), True),
    ("p3-reconstruction-skip-oracle-use", lambda source: source.replace("f\"oracle-use/{expected_authorization_id}/{expected_oracle_key_id}\"", "expected_oracle_key_id", 1), True),
    ("p3-reconstruction-sort-observations", lambda source: source.replace("expected_observations=expected_observations,", "expected_observations=sorted(expected_observations),", 1), True),
    ("p3-reconstruction-sort-effects", lambda source: source.replace("expected_effects=expected_effects,", "expected_effects=sorted(expected_effects),", 1), True),
    ("p3-reconstruction-prefilter-history", lambda source: source.replace("range(len(witness.effect_history))", "range(len(recorded_effects))", 1), True),
    ("p3-reconstruction-wrong-observation-order", lambda source: source.replace("for observation_index in range(10)", "for observation_index in reversed(range(10))", 1), True),
    ("p3-reconstruction-wrong-effect-order", lambda source: source.replace("for effect_index in range(5)", "for effect_index in reversed(range(5))", 1), True),
    ("p3-reconstruction-skip-raw-digest", lambda source: source.replace("effect_payload_sha256 = _hashlib.sha256(effect_payload_bytes).hexdigest()", "effect_payload_sha256 = effect_evidence[2]", 1), False),
    ("p3-reconstruction-framed-digest", lambda source: source.replace("_hashlib.sha256(effect_payload_bytes).hexdigest()", "_protocol_hash('effect', effect_payload_bytes)", 1), False),
)
_ACTIVE_P3_IDENTITY_MUTATIONS = (
    ("p3-identity-b-supplies-a", lambda source: _replace_p3_assignment(source, "expected_projection", "actual_helper_result")),
    ("p3-identity-c-supplies-a", lambda source: _replace_p3_assignment(source, "expected_projection", "p3_input.selector_result_projection")),
    ("p3-identity-h-supplies-a", lambda source: _replace_p3_assignment(source, "expected_projection", "selection[16]")),
    ("p3-identity-before-projection", lambda source: _move_p3_assignment_before(source, "expected_selector_result_identity", "expected_projection")),
    ("p3-identity-before-helper-validation", lambda source: _move_p3_assignment_before(source, "expected_selector_result_identity", "historical_selection")),
    ("p3-identity-skip-strict-decoder", lambda source: source.replace("_decode_scientific_calibration_selection_projection(", "_skip_scientific_projection_decoder(", 1)),
    ("p3-identity-b-h-order", lambda source: _swap_once(source, "actual_helper_result.selection_identity", "historical_selection.selection_identity")),
    ("p3-identity-h-d-order", lambda source: _swap_once(source, "historical_selection.selection_identity", "p3_input.selector_result_identity")),
)
_ACTIVE_P3_HELPER_MUTATIONS = (
    ("p3-helper-omit-field-1", "_first_history_nonidentity_mismatch", architecture._P3_HISTORY_NONIDENTITY_FIELDS, "study_id"),
    ("p3-helper-reorder-fields", "_first_history_nonidentity_mismatch", architecture._P3_HISTORY_NONIDENTITY_FIELDS, "world_id"),
    ("p3-helper-skip-physical-cost", "_first_history_nonidentity_mismatch", architecture._P3_HISTORY_NONIDENTITY_FIELDS, "physical_cost"),
    ("p3-helper-skip-exclusion-flag", "_first_history_nonidentity_mismatch", architecture._P3_HISTORY_NONIDENTITY_FIELDS, "future_history_excluded"),
    ("p3-helper-skip-effects", "_first_history_nonidentity_mismatch", architecture._P3_HISTORY_NONIDENTITY_FIELDS, "effects"),
    ("p3-helper-skip-observations", "_first_history_nonidentity_mismatch", architecture._P3_HISTORY_NONIDENTITY_FIELDS, "observations"),
    ("p3-helper-skip-effect-field", "_first_effect_mismatch", architecture._P3_EFFECT_FIELDS, "provenance"),
    ("p3-helper-skip-run-effect-field", "_first_run_effect_mismatch", architecture._P3_EFFECT_FIELDS, "provenance"),
    ("p3-helper-skip-observation-field", "_first_observation_mismatch", architecture._P3_OBSERVATION_FIELDS, "oracle_use_id"),
    ("p3-projection-omit-field-21", "_first_scientific_projection_mismatch", architecture.PROJECTION_FIELDS["ScientificCalibrationSelectionProjection"], "world_id"),
    ("p3-projection-reorder-fields", "_first_scientific_projection_mismatch", architecture.PROJECTION_FIELDS["ScientificCalibrationSelectionProjection"], "ddof"),
)
_ACTIVE_P3_BOUNDARY_NAMES = (
    ("p3-boundary-p4-class", "class CalibrationSelectionProjection:\n    pass\n"),
    ("p3-boundary-p4-identity", "def calibration_selection_id(value):\n    return value\n"),
    ("p3-boundary-3p", "def _predicate_3p_0_0():\n    return None\n"),
    ("p3-boundary-reader", "class _Reader:\n    pass\n"),
    ("p3-boundary-persistence", "def _persistence():\n    return None\n"),
    ("p3-boundary-evidence-writer", "def _evidence_writer():\n    return None\n"),
)
# fmt: on


def _p3_failure_flow_source() -> str:
    field_checks = "\n".join(
        (f"    if actual.{field} != expected.{field}:\n        return {field!r}")
        for field in architecture._P3_HISTORY_NONIDENTITY_FIELDS
    )
    return (
        "def _selector_result_failure(detail):\n"
        "    return detail\n\n"
        "def _first_history_nonidentity_mismatch(\n"
        "    actual, expected, expected_effects, expected_observations, physical_cost\n"
        "):\n"
        f"{field_checks}\n"
        "    return None\n\n"
        "def _predicate_3o_5_1(\n"
        "    selection, p2_selection, expected_predecessor,\n"
        "    expected_execution_attestation_pairs,\n"
        "    attested_execution_specification_ids,\n"
        "    validated_returned_results_by_role, p3_input, selection_index\n"
        "):\n"
        "    helper_mismatch = _first_history_nonidentity_mismatch(actual_helper_result, expected_projection, expected_effects, expected_observations, physical_cost)\n"
        "    if helper_mismatch is not None:\n"
        '        return _selector_result_failure(f"helper.{helper_mismatch} differs")\n'
        "    historical_selection = selection[16]\n"
        "    historical_mismatch = _first_history_nonidentity_mismatch(historical_selection, expected_projection, expected_effects, expected_observations, physical_cost)\n"
        "    if historical_mismatch is not None:\n"
        '        return _selector_result_failure(f"historical.{historical_mismatch} differs")\n'
        "    return None\n\n"
        "def _p3_outcome(failure, selection_index, p2_counts, p3_count):\n"
        "    return failure\n\n"
        "_CANONICAL_SELECTION_COUNT = 318\n\n"
        "def _validate_stage2f_p3(\n"
        "    *, selections, expected_execution_attestation_pairs,\n"
        "    attested_execution_specification_ids, p2_selections,\n"
        "    expected_predecessors, validated_returned_results_by_role, p3_inputs\n"
        "):\n"
        "    p2_counts = ()\n"
        "    p3_count = 0\n"
        "    for selection_index in range(_CANONICAL_SELECTION_COUNT):\n"
        "        failure = _predicate_3o_5_1(selections[selection_index], p2_selections[selection_index], expected_predecessors[selection_index], expected_execution_attestation_pairs, attested_execution_specification_ids, validated_returned_results_by_role, p3_inputs[selection_index], selection_index)\n"
        "        if failure is not None:\n"
        "            return _p3_outcome(failure, selection_index, p2_counts, p3_count)\n"
        "    return None\n"
    )


_P3_FAILURE_FLOW_SOURCE = _p3_failure_flow_source()
_P3_B_ASSIGNMENT = "    helper_mismatch = _first_history_nonidentity_mismatch(actual_helper_result, expected_projection, expected_effects, expected_observations, physical_cost)\n"
_P3_B_FAILURE_BRANCH = (
    "    if helper_mismatch is not None:\n"
    '        return _selector_result_failure(f"helper.{helper_mismatch} differs")\n'
)
_P3_VALIDATOR_ASSIGNMENT = "        failure = _predicate_3o_5_1(selections[selection_index], p2_selections[selection_index], expected_predecessors[selection_index], expected_execution_attestation_pairs, attested_execution_specification_ids, validated_returned_results_by_role, p3_inputs[selection_index], selection_index)\n"
_P3_VALIDATOR_FAILURE_BRANCH = (
    "        if failure is not None:\n"
    "            return _p3_outcome(failure, selection_index, p2_counts, p3_count)\n"
)


def _p3_flow_replace_once(source: str, old: str, new: str) -> str:
    assert source.count(old) == 1
    return source.replace(old, new, 1)


def _p3_flow_field_statement(source: str, field: str = "study_id") -> ast.If:
    function = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "_first_history_nonidentity_mismatch"
    )
    matches = tuple(
        statement
        for statement in function.body
        if isinstance(statement, ast.If)
        and any(
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "actual"
            and node.attr == field
            for node in ast.walk(statement)
        )
    )
    assert len(matches) == 1
    return matches[0]


def _p3_flow_replace_statement(
    source: str,
    statement: ast.stmt,
    replacement: str,
) -> str:
    assert statement.end_lineno is not None
    lines = source.splitlines(keepends=True)
    lines[statement.lineno - 1 : statement.end_lineno] = [replacement]
    return "".join(lines)


def _p3_flow_all_fields_under_false(source: str) -> str:
    function = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "_first_history_nonidentity_mismatch"
    )
    first = cast(ast.If, function.body[0])
    last = cast(ast.Return, function.body[-1])
    assert last.end_lineno is not None
    lines = source.splitlines(keepends=True)
    original = lines[first.lineno - 1 : last.end_lineno]
    lines[first.lineno - 1 : last.end_lineno] = [
        "    if False:\n",
        *(f"    {line}" for line in original),
    ]
    return "".join(lines)


def _p3_flow_one_field_under(source: str, condition: str) -> str:
    statement = _p3_flow_field_statement(source)
    assert statement.end_lineno is not None
    lines = source.splitlines()
    original = lines[statement.lineno - 1 : statement.end_lineno]
    indented = "\n".join(f"    {line}" for line in original)
    return _p3_flow_replace_statement(
        source,
        statement,
        f"    {condition}:\n{indented}\n",
    )


def _p3_flow_fields_after_return(source: str) -> str:
    statement = _p3_flow_field_statement(source)
    lines = source.splitlines(keepends=True)
    lines.insert(statement.lineno - 1, "    return None\n")
    return "".join(lines)


def _p3_flow_fields_after_true_return(source: str) -> str:
    statement = _p3_flow_field_statement(source)
    lines = source.splitlines(keepends=True)
    lines[statement.lineno - 1 : statement.lineno - 1] = [
        "    if True:\n",
        "        return None\n",
    ]
    return "".join(lines)


def _p3_flow_short_circuit_field(source: str) -> str:
    statement = _p3_flow_field_statement(source)
    return _p3_flow_replace_statement(
        source,
        statement,
        "    if False and actual.study_id != expected.study_id:\n        return 'study_id'\n",
    )


def _p3_flow_findings(source: str) -> set[architecture.Finding]:
    facts = architecture._AnalysisSession().source_analysis(
        source,
        module_name=architecture.CANONICAL_MODULE,
        owned=True,
    )
    return architecture._p3_failure_flow_findings(facts)


_P3_B_VALIDATION_FINDING = architecture.Finding("p3-b-validation-flow", "fields-1-27")
_P3_B_MISMATCH_FINDING = architecture.Finding("p3-b-mismatch-flow", "B-H-failure-return")
_P3_VALIDATOR_FLOW_FINDING = architecture.Finding(
    "p3-validator-failure-flow", "predicate-failure-stop"
)


def _p3_flow_cases(
    specifications: tuple[tuple[str, str], ...],
    finding: architecture.Finding | None,
) -> tuple[LogicalCase, ...]:
    expected = frozenset() if finding is None else frozenset({finding})
    return tuple(
        LogicalCase(case_id, source, expected, finding is None)
        for case_id, source in specifications
    )


# fmt: off
_ACTIVE_P3_B_VALIDATION_FLOW_CASES = _p3_flow_cases((
    ("p3-b-validation-all-fields-under-if-false", _p3_flow_all_fields_under_false(_P3_FAILURE_FLOW_SOURCE)),
    ("p3-b-validation-one-field-under-if-false", _p3_flow_one_field_under(_P3_FAILURE_FLOW_SOURCE, "if False")),
    ("p3-b-validation-all-fields-after-return", _p3_flow_fields_after_return(_P3_FAILURE_FLOW_SOURCE)),
    ("p3-b-validation-one-field-under-while-false", _p3_flow_one_field_under(_P3_FAILURE_FLOW_SOURCE, "while False")),
    ("p3-b-validation-fields-after-if-true-return", _p3_flow_fields_after_true_return(_P3_FAILURE_FLOW_SOURCE)),
    ("p3-b-validation-short-circuited-field", _p3_flow_short_circuit_field(_P3_FAILURE_FLOW_SOURCE)),
), _P3_B_VALIDATION_FINDING)

_ACTIVE_P3_B_MISMATCH_FLOW_CASES = _p3_flow_cases((
    ("p3-b-mismatch-comparison-result-discarded", _p3_flow_replace_once(_P3_FAILURE_FLOW_SOURCE, _P3_B_FAILURE_BRANCH, "    helper_mismatch is not None\n")),
    ("p3-b-mismatch-helper-result-discarded", _p3_flow_replace_once(_P3_FAILURE_FLOW_SOURCE, _P3_B_ASSIGNMENT, "    _first_history_nonidentity_mismatch(actual_helper_result, expected_projection, expected_effects, expected_observations, physical_cost)\n    helper_mismatch = None\n")),
    ("p3-b-mismatch-result-overwritten", _p3_flow_replace_once(_P3_FAILURE_FLOW_SOURCE, _P3_B_ASSIGNMENT, _P3_B_ASSIGNMENT + "    helper_mismatch = None\n")),
    ("p3-b-mismatch-failure-object-discarded", _p3_flow_replace_once(_P3_FAILURE_FLOW_SOURCE, _P3_B_FAILURE_BRANCH, "    if helper_mismatch is not None:\n        _selector_result_failure(f\"helper.{helper_mismatch} differs\")\n        return None\n")),
    ("p3-b-mismatch-failure-object-overwritten", _p3_flow_replace_once(_P3_FAILURE_FLOW_SOURCE, _P3_B_FAILURE_BRANCH, "    if helper_mismatch is not None:\n        failure_result = _selector_result_failure(f\"helper.{helper_mismatch} differs\")\n        failure_result = None\n        return failure_result\n")),
    ("p3-b-mismatch-decision-does-not-dominate-return", _p3_flow_replace_once(_P3_FAILURE_FLOW_SOURCE, _P3_B_FAILURE_BRANCH, "    helper_mismatch is not None\n    if True:\n        return _selector_result_failure(\"helper differs\")\n")),
), _P3_B_MISMATCH_FINDING)
# fmt: on


# fmt: off
_ACTIVE_P3_VALIDATOR_FLOW_CASES = _p3_flow_cases((
    ("p3-validator-failure-pass", _p3_flow_replace_once(_P3_FAILURE_FLOW_SOURCE, _P3_VALIDATOR_FAILURE_BRANCH, "        if failure is not None:\n            pass\n")),
    ("p3-validator-failure-continue", _p3_flow_replace_once(_P3_FAILURE_FLOW_SOURCE, _P3_VALIDATOR_FAILURE_BRANCH, "        if failure is not None:\n            continue\n")),
    ("p3-validator-predicate-result-ignored", _p3_flow_replace_once(_P3_FAILURE_FLOW_SOURCE, _P3_VALIDATOR_ASSIGNMENT + _P3_VALIDATOR_FAILURE_BRANCH, _P3_VALIDATOR_ASSIGNMENT.replace("failure = ", ""))),
    ("p3-validator-predicate-result-overwritten", _p3_flow_replace_once(_P3_FAILURE_FLOW_SOURCE, _P3_VALIDATOR_ASSIGNMENT, _P3_VALIDATOR_ASSIGNMENT + "        failure = None\n")),
    ("p3-validator-outcome-discarded-and-continued", _p3_flow_replace_once(_P3_FAILURE_FLOW_SOURCE, _P3_VALIDATOR_FAILURE_BRANCH, "        if failure is not None:\n            _p3_outcome(failure, selection_index, p2_counts, p3_count)\n            continue\n")),
    ("p3-validator-outcome-overwritten-by-success", _p3_flow_replace_once(_P3_FAILURE_FLOW_SOURCE, _P3_VALIDATOR_FAILURE_BRANCH, "        if failure is not None:\n            outcome = _p3_outcome(failure, selection_index, p2_counts, p3_count)\n            outcome = None\n            return outcome\n")),
    ("p3-validator-failure-caught-and-continued", _p3_flow_replace_once(_P3_FAILURE_FLOW_SOURCE, _P3_VALIDATOR_FAILURE_BRANCH, "        if failure is not None:\n            try:\n                _p3_outcome(failure, selection_index, p2_counts, p3_count)\n            except Exception:\n                pass\n            continue\n")),
), _P3_VALIDATOR_FLOW_FINDING)
# fmt: on


def _p3_flow_b_one_hop_alias(source: str) -> str:
    return _p3_flow_replace_once(
        source,
        _P3_B_FAILURE_BRANCH,
        "    helper_alias = helper_mismatch\n"
        "    if helper_alias is not None:\n"
        '        return _selector_result_failure(f"helper.{helper_alias} differs")\n',
    )


def _p3_flow_b_two_hop_aliases(source: str) -> str:
    return _p3_flow_replace_once(
        source,
        _P3_B_FAILURE_BRANCH,
        "    first_alias = helper_mismatch\n"
        "    second_alias = first_alias\n"
        "    if second_alias is not None:\n"
        '        first_failure = _selector_result_failure(f"helper.{second_alias} differs")\n'
        "        second_failure = first_failure\n"
        "        return second_failure\n",
    )


def _p3_flow_validator_aliases(source: str) -> str:
    return _p3_flow_replace_once(
        source,
        _P3_VALIDATOR_FAILURE_BRANCH,
        "        first_failure = failure\n"
        "        second_failure = first_failure\n"
        "        if second_failure is not None:\n"
        "            first_outcome = _p3_outcome(second_failure, selection_index, p2_counts, p3_count)\n"
        "            second_outcome = first_outcome\n"
        "            return second_outcome\n",
    )


def _p3_flow_private_failure_helper(source: str) -> str:
    source = source.replace(
        "def _predicate_3o_5_1(\n",
        "def _private_b_failure():\n"
        '    return _selector_result_failure("helper differs")\n\n'
        "def _predicate_3o_5_1(\n",
        1,
    )
    return _p3_flow_replace_once(
        source,
        '        return _selector_result_failure(f"helper.{helper_mismatch} differs")\n',
        "        return _private_b_failure()\n",
    )


def _p3_flow_comments_and_inert_locals(source: str) -> str:
    return source.replace(
        "):\n    if actual.study_id",
        '):\n    """B fields remain live despite inert local context."""\n'
        "    inert_note = 'ScientificCalibrationSelectionProjection'\n"
        "    if actual.study_id",
        1,
    )


def _p3_flow_unrelated_comparison(source: str) -> str:
    return source.replace(
        "    helper_mismatch = ",
        "    unrelated = None\n"
        "    if unrelated is not None:\n"
        "        return None\n"
        "    helper_mismatch = ",
        1,
    )


# fmt: off
_ACTIVE_P3_FAILURE_FLOW_BENIGN_CASES = _p3_flow_cases((
    ("p3-flow-valid-exact", _P3_FAILURE_FLOW_SOURCE),
    ("p3-flow-valid-b-one-hop-alias", _p3_flow_b_one_hop_alias(_P3_FAILURE_FLOW_SOURCE)),
    ("p3-flow-valid-b-two-hop-aliases", _p3_flow_b_two_hop_aliases(_P3_FAILURE_FLOW_SOURCE)),
    ("p3-flow-valid-validator-two-hop-aliases", _p3_flow_validator_aliases(_P3_FAILURE_FLOW_SOURCE)),
    ("p3-flow-valid-private-failure-helper", _p3_flow_private_failure_helper(_P3_FAILURE_FLOW_SOURCE)),
    ("p3-flow-valid-comments-docstring-inert-local", _p3_flow_comments_and_inert_locals(_P3_FAILURE_FLOW_SOURCE)),
    ("p3-flow-valid-unrelated-local-comparison", _p3_flow_unrelated_comparison(_P3_FAILURE_FLOW_SOURCE)),
), None)
# fmt: on


def _p3_flow_guard_maintenance_findings(
    source: str,
) -> tuple[architecture.Finding, ...]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return (architecture.Finding("p3-flow-maintenance", "guard-syntax"),)
    functions: dict[str, list[ast.FunctionDef]] = {}
    classes: dict[str, list[ast.ClassDef]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            functions.setdefault(node.name, []).append(node)
        elif isinstance(node, ast.ClassDef):
            classes.setdefault(node.name, []).append(node)

    def loaded_names(name: str) -> frozenset[str]:
        candidates = functions.get(name, ())
        if len(candidates) != 1:
            return frozenset()
        return frozenset(
            node.id
            for node in ast.walk(candidates[0])
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        )

    def called_names(name: str) -> frozenset[str]:
        candidates = functions.get(name, ())
        if len(candidates) != 1:
            return frozenset()
        return frozenset(
            node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            for node in ast.walk(candidates[0])
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name))
        )

    findings: set[architecture.Finding] = set()
    if (
        len(classes.get("_OwnedQualifiedSymbolAnalyzer", ())) != 1
        or len(classes.get("_AnalysisSession", ())) != 1
    ):
        findings.add(architecture.Finding("p3-flow-maintenance", "single-analyzer-authority"))
    active_calls = called_names("_active_p3_internal_findings_with_session")
    if "_p3_failure_flow_findings" not in active_calls:
        findings.add(architecture.Finding("p3-flow-maintenance", "active-p3-wiring"))
    live_calls = called_names("_p3_live_direct_attribute_order")
    if "_p3_direct_attribute_order" not in live_calls:
        findings.add(architecture.Finding("p3-flow-maintenance", "no-helper-presence-fallback"))
    if "_p3_node_is_statically_reachable" not in live_calls:
        findings.add(architecture.Finding("p3-flow-maintenance", "live-b-reachability"))
    flow_names = loaded_names("_p3_failure_flow_findings")
    flow_calls = called_names("_p3_failure_flow_findings")
    if {
        "_P3_B_RESULT_MARKER",
        "_P3_H_RESULT_MARKER",
        "_P3_SELECTOR_FAILURE_MARKER",
    } - flow_names or "_p3_return_is_certified" not in flow_calls:
        findings.add(architecture.Finding("p3-flow-maintenance", "b-result-consumption"))
    if {
        "_P3_PREDICATE_RESULT_MARKER",
        "_P3_PREDICATE_DECISION_MARKER",
        "_P3_OUTCOME_MARKER",
    } - flow_names or "_p3_validator_control_has_canonical_loop" not in flow_calls:
        findings.add(architecture.Finding("p3-flow-maintenance", "validator-failure-propagation"))
    flow_block = _guard_source_function_block(source, "_p3_failure_flow_findings")
    if flow_block.count("len(certified_returns) == 1") != 2:
        findings.add(architecture.Finding("p3-flow-maintenance", "validator-requires-return"))
    direct_block = _guard_source_function_block(source, "_p3_direct_control")
    if "not test_value.unresolved" not in direct_block:
        findings.add(architecture.Finding("p3-flow-maintenance", "unresolved-fails-closed"))
    analyzer_names = loaded_names("_flow_eval_expression_inner")
    if {
        "_p3_history_result_marker",
        "_p3_predicate_call_is_exact",
        "_p3_outcome_call_is_exact",
    } - called_names("_flow_eval_expression_inner") or {
        "_P3_B_DECISION_MARKER",
        "_P3_H_DECISION_MARKER",
        "_P3_PREDICATE_DECISION_MARKER",
    } - analyzer_names:
        findings.add(architecture.Finding("p3-flow-maintenance", "single-flow-marker-authority"))
    top_level_bindings = frozenset(
        target.id
        for statement in tree.body
        if isinstance(statement, (ast.Assign, ast.AnnAssign))
        for target in (
            tuple(statement.targets) if isinstance(statement, ast.Assign) else (statement.target,)
        )
        if isinstance(target, ast.Name)
    )
    if "_P3_FLOW_RULES" in top_level_bindings:
        findings.add(architecture.Finding("p3-flow-maintenance", "single-control-authority"))
    if any(name.startswith("_P3_FLOW") and "CACHE" in name for name in top_level_bindings):
        findings.add(architecture.Finding("p3-flow-maintenance", "no-result-cache"))
    if any(name.startswith("_P3_FLOW") and "HASH" in name for name in top_level_bindings):
        findings.add(architecture.Finding("p3-flow-maintenance", "no-candidate-hash-exception"))
    return tuple(sorted(findings))


def _p3_remove_active_flow_wiring(source: str) -> str:
    return _mutate_guard_function_reference(
        source,
        "_active_p3_internal_findings_with_session",
        "findings.update(_p3_failure_flow_findings(facts))",
        "findings.update(())",
    )


def _p3_treat_helper_presence_as_sufficient(source: str) -> str:
    return _mutate_guard_function_reference(
        source,
        "_p3_live_direct_attribute_order",
        "_p3_direct_attribute_order",
        "_p3_helper_is_present",
    )


def _p3_remove_live_reachability(source: str) -> str:
    return _mutate_guard_function_reference(
        source,
        "_p3_live_direct_attribute_order",
        "_p3_node_is_statically_reachable",
        "_p3_node_is_assumed_reachable",
    )


def _p3_remove_b_result_consumption(source: str) -> str:
    block = _guard_source_function_block(source, "_p3_failure_flow_findings")
    assert block.count("_P3_B_RESULT_MARKER") == 2
    return source.replace(
        block,
        block.replace("_P3_B_RESULT_MARKER", "_P3_H_RESULT_MARKER"),
        1,
    )


def _p3_remove_validator_loop_propagation(source: str) -> str:
    return _mutate_guard_function_reference(
        source,
        "_p3_failure_flow_findings",
        "_p3_validator_control_has_canonical_loop",
        "_p3_validator_control_has_any_loop",
    )


def _p3_accept_validator_pass(source: str) -> str:
    block = _guard_source_function_block(source, "_p3_failure_flow_findings")
    marker = "len(certified_returns) == 1"
    assert block.count(marker) == 2
    before, separator, after = block.rpartition(marker)
    assert separator
    return source.replace(block, before + "len(certified_returns) >= 0" + after, 1)


def _p3_ignore_unresolved_control(source: str) -> str:
    return _mutate_guard_function_reference(
        source,
        "_p3_direct_control",
        "not test_value.unresolved",
        "True",
    )


def _p3_split_flow_marker_authority(source: str) -> str:
    return _mutate_guard_function_reference(
        source,
        "_flow_eval_expression_inner",
        "self._p3_history_result_marker",
        "self._parallel_p3_history_result_marker",
    )


# fmt: off
_ACTIVE_P3_FLOW_MAINTENANCE_CASES = (
    Mutation("p3-flow-maintenance-active-wiring-removed", _p3_remove_active_flow_wiring, architecture.Finding("p3-flow-maintenance", "active-p3-wiring")),
    Mutation("p3-flow-maintenance-helper-presence-sufficient", _p3_treat_helper_presence_as_sufficient, architecture.Finding("p3-flow-maintenance", "no-helper-presence-fallback")),
    Mutation("p3-flow-maintenance-live-reachability-removed", _p3_remove_live_reachability, architecture.Finding("p3-flow-maintenance", "live-b-reachability")),
    Mutation("p3-flow-maintenance-b-consumption-removed", _p3_remove_b_result_consumption, architecture.Finding("p3-flow-maintenance", "b-result-consumption")),
    Mutation("p3-flow-maintenance-validator-propagation-removed", _p3_remove_validator_loop_propagation, architecture.Finding("p3-flow-maintenance", "validator-failure-propagation")),
    Mutation("p3-flow-maintenance-validator-pass-accepted", _p3_accept_validator_pass, architecture.Finding("p3-flow-maintenance", "validator-requires-return")),
    Mutation("p3-flow-maintenance-unresolved-control-ignored", _p3_ignore_unresolved_control, architecture.Finding("p3-flow-maintenance", "unresolved-fails-closed")),
    Mutation("p3-flow-maintenance-parallel-marker-authority", _p3_split_flow_marker_authority, architecture.Finding("p3-flow-maintenance", "single-flow-marker-authority")),
    Mutation("p3-flow-maintenance-second-analyzer", lambda source: source + "\nclass _OwnedQualifiedSymbolAnalyzer:\n    pass\n", architecture.Finding("p3-flow-maintenance", "single-analyzer-authority")),
    Mutation("p3-flow-maintenance-second-control-table", lambda source: source + "\n_P3_FLOW_RULES = {}\n", architecture.Finding("p3-flow-maintenance", "single-control-authority")),
    Mutation("p3-flow-maintenance-module-result-cache", lambda source: source + "\n_P3_FLOW_RESULT_CACHE = {}\n", architecture.Finding("p3-flow-maintenance", "no-result-cache")),
    Mutation("p3-flow-maintenance-candidate-hash-exception", lambda source: source + "\n_P3_FLOW_APPROVED_HASH = 'candidate'\n", architecture.Finding("p3-flow-maintenance", "no-candidate-hash-exception")),
)
# fmt: on


def test_active_p3_repository_surface_is_exact_and_bounded() -> None:
    started = time.perf_counter()
    findings = architecture.repository_findings(_production_sources(), architecture.P3_MANIFEST)
    assert findings == ()
    assert time.perf_counter() - started < 30.0


def test_active_p3_b_validation_flow_matrix_is_independently_attributed() -> None:
    assert len(_ACTIVE_P3_B_VALIDATION_FLOW_CASES) == 6
    _assert_batch(_evaluate_batch(_ACTIVE_P3_B_VALIDATION_FLOW_CASES, _p3_flow_findings))


def test_active_p3_b_mismatch_flow_matrix_is_independently_attributed() -> None:
    assert len(_ACTIVE_P3_B_MISMATCH_FLOW_CASES) == 6
    _assert_batch(_evaluate_batch(_ACTIVE_P3_B_MISMATCH_FLOW_CASES, _p3_flow_findings))


def test_active_p3_validator_failure_flow_matrix_is_independently_attributed() -> None:
    assert len(_ACTIVE_P3_VALIDATOR_FLOW_CASES) == 7
    _assert_batch(_evaluate_batch(_ACTIVE_P3_VALIDATOR_FLOW_CASES, _p3_flow_findings))


def test_active_p3_failure_flow_benign_matrix_is_accepted() -> None:
    assert len(_ACTIVE_P3_FAILURE_FLOW_BENIGN_CASES) == 7
    _assert_batch(_evaluate_batch(_ACTIVE_P3_FAILURE_FLOW_BENIGN_CASES, _p3_flow_findings))


_ACTIVE_P3_FLOW_MAINTENANCE_MATRICES = (
    ("authority", _ACTIVE_P3_FLOW_MAINTENANCE_CASES[:6]),
    ("shortcuts", _ACTIVE_P3_FLOW_MAINTENANCE_CASES[6:]),
)


@pytest.mark.parametrize(
    ("matrix_id", "cases"),
    _ACTIVE_P3_FLOW_MAINTENANCE_MATRICES,
    ids=[matrix_id for matrix_id, _cases in _ACTIVE_P3_FLOW_MAINTENANCE_MATRICES],
)
def test_active_p3_failure_flow_maintenance_mutation_is_attributed(
    matrix_id: str,
    cases: tuple[Mutation, ...],
) -> None:
    source = Path(architecture.__file__).read_text(encoding="utf-8")
    assert matrix_id in {"authority", "shortcuts"}
    assert len(_ACTIVE_P3_FLOW_MAINTENANCE_CASES) == 12 and len(cases) == 6
    assert _p3_flow_guard_maintenance_findings(source) == ()
    executed: list[str] = []
    failures: list[str] = []
    for case in cases:
        executed.append(case.id)
        try:
            findings = _p3_flow_guard_maintenance_findings(case.mutate(source))
        except Exception as error:  # noqa: BLE001 - every mutation must execute
            failures.append(f"{case.id}: {type(error).__name__}: {error}")
            continue
        if case.expected not in findings:
            failures.append(f"{case.id}: missing {case.expected!r} in {findings!r}")
    assert executed == [case.id for case in cases] and not failures, "\n".join(failures)


@pytest.mark.parametrize(
    ("case_id", "mutate"),
    _ACTIVE_P3_PROJECTION_MUTATIONS,
    ids=[case_id for case_id, _mutate in _ACTIVE_P3_PROJECTION_MUTATIONS],
)
def test_active_p3_projection_shape_mutation_is_attributed(
    case_id: str, mutate: Callable[[str], str]
) -> None:
    assert case_id.startswith("p3-projection-")
    assert _p3_projection_shape_is_exact(_P3_PROJECTION_SOURCE)
    assert not _p3_projection_shape_is_exact(mutate(_P3_PROJECTION_SOURCE))


@pytest.mark.parametrize(
    ("case_id", "mutate"),
    _ACTIVE_P3_INPUT_MUTATIONS,
    ids=[case_id for case_id, _mutate in _ACTIVE_P3_INPUT_MUTATIONS],
)
def test_active_p3_input_shape_mutation_is_attributed(
    case_id: str, mutate: Callable[[str], str]
) -> None:
    assert case_id.startswith("p3-input-")
    assert _p3_input_shape_is_exact(_P3_INPUT_SOURCE)
    assert not _p3_input_shape_is_exact(mutate(_P3_INPUT_SOURCE))


@pytest.mark.parametrize(
    ("case_id", "mutate"),
    _ACTIVE_P3_CODEC_MUTATIONS,
    ids=[case_id for case_id, _mutate in _ACTIVE_P3_CODEC_MUTATIONS],
)
def test_active_p3_projection_codec_mutation_is_attributed(
    case_id: str, mutate: Callable[[str], str]
) -> None:
    assert case_id.startswith("p3-codec-")
    assert _p3_codec_is_exact(_P3_CODEC_SOURCE)
    assert not _p3_codec_is_exact(mutate(_P3_CODEC_SOURCE))


@pytest.mark.parametrize(
    ("case_id", "mutate"),
    _ACTIVE_P3_WITNESS_MUTATIONS,
    ids=[case_id for case_id, _mutate in _ACTIVE_P3_WITNESS_MUTATIONS],
)
def test_active_p3_witness_mutation_is_attributed(
    case_id: str, mutate: Callable[[str], str]
) -> None:
    assert case_id.startswith("p3-witness-")
    assert architecture._p3_witness_is_exact(_p3_predicate(_P3_PREDICATE_SOURCE))
    assert not architecture._p3_witness_is_exact(_p3_predicate(mutate(_P3_PREDICATE_SOURCE)))


@pytest.mark.parametrize(
    ("case_id", "mutate", "raw_digest_authorized"),
    _ACTIVE_P3_RECONSTRUCTION_MUTATIONS,
    ids=[case_id for case_id, _mutate, _raw in _ACTIVE_P3_RECONSTRUCTION_MUTATIONS],
)
def test_active_p3_reconstruction_mutation_is_attributed(
    case_id: str,
    mutate: Callable[[str], str],
    raw_digest_authorized: bool,
) -> None:
    raw_sites = frozenset({(1, "sha256"), (2, "hexdigest")})
    assert case_id.startswith("p3-reconstruction-")
    assert architecture._p3_reconstruction_is_exact(_p3_predicate(_P3_PREDICATE_SOURCE), raw_sites)
    assert not architecture._p3_reconstruction_is_exact(
        _p3_predicate(mutate(_P3_PREDICATE_SOURCE)),
        raw_sites if raw_digest_authorized else frozenset(),
    )


@pytest.mark.parametrize(
    ("case_id", "mutate"),
    _ACTIVE_P3_IDENTITY_MUTATIONS,
    ids=[case_id for case_id, _mutate in _ACTIVE_P3_IDENTITY_MUTATIONS],
)
def test_active_p3_identity_order_mutation_is_attributed(
    case_id: str, mutate: Callable[[str], str]
) -> None:
    assert case_id.startswith("p3-identity-")
    assert _p3_identity_order_is_exact(_P3_PREDICATE_SOURCE)
    assert not _p3_identity_order_is_exact(mutate(_P3_PREDICATE_SOURCE))


@pytest.mark.parametrize(
    ("case_id", "owner", "fields", "omitted"),
    _ACTIVE_P3_HELPER_MUTATIONS,
    ids=[case_id for case_id, _owner, _fields, _omitted in _ACTIVE_P3_HELPER_MUTATIONS],
)
def test_active_p3_helper_field_mutation_is_attributed(
    case_id: str,
    owner: str,
    fields: tuple[str, ...],
    omitted: str,
) -> None:
    source = _p3_top_level_segment(owner)
    function = _p3_predicate(source)
    assert case_id.startswith(("p3-helper-", "p3-projection-"))
    assert architecture._p3_direct_attribute_order(function, "actual", fields)
    if "reorder" in case_id:
        first = fields[0]
        mutated = _swap_all(source, f"actual.{first}", f"actual.{omitted}")
    else:
        mutated = source.replace(f"actual.{omitted}", f"expected.{omitted}")
    assert not architecture._p3_direct_attribute_order(_p3_predicate(mutated), "actual", fields)


@pytest.mark.parametrize(
    ("case_id", "suffix"),
    _ACTIVE_P3_BOUNDARY_NAMES,
    ids=[case_id for case_id, _suffix in _ACTIVE_P3_BOUNDARY_NAMES],
)
def test_active_p3_boundary_mutation_is_attributed(case_id: str, suffix: str) -> None:
    assert case_id.startswith("p3-boundary-")
    assert architecture._p3_boundary_is_exact(ast.parse(""))
    assert not architecture._p3_boundary_is_exact(ast.parse(suffix))


def test_active_p3_schedule_and_exception_mutations_are_attributed() -> None:
    facts = architecture._AnalysisSession().source_analysis(
        _P3_SCHEDULE_SOURCE,
        module_name=architecture.CANONICAL_MODULE,
        owned=True,
    )
    assert architecture._p3_schedule_is_exact(dict(facts.functions), facts.analysis)
    assert not _p3_schedule_is_exact(
        _P3_SCHEDULE_SOURCE.replace("_validate_stage2f_p2(", "_validate_stage2f_p1(", 1)
    )
    assert not _p3_schedule_is_exact(
        _P3_SCHEDULE_SOURCE.replace("range(_CANONICAL_SELECTION_COUNT)", "range(1)", 1)
    )
    predicate = _P3_PREDICATE_SOURCE
    assert architecture._p3_exception_boundary_is_exact(_p3_predicate(predicate))
    assert not architecture._p3_exception_boundary_is_exact(
        _p3_predicate(predicate.replace("except _RunProvenanceError:", "except Exception:", 1))
    )
    assert not architecture._p3_exception_boundary_is_exact(
        _p3_predicate(
            predicate.replace(
                "except _RunProvenanceError:",
                "except _RunProvenanceError:\n        actual_helper_result = _replay_calibration_history_selection()",
                1,
            )
        )
    )


def test_active_p3_process_global_cache_is_rejected() -> None:
    source = _active_p3_source() + "\n_P3_VALIDATION_CACHE = {}\n"
    assert architecture.Finding(
        "p3-performance-invariant", "invocation-local"
    ) in architecture._p3_process_global_cache_findings(ast.parse(source))


def test_active_p3_has_no_p4_or_operational_surface() -> None:
    tree = ast.parse(_active_p3_source())
    names = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert (
        "ScientificCalibrationSelectionProjection" in names
        and "CalibrationSelectionProjection" not in names
        and "calibration_selection_id" not in names
        and "_validate_stage2f_p4" not in names
        and not any(name.startswith("_predicate_3p") for name in names)
    )


def test_active_p3_architecture_node_ledger_is_exact() -> None:
    parameterized = (
        len(_ACTIVE_P3_PROJECTION_MUTATIONS)
        + len(_ACTIVE_P3_INPUT_MUTATIONS)
        + len(_ACTIVE_P3_CODEC_MUTATIONS)
        + len(_ACTIVE_P3_WITNESS_MUTATIONS)
        + len(_ACTIVE_P3_RECONSTRUCTION_MUTATIONS)
        + len(_ACTIVE_P3_IDENTITY_MUTATIONS)
        + len(_ACTIVE_P3_HELPER_MUTATIONS)
        + len(_ACTIVE_P3_BOUNDARY_NAMES)
    )
    assert parameterized == 57
    assert parameterized + 6 == 63


def test_active_p1_repository_surface_is_exact_and_bounded() -> None:
    path = _BENCHMARKS / "broader_calibration_evidence.py"
    spec = importlib.machinery.PathFinder.find_spec(
        "broader_calibration_evidence", [str(_BENCHMARKS)]
    )
    started = time.perf_counter()
    sources = _production_sources()
    sources[architecture.CANONICAL_MODULE] = _historical_p1_source()
    findings = architecture.repository_findings(sources, architecture.P1_MANIFEST)
    runtime = time.perf_counter() - started
    assert path.exists() and spec is not None and findings == ()
    assert runtime < 60.0


@pytest.mark.parametrize("case", _ACTIVE_P1_CASES, ids=[case.id for case in _ACTIVE_P1_CASES])
def test_active_p1_architecture_violation_is_independently_attributed(case: Mutation) -> None:
    findings: Iterable[architecture.Finding]
    if case.id == "active-p1-wrong-owner":
        findings = architecture.repository_findings(
            {architecture._EXECUTION: _historical_p1_source()}, architecture.P1_MANIFEST
        )
    elif case.id.startswith("active-p1-effect-"):
        findings = architecture._active_p1_effect_findings(ast.parse(case.mutate(_historical_p1_source())))  # fmt: skip
    elif case.id == "active-p1-chronology-hidden-extra-mapper":
        findings = _focused_p1_schedule_findings(case.mutate(_FOCUSED_P1_SCHEDULE_SOURCE))
    elif case.id.startswith("active-p1-chronology-"):
        findings = architecture._active_p1_chronology_findings(ast.parse(case.mutate(_historical_p1_source())))  # fmt: skip
    elif case.id in _P1_FOCUSED_MANIFEST_CASE_IDS:
        source = _future_source(architecture.P1_MANIFEST)
        assert architecture.future_source_findings(source, architecture.P1_MANIFEST) == ()
        findings = architecture.future_source_findings(case.mutate(source), architecture.P1_MANIFEST)  # fmt: skip
    else:
        findings = architecture.repository_findings(
            {architecture.CANONICAL_MODULE: case.mutate(_historical_p1_source())},
            architecture.P1_MANIFEST,
        )
    assert len(_ACTIVE_P1_CASES) == 39 and case.expected in findings


@pytest.mark.parametrize("case", _P1_SCHEDULE_CASES, ids=[case.id for case in _P1_SCHEDULE_CASES])
def test_p1_validator_schedule_violation_is_independently_attributed(
    case: Mutation,
) -> None:
    findings = _focused_p1_schedule_findings(case.mutate(_FOCUSED_P1_SCHEDULE_SOURCE))
    assert len(_P1_SCHEDULE_CASES) == 34 and case.expected in findings


@pytest.mark.parametrize(
    ("case_id", "mutate"),
    _P1_BENIGN_SCHEDULE_CASES,
    ids=[case_id for case_id, _ in _P1_BENIGN_SCHEDULE_CASES],
)
def test_p1_validator_proven_neutral_schedule_control_is_accepted(
    case_id: str,
    mutate: Callable[[str], str],
) -> None:
    assert len(_P1_BENIGN_SCHEDULE_CASES) == 5
    assert case_id.startswith("schedule-benign-")
    assert _focused_p1_schedule_findings(mutate(_FOCUSED_P1_SCHEDULE_SOURCE)) == set()


def test_p1_harness_is_fixture_only_and_identity_independent() -> None:
    source = _historical_p1_harness_source()
    assert architecture.harness_findings(source) == ()
    missing = tuple(
        case.id
        for case in _HARNESS_SUPPLEMENTARY_ALIAS_CASES
        if case.expected not in architecture.harness_findings(case.mutate(source))
    )
    benign_source = source
    for _case_id, mutate in _HARNESS_SUPPLEMENTARY_BENIGN_CONTROLS:
        benign_source = mutate(benign_source)
    assert len(_HARNESS_SUPPLEMENTARY_ALIAS_CASES) == 2 and not missing
    assert len(_HARNESS_BENIGN_ALIAS_CASES) + len(_HARNESS_SUPPLEMENTARY_BENIGN_CONTROLS) == 14
    assert architecture.harness_findings(benign_source) == ()


@pytest.mark.parametrize("case", _HARNESS_CASES, ids=[case.id for case in _HARNESS_CASES])
def test_p1_harness_authority_violation_is_independently_attributed(
    case: Mutation,
) -> None:
    source = _historical_p1_harness_source()
    findings = architecture.harness_findings(case.mutate(source))
    assert len(_HARNESS_CASES) == 19 and case.expected in findings


@pytest.mark.parametrize(
    "case", _HARNESS_ALIAS_CASES, ids=[case.id for case in _HARNESS_ALIAS_CASES]
)
def test_p1_harness_forbidden_alias_is_independently_attributed(
    case: Mutation,
) -> None:
    source = _historical_p1_harness_source()
    findings = architecture.harness_findings(case.mutate(source))
    assert len(_HARNESS_ALIAS_CASES) == 38 and case.expected in findings


@pytest.mark.parametrize(
    ("case_id", "mutate"),
    _HARNESS_BENIGN_ALIAS_CASES,
    ids=[case_id for case_id, _ in _HARNESS_BENIGN_ALIAS_CASES],
)
def test_p1_harness_benign_alias_control_is_accepted(
    case_id: str,
    mutate: Callable[[str], str],
) -> None:
    source = _historical_p1_harness_source()
    assert len(_HARNESS_BENIGN_ALIAS_CASES) == 7
    assert case_id.startswith("harness-benign-")
    assert architecture.harness_findings(mutate(source)) == ()


@pytest.mark.parametrize(
    "case",
    _POSSIBLE_PRODUCTION_JOIN_CASES,
    ids=[case.id for case in _POSSIBLE_PRODUCTION_JOIN_CASES],
)
def test_possible_production_helper_join_is_independently_attributed(
    case: LogicalCase,
) -> None:
    findings = frozenset(architecture.harness_findings(case.source))
    assert case.expected <= findings
    attributions = architecture.harness_provenance_attributions(case.source)
    matching = tuple(
        attribution
        for attribution in attributions
        if (
            attribution.finding in case.expected
            and attribution.certainty == "possible"
            and attribution.origin.startswith(architecture.CANONICAL_MODULE)
        )
    )
    assert len(matching) == 1
    assert matching[0].operation.endswith(".strict_chronology_id")


def test_remaining_possible_production_cases_are_complete() -> None:
    assert len(_POSSIBLE_PRODUCTION_JOIN_CASES) == 5
    assert len(_POSSIBLE_PRODUCTION_OTHER_CASES) == 13
    _assert_batch(
        _evaluate_batch(
            _POSSIBLE_PRODUCTION_OTHER_CASES,
            architecture.harness_findings,
        )
    )


def test_possible_production_dynamic_attribution_records_operation_and_origin() -> None:
    case = next(
        item
        for item in _POSSIBLE_PRODUCTION_OTHER_CASES
        if item.id == "possible-production-dynamic-attribute"
    )
    attributions = architecture.harness_provenance_attributions(case.source)
    dynamic = tuple(
        item
        for item in attributions
        if item.finding == architecture.Finding("harness-unresolved-production-alias", "getattr")
    )
    escaped_line = _line_of(case.source, "escaped = getattr")
    assert dynamic == (
        architecture.HarnessProvenanceAttribution(
            architecture.Finding(
                "harness-unresolved-production-alias",
                "getattr",
            ),
            escaped_line,
            architecture.CANONICAL_MODULE,
            "possible",
            "getattr(audit_owner(unknown_flag), dynamic_name)",
            10,
            "result",
            "canonical-production-module",
            True,
            "none",
            architecture.CANONICAL_MODULE,
        ),
    )


def test_unrelated_dynamic_benign_controls_are_complete() -> None:
    assert len(_UNRELATED_DYNAMIC_BENIGN_CASES) == 9
    _assert_batch(
        _evaluate_batch(
            _UNRELATED_DYNAMIC_BENIGN_CASES,
            architecture.harness_findings,
        )
    )


def test_production_dynamic_fail_closed_controls_are_complete() -> None:
    assert len(_FAIL_CLOSED_PRODUCTION_DYNAMIC_CASES) == 9
    _assert_batch(
        _evaluate_batch(
            _FAIL_CLOSED_PRODUCTION_DYNAMIC_CASES,
            architecture.harness_findings,
        )
    )
    propagated_ids = {
        "fail-closed-forbidden-helper-unknown-container-retrieval",
        "fail-closed-forbidden-helper-branch-return",
        "fail-closed-forbidden-helper-closure-return",
        "fail-closed-forbidden-helper-mixed-callable-sequence",
    }
    observed = {
        case.id: architecture.harness_provenance_attributions(case.source)
        for case in _FAIL_CLOSED_PRODUCTION_DYNAMIC_CASES
        if case.id in propagated_ids
    }
    assert set(observed) == propagated_ids
    assert all(
        any(
            attribution.finding == _FORBIDDEN_IDENTITY and attribution.certainty == "possible"
            for attribution in attributions
        )
        for attributions in observed.values()
    )


# fmt: off
def _projected_provenance(source: str) -> tuple[architecture.ProjectedProvenance, ...]:
    return architecture._canonical_production_origins(architecture._qualified_analysis(source, module_name=architecture.HARNESS_MODULE))

def _site_facts(source: str, marker: str, node_kind: str) -> tuple[architecture.ProjectedProvenance, ...]:
    line = _line_of(source, marker)
    return tuple(fact for fact in _projected_provenance(source) if fact.lineno == line and fact.node_kind == node_kind)

def _codec_analysis() -> qualified.QualifiedSymbolAnalysis:
    analysis = architecture._qualified_analysis("value = 1\n", module_name=architecture.HARNESS_MODULE)
    return analysis._replace(findings=tuple(finding for finding in analysis.findings if finding.code != architecture._CANONICAL_PRODUCTION_ORIGIN_CODE))

def _decode_codec_symbol(analysis: qualified.QualifiedSymbolAnalysis, symbol: object) -> tuple[architecture.ProjectedProvenance, ...]:
    finding = qualified.ArchitectureFinding(architecture._CANONICAL_PRODUCTION_ORIGIN_CODE, cast(str, symbol), 1)
    return architecture._canonical_production_origins(analysis._replace(findings=(*analysis.findings, finding)))

def _malformed_wire_failures(cases: tuple[tuple[str, object], ...]) -> tuple[str, ...]:
    analysis = _codec_analysis()
    expected = (architecture._malformed_projected_provenance(1),)
    failures: list[str] = []
    executed: list[str] = []
    for case_id, symbol in cases:
        executed.append(case_id)
        try:
            first = _decode_codec_symbol(analysis, symbol)
            second = _decode_codec_symbol(analysis, symbol)
            if first != expected or second != expected or first != second:
                failures.append(f"{case_id}:noncanonical")
        except BaseException as exc:
            failures.append(f"{case_id}:raised-{type(exc).__name__}")
    if tuple(executed) != tuple(case_id for case_id, _symbol in cases):
        failures.append("matrix:short-circuited")
    return tuple(failures)

def _malformed_encoder_failures(cases: tuple[tuple[str, object], ...]) -> tuple[str, ...]:
    expected_fact = architecture._malformed_projected_provenance(1)
    expected = architecture._encoded_projected_provenance(expected_fact)
    analysis = _codec_analysis()
    failures: list[str] = []
    executed: list[str] = []
    for case_id, fact in cases:
        executed.append(case_id)
        try:
            first = architecture._encoded_projected_provenance(fact)
            second = architecture._encoded_projected_provenance(fact)
            decoded = _decode_codec_symbol(analysis, first.symbol)
            if first != expected or second != expected or decoded != (expected_fact,):
                failures.append(f"{case_id}:noncanonical")
        except BaseException as exc:
            failures.append(f"{case_id}:raised-{type(exc).__name__}")
    if tuple(executed) != tuple(case_id for case_id, _fact in cases):
        failures.append("matrix:short-circuited")
    return tuple(failures)

def test_exact_unrelated_reflection_matrix_is_receiver_sensitive_and_bounded() -> None:
    started = time.perf_counter()
    result = _evaluate_batch(_UNRELATED_REFLECTION_CASES, architecture.harness_findings)
    facts = {case.id: _projected_provenance(case.source) for case in _UNRELATED_REFLECTION_CASES}
    _assert_batch(result)
    assert len(_UNRELATED_REFLECTION_CASES) == 14 and all(facts.values())
    assert all(not fact.production_reachable for case_facts in facts.values() for fact in case_facts)
    assert time.perf_counter() - started < 10.0

def test_production_sensitive_reflection_matrix_fails_closed_with_provenance() -> None:
    started = time.perf_counter()
    _assert_batch(_evaluate_batch(_PRODUCTION_REFLECTION_CASES, architecture.harness_findings))
    attributions = {case.id: architecture.harness_provenance_attributions(case.source) for case in _PRODUCTION_REFLECTION_CASES[:8]}
    assert len(_PRODUCTION_REFLECTION_CASES) == 15 and all(attributions.values())
    assert all(item.production_reachable and item.certainty in {"exact", "possible", "limited"} and item.col_offset >= 0 and item.qualified_origin is not None for case_attributions in attributions.values() for item in case_attributions)
    assert any(item.relation == "receiver" for item in attributions["production-reflection-module-dict"])
    assert any(item.relation == "result" for item in attributions["production-reflection-possible-module-dict"])
    assert any(item.relation == "result" for item in attributions["production-reflection-getattr-possible-module"])
    assert time.perf_counter() - started < 10.0

@pytest.mark.parametrize(("projection_name", "construction"), (("CalibrationCandidatePairProjection", "adam_candidate_id='adam', comparison_group_id='group', replication_id='1', schema_version='broader-replication-calibration-candidate-pair/v1', sgd_candidate_id='sgd', world_id='world'"), ("StrictChronologyProjection", "current_effect_excluded=True, current_observation_excluded=True, effect_available_sequences=(1, 2, 3, 4, 5), future_history_excluded=True, schema_version='broader-replication-calibration-chronology/v1', source_sequence_cutoff=1")), ids=("allowed-pair-projection", "allowed-chronology-projection"))
def test_exact_allowed_projection_origin_survives_alias_and_construction(projection_name: str, construction: str) -> None:
    source = f"from {architecture.CANONICAL_MODULE} import {projection_name}\nDirectFixtureProjection = {projection_name}\nFixtureOptions = (DirectFixtureProjection, {projection_name})\nFixtureProjection = FixtureOptions[unknown_index]\nfixture = FixtureProjection({construction})\n"
    facts, expected_origin = _projected_provenance(source), f"{architecture.CANONICAL_MODULE}.{projection_name}"
    assert architecture.harness_findings(source) == ()
    allowed = tuple(fact for fact in facts if fact.origin_class == "allowed-production-projection-class")
    assert allowed and all(fact.production_reachable is False and fact.limit_class == "none" for fact in allowed)
    assert any(fact.qualified_origin == expected_origin and fact.certainty == "exact" for fact in allowed)
    assert any(fact.qualified_origin == expected_origin and fact.certainty == "possible" and fact.relation == "aggregate" for fact in allowed)
    assert any(fact.relation in {"callable", "result"} for fact in allowed)

def test_allowed_projection_direct_alias_construction_and_aggregate_facts_are_retained_but_unreachable() -> None:
    pair = "CalibrationCandidatePairProjection"
    chronology = "StrictChronologyProjection"
    pair_construction = "adam_candidate_id='adam', comparison_group_id='group', replication_id='1', schema_version='broader-replication-calibration-candidate-pair/v1', sgd_candidate_id='sgd', world_id='world'"
    chronology_construction = "current_effect_excluded=True, current_observation_excluded=True, effect_available_sequences=(1, 2, 3, 4, 5), future_history_excluded=True, schema_version='broader-replication-calibration-chronology/v1', source_sequence_cutoff=1"
    module = architecture.CANONICAL_MODULE
    cases = {
        "direct-candidate-pair": (f"from {module} import {pair}\nselected = {pair}\n", "selected =", "Name"),
        "direct-strict-chronology": (f"from {module} import {chronology}\nselected = {chronology}\n", "selected =", "Name"),
        "private-candidate-pair-alias": (f"from {module} import {pair} as _Pair\nselected = _Pair\n", "selected =", "Name"),
        "one-hop-candidate-pair-alias": (f"from {module} import {pair}\nPairAlias = {pair}\nselected = PairAlias\n", "selected =", "Name"),
        "constructed-candidate-pair-instance": (f"from {module} import {pair}\nfixture = {pair}({pair_construction})\n", "fixture =", "Call"),
        "constructed-strict-chronology-instance": (f"from {module} import {chronology}\nfixture = {chronology}({chronology_construction})\n", "fixture =", "Call"),
        "branch-both-allowed-classes": (f"from {module} import {pair}, {chronology}\nselected = {pair} if unknown_flag else {chronology}\n", "selected =", "IfExp"),
        "bounded-allowed-aggregate": (f"from {module} import {pair}, {chronology}\noptions = ({pair}, {chronology})\nselected = options[0]\n", "selected =", "Subscript"),
        "unknown-index-allowed-aggregate": (f"from {module} import {pair}, {chronology}\noptions = ({pair}, {chronology})\nselected = options[unknown_index]\n", "selected =", "Subscript"),
    }
    observed = {case_id: _site_facts(source, marker, node_kind) for case_id, (source, marker, node_kind) in cases.items()}
    assert set(observed) == set(cases)
    for case_id, facts in observed.items():
        allowed = tuple(fact for fact in facts if fact.origin_class == "allowed-production-projection-class")
        assert allowed, case_id
        assert all(fact.production_reachable is False and fact.limit_class == "none" for fact in allowed), case_id
        assert not any(fact.production_reachable for fact in facts), case_id

def test_allowed_projection_join_facts_are_symmetric_and_only_sensitive_with_production_origins() -> None:
    pair = "CalibrationCandidatePairProjection"
    chronology = "StrictChronologyProjection"
    module = architecture.CANONICAL_MODULE
    prefixes = {
        "local": f"from {module} import {pair}\nclass Local:\n    pass\n",
        "math": f"from {module} import {pair}\nimport math\n",
        "production": f"from {module} import {pair}\nfrom research_decision_engine.benchmarks import broader_calibration_evidence as production\n",
        "helper": f"from {module} import {pair}, strict_chronology_id as forbidden\n",
        "allowed-only-container": f"from {module} import {pair}, {chronology}\n",
        "mixed-container": f"from {module} import {pair}, strict_chronology_id as forbidden\n",
    }
    cases = {
        "allowed-plus-local": (prefixes["local"] + f"selected = {pair} if unknown_flag else Local\n", "IfExp", False),
        "local-plus-allowed": (prefixes["local"] + f"selected = Local if unknown_flag else {pair}\n", "IfExp", False),
        "allowed-plus-unrelated-module": (prefixes["math"] + f"selected = {pair} if unknown_flag else math\n", "IfExp", False),
        "allowed-plus-production-module": (prefixes["production"] + f"selected = {pair} if unknown_flag else production\n", "IfExp", True),
        "production-module-plus-allowed": (prefixes["production"] + f"selected = production if unknown_flag else {pair}\n", "IfExp", True),
        "allowed-plus-forbidden-helper": (prefixes["helper"] + f"selected = {pair} if unknown_flag else forbidden\n", "IfExp", True),
        "allowed-only-unknown-index": (prefixes["allowed-only-container"] + f"selected = ({pair}, {chronology})[unknown_index]\n", "Subscript", False),
        "allowed-sensitive-unknown-index": (prefixes["mixed-container"] + f"selected = ({pair}, forbidden)[unknown_index]\n", "Subscript", True),
    }
    observed: dict[str, tuple[architecture.ProjectedProvenance, ...]] = {}
    for case_id, (source, node_kind, sensitive) in cases.items():
        facts = _site_facts(source, "selected =", node_kind)
        observed[case_id] = facts
        allowed = tuple(fact for fact in facts if fact.origin_class == "allowed-production-projection-class")
        assert allowed and all(fact.production_reachable is False for fact in allowed), case_id
        assert any(fact.production_reachable is True for fact in facts) is sensitive, case_id
        assert not any(fact.origin_class == "allowed-production-projection-class" and fact.production_reachable is True for fact in facts), case_id

    def signature(facts: tuple[architecture.ProjectedProvenance, ...]) -> tuple[tuple[str, bool, str, str], ...]:
        return tuple(sorted((fact.origin_class, fact.production_reachable, fact.limit_class, fact.qualified_origin or "") for fact in facts))

    assert signature(observed["allowed-plus-local"]) == signature(observed["local-plus-allowed"])
    assert signature(observed["allowed-plus-production-module"]) == signature(observed["production-module-plus-allowed"])

def test_provenance_codec_rejects_non_exact_wire_types() -> None:
    valid_wire = f"0|Name|exact|direct|allowed-production-projection-class|0|none|{architecture.CANONICAL_MODULE}.CalibrationCandidatePairProjection"
    cases = (("none", None), ("bytes", valid_wire.encode()), ("bytearray", bytearray(valid_wire.encode())), ("memoryview", memoryview(valid_wire.encode())), ("list", [valid_wire]), ("tuple", (valid_wire,)), ("plain-object", object()))
    assert _malformed_wire_failures(cases) == ()

def test_provenance_codec_rejects_missing_and_extra_wire_fields() -> None:
    valid_wire = f"0|Name|exact|direct|allowed-production-projection-class|0|none|{architecture.CANONICAL_MODULE}.CalibrationCandidatePairProjection"
    parts = valid_wire.split("|")
    cases = (
        ("empty", ""), ("one-field", "only"), ("missing-first", "|".join(parts[1:])), ("missing-final", "|".join(parts[:-1])),
        ("one-extra", valid_wire + "|EXTRA"), ("two-extra", valid_wire + "|EXTRA|MORE"), ("trailing-separator", valid_wire + "|"),
        ("leading-separator", "|" + valid_wire), ("empty-ninth", valid_wire + "|"),
        ("embedded-qualified-delimiter", valid_wire.replace("CalibrationCandidatePairProjection", "CalibrationCandidatePairProjection|HIDDEN")),
    )
    assert _malformed_wire_failures(cases) == ()

def test_provenance_codec_rejects_unknown_and_malformed_wire_fields() -> None:
    fields = ["0", "Name", "exact", "direct", "allowed-production-projection-class", "0", "none", f"{architecture.CANONICAL_MODULE}.CalibrationCandidatePairProjection"]
    def changed(index: int, value: str) -> str:
        candidate = fields.copy()
        candidate[index] = value
        return "|".join(candidate)
    cases = (
        ("empty-node-kind", changed(1, "")), ("unknown-certainty", changed(2, "unknown-certainty")), ("unknown-relation", changed(3, "unknown-relation")),
        ("unknown-origin", changed(4, "unknown-origin")), ("unknown-limit", changed(6, "unknown-limit")), ("invalid-boolean", changed(5, "true")),
        ("truthy-integer-token", changed(5, "2")), ("malformed-position-negative", changed(0, "-1")), ("malformed-position-leading-zero", changed(0, "00")),
        ("malformed-position-unicode", changed(0, "\N{ARABIC-INDIC DIGIT ONE}")), ("malformed-position-oversized", changed(0, "9" * 5000)), ("unknown-node-kind", changed(1, "UnknownNode")),
        ("malformed-qualified-origin", changed(7, f"{architecture.CANONICAL_MODULE}.bad-origin")),
    )
    assert _malformed_wire_failures(cases) == ()

def test_provenance_codec_rejects_semantically_contradictory_wire_records() -> None:
    module = architecture.CANONICAL_MODULE
    cases = (
        ("unrelated-reachable", "0|Name|exact|direct|unrelated-local|1|none|"),
        ("sensitive-unreachable", f"0|Name|possible|result|unresolved-production-sensitive|0|none|{module}"),
        ("limited-with-none", "0|AnalysisLimit|limited|aggregate|unresolved-local|0|none|"),
        ("nonlimited-with-unrelated", "0|Name|exact|direct|unresolved-local|0|unrelated|"),
        ("nonlimited-with-sensitive", f"0|Name|possible|result|unresolved-production-sensitive|1|production-sensitive|{module}"),
        ("allowed-projection-reachable", f"0|Name|exact|direct|allowed-production-projection-class|1|none|{module}.CalibrationCandidatePairProjection"),
        ("forbidden-helper-unreachable", f"0|Name|exact|direct|forbidden-production-helper|0|none|{module}.strict_chronology_id"),
        ("limited-unrelated-reachable", "0|AnalysisLimit|limited|aggregate|unrelated-local|1|unrelated|"),
        ("limited-sensitive-unreachable", f"0|AnalysisLimit|limited|aggregate|unresolved-production-sensitive|0|production-sensitive|{module}"),
    )
    assert _malformed_wire_failures(cases) == ()

def test_provenance_codec_encoder_rejects_unknown_closed_values() -> None:
    origin = f"{architecture.CANONICAL_MODULE}.CalibrationCandidatePairProjection"
    valid = architecture.ProjectedProvenance(1, 0, "Name", "exact", "direct", "allowed-production-projection-class", False, "none", origin)
    cases = (
        ("unknown-origin", valid._replace(origin_class=cast(architecture.ProjectedProvenanceOriginClass, "unknown-origin"))),
        ("unknown-certainty", valid._replace(certainty=cast(architecture.ProjectedProvenanceCertainty, "unknown-certainty"))),
        ("unknown-relation", valid._replace(relation=cast(architecture.ProjectedProvenanceRelation, "unknown-relation"))),
        ("unknown-limit", valid._replace(limit_class=cast(architecture.ProjectedProvenanceLimitClass, "unknown-limit"))),
        ("nonboolean-reachability", valid._replace(production_reachable=cast(bool, 1))), ("unknown-node-kind", valid._replace(node_kind="UnknownNode")),
        ("oversized-lineno", valid._replace(lineno=10**5000)), ("oversized-col-offset", valid._replace(col_offset=10**5000)),
        ("invalid-node-kind-type", valid._replace(node_kind=cast(str, 1))), ("invalid-qualified-origin-type", valid._replace(qualified_origin=cast(str | None, 1))),
        ("malformed-qualified-origin", valid._replace(qualified_origin=f"{architecture.CANONICAL_MODULE}.bad-origin")),
    )
    assert _malformed_encoder_failures(cases) == ()

def test_provenance_codec_encoder_rejects_wrong_record_shapes() -> None:
    origin = f"{architecture.CANONICAL_MODULE}.CalibrationCandidatePairProjection"
    valid = architecture.ProjectedProvenance(1, 0, "Name", "exact", "direct", "allowed-production-projection-class", False, "none", origin)
    MissingCodecFact = namedtuple("MissingCodecFact", ("lineno", "col_offset", "node_kind", "certainty", "relation", "origin_class", "production_reachable", "limit_class"))
    ExtraCodecFact = namedtuple("ExtraCodecFact", ("lineno", "col_offset", "node_kind", "certainty", "relation", "origin_class", "production_reachable", "limit_class", "qualified_origin", "extra"))
    class ProjectedSubclass(architecture.ProjectedProvenance):
        __slots__ = ()
    proxy = HostileMetadata()
    cases = (("wrong-record-type", tuple(valid)), ("missing-field", MissingCodecFact(*valid[:-1])), ("extra-field", ExtraCodecFact(*valid, "extra")), ("proxy-record", proxy), ("subclass-record", ProjectedSubclass(*valid)))
    assert _malformed_encoder_failures(cases) == ()
    assert all(count == 0 for count in proxy.counts.values())

def test_provenance_codec_encoder_rejects_consistency_contradictions() -> None:
    module = architecture.CANONICAL_MODULE
    allowed = architecture.ProjectedProvenance(1, 0, "Name", "exact", "direct", "allowed-production-projection-class", False, "none", f"{module}.CalibrationCandidatePairProjection")
    helper = architecture.ProjectedProvenance(1, 0, "Name", "exact", "direct", "forbidden-production-helper", True, "none", f"{module}.strict_chronology_id")
    unrelated_limit = architecture.ProjectedProvenance(1, 0, "AnalysisLimit", "limited", "aggregate", "unresolved-local", False, "unrelated", None)
    sensitive_limit = architecture.ProjectedProvenance(1, 0, "AnalysisLimit", "limited", "aggregate", "unresolved-production-sensitive", True, "production-sensitive", module)
    cases = (
        ("allowed-reachable", allowed._replace(production_reachable=True)), ("helper-unreachable", helper._replace(production_reachable=False)),
        ("unrelated-reachable", unrelated_limit._replace(production_reachable=True)), ("sensitive-unreachable", sensitive_limit._replace(production_reachable=False)),
        ("limited-none", unrelated_limit._replace(limit_class="none")), ("exact-unrelated-limit", unrelated_limit._replace(certainty="exact")),
        ("possible-sensitive-limit", sensitive_limit._replace(certainty="possible")), ("missing-required-origin", allowed._replace(qualified_origin=None)),
    )
    assert _malformed_encoder_failures(cases) == ()

def test_provenance_codec_hostile_wire_and_str_subclass_execute_no_hooks() -> None:
    valid_wire = f"0|Name|exact|direct|allowed-production-projection-class|0|none|{architecture.CANONICAL_MODULE}.CalibrationCandidatePairProjection"
    hostile = HostileMetadata()
    hostile_string = HostileCodecString(valid_wire)
    assert _malformed_wire_failures((("hostile-object", hostile), ("exact-str-subclass", hostile_string))) == ()
    assert all(count == 0 for sentinel in (hostile, hostile_string) for count in sentinel.counts.values())

def test_provenance_codec_hostile_internal_fields_execute_no_hooks() -> None:
    origin = f"{architecture.CANONICAL_MODULE}.CalibrationCandidatePairProjection"
    valid = architecture.ProjectedProvenance(1, 0, "Name", "exact", "direct", "allowed-production-projection-class", False, "none", origin)
    sentinels = tuple(HostileMetadata() for _ in architecture.ProjectedProvenance._fields)
    cases = (
        ("hostile-lineno", valid._replace(lineno=cast(int, sentinels[0]))), ("hostile-col-offset", valid._replace(col_offset=cast(int, sentinels[1]))),
        ("hostile-node-kind", valid._replace(node_kind=cast(str, sentinels[2]))), ("hostile-certainty", valid._replace(certainty=cast(architecture.ProjectedProvenanceCertainty, sentinels[3]))),
        ("hostile-relation", valid._replace(relation=cast(architecture.ProjectedProvenanceRelation, sentinels[4]))), ("hostile-origin", valid._replace(origin_class=cast(architecture.ProjectedProvenanceOriginClass, sentinels[5]))),
        ("hostile-reachability", valid._replace(production_reachable=cast(bool, sentinels[6]))), ("hostile-limit", valid._replace(limit_class=cast(architecture.ProjectedProvenanceLimitClass, sentinels[7]))),
        ("hostile-qualified-origin", valid._replace(qualified_origin=cast(str | None, sentinels[8]))),
    )
    assert _malformed_encoder_failures(cases) == ()
    assert all(count == 0 for sentinel in sentinels for count in sentinel.counts.values())

def test_provenance_codec_valid_round_trips_preserve_canonical_bytes() -> None:
    module = architecture.CANONICAL_MODULE
    vectors = (
        ("canonical-module", architecture.ProjectedProvenance(1, 0, "ImportBinding", "exact", "direct", "canonical-production-module", True, "none", module), f"0|ImportBinding|exact|direct|canonical-production-module|1|none|{module}"),
        ("forbidden-helper", architecture.ProjectedProvenance(1, 0, "Name", "exact", "callable", "forbidden-production-helper", True, "none", f"{module}.strict_chronology_id"), f"0|Name|exact|callable|forbidden-production-helper|1|none|{module}.strict_chronology_id"),
        ("allowed-projection", architecture.ProjectedProvenance(1, 0, "Name", "exact", "direct", "allowed-production-projection-class", False, "none", f"{module}.CalibrationCandidatePairProjection"), f"0|Name|exact|direct|allowed-production-projection-class|0|none|{module}.CalibrationCandidatePairProjection"),
        ("unrelated-import", architecture.ProjectedProvenance(1, 2, "Attribute", "exact", "receiver", "unrelated-imported-module", False, "none", "math"), "2|Attribute|exact|receiver|unrelated-imported-module|0|none|math"),
        ("unrelated-local-null", architecture.ProjectedProvenance(1, 0, "Name", "exact", "direct", "unrelated-local", False, "none", None), "0|Name|exact|direct|unrelated-local|0|none|"),
        ("unresolved-local-null", architecture.ProjectedProvenance(1, 0, "Call", "possible", "result", "unresolved-local", False, "none", None), "0|Call|possible|result|unresolved-local|0|none|"),
        ("unresolved-sensitive", architecture.ProjectedProvenance(1, 0, "Call", "possible", "result", "unresolved-production-sensitive", True, "none", module), f"0|Call|possible|result|unresolved-production-sensitive|1|none|{module}"),
        ("possible-aggregate", architecture.ProjectedProvenance(1, 0, "Tuple", "possible", "aggregate", "allowed-production-projection-class", False, "none", f"{module}.StrictChronologyProjection"), f"0|Tuple|possible|aggregate|allowed-production-projection-class|0|none|{module}.StrictChronologyProjection"),
        ("unrelated-limit", architecture.ProjectedProvenance(1, 0, "AnalysisLimit", "limited", "aggregate", "unresolved-local", False, "unrelated", None), "0|AnalysisLimit|limited|aggregate|unresolved-local|0|unrelated|"),
        ("sensitive-limit", architecture.ProjectedProvenance(1, 0, "AnalysisLimit", "limited", "aggregate", "unresolved-production-sensitive", True, "production-sensitive", module), f"0|AnalysisLimit|limited|aggregate|unresolved-production-sensitive|1|production-sensitive|{module}"),
    )
    analysis = _codec_analysis()
    failures = []
    for case_id, fact, wire in vectors:
        encoded = architecture._encoded_projected_provenance(fact)
        decoded = _decode_codec_symbol(analysis, wire)
        if encoded.symbol != wire or decoded != (fact,) or architecture._encoded_projected_provenance(decoded[0]).symbol != wire:
            failures.append(case_id)
    assert not failures

def test_provenance_codec_fail_closed_sentinel_round_trips_and_is_sensitive() -> None:
    sentinel = architecture._malformed_projected_provenance(1)
    encoded = architecture._encoded_projected_provenance(sentinel)
    analysis = _codec_analysis()._replace(findings=(encoded,))
    decoded = architecture._canonical_production_origins(analysis)
    attributions = architecture._harness_provenance_attributions(ast.parse("value = 1\n"), analysis)
    assert decoded == (sentinel,) and architecture._encoded_projected_provenance(decoded[0]) == encoded
    assert sentinel.node_kind == "AnalysisLimit" and sentinel.production_reachable is True
    assert sentinel.qualified_origin == architecture._MALFORMED_PROJECTED_PROVENANCE_ORIGIN
    assert any(item.finding == architecture.Finding("harness-unresolved-production-alias", "provenance-limit") for item in attributions)

def test_projected_provenance_limit_consistency_matrix_fails_closed_without_hooks() -> None:
    source = "value = 1\n"
    analysis = architecture._qualified_analysis(source, module_name=architecture.HARNESS_MODULE)
    analysis = analysis._replace(findings=tuple(finding for finding in analysis.findings if finding.code != architecture._CANONICAL_PRODUCTION_ORIGIN_CODE))
    allowed_origin = f"{architecture.CANONICAL_MODULE}.CalibrationCandidatePairProjection"
    helper_origin = f"{architecture.CANONICAL_MODULE}.strict_chronology_id"
    valid = {
        "limited-unrelated-unreachable": architecture.ProjectedProvenance(1, 0, "AnalysisLimit", "limited", "aggregate", "allowed-production-projection-class", False, "unrelated", allowed_origin),
        "limited-sensitive-reachable": architecture.ProjectedProvenance(1, 0, "AnalysisLimit", "limited", "aggregate", "unresolved-production-sensitive", True, "production-sensitive", architecture.CANONICAL_MODULE),
    }
    invalid = {
        "limited-unrelated-reachable": valid["limited-unrelated-unreachable"]._replace(production_reachable=True),
        "limited-sensitive-unreachable": valid["limited-sensitive-reachable"]._replace(production_reachable=False),
        "exact-unrelated-limit": valid["limited-unrelated-unreachable"]._replace(certainty="exact"),
        "possible-sensitive-limit": valid["limited-sensitive-reachable"]._replace(certainty="possible"),
        "limited-none": valid["limited-unrelated-unreachable"]._replace(limit_class="none"),
        "direct-allowed-reachable": architecture.ProjectedProvenance(1, 0, "Name", "exact", "direct", "allowed-production-projection-class", True, "none", allowed_origin),
        "direct-helper-unreachable": architecture.ProjectedProvenance(1, 0, "Name", "exact", "direct", "forbidden-production-helper", False, "none", helper_origin),
        "unrelated-local-reachable": architecture.ProjectedProvenance(1, 0, "Name", "exact", "direct", "unrelated-local", True, "none", None),
        "unresolved-sensitive-unreachable": architecture.ProjectedProvenance(1, 0, "Name", "possible", "result", "unresolved-production-sensitive", False, "none", architecture.CANONICAL_MODULE),
    }
    fail_closed = architecture._malformed_projected_provenance(1)
    for case_id, fact in valid.items():
        encoded = architecture._encoded_projected_provenance(fact)
        assert architecture._canonical_production_origins(analysis._replace(findings=(*analysis.findings, encoded))) == (fact,), case_id
    for case_id, fact in invalid.items():
        encoded = architecture._encoded_projected_provenance(fact)
        assert encoded == architecture._encoded_projected_provenance(fail_closed), case_id
        assert architecture._canonical_production_origins(analysis._replace(findings=(*analysis.findings, encoded))) == (fail_closed,), case_id
    non_boolean = invalid["direct-allowed-reachable"]._replace(production_reachable=cast(bool, 1))
    assert architecture._encoded_projected_provenance(non_boolean) == architecture._encoded_projected_provenance(fail_closed)
    hostile = HostileMetadata()
    hostile_fact = valid["limited-unrelated-unreachable"]._replace(production_reachable=cast(bool, hostile))
    assert architecture._projected_provenance_is_consistent(hostile_fact) is False
    hostile_encoded = architecture._encoded_projected_provenance(hostile_fact)
    assert hostile_encoded == architecture._encoded_projected_provenance(fail_closed)
    assert architecture._canonical_production_origins(analysis._replace(findings=(*analysis.findings, hostile_encoded))) == (fail_closed,)
    assert all(count == 0 for count in hostile.counts.values())

def test_allowed_projection_overflow_facts_preserve_unrelated_until_sensitive() -> None:
    module = architecture.CANONICAL_MODULE
    pair_import = f"from {module} import CalibrationCandidatePairProjection\n"
    chronology_import = f"from {module} import StrictChronologyProjection\n"
    helper_import = f"from {module} import strict_chronology_id as forbidden\n"
    production_import = "from research_decision_engine.benchmarks import broader_calibration_evidence as production\n"
    pair_construction = "fixture = CalibrationCandidatePairProjection(adam_candidate_id='adam', comparison_group_id='group', replication_id='1', schema_version='broader-replication-calibration-candidate-pair/v1', sgd_candidate_id='sgd', world_id='world')\n"
    cases = {
        "300-local-plus-pair": (_overflow_source(300, prefix=pair_import, suffix="FixtureProjection = CalibrationCandidatePairProjection\n"), False),
        "600-local-plus-pair": (_overflow_source(600, prefix=pair_import, suffix="FixtureProjection = CalibrationCandidatePairProjection\n"), False),
        "600-local-plus-chronology": (_overflow_source(600, prefix=chronology_import, suffix="FixtureProjection = StrictChronologyProjection\n"), False),
        "600-local-plus-pair-instance": (_overflow_source(600, prefix=pair_import, suffix=pair_construction), False),
        "600-local-plus-pair-and-math": (_overflow_source(600, prefix=pair_import + "import math\n", suffix="unrelated_module = math\n"), False),
        "600-local-plus-pair-and-helper": (_overflow_source(600, prefix=pair_import + helper_import, suffix="selected = (CalibrationCandidatePairProjection, forbidden)[unknown_index]\n"), True),
        "600-local-plus-pair-and-production": (_overflow_source(600, prefix=pair_import + production_import, suffix="selected = CalibrationCandidatePairProjection if unknown_flag else production\n"), True),
    }
    observed: dict[str, tuple[architecture.ProjectedProvenance, ...]] = {}
    for case_id, (source, sensitive) in cases.items():
        facts = _projected_provenance(source)
        observed[case_id] = facts
        limits = tuple(fact for fact in facts if fact.certainty == "limited")
        if case_id == "300-local-plus-pair" and not limits:
            assert not any(fact.production_reachable for fact in facts)
            continue
        assert limits, case_id
        assert all(fact.production_reachable is sensitive for fact in limits), case_id
        assert all(fact.limit_class == ("production-sensitive" if sensitive else "unrelated") for fact in limits), case_id
    assert _projected_provenance(cases["600-local-plus-pair"][0]) == observed["600-local-plus-pair"]
    assert _projected_provenance(cases["600-local-plus-pair-and-helper"][0]) == observed["600-local-plus-pair-and-helper"]
    reversed_source = _overflow_source(600, prefix=helper_import + pair_import, suffix="selected = (forbidden, CalibrationCandidatePairProjection)[unknown_index]\n")
    reversed_limits = tuple((fact.limit_class, fact.production_reachable) for fact in _projected_provenance(reversed_source) if fact.certainty == "limited")
    forward_limits = tuple((fact.limit_class, fact.production_reachable) for fact in observed["600-local-plus-pair-and-helper"] if fact.certainty == "limited")
    assert reversed_limits == forward_limits

def test_projected_provenance_schema_preserves_all_origin_classes() -> None:
    cases = {
        "unrelated-local": "class Local:\n    value = 1\nnamespace = Local.__dict__\n",
        "unrelated-imported-module": "import math\nnamespace = math.__dict__\n",
        "unresolved-local": "local_value = unresolved_local\nescaped = getattr(local_value, dynamic_name)\n",
        "unresolved-production-sensitive": _POSSIBLE_MODULE_PREFIX + "def owner(flag):\n    return production if flag else LocalAuditOwner\nescaped = getattr(owner(unknown_flag), dynamic_name)\n",
    }
    observed = {case_id: _projected_provenance(source) for case_id, source in cases.items()}
    assert architecture.ProjectedProvenance._fields == ("lineno", "col_offset", "node_kind", "certainty", "relation", "origin_class", "production_reachable", "limit_class", "qualified_origin")
    assert all(any(fact.origin_class == case_id for fact in facts) for case_id, facts in observed.items())
    assert all(not fact.production_reachable for case_id in {"unrelated-local", "unrelated-imported-module", "unresolved-local"} for fact in observed[case_id])
    assert any(fact.origin_class == "unresolved-production-sensitive" and fact.production_reachable for fact in observed["unresolved-production-sensitive"])

def test_unrelated_and_sensitive_overflow_controls_are_complete_and_bounded() -> None:
    started = time.perf_counter()
    _assert_batch(_evaluate_batch(_OVERFLOW_CASES, architecture.harness_findings))
    fact_ids = {"overflow-unrelated-600-bindings", "overflow-sensitive-600-with-forbidden-helper"}
    facts = {case.id: _projected_provenance(case.source) for case in _OVERFLOW_CASES if case.id in fact_ids}
    unrelated = next(fact for fact in facts["overflow-unrelated-600-bindings"] if fact.limit_class == "unrelated")
    sensitive = next(fact for fact in facts["overflow-sensitive-600-with-forbidden-helper"] if fact.limit_class == "production-sensitive")
    assert len(_OVERFLOW_CASES) == 9 and unrelated.certainty == sensitive.certainty == "limited"
    assert not unrelated.production_reachable and sensitive.production_reachable
    assert time.perf_counter() - started < 15.0

def test_overflow_classification_is_deterministic_near_the_canonical_bound() -> None:
    sources = tuple(_overflow_source(width) for width in (qualified._MAX_ABSTRACT_STRUCTURE_NODES - 1, qualified._MAX_ABSTRACT_STRUCTURE_NODES, qualified._MAX_ABSTRACT_STRUCTURE_NODES + 1, 600))
    first = tuple(architecture.harness_findings(source) for source in sources)
    second = tuple(architecture.harness_findings(source) for source in sources)
    final_facts = _projected_provenance(sources[-1])
    assert first == second and all(not findings for findings in first)
    assert final_facts[-1].limit_class == "unrelated"

def test_no_fact_semantics_never_infer_production_sensitivity() -> None:
    source = "class Local:\n    value = 1\nnamespace = Local.__dict__\n"
    analysis = architecture._qualified_analysis(source, module_name=architecture.HARNESS_MODULE)
    stripped = analysis._replace(findings=tuple(finding for finding in analysis.findings if finding.code != architecture._CANONICAL_PRODUCTION_ORIGIN_CODE))
    assert architecture._canonical_production_origins(stripped) == ()
    assert architecture._harness_provenance_attributions(ast.parse(source), stripped) == ()
    assert _projected_provenance("fixture = 1\n") == ()

def test_production_sensitivity_is_monotonic_through_helpers_and_containers() -> None:
    helper = _POSSIBLE_MODULE_PREFIX + "def owner(flag):\n    return production if flag else LocalAuditOwner\nescaped = getattr(owner(unknown_flag), dynamic_name)\n"
    container = f"from {architecture.CANONICAL_MODULE} import strict_chronology_id as forbidden\ndef local(value):\n    return value\nhelpers = (forbidden, local)\nescaped = helpers[unknown_index]\n"
    for source, expected in ((helper, architecture.Finding("harness-unresolved-production-alias", "getattr")), (container, _FORBIDDEN_IDENTITY)):
        assert expected in architecture.harness_findings(source)
        assert any(architecture._production_sensitive_provenance(fact) for fact in _projected_provenance(source))

def test_provenance_join_is_branch_order_symmetric_without_benign_contamination() -> None:
    observed = []
    for body in ("return production if flag else LocalAuditOwner", "return LocalAuditOwner if flag else production"):
        source = _POSSIBLE_MODULE_PREFIX + f"def owner(flag):\n    {body}\nescaped = getattr(owner(unknown_flag), dynamic_name)\n"
        observed.append((architecture.harness_findings(source), tuple((fact.origin_class, fact.production_reachable) for fact in _projected_provenance(source) if fact.relation == "receiver")))
    unrelated = "class First:\n    pass\nclass Second:\n    pass\ndef owner(flag):\n    return First if flag else Second\nescaped = getattr(owner(unknown_flag), dynamic_name)\n"
    assert observed[0] == observed[1] and architecture.Finding("harness-unresolved-production-alias", "getattr") in observed[0][0]
    assert architecture.harness_findings(unrelated) == () and not any(fact.production_reachable for fact in _projected_provenance(unrelated))
# fmt: on


def _inert_tuple_expression(width: int, special: str | None = None) -> str:
    values = [str(index) for index in range(width)]
    if special is not None:
        assert values
        values[width // 2] = special
    return "()" if not values else f"({', '.join(values)})"


def _parsed_assignment_value(expression: str) -> ast.expr:
    statement = ast.parse(f"neutral_value = {expression}\n").body[0]
    assert isinstance(statement, ast.Assign)
    return statement.value


@pytest.mark.parametrize(
    ("width", "expected"),
    ((0, True), (32, True), (33, True), (128, True), (256, True), (257, False)),
    ids=("width-0", "width-32", "width-33", "width-128", "width-256", "width-257"),
)
def test_neutral_tuple_width_uses_canonical_container_authority(
    width: int,
    expected: bool,
) -> None:
    assert (
        architecture._p1_inert_literal(_parsed_assignment_value(_inert_tuple_expression(width)))
        is expected
    )
    assert qualified._MAX_ABSTRACT_CONTAINER_WIDTH == 256


def _nested_inert_tuple(depth: int) -> str:
    expression = "0"
    for _ in range(depth):
        expression = f"({expression},)"
    return expression


def _insert_neutral_assignment(
    source: str,
    *,
    anchor: str,
    name: str,
    expression: str,
) -> str:
    assert source.count(anchor) == 1
    return source.replace(
        anchor,
        f"    {name} = {expression}\n{anchor}",
        1,
    )


def test_neutral_schedule_positions_depth_and_sensitive_contents_are_complete() -> None:
    source = _p1_architecture_source()
    inert_128 = _inert_tuple_expression(128)
    inside_depth = _nested_inert_tuple(qualified._MAX_ABSTRACT_STRUCTURE_DEPTH - 1)
    beyond_depth = _nested_inert_tuple(qualified._MAX_ABSTRACT_STRUCTURE_DEPTH)
    schedule_cases = {
        "neutral-128-between-family-0-and-family-1": _insert_neutral_assignment(
            source,
            anchor="    count_1 = 0\n",
            name="neutral_between_0_and_1",
            expression=inert_128,
        ),
        "neutral-128-between-family-5-and-family-6": _insert_neutral_assignment(
            source,
            anchor="    count_6 = 0\n",
            name="neutral_between_5_and_6",
            expression=inert_128,
        ),
        "neutral-128-after-family-6": _insert_neutral_assignment(
            source,
            anchor="    return (\n        None,\n",
            name="neutral_after_6",
            expression=inert_128,
        ),
        "nonneutral-128-sensitive-alias": _insert_neutral_assignment(
            source,
            anchor="    count_3 = 0\n",
            name="neutral_sensitive_alias",
            expression=_inert_tuple_expression(128, "strict_chronology_id"),
        ),
    }
    observed = {
        case_id: architecture._active_p1_internal_findings(candidate)
        for case_id, candidate in schedule_cases.items()
    }
    accepted = {
        "neutral-128-between-family-0-and-family-1",
        "neutral-128-between-family-5-and-family-6",
        "neutral-128-after-family-6",
    }
    assert all(observed[case_id] == set() for case_id in accepted)
    assert (
        architecture.Finding("p1-validator-schedule", "entry-skeleton")
        in observed["nonneutral-128-sensitive-alias"]
    )
    direct_cases = {
        "nonneutral-nested-beyond-canonical-depth": beyond_depth,
        "nonneutral-128-sensitive-alias": _inert_tuple_expression(128, "strict_chronology_id"),
        "nonneutral-128-call": _inert_tuple_expression(128, "object()"),
        "nonneutral-128-dynamic-attribute": _inert_tuple_expression(
            128, "neutral_owner.dynamic_attribute"
        ),
    }
    assert all(
        not architecture._p1_inert_literal(_parsed_assignment_value(expression))
        for expression in direct_cases.values()
    )
    assert architecture._p1_inert_literal(_parsed_assignment_value(inside_depth))
    assert not architecture._p1_inert_literal(_parsed_assignment_value(beyond_depth))


# fmt: off
def _harness_correlation_findings(addition: str) -> tuple[architecture.Finding, ...]:
    source = _historical_p1_harness_source()
    return architecture.harness_findings(_harness_qualified_alias(source, addition))

def test_p1_harness_same_line_call_and_binding_correlation_is_exact() -> None:
    findings = _harness_correlation_findings("\nclass SameLineLocalHolder:\n    strict_chronology_id = object()\ndef same_line_extract(module):\n    return module.strict_chronology_id\nsame_line_local_alias = same_line_extract(SameLineLocalHolder); same_line_production_alias = same_line_extract(production_evidence)\n")
    production = architecture.Finding("harness-unresolved-production-alias", "same_line_production_alias")
    local = architecture.Finding("harness-unresolved-production-alias", "same_line_local_alias")
    assert production in findings and local not in findings

def test_p1_harness_reassigned_alias_uses_exact_call_owner() -> None:
    findings = _harness_correlation_findings("\ndef rebound_extract(module):\n    return module.strict_chronology_id\nrebound_alias = None\nrebound_alias = rebound_extract(production_evidence)\n")
    assert architecture.Finding("harness-unresolved-production-alias", "rebound_alias") in findings

def _p1_architecture_source() -> str:
    return _historical_p1_source()

def test_qualified_analysis_is_not_an_lru_cache_wrapper() -> None:
    assert type(architecture._qualified_analysis).__name__ != "_lru_cache_wrapper"

def test_no_process_global_cache_api_or_object_exists() -> None:
    assert not hasattr(architecture._qualified_analysis, "cache_info")
    assert not hasattr(architecture._qualified_analysis, "cache_clear")
    persistent = {name for name, value in vars(architecture).items() if ("cache" in name.lower() or "session" in name.lower()) and isinstance(value, (dict, list, set))}
    persistent_sessions = {name for name, value in vars(architecture).items() if isinstance(value, architecture._AnalysisSession)}
    assert persistent == persistent_sessions == set()
    source = Path(architecture.__file__).read_text(encoding="utf-8")
    assert _guard_maintenance_findings(source) == ()
    persistent_helper = source + "\n_PERSISTENT_ANALYZER = _AnalysisSession()\ndef _persistent_analyzer_helper():\n    return _PERSISTENT_ANALYZER\n"
    assert architecture.Finding("guard-maintainability", "persistent-analyzer-helper") in _guard_maintenance_findings(persistent_helper)

def test_repository_reuses_one_invocation_local_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _p1_architecture_source()
    real_analysis = architecture._source_analysis
    calls: list[tuple[str, int, bool]] = []
    def counted_analysis(candidate: str, *, module_name: str, owned: bool = False) -> architecture._SourceAnalysis:
        calls.append((module_name, len(candidate), owned))
        return real_analysis(candidate, module_name=module_name, owned=owned)
    monkeypatch.setattr(architecture, "_source_analysis", counted_analysis)
    assert architecture.repository_findings({architecture.CANONICAL_MODULE: source}, architecture.P1_MANIFEST) == ()
    assert calls == [(architecture.CANONICAL_MODULE, len(source), False)]

def test_source_a_analysis_does_not_affect_source_b() -> None:
    source_a, source_b = "alpha = 1\n", "bravo = 2\n"
    left, right = architecture._AnalysisSession(), architecture._AnalysisSession()
    analysis_a = left.qualified_analysis(source_a, module_name=architecture.CANONICAL_MODULE)
    analysis_b = right.qualified_analysis(source_b, module_name=architecture.CANONICAL_MODULE)
    assert analysis_a.source_text == source_a and analysis_b.source_text == source_b
    assert len(left._analyses) == len(right._analyses) == 1

def test_source_a_b_a_sequence_constructs_fresh_results() -> None:
    source_a, source_b = "alpha = 1\n", "bravo = 2\n"
    first, middle, last = (architecture._qualified_analysis(source, module_name=architecture.CANONICAL_MODULE) for source in (source_a, source_b, source_a))
    assert first == last and first is not last
    assert (first.source_text, middle.source_text, last.source_text) == (source_a, source_b, source_a)

def test_same_length_source_mutation_never_reuses_stale_analysis() -> None:
    source_a, source_b = "alpha = 1\n", "bravo = 2\n"
    assert len(source_a) == len(source_b) and source_a != source_b
    session = architecture._AnalysisSession()
    first = session.qualified_analysis(source_a, module_name=architecture.CANONICAL_MODULE)
    second = session.qualified_analysis(source_b, module_name=architecture.CANONICAL_MODULE)
    assert first.source_text == source_a and second.source_text == source_b
    assert len(session._analyses) == 2

def test_analysis_exception_does_not_persist_partial_state(monkeypatch: pytest.MonkeyPatch) -> None:
    source = "fixture = 1\n"
    session = architecture._AnalysisSession()
    real_analysis = architecture._source_analysis
    def failed_analysis(_candidate: str, *, module_name: str, owned: bool = False) -> architecture._SourceAnalysis:
        del owned
        raise RuntimeError(module_name)
    monkeypatch.setattr(architecture, "_source_analysis", failed_analysis)
    with pytest.raises(RuntimeError, match=architecture.CANONICAL_MODULE):
        session.qualified_analysis(source, module_name=architecture.CANONICAL_MODULE)
    assert session._analyses == {}
    monkeypatch.setattr(architecture, "_source_analysis", real_analysis)
    result = session.qualified_analysis(source, module_name=architecture.CANONICAL_MODULE)
    assert result.source_text == source and len(session._analyses) == 1

def test_independent_analysis_sessions_have_distinct_bounded_state() -> None:
    left, right = architecture._AnalysisSession(), architecture._AnalysisSession()
    assert id(left._analyses) != id(right._analyses)
    assert architecture._MAX_ANALYSES_PER_SESSION == 64
    assert (qualified._MAX_ALIAS_RESOLUTION_PASSES, qualified._MAX_PARAMETER_PROPAGATION_PASSES, qualified._MAX_LOCAL_HELPER_DEPTH, qualified._MAX_ABSTRACT_STRUCTURE_DEPTH, qualified._MAX_ABSTRACT_STRUCTURE_NODES, qualified._MAX_ABSTRACT_LOCATIONS, qualified._MAX_ABSTRACT_CONTAINER_WIDTH, qualified._MAX_ABSTRACT_FLOW_PASSES, qualified._MAX_POST_FLOW_RESOLUTION_CACHE) == (16, 16, 16, 24, 512, 512, 256, 16, 32_768)

def test_repeated_analysis_calls_are_deterministic() -> None:
    source = "fixture = 1\n"
    first = architecture._qualified_analysis(source, module_name=architecture.CANONICAL_MODULE)
    second = architecture._qualified_analysis(source, module_name=architecture.CANONICAL_MODULE)
    assert first == second and first is not second

def test_current_analysis_performance_remains_bounded() -> None:
    source = _p1_architecture_source()
    tracemalloc.start()
    started = time.perf_counter()
    findings = architecture._active_p1_internal_findings(source)
    runtime = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert findings == set() and runtime < 10.0 and peak < 512 * 1024 * 1024

@pytest.mark.parametrize("case", _GUARD_MAINTENANCE_CASES, ids=[case.id for case in _GUARD_MAINTENANCE_CASES])
def test_guard_single_authority_mutation_is_independently_attributed(case: Mutation) -> None:
    source = Path(architecture.__file__).read_text(encoding="utf-8")
    assert len(_GUARD_MAINTENANCE_CASES) == 12
    assert case.expected in _guard_maintenance_findings(case.mutate(source))

@pytest.mark.parametrize("case", _OWNED_DATAFLOW_MAINTENANCE_CASES, ids=[case.id for case in _OWNED_DATAFLOW_MAINTENANCE_CASES])
def test_active_p2_owned_dataflow_single_authority_mutation_is_attributed(case: Mutation) -> None: source = Path(architecture.__file__).read_text(encoding="utf-8"); assert len(_OWNED_DATAFLOW_MAINTENANCE_CASES) == 16; assert _owned_dataflow_maintenance_findings(source) == (); assert case.expected in _owned_dataflow_maintenance_findings(case.mutate(source))  # fmt: skip  # noqa: E702

def test_provenance_and_neutral_bound_mutations_are_independently_attributed() -> None:
    source = Path(architecture.__file__).read_text(encoding="utf-8")
    observed = tuple(
        (
            case.id,
            case.expected,
            _guard_maintenance_findings(case.mutate(source)),
        )
        for case in _PROVENANCE_BOUND_GUARD_MUTATIONS
    )
    assert len(_PROVENANCE_BOUND_GUARD_MUTATIONS) == 15
    assert all(expected in findings for _case_id, expected, findings in observed)
    prior_ids = {case.id for case in _GUARD_MAINTENANCE_CASES}
    assert {
        "guard-restore-helper-return-scanner",
        "guard-special-case-current-source-hash",
    } <= prior_ids


@pytest.mark.parametrize(
    "case",
    _PROVENANCE_CLASSIFICATION_MUTATIONS,
    ids=[case.id for case in _PROVENANCE_CLASSIFICATION_MUTATIONS],
)
def test_provenance_classification_mutation_is_independently_attributed(
    case: Mutation,
) -> None:
    source = Path(architecture.__file__).read_text(encoding="utf-8")
    assert len(_PROVENANCE_CLASSIFICATION_MUTATIONS) == 16
    assert case.expected in _guard_maintenance_findings(case.mutate(source))


@pytest.mark.parametrize(
    "case",
    _RETENTION_REACHABILITY_GUARD_MUTATIONS,
    ids=[case.id for case in _RETENTION_REACHABILITY_GUARD_MUTATIONS],
)
def test_retention_reachability_mutation_is_independently_attributed(
    case: Mutation,
) -> None:
    source = Path(architecture.__file__).read_text(encoding="utf-8")
    assert len(_RETENTION_REACHABILITY_GUARD_MUTATIONS) == 12
    assert case.expected in _retention_reachability_maintenance_findings(
        case.mutate(source)
    )


def test_provenance_codec_architecture_mutations_are_independently_attributed() -> None:
    source = Path(architecture.__file__).read_text(encoding="utf-8")
    observed: list[tuple[str, architecture.Finding, tuple[architecture.Finding, ...]]] = []
    exceptions: list[tuple[str, str]] = []
    for case in _CODEC_GUARD_MUTATIONS:
        try:
            observed.append((case.id, case.expected, _codec_maintenance_findings(case.mutate(source))))
        except BaseException as exc:
            exceptions.append((case.id, type(exc).__name__))
    missing = tuple(case_id for case_id, expected, findings in observed if expected not in findings)
    assert len(_CODEC_GUARD_MUTATIONS) == 16
    assert tuple(case.id for case in _CODEC_GUARD_MUTATIONS) == tuple(case_id for case_id, _expected, _findings in observed) + tuple(case_id for case_id, _exception in exceptions)
    assert not exceptions and not missing


def test_provenance_and_neutral_bound_single_authority_source_invariants() -> None:
    source = Path(architecture.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name: ast.get_source_segment(source, node) or ""
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    projector = functions["_canonical_production_origin_findings"]
    encoder = functions["_encoded_projected_provenance"]
    decoder = functions["_canonical_production_origins"]
    consistency = functions["_projected_provenance_is_consistent"]
    retention = functions["_retain_projected_origin"]
    reachability = functions["_production_reachable_origin"]
    classifier = functions["_harness_provenance_attributions"]
    neutral = functions["_p1_inert_literal"]
    policy_rows = _guard_origin_policy_rows(tree)
    owned_analyzers = tuple(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "_OwnedQualifiedSymbolAnalyzer"
    )
    source_analysis = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_source_analysis"
    )
    assert _guard_maintenance_findings(source) == ()
    assert _retention_reachability_maintenance_findings(source) == ()
    assert _codec_maintenance_findings(source) == ()
    assert _guard_wire_schema_fields(tree) == ("col_offset", "node_kind", "certainty", "relation", "origin_class", "production_reachable", "limit_class", "qualified_origin")
    assert len(owned_analyzers) == 1
    assert tuple(ast.unparse(base) for base in owned_analyzers[0].bases) == (
        "qualified._QualifiedSymbolAnalyzer",
    )
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "analyzer_type"
        for node in ast.walk(source_analysis)
    ) == 1
    assert not any(
        isinstance(node, ast.Call)
        and ast.unparse(node.func) == "qualified._QualifiedSymbolAnalyzer"
        for node in ast.walk(tree)
    )
    assert source.count("class OriginClassPolicy(NamedTuple):") == 1
    assert source.count("_ORIGIN_CLASS_POLICIES: Final = MappingProxyType(") == 1
    assert policy_rows == {
        "canonical-production-module": (True, True),
        "forbidden-production-helper": (True, True),
        "allowed-production-projection-class": (True, False),
        "unrelated-imported-module": (True, False),
        "unrelated-local": (True, False),
        "unresolved-local": (True, False),
        "unresolved-production-sensitive": (True, True),
    }
    assert "_PRODUCTION_REACHABLE_ORIGIN_CLASSES" not in source
    assert "_PRODUCTION_SENSITIVE_ORIGIN_CLASSES" not in source
    assert source.count("class ProjectedProvenance(NamedTuple):") == 1
    assert source.count("def _production_sensitive_provenance(") == 1
    assert ".retain_fact is True" in retention and ".production_reachable" not in retention
    assert ".production_reachable is True" in reachability and ".retain_fact" not in reachability
    assert "analyzer.flow_node_values.get(id(node))" in projector
    assert "_retain_projected_origin(origin_class(origin))" in projector
    assert "_production_reachable_origin(classified)" in projector
    assert "_merge_values" not in projector
    assert "_projected_provenance_is_consistent(fact)" in encoder
    assert "_projected_provenance_is_consistent(fact)" in decoder
    assert "type(symbol) is not str" in decoder
    assert "split(_PROJECTED_PROVENANCE_WIRE_SEPARATOR)" in decoder and "split(_PROJECTED_PROVENANCE_WIRE_SEPARATOR," not in decoder
    assert "len(parts) != len(_PROJECTED_PROVENANCE_WIRE_FIELDS)" in decoder
    assert "type(fact.production_reachable) is not bool" in consistency
    assert 'fact.limit_class == "unrelated"' in consistency
    assert 'fact.limit_class == "production-sensitive"' in consistency
    assert '"allowed-production-projection-class"' not in consistency
    assert 'dynamic_finding.code == "dynamic-call"' not in classifier
    assert "_harness_bounded_walk(" in classifier and "tuple(ast.walk(tree))" not in classifier
    assert "_production_sensitive_provenance(fact)" in classifier
    assert "if not reflection_facts:" in classifier
    assert "fact.production_reachable" in classifier
    assert "and receiver_facts:" in classifier
    assert "production-sensitive" in projector and "unrelated" in projector
    assert "qualified._MAX_ABSTRACT_CONTAINER_WIDTH" in neutral
    assert "qualified._MAX_ABSTRACT_STRUCTURE_DEPTH" in neutral
    assert "<= 32" not in neutral
    assert "hashlib.sha256(source" not in source
    overflow_source = "value = 1\n"
    overflow_analysis = architecture._qualified_analysis(overflow_source, module_name=architecture.HARNESS_MODULE)
    unrelated_limit = architecture.ProjectedProvenance(1, 0, "AnalysisLimit", "limited", "aggregate", "unresolved-local", False, "unrelated", None)
    sensitive_limit = architecture.ProjectedProvenance(1, 0, "AnalysisLimit", "limited", "aggregate", "unresolved-production-sensitive", True, "production-sensitive", architecture.CANONICAL_MODULE)
    unrelated_analysis = overflow_analysis._replace(findings=(*overflow_analysis.findings, architecture._encoded_projected_provenance(unrelated_limit)))
    sensitive_analysis = overflow_analysis._replace(findings=(*overflow_analysis.findings, architecture._encoded_projected_provenance(sensitive_limit)))
    assert architecture._harness_provenance_attributions(ast.parse(overflow_source), unrelated_analysis) == ()
    assert architecture._harness_provenance_attributions(ast.parse(overflow_source), sensitive_analysis) == (architecture.HarnessProvenanceAttribution(architecture.Finding("harness-unresolved-production-alias", "provenance-limit"), 1, architecture.CANONICAL_MODULE, "limited", "analysis:AnalysisLimit", 0, "aggregate", "unresolved-production-sensitive", True, "production-sensitive", architecture.CANONICAL_MODULE),)
    contradictory_limits = (unrelated_limit._replace(limit_class="production-sensitive"), sensitive_limit._replace(limit_class="unrelated"))
    assert all(architecture._canonical_production_origins(overflow_analysis._replace(findings=(*overflow_analysis.findings, architecture._encoded_projected_provenance(fact)))) == (architecture._malformed_projected_provenance(1),) for fact in contradictory_limits)
# fmt: on


def test_c0_exact_baseline_absence_source_scan_is_bounded() -> None:
    sources = _production_sources()
    assert sources.pop(architecture.CANONICAL_MODULE, None) is not None
    started = time.perf_counter()
    findings = architecture.repository_findings(sources, architecture.C0_MANIFEST)
    runtime = time.perf_counter() - started
    assert architecture.CANONICAL_MODULE not in sources and findings == ()
    assert runtime < 60.0


def test_manifests_literals_imports_and_helper_policies_are_exact() -> None:
    # fmt: off
    observed = tuple((item.phase, item.module_present, tuple(sorted(item.projection_classes)), tuple(sorted(item.identity_functions)), item.identity_domains, item.schemas, tuple(sorted(item.public_validators))) for item in architecture.PHASE_MANIFESTS)
    assert observed == (
        ("C0", False, (), (), (), (), ()),
        ("P1", True, ("CalibrationCandidatePairProjection", "StrictChronologyProjection"), ("calibration_candidate_pair_id", "strict_chronology_id"), (("calibration_candidate_pair_id", "validation_evidence_calibration_candidate_pair/v1"), ("strict_chronology_id", "validation_evidence_calibration_chronology/v1")), (("CalibrationCandidatePairProjection", "broader-replication-calibration-candidate-pair/v1"), ("StrictChronologyProjection", "broader-replication-calibration-chronology/v1")), ()),
        ("P2", True, ("CalibrationCandidatePairProjection", "CalibrationSourceObservationProjection", "StrictChronologyProjection"), ("calibration_candidate_pair_id", "source_observation_identity", "strict_chronology_id"), (("calibration_candidate_pair_id", "validation_evidence_calibration_candidate_pair/v1"), ("strict_chronology_id", "validation_evidence_calibration_chronology/v1"), ("source_observation_identity", "validation_evidence_calibration_source_observation/v1")), (("CalibrationCandidatePairProjection", "broader-replication-calibration-candidate-pair/v1"), ("StrictChronologyProjection", "broader-replication-calibration-chronology/v1"), ("CalibrationSourceObservationProjection", "broader-replication-calibration-source-observation/v1")), ()),
        ("P3", True, ("CalibrationCandidatePairProjection", "CalibrationSourceObservationProjection", "ScientificCalibrationSelectionProjection", "StrictChronologyProjection"), ("calibration_candidate_pair_id", "source_observation_identity", "strict_chronology_id"), (("calibration_candidate_pair_id", "validation_evidence_calibration_candidate_pair/v1"), ("strict_chronology_id", "validation_evidence_calibration_chronology/v1"), ("source_observation_identity", "validation_evidence_calibration_source_observation/v1"), ("selection_identity", "broader-calibration-history-selection/v1")), (("CalibrationCandidatePairProjection", "broader-replication-calibration-candidate-pair/v1"), ("StrictChronologyProjection", "broader-replication-calibration-chronology/v1"), ("CalibrationSourceObservationProjection", "broader-replication-calibration-source-observation/v1"), ("ScientificCalibrationSelectionProjection", None)), ()),
        ("P4", True, ("CalibrationCandidatePairProjection", "CalibrationSelectionProjection", "CalibrationSourceObservationProjection", "ScientificCalibrationSelectionProjection", "StrictChronologyProjection"), ("calibration_candidate_pair_id", "calibration_selection_id", "source_observation_identity", "strict_chronology_id"), (("calibration_candidate_pair_id", "validation_evidence_calibration_candidate_pair/v1"), ("strict_chronology_id", "validation_evidence_calibration_chronology/v1"), ("source_observation_identity", "validation_evidence_calibration_source_observation/v1"), ("selection_identity", "broader-calibration-history-selection/v1"), ("calibration_selection_id", "validation_evidence_calibration_selection/v1")), (("CalibrationCandidatePairProjection", "broader-replication-calibration-candidate-pair/v1"), ("StrictChronologyProjection", "broader-replication-calibration-chronology/v1"), ("CalibrationSourceObservationProjection", "broader-replication-calibration-source-observation/v1"), ("ScientificCalibrationSelectionProjection", None), ("CalibrationSelectionProjection", "broader-replication-calibration-selection-binding/v1")), ()),
    )
    assert tuple((item.phase, item.name, item.fields, item.field_count, item.schema) for item in architecture.PROJECTION_MANIFESTS) == (
        ("P1", "CalibrationCandidatePairProjection", ("adam_candidate_id", "comparison_group_id", "replication_id", "schema_version", "sgd_candidate_id", "world_id"), 6, "broader-replication-calibration-candidate-pair/v1"),
        ("P1", "StrictChronologyProjection", ("current_effect_excluded", "current_observation_excluded", "effect_available_sequences", "future_history_excluded", "schema_version", "source_sequence_cutoff"), 6, "broader-replication-calibration-chronology/v1"),
        ("P2", "CalibrationSourceObservationProjection", ("candidate_id", "comparison_group_id", "digest", "intervention_arm", "key_fields", "namespace", "oracle_key_id", "outcome_digest", "replication_id", "revealed_observation", "schema_version", "seed", "serialized_key_hex", "u", "world_id", "z"), 16, "broader-replication-calibration-source-observation/v1"),
        ("P3", "ScientificCalibrationSelectionProjection", ("comparison_group_id", "ddof", "effect_values", "eligibility_basis", "estimated_sigma", "namespace", "sample_count", "sample_mean", "sample_standard_deviation", "seed", "sigma_floor", "source_candidate_pairs", "source_effect_ids", "source_effect_payload_sha256", "source_observation_identities", "source_oracle_key_ids", "source_replication_ids", "source_sequence_cutoff", "study_id", "target_comparison_group_id", "world_id"), 21, None),
        ("P4", "CalibrationSelectionProjection", ("calibration_namespace", "comparison_group_id", "current_oracle_binding_id", "current_oracle_execution_id", "evidence_contract_checkpoint", "execution_specification_id", "executor_attestation_id", "implementation", "ordered_candidate_pair_ids", "ordered_candidate_pairs", "ordered_replication_ids", "ordered_source_effect_ids", "ordered_source_effects", "ordered_source_observations", "protocol_checkpoint", "schema_version", "seed", "selection_issuer_identity", "selector_result_identity", "selector_result_projection", "strict_chronology", "strict_chronology_id", "study_id", "runtime", "runtime_identity", "validation_authority_id", "validation_run_id", "world_id"), 28, "broader-replication-calibration-selection-binding/v1"),
    )
    assert tuple((item.phase, item.name, item.domain, item.stage2f_owned) for item in architecture.IDENTITY_MANIFESTS) == (
        ("P1", "calibration_candidate_pair_id", "validation_evidence_calibration_candidate_pair/v1", True),
        ("P1", "strict_chronology_id", "validation_evidence_calibration_chronology/v1", True),
        ("P2", "source_observation_identity", "validation_evidence_calibration_source_observation/v1", True),
        ("P3", "selection_identity", "broader-calibration-history-selection/v1", False),
        ("P4", "calibration_selection_id", "validation_evidence_calibration_selection/v1", True),
    )
    assert {item.name: item.fields for item in architecture.PROJECTION_MANIFESTS} == architecture.PROJECTION_FIELDS
    assert {item.name: item.field_count for item in architecture.PROJECTION_MANIFESTS} == architecture.PROJECTION_FIELD_COUNTS
    owned_manifest = architecture.OWNED_OPERATION_MANIFEST
    assert type(owned_manifest) is architecture.OwnedDataflowManifest
    assert tuple(producer.key for producer in owned_manifest.producers) == (
        "p21-coordinate", "p21-oracle-key", "p31-world", "p31-observation",
        "p31-coordinate", "p31-oracle-key", "p31-digest",
    )
    assert owned_manifest.operations._fields == (
        "key_fields", "projection_oracle_key", "selector_oracle_key",
        "paired_oracle_key", "revealed_observation",
        "projection_outcome_digest", "selector_outcome_digest",
    )
    assert tuple((edge.owner, edge.operation, edge.producer) for edge in owned_manifest.operations) == (
        ("_predicate_3o_2_1", "key-fields", "p21-coordinate"),
        ("_predicate_3o_2_1", "projection-oracle-key", "p21-oracle-key"),
        ("_predicate_3o_2_1", "selector-oracle-key", "p21-oracle-key"),
        ("_predicate_3o_2_1", "paired-oracle-key", "p21-oracle-key"),
        ("_predicate_3o_3_1", "revealed-observation", "p31-observation"),
        ("_predicate_3o_3_1", "projection-outcome-digest", "p31-digest"),
        ("_predicate_3o_3_1", "selector-outcome-digest", "p31-digest"),
    )
    assert architecture.CURRENT_MANIFEST == architecture.P3_MANIFEST
    assert architecture.FUTURE_FIXED_LITERALS == (
        ("calibration_namespace", "rde.broader.calibration-outcome/v1"), ("study", "broader-closed-loop-replication/v1"),
        ("oracle_namespace", "broader_selected_only_oracle/v1"), ("protocol_checkpoint", "89c0b4fadba33b9fd9a257b43eacf476b7779d59"),
        ("evidence_contract_checkpoint", "cbeea072ed39697e2cd42ca571685faed5f6ead8"), ("source_sequence_cutoff", 1),
        ("pair_arm_order", ("adam", "sgd")), ("replications", (1, 2, 3, 4, 5)),
    )
    assert {
        "C0": frozenset(),
        "P1": architecture._names("calibration_namespace study source_sequence_cutoff pair_arm_order replications"),
        "P2": architecture._names("calibration_namespace study oracle_namespace source_sequence_cutoff pair_arm_order replications"),
        "P3": architecture._names("calibration_namespace study oracle_namespace source_sequence_cutoff pair_arm_order replications"),
        "P4": frozenset(key for key, _ in architecture.FUTURE_FIXED_LITERALS),
    } == architecture._PHASE_FIXED_LITERAL_KEYS
    expected_imports = {
        "__future__": architecture._names("annotations"), "dataclasses": architecture._names("dataclass"), "hashlib": architecture._names("sha256"),
            "typing": architecture._names("Final Literal NamedTuple NoReturn TYPE_CHECKING"), "math": architecture._names("isfinite"),
        "statistics": architecture._names("mean stdev"), "unicodedata": architecture._names("normalize"), "research_decision_engine.belief_models": architecture._names("SIGMA_FLOOR MatchedEffectObservation"),
        "research_decision_engine.benchmarks.broader_protocol": architecture._names("PROTOCOL_VERSION canonical_json_bytes f64 protocol_hash runtime_id"),
        "research_decision_engine.benchmarks.broader_execution": architecture._names("ExecutorAttestationProjection ReturnedResultsProjection decode_executor_attestation_projection execution_instance_identity execution_id submitted_jobs_sha256 execution_start_id worker_identity returned_result_id result_batch_id execution_completion_id returned_results_sha256 worker_result_order_sha256 executor_attestation_id validate_stage2d2_execution_foundations validate_stage2d2_returned_results validate_stage2d2_result_batch_completion validate_stage2d2_result_aggregates validate_stage2e_executor_attestation"),
        "research_decision_engine.benchmarks.broader_returned_run": architecture._names("ProvenanceValueProjection ReturnedRunProjection RunCalibrationEstimateProjection RunCalibrationProjection RunMatchedEffectProjection RunObservationAuthorizationProjection RunProvenanceProjection RunRevealedObservationProjection decode_run_matched_effect_projection reconstruct_matched_effect validate_returned_run_projection_shape"),
        "research_decision_engine.benchmarks.broader_calibration_selector_replay": architecture._names("raw_effect_sha256 replay_calibration_history_selection"),
        "research_decision_engine.benchmarks.broader_calibration_history": architecture._names("CALIBRATION_ELIGIBILITY_BASIS CALIBRATION_SELECTION_VERSION CALIBRATION_SIGMA_DDOF CALIBRATION_SOURCE_SEQUENCE_CUTOFF CalibrationHistorySelection RunProvenanceError expected_calibration_effect"),
        "research_decision_engine.benchmarks.broader_oracle": architecture._names("CALIBRATION_NAMESPACE ORACLE_VERSION RevealedObservation calibration_key transform_key _parse_calibration_candidate"),
            "research_decision_engine.benchmarks.broader_worlds": architecture._names("GROUP_IDS WORLDS_BY_ID BenchmarkWorld HiddenWorldParameters PublicWorldDefinition candidate_costs hidden_arm_mean hidden_observation_sigma"),
    }
    assert expected_imports == architecture.ALLOWED_IMPORTS
    assert architecture._P3_PRIVATE_MODULE_IMPORTS == {"hashlib": "_hashlib", "statistics": "_statistics", "unicodedata": "_unicodedata"}
    expected_pure = architecture._names("builtins.abs builtins.enumerate builtins.float builtins.len builtins.list builtins.max builtins.min builtins.ord builtins.range builtins.round builtins.sorted builtins.tuple dataclasses.dataclass hashlib.sha256 math.isfinite statistics.mean statistics.stdev unicodedata.normalize") | frozenset(f"{module}.{name}" for module, names in expected_imports.items() for name in names if name[0].islower() or name.startswith("_"))
    assert expected_pure == architecture.PURE_HELPER_CALLS
    assert architecture._names("asyncio git http importlib multiprocessing os pathlib pickle shutil socket sqlite3 subprocess tempfile urllib") == architecture.FORBIDDEN_IMPORT_ROOTS
    assert architecture._names("research_decision_engine.storage research_decision_engine.benchmarks.broader_artifacts research_decision_engine.benchmarks.broader_assembly research_decision_engine.benchmarks.broader_lifecycle research_decision_engine.benchmarks.broader_lifecycle_io research_decision_engine.benchmarks.broader_lifecycle_records research_decision_engine.benchmarks.broader_validation research_decision_engine.benchmarks.broader_validation_evidence") == architecture.FORBIDDEN_IMPORT_MODULES
    p2_required = architecture._names("research_decision_engine.benchmarks.broader_protocol.runtime_id research_decision_engine.benchmarks.broader_protocol.protocol_hash research_decision_engine.benchmarks.broader_calibration_evidence.source_observation_identity")
    p3_required = p2_required | architecture._names("research_decision_engine.benchmarks.broader_calibration_selector_replay.replay_calibration_history_selection")
    raw = frozenset({f"{architecture._REPLAY}.raw_effect_sha256"})
    p1_pure = architecture._names("research_decision_engine.benchmarks.broader_protocol.f64 research_decision_engine.benchmarks.broader_oracle._parse_calibration_candidate")
    assert p1_pure == architecture._P1_PURE_HELPERS
    p2_pure = architecture._names("research_decision_engine.benchmarks.broader_protocol.f64 research_decision_engine.benchmarks.broader_oracle.calibration_key research_decision_engine.benchmarks.broader_oracle.transform_key research_decision_engine.benchmarks.broader_oracle._parse_calibration_candidate research_decision_engine.benchmarks.broader_worlds.hidden_arm_mean research_decision_engine.benchmarks.broader_worlds.hidden_observation_sigma")
    assert p2_pure == architecture._P2_PURE_HELPERS
    assert {"C0": frozenset(), "P1": raw, "P2": p2_required | raw, "P3": p3_required | raw, "P4": p3_required | raw} == architecture._PHASE_REQUIRED_CALLS
    assert {"C0": frozenset(), "P1": raw | p1_pure | frozenset({architecture._PROTOCOL_HASH_TARGET}), "P2": p2_required | raw | p2_pure, "P3": p3_required | raw | p2_pure, "P4": p3_required | raw | p2_pure} == architecture._PHASE_ALLOWED_CALLS
    # fmt: on


@pytest.mark.parametrize(
    "manifest",
    architecture.PHASE_MANIFESTS[1:],
    ids=[manifest.phase for manifest in architecture.PHASE_MANIFESTS[1:]],
)
def test_each_inert_future_manifest_accepts_its_exact_hypothetical_surface(
    manifest: architecture.PhaseManifest,
) -> None:
    assert architecture.future_source_findings(_future_source(manifest), manifest) == ()


def test_future_helper_provenance_and_fixed_relations_fail_closed() -> None:
    # fmt: off
    assert architecture.future_source_findings(_future_source(architecture.P1_MANIFEST), architecture.P1_MANIFEST) == ()
    framed_raw = _future_source(architecture.P1_MANIFEST).replace("return _raw_effect_sha256(effect)", "return _protocol_hash('raw/v1', effect)")
    assert {architecture.Finding("required-pure-helper", f"{architecture._REPLAY}.raw_effect_sha256"), architecture.Finding("nonidentity-protocol-hash", "_effect_payload_sha256")} <= set(architecture.future_source_findings(framed_raw, architecture.P1_MANIFEST))
    p3_without_replay = _future_source(architecture.P3_MANIFEST).replace("_replay_calibration_history_selection(", "_missing_replay(", 1) + "\ndef _decoy(history):\n return _replay_calibration_history_selection(history)"
    assert {architecture.Finding("required-pure-helper", f"{architecture._REPLAY}.replay_calibration_history_selection"), architecture.Finding("generic-replay-authority", "_replay_calibration_history_selection")} <= set(architecture.future_source_findings(p3_without_replay, architecture.P3_MANIFEST)) and architecture.Finding("required-pure-helper", f"{architecture._REPLAY}.replay_calibration_history_selection") in architecture.future_source_findings(_future_source(architecture.P3_MANIFEST).replace("run_id=replay_run_id", "run_id=None"), architecture.P3_MANIFEST)
    p1_with_replay = _future_source(architecture.P1_MANIFEST).replace("from research_decision_engine.benchmarks.broader_protocol", f"from {architecture._REPLAY} import replay_calibration_history_selection as _replay\nfrom research_decision_engine.benchmarks.broader_protocol")
    assert architecture.Finding("unexpected-phase-helper", f"{architecture._REPLAY}.replay_calibration_history_selection") in architecture.future_source_findings(p1_with_replay, architecture.P1_MANIFEST)
    assert architecture.Finding("nonidentity-protocol-hash", "_outcome") in architecture.future_source_findings(_future_source(architecture.P1_MANIFEST) + "\ndef _outcome(oracle_key_id, revealed_observation):\n return _protocol_hash('revealed_outcome/v1', {'oracle_key_id': oracle_key_id, 'revealed_observation': revealed_observation})", architecture.P1_MANIFEST) and architecture.Finding("second-identity-algebra", "_runtime_id") in architecture.future_source_findings(_future_source(architecture.P1_MANIFEST).replace("import protocol_hash as _protocol_hash", "import protocol_hash as _protocol_hash, runtime_id as _runtime_id") + "\ndef _oracle_key(key_fields):\n return _runtime_id('oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})", architecture.P1_MANIFEST)
    benign_comparison = _future_source(architecture.P4_MANIFEST) + "\ndef _matches(projection, expected):\n return calibration_selection_id(projection) == expected\ndef _matches_checkpoint(value):\n return value.protocol_checkpoint == _PROTOCOL_CHECKPOINT\ndef _differs_checkpoint(value):\n return value.protocol_checkpoint != '89c0b4fadba33b9fd9a257b43eacf476b7779d59'\ndef _same_selection(value, expected):\n return value.selection_identity == expected\ndef _oracle_key(key_fields):\n return _runtime_id('oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})\ndef _outcome(oracle_key_id, revealed_observation):\n return _protocol_hash('revealed_outcome/v1', {'oracle_key_id': oracle_key_id, 'revealed_observation': revealed_observation})\ndef _frozen_identities(oracle_key_id: str, source_oracle_key_ids: tuple[str, ...], selector_result_identity: str, validation_authority_id: str, executor_attestation_id: str, worker_identity: str, oracleKeyId: str, workerIdentity: str):\n return (oracle_key_id, source_oracle_key_ids, selector_result_identity, validation_authority_id, executor_attestation_id, worker_identity, oracleKeyId, workerIdentity)"
    assert architecture.future_source_findings(benign_comparison, architecture.P4_MANIFEST) == ()
    # fmt: on


# fmt: off
_OWNER_CASES = (Case("wrong-owner-execution", architecture._EXECUTION, "CalibrationCandidatePairProjection"), Case("wrong-owner-returned-run", architecture._RETURNED, "StrictChronologyProjection"), Case("wrong-owner-calibration-history", architecture._HISTORY, "CalibrationSourceObservationProjection"))
_PREMATURE_CASES = (Case("premature-candidate-pair", "class CalibrationCandidatePairProjection:\n pass", "premature-projection"), Case("premature-chronology", "class StrictChronologyProjection:\n pass", "premature-projection"), Case("premature-p1-identities-domains", "def calibration_candidate_pair_id():\n pass\n\"validation_evidence_calibration_candidate_pair/v1\"\ndef strict_chronology_id():\n pass\n\"validation_evidence_calibration_chronology/v1\"", "premature-identity"), Case("premature-p2-p3-p4", "class CalibrationSourceObservationProjection:\n pass\nclass ScientificCalibrationSelectionProjection:\n pass\nclass CalibrationSelectionProjection:\n pass\ndef validate_stage2f_calibration_evidence():\n pass\n\"validation_evidence_calibration_source_observation/v1\"\n\"validation_evidence_calibration_selection/v1\"", "premature-projection"), Case("second-selector-and-final-identities", "def scientific_calibration_selection_id():\n pass\ndef final_calibration_aggregate_id():\n pass", "premature-identity-alias"))
_ALIAS_CASES = (Case("assignment-alias", "\nAliasProjection = CalibrationSelectionProjection", "stage2f-assignment-alias"), Case("import-alias", "\nfrom elsewhere import CalibrationSelectionProjection as _Alias", "stage2f-import-alias"), Case("two-hop-alias", "\n_First = CalibrationSelectionProjection\n_Second = _First", "stage2f-assignment-alias"), Case("dynamic-class-factory", "\n_Dynamic = type(\"OtherProjection\", (), {})", "dynamic-construction"), Case("dynamic-identity-helper", "\n_dynamic_identity = lambda value: value", "dynamic-function"), Case("dunder-all", "\n__all__ = (\"CalibrationSelectionProjection\",)", "dynamic-export-surface"), Case("module-getattr", "\ndef __getattr__(name):\n return name", "dynamic-module-hook"), Case("module-dir", "\ndef __dir__():\n return ()", "dynamic-module-hook"))
_OPERATION_CASES = (Case("production-selector-call", "\ndef _bad():\n return select_calibration_history()", "forbidden-sensitive-call"), Case("live-oracle-call", "\ndef _bad(oracle):\n return oracle.reobserve()", "forbidden-sensitive-call"), Case("authorization-issuance", "\ndef _bad():\n return authorize_observation()", "forbidden-sensitive-call"), Case("registry-access-mutation", "\ndef _bad(registry):\n registry.register(\"x\")", "registry-state"), Case("runner-worker-workload", "\ndef _bad(worker):\n return worker.run_arm()", "forbidden-sensitive-call"), Case("reader-evidence-persistence-sqlite", "\nfrom research_decision_engine.benchmarks.broader_lifecycle import Reader as _Reader\nfrom research_decision_engine.benchmarks.broader_validation_evidence import write_evidence as _write_evidence\nimport sqlite3\n\ndef _bad():\n _write_evidence()\n return sqlite3.connect(\"x\")", "forbidden-import"), Case("subprocess-network-environment-git-filesystem", "\nimport subprocess\nimport socket\nimport os\nimport pathlib\nimport git", "forbidden-import"))
_MUTATIONS = (Mutation("wrong-schema-literal", _replace("broader-replication-calibration-selection-binding/v1", "broader-replication-calibration-selection-binding/v2"), architecture.Finding("schema-literal", "CalibrationSelectionProjection")), Mutation("wrong-identity-domain", _replace("validation_evidence_calibration_selection/v1", "validation_evidence_calibration_selection/v2"), architecture.Finding("identity-domain", "calibration_selection_id")), Mutation("wrong-fixed-protocol-literal", _replace("89c0b4fadba33b9fd9a257b43eacf476b7779d59", "0bd025b696a31bdf5f71e80b275542de1b50ffdb"), architecture.Finding("fixed-literal", "protocol_checkpoint")), Mutation("raw-sha-replaced-by-framed-hash", _append("\ndef _bad(projection):\n return ScientificCalibrationSelectionProjection(source_effect_payload_sha256=_protocol_hash(\"raw/v1\", projection))"), architecture.Finding("nonidentity-protocol-hash", "_bad")), Mutation("second-hash-algebra", _append("\nimport hashlib\n\ndef _bad(value):\n return hashlib.sha256(value)"), architecture.Finding("second-hash-algebra", "hashlib.sha256")), Mutation("repr-asdict-pickle-identity", _append("\ndef _bad(value):\n return (repr(value), dataclasses.asdict(value), pickle.dumps(value))"), architecture.Finding("identity-serialization", "repr")), Mutation("caller-validator-factory-variadic", _caller_mutation, architecture.Finding("caller-authority-parameter", "calibration_selection_id:validator")))
_LATER_CASES = (Case("later-reader-evidence-finalization", "\nclass ReaderReconciliationProjection:\n pass\nclass CalibrationEvidenceBundleProjection:\n pass\nclass CalibrationBindingProjection:\n pass\nclass EvidenceMemberInventory:\n pass\nclass FinalizationWriter:\n pass\nvalidation_bindings_writer = object()\nfinal_content_root = \"root\"\nfinal_manifest_binding = \"manifest\"\n_BINDINGS = \"validation_bindings.json\"", "later-stage-binding"), Case("later-stage3-authority-and-aggregate", "\ndef bounded_validation_authorization():\n pass\ndef full_replication_authorization():\n pass\nclass CalibrationFinalAggregateProjection:\n pass\nfull_replication = True", "later-stage-binding"))
_OWNER_ISOLATED = {
    "wrong-owner-execution": (("stage2e-source-field", "class ExecutorAttestationProjection:\n source_observation_identity: str", architecture.Finding("stage2e-calibration-field", architecture._EXECUTION)), ("second-identity-owner", "def scientific_calibration_selection_id(value):\n return value", architecture.Finding("wrong-module-owner", f"{architecture._EXECUTION}:scientific_calibration_selection_id")), ("private-second-identity-owner", "def _scientific_calibration_selection_id(value):\n return value", architecture.Finding("wrong-module-owner", f"{architecture._EXECUTION}:_scientific_calibration_selection_id")), ("selector-result-owner", "def calibration_selector_result_id(value):\n return value", architecture.Finding("wrong-module-owner", f"{architecture._EXECUTION}:calibration_selector_result_id")), ("final-aggregate-owner", "def final_calibration_aggregate_id(value):\n return value", architecture.Finding("wrong-module-owner", f"{architecture._EXECUTION}:final_calibration_aggregate_id")), ("module-name-dynamic-import", f"_TARGET = {architecture.CANONICAL_MODULE!r}\ndef _scope():\n return __import__(_TARGET)", architecture.Finding("wrong-module-alias", f"{architecture._EXECUTION}:__import__")), ("local-name-dynamic-import", f"def _scope():\n target = {architecture.CANONICAL_MODULE!r}\n return __import__(target)", architecture.Finding("wrong-module-alias", f"{architecture._EXECUTION}:__import__")), ("two-hop-import-module", f"def _scope(import_module):\n target = {architecture.CANONICAL_MODULE!r}\n other = target\n return import_module(other)", architecture.Finding("wrong-module-alias", f"{architecture._EXECUTION}:import_module")), ("dynamic-owner-install", '_n = "Calibration" + "SelectionProjection"\nglobals()[_n] = type(_n, (), {})', architecture.Finding("wrong-module-owner", f"{architecture._EXECUTION}:dynamic-stage2f-surface"))),
    "wrong-owner-returned-run": (("canonical-module-alias", f"import {architecture.CANONICAL_MODULE} as _impl", architecture.Finding("wrong-module-alias", f"{architecture._RETURNED}:_impl")), ("canonical-module-bare-import", f"import {architecture.CANONICAL_MODULE}", architecture.Finding("wrong-module-alias", f"{architecture._RETURNED}:{architecture.CANONICAL_MODULE}")), ("package-module-alias", "from research_decision_engine.benchmarks import broader_calibration_evidence as _impl", architecture.Finding("wrong-module-alias", f"{architecture._RETURNED}:_impl")), ("nested-package-module-alias", "def _scope():\n from research_decision_engine.benchmarks import broader_calibration_evidence as _impl", architecture.Finding("wrong-module-alias", f"{architecture._RETURNED}:_impl")), ("nested-canonical-module-alias", f"if True:\n import {architecture.CANONICAL_MODULE} as _impl", architecture.Finding("wrong-module-alias", f"{architecture._RETURNED}:_impl")), ("relative-module-alias", "from . import broader_calibration_evidence as _impl", architecture.Finding("wrong-module-alias", f"{architecture._RETURNED}:_impl")), ("relative-submodule-star", "from .broader_calibration_evidence import *", architecture.Finding("wrong-module-alias", f"{architecture._RETURNED}:*")), ("canonical-star-export", f"from {architecture.CANONICAL_MODULE} import *", architecture.Finding("wrong-module-alias", f"{architecture._RETURNED}:*")), ("nested-dynamic-import", f"def _scope():\n return __import__({architecture.CANONICAL_MODULE!r})", architecture.Finding("wrong-module-alias", f"{architecture._RETURNED}:__import__"))),
    "wrong-owner-calibration-history": (("lambda-identity", "calibration_selection_id = lambda value: value", architecture.Finding("wrong-module-owner", f"{architecture._HISTORY}:calibration_selection_id")), ("wrong-owner-private-subclass", f"from {architecture.CANONICAL_MODULE} import CalibrationSelectionProjection as _Projection\nclass _Alias(_Projection):\n pass", architecture.Finding("wrong-module-alias", f"{architecture._HISTORY}:_Projection")), ("private-wrapper", f"from {architecture.CANONICAL_MODULE} import calibration_selection_id as _identity\ndef _alias(value):\n return _identity(value)", architecture.Finding("wrong-module-alias", f"{architecture._HISTORY}:_identity")), ("private-normalized-projection", "class _CalibrationSelectionProjection:\n pass", architecture.Finding("wrong-module-owner", f"{architecture._HISTORY}:_CalibrationSelectionProjection")), ("private-normalized-identity", "def _calibration_selection_id(value):\n return value", architecture.Finding("wrong-module-owner", f"{architecture._HISTORY}:_calibration_selection_id")), ("uppercase-normalized-identity", "def _CALIBRATION_SELECTION_ID(value):\n return value", architecture.Finding("wrong-module-owner", f"{architecture._HISTORY}:_CALIBRATION_SELECTION_ID")), ("interspersed-projection-name", "Calibration_Selection_Projection = object", architecture.Finding("wrong-module-owner", f"{architecture._HISTORY}:Calibration_Selection_Projection"))),
}
_ISOLATED_C0 = {
    "premature-p1-identities-domains": (Mutation("pair-identity", lambda _: "def calibration_candidate_pair_id():\n pass", architecture.Finding("premature-identity", "calibration_candidate_pair_id")), Mutation("chronology-identity", lambda _: "def strict_chronology_id():\n pass", architecture.Finding("premature-identity", "strict_chronology_id")), Mutation("pair-domain", lambda _: '_CALIBRATION_CANDIDATE_PAIR_ID_DOMAIN = "validation_evidence_calibration_candidate_pair/v1"', architecture.Finding("premature-domain", "validation_evidence_calibration_candidate_pair/v1")), Mutation("chronology-domain", lambda _: '_STRICT_CHRONOLOGY_ID_DOMAIN = "validation_evidence_calibration_chronology/v1"', architecture.Finding("premature-domain", "validation_evidence_calibration_chronology/v1"))),
    "premature-p2-p3-p4": (Mutation("source-class", lambda _: "class CalibrationSourceObservationProjection:\n pass", architecture.Finding("premature-projection", "CalibrationSourceObservationProjection")), Mutation("source-domain", lambda _: '_SOURCE_OBSERVATION_IDENTITY_DOMAIN = "validation_evidence_calibration_source_observation/v1"', architecture.Finding("premature-domain", "validation_evidence_calibration_source_observation/v1")), Mutation("scientific-class", lambda _: "class ScientificCalibrationSelectionProjection:\n pass", architecture.Finding("premature-projection", "ScientificCalibrationSelectionProjection")), Mutation("final-class", lambda _: "class CalibrationSelectionProjection:\n pass", architecture.Finding("premature-projection", "CalibrationSelectionProjection")), Mutation("final-domain", lambda _: '_CALIBRATION_SELECTION_ID_DOMAIN = "validation_evidence_calibration_selection/v1"', architecture.Finding("premature-domain", "validation_evidence_calibration_selection/v1")), Mutation("public-validator", lambda _: "def validate_stage2f_calibration_evidence():\n pass", architecture.Finding("premature-validator", "validate_stage2f_calibration_evidence"))),
    "second-selector-and-final-identities": (Mutation("selector-alias", lambda _: "def scientific_calibration_selection_id():\n pass", architecture.Finding("premature-identity-alias", "scientific_calibration_selection_id")), Mutation("final-aggregate-id", lambda _: "def final_calibration_aggregate_id():\n pass", architecture.Finding("premature-identity-alias", "final_calibration_aggregate_id"))),
}
_ISOLATED_FUTURE = {
    "assignment-alias": (Mutation("public-nonliteral-binding", _append("\n_PRIVATE = 1\nPublicLeak = _PRIVATE"), architecture.Finding("public-export-surface", "P4")), Mutation("exact-public-rebind", _append("\nCalibrationSelectionProjection = 1"), architecture.Finding("public-export-surface", "P4"))),
    "two-hop-alias": (Mutation("private-subclass", _append("\nclass _Alias(CalibrationSelectionProjection):\n pass"), architecture.Finding("stage2f-subclass-alias", "_Alias")), Mutation("nested-private-subclass", _append("\ndef _scope():\n class _Alias(CalibrationSelectionProjection):\n  pass"), architecture.Finding("stage2f-subclass-alias", "_Alias")), Mutation("private-projection-duplicate", _append("\nclass _CalibrationSelectionProjection:\n pass"), architecture.Finding("stage2f-assignment-alias", "_CalibrationSelectionProjection")), Mutation("private-identity-duplicate", _append("\ndef _calibration_selection_id(projection):\n return projection"), architecture.Finding("stage2f-assignment-alias", "_calibration_selection_id")), Mutation("normalized-identity-duplicate", _append("\ndef _CALIBRATION_SELECTION_ID(projection):\n return projection"), architecture.Finding("stage2f-assignment-alias", "_CALIBRATION_SELECTION_ID")), Mutation("private-identity-wrapper", _append("\ndef _alias(projection):\n return calibration_selection_id(projection)"), architecture.Finding("stage2f-wrapper-alias", "_alias")), Mutation("callable-class-wrapper", _append("\nclass _Alias:\n def __call__(self, projection):\n  return calibration_selection_id(projection)"), architecture.Finding("stage2f-wrapper-alias", "__call__")), Mutation("nested-identity-wrapper", _append("\ndef _outer():\n def _alias(projection):\n  return calibration_selection_id(projection)\n return _alias"), architecture.Finding("stage2f-wrapper-alias", "_alias")), Mutation("returned-identity-function", _append("\ndef _alias():\n return calibration_selection_id"), architecture.Finding("stage2f-wrapper-alias", "_alias")), Mutation("multistatement-wrapper", _append("\ndef _alias(projection):\n value = calibration_selection_id(projection)\n return value"), architecture.Finding("stage2f-wrapper-alias", "_alias")), Mutation("two-hop-wrapper", _append("\ndef _alias(projection):\n first = calibration_selection_id(projection)\n second = first\n return second"), architecture.Finding("stage2f-wrapper-alias", "_alias")), Mutation("container-intermediate-wrapper", _append("\ndef _alias(projection):\n first = calibration_selection_id(projection)\n second = [first]\n return second"), architecture.Finding("stage2f-wrapper-alias", "_alias")), Mutation("ifexp-wrapper", _append("\ndef _alias(projection):\n return calibration_selection_id(projection) if projection else None"), architecture.Finding("stage2f-wrapper-alias", "_alias")), Mutation("boolop-wrapper", _append("\ndef _alias(projection):\n return calibration_selection_id(projection) or projection"), architecture.Finding("stage2f-wrapper-alias", "_alias")), Mutation("subscript-wrapper", _append("\ndef _alias(projection):\n return [calibration_selection_id(projection)][0]"), architecture.Finding("stage2f-wrapper-alias", "_alias")), Mutation("namedexpr-wrapper", _append("\ndef _alias(projection):\n return (value := calibration_selection_id(projection))"), architecture.Finding("stage2f-wrapper-alias", "_alias")), Mutation("mapping-alias", _append("\n_IDENTITIES = {'selection': calibration_selection_id}"), architecture.Finding("stage2f-mapping-alias", "calibration_selection_id")), Mutation("local-mapping-alias", _append("\ndef _alias():\n return {'selection': calibration_selection_id}"), architecture.Finding("stage2f-mapping-alias", "calibration_selection_id")), Mutation("swapped-replay-keywords", _replace("run_id=run_id, world_id=world_id", "run_id=world_id, world_id=run_id"), architecture.Finding("scientific-selection-provenance", "ScientificCalibrationSelectionProjection")), Mutation("duplicate-replay-keyword", _replace("run_id=run_id, world_id=world_id", "run_id=run_id, run_id=world_id"), architecture.Finding("scientific-selection-provenance", "ScientificCalibrationSelectionProjection")), Mutation("replay-result-early-return", _replace("    return ScientificCalibrationSelectionProjection(", "    if run_id:\n        return selection\n    return ScientificCalibrationSelectionProjection("), architecture.Finding("scientific-selection-provenance", "ScientificCalibrationSelectionProjection")), Mutation("replay-result-yield", _replace("    return ScientificCalibrationSelectionProjection(", "    if run_id:\n        yield selection\n    return ScientificCalibrationSelectionProjection("), architecture.Finding("scientific-selection-provenance", "ScientificCalibrationSelectionProjection")), Mutation("replay-alias-early-return", _replace("    return ScientificCalibrationSelectionProjection(", "    alias = selection\n    if run_id:\n        return alias\n    return ScientificCalibrationSelectionProjection("), architecture.Finding("scientific-selection-provenance", "ScientificCalibrationSelectionProjection")), Mutation("replay-attribute-store", _replace("    return ScientificCalibrationSelectionProjection(", "    holder.value = selection\n    return ScientificCalibrationSelectionProjection("), architecture.Finding("object-state-mutation", "Assign")), Mutation("replay-subscript-store", _replace("    return ScientificCalibrationSelectionProjection(", "    holder[0] = selection\n    return ScientificCalibrationSelectionProjection("), architecture.Finding("object-state-mutation", "Assign")), Mutation("scientific-selection-id-alias", _append("\ndef _scientific_calibration_selection_id(selection):\n return selection.selection_identity"), architecture.Finding("premature-identity-alias", "_scientific_calibration_selection_id")), Mutation("selector-result-id-alias", _append("\ndef _calibration_selector_result_id(selection):\n return selection.selection_identity"), architecture.Finding("premature-identity-alias", "_calibration_selector_result_id")), Mutation("final-aggregate-id-alias", _append("\ndef _final_calibration_aggregate_id(selection):\n return selection.selection_identity"), architecture.Finding("premature-identity-alias", "_final_calibration_aggregate_id")), Mutation("binding-id-alias", _append("\ndef _calibration_binding_id(selection):\n return selection.selection_identity"), architecture.Finding("premature-identity-alias", "_calibration_binding_id")), Mutation("arbitrary-selection-id", _append("\ndef _selection_id(selection):\n return selection.selection_identity"), architecture.Finding("premature-identity-alias", "_selection_id")), Mutation("arbitrary-selector-result-id", _append("\ndef _selector_result_id(selection):\n return selection.selector_result_identity"), architecture.Finding("premature-identity-alias", "_selector_result_id")), Mutation("selection-identity-attribute-wrapper", _append("\ndef _identity_alias(selection):\n return selection.selection_identity"), architecture.Finding("stage2f-wrapper-alias", "_identity_alias")), Mutation("selector-result-identity-attribute-wrapper", _append("\ndef _identity_alias(selection):\n return selection.selector_result_identity"), architecture.Finding("stage2f-wrapper-alias", "_identity_alias")), Mutation("stage2f-runtime-id", lambda source: source.replace("import protocol_hash as _protocol_hash", "import protocol_hash as _protocol_hash, runtime_id as _runtime_id") + "\ndef _identity_alias(projection):\n return _runtime_id('selection', 'broader-calibration-history-selection/v1', projection)", architecture.Finding("second-identity-algebra", "_runtime_id")), Mutation("aliased-stage2f-runtime-id", lambda source: source.replace("import protocol_hash as _protocol_hash", "import protocol_hash as _protocol_hash, runtime_id as _runtime_id") + "\ndef _identity_alias(projection):\n return _runtime_id('selection', _SELECTION_IDENTITY_DOMAIN, projection)", architecture.Finding("second-identity-algebra", "_runtime_id"))),
    "dynamic-class-factory": (Mutation("projection-decorator", _replace("class CalibrationSelectionProjection:", "@_factory\nclass CalibrationSelectionProjection:"), architecture.Finding("unapproved-projection-decorator", "CalibrationSelectionProjection")), Mutation("projection-metaclass", _replace("class CalibrationSelectionProjection:", "class CalibrationSelectionProjection(metaclass=_Meta):"), architecture.Finding("dynamic-construction", "CalibrationSelectionProjection")), Mutation("private-metaclass", _append("\nclass _Dynamic(metaclass=_Meta):\n pass"), architecture.Finding("dynamic-construction", "_Dynamic")), Mutation("nested-private-class", _append("\ndef _maker():\n class _Dynamic:\n  pass\n return _Dynamic"), architecture.Finding("dynamic-construction", "_Dynamic")), Mutation("dynamic-base-call", _append("\nclass _Dynamic(_factory()):\n pass"), architecture.Finding("dynamic-construction", "_Dynamic")), Mutation("private-class-decorator", _append("\n@_factory\nclass _Dynamic:\n pass"), architecture.Finding("dynamic-construction", "_Dynamic"))),
    "dynamic-identity-helper": (Mutation("identity-decorator", _replace("def calibration_selection_id(projection):", "@_factory\ndef calibration_selection_id(projection):"), architecture.Finding("decorated-public-api", "calibration_selection_id")), Mutation("nested-generated-public-function", _append("\ndef _maker():\n def UnexpectedPublic():\n  return None\n return UnexpectedPublic"), architecture.Finding("dynamic-function", "UnexpectedPublic")), Mutation("nested-generated-public-async", _append("\ndef _maker():\n async def UnexpectedPublic():\n  return None\n return UnexpectedPublic"), architecture.Finding("dynamic-function", "UnexpectedPublic")), Mutation("local-domain-runtime-id", lambda source: source.replace("import protocol_hash as _protocol_hash", "import protocol_hash as _protocol_hash, runtime_id as _runtime_id") + "\ndef _identity_alias(projection):\n domain = 'validation_evidence_calibration_selection/v1'\n return _runtime_id('selection', domain, projection)", architecture.Finding("second-identity-algebra", "_runtime_id")), Mutation("two-hop-domain-runtime-id", lambda source: source.replace("import protocol_hash as _protocol_hash", "import protocol_hash as _protocol_hash, runtime_id as _runtime_id") + "\ndef _identity_alias(projection):\n domain = 'validation_evidence_calibration_selection/v1'\n other = domain\n return _runtime_id('selection', other, projection)", architecture.Finding("second-identity-algebra", "_runtime_id")), Mutation("identity-attribute-local", _append("\ndef _alias(selection):\n value = selection.selection_identity\n return value"), architecture.Finding("stage2f-wrapper-alias", "_alias")), Mutation("identity-attribute-two-hop", _append("\ndef _alias(selection):\n value = selection.selector_result_identity\n other = value\n return other"), architecture.Finding("stage2f-wrapper-alias", "_alias")), Mutation("replay-owner-no-parameters", _replace("def _scientific_selection(run_id, world_id, seed, comparison_group_id, group_index, expected_observations, expected_effects, physical_cost):", "def _scientific_selection():"), architecture.Finding("scientific-selection-provenance", "ScientificCalibrationSelectionProjection")), Mutation("replay-owner-other-parameter", _replace("def _scientific_selection(run_id, world_id, seed, comparison_group_id, group_index, expected_observations, expected_effects, physical_cost):", "def _scientific_selection(other):"), architecture.Finding("scientific-selection-provenance", "ScientificCalibrationSelectionProjection")), Mutation("replay-owner-partial-parameters", _replace("def _scientific_selection(run_id, world_id, seed, comparison_group_id, group_index, expected_observations, expected_effects, physical_cost):", "def _scientific_selection(run_id):"), architecture.Finding("scientific-selection-provenance", "ScientificCalibrationSelectionProjection")), Mutation("nested-replay-decoy", _replace("    selection = _replay(", "    if False:\n        selection = _replay("), architecture.Finding("scientific-selection-provenance", "ScientificCalibrationSelectionProjection"))),
    "module-getattr": (Mutation("assigned-getattr-hook", _append("\ndef _hook(name):\n return None\n__getattr__ = _hook"), architecture.Finding("dynamic-module-hook", "__getattr__")), Mutation("caller-runtime-domain", lambda source: source.replace("import protocol_hash as _protocol_hash", "import protocol_hash as _protocol_hash, runtime_id as _runtime_id") + "\ndef _bad(projection, domain):\n return _runtime_id('x', domain, projection)", architecture.Finding("second-identity-algebra", "_runtime_id")), Mutation("subscript-runtime-domain", lambda source: source.replace("import protocol_hash as _protocol_hash", "import protocol_hash as _protocol_hash, runtime_id as _runtime_id") + "\ndef _bad(projection):\n domains = ('validation_evidence_calibration_selection/v1',)\n return _runtime_id('x', domains[0], projection)", architecture.Finding("second-identity-algebra", "_runtime_id")), Mutation("concatenated-runtime-domain", lambda source: source.replace("import protocol_hash as _protocol_hash", "import protocol_hash as _protocol_hash, runtime_id as _runtime_id") + "\ndef _bad(projection):\n return _runtime_id('x', 'validation_evidence_' + 'calibration_selection/v1', projection)", architecture.Finding("second-identity-algebra", "_runtime_id")), Mutation("decoy-effect-type", lambda source: source.replace("from research_decision_engine.benchmarks.broader_protocol", f"from {architecture._REPLAY} import raw_effect_sha256 as _raw_effect_sha256\nfrom research_decision_engine.benchmarks.broader_protocol") + "\nclass _MatchedEffectObservation:\n pass\ndef _bad(effect: _MatchedEffectObservation):\n return _raw_effect_sha256(effect)", architecture.Finding("raw-digest-provenance", "raw_effect_sha256"))),
    "module-dir": (Mutation("assigned-dir-hook", _append("\ndef _hook():\n return ()\n__dir__ = _hook"), architecture.Finding("dynamic-module-hook", "__dir__")), Mutation("wrong-outcome-payload", _append("\ndef _bad(oracle_key_id, revealed_observation):\n return _protocol_hash('revealed_outcome/v1', {'oracle_key_id': oracle_key_id, 'wrong': revealed_observation})"), architecture.Finding("nonidentity-protocol-hash", "_bad")), Mutation("swapped-outcome-payload", _append("\ndef _bad(oracle_key_id, revealed_observation):\n return _protocol_hash('revealed_outcome/v1', {'oracle_key_id': revealed_observation, 'revealed_observation': oracle_key_id})"), architecture.Finding("nonidentity-protocol-hash", "_bad")), Mutation("aliased-outcome-domain", _append("\ndef _bad(oracle_key_id, revealed_observation):\n domain = 'revealed_outcome/v1'\n return _protocol_hash(domain, {'oracle_key_id': oracle_key_id, 'revealed_observation': revealed_observation})"), architecture.Finding("nonidentity-protocol-hash", "_bad")), Mutation("unbound-outcome-inputs", _append("\ndef _bad():\n return _protocol_hash('revealed_outcome/v1', {'oracle_key_id': oracle_key_id, 'revealed_observation': revealed_observation})"), architecture.Finding("nonidentity-protocol-hash", "_bad")), Mutation("wrong-oracle-key-payload", lambda source: source.replace("import protocol_hash as _protocol_hash", "import protocol_hash as _protocol_hash, runtime_id as _runtime_id") + "\ndef _bad(wrong_payload):\n return _runtime_id('oracle-key', 'oracle_key_id/v1', wrong_payload)", architecture.Finding("second-identity-algebra", "_runtime_id")), Mutation("unbound-oracle-key-input", lambda source: source.replace("import protocol_hash as _protocol_hash", "import protocol_hash as _protocol_hash, runtime_id as _runtime_id") + "\ndef _bad():\n return _runtime_id('oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})", architecture.Finding("second-identity-algebra", "_runtime_id"))),
    "production-selector-call": (Mutation("unresolved-bare-call", _append("\ndef _bad():\n return _unknown()"), architecture.Finding("unresolved-call", "_unknown")), Mutation("phase-dispatch-read", _append("\ndef _dispatch(phase):\n return _HANDLERS[phase]"), architecture.Finding("caller-stage-dispatch", "_dispatch"))),
    "reader-evidence-persistence-sqlite": (Mutation("reader-import", _append(f"\nfrom {architecture._EXECUTION.rsplit('.', 1)[0]}.broader_lifecycle import Reader as _Reader"), architecture.Finding("forbidden-import", "research_decision_engine.benchmarks.broader_lifecycle")), Mutation("evidence-write", _append("\nfrom research_decision_engine.benchmarks.broader_validation_evidence import write_evidence as _write_evidence\ndef _bad():\n _write_evidence()"), architecture.Finding("forbidden-sensitive-call", "_write_evidence")), Mutation("persistence-import", _append("\nimport research_decision_engine.storage"), architecture.Finding("forbidden-import", "research_decision_engine.storage")), Mutation("sqlite-import", _append("\nimport sqlite3"), architecture.Finding("forbidden-import", "sqlite3")), *(Mutation(f"{name}-attribute-read", _append(f"\ndef _bad(state):\n return state.{name}"), architecture.Finding("registry-state", name)) for name in ("registry", "selector_registry", "oracle_authority_registry", "capability_registry"))),
    "subprocess-network-environment-git-filesystem": tuple(Mutation(f"{name}-import", _append(f"\nimport {name}"), architecture.Finding("forbidden-import", name)) for name in ("subprocess", "socket", "os", "git", "pathlib")),
    "wrong-schema-literal": (Mutation("scientific-schema-annotation", _replace("class ScientificCalibrationSelectionProjection:", "class ScientificCalibrationSelectionProjection:\n    schema_version: str"), architecture.Finding("scientific-selection-schema-field", "ScientificCalibrationSelectionProjection")), Mutation("scientific-schema-slots", _replace("class ScientificCalibrationSelectionProjection:", 'class ScientificCalibrationSelectionProjection:\n    __slots__ = ("schema_version",)'), architecture.Finding("scientific-selection-schema-field", "ScientificCalibrationSelectionProjection")), Mutation("scientific-schema-base", lambda source: "_Base = object\nclass _SchemaBase:\n schema_version = 'wrong'\n" + source.replace("class ScientificCalibrationSelectionProjection:", "class ScientificCalibrationSelectionProjection(_SchemaBase):"), architecture.Finding("unapproved-projection-base", "ScientificCalibrationSelectionProjection")), Mutation("schema-method-overwrite", _replace("    schema_version = 'broader-replication-calibration-selection-binding/v1'", "    schema_version = 'broader-replication-calibration-selection-binding/v1'\n    def schema_version(self):\n        return 'wrong'"), architecture.Finding("schema-literal", "CalibrationSelectionProjection")), Mutation("domain-method-overwrite", _replace("_SELECTION_IDENTITY_DOMAIN = 'broader-calibration-history-selection/v1'", "_SELECTION_IDENTITY_DOMAIN = 'broader-calibration-history-selection/v1'\ndef _SELECTION_IDENTITY_DOMAIN():\n return 'wrong'"), architecture.Finding("identity-domain", "selection_identity")), Mutation("schema-delete", _replace("    schema_version = 'broader-replication-calibration-selection-binding/v1'", "    schema_version = 'broader-replication-calibration-selection-binding/v1'\n    del schema_version"), architecture.Finding("schema-literal", "CalibrationSelectionProjection")), Mutation("wrong-construction-schema", _append('\ndef _bad():\n return CalibrationSelectionProjection(schema_version="wrong/v1")'), architecture.Finding("schema-literal", "CalibrationSelectionProjection"))),
    "wrong-identity-domain": (Mutation("fake-qualified-hash", lambda source: source.replace("return _protocol_hash('validation_evidence_calibration_selection/v1', projection)", "return _fake_protocol_hash('validation_evidence_calibration_selection/v1', projection)") + "\ndef _fake_protocol_hash(domain, payload):\n return domain", architecture.Finding("identity-domain", "calibration_selection_id")), Mutation("none-hash-payload", _replace("return _protocol_hash('validation_evidence_calibration_selection/v1', projection)", "return _protocol_hash('validation_evidence_calibration_selection/v1', None)"), architecture.Finding("identity-domain", "calibration_selection_id")), Mutation("alternate-hash-payload", _replace("def calibration_selection_id(projection):\n    return _protocol_hash('validation_evidence_calibration_selection/v1', projection)", "def calibration_selection_id(projection, alternate):\n    return _protocol_hash('validation_evidence_calibration_selection/v1', alternate)"), architecture.Finding("identity-domain", "calibration_selection_id"))),
    "wrong-fixed-protocol-literal": (Mutation("wrong-owner-plus-decoy", _replace('_PROTOCOL_CHECKPOINT = "89c0b4fadba33b9fd9a257b43eacf476b7779d59"', '_PROTOCOL_CHECKPOINT = "0bd025b696a31bdf5f71e80b275542de1b50ffdb"\n_DECOY_PROTOCOL_CHECKPOINT = "89c0b4fadba33b9fd9a257b43eacf476b7779d59"'), architecture.Finding("fixed-literal", "protocol_checkpoint")), Mutation("decoy-only-fixed-literal", _replace("_PROTOCOL_CHECKPOINT =", "_DECOY_PROTOCOL_CHECKPOINT ="), architecture.Finding("fixed-literal", "protocol_checkpoint")), Mutation("class-fixed-literal-consumer", _replace("class CalibrationSelectionProjection:", 'class CalibrationSelectionProjection:\n    protocol_checkpoint = "89c0b4fadba33b9fd9a257b43eacf476b7779d59"'), architecture.Finding("projection-field-surface", "CalibrationSelectionProjection")), Mutation("wrong-fixed-literal-comparison", _append("\ndef _check_checkpoint(value):\n return value.protocol_checkpoint == 'WRONG-CHECKPOINT'"), architecture.Finding("fixed-literal", "protocol_checkpoint")), Mutation("aliased-wrong-fixed-comparison", _append("\ndef _check_checkpoint(value):\n checkpoint = value.protocol_checkpoint\n return checkpoint == 'WRONG-CHECKPOINT'"), architecture.Finding("fixed-literal", "protocol_checkpoint")), Mutation("ordered-fixed-literal-comparison", _append("\ndef _check_checkpoint(value):\n return value.protocol_checkpoint < _PROTOCOL_CHECKPOINT"), architecture.Finding("fixed-literal", "protocol_checkpoint")), Mutation("fixed-literal-delete", _append("\ndel _PROTOCOL_CHECKPOINT"), architecture.Finding("fixed-literal", "protocol_checkpoint")), Mutation("wrong-construction-literal", _append('\ndef _bad():\n return CalibrationSelectionProjection(calibration_namespace="wrong/v1")'), architecture.Finding("fixed-literal", "calibration_namespace"))),
    "raw-sha-replaced-by-framed-hash": (Mutation("framed-intermediate", _append("\ndef _bad(projection):\n _digest = _protocol_hash('raw/v1', projection)\n return ScientificCalibrationSelectionProjection(source_effect_payload_sha256=_digest)"), architecture.Finding("nonidentity-protocol-hash", "_bad")), Mutation("framed-wrapper", _append("\ndef _framed(projection):\n return _protocol_hash('raw/v1', projection)\ndef _bad(projection):\n return ScientificCalibrationSelectionProjection(source_effect_payload_sha256=_framed(projection))"), architecture.Finding("nonidentity-protocol-hash", "_framed")), Mutation("raw-none-input", lambda source: source.replace("from research_decision_engine.benchmarks.broader_protocol", f"from {architecture._REPLAY} import raw_effect_sha256 as _raw_effect_sha256\nfrom research_decision_engine.benchmarks.broader_protocol") + "\ndef _bad(effect):\n return _raw_effect_sha256(None)", architecture.Finding("raw-digest-provenance", "raw_effect_sha256")), Mutation("raw-other-parameter", lambda source: source.replace("from research_decision_engine.benchmarks.broader_protocol", f"from {architecture._REPLAY} import raw_effect_sha256 as _raw_effect_sha256\nfrom research_decision_engine.benchmarks.broader_protocol") + "\ndef _bad(effect, other_effect):\n return _raw_effect_sha256(other_effect)", architecture.Finding("raw-digest-provenance", "raw_effect_sha256")), Mutation("raw-untyped-effect", lambda source: source.replace("from research_decision_engine.benchmarks.broader_protocol", f"from {architecture._REPLAY} import raw_effect_sha256 as _raw_effect_sha256\nfrom research_decision_engine.benchmarks.broader_protocol") + "\ndef _bad(effect):\n return _raw_effect_sha256(effect)", architecture.Finding("raw-digest-provenance", "raw_effect_sha256")), Mutation("raw-projection-parameter", lambda source: source.replace("from research_decision_engine.benchmarks.broader_protocol", f"from research_decision_engine.belief_models import MatchedEffectObservation as _MatchedEffectObservation\nfrom {architecture._REPLAY} import raw_effect_sha256 as _raw_effect_sha256\nfrom research_decision_engine.benchmarks.broader_protocol") + "\ndef _bad(projection: _MatchedEffectObservation):\n return _raw_effect_sha256(projection)", architecture.Finding("raw-digest-provenance", "raw_effect_sha256")), Mutation("positional-source-projection", _append("\ndef _bad(effect):\n return CalibrationSourceObservationProjection(effect)"), architecture.Finding("positional-projection-construction", "CalibrationSourceObservationProjection")), Mutation("runtime-identity-raw-sink", lambda source: source.replace("import protocol_hash as _protocol_hash", "import protocol_hash as _protocol_hash, runtime_id as _runtime_id") + "\ndef _bad(effect):\n return ScientificCalibrationSelectionProjection(source_effect_payload_sha256=_runtime_id(effect))", architecture.Finding("scientific-selection-provenance", "ScientificCalibrationSelectionProjection")), Mutation("runtime-identity-intermediate", lambda source: source.replace("import protocol_hash as _protocol_hash", "import protocol_hash as _protocol_hash, runtime_id as _runtime_id") + "\ndef _bad(effect):\n _digest = _runtime_id('raw/v1', effect)\n return ScientificCalibrationSelectionProjection(source_effect_payload_sha256=_digest)", architecture.Finding("scientific-selection-provenance", "ScientificCalibrationSelectionProjection")), Mutation("runtime-identity-kwargs", lambda source: source.replace("import protocol_hash as _protocol_hash", "import protocol_hash as _protocol_hash, runtime_id as _runtime_id") + "\ndef _bad(effect):\n return ScientificCalibrationSelectionProjection(**{'source_effect_payload_sha256': _runtime_id('raw/v1', effect)})", architecture.Finding("dynamic-surface", "**"))),
    "repr-asdict-pickle-identity": (Mutation("repr-identity", _append("\ndef _bad(value):\n return repr(value)"), architecture.Finding("identity-serialization", "repr")), Mutation("fstring-repr-identity", _append('\ndef _bad(value):\n return f"{value!r}"'), architecture.Finding("identity-serialization", "f-string-!r")), Mutation("asdict-identity", _append("\nfrom dataclasses import asdict as _asdict\ndef _bad(value):\n return _asdict(value)"), architecture.Finding("identity-serialization", "_asdict")), Mutation("pickle-identity", _append("\nimport pickle\ndef _bad(value):\n return pickle.dumps(value)"), architecture.Finding("identity-serialization", "pickle.dumps"))),
    "caller-validator-factory-variadic": (Mutation("identity-factory", _replace("def calibration_selection_id(projection):", "def calibration_selection_id(projection, identity_factory):"), architecture.Finding("caller-authority-parameter", "calibration_selection_id:identity_factory")), Mutation("validator-factory", _replace("def calibration_selection_id(projection):", "def calibration_selection_id(projection, validator_factory):"), architecture.Finding("caller-authority-parameter", "calibration_selection_id:validator_factory")), Mutation("camel-identity-factory", _replace("def calibration_selection_id(projection):", "def calibration_selection_id(projection, identityFactory):"), architecture.Finding("caller-authority-parameter", "calibration_selection_id:identityFactory")), Mutation("camel-validator-factory", _replace("def calibration_selection_id(projection):", "def calibration_selection_id(projection, validatorFactory):"), architecture.Finding("caller-authority-parameter", "calibration_selection_id:validatorFactory")), Mutation("validator-map", _replace("def calibration_selection_id(projection):", "def calibration_selection_id(projection, validator_map):"), architecture.Finding("caller-authority-parameter", "calibration_selection_id:validator_map")), Mutation("untyped-live-authority", _replace("def calibration_selection_id(projection):", "def calibration_selection_id(projection, authority: object):"), architecture.Finding("caller-authority-parameter", "calibration_selection_id:authority")), Mutation("forward-live-authority", _replace("def calibration_selection_id(projection):", 'def calibration_selection_id(projection: "ObservationAuthority"):'), architecture.Finding("caller-authority-parameter", "calibration_selection_id:projection")), Mutation("forward-live-return", _replace("def calibration_selection_id(projection):", 'def calibration_selection_id(projection) -> "ObservationAuthority":'), architecture.Finding("live-capability-return", "calibration_selection_id")), Mutation("live-projection-field", _replace("class CalibrationSelectionProjection:", "class CalibrationSelectionProjection:\n    authority: object"), architecture.Finding("projection-field-surface", "CalibrationSelectionProjection")), Mutation("callable-projection-field", _replace("class CalibrationSelectionProjection:", "class CalibrationSelectionProjection:\n    validator: object"), architecture.Finding("live-capability-field", "CalibrationSelectionProjection")), Mutation("validator-factory-projection-field", _replace("class CalibrationSelectionProjection:", "class CalibrationSelectionProjection:\n    validator_factory: object"), architecture.Finding("live-capability-field", "CalibrationSelectionProjection")), Mutation("forward-live-projection-field", _replace("class CalibrationSelectionProjection:", 'class CalibrationSelectionProjection:\n    token: "ObservationAuthority"'), architecture.Finding("live-capability-field", "CalibrationSelectionProjection")), Mutation("nested-forward-live-field", _replace("class CalibrationSelectionProjection:", 'class CalibrationSelectionProjection:\n    token: list["ObservationAuthority"]'), architecture.Finding("live-capability-field", "CalibrationSelectionProjection")), Mutation("projection-validator-method", _replace("class CalibrationSelectionProjection:", "class CalibrationSelectionProjection:\n    def _helper(self, validator):\n        return None"), architecture.Finding("private-caller-authority-parameter", "_helper")), Mutation("nested-private-validator", _append("\ndef _outer():\n def _helper(validator_factory):\n  return None"), architecture.Finding("private-caller-authority-parameter", "_helper"))),
    "later-reader-evidence-finalization": tuple(Mutation(name, _append(source), architecture.Finding(code, detail)) for name, source, code, detail in (("reader-projection", "\nclass _ReaderReconciliationProjection:\n pass", "later-stage-binding", "_ReaderReconciliationProjection"), ("reader-binding", "\n_Reader = object", "later-stage-binding", "_Reader"), ("evidence-writer-binding", "\n_EvidenceWriter = object", "later-stage-binding", "_EvidenceWriter"), ("persistence-binding", "\n_Persistence = object", "later-stage-binding", "_Persistence"), ("storage-binding", "\n_Storage = object", "later-stage-binding", "_Storage"), ("normalized-reader-projection", "\nclass _calibration_evidence_bundle_projection:\n pass", "later-stage-binding", "_calibration_evidence_bundle_projection"), ("evidence-bundle", "\nclass _CalibrationEvidenceBundleProjection:\n pass", "later-stage-binding", "_CalibrationEvidenceBundleProjection"), ("member-inventory", "\nclass _EvidenceMemberInventory:\n pass", "later-stage-binding", "_EvidenceMemberInventory"), ("bindings-writer", "\n_validation_bindings_writer = object()", "later-stage-binding", "_validation_bindings_writer"), ("finalization-writer", "\nclass _FinalizationWriter:\n pass", "later-stage-binding", "_FinalizationWriter"))),
    "later-stage3-authority-and-aggregate": tuple(Mutation(name, _append(source), architecture.Finding("later-stage-binding", detail)) for name, source, detail in (("bounded-authorization", "\ndef _bounded_validation_authorization():\n pass", "_bounded_validation_authorization"), ("stage3-workload-authorization", "\ndef _stage3_workload_authorization():\n pass", "_stage3_workload_authorization"), ("full-authorization", "\ndef _full_replication_authorization():\n pass", "_full_replication_authorization"), ("final-aggregate", "\nclass _CalibrationFinalAggregateProjection:\n pass", "_CalibrationFinalAggregateProjection"), ("full-replication", "\n_FULL_REPLICATION = True", "_FULL_REPLICATION"))),
}


_P4_PREDICATE_SIGNATURE = (
    "def _predicate_3o_5_1("
    "replay_run_id, world_id, seed, comparison_group_id, group_index, "
    "expected_observations, expected_effects, physical_cost, "
    "recorded_observations, recorded_effects, expected_projection):"
)
_P4_REPLAY_ASSIGNMENT = (
    "    actual_helper_result = _replay_calibration_history_selection("
)
_P4_REPLAY_KEYWORD_PREFIX = (
    "        run_id=replay_run_id,\n"
    "        world_id=world_id,"
)
_P4_PREDICATE_RETURN = (
    "    return (actual_helper_result, expected_selector_result_identity)"
)
_GENERIC_REPLAY_FINDING = architecture.Finding(
    "generic-replay-authority", "_replay_calibration_history_selection"
)


def _p4_replay_early_return(source: str) -> str:
    return source.replace(
        _P4_REPLAY_ASSIGNMENT,
        "    return _replay_calibration_history_selection(",
        1,
    )


def _p4_replay_yield(source: str) -> str:
    return source.replace(
        _P4_REPLAY_ASSIGNMENT,
        "    yield _replay_calibration_history_selection(",
        1,
    )


def _p4_replay_alias_return(source: str) -> str:
    return source.replace(
        _P4_REPLAY_ASSIGNMENT,
        "    replay_alias = _replay_calibration_history_selection(",
        1,
    ).replace(
        _P4_PREDICATE_RETURN,
        "    return (replay_alias, expected_selector_result_identity)",
        1,
    )


def _p4_replay_store(source: str, target: str) -> str:
    return source.replace(
        _P4_PREDICATE_RETURN,
        f"    {target} = actual_helper_result\n{_P4_PREDICATE_RETURN}",
        1,
    )


def _p4_selection_domain_callable(source: str) -> str:
    return source.replace(
        "        'broader-calibration-history-selection/v1',",
        "        _SELECTION_IDENTITY_DOMAIN(),",
        1,
    ) + (
        "\n"
        "def _SELECTION_IDENTITY_DOMAIN():\n"
        "    return 'broader-calibration-history-selection/v1'\n"
    )


_ISOLATED_FUTURE_OVERRIDES = {
    "swapped-replay-keywords": Mutation(
        "swapped-replay-keywords",
        lambda source: source.replace(
            _P4_REPLAY_KEYWORD_PREFIX,
            "        run_id=world_id,\n        world_id=replay_run_id,",
            1,
        ),
        _GENERIC_REPLAY_FINDING,
    ),
    "duplicate-replay-keyword": Mutation(
        "duplicate-replay-keyword",
        lambda source: source.replace(
            _P4_REPLAY_KEYWORD_PREFIX,
            "        run_id=replay_run_id,\n        run_id=world_id,",
            1,
        ),
        _GENERIC_REPLAY_FINDING,
    ),
    "replay-result-early-return": Mutation(
        "replay-result-early-return",
        _p4_replay_early_return,
        _GENERIC_REPLAY_FINDING,
    ),
    "replay-result-yield": Mutation(
        "replay-result-yield",
        _p4_replay_yield,
        _GENERIC_REPLAY_FINDING,
    ),
    "replay-alias-early-return": Mutation(
        "replay-alias-early-return",
        _p4_replay_alias_return,
        _GENERIC_REPLAY_FINDING,
    ),
    "replay-attribute-store": Mutation(
        "replay-attribute-store",
        lambda source: _p4_replay_store(source, "holder.value"),
        architecture.Finding("object-state-mutation", "Assign"),
    ),
    "replay-subscript-store": Mutation(
        "replay-subscript-store",
        lambda source: _p4_replay_store(source, "holder[0]"),
        architecture.Finding("object-state-mutation", "Assign"),
    ),
    "replay-owner-no-parameters": Mutation(
        "replay-owner-no-parameters",
        lambda source: source.replace(
            _P4_PREDICATE_SIGNATURE, "def _predicate_3o_5_1():", 1
        ),
        _GENERIC_REPLAY_FINDING,
    ),
    "replay-owner-other-parameter": Mutation(
        "replay-owner-other-parameter",
        lambda source: source.replace(
            _P4_PREDICATE_SIGNATURE, "def _predicate_3o_5_1(other):", 1
        ),
        _GENERIC_REPLAY_FINDING,
    ),
    "replay-owner-partial-parameters": Mutation(
        "replay-owner-partial-parameters",
        lambda source: source.replace(
            _P4_PREDICATE_SIGNATURE,
            "def _predicate_3o_5_1(replay_run_id):",
            1,
        ),
        _GENERIC_REPLAY_FINDING,
    ),
    "nested-replay-decoy": Mutation(
        "nested-replay-decoy",
        lambda source: source.replace(
            _P4_REPLAY_ASSIGNMENT,
            "    if False:\n"
            "        actual_helper_result = _replay_calibration_history_selection(",
            1,
        ),
        _GENERIC_REPLAY_FINDING,
    ),
    "domain-method-overwrite": Mutation(
        "domain-method-overwrite",
        _p4_selection_domain_callable,
        architecture.Finding("identity-domain-set", "P4"),
    ),
    "runtime-identity-raw-sink": Mutation(
        "runtime-identity-raw-sink",
        _append(
            "\ndef _bad(effect):\n"
            " return ScientificCalibrationSelectionProjection("
            "source_effect_payload_sha256=_runtime_id(effect))"
        ),
        architecture.Finding("second-identity-algebra", "_runtime_id"),
    ),
    "runtime-identity-intermediate": Mutation(
        "runtime-identity-intermediate",
        _append(
            "\ndef _bad(effect):\n"
            " _digest = _runtime_id('raw/v1', effect)\n"
            " return ScientificCalibrationSelectionProjection("
            "source_effect_payload_sha256=_digest)"
        ),
        architecture.Finding("second-identity-algebra", "_runtime_id"),
    ),
}
_ISOLATED_FUTURE = {
    group: tuple(_ISOLATED_FUTURE_OVERRIDES.get(case.id, case) for case in cases)
    for group, cases in _ISOLATED_FUTURE.items()
}


@pytest.mark.parametrize("case", _OWNER_CASES, ids=[case.id for case in _OWNER_CASES])
def test_noncanonical_modules_cannot_own_stage2f(case: Case) -> None:
    logical_cases = tuple(
        LogicalCase(logical_id, source, frozenset({expected}))
        for logical_id, source, expected in _OWNER_ISOLATED.get(case.id, ())
    )
    _assert_batch(
        _evaluate_batch(
            logical_cases,
            lambda source: architecture.repository_findings({case.source: source}, architecture.C0_MANIFEST),
        )
    )
    source = f"class {case.expected}:\n pass"
    codes = {item.code for item in architecture.repository_findings({case.source: source}, architecture.C0_MANIFEST)}
    assert "wrong-module-owner" in codes

@pytest.mark.parametrize("case", _PREMATURE_CASES, ids=[case.id for case in _PREMATURE_CASES])
def test_c0_rejects_every_premature_surface(case: Case) -> None:
    logical_cases = tuple(
        LogicalCase(logical.id, logical.mutate(""), frozenset({logical.expected}))
        for logical in _ISOLATED_C0.get(case.id, ())
    )
    _assert_batch(
        _evaluate_batch(
            logical_cases,
            lambda source: architecture.repository_findings(
                {architecture.CANONICAL_MODULE: source}, architecture.C0_MANIFEST
            ),
        )
    )
    codes = {item.code for item in architecture.repository_findings({architecture.CANONICAL_MODULE: case.source}, architecture.C0_MANIFEST)}
    assert {"c0-production-module-present", case.expected} <= codes
    if case.id == "premature-p2-p3-p4":
        assert "premature-validator" in codes

@pytest.mark.parametrize("case", _ALIAS_CASES, ids=[case.id for case in _ALIAS_CASES])
def test_alias_and_dynamic_surfaces_fail_closed(case: Case) -> None:
    _assert_isolated(case.id)
    assert case.expected in _codes(_future_source(architecture.P4_MANIFEST) + case.source)

@pytest.mark.parametrize("case", _OPERATION_CASES, ids=[case.id for case in _OPERATION_CASES])
def test_forbidden_operational_surfaces_fail_closed(case: Case) -> None:
    _assert_isolated(case.id)
    assert case.expected in _codes(_future_source(architecture.P4_MANIFEST) + case.source)

@pytest.mark.parametrize("case", _MUTATIONS, ids=[case.id for case in _MUTATIONS])
def test_identity_schema_and_signature_violations_fail_closed(case: Mutation) -> None:
    _assert_isolated(case.id)
    findings = _findings(case.mutate(_future_source(architecture.P4_MANIFEST)))
    codes = frozenset(item.code for item in findings)
    assert case.expected in findings
    if case.id == "caller-validator-factory-variadic":
        assert architecture._names("caller-authority-parameter caller-callable-invocation caller-stage-dispatch variadic-public-api") <= codes

@pytest.mark.parametrize("case", _LATER_CASES, ids=[case.id for case in _LATER_CASES])
def test_later_stage_leakage_is_permanently_forbidden(case: Case) -> None:
    _assert_isolated(case.id)
    codes = _codes(_future_source(architecture.P4_MANIFEST) + case.source)
    assert case.expected in codes
    if case.id == "later-reader-evidence-finalization":
        assert "later-stage-literal" in codes
# fmt: on
