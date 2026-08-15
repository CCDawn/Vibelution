"""Project Agent bus JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.project_agent_bus_models import (
    ProjectAgentBusEventResponse,
    ProjectAgentBusListResponse,
)


def test_project_agent_bus_models_publish_known_schema_fields() -> None:
    expected_properties = {
        ProjectAgentBusListResponse: {"events", "activeAgentCount", "updatedAt"},
        ProjectAgentBusEventResponse: {
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
            "status",
            "revokedAt",
            "revokedBy",
            "revokeReason",
            "createdBy",
            "createdAt",
            "updatedAt",
            "metadata",
            "kernel",
            "deliveries",
            "interruptions",
            "revocations",
        },
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_project_agent_bus_event_keeps_unknown_fields() -> None:
    payload = ProjectAgentBusEventResponse.model_validate(
        {
            "eventId": "projectbus-1",
            "deliveries": [{"status": "delivered"}],
            "kernel": {"enabled": True},
        }
    ).model_dump()

    assert payload["deliveries"] == [{"status": "delivered"}]
    assert payload["kernel"] == {"enabled": True}


def test_project_agent_bus_event_keeps_unknown_fields_without_injecting_defaults() -> None:
    payload = ProjectAgentBusEventResponse.model_validate(
        {
            "eventId": "projectbus-2",
            "content": "hello",
            "futureHint": {"owner": "bus"},
        }
    ).model_dump(exclude_unset=True)

    assert payload == {
        "eventId": "projectbus-2",
        "content": "hello",
        "futureHint": {"owner": "bus"},
    }
