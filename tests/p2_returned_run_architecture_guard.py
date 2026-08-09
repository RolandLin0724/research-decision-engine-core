"""Central, test-owned architecture model for returned-run projections."""

from __future__ import annotations

import ast
import hashlib
from typing import Final, NamedTuple

# This is deliberately handwritten test authority.  It must never be derived
# from production exports, runtime globals, reflection, or discovered classes.
AUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "ReturnedRunProjectionError",
        "ProvenanceValueProjection",
        "RunProvenanceProjection",
        "RunCandidateProjection",
        "RunCompletedExperimentProjection",
        "RunEvidenceProjection",
        "RunBeliefStateProjection",
        "RunHypothesisLikelihoodProjection",
        "RunBeliefUpdateProjection",
        "RunMatchedEffectProjection",
        "RunSigmaEstimateProjection",
        "RunModelBeliefStateProjection",
        "RunLineageProjection",
        "RunPredictiveIntervalProjection",
        "RunDiagnosticProjection",
        "RunModelUpdateProjection",
        "RunObservationAuthorizationProjection",
        "RunRevealedObservationProjection",
        "RunCalibrationEstimateProjection",
        "RunCalibrationProjection",
        "ControlValueProjection",
        "RunPublicExperimentDesignProjection",
        "RunHypothesisDecisionContextProjection",
        "RunCandidateScoreProjection",
        "RunDecisionTraceProjection",
        "RunLookaheadSecondActionProjection",
        "RunLookaheadBranchProjection",
        "RunLookaheadFirstActionProjection",
        "RunLookaheadAlternativeProjection",
        "RunLookaheadTraceProjection",
        "RunPolicyTraceProjection",
        "RunArmDecisionProjection",
        "RunArmActionProjection",
        "ReturnedRunProjection",
    }
)

EXPECTED_AUTHORIZED_TOP_LEVEL_CLASS_COUNT: Final = 34
RETURNED_RUN_SHAPE_PROJECTION_TYPES: Final[frozenset[str]] = (
    AUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES - {"ReturnedRunProjectionError"}
)
RETURNED_RUN_SHAPE_AUTHORITY_SHA256: Final = (
    "e32b0972e0de9216a4527a65fa64d5fe4171f38e0044b9c50e74d64476dcbb4b"
)

# Explicit current-stage rejection examples, never production-derived authority.
# A later stage removes a name only when that same central change adds it to the
# exact authorized manifest above.
CURRENT_STAGE_UNAUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "ReturnedResultProjection",
        "ExecutionInstanceProjection",
        "ExecutionIdentityProjection",
        "ExecutionStartProjection",
        "SubmittedJobsProjection",
        "WorkerIdentityProjection",
        "ResultBatchProjection",
        "ExecutionCompletionProjection",
        "ReturnedResultsProjection",
        "WorkerResultOrderProjection",
        "ExecutorAttestationProjection",
        "CalibrationCandidatePairProjection",
        "CalibrationSourceObservationProjection",
        "CalibrationSelectionProjection",
    }
)

AUTHORIZED_PROJECTION_MODULE_IMPORTS: Final[frozenset[str]] = frozenset(
    {
        "__future__",
        "belief_models",
        "broader_calibration_history",
        "broader_calibration_selector_replay",
        "broader_oracle",
        "broader_protocol",
        "broader_runner",
        "broader_worlds",
        "closed_loop",
        "collections",
        "dataclasses",
        "decision",
        "evidence_eligibility",
        "lookahead",
        "math",
        "optimizer_effect",
        "reasoning",
        "struct",
        "statistics",
        "types",
        "typing",
        "unicodedata",
    }
)

PERMANENT_FORBIDDEN_IMPORTS: Final[frozenset[str]] = frozenset(
    {
        "asyncio",
        "broader_assembly",
        "broader_conformance",
        "broader_execution",
        "broader_finalization",
        "broader_lifecycle",
        "broader_reader",
        "broader_smoke",
        "broader_validation_evidence",
        "hashlib",
        "http",
        "os",
        "pathlib",
        "pickle",
        "requests",
        "reader",
        "socket",
        "sqlite3",
        "storage",
        "subprocess",
        "urllib",
    }
)

# Stage 2D.1B admits only the frozen S6 scientific-record imports and S10.9
# replay entry point checked by ``returned_run_path_imports_are_authorized``.
CURRENT_STAGE_FORBIDDEN_IMPORTS: Final[frozenset[str]] = frozenset()

PERMANENT_FORBIDDEN_CALLS: Final[frozenset[str]] = frozenset(
    {
        "_validate_recorded_calibration",
        "_validate_effects",
        "_validate_observations",
        "_revealed_record",
        "_validate_revealed_observation",
        "_validated_effect_history",
        "asdict",
        "authorize_observation",
        "crossed_decision_traces",
        "compile",
        "eval",
        "evaluate_arm",
        "exec",
        "fields",
        "getattr",
        "getenv",
        "getmembers",
        "globals",
        "hasattr",
        "__import__",
        "locals",
        "make_dataclass",
        "new_class",
        "observe_selected",
        "open",
        "reconstruct_calibration_sources",
        "reobserve_authorized_observation",
        "replay_decisions",
        "repr",
        "run",
        "run_arm",
        "select_calibration_history",
        "selected_only_interface",
        "sha1",
        "sha256",
        "system",
        "setattr",
        "validate_recorded_calibration",
        "vars",
        "world_authority",
        "write_bytes",
        "write_text",
    }
)

PERMANENT_FORBIDDEN_SOURCE_OR_AST_PATTERNS: Final[frozenset[str]] = frozenset(
    {
        "ObservationAuthority",
        "OraclePlan",
        "SelectedObservationInterface",
        "_SelectedOnlyOracle",
        "_ISSUED",
        "broader_assembly",
        "broader_conformance",
        "broader_execution",
        "broader_finalization",
        "broader_lifecycle",
        "broader_reader",
        "broader_smoke",
        "broader_validation_evidence",
        "authorize_observation",
        "observe_selected",
        "_validate_recorded_calibration",
        "_validate_effects",
        "_validate_observations",
        "_revealed_record",
        "_validate_revealed_observation",
        "_validated_effect_history",
        "crossed_decision_traces",
        "evaluate_arm",
        "projection_sha256",
        "provenance_id",
        "returned_belief_state_id",
        "returned_belief_update_id",
        "returned_candidate_id",
        "returned_diagnostic_id",
        "returned_effect_id",
        "returned_evidence_id",
        "returned_lineage_id",
        "returned_model_update_id",
        "returned_observation_id",
        "returned_sigma_id",
        "reconstruct_calibration_sources",
        "reobserve_authorized_observation",
        "replay_decisions",
        "run_candidate_id",
        "select_calibration_history",
        "selected_only_interface",
        "storage",
        "validate_recorded_calibration",
        "world_authority",
    }
)

# Frozen later-stage names that are prohibited now but are not permanent
# authority, side-effect, reflection, or scientific-leaf prohibitions.
CURRENT_STAGE_FORBIDDEN_SOURCE_OR_AST_PATTERNS: Final[frozenset[str]] = frozenset(
    {
        "returned_result_id",
    }
)

RETURNED_RUN_MODULE_NAME: Final = "research_decision_engine.benchmarks.broader_returned_run"
CALIBRATION_SELECTOR_REPLAY_MODULE_NAME: Final = (
    "research_decision_engine.benchmarks.broader_calibration_selector_replay"
)

CURRENT_STAGE_UNAUTHORIZED_TOP_LEVEL_BINDINGS: Final[frozenset[str]] = (
    CURRENT_STAGE_UNAUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES
    | frozenset(
        {
            "ReturnedRunReader",
            "ReturnedRunPersistence",
            "ReturnedRunRepository",
            "ReturnedRunStore",
            "ReturnedResultIdentity",
            "ExecutionIdentity",
            "ResultBatchIdentity",
            "WorkerResultOrderIdentity",
        }
    )
)

_DYNAMIC_BUILTIN_NAMES: Final[frozenset[str]] = frozenset(
    {
        "__import__",
        "breakpoint",
        "compile",
        "delattr",
        "dir",
        "eval",
        "exec",
        "getattr",
        "globals",
        "hasattr",
        "help",
        "input",
        "locals",
        "open",
        "print",
        "setattr",
        "type",
        "vars",
    }
)
_SAFE_BUILTIN_NAMES: Final[frozenset[str]] = frozenset(
    {
        "abs",
        "all",
        "any",
        "bool",
        "bytes",
        "dict",
        "enumerate",
        "float",
        "frozenset",
        "int",
        "isinstance",
        "len",
        "list",
        "max",
        "min",
        "object",
        "ord",
        "range",
        "round",
        "set",
        "sorted",
        "str",
        "sum",
        "super",
        "tuple",
        "zip",
    }
)
_SELF_MATCHING_BUILTIN_PATTERN_NAMES: Final[frozenset[str]] = frozenset(
    {
        "bool",
        "bytearray",
        "bytes",
        "complex",
        "dict",
        "float",
        "frozenset",
        "int",
        "list",
        "set",
        "str",
        "tuple",
    }
)
_CALLBACK_KEYWORD_BUILTIN_TARGETS: Final[frozenset[str]] = frozenset(
    {"builtins.max", "builtins.min", "builtins.sorted"}
)

FORBIDDEN_QUALIFIED_CALLS: Final[frozenset[str]] = frozenset(
    {
        "builtins.__import__",
        "builtins.breakpoint",
        "builtins.compile",
        "builtins.delattr",
        "builtins.dir",
        "builtins.eval",
        "builtins.exec",
        "builtins.getattr",
        "builtins.globals",
        "builtins.hasattr",
        "builtins.help",
        "builtins.input",
        "builtins.locals",
        "builtins.object.__getattribute__",
        "builtins.object.__subclasses__",
        "builtins.open",
        "builtins.print",
        "builtins.setattr",
        "builtins.type.__getattribute__",
        "builtins.type.__subclasses__",
        "builtins.type.mro",
        "builtins.vars",
        "dataclasses.make_dataclass",
        "research_decision_engine.benchmarks.broader_calibration_history.select_calibration_history",
        "research_decision_engine.benchmarks.broader_returned_run.select_calibration_history",
        "research_decision_engine.benchmarks.broader_runner.run_arm",
        "types.new_class",
    }
)

FORBIDDEN_QUALIFIED_CALL_PREFIXES: Final[tuple[str, ...]] = (
    "asyncio.",
    "http.",
    "importlib.",
    "os.",
    "pathlib.",
    "pickle.",
    "requests.",
    "socket.",
    "sqlite3.",
    "subprocess.",
    "urllib.",
    "research_decision_engine.benchmarks.broader_assembly.",
    "research_decision_engine.benchmarks.broader_conformance.",
    "research_decision_engine.benchmarks.broader_execution.",
    "research_decision_engine.benchmarks.broader_finalization.",
    "research_decision_engine.benchmarks.broader_lifecycle.",
    "research_decision_engine.benchmarks.broader_reader.",
    "research_decision_engine.benchmarks.broader_smoke.",
    "research_decision_engine.benchmarks.broader_validation_evidence.",
    "research_decision_engine.policies.",
    "research_decision_engine.storage.",
)

_REGISTRY_MUTATION_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {
        "__delitem__",
        "__setitem__",
        "add",
        "append",
        "clear",
        "discard",
        "extend",
        "insert",
        "pop",
        "popitem",
        "remove",
        "setdefault",
        "update",
    }
)

_BUILTIN_MUTATION_TYPES: Final[frozenset[str]] = frozenset(
    {
        "builtins.dict",
        "builtins.list",
        "builtins.object",
        "builtins.set",
        "builtins.type",
    }
)

_BUILTIN_MUTATION_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {
        "__delattr__",
        "__delitem__",
        "__iadd__",
        "__iand__",
        "__init__",
        "__imul__",
        "__ior__",
        "__isub__",
        "__ixor__",
        "__setattr__",
        "__setitem__",
        "add",
        "append",
        "clear",
        "difference_update",
        "discard",
        "extend",
        "insert",
        "intersection_update",
        "pop",
        "popitem",
        "remove",
        "reverse",
        "setdefault",
        "sort",
        "symmetric_difference_update",
        "update",
    }
)

_DYNAMIC_NAMESPACE_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {
        "__annotations__",
        "__base__",
        "__bases__",
        "__builtins__",
        "__class__",
        "__closure__",
        "__code__",
        "__dict__",
        "__func__",
        "__getattribute__",
        "__globals__",
        "__loader__",
        "__mro__",
        "__reduce__",
        "__reduce_ex__",
        "__self__",
        "__spec__",
        "__subclasses__",
    }
)

_REGISTRY_OR_EVIDENCE_MARKERS: Final[tuple[str, ...]] = (
    "CANDIDATE_CATALOG",
    "CANDIDATES_BY_ID",
    "WORLDS_BY_ID",
    "registry",
    "evidence",
)

_MAX_ABSTRACT_STRUCTURE_DEPTH: Final = 24
_MAX_ABSTRACT_STRUCTURE_NODES: Final = 512
_MAX_ALIAS_RESOLUTION_PASSES: Final = 16
_MAX_PARAMETER_PROPAGATION_PASSES: Final = 16
_MAX_LOCAL_HELPER_DEPTH: Final = 16
_MAX_PRECISE_LOCAL_HELPER_NODES: Final = 512
_MAX_PRECISE_UNUSED_HELPER_CONTEXTS: Final = 16
_MAX_ABSTRACT_LOCATIONS: Final = 512
_MAX_ABSTRACT_CONTAINER_WIDTH: Final = 256
_MAX_ABSTRACT_FLOW_PASSES: Final = 16
_MAX_POST_FLOW_RESOLUTION_CACHE: Final = 32_768


def _qualified_call_target_is_forbidden(target: str) -> bool:
    if target in FORBIDDEN_QUALIFIED_CALLS or target.startswith(FORBIDDEN_QUALIFIED_CALL_PREFIXES):
        return True
    owner, _, attribute = target.rpartition(".")
    if owner in _BUILTIN_MUTATION_TYPES and attribute in _BUILTIN_MUTATION_ATTRIBUTES:
        return True
    leaf = target.rsplit(".", 1)[-1]
    return leaf in _REGISTRY_MUTATION_ATTRIBUTES and any(
        marker in target for marker in _REGISTRY_OR_EVIDENCE_MARKERS
    )


class _StaticKey(NamedTuple):
    """One deterministic, Python-equivalent literal mapping key."""

    type_name: str
    representation: str


class _AbstractLocation(NamedTuple):
    """One deterministic mutable-composite allocation site."""

    scope: tuple[str, ...]
    kind: str
    lineno: int
    col_offset: int


class _BoundMutator(NamedTuple):
    """One captured built-in mutator and its abstract receiver identity."""

    method: str
    locations: frozenset[_AbstractLocation]
    location_uncertain: bool = False


class ResolvedValue(NamedTuple):
    """Immutable abstract value used by the qualified-provenance analyzer."""

    direct_origins: frozenset[str] = frozenset()
    sequence_kind: str | None = None
    sequence_elements: tuple[ResolvedValue, ...] | None = None
    mapping_entries: tuple[tuple[_StaticKey, ResolvedValue], ...] | None = None
    aggregate_origins: frozenset[str] = frozenset()
    is_unknown: bool = False
    sensitive_unknown: bool = False
    static_key: _StaticKey | None = None
    locations: frozenset[_AbstractLocation] = frozenset()
    location_uncertain: bool = False
    bound_mutators: frozenset[_BoundMutator] = frozenset()
    bound_mutator_uncertain: bool = False
    deferred_locations: frozenset[_AbstractLocation] = frozenset()
    deferred_origins: frozenset[str] = frozenset()
    reachability_overflow: bool = False
    temporally_derived: bool = False


class _AbstractContainerState(NamedTuple):
    """Immutable contents for one abstract list or dictionary location."""

    kind: str
    sequence_elements: tuple[ResolvedValue, ...] | None = None
    mapping_entries: tuple[tuple[_StaticKey, ResolvedValue], ...] | None = None
    unknown_value: ResolvedValue = ResolvedValue()
    uncertain: bool = False
    masked_sequence_indexes: frozenset[int] = frozenset()
    masked_mapping_keys: frozenset[_StaticKey] = frozenset()


class _OrderedMappingWrite(NamedTuple):
    """One source-ordered exact or unknown write into an abstract dictionary."""

    mapping_entries: tuple[tuple[_StaticKey, ResolvedValue], ...] = ()
    unknown_value: ResolvedValue | None = None


class _AbstractStore(NamedTuple):
    """A bounded persistent store, sorted by deterministic locations."""

    entries: tuple[tuple[_AbstractLocation, _AbstractContainerState], ...] = ()


def _flow_store_fingerprint(store: _AbstractStore) -> int:
    """Return a cache fingerprint whose immutable store remains identity-stable."""

    return id(store)


class _FlowState(NamedTuple):
    """Immutable lexical bindings paired with one persistent composite store."""

    bindings: tuple[tuple[str, ResolvedValue], ...] = ()
    store: _AbstractStore = _AbstractStore()


def _flow_binding_get(
    bindings: tuple[tuple[str, ResolvedValue], ...],
    name: str,
) -> ResolvedValue | None:
    """Read one value from a deterministically sorted flow environment."""

    lower = 0
    upper = len(bindings)
    while lower < upper:
        middle = (lower + upper) // 2
        if bindings[middle][0] < name:
            lower = middle + 1
        else:
            upper = middle
    if lower < len(bindings) and bindings[lower][0] == name:
        return bindings[lower][1]
    return None


def _direct_value(origins: frozenset[str]) -> ResolvedValue:
    return ResolvedValue(direct_origins=origins, aggregate_origins=origins)


def _sequence_value(kind: str, elements: tuple[ResolvedValue, ...]) -> ResolvedValue:
    aggregate = frozenset(origin for element in elements for origin in element.aggregate_origins)
    return _bounded_value(
        ResolvedValue(
            sequence_kind=kind,
            sequence_elements=elements,
            aggregate_origins=aggregate,
            is_unknown=any(element.is_unknown for element in elements),
            sensitive_unknown=any(element.sensitive_unknown for element in elements),
            temporally_derived=any(element.temporally_derived for element in elements),
        )
    )


def _mapping_value(
    entries: tuple[tuple[_StaticKey, ResolvedValue], ...],
    *,
    extra_origins: frozenset[str] = frozenset(),
) -> ResolvedValue:
    aggregate = extra_origins | frozenset(
        origin for _key, value in entries for origin in value.aggregate_origins
    )
    return _bounded_value(
        ResolvedValue(
            mapping_entries=tuple(sorted(entries)),
            aggregate_origins=aggregate,
            is_unknown=any(value.is_unknown for _key, value in entries),
            sensitive_unknown=any(value.sensitive_unknown for _key, value in entries),
            temporally_derived=any(value.temporally_derived for _key, value in entries),
        )
    )


def _unknown_value(
    possible_origins: frozenset[str] = frozenset(),
    *,
    sensitive: bool,
) -> ResolvedValue:
    return ResolvedValue(
        direct_origins=possible_origins,
        aggregate_origins=possible_origins,
        is_unknown=True,
        sensitive_unknown=sensitive,
    )


def _bounded_value(value: ResolvedValue) -> ResolvedValue:
    """Collapse oversized abstract structure while retaining fail-closed origins."""

    if value.sequence_elements is None and value.mapping_entries is None:
        return value
    pending: list[tuple[ResolvedValue, int]] = [(value, 1)]
    visited = 0
    while pending:
        current, depth = pending.pop()
        visited += 1
        if visited > _MAX_ABSTRACT_STRUCTURE_NODES or depth > _MAX_ABSTRACT_STRUCTURE_DEPTH:
            return _unknown_value(
                value.direct_origins | value.aggregate_origins,
                sensitive=True,
            )._replace(
                locations=value.locations,
                location_uncertain=value.location_uncertain,
                bound_mutators=value.bound_mutators,
                bound_mutator_uncertain=value.bound_mutator_uncertain,
                deferred_locations=value.deferred_locations,
                deferred_origins=value.deferred_origins,
                reachability_overflow=True,
                temporally_derived=value.temporally_derived,
            )
        if current.sequence_elements is not None:
            pending.extend((element, depth + 1) for element in current.sequence_elements)
        if current.mapping_entries is not None:
            pending.extend(
                (entry_value, depth + 1) for _key, entry_value in current.mapping_entries
            )
    return value


def _union_origins(origin_sets: tuple[frozenset[str], ...]) -> frozenset[str]:
    """Union immutable origin sets while reusing a dominating input set."""

    if not origin_sets:
        return frozenset()
    if len(origin_sets) == 1:
        return origin_sets[0]
    if len(origin_sets) == 2:
        left, right = origin_sets
        if not left:
            return right
        if not right:
            return left
        if len(left) >= len(right) and right.issubset(left):
            return left
        if len(right) >= len(left) and left.issubset(right):
            return right
        return left | right
    nonempty = tuple(origins for origins in origin_sets if origins)
    if not nonempty:
        return frozenset()
    if len(nonempty) == 1:
        return nonempty[0]
    combined = frozenset(origin for origins in nonempty for origin in origins)
    for origins in nonempty:
        if len(origins) == len(combined) and origins == combined:
            return origins
    return combined


def _merge_values(values: tuple[ResolvedValue, ...]) -> ResolvedValue:
    """Join possible values deterministically without mutating either input."""

    if not values:
        return ResolvedValue()
    if len(values) > 2:
        unique_values: list[ResolvedValue] = []
        identities: set[int] = set()
        for value in values:
            identity = id(value)
            if identity in identities:
                continue
            identities.add(identity)
            unique_values.append(value)
        if len(unique_values) != len(values):
            values = tuple(unique_values)
    if len(values) == 1:
        return values[0]
    first = values[0]
    if all(value is first for value in values[1:]) or all(value == first for value in values[1:]):
        return first
    direct = _union_origins(tuple(value.direct_origins for value in values))
    aggregate = _union_origins(tuple(value.aggregate_origins for value in values))
    locations = frozenset(location for value in values for location in value.locations)
    has_location = tuple(bool(value.locations) for value in values)
    location_uncertain = bool(
        any(value.location_uncertain for value in values)
        or len(locations) > 1
        or (any(has_location) and not all(has_location))
    )
    bound_mutators = frozenset(mutator for value in values for mutator in value.bound_mutators)
    has_bound_mutator = tuple(bool(value.bound_mutators) for value in values)
    bound_mutator_uncertain = bool(
        any(value.bound_mutator_uncertain for value in values)
        or len(bound_mutators) > 1
        or (any(has_bound_mutator) and not all(has_bound_mutator))
    )
    deferred_locations = frozenset(
        location for value in values for location in value.deferred_locations
    )
    deferred_origins = _union_origins(tuple(value.deferred_origins for value in values))

    sequence_elements: tuple[ResolvedValue, ...] | None = None
    sequence_kind: str | None = None
    sequence_shapes = tuple(value.sequence_elements for value in values)
    sequence_kinds = tuple(value.sequence_kind for value in values)
    if (
        all(elements is not None for elements in sequence_shapes)
        and len(set(sequence_kinds)) == 1
        and len({len(elements) for elements in sequence_shapes if elements is not None}) == 1
    ):
        known_shapes = tuple(elements for elements in sequence_shapes if elements is not None)
        sequence_elements = tuple(
            _merge_values(tuple(elements[index] for elements in known_shapes))
            for index in range(len(known_shapes[0]))
        )
        sequence_kind = sequence_kinds[0]

    mapping_entries: tuple[tuple[_StaticKey, ResolvedValue], ...] | None = None
    mappings = tuple(value.mapping_entries for value in values)
    if all(entries is not None for entries in mappings):
        known_mappings = tuple(dict(entries) for entries in mappings if entries is not None)
        key_sets = tuple(frozenset(entries) for entries in known_mappings)
        if len(set(key_sets)) == 1:
            mapping_entries = tuple(
                (
                    key,
                    _merge_values(tuple(entries[key] for entries in known_mappings)),
                )
                for key in sorted(key_sets[0])
            )

    static_keys = tuple(value.static_key for value in values)
    static_key = static_keys[0] if len(set(static_keys)) == 1 else None
    return _bounded_value(
        ResolvedValue(
            direct_origins=direct,
            sequence_kind=sequence_kind,
            sequence_elements=sequence_elements,
            mapping_entries=mapping_entries,
            aggregate_origins=_union_origins((aggregate, direct)),
            is_unknown=any(value.is_unknown for value in values),
            sensitive_unknown=any(value.sensitive_unknown for value in values),
            static_key=static_key,
            locations=locations,
            location_uncertain=location_uncertain,
            bound_mutators=bound_mutators,
            bound_mutator_uncertain=bound_mutator_uncertain,
            deferred_locations=deferred_locations,
            deferred_origins=deferred_origins,
            reachability_overflow=any(value.reachability_overflow for value in values),
            temporally_derived=any(value.temporally_derived for value in values),
        )
    )


def _mark_unknown_leaves_sensitive(value: ResolvedValue) -> ResolvedValue:
    sequence_elements = (
        None
        if value.sequence_elements is None
        else tuple(_mark_unknown_leaves_sensitive(element) for element in value.sequence_elements)
    )
    mapping_entries = (
        None
        if value.mapping_entries is None
        else tuple(
            (key, _mark_unknown_leaves_sensitive(entry_value))
            for key, entry_value in value.mapping_entries
        )
    )
    has_structure = sequence_elements is not None or mapping_entries is not None
    return _bounded_value(
        value._replace(
            sequence_elements=sequence_elements,
            mapping_entries=mapping_entries,
            sensitive_unknown=(value.sensitive_unknown or (value.is_unknown and not has_structure)),
        )
    )


def _unknown_mapping_value(value: ResolvedValue) -> ResolvedValue:
    """Collapse an unresolved mapping contribution without losing reachable origins."""

    return _unknown_value(
        value.direct_origins | value.aggregate_origins | value.deferred_origins,
        sensitive=True,
    )._replace(
        deferred_locations=value.deferred_locations,
        deferred_origins=value.deferred_origins,
        reachability_overflow=value.reachability_overflow,
        temporally_derived=value.temporally_derived,
    )


def _mapping_unknown_is_present(value: ResolvedValue) -> bool:
    return bool(
        value.direct_origins
        or value.aggregate_origins
        or value.is_unknown
        or value.sensitive_unknown
        or value.locations
        or value.deferred_locations
        or value.deferred_origins
        or value.reachability_overflow
    )


def _apply_ordered_mapping_writes(
    container: _AbstractContainerState,
    writes: tuple[_OrderedMappingWrite, ...],
) -> _AbstractContainerState:
    """Apply sequential Python mapping writes with exact last-write-wins cells."""

    if container.kind != "dict":
        raise ValueError("ordered mapping writes require a dictionary container")
    entries = dict(container.mapping_entries or ())
    unknown = container.unknown_value
    uncertain = container.uncertain or container.mapping_entries is None
    masks = set(container.masked_mapping_keys if container.mapping_entries is not None else ())
    for write in writes:
        if write.unknown_value is not None:
            unknown = _merge_values((unknown, write.unknown_value))
            uncertain = True
            masks.clear()
        for key, value in write.mapping_entries:
            entries[key] = value
            masks.add(key)
    if len(entries) > _MAX_ABSTRACT_CONTAINER_WIDTH:
        possible = frozenset(
            origin
            for value in entries.values()
            for origin in value.direct_origins | value.aggregate_origins | value.deferred_origins
        )
        return _AbstractContainerState(
            "dict",
            mapping_entries=None,
            unknown_value=_merge_values((unknown, _unknown_value(possible, sensitive=True))),
            uncertain=True,
        )
    return container._replace(
        mapping_entries=tuple(sorted(entries.items())),
        unknown_value=unknown,
        uncertain=uncertain,
        masked_mapping_keys=frozenset(masks),
    )


def _ordered_direct_mapping_write(
    key: _StaticKey,
    value: ResolvedValue,
) -> _OrderedMappingWrite:
    """Write one exact Python mapping cell with last-write-wins semantics."""

    return _OrderedMappingWrite(((key, value),))


def _resolved_pair_iterable_mapping_writes(
    value: ResolvedValue,
) -> tuple[_OrderedMappingWrite, ...]:
    """Classify exact pair items without discarding their iteration order."""

    if value.sequence_elements is None:
        return (_OrderedMappingWrite(unknown_value=_unknown_mapping_value(value)),)
    writes: list[_OrderedMappingWrite] = []
    for pair in value.sequence_elements:
        if pair.sequence_elements is None or len(pair.sequence_elements) != 2:
            return (
                *writes,
                _OrderedMappingWrite(unknown_value=_unknown_mapping_value(value)),
            )
        key, entry_value = pair.sequence_elements
        if key.static_key is None:
            writes.append(_OrderedMappingWrite(unknown_value=_unknown_mapping_value(pair)))
            continue
        writes.append(_ordered_direct_mapping_write(key.static_key, entry_value))
    return tuple(writes)


def _resolved_mapping_write(value: ResolvedValue) -> _OrderedMappingWrite:
    """Classify a legacy resolved mapping without inventing exact dynamic keys."""

    if (
        value.mapping_entries is not None
        and not value.is_unknown
        and not value.sensitive_unknown
        and not value.reachability_overflow
    ):
        return _OrderedMappingWrite(value.mapping_entries)
    return _OrderedMappingWrite(unknown_value=_unknown_mapping_value(value))


def _resolved_mapping_value(container: _AbstractContainerState) -> ResolvedValue:
    """Project ordered cells and masks into the legacy immutable value model."""

    unknown = container.unknown_value
    if container.mapping_entries is None:
        return _unknown_mapping_value(unknown)
    unknown_present = container.uncertain or _mapping_unknown_is_present(unknown)
    projected_unknown = (
        unknown if _mapping_unknown_is_present(unknown) else _unknown_value(sensitive=True)
    )
    entries = tuple(
        (
            key,
            value
            if not unknown_present or key in container.masked_mapping_keys
            else _merge_values((value, projected_unknown)),
        )
        for key, value in container.mapping_entries
    )
    result = _mapping_value(
        entries,
        extra_origins=(
            unknown.direct_origins | unknown.aggregate_origins | unknown.deferred_origins
        ),
    )
    return result._replace(
        is_unknown=result.is_unknown or container.uncertain or unknown.is_unknown,
        sensitive_unknown=(
            result.sensitive_unknown
            or unknown.sensitive_unknown
            or (container.uncertain and unknown_present)
        ),
        deferred_locations=unknown.deferred_locations,
        deferred_origins=unknown.deferred_origins,
        reachability_overflow=unknown.reachability_overflow,
        temporally_derived=result.temporally_derived or unknown.temporally_derived,
    )


class SymbolBinding(NamedTuple):
    """One statically discovered binding and all of its qualified origins."""

    scope: tuple[str, ...]
    name: str
    kind: str
    origins: frozenset[str]
    lineno: int
    top_level: bool


class ResolvedCall(NamedTuple):
    """One call site with every qualified target reachable by simple aliases."""

    scope: tuple[str, ...]
    spelling: str
    targets: frozenset[str]
    lineno: int
    dynamic: bool
    sensitive_unresolved: bool
    modeled_bound_mutator: bool = False


class ResolvedReference(NamedTuple):
    """One loaded name/attribute and every qualified origin it can denote."""

    scope: tuple[str, ...]
    spelling: str
    targets: frozenset[str]
    lineno: int


class ResolvedMutation(NamedTuple):
    """One unresolved sensitive mutation target retained for exact inventory checks."""

    scope: tuple[str, ...]
    spelling: str
    lineno: int


class ImportOccurrence(NamedTuple):
    """One exact import occurrence, retaining requested module and multiplicity."""

    scope: tuple[str, ...]
    local: str
    kind: str
    origins: tuple[str, ...]


class ArchitectureFinding(NamedTuple):
    """A fail-closed architecture finding suitable for adversarial tests."""

    code: str
    symbol: str
    lineno: int


class QualifiedSymbolAnalysis(NamedTuple):
    """Test-owned qualified-symbol inventory for one pure production module."""

    imports: tuple[SymbolBinding, ...]
    bindings: tuple[SymbolBinding, ...]
    binding_events: tuple[SymbolBinding, ...]
    calls: tuple[ResolvedCall, ...]
    references: tuple[ResolvedReference, ...]
    unresolved_mutations: tuple[ResolvedMutation, ...]
    exports: frozenset[str]
    findings: tuple[ArchitectureFinding, ...]
    source_text: str
    module_name: str


class _Scope:
    """A deliberately small lexical scope model used by the AST analyzer."""

    def __init__(
        self,
        path: tuple[str, ...],
        parent: _Scope | None,
    ) -> None:
        self.path = path
        self.parent = parent
        self.values: dict[str, ResolvedValue] = {}
        self.base_values: dict[str, ResolvedValue] = {}
        self.kinds: dict[str, set[str]] = {}
        self.lines: dict[str, int] = {}
        self.aliases: dict[str, list[ast.expr]] = {}
        self.events: list[tuple[str, str, int]] = []

    def bind(
        self,
        name: str,
        kind: str,
        lineno: int,
        *,
        origins: frozenset[str] = frozenset(),
        alias: ast.expr | None = None,
        unknown: bool = False,
        sensitive_unknown: bool = False,
    ) -> None:
        self.events.append((name, kind, lineno))
        self.kinds.setdefault(name, set()).add(kind)
        self.lines.setdefault(name, lineno)
        base_candidates: list[ResolvedValue] = []
        if name in self.base_values:
            base_candidates.append(self.base_values[name])
        if origins:
            base_candidates.append(_direct_value(origins))
        if unknown or sensitive_unknown:
            base_candidates.append(_unknown_value(sensitive=sensitive_unknown))
        if base_candidates:
            self.base_values[name] = _merge_values(tuple(base_candidates))
        self.values.setdefault(name, self.base_values.get(name, ResolvedValue()))
        if alias is not None:
            self.aliases.setdefault(name, []).append(alias)


class _QualifiedSymbolAnalyzer:
    """Resolve imports, attributes, and simple aliases without executing source."""

    def __init__(self, source: str, module_name: str) -> None:
        self.source = source
        self.module_name = module_name
        self.tree = ast.parse(source)
        self.parents: dict[int, ast.AST] = {
            id(child): parent
            for parent in ast.walk(self.tree)
            for child in ast.iter_child_nodes(parent)
        }
        self.module_scope = _Scope((), None)
        self.scopes: list[_Scope] = [self.module_scope]
        self.class_scope_ids: set[int] = set()
        self.class_scope_nodes: dict[int, ast.ClassDef] = {}
        self.node_scopes: dict[int, _Scope] = {}
        self.iteration_alias_scopes: dict[int, _Scope] = {}
        self.destructuring_alias_shapes: dict[int, tuple[int, int | None]] = {}
        self.imports: list[SymbolBinding] = []
        self.exports: set[str] = set()
        self.findings: list[ArchitectureFinding] = []
        self.unresolved_mutations: list[ResolvedMutation] = []
        self.local_functions: dict[
            str, list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, _Scope]]
        ] = {}
        self.alias_cycle_names: set[tuple[tuple[str, ...], str]] = set()
        self.active_alias_bindings: set[tuple[int, str]] = set()
        self.reported_fail_closed_limits: set[tuple[str, str, int]] = set()
        self.alias_resolution_exhausted = False
        self.flow_node_states: dict[int, _FlowState] = {}
        self.flow_node_values: dict[int, ResolvedValue] = {}
        self.flow_mutated_locations: set[_AbstractLocation] = set()
        self.flow_write_target_node_ids: set[int] = set()
        for statement in ast.walk(self.tree):
            if isinstance(statement, (ast.Assign, ast.Delete)):
                targets: tuple[ast.expr, ...] = tuple(statement.targets)
            elif isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
                targets = (statement.target,)
            else:
                continue
            self.flow_write_target_node_ids.update(
                id(candidate) for target in targets for candidate in ast.walk(target)
            )
        self.flow_final_states: dict[int, _FlowState] = {}
        self.flow_snapshot_node_ids: set[int] = set()
        self.flow_called_function_targets: set[str] = set()
        self.flow_function_defaults: dict[int, dict[str, ResolvedValue]] = {}
        self.flow_function_node_counts: dict[int, int] = {}
        self.flow_function_return_nodes: dict[int, tuple[ast.Return, ...]] = {}
        self.flow_function_relevance: dict[int, bool] = {}
        self.flow_function_composite_mutation: dict[int, bool] = {}
        self.flow_function_may_mutate: dict[int, bool] = {}
        self.flow_precise_helper_context_counts: dict[int, int] = {}
        self._post_flow_resolution_cache: dict[
            tuple[int, int, int, frozenset[str]],
            tuple[_AbstractStore, ResolvedValue],
        ] = {}
        self._post_flow_resolution_cache_hits = 0
        self._post_flow_resolution_cache_misses = 0
        self._building_composite_flow = False
        self._resolving_flow_snapshot = False
        self._collect(self.tree, self.module_scope)
        self.flow_snapshot_node_ids = self._flow_snapshot_nodes()
        self._find_alias_cycles()
        self._resolve_aliases()
        sensitive_parameters = self._sensitive_parameter_bindings()
        callable_parameters = self._callable_parameter_bindings()
        (
            self.sensitive_parameter_bindings,
            self.callable_parameter_bindings,
        ) = self._propagate_parameter_use_bindings(
            sensitive_parameters,
            callable_parameters,
        )
        self._propagate_local_function_inputs()
        self._build_composite_flow()
        self._find_top_level_alias_behavior()
        self.calls = self._resolved_calls()
        self.references = self._resolved_references()
        self._find_dynamic_behavior()

    def _absolute_import_module(self, node: ast.ImportFrom) -> str:
        if node.level == 0:
            return node.module or ""
        package_parts = self.module_name.rsplit(".", 1)[0].split(".")
        retained = len(package_parts) - node.level + 1
        if retained < 0:
            return ""
        base = ".".join(package_parts[:retained])
        return base if node.module is None else f"{base}.{node.module}"

    def _collect(self, node: ast.AST, scope: _Scope) -> None:
        self.node_scopes[id(node)] = scope
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            kind = "global" if isinstance(node, ast.Global) else "nonlocal"
            for name in node.names:
                scope.bind(name, kind, node.lineno, unknown=True)
            self.findings.extend(
                ArchitectureFinding(
                    "dynamic-scope-binding",
                    name,
                    node.lineno,
                )
                for name in node.names
            )
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                bound_origin = alias.name if alias.asname else local
                scope.bind(
                    local,
                    "import",
                    node.lineno,
                    origins=frozenset({bound_origin}),
                )
                self.imports.append(
                    SymbolBinding(
                        scope.path,
                        local,
                        f"plain-import:{alias.name}",
                        frozenset({bound_origin}),
                        node.lineno,
                        scope is self.module_scope,
                    )
                )
            return
        if isinstance(node, ast.ImportFrom):
            module = self._absolute_import_module(node)
            for alias in node.names:
                origin = f"{module}.{alias.name}" if module else alias.name
                if module == "__future__":
                    self.imports.append(
                        SymbolBinding(
                            scope.path,
                            alias.name,
                            f"future:{origin}",
                            frozenset({origin}),
                            node.lineno,
                            scope is self.module_scope,
                        )
                    )
                    continue
                local = alias.asname or alias.name
                scope.bind(
                    local,
                    "import",
                    node.lineno,
                    origins=frozenset({origin}),
                )
                self.imports.append(
                    SymbolBinding(
                        scope.path,
                        local,
                        f"from-import:{origin}",
                        frozenset({origin}),
                        node.lineno,
                        scope is self.module_scope,
                    )
                )
            return
        if isinstance(node, ast.Match):
            self._collect(node.subject, scope)
            for case in node.cases:
                self.node_scopes[id(case)] = scope
                self._bind_match_pattern(case.pattern, node.subject, scope)
                if case.guard is not None:
                    self._collect(case.guard, scope)
                for statement in case.body:
                    self._collect(statement, scope)
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            child = _Scope((*scope.path, f"<comprehension:{node.lineno}>"), scope)
            self.scopes.append(child)
            for index, generator in enumerate(node.generators):
                self.node_scopes[id(generator)] = child
                self._collect(generator.iter, scope if index == 0 else child)
                self._bind_target(
                    generator.target,
                    self._iteration_alias(
                        generator.iter,
                        scope if index == 0 else child,
                    ),
                    child,
                    "comprehension-target",
                    generator.target.lineno,
                )
                for condition in generator.ifs:
                    self._collect(condition, child)
            if isinstance(node, ast.DictComp):
                self._collect(node.key, child)
                self._collect(node.value, child)
            else:
                self._collect(node.elt, child)
            return
        if isinstance(node, ast.TypeAlias):
            self._bind_target(
                node.name,
                node.value,
                scope,
                "type-alias",
                node.lineno,
            )
            self._collect(node.value, scope)
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "async-function" if isinstance(node, ast.AsyncFunctionDef) else "function"
            origin = ".".join((self.module_name, *scope.path, node.name))
            scope.bind(
                node.name,
                kind,
                node.lineno,
                origins=frozenset({origin}),
            )
            if scope is self.module_scope and node.name in {"__getattr__", "__dir__"}:
                self.findings.append(
                    ArchitectureFinding("dynamic-module-hook", node.name, node.lineno)
                )
            for decorator in node.decorator_list:
                self._collect(decorator, scope)
            for default in (*node.args.defaults, *node.args.kw_defaults):
                if default is not None:
                    self._collect(default, scope)
            child = _Scope((*scope.path, node.name), scope)
            self.scopes.append(child)
            self.local_functions.setdefault(origin, []).append((node, child))
            for argument in (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            ):
                child.bind(
                    argument.arg,
                    "argument",
                    argument.lineno,
                    unknown=True,
                )
            if node.args.vararg is not None:
                child.bind(
                    node.args.vararg.arg,
                    "argument",
                    node.args.vararg.lineno,
                    unknown=True,
                )
            if node.args.kwarg is not None:
                child.bind(
                    node.args.kwarg.arg,
                    "argument",
                    node.args.kwarg.lineno,
                    unknown=True,
                )
            for statement in node.body:
                self._collect(statement, child)
            return
        if isinstance(node, ast.Lambda):
            child = _Scope((*scope.path, f"<lambda:{node.lineno}>"), scope)
            self.scopes.append(child)
            for argument in (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            ):
                child.bind(
                    argument.arg,
                    "argument",
                    argument.lineno,
                    unknown=True,
                )
            if node.args.vararg is not None:
                child.bind(
                    node.args.vararg.arg,
                    "argument",
                    node.args.vararg.lineno,
                    unknown=True,
                )
            if node.args.kwarg is not None:
                child.bind(
                    node.args.kwarg.arg,
                    "argument",
                    node.args.kwarg.lineno,
                    unknown=True,
                )
            self._collect(node.body, child)
            return
        if isinstance(node, ast.ClassDef):
            origin = ".".join((self.module_name, *scope.path, node.name))
            scope.bind(
                node.name,
                "class",
                node.lineno,
                origins=frozenset({origin}),
            )
            for decorator in node.decorator_list:
                self._collect(decorator, scope)
            for base in node.bases:
                self._collect(base, scope)
            child = _Scope((*scope.path, node.name), scope)
            self.scopes.append(child)
            self.class_scope_ids.add(id(child))
            self.class_scope_nodes[id(child)] = node
            for statement in node.body:
                self._collect(statement, child)
            return
        if isinstance(node, ast.Assign):
            for target in node.targets:
                self._bind_target(target, node.value, scope, "assign", node.lineno)
            if scope is self.module_scope:
                self._collect_all_export(node.targets, node.value, node.lineno)
        elif isinstance(node, ast.AnnAssign):
            self._bind_target(node.target, node.value, scope, "annassign", node.lineno)
            if scope is self.module_scope:
                self._collect_all_export((node.target,), node.value, node.lineno)
        elif isinstance(node, ast.NamedExpr):
            binding_scope = self._named_expression_binding_scope(scope)
            self._bind_target(
                node.target,
                node.value,
                binding_scope,
                "named-expression",
                node.lineno,
                sensitive_unknown=binding_scope is not scope,
            )
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name is not None:
            scope.bind(node.name, "match-target", node.lineno, unknown=True)
        elif isinstance(node, ast.MatchMapping) and node.rest is not None:
            scope.bind(node.rest, "match-target", node.lineno, unknown=True)
        elif isinstance(node, ast.For):
            self._bind_target(
                node.target,
                self._iteration_alias(node.iter, scope),
                scope,
                "loop-target",
                node.lineno,
            )
        elif isinstance(node, ast.AsyncFor):
            self._bind_target(
                node.target,
                None,
                scope,
                "loop-target",
                node.lineno,
                sensitive_unknown=True,
            )
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    self._bind_target(
                        item.optional_vars,
                        None,
                        scope,
                        "with-target",
                        node.lineno,
                    )
        elif isinstance(node, ast.ExceptHandler) and node.name is not None:
            scope.bind(node.name, "exception-target", node.lineno, unknown=True)
        for child_node in ast.iter_child_nodes(node):
            self._collect(child_node, scope)

    def _bind_target(
        self,
        target: ast.expr,
        value: ast.expr | None,
        scope: _Scope,
        kind: str,
        lineno: int,
        *,
        sensitive_unknown: bool = False,
    ) -> None:
        if isinstance(target, ast.Name):
            scope.bind(
                target.id,
                kind,
                lineno,
                alias=value,
                unknown=value is None,
                sensitive_unknown=sensitive_unknown,
            )
            return
        if isinstance(target, ast.Starred):
            self._bind_target(
                target.value,
                value,
                scope,
                kind,
                lineno,
                sensitive_unknown=sensitive_unknown,
            )
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            if value is None:
                values: tuple[ast.expr | None, ...] = (None,) * len(target.elts)
            else:
                starred_indexes = tuple(
                    index for index, item in enumerate(target.elts) if isinstance(item, ast.Starred)
                )
                star_index = starred_indexes[0] if starred_indexes else None
                selected: list[ast.expr] = []
                for index in range(len(target.elts)):
                    if index == star_index:
                        trailing = len(target.elts) - index - 1
                        upper: ast.expr | None = ast.Constant(value=-trailing) if trailing else None
                        selector: ast.expr = ast.Slice(
                            lower=ast.Constant(value=index),
                            upper=upper,
                            step=None,
                        )
                    else:
                        selected_index = (
                            index - len(target.elts)
                            if star_index is not None and index > star_index
                            else index
                        )
                        selector = ast.Constant(value=selected_index)
                    expression = ast.Subscript(value=value, slice=selector, ctx=ast.Load())
                    selected.append(ast.copy_location(expression, value))
                    self.destructuring_alias_shapes[id(expression)] = (
                        len(target.elts),
                        star_index,
                    )
                values = tuple(selected)
            for item, item_value in zip(target.elts, values, strict=True):
                self._bind_target(
                    item,
                    item_value,
                    scope,
                    kind,
                    lineno,
                    sensitive_unknown=sensitive_unknown,
                )

    def _bind_match_pattern(
        self,
        pattern: ast.pattern,
        value: ast.expr,
        scope: _Scope,
        *,
        sensitive_unknown: bool = False,
    ) -> None:
        self.node_scopes[id(pattern)] = scope
        if isinstance(pattern, ast.MatchAs):
            if pattern.name is not None:
                scope.bind(
                    pattern.name,
                    "match-target",
                    pattern.lineno,
                    alias=value,
                    sensitive_unknown=sensitive_unknown,
                )
            if pattern.pattern is not None:
                self._bind_match_pattern(
                    pattern.pattern,
                    value,
                    scope,
                    sensitive_unknown=sensitive_unknown,
                )
            return
        if isinstance(pattern, ast.MatchStar):
            if pattern.name is not None:
                scope.bind(
                    pattern.name,
                    "match-target",
                    pattern.lineno,
                    alias=value,
                    sensitive_unknown=sensitive_unknown,
                )
            return
        if isinstance(pattern, ast.MatchSequence):
            starred_indexes = tuple(
                index
                for index, item in enumerate(pattern.patterns)
                if isinstance(item, ast.MatchStar)
            )
            star_index = starred_indexes[0] if starred_indexes else None
            for index, item in enumerate(pattern.patterns):
                if index == star_index:
                    trailing = len(pattern.patterns) - index - 1
                    upper: ast.expr | None = ast.Constant(value=-trailing) if trailing else None
                    selector: ast.expr = ast.Slice(
                        lower=ast.Constant(value=index),
                        upper=upper,
                        step=None,
                    )
                else:
                    selected_index = (
                        index - len(pattern.patterns)
                        if star_index is not None and index > star_index
                        else index
                    )
                    selector = ast.Constant(value=selected_index)
                selected = ast.copy_location(
                    ast.Subscript(value=value, slice=selector, ctx=ast.Load()),
                    value,
                )
                self._bind_match_pattern(
                    item,
                    selected,
                    scope,
                    sensitive_unknown=sensitive_unknown,
                )
            return
        if isinstance(pattern, ast.MatchMapping):
            for key, item in zip(pattern.keys, pattern.patterns, strict=True):
                self._collect(key, scope)
                mapping_selected = ast.copy_location(
                    ast.Subscript(value=value, slice=key, ctx=ast.Load()),
                    value,
                )
                self._bind_match_pattern(
                    item,
                    mapping_selected,
                    scope,
                    sensitive_unknown=sensitive_unknown,
                )
            if pattern.rest is not None:
                scope.bind(
                    pattern.rest,
                    "match-target",
                    pattern.lineno,
                    alias=value,
                    sensitive_unknown=sensitive_unknown,
                )
            return
        if isinstance(pattern, ast.MatchClass):
            self._collect(pattern.cls, scope)
            for attribute, item in zip(pattern.kwd_attrs, pattern.kwd_patterns, strict=True):
                attribute_selected = ast.copy_location(
                    ast.Attribute(value=value, attr=attribute, ctx=ast.Load()),
                    value,
                )
                self._bind_match_pattern(
                    item,
                    attribute_selected,
                    scope,
                    sensitive_unknown=sensitive_unknown,
                )
            class_targets = self._resolve_expression(pattern.cls, scope).direct_origins
            self_matching = bool(
                isinstance(pattern.cls, ast.Name)
                and pattern.cls.id in _SELF_MATCHING_BUILTIN_PATTERN_NAMES
                and class_targets == {f"builtins.{pattern.cls.id}"}
            )
            for item in pattern.patterns:
                self._bind_match_pattern(
                    item,
                    value,
                    scope,
                    sensitive_unknown=sensitive_unknown or not self_matching,
                )
            return
        if isinstance(pattern, ast.MatchOr):
            for item in pattern.patterns:
                self._bind_match_pattern(
                    item,
                    value,
                    scope,
                    sensitive_unknown=sensitive_unknown,
                )
            return
        if isinstance(pattern, ast.MatchValue):
            self._collect(pattern.value, scope)

    def _named_expression_binding_scope(self, scope: _Scope) -> _Scope:
        current = scope
        while current.parent is not None and current.path[-1].startswith("<comprehension:"):
            current = current.parent
        return current

    def _iteration_alias(self, iterable: ast.expr, scope: _Scope) -> ast.Subscript:
        alias = ast.copy_location(
            ast.Subscript(
                value=iterable,
                slice=ast.Constant(value=None),
                ctx=ast.Load(),
            ),
            iterable,
        )
        self.iteration_alias_scopes[id(alias)] = scope
        return alias

    def _collect_all_export(
        self,
        targets: tuple[ast.expr, ...] | list[ast.expr],
        value: ast.expr | None,
        lineno: int,
    ) -> None:
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
            return
        try:
            exported = ast.literal_eval(value) if value is not None else None
        except (TypeError, ValueError):
            exported = None
        if not isinstance(exported, (tuple, list, set)) or not all(
            isinstance(item, str) for item in exported
        ):
            self.findings.append(ArchitectureFinding("dynamic-__all__", "__all__", lineno))
            return
        self.exports.update(exported)

    def _target_names(self, target: ast.AST) -> frozenset[str]:
        if isinstance(target, ast.Name):
            return frozenset({target.id})
        if isinstance(target, ast.Starred):
            return self._target_names(target.value)
        if isinstance(target, (ast.Tuple, ast.List)):
            return frozenset(name for item in target.elts for name in self._target_names(item))
        return frozenset()

    def _direct_statement_binding_names(self, statement: ast.stmt) -> frozenset[str]:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return frozenset({statement.name})
        if isinstance(statement, ast.Assign):
            return frozenset(
                name for target in statement.targets for name in self._target_names(target)
            )
        if isinstance(statement, (ast.AnnAssign, ast.TypeAlias)):
            return self._target_names(
                statement.target if isinstance(statement, ast.AnnAssign) else statement.name
            )
        if isinstance(statement, ast.Import):
            return frozenset(
                alias.asname or alias.name.split(".", 1)[0] for alias in statement.names
            )
        if isinstance(statement, ast.ImportFrom):
            return frozenset(alias.asname or alias.name for alias in statement.names)
        return frozenset()

    def _class_body_nodes(self, node: ast.AST) -> tuple[ast.AST, ...]:
        collected: list[ast.AST] = []

        def visit(current: ast.AST) -> None:
            collected.append(current)
            if isinstance(
                current, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef, ast.Lambda)
            ):
                return
            for child in ast.iter_child_nodes(current):
                visit(child)

        for statement in node.body if isinstance(node, ast.ClassDef) else ():
            visit(statement)
        return tuple(collected)

    def _class_binding_is_definite(
        self,
        scope: _Scope,
        name: str,
        position: tuple[int, int],
    ) -> bool:
        class_node = self.class_scope_nodes[id(scope)]
        baselines = tuple(
            (
                statement.end_lineno or statement.lineno,
                statement.end_col_offset or statement.col_offset,
            )
            for statement in class_node.body
            if name in self._direct_statement_binding_names(statement)
            and (
                statement.end_lineno or statement.lineno,
                statement.end_col_offset or statement.col_offset,
            )
            < position
        )
        if not baselines:
            return False
        baseline = max(baselines)
        for node in self._class_body_nodes(class_node):
            node_position = (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))
            if not baseline < node_position < position:
                continue
            if isinstance(node, ast.Delete) and any(
                name in self._target_names(target) for target in node.targets
            ):
                return False
            if isinstance(node, ast.ExceptHandler) and node.name == name:
                return False
        return True

    def _lookup_value(
        self,
        scope: _Scope,
        name: str,
        lineno: int | None = None,
        col_offset: int | None = None,
    ) -> ResolvedValue:
        class_candidates: list[ResolvedValue] = []
        current: _Scope | None = scope
        while current is not None:
            class_binding_is_live = bool(
                id(current) not in self.class_scope_ids
                or lineno is None
                or current.lines.get(name, lineno) < lineno
            )
            if name in current.values and class_binding_is_live:
                if (id(current), name) in self.active_alias_bindings and (
                    lineno is None or current.lines.get(name, lineno) >= lineno
                ):
                    existing = current.values[name]
                    self._record_fail_closed_finding(
                        "alias-cycle",
                        name,
                        lineno or current.lines.get(name, 0),
                    )
                    return _unknown_value(
                        existing.direct_origins | existing.aggregate_origins,
                        sensitive=True,
                    )
                if id(current) not in self.class_scope_ids:
                    return _merge_values((*class_candidates, current.values[name]))
                if (
                    lineno is not None
                    and col_offset is not None
                    and self._class_binding_is_definite(
                        current,
                        name,
                        (lineno, col_offset),
                    )
                ):
                    return _merge_values((*class_candidates, current.values[name]))
                class_candidates.append(current.values[name])
            current = current.parent
            while current is not None and id(current) in self.class_scope_ids:
                current = current.parent
        if name in _DYNAMIC_BUILTIN_NAMES | _SAFE_BUILTIN_NAMES:
            fallback = _direct_value(frozenset({f"builtins.{name}"}))
        else:
            fallback = _unknown_value(sensitive=False)
        return _merge_values((*class_candidates, fallback))

    def _is_unresolved_bare_parameter(
        self,
        node: ast.AST,
        scope: _Scope,
        value: ResolvedValue,
        bindings: frozenset[tuple[int, str]],
    ) -> bool:
        """Recognize an unknown parameter only at its sensitive use site."""

        if not isinstance(node, ast.Name) or not value.is_unknown or value.direct_origins:
            return False
        current: _Scope | None = scope
        while current is not None:
            if node.id in current.kinds:
                return (id(current), node.id) in bindings
            current = current.parent
            while current is not None and id(current) in self.class_scope_ids:
                current = current.parent
        return False

    def _record_fail_closed_finding(self, code: str, symbol: str, lineno: int) -> None:
        finding = (code, symbol, lineno)
        if finding in self.reported_fail_closed_limits:
            return
        self.reported_fail_closed_limits.add(finding)
        self.findings.append(ArchitectureFinding(code, symbol, lineno))

    def _reported_scope_path(self, scope: _Scope) -> tuple[str, ...]:
        return tuple(
            component for component in scope.path if not component.startswith("<comprehension:")
        )

    def _real_numeric_representation(self, value: bool | int | float) -> str | None:
        if isinstance(value, (bool, int)):
            return f"{int(value)}/1"
        try:
            numerator, denominator = value.as_integer_ratio()
        except (OverflowError, ValueError):
            if value != value:
                return None
            return f"special:{value!r}"
        return f"{numerator}/{denominator}"

    def _literal_static_key(self, value: object) -> _StaticKey | None:
        if value is None:
            return _StaticKey("none", "None")
        if isinstance(value, (bool, int, float)):
            representation = self._real_numeric_representation(value)
            if representation is None:
                return None
            return _StaticKey("number", f"real:{representation}")
        if isinstance(value, complex):
            real = self._real_numeric_representation(value.real)
            if real is None:
                return None
            if value.imag == 0:
                return _StaticKey("number", f"real:{real}")
            imaginary = self._real_numeric_representation(value.imag)
            if imaginary is None:
                return None
            return _StaticKey("number", f"complex:{real}:{imaginary}")
        if isinstance(value, str):
            return _StaticKey("str", repr(value))
        if isinstance(value, bytes):
            return _StaticKey("bytes", repr(value))
        if isinstance(value, tuple):
            items = tuple(self._literal_static_key(item) for item in value)
            if any(item is None for item in items):
                return None
            return _StaticKey(
                "tuple",
                repr(
                    tuple(
                        (item.type_name, item.representation) for item in items if item is not None
                    )
                ),
            )
        return None

    def _static_key(self, node: ast.AST) -> _StaticKey | None:
        try:
            value = ast.literal_eval(node)
        except (TypeError, ValueError):
            return None
        return self._literal_static_key(value)

    def _with_static_key(self, node: ast.AST, value: ResolvedValue) -> ResolvedValue:
        """Carry the shared canonical key after an exact expression loses its AST."""

        if value.static_key is not None or not isinstance(
            node,
            (ast.BinOp, ast.Constant, ast.Tuple, ast.UnaryOp),
        ):
            return value
        static_key = self._static_key(node)
        return value if static_key is None else value._replace(static_key=static_key)

    def _static_integer(self, node: ast.AST | None) -> tuple[bool, int | None]:
        if node is None:
            return True, None
        try:
            value = ast.literal_eval(node)
        except (TypeError, ValueError):
            return False, None
        if isinstance(value, int):
            return True, value
        return False, None

    def _contained_origins(self, value: ResolvedValue) -> frozenset[str]:
        if value.sequence_elements is not None:
            return frozenset(
                origin
                for element in value.sequence_elements
                for origin in element.aggregate_origins
            )
        if value.mapping_entries is not None:
            return value.aggregate_origins | frozenset(
                origin
                for _key, entry_value in value.mapping_entries
                for origin in entry_value.aggregate_origins
            )
        return value.aggregate_origins

    def _resolve_iteration_value(
        self,
        iterable_node: ast.expr,
        scope: _Scope,
        active_functions: frozenset[str],
    ) -> ResolvedValue:
        iterable = self._resolve_expression(iterable_node, scope, active_functions)
        if iterable.sequence_elements is not None:
            return _mark_unknown_leaves_sensitive(_merge_values(iterable.sequence_elements))
        if iterable.mapping_entries is not None:
            return _merge_values(
                tuple(ResolvedValue(static_key=key) for key, _value in iterable.mapping_entries)
            )
        if iterable.sequence_kind == "set" and iterable.aggregate_origins:
            return _unknown_value(iterable.aggregate_origins, sensitive=True)
        if iterable.is_unknown and (iterable.aggregate_origins or iterable.sensitive_unknown):
            return _unknown_value(iterable.aggregate_origins, sensitive=True)
        return ResolvedValue(
            sequence_kind="unresolved-iteration",
            is_unknown=True,
            sensitive_unknown=True,
        )

    def _is_iteration_derived_alias(self, node: ast.expr) -> bool:
        if id(node) in self.iteration_alias_scopes:
            return True
        return isinstance(node, ast.Subscript) and self._is_iteration_derived_alias(node.value)

    def _resolve_subscript(
        self,
        node: ast.Subscript,
        scope: _Scope,
        active_functions: frozenset[str],
    ) -> ResolvedValue:
        if iteration_scope := self.iteration_alias_scopes.get(id(node)):
            return self._resolve_iteration_value(node.value, iteration_scope, active_functions)
        container = self._resolve_expression(node.value, scope, active_functions)
        possible = self._contained_origins(container)
        if (
            shape := self.destructuring_alias_shapes.get(id(node))
        ) is not None and container.sequence_elements is not None:
            target_length, star_index = shape
            source_length = len(container.sequence_elements)
            valid = (
                source_length == target_length
                if star_index is None
                else source_length >= target_length - 1
            )
            if not valid:
                return _unknown_value(possible, sensitive=True)
        if isinstance(node.slice, ast.Slice):
            lower_known, lower = self._static_integer(node.slice.lower)
            upper_known, upper = self._static_integer(node.slice.upper)
            step_known, step = self._static_integer(node.slice.step)
            if (
                container.sequence_elements is not None
                and lower_known
                and upper_known
                and step_known
                and step != 0
            ):
                selected = container.sequence_elements[slice(lower, upper, step)]
                return _sequence_value(container.sequence_kind or "sequence", selected)
            return _unknown_value(possible, sensitive=True)

        key = self._static_key(node.slice)
        if container.sequence_elements is not None:
            known_index, index = self._static_integer(node.slice)
            if known_index and index is not None:
                try:
                    return _mark_unknown_leaves_sensitive(container.sequence_elements[index])
                except IndexError:
                    return _unknown_value(possible, sensitive=True)
            return _unknown_value(possible, sensitive=True)
        if container.mapping_entries is not None:
            entries = dict(container.mapping_entries)
            if key is not None and key in entries:
                return _mark_unknown_leaves_sensitive(entries[key])
            return _unknown_value(possible, sensitive=True)
        if container.sequence_kind == "unresolved-iteration":
            return container
        return _unknown_value(
            (
                container.aggregate_origins | container.direct_origins
                if container.sensitive_unknown or not container.direct_origins
                else frozenset()
            ),
            sensitive=True,
        )

    def _simple_local_return(
        self,
        target: str,
        active_functions: frozenset[str],
        call_lineno: int,
        call_scope: _Scope,
    ) -> ResolvedValue | None:
        definitions = self.local_functions.get(target)
        if definitions is None:
            return None
        binding_scope = definitions[0][1].parent
        immediate_scope = call_scope
        while immediate_scope.parent is not None and immediate_scope.path[-1].startswith(
            "<comprehension:"
        ):
            immediate_scope = immediate_scope.parent
        preceding = tuple(local for local in definitions if local[0].lineno < call_lineno)
        include_unbound = False
        if immediate_scope is not binding_scope:
            selected = tuple(definitions)
            include_unbound = bool(
                not any(self._definition_is_unconditional(local[0]) for local in definitions)
                or (
                    binding_scope is not self.module_scope
                    and any(local[0].lineno > call_lineno for local in definitions)
                )
            )
        elif not preceding:
            return _unknown_value(sensitive=True)
        else:
            unconditional = tuple(
                local for local in preceding if self._definition_is_unconditional(local[0])
            )
            if not unconditional:
                selected = preceding
                include_unbound = True
            else:
                baseline = max(unconditional, key=lambda local: local[0].lineno)
                selected = (
                    baseline,
                    *(
                        local
                        for local in preceding
                        if local[0].lineno > baseline[0].lineno
                        and not self._definition_is_unconditional(local[0])
                    ),
                )
        resolved = tuple(
            self._simple_function_return(target, node, child, active_functions)
            for node, child in selected
        )
        return _merge_values(
            (*resolved, _unknown_value(sensitive=True)) if include_unbound else resolved
        )

    def _merge_parameter_value(
        self,
        scope: _Scope,
        name: str,
        value: ResolvedValue,
    ) -> bool:
        binding = (id(scope), name)
        used_for_mutation = binding in self.sensitive_parameter_bindings
        used_as_callable = binding in self.callable_parameter_bindings
        possible_origins = value.direct_origins | value.aggregate_origins
        if (
            not (used_for_mutation or used_as_callable)
            or (not possible_origins and not (used_for_mutation and value.sensitive_unknown))
            or (
                used_as_callable
                and not used_for_mutation
                and not any(
                    _qualified_call_target_is_forbidden(origin) for origin in possible_origins
                )
            )
        ):
            return False
        previous_base = scope.base_values.get(name, ResolvedValue())
        combined_base = _merge_values((previous_base, value))
        if combined_base == previous_base:
            return False
        scope.base_values[name] = combined_base
        scope.values[name] = _merge_values((scope.values.get(name, ResolvedValue()), value))
        return True

    def _bind_local_call_inputs(
        self,
        node: ast.Call,
        call_scope: _Scope,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        child: _Scope,
    ) -> bool:
        changed = False
        positional_parameters = (*function.args.posonlyargs, *function.args.args)
        keyword_parameters = {
            argument.arg: argument for argument in (*function.args.args, *function.args.kwonlyargs)
        }
        positional_values: list[ResolvedValue] = []
        unresolved_starred: list[ResolvedValue] = []
        for argument in node.args:
            if isinstance(argument, ast.Starred):
                value = self._resolve_expression(argument.value, call_scope)
                if value.sequence_elements is None:
                    unresolved_starred.append(
                        _unknown_value(value.aggregate_origins, sensitive=True)
                    )
                else:
                    positional_values.extend(value.sequence_elements)
            else:
                positional_values.append(self._resolve_expression(argument, call_scope))
        for parameter, value in zip(
            positional_parameters,
            positional_values,
            strict=False,
        ):
            changed = self._merge_parameter_value(child, parameter.arg, value) or changed
        extra_values = positional_values[len(positional_parameters) :]
        if function.args.vararg is not None and extra_values:
            changed = (
                self._merge_parameter_value(
                    child,
                    function.args.vararg.arg,
                    _sequence_value("tuple", tuple(extra_values)),
                )
                or changed
            )
        if unresolved_starred:
            uncertain = _merge_values((*positional_values, *unresolved_starred))
            possible = _unknown_value(uncertain.aggregate_origins, sensitive=True)
            for parameter in positional_parameters:
                changed = self._merge_parameter_value(child, parameter.arg, possible) or changed
            if function.args.vararg is not None:
                changed = (
                    self._merge_parameter_value(child, function.args.vararg.arg, possible)
                    or changed
                )

        extra_keywords: list[tuple[_StaticKey, ResolvedValue]] = []
        for keyword in node.keywords:
            value = self._resolve_expression(keyword.value, call_scope)
            if keyword.arg is None:
                if value.mapping_entries is not None:
                    for name, parameter in keyword_parameters.items():
                        key = self._literal_static_key(name)
                        entries = dict(value.mapping_entries)
                        if key is not None and key in entries:
                            changed = (
                                self._merge_parameter_value(child, parameter.arg, entries[key])
                                or changed
                            )
                    if function.args.kwarg is not None:
                        extra_keywords.extend(value.mapping_entries)
                else:
                    possible = _unknown_value(value.aggregate_origins, sensitive=True)
                    for parameter in keyword_parameters.values():
                        changed = (
                            self._merge_parameter_value(child, parameter.arg, possible) or changed
                        )
                    if function.args.kwarg is not None:
                        changed = (
                            self._merge_parameter_value(child, function.args.kwarg.arg, possible)
                            or changed
                        )
                continue
            keyword_parameter = keyword_parameters.get(keyword.arg)
            if keyword_parameter is not None:
                changed = (
                    self._merge_parameter_value(child, keyword_parameter.arg, value) or changed
                )
            elif function.args.kwarg is not None:
                key = self._literal_static_key(keyword.arg)
                if key is not None:
                    extra_keywords.append((key, value))
        if function.args.kwarg is not None and extra_keywords:
            changed = (
                self._merge_parameter_value(
                    child,
                    function.args.kwarg.arg,
                    _mapping_value(tuple(extra_keywords)),
                )
                or changed
            )
        return changed

    def _sensitive_parameter_bindings(self) -> frozenset[tuple[int, str]]:
        sensitive_bindings: set[tuple[int, str]] = set()
        for definitions in self.local_functions.values():
            for function, child in definitions:
                sensitive_names: set[str] = set()
                for node in ast.walk(function):
                    if self.node_scopes.get(id(node)) is not child:
                        continue
                    sensitive_nodes: tuple[ast.AST, ...] = ()
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr
                        in _REGISTRY_MUTATION_ATTRIBUTES | _BUILTIN_MUTATION_ATTRIBUTES
                    ):
                        sensitive_nodes = (node.func.value,)
                    elif isinstance(node, ast.Assign):
                        sensitive_nodes = tuple(
                            target for target in node.targets if not isinstance(target, ast.Name)
                        )
                    elif isinstance(node, ast.AnnAssign) and not isinstance(node.target, ast.Name):
                        sensitive_nodes = (node.target,)
                    elif isinstance(node, (ast.AugAssign, ast.Delete)):
                        sensitive_nodes = (
                            (node.target,)
                            if isinstance(node, ast.AugAssign)
                            else tuple(node.targets)
                        )
                    sensitive_names.update(
                        loaded.id
                        for sensitive_node in sensitive_nodes
                        for loaded in ast.walk(sensitive_node)
                        if isinstance(loaded, ast.Name)
                    )
                changed = True
                while changed:
                    changed = False
                    for name in tuple(sensitive_names):
                        dependencies = frozenset(
                            dependency
                            for expression in child.aliases.get(name, ())
                            for dependency in self._alias_dependencies(expression)
                        )
                        if not dependencies.issubset(sensitive_names):
                            sensitive_names.update(dependencies)
                            changed = True
                parameters = {
                    argument.arg
                    for argument in (
                        *function.args.posonlyargs,
                        *function.args.args,
                        *function.args.kwonlyargs,
                    )
                }
                if function.args.vararg is not None:
                    parameters.add(function.args.vararg.arg)
                if function.args.kwarg is not None:
                    parameters.add(function.args.kwarg.arg)
                sensitive_bindings.update(
                    (id(child), name) for name in parameters & sensitive_names
                )
        return frozenset(sensitive_bindings)

    def _callable_parameter_bindings(self) -> frozenset[tuple[int, str]]:
        callable_bindings: set[tuple[int, str]] = set()
        for definitions in self.local_functions.values():
            for function, child in definitions:
                callable_names = {
                    loaded.id
                    for node in ast.walk(function)
                    if isinstance(node, ast.Call) and self.node_scopes.get(id(node)) is child
                    for loaded in ast.walk(node.func)
                    if isinstance(loaded, ast.Name) and isinstance(loaded.ctx, ast.Load)
                }
                changed = True
                while changed:
                    changed = False
                    for name in tuple(callable_names):
                        dependencies = frozenset(
                            dependency
                            for expression in child.aliases.get(name, ())
                            for dependency in self._alias_dependencies(expression)
                        )
                        if not dependencies.issubset(callable_names):
                            callable_names.update(dependencies)
                            changed = True
                parameters = {
                    argument.arg
                    for argument in (
                        *function.args.posonlyargs,
                        *function.args.args,
                        *function.args.kwonlyargs,
                    )
                }
                if function.args.vararg is not None:
                    parameters.add(function.args.vararg.arg)
                if function.args.kwarg is not None:
                    parameters.add(function.args.kwarg.arg)
                callable_bindings.update((id(child), name) for name in parameters & callable_names)
        return frozenset(callable_bindings)

    def _call_argument_expressions(
        self,
        call: ast.Call,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> dict[str, tuple[ast.expr, ...]]:
        expressions: dict[str, list[ast.expr]] = {}
        positional_parameters = (*function.args.posonlyargs, *function.args.args)
        positional_index = 0
        for argument in call.args:
            if isinstance(argument, ast.Starred):
                for parameter in positional_parameters[positional_index:]:
                    expressions.setdefault(parameter.arg, []).append(argument.value)
                if function.args.vararg is not None:
                    expressions.setdefault(function.args.vararg.arg, []).append(argument.value)
                positional_index = len(positional_parameters)
                continue
            if positional_index < len(positional_parameters):
                parameter_name = positional_parameters[positional_index].arg
                positional_index += 1
            elif function.args.vararg is not None:
                parameter_name = function.args.vararg.arg
            else:
                continue
            expressions.setdefault(parameter_name, []).append(argument)
        keyword_parameters = {
            argument.arg for argument in (*function.args.args, *function.args.kwonlyargs)
        }
        for keyword in call.keywords:
            if keyword.arg is None:
                for parameter_name in keyword_parameters:
                    expressions.setdefault(parameter_name, []).append(keyword.value)
                if function.args.kwarg is not None:
                    expressions.setdefault(function.args.kwarg.arg, []).append(keyword.value)
            elif keyword.arg in keyword_parameters:
                expressions.setdefault(keyword.arg, []).append(keyword.value)
            elif function.args.kwarg is not None:
                expressions.setdefault(function.args.kwarg.arg, []).append(keyword.value)
        return {name: tuple(values) for name, values in expressions.items()}

    def _enclosing_function_scope(self, scope: _Scope) -> _Scope | None:
        function_scope_ids = {
            id(child)
            for definitions in self.local_functions.values()
            for _function, child in definitions
        }
        current: _Scope | None = scope
        while current is not None:
            if id(current) in function_scope_ids:
                return current
            current = current.parent
        return None

    def _caller_parameter_dependencies(
        self,
        caller: _Scope,
        expression: ast.expr,
    ) -> frozenset[str]:
        dependencies = set(self._alias_dependencies(expression))
        changed = True
        while changed:
            changed = False
            for name in tuple(dependencies):
                nested = {
                    dependency
                    for alias in caller.aliases.get(name, ())
                    for dependency in self._alias_dependencies(alias)
                }
                if not nested.issubset(dependencies):
                    dependencies.update(nested)
                    changed = True
        parameters = {name for name, kinds in caller.kinds.items() if "argument" in kinds}
        return frozenset(dependencies & parameters)

    def _propagate_parameter_use_bindings(
        self,
        sensitive_parameters: frozenset[tuple[int, str]],
        callable_parameters: frozenset[tuple[int, str]],
    ) -> tuple[frozenset[tuple[int, str]], frozenset[tuple[int, str]]]:
        sensitive = set(sensitive_parameters)
        callable_uses = set(callable_parameters)
        for _pass in range(_MAX_PARAMETER_PROPAGATION_PASSES):
            changed = False
            for call in (node for node in ast.walk(self.tree) if isinstance(node, ast.Call)):
                call_scope = self.node_scopes.get(id(call), self.module_scope)
                caller = self._enclosing_function_scope(call_scope)
                if caller is None:
                    continue
                targets = self._resolve_expression(call.func, call_scope).direct_origins
                for target in targets:
                    for function, callee in self.local_functions.get(target, ()):
                        arguments = self._call_argument_expressions(call, function)
                        for parameter_name, expressions in arguments.items():
                            callee_binding = (id(callee), parameter_name)
                            modes = (
                                (sensitive, callee_binding in sensitive),
                                (callable_uses, callee_binding in callable_uses),
                            )
                            for bindings, active in modes:
                                if not active:
                                    continue
                                for expression in expressions:
                                    for dependency in self._caller_parameter_dependencies(
                                        caller,
                                        expression,
                                    ):
                                        caller_binding = (id(caller), dependency)
                                        if caller_binding not in bindings:
                                            bindings.add(caller_binding)
                                            changed = True
            if not changed:
                return frozenset(sensitive), frozenset(callable_uses)
        all_parameters = {
            (id(scope), name)
            for scope in self.scopes
            for name, kinds in scope.kinds.items()
            if "argument" in kinds
        }
        self._record_fail_closed_finding(
            "unresolved-sensitive-provenance",
            "analysis:parameter-use-fixed-point-limit",
            0,
        )
        return frozenset(sensitive | all_parameters), frozenset(callable_uses | all_parameters)

    def _propagate_local_function_inputs(self) -> None:
        for _pass in range(_MAX_PARAMETER_PROPAGATION_PASSES):
            changed = False
            for definitions in self.local_functions.values():
                for function, child in definitions:
                    definition_scope = child.parent or self.module_scope
                    positional_parameters = (*function.args.posonlyargs, *function.args.args)
                    if function.args.defaults:
                        default_parameters = positional_parameters[-len(function.args.defaults) :]
                        for parameter, default in zip(
                            default_parameters,
                            function.args.defaults,
                            strict=True,
                        ):
                            changed = (
                                self._merge_parameter_value(
                                    child,
                                    parameter.arg,
                                    self._resolve_expression(default, definition_scope),
                                )
                                or changed
                            )
                    for kw_parameter, kw_default in zip(
                        function.args.kwonlyargs,
                        function.args.kw_defaults,
                        strict=True,
                    ):
                        if kw_default is not None:
                            changed = (
                                self._merge_parameter_value(
                                    child,
                                    kw_parameter.arg,
                                    self._resolve_expression(kw_default, definition_scope),
                                )
                                or changed
                            )
            for call in (node for node in ast.walk(self.tree) if isinstance(node, ast.Call)):
                call_scope = self.node_scopes.get(id(call), self.module_scope)
                argument_values = tuple(
                    self._resolve_expression(
                        argument.value if isinstance(argument, ast.Starred) else argument,
                        call_scope,
                    )
                    for argument in call.args
                ) + tuple(
                    self._resolve_expression(keyword.value, call_scope) for keyword in call.keywords
                )
                if not any(
                    value.direct_origins or value.aggregate_origins for value in argument_values
                ):
                    continue
                targets = self._resolve_expression(call.func, call_scope).direct_origins
                for target in targets:
                    for function, child in self.local_functions.get(target, ()):
                        changed = (
                            self._bind_local_call_inputs(call, call_scope, function, child)
                            or changed
                        )
            if changed:
                self._resolve_aliases()
                if self.alias_resolution_exhausted:
                    return
            else:
                return
        self._record_fail_closed_finding(
            "unresolved-sensitive-provenance",
            "analysis:local-input-fixed-point-limit",
            0,
        )
        for scope in self.scopes:
            for name, kinds in scope.kinds.items():
                if "argument" not in kinds:
                    continue
                current = scope.values.get(name, ResolvedValue())
                scope.values[name] = _unknown_value(
                    current.direct_origins | current.aggregate_origins,
                    sensitive=True,
                )

    def _flow_bind(self, state: _FlowState, name: str, value: ResolvedValue) -> _FlowState:
        if value.locations:
            value = self._compact_flow_value(value, state.store)
        value = _bounded_value(value)
        bindings = state.bindings
        lower = 0
        upper = len(bindings)
        while lower < upper:
            middle = (lower + upper) // 2
            if bindings[middle][0] < name:
                lower = middle + 1
            else:
                upper = middle
        if lower < len(bindings) and bindings[lower][0] == name:
            current = bindings[lower][1]
            if current is value or current == value:
                return state
            updated = (*bindings[:lower], (name, value), *bindings[lower + 1 :])
        else:
            updated = (*bindings[:lower], (name, value), *bindings[lower:])
        return state._replace(bindings=updated)

    def _flow_unbind(self, state: _FlowState, name: str) -> _FlowState:
        bindings = state.bindings
        lower = 0
        upper = len(bindings)
        while lower < upper:
            middle = (lower + upper) // 2
            if bindings[middle][0] < name:
                lower = middle + 1
            else:
                upper = middle
        if lower >= len(bindings) or bindings[lower][0] != name:
            return state
        return state._replace(bindings=(*bindings[:lower], *bindings[lower + 1 :]))

    def _flow_store_get(
        self,
        store: _AbstractStore,
        location: _AbstractLocation,
    ) -> _AbstractContainerState | None:
        entries = store.entries
        lower = 0
        upper = len(entries)
        while lower < upper:
            middle = (lower + upper) // 2
            if entries[middle][0] < location:
                lower = middle + 1
            else:
                upper = middle
        if lower < len(entries) and entries[lower][0] == location:
            return entries[lower][1]
        return None

    def _flow_store_set(
        self,
        store: _AbstractStore,
        location: _AbstractLocation,
        container: _AbstractContainerState,
    ) -> _AbstractStore:
        entries = store.entries
        lower = 0
        upper = len(entries)
        while lower < upper:
            middle = (lower + upper) // 2
            if entries[middle][0] < location:
                lower = middle + 1
            else:
                upper = middle
        exists = lower < len(entries) and entries[lower][0] == location
        if not exists and len(entries) >= _MAX_ABSTRACT_LOCATIONS:
            self._record_fail_closed_finding(
                "unresolved-sensitive-provenance",
                "analysis:abstract-location-limit",
                location.lineno,
            )
            return store
        if exists:
            current = entries[lower][1]
            if current is container or current == container:
                return store
            updated = (*entries[:lower], (location, container), *entries[lower + 1 :])
        else:
            updated = (*entries[:lower], (location, container), *entries[lower:])
        return _AbstractStore(updated)

    def _flow_location(self, node: ast.AST, scope: _Scope, kind: str) -> _AbstractLocation:
        return _AbstractLocation(
            scope.path,
            kind,
            getattr(node, "lineno", 0),
            getattr(node, "col_offset", 0),
        )

    def _container_possible_origins(
        self,
        container: _AbstractContainerState,
    ) -> frozenset[str]:
        values = (
            container.sequence_elements
            if container.sequence_elements is not None
            else tuple(value for _key, value in container.mapping_entries or ())
        )
        return container.unknown_value.aggregate_origins | frozenset(
            origin for value in values for origin in value.aggregate_origins
        )

    def _join_containers(
        self,
        containers: tuple[_AbstractContainerState, ...],
    ) -> _AbstractContainerState:
        if len(containers) == 1:
            return containers[0]
        first = containers[0]
        if all(container is first for container in containers[1:]) or all(
            container == first for container in containers[1:]
        ):
            return first
        kinds = {container.kind for container in containers}
        if len(kinds) != 1:
            possible = frozenset(
                origin
                for container in containers
                for origin in self._container_possible_origins(container)
            )
            return _AbstractContainerState(
                "unknown",
                unknown_value=_unknown_value(possible, sensitive=True),
                uncertain=True,
            )
        kind = containers[0].kind
        unknown = _merge_values(tuple(container.unknown_value for container in containers))
        uncertain = any(container.uncertain for container in containers)
        masked_sequence_indexes = set(containers[0].masked_sequence_indexes)
        masked_mapping_keys = set(containers[0].masked_mapping_keys)
        for container in containers[1:]:
            masked_sequence_indexes.intersection_update(container.masked_sequence_indexes)
            masked_mapping_keys.intersection_update(container.masked_mapping_keys)
        if kind == "list":
            shapes = tuple(container.sequence_elements for container in containers)
            if (
                all(shape is not None for shape in shapes)
                and len({len(shape) for shape in shapes if shape is not None}) == 1
            ):
                known_shapes = tuple(shape for shape in shapes if shape is not None)
                elements = tuple(
                    _merge_values(tuple(shape[index] for shape in known_shapes))
                    for index in range(len(known_shapes[0]))
                )
                return _AbstractContainerState(
                    kind,
                    sequence_elements=elements,
                    unknown_value=unknown,
                    uncertain=uncertain,
                    masked_sequence_indexes=frozenset(masked_sequence_indexes),
                )
            possible_elements = tuple(
                element for shape in shapes if shape is not None for element in shape
            )
            return _AbstractContainerState(
                kind,
                unknown_value=_merge_values((unknown, *possible_elements)),
                uncertain=True,
            )

        mappings = tuple(dict(container.mapping_entries or ()) for container in containers)
        keys = frozenset(key for mapping in mappings for key in mapping)
        masked_mapping_keys.intersection_update(
            key for key in keys if all(key in mapping for mapping in mappings)
        )
        entries: list[tuple[_StaticKey, ResolvedValue]] = []
        missing_key = False
        for key in sorted(keys):
            candidates = tuple(mapping[key] for mapping in mappings if key in mapping)
            missing_key = missing_key or len(candidates) != len(mappings)
            entries.append((key, _merge_values(candidates)))
        if len(entries) > _MAX_ABSTRACT_CONTAINER_WIDTH:
            possible = frozenset(
                origin for _key, value in entries for origin in value.aggregate_origins
            )
            return _AbstractContainerState(
                kind,
                unknown_value=_merge_values(
                    (unknown, _unknown_value(possible, sensitive=bool(possible)))
                ),
                uncertain=True,
            )
        if missing_key:
            possible = frozenset(
                origin for _key, value in entries for origin in value.aggregate_origins
            )
            unknown = _merge_values((unknown, _unknown_value(possible, sensitive=bool(possible))))
        return _AbstractContainerState(
            kind,
            mapping_entries=tuple(entries),
            unknown_value=unknown,
            uncertain=uncertain or missing_key,
            masked_mapping_keys=frozenset(masked_mapping_keys),
        )

    def _flow_join(self, states: tuple[_FlowState, ...]) -> _FlowState:
        if not states:
            return _FlowState()
        if len(states) > 2:
            unique_states: list[_FlowState] = []
            identities: set[int] = set()
            for state in states:
                identity = id(state)
                if identity in identities:
                    continue
                identities.add(identity)
                unique_states.append(state)
            if len(unique_states) != len(states):
                states = tuple(unique_states)
        if len(states) == 1:
            return states[0]
        first = states[0]
        if all(state is first for state in states[1:]) or all(
            state == first for state in states[1:]
        ):
            return first

        first_bindings = first.bindings
        if all(state.bindings is first_bindings for state in states[1:]) or all(
            state.bindings == first_bindings for state in states[1:]
        ):
            joined_bindings = first_bindings
        else:
            binding_maps = tuple(dict(state.bindings) for state in states)
            names = frozenset(name for bindings in binding_maps for name in bindings)
            bindings: list[tuple[str, ResolvedValue]] = []
            for name in sorted(names):
                candidates = tuple(bindings[name] for bindings in binding_maps if name in bindings)
                if len(candidates) != len(binding_maps):
                    possible = frozenset(
                        origin
                        for candidate in candidates
                        for origin in candidate.aggregate_origins | candidate.direct_origins
                    )
                    candidates = (*candidates, _unknown_value(sensitive=bool(possible)))
                bindings.append((name, _merge_values(candidates)))
            joined_bindings = tuple(bindings)
            if joined_bindings == first_bindings:
                joined_bindings = first_bindings

        first_store = first.store
        if all(state.store is first_store for state in states[1:]) or all(
            state.store == first_store for state in states[1:]
        ):
            joined_store = first_store
        else:
            stores = tuple(dict(state.store.entries) for state in states)
            locations = frozenset(location for store in stores for location in store)
            joined_entries: list[tuple[_AbstractLocation, _AbstractContainerState]] = []
            for location in sorted(locations):
                container_candidates = tuple(
                    store[location] for store in stores if location in store
                )
                joined = self._join_containers(container_candidates)
                joined_entries.append((location, joined))
            joined_store = _AbstractStore(tuple(joined_entries))
            if joined_store == first_store:
                joined_store = first_store

        if joined_bindings is first.bindings and joined_store is first.store:
            return first
        return _FlowState(joined_bindings, joined_store)

    def _record_flow_state(self, node: ast.AST, state: _FlowState) -> None:
        if not self._building_composite_flow or id(node) not in self.flow_snapshot_node_ids:
            return
        previous = self.flow_node_states.get(id(node))
        if previous is None:
            self.flow_node_states[id(node)] = state
            return
        if previous is state or previous == state:
            return
        joined = self._flow_join((previous, state))
        if joined is not previous and joined != previous:
            self.flow_node_states[id(node)] = joined

    def _record_flow_value(
        self,
        node: ast.AST,
        value: ResolvedValue,
        state: _FlowState,
    ) -> None:
        if not self._building_composite_flow or id(node) not in self.flow_snapshot_node_ids:
            return
        materialized = self._compact_flow_value(value, state.store)
        previous = self.flow_node_values.get(id(node))
        if previous is None:
            self.flow_node_values[id(node)] = materialized
        elif previous is not materialized and previous != materialized:
            self.flow_node_values[id(node)] = _merge_values((previous, materialized))
        self.flow_node_states.pop(id(node), None)

    def _compact_flow_value(
        self,
        value: ResolvedValue,
        store: _AbstractStore,
    ) -> ResolvedValue:
        """Retain queried provenance without copying the reachable composite graph."""

        pending: list[tuple[ResolvedValue, int]] = [(value, 1)]
        visited_values: set[int] = set()
        visited_locations: set[_AbstractLocation] = set()
        origins: set[str] = set()
        is_unknown = value.is_unknown
        sensitive_unknown = value.sensitive_unknown
        reachability_overflow = value.reachability_overflow
        uncertain_container = False
        visited = 0
        while pending:
            current, depth = pending.pop()
            identity = id(current)
            if identity in visited_values:
                continue
            visited_values.add(identity)
            visited += 1
            if visited > _MAX_ABSTRACT_STRUCTURE_NODES or depth > _MAX_ABSTRACT_STRUCTURE_DEPTH:
                is_unknown = True
                sensitive_unknown = True
                reachability_overflow = True
                break
            origins.update(current.direct_origins)
            origins.update(current.aggregate_origins)
            origins.update(current.deferred_origins)
            is_unknown = is_unknown or current.is_unknown
            sensitive_unknown = sensitive_unknown or current.sensitive_unknown
            reachability_overflow = reachability_overflow or current.reachability_overflow
            pending.extend((element, depth + 1) for element in current.sequence_elements or ())
            pending.extend(
                (entry_value, depth + 1) for _key, entry_value in current.mapping_entries or ()
            )
            for location in current.locations:
                if location in visited_locations:
                    continue
                visited_locations.add(location)
                container = self._flow_store_get(store, location)
                if container is None:
                    is_unknown = True
                    sensitive_unknown = True
                    reachability_overflow = True
                    continue
                uncertain_container = uncertain_container or container.uncertain
                pending.append((container.unknown_value, depth + 1))
                pending.extend(
                    (element, depth + 1) for element in container.sequence_elements or ()
                )
                pending.extend(
                    (entry_value, depth + 1)
                    for _key, entry_value in container.mapping_entries or ()
                )
        precise_location_identity = bool(
            value.locations and not value.location_uncertain and not reachability_overflow
        )
        if precise_location_identity:
            sensitive_unknown = value.sensitive_unknown
        else:
            sensitive_unknown = sensitive_unknown or (uncertain_container and bool(origins))
        return value._replace(
            sequence_elements=None,
            mapping_entries=None,
            aggregate_origins=frozenset(origins),
            is_unknown=is_unknown or uncertain_container,
            sensitive_unknown=sensitive_unknown,
            reachability_overflow=reachability_overflow,
        )

    def _flow_snapshot_nodes(self) -> set[int]:
        """Return exactly the AST nodes queried after temporal flow is fixed."""

        node_ids = {
            id(expression)
            for scope in self.scopes
            for expressions in scope.aliases.values()
            for expression in expressions
        }
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load):
                node_ids.add(id(node))
            if isinstance(node, ast.Call):
                node_ids.add(id(node.func))
                if isinstance(node.func, ast.Attribute):
                    node_ids.add(id(node.func.value))
                node_ids.update(id(keyword.value) for keyword in node.keywords)
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete)):
                targets = (
                    tuple(node.targets)
                    if isinstance(node, (ast.Assign, ast.Delete))
                    else (node.target,)
                )
                node_ids.update(
                    id(candidate) for target in targets for candidate in ast.walk(target)
                )
        return node_ids

    def _materialize_flow_value(
        self,
        value: ResolvedValue,
        store: _AbstractStore,
        active: frozenset[_AbstractLocation] = frozenset(),
    ) -> ResolvedValue:
        return self._materialize_flow_value_inner(value, store, active, {})

    def _materialize_flow_value_inner(
        self,
        value: ResolvedValue,
        store: _AbstractStore,
        active: frozenset[_AbstractLocation],
        memo: dict[
            tuple[int, frozenset[_AbstractLocation]],
            tuple[ResolvedValue, ResolvedValue],
        ],
    ) -> ResolvedValue:
        if (
            not value.locations
            and value.sequence_elements is None
            and value.mapping_entries is None
        ):
            return value
        memo_key = (id(value), active)
        cached = memo.get(memo_key)
        if cached is not None and cached[0] is value:
            return cached[1]
        if not value.locations:
            sequence_elements = (
                None
                if value.sequence_elements is None
                else tuple(
                    self._materialize_flow_value_inner(element, store, active, memo)
                    for element in value.sequence_elements
                )
            )
            mapping_entries = (
                None
                if value.mapping_entries is None
                else tuple(
                    (
                        key,
                        self._materialize_flow_value_inner(entry_value, store, active, memo),
                    )
                    for key, entry_value in value.mapping_entries
                )
            )
            if (
                sequence_elements == value.sequence_elements
                and mapping_entries == value.mapping_entries
            ):
                memo[memo_key] = (value, value)
                return value
            aggregate = (
                value.direct_origins
                | frozenset(
                    origin
                    for element in sequence_elements or ()
                    for origin in element.aggregate_origins
                )
                | frozenset(
                    origin
                    for _key, entry_value in mapping_entries or ()
                    for origin in entry_value.aggregate_origins
                )
            )
            materialized_value = _bounded_value(
                value._replace(
                    sequence_elements=sequence_elements,
                    mapping_entries=mapping_entries,
                    aggregate_origins=value.aggregate_origins | aggregate,
                )
            )
            memo[memo_key] = (value, materialized_value)
            return materialized_value

        materialized: list[ResolvedValue] = []
        for location in sorted(value.locations):
            container = self._flow_store_get(store, location)
            if container is None or location in active:
                materialized.append(
                    ResolvedValue(
                        direct_origins=value.direct_origins,
                        aggregate_origins=value.aggregate_origins | value.direct_origins,
                        is_unknown=True,
                        sensitive_unknown=True,
                        static_key=value.static_key,
                        locations=frozenset({location}),
                        location_uncertain=value.location_uncertain,
                        bound_mutators=value.bound_mutators,
                        bound_mutator_uncertain=value.bound_mutator_uncertain,
                        deferred_locations=value.deferred_locations,
                        deferred_origins=value.deferred_origins,
                        reachability_overflow=value.reachability_overflow,
                        temporally_derived=value.temporally_derived,
                    )
                )
                continue
            next_active = active | {location}
            unknown = self._materialize_flow_value_inner(
                container.unknown_value,
                store,
                next_active,
                memo,
            )
            if container.kind == "list":
                elements = (
                    None
                    if container.sequence_elements is None
                    else tuple(
                        self._materialize_flow_value_inner(element, store, next_active, memo)
                        for element in container.sequence_elements
                    )
                )
                if elements is not None and (
                    unknown.is_unknown
                    or unknown.sensitive_unknown
                    or unknown.aggregate_origins
                    or unknown.direct_origins
                ):
                    elements = tuple(
                        element
                        if index in container.masked_sequence_indexes
                        else _merge_values((element, unknown))
                        for index, element in enumerate(elements)
                    )
                aggregate = (
                    frozenset(
                        origin for element in elements or () for origin in element.aggregate_origins
                    )
                    | unknown.aggregate_origins
                )
                materialized.append(
                    ResolvedValue(
                        direct_origins=value.direct_origins,
                        sequence_kind="list",
                        sequence_elements=elements,
                        aggregate_origins=value.aggregate_origins | aggregate,
                        is_unknown=value.is_unknown or container.uncertain or unknown.is_unknown,
                        sensitive_unknown=(
                            value.sensitive_unknown
                            or unknown.sensitive_unknown
                            or (container.uncertain and bool(aggregate))
                        ),
                        static_key=value.static_key,
                        locations=frozenset({location}),
                        location_uncertain=value.location_uncertain,
                        bound_mutators=value.bound_mutators,
                        bound_mutator_uncertain=value.bound_mutator_uncertain,
                        deferred_locations=value.deferred_locations,
                        deferred_origins=value.deferred_origins,
                        reachability_overflow=value.reachability_overflow,
                        temporally_derived=value.temporally_derived,
                    )
                )
                continue
            entries = (
                None
                if container.mapping_entries is None
                else tuple(
                    (
                        key,
                        self._materialize_flow_value_inner(
                            entry_value,
                            store,
                            next_active,
                            memo,
                        )
                        if key in container.masked_mapping_keys
                        else _merge_values(
                            (
                                self._materialize_flow_value_inner(
                                    entry_value,
                                    store,
                                    next_active,
                                    memo,
                                ),
                                unknown,
                            )
                        )
                        if (
                            unknown.is_unknown
                            or unknown.sensitive_unknown
                            or unknown.aggregate_origins
                            or unknown.direct_origins
                        )
                        else self._materialize_flow_value_inner(
                            entry_value,
                            store,
                            next_active,
                            memo,
                        ),
                    )
                    for key, entry_value in container.mapping_entries
                )
            )
            aggregate = (
                frozenset(
                    origin
                    for _key, entry_value in entries or ()
                    for origin in entry_value.aggregate_origins
                )
                | unknown.aggregate_origins
            )
            materialized.append(
                ResolvedValue(
                    direct_origins=value.direct_origins,
                    mapping_entries=entries,
                    aggregate_origins=value.aggregate_origins | aggregate,
                    is_unknown=value.is_unknown or container.uncertain or unknown.is_unknown,
                    sensitive_unknown=(
                        value.sensitive_unknown
                        or unknown.sensitive_unknown
                        or (container.uncertain and bool(aggregate))
                    ),
                    static_key=value.static_key,
                    locations=frozenset({location}),
                    location_uncertain=value.location_uncertain,
                    bound_mutators=value.bound_mutators,
                    bound_mutator_uncertain=value.bound_mutator_uncertain,
                    deferred_locations=value.deferred_locations,
                    deferred_origins=value.deferred_origins,
                    reachability_overflow=value.reachability_overflow,
                    temporally_derived=value.temporally_derived,
                )
            )
        materialized_value = _merge_values(tuple(materialized))
        memo[memo_key] = (value, materialized_value)
        return materialized_value

    def _flow_lookup(self, scope: _Scope, state: _FlowState, node: ast.Name) -> ResolvedValue:
        value = _flow_binding_get(state.bindings, node.id)
        if value is None:
            value = self._lookup_value(scope, node.id, node.lineno, node.col_offset)
        if not value.temporally_derived and not value.locations.isdisjoint(
            self.flow_mutated_locations
        ):
            value = value._replace(temporally_derived=True)
        return self._compact_flow_value(value, state.store) if value.locations else value

    def _flow_attribute_value(
        self,
        owner: ResolvedValue,
        attribute: str,
        state: _FlowState,
    ) -> ResolvedValue:
        direct = frozenset(f"{origin}.{attribute}" for origin in owner.direct_origins)
        if owner.sequence_kind in {"generator", "lazy-adapter"} and attribute == "__next__":
            direct = direct | {"builtins.generator.__next__"}
        modeled_locations = frozenset(
            location
            for location in owner.locations
            if (
                (container := self._flow_store_get(state.store, location)) is not None
                and container.kind in {"dict", "list"}
            )
        )
        bound_mutators = (
            frozenset(
                {
                    _BoundMutator(
                        attribute,
                        modeled_locations,
                        owner.location_uncertain or modeled_locations != owner.locations,
                    )
                }
            )
            if modeled_locations and attribute in _BUILTIN_MUTATION_ATTRIBUTES
            else frozenset()
        )
        modeled_mutator = bool(bound_mutators)
        unmodeled_receiver_possible = bool(
            modeled_locations != owner.locations
            or (
                owner.location_uncertain
                and (
                    owner.direct_origins
                    or owner.is_unknown
                    or owner.sensitive_unknown
                    or owner.deferred_origins
                    or owner.reachability_overflow
                )
            )
        )
        return ResolvedValue(
            direct_origins=direct,
            aggregate_origins=owner.aggregate_origins | direct,
            is_unknown=owner.is_unknown and not modeled_mutator,
            sensitive_unknown=owner.sensitive_unknown
            and (not modeled_mutator or owner.location_uncertain),
            bound_mutators=bound_mutators,
            bound_mutator_uncertain=modeled_mutator and unmodeled_receiver_possible,
            reachability_overflow=owner.reachability_overflow,
            temporally_derived=owner.temporally_derived,
        )

    def _flow_reachable_locations(
        self,
        values: tuple[ResolvedValue, ...],
        store: _AbstractStore,
    ) -> frozenset[_AbstractLocation]:
        pending: list[tuple[ResolvedValue, int]] = [(value, 1) for value in values]
        locations: set[_AbstractLocation] = set()
        visited = 0
        while pending:
            value, depth = pending.pop()
            visited += 1
            if (
                value.reachability_overflow
                or visited > _MAX_ABSTRACT_STRUCTURE_NODES
                or depth > _MAX_ABSTRACT_STRUCTURE_DEPTH
            ):
                return frozenset(location for location, _container in store.entries)
            locations.update(value.deferred_locations)
            locations.update(
                location for mutator in value.bound_mutators for location in mutator.locations
            )
            pending.extend((element, depth + 1) for element in value.sequence_elements or ())
            pending.extend(
                (entry_value, depth + 1) for _key, entry_value in value.mapping_entries or ()
            )
            for location in value.locations:
                if location in locations:
                    continue
                locations.add(location)
                container = self._flow_store_get(store, location)
                if container is None:
                    continue
                pending.append((container.unknown_value, depth + 1))
                pending.extend(
                    (element, depth + 1) for element in container.sequence_elements or ()
                )
                pending.extend(
                    (entry_value, depth + 1)
                    for _key, entry_value in container.mapping_entries or ()
                )
        return frozenset(locations)

    def _flow_consume_deferred(
        self,
        value: ResolvedValue,
        state: _FlowState,
    ) -> _FlowState:
        if not value.deferred_locations and not value.reachability_overflow:
            return state
        locations = (
            frozenset(location for location, _container in state.store.entries)
            if value.reachability_overflow
            else value.deferred_locations
        )
        possible = _unknown_value(
            value.deferred_origins | value.aggregate_origins | value.direct_origins,
            sensitive=value.sensitive_unknown or value.reachability_overflow,
        )
        store = state.store
        for location in sorted(locations):
            container = self._flow_store_get(store, location)
            if container is None:
                continue
            store = self._flow_store_set(
                store,
                location,
                self._flow_unknown_write(container, possible),
            )
        return state._replace(store=store)

    def _flow_callable_parameters(
        self,
        function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
    ) -> tuple[str, ...]:
        parameters = tuple(
            argument.arg
            for argument in (
                *function.args.posonlyargs,
                *function.args.args,
                *function.args.kwonlyargs,
            )
        )
        if function.args.vararg is not None:
            parameters = (*parameters, function.args.vararg.arg)
        if function.args.kwarg is not None:
            parameters = (*parameters, function.args.kwarg.arg)
        return parameters

    def _flow_function_node_count(
        self,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        function_scope: _Scope,
    ) -> int:
        cached = self.flow_function_node_counts.get(id(function))
        if cached is not None:
            return cached
        count = sum(
            1 for node in ast.walk(function) if self.node_scopes.get(id(node)) is function_scope
        )
        self.flow_function_node_counts[id(function)] = count
        return count

    def _flow_callable_ast_may_mutate(
        self,
        root: ast.AST,
        callback_scope: _Scope,
        active_scopes: frozenset[int] = frozenset(),
    ) -> bool:
        scope_id = id(callback_scope)
        if scope_id in active_scopes:
            return True
        active_scopes = active_scopes | {scope_id}
        if isinstance(root, (ast.AsyncFunctionDef, ast.FunctionDef)) and (
            isinstance(root, ast.AsyncFunctionDef) or root.decorator_list
        ):
            return True
        for candidate in ast.walk(root):
            if self.node_scopes.get(id(candidate)) is not callback_scope:
                continue
            if (
                isinstance(candidate, ast.Call)
                and isinstance(candidate.func, ast.Attribute)
                and candidate.func.attr
                in _REGISTRY_MUTATION_ATTRIBUTES | _BUILTIN_MUTATION_ATTRIBUTES
            ):
                return True
            if isinstance(candidate, ast.Assign) and any(
                not isinstance(target, ast.Name) for target in candidate.targets
            ):
                return True
            if isinstance(candidate, ast.AnnAssign) and not isinstance(
                candidate.target,
                ast.Name,
            ):
                return True
            if isinstance(candidate, (ast.AugAssign, ast.Delete)):
                return True
            if not isinstance(candidate, ast.Call):
                continue
            target = self._resolve_expression(candidate.func, callback_scope)
            if target.bound_mutators or target.is_unknown or target.sensitive_unknown:
                return True
            if not target.direct_origins:
                return True
            for origin in target.direct_origins:
                definitions = self.local_functions.get(origin, ())
                if definitions:
                    if any(
                        self._flow_callable_ast_may_mutate(
                            function,
                            child,
                            active_scopes,
                        )
                        for function, child in definitions
                    ):
                        return True
                    continue
                if origin == "typing.cast":
                    continue
                if not origin.startswith("builtins."):
                    return True
                if _qualified_call_target_is_forbidden(origin):
                    return True
        return False

    def _flow_function_may_mutate(
        self,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        function_scope: _Scope,
    ) -> bool:
        cached = self.flow_function_may_mutate.get(id(function))
        if cached is None:
            cached = self._flow_callable_ast_may_mutate(function, function_scope)
            self.flow_function_may_mutate[id(function)] = cached
        return cached

    def _flow_callback_effect(
        self,
        callback: ResolvedValue,
        arguments: tuple[ResolvedValue, ...],
        scope: _Scope,
        state: _FlowState,
        *,
        callback_node: ast.AST | None = None,
        active_origins: frozenset[str] = frozenset(),
    ) -> ResolvedValue:
        if callback.static_key == self._literal_static_key(None):
            return ResolvedValue()
        locations: set[_AbstractLocation] = set()
        origins: set[str] = set()
        overflow = callback.reachability_overflow
        handled_origins: set[str] = set()
        argument_origins = frozenset(
            origin
            for value in arguments
            for origin in (value.direct_origins | value.aggregate_origins | value.deferred_origins)
        )
        for mutator in callback.bound_mutators:
            locations.update(mutator.locations)
            origins.update(argument_origins)
            if mutator.location_uncertain or callback.bound_mutator_uncertain:
                locations.update(self._flow_reachable_locations(arguments, state.store))

        inline_handled = False
        if isinstance(callback_node, ast.Lambda):
            callback_scope = self.node_scopes.get(id(callback_node.body), scope)
            inline_handled = True
            if self._flow_callable_ast_may_mutate(callback_node, callback_scope):
                parameters = frozenset(self._flow_callable_parameters(callback_node))
                local_names = frozenset(callback_scope.kinds) - parameters
                loaded_names = frozenset(
                    loaded.id
                    for loaded in ast.walk(callback_node)
                    if isinstance(loaded, ast.Name)
                    and isinstance(loaded.ctx, ast.Load)
                    and self.node_scopes.get(id(loaded)) is callback_scope
                )
                caller_bindings = dict(state.bindings)
                closure_values = tuple(
                    caller_bindings.get(
                        name,
                        self._lookup_value(
                            callback_scope,
                            name,
                            callback_node.lineno,
                            callback_node.col_offset,
                        ),
                    )
                    for name in sorted(loaded_names - parameters - local_names)
                )
                locations.update(self._flow_reachable_locations(closure_values, state.store))
                locations.update(self._flow_reachable_locations(arguments, state.store))
                origins.update(argument_origins)
                origins.update(
                    origin
                    for value in closure_values
                    for origin in value.direct_origins | value.aggregate_origins
                )

        for origin in sorted(callback.direct_origins):
            definitions = self.local_functions.get(origin, ())
            if not definitions:
                if origin == "typing.cast" or (
                    origin.startswith("builtins.")
                    and not _qualified_call_target_is_forbidden(origin)
                ):
                    handled_origins.add(origin)
                continue
            handled_origins.add(origin)
            if origin in active_origins:
                overflow = True
                continue
            for function, child in definitions:
                if not self._flow_callable_ast_may_mutate(function, child):
                    continue
                callable_parameters = self._flow_callable_parameters(function)
                parameter_names = frozenset(callable_parameters)
                local_names = frozenset(child.kinds) - parameter_names
                loaded_names = frozenset(
                    loaded.id
                    for loaded in ast.walk(function)
                    if isinstance(loaded, ast.Name)
                    and isinstance(loaded.ctx, ast.Load)
                    and self.node_scopes.get(id(loaded)) is child
                )
                caller_bindings = dict(state.bindings)
                closure_values = tuple(
                    caller_bindings.get(
                        name,
                        self._lookup_value(
                            child,
                            name,
                            function.lineno,
                            function.col_offset,
                        ),
                    )
                    for name in sorted(loaded_names - parameter_names - local_names)
                )
                locations.update(self._flow_reachable_locations(closure_values, state.store))
                sensitive_parameters = frozenset(
                    name
                    for name in parameter_names
                    if (id(child), name) in self.sensitive_parameter_bindings
                )
                if sensitive_parameters:
                    locations.update(self._flow_reachable_locations(arguments, state.store))
                    origins.update(argument_origins)
                origins.update(
                    candidate
                    for value in closure_values
                    for candidate in value.direct_origins | value.aggregate_origins
                )
                callable_indexes = tuple(
                    index
                    for index, name in enumerate(callable_parameters)
                    if (id(child), name) in self.callable_parameter_bindings
                )
                for index in callable_indexes:
                    if index >= len(arguments):
                        continue
                    nested = self._flow_callback_effect(
                        arguments[index],
                        (),
                        scope,
                        state,
                        active_origins=active_origins | {origin},
                    )
                    locations.update(nested.deferred_locations)
                    origins.update(nested.deferred_origins)
                    overflow = overflow or nested.reachability_overflow
                if child.parent is not scope and locations:
                    overflow = True

        unresolved = bool(
            ((callback.is_unknown or callback.sensitive_unknown) and not inline_handled)
            or (callback.direct_origins and handled_origins != set(callback.direct_origins))
            or (not callback.direct_origins and not callback.bound_mutators and not inline_handled)
        )
        if unresolved:
            locations.update(self._flow_reachable_locations(arguments, state.store))
            origins.update(argument_origins)
            overflow = True
        if not locations and not overflow:
            return ResolvedValue()
        origins.update(callback.deferred_origins)
        return ResolvedValue(
            is_unknown=True,
            sensitive_unknown=True,
            deferred_locations=frozenset(locations),
            deferred_origins=frozenset(origins),
            reachability_overflow=overflow,
        )

    def _flow_expression_callback_effect(
        self,
        roots: tuple[ast.AST, ...],
        execution_scope: _Scope,
        state: _FlowState,
    ) -> ResolvedValue:
        effects: list[ResolvedValue] = []
        for root in roots:
            for call in ast.walk(root):
                if not isinstance(call, ast.Call):
                    continue
                call_scope = self.node_scopes.get(id(call), execution_scope)
                if call_scope is not execution_scope:
                    continue
                callback, _shadow = self._flow_eval_expression(
                    call.func,
                    call_scope,
                    state,
                    apply_effects=False,
                )
                arguments: list[ResolvedValue] = []
                for argument in call.args:
                    value, _shadow = self._flow_eval_expression(
                        argument.value if isinstance(argument, ast.Starred) else argument,
                        call_scope,
                        state,
                        apply_effects=False,
                    )
                    arguments.append(value)
                effects.append(
                    self._flow_callback_effect(
                        callback,
                        tuple(arguments),
                        call_scope,
                        state,
                        callback_node=call.func,
                    )
                )
        return _merge_values(tuple(effects))

    def _flow_allocate_sequence(
        self,
        node: ast.AST,
        scope: _Scope,
        state: _FlowState,
        elements: tuple[ResolvedValue, ...] | None,
        unknown: ResolvedValue | None = None,
    ) -> tuple[ResolvedValue, _FlowState]:
        unknown = ResolvedValue() if unknown is None else unknown
        location = self._flow_location(node, scope, "list")
        if elements is not None and len(elements) > _MAX_ABSTRACT_CONTAINER_WIDTH:
            unknown = _unknown_value(
                frozenset(origin for element in elements for origin in element.aggregate_origins),
                sensitive=True,
            )
            elements = None
        container = _AbstractContainerState(
            "list",
            sequence_elements=elements,
            unknown_value=unknown,
            uncertain=elements is None,
        )
        previous = self._flow_store_get(state.store, location)
        if previous is not None:
            container = self._join_containers((previous, container))
        store = self._flow_store_set(state.store, location, container)
        reference = ResolvedValue(
            sequence_kind="list",
            sequence_elements=elements,
            aggregate_origins=self._container_possible_origins(container),
            is_unknown=container.uncertain,
            sensitive_unknown=container.unknown_value.sensitive_unknown,
            locations=frozenset({location}),
            location_uncertain=previous is not None,
            temporally_derived=bool(
                unknown.temporally_derived
                or any(element.temporally_derived for element in elements or ())
            ),
        )
        return reference, state._replace(store=store)

    def _flow_allocate_mapping(
        self,
        node: ast.AST,
        scope: _Scope,
        state: _FlowState,
        container: _AbstractContainerState,
    ) -> tuple[ResolvedValue, _FlowState]:
        if container.kind != "dict":
            raise ValueError("mapping allocation requires a dictionary container")
        location = self._flow_location(node, scope, "dict")
        previous = self._flow_store_get(state.store, location)
        if previous is not None:
            container = self._join_containers((previous, container))
        store = self._flow_store_set(state.store, location, container)
        reference = ResolvedValue(
            mapping_entries=container.mapping_entries,
            aggregate_origins=self._container_possible_origins(container),
            is_unknown=container.uncertain,
            sensitive_unknown=container.unknown_value.sensitive_unknown,
            locations=frozenset({location}),
            location_uncertain=previous is not None,
            temporally_derived=bool(
                container.unknown_value.temporally_derived
                or any(value.temporally_derived for _key, value in container.mapping_entries or ())
            ),
        )
        return reference, state._replace(store=store)

    def _flow_subscript_value(
        self,
        container: ResolvedValue,
        selector: ast.expr,
    ) -> ResolvedValue:
        def selected(value: ResolvedValue) -> ResolvedValue:
            if (
                container.temporally_derived
                or not value.locations.isdisjoint(self.flow_mutated_locations)
            ) and not value.temporally_derived:
                return value._replace(temporally_derived=True)
            return value

        possible = self._contained_origins(container)
        if isinstance(selector, ast.Slice):
            lower_known, lower = self._static_integer(selector.lower)
            upper_known, upper = self._static_integer(selector.upper)
            step_known, step = self._static_integer(selector.step)
            if (
                container.sequence_elements is not None
                and lower_known
                and upper_known
                and step_known
                and step != 0
            ):
                return selected(
                    _sequence_value(
                        "tuple" if container.sequence_kind == "tuple" else "list",
                        container.sequence_elements[slice(lower, upper, step)],
                    )
                )
            return selected(_unknown_value(possible, sensitive=True))
        if container.sequence_elements is not None:
            known, index = self._static_integer(selector)
            if known and index is not None:
                try:
                    return selected(
                        _mark_unknown_leaves_sensitive(container.sequence_elements[index])
                    )
                except IndexError:
                    return selected(_unknown_value(possible, sensitive=True))
            return selected(
                _merge_values(
                    (
                        *container.sequence_elements,
                        _unknown_value(possible, sensitive=True),
                    )
                )
            )
        if container.mapping_entries is not None:
            key = self._static_key(selector)
            entries = dict(container.mapping_entries)
            if key is not None and key in entries:
                return selected(_mark_unknown_leaves_sensitive(entries[key]))
            if key is None:
                return selected(
                    _merge_values(
                        (
                            *entries.values(),
                            _unknown_value(possible, sensitive=True),
                        )
                    )
                )
            return selected(_unknown_value(possible, sensitive=True))
        return selected(
            _unknown_value(
                container.aggregate_origins | container.direct_origins,
                sensitive=True,
            )
        )

    def _flow_stored_unknown_sequence_value(
        self,
        container: ResolvedValue,
        selector: ast.expr,
        store: _AbstractStore,
    ) -> ResolvedValue | None:
        """Recover possible elements summarized by modeled uncertain lists."""

        candidates: list[ResolvedValue] = []
        known_index, index = self._static_integer(selector)
        for location in sorted(container.locations):
            stored = self._flow_store_get(store, location)
            if stored is None or stored.kind != "list":
                return None
            unknown_applies = bool(
                stored.sequence_elements is None
                or not known_index
                or index is None
                or index not in stored.masked_sequence_indexes
            )
            if unknown_applies and stored.unknown_value != ResolvedValue():
                candidates.append(self._materialize_flow_value(stored.unknown_value, store))
        return _merge_values(tuple(candidates)) if candidates else None

    def _flow_eval_subscript_selector(
        self,
        selector: ast.expr,
        scope: _Scope,
        state: _FlowState,
        *,
        apply_effects: bool,
        active_functions: frozenset[str],
    ) -> _FlowState:
        components = (
            (selector.lower, selector.upper, selector.step)
            if isinstance(selector, ast.Slice)
            else (selector,)
        )
        for component in components:
            if component is None:
                continue
            _value, state = self._flow_eval_expression(
                component,
                scope,
                state,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
        return state

    def _flow_unknown_write(
        self,
        container: _AbstractContainerState,
        value: ResolvedValue,
    ) -> _AbstractContainerState:
        unknown = _merge_values(
            (
                container.unknown_value,
                value,
            )
        )
        return container._replace(
            unknown_value=unknown,
            uncertain=True,
            masked_sequence_indexes=frozenset(),
            masked_mapping_keys=frozenset(),
        )

    def _flow_write_locations(
        self,
        receiver: ResolvedValue,
        selector: ast.expr,
        value: ResolvedValue,
        state: _FlowState,
        *,
        deleting: bool = False,
    ) -> _FlowState:
        if value.locations:
            value = self._compact_flow_value(value, state.store)
        locations = tuple(sorted(receiver.locations))
        if not locations:
            return state
        self.flow_mutated_locations.update(locations)
        store = state.store
        singleton = len(locations) == 1
        precise_receiver = bool(singleton and not receiver.location_uncertain)
        for location in locations:
            container = self._flow_store_get(store, location)
            if container is None:
                continue
            if container.kind == "list":
                elements = container.sequence_elements
                if isinstance(selector, ast.Slice):
                    lower_known, lower = self._static_integer(selector.lower)
                    upper_known, upper = self._static_integer(selector.upper)
                    step_known, step = self._static_integer(selector.step)
                    replacement = value.sequence_elements
                    if (
                        precise_receiver
                        and elements is not None
                        and replacement is not None
                        and lower_known
                        and upper_known
                        and step_known
                        and step != 0
                    ):
                        changed = list(elements)
                        normalized_start, normalized_stop, normalized_step = slice(
                            lower,
                            upper,
                            step,
                        ).indices(len(elements))
                        changed[slice(lower, upper, step)] = () if deleting else replacement
                        if len(changed) <= _MAX_ABSTRACT_CONTAINER_WIDTH:
                            replacement_length = 0 if deleting else len(replacement)
                            masks = set(container.masked_sequence_indexes)
                            if normalized_step == 1:
                                removed_length = max(0, normalized_stop - normalized_start)
                                delta = replacement_length - removed_length
                                masks = {
                                    (masked if masked < normalized_start else masked + delta)
                                    for masked in masks
                                    if not normalized_start <= masked < normalized_stop
                                }
                                masks.update(
                                    range(
                                        normalized_start,
                                        normalized_start + replacement_length,
                                    )
                                )
                            else:
                                selected_indexes = tuple(
                                    range(
                                        normalized_start,
                                        normalized_stop,
                                        normalized_step,
                                    )
                                )
                                if not deleting:
                                    masks.update(selected_indexes)
                                else:
                                    masks.clear()
                            container = container._replace(
                                sequence_elements=tuple(changed),
                                masked_sequence_indexes=frozenset(masks),
                            )
                        else:
                            container = self._flow_unknown_write(container, value)
                    else:
                        container = self._flow_unknown_write(container, value)
                    store = self._flow_store_set(store, location, container)
                    continue
                known, index = self._static_integer(selector)
                if precise_receiver and known and index is not None and elements is not None:
                    normalized = index if index >= 0 else len(elements) + index
                    if 0 <= normalized < len(elements):
                        changed = list(elements)
                        if deleting:
                            del changed[normalized]
                            normalized_masks = frozenset(
                                masked if masked < normalized else masked - 1
                                for masked in container.masked_sequence_indexes
                                if masked != normalized
                            )
                        else:
                            changed[normalized] = value
                            normalized_masks = container.masked_sequence_indexes | {normalized}
                        container = container._replace(
                            sequence_elements=tuple(changed),
                            masked_sequence_indexes=normalized_masks,
                        )
                    else:
                        container = self._flow_unknown_write(container, value)
                elif known and index is not None and elements is not None and not deleting:
                    normalized = index if index >= 0 else len(elements) + index
                    if 0 <= normalized < len(elements):
                        changed = list(elements)
                        changed[normalized] = _merge_values((changed[normalized], value))
                        container = container._replace(
                            sequence_elements=tuple(changed),
                            uncertain=True,
                        )
                    else:
                        container = self._flow_unknown_write(container, value)
                else:
                    container = self._flow_unknown_write(container, value)
                store = self._flow_store_set(store, location, container)
                continue

            if container.kind == "dict":
                key = self._static_key(selector)
                entries = dict(container.mapping_entries or ())
                if precise_receiver and key is not None:
                    if deleting:
                        entries.pop(key, None)
                    else:
                        entries[key] = value
                    container = container._replace(
                        mapping_entries=tuple(sorted(entries.items())),
                        masked_mapping_keys=container.masked_mapping_keys | {key},
                    )
                elif key is not None and not deleting:
                    entries[key] = _merge_values(
                        tuple(
                            candidate
                            for candidate in (entries.get(key), value)
                            if candidate is not None
                        )
                    )
                    container = container._replace(
                        mapping_entries=tuple(sorted(entries.items())),
                        uncertain=True,
                    )
                else:
                    container = self._flow_unknown_write(container, value)
                store = self._flow_store_set(store, location, container)
        return state._replace(store=store)

    def _flow_clear_locations(self, receiver: ResolvedValue, state: _FlowState) -> _FlowState:
        locations = tuple(sorted(receiver.locations))
        precise_receiver = bool(len(locations) == 1 and not receiver.location_uncertain)
        store = state.store
        for location in locations:
            container = self._flow_store_get(store, location)
            if container is None:
                continue
            empty = (
                _AbstractContainerState("list", sequence_elements=())
                if container.kind == "list"
                else _AbstractContainerState("dict", mapping_entries=())
            )
            container = empty if precise_receiver else self._join_containers((container, empty))
            store = self._flow_store_set(store, location, container)
        return state._replace(store=store)

    def _flow_append_locations(
        self,
        receiver: ResolvedValue,
        values: tuple[ResolvedValue, ...] | None,
        state: _FlowState,
        *,
        index: int | None = None,
    ) -> _FlowState:
        locations = tuple(sorted(receiver.locations))
        self.flow_mutated_locations.update(locations)
        precise_receiver = bool(len(locations) == 1 and not receiver.location_uncertain)
        store = state.store
        possible = _merge_values(values or ())
        for location in locations:
            container = self._flow_store_get(store, location)
            if container is None or container.kind != "list":
                continue
            elements = container.sequence_elements
            if precise_receiver and elements is not None and values is not None:
                changed = list(elements)
                if index is None:
                    insertion = len(changed)
                elif index < 0:
                    insertion = max(0, len(changed) + index)
                else:
                    insertion = min(index, len(changed))
                changed[insertion:insertion] = values
                if len(changed) <= _MAX_ABSTRACT_CONTAINER_WIDTH:
                    masks = {
                        masked if masked < insertion else masked + len(values)
                        for masked in container.masked_sequence_indexes
                    }
                    masks.update(range(insertion, insertion + len(values)))
                    container = container._replace(
                        sequence_elements=tuple(changed),
                        masked_sequence_indexes=frozenset(masks),
                    )
                else:
                    container = self._flow_unknown_write(container, possible)
            else:
                container = self._flow_unknown_write(container, possible)
            store = self._flow_store_set(store, location, container)
        return state._replace(store=store)

    def _flow_update_mapping(
        self,
        receiver: ResolvedValue,
        writes: tuple[_OrderedMappingWrite, ...],
        state: _FlowState,
    ) -> _FlowState:
        locations = tuple(sorted(receiver.locations))
        self.flow_mutated_locations.update(locations)
        precise_receiver = bool(len(locations) == 1 and not receiver.location_uncertain)
        store = state.store
        for location in locations:
            container = self._flow_store_get(store, location)
            if container is None or container.kind != "dict":
                continue
            updated = _apply_ordered_mapping_writes(container, writes)
            container = (
                updated
                if precise_receiver
                else self._join_containers((container, updated))._replace(
                    uncertain=True,
                )
            )
            store = self._flow_store_set(store, location, container)
        return state._replace(store=store)

    def _flow_exact_mapping_updates(
        self,
        value: ResolvedValue,
    ) -> tuple[tuple[_StaticKey, ResolvedValue], ...] | None:
        if (
            value.mapping_entries is None
            or value.is_unknown
            or value.sensitive_unknown
            or value.reachability_overflow
        ):
            return None
        return value.mapping_entries

    def _flow_mapping_unknown_summary(
        self,
        value: ResolvedValue,
        store: _AbstractStore,
    ) -> ResolvedValue | None:
        """Preserve unknown-key state when copying a modeled dictionary."""

        summaries: list[ResolvedValue] = []
        for location in sorted(value.locations):
            container = self._flow_store_get(store, location)
            if container is None or container.kind != "dict":
                summaries.append(
                    _unknown_value(
                        value.direct_origins | value.aggregate_origins | value.deferred_origins,
                        sensitive=True,
                    )
                )
                continue
            unknown = container.unknown_value
            if not (
                container.uncertain
                or unknown.direct_origins
                or unknown.aggregate_origins
                or unknown.is_unknown
                or unknown.sensitive_unknown
                or unknown.reachability_overflow
            ):
                continue
            summaries.append(
                _unknown_value(
                    unknown.direct_origins | unknown.aggregate_origins | unknown.deferred_origins,
                    sensitive=True,
                )._replace(
                    reachability_overflow=unknown.reachability_overflow,
                    temporally_derived=unknown.temporally_derived,
                )
            )
        return _merge_values(tuple(summaries)) if summaries else None

    def _flow_ordered_mapping_write(
        self,
        value: ResolvedValue,
        store: _AbstractStore,
    ) -> _OrderedMappingWrite:
        """Return exact cells and one conservative unknown-key contribution."""

        materialized = self._materialize_flow_value(value, store)
        exact = self._flow_exact_mapping_updates(materialized)
        if exact is not None:
            return _OrderedMappingWrite(exact)

        candidate_entries = dict(materialized.mapping_entries or ())
        definite_keys: set[_StaticKey] = set()
        if candidate_entries and materialized.locations:
            definite_keys = set(candidate_entries)
            for location in sorted(materialized.locations):
                container = self._flow_store_get(store, location)
                if container is None or container.kind != "dict":
                    definite_keys.clear()
                    break
                container_keys = set(dict(container.mapping_entries or ()))
                if not container.uncertain and not _mapping_unknown_is_present(
                    container.unknown_value
                ):
                    guaranteed_keys = container_keys
                else:
                    guaranteed_keys = set(container.masked_mapping_keys)
                definite_keys.intersection_update(guaranteed_keys)

        unknown_values: list[ResolvedValue] = []
        summary = self._flow_mapping_unknown_summary(materialized, store)
        if summary is not None:
            unknown_values.append(summary)
        unknown_values.extend(
            _unknown_mapping_value(entry_value)
            for key, entry_value in candidate_entries.items()
            if key not in definite_keys
        )
        if (
            materialized.mapping_entries is None
            or materialized.direct_origins
            or materialized.deferred_origins
            or materialized.reachability_overflow
            or (materialized.is_unknown and not materialized.locations)
        ):
            unknown_values.append(_unknown_mapping_value(materialized))
        unknown = (
            _unknown_mapping_value(_merge_values(tuple(unknown_values))) if unknown_values else None
        )
        return _OrderedMappingWrite(
            tuple((key, candidate_entries[key]) for key in sorted(definite_keys)),
            unknown,
        )

    def _flow_location_reference(self, value: ResolvedValue) -> ResolvedValue:
        """Drop materialized cell snapshots while preserving receiver identity."""

        return ResolvedValue(
            direct_origins=value.direct_origins,
            aggregate_origins=value.direct_origins,
            is_unknown=value.is_unknown,
            sensitive_unknown=value.sensitive_unknown,
            static_key=value.static_key,
            locations=value.locations,
            location_uncertain=value.location_uncertain,
            bound_mutators=value.bound_mutators,
            bound_mutator_uncertain=value.bound_mutator_uncertain,
            deferred_locations=value.deferred_locations,
            deferred_origins=value.deferred_origins,
            reachability_overflow=value.reachability_overflow,
            temporally_derived=True,
        )

    def _flow_value_is_modeled_dictionary(
        self,
        value: ResolvedValue,
        store: _AbstractStore,
    ) -> bool:
        return bool(
            value.locations
            and all(
                (container := self._flow_store_get(store, location)) is not None
                and container.kind == "dict"
                for location in value.locations
            )
        )

    def _flow_inplace_mapping_union(
        self,
        receiver: ResolvedValue,
        right: ResolvedValue,
        state: _FlowState,
    ) -> tuple[ResolvedValue, _FlowState]:
        updated = self._flow_update_mapping(
            receiver,
            (self._flow_ordered_mapping_write(right, state.store),),
            state,
        )
        return self._flow_location_reference(receiver), updated

    def _flow_eval_expression(
        self,
        node: ast.AST,
        scope: _Scope,
        state: _FlowState,
        *,
        apply_effects: bool,
        active_functions: frozenset[str] = frozenset(),
    ) -> tuple[ResolvedValue, _FlowState]:
        value, result_state = self._flow_eval_expression_inner(
            node,
            scope,
            state,
            apply_effects=apply_effects,
            active_functions=active_functions,
        )
        value = self._with_static_key(node, value)
        self._record_flow_value(node, value, result_state)
        return value, result_state

    def _flow_eval_expression_inner(
        self,
        node: ast.AST,
        scope: _Scope,
        state: _FlowState,
        *,
        apply_effects: bool,
        active_functions: frozenset[str] = frozenset(),
    ) -> tuple[ResolvedValue, _FlowState]:
        self._record_flow_state(node, state)
        if isinstance(node, ast.Name):
            return self._flow_lookup(scope, state, node), state
        if isinstance(node, ast.Attribute):
            owner, state = self._flow_eval_expression(
                node.value,
                scope,
                state,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
            return self._flow_attribute_value(owner, node.attr, state), state
        if isinstance(node, ast.Constant):
            return ResolvedValue(static_key=self._literal_static_key(node.value)), state
        if isinstance(node, ast.Starred):
            return self._flow_eval_expression(
                node.value,
                scope,
                state,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
        if isinstance(node, (ast.Tuple, ast.List)):
            elements: list[ResolvedValue] = []
            unresolved: list[ResolvedValue] = []
            for item in node.elts:
                value, state = self._flow_eval_expression(
                    item.value if isinstance(item, ast.Starred) else item,
                    scope,
                    state,
                    apply_effects=apply_effects,
                    active_functions=active_functions,
                )
                if isinstance(item, ast.Starred):
                    state = self._flow_consume_deferred(value, state)
                    materialized = self._materialize_flow_value(value, state.store)
                    if materialized.sequence_elements is None:
                        unresolved.append(materialized)
                    else:
                        elements.extend(materialized.sequence_elements)
                else:
                    elements.append(value)
            if unresolved:
                possible = frozenset(
                    origin
                    for value in (*elements, *unresolved)
                    for origin in value.aggregate_origins
                )
                if isinstance(node, ast.List):
                    return self._flow_allocate_sequence(
                        node,
                        scope,
                        state,
                        None,
                        _unknown_value(possible, sensitive=True),
                    )
                return _unknown_value(possible, sensitive=True), state
            if isinstance(node, ast.List):
                return self._flow_allocate_sequence(node, scope, state, tuple(elements))
            return _sequence_value("tuple", tuple(elements)), state
        if isinstance(node, ast.Dict):
            mapping_container = _AbstractContainerState("dict", mapping_entries=())
            for key_node, value_node in zip(node.keys, node.values, strict=True):
                if key_node is None:
                    value, state = self._flow_eval_expression(
                        value_node,
                        scope,
                        state,
                        apply_effects=apply_effects,
                        active_functions=active_functions,
                    )
                    mapping_container = _apply_ordered_mapping_writes(
                        mapping_container,
                        (self._flow_ordered_mapping_write(value, state.store),),
                    )
                    continue
                key_value, state = self._flow_eval_expression(
                    key_node,
                    scope,
                    state,
                    apply_effects=apply_effects,
                    active_functions=active_functions,
                )
                value, state = self._flow_eval_expression(
                    value_node,
                    scope,
                    state,
                    apply_effects=apply_effects,
                    active_functions=active_functions,
                )
                key = self._static_key(key_node)
                if key is None:
                    write = _OrderedMappingWrite(
                        unknown_value=_unknown_mapping_value(_merge_values((key_value, value)))
                    )
                else:
                    write = _ordered_direct_mapping_write(
                        key,
                        value,
                    )
                mapping_container = _apply_ordered_mapping_writes(
                    mapping_container,
                    (write,),
                )
            return self._flow_allocate_mapping(
                node,
                scope,
                state,
                mapping_container,
            )
        if isinstance(node, ast.Set):
            values: list[ResolvedValue] = []
            for item in node.elts:
                value, state = self._flow_eval_expression(
                    item,
                    scope,
                    state,
                    apply_effects=apply_effects,
                    active_functions=active_functions,
                )
                values.append(value)
            return (
                ResolvedValue(
                    sequence_kind="set",
                    aggregate_origins=frozenset(
                        origin for value in values for origin in value.aggregate_origins
                    ),
                    is_unknown=any(value.is_unknown for value in values),
                    sensitive_unknown=any(value.sensitive_unknown for value in values),
                ),
                state,
            )
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp)):
            return self._flow_eval_eager_comprehension(
                node,
                scope,
                state,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
        if isinstance(node, ast.GeneratorExp):
            if node.generators:
                _outer_iterable, state = self._flow_eval_expression(
                    node.generators[0].iter,
                    scope,
                    state,
                    apply_effects=apply_effects,
                    active_functions=active_functions,
                )
            execution_scope = (
                self.node_scopes.get(id(node.generators[0]), scope) if node.generators else scope
            )
            deferred_roots = (
                node.elt,
                *(generator.iter for generator in node.generators[1:]),
                *(condition for generator in node.generators for condition in generator.ifs),
            )
            callback_effect = self._flow_expression_callback_effect(
                deferred_roots,
                execution_scope,
                state,
            )
            captured_values = tuple(
                self._flow_lookup(scope, state, loaded)
                for loaded in ast.walk(node)
                if isinstance(loaded, ast.Name) and isinstance(loaded.ctx, ast.Load)
            )
            origins = frozenset(
                origin
                for value in captured_values
                for origin in value.aggregate_origins | value.direct_origins
            )
            origins = origins | callback_effect.deferred_origins
            return ResolvedValue(
                sequence_kind="generator",
                aggregate_origins=origins,
                is_unknown=True,
                sensitive_unknown=bool(origins or callback_effect.sensitive_unknown),
                deferred_locations=self._flow_reachable_locations(
                    captured_values,
                    state.store,
                )
                | callback_effect.deferred_locations,
                deferred_origins=origins,
                reachability_overflow=bool(
                    callback_effect.reachability_overflow
                    or any(value.reachability_overflow for value in captured_values)
                ),
            ), state
        if isinstance(node, ast.Subscript):
            container, state = self._flow_eval_expression(
                node.value,
                scope,
                state,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
            state = self._flow_eval_subscript_selector(
                node.slice,
                scope,
                state,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
            materialized = self._materialize_flow_value(container, state.store)
            selected = self._flow_subscript_value(materialized, node.slice)
            summarized = self._flow_stored_unknown_sequence_value(
                container,
                node.slice,
                state.store,
            )
            if summarized is not None:
                selected = (
                    summarized
                    if (
                        container.locations
                        and not container.direct_origins
                        and not container.location_uncertain
                    )
                    else _merge_values((selected, summarized))
                )
            if isinstance(node.slice, ast.Slice) and materialized.sequence_kind == "list":
                unknown = ResolvedValue()
                if selected.sequence_elements is None:
                    unknown = _unknown_value(
                        selected.aggregate_origins | selected.direct_origins,
                        sensitive=True,
                    )._replace(
                        locations=self._flow_reachable_locations(
                            (materialized,),
                            state.store,
                        ),
                        location_uncertain=True,
                    )
                return self._flow_allocate_sequence(
                    node,
                    scope,
                    state,
                    selected.sequence_elements,
                    unknown,
                )
            return selected, state
        if isinstance(node, ast.IfExp):
            _test, tested = self._flow_eval_expression(
                node.test,
                scope,
                state,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
            body, body_state = self._flow_eval_expression(
                node.body,
                scope,
                tested,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
            otherwise, otherwise_state = self._flow_eval_expression(
                node.orelse,
                scope,
                tested,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
            return _merge_values((body, otherwise)), self._flow_join((body_state, otherwise_state))
        if isinstance(node, ast.BoolOp):
            bool_values: list[ResolvedValue] = []
            paths = [state]
            current = state
            for item in node.values:
                value, current = self._flow_eval_expression(
                    item,
                    scope,
                    current,
                    apply_effects=apply_effects,
                    active_functions=active_functions,
                )
                bool_values.append(value)
                paths.append(current)
            return _merge_values(tuple(bool_values)), self._flow_join(tuple(paths))
        if isinstance(node, ast.NamedExpr):
            value, state = self._flow_eval_expression(
                node.value,
                scope,
                state,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
            return value, self._flow_write_target(
                node.target,
                value,
                scope,
                state,
                active_functions=active_functions,
            )
        if isinstance(node, ast.Await):
            value, state = self._flow_eval_expression(
                node.value,
                scope,
                state,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
            if value.is_unknown and not value.sensitive_unknown:
                value = value._replace(sensitive_unknown=True)
            return value, state
        if isinstance(node, ast.UnaryOp):
            operand, state = self._flow_eval_expression(
                node.operand,
                scope,
                state,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
            return (
                _unknown_value(
                    operand.aggregate_origins | operand.direct_origins,
                    sensitive=True,
                ),
                state,
            )
        if isinstance(node, ast.BinOp):
            left, state = self._flow_eval_expression(
                node.left,
                scope,
                state,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
            right, state = self._flow_eval_expression(
                node.right,
                scope,
                state,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
            left = self._materialize_flow_value(left, state.store)
            right = self._materialize_flow_value(right, state.store)
            if (
                isinstance(node.op, ast.BitOr)
                and (
                    left.mapping_entries is not None
                    or self._flow_value_is_modeled_dictionary(left, state.store)
                )
                and (
                    right.mapping_entries is not None
                    or self._flow_value_is_modeled_dictionary(right, state.store)
                )
            ):
                union_container = _apply_ordered_mapping_writes(
                    _AbstractContainerState("dict", mapping_entries=()),
                    (
                        self._flow_ordered_mapping_write(left, state.store),
                        self._flow_ordered_mapping_write(right, state.store),
                    ),
                )
                return self._flow_allocate_mapping(
                    node,
                    scope,
                    state,
                    union_container,
                )
            if isinstance(node.op, ast.Add) and left.sequence_kind == right.sequence_kind:
                if left.sequence_kind == "list":
                    combined_elements = (
                        (*left.sequence_elements, *right.sequence_elements)
                        if left.sequence_elements is not None
                        and right.sequence_elements is not None
                        else None
                    )
                    possible = (
                        left.aggregate_origins
                        | left.direct_origins
                        | right.aggregate_origins
                        | right.direct_origins
                    )
                    unknown = ResolvedValue()
                    if combined_elements is None:
                        unknown = _unknown_value(possible, sensitive=True)._replace(
                            locations=self._flow_reachable_locations(
                                (left, right),
                                state.store,
                            ),
                            location_uncertain=True,
                        )
                    return self._flow_allocate_sequence(
                        node,
                        scope,
                        state,
                        combined_elements,
                        unknown,
                    )
                if left.sequence_elements is not None and right.sequence_elements is not None:
                    return _sequence_value(
                        left.sequence_kind or "sequence",
                        (*left.sequence_elements, *right.sequence_elements),
                    ), state
            repeated: ResolvedValue | None = None
            count_known = False
            count: int | None = None
            if isinstance(node.op, ast.Mult) and left.sequence_kind == "list":
                repeated = left
                count_known, count = self._static_integer(node.right)
            elif isinstance(node.op, ast.Mult) and right.sequence_kind == "list":
                repeated = right
                count_known, count = self._static_integer(node.left)
            if repeated is not None:
                repeat_count = max(count or 0, 0)
                repeated_elements: tuple[ResolvedValue, ...] | None = None
                if (
                    count_known
                    and count is not None
                    and repeated.sequence_elements is not None
                    and (
                        not repeated.sequence_elements
                        or repeat_count
                        <= _MAX_ABSTRACT_CONTAINER_WIDTH // len(repeated.sequence_elements)
                    )
                ):
                    repeated_elements = repeated.sequence_elements * repeat_count
                possible = repeated.aggregate_origins | repeated.direct_origins
                unknown = ResolvedValue()
                if repeated_elements is None:
                    unknown = _unknown_value(possible, sensitive=True)._replace(
                        locations=self._flow_reachable_locations(
                            (repeated,),
                            state.store,
                        ),
                        location_uncertain=True,
                    )
                return self._flow_allocate_sequence(
                    node,
                    scope,
                    state,
                    repeated_elements,
                    unknown,
                )
            return _unknown_value(
                left.aggregate_origins | right.aggregate_origins,
                sensitive=True,
            ), state
        if isinstance(node, ast.Compare):
            compared_values: list[ResolvedValue] = []
            left, state = self._flow_eval_expression(
                node.left,
                scope,
                state,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
            compared_values.append(left)
            exits: list[_FlowState] = []
            for index, comparator in enumerate(node.comparators):
                if index:
                    exits.append(state)
                value, state = self._flow_eval_expression(
                    comparator,
                    scope,
                    state,
                    apply_effects=apply_effects,
                    active_functions=active_functions,
                )
                compared_values.append(value)
            exits.append(state)
            possible = frozenset(
                origin
                for value in compared_values
                for origin in value.aggregate_origins | value.direct_origins
            )
            return _unknown_value(possible, sensitive=bool(possible)), self._flow_join(tuple(exits))
        if isinstance(node, ast.Call):
            return self._flow_eval_call(
                node,
                scope,
                state,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
        if isinstance(node, (ast.JoinedStr, ast.FormattedValue)):
            formatted_origins: set[str] = set()
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.expr):
                    value, state = self._flow_eval_expression(
                        child,
                        scope,
                        state,
                        apply_effects=apply_effects,
                        active_functions=active_functions,
                    )
                    formatted_origins.update(value.aggregate_origins | value.direct_origins)
            return _unknown_value(
                frozenset(formatted_origins),
                sensitive=bool(formatted_origins),
            ), state
        previous = self._resolving_flow_snapshot
        self._resolving_flow_snapshot = True
        try:
            return self._resolve_expression(node, scope, active_functions), state
        finally:
            self._resolving_flow_snapshot = previous

    def _flow_eval_eager_comprehension(
        self,
        node: ast.ListComp | ast.SetComp | ast.DictComp,
        scope: _Scope,
        state: _FlowState,
        *,
        apply_effects: bool,
        active_functions: frozenset[str],
    ) -> tuple[ResolvedValue, _FlowState]:
        original_bindings = dict(state.bindings)
        if isinstance(node, ast.ListComp):
            result, state = self._flow_allocate_sequence(node, scope, state, ())
        elif isinstance(node, ast.DictComp):
            result, state = self._flow_allocate_mapping(
                node,
                scope,
                state,
                _AbstractContainerState("dict", mapping_entries=()),
            )
        else:
            result = ResolvedValue(sequence_kind="set")
        exits: list[_FlowState] = []
        current = state
        comprehension_scope = (
            self.node_scopes.get(id(node.generators[0]), scope) if node.generators else scope
        )
        target_names: set[str] = set()
        for generator in node.generators:
            iterable, current = self._flow_eval_expression(
                generator.iter,
                comprehension_scope,
                current,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
            exits.append(current)
            target_names.update(self._target_names(generator.target))
            current = self._flow_write_target(
                generator.target,
                self._flow_iteration_value(iterable, current),
                comprehension_scope,
                current,
                active_functions=active_functions,
            )
            for condition in generator.ifs:
                _condition, current = self._flow_eval_expression(
                    condition,
                    comprehension_scope,
                    current,
                    apply_effects=apply_effects,
                    active_functions=active_functions,
                )
                exits.append(current)

        if isinstance(node, ast.DictComp):
            _key, current = self._flow_eval_expression(
                node.key,
                comprehension_scope,
                current,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
            entry_value, current = self._flow_eval_expression(
                node.value,
                comprehension_scope,
                current,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
            current = self._flow_write_locations(
                self._materialize_flow_value(result, current.store),
                node.key,
                entry_value,
                current,
            )
            result_value = entry_value
        else:
            result_value, current = self._flow_eval_expression(
                node.elt,
                comprehension_scope,
                current,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
            if isinstance(node, ast.ListComp):
                current = self._flow_append_locations(
                    self._materialize_flow_value(result, current.store),
                    (result_value,),
                    current,
                )
        exits.append(current)
        joined = self._flow_join(tuple(exits))
        bindings = dict(joined.bindings)
        for name in target_names:
            if name in original_bindings:
                bindings[name] = original_bindings[name]
            else:
                bindings.pop(name, None)
        joined = joined._replace(bindings=tuple(sorted(bindings.items())))
        if apply_effects:
            repeated_roots = (
                *((node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,)),
                *(generator.iter for generator in node.generators[1:]),
                *(condition for generator in node.generators for condition in generator.ifs),
            )
            callback_effect = self._flow_expression_callback_effect(
                repeated_roots,
                comprehension_scope,
                joined,
            )
            joined = self._flow_consume_deferred(callback_effect, joined)
        if isinstance(node, ast.SetComp):
            return ResolvedValue(
                sequence_kind="set",
                aggregate_origins=result_value.aggregate_origins,
                is_unknown=True,
                sensitive_unknown=result_value.sensitive_unknown,
            ), joined
        return self._materialize_flow_value(result, joined.store), joined

    def _flow_eval_call(
        self,
        node: ast.Call,
        scope: _Scope,
        state: _FlowState,
        *,
        apply_effects: bool,
        active_functions: frozenset[str],
    ) -> tuple[ResolvedValue, _FlowState]:
        receiver_before_arguments: ResolvedValue | None = None
        if isinstance(node.func, ast.Attribute):
            self._record_flow_state(node.func, state)
            receiver_before_arguments, state = self._flow_eval_expression(
                node.func.value,
                scope,
                state,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
            target = self._flow_attribute_value(
                receiver_before_arguments,
                node.func.attr,
                state,
            )
        else:
            target, state = self._flow_eval_expression(
                node.func,
                scope,
                state,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
        positional: list[ResolvedValue] = []
        for argument in node.args:
            value, state = self._flow_eval_expression(
                argument.value if isinstance(argument, ast.Starred) else argument,
                scope,
                state,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
            if isinstance(argument, ast.Starred):
                value = self._materialize_flow_value(value, state.store)
                if value.sequence_elements is not None:
                    positional.extend(value.sequence_elements)
                else:
                    positional.append(_unknown_value(value.aggregate_origins, sensitive=True))
            else:
                positional.append(value)
        keywords: list[tuple[str | None, ResolvedValue]] = []
        for keyword in node.keywords:
            value, state = self._flow_eval_expression(
                keyword.value,
                scope,
                state,
                apply_effects=apply_effects,
                active_functions=active_functions,
            )
            keywords.append((keyword.arg, value))

        eager_consumers = frozenset(
            {
                "builtins.all",
                "builtins.any",
                "builtins.dict",
                "builtins.frozenset",
                "builtins.list",
                "builtins.max",
                "builtins.min",
                "builtins.next",
                "builtins.set",
                "builtins.sorted",
                "builtins.sum",
                "builtins.tuple",
            }
        )
        if not target.direct_origins.isdisjoint(eager_consumers):
            for value in positional:
                state = self._flow_consume_deferred(value, state)
        if not target.direct_origins.isdisjoint(_CALLBACK_KEYWORD_BUILTIN_TARGETS):
            key_callback = next(
                (value for name, value in keywords if name == "key"),
                None,
            )
            if key_callback is not None:
                key_node = next(
                    (keyword.value for keyword in node.keywords if keyword.arg == "key"),
                    None,
                )
                callback_arguments = (
                    tuple(self._flow_iteration_value(value, state) for value in positional)
                    if len(positional) == 1
                    else tuple(positional)
                )
                callback_effect = self._flow_callback_effect(
                    key_callback,
                    callback_arguments,
                    scope,
                    state,
                    callback_node=key_node,
                )
                state = self._flow_consume_deferred(callback_effect, state)
        if (
            receiver_before_arguments is not None
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "__next__"
        ):
            state = self._flow_consume_deferred(receiver_before_arguments, state)

        if target.direct_origins == {"typing.cast"} and len(positional) == 2 and not keywords:
            return positional[1], state
        constructor = next(iter(target.direct_origins)) if len(target.direct_origins) == 1 else None
        if constructor in {
            "builtins.enumerate",
            "builtins.filter",
            "builtins.iter",
            "builtins.map",
            "builtins.reversed",
            "builtins.zip",
        }:
            callback_effect = ResolvedValue()
            callback_node: ast.AST | None = None
            generator_callback_arguments: tuple[ResolvedValue, ...] = ()
            callback: ResolvedValue | None = None
            if constructor == "builtins.map" and positional:
                callback = positional[0]
                generator_callback_arguments = tuple(
                    self._flow_iteration_value(value, state) for value in positional[1:]
                )
                if node.args and not isinstance(node.args[0], ast.Starred):
                    callback_node = node.args[0]
            elif constructor == "builtins.filter" and positional:
                callback = positional[0]
                generator_callback_arguments = tuple(
                    self._flow_iteration_value(value, state) for value in positional[1:2]
                )
                if node.args and not isinstance(node.args[0], ast.Starred):
                    callback_node = node.args[0]
            elif constructor == "builtins.iter" and len(positional) == 2:
                callback = positional[0]
                if node.args and not isinstance(node.args[0], ast.Starred):
                    callback_node = node.args[0]
            if callback is not None:
                callback_effect = self._flow_callback_effect(
                    callback,
                    generator_callback_arguments,
                    scope,
                    state,
                    callback_node=callback_node,
                )
            return ResolvedValue(
                sequence_kind="lazy-adapter",
                aggregate_origins=frozenset(
                    origin
                    for value in positional
                    for origin in value.aggregate_origins | value.direct_origins
                )
                | callback_effect.deferred_origins,
                is_unknown=True,
                sensitive_unknown=bool(
                    callback_effect.deferred_origins
                    or callback_effect.deferred_locations
                    or callback_effect.reachability_overflow
                    or any(value.sensitive_unknown for value in positional)
                ),
                deferred_locations=frozenset(
                    location for value in positional for location in value.deferred_locations
                )
                | callback_effect.deferred_locations,
                deferred_origins=frozenset(
                    origin for value in positional for origin in value.deferred_origins
                )
                | callback_effect.deferred_origins,
                reachability_overflow=bool(
                    callback_effect.reachability_overflow
                    or any(value.reachability_overflow for value in positional)
                ),
            ), state
        if (
            constructor in {"builtins.list", "builtins.tuple"}
            and len(positional) <= 1
            and not keywords
        ):
            source = (
                ResolvedValue()
                if not positional
                else self._materialize_flow_value(positional[0], state.store)
            )
            state = self._flow_consume_deferred(source, state)
            source = self._materialize_flow_value(source, state.store)
            elements = () if not positional else source.sequence_elements
            if constructor == "builtins.list":
                return self._flow_allocate_sequence(
                    node,
                    scope,
                    state,
                    elements,
                    _unknown_value(
                        source.aggregate_origins | source.direct_origins,
                        sensitive=source.sensitive_unknown,
                    )
                    if elements is None
                    else ResolvedValue(),
                )
            if elements is not None:
                return _sequence_value("tuple", elements), state
            return ResolvedValue(
                sequence_kind="tuple",
                aggregate_origins=source.aggregate_origins,
                is_unknown=True,
                sensitive_unknown=source.sensitive_unknown,
            ), state
        if constructor == "builtins.dict" and len(positional) <= 1:
            writes: list[_OrderedMappingWrite] = []
            if positional:
                source = self._materialize_flow_value(positional[0], state.store)
                if source.mapping_entries is not None or self._flow_value_is_modeled_dictionary(
                    source, state.store
                ):
                    writes.append(self._flow_ordered_mapping_write(source, state.store))
                else:
                    writes.extend(_resolved_pair_iterable_mapping_writes(source))
            dynamic_keywords: list[ResolvedValue] = []
            for name, value in keywords:
                if name is None:
                    dynamic_keywords.append(
                        _unknown_mapping_value(self._materialize_flow_value(value, state.store))
                    )
                else:
                    key = self._literal_static_key(name)
                    if key is not None:
                        writes.append(_OrderedMappingWrite(((key, value),)))
            if dynamic_keywords:
                writes.append(
                    _OrderedMappingWrite(
                        unknown_value=_unknown_mapping_value(_merge_values(tuple(dynamic_keywords)))
                    )
                )
            container = _apply_ordered_mapping_writes(
                _AbstractContainerState("dict", mapping_entries=()),
                tuple(writes),
            )
            return self._flow_allocate_mapping(
                node,
                scope,
                state,
                container,
            )

        return_value = _unknown_value(
            frozenset(
                origin
                for value in (*positional, *(value for _name, value in keywords))
                for origin in value.aggregate_origins | value.direct_origins
            ),
            sensitive=True,
        )
        if not apply_effects:
            simple_returns = tuple(
                resolved
                for origin in sorted(target.direct_origins)
                if (
                    resolved := self._simple_local_return(
                        origin,
                        active_functions,
                        node.lineno,
                        scope,
                    )
                )
                is not None
            )
            if simple_returns and len(simple_returns) == len(target.direct_origins):
                return_value = _merge_values(simple_returns)
            return return_value, state

        incoming = state
        outcome_states: list[_FlowState] = []
        modeled_returns: list[ResolvedValue] = []
        handled_origins: set[str] = set()
        if receiver_before_arguments is not None:
            receiver = self._materialize_flow_value(
                receiver_before_arguments,
                incoming.store,
            )
            mutator_return, mutator_state = self._flow_apply_mutator(
                node,
                receiver,
                tuple(positional),
                tuple(keywords),
                return_value,
                incoming,
            )
            modeled_returns.append(mutator_return)
            outcome_states.append(mutator_state)
            if target.direct_origins:
                outcome_states.append(incoming)
        if receiver_before_arguments is None and target.bound_mutators:
            receivers: list[ResolvedValue] = []
            for mutator in sorted(
                target.bound_mutators,
                key=lambda candidate: (
                    candidate.method,
                    tuple(sorted(candidate.locations)),
                    candidate.location_uncertain,
                ),
            ):
                receiver = self._materialize_flow_value(
                    ResolvedValue(
                        locations=mutator.locations,
                        location_uncertain=(
                            mutator.location_uncertain or target.bound_mutator_uncertain
                        ),
                    ),
                    incoming.store,
                )
                receivers.append(receiver)
                mutator_return, mutator_state = self._flow_apply_mutator(
                    node,
                    receiver,
                    tuple(positional),
                    tuple(keywords),
                    return_value,
                    incoming,
                    method_override=mutator.method,
                )
                modeled_returns.append(mutator_return)
                outcome_states.append(mutator_state)
            if target.bound_mutator_uncertain:
                outcome_states.append(
                    self._flow_invalidate_mutator_receivers(
                        tuple(receivers),
                        (*positional, *(value for _name, value in keywords)),
                        incoming,
                    )
                )
                outcome_states.append(incoming)

        for origin in sorted(target.direct_origins):
            owner, _separator, method = origin.rpartition(".")
            if owner in {"builtins.dict", "builtins.list"} and positional:
                receiver = self._materialize_flow_value(positional[0], incoming.store)
                unbound_return, unbound_state = self._flow_apply_mutator(
                    node,
                    receiver,
                    tuple(positional[1:]),
                    tuple(keywords),
                    return_value,
                    incoming,
                    method_override=method,
                    argument_offset=1,
                )
                modeled_returns.append(unbound_return)
                outcome_states.append(unbound_state)
                handled_origins.add(origin)
                continue
            definitions = self.local_functions.get(origin, ())
            for function, child in definitions:
                helper_return, helper_state = self._flow_apply_local_helper(
                    node,
                    origin,
                    function,
                    child,
                    scope,
                    incoming,
                    tuple(positional),
                    tuple(keywords),
                    active_functions,
                )
                modeled_returns.append(helper_return)
                outcome_states.append(helper_state)
                handled_origins.add(origin)
            if not definitions:
                proven_pure = bool(
                    origin.startswith("typing.")
                    or (
                        origin.startswith("builtins.")
                        and not _qualified_call_target_is_forbidden(origin)
                    )
                )
                actual_values = (*positional, *(value for _name, value in keywords))
                if not proven_pure and self._flow_reachable_locations(
                    actual_values, incoming.store
                ):
                    outcome_states.append(self._flow_invalidate_values(actual_values, incoming))
                outcome_states.append(incoming)

        unresolved = bool(target.is_unknown or target.sensitive_unknown)
        if unresolved:
            actual_values = (*positional, *(value for _name, value in keywords))
            if self._flow_reachable_locations(actual_values, incoming.store):
                outcome_states.append(self._flow_invalidate_values(actual_values, incoming))
            outcome_states.append(incoming)
        if not outcome_states:
            outcome_states.append(incoming)
        state = self._flow_join(tuple(outcome_states))
        all_direct_origins_handled = handled_origins == set(target.direct_origins)
        if modeled_returns and all_direct_origins_handled and not unresolved:
            return_value = _merge_values(tuple(modeled_returns))
        elif modeled_returns:
            return_value = _merge_values((return_value, *modeled_returns))
        return return_value, state

    def _flow_invalidate_mutator_receivers(
        self,
        receivers: tuple[ResolvedValue, ...],
        arguments: tuple[ResolvedValue, ...],
        state: _FlowState,
    ) -> _FlowState:
        possible = _merge_values(arguments)
        locations = frozenset(location for receiver in receivers for location in receiver.locations)
        store = state.store
        for location in sorted(locations):
            container = self._flow_store_get(store, location)
            if container is None:
                continue
            store = self._flow_store_set(
                store,
                location,
                self._flow_unknown_write(container, possible),
            )
        return state._replace(store=store)

    def _flow_mark_locations_uncertain(
        self,
        receiver: ResolvedValue,
        state: _FlowState,
    ) -> _FlowState:
        store = state.store
        for location in sorted(receiver.locations):
            container = self._flow_store_get(store, location)
            if container is None:
                continue
            possible = self._container_possible_origins(container)
            container = container._replace(
                unknown_value=_merge_values(
                    (
                        container.unknown_value,
                        _unknown_value(possible, sensitive=bool(possible)),
                    )
                ),
                uncertain=True,
                masked_sequence_indexes=frozenset(),
                masked_mapping_keys=frozenset(),
            )
            store = self._flow_store_set(store, location, container)
        return state._replace(store=store)

    def _flow_apply_mutator(
        self,
        node: ast.Call,
        receiver: ResolvedValue,
        positional: tuple[ResolvedValue, ...],
        keywords: tuple[tuple[str | None, ResolvedValue], ...],
        fallback: ResolvedValue,
        state: _FlowState,
        *,
        method_override: str | None = None,
        argument_offset: int = 0,
    ) -> tuple[ResolvedValue, _FlowState]:
        if method_override is None and not isinstance(node.func, ast.Attribute):
            return fallback, state
        if not receiver.locations:
            return fallback, state
        containers = tuple(
            container
            for location in sorted(receiver.locations)
            if (container := self._flow_store_get(state.store, location)) is not None
        )
        if not containers:
            return fallback, state
        kinds = {container.kind for container in containers}
        if len(kinds) != 1 or next(iter(kinds)) not in {"list", "dict"}:
            return fallback, state
        self.flow_mutated_locations.update(receiver.locations)
        kind = next(iter(kinds))
        argument_nodes = tuple(node.args[argument_offset:])
        method = (
            method_override
            if method_override is not None
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else ""
        )
        none_value = ResolvedValue(static_key=self._literal_static_key(None))

        if method == "clear" and not positional and not keywords:
            return none_value, self._flow_clear_locations(receiver, state)
        if method == "__ior__" and len(positional) == 1 and not keywords:
            right = self._materialize_flow_value(positional[0], state.store)
            if kind == "dict":
                return self._flow_inplace_mapping_union(receiver, right, state)
            return fallback, self._flow_invalidate_mutator_receivers(
                (receiver,),
                (right,),
                state,
            )
        if kind == "list":
            if method == "append" and len(positional) == 1 and not keywords:
                return none_value, self._flow_append_locations(
                    receiver,
                    (positional[0],),
                    state,
                )
            if method in {"extend", "__iadd__"} and len(positional) == 1 and not keywords:
                source = self._materialize_flow_value(positional[0], state.store)
                return none_value, self._flow_append_locations(
                    receiver,
                    source.sequence_elements,
                    state,
                )
            if method == "insert" and len(positional) == 2 and not keywords:
                known, index = self._static_integer(argument_nodes[0])
                if not known:
                    return none_value, self._flow_write_locations(
                        receiver,
                        argument_nodes[0],
                        positional[1],
                        state,
                    )
                return none_value, self._flow_append_locations(
                    receiver,
                    (positional[1],),
                    state,
                    index=index if known else None,
                )
            if method == "__setitem__" and len(positional) == 2 and not keywords:
                return none_value, self._flow_write_locations(
                    receiver,
                    argument_nodes[0],
                    positional[1],
                    state,
                )
            if method in {"pop", "__delitem__"} and len(positional) <= 1 and not keywords:
                selector: ast.expr = (
                    argument_nodes[0]
                    if argument_nodes
                    else ast.copy_location(ast.Constant(value=-1), node)
                )
                removed = self._flow_subscript_value(receiver, selector)
                return removed, self._flow_write_locations(
                    receiver,
                    selector,
                    ResolvedValue(),
                    state,
                    deleting=True,
                )
            if method == "remove" and len(positional) == 1 and not keywords:
                return none_value, self._flow_mark_locations_uncertain(receiver, state)
            if method == "sort":
                key_callback = next(
                    (value for name, value in keywords if name == "key"),
                    None,
                )
                if key_callback is not None:
                    key_node = next(
                        (keyword.value for keyword in node.keywords if keyword.arg == "key"),
                        None,
                    )
                    callback_scope = self.node_scopes.get(id(node), self.module_scope)
                    callback_effect = self._flow_callback_effect(
                        key_callback,
                        (self._flow_iteration_value(receiver, state),),
                        callback_scope,
                        state,
                        callback_node=key_node,
                    )
                    state = self._flow_consume_deferred(callback_effect, state)
                return none_value, self._flow_mark_locations_uncertain(receiver, state)
            if method == "reverse":
                return none_value, self._flow_mark_locations_uncertain(receiver, state)
            return fallback, state

        if method == "update":
            writes: list[_OrderedMappingWrite] = []
            if positional:
                source = self._materialize_flow_value(positional[0], state.store)
                if source.mapping_entries is not None or self._flow_value_is_modeled_dictionary(
                    source, state.store
                ):
                    writes.append(self._flow_ordered_mapping_write(source, state.store))
                else:
                    writes.extend(_resolved_pair_iterable_mapping_writes(source))
            dynamic_keywords: list[ResolvedValue] = []
            for name, value in keywords:
                if name is None:
                    dynamic_keywords.append(
                        _unknown_mapping_value(self._materialize_flow_value(value, state.store))
                    )
                else:
                    key = self._literal_static_key(name)
                    if key is not None:
                        writes.append(_OrderedMappingWrite(((key, value),)))
            if dynamic_keywords:
                writes.append(
                    _OrderedMappingWrite(
                        unknown_value=_unknown_mapping_value(_merge_values(tuple(dynamic_keywords)))
                    )
                )
            return none_value, self._flow_update_mapping(
                receiver,
                tuple(writes),
                state,
            )
        if method in {"__setitem__", "setdefault"} and len(positional) >= 1:
            value = positional[1] if len(positional) >= 2 else none_value
            if method == "setdefault":
                existing = self._flow_subscript_value(receiver, argument_nodes[0])
                key = self._static_key(argument_nodes[0])
                all_receivers_modeled = bool(
                    containers
                    and len(containers) == len(receiver.locations)
                    and not receiver.direct_origins
                    and not receiver.is_unknown
                    and not receiver.sensitive_unknown
                    and not receiver.deferred_origins
                    and not receiver.reachability_overflow
                )

                def summary_is_empty(container: _AbstractContainerState) -> bool:
                    return not (
                        container.unknown_value.direct_origins
                        or container.unknown_value.aggregate_origins
                        or container.unknown_value.is_unknown
                        or container.unknown_value.sensitive_unknown
                    )

                definite_existing = bool(
                    all_receivers_modeled
                    and key is not None
                    and all(
                        container.mapping_entries is not None
                        and key in dict(container.mapping_entries)
                        and (
                            key in container.masked_mapping_keys
                            or (not container.uncertain and summary_is_empty(container))
                        )
                        for container in containers
                    )
                )
                if definite_existing:
                    return existing, state
                definite_absence = bool(
                    all_receivers_modeled
                    and key is not None
                    and all(
                        container.mapping_entries is not None
                        and key not in dict(container.mapping_entries)
                        and not container.uncertain
                        and summary_is_empty(container)
                        for container in containers
                    )
                )
                if not definite_absence:
                    receiver = receiver._replace(location_uncertain=True)
                    value = _merge_values((existing, value))
            return value if method == "setdefault" else none_value, self._flow_write_locations(
                receiver,
                argument_nodes[0],
                value,
                state,
            )
        if method in {"pop", "__delitem__"} and positional:
            removed = self._flow_subscript_value(receiver, argument_nodes[0])
            return removed, self._flow_write_locations(
                receiver,
                argument_nodes[0],
                ResolvedValue(),
                state,
                deleting=True,
            )
        if method == "popitem" and not positional and not keywords:
            return fallback, self._flow_mark_locations_uncertain(receiver, state)
        return fallback, state

    def _flow_write_target(
        self,
        target: ast.expr,
        value: ResolvedValue,
        scope: _Scope,
        state: _FlowState,
        *,
        active_functions: frozenset[str] = frozenset(),
    ) -> _FlowState:
        self._record_flow_state(target, state)
        if isinstance(target, ast.Name):
            return self._flow_bind(state, target.id, value)
        if isinstance(target, ast.Starred):
            return self._flow_write_target(
                target.value,
                value,
                scope,
                state,
                active_functions=active_functions,
            )
        if isinstance(target, (ast.Tuple, ast.List)):
            materialized = self._materialize_flow_value(value, state.store)
            elements = materialized.sequence_elements
            starred = next(
                (index for index, item in enumerate(target.elts) if isinstance(item, ast.Starred)),
                None,
            )
            for index, item in enumerate(target.elts):
                if index == starred:
                    trailing = len(target.elts) - index - 1
                    upper = -trailing if trailing else None
                    star_elements = None if elements is None else elements[index:upper]
                    unknown = ResolvedValue()
                    if star_elements is None:
                        unknown = _unknown_value(
                            materialized.aggregate_origins | materialized.direct_origins,
                            sensitive=True,
                        )._replace(
                            locations=self._flow_reachable_locations(
                                (materialized,),
                                state.store,
                            ),
                            location_uncertain=True,
                        )
                    item_value, state = self._flow_allocate_sequence(
                        item,
                        scope,
                        state,
                        star_elements,
                        unknown,
                    )
                elif elements is None:
                    item_value = _unknown_value(
                        materialized.aggregate_origins,
                        sensitive=True,
                    )._replace(
                        locations=self._flow_reachable_locations(
                            (materialized,),
                            state.store,
                        ),
                        location_uncertain=True,
                    )
                else:
                    selected_index = (
                        index - len(target.elts)
                        if starred is not None and index > starred
                        else index
                    )
                    try:
                        item_value = elements[selected_index]
                    except IndexError:
                        item_value = _unknown_value(
                            materialized.aggregate_origins,
                            sensitive=True,
                        )
                state = self._flow_write_target(
                    item,
                    item_value,
                    scope,
                    state,
                    active_functions=active_functions,
                )
            return state
        if isinstance(target, ast.Subscript):
            receiver, state = self._flow_eval_expression(
                target.value,
                scope,
                state,
                apply_effects=True,
                active_functions=active_functions,
            )
            state = self._flow_eval_subscript_selector(
                target.slice,
                scope,
                state,
                apply_effects=True,
                active_functions=active_functions,
            )
            receiver = self._materialize_flow_value(receiver, state.store)
            return self._flow_write_locations(receiver, target.slice, value, state)
        return state

    def _flow_delete_target(
        self,
        target: ast.expr,
        scope: _Scope,
        state: _FlowState,
        *,
        active_functions: frozenset[str] = frozenset(),
    ) -> _FlowState:
        self._record_flow_state(target, state)
        if isinstance(target, ast.Name):
            return self._flow_unbind(state, target.id)
        if isinstance(target, ast.Starred):
            return self._flow_delete_target(
                target.value,
                scope,
                state,
                active_functions=active_functions,
            )
        if isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                state = self._flow_delete_target(
                    item,
                    scope,
                    state,
                    active_functions=active_functions,
                )
            return state
        if isinstance(target, ast.Subscript):
            receiver, state = self._flow_eval_expression(
                target.value,
                scope,
                state,
                apply_effects=True,
                active_functions=active_functions,
            )
            state = self._flow_eval_subscript_selector(
                target.slice,
                scope,
                state,
                apply_effects=True,
                active_functions=active_functions,
            )
            receiver = self._materialize_flow_value(receiver, state.store)
            return self._flow_write_locations(
                receiver,
                target.slice,
                ResolvedValue(),
                state,
                deleting=True,
            )
        return state

    def _flow_augmented_value(
        self,
        operation: ast.operator,
        left: ResolvedValue,
        right: ResolvedValue,
        state: _FlowState,
    ) -> ResolvedValue:
        left = self._materialize_flow_value(left, state.store)
        right = self._materialize_flow_value(right, state.store)
        if (
            isinstance(operation, ast.Add)
            and left.sequence_elements is not None
            and right.sequence_elements is not None
            and left.sequence_kind == right.sequence_kind
        ):
            return _sequence_value(
                left.sequence_kind or "sequence",
                (*left.sequence_elements, *right.sequence_elements),
            )
        possible = (
            left.direct_origins
            | left.aggregate_origins
            | right.direct_origins
            | right.aggregate_origins
        )
        return _unknown_value(
            possible,
            sensitive=bool(
                possible
                or left.sensitive_unknown
                or left.reachability_overflow
                or right.sensitive_unknown
                or right.reachability_overflow
            ),
        )._replace(
            temporally_derived=left.temporally_derived or right.temporally_derived,
        )

    def _flow_iteration_value(
        self,
        value: ResolvedValue,
        state: _FlowState,
    ) -> ResolvedValue:
        value = self._materialize_flow_value(value, state.store)
        if value.sequence_elements is not None:
            result = _mark_unknown_leaves_sensitive(_merge_values(value.sequence_elements))
            return (
                result._replace(temporally_derived=True)
                if value.temporally_derived and not result.temporally_derived
                else result
            )
        if value.mapping_entries is not None:
            result = _merge_values(
                tuple(ResolvedValue(static_key=key) for key, _entry in value.mapping_entries)
            )
            return (
                result._replace(temporally_derived=True)
                if value.temporally_derived and not result.temporally_derived
                else result
            )
        return _unknown_value(value.aggregate_origins, sensitive=True)._replace(
            temporally_derived=value.temporally_derived,
        )

    def _flow_bind_pattern(
        self,
        pattern: ast.pattern,
        value: ResolvedValue,
        scope: _Scope,
        state: _FlowState,
    ) -> _FlowState:
        self._record_flow_state(pattern, state)
        if isinstance(pattern, ast.MatchAs):
            if pattern.pattern is not None:
                state = self._flow_bind_pattern(pattern.pattern, value, scope, state)
            return state if pattern.name is None else self._flow_bind(state, pattern.name, value)
        if isinstance(pattern, ast.MatchStar):
            return state if pattern.name is None else self._flow_bind(state, pattern.name, value)
        if isinstance(pattern, ast.MatchOr):
            states = tuple(
                self._flow_bind_pattern(child, value, scope, state) for child in pattern.patterns
            )
            return self._flow_join(states) if states else state
        if isinstance(pattern, ast.MatchSequence):
            materialized = self._materialize_flow_value(value, state.store)
            elements = materialized.sequence_elements
            starred = next(
                (
                    index
                    for index, child in enumerate(pattern.patterns)
                    if isinstance(child, ast.MatchStar)
                ),
                None,
            )
            for index, child in enumerate(pattern.patterns):
                if index == starred:
                    trailing = len(pattern.patterns) - index - 1
                    upper = -trailing if trailing else None
                    star_elements = None if elements is None else elements[index:upper]
                    unknown = ResolvedValue()
                    if star_elements is None:
                        unknown = _unknown_value(
                            materialized.aggregate_origins | materialized.direct_origins,
                            sensitive=True,
                        )._replace(
                            locations=self._flow_reachable_locations(
                                (materialized,),
                                state.store,
                            ),
                            location_uncertain=True,
                        )
                    selected, state = self._flow_allocate_sequence(
                        child,
                        scope,
                        state,
                        star_elements,
                        unknown,
                    )
                elif elements is None:
                    selected = _unknown_value(
                        materialized.aggregate_origins | materialized.direct_origins,
                        sensitive=True,
                    )._replace(
                        locations=self._flow_reachable_locations(
                            (materialized,),
                            state.store,
                        ),
                        location_uncertain=True,
                    )
                else:
                    selected_index = (
                        index - len(pattern.patterns)
                        if starred is not None and index > starred
                        else index
                    )
                    try:
                        selected = elements[selected_index]
                    except IndexError:
                        selected = _unknown_value(
                            materialized.aggregate_origins,
                            sensitive=True,
                        )
                state = self._flow_bind_pattern(child, selected, scope, state)
            return state
        if isinstance(pattern, ast.MatchMapping):
            materialized = self._materialize_flow_value(value, state.store)
            entries = dict(materialized.mapping_entries or ())
            for key_node, child in zip(pattern.keys, pattern.patterns, strict=True):
                key = self._static_key(key_node)
                selected = (
                    entries[key]
                    if key is not None and key in entries
                    else _unknown_value(
                        materialized.aggregate_origins | materialized.direct_origins,
                        sensitive=True,
                    )._replace(
                        locations=self._flow_reachable_locations(
                            (materialized,),
                            state.store,
                        ),
                        location_uncertain=True,
                    )
                )
                state = self._flow_bind_pattern(child, selected, scope, state)
            if pattern.rest is not None:
                matched_keys = frozenset(
                    key
                    for key_node in pattern.keys
                    if (key := self._static_key(key_node)) is not None
                )
                remaining = (
                    tuple(
                        (key, entry_value)
                        for key, entry_value in materialized.mapping_entries
                        if key not in matched_keys
                    )
                    if materialized.mapping_entries is not None
                    else None
                )
                unknown = ResolvedValue()
                if remaining is None:
                    unknown = _unknown_value(
                        materialized.aggregate_origins | materialized.direct_origins,
                        sensitive=True,
                    )._replace(
                        locations=self._flow_reachable_locations(
                            (materialized,),
                            state.store,
                        ),
                        location_uncertain=True,
                    )
                rest_write = (
                    _OrderedMappingWrite(tuple(remaining))
                    if remaining is not None
                    else _OrderedMappingWrite(unknown_value=unknown)
                )
                rest_container = _apply_ordered_mapping_writes(
                    _AbstractContainerState("dict", mapping_entries=()),
                    (rest_write,),
                )
                rest, state = self._flow_allocate_mapping(
                    pattern,
                    scope,
                    state,
                    rest_container,
                )
                state = self._flow_bind(state, pattern.rest, rest)
            return state
        if isinstance(pattern, ast.MatchClass):
            possible = _unknown_value(
                value.aggregate_origins | value.direct_origins,
                sensitive=True,
            )._replace(
                locations=self._flow_reachable_locations((value,), state.store),
                location_uncertain=True,
            )
            for child in (*pattern.patterns, *pattern.kwd_patterns):
                state = self._flow_bind_pattern(
                    child,
                    possible,
                    scope,
                    state,
                )
        return state

    def _flow_block(
        self,
        statements: tuple[ast.stmt, ...] | list[ast.stmt],
        scope: _Scope,
        state: _FlowState,
        *,
        active_functions: frozenset[str] = frozenset(),
    ) -> _FlowState:
        abrupt_states: list[_FlowState] = []
        for statement in statements:
            state = self._flow_statement(
                statement,
                scope,
                state,
                active_functions=active_functions,
            )
            if self._flow_statement_has_function_abrupt(statement):
                abrupt_states.append(state)
            if isinstance(statement, (ast.Break, ast.Continue, ast.Raise, ast.Return)):
                break
        return self._flow_join((state, *abrupt_states))

    def _flow_statement_has_function_abrupt(self, statement: ast.stmt) -> bool:
        if isinstance(statement, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef)):
            return False
        pending: list[ast.AST] = [statement]
        while pending:
            node = pending.pop()
            if isinstance(node, (ast.Raise, ast.Return)):
                return True
            if node is not statement and isinstance(
                node,
                (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef, ast.Lambda),
            ):
                continue
            pending.extend(ast.iter_child_nodes(node))
        return False

    def _flow_loop(
        self,
        body: tuple[ast.stmt, ...] | list[ast.stmt],
        orelse: tuple[ast.stmt, ...] | list[ast.stmt],
        scope: _Scope,
        entry: _FlowState,
        *,
        target: ast.expr | None = None,
        iterable: ResolvedValue | None = None,
        condition: ast.expr | None = None,
        active_functions: frozenset[str],
    ) -> _FlowState:
        current = entry
        for _pass in range(_MAX_ABSTRACT_FLOW_PASSES):
            abrupt_states: list[_FlowState] = []
            body_entry = current
            condition_state: _FlowState | None = None
            if condition is not None:
                _condition, body_entry = self._flow_eval_expression(
                    condition,
                    scope,
                    body_entry,
                    apply_effects=True,
                    active_functions=active_functions,
                )
                condition_state = body_entry
            if target is not None and iterable is not None:
                body_entry = self._flow_consume_deferred(iterable, body_entry)
                body_entry = self._flow_write_target(
                    target,
                    self._flow_iteration_value(iterable, body_entry),
                    scope,
                    body_entry,
                    active_functions=active_functions,
                )
            body_exit = body_entry
            for statement in body:
                body_exit = self._flow_statement(
                    statement,
                    scope,
                    body_exit,
                    active_functions=active_functions,
                )
                if self._flow_statement_has_loop_abrupt(statement):
                    abrupt_states.append(body_exit)
                if isinstance(statement, (ast.Break, ast.Continue, ast.Raise, ast.Return)):
                    break
            joined = self._flow_join(
                (entry, body_exit, *abrupt_states)
                if condition_state is None
                else (condition_state, body_exit, *abrupt_states)
            )
            if joined == current:
                current = joined
                break
            current = joined
        else:
            widened_store_entries: list[tuple[_AbstractLocation, _AbstractContainerState]] = []
            for location, container in current.store.entries:
                if self._flow_store_get(entry.store, location) == container:
                    widened_store_entries.append((location, container))
                    continue
                possible = self._container_possible_origins(container)
                widened_store_entries.append(
                    (
                        location,
                        _AbstractContainerState(
                            container.kind,
                            unknown_value=_merge_values(
                                (
                                    container.unknown_value,
                                    _unknown_value(
                                        possible,
                                        sensitive=container.unknown_value.sensitive_unknown,
                                    ),
                                )
                            ),
                            uncertain=True,
                            masked_sequence_indexes=container.masked_sequence_indexes,
                            masked_mapping_keys=container.masked_mapping_keys,
                        ),
                    )
                )
            current = self._flow_join(
                (
                    current,
                    _FlowState(
                        tuple(
                            (
                                name,
                                value
                                if _flow_binding_get(entry.bindings, name) == value
                                else _unknown_value(
                                    value.aggregate_origins | value.direct_origins,
                                    sensitive=bool(
                                        value.sensitive_unknown or value.reachability_overflow
                                    ),
                                ),
                            )
                            for name, value in current.bindings
                        ),
                        _AbstractStore(tuple(widened_store_entries)),
                    ),
                )
            )
        orelse_state = self._flow_block(
            orelse,
            scope,
            current,
            active_functions=active_functions,
        )
        if orelse and self._flow_body_has_break(body):
            return self._flow_join((current, orelse_state))
        return orelse_state

    def _flow_body_has_break(
        self,
        statements: tuple[ast.stmt, ...] | list[ast.stmt],
    ) -> bool:
        pending: list[ast.AST] = list(statements)
        while pending:
            node = pending.pop()
            if isinstance(node, ast.Break):
                return True
            if isinstance(
                node,
                (
                    ast.AsyncFor,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                    ast.For,
                    ast.FunctionDef,
                    ast.Lambda,
                    ast.While,
                ),
            ):
                continue
            pending.extend(ast.iter_child_nodes(node))
        return False

    def _flow_statement_has_loop_abrupt(self, statement: ast.stmt) -> bool:
        nested_scopes = (
            ast.AsyncFor,
            ast.AsyncFunctionDef,
            ast.ClassDef,
            ast.For,
            ast.FunctionDef,
            ast.Lambda,
            ast.While,
        )
        if isinstance(statement, nested_scopes):
            return False
        pending: list[ast.AST] = [statement]
        while pending:
            node = pending.pop()
            if isinstance(node, (ast.Break, ast.Continue)):
                return True
            if node is not statement and isinstance(node, nested_scopes):
                continue
            pending.extend(ast.iter_child_nodes(node))
        return False

    def _flow_statement(
        self,
        node: ast.stmt,
        scope: _Scope,
        state: _FlowState,
        *,
        active_functions: frozenset[str],
    ) -> _FlowState:
        self._record_flow_state(node, state)
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                origin = alias.name if alias.asname else local
                state = self._flow_bind(state, local, _direct_value(frozenset({origin})))
            return state
        if isinstance(node, ast.ImportFrom):
            module = self._absolute_import_module(node)
            if module == "__future__":
                return state
            for alias in node.names:
                local = alias.asname or alias.name
                origin = f"{module}.{alias.name}" if module else alias.name
                state = self._flow_bind(state, local, _direct_value(frozenset({origin})))
            return state
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for expression in node.decorator_list:
                _value, state = self._flow_eval_expression(
                    expression,
                    scope,
                    state,
                    apply_effects=True,
                    active_functions=active_functions,
                )
            captured_defaults: dict[str, ResolvedValue] = {}
            positional_parameters = (*node.args.posonlyargs, *node.args.args)
            default_parameters = (
                positional_parameters[-len(node.args.defaults) :] if node.args.defaults else ()
            )
            for parameter, expression in zip(
                default_parameters,
                node.args.defaults,
                strict=True,
            ):
                value, state = self._flow_eval_expression(
                    expression,
                    scope,
                    state,
                    apply_effects=True,
                    active_functions=active_functions,
                )
                captured_defaults[parameter.arg] = value
            for parameter, keyword_default in zip(
                node.args.kwonlyargs,
                node.args.kw_defaults,
                strict=True,
            ):
                if keyword_default is None:
                    continue
                value, state = self._flow_eval_expression(
                    keyword_default,
                    scope,
                    state,
                    apply_effects=True,
                    active_functions=active_functions,
                )
                captured_defaults[parameter.arg] = value
            previous_defaults = self.flow_function_defaults.get(id(node), {})
            self.flow_function_defaults[id(node)] = {
                name: _merge_values(
                    tuple(
                        candidate
                        for candidate in (previous_defaults.get(name), value)
                        if candidate is not None
                    )
                )
                for name, value in captured_defaults.items()
            }
            origin = ".".join((self.module_name, *scope.path, node.name))
            return self._flow_bind(state, node.name, _direct_value(frozenset({origin})))
        if isinstance(node, ast.ClassDef):
            for expression in (*node.decorator_list, *node.bases):
                _value, state = self._flow_eval_expression(
                    expression,
                    scope,
                    state,
                    apply_effects=True,
                    active_functions=active_functions,
                )
            for keyword in node.keywords:
                _value, state = self._flow_eval_expression(
                    keyword.value,
                    scope,
                    state,
                    apply_effects=True,
                    active_functions=active_functions,
                )
            class_scope = next(
                (
                    candidate
                    for scope_id, class_node in self.class_scope_nodes.items()
                    if class_node is node
                    for candidate in self.scopes
                    if id(candidate) == scope_id
                ),
                None,
            )
            if class_scope is not None:
                class_exit = self._flow_block(
                    node.body,
                    class_scope,
                    state,
                    active_functions=active_functions,
                )
                self.flow_final_states[id(class_scope)] = class_exit
                state = _FlowState(state.bindings, class_exit.store)
            origin = ".".join((self.module_name, *scope.path, node.name))
            return self._flow_bind(state, node.name, _direct_value(frozenset({origin})))
        if isinstance(node, ast.Assign):
            value, state = self._flow_eval_expression(
                node.value,
                scope,
                state,
                apply_effects=True,
                active_functions=active_functions,
            )
            for target in node.targets:
                state = self._flow_write_target(
                    target,
                    value,
                    scope,
                    state,
                    active_functions=active_functions,
                )
            return state
        if isinstance(node, ast.AnnAssign):
            if node.value is None:
                value = _unknown_value(sensitive=False)
            else:
                value, state = self._flow_eval_expression(
                    node.value,
                    scope,
                    state,
                    apply_effects=True,
                    active_functions=active_functions,
                )
            return self._flow_write_target(
                node.target,
                value,
                scope,
                state,
                active_functions=active_functions,
            )
        if isinstance(node, ast.AugAssign):
            saved_receiver: ResolvedValue | None = None
            if isinstance(node.target, ast.Subscript):
                self._record_flow_state(node.target, state)
                saved_receiver, state = self._flow_eval_expression(
                    node.target.value,
                    scope,
                    state,
                    apply_effects=True,
                    active_functions=active_functions,
                )
                state = self._flow_eval_subscript_selector(
                    node.target.slice,
                    scope,
                    state,
                    apply_effects=True,
                    active_functions=active_functions,
                )
                current = self._flow_subscript_value(
                    self._materialize_flow_value(saved_receiver, state.store),
                    node.target.slice,
                )
            else:
                current, state = self._flow_eval_expression(
                    node.target,
                    scope,
                    state,
                    apply_effects=True,
                    active_functions=active_functions,
                )
            right, state = self._flow_eval_expression(
                node.value,
                scope,
                state,
                apply_effects=True,
                active_functions=active_functions,
            )
            current = self._materialize_flow_value(current, state.store)
            right = self._materialize_flow_value(right, state.store)
            if isinstance(node.op, ast.BitOr) and self._flow_value_is_modeled_dictionary(
                current,
                state.store,
            ):
                value, state = self._flow_inplace_mapping_union(current, right, state)
                if saved_receiver is not None and isinstance(node.target, ast.Subscript):
                    return self._flow_write_locations(
                        self._materialize_flow_value(saved_receiver, state.store),
                        node.target.slice,
                        value,
                        state,
                    )
                return self._flow_write_target(
                    node.target,
                    value,
                    scope,
                    state,
                    active_functions=active_functions,
                )
            if (
                isinstance(node.op, ast.Add)
                and current.locations
                and current.sequence_kind == "list"
            ):
                return self._flow_append_locations(
                    current,
                    right.sequence_elements,
                    state,
                )
            value = self._flow_augmented_value(node.op, current, right, state)
            if saved_receiver is not None and isinstance(node.target, ast.Subscript):
                return self._flow_write_locations(
                    self._materialize_flow_value(saved_receiver, state.store),
                    node.target.slice,
                    value,
                    state,
                )
            return self._flow_write_target(
                node.target,
                value,
                scope,
                state,
                active_functions=active_functions,
            )
        if isinstance(node, ast.Delete):
            for target in node.targets:
                state = self._flow_delete_target(
                    target,
                    scope,
                    state,
                    active_functions=active_functions,
                )
            return state
        if isinstance(node, ast.Expr):
            _value, state = self._flow_eval_expression(
                node.value,
                scope,
                state,
                apply_effects=True,
                active_functions=active_functions,
            )
            return state
        if isinstance(node, ast.If):
            _test, state = self._flow_eval_expression(
                node.test,
                scope,
                state,
                apply_effects=True,
                active_functions=active_functions,
            )
            return self._flow_join(
                (
                    self._flow_block(
                        node.body,
                        scope,
                        state,
                        active_functions=active_functions,
                    ),
                    self._flow_block(
                        node.orelse,
                        scope,
                        state,
                        active_functions=active_functions,
                    ),
                )
            )
        if isinstance(node, (ast.For, ast.AsyncFor)):
            iterable, state = self._flow_eval_expression(
                node.iter,
                scope,
                state,
                apply_effects=True,
                active_functions=active_functions,
            )
            state = self._flow_consume_deferred(iterable, state)
            return self._flow_loop(
                node.body,
                node.orelse,
                scope,
                state,
                target=node.target,
                iterable=iterable,
                active_functions=active_functions,
            )
        if isinstance(node, ast.While):
            return self._flow_loop(
                node.body,
                node.orelse,
                scope,
                state,
                condition=node.test,
                active_functions=active_functions,
            )
        if isinstance(node, (ast.Try, ast.TryStar)):
            prefixes = [state]
            normal = state
            for statement in node.body:
                normal = self._flow_statement(
                    statement,
                    scope,
                    normal,
                    active_functions=active_functions,
                )
                prefixes.append(normal)
                if isinstance(statement, (ast.Break, ast.Continue, ast.Raise, ast.Return)):
                    break
            normal = self._flow_block(
                node.orelse,
                scope,
                normal,
                active_functions=active_functions,
            )
            paths = [normal]
            handler_entry = self._flow_join(tuple(prefixes))
            for handler in node.handlers:
                handler_state = handler_entry
                if handler.type is not None:
                    _type, handler_state = self._flow_eval_expression(
                        handler.type,
                        scope,
                        handler_state,
                        apply_effects=True,
                        active_functions=active_functions,
                    )
                if handler.name is not None:
                    handler_state = self._flow_bind(
                        handler_state,
                        handler.name,
                        _unknown_value(sensitive=False),
                    )
                paths.append(
                    self._flow_block(
                        handler.body,
                        scope,
                        handler_state,
                        active_functions=active_functions,
                    )
                )
            joined = self._flow_join((*paths, handler_entry))
            return self._flow_block(
                node.finalbody,
                scope,
                joined,
                active_functions=active_functions,
            )
        if isinstance(node, ast.Match):
            subject, state = self._flow_eval_expression(
                node.subject,
                scope,
                state,
                apply_effects=True,
                active_functions=active_functions,
            )
            exhaustive = bool(
                node.cases
                and node.cases[-1].guard is None
                and isinstance(node.cases[-1].pattern, ast.MatchAs)
                and node.cases[-1].pattern.pattern is None
            )
            paths = [] if exhaustive else [state]
            for case in node.cases:
                case_state = self._flow_bind_pattern(case.pattern, subject, scope, state)
                if case.guard is not None:
                    _guard, case_state = self._flow_eval_expression(
                        case.guard,
                        scope,
                        case_state,
                        apply_effects=True,
                        active_functions=active_functions,
                    )
                paths.append(
                    self._flow_block(
                        case.body,
                        scope,
                        case_state,
                        active_functions=active_functions,
                    )
                )
            return self._flow_join(tuple(paths))
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                value, state = self._flow_eval_expression(
                    item.context_expr,
                    scope,
                    state,
                    apply_effects=True,
                    active_functions=active_functions,
                )
                if item.optional_vars is not None:
                    state = self._flow_write_target(
                        item.optional_vars,
                        value,
                        scope,
                        state,
                        active_functions=active_functions,
                    )
            return self._flow_block(
                node.body,
                scope,
                state,
                active_functions=active_functions,
            )
        if isinstance(node, ast.Return):
            value = ResolvedValue(static_key=self._literal_static_key(None))
            if node.value is not None:
                value, state = self._flow_eval_expression(
                    node.value,
                    scope,
                    state,
                    apply_effects=True,
                    active_functions=active_functions,
                )
            return self._flow_bind(state, "<return>", value)
        if isinstance(node, ast.Assert):
            _test, state = self._flow_eval_expression(
                node.test,
                scope,
                state,
                apply_effects=True,
                active_functions=active_functions,
            )
            if node.msg is not None:
                _message, state = self._flow_eval_expression(
                    node.msg,
                    scope,
                    state,
                    apply_effects=True,
                    active_functions=active_functions,
                )
        return state

    def _flow_invalidate_values(
        self,
        values: tuple[ResolvedValue, ...],
        state: _FlowState,
    ) -> _FlowState:
        locations = self._flow_reachable_locations(values, state.store)
        self.flow_mutated_locations.update(locations)
        argument_possible = _merge_values(values)
        store = state.store
        for location in sorted(locations):
            container = self._flow_store_get(store, location)
            if container is None:
                continue
            possible = _merge_values(
                (
                    argument_possible,
                    _unknown_value(
                        self._container_possible_origins(container),
                        sensitive=True,
                    ),
                )
            )
            container = self._flow_unknown_write(container, possible)
            store = self._flow_store_set(store, location, container)
        return state._replace(store=store)

    def _flow_helper_bindings(
        self,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        positional: tuple[ResolvedValue, ...],
        keywords: tuple[tuple[str | None, ResolvedValue], ...],
        caller: _FlowState,
        closure_bindings: tuple[tuple[str, ResolvedValue], ...],
    ) -> _FlowState:
        state = _FlowState(closure_bindings, caller.store)
        positional_parameters = (*function.args.posonlyargs, *function.args.args)
        consumed = min(len(positional), len(positional_parameters))
        for parameter, value in zip(
            positional_parameters,
            positional[:consumed],
            strict=False,
        ):
            state = self._flow_bind(state, parameter.arg, value)
        supplied_keywords = {name: value for name, value in keywords if name is not None}
        defaults_by_name = self.flow_function_defaults.get(id(function), {})
        for parameter in positional_parameters[consumed:]:
            if parameter.arg in supplied_keywords:
                parameter_value = supplied_keywords.pop(parameter.arg)
            else:
                default_value = defaults_by_name.get(parameter.arg)
                parameter_value = (
                    _unknown_value(sensitive=False) if default_value is None else default_value
                )
            state = self._flow_bind(state, parameter.arg, parameter_value)
        if function.args.vararg is not None:
            state = self._flow_bind(
                state,
                function.args.vararg.arg,
                _sequence_value("tuple", positional[len(positional_parameters) :]),
            )
        for parameter, default in zip(
            function.args.kwonlyargs,
            function.args.kw_defaults,
            strict=True,
        ):
            if parameter.arg in supplied_keywords:
                keyword_value = supplied_keywords.pop(parameter.arg)
            else:
                default_value = defaults_by_name.get(parameter.arg)
                if default is None or default_value is None:
                    keyword_value = _unknown_value(sensitive=False)
                else:
                    keyword_value = default_value
            state = self._flow_bind(state, parameter.arg, keyword_value)
        if function.args.kwarg is not None:
            entries = tuple(
                (key, value)
                for name, value in supplied_keywords.items()
                if (key := self._literal_static_key(name)) is not None
            )
            state = self._flow_bind(
                state,
                function.args.kwarg.arg,
                _mapping_value(entries),
            )
        return state

    def _flow_value_is_security_relevant(self, value: ResolvedValue) -> bool:
        if value.sensitive_unknown or value.reachability_overflow:
            return True
        origin_sets: tuple[frozenset[str], ...] = (
            value.direct_origins,
            value.deferred_origins,
        )
        if (
            value.locations
            or value.sequence_elements is not None
            or value.mapping_entries is not None
        ):
            origin_sets = (*origin_sets, value.aggregate_origins)
        origins = _union_origins(origin_sets)
        return any(
            _qualified_call_target_is_forbidden(origin)
            or _is_forbidden_binding_name(origin.rsplit(".", 1)[-1])
            or origin.endswith((".ArmAction", ".ReturnedRunProjection"))
            or any(marker in origin for marker in _REGISTRY_OR_EVIDENCE_MARKERS)
            for origin in origins
        )

    def _flow_function_returns(
        self,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        function_scope: _Scope,
    ) -> tuple[ast.Return, ...]:
        cached = self.flow_function_return_nodes.get(id(function))
        if cached is not None:
            return cached
        returns = tuple(
            candidate
            for candidate in ast.walk(function)
            if isinstance(candidate, ast.Return)
            and self.node_scopes.get(id(candidate)) is function_scope
        )
        self.flow_function_return_nodes[id(function)] = returns
        return returns

    def _flow_summarize_local_helper(
        self,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        child: _Scope,
        caller: _FlowState,
        helper_entry: _FlowState,
        affected_values: tuple[ResolvedValue, ...],
        active_functions: frozenset[str],
        *,
        may_mutate: bool,
    ) -> tuple[ResolvedValue, _FlowState]:
        summary_entry = (
            self._flow_invalidate_values(affected_values, helper_entry)
            if may_mutate
            else helper_entry
        )
        returned_values: list[ResolvedValue] = []
        return_states: list[_FlowState] = []
        for return_node in self._flow_function_returns(function, child):
            if return_node.value is None:
                returned_values.append(ResolvedValue(static_key=self._literal_static_key(None)))
                return_states.append(summary_entry)
                continue
            returned, return_state = self._flow_eval_expression(
                return_node.value,
                child,
                summary_entry,
                apply_effects=False,
                active_functions=active_functions,
            )
            returned_values.append(returned)
            return_states.append(return_state)
        returned = (
            _merge_values(tuple(returned_values))
            if returned_values
            else ResolvedValue(static_key=self._literal_static_key(None))
        )
        summarized = _FlowState(
            caller.bindings,
            self._flow_join(tuple(return_states)).store if return_states else summary_entry.store,
        )
        return returned, summarized

    def _flow_function_mutates_composites(
        self,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        function_scope: _Scope,
    ) -> bool:
        cached = self.flow_function_composite_mutation.get(id(function))
        if cached is not None:
            return cached
        mutates = False
        for node in ast.walk(function):
            if self.node_scopes.get(id(node)) is not function_scope:
                continue
            if isinstance(node, ast.Assign) and any(
                not isinstance(target, ast.Name) for target in node.targets
            ):
                mutates = True
                break
            if isinstance(node, ast.AnnAssign) and not isinstance(node.target, ast.Name):
                mutates = True
                break
            if isinstance(node, (ast.AugAssign, ast.Delete)):
                mutates = True
                break
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _REGISTRY_MUTATION_ATTRIBUTES | _BUILTIN_MUTATION_ATTRIBUTES
            ):
                mutates = True
                break
        self.flow_function_composite_mutation[id(function)] = mutates
        return mutates

    def _flow_apply_local_helper(
        self,
        call: ast.Call,
        target: str,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        child: _Scope,
        call_scope: _Scope,
        caller: _FlowState,
        positional: tuple[ResolvedValue, ...],
        keywords: tuple[tuple[str | None, ResolvedValue], ...],
        active_functions: frozenset[str],
    ) -> tuple[ResolvedValue, _FlowState]:
        parameter_names = frozenset(self._flow_callable_parameters(function))
        local_names = frozenset(child.kinds) - parameter_names
        loaded_names = {
            loaded.id
            for loaded in ast.walk(function)
            if isinstance(loaded, ast.Name)
            and isinstance(loaded.ctx, ast.Load)
            and self.node_scopes.get(id(loaded)) is child
        }
        closure_names = loaded_names - parameter_names - local_names
        closure_bindings: list[tuple[str, ResolvedValue]] = []
        for name in sorted(closure_names):
            value = _flow_binding_get(caller.bindings, name) if child.parent is call_scope else None
            if value is None:
                value = self._lookup_value(
                    child,
                    name,
                    function.lineno,
                    function.col_offset,
                )
            closure_bindings.append((name, value))
        closure_values = tuple(value for _name, value in closure_bindings)
        closure_binding_tuple = tuple(closure_bindings)
        helper_entry = self._flow_helper_bindings(
            function,
            positional,
            keywords,
            caller,
            closure_binding_tuple,
        )
        effective_parameters = tuple(
            value for name, value in helper_entry.bindings if name in parameter_names
        )
        affected_values = (*effective_parameters, *closure_values)
        lexical_fallback = caller
        helper_may_mutate = bool(
            self._flow_reachable_locations(affected_values, caller.store)
        ) and self._flow_function_may_mutate(function, child)
        lexically_uncertain = bool(
            child.parent is not call_scope
            and child.parent is not self.module_scope
            and closure_names
            and helper_may_mutate
        )
        if lexically_uncertain:
            lexical_fallback = self._flow_invalidate_values(affected_values, caller)
        security_relevant_context = any(
            self._flow_value_is_security_relevant(value) for value in affected_values
        )
        known_composite_mutation = bool(
            security_relevant_context and self._flow_function_mutates_composites(function, child)
        )
        precise_helper = self._flow_function_needs_temporal_analysis(
            target,
            function,
            child,
        ) or (security_relevant_context and known_composite_mutation)
        if not precise_helper:
            self.flow_called_function_targets.add(target)
            return self._flow_summarize_local_helper(
                function,
                child,
                caller,
                helper_entry,
                affected_values,
                active_functions | {target},
                may_mutate=helper_may_mutate,
            )
        if (
            target in active_functions
            or len(active_functions) >= _MAX_LOCAL_HELPER_DEPTH
            or isinstance(function, ast.AsyncFunctionDef)
            or function.decorator_list
            or self._flow_function_node_count(function, child) > _MAX_PRECISE_LOCAL_HELPER_NODES
            or (
                isinstance(self.parents.get(id(call)), ast.Expr)
                and self.flow_precise_helper_context_counts.get(id(function), 0)
                >= _MAX_PRECISE_UNUSED_HELPER_CONTEXTS
            )
        ):
            if len(active_functions) >= _MAX_LOCAL_HELPER_DEPTH:
                self._record_fail_closed_finding(
                    "unresolved-sensitive-provenance",
                    "analysis:local-helper-depth-limit",
                    call.lineno,
                )
            invalidated = self._flow_invalidate_values(affected_values, caller)
            if lexically_uncertain:
                invalidated = self._flow_join((invalidated, lexical_fallback))
            return _unknown_value(
                frozenset(
                    origin
                    for value in affected_values
                    for origin in value.aggregate_origins | value.direct_origins
                ),
                sensitive=True,
            ), invalidated
        self.flow_called_function_targets.add(target)
        self.flow_precise_helper_context_counts[id(function)] = (
            self.flow_precise_helper_context_counts.get(id(function), 0) + 1
        )
        helper_exit = self._flow_block(
            function.body,
            child,
            helper_entry,
            active_functions=active_functions | {target},
        )
        returned = _flow_binding_get(helper_exit.bindings, "<return>")
        if returned is None:
            returned = ResolvedValue(static_key=self._literal_static_key(None))
        result_state = _FlowState(caller.bindings, helper_exit.store)
        if lexically_uncertain:
            result_state = self._flow_join((result_state, lexical_fallback))
        return returned, result_state

    def _flow_function_needs_temporal_analysis(
        self,
        target: str,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        function_scope: _Scope,
    ) -> bool:
        cached = self.flow_function_relevance.get(id(function))
        if cached is not None:
            return cached
        function_id = id(function)
        relevant = target.endswith("._fail")
        if not relevant:
            relevant = any(
                self._flow_value_is_security_relevant(value)
                for value in self.flow_function_defaults.get(function_id, {}).values()
            )
        if not relevant:
            for node in ast.walk(function):
                if self.node_scopes.get(id(node)) is not function_scope:
                    continue
                mutation_targets: tuple[ast.expr, ...] = ()
                include_names = False
                if isinstance(node, ast.Assign):
                    mutation_targets = tuple(
                        candidate
                        for candidate in node.targets
                        if not isinstance(candidate, ast.Name)
                    )
                elif isinstance(node, ast.AnnAssign) and not isinstance(
                    node.target,
                    ast.Name,
                ):
                    mutation_targets = (node.target,)
                elif isinstance(node, (ast.AugAssign, ast.Delete)):
                    mutation_targets = (
                        (node.target,) if isinstance(node, ast.AugAssign) else tuple(node.targets)
                    )
                    include_names = True
                if mutation_targets and self._flow_value_is_security_relevant(
                    _merge_values(
                        tuple(
                            self._mutation_target_value(
                                candidate,
                                function_scope,
                                include_names=include_names,
                            )
                            for candidate in mutation_targets
                        )
                    )
                ):
                    relevant = True
                    break
                if isinstance(node, ast.Call):
                    if (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr
                        in _REGISTRY_MUTATION_ATTRIBUTES | _BUILTIN_MUTATION_ATTRIBUTES
                    ):
                        receiver = self._resolve_expression(node.func.value, function_scope)
                        if self._flow_value_is_security_relevant(receiver) or (
                            receiver.is_unknown and isinstance(node.func.value, ast.Attribute)
                        ):
                            relevant = True
                            break
                    call_value = self._resolve_expression(node.func, function_scope)
                    if any(
                        origin.startswith(f"{target}.")
                        for origin in call_value.direct_origins | call_value.deferred_origins
                    ):
                        relevant = True
                        break
                if isinstance(node, ast.Name) and (
                    node.id in {"ArmAction", "ReturnedRunProjection", "run_arm"}
                    or _is_forbidden_binding_name(node.id)
                    or any(marker in node.id for marker in _REGISTRY_OR_EVIDENCE_MARKERS)
                ):
                    relevant = True
                    break
                if isinstance(node, (ast.Attribute, ast.Name)):
                    resolved = self._resolve_expression(node, function_scope)
                    if any(
                        _qualified_call_target_is_forbidden(origin)
                        or _is_forbidden_binding_name(origin.rsplit(".", 1)[-1])
                        or origin.endswith((".ArmAction", ".ReturnedRunProjection"))
                        or any(marker in origin for marker in _REGISTRY_OR_EVIDENCE_MARKERS)
                        for origin in resolved.direct_origins | resolved.deferred_origins
                    ):
                        relevant = True
                        break
        self.flow_function_relevance[id(function)] = relevant
        return relevant

    def _build_composite_flow(self) -> None:
        self._building_composite_flow = True
        try:
            module_final = self._flow_block(
                self.tree.body,
                self.module_scope,
                _FlowState(),
            )
            self.flow_final_states[id(self.module_scope)] = module_final
            for target in sorted(self.local_functions):
                if target in self.flow_called_function_targets:
                    continue
                for function, child in self.local_functions[target]:
                    if not self._flow_function_needs_temporal_analysis(
                        target,
                        function,
                        child,
                    ):
                        continue
                    initial_bindings = tuple(
                        sorted(
                            (
                                name,
                                child.values.get(name, _unknown_value(sensitive=False)),
                            )
                            for name, kinds in child.kinds.items()
                            if "argument" in kinds
                        )
                    )
                    final = self._flow_block(
                        function.body,
                        child,
                        _FlowState(initial_bindings),
                        active_functions=frozenset({target}),
                    )
                    self.flow_final_states[id(child)] = final
            for scope_id, class_node in self.class_scope_nodes.items():
                if scope_id in self.flow_final_states:
                    continue
                class_scope = next(scope for scope in self.scopes if id(scope) == scope_id)
                final = self._flow_block(
                    class_node.body,
                    class_scope,
                    _FlowState(),
                )
                self.flow_final_states[scope_id] = final
        finally:
            self._building_composite_flow = False

    def _definition_is_unconditional(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> bool:
        conditional_ancestors = (
            ast.AsyncFor,
            ast.AsyncWith,
            ast.ExceptHandler,
            ast.For,
            ast.If,
            ast.Match,
            ast.Try,
            ast.TryStar,
            ast.While,
            ast.With,
        )
        parent = self.parents.get(id(node))
        while parent is not None and not isinstance(
            parent,
            (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef, ast.Lambda, ast.Module),
        ):
            if isinstance(parent, conditional_ancestors):
                return False
            parent = self.parents.get(id(parent))
        return True

    def _simple_function_return(
        self,
        target: str,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        child: _Scope,
        active_functions: frozenset[str],
    ) -> ResolvedValue:
        if (
            target in active_functions
            or len(active_functions) >= _MAX_LOCAL_HELPER_DEPTH
            or isinstance(node, ast.AsyncFunctionDef)
            or node.decorator_list
        ):
            if len(active_functions) >= _MAX_LOCAL_HELPER_DEPTH:
                self._record_fail_closed_finding(
                    "unresolved-sensitive-provenance",
                    "analysis:local-helper-depth-limit",
                    node.lineno,
                )
            return _unknown_value(sensitive=True)
        arguments = node.args
        if (
            arguments.posonlyargs
            or arguments.args
            or arguments.kwonlyargs
            or arguments.vararg is not None
            or arguments.kwarg is not None
        ):
            return _unknown_value(sensitive=True)
        body = tuple(
            statement
            for statement in node.body
            if not (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            )
        )
        if (
            not body
            or not isinstance(body[-1], ast.Return)
            or any(
                not isinstance(statement, (ast.Assign, ast.AnnAssign)) for statement in body[:-1]
            )
        ):
            return _unknown_value(sensitive=True)
        return_statement = body[-1]
        if return_statement.value is None:
            key = self._literal_static_key(None)
            return ResolvedValue(static_key=key)
        resolved = self._resolve_expression(
            return_statement.value,
            child,
            active_functions | {target},
        )
        return _mark_unknown_leaves_sensitive(resolved)

    def _resolve_expression(
        self,
        node: ast.AST,
        scope: _Scope,
        active_functions: frozenset[str] = frozenset(),
    ) -> ResolvedValue:
        return self._with_static_key(
            node,
            self._resolve_expression_inner(node, scope, active_functions),
        )

    def _resolve_expression_inner(
        self,
        node: ast.AST,
        scope: _Scope,
        active_functions: frozenset[str] = frozenset(),
    ) -> ResolvedValue:
        if not self._building_composite_flow and not self._resolving_flow_snapshot:
            flow_value = self.flow_node_values.get(id(node))
            if flow_value is not None and (
                flow_value.temporally_derived
                or flow_value.bound_mutators
                or id(node) in self.flow_write_target_node_ids
            ):
                return flow_value
            flow_state = self.flow_node_states.get(id(node))
            if flow_state is not None:
                cache_key = (
                    id(node),
                    id(scope),
                    _flow_store_fingerprint(flow_state.store),
                    active_functions,
                )
                cached = self._post_flow_resolution_cache.get(cache_key)
                if cached is not None and cached[0] is flow_state.store:
                    self._post_flow_resolution_cache_hits += 1
                    return cached[1]
                self._post_flow_resolution_cache_misses += 1
                self._resolving_flow_snapshot = True
                try:
                    resolved, _state = self._flow_eval_expression(
                        node,
                        scope,
                        flow_state,
                        apply_effects=False,
                        active_functions=active_functions,
                    )
                    materialized = self._materialize_flow_value(resolved, flow_state.store)
                    if (
                        not materialized.temporally_derived
                        and id(node) not in self.flow_write_target_node_ids
                    ):
                        continue_with_legacy = True
                    else:
                        continue_with_legacy = False
                    if (
                        not continue_with_legacy
                        and len(self._post_flow_resolution_cache) < _MAX_POST_FLOW_RESOLUTION_CACHE
                    ):
                        self._post_flow_resolution_cache[cache_key] = (
                            flow_state.store,
                            materialized,
                        )
                    if not continue_with_legacy:
                        return materialized
                finally:
                    self._resolving_flow_snapshot = False
        if isinstance(node, ast.Name):
            return self._lookup_value(scope, node.id, node.lineno, node.col_offset)
        if isinstance(node, ast.Attribute):
            owner = self._resolve_expression(node.value, scope, active_functions)
            direct = frozenset(f"{origin}.{node.attr}" for origin in owner.direct_origins)
            return ResolvedValue(
                direct_origins=direct,
                aggregate_origins=owner.aggregate_origins | direct,
                is_unknown=owner.is_unknown,
                sensitive_unknown=owner.sensitive_unknown,
            )
        if isinstance(node, ast.Constant):
            return ResolvedValue(static_key=self._literal_static_key(node.value))
        if isinstance(node, (ast.Tuple, ast.List)):
            elements: list[ResolvedValue] = []
            unresolved_starred: list[ResolvedValue] = []
            for item in node.elts:
                if isinstance(item, ast.Starred):
                    starred = self._resolve_expression(item.value, scope, active_functions)
                    if starred.sequence_elements is None:
                        unresolved_starred.append(starred)
                    else:
                        elements.extend(starred.sequence_elements)
                else:
                    elements.append(self._resolve_expression(item, scope, active_functions))
            if unresolved_starred:
                starred_origins = frozenset(
                    origin
                    for value in (*elements, *unresolved_starred)
                    for origin in value.aggregate_origins
                )
                return ResolvedValue(
                    aggregate_origins=starred_origins,
                    is_unknown=True,
                    sensitive_unknown=any(value.sensitive_unknown for value in unresolved_starred),
                )
            return _sequence_value(
                "tuple" if isinstance(node, ast.Tuple) else "list",
                tuple(elements),
            )
        if isinstance(node, ast.Dict):
            container = _AbstractContainerState("dict", mapping_entries=())
            for key_node, value_node in zip(node.keys, node.values, strict=True):
                if key_node is None:
                    value = self._resolve_expression(value_node, scope, active_functions)
                    container = _apply_ordered_mapping_writes(
                        container,
                        (_resolved_mapping_write(value),),
                    )
                    continue
                key_value = self._resolve_expression(key_node, scope, active_functions)
                value = self._resolve_expression(value_node, scope, active_functions)
                key = self._static_key(key_node)
                if key is None:
                    write = _OrderedMappingWrite(
                        unknown_value=_unknown_mapping_value(_merge_values((key_value, value)))
                    )
                else:
                    write = _ordered_direct_mapping_write(
                        key,
                        value,
                    )
                container = _apply_ordered_mapping_writes(container, (write,))
            return _resolved_mapping_value(container)
        if isinstance(node, ast.Set):
            values = tuple(
                self._resolve_expression(item, scope, active_functions) for item in node.elts
            )
            return ResolvedValue(
                sequence_kind="set",
                aggregate_origins=frozenset(
                    origin for value in values for origin in value.aggregate_origins
                ),
                is_unknown=any(value.is_unknown for value in values),
                sensitive_unknown=any(value.sensitive_unknown for value in values),
            )
        if isinstance(node, ast.Starred):
            return self._resolve_expression(node.value, scope, active_functions)
        if isinstance(node, ast.IfExp):
            return _merge_values(
                (
                    self._resolve_expression(node.body, scope, active_functions),
                    self._resolve_expression(node.orelse, scope, active_functions),
                )
            )
        if isinstance(node, ast.BoolOp):
            return _merge_values(
                tuple(
                    self._resolve_expression(value, scope, active_functions)
                    for value in node.values
                )
            )
        if isinstance(node, ast.NamedExpr):
            return self._resolve_expression(node.value, scope, active_functions)
        if isinstance(node, ast.Await):
            awaited = self._resolve_expression(node.value, scope, active_functions)
            return (
                awaited._replace(sensitive_unknown=True)
                if awaited.is_unknown and not awaited.sensitive_unknown
                else awaited
            )
        if isinstance(node, ast.UnaryOp):
            operand = self._resolve_expression(node.operand, scope, active_functions)
            return _unknown_value(
                operand.aggregate_origins | operand.direct_origins,
                sensitive=True,
            )
        if isinstance(node, ast.BinOp):
            left = self._resolve_expression(node.left, scope, active_functions)
            right = self._resolve_expression(node.right, scope, active_functions)
            if (
                isinstance(node.op, ast.BitOr)
                and left.mapping_entries is not None
                and right.mapping_entries is not None
            ):
                return _resolved_mapping_value(
                    _apply_ordered_mapping_writes(
                        _AbstractContainerState("dict", mapping_entries=()),
                        (
                            _resolved_mapping_write(left),
                            _resolved_mapping_write(right),
                        ),
                    )
                )
            if (
                isinstance(node.op, ast.Add)
                and left.sequence_elements is not None
                and right.sequence_elements is not None
                and left.sequence_kind == right.sequence_kind
            ):
                return _sequence_value(
                    left.sequence_kind or "sequence",
                    (*left.sequence_elements, *right.sequence_elements),
                )
            aggregate = left.aggregate_origins | right.aggregate_origins
            return _unknown_value(aggregate, sensitive=True)
        if isinstance(node, ast.Subscript):
            return self._resolve_subscript(node, scope, active_functions)
        if isinstance(node, ast.Call):
            call_target = self._resolve_expression(node.func, scope, active_functions)
            if (
                call_target.direct_origins == {"typing.cast"}
                and len(node.args) == 2
                and not node.keywords
            ):
                return self._resolve_expression(node.args[1], scope, active_functions)
            if (
                call_target.direct_origins == {"builtins.dict"}
                and len(node.args) <= 1
                and all(keyword.arg is not None for keyword in node.keywords)
            ):
                writes: list[_OrderedMappingWrite] = []
                if node.args:
                    source = self._resolve_expression(
                        node.args[0],
                        scope,
                        active_functions,
                    )
                    if source.mapping_entries is not None:
                        writes.append(_resolved_mapping_write(source))
                    else:
                        writes.extend(_resolved_pair_iterable_mapping_writes(source))
                for keyword in node.keywords:
                    if keyword.arg is None:
                        continue
                    key = self._literal_static_key(keyword.arg)
                    if key is not None:
                        writes.append(
                            _OrderedMappingWrite(
                                (
                                    (
                                        key,
                                        self._resolve_expression(
                                            keyword.value,
                                            scope,
                                            active_functions,
                                        ),
                                    ),
                                )
                            )
                        )
                return _resolved_mapping_value(
                    _apply_ordered_mapping_writes(
                        _AbstractContainerState("dict", mapping_entries=()),
                        tuple(writes),
                    )
                )
            if (
                len(call_target.direct_origins) == 1
                and not node.keywords
                and next(iter(call_target.direct_origins))
                in {
                    "builtins.frozenset",
                    "builtins.list",
                    "builtins.set",
                    "builtins.tuple",
                }
                and len(node.args) <= 1
            ):
                constructor = next(iter(call_target.direct_origins))
                source_value = (
                    ResolvedValue()
                    if not node.args
                    else self._resolve_expression(node.args[0], scope, active_functions)
                )
                if constructor in {"builtins.list", "builtins.tuple"}:
                    if source_value.sequence_elements is not None:
                        return _sequence_value(
                            "list" if constructor == "builtins.list" else "tuple",
                            source_value.sequence_elements,
                        )
                    return ResolvedValue(
                        sequence_kind=("list" if constructor == "builtins.list" else "tuple"),
                        aggregate_origins=source_value.aggregate_origins,
                        is_unknown=bool(node.args),
                        sensitive_unknown=source_value.sensitive_unknown,
                    )
                return ResolvedValue(
                    sequence_kind=(
                        "set" if constructor in {"builtins.frozenset", "builtins.set"} else None
                    ),
                    aggregate_origins=source_value.aggregate_origins,
                    is_unknown=bool(node.args),
                    sensitive_unknown=source_value.sensitive_unknown,
                )
            local_returns = tuple(
                local_return
                for target in sorted(call_target.direct_origins)
                if (
                    local_return := self._simple_local_return(
                        target,
                        active_functions,
                        node.lineno,
                        scope,
                    )
                )
                is not None
            )
            if local_returns and len(local_returns) == len(call_target.direct_origins):
                return _merge_values(local_returns)
            argument_values = tuple(
                self._resolve_expression(argument.value, scope, active_functions)
                if isinstance(argument, ast.Starred)
                else self._resolve_expression(argument, scope, active_functions)
                for argument in node.args
            ) + tuple(
                self._resolve_expression(keyword.value, scope, active_functions)
                for keyword in node.keywords
            )
            possible = frozenset(
                origin for value in argument_values for origin in value.aggregate_origins
            )
            candidates = (*local_returns, _unknown_value(possible, sensitive=True))
            return _merge_values(candidates)
        return _unknown_value(sensitive=False)

    def _resolve_aliases(self) -> None:
        if self.alias_resolution_exhausted:
            return
        for _pass in range(_MAX_ALIAS_RESOLUTION_PASSES):
            changed = False
            for scope in self.scopes:
                for name, expressions in scope.aliases.items():
                    if (scope.path, name) in self.alias_cycle_names:
                        combined = _unknown_value(sensitive=True)
                    else:
                        binding = (id(scope), name)
                        self.active_alias_bindings.add(binding)
                        try:
                            candidates = tuple(
                                self._resolve_alias_expression(expression, scope)
                                for expression in expressions
                            )
                        finally:
                            self.active_alias_bindings.remove(binding)
                        if name in scope.base_values:
                            candidates = (scope.base_values[name], *candidates)
                        combined = _merge_values(candidates)
                    if combined != scope.values.get(name, ResolvedValue()):
                        scope.values[name] = combined
                        changed = True
            if not changed:
                return
        self.alias_resolution_exhausted = True
        self._record_fail_closed_finding(
            "unresolved-sensitive-provenance",
            "analysis:alias-fixed-point-limit",
            0,
        )
        for scope in self.scopes:
            for name in scope.aliases:
                current = scope.values.get(name, ResolvedValue())
                base = scope.base_values.get(name, ResolvedValue())
                scope.values[name] = _unknown_value(
                    current.direct_origins
                    | current.aggregate_origins
                    | base.direct_origins
                    | base.aggregate_origins,
                    sensitive=True,
                )

    def _resolve_alias_expression(self, expression: ast.expr, scope: _Scope) -> ResolvedValue:
        resolved = self._resolve_expression(expression, scope)
        if isinstance(expression, ast.Attribute) and resolved.is_unknown:
            return resolved._replace(sensitive_unknown=True)
        return resolved

    def _alias_dependencies(self, node: ast.AST) -> frozenset[str]:
        if isinstance(node, ast.Name):
            return frozenset({node.id})
        if isinstance(node, ast.Attribute):
            return self._alias_dependencies(node.value)
        if isinstance(node, ast.Subscript):
            return self._alias_dependencies(node.value)
        if isinstance(node, ast.Starred):
            return self._alias_dependencies(node.value)
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return frozenset(
                dependency for item in node.elts for dependency in self._alias_dependencies(item)
            )
        if isinstance(node, ast.Dict):
            return frozenset(
                dependency for item in node.values for dependency in self._alias_dependencies(item)
            )
        if isinstance(node, ast.IfExp):
            return self._alias_dependencies(node.body) | self._alias_dependencies(node.orelse)
        if isinstance(node, ast.BoolOp):
            return frozenset(
                dependency
                for value in node.values
                for dependency in self._alias_dependencies(value)
            )
        if isinstance(node, ast.NamedExpr):
            return self._alias_dependencies(node.value)
        if isinstance(node, ast.UnaryOp):
            return self._alias_dependencies(node.operand)
        if isinstance(node, ast.Await):
            return self._alias_dependencies(node.value)
        if isinstance(node, ast.BinOp):
            return self._alias_dependencies(node.left) | self._alias_dependencies(node.right)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "cast"
            and len(node.args) == 2
            and not node.keywords
        ):
            return self._alias_dependencies(node.args[1])
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"dict", "frozenset", "list", "set", "tuple"}
            and len(node.args) <= 1
        ):
            return frozenset(
                dependency
                for argument in (*node.args, *(keyword.value for keyword in node.keywords))
                for dependency in self._alias_dependencies(argument)
            )
        return frozenset()

    def _find_alias_cycles(self) -> None:
        for scope in self.scopes:
            graph = {
                name: frozenset(
                    dependency
                    for index, expression in enumerate(expressions)
                    for dependency in self._alias_dependencies(expression)
                    if dependency in scope.aliases
                    and not (
                        dependency == name
                        and self._is_exact_non_inplace_dict_union_rebind(
                            scope,
                            name,
                            expression,
                            expressions[:index],
                        )
                    )
                )
                for name, expressions in scope.aliases.items()
            }
            active: list[str] = []
            complete: set[str] = set()
            for name in graph:
                self._visit_alias_cycle(scope, graph, name, active, complete)

    def _is_exact_non_inplace_dict_union_rebind(
        self,
        scope: _Scope,
        name: str,
        expression: ast.expr,
        previous: list[ast.expr],
    ) -> bool:
        def exact_mapping(
            candidate: ast.expr,
            before_line: int,
            active_names: frozenset[str] = frozenset(),
        ) -> bool:
            if isinstance(candidate, ast.Name):
                if candidate.id in active_names:
                    return False
                return any(
                    getattr(alias, "lineno", 0) < before_line
                    and exact_mapping(
                        alias,
                        getattr(alias, "lineno", before_line),
                        active_names | {candidate.id},
                    )
                    for alias in scope.aliases.get(candidate.id, ())
                )
            return bool(
                isinstance(candidate, (ast.Dict, ast.DictComp))
                or (
                    isinstance(candidate, ast.Call)
                    and isinstance(candidate.func, ast.Name)
                    and candidate.func.id == "dict"
                    and len(candidate.args) <= 1
                )
            )

        if not isinstance(expression, ast.BinOp) or not isinstance(expression.op, ast.BitOr):
            return False
        left_is_self = isinstance(expression.left, ast.Name) and expression.left.id == name
        right_is_self = isinstance(expression.right, ast.Name) and expression.right.id == name
        other_is_exact = bool(
            (left_is_self and exact_mapping(expression.right, expression.lineno))
            or (right_is_self and exact_mapping(expression.left, expression.lineno))
        )
        return bool(
            other_is_exact
            and any(
                exact_mapping(candidate, expression.lineno, frozenset({name}))
                for candidate in previous
            )
        )

    def _visit_alias_cycle(
        self,
        scope: _Scope,
        graph: dict[str, frozenset[str]],
        name: str,
        active: list[str],
        complete: set[str],
    ) -> None:
        if name in complete:
            return
        if name in active:
            cycle = active[active.index(name) :]
            self.alias_cycle_names.update((scope.path, item) for item in cycle)
            self.findings.append(
                ArchitectureFinding(
                    "alias-cycle",
                    name,
                    scope.lines.get(name, 0),
                )
            )
            return
        active.append(name)
        for dependency in graph[name]:
            self._visit_alias_cycle(scope, graph, dependency, active, complete)
        active.pop()
        complete.add(name)

    def _is_exact_missing_context_sentinel(self, name: str, expression: ast.expr) -> bool:
        return bool(
            name == "_MISSING_CONTEXT"
            and isinstance(expression, ast.Call)
            and isinstance(expression.func, ast.Name)
            and expression.func.id == "object"
            and not expression.args
            and not expression.keywords
        )

    def _is_exact_approved_type_alias(self, name: str, expression: ast.expr) -> bool:
        return bool(
            self.module_name == RETURNED_RUN_MODULE_NAME
            and (name, ast.unparse(expression)) in AUTHORIZED_RETURNED_RUN_TYPE_ALIAS_VALUES
        )

    def _find_top_level_alias_behavior(self) -> None:
        dynamic_expression_types = (
            ast.Call,
            ast.IfExp,
            ast.Lambda,
            ast.Subscript,
        )
        for name, expressions in self.module_scope.aliases.items():
            for expression in expressions:
                if self._is_exact_approved_type_alias(name, expression):
                    continue
                resolved = self._resolve_expression(expression, self.module_scope)
                if resolved.direct_origins:
                    self.findings.append(
                        ArchitectureFinding(
                            "top-level-qualified-alias",
                            name,
                            self.module_scope.lines[name],
                        )
                    )
                elif isinstance(
                    expression, dynamic_expression_types
                ) and not self._is_exact_missing_context_sentinel(name, expression):
                    self.findings.append(
                        ArchitectureFinding(
                            "unresolved-top-level-binding",
                            name,
                            self.module_scope.lines[name],
                        )
                    )

    def _resolved_calls(self) -> tuple[ResolvedCall, ...]:
        calls: list[ResolvedCall] = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            scope = self.node_scopes.get(id(node), self.module_scope)
            resolved = self._resolve_expression(node.func, scope)
            targets = resolved.direct_origins
            spelling = ast.unparse(node.func)
            unresolved_bare_parameter = self._is_unresolved_bare_parameter(
                node.func,
                scope,
                resolved,
                self.callable_parameter_bindings,
            )
            aliases = scope.aliases.get(node.func.id, []) if isinstance(node.func, ast.Name) else []
            unresolved_iteration_target = bool(
                aliases and all(self._is_iteration_derived_alias(alias) for alias in aliases)
            )
            dynamic = bool(
                isinstance(node.func, ast.Name)
                and aliases
                and not targets
                and not resolved.bound_mutators
                and not unresolved_iteration_target
            )
            reported_scope = self._reported_scope_path(scope)
            calls.append(
                ResolvedCall(
                    reported_scope,
                    spelling,
                    targets,
                    node.lineno,
                    dynamic,
                    resolved.sensitive_unknown
                    or resolved.bound_mutator_uncertain
                    or (resolved.is_unknown and isinstance(node.func, ast.Attribute))
                    or unresolved_bare_parameter
                    or self._unresolved_site_is_approved(reported_scope, spelling),
                    bool(resolved.bound_mutators),
                )
            )
        return tuple(calls)

    def _resolved_references(self) -> tuple[ResolvedReference, ...]:
        references: list[ResolvedReference] = []
        call_function_ids = {
            id(node.func) for node in ast.walk(self.tree) if isinstance(node, ast.Call)
        }
        for node in ast.walk(self.tree):
            if not isinstance(node, (ast.Name, ast.Attribute)) or not isinstance(
                node.ctx, ast.Load
            ):
                continue
            scope = self.node_scopes.get(id(node), self.module_scope)
            resolved = self._resolve_expression(node, scope)
            targets = resolved.direct_origins
            if (isinstance(node, ast.Attribute) and node.attr in _DYNAMIC_NAMESPACE_ATTRIBUTES) or (
                isinstance(node, ast.Name) and node.id in _DYNAMIC_NAMESPACE_ATTRIBUTES
            ):
                self.findings.append(
                    ArchitectureFinding(
                        "dynamic-namespace-reference",
                        ast.unparse(node),
                        node.lineno,
                    )
                )
            if (
                isinstance(node, ast.Attribute)
                and node.attr in _REGISTRY_MUTATION_ATTRIBUTES | _BUILTIN_MUTATION_ATTRIBUTES
                and not targets
                and not resolved.bound_mutators
                and id(node) not in call_function_ids
            ):
                self.findings.append(
                    ArchitectureFinding(
                        "unresolved-mutator-reference",
                        ast.unparse(node),
                        node.lineno,
                    )
                )
            references.append(
                ResolvedReference(
                    self._reported_scope_path(scope),
                    ast.unparse(node),
                    targets,
                    node.lineno,
                )
            )
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            scope = self.node_scopes.get(id(node), self.module_scope)
            call_targets = self._resolve_expression(node.func, scope).direct_origins
            if call_targets.isdisjoint(_CALLBACK_KEYWORD_BUILTIN_TARGETS):
                continue
            for keyword in node.keywords:
                if keyword.arg != "key":
                    continue
                resolved = self._resolve_expression(keyword.value, scope)
                spelling = ast.unparse(keyword.value)
                if not isinstance(keyword.value, (ast.Name, ast.Attribute)):
                    references.append(
                        ResolvedReference(
                            self._reported_scope_path(scope),
                            spelling,
                            resolved.direct_origins,
                            keyword.value.lineno,
                        )
                    )
                if resolved.is_unknown or resolved.sensitive_unknown:
                    self.findings.append(
                        ArchitectureFinding(
                            "unresolved-sensitive-provenance",
                            f"callback:{spelling}",
                            keyword.value.lineno,
                        )
                    )
        return tuple(references)

    def _is_globals_mapping(self, node: ast.AST, scope: _Scope) -> bool:
        if isinstance(node, ast.Starred):
            return self._is_globals_mapping(node.value, scope)
        if isinstance(node, (ast.Tuple, ast.List)):
            return any(self._is_globals_mapping(item, scope) for item in node.elts)
        return bool(
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Call)
            and "builtins.globals"
            in self._resolve_expression(node.value.func, scope).direct_origins
        )

    def _mutation_target_value(
        self,
        node: ast.expr,
        scope: _Scope,
        *,
        include_names: bool,
        include_retrieved_subscript: bool = False,
    ) -> ResolvedValue:
        if isinstance(node, ast.Starred):
            return self._mutation_target_value(
                node.value,
                scope,
                include_names=include_names,
                include_retrieved_subscript=include_retrieved_subscript,
            )
        if isinstance(node, (ast.Tuple, ast.List)):
            return _merge_values(
                tuple(
                    self._mutation_target_value(
                        item,
                        scope,
                        include_names=include_names,
                        include_retrieved_subscript=include_retrieved_subscript,
                    )
                    for item in node.elts
                )
            )
        if isinstance(node, ast.Subscript):
            receiver = self._resolve_expression(node.value, scope)
            if (
                isinstance(node.value, ast.Subscript)
                and isinstance(node.value.value, ast.Name)
                and not receiver.temporally_derived
            ):
                lexical_container = self._lookup_value(
                    scope,
                    node.value.value.id,
                    node.value.value.lineno,
                    node.value.value.col_offset,
                )
                lexical_receiver = self._flow_subscript_value(
                    lexical_container,
                    node.value.slice,
                )
                if lexical_receiver.sensitive_unknown:
                    receiver = receiver._replace(sensitive_unknown=True)
            if (
                isinstance(node.value, ast.Name)
                and receiver.locations
                and not receiver.location_uncertain
                and not receiver.direct_origins
                and not receiver.reachability_overflow
            ):
                receiver = receiver._replace(
                    is_unknown=False,
                    sensitive_unknown=False,
                )
            elif isinstance(node.value, ast.Name) and any(
                self._is_iteration_derived_alias(alias)
                for alias in scope.aliases.get(node.value.id, ())
            ):
                lexical_receiver = self._lookup_value(
                    scope,
                    node.value.id,
                    node.value.lineno,
                    node.value.col_offset,
                )
                if lexical_receiver.sensitive_unknown:
                    receiver = receiver._replace(sensitive_unknown=True)
            if receiver.is_unknown:
                receiver = receiver._replace(sensitive_unknown=True)
            if self._is_unresolved_bare_parameter(
                node.value,
                scope,
                receiver,
                self.sensitive_parameter_bindings,
            ):
                receiver = receiver._replace(sensitive_unknown=True)
            if include_retrieved_subscript:
                return _merge_values((receiver, self._resolve_expression(node, scope)))
            return receiver
        if isinstance(node, ast.Attribute):
            target = self._resolve_expression(node, scope)
            owner = self._resolve_expression(node.value, scope)
            if self._is_unresolved_bare_parameter(
                node.value,
                scope,
                owner,
                self.sensitive_parameter_bindings,
            ):
                target = target._replace(sensitive_unknown=True)
            return target
        if include_names and isinstance(node, ast.Name):
            target = self._lookup_value(
                scope,
                node.id,
                node.lineno,
                node.col_offset,
            )
            if self._is_unresolved_bare_parameter(
                node,
                scope,
                target,
                self.sensitive_parameter_bindings,
            ):
                target = target._replace(sensitive_unknown=True)
            return target
        return ResolvedValue()

    def _mutation_target_origins(
        self,
        node: ast.expr,
        scope: _Scope,
        *,
        include_names: bool,
        include_retrieved_subscript: bool = False,
    ) -> frozenset[str]:
        return self._mutation_target_value(
            node,
            scope,
            include_names=include_names,
            include_retrieved_subscript=include_retrieved_subscript,
        ).direct_origins

    def _unresolved_site_is_approved(
        self,
        scope: tuple[str, ...],
        spelling: str,
    ) -> bool:
        if self.module_name == RETURNED_RUN_MODULE_NAME:
            return any(
                approved_scope == scope and approved_spelling == spelling
                for approved_scope, approved_spelling, _count in (
                    AUTHORIZED_RETURNED_RUN_UNRESOLVED_CALL_COUNTS
                )
            )
        if self.module_name == CALIBRATION_SELECTOR_REPLAY_MODULE_NAME:
            return (scope, spelling) in AUTHORIZED_SELECTOR_REPLAY_UNRESOLVED_CALLS
        return False

    def _unresolved_mutation_target_is_approved(
        self,
        scope: tuple[str, ...],
        spelling: str,
    ) -> bool:
        return self.module_name == RETURNED_RUN_MODULE_NAME and any(
            approved_scope == scope and approved_spelling == spelling
            for approved_scope, approved_spelling, _count in (
                AUTHORIZED_RETURNED_RUN_UNRESOLVED_MUTATION_COUNTS
            )
        )

    def _find_dynamic_behavior(self) -> None:
        for scope in self.scopes:
            for name, _kind, lineno in scope.events:
                if _is_forbidden_binding_name(name):
                    self.findings.append(
                        ArchitectureFinding("forbidden-later-stage-binding", name, lineno)
                    )
        for exported in sorted(self.exports):
            exported_value = self._lookup_value(self.module_scope, exported)
            structured = bool(
                exported_value.sequence_kind is not None
                or exported_value.mapping_entries is not None
            )
            if (
                exported_value.sensitive_unknown
                or exported_value.is_unknown
                or (structured and exported_value.aggregate_origins)
                or _is_forbidden_binding_name(exported)
            ):
                self.findings.append(
                    ArchitectureFinding(
                        "unresolved-sensitive-provenance",
                        f"export:{exported}",
                        self.module_scope.lines.get("__all__", 0),
                    )
                )
        for call in self.calls:
            for target in call.targets:
                if _qualified_call_target_is_forbidden(target):
                    self.findings.append(
                        ArchitectureFinding(
                            "forbidden-qualified-call",
                            target,
                            call.lineno,
                        )
                    )
                if target in {
                    "builtins.__import__",
                    "builtins.compile",
                    "builtins.delattr",
                    "builtins.eval",
                    "builtins.exec",
                    "builtins.getattr",
                    "builtins.globals",
                    "builtins.hasattr",
                    "builtins.locals",
                    "builtins.setattr",
                    "builtins.vars",
                } or target.startswith("importlib."):
                    self.findings.append(ArchitectureFinding("dynamic-call", target, call.lineno))
            if call.dynamic:
                self.findings.append(
                    ArchitectureFinding("unresolved-call-alias", call.spelling, call.lineno)
                )
            if call.sensitive_unresolved and not self._unresolved_site_is_approved(
                call.scope,
                call.spelling,
            ):
                self.findings.append(
                    ArchitectureFinding(
                        "unresolved-sensitive-provenance",
                        f"call:{call.spelling}",
                        call.lineno,
                    )
                )
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                scope = self.node_scopes.get(id(node), self.module_scope)
                call_value = self._resolve_expression(node.func, scope)
                call_targets = call_value.direct_origins
                if (
                    "builtins.type" in call_targets
                    and not (
                        len(node.args) == 1
                        and not isinstance(node.args[0], ast.Starred)
                        and not node.keywords
                    )
                ) or not call_targets.isdisjoint(
                    {
                        "builtins.type.__call__",
                        "builtins.type.__new__",
                        "dataclasses.make_dataclass",
                        "types.new_class",
                    }
                ):
                    self.findings.append(
                        ArchitectureFinding(
                            "dynamic-class",
                            ast.unparse(node.func),
                            node.lineno,
                        )
                    )
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr
                    in _REGISTRY_MUTATION_ATTRIBUTES | _BUILTIN_MUTATION_ATTRIBUTES
                ):
                    receiver = self._resolve_expression(node.func.value, scope)
                    receiver_is_sensitive = receiver.sensitive_unknown or (
                        receiver.is_unknown and isinstance(node.func.value, ast.Attribute)
                    )
                    if receiver_is_sensitive and not self._unresolved_site_is_approved(
                        scope.path, ast.unparse(node.func)
                    ):
                        self.findings.append(
                            ArchitectureFinding(
                                "unresolved-sensitive-provenance",
                                f"mutation:{ast.unparse(node.func.value)}",
                                node.lineno,
                            )
                        )
                    elif receiver.direct_origins and all(
                        not _qualified_call_target_is_forbidden(target) for target in call_targets
                    ):
                        self.findings.append(
                            ArchitectureFinding(
                                "qualified-state-mutation",
                                ",".join(sorted(receiver.direct_origins)),
                                node.lineno,
                            )
                        )
                continue
            if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete)):
                continue
            scope = self.node_scopes.get(id(node), self.module_scope)
            if isinstance(node, ast.Assign):
                assignment_targets: tuple[ast.expr, ...] = tuple(node.targets)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                assignment_targets = (node.target,)
            else:
                assignment_targets = tuple(node.targets)
            if (
                scope is self.module_scope
                and any(
                    isinstance(target, ast.Name) and target.id == "__all__"
                    for target in assignment_targets
                )
                and isinstance(node, (ast.AugAssign, ast.Delete))
            ):
                self.findings.append(ArchitectureFinding("dynamic-__all__", "__all__", node.lineno))
            if any(self._is_globals_mapping(target, scope) for target in assignment_targets):
                self.findings.append(
                    ArchitectureFinding(
                        "dynamic-module-mutation",
                        "globals()",
                        node.lineno,
                    )
                )
            mutation_targets = tuple(
                (
                    target,
                    self._mutation_target_value(
                        target,
                        scope,
                        include_names=isinstance(node, (ast.AugAssign, ast.Delete)),
                        include_retrieved_subscript=isinstance(node, ast.AugAssign),
                    ),
                )
                for target in assignment_targets
            )
            reported_scope = self._reported_scope_path(scope)
            mutation_value = _merge_values(tuple(value for _target, value in mutation_targets))
            mutation_origins = mutation_value.direct_origins
            if mutation_origins:
                self.findings.append(
                    ArchitectureFinding(
                        "qualified-state-mutation",
                        ",".join(sorted(mutation_origins)),
                        node.lineno,
                    )
                )
            sensitive_targets = (
                ()
                if isinstance(node, ast.Delete)
                and all(isinstance(target, ast.Name) for target in assignment_targets)
                else tuple(target for target, value in mutation_targets if value.sensitive_unknown)
            )
            unresolved_targets = (
                ()
                if isinstance(node, ast.Delete)
                and all(isinstance(target, ast.Name) for target in assignment_targets)
                else tuple(
                    target
                    for target, value in mutation_targets
                    if value.sensitive_unknown
                    or self._unresolved_mutation_target_is_approved(
                        reported_scope,
                        ast.unparse(target),
                    )
                )
            )
            self.unresolved_mutations.extend(
                ResolvedMutation(reported_scope, ast.unparse(target), node.lineno)
                for target in unresolved_targets
            )
            unapproved_sensitive_targets = tuple(
                target
                for target in sensitive_targets
                if not self._unresolved_mutation_target_is_approved(
                    reported_scope,
                    ast.unparse(target),
                )
            )
            if unapproved_sensitive_targets:
                self.findings.append(
                    ArchitectureFinding(
                        "unresolved-sensitive-provenance",
                        "mutation:"
                        + ",".join(ast.unparse(target) for target in unapproved_sensitive_targets),
                        node.lineno,
                    )
                )

    def analysis(self) -> QualifiedSymbolAnalysis:
        def reported_binding_value(scope: _Scope, name: str) -> ResolvedValue:
            if _is_forbidden_binding_name(name):
                flow_state = self.flow_final_states.get(id(scope))
                if flow_state is not None and name in dict(flow_state.bindings):
                    return self._materialize_flow_value(
                        dict(flow_state.bindings)[name],
                        flow_state.store,
                    )
            return scope.values.get(name, ResolvedValue())

        bindings = tuple(
            SymbolBinding(
                scope.path,
                name,
                "+".join(sorted(kinds)),
                reported_binding_value(scope, name).direct_origins,
                scope.lines[name],
                scope is self.module_scope,
            )
            for scope in self.scopes
            for name, kinds in scope.kinds.items()
        )
        binding_events = tuple(
            SymbolBinding(
                scope.path,
                name,
                kind,
                reported_binding_value(scope, name).direct_origins,
                lineno,
                scope is self.module_scope,
            )
            for scope in self.scopes
            for name, kind, lineno in scope.events
        )
        return QualifiedSymbolAnalysis(
            imports=tuple(self.imports),
            bindings=bindings,
            binding_events=binding_events,
            calls=self.calls,
            references=self.references,
            unresolved_mutations=tuple(self.unresolved_mutations),
            exports=frozenset(self.exports),
            findings=tuple(self.findings),
            source_text=self.source,
            module_name=self.module_name,
        )


def analyze_qualified_symbols(
    source: str,
    *,
    module_name: str = RETURNED_RUN_MODULE_NAME,
) -> QualifiedSymbolAnalysis:
    """Return a fail-closed qualified-symbol analysis without importing source."""

    return _QualifiedSymbolAnalyzer(source, module_name).analysis()


def top_level_class_names(source: str) -> set[str]:
    """Discover actual top-level classes without defining expected authority."""

    return {node.name for node in ast.parse(source).body if isinstance(node, ast.ClassDef)}


def imported_module_roots(source: str) -> set[str]:
    """Return the first component of every actual import in source."""

    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            roots.add(node.module.split(".")[0])
    return roots


def called_function_names(source: str) -> set[str]:
    """Return simple and attribute call names used by the production module."""

    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def dynamic_projection_class_assignments(source: str) -> set[str]:
    """Detect projection names assigned from runtime class factories."""

    discovered: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        targets: tuple[ast.expr, ...]
        value: ast.expr | None
        if isinstance(node, ast.Assign):
            targets, value = tuple(node.targets), node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = (node.target,), node.value
        else:
            continue
        if not isinstance(value, ast.Call):
            continue
        factory = value.func.id if isinstance(value.func, ast.Name) else None
        if factory not in {"type", "make_dataclass", "new_class"}:
            continue
        discovered.update(
            target.id
            for target in targets
            if isinstance(target, ast.Name) and "Projection" in target.id
        )
    return discovered


def is_exact_authorized_top_level_class_set(classes: set[str]) -> bool:
    """Require exact equality with the explicit test-owned stage model."""

    return classes == set(AUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES)


def current_stage_manifest_regression_checks() -> tuple[tuple[str, bool], ...]:
    """Exercise exact, missing, added, replaced, and named future-stage cases."""

    expected = set(AUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES)
    removed = "RunArmActionProjection"
    checks: list[tuple[str, bool]] = [
        (
            "exact-current-stage",
            len(expected) == EXPECTED_AUTHORIZED_TOP_LEVEL_CLASS_COUNT
            and is_exact_authorized_top_level_class_set(expected),
        ),
        (
            "missing-expected-class",
            not is_exact_authorized_top_level_class_set(expected - {removed}),
        ),
        (
            "unexpected-class",
            not is_exact_authorized_top_level_class_set(
                expected | {"RunUnexpectedStage2Projection"}
            ),
        ),
        (
            "replaced-expected-class",
            not is_exact_authorized_top_level_class_set(
                (expected - {removed}) | {"RunReplacementStage2Projection"}
            ),
        ),
    ]
    checks.extend(
        (
            f"current-stage-rejects-{name}",
            name not in expected and not is_exact_authorized_top_level_class_set(expected | {name}),
        )
        for name in sorted(CURRENT_STAGE_UNAUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES)
    )
    return tuple(checks)


def forbidden_source_or_ast_patterns() -> frozenset[str]:
    """Return permanent and explicit current-stage source prohibitions."""

    return (
        PERMANENT_FORBIDDEN_SOURCE_OR_AST_PATTERNS | CURRENT_STAGE_FORBIDDEN_SOURCE_OR_AST_PATTERNS
    )


def imports_are_authorized(imports: set[str]) -> bool:
    """Apply the exact allow-list plus permanent and current-stage deny-lists."""

    return (
        imports <= AUTHORIZED_PROJECTION_MODULE_IMPORTS
        and imports.isdisjoint(PERMANENT_FORBIDDEN_IMPORTS)
        and imports.isdisjoint(CURRENT_STAGE_FORBIDDEN_IMPORTS)
    )


# These exceptions are deliberately path- and imported-name-specific.  They do
# not weaken the permanent ``hashlib`` or ``sha256`` prohibitions applied to the
# returned-run module or any other projection module.
RETURNED_RUN_RELATIVE_PATH: Final = "research_decision_engine/benchmarks/broader_returned_run.py"
CALIBRATION_SELECTOR_REPLAY_RELATIVE_PATH: Final = (
    "research_decision_engine/benchmarks/broader_calibration_selector_replay.py"
)

AUTHORIZED_RETURNED_RUN_TOP_LEVEL_FUNCTIONS: Final[frozenset[str]] = frozenset(
    """
    _fail
    _structural
    _scientific
    _missing_context
    validate_returned_run_projection_shape
    _projection_list
    _projection_child
    _provenance_value_mapping
    _provenance_mapping
    _candidate_mapping
    _experiment_mapping
    _evidence_mapping
    _belief_state_mapping
    _likelihood_mapping
    _update_mapping
    _matched_effect_mapping
    _sigma_estimate_mapping
    _model_belief_state_mapping
    _lineage_mapping
    _predictive_interval_mapping
    _diagnostic_mapping
    _model_update_mapping
    _observation_authorization_mapping
    _revealed_observation_mapping
    _calibration_estimate_mapping
    _calibration_mapping
    _control_value_mapping
    _controlled_variables_mapping
    _public_design_mapping
    _hypothesis_decision_context_mapping
    _candidate_score_mapping
    _decision_trace_mapping
    _probability_pairs_mapping
    _projection_sequence_mapping
    _lookahead_second_action_mapping
    _lookahead_branch_mapping
    _lookahead_first_action_mapping
    _lookahead_alternative_mapping
    _lookahead_trace_mapping
    _policy_trace_mapping
    _arm_decision_mapping
    _arm_action_mapping
    _arm_value_mapping
    _returned_run_mapping
    projection_as_dict
    _closed_dict
    _list
    _string
    _is_structurally_admitted_string
    _id
    _i64
    _bool
    _optional_id
    _optional_string
    _optional_i64
    _authorization_kind
    _arm_value
    _run_status
    _returned_run_schema_version
    _public_action_effect
    _non_stop_public_action_effect
    _h64
    _hexbytes
    _effect_source_kind
    _f64_text
    _float_from_f64
    _project_float
    _decoded_items
    _optional_f64
    _decoded_residuals
    _decoded_controlled_variables
    _decoded_probability_pairs
    _projected_items
    _flat_record
    _decode_flat
    project_provenance_value
    decode_provenance_value_projection
    provenance_value_from_projection
    project_provenance
    project_candidate
    project_completed_experiment
    project_evidence
    project_belief_state
    project_hypothesis_likelihood
    project_belief_update
    _checked_projection
    _checked_scientific_projection
    project_matched_effect
    _project_matched_effect
    _project_optional_float
    project_sigma_estimate
    _project_sigma_estimate
    project_model_belief_state
    project_lineage
    project_predictive_interval
    project_diagnostic
    _project_diagnostic
    project_model_update
    _project_model_update
    project_control_value
    _project_controlled_variables
    project_public_experiment_design
    project_hypothesis_decision_context
    project_candidate_score
    project_decision_trace
    _project_probability_pairs
    _lf64
    project_lookahead_second_action
    _project_lookahead_second_action
    _validate_evidence_bound_coupling
    _project_lookahead_branch
    project_lookahead_branch
    _project_lookahead_first_action
    project_lookahead_first_action
    project_lookahead_alternative
    _project_lookahead_alternative
    _project_lookahead_trace
    project_lookahead_trace
    _project_policy_trace
    project_policy_trace
    _validate_unique_ids
    _validate_arm_decision_projection
    _project_revealed_observation
    _calibration_authorization
    _calibration_run_id
    _validate_calibration_estimate_projection
    _project_calibration_estimate
    project_calibration_estimate
    _project_calibration
    project_calibration
    _validate_arm_action_projection
    _project_arm_decision
    project_arm_decision
    _project_arm_action
    project_arm_action
    _project_returned_run
    project_returned_run
    decode_run_provenance_projection
    decode_run_candidate_projection
    decode_run_completed_experiment_projection
    decode_run_evidence_projection
    decode_run_belief_state_projection
    decode_run_hypothesis_likelihood_projection
    decode_run_belief_update_projection
    decode_run_matched_effect_projection
    decode_run_sigma_estimate_projection
    decode_run_model_belief_state_projection
    decode_run_lineage_projection
    decode_run_predictive_interval_projection
    decode_run_diagnostic_projection
    decode_run_model_update_projection
    decode_run_observation_authorization_projection
    decode_run_revealed_observation_projection
    decode_run_calibration_estimate_projection
    decode_run_calibration_projection
    decode_control_value_projection
    decode_run_public_experiment_design_projection
    decode_run_hypothesis_decision_context_projection
    decode_run_candidate_score_projection
    decode_run_decision_trace_projection
    decode_run_lookahead_second_action_projection
    decode_run_lookahead_branch_projection
    decode_run_lookahead_first_action_projection
    decode_run_lookahead_alternative_projection
    decode_run_lookahead_trace_projection
    decode_run_policy_trace_projection
    decode_run_arm_decision_projection
    decode_run_arm_action_projection
    decode_returned_run_projection
    _rebuild
    reconstruct_provenance
    reconstruct_candidate
    control_value_from_projection
    reconstruct_public_experiment_design
    reconstruct_hypothesis_decision_context
    reconstruct_candidate_score
    reconstruct_decision_trace
    reconstruct_lookahead_second_action
    _reconstruct_probability_pairs
    _from_lf64
    reconstruct_lookahead_branch
    reconstruct_lookahead_first_action
    reconstruct_lookahead_alternative
    reconstruct_lookahead_trace
    reconstruct_policy_trace
    _reconstruct_revealed_observation
    reconstruct_calibration_estimate
    _validate_calibration_projection
    reconstruct_calibration
    reconstruct_arm_decision
    reconstruct_arm_action
    reconstruct_completed_experiment
    _reconstruct_evidence
    reconstruct_evidence
    reconstruct_belief_state
    reconstruct_hypothesis_likelihood
    _same_f64
    _validate_belief_update_relations
    reconstruct_belief_update
    reconstruct_matched_effect
    _validate_sigma_coupling
    reconstruct_sigma_estimate
    reconstruct_model_belief_state
    reconstruct_lineage
    _reconstruct_predictive_interval
    reconstruct_predictive_interval
    _diagnostic_adequacy
    _reconstruct_diagnostic
    reconstruct_diagnostic
    reconstruct_model_update
    recompute_observation_authorization_id
    recompute_revealed_oracle_key_id
    recompute_revealed_outcome_digest
    recompute_revealed_oracle_use_id
    _validate_revealed_key_facts
    validate_revealed_observation_projection
    observation_authorization_projections_match
    revealed_observation_projections_match
    validate_observation_authorization_relation
    validate_revealed_observation_relations
    _scientific_call
    _policy_payload
    _returned_policy_occurrences
    _returned_decision_trace_occurrences
    _returned_lookahead_trace_occurrences
    _policy_candidate_occurrences
    _returned_candidate_occurrences
    _returned_diagnostic_occurrences
    _returned_sigma_occurrences
    _returned_evidence_occurrences
    _returned_belief_state_occurrences
    _returned_model_state_occurrences
    _returned_likelihood_occurrences
    _returned_interval_occurrences
    _returned_score_occurrences
    _returned_context_occurrences
    _returned_second_action_occurrences
    _returned_branch_occurrences
    _returned_first_action_occurrences
    _returned_alternative_occurrences
    _returned_design_occurrences
    _returned_provenance_occurrences
    _returned_control_value_occurrences
    _s1_probability_distribution
    _s1_probability_pair_distribution
    _s1_non_negative
    _s1_positive
    _validate_returned_run_s1_tags
    _validate_returned_run_s1_enums
    _validate_returned_run_s1_optional
    _validate_returned_run_s1_numeric
    _validate_returned_run_s1_pairs
    _s1_require_hypothesis_order
    _validate_returned_run_s1_sequences
    _validate_returned_run_s1
    _returned_observation_occurrences
    _calibration_observation_context
    _returned_observation_contexts
    _pure_revealed_observation
    _validate_returned_run_s6
    _returned_effect_occurrences
    _construct_returned_run_s2
    _sigma_from_s3
    _diagnostic_from_s3
    _construct_returned_run_s3
    _construct_returned_run_s4
    _construct_returned_run_s5
    _construct_calibration_estimate_s7
    _construct_returned_run_s7
    _arm_action_from_s8
    _arm_decision_from_s8
    _construct_returned_run_s8
    _validate_returned_run_s9
    _s10_calibration_effects
    _s10_candidate_occurrences
    _validate_returned_run_s10_updates
    _validate_returned_run_s10_replay
    _validate_returned_run_s10
    _terminal_reason_value
    _construct_returned_run_s7_stage
    _construct_returned_run_s8_stage
    _reraise_returned_run_batch_error
    _neutralize_returned_run_structure
    _validate_returned_run_projection_structure
    _prepare_returned_run_batch
    _reconstruct_returned_run_batch
    _validate_returned_run_relation_context
    _accepted_result_payload_sha256
    validate_returned_run_batch
    reconstruct_returned_run
    validate_returned_run_relation
    result_payload_sha256
    projection_matches_domain
    validate_completed_experiment_relation
    validate_evidence_relations
    validate_belief_state_relation
    validate_belief_update_relation
    _validate_expected_projection
    validate_matched_effect_relation
    validate_sigma_estimate_relation
    validate_model_belief_state_relation
    validate_lineage_relation
    validate_predictive_interval_relation
    validate_diagnostic_relation
    validate_model_update_relation
    _validate_calibration_observation_context
    validate_calibration_estimate_relation
    validate_calibration_relation
    validate_public_experiment_design_relation
    validate_hypothesis_decision_context_relation
    validate_candidate_score_relation
    validate_decision_trace_relation
    validate_lookahead_trace_relation
    validate_policy_trace_relation
    _validate_arm_decision_action_relation
    _validate_arm_decision_id
    validate_arm_decision_relation
    validate_arm_action_relation
    """.split()  # noqa: SIM905 - the one-name-per-line manifest is intentional.
)

EXPECTED_RETURNED_RUN_BATCH_STAGE_HELPERS: Final[tuple[tuple[str, str], ...]] = (
    ("S1", "_validate_returned_run_s1"),
    ("S2", "_construct_returned_run_s2"),
    ("S3", "_construct_returned_run_s3"),
    ("S4", "_construct_returned_run_s4"),
    ("S5", "_construct_returned_run_s5"),
    ("S6", "_validate_returned_run_s6"),
    ("S7", "_construct_returned_run_s7_stage"),
    ("S8", "_construct_returned_run_s8_stage"),
    ("S9", "_validate_returned_run_s9"),
    ("S10", "_validate_returned_run_s10"),
)
_RETURNED_RUN_BATCH_STAGE_HELPERS: Final[frozenset[str]] = frozenset(
    helper for _stage, helper in EXPECTED_RETURNED_RUN_BATCH_STAGE_HELPERS
)
_EXPECTED_RETURNED_RUN_BATCH_STAGE_BODIES: Final = """\
_validate_returned_run_s1::_validate_returned_run_s1(projection)
_construct_returned_run_s2::cache, completed, evidence = _construct_returned_run_s2(projection); caches.append(cache); completed_by_payload.append(completed); evidence_by_payload.append(evidence)
_construct_returned_run_s3::lineage, updates, diagnostics, effects, effect_map = _construct_returned_run_s3(projection, caches[index]); lineages.append(lineage); updates_by_payload.append(updates); diagnostics_by_payload.append(diagnostics); effects_by_payload.append(effects); effect_maps.append(effect_map)
_construct_returned_run_s4::_construct_returned_run_s4(projection, caches[index])
_construct_returned_run_s5::traces = _construct_returned_run_s5(projection, caches[index]); traces_by_payload.append(traces)
_validate_returned_run_s6::observations = _validate_returned_run_s6(projection); observations_by_payload.append(observations)
_construct_returned_run_s7_stage::calibration = _construct_returned_run_s7_stage(projection.calibration, observations_by_payload[index], effect_maps[index]); calibrations.append(calibration)
_construct_returned_run_s8_stage::run = _construct_returned_run_s8_stage(projection, completed=completed_by_payload[index], evidence=evidence_by_payload[index], lineage=lineages[index], updates=updates_by_payload[index], diagnostics=diagnostics_by_payload[index], effects=effects_by_payload[index], calibration=calibrations[index], observations=observations_by_payload[index], traces=traces_by_payload[index]); runs.append(run)
_validate_returned_run_s9::_validate_returned_run_s9(run)
_validate_returned_run_s10::_validate_returned_run_s10(run)"""  # noqa: E501
_APPROVED_RETURNED_RUN_PAYLOAD_HASH_DOMAIN: Final = "validation_evidence_returned_run_payload/v1"

AUTHORIZED_RETURNED_RUN_TOP_LEVEL_ASSIGNMENTS: Final[frozenset[str]] = frozenset(
    {
        "EXECUTION_RETURNED_SCIENTIFIC_RECORD_INVALID",
        "_MISSING_CONTEXT",
        "_CANDIDATE_SCHEMA",
        "_EXPERIMENT_SCHEMA",
        "_EVIDENCE_SCHEMA",
        "_BELIEF_SCHEMA",
        "_LIKELIHOOD_SCHEMA",
        "_UPDATE_SCHEMA",
        "_OBSERVATION_AUTHORIZATION_SCHEMA",
        "_REVEALED_OBSERVATION_SCHEMA",
        "_CALIBRATION_ESTIMATE_SCHEMA",
        "_CALIBRATION_SCHEMA",
        "_PUBLIC_DESIGN_SCHEMA",
        "_HYPOTHESIS_DECISION_CONTEXT_SCHEMA",
        "_CANDIDATE_SCORE_SCHEMA",
        "_DECISION_TRACE_SCHEMA",
        "_LOOKAHEAD_SECOND_ACTION_SCHEMA",
        "_LOOKAHEAD_BRANCH_SCHEMA",
        "_LOOKAHEAD_FIRST_ACTION_SCHEMA",
        "_LOOKAHEAD_ALTERNATIVE_SCHEMA",
        "_LOOKAHEAD_TRACE_SCHEMA",
        "_ARM_DECISION_SCHEMA",
        "_ARM_ACTION_SCHEMA",
        "_RETURNED_RUN_SCHEMA",
        "_MATCHED_EFFECT_SCHEMA",
        "_SIGMA_ESTIMATE_SCHEMA",
        "_MODEL_BELIEF_STATE_SCHEMA",
        "_LINEAGE_SCHEMA",
        "_PREDICTIVE_INTERVAL_SCHEMA",
        "_DIAGNOSTIC_SCHEMA",
        "_MODEL_UPDATE_SCHEMA",
    }
)

AUTHORIZED_RETURNED_RUN_TYPE_ALIAS_VALUES: Final[tuple[tuple[str, str], ...]] = (
    (
        "ValidationCategory",
        "Literal['structural_projection_invalid', 'scientific_record_invalid', "
        "'missing_relation_context']",
    ),
    (
        "PublicActionEffect",
        "Literal['opens_pair', 'completes_pair', 'ineligible', 'stop']",
    ),
    (
        "NonStopPublicActionEffect",
        "Literal['opens_pair', 'completes_pair', 'ineligible']",
    ),
    ("RunArmValue", "tuple[str, int, str, str]"),
    ("FieldCheck", "Callable[[object, str], object]"),
    ("FlatSchema", "tuple[tuple[str, FieldCheck], ...]"),
    (
        "_ReturnedObservationContext",
        "tuple[RunRevealedObservationProjection, Literal['calibration', 'decision'], "
        "str, str, str]",
    ),
)

AUTHORIZED_RETURNED_RUN_TYPE_ALIASES: Final[frozenset[str]] = frozenset(
    name for name, _value in AUTHORIZED_RETURNED_RUN_TYPE_ALIAS_VALUES
)

_TOP_LEVEL_VALUE_BINDING_KINDS: Final[frozenset[str]] = frozenset(
    {
        "annassign",
        "assign",
        "exception-target",
        "loop-target",
        "match-target",
        "named-expression",
        "type-alias",
        "with-target",
    }
)

_RETURNED_RUN_BELIEF_IMPORTS: Final[tuple[str, ...]] = (
    "ADEQUACY_MINIMUM_RESIDUALS",
    "CALIBRATED_SIGMA_MODEL_ID",
    "CALIBRATED_SIGMA_MODEL_VERSION",
    "FIXED_SIGMA_MODEL_ID",
    "MINIMUM_PRIOR_EFFECTS",
    "RESIDUAL_ALARM_COUNT",
    "RESIDUAL_OUTLIER_THRESHOLD",
    "RESIDUAL_WINDOW_SIZE",
    "SIGMA_FLOOR",
    "TAIL_ALARM_THRESHOLD",
    "AdequacyState",
    "BeliefModelLineage",
    "EffectSourceKind",
    "MatchedEffectObservation",
    "ModelAdequacyDiagnostic",
    "ModelBeliefState",
    "ModelBeliefUpdate",
    "PredictiveInterval",
    "SigmaEstimate",
    "SigmaEstimateStatus",
    "belief_model",
)
_RETURNED_RUN_LOOKAHEAD_IMPORTS: Final[tuple[str, ...]] = (
    "NO_EVIDENCE_BRANCH_ID",
    "NO_EVIDENCE_BRANCH_LABEL",
    "LookaheadAlternative",
    "LookaheadBranch",
    "LookaheadFirstActionPlan",
    "LookaheadPlanTrace",
    "LookaheadSecondAction",
)
_RETURNED_RUN_REASONING_IMPORTS: Final[tuple[str, ...]] = (
    "PROBABILITY_TOLERANCE",
    "BeliefState",
    "BeliefUpdate",
    "Evidence",
    "HypothesisLikelihood",
    "Provenance",
    "ProvenanceValue",
    "ReasoningError",
)
_RETURNED_RUN_RUNNER_IMPORTS: Final[tuple[str, ...]] = (
    "CALIBRATION_SIGMA_DDOF",
    "CALIBRATION_SOURCE_SEQUENCE_CUTOFF",
    "CREATED_AT",
    "GROUP_IDS",
    "ArmAction",
    "ArmDecision",
    "BroaderArmRun",
    "CalibrationDeployment",
    "CalibrationGroupEstimate",
    "RevealedObservation",
    "_decide",
    "_experiment_record_id",
    "_fixed_policy_match",
    "arm_spec",
    "calibration_sigma_provenance_sha256",
    "comparison_identity",
    "initial_lineage_for",
    "run_identity",
    "terminal_reason_for",
    "validate_lineage_binding",
)
_RETURNED_RUN_WORLD_IMPORTS: Final[tuple[str, ...]] = (
    "BUDGETS",
    "CANDIDATE_CATALOG",
    "CANDIDATES_BY_ID",
    "WORLDS_BY_ID",
    "PublicFeasibilityState",
    "candidate_costs",
    "evidence_eligibility_contract",
    "hidden_arm_mean",
    "hidden_observation_sigma",
)

AUTHORIZED_RETURNED_RUN_IMPORT_BINDINGS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("math", "math"),
        ("statistics", "statistics"),
        ("struct", "struct"),
        ("unicodedata", "unicodedata"),
        ("Callable", "collections.abc.Callable"),
        ("dataclass", "dataclasses.dataclass"),
        ("replace", "dataclasses.replace"),
        ("Final", "typing.Final"),
        ("Literal", "typing.Literal"),
        ("Never", "typing.Never"),
        ("cast", "typing.cast"),
        (
            "FrozenArm",
            "research_decision_engine.benchmarks.broader_protocol.FrozenArm",
        ),
        (
            "build_candidate_group_prediction_adapter",
            "research_decision_engine.closed_loop.build_candidate_group_prediction_adapter",
        ),
        ("CandidateScore", "research_decision_engine.decision.CandidateScore"),
        ("DecisionTrace", "research_decision_engine.decision.DecisionTrace"),
        (
            "HypothesisDecisionContext",
            "research_decision_engine.decision.HypothesisDecisionContext",
        ),
        (
            "DomainControlValue",
            "research_decision_engine.evidence_eligibility.ControlValue",
        ),
        (
            "MatchedExperimentPair",
            "research_decision_engine.evidence_eligibility.MatchedExperimentPair",
        ),
        (
            "PublicExperimentDesign",
            "research_decision_engine.evidence_eligibility.PublicExperimentDesign",
        ),
        (
            "ADAM_ADVANTAGE_ID",
            "research_decision_engine.optimizer_effect.ADAM_ADVANTAGE_ID",
        ),
        (
            "NO_ADVANTAGE_ID",
            "research_decision_engine.optimizer_effect.NO_ADVANTAGE_ID",
        ),
        (
            "SGD_ADVANTAGE_ID",
            "research_decision_engine.optimizer_effect.SGD_ADVANTAGE_ID",
        ),
        (
            "evidence_from_matched_pair",
            "research_decision_engine.optimizer_effect.evidence_from_matched_pair",
        ),
        ("Candidate", "research_decision_engine.types.Candidate"),
        ("CompletedExperiment", "research_decision_engine.types.CompletedExperiment"),
        (
            "CALIBRATION_ELIGIBILITY_BASIS",
            "research_decision_engine.benchmarks.broader_calibration_history.CALIBRATION_ELIGIBILITY_BASIS",
        ),
        (
            "CALIBRATION_SELECTION_VERSION",
            "research_decision_engine.benchmarks.broader_calibration_history.CALIBRATION_SELECTION_VERSION",
        ),
        (
            "expected_calibration_effect",
            "research_decision_engine.benchmarks.broader_calibration_history.expected_calibration_effect",
        ),
        (
            "replay_calibration_history_selection",
            "research_decision_engine.benchmarks.broader_calibration_selector_replay.replay_calibration_history_selection",
        ),
        (
            "raw_effect_sha256",
            "research_decision_engine.benchmarks.broader_calibration_selector_replay.raw_effect_sha256",
        ),
        (
            "CALIBRATION_NAMESPACE",
            "research_decision_engine.benchmarks.broader_oracle.CALIBRATION_NAMESPACE",
        ),
        ("OracleError", "research_decision_engine.benchmarks.broader_oracle.OracleError"),
        (
            "_parse_calibration_candidate",
            "research_decision_engine.benchmarks.broader_oracle._parse_calibration_candidate",
        ),
        (
            "calibration_key",
            "research_decision_engine.benchmarks.broader_oracle.calibration_key",
        ),
        ("decision_key", "research_decision_engine.benchmarks.broader_oracle.decision_key"),
        (
            "transform_key",
            "research_decision_engine.benchmarks.broader_oracle.transform_key",
        ),
        (
            "PROTOCOL_VERSION",
            "research_decision_engine.benchmarks.broader_protocol.PROTOCOL_VERSION",
        ),
        (
            "ProtocolError",
            "research_decision_engine.benchmarks.broader_protocol.ProtocolError",
        ),
        (
            "canonical_json_bytes",
            "research_decision_engine.benchmarks.broader_protocol.canonical_json_bytes",
        ),
        ("f64", "research_decision_engine.benchmarks.broader_protocol.f64"),
        (
            "protocol_hash",
            "research_decision_engine.benchmarks.broader_protocol.protocol_hash",
        ),
        ("runtime_id", "research_decision_engine.benchmarks.broader_protocol.runtime_id"),
    }
    | {
        (name, f"research_decision_engine.belief_models.{name}")
        for name in _RETURNED_RUN_BELIEF_IMPORTS
    }
    | {
        (name, f"research_decision_engine.lookahead.{name}")
        for name in _RETURNED_RUN_LOOKAHEAD_IMPORTS
    }
    | {
        (name, f"research_decision_engine.reasoning.{name}")
        for name in _RETURNED_RUN_REASONING_IMPORTS
    }
    | {
        (name, f"research_decision_engine.benchmarks.broader_runner.{name}")
        for name in _RETURNED_RUN_RUNNER_IMPORTS
    }
    | {
        (name, f"research_decision_engine.benchmarks.broader_worlds.{name}")
        for name in _RETURNED_RUN_WORLD_IMPORTS
    }
)

AUTHORIZED_SELECTOR_REPLAY_IMPORT_BINDINGS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("hashlib", "hashlib"),
        ("statistics", "statistics"),
        ("TYPE_CHECKING", "typing.TYPE_CHECKING"),
        ("SIGMA_FLOOR", "research_decision_engine.belief_models.SIGMA_FLOOR"),
        (
            "MatchedEffectObservation",
            "research_decision_engine.belief_models.MatchedEffectObservation",
        ),
        (
            "CALIBRATION_ELIGIBILITY_BASIS",
            "research_decision_engine.benchmarks.broader_calibration_history.CALIBRATION_ELIGIBILITY_BASIS",
        ),
        (
            "CALIBRATION_SELECTION_VERSION",
            "research_decision_engine.benchmarks.broader_calibration_history.CALIBRATION_SELECTION_VERSION",
        ),
        (
            "CALIBRATION_SIGMA_DDOF",
            "research_decision_engine.benchmarks.broader_calibration_history.CALIBRATION_SIGMA_DDOF",
        ),
        (
            "CALIBRATION_SOURCE_SEQUENCE_CUTOFF",
            "research_decision_engine.benchmarks.broader_calibration_history.CALIBRATION_SOURCE_SEQUENCE_CUTOFF",
        ),
        (
            "CalibrationHistorySelection",
            "research_decision_engine.benchmarks.broader_calibration_history.CalibrationHistorySelection",
        ),
        (
            "RunProvenanceError",
            "research_decision_engine.benchmarks.broader_calibration_history.RunProvenanceError",
        ),
        (
            "_validate_effects",
            "research_decision_engine.benchmarks.broader_calibration_history._validate_effects",
        ),
        (
            "_validate_observations",
            "research_decision_engine.benchmarks.broader_calibration_history._validate_observations",
        ),
        (
            "CALIBRATION_NAMESPACE",
            "research_decision_engine.benchmarks.broader_oracle.CALIBRATION_NAMESPACE",
        ),
        (
            "RevealedObservation",
            "research_decision_engine.benchmarks.broader_oracle.RevealedObservation",
        ),
        (
            "PROTOCOL_VERSION",
            "research_decision_engine.benchmarks.broader_protocol.PROTOCOL_VERSION",
        ),
        (
            "canonical_json_bytes",
            "research_decision_engine.benchmarks.broader_protocol.canonical_json_bytes",
        ),
        ("f64", "research_decision_engine.benchmarks.broader_protocol.f64"),
        (
            "protocol_hash",
            "research_decision_engine.benchmarks.broader_protocol.protocol_hash",
        ),
    }
)

AUTHORIZED_SELECTOR_REPLAY_TOP_LEVEL_BINDING_KINDS: Final[frozenset[tuple[str, str]]] = frozenset(
    {(name, "import") for name, _origin in AUTHORIZED_SELECTOR_REPLAY_IMPORT_BINDINGS}
    | {
        ("raw_effect_sha256", "function"),
        ("replay_calibration_history_selection", "function"),
    }
)

AUTHORIZED_RETURNED_RUN_EXTERNAL_CALLS: Final[frozenset[str]] = frozenset(
    {
        "dataclasses.dataclass",
        "dataclasses.replace",
        "math.fsum",
        "math.isclose",
        "math.log",
        "math.sqrt",
        "statistics.mean",
        "statistics.stdev",
        "struct.unpack",
        "typing.cast",
        "unicodedata.normalize",
        "research_decision_engine.belief_models.MatchedEffectObservation.from_decision",
        "research_decision_engine.belief_models.belief_model",
        "research_decision_engine.benchmarks.broader_calibration_history.expected_calibration_effect",
        "research_decision_engine.benchmarks.broader_calibration_selector_replay.raw_effect_sha256",
        "research_decision_engine.benchmarks.broader_oracle._parse_calibration_candidate",
        "research_decision_engine.benchmarks.broader_oracle.calibration_key",
        "research_decision_engine.benchmarks.broader_oracle.decision_key",
        "research_decision_engine.benchmarks.broader_oracle.transform_key",
        "research_decision_engine.benchmarks.broader_protocol.canonical_json_bytes",
        "research_decision_engine.benchmarks.broader_protocol.f64",
        "research_decision_engine.benchmarks.broader_protocol.protocol_hash",
        "research_decision_engine.benchmarks.broader_protocol.runtime_id",
        "research_decision_engine.benchmarks.broader_runner.ArmAction",
        "research_decision_engine.benchmarks.broader_runner.ArmDecision",
        "research_decision_engine.benchmarks.broader_runner.BroaderArmRun",
        "research_decision_engine.benchmarks.broader_runner.CalibrationDeployment",
        "research_decision_engine.benchmarks.broader_runner.CalibrationGroupEstimate",
        "research_decision_engine.benchmarks.broader_runner.RevealedObservation",
        "research_decision_engine.benchmarks.broader_runner._decide",
        "research_decision_engine.benchmarks.broader_runner._experiment_record_id",
        "research_decision_engine.benchmarks.broader_runner._fixed_policy_match",
        "research_decision_engine.benchmarks.broader_runner.arm_spec",
        "research_decision_engine.benchmarks.broader_runner.calibration_sigma_provenance_sha256",
        "research_decision_engine.benchmarks.broader_runner.comparison_identity",
        "research_decision_engine.benchmarks.broader_runner.initial_lineage_for",
        "research_decision_engine.benchmarks.broader_runner.run_identity",
        "research_decision_engine.benchmarks.broader_runner.terminal_reason_for",
        "research_decision_engine.benchmarks.broader_runner.validate_lineage_binding",
        "research_decision_engine.benchmarks.broader_worlds.PublicFeasibilityState",
        "research_decision_engine.benchmarks.broader_worlds.candidate_costs",
        "research_decision_engine.benchmarks.broader_worlds.evidence_eligibility_contract",
        "research_decision_engine.benchmarks.broader_worlds.hidden_arm_mean",
        "research_decision_engine.benchmarks.broader_worlds.hidden_observation_sigma",
        "research_decision_engine.closed_loop.build_candidate_group_prediction_adapter",
        "research_decision_engine.optimizer_effect.evidence_from_matched_pair",
        "research_decision_engine.types.CompletedExperiment",
    }
)

AUTHORIZED_RETURNED_RUN_EXTERNAL_CALL_COUNTS: Final[tuple[tuple[str, int], ...]] = (
    ("dataclasses.dataclass", 33),
    ("dataclasses.replace", 2),
    ("math.fsum", 8),
    ("math.isclose", 5),
    ("math.log", 1),
    ("math.sqrt", 1),
    ("research_decision_engine.belief_models.MatchedEffectObservation.from_decision", 2),
    ("research_decision_engine.belief_models.belief_model", 2),
    (
        "research_decision_engine.benchmarks.broader_calibration_history."
        "expected_calibration_effect",
        1,
    ),
    (
        "research_decision_engine.benchmarks.broader_calibration_selector_replay.raw_effect_sha256",
        1,
    ),
    ("research_decision_engine.benchmarks.broader_oracle._parse_calibration_candidate", 1),
    ("research_decision_engine.benchmarks.broader_oracle.calibration_key", 1),
    ("research_decision_engine.benchmarks.broader_oracle.decision_key", 1),
    ("research_decision_engine.benchmarks.broader_oracle.transform_key", 1),
    ("research_decision_engine.benchmarks.broader_protocol.canonical_json_bytes", 1),
    ("research_decision_engine.benchmarks.broader_protocol.f64", 27),
    ("research_decision_engine.benchmarks.broader_protocol.protocol_hash", 4),
    ("research_decision_engine.benchmarks.broader_protocol.runtime_id", 3),
    ("research_decision_engine.benchmarks.broader_runner.ArmAction", 1),
    ("research_decision_engine.benchmarks.broader_runner.ArmDecision", 1),
    ("research_decision_engine.benchmarks.broader_runner.BroaderArmRun", 1),
    ("research_decision_engine.benchmarks.broader_runner.CalibrationDeployment", 1),
    ("research_decision_engine.benchmarks.broader_runner.CalibrationGroupEstimate", 1),
    ("research_decision_engine.benchmarks.broader_runner.RevealedObservation", 1),
    ("research_decision_engine.benchmarks.broader_runner._decide", 1),
    ("research_decision_engine.benchmarks.broader_runner._experiment_record_id", 1),
    ("research_decision_engine.benchmarks.broader_runner._fixed_policy_match", 1),
    ("research_decision_engine.benchmarks.broader_runner.arm_spec", 1),
    (
        "research_decision_engine.benchmarks.broader_runner.calibration_sigma_provenance_sha256",
        2,
    ),
    ("research_decision_engine.benchmarks.broader_runner.comparison_identity", 1),
    ("research_decision_engine.benchmarks.broader_runner.initial_lineage_for", 1),
    ("research_decision_engine.benchmarks.broader_runner.run_identity", 1),
    ("research_decision_engine.benchmarks.broader_runner.terminal_reason_for", 1),
    ("research_decision_engine.benchmarks.broader_runner.validate_lineage_binding", 2),
    ("research_decision_engine.benchmarks.broader_worlds.PublicFeasibilityState", 3),
    ("research_decision_engine.benchmarks.broader_worlds.candidate_costs", 4),
    ("research_decision_engine.benchmarks.broader_worlds.evidence_eligibility_contract", 1),
    ("research_decision_engine.benchmarks.broader_worlds.hidden_arm_mean", 1),
    ("research_decision_engine.benchmarks.broader_worlds.hidden_observation_sigma", 1),
    (
        "research_decision_engine.closed_loop.build_candidate_group_prediction_adapter",
        1,
    ),
    ("research_decision_engine.optimizer_effect.evidence_from_matched_pair", 1),
    ("research_decision_engine.types.CompletedExperiment", 1),
    ("statistics.mean", 2),
    ("statistics.stdev", 2),
    ("struct.unpack", 2),
    ("typing.cast", 41),
    ("unicodedata.normalize", 2),
)

SENSITIVE_APPROVED_QUALIFIED_TARGETS: Final[frozenset[str]] = frozenset(
    {
        "research_decision_engine.belief_models.belief_model",
        "research_decision_engine.benchmarks.broader_runner._decide",
        "research_decision_engine.benchmarks.broader_runner._fixed_policy_match",
        "research_decision_engine.closed_loop.build_candidate_group_prediction_adapter",
    }
)

AUTHORIZED_SENSITIVE_APPROVED_SITES: Final[tuple[tuple[tuple[str, ...], str, int], ...]] = (
    (
        ("_validate_returned_run_s10_replay",),
        "research_decision_engine.benchmarks.broader_runner._decide",
        1,
    ),
    (
        ("_validate_returned_run_s10_replay",),
        "research_decision_engine.benchmarks.broader_runner._fixed_policy_match",
        1,
    ),
    (
        ("_validate_returned_run_s10_replay",),
        "research_decision_engine.closed_loop.build_candidate_group_prediction_adapter",
        1,
    ),
    (
        ("_validate_returned_run_s10_replay", "<lambda>"),
        "research_decision_engine.belief_models.belief_model",
        1,
    ),
    (
        ("_validate_returned_run_s10_updates", "<lambda>"),
        "research_decision_engine.belief_models.belief_model",
        1,
    ),
)

AUTHORIZED_SELECTOR_REPLAY_EXTERNAL_CALLS: Final[frozenset[str]] = frozenset(
    {
        "hashlib.sha256",
        "statistics.mean",
        "statistics.stdev",
        "research_decision_engine.benchmarks.broader_calibration_history.CalibrationHistorySelection",
        "research_decision_engine.benchmarks.broader_calibration_history.RunProvenanceError",
        "research_decision_engine.benchmarks.broader_calibration_history._validate_effects",
        "research_decision_engine.benchmarks.broader_calibration_history._validate_observations",
        "research_decision_engine.benchmarks.broader_protocol.canonical_json_bytes",
        "research_decision_engine.benchmarks.broader_protocol.f64",
        "research_decision_engine.benchmarks.broader_protocol.protocol_hash",
    }
)

AUTHORIZED_SELECTOR_REPLAY_EXTERNAL_CALL_COUNTS: Final[tuple[tuple[str, int], ...]] = (
    ("hashlib.sha256", 1),
    (
        "research_decision_engine.benchmarks.broader_calibration_history.CalibrationHistorySelection",
        1,
    ),
    ("research_decision_engine.benchmarks.broader_calibration_history.RunProvenanceError", 2),
    ("research_decision_engine.benchmarks.broader_calibration_history._validate_effects", 1),
    ("research_decision_engine.benchmarks.broader_calibration_history._validate_observations", 1),
    ("research_decision_engine.benchmarks.broader_protocol.canonical_json_bytes", 1),
    ("research_decision_engine.benchmarks.broader_protocol.f64", 5),
    ("research_decision_engine.benchmarks.broader_protocol.protocol_hash", 1),
    ("statistics.mean", 1),
    ("statistics.stdev", 1),
)

AUTHORIZED_SELECTOR_REPLAY_INTERNAL_SITES: Final[tuple[tuple[tuple[str, ...], str, int], ...]] = (
    (
        ("replay_calibration_history_selection",),
        f"{CALIBRATION_SELECTOR_REPLAY_MODULE_NAME}.raw_effect_sha256",
        1,
    ),
)

AUTHORIZED_SELECTOR_REPLAY_UNRESOLVED_CALLS: Final[tuple[tuple[tuple[str, ...], str], ...]] = (
    (("raw_effect_sha256",), "effect.to_dict"),
    (
        ("raw_effect_sha256",),
        "hashlib.sha256(canonical_json_bytes(effect.to_dict(), final_lf=True)).hexdigest",
    ),
    (("replay_calibration_history_selection",), "run_id.strip"),
)

AUTHORIZED_RETURNED_RUN_UNRESOLVED_CALL_COUNTS: Final[
    tuple[tuple[tuple[str, ...], str, int], ...]
] = (
    (("ReturnedRunProjectionError", "__init__"), "super().__init__", 1),
    (("_construct_returned_run_s2",), "cache.update", 1),
    (("_construct_returned_run_s2",), "completed_items.append", 1),
    (("_construct_returned_run_s3",), "updates.append", 1),
    (("_construct_returned_run_s8",), "feasibility_state.complete", 1),
    (
        ("_construct_returned_run_s8",),
        "feasibility_state.publicly_feasible_candidate_ids",
        1,
    ),
    (
        ("_construct_returned_run_s8",),
        "last_update.posterior_state.state.posterior_map",
        1,
    ),
    (
        ("_construct_returned_run_s8",),
        "last_update.posterior_state.state.posterior_map().items",
        1,
    ),
    (("_controlled_variables_mapping",), "encoded.append", 2),
    (("_decode_flat",), "check", 1),
    (("_decode_flat",), "constructor", 1),
    (("_decoded_controlled_variables",), "result.append", 1),
    (("_decoded_items",), "check", 1),
    (("_decoded_probability_pairs",), "result.append", 1),
    (("_decoded_residuals",), "result.append", 1),
    (("_diagnostic_mapping",), "encoded.append", 2),
    (("_f64_text",), "text.startswith", 1),
    (("_hexbytes",), "bytes.fromhex(text).hex", 1),
    (("_neutralize_returned_run_structure",), "identifier.strip", 1),
    (("_neutralize_returned_run_structure",), "neutral.get", 1),
    (("_neutralize_returned_run_structure",), "parsed.items", 1),
    (("_probability_pairs_mapping",), "encoded.append", 2),
    (("_project_controlled_variables",), "result.append", 1),
    (("_project_probability_pairs",), "result.append", 1),
    (("_projected_items",), "check", 1),
    (("_projection_child",), "mapping", 1),
    (("_projection_sequence_mapping",), "mapping", 1),
    (("_provenance_mapping",), "encoded.append", 2),
    (("_pure_revealed_observation",), "transform.serialized_key.hex", 1),
    (("_rebuild",), "constructor", 1),
    (("_rebuild",), "projector", 1),
    (("_reraise_returned_run_batch_error",), "message.startswith", 1),
    (("_returned_decision_trace_occurrences",), "result.append", 1),
    (("_returned_lookahead_trace_occurrences",), "result.append", 1),
    (("_returned_observation_contexts",), "action_contexts.append", 1),
    (("_s10_calibration_effects",), "expected_deployment_effects.extend", 1),
    (("_s10_calibration_effects",), "expected_deployment_observations.extend", 1),
    (("_s10_calibration_effects",), "selector_physical_costs.append", 1),
    (("_s10_candidate_occurrences",), "occurrences.append", 2),
    (("_s10_candidate_occurrences",), "occurrences.extend", 3),
    (("_scientific_call",), "call", 1),
    (("_validate_returned_run_s10_replay",), "decision.policy_trace.to_dict", 1),
    (("_validate_returned_run_s10_replay",), "public_state.complete", 1),
    (
        ("_validate_returned_run_s10_replay",),
        "public_state.publicly_feasible_candidate_ids",
        1,
    ),
    (("_validate_returned_run_s10_replay",), "trace.to_dict", 1),
    (("_validate_returned_run_s10_updates",), "applied_pairs.update", 1),
    (("_validate_returned_run_s10_updates",), "completed.append", 1),
    (
        ("_validate_returned_run_s10_updates",),
        "eligibility.valid_unapplied_pairs",
        1,
    ),
    (("_validate_returned_run_s10_updates",), "eligible_pairs.extend", 1),
    (
        ("_validate_returned_run_s10_updates",),
        "initial.current_state.state.posterior_map",
        1,
    ),
    (
        ("_validate_returned_run_s10_updates",),
        "initial.current_state.state.posterior_map().items",
        1,
    ),
    (("_validate_returned_run_s10_updates",), "model.update", 1),
    (("_validate_returned_run_s10_updates",), "temporary_diagnostics.append", 1),
    (("_validate_returned_run_s10_updates",), "temporary_effects.append", 1),
    (("_validate_returned_run_s9",), "initial_state.posterior_map", 1),
    (("_validate_returned_run_s9",), "initial_state.posterior_map().items", 1),
    (("_validate_returned_run_s9",), "state.complete", 1),
    (("_validate_returned_run_s9",), "state.publicly_feasible_candidate_ids", 1),
    (("decode_run_provenance_projection",), "details.append", 1),
    (("reconstruct_model_update",), "evidence.provenance.details_dict", 1),
    (("reconstruct_model_update",), "evidence.provenance.details_dict().get", 1),
    (("reconstruct_model_update",), "group.strip", 1),
    (
        ("validate_revealed_observation_projection",),
        "canonical_json_bytes(list(projection.key_fields)).hex",
        1,
    ),
)

AUTHORIZED_RETURNED_RUN_UNRESOLVED_MUTATION_COUNTS: Final[
    tuple[tuple[tuple[str, ...], str, int], ...]
] = (
    (
        ("ReturnedRunProjectionError", "__init__"),
        "(self.category, self.failure_code, self.path)",
        1,
    ),
    (("_construct_returned_run_s2",), "cache[candidate_projection]", 1),
    (("_construct_returned_run_s2",), "cache[evidence_projection]", 1),
    (("_construct_returned_run_s2",), "cache[likelihood_projection]", 1),
    (("_construct_returned_run_s2",), "cache[provenance_projection]", 1),
    (("_construct_returned_run_s2",), "cache[state_projection]", 1),
    (("_construct_returned_run_s3",), "cache[belief_update_projection]", 1),
    (("_construct_returned_run_s3",), "cache[diagnostic_projection]", 1),
    (("_construct_returned_run_s3",), "cache[effect_projection]", 1),
    (("_construct_returned_run_s3",), "cache[interval_projection]", 1),
    (("_construct_returned_run_s3",), "cache[model_state_projection]", 1),
    (("_construct_returned_run_s3",), "cache[model_update_projection]", 1),
    (("_construct_returned_run_s3",), "cache[projection.lineage]", 1),
    (("_construct_returned_run_s3",), "cache[sigma_projection]", 1),
    (("_construct_returned_run_s3",), "effect_by_projection[effect_projection]", 1),
    (("_construct_returned_run_s4",), "cache[context_projection]", 1),
    (("_construct_returned_run_s4",), "cache[decision_trace_projection]", 1),
    (("_construct_returned_run_s4",), "cache[design_projection]", 1),
    (("_construct_returned_run_s4",), "cache[score_projection]", 1),
    (("_construct_returned_run_s5",), "cache[alternative_projection]", 1),
    (("_construct_returned_run_s5",), "cache[branch_projection]", 1),
    (("_construct_returned_run_s5",), "cache[first_projection]", 1),
    (("_construct_returned_run_s5",), "cache[lookahead_trace_projection]", 1),
    (("_construct_returned_run_s5",), "cache[second_projection]", 1),
    (("_construct_returned_run_s5",), "traces[policy_projection]", 1),
    (("_validate_returned_run_s6",), "reconstructed[observation]", 1),
)

AUTHORIZED_RETURNED_RUN_ORACLE_IMPORT_NAMES: Final[frozenset[str]] = frozenset(
    {
        "CALIBRATION_NAMESPACE",
        "OracleError",
        "_parse_calibration_candidate",
        "calibration_key",
        "decision_key",
        "transform_key",
    }
)
AUTHORIZED_RETURNED_RUN_CALIBRATION_HISTORY_IMPORT_NAMES: Final[frozenset[str]] = frozenset(
    {
        "CALIBRATION_ELIGIBILITY_BASIS",
        "CALIBRATION_SELECTION_VERSION",
        "expected_calibration_effect",
    }
)
AUTHORIZED_RETURNED_RUN_SELECTOR_REPLAY_IMPORT_NAMES: Final[frozenset[str]] = frozenset(
    {"raw_effect_sha256", "replay_calibration_history_selection"}
)

AUTHORIZED_SELECTOR_REPLAY_IMPORT_ROOTS: Final[frozenset[str]] = frozenset(
    {
        "__future__",
        "belief_models",
        "broader_calibration_history",
        "broader_oracle",
        "broader_protocol",
        "hashlib",
        "statistics",
        "typing",
    }
)
AUTHORIZED_SELECTOR_REPLAY_HISTORY_IMPORT_NAMES: Final[frozenset[str]] = frozenset(
    {
        "CALIBRATION_ELIGIBILITY_BASIS",
        "CALIBRATION_SELECTION_VERSION",
        "CALIBRATION_SIGMA_DDOF",
        "CALIBRATION_SOURCE_SEQUENCE_CUTOFF",
        "CalibrationHistorySelection",
        "RunProvenanceError",
        "_validate_effects",
        "_validate_observations",
    }
)
AUTHORIZED_SELECTOR_REPLAY_ORACLE_IMPORT_NAMES: Final[frozenset[str]] = frozenset(
    {"CALIBRATION_NAMESPACE", "RevealedObservation"}
)
AUTHORIZED_SELECTOR_REPLAY_PROTOCOL_IMPORT_NAMES: Final[frozenset[str]] = frozenset(
    {"PROTOCOL_VERSION", "canonical_json_bytes", "f64", "protocol_hash"}
)
AUTHORIZED_SELECTOR_REPLAY_BELIEF_IMPORT_NAMES: Final[frozenset[str]] = frozenset(
    {"SIGMA_FLOOR", "MatchedEffectObservation"}
)


def _module_leaf(module: str | None) -> str:
    """Return one imported module's final dotted component."""

    return "" if module is None else module.rsplit(".", 1)[-1]


def imported_module_leaves(source: str) -> set[str]:
    """Normalize local absolute imports while retaining stdlib package roots."""

    def boundary_name(module: str) -> str:
        if module.startswith("research_decision_engine."):
            return _module_leaf(module)
        return module.split(".", 1)[0]

    leaves: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            leaves.update(boundary_name(alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                leaves.update(boundary_name(alias.name) for alias in node.names)
            else:
                leaves.add(boundary_name(node.module))
    return leaves


def _imports_for_module_leaf(
    tree: ast.AST, module_leaf: str
) -> tuple[ast.Import | ast.ImportFrom, ...]:
    """Find imports of exactly one module leaf without resolving imports."""

    found: list[ast.Import | ast.ImportFrom] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and (
                _module_leaf(node.module) == module_leaf
                or (
                    node.module is None
                    and any(_module_leaf(alias.name) == module_leaf for alias in node.names)
                )
            )
        ) or (
            isinstance(node, ast.Import)
            and any(_module_leaf(alias.name) == module_leaf for alias in node.names)
        ):
            found.append(node)
    return tuple(found)


def _is_exact_guarded_module_path(node: ast.ImportFrom, module_leaf: str) -> bool:
    """Accept only the package paths owned by one guarded scientific module."""

    if module_leaf == "belief_models":
        return (node.level == 0 and node.module == "research_decision_engine.belief_models") or (
            node.level == 2 and node.module == "belief_models"
        )
    return (
        node.level == 0 and node.module == f"research_decision_engine.benchmarks.{module_leaf}"
    ) or (node.level == 1 and node.module == module_leaf)


def imported_names_from_module(source: str, module_leaf: str) -> frozenset[str]:
    """Return statically named ``from module import name`` bindings."""

    names: set[str] = set()
    for node in _imports_for_module_leaf(ast.parse(source), module_leaf):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
    return frozenset(names)


def module_import_names_are_authorized(
    source: str, module_leaf: str, authorized_names: frozenset[str]
) -> bool:
    """Permit only unaliased, explicitly named imports from one module."""

    nodes = _imports_for_module_leaf(ast.parse(source), module_leaf)
    return all(
        isinstance(node, ast.ImportFrom)
        and _is_exact_guarded_module_path(node, module_leaf)
        and all(
            alias.name != "*" and alias.asname is None and alias.name in authorized_names
            for alias in node.names
        )
        for node in nodes
    )


def returned_run_path_imports_are_authorized(source: str) -> bool:
    """Apply exact qualified import bindings to returned-run source or snippets."""

    analysis = analyze_qualified_symbols(source, module_name=RETURNED_RUN_MODULE_NAME)
    runtime_bindings = _runtime_import_bindings(analysis)
    future_features = _future_import_features(analysis)
    raw_effect_binding = (
        "raw_effect_sha256",
        "research_decision_engine.benchmarks.broader_calibration_selector_replay.raw_effect_sha256",
    )
    replay_binding = (
        "replay_calibration_history_selection",
        "research_decision_engine.benchmarks.broader_calibration_selector_replay."
        "replay_calibration_history_selection",
    )
    return (
        runtime_bindings <= AUTHORIZED_RETURNED_RUN_IMPORT_BINDINGS
        and future_features <= {"annotations"}
        and all("*" not in origin for _local, origin in runtime_bindings)
        and (raw_effect_binding not in runtime_bindings or replay_binding in runtime_bindings)
    )


def _runtime_import_bindings(
    analysis: QualifiedSymbolAnalysis,
) -> frozenset[tuple[str, str]]:
    return frozenset(
        (binding.name, origin)
        for binding in analysis.imports
        if not binding.kind.startswith("future:")
        for origin in binding.origins
    )


def _import_occurrences(analysis: QualifiedSymbolAnalysis) -> tuple[ImportOccurrence, ...]:
    return tuple(
        sorted(
            ImportOccurrence(
                binding.scope,
                binding.name,
                binding.kind,
                tuple(sorted(binding.origins)),
            )
            for binding in analysis.imports
        )
    )


def _authorized_import_occurrences(
    bindings: frozenset[tuple[str, str]],
    plain_modules: frozenset[str],
) -> tuple[ImportOccurrence, ...]:
    runtime = (
        ImportOccurrence(
            (),
            local,
            (
                f"plain-import:{origin}"
                if local == origin and origin in plain_modules
                else f"from-import:{origin}"
            ),
            (origin,),
        )
        for local, origin in bindings
    )
    future = ImportOccurrence(
        (),
        "annotations",
        "future:__future__.annotations",
        ("__future__.annotations",),
    )
    return tuple(sorted((*runtime, future)))


def _future_import_features(analysis: QualifiedSymbolAnalysis) -> frozenset[str]:
    return frozenset(
        binding.name for binding in analysis.imports if binding.kind.startswith("future:")
    )


def _top_level_binding_names(
    analysis: QualifiedSymbolAnalysis,
    kinds: frozenset[str],
) -> frozenset[str]:
    return frozenset(
        binding.name
        for binding in analysis.bindings
        if binding.top_level and not kinds.isdisjoint(binding.kind.split("+"))
    )


def _external_call_targets(
    analysis: QualifiedSymbolAnalysis,
    module_name: str,
) -> frozenset[str]:
    return frozenset(
        target
        for call in analysis.calls
        for target in call.targets
        if not target.startswith(f"{module_name}.") and not target.startswith("builtins.")
    )


def _external_call_counts(
    analysis: QualifiedSymbolAnalysis,
    module_name: str,
) -> tuple[tuple[str, int], ...]:
    targets = frozenset(
        target
        for call in analysis.calls
        for target in call.targets
        if not target.startswith(f"{module_name}.") and not target.startswith("builtins.")
    )
    return tuple(
        sorted(
            (
                target,
                sum(target in call.targets for call in analysis.calls),
            )
            for target in targets
        )
    )


def _normalized_sensitive_sites(
    resolved: tuple[ResolvedCall, ...] | tuple[ResolvedReference, ...],
) -> tuple[tuple[tuple[str, ...], str, int], ...]:
    return _normalized_target_sites(resolved, SENSITIVE_APPROVED_QUALIFIED_TARGETS)


def _normalized_target_sites(
    resolved: tuple[ResolvedCall, ...] | tuple[ResolvedReference, ...],
    targets: frozenset[str],
) -> tuple[tuple[tuple[str, ...], str, int], ...]:
    occurrences = tuple(
        (
            tuple("<lambda>" if part.startswith("<lambda:") else part for part in item.scope),
            target,
        )
        for item in resolved
        for target in item.targets
        if target in targets
    )
    keys = frozenset(occurrences)
    return tuple(
        sorted((scope, target, occurrences.count((scope, target))) for scope, target in keys)
    )


def _top_level_projection_aliases(
    analysis: QualifiedSymbolAnalysis,
) -> frozenset[str]:
    authorized_origins = frozenset(
        f"{RETURNED_RUN_MODULE_NAME}.{name}" for name in AUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES
    )
    return frozenset(
        binding.name
        for binding in analysis.bindings
        if binding.top_level
        and not _TOP_LEVEL_VALUE_BINDING_KINDS.isdisjoint(binding.kind.split("+"))
        and not binding.origins.isdisjoint(authorized_origins)
    )


def _is_forbidden_binding_name(name: str) -> bool:
    if name in AUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES:
        return False
    return (
        name in CURRENT_STAGE_UNAUTHORIZED_TOP_LEVEL_BINDINGS
        or name.endswith(("Identity", "Projection"))
        or any(marker in name for marker in ("Persistence", "Reader", "Repository"))
    )


def _exact_top_level_function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    matches = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    return matches[0] if len(matches) == 1 else None


def _function_has_exact_signature(
    node: ast.FunctionDef | None,
    *,
    positional: tuple[tuple[str, str], ...] = (),
    keyword_only: tuple[tuple[str, str], ...] = (),
    returns: str,
) -> bool:
    if node is None:
        return False

    def annotated(arguments: list[ast.arg]) -> tuple[tuple[str, str], ...]:
        return tuple(
            (
                argument.arg,
                "" if argument.annotation is None else ast.unparse(argument.annotation),
            )
            for argument in arguments
        )

    return bool(
        not node.decorator_list
        and not node.type_params
        and not node.args.posonlyargs
        and annotated(node.args.args) == positional
        and node.args.vararg is None
        and annotated(node.args.kwonlyargs) == keyword_only
        and node.args.kwarg is None
        and not node.args.defaults
        and len(node.args.kw_defaults) == len(keyword_only)
        and all(default is None for default in node.args.kw_defaults)
        and node.returns is not None
        and ast.unparse(node.returns) == returns
        and node.type_comment is None
    )


def _function_has_exact_signature_source(
    node: ast.FunctionDef | None,
    source: str,
) -> bool:
    expected = ast.parse(source).body[0]
    return bool(
        node is not None
        and isinstance(expected, ast.FunctionDef)
        and not node.decorator_list
        and not node.type_params
        and node.type_comment is None
        and node.returns is not None
        and expected.returns is not None
        and ast.dump(node.args) == ast.dump(expected.args)
        and ast.dump(node.returns) == ast.dump(expected.returns)
    )


def _exact_returned_run_batch_public_signature(tree: ast.Module) -> bool:
    return _function_has_exact_signature(
        _exact_top_level_function(tree, "validate_returned_run_batch"),
        keyword_only=(
            (
                "returned_runs_in_actual_delivery_order",
                "tuple[ReturnedRunProjection, ...]",
            ),
            (
                "returned_domains_in_actual_delivery_order",
                "tuple[BroaderArmRun, ...] | None",
            ),
        ),
        returns="tuple[tuple[BroaderArmRun, str], ...]",
    )


def _direct_call_name(node: ast.Call) -> str | None:
    return node.func.id if isinstance(node.func, ast.Name) else None


def _exact_returned_run_stage_loop(
    loop: ast.For,
    *,
    helper: str,
    source: str,
) -> bool:
    expected_item = "run" if source == "runs" else "projection"
    expected_bodies = dict(
        item.split("::", 1) for item in _EXPECTED_RETURNED_RUN_BATCH_STAGE_BODIES.splitlines()
    )
    expected_body = expected_bodies.get(helper)
    return bool(
        expected_body is not None
        and not loop.orelse
        and loop.type_comment is None
        and isinstance(loop.target, ast.Tuple)
        and len(loop.target.elts) == 2
        and isinstance(loop.target.elts[0], ast.Name)
        and isinstance(loop.target.elts[1], ast.Name)
        and loop.target.elts[0].id == "index"
        and loop.target.elts[1].id == expected_item
        and isinstance(loop.iter, ast.Call)
        and isinstance(loop.iter.func, ast.Name)
        and loop.iter.func.id == "enumerate"
        and len(loop.iter.args) == 1
        and isinstance(loop.iter.args[0], ast.Name)
        and loop.iter.args[0].id == source
        and not loop.iter.keywords
        and tuple(ast.dump(statement) for statement in ast.parse(expected_body).body)
        == tuple(ast.dump(statement) for statement in loop.body)
    )


def _returned_run_batch_stage_schedule_is_exact(tree: ast.Module) -> bool:
    reconstruction = _exact_top_level_function(tree, "_reconstruct_returned_run_batch")
    entry_point = _exact_top_level_function(tree, "validate_returned_run_batch")
    if reconstruction is None or entry_point is None:
        return False
    reconstruction_calls = [
        node
        for node in ast.walk(reconstruction)
        if isinstance(node, ast.Call)
        and _direct_call_name(node) in _RETURNED_RUN_BATCH_STAGE_HELPERS
    ]
    expected_helpers = tuple(helper for _stage, helper in EXPECTED_RETURNED_RUN_BATCH_STAGE_HELPERS)
    if len(reconstruction_calls) != len(expected_helpers) or any(
        tuple(_direct_call_name(call) for call in reconstruction_calls).count(helper) != 1
        for helper in expected_helpers
    ):
        return False
    stage_tries = [statement for statement in reconstruction.body if isinstance(statement, ast.Try)]
    if (
        len(stage_tries) != 1
        or stage_tries[0].orelse
        or stage_tries[0].finalbody
        or len(reconstruction.body) != 3
        or ast.dump(reconstruction.body[0])
        != ast.dump(
            ast.parse("payload_count = len(returned_runs_in_actual_delivery_order)").body[0]
        )
        or reconstruction.body[1] is not stage_tries[0]
        or ast.dump(reconstruction.body[2]) != ast.dump(ast.parse("return tuple(runs)").body[0])
    ):
        return False
    if any(
        not (
            isinstance(statement, ast.For)
            or (
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and isinstance(statement.value, ast.List)
                and not statement.value.elts
            )
        )
        for statement in stage_tries[0].body
    ):
        return False
    scheduled_loops: list[tuple[ast.For, str]] = []
    for statement in stage_tries[0].body:
        if not isinstance(statement, ast.For):
            continue
        calls = [
            node
            for node in ast.walk(statement)
            if isinstance(node, ast.Call)
            and _direct_call_name(node) in _RETURNED_RUN_BATCH_STAGE_HELPERS
        ]
        if calls:
            if len(calls) != 1:
                return False
            helper = _direct_call_name(calls[0])
            if helper is None:
                return False
            scheduled_loops.append((statement, helper))
    if tuple(helper for _loop, helper in scheduled_loops) != expected_helpers:
        return False
    for index, ((loop, helper), expected_helper) in enumerate(
        zip(scheduled_loops, expected_helpers, strict=True)
    ):
        if helper != expected_helper or not _exact_returned_run_stage_loop(
            loop,
            helper=helper,
            source=("returned_runs_in_actual_delivery_order" if index < 8 else "runs"),
        ):
            return False
    entry_calls = [
        node
        for node in ast.walk(entry_point)
        if isinstance(node, ast.Call)
        and _direct_call_name(node) == "_reconstruct_returned_run_batch"
    ]
    if len(entry_calls) != 1:
        return False
    call = entry_calls[0]
    return bool(
        len(call.args) == 1
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id == "returned_runs_in_actual_delivery_order"
        and not call.keywords
        and any(
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == "runs"
            and statement.value is call
            for statement in entry_point.body
        )
    )


def _returned_run_batch_validator_surface_is_closed(tree: ast.Module) -> bool:
    preparation = _exact_top_level_function(tree, "_prepare_returned_run_batch")
    reconstruction = _exact_top_level_function(tree, "_reconstruct_returned_run_batch")
    relation = _exact_top_level_function(tree, "_validate_returned_run_relation_context")
    projection_tuple = "tuple[ReturnedRunProjection, ...]"
    stage_signatures = dict(
        item.split("::", 1)
        for item in """\
_validate_returned_run_s1::def _(projection: ReturnedRunProjection) -> None: ...
_construct_returned_run_s2::def _(projection: ReturnedRunProjection) -> tuple[dict[object, object], tuple[CompletedExperiment, ...], tuple[Evidence, ...]]: ...
_construct_returned_run_s3::def _(projection: ReturnedRunProjection, cache: dict[object, object]) -> tuple[BeliefModelLineage, tuple[ModelBeliefUpdate, ...], tuple[ModelAdequacyDiagnostic, ...], tuple[MatchedEffectObservation, ...], dict[RunMatchedEffectProjection, MatchedEffectObservation]]: ...
_construct_returned_run_s4::def _(projection: ReturnedRunProjection, cache: dict[object, object]) -> None: ...
_construct_returned_run_s5::def _(projection: ReturnedRunProjection, cache: dict[object, object]) -> dict[RunPolicyTraceProjection, DecisionTrace | LookaheadPlanTrace]: ...
_validate_returned_run_s6::def _(projection: ReturnedRunProjection) -> dict[RunRevealedObservationProjection, RevealedObservation]: ...
_construct_returned_run_s7_stage::def _(projection: RunCalibrationProjection | None, observations: dict[RunRevealedObservationProjection, RevealedObservation], effects: dict[RunMatchedEffectProjection, MatchedEffectObservation]) -> CalibrationDeployment | None: ...
_construct_returned_run_s8_stage::def _(projection: ReturnedRunProjection, *, completed: tuple[CompletedExperiment, ...], evidence: tuple[Evidence, ...], lineage: BeliefModelLineage, updates: tuple[ModelBeliefUpdate, ...], diagnostics: tuple[ModelAdequacyDiagnostic, ...], effects: tuple[MatchedEffectObservation, ...], calibration: CalibrationDeployment | None, observations: dict[RunRevealedObservationProjection, RevealedObservation], traces: dict[RunPolicyTraceProjection, DecisionTrace | LookaheadPlanTrace]) -> BroaderArmRun: ...
_validate_returned_run_s9::def _(run: BroaderArmRun) -> None: ...
_validate_returned_run_s10::def _(run: BroaderArmRun) -> None: ...""".splitlines()  # noqa: E501
    )
    return bool(
        _exact_returned_run_batch_public_signature(tree)
        and _function_has_exact_signature(
            preparation,
            keyword_only=(
                ("returned_runs_in_actual_delivery_order", projection_tuple),
                (
                    "returned_domains_in_actual_delivery_order",
                    "tuple[BroaderArmRun, ...] | None",
                ),
            ),
            returns="None",
        )
        and _function_has_exact_signature(
            reconstruction,
            positional=(("returned_runs_in_actual_delivery_order", projection_tuple),),
            returns="tuple[BroaderArmRun, ...]",
        )
        and _function_has_exact_signature(
            relation,
            positional=(("run", "BroaderArmRun"), ("expected_run", "BroaderArmRun | None")),
            returns="None",
        )
        and all(
            _function_has_exact_signature_source(
                _exact_top_level_function(tree, helper),
                source,
            )
            for helper, source in stage_signatures.items()
        )
    )


def _returned_run_payload_hash_helper_is_exact(tree: ast.Module) -> bool:
    helper = _exact_top_level_function(tree, "_accepted_result_payload_sha256")
    if not (
        _function_has_exact_signature(
            helper,
            positional=(("projection", "ReturnedRunProjection"),),
            returns="str",
        )
        and helper is not None
        and len(helper.body) == 1
        and isinstance(helper.body[0], ast.Return)
        and isinstance(helper.body[0].value, ast.Call)
    ):
        return False
    protocol_call = helper.body[0].value
    if not (
        isinstance(protocol_call.func, ast.Name)
        and protocol_call.func.id == "protocol_hash"
        and len(protocol_call.args) == 2
        and not protocol_call.keywords
        and isinstance(protocol_call.args[0], ast.Constant)
        and protocol_call.args[0].value == _APPROVED_RETURNED_RUN_PAYLOAD_HASH_DOMAIN
        and isinstance(protocol_call.args[1], ast.Call)
    ):
        return False
    payload_call = protocol_call.args[1]
    return bool(
        isinstance(payload_call.func, ast.Name)
        and payload_call.func.id == "projection_as_dict"
        and len(payload_call.args) == 1
        and isinstance(payload_call.args[0], ast.Name)
        and payload_call.args[0].id == "projection"
        and not payload_call.keywords
    )


def _returned_run_batch_hash_phase_is_exact(tree: ast.Module) -> bool:
    entry_point = _exact_top_level_function(tree, "validate_returned_run_batch")
    if entry_point is None:
        return False
    hash_assignments = [
        statement
        for statement in entry_point.body
        if isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id == "hashes"
    ]
    if len(hash_assignments) != 1:
        return False
    expected_assignment = ast.parse(
        "hashes = tuple("
        "_accepted_result_payload_sha256(projection) "
        "for projection in returned_runs_in_actual_delivery_order)"
    ).body[0]
    if ast.dump(hash_assignments[0]) != ast.dump(expected_assignment):
        return False
    if any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
        and node is not entry_point
        for node in ast.walk(entry_point)
    ):
        return False
    accepted_calls = [
        node
        for node in ast.walk(entry_point)
        if isinstance(node, ast.Call)
        and _direct_call_name(node) == "_accepted_result_payload_sha256"
    ]
    context_calls = [
        node
        for node in ast.walk(entry_point)
        if isinstance(node, ast.Call)
        and _direct_call_name(node) == "_validate_returned_run_relation_context"
    ]
    if (
        len(accepted_calls) != 1
        or len(context_calls) != 2
        or max(call.end_lineno or call.lineno for call in context_calls)
        >= hash_assignments[0].lineno
    ):
        return False
    expected_return = ast.parse("return tuple(zip(runs, hashes, strict=True))").body[0]
    return bool(entry_point.body and ast.dump(entry_point.body[-1]) == ast.dump(expected_return))


def _returned_run_batch_hash_identity_surface_is_closed(
    tree: ast.Module,
    analysis: QualifiedSymbolAnalysis,
) -> bool:
    protocol_hash = "research_decision_engine.benchmarks.broader_protocol.protocol_hash"
    runtime_id = "research_decision_engine.benchmarks.broader_protocol.runtime_id"
    expected_domains: dict[tuple[tuple[str, ...], str], tuple[str, ...]] = {
        (("_accepted_result_payload_sha256",), protocol_hash): (
            repr(_APPROVED_RETURNED_RUN_PAYLOAD_HASH_DOMAIN),
        ),
        (("_pure_revealed_observation",), protocol_hash): ("'revealed_outcome/v1'",),
        (("_pure_revealed_observation",), runtime_id): (
            "'oracle-key'",
            "'oracle_key_id/v1'",
        ),
        (("_s10_calibration_effects",), protocol_hash): ("CALIBRATION_SELECTION_VERSION",),
        (("recompute_observation_authorization_id",), runtime_id): (
            "'authorization'",
            "'authorization_id/v1'",
        ),
        (("recompute_revealed_oracle_key_id",), runtime_id): (
            "'oracle-key'",
            "'oracle_key_id/v1'",
        ),
        (("recompute_revealed_outcome_digest",), protocol_hash): ("'revealed_outcome/v1'",),
    }
    identity_calls = tuple(
        (call, target)
        for call in analysis.calls
        for target in call.targets
        if target in {protocol_hash, runtime_id}
    )
    if (
        len(identity_calls) != len(expected_domains)
        or {(call.scope, target) for call, target in identity_calls} != set(expected_domains)
        or any(call.targets != {target} for call, target in identity_calls)
    ):
        return False
    call_nodes = tuple(node for node in ast.walk(tree) if isinstance(node, ast.Call))
    for resolved, target in identity_calls:
        matches = [
            node
            for node in call_nodes
            if node.lineno == resolved.lineno and ast.unparse(node.func) == resolved.spelling
        ]
        expected = expected_domains[(resolved.scope, target)]
        if (
            len(matches) != 1
            or len(matches[0].args) != len(expected) + 1
            or matches[0].keywords
            or tuple(ast.dump(argument) for argument in matches[0].args[: len(expected)])
            != tuple(ast.dump(ast.parse(item, mode="eval").body) for item in expected)
        ):
            return False
    return bool(
        _returned_run_payload_hash_helper_is_exact(tree)
        and _returned_run_batch_hash_phase_is_exact(tree)
    )


def _exact_projection_type_targets(node: ast.AST) -> frozenset[str]:
    return frozenset(
        comparison.comparators[0].id
        for comparison in ast.walk(node)
        if isinstance(comparison, ast.Compare)
        and len(comparison.ops) == 1
        and isinstance(comparison.ops[0], (ast.Is, ast.IsNot))
        and len(comparison.comparators) == 1
        and isinstance(comparison.comparators[0], ast.Name)
        and comparison.comparators[0].id in RETURNED_RUN_SHAPE_PROJECTION_TYPES
        and isinstance(comparison.left, ast.Call)
        and isinstance(comparison.left.func, ast.Name)
        and comparison.left.func.id == "type"
        and len(comparison.left.args) == 1
        and not comparison.left.keywords
    )


def _returned_run_shape_authority_checks(
    tree: ast.Module,
) -> tuple[bool, bool, bool, bool, bool]:
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    authority = functions.get("validate_returned_run_projection_shape")
    if authority is None:
        return False, False, False, False, False
    arguments = authority.args
    defaults = tuple(
        default.value for default in arguments.kw_defaults if isinstance(default, ast.Constant)
    )
    exact_signature = (
        tuple(item.arg for item in arguments.args) == ("value",)
        and tuple(item.arg for item in arguments.kwonlyargs)
        == ("path", "_defer_scientific_validation")
        and arguments.vararg is None
        and arguments.kwarg is None
        and not arguments.defaults
        and defaults == ("returned_run", False)
        and isinstance(authority.returns, ast.Name)
        and authority.returns.id == "ReturnedRunProjection"
    )
    exact_coverage = (
        _exact_projection_type_targets(authority) == RETURNED_RUN_SHAPE_PROJECTION_TYPES
    )
    nested = {node.name: node for node in ast.walk(authority) if isinstance(node, ast.FunctionDef)}

    def literals(name: str) -> frozenset[str]:
        return frozenset(
            value.value
            for value in ast.walk(nested[name])
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        )

    explicit_coupling = (
        nested.keys() >= {"_provenance_value", "_control_value", "_second_action", "_policy_trace"}
        and {"null", "bool", "i64", "f64", "string"} <= literals("_provenance_value")
        and {"i64", "f64", "string"} <= literals("_control_value")
        and {"opens_pair", "completes_pair", "ineligible", "stop"} <= literals("_second_action")
        and {"decision_trace", "lookahead_plan_trace"} <= literals("_policy_trace")
        and {
            "RunPolicyTraceProjection",
            "RunDecisionTraceProjection",
            "RunLookaheadTraceProjection",
        }
        <= _exact_projection_type_targets(nested["_policy_trace"])
    )
    forbidden_calls = {
        "asdict",
        "dict",
        "fields",
        "getattr",
        "hasattr",
        "is_dataclass",
        "isinstance",
        "repr",
        "vars",
    }
    no_reflection_or_coercion = not any(
        (
            isinstance(node, ast.Attribute)
            and node.attr == "__dict__"
            or isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in forbidden_calls
        )
        for node in ast.walk(authority)
    )
    second_function_authority = any(
        name not in {"validate_returned_run_projection_shape", "projection_as_dict"}
        and _exact_projection_type_targets(function) == RETURNED_RUN_SHAPE_PROJECTION_TYPES
        for name, function in functions.items()
    )
    second_table_authority = any(
        len(
            {
                name.id
                for name in ast.walk(node.value)
                if isinstance(name, ast.Name) and name.id in RETURNED_RUN_SHAPE_PROJECTION_TYPES
            }
        )
        == len(RETURNED_RUN_SHAPE_PROJECTION_TYPES)
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
    )
    digest = hashlib.sha256(ast.dump(authority).encode("utf-8")).hexdigest()
    exact_fingerprint = exact_signature and digest == RETURNED_RUN_SHAPE_AUTHORITY_SHA256
    return (
        exact_fingerprint,
        exact_coverage,
        explicit_coupling,
        no_reflection_or_coercion,
        not second_function_authority and not second_table_authority,
    )


def returned_run_architecture_checks(
    source: str,
    *,
    analysis: QualifiedSymbolAnalysis | None = None,
) -> tuple[tuple[str, bool], ...]:
    """Return the complete alias-aware Stage-2D.1 returned-run guard."""

    tree = ast.parse(source)
    if analysis is None:
        analysis = analyze_qualified_symbols(source, module_name=RETURNED_RUN_MODULE_NAME)
    elif analysis.source_text != source or analysis.module_name != RETURNED_RUN_MODULE_NAME:
        raise ValueError("precomputed analysis does not match the returned-run source")
    classes = _top_level_binding_names(analysis, frozenset({"class"}))
    functions = _top_level_binding_names(analysis, frozenset({"function"}))
    assignments = _top_level_binding_names(analysis, _TOP_LEVEL_VALUE_BINDING_KINDS)
    top_level_names = frozenset(binding.name for binding in analysis.bindings if binding.top_level)
    all_binding_names = frozenset(binding.name for binding in analysis.binding_events)
    external_calls = _external_call_targets(analysis, RETURNED_RUN_MODULE_NAME)
    finding_codes = frozenset(finding.code for finding in analysis.findings)
    forbidden_calls = frozenset(
        target
        for call in analysis.calls
        for target in call.targets
        if _qualified_call_target_is_forbidden(target)
    ) | frozenset(
        target
        for reference in analysis.references
        for target in reference.targets
        if _qualified_call_target_is_forbidden(target)
    )
    (
        exact_shape_authority,
        exact_shape_coverage,
        explicit_shape_coupling,
        shape_without_reflection,
        single_shape_authority,
    ) = _returned_run_shape_authority_checks(tree)
    return (
        (
            "exact-qualified-import-bindings",
            _runtime_import_bindings(analysis) == AUTHORIZED_RETURNED_RUN_IMPORT_BINDINGS
            and _import_occurrences(analysis)
            == _authorized_import_occurrences(
                AUTHORIZED_RETURNED_RUN_IMPORT_BINDINGS,
                frozenset({"math", "statistics", "struct", "unicodedata"}),
            ),
        ),
        ("exact-future-import", _future_import_features(analysis) == {"annotations"}),
        (
            "closed-top-level-statement-surface",
            _returned_top_level_statement_surface_is_closed(tree),
        ),
        (
            "exact-top-level-function-surface",
            functions == AUTHORIZED_RETURNED_RUN_TOP_LEVEL_FUNCTIONS,
        ),
        (
            "exact-returned-run-batch-public-signature",
            _exact_returned_run_batch_public_signature(tree),
        ),
        (
            "closed-returned-run-batch-validator-surface",
            _returned_run_batch_validator_surface_is_closed(tree),
        ),
        (
            "exact-returned-run-batch-stage-major-schedule",
            _returned_run_batch_stage_schedule_is_exact(tree),
        ),
        (
            "exact-returned-run-payload-hash-domain-and-call",
            _returned_run_payload_hash_helper_is_exact(tree),
        ),
        (
            "no-returned-run-batch-hash-or-identity",
            _returned_run_batch_hash_identity_surface_is_closed(tree, analysis),
        ),
        (
            "exact-top-level-binding-surface",
            top_level_names
            == (
                AUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES
                | AUTHORIZED_RETURNED_RUN_TOP_LEVEL_FUNCTIONS
                | AUTHORIZED_RETURNED_RUN_TOP_LEVEL_ASSIGNMENTS
                | AUTHORIZED_RETURNED_RUN_TYPE_ALIASES
                | frozenset(name for name, _origin in AUTHORIZED_RETURNED_RUN_IMPORT_BINDINGS)
            ),
        ),
        ("exact-34-class-surface", is_exact_authorized_top_level_class_set(set(classes))),
        ("exact-direct-class-definitions", _returned_run_class_definitions_are_exact(tree)),
        ("exact-type-alias-definitions", _returned_run_type_aliases_are_exact(tree)),
        ("exact-returned-run-deep-shape-authority", exact_shape_authority),
        ("complete-returned-run-deep-shape-coverage", exact_shape_coverage),
        ("explicit-returned-run-tag-payload-coupling", explicit_shape_coupling),
        ("no-returned-run-shape-reflection-or-coercion", shape_without_reflection),
        ("single-returned-run-deep-shape-authority", single_shape_authority),
        (
            "exact-top-level-assignment-surface",
            assignments
            == AUTHORIZED_RETURNED_RUN_TOP_LEVEL_ASSIGNMENTS | AUTHORIZED_RETURNED_RUN_TYPE_ALIASES,
        ),
        (
            "exact-protected-binding-kinds",
            _returned_run_protected_binding_kinds_are_exact(analysis),
        ),
        ("no-top-level-rebinding", _top_level_binding_events_are_unique(analysis)),
        (
            "no-module-delete-or-augassign",
            _module_scope_is_free_of_delete_and_augassign(tree),
        ),
        ("closed-implicit-execution-surface", _implicit_execution_surface_is_closed(tree)),
        (
            "no-generator-function-surface",
            not any(isinstance(node, (ast.Yield, ast.YieldFrom)) for node in ast.walk(tree)),
        ),
        ("no-projection-class-alias", not _top_level_projection_aliases(analysis)),
        (
            "no-top-level-qualified-alias",
            "top-level-qualified-alias" not in finding_codes,
        ),
        (
            "no-forbidden-later-stage-binding",
            not any(_is_forbidden_binding_name(name) for name in all_binding_names),
        ),
        (
            "no-forbidden-later-stage-export",
            not any(_is_forbidden_binding_name(name) for name in analysis.exports),
        ),
        ("no-__all__-surface", "__all__" not in top_level_names and not analysis.exports),
        (
            "no-module-dynamic-hooks",
            "dynamic-module-hook" not in finding_codes,
        ),
        ("no-alias-cycle", "alias-cycle" not in finding_codes),
        (
            "no-dynamic-indirection",
            finding_codes.isdisjoint(
                {
                    "dynamic-call",
                    "dynamic-class",
                    "dynamic-module-mutation",
                    "dynamic-namespace-reference",
                    "dynamic-scope-binding",
                    "dynamic-__all__",
                    "qualified-state-mutation",
                    "unresolved-mutator-reference",
                    "unresolved-top-level-binding",
                    "unresolved-call-alias",
                    "unresolved-sensitive-provenance",
                    "forbidden-later-stage-binding",
                }
            ),
        ),
        ("no-forbidden-qualified-call", not forbidden_calls),
        (
            "exact-qualified-external-call-surface",
            external_calls == AUTHORIZED_RETURNED_RUN_EXTERNAL_CALLS
            and _external_call_counts(analysis, RETURNED_RUN_MODULE_NAME)
            == AUTHORIZED_RETURNED_RUN_EXTERNAL_CALL_COUNTS,
        ),
        (
            "exact-sensitive-approved-call-and-reference-sites",
            _normalized_sensitive_sites(analysis.calls) == AUTHORIZED_SENSITIVE_APPROVED_SITES
            and _normalized_sensitive_sites(analysis.references)
            == AUTHORIZED_SENSITIVE_APPROVED_SITES,
        ),
        (
            "exact-unresolved-call-surface",
            _unresolved_call_counts(analysis) == AUTHORIZED_RETURNED_RUN_UNRESOLVED_CALL_COUNTS,
        ),
        (
            "exact-unresolved-mutation-surface",
            _unresolved_mutation_counts(analysis)
            == AUTHORIZED_RETURNED_RUN_UNRESOLVED_MUTATION_COUNTS,
        ),
        (
            "no-top-level-async-function",
            not _top_level_binding_names(analysis, frozenset({"async-function"})),
        ),
    )


def _is_exact_effect_to_dict_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "to_dict"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "effect"
        and not node.args
        and not node.keywords
    )


def _is_exact_raw_effect_sha256_call(node: ast.Call) -> bool:
    """Recognize the sole frozen raw-effect digest expression."""

    if not (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "hashlib"
        and node.func.attr == "sha256"
        and len(node.args) == 1
        and len(node.keywords) == 0
    ):
        return False
    canonical = node.args[0]
    return (
        isinstance(canonical, ast.Call)
        and isinstance(canonical.func, ast.Name)
        and canonical.func.id == "canonical_json_bytes"
        and len(canonical.args) == 1
        and _is_exact_effect_to_dict_call(canonical.args[0])
        and len(canonical.keywords) == 1
        and canonical.keywords[0].arg == "final_lf"
        and isinstance(canonical.keywords[0].value, ast.Constant)
        and canonical.keywords[0].value.value is True
    )


def _has_exact_hashlib_import(tree: ast.AST) -> bool:
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and (
            (isinstance(node, ast.Import) and any(alias.name == "hashlib" for alias in node.names))
            or (isinstance(node, ast.ImportFrom) and _module_leaf(node.module) == "hashlib")
        )
    ]
    return (
        len(imports) == 1
        and isinstance(imports[0], ast.Import)
        and len(imports[0].names) == 1
        and imports[0].names[0].name == "hashlib"
        and imports[0].names[0].asname is None
    )


def _oracle_type_import_is_narrow(tree: ast.AST) -> bool:
    """Keep the Oracle record type under TYPE_CHECKING; allow its pure constant."""

    type_checking_nodes: set[int] = set()
    for node in getattr(tree, "body", ()):
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "TYPE_CHECKING"
        ):
            type_checking_nodes.update(id(child) for child in ast.walk(node))
    for node in _imports_for_module_leaf(tree, "broader_oracle"):
        if not isinstance(node, ast.ImportFrom):
            return False
        for alias in node.names:
            if alias.name == "RevealedObservation" and id(node) not in type_checking_nodes:
                return False
    return True


def _exact_raw_effect_function(node: ast.FunctionDef) -> bool:
    if not (
        not node.decorator_list
        and not node.type_params
        and not node.args.posonlyargs
        and [argument.arg for argument in node.args.args] == ["effect"]
        and isinstance(node.args.args[0].annotation, ast.Name)
        and node.args.args[0].annotation.id == "MatchedEffectObservation"
        and node.args.vararg is None
        and not node.args.kwonlyargs
        and node.args.kwarg is None
        and not node.args.defaults
        and isinstance(node.returns, ast.Name)
        and node.returns.id == "str"
        and len(node.body) == 2
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
        and isinstance(node.body[1], ast.Return)
    ):
        return False
    returned = node.body[1].value
    return bool(
        isinstance(returned, ast.Call)
        and isinstance(returned.func, ast.Attribute)
        and returned.func.attr == "hexdigest"
        and not returned.args
        and not returned.keywords
        and isinstance(returned.func.value, ast.Call)
        and _is_exact_raw_effect_sha256_call(returned.func.value)
    )


def _unresolved_call_counts(
    analysis: QualifiedSymbolAnalysis,
) -> tuple[tuple[tuple[str, ...], str, int], ...]:
    unresolved_calls = tuple(
        call
        for call in analysis.calls
        if call.sensitive_unresolved or (not call.targets and not call.modeled_bound_mutator)
    )
    keys = frozenset((call.scope, call.spelling) for call in unresolved_calls)
    return tuple(
        sorted(
            (
                scope,
                spelling,
                sum(call.scope == scope and call.spelling == spelling for call in unresolved_calls),
            )
            for scope, spelling in keys
        )
    )


def _unresolved_mutation_counts(
    analysis: QualifiedSymbolAnalysis,
) -> tuple[tuple[tuple[str, ...], str, int], ...]:
    keys = frozenset(
        (mutation.scope, mutation.spelling) for mutation in analysis.unresolved_mutations
    )
    return tuple(
        sorted(
            (
                scope,
                spelling,
                sum(
                    mutation.scope == scope and mutation.spelling == spelling
                    for mutation in analysis.unresolved_mutations
                ),
            )
            for scope, spelling in keys
        )
    )


def _exact_replay_function_signature(node: ast.FunctionDef) -> bool:
    expected_keyword_annotations = (
        ("run_id", "str"),
        ("world_id", "str"),
        ("seed", "int"),
        ("comparison_group_id", "str"),
        ("group_index", "int"),
        ("expected_observations", "tuple[RevealedObservation, ...]"),
        ("expected_effects", "tuple[MatchedEffectObservation, ...]"),
        ("physical_cost", "float"),
        ("recorded_observations", "tuple[RevealedObservation, ...] | None"),
        ("recorded_effects", "tuple[MatchedEffectObservation, ...] | None"),
        ("source_sequence_cutoff", "int"),
    )
    actual_keyword_annotations = tuple(
        (
            argument.arg,
            "" if argument.annotation is None else ast.unparse(argument.annotation),
        )
        for argument in node.args.kwonlyargs
    )
    defaults = node.args.kw_defaults
    return bool(
        not node.decorator_list
        and not node.type_params
        and not node.args.posonlyargs
        and not node.args.args
        and node.args.vararg is None
        and node.args.kwarg is None
        and not node.args.defaults
        and actual_keyword_annotations == expected_keyword_annotations
        and len(defaults) == len(expected_keyword_annotations)
        and all(default is None for default in defaults[:8])
        and all(
            isinstance(default, ast.Constant) and default.value is None
            for default in defaults[8:10]
        )
        and isinstance(defaults[10], ast.Name)
        and defaults[10].id == "CALIBRATION_SOURCE_SEQUENCE_CUTOFF"
        and isinstance(node.returns, ast.Name)
        and node.returns.id == "CalibrationHistorySelection"
        and node.type_comment is None
    )


def _is_exact_projection_dataclass(node: ast.ClassDef) -> bool:
    if not (
        not node.bases
        and not node.keywords
        and not node.type_params
        and len(node.decorator_list) == 1
        and isinstance(node.decorator_list[0], ast.Call)
    ):
        return False
    decorator = node.decorator_list[0]
    return bool(
        isinstance(decorator.func, ast.Name)
        and decorator.func.id == "dataclass"
        and not decorator.args
        and len(decorator.keywords) == 2
        and {
            keyword.arg: keyword.value.value
            for keyword in decorator.keywords
            if keyword.arg is not None and isinstance(keyword.value, ast.Constant)
        }
        == {"frozen": True, "slots": True}
    )


def _returned_run_class_definitions_are_exact(tree: ast.Module) -> bool:
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    all_classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    if len(classes) != EXPECTED_AUTHORIZED_TOP_LEVEL_CLASS_COUNT:
        return False
    if len(all_classes) != len(classes):
        return False
    if {node.name for node in classes} != set(AUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES):
        return False
    for node in classes:
        if node.name == "ReturnedRunProjectionError":
            if not (
                not node.decorator_list
                and not node.keywords
                and not node.type_params
                and len(node.bases) == 1
                and isinstance(node.bases[0], ast.Name)
                and node.bases[0].id == "ValueError"
            ):
                return False
        elif not _is_exact_projection_dataclass(node):
            return False
    return True


def _returned_run_type_aliases_are_exact(tree: ast.Module) -> bool:
    aliases = [node for node in tree.body if isinstance(node, ast.TypeAlias)]
    if len(aliases) != len(AUTHORIZED_RETURNED_RUN_TYPE_ALIAS_VALUES):
        return False
    actual = tuple(
        sorted(
            (
                node.name.id,
                ast.unparse(node.value),
                len(node.type_params),
            )
            for node in aliases
        )
    )
    expected = tuple(
        sorted((name, value, 0) for name, value in AUTHORIZED_RETURNED_RUN_TYPE_ALIAS_VALUES)
    )
    return actual == expected


def _top_level_binding_events_are_unique(analysis: QualifiedSymbolAnalysis) -> bool:
    events = [
        (binding.name, binding.kind) for binding in analysis.binding_events if binding.top_level
    ]
    names = [name for name, _kind in events]
    return len(names) == len(set(names))


def _module_scope_statements(tree: ast.Module) -> tuple[ast.stmt, ...]:
    statements: list[ast.stmt] = []

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                statements.append(child)
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            visit(child)

    visit(tree)
    return tuple(statements)


def _module_scope_is_free_of_delete_and_augassign(tree: ast.Module) -> bool:
    return not any(
        isinstance(node, (ast.Delete, ast.AugAssign)) for node in _module_scope_statements(tree)
    )


def _implicit_execution_surface_is_closed(tree: ast.Module) -> bool:
    return not any(
        isinstance(node, (ast.With, ast.AsyncWith))
        or (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and bool(node.decorator_list))
        for node in ast.walk(tree)
    )


def _returned_top_level_statement_surface_is_closed(tree: ast.Module) -> bool:
    allowed = (
        ast.AnnAssign,
        ast.ClassDef,
        ast.Expr,
        ast.FunctionDef,
        ast.Import,
        ast.ImportFrom,
        ast.TypeAlias,
    )
    expressions = [node for node in tree.body if isinstance(node, ast.Expr)]
    return bool(
        tree.body
        and len(expressions) == 1
        and tree.body[0] is expressions[0]
        and isinstance(expressions[0].value, ast.Constant)
        and isinstance(expressions[0].value.value, str)
        and all(isinstance(node, allowed) for node in tree.body)
    )


def _helper_top_level_statement_surface_is_closed(tree: ast.Module) -> bool:
    expressions = [node for node in tree.body if isinstance(node, ast.Expr)]
    type_checking = [
        node
        for node in tree.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "TYPE_CHECKING"
    ]
    if not (
        tree.body
        and len(expressions) == 1
        and tree.body[0] is expressions[0]
        and isinstance(expressions[0].value, ast.Constant)
        and isinstance(expressions[0].value.value, str)
        and len(type_checking) == 1
        and len(type_checking[0].body) == 1
        and isinstance(type_checking[0].body[0], ast.ImportFrom)
        and not type_checking[0].orelse
        and all(
            isinstance(node, (ast.Expr, ast.FunctionDef, ast.If, ast.Import, ast.ImportFrom))
            for node in tree.body
        )
    ):
        return False
    guarded_ids = {id(node) for node in ast.walk(type_checking[0])}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        aliases = tuple(node.names)
        has_oracle_type = isinstance(node, ast.ImportFrom) and any(
            alias.name == "RevealedObservation" for alias in aliases
        )
        if has_oracle_type != (id(node) in guarded_ids):
            return False
    return True


def _returned_run_protected_binding_kinds_are_exact(
    analysis: QualifiedSymbolAnalysis,
) -> bool:
    actual = {binding.name: binding.kind for binding in analysis.bindings if binding.top_level}
    expected = {
        **{name: "class" for name in AUTHORIZED_TOP_LEVEL_PROJECTION_CLASSES},
        **{name: "annassign" for name in AUTHORIZED_RETURNED_RUN_TOP_LEVEL_ASSIGNMENTS},
        **{name: "type-alias" for name in AUTHORIZED_RETURNED_RUN_TYPE_ALIASES},
        **{name: "import" for name, _origin in AUTHORIZED_RETURNED_RUN_IMPORT_BINDINGS},
        **{name: "function" for name in AUTHORIZED_RETURNED_RUN_TOP_LEVEL_FUNCTIONS},
    }
    return all(actual.get(name) == kind for name, kind in expected.items())


def _helper_hash_callable_references_are_exact(
    tree: ast.Module,
    raw_function: ast.FunctionDef | None,
    protocol_call: ast.Call | None,
) -> bool:
    hashlib_references = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id == "hashlib"
    ]
    sha256_references = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.ctx, ast.Load)
        and isinstance(node.value, ast.Name)
        and node.value.id == "hashlib"
        and node.attr == "sha256"
    ]
    protocol_hash_references = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id == "protocol_hash"
    ]
    if not (
        raw_function is not None
        and raw_function.body
        and isinstance(raw_function.body[-1], ast.Return)
        and isinstance(raw_function.body[-1].value, ast.Call)
    ):
        return False
    hexdigest_call = raw_function.body[-1].value
    if not (
        isinstance(hexdigest_call.func, ast.Attribute)
        and isinstance(hexdigest_call.func.value, ast.Call)
        and isinstance(hexdigest_call.func.value.func, ast.Attribute)
    ):
        return False
    approved_sha256_reference = hexdigest_call.func.value.func
    return bool(
        len(hashlib_references) == 1
        and isinstance(approved_sha256_reference.value, ast.Name)
        and hashlib_references[0] is approved_sha256_reference.value
        and len(sha256_references) == 1
        and sha256_references[0] is approved_sha256_reference
        and len(protocol_hash_references) == 1
        and protocol_call is not None
        and protocol_hash_references[0] is protocol_call.func
    )


def _exact_selection_protocol_hash_call(
    replay_function: ast.FunctionDef | None,
    protocol_call: ast.Call | None,
) -> bool:
    if not (
        protocol_call is not None
        and isinstance(protocol_call.func, ast.Name)
        and protocol_call.func.id == "protocol_hash"
        and len(protocol_call.args) == 2
        and not protocol_call.keywords
        and isinstance(protocol_call.args[0], ast.Name)
        and protocol_call.args[0].id == "CALIBRATION_SELECTION_VERSION"
        and isinstance(protocol_call.args[1], ast.Name)
        and protocol_call.args[1].id == "identity_values"
    ):
        return False
    if not (
        replay_function is not None
        and replay_function.body
        and isinstance(replay_function.body[-1], ast.Return)
        and isinstance(replay_function.body[-1].value, ast.Call)
    ):
        return False
    constructor = replay_function.body[-1].value
    return bool(
        isinstance(constructor.func, ast.Name)
        and constructor.func.id == "CalibrationHistorySelection"
        and any(
            keyword.arg == "selection_identity" and keyword.value is protocol_call
            for keyword in constructor.keywords
        )
    )


def _helper_has_mutation_target(tree: ast.Module) -> bool:
    def mutates(target: ast.expr) -> bool:
        if isinstance(target, ast.Starred):
            return mutates(target.value)
        if isinstance(target, (ast.Tuple, ast.List)):
            return any(mutates(item) for item in target.elts)
        return isinstance(target, (ast.Attribute, ast.Subscript))

    for node in ast.walk(tree):
        if isinstance(node, ast.AugAssign):
            return True
        if isinstance(node, ast.Assign):
            targets: tuple[ast.expr, ...] = tuple(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
        elif isinstance(node, ast.Delete):
            targets = tuple(node.targets)
        else:
            continue
        if any(mutates(target) for target in targets):
            return True
    return False


def selector_replay_helper_architecture_checks(
    source: str,
    *,
    analysis: QualifiedSymbolAnalysis | None = None,
) -> tuple[tuple[str, bool], ...]:
    """Return the alias-aware closed-surface checks for the replay helper."""

    tree = ast.parse(source)
    if analysis is None:
        analysis = analyze_qualified_symbols(
            source,
            module_name=CALIBRATION_SELECTOR_REPLAY_MODULE_NAME,
        )
    elif (
        analysis.source_text != source
        or analysis.module_name != CALIBRATION_SELECTOR_REPLAY_MODULE_NAME
    ):
        raise ValueError("precomputed analysis does not match the selector-replay source")
    top_level_functions = frozenset(
        binding.name
        for binding in analysis.bindings
        if binding.top_level and binding.kind == "function"
    )
    all_classes = tuple(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
    all_functions = tuple(
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    top_level_assignments = _top_level_binding_names(analysis, _TOP_LEVEL_VALUE_BINDING_KINDS)
    top_level_binding_kinds = frozenset(
        (binding.name, binding.kind) for binding in analysis.bindings if binding.top_level
    )
    top_level_binding_events = tuple(
        sorted(
            (binding.name, binding.kind) for binding in analysis.binding_events if binding.top_level
        )
    )
    expected_top_level_binding_events = tuple(
        sorted(AUTHORIZED_SELECTOR_REPLAY_TOP_LEVEL_BINDING_KINDS)
    )
    raw_functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "raw_effect_sha256"
    ]
    raw_function = raw_functions[0] if len(raw_functions) == 1 else None
    replay_functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "replay_calibration_history_selection"
    ]
    replay_function = replay_functions[0] if len(replay_functions) == 1 else None
    sha_call_count = sum(
        target == "hashlib.sha256" for call in analysis.calls for target in call.targets
    )
    protocol_call_count = sum(
        target == "research_decision_engine.benchmarks.broader_protocol.protocol_hash"
        for call in analysis.calls
        for target in call.targets
    )
    protocol_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "protocol_hash"
    ]
    protocol_call = protocol_calls[0] if len(protocol_calls) == 1 else None
    sensitive_alias_origins = frozenset(
        {
            "hashlib",
            "hashlib.sha256",
            "research_decision_engine.benchmarks.broader_protocol.protocol_hash",
        }
    )
    sensitive_aliases = tuple(
        binding
        for binding in analysis.bindings
        if not _TOP_LEVEL_VALUE_BINDING_KINDS.isdisjoint(binding.kind.split("+"))
        and not binding.origins.isdisjoint(sensitive_alias_origins)
    )
    finding_codes = frozenset(finding.code for finding in analysis.findings)
    forbidden_calls = frozenset(
        target
        for call in analysis.calls
        for target in call.targets
        if _qualified_call_target_is_forbidden(target)
    ) | frozenset(
        target
        for reference in analysis.references
        for target in reference.targets
        if _qualified_call_target_is_forbidden(target)
    )
    external_calls = _external_call_targets(
        analysis,
        CALIBRATION_SELECTOR_REPLAY_MODULE_NAME,
    )
    unresolved_calls = tuple(
        sorted(
            (call.scope, call.spelling)
            for call in analysis.calls
            if not call.targets and not call.modeled_bound_mutator
        )
    )
    return (
        (
            "exact-helper-import-bindings",
            _runtime_import_bindings(analysis) == AUTHORIZED_SELECTOR_REPLAY_IMPORT_BINDINGS
            and _import_occurrences(analysis)
            == _authorized_import_occurrences(
                AUTHORIZED_SELECTOR_REPLAY_IMPORT_BINDINGS,
                frozenset({"hashlib", "statistics"}),
            ),
        ),
        ("exact-helper-future-import", _future_import_features(analysis) == {"annotations"}),
        (
            "closed-helper-top-level-statement-surface",
            _helper_top_level_statement_surface_is_closed(tree),
        ),
        (
            "exact-helper-function-surface",
            top_level_functions == {"raw_effect_sha256", "replay_calibration_history_selection"},
        ),
        (
            "exact-helper-top-level-binding-surface",
            top_level_binding_kinds == AUTHORIZED_SELECTOR_REPLAY_TOP_LEVEL_BINDING_KINDS,
        ),
        (
            "exact-helper-binding-events",
            top_level_binding_events == expected_top_level_binding_events,
        ),
        ("no-helper-class", not all_classes),
        (
            "exact-all-helper-function-definitions",
            len(all_functions) == 2
            and all(isinstance(node, ast.FunctionDef) for node in all_functions)
            and {node.name for node in all_functions}
            == {"raw_effect_sha256", "replay_calibration_history_selection"},
        ),
        (
            "no-helper-later-stage-binding",
            not any(
                _is_forbidden_binding_name(binding.name) for binding in analysis.binding_events
            ),
        ),
        (
            "no-helper-async-function",
            not _top_level_binding_names(analysis, frozenset({"async-function"})),
        ),
        (
            "no-helper-module-delete-or-augassign",
            _module_scope_is_free_of_delete_and_augassign(tree),
        ),
        ("closed-helper-implicit-execution-surface", _implicit_execution_surface_is_closed(tree)),
        (
            "no-helper-generator-function-surface",
            not any(isinstance(node, (ast.Yield, ast.YieldFrom)) for node in ast.walk(tree)),
        ),
        ("no-helper-constant-or-alias", not top_level_assignments),
        ("no-helper-export", not analysis.exports and "__all__" not in top_level_assignments),
        (
            "no-helper-module-hook",
            "dynamic-module-hook" not in finding_codes,
        ),
        ("one-unaliased-hashlib-import", _has_exact_hashlib_import(tree)),
        (
            "one-exact-raw-digest-function",
            isinstance(raw_function, ast.FunctionDef) and _exact_raw_effect_function(raw_function),
        ),
        (
            "exact-replay-entry-point-signature",
            isinstance(replay_function, ast.FunctionDef)
            and _exact_replay_function_signature(replay_function),
        ),
        ("one-resolved-sha256-call", sha_call_count == 1),
        ("no-sensitive-hash-alias", not sensitive_aliases),
        (
            "exact-helper-hash-callable-reference-surface",
            _helper_hash_callable_references_are_exact(tree, raw_function, protocol_call),
        ),
        (
            "one-exact-selection-protocol-hash",
            protocol_call_count == 1
            and _exact_selection_protocol_hash_call(replay_function, protocol_call),
        ),
        (
            "exact-helper-qualified-call-surface",
            external_calls == AUTHORIZED_SELECTOR_REPLAY_EXTERNAL_CALLS
            and _external_call_counts(
                analysis,
                CALIBRATION_SELECTOR_REPLAY_MODULE_NAME,
            )
            == AUTHORIZED_SELECTOR_REPLAY_EXTERNAL_CALL_COUNTS,
        ),
        (
            "exact-helper-internal-call-and-reference-sites",
            _normalized_target_sites(
                analysis.calls,
                frozenset(
                    {
                        f"{CALIBRATION_SELECTOR_REPLAY_MODULE_NAME}.raw_effect_sha256",
                    }
                ),
            )
            == AUTHORIZED_SELECTOR_REPLAY_INTERNAL_SITES
            and _normalized_target_sites(
                analysis.references,
                frozenset(
                    {
                        f"{CALIBRATION_SELECTOR_REPLAY_MODULE_NAME}.raw_effect_sha256",
                    }
                ),
            )
            == AUTHORIZED_SELECTOR_REPLAY_INTERNAL_SITES,
        ),
        (
            "exact-helper-unresolved-call-surface",
            unresolved_calls == AUTHORIZED_SELECTOR_REPLAY_UNRESOLVED_CALLS,
        ),
        ("no-helper-forbidden-qualified-call", not forbidden_calls),
        ("no-helper-mutation-target", not _helper_has_mutation_target(tree)),
        ("no-helper-alias-cycle", "alias-cycle" not in finding_codes),
        (
            "no-helper-dynamic-indirection",
            finding_codes.isdisjoint(
                {
                    "dynamic-call",
                    "dynamic-class",
                    "dynamic-module-mutation",
                    "dynamic-namespace-reference",
                    "dynamic-scope-binding",
                    "dynamic-__all__",
                    "qualified-state-mutation",
                    "unresolved-mutator-reference",
                    "unresolved-top-level-binding",
                    "unresolved-call-alias",
                    "unresolved-sensitive-provenance",
                    "forbidden-later-stage-binding",
                }
            ),
        ),
        ("oracle-type-import-is-type-only", _oracle_type_import_is_narrow(tree)),
    )


def hashlib_use_is_authorized_for_path(path: str, source: str) -> bool:
    """Reject raw hashing everywhere except the exact replay-helper path."""

    normalized_path = path.replace("\\", "/")
    analysis = analyze_qualified_symbols(
        source,
        module_name=CALIBRATION_SELECTOR_REPLAY_MODULE_NAME,
    )
    has_hash_surface = any(
        origin == "hashlib" or origin.startswith("hashlib.")
        for binding in (*analysis.imports, *analysis.bindings)
        for origin in binding.origins
    ) or any(target == "hashlib.sha256" for call in analysis.calls for target in call.targets)
    if not has_hash_surface:
        return True
    if not (
        normalized_path == CALIBRATION_SELECTOR_REPLAY_RELATIVE_PATH
        or normalized_path.endswith(f"/{CALIBRATION_SELECTOR_REPLAY_RELATIVE_PATH}")
    ):
        return False
    return all(passed for _name, passed in selector_replay_helper_architecture_checks(source))
