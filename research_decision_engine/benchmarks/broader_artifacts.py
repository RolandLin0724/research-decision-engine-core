"""Canonical artifact contracts and deterministic serialization."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import struct
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from research_decision_engine.belief_models import CALIBRATED_SIGMA_MODEL_ID
from research_decision_engine.benchmarks.broader_protocol import (
    ARMS,
    FULL_SEEDS,
    PROTOCOL_CHECKPOINT,
    PROTOCOL_VERSION,
    SMOKE_SEEDS,
    ProtocolSnapshot,
    canonical_json_bytes,
    f64,
    load_protocol_snapshot,
    registry_content_hash,
    scalar_constant,
)
from research_decision_engine.benchmarks.broader_worlds import (
    CANDIDATE_CATALOG,
    CANDIDATES_BY_ID,
    COST_CATALOGS,
    GROUP_IDS,
    MIDPOINTS,
    WORLDS,
)

type ArtifactFormat = Literal["JSON", "JSONL", "CSV"]

ID_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*\Z")
SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}\Z")
GIT40_PATTERN: Final = re.compile(r"[0-9a-f]{40}\Z")
F64_PATTERN: Final = re.compile(r"f64:[0-9a-f]{16}\Z")


class ArtifactValidationError(ValueError):
    """Raised before any invalid canonical artifact can be finalized."""


@dataclass(frozen=True, slots=True)
class RecordContract:
    required_fields: frozenset[str]
    nullable_fields: frozenset[str] = frozenset()
    primary_key: str | None = None

    def validate(self, record: Mapping[str, object], *, path: str) -> None:
        actual = frozenset(record)
        if actual != self.required_fields:
            missing = sorted(self.required_fields - actual)
            extra = sorted(actual - self.required_fields)
            raise ArtifactValidationError(
                f"{path} fields differ from contract; missing={missing}, extra={extra}."
            )
        for field in self.required_fields - self.nullable_fields:
            if record[field] is None:
                raise ArtifactValidationError(f"{path}.{field} must not be null.")
        if self.primary_key is not None:
            validate_id(record[self.primary_key], f"{path}.{self.primary_key}")


@dataclass(frozen=True, slots=True)
class TaggedRecordContract:
    discriminator: str
    variants: tuple[tuple[str, RecordContract], ...]
    primary_key: str | None

    @property
    def required_fields(self) -> frozenset[str]:
        fields: frozenset[str] = frozenset()
        for _, contract in self.variants:
            fields |= contract.required_fields
        return fields

    def validate(self, record: Mapping[str, object], *, path: str) -> None:
        value = record.get(self.discriminator)
        for literal, contract in self.variants:
            if value == literal:
                contract.validate(record, path=path)
                return
        raise ArtifactValidationError(f"{path} has an unknown {self.discriminator} variant.")


type ExecutableRecordContract = RecordContract | TaggedRecordContract


@dataclass(frozen=True, slots=True)
class ArtifactContract:
    order: int
    filename: str
    schema_version: str
    format: ArtifactFormat
    primary_key: str
    row_order: str
    record_contract: ExecutableRecordContract


ENVELOPE_FIELDS: Final = (
    "schema_version",
    "protocol_version",
    "source_design_sha256",
    "source_checkpoint_identifier",
    "scientific_payload_sha256",
)

ARM_RUN_FIELDS: Final = frozenset(
    {
        "run_id",
        "comparison_id",
        "arm_id",
        "world_id",
        "seed",
        "budget_id",
        "budget",
        "policy_id",
        "belief_model_id",
        "lineage_id",
        "store_id",
        "initial_probabilities",
        "final_probabilities",
        "scientific_hypothesis_id",
        "metrics",
        "decision_ids",
        "event_ids",
        "calibration_prefix_ids",
        "run_status",
        "terminal_reason",
        "ordered_decisions_sha256",
        "reconciliation_sha256",
        "trajectory_sha256",
    }
)
# This declaration order is the frozen B.3.5 schema order. Canonical JSON still uses the
# independently frozen UTF-8 key ordering from Section 9.2.
CALIBRATION_FIELD_ORDER: Final = (
    "sigma_estimate_id",
    "calibration_prefix_id",
    "world_id",
    "seed",
    "comparison_group_id",
    "effect_ids",
    "replication_ids",
    "source_candidate_pairs",
    "source_oracle_key_ids",
    "effect_values",
    "sample_count",
    "sample_mean",
    "sample_standard_deviation",
    "sigma_floor",
    "estimated_sigma",
    "target_belief_model_id",
    "target_comparison_group_id",
    "target_intervention_arms",
    "physical_cost",
    "deployment_cost",
    "deployed_run_ids",
    "deployed_lineage_ids",
    "scientific_belief_updated",
)
CALIBRATION_FIELDS: Final = frozenset(CALIBRATION_FIELD_ORDER)
ORACLE_KEY_FIELDS: Final = frozenset(
    {
        "record_type",
        "oracle_key_id",
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
    }
)
ORACLE_USE_FIELDS: Final = frozenset(
    {
        "record_type",
        "oracle_use_id",
        "oracle_key_id",
        "run_id",
        "arm_id",
        "use_kind",
        "authorization_id",
        "decision_id",
        "calibration_prefix_id",
    }
)
COMPARISON_SHARED_FIELDS: Final = frozenset(
    {
        "record_type",
        "comparison_id",
        "policy_id",
        "world_id",
        "seed",
        "budget_id",
        "budget",
        "fixed_run_id",
        "calibrated_run_id",
        "fixed_sequence",
        "calibrated_sequence",
        "nll_difference",
        "brier_difference",
        "decision_cost_difference",
        "outcome_label",
    }
)
DIVERGENCE_ONLY_FIELDS: Final = frozenset(
    {
        "first_divergence_step",
        "fixed_candidate_id",
        "calibrated_candidate_id",
        "pre_divergence_fixed_belief",
        "pre_divergence_calibrated_belief",
        "first_action_divergent",
        "sequence_class",
        "predicate_results",
        "primary_mechanism_id",
        "contributing_mechanism_ids",
        "controller_stage_id",
        "mechanism_row_without_outcome_sha256",
    }
)
BOOTSTRAP_FIELDS: Final = frozenset(
    {
        "record_type",
        "resample_id",
        "contrast_id",
        "replicate_index",
        "seed_preimage_utf8_hex",
        "seed_digest",
        "seed",
        "sampled_position_count",
        "completion_status",
        "result_status",
        "failure_code",
        "sampled_seed_ids_sha256",
        "replicate_estimate",
    }
)
SIGN_FLIP_FIELDS: Final = frozenset(
    (BOOTSTRAP_FIELDS - {"sampled_seed_ids_sha256", "replicate_estimate"})
    | {"sign_vector_sha256", "replicate_statistic", "extreme"}
)

CANONICAL_EVENT_FIELDS: Final = frozenset(
    {
        "schema_version",
        "event_type",
        "event_id",
        "run_id",
        "sequence",
        "comparison_id",
        "world_id",
        "seed",
        "budget_id",
        "arm_id",
        "policy_id",
        "controller_stage_id",
        "candidate_id",
        "public_state_sha256",
        "ordered_decisions_sha256",
        "eligibility_state_sha256",
        "belief_lineage_id",
        "sigma_estimate_id",
        "cost_before",
        "cost_after",
        "status",
        "terminal_reason",
        "integrity_audit_id",
        "event_specific_payload",
    }
)
EVENT_PAYLOAD_FIELDS: Final = {
    "decision": frozenset(
        {
            "decision_id",
            "step",
            "belief_model_id",
            "belief_state_id",
            "active_sigma_estimate_ids",
            "fixed_sigma",
            "remaining_budget",
            "completed_candidate_ids",
            "unexecuted_candidate_ids",
            "publicly_feasible_candidate_ids",
            "affordable_candidate_ids",
            "selected_candidate_id",
            "candidate_scores",
            "planning_branch_tree",
            "fallback_reason",
            "tie_break_order",
        }
    ),
    "setup": frozenset({"decision_id", "setup_completion_id", "cost", "cumulative_decision_cost"}),
    "experiment": frozenset(
        {
            "decision_id",
            "experiment_id",
            "observed_objective",
            "cost",
            "cumulative_decision_cost",
            "oracle_key_id",
            "oracle_use_id",
        }
    ),
    "evidence": frozenset(
        {
            "evidence_id",
            "source_experiment_ids",
            "comparison_group_id",
            "observed_effect",
        }
    ),
    "belief_update": frozenset(
        {
            "belief_update_id",
            "evidence_id",
            "fixed_sigma",
            "belief_before",
            "likelihoods",
            "belief_after",
            "update_rule_version",
        }
    ),
    "terminal": frozenset(
        {
            "final_belief_state_id",
            "remaining_budget",
            "completed_candidate_ids",
            "unexecuted_candidate_ids",
            "publicly_feasible_candidate_ids",
            "affordable_candidate_ids",
            "decision_cost",
            "calibration_cost",
            "required_total_cost",
        }
    ),
}
EVENT_STAGES: Final = {
    "decision": "CONTROLLER-STAGE-SELECTION",
    "setup": "CONTROLLER-STAGE-EXECUTION",
    "experiment": "CONTROLLER-STAGE-EXECUTION",
    "evidence": "CONTROLLER-STAGE-EVIDENCE",
    "belief_update": "CONTROLLER-STAGE-BELIEF-UPDATE",
    "terminal": "CONTROLLER-STAGE-TERMINATION",
}
METRIC_SET_FIELDS: Final = frozenset(
    {
        "true_probability",
        "top_scientific_hypothesis_id",
        "top_probability",
        "prediction_correct",
        "confidently_wrong",
        "nll",
        "brier",
        "posterior_entropy",
        "conditional_brier_efficiency",
        "end_to_end_brier_efficiency",
        "decision_cost",
        "calibration_cost",
        "required_total_cost",
        "physical_cost_share",
        "best_observed_objective",
        "matched_pairs",
        "redundant_selected",
        "irrelevant_selected",
        "outcome_experiments_completed",
        "setup_actions_completed",
        "budget_exhausted",
        "terminal_reason",
    }
)

CONTRAST_HEADER: Final = (
    *ENVELOPE_FIELDS,
    "contrast_id",
    "analysis_class",
    "research_question_id",
    "policy_scope",
    "population_scope",
    "metric_id",
    "estimand_id",
    "source_contrast_id",
    "missingness_counts",
    "n_present",
    "n_absent",
    "present_weight",
    "absent_weight",
    "left_value",
    "right_value",
    "left_denominator",
    "right_denominator",
    "estimate",
    "ci_low",
    "ci_high",
    "usable_bootstrap_replicates",
    "test_statistic",
    "permutation_count",
    "extreme_count",
    "p_raw",
    "p_adjusted",
    "holm_rank",
    "statistical_hypothesis_id",
    "holm_member",
    "result_status",
    "estimability_status",
)

PROTOCOL_SNAPSHOT_FIELDS: Final = frozenset(
    {
        "constants",
        "arms",
        "full_seeds",
        "smoke_seeds",
        "budget_registry",
        "ece_bin_edges",
        "research_question_registry",
        "scientific_hypothesis_registry",
        "statistical_hypothesis_registry",
        "metric_registry",
        "estimand_registry",
        "mechanism_registry",
        "population_registry",
        "count_symbol_registry",
        "decision_symbol_registry",
        "predicate_registry",
        "confirmatory_contrast_registry",
        "decision_contrast_registry",
        "descriptive_contrast_registry",
        "veto_registry",
        "formula_registry",
        "gate_condition_registry",
        "gate_registry",
        "audit_registry",
        "controller_stage_registry",
        "branch_registry",
        "artifact_registry",
        "enum_registry",
        "schema_versions",
        "oracle_transform_version",
        "oracle_domain_count",
        "oracle_domain_expected_sha256",
        "oracle_conformance_generator",
    }
)
WORLD_DEFINITION_FIELDS: Final = frozenset(
    {"candidate_catalog", "cost_catalogs", "midpoint_map", "worlds", "world_registry_sha256"}
)
CONTRAST_RESULT_FIELDS: Final = frozenset(CONTRAST_HEADER[len(ENVELOPE_FIELDS) :])
GATE_EVALUATION_FIELDS: Final = frozenset(
    {
        "evaluation_id",
        "gates",
        "P_RAW",
        "veto_evaluations",
        "VETOED_TUPLES",
        "P",
        "ACTIONABILITY_COMPLETE",
        "VETO_COMPLETE",
        "CONTROLLER_CHANGE_NEEDED",
        "UNIQUE_ACTIONABLE_MECHANISM",
        "unique_mechanism_id",
        "PPO_ELIGIBLE",
        "B_AUTHORIZED",
        "final_branch_id",
        "final_branch_trace",
        "final_gate_status",
        "recommendation",
        "decision_precedence",
    }
)
AUDIT_RESULT_FIELDS: Final = frozenset({"evaluation_id", "audits", "all_passed"})
RUN_MANIFEST_FIELDS: Final = frozenset(
    {"evaluation_id", "status", "expected_counts", "observed_counts", "database_schema_version"}
)
RECOMMENDATION_FIELDS: Final = frozenset(
    {
        "evaluation_id",
        "recommendation",
        "decision_precedence",
        "branch_id",
        "branch_trace",
        "gate_status",
        "integrity_status",
        "gate_evaluation_scientific_payload_sha256",
        "unique_mechanism_id",
        "authorized_policy_scopes",
    }
)


def artifact_contracts(snapshot: ProtocolSnapshot | None = None) -> tuple[ArtifactContract, ...]:
    protocol = snapshot or load_protocol_snapshot()
    row_contracts: dict[str, ExecutableRecordContract] = {
        "protocol_snapshot.json": RecordContract(PROTOCOL_SNAPSHOT_FIELDS),
        "world_definitions.json": RecordContract(WORLD_DEFINITION_FIELDS),
        "arm_runs.jsonl": RecordContract(ARM_RUN_FIELDS, primary_key="run_id"),
        "oracle_provenance.jsonl": TaggedRecordContract(
            "record_type",
            (
                (
                    "oracle_key",
                    RecordContract(
                        ORACLE_KEY_FIELDS,
                        frozenset({"comparison_group_id", "intervention_arm"}),
                        "oracle_key_id",
                    ),
                ),
                (
                    "oracle_use",
                    RecordContract(
                        ORACLE_USE_FIELDS,
                        frozenset({"decision_id", "calibration_prefix_id"}),
                        "oracle_use_id",
                    ),
                ),
            ),
            None,
        ),
        "calibration_estimates.jsonl": RecordContract(
            CALIBRATION_FIELDS, primary_key="sigma_estimate_id"
        ),
        "trajectory_events.jsonl": RecordContract(
            frozenset({"event_payload", "provenance_sha256"})
        ),
        "comparisons.jsonl": TaggedRecordContract(
            "record_type",
            (
                (
                    "nondivergent",
                    RecordContract(COMPARISON_SHARED_FIELDS, primary_key="comparison_id"),
                ),
                (
                    "divergent",
                    RecordContract(
                        COMPARISON_SHARED_FIELDS | DIVERGENCE_ONLY_FIELDS,
                        frozenset({"controller_stage_id"}),
                        "comparison_id",
                    ),
                ),
            ),
            "comparison_id",
        ),
        "contrast_results.csv": RecordContract(
            CONTRAST_RESULT_FIELDS,
            frozenset(
                CONTRAST_RESULT_FIELDS
                - {
                    "contrast_id",
                    "analysis_class",
                    "research_question_id",
                    "policy_scope",
                    "population_scope",
                    "metric_id",
                    "estimand_id",
                    "missingness_counts",
                    "usable_bootstrap_replicates",
                    "holm_member",
                    "result_status",
                    "estimability_status",
                }
            ),
            "contrast_id",
        ),
        "resampling_audit.jsonl": TaggedRecordContract(
            "record_type",
            (
                (
                    "bootstrap",
                    RecordContract(
                        BOOTSTRAP_FIELDS,
                        frozenset({"failure_code", "replicate_estimate"}),
                        "resample_id",
                    ),
                ),
                (
                    "sign_flip",
                    RecordContract(
                        SIGN_FLIP_FIELDS,
                        frozenset({"failure_code", "replicate_statistic", "extreme"}),
                        "resample_id",
                    ),
                ),
            ),
            "resample_id",
        ),
        "gate_evaluations.json": RecordContract(
            GATE_EVALUATION_FIELDS,
            frozenset({"unique_mechanism_id"}),
            "evaluation_id",
        ),
        "audit_results.json": RecordContract(AUDIT_RESULT_FIELDS, primary_key="evaluation_id"),
        "run_manifest.json": RecordContract(RUN_MANIFEST_FIELDS, primary_key="evaluation_id"),
        "recommendation.json": RecordContract(
            RECOMMENDATION_FIELDS,
            frozenset({"unique_mechanism_id"}),
            "evaluation_id",
        ),
    }
    contracts: list[ArtifactContract] = []
    for record in protocol.registry("artifact").records():
        filename = record["filename"]
        contracts.append(
            ArtifactContract(
                order=int(record["order"]),
                filename=filename,
                schema_version=record["schema_version"],
                format=record["format"],  # type: ignore[arg-type]
                primary_key=record["primary key or singleton"],
                row_order=record["row order"],
                record_contract=row_contracts[filename],
            )
        )
    if len(contracts) != 13:
        raise ArtifactValidationError("Exactly 13 canonical artifact contracts are required.")
    return tuple(contracts)


def validate_oracle_record(record: Mapping[str, object]) -> None:
    record_type = record.get("record_type")
    if record_type == "oracle_key":
        RecordContract(
            ORACLE_KEY_FIELDS,
            frozenset({"comparison_group_id", "intervention_arm"}),
            "oracle_key_id",
        ).validate(record, path="OracleKeyRow")
        validate_sha256(record["digest"], "OracleKeyRow.digest")
        validate_sha256(record["outcome_digest"], "OracleKeyRow.outcome_digest")
        return
    if record_type == "oracle_use":
        RecordContract(
            ORACLE_USE_FIELDS,
            frozenset({"decision_id", "calibration_prefix_id"}),
            "oracle_use_id",
        ).validate(record, path="OracleUseRow")
        if (record["decision_id"] is None) == (record["calibration_prefix_id"] is None):
            raise ArtifactValidationError("Oracle use requires exactly one source reference.")
        return
    raise ArtifactValidationError("Unknown oracle record_type.")


def validate_calibration_record(record: Mapping[str, object], *, index: int = 0) -> None:
    """Validate the complete frozen Artifact 5 row shape at the reader boundary."""

    path = f"calibration_estimates.jsonl[{index}]"
    RecordContract(CALIBRATION_FIELDS, primary_key="sigma_estimate_id").validate(record, path=path)
    _validate_record_scalar_types("calibration_estimates.jsonl", record, index)

    def frozen_list(field: str, length: int) -> list[object]:
        value = record[field]
        if not isinstance(value, list):
            raise ArtifactValidationError(f"{path}.{field} must be a JSON LIST.")
        if len(value) != length:
            raise ArtifactValidationError(f"{path}.{field} must contain exactly {length} entries.")
        return value

    def distinct_ids(field: str, length: int) -> list[object]:
        values = frozen_list(field, length)
        for position, value in enumerate(values):
            validate_id(value, f"{path}.{field}[{position}]")
        if len(set(values)) != length:
            raise ArtifactValidationError(f"{path}.{field} must contain distinct IDs.")
        return values

    distinct_ids("effect_ids", 5)
    distinct_ids("replication_ids", 5)
    distinct_ids("source_oracle_key_ids", 10)
    distinct_ids("deployed_run_ids", 6)
    distinct_ids("deployed_lineage_ids", 6)

    pairs = frozen_list("source_candidate_pairs", 5)
    candidates: list[object] = []
    for pair_index, pair in enumerate(pairs):
        if not isinstance(pair, list) or len(pair) != 2:
            raise ArtifactValidationError(
                f"{path}.source_candidate_pairs[{pair_index}] must be a two-ID JSON LIST."
            )
        for candidate_index, candidate_id in enumerate(pair):
            validate_id(
                candidate_id,
                f"{path}.source_candidate_pairs[{pair_index}][{candidate_index}]",
            )
            candidates.append(candidate_id)
    if len(set(candidates)) != 10:
        raise ArtifactValidationError(
            f"{path}.source_candidate_pairs must contain ten distinct candidate IDs."
        )

    effect_values = frozen_list("effect_values", 5)
    for position, value in enumerate(effect_values):
        _decode_f64(value, f"{path}.effect_values[{position}]")

    target_arms = frozen_list("target_intervention_arms", 2)
    for position, arm_id in enumerate(target_arms):
        validate_id(arm_id, f"{path}.target_intervention_arms[{position}]")
    if target_arms != ["adam", "sgd"]:
        raise ArtifactValidationError(
            f"{path}.target_intervention_arms differs from the frozen arm order."
        )
    if record["sample_count"] != 5:
        raise ArtifactValidationError(f"{path}.sample_count must equal 5.")
    if record["sigma_floor"] != f64(0.05):
        raise ArtifactValidationError(f"{path}.sigma_floor must equal the frozen floor.")
    if record["target_belief_model_id"] != CALIBRATED_SIGMA_MODEL_ID:
        raise ArtifactValidationError(
            f"{path}.target_belief_model_id differs from the frozen calibrated model."
        )
    if record["target_comparison_group_id"] != record["comparison_group_id"]:
        raise ArtifactValidationError(
            f"{path}.target_comparison_group_id must equal comparison_group_id."
        )
    if record["scientific_belief_updated"] is not False:
        raise ArtifactValidationError(f"{path}.scientific_belief_updated must be false.")


def validate_comparison_record(record: Mapping[str, object]) -> None:
    if record.get("record_type") == "nondivergent":
        RecordContract(COMPARISON_SHARED_FIELDS, primary_key="comparison_id").validate(
            record, path="NondivergentComparison"
        )
        if record["outcome_label"] != "nondivergent":
            raise ArtifactValidationError("Nondivergent comparison has a nonliteral outcome.")
        return
    if record.get("record_type") == "divergent":
        fields = COMPARISON_SHARED_FIELDS | DIVERGENCE_ONLY_FIELDS
        RecordContract(
            fields,
            frozenset({"controller_stage_id"}),
            "comparison_id",
        ).validate(record, path="DivergentComparison")
        if record["outcome_label"] not in {"helped", "hurt", "mixed"}:
            raise ArtifactValidationError("Divergent comparison has an invalid outcome label.")
        return
    raise ArtifactValidationError("Unknown comparison record_type.")


def validate_resampling_record(record: Mapping[str, object]) -> None:
    record_type = record.get("record_type")
    if record_type == "bootstrap":
        contract = RecordContract(
            BOOTSTRAP_FIELDS,
            frozenset({"failure_code", "replicate_estimate"}),
            "resample_id",
        )
    elif record_type == "sign_flip":
        contract = RecordContract(
            SIGN_FLIP_FIELDS,
            frozenset({"failure_code", "replicate_statistic", "extreme"}),
            "resample_id",
        )
    else:
        raise ArtifactValidationError("Unknown resampling record_type.")
    contract.validate(record, path=f"{record_type}Row")
    complete = record["completion_status"] == "complete"
    valid = record["result_status"] == "valid"
    if complete and record["sampled_position_count"] != 128:
        raise ArtifactValidationError("Completed resampling streams require 128 positions.")
    if valid != (record["failure_code"] is None):
        raise ArtifactValidationError("Resampling result and failure-code nullability disagree.")


def validate_canonical_rows(
    contract: ArtifactContract, rows: Sequence[Mapping[str, object]]
) -> None:
    keys: set[object] = set()
    for index, row in enumerate(rows):
        contract.record_contract.validate(row, path=f"{contract.filename}[{index}]")
        _validate_record_scalar_types(contract.filename, row, index)
        if contract.filename == "arm_runs.jsonl":
            metrics = row["metrics"]
            if not isinstance(metrics, Mapping):
                raise ArtifactValidationError("Arm run metrics must be an object.")
            validate_metric_set(metrics)
            validate_probability_map(
                row["initial_probabilities"], path="ArmRun.initial_probabilities"
            )
            validate_probability_map(row["final_probabilities"], path="ArmRun.final_probabilities")
        if contract.filename == "oracle_provenance.jsonl":
            validate_oracle_record(row)
        elif contract.filename == "calibration_estimates.jsonl":
            validate_calibration_record(row, index=index)
        elif contract.filename == "trajectory_events.jsonl":
            validate_canonical_event_row(row)
        elif contract.filename == "comparisons.jsonl":
            validate_comparison_record(row)
        elif contract.filename == "resampling_audit.jsonl":
            validate_resampling_record(row)
        key_name = contract.record_contract.primary_key
        if contract.filename == "oracle_provenance.jsonl":
            key_name = "oracle_key_id" if row["record_type"] == "oracle_key" else "oracle_use_id"
        if key_name is not None:
            key = row[key_name]
            if key in keys:
                raise ArtifactValidationError(f"Duplicate {key_name} in {contract.filename}.")
            keys.add(key)


def validate_canonical_event_row(record: Mapping[str, object]) -> None:
    """Validate the complete closed six-variant canonical event union."""

    RecordContract(frozenset({"event_payload", "provenance_sha256"})).validate(
        record, path="CanonicalEventRow"
    )
    raw_payload = record["event_payload"]
    if not isinstance(raw_payload, Mapping):
        raise ArtifactValidationError("CanonicalEventRow.event_payload must be an object.")
    payload: Mapping[str, object] = raw_payload
    RecordContract(
        CANONICAL_EVENT_FIELDS,
        frozenset(
            {
                "candidate_id",
                "public_state_sha256",
                "eligibility_state_sha256",
                "sigma_estimate_id",
                "terminal_reason",
                "integrity_audit_id",
            }
        ),
        "event_id",
    ).validate(payload, path="CanonicalEventPayload")
    event_type = payload["event_type"]
    if not isinstance(event_type, str) or event_type not in EVENT_PAYLOAD_FIELDS:
        raise ArtifactValidationError("Canonical event has an unknown event_type.")
    if payload["schema_version"] != "canonical-event-payload/v1":
        raise ArtifactValidationError("Canonical event payload schema version changed.")
    if payload["controller_stage_id"] != EVENT_STAGES[event_type]:
        raise ArtifactValidationError("Canonical event controller stage is incompatible.")
    if payload["status"] != "complete" or payload["integrity_audit_id"] is not None:
        raise ArtifactValidationError("Invalid temporary events cannot be canonicalized.")
    specialized = payload["event_specific_payload"]
    if not isinstance(specialized, Mapping):
        raise ArtifactValidationError("Canonical event specialization must be an object.")
    expected_fields = EVENT_PAYLOAD_FIELDS[event_type]
    if frozenset(specialized) != expected_fields:
        raise ArtifactValidationError("Canonical event specialization fields differ.")
    _validate_event_presence(payload, event_type, specialized)
    expected_provenance = hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()
    if record["provenance_sha256"] != expected_provenance:
        raise ArtifactValidationError("Canonical event provenance SHA-256 does not match payload.")


def validate_metric_set(metrics: Mapping[str, object]) -> None:
    RecordContract(
        METRIC_SET_FIELDS,
        frozenset(
            {
                "conditional_brier_efficiency",
                "end_to_end_brier_efficiency",
                "best_observed_objective",
            }
        ),
    ).validate(metrics, path="MetricSet")
    if metrics["terminal_reason"] not in {
        "candidate_space_exhausted",
        "budget_exhausted",
    }:
        raise ArtifactValidationError("Canonical MetricSet has an invalid terminal reason.")
    if bool(metrics["budget_exhausted"]) != (metrics["terminal_reason"] == "budget_exhausted"):
        raise ArtifactValidationError("MetricSet budget exhaustion does not reconcile.")


def validate_probability_map(value: object, *, path: str) -> None:
    if not isinstance(value, Mapping):
        raise ArtifactValidationError(f"{path} must be a probability map.")
    expected = {
        "optimizer.adam-advantage",
        "optimizer.no-consistent-advantage",
        "optimizer.sgd-advantage",
    }
    if set(value) != expected:
        raise ArtifactValidationError(f"{path} does not contain the three hypotheses.")
    probabilities: list[float] = []
    for raw in value.values():
        if not isinstance(raw, str) or F64_PATTERN.fullmatch(raw) is None:
            raise ArtifactValidationError(f"{path} contains a non-F64 probability.")
        probability = struct.unpack(">d", bytes.fromhex(raw[4:]))[0]
        if not math.isfinite(probability) or probability < 0.0:
            raise ArtifactValidationError(f"{path} contains an invalid probability.")
        probabilities.append(probability)
    if not math.isclose(math.fsum(probabilities), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ArtifactValidationError(f"{path} probabilities do not normalize.")


def _validate_event_presence(
    common: Mapping[str, object],
    event_type: str,
    specialized: Mapping[str, object],
) -> None:
    candidate_required = event_type in {"decision", "setup", "experiment"}
    if (common["candidate_id"] is not None) != candidate_required:
        raise ArtifactValidationError("Canonical event candidate nullability is invalid.")
    public_required = event_type == "decision"
    for field in ("public_state_sha256", "eligibility_state_sha256"):
        if (common[field] is not None) != public_required:
            raise ArtifactValidationError(f"Canonical event {field} nullability is invalid.")
    terminal_required = event_type == "terminal"
    if (common["terminal_reason"] is not None) != terminal_required:
        raise ArtifactValidationError("Canonical event terminal reason nullability is invalid.")
    if event_type in {"decision", "setup", "terminal"} and common["sigma_estimate_id"] is not None:
        raise ArtifactValidationError("This event type forbids a singular sigma estimate.")
    if event_type in {"experiment", "evidence", "belief_update"}:
        calibrated_arm = str(common["arm_id"]).startswith("calibrated_")
        grouped_event = event_type in {"evidence", "belief_update"}
        if event_type == "experiment":
            candidate = CANDIDATES_BY_ID.get(str(common["candidate_id"]))
            grouped_event = candidate is not None and candidate.comparison_group_id in GROUP_IDS
        sigma_required = calibrated_arm and grouped_event
        if (common["sigma_estimate_id"] is not None) != sigma_required:
            raise ArtifactValidationError(
                "Canonical event singular sigma nullability differs from its arm and group."
            )
    if event_type == "decision":
        if specialized["selected_candidate_id"] != common["candidate_id"]:
            raise ArtifactValidationError("Decision selected candidate differs from common field.")
        fixed_model = specialized["belief_model_id"] == "fixed_sigma_gaussian"
        active = specialized["active_sigma_estimate_ids"]
        if not isinstance(active, list):
            raise ArtifactValidationError("Decision active sigma IDs must be a list.")
        if fixed_model and (specialized["fixed_sigma"] is None or active):
            raise ArtifactValidationError("Fixed decision sigma fields are invalid.")
        if not fixed_model and (specialized["fixed_sigma"] is not None or len(active) != 3):
            raise ArtifactValidationError("Calibrated decision sigma fields are invalid.")
    if event_type == "belief_update":
        fixed_arm = str(common["arm_id"]).startswith("fixed_")
        if fixed_arm != (specialized["fixed_sigma"] is not None):
            raise ArtifactValidationError("Belief-update fixed sigma nullability is invalid.")
    if event_type in {"setup", "experiment"}:
        before = _decode_f64(common["cost_before"], "cost_before")
        after = _decode_f64(common["cost_after"], "cost_after")
        cost = _decode_f64(specialized["cost"], "event cost")
        if not math.isclose(after, before + cost, abs_tol=1e-12):
            raise ArtifactValidationError("Action event costs do not reconcile.")
    elif _decode_f64(common["cost_before"], "cost_before") != _decode_f64(
        common["cost_after"], "cost_after"
    ):
        raise ArtifactValidationError("Non-action event changed decision cost.")


def _decode_f64(value: object, path: str) -> float:
    if not isinstance(value, str) or F64_PATTERN.fullmatch(value) is None:
        raise ArtifactValidationError(f"{path} is not canonical F64.")
    result = float(struct.unpack(">d", bytes.fromhex(value[4:]))[0])
    if not math.isfinite(result):
        raise ArtifactValidationError(f"{path} must be finite.")
    return result


def serialize_json_artifact(
    *,
    schema_version: str,
    source_design_sha256: str,
    scientific_fields: Mapping[str, object],
    operational_fields: Mapping[str, object] | None = None,
) -> bytes:
    scientific_payload = canonical_json_bytes(dict(scientific_fields), final_lf=True)
    envelope = _envelope(schema_version, source_design_sha256, scientific_payload)
    document = {**envelope, **scientific_fields, **(operational_fields or {})}
    return canonical_json_bytes(document, final_lf=True)


def serialize_jsonl_artifact(
    *,
    schema_version: str,
    source_design_sha256: str,
    rows: Sequence[Mapping[str, object]],
) -> bytes:
    scientific_payload = b"".join(canonical_json_bytes(row, final_lf=True) for row in rows)
    metadata = _envelope(schema_version, source_design_sha256, scientific_payload)
    return canonical_json_bytes(metadata, final_lf=True) + scientific_payload


def serialize_csv_artifact(
    *,
    schema_version: str,
    source_design_sha256: str,
    rows: Sequence[Mapping[str, object]],
) -> bytes:
    scientific_header = CONTRAST_HEADER[len(ENVELOPE_FIELDS) :]
    scientific_payload = _csv_bytes(scientific_header, rows)
    payload_hash = hashlib.sha256(scientific_payload).hexdigest()
    envelope = {
        "schema_version": schema_version,
        "protocol_version": PROTOCOL_VERSION,
        "source_design_sha256": source_design_sha256,
        "source_checkpoint_identifier": PROTOCOL_CHECKPOINT,
        "scientific_payload_sha256": payload_hash,
    }
    expanded = tuple({**envelope, **row} for row in rows)
    return _csv_bytes(CONTRAST_HEADER, expanded)


def build_protocol_snapshot_payload(
    snapshot: ProtocolSnapshot | None = None,
) -> dict[str, object]:
    protocol = snapshot or load_protocol_snapshot()
    registries = {item.name: item for item in protocol.registries}

    def records(name: str, id_field: str, hash_field: str) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        registry = registries[name]
        for raw in registry.records():
            converted = _convert_registry_record(name, raw)
            converted[hash_field] = registry_content_hash(
                entity_type=name,
                literal_id=str(converted[id_field]),
                ordered_field_names=tuple(raw),
                field_values=tuple(converted[_output_field(name, field)] for field in raw),
            )
            result.append(converted)
        return result

    artifacts = records("artifact", "filename", "artifact_sha256")
    payload: dict[str, object] = {
        "constants": {key: _artifact_constant(value) for key, value in protocol.constants},
        "arms": [
            {
                "arm_order": arm.arm_order,
                "arm_id": arm.arm_id,
                "belief_model_id": arm.belief_model_id,
                "policy_id": arm.policy_id,
            }
            for arm in ARMS
        ],
        "full_seeds": list(FULL_SEEDS),
        "smoke_seeds": list(SMOKE_SEEDS),
        "budget_registry": records("budget", "budget_id", "budget_sha256"),
        "ece_bin_edges": [f64(index / 10.0) for index in range(11)],
        "research_question_registry": _question_records(protocol),
        "scientific_hypothesis_registry": records(
            "scientific_hypothesis",
            "scientific_hypothesis_id",
            "scientific_hypothesis_sha256",
        ),
        "statistical_hypothesis_registry": records(
            "statistical_hypothesis",
            "statistical_hypothesis_id",
            "statistical_hypothesis_sha256",
        ),
        "metric_registry": records("metric", "metric_id", "metric_sha256"),
        "estimand_registry": records("estimand", "estimand_id", "estimand_sha256"),
        "mechanism_registry": records("mechanism", "mechanism_id", "mechanism_sha256"),
        "population_registry": records("population", "population_id", "population_sha256"),
        "count_symbol_registry": records("count_symbol", "symbol_id", "count_symbol_sha256"),
        "decision_symbol_registry": records(
            "decision_symbol", "symbol_id", "decision_symbol_sha256"
        ),
        "predicate_registry": records("predicate", "predicate_id", "predicate_sha256"),
        "confirmatory_contrast_registry": records("confirmatory", "contrast_id", "contrast_sha256"),
        "decision_contrast_registry": records("decision", "contrast_id", "contrast_sha256"),
        "descriptive_contrast_registry": records("descriptive", "contrast_id", "contrast_sha256"),
        "veto_registry": records("veto", "veto_id", "veto_sha256"),
        "formula_registry": records("formula", "formula_id", "formula_sha256"),
        "gate_condition_registry": records("gate_condition", "condition_id", "condition_sha256"),
        "gate_registry": records("gate", "gate_id", "gate_sha256"),
        "audit_registry": records("audit", "audit_id", "audit_sha256"),
        "controller_stage_registry": records(
            "controller_stage", "controller_stage_id", "controller_stage_sha256"
        ),
        "branch_registry": records("branch", "branch_id", "branch_sha256"),
        "artifact_registry": artifacts,
        "enum_registry": records("enum", "enum_id", "enum_sha256"),
        "schema_versions": {item["filename"]: item["schema_version"] for item in artifacts},
        "oracle_transform_version": "broader_selected_only_oracle/v1",
        "oracle_domain_count": 117_952,
        "oracle_domain_expected_sha256": protocol.constant("oracle_domain_expected_sha256"),
        "oracle_conformance_generator": _oracle_generator(protocol),
    }
    return payload


def build_world_definitions_payload() -> dict[str, object]:
    candidate_catalog = [
        {
            "candidate_id": item.candidate_id,
            "family": item.family,
            "comparison_group_id": item.comparison_group_id,
            "controlled_fingerprint": [
                [name, value if isinstance(value, int) else f64(float(value))]
                for name, value in item.controlled_variables
            ],
            "intervention_variable": item.intervention_variable,
            "intervention_arm": item.intervention_arm,
            "replication_id": item.replication_id,
            "role": item.role,
        }
        for item in CANDIDATE_CATALOG
    ]
    cost_catalogs = {
        catalog_id: {candidate_id: f64(cost) for candidate_id, cost in costs.items()}
        for catalog_id, costs in COST_CATALOGS.items()
    }
    midpoint_map = {key: f64(value) for key, value in MIDPOINTS.items()}
    worlds = [
        {
            "world_id": item.public.world_id,
            "block": item.public.block,
            "scientific_hypothesis_id": item.hidden.scientific_hypothesis_id,
            "effect_size": f64(item.hidden.effect_size),
            "group_sigmas": {key: f64(value) for key, value in item.hidden.group_sigmas},
            "cost_catalog_id": item.public.cost_catalog_id,
            "depth": item.public.depth,
            "candidate_ids": list(item.public.candidate_ids),
            "initial_feasible_candidate_ids": list(item.public.initial_feasible_candidate_ids),
            "setup_candidate_ids": list(item.public.setup_candidate_ids),
            "comparison_group_ids": list(item.public.comparison_group_ids),
            "budget_ids": list(item.public.budget_ids),
        }
        for item in WORLDS
    ]
    from research_decision_engine.benchmarks.broader_protocol import protocol_hash

    return {
        "candidate_catalog": candidate_catalog,
        "cost_catalogs": cost_catalogs,
        "midpoint_map": midpoint_map,
        "worlds": worlds,
        "world_registry_sha256": protocol_hash(
            "world_registry",
            {
                "candidate_catalog": candidate_catalog,
                "cost_catalogs": cost_catalogs,
                "midpoint_map": midpoint_map,
                "worlds": worlds,
            },
        ),
    }


def _validate_record_scalar_types(filename: str, record: Mapping[str, object], index: int) -> None:
    path = f"{filename}[{index}]"
    integer_fields = {
        "seed",
        "sample_count",
        "replicate_index",
        "sampled_position_count",
        "first_divergence_step",
        "usable_bootstrap_replicates",
        "permutation_count",
        "extreme_count",
        "holm_rank",
        "n_present",
        "n_absent",
    }
    boolean_fields = {
        "scientific_belief_updated",
        "first_action_divergent",
        "holm_member",
        "extreme",
    }
    f64_fields = {
        "budget",
        "sample_mean",
        "sample_standard_deviation",
        "sigma_floor",
        "estimated_sigma",
        "physical_cost",
        "deployment_cost",
        "revealed_observation",
        "nll_difference",
        "brier_difference",
        "decision_cost_difference",
        "present_weight",
        "absent_weight",
        "left_value",
        "right_value",
        "left_denominator",
        "right_denominator",
        "estimate",
        "ci_low",
        "ci_high",
        "test_statistic",
        "p_raw",
        "p_adjusted",
        "replicate_estimate",
        "replicate_statistic",
    }
    id_fields = {
        "run_id",
        "comparison_id",
        "arm_id",
        "world_id",
        "budget_id",
        "policy_id",
        "belief_model_id",
        "lineage_id",
        "store_id",
        "scientific_hypothesis_id",
        "terminal_reason",
        "sigma_estimate_id",
        "calibration_prefix_id",
        "comparison_group_id",
        "target_belief_model_id",
        "target_comparison_group_id",
        "oracle_key_id",
        "oracle_use_id",
        "candidate_id",
        "intervention_arm",
        "replication_id",
        "authorization_id",
        "decision_id",
        "record_type",
        "sequence_class",
        "primary_mechanism_id",
        "controller_stage_id",
        "contrast_id",
        "analysis_class",
        "research_question_id",
        "policy_scope",
        "population_scope",
        "metric_id",
        "estimand_id",
        "source_contrast_id",
        "statistical_hypothesis_id",
        "result_status",
        "estimability_status",
        "completion_status",
        "failure_code",
    }
    for field, value in record.items():
        if value is None:
            continue
        field_path = f"{path}.{field}"
        if field in integer_fields and (not isinstance(value, int) or isinstance(value, bool)):
            raise ArtifactValidationError(f"{field_path} must be I64.")
        if (
            field == "seed"
            and filename == "resampling_audit.jsonl"
            and (not isinstance(value, int) or isinstance(value, bool) or value not in range(2**64))
        ):
            raise ArtifactValidationError(f"{field_path} must be U64.")
        if field in boolean_fields and not isinstance(value, bool):
            raise ArtifactValidationError(f"{field_path} must be BOOL.")
        if field in f64_fields:
            _decode_f64(value, field_path)
        if field in id_fields:
            validate_id(value, field_path)
    for field in (
        "ordered_decisions_sha256",
        "reconciliation_sha256",
        "trajectory_sha256",
        "provenance_sha256",
    ):
        if field in record:
            validate_sha256(record[field], f"{path}.{field}")


def validate_id(value: object, path: str) -> None:
    if not isinstance(value, str) or ID_PATTERN.fullmatch(value) is None:
        raise ArtifactValidationError(f"{path} is not an ID.")


def validate_sha256(value: object, path: str) -> None:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise ArtifactValidationError(f"{path} is not a SHA256 value.")


def _envelope(
    schema_version: str, source_design_sha256: str, scientific_payload: bytes
) -> dict[str, str]:
    validate_sha256(source_design_sha256, "source_design_sha256")
    return {
        "schema_version": schema_version,
        "protocol_version": PROTOCOL_VERSION,
        "source_design_sha256": source_design_sha256,
        "source_checkpoint_identifier": PROTOCOL_CHECKPOINT,
        "scientific_payload_sha256": hashlib.sha256(scientific_payload).hexdigest(),
    }


def _csv_bytes(header: Sequence[str], rows: Iterable[Mapping[str, object]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=header, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        rendered = {
            key: (
                json.dumps(value, sort_keys=True, separators=(",", ":"))
                if isinstance(value, (dict, list, tuple))
                else ("true" if value else "false")
                if isinstance(value, bool)
                else ""
                if value is None
                else value
            )
            for key, value in row.items()
        }
        writer.writerow(rendered)
    return output.getvalue().encode("utf-8")


def _convert_registry_record(name: str, raw: Mapping[str, str]) -> dict[str, object]:
    return {_output_field(name, key): _convert_cell(name, key, value) for key, value in raw.items()}


def _artifact_constant(value: str) -> object:
    converted = scalar_constant(value)
    return f64(converted) if isinstance(converted, float) else converted


def _output_field(name: str, field: str) -> str:
    overrides = {
        ("population", "eligible rows"): "eligible_rows_rule",
        ("population", "weighting"): "weighting_rule",
        ("gate", "required sources"): "required_source_ids",
        ("gate", "decision use"): "decision_use",
        ("artifact", "primary key or singleton"): "primary_key",
        ("artifact", "row order"): "row_order",
        ("predicate", "exact predicate"): "exact_predicate",
    }
    return overrides.get((name, field), field)


def _convert_cell(name: str, field: str, value: str) -> object:
    if value == "null":
        return [] if field == "decision_use" else None
    if field in {
        "order",
        "hypothesis_order",
        "metric_order",
        "estimand_order",
        "mechanism_order",
        "gate_order",
        "formula_order",
        "condition_order",
        "audit_order",
        "branch_order",
        "stage_order",
        "symbol_order",
        "predicate_order",
        "budget_order",
        "enum_order",
    }:
        return int(value)
    if field in {"holm_member", "actionable"}:
        return value == "true"
    if field == "budget":
        return f64(float(value))
    list_fields = {
        "decision_use",
        "ordered_operand_ids",
        "required sources",
        "ordered_condition_ids",
        "allowed_event_types",
        "ordered_values",
    }
    if field in list_fields:
        return [] if value == "null" else value.split(";")
    if name == "contrast" and field in {"decision_use"}:
        return value.split(";")
    return value


def _question_records(protocol: ProtocolSnapshot) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for item in protocol.research_questions:
        row = dict(item)
        identifier = str(row["research_question_id"])
        names = tuple(row)
        row["question_sha256"] = registry_content_hash(
            entity_type="research_question",
            literal_id=identifier,
            ordered_field_names=names,
            field_values=tuple(row[name] for name in names),
        )
        records.append(row)
    return records


def _oracle_generator(protocol: ProtocolSnapshot) -> dict[str, object]:
    return {
        "generator_version": "broader-oracle-conformance/v1",
        "decision_key_fields": [
            "namespace",
            "protocol_version",
            "oracle_version",
            "world_id",
            "seed",
            "candidate_id",
            "replication_id",
        ],
        "calibration_key_fields": [
            "namespace",
            "protocol_version",
            "oracle_version",
            "world_id",
            "seed",
            "comparison_group_id",
            "intervention_arm",
            "replication_id",
        ],
        "decimal_context": {
            "prec": "80",
            "rounding": "ROUND_HALF_EVEN",
            "Emin": "-999999",
            "Emax": "999999",
            "capitals": "1",
            "clamp": "0",
            "traps_true": "InvalidOperation;DivisionByZero;Overflow;FloatOperation",
            "traps_false": "Underflow;Subnormal;Inexact;Rounded;Clamped",
        },
        "acklam_coefficients": {
            "a": [
                "-39.69683028665376",
                "220.9460984245205",
                "-275.9285104469687",
                "138.3577518672690",
                "-30.66479806614716",
                "2.506628277459239",
            ],
            "b": [
                "-54.47609879822406",
                "161.5858368580409",
                "-155.6989798598866",
                "66.80131188771972",
                "-13.28068155288572",
            ],
            "c": [
                "-0.007784894002430293",
                "-0.3223964580411365",
                "-2.400758277161838",
                "-2.549732539343734",
                "4.374664141464968",
                "2.938163982698783",
            ],
            "d": [
                "0.007784695709041462",
                "0.3224671290700398",
                "2.445134137142996",
                "3.754408661907416",
            ],
        },
        "enumeration_partitions": [
            "full_decision",
            "full_calibration",
            "smoke_decision",
            "smoke_calibration",
        ],
        "canonical_line_fields": [
            "namespace",
            "serialized_key_hex",
            "digest_hex",
            "u_string",
            "z_string",
        ],
        "domain_count": 117_952,
        "expected_sha256": protocol.constant("oracle_domain_expected_sha256"),
    }
