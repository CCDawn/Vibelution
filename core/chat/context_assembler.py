# -*- coding: utf-8 -*-
"""Cache-friendly conversation context assembly."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable

from .history_ledger import (
    EVENT_CHECKPOINT,
    EVENT_TOOL_CALL,
    EVENT_TOOL_RESULT,
    HistoryEvent,
    build_history_events,
    latest_checkpoint,
)


DEFAULT_RECENT_MESSAGE_LIMIT = 8
MAX_RECENT_TOOL_COUNT = 6
MAX_RECENT_TOOL_PREVIEW_CHARS = 700
MAX_RECENT_TOOL_ARGS_CHARS = 320
MAX_RECENT_MESSAGE_CONTENT_CHARS = 6000


@dataclass(frozen=True)
class ContextSegment:
    key: str
    label: str
    source: str
    item_count: int = 0
    chars: int = 0
    cache_policy: str = "dynamic"
    included_in_model_input: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "source": self.source,
            "itemCount": self.item_count,
            "chars": self.chars,
            "cachePolicy": self.cache_policy,
            "includedInModelInput": self.included_in_model_input,
        }


@dataclass(frozen=True)
class ContextAssemblyResult:
    history_messages: list[dict[str, Any]]
    events: list[HistoryEvent]
    included_event_ids: list[str] = field(default_factory=list)
    omitted_event_count: int = 0
    checkpoint_event_id: str = ""
    segments: list[ContextSegment] = field(default_factory=list)
    cacheable_prefix_hash: str = ""
    dynamic_context_hash: str = ""

    def to_composition_patch(self) -> dict[str, Any]:
        return {
            "schemaVersion": 2,
            "includedEventIds": list(self.included_event_ids),
            "omittedEventCount": self.omitted_event_count,
            "checkpointEventId": self.checkpoint_event_id,
            "cache": {
                "cacheablePrefixHash": self.cacheable_prefix_hash,
                "dynamicContextHash": self.dynamic_context_hash,
                "cacheableSegmentCount": len(
                    [segment for segment in self.segments if segment.cache_policy == "prefix_candidate"]
                ),
                "volatileSegmentCount": len(
                    [segment for segment in self.segments if segment.cache_policy != "prefix_candidate"]
                ),
            },
            "segments": [segment.to_dict() for segment in self.segments],
        }


def assemble_conversation_context(
    messages: Iterable[dict[str, Any]] | None,
    *,
    session_id: str = "",
    recent_message_limit: int = DEFAULT_RECENT_MESSAGE_LIMIT,
    retrieved_events: Iterable[HistoryEvent] | None = None,
) -> ContextAssemblyResult:
    """Return the bounded history view used to seed an agent turn."""

    normalized_messages = [dict(item) for item in list(messages or []) if isinstance(item, dict)]
    events = build_history_events(normalized_messages, session_id=session_id)
    bounded_recent_limit = max(1, min(int(recent_message_limit or DEFAULT_RECENT_MESSAGE_LIMIT), 40))
    recent_start_index = max(0, len(normalized_messages) - bounded_recent_limit)
    recent_raw_messages = normalized_messages[recent_start_index:]
    recent_messages = _compact_recent_messages(recent_raw_messages)
    checkpoint = latest_checkpoint(events)
    checkpoint_message = _checkpoint_seed_message(checkpoint)
    retrieved_list = list(retrieved_events or [])
    retrieved_messages = [_event_seed_message(event) for event in retrieved_list]
    history_messages = [message for message in [checkpoint_message, *retrieved_messages, *recent_messages] if message]
    included_event_ids = _included_event_ids(
        events,
        recent_start_index=recent_start_index,
        checkpoint=checkpoint,
        retrieved_events=retrieved_list,
    )
    omitted_event_count = max(0, len(events) - len(set(included_event_ids)))
    segments = [
        ContextSegment(
            key="stable_prefix",
            label="stable prefix",
            source="agent_protocol",
            item_count=1,
            chars=0,
            cache_policy="prefix_candidate",
        ),
        ContextSegment(
            key="history_tail",
            label="history tail",
            source="conversation_history_assembler",
            item_count=len(recent_raw_messages),
            chars=_message_chars(recent_messages),
            cache_policy="dynamic",
        ),
    ]
    if checkpoint is not None:
        segments.append(
            ContextSegment(
                key="history_checkpoint",
                label="history checkpoint",
                source="conversation_history_assembler",
                item_count=1,
                chars=len(checkpoint.content),
                cache_policy="dynamic",
            )
        )
    if retrieved_list:
        segments.append(
            ContextSegment(
                key="retrieved_history",
                label="retrieved history",
                source="history_lookup_tools",
                item_count=len(retrieved_list),
                chars=sum(len(event.content) + len(event.summary) for event in retrieved_list),
                cache_policy="dynamic",
            )
        )
    return ContextAssemblyResult(
        history_messages=history_messages,
        events=events,
        included_event_ids=included_event_ids,
        omitted_event_count=omitted_event_count,
        checkpoint_event_id=checkpoint.event_id if checkpoint else "",
        segments=segments,
        cacheable_prefix_hash=_hash_text("agent_protocol:v1"),
        dynamic_context_hash=_hash_messages(history_messages),
    )


def _checkpoint_seed_message(event: HistoryEvent | None) -> dict[str, Any] | None:
    if event is None:
        return None
    return {
        "role": "assistant",
        "content": f"历史检查点：{event.content or event.summary}",
        "metadata": {
            "kind": "history_checkpoint_seed",
            "eventId": event.event_id,
        },
    }


def _event_seed_message(event: HistoryEvent) -> dict[str, Any]:
    label = event.tool_name or event.event_type
    content = event.content or event.summary
    if event.event_type in {EVENT_TOOL_CALL, EVENT_TOOL_RESULT}:
        content = f"历史工具证据：{label}\n状态：{event.status or 'unknown'}\n{content}".strip()
    return {
        "role": "assistant",
        "content": content,
        "metadata": {
            "kind": "retrieved_history_seed",
            "eventId": event.event_id,
            "eventType": event.event_type,
        },
    }


def _compact_recent_messages(messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_compact_recent_message(message) for message in list(messages or []) if isinstance(message, dict)]


def _compact_recent_message(message: dict[str, Any]) -> dict[str, Any]:
    compacted = dict(message)
    content = str(compacted.get("content") or "")
    if len(content) > MAX_RECENT_MESSAGE_CONTENT_CHARS:
        compacted["content"] = _clip_text(content, MAX_RECENT_MESSAGE_CONTENT_CHARS)

    for key in ("toolCalls", "tool_calls", "tools"):
        entries = compacted.get(key)
        if not isinstance(entries, list):
            continue
        compacted[key] = _compact_tool_entries(entries)

    return compacted


def _compact_tool_entries(entries: list[Any]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    omitted = max(0, len(entries) - MAX_RECENT_TOOL_COUNT)
    for entry in entries[-MAX_RECENT_TOOL_COUNT:]:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or entry.get("toolName") or entry.get("tool_name") or "").strip()
        status = _extract_tool_status(entry)
        item: dict[str, Any] = {
            "name": name,
            "toolName": name,
            "status": status,
            "semanticStatus": str(entry.get("semanticStatus") or entry.get("semantic_status") or status or "").strip(),
        }
        for id_key in ("id", "toolCallId", "tool_call_id"):
            if entry.get(id_key):
                item[id_key] = str(entry.get(id_key))
        preview = _extract_tool_result_preview(entry)
        if preview:
            item["resultPreview"] = _clip_text(preview, MAX_RECENT_TOOL_PREVIEW_CHARS)
        error = str(entry.get("error") or "").strip()
        if error:
            item["error"] = _clip_text(error, MAX_RECENT_TOOL_PREVIEW_CHARS)
        arg_keys = _extract_tool_arg_keys(entry)
        if arg_keys:
            item["argKeys"] = arg_keys[:24]
        elif entry.get("args") is not None or entry.get("arguments") is not None:
            item["argsPreview"] = _clip_text(str(entry.get("args") or entry.get("arguments") or ""), MAX_RECENT_TOOL_ARGS_CHARS)
        compacted.append(item)
    if omitted:
        compacted.insert(
            0,
            {
                "name": "omitted_tool_history",
                "toolName": "omitted_tool_history",
                "status": "omitted",
                "resultPreview": f"已省略 {omitted} 条更早的工具证据；完整记录保留在历史账本中。",
            },
        )
    return compacted


def _extract_tool_status(entry: dict[str, Any]) -> str:
    for key in ("semanticStatus", "semantic_status", "status", "state", "outcome"):
        value = str(entry.get(key) or "").strip()
        if value:
            return value
    result = entry.get("result")
    if isinstance(result, dict):
        return str(result.get("semanticStatus") or result.get("status") or result.get("outcome") or "").strip()
    return ""


def _extract_tool_result_preview(entry: dict[str, Any]) -> str:
    for key in ("resultPreview", "result_preview", "summary", "stdoutPreview", "stdout_preview"):
        value = str(entry.get(key) or "").strip()
        if value:
            return value
    result = entry.get("result")
    if isinstance(result, dict):
        for key in ("resultPreview", "summary", "message", "error", "stdoutPreview", "content"):
            value = str(result.get(key) or "").strip()
            if value:
                return value
    elif result is not None:
        return str(result)
    return ""


def _extract_tool_arg_keys(entry: dict[str, Any]) -> list[str]:
    args = entry.get("args")
    if args is None:
        args = entry.get("arguments")
    if isinstance(args, dict):
        return sorted(str(key) for key in args.keys() if str(key) != "_cancel_checker")
    return []


def _clip_text(text: str, max_chars: int) -> str:
    raw = str(text or "")
    if len(raw) <= max_chars:
        return raw
    suffix = f"\n[...已压缩，原长度 {len(raw)} 字符...]"
    budget = max(0, max_chars - len(suffix))
    return raw[:budget] + suffix


def _included_event_ids(
    events: list[HistoryEvent],
    *,
    recent_start_index: int,
    checkpoint: HistoryEvent | None,
    retrieved_events: Iterable[HistoryEvent] | None,
) -> list[str]:
    included: list[str] = []
    for event in events:
        if event.message_index >= recent_start_index:
            included.append(event.event_id)
    if checkpoint is not None:
        included.append(checkpoint.event_id)
    for event in list(retrieved_events or []):
        included.append(event.event_id)
    return list(dict.fromkeys(included))


def _message_chars(messages: Iterable[dict[str, Any]]) -> int:
    total = 0
    for message in list(messages or []):
        total += len(str(message.get("content") or ""))
        for tool in list(message.get("toolCalls") or message.get("tool_calls") or []):
            if isinstance(tool, dict):
                total += len(str(tool.get("name") or tool.get("toolName") or ""))
                total += len(str(tool.get("summary") or tool.get("resultPreview") or tool.get("error") or ""))
    return total


def _hash_messages(messages: Iterable[dict[str, Any]]) -> str:
    parts = []
    for message in list(messages or []):
        parts.append(str(message.get("role") or ""))
        parts.append(str(message.get("content") or ""))
        parts.append(str(message.get("metadata") or ""))
        for tool in list(message.get("toolCalls") or message.get("tool_calls") or message.get("tools") or []):
            if isinstance(tool, dict):
                parts.append(str(tool.get("name") or tool.get("toolName") or ""))
                parts.append(str(tool.get("status") or tool.get("semanticStatus") or ""))
                parts.append(str(tool.get("resultPreview") or tool.get("error") or ""))
    return _hash_text("\n".join(parts))


def _hash_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8", errors="replace")).hexdigest()[:16]


__all__ = [
    "ContextAssemblyResult",
    "ContextSegment",
    "DEFAULT_RECENT_MESSAGE_LIMIT",
    "assemble_conversation_context",
]
