from __future__ import annotations

from copy import deepcopy

import pytest

from research_decision_engine.information_gain_table import (
    EmptyOrDuplicateHypothesisSetError,
    EvidenceModelDecodeError,
    FiniteTableEvidenceModel,
    InvalidLikelihoodWeightError,
    InvalidOutcomeSetError,
    InvalidThresholdCountError,
    InvalidThresholdOrderError,
    LikelihoodCandidateKeyMismatchError,
    LikelihoodHypothesisKeyMismatchError,
    LikelihoodOutcomeKeyMismatchError,
    LikelihoodRowTotalMismatchError,
    MissingObservationMetricError,
    NonfiniteObservationMetricError,
    NonpositivePriorWeightError,
    ObservationMetricError,
    PriorKeyMismatchError,
)


def _model_inputs() -> dict[str, object]:
    return {
        "hypothesis_ids": ["h0", "h1"],
        "prior_weight_by_hypothesis": {"h0": 1, "h1": 2},
        "observation_metric": "metric",
        "outcome_ids": ["low", "medium", "high"],
        "outcome_thresholds": [1.0, 2.0],
        "likelihood_row_total": 10,
        "likelihood_weight_by_candidate_id": {
            "c0": {
                "h0": {"low": 1, "medium": 3, "high": 6},
                "h1": {"low": 5, "medium": 4, "high": 1},
            },
            "c1": {
                "h0": {"low": 4, "medium": 4, "high": 2},
                "h1": {"low": 2, "medium": 4, "high": 4},
            },
        },
    }


def _model() -> FiniteTableEvidenceModel:
    return FiniteTableEvidenceModel(**_model_inputs())  # type: ignore[arg-type]


def test_valid_construction_is_immutable_and_caller_mutation_isolated() -> None:
    inputs = _model_inputs()
    model = FiniteTableEvidenceModel(**inputs)  # type: ignore[arg-type]
    priors = inputs["prior_weight_by_hypothesis"]
    likelihoods = inputs["likelihood_weight_by_candidate_id"]
    assert isinstance(priors, dict)
    assert isinstance(likelihoods, dict)
    priors["h0"] = 999
    likelihoods["c0"]["h0"]["low"] = 999

    assert model.prior_weight_by_hypothesis["h0"] == 1
    assert model.likelihood_weight("c0", "h0", "low") == 1
    with pytest.raises(TypeError):
        model.prior_weight_by_hypothesis["h0"] = 8  # type: ignore[index]
    with pytest.raises(TypeError):
        model.likelihood_weight_by_candidate_id["c0"]["h0"]["low"] = 8  # type: ignore[index]


def test_payload_has_exact_seven_semantic_fields_and_round_trips_canonically() -> None:
    model = _model()
    payload = model.to_payload()

    assert frozenset(payload) == frozenset(
        {
            "hypothesis_ids",
            "prior_weight_by_hypothesis",
            "observation_metric",
            "outcome_ids",
            "outcome_thresholds",
            "likelihood_row_total",
            "likelihood_weight_by_candidate_id",
        }
    )
    encoded = model.to_canonical_bytes()
    assert encoded.endswith(b"\n") and not encoded.endswith(b"\n\n")
    assert FiniteTableEvidenceModel.from_payload(payload) == model
    assert FiniteTableEvidenceModel.from_canonical_bytes(encoded) == model
    assert (
        FiniteTableEvidenceModel.from_canonical_bytes(encoded).fingerprint() == model.fingerprint()
    )
    assert len(model.fingerprint()) == 64


def test_canonical_decoder_rejects_noncanonical_unknown_and_duplicate_content() -> None:
    model = _model()
    with pytest.raises(EvidenceModelDecodeError, match="not canonical"):
        FiniteTableEvidenceModel.from_canonical_bytes(
            model.to_canonical_bytes().replace(b'"h0":1', b'"h0": 1')
        )
    payload = model.to_payload()
    payload["unknown"] = None
    with pytest.raises(EvidenceModelDecodeError, match="exactly"):
        FiniteTableEvidenceModel.from_payload(payload)
    with pytest.raises(EvidenceModelDecodeError, match="invalid JSON"):
        FiniteTableEvidenceModel.from_canonical_bytes(b'{"x":1,"x":2}\n')


@pytest.mark.parametrize("hypotheses", [[], ["h0", "h0"], ["h0", ""]])
def test_invalid_hypothesis_sets_are_rejected(hypotheses: list[str]) -> None:
    inputs = _model_inputs()
    inputs["hypothesis_ids"] = hypotheses
    with pytest.raises(EmptyOrDuplicateHypothesisSetError):
        FiniteTableEvidenceModel(**inputs)  # type: ignore[arg-type]


def test_prior_contract_is_exact_and_supports_more_than_signed_64_bits() -> None:
    inputs = _model_inputs()
    inputs["prior_weight_by_hypothesis"] = {"h0": 2**100, "h1": 1}
    model = FiniteTableEvidenceModel(**inputs)  # type: ignore[arg-type]
    assert model.prior_weight_by_hypothesis["h0"] == 2**100

    for invalid in (0, -1, True):
        changed = _model_inputs()
        changed["prior_weight_by_hypothesis"] = {"h0": invalid, "h1": 1}
        with pytest.raises(NonpositivePriorWeightError):
            FiniteTableEvidenceModel(**changed)  # type: ignore[arg-type]

    changed = _model_inputs()
    changed["prior_weight_by_hypothesis"] = {"h0": 1}
    with pytest.raises(PriorKeyMismatchError):
        FiniteTableEvidenceModel(**changed)  # type: ignore[arg-type]


@pytest.mark.parametrize("outcomes", [[], ["only"], ["low", "low"], ["low", ""]])
def test_invalid_outcome_sets_are_rejected(outcomes: list[str]) -> None:
    inputs = _model_inputs()
    inputs["outcome_ids"] = outcomes
    with pytest.raises(InvalidOutcomeSetError):
        FiniteTableEvidenceModel(**inputs)  # type: ignore[arg-type]


def test_threshold_count_and_strict_order_are_validated() -> None:
    inputs = _model_inputs()
    inputs["outcome_thresholds"] = [1.0]
    with pytest.raises(InvalidThresholdCountError):
        FiniteTableEvidenceModel(**inputs)  # type: ignore[arg-type]

    for thresholds in ([1.0, 1.0], [2.0, 1.0]):
        changed = _model_inputs()
        changed["outcome_thresholds"] = thresholds
        with pytest.raises(InvalidThresholdOrderError):
            FiniteTableEvidenceModel(**changed)  # type: ignore[arg-type]


def test_large_integer_thresholds_preserve_identity_and_exact_partition() -> None:
    lower_inputs = _model_inputs()
    higher_inputs = _model_inputs()
    lower_inputs["outcome_ids"] = ["low", "high"]
    higher_inputs["outcome_ids"] = ["low", "high"]
    lower_inputs["outcome_thresholds"] = [2**53]
    higher_inputs["outcome_thresholds"] = [2**53 + 1]
    for inputs in (lower_inputs, higher_inputs):
        likelihoods = inputs["likelihood_weight_by_candidate_id"]
        assert isinstance(likelihoods, dict)
        for hypothesis_map in likelihoods.values():
            for outcome_map in hypothesis_map.values():
                outcome_map.clear()
                outcome_map.update({"low": 4, "high": 6})

    lower = FiniteTableEvidenceModel(**lower_inputs)  # type: ignore[arg-type]
    higher = FiniteTableEvidenceModel(**higher_inputs)  # type: ignore[arg-type]

    assert lower.outcome_thresholds == (2**53,)
    assert higher.outcome_thresholds == (2**53 + 1,)
    assert lower.fingerprint() != higher.fingerprint()
    assert lower.classify_observation({"metric": 2**53}) == "high"
    assert higher.classify_observation({"metric": 2**53}) == "low"
    assert higher.classify_observation({"metric": 2**53 + 1}) == "high"


def test_likelihood_keys_weights_and_row_totals_are_closed() -> None:
    inputs = _model_inputs()
    likelihoods = deepcopy(inputs["likelihood_weight_by_candidate_id"])
    assert isinstance(likelihoods, dict)
    del likelihoods["c0"]["h1"]
    inputs["likelihood_weight_by_candidate_id"] = likelihoods
    with pytest.raises(LikelihoodHypothesisKeyMismatchError):
        FiniteTableEvidenceModel(**inputs)  # type: ignore[arg-type]

    inputs = _model_inputs()
    likelihoods = deepcopy(inputs["likelihood_weight_by_candidate_id"])
    del likelihoods["c0"]["h0"]["high"]  # type: ignore[index]
    inputs["likelihood_weight_by_candidate_id"] = likelihoods
    with pytest.raises(LikelihoodOutcomeKeyMismatchError):
        FiniteTableEvidenceModel(**inputs)  # type: ignore[arg-type]

    for invalid in (-1, True):
        inputs = _model_inputs()
        likelihoods = deepcopy(inputs["likelihood_weight_by_candidate_id"])
        likelihoods["c0"]["h0"]["low"] = invalid  # type: ignore[index]
        inputs["likelihood_weight_by_candidate_id"] = likelihoods
        with pytest.raises(InvalidLikelihoodWeightError):
            FiniteTableEvidenceModel(**inputs)  # type: ignore[arg-type]

    inputs = _model_inputs()
    likelihoods = deepcopy(inputs["likelihood_weight_by_candidate_id"])
    likelihoods["c0"]["h0"]["low"] = 2  # type: ignore[index]
    inputs["likelihood_weight_by_candidate_id"] = likelihoods
    with pytest.raises(LikelihoodRowTotalMismatchError):
        FiniteTableEvidenceModel(**inputs)  # type: ignore[arg-type]


def test_candidate_coverage_is_checked_against_exact_runspec_ids() -> None:
    model = _model()
    model.validate_candidate_ids(["c0", "c1"])
    with pytest.raises(LikelihoodCandidateKeyMismatchError):
        model.validate_candidate_ids(["c0"])
    with pytest.raises(LikelihoodCandidateKeyMismatchError):
        model.validate_candidate_ids(["c0", "c1", "extra"])


@pytest.mark.parametrize(
    ("value", "outcome"),
    [
        (0.5, "low"),
        (1.0, "medium"),
        (1.5, "medium"),
        (2.0, "high"),
        (5.0, "high"),
    ],
)
def test_outcome_classification_has_exact_half_open_boundaries(value: float, outcome: str) -> None:
    assert _model().classify_observation({"metric": value}) == outcome


def test_observation_classification_fails_closed() -> None:
    model = _model()
    with pytest.raises(MissingObservationMetricError):
        model.classify_observation({"other": 1.0})
    with pytest.raises(ObservationMetricError, match="exactly"):
        model.classify_observation({"metric": 1.0, "other": 2.0})
    for invalid in (True, float("nan"), float("inf"), -float("inf")):
        with pytest.raises(NonfiniteObservationMetricError):
            model.classify_observation({"metric": invalid})


def test_evidence_model_has_no_hidden_truth_or_callable_surface() -> None:
    model = _model()
    encoded = model.to_canonical_bytes().lower()
    assert b"true_value" not in encoded
    assert b"hidden_truth" not in encoded
    assert b"callable" not in encoded
