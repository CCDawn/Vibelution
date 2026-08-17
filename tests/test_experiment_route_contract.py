"""Team workflow experiment read JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.team_workflows.experiment_models import (
    CandidateStoreListResponse,
    CandidateStoreValidationResponse,
    ChallengeQuestionRunStatusResponse,
    ExperimentMethodCatalogResponse,
    ExperimentPlanningStatusResponse,
    ExperimentRouteResponse,
)


def test_experiment_read_models_publish_known_schema_fields() -> None:
    expected_properties = {
        ExperimentPlanningStatusResponse: {
            "schemaVersion",
            "teamId",
            "status",
            "latestExperimentRound",
            "latestKnowledgeCollectionRound",
            "activePlan",
            "plans",
            "lifecycleProjection",
            "challengeProgramProjection",
            "hypothesisCandidates",
            "readyHypothesisCandidates",
            "gaps",
            "summary",
            "readiness",
            "boundaries",
            "storagePath",
            "nextActions",
            "updatedAt",
        },
        ExperimentMethodCatalogResponse: {
            "schemaVersion",
            "teamId",
            "researchModes",
            "experimentPurposes",
            "methods",
            "adapters",
            "boundaries",
        },
        ChallengeQuestionRunStatusResponse: {
            "teamId",
            "summary",
            "storePath",
        },
        CandidateStoreListResponse: {
            "teamId",
            "workflowId",
            "filters",
            "candidates",
            "candidateCount",
            "sourceFamilySummary",
            "validationSummary",
            "store",
        },
        CandidateStoreValidationResponse: {
            "schemaVersion",
            "teamId",
            "workflowId",
            "summary",
            "candidates",
            "storagePath",
        },
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_experiment_read_models_keep_unknown_fields() -> None:
    status = ExperimentPlanningStatusResponse.model_validate(
        {
            "teamId": "team-1",
            "status": "planned",
            "lifecycleProjection": {"stage2": {"activeDesignPlanId": "plan-1"}},
        }
    ).model_dump()
    assert status["lifecycleProjection"]["stage2"]["activeDesignPlanId"] == "plan-1"

    listed = CandidateStoreListResponse.model_validate(
        {
            "teamId": "team-1",
            "candidates": [{"candidateId": "c-1"}],
            "store": {"candidateCount": 1},
        }
    ).model_dump()
    assert listed["store"]["candidateCount"] == 1


def test_experiment_read_models_keep_unknown_fields_without_injecting_defaults() -> None:
    payload = ExperimentPlanningStatusResponse.model_validate(
        {
            "teamId": "team-1",
            "status": "needs_hypothesis",
            "futureHint": {"owner": "experiment"},
        }
    ).model_dump(exclude_unset=True)

    assert payload == {
        "teamId": "team-1",
        "status": "needs_hypothesis",
        "futureHint": {"owner": "experiment"},
    }


def test_experiment_planning_status_next_actions_accepts_service_string_list() -> None:
    status = ExperimentPlanningStatusResponse.model_validate(
        {
            "teamId": "team-1",
            "status": "needs_hypothesis",
            "nextActions": [
                "Start the experiment planning stage round.",
                "Keep training execution disabled until a plan is reviewed.",
            ],
        }
    )

    assert status.nextActions == [
        "Start the experiment planning stage round.",
        "Keep training execution disabled until a plan is reviewed.",
    ]


def test_experiment_write_catch_all_remains_empty_shell() -> None:
    properties = set(ExperimentRouteResponse.model_json_schema().get("properties") or {})
    assert properties == set()
