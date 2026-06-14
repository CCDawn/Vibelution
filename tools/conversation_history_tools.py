# -*- coding: utf-8 -*-
"""LLM-facing read-only tools for the current chat conversation history."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from core.chat.history_ledger import (
    build_checkpoint_message,
    build_history_events,
    fetch_history_event,
    latest_checkpoint,
    render_events_for_tool,
    search_history_events,
    timeline_events,
)
from core.ui.chat_state import load_chat_state, normalize_chat_messages
from core.ui.chat_state import save_chat_state


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
    """Append a hidden checkpoint message to persisted chat state."""

    normalized_session_id = str(session_id or "").strip()
    checkpoint_summary = str(summary or "").strip()
    if not normalized_session_id or not checkpoint_summary:
        return False
    payload = load_chat_state(PROJECT_ROOT)
    conversations = payload.get("conversations")
    if not isinstance(conversations, list):
        return False
    checkpoint = build_checkpoint_message(
        session_id=normalized_session_id,
        covered_event_ids=covered_event_ids or [],
        summary=checkpoint_summary,
        reason=reason,
    )
    timestamp = datetime.now().isoformat(timespec="seconds")
    checkpoint["timestamp"] = timestamp
    for conversation in conversations:
        if not isinstance(conversation, dict):
            continue
        candidate_id = str(
            conversation.get("conversation_id")
            or conversation.get("conversationId")
            or conversation.get("id")
            or ""
        ).strip()
        if candidate_id != normalized_session_id:
            continue
        messages = list(conversation.get("messages") or [])
        existing_checkpoint_ids = {
            str(((item.get("metadata") or {}) if isinstance(item, dict) else {}).get("checkpointId") or "")
            for item in messages
        }
        checkpoint_id = str((checkpoint.get("metadata") or {}).get("checkpointId") or "")
        if checkpoint_id and checkpoint_id in existing_checkpoint_ids:
            return False
        messages.append(checkpoint)
        conversation["messages"] = messages
        conversation["updated_at"] = timestamp
        payload["updated_at"] = timestamp
        save_chat_state(PROJECT_ROOT, payload)
        return True
    return False


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
            return normalize_chat_messages(conversation.get("messages") or [])
    return []


def _json_error(code: str, message: str) -> str:
    return json.dumps({"error": code, "message": message}, ensure_ascii=False)


__all__ = [
    "history_checkpoint_tool",
    "history_fetch_tool",
    "history_search_tool",
    "history_timeline_tool",
    "append_history_checkpoint",
]
