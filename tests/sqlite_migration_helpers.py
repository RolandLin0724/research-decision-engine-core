from __future__ import annotations

import sqlite3

# Test-owned helpers for constructing exact historical SQLite schemas.


_OBJECTS_BY_INTRODUCTION: tuple[tuple[int, str, str], ...] = (
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


def downgrade_to_exact_schema(connection: sqlite3.Connection, target_version: int) -> None:
    """Remove all later-version objects from a latest-schema test database."""

    if connection.in_transaction:
        raise RuntimeError("Test schema downgrade requires no active transaction.")
    connection.execute("PRAGMA foreign_keys = OFF")
    later_objects = [
        (object_type, name)
        for introduced_version, object_type, name in _OBJECTS_BY_INTRODUCTION
        if introduced_version > target_version
    ]
    order = {"trigger": 0, "view": 1, "index": 2, "table": 3}
    for object_type, name in sorted(later_objects, key=lambda item: order[item[0]]):
        connection.execute(f'DROP {object_type.upper()} IF EXISTS "{name}"')
    connection.execute(f"PRAGMA user_version = {target_version}")
    connection.commit()
