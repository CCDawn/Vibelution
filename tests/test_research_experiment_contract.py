from copy import deepcopy

import pytest

from core.research import experiment_contract


def _legacy_model_plan():
    return {
        "dataset": "FashionMNIST pinned split",
        "metric": "test_accuracy",
        "baseline": "standard backprop model",
        "smokePlan": "run one bounded batch",
    }


def test_method_registry_separates_experiment_methods_from_evidence_and_preflight():
    methods = experiment_contract.list_experiment_methods()
    method_ids = {item["methodId"] for item in methods}
    research_mode_ids = {item["modeId"] for item in experiment_contract.list_research_modes()}
    purpose_ids = {item["purposeId"] for item in experiment_contract.list_experiment_purposes()}

    assert method_ids == {
        "model_training_inference",
        "dataset_analysis_benchmark",
        "numerical_simulation",
        "statistical_causal_test",
        "theoretical_symbolic_validation",
        "external_instrument_experiment",
    }
    assert "deep_research_review" not in method_ids
    assert "environment_probe" not in method_ids
    assert research_mode_ids == set(experiment_contract.RESEARCH_MODES)
    assert purpose_ids == set(experiment_contract.EXPERIMENT_PURPOSES)


def test_legacy_algorithm_plan_migrates_without_inventing_missing_execution_fields_or_full_run_adapter():
    contract = experiment_contract.build_experiment_contract(
        plan_id="exp-plan-1",
        team_id="research-team",
        research_question="Does predictive coding improve the declared benchmark?",
        payload={"researchMode": "full_research_loop"},
        legacy_plan=_legacy_model_plan(),
        hypothesis_refs=["hypothesis-1"],
        evidence_refs=["paper-note-1"],
    )

    assert contract["schemaVersion"] == 2
    assert contract["researchMode"] == "full_research_loop"
    assert contract["purpose"]["primaryPurpose"] == "baseline_comparison"
    assert contract["experimentMethod"] == "model_training_inference"
    assert contract["methodConfig"]["dataset"] == "FashionMNIST pinned split"
    assert contract["metricContract"]["primaryMetric"] == "test_accuracy"
    assert contract["adapterSelection"]["selectionSource"] == "unresolved"
    assert contract["adapterSelection"]["resolvedAdapterId"] == ""
    assert "full_run" in contract["adapterSelection"]["unavailableReason"]
    validation = experiment_contract.validate_experiment_contract(contract)
    assert validation["valid"] is False
    assert validation["missingFields"] == [
        "decisionContract.failureCriteria",
        "decisionContract.inconclusiveCriteria",
        "decisionContract.successCriteria",
        "methodConfig.budget",
        "methodConfig.model",
        "methodConfig.seeds",
    ]
    assert validation["readyForExecution"] is False


def test_simulation_contract_requires_method_specific_fields():
    payload = {
        "researchProfileId": "generic-simulation",
        "researchMode": "experiment_feedback",
        "experimentPurpose": {"primaryPurpose": "robustness", "secondaryPurposes": []},
        "experimentMethod": "numerical_simulation",
        "methodConfig": {
            "simulator": "controllable-agent-simulator",
            "scenario": "resource-constrained adaptation",
            "parameters": {"temperature": [0.1, 0.5, 1.0]},
            "replicates": 5,
        },
        "metricContract": {
            "primaryMetric": "task_success_rate",
            "metrics": [{"name": "task_success_rate", "direction": "maximize"}],
        },
        "decisionContract": {
            "successCriteria": ["task success remains above the reviewed threshold across scenarios"],
            "failureCriteria": ["task success falls below the reviewed failure threshold"],
            "inconclusiveCriteria": ["replicate variance prevents a stable comparison"],
        },
    }
    contract = experiment_contract.build_experiment_contract(
        plan_id="exp-plan-sim-1",
        team_id="research-team",
        research_question="How robust is the policy under scenario changes?",
        payload=payload,
        legacy_plan={},
        hypothesis_refs=["hypothesis-sim-1"],
        evidence_refs=[],
    )

    assert contract["experimentMethod"] == "numerical_simulation"
    assert contract["methodConfig"]["replicates"] == 5
    assert experiment_contract.validate_experiment_contract(contract)["valid"] is True

    invalid = deepcopy(contract)
    del invalid["methodConfig"]["scenario"]
    with pytest.raises(experiment_contract.ExperimentContractError, match="scenario"):
        experiment_contract.require_valid_experiment_contract(invalid)


def test_smoke_only_adapter_cannot_satisfy_full_research_loop():
    plan_only = experiment_contract.resolve_adapter_selection(
        "model_training_inference",
        "hypothesis_and_plan",
        requested_adapter_id="synthetic_classification_baseline_vs_variant",
    )
    full_loop = experiment_contract.resolve_adapter_selection(
        "model_training_inference",
        "full_research_loop",
        requested_adapter_id="synthetic_classification_baseline_vs_variant",
    )

    assert plan_only["resolvedAdapterId"] == "synthetic_classification_baseline_vs_variant"
    assert plan_only["selectionSource"] == "user_override"
    assert full_loop["resolvedAdapterId"] == ""
    assert "full_run" in full_loop["unavailableReason"]


def test_explicit_fashion_mnist_multi_seed_adapter_can_satisfy_full_research_loop_without_becoming_a_default():
    default_full_loop = experiment_contract.resolve_adapter_selection(
        "model_training_inference",
        "full_research_loop",
    )
    explicit_full_loop = experiment_contract.resolve_adapter_selection(
        "model_training_inference",
        "full_research_loop",
        requested_adapter_id="fashion_mnist_predictive_coding_multi_seed",
    )

    assert default_full_loop["resolvedAdapterId"] == ""
    assert explicit_full_loop["resolvedAdapterId"] == "fashion_mnist_predictive_coding_multi_seed"
    assert explicit_full_loop["selectionSource"] == "user_override"


def test_legacy_plan_record_projection_is_idempotent_and_preserves_legacy_fields():
    legacy = {
        "schemaVersion": 1,
        "planId": "exp-plan-legacy",
        "teamId": "research-team",
        "topic": "legacy routing experiment",
        "goal": "compare a routing candidate",
        "hypothesisCandidateIds": ["hypothesis-legacy"],
        "experimentPlan": _legacy_model_plan(),
        "status": "draft",
    }

    migrated = experiment_contract.migrate_legacy_plan_record(legacy)
    migrated_again = experiment_contract.migrate_legacy_plan_record(migrated)

    assert migrated["experimentPlan"] == legacy["experimentPlan"]
    assert migrated["experimentContract"]["schemaVersion"] == 2
    assert migrated["contractMigration"]["status"] == "projected_from_v1"
    assert migrated_again == migrated

    smoke_passed = deepcopy(legacy)
    smoke_passed["status"] = "smoke_passed"
    assert experiment_contract.migrate_legacy_plan_record(smoke_passed)["experimentContract"]["status"] == "ready_for_full_run"
