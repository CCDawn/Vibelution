# -*- coding: utf-8 -*-
"""Safe LLM payload trace summaries.

This module keeps trace construction independent from web/session services.
Only bounded route, count, cache, protocol, and thinking facts belong here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


_ROUTE_KEYS = {"transport", "selectedProtocol", "protocolSource"}
_SHAPE_KEYS = {
    "inputItemCount",
    "messagePayloadCount",
    "toolDefinitionCount",
    "imageBlockCount",
    "hasTools",
    "usesResponsesPayload",
}
_CACHE_KEYS = {
    "promptCacheMode",
    "promptCacheEnabled",
    "promptCachePayloadEnabled",
    "promptCachePartitionHash",
    "promptCachePartitionChars",
    "cacheControlMessageCount",
}
_THINKING_KEYS = {"thinkingRequested", "thinkingType", "thinkingDisplay"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_dict(source: Mapping[str, Any] | None, keys: set[str]) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            result[key] = value
    return result


def _merge_summaries(summaries: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for summary in summaries or []:
        if not isinstance(summary, Mapping):
            continue
        merged.update({str(key): value for key, value in summary.items() if value not in (None, "")})
    return merged


def _message_roles(merged: Mapping[str, Any]) -> list[str]:
    roles = merged.get("messageRoles")
    if isinstance(roles, list):
        return [str(role or "").strip() for role in roles if str(role or "").strip()]
    return []


def _first_text(source: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(source.get(key) or "").strip()
        if value:
            return value
    return ""


def build_llm_payload_trace(
    *,
    phase: str,
    stream: bool,
    role: str,
    profile_id: str,
    provider: str,
    model: str,
    message_count: int,
    tool_count: int,
    metadata: Mapping[str, Any] | None,
    summaries: Iterable[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Build a bounded trace summary for one logical LLM payload."""

    merged = _merge_summaries(summaries)
    meta = metadata if isinstance(metadata, Mapping) else {}
    prompt_cache_source = {**merged, **meta}
    prompt_cache = _safe_dict(prompt_cache_source, _CACHE_KEYS)
    prompt_cache["promptCachePartitionChars"] = _safe_int(prompt_cache.get("promptCachePartitionChars"))

    trace = {
        "schemaVersion": 1,
        "traceId": uuid4().hex[:12],
        "recordedAt": _utc_now(),
        "phase": str(phase or "").strip(),
        "stream": bool(stream),
        "role": str(role or "").strip(),
        "profileId": str(profile_id or "").strip(),
        "provider": str(provider or "").strip(),
        "model": str(model or "").strip(),
        "sessionId": _first_text(meta, "sessionId", "session_id"),
        "turnId": _first_text(meta, "turnId", "turn_id", "llmRunId"),
        "agentId": _first_text(meta, "agentId", "agent_id"),
        "llmSlot": _first_text(meta, "llmSlot", "llm_slot"),
        "modelId": _first_text(meta, "llmModelId", "modelId", "model_id"),
        "promptPurpose": str(meta.get("promptPurpose") or "").strip(),
        "dialogueChainMode": str(meta.get("dialogueChainMode") or "").strip(),
        "messageCount": _safe_int(message_count),
        "toolCount": _safe_int(tool_count),
        "messageRoleCounts": dict(merged.get("messageRoleCounts") or {}),
        "messageRoles": _message_roles(merged),
        "imageBlockCount": _safe_int(merged.get("imageBlockCount")),
        "payloadShape": _safe_dict(merged, _SHAPE_KEYS),
        "promptCache": prompt_cache,
        "thinking": _safe_dict(merged, _THINKING_KEYS),
    }
    trace.update(_safe_dict(merged, _ROUTE_KEYS))
    return {key: value for key, value in trace.items() if value not in (None, "", {}, [])}


__all__ = ["build_llm_payload_trace"]
