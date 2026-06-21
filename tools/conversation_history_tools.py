# -*- coding: utf-8 -*-
"""LLM-facing read-only tools for the current chat conversation history."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.chat.conversation_ledger import (
    append_context_compression_checkpoint,
    conversation_visible_messages_from_events,
    load_conversation_events,
)
from core.chat.history_ledger import (
    build_history_events,
    fetch_history_event,
    latest_checkpoint,
    render_events_for_tool,
    search_history_events,
    timeline_events,
)
from core.ui.chat_state import load_chat_state, save_chat_state


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def history_search_tool(
    query: str = "",
    event_type: str = "",
    tool_name: str = "",
    role: str = "",
    limit: int = 8,
    session_id: str = "",
) -> str:
    """Search the current conversation history."""

    resolved_session_id = _resolve_session_id(session_id)
    if not resolved_session_id:
        return _json_error("missing_session_id", "找不到当前会话 ID，无法查询会话历史。")
    messages = _messages_for_session(resolved_session_id)
    events = build_history_events(messages, session_id=resolved_session_id)
    matches = search_history_events(
        events,
        query=query,
        event_type=event_type,
        tool_name=tool_name,
        role=role,
        limit=limit,
    )
    return render_events_for_tool(matches, max_content_chars=500)


def history_fetch_tool(event_id: str, session_id: str = "") -> str:
    """Fetch one exact conversation history event by event_id."""

    resolved_session_id = _resolve_session_id(session_id)
    if not resolved_session_id:
        return _json_error("missing_session_id", "找不到当前会话 ID，无法读取会话历史。")
    normalized_event_id = str(event_id or "").strip()
    if not normalized_event_id:
        return _json_error("missing_event_id", "event_id 不能为空。")
    messages = _messages_for_session(resolved_session_id)
    events = build_history_events(messages, session_id=resolved_session_id)
    event = fetch_history_event(events, normalized_event_id)
    if event is None:
        return _json_error("event_not_found", f"找不到历史事件：{normalized_event_id}")
    return render_events_for_tool([event], max_content_chars=2000)


def history_timeline_tool(start: int = 0, limit: int = 20, include_tools: bool = False, session_id: str = "") -> str:
    """Return a compact timeline of the current conversation history."""

    resolved_session_id = _resolve_session_id(session_id)
    if not resolved_session_id:
        return _json_error("missing_session_id", "找不到当前会话 ID，无法读取会话时间线。")
    messages = _messages_for_session(resolved_session_id)
    events = build_history_events(messages, session_id=resolved_session_id)
    return render_events_for_tool(
        timeline_events(events, start=start, limit=limit, include_tools=include_tools),
        max_content_chars=400,
    )


def history_checkpoint_tool(session_id: str = "") -> str:
    """Return the latest conversation checkpoint, if one exists."""

    resolved_session_id = _resolve_session_id(session_id)
    if not resolved_session_id:
        return _json_error("missing_session_id", "找不到当前会话 ID，无法读取会话检查点。")
    messages = _messages_for_session(resolved_session_id)
    checkpoint = latest_checkpoint(build_history_events(messages, session_id=resolved_session_id))
    if checkpoint is None:
        return json.dumps({"checkpoint": None, "message": "当前会话还没有历史检查点。"}, ensure_ascii=False)
    return render_events_for_tool([checkpoint], max_content_chars=1200)


def append_history_checkpoint(
    *,
    session_id: str,
    summary: str,
    reason: str = "",
    covered_event_ids: list[str] | None = None,
) -> bool:
    """Append a ledger-backed history checkpoint."""

    normalized_session_id = str(session_id or "").strip()
    checkpoint_summary = str(summary or "").strip()
    if not normalized_session_id or not checkpoint_summary:
        return False
    if not _session_exists(normalized_session_id):
        return False
    events = load_conversation_events(PROJECT_ROOT, normalized_session_id)
    existing_checkpoint_summaries = {
        str(event.payload.get("summary") or "").strip()
        for event in events
        if getattr(event, "event_type", "") == "compaction_checkpoint"
    }
    if checkpoint_summary in existing_checkpoint_summaries:
        return False
    written = append_context_compression_checkpoint(
        PROJECT_ROOT,
        normalized_session_id,
        turn_id="history-checkpoint",
        summary=checkpoint_summary,
        level="history",
        reason=reason,
        before_tokens=0,
        after_tokens=0,
        source_message_count=len(conversation_visible_messages_from_events(events)),
        source="conversation_history_tool",
    )
    if written is None:
        return False
    _drop_session_messages_field(normalized_session_id)
    return True


def _resolve_session_id(session_id: str = "") -> str:
    explicit = str(session_id or "").strip()
    if explicit:
        return explicit
    try:
        from core.web.services.agent_directory_service import current_agent_runtime

        runtime = current_agent_runtime()
    except Exception:
        runtime = {}
    if isinstance(runtime, dict):
        value = str(runtime.get("sessionId") or runtime.get("directSessionId") or "").strip()
        if value:
            return value
    return ""


def _messages_for_session(session_id: str) -> list[dict[str, Any]]:
    if not _session_exists(session_id):
        return []
    events = load_conversation_events(PROJECT_ROOT, session_id)
    return conversation_visible_messages_from_events(events)


def _session_exists(session_id: str) -> bool:
    payload = load_chat_state(PROJECT_ROOT)
    for conversation in list(payload.get("conversations") or []):
        if not isinstance(conversation, dict):
            continue
        candidate_id = str(
            conversation.get("conversation_id")
            or conversation.get("conversationId")
            or conversation.get("id")
            or ""
        ).strip()
        if candidate_id == session_id:
            return True
    return False


def _drop_session_messages_field(session_id: str) -> None:
    payload = load_chat_state(PROJECT_ROOT)
    changed = False
    for conversation in list(payload.get("conversations") or []):
        if not isinstance(conversation, dict):
            continue
        candidate_id = str(
            conversation.get("conversation_id")
            or conversation.get("conversationId")
            or conversation.get("id")
            or ""
        ).strip()
        if candidate_id == session_id and "messages" in conversation:
            conversation.pop("messages", None)
            changed = True
    if changed:
        save_chat_state(PROJECT_ROOT, payload)


def _json_error(code: str, message: str) -> str:
    return json.dumps({"error": code, "message": message}, ensure_ascii=False)


__all__ = [
    "history_checkpoint_tool",
    "history_fetch_tool",
    "history_search_tool",
    "history_timeline_tool",
    "append_history_checkpoint",
]
