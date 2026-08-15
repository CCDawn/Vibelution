# -*- coding: utf-8 -*-
"""Serialization, deserialization, and carryover helpers for Agent turn messages."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage


def serialize_turn_message(message: Any) -> Dict[str, Any]:
    if isinstance(message, AIMessage):
        payload: Dict[str, Any] = {
            "kind": "ai",
            "content": message.content,
            "tool_calls": list(getattr(message, "tool_calls", []) or []),
        }
        additional_kwargs = getattr(message, "additional_kwargs", None) or {}
        if additional_kwargs:
            payload["additional_kwargs"] = dict(additional_kwargs)
        response_metadata = getattr(message, "response_metadata", None) or {}
        if response_metadata:
            payload["response_metadata"] = dict(response_metadata)
        return payload
    if isinstance(message, ToolMessage):
        return {
            "kind": "tool",
            "content": message.content,
            "tool_call_id": str(getattr(message, "tool_call_id", "") or ""),
        }
    if isinstance(message, SystemMessage):
        return {
            "kind": "system",
            "content": message.content,
        }
    if isinstance(message, dict):
        payload = dict(message)
        payload["kind"] = "dict"
        return payload
    content = getattr(message, "content", None)
    if content not in (None, ""):
        return {
            "kind": "system",
            "content": content,
        }
    return {}


def serialize_turn_messages(messages: Optional[List[Any]]) -> List[Dict[str, Any]]:
    serialized: List[Dict[str, Any]] = []
    for item in list(messages or []):
        payload = serialize_turn_message(item)
        if payload:
            serialized.append(payload)
    return serialized


def deserialize_turn_messages(messages: List[Dict[str, Any]]) -> List[Any]:
    restored: List[Any] = []
    for item in list(messages or []):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        if kind == "ai":
            restored.append(
                AIMessage(
                    content=item.get("content", ""),
                    tool_calls=list(item.get("tool_calls") or []),
                    additional_kwargs=dict(item.get("additional_kwargs") or {}),
                    response_metadata=dict(item.get("response_metadata") or {}),
                )
            )
            continue
        if kind == "tool":
            restored.append(
                ToolMessage(
                    content=item.get("content", ""),
                    tool_call_id=str(item.get("tool_call_id") or ""),
                )
            )
            continue
        if kind == "system":
            restored.append(SystemMessage(content=item.get("content", "")))
            continue
        if kind == "dict":
            payload = dict(item)
            payload.pop("kind", None)
            restored.append(payload)
    return restored
