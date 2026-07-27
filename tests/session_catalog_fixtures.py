"""Deterministic synthetic session summaries for catalog parity and profiling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


QUERY_SEARCH_FIELDS = (
    "id",
    "title",
    "taskTitle",
    "taskSummary",
    "agentId",
    "agentCode",
    "agentDisplayName",
    "dialogueModelId",
    "sessionKind",
    "status",
    "currentPhase",
)


def build_session_query_summaries(count: int) -> list[dict[str, Any]]:
    """Return summaries in the current default session-list order."""

    if count < 0:
        raise ValueError("count must be non-negative")

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    state_cycle = (
        ("ready", "idle", ""),
        ("running", "model_request", "running"),
        ("failed", "terminal", "failed"),
        ("completed", "terminal", "completed"),
    )
    summaries: list[dict[str, Any]] = []
    for index in range(count):
        status, current_phase, child_status = state_cycle[index % len(state_cycle)]
        updated_at = base + timedelta(seconds=index)
        agent_number = index % 16
        session_kind = "child" if index % 7 == 0 else "main"
        search_marker = "needle" if index % 10 == 0 else "ordinary"
        summaries.append(
            {
                "id": f"session-{index:05d}",
                "title": f"Session {index:05d} {search_marker}",
                "taskTitle": f"Task {index:05d}",
                "taskSummary": f"Synthetic {search_marker} summary {index:05d}",
                "agentId": f"agent-{agent_number:02d}",
                "agentCode": f"A{agent_number:03d}",
                "agentDisplayName": f"Agent {agent_number:02d}",
                "dialogueModelId": f"model-{index % 3}",
                "sessionKind": session_kind,
                "status": status,
                "currentPhase": current_phase,
                "childStatus": child_status,
                "conversationIndexVisibility": "user_visible",
                "updatedAt": updated_at.isoformat(),
                "lastActive": updated_at.isoformat(),
            }
        )

    summaries.reverse()
    return summaries


def build_session_conversations(count: int) -> list[dict[str, Any]]:
    """Return canonical chat-state records matching the synthetic summaries."""

    summaries = build_session_query_summaries(count)
    conversations: list[dict[str, Any]] = []
    for summary in reversed(summaries):
        conversations.append(
            {
                "conversation_id": summary["id"],
                "title": summary["title"],
                "task_title": summary["title"],
                "task_summary": summary["taskSummary"],
                "agent_id": summary["agentId"],
                "agentId": summary["agentId"],
                "dialogue_model_id": summary["dialogueModelId"],
                "session_kind": summary["sessionKind"],
                "status": summary["status"],
                "current_phase": summary["currentPhase"],
                "child_status": summary["childStatus"],
                "conversation_index_kind": "user_chat",
                "conversationIndexKind": "user_chat",
                "updated_at": summary["updatedAt"],
            }
        )
    return conversations
