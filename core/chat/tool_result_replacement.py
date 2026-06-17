# -*- coding: utf-8 -*-
"""Compression-only replacement state for large tool results.

Normal conversation context keeps tool results intact. This helper is only for
context-compression paths where large tool payloads would otherwise dominate the
summary input and cache hash.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable


DEFAULT_TOOL_RESULT_REPLACEMENT_CHAR_LIMIT = 12_000


def empty_tool_result_replacement_state(*, char_limit: int = DEFAULT_TOOL_RESULT_REPLACEMENT_CHAR_LIMIT) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "mode": "compression_only",
        "charLimit": max(1, int(char_limit or DEFAULT_TOOL_RESULT_REPLACEMENT_CHAR_LIMIT)),
        "replacements": [],
    }


def replace_large_tool_results_for_compression(
    messages: Iterable[Any],
    *,
    char_limit: int = DEFAULT_TOOL_RESULT_REPLACEMENT_CHAR_LIMIT,
    session_id: str = "",
) -> tuple[list[Any], dict[str, Any]]:
    """Replace oversized tool-message contents with stable references.

    The returned state is metadata for the compression round, not a replacement
    for the canonical transcript. The original tool result remains recoverable
    from the persisted conversation or turn journal by ``tool_call_id``.
    """

    bounded_limit = max(1, int(char_limit or DEFAULT_TOOL_RESULT_REPLACEMENT_CHAR_LIMIT))
    state = empty_tool_result_replacement_state(char_limit=bounded_limit)
    replaced: list[Any] = []
    for index, message in enumerate(list(messages or [])):
        role = _message_role(message)
        semantic_tool_result = _is_semantic_tool_result(message)
        if role != "tool" and not semantic_tool_result:
            replaced.append(message)
            continue
        content = _message_content(message)
        replacement_basis = _semantic_tool_result_payload(content) if semantic_tool_result else content
        if len(replacement_basis) <= bounded_limit:
            replaced.append(message)
            continue
        tool_call_id = _message_tool_call_id(message) or f"tool_message_{index}"
        metadata = _message_metadata(message)
        tool_name = str(metadata.get("toolName") or metadata.get("tool_name") or "").strip()
        if not tool_name and semantic_tool_result:
            tool_name = _semantic_tool_name(content)
        digest = hashlib.sha256(replacement_basis.encode("utf-8", errors="replace")).hexdigest()
        reference = _replacement_reference(
            session_id=session_id,
            tool_call_id=tool_call_id,
            digest=digest,
        )
        replacement_content = _replacement_content(
            reference=reference,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            original_chars=len(replacement_basis),
            digest=digest,
            preview=_bounded_preview(replacement_basis, limit=min(800, bounded_limit)),
        )
        if semantic_tool_result:
            replacement_content = _semantic_replacement_content(content, replacement_content)
        state["replacements"].append(
            {
                "reference": reference,
                "toolCallId": tool_call_id,
                "toolName": tool_name,
                "messageIndex": index,
                "originalChars": len(replacement_basis),
                "sha256": digest,
            }
        )
        replaced.append(_with_replacement_content(message, replacement_content, reference))
    return replaced, state


def _message_role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role") or "").strip().lower()
    role = str(getattr(message, "type", "") or getattr(message, "role", "") or "").strip().lower()
    if role == "ai":
        return "assistant"
    return role


def _message_content(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


def _message_tool_call_id(message: Any) -> str:
    if isinstance(message, dict):
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        return str(
            message.get("tool_call_id")
            or message.get("toolCallId")
            or message.get("id")
            or metadata.get("toolCallId")
            or metadata.get("tool_call_id")
            or ""
        ).strip()
    return str(getattr(message, "tool_call_id", "") or "").strip()


def _message_metadata(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        metadata = message.get("metadata")
        return dict(metadata) if isinstance(metadata, dict) else {}
    metadata = getattr(message, "response_metadata", None)
    return dict(metadata) if isinstance(metadata, dict) else {}


def _is_semantic_tool_result(message: Any) -> bool:
    if _message_role(message) != "assistant":
        return False
    content = _message_content(message).lstrip()
    return content.startswith("历史工具结果:") or content.startswith("历史工具结果：")


def _semantic_tool_name(content: str) -> str:
    first_line = str(content or "").splitlines()[0].strip() if str(content or "").splitlines() else ""
    for marker in ("历史工具结果:", "历史工具结果："):
        if first_line.startswith(marker):
            return first_line[len(marker):].strip().split()[0] if first_line[len(marker):].strip() else ""
    return ""


def _semantic_tool_result_payload(content: str) -> str:
    lines = str(content or "").splitlines()
    if not lines:
        return ""
    for index, line in enumerate(lines):
        if line.strip() in {"结果:", "结果："}:
            return "\n".join(lines[index + 1:]).strip()
    return "\n".join(lines[1:]).strip()


def _semantic_replacement_content(content: str, replacement_content: str) -> str:
    lines = str(content or "").splitlines()
    if not lines:
        return replacement_content
    return "\n".join([lines[0].strip(), replacement_content]).strip()


def _with_replacement_content(message: Any, replacement_content: str, reference: str) -> Any:
    if isinstance(message, dict):
        updated = dict(message)
        metadata = dict(updated.get("metadata") or {}) if isinstance(updated.get("metadata"), dict) else {}
        metadata["toolResultReplacement"] = {"reference": reference, "mode": "compression_only"}
        updated["metadata"] = metadata
        updated["content"] = replacement_content
        return updated
    if _message_role(message) == "tool":
        try:
            from langchain_core.messages import ToolMessage

            kwargs: dict[str, Any] = {}
            for attr in ("name", "status", "artifact"):
                value = getattr(message, attr, None)
                if value not in (None, ""):
                    kwargs[attr] = value
            return ToolMessage(
                content=replacement_content,
                tool_call_id=_message_tool_call_id(message) or "tool_message",
                **kwargs,
            )
        except Exception:
            return message
    return message


def _replacement_reference(*, session_id: str, tool_call_id: str, digest: str) -> str:
    session_part = str(session_id or "session").strip().replace(":", "_")[:48] or "session"
    call_part = str(tool_call_id or "tool").strip().replace(":", "_")[:64] or "tool"
    return f"tool-result-ref:{session_part}:{call_part}:{digest[:16]}"


def _replacement_content(
    *,
    reference: str,
    tool_call_id: str,
    tool_name: str,
    original_chars: int,
    digest: str,
    preview: str,
) -> str:
    lines = [
        "[工具结果压缩引用]",
        f"引用: {reference}",
        f"工具调用ID: {tool_call_id}",
    ]
    if tool_name:
        lines.append(f"工具: {tool_name}")
    lines.extend(
        [
            f"原始字符数: {original_chars}",
            f"原始SHA256: {digest}",
            "说明: 原始工具结果仍保存在会话历史或 turn journal；需要完整内容时按 tool_call_id 或引用查询历史事件。",
        ]
    )
    if preview:
        lines.extend(["可读片段:", preview])
    return "\n".join(lines)


def _bounded_preview(content: str, *, limit: int) -> str:
    text = str(content or "").strip()
    if not text or limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    head = max(1, limit // 2)
    tail = max(1, limit - head)
    return f"{text[:head].rstrip()}\n...\n{text[-tail:].lstrip()}"


__all__ = [
    "DEFAULT_TOOL_RESULT_REPLACEMENT_CHAR_LIMIT",
    "empty_tool_result_replacement_state",
    "replace_large_tool_results_for_compression",
]
