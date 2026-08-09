from __future__ import annotations

import tomllib
from importlib import metadata as importlib_metadata
from pathlib import Path

import pytest

import research_decision_engine
import research_decision_engine.generic_policies as generic_policies_module
import research_decision_engine.information_gain_table as information_gain_table_module
import research_decision_engine.policy_contracts as policy_contracts_module
import research_decision_engine.run_bundle_v2 as run_bundle_v2_module
import research_decision_engine.run_bundle_v3 as run_bundle_v3_module
import research_decision_engine.run_spec_v2 as run_spec_v2_module
import research_decision_engine.run_spec_v3 as run_spec_v3_module
import research_decision_engine.runner as runner_module
from research_decision_engine import (
    INFORMATION_GAIN_NUMERIC_CONTRACT,
    CandidateSpec,
    CommandAdapter,
    CommandAdapterError,
    CommandBuildError,
    CommandExitError,
    CommandInvocation,
    CommandOutputError,
    CommandTimeoutError,
    CompletedWorkloadExperiment,
    CompletedWorkloadRunTrace,
    CompletedWorkloadRunTraceV2,
    CompletedWorkloadRunTraceV3,
    DeterministicPolicySeedError,
    EmptyOrDuplicateHypothesisSetError,
    EvidenceModelDecodeError,
    EvidenceModelError,
    ExtraCandidateUtilityError,
    FiniteTableEvidenceModel,
    ImpossibleEvidenceError,
    InformationGainBeliefLineage,
    InformationGainContractError,
    InformationGainNumericContract,
    InvalidCandidateUtilityError,
    InvalidInformationGainBeliefError,
    InvalidLikelihoodWeightError,
    InvalidOutcomeSetError,
    InvalidPolicyTieBreakError,
    InvalidThresholdCountError,
    InvalidThresholdError,
    InvalidThresholdOrderError,
    LikelihoodCandidateKeyMismatchError,
    LikelihoodHypothesisKeyMismatchError,
    LikelihoodOutcomeKeyMismatchError,
    LikelihoodRowTotalMismatchError,
    MissingCandidateUtilityError,
    MissingObservationMetricError,
    NonfiniteObservationMetricError,
    NonfiniteUtilityError,
    NonpositivePriorWeightError,
    NormalizedObservation,
    ObservationMetricError,
    PolicyConfigurationError,
    PolicyContractError,
    PriorGreedyPolicy,
    PriorKeyMismatchError,
    PythonFunctionAdapter,
    ReplayBeliefMismatchError,
    ReplayDecisionMismatchError,
    ReplayInformationGainScoreMismatchError,
    ReplayPolicyUnavailableError,
    ReplayRationaleMismatchError,
    RunBundle,
    RunBundleError,
    RunBundleReplayError,
    RunBundleReplayResult,
    RunBundleStep,
    RunBundleStepV2,
    RunBundleStepV3,
    RunBundleV2,
    RunBundleV2Error,
    RunBundleV2ReplayError,
    RunBundleV2ReplayResult,
    RunBundleV2ValidationError,
    RunBundleV2VerificationError,
    RunBundleV2VerificationResult,
    RunBundleV3,
    RunBundleV3Error,
    RunBundleV3ReplayError,
    RunBundleV3ReplayResult,
    RunBundleV3ValidationError,
    RunBundleV3VerificationError,
    RunBundleV3VerificationResult,
    RunBundleValidationError,
    RunBundleVerificationError,
    RunBundleVerificationResult,
    RunBundleVersionMismatchError,
    RunSpec,
    RunSpecV2,
    RunSpecV3,
    RunSpecVersionMismatchError,
    TableInformationGainPolicy,
    UnsupportedInformationGainNumericContractError,
    UnsupportedPolicyForSchemaError,
    UnsupportedPolicyIdentityError,
    UnsupportedRunSpecSchemaError,
    WorkloadAdapter,
    WorkloadAdapterError,
    export_run_bundle,
    export_run_bundle_v2,
    export_run_bundle_v3,
    policy_contract_for_schema,
    policy_identity_contract,
    replay_run_bundle,
    replay_run_bundle_v2,
    replay_run_bundle_v3,
    resume_workload_trace,
    resume_workload_trace_v2,
    resume_workload_trace_v3,
    run_workload_experiment,
    run_workload_experiment_v2,
    run_workload_experiment_v3,
    run_workload_trace,
    run_workload_trace_v2,
    run_workload_trace_v3,
    supported_policy_identities,
    verify_run_bundle,
    verify_run_bundle_v2,
    verify_run_bundle_v3,
)

EXPECTED_ALL = [
    "CandidateSpec",
    "CommandAdapter",
    "CommandAdapterError",
    "CommandBuildError",
    "CommandExitError",
    "CommandInvocation",
    "CommandOutputError",
    "CommandTimeoutError",
    "CompletedWorkloadExperiment",
    "CompletedWorkloadRunTrace",
    "CompletedWorkloadRunTraceV2",
    "CompletedWorkloadRunTraceV3",
    "DeterministicPolicySeedError",
    "EmptyOrDuplicateHypothesisSetError",
    "EvidenceModelDecodeError",
    "EvidenceModelError",
    "ExtraCandidateUtilityError",
    "FiniteTableEvidenceModel",
    "INFORMATION_GAIN_NUMERIC_CONTRACT",
    "ImpossibleEvidenceError",
    "InformationGainBeliefLineage",
    "InformationGainContractError",
    "InformationGainNumericContract",
    "InvalidCandidateUtilityError",
    "InvalidInformationGainBeliefError",
    "InvalidLikelihoodWeightError",
    "InvalidOutcomeSetError",
    "InvalidPolicyTieBreakError",
    "InvalidThresholdCountError",
    "InvalidThresholdError",
    "InvalidThresholdOrderError",
    "LikelihoodCandidateKeyMismatchError",
    "LikelihoodHypothesisKeyMismatchError",
    "LikelihoodOutcomeKeyMismatchError",
    "LikelihoodRowTotalMismatchError",
    "MissingCandidateUtilityError",
    "MissingObservationMetricError",
    "NonfiniteObservationMetricError",
    "NonfiniteUtilityError",
    "NonpositivePriorWeightError",
    "NormalizedObservation",
    "ObservationMetricError",
    "PolicyConfigurationError",
    "PolicyContractError",
    "PriorGreedyPolicy",
    "PriorKeyMismatchError",
    "PythonFunctionAdapter",
    "ReplayBeliefMismatchError",
    "ReplayDecisionMismatchError",
    "ReplayInformationGainScoreMismatchError",
    "ReplayPolicyUnavailableError",
    "ReplayRationaleMismatchError",
    "RunBundle",
    "RunBundleError",
    "RunBundleReplayError",
    "RunBundleReplayResult",
    "RunBundleStep",
    "RunBundleStepV2",
    "RunBundleStepV3",
    "RunBundleV2",
    "RunBundleV2Error",
    "RunBundleV2ReplayError",
    "RunBundleV2ReplayResult",
    "RunBundleV2ValidationError",
    "RunBundleV2VerificationError",
    "RunBundleV2VerificationResult",
    "RunBundleV3",
    "RunBundleV3Error",
    "RunBundleV3ReplayError",
    "RunBundleV3ReplayResult",
    "RunBundleV3ValidationError",
    "RunBundleV3VerificationError",
    "RunBundleV3VerificationResult",
    "RunBundleValidationError",
    "RunBundleVerificationError",
    "RunBundleVerificationResult",
    "RunBundleVersionMismatchError",
    "RunSpec",
    "RunSpecV2",
    "RunSpecV3",
    "RunSpecVersionMismatchError",
    "TableInformationGainPolicy",
    "UnsupportedInformationGainNumericContractError",
    "UnsupportedPolicyForSchemaError",
    "UnsupportedPolicyIdentityError",
    "UnsupportedRunSpecSchemaError",
    "WorkloadAdapter",
    "WorkloadAdapterError",
    "__version__",
    "export_run_bundle",
    "export_run_bundle_v2",
    "export_run_bundle_v3",
    "policy_contract_for_schema",
    "policy_identity_contract",
    "replay_run_bundle",
    "replay_run_bundle_v2",
    "replay_run_bundle_v3",
    "resume_workload_trace",
    "resume_workload_trace_v2",
    "resume_workload_trace_v3",
    "run_workload_experiment",
    "run_workload_experiment_v2",
    "run_workload_experiment_v3",
    "run_workload_trace",
    "run_workload_trace_v2",
    "run_workload_trace_v3",
    "supported_policy_identities",
    "verify_run_bundle",
    "verify_run_bundle_v2",
    "verify_run_bundle_v3",
]

POLICY_ERROR_NAMES = (
    "DeterministicPolicySeedError",
    "ExtraCandidateUtilityError",
    "InvalidCandidateUtilityError",
    "InvalidPolicyTieBreakError",
    "MissingCandidateUtilityError",
    "NonfiniteUtilityError",
    "PolicyConfigurationError",
    "PolicyContractError",
    "ReplayDecisionMismatchError",
    "ReplayPolicyUnavailableError",
    "ReplayRationaleMismatchError",
    "RunBundleVersionMismatchError",
    "RunSpecVersionMismatchError",
    "UnsupportedPolicyForSchemaError",
    "UnsupportedPolicyIdentityError",
    "UnsupportedRunSpecSchemaError",
)

RUN_BUNDLE_V2_ERROR_NAMES = (
    "RunBundleV2Error",
    "RunBundleV2ReplayError",
    "RunBundleV2ValidationError",
    "RunBundleV2VerificationError",
)


def test_runspec_and_adapter_public_api_is_available_from_package_root() -> None:
    expected = {
        "CandidateSpec": CandidateSpec,
        "CommandAdapter": CommandAdapter,
        "CommandAdapterError": CommandAdapterError,
        "CommandBuildError": CommandBuildError,
        "CommandExitError": CommandExitError,
        "CommandInvocation": CommandInvocation,
        "CommandOutputError": CommandOutputError,
        "CommandTimeoutError": CommandTimeoutError,
        "CompletedWorkloadExperiment": CompletedWorkloadExperiment,
        "CompletedWorkloadRunTrace": CompletedWorkloadRunTrace,
        "CompletedWorkloadRunTraceV2": CompletedWorkloadRunTraceV2,
        "DeterministicPolicySeedError": DeterministicPolicySeedError,
        "ExtraCandidateUtilityError": ExtraCandidateUtilityError,
        "InvalidCandidateUtilityError": InvalidCandidateUtilityError,
        "InvalidPolicyTieBreakError": InvalidPolicyTieBreakError,
        "MissingCandidateUtilityError": MissingCandidateUtilityError,
        "NonfiniteUtilityError": NonfiniteUtilityError,
        "NormalizedObservation": NormalizedObservation,
        "PolicyConfigurationError": PolicyConfigurationError,
        "PolicyContractError": PolicyContractError,
        "PriorGreedyPolicy": PriorGreedyPolicy,
        "PythonFunctionAdapter": PythonFunctionAdapter,
        "ReplayDecisionMismatchError": ReplayDecisionMismatchError,
        "ReplayPolicyUnavailableError": ReplayPolicyUnavailableError,
        "ReplayRationaleMismatchError": ReplayRationaleMismatchError,
        "RunBundle": RunBundle,
        "RunBundleError": RunBundleError,
        "RunBundleReplayError": RunBundleReplayError,
        "RunBundleReplayResult": RunBundleReplayResult,
        "RunBundleStep": RunBundleStep,
        "RunBundleStepV2": RunBundleStepV2,
        "RunBundleV2": RunBundleV2,
        "RunBundleV2Error": RunBundleV2Error,
        "RunBundleV2ReplayError": RunBundleV2ReplayError,
        "RunBundleV2ReplayResult": RunBundleV2ReplayResult,
        "RunBundleV2ValidationError": RunBundleV2ValidationError,
        "RunBundleV2VerificationError": RunBundleV2VerificationError,
        "RunBundleV2VerificationResult": RunBundleV2VerificationResult,
        "RunBundleValidationError": RunBundleValidationError,
        "RunBundleVerificationError": RunBundleVerificationError,
        "RunBundleVerificationResult": RunBundleVerificationResult,
        "RunBundleVersionMismatchError": RunBundleVersionMismatchError,
        "RunSpec": RunSpec,
        "RunSpecV2": RunSpecV2,
        "RunSpecVersionMismatchError": RunSpecVersionMismatchError,
        "UnsupportedPolicyForSchemaError": UnsupportedPolicyForSchemaError,
        "UnsupportedPolicyIdentityError": UnsupportedPolicyIdentityError,
        "UnsupportedRunSpecSchemaError": UnsupportedRunSpecSchemaError,
        "WorkloadAdapter": WorkloadAdapter,
        "WorkloadAdapterError": WorkloadAdapterError,
        "export_run_bundle": export_run_bundle,
        "export_run_bundle_v2": export_run_bundle_v2,
        "policy_contract_for_schema": policy_contract_for_schema,
        "policy_identity_contract": policy_identity_contract,
        "replay_run_bundle": replay_run_bundle,
        "replay_run_bundle_v2": replay_run_bundle_v2,
        "resume_workload_trace": resume_workload_trace,
        "resume_workload_trace_v2": resume_workload_trace_v2,
        "run_workload_experiment": run_workload_experiment,
        "run_workload_experiment_v2": run_workload_experiment_v2,
        "run_workload_trace": run_workload_trace,
        "run_workload_trace_v2": run_workload_trace_v2,
        "supported_policy_identities": supported_policy_identities,
        "verify_run_bundle": verify_run_bundle,
        "verify_run_bundle_v2": verify_run_bundle_v2,
    }
    expected.update(
        {
            "CompletedWorkloadRunTraceV3": CompletedWorkloadRunTraceV3,
            "EmptyOrDuplicateHypothesisSetError": EmptyOrDuplicateHypothesisSetError,
            "EvidenceModelDecodeError": EvidenceModelDecodeError,
            "EvidenceModelError": EvidenceModelError,
            "FiniteTableEvidenceModel": FiniteTableEvidenceModel,
            "INFORMATION_GAIN_NUMERIC_CONTRACT": INFORMATION_GAIN_NUMERIC_CONTRACT,
            "ImpossibleEvidenceError": ImpossibleEvidenceError,
            "InformationGainBeliefLineage": InformationGainBeliefLineage,
            "InformationGainContractError": InformationGainContractError,
            "InformationGainNumericContract": InformationGainNumericContract,
            "InvalidInformationGainBeliefError": InvalidInformationGainBeliefError,
            "InvalidLikelihoodWeightError": InvalidLikelihoodWeightError,
            "InvalidOutcomeSetError": InvalidOutcomeSetError,
            "InvalidThresholdCountError": InvalidThresholdCountError,
            "InvalidThresholdError": InvalidThresholdError,
            "InvalidThresholdOrderError": InvalidThresholdOrderError,
            "LikelihoodCandidateKeyMismatchError": LikelihoodCandidateKeyMismatchError,
            "LikelihoodHypothesisKeyMismatchError": LikelihoodHypothesisKeyMismatchError,
            "LikelihoodOutcomeKeyMismatchError": LikelihoodOutcomeKeyMismatchError,
            "LikelihoodRowTotalMismatchError": LikelihoodRowTotalMismatchError,
            "MissingObservationMetricError": MissingObservationMetricError,
            "NonfiniteObservationMetricError": NonfiniteObservationMetricError,
            "NonpositivePriorWeightError": NonpositivePriorWeightError,
            "ObservationMetricError": ObservationMetricError,
            "PriorKeyMismatchError": PriorKeyMismatchError,
            "ReplayBeliefMismatchError": ReplayBeliefMismatchError,
            "ReplayInformationGainScoreMismatchError": ReplayInformationGainScoreMismatchError,
            "RunBundleStepV3": RunBundleStepV3,
            "RunBundleV3": RunBundleV3,
            "RunBundleV3Error": RunBundleV3Error,
            "RunBundleV3ReplayError": RunBundleV3ReplayError,
            "RunBundleV3ReplayResult": RunBundleV3ReplayResult,
            "RunBundleV3ValidationError": RunBundleV3ValidationError,
            "RunBundleV3VerificationError": RunBundleV3VerificationError,
            "RunBundleV3VerificationResult": RunBundleV3VerificationResult,
            "RunSpecV3": RunSpecV3,
            "TableInformationGainPolicy": TableInformationGainPolicy,
            "UnsupportedInformationGainNumericContractError": (
                UnsupportedInformationGainNumericContractError
            ),
            "export_run_bundle_v3": export_run_bundle_v3,
            "replay_run_bundle_v3": replay_run_bundle_v3,
            "resume_workload_trace_v3": resume_workload_trace_v3,
            "run_workload_experiment_v3": run_workload_experiment_v3,
            "run_workload_trace_v3": run_workload_trace_v3,
            "verify_run_bundle_v3": verify_run_bundle_v3,
        }
    )

    assert research_decision_engine.__all__ == EXPECTED_ALL == sorted(EXPECTED_ALL)
    assert all(getattr(research_decision_engine, name) is value for name, value in expected.items())
    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    project_version = pyproject["project"]["version"]
    distribution_version = importlib_metadata.version("research-decision-engine")
    assert "__version__" in research_decision_engine.__all__
    assert type(research_decision_engine.__version__) is str
    assert (
        research_decision_engine.__version__
        == project_version
        == distribution_version
        == "1.0.0rc5"
    )
    assert research_decision_engine.__file__ is not None
    assert Path(research_decision_engine.__file__).is_file()


def test_versioned_root_symbols_retain_exact_implementation_identities() -> None:
    assert PriorGreedyPolicy is generic_policies_module.PriorGreedyPolicy
    assert RunSpecV2 is run_spec_v2_module.RunSpecV2
    assert RunBundleStepV2 is run_bundle_v2_module.RunBundleStepV2
    assert CompletedWorkloadRunTraceV2 is run_bundle_v2_module.CompletedWorkloadRunTraceV2
    assert RunBundleV2 is run_bundle_v2_module.RunBundleV2
    assert RunBundleV2VerificationResult is run_bundle_v2_module.RunBundleV2VerificationResult
    assert RunBundleV2ReplayResult is run_bundle_v2_module.RunBundleV2ReplayResult
    assert export_run_bundle_v2 is run_bundle_v2_module.export_run_bundle_v2
    assert verify_run_bundle_v2 is run_bundle_v2_module.verify_run_bundle_v2
    assert replay_run_bundle_v2 is run_bundle_v2_module.replay_run_bundle_v2
    assert run_workload_experiment_v2 is runner_module.run_workload_experiment_v2
    assert run_workload_trace_v2 is runner_module.run_workload_trace_v2
    assert resume_workload_trace_v2 is runner_module.resume_workload_trace_v2
    assert FiniteTableEvidenceModel is information_gain_table_module.FiniteTableEvidenceModel
    assert TableInformationGainPolicy is information_gain_table_module.TableInformationGainPolicy
    assert RunSpecV3 is run_spec_v3_module.RunSpecV3
    assert RunBundleStepV3 is run_bundle_v3_module.RunBundleStepV3
    assert CompletedWorkloadRunTraceV3 is run_bundle_v3_module.CompletedWorkloadRunTraceV3
    assert RunBundleV3 is run_bundle_v3_module.RunBundleV3
    assert RunBundleV3VerificationResult is run_bundle_v3_module.RunBundleV3VerificationResult
    assert RunBundleV3ReplayResult is run_bundle_v3_module.RunBundleV3ReplayResult
    assert export_run_bundle_v3 is run_bundle_v3_module.export_run_bundle_v3
    assert verify_run_bundle_v3 is run_bundle_v3_module.verify_run_bundle_v3
    assert replay_run_bundle_v3 is run_bundle_v3_module.replay_run_bundle_v3
    assert run_workload_experiment_v3 is runner_module.run_workload_experiment_v3
    assert run_workload_trace_v3 is runner_module.run_workload_trace_v3
    assert resume_workload_trace_v3 is runner_module.resume_workload_trace_v3

    assert all(
        getattr(research_decision_engine, name) is getattr(policy_contracts_module, name)
        for name in POLICY_ERROR_NAMES
    )
    assert all(
        getattr(research_decision_engine, name) is getattr(run_bundle_v2_module, name)
        for name in RUN_BUNDLE_V2_ERROR_NAMES
    )
    assert all(
        issubclass(getattr(policy_contracts_module, name), PolicyContractError)
        for name in POLICY_ERROR_NAMES
        if name != "PolicyContractError"
    )
    assert all(
        issubclass(getattr(run_bundle_v2_module, name), RunBundleV2Error)
        for name in RUN_BUNDLE_V2_ERROR_NAMES
        if name != "RunBundleV2Error"
    )


def test_public_policy_introspection_is_exactly_versioned() -> None:
    v1 = policy_contract_for_schema("rde-core-run-spec/v1")
    v2 = policy_contract_for_schema("rde-core-run-spec/v2")
    v3 = policy_contract_for_schema("rde-core-run-spec/v3")

    assert supported_policy_identities(v1.run_spec_schema) == ("random",)
    assert supported_policy_identities(v2.run_spec_schema) == ("random", "greedy_prior")
    assert supported_policy_identities(v3.run_spec_schema) == (
        "random",
        "greedy_prior",
        "information_gain_table",
    )
    assert (
        v1.run_spec_schema,
        v1.run_bundle_schema,
        v1.replay_contract,
    ) == (
        "rde-core-run-spec/v1",
        "rde-core-run-bundle/v1",
        "RECORDED_OBSERVATION_DECISION_REPLAY_V1",
    )
    assert (
        v2.run_spec_schema,
        v2.run_bundle_schema,
        v2.replay_contract,
    ) == (
        "rde-core-run-spec/v2",
        "rde-core-run-bundle/v2",
        "RECORDED_OBSERVATION_DECISION_REPLAY_V2",
    )
    assert (
        v3.run_spec_schema,
        v3.run_bundle_schema,
        v3.replay_contract,
    ) == (
        "rde-core-run-spec/v3",
        "rde-core-run-bundle/v3",
        "RECORDED_OBSERVATION_DECISION_REPLAY_V3",
    )

    random_contract = policy_identity_contract(v2.run_spec_schema, "random")
    greedy_contract = policy_identity_contract(v2.run_spec_schema, "greedy_prior")
    information_gain_contract = policy_identity_contract(
        v3.run_spec_schema, "information_gain_table"
    )
    assert (
        random_contract.semantic_classification,
        random_contract.required_config_fields,
        random_contract.seed_requirement,
    ) == ("SEEDED_RANDOM_WITHOUT_REPLACEMENT", (), "required")
    assert (
        greedy_contract.semantic_classification,
        greedy_contract.required_config_fields,
        greedy_contract.seed_requirement,
    ) == (
        "STATIC_TRUTH_FREE_PRIOR_UTILITY_GREEDY",
        ("utility_by_candidate_id", "tie_break"),
        "forbidden",
    )
    assert (
        information_gain_contract.semantic_classification,
        information_gain_contract.required_config_fields,
        information_gain_contract.seed_requirement,
    ) == (
        "USER_DECLARED_FINITE_HYPOTHESIS_OUTCOME_LIKELIHOOD_TABLE",
        ("evidence_model", "tie_break"),
        "forbidden",
    )
    assert INFORMATION_GAIN_NUMERIC_CONTRACT.to_payload() == {
        "implementation": "decimal.Decimal",
        "precision": 50,
        "rounding": "ROUND_HALF_EVEN",
        "logarithm": "Decimal.ln",
        "base_conversion": "divide_by_Decimal_2_ln",
        "score_quantum": "1e-30",
    }

    with pytest.raises(UnsupportedPolicyForSchemaError):
        policy_identity_contract(v1.run_spec_schema, "greedy_prior")
    with pytest.raises(UnsupportedPolicyForSchemaError):
        policy_identity_contract(v1.run_spec_schema, "information_gain_table")
    with pytest.raises(UnsupportedPolicyForSchemaError):
        policy_identity_contract(v2.run_spec_schema, "information_gain_table")


if __name__ == "__main__":
    test_runspec_and_adapter_public_api_is_available_from_package_root()
    test_versioned_root_symbols_retain_exact_implementation_identities()
    test_public_policy_introspection_is_exactly_versioned()
    print(f"PUBLIC_API_IMPORT_OK={Path(research_decision_engine.__file__).resolve()}")
