"""Frozen protocol registries for the broader closed-loop replication.

The committed design document is the normative source.  This module reads its
literal fenced registries, validates their declared cardinalities, and exposes
an immutable snapshot without duplicating scientific choices in Python.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, cast

PROTOCOL_VERSION: Final = "broader-closed-loop-replication/v1"
PUBLIC_PROVENANCE_ROLE_TOKEN_SCHEMA: Final = "rde-core-public-provenance-role-token/v1"
PUBLIC_PROVENANCE_ROLE_TOKEN_NAMESPACE: Final = "RDE_CORE_PUBLIC_PROVENANCE_ROLE_V1"


def _public_provenance_role_token(role_name: str) -> str:
    """Derive a public semantic role token without using private provenance."""

    namespace = PUBLIC_PROVENANCE_ROLE_TOKEN_NAMESPACE.encode("ascii")
    role = role_name.encode("ascii")
    return hashlib.sha256(namespace + b"\0" + role + b"\0").hexdigest()[:40]


SOURCE_DESIGN_CHECKPOINT: Final[Literal["ebd1591c7332544c8f991a34ef3936f2e048ca16"]] = cast(
    Literal["ebd1591c7332544c8f991a34ef3936f2e048ca16"],
    _public_provenance_role_token("SOURCE_DESIGN"),
)
PROTOCOL_CHECKPOINT: Final[Literal["89c0b4fadba33b9fd9a257b43eacf476b7779d59"]] = cast(
    Literal["89c0b4fadba33b9fd9a257b43eacf476b7779d59"],
    _public_provenance_role_token("PROTOCOL"),
)
PUBLIC_PROVENANCE_ROLE_TOKENS: Final = frozenset(
    {
        _public_provenance_role_token("EVIDENCE_CONTRACT"),
        PROTOCOL_CHECKPOINT,
        SOURCE_DESIGN_CHECKPOINT,
    }
)
# Compatibility name for the stable public source-design role.  It is not a Git
# revision and must never be passed to a Git command.
SOURCE_CHECKPOINT: Final = SOURCE_DESIGN_CHECKPOINT
DESIGN_FILENAME: Final = "BROADER_REPLICATION_DESIGN.md"
FULL_SEEDS: Final = tuple(range(1000, 1128))
SMOKE_SEEDS: Final = tuple(range(9000, 9004))
SMOKE_WORLD_IDS: Final = (
    "h_adam_low",
    "h_null_high",
    "w_sgd_medium",
    "g_adam_lmh",
    "g_null_hml",
    "c_sgd_a",
    "d2_null",
    "d3_adam",
)
EXPECTED_ORACLE_DOMAIN_SHA256: Final = (
    "0452652278d2670ac11f923a6919cae923b2baf88d2ea9b0356a5d4923dc706c"
)


class ProtocolError(ValueError):
    """Raised when the committed protocol cannot be reconstructed exactly."""


@dataclass(frozen=True, slots=True)
class Registry:
    """One ordered, literal protocol registry."""

    name: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def __post_init__(self) -> None:
        if not self.rows:
            raise ProtocolError(f"Registry {self.name} must not be empty.")
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ProtocolError(f"Registry {self.name} has a malformed row.")

    def records(self) -> tuple[dict[str, str], ...]:
        return tuple(dict(zip(self.columns, row, strict=True)) for row in self.rows)

    def ids(self, column: str) -> tuple[str, ...]:
        try:
            index = self.columns.index(column)
        except ValueError as error:
            raise ProtocolError(f"Registry {self.name} has no {column} column.") from error
        return tuple(row[index] for row in self.rows)


@dataclass(frozen=True, slots=True)
class ProtocolSnapshot:
    """Immutable reconstruction of every frozen literal registry."""

    source_design_sha256: str
    constants: tuple[tuple[str, str], ...]
    registries: tuple[Registry, ...]
    statistical_hypotheses: tuple[dict[str, object], ...]
    research_questions: tuple[dict[str, object], ...]
    artifact_schema_text: tuple[tuple[str, str], ...]

    def registry(self, name: str) -> Registry:
        for registry in self.registries:
            if registry.name == name:
                return registry
        raise ProtocolError(f"Unknown protocol registry: {name}")

    def constant(self, name: str) -> str:
        values = dict(self.constants)
        try:
            return values[name]
        except KeyError as error:
            raise ProtocolError(f"Unknown protocol constant: {name}") from error

    def validate(self) -> None:
        expected = {
            "confirmatory": 66,
            "decision": 20,
            "descriptive": 36,
            "veto": 20,
            "scientific_hypothesis": 3,
            "statistical_hypothesis": 64,
            "metric": 16,
            "estimand": 8,
            "mechanism": 11,
            "population": 22,
            "count_symbol": 9,
            "decision_symbol": 9,
            "predicate": 7,
            "budget": 3,
            "controller_stage": 6,
            "branch": 4,
            "enum": 33,
            "gate": 44,
            "formula": 43,
            "gate_condition": 66,
            "audit": 16,
            "artifact": 13,
        }
        for name, count in expected.items():
            actual = len(self.registry(name).rows)
            if actual != count:
                raise ProtocolError(f"{name} registry has {actual} rows; expected {count}.")

        contrasts = (
            self.registry("confirmatory").ids("contrast_id")
            + self.registry("decision").ids("contrast_id")
            + self.registry("descriptive").ids("contrast_id")
        )
        if len(contrasts) != 122 or len(set(contrasts)) != 122:
            raise ProtocolError("Contrast registry must contain 122 unique literal IDs.")
        holm = tuple(
            record["statistical_hypothesis_id"]
            for record in self.registry("confirmatory").records()
            if record["holm_member"] == "true"
        )
        ordered_holm = tuple(
            str(item["statistical_hypothesis_id"]) for item in self.statistical_hypotheses
        )
        if holm != ordered_holm or len(holm) != 64:
            raise ProtocolError("HOLM-64 order does not match the literal hypothesis registry.")
        if tuple(range(1000, 1128)) != FULL_SEEDS or len(set(FULL_SEEDS)) != 128:
            raise ProtocolError("The frozen full-study seed schedule is invalid.")
        if set(FULL_SEEDS).intersection(SMOKE_SEEDS):
            raise ProtocolError("Smoke seeds overlap full-study seeds.")
        if int(self.constant("oracle_domain_count")) != 117_952:
            raise ProtocolError("Oracle domain count changed.")
        if self.constant("oracle_domain_expected_sha256") != EXPECTED_ORACLE_DOMAIN_SHA256:
            raise ProtocolError("Oracle conformance digest changed.")
        _validate_registry_references(self)


@dataclass(frozen=True, slots=True)
class FrozenArm:
    arm_order: int
    arm_id: str
    belief_model_id: str
    policy_id: str


ARMS: Final = (
    FrozenArm(1, "fixed_ig", "fixed_sigma_gaussian", "information_gain"),
    FrozenArm(
        2,
        "calibrated_ig",
        "replicated_noise_calibrated_gaussian",
        "information_gain",
    ),
    FrozenArm(
        3,
        "fixed_lookahead",
        "fixed_sigma_gaussian",
        "lookahead_information_gain",
    ),
    FrozenArm(
        4,
        "calibrated_lookahead",
        "replicated_noise_calibrated_gaussian",
        "lookahead_information_gain",
    ),
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def design_path() -> Path:
    return repository_root() / DESIGN_FILENAME


def canonical_json_bytes(value: object, *, final_lf: bool = False) -> bytes:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return encoded + (b"\n" if final_lf else b"")


def f64(value: float) -> str:
    if value == 0.0:
        value = 0.0
    if not (-float("inf") < value < float("inf")):
        raise ProtocolError("F64 values must be finite.")
    return "f64:" + struct.pack(">d", value).hex()


def protocol_hash(namespace: str, payload: object) -> str:
    return hashlib.sha256(
        canonical_json_bytes(["rde.broader.hash/v3", namespace, payload])
    ).hexdigest()


def runtime_id(prefix: str, namespace: str, payload: object) -> str:
    return f"{prefix}:{protocol_hash(namespace, payload)}"


def load_protocol_snapshot(path: Path | None = None) -> ProtocolSnapshot:
    source = (path or design_path()).read_bytes()
    text = source.decode("utf-8")
    blocks = _fenced_blocks(text)

    registry_specs = (
        ("confirmatory", "contrast_id|analysis_class", 66),
        ("decision", "contrast_id|analysis_class", 20),
        ("veto", "veto_id|formula_id", 20),
        ("descriptive", "contrast_id|analysis_class", 36),
        ("scientific_hypothesis", "hypothesis_order|scientific_hypothesis_id", 3),
        ("metric", "metric_order|metric_id", 16),
        ("estimand", "estimand_order|estimand_id", 8),
        ("mechanism", "mechanism_order|mechanism_id", 11),
        ("population", "population_id|policy_scope|eligible rows|weighting", 22),
        ("count_symbol", "symbol_order|symbol_id|value_type|definition", 9),
        ("decision_symbol", "symbol_order|symbol_id|value_type|producer_formula_id", 9),
        ("predicate", "predicate_order|predicate_id", 7),
        ("budget", "budget_order|budget_id|budget", 3),
        ("controller_stage", "stage_order|controller_stage_id", 6),
        ("branch", "branch_order|branch_id", 4),
        ("enum", "enum_order|enum_id", 33),
        ("gate", "gate_order|gate_id|formula_id", 44),
        ("formula", "formula_order|formula_id", 43),
        ("gate_condition", "condition_order|condition_id", 66),
        ("audit", "audit_order|audit_id|requirement", 16),
        ("artifact", "order|filename|schema_version|format", 13),
    )
    registries: list[Registry] = []
    for specification in registry_specs:
        name, prefix, expected = specification
        candidates = [block for block in blocks if block.startswith(prefix)]
        parsed: list[Registry] = []
        for candidate in candidates:
            try:
                registry = _parse_registry(name, candidate)
            except ProtocolError:
                continue
            if len(registry.rows) == expected:
                parsed.append(registry)
        if len(parsed) != 1:
            raise ProtocolError(f"Could not locate literal {name} registry.")
        registries.append(parsed[0])

    constants_block = next(block for block in blocks if block.startswith("protocol_version="))
    constant_rows: list[tuple[str, str]] = []
    for line in constants_block.splitlines():
        if line and "=" in line:
            key, value = line.split("=", 1)
            constant_rows.append((key, value))
    constants = tuple(constant_rows)
    statistical_block = next(block for block in blocks if block.startswith('[{"order":1,'))
    statistical = tuple(json.loads(statistical_block))
    statistical_registry = Registry(
        name="statistical_hypothesis",
        columns=("order", "statistical_hypothesis_id", "contrast_id"),
        rows=tuple(
            (
                str(item["order"]),
                str(item["statistical_hypothesis_id"]),
                str(item["contrast_id"]),
            )
            for item in statistical
        ),
    )
    registries.append(statistical_registry)

    research_block = next(block for block in blocks if block.startswith("[\n  {"))
    questions = tuple(json.loads(research_block))
    question_registry = Registry(
        name="research_question",
        columns=("research_question_id",),
        rows=tuple((str(item["research_question_id"]),) for item in questions),
    )
    registries.append(question_registry)

    schemas = tuple(
        (f"block-{index:02d}", block)
        for index, block in enumerate(blocks, start=1)
        if any(
            token in block
            for token in (
                "CandidateSpec={",
                "constants:MAP<",
                "run_id:ID,comparison_id:ID",
                "OracleKeyRow={",
                "sigma_estimate_id:ID,calibration_prefix_id",
                "CanonicalEventRow={",
                "ComparisonShared={",
                "contrast_id,analysis_class",
                "BootstrapRow={",
                "evaluation_id:ID\ngates:",
                "evaluation_id:ID\naudits:",
                "arm_runs=36864",
                "recommendation:recommendation",
            )
        )
    )
    snapshot = ProtocolSnapshot(
        source_design_sha256=hashlib.sha256(source).hexdigest(),
        constants=constants,
        registries=tuple(registries),
        statistical_hypotheses=statistical,
        research_questions=questions,
        artifact_schema_text=schemas,
    )
    snapshot.validate()
    return snapshot


def registry_content_hash(
    *,
    entity_type: str,
    literal_id: str,
    ordered_field_names: Sequence[str],
    field_values: Sequence[object],
) -> str:
    return protocol_hash(
        "registry_content/v1",
        {
            "schema_version": "registry-content/v1",
            "entity_type": entity_type,
            "literal_id": literal_id,
            "ordered_field_names": list(ordered_field_names),
            "field_values": list(field_values),
        },
    )


def assert_unique_owner(snapshot: ProtocolSnapshot, identifiers: Iterable[str]) -> None:
    owners: dict[str, list[str]] = {}
    for registry in snapshot.registries:
        id_column = _registry_id_column(registry)
        if id_column is None:
            continue
        for identifier in registry.ids(id_column):
            owners.setdefault(identifier, []).append(registry.name)
    for identifier in identifiers:
        matches = owners.get(identifier, [])
        if len(matches) != 1:
            raise ProtocolError(f"Protocol ID {identifier!r} has {len(matches)} owners: {matches}.")


def _registry_id_column(registry: Registry) -> str | None:
    fields = {
        "confirmatory": "contrast_id",
        "decision": "contrast_id",
        "descriptive": "contrast_id",
        "veto": "veto_id",
        "scientific_hypothesis": "scientific_hypothesis_id",
        "statistical_hypothesis": "statistical_hypothesis_id",
        "metric": "metric_id",
        "estimand": "estimand_id",
        "mechanism": "mechanism_id",
        "population": "population_id",
        "count_symbol": "symbol_id",
        "decision_symbol": "symbol_id",
        "predicate": "predicate_id",
        "budget": "budget_id",
        "controller_stage": "controller_stage_id",
        "branch": "branch_id",
        "enum": "enum_id",
        "gate": "gate_id",
        "formula": "formula_id",
        "gate_condition": "condition_id",
        "audit": "audit_id",
        "artifact": "filename",
        "research_question": "research_question_id",
    }
    return fields.get(registry.name)


def _validate_registry_references(snapshot: ProtocolSnapshot) -> None:
    owners: dict[str, str] = {}
    for registry in snapshot.registries:
        id_column = _registry_id_column(registry)
        if id_column is None:
            continue
        for identifier in registry.ids(id_column):
            if identifier in owners:
                raise ProtocolError(
                    f"Protocol ID {identifier!r} is owned by both {owners[identifier]} "
                    f"and {registry.name}."
                )
            owners[identifier] = registry.name
    enum_values = {
        value
        for record in snapshot.registry("enum").records()
        for value in record["ordered_values"].split(";")
    }

    def require(identifier: str, owner: str | tuple[str, ...], path: str) -> None:
        if identifier == "null":
            return
        actual = owners.get(identifier)
        expected = (owner,) if isinstance(owner, str) else owner
        if actual not in expected:
            raise ProtocolError(
                f"{path} references {identifier!r} owned by {actual!r}, expected {expected}."
            )

    for question in snapshot.research_questions:
        question_id = str(question["research_question_id"])

        def question_ids(
            field: str,
            record: dict[str, object] = question,
            path: str = question_id,
        ) -> tuple[str, ...]:
            value = record[field]
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ProtocolError(f"{path}.{field} must be a list of literal IDs.")
            return tuple(value)

        for identifier in question_ids("estimand_ids"):
            require(identifier, "estimand", question_id)
        for identifier in question_ids("contrast_ids"):
            require(identifier, ("confirmatory", "decision", "descriptive"), question_id)
        for identifier in question_ids("statistical_hypothesis_ids"):
            require(identifier, "statistical_hypothesis", question_id)
        for identifier in question_ids("gate_ids"):
            require(identifier, "gate", question_id)
        for identifier in question_ids("descriptive_only_ids"):
            require(identifier, "descriptive", question_id)
        for literal in question_ids("decision_uses"):
            if literal not in enum_values:
                require(literal, "decision_symbol", question_id)

    for record in snapshot.registry("statistical_hypothesis").records():
        require(record["contrast_id"], "confirmatory", record["statistical_hypothesis_id"])

    contrasts = (
        snapshot.registry("confirmatory").records()
        + snapshot.registry("decision").records()
        + snapshot.registry("descriptive").records()
    )
    for record in contrasts:
        path = record["contrast_id"]
        require(record["research_question_id"], "research_question", path)
        require(record["population_scope"], "population", path)
        require(record["metric_id"], "metric", path)
        require(record["estimand_id"], "estimand", path)
        for field in ("numerator", "denominator", "missingness_rule"):
            require(record[field], "formula", path)
        for field in ("ci_method", "permutation_method"):
            if record[field] not in {"reuse_source", "none"}:
                require(record[field], "formula", path)
        require(record["statistical_hypothesis_id"], "statistical_hypothesis", path)
        require(record["gate_id"], "gate", path)
        require(
            record["source_contrast_id"],
            ("confirmatory", "decision", "descriptive"),
            path,
        )
        if record["decision_use"] != "null":
            for identifier in record["decision_use"].split(";"):
                require(identifier, "decision_symbol", path)

    for record in snapshot.registry("veto").records():
        path = record["veto_id"]
        require(record["formula_id"], "formula", path)
        require(record["decision_contrast_id"], "decision", path)
        require(record["mechanism_id"], "mechanism", path)
        require(record["population_scope"], "population", path)
        require(record["own_confirmatory_contrast_id"], "confirmatory", path)
        require(record["required_veto_contrast_id"], "confirmatory", path)

    for record in snapshot.registry("decision_symbol").records():
        require(record["producer_formula_id"], "formula", record["symbol_id"])
    for record in snapshot.registry("gate").records():
        path = record["gate_id"]
        require(record["formula_id"], "formula", path)
        for identifier in record["required sources"].split(";"):
            if identifier in owners:
                continue
            raise ProtocolError(f"{path} has unresolved required source {identifier!r}.")
    for record in snapshot.registry("gate_condition").records():
        path = record["condition_id"]
        require(record["gate_id"], "gate", path)
        for identifier in record["ordered_operand_ids"].split(";"):
            if identifier not in owners:
                raise ProtocolError(f"{path} has unresolved operand {identifier!r}.")
    for record in snapshot.registry("controller_stage").records():
        if not record["allowed_event_types"]:
            raise ProtocolError("Controller stage has no allowed event type.")
    for record in snapshot.registry("branch").records():
        path = record["branch_id"]
        for identifier in record["ordered_condition_ids"].split(";"):
            require(identifier, "gate_condition", path)
        require(record["first_decisive_condition_id"], "gate_condition", path)


def _parse_registry(name: str, block: str) -> Registry:
    lines = tuple(line for line in block.splitlines() if line)
    columns = tuple(lines[0].split("|"))
    rows = tuple(tuple(line.split("|")) for line in lines[1:])
    return Registry(name=name, columns=columns, rows=rows)


def _fenced_blocks(text: str) -> tuple[str, ...]:
    return tuple(
        match.group(1).strip("\n") for match in re.finditer(r"```(?:\w+)?\n(.*?)```", text, re.S)
    )


def scalar_constant(value: str) -> str | int | float | bool:
    if value == "true":
        return True
    if value == "false":
        return False
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?(?:\d+\.\d*|\d*\.\d+|\d+e-?\d+)", value, re.I):
        return float(value)
    return value


def ordered_map(mapping: Mapping[str, object]) -> dict[str, object]:
    return {key: mapping[key] for key in sorted(mapping, key=lambda item: item.encode("utf-8"))}
