# -*- coding: utf-8 -*-
"""Project canonical model messages to provider-neutral OpenAI-style dicts."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage

from .streaming import extract_text_content


def normalize_messages_for_provider(messages: List[Any]) -> list[Any]:
    """Normalize persisted/UI messages before protocol-specific payload shaping."""

    from core.chat.model_messages import normalize_provider_turn_messages

    return normalize_provider_turn_messages(messages)


def message_to_openai_dict(
    message: Any,
    *,
    preserve_structured_content: bool = False,
    preserve_reasoning_content: bool = False,
) -> Dict[str, Any]:
    def content_value(value: Any) -> Any:
        if preserve_structured_content and isinstance(value, list):
            return value
        return extract_text_content(value)

    def maybe_attach_reasoning(payload: Dict[str, Any], value: Any) -> Dict[str, Any]:
        if not preserve_reasoning_content or payload.get("role") != "assistant":
            return payload
        reasoning_text = extract_text_content(value)
        if reasoning_text.strip():
            payload["reasoning_content"] = reasoning_text
        return payload

    if isinstance(message, SystemMessage):
        return {"role": "system", "content": content_value(message.content)}
    if isinstance(message, ToolMessage):
        payload = {"role": "tool", "content": content_value(message.content)}
        if getattr(message, "tool_call_id", None):
            payload["tool_call_id"] = message.tool_call_id
        return payload
    if isinstance(message, AIMessage):
        payload = {"role": "assistant", "content": content_value(message.content)}
        tool_calls = normalize_tool_calls(getattr(message, "tool_calls", []) or [])
        if tool_calls:
            payload["tool_calls"] = tool_calls
        additional_kwargs = getattr(message, "additional_kwargs", None) or {}
        return maybe_attach_reasoning(payload, additional_kwargs.get("reasoning_content"))
    if isinstance(message, BaseMessage):
        return {"role": getattr(message, "type", "user"), "content": content_value(getattr(message, "content", ""))}
    if isinstance(message, dict):
        role = str(message.get("role") or "user").strip().lower() or "user"
        payload = {"role": role, "content": content_value(message.get("content"))}
        if role == "assistant":
            tool_calls = normalize_tool_calls(message.get("tool_calls") or message.get("toolCalls") or [])
            if tool_calls:
                payload["tool_calls"] = tool_calls
        if role == "tool":
            tool_call_id = str(message.get("tool_call_id") or message.get("toolCallId") or message.get("id") or "").strip()
            if tool_call_id:
                payload["tool_call_id"] = tool_call_id
        reasoning = message.get("reasoning_content")
        if reasoning in (None, "") and isinstance(message.get("additional_kwargs"), dict):
            reasoning = message["additional_kwargs"].get("reasoning_content")
        return maybe_attach_reasoning(payload, reasoning)
    return {"role": "user", "content": content_value(message)}


def normalize_tool_calls(tool_calls: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for index, raw_tool in enumerate(tool_calls or []):
        if isinstance(raw_tool, dict):
            function = raw_tool.get("function") if isinstance(raw_tool.get("function"), dict) else None
            if function is not None:
                normalized.append(
                    {
                        "id": str(raw_tool.get("id") or raw_tool.get("tool_call_id") or raw_tool.get("toolCallId") or f"tool_{index}"),
                        "type": str(raw_tool.get("type") or "function"),
                        "function": {
                            "name": str(function.get("name") or raw_tool.get("name") or ""),
                            "arguments": (
                                function.get("arguments")
                                if isinstance(function.get("arguments"), str)
                                else json.dumps(function.get("arguments") or raw_tool.get("args") or {}, ensure_ascii=False)
                            ),
                        },
                    }
                )
                continue
            normalized.append(
                {
                    "id": str(raw_tool.get("id") or raw_tool.get("tool_call_id") or raw_tool.get("toolCallId") or f"tool_{index}"),
                    "type": "function",
                    "function": {
                        "name": str(raw_tool.get("name") or raw_tool.get("tool_name") or raw_tool.get("toolName") or ""),
                        "arguments": json.dumps(raw_tool.get("args") or raw_tool.get("arguments") or {}, ensure_ascii=False),
                    },
                }
            )
            continue
        normalized.append(
            {
                "id": f"tool_{index}",
                "type": "function",
                "function": {"name": "", "arguments": "{}"},
            }
        )
    return [item for item in normalized if str((item.get("function") or {}).get("name") or "").strip()]


__all__ = [
    "message_to_openai_dict",
    "normalize_messages_for_provider",
    "normalize_tool_calls",
]
