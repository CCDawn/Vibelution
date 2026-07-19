from __future__ import annotations

from core.chat.turn_journal import (
    EVENT_ASSISTANT_MESSAGE,
    TurnJournalEvent,
    model_visible_messages_from_events,
)


def test_stopped_assistant_event_projects_explicit_interruption_metadata():
    event = TurnJournalEvent(
        schema_version=1,
        event_id="event-stopped",
        session_id="session-stopped",
        turn_id="turn-stopped",
        sequence=1,
        event_type=EVENT_ASSISTANT_MESSAGE,
        status="stopped",
        timestamp="2026-07-20T00:00:00",
        source="test",
        payload={
            "content": "本轮已按请求停止。",
            "toolCalls": [
                {
                    "id": "call-stopped",
                    "name": "code_symbol_tool",
                    "status": "stopped",
                }
            ],
        },
    )

    messages = model_visible_messages_from_events([event])

    assert len(messages) == 1
    assert messages[0]["metadata"]["interrupted"] is True


def test_completed_assistant_event_does_not_project_interruption_metadata():
    event = TurnJournalEvent(
        schema_version=1,
        event_id="event-completed",
        session_id="session-completed",
        turn_id="turn-completed",
        sequence=1,
        event_type=EVENT_ASSISTANT_MESSAGE,
        status="completed",
        timestamp="2026-07-20T00:00:00",
        source="test",
        payload={"content": "已完成。"},
    )

    messages = model_visible_messages_from_events([event])

    assert len(messages) == 1
    assert messages[0]["metadata"]["interrupted"] is False
