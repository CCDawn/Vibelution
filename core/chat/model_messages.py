# -*- coding: utf-8 -*-
"""Canonical model-visible chat messages.

This module is the boundary between persisted/UI conversation shapes and the
LLM-facing message chain. UI projections may keep camelCase fields such as
``toolCalls``.

Historical model context is semantic text. Provider ``role=tool`` messages are
reserved for the live tool-call protocol inside the current ReAct turn.
"""

from __future__ import annotations

import json
from typing import Any, Iterable


MODEL_MESSAGE_SCHEMA_VERSION = 1


def normalize_model_messages(messages: Iterable[Any]) -> list[Any]:
    """Return history-safe model messages from mixed persisted message shapes."""

    return normalize_model_history_messages(messages)


def normalize_model_history_messages(messages: Iterable[Any]) -> list[Any]:
    """Return semantic history messages without provider-level tool roles."""

    normalized: list[Any] = []
    raw_messages = list(messages or [])
    for index, raw in enumerate(raw_messages):
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
            normalized.extend(
                _assistant_history_messages(
                    raw,
                    source_index=index,
                    suppress_empty_tool_summaries=_assistant_tool_calls_have_following_results(
                        raw_messages,
                        index,
                        raw,
                    ),
                )
            )
            continue
        if role == "tool":
            tool_message = _tool_role_history_message(raw, source_index=index)
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
    return _dedupe_adjacent_semantic_messages(normalized)


def normalize_provider_turn_messages(messages: Iterable[Any]) -> list[Any]:
    """Return provider-facing messages with illegal historical tool chains repaired."""

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
            normalized.extend(_assistant_provider_messages(raw, source_index=index))
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
    return _repair_provider_tool_chain(_dedupe_adjacent_tool_results(normalized))


def _assistant_history_messages(
    message: dict[str, Any],
    *,
    source_index: int,
    suppress_empty_tool_summaries: bool = False,
) -> list[dict[str, Any]]:
    content = _content_value(message.get("content"))
    tool_entries = _tool_entries(message)
    tool_summaries: list[str] = []
    for tool_index, entry in enumerate(tool_entries, start=1):
        normalized = _normalize_tool_call(entry, source_index=source_index, tool_index=tool_index)
        if not normalized:
            continue
        if suppress_empty_tool_summaries and not _tool_entry_has_result(entry):
            continue
        summary = _history_tool_summary(normalized["name"], entry)
        if summary:
            tool_summaries.append(summary)
    if not tool_summaries:
        if not _visible_text(content) and not _visible_text(message.get("reasoning_content")):
            return []
        assistant = _base_message("assistant", content, source_index=source_index)
        _copy_optional(message, assistant, ("metadata", "reasoning_content", "mental_snapshot", "mentalSnapshot"))
        return [assistant]

    history_content = _join_text_blocks([_visible_text(content), *tool_summaries])
    assistant = _base_message("assistant", history_content, source_index=source_index)
    _copy_optional(message, assistant, ("metadata", "reasoning_content", "mental_snapshot", "mentalSnapshot"))
    metadata = dict(assistant.get("metadata") or {})
    metadata["kind"] = "historical_tool_context"
    metadata["toolSummaryCount"] = len(tool_summaries)
    assistant["metadata"] = metadata
    return [assistant]


def _assistant_provider_messages(message: dict[str, Any], *, source_index: int) -> list[dict[str, Any]]:
    content = _content_value(message.get("content"))
    tool_entries = _tool_entries(message)
    if any(_tool_entry_has_result(entry) for entry in tool_entries):
        return _assistant_history_messages(message, source_index=source_index)
    if not tool_entries:
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


def _tool_role_history_message(message: dict[str, Any], *, source_index: int) -> dict[str, Any]:
    content = _content_value(message.get("content"))
    if not _visible_text(content):
        return {}
    name = _tool_name_from_text(content) or _tool_name_from_metadata(message) or "unknown_tool"
    normalized = _base_message("assistant", _history_tool_result_text(name, content), source_index=source_index)
    _copy_optional(message, normalized, ("metadata",))
    metadata = dict(normalized.get("metadata") or {})
    metadata["kind"] = "historical_orphan_tool_result"
    metadata["toolName"] = name
    tool_call_id = str(message.get("tool_call_id") or message.get("toolCallId") or message.get("id") or "").strip()
    if tool_call_id:
        metadata["toolCallId"] = tool_call_id
    normalized["metadata"] = metadata
    return normalized


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


def _assistant_tool_calls_have_following_results(
    messages: list[Any],
    assistant_index: int,
    assistant_message: dict[str, Any],
) -> bool:
    tool_entries = _tool_entries(assistant_message)
    if not tool_entries or any(_tool_entry_has_result(entry) for entry in tool_entries):
        return False
    expected_ids: set[str] = set()
    for tool_index, entry in enumerate(tool_entries, start=1):
        normalized = _normalize_tool_call(entry, source_index=assistant_index, tool_index=tool_index)
        tool_call_id = str(normalized.get("id") or "").strip() if normalized else ""
        if tool_call_id:
            expected_ids.add(tool_call_id)
    if not expected_ids:
        return False
    seen_ids: set[str] = set()
    for raw in list(messages or [])[assistant_index + 1:]:
        if not isinstance(raw, dict) or _normalize_role(raw.get("role")) != "tool":
            break
        tool_call_id = str(raw.get("tool_call_id") or raw.get("toolCallId") or raw.get("id") or "").strip()
        content = _visible_text(raw.get("content"))
        if tool_call_id in expected_ids and content:
            seen_ids.add(tool_call_id)
    return expected_ids.issubset(seen_ids)


def _tool_entry_has_result(entry: dict[str, Any]) -> bool:
    for key in (
        "result",
        "error",
        "resultSegments",
        "stdoutPreview",
        "stderrPreview",
        "summary",
        "resultPreview",
        "result_preview",
        "status",
    ):
        if key in entry and entry.get(key) not in (None, "", [], {}):
            return True
    return False


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
        entry.get("resultPreview"),
        entry.get("result_preview"),
        entry.get("summary"),
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
        lines.append(f"status: {status}")
    for key in (
        "transportStatus",
        "semanticStatus",
        "exitCode",
        "timedOut",
        "failureClass",
        "resultKind",
        "truncated",
        "originalLength",
    ):
        if key in entry and entry.get(key) not in (None, ""):
            lines.append(f"{key}: {entry.get(key)}")
    lines.extend(["结果:", result_text])
    return "\n".join(lines)


def _history_tool_summary(name: str, entry: dict[str, Any]) -> str:
    result = _first_non_empty(
        entry.get("result"),
        entry.get("error"),
        entry.get("resultSegments"),
        entry.get("stdoutPreview"),
        entry.get("stderrPreview"),
        entry.get("resultPreview"),
        entry.get("result_preview"),
        entry.get("summary"),
    )
    status = str(entry.get("status") or "").strip()
    lines = [f"历史工具结果: {name}" if result not in (None, "") else f"历史工具调用未返回结果: {name}"]
    if status:
        lines.append(f"status: {status}")
    for key in (
        "transportStatus",
        "semanticStatus",
        "exitCode",
        "timedOut",
        "failureClass",
        "resultKind",
        "truncated",
        "originalLength",
    ):
        if key in entry and entry.get(key) not in (None, ""):
            lines.append(f"{key}: {entry.get(key)}")
    if result not in (None, ""):
        if isinstance(result, (list, dict)):
            result_text = json.dumps(result, ensure_ascii=False, sort_keys=True)
        else:
            result_text = str(result)
        if result_text.strip():
            lines.extend(["结果:", result_text])
    return "\n".join(lines)


def _history_tool_result_text(name: str, content: Any) -> str:
    text = _visible_text(content)
    if text.startswith("历史工具结果:"):
        return text
    return f"历史工具结果: {name}\n{text}".strip()


def _tool_name_from_text(content: Any) -> str:
    text = _visible_text(content)
    first_line = text.splitlines()[0].strip() if text.splitlines() else ""
    for marker in ("历史工具调用:", "历史工具调用：", "历史工具结果:", "历史工具结果："):
        if first_line.startswith(marker):
            return first_line[len(marker):].strip().split()[0] if first_line[len(marker):].strip() else ""
    return ""


def _tool_name_from_metadata(message: dict[str, Any]) -> str:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    return str(metadata.get("toolName") or metadata.get("tool_name") or "").strip()


def _join_text_blocks(parts: Iterable[Any]) -> str:
    return "\n\n".join(str(part or "").strip() for part in parts if str(part or "").strip())


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


def _dedupe_adjacent_semantic_messages(messages: list[Any]) -> list[Any]:
    deduped: list[Any] = []
    previous_key: tuple[str, str] | None = None
    for message in messages:
        if not isinstance(message, dict):
            deduped.append(message)
            previous_key = None
            continue
        key = (str(message.get("role") or ""), str(message.get("content") or ""))
        if key == previous_key:
            continue
        deduped.append(message)
        previous_key = key
    return deduped


def _repair_provider_tool_chain(messages: list[Any]) -> list[Any]:
    repaired: list[Any] = []
    pending_ids: list[str] = []
    pending_assistant_index = -1
    pending_result_indices: list[int] = []
    pending_tool_names: dict[str, str] = {}

    def clear_pending_chain() -> None:
        nonlocal pending_ids, pending_assistant_index, pending_result_indices, pending_tool_names
        pending_ids = []
        pending_assistant_index = -1
        pending_result_indices = []
        pending_tool_names = {}

    def demote_pending_chain() -> None:
        nonlocal pending_ids, pending_assistant_index, pending_result_indices, pending_tool_names
        if 0 <= pending_assistant_index < len(repaired):
            assistant = repaired[pending_assistant_index]
            if isinstance(assistant, dict) and assistant.get("role") == "assistant":
                tool_calls = list(assistant.get("tool_calls") or [])
                if tool_calls:
                    content_parts = [_visible_text(assistant.get("content"))]
                    for call in tool_calls:
                        name = _provider_tool_call_name(call)
                        content_parts.append(f"历史工具调用未返回结果: {name}")
                    demoted = dict(assistant)
                    demoted.pop("tool_calls", None)
                    demoted["content"] = _join_text_blocks(content_parts)
                    metadata = dict(demoted.get("metadata") or {})
                    metadata["kind"] = "historical_unresolved_tool_call"
                    metadata["repairedProviderToolChain"] = True
                    demoted["metadata"] = metadata
                    repaired[pending_assistant_index] = demoted
        for result_index in pending_result_indices:
            if 0 <= result_index < len(repaired):
                result_message = repaired[result_index]
                if isinstance(result_message, dict) and result_message.get("role") == "tool":
                    result_message = dict(result_message)
                    tool_call_id = str(result_message.get("tool_call_id") or "").strip()
                    tool_name = pending_tool_names.get(tool_call_id, "")
                    if tool_name:
                        metadata = dict(result_message.get("metadata") or {})
                        metadata.setdefault("toolName", tool_name)
                        result_message["metadata"] = metadata
                    repaired[result_index] = _tool_role_history_message(result_message, source_index=result_index)
        clear_pending_chain()

    for raw in list(messages or []):
        if not isinstance(raw, dict):
            if pending_ids:
                demote_pending_chain()
            repaired.append(raw)
            continue
        message = dict(raw)
        role = str(message.get("role") or "").strip().lower()
        if role == "assistant":
            if pending_ids:
                demote_pending_chain()
            repaired.append(message)
            tool_call_ids = _message_tool_call_ids(message)
            if tool_call_ids:
                pending_ids = list(tool_call_ids)
                pending_assistant_index = len(repaired) - 1
                pending_result_indices = []
                pending_tool_names = _message_tool_call_names(message)
            continue
        if role == "tool":
            tool_call_id = str(message.get("tool_call_id") or "").strip()
            if tool_call_id and tool_call_id in pending_ids:
                repaired.append(message)
                pending_result_indices.append(len(repaired) - 1)
                pending_ids = [item for item in pending_ids if item != tool_call_id]
                if not pending_ids:
                    clear_pending_chain()
                continue
            if pending_ids:
                demote_pending_chain()
            repaired.append(_tool_role_history_message(message, source_index=len(repaired)))
            continue
        if pending_ids:
            demote_pending_chain()
        repaired.append(message)
    if pending_ids:
        demote_pending_chain()
    return _dedupe_adjacent_semantic_messages(repaired)


def _message_tool_call_ids(message: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for index, call in enumerate(list(message.get("tool_calls") or [])):
        if not isinstance(call, dict):
            continue
        tool_call_id = str(call.get("id") or "").strip() or f"tool_{index}"
        ids.append(tool_call_id)
    return ids


def _message_tool_call_names(message: dict[str, Any]) -> dict[str, str]:
    names: dict[str, str] = {}
    for index, call in enumerate(list(message.get("tool_calls") or [])):
        if not isinstance(call, dict):
            continue
        tool_call_id = str(call.get("id") or "").strip() or f"tool_{index}"
        names[tool_call_id] = _provider_tool_call_name(call)
    return names


def _provider_tool_call_name(call: Any) -> str:
    if not isinstance(call, dict):
        return "unknown_tool"
    function = call.get("function") if isinstance(call.get("function"), dict) else {}
    return str(function.get("name") or call.get("name") or "").strip() or "unknown_tool"


__all__ = [
    "MODEL_MESSAGE_SCHEMA_VERSION",
    "normalize_model_history_messages",
    "normalize_model_messages",
    "normalize_provider_turn_messages",
]
