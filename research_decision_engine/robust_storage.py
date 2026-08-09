"""SQLite persistence for versioned belief models and calibration records."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from research_decision_engine.belief_models import (
    DEFAULT_BELIEF_MODEL_ID,
    BeliefModelLineage,
    MatchedEffectObservation,
    ModelBeliefState,
    ModelBeliefUpdate,
    belief_models,
)
from research_decision_engine.calibration import CalibrationPrefix
from research_decision_engine.optimizer_effect import optimizer_effect_hypotheses
from research_decision_engine.reasoning import DuplicateEvidenceError, ReasoningError
from research_decision_engine.storage import ExperimentStore
from research_decision_engine.types import ExperimentRecord


class RobustBeliefStore:
    """Add model-scoped records through an initialized ``ExperimentStore``."""

    def __init__(self, store: ExperimentStore) -> None:
        self.store = store

    def register_models(self, *, created_at: str) -> None:
        connection = self._connection()
        with connection:
            for model in belief_models():
                connection.execute(
                    """
                    INSERT INTO belief_models (id, version, is_default, config_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (id, version) DO NOTHING
                    """,
                    (
                        model.model_id,
                        model.model_version,
                        int(model.model_id == DEFAULT_BELIEF_MODEL_ID),
                        json.dumps(
                            {
                                "likelihood_family": "gaussian",
                                "model_id": model.model_id,
                                "model_version": model.model_version,
                            },
                            sort_keys=True,
                        ),
                        created_at,
                    ),
                )

    def add_calibration_prefix(self, prefix: CalibrationPrefix) -> None:
        """Persist a calibration prefix atomically without scientific evidence links."""

        connection = self._connection()
        with connection:
            connection.execute(
                """
                INSERT INTO calibration_prefixes (
                    id, world_id, evaluation_seed, calibration_cost,
                    provenance_method, provenance_version, provenance_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prefix.prefix_id,
                    prefix.world_id,
                    prefix.evaluation_seed,
                    prefix.calibration_cost,
                    prefix.provenance.method,
                    prefix.provenance.version,
                    _json(prefix.provenance.to_dict()),
                    prefix.created_at,
                ),
            )
            for group in prefix.groups:
                connection.execute(
                    """
                    INSERT INTO calibration_groups (
                        id, prefix_id, comparison_group_id, controlled_variables_json,
                        intervention_variable, provenance_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        group.calibration_group_id,
                        prefix.prefix_id,
                        group.comparison_group_id,
                        _json(dict(group.controlled_variables)),
                        group.intervention_variable,
                        _json(group.provenance.to_dict()),
                        group.created_at,
                    ),
                )
            for replication in prefix.replications:
                connection.execute(
                    """
                    INSERT INTO calibration_replications (
                        id, calibration_group_id, replication_index, replication_seed,
                        adam_arm_id, sgd_arm_id, provenance_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        replication.replication_id,
                        replication.calibration_group_id,
                        replication.replication_index,
                        replication.replication_seed,
                        replication.adam_arm_id,
                        replication.sgd_arm_id,
                        _json(replication.provenance.to_dict()),
                        replication.created_at,
                    ),
                )
            for arm in prefix.arms:
                connection.execute(
                    """
                    INSERT INTO calibration_experiment_arms (
                        id, calibration_group_id, replication_id, replication_seed,
                        candidate_id, intervention_arm, controlled_variables_json,
                        observed_value, cost, shared_key, arm_noise_key, successful,
                        provenance_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        arm.calibration_arm_id,
                        arm.calibration_group_id,
                        arm.replication_id,
                        arm.replication_seed,
                        arm.candidate_id,
                        arm.intervention_arm,
                        _json(dict(arm.controlled_variables)),
                        arm.observed_value,
                        arm.cost,
                        arm.shared_key,
                        arm.arm_noise_key,
                        int(arm.successful),
                        _json(arm.provenance.to_dict()),
                        arm.created_at,
                    ),
                )
            for effect in prefix.matched_effects:
                connection.execute(
                    """
                    INSERT INTO calibration_matched_effects (
                        id, calibration_group_id, comparison_group_id, replication_id,
                        replication_seed, adam_arm_id, sgd_arm_id, observed_effect,
                        available_sequence, scientific_evidence, provenance_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        effect.calibration_effect_id,
                        effect.calibration_group_id,
                        effect.comparison_group_id,
                        effect.replication_id,
                        effect.replication_seed,
                        effect.adam_arm_id,
                        effect.sgd_arm_id,
                        effect.observed_effect,
                        effect.available_sequence,
                        _json(effect.provenance.to_dict()),
                        effect.created_at,
                    ),
                )
            for arm in prefix.arms:
                connection.execute(
                    """
                    INSERT INTO calibration_cost_entries (
                        id, prefix_id, calibration_arm_id, source_record_key, cost, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _stable_id("calibration-cost", arm.calibration_arm_id),
                        prefix.prefix_id,
                        arm.calibration_arm_id,
                        f"calibration-arm:{arm.calibration_arm_id}",
                        arm.cost,
                        arm.created_at,
                    ),
                )

    def add_lineage(self, lineage: BeliefModelLineage) -> None:
        self.store.register_hypotheses(optimizer_effect_hypotheses())
        self.register_models(created_at=lineage.created_at)
        connection = self._connection()
        with connection:
            connection.execute(
                """
                INSERT INTO belief_model_lineages (
                    id, belief_model_id, belief_model_version, lineage_key,
                    current_state_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    lineage.lineage_id,
                    lineage.belief_model_id,
                    lineage.belief_model_version,
                    lineage.lineage_key,
                    lineage.current_state.state.belief_state_id,
                    lineage.created_at,
                ),
            )
            self._insert_state(connection, lineage.current_state)

    def add_model_update(
        self,
        update: ModelBeliefUpdate,
        *,
        effect_history: tuple[MatchedEffectObservation, ...],
    ) -> None:
        """Persist one complete model update and advance only its lineage pointer."""

        connection = self._connection()
        source_by_id = {item.effect_id: item for item in effect_history}
        missing = set(update.sigma_estimate.source_effect_ids).difference(source_by_id)
        if missing:
            raise ReasoningError("Missing sigma-estimate sources: " + ", ".join(sorted(missing)))
        try:
            with connection:
                self._insert_state(connection, update.posterior_state)
                estimate = update.sigma_estimate
                connection.execute(
                    """
                    INSERT INTO sigma_estimates (
                        id, belief_model_id, belief_model_version, lineage_id, evidence_id,
                        comparison_group_id, cutoff_sequence, sample_count, sample_mean,
                        raw_sample_standard_deviation, sigma_floor, variance_floor,
                        estimated_sigma, status, estimator_version, current_evidence_excluded,
                        provenance_method, provenance_version, provenance_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        estimate.estimate_id,
                        estimate.belief_model_id,
                        estimate.belief_model_version,
                        estimate.lineage_id,
                        estimate.evidence_id,
                        estimate.comparison_group_id,
                        estimate.cutoff_sequence,
                        estimate.sample_count,
                        estimate.sample_mean,
                        estimate.raw_sample_standard_deviation,
                        estimate.sigma_floor,
                        estimate.variance_floor,
                        estimate.estimated_sigma,
                        estimate.status,
                        estimate.estimator_version,
                        int(estimate.current_evidence_excluded),
                        estimate.provenance.method,
                        estimate.provenance.version,
                        _json(estimate.provenance.to_dict()),
                        estimate.created_at,
                    ),
                )
                for source_order, source_id in enumerate(estimate.source_effect_ids):
                    source = source_by_id[source_id]
                    connection.execute(
                        """
                        INSERT INTO sigma_estimate_sources (
                            sigma_estimate_id, source_effect_id, source_kind, source_order
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (estimate.estimate_id, source_id, source.source_kind, source_order),
                    )
                bayes = update.bayesian_update
                connection.execute(
                    """
                    INSERT INTO model_belief_updates (
                        id, belief_model_id, belief_model_version, lineage_id,
                        state_before_id, evidence_id, sigma_estimate_id, posterior_state_id,
                        bayesian_update_id, update_rule_version, normalization_constant,
                        provenance_method, provenance_version, provenance_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        update.model_update_id,
                        update.belief_model_id,
                        update.belief_model_version,
                        update.lineage_id,
                        update.state_before.state.belief_state_id,
                        update.evidence.evidence_id,
                        estimate.estimate_id,
                        update.posterior_state.state.belief_state_id,
                        bayes.update_id,
                        bayes.update_rule_version,
                        bayes.normalization_constant,
                        update.provenance.method,
                        update.provenance.version,
                        _json(update.provenance.to_dict()),
                        update.created_at,
                    ),
                )
                for likelihood in bayes.likelihoods:
                    connection.execute(
                        """
                        INSERT INTO model_belief_update_likelihoods (
                            model_update_id, belief_model_id, lineage_id, hypothesis_id,
                            prior_for_update, likelihood, unnormalized_weight,
                            posterior_probability
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            update.model_update_id,
                            update.belief_model_id,
                            update.lineage_id,
                            likelihood.hypothesis_id,
                            likelihood.prior_for_update,
                            likelihood.likelihood,
                            likelihood.unnormalized_weight,
                            likelihood.posterior_probability,
                        ),
                    )
                diagnostic = update.diagnostic
                connection.execute(
                    """
                    INSERT INTO model_adequacy_diagnostics (
                        id, belief_model_id, belief_model_version, lineage_id,
                        belief_state_before_id, evidence_id, sigma_estimate_id,
                        comparison_group_id, predictive_mean, predictive_variance,
                        predictive_density, predictive_log_likelihood, predictive_cdf,
                        tail_probability, standardized_residual, residual_count,
                        rolling_outlier_count, tail_alarm, residual_outlier,
                        repeated_residual_alarm, diagnostics_disagree, adequacy_state,
                        diagnostic_version, details_json, provenance_json, created_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        diagnostic.diagnostic_id,
                        diagnostic.belief_model_id,
                        diagnostic.belief_model_version,
                        diagnostic.lineage_id,
                        diagnostic.belief_state_before_id,
                        diagnostic.evidence_id,
                        diagnostic.sigma_estimate_id,
                        diagnostic.comparison_group_id,
                        diagnostic.predictive_mean,
                        diagnostic.predictive_variance,
                        diagnostic.predictive_density,
                        diagnostic.predictive_log_likelihood,
                        diagnostic.predictive_cdf,
                        diagnostic.posterior_predictive_tail_probability,
                        diagnostic.standardized_residual,
                        diagnostic.residual_count,
                        diagnostic.rolling_residual_outlier_count,
                        int(diagnostic.tail_alarm),
                        int(diagnostic.residual_outlier),
                        int(diagnostic.repeated_residual_alarm),
                        int(diagnostic.diagnostics_disagree),
                        diagnostic.adequacy_state,
                        diagnostic.diagnostic_version,
                        _json(
                            {
                                "central_intervals": [
                                    item.to_dict() for item in diagnostic.central_intervals
                                ],
                                "per_hypothesis_residuals": dict(
                                    diagnostic.per_hypothesis_residuals
                                ),
                            }
                        ),
                        _json(diagnostic.provenance.to_dict()),
                        diagnostic.created_at,
                    ),
                )
                connection.execute(
                    """
                    UPDATE belief_model_lineages
                    SET current_state_id = ?
                    WHERE id = ? AND current_state_id = ?
                    """,
                    (
                        update.posterior_state.state.belief_state_id,
                        update.lineage_id,
                        update.state_before.state.belief_state_id,
                    ),
                )
                if connection.execute("SELECT changes()").fetchone()[0] != 1:
                    raise ReasoningError(
                        "Belief lineage current-state pointer changed concurrently."
                    )
        except sqlite3.IntegrityError as error:
            if "model_belief_updates" in str(error) or "UNIQUE constraint" in str(error):
                raise DuplicateEvidenceError(
                    f"Evidence {update.evidence.evidence_id} is already applied to this lineage."
                ) from error
            raise

    def add_decision_cost(
        self,
        *,
        run_id: str,
        record: ExperimentRecord,
        source_record_key: str | None = None,
    ) -> None:
        if record.record_id is None:
            raise ReasoningError("Decision cost requires a persisted experiment record.")
        key = source_record_key or f"experiment:{record.record_id}"
        connection = self._connection()
        with connection:
            connection.execute(
                """
                INSERT INTO decision_cost_entries (
                    id, run_id, experiment_id, source_record_key, cost, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    _stable_id("decision-cost", f"{run_id}:{record.record_id}"),
                    run_id,
                    record.record_id,
                    key,
                    record.cost,
                    record.created_at,
                ),
            )

    def calibration_history(self) -> list[dict[str, Any]]:
        rows = (
            self._connection()
            .execute(
                """
            SELECT e.id, p.world_id, p.evaluation_seed, g.comparison_group_id,
                   e.replication_id, e.replication_seed, e.observed_effect,
                   e.adam_arm_id, e.sgd_arm_id, e.created_at
            FROM calibration_matched_effects AS e
            JOIN calibration_groups AS g ON g.id = e.calibration_group_id
            JOIN calibration_prefixes AS p ON p.id = g.prefix_id
            ORDER BY p.world_id, p.evaluation_seed, g.comparison_group_id, e.replication_id
            """
            )
            .fetchall()
        )
        return [dict(row) for row in rows]

    def sigma_estimates(self) -> list[dict[str, Any]]:
        rows = (
            self._connection()
            .execute(
                """
            SELECT id, belief_model_id, belief_model_version, lineage_id, evidence_id,
                   comparison_group_id, cutoff_sequence, sample_count, sample_mean,
                   raw_sample_standard_deviation, sigma_floor, variance_floor,
                   estimated_sigma, status, estimator_version, created_at
            FROM sigma_estimates
            ORDER BY created_at, lineage_id, cutoff_sequence
            """
            )
            .fetchall()
        )
        return [dict(row) for row in rows]

    def belief_lineages(self) -> list[dict[str, Any]]:
        rows = (
            self._connection()
            .execute(
                """
            SELECT l.id, l.belief_model_id, l.belief_model_version, l.lineage_key,
                   l.current_state_id, s.sequence, s.posterior_probabilities_json,
                   l.created_at
            FROM belief_model_lineages AS l
            JOIN model_belief_states AS s ON s.id = l.current_state_id
            ORDER BY l.belief_model_id, l.lineage_key
            """
            )
            .fetchall()
        )
        return [dict(row) for row in rows]

    def model_adequacy(self) -> list[dict[str, Any]]:
        rows = (
            self._connection()
            .execute(
                """
            SELECT id, belief_model_id, belief_model_version, lineage_id, evidence_id,
                   comparison_group_id, tail_probability, standardized_residual,
                   predictive_log_likelihood, residual_count, rolling_outlier_count,
                   tail_alarm, residual_outlier, repeated_residual_alarm,
                   diagnostics_disagree, adequacy_state, diagnostic_version, created_at
            FROM model_adequacy_diagnostics
            ORDER BY created_at, lineage_id, residual_count
            """
            )
            .fetchall()
        )
        return [dict(row) for row in rows]

    def explain_sigma_estimate(self, estimate_id: str) -> dict[str, Any] | None:
        row = (
            self._connection()
            .execute(
                "SELECT * FROM sigma_estimates WHERE id = ?",
                (estimate_id,),
            )
            .fetchone()
        )
        if row is None:
            return None
        sources = (
            self._connection()
            .execute(
                """
            SELECT s.source_effect_id, s.source_kind, s.source_order,
                   COALESCE(c.observed_effect, e.observed_comparison) AS observed_effect,
                   c.replication_id, c.replication_seed,
                   e.provenance_json AS decision_evidence_provenance_json,
                   c.provenance_json AS calibration_effect_provenance_json
            FROM sigma_estimate_sources AS s
            LEFT JOIN calibration_matched_effects AS c
                ON s.source_kind = 'calibration' AND c.id = s.source_effect_id
            LEFT JOIN evidence AS e
                ON s.source_kind = 'decision' AND e.id = s.source_effect_id
            WHERE s.sigma_estimate_id = ?
            ORDER BY s.source_order
            """,
                (estimate_id,),
            )
            .fetchall()
        )
        diagnostic = (
            self._connection()
            .execute(
                """
            SELECT id, tail_probability,
                   standardized_residual, predictive_log_likelihood, residual_count,
                   adequacy_state, details_json, provenance_json
            FROM model_adequacy_diagnostics
            WHERE sigma_estimate_id = ?
            """,
                (estimate_id,),
            )
            .fetchone()
        )
        result: dict[str, Any] = dict(row)
        result["sources"] = [dict(item) for item in sources]
        result["diagnostic"] = None if diagnostic is None else dict(diagnostic)
        return result

    def cost_summary(self) -> dict[str, float]:
        connection = self._connection()
        calibration = float(
            connection.execute(
                "SELECT COALESCE(SUM(cost), 0.0) FROM calibration_cost_entries"
            ).fetchone()[0]
        )
        decision = float(
            connection.execute(
                "SELECT COALESCE(SUM(cost), 0.0) FROM decision_cost_entries"
            ).fetchone()[0]
        )
        return {
            "calibration_cost": calibration,
            "decision_cost": decision,
            "total_cost": calibration + decision,
        }

    @staticmethod
    def _insert_state(connection: sqlite3.Connection, state: ModelBeliefState) -> None:
        inner = state.state
        connection.execute(
            """
            INSERT INTO model_belief_states (
                id, lineage_id, belief_model_id, belief_model_version, parent_state_id,
                sequence, prior_probabilities_json, posterior_probabilities_json,
                evidence_ids_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                inner.belief_state_id,
                state.lineage_id,
                state.belief_model_id,
                state.belief_model_version,
                inner.parent_belief_state_id,
                inner.sequence,
                _json(inner.prior_map()),
                _json(inner.posterior_map()),
                _json(inner.evidence_ids),
                inner.created_at,
            ),
        )

    def _connection(self) -> sqlite3.Connection:
        if self.store.connection is None:
            raise RuntimeError("ExperimentStore must be open before robust belief persistence.")
        return self.store.connection


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"
