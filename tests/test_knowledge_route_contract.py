"""Team workflow knowledge JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.team_workflows.knowledge_models import (
    CoordinationStatusResponse,
    KnowledgeIngestionStatusResponse,
)


def test_knowledge_status_models_publish_known_schema_fields() -> None:
    expected_properties = {
        KnowledgeIngestionStatusResponse: {
            "schemaVersion",
            "teamId",
            "workflowId",
            "workflowKind",
            "scope",
            "status",
            "summary",
            "stages",
            "actionItems",
            "candidateBreakdown",
            "candidateGraphSummary",
            "officialBoundary",
            "knowledgeBases",
            "storage",
            "activeWorkRun",
            "latestWorkRun",
            "updatedAt",
        },
        CoordinationStatusResponse: {
            "schemaVersion",
            "teamId",
            "workflowId",
            "workflowKind",
            "scope",
            "status",
            "ownerAgentId",
            "summary",
            "queues",
            "actionItems",
            "communication",
            "coordinationPolicy",
            "storage",
            "updatedAt",
        },
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_knowledge_status_models_keep_unknown_fields() -> None:
    payload = KnowledgeIngestionStatusResponse.model_validate(
        {
            "teamId": "team-1",
            "status": "ready",
            "officialBoundary": {"writesOfficialRag": False},
        }
    ).model_dump()

    assert payload["officialBoundary"] == {"writesOfficialRag": False}

    coordinated = CoordinationStatusResponse.model_validate(
        {
            "teamId": "team-1",
            "queues": {"pendingTransfers": [{"candidateId": "c-1"}]},
        }
    ).model_dump()
    assert coordinated["queues"]["pendingTransfers"] == [{"candidateId": "c-1"}]


def test_knowledge_status_models_keep_unknown_fields_without_injecting_defaults() -> None:
    payload = KnowledgeIngestionStatusResponse.model_validate(
        {
            "teamId": "team-1",
            "status": "in_progress",
            "futureHint": {"owner": "knowledge"},
        }
    ).model_dump(exclude_unset=True)

    assert payload == {
        "teamId": "team-1",
        "status": "in_progress",
        "futureHint": {"owner": "knowledge"},
    }
