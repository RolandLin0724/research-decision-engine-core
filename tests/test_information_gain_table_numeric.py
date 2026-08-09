from __future__ import annotations

from decimal import ROUND_DOWN, Decimal, Underflow, getcontext, setcontext

import pytest

from research_decision_engine.information_gain_table import (
    INFORMATION_GAIN_NUMERIC_CONTRACT,
    FiniteTableEvidenceModel,
    ImpossibleEvidenceError,
    InformationGainBeliefLineage,
    TableInformationGainPolicy,
    expected_information_gain_bits,
    format_information_gain_bits,
    information_gain_belief_fingerprint,
    initial_information_gain_belief,
    update_information_gain_belief,
)
from research_decision_engine.run_spec import (
    CandidateSpec,
    CompletedWorkloadExperiment,
    NormalizedObservation,
)
from research_decision_engine.run_spec_v3 import RunSpecV3


def _numeric_model() -> FiniteTableEvidenceModel:
    return FiniteTableEvidenceModel(
        hypothesis_ids=("h0", "h1"),
        prior_weight_by_hypothesis={"h0": 1, "h1": 1},
        observation_metric="metric",
        outcome_ids=("left", "right"),
        outcome_thresholds=(0.0,),
        likelihood_row_total=2,
        likelihood_weight_by_candidate_id={
            "deterministic": {
                "h0": {"left": 2, "right": 0},
                "h1": {"left": 0, "right": 2},
            },
            "uninformative": {
                "h0": {"left": 1, "right": 1},
                "h1": {"left": 1, "right": 1},
            },
            "gcd": {
                "h0": {"left": 2, "right": 0},
                "h1": {"left": 1, "right": 1},
            },
            "impossible-left": {
                "h0": {"left": 0, "right": 2},
                "h1": {"left": 0, "right": 2},
            },
        },
    )


def test_numeric_contract_is_frozen_and_public() -> None:
    assert INFORMATION_GAIN_NUMERIC_CONTRACT.to_payload() == {
        "implementation": "decimal.Decimal",
        "precision": 50,
        "rounding": "ROUND_HALF_EVEN",
        "logarithm": "Decimal.ln",
        "base_conversion": "divide_by_Decimal_2_ln",
        "score_quantum": "1e-30",
    }


def test_initial_and_updated_belief_use_exact_integer_weights_and_gcd() -> None:
    model = _numeric_model()
    assert initial_information_gain_belief(model) == (1, 1)
    before_payload = model.to_payload()

    # (6 * 2, 2 * 1) -> (12, 2) -> GCD reduction -> (6, 1).
    updated = update_information_gain_belief(
        model,
        (6, 2),
        candidate_id="gcd",
        outcome_id="left",
    )

    assert updated == (6, 1)
    assert all(type(item) is int for item in updated)
    assert model.to_payload() == before_payload


def test_impossible_zero_probability_evidence_is_rejected() -> None:
    with pytest.raises(ImpossibleEvidenceError):
        update_information_gain_belief(
            _numeric_model(),
            (1, 1),
            candidate_id="impossible-left",
            outcome_id="left",
        )


def test_belief_fingerprint_binds_schema_order_and_exact_weights() -> None:
    left = information_gain_belief_fingerprint(("h0", "h1"), (2, 1))
    repeated = information_gain_belief_fingerprint(("h0", "h1"), (2, 1))
    changed_weight = information_gain_belief_fingerprint(("h0", "h1"), (1, 2))
    changed_order = information_gain_belief_fingerprint(("h1", "h0"), (2, 1))

    assert left == repeated
    assert left != changed_weight
    assert left != changed_order
    assert len(left) == 64


def test_information_gain_known_one_bit_case_and_entropy_zero_case() -> None:
    model = _numeric_model()
    one_bit = expected_information_gain_bits(model, (1, 1), "deterministic")
    certain = expected_information_gain_bits(model, (1, 0), "deterministic")
    uninformative = expected_information_gain_bits(model, (1, 1), "uninformative")

    assert one_bit == Decimal("1.000000000000000000000000000000")
    assert certain == Decimal("0.000000000000000000000000000000")
    assert uninformative == Decimal("0.000000000000000000000000000000")


def test_decimal_scoring_uses_local_50_digit_context_and_is_repeatable() -> None:
    model = _numeric_model()
    global_context = getcontext()
    original_precision = global_context.prec
    original_rounding = global_context.rounding
    global_context.prec = 7
    global_context.rounding = ROUND_DOWN
    try:
        left = expected_information_gain_bits(model, (2, 3), "gcd")
        right = expected_information_gain_bits(model, (2, 3), "gcd")
    finally:
        global_context.prec = original_precision
        global_context.rounding = original_rounding

    assert left == right
    assert left.as_tuple().exponent == -30
    assert format_information_gain_bits(left) == format(left, ".30f")


def test_decimal_scoring_is_isolated_from_ambient_exponents_and_traps() -> None:
    model = _numeric_model()
    baseline = expected_information_gain_bits(model, (1, 10**100), "gcd")
    original_context = getcontext().copy()
    global_context = getcontext()
    global_context.prec = 7
    global_context.rounding = ROUND_DOWN
    global_context.Emin = -9
    global_context.Emax = 9
    global_context.traps[Underflow] = True
    try:
        disturbed = expected_information_gain_bits(model, (1, 10**100), "gcd")
        rendered = format_information_gain_bits(disturbed)
    finally:
        setcontext(original_context)

    assert disturbed == baseline
    assert rendered == format(baseline, ".30f")


def test_score_format_is_half_even_fixed_width_and_normalizes_negative_zero() -> None:
    assert format_information_gain_bits(Decimal("0.1234567890123456789012345678904")) == (
        "0.123456789012345678901234567890"
    )
    assert format_information_gain_bits(Decimal("0.1234567890123456789012345678906")) == (
        "0.123456789012345678901234567891"
    )
    assert format_information_gain_bits(Decimal("-0")) == "0.000000000000000000000000000000"


def test_belief_lineage_copies_sequences_and_has_closed_payload() -> None:
    before = [2, 3]
    after = [6, 1]
    before_fingerprint = information_gain_belief_fingerprint(("h0", "h1"), before)
    after_fingerprint = information_gain_belief_fingerprint(("h0", "h1"), after)
    lineage = InformationGainBeliefLineage(
        step_index=0,
        candidate_id="gcd",
        outcome_id="left",
        weights_before=before,  # type: ignore[arg-type]
        weights_after=after,  # type: ignore[arg-type]
        belief_fingerprint_before=before_fingerprint,
        belief_fingerprint_after=after_fingerprint,
    )
    before[0] = 999
    after[0] = 999

    assert lineage.weights_before == (2, 3)
    assert lineage.weights_after == (6, 1)
    assert lineage.to_payload() == {
        "step_index": 0,
        "candidate_id": "gcd",
        "outcome_id": "left",
        "weights_before": [2, 3],
        "weights_after": [6, 1],
        "belief_fingerprint_before": before_fingerprint,
        "belief_fingerprint_after": after_fingerprint,
    }


def _information_gain_run_spec() -> RunSpecV3:
    model = FiniteTableEvidenceModel(
        hypothesis_ids=("h0", "h1"),
        prior_weight_by_hypothesis={"h0": 1, "h1": 1},
        observation_metric="metric",
        outcome_ids=("left", "right"),
        outcome_thresholds=(0.0,),
        likelihood_row_total=2,
        likelihood_weight_by_candidate_id={
            candidate_id: {
                "h0": {"left": 2, "right": 0},
                "h1": {"left": 0, "right": 2},
            }
            for candidate_id in ("c0", "c1")
        },
    )
    return RunSpecV3(
        candidates=(CandidateSpec("c0", {}), CandidateSpec("c1", {})),
        policy_id="information_gain_table",
        policy_config={
            "evidence_model": model.to_payload(),
            "tie_break": "runspec_candidate_order",
        },
        policy_seed=None,
        experiment_count_budget=2,
        adapter_id="test-adapter",
        adapter_version="test-adapter/v1",
        objective_name="metric",
        objective_direction="maximize",
    )


def test_table_policy_uses_exact_score_and_runspec_order_tie_break() -> None:
    policy = TableInformationGainPolicy(_information_gain_run_spec())
    details = policy.selection_details([])

    assert details.candidate.candidate_id == "c0"
    assert details.eligible_candidate_ids == ("c0", "c1")
    assert details.selected_information_gain_bits == "1.000000000000000000000000000000"
    assert dict(details.selection_metadata()) == {
        "policy_identity": "information_gain_table",
        "selected_candidate_id": "c0",
        "selected_information_gain_bits": "1.000000000000000000000000000000",
        "eligible_candidate_count": 2,
        "current_belief_fingerprint": details.current_belief_fingerprint,
        "evidence_model_fingerprint": details.evidence_model_fingerprint,
        "tie_break": "runspec_candidate_order",
    }


def test_table_policy_replays_history_and_returns_exact_lineage_for_new_observation() -> None:
    run_spec = _information_gain_run_spec()
    policy = TableInformationGainPolicy(run_spec)
    first = policy.selection_details([]).candidate
    record = CompletedWorkloadExperiment(
        run_spec_fingerprint=run_spec.fingerprint(),
        candidate=first,
        policy_id="information_gain_table",
        observation=NormalizedObservation(-1.0, 1.0),
        created_at="2026-08-04T00:00:00+00:00",
    )

    lineage = policy.lineage_for_observation([], record)
    resumed = policy.selection_details([record])

    assert lineage.step_index == 0
    assert lineage.candidate_id == "c0"
    assert lineage.outcome_id == "left"
    assert lineage.weights_before == (1, 1)
    assert lineage.weights_after == (1, 0)
    assert resumed.current_belief_weights == (1, 0)
    assert resumed.current_belief_fingerprint == lineage.belief_fingerprint_after
    assert resumed.candidate.candidate_id == "c1"
    assert resumed.selected_information_gain_bits == "0.000000000000000000000000000000"
