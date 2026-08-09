"""Versioned SQLite storage for experiments and scientific reasoning history."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import suppress
from hashlib import sha256
from pathlib import Path
from types import TracebackType
from typing import cast

from research_decision_engine.decision import (
    CandidateScore,
    DecisionTrace,
    HypothesisDecisionContext,
)
from research_decision_engine.lookahead import LookaheadPlanTrace
from research_decision_engine.reasoning import (
    BeliefState,
    BeliefUpdate,
    DuplicateEvidenceError,
    Evidence,
    Hypothesis,
    HypothesisLikelihood,
    Provenance,
    ProvenanceValue,
    ReasoningError,
    prediction_model_from_record,
)
from research_decision_engine.run_spec import (
    CandidateSpec,
    CompletedWorkloadExperiment,
    NormalizedObservation,
    _canonical_json_text,
)
from research_decision_engine.types import Candidate, CompletedExperiment, ExperimentRecord

SCHEMA_VERSION = 6

_EXPERIMENTS_DDL = """
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT NOT NULL UNIQUE,
    policy TEXT NOT NULL,
    observed_value REAL NOT NULL,
    true_value REAL NOT NULL,
    cost REAL NOT NULL,
    created_at TEXT NOT NULL,
    params_json TEXT NOT NULL
)
""".strip()

_MIGRATION_SCHEMA_OBJECTS: tuple[tuple[int, str, str], ...] = (
    (1, "table", "experiments"),
    (2, "table", "hypotheses"),
    (2, "table", "evidence"),
    (2, "table", "evidence_sources"),
    (2, "table", "belief_states"),
    (2, "table", "belief_state_probabilities"),
    (2, "table", "belief_state_evidence"),
    (2, "table", "belief_updates"),
    (2, "table", "belief_update_likelihoods"),
    (3, "table", "decision_traces"),
    (3, "table", "decision_hypotheses"),
    (3, "table", "decision_ranked_candidates"),
    (4, "table", "lookahead_plan_traces"),
    (5, "table", "belief_models"),
    (5, "table", "belief_model_lineages"),
    (5, "table", "model_belief_states"),
    (5, "table", "sigma_estimates"),
    (5, "table", "calibration_prefixes"),
    (5, "table", "calibration_groups"),
    (5, "table", "calibration_replications"),
    (5, "table", "calibration_experiment_arms"),
    (5, "table", "calibration_matched_effects"),
    (5, "table", "sigma_estimate_sources"),
    (5, "table", "model_belief_updates"),
    (5, "table", "model_belief_update_likelihoods"),
    (5, "table", "model_adequacy_diagnostics"),
    (5, "table", "calibration_cost_entries"),
    (5, "table", "decision_cost_entries"),
    (5, "trigger", "calibration_cost_ledger_disjoint"),
    (5, "trigger", "decision_cost_ledger_disjoint"),
    (6, "table", "workload_experiments"),
)

# SHA-256 over whitespace-normalized sqlite_schema.sql from the frozen opening
# commit. These fingerprints make version declarations fail closed without
# changing any migration DDL.
_MIGRATION_SCHEMA_SQL_SHA256 = {
    "belief_model_lineages": "5a170d2db975ea9a828df2c2903723126f5d4ae33eb4de383b5bd0eec47eed8e",
    "belief_models": "6aadcd1a8171dd041e9b173bbabde53378c68c0094cf14757dd17a78288916dc",
    "belief_state_evidence": "f9fa1cd688eff89c5e223f62e00cb65478a6186a02522f1de555d5a73fc9c05b",
    "belief_state_probabilities": (
        "fe39492b18b3c88669e5aabe362522fcd2669caa109958de1a2ff8f9b9718be2"
    ),
    "belief_states": "014feafd332e12abcf1f6aac50d8e39a58d2fae7b2a1a6b87d2e95e34682ab1f",
    "belief_update_likelihoods": "136f9ed50271818f031534c6a984147c979527ca3cf81a508e0ac61951a4a5ce",
    "belief_updates": "3f0ab0c08a44c0bac7bf1530da52fb3eeb05ae1588d68e7f2227f4d0e935cd37",
    "calibration_cost_entries": "44cf9868413374667d89b3e890d6a431455d644864571f9d3744141819e97365",
    "calibration_cost_ledger_disjoint": (
        "fa18391a5c05e5247f2727a4bb8665d747a59f3c4091e1047fcc9f30b8e198ba"
    ),
    "calibration_experiment_arms": (
        "bb719bc999ecf2d7c35d538c58d59fd242bb4a76ed081de7adcbd5ff69d9e6cc"
    ),
    "calibration_groups": "5669728419cb10c06bf9da335696d0c1118a6b82b361a01a434995cf5badf74c",
    "calibration_matched_effects": (
        "13f3c65f54c76a75bcb416adb4dfb1e3faf623b8f80a9893e312dd2da2e2c967"
    ),
    "calibration_prefixes": "eefcf90c9139f5fe0efb5b7074948853b5c0c5a534310575f6865f5290fd48c5",
    "calibration_replications": "58769fce9141eb5b5d9a96ab942a618d0b7e17f0fc1bce5741a4494fd72103ab",
    "decision_cost_entries": "34c4b2cbd6e6b5475875edcec7b2e5a3f39e91c0526cfcd0e9625cc909c6569c",
    "decision_cost_ledger_disjoint": (
        "a177c81f490593add88759d640ac92b8dbce6cab8a3d3a94bbb947569c70093b"
    ),
    "decision_hypotheses": "21921a29c6bafb397a7df931314d4c6858cd6ff55d6544efd31d242e3861da0e",
    "decision_ranked_candidates": (
        "b1e37e75a1a1bdf0702d714fd791d4054f8d6b84fdc9c73e4ea8c56c4f3b9de0"
    ),
    "decision_traces": "a78e435e7f5f85c809457bf5cfe56bd1d6549133f03838e2d5a0a2d78ad5d60b",
    "evidence": "7717d6bba612b81cc67fe5756ce08cc77026f6f7f86a84d97441f39ec2c87e7b",
    "evidence_sources": "d164cea01cab04295bc9da50abe05f2ff03b5a8b63bfb59aac4392dd2a443735",
    "experiments": "c0c5e579fa8ff3092444d0ff880f2fda3fb01f6e6ba24436776c77236547fc9c",
    "hypotheses": "8d9de8caa2f6240b4d2aad4078b000bfc439a7a01ee9d128de44d5357334352f",
    "lookahead_plan_traces": "e8c37893b270a17200c2192d6b98f3ce0f3b5f09d31f440e25c920cd464e211d",
    "model_adequacy_diagnostics": (
        "cf4155e1517576eb5f1d08d9ba60e89e1e1ea9b0c813dfca3835ad510a34f41f"
    ),
    "model_belief_states": "5dd8446d93b36cb19dafcfc10d9e5af3c5eac71c64c6f52d1d84fd84b39c7c7e",
    "model_belief_update_likelihoods": (
        "3e3cb98e3c3e126ed5b8924cb9a33db934d228a062e8ae0eed59d34facaea097"
    ),
    "model_belief_updates": "2c5c538187f1e977b9f6b1df564ac9b5bdc08477982d8c90bb0999e58ef92a40",
    "sigma_estimate_sources": "5326e462d0debca2facb8e52a365f94a9cfe45abefa97ab9704719880fcb0bd1",
    "sigma_estimates": "1d0f8ae6d1bbfa89e292a25f966be00585c63819b7070170b42a99242847b693",
    "workload_experiments": "5a3c226e2407d567af2d445681d626f612c0adff50c24fd0b9ae16c1e3843066",
}

_WORKLOAD_EXPERIMENTS_DDL = """
CREATE TABLE workload_experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_spec_fingerprint TEXT NOT NULL CHECK (
        length(run_spec_fingerprint) = 64
        AND run_spec_fingerprint NOT GLOB '*[^0-9a-f]*'
    ),
    candidate_id TEXT NOT NULL CHECK (length(candidate_id) > 0),
    policy_id TEXT NOT NULL CHECK (length(policy_id) > 0),
    objective_value REAL NOT NULL CHECK (
        typeof(objective_value) IN ('integer', 'real')
        AND objective_value BETWEEN
            -1.7976931348623157e308 AND 1.7976931348623157e308
    ),
    cost REAL NOT NULL CHECK (
        typeof(cost) IN ('integer', 'real')
        AND cost BETWEEN 0.0 AND 1.7976931348623157e308
    ),
    created_at TEXT NOT NULL CHECK (length(created_at) > 0),
    parameters_json TEXT NOT NULL CHECK (length(parameters_json) > 0),
    UNIQUE (run_spec_fingerprint, candidate_id)
)
""".strip()


class ExperimentStore:
    """Small SQLite repository for experiment and reasoning records."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.connection: sqlite3.Connection | None = None

    def __enter__(self) -> ExperimentStore:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def init_schema(self) -> None:
        """Apply each additive migration in its own resumable transaction."""

        connection = self._connection()
        if connection.in_transaction:
            raise RuntimeError(
                "Cannot initialize the schema while a caller-owned transaction is active."
            )

        current_version = _schema_version_from(connection)
        _validate_supported_schema_version(current_version)
        while current_version < SCHEMA_VERSION:
            migrated = self._migrate_one_step(connection, current_version, current_version + 1)
            if migrated:
                current_version += 1
            else:
                current_version = _schema_version_from(connection)
                _validate_supported_schema_version(current_version)

        _validate_schema_for_version(connection, current_version)

    def schema_version(self) -> int:
        return _schema_version_from(self._connection())

    def _migrate_one_step(
        self,
        connection: sqlite3.Connection,
        source_version: int,
        target_version: int,
    ) -> bool:
        """Commit one migration edge, or report that another runner won the lock."""

        if connection.in_transaction:
            raise RuntimeError("Cannot migrate while a caller-owned transaction is active.")
        opening_version = _schema_version_from(connection)
        _validate_supported_schema_version(opening_version)
        if opening_version != source_version:
            raise RuntimeError(
                "Migration source version changed before transaction acquisition: "
                f"expected {source_version}, found {opening_version}."
            )
        if target_version != source_version + 1 or not 1 <= target_version <= SCHEMA_VERSION:
            raise RuntimeError(
                f"Unsupported SQLite migration edge {source_version} -> {target_version}."
            )

        migrations: dict[int, Callable[[sqlite3.Connection], None]] = {
            1: self._migrate_to_v1,
            2: self._migrate_to_v2,
            3: self._migrate_to_v3,
            4: self._migrate_to_v4,
            5: self._migrate_to_v5,
            6: self._migrate_to_v6,
        }
        migration = migrations[target_version]

        try:
            connection.execute("BEGIN IMMEDIATE")
            locked_version = _schema_version_from(connection)
            if locked_version != source_version:
                connection.rollback()
                return False

            _validate_schema_for_version(connection, source_version)
            migration(connection)
            if not connection.in_transaction:
                raise RuntimeError(
                    f"Migration {source_version} -> {target_version} relinquished "
                    "transaction ownership."
                )
            _validate_schema_for_version(connection, target_version)
            _execute_migration_statement(connection, f"PRAGMA user_version = {target_version}")
            if _schema_version_from(connection) != target_version:
                raise RuntimeError(f"SQLite did not advance to schema version {target_version}.")
            _validate_schema_for_version(connection, target_version)
            connection.commit()
        except BaseException:
            with suppress(Exception):
                connection.rollback()
            raise
        return True

    def add_record(self, record: ExperimentRecord) -> ExperimentRecord:
        connection = self._connection()
        cursor = connection.execute(
            """
            INSERT INTO experiments (
                candidate_id, policy, observed_value, true_value, cost, created_at, params_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.candidate.candidate_id,
                record.policy,
                record.observed_value,
                record.true_value,
                record.cost,
                record.created_at,
                json.dumps(record.candidate.params(), sort_keys=True),
            ),
        )
        connection.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return an inserted experiment id.")
        return ExperimentRecord(
            record_id=int(cursor.lastrowid),
            candidate=record.candidate,
            policy=record.policy,
            observed_value=record.observed_value,
            true_value=record.true_value,
            cost=record.cost,
            created_at=record.created_at,
        )

    def list_records(self) -> list[ExperimentRecord]:
        rows = self._connection().execute("SELECT * FROM experiments ORDER BY id").fetchall()
        return [self._record_from_row(row) for row in rows]

    def get_record(self, record_id: int) -> ExperimentRecord:
        row = (
            self._connection()
            .execute("SELECT * FROM experiments WHERE id = ?", (record_id,))
            .fetchone()
        )
        if row is None:
            raise KeyError(f"Unknown experiment record: {record_id}")
        return self._record_from_row(row)

    def list_completed_experiments(self) -> list[CompletedExperiment]:
        """Return successful observations without benchmark-only true values."""

        rows = (
            self._connection()
            .execute(
                """
            SELECT id, candidate_id, observed_value, created_at, params_json
            FROM experiments
            ORDER BY id
            """
            )
            .fetchall()
        )
        return [
            CompletedExperiment(
                record_id=int(row["id"]),
                candidate=self._candidate_from_row(row),
                observed_value=float(row["observed_value"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def completed_candidate_ids(self) -> set[str]:
        rows = self._connection().execute("SELECT candidate_id FROM experiments").fetchall()
        return {str(row["candidate_id"]) for row in rows}

    def add_workload_experiment(
        self, record: CompletedWorkloadExperiment
    ) -> CompletedWorkloadExperiment:
        """Persist one truth-free generic workload completion."""

        if type(record) is not CompletedWorkloadExperiment:
            raise TypeError("record must be an exact CompletedWorkloadExperiment.")
        self._connection().execute(
            """
            INSERT INTO workload_experiments (
                run_spec_fingerprint,
                candidate_id,
                policy_id,
                objective_value,
                cost,
                created_at,
                parameters_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.run_spec_fingerprint,
                record.candidate.candidate_id,
                record.policy_id,
                record.observation.objective_value,
                record.observation.cost,
                record.created_at,
                _canonical_json_text(dict(record.candidate.parameters)),
            ),
        )
        self._connection().commit()
        return record

    def list_workload_experiments(
        self, run_spec_fingerprint: str
    ) -> list[CompletedWorkloadExperiment]:
        """Reopen truth-free completions for one externally supplied RunSpec identity."""

        _validate_run_spec_fingerprint(run_spec_fingerprint)
        rows = (
            self._connection()
            .execute(
                """
                SELECT
                    run_spec_fingerprint,
                    candidate_id,
                    policy_id,
                    objective_value,
                    cost,
                    created_at,
                    parameters_json
                FROM workload_experiments
                WHERE run_spec_fingerprint = ?
                ORDER BY id
                """,
                (run_spec_fingerprint,),
            )
            .fetchall()
        )
        return [self._workload_experiment_from_row(row) for row in rows]

    def iter_rows(self) -> Iterator[sqlite3.Row]:
        rows = self._connection().execute("SELECT * FROM experiments ORDER BY id").fetchall()
        yield from rows

    def register_hypotheses(self, hypotheses: tuple[Hypothesis, ...]) -> None:
        connection = self._connection()
        with connection:
            for hypothesis in hypotheses:
                existing_row = connection.execute(
                    "SELECT * FROM hypotheses WHERE id = ?", (hypothesis.hypothesis_id,)
                ).fetchone()
                if existing_row is not None:
                    if self._hypothesis_from_row(existing_row) != hypothesis:
                        raise ReasoningError(
                            f"Stored hypothesis {hypothesis.hypothesis_id} has different content."
                        )
                    continue
                connection.execute(
                    """
                    INSERT INTO hypotheses (
                        id,
                        statement,
                        prior_probability,
                        prediction_model_type,
                        prediction_model_version,
                        prediction_parameters_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        hypothesis.hypothesis_id,
                        hypothesis.statement,
                        hypothesis.prior_probability,
                        hypothesis.prediction_model.model_type,
                        hypothesis.prediction_model.version,
                        json.dumps(hypothesis.prediction_model.parameters(), sort_keys=True),
                    ),
                )

    def list_hypotheses(self) -> list[Hypothesis]:
        rows = self._connection().execute("SELECT * FROM hypotheses ORDER BY id").fetchall()
        return [self._hypothesis_from_row(row) for row in rows]

    def add_initial_belief_state(self, state: BeliefState) -> None:
        if state.sequence != 0:
            raise ReasoningError("Initial belief state must have sequence zero.")
        connection = self._connection()
        existing = self.current_belief_state()
        if existing is not None:
            if existing != state:
                raise ReasoningError("A different belief state is already initialized.")
            return
        with connection:
            self._insert_belief_state(connection, state)

    def current_belief_state(self) -> BeliefState | None:
        row = (
            self._connection()
            .execute("SELECT id FROM belief_states ORDER BY sequence_number DESC LIMIT 1")
            .fetchone()
        )
        if row is None:
            return None
        return self.get_belief_state(str(row["id"]))

    def get_belief_state(self, belief_state_id: str) -> BeliefState:
        connection = self._connection()
        row = connection.execute(
            "SELECT * FROM belief_states WHERE id = ?", (belief_state_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown belief state: {belief_state_id}")
        probability_rows = connection.execute(
            """
            SELECT hypothesis_id, prior_probability, posterior_probability
            FROM belief_state_probabilities
            WHERE belief_state_id = ?
            ORDER BY hypothesis_id
            """,
            (belief_state_id,),
        ).fetchall()
        evidence_rows = connection.execute(
            """
            SELECT evidence_id
            FROM belief_state_evidence
            WHERE belief_state_id = ?
            ORDER BY evidence_order
            """,
            (belief_state_id,),
        ).fetchall()
        return BeliefState(
            belief_state_id=str(row["id"]),
            hypothesis_ids=tuple(str(item["hypothesis_id"]) for item in probability_rows),
            prior_probabilities=tuple(
                float(item["prior_probability"]) for item in probability_rows
            ),
            posterior_probabilities=tuple(
                float(item["posterior_probability"]) for item in probability_rows
            ),
            evidence_ids=tuple(str(item["evidence_id"]) for item in evidence_rows),
            sequence=int(row["sequence_number"]),
            created_at=str(row["created_at"]),
            parent_belief_state_id=(
                None
                if row["parent_belief_state_id"] is None
                else str(row["parent_belief_state_id"])
            ),
        )

    def evidence_exists(self, evidence_id: str) -> bool:
        row = (
            self._connection()
            .execute("SELECT 1 FROM evidence WHERE id = ?", (evidence_id,))
            .fetchone()
        )
        return row is not None

    def list_evidence(self) -> list[Evidence]:
        rows = self._connection().execute("SELECT id FROM evidence ORDER BY id").fetchall()
        return [self.get_evidence(str(row["id"])) for row in rows]

    def get_evidence(self, evidence_id: str) -> Evidence:
        connection = self._connection()
        row = connection.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown evidence: {evidence_id}")
        source_rows = connection.execute(
            """
            SELECT experiment_id
            FROM evidence_sources
            WHERE evidence_id = ?
            ORDER BY source_order
            """,
            (evidence_id,),
        ).fetchall()
        return Evidence(
            evidence_id=str(row["id"]),
            source_experiment_ids=tuple(int(item["experiment_id"]) for item in source_rows),
            observed_comparison=float(row["observed_comparison"]),
            observed_outcome=str(row["observed_outcome"]),
            provenance=self._provenance_from_row(row),
            created_at=str(row["created_at"]),
        )

    def add_reasoning_step(self, update: BeliefUpdate) -> None:
        connection = self._connection()
        current = self.current_belief_state()
        if current is None or current.belief_state_id != update.belief_state_before.belief_state_id:
            raise ReasoningError("Belief update must extend the current stored belief state.")
        if self.evidence_exists(update.evidence.evidence_id):
            raise DuplicateEvidenceError(
                f"Evidence {update.evidence.evidence_id} has already been persisted."
            )

        with connection:
            self._insert_evidence(connection, update.evidence)
            self._insert_belief_state(connection, update.posterior_belief_state)
            connection.execute(
                """
                INSERT INTO belief_updates (
                    id,
                    belief_state_before_id,
                    evidence_id,
                    posterior_belief_state_id,
                    update_rule_version,
                    normalization_constant,
                    provenance_method,
                    provenance_version,
                    provenance_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    update.update_id,
                    update.belief_state_before.belief_state_id,
                    update.evidence.evidence_id,
                    update.posterior_belief_state.belief_state_id,
                    update.update_rule_version,
                    update.normalization_constant,
                    update.provenance.method,
                    update.provenance.version,
                    self._provenance_json(update.provenance),
                    update.created_at,
                ),
            )
            connection.executemany(
                """
                INSERT INTO belief_update_likelihoods (
                    belief_update_id,
                    hypothesis_id,
                    prior_for_update,
                    likelihood,
                    unnormalized_weight,
                    posterior_probability
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        update.update_id,
                        item.hypothesis_id,
                        item.prior_for_update,
                        item.likelihood,
                        item.unnormalized_weight,
                        item.posterior_probability,
                    )
                    for item in update.likelihoods
                ],
            )

    def list_belief_updates(self) -> list[BeliefUpdate]:
        rows = self._connection().execute("SELECT id FROM belief_updates ORDER BY rowid").fetchall()
        return [self.get_belief_update(str(row["id"])) for row in rows]

    def get_belief_update(self, update_id: str) -> BeliefUpdate:
        connection = self._connection()
        row = connection.execute(
            "SELECT * FROM belief_updates WHERE id = ?", (update_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown belief update: {update_id}")
        likelihood_rows = connection.execute(
            """
            SELECT *
            FROM belief_update_likelihoods
            WHERE belief_update_id = ?
            ORDER BY hypothesis_id
            """,
            (update_id,),
        ).fetchall()
        return BeliefUpdate(
            update_id=str(row["id"]),
            belief_state_before=self.get_belief_state(str(row["belief_state_before_id"])),
            evidence=self.get_evidence(str(row["evidence_id"])),
            likelihoods=tuple(
                HypothesisLikelihood(
                    hypothesis_id=str(item["hypothesis_id"]),
                    prior_for_update=float(item["prior_for_update"]),
                    likelihood=float(item["likelihood"]),
                    unnormalized_weight=float(item["unnormalized_weight"]),
                    posterior_probability=float(item["posterior_probability"]),
                )
                for item in likelihood_rows
            ),
            posterior_belief_state=self.get_belief_state(str(row["posterior_belief_state_id"])),
            update_rule_version=str(row["update_rule_version"]),
            normalization_constant=float(row["normalization_constant"]),
            provenance=self._provenance_from_row(row),
            created_at=str(row["created_at"]),
        )

    def update_id_for_evidence(self, evidence_id: str) -> str | None:
        row = (
            self._connection()
            .execute("SELECT id FROM belief_updates WHERE evidence_id = ?", (evidence_id,))
            .fetchone()
        )
        return None if row is None else str(row["id"])

    def supporting_evidence_counts(self) -> dict[str, int]:
        counts = {hypothesis.hypothesis_id: 0 for hypothesis in self.list_hypotheses()}
        rows = (
            self._connection()
            .execute(
                """
            SELECT belief_update_id, hypothesis_id, likelihood
            FROM belief_update_likelihoods
            ORDER BY belief_update_id, hypothesis_id
            """
            )
            .fetchall()
        )
        by_update: dict[str, list[tuple[str, float]]] = {}
        for row in rows:
            by_update.setdefault(str(row["belief_update_id"]), []).append(
                (str(row["hypothesis_id"]), float(row["likelihood"]))
            )
        for likelihoods in by_update.values():
            maximum = max(value for _, value in likelihoods)
            for hypothesis_id, value in likelihoods:
                if math.isclose(value, maximum, rel_tol=1e-12, abs_tol=1e-15):
                    counts[hypothesis_id] += 1
        return counts

    def add_decision_trace(self, trace: DecisionTrace) -> DecisionTrace:
        """Persist one suggestion and its complete ranking atomically."""

        connection = self._connection()
        existing = connection.execute(
            "SELECT id FROM decision_traces WHERE id = ?", (trace.suggestion_id,)
        ).fetchone()
        if existing is not None:
            return self.get_decision_trace(trace.suggestion_id)

        with connection:
            connection.execute(
                """
                INSERT INTO decision_traces (
                    id,
                    policy,
                    policy_version,
                    created_at,
                    candidate_id,
                    candidate_params_json,
                    belief_state_id,
                    expected_information_gain,
                    prior_entropy,
                    expected_posterior_entropy,
                    estimated_cost,
                    max_cost,
                    fallback_reason,
                    rationale,
                    provenance_method,
                    provenance_version,
                    provenance_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace.suggestion_id,
                    trace.policy,
                    trace.policy_version,
                    trace.created_at,
                    trace.candidate.candidate_id,
                    json.dumps(trace.candidate.params(), sort_keys=True),
                    trace.belief_state_id,
                    trace.selected.expected_information_gain,
                    trace.selected.prior_entropy,
                    trace.selected.expected_posterior_entropy,
                    trace.selected.estimated_cost,
                    trace.max_cost,
                    trace.fallback_reason,
                    trace.rationale,
                    trace.provenance.method,
                    trace.provenance.version,
                    self._provenance_json(trace.provenance),
                ),
            )
            connection.executemany(
                """
                INSERT INTO decision_hypotheses (
                    suggestion_id,
                    hypothesis_id,
                    statement,
                    posterior_probability,
                    most_favorable_outcome,
                    most_favorable_outcome_label,
                    posterior_if_observed
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        trace.suggestion_id,
                        item.hypothesis_id,
                        item.statement,
                        item.posterior_probability,
                        item.most_favorable_outcome,
                        item.most_favorable_outcome_label,
                        item.posterior_if_observed,
                    )
                    for item in trace.hypotheses
                ],
            )
            connection.executemany(
                """
                INSERT INTO decision_ranked_candidates (
                    suggestion_id,
                    rank,
                    candidate_id,
                    candidate_params_json,
                    expected_information_gain,
                    prior_entropy,
                    expected_posterior_entropy,
                    estimated_cost,
                    completes_matched_pair,
                    matched_experiment_id,
                    score_reason,
                    ranking_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        trace.suggestion_id,
                        rank,
                        item.candidate.candidate_id,
                        json.dumps(item.candidate.params(), sort_keys=True),
                        item.expected_information_gain,
                        item.prior_entropy,
                        item.expected_posterior_entropy,
                        item.estimated_cost,
                        int(item.completes_matched_pair),
                        item.matched_experiment_id,
                        item.score_reason,
                        item.ranking_reason,
                    )
                    for rank, item in enumerate(trace.ranked_candidates)
                ],
            )
        return trace

    def latest_decision_trace(self) -> DecisionTrace | None:
        row = (
            self._connection()
            .execute("SELECT id FROM decision_traces ORDER BY rowid DESC LIMIT 1")
            .fetchone()
        )
        if row is None:
            return None
        return self.get_decision_trace(str(row["id"]))

    def list_decision_traces(self) -> list[DecisionTrace]:
        rows = (
            self._connection().execute("SELECT id FROM decision_traces ORDER BY rowid").fetchall()
        )
        return [self.get_decision_trace(str(row["id"])) for row in rows]

    def get_decision_trace(self, suggestion_id: str) -> DecisionTrace:
        connection = self._connection()
        row = connection.execute(
            "SELECT * FROM decision_traces WHERE id = ?", (suggestion_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown suggestion: {suggestion_id}")
        hypothesis_rows = connection.execute(
            """
            SELECT *
            FROM decision_hypotheses
            WHERE suggestion_id = ?
            ORDER BY hypothesis_id
            """,
            (suggestion_id,),
        ).fetchall()
        candidate_rows = connection.execute(
            """
            SELECT *
            FROM decision_ranked_candidates
            WHERE suggestion_id = ?
            ORDER BY rank
            """,
            (suggestion_id,),
        ).fetchall()
        ranked_candidates = tuple(self._candidate_score_from_row(item) for item in candidate_rows)
        if not ranked_candidates:
            raise ReasoningError(f"Suggestion {suggestion_id} has no ranked candidates.")
        selected_candidate_id = str(row["candidate_id"])
        if ranked_candidates[0].candidate.candidate_id != selected_candidate_id:
            raise ReasoningError(
                f"Suggestion {suggestion_id} has an inconsistent selected candidate."
            )
        return DecisionTrace(
            suggestion_id=str(row["id"]),
            policy=str(row["policy"]),
            policy_version=str(row["policy_version"]),
            created_at=str(row["created_at"]),
            belief_state_id=str(row["belief_state_id"]),
            selected=ranked_candidates[0],
            hypotheses=tuple(
                HypothesisDecisionContext(
                    hypothesis_id=str(item["hypothesis_id"]),
                    statement=str(item["statement"]),
                    posterior_probability=float(item["posterior_probability"]),
                    most_favorable_outcome=float(item["most_favorable_outcome"]),
                    most_favorable_outcome_label=str(item["most_favorable_outcome_label"]),
                    posterior_if_observed=float(item["posterior_if_observed"]),
                )
                for item in hypothesis_rows
            ),
            max_cost=float(row["max_cost"]),
            fallback_reason=(
                None if row["fallback_reason"] is None else str(row["fallback_reason"])
            ),
            rationale=str(row["rationale"]),
            ranked_candidates=ranked_candidates,
            provenance=self._provenance_from_row(row),
        )

    def add_lookahead_plan_trace(self, trace: LookaheadPlanTrace) -> LookaheadPlanTrace:
        """Persist one real decision trace without materializing simulated branches."""

        connection = self._connection()
        existing = connection.execute(
            "SELECT id FROM lookahead_plan_traces WHERE id = ?", (trace.plan_id,)
        ).fetchone()
        if existing is not None:
            return self.get_lookahead_plan_trace(trace.plan_id)
        with connection:
            connection.execute(
                """
                INSERT INTO lookahead_plan_traces (
                    id,
                    policy,
                    policy_version,
                    created_at,
                    belief_state_id,
                    candidate_id,
                    expected_total_information_gain,
                    expected_total_cost,
                    information_gain_per_expected_cost,
                    max_cost,
                    trace_json,
                    provenance_method,
                    provenance_version,
                    provenance_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace.plan_id,
                    trace.policy,
                    trace.policy_version,
                    trace.created_at,
                    trace.belief_state_id,
                    trace.candidate.candidate_id,
                    trace.selected.expected_total_information_gain,
                    trace.selected.expected_total_cost,
                    trace.selected.information_gain_per_expected_cost,
                    trace.max_cost,
                    json.dumps(trace.to_dict(), sort_keys=True, separators=(",", ":")),
                    trace.provenance.method,
                    trace.provenance.version,
                    self._provenance_json(trace.provenance),
                ),
            )
        return trace

    def latest_lookahead_plan_trace(self) -> LookaheadPlanTrace | None:
        row = (
            self._connection()
            .execute("SELECT id FROM lookahead_plan_traces ORDER BY rowid DESC LIMIT 1")
            .fetchone()
        )
        if row is None:
            return None
        return self.get_lookahead_plan_trace(str(row["id"]))

    def list_lookahead_plan_traces(self) -> list[LookaheadPlanTrace]:
        rows = (
            self._connection()
            .execute("SELECT id FROM lookahead_plan_traces ORDER BY rowid")
            .fetchall()
        )
        return [self.get_lookahead_plan_trace(str(row["id"])) for row in rows]

    def get_lookahead_plan_trace(self, plan_id: str) -> LookaheadPlanTrace:
        row = (
            self._connection()
            .execute("SELECT * FROM lookahead_plan_traces WHERE id = ?", (plan_id,))
            .fetchone()
        )
        if row is None:
            raise KeyError(f"Unknown lookahead plan: {plan_id}")
        raw = cast(object, json.loads(str(row["trace_json"])))
        if not isinstance(raw, dict):
            raise ReasoningError("Persisted lookahead plan trace must be a JSON object.")
        trace = LookaheadPlanTrace.from_dict(cast(dict[str, object], raw))
        if (
            trace.plan_id != str(row["id"])
            or trace.belief_state_id != str(row["belief_state_id"])
            or trace.candidate.candidate_id != str(row["candidate_id"])
        ):
            raise ReasoningError(f"Persisted lookahead plan {plan_id} is inconsistent.")
        return trace

    def _connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("ExperimentStore must be used as a context manager.")
        return self.connection

    def _record_from_row(self, row: sqlite3.Row) -> ExperimentRecord:
        return ExperimentRecord(
            record_id=int(row["id"]),
            candidate=self._candidate_from_row(row),
            policy=str(row["policy"]),
            observed_value=float(row["observed_value"]),
            true_value=float(row["true_value"]),
            cost=float(row["cost"]),
            created_at=str(row["created_at"]),
        )

    def _candidate_from_row(self, row: sqlite3.Row) -> Candidate:
        params = json.loads(str(row["params_json"]))
        return Candidate(
            candidate_id=str(row["candidate_id"]),
            learning_rate=float(params["learning_rate"]),
            regularization=float(params["regularization"]),
            model_width=int(params["model_width"]),
            optimizer=str(params["optimizer"]),
        )

    def _workload_experiment_from_row(self, row: sqlite3.Row) -> CompletedWorkloadExperiment:
        raw_parameters = cast(object, json.loads(str(row["parameters_json"])))
        if type(raw_parameters) is not dict:
            raise RuntimeError("Persisted workload parameters must be a JSON object.")
        return CompletedWorkloadExperiment(
            run_spec_fingerprint=str(row["run_spec_fingerprint"]),
            candidate=CandidateSpec(
                candidate_id=str(row["candidate_id"]),
                parameters=cast(dict[str, object], raw_parameters),
            ),
            policy_id=str(row["policy_id"]),
            observation=NormalizedObservation(
                objective_value=float(row["objective_value"]),
                cost=float(row["cost"]),
            ),
            created_at=str(row["created_at"]),
        )

    def _hypothesis_from_row(self, row: sqlite3.Row) -> Hypothesis:
        return Hypothesis(
            hypothesis_id=str(row["id"]),
            statement=str(row["statement"]),
            prior_probability=float(row["prior_probability"]),
            prediction_model=prediction_model_from_record(
                model_type=str(row["prediction_model_type"]),
                version=str(row["prediction_model_version"]),
                parameters=self._float_mapping(str(row["prediction_parameters_json"])),
            ),
        )

    def _candidate_score_from_row(self, row: sqlite3.Row) -> CandidateScore:
        matched_experiment_id = row["matched_experiment_id"]
        return CandidateScore(
            candidate=self._candidate_from_json(
                str(row["candidate_id"]), str(row["candidate_params_json"])
            ),
            expected_information_gain=float(row["expected_information_gain"]),
            prior_entropy=float(row["prior_entropy"]),
            expected_posterior_entropy=float(row["expected_posterior_entropy"]),
            estimated_cost=float(row["estimated_cost"]),
            completes_matched_pair=bool(row["completes_matched_pair"]),
            matched_experiment_id=(
                None if matched_experiment_id is None else int(matched_experiment_id)
            ),
            score_reason=str(row["score_reason"]),
            ranking_reason=str(row["ranking_reason"]),
        )

    def _candidate_from_json(self, candidate_id: str, encoded: str) -> Candidate:
        params = json.loads(encoded)
        return Candidate(
            candidate_id=candidate_id,
            learning_rate=float(params["learning_rate"]),
            regularization=float(params["regularization"]),
            model_width=int(params["model_width"]),
            optimizer=str(params["optimizer"]),
        )

    def _insert_evidence(self, connection: sqlite3.Connection, evidence: Evidence) -> None:
        connection.execute(
            """
            INSERT INTO evidence (
                id,
                observed_comparison,
                observed_outcome,
                provenance_method,
                provenance_version,
                provenance_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence.evidence_id,
                evidence.observed_comparison,
                evidence.observed_outcome,
                evidence.provenance.method,
                evidence.provenance.version,
                self._provenance_json(evidence.provenance),
                evidence.created_at,
            ),
        )
        connection.executemany(
            """
            INSERT INTO evidence_sources (evidence_id, experiment_id, source_order)
            VALUES (?, ?, ?)
            """,
            [
                (evidence.evidence_id, source_id, source_order)
                for source_order, source_id in enumerate(evidence.source_experiment_ids)
            ],
        )

    def _insert_belief_state(self, connection: sqlite3.Connection, state: BeliefState) -> None:
        connection.execute(
            """
            INSERT INTO belief_states (
                id, parent_belief_state_id, sequence_number, created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                state.belief_state_id,
                state.parent_belief_state_id,
                state.sequence,
                state.created_at,
            ),
        )
        connection.executemany(
            """
            INSERT INTO belief_state_probabilities (
                belief_state_id, hypothesis_id, prior_probability, posterior_probability
            )
            VALUES (?, ?, ?, ?)
            """,
            [
                (state.belief_state_id, hypothesis_id, prior, posterior)
                for hypothesis_id, prior, posterior in zip(
                    state.hypothesis_ids,
                    state.prior_probabilities,
                    state.posterior_probabilities,
                    strict=True,
                )
            ],
        )
        connection.executemany(
            """
            INSERT INTO belief_state_evidence (belief_state_id, evidence_id, evidence_order)
            VALUES (?, ?, ?)
            """,
            [
                (state.belief_state_id, evidence_id, evidence_order)
                for evidence_order, evidence_id in enumerate(state.evidence_ids)
            ],
        )

    def _provenance_from_row(self, row: sqlite3.Row) -> Provenance:
        return Provenance.create(
            method=str(row["provenance_method"]),
            version=str(row["provenance_version"]),
            details=self._provenance_mapping(str(row["provenance_json"])),
        )

    def _provenance_json(self, provenance: Provenance) -> str:
        return json.dumps(provenance.details_dict(), sort_keys=True, separators=(",", ":"))

    def _float_mapping(self, encoded: str) -> dict[str, float]:
        raw = cast(object, json.loads(encoded))
        if not isinstance(raw, dict):
            raise ReasoningError("Prediction parameters must be a JSON object.")
        result: dict[str, float] = {}
        for key, value in cast(dict[object, object], raw).items():
            if not isinstance(key, str):
                raise ReasoningError("Prediction parameter names must be strings.")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ReasoningError(f"Prediction parameter {key!r} must be numeric.")
            result[key] = float(value)
        return result

    def _provenance_mapping(self, encoded: str) -> dict[str, ProvenanceValue]:
        raw = cast(object, json.loads(encoded))
        if not isinstance(raw, dict):
            raise ReasoningError("Provenance details must be a JSON object.")
        result: dict[str, ProvenanceValue] = {}
        for key, value in cast(dict[object, object], raw).items():
            if not isinstance(key, str):
                raise ReasoningError("Provenance keys must be strings.")
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ReasoningError(f"Unsupported provenance value for {key!r}.")
            result[key] = value
        return result

    def _migrate_to_v1(self, connection: sqlite3.Connection) -> None:
        _execute_migration_statement(connection, _EXPERIMENTS_DDL)

    def _migrate_to_v2(self, connection: sqlite3.Connection) -> None:
        _execute_migration_script(
            connection,
            """
            CREATE TABLE IF NOT EXISTS hypotheses (
                id TEXT PRIMARY KEY,
                statement TEXT NOT NULL,
                prior_probability REAL NOT NULL CHECK (
                    prior_probability >= 0.0 AND prior_probability <= 1.0
                ),
                prediction_model_type TEXT NOT NULL,
                prediction_model_version TEXT NOT NULL,
                prediction_parameters_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY,
                observed_comparison REAL NOT NULL,
                observed_outcome TEXT NOT NULL,
                provenance_method TEXT NOT NULL,
                provenance_version TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evidence_sources (
                evidence_id TEXT NOT NULL REFERENCES evidence(id),
                experiment_id INTEGER NOT NULL REFERENCES experiments(id),
                source_order INTEGER NOT NULL CHECK (source_order >= 0),
                PRIMARY KEY (evidence_id, experiment_id),
                UNIQUE (evidence_id, source_order)
            );

            CREATE TABLE IF NOT EXISTS belief_states (
                id TEXT PRIMARY KEY,
                parent_belief_state_id TEXT REFERENCES belief_states(id),
                sequence_number INTEGER NOT NULL UNIQUE CHECK (sequence_number >= 0),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS belief_state_probabilities (
                belief_state_id TEXT NOT NULL REFERENCES belief_states(id),
                hypothesis_id TEXT NOT NULL REFERENCES hypotheses(id),
                prior_probability REAL NOT NULL CHECK (prior_probability >= 0.0),
                posterior_probability REAL NOT NULL CHECK (posterior_probability >= 0.0),
                PRIMARY KEY (belief_state_id, hypothesis_id)
            );

            CREATE TABLE IF NOT EXISTS belief_state_evidence (
                belief_state_id TEXT NOT NULL REFERENCES belief_states(id),
                evidence_id TEXT NOT NULL REFERENCES evidence(id),
                evidence_order INTEGER NOT NULL CHECK (evidence_order >= 0),
                PRIMARY KEY (belief_state_id, evidence_id),
                UNIQUE (belief_state_id, evidence_order)
            );

            CREATE TABLE IF NOT EXISTS belief_updates (
                id TEXT PRIMARY KEY,
                belief_state_before_id TEXT NOT NULL REFERENCES belief_states(id),
                evidence_id TEXT NOT NULL UNIQUE REFERENCES evidence(id),
                posterior_belief_state_id TEXT NOT NULL UNIQUE REFERENCES belief_states(id),
                update_rule_version TEXT NOT NULL,
                normalization_constant REAL NOT NULL CHECK (normalization_constant > 0.0),
                provenance_method TEXT NOT NULL,
                provenance_version TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS belief_update_likelihoods (
                belief_update_id TEXT NOT NULL REFERENCES belief_updates(id),
                hypothesis_id TEXT NOT NULL REFERENCES hypotheses(id),
                prior_for_update REAL NOT NULL CHECK (prior_for_update >= 0.0),
                likelihood REAL NOT NULL CHECK (likelihood >= 0.0),
                unnormalized_weight REAL NOT NULL CHECK (unnormalized_weight >= 0.0),
                posterior_probability REAL NOT NULL CHECK (posterior_probability >= 0.0),
                PRIMARY KEY (belief_update_id, hypothesis_id)
            );
            """,
        )

    def _migrate_to_v3(self, connection: sqlite3.Connection) -> None:
        _execute_migration_script(
            connection,
            """
            CREATE TABLE IF NOT EXISTS decision_traces (
                id TEXT PRIMARY KEY,
                policy TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                candidate_params_json TEXT NOT NULL,
                belief_state_id TEXT NOT NULL REFERENCES belief_states(id),
                expected_information_gain REAL NOT NULL CHECK (
                    expected_information_gain >= 0.0
                ),
                prior_entropy REAL NOT NULL CHECK (prior_entropy >= 0.0),
                expected_posterior_entropy REAL NOT NULL CHECK (
                    expected_posterior_entropy >= 0.0
                ),
                estimated_cost REAL NOT NULL CHECK (estimated_cost >= 0.0),
                max_cost REAL NOT NULL CHECK (max_cost >= 0.0),
                fallback_reason TEXT,
                rationale TEXT NOT NULL,
                provenance_method TEXT NOT NULL,
                provenance_version TEXT NOT NULL,
                provenance_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS decision_hypotheses (
                suggestion_id TEXT NOT NULL REFERENCES decision_traces(id),
                hypothesis_id TEXT NOT NULL REFERENCES hypotheses(id),
                statement TEXT NOT NULL,
                posterior_probability REAL NOT NULL CHECK (posterior_probability >= 0.0),
                most_favorable_outcome REAL NOT NULL,
                most_favorable_outcome_label TEXT NOT NULL,
                posterior_if_observed REAL NOT NULL CHECK (posterior_if_observed >= 0.0),
                PRIMARY KEY (suggestion_id, hypothesis_id)
            );

            CREATE TABLE IF NOT EXISTS decision_ranked_candidates (
                suggestion_id TEXT NOT NULL REFERENCES decision_traces(id),
                rank INTEGER NOT NULL CHECK (rank >= 0),
                candidate_id TEXT NOT NULL,
                candidate_params_json TEXT NOT NULL,
                expected_information_gain REAL NOT NULL CHECK (
                    expected_information_gain >= 0.0
                ),
                prior_entropy REAL NOT NULL CHECK (prior_entropy >= 0.0),
                expected_posterior_entropy REAL NOT NULL CHECK (
                    expected_posterior_entropy >= 0.0
                ),
                estimated_cost REAL NOT NULL CHECK (estimated_cost >= 0.0),
                completes_matched_pair INTEGER NOT NULL CHECK (
                    completes_matched_pair IN (0, 1)
                ),
                matched_experiment_id INTEGER REFERENCES experiments(id),
                score_reason TEXT NOT NULL,
                ranking_reason TEXT NOT NULL,
                PRIMARY KEY (suggestion_id, rank),
                UNIQUE (suggestion_id, candidate_id)
            );
            """,
        )

    def _migrate_to_v4(self, connection: sqlite3.Connection) -> None:
        _execute_migration_statement(
            connection,
            """
            CREATE TABLE IF NOT EXISTS lookahead_plan_traces (
                id TEXT PRIMARY KEY,
                policy TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                belief_state_id TEXT NOT NULL REFERENCES belief_states(id),
                candidate_id TEXT NOT NULL,
                expected_total_information_gain REAL NOT NULL CHECK (
                    expected_total_information_gain >= 0.0
                ),
                expected_total_cost REAL NOT NULL CHECK (expected_total_cost >= 0.0),
                information_gain_per_expected_cost REAL NOT NULL CHECK (
                    information_gain_per_expected_cost >= 0.0
                ),
                max_cost REAL NOT NULL CHECK (max_cost >= 0.0),
                trace_json TEXT NOT NULL,
                provenance_method TEXT NOT NULL,
                provenance_version TEXT NOT NULL,
                provenance_json TEXT NOT NULL
            )
            """,
        )

    def _migrate_to_v5(self, connection: sqlite3.Connection) -> None:
        _execute_migration_script(
            connection,
            """
            CREATE TABLE IF NOT EXISTS belief_models (
                id TEXT NOT NULL,
                version TEXT NOT NULL,
                is_default INTEGER NOT NULL CHECK (is_default IN (0, 1)),
                config_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (id, version)
            );

            CREATE TABLE IF NOT EXISTS belief_model_lineages (
                id TEXT PRIMARY KEY,
                belief_model_id TEXT NOT NULL,
                belief_model_version TEXT NOT NULL,
                lineage_key TEXT NOT NULL,
                current_state_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (belief_model_id, belief_model_version, lineage_key),
                FOREIGN KEY (belief_model_id, belief_model_version)
                    REFERENCES belief_models(id, version)
            );

            CREATE TABLE IF NOT EXISTS model_belief_states (
                id TEXT PRIMARY KEY,
                lineage_id TEXT NOT NULL REFERENCES belief_model_lineages(id),
                belief_model_id TEXT NOT NULL,
                belief_model_version TEXT NOT NULL,
                parent_state_id TEXT REFERENCES model_belief_states(id),
                sequence INTEGER NOT NULL CHECK (sequence >= 0),
                prior_probabilities_json TEXT NOT NULL,
                posterior_probabilities_json TEXT NOT NULL,
                evidence_ids_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (lineage_id, sequence),
                FOREIGN KEY (belief_model_id, belief_model_version)
                    REFERENCES belief_models(id, version)
            );

            CREATE TABLE IF NOT EXISTS sigma_estimates (
                id TEXT PRIMARY KEY,
                belief_model_id TEXT NOT NULL,
                belief_model_version TEXT NOT NULL,
                lineage_id TEXT NOT NULL REFERENCES belief_model_lineages(id),
                evidence_id TEXT NOT NULL REFERENCES evidence(id),
                comparison_group_id TEXT NOT NULL,
                cutoff_sequence INTEGER NOT NULL CHECK (cutoff_sequence > 0),
                sample_count INTEGER NOT NULL CHECK (sample_count >= 0),
                sample_mean REAL,
                raw_sample_standard_deviation REAL,
                sigma_floor REAL NOT NULL CHECK (sigma_floor > 0.0),
                variance_floor REAL NOT NULL CHECK (variance_floor > 0.0),
                estimated_sigma REAL NOT NULL CHECK (estimated_sigma > 0.0),
                status TEXT NOT NULL CHECK (
                    status IN ('fixed', 'baseline_fallback', 'calibrated')
                ),
                estimator_version TEXT NOT NULL,
                current_evidence_excluded INTEGER NOT NULL CHECK (
                    current_evidence_excluded = 1
                ),
                provenance_method TEXT NOT NULL,
                provenance_version TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (lineage_id, evidence_id),
                FOREIGN KEY (belief_model_id, belief_model_version)
                    REFERENCES belief_models(id, version)
            );

            CREATE TABLE IF NOT EXISTS calibration_prefixes (
                id TEXT PRIMARY KEY,
                world_id TEXT NOT NULL,
                evaluation_seed INTEGER NOT NULL,
                calibration_cost REAL NOT NULL CHECK (calibration_cost >= 0.0),
                provenance_method TEXT NOT NULL,
                provenance_version TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (world_id, evaluation_seed)
            );

            CREATE TABLE IF NOT EXISTS calibration_groups (
                id TEXT PRIMARY KEY,
                prefix_id TEXT NOT NULL REFERENCES calibration_prefixes(id),
                comparison_group_id TEXT NOT NULL,
                controlled_variables_json TEXT NOT NULL,
                intervention_variable TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (prefix_id, comparison_group_id)
            );

            CREATE TABLE IF NOT EXISTS calibration_replications (
                id TEXT PRIMARY KEY,
                calibration_group_id TEXT NOT NULL REFERENCES calibration_groups(id),
                replication_index INTEGER NOT NULL CHECK (replication_index >= 0),
                replication_seed TEXT NOT NULL,
                adam_arm_id TEXT NOT NULL UNIQUE,
                sgd_arm_id TEXT NOT NULL UNIQUE,
                provenance_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (calibration_group_id, replication_index),
                UNIQUE (calibration_group_id, replication_seed)
            );

            CREATE TABLE IF NOT EXISTS calibration_experiment_arms (
                id TEXT PRIMARY KEY,
                calibration_group_id TEXT NOT NULL REFERENCES calibration_groups(id),
                replication_id TEXT NOT NULL REFERENCES calibration_replications(id),
                replication_seed TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                intervention_arm TEXT NOT NULL CHECK (intervention_arm IN ('adam', 'sgd')),
                controlled_variables_json TEXT NOT NULL,
                observed_value REAL NOT NULL,
                cost REAL NOT NULL CHECK (cost >= 0.0),
                shared_key TEXT NOT NULL,
                arm_noise_key TEXT NOT NULL UNIQUE,
                successful INTEGER NOT NULL CHECK (successful = 1),
                provenance_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (replication_id, intervention_arm)
            );

            CREATE TABLE IF NOT EXISTS calibration_matched_effects (
                id TEXT PRIMARY KEY,
                calibration_group_id TEXT NOT NULL REFERENCES calibration_groups(id),
                comparison_group_id TEXT NOT NULL,
                replication_id TEXT NOT NULL UNIQUE REFERENCES calibration_replications(id),
                replication_seed TEXT NOT NULL,
                adam_arm_id TEXT NOT NULL UNIQUE REFERENCES calibration_experiment_arms(id),
                sgd_arm_id TEXT NOT NULL UNIQUE REFERENCES calibration_experiment_arms(id),
                observed_effect REAL NOT NULL,
                available_sequence INTEGER NOT NULL CHECK (available_sequence = 0),
                scientific_evidence INTEGER NOT NULL CHECK (scientific_evidence = 0),
                provenance_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sigma_estimate_sources (
                sigma_estimate_id TEXT NOT NULL REFERENCES sigma_estimates(id),
                source_effect_id TEXT NOT NULL,
                source_kind TEXT NOT NULL CHECK (source_kind IN ('calibration', 'decision')),
                source_order INTEGER NOT NULL CHECK (source_order >= 0),
                PRIMARY KEY (sigma_estimate_id, source_effect_id),
                UNIQUE (sigma_estimate_id, source_order)
            );

            CREATE TABLE IF NOT EXISTS model_belief_updates (
                id TEXT PRIMARY KEY,
                belief_model_id TEXT NOT NULL,
                belief_model_version TEXT NOT NULL,
                lineage_id TEXT NOT NULL REFERENCES belief_model_lineages(id),
                state_before_id TEXT NOT NULL REFERENCES model_belief_states(id),
                evidence_id TEXT NOT NULL REFERENCES evidence(id),
                sigma_estimate_id TEXT NOT NULL UNIQUE REFERENCES sigma_estimates(id),
                posterior_state_id TEXT NOT NULL UNIQUE REFERENCES model_belief_states(id),
                bayesian_update_id TEXT NOT NULL,
                update_rule_version TEXT NOT NULL,
                normalization_constant REAL NOT NULL CHECK (normalization_constant > 0.0),
                provenance_method TEXT NOT NULL,
                provenance_version TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (belief_model_id, lineage_id, evidence_id),
                FOREIGN KEY (belief_model_id, belief_model_version)
                    REFERENCES belief_models(id, version)
            );

            CREATE TABLE IF NOT EXISTS model_belief_update_likelihoods (
                model_update_id TEXT NOT NULL REFERENCES model_belief_updates(id),
                belief_model_id TEXT NOT NULL,
                lineage_id TEXT NOT NULL,
                hypothesis_id TEXT NOT NULL REFERENCES hypotheses(id),
                prior_for_update REAL NOT NULL CHECK (prior_for_update >= 0.0),
                likelihood REAL NOT NULL CHECK (likelihood >= 0.0),
                unnormalized_weight REAL NOT NULL CHECK (unnormalized_weight >= 0.0),
                posterior_probability REAL NOT NULL CHECK (posterior_probability >= 0.0),
                PRIMARY KEY (model_update_id, hypothesis_id)
            );

            CREATE TABLE IF NOT EXISTS model_adequacy_diagnostics (
                id TEXT PRIMARY KEY,
                belief_model_id TEXT NOT NULL,
                belief_model_version TEXT NOT NULL,
                lineage_id TEXT NOT NULL REFERENCES belief_model_lineages(id),
                belief_state_before_id TEXT NOT NULL REFERENCES model_belief_states(id),
                evidence_id TEXT NOT NULL REFERENCES evidence(id),
                sigma_estimate_id TEXT NOT NULL REFERENCES sigma_estimates(id),
                comparison_group_id TEXT NOT NULL,
                predictive_mean REAL NOT NULL,
                predictive_variance REAL NOT NULL CHECK (predictive_variance > 0.0),
                predictive_density REAL NOT NULL CHECK (predictive_density > 0.0),
                predictive_log_likelihood REAL NOT NULL,
                predictive_cdf REAL NOT NULL CHECK (predictive_cdf BETWEEN 0.0 AND 1.0),
                tail_probability REAL NOT NULL CHECK (tail_probability BETWEEN 0.0 AND 1.0),
                standardized_residual REAL NOT NULL,
                residual_count INTEGER NOT NULL CHECK (residual_count > 0),
                rolling_outlier_count INTEGER NOT NULL CHECK (rolling_outlier_count >= 0),
                tail_alarm INTEGER NOT NULL CHECK (tail_alarm IN (0, 1)),
                residual_outlier INTEGER NOT NULL CHECK (residual_outlier IN (0, 1)),
                repeated_residual_alarm INTEGER NOT NULL CHECK (
                    repeated_residual_alarm IN (0, 1)
                ),
                diagnostics_disagree INTEGER NOT NULL CHECK (
                    diagnostics_disagree IN (0, 1)
                ),
                adequacy_state TEXT NOT NULL CHECK (
                    adequacy_state IN ('adequate', 'uncertain', 'appears_misspecified')
                ),
                diagnostic_version TEXT NOT NULL,
                details_json TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (lineage_id, evidence_id)
            );

            CREATE TABLE IF NOT EXISTS calibration_cost_entries (
                id TEXT PRIMARY KEY,
                prefix_id TEXT NOT NULL REFERENCES calibration_prefixes(id),
                calibration_arm_id TEXT NOT NULL UNIQUE REFERENCES calibration_experiment_arms(id),
                source_record_key TEXT NOT NULL UNIQUE,
                cost REAL NOT NULL CHECK (cost >= 0.0),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS decision_cost_entries (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                experiment_id INTEGER NOT NULL REFERENCES experiments(id),
                source_record_key TEXT NOT NULL UNIQUE,
                cost REAL NOT NULL CHECK (cost >= 0.0),
                created_at TEXT NOT NULL,
                UNIQUE (run_id, experiment_id)
            );

            CREATE TRIGGER IF NOT EXISTS calibration_cost_ledger_disjoint
            BEFORE INSERT ON calibration_cost_entries
            WHEN EXISTS (
                SELECT 1 FROM decision_cost_entries
                WHERE source_record_key = NEW.source_record_key
            )
            BEGIN
                SELECT RAISE(ABORT, 'source record already belongs to decision ledger');
            END;

            CREATE TRIGGER IF NOT EXISTS decision_cost_ledger_disjoint
            BEFORE INSERT ON decision_cost_entries
            WHEN EXISTS (
                SELECT 1 FROM calibration_cost_entries
                WHERE source_record_key = NEW.source_record_key
            )
            BEGIN
                SELECT RAISE(ABORT, 'source record already belongs to calibration ledger');
            END;
            """,
        )

    def _migrate_to_v6(self, connection: sqlite3.Connection) -> None:
        existing = connection.execute(
            "SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = ?",
            ("workload_experiments",),
        ).fetchone()
        if existing is not None:
            if not _same_schema_sql(existing[0], _WORKLOAD_EXPERIMENTS_DDL):
                raise RuntimeError("Existing workload_experiments table does not match schema v6.")
            return
        _execute_migration_statement(connection, _WORKLOAD_EXPERIMENTS_DDL)


def _schema_version_from(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    if row is None:
        raise RuntimeError("SQLite did not return a schema version.")
    try:
        version = int(row[0])
    except (TypeError, ValueError) as error:
        raise RuntimeError("SQLite returned a malformed schema version.") from error
    return version


def _validate_supported_schema_version(version: int) -> None:
    if version < 0:
        raise RuntimeError(f"Database schema version {version} is unsupported.")
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema version {version} is newer than supported version {SCHEMA_VERSION}."
        )


def _validate_schema_for_version(connection: sqlite3.Connection, version: int) -> None:
    _validate_supported_schema_version(version)
    rows = connection.execute(
        """
        SELECT type, name, sql
        FROM sqlite_schema
        WHERE type IN ('table', 'index', 'trigger', 'view')
          AND substr(name, 1, 7) != 'sqlite_'
        ORDER BY type, name
        """
    ).fetchall()
    actual = {str(row[1]): (str(row[0]), row[2]) for row in rows}
    if version == 0:
        unexpected = sorted(name for name in actual if name != "experiments")
        if unexpected:
            raise RuntimeError(
                "Unversioned database contains unsupported schema objects: "
                + ", ".join(unexpected)
                + "."
            )
        experiments = actual.get("experiments")
        if experiments is not None:
            object_type, sql = experiments
            if object_type != "table" or not _same_schema_sql(sql, _EXPERIMENTS_DDL):
                raise RuntimeError("Unversioned experiments table does not match schema v1.")
    else:
        for introduced_version, expected_type, name in _MIGRATION_SCHEMA_OBJECTS:
            found = actual.get(name)
            if introduced_version <= version:
                if found is None:
                    raise RuntimeError(
                        f"Database schema v{version} is missing {expected_type} {name}."
                    )
                object_type, sql = found
                if (
                    object_type != expected_type
                    or sql is None
                    or _schema_sql_sha256(sql) != _MIGRATION_SCHEMA_SQL_SHA256[name]
                ):
                    if name == "workload_experiments":
                        raise RuntimeError(
                            "Existing workload_experiments table does not match schema v6."
                        )
                    raise RuntimeError(
                        f"Database schema v{version} has a noncanonical {expected_type} {name}."
                    )
            elif found is not None:
                if (
                    name == "workload_experiments"
                    and version == 5
                    and not _same_schema_sql(found[1], _WORKLOAD_EXPERIMENTS_DDL)
                ):
                    raise RuntimeError(
                        "Existing workload_experiments table does not match schema v6."
                    )
                raise RuntimeError(
                    f"Database schema contains {name}, which is newer than user_version {version}."
                )

    workload = actual.get("workload_experiments")
    if version >= 6 and (
        workload is None
        or workload[0] != "table"
        or not _same_schema_sql(workload[1], _WORKLOAD_EXPERIMENTS_DDL)
    ):
        raise RuntimeError("Existing workload_experiments table does not match schema v6.")

    integrity = connection.execute("PRAGMA integrity_check").fetchone()
    if integrity is None or str(integrity[0]) != "ok":
        raise RuntimeError(f"SQLite integrity check failed for schema v{version}.")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise RuntimeError(f"SQLite foreign-key check failed for schema v{version}.")


def _same_schema_sql(actual: object, expected: str) -> bool:
    if actual is None:
        return False
    normalized_actual = _normalize_schema_sql(actual)
    normalized_expected = _normalize_schema_sql(expected).replace(
        "CREATE TABLE IF NOT EXISTS", "CREATE TABLE", 1
    )
    return normalized_actual == normalized_expected


def _normalize_schema_sql(sql: object) -> str:
    """Collapse SQL whitespace only where it cannot change a quoted literal."""

    characters = str(sql)
    normalized: list[str] = []
    quote: str | None = None
    pending_space = False
    index = 0
    while index < len(characters):
        character = characters[index]
        if quote is not None:
            normalized.append(character)
            if quote == "]":
                if character == "]":
                    quote = None
            elif character == quote:
                if index + 1 < len(characters) and characters[index + 1] == quote:
                    normalized.append(characters[index + 1])
                    index += 1
                else:
                    quote = None
            index += 1
            continue

        if character.isspace():
            pending_space = bool(normalized)
            index += 1
            continue
        if pending_space:
            normalized.append(" ")
            pending_space = False
        normalized.append(character)
        if character in {"'", '"', "`"}:
            quote = character
        elif character == "[":
            quote = "]"
        index += 1
    return "".join(normalized)


def _schema_sql_sha256(sql: object) -> str:
    normalized = _normalize_schema_sql(sql).encode("utf-8")
    return sha256(normalized).hexdigest()


def _execute_migration_statement(connection: sqlite3.Connection, statement: str) -> None:
    if not connection.in_transaction:
        raise RuntimeError("Migration statements require an active owned transaction.")
    connection.execute(statement)


def _execute_migration_script(connection: sqlite3.Connection, script: str) -> None:
    buffer: list[str] = []
    for character in script:
        buffer.append(character)
        if character != ";":
            continue
        candidate = "".join(buffer)
        if sqlite3.complete_statement(candidate):
            if candidate.strip():
                _execute_migration_statement(connection, candidate)
            buffer.clear()
    if "".join(buffer).strip():
        raise RuntimeError("Migration SQL contains an incomplete statement.")


def _validate_run_spec_fingerprint(value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("run_spec_fingerprint must be a lowercase SHA-256 hex digest.")
    return value
