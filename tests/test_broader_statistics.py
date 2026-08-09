from __future__ import annotations

import itertools

import pytest

from research_decision_engine.benchmarks.broader_conformance import (
    DiagnosticConformanceFixture,
)
from research_decision_engine.benchmarks.broader_protocol import load_protocol_snapshot
from research_decision_engine.benchmarks.broader_statistics import (
    FORMULA_EXECUTORS,
    GATE_EXECUTORS,
    ActionTuple,
    ContrastInference,
    DecisionBoolean,
    GateStatus,
    HolmInput,
    OutcomeRow,
    PairedProbabilityRow,
    VetoResult,
    assert_executor_completeness,
    b_authorized,
    bootstrap_10000,
    bootstrap_seed,
    bootstrap_seed_ids,
    execute_formula,
    execute_formula_traced,
    execute_gate,
    expected_calibration_error,
    f_cal,
    f_concentration,
    f_dominance,
    f_hard_safety,
    f_veto,
    final_decision,
    holm_64,
    miss_action25,
    miss_divergent20,
    miss_dominance30,
    miss_mechanism20,
    miss_sequence30,
    miss_two_rates20,
    num_help_hurt,
    partition_action_tuples,
    sign_flip_seed,
    sign_flip_vector,
    signflip_10000,
    three_valued_and,
    three_valued_or,
    unique_actionable_mechanism,
)


def test_all_two_operand_three_valued_truth_table_rows() -> None:
    statuses = tuple(GateStatus)
    for left, right in itertools.product(statuses, repeat=2):
        expected_and = (
            GateStatus.FAIL
            if GateStatus.FAIL in {left, right}
            else GateStatus.PASS
            if left is right is GateStatus.PASS
            else GateStatus.INCONCLUSIVE
        )
        expected_or = (
            GateStatus.PASS
            if GateStatus.PASS in {left, right}
            else GateStatus.FAIL
            if left is right is GateStatus.FAIL
            else GateStatus.INCONCLUSIVE
        )
        assert three_valued_and((left, right)) is expected_and
        assert three_valued_or((left, right)) is expected_or


def test_inconclusive_veto_cannot_be_masked_by_empty_p() -> None:
    item = ActionTuple("IG", "SCORE_FLATTENING", "BR-J001", "BR-C023")
    partition = partition_action_tuples((item,), (VetoResult(item, "INCONCLUSIVE"),))
    unique = unique_actionable_mechanism(partition)
    authorization = b_authorized(
        controller_change_needed=DecisionBoolean.from_status(GateStatus.PASS),
        actionability_complete=DecisionBoolean.from_status(GateStatus.PASS),
        partition=partition,
        unique_mechanism=unique,
    )
    assert partition.surviving_tuples == ()
    assert partition.veto_complete.status is GateStatus.INCONCLUSIVE
    assert unique.status is GateStatus.INCONCLUSIVE
    assert authorization.status is GateStatus.INCONCLUSIVE


@pytest.mark.parametrize(
    ("b_status", "veto_status", "change_status", "ppo_status", "branch"),
    (
        (GateStatus.PASS, GateStatus.PASS, GateStatus.PASS, GateStatus.FAIL, "BRANCH-B"),
        (GateStatus.FAIL, GateStatus.PASS, GateStatus.PASS, GateStatus.FAIL, "BRANCH-C"),
        (
            GateStatus.INCONCLUSIVE,
            GateStatus.INCONCLUSIVE,
            GateStatus.PASS,
            GateStatus.FAIL,
            "BRANCH-C",
        ),
        (GateStatus.FAIL, GateStatus.PASS, GateStatus.FAIL, GateStatus.PASS, "BRANCH-D"),
        (GateStatus.FAIL, GateStatus.PASS, GateStatus.FAIL, GateStatus.FAIL, "BRANCH-A"),
    ),
)
def test_every_final_decision_branch(
    b_status: GateStatus,
    veto_status: GateStatus,
    change_status: GateStatus,
    ppo_status: GateStatus,
    branch: str,
) -> None:
    result = final_decision(
        g_b_authorization=b_status,
        b_authorization=DecisionBoolean.from_status(b_status),
        veto_complete=DecisionBoolean.from_status(veto_status),
        controller_change_needed=DecisionBoolean.from_status(change_status),
        ppo_eligible=DecisionBoolean.from_status(ppo_status),
    )
    assert result.branch_id == branch
    assert result.gate_status is GateStatus.PASS


def test_independent_g_b_authorization_mismatch_fails_final_gate() -> None:
    result = final_decision(
        g_b_authorization=GateStatus.FAIL,
        b_authorization=DecisionBoolean.from_status(GateStatus.PASS),
        veto_complete=DecisionBoolean.from_status(GateStatus.PASS),
        controller_change_needed=DecisionBoolean.from_status(GateStatus.PASS),
        ppo_eligible=DecisionBoolean.from_status(GateStatus.FAIL),
    )
    assert result.branch_id != "BRANCH-B"
    assert result.gate_status is GateStatus.FAIL


def test_every_formula_gate_estimand_and_contrast_has_one_executor() -> None:
    assert_executor_completeness()


def test_all_43_formulas_and_44_gates_execute_real_production_operands(
    diagnostic_conformance_fixture: DiagnosticConformanceFixture,
) -> None:
    samples = _production_formula_operands(diagnostic_conformance_fixture)
    assert set(samples) == set(FORMULA_EXECUTORS)
    assert len(samples) == 43
    assert len(GATE_EXECUTORS) == 44
    for formula_id, operands in samples.items():
        execution = execute_formula_traced(formula_id, operands)
        assert execution.output is not None
        assert execution.trace.ordered_operand_ids == tuple(operands)
        assert tuple(item[0] for item in execution.trace.operand_values) == tuple(operands)
    for gate_id, executor in GATE_EXECUTORS.items():
        assert execute_gate(gate_id, samples[executor.formula_id]) is not None
    assert execute_formula("NUM-HARM-PRESENT-ABSENT", samples["NUM-HARM-PRESENT-ABSENT"]) == 0.0


def test_formula_contract_rejects_missing_unknown_and_wrong_order(
    diagnostic_conformance_fixture: DiagnosticConformanceFixture,
) -> None:
    formula_id = "F-CORE"
    sample = _production_formula_operands(diagnostic_conformance_fixture)[formula_id]
    missing = dict(sample)
    missing.pop(next(iter(missing)))
    with pytest.raises(KeyError, match="operand contract differs"):
        execute_formula(formula_id, missing)
    unknown = {**sample, "UNDECLARED": True}
    with pytest.raises(KeyError, match="operand contract differs"):
        execute_formula(formula_id, unknown)
    reversed_sample = dict(reversed(tuple(sample.items())))
    with pytest.raises(ValueError, match="frozen order"):
        execute_formula(formula_id, reversed_sample)


def test_semantic_completeness_rejects_executor_that_ignores_operand(
    monkeypatch: pytest.MonkeyPatch,
    diagnostic_conformance_fixture: DiagnosticConformanceFixture,
) -> None:
    def ignores_everything(_: object) -> GateStatus:
        return GateStatus.PASS

    monkeypatch.setitem(FORMULA_EXECUTORS, "F-CORE", ignores_everything)
    with pytest.raises(RuntimeError, match="ignored frozen operands"):
        execute_formula(
            "F-CORE",
            _production_formula_operands(diagnostic_conformance_fixture)["F-CORE"],
        )


def test_weighted_and_missingness_formulas_use_frozen_boundaries() -> None:
    assert num_help_hurt(("helped", "hurt", "mixed"), (0.4, 0.1, 0.5)) == pytest.approx(0.3)
    assert miss_divergent20(n_helped=20, n_hurt=20, weighted_denominator=1.0) is GateStatus.PASS
    assert (
        miss_divergent20(n_helped=19, n_hurt=20, weighted_denominator=1.0)
        is GateStatus.INCONCLUSIVE
    )
    assert (
        miss_mechanism20(
            weighted_present_helped=0.1,
            weighted_present_hurt=0.2,
            weighted_absent_helped=0.3,
            weighted_absent_hurt=0.4,
            n_complete_seed_blocks=20,
        )
        is GateStatus.PASS
    )
    assert expected_calibration_error((0.8, 0.2), (True, False), (0.5, 0.5)) == pytest.approx(0.2)
    assert (
        miss_two_rates20(
            weighted_target_denominator=1.0,
            weighted_comparator_denominator=1.0,
            n_target_divergent_raw=20,
            n_comparator_divergent_raw=20,
        )
        is GateStatus.PASS
    )
    assert (
        miss_sequence30(
            weighted_present_denominator=1.0,
            weighted_absent_denominator=1.0,
            n_present_raw=30,
            n_absent_raw=30,
        )
        is GateStatus.PASS
    )
    assert (
        miss_dominance30(weighted_classifiable_denominator=1.0, n_classifiable_raw=30)
        is GateStatus.PASS
    )
    assert (
        miss_action25(
            weighted_present_denominator=1.0,
            weighted_absent_denominator=1.0,
            n_present_raw=25,
            n_absent_raw=25,
            block_support_counts=((20, 5, 5),) * 4 + ((19, 5, 5),),
        )
        is GateStatus.PASS
    )


def test_frozen_gate_boundaries_and_veto() -> None:
    favorable = ContrastInference(-0.10, -0.20, -0.01, 0.01, "ESTIMATED")
    assert (
        f_cal(
            nll=favorable,
            brier=favorable,
            ece=favorable,
            confidently_wrong=ContrastInference(-0.05, -0.10, -0.01, 0.01, "ESTIMATED"),
            true_probability=ContrastInference(0.0, -0.02, 0.01, 0.5, "ESTIMATED"),
        )
        is GateStatus.PASS
    )
    assert (
        f_hard_safety((ContrastInference(0.05, 0.01, 0.10, 0.01, "ESTIMATED"),)) is GateStatus.PASS
    )
    assert (
        f_concentration(
            target_count=20,
            comparator_count=20,
            contrast=ContrastInference(0.10, 0.01, 0.20, 0.01, "ESTIMATED"),
        )
        is GateStatus.PASS
    )
    assert (
        f_dominance(
            classifiable_count=30,
            combined_share=0.70,
            ci_low=0.60,
            score_flattening_share=0.10,
            group_sigma_reordering_share=0.10,
        )
        is GateStatus.PASS
    )
    assert (
        f_veto(
            own_effect=0.2,
            other_effect=-0.15,
            other_ci_low=-0.2,
            other_ci_high=-0.01,
            other_holm_p=0.01,
            support_resolved=True,
        )
        == "VETOED"
    )


def test_resampling_seed_streams_and_small_execution_are_deterministic() -> None:
    assert bootstrap_seed("BR-C001", 0) == bootstrap_seed("BR-C001", 0)
    assert sign_flip_seed("BR-C001", 0) == sign_flip_seed("BR-C001", 0)
    assert len(bootstrap_seed_ids("BR-C001", 0)) == 128
    assert len(sign_flip_vector("BR-C001", 0)) == 128
    assert bootstrap_seed_ids("BR-C001", 0) != bootstrap_seed_ids("BR-C001", 1)
    bootstrap = bootstrap_10000(
        "BR-C001", lambda sampled: sum(sampled) / len(sampled), replicates=20
    )
    assert bootstrap == bootstrap_10000(
        "BR-C001", lambda sampled: sum(sampled) / len(sampled), replicates=20
    )
    assert (
        signflip_10000("BR-C001", 0.0, lambda signs: float(sum(signs)), replicates=20).p_raw == 1.0
    )


def test_holm_keeps_all_64_members_and_preserves_inconclusive() -> None:
    ids = (
        load_protocol_snapshot().registry("statistical_hypothesis").ids("statistical_hypothesis_id")
    )
    results = holm_64(
        tuple(
            HolmInput(identifier, None if index == 0 else 0.01, index != 0)
            for index, identifier in enumerate(ids)
        )
    )
    assert len(results) == 64
    assert results[0].result_status == "INCONCLUSIVE"
    assert results[0].p_raw is None
    assert results[0].p_adjusted is None
    assert {item.holm_rank for item in results} == set(range(1, 65))
    with pytest.raises(ValueError, match="exact 64-member"):
        holm_64(tuple(reversed(tuple(HolmInput(item, 0.5, True) for item in ids))))
    with pytest.raises(ValueError, match="outside the frozen"):
        bootstrap_seed("BR-C999", 0)
    with pytest.raises(ValueError, match="outside the frozen"):
        sign_flip_seed("BR-C067", 0)


def _production_formula_operands(
    fixture: DiagnosticConformanceFixture,
) -> dict[str, dict[str, object]]:
    samples: dict[str, dict[str, object]] = {}
    for trace in fixture.analysis.formula_traces:
        samples.setdefault(
            trace.formula_id,
            {operand_id: value for operand_id, value, _ in trace.operand_values},
        )
    samples["NUM-ECE"] = {
        "paired_probability_rows": (
            PairedProbabilityRow("comparison", 1000, 1.0, 0.7, True, 0.8, True),
        ),
        "ece_bin_edges": tuple(index / 10.0 for index in range(11)),
        "seed_block_weights": {1000: 1.0},
    }
    samples["NUM-HARM-PRESENT-ABSENT"] = {
        "mechanism_present_rows": (
            OutcomeRow("present-helped", 1000, 1.0, "helped", True),
            OutcomeRow("present-hurt", 1001, 1.0, "hurt", True),
        ),
        "mechanism_absent_rows": (
            OutcomeRow("absent-helped", 1000, 1.0, "helped", True),
            OutcomeRow("absent-hurt", 1001, 1.0, "hurt", True),
        ),
        "seed_block_weights": {1000: 0.5, 1001: 0.5},
    }
    samples["MISS-ACTION25"] = {
        "weighted_present_denominator": 1.0,
        "weighted_absent_denominator": 1.0,
        "n_present_raw": 25,
        "n_absent_raw": 25,
        "five_block_support_counts": ((20, 5, 5),) * 5,
    }
    return samples
