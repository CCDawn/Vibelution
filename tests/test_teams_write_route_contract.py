"""Team write response contract regressions."""

from __future__ import annotations

from fastapi.routing import APIRoute

from core.web.routes import teams
from core.web.routes.teams_write_models import (
    TeamAiSearchRunResponse,
    TeamMessageResponse,
    TeamRepairResponse,
)


def test_team_write_response_models_publish_stable_fields() -> None:
    expected_properties = {
        TeamAiSearchRunResponse: {
            "schemaVersion",
            "runId",
            "teamId",
            "title",
            "topic",
            "status",
            "createdAt",
            "updatedAt",
            "sourceScope",
            "queryPlan",
            "cards",
            "errors",
            "summary",
            "storage",
        },
        TeamMessageResponse: {
            "eventId",
            "messageType",
            "targetScope",
            "targetAgentIds",
            "targetAgentCodes",
            "targetAgentNames",
            "mentionedTokens",
            "unresolvedMentions",
            "content",
            "summary",
            "createdBy",
            "createdAt",
            "updatedAt",
            "metadata",
            "kernel",
            "deliveries",
            "interruptions",
        },
        TeamRepairResponse: {
            "schemaVersion",
            "teamId",
            "created",
            "memberCount",
            "agentCount",
            "directSessionCount",
            "purgedAgentIds",
            "purgeResults",
            "roles",
            "team",
        },
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_team_write_response_models_keep_unknown_fields_without_defaults() -> None:
    run = TeamAiSearchRunResponse.model_validate(
        {"runId": "run-1", "futureEvidence": {"source": "catalog"}}
    ).model_dump(exclude_unset=True)
    assert run == {
        "runId": "run-1",
        "futureEvidence": {"source": "catalog"},
    }

    message = TeamMessageResponse.model_validate(
        {"eventId": "event-1", "futureDelivery": True}
    ).model_dump(exclude_unset=True)
    assert message == {"eventId": "event-1", "futureDelivery": True}

    repair = TeamRepairResponse.model_validate(
        {"teamId": "research-team", "futureRepair": ["agent-1"]}
    ).model_dump(exclude_unset=True)
    assert repair == {
        "teamId": "research-team",
        "futureRepair": ["agent-1"],
    }


def test_team_write_routes_use_typed_models_without_default_injection() -> None:
    expected_models = {
        "team_ai_search_run_start": TeamAiSearchRunResponse,
        "team_message_create": TeamMessageResponse,
        "team_knowledge_expansion_agents_repair": TeamRepairResponse,
    }
    routes = {
        route.name: route
        for route in teams.router.routes
        if isinstance(route, APIRoute)
    }

    for route_name, response_model in expected_models.items():
        route = routes[route_name]
        assert route.response_model is response_model
        assert route.response_model_exclude_unset is True

    assert "team_challenge_cup_agents_repair" not in routes
