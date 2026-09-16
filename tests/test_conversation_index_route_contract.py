"""Conversation index JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.conversation_models import (
    ConversationIndexItem,
    ConversationQueryResponse,
)


def test_conversation_index_item_publishes_known_schema_fields() -> None:
    properties = set(ConversationIndexItem.model_json_schema().get("properties") or {})
    expected = {"conversationId", "type", "title", "status", "updatedAt"}
    assert expected <= properties, (
        f"ConversationIndexItem is missing fields: {sorted(expected - properties)}"
    )


def test_conversation_index_item_keeps_unknown_fields() -> None:
    payload = ConversationIndexItem.model_validate(
        {
            "conversationId": "session-direct",
            "type": "direct_agent",
            "title": "唐映白",
            "status": "idle",
            "updatedAt": "2026-08-16T00:00:00Z",
            "conversationIndexKind": "personal_agent",
            "sourceRef": {"owner": "ConversationLedger"},
        }
    ).model_dump()

    assert payload["conversationIndexKind"] == "personal_agent"
    assert payload["sourceRef"] == {"owner": "ConversationLedger"}


def test_conversation_query_response_publishes_cursor_envelope() -> None:
    properties = set(ConversationQueryResponse.model_json_schema().get("properties") or {})
    expected = {"items", "nextCursor", "totalEstimate", "filters"}
    assert expected <= properties, (
        f"ConversationQueryResponse is missing fields: {sorted(expected - properties)}"
    )

    filters = set(
        ConversationQueryResponse.model_fields["filters"]
        .annotation.model_json_schema()
        .get("properties")
        or {}
    )
    assert {"q", "agentId", "teamId", "type", "sort", "limit", "cursor"} <= filters


def test_conversation_query_response_items_validate_as_index_items() -> None:
    payload = ConversationQueryResponse.model_validate(
        {
            "items": [
                {
                    "conversationId": "session-direct",
                    "type": "direct_agent",
                    "title": "唐映白",
                    "status": "ready",
                    "updatedAt": "2026-09-01T00:00:00Z",
                    "conversationIndexKind": "personal_agent",
                },
                {
                    "conversationId": "room-1",
                    "type": "group_room",
                    "title": "团队房间",
                    "roomId": "room-1",
                    "participantCount": 3,
                },
            ],
            "nextCursor": "2",
            "totalEstimate": 7,
            "filters": {"q": "", "type": "", "limit": 100, "cursor": ""},
        }
    )

    assert payload.totalEstimate == 7
    assert payload.nextCursor == "2"
    assert payload.items[0].conversationIndexKind == "personal_agent"
    assert payload.items[1].roomId == "room-1"
