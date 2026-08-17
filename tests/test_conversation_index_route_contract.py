"""Conversation index JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.conversation_models import ConversationIndexItem


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
