"""Conversation timeline projection for chat session messages.

This module intentionally projects from normalized conversation events to a
small, natural-language DTO. It does not expose raw tool protocol payloads.
"""

from __future__ import annotations

from typing import Any


TimelineStatus = str


def build_conversation_timeline_items(
    *,
    message_id: str,
    content: Any = "",
    feedback_events: Any = None,
    streaming: bool = False,
    lang: str = "zh",
    include_assistant_text: bool = True,
) -> list[dict[str, Any]]:
    events = _normalize_feedback_events(feedback_events)
    items: list[dict[str, Any]] = []
    command_buffer: list[dict[str, Any]] = []

    def flush_command_buffer() -> None:
        nonlocal command_buffer
        if not command_buffer:
            return
        if len(command_buffer) == 1:
            items.append(_operation_item(message_id, command_buffer[0], lang=lang))
        else:
            items.append(_command_group_item(message_id, command_buffer, lang=lang))
        command_buffer = []

    for event in events:
        kind = str(event.get("kind") or "").strip()
        if kind == "thought":
            flush_command_buffer()
            text = _event_text(event)
            if text:
                operation_id = _event_operation_id(message_id, event)
                items.append(
                    {
                        "id": f"{operation_id}-timeline-thought",
                        "kind": "thought",
                        "status": _timeline_status(event.get("status")),
                        "text": text,
                        "preview": _first_paragraph_preview(text),
                        "defaultExpanded": _is_running_status(event.get("status")),
                        "sourceOperationIds": [operation_id],
                        "operationIds": [operation_id],
                    }
                )
            continue
        if kind == "mental":
            continue
        if _is_command_like_event(event):
            command_buffer.append(event)
            continue
        flush_command_buffer()
        if kind == "status" and not str(event.get("error") or "").strip() and _timeline_status(event.get("status")) != "failed":
            continue
        items.append(_operation_item(message_id, event, lang=lang))

    flush_command_buffer()

    if include_assistant_text:
        text = str(content or "").strip()
        if text:
            items.append(
                {
                    "id": f"{message_id}-timeline-response",
                    "kind": "assistant_text",
                    "status": "running" if streaming else "completed",
                    "text": text,
                }
            )

    return _merge_adjacent_thought_items(items)


def _operation_item(message_id: str, event: dict[str, Any], *, lang: str) -> dict[str, Any]:
    operation_id = _event_operation_id(message_id, event)
    return {
        "id": f"{operation_id}-timeline-operation",
        "kind": "operation",
        "status": _timeline_status(event.get("status")),
        "title": _event_title(event, lang=lang),
        "summary": _event_summary(event),
        "sourceOperationIds": [operation_id],
        "operationIds": [operation_id],
    }


def _command_group_item(message_id: str, events: list[dict[str, Any]], *, lang: str) -> dict[str, Any]:
    status = (
        "failed"
        if any(_is_failed_status(event.get("status")) for event in events)
        else "running"
        if any(_is_running_status(event.get("status")) for event in events)
        else "completed"
    )
    command_count = len(events)
    if lang == "zh":
        title = f"正在运行 {command_count} 条命令" if status == "running" else f"已运行 {command_count} 条命令"
    else:
        title = f"Running {command_count} commands" if status == "running" else f"Ran {command_count} commands"
    first = events[0]
    last = events[-1]
    operation_ids = [_event_operation_id(message_id, event) for event in events]
    summary = "；".join(filter(None, (_event_summary(event) or _event_title(event, lang=lang) for event in events[:2])))
    return {
        "id": (
            f"{message_id}-timeline-command-group-"
            f"{_event_sequence_token(first)}-{_event_sequence_token(last)}"
        ),
        "kind": "command_group",
        "status": status,
        "title": title,
        "summary": summary,
        "sourceOperationIds": operation_ids,
        "operationIds": operation_ids,
    }


def _merge_adjacent_thought_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for item in items:
        previous = merged[-1] if merged else None
        if previous and previous.get("kind") == "thought" and item.get("kind") == "thought":
            text = _append_natural_text(previous.get("text") or "", item.get("text") or "")
            previous["text"] = text
            previous["preview"] = _first_paragraph_preview(text)
            previous["defaultExpanded"] = bool(previous.get("defaultExpanded") or item.get("defaultExpanded"))
            previous["status"] = "running" if item.get("status") == "running" else previous.get("status") or "completed"
            previous["sourceOperationIds"] = [
                *list(previous.get("sourceOperationIds") or []),
                *list(item.get("sourceOperationIds") or []),
            ]
            previous["operationIds"] = [
                *list(previous.get("operationIds") or []),
                *list(item.get("operationIds") or []),
            ]
            continue
        merged.append(item)
    return merged


def _normalize_feedback_events(value: Any) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, raw in enumerate(list(value or []), start=1):
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "").strip()
        if kind not in {"thought", "mental", "tool", "status"}:
            continue
        sequence = _coerce_positive_int(raw.get("sequence")) or index
        event = dict(raw)
        event["sequence"] = sequence
        event["kind"] = kind
        event["status"] = str(raw.get("status") or "done").strip() or "done"
        events.append(event)
    return sorted(events, key=lambda event: _coerce_positive_int(event.get("sequence")) or 0)[-120:]


def _event_operation_id(message_id: str, event: dict[str, Any]) -> str:
    return f"{message_id}-feedback-{_event_sequence_token(event)}"


def _event_sequence_token(event: dict[str, Any]) -> str:
    sequence = _coerce_positive_int(event.get("sequence"))
    if sequence:
        return str(sequence)
    return str(event.get("id") or "0").strip() or "0"


def _event_text(event: dict[str, Any]) -> str:
    return str(event.get("resultPreview") or event.get("result_preview") or event.get("summary") or "").strip()


def _event_summary(event: dict[str, Any]) -> str:
    text = str(event.get("summary") or event.get("resultPreview") or event.get("result_preview") or event.get("error") or "").strip()
    return _compact_preview(text, limit=180)


def _event_title(event: dict[str, Any], *, lang: str) -> str:
    kind = str(event.get("kind") or "").strip()
    if kind == "thought":
        return "思考" if lang == "zh" else "Thinking"
    if kind == "status":
        return _status_title(str(event.get("name") or "").strip(), lang=lang)
    return _tool_title(str(event.get("name") or event.get("label") or "tool").strip(), lang=lang)


def _status_title(name: str, *, lang: str) -> str:
    lower = name.lower().replace("-", "_")
    if lang == "zh":
        exact = {
            "context_prepare": "准备上下文",
            "agent_prepare": "绑定 Agent",
            "model_request": "请求模型",
            "model_thinking": "模型思考",
            "tool_call": "工具调用",
            "model_response": "生成回答",
        }
        return exact.get(lower) or (name.replace("_", " ").strip() or "运行状态")
    return name.replace("_", " ").strip().title() or "Runtime status"


def _tool_title(name: str, *, lang: str) -> str:
    lower = name.lower()
    if lang == "zh":
        exact = {
            "cli_tool": "命令",
            "grep_search_tool": "搜索",
            "read_file_tool": "读取文件",
            "glob_tool": "列出文件",
            "code_symbol_tool": "代码图谱",
            "get_git_status_summary_tool": "Git 状态",
            "image2_generate_tool": "生成图片",
            "web_search_tool": "网页搜索",
            "web_fetch_tool": "网页读取",
            "computer_use_task_tool": "沙盒浏览器",
        }
        if lower in exact:
            return exact[lower]
        if "search" in lower:
            return "搜索"
        if "read" in lower or "file" in lower:
            return "读取"
        if "git" in lower:
            return "Git"
        if "image" in lower:
            return "图片"
    return name or "tool"


def _is_command_like_event(event: dict[str, Any]) -> bool:
    if str(event.get("kind") or "").strip() != "tool":
        return False
    haystack = " ".join(
        str(event.get(key) or "").lower()
        for key in ("name", "label", "summary")
    )
    if any(marker in haystack for marker in ("apply_diff", "edit", "编辑", "computer_use", "image", "spawn_agent", "cli_agent")):
        return False
    return any(
        marker in haystack
        for marker in ("tool_", "cli_tool", "shell", "command", "命令", "grep_search_tool", "read_file_tool", "glob_tool", "rg", "搜索", "读取", "列出")
    )


def _timeline_status(status: Any) -> TimelineStatus:
    if _is_failed_status(status):
        return "failed"
    if _is_running_status(status):
        return "running"
    normalized = str(status or "").strip().lower()
    if normalized in {"queued", "pending"}:
        return "pending"
    return "completed"


def _is_running_status(status: Any) -> bool:
    return str(status or "").strip().lower() in {"running", "thinking", "tooling", "answering", "streaming", "pending"}


def _is_failed_status(status: Any) -> bool:
    return str(status or "").strip().lower() in {"failed", "error", "timeout", "cancelled", "timed_out"}


def _append_natural_text(previous: str, next_text: str) -> str:
    left = str(previous or "").rstrip()
    right = str(next_text or "").lstrip()
    if not left:
        return right
    if not right:
        return left
    if left.endswith(right):
        return left
    return f"{left}\n\n{right}"


def _first_paragraph_preview(text: str) -> str:
    for paragraph in str(text or "").split("\n\n"):
        candidate = paragraph.strip()
        if candidate:
            return _compact_preview(candidate, limit=180)
    return ""


def _compact_preview(text: str, *, limit: int) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return f"{value[:limit].rstrip()}..."


def _coerce_positive_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0
