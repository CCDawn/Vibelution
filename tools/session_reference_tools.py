# -*- coding: utf-8 -*-
"""Read-only tools for querying session references attached to the current turn."""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator


_CURRENT_SESSION_REFERENCES: ContextVar[tuple[dict[str, Any], ...]] = ContextVar(
    "vibelution_current_session_references",
    default=(),
)


def _json_dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


@contextmanager
def session_reference_context(references: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> Iterator[None]:
    normalized = tuple(dict(item) for item in list(references or []) if isinstance(item, dict))
    token = _CURRENT_SESSION_REFERENCES.set(normalized)
    try:
        yield
    finally:
        _CURRENT_SESSION_REFERENCES.reset(token)


def current_session_references() -> list[dict[str, Any]]:
    return [dict(item) for item in _CURRENT_SESSION_REFERENCES.get()]


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _trim_text(value: Any, *, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def _allowed_reference(reference_id: str = "", session_id: str = "") -> dict[str, Any] | None:
    normalized_reference_id = str(reference_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    for reference in current_session_references():
        if normalized_reference_id and str(reference.get("referenceId") or "").strip() == normalized_reference_id:
            return reference
        if normalized_session_id and str(reference.get("sessionId") or "").strip() == normalized_session_id:
            return reference
    return None


def session_reference_query_tool(
    reference_id: str = "",
    session_id: str = "",
    query: str = "",
    limit: int = 8,
    max_chars_per_message: int = 700,
) -> str:
    """Query bounded history from a session reference attached to the current turn."""

    reference = _allowed_reference(reference_id=reference_id, session_id=session_id)
    if reference is None:
        return _json_dump(
            {
                "status": "error",
                "error": "session_reference_not_allowed",
                "message": "只能查询本轮用户拖入消息框并随消息发送的会话引用。",
                "requestedReferenceId": str(reference_id or "").strip(),
                "requestedSessionId": str(session_id or "").strip(),
                "availableReferences": [
                    {
                        "referenceId": item.get("referenceId"),
                        "sessionId": item.get("sessionId"),
                        "title": item.get("title"),
                    }
                    for item in current_session_references()
                ],
            }
        )
    target_session_id = str(reference.get("sessionId") or "").strip()
    try:
        from core.web.services.session_service import get_session_detail

        detail = get_session_detail(target_session_id)
    except Exception as exc:
        return _json_dump(
            {
                "status": "error",
                "error": exc.__class__.__name__,
                "message": str(exc),
                "sessionId": target_session_id,
            }
        )
    if not isinstance(detail, dict):
        return _json_dump(
            {
                "status": "error",
                "error": "session_not_found",
                "message": f"找不到引用会话 {target_session_id}。",
                "sessionId": target_session_id,
            }
        )

    normalized_limit = _bounded_int(limit, default=8, minimum=1, maximum=20)
    per_message_chars = _bounded_int(max_chars_per_message, default=700, minimum=120, maximum=1600)
    normalized_query = str(query or "").strip().lower()
    messages: list[dict[str, Any]] = []
    for index, message in enumerate(list(detail.get("messages") or []), start=1):
        if not isinstance(message, dict):
            continue
        content = str(message.get("content") or "")
        thought = str(message.get("thought") or "")
        haystack = f"{content}\n{thought}".lower()
        if normalized_query and normalized_query not in haystack:
            continue
        messages.append(
            {
                "index": index,
                "role": str(message.get("role") or "").strip(),
                "timestamp": str(message.get("timestamp") or "").strip(),
                "content": _trim_text(content, max_chars=per_message_chars),
                "hasThought": bool(thought.strip()),
                "toolCallCount": len(message.get("toolCalls") or []),
                "referenceCount": len(message.get("references") or []),
            }
        )
    selected = messages[-normalized_limit:]
    return _json_dump(
        {
            "status": "ok",
            "tool": "session_reference_query_tool",
            "reference": {
                "referenceId": reference.get("referenceId"),
                "sessionId": target_session_id,
                "title": reference.get("title") or detail.get("title"),
                "agentId": reference.get("agentId") or detail.get("agentId"),
                "agentDisplayName": reference.get("agentDisplayName") or detail.get("agentDisplayName"),
                "allowed": {"query": True, "sendMessage": False},
            },
            "query": str(query or "").strip(),
            "matchedMessageCount": len(messages),
            "returnedMessageCount": len(selected),
            "messages": selected,
            "usageBoundary": "Read-only. Sending to this Agent requires an explicit user request and agent_message_tool.",
        }
    )
