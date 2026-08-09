"""Test-owned Stage-2F calibration-evidence architecture boundary."""
# ruff: noqa: E501, E701, E702, UP014

from __future__ import annotations

import ast
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, Literal, NamedTuple, cast

from tests import p2_returned_run_architecture_guard as qualified

type CalibrationEvidencePhase = Literal["C0", "P1", "P2", "P3", "P4"]

CANONICAL_MODULE: Final = "research_decision_engine.benchmarks.broader_calibration_evidence"
CANONICAL_RELATIVE_PATH: Final = "research_decision_engine/benchmarks/broader_calibration_evidence.py"  # fmt: skip
HARNESS_MODULE: Final = "tests.p2_calibration_evidence_harness"
HARNESS_RELATIVE_PATH: Final = "tests/p2_calibration_evidence_harness.py"


def _names(value: str) -> frozenset[str]:
    return frozenset(value.split())


_MAX_ANALYSES_PER_SESSION: Final = 64
_CANONICAL_PRODUCTION_ORIGIN_CODE: Final = "canonical-production-origin"


# fmt: off
type ProjectedProvenanceCertainty = Literal["exact", "possible", "limited"]
type ProjectedProvenanceRelation = Literal["direct", "aggregate", "receiver", "callable", "result"]
type ProjectedProvenanceOriginClass = Literal["canonical-production-module", "forbidden-production-helper", "allowed-production-projection-class", "unrelated-imported-module", "unrelated-local", "unresolved-local", "unresolved-production-sensitive"]
type ProjectedProvenanceLimitClass = Literal["none", "unrelated", "production-sensitive"]

_PROJECTED_CERTAINTIES = frozenset({"exact", "possible", "limited"})
_PROJECTED_RELATIONS = frozenset({"direct", "aggregate", "receiver", "callable", "result"})
_PROJECTED_LIMIT_CLASSES = frozenset({"none", "unrelated", "production-sensitive"})
_PROJECTED_NODE_KINDS = frozenset({"AnalysisLimit", "Attribute", "Await", "BinOp", "BoolOp", "Bytes", "Call", "Compare", "Constant", "Dict", "DictComp", "Ellipsis", "FormattedValue", "GeneratorExp", "IfExp", "ImportBinding", "JoinedStr", "Lambda", "List", "ListComp", "Name", "NameConstant", "NamedExpr", "Num", "Set", "SetComp", "Slice", "SpanCorrelationLimit", "Starred", "Str", "Subscript", "Tuple", "UnaryOp", "Yield", "YieldFrom"})


class OriginClassPolicy(NamedTuple):
    """The single retention and production-reachability authority."""

    retain_fact: bool
    production_reachable: bool


_ORIGIN_CLASS_POLICIES: Final = MappingProxyType({
    "canonical-production-module": OriginClassPolicy(True, True),
    "forbidden-production-helper": OriginClassPolicy(True, True),
    "allowed-production-projection-class": OriginClassPolicy(True, False),
    "unrelated-imported-module": OriginClassPolicy(True, False),
    "unrelated-local": OriginClassPolicy(True, False),
    "unresolved-local": OriginClassPolicy(True, False),
    "unresolved-production-sensitive": OriginClassPolicy(True, True),
})
_PROJECTED_ORIGIN_CLASSES = frozenset(_ORIGIN_CLASS_POLICIES)


class ProjectedProvenance(NamedTuple):
    """One closed, immutable projection of a canonical analyzer flow value."""

    lineno: int
    col_offset: int
    node_kind: str
    certainty: ProjectedProvenanceCertainty
    relation: ProjectedProvenanceRelation
    origin_class: ProjectedProvenanceOriginClass
    production_reachable: bool
    limit_class: ProjectedProvenanceLimitClass
    qualified_origin: str | None


_PROJECTED_PROVENANCE_WIRE_FIELDS: Final = ("col_offset", "node_kind", "certainty", "relation", "origin_class", "production_reachable", "limit_class", "qualified_origin")
_PROJECTED_PROVENANCE_WIRE_SEPARATOR: Final = "|"
_MAX_PROJECTED_SOURCE_POSITION: Final = (1 << 63) - 1
_MAX_PROJECTED_SOURCE_POSITION_DIGITS: Final = len(str(_MAX_PROJECTED_SOURCE_POSITION))
_MALFORMED_PROJECTED_PROVENANCE_ORIGIN: Final = f"{CANONICAL_MODULE}.malformed_provenance_codec"


def _origin_class_policy(
    origin_class: ProjectedProvenanceOriginClass,
) -> OriginClassPolicy:
    return _ORIGIN_CLASS_POLICIES[origin_class]


def _retain_projected_origin(
    origin_class: ProjectedProvenanceOriginClass,
) -> bool:
    return _origin_class_policy(origin_class).retain_fact is True


def _production_reachable_origin(
    origin_class: ProjectedProvenanceOriginClass,
) -> bool:
    return _origin_class_policy(origin_class).production_reachable is True


def _production_sensitive_provenance(fact: ProjectedProvenance) -> bool:
    return (
        fact.production_reachable is True
        and _production_reachable_origin(fact.origin_class)
    )


def _dynamic_namespace_restricted_provenance(
    fact: ProjectedProvenance,
) -> bool:
    return (
        _production_sensitive_provenance(fact)
        or fact.origin_class == "allowed-production-projection-class"
    )


def _projected_qualified_origin_is_valid(value: object) -> bool:
    if value is None:
        return True
    if type(value) is not str or not value:
        return False
    if _PROJECTED_PROVENANCE_WIRE_SEPARATOR in value:
        return False
    return all(part.isidentifier() for part in value.split("."))


def _projected_provenance_is_consistent(fact: object) -> bool:
    if type(fact) is not ProjectedProvenance:
        return False
    if type(fact.lineno) is not int or not 1 <= fact.lineno <= _MAX_PROJECTED_SOURCE_POSITION:
        return False
    if type(fact.col_offset) is not int or not 0 <= fact.col_offset <= _MAX_PROJECTED_SOURCE_POSITION:
        return False
    if type(fact.node_kind) is not str or fact.node_kind not in _PROJECTED_NODE_KINDS:
        return False
    if type(fact.certainty) is not str or fact.certainty not in _PROJECTED_CERTAINTIES:
        return False
    if type(fact.relation) is not str or fact.relation not in _PROJECTED_RELATIONS:
        return False
    if type(fact.origin_class) is not str or fact.origin_class not in _PROJECTED_ORIGIN_CLASSES:
        return False
    if type(fact.production_reachable) is not bool:
        return False
    if type(fact.limit_class) is not str or fact.limit_class not in _PROJECTED_LIMIT_CLASSES:
        return False
    if not _projected_qualified_origin_is_valid(fact.qualified_origin):
        return False
    if fact.qualified_origin is None and fact.origin_class not in {
        "unrelated-local",
        "unresolved-local",
        "unresolved-production-sensitive",
    }:
        return False
    if fact.production_reachable is not _origin_class_policy(
        fact.origin_class
    ).production_reachable:
        return False
    if fact.certainty != "limited":
        return fact.limit_class == "none"
    if fact.limit_class == "unrelated":
        return fact.production_reachable is False
    if fact.limit_class == "production-sensitive":
        return fact.production_reachable is True
    return False


def _projected_provenance_wire_fields_are_valid(
    fields: dict[str, str],
) -> bool:
    col_offset = fields["col_offset"]
    qualified_origin = fields["qualified_origin"]
    return (
        all(type(fields[name]) is str for name in _PROJECTED_PROVENANCE_WIRE_FIELDS)
        and col_offset.isascii() and col_offset.isdecimal()
        and len(col_offset) <= _MAX_PROJECTED_SOURCE_POSITION_DIGITS
        and (col_offset == "0" or not col_offset.startswith("0"))
        and int(col_offset) <= _MAX_PROJECTED_SOURCE_POSITION
        and fields["node_kind"] in _PROJECTED_NODE_KINDS
        and fields["certainty"] in _PROJECTED_CERTAINTIES
        and fields["relation"] in _PROJECTED_RELATIONS
        and fields["origin_class"] in _PROJECTED_ORIGIN_CLASSES
        and fields["production_reachable"] in {"0", "1"}
        and fields["limit_class"] in _PROJECTED_LIMIT_CLASSES
        and (qualified_origin == "" or _projected_qualified_origin_is_valid(qualified_origin))
    )


def _malformed_projected_provenance(lineno: int) -> ProjectedProvenance:
    safe_lineno = lineno if type(lineno) is int and 1 <= lineno <= _MAX_PROJECTED_SOURCE_POSITION else 1
    return ProjectedProvenance(safe_lineno, 0, "AnalysisLimit", "limited", "aggregate", "unresolved-production-sensitive", True, "production-sensitive", _MALFORMED_PROJECTED_PROVENANCE_ORIGIN)


def _encoded_projected_provenance(
    fact: object,
) -> qualified.ArchitectureFinding:
    if _projected_provenance_is_consistent(fact):
        projected = cast(ProjectedProvenance, fact)
    else:
        lineno = (
            fact.lineno
            if type(fact) is ProjectedProvenance
            and type(fact.lineno) is int
            and fact.lineno >= 1
            else 1
        )
        projected = _malformed_projected_provenance(lineno)
    encoded_fields = {"col_offset": str(projected.col_offset), "node_kind": projected.node_kind, "certainty": projected.certainty, "relation": projected.relation, "origin_class": projected.origin_class, "production_reachable": "1" if projected.production_reachable else "0", "limit_class": projected.limit_class, "qualified_origin": projected.qualified_origin or ""}
    payload = tuple(encoded_fields[name] for name in _PROJECTED_PROVENANCE_WIRE_FIELDS)
    return qualified.ArchitectureFinding(_CANONICAL_PRODUCTION_ORIGIN_CODE, _PROJECTED_PROVENANCE_WIRE_SEPARATOR.join(payload), projected.lineno)


def _canonical_production_origin_findings(
    analyzer: qualified._QualifiedSymbolAnalyzer,
    analysis: qualified.QualifiedSymbolAnalysis,
) -> tuple[qualified.ArchitectureFinding, ...]:
    """Project bounded canonical flow values without performing a second analysis."""

    def origin_class(origin: str) -> ProjectedProvenanceOriginClass:
        if any(origin == target or origin.startswith(f"{target}.") for target in _HARNESS_FORBIDDEN_PRODUCTION_TARGETS):
            return "forbidden-production-helper"
        if any(origin == target or origin.startswith(f"{target}.") for target in _HARNESS_ALLOWED_PROJECTION_TARGETS):
            return "allowed-production-projection-class"
        if origin == CANONICAL_MODULE or origin.startswith(f"{CANONICAL_MODULE}."):
            return "canonical-production-module"
        if origin.startswith(f"{analyzer.module_name}.") or origin.startswith("builtins."):
            return "unrelated-local"
        return "unrelated-imported-module"

    def has_retained_authority_origin(value: qualified.ResolvedValue) -> bool:
        all_origins = (
            value.direct_origins | value.aggregate_origins | value.deferred_origins
        )
        for origin in all_origins:
            classified = origin_class(origin)
            if _retain_projected_origin(classified) and classified not in {
                "unrelated-imported-module",
                "unrelated-local",
            }:
                return True
        return False

    facts: set[ProjectedProvenance] = set()

    for binding in analysis.imports:
        for origin in binding.origins:
            classified = origin_class(origin)
            if _retain_projected_origin(classified):
                facts.add(ProjectedProvenance(binding.lineno, 0, "ImportBinding", "exact" if len(binding.origins) == 1 else "possible", "direct", classified, _production_reachable_origin(classified), "none", origin))

    def project(
        node: ast.expr,
        value: qualified.ResolvedValue,
        relation: ProjectedProvenanceRelation | None = None,
    ) -> None:
        classified_origins = tuple(
            (
                value_relation,
                origin,
                classified,
                _origin_class_policy(classified),
            )
            for value_relation, origin in (
                *(("direct", origin) for origin in value.direct_origins),
                *(("aggregate", origin) for origin in value.aggregate_origins - value.direct_origins),
                *(("aggregate", origin) for origin in value.deferred_origins - value.aggregate_origins - value.direct_origins),
            )
            for classified in (origin_class(origin),)
        )
        retained_origins = tuple(origin for _value_relation, origin, _classified, policy in classified_origins if policy.retain_fact)
        reachable_origins = tuple(origin for _value_relation, origin, _classified, policy in classified_origins if policy.production_reachable)
        production_reachable = bool(reachable_origins)
        if value.reachability_overflow:
            representative = min(reachable_origins or retained_origins, default=None)
            limited_origin: ProjectedProvenanceOriginClass = "unresolved-production-sensitive" if production_reachable else origin_class(representative) if representative is not None else "unresolved-local"
            facts.add(ProjectedProvenance(node.lineno, node.col_offset, type(node).__name__, "limited", relation or "aggregate", limited_origin, production_reachable, "production-sensitive" if production_reachable else "unrelated", representative))
        for value_relation, origin, classified, policy in classified_origins:
            projected_relation = relation or cast(ProjectedProvenanceRelation, value_relation)
            if not policy.retain_fact:
                continue
            certainty: ProjectedProvenanceCertainty = "exact" if value_relation == "direct" and len(value.direct_origins) == 1 and not value.is_unknown and not value.sensitive_unknown and not value.reachability_overflow else "possible"
            facts.add(ProjectedProvenance(node.lineno, node.col_offset, type(node).__name__, certainty, projected_relation, classified, policy.production_reachable, "none", origin))
        if value.is_unknown or value.sensitive_unknown:
            unresolved_class: ProjectedProvenanceOriginClass = "unresolved-production-sensitive" if production_reachable else "unresolved-local"
            facts.add(ProjectedProvenance(node.lineno, node.col_offset, type(node).__name__, "possible", relation or "result", unresolved_class, production_reachable, "none", min(reachable_origins, default=None) if production_reachable else None))
        elif not classified_origins:
            facts.add(ProjectedProvenance(node.lineno, node.col_offset, type(node).__name__, "exact", relation or "direct", "unrelated-local", _production_reachable_origin("unrelated-local"), "none", None))

    walked = _harness_bounded_walk(analyzer.tree, depth_limit=qualified._MAX_ABSTRACT_STRUCTURE_DEPTH, node_limit=qualified._MAX_POST_FLOW_RESOLUTION_CACHE, root_width_limit=qualified._MAX_ABSTRACT_STRUCTURE_NODES, width_limit=qualified._MAX_ABSTRACT_CONTAINER_WIDTH)
    frontier_origins = frozenset(
        origin
        for value in analyzer.flow_node_values.values()
        for origin in (value.direct_origins | value.aggregate_origins | value.deferred_origins)
    ) if walked is None else frozenset()
    frontier_retained_origins = tuple(origin for origin in frontier_origins if _retain_projected_origin(origin_class(origin)))
    frontier_reachable_origins = tuple(origin for origin in frontier_origins if _production_reachable_origin(origin_class(origin)))

    reflection_targets = frozenset({"builtins.getattr", "builtins.hasattr", "builtins.vars"})
    for node in walked or ():
        if not isinstance(node, ast.expr):
            continue
        value = analyzer.flow_node_values.get(id(node))
        if value is not None and (
            value.reachability_overflow or has_retained_authority_origin(value)
        ):
            project(node, value, "result" if isinstance(node, ast.Call) else None)
        if isinstance(node, ast.Attribute) and node.attr in qualified._DYNAMIC_NAMESPACE_ATTRIBUTES:
            receiver = analyzer.flow_node_values.get(id(node.value))
            if receiver is not None:
                project(node, receiver, "receiver")
            elif value is not None:
                project(node, value, "result")
        if not isinstance(node, ast.Call):
            continue
        callee = analyzer.flow_node_values.get(id(node.func))
        if callee is None:
            continue
        callee_targets = callee.direct_origins | callee.aggregate_origins | callee.deferred_origins
        if callee_targets & reflection_targets and node.args:
            receiver = analyzer.flow_node_values.get(id(node.args[0]))
            if receiver is not None:
                project(node, receiver, "receiver")
            elif value is not None:
                project(node, value, "result")
        if callee.is_unknown or callee.sensitive_unknown or len(callee_targets) != 1 or isinstance(node.func, (ast.Call, ast.IfExp, ast.Lambda, ast.Subscript)) or has_retained_authority_origin(callee):
            project(node, callee, "callable")

    span_limited = bool(len(analyzer.tree.body) > qualified._MAX_ABSTRACT_STRUCTURE_NODES or sum(len(scope.events) for scope in analyzer.scopes) > qualified._MAX_ABSTRACT_LOCATIONS or len(analyzer.calls) > qualified._MAX_ABSTRACT_LOCATIONS or walked is None)
    projection_limited = len(facts) > qualified._MAX_ABSTRACT_LOCATIONS
    if span_limited or projection_limited:
        retained = tuple(fact for fact in facts if _retain_projected_origin(fact.origin_class))
        reachable = tuple(fact for fact in retained if fact.production_reachable is True)
        representative_fact = min(reachable or retained, key=lambda fact: (fact.lineno, fact.col_offset, fact.qualified_origin or ""), default=None)
        representative_origin = representative_fact.qualified_origin if representative_fact is not None else min(frontier_reachable_origins or frontier_retained_origins, default=None)
        production_reachable = bool(reachable or frontier_reachable_origins)
        limit_origin: ProjectedProvenanceOriginClass = "unresolved-production-sensitive" if production_reachable else origin_class(representative_origin) if representative_origin is not None else "unresolved-local"
        limit = ProjectedProvenance(
            representative_fact.lineno if representative_fact is not None else 1,
            representative_fact.col_offset if representative_fact is not None else 0,
            "SpanCorrelationLimit" if span_limited else "AnalysisLimit",
            "limited",
            "aggregate",
            limit_origin,
            production_reachable,
            "production-sensitive" if production_reachable else "unrelated",
            representative_origin,
        )
        facts = {limit} if projection_limited else facts | {limit}
    ordered = sorted(facts, key=lambda fact: (fact.lineno, fact.col_offset, fact.node_kind, fact.certainty, fact.relation, fact.origin_class, fact.production_reachable, fact.limit_class, fact.qualified_origin or ""))
    return tuple(_encoded_projected_provenance(fact) for fact in ordered)


def _source_analysis(source: str, *, module_name: str, owned: bool = False) -> _SourceAnalysis:
    """Construct one fresh parse/analyzer and project its immutable facts."""
    analyzer_type = _OwnedQualifiedSymbolAnalyzer if owned and module_name == CANONICAL_MODULE else qualified._QualifiedSymbolAnalyzer
    analyzer = analyzer_type(source, module_name)
    analysis = analyzer.analysis()
    if module_name == HARNESS_MODULE:
        analysis = analysis._replace(findings=(*analysis.findings, *_canonical_production_origin_findings(analyzer, analysis)))
    functions = MappingProxyType({node.name: node for node in analyzer.tree.body if isinstance(node, ast.FunctionDef)}); module_state = analyzer.flow_final_states.get(id(analyzer.module_scope)); module_bindings = MappingProxyType({} if module_state is None else dict(module_state.bindings)); function_definition_counts = MappingProxyType({name: len(analyzer.local_functions.get(f"{module_name}.{name}", ())) for name in functions}); function_binding_event_counts = MappingProxyType({name: sum(event_name == name for event_name, _kind, _line in analyzer.module_scope.events) for name in functions})
    owned_values: dict[int, _OwnedFlowValue] = {}; owned_expressions: tuple[ast.expr, ...] = (); owned_controls: Mapping[str, tuple[ast.If, ...]] = MappingProxyType({}); owned_benign_mutation_lines: frozenset[tuple[int, str]] = frozenset()
    execution_changed_function_roots = frozenset(child.path[0] for entries in analyzer.local_functions.values() for function, child in entries if function.decorator_list and child.path) | frozenset(scope.path[0] if scope.path else "" for node in ast.walk(analyzer.tree) if (isinstance(node, (ast.Assert, ast.Raise, ast.While, ast.Yield, ast.YieldFrom)) or isinstance(node, ast.Name) and node.id == "__debug__" or isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and isinstance(node.right, ast.Constant) and node.right.value == 0 or isinstance(node, ast.Expr) and isinstance(node.value, ast.BinOp) and isinstance(node.value.op, (ast.Div, ast.FloorDiv, ast.Mod)) or isinstance(node, ast.For) and isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Name) and node.iter.func.id == "iter" and len(node.iter.args) == 2) and (scope := analyzer.node_scopes.get(id(node))) is not None)
    if isinstance(analyzer, _OwnedQualifiedSymbolAnalyzer):
        for node_id, value in analyzer.flow_node_values.items():
            markers = _owned_markers(value, analyzer.owned_marker_vocabulary)
            if markers:
                owned_values[node_id] = _OwnedFlowValue(markers, _OWNED_UNRESOLVED_MARKER in markers, value.reachability_overflow, bool(value.deferred_origins), value.location_uncertain or value.bound_mutator_uncertain)
        owned_expressions = tuple(sorted((node for node_id, node in analyzer.owned_expression_nodes.items() if node_id in owned_values), key=lambda node: (node.lineno, node.col_offset, type(node).__name__)))
        owned_controls = analyzer.owned_controls
        owned_benign_mutation_lines = frozenset(analyzer.owned_benign_mutation_lines)
    return _SourceAnalysis(analyzer.tree, functions, module_bindings, function_definition_counts, function_binding_event_counts, analysis, MappingProxyType(dict(analyzer.parents)), MappingProxyType({node_id: scope.path for node_id, scope in analyzer.node_scopes.items()}), MappingProxyType(owned_values), owned_expressions, owned_controls, owned_benign_mutation_lines, execution_changed_function_roots)
def _qualified_analysis(source: str, *, module_name: str) -> qualified.QualifiedSymbolAnalysis:
    """Construct one fresh canonical qualified-symbol result."""
    return _source_analysis(source, module_name=module_name).analysis


class _AnalysisSession:
    """Bounded memoization owned by one architecture-check invocation."""

    def __init__(self) -> None:
        self._analyses: dict[tuple[str, str, bool], _SourceAnalysis] = {}
    def source_analysis(self, source: str, *, module_name: str, owned: bool = False) -> _SourceAnalysis:
        key = (module_name, source, owned)
        existing = self._analyses.get(key)
        if existing is None and not owned:
            existing = self._analyses.get((module_name, source, True))
        if existing is not None:
            return existing
        if len(self._analyses) >= _MAX_ANALYSES_PER_SESSION:
            raise RuntimeError("analysis-session-limit")
        result = _source_analysis(source, module_name=module_name, owned=owned)
        self._analyses[key] = result
        return result

    def qualified_analysis(self, source: str, *, module_name: str) -> qualified.QualifiedSymbolAnalysis:
        return self.source_analysis(source, module_name=module_name).analysis

class ProjectionManifest(NamedTuple):
    phase: CalibrationEvidencePhase
    name: str
    fields: tuple[str, ...]
    field_count: int
    schema: str | None


class IdentityManifest(NamedTuple):
    phase: CalibrationEvidencePhase
    name: str
    domain: str
    stage2f_owned: bool


class PhaseManifest(NamedTuple):
    phase: CalibrationEvidencePhase
    module_present: bool
    projection_classes: frozenset[str]
    identity_functions: frozenset[str]
    identity_domains: tuple[tuple[str, str], ...]
    schemas: tuple[tuple[str, str | None], ...]
    public_validators: frozenset[str]


type OwnedPathStepKind = Literal["attribute", "index-literal", "index-symbol"]
type OwnedArgumentKind = Literal["expression", "producer"]

# fmt: off
OwnedPathStep = NamedTuple("OwnedPathStep", [("kind", OwnedPathStepKind), ("value", str | int)])
OwnedArgument = NamedTuple("OwnedArgument", [("kind", OwnedArgumentKind), ("value", str), ("path", tuple[OwnedPathStep, ...])])
OwnedProducer = NamedTuple("OwnedProducer", [("key", str), ("owner", str), ("qualified_target", str), ("arguments", tuple[OwnedArgument, ...]), ("result_path", tuple[OwnedPathStep, ...]), ("legacy_detail", str | None)])
OwnedCarrier = NamedTuple("OwnedCarrier", [("root_parameter", str), ("path", tuple[OwnedPathStep, ...]), ("validators", tuple[tuple[str, int], ...])])
OwnedComparison = NamedTuple("OwnedComparison", [("operator", Literal["NotEq"]), ("carrier_side", Literal["left"]), ("group_rank", int), ("occurrence_rank", int), ("producer_path", tuple[OwnedPathStep, ...])])
OwnedFailure = NamedTuple("OwnedFailure", [("helper", str), ("code", str), ("path", str), ("dispatcher", str), ("dispatcher_index", int)])
OwnedEdge = NamedTuple("OwnedEdge", [("owner", str), ("operation", str), ("producer", str), ("carrier", OwnedCarrier), ("comparison", OwnedComparison), ("failure", OwnedFailure)])
P2OwnedOperations = NamedTuple("P2OwnedOperations", [("key_fields", OwnedEdge), ("projection_oracle_key", OwnedEdge), ("selector_oracle_key", OwnedEdge), ("paired_oracle_key", OwnedEdge), ("revealed_observation", OwnedEdge), ("projection_outcome_digest", OwnedEdge), ("selector_outcome_digest", OwnedEdge)])
OwnedDataflowManifest = NamedTuple("OwnedDataflowManifest", [("producers", tuple[OwnedProducer, ...]), ("operations", P2OwnedOperations), ("index_counts", tuple[tuple[str, int], ...])])
PROJECTION_MANIFESTS: Final = (
    ProjectionManifest("P1", "CalibrationCandidatePairProjection", ("adam_candidate_id", "comparison_group_id", "replication_id", "schema_version", "sgd_candidate_id", "world_id"), 6, "broader-replication-calibration-candidate-pair/v1"),
    ProjectionManifest("P1", "StrictChronologyProjection", ("current_effect_excluded", "current_observation_excluded", "effect_available_sequences", "future_history_excluded", "schema_version", "source_sequence_cutoff"), 6, "broader-replication-calibration-chronology/v1"),
    ProjectionManifest("P2", "CalibrationSourceObservationProjection", ("candidate_id", "comparison_group_id", "digest", "intervention_arm", "key_fields", "namespace", "oracle_key_id", "outcome_digest", "replication_id", "revealed_observation", "schema_version", "seed", "serialized_key_hex", "u", "world_id", "z"), 16, "broader-replication-calibration-source-observation/v1"),
    ProjectionManifest("P3", "ScientificCalibrationSelectionProjection", ("comparison_group_id", "ddof", "effect_values", "eligibility_basis", "estimated_sigma", "namespace", "sample_count", "sample_mean", "sample_standard_deviation", "seed", "sigma_floor", "source_candidate_pairs", "source_effect_ids", "source_effect_payload_sha256", "source_observation_identities", "source_oracle_key_ids", "source_replication_ids", "source_sequence_cutoff", "study_id", "target_comparison_group_id", "world_id"), 21, None),
    ProjectionManifest("P4", "CalibrationSelectionProjection", ("calibration_namespace", "comparison_group_id", "current_oracle_binding_id", "current_oracle_execution_id", "evidence_contract_checkpoint", "execution_specification_id", "executor_attestation_id", "implementation", "ordered_candidate_pair_ids", "ordered_candidate_pairs", "ordered_replication_ids", "ordered_source_effect_ids", "ordered_source_effects", "ordered_source_observations", "protocol_checkpoint", "schema_version", "seed", "selection_issuer_identity", "selector_result_identity", "selector_result_projection", "strict_chronology", "strict_chronology_id", "study_id", "runtime", "runtime_identity", "validation_authority_id", "validation_run_id", "world_id"), 28, "broader-replication-calibration-selection-binding/v1"),
)
IDENTITY_MANIFESTS: Final = (
    IdentityManifest("P1", "calibration_candidate_pair_id", "validation_evidence_calibration_candidate_pair/v1", True),
    IdentityManifest("P1", "strict_chronology_id", "validation_evidence_calibration_chronology/v1", True),
    IdentityManifest("P2", "source_observation_identity", "validation_evidence_calibration_source_observation/v1", True),
    IdentityManifest("P3", "selection_identity", "broader-calibration-history-selection/v1", False),
    IdentityManifest("P4", "calibration_selection_id", "validation_evidence_calibration_selection/v1", True),
)
_PHASE_ORDER: Final = ("C0", "P1", "P2", "P3", "P4")


def _phase_manifest(phase: CalibrationEvidencePhase) -> PhaseManifest:
    phase_index = _PHASE_ORDER.index(phase)
    projections = tuple(item for item in PROJECTION_MANIFESTS if _PHASE_ORDER.index(item.phase) <= phase_index)
    identities = tuple(item for item in IDENTITY_MANIFESTS if _PHASE_ORDER.index(item.phase) <= phase_index)
    return PhaseManifest(
        phase,
        phase != "C0",
        frozenset(item.name for item in projections),
        frozenset(item.name for item in identities if item.stage2f_owned),
        tuple((item.name, item.domain) for item in identities),
        tuple((item.name, item.schema) for item in projections),
        frozenset(),
    )


C0_MANIFEST: Final = _phase_manifest("C0")
P1_MANIFEST: Final = _phase_manifest("P1")
P2_MANIFEST: Final = _phase_manifest("P2")
P3_MANIFEST: Final = _phase_manifest("P3")
P4_MANIFEST: Final = _phase_manifest("P4")
PHASE_MANIFESTS: Final = (C0_MANIFEST, P1_MANIFEST, P2_MANIFEST, P3_MANIFEST, P4_MANIFEST)
CURRENT_MANIFEST: Final = P3_MANIFEST
PROJECTION_FIELDS: Final = {item.name: item.fields for item in PROJECTION_MANIFESTS}
PROJECTION_FIELD_COUNTS: Final = {item.name: item.field_count for item in PROJECTION_MANIFESTS}
OWNED_OPERATION_MANIFEST: Final = OwnedDataflowManifest(producers=(
        OwnedProducer("p21-coordinate", "_predicate_3o_2_1", f"{CANONICAL_MODULE}._expected_source_coordinate", (OwnedArgument("expression", "selection", ()), OwnedArgument("expression", "observation_index", ())), (OwnedPathStep("index-literal", 6),), None),
        OwnedProducer("p21-oracle-key", "_predicate_3o_2_1", f"{CANONICAL_MODULE}._oracle_key_id", (OwnedArgument("producer", "p21-coordinate", ()),), (), "oracle-key-recompute"),
        OwnedProducer("p31-world", "_predicate_3o_3_1", f"{CANONICAL_MODULE}._exact_frozen_world", (OwnedArgument("expression", "expected_predecessor", (OwnedPathStep("index-literal", 10),)), OwnedArgument("expression", "selection", (OwnedPathStep("index-literal", 2),)), OwnedArgument("expression", "selection", (OwnedPathStep("index-literal", 10),))), (), None),
        OwnedProducer("p31-observation", "_predicate_3o_3_1", f"{CANONICAL_MODULE}._expected_observation_f64", (OwnedArgument("expression", "selection", ()), OwnedArgument("expression", "observation_index", ()), OwnedArgument("producer", "p31-world", ())), (), "selected-only-reconstruction"),
        OwnedProducer("p31-coordinate", "_predicate_3o_3_1", f"{CANONICAL_MODULE}._expected_source_coordinate", (OwnedArgument("expression", "selection", ()), OwnedArgument("expression", "observation_index", ())), (OwnedPathStep("index-literal", 6),), None),
        OwnedProducer("p31-oracle-key", "_predicate_3o_3_1", f"{CANONICAL_MODULE}._oracle_key_id", (OwnedArgument("producer", "p31-coordinate", ()),), (), None),
        OwnedProducer("p31-digest", "_predicate_3o_3_1", f"{CANONICAL_MODULE}._outcome_digest", (OwnedArgument("producer", "p31-oracle-key", ()), OwnedArgument("producer", "p31-observation", ())), (), "outcome-digest-recompute"),
    ), operations=P2OwnedOperations(
        key_fields=OwnedEdge("_predicate_3o_2_1", "key-fields", "p21-coordinate", OwnedCarrier("p2_selection", (OwnedPathStep("index-literal", 1), OwnedPathStep("index-symbol", "observation_index"), OwnedPathStep("index-literal", 0), OwnedPathStep("attribute", "key_fields"), OwnedPathStep("index-symbol", "field_index")), (("_require_exact_source_observation_object", 3), ("_source_key_fields", 4))), OwnedComparison("NotEq", "left", 0, 0, (OwnedPathStep("index-symbol", "field_index"),)), OwnedFailure("_oracle_key_failure", "CALIBRATION_ORACLE_KEY_ID_MISMATCH", "calibration/3o.2.1/oracle_key", "_validate_stage2f_p2", 1)),
        projection_oracle_key=OwnedEdge("_predicate_3o_2_1", "projection-oracle-key", "p21-oracle-key", OwnedCarrier("p2_selection", (OwnedPathStep("index-literal", 1), OwnedPathStep("index-symbol", "observation_index"), OwnedPathStep("index-literal", 0), OwnedPathStep("attribute", "oracle_key_id")), (("_require_exact_source_observation_object", 3), ("_exact_oracle_key_id", 4))), OwnedComparison("NotEq", "left", 1, 0, ()), OwnedFailure("_oracle_key_failure", "CALIBRATION_ORACLE_KEY_ID_MISMATCH", "calibration/3o.2.1/oracle_key", "_validate_stage2f_p2", 1)),
        selector_oracle_key=OwnedEdge("_predicate_3o_2_1", "selector-oracle-key", "p21-oracle-key", OwnedCarrier("selection", (OwnedPathStep("index-literal", 16), OwnedPathStep("attribute", "source_oracle_key_ids"), OwnedPathStep("index-symbol", "observation_index")), (("_exact_oracle_key_id", 3),)), OwnedComparison("NotEq", "left", 1, 1, ()), OwnedFailure("_oracle_key_failure", "CALIBRATION_ORACLE_KEY_ID_MISMATCH", "calibration/3o.2.1/oracle_key", "_validate_stage2f_p2", 1)),
        paired_oracle_key=OwnedEdge("_predicate_3o_2_1", "paired-oracle-key", "p21-oracle-key", OwnedCarrier("selection", (OwnedPathStep("index-literal", 16), OwnedPathStep("attribute", "source_observation_identities"), OwnedPathStep("index-symbol", "observation_index"), OwnedPathStep("index-literal", 0)), (("_exact_oracle_key_id", 4),)), OwnedComparison("NotEq", "left", 1, 2, ()), OwnedFailure("_oracle_key_failure", "CALIBRATION_ORACLE_KEY_ID_MISMATCH", "calibration/3o.2.1/oracle_key", "_validate_stage2f_p2", 1)),
        revealed_observation=OwnedEdge("_predicate_3o_3_1", "revealed-observation", "p31-observation", OwnedCarrier("p2_selection", (OwnedPathStep("index-literal", 1), OwnedPathStep("index-symbol", "observation_index"), OwnedPathStep("index-literal", 0), OwnedPathStep("attribute", "revealed_observation")), (("_require_exact_source_observation_object", 3), ("_exact_f64_string", 4))), OwnedComparison("NotEq", "left", 0, 0, ()), OwnedFailure("_outcome_failure", "CALIBRATION_OUTCOME_DIGEST_MISMATCH", "calibration/3o.3.1/outcome", "_validate_stage2f_p2", 2)),
        projection_outcome_digest=OwnedEdge("_predicate_3o_3_1", "projection-outcome-digest", "p31-digest", OwnedCarrier("p2_selection", (OwnedPathStep("index-literal", 1), OwnedPathStep("index-symbol", "observation_index"), OwnedPathStep("index-literal", 0), OwnedPathStep("attribute", "outcome_digest")), (("_require_exact_source_observation_object", 3), ("_exact_h64", 4))), OwnedComparison("NotEq", "left", 1, 0, ()), OwnedFailure("_outcome_failure", "CALIBRATION_OUTCOME_DIGEST_MISMATCH", "calibration/3o.3.1/outcome", "_validate_stage2f_p2", 2)),
        selector_outcome_digest=OwnedEdge("_predicate_3o_3_1", "selector-outcome-digest", "p31-digest", OwnedCarrier("selection", (OwnedPathStep("index-literal", 16), OwnedPathStep("attribute", "source_observation_identities"), OwnedPathStep("index-symbol", "observation_index"), OwnedPathStep("index-literal", 1)), (("_exact_h64", 4),)), OwnedComparison("NotEq", "left", 1, 1, ()), OwnedFailure("_outcome_failure", "CALIBRATION_OUTCOME_DIGEST_MISMATCH", "calibration/3o.3.1/outcome", "_validate_stage2f_p2", 2)),
    ), index_counts=(("field_index", 8), ("observation_index", 10)))
FUTURE_FIXED_LITERALS: Final = (("calibration_namespace", "rde.broader.calibration-outcome/v1"), ("study", "broader-closed-loop-replication/v1"), ("oracle_namespace", "broader_selected_only_oracle/v1"), ("protocol_checkpoint", "89c0b4fadba33b9fd9a257b43eacf476b7779d59"), ("evidence_contract_checkpoint", "cbeea072ed39697e2cd42ca571685faed5f6ead8"), ("source_sequence_cutoff", 1), ("pair_arm_order", ("adam", "sgd")), ("replications", (1, 2, 3, 4, 5)))
_PHASE_FIXED_LITERAL_KEYS: Final = {
    "C0": frozenset(),
    "P1": _names("calibration_namespace study source_sequence_cutoff pair_arm_order replications"),
    "P2": _names("calibration_namespace study oracle_namespace source_sequence_cutoff pair_arm_order replications"),
    "P3": _names("calibration_namespace study oracle_namespace source_sequence_cutoff pair_arm_order replications"),
    "P4": frozenset(key for key, _ in FUTURE_FIXED_LITERALS),
}
# fmt: on

_PROTOCOL = "research_decision_engine.benchmarks.broader_protocol"
_EXECUTION = "research_decision_engine.benchmarks.broader_execution"
_RETURNED = "research_decision_engine.benchmarks.broader_returned_run"
_REPLAY = "research_decision_engine.benchmarks.broader_calibration_selector_replay"
_HISTORY = "research_decision_engine.benchmarks.broader_calibration_history"
_ORACLE = "research_decision_engine.benchmarks.broader_oracle"
_WORLDS = "research_decision_engine.benchmarks.broader_worlds"
_PROTOCOL_HASH_TARGET = f"{_PROTOCOL}.protocol_hash"
_RUNTIME_ID_TARGET = f"{_PROTOCOL}.runtime_id"
_SOURCE_OBSERVATION_ID_TARGET = f"{CANONICAL_MODULE}.source_observation_identity"
_SELECTION_IDENTITY_DOMAIN: Final = "broader-calibration-history-selection/v1"
_REPLAY_TARGET = f"{_REPLAY}.replay_calibration_history_selection"

# fmt: off
_OWNED_FLOW_PREFIX: Final = f"{CANONICAL_MODULE}.__stage2f_owned_flow__"
_OWNED_UNRESOLVED_MARKER: Final = f"{_OWNED_FLOW_PREFIX}.unresolved"
_OWNED_CONTINUATION_MARKER: Final = f"{_OWNED_FLOW_PREFIX}.continuation"
_OWNED_NONEMPTY_LOOP_MARKER: Final = f"{_OWNED_FLOW_PREFIX}.nonempty_loop"
_P3_B_RESULT_MARKER: Final = f"{_OWNED_FLOW_PREFIX}.p3.b.result"
_P3_H_RESULT_MARKER: Final = f"{_OWNED_FLOW_PREFIX}.p3.h.result"
_P3_B_DECISION_MARKER: Final = f"{_OWNED_FLOW_PREFIX}.p3.b.decision"
_P3_H_DECISION_MARKER: Final = f"{_OWNED_FLOW_PREFIX}.p3.h.decision"
_P3_SELECTOR_FAILURE_MARKER: Final = f"{_OWNED_FLOW_PREFIX}.p3.selector_failure"
_P3_PREDICATE_RESULT_MARKER: Final = f"{_OWNED_FLOW_PREFIX}.p3.predicate.result"
_P3_PREDICATE_DECISION_MARKER: Final = f"{_OWNED_FLOW_PREFIX}.p3.predicate.decision"
_P3_OUTCOME_MARKER: Final = f"{_OWNED_FLOW_PREFIX}.p3.outcome"
_P3_FLOW_OWNER_NAMES: Final = frozenset(
    {
        "_first_history_nonidentity_mismatch",
        "_predicate_3o_5_1",
        "_validate_stage2f_p3",
    }
)
_OWNED_DEFERRED_WRITE_PREFIX: Final = f"{_OWNED_FLOW_PREFIX}.deferred_write."; _OWNED_VALIDATION_PREFIX: Final = f"{_OWNED_FLOW_PREFIX}.validation."
def _owned_operation_items() -> tuple[tuple[str, OwnedEdge], ...]: return tuple(zip(OWNED_OPERATION_MANIFEST.operations._fields, OWNED_OPERATION_MANIFEST.operations, strict=True))
def _owned_producer_marker(key: str, position: int | None = None) -> str: return f"{_OWNED_FLOW_PREFIX}.producer.{key}.{'result' if position is None else f'path_{position}'}"
def _owned_carrier_marker(slot: str, position: int) -> str: return f"{_OWNED_FLOW_PREFIX}.carrier.{slot}.path_{position}"
def _owned_argument_marker(producer: str, argument: int, position: int) -> str: return f"{_OWNED_FLOW_PREFIX}.argument.{producer}.{argument}.path_{position}"
def _owned_comparison_marker(slot: str, position: int) -> str: return f"{_OWNED_FLOW_PREFIX}.comparison.{slot}.path_{position}"
def _owned_group_marker(owner: str, group: int) -> str: return f"{_OWNED_FLOW_PREFIX}.group.{owner}.{group}.complete"
def _owned_group_validation_marker(owner: str, group: int) -> str: return f"{_OWNED_FLOW_PREFIX}.group.{owner}.{group}.validated"
def _owned_ordered_group_marker(owner: str, group: int) -> str: return f"{_OWNED_FLOW_PREFIX}.group.{owner}.{group}.ordered"
def _owned_control_marker(slot: str) -> str: return f"{_OWNED_FLOW_PREFIX}.control.{slot}"
def _owned_index_marker(symbol: str) -> str: return f"{_OWNED_FLOW_PREFIX}.index.{symbol}"
def _owned_certification_marker(marker: str) -> bool: return marker == _OWNED_NONEMPTY_LOOP_MARKER or any(part in marker for part in (".control.", ".group.", ".index.", ".validation."))
def _owned_benign_group_noop(node: ast.AST) -> bool: return isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add) and isinstance(node.value, (ast.List, ast.Tuple)) and not node.value.elts
def _owned_marker_vocabulary() -> frozenset[str]:
    vocabulary = {_OWNED_UNRESOLVED_MARKER, _OWNED_CONTINUATION_MARKER, _OWNED_NONEMPTY_LOOP_MARKER, _P3_B_RESULT_MARKER, _P3_H_RESULT_MARKER, _P3_B_DECISION_MARKER, _P3_H_DECISION_MARKER, _P3_SELECTOR_FAILURE_MARKER, _P3_PREDICATE_RESULT_MARKER, _P3_PREDICATE_DECISION_MARKER, _P3_OUTCOME_MARKER}
    for producer in OWNED_OPERATION_MANIFEST.producers:
        vocabulary.add(_owned_producer_marker(producer.key)); vocabulary.update(_owned_producer_marker(producer.key, position) for position in range(len(producer.result_path)))
        for index, argument in enumerate(producer.arguments):
            vocabulary.update(_owned_argument_marker(producer.key, index, position) for position in range(len(argument.path) + 1))
    for slot, edge in _owned_operation_items():
        vocabulary.update(_owned_carrier_marker(slot, position) for position in range(len(edge.carrier.path) + 1)); vocabulary.update(f"{_OWNED_VALIDATION_PREFIX}{slot}.stage_{position}" for position in range(len(edge.carrier.validators))); vocabulary.update(_owned_comparison_marker(slot, position) for position in range(1, len(edge.comparison.producer_path) + 1)); vocabulary.update((_owned_group_marker(edge.owner, edge.comparison.group_rank), _owned_group_validation_marker(edge.owner, edge.comparison.group_rank), _owned_ordered_group_marker(edge.owner, edge.comparison.group_rank), _owned_control_marker(slot)))
    vocabulary.update(_owned_index_marker(symbol) for symbol, _count in OWNED_OPERATION_MANIFEST.index_counts); return frozenset(vocabulary)
def _owned_markers(value: qualified.ResolvedValue, vocabulary: frozenset[str] | None = None) -> frozenset[str]: vocabulary = _owned_marker_vocabulary() if vocabulary is None else vocabulary; return frozenset(origin for origin in (value.direct_origins | value.aggregate_origins | value.deferred_origins) if origin in vocabulary)
def _with_owned_markers(value: qualified.ResolvedValue, markers: frozenset[str]) -> qualified.ResolvedValue:
    return value if not markers else value._replace(aggregate_origins=value.aggregate_origins | markers)
def _with_owned_markers_deep(value: qualified.ResolvedValue, markers: frozenset[str]) -> qualified.ResolvedValue: return (enriched := _with_owned_markers(value, markers))._replace(sequence_elements=None if enriched.sequence_elements is None else tuple(_with_owned_markers_deep(element, markers) for element in enriched.sequence_elements), mapping_entries=None if enriched.mapping_entries is None else tuple((key, _with_owned_markers_deep(item, markers)) for key, item in enriched.mapping_entries))
def _replace_owned_markers(value: qualified.ResolvedValue, removed: set[str], added: set[str]) -> qualified.ResolvedValue:
    return value._replace(direct_origins=value.direct_origins - removed, aggregate_origins=(value.aggregate_origins - removed) | added, deferred_origins=value.deferred_origins - removed)
def _strip_owned_markers(value: qualified.ResolvedValue, removed: set[str]) -> qualified.ResolvedValue: return (cleaned := _replace_owned_markers(value, removed, set()))._replace(sequence_elements=None if cleaned.sequence_elements is None else tuple(_strip_owned_markers(element, removed) for element in cleaned.sequence_elements), mapping_entries=None if cleaned.mapping_entries is None else tuple((key, _strip_owned_markers(item, removed)) for key, item in cleaned.mapping_entries))
def _strip_owned_store(store: qualified._AbstractStore, removed: set[str]) -> qualified._AbstractStore: return qualified._AbstractStore(tuple((location, container._replace(sequence_elements=None if container.sequence_elements is None else tuple(_strip_owned_markers(element, removed) for element in container.sequence_elements), mapping_entries=None if container.mapping_entries is None else tuple((key, _strip_owned_markers(item, removed)) for key, item in container.mapping_entries), unknown_value=_strip_owned_markers(container.unknown_value, removed))) for location, container in store.entries))
def _at_owned_producer_boundary(value: qualified.ResolvedValue, markers: frozenset[str]) -> qualified.ResolvedValue:
    def retained(origins: frozenset[str]) -> frozenset[str]: return frozenset(origin for origin in origins if not origin.startswith(_OWNED_FLOW_PREFIX))
    return value._replace(direct_origins=retained(value.direct_origins), aggregate_origins=retained(value.aggregate_origins) | markers, deferred_origins=retained(value.deferred_origins))
def _owned_path_step_matches(node: ast.AST, step: OwnedPathStep) -> bool:
    return step.kind == "attribute" and isinstance(node, ast.Attribute) and node.attr == step.value or isinstance(node, ast.Subscript) and (step.kind == "index-literal" and isinstance(node.slice, ast.Constant) and node.slice.value == step.value or step.kind == "index-symbol" and isinstance(node.slice, ast.Name))
def _p2_safe_string_expression(node: ast.AST) -> bool: return isinstance(node, ast.Constant) and type(node.value) is str or isinstance(node, ast.JoinedStr) and all(isinstance(part, ast.Constant) and type(part.value) is str or isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name) and part.conversion == -1 and part.format_spec is None for part in node.values)
class _OwnedQualifiedSymbolAnalyzer(qualified._QualifiedSymbolAnalyzer):
    """The canonical analyzer enriched by the one owned-operation manifest."""
    def __init__(self, source: str, module_name: str) -> None:
        self.owned_edges = _owned_operation_items()
        self.p3_owner_targets = frozenset(f"{CANONICAL_MODULE}.{name}" for name in _P3_FLOW_OWNER_NAMES); self.owned_owner_targets = frozenset(f"{CANONICAL_MODULE}.{edge.owner}" for _slot, edge in self.owned_edges) | self.p3_owner_targets; leaf_validation_targets = frozenset(f"{CANONICAL_MODULE}.{validator}" for _slot, edge in self.owned_edges for validator, _position in edge.carrier.validators); self.owned_validation_targets = leaf_validation_targets | {f"{CANONICAL_MODULE}._validate_source_observation_key_surface", f"{CANONICAL_MODULE}._validate_source_observation_outcome_surface"}; self.owned_validation_stages = MappingProxyType({target: tuple((slot, stage, path_position, frozenset(f"{_OWNED_VALIDATION_PREFIX}{slot}.stage_{prior}" for prior in range(stage))) for slot, edge in self.owned_edges for stage, (validator, path_position) in enumerate(edge.carrier.validators) if target == f"{CANONICAL_MODULE}.{validator}") for target in leaf_validation_targets})
        self.owned_groups = tuple((owner, group, tuple(sorted(((edge.comparison.occurrence_rank, slot, edge) for slot, edge in self.owned_edges if edge.owner == owner and edge.comparison.group_rank == group)))) for owner, group in {(edge.owner, edge.comparison.group_rank) for _slot, edge in self.owned_edges})
        self.owned_expression_nodes: dict[int, ast.expr] = {}; self.owned_marker_vocabulary = _owned_marker_vocabulary(); self.owned_loop_entries: list[tuple[int, bool]] = []; self.owned_statement_stack: list[ast.stmt] = []
        self.owned_try_contexts: list[tuple[int, int, int | None]] = []; self.owned_active_helper_target: str | None = None
        self.owned_benign_mutation_lines: set[tuple[int, str]] = set()
        super().__init__(source, module_name)
        self.owned_controls = MappingProxyType(self._owned_control_inventory())
    def _flow_function_needs_temporal_analysis(self, target: str, function: ast.FunctionDef | ast.AsyncFunctionDef, function_scope: qualified._Scope) -> bool:
        return target == self.owned_active_helper_target or target in self.owned_owner_targets or super()._flow_function_needs_temporal_analysis(target, function, function_scope)
    def _flow_apply_local_helper(self, call: ast.Call, target: str, function: ast.FunctionDef | ast.AsyncFunctionDef, child: qualified._Scope, call_scope: qualified._Scope, caller: qualified._FlowState, positional: tuple[qualified.ResolvedValue, ...], keywords: tuple[tuple[str | None, qualified.ResolvedValue], ...], active_functions: frozenset[str]) -> tuple[qualified.ResolvedValue, qualified._FlowState]:
        prior = self.owned_active_helper_target; self.owned_active_helper_target = target if self._owned_context(active_functions) else None
        try: return super()._flow_apply_local_helper(call, target, function, child, call_scope, caller, positional, keywords, active_functions)
        finally: self.owned_active_helper_target = prior
    def _owned_context(self, active_functions: frozenset[str]) -> bool: return not self.owned_owner_targets.isdisjoint(active_functions)
    def _p3_context(self, active_functions: frozenset[str]) -> bool: return not self.p3_owner_targets.isdisjoint(active_functions)
    def _p3_direct_control_markers(self, node: ast.AST) -> frozenset[str]:
        ancestor = self.parents.get(id(node))
        while ancestor is not None and not isinstance(ancestor, (ast.AsyncFunctionDef, ast.FunctionDef)):
            if isinstance(ancestor, ast.If):
                return _owned_markers(self._owned_recorded_value(ancestor.test), self.owned_marker_vocabulary)
            if isinstance(ancestor, (ast.AsyncFor, ast.AsyncWith, ast.For, ast.Match, ast.Try, ast.TryStar, ast.While, ast.With)):
                return frozenset()
            ancestor = self.parents.get(id(ancestor))
        return frozenset()
    def _p3_history_result_marker(self, node: ast.Call, call_targets: frozenset[str], scope: qualified._Scope) -> str | None:
        if scope.path != ("_predicate_3o_5_1",) or call_targets != frozenset({f"{CANONICAL_MODULE}._first_history_nonidentity_mismatch"}) or node.keywords:
            return None
        arguments = tuple(ast.unparse(argument) for argument in node.args)
        common = ("expected_projection", "expected_effects", "expected_observations", "physical_cost")
        if arguments == ("actual_helper_result", *common):
            return _P3_B_RESULT_MARKER
        if arguments == ("historical_selection", *common):
            return _P3_H_RESULT_MARKER
        return None
    def _p3_predicate_call_is_exact(self, node: ast.Call, call_targets: frozenset[str], scope: qualified._Scope) -> bool:
        return bool(
            scope.path == ("_validate_stage2f_p3",)
            and call_targets == frozenset({f"{CANONICAL_MODULE}._predicate_3o_5_1"})
            and not node.keywords
            and tuple(ast.unparse(argument) for argument in node.args)
            == (
                "selections[selection_index]",
                "p2_selections[selection_index]",
                "expected_predecessors[selection_index]",
                "expected_execution_attestation_pairs",
                "attested_execution_specification_ids",
                "validated_returned_results_by_role",
                "p3_inputs[selection_index]",
                "selection_index",
            )
        )
    def _p3_outcome_call_is_exact(self, node: ast.Call, call_targets: frozenset[str]) -> bool:
        if call_targets != frozenset({f"{CANONICAL_MODULE}._p3_outcome"}) or node.keywords or len(node.args) != 4:
            return False
        first_markers = _owned_markers(self._owned_recorded_value(node.args[0]), self.owned_marker_vocabulary)
        return bool(
            _P3_PREDICATE_RESULT_MARKER in first_markers
            and _OWNED_UNRESOLVED_MARKER not in first_markers
            and tuple(ast.unparse(argument) for argument in node.args[1:])
            == ("selection_index", "p2_counts", "p3_count")
            and _P3_PREDICATE_DECISION_MARKER in self._p3_direct_control_markers(node)
        )
    def _p3_selector_failure_chain_is_exact(
        self,
        node: ast.Call,
        call_targets: frozenset[str],
        *,
        depth: int = 0,
    ) -> bool:
        selector_target = f"{CANONICAL_MODULE}._selector_result_failure"
        if call_targets == frozenset({selector_target}):
            return bool(
                len(node.args) == 1
                and not node.keywords
                and _p2_safe_string_expression(node.args[0])
            )
        if depth >= 2 or len(call_targets) != 1:
            return False
        target = next(iter(call_targets))
        definitions = self.local_functions.get(target, ())
        if len(definitions) != 1:
            return False
        function, _child = definitions[0]
        body = tuple(
            statement
            for statement in function.body
            if not (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            )
        )
        if (
            function.decorator_list
            or len(body) != 1
            or not isinstance(body[0], ast.Return)
            or not isinstance(body[0].value, ast.Call)
        ):
            return False
        returned_call = body[0].value
        returned_targets = self._owned_recorded_value(
            returned_call.func
        ).direct_origins
        return self._p3_selector_failure_chain_is_exact(
            returned_call,
            returned_targets,
            depth=depth + 1,
        )
    def _owned_recorded_value(self, node: ast.AST) -> qualified.ResolvedValue: return self.flow_node_values.get(id(node), qualified.ResolvedValue())
    def _owned_index_binding_markers(self, node: ast.AST, name: str | None = None) -> frozenset[str]: name = node.id if name is None and isinstance(node, ast.Name) else name; parent = self.parents.get(id(node)); markers = frozenset(f"{_owned_index_marker(symbol)}.binding_{parent.lineno}_{parent.col_offset}" for symbol, count in OWNED_OPERATION_MANIFEST.index_counts if isinstance(parent, ast.For) and isinstance(parent.target, ast.Name) and parent.target.id == name and isinstance(parent.iter, ast.Call) and isinstance(parent.iter.func, ast.Name) and parent.iter.func.id == "range" and len(parent.iter.args) == 1 and not parent.iter.keywords and isinstance(parent.iter.args[0], ast.Constant) and parent.iter.args[0].value == count); return (setattr(self, "owned_marker_vocabulary", self.owned_marker_vocabulary | markers) or markers) if markers else frozenset() if isinstance(parent, (ast.AsyncFunctionDef, ast.FunctionDef, ast.Lambda)) or parent is None or isinstance(parent, (ast.AsyncFor, ast.For)) and isinstance(parent.target, ast.Name) and parent.target.id == name else self._owned_index_binding_markers(parent, name)  # type: ignore[func-returns-value]
    def _owned_call_matches(self, node: ast.Call, producer: OwnedProducer) -> bool:
        if not isinstance(node.func, ast.Name) or node.keywords or len(node.args) != len(producer.arguments) or self._owned_recorded_value(node.func).direct_origins != frozenset({producer.qualified_target}):
            return False
        for argument_index, (argument_node, requirement) in enumerate(zip(node.args, producer.arguments, strict=True)):
            if isinstance(argument_node, ast.Starred): return False
            markers = _owned_markers(self._owned_recorded_value(argument_node), self.owned_marker_vocabulary)
            required = _owned_argument_marker(producer.key, argument_index, len(requirement.path)) if requirement.kind == "expression" else _owned_producer_marker(requirement.value)
            if required not in markers or _OWNED_UNRESOLVED_MARKER in markers: return False
        return True
    def _owned_group_iterable(self, node: ast.expr) -> bool: return isinstance(node, (ast.Name, ast.Tuple))
    def _owned_path_step_matches(self, node: ast.AST, step: OwnedPathStep) -> bool:
        return _owned_path_step_matches(node, step) and (step.kind != "index-symbol" or _owned_index_marker(cast(str, step.value)) in _owned_markers(self._owned_recorded_value(cast(ast.Subscript, node).slice), self.owned_marker_vocabulary) and _OWNED_UNRESOLVED_MARKER not in _owned_markers(self._owned_recorded_value(cast(ast.Subscript, node).slice), self.owned_marker_vocabulary))
    def _owned_control_inventory(self) -> dict[str, tuple[ast.If, ...]]:
        controls: dict[str, list[ast.If]] = {slot: [] for slot, _edge in self.owned_edges}
        for expression in self.owned_expression_nodes.values():
            control = self.parents.get(id(expression))
            if not isinstance(control, ast.If) or control.test is not expression or control.orelse or len(control.body) != 1: continue
            returned = control.body[0]
            if not isinstance(returned, ast.Return) or not isinstance(returned.value, ast.Call): continue
            markers = _owned_markers(self._owned_recorded_value(expression), self.owned_marker_vocabulary)
            scope = self.node_scopes.get(id(expression), self.module_scope).path
            for slot, edge in self.owned_edges:
                producer_marker = _owned_comparison_marker(slot, len(edge.comparison.producer_path)) if edge.comparison.producer_path else _owned_producer_marker(edge.producer)
                carrier_marker = _owned_carrier_marker(slot, len(edge.carrier.path))
                group_size = sum(candidate.owner == edge.owner and candidate.comparison.group_rank == edge.comparison.group_rank for _candidate_slot, candidate in self.owned_edges)
                required = {producer_marker, carrier_marker, _owned_control_marker(slot)}
                if scope != (edge.owner,) or not required <= markers or _OWNED_UNRESOLVED_MARKER in markers or group_size > 1 and _owned_group_validation_marker(edge.owner, edge.comparison.group_rank) not in markers: continue
                if self._owned_recorded_value(returned.value.func).direct_origins != frozenset({f"{CANONICAL_MODULE}.{edge.failure.helper}"}) or len(returned.value.args) != 1 or returned.value.keywords or isinstance(returned.value.args[0], ast.Starred) or not _p2_safe_string_expression(returned.value.args[0]): continue
                ancestor = self.parents.get(id(control))
                while ancestor is not None and not isinstance(ancestor, (ast.AsyncFunctionDef, ast.FunctionDef)):
                    if isinstance(ancestor, (ast.AsyncWith, ast.If, ast.Match, ast.Try, ast.TryStar, ast.While, ast.With)): break
                    if isinstance(ancestor, (ast.AsyncFor, ast.For)) and (_OWNED_NONEMPTY_LOOP_MARKER not in _owned_markers(self._owned_recorded_value(ancestor.iter), self.owned_marker_vocabulary) or any(self._flow_statement_has_loop_abrupt(statement) for statement in (*ancestor.body, *ancestor.orelse))): break
                    ancestor = self.parents.get(id(ancestor))
                if isinstance(ancestor, (ast.AsyncFunctionDef, ast.FunctionDef)) and ancestor.name == edge.owner: controls[slot].append(control)
        return {slot: tuple(nodes) for slot, nodes in controls.items()}
    def _owned_complete_iterable(self, iterable: qualified.ResolvedValue, body: tuple[ast.stmt, ...] | list[ast.stmt], expression: ast.expr) -> qualified.ResolvedValue:
        abrupt = any(self._flow_statement_has_loop_abrupt(statement) for statement in body)
        validating = any(isinstance(candidate, ast.If) and isinstance(candidate.test, (ast.Compare, ast.Call)) for statement in body for candidate in ast.walk(statement))
        ordered = self._owned_group_iterable(expression)
        for owner, group, ranked in self.owned_groups:
            if len(ranked) < 2: continue
            inventory_marker = _owned_group_marker(owner, group)
            validation_marker = _owned_group_validation_marker(owner, group)
            iterable = _replace_owned_markers(iterable, {validation_marker}, set())
            terminals = frozenset(_owned_carrier_marker(slot, len(edge.carrier.path)) for _rank, slot, edge in ranked)
            elements = None if iterable.sequence_elements is None else list(iterable.sequence_elements)
            exact_ordered = False
            if elements is not None and len(elements) == len(ranked):
                payloads = tuple(element.sequence_elements[1] if element.sequence_elements is not None and len(element.sequence_elements) == 2 else None for element in elements)
                if ordered and all(payload is not None and _OWNED_UNRESOLVED_MARKER not in _owned_markers(payload, self.owned_marker_vocabulary) and (_owned_markers(payload, self.owned_marker_vocabulary) & terminals) == {_owned_carrier_marker(slot, len(edge.carrier.path))} for payload, (_rank, slot, edge) in zip(payloads, ranked, strict=True)):
                    exact_ordered = True
                    iterable = _replace_owned_markers(iterable, {_OWNED_UNRESOLVED_MARKER}, set())
                    payload_markers = frozenset({inventory_marker, *({validation_marker} if validating and not abrupt else set())})
                    for index, (element, payload) in enumerate(zip(elements, payloads, strict=True)):
                        assert payload is not None and element.sequence_elements is not None
                        elements[index] = element._replace(sequence_elements=(element.sequence_elements[0], _with_owned_markers(_replace_owned_markers(payload, {_OWNED_UNRESOLVED_MARKER}, set()), payload_markers)))
                    iterable = _with_owned_markers(iterable._replace(sequence_elements=tuple(elements)), frozenset({inventory_marker}))
            ordered_marker = _owned_ordered_group_marker(owner, group)
            if ordered and validating and not abrupt and inventory_marker in _owned_markers(iterable, self.owned_marker_vocabulary) and (exact_ordered or ordered_marker in _owned_markers(iterable, self.owned_marker_vocabulary)):
                iterable = _replace_owned_markers(iterable, {_OWNED_UNRESOLVED_MARKER}, {validation_marker})
        return iterable
    def _flow_join(self, states: tuple[qualified._FlowState, ...]) -> qualified._FlowState:
        result = super()._flow_join(states)
        if not self.owned_statement_stack:
            return result
        source_states = states
        try_prefix = False
        if self.owned_try_contexts and self.owned_statement_stack and id(self.owned_statement_stack[-1]) == self.owned_try_contexts[-1][0]:
            node_id, entry_id, handler_id = self.owned_try_contexts[-1]
            if handler_id is None and len(states) > 1 and id(states[0]) == entry_id:
                try_prefix = True
            elif handler_id is not None and len(states) > 1 and id(states[-1]) == handler_id:
                source_states = states[:-1]
        loop_nonempty = next((nonempty for identity, nonempty in reversed(self.owned_loop_entries) if source_states and id(source_states[0]) == identity), False)
        if loop_nonempty: source_states = source_states[1:]
        if len(source_states) < 2 and source_states is states: return result
        returned = tuple(state for state in source_states if qualified._flow_binding_get(state.bindings, "<return>") is not None); actual_returned = tuple(state for state in returned if _OWNED_CONTINUATION_MARKER not in _owned_markers(cast(qualified.ResolvedValue, qualified._flow_binding_get(state.bindings, "<return>")), self.owned_marker_vocabulary))
        continuing = tuple(state for state in source_states if (value := qualified._flow_binding_get(state.bindings, "<return>")) is None or _OWNED_CONTINUATION_MARKER in _owned_markers(value, self.owned_marker_vocabulary))
        bindings = []
        for name, value in result.bindings:
            sources = returned if name == "<return>" else continuing or source_states
            candidates = tuple(qualified._flow_binding_get(source.bindings, name) for source in sources)
            marker_sets = tuple(_owned_markers(candidate, self.owned_marker_vocabulary) - {_OWNED_CONTINUATION_MARKER} if candidate is not None else frozenset() for candidate in candidates); markerless = tuple(candidate for candidate, marker_set in zip(candidates, marker_sets, strict=True) if not marker_set)
            markers = set().union(*marker_sets)
            if marker_sets:
                common = set.intersection(*(set(marker_set) for marker_set in marker_sets)); markers.difference_update(marker for marker in markers - common if _owned_certification_marker(marker))
            if len(set(marker_sets)) > 1 and (name != "<return>" or self.owned_active_helper_target is not None and not (markerless and all(candidate is not None and candidate.static_key == self._literal_static_key(None) for candidate in markerless))): markers.add(_OWNED_UNRESOLVED_MARKER)
            if name == "<return>" and continuing: markers.add(_OWNED_CONTINUATION_MARKER); value = cast(qualified.ResolvedValue, qualified._flow_binding_get(actual_returned[0].bindings, name)) if len(actual_returned) == 1 else value
            bindings.append((name, _replace_owned_markers(value, set(self.owned_marker_vocabulary), markers)))
        joined = qualified._FlowState(tuple(bindings), result.store)
        if try_prefix: self.owned_try_contexts[-1] = (node_id, entry_id, id(joined))
        return joined
    def _flow_write_target(self, target: ast.expr, value: qualified.ResolvedValue, scope: qualified._Scope, state: qualified._FlowState, *, active_functions: frozenset[str] = frozenset()) -> qualified._FlowState:
        parent = self.parents.get(id(target))
        if self._owned_context(active_functions) and isinstance(parent, (ast.AnnAssign, ast.Assign, ast.NamedExpr)) and isinstance(parent.value, ast.Name): value = _with_owned_markers(value, self._owned_index_binding_markers(parent.value))
        inside_producer = scope.path and f"{CANONICAL_MODULE}.{scope.path[0]}" in {producer.qualified_target for producer in OWNED_OPERATION_MANIFEST.producers}
        if self._owned_context(active_functions) and isinstance(parent, ast.AugAssign) and not inside_producer and _owned_markers(value, self.owned_marker_vocabulary):
            benign_group_noop = _owned_benign_group_noop(parent)
            if benign_group_noop: self.owned_benign_mutation_lines.add((parent.lineno, ast.unparse(parent.target)))
            removed = set() if benign_group_noop else {_owned_ordered_group_marker(owner, group) for owner, group, _ranked in self.owned_groups}
            value = _replace_owned_markers(value, removed, {_OWNED_UNRESOLVED_MARKER})
        assignment_loop = self.parents.get(id(parent)) if isinstance(parent, ast.Assign) else None
        rhs = parent.value if isinstance(parent, ast.Assign) else None
        ordered_append = isinstance(target, ast.Name) and isinstance(rhs, ast.Tuple) and len(rhs.elts) == 2 and isinstance(rhs.elts[0], ast.Starred) and isinstance(rhs.elts[0].value, ast.Name) and rhs.elts[0].value.id == target.id and isinstance(rhs.elts[1], ast.Tuple) and len(rhs.elts[1].elts) == 2
        if self._owned_context(active_functions) and ordered_append and isinstance(assignment_loop, (ast.For, ast.AsyncFor)):
            loop_markers = _owned_markers(self._owned_recorded_value(assignment_loop.iter), self.owned_marker_vocabulary)
            for owner, group, ranked in self.owned_groups:
                payload_node = cast(ast.Tuple, cast(ast.Tuple, rhs).elts[1]).elts[1]
                payload_markers = _owned_markers(self._owned_recorded_value(payload_node), self.owned_marker_vocabulary)
                terminals = frozenset(_owned_carrier_marker(slot, len(edge.carrier.path)) for _rank, slot, edge in ranked)
                if ranked and isinstance(assignment_loop.iter, ast.Tuple) and _owned_group_marker(owner, group) in loop_markers and payload_markers & terminals == terminals and _OWNED_UNRESOLVED_MARKER not in payload_markers and not any(self._flow_statement_has_loop_abrupt(statement) for statement in (*assignment_loop.body, *assignment_loop.orelse)):
                    value = _with_owned_markers(value, frozenset({_owned_ordered_group_marker(owner, group)}))
        return super()._flow_write_target(target, value, scope, state, active_functions=active_functions)
    def _flow_loop(self, body: tuple[ast.stmt, ...] | list[ast.stmt], orelse: tuple[ast.stmt, ...] | list[ast.stmt], scope: qualified._Scope, entry: qualified._FlowState, *, target: ast.expr | None = None, iterable: qualified.ResolvedValue | None = None, condition: ast.expr | None = None, active_functions: frozenset[str]) -> qualified._FlowState:
        nonempty = iterable is not None and _OWNED_NONEMPTY_LOOP_MARKER in _owned_markers(iterable, self.owned_marker_vocabulary)
        loop = self.owned_statement_stack[-1] if self.owned_statement_stack else None; range_loop = isinstance(loop, ast.For) and isinstance(loop.iter, ast.Call) and isinstance(loop.iter.func, ast.Name) and loop.iter.func.id == "range"; semantic_markers = set() if iterable is None or not isinstance(loop, (ast.AsyncFor, ast.For)) or not (range_loop or isinstance(loop.target, ast.Name)) else {marker for marker in _owned_markers(iterable, self.owned_marker_vocabulary) if marker in {_owned_index_marker(symbol) for symbol, _count in OWNED_OPERATION_MANIFEST.index_counts}}; own_bindings = {f"{marker}.binding_{cast(ast.For, loop).lineno}_{cast(ast.For, loop).col_offset}" for marker in semantic_markers} if range_loop else set(); self.owned_marker_vocabulary |= own_bindings; index_markers = semantic_markers | own_bindings
        if iterable is not None: iterable = _replace_owned_markers(iterable, {_OWNED_NONEMPTY_LOOP_MARKER}, set())
        self.owned_loop_entries.append((id(entry), nonempty))
        try:
            result = super()._flow_loop(body, orelse, scope, entry, target=target, iterable=iterable, condition=condition, active_functions=active_functions)
            if index_markers: result = qualified._FlowState(tuple((name, _strip_owned_markers(value, index_markers)) for name, value in result.bindings), _strip_owned_store(result.store, index_markers)); self.flow_function_defaults = {function_id: {name: _strip_owned_markers(value, index_markers) for name, value in defaults.items()} for function_id, defaults in self.flow_function_defaults.items()}
            return result
        finally:
            self.owned_loop_entries.pop()
    def _flow_statement(self, node: ast.stmt, scope: qualified._Scope, state: qualified._FlowState, *, active_functions: frozenset[str]) -> qualified._FlowState:
        if not self._owned_context(active_functions): return super()._flow_statement(node, scope, state, active_functions=active_functions)
        self.owned_statement_stack.append(node)
        is_try = isinstance(node, (ast.Try, ast.TryStar))
        if is_try: self.owned_try_contexts.append((id(node), id(state), None))
        try:
            result = super()._flow_statement(node, scope, state, active_functions=active_functions); return self._flow_consume_deferred(self._owned_recorded_value(node.value), result) if isinstance(node, ast.Assign) and any(isinstance(target, (ast.List, ast.Starred, ast.Tuple)) for target in node.targets) else result
        finally:
            if is_try: self.owned_try_contexts.pop()
            self.owned_statement_stack.pop()
    def _flow_consume_deferred(self, value: qualified.ResolvedValue, state: qualified._FlowState) -> qualified._FlowState:
        result = super()._flow_consume_deferred(value, state); names = sorted(origin.removeprefix(_OWNED_DEFERRED_WRITE_PREFIX) for origin in value.deferred_origins if origin.startswith(_OWNED_DEFERRED_WRITE_PREFIX))
        for name in names:
            if (current := qualified._flow_binding_get(result.bindings, name)) is not None: result = self._flow_bind(result, name, _replace_owned_markers(current, set(self.owned_marker_vocabulary), {_OWNED_UNRESOLVED_MARKER}))
        return result
    def _flow_eval_expression_inner(self, node: ast.AST, scope: qualified._Scope, state: qualified._FlowState, *, apply_effects: bool, active_functions: frozenset[str] = frozenset()) -> tuple[qualified.ResolvedValue, qualified._FlowState]:
        owned_context = self._owned_context(active_functions)
        p3_context = self._p3_context(active_functions)
        parent = self.parents.get(id(node))
        index_name = isinstance(node, ast.Name) and isinstance(parent, ast.Subscript) and parent.slice is node
        append_payload = isinstance(parent, ast.Tuple) and len(parent.elts) == 2 and parent.elts[1] is node and isinstance(grandparent := self.parents.get(id(parent)), ast.Tuple) and len(grandparent.elts) == 2 and isinstance(grandparent.elts[0], ast.Starred) and grandparent.elts[1] is parent
        loop_iter = isinstance(parent, (ast.AsyncFor, ast.For)) and parent.iter is node
        if owned_context and (index_name or append_payload or loop_iter or isinstance(node, (ast.Subscript, ast.Call, ast.Compare, ast.Tuple, ast.List, ast.Set, ast.Dict, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))): self.flow_snapshot_node_ids.add(id(node))
        if owned_context and isinstance(node, (ast.Call, ast.Compare, ast.Tuple)): self.owned_expression_nodes[id(node)] = node
        value, result_state = super()._flow_eval_expression_inner(node, scope, state, apply_effects=apply_effects, active_functions=active_functions)
        if not owned_context: return value, result_state
        if isinstance(node, ast.Call):
            for argument in (*node.args, *(keyword.value for keyword in node.keywords)): result_state = self._flow_consume_deferred(self._owned_recorded_value(argument.value if isinstance(argument, ast.Starred) else argument), result_state)
        if isinstance(node, ast.GeneratorExp) and (writes := frozenset(candidate.target.id for candidate in ast.walk(node) if isinstance(candidate, ast.NamedExpr) and isinstance(candidate.target, ast.Name))): value = value._replace(deferred_origins=value.deferred_origins | frozenset(_OWNED_DEFERRED_WRITE_PREFIX + name for name in writes))
        if isinstance(node, ast.Compare): _ = [result_state := self._flow_consume_deferred(self._owned_recorded_value(comparator), result_state) for operation, comparator in zip(node.ops, node.comparators, strict=True) if isinstance(operation, (ast.In, ast.NotIn))]
        added: set[str] = set()
        removed: set[str] = set()
        call_targets = self._owned_recorded_value(node.func).direct_origins if isinstance(node, ast.Call) else frozenset()
        if isinstance(node, ast.Call) and p3_context:
            if (history_marker := self._p3_history_result_marker(node, call_targets, scope)) is not None:
                value = _at_owned_producer_boundary(value, frozenset({history_marker}))
            elif self._p3_predicate_call_is_exact(node, call_targets, scope):
                value = _at_owned_producer_boundary(value, frozenset({_P3_PREDICATE_RESULT_MARKER}))
            elif scope.path == (
                "_predicate_3o_5_1",
            ) and self._p3_selector_failure_chain_is_exact(node, call_targets):
                direct_markers = self._p3_direct_control_markers(node)
                result_markers = frozenset(
                    marker
                    for marker, decision in (
                        (_P3_B_RESULT_MARKER, _P3_B_DECISION_MARKER),
                        (_P3_H_RESULT_MARKER, _P3_H_DECISION_MARKER),
                    )
                    if decision in direct_markers
                )
                if result_markers:
                    value = _at_owned_producer_boundary(
                        value, result_markers | frozenset({_P3_SELECTOR_FAILURE_MARKER})
                    )
            elif self._p3_outcome_call_is_exact(node, call_targets):
                value = _at_owned_producer_boundary(value, frozenset({_P3_OUTCOME_MARKER}))
        alternatives = (node.body, node.orelse) if isinstance(node, ast.IfExp) else tuple(node.values) if isinstance(node, ast.BoolOp) else ()
        if alternatives:
            alternative_markers = tuple(_owned_markers(self._owned_recorded_value(alternative), self.owned_marker_vocabulary) for alternative in alternatives)
            if len(set(alternative_markers)) > 1: added.add(_OWNED_UNRESOLVED_MARKER)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            for slot, edge in self.owned_edges:
                if scope.path == (edge.owner,) and node.id == edge.carrier.root_parameter and scope.kinds.get(node.id) == {"argument"}: added.add(_owned_carrier_marker(slot, 0))
            for producer in OWNED_OPERATION_MANIFEST.producers:
                for argument_index, producer_argument in enumerate(producer.arguments):
                    if producer_argument.kind == "expression" and scope.path == (producer.owner,) and node.id == producer_argument.value and scope.kinds.get(node.id) == {"argument"}: added.add(_owned_argument_marker(producer.key, argument_index, 0))
        parent_value = qualified.ResolvedValue()
        if isinstance(node, (ast.Attribute, ast.Subscript)): parent_value = self._owned_recorded_value(node.value)
        parent_markers = _owned_markers(parent_value, self.owned_marker_vocabulary)
        if parent_markers:
            added.update({marker for marker in parent_markers if ".binding_" in marker} | (set(self._owned_index_binding_markers(node.slice)) if isinstance(node, ast.Subscript) else set()))
            if _OWNED_UNRESOLVED_MARKER in parent_markers: added.add(_OWNED_UNRESOLVED_MARKER)
            for slot, edge in self.owned_edges:
                for position in range(len(edge.carrier.path) + 1):
                    marker = _owned_carrier_marker(slot, position)
                    if marker in parent_markers:
                        removed.add(marker)
                        if position < len(edge.carrier.path) and self._owned_path_step_matches(node, edge.carrier.path[position]):
                            added.add(_owned_carrier_marker(slot, position + 1))
            for producer in OWNED_OPERATION_MANIFEST.producers:
                for argument_index, producer_argument in enumerate(producer.arguments):
                    for position in range(len(producer_argument.path) + 1):
                        marker = _owned_argument_marker(producer.key, argument_index, position)
                        if marker in parent_markers:
                            removed.add(marker)
                            if position < len(producer_argument.path) and self._owned_path_step_matches(node, producer_argument.path[position]): added.add(_owned_argument_marker(producer.key, argument_index, position + 1))
                for position in range(len(producer.result_path) + 1):
                    marker = _owned_producer_marker(producer.key, position if position < len(producer.result_path) else None)
                    if marker in parent_markers:
                        removed.add(marker)
                        if position < len(producer.result_path) and self._owned_path_step_matches(node, producer.result_path[position]):
                            next_position = position + 1
                            added.add(_owned_producer_marker(producer.key, next_position if next_position < len(producer.result_path) else None))
                        elif position == len(producer.result_path):
                            for slot, edge in self.owned_edges:
                                if edge.producer == producer.key and edge.comparison.producer_path and self._owned_path_step_matches(node, edge.comparison.producer_path[0]): added.add(_owned_comparison_marker(slot, 1))
            for slot, edge in self.owned_edges:
                for position in range(1, len(edge.comparison.producer_path) + 1):
                    marker = _owned_comparison_marker(slot, position)
                    if marker in parent_markers:
                        removed.add(marker)
                        if position < len(edge.comparison.producer_path) and self._owned_path_step_matches(node, edge.comparison.producer_path[position]): added.add(_owned_comparison_marker(slot, position + 1))
            for owner, group, _ranked in self.owned_groups:
                removed.update({_owned_group_marker(owner, group), _owned_group_validation_marker(owner, group)} & parent_markers)
        matched_producers: tuple[OwnedProducer, ...] = ()
        if isinstance(node, ast.Call) and scope.path:
            matched_producers = tuple(producer for producer in OWNED_OPERATION_MANIFEST.producers if f"{CANONICAL_MODULE}.{producer.owner}" in active_functions and self._owned_call_matches(node, producer))
            if matched_producers:
                producer_markers = frozenset({_owned_producer_marker(producer.key, 0 if producer.result_path else None) for producer in matched_producers} | {marker for producer in matched_producers for argument, requirement in zip(node.args, producer.arguments, strict=True) for marker in (self._owned_index_binding_markers(argument) if requirement.kind == "expression" else frozenset(item for item in _owned_markers(self._owned_recorded_value(argument), self.owned_marker_vocabulary) if ".binding_" in item))}); value = _at_owned_producer_boundary(value, producer_markers)
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1 and isinstance(node.ops[0], ast.NotEq):
            left_markers = _owned_markers(self._owned_recorded_value(node.left), self.owned_marker_vocabulary)
            right_markers = _owned_markers(self._owned_recorded_value(node.comparators[0]), self.owned_marker_vocabulary)
            for slot, edge in self.owned_edges:
                producer_marker = _owned_comparison_marker(slot, len(edge.comparison.producer_path)) if edge.comparison.producer_path else _owned_producer_marker(edge.producer)
                carrier_marker = _owned_carrier_marker(slot, len(edge.carrier.path))
                if carrier_marker in left_markers and producer_marker in right_markers and _OWNED_UNRESOLVED_MARKER not in left_markers | right_markers: added.add(_owned_control_marker(slot))
        if (
            isinstance(node, ast.Compare)
            and p3_context
            and len(node.ops) == len(node.comparators) == 1
            and isinstance(node.ops[0], ast.IsNot)
            and isinstance(node.comparators[0], ast.Constant)
            and node.comparators[0].value is None
        ):
            left_markers = _owned_markers(
                self._owned_recorded_value(node.left), self.owned_marker_vocabulary
            )
            if _OWNED_UNRESOLVED_MARKER not in left_markers:
                for result_marker, decision_marker in (
                    (_P3_B_RESULT_MARKER, _P3_B_DECISION_MARKER),
                    (_P3_H_RESULT_MARKER, _P3_H_DECISION_MARKER),
                    (_P3_PREDICATE_RESULT_MARKER, _P3_PREDICATE_DECISION_MARKER),
                ):
                    if result_marker in left_markers:
                        added.add(decision_marker)
        value = _replace_owned_markers(value, removed, added)
        if isinstance(node, ast.Call) and call_targets == frozenset({f"{CANONICAL_MODULE}._source_evidence_at"}): value = _with_owned_markers(value, frozenset(marker for argument in node.args for marker in (self._owned_index_binding_markers(argument) | frozenset(item for item in _owned_markers(self._owned_recorded_value(argument), self.owned_marker_vocabulary) if ".binding_" in item))))
        if isinstance(node, ast.Call) and not self.owned_validation_targets.isdisjoint(call_targets): value = _with_owned_markers_deep(value, frozenset(marker for argument in node.args for marker in (self._owned_index_binding_markers(argument) | frozenset(item for item in _owned_markers(self._owned_recorded_value(argument), self.owned_marker_vocabulary) if ".binding_" in item))))
        if isinstance(node, ast.Call): call_markers = _owned_markers(self._owned_recorded_value(node.args[0]), self.owned_marker_vocabulary) if node.args else frozenset(); value = _with_owned_markers(value, frozenset(f"{_OWNED_VALIDATION_PREFIX}{slot}.stage_{stage}" for target in call_targets for slot, stage, path_position, prior in self.owned_validation_stages.get(target, ()) if len(call_targets) == 1 and node.args and not node.keywords and not isinstance(node.args[0], ast.Starred) and len(node.args) == (1 if target.rsplit(".", 1)[-1] in {"_require_exact_source_observation_object", "_source_key_fields"} else 2) and all(_p2_safe_string_expression(argument) for argument in node.args[1:]) and {_owned_carrier_marker(slot, path_position), *prior} <= call_markers and _OWNED_UNRESOLVED_MARKER not in call_markers))
        control_markers = frozenset(marker for marker in _owned_markers(value, self.owned_marker_vocabulary) if ".control." in marker)
        exact_helper_chain = bool(call_targets) and all(target in self.local_functions for target in call_targets) and all(len(body := tuple(statement for statement in function.body if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str)))) == 1 and isinstance(body[0], ast.Return) and isinstance(body[0].value, (ast.Call, ast.Compare)) for target in call_targets for function, _child in self.local_functions.get(target, ()))
        value_markers = _owned_markers(value, self.owned_marker_vocabulary)
        p3_safe_call = p3_context and bool(
            value_markers
            & {
                _P3_B_RESULT_MARKER,
                _P3_H_RESULT_MARKER,
                _P3_SELECTOR_FAILURE_MARKER,
                _P3_PREDICATE_RESULT_MARKER,
                _P3_OUTCOME_MARKER,
            }
        )
        safe_call = p3_safe_call or bool(matched_producers) or call_targets == frozenset({f"{CANONICAL_MODULE}._source_evidence_at"}) or len(call_targets) == 1 and (not self.owned_validation_targets.isdisjoint(call_targets) or any(".producer." in marker for marker in value_markers) and exact_helper_chain or bool(control_markers) and exact_helper_chain or all(target in self.local_functions for target in call_targets) and not any(".index." in marker for marker in value_markers))
        if isinstance(node, ast.Call) and control_markers and not exact_helper_chain: value = _with_owned_markers(value, frozenset({_OWNED_UNRESOLVED_MARKER}))
        inside_producer = scope.path and f"{CANONICAL_MODULE}.{scope.path[0]}" in {producer.qualified_target for producer in OWNED_OPERATION_MANIFEST.producers}
        certified_control = any(marker.startswith(f"{_OWNED_FLOW_PREFIX}.control.") for marker in added) or bool(
            {
                _P3_B_DECISION_MARKER,
                _P3_H_DECISION_MARKER,
                _P3_PREDICATE_DECISION_MARKER,
            }
            & added
        )
        transformed = not inside_producer and (isinstance(node, (ast.Await, ast.BinOp, ast.BoolOp, ast.FormattedValue, ast.IfExp, ast.JoinedStr, ast.Lambda, ast.UnaryOp, ast.Yield, ast.YieldFrom)) or isinstance(node, ast.Compare) and not certified_control or isinstance(node, ast.Call) and not safe_call)
        if (isinstance(node, (ast.Tuple, ast.List, ast.Set, ast.Dict, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)) or transformed) and _owned_markers(value, self.owned_marker_vocabulary):
            value = _replace_owned_markers(value, {_owned_ordered_group_marker(owner, group) for owner, group, _ranked in self.owned_groups}, {_OWNED_UNRESOLVED_MARKER})
        loop = self.parents.get(id(node))
        if isinstance(loop, (ast.For, ast.AsyncFor)) and loop.iter is node:
            value = self._owned_complete_iterable(self._materialize_flow_value(value, result_state.store), loop.body, node)
            range_call = isinstance(node, ast.Call) and self._owned_recorded_value(node.func).direct_origins == frozenset({"builtins.range"}) and len(node.args) == 1 and not node.keywords and isinstance(node.args[0], ast.Constant) and type(node.args[0].value) is int and node.args[0].value > 0
            if range_call and isinstance(loop.target, ast.Name):
                value = _with_owned_markers(value, frozenset(_owned_index_marker(symbol) for symbol, count in OWNED_OPERATION_MANIFEST.index_counts if cast(ast.Constant, cast(ast.Call, node).args[0]).value == count))
                value_markers = _owned_markers(value, self.owned_marker_vocabulary)
                value = _with_owned_markers(value, frozenset(_owned_argument_marker(producer.key, index, 0) for producer in OWNED_OPERATION_MANIFEST.producers for index, producer_argument in enumerate(producer.arguments) if producer_argument.kind == "expression" and not producer_argument.path and scope.path == (producer.owner,) and _owned_index_marker(producer_argument.value) in value_markers))
            group_nonempty = any(_owned_ordered_group_marker(owner, group) in _owned_markers(value, self.owned_marker_vocabulary) for owner, group, ranked in self.owned_groups if ranked)
            if range_call or bool(value.sequence_elements) or group_nonempty: value = _with_owned_markers(value, frozenset({_OWNED_NONEMPTY_LOOP_MARKER}))
        return value, result_state
_OwnedFlowValue = NamedTuple("_OwnedFlowValue", [("markers", frozenset[str]), ("unresolved", bool), ("overflow", bool), ("deferred", bool), ("uncertain_location", bool)])
_SourceAnalysis = NamedTuple("_SourceAnalysis", [("tree", ast.Module), ("functions", Mapping[str, ast.FunctionDef]), ("module_bindings", Mapping[str, qualified.ResolvedValue]), ("function_definition_counts", Mapping[str, int]), ("function_binding_event_counts", Mapping[str, int]), ("analysis", qualified.QualifiedSymbolAnalysis), ("parents", Mapping[int, ast.AST]), ("scope_paths", Mapping[int, tuple[str, ...]]), ("owned_values", Mapping[int, _OwnedFlowValue]), ("owned_expressions", tuple[ast.expr, ...]), ("owned_controls", Mapping[str, tuple[ast.If, ...]]), ("owned_benign_mutation_lines", frozenset[tuple[int, str]]), ("execution_changed_function_roots", frozenset[str])])
# fmt: off
type ExpressionKind = Literal["literal", "name", "parameter", "ordered-parameter-dict", "scientific-projection-mapping"]
type ResultKind = Literal["bound-once", "recomputed-value", "validate-carried"]
type TargetBindingKind = Literal["canonical-local", "private-import", "phase-private-import"]
type ExpressionValue = str | int | tuple[str, ...] | tuple[tuple[str, int], ...]

_SUPPORTED_EXPRESSION_KINDS: Final = ("literal", "name", "parameter", "ordered-parameter-dict", "scientific-projection-mapping")
_SUPPORTED_RESULT_KINDS: Final = ("bound-once", "recomputed-value", "validate-carried")
_SUPPORTED_TARGET_BINDINGS: Final = ("canonical-local", "private-import", "phase-private-import")

ParameterConstraint = NamedTuple("ParameterConstraint", [("name", str), ("annotation", str | None)])
ExpressionConstraint = NamedTuple("ExpressionConstraint", [("kind", ExpressionKind), ("value", ExpressionValue)])
KeywordConstraint = NamedTuple("KeywordConstraint", [("name", str), ("expression", ExpressionConstraint)])
CallShape = NamedTuple("CallShape", [("parameters", tuple[ParameterConstraint, ...]), ("positional", tuple[ExpressionConstraint, ...]), ("keywords", tuple[KeywordConstraint, ...]), ("result_kind", ResultKind), ("compared_parameter", int | str | None), ("target_binding", TargetBindingKind), ("validation_only", bool)])


class RequiredCall(NamedTuple):
    phase: CalibrationEvidencePhase
    name: str
    owner: str
    qualified_target: str
    call_shape: CallShape

REQUIRED_CALLS: Final = (
    RequiredCall("P2", "oracle_key_id", "_oracle_key_id", _RUNTIME_ID_TARGET, CallShape((ParameterConstraint("key_fields", None),), (ExpressionConstraint("literal", "oracle-key"), ExpressionConstraint("literal", "oracle_key_id/v1"), ExpressionConstraint("ordered-parameter-dict", (("key_fields", 0),))), (), "recomputed-value", None, "private-import", True)),
    RequiredCall("P2", "outcome_digest", "_outcome_digest", _PROTOCOL_HASH_TARGET, CallShape((ParameterConstraint("oracle_key_id", None), ParameterConstraint("revealed_observation", None)), (ExpressionConstraint("literal", "revealed_outcome/v1"), ExpressionConstraint("ordered-parameter-dict", (("oracle_key_id", 0), ("revealed_observation", 1)))), (), "recomputed-value", None, "private-import", True)),
    RequiredCall("P2", "source_observation_identity", "_source_observation_matches", _SOURCE_OBSERVATION_ID_TARGET, CallShape((ParameterConstraint("projection", "CalibrationSourceObservationProjection"), ParameterConstraint("carried_source_observation_identity", None)), (ExpressionConstraint("parameter", 0),), (), "validate-carried", 1, "canonical-local", True)),
    RequiredCall("P3", "calibration_selector_replay", "_predicate_3o_5_1", _REPLAY_TARGET, CallShape((), (), (
        KeywordConstraint("run_id", ExpressionConstraint("name", "replay_run_id")),
        KeywordConstraint("world_id", ExpressionConstraint("name", "world_id")),
        KeywordConstraint("seed", ExpressionConstraint("name", "seed")),
        KeywordConstraint("comparison_group_id", ExpressionConstraint("name", "comparison_group_id")),
        KeywordConstraint("group_index", ExpressionConstraint("name", "group_index")),
        KeywordConstraint("expected_observations", ExpressionConstraint("name", "expected_observations")),
        KeywordConstraint("expected_effects", ExpressionConstraint("name", "expected_effects")),
        KeywordConstraint("physical_cost", ExpressionConstraint("name", "physical_cost")),
        KeywordConstraint("recorded_observations", ExpressionConstraint("name", "recorded_observations")),
        KeywordConstraint("recorded_effects", ExpressionConstraint("name", "recorded_effects")),
        KeywordConstraint("source_sequence_cutoff", ExpressionConstraint("name", "_CALIBRATION_SOURCE_SEQUENCE_CUTOFF")),
    ), "bound-once", "actual_helper_result", "phase-private-import", True)),
    RequiredCall("P3", "selection_identity", "_predicate_3o_5_1", _PROTOCOL_HASH_TARGET, CallShape((), (
        ExpressionConstraint("literal", _SELECTION_IDENTITY_DOMAIN),
        ExpressionConstraint("scientific-projection-mapping", PROJECTION_FIELDS["ScientificCalibrationSelectionProjection"]),
    ), (), "bound-once", "expected_selector_result_identity", "private-import", True)),
)


def _required_call_metadata_is_valid(requirement: object) -> bool:
    """Validate one exact, closed, immutable required-call metadata graph."""

    def parameter_is_valid(value: object) -> bool:
        if type(value) is not ParameterConstraint or len(value) != 2:
            return False
        return bool(
            type(value.name) is str
            and value.name
            and value.name.isidentifier()
            and (
                value.annotation is None
                or type(value.annotation) is str
                and bool(value.annotation)
                and value.annotation.isidentifier()
            )
        )

    def expression_is_valid(
        value: object, parameter_names: tuple[str, ...]
    ) -> bool:
        if type(value) is not ExpressionConstraint or len(value) != 2:
            return False
        if type(value.kind) is not str or value.kind not in _SUPPORTED_EXPRESSION_KINDS:
            return False
        if value.kind == "literal":
            return type(value.value) is str or type(value.value) is int
        if value.kind == "name":
            return bool(type(value.value) is str and value.value.isidentifier())
        if value.kind == "scientific-projection-mapping":
            return bool(
                type(value.value) is tuple
                and value.value == PROJECTION_FIELDS["ScientificCalibrationSelectionProjection"]
                and all(type(field) is str for field in value.value)
            )
        if value.kind == "parameter":
            return bool(
                type(value.value) is int and 0 <= value.value < len(parameter_names)
            )
        if type(value.value) is not tuple:
            return False
        entry_names: list[str] = []
        entry_indexes: list[int] = []
        for entry in value.value:
            if (
                type(entry) is not tuple
                or len(entry) != 2
                or type(entry[0]) is not str
                or not entry[0]
                or type(entry[1]) is not int
                or not 0 <= entry[1] < len(parameter_names)
                or entry[0] != parameter_names[entry[1]]
            ):
                return False
            entry_names.append(entry[0])
            entry_indexes.append(entry[1])
        return bool(
            len(entry_names) == len(set(entry_names))
            and len(entry_indexes) == len(set(entry_indexes))
        )

    def keyword_is_valid(value: object, parameter_names: tuple[str, ...]) -> bool:
        if type(value) is not KeywordConstraint or len(value) != 2:
            return False
        return bool(
            type(value.name) is str
            and value.name
            and value.name.isidentifier()
            and expression_is_valid(value.expression, parameter_names)
        )

    def referenced_parameters(value: ExpressionConstraint) -> tuple[int, ...]:
        if value.kind == "parameter":
            return (cast(int, value.value),)
        if value.kind == "ordered-parameter-dict":
            entries = cast(tuple[tuple[str, int], ...], value.value)
            return tuple(entry[1] for entry in entries)
        return ()

    if type(requirement) is not RequiredCall or len(requirement) != 5:
        return False
    if (
        type(requirement.phase) is not str
        or requirement.phase not in _PHASE_ORDER
        or type(requirement.name) is not str
        or not requirement.name
        or not requirement.name.isidentifier()
        or type(requirement.owner) is not str
        or not requirement.owner
        or not requirement.owner.isidentifier()
        or type(requirement.qualified_target) is not str
        or not requirement.qualified_target
        or type(requirement.call_shape) is not CallShape
        or len(requirement.call_shape) != 7
    ):
        return False

    target_module, separator, target_name = requirement.qualified_target.rpartition(".")
    if (
        not separator
        or not target_name.isidentifier()
        or not target_module
        or any(not part.isidentifier() for part in target_module.split("."))
    ):
        return False

    shape = requirement.call_shape
    parameters = shape.parameters
    positional = shape.positional
    keywords = shape.keywords
    result_kind = shape.result_kind
    compared_parameter = shape.compared_parameter
    target_binding = shape.target_binding
    validation_only = shape.validation_only
    if (
        type(parameters) is not tuple
        or type(positional) is not tuple
        or type(keywords) is not tuple
        or not (positional or keywords)
        or type(result_kind) is not str
        or result_kind not in _SUPPORTED_RESULT_KINDS
        or compared_parameter is not None
        and type(compared_parameter) not in {int, str}
        or type(target_binding) is not str
        or target_binding not in _SUPPORTED_TARGET_BINDINGS
        or type(validation_only) is not bool
    ):
        return False
    if not all(parameter_is_valid(parameter) for parameter in parameters):
        return False
    parameter_names = tuple(parameter.name for parameter in parameters)
    if len(parameter_names) != len(set(parameter_names)):
        return False
    if not all(
        expression_is_valid(expression, parameter_names) for expression in positional
    ) or not all(
        keyword_is_valid(keyword, parameter_names) for keyword in keywords
    ):
        return False
    keyword_names = tuple(keyword.name for keyword in keywords)
    if len(keyword_names) != len(set(keyword_names)):
        return False

    argument_references = tuple(
        index
        for expression in (
            *positional,
            *(keyword.expression for keyword in keywords),
        )
        for index in referenced_parameters(expression)
    )
    if len(argument_references) != len(set(argument_references)):
        return False
    if result_kind == "recomputed-value":
        if compared_parameter is not None:
            return False
    elif result_kind == "bound-once":
        if type(compared_parameter) is not str or not compared_parameter.isidentifier():
            return False
    elif (
        type(compared_parameter) is not int
        or not 0 <= compared_parameter < len(parameters)
    ):
        return False

    canonical_local = target_module == CANONICAL_MODULE
    return bool(
        (target_binding == "canonical-local") == canonical_local
        and (
            target_binding != "phase-private-import"
            or requirement.phase in {"P3", "P4"}
        )
    )


def _valid_required_call_entries(value: object) -> tuple[RequiredCall, ...]:
    return tuple(item for item in value if _required_call_metadata_is_valid(item)) if type(value) is tuple else ()


ALLOWED_IMPORTS: Final = {"__future__": _names("annotations"), "dataclasses": _names("dataclass"), "hashlib": _names("sha256"), "typing": _names("Final Literal NamedTuple NoReturn TYPE_CHECKING"), "math": _names("isfinite"), "statistics": _names("mean stdev"), "unicodedata": _names("normalize"), "research_decision_engine.belief_models": _names("SIGMA_FLOOR MatchedEffectObservation"), _PROTOCOL: _names("PROTOCOL_VERSION canonical_json_bytes f64 protocol_hash runtime_id"), _EXECUTION: _names("ExecutorAttestationProjection ReturnedResultsProjection decode_executor_attestation_projection execution_instance_identity execution_id submitted_jobs_sha256 execution_start_id worker_identity returned_result_id result_batch_id execution_completion_id returned_results_sha256 worker_result_order_sha256 executor_attestation_id validate_stage2d2_execution_foundations validate_stage2d2_returned_results validate_stage2d2_result_batch_completion validate_stage2d2_result_aggregates validate_stage2e_executor_attestation"), _RETURNED: _names("ProvenanceValueProjection ReturnedRunProjection RunCalibrationEstimateProjection RunCalibrationProjection RunMatchedEffectProjection RunObservationAuthorizationProjection RunProvenanceProjection RunRevealedObservationProjection decode_run_matched_effect_projection reconstruct_matched_effect validate_returned_run_projection_shape"), _REPLAY: _names("raw_effect_sha256 replay_calibration_history_selection"), _HISTORY: _names("CALIBRATION_ELIGIBILITY_BASIS CALIBRATION_SELECTION_VERSION CALIBRATION_SIGMA_DDOF CALIBRATION_SOURCE_SEQUENCE_CUTOFF CalibrationHistorySelection RunProvenanceError expected_calibration_effect"), _ORACLE: _names("CALIBRATION_NAMESPACE ORACLE_VERSION RevealedObservation calibration_key transform_key _parse_calibration_candidate"), _WORLDS: _names("GROUP_IDS WORLDS_BY_ID BenchmarkWorld HiddenWorldParameters PublicWorldDefinition candidate_costs hidden_arm_mean hidden_observation_sigma")}
_P3_PRIVATE_MODULE_IMPORTS: Final = {"hashlib": "_hashlib", "statistics": "_statistics", "unicodedata": "_unicodedata"}
PURE_HELPER_CALLS: Final = frozenset({"builtins.abs", "builtins.enumerate", "builtins.float", "builtins.len", "builtins.list", "builtins.max", "builtins.min", "builtins.ord", "builtins.range", "builtins.round", "builtins.sorted", "builtins.tuple", "dataclasses.dataclass", "hashlib.sha256", "math.isfinite", "statistics.mean", "statistics.stdev", "unicodedata.normalize", *(f"{module}.{name}" for module, names in ALLOWED_IMPORTS.items() for name in names if name[0].islower() or name.startswith("_"))})
FORBIDDEN_IMPORT_ROOTS: Final = _names("asyncio git http importlib multiprocessing os pathlib pickle shutil socket sqlite3 subprocess tempfile urllib")
FORBIDDEN_IMPORT_MODULES: Final = _names("research_decision_engine.storage research_decision_engine.benchmarks.broader_artifacts research_decision_engine.benchmarks.broader_assembly research_decision_engine.benchmarks.broader_lifecycle research_decision_engine.benchmarks.broader_lifecycle_io research_decision_engine.benchmarks.broader_lifecycle_records research_decision_engine.benchmarks.broader_validation research_decision_engine.benchmarks.broader_validation_evidence")
FORBIDDEN_CALL_TAILS: Final = _names("Popen authorize_observation connect create_subprocess_exec create_subprocess_shell enumerate_registry exec eval finalize getattr getenv globals hasattr issue_authority locals observe_selected open persist read_bytes read_text register reobserve reobserve_authorized_observation run run_arm run_worker select_calibration_history system vars write write_bytes write_evidence write_text")
FORBIDDEN_BINDINGS: Final = _names("CalibrationEvidenceBundleProjection CalibrationBindingProjection CalibrationEvidenceAggregateProjection CalibrationFinalAggregateProjection ReaderReconciliationProjection EvidenceBundle EvidenceMemberInventory EvidenceWriter Reader Persistence Storage SelectorRegistry OracleAuthorityRegistry ObservationAuthority SelectedObservationInterface ValidationBindingsWriter FinalizationWriter bounded_validation_authorization full_replication_authorization stage3_workload_authorization validation_bindings_writer final_content_root final_manifest_binding full_replication")
FORBIDDEN_STRINGS: Final = _names("validation_bindings.json bounded-validation-authorization full-replication-authorization stage-3-workload-authorization")
_REGISTRY_NAMES = _names("registry selector_registry oracle_authority_registry capability_registry")
_CALLABLE_PARAMETER_NAMES = _names("callback factory identity_factory validator validator_factory validator_map validators")
_LIVE_ANNOTATIONS = _names("Callable ObservationAuthority SelectedObservationInterface ValidationRun ExecutionCapability Reader")
_LIVE_PARAMETER_NAMES = _names("authority capability executor oracle reader registry selector worker")
_DYNAMIC_FINDINGS = _names("alias-cycle dynamic-call dynamic-class dynamic-module-mutation dynamic-module-hook dynamic-namespace-reference dynamic-scope-binding dynamic-__all__ qualified-state-mutation unresolved-call-alias unresolved-mutator-reference unresolved-sensitive-provenance")
_DYNAMIC_CALL_TAILS = _names("type make_dataclass namedtuple FunctionType")
_SERIALIZATION_TAILS = _names("asdict dumps pickle repr")
_ALL_PROJECTIONS = P4_MANIFEST.projection_classes
_ALL_IDENTITIES = P4_MANIFEST.identity_functions
_ALL_IDENTITY_NAMES = frozenset(name for name, _ in P4_MANIFEST.identity_domains)
_NEW_IDENTITY_DOMAINS = frozenset(domain for name, domain in P4_MANIFEST.identity_domains if name in P4_MANIFEST.identity_functions)
_ALL_SCHEMAS = frozenset(schema for _, schema in P4_MANIFEST.schemas if schema)
_FORBIDDEN_IDENTITY_ALIASES = _names("scientific_calibration_selection_id calibration_selector_result_id final_calibration_aggregate_id calibration_binding_id")
_FORBIDDEN_IDENTITY_CALLABLES = _names("selection_identity selector_result_identity scientific_calibration_selection_id calibration_selector_identity calibration_selector_result_id final_calibration_aggregate_id calibration_binding_id")
_FUTURE_PUBLIC_VALIDATORS = _names("validate_calibration_candidate_pair_projection validate_strict_chronology_projection validate_calibration_source_observation_projection validate_scientific_calibration_selection_projection validate_calibration_selection_projection validate_stage2f_calibration_evidence reconstruct_calibration_evidence")
_STAGE2F_ATTESTATION_FIELDS = _names("calibration_candidate_pair calibration_candidate_pair_id strict_chronology strict_chronology_id source_observation source_observation_identity scientific_calibration_selection selection_identity calibration_selection calibration_selection_id oracle_key_id outcome_digest")
_BUILTIN_CLASS_NAMES = _names("ArithmeticError AssertionError AttributeError BaseException BaseExceptionGroup BlockingIOError BrokenPipeError BufferError BytesWarning ChildProcessError ConnectionAbortedError ConnectionError ConnectionRefusedError ConnectionResetError DeprecationWarning EOFError EncodingWarning EnvironmentError Exception ExceptionGroup FileExistsError FileNotFoundError FloatingPointError FutureWarning GeneratorExit IOError ImportError ImportWarning IndentationError IndexError InterruptedError IsADirectoryError KeyError KeyboardInterrupt LookupError MemoryError ModuleNotFoundError NameError NotADirectoryError NotImplementedError OSError OverflowError PendingDeprecationWarning PermissionError ProcessLookupError RecursionError ReferenceError ResourceWarning RuntimeError RuntimeWarning StopAsyncIteration StopIteration SyntaxError SyntaxWarning SystemError SystemExit TabError TimeoutError TypeError UnboundLocalError UnicodeDecodeError UnicodeEncodeError UnicodeError UnicodeTranslateError UnicodeWarning UserWarning ValueError Warning WindowsError ZeroDivisionError bool bytearray bytes classmethod complex dict enumerate filter float frozenset int list map memoryview object property range reversed set slice staticmethod str super tuple type zip")
_BUILTIN_CLASS_TARGETS = frozenset(f"builtins.{name}" for name in _BUILTIN_CLASS_NAMES)
_KNOWN_CLASS_TARGETS = _BUILTIN_CLASS_TARGETS | frozenset({"research_decision_engine.belief_models.MatchedEffectObservation", *(f"{_EXECUTION}.{name}" for name in _names("ExecutorAttestationProjection ReturnedResultsProjection")), *(f"{_RETURNED}.{name}" for name in _names("ReturnedRunProjection RunCalibrationEstimateProjection RunCalibrationProjection RunMatchedEffectProjection RunObservationAuthorizationProjection RunRevealedObservationProjection")), *(f"{_HISTORY}.{name}" for name in _names("CalibrationHistorySelection RunProvenanceError")), f"{_ORACLE}.RevealedObservation", *(f"{_WORLDS}.{name}" for name in _names("BenchmarkWorld HiddenWorldParameters PublicWorldDefinition")), *(f"{CANONICAL_MODULE}.{name}" for name in _ALL_PROJECTIONS)})
_PHASE_REQUIRED_HELPERS = {"C0": frozenset(), "P1": frozenset({f"{_REPLAY}.raw_effect_sha256"}), "P2": frozenset({f"{_REPLAY}.raw_effect_sha256"}), "P3": frozenset({f"{_REPLAY}.raw_effect_sha256", f"{_REPLAY}.replay_calibration_history_selection"}), "P4": frozenset({f"{_REPLAY}.raw_effect_sha256", f"{_REPLAY}.replay_calibration_history_selection"})}
_P1_PURE_HELPERS = frozenset({f"{_PROTOCOL}.f64", f"{_ORACLE}._parse_calibration_candidate"})
_P2_PURE_HELPERS = frozenset({f"{_PROTOCOL}.f64", f"{_ORACLE}.calibration_key", f"{_ORACLE}.transform_key", f"{_ORACLE}._parse_calibration_candidate", f"{_WORLDS}.hidden_arm_mean", f"{_WORLDS}.hidden_observation_sigma"})
_PHASE_ALLOWED_HELPERS = {"C0": _PHASE_REQUIRED_HELPERS["C0"], "P1": _PHASE_REQUIRED_HELPERS["P1"] | _P1_PURE_HELPERS, **{phase: _PHASE_REQUIRED_HELPERS[phase] | _P2_PURE_HELPERS for phase in ("P2", "P3", "P4")}}
_PHASE_REQUIRED_CALLS = {phase: _PHASE_REQUIRED_HELPERS[phase] | frozenset(item.qualified_target for item in _valid_required_call_entries(REQUIRED_CALLS) if _PHASE_ORDER.index(item.phase) <= _PHASE_ORDER.index(phase)) for phase in _PHASE_ORDER}
_PHASE_ALLOWED_CALLS = {phase: _PHASE_ALLOWED_HELPERS[phase] | _PHASE_REQUIRED_CALLS[phase] | ({_PROTOCOL_HASH_TARGET} if phase != "C0" else set()) for phase in _PHASE_ORDER}
_P1_PROJECTION_SHAPES = {
    "CalibrationCandidatePairProjection": (
        ("adam_candidate_id", "str"),
        ("comparison_group_id", "str"),
        ("replication_id", "str"),
        ("schema_version", 'Literal["broader-replication-calibration-candidate-pair/v1"]'),
        ("sgd_candidate_id", "str"),
        ("world_id", "str"),
    ),
    "StrictChronologyProjection": (
        ("current_effect_excluded", "Literal[True]"),
        ("current_observation_excluded", "Literal[True]"),
        ("effect_available_sequences", "tuple[int, int, int, int, int]"),
        ("future_history_excluded", "Literal[True]"),
        ("schema_version", 'Literal["broader-replication-calibration-chronology/v1"]'),
        ("source_sequence_cutoff", "Literal[1]"),
    ),
    "CalibrationSourceObservationProjection": (("candidate_id", "str"), ("comparison_group_id", "str"), ("digest", "str"), ("intervention_arm", 'Literal["adam", "sgd"]'), ("key_fields", "tuple[str, ...]"), ("namespace", 'Literal["rde.broader.calibration-outcome/v1"]'), ("oracle_key_id", "str"), ("outcome_digest", "str"), ("replication_id", "str"), ("revealed_observation", "str"), ("schema_version", 'Literal["broader-replication-calibration-source-observation/v1"]'), ("seed", "int"), ("serialized_key_hex", "str"), ("u", "str"), ("world_id", "str"), ("z", "str")),
    "ScientificCalibrationSelectionProjection": (
        ("comparison_group_id", "str"),
        ("ddof", "int"),
        ("effect_values", "tuple[str, ...]"),
        ("eligibility_basis", "str"),
        ("estimated_sigma", "str"),
        ("namespace", "str"),
        ("sample_count", "int"),
        ("sample_mean", "str"),
        ("sample_standard_deviation", "str"),
        ("seed", "int"),
        ("sigma_floor", "str"),
        ("source_candidate_pairs", "tuple[tuple[str, str], ...]"),
        ("source_effect_ids", "tuple[str, ...]"),
        ("source_effect_payload_sha256", "tuple[str, ...]"),
        ("source_observation_identities", "tuple[tuple[str, str], ...]"),
        ("source_oracle_key_ids", "tuple[str, ...]"),
        ("source_replication_ids", "tuple[str, ...]"),
        ("source_sequence_cutoff", "int"),
        ("study_id", "str"),
        ("target_comparison_group_id", "str"),
        ("world_id", "str"),
    ),
}
_P1_IDENTITY_PREIMAGES = {
    "calibration_candidate_pair_id": ("CalibrationCandidatePairProjection", "_calibration_candidate_pair_preimage"),
    "strict_chronology_id": ("StrictChronologyProjection", "_strict_chronology_preimage"),
}
_P1_PREDICATE_FAMILIES = tuple(f"_predicate_3o_1_{index}" for index in range(7))
_P1_PREDICATE_TARGETS = tuple(f"{CANONICAL_MODULE}.{name}" for name in _P1_PREDICATE_FAMILIES)
_P1_CHRONOLOGY_SCHEDULE_TARGETS = frozenset({f"{CANONICAL_MODULE}.strict_chronology_id", f"{CANONICAL_MODULE}._strict_chronology_mapping"})
_P1_LATER_SCHEDULE_LEAVES = frozenset({*(requirement.owner for requirement in REQUIRED_CALLS if requirement.phase in {"P2", "P3", "P4"}), *(item.name for item in IDENTITY_MANIFESTS if item.phase in {"P2", "P3", "P4"}), "_calibration_source_observation_mapping", "_decode_calibration_source_observation_projection", "_validate_calibration_source_observation_projection", "_validate_stage2f_p2", "_validate_stage2f_p3", "_validate_stage2f_p4", "validate_stage2f_calibration_evidence"})
_HARNESS_ALLOWED_PROJECTION_TARGETS = frozenset(
    f"{CANONICAL_MODULE}.{name}" for name in P3_MANIFEST.projection_classes
)
_HARNESS_FORBIDDEN_PRODUCTION_TARGETS = frozenset(
    f"{CANONICAL_MODULE}.{name}"
    for name in (
        "calibration_candidate_pair_id",
        "strict_chronology_id",
        "_calibration_candidate_pair_mapping",
        "_strict_chronology_mapping",
        "_decode_calibration_candidate_pair_projection",
        "_decode_strict_chronology_projection",
        "source_observation_identity",
        "_calibration_source_observation_mapping",
        "_decode_calibration_source_observation_projection",
        "_scientific_calibration_selection_mapping",
        "_decode_scientific_calibration_selection_projection",
        "_predicate_3o_5_1",
        "_validate_stage2f_p3",
    )
)
# fmt: on


# fmt: off
class Finding(NamedTuple):
    code: str
    detail: str


class _P1ScheduleEvent(NamedTuple):
    kind: str
    detail: str
    entry_index: int
    owner: str
    spelling: str
    targets: frozenset[str]
    node: ast.Call


def _top_level_function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    return next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name), None)


def _call_leaf(node: ast.Call) -> str:
    return ast.unparse(node.func).rsplit(".", 1)[-1]


def _decoded_effect_id_comparison(
    node: ast.AST,
    carried_name: str,
) -> bool:
    return bool(isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == carried_name and len(node.ops) == 1 and isinstance(node.ops[0], ast.NotEq) and len(node.comparators) == 1 and isinstance(node.comparators[0], ast.Attribute) and node.comparators[0].attr == "effect_id" and isinstance(node.comparators[0].value, ast.Name) and node.comparators[0].value.id == "decoded_projection")


_P1_EFFECT_ID_OCCURRENCES = ("effect_id", "record_effect_id", "selector_effect_id")


def _complete_decoded_effect_id_relation(node: ast.AST) -> bool:
    return bool(isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or) and len(node.values) == len(_P1_EFFECT_ID_OCCURRENCES) and all(_decoded_effect_id_comparison(comparison, carried_name) for comparison, carried_name in zip(node.values, _P1_EFFECT_ID_OCCURRENCES, strict=True)))


def _returns_effect_failure(node: ast.If) -> bool:
    return bool(len(node.body) == 1 and isinstance(node.body[0], ast.Return) and isinstance(node.body[0].value, ast.Call) and isinstance(node.body[0].value.func, ast.Name) and node.body[0].value.func.id == "_effect_failure")


def _active_p1_effect_findings(tree: ast.Module) -> set[Finding]:
    findings: set[Finding] = set()
    predicate = _top_level_function(tree, "_predicate_3o_1_5")
    if predicate is None:
        return {Finding("p1-effect-id-binding", "_predicate_3o_1_5")}

    decoded_assignments = tuple(node for node in ast.walk(predicate) if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "decoded_projection" and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "_decode_run_matched_effect_projection")
    if len(decoded_assignments) != 1:
        findings.add(Finding("p1-effect-id-binding", "strict-decode"))
        decoded_line = -1
    else:
        decoded_line = decoded_assignments[0].lineno
        decoder_call = cast(ast.Call, decoded_assignments[0].value)
        mapping_calls = tuple(call for argument in decoder_call.args for call in ast.walk(argument) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "_effect_projection_mapping" and len(call.args) == 1 and isinstance(call.args[0], ast.Name) and call.args[0].id == "carried_projection")
        if len(mapping_calls) != 1:
            findings.add(Finding("p1-effect-id-binding", "complete-projection-decode"))

    binding_ifs = tuple(node for node in ast.walk(predicate) if isinstance(node, ast.If) and any(_decoded_effect_id_comparison(candidate, carried_name) for candidate in ast.walk(node.test) for carried_name in _P1_EFFECT_ID_OCCURRENCES))
    complete_binding = next((node for node in binding_ifs if _complete_decoded_effect_id_relation(node.test)), None)
    if complete_binding is None:
        findings.add(Finding("p1-effect-id-binding", "complete-decoded-relation"))
    else:
        if complete_binding.lineno <= decoded_line:
            findings.add(Finding("p1-effect-id-binding", "decode-before-relation"))
        if not _returns_effect_failure(complete_binding):
            findings.add(Finding("p1-effect-id-binding", "stop-on-mismatch"))
        value_lines = tuple(node.lineno for node in ast.walk(predicate) if isinstance(node, ast.If) and node.lineno > decoded_line and any(isinstance(candidate, ast.Attribute) and candidate.attr == "effect_values" and isinstance(candidate.value, ast.Name) and candidate.value.id == "selector_result" for candidate in ast.walk(node.test)))
        if not value_lines or complete_binding.lineno >= min(value_lines):
            findings.add(Finding("p1-effect-id-binding", "relation-before-value"))

    occurrence_details = {"effect_id": "ordered_source_effect_ids", "record_effect_id": "ordered_source_effects.effect_id", "selector_effect_id": "selector_result.source_effect_ids"}
    for carried_name, detail in occurrence_details.items():
        if not any(_decoded_effect_id_comparison(candidate, carried_name) for node in binding_ifs for candidate in ast.walk(node.test)):
            findings.add(Finding("p1-effect-id-binding", detail))

    forbidden_calls = {"sorted": "no-sort", "set": "no-set", "frozenset": "no-set"}
    for call in (node for node in ast.walk(predicate) if isinstance(node, ast.Call)):
        if (forbidden_detail := forbidden_calls.get(_call_leaf(call))) is not None:
            findings.add(Finding("p1-effect-id-binding", forbidden_detail))
    return findings


def _if_references_attribute(node: ast.If, owner: str, attribute: str) -> bool:
    return any(isinstance(candidate, ast.Attribute) and candidate.attr == attribute and isinstance(candidate.value, ast.Name) and candidate.value.id == owner for candidate in ast.walk(node.test))


def _if_references_name(node: ast.If, name: str) -> bool:
    return any(isinstance(candidate, ast.Name) and candidate.id == name for candidate in ast.walk(node.test))


def _active_p1_chronology_findings(tree: ast.Module) -> set[Finding]:
    findings: set[Finding] = set()
    predicate = _top_level_function(tree, "_predicate_3o_1_6")
    if predicate is None:
        return {Finding("p1-chronology-order", "_predicate_3o_1_6")}
    top_level_ifs = tuple(node for node in predicate.body if isinstance(node, ast.If))

    type_line = next((node.lineno for node in top_level_ifs if "type(strict_chronology) is not StrictChronologyProjection" in ast.unparse(node.test)), None)
    if type_line is None:
        findings.add(Finding("p1-chronology-order", "projection-type"))

    fields = tuple(name for name, _ in _P1_PROJECTION_SHAPES["StrictChronologyProjection"])
    field_lines: list[int] = []
    for field in fields:
        field_if = next((node for node in top_level_ifs if _if_references_attribute(node, "strict_chronology", field)), None)
        if field_if is None:
            findings.add(Finding("p1-chronology-order", field))
        else:
            field_lines.append(field_if.lineno)
    if type_line is not None and len(field_lines) == len(fields) and [type_line, *field_lines] != sorted([type_line, *field_lines]):
        findings.add(Finding("p1-chronology-order", "declaration-order"))

    relation_lines = [node.lineno for node in top_level_ifs if _if_references_name(node, "selector_result") or _if_references_name(node, "ordered_source_effects") or _if_references_name(node, "sequences")]
    sequence_assignments = [node.lineno for node in predicate.body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "sequences"]
    relation_lines.extend(sequence_assignments)
    last_field_line = max(field_lines, default=-1)
    if not relation_lines or min(relation_lines) <= last_field_line:
        findings.add(Finding("p1-chronology-order", "relation-after-fields"))

    identity_calls = tuple(call for call in ast.walk(predicate) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "strict_chronology_id")
    identity_comparison = next((node for node in top_level_ifs if any(isinstance(candidate, ast.Name) and candidate.id in {"carried_id", "expected_id"} for candidate in ast.walk(node.test))), None)
    if len(identity_calls) != 1 or identity_comparison is None or identity_calls[0].lineno >= identity_comparison.lineno or relation_lines and identity_calls[0].lineno <= max(relation_lines) or any(node.lineno > identity_comparison.lineno for node in top_level_ifs):
        findings.add(Finding("p1-chronology-order", "identity-last"))
    return findings


def _resolved_call(
    analysis: qualified.QualifiedSymbolAnalysis,
    owner: str,
    call: ast.Call,
) -> tuple[frozenset[str], bool, bool]:
    spelling = ast.unparse(call.func)
    matches = tuple(
        item
        for item in analysis.calls
        if item.scope == (owner,)
        and item.lineno == call.lineno
        and item.spelling == spelling
    )
    return (
        frozenset(target for item in matches for target in item.targets),
        any(item.dynamic for item in matches),
        any(item.sensitive_unresolved for item in matches),
    )


def _p1_later_schedule_target(target: str) -> bool:
    module, _, leaf = target.rpartition(".")
    return bool(
        module == CANONICAL_MODULE
        and (
            leaf in _P1_LATER_SCHEDULE_LEAVES
            or leaf.startswith(("_predicate_3o_2", "_predicate_3o_3", "_predicate_3o_4"))
        )
    )


def _p1_schedule_events(
    *,
    node: ast.AST,
    owner: str,
    entry_index: int,
    analysis: qualified.QualifiedSymbolAnalysis,
    functions: dict[str, ast.FunctionDef],
    stack: tuple[str, ...],
    reachable_owners: set[str],
    findings: set[Finding],
) -> tuple[_P1ScheduleEvent, ...]:
    reachable_owners.add(owner)
    events: list[_P1ScheduleEvent] = []
    calls = sorted(
        (candidate for candidate in ast.walk(node) if isinstance(candidate, ast.Call)),
        key=lambda candidate: (candidate.lineno, candidate.col_offset),
    )
    for call in calls:
        spelling = ast.unparse(call.func)
        targets, dynamic, sensitive_unresolved = _resolved_call(analysis, owner, call)
        predicate_targets = targets & frozenset(_P1_PREDICATE_TARGETS)
        chronology_targets = targets & _P1_CHRONOLOGY_SCHEDULE_TARGETS
        later_targets = frozenset(
            target for target in targets if _p1_later_schedule_target(target)
        )
        if (dynamic or sensitive_unresolved) and (
            owner not in _P1_PREDICATE_FAMILIES
            or predicate_targets
            or chronology_targets
            or later_targets
        ):
            findings.add(Finding("p1-validator-schedule", "dynamic-dispatch"))
        for target in sorted(predicate_targets):
            events.append(
                _P1ScheduleEvent(
                    "predicate",
                    str(_P1_PREDICATE_TARGETS.index(target)),
                    entry_index,
                    owner,
                    spelling,
                    targets,
                    call,
                )
            )
        for target in sorted(chronology_targets):
            events.append(
                _P1ScheduleEvent(
                    "chronology",
                    target.rsplit(".", 1)[-1],
                    entry_index,
                    owner,
                    spelling,
                    targets,
                    call,
                )
            )
        for target in sorted(later_targets):
            events.append(
                _P1ScheduleEvent(
                    "later",
                    target.rsplit(".", 1)[-1],
                    entry_index,
                    owner,
                    spelling,
                    targets,
                    call,
                )
            )
        terminal_targets = predicate_targets | chronology_targets | later_targets
        for target in sorted(targets - terminal_targets):
            module, _, leaf = target.rpartition(".")
            if module != CANONICAL_MODULE or leaf not in functions:
                continue
            if leaf in stack or len(stack) >= 6:
                findings.add(Finding("p1-validator-schedule", "helper-propagation"))
                continue
            events.extend(
                _p1_schedule_events(
                    node=functions[leaf],
                    owner=leaf,
                    entry_index=entry_index,
                    analysis=analysis,
                    functions=functions,
                    stack=(*stack, leaf),
                    reachable_owners=reachable_owners,
                    findings=findings,
                )
            )
    return tuple(events)


def _p1_schedule_loop(
    event: _P1ScheduleEvent,
    validator: ast.FunctionDef,
    parents: dict[ast.AST, ast.AST],
) -> ast.For | None:
    if event.owner != validator.name:
        return None
    controls: list[ast.AST] = []
    current = parents.get(event.node)
    while current is not None and current is not validator:
        if isinstance(
            current,
            (
                ast.AsyncFor,
                ast.AsyncWith,
                ast.BoolOp,
                ast.For,
                ast.If,
                ast.IfExp,
                ast.Match,
                ast.Try,
                ast.TryStar,
                ast.While,
                ast.With,
                ast.comprehension,
            ),
        ):
            controls.append(current)
        current = parents.get(current)
    if (
        current is validator
        and len(controls) == 1
        and isinstance(controls[0], ast.For)
        and parents.get(controls[0]) is validator
    ):
        return controls[0]
    return None


def _p1_selection_count_is_exact(
    tree: ast.Module,
    analysis: qualified.QualifiedSymbolAnalysis,
) -> bool:
    declarations = tuple(
        node
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "_CANONICAL_SELECTION_COUNT"
    )
    stores = tuple(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and node.id == "_CANONICAL_SELECTION_COUNT"
        and isinstance(node.ctx, (ast.Del, ast.Store))
    )
    shadowing_parameters = tuple(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.arg) and node.arg == "_CANONICAL_SELECTION_COUNT"
    )
    binding_events = tuple(
        binding
        for binding in analysis.binding_events
        if binding.name == "_CANONICAL_SELECTION_COUNT"
    )
    return bool(
        len(declarations) == 1
        and stores == (declarations[0].target,)
        and not shadowing_parameters
        and len(binding_events) == 1
        and binding_events[0].scope == ()
        and binding_events[0].kind == "annassign"
        and binding_events[0].lineno == declarations[0].lineno
        and isinstance(declarations[0].value, ast.Constant)
        and type(declarations[0].value.value) is int
        and declarations[0].value.value == 318
        and ast.unparse(declarations[0].annotation) == "_Final"
    )


def _p1_count_increment(node: ast.stmt, family: int) -> bool:
    return bool(
        isinstance(node, ast.AugAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == f"count_{family}"
        and isinstance(node.op, ast.Add)
        and isinstance(node.value, ast.Constant)
        and type(node.value.value) is int
        and node.value.value == 1
    )


def _p1_failure_guard(node: ast.stmt) -> bool:
    return bool(
        isinstance(node, ast.If)
        and ast.unparse(node.test) == "failure is not None"
        and len(node.body) == 1
        and isinstance(node.body[0], ast.Return)
        and not node.orelse
    )


def _p1_selection_shape_guard(node: ast.stmt) -> bool:
    return bool(
        isinstance(node, ast.If)
        and ast.unparse(node.test) == "not _selection_shape(selections[index])"
        and len(node.body) == 2
        and isinstance(node.body[0], ast.Assign)
        and len(node.body[0].targets) == 1
        and isinstance(node.body[0].targets[0], ast.Name)
        and node.body[0].targets[0].id == "failure"
        and isinstance(node.body[1], ast.Return)
        and not node.orelse
    )


def _p1_count_initialization(node: ast.stmt, family: int) -> bool:
    return bool(
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == f"count_{family}"
        and isinstance(node.value, ast.Constant)
        and type(node.value.value) is int
        and node.value.value == 0
    )


def _p1_failure_declaration(node: ast.stmt) -> bool:
    return bool(
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "failure"
        and ast.unparse(node.annotation) == "_PredicateFailure | None"
        and node.value is None
    )


def _p1_scope_guard(node: ast.stmt) -> bool:
    return bool(
        isinstance(node, ast.If)
        and ast.unparse(node.test)
        == "type(selections) is not tuple or len(selections) != _CANONICAL_SELECTION_COUNT"
        and len(node.body) == 2
        and isinstance(node.body[0], ast.Assign)
        and len(node.body[0].targets) == 1
        and isinstance(node.body[0].targets[0], ast.Name)
        and node.body[0].targets[0].id == "failure"
        and isinstance(node.body[1], ast.Return)
        and not node.orelse
    )


def _p1_final_return(node: ast.stmt) -> bool:
    return bool(
        isinstance(node, ast.Return)
        and node.value is not None
        and ast.unparse(node.value)
        == "(None, (count_0, count_1, count_2, count_3, count_4, count_5, count_6))"
    )


def _p1_inert_literal(node: ast.expr, *, depth: int = 0) -> bool:
    if depth >= qualified._MAX_ABSTRACT_STRUCTURE_DEPTH:
        return False
    if isinstance(node, ast.Constant):
        return type(node.value) in {bool, bytes, float, int, str, type(None)}
    return bool(
        isinstance(node, ast.Tuple)
        and len(node.elts) <= qualified._MAX_ABSTRACT_CONTAINER_WIDTH
        and all(_p1_inert_literal(item, depth=depth + 1) for item in node.elts)
    )


def _p1_trivial_statement(node: ast.stmt) -> bool:
    return isinstance(node, ast.Pass) or bool(
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and type(node.value.value) is str
    )


def _p1_inert_local_assignment(node: ast.stmt, owner: ast.FunctionDef) -> bool:
    if (
        not isinstance(node, ast.Assign)
        or len(node.targets) != 1
        or not isinstance(node.targets[0], ast.Name)
        or not _p1_inert_literal(node.value)
    ):
        return False
    name = node.targets[0].id
    uses = tuple(
        item
        for item in ast.walk(owner)
        if isinstance(item, ast.Name)
        and item.id == name
    )
    return tuple(item for item in uses if isinstance(item.ctx, ast.Store)) == (
        node.targets[0],
    ) and not any(isinstance(item.ctx, ast.Load) for item in uses)


def _p1_sensitive_schedule_target(target: str) -> bool:
    return bool(
        target in frozenset(_P1_PREDICATE_TARGETS)
        or target in _P1_CHRONOLOGY_SCHEDULE_TARGETS
        or _p1_later_schedule_target(target)
    )


def _p1_neutral_helper_reason(helper: ast.FunctionDef, *, analysis: qualified.QualifiedSymbolAnalysis, functions: dict[str, ast.FunctionDef], memo: dict[str, str | None], stack: tuple[str, ...]) -> str | None:
    if helper.name in memo:
        return memo[helper.name]
    if helper.name in stack or len(stack) >= 8:
        return "helper-propagation"
    nodes = tuple(ast.walk(helper))
    parameters = (*helper.args.posonlyargs, *helper.args.args, helper.args.vararg, *helper.args.kwonlyargs, helper.args.kwarg)
    if (
        not helper.name.startswith("_")
        or helper.decorator_list
        or len(nodes) > 512
        or any(parameters)
        or any(isinstance(node, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef, ast.Lambda)) for node in nodes if node is not helper)
        or any(isinstance(node, (ast.Global, ast.Nonlocal)) for node in nodes)
    ):
        return "helper-propagation"
    scope = (helper.name,)
    if any(_p1_sensitive_schedule_target(target) for reference in analysis.references if reference.scope == scope for target in reference.targets) or any(_p1_sensitive_schedule_target(origin) for binding in analysis.binding_events if binding.scope == scope for origin in binding.origins):
        return "hidden-helper"
    if any(call.dynamic or call.sensitive_unresolved for call in analysis.calls if call.scope == scope):
        return "dynamic-dispatch"
    reason: str | None = None
    for index, statement in enumerate(helper.body):
        terminal_none = isinstance(statement, ast.Return) and (statement.value is None or isinstance(statement.value, ast.Constant) and statement.value.value is None)
        if terminal_none:
            if index == len(helper.body) - 1:
                continue
            reason = "entry-skeleton"
            break
        reason = _p1_neutral_statement_reason(statement, owner=helper, analysis=analysis, functions=functions, memo=memo, stack=(*stack, helper.name))
        if reason is not None:
            break
    memo[helper.name] = reason
    return reason


def _p1_neutral_statement_reason(node: ast.stmt, *, owner: ast.FunctionDef, analysis: qualified.QualifiedSymbolAnalysis, functions: dict[str, ast.FunctionDef], memo: dict[str, str | None], stack: tuple[str, ...]) -> str | None:
    if _p1_trivial_statement(node):
        return None
    if _p1_inert_local_assignment(node, owner):
        return None
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return "entry-skeleton"
    targets, dynamic, unresolved = _resolved_call(analysis, owner.name, node.value)
    local_helpers = tuple(functions[target.rsplit(".", 1)[-1]] for target in targets if target.rpartition(".")[0] == CANONICAL_MODULE and target.rsplit(".", 1)[-1] in functions)
    if dynamic or unresolved or len(local_helpers) != 1 or node.value.args or node.value.keywords:
        return "dynamic-dispatch"
    return _p1_neutral_helper_reason(local_helpers[0], analysis=analysis, functions=functions, memo=memo, stack=stack)


def _p1_entry_contract_findings(
    validator: ast.FunctionDef,
    family_loops: dict[int, ast.For],
    analysis: qualified.QualifiedSymbolAnalysis,
    functions: dict[str, ast.FunctionDef],
) -> set[Finding]:
    findings: set[Finding] = set()
    loop_families = {loop: family for family, loop in family_loops.items()}
    memo: dict[str, str | None] = {}
    observed: list[str] = []
    for statement in validator.body:
        if _p1_failure_declaration(statement):
            observed.append("failure")
            continue
        if _p1_scope_guard(statement):
            observed.append("scope")
            continue
        if _p1_final_return(statement):
            observed.append("return")
            continue
        family = next(
            (
                candidate
                for candidate in range(7)
                if _p1_count_initialization(statement, candidate)
            ),
            None,
        )
        if family is not None:
            observed.append(f"count-{family}")
            continue
        loop_family = (
            loop_families.get(statement) if isinstance(statement, ast.For) else None
        )
        if loop_family is not None:
            observed.append(f"loop-{loop_family}")
            continue
        reason = _p1_neutral_statement_reason(
            statement,
            owner=validator,
            analysis=analysis,
            functions=functions,
            memo=memo,
            stack=(validator.name,),
        )
        if reason is not None:
            findings.add(Finding("p1-validator-schedule", reason))
    labels = (
        "failure",
        "scope",
        *(label for family in range(7) for label in (f"count-{family}", f"loop-{family}")),
        "return",
    )
    if tuple(observed) != labels:
        findings.add(Finding("p1-validator-schedule", "entry-skeleton"))
    return findings


def _canonical_p1_schedule_loop(
    loop: ast.For,
    event: _P1ScheduleEvent,
    family: int,
    validator: ast.FunctionDef,
    analysis: qualified.QualifiedSymbolAnalysis,
    parents: dict[ast.AST, ast.AST],
) -> bool:
    if not isinstance(loop.iter, ast.Call):
        return False
    iterator_targets, iterator_dynamic, iterator_unresolved = _resolved_call(
        analysis, validator.name, loop.iter
    )
    current: ast.AST = event.node
    while parents.get(current) is not None and parents[current] is not loop:
        current = parents[current]
    if not (
        isinstance(loop.target, ast.Name)
        and loop.target.id == "index"
        and isinstance(loop.iter.func, ast.Name)
        and loop.iter.func.id == "range"
        and len(loop.iter.args) == 1
        and not loop.iter.keywords
        and isinstance(loop.iter.args[0], ast.Name)
        and loop.iter.args[0].id == "_CANONICAL_SELECTION_COUNT"
        and not loop.orelse
        and iterator_targets == frozenset({"builtins.range"})
        and not iterator_dynamic
        and not iterator_unresolved
        and isinstance(current, ast.Assign)
        and len(current.targets) == 1
        and isinstance(current.targets[0], ast.Name)
        and current.targets[0].id == "failure"
        and current.value is event.node
    ):
        return False
    increments = tuple(
        statement for statement in loop.body if _p1_count_increment(statement, family)
    )
    shape_guards = tuple(
        statement for statement in loop.body if _p1_selection_shape_guard(statement)
    )
    failure_guards = tuple(
        statement for statement in loop.body if _p1_failure_guard(statement)
    )
    recognized = {
        current,
        *increments,
        *shape_guards,
        *failure_guards,
    }
    if any(
        statement not in recognized
        and not _p1_trivial_statement(statement)
        for statement in loop.body
    ):
        return False
    if (
        len(increments) != 1
        or len(failure_guards) != 1
        or len(shape_guards) != (1 if family == 0 else 0)
    ):
        return False
    ordered = (
        increments[0],
        *shape_guards,
        current,
        failure_guards[0],
    )
    return tuple(loop.body.index(statement) for statement in ordered) == tuple(
        sorted(loop.body.index(statement) for statement in ordered)
    )


def _active_p1_schedule_findings(
    tree: ast.Module,
    analysis: qualified.QualifiedSymbolAnalysis,
) -> set[Finding]:
    findings: set[Finding] = set()
    validator = _top_level_function(tree, "_validate_stage2f_p1")
    if validator is None:
        return {Finding("p1-validator-schedule", "_validate_stage2f_p1")}
    if any(
        isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef, ast.Lambda))
        for node in ast.walk(validator)
        if node is not validator
    ):
        findings.add(Finding("p1-validator-schedule", "helper-propagation"))
    functions = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    if not _p1_selection_count_is_exact(tree, analysis):
        findings.add(Finding("p1-validator-schedule", "selection-count-authority"))
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    reachable_owners: set[str] = set()
    entry_events = tuple(
        event
        for entry_index, statement in enumerate(validator.body)
        for event in _p1_schedule_events(
            node=statement,
            owner=validator.name,
            entry_index=entry_index,
            analysis=analysis,
            functions=functions,
            stack=(validator.name,),
            reachable_owners=reachable_owners,
            findings=findings,
        )
    )
    predicate_body_events: list[_P1ScheduleEvent] = []
    for family, predicate_name in enumerate(_P1_PREDICATE_FAMILIES):
        predicate = functions.get(predicate_name)
        if predicate is None:
            continue
        body_events = _p1_schedule_events(
            node=predicate,
            owner=predicate_name,
            entry_index=family,
            analysis=analysis,
            functions=functions,
            stack=(predicate_name,),
            reachable_owners=reachable_owners,
            findings=findings,
        )
        predicate_body_events.extend(
            event for event in body_events if event.kind == "predicate"
        )
        chronology_events = tuple(
            event for event in body_events if event.kind == "chronology"
        )
        if family < 6:
            for event in chronology_events:
                findings.add(Finding("p1-validator-chronology", event.detail))
        elif (
            len(chronology_events) != 1
            or chronology_events[0].owner != predicate_name
            or chronology_events[0].spelling != "strict_chronology_id"
            or chronology_events[0].targets
            != frozenset({f"{CANONICAL_MODULE}.strict_chronology_id"})
        ):
            for detail in {
                *(event.detail for event in chronology_events),
                "strict_chronology_id",
            }:
                findings.add(Finding("p1-validator-chronology", detail))
        for event in body_events:
            if event.kind == "later":
                findings.add(Finding("p1-validator-p2", event.detail))
    predicate_events = (
        *(event for event in entry_events if event.kind == "predicate"),
        *predicate_body_events,
    )
    for event in predicate_events:
        family = int(event.detail)
        if event.owner != validator.name:
            findings.add(Finding("p1-validator-schedule", "hidden-helper"))
        if (
            event.spelling != _P1_PREDICATE_FAMILIES[family]
            or event.targets != frozenset({_P1_PREDICATE_TARGETS[family]})
        ):
            findings.add(Finding("p1-validator-schedule", "predicate-alias"))
            findings.add(Finding("p1-validator-schedule", "dynamic-dispatch"))
    family_loops: dict[int, ast.For] = {}
    for family, _predicate_name in enumerate(_P1_PREDICATE_FAMILIES):
        family_events = tuple(
            event for event in predicate_events if event.detail == str(family)
        )
        if len(family_events) != 1:
            findings.add(Finding("p1-validator-schedule", f"family-{family}-count"))
            continue
        event = family_events[0]
        loop = _p1_schedule_loop(event, validator, parents)
        if loop is not None and isinstance(loop.iter, ast.Call):
            range_targets, range_dynamic, range_unresolved = _resolved_call(
                analysis, validator.name, loop.iter
            )
            if (
                range_targets != frozenset({"builtins.range"})
                or range_dynamic
                or range_unresolved
            ):
                findings.add(Finding("p1-validator-schedule", "range-authority"))
        if loop is None or not _canonical_p1_schedule_loop(
            loop,
            event,
            family,
            validator,
            analysis,
            parents,
        ):
            findings.add(Finding("p1-validator-schedule", f"family-{family}-loop"))
        else:
            family_loops[family] = loop

    normalized_families = tuple(
        event.detail
        for event in entry_events
        if event.kind == "predicate" and event.owner == validator.name
    )
    if normalized_families != tuple(str(family) for family in range(7)):
        findings.add(Finding("p1-validator-schedule", "family-order"))
    if len(family_loops) != 7 or len({id(loop) for loop in family_loops.values()}) != 7:
        findings.add(Finding("p1-validator-schedule", "predicate-family-major"))
    else:
        findings.update(
            _p1_entry_contract_findings(
                validator,
                family_loops,
                analysis,
                functions,
            )
        )

    matching_call_references = {
        (item.scope, item.lineno, item.spelling, target)
        for item in analysis.calls
        for target in item.targets
    }
    reachable_scopes = {(owner,) for owner in reachable_owners}
    for reference in analysis.references:
        predicate_targets = reference.targets & frozenset(_P1_PREDICATE_TARGETS)
        if reference.scope not in reachable_scopes or not predicate_targets:
            continue
        if any(
            (reference.scope, reference.lineno, reference.spelling, target)
            not in matching_call_references
            for target in predicate_targets
        ):
            findings.add(Finding("p1-validator-schedule", "dynamic-dispatch"))

    family_6_entry = (
        validator.body.index(family_loops[6]) if 6 in family_loops else None
    )
    for event in entry_events:
        if event.kind == "chronology" and (
            family_6_entry is None or event.entry_index <= family_6_entry
        ):
            findings.add(Finding("p1-validator-chronology", event.detail))
        elif event.kind == "later" and (
            family_6_entry is None or event.entry_index <= family_6_entry
        ):
            findings.add(Finding("p1-validator-p2", event.detail))
    return findings


def _active_p1_internal_findings_with_session(
    source: str,
    session: _AnalysisSession,
) -> set[Finding]:
    try:
        facts = session.source_analysis(source, module_name=CANONICAL_MODULE)
    except SyntaxError:
        return {Finding("invalid-production-syntax", CANONICAL_MODULE)}
    tree = facts.tree
    analysis = facts.analysis
    return (
        _active_p1_effect_findings(tree)
        | _active_p1_chronology_findings(tree)
        | _active_p1_schedule_findings(tree, analysis)
    )


def _active_p1_internal_findings(source: str) -> set[Finding]:
    return _active_p1_internal_findings_with_session(source, _AnalysisSession())


def _p2_functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _p2_source_identity_is_exact(
    functions: dict[str, ast.FunctionDef],
) -> bool:
    identity, preimage = (
        functions.get("source_observation_identity"),
        functions.get("_source_observation_preimage"),
    )
    if identity is None or preimage is None:
        return False
    parameters = _parameters(identity)
    returns = identity.body[0] if len(identity.body) == 1 else None
    direct = returns.value if isinstance(returns, ast.Return) and isinstance(returns.value, ast.Call) else None
    expected_preimage = (
        "mapping = _calibration_source_observation_mapping(projection)",
        "decoded = _decode_calibration_source_observation_projection(mapping)",
        "if decoded != projection:\n    _reject('source_observation', 'projection does not exactly reconstruct')",
        "return mapping",
    )
    return bool(
        len(parameters) == 1
        and parameters[0].arg == "projection"
        and _annotation_is(parameters[0].annotation, "CalibrationSourceObservationProjection")
        and _annotation_is(identity.returns, "str")
        and direct is not None
        and ast.unparse(direct) == "_protocol_hash('validation_evidence_calibration_source_observation/v1', _source_observation_preimage(projection))"
        and tuple(map(ast.unparse, preimage.body)) == expected_preimage
    )


def _p2_source_codec_is_exact(functions: dict[str, ast.FunctionDef]) -> bool:
    mapper, decoder = (
        functions.get("_calibration_source_observation_mapping"),
        functions.get("_decode_calibration_source_observation_projection"),
    )
    if mapper is None or decoder is None:
        return False
    mapper_return = next((node for node in reversed(mapper.body) if isinstance(node, ast.Return)), None)
    decoder_return = next((node for node in reversed(decoder.body) if isinstance(node, ast.Return)), None)
    expected = PROJECTION_FIELDS["CalibrationSourceObservationProjection"]
    return bool(
        mapper_return is not None
        and isinstance(mapper_return.value, ast.Dict)
        and tuple(key.value if isinstance(key, ast.Constant) else None for key in mapper_return.value.keys) == expected
        and decoder_return is not None
        and isinstance(decoder_return.value, ast.Call)
        and ast.unparse(decoder_return.value.func) == "CalibrationSourceObservationProjection"
        and not decoder_return.value.args
        and tuple(keyword.arg for keyword in decoder_return.value.keywords) == expected
    )


def _p2_signature_is_exact(function: ast.FunctionDef | None, positional: tuple[str, ...], keyword_only: tuple[str, ...], annotations: tuple[str, ...], returns: str) -> bool: return bool(function is not None and not function.decorator_list and not function.args.posonlyargs and tuple(argument.arg for argument in function.args.args) == positional and tuple(argument.arg for argument in function.args.kwonlyargs) == keyword_only and not function.args.defaults and all(item is None for item in function.args.kw_defaults) and function.args.vararg is None and function.args.kwarg is None and not getattr(function, "type_params", ()) and function.type_comment is None and tuple(ast.unparse(argument.annotation) if argument.annotation is not None else None for argument in (*function.args.args, *function.args.kwonlyargs)) in {annotations, (None,) * len(annotations)} and (ast.unparse(function.returns) if function.returns is not None else None) in {returns, None})
def _p2_dispatch_loops_are_exact(validator: ast.FunctionDef, loops: tuple[ast.For, ...], expected: tuple[str, ...]) -> bool: counters = tuple(loop.body[0].target.id if len(loop.body) == 2 and isinstance(loop.body[0], ast.AugAssign) and isinstance(loop.body[0].target, ast.Name) else "" for loop in loops); loop_names = tuple(loop.target.id if isinstance(loop.target, ast.Name) else "" for loop in loops); failure_names = tuple(loop.body[1].test.target.id if len(loop.body) == 2 and isinstance(loop.body[1], ast.If) and isinstance(loop.body[1].test, ast.NamedExpr) and isinstance(loop.body[1].test.target, ast.Name) else "" for loop in loops); protected = {parameter.arg for parameter in _parameters(validator)} | set(counters) | set(expected) | {"range", "_p2_outcome", "_validate_stage2f_p1", "p1_failure", "p1_counts"}; roots = (("selections", "p2_selections", "expected_predecessors"), ("selections", "p2_selections"), ("selections", "p2_selections", "expected_predecessors"), ("selections", "p2_selections", "expected_predecessors")); return bool(len(loops) == len(expected) == len(roots) == 4 and len(set(counters)) == 4 and all(loop_name and failure_name and loop_name not in protected and failure_name not in protected and loop_name != failure_name for loop_name, failure_name in zip(loop_names, failure_names, strict=True)) and all(isinstance(loop.target, ast.Name) and isinstance(loop.body[1], ast.If) and isinstance(loop.body[1].test, ast.NamedExpr) and isinstance(loop.body[1].test.target, ast.Name) and (position := validator.body.index(loop)) > 0 and ast.unparse(validator.body[position - 1]) == f"{counters[index]} = 0" and ast.unparse(loop) == f"for {loop.target.id} in range(_CANONICAL_SELECTION_COUNT):\n    {counters[index]} += 1\n    if ({loop.body[1].test.target.id} := {predicate}({', '.join(f'{root}[{loop.target.id}]' for root in roots[index])})):\n        return _p2_outcome({loop.body[1].test.target.id}, {index}, {loop.target.id}, p1_counts, ({', '.join((*counters[:index + 1], *('0' for _ in range(3 - index))))}))" for index, (loop, predicate) in enumerate(zip(loops, expected, strict=True))))
def _p2_schedule_is_exact(
    functions: dict[str, ast.FunctionDef],
) -> bool:
    validator = functions.get("_validate_stage2f_p2")
    if validator is None:
        return False
    expected = ("_predicate_3o_2_0", "_predicate_3o_2_1", "_predicate_3o_3_1", "_predicate_3o_4_1")
    signatures = (("_predicate_3o_2_0", ("selection", "p2_selection", "expected_predecessor"), (), ("_SelectionEvidence", "_P2SelectionEvidence", "_OraclePredecessor"), "_PredicateFailure | None"), ("_predicate_3o_2_1", ("selection", "p2_selection"), (), ("_SelectionEvidence", "_P2SelectionEvidence"), "_PredicateFailure | None"), ("_predicate_3o_3_1", ("selection", "p2_selection", "expected_predecessor"), (), ("_SelectionEvidence", "_P2SelectionEvidence", "_OraclePredecessor"), "_PredicateFailure | None"), ("_predicate_3o_4_1", ("selection", "p2_selection", "expected_predecessor"), (), ("_SelectionEvidence", "_P2SelectionEvidence", "_OraclePredecessor"), "_PredicateFailure | None"), ("_validate_stage2f_p2", (), ("selections", "expected_execution_attestation_pairs", "attested_execution_specification_ids", "p2_selections", "expected_predecessors"), ("tuple[_SelectionEvidence, ...]", "_ExecutionAttestationPairs", "_AttestedSpecificationIds", "tuple[_P2SelectionEvidence, ...]", "tuple[_OraclePredecessor, ...]"), "_P2ValidationOutcome")); body = tuple(statement for statement in validator.body if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str)))
    loops = tuple(node for node in validator.body if isinstance(node, ast.For))
    loop_calls = tuple(
        tuple(call.func.id for call in ast.walk(loop) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in expected)
        for loop in loops
    )
    return _p2_schedule_result_is_exact(functions, validator, expected, signatures, body, loops, loop_calls)
def _p2_owned_function_authority_findings(facts: _SourceAnalysis) -> set[Finding]: expected = {'_exact_h64': "def _exact_h64(value: object, path: str) -> str:\n    if type(value) is not str or len(value) != 64:\n        _reject(path, 'expected exact lowercase H64')\n    for character in value:\n        if character not in _LOWER_HEX:\n            _reject(path, 'expected exact lowercase H64')\n    return value", '_exact_oracle_key_id': "def _exact_oracle_key_id(value: object, path: str) -> str:\n    if type(value) is not str or value[:11] != 'oracle-key:':\n        _reject(path, 'expected exact Oracle key identity')\n    _exact_h64(value[len('oracle-key:'):], path)\n    return value", '_exact_f64_string': "def _exact_f64_string(value: object, path: str) -> str:\n    if type(value) is not str or len(value) != 20 or value[:4] != 'f64:':\n        _reject(path, 'expected exact canonical F64')\n    for character in value[4:]:\n        if character not in _LOWER_HEX:\n            _reject(path, 'expected exact canonical F64')\n    if value == 'f64:8000000000000000' or (value[4] in '7f' and value[5:7] == 'ff'):\n        _reject(path, 'expected finite canonical F64')\n    return value", '_source_key_fields': "def _source_key_fields(value: object) -> tuple[str, ...]:\n    if type(value) is not tuple or len(value) != 8:\n        _reject('source_observation.key_fields', 'expected exact eight-item tuple')\n    for field in value:\n        _exact_ascii_string(field, 'source_observation.key_fields')\n    return value", '_oracle_key_id': "def _oracle_key_id(key_fields):\n    return _runtime_id('oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})", '_outcome_digest': "def _outcome_digest(oracle_key_id, revealed_observation):\n    return _protocol_hash('revealed_outcome/v1', {'oracle_key_id': oracle_key_id, 'revealed_observation': revealed_observation})", '_coordinate_detail': "def _coordinate_detail(index: int, detail: str) -> str:\n    if 0 <= index < _CANONICAL_SELECTION_COUNT:\n        role, world_id, seed, comparison_group_id = _CANONICAL_SELECTION_COORDINATES[index]\n        return f'selection[{index}] {role}/{world_id}/{seed}/{comparison_group_id}: {detail}'\n    return f'selection[{index}]: {detail}'", '_exact_frozen_world': 'def _exact_frozen_world(value: object, world_id: str, ordered_candidate_pairs: tuple[tuple[str, str], ...]) -> _BenchmarkWorld:\n    """Reject capability-bearing or malformed substitutes before hidden helpers."""\n    if type(value) is not _BenchmarkWorld:\n        _reject(\'oracle_predecessor.world\', \'expected exact frozen BenchmarkWorld\')\n    try:\n        public = value.public\n        hidden = value.hidden\n    except AttributeError:\n        _reject(\'oracle_predecessor.world\', \'frozen world slots are incomplete\')\n    if type(public) is not _PublicWorldDefinition or type(hidden) is not _HiddenWorldParameters:\n        _reject(\'oracle_predecessor.world\', \'frozen world component type differs\')\n    try:\n        public_sequences = (public.candidate_ids, public.initial_feasible_candidate_ids, public.setup_candidate_ids, public.comparison_group_ids, public.budget_ids)\n    except AttributeError:\n        _reject(\'oracle_predecessor.world\', \'frozen world slots are incomplete\')\n    if type(world_id) is not str or type(public.world_id) is not str or public.world_id != world_id or (type(public.block) is not str) or (type(public.cost_catalog_id) is not str) or (type(public.depth) is not int) or (public.depth not in (2, 3)):\n        _reject(\'oracle_predecessor.world\', \'public frozen-world relation differs\')\n    for sequence in public_sequences:\n        if type(sequence) is not tuple:\n            _reject(\'oracle_predecessor.world\', \'public frozen-world sequence type differs\')\n        for item in sequence:\n            if type(item) is not str:\n                _reject(\'oracle_predecessor.world\', \'public frozen-world item type differs\')\n    if public.comparison_group_ids != _GROUP_IDS or not public.candidate_ids:\n        _reject(\'oracle_predecessor.world\', \'public frozen-world catalog differs\')\n    if type(ordered_candidate_pairs) is not tuple or len(ordered_candidate_pairs) != 5:\n        _reject(\'oracle_predecessor.world\', \'P1 candidate-pair relation differs\')\n    if type(hidden.scientific_hypothesis_id) is not str or type(hidden.effect_size) is not float or (not 0.0 <= hidden.effect_size <= 1.0) or (type(hidden.group_sigmas) is not tuple) or (len(hidden.group_sigmas) != 3):\n        _reject(\'oracle_predecessor.world\', \'hidden frozen-world relation differs\')\n    for group_index in range(3):\n        sigma_item = hidden.group_sigmas[group_index]\n        if type(sigma_item) is not tuple or len(sigma_item) != 2 or type(sigma_item[0]) is not str or (sigma_item[0] != _GROUP_IDS[group_index]) or (type(sigma_item[1]) is not float) or (not 0.0 < sigma_item[1] <= 1.0):\n            _reject(\'oracle_predecessor.world\', \'hidden frozen-world sigma relation differs\')\n    return value', '_source_evidence_at': 'def _source_evidence_at(p2_selection: _P2SelectionEvidence, observation_index: int) -> tuple[object, object] | None:\n    if not _p2_selection_shape(p2_selection):\n        return None\n    source_observations = p2_selection[1]\n    if type(source_observations) is not tuple or observation_index >= len(source_observations):\n        return None\n    evidence = source_observations[observation_index]\n    if type(evidence) is not tuple or len(evidence) != 2:\n        return None\n    return evidence', '_require_exact_source_observation_object': "def _require_exact_source_observation_object(value: object) -> CalibrationSourceObservationProjection:\n    if type(value) is not CalibrationSourceObservationProjection:\n        _reject('source_observation', 'expected exact CalibrationSourceObservationProjection')\n    return value", '_validate_source_observation_key_surface': "def _validate_source_observation_key_surface(value: object) -> tuple[CalibrationSourceObservationProjection, tuple[str, ...], str]:\n    projection = _require_exact_source_observation_object(value)\n    key_fields = _source_key_fields(projection.key_fields)\n    oracle_key_id = _exact_oracle_key_id(projection.oracle_key_id, 'source_observation.oracle_key_id')\n    return (projection, key_fields, oracle_key_id)", '_validate_source_observation_outcome_surface': "def _validate_source_observation_outcome_surface(value: object) -> tuple[CalibrationSourceObservationProjection, str, str]:\n    projection = _require_exact_source_observation_object(value)\n    revealed_observation = _exact_f64_string(projection.revealed_observation, 'source_observation.revealed_observation')\n    outcome_digest = _exact_h64(projection.outcome_digest, 'source_observation.outcome_digest')\n    return (projection, revealed_observation, outcome_digest)", '_expected_source_coordinate': "def _expected_source_coordinate(selection: _SelectionEvidence, observation_index: int) -> tuple[str, int, str, _Literal['adam', 'sgd'], str, str, tuple[str, ...]]:\n    from research_decision_engine.benchmarks.broader_oracle import _parse_calibration_candidate\n    from research_decision_engine.benchmarks.broader_oracle import calibration_key as _calibration_key\n    world_id, seed, comparison_group_id = (selection[2], selection[3], selection[4])\n    ordered_candidate_pairs, ordered_replication_ids = (selection[10], selection[13])\n    pair_index, arm_index = (observation_index // 2, observation_index % 2)\n    expected_arm: _Literal['adam', 'sgd'] = 'adam' if arm_index == 0 else 'sgd'\n    pair = ordered_candidate_pairs[pair_index]\n    if type(pair) is not tuple or len(pair) != 2:\n        _reject('source_observation', 'validated P1 candidate pair is malformed')\n    candidate_id, replication_id = (pair[arm_index], ordered_replication_ids[pair_index])\n    if type(world_id) is not str or type(seed) is not int or type(comparison_group_id) is not str or (type(candidate_id) is not str) or (type(replication_id) is not str):\n        _reject('source_observation', 'validated P1 source coordinate is malformed')\n    parsed = _parse_calibration_candidate(candidate_id)\n    if parsed != (comparison_group_id, expected_arm, replication_id):\n        _reject('source_observation', 'validated P1 pair/arm/replication differs')\n    key_fields = _calibration_key(world_id=world_id, seed=seed, comparison_group_id=comparison_group_id, intervention_arm=expected_arm, replication_id=replication_id, namespace=_CALIBRATION_NAMESPACE)\n    return (world_id, seed, comparison_group_id, expected_arm, candidate_id, replication_id, key_fields)", '_expected_observation_f64': "def _expected_observation_f64(selection: _SelectionEvidence, observation_index: int, world: _BenchmarkWorld) -> str:\n    from research_decision_engine.benchmarks.broader_oracle import transform_key as _transform_key\n    _world_id, _seed, comparison_group_id, expected_arm, _candidate_id, _replication_id, key_fields = _expected_source_coordinate(selection, observation_index)\n    base_candidate_id = f'g{comparison_group_id[-2:]}-{expected_arm}-r1'\n    transform = _transform_key(key_fields)\n    observed = _hidden_arm_mean(world, base_candidate_id) + _hidden_observation_sigma(world, base_candidate_id) * transform.z\n    return _f64(observed)", '_p2_outcome': 'def _p2_outcome(failure: _PredicateFailure, predicate_index: int, selection_index: int, p1_counts: _PredicateCounts, p2_counts: _P2PredicateCounts) -> _P2ValidationOutcome:\n    return ((failure[0], _P2_PREDICATE_PATHS[predicate_index], selection_index, _coordinate_detail(selection_index, failure[1])), (*p1_counts, *p2_counts))', '_p2_selection_shape': 'def _p2_selection_shape(value: object) -> bool:\n    return type(value) is tuple and len(value) == 2', '_oracle_predecessor_shape': 'def _oracle_predecessor_shape(value: object) -> bool:\n    return type(value) is tuple and len(value) == 11'}; protected = frozenset(expected) | {producer.qualified_target.rsplit(".", 1)[-1] for producer in OWNED_OPERATION_MANIFEST.producers} | {name for edge in OWNED_OPERATION_MANIFEST.operations for name in (edge.owner, edge.failure.helper, edge.failure.dispatcher, *(validator for validator, _stage in edge.carrier.validators))} | _names("_predicate_3o_2_0 _predicate_3o_4_1 _validate_stage2f_p2 _oracle_binding_failure _source_observation_failure"); return {Finding("p2-owned-function-authority", name) for name in protected if name not in facts.functions or facts.function_definition_counts.get(name) != 1 or facts.function_binding_event_counts.get(name) != 1 or name in expected and ast.unparse(facts.functions[name]) != expected[name] or facts.module_bindings.get(name) != qualified.ResolvedValue(direct_origins=frozenset({f'{CANONICAL_MODULE}.{name}'}), aggregate_origins=frozenset({f'{CANONICAL_MODULE}.{name}'}))}
def _p2_owned_terminal_authority_findings(facts: _SourceAnalysis) -> set[Finding]: failures = (OwnedFailure("_oracle_binding_failure", "CALIBRATION_ORACLE_BINDING_MISMATCH", "", "", 0), OwnedFailure("_oracle_key_failure", "CALIBRATION_ORACLE_KEY_ID_MISMATCH", "", "", 0), OwnedFailure("_outcome_failure", "CALIBRATION_OUTCOME_DIGEST_MISMATCH", "", "", 0), OwnedFailure("_source_observation_failure", "CALIBRATION_SOURCE_OBSERVATION_ID_MISMATCH", "", "", 0)); exact = {"_reject": "def _reject(path: str, detail: str) -> _NoReturn:\n    raise ValueError(f'{path}: {detail}')", "_exact_ascii_string": "def _exact_ascii_string(value: object, path: str) -> str:\n    if type(value) is not str or not value:\n        _reject(path, 'expected exact non-empty ASCII string')\n    for character in value:\n        if character > '\\x7f':\n            _reject(path, 'expected exact non-empty ASCII string')\n    return value"}; protected = frozenset(exact) | {failure.helper for failure in failures} | {"_validate_stage2f_p1"}; findings = {Finding("p2-owned-function-authority", name) for name in protected if facts.function_definition_counts.get(name) != 1 or facts.function_binding_event_counts.get(name) != 1 or facts.module_bindings.get(name) != qualified.ResolvedValue(direct_origins=frozenset({f"{CANONICAL_MODULE}.{name}"}), aggregate_origins=frozenset({f"{CANONICAL_MODULE}.{name}"}))}; findings.update(Finding("p2-owned-function-authority", failure.helper) for failure in failures if not _p2_failure_helper_is_exact(facts.functions.get(failure.helper), failure)); findings.update(Finding("p2-owned-function-authority", name) for name, expected in exact.items() if name not in facts.functions or ast.unparse(facts.functions[name]) != expected); findings.update(Finding("p2-owned-function-authority", "_validate_stage2f_p1") for _ in (0,) if not _p2_signature_is_exact(facts.functions.get("_validate_stage2f_p1"), (), ("selections", "expected_execution_attestation_pairs", "attested_execution_specification_ids"), ("tuple[_SelectionEvidence, ...]", "_ExecutionAttestationPairs", "_AttestedSpecificationIds"), "_ValidationOutcome")); return findings
def _p2_schedule_result_is_exact(functions: dict[str, ast.FunctionDef], validator: ast.FunctionDef, expected: tuple[str, ...], signatures: tuple[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...], str], ...], body: tuple[ast.stmt, ...], loops: tuple[ast.For, ...], loop_calls: tuple[tuple[str, ...], ...]) -> bool:
    p1_calls = tuple(call for call in ast.walk(validator) if isinstance(call, ast.Call) and ast.unparse(call.func) == "_validate_stage2f_p1")
    return bool(
        tuple(calls[0] for calls in loop_calls if len(calls) == 1) == expected
        and len(loop_calls) == len(expected)
        and all(ast.unparse(loop.iter) == "range(_CANONICAL_SELECTION_COUNT)" for loop in loops)
        and len(p1_calls) == 1
        and p1_calls[0].lineno < loops[0].lineno
        and len(body) == 12
        and body[-2] is loops[-1]
        and ast.unparse(body[0]) == "p1_failure, p1_counts = _validate_stage2f_p1(selections=selections, expected_execution_attestation_pairs=expected_execution_attestation_pairs, attested_execution_specification_ids=attested_execution_specification_ids)"
        and ast.unparse(body[1]) == "if p1_failure is not None:\n    return (p1_failure, (*p1_counts, 0, 0, 0, 0))"
        and ast.unparse(body[2]) == "if type(p2_selections) is not tuple or len(p2_selections) != _CANONICAL_SELECTION_COUNT or type(expected_predecessors) is not tuple or (len(expected_predecessors) != _CANONICAL_SELECTION_COUNT):\n    return _p2_outcome(_oracle_binding_failure('canonical P2 selection or Oracle predecessor count is not exactly 318'), 0, 0, p1_counts, (0, 0, 0, 0))"
        and ast.unparse(body[-1]) == "return (None, (*p1_counts, count_0, count_1, count_2, count_3))"
        and all(_p2_signature_is_exact(functions.get(name), positional, keyword_only, annotations, returns) for name, positional, keyword_only, annotations, returns in signatures)
        and _p2_dispatch_loops_are_exact(validator, loops, expected)
    )


_P2_COMPLETE_SOURCE_AUTHORITIES: Final = _names("_calibration_source_observation_mapping _decode_calibration_source_observation_projection _validate_complete_source_observation_surface _source_observation_preimage source_observation_identity _source_observation_matches _first_source_mismatch _predicate_3o_4_1")


def _p2_subscript_path(node: ast.expr) -> tuple[str, tuple[str, ...]] | None:
    indices: list[str] = []
    while isinstance(node, ast.Subscript):
        indices.append(ast.unparse(node.slice))
        node = node.value
    return (node.id, tuple(reversed(indices))) if isinstance(node, ast.Name) else None


def _p2_reachable_functions(root: str, functions: dict[str, ast.FunctionDef], analysis: qualified.QualifiedSymbolAnalysis) -> tuple[frozenset[str], bool]:
    reachable, pending, dynamic = {root}, [root], False
    while pending:
        owner = pending.pop()
        for call in analysis.calls:
            if call.scope != (owner,):
                continue
            dynamic = dynamic or call.dynamic or call.sensitive_unresolved
            for target in call.targets:
                callee = target.rsplit(".", 1)[-1]
                if target.startswith(f"{CANONICAL_MODULE}.") and callee in functions and callee not in reachable:
                    reachable.add(callee)
                    pending.append(callee)
    return frozenset(reachable), dynamic


def _p2_projection_expression(node: ast.expr, receiver_names: frozenset[str], bundle_names: frozenset[str] = frozenset()) -> bool:
    path = _p2_subscript_path(node)
    return bool(
        isinstance(node, ast.Name) and node.id in receiver_names
        or isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in {"evidence", "source_evidence"} and isinstance(node.slice, ast.Constant) and node.slice.value == 0
        or isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in bundle_names and isinstance(node.slice, ast.Constant) and node.slice.value == 0
        or path is not None and path[0] in receiver_names and path[1][-1:] == ("0",) and (len(path[1]) < 3 or path[1][0] == "1")
        or isinstance(node, ast.Call) and ast.unparse(node.func).rsplit(".", 1)[-1] == "_require_exact_source_observation_object" and len(node.args) == 1
    )


def _p2_projection_receivers(function: ast.FunctionDef) -> frozenset[str]:
    receivers = {parameter.arg for parameter in _parameters(function)} | {"projection", "source_projection"}
    bundles: set[str] = set()
    narrow = {"_validate_source_observation_key_surface", "_validate_source_observation_outcome_surface"}
    while True:
        aliases: set[str] = set()
        for node in ast.walk(function):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets, value = (node.targets if isinstance(node, ast.Assign) else (node.target,)), node.value
            if isinstance(value, ast.Call) and ast.unparse(value.func).rsplit(".", 1)[-1] in narrow:
                for target in targets:
                    if isinstance(target, ast.Name):
                        bundles.add(target.id)
                    elif isinstance(target, (ast.Tuple, ast.List)) and target.elts and isinstance(target.elts[0], ast.Name):
                        aliases.add(target.elts[0].id)
            elif value is not None and (_p2_projection_expression(value, frozenset(receivers), frozenset(bundles)) or isinstance(value, ast.Subscript) and (path := _p2_subscript_path(value)) is not None and path[0] in receivers):
                aliases.update(target.id for target in targets if isinstance(target, ast.Name))
        if aliases <= receivers:
            return frozenset(receivers)
        receivers.update(aliases)


def _p2_projection_field_references(function: ast.FunctionDef) -> frozenset[str]:
    receiver_names = _p2_projection_receivers(function)
    return frozenset(node.attr for node in ast.walk(function) if isinstance(node, ast.Attribute) and _p2_projection_expression(node.value, receiver_names) and node.attr in PROJECTION_FIELDS["CalibrationSourceObservationProjection"])


def _p2_dynamic_projection_access(function: ast.FunctionDef) -> bool:
    receivers = _p2_projection_receivers(function)
    return any(isinstance(node, ast.Call) and ast.unparse(node.func).rsplit(".", 1)[-1] in {"getattr", "hasattr", "vars"} and node.args and _p2_projection_expression(node.args[0], receivers) or isinstance(node, ast.Attribute) and node.attr == "__dict__" and _p2_projection_expression(node.value, receivers) or isinstance(node, ast.MatchClass) and ast.unparse(node.cls).rsplit(".", 1)[-1] == "CalibrationSourceObservationProjection" for node in ast.walk(function))


def _p2_try_relabels_complete_error(function: ast.FunctionDef, analysis: qualified.QualifiedSymbolAnalysis, failure_leaf: str) -> bool:
    targets_by_line = {call.lineno: call.targets for call in analysis.calls if call.scope == (function.name,)}
    for statement in (node for node in ast.walk(function) if isinstance(node, ast.Try)):
        try_targets = frozenset(target for node in ast.walk(statement) if isinstance(node, ast.Call) and node.lineno in targets_by_line for target in targets_by_line[node.lineno])
        complete = any(target.rsplit(".", 1)[-1] in _P2_COMPLETE_SOURCE_AUTHORITIES for target in try_targets)
        if complete and any(isinstance(node, ast.Call) and ast.unparse(node.func).rsplit(".", 1)[-1] == failure_leaf for handler in statement.handlers for node in ast.walk(handler)):
            return True
    return False


def _p2_call_reachability(call: qualified.ResolvedCall, functions: dict[str, ast.FunctionDef], analysis: qualified.QualifiedSymbolAnalysis) -> tuple[frozenset[str], bool]:
    reachable: set[str] = set()
    dynamic = call.dynamic or call.sensitive_unresolved
    for target in call.targets:
        root = target.rsplit(".", 1)[-1]
        if not target.startswith(f"{CANONICAL_MODULE}.") or root not in functions:
            continue
        root_reachable, root_dynamic = _p2_reachable_functions(root, functions, analysis)
        reachable.update(root_reachable)
        dynamic = dynamic or root_dynamic
    return frozenset(reachable), dynamic


def _p2_named_calls(function: ast.FunctionDef, name: str) -> tuple[ast.Call, ...]:
    return tuple(node for node in ast.walk(function) if isinstance(node, ast.Call) and ast.unparse(node.func).rsplit(".", 1)[-1] == name)


def _p2_call_ancestry(function: ast.FunctionDef, call: ast.Call) -> tuple[str, ...]:
    parents = {id(child): parent for parent in ast.walk(function) for child in ast.iter_child_nodes(parent)}
    chain: list[str] = []
    node: ast.AST = call
    while node is not function:
        node = parents[id(node)]
        chain.append(type(node).__name__)
    return tuple(chain)


def _p2_success_return_is_final(function: ast.FunctionDef, failure_leaf: str) -> bool:
    successes = tuple(node for node in ast.walk(function) if isinstance(node, ast.Return) and not (isinstance(node.value, ast.Call) and ast.unparse(node.value.func).rsplit(".", 1)[-1] == failure_leaf))
    return bool(len(successes) == 1 and successes[0] is function.body[-1] and isinstance(successes[0].value, ast.Constant) and successes[0].value.value is None and len(function.body) >= 2 and isinstance(outer := function.body[-2], ast.For) and outer.body and isinstance(group := outer.body[-1], ast.For) and group.body and isinstance(group.body[-1], ast.If))
def _p2_failure_helper_is_exact(function: ast.FunctionDef | None, failure: OwnedFailure) -> bool: return bool(function is not None and not function.decorator_list and len(parameters := (*function.args.posonlyargs, *function.args.args)) == 1 and not function.args.kwonlyargs and not function.args.defaults and function.args.vararg is None and function.args.kwarg is None and len(body := tuple(statement for statement in function.body if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str)))) == 1 and isinstance(body[0], ast.Return) and isinstance(value := body[0].value, ast.Tuple) and len(value.elts) == 2 and isinstance(value.elts[0], ast.Constant) and value.elts[0].value == failure.code and isinstance(value.elts[1], ast.Name) and value.elts[1].id == parameters[0].arg)
def _p2_outcome_is_exact(function: ast.FunctionDef | None) -> bool: return bool(function is not None and not function.decorator_list and len(parameters := (*function.args.posonlyargs, *function.args.args)) == 5 and not function.args.kwonlyargs and not function.args.defaults and function.args.vararg is None and function.args.kwarg is None and len(function.body) == 1 and isinstance(function.body[0], ast.Return) and function.body[0].value is not None and ast.unparse(function.body[0].value) == f"(({parameters[0].arg}[0], _P2_PREDICATE_PATHS[{parameters[1].arg}], {parameters[2].arg}, _coordinate_detail({parameters[2].arg}, {parameters[0].arg}[1])), (*{parameters[3].arg}, *{parameters[4].arg}))")
def _p2_producer_formulas_are_exact(functions: Mapping[str, ast.FunctionDef], owner: str) -> bool: return bool((oracle := functions.get("_oracle_key_id")) is not None and tuple(map(ast.unparse, oracle.body)) == ("return _runtime_id('oracle-key', 'oracle_key_id/v1', {'key_fields': key_fields})",) and (owner != "_predicate_3o_3_1" or (digest := functions.get("_outcome_digest")) is not None and tuple(map(ast.unparse, digest.body)) == ("return _protocol_hash('revealed_outcome/v1', {'oracle_key_id': oracle_key_id, 'revealed_observation': revealed_observation})",) and (observation := functions.get("_expected_observation_f64")) is not None and tuple(map(ast.unparse, observation.body)) == ("from research_decision_engine.benchmarks.broader_oracle import transform_key as _transform_key", "_world_id, _seed, comparison_group_id, expected_arm, _candidate_id, _replication_id, key_fields = _expected_source_coordinate(selection, observation_index)", "base_candidate_id = f'g{comparison_group_id[-2:]}-{expected_arm}-r1'", "transform = _transform_key(key_fields)", "observed = _hidden_arm_mean(world, base_candidate_id) + _hidden_observation_sigma(world, base_candidate_id) * transform.z", "return _f64(observed)")))


# fmt: off
def _owned_manifest_findings() -> tuple[Finding, ...]:
    manifest = OWNED_OPERATION_MANIFEST; invalid = Finding("p2-owned-dataflow-manifest", "OWNED_OPERATION_MANIFEST")
    if type(manifest) is not OwnedDataflowManifest or type(manifest.producers) is not tuple or type(manifest.operations) is not P2OwnedOperations or manifest.index_counts != (("field_index", 8), ("observation_index", 10)): return (invalid,)
    producer_keys: set[str] = set(); producer_owners: dict[str, str] = {}
    referenced_producers: set[str] = set()
    for producer in manifest.producers:
        if type(producer) is not OwnedProducer or not producer.key.replace("-", "_").isidentifier() or not producer.owner.isidentifier() or not producer.qualified_target.startswith(f"{CANONICAL_MODULE}.") or not producer.qualified_target.rsplit(".", 1)[-1].isidentifier() or type(producer.arguments) is not tuple or type(producer.result_path) is not tuple or producer.legacy_detail is not None and (type(producer.legacy_detail) is not str or not producer.legacy_detail.replace("-", "_").isidentifier()) or producer.key in producer_keys: return (invalid,)
        for argument in producer.arguments:
            if type(argument) is not OwnedArgument or argument.kind not in {"expression", "producer"} or not argument.value or type(argument.path) is not tuple or not all(_owned_path_step_is_valid(step) for step in argument.path) or argument.kind == "expression" and not argument.value.isidentifier() or argument.kind == "producer" and argument.path or argument.kind == "producer" and (argument.value not in producer_keys or producer_owners[argument.value] != producer.owner): return (invalid,)
            if argument.kind == "producer": referenced_producers.add(argument.value)
        if not all(_owned_path_step_is_valid(step) for step in producer.result_path): return (invalid,)
        producer_keys.add(producer.key); producer_owners[producer.key] = producer.owner
    carrier_paths: set[tuple[str, str, tuple[OwnedPathStep, ...]]] = set(); ranks: dict[tuple[str, int], set[int]] = {}
    failures: dict[str, OwnedFailure] = {}
    for slot, edge in _owned_operation_items():
        if type(edge) is not OwnedEdge or edge.operation != slot.replace("_", "-") or edge.producer not in producer_keys or producer_owners[edge.producer] != edge.owner or type(edge.carrier) is not OwnedCarrier or not edge.carrier.root_parameter.isidentifier() or not edge.carrier.path or not all(_owned_path_step_is_valid(step) for step in edge.carrier.path) or type(edge.carrier.validators) is not tuple or not edge.carrier.validators or not all(type(item) is tuple and len(item) == 2 and type(item[0]) is str and item[0].isidentifier() and type(item[1]) is int and 0 < item[1] <= len(edge.carrier.path) for item in edge.carrier.validators) or len({item[0] for item in edge.carrier.validators}) != len(edge.carrier.validators) or type(edge.comparison) is not OwnedComparison or edge.comparison.operator != "NotEq" or edge.comparison.carrier_side != "left" or min(edge.comparison.group_rank, edge.comparison.occurrence_rank) < 0 or type(edge.comparison.producer_path) is not tuple or not all(_owned_path_step_is_valid(step) for step in edge.comparison.producer_path) or type(edge.failure) is not OwnedFailure or not edge.failure.helper.isidentifier() or not edge.failure.code.isidentifier() or not edge.failure.path.startswith("calibration/") or edge.failure.dispatcher != "_validate_stage2f_p2" or edge.failure.dispatcher_index < 0: return (invalid,)
        path_key = (edge.owner, edge.carrier.root_parameter, edge.carrier.path)
        if path_key in carrier_paths: return (invalid,)
        carrier_paths.add(path_key); referenced_producers.add(edge.producer)
        ranks.setdefault((edge.owner, edge.comparison.group_rank), set()).add(edge.comparison.occurrence_rank)
        if edge.owner in failures and failures[edge.owner] != edge.failure: return (invalid,)
        failures[edge.owner] = edge.failure
    if referenced_producers != producer_keys: return (invalid,)
    for owner in failures:
        groups = sorted(group for candidate, group in ranks if candidate == owner)
        if groups != list(range(len(groups))): return (invalid,)
        for group in groups:
            occurrences = ranks[(owner, group)]
            if sorted(occurrences) != list(range(len(occurrences))): return (invalid,)
    return ()
def _owned_path_step_is_valid(step: object) -> bool:
    return bool(type(step) is OwnedPathStep and (step.kind == "attribute" and type(step.value) is str and step.value.isidentifier() or step.kind == "index-symbol" and type(step.value) is str and step.value.isidentifier() or step.kind == "index-literal" and type(step.value) is int and step.value >= 0))
def _owned_value(facts: _SourceAnalysis, node: ast.AST) -> _OwnedFlowValue:
    return facts.owned_values.get(id(node), _OwnedFlowValue(frozenset(), True, False, False, False))
def _p2_owned_dataflow_findings(facts: _SourceAnalysis) -> set[Finding]:
    metadata = _owned_manifest_findings()
    if metadata: return set(metadata)
    functions = dict(facts.functions); reachability = {owner: _p2_reachable_functions(owner, functions, facts.analysis)[0] for owner in {edge.owner for _slot, edge in _owned_operation_items()} if owner in functions}
    owned_flow_roots = set().union(*reachability.values(), *(_p2_reachable_functions(dispatcher, functions, facts.analysis)[0] for dispatcher in {edge.failure.dispatcher for _slot, edge in _owned_operation_items()} if dispatcher in functions)); execution_changed_owned_flow = not owned_flow_roots.isdisjoint(facts.execution_changed_function_roots - {"_reject"})
    unsafe_flow_owners = {owner for owner, function in functions.items() if function.end_lineno is not None and any(finding.code in _DYNAMIC_FINDINGS - {"alias-cycle"} and function.lineno <= finding.lineno <= function.end_lineno and not (finding.code == "unresolved-sensitive-provenance" and finding.symbol.startswith("mutation:") and (finding.lineno, finding.symbol.removeprefix("mutation:")) in facts.owned_benign_mutation_lines) for finding in facts.analysis.findings)}
    module_sites = tuple(item for items in (facts.analysis.calls, facts.analysis.references, facts.analysis.unresolved_mutations) for item in items if not item.scope or len(item.scope) == 1 and item.scope[0] not in functions); module_lines = frozenset(item.lineno for item in module_sites)
    module_roots = frozenset({target.rsplit(".", 1)[-1] for item in facts.analysis.calls if not item.scope or len(item.scope) == 1 and item.scope[0] not in functions for target in item.targets} | {target.rsplit(".", 1)[-1] for item in facts.analysis.references if not item.scope or len(item.scope) == 1 and item.scope[0] not in functions for target in item.targets}); module_reachable = set().union(*(_p2_reachable_functions(root, functions, facts.analysis)[0] for root in module_roots if root in functions))
    unsafe_module_flow = "" in facts.execution_changed_function_roots or execution_changed_owned_flow or any(finding.code in _DYNAMIC_FINDINGS - {"alias-cycle"} and finding.lineno in module_lines for finding in facts.analysis.findings) or not module_reachable.isdisjoint(unsafe_flow_owners)
    producer_lines: dict[str, int] = {}
    for producer in OWNED_OPERATION_MANIFEST.producers:
        reachable = reachability.get(producer.owner, ()); eligible = tuple(call for call in facts.analysis.calls if call.scope and call.scope[0] in reachable and call.targets == frozenset({producer.qualified_target}) and not call.dynamic and not call.sensitive_unresolved)
        producer_markers = frozenset({_owned_producer_marker(producer.key), *(_owned_producer_marker(producer.key, position) for position in range(len(producer.result_path)))})
        boundaries = tuple(expression for expression in facts.owned_expressions if isinstance(expression, ast.Call) and facts.scope_paths.get(id(expression)) == (producer.owner,) and _owned_value(facts, expression).markers & producer_markers and not _owned_value(facts, expression).unresolved)
        if eligible and boundaries: producer_lines[producer.key] = min(boundary.lineno for boundary in boundaries)
    findings: set[Finding] = {Finding("p2-predicate-ownership", f"{producer.owner}:{producer.legacy_detail}") for producer in OWNED_OPERATION_MANIFEST.producers if producer.legacy_detail is not None and producer.key not in producer_lines}
    all_producer_markers = frozenset({_owned_producer_marker(producer.key) for producer in OWNED_OPERATION_MANIFEST.producers} | {_owned_comparison_marker(slot, len(edge.comparison.producer_path)) for slot, edge in _owned_operation_items() if edge.comparison.producer_path})
    all_carrier_markers = frozenset(_owned_carrier_marker(slot, len(edge.carrier.path)) for slot, edge in _owned_operation_items()); predicate_paths = _assigned_literals(facts.tree).get("_P2_PREDICATE_PATHS")
    dispatch_calls = {dispatcher: tuple(call for call in sorted(facts.analysis.calls, key=lambda item: item.lineno) if call.scope == (dispatcher,) and call.spelling.startswith("_predicate_3o_")) for dispatcher in {edge.failure.dispatcher for _slot, edge in _owned_operation_items()}}
    failure_shapes = {edge.failure.helper: _p2_failure_helper_is_exact(functions.get(edge.failure.helper), edge.failure) for _slot, edge in _owned_operation_items()}; outcome_shape = _p2_outcome_is_exact(functions.get("_p2_outcome")); producer_formulas = {owner: _p2_producer_formulas_are_exact(functions, owner) for owner in reachability}
    matched_order: dict[tuple[str, int], list[tuple[int, str]]] = {}
    for slot, edge in _owned_operation_items():
        detail = f"{edge.owner}:{edge.operation}"; producer_marker = _owned_comparison_marker(slot, len(edge.comparison.producer_path)) if edge.comparison.producer_path else _owned_producer_marker(edge.producer)
        carrier_marker = _owned_carrier_marker(slot, len(edge.carrier.path)); group_size = sum(candidate.owner == edge.owner and candidate.comparison.group_rank == edge.comparison.group_rank for _candidate_slot, candidate in _owned_operation_items())
        group_marker = _owned_group_validation_marker(edge.owner, edge.comparison.group_rank)
        candidates: list[tuple[ast.Compare, ast.If]] = []
        for expression in facts.owned_expressions:
            if not isinstance(expression, ast.Compare) or len(expression.ops) != 1 or type(expression.ops[0]).__name__ != edge.comparison.operator or len(expression.comparators) != 1: continue
            left = _owned_value(facts, expression.left); right = _owned_value(facts, expression.comparators[0])
            if carrier_marker not in left.markers or f"{_OWNED_VALIDATION_PREFIX}{slot}.stage_{len(edge.carrier.validators) - 1}" not in left.markers or producer_marker not in right.markers or left.markers & all_producer_markers or right.markers & all_carrier_markers or not (left_bindings := frozenset(marker for marker in left.markers if ".binding_" in marker)) or left_bindings != frozenset(marker for marker in right.markers if ".binding_" in marker) or group_size > 1 and group_marker not in left.markers or left.unresolved or right.unresolved or left.overflow or right.overflow or left.deferred or right.deferred: continue
            scope = facts.scope_paths.get(id(expression), ()); reachable = reachability.get(edge.owner, frozenset())
            if not scope or scope[0] not in reachable: continue
            controls = facts.owned_controls.get(slot, ())
            if len(controls) == 1: candidates.append((expression, controls[0]))
        if unsafe_module_flow or not producer_formulas.get(edge.owner, False) or not reachability.get(edge.owner, frozenset()).isdisjoint(unsafe_flow_owners) or edge.producer not in producer_lines or len(candidates) != 1 or producer_lines.get(edge.producer, 1 << 62) >= candidates[0][1].lineno: findings.add(Finding("p2-owned-dataflow", detail)); continue
        comparison, control = candidates[0]
        declaration_line = comparison.lineno if facts.scope_paths.get(id(comparison)) == (edge.owner,) else control.lineno
        matched_order.setdefault((edge.owner, edge.comparison.group_rank), []).append((declaration_line, detail))
        function = functions.get(edge.failure.helper); calls = dispatch_calls.get(edge.failure.dispatcher, ())
        if function is None or not failure_shapes.get(edge.failure.helper) or not outcome_shape or type(predicate_paths) is not tuple or edge.failure.dispatcher_index >= len(predicate_paths) or predicate_paths[edge.failure.dispatcher_index] != edge.failure.path or edge.failure.dispatcher_index >= len(calls) or calls[edge.failure.dispatcher_index].targets != frozenset({f"{CANONICAL_MODULE}.{edge.owner}"}): findings.add(Finding("p2-owned-dataflow", detail))
    for owner in {edge.owner for _slot, edge in _owned_operation_items()}:
        groups = sorted(group for candidate, group in matched_order if candidate == owner)
        if groups and all(len(matched_order[(owner, group)]) == sum(edge.owner == owner and edge.comparison.group_rank == group for _slot, edge in _owned_operation_items()) for group in groups):
            lines = [min(item[0] for item in matched_order[(owner, group)]) for group in groups]
            if lines != sorted(lines): findings.update(Finding("p2-owned-dataflow", item[1]) for group in groups for item in matched_order[(owner, group)])
    return findings


def _p2_predicate_ownership_findings(facts: _SourceAnalysis) -> set[Finding]:
    findings: set[Finding] = set()
    functions = dict(facts.functions)
    analysis = facts.analysis
    projection_fields = frozenset(
        PROJECTION_FIELDS["CalibrationSourceObservationProjection"]
    )
    ownership = {
        owner: frozenset(
            step.value
            for _slot, edge in _owned_operation_items()
            if edge.owner == owner
            for step in edge.carrier.path
            if step.kind == "attribute" and step.value in projection_fields
        )
        for owner in {edge.owner for _slot, edge in _owned_operation_items()}
    }
    ownership["_predicate_3o_4_1"] = projection_fields
    failures = {
        edge.owner: edge.failure.helper for _slot, edge in _owned_operation_items()
    }
    for owner, failure_leaf in failures.items():
        function = functions.get(owner)
        if function is None:
            continue
        if not _p2_success_return_is_final(function, failure_leaf):
            findings.add(Finding("p2-predicate-ownership", f"{owner}:control-flow"))
        reachable, dynamic = _p2_reachable_functions(owner, functions, analysis)
        if dynamic:
            findings.add(Finding("p2-predicate-ownership", f"{owner}:dynamic-dispatch"))
        for terminal in sorted(reachable & _P2_COMPLETE_SOURCE_AUTHORITIES):
            findings.add(Finding("p2-predicate-ownership", f"{owner}:{terminal}"))
        for helper_name in reachable:
            for field in sorted(_p2_projection_field_references(functions[helper_name]) - ownership[owner]):
                findings.add(Finding("p2-predicate-ownership", f"{owner}:{field}"))
            if _p2_dynamic_projection_access(functions[helper_name]):
                findings.add(Finding("p2-predicate-ownership", f"{owner}:dynamic-field-access"))
        if any(_p2_broad_projection_equality(functions[name], facts) for name in reachable):
            findings.add(Finding("p2-predicate-ownership", f"{owner}:full-projection-equality"))
        nested_leaves = {ast.unparse(call.func).rsplit(".", 1)[-1] for nested in ast.walk(function) if nested is not function and isinstance(nested, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) for call in ast.walk(nested) if isinstance(call, ast.Call)}
        for leaf in sorted(nested_leaves & _P2_COMPLETE_SOURCE_AUTHORITIES):
            findings.add(Finding("p2-predicate-ownership", f"{owner}:{leaf}"))
        if _p2_try_relabels_complete_error(function, analysis, failure_leaf):
            findings.add(Finding("p2-predicate-ownership", f"{owner}:error-relabel"))
    findings.update(_p2_owned_dataflow_findings(facts))
    validator = functions.get("_validate_stage2f_p2")
    validator_calls = tuple(call for call in analysis.calls if call.scope == ("_validate_stage2f_p2",))
    loop_call_lines = frozenset(node.lineno for loop in validator.body for node in ast.walk(loop) if isinstance(loop, (ast.For, ast.AsyncFor)) and isinstance(node, ast.Call)) if validator is not None else frozenset()
    allowed_preflight_helpers = {"_validate_stage2f_p1", "_p2_outcome", "_oracle_binding_failure"}
    for call in validator_calls:
        if call.lineno in loop_call_lines:
            continue
        reachable, _dynamic = _p2_call_reachability(call, functions, analysis)
        local_roots = {target.rsplit(".", 1)[-1] for target in call.targets if target.startswith(f"{CANONICAL_MODULE}.")}
        if local_roots - allowed_preflight_helpers or reachable & _P2_COMPLETE_SOURCE_AUTHORITIES:
            findings.add(Finding("p2-predicate-ownership", "_validate_stage2f_p2:preflight"))
    if validator is not None and (
        _p2_broad_projection_equality(validator)
        or any(isinstance(node, ast.Attribute) and node.attr in PROJECTION_FIELDS["CalibrationSourceObservationProjection"] for statement in validator.body if not isinstance(statement, (ast.For, ast.AsyncFor)) for node in ast.walk(statement))
    ):
        findings.add(Finding("p2-predicate-ownership", "_validate_stage2f_p2:preflight"))
    if validator is not None:
        successes = tuple(node for node in ast.walk(validator) if isinstance(node, ast.Return) and not (isinstance(node.value, ast.Call) and ast.unparse(node.value.func).rsplit(".", 1)[-1] == "_p2_outcome") and not (isinstance(node.value, ast.Tuple) and node.value.elts and isinstance(node.value.elts[0], ast.Name) and node.value.elts[0].id == "p1_failure"))
        final_success = "(None, (*p1_counts, count_0, count_1, count_2, count_3))"
        if len(successes) != 1 or successes[0] is not validator.body[-1] or successes[0].value is None or ast.unparse(successes[0].value) != final_success:
            findings.add(Finding("p2-predicate-ownership", "_validate_stage2f_p2:preflight"))
    direct_complete = tuple(target.rsplit(".", 1)[-1] for call in validator_calls for target in call.targets if target.startswith(f"{CANONICAL_MODULE}.") and target.rsplit(".", 1)[-1] in _P2_COMPLETE_SOURCE_AUTHORITIES)
    if direct_complete.count("_predicate_3o_4_1") != 1 or any(name != "_predicate_3o_4_1" for name in direct_complete):
        findings.add(Finding("p2-predicate-ownership", "_validate_stage2f_p2:preflight"))
    return findings


def _p2_source_comparison_order(function: ast.FunctionDef) -> tuple[str, ...] | None:
    expected = PROJECTION_FIELDS["CalibrationSourceObservationProjection"]
    body = ["projection = _require_exact_source_observation_object(projection)"]
    for field in expected:
        if field == "key_fields":
            body.extend(("try:\n    key_fields = _source_key_fields(projection.key_fields)\nexcept ValueError:\n    return 'key_fields'", "if key_fields != expected.key_fields:\n    return 'key_fields'"))
        else:
            exact_type = "int" if field == "seed" else "str"
            body.append(f"if type(projection.{field}) is not {exact_type} or projection.{field} != expected.{field}:\n    return '{field}'")
    body.append("return None")
    return expected if tuple(map(ast.unparse, function.body)) == tuple(body) else None


def _p2_broad_projection_equality(function: ast.FunctionDef, facts: _SourceAnalysis | None = None) -> bool:
    receiver_names = _p2_projection_receivers(function)
    carrier_markers = frozenset(_owned_carrier_marker(slot, len(edge.carrier.path)) for slot, edge in _owned_operation_items())
    producer_markers = frozenset(_owned_comparison_marker(slot, len(edge.comparison.producer_path)) if edge.comparison.producer_path else _owned_producer_marker(edge.producer) for slot, edge in _owned_operation_items())
    return any(
        sum(_p2_projection_expression(expression, receiver_names) for expression in (node.left, *node.comparators)) >= 2
        and not (facts is not None and len(node.comparators) == 1 and _owned_value(facts, node.left).markers & carrier_markers and _owned_value(facts, node.comparators[0]).markers & producer_markers)
        for node in ast.walk(function) if isinstance(node, ast.Compare))


def _p2_source_order_findings(tree: ast.Module, functions: dict[str, ast.FunctionDef], analysis: qualified.QualifiedSymbolAnalysis) -> set[Finding]:
    finding = Finding("p2-source-comparison-order", "declaration-order")
    source_class = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "CalibrationSourceObservationProjection"), None)
    comparison = functions.get("_first_source_mismatch")
    predicate = functions.get("_predicate_3o_4_1")
    if source_class is None or comparison is None or predicate is None:
        return {finding}
    expected = _fields(source_class)
    if (
        expected != PROJECTION_FIELDS["CalibrationSourceObservationProjection"]
        or _p2_source_comparison_order(comparison) != expected
        or not _p2_success_return_is_final(predicate, "_source_observation_failure")
    ):
        return {finding}
    direct_calls = tuple(call for call in analysis.calls if call.scope == ("_predicate_3o_4_1",))
    reachability = tuple((call, *_p2_call_reachability(call, functions, analysis)) for call in direct_calls)
    if any(dynamic for _call, _reachable, dynamic in reachability):
        return {finding}
    authorities = (("_first_source_mismatch", {"_first_source_mismatch"}), ("_validate_complete_source_observation_surface", {"_validate_complete_source_observation_surface"}), ("source_observation_identity", {"source_observation_identity", "_source_observation_matches"}))
    positions = {name: [call.lineno for call, reachable, _dynamic in reachability if reachable & terminals] for name, terminals in authorities}
    comparison_lines, complete_lines, identity_lines = (positions.get(name, []) for name in ("_first_source_mismatch", "_validate_complete_source_observation_surface", "source_observation_identity"))
    if tuple(map(len, (comparison_lines, complete_lines, identity_lines))) != (1, 1, 1) or not comparison_lines[0] < complete_lines[0] < identity_lines[0] or _p2_broad_projection_equality(predicate):
        return {finding}
    loops = tuple(node for node in predicate.body if isinstance(node, ast.For))
    if len(loops) != 2 or any(ast.unparse(loop.iter) != "range(10)" for loop in loops):
        return {finding}
    required_calls = (
        ("_first_source_mismatch", ("evidence[0]", "expected_projection"), ("Assign", "Try", "For", "FunctionDef")),
        ("_validate_complete_source_observation_surface", ("projection",), ("Expr", "Try", "For", "FunctionDef")),
        ("_source_observation_matches", ("projection", "carried_identity"), ("Assign", "Try", "For", "FunctionDef")),
    )
    if any(len(calls := _p2_named_calls(predicate, leaf)) != 1 or tuple(map(ast.unparse, calls[0].args)) != args or calls[0].keywords or _p2_call_ancestry(predicate, calls[0]) != context for leaf, args, context in required_calls):
        return {finding}
    complete_call = _p2_named_calls(predicate, "_validate_complete_source_observation_surface")[0]
    complete_try = next(node for node in ast.walk(predicate) if isinstance(node, ast.Try) and any(candidate is complete_call for candidate in ast.walk(node)))
    expected_complete_try = "try:\n    _validate_complete_source_observation_surface(projection)\nexcept (AttributeError, TypeError, ValueError):\n    return _source_observation_failure(f'source observation[{observation_index}] strict reconstruction failed')"
    if ast.unparse(complete_try) != expected_complete_try:
        return {finding}
    first_loop_index = predicate.body.index(loops[0])
    carried_assignments = tuple(ast.unparse(node) for node in sorted((node for node in ast.walk(loops[0]) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "carried_identity" for target in node.targets)), key=lambda node: node.lineno))
    accumulation = tuple(node for node in ast.walk(loops[0]) if isinstance(node, ast.Assign) and ast.unparse(node) == "identities = (*identities, carried_identity)")
    allowed_identity_uses = {id(node) for node in ast.walk(accumulation[0])} if len(accumulation) == 1 else set()
    uniqueness = "for observation_index in range(10):\n    for earlier_index in range(observation_index):\n        if identities[observation_index] == identities[earlier_index]:\n            return _source_observation_failure(f'source observation identity[{observation_index}] is duplicated')"
    if (
        first_loop_index == 0
        or ast.unparse(predicate.body[first_loop_index - 1]) != "identities: tuple[str, ...] = ()"
        or predicate.body[first_loop_index + 1] is not loops[1]
        or carried_assignments != ("carried_identity = evidence[1]", "carried_identity = _exact_h64(carried_identity, 'source_observation_identity')")
        or len(accumulation) != 1
        or any(id(node) not in allowed_identity_uses for node in ast.walk(loops[0]) if isinstance(node, ast.Name) and node.id == "identities")
        or ast.unparse(loops[1]) != uniqueness
        or loops[0].lineno >= loops[1].lineno
    ):
        return {finding}
    return set()


def _p2_complete_source_surface_is_exact(functions: dict[str, ast.FunctionDef]) -> bool:
    function = functions.get("_validate_complete_source_observation_surface")
    return function is not None and tuple(map(ast.unparse, function.body)) == (
        "projection = _require_exact_source_observation_object(value)",
        "mapping = _calibration_source_observation_mapping(projection)",
        "decoded = _decode_calibration_source_observation_projection(mapping)",
        "if decoded != projection:\n    _reject('source_observation', 'projection does not exactly reconstruct')",
        "return mapping",
    )


def _p2_complete_authority_findings(functions: dict[str, ast.FunctionDef], analysis: qualified.QualifiedSymbolAnalysis) -> set[Finding]:
    expected_callers = {
        "_calibration_source_observation_mapping": {("_source_observation_preimage",), ("_validate_complete_source_observation_surface",), ("CalibrationSourceObservationProjection", "__post_init__")},
        "_decode_calibration_source_observation_projection": {("_source_observation_preimage",), ("_validate_complete_source_observation_surface",)},
        "_validate_complete_source_observation_surface": {("_predicate_3o_4_1",)},
        "_source_observation_preimage": {("source_observation_identity",)},
    }
    for authority, expected in expected_callers.items():
        target = f"{CANONICAL_MODULE}.{authority}"
        observed = {call.scope for call in analysis.calls if target in call.targets}
        if observed != expected:
            return {Finding("p2-complete-source-authority", authority)}
    if not _p2_complete_source_surface_is_exact(functions):
        return {Finding("p2-complete-source-authority", "_validate_complete_source_observation_surface")}
    return set()


def _p2_eager_nodes(node: ast.AST) -> tuple[ast.AST, ...]:
    if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "_TYPE_CHECKING":
        return ()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        expressions = (*node.args.defaults, *(item for item in node.args.kw_defaults if item is not None), *(node.decorator_list if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else ()))
        return (node, *(descendant for expression in expressions for descendant in _p2_eager_nodes(expression)))
    return (node, *(descendant for child in ast.iter_child_nodes(node) for descendant in _p2_eager_nodes(child)))


def _p2_performance_findings(tree: ast.Module, functions: dict[str, ast.FunctionDef]) -> set[Finding]:
    finding = Finding("p2-performance-invariant", "cold-minimal")
    p3_active = any(
        isinstance(node, ast.ClassDef)
        and node.name == "ScientificCalibrationSelectionProjection"
        for node in tree.body
    )
    heavy_modules = set() if p3_active else {_HISTORY, _ORACLE, _REPLAY, _RETURNED}
    eager = _p2_eager_nodes(tree)
    stores = {node.id for node in eager if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
    critical = {"_TYPE_CHECKING", "_protocol_hash", "range", "tuple", "type", "_dataclass", "_require_exact_source_observation_object", "_validate_source_observation_key_surface", "_validate_source_observation_outcome_surface", "_validate_complete_source_observation_surface", "_calibration_source_observation_mapping", "_decode_calibration_source_observation_projection", "_source_observation_preimage", "source_observation_identity", "_oracle_key_id", "_outcome_digest", "_expected_observation_f64", "_first_source_mismatch", "_source_observation_matches"}
    if (
        any(isinstance(node, ast.ImportFrom) and node.module in heavy_modules or isinstance(node, ast.Import) and any(alias.name in heavy_modules for alias in node.names) for node in eager)
        or stores & critical
        or any(any(token in name.lower() for token in ("cache", "memo")) for name in stores)
        or any(isinstance(node, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)) or isinstance(node, ast.Call) and ast.unparse(node.func).rsplit(".", 1)[-1] in {"list", "dict", "set"} for node in eager)
        or any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any("cache" in ast.unparse(decorator).lower() for decorator in node.decorator_list) for node in tree.body)
        or any(ast.unparse(node.func).rsplit(".", 1)[-1] not in {"tuple", "_dataclass"} for node in eager if isinstance(node, ast.Call))
    ):
        return {finding}
    protected = {"source_observation_identity", "_source_observation_preimage", "_validate_complete_source_observation_surface", "_calibration_source_observation_mapping", "_decode_calibration_source_observation_projection"}
    if (
        "source_observation_identity" not in functions
        or "_source_observation_preimage" not in functions
        or not _p2_source_identity_is_exact(functions)
        or not _p2_complete_source_surface_is_exact(functions)
        or any(name in functions and functions[name].decorator_list for name in protected)
        or any(isinstance(node, ast.Call) and (ast.unparse(node.func).rsplit(".", 1)[-1] in {"__import__", "import_module", "getenv", "exec", "eval"} or ast.unparse(node.func).rsplit(".", 1)[-1] == "getattr" and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and node.args[1].value in {"__import__", "import_module"}) or isinstance(node, ast.Attribute) and node.attr == "environ" for node in ast.walk(tree))
    ):
        return {finding}
    return set()


def _active_p2_internal_findings_with_session(
    source: str,
    session: _AnalysisSession,
) -> set[Finding]:
    try:
        facts = session.source_analysis(source, module_name=CANONICAL_MODULE, owned=True)
    except SyntaxError:
        return {Finding("invalid-production-syntax", CANONICAL_MODULE)}
    tree = facts.tree
    functions = dict(facts.functions)
    analysis = facts.analysis
    findings: set[Finding] = set()
    findings.update(_p2_owned_function_authority_findings(facts)); findings.update(_p2_owned_terminal_authority_findings(facts))
    source_class = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "CalibrationSourceObservationProjection"), None)
    if source_class is None or not _p1_projection_shape_is_exact(source_class, None):
        findings.add(Finding("p2-source-projection-shape", "CalibrationSourceObservationProjection"))
    if not _p2_source_codec_is_exact(functions):
        findings.add(Finding("p2-source-codec", "declaration-order"))
    if not _p2_source_identity_is_exact(functions):
        findings.add(Finding("p2-source-identity", "preimage"))
    if not _p2_schedule_is_exact(functions):
        findings.add(Finding("p2-schedule", "predicate-family-major"))
    findings.update(_p2_predicate_ownership_findings(facts))
    findings.update(_p2_source_order_findings(tree, functions, analysis))
    findings.update(_p2_complete_authority_findings(functions, analysis))
    findings.update(_p2_performance_findings(tree, functions))
    for name in sorted(_names("_predicate_3o_2_0 _predicate_3o_2_1 _predicate_3o_3_1 _predicate_3o_4_1 _validate_stage2f_p2") - functions.keys()):
        findings.add(Finding("p2-required-function", name))
    helper_calls = {
        f"{_ORACLE}._parse_calibration_candidate": "_parse_calibration_candidate",
        f"{_ORACLE}.calibration_key": "_calibration_key",
        f"{_ORACLE}.transform_key": "_transform_key",
        f"{_PROTOCOL}.f64": "_f64",
        f"{_WORLDS}.hidden_arm_mean": "_hidden_arm_mean",
        f"{_WORLDS}.hidden_observation_sigma": "_hidden_observation_sigma",
    }
    observed_calls = frozenset(ast.unparse(call.func) for call in ast.walk(tree) if isinstance(call, ast.Call))
    for target, local in helper_calls.items():
        if local not in observed_calls:
            findings.add(Finding("p2-required-pure-helper", target))
    expected_paths = ("calibration/3o.2.0/oracle_binding", "calibration/3o.2.1/oracle_key", "calibration/3o.3.1/outcome", "calibration/3o.4.1/source_observation")
    assigned = _assigned_literals(tree)
    if assigned.get("_P2_PREDICATE_PATHS") != expected_paths:
        findings.add(Finding("p2-failure-paths", "ordered-paths"))
    expected_codes = _names("CALIBRATION_ORACLE_BINDING_MISMATCH CALIBRATION_ORACLE_KEY_ID_MISMATCH CALIBRATION_OUTCOME_DIGEST_MISMATCH CALIBRATION_SOURCE_OBSERVATION_ID_MISMATCH")
    if not expected_codes <= _strings(tree):
        findings.add(Finding("p2-failure-codes", "complete-set"))
    return findings


def _active_p2_internal_findings(source: str) -> set[Finding]:
    return _active_p2_internal_findings_with_session(source, _AnalysisSession())


_P3_INPUT_FIELDS: Final = (
    ("returned_result_id", "str"),
    ("returned_run_projection", "_ReturnedRunProjection"),
    ("submitted_job_id", "str"),
    (
        "selector_result_projection",
        "ScientificCalibrationSelectionProjection",
    ),
    ("selector_result_identity", "str"),
)
_P3_HISTORY_NONIDENTITY_FIELDS: Final = (
    "study_id",
    "world_id",
    "seed",
    "namespace",
    "comparison_group_id",
    "target_comparison_group_id",
    "source_sequence_cutoff",
    "source_effect_ids",
    "source_effect_payload_sha256",
    "source_observation_identities",
    "source_oracle_key_ids",
    "source_candidate_pairs",
    "source_replication_ids",
    "effect_values",
    "sample_count",
    "sample_mean",
    "sample_standard_deviation",
    "ddof",
    "sigma_floor",
    "estimated_sigma",
    "physical_cost",
    "eligibility_basis",
    "current_observation_excluded",
    "current_effect_excluded",
    "future_history_excluded",
    "effects",
    "observations",
)
_P3_OBSERVATION_FIELDS: Final = (
    "oracle_key_id",
    "oracle_use_id",
    "authorization_id",
    "namespace",
    "world_id",
    "seed",
    "candidate_id",
    "comparison_group_id",
    "intervention_arm",
    "replication_id",
    "key_fields",
    "serialized_key_hex",
    "digest",
    "u",
    "z",
    "revealed_observation",
    "outcome_digest",
)
_P3_EFFECT_FIELDS: Final = (
    "effect_id",
    "comparison_group_id",
    "observed_effect",
    "available_sequence",
    "source_kind",
    "source_ids",
    "created_at",
    "provenance",
)
_P3_WITNESS_LITERALS: Final = (
    "budget-2.25",
    "f64:4002000000000000",
    "calibrated_ig",
    "replicated_noise_calibrated_gaussian",
    "information_gain",
)


def _p3_function_signature_is_exact(
    function: ast.FunctionDef | None,
    *,
    positional: tuple[tuple[str, str], ...],
    keyword_only: tuple[tuple[str, str], ...],
    returns: str,
) -> bool:
    if (
        function is None
        or function.decorator_list
        or function.args.posonlyargs
        or function.args.defaults
        or any(default is not None for default in function.args.kw_defaults)
        or function.args.vararg is not None
        or function.args.kwarg is not None
        or function.type_params
        or function.type_comment is not None
        or tuple(argument.arg for argument in function.args.args)
        != tuple(name for name, _annotation in positional)
        or tuple(argument.arg for argument in function.args.kwonlyargs)
        != tuple(name for name, _annotation in keyword_only)
    ):
        return False
    annotations = tuple(
        ast.unparse(argument.annotation) if argument.annotation is not None else None
        for argument in (*function.args.args, *function.args.kwonlyargs)
    )
    return bool(
        annotations
        == tuple(annotation for _name, annotation in (*positional, *keyword_only))
        and function.returns is not None
        and ast.unparse(function.returns) == returns
    )


def _p3_private_input_is_exact(
    class_node: ast.ClassDef | None,
    analysis: qualified.QualifiedSymbolAnalysis,
) -> bool:
    if (
        class_node is None
        or class_node.bases
        or class_node.keywords
        or len(class_node.decorator_list) != 1
        or len(class_node.body) != len(_P3_INPUT_FIELDS)
    ):
        return False
    decorator = class_node.decorator_list[0]
    reference_targets = {
        (reference.lineno, reference.spelling): reference.targets
        for reference in analysis.references
    }
    if (
        not isinstance(decorator, ast.Call)
        or decorator.args
        or reference_targets.get(
            (decorator.func.lineno, ast.unparse(decorator.func))
        )
        != frozenset({"dataclasses.dataclass"})
        or {
            keyword.arg: keyword.value.value
            if isinstance(keyword.value, ast.Constant)
            else None
            for keyword in decorator.keywords
        }
        != {"frozen": True, "slots": True}
    ):
        return False
    fields = tuple(class_node.body)
    return all(
        isinstance(field, ast.AnnAssign)
        and isinstance(field.target, ast.Name)
        and field.target.id == name
        and field.value is None
        and field.simple == 1
        and ast.unparse(field.annotation) == annotation
        for field, (name, annotation) in zip(fields, _P3_INPUT_FIELDS, strict=True)
    )


def _p3_direct_attribute_order(
    function: ast.FunctionDef | None,
    base: str,
    expected: tuple[str, ...],
) -> bool:
    if function is None:
        return False
    positions: dict[str, tuple[int, int]] = {}
    for node in ast.walk(function):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == base
            and node.attr in expected
        ):
            positions.setdefault(node.attr, (node.lineno, node.col_offset))
    return bool(
        frozenset(positions) == frozenset(expected)
        and tuple(sorted(positions, key=positions.__getitem__)) == expected
    )


def _p3_static_truth(node: ast.AST) -> tuple[bool, bool]:
    try:
        return True, bool(ast.literal_eval(node))
    except (ValueError, TypeError):
        return False, False


def _p3_statement_never_falls_through(node: ast.stmt) -> bool:
    if isinstance(node, (ast.Break, ast.Continue, ast.Raise, ast.Return)):
        return True
    if isinstance(node, ast.If):
        known, truth = _p3_static_truth(node.test)
        if known:
            selected = node.body if truth else node.orelse
            return bool(selected and _p3_statement_never_falls_through(selected[-1]))
        return bool(
            node.body
            and node.orelse
            and _p3_statement_never_falls_through(node.body[-1])
            and _p3_statement_never_falls_through(node.orelse[-1])
        )
    return False


def _p3_node_is_statically_reachable(
    facts: _SourceAnalysis,
    node: ast.AST,
    function: ast.FunctionDef,
) -> bool:
    child = node
    ancestor = facts.parents.get(id(node))
    while ancestor is not None:
        if isinstance(ancestor, (ast.AsyncFunctionDef, ast.FunctionDef, ast.Lambda)) and ancestor is not function:
            return False
        if isinstance(ancestor, ast.If):
            known, truth = _p3_static_truth(ancestor.test)
            if known and (
                child in ancestor.body
                and not truth
                or child in ancestor.orelse
                and truth
            ):
                return False
        elif isinstance(ancestor, ast.IfExp):
            known, truth = _p3_static_truth(ancestor.test)
            if known and (
                child is ancestor.body
                and not truth
                or child is ancestor.orelse
                and truth
            ):
                return False
        elif isinstance(ancestor, ast.BoolOp):
            position = next(
                (
                    index
                    for index, value in enumerate(ancestor.values)
                    if value is child
                ),
                None,
            )
            if position is not None:
                prior = tuple(_p3_static_truth(value) for value in ancestor.values[:position])
                if isinstance(ancestor.op, ast.And) and any(
                    known and not truth for known, truth in prior
                ):
                    return False
                if isinstance(ancestor.op, ast.Or) and any(
                    known and truth for known, truth in prior
                ):
                    return False
        elif isinstance(ancestor, ast.While):
            known, truth = _p3_static_truth(ancestor.test)
            if known and not truth and child in ancestor.body:
                return False
        for _field, value in ast.iter_fields(ancestor):
            if (
                isinstance(value, list)
                and child in value
                and all(isinstance(item, ast.stmt) for item in value)
            ):
                position = value.index(child)
                if any(
                    _p3_statement_never_falls_through(statement)
                    for statement in value[:position]
                ):
                    return False
        if ancestor is function:
            return True
        child = ancestor
        ancestor = facts.parents.get(id(ancestor))
    return False


def _p3_live_direct_attribute_order(
    facts: _SourceAnalysis,
    function: ast.FunctionDef | None,
    base: str,
    expected: tuple[str, ...],
) -> bool:
    if not _p3_direct_attribute_order(function, base, expected) or function is None:
        return False
    attributes = tuple(
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == base
        and node.attr in expected
    )
    return bool(
        frozenset(node.attr for node in attributes) == frozenset(expected)
        and all(
            _p3_node_is_statically_reachable(facts, node, function)
            for node in attributes
        )
    )


def _p3_direct_control(
    facts: _SourceAnalysis,
    node: ast.AST,
    decision_marker: str,
) -> ast.If | None:
    scope = facts.scope_paths.get(id(node), ())
    function = facts.functions.get(scope[0]) if len(scope) == 1 else None
    if function is None:
        return None
    child = node
    ancestor = facts.parents.get(id(node))
    while ancestor is not None and not isinstance(
        ancestor, (ast.AsyncFunctionDef, ast.FunctionDef)
    ):
        if isinstance(ancestor, ast.If):
            test_value = _owned_value(facts, ancestor.test)
            return (
                ancestor
                if child in ancestor.body
                and _p3_node_is_statically_reachable(facts, ancestor, function)
                and decision_marker in test_value.markers
                and not test_value.unresolved
                else None
            )
        if isinstance(
            ancestor,
            (
                ast.AsyncFor,
                ast.AsyncWith,
                ast.For,
                ast.Match,
                ast.Try,
                ast.TryStar,
                ast.While,
                ast.With,
            ),
        ):
            return None
        child = ancestor
        ancestor = facts.parents.get(id(ancestor))
    return None


def _p3_return_is_certified(
    facts: _SourceAnalysis,
    node: ast.Return,
    *,
    scope: tuple[str, ...],
    decision_marker: str,
    result_markers: frozenset[str],
) -> ast.If | None:
    function = facts.functions.get(scope[0]) if len(scope) == 1 else None
    if (
        node.value is None
        or function is None
        or facts.scope_paths.get(id(node)) != scope
        or not _p3_node_is_statically_reachable(facts, node, function)
    ):
        return None
    value = _owned_value(facts, node.value)
    if not result_markers <= value.markers:
        return None
    return _p3_direct_control(facts, node, decision_marker)


def _p3_validator_control_has_canonical_loop(
    facts: _SourceAnalysis,
    control: ast.If,
) -> bool:
    validator = facts.functions.get("_validate_stage2f_p3")
    if validator is None:
        return False
    ancestor = facts.parents.get(id(control))
    while ancestor is not None and not isinstance(
        ancestor, (ast.AsyncFunctionDef, ast.FunctionDef)
    ):
        if isinstance(ancestor, ast.For):
            iterator = ancestor.iter
            return bool(
                _p3_node_is_statically_reachable(facts, ancestor, validator)
                and not ancestor.orelse
                and isinstance(ancestor.target, ast.Name)
                and ancestor.target.id == "selection_index"
                and isinstance(iterator, ast.Call)
                and isinstance(iterator.func, ast.Name)
                and iterator.func.id == "range"
                and len(iterator.args) == 1
                and not iterator.keywords
                and isinstance(iterator.args[0], ast.Name)
                and iterator.args[0].id == "_CANONICAL_SELECTION_COUNT"
            )
        if isinstance(
            ancestor,
            (
                ast.AsyncFor,
                ast.AsyncWith,
                ast.If,
                ast.Match,
                ast.Try,
                ast.TryStar,
                ast.While,
                ast.With,
            ),
        ):
            return False
        ancestor = facts.parents.get(id(ancestor))
    return False


def _p3_failure_flow_findings(facts: _SourceAnalysis) -> set[Finding]:
    findings: set[Finding] = set()
    certified_returns: tuple[tuple[ast.Return, ast.If], ...] = ()
    functions = dict(facts.functions)
    history_helper = functions.get("_first_history_nonidentity_mismatch")
    predicate = functions.get("_predicate_3o_5_1")
    b_entry_calls = (
        tuple(
            node
            for node in ast.walk(predicate)
            if isinstance(node, ast.Call)
            and _P3_B_RESULT_MARKER in _owned_value(facts, node).markers
            and _P3_SELECTOR_FAILURE_MARKER not in _owned_value(facts, node).markers
            and _p3_node_is_statically_reachable(facts, node, predicate)
        )
        if predicate is not None
        else ()
    )
    if len(b_entry_calls) != 1 or not _p3_live_direct_attribute_order(
        facts,
        history_helper,
        "actual",
        _P3_HISTORY_NONIDENTITY_FIELDS,
    ):
        findings.add(Finding("p3-b-validation-flow", "fields-1-27"))

    predicate_flow_is_exact = predicate is not None
    if predicate is not None:
        for result_marker, decision_marker in (
            (_P3_B_RESULT_MARKER, _P3_B_DECISION_MARKER),
            (_P3_H_RESULT_MARKER, _P3_H_DECISION_MARKER),
        ):
            calls = tuple(
                node
                for node in ast.walk(predicate)
                if isinstance(node, ast.Call)
                and result_marker in _owned_value(facts, node).markers
                and _p3_node_is_statically_reachable(facts, node, predicate)
            )
            comparisons = tuple(
                node
                for node in ast.walk(predicate)
                if isinstance(node, ast.Compare)
                and decision_marker in _owned_value(facts, node).markers
                and _p3_node_is_statically_reachable(facts, node, predicate)
            )
            failure_calls = tuple(
                node
                for node in ast.walk(predicate)
                if isinstance(node, ast.Call)
                and {
                    result_marker,
                    _P3_SELECTOR_FAILURE_MARKER,
                }
                <= _owned_value(facts, node).markers
                and _p3_node_is_statically_reachable(facts, node, predicate)
            )
            certified_returns = tuple(
                (node, control)
                for node in ast.walk(predicate)
                if isinstance(node, ast.Return)
                and (
                    control := _p3_return_is_certified(
                        facts,
                        node,
                        scope=("_predicate_3o_5_1",),
                        decision_marker=decision_marker,
                        result_markers=frozenset(
                            {result_marker, _P3_SELECTOR_FAILURE_MARKER}
                        ),
                    )
                )
                is not None
            )
            predicate_flow_is_exact = bool(
                predicate_flow_is_exact
                and len(calls) == 2
                and len(comparisons) == 1
                and len(failure_calls) == 1
                and len(certified_returns) == 1
            )
    if not predicate_flow_is_exact:
        findings.add(Finding("p3-b-mismatch-flow", "B-H-failure-return"))

    validator = functions.get("_validate_stage2f_p3")
    validator_flow_is_exact = validator is not None
    if validator is not None:
        predicate_calls = tuple(
            node
            for node in ast.walk(validator)
            if isinstance(node, ast.Call)
            and _P3_PREDICATE_RESULT_MARKER in _owned_value(facts, node).markers
            and _P3_OUTCOME_MARKER not in _owned_value(facts, node).markers
            and _p3_node_is_statically_reachable(facts, node, validator)
        )
        comparisons = tuple(
            node
            for node in ast.walk(validator)
            if isinstance(node, ast.Compare)
            and _P3_PREDICATE_DECISION_MARKER
            in _owned_value(facts, node).markers
            and _p3_node_is_statically_reachable(facts, node, validator)
        )
        outcome_calls = tuple(
            node
            for node in ast.walk(validator)
            if isinstance(node, ast.Call)
            and _P3_OUTCOME_MARKER in _owned_value(facts, node).markers
            and _p3_node_is_statically_reachable(facts, node, validator)
        )
        certified_returns = tuple(
            (node, control)
            for node in ast.walk(validator)
            if isinstance(node, ast.Return)
            and (
                control := _p3_return_is_certified(
                    facts,
                    node,
                    scope=("_validate_stage2f_p3",),
                    decision_marker=_P3_PREDICATE_DECISION_MARKER,
                    result_markers=frozenset({_P3_OUTCOME_MARKER}),
                )
            )
            is not None
        )
        validator_flow_is_exact = bool(
            validator_flow_is_exact
            and len(predicate_calls) == 1
            and len(comparisons) == 1
            and len(outcome_calls) == 1
            and len(certified_returns) == 1
            and _p3_validator_control_has_canonical_loop(
                facts, certified_returns[0][1]
            )
        )
    if not validator_flow_is_exact:
        findings.add(Finding("p3-validator-failure-flow", "predicate-failure-stop"))
    return findings


def _p3_projection_codec_is_exact(
    functions: dict[str, ast.FunctionDef],
) -> bool:
    mapper = functions.get("_scientific_calibration_selection_mapping")
    decoder = functions.get("_decode_scientific_calibration_selection_projection")
    if mapper is None or decoder is None:
        return False
    expected = PROJECTION_FIELDS["ScientificCalibrationSelectionProjection"]
    mapper_return = next(
        (node for node in reversed(mapper.body) if isinstance(node, ast.Return)),
        None,
    )
    decoder_returns = tuple(
        node
        for node in ast.walk(decoder)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Call)
        and _call_leaf(node.value) == "ScientificCalibrationSelectionProjection"
    )
    closed_calls = tuple(
        node
        for node in ast.walk(decoder)
        if isinstance(node, ast.Call) and _call_leaf(node) == "_closed_mapping"
    )
    if (
        mapper_return is None
        or not isinstance(mapper_return.value, ast.Dict)
        or tuple(
            key.value if isinstance(key, ast.Constant) else None
            for key in mapper_return.value.keys
        )
        != expected
        or len(decoder_returns) != 1
        or len(closed_calls) != 1
    ):
        return False
    constructor = cast(ast.Call, decoder_returns[0].value)
    closed = closed_calls[0]
    return bool(
        not constructor.args
        and tuple(keyword.arg for keyword in constructor.keywords) == expected
        and ast.unparse(closed)
        == "_closed_mapping(value, _SCIENTIFIC_SELECTION_FIELDS, 'scientific_selection')"
        and not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
            for statement in decoder.body
            for node in ast.walk(statement)
            if node is not decoder
        )
        and not any(
            isinstance(node, ast.Call)
            and _call_leaf(node) in {"dict", "getattr", "hasattr", "vars"}
            for node in (*ast.walk(mapper), *ast.walk(decoder))
        )
    )


def _p3_call_keywords(
    function: ast.FunctionDef, leaf: str,
) -> tuple[tuple[str | None, ...], ...]:
    return tuple(
        tuple(keyword.arg for keyword in call.keywords)
        for call in ast.walk(function)
        if isinstance(call, ast.Call) and _call_leaf(call) == leaf
    )


def _p3_assignment_dependencies(
    function: ast.FunctionDef,
    root: str,
) -> frozenset[str]:
    assignments: dict[str, set[str]] = {}
    for node in ast.walk(function):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        targets = tuple(node.targets) if isinstance(node, ast.Assign) else (node.target,)
        names = {
            item.id
            for item in ast.walk(node.value)
            if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)
        }
        for target in targets:
            if isinstance(target, ast.Name):
                assignments.setdefault(target.id, set()).update(names)
    reached = {root}
    for _ in range(len(assignments) + 1):
        expanded = reached | {
            dependency
            for name in reached
            for dependency in assignments.get(name, set())
        }
        if expanded == reached:
            break
        reached = expanded
    return frozenset(reached)


def _p3_raw_hash_sites(
    tree: ast.Module,
    analysis: qualified.QualifiedSymbolAnalysis,
) -> frozenset[tuple[int, str]]:
    predicate = _top_level_function(tree, "_predicate_3o_5_1")
    if predicate is None:
        return frozenset()
    call_targets = {
        (call.lineno, call.spelling): call.targets for call in analysis.calls
    }
    byte_assignments = tuple(
        node
        for node in ast.walk(predicate)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "effect_payload_bytes"
        and isinstance(node.value, ast.Call)
        and call_targets.get((node.value.lineno, ast.unparse(node.value.func)))
        == frozenset({f"{_PROTOCOL}.canonical_json_bytes"})
        and len(node.value.args) == 1
        and isinstance(node.value.args[0], ast.Call)
        and isinstance(node.value.args[0].func, ast.Attribute)
        and node.value.args[0].func.attr == "to_dict"
        and isinstance(node.value.args[0].func.value, ast.Name)
        and node.value.args[0].func.value.id == "expected_effect"
        and not node.value.args[0].args
        and not node.value.args[0].keywords
        and len(node.value.keywords) == 1
        and node.value.keywords[0].arg == "final_lf"
        and isinstance(node.value.keywords[0].value, ast.Constant)
        and node.value.keywords[0].value.value is True
    )
    digest_assignments = tuple(
        node
        for node in ast.walk(predicate)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "effect_payload_sha256"
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "hexdigest"
        and not node.value.args
        and not node.value.keywords
        and isinstance(node.value.func.value, ast.Call)
        and call_targets.get(
            (
                node.value.func.value.lineno,
                ast.unparse(node.value.func.value.func),
            )
        )
        == frozenset({"hashlib.sha256"})
        and len(node.value.func.value.args) == 1
        and isinstance(node.value.func.value.args[0], ast.Name)
        and node.value.func.value.args[0].id == "effect_payload_bytes"
        and not node.value.func.value.keywords
    )
    if (
        len(byte_assignments) != 1
        or len(digest_assignments) != 1
        or byte_assignments[0].lineno >= digest_assignments[0].lineno
    ):
        return frozenset()
    digest = digest_assignments[0].value
    assert isinstance(digest, ast.Call)
    assert isinstance(digest.func, ast.Attribute)
    sha_call = digest.func.value
    assert isinstance(sha_call, ast.Call)
    return frozenset(
        {
            (digest.lineno, ast.unparse(digest.func)),
            (sha_call.lineno, ast.unparse(sha_call.func)),
        }
    )


def _p3_approved_external_call_sites(
    tree: ast.Module,
    analysis: qualified.QualifiedSymbolAnalysis,
) -> frozenset[tuple[int, str]]:
    predicate = _top_level_function(tree, "_predicate_3o_5_1")
    raw_hash_sites = _p3_raw_hash_sites(tree, analysis)
    if (
        predicate is None
        or not _p3_witness_is_exact(predicate)
        or not _p3_reconstruction_is_exact(predicate, raw_hash_sites)
    ):
        return frozenset()
    approved: set[tuple[int, str]] = set(raw_hash_sites)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    decoder = functions.get("_decode_scientific_calibration_selection_projection")
    if _p3_projection_codec_is_exact(functions) and decoder is not None:
        approved.update(
            (call.lineno, ast.unparse(call.func))
            for call in ast.walk(decoder)
            if isinstance(call, ast.Call)
            and ast.unparse(call) == "dict.keys(value)"
        )
    for call in ast.walk(predicate):
        if not isinstance(call, ast.Call):
            continue
        site = (call.lineno, ast.unparse(call.func))
        if (
            (
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "replay_run_id"
                and call.func.attr == "strip"
                and not call.args
                and not call.keywords
            )
            or (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "hex"
                and isinstance(call.func.value, ast.Attribute)
                and isinstance(call.func.value.value, ast.Name)
                and call.func.value.value.id == "transform"
                and call.func.value.attr == "serialized_key"
                and not call.args
                and not call.keywords
            )
            or _call_leaf(call)
            in {
                "_RevealedObservation",
                "_RunObservationAuthorizationProjection",
            }
        ):
            approved.add(site)
    return frozenset(approved)


def _p3_approved_runtime_id_sites(
    tree: ast.Module,
    analysis: qualified.QualifiedSymbolAnalysis,
    approved_external: frozenset[tuple[int, str]] | None = None,
) -> frozenset[tuple[int, str]]:
    predicate = _top_level_function(tree, "_predicate_3o_5_1")
    if approved_external is None:
        approved_external = _p3_approved_external_call_sites(tree, analysis)
    if predicate is None or not approved_external:
        return frozenset()
    return frozenset(
        (call.lineno, ast.unparse(call.func))
        for call in ast.walk(predicate)
        if isinstance(call, ast.Call)
        and _call_leaf(call) == "_runtime_id"
        and len(call.args) == 3
        and not call.keywords
        and isinstance(call.args[0], ast.Constant)
        and call.args[0].value == "authorization"
        and isinstance(call.args[1], ast.Constant)
        and call.args[1].value == "authorization_id/v1"
        and isinstance(call.args[2], ast.Dict)
        and tuple(
            key.value if isinstance(key, ast.Constant) else None
            for key in call.args[2].keys
        )
        == ("candidate_id", "kind", "run_id", "source_id")
    )


def _p3_schedule_is_exact(
    functions: dict[str, ast.FunctionDef],
    analysis: qualified.QualifiedSymbolAnalysis,
) -> bool:
    validator = functions.get("_validate_stage2f_p3")
    if validator is None:
        return False
    calls = tuple(
        call
        for call in analysis.calls
        if call.scope == ("_validate_stage2f_p3",)
    )
    p2_calls = tuple(
        call
        for call in calls
        if call.targets == frozenset({f"{CANONICAL_MODULE}._validate_stage2f_p2"})
    )
    p3_calls = tuple(
        call
        for call in calls
        if call.targets == frozenset({f"{CANONICAL_MODULE}._predicate_3o_5_1"})
    )
    loops = tuple(node for node in validator.body if isinstance(node, ast.For))
    expected_arguments = (
        "selections[selection_index]",
        "p2_selections[selection_index]",
        "expected_predecessors[selection_index]",
        "expected_execution_attestation_pairs",
        "attested_execution_specification_ids",
        "validated_returned_results_by_role",
        "p3_inputs[selection_index]",
        "selection_index",
    )
    predicate_node = next(
        (
            node
            for node in ast.walk(validator)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_predicate_3o_5_1"
        ),
        None,
    )
    return bool(
        len(p2_calls) == len(p3_calls) == len(loops) == 1
        and p2_calls[0].lineno < loops[0].lineno <= p3_calls[0].lineno
        and isinstance(loops[0].target, ast.Name)
        and loops[0].target.id == "selection_index"
        and ast.unparse(loops[0].iter) == "range(_CANONICAL_SELECTION_COUNT)"
        and predicate_node is not None
        and tuple(ast.unparse(argument) for argument in predicate_node.args)
        == expected_arguments
        and not predicate_node.keywords
        and "len(p3_inputs) != _CANONICAL_SELECTION_COUNT"
        in ast.unparse(validator)
        and "len(validated_returned_results_by_role) != 4"
        in ast.unparse(validator)
    )


def _p3_witness_is_exact(predicate: ast.FunctionDef) -> bool:
    source = ast.unparse(predicate)
    required_fragments = (
        "role_results = validated_returned_results_by_role[role_index]",
        "role_results.results_in_submission_order",
        "matching_rows",
        "if len(matching_rows) != 1",
        "role_results.job_result_mapping",
        "mapping_occurrences != 1",
        "p3_input.returned_result_id",
        "p3_input.submitted_job_id",
        "p3_input.returned_run_projection is not witness",
        "replay_run_id = witness.run_id",
    )
    return bool(
        all(fragment in source for fragment in required_fragments)
        and all(value in _strings(predicate) for value in _P3_WITNESS_LITERALS)
        and "results_in_delivery_order" not in source
        and "validation_run_id" not in source
    )


def _p3_reconstruction_is_exact(
    predicate: ast.FunctionDef,
    raw_hash_sites: frozenset[tuple[int, str]],
) -> bool:
    source = ast.unparse(predicate)
    observation_keywords = _p3_call_keywords(predicate, "_RevealedObservation")
    authorization_keywords = _p3_call_keywords(
        predicate, "_RunObservationAuthorizationProjection"
    )
    effect_keywords = _p3_call_keywords(predicate, "_expected_calibration_effect")
    runtime_calls = tuple(
        node
        for node in ast.walk(predicate)
        if isinstance(node, ast.Call) and _call_leaf(node) == "_runtime_id"
    )
    exact_authorization = any(
        len(call.args) == 3
        and not call.keywords
        and isinstance(call.args[0], ast.Constant)
        and call.args[0].value == "authorization"
        and isinstance(call.args[1], ast.Constant)
        and call.args[1].value == "authorization_id/v1"
        and isinstance(call.args[2], ast.Dict)
        and tuple(
            key.value if isinstance(key, ast.Constant) else None
            for key in call.args[2].keys
        )
        == ("candidate_id", "kind", "run_id", "source_id")
        and tuple(ast.unparse(value) for value in call.args[2].values)
        == (
            "expected_candidate_id",
            "'calibration'",
            "replay_run_id",
            "source_id",
        )
        for call in runtime_calls
    )
    return bool(
        observation_keywords
        and all(keywords == _P3_OBSERVATION_FIELDS for keywords in observation_keywords)
        and authorization_keywords
        == (("candidate_id", "kind", "run_id", "source_id"),)
        and effect_keywords
        == (
            (
                "prefix_id",
                "world_id",
                "comparison_group_id",
                "group_index",
                "replication_index",
                "observed_effect",
            ),
        )
        and exact_authorization
        and "for observation_index in range(10)" in source
        and "for effect_index in range(5)" in source
        and "not replay_run_id.strip()" in source
        and source.count("transform.serialized_key.hex()") == 2
        and "expected_observations[2 * effect_index].revealed_observation - expected_observations[2 * effect_index + 1].revealed_observation"
        in source
        and "f'oracle-use/{expected_authorization_id}/{expected_oracle_key_id}'"
        in source
        and "for history_index in range(len(witness.effect_history))" in source
        and "recorded_effect = _reconstruct_matched_effect(history_projection)"
        in source
        and "len(witness.effect_history) != 15 + len(witness.updates)" in source
        and len(raw_hash_sites) == 2
        and not any(
            isinstance(call, ast.Call) and _call_leaf(call) in {"sorted", "set"}
            for call in ast.walk(predicate)
        )
    )


def _p3_validation_and_identity_is_exact(
    predicate: ast.FunctionDef,
    required_call_matches: frozenset[RequiredCallMatch],
) -> bool:
    assignments = {
        target.id: node
        for node in ast.walk(predicate)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and node.value is not None
        for target in (
            tuple(node.targets) if isinstance(node, ast.Assign) else (node.target,)
        )
        if isinstance(target, ast.Name)
    }
    expected_projection = assignments.get("expected_projection")
    if (
        expected_projection is None
        or not isinstance(expected_projection.value, ast.Call)
        or _call_leaf(expected_projection.value)
        != "ScientificCalibrationSelectionProjection"
        or tuple(keyword.arg for keyword in expected_projection.value.keywords)
        != PROJECTION_FIELDS["ScientificCalibrationSelectionProjection"]
    ):
        return False
    forbidden_dependencies = {
        "actual_helper_result",
        "carried_projection",
        "historical_selection",
        "expected_selector_result_identity",
    }
    if _p3_assignment_dependencies(predicate, "expected_projection") & forbidden_dependencies:
        return False
    calls = tuple(
        node
        for node in ast.walk(predicate)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    )
    exact_calls = {
        ast.unparse(call)
        for call in calls
        if isinstance(call.func, ast.Name)
        and call.func.id
        in {
            "_first_history_nonidentity_mismatch",
            "_first_scientific_projection_mismatch",
        }
    }
    required_validations = {
        "_first_history_nonidentity_mismatch(actual_helper_result, expected_projection, expected_effects, expected_observations, physical_cost)",
        "_first_history_nonidentity_mismatch(historical_selection, expected_projection, expected_effects, expected_observations, physical_cost)",
        "_first_scientific_projection_mismatch(carried_projection, expected_projection)",
    }
    identity_match = next(
        (
            match
            for match in required_call_matches
            if match.requirement.name == "selection_identity"
        ),
        None,
    )
    replay_match = next(
        (
            match
            for match in required_call_matches
            if match.requirement.name == "calibration_selector_replay"
        ),
        None,
    )
    identity_sources = (
        "actual_helper_result.selection_identity",
        "historical_selection.selection_identity",
        "p3_input.selector_result_identity",
    )
    identity_calls = tuple(
        next(
            (
                call
                for call in calls
                if isinstance(call.func, ast.Name)
                and call.func.id == "_exact_h64"
                and call.args
                and ast.unparse(call.args[0]) == source
            ),
            None,
        )
        for source in identity_sources
    )
    strict_mapping = next(
        (
            call
            for call in calls
            if isinstance(call.func, ast.Name)
            and call.func.id == "_scientific_calibration_selection_mapping"
            and ast.unparse(call.args[0]) == "carried_projection"
        ),
        None,
    )
    strict_decoder = next(
        (
            call
            for call in calls
            if isinstance(call.func, ast.Name)
            and call.func.id == "_decode_scientific_calibration_selection_projection"
        ),
        None,
    )
    historical_selection = assignments.get("historical_selection")
    carried_projection = assignments.get("carried_projection")
    helper_validation_line = min(
        (
            call.lineno
            for call in calls
            if ast.unparse(call) in required_validations
        ),
        default=-1,
    )
    return bool(
        required_validations <= exact_calls
        and identity_match is not None
        and replay_match is not None
        and replay_match.lineno < helper_validation_line
        and strict_mapping is not None
        and strict_decoder is not None
        and strict_mapping.lineno < strict_decoder.lineno < identity_match.lineno
        and all(call is not None for call in identity_calls)
        and identity_match.lineno
        < cast(ast.Call, identity_calls[0]).lineno
        < cast(ast.Call, identity_calls[1]).lineno
        < cast(ast.Call, identity_calls[2]).lineno
        and historical_selection is not None
        and historical_selection.value is not None
        and carried_projection is not None
        and carried_projection.value is not None
        and ast.unparse(historical_selection.value) == "selection[16]"
        and ast.unparse(carried_projection.value)
        == "p3_input.selector_result_projection"
    )


def _p3_exception_boundary_is_exact(predicate: ast.FunctionDef) -> bool:
    handlers = tuple(node for node in ast.walk(predicate) if isinstance(node, ast.ExceptHandler))
    replay_handlers = tuple(
        handler
        for handler in handlers
        if isinstance(handler.type, ast.Name)
        and handler.type.id == "_RunProvenanceError"
    )
    return bool(
        len(replay_handlers) == 1
        and ast.unparse(replay_handlers[0])
        == "except _RunProvenanceError:\n    return _selector_result_failure('replay helper rejected run-local provenance')"
        and not any(
            handler.type is None
            or isinstance(handler.type, ast.Name)
            and handler.type.id in {"Exception", "BaseException"}
            for handler in handlers
        )
    )


def _p3_boundary_is_exact(tree: ast.Module) -> bool:
    forbidden_names = {
        "CalibrationSelectionProjection",
        "calibration_selection_id",
        "_validate_stage2f_p4",
        "validate_stage2f_calibration_evidence",
    }
    for node in tree.body:
        name = getattr(node, "name", None)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        if (
            type(name) is str
            and (
                name in forbidden_names
                or name.startswith("_predicate_3p")
                or "reader" in name.lower()
                or "evidence_writer" in name.lower()
                or "persistence" in name.lower()
            )
        ):
            return False
    return True


def _p3_process_global_cache_findings(
    tree: ast.Module,
    analysis: qualified.QualifiedSymbolAnalysis | None = None,
) -> set[Finding]:
    if analysis is None:
        binding_names = {
            target.id
            for statement in tree.body
            if isinstance(statement, (ast.Assign, ast.AnnAssign))
            for target in (
                statement.targets if isinstance(statement, ast.Assign) else (statement.target,)
            )
            if isinstance(target, ast.Name)
        }
    else:
        binding_names = {
            binding.name for binding in analysis.bindings if binding.top_level
        }
    return (
        {Finding("p3-performance-invariant", "invocation-local")}
        if any("cache" in name.lower() for name in binding_names)
        else set()
    )


def _active_p3_internal_findings_with_session(
    source: str,
    session: _AnalysisSession,
) -> set[Finding]:
    try:
        facts = session.source_analysis(
            source,
            module_name=CANONICAL_MODULE,
            owned=True,
        )
    except SyntaxError:
        return {Finding("invalid-production-syntax", CANONICAL_MODULE)}
    tree = facts.tree
    functions = dict(facts.functions)
    analysis = facts.analysis
    classes = {
        node.name: node for node in tree.body if isinstance(node, ast.ClassDef)
    }
    findings: set[Finding] = set()
    scientific_class = classes.get("ScientificCalibrationSelectionProjection")
    if scientific_class is None or not _p1_projection_shape_is_exact(
        scientific_class, analysis
    ):
        findings.add(
            Finding(
                "p3-projection-shape",
                "ScientificCalibrationSelectionProjection",
            )
        )
    if not _p3_private_input_is_exact(classes.get("_P3SelectionInput"), analysis):
        findings.add(Finding("p3-input-shape", "_P3SelectionInput"))
    validator_signature = _p3_function_signature_is_exact(
        functions.get("_validate_stage2f_p3"),
        positional=(),
        keyword_only=(
            ("selections", "tuple[_SelectionEvidence, ...]"),
            (
                "expected_execution_attestation_pairs",
                "_ExecutionAttestationPairs",
            ),
            (
                "attested_execution_specification_ids",
                "_AttestedSpecificationIds",
            ),
            ("p2_selections", "tuple[_P2SelectionEvidence, ...]"),
            ("expected_predecessors", "tuple[_OraclePredecessor, ...]"),
            (
                "validated_returned_results_by_role",
                "tuple[_ReturnedResultsProjection, _ReturnedResultsProjection, _ReturnedResultsProjection, _ReturnedResultsProjection]",
            ),
            ("p3_inputs", "tuple[_P3SelectionInput, ...]"),
        ),
        returns="_P3ValidationOutcome",
    )
    predicate_signature = _p3_function_signature_is_exact(
        functions.get("_predicate_3o_5_1"),
        positional=(
            ("selection", "_SelectionEvidence"),
            ("p2_selection", "_P2SelectionEvidence"),
            ("expected_predecessor", "_OraclePredecessor"),
            (
                "expected_execution_attestation_pairs",
                "_ExecutionAttestationPairs",
            ),
            (
                "attested_execution_specification_ids",
                "_AttestedSpecificationIds",
            ),
            (
                "validated_returned_results_by_role",
                "tuple[_ReturnedResultsProjection, _ReturnedResultsProjection, _ReturnedResultsProjection, _ReturnedResultsProjection]",
            ),
            ("p3_input", "_P3SelectionInput"),
            ("selection_index", "int"),
        ),
        keyword_only=(),
        returns="_PredicateFailure | None",
    )
    if not validator_signature or not predicate_signature:
        findings.add(Finding("p3-validator-signature", "_validate_stage2f_p3"))
    if not _p3_projection_codec_is_exact(functions):
        findings.add(Finding("p3-projection-codec", "strict-21-field"))
    history_helper = functions.get("_first_history_nonidentity_mismatch")
    effect_helper = functions.get("_first_effect_mismatch")
    run_effect_helper = functions.get("_first_run_effect_mismatch")
    observation_helper = functions.get("_first_observation_mismatch")
    if (
        not _p3_direct_attribute_order(
            history_helper,
            "actual",
            _P3_HISTORY_NONIDENTITY_FIELDS,
        )
        or history_helper is not None
        and any(
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "actual"
            and node.attr == "selection_identity"
            for node in ast.walk(history_helper)
        )
        or not _p3_direct_attribute_order(
            effect_helper,
            "actual",
            _P3_EFFECT_FIELDS,
        )
        or not _p3_direct_attribute_order(
            run_effect_helper,
            "actual",
            _P3_EFFECT_FIELDS,
        )
        or not _p3_direct_attribute_order(
            observation_helper,
            "actual",
            _P3_OBSERVATION_FIELDS,
        )
    ):
        findings.add(Finding("p3-helper-field-order", "fields-1-27"))
    findings.update(_p3_failure_flow_findings(facts))
    projection_helper = functions.get("_first_scientific_projection_mismatch")
    if not _p3_direct_attribute_order(
        projection_helper,
        "actual",
        PROJECTION_FIELDS["ScientificCalibrationSelectionProjection"],
    ):
        findings.add(Finding("p3-projection-field-order", "fields-1-21"))
    predicate = functions.get("_predicate_3o_5_1")
    required_matches = _canonical_required_call_matches(tree, P3_MANIFEST, analysis)
    if predicate is None:
        findings.add(Finding("p3-required-function", "_predicate_3o_5_1"))
    else:
        raw_hash_sites = _p3_raw_hash_sites(tree, analysis)
        if not _p3_witness_is_exact(predicate):
            findings.add(Finding("p3-witness-authority", "role-owned-row"))
        if not _p3_reconstruction_is_exact(predicate, raw_hash_sites):
            findings.add(Finding("p3-reconstruction", "observations-effects-history"))
        if not _p3_validation_and_identity_is_exact(predicate, required_matches):
            findings.add(Finding("p3-identity-order", "A-B-H-C-E-B-H-D"))
        if not _p3_exception_boundary_is_exact(predicate):
            findings.add(Finding("p3-exception-boundary", "RunProvenanceError"))
    if not _p3_schedule_is_exact(functions, analysis):
        findings.add(Finding("p3-schedule", "all-p2-before-p3"))
    if not _p3_boundary_is_exact(tree):
        findings.add(Finding("p3-boundary", "no-p4-reader-live-io"))
    protected = {
        "_predicate_3o_5_1",
        "_validate_stage2f_p3",
        "_scientific_calibration_selection_mapping",
        "_decode_scientific_calibration_selection_projection",
        "_first_run_effect_mismatch",
        "_first_history_nonidentity_mismatch",
        "_first_scientific_projection_mismatch",
    }
    if any(
        name not in functions or functions[name].decorator_list for name in protected
    ):
        findings.add(Finding("p3-performance-invariant", "invocation-local"))
    findings.update(_p3_process_global_cache_findings(tree, analysis))
    return findings


def _active_p3_internal_findings(source: str) -> set[Finding]:
    return _active_p3_internal_findings_with_session(source, _AnalysisSession())


def _loop_source(iterator: ast.expr) -> ast.expr:
    if (
        isinstance(iterator, ast.Call)
        and _call_leaf(iterator) == "enumerate"
        and len(iterator.args) == 1
    ):
        return iterator.args[0]
    return iterator


def _harness_node_contains(container: ast.AST, child: ast.AST) -> bool:
    span = (getattr(container, "lineno", -1), getattr(container, "col_offset", -1), getattr(container, "end_lineno", -1), getattr(container, "end_col_offset", -1), getattr(child, "lineno", -1), getattr(child, "col_offset", -1), getattr(child, "end_lineno", -1), getattr(child, "end_col_offset", -1))
    return min(span) >= 0 and span[:2] <= span[4:6] and span[6:] <= span[2:4]


def _harness_bounded_walk(node: ast.AST, *, depth_limit: int, node_limit: int, root_width_limit: int, width_limit: int) -> tuple[ast.AST, ...] | None:
    """Return the canonical breadth-first syntax order under a fixed bound."""

    walked, depths = [node], [0]
    index = 0
    while index < len(walked):
        depth = depths[index]
        width = root_width_limit if index == 0 else width_limit
        for child_count, child in enumerate(ast.iter_child_nodes(walked[index]), start=1):
            if child_count > width or depth >= depth_limit or len(walked) >= node_limit:
                return None
            walked.append(child)
            depths.append(depth + 1)
        index += 1
    return tuple(walked)


def _harness_unresolved_local_aliases(
    tree: ast.Module,
    analysis: qualified.QualifiedSymbolAnalysis,
    *,
    production_sensitive: bool,
) -> frozenset[str]:
    """Correlate legacy alias names; canonical facts own sensitivity and limits."""

    if not production_sensitive:
        return frozenset()
    node_limit, width_limit, location_limit = qualified._MAX_ABSTRACT_STRUCTURE_NODES, qualified._MAX_ABSTRACT_CONTAINER_WIDTH, qualified._MAX_ABSTRACT_LOCATIONS
    if len(tree.body) > node_limit or len(analysis.binding_events) > location_limit or len(analysis.calls) > location_limit:
        return frozenset()
    walked = _harness_bounded_walk(tree, depth_limit=qualified._MAX_ABSTRACT_STRUCTURE_DEPTH, node_limit=qualified._MAX_POST_FLOW_RESOLUTION_CACHE, root_width_limit=node_limit, width_limit=width_limit)
    if walked is None:
        return frozenset()
    call_nodes = tuple(node for node in walked if isinstance(node, ast.Call))
    reference_nodes = tuple(node for node in walked if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load))
    direct_references = analysis.references[: len(reference_nodes)]
    calls_align = len(call_nodes) == len(analysis.calls) and all(call.lineno == node.lineno and call.spelling == ast.unparse(node.func) for call, node in zip(analysis.calls, call_nodes, strict=True))
    references_align = len(direct_references) == len(reference_nodes) and all(reference.lineno == node.lineno and reference.spelling == ast.unparse(node) for reference, node in zip(direct_references, reference_nodes, strict=True))
    if not calls_align or not references_align or any(CANONICAL_MODULE in reference.targets for reference in analysis.references[len(reference_nodes) :]):
        return frozenset()
    call_sites = tuple(zip(analysis.calls, call_nodes, strict=True))
    local_functions = {f"{HARNESS_MODULE}.{node.name}": node for node in tree.body if isinstance(node, ast.FunctionDef)}
    canonical_nodes = tuple(node for reference, node in zip(direct_references, reference_nodes, strict=True) if CANONICAL_MODULE in reference.targets)
    unresolved_bindings = tuple(finding for finding in analysis.findings if finding.code == "unresolved-top-level-binding")
    if len(canonical_nodes) > location_limit or len(unresolved_bindings) > location_limit:
        return frozenset()
    default_helpers: set[str] = set()
    for target, function in local_functions.items():
        defaults = (*function.args.defaults, *(item for item in function.args.kw_defaults if item is not None))
        if len(defaults) > width_limit or len(function.body) > node_limit:
            return frozenset()
        if any(_harness_node_contains(default, reference) for default in defaults for reference in canonical_nodes):
            default_helpers.add(target)
    unresolved_helpers = {target for target, function in local_functions.items() if any(call.scope == (function.name,) and call.sensitive_unresolved for call in analysis.calls)}
    binding_owners: list[ast.Assign | ast.AnnAssign | ast.NamedExpr] = []
    for node in walked:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            if len(binding_owners) >= location_limit:
                return frozenset()
            binding_owners.append(node)
    aliases: set[str] = set()
    for call, call_node in call_sites:
        local_targets = call.targets & frozenset(local_functions)
        if call.scope or not local_targets:
            continue
        owners = tuple(owner for owner in binding_owners if _harness_node_contains(owner, call_node))
        if len(owners) > width_limit:
            return frozenset()
        ambiguous = sum(any(_harness_node_contains(owner, candidate) for owner in owners) for candidate in call_nodes) > 1
        owner_targets: list[ast.expr] = []
        for owner in owners:
            for binding_target in (owner.targets if isinstance(owner, ast.Assign) else (owner.target,)):
                if len(owner_targets) >= width_limit:
                    return frozenset()
                owner_targets.append(binding_target)
        owned_names: set[str] = set()
        if not ambiguous:
            for node in walked:
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and any(_harness_node_contains(target, node) for target in owner_targets):
                    owned_names.add(node.id)
                    if len(owned_names) > width_limit:
                        return frozenset()
        binding_aliases = {finding.symbol for finding in unresolved_bindings if finding.symbol in owned_names}
        has_provenance = any(_harness_node_contains(call_node, reference) for reference in canonical_nodes) or bool(local_targets & default_helpers)
        is_unresolved = bool(local_targets & unresolved_helpers or binding_aliases or ambiguous)
        if has_provenance and is_unresolved:
            aliases.update(binding_aliases or {call.spelling})
    return frozenset(aliases)


class HarnessProvenanceAttribution(NamedTuple):
    """One finding tied to the projected receiver, callee, result, or limit."""

    finding: Finding
    lineno: int
    origin: str
    certainty: ProjectedProvenanceCertainty
    operation: str
    col_offset: int = 0
    relation: ProjectedProvenanceRelation = "direct"
    origin_class: ProjectedProvenanceOriginClass = "unresolved-production-sensitive"
    production_reachable: bool = _production_reachable_origin(
        "unresolved-production-sensitive"
    )
    limit_class: ProjectedProvenanceLimitClass = "none"
    qualified_origin: str | None = None


def _canonical_production_origins(
    analysis: qualified.QualifiedSymbolAnalysis,
) -> tuple[ProjectedProvenance, ...]:
    def fail_closed(lineno: object) -> tuple[ProjectedProvenance, ...]:
        return (_malformed_projected_provenance(lineno if type(lineno) is int else 1),)

    decoded: list[ProjectedProvenance] = []
    for finding in analysis.findings:
        if finding.code != _CANONICAL_PRODUCTION_ORIGIN_CODE:
            continue
        symbol = finding.symbol
        if type(symbol) is not str:
            return fail_closed(finding.lineno)
        parts = symbol.split(_PROJECTED_PROVENANCE_WIRE_SEPARATOR)
        if len(parts) != len(_PROJECTED_PROVENANCE_WIRE_FIELDS):
            return fail_closed(finding.lineno)
        fields = dict(zip(_PROJECTED_PROVENANCE_WIRE_FIELDS, parts, strict=True))
        if (
            type(finding.lineno) is not int
            or finding.lineno < 1
            or not _projected_provenance_wire_fields_are_valid(fields)
        ):
            return fail_closed(finding.lineno)
        fact = ProjectedProvenance(finding.lineno, int(fields["col_offset"]), fields["node_kind"], cast(ProjectedProvenanceCertainty, fields["certainty"]), cast(ProjectedProvenanceRelation, fields["relation"]), cast(ProjectedProvenanceOriginClass, fields["origin_class"]), fields["production_reachable"] == "1", cast(ProjectedProvenanceLimitClass, fields["limit_class"]), fields["qualified_origin"] or None)
        if not _projected_provenance_is_consistent(fact):
            return fail_closed(finding.lineno)
        decoded.append(fact)
    return tuple(decoded)


def _harness_provenance_attributions(
    tree: ast.Module,
    analysis: qualified.QualifiedSymbolAnalysis,
    facts: tuple[ProjectedProvenance, ...] | None = None,
) -> tuple[HarnessProvenanceAttribution, ...]:
    if facts is None:
        facts = _canonical_production_origins(analysis)
    by_site: dict[tuple[int, int, str], tuple[ProjectedProvenance, ...]] = {}
    for fact in facts:
        site_key = (fact.lineno, fact.col_offset, fact.node_kind)
        by_site[site_key] = (*by_site.get(site_key, ()), fact)

    def facts_for(node: ast.expr) -> tuple[ProjectedProvenance, ...]:
        return by_site.get(
            (node.lineno, node.col_offset, type(node).__name__),
            (),
        )

    call_targets: dict[tuple[int, str], frozenset[str]] = {}
    for call in analysis.calls:
        call_key = (call.lineno, call.spelling)
        call_targets[call_key] = call_targets.get(call_key, frozenset()) | call.targets
    import_targets = frozenset({"builtins.__import__", "importlib.import_module"})
    if not facts and not any(
        targets & import_targets for targets in call_targets.values()
    ):
        return ()

    attributions: set[HarnessProvenanceAttribution] = set()

    for fact in facts:
        if fact.limit_class != "production-sensitive":
            continue
        detail = (
            "span-correlation-limit"
            if fact.node_kind == "SpanCorrelationLimit"
            else "provenance-limit"
        )
        attributions.add(
            HarnessProvenanceAttribution(
                Finding("harness-unresolved-production-alias", detail),
                fact.lineno,
                fact.qualified_origin or CANONICAL_MODULE,
                fact.certainty,
                f"analysis:{fact.node_kind}",
                fact.col_offset,
                fact.relation,
                fact.origin_class,
                fact.production_reachable,
                fact.limit_class,
                fact.qualified_origin,
            )
        )

    def record(
        finding: Finding,
        node: ast.expr,
        fact: ProjectedProvenance,
    ) -> None:
        attributions.add(
            HarnessProvenanceAttribution(
                finding,
                node.lineno,
                fact.qualified_origin or fact.origin_class,
                fact.certainty,
                ast.unparse(node),
                node.col_offset,
                fact.relation,
                fact.origin_class,
                fact.production_reachable,
                fact.limit_class,
                fact.qualified_origin,
            )
        )

    def forbidden_target(fact: ProjectedProvenance) -> str | None:
        if fact.qualified_origin is None:
            return None
        return next(
            (
                target
                for target in _HARNESS_FORBIDDEN_PRODUCTION_TARGETS
                if fact.qualified_origin == target
                or fact.qualified_origin.startswith(f"{target}.")
            ),
            None,
        )

    walked = _harness_bounded_walk(tree, depth_limit=qualified._MAX_ABSTRACT_STRUCTURE_DEPTH, node_limit=qualified._MAX_POST_FLOW_RESOLUTION_CACHE, root_width_limit=qualified._MAX_ABSTRACT_STRUCTURE_NODES, width_limit=qualified._MAX_ABSTRACT_CONTAINER_WIDTH) or ()
    assignment_values = tuple(
        node.value
        for node in walked
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr))
        and node.value is not None
    )
    for value in assignment_values:
        for fact in facts_for(value):
            if fact.relation not in {"direct", "aggregate", "result"}:
                continue
            target = forbidden_target(fact)
            if target is not None and fact.production_reachable:
                record(
                    Finding(
                        "harness-forbidden-production-alias",
                        target.rsplit(".", 1)[-1],
                    ),
                    value,
                    fact,
                )

    for node in walked:
        if not isinstance(node, ast.Attribute) or not isinstance(node.ctx, ast.Load):
            continue
        site_facts = facts_for(node)
        for fact in site_facts:
            target = forbidden_target(fact)
            if target is not None and fact.production_reachable:
                record(
                    Finding(
                        "harness-forbidden-production-alias",
                        target.rsplit(".", 1)[-1],
                    ),
                    node,
                    fact,
                )
        receiver_facts = tuple(
            fact
            for fact in site_facts
            if fact.relation == "receiver"
            and _dynamic_namespace_restricted_provenance(fact)
        )
        if not receiver_facts:
            receiver_facts = tuple(
                fact
                for fact in site_facts
                if fact.relation == "result"
                and _dynamic_namespace_restricted_provenance(fact)
            )
        if node.attr in qualified._DYNAMIC_NAMESPACE_ATTRIBUTES and receiver_facts:
            fact = min(
                receiver_facts,
                key=lambda item: (
                    item.certainty != "exact",
                    item.qualified_origin or "",
                ),
            )
            record(
                Finding(
                    "harness-unresolved-production-alias",
                    "dynamic-namespace",
                ),
                node,
                fact,
            )

    for node in walked:
        if not isinstance(node, ast.Call):
            continue
        targets = call_targets.get((node.lineno, ast.unparse(node.func)), frozenset())
        callable_facts = tuple(
            fact
            for fact in facts_for(node)
            if fact.relation == "callable" and fact.production_reachable
        )
        forbidden_callable_facts = tuple(
            fact for fact in callable_facts if forbidden_target(fact) is not None
        )
        for fact in forbidden_callable_facts:
            target = forbidden_target(fact)
            assert target is not None
            record(
                Finding(
                    "harness-forbidden-production-alias",
                    target.rsplit(".", 1)[-1],
                ),
                node,
                fact,
            )
        if not forbidden_callable_facts:
            unresolved_callable_facts = tuple(
                fact
                for fact in callable_facts
                if _production_sensitive_provenance(fact)
            )
            if unresolved_callable_facts:
                fact = min(
                    unresolved_callable_facts,
                    key=lambda item: (
                        item.certainty != "exact",
                        item.qualified_origin or "",
                        item.origin_class,
                    ),
                )
                record(
                    Finding("harness-unresolved-production-alias", "dynamic-call"),
                    node,
                    fact,
                )
        if targets & import_targets:
            first = node.args[0] if node.args else next((keyword.value for keyword in node.keywords if keyword.arg == "name"), None)
            exact_name = (
                first.value
                if isinstance(first, ast.Constant) and type(first.value) is str
                else None
            )
            if exact_name == CANONICAL_MODULE or exact_name is None:
                certainty: ProjectedProvenanceCertainty = (
                    "exact" if exact_name == CANONICAL_MODULE else "possible"
                )
                fact = ProjectedProvenance(
                    node.lineno,
                    node.col_offset,
                    type(node).__name__,
                    certainty,
                    "result",
                    "canonical-production-module",
                    _production_reachable_origin("canonical-production-module"),
                    "none",
                    CANONICAL_MODULE,
                )
                record(
                    Finding(
                        "harness-unresolved-production-alias",
                        ast.unparse(node.func).rsplit(".", 1)[-1],
                    ),
                    node,
                    fact,
                )
            continue
        reflection = targets & frozenset(
            {"builtins.getattr", "builtins.hasattr", "builtins.vars"}
        )
        if not reflection or not node.args:
            continue
        reflection_facts = tuple(
            fact
            for fact in facts_for(node)
            if fact.relation == "receiver"
            and _production_sensitive_provenance(fact)
        ) or tuple(
            fact
            for fact in facts_for(node)
            if fact.relation == "result"
            and _production_sensitive_provenance(fact)
        )
        if not reflection_facts:
            continue
        fact = min(
            reflection_facts,
            key=lambda item: (
                item.certainty != "exact",
                item.qualified_origin or "",
            ),
        )
        operation = next(iter(sorted(reflection))).rsplit(".", 1)[-1]
        attribute = node.args[1] if len(node.args) >= 2 else None
        attribute_name = (
            attribute.value
            if isinstance(attribute, ast.Constant)
            and type(attribute.value) is str
            else None
        )
        target = (
            f"{CANONICAL_MODULE}.{attribute_name}"
            if fact.qualified_origin == CANONICAL_MODULE and attribute_name is not None
            else None
        )
        if target in _HARNESS_FORBIDDEN_PRODUCTION_TARGETS:
            forbidden_fact = fact._replace(
                origin_class="forbidden-production-helper",
                production_reachable=_production_reachable_origin(
                    "forbidden-production-helper"
                ),
                qualified_origin=target,
            )
            record(
                Finding(
                    "harness-forbidden-production-alias",
                    cast(str, attribute_name),
                ),
                node,
                forbidden_fact,
            )
        else:
            record(
                Finding(
                    "harness-unresolved-production-alias",
                    operation,
                ),
                node,
                fact,
            )
    return tuple(
        sorted(
            attributions,
            key=lambda item: (
                item.lineno,
                item.operation,
                item.finding,
                item.origin,
                item.certainty,
                item.col_offset,
                item.relation,
                item.origin_class,
                item.production_reachable,
                item.limit_class,
                item.qualified_origin or "",
            ),
        )
    )


def harness_provenance_attributions(
    source: str,
) -> tuple[HarnessProvenanceAttribution, ...]:
    """Return structured attribution for production-sensitive harness findings."""

    try:
        facts = _source_analysis(source, module_name=HARNESS_MODULE)
    except SyntaxError:
        return ()
    return _harness_provenance_attributions(facts.tree, facts.analysis)


def harness_findings(source: str) -> tuple[Finding, ...]:
    """Check that the test-owned fixture harness never becomes P1/P2 authority."""

    session = _AnalysisSession()
    try:
        facts = session.source_analysis(source, module_name=HARNESS_MODULE)
    except SyntaxError as error:
        return (Finding("invalid-harness-syntax", f"{error.lineno}:{error.offset}"),)
    tree = facts.tree
    findings: set[Finding] = set()
    analysis = facts.analysis
    projected = _canonical_production_origins(analysis)
    findings.update(
        attribution.finding
        for attribution in _harness_provenance_attributions(
            tree,
            analysis,
            projected,
        )
    )
    for alias in _harness_unresolved_local_aliases(
        tree,
        analysis,
        production_sensitive=any(
            _production_sensitive_provenance(fact) for fact in projected
        ),
    ):
        findings.add(Finding("harness-unresolved-production-alias", alias))
    for binding in analysis.imports:
        for target in binding.origins & _HARNESS_FORBIDDEN_PRODUCTION_TARGETS:
            findings.add(
                Finding("harness-forbidden-production-alias", target.rsplit(".", 1)[-1])
            )
    for binding in analysis.binding_events:
        for target in binding.origins & _HARNESS_FORBIDDEN_PRODUCTION_TARGETS:
            findings.add(
                Finding("harness-forbidden-production-alias", target.rsplit(".", 1)[-1])
            )
        if (
            binding.kind != "import"
            and CANONICAL_MODULE in binding.origins
        ):
            findings.add(
                Finding("harness-unresolved-production-alias", binding.name)
            )
    for reference in analysis.references:
        for target in reference.targets & _HARNESS_FORBIDDEN_PRODUCTION_TARGETS:
            findings.add(
                Finding("harness-forbidden-production-alias", target.rsplit(".", 1)[-1])
            )
        if any(
            target == f"{CANONICAL_MODULE}.__dict__"
            or target.startswith(f"{CANONICAL_MODULE}.__dict__.")
            for target in reference.targets
        ):
            findings.add(
                Finding("harness-unresolved-production-alias", reference.spelling)
            )
    for imported_from in (
        node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ):
        if imported_from.module == CANONICAL_MODULE and any(
            item.name == "*" for item in imported_from.names
        ):
            findings.add(
                Finding("harness-unresolved-production-alias", "star-import")
            )
    identity_helpers = {"calibration_candidate_pair_id", "strict_chronology_id"}
    identity_helpers.add("source_observation_identity")
    for node in (item for item in ast.walk(tree) if isinstance(item, ast.ImportFrom)):
        if node.module == CANONICAL_MODULE:
            for item in node.names:
                if item.name in identity_helpers:
                    findings.add(Finding("harness-production-identity-helper", item.name))
                elif item.name.startswith("_"):
                    findings.add(Finding("harness-private-production-helper", item.name))

    production_calls: dict[int, set[str]] = {}
    for resolved_call in analysis.calls:
        for target in resolved_call.targets:
            target_module, _, target_name = target.rpartition(".")
            if target_module != CANONICAL_MODULE:
                continue
            production_calls.setdefault(resolved_call.lineno, set()).add(target_name)
            if target_name in identity_helpers:
                findings.add(Finding("harness-production-identity-helper-call", target_name))
            elif target_name.startswith("_"):
                findings.add(Finding("harness-private-production-helper-call", target_name))

    validation_lines = {line for line, targets in production_calls.items() if targets & {"_validate_stage2f_p1", "validate_stage2f_p1"}}
    if validation_lines:
        findings.add(Finding("harness-production-derived-expectation", "_validate_stage2f_p1"))
    for assignment in (node for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))):
        value = assignment.value
        if value is None:
            continue
        assigned_names = {walked_name.id for target in (tuple(assignment.targets) if isinstance(assignment, ast.Assign) else (assignment.target,)) for walked_name in ast.walk(target) if isinstance(walked_name, ast.Name)}
        if any("expected" in name.lower() for name in assigned_names) and any(isinstance(call, ast.Call) and call.lineno in validation_lines for call in ast.walk(value)):
            findings.add(Finding("harness-production-output-as-expected", "expected"))

    predicate_names = {f"_predicate_3o_1_{index}" for index in range(7)}
    for function in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)):
        function_nodes = tuple(ast.walk(function))
        normalized = function.name.replace("_", "").lower()
        referenced_predicates = {node.id for node in function_nodes if isinstance(node, ast.Name) and node.id in predicate_names}
        if "validatestage2fp1" in normalized or referenced_predicates == predicate_names:
            findings.add(Finding("harness-competing-p1-validator", function.name))
        assignments = tuple(node for node in function_nodes if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None)
        predicate_domains = {name.id for assignment in assignments if isinstance(assignment.value, (ast.Tuple, ast.List)) and len(assignment.value.elts) == 7 and {item.id for item in assignment.value.elts if isinstance(item, ast.Name)} == predicate_names for target in (tuple(assignment.targets) if isinstance(assignment, ast.Assign) else (assignment.target,)) for name in ast.walk(target) if isinstance(name, ast.Name)}
        loops = tuple(node for node in function_nodes if isinstance(node, (ast.For, ast.comprehension)))
        predicate_loop_names = {name.id for loop in loops if isinstance(_loop_source(loop.iter), ast.Name) and cast(ast.Name, _loop_source(loop.iter)).id in predicate_domains for name in ast.walk(loop.target) if isinstance(name, ast.Name)}
        selection_loop_names = {name.id for loop in loops if isinstance(_loop_source(loop.iter), ast.Name) and cast(ast.Name, _loop_source(loop.iter)).id == "selections" for name in ast.walk(loop.target) if isinstance(name, ast.Name)}
        linked_predicate_execution = any(isinstance(call.func, ast.Name) and call.func.id in predicate_loop_names and any(isinstance(name, ast.Name) and name.id in selection_loop_names for argument in (*call.args, *(keyword.value for keyword in call.keywords)) for name in ast.walk(argument)) for call in function_nodes if isinstance(call, ast.Call))
        has_predicate_range = any(isinstance(loop.iter, ast.Call) and _call_leaf(loop.iter) == "range" and any(isinstance(argument, ast.Constant) and argument.value == 7 for argument in loop.iter.args) for loop in loops)
        has_selection_range = any(isinstance(loop.iter, ast.Call) and _call_leaf(loop.iter) == "range" and any(isinstance(argument, ast.Constant) and argument.value == 318 or isinstance(argument, ast.Name) and argument.id == "CANONICAL_SELECTION_COUNT" for argument in loop.iter.args) for loop in loops)
        if linked_predicate_execution or (has_predicate_range and has_selection_range):
            findings.add(Finding("harness-second-predicate-engine", function.name))
    return tuple(sorted(findings))


# fmt: on
def _call_metadata_manifest_findings() -> tuple[Finding, ...]:
    manifest = REQUIRED_CALLS
    if type(manifest) is not tuple:
        return (Finding("invalid-required-call-metadata", "REQUIRED_CALLS"),)
    if not manifest:
        return (Finding("invalid-required-call-metadata", "REQUIRED_CALLS:empty"),)

    findings: set[Finding] = set()
    if len(manifest) != 5:
        findings.add(Finding("invalid-required-call-metadata", "REQUIRED_CALLS:length"))
    names: list[str] = []
    owner_targets: list[tuple[str, str]] = []
    for index, requirement in enumerate(manifest):
        detail = f"REQUIRED_CALLS[{index}]"
        if not _required_call_metadata_is_valid(requirement):
            findings.add(Finding("invalid-required-call-metadata", detail))
            continue
        if requirement.call_shape.validation_only is not True:
            findings.add(Finding("invalid-required-call-metadata", detail))
        if requirement.name in names:
            findings.add(Finding("duplicate-required-call-metadata", detail))
        names.append(requirement.name)
        owner_target = (requirement.owner, requirement.qualified_target)
        if owner_target in owner_targets:
            findings.add(Finding("duplicate-required-call-metadata", detail))
        owner_targets.append(owner_target)
    return tuple(sorted(findings))


# fmt: off
def _strings(node: ast.AST) -> frozenset[str]:
    return frozenset(item.value for item in ast.walk(node) if isinstance(item, ast.Constant) and isinstance(item.value, str))

def _fields(node: ast.ClassDef) -> tuple[str, ...]:
    return tuple(target.id for item in node.body for target in ((item.target,) if isinstance(item, ast.AnnAssign) else tuple(item.targets) if isinstance(item, ast.Assign) else ()) if isinstance(target, ast.Name))

def _parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[ast.arg, ...]:
    return (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)

def _exact_positional_parameters(node: ast.FunctionDef | ast.AsyncFunctionDef, expected: tuple[str, ...]) -> bool:
    return tuple(parameter.arg for parameter in (*node.args.posonlyargs, *node.args.args)) == expected and not node.args.kwonlyargs and not node.args.defaults and node.args.vararg is None and node.args.kwarg is None

def _literal_exact(actual: object, expected: object) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, tuple) and isinstance(expected, tuple):
        return len(actual) == len(expected) and all(_literal_exact(left, right) for left, right in zip(actual, expected, strict=True))
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(_literal_exact(left, right) for left, right in zip(actual, expected, strict=True))
    if isinstance(actual, dict) and isinstance(expected, dict):
        return len(actual) == len(expected) and all(_literal_exact(left_key, right_key) and _literal_exact(left_value, right_value) for (left_key, left_value), (right_key, right_value) in zip(actual.items(), expected.items(), strict=True))
    return actual == expected

def _dynamic_class_aliases(tree: ast.Module, analysis: qualified.QualifiedSymbolAnalysis) -> frozenset[str]:
    top_level_sites = {(binding.lineno, binding.name) for binding in analysis.bindings if binding.top_level}
    assignments: list[tuple[frozenset[str], ast.expr, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = tuple(node.targets), node.value
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
            targets, value = (node.target,), node.value
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            targets, value = (node.target,), node.iter
        elif isinstance(node, ast.Match):
            names = frozenset(name for pattern in ast.walk(node) for name in ((pattern.name,) if isinstance(pattern, (ast.MatchAs, ast.MatchStar)) and pattern.name is not None else (pattern.rest,) if isinstance(pattern, ast.MatchMapping) and pattern.rest is not None else ()) if (getattr(pattern, "lineno", 0), name) in top_level_sites)
            assignments.append((names, node.subject, False))
            continue
        else:
            continue
        assignments.append((frozenset(item.id for target in targets for item in ast.walk(target) if isinstance(item, ast.Name) and (node.lineno, item.id) in top_level_sites), value, node in tree.body))
    origin_class_bindings = {binding.name for binding in analysis.bindings if binding.origins & _KNOWN_CLASS_TARGETS}
    aliases = set(_BUILTIN_CLASS_NAMES) | {binding.name for binding in analysis.bindings if binding.kind in {"class", "import"} and binding.name in origin_class_bindings}
    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and (node.lineno, node.name) in top_level_sites}
    reference_targets = {(reference.lineno, reference.spelling): reference.targets for reference in analysis.references}
    call_targets = {(call.lineno, call.spelling): call.targets for call in analysis.calls}
    class_source = "<class>"
    container_helpers = {"builtins.frozenset", "builtins.list", "builtins.set", "builtins.sorted", "builtins.tuple"}
    function_sources: dict[str, frozenset[str]] = {}

    def source_arguments(call: ast.Call, function: ast.FunctionDef, source: str) -> tuple[ast.expr, ...]:
        positional = (*function.args.posonlyargs, *function.args.args)
        named = {parameter.arg for parameter in (*positional, *function.args.kwonlyargs)}
        if function.args.vararg is not None and source == function.args.vararg.arg:
            return tuple(call.args[len(positional):])
        if function.args.kwarg is not None and source == function.args.kwarg.arg:
            return tuple(keyword.value for keyword in call.keywords if keyword.arg not in named)
        for index, parameter in enumerate(positional):
            if parameter.arg != source:
                continue
            if index < len(call.args):
                return (call.args[index],)
            if keyword := next((keyword for keyword in call.keywords if keyword.arg == source), None):
                return (keyword.value,)
            default_index = index - (len(positional) - len(function.args.defaults))
            return (function.args.defaults[default_index],) if default_index >= 0 else ()
        for parameter, default in zip(function.args.kwonlyargs, function.args.kw_defaults, strict=True):
            if parameter.arg == source:
                keyword = next((keyword for keyword in call.keywords if keyword.arg == source), None)
                return (keyword.value,) if keyword is not None else (default,) if default is not None else ()
        return ()

    def value_sources(node: ast.expr, environment: dict[str, frozenset[str]]) -> frozenset[str]:
        if isinstance(node, ast.Name):
            return environment.get(node.id, frozenset({class_source}) if node.id in aliases else frozenset())
        if isinstance(node, ast.Attribute):
            targets = reference_targets.get((node.lineno, ast.unparse(node)), frozenset())
            if targets & _KNOWN_CLASS_TARGETS:
                return frozenset({class_source})
            return value_sources(node.value, environment) if node.attr in {"__base__", "__bases__", "__class__", "__mro__"} else frozenset()
        if isinstance(node, ast.Call):
            targets = call_targets.get((node.lineno, ast.unparse(node.func)), frozenset())
            if targets & (container_helpers | {"builtins.max", "builtins.min"}):
                return frozenset().union(*(value_sources(argument, environment) for argument in (*node.args, *(keyword.value for keyword in node.keywords))))
            if "builtins.type" in targets:
                return frozenset({class_source})
            sources: set[str] = set()
            for target_name in {target.rsplit(".", 1)[-1] for target in targets} & function_sources.keys():
                sources.update(function_sources[target_name] & {class_source})
                for source in function_sources[target_name] - {class_source}:
                    sources.update(*(value_sources(argument, environment) for argument in source_arguments(node, functions[target_name], source)))
            return frozenset(sources)
        return frozenset().union(*(value_sources(child, environment) for child in ast.iter_child_nodes(node) if isinstance(child, ast.expr)))

    for _ in range(len(functions) + 1):
        updated: dict[str, frozenset[str]] = {}
        for name, function in functions.items():
            parameters = (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs, *((function.args.vararg,) if function.args.vararg is not None else ()), *((function.args.kwarg,) if function.args.kwarg is not None else ()))
            environment = {parameter.arg: frozenset({parameter.arg}) for parameter in parameters} | {alias: frozenset({class_source}) for alias in aliases}
            local_names = {binding.name for binding in analysis.bindings if binding.scope == (name,)} | {parameter.arg for parameter in parameters}
            local_assignments = [(tuple(node.targets), node.value, node in function.body) if isinstance(node, ast.Assign) else ((node.target,), node.value, node in function.body) for node in ast.walk(function) if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None]
            for targets, value, direct in local_assignments:
                sources = value_sources(value, environment)
                for target in targets:
                    for local in (item for item in ast.walk(target) if isinstance(item, ast.Name) and item.id in local_names):
                        environment[local.id] = sources if direct else environment.get(local.id, frozenset()) | sources
            updated[name] = frozenset().union(*(value_sources(node.value, environment) for node in ast.walk(function) if isinstance(node, ast.Return) and node.value is not None))
        if updated == function_sources:
            break
        function_sources = updated

    environment = {alias: frozenset({class_source}) for alias in aliases}
    assigned: set[str] = set()
    for target_names, value, direct in assignments:
        sources = value_sources(value, environment)
        if direct:
            assigned.difference_update(target_names)
            aliases.difference_update(target_names)
        for target_name in target_names:
            environment[target_name] = sources if direct else environment.get(target_name, frozenset()) | sources
        call_target_set = call_targets.get((value.lineno, ast.unparse(value.func)), frozenset()) if isinstance(value, ast.Call) else frozenset()
        container_call = bool(call_target_set & container_helpers)
        if class_source in sources and not container_call:
            aliases.update(target_names)
            assigned.update(target_names)
    return frozenset(assigned)

def _caller_controlled(name: str) -> bool:
    lowered, normalized = name.lower().strip("_"), name.lower().replace("_", "")
    if lowered.endswith(("_id", "_ids", "_identity", "_identities")) or name.strip("_").endswith(("Id", "Ids", "Identity", "Identities")):
        return False
    return any(token.replace("_", "") in normalized for token in _CALLABLE_PARAMETER_NAMES | _LIVE_PARAMETER_NAMES)

def _annotation_names(node: ast.expr | None) -> frozenset[str]:
    if node is None:
        return frozenset()
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return frozenset()
    return frozenset(item.id if isinstance(item, ast.Name) else item.attr for item in ast.walk(node) if isinstance(item, (ast.Name, ast.Attribute))) | frozenset().union(*(_annotation_names(item) for item in ast.walk(node) if isinstance(item, ast.Constant) and isinstance(item.value, str)))

def _assigned_literals(node: ast.Module | ast.ClassDef) -> dict[str, object]:
    values: dict[str, object] = {}
    for item in node.body:
        if isinstance(item, ast.Assign):
            targets = tuple(item.targets)
            value_node = item.value
        elif isinstance(item, ast.AnnAssign) and item.value is not None:
            targets = (item.target,)
            value_node = item.value
        else:
            continue
        try:
            value = ast.literal_eval(value_node)
        except (TypeError, ValueError):
            continue
        values.update((target.id, value) for target in targets if isinstance(target, ast.Name))
    return values

def _annotation_is(node: ast.expr | None, expected: str) -> bool:
    if node is None:
        return False
    expected_node = ast.parse(expected, mode="eval").body
    if isinstance(expected_node, ast.Subscript) and isinstance(expected_node.value, ast.Name) and expected_node.value.id == "Literal":
        return isinstance(node, ast.Subscript) and (isinstance(node.value, ast.Name) and node.value.id.lstrip("_") == "Literal" or isinstance(node.value, ast.Attribute) and node.value.attr == "Literal") and ast.dump(node.slice) == ast.dump(expected_node.slice)
    return ast.dump(node) == ast.dump(expected_node)


def _p1_projection_shape_is_exact(
    node: ast.ClassDef, analysis: qualified.QualifiedSymbolAnalysis | None,
) -> bool:
    expected = _P1_PROJECTION_SHAPES.get(node.name)
    if expected is None or node.bases or node.keywords or len(node.decorator_list) != 1:
        return False
    decorator = node.decorator_list[0]
    if not isinstance(decorator, ast.Call) or decorator.args or any(keyword.arg is None for keyword in decorator.keywords):
        return False
    targets = {} if analysis is None else {(reference.lineno, reference.spelling): reference.targets for reference in analysis.references}
    if ast.unparse(decorator.func) != "_dataclass" if analysis is None else targets.get((decorator.func.lineno, ast.unparse(decorator.func))) != frozenset({"dataclasses.dataclass"}):
        return False
    if {keyword.arg: keyword.value.value if isinstance(keyword.value, ast.Constant) else object() for keyword in decorator.keywords} != {"frozen": True, "slots": True}:
        return False
    fields = tuple(item for item in node.body if isinstance(item, ast.AnnAssign))
    methods = tuple(item for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)))
    if len(node.body) != len(expected) + 1 or tuple(node.body[:-1]) != fields or tuple(node.body[-1:]) != methods or len(fields) != len(expected) or len(methods) != 1:
        return False
    if any(not isinstance(field.target, ast.Name) or field.value is not None or field.simple != 1 or field.target.id != name or not _annotation_is(field.annotation, annotation) for field, (name, annotation) in zip(fields, expected, strict=True)):
        return False
    method = methods[0]
    parameters = _parameters(method)
    mapper = {"CalibrationCandidatePairProjection": "_calibration_candidate_pair_mapping", "CalibrationSourceObservationProjection": "_calibration_source_observation_mapping", "ScientificCalibrationSelectionProjection": "_scientific_calibration_selection_mapping", "StrictChronologyProjection": "_strict_chronology_mapping"}[node.name]
    call = method.body[0].value if len(method.body) == 1 and isinstance(method.body[0], ast.Expr) and isinstance(method.body[0].value, ast.Call) else None
    return bool(method.name == "__post_init__" and not method.decorator_list and len(parameters) == 1 and parameters[0].arg == "self" and not method.args.defaults and not method.args.kwonlyargs and method.args.vararg is None and method.args.kwarg is None and _annotation_is(method.returns, "None") and call is not None and isinstance(call.func, ast.Name) and call.func.id == mapper and len(call.args) == 1 and isinstance(call.args[0], ast.Name) and call.args[0].id == "self" and not call.keywords)


def _p1_preimage_is_exact(
    node: ast.FunctionDef | ast.AsyncFunctionDef, projection_name: str,
) -> bool:
    parameters = _parameters(node)
    stem = node.name.removesuffix("_preimage")
    mapping_name, decoder_name = f"{stem}_mapping", f"_decode{stem}_projection"
    if len(parameters) != 1 or parameters[0].arg != "projection" or not _annotation_is(parameters[0].annotation, projection_name) or not _annotation_is(node.returns, "dict[str, object]") or node.args.defaults or node.args.kwonlyargs or node.args.vararg is not None or node.args.kwarg is not None or len(node.body) != 4:
        return False
    mapping, decoded, comparison, returned = node.body
    return bool(isinstance(mapping, ast.Assign) and len(mapping.targets) == 1 and isinstance(mapping.targets[0], ast.Name) and mapping.targets[0].id == "mapping" and isinstance(mapping.value, ast.Call) and isinstance(mapping.value.func, ast.Name) and mapping.value.func.id == mapping_name and len(mapping.value.args) == 1 and isinstance(mapping.value.args[0], ast.Name) and mapping.value.args[0].id == "projection" and not mapping.value.keywords and isinstance(decoded, ast.Assign) and len(decoded.targets) == 1 and isinstance(decoded.targets[0], ast.Name) and decoded.targets[0].id == "decoded" and isinstance(decoded.value, ast.Call) and isinstance(decoded.value.func, ast.Name) and decoded.value.func.id == decoder_name and len(decoded.value.args) == 1 and isinstance(decoded.value.args[0], ast.Name) and decoded.value.args[0].id == "mapping" and not decoded.value.keywords and isinstance(comparison, ast.If) and not comparison.orelse and isinstance(comparison.test, ast.Compare) and isinstance(comparison.test.left, ast.Name) and comparison.test.left.id == "decoded" and len(comparison.test.ops) == 1 and isinstance(comparison.test.ops[0], ast.NotEq) and len(comparison.test.comparators) == 1 and isinstance(comparison.test.comparators[0], ast.Name) and comparison.test.comparators[0].id == "projection" and isinstance(returned, ast.Return) and isinstance(returned.value, ast.Name) and returned.value.id == "mapping")


def _identity_hash_is_exact(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    analysis: qualified.QualifiedSymbolAnalysis,
    domain: str,
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    strict_p1: bool,
) -> bool:
    calls = tuple(call for call in analysis.calls if call.scope == (node.name,) and (_PROTOCOL_HASH_TARGET in call.targets or call.spelling.rsplit(".", 1)[-1].endswith("protocol_hash")))
    direct = node.body[0].value if len(node.body) == 1 and isinstance(node.body[0], ast.Return) and isinstance(node.body[0].value, ast.Call) else None
    parameters = (*node.args.posonlyargs, *node.args.args)
    if not (len(parameters) == 1 and not node.args.defaults and not node.args.kwonlyargs and node.args.vararg is None and node.args.kwarg is None and len(calls) == 1 and direct is not None and calls[0].lineno == direct.lineno and calls[0].spelling == ast.unparse(direct.func) and calls[0].targets == {_PROTOCOL_HASH_TARGET} and len(direct.args) == 2 and not direct.keywords and isinstance(direct.args[0], ast.Constant) and direct.args[0].value == domain):
        return False
    if not strict_p1:
        payload = direct.args[1]
        return bool(isinstance(payload, ast.Name) and payload.id == parameters[0].arg or isinstance(payload, ast.Call) and len(payload.args) == 1 and isinstance(payload.args[0], ast.Name) and payload.args[0].id == parameters[0].arg and not payload.keywords)
    projection_name, preimage_name = _P1_IDENTITY_PREIMAGES[node.name]
    payload = direct.args[1]
    preimage = functions.get(preimage_name)
    return bool(_annotation_is(parameters[0].annotation, projection_name) and _annotation_is(node.returns, "str") and isinstance(payload, ast.Call) and isinstance(payload.func, ast.Name) and payload.func.id == preimage_name and len(payload.args) == 1 and isinstance(payload.args[0], ast.Name) and payload.args[0].id == parameters[0].arg and not payload.keywords and preimage is not None and _p1_preimage_is_exact(preimage, projection_name))

def _literal_relation(
    tree: ast.Module, analysis: qualified.QualifiedSymbolAnalysis, key: str, expected: object,
) -> bool:
    matches = tuple(binding for binding in analysis.binding_events if binding.top_level and binding.name.startswith("_") and binding.name.lstrip("_").lower() == key)
    assignments = [(tuple(node.targets), node.value) if isinstance(node, ast.Assign) else ((node.target,), node.value) for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None]
    aliases = {target.id for targets, value in assignments if isinstance(value, (ast.Name, ast.Attribute)) and (value.id if isinstance(value, ast.Name) else value.attr).lstrip("_").lower() == key for target in targets if isinstance(target, ast.Name)}
    for _ in assignments:
        aliases.update(target.id for targets, value in assignments if isinstance(value, ast.Name) and value.id in aliases for target in targets if isinstance(target, ast.Name))
    comparisons = tuple(node for node in ast.walk(tree) if isinstance(node, ast.Compare) and any(isinstance(item, ast.Name) and item.id in aliases or (item.id if isinstance(item, ast.Name) else item.attr).lstrip("_").lower() == key for item in ast.walk(node) if isinstance(item, (ast.Name, ast.Attribute))))
    def comparison_is_exact(node: ast.Compare) -> bool:
        operands = (node.left, *node.comparators)
        if len(node.ops) == 1 and isinstance(node.ops[0], (ast.Is, ast.IsNot)) and any(isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == "type" and len(item.args) == 1 and not item.keywords for item in operands):
            return True
        if not all(isinstance(operator, (ast.Eq, ast.NotEq)) for operator in node.ops):
            return False
        literals: list[object] = []
        for operand in operands:
            try:
                literals.append(ast.literal_eval(operand))
            except (TypeError, ValueError):
                continue
        return all(_literal_exact(value, expected) for value in literals)
    return len(matches) == 1 and matches[0].kind in {"assign", "annassign"} and _literal_exact(_assigned_literals(tree).get(matches[0].name), expected) and not any(isinstance(node, ast.Delete) and any(isinstance(target, ast.Name) and target.id == matches[0].name for target in node.targets) for node in ast.walk(tree)) and all(comparison_is_exact(node) for node in comparisons)

def _replay_result_escapes(function: ast.FunctionDef | ast.AsyncFunctionDef, origin: str, sink: ast.Call) -> bool:
    assignments = [(tuple(node.targets), node.value) if isinstance(node, ast.Assign) else ((node.target,), node.value) for node in ast.walk(function) if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None]
    derived = {origin}
    for _ in assignments:
        derived.update(target.id for targets, value in assignments if any(isinstance(item, ast.Name) and item.id in derived for item in ast.walk(value)) for target in targets if isinstance(target, ast.Name))
    return any(node.value is not None and node.value is not sink and any(isinstance(item, ast.Name) and item.id in derived for item in ast.walk(node.value)) for node in ast.walk(function) if isinstance(node, (ast.Return, ast.Yield, ast.YieldFrom)))

def _literal_alias_names(tree: ast.AST, values: frozenset[object]) -> set[str]:
    assignments = [(tuple(node.targets), node.value) if isinstance(node, ast.Assign) else ((node.target,), node.value) for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None]
    aliases = {target.id for targets, value in assignments if isinstance(value, ast.Constant) and value.value in values for target in targets if isinstance(target, ast.Name)}
    for _ in assignments:
        aliases.update(target.id for targets, value in assignments if isinstance(value, ast.Name) and value.id in aliases for target in targets if isinstance(target, ast.Name))
    return aliases


def _string_expression_value(node: ast.expr | None, values: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return values.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _string_expression_value(node.left, values)
        right = _string_expression_value(node.right, values)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                parts.append(part.value)
            elif (
                isinstance(part, ast.FormattedValue)
                and part.conversion in {-1, ord("s")}
                and part.format_spec is None
                and (value := _string_expression_value(part.value, values)) is not None
            ):
                parts.append(value)
            else:
                return None
        return "".join(parts)
    return None


def _authority_suffix(parts: list[str], marker_index: int) -> bool:
    suffix = parts[marker_index + 1 :]
    return not suffix or len(suffix) == 1 and (suffix[0] in {"alias", "authority", "constant", "manifest"} or len(suffix[0]) > 1 and suffix[0][0] == "v" and suffix[0][1:].isdigit()) or len(suffix) == 2 and suffix[0] in {"alias", "authority", "constant", "manifest"} and len(suffix[1]) > 1 and suffix[1][0] == "v" and suffix[1][1:].isdigit()

def _identity_domain_binding(name: str) -> bool:
    normalized = name.strip("_").lower()
    collapsed = normalized.replace("_", "")
    manifested = {f"{item.name}_domain".replace("_", "").lower() for item in IDENTITY_MANIFESTS}
    parts = normalized.split("_")
    if collapsed in manifested:
        return True
    return "domain" in parts and (domain_index := parts.index("domain")) >= 0 and _authority_suffix(parts, domain_index) and bool({"id", "identity", "selection", "selector"} & set(parts[:domain_index]))

def _identity_manifest_binding(name: str, has_identity_entry: bool = False) -> bool:
    parts = name.strip("_").lower().split("_")
    return "manifest" in parts and (manifest_index := parts.index("manifest")) >= 0 and _authority_suffix(parts, manifest_index) and (has_identity_entry or "identity" in parts[:manifest_index])


def _authority_domain_literals(tree: ast.Module, analysis: qualified.QualifiedSymbolAnalysis) -> frozenset[str]:
    values: set[str] = set()
    module_strings: dict[str, str] = {}
    handled_authority_sites: set[tuple[int, str]] = set()
    module_sites = {(binding.lineno, binding.name) for binding in analysis.bindings if binding.top_level} | {(reference.lineno, reference.spelling) for reference in analysis.references if reference.scope == ()}
    for item in ast.walk(tree):
        assignment_targets: tuple[ast.expr, ...]
        value_node: ast.expr | None
        if isinstance(item, ast.Assign):
            assignment_targets, value_node = tuple(item.targets), item.value
        elif isinstance(item, ast.AnnAssign):
            assignment_targets, value_node = (item.target,), item.value
        else:
            continue
        value = _string_expression_value(value_node, module_strings)
        for assignment_target in assignment_targets:
            for target in (node for node in ast.walk(assignment_target) if isinstance(node, ast.Name) and (item.lineno, node.id) in module_sites):
                normalized = target.id.lstrip("_").lower().replace("_", "")
                manifest_entries = tuple(value_node.values) if isinstance(value_node, ast.Dict) else tuple(entry.elts[1] for entry in value_node.elts if isinstance(entry, (ast.Tuple, ast.List)) and len(entry.elts) == 2) if isinstance(value_node, (ast.Tuple, ast.List)) else ()
                manifest_keys = tuple(value_node.keys) if isinstance(value_node, ast.Dict) else tuple(entry.elts[0] for entry in value_node.elts if isinstance(entry, (ast.Tuple, ast.List)) and len(entry.elts) == 2) if isinstance(value_node, (ast.Tuple, ast.List)) else ()
                has_identity_entry = any(_string_expression_value(key, module_strings) in _ALL_IDENTITY_NAMES for key in manifest_keys)
                if _identity_domain_binding(target.id) or (
                    not target.id.startswith("_") and normalized.endswith("domain")
                ):
                    handled_authority_sites.add((item.lineno, target.id))
                    values.add(
                        value
                        if value is not None
                        else f"<unresolved-authority-domain:{target.id}>"
                    )
                if _identity_manifest_binding(target.id, has_identity_entry):
                    handled_authority_sites.add((item.lineno, target.id))
                    values.update(_string_expression_value(entry, module_strings) or f"<unresolved-authority-domain:{target.id}>" for entry in manifest_entries)
                    if not manifest_entries:
                        values.add(f"<unresolved-authority-domain:{target.id}>")
                if value is None:
                    module_strings.pop(target.id, None)
                else:
                    module_strings[target.id] = value
    for binding in (binding for binding in analysis.bindings if binding.top_level and (binding.lineno, binding.name) not in handled_authority_sites and (_identity_domain_binding(binding.name) or _identity_manifest_binding(binding.name))):
        values.add(f"<unresolved-authority-domain:{binding.name}>")
    for mutation in (item for item in ast.walk(tree) if isinstance(item, (ast.AugAssign, ast.Delete))):
        targets = mutation.targets if isinstance(mutation, ast.Delete) else (mutation.target,)
        for mutation_target in targets:
            if isinstance(mutation_target, ast.Name) and (mutation.lineno, mutation_target.id) in module_sites and (
                _identity_domain_binding(mutation_target.id)
                or not mutation_target.id.startswith("_")
                and mutation_target.id.lower().replace("_", "").endswith("domain")
                or _identity_manifest_binding(mutation_target.id)
            ):
                values.add(f"<mutated-authority-domain:{mutation_target.id}>")
    call_scopes = {(item.lineno, item.spelling): item.scope for item in analysis.calls}
    call_targets = {(item.lineno, item.spelling): item.targets for item in analysis.calls}
    identity_functions = P4_MANIFEST.identity_functions
    for call in (item for item in ast.walk(tree) if isinstance(item, ast.Call) and item.args):
        site = (call.lineno, ast.unparse(call.func))
        resolved_targets = call_targets.get(site, frozenset())
        first = call.args[0]
        value = _string_expression_value(first, module_strings)
        scope = call_scopes.get(site, ())
        if _PROTOCOL_HASH_TARGET in resolved_targets and (
            scope in {(name,) for name in identity_functions}
            or value is not None
            and (
                value.startswith("validation_evidence_calibration_")
                or value.startswith("broader-calibration-history-selection/")
            )
        ):
            values.add(
                value
                if value is not None
                else f"<unresolved-authority-domain:{ast.unparse(first)}>"
            )
    return frozenset(values)


class RequiredCallMatch(NamedTuple):
    requirement: RequiredCall
    lineno: int
    spelling: str


def _active_required_calls(manifest: PhaseManifest) -> tuple[RequiredCall, ...]:
    requirements = _valid_required_call_entries(REQUIRED_CALLS)
    if type(REQUIRED_CALLS) is not tuple or len(requirements) != len(REQUIRED_CALLS):
        return ()
    phase_index = _PHASE_ORDER.index(manifest.phase)
    return tuple(requirement for requirement in requirements if _PHASE_ORDER.index(requirement.phase) <= phase_index)


def _qualified_import_target(node: ast.ImportFrom, item: ast.alias) -> str | None:
    if node.level or node.module is None:
        return None
    return f"{node.module}.{item.name}"


def _approved_required_call_import(manifest: PhaseManifest, node: ast.ImportFrom, item: ast.alias) -> bool:
    local = item.asname or item.name
    target = _qualified_import_target(node, item)
    return bool(local.startswith("_") and any(requirement.qualified_target == target and requirement.call_shape.target_binding in {"private-import", "phase-private-import"} for requirement in _active_required_calls(manifest)))


def _approved_required_call_binding(manifest: PhaseManifest, binding: qualified.SymbolBinding) -> bool:
    return bool(binding.top_level and binding.name.startswith("_") and binding.kind == "import" and any(binding.origins == frozenset({requirement.qualified_target}) and requirement.call_shape.target_binding in {"private-import", "phase-private-import"} for requirement in _active_required_calls(manifest)))


def _parameter_name(shape: CallShape, index: object) -> str | None:
    if type(index) is not int or not 0 <= index < len(shape.parameters):
        return None
    return shape.parameters[index].name


def _scientific_projection_attribute(node: ast.expr, field: str) -> bool:
    return bool(
        isinstance(node, ast.Attribute)
        and node.attr == field
        and isinstance(node.value, ast.Name)
        and node.value.id == "expected_projection"
    )


def _scientific_projection_list(node: ast.expr, field: str) -> bool:
    return bool(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "list"
        and len(node.args) == 1
        and not node.keywords
        and _scientific_projection_attribute(node.args[0], field)
    )


def _scientific_projection_pair_list(node: ast.expr, field: str) -> bool:
    if (
        not isinstance(node, ast.ListComp)
        or not isinstance(node.elt, ast.Call)
        or not isinstance(node.elt.func, ast.Name)
        or node.elt.func.id != "list"
        or len(node.elt.args) != 1
        or node.elt.keywords
        or not isinstance(node.elt.args[0], ast.Name)
        or len(node.generators) != 1
    ):
        return False
    generator = node.generators[0]
    return bool(
        isinstance(generator.target, ast.Name)
        and generator.target.id == "pair"
        and node.elt.args[0].id == "pair"
        and _scientific_projection_attribute(generator.iter, field)
        and not generator.ifs
        and generator.is_async == 0
    )


def _scientific_projection_mapping(
    node: ast.expr,
    fields: object,
) -> bool:
    if (
        type(fields) is not tuple
        or fields != PROJECTION_FIELDS["ScientificCalibrationSelectionProjection"]
        or not isinstance(node, ast.Dict)
        or len(node.keys) != len(fields)
        or len(node.values) != len(fields)
    ):
        return False
    list_fields = frozenset(
        {
            "effect_values",
            "source_effect_ids",
            "source_effect_payload_sha256",
            "source_oracle_key_ids",
            "source_replication_ids",
        }
    )
    pair_list_fields = frozenset(
        {"source_candidate_pairs", "source_observation_identities"}
    )
    for key, value, field in zip(node.keys, node.values, fields, strict=True):
        if (
            not isinstance(key, ast.Constant)
            or type(key.value) is not str
            or key.value != field
        ):
            return False
        if field in list_fields:
            valid = _scientific_projection_list(value, field)
        elif field in pair_list_fields:
            valid = _scientific_projection_pair_list(value, field)
        else:
            valid = _scientific_projection_attribute(value, field)
        if not valid:
            return False
    return True


def _expression_matches(node: ast.expr, constraint: ExpressionConstraint, shape: CallShape) -> bool:
    match constraint.kind:
        case "literal":
            return isinstance(constraint.value, str) and isinstance(node, ast.Constant) and _literal_exact(node.value, constraint.value)
        case "name":
            return bool(
                isinstance(constraint.value, str)
                and isinstance(node, ast.Name)
                and node.id == constraint.value
            )
        case "parameter":
            parameter = _parameter_name(shape, constraint.value)
            return parameter is not None and isinstance(node, ast.Name) and node.id == parameter
        case "ordered-parameter-dict":
            if not isinstance(constraint.value, tuple) or not isinstance(node, ast.Dict):
                return False
            entries = constraint.value
            if len(node.keys) != len(entries) or len(node.values) != len(entries):
                return False
            for key_node, value_node, entry in zip(node.keys, node.values, entries, strict=True):
                if not isinstance(entry, tuple) or len(entry) != 2 or not isinstance(entry[0], str) or type(entry[1]) is not int:
                    return False
                parameter = _parameter_name(shape, entry[1])
                if parameter is None or not isinstance(key_node, ast.Constant) or not _literal_exact(key_node.value, entry[0]) or not isinstance(value_node, ast.Name) or value_node.id != parameter:
                    return False
            return True
        case "scientific-projection-mapping":
            return _scientific_projection_mapping(node, constraint.value)
        case _:
            return False


def _owner_matches(owner: ast.FunctionDef, shape: CallShape) -> bool:
    if not shape.parameters:
        return True
    if not shape.parameters or not _exact_positional_parameters(owner, tuple(parameter.name for parameter in shape.parameters)):
        return False
    parameters = (*owner.args.posonlyargs, *owner.args.args)
    for node, constraint in zip(parameters, shape.parameters, strict=True):
        if constraint.annotation is not None and (not isinstance(node.annotation, ast.Name) or node.annotation.id != constraint.annotation):
            return False
    return True


def _arguments_match(call: ast.Call, shape: CallShape) -> bool:
    if len(call.args) != len(shape.positional) or len(call.keywords) != len(shape.keywords):
        return False
    if not all(_expression_matches(node, constraint, shape) for node, constraint in zip(call.args, shape.positional, strict=True)):
        return False
    return all(keyword.arg == constraint.name and _expression_matches(keyword.value, constraint.expression, shape) for keyword, constraint in zip(call.keywords, shape.keywords, strict=True))


def _result_matches(owner: ast.FunctionDef, call: ast.Call, shape: CallShape) -> bool:
    match shape.result_kind:
        case "bound-once":
            target_name = shape.compared_parameter
            if type(target_name) is not str:
                return False
            bindings = tuple(
                node
                for node in ast.walk(owner)
                if isinstance(node, (ast.Assign, ast.AnnAssign))
                and node.value is call
            )
            if len(bindings) != 1:
                return False
            binding = bindings[0]
            targets = (
                tuple(binding.targets)
                if isinstance(binding, ast.Assign)
                else (binding.target,)
            )
            stores = tuple(
                node
                for target in targets
                for node in ast.walk(target)
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
            )
            return bool(
                len(stores) == 1
                and stores[0].id == target_name
                and sum(
                    1
                    for node in ast.walk(owner)
                    if isinstance(node, ast.Name)
                    and isinstance(node.ctx, ast.Store)
                    and node.id == target_name
                )
                == 1
                and any(
                    isinstance(node, ast.Name)
                    and isinstance(node.ctx, ast.Load)
                    and node.id == target_name
                    for node in ast.walk(owner)
                )
            )
        case "recomputed-value":
            return bool(shape.compared_parameter is None and len(owner.body) == 1 and isinstance(owner.body[0], ast.Return) and owner.body[0].value is call)
        case "validate-carried":
            carried = _parameter_name(shape, shape.compared_parameter)
            if carried is None or len(owner.body) != 1 or not isinstance(owner.body[0], ast.Return):
                return False
            comparison = owner.body[0].value
            return bool(isinstance(comparison, ast.Compare) and comparison.left is call and len(comparison.ops) == 1 and isinstance(comparison.ops[0], ast.Eq) and len(comparison.comparators) == 1 and isinstance(comparison.comparators[0], ast.Name) and comparison.comparators[0].id == carried)
        case _:
            return False


def _target_binding_matches(tree: ast.Module, call: ast.Call, requirement: RequiredCall) -> bool:
    shape = requirement.call_shape
    match shape.target_binding:
        case "canonical-local":
            return bool(isinstance(call.func, ast.Name) and call.func.id == requirement.qualified_target.rsplit(".", 1)[-1])
        case "private-import" | "phase-private-import":
            if not isinstance(call.func, ast.Name) or not call.func.id.startswith("_"):
                return False
            top_level_match = any(isinstance(node, ast.ImportFrom) and any((item.asname or item.name) == call.func.id and _qualified_import_target(node, item) == requirement.qualified_target for item in node.names) for node in tree.body)
            if top_level_match:
                return True
            if shape.target_binding != "phase-private-import":
                return False
            target_module, target_name = requirement.qualified_target.rsplit(".", 1)
            expected_local = f"_{target_name}"
            if call.func.id != expected_local:
                return False
            owners = tuple(
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef)
                and any(candidate is call for candidate in ast.walk(node))
            )
            if len(owners) != 1:
                return False
            owner = owners[0]
            exact_imports = tuple(
                node
                for node in owner.body
                if isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module == target_module
                and len(node.names) == 1
                and node.names[0].name == target_name
                and node.names[0].asname == expected_local
                and node.lineno < call.lineno
            )
            if len(exact_imports) != 1:
                return False
            rebound = any(
                isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Store)
                and node.id == expected_local
                for node in ast.walk(owner)
            )
            duplicate_import = any(
                isinstance(node, (ast.Import, ast.ImportFrom))
                and node is not exact_imports[0]
                and any(
                    (item.asname or item.name) == expected_local
                    for item in node.names
                )
                for node in ast.walk(owner)
            )
            return not rebound and not duplicate_import
        case _:
            return False

def _call_shape_matches_in_owner(tree: ast.Module, analysis: qualified.QualifiedSymbolAnalysis, requirement: object, owner_name: object) -> frozenset[RequiredCallMatch]:
    if not _required_call_metadata_is_valid(requirement) or type(owner_name) is not str:
        return frozenset()
    validated = cast(RequiredCall, requirement)
    shape = validated.call_shape
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == owner_name]
    if len(functions) != 1 or not _owner_matches(functions[0], shape):
        return frozenset()
    owner = functions[0]
    call_nodes: dict[tuple[int, str], list[ast.Call]] = {}
    for node in (item for item in ast.walk(tree) if isinstance(item, ast.Call)):
        call_nodes.setdefault((node.lineno, ast.unparse(node.func)), []).append(node)
    matched: set[RequiredCallMatch] = set()
    for resolved in analysis.calls:
        if resolved.scope != (owner_name,) or resolved.targets != frozenset({validated.qualified_target}):
            continue
        candidates = call_nodes.get((resolved.lineno, resolved.spelling), [])
        if len(candidates) != 1:
            continue
        call = candidates[0]
        if _target_binding_matches(tree, call, validated) and _arguments_match(call, shape) and _result_matches(owner, call, shape):
            matched.add(RequiredCallMatch(validated, resolved.lineno, resolved.spelling))
    return frozenset(matched)


def _required_call_matches(tree: ast.Module, analysis: qualified.QualifiedSymbolAnalysis, requirement: object) -> frozenset[RequiredCallMatch]:
    if not _required_call_metadata_is_valid(requirement):
        return frozenset()
    if type(requirement) is not RequiredCall or type(requirement.call_shape) is not CallShape:
        return frozenset()
    return _call_shape_matches_in_owner(tree, analysis, requirement, requirement.owner)


def _canonical_required_call_matches(tree: ast.Module, manifest: PhaseManifest, analysis: qualified.QualifiedSymbolAnalysis) -> frozenset[RequiredCallMatch]:
    if _call_metadata_manifest_findings():
        return frozenset()
    return frozenset(match for requirement in _active_required_calls(manifest) for match in _required_call_matches(tree, analysis, requirement))


def _equivalent_validation_call_matches(tree: ast.Module, analysis: qualified.QualifiedSymbolAnalysis, requirement: object) -> frozenset[RequiredCallMatch]:
    if not _required_call_metadata_is_valid(requirement):
        return frozenset()
    validated = cast(RequiredCall, requirement)
    shape = validated.call_shape
    return frozenset(match for owner_name in frozenset(call.scope[0] for call in analysis.calls if len(call.scope) == 1 and call.targets == frozenset({validated.qualified_target})) for match in _call_shape_matches_in_owner(tree, analysis, validated, owner_name)) if shape.validation_only is True else frozenset()
# fmt: on


def _raw_effect_wrapper_return(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> ast.Return | None:
    body = function.body
    result = body[-1] if body else None
    if not isinstance(result, ast.Return) or len(body) not in {1, 2}:
        return None
    exact_import = f"from {_REPLAY} import raw_effect_sha256 as _raw_effect_sha256"
    return result if len(body) == 1 or ast.unparse(body[0]) == exact_import else None


def _manifest_findings(
    tree: ast.Module,
    manifest: PhaseManifest,
    analysis: qualified.QualifiedSymbolAnalysis,
    required_call_matches: frozenset[RequiredCallMatch],
) -> set[Finding]:
    findings: set[Finding] = set()
    class_nodes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    function_nodes = [
        node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    classes = {node.name: node for node in class_nodes}
    functions = {node.name: node for node in function_nodes}
    if len(classes) != len(class_nodes) or len(functions) != len(function_nodes):
        findings.add(Finding("duplicate-public-definition", manifest.phase))
    public_classes = frozenset(name for name in classes if not name.startswith("_"))
    public_functions = frozenset(name for name in functions if not name.startswith("_"))
    expected_functions = manifest.identity_functions | manifest.public_validators
    allowed_private_classes = (
        frozenset({"_P3SelectionInput"}) if manifest.phase in {"P3", "P4"} else frozenset()
    )
    if (
        not manifest.projection_classes <= frozenset(classes)
        or frozenset(classes) - manifest.projection_classes - allowed_private_classes
    ):
        findings.add(Finding("top-level-class-surface", manifest.phase))
    public_bindings = tuple(
        (binding.name, binding.kind)
        for binding in analysis.binding_events
        if binding.top_level and not binding.name.startswith("_")
    )
    expected_bindings = {
        **dict.fromkeys(manifest.projection_classes, "class"),
        **dict.fromkeys(expected_functions, "function"),
    }
    if public_classes != manifest.projection_classes:
        findings.add(Finding("public-class-surface", manifest.phase))
    if public_functions != expected_functions:
        findings.add(Finding("public-function-surface", manifest.phase))
    if (
        public_classes | public_functions != (manifest.projection_classes | expected_functions)
        or len(public_bindings) != len(expected_bindings)
        or dict(public_bindings) != expected_bindings
    ):
        findings.add(Finding("public-export-surface", manifest.phase))

    # fmt: off
    schemas = dict(manifest.schemas)
    for name, schema_expected in schemas.items():
        class_node = classes.get(name)
        if class_node is None:
            continue
        if manifest.phase == "P1" and name in _P1_PROJECTION_SHAPES and not _p1_projection_shape_is_exact(class_node, analysis):
            findings.add(Finding("projection-class-shape", name))
        assignments = _assigned_literals(class_node)
        field_events = tuple(binding for binding in analysis.binding_events if binding.scope == (name,) and binding.name in PROJECTION_FIELDS[name])
        if _fields(class_node) != PROJECTION_FIELDS[name] or len(_fields(class_node)) != PROJECTION_FIELD_COUNTS[name] or len(field_events) != PROJECTION_FIELD_COUNTS[name]:
            findings.add(Finding("projection-field-surface", name))
        if schema_expected is None and any(isinstance(item, ast.Name) and item.id == "schema_version" or isinstance(item, ast.Attribute) and item.attr == "schema_version" or isinstance(item, ast.Constant) and item.value == "schema_version" or isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "schema_version" for item in ast.walk(class_node)):
            findings.add(Finding("scientific-selection-schema-field", name))
        if schema_expected is not None:
            events = tuple(binding for binding in analysis.binding_events if binding.scope == (name,) and binding.name == "schema_version")
            schema_field = next((item for item in class_node.body if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) and item.target.id == "schema_version"), None)
            schema_is_exact = _annotation_is(schema_field.annotation, f"Literal[{schema_expected!r}]") and schema_field.value is None if schema_field is not None else _literal_exact(assignments.get("schema_version"), schema_expected)
            if len(events) != 1 or events[0].kind not in {"assign", "annassign"} or not schema_is_exact or any(isinstance(node, ast.Delete) and any(isinstance(target, ast.Name) and target.id == "schema_version" or isinstance(target, ast.Attribute) and target.attr == "schema_version" for target in node.targets) for node in ast.walk(class_node)):
                findings.add(Finding("schema-literal", name))
    strings = _strings(tree)
    observed_schemas = frozenset(
        value for value in strings if value.startswith("broader-replication-calibration-")
    )
    if observed_schemas != frozenset(value for value in schemas.values() if value):
        findings.add(Finding("schema-set", manifest.phase))
    domains = dict(manifest.identity_domains)
    observed_domains = _authority_domain_literals(tree, analysis)
    if observed_domains != frozenset(domains.values()):
        findings.add(Finding("identity-domain-set", manifest.phase))
    for name in manifest.identity_functions:
        if name in functions and not _identity_hash_is_exact(
            functions[name],
            analysis,
            domains[name],
            functions,
            manifest.phase == "P1" and name in _P1_IDENTITY_PREIMAGES,
        ):
            findings.add(Finding("identity-domain", name))
    for key, fixed_expected in FUTURE_FIXED_LITERALS:
        if key not in _PHASE_FIXED_LITERAL_KEYS[manifest.phase]:
            continue
        if not _literal_relation(tree, analysis, key, fixed_expected):
            findings.add(Finding("fixed-literal", key))
    raw_helper, replay_helper = f"{_REPLAY}.raw_effect_sha256", f"{_REPLAY}.replay_calibration_history_selection"
    call_targets = {(call.lineno, call.spelling): call.targets for call in analysis.calls}
    reference_targets = {(item.lineno, item.spelling): item.targets for item in analysis.references}
    call_nodes = {(node.lineno, ast.unparse(node.func)): node for node in ast.walk(tree) if isinstance(node, ast.Call)}
    raw_calls = tuple(call for call in analysis.calls if raw_helper in call.targets)
    raw_sites = {(call.lineno, call.spelling) for call in raw_calls if call.targets == frozenset({raw_helper}) and len(call.scope) == 1 and (function := functions.get(call.scope[0])) is not None and (wrapper_return := _raw_effect_wrapper_return(function)) is not None and (node := call_nodes.get((call.lineno, call.spelling))) is not None and node is wrapper_return.value and len(_parameters(function)) == 1 and _parameters(function)[0].arg == "effect" and (annotation := _parameters(function)[0].annotation) is not None and reference_targets.get((annotation.lineno, ast.unparse(annotation))) == frozenset({"research_decision_engine.belief_models.MatchedEffectObservation"}) and not function.args.defaults and function.args.vararg is None and function.args.kwarg is None and len(node.args) == 1 and isinstance(node.args[0], ast.Name) and node.args[0].id == "effect" and not node.keywords}
    replay_calls = tuple(call for call in analysis.calls if replay_helper in call.targets)
    call_scopes = {(call.lineno, call.spelling): call.scope for call in analysis.calls}
    binding_scopes = {(binding.lineno, binding.name): binding.scope for binding in analysis.binding_events}
    candidate_replay_sites = frozenset((match.lineno, match.spelling) for match in required_call_matches if match.requirement.qualified_target == replay_helper)
    parents = {
        id(child): parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    scoped_binding_lines: dict[tuple[tuple[str, ...], str], list[int]] = {}
    for binding in analysis.binding_events:
        scoped_binding_lines.setdefault((binding.scope, binding.name), []).append(
            binding.lineno
        )
    required_replay_names = frozenset(
        cast(str, keyword.expression.value)
        for requirement in _active_required_calls(manifest)
        if requirement.qualified_target == replay_helper
        for keyword in requirement.call_shape.keywords
        if keyword.expression.kind == "name"
    )

    def replay_site_is_owned(site: tuple[int, str]) -> bool:
        node = call_nodes.get(site)
        if node is None:
            return False
        scope = call_scopes.get(site, ())
        if len(scope) != 1:
            return False
        assignment = parents.get(id(node))
        if not isinstance(assignment, (ast.Assign, ast.AnnAssign)) or assignment.value is not node:
            return False
        container = parents.get(id(assignment))
        owner = functions.get(scope[0])
        structurally_owned = container is owner or (
            isinstance(container, (ast.Try, ast.TryStar))
            and assignment in container.body
            and parents.get(id(container)) is owner
        )
        return bool(
            structurally_owned
            and all(
                any(
                    line <= node.lineno
                    for binding_scope in (scope, ())
                    for line in scoped_binding_lines.get((binding_scope, name), ())
                )
                for name in required_replay_names
            )
        )

    matched_replay_sites = frozenset(
        site for site in candidate_replay_sites if replay_site_is_owned(site)
    )
    replay_results = {(scope, target.id) for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Call) and (node.value.lineno, ast.unparse(node.value.func)) in matched_replay_sites for target in (tuple(node.targets) if isinstance(node, ast.Assign) else (node.target,)) if isinstance(target, ast.Name) and len(scope := binding_scopes.get((node.lineno, target.id), ())) == 1}
    scientific_calls = tuple(node for node in ast.walk(tree) if isinstance(node, ast.Call) and call_targets.get((node.lineno, ast.unparse(node.func))) == frozenset({f"{CANONICAL_MODULE}.ScientificCalibrationSelectionProjection"}))
    replay_supplied_scientific = tuple(node for node in scientific_calls if len(scope := call_scopes.get((node.lineno, ast.unparse(node.func)), ())) == 1 and any(isinstance(item, ast.Name) and (scope, item.id) in replay_results for keyword in node.keywords for item in ast.walk(keyword.value)))
    findings.update({Finding("raw-digest-provenance", "raw_effect_sha256")} if len(raw_sites) != len(raw_calls) or len(raw_sites) > 1 else ())
    findings.update({Finding("scientific-selection-provenance", "ScientificCalibrationSelectionProjection")} if replay_supplied_scientific else ())
    findings.update(Finding("generic-replay-authority", call.spelling) for call in replay_calls if (call.lineno, call.spelling) not in matched_replay_sites)
    findings.update(Finding("positional-projection-construction", ast.unparse(node.func)) for node in ast.walk(tree) if isinstance(node, ast.Call) and node.args and {target.rsplit(".", 1)[-1] for target in call_targets.get((node.lineno, ast.unparse(node.func)), frozenset())} & manifest.projection_classes)
    assigned_values, construction_literals = _assigned_literals(tree), {("CalibrationSelectionProjection", "calibration_namespace"): dict(FUTURE_FIXED_LITERALS)["calibration_namespace"], ("CalibrationSelectionProjection", "evidence_contract_checkpoint"): dict(FUTURE_FIXED_LITERALS)["evidence_contract_checkpoint"], ("CalibrationSelectionProjection", "protocol_checkpoint"): dict(FUTURE_FIXED_LITERALS)["protocol_checkpoint"], ("CalibrationSelectionProjection", "study_id"): dict(FUTURE_FIXED_LITERALS)["study"]}
    projection_constructions = tuple((node, min({target.rsplit(".", 1)[-1] for target in call_targets.get((node.lineno, ast.unparse(node.func)), frozenset())} & manifest.projection_classes)) for node in ast.walk(tree) if isinstance(node, ast.Call) and {target.rsplit(".", 1)[-1] for target in call_targets.get((node.lineno, ast.unparse(node.func)), frozenset())} & manifest.projection_classes)
    findings.update(Finding("projection-construction-surface", name) for node, name in projection_constructions if node.args or len(node.keywords) != PROJECTION_FIELD_COUNTS[name] or tuple(keyword.arg for keyword in node.keywords) != PROJECTION_FIELDS[name])
    findings.update(Finding("fixed-literal", keyword.arg) for node, name in projection_constructions for keyword in node.keywords if keyword.arg is not None and (expected := construction_literals.get((name, keyword.arg))) is not None and not _literal_exact(keyword.value.value if isinstance(keyword.value, ast.Constant) else assigned_values.get(keyword.value.id) if isinstance(keyword.value, ast.Name) else None, expected))
    findings.update(Finding("schema-literal", name) for node, name in projection_constructions for keyword in node.keywords if keyword.arg == "schema_version" and (schema_expected := schemas.get(name)) is not None and not _literal_exact(keyword.value.value if isinstance(keyword.value, ast.Constant) else assigned_values.get(keyword.value.id) if isinstance(keyword.value, ast.Name) else None, schema_expected) and not (name == "CalibrationSourceObservationProjection" and isinstance(keyword.value, ast.Call) and ast.unparse(keyword.value.func) == "_source_schema" and len(keyword.value.args) == 1 and not keyword.value.keywords))
    phase_helpers = frozenset().union(*_PHASE_ALLOWED_HELPERS.values())
    called_targets = frozenset(target for call in analysis.calls for target in call.targets if target == raw_helper and (call.lineno, call.spelling) in raw_sites or target == replay_helper and (call.lineno, call.spelling) in matched_replay_sites)
    imported_targets = frozenset(origin for binding in analysis.imports for origin in binding.origins)
    phase_targets = (frozenset(target for call in analysis.calls for target in call.targets) | imported_targets) & phase_helpers
    matched_requirements = frozenset(match.requirement for match in required_call_matches)
    findings.update(Finding("required-pure-helper", target) for target in _PHASE_REQUIRED_HELPERS[manifest.phase] - called_targets)
    findings.update(Finding("required-pure-helper", requirement.qualified_target) for requirement in _active_required_calls(manifest) if requirement not in matched_requirements)
    findings.update(Finding("unexpected-phase-helper", target) for target in phase_targets - _PHASE_ALLOWED_HELPERS[manifest.phase])
    for name in expected_functions:
        function_node = functions.get(name)
        if function_node is None:
            continue
        if function_node.args.vararg is not None or function_node.args.kwarg is not None:
            findings.add(Finding("variadic-public-api", name))
        for parameter in _parameters(function_node):
            if (
                _caller_controlled(parameter.arg)
                or _annotation_names(parameter.annotation) & _LIVE_ANNOTATIONS
            ):
                findings.add(Finding("caller-authority-parameter", f"{name}:{parameter.arg}"))
        if _annotation_names(function_node.returns) & _LIVE_ANNOTATIONS:
            findings.add(Finding("live-capability-return", name))
    for function_node in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
        if functions.get(function_node.name) is function_node and function_node.name in expected_functions:
            continue
        if _annotation_names(function_node.returns) & _LIVE_ANNOTATIONS or any(_caller_controlled(parameter.arg) or _annotation_names(parameter.annotation) & _LIVE_ANNOTATIONS for parameter in _parameters(function_node)):
            findings.add(Finding("private-caller-authority-parameter", function_node.name))
    for name in manifest.projection_classes:
        class_node = classes.get(name)
        if class_node and any((isinstance(item.target, ast.Name) and any(token.replace("_", "") in item.target.id.lower().replace("_", "") for token in _CALLABLE_PARAMETER_NAMES)) or bool(_annotation_names(item.annotation) & _LIVE_ANNOTATIONS) for item in class_node.body if isinstance(item, ast.AnnAssign)):
            findings.add(Finding("live-capability-field", name))
    for name in expected_functions:
        function_node = functions.get(name)
        if function_node and function_node.decorator_list:
            findings.add(Finding("decorated-public-api", name))
    for name in manifest.projection_classes:
        class_node = classes.get(name)
        if class_node is None:
            continue
        if class_node.bases:
            findings.add(Finding("unapproved-projection-base", name))
        for decorator in class_node.decorator_list:
            target_node = decorator.func if isinstance(decorator, ast.Call) else decorator
            targets = reference_targets.get((target_node.lineno, ast.unparse(target_node)), frozenset())
            if targets != {"dataclasses.dataclass"}:
                findings.add(Finding("unapproved-projection-decorator", name))
    for reference in analysis.references:
        if any(target.rsplit(".", 1)[-1] in _LIVE_ANNOTATIONS for target in reference.targets):
            findings.add(Finding("live-capability-reference", reference.spelling))
    # fmt: on
    return findings


def _import_findings(tree: ast.Module, manifest: PhaseManifest) -> set[Finding]:
    findings: set[Finding] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                root = item.name.split(".", 1)[0]
                exact_p3_private_module = (
                    manifest.phase in {"P3", "P4"}
                    and len(node.names) == 1
                    and item.name in _P3_PRIVATE_MODULE_IMPORTS
                    and item.asname == _P3_PRIVATE_MODULE_IMPORTS[item.name]
                )
                if not exact_p3_private_module:
                    code = (
                        "forbidden-import"
                        if root in FORBIDDEN_IMPORT_ROOTS
                        or item.name in FORBIDDEN_IMPORT_MODULES
                        or item.name == "hashlib"
                        and manifest.phase not in {"P3", "P4"}
                        else "whole-module-import"
                    )
                    findings.add(Finding(code, item.name))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".", 1)[0]
            if node.level:
                findings.add(Finding("relative-import", module))
            if root in FORBIDDEN_IMPORT_ROOTS or module in FORBIDDEN_IMPORT_MODULES:
                findings.add(Finding("forbidden-import", module))
            allowed = ALLOWED_IMPORTS.get(module, frozenset())
            for item in node.names:
                target = _qualified_import_target(node, item)
                phase_gated_required_import = any(
                    requirement.qualified_target == target
                    and requirement.call_shape.target_binding == "phase-private-import"
                    for requirement in REQUIRED_CALLS
                )
                if (
                    item.name == "*"
                    or item.name not in allowed
                    or phase_gated_required_import
                    and not _approved_required_call_import(manifest, node, item)
                ):
                    findings.add(Finding("unapproved-import", f"{module}.{item.name}"))
                local = item.asname or item.name
                if module != "__future__" and not local.startswith("_"):
                    findings.add(Finding("public-import-binding", local))
                if item.name in _ALL_PROJECTIONS | _ALL_IDENTITIES:
                    findings.add(Finding("stage2f-import-alias", item.name))
    return findings


# fmt: off
def _type_only_nodes(tree: ast.Module) -> frozenset[ast.AST]:
    roots: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            roots.extend(item.annotation for item in _parameters(node) if item.annotation is not None)
            if node.returns is not None:
                roots.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            roots.append(node.annotation)
        elif hasattr(ast, "TypeAlias") and isinstance(node, ast.TypeAlias):
            roots.append(node.value)
    return frozenset(item for root in roots for item in ast.walk(root))


def _exact_type_check_sites(tree: ast.Module) -> frozenset[tuple[int, str]]:
    return frozenset((operand.lineno, ast.unparse(operand.func)) for node in ast.walk(tree) if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], (ast.Is, ast.IsNot)) for operand in (node.left, *node.comparators) if isinstance(operand, ast.Call) and isinstance(operand.func, ast.Name) and operand.func.id == "type" and len(operand.args) == 1 and not operand.keywords)


def _exact_type_reference_sites(tree: ast.Module) -> frozenset[tuple[int, str]]:
    return frozenset((item.lineno, ast.unparse(item)) for node in ast.walk(tree) if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], (ast.Is, ast.IsNot)) and any(isinstance(operand, ast.Call) and isinstance(operand.func, ast.Name) and operand.func.id == "type" and len(operand.args) == 1 and not operand.keywords for operand in (node.left, *node.comparators)) for item in (node.left, *node.comparators) if isinstance(item, (ast.Name, ast.Attribute)))


def _raise_constructor_sites(tree: ast.Module) -> frozenset[tuple[int, str]]:
    return frozenset((node.exc.lineno, ast.unparse(node.exc.func)) for node in ast.walk(tree) if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name) and node.exc.func.id == "ValueError" and not node.exc.keywords)


def _matched_effect_to_dict_sites(
    tree: ast.Module, analysis: qualified.QualifiedSymbolAnalysis,
) -> frozenset[tuple[int, str]]:
    call_targets = {(call.lineno, call.spelling): call.targets for call in analysis.calls}
    reference_targets = {(reference.lineno, reference.spelling): reference.targets for reference in analysis.references}
    sites: set[tuple[int, str]] = set()
    expected_target = f"{_HISTORY}.expected_calibration_effect"
    matched_target = "research_decision_engine.belief_models.MatchedEffectObservation"
    for function in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
        effects = {parameter.arg for parameter in _parameters(function) if parameter.annotation is not None and reference_targets.get((parameter.annotation.lineno, ast.unparse(parameter.annotation))) == frozenset({matched_target})}
        effects.update(target.id for assignment in ast.walk(function) if isinstance(assignment, (ast.Assign, ast.AnnAssign)) and isinstance(assignment.value, ast.Call) and call_targets.get((assignment.value.lineno, ast.unparse(assignment.value.func))) == frozenset({expected_target}) for target in (tuple(assignment.targets) if isinstance(assignment, ast.Assign) else (assignment.target,)) if isinstance(target, ast.Name))
        sites.update((call.lineno, ast.unparse(call.func)) for call in ast.walk(function) if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "to_dict" and isinstance(call.func.value, ast.Name) and call.func.value.id in effects and not call.args and not call.keywords)
    return frozenset(sites)


def _exact_tuple_accumulator(tree: ast.Module, symbol: str, lineno: int) -> bool:
    initial = next((node for node in ast.walk(tree) if isinstance(node, ast.AnnAssign) and node.lineno == lineno and isinstance(node.target, ast.Name) and node.target.id == symbol and isinstance(node.value, ast.Tuple) and not node.value.elts), None)
    if initial is None:
        return False
    owner = next((node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and initial in frozenset(ast.walk(node))), None)
    if owner is None:
        return False
    updates = tuple(node for node in ast.walk(owner) if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == symbol)
    return bool(updates and all(isinstance(node.value, ast.Tuple) and any(isinstance(item, ast.Starred) and isinstance(item.value, ast.Name) and item.value.id == symbol for item in node.value.elts) for node in updates))


def _dynamic_analysis_codes(
    tree: ast.Module,
    analysis: qualified.QualifiedSymbolAnalysis,
    approved_unresolved_sites: frozenset[tuple[int, str]],
) -> frozenset[str]:
    return frozenset(finding.code for finding in analysis.findings if finding.code in _DYNAMIC_FINDINGS and not (finding.code == "alias-cycle" and _exact_tuple_accumulator(tree, finding.symbol, finding.lineno)) and not (finding.code == "unresolved-sensitive-provenance" and (finding.lineno, finding.symbol.removeprefix("call:")) in approved_unresolved_sites))
# fmt: on


def _future_source_findings_with_session(
    source: str,
    manifest: PhaseManifest,
    session: _AnalysisSession,
) -> tuple[Finding, ...]:
    """Analyze one hypothetical canonical module without executing it."""

    metadata_findings = _call_metadata_manifest_findings()
    if metadata_findings:
        return metadata_findings
    if manifest.phase == "C0":
        return (Finding("c0-production-module-present", CANONICAL_RELATIVE_PATH),)
    try:
        facts = session.source_analysis(source, module_name=CANONICAL_MODULE, owned=_PHASE_ORDER.index(manifest.phase) >= _PHASE_ORDER.index("P2"))  # fmt: skip
    except SyntaxError as error:
        return (Finding("invalid-syntax", f"{error.lineno}:{error.offset}"),)
    tree = facts.tree
    analysis = facts.analysis
    required_call_matches = _canonical_required_call_matches(tree, manifest, analysis)
    matched_effect_to_dict_sites = _matched_effect_to_dict_sites(tree, analysis)
    p3_external_sites = (
        _p3_approved_external_call_sites(tree, analysis)
        if manifest.phase in {"P3", "P4"}
        else frozenset()
    )
    findings = _manifest_findings(
        tree, manifest, analysis, required_call_matches
    ) | _import_findings(tree, manifest)
    analysis_codes = _dynamic_analysis_codes(
        tree,
        analysis,
        matched_effect_to_dict_sites | p3_external_sites,
    )
    if analysis_codes & _DYNAMIC_FINDINGS:
        findings.add(Finding("dynamic-surface", ",".join(sorted(analysis_codes))))
    dynamic_class_aliases = _dynamic_class_aliases(tree, analysis)
    # fmt: off
    for binding in analysis.bindings:
        approved_required_call_binding = _approved_required_call_binding(manifest, binding)
        if binding.name.replace("_", "").lower() in {name.replace("_", "").lower() for name in FORBIDDEN_BINDINGS}:
            findings.add(Finding("later-stage-binding", binding.name))
        if binding.top_level and binding.name in dynamic_class_aliases:
            findings.add(Finding("top-level-class-surface", manifest.phase))
        if binding.name.replace("_", "").lower() in {name.replace("_", "").lower() for name in _FORBIDDEN_IDENTITY_ALIASES}:
            findings.add(Finding("premature-identity-alias", binding.name))
        if binding.top_level and binding.name in {"__getattr__", "__dir__"}:
            findings.add(Finding("dynamic-module-hook", binding.name))
        if binding.name.replace("_", "").lower() in {name.replace("_", "").lower() for name in _ALL_PROJECTIONS | _ALL_IDENTITY_NAMES} and not (approved_required_call_binding or binding.top_level and binding.name in _ALL_PROJECTIONS | _ALL_IDENTITY_NAMES and binding.kind in {"class", "function"} or len(binding.scope) == 1 and binding.scope[0] in manifest.projection_classes and binding.name in PROJECTION_FIELDS[binding.scope[0]] and binding.kind in {"assign", "annassign"}):
            findings.add(Finding("stage2f-assignment-alias", binding.name))
        if any(origin.rsplit(".", 1)[-1] in _ALL_PROJECTIONS | _ALL_IDENTITY_NAMES for origin in binding.origins):
            origin_names = frozenset(origin.rsplit(".", 1)[-1] for origin in binding.origins)
            if not approved_required_call_binding and (binding.name not in origin_names or binding.kind not in {"class", "function"}):
                findings.add(Finding("stage2f-assignment-alias", binding.name))
    references = {(reference.lineno, reference.spelling): reference.targets for reference in analysis.references}
    type_only_nodes = _type_only_nodes(tree)
    type_only_sites = {(node.lineno, ast.unparse(node)) for node in type_only_nodes if isinstance(node, (ast.Name, ast.Attribute))}
    exact_type_reference_sites = _exact_type_reference_sites(tree)
    p3_exact_h64 = (
        _top_level_function(tree, "_exact_h64")
        if manifest.phase in {"P3", "P4"}
        else None
    )
    p3_exact_h64_nodes = (
        frozenset(ast.walk(p3_exact_h64)) if p3_exact_h64 is not None else frozenset()
    )
    findings.update(Finding("stage2f-mapping-alias", reference.spelling) for reference in analysis.references if reference.scope == () and (reference.lineno, reference.spelling) not in type_only_sites and {target.rsplit(".", 1)[-1] for target in reference.targets} & (_ALL_PROJECTIONS | _ALL_IDENTITY_NAMES))
    for container in (node for node in ast.walk(tree) if node not in type_only_nodes and isinstance(node, (ast.Tuple, ast.List, ast.Set, ast.Dict, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.IfExp, ast.BoolOp, ast.Subscript, ast.NamedExpr))):
        for reference_node in (item for item in ast.walk(container) if isinstance(item, (ast.Name, ast.Attribute))):
            if reference_node not in p3_exact_h64_nodes and (reference_node.lineno, ast.unparse(reference_node)) not in exact_type_reference_sites and {target.rsplit(".", 1)[-1] for target in references.get((reference_node.lineno, ast.unparse(reference_node)), frozenset())} & (_ALL_PROJECTIONS | _ALL_IDENTITY_NAMES):
                findings.add(Finding("stage2f-mapping-alias", ast.unparse(reference_node)))
    for class_node in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        if any({target.rsplit(".", 1)[-1] for target in references.get((base.lineno, ast.unparse(base)), frozenset())} & _ALL_PROJECTIONS for base in class_node.bases):
            findings.add(Finding("stage2f-subclass-alias", class_node.name))
    identity_sites = {(call.lineno, call.spelling) for call in analysis.calls if {target.rsplit(".", 1)[-1] for target in call.targets} & _ALL_IDENTITY_NAMES}
    for function in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name not in manifest.identity_functions | manifest.public_validators):
        assignments = [(tuple(node.targets), node.value) if isinstance(node, ast.Assign) else ((node.target,), node.value) for node in ast.walk(function) if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None]
        derived = {target.id for targets, value in assignments if isinstance(value, ast.Call) and (value.lineno, ast.unparse(value.func)) in identity_sites or not isinstance(value, ast.Compare) and any(isinstance(item, ast.Attribute) and item.attr in {"selection_identity", "selector_result_identity"} for item in ast.walk(value)) for target in targets if isinstance(target, ast.Name)}
        for _ in assignments:
            derived.update(target.id for targets, value in assignments if isinstance(value, ast.Name) and value.id in derived or isinstance(value, (ast.Tuple, ast.List, ast.Set, ast.Dict, ast.IfExp, ast.BoolOp, ast.Subscript, ast.NamedExpr)) and any(isinstance(item, ast.Name) and item.id in derived for item in ast.walk(value)) for target in targets if isinstance(target, ast.Name))
        if not (manifest.phase in {"P3", "P4"} and function.name == "_exact_h64") and any(node.value is not None and (isinstance(node.value, ast.Call) and (node.value.lineno, ast.unparse(node.value.func)) in identity_sites or isinstance(node.value, ast.Name) and node.value.id in derived or isinstance(node.value, (ast.Name, ast.Attribute)) and {target.rsplit(".", 1)[-1] for target in references.get((node.value.lineno, ast.unparse(node.value)), frozenset())} & (_ALL_PROJECTIONS | _ALL_IDENTITY_NAMES) or not isinstance(node.value, ast.Compare) and any(isinstance(item, ast.Attribute) and item.attr in {"selection_identity", "selector_result_identity"} for item in ast.walk(node.value)) or isinstance(node.value, (ast.Tuple, ast.List, ast.Set, ast.Dict, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.IfExp, ast.BoolOp, ast.Subscript, ast.NamedExpr)) and any(isinstance(item, ast.Name) and item.id in derived or isinstance(item, ast.Call) and (item.lineno, ast.unparse(item.func)) in identity_sites for item in ast.walk(node.value))) for node in ast.walk(function) if isinstance(node, (ast.Return, ast.Yield, ast.YieldFrom))):
            findings.add(Finding("stage2f-wrapper-alias", function.name))
    for value in _strings(tree) & FORBIDDEN_STRINGS:
        findings.add(Finding("later-stage-literal", value))
    approved_projection_methods = frozenset(item for class_node in tree.body if isinstance(class_node, ast.ClassDef) and class_node.name in manifest.projection_classes for item in class_node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__post_init__")
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and (node not in tree.body or node.keywords or any(isinstance(base, ast.Call) for base in node.bases) or node.decorator_list and node.name not in manifest.projection_classes | ({"_P3SelectionInput"} if manifest.phase in {"P3", "P4"} else set())):
            findings.add(Finding("dynamic-construction", node.name))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (node not in tree.body or node.decorator_list) and node.name not in manifest.identity_functions | manifest.public_validators and node not in approved_projection_methods:
            findings.add(Finding("dynamic-function", node.name))
        if isinstance(node, ast.Lambda):
            findings.add(Finding("dynamic-function", "lambda"))
        if isinstance(node, ast.keyword) and node.arg is None:
            findings.add(Finding("dynamic-surface", "**"))
        if isinstance(node, ast.FormattedValue) and node.conversion == ord("r"):
            findings.add(Finding("identity-serialization", "f-string-!r"))
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            if any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
                findings.add(Finding("dynamic-export-surface", "__all__"))
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete)) and any(isinstance(target, (ast.Attribute, ast.Subscript)) for target in (tuple(node.targets) if isinstance(node, (ast.Assign, ast.Delete)) else (node.target,))):
            findings.add(Finding("object-state-mutation", type(node).__name__))
        if isinstance(node, (ast.Name, ast.Attribute)) and (node.id if isinstance(node, ast.Name) else node.attr).replace("_", "").lower() in {
            name.replace("_", "").lower() for name in _REGISTRY_NAMES
        }:
            findings.add(Finding("registry-state", node.id if isinstance(node, ast.Name) else node.attr))
    function_nodes = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    required_call_sites = frozenset((match.lineno, match.spelling) for requirement in _active_required_calls(manifest) for match in _equivalent_validation_call_matches(tree, analysis, requirement))
    exact_type_check_sites = _exact_type_check_sites(tree)
    raise_constructor_sites = _raise_constructor_sites(tree)
    p3_raw_hash_sites = (
        _p3_raw_hash_sites(tree, analysis)
        if manifest.phase in {"P3", "P4"}
        else frozenset()
    )
    p3_runtime_id_sites = (
        _p3_approved_runtime_id_sites(tree, analysis, p3_external_sites)
        if manifest.phase in {"P3", "P4"}
        else frozenset()
    )
    for call in analysis.calls:
        if _PROTOCOL_HASH_TARGET in call.targets and call.scope not in {
            (name,) for name in manifest.identity_functions
        } and (call.lineno, call.spelling) not in required_call_sites:
            findings.add(
                Finding(
                    "nonidentity-protocol-hash",
                    ".".join(call.scope) or "<module>",
                )
            )
    findings.update(Finding("second-hash-algebra", node.name) for node in function_nodes.values() if node.name.lstrip("_").lower() in {"hash", "sha1", "sha256", "blake2b", "md5", "protocol_hash"})
    for call in analysis.calls:
        resolved_targets = call.targets or frozenset({call.spelling})
        site = (call.lineno, call.spelling)
        approved_type_check = site in exact_type_check_sites and call.targets == frozenset({"builtins.type"})
        approved_raise_constructor = site in raise_constructor_sites and call.spelling == "ValueError"
        approved_matched_effect_to_dict = site in matched_effect_to_dict_sites
        approved_p3_raw_hash = site in p3_raw_hash_sites
        approved_external = approved_type_check or approved_raise_constructor or approved_matched_effect_to_dict or approved_p3_raw_hash or site in p3_external_sites
        tails = {call.spelling.rsplit(".", 1)[-1].lstrip("_")}
        tails.update(target.rsplit(".", 1)[-1].lstrip("_") for target in resolved_targets)
        if tails & _DYNAMIC_CALL_TAILS and not approved_type_check:
            findings.add(Finding("dynamic-construction", call.spelling))
        if {tail.replace("_", "").lower() for tail in tails} & {
            name.replace("_", "").lower() for name in FORBIDDEN_CALL_TAILS
        }:
            findings.add(Finding("forbidden-sensitive-call", call.spelling))
        if tails & _SERIALIZATION_TAILS:
            findings.add(Finding("identity-serialization", call.spelling))
        hash_tails = {tail.lower() for tail in tails} & {"hash", "sha1", "sha256", "blake2b", "md5", "protocol_hash"}
        if resolved_targets != frozenset({_PROTOCOL_HASH_TARGET}) and hash_tails and not approved_p3_raw_hash:
            findings.add(Finding("second-hash-algebra", call.spelling))
        if _RUNTIME_ID_TARGET in resolved_targets and (call.lineno, call.spelling) not in required_call_sites | p3_runtime_id_sites:
            findings.add(Finding("second-identity-algebra", call.spelling))
        for target in resolved_targets:
            if any(
                target == module or target.startswith(f"{module}.")
                for module in FORBIDDEN_IMPORT_MODULES
            ):
                findings.add(Finding("forbidden-qualified-call", target))
            if not target.startswith(f"{CANONICAL_MODULE}.") and target not in PURE_HELPER_CALLS and not approved_external:
                findings.add(Finding("unapproved-external-call", target))
        if call.sensitive_unresolved and not approved_external:
            findings.add(Finding("unresolved-sensitive-call", call.spelling))
        if not call.targets and not approved_external:
            findings.add(Finding("unresolved-call", call.spelling))
    for function in (
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        parameter_names = frozenset(item.arg for item in _parameters(function))
        called_names = frozenset(
            call.func.id
            for call in ast.walk(function)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        )
        if function.name.replace("_", "").lower() in {
            name.replace("_", "").lower()
            for name in _FORBIDDEN_IDENTITY_CALLABLES
        }:
            findings.add(Finding("premature-identity-alias", function.name))
        if function.name not in manifest.identity_functions and function.name.replace("_", "").lower().endswith(("selectionid", "selectorresultid")):
            findings.add(Finding("premature-identity-alias", function.name))
        if called_names & parameter_names:
            findings.add(
                Finding(
                    "caller-callable-invocation",
                    ",".join(sorted(called_names & parameter_names)),
                )
            )
        if any(
            item.arg in {"phase", "phase_name", "stage", "stage_name"} for item in _parameters(function)
        ) and any(isinstance(item, (ast.Subscript, ast.Call)) for item in ast.walk(function)):
            findings.add(Finding("caller-stage-dispatch", function.name))
    return tuple(sorted(findings))


def future_source_findings(
    source: str,
    manifest: PhaseManifest,
) -> tuple[Finding, ...]:
    """Analyze one hypothetical canonical module with invocation-local state."""

    return _future_source_findings_with_session(source, manifest, _AnalysisSession())


def _premature_findings(source: str, session: _AnalysisSession) -> set[Finding]:
    try:
        facts = session.source_analysis(source, module_name=CANONICAL_MODULE)
    except SyntaxError:
        return {Finding("invalid-production-syntax", CANONICAL_MODULE)}
    tree = facts.tree
    analysis = facts.analysis
    definitions = {binding.name for binding in analysis.bindings if binding.top_level}
    findings = {Finding("premature-projection", name) for name in definitions & _ALL_PROJECTIONS}
    findings |= {Finding("premature-identity", name) for name in definitions & _ALL_IDENTITIES}
    findings |= {Finding("premature-identity-alias", name) for name in definitions if name.replace("_", "").lower() in {alias.replace("_", "").lower() for alias in _FORBIDDEN_IDENTITY_ALIASES}}  # fmt: skip
    findings |= {
        Finding("premature-validator", name) for name in definitions & _FUTURE_PUBLIC_VALIDATORS
    }
    findings |= {
        Finding("premature-alias", binding.name)
        for binding in analysis.bindings
        if any(
            origin.rsplit(".", 1)[-1] in _ALL_PROJECTIONS | _ALL_IDENTITY_NAMES
            for origin in binding.origins
        )
    }
    findings |= {
        Finding("premature-domain", value)
        for value in _authority_domain_literals(tree, analysis) & _NEW_IDENTITY_DOMAINS
    }
    return findings


def repository_findings(
    sources: dict[str, str], manifest: PhaseManifest = CURRENT_MANIFEST
) -> tuple[Finding, ...]:
    """Check ownership and the active phase using caller-supplied source text only."""

    metadata_findings = _call_metadata_manifest_findings()
    if metadata_findings:
        return metadata_findings
    findings: set[Finding] = set()
    session = _AnalysisSession()
    canonical_source = sources.get(CANONICAL_MODULE)
    if manifest.module_present:
        if canonical_source is None:
            findings.add(Finding("production-module-absent", CANONICAL_MODULE))
        else:
            findings.update(
                _future_source_findings_with_session(
                    canonical_source,
                    manifest,
                    session,
                )
            )
            if manifest.phase == "P1":
                findings.update(
                    _active_p1_internal_findings_with_session(
                        canonical_source,
                        session,
                    )
                )
            elif manifest.phase == "P2":
                findings.update(
                    _active_p1_internal_findings_with_session(
                        canonical_source,
                        session,
                    )
                )
                findings.update(
                    _active_p2_internal_findings_with_session(
                        canonical_source,
                        session,
                    )
                )
            elif manifest.phase == "P3":
                findings.update(
                    _active_p1_internal_findings_with_session(
                        canonical_source,
                        session,
                    )
                )
                findings.update(
                    _active_p2_internal_findings_with_session(
                        canonical_source,
                        session,
                    )
                )
                findings.update(
                    _active_p3_internal_findings_with_session(
                        canonical_source,
                        session,
                    )
                )
    elif canonical_source is not None:
        findings.add(Finding("c0-production-module-present", CANONICAL_MODULE))
        findings.update(_premature_findings(canonical_source, session))
    stage_names = (
        _ALL_PROJECTIONS | _ALL_IDENTITIES | _FORBIDDEN_IDENTITY_ALIASES | _FUTURE_PUBLIC_VALIDATORS
    )
    source_scan_tokens = (
        stage_names
        | _NEW_IDENTITY_DOMAINS
        | _ALL_SCHEMAS
        | {CANONICAL_MODULE, CANONICAL_MODULE.rsplit(".", 1)[-1]}
    )
    normalized_scan_tokens = frozenset(
        "".join(character for character in token.lower() if character.isalnum())
        for token in source_scan_tokens
    )
    for module, source in sources.items():
        if module == CANONICAL_MODULE:
            continue
        alternate_owner = module.endswith("broader_calibration_evidence")
        if alternate_owner:
            findings.add(Finding("alternate-production-owner", module))
        normalized_source = "".join(
            character for character in source.lower() if character.isalnum()
        )
        if (
            module != _EXECUTION
            and not alternate_owner
            and not any(token in source for token in source_scan_tokens)
            and not any(token in normalized_source for token in normalized_scan_tokens)
        ):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            findings.add(Finding("invalid-production-syntax", module))
            continue
        # fmt: off
        for imported in (item for node in ast.walk(tree) if isinstance(node, ast.Import) for item in node.names):
            if imported.name == CANONICAL_MODULE:
                findings.add(Finding("wrong-module-alias", f"{module}:{imported.asname or imported.name}"))
        for imported_from in (node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)):
            for item in imported_from.names:
                if imported_from.module == CANONICAL_MODULE or ((imported_from.module or "") == CANONICAL_MODULE.rsplit(".", 1)[0] and item.name == "broader_calibration_evidence") or (imported_from.level and ((imported_from.module or "").endswith("broader_calibration_evidence") or item.name == "broader_calibration_evidence")):
                    findings.add(Finding("wrong-module-alias", f"{module}:{item.asname or item.name}"))
        canonical_module_names = _literal_alias_names(tree, frozenset({CANONICAL_MODULE}))
        for dynamic_import in (node for node in ast.walk(tree) if isinstance(node, ast.Call) and ast.unparse(node.func).rsplit(".", 1)[-1] in {"__import__", "import_module", "eval", "exec"} and (CANONICAL_MODULE in _strings(node) or any(isinstance(item, ast.Name) and item.id in canonical_module_names for argument in (*node.args, *(keyword.value for keyword in node.keywords)) for item in ast.walk(argument)))):
            findings.add(Finding("wrong-module-alias", f"{module}:{ast.unparse(dynamic_import.func)}"))
        names = {node.name for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                names.update(target.id for target in node.targets if isinstance(target, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
            if isinstance(node, ast.ImportFrom):
                names.update(item.name for item in node.names)
                for item in node.names:
                    if node.module == CANONICAL_MODULE or ((node.module or "") == CANONICAL_MODULE.rsplit(".", 1)[0] and item.name == "broader_calibration_evidence") or (node.level and ((node.module or "").endswith("broader_calibration_evidence") or item.name == "broader_calibration_evidence")):
                        findings.add(Finding("wrong-module-alias", f"{module}:{item.asname or item.name}"))
        # fmt: on
        # fmt: off
        for name in (name for name in names if name.replace("_", "").lower() in {stage_name.replace("_", "").lower() for stage_name in stage_names}):  # fmt: skip
            findings.add(Finding("wrong-module-owner", f"{module}:{name}"))
        # fmt: on
        analysis = None
        if any(
            token in source or token.replace("_", "").lower() in normalized_source
            for token in stage_names | _NEW_IDENTITY_DOMAINS | _ALL_SCHEMAS | {CANONICAL_MODULE}
        ):
            analysis = session.qualified_analysis(source, module_name=module)
            findings.update({Finding("wrong-module-owner", f"{module}:dynamic-stage2f-surface")} if frozenset(item.code for item in analysis.findings) & _DYNAMIC_FINDINGS and any(stage_name.replace("_", "").lower() in normalized_source for stage_name in stage_names) else ())  # fmt: skip
            for binding in analysis.bindings:
                if any(
                    origin == CANONICAL_MODULE or origin.rsplit(".", 1)[-1] in stage_names
                    for origin in binding.origins
                ):
                    findings.add(Finding("wrong-module-alias", f"{module}:{binding.name}"))
            for reference in analysis.references:
                if any(target.rsplit(".", 1)[-1] in stage_names for target in reference.targets):
                    findings.add(
                        Finding("wrong-module-reference", f"{module}:{reference.spelling}")
                    )
        for value in _strings(tree) & (_ALL_SCHEMAS | _ALL_PROJECTIONS | _ALL_IDENTITIES):
            findings.add(Finding("wrong-module-literal", f"{module}:{value}"))
        if analysis is not None:
            for value in _authority_domain_literals(tree, analysis) & _NEW_IDENTITY_DOMAINS:
                findings.add(Finding("wrong-module-literal", f"{module}:{value}"))
        if module == _EXECUTION:
            attestation = next(
                (
                    node
                    for node in tree.body
                    if isinstance(node, ast.ClassDef)
                    and node.name == "ExecutorAttestationProjection"
                ),
                None,
            )
            if attestation is None:
                findings.add(Finding("stage2e-attestation-missing", module))
            elif frozenset(_fields(attestation)) & _STAGE2F_ATTESTATION_FIELDS:
                findings.add(Finding("stage2e-calibration-field", module))
    return tuple(sorted(findings))
