# -*- coding: utf-8 -*-
"""Serialization, deserialization, and carryover helpers for Agent turn messages."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_jsonish(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, Mapping):
        return {key: _coerce_jsonish(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_coerce_jsonish(item) for item in value]
    return value


def _as_mapping(value: Any) -> Dict[str, Any]:
    value = _maybe_json(value)
    if isinstance(value, Mapping):
        return {key: _coerce_jsonish(val) for key, val in value.items()}
    return {}


def _maybe_json(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _coerce_message_list(value: Any) -> list:
    value = _maybe_json(value)
    if value is None or isinstance(value, (str, bytes, bytearray, memoryview)):
        return []
    if isinstance(value, Mapping):
        nested = value.get("messages")
        if nested is None:
            nested = value.get("items")
        if nested is None:
            nested = value.get("history")
        if nested is not None:
            return _coerce_message_list(nested)
        if any(key in value for key in ("kind", "role", "content", "type", "tool_calls", "toolCalls")):
            return [dict(value)]
        return []
    try:
        return list(value)
    except TypeError:
        return []


def _coerce_tool_call_list(value: Any) -> List[Dict[str, Any]]:
    value = _maybe_json(value)
    if value is None or isinstance(value, (str, bytes, bytearray, memoryview)):
        return []
    if isinstance(value, Mapping):
        nested = value.get("tool_calls")
        if nested is None:
            nested = value.get("toolCalls")
        if nested is not None:
            return _coerce_tool_call_list(nested)
        return [_as_mapping(value)] if value else []
    try:
        items = list(value)
    except TypeError:
        return []
    calls: List[Dict[str, Any]] = []
    for item in items:
        mapped = _as_mapping(item)
        if mapped:
            calls.append(mapped)
    return calls


def _coerce_content(value: Any) -> Any:
    return _coerce_jsonish(value)


def _message_kind(item: Mapping[str, Any]) -> str:
    kind = _coerce_text(item.get("kind")).strip().lower()
    if kind:
        return kind
    role = _coerce_text(item.get("role") or item.get("type")).strip().lower()
    if role in {"ai", "assistant"}:
        return "ai"
    if role == "tool":
        return "tool"
    if role == "system":
        return "system"
    if role in {"user", "human"} or "content" in item:
        return "dict"
    return ""


def serialize_turn_message(message: Any) -> Dict[str, Any]:
    message = _maybe_json(message)
    if isinstance(message, AIMessage):
        payload: Dict[str, Any] = {
            "kind": "ai",
            "content": _coerce_content(message.content),
            "tool_calls": _coerce_tool_call_list(getattr(message, "tool_calls", [])),
        }
        additional_kwargs = _as_mapping(getattr(message, "additional_kwargs", None))
        if additional_kwargs:
            payload["additional_kwargs"] = additional_kwargs
        response_metadata = _as_mapping(getattr(message, "response_metadata", None))
        if response_metadata:
            payload["response_metadata"] = response_metadata
        return payload
    if isinstance(message, ToolMessage):
        return {
            "kind": "tool",
            "content": _coerce_content(message.content),
            "tool_call_id": _coerce_text(getattr(message, "tool_call_id", "")).strip(),
        }
    if isinstance(message, SystemMessage):
        return {
            "kind": "system",
            "content": _coerce_content(message.content),
        }
    if isinstance(message, HumanMessage):
        return {
            "kind": "dict",
            "role": "user",
            "content": _coerce_content(message.content),
        }
    if isinstance(message, Mapping):
        payload = _as_mapping(message)
        payload["kind"] = "dict"
        if "content" in payload:
            payload["content"] = _coerce_content(payload.get("content"))
        return payload
    content = _coerce_content(getattr(message, "content", None))
    if content not in (None, ""):
        return {
            "kind": "system",
            "content": content,
        }
    return {}


def serialize_turn_messages(messages: Optional[List[Any]]) -> List[Dict[str, Any]]:
    serialized: List[Dict[str, Any]] = []
    for item in _coerce_message_list(messages):
        payload = serialize_turn_message(item)
        if payload:
            serialized.append(payload)
    return serialized


def deserialize_turn_messages(messages: List[Dict[str, Any]]) -> List[Any]:
    restored: List[Any] = []
    for raw in _coerce_message_list(messages):
        item = _as_mapping(raw)
        if not item:
            continue
        kind = _message_kind(item)
        if kind == "ai":
            restored.append(
                AIMessage(
                    content=_coerce_content(item.get("content", "")),
                    tool_calls=_coerce_tool_call_list(
                        item.get("tool_calls") if item.get("tool_calls") is not None else item.get("toolCalls")
                    ),
                    additional_kwargs=_as_mapping(
                        item.get("additional_kwargs")
                        if item.get("additional_kwargs") is not None
                        else item.get("additionalKwargs")
                    ),
                    response_metadata=_as_mapping(
                        item.get("response_metadata")
                        if item.get("response_metadata") is not None
                        else item.get("responseMetadata")
                    ),
                )
            )
            continue
        if kind == "tool":
            restored.append(
                ToolMessage(
                    content=_coerce_content(item.get("content", "")),
                    tool_call_id=_coerce_text(
                        item.get("tool_call_id") or item.get("toolCallId")
                    ).strip(),
                )
            )
            continue
        if kind == "system":
            restored.append(SystemMessage(content=_coerce_content(item.get("content", ""))))
            continue
        if kind == "dict":
            payload = dict(item)
            payload.pop("kind", None)
            if "content" in payload:
                payload["content"] = _coerce_content(payload.get("content"))
            restored.append(payload)
    return restored
