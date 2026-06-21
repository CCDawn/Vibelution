# -*- coding: utf-8 -*-
"""Append-only conversation history event view.

This module adapts the conversation ledger's visible message projection into a
searchable tool-facing event list. The ledger remains the only durable history
source.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable


EVENT_USER_MESSAGE = "user_message"
EVENT_ASSISTANT_MESSAGE = "assistant_message"
EVENT_TOOL_CALL = "tool_call"
EVENT_TOOL_RESULT = "tool_result"
EVENT_CHECKPOINT = "checkpoint"
EVENT_RUNTIME_NOTICE = "runtime_notice"


@dataclass(frozen=True)
class HistoryEvent:
    event_id: str
    event_type: str
    session_id: str = ""
    message_index: int = -1
    turn_id: str = ""
    role: str = ""
    content: str = ""
    timestamp: str = ""
    tool_name: str = ""
    tool_call_id: str = ""
    status: str = ""
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "eventId": self.event_id,
            "eventType": self.event_type,
            "sessionId": self.session_id,
            "messageIndex": self.message_index,
            "turnId": self.turn_id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "toolName": self.tool_name,
            "toolCallId": self.tool_call_id,
            "status": self.status,
            "summary": self.summary,
            "metadata": dict(self.metadata or {}),
        }
        return {key: value for key, value in payload.items() if value not in ("", -1, {}, [])}


def build_history_events(
    messages: Iterable[dict[str, Any]] | None,
    *,
    session_id: str = "",
) -> list[HistoryEvent]:
    """Build a stable event view from persisted conversation messages."""

    events: list[HistoryEvent] = []
    tool_call_lookup: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(list(messages or [])):
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "").strip().lower()
        if role == "tool":
            tool_result_event = _tool_role_result_event(
                dict(raw),
                index=index,
                session_id=session_id,
                tool_call_lookup=tool_call_lookup,
            )
            if tool_result_event is not None:
                events.append(tool_result_event)
            continue
        if role not in {"user", "assistant", "runtime_context", "runtime", "system"}:
            continue
        message = dict(raw)
        metadata = _metadata_dict(message)
        content = _content_text(message.get("content"))
        turn_id = _turn_id(message, metadata)
        event_type = _message_event_type(role, metadata)
        message_event_id = _stable_event_id(session_id, index, event_type, message)
        events.append(
            HistoryEvent(
                event_id=message_event_id,
                event_type=event_type,
                session_id=session_id,
                message_index=index,
                turn_id=turn_id,
                role=role,
                content=content,
                timestamp=str(message.get("timestamp") or "").strip(),
                summary=_summary_for_message(content, message),
                metadata=metadata,
                source=message,
            )
        )
        for tool_index, tool in enumerate(_tool_entries(message), start=1):
            tool_name = _tool_name(tool)
            if not tool_name:
                continue
            tool_call_id = _tool_call_id(tool, index=index, tool_index=tool_index)
            tool_summary = _tool_summary(tool)
            common = {
                "session_id": session_id,
                "message_index": index,
                "turn_id": turn_id,
                "role": role,
                "timestamp": str(message.get("timestamp") or "").strip(),
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "status": str(tool.get("status") or "").strip(),
                "summary": tool_summary,
                "metadata": {"messageEventId": message_event_id},
                "source": tool,
            }
            tool_call_lookup[tool_call_id] = {
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "status": str(tool.get("status") or "").strip(),
                "message_event_id": message_event_id,
                "timestamp": str(message.get("timestamp") or "").strip(),
                "turn_id": turn_id,
            }
            events.append(
                HistoryEvent(
                    event_id=_stable_event_id(session_id, index, EVENT_TOOL_CALL, tool, suffix=str(tool_index)),
                    event_type=EVENT_TOOL_CALL,
                    content=_json_preview(_tool_arguments(tool), limit=1000),
                    **common,
                )
            )
            if tool_summary:
                events.append(
                    HistoryEvent(
                        event_id=_stable_event_id(session_id, index, EVENT_TOOL_RESULT, tool, suffix=str(tool_index)),
                        event_type=EVENT_TOOL_RESULT,
                        content=tool_summary,
                        **common,
                    )
                )
    return events


def _tool_role_result_event(
    message: dict[str, Any],
    *,
    index: int,
    session_id: str,
    tool_call_lookup: dict[str, dict[str, Any]],
) -> HistoryEvent | None:
    metadata = _metadata_dict(message)
    content = _content_text(message.get("content"))
    tool_call_id = str(message.get("tool_call_id") or message.get("toolCallId") or message.get("id") or "").strip()
    if not tool_call_id or not content:
        return None
    linked = tool_call_lookup.get(tool_call_id) or {}
    tool_name = (
        str(metadata.get("toolName") or metadata.get("tool_name") or "").strip()
        or str(linked.get("tool_name") or "").strip()
        or _tool_name_from_result_content(content)
    )
    status = (
        str(metadata.get("toolStatus") or metadata.get("tool_status") or metadata.get("status") or "").strip()
        or str(linked.get("status") or "").strip()
    )
    turn_id = _turn_id(message, metadata) or str(linked.get("turn_id") or "")
    event_metadata = {
        "messageEventId": str(linked.get("message_event_id") or ""),
        "canonicalRole": "tool",
    }
    event_metadata.update(metadata)
    return HistoryEvent(
        event_id=_stable_event_id(session_id, index, EVENT_TOOL_RESULT, message, suffix=tool_call_id),
        event_type=EVENT_TOOL_RESULT,
        session_id=session_id,
        message_index=index,
        turn_id=turn_id,
        role="tool",
        content=content,
        timestamp=str(message.get("timestamp") or linked.get("timestamp") or "").strip(),
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        status=status,
        summary=content[:240],
        metadata={key: value for key, value in event_metadata.items() if value not in ("", {}, [])},
        source=message,
    )


def search_history_events(
    events: Iterable[HistoryEvent],
    *,
    query: str = "",
    event_type: str = "",
    tool_name: str = "",
    role: str = "",
    limit: int = 8,
) -> list[HistoryEvent]:
    """Search events by bounded keyword matching."""

    requested_terms = [term for term in _normalize_search_text(query).split() if term]
    normalized_event_type = str(event_type or "").strip().lower()
    normalized_tool = str(tool_name or "").strip().lower()
    normalized_role = str(role or "").strip().lower()
    matches: list[tuple[int, HistoryEvent]] = []
    for event in events:
        if normalized_event_type and event.event_type != normalized_event_type:
            continue
        if normalized_tool and event.tool_name.lower() != normalized_tool:
            continue
        if normalized_role and event.role.lower() != normalized_role:
            continue
        haystack = _normalize_search_text(_event_search_text(event))
        if requested_terms and not all(term in haystack for term in requested_terms):
            continue
        matches.append((_score_event(event, requested_terms, haystack), event))
    bounded_limit = max(1, min(int(limit or 8), 30))
    return [
        event
        for _score, event in sorted(matches, key=lambda item: (item[0], item[1].message_index), reverse=True)[
            :bounded_limit
        ]
    ]


def fetch_history_event(events: Iterable[HistoryEvent], event_id: str) -> HistoryEvent | None:
    normalized = str(event_id or "").strip()
    if not normalized:
        return None
    for event in events:
        if event.event_id == normalized:
            return event
    return None


def timeline_events(
    events: Iterable[HistoryEvent],
    *,
    start: int = 0,
    limit: int = 20,
    include_tools: bool = False,
) -> list[HistoryEvent]:
    bounded_start = max(0, int(start or 0))
    bounded_limit = max(1, min(int(limit or 20), 50))
    selected = [
        event
        for event in events
        if include_tools or event.event_type not in {EVENT_TOOL_CALL, EVENT_TOOL_RESULT}
    ]
    return selected[bounded_start : bounded_start + bounded_limit]


def latest_checkpoint(events: Iterable[HistoryEvent]) -> HistoryEvent | None:
    checkpoints = [event for event in events if event.event_type == EVENT_CHECKPOINT]
    return checkpoints[-1] if checkpoints else None


def render_events_for_tool(events: Iterable[HistoryEvent], *, max_content_chars: int = 600) -> str:
    payload = []
    for event in events:
        item = event.to_dict()
        content = str(item.get("content") or "")
        if len(content) > max_content_chars:
            item["content"] = f"{content[: max_content_chars - 3].rstrip()}..."
        payload.append(item)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _message_event_type(role: str, metadata: dict[str, Any]) -> str:
    kind = str(metadata.get("kind") or "").strip()
    if kind in {EVENT_CHECKPOINT, "compaction_checkpoint"}:
        return EVENT_CHECKPOINT
    if kind == EVENT_RUNTIME_NOTICE:
        return EVENT_RUNTIME_NOTICE
    if role == "user":
        return EVENT_USER_MESSAGE
    if role == "assistant":
        return EVENT_ASSISTANT_MESSAGE
    return EVENT_RUNTIME_NOTICE


def _metadata_dict(message: dict[str, Any]) -> dict[str, Any]:
    metadata = message.get("metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


def _turn_id(message: dict[str, Any], metadata: dict[str, Any]) -> str:
    return str(
        message.get("turnId")
        or message.get("turn_id")
        or metadata.get("turnId")
        or metadata.get("turn_id")
        or ""
    ).strip()


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or "").strip())
        return "\n".join(part for part in parts if part).strip()
    return str(value or "").strip()


def _tool_entries(message: dict[str, Any]) -> list[dict[str, Any]]:
    raw = message.get("toolCalls") or message.get("tool_calls") or message.get("tools") or []
    return [dict(item) for item in list(raw or []) if isinstance(item, dict)]


def _tool_name(tool: dict[str, Any]) -> str:
    function_block = tool.get("function") if isinstance(tool.get("function"), dict) else {}
    return str(
        tool.get("name")
        or tool.get("tool_name")
        or tool.get("toolName")
        or function_block.get("name")
        or ""
    ).strip()


def _tool_call_id(tool: dict[str, Any], *, index: int, tool_index: int) -> str:
    return str(
        tool.get("id")
        or tool.get("tool_call_id")
        or tool.get("toolCallId")
        or f"history_tool_{index}_{tool_index}"
    ).strip()


def _tool_arguments(tool: dict[str, Any]) -> dict[str, Any]:
    function_block = tool.get("function") if isinstance(tool.get("function"), dict) else {}
    args = tool.get("arguments") or tool.get("args") or function_block.get("arguments") or {}
    if isinstance(args, dict):
        return dict(args)
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except json.JSONDecodeError:
            return {"raw": args}
        return parsed if isinstance(parsed, dict) else {"raw": args}
    return {}


def _tool_summary(tool: dict[str, Any]) -> str:
    for key in ("resultPreview", "result_preview", "result", "summary", "error"):
        value = str(tool.get(key) or "").strip()
        if value:
            return value
    return ""


def _tool_name_from_result_content(content: str) -> str:
    for line in str(content or "").splitlines()[:4]:
        match = re.match(r"\s*历史工具调用\s*[:：]\s*(?P<name>[^\s]+)", line)
        if match:
            return match.group("name").strip()
    return ""


def _summary_for_message(content: str, message: dict[str, Any]) -> str:
    tool_count = len(_tool_entries(message))
    text = content.strip()
    if text:
        return text[:240]
    if tool_count:
        return f"包含 {tool_count} 个历史工具调用"
    return ""


def _stable_event_id(session_id: str, index: int, event_type: str, payload: dict[str, Any], *, suffix: str = "") -> str:
    raw_id = str(payload.get("id") or payload.get("messageId") or payload.get("message_id") or "").strip()
    if raw_id and not suffix:
        return raw_id
    seed = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)[:4000]
    digest = hashlib.sha256(seed.encode("utf-8", errors="replace")).hexdigest()[:12]
    parts = [str(session_id or "session"), str(index), event_type]
    if suffix:
        parts.append(suffix)
    parts.append(digest)
    return ":".join(parts)


def _json_preview(value: Any, *, limit: int = 1000) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def _normalize_search_text(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[\s，,。.!！?？、；;：:()（）\[\]{}<>\"'`]+", " ", text)
    return text.strip()


def _event_search_text(event: HistoryEvent) -> str:
    return "\n".join(
        part
        for part in (
            event.event_type,
            event.role,
            event.content,
            event.summary,
            event.tool_name,
            event.status,
            json.dumps(event.metadata, ensure_ascii=False, default=str),
        )
        if str(part or "").strip()
    )


def _score_event(event: HistoryEvent, requested_terms: list[str], haystack: str) -> int:
    score = event.message_index
    if event.event_type in {EVENT_TOOL_RESULT, EVENT_CHECKPOINT}:
        score += 1000
    if event.event_type == EVENT_TOOL_CALL:
        score += 800
    for term in requested_terms:
        score += haystack.count(term) * 20
    return score


__all__ = [
    "EVENT_ASSISTANT_MESSAGE",
    "EVENT_CHECKPOINT",
    "EVENT_RUNTIME_NOTICE",
    "EVENT_TOOL_CALL",
    "EVENT_TOOL_RESULT",
    "EVENT_USER_MESSAGE",
    "HistoryEvent",
    "build_history_events",
    "fetch_history_event",
    "latest_checkpoint",
    "render_events_for_tool",
    "search_history_events",
    "timeline_events",
]
