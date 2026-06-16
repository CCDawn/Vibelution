# -*- coding: utf-8 -*-
"""Canonical model-visible chat messages.

This module is the boundary between persisted/UI conversation shapes and the
LLM-facing message chain. UI projections may keep camelCase fields such as
``toolCalls``; model context uses the snake_case/tool-role structure here.
"""

from __future__ import annotations

import json
from typing import Any, Iterable


MODEL_MESSAGE_SCHEMA_VERSION = 1


def normalize_model_messages(messages: Iterable[Any]) -> list[Any]:
    """Return canonical model messages from mixed persisted message shapes."""

    normalized: list[Any] = []
    for index, raw in enumerate(list(messages or [])):
        if not isinstance(raw, dict):
            if hasattr(raw, "content") and hasattr(raw, "type"):
                normalized.append(raw)
                continue
            text = str(raw or "").strip()
            if text:
                normalized.append(_base_message("user", text, source_index=index))
            continue
        role = _normalize_role(raw.get("role"))
        if role == "assistant":
            normalized.extend(_assistant_messages(raw, source_index=index))
            continue
        if role == "tool":
            tool_message = _tool_role_message(raw, source_index=index)
            if tool_message:
                normalized.append(tool_message)
            continue
        message = _base_message(role, _content_value(raw.get("content")), source_index=index)
        _copy_optional(raw, message, ("attachments", "metadata", "references", "reasoning_content"))
        if role == "assistant" and not message.get("content"):
            continue
        if role == "user" and not message.get("content") and not message.get("attachments") and not message.get("references"):
            continue
        normalized.append(message)
    return _dedupe_adjacent_tool_results(normalized)


def _assistant_messages(message: dict[str, Any], *, source_index: int) -> list[dict[str, Any]]:
    content = _content_value(message.get("content"))
    tool_entries = _tool_entries(message)
    if not tool_entries:
        if not _visible_text(content) and not _visible_text(message.get("reasoning_content")):
            return []
        assistant = _base_message("assistant", content, source_index=source_index)
        _copy_optional(message, assistant, ("metadata", "reasoning_content", "mental_snapshot", "mentalSnapshot"))
        return [assistant]

    tool_calls: list[dict[str, Any]] = []
    tool_messages: list[dict[str, Any]] = []
    for tool_index, entry in enumerate(tool_entries, start=1):
        normalized = _normalize_tool_call(entry, source_index=source_index, tool_index=tool_index)
        if not normalized:
            continue
        tool_calls.append(normalized)
        result_content = _tool_result_content(normalized["name"], entry)
        if result_content:
            tool_messages.append(
                {
                    "role": "tool",
                    "content": result_content,
                    "tool_call_id": normalized["id"],
                    "metadata": {
                        "schemaVersion": MODEL_MESSAGE_SCHEMA_VERSION,
                        "kind": "canonical_tool_result",
                        "sourceIndex": source_index,
                        "toolName": normalized["name"],
                    },
                }
            )
    if not tool_calls and not _visible_text(content):
        return []
    assistant = _base_message("assistant", content, source_index=source_index)
    if tool_calls:
        assistant["tool_calls"] = [_provider_tool_call(item) for item in tool_calls]
    _copy_optional(message, assistant, ("metadata", "reasoning_content", "mental_snapshot", "mentalSnapshot"))
    return [assistant, *tool_messages]


def _tool_role_message(message: dict[str, Any], *, source_index: int) -> dict[str, Any]:
    tool_call_id = str(message.get("tool_call_id") or message.get("toolCallId") or message.get("id") or "").strip()
    content = _content_value(message.get("content"))
    if not tool_call_id or not _visible_text(content):
        return {}
    normalized = _base_message("tool", content, source_index=source_index)
    normalized["tool_call_id"] = tool_call_id
    _copy_optional(message, normalized, ("metadata",))
    return normalized


def _base_message(role: str, content: Any, *, source_index: int) -> dict[str, Any]:
    return {
        "role": _normalize_role(role),
        "content": content,
        "metadata": {
            "schemaVersion": MODEL_MESSAGE_SCHEMA_VERSION,
            "sourceIndex": source_index,
        },
    }


def _copy_optional(source: dict[str, Any], target: dict[str, Any], keys: tuple[str, ...]) -> None:
    for key in keys:
        if key not in source:
            continue
        value = source.get(key)
        if key == "metadata" and isinstance(value, dict):
            metadata = dict(target.get("metadata") or {})
            metadata.update(value)
            metadata.setdefault("schemaVersion", MODEL_MESSAGE_SCHEMA_VERSION)
            target["metadata"] = metadata
        elif value not in (None, "", [], {}):
            target["mental_snapshot" if key == "mentalSnapshot" else key] = value


def _normalize_role(value: Any) -> str:
    role = str(value or "user").strip().lower() or "user"
    if role == "human":
        return "user"
    if role == "ai":
        return "assistant"
    if role in {"system", "user", "assistant", "tool", "runtime_context", "runtime"}:
        return role
    return "user"


def _content_value(value: Any) -> Any:
    if isinstance(value, list):
        return [dict(item) if isinstance(item, dict) else item for item in value]
    return str(value or "").strip()


def _visible_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item or ""))
        return "".join(parts).strip()
    return str(value or "").strip()


def _tool_entries(message: dict[str, Any]) -> list[dict[str, Any]]:
    raw = message.get("tool_calls") or message.get("toolCalls") or message.get("tools") or []
    return [dict(item) for item in list(raw or []) if isinstance(item, dict)]


def _normalize_tool_call(entry: dict[str, Any], *, source_index: int, tool_index: int) -> dict[str, Any]:
    function = entry.get("function") if isinstance(entry.get("function"), dict) else {}
    name = str(
        entry.get("name")
        or entry.get("tool_name")
        or entry.get("toolName")
        or function.get("name")
        or ""
    ).strip()
    if not name:
        return {}
    tool_call_id = str(
        entry.get("id")
        or entry.get("tool_call_id")
        or entry.get("toolCallId")
        or entry.get("taskId")
        or f"history_tool_{source_index}_{tool_index}"
    ).strip()
    arguments = _tool_arguments(entry)
    return {
        "id": tool_call_id,
        "name": name,
        "args": arguments,
    }


def _tool_arguments(entry: dict[str, Any]) -> dict[str, Any]:
    function = entry.get("function") if isinstance(entry.get("function"), dict) else {}
    raw = entry.get("arguments") if "arguments" in entry else entry.get("args")
    if raw is None:
        raw = function.get("arguments")
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}
        return parsed if isinstance(parsed, dict) else {"raw": raw}
    return {}


def _provider_tool_call(tool_call: dict[str, Any]) -> dict[str, Any]:
    arguments = tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {}
    return {
        "id": str(tool_call.get("id") or ""),
        "type": "function",
        "function": {
            "name": str(tool_call.get("name") or ""),
            "arguments": json.dumps(arguments, ensure_ascii=False),
        },
        "name": str(tool_call.get("name") or ""),
        "args": dict(arguments),
    }


def _tool_result_content(name: str, entry: dict[str, Any]) -> str:
    result = _first_non_empty(
        entry.get("result"),
        entry.get("error"),
        entry.get("resultSegments"),
        entry.get("stdoutPreview"),
        entry.get("stderrPreview"),
        entry.get("summary"),
        entry.get("resultPreview"),
        entry.get("result_preview"),
    )
    if result in (None, ""):
        return ""
    if isinstance(result, (list, dict)):
        result_text = json.dumps(result, ensure_ascii=False, sort_keys=True)
    else:
        result_text = str(result)
    status = str(entry.get("status") or "").strip()
    lines = [f"历史工具调用: {name}"]
    if status:
        lines.append(f"状态: {status}")
    lines.extend(["结果:", result_text])
    return "\n".join(lines)


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value in (None, ""):
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        text = value if isinstance(value, (list, dict)) else str(value)
        if isinstance(text, str) and not text.strip():
            continue
        return value
    return ""


def _dedupe_adjacent_tool_results(messages: list[Any]) -> list[Any]:
    deduped: list[Any] = []
    previous_key: tuple[str, str, str] | None = None
    for message in messages:
        if not isinstance(message, dict):
            deduped.append(message)
            previous_key = None
            continue
        key = (
            str(message.get("role") or ""),
            str(message.get("tool_call_id") or ""),
            str(message.get("content") or ""),
        )
        if message.get("role") == "tool" and key == previous_key:
            continue
        deduped.append(message)
        previous_key = key
    return deduped


__all__ = [
    "MODEL_MESSAGE_SCHEMA_VERSION",
    "normalize_model_messages",
]
