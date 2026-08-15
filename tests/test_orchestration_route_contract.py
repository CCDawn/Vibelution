"""Team workflow orchestration JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.team_workflows.orchestration_models import TeamWorkflowOrchestrationResponse


def test_orchestration_model_publishes_known_schema_fields() -> None:
    properties = set(TeamWorkflowOrchestrationResponse.model_json_schema().get("properties") or {})
    expected = {
        "schemaVersion",
        "workflowId",
        "teamId",
        "workflowKind",
        "status",
        "ownerAgentId",
        "stateMachine",
        "routingPolicy",
        "transferPolicy",
        "activeWorkflowItems",
        "candidateStore",
        "transferRecordsPath",
        "storagePath",
        "createdAt",
        "updatedAt",
    }
    assert expected <= properties, (
        f"TeamWorkflowOrchestrationResponse is missing fields: {sorted(expected - properties)}"
    )


def test_orchestration_model_keeps_unknown_fields() -> None:
    payload = TeamWorkflowOrchestrationResponse.model_validate(
        {
            "teamId": "team-1",
            "candidateStore": {"candidateCount": 2, "candidateTypes": ["source"]},
        }
    ).model_dump()

    assert payload["candidateStore"] == {"candidateCount": 2, "candidateTypes": ["source"]}


def test_orchestration_model_keeps_unknown_fields_without_injecting_defaults() -> None:
    payload = TeamWorkflowOrchestrationResponse.model_validate(
        {
            "teamId": "team-1",
            "workflowId": "wf-1",
            "futureHint": {"owner": "orchestration"},
        }
    ).model_dump(exclude_unset=True)

    assert payload == {
        "teamId": "team-1",
        "workflowId": "wf-1",
        "futureHint": {"owner": "orchestration"},
    }
