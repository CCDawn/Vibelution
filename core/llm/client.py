# -*- coding: utf-8 -*-
"""统一 LLM client。"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlparse

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, SystemMessage, ToolMessage

from config import AppConfig, get_config
from config.llm_security import is_llm_local_network_base_url
from core.context.volatility import is_volatile_context_text

from .adapters import get_provider_adapter
from .discovery import discover_model
from .errors import classify_exception
from .message_projector import message_to_openai_dict as project_message_to_openai_dict
from .message_projector import normalize_messages_for_provider
from .payload_builder import PayloadBuildInput, compose_runtime_wire_payload
from .payload_trace import build_llm_payload_trace
from .payload_validator import payload_protocol_summary
from .protocol_resolver import ProtocolResolutionError, resolve_model_protocol
from .protocols import WireProtocol
from .reasoning_extractor import extract_reasoning_text, strip_think_tag_reasoning
from .schema import sanitize_tool_schema
from .streaming import ResponsesStreamNormalizer, extract_message_tool_calls, extract_text_content
from .semantic_messages import SemanticGenerationSettings
from .semantic_projector import SemanticProjectionError, SemanticProjectionInput, project_semantic_request
from .types import LLMCapabilities, LLMError, StreamChunk, ToolCall, TurnOutcome, UsageStats
from .usage import read_usage_int as _read_provider_usage_int
from .usage import usage_stats_from_payload, usage_to_dict
from .wire.registry import build_default_wire_adapter_registry


_LLM_STATUS_CONTEXT: ContextVar[Dict[str, str]] = ContextVar(
    "vibelution_llm_status_context",
    default={},
)
_LLM_CANCEL_CHECKER_CONTEXT: ContextVar[Callable[[], str] | None] = ContextVar(
    "vibelution_llm_cancel_checker",
    default=None,
)
_LLM_ROUTE_CONCURRENCY_LIMIT = 2
_LLM_ROUTE_CONCURRENCY_LOCK = threading.Lock()
_LLM_ROUTE_CONCURRENCY_GATES: Dict[str, threading.BoundedSemaphore] = {}
_NO_PROXY_LOCK = threading.Lock()
_NO_PROXY_ENV_NAMES = ("NO_PROXY", "no_proxy")
_PROXY_ENV_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
_PROXY_ENV_CONDITION = threading.Condition(threading.RLock())
_PROXY_ENV_STATE = {"readers": 0, "writer": False}
PROMPT_CACHE_OPPORTUNITY_PREFIX_CHARS = 4096
_CANONICAL_WIRE_ADAPTERS = build_default_wire_adapter_registry()


def _safe_semantic_projection_snapshot(messages: List[Any]) -> Dict[str, Any]:
    shape_tail: list[dict[str, Any]] = []
    assistant_tool_calls = 0
    tool_results = 0
    for message in list(messages or []):
        role = str(
            (message.get("role") if isinstance(message, dict) else getattr(message, "type", ""))
            or ""
        ).strip().lower()
        role = {"ai": "assistant", "human": "user"}.get(role, role)
        tool_calls = (
            message.get("tool_calls") if isinstance(message, dict) else getattr(message, "tool_calls", None)
        ) or []
        assistant_tool_calls += len(tool_calls) if role == "assistant" else 0
        tool_results += 1 if role == "tool" else 0
        shape_tail.append({"role": role, "toolCallCount": len(tool_calls)})
    bounded_tail = shape_tail[-8:]
    shape_hash = hashlib.sha256(
        json.dumps(bounded_tail, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "payloadMessageAssistantToolCallCount": assistant_tool_calls,
        "payloadMessageToolResultCount": tool_results,
        "payloadMessageShapeHash": shape_hash,
        "payloadMessageShapeTail": bounded_tail,
    }


def _normalize_semantic_messages_with_adapter(messages: List[Any], adapter: Any) -> List[Any]:
    role_envelopes: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        raw_role = message.get("role") if isinstance(message, dict) else getattr(message, "type", "")
        role = {"ai": "assistant", "human": "user"}.get(
            str(raw_role or "").strip().lower(),
            str(raw_role or "").strip().lower(),
        )
        role_envelopes.append({"role": role, "messageIndex": index})
    normalized_roles = adapter.messages(role_envelopes)
    normalized_messages: list[Any] = []
    for index, message in enumerate(messages):
        original_role = str(role_envelopes[index].get("role") or "").strip().lower()
        normalized_role = str(normalized_roles[index].get("role") or original_role).strip().lower()
        if normalized_role == original_role:
            normalized_messages.append(message)
            continue
        if isinstance(message, dict):
            converted = dict(message)
            converted["role"] = normalized_role
        else:
            converted = {
                "role": normalized_role,
                "content": getattr(message, "content", ""),
            }
        normalized_messages.append(converted)
    return normalized_messages


class LLMCancelledError(Exception):
    """Raised when an active turn requests cancellation before more LLM work."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason or "LLM call cancelled.")
        self.reason = str(reason or "").strip()


def _find_ui_tool_calls_message_index(messages: List[Any]) -> int:
    for index, message in enumerate(list(messages or [])):
        if isinstance(message, dict) and "toolCalls" in message:
            return index
    return -1


def _current_llm_cancel_reason() -> str:
    checker = _LLM_CANCEL_CHECKER_CONTEXT.get(None)
    if not callable(checker):
        return ""
    try:
        return str(checker() or "").strip()
    except Exception:
        return ""


def _raise_if_llm_cancelled() -> None:
    reason = _current_llm_cancel_reason()
    if reason:
        raise LLMCancelledError(reason)


def _sleep_with_llm_cancel_check(wait_seconds: float) -> None:
    deadline = time.time() + max(0.0, float(wait_seconds or 0.0))
    while True:
        _raise_if_llm_cancelled()
        remaining = deadline - time.time()
        if remaining <= 0:
            return
        time.sleep(min(0.1, remaining))


def _llm_route_concurrency_key(provider: Any, profile: Any, *, profile_id: str) -> str:
    provider_kind = str(getattr(provider, "kind", "") or "").strip().lower() or "unknown"
    base_url = str(getattr(provider, "base_url", "") or "").strip().lower()
    model = str(getattr(profile, "model", "") or "").strip().lower() or "unknown"
    return "|".join((provider_kind, base_url, model, str(profile_id or "").strip()))


def _llm_route_concurrency_gate(route_key: str) -> threading.BoundedSemaphore:
    with _LLM_ROUTE_CONCURRENCY_LOCK:
        gate = _LLM_ROUTE_CONCURRENCY_GATES.get(route_key)
        if gate is None:
            gate = threading.BoundedSemaphore(_LLM_ROUTE_CONCURRENCY_LIMIT)
            _LLM_ROUTE_CONCURRENCY_GATES[route_key] = gate
        return gate


@contextmanager
def _reserve_llm_route_slot(
    route_key: str,
    *,
    role: str,
    profile_id: str,
    provider: str,
    model: str,
    phase: str,
    message_count: int,
    tool_count: int,
):
    gate = _llm_route_concurrency_gate(route_key)
    wait_started = time.time()
    acquired_immediately = gate.acquire(blocking=False)
    if not acquired_immediately:
        _record_llm_scene_event(
            "concurrency",
            "llm.concurrency.waiting",
            message="LLM route concurrency gate is waiting for a free slot.",
            outcome="waiting",
            fields={
                "role": role,
                "profileId": profile_id,
                "provider": provider,
                "model": model,
                "phase": phase,
                "routeKeyHash": _short_hash(route_key),
                "limit": _LLM_ROUTE_CONCURRENCY_LIMIT,
                "messageCount": message_count,
                "toolCount": tool_count,
            },
            lifecycle=False,
        )
        while not gate.acquire(timeout=0.1):
            _raise_if_llm_cancelled()
    wait_ms = int((time.time() - wait_started) * 1000)
    _publish_llm_status_event(
        "concurrency_acquired",
        profileId=profile_id,
        provider=provider,
        model=model,
        phase=phase,
        waitMs=wait_ms,
    )
    if wait_ms > 0:
        _record_llm_scene_event(
            "concurrency",
            "llm.concurrency.acquired",
            message="LLM route concurrency slot acquired.",
            outcome="acquired",
            fields={
                "role": role,
                "profileId": profile_id,
                "provider": provider,
                "model": model,
                "phase": phase,
                "routeKeyHash": _short_hash(route_key),
                "limit": _LLM_ROUTE_CONCURRENCY_LIMIT,
                "waitMs": wait_ms,
                "messageCount": message_count,
                "toolCount": tool_count,
            },
            lifecycle=False,
        )
    try:
        yield wait_ms
    finally:
        gate.release()
        _publish_llm_status_event(
            "concurrency_released",
            profileId=profile_id,
            provider=provider,
            model=model,
            phase=phase,
        )


@contextmanager
def llm_status_context(**fields: str):
    """Attach safe session breadcrumbs to LLM status events in this call context."""

    normalized = {
        str(key): str(value or "").strip()
        for key, value in fields.items()
        if str(value or "").strip()
    }
    token = _LLM_STATUS_CONTEXT.set(normalized)
    try:
        yield
    finally:
        _LLM_STATUS_CONTEXT.reset(token)


def _record_llm_scene_event(
    phase: str,
    event_code: str,
    *,
    message: str = "",
    level: str = "info",
    outcome: str = "observed",
    fields: Dict[str, Any] | None = None,
    lifecycle: bool = False,
) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "llm",
            phase,
            event_code,
            message=message or event_code,
            level=level,
            outcome=outcome,
            fields=fields or {},
            lifecycle=lifecycle,
        )
    except Exception:
        return


@contextmanager
def llm_cancel_context(checker: Callable[[], str] | None):
    token = _LLM_CANCEL_CHECKER_CONTEXT.set(checker if callable(checker) else None)
    try:
        yield
    finally:
        _LLM_CANCEL_CHECKER_CONTEXT.reset(token)


def _publish_llm_status_event(status: str, **fields: Any) -> None:
    """Publish a small LLM status breadcrumb for live session surfaces."""
    context = dict(_LLM_STATUS_CONTEXT.get({}) or {})
    payload = {
        "status": str(status or "").strip(),
        **context,
        **{key: value for key, value in fields.items() if value is not None},
    }
    try:
        from core.infrastructure.event_bus import EventNames, get_event_bus

        get_event_bus().publish(EventNames.LLM_STATUS, payload, source="LLMClient")
    except Exception:
        return


def _retry_policy_max_attempts(profile: Any) -> int:
    retry_policy = getattr(profile, "retry_policy", None)
    try:
        return max(1, min(5, int(getattr(retry_policy, "max_attempts", 5) or 5)))
    except Exception:
        return 5


def _retry_policy_backoff_seconds(profile: Any, attempt: int) -> float:
    retry_policy = getattr(profile, "retry_policy", None)
    try:
        base = float(getattr(retry_policy, "backoff_base_seconds", 2.0) or 2.0)
    except Exception:
        base = 2.0
    return max(0.1, base) * (2 ** max(0, attempt - 1))


def _llm_retry_event_fields(
    *,
    role: str,
    profile_id: str,
    provider: str,
    model: str,
    message_count: int,
    tool_count: int,
    metadata: Optional[Dict[str, Any]],
    attempt: int,
    max_attempts: int,
    llm_error: LLMError,
) -> Dict[str, Any]:
    safe_metadata = metadata or {}
    role_fields = {}
    if isinstance(safe_metadata, dict):
        for key in (
            "messageRoles",
            "messageRoleCounts",
            "protocol",
            "selectedProtocol",
            "protocolSource",
            "protocolWarnings",
            "reasoningRoundtripEnabled",
            "thinkingFormat",
            "toolChoiceMode",
            "strictMessageKeys",
            "requiresStringContent",
            "allowAssistantPrefill",
            "payloadValidationResult",
            "payloadValidationErrorType",
            "payloadPolicySystemMessagesConverted",
            "payloadPolicyStringContentMessages",
            "payloadPolicyReasoningContentStripped",
            "payloadPolicyEmptyAssistantPrefillRemoved",
            "payloadPolicyQwenThinkingParameter",
            "payloadPolicyMinimalToolSchema",
            "modelLibraryId",
            "capabilitySource",
            "declaredCapabilityFields",
        ):
            if key in safe_metadata:
                role_fields[key] = safe_metadata[key]
    return {
        "role": role,
        "profileId": profile_id,
        "provider": provider,
        "model": model,
        "messageCount": message_count,
        "toolCount": tool_count,
        **role_fields,
        "metadata": safe_metadata,
        "attempt": attempt,
        "maxAttempts": max_attempts,
        "errorType": llm_error.category,
        "retryable": llm_error.retryable,
        "error": str(llm_error),
    }


def _safe_message_role_summary(messages: List[Any]) -> Dict[str, Any]:
    roles: List[str] = []
    counts: Dict[str, int] = {}
    for message in list(messages or []):
        if isinstance(message, SystemMessage):
            role = "system"
        elif isinstance(message, ToolMessage):
            role = "tool"
        elif isinstance(message, AIMessage):
            role = "assistant"
        elif isinstance(message, dict):
            role = str(message.get("role") or "user").strip().lower() or "user"
        elif isinstance(message, BaseMessage):
            role = str(getattr(message, "type", "") or "user").strip().lower() or "user"
        else:
            role = "user"
        roles.append(role)
        counts[role] = counts.get(role, 0) + 1
    return {
        "messageRoles": roles,
        "messageRoleCounts": counts,
    }


def _payload_conversation_items(payload: Dict[str, Any]) -> List[Any]:
    for key in ("messages", "input"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _message_role_and_content(message: Any) -> tuple[str, Any]:
    def normalize_role(value: str) -> str:
        role = str(value or "user").strip().lower() or "user"
        return "user" if role == "human" else role

    if isinstance(message, SystemMessage):
        return "system", getattr(message, "content", None)
    if isinstance(message, ToolMessage):
        return "tool", getattr(message, "content", None)
    if isinstance(message, AIMessage):
        return "assistant", getattr(message, "content", None)
    if isinstance(message, dict):
        return normalize_role(str(message.get("role") or "user")), message.get("content")
    if isinstance(message, BaseMessage):
        return normalize_role(str(getattr(message, "type", "") or "user")), getattr(message, "content", None)
    return "user", str(message or "")


def _is_volatile_context_content(text: str) -> bool:
    return is_volatile_context_text(text)


def _safe_message_order_cache_summary(messages: List[Any]) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    digest_entries: List[Dict[str, Any]] = []
    first_volatile_index = -1
    last_user_index = -1
    stable_history_chars_before_volatile = 0
    volatile_chars_before_history = 0
    seen_history = False
    for index, message in enumerate(list(messages or [])):
        role, content = _message_role_and_content(message)
        text = extract_text_content(content)
        chars = len(text)
        volatile = _is_volatile_context_content(text)
        if role == "user":
            last_user_index = index
        is_history = role in {"user", "assistant", "tool"} and not volatile
        if index > 0 and is_history:
            seen_history = True
        if index > 0 and first_volatile_index < 0 and is_history:
            stable_history_chars_before_volatile += chars
        if volatile and not seen_history:
            volatile_chars_before_history += chars
        if volatile and first_volatile_index < 0:
            first_volatile_index = index
        entries.append(
            {
                "index": index,
                "role": role,
                "chars": chars,
                "volatileContext": volatile,
            }
        )
        digest_entries.append({"role": role, "content": content})
    if first_volatile_index >= 0:
        stable_prefix_boundary = first_volatile_index
        stable_prefix_end_reason = "before_volatile_context"
    elif last_user_index >= 0:
        stable_prefix_boundary = last_user_index
        stable_prefix_end_reason = "before_current_user"
    else:
        stable_prefix_boundary = len(digest_entries)
        stable_prefix_end_reason = "end_of_messages"
    stable_prefix_entries = digest_entries[: max(0, stable_prefix_boundary)]
    stable_prefix_chars = sum(_text_length(item.get("content")) for item in stable_prefix_entries)
    return {
        "messageOrderProfile": entries[:48],
        "promptCacheOrderDiagnostics": {
            "firstVolatileContextIndex": first_volatile_index,
            "lastUserIndex": last_user_index,
            "stableHistoryBeforeVolatileChars": stable_history_chars_before_volatile,
            "volatileContextBeforeHistoryChars": volatile_chars_before_history,
            "volatileContextBeforeHistory": bool(volatile_chars_before_history > 0),
            "stableCachePrefixMessageCount": len(stable_prefix_entries),
            "stableCachePrefixChars": stable_prefix_chars,
            "stableCachePrefixHash": _short_hash(stable_prefix_entries),
            "stableCachePrefixEndReason": stable_prefix_end_reason,
        },
    }


def _safe_capability_source_summary(resolved_spec: Any) -> Dict[str, Any]:
    details = getattr(resolved_spec, "provider_details", None)
    if not isinstance(details, dict):
        return {}
    summary: Dict[str, Any] = {}
    model_library_id = str(details.get("model_library_id") or "").strip()
    capability_source = str(details.get("capability_source") or "").strip()
    declared_fields = details.get("declared_capability_fields")
    if model_library_id:
        summary["modelLibraryId"] = model_library_id
    if capability_source:
        summary["capabilitySource"] = capability_source
    if isinstance(declared_fields, list):
        summary["declaredCapabilityFields"] = [
            str(item)
            for item in declared_fields
            if str(item or "").strip()
        ]
    return summary


def _short_hash(value: Any) -> str:
    try:
        if isinstance(value, str):
            raw = value
        else:
            raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        raw = str(value)
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def _text_length(value: Any) -> int:
    return len(extract_text_content(value))


def _content_blocks_have_cache_control(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    for block in value:
        if isinstance(block, dict) and block.get("cache_control"):
            return True
    return False


def _messages_have_prompt_cache_control(messages: List[Any]) -> bool:
    for message in list(messages or []):
        content: Any = None
        if isinstance(message, dict):
            content = message.get("content")
        elif isinstance(message, BaseMessage):
            content = getattr(message, "content", None)
        if _content_blocks_have_cache_control(content):
            return True
    return False


def _first_system_content_from_messages(messages: List[Any]) -> Any:
    for message in list(messages or []):
        role = ""
        content: Any = None
        if isinstance(message, SystemMessage):
            role = "system"
            content = getattr(message, "content", None)
        elif isinstance(message, dict):
            role = str(message.get("role") or "user").strip().lower() or "user"
            content = message.get("content")
        elif isinstance(message, BaseMessage):
            role = str(getattr(message, "type", "") or "user").strip().lower() or "user"
            content = getattr(message, "content", None)
        if role == "system":
            return content
    return None


def _cache_control_text_shape(content: Any) -> Dict[str, Any]:
    blocks = content if isinstance(content, list) else []
    cacheable_parts: List[str] = []
    dynamic_parts: List[str] = []
    cache_control_blocks = 0
    if blocks:
        for block in blocks:
            if not isinstance(block, dict):
                text = extract_text_content(block)
                if text:
                    dynamic_parts.append(text)
                continue
            text = extract_text_content(block.get("text") if "text" in block else block)
            if block.get("cache_control"):
                cache_control_blocks += 1
                if text:
                    cacheable_parts.append(text)
            elif text:
                dynamic_parts.append(text)
    elif content is not None:
        dynamic_parts.append(extract_text_content(content))

    cacheable_text = "\n\n".join(cacheable_parts)
    dynamic_text = "\n\n".join(dynamic_parts)
    first_system_text_chars = _text_length(content)
    cacheable_chars = len(cacheable_text)
    return {
        "firstSystemTextChars": first_system_text_chars,
        "firstSystemBlockCount": len(blocks),
        "firstSystemCacheControlBlockCount": cache_control_blocks,
        "firstSystemCacheableTextChars": cacheable_chars,
        "firstSystemDynamicTextChars": len(dynamic_text),
        "firstSystemCacheableTextRatio": round(cacheable_chars / first_system_text_chars, 4)
        if first_system_text_chars > 0
        else 0.0,
        "firstSystemCacheableHash": _short_hash(cacheable_text),
        "firstSystemDynamicHash": _short_hash(dynamic_text),
    }


def _safe_prompt_cache_design_summary(messages: List[Any], *, prompt_cache_mode: str) -> Dict[str, Any]:
    first_system_content = _first_system_content_from_messages(messages)
    shape = _cache_control_text_shape(first_system_content)
    mode = str(prompt_cache_mode or "").strip().lower()
    cacheable_chars = int(shape.get("firstSystemCacheableTextChars") or 0)
    first_system_cache_control_blocks = int(shape.get("firstSystemCacheControlBlockCount") or 0)
    first_system_dynamic_chars = int(shape.get("firstSystemDynamicTextChars") or 0)
    disabled_mode = mode in {"", "disabled"}
    cacheable_prefix_without_enabled_mode = (
        disabled_mode
        and bool(_messages_have_prompt_cache_control(messages))
        and cacheable_chars >= PROMPT_CACHE_OPPORTUNITY_PREFIX_CHARS
    )
    has_history_after_first_system = False
    for index, message in enumerate(list(messages or [])):
        if index <= 0:
            continue
        role, content = _message_role_and_content(message)
        text = extract_text_content(content)
        if role in {"user", "assistant", "tool"} and not _is_volatile_context_content(text):
            has_history_after_first_system = True
            break
    cacheable_prefix_break_reason = ""
    cacheable_prefix_ends_at = ""
    if first_system_cache_control_blocks > 0:
        if first_system_dynamic_chars > 0:
            cacheable_prefix_ends_at = "first_system_cache_control_block"
            cacheable_prefix_break_reason = (
                "dynamic_system_suffix_before_history"
                if has_history_after_first_system
                else "dynamic_system_suffix_in_first_system"
            )
        else:
            cacheable_prefix_ends_at = "first_system_message"
    return {
        "promptCacheDesign": {
            "mode": mode,
            "hasCacheControl": bool(_messages_have_prompt_cache_control(messages)),
            "cacheablePrefixWithoutEnabledMode": cacheable_prefix_without_enabled_mode,
            "cacheablePrefixOpportunityThresholdChars": PROMPT_CACHE_OPPORTUNITY_PREFIX_CHARS,
            "cacheablePrefixOpportunityReason": (
                "prompt_cache_mode_disabled"
                if cacheable_prefix_without_enabled_mode
                else ""
            ),
            "cacheablePrefixBreakReason": cacheable_prefix_break_reason,
            "cacheablePrefixEndsAt": cacheable_prefix_ends_at,
            "dynamicSystemSuffixOutsideCachePrefix": bool(first_system_dynamic_chars > 0),
            **shape,
        }
    }


def _safe_prompt_cache_payload_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    cache_key_field = ""
    cache_key = ""
    for field in ("prompt_cache_key", "promptCacheKey"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            cache_key_field = field
            cache_key = value.strip()
            break
    retention = payload.get("prompt_cache_retention") or payload.get("promptCacheRetention") or ""
    messages = _payload_conversation_items(payload)
    cache_control_blocks = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("cache_control"):
                cache_control_blocks += 1
    return {
        "promptCachePayload": {
            "keyField": cache_key_field,
            "keyHash": _short_hash(cache_key),
            "keyChars": len(cache_key),
            "retention": str(retention or "").strip(),
            "cacheControlBlockCount": cache_control_blocks,
        }
    }


def _usage_cache_observation_fields(usage: UsageStats) -> Dict[str, Any]:
    input_tokens = max(0, int(getattr(usage, "input_tokens", 0) or 0))
    cache_read_tokens = max(0, int(getattr(usage, "cached_input_tokens", 0) or 0))
    cache_creation_tokens = max(0, int(getattr(usage, "cache_creation_input_tokens", 0) or 0))
    if input_tokens:
        cache_read_tokens = min(cache_read_tokens, input_tokens)
        cache_creation_tokens = min(cache_creation_tokens, input_tokens)
    uncached_tokens = max(0, input_tokens - cache_read_tokens)
    return {
        "cachedInputTokens": cache_read_tokens,
        "cacheReadInputTokens": cache_read_tokens,
        "cacheCreationInputTokens": cache_creation_tokens,
        "uncachedInputTokens": uncached_tokens,
        "cacheHitRate": round(cache_read_tokens / input_tokens, 4) if input_tokens > 0 else 0.0,
    }


def _usage_observation_metadata(usage: UsageStats) -> Dict[str, Any]:
    cache_fields = _usage_cache_observation_fields(usage)
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "reasoning_output_tokens": usage.reasoning_output_tokens,
        "total_tokens": usage.total_tokens,
        "cached_input_tokens": cache_fields["cacheReadInputTokens"],
        "cache_read_input_tokens": cache_fields["cacheReadInputTokens"],
        "cache_creation_input_tokens": cache_fields["cacheCreationInputTokens"],
        "uncached_input_tokens": cache_fields["uncachedInputTokens"],
        "cache_hit_rate": cache_fields["cacheHitRate"],
    }


def _usage_missing_reason(usage: UsageStats) -> str:
    if not isinstance(getattr(usage, "provider_raw_usage", None), dict) or not usage.provider_raw_usage:
        return "provider_usage_missing"
    observed = (
        int(getattr(usage, "input_tokens", 0) or 0) > 0
        or int(getattr(usage, "output_tokens", 0) or 0) > 0
        or int(getattr(usage, "total_tokens", 0) or 0) > 0
        or int(getattr(usage, "cached_input_tokens", 0) or 0) > 0
        or int(getattr(usage, "cache_creation_input_tokens", 0) or 0) > 0
    )
    if observed:
        return ""
    return "provider_usage_without_token_counts"


def record_usage_event(event: Any) -> Any:
    from .usage_ledger import record_usage_event as write_usage_event

    return write_usage_event(event, timeout_seconds=0.05)


def _usage_ledger_event(**kwargs: Any) -> Any:
    from .usage_ledger import UsageLedgerEvent

    return UsageLedgerEvent(**kwargs)


def _estimate_messages_for_usage(messages: List[Any]) -> int:
    try:
        from tools.token_manager import estimate_messages_tokens

        return max(0, int(estimate_messages_tokens(messages) or 0))
    except Exception:
        return 0


def _estimate_text_for_usage(text: Any) -> int:
    content = extract_text_content(text)
    if not content:
        return 0
    try:
        from tools.token_manager import estimate_tokens_precise

        return max(0, int(estimate_tokens_precise(content) or 0))
    except Exception:
        return max(1, len(content) // 4)


def _usage_scope_kind(metadata: Dict[str, Any]) -> str:
    mode = str(metadata.get("mode") or metadata.get("runKind") or "").strip().lower()
    if str(metadata.get("teamId") or metadata.get("team_id") or "").strip():
        return "team_workflow"
    if "evolution" in mode:
        return "evolution"
    if str(metadata.get("sessionId") or metadata.get("session_id") or "").strip():
        return "chat_session"
    if str(metadata.get("agentId") or metadata.get("agent_id") or "").strip():
        return "agent_round"
    return "unknown"


def _usage_metadata_value(metadata: Dict[str, Any], camel_key: str, snake_key: str) -> str:
    return str(metadata.get(camel_key) or metadata.get(snake_key) or "").strip()


def _record_usage_ledger_event(
    *,
    usage: UsageStats,
    metadata: Optional[Dict[str, Any]],
    provider: str,
    model: str,
    profile_id: str,
    transport: str,
    context_window: int = 0,
    estimated_input_tokens: int = 0,
    estimated_output_tokens: int = 0,
) -> None:
    meta = metadata if isinstance(metadata, dict) else {}
    provider_usage = getattr(usage, "provider_raw_usage", {}) if usage is not None else {}
    provider_usage_keys = sorted(str(key) for key in provider_usage.keys()) if isinstance(provider_usage, dict) else []
    input_tokens = max(0, int(getattr(usage, "input_tokens", 0) or 0))
    output_tokens = max(0, int(getattr(usage, "output_tokens", 0) or 0))
    total_tokens = max(0, int(getattr(usage, "total_tokens", 0) or 0))
    if estimated_input_tokens or estimated_output_tokens:
        source = "estimated"
        input_tokens = max(input_tokens, max(0, int(estimated_input_tokens or 0)))
        output_tokens = max(output_tokens, max(0, int(estimated_output_tokens or 0)))
        total_tokens = input_tokens + output_tokens
    elif provider_usage and (input_tokens or output_tokens or total_tokens):
        source = "provider_usage"
    else:
        source = "missing"
        total_tokens = total_tokens or input_tokens + output_tokens
    cached_input_tokens = max(0, int(getattr(usage, "cached_input_tokens", 0) or 0))
    cache_creation_tokens = max(0, int(getattr(usage, "cache_creation_input_tokens", 0) or 0))
    if input_tokens:
        cached_input_tokens = min(cached_input_tokens, input_tokens)
        cache_creation_tokens = min(cache_creation_tokens, input_tokens)
    event = _usage_ledger_event(
        source=source,
        scope_kind=_usage_scope_kind(meta),
        session_id=_usage_metadata_value(meta, "sessionId", "session_id"),
        conversation_id=_usage_metadata_value(meta, "conversationId", "conversation_id"),
        turn_id=_usage_metadata_value(meta, "turnId", "turn_id"),
        agent_id=_usage_metadata_value(meta, "agentId", "agent_id"),
        team_id=_usage_metadata_value(meta, "teamId", "team_id"),
        provider=str(provider or "").strip(),
        model=str(model or "").strip(),
        profile_id=str(profile_id or "").strip(),
        transport=str(transport or "").strip(),
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_read_input_tokens=cached_input_tokens,
        cache_creation_input_tokens=cache_creation_tokens,
        uncached_input_tokens=max(0, input_tokens - cached_input_tokens),
        output_tokens=output_tokens,
        reasoning_output_tokens=max(0, int(getattr(usage, "reasoning_output_tokens", 0) or 0)),
        total_tokens=total_tokens or input_tokens + output_tokens,
        context_window=max(0, int(context_window or 0)),
        latency_ms=max(0, int(getattr(usage, "latency_ms", 0) or 0)),
        runtime_scene_id=_usage_metadata_value(meta, "runtimeSceneId", "runtime_scene_id"),
        provider_usage_keys=provider_usage_keys,
    )
    try:
        record_usage_event(event)
    except Exception as exc:
        _record_llm_scene_event(
            "usage",
            "llm.usage_ledger.write_failed",
            message="LLM usage ledger write failed.",
            level="warning",
            outcome="failed",
            fields={
                "errorType": type(exc).__name__,
                "profileId": str(profile_id or "").strip(),
                "provider": str(provider or "").strip(),
                "model": str(model or "").strip(),
            },
            lifecycle=False,
        )


def _strip_cache_control_from_content(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    stripped: List[Any] = []
    for block in value:
        if isinstance(block, dict) and "cache_control" in block:
            cleaned = dict(block)
            cleaned.pop("cache_control", None)
            stripped.append(cleaned)
        else:
            stripped.append(block)
    return stripped


def _strip_cache_control_from_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned_messages: List[Dict[str, Any]] = []
    for message in list(messages or []):
        if not isinstance(message, dict):
            cleaned_messages.append(message)
            continue
        cleaned = dict(message)
        cleaned["content"] = _strip_cache_control_from_content(cleaned.get("content"))
        cleaned_messages.append(cleaned)
    return cleaned_messages


def _safe_payload_shape_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    messages = _payload_conversation_items(payload)
    role_text_chars: Dict[str, int] = {}
    system_text_chars = 0
    non_system_text_chars = 0
    image_block_count = 0
    structured_content_message_count = 0
    first_system_content: Any = None

    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip().lower() or "user"
        content = message.get("content")
        text_chars = _text_length(content)
        role_text_chars[role] = role_text_chars.get(role, 0) + text_chars
        if role == "system":
            system_text_chars += text_chars
            if first_system_content is None:
                first_system_content = content
        else:
            non_system_text_chars += text_chars
        if isinstance(content, list):
            structured_content_message_count += 1
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = str(block.get("type") or "").strip().lower()
                if block_type in {"image_url", "input_image"} or block.get("image_url") or block.get("imageUrl"):
                    image_block_count += 1

    first_system_shape = _cache_control_text_shape(first_system_content)

    tools = payload.get("tools") if isinstance(payload.get("tools"), list) else []
    tool_names: List[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
        name = str(function.get("name") or tool.get("name") or "").strip()
        if name:
            tool_names.append(name)

    return {
        "payloadShape": {
            "messageTextCharsByRole": role_text_chars,
            "systemTextChars": system_text_chars,
            "nonSystemTextChars": non_system_text_chars,
            "structuredContentMessageCount": structured_content_message_count,
            "imageBlockCount": image_block_count,
            "firstSystemHash": _short_hash(first_system_content),
            **first_system_shape,
            "toolSchemaHash": _short_hash(tools) if tools else "",
            "toolNameHash": _short_hash(sorted(tool_names)) if tool_names else "",
        }
    }


def _safe_payload_route_summary(payload: Dict[str, Any], profile: Any, provider: Any) -> Dict[str, Any]:
    host = ""
    try:
        host = urlparse(str(getattr(provider, "base_url", "") or payload.get("base_url") or "")).hostname or ""
    except Exception:
        host = ""
    return {
        "runtimeRoute": str(payload.get("model") or ""),
        "transport": str(getattr(profile, "transport", "") or ""),
        "contract": str(getattr(profile, "contract", "") or ""),
        "baseUrlHost": host,
        "stream": bool(payload.get("stream")),
        "maxTokens": payload.get("max_tokens") if "max_tokens" in payload else payload.get("max_output_tokens"),
        "timeout": _safe_timeout_summary(payload.get("timeout")),
    }


def _safe_timeout_summary(timeout: Any) -> Any:
    if timeout is None or isinstance(timeout, (bool, int, float, str)):
        return timeout
    fields = {
        key: getattr(timeout, key, None)
        for key in ("connect", "read", "write", "pool")
        if getattr(timeout, key, None) is not None
    }
    if fields:
        return fields
    return str(timeout)


def _safe_payload_thinking_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    thinking = payload.get("thinking")
    reasoning = payload.get("reasoning")
    reasoning_summary = {
        "reasoningEffortRequested": isinstance(reasoning, dict) and bool(str(reasoning.get("effort") or "").strip()),
        "reasoningEffort": str(reasoning.get("effort") or "").strip() if isinstance(reasoning, dict) else "",
    }
    if not isinstance(thinking, dict):
        return {
            "thinkingRequested": False,
            "thinkingType": "",
            "thinkingDisplay": "",
            **reasoning_summary,
        }
    return {
        "thinkingRequested": True,
        "thinkingType": str(thinking.get("type") or "").strip(),
        "thinkingDisplay": str(thinking.get("display") or "").strip(),
        **reasoning_summary,
    }


def _read_usage_int(container: Any, *keys: str) -> int:
    return _read_provider_usage_int(container, *keys)


def _usage_to_dict(usage: Any) -> Dict[str, Any]:
    return usage_to_dict(usage)


def _with_retry_details(llm_error: LLMError, *, attempt: int, max_attempts: int) -> LLMError:
    details = dict(getattr(llm_error, "details", {}) or {})
    details.update(
        {
            "attempt": int(attempt),
            "max_attempts": int(max_attempts),
            "retry_budget_exhausted": int(attempt) >= int(max_attempts),
        }
    )
    llm_error.details = details
    return llm_error


def _looks_like_stream_usage_options_rejection(exc: Exception, llm_error: LLMError) -> bool:
    if llm_error.category not in {"provider_protocol_error", "capability_error", "empty_content_error"}:
        return False
    text = f"{type(exc).__name__} {exc} {llm_error}".lower()
    return "stream_options" in text or "stream options" in text or "include_usage" in text


def _llm_cancelled_error(reason: str) -> LLMError:
    return LLMError(
        "cancelled",
        reason or "当前 LLM 调用已按停止请求取消。",
        retryable=False,
        details={"stop_reason": reason or ""},
    )


def _ensure_no_proxy_for_local_base_url(base_url: Any) -> None:
    """Ensure local/private-LAN model endpoints bypass process proxy settings."""

    raw_base_url = str(base_url or "").strip()
    if not raw_base_url or not is_llm_local_network_base_url(raw_base_url):
        return
    host = (urlparse(raw_base_url).hostname or "").strip().lower().rstrip(".")
    if not host:
        return
    with _NO_PROXY_LOCK:
        for env_name in _NO_PROXY_ENV_NAMES:
            current = os.environ.get(env_name, "")
            parts = [part.strip() for part in current.split(",") if part.strip()]
            normalized = {part.lower().rstrip(".") for part in parts}
            if host in normalized:
                continue
            os.environ[env_name] = ",".join([*parts, host]) if parts else host


@contextmanager
def _llm_provider_proxy_env(config: Any, base_url: Any) -> Iterator[None]:
    """Bound provider proxy env to project config for the duration of one LLM call."""

    network_config = getattr(config, "network", None)
    proxy_enabled = bool(getattr(network_config, "proxy_enabled", False))
    proxy_url = str(getattr(network_config, "proxy_url", "") or "").strip()
    raw_base_url = str(base_url or "").strip()
    if is_llm_local_network_base_url(raw_base_url):
        _ensure_no_proxy_for_local_base_url(raw_base_url)
        yield
        return
    desired_proxy = proxy_url if proxy_enabled and proxy_url else None
    mode = "read"
    previous: Dict[str, str | None] = {}
    with _PROXY_ENV_CONDITION:
        while _PROXY_ENV_STATE["writer"]:
            _PROXY_ENV_CONDITION.wait()
        env_matches = all(os.environ.get(env_name) == desired_proxy for env_name in _PROXY_ENV_NAMES)
        if env_matches:
            _PROXY_ENV_STATE["readers"] += 1
        else:
            mode = "write"
            while _PROXY_ENV_STATE["writer"] or int(_PROXY_ENV_STATE["readers"]) > 0:
                _PROXY_ENV_CONDITION.wait()
            _PROXY_ENV_STATE["writer"] = True
            previous = {env_name: os.environ.get(env_name) for env_name in _PROXY_ENV_NAMES}
            if desired_proxy:
                for env_name in _PROXY_ENV_NAMES:
                    os.environ[env_name] = desired_proxy
            else:
                for env_name in _PROXY_ENV_NAMES:
                    os.environ.pop(env_name, None)
    try:
        yield
    finally:
        with _PROXY_ENV_CONDITION:
            if mode == "write":
                for env_name, value in previous.items():
                    if value is None:
                        os.environ.pop(env_name, None)
                    else:
                        os.environ[env_name] = value
                _PROXY_ENV_STATE["writer"] = False
            else:
                _PROXY_ENV_STATE["readers"] = max(0, int(_PROXY_ENV_STATE["readers"]) - 1)
            _PROXY_ENV_CONDITION.notify_all()


def _default_completion_backend(payload: Dict[str, Any]) -> Any:
    _raise_if_llm_cancelled()
    try:
        from litellm import completion
    except Exception as exc:  # pragma: no cover
        raise LLMError(
            "configuration_error",
            "LiteLLM 未安装，无法执行模型调用；请安装 litellm",
            retryable=False,
        ) from exc
    _ensure_no_proxy_for_local_base_url(payload.get("base_url"))
    return completion(**payload)


def _default_responses_backend(payload: Dict[str, Any]) -> Any:
    _raise_if_llm_cancelled()
    try:
        from litellm import responses
    except Exception as exc:  # pragma: no cover
        raise LLMError(
            "configuration_error",
            "LiteLLM 未安装或不支持 Responses API，无法执行模型调用；请安装支持 responses 的 litellm",
            retryable=False,
        ) from exc
    _ensure_no_proxy_for_local_base_url(payload.get("base_url"))
    request_payload = dict(payload)
    if request_payload.get("base_url") and not request_payload.get("api_base"):
        request_payload["api_base"] = request_payload["base_url"]
    request_payload.pop("base_url", None)
    return responses(**request_payload)


def _payload_uses_responses(payload: Dict[str, Any]) -> bool:
    return "input" in payload and "messages" not in payload


def _normalize_tool_calls(tool_calls: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for index, raw_tool in enumerate(tool_calls or []):
        if isinstance(raw_tool, dict):
            function = raw_tool.get("function") if isinstance(raw_tool.get("function"), dict) else None
            if function is not None:
                normalized.append(
                    {
                        "id": str(raw_tool.get("id") or f"tool_{index}"),
                        "type": str(raw_tool.get("type") or "function"),
                        "function": {
                            "name": str(function.get("name") or ""),
                            "arguments": (
                                function.get("arguments")
                                if isinstance(function.get("arguments"), str)
                                else json.dumps(function.get("arguments") or {}, ensure_ascii=False)
                            ),
                        },
                    }
                )
                continue
            normalized.append(
                {
                    "id": str(raw_tool.get("id") or f"tool_{index}"),
                    "type": "function",
                    "function": {
                        "name": str(raw_tool.get("name") or ""),
                        "arguments": json.dumps(raw_tool.get("args") or {}, ensure_ascii=False),
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
    return normalized


def _message_to_openai_dict(
    message: Any,
    *,
    preserve_structured_content: bool = False,
    preserve_reasoning_content: bool = False,
) -> Dict[str, Any]:
    return project_message_to_openai_dict(
        message,
        preserve_structured_content=preserve_structured_content,
        preserve_reasoning_content=preserve_reasoning_content,
    )


def _content_blocks_have_image(value: Any) -> bool:
    for block in list(value or []):
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "").strip().lower()
        if block_type in {"image_url", "input_image"}:
            return True
        if isinstance(block.get("image_url"), dict) or block.get("image_url") or block.get("imageUrl"):
            return True
    return False


def _convert_content_blocks_for_transport(content: Any, *, transport: str) -> Any:
    if not isinstance(content, list):
        return content
    normalized_transport = str(transport or "").strip().lower()
    if normalized_transport != "responses":
        return content
    converted: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            text = str(block or "").strip()
            if text:
                converted.append({"type": "input_text", "text": text})
            continue
        block_type = str(block.get("type") or "").strip().lower()
        if block_type in {"text", "input_text"}:
            converted.append({"type": "input_text", "text": str(block.get("text") or "").strip()})
            continue
        if block_type in {"image_url", "input_image"} or block.get("image_url") or block.get("imageUrl"):
            image_url = block.get("image_url")
            if isinstance(image_url, dict):
                image_url = image_url.get("url")
            image_url = image_url or block.get("imageUrl") or block.get("image_url")
            if image_url:
                converted.append({"type": "input_image", "image_url": str(image_url).strip()})
            continue
        converted.append(dict(block))
    return converted


def _tool_to_schema(tool: Any) -> Dict[str, Any]:
    if isinstance(tool, dict) and tool.get("type") == "function":
        return tool
    schema = getattr(tool, "args_schema", None)
    parameters = {"type": "object", "properties": {}, "required": []}
    if schema is not None and hasattr(schema, "model_json_schema"):
        parameters = schema.model_json_schema()
    return {
        "type": "function",
        "function": {
            "name": str(getattr(tool, "name", "")),
            "description": str(getattr(tool, "description", "")),
            "parameters": parameters,
        },
    }


class LLMClient:
    """项目统一 LLM client。"""

    def __init__(
        self,
        *,
        config: Optional[AppConfig] = None,
        role: str = "primary",
        profile_id: Optional[str] = None,
        bound_tools: Optional[List[Any]] = None,
        backend: Any = None,
        responses_backend: Any = None,
    ) -> None:
        self.config = config or get_config()
        self.role = role
        self.profile_id = profile_id or self.config.llm.get_role_profile_id(role)
        self.profile = self.config.llm.get_profile(self.profile_id)
        self.provider = self.config.llm.get_provider(self.profile.provider_id)
        self.bound_tools = list(bound_tools or [])
        self._backend = backend or _default_completion_backend
        self._responses_backend = responses_backend or backend or _default_responses_backend
        self.adapter = get_provider_adapter(self.provider, self.profile)
        self._resolved_spec = discover_model(self.config, self.profile_id)
        _model_id, model_entry = self.config.llm.get_model_library_entry_for_profile(self.profile)
        try:
            self.protocol_route = resolve_model_protocol(
                self.profile,
                self.provider,
                model_entry=model_entry if isinstance(model_entry, dict) else None,
            )
        except ProtocolResolutionError as exc:
            _record_llm_scene_event(
                "protocol",
                "llm.protocol.blocked",
                outcome="blocked",
                fields={
                    "providerId": exc.provider_id,
                    "modelRef": exc.model_ref,
                    "errorType": exc.code,
                },
            )
            raise LLMError(
                "provider_protocol_error",
                str(exc),
                retryable=False,
                provider=self.provider.provider_id,
                model=self.profile.model,
            ) from exc
        _record_llm_scene_event(
            "protocol",
            "llm.protocol.resolved",
            outcome="succeeded",
            fields=self.protocol_route.log_summary(),
        )
        self._last_payload_protocol_summary: Dict[str, Any] = {}

    @property
    def capabilities(self) -> LLMCapabilities:
        return self._resolved_spec.capabilities

    @property
    def resolved_spec(self):
        return self._resolved_spec

    def _required_wire_adapter(self):
        try:
            return _CANONICAL_WIRE_ADAPTERS.require(self.protocol_route)
        except LookupError as exc:
            route = self.protocol_route
            raise LLMError(
                "unsupported_wire_protocol",
                str(exc),
                retryable=False,
                provider=self.provider.kind,
                model=self.profile.model,
                details={
                    "profileId": self.profile_id,
                    "providerKind": self.provider.kind,
                    "modelId": route.model_id,
                    "wireProtocol": route.wire_protocol.value,
                    "adapterId": route.adapter_id,
                    "routeSource": route.wire_source,
                    "payloadValidationResult": "blocked_before_provider",
                },
            ) from exc

    def _project_semantic_request_or_raise(self, projection_input: SemanticProjectionInput):
        try:
            return project_semantic_request(projection_input)
        except SemanticProjectionError as exc:
            details = _safe_semantic_projection_snapshot(list(projection_input.messages))
            details.update(
                {
                    "messageIndex": exc.message_index,
                    "payloadValidationErrorType": exc.code,
                    "payloadValidationResult": "blocked_before_provider",
                }
            )
            raise LLMError(
                "payload_protocol_error",
                str(exc),
                retryable=False,
                provider=self.provider.kind,
                model=self.profile.model,
                details=details,
            ) from exc

    def bind_tools(self, tools: List[Any], *, binding_name: str = "default") -> "LLMClient":
        return LLMClient(
            config=self.config,
            role=self.role,
            profile_id=self.profile_id,
            bound_tools=list(tools or []),
            backend=self._backend,
            responses_backend=self._responses_backend,
        )

    def _build_payload(
        self,
        messages: List[Any],
        *,
        tools: Optional[List[Any]] = None,
        stream: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
        invocation_scope: Any = None,
    ) -> Dict[str, Any]:
        wire_adapter = self._required_wire_adapter()
        selected_tools = list(self.bound_tools)
        if tools is not None:
            selected_tools = list(tools or [])
        ui_tool_calls_index = _find_ui_tool_calls_message_index(list(messages or []))
        if ui_tool_calls_index >= 0:
            raise LLMError(
                "payload_protocol_error",
                "UI field `toolCalls` is not allowed in model input. Build model context from ConversationLedger ModelProjection first.",
                retryable=False,
                provider=self.provider.kind,
                model=self.profile.model,
                details={
                    "messageIndex": ui_tool_calls_index,
                    "requiredSource": "conversation_ledger_model_projection",
                    "forbiddenField": "toolCalls",
                },
            )
        provider_messages = _normalize_semantic_messages_with_adapter(
            normalize_messages_for_provider(list(messages or [])),
            self.adapter,
        )
        build_input = PayloadBuildInput(
            messages=provider_messages,
            tools=selected_tools,
            profile=self.profile,
            provider=self.provider,
            adapter=self.adapter,
            route=self.protocol_route,
            capabilities=self.capabilities,
            stream=stream,
            api_key=self.config.get_api_key_for_profile(profile_id=self.profile_id),
            profile_id=self.profile_id,
            config=self.config,
        )
        if self.protocol_route.wire_protocol in {
            WireProtocol.RESPONSES,
            WireProtocol.CHAT_COMPLETIONS,
        }:
            from .invocation import invocation_scope_from_metadata

            if selected_tools and (
                not self.capabilities.supports_tool_calling
                or not self.protocol_route.policy.allow_tools
            ):
                raise LLMError(
                    "capability_error",
                    f"profile `{self.profile_id}` 不支持 tool calling",
                    retryable=False,
                )
            semantic_request = self._project_semantic_request_or_raise(
                SemanticProjectionInput(
                    messages=tuple(provider_messages),
                    tools=tuple(selected_tools),
                    scope=invocation_scope or invocation_scope_from_metadata(metadata),
                    settings=SemanticGenerationSettings(
                        max_output_tokens=self.profile.max_output_tokens,
                        stream=stream,
                        tool_choice=(
                            "auto"
                            if self.protocol_route.policy.allow_explicit_tool_choice
                            and self.protocol_route.compat.tool_choice_mode != "omit"
                            else "omit"
                        ),
                    ),
                    tool_to_schema=lambda tool: (
                        sanitize_tool_schema(self.adapter.sanitize_tool_schema(_tool_to_schema(tool)))
                        if self.protocol_route.policy.tool_schema_policy == "minimal"
                        or self.protocol_route.compat.strict_message_keys
                        else self.adapter.sanitize_tool_schema(_tool_to_schema(tool))
                    ),
                    system_message_policy=self.protocol_route.policy.system_message_policy,
                    allow_assistant_prefill=self.protocol_route.policy.allow_assistant_prefill,
                    reasoning_roundtrip=self.protocol_route.compat.reasoning_roundtrip,
                )
            )
            wire_payload = wire_adapter.encode_request(semantic_request, route=self.protocol_route)
            built = compose_runtime_wire_payload(
                build_input,
                wire_payload=wire_payload,
                has_prompt_cache_control=_messages_have_prompt_cache_control(provider_messages),
            )
        else:
            raise AssertionError("registered wire adapter uses unsupported protocol")
        self._last_payload_protocol_summary = dict(built.summary or payload_protocol_summary(built.payload, self.protocol_route))
        return built.payload

    def _usage_from_response(self, response: Any, latency_ms: int) -> UsageStats:
        usage = getattr(response, "usage", None)
        if usage is None and isinstance(response, dict):
            usage = response.get("usage")
        return usage_stats_from_payload(usage, latency_ms=latency_ms)

    def _choice_message(self, response: Any) -> Dict[str, Any]:
        if isinstance(response, dict):
            choices = response.get("choices") or []
            return (choices[0] or {}).get("message") or {}
        choices = getattr(response, "choices", None) or []
        if not choices:
            return {}
        choice = choices[0]
        message = getattr(choice, "message", None)
        if message is None and isinstance(choice, dict):
            message = choice.get("message")
        if hasattr(message, "model_dump"):
            return message.model_dump()
        if isinstance(message, dict):
            return message
        if message is not None:
            return {
                "role": getattr(message, "role", "assistant"),
                "content": getattr(message, "content", ""),
                "tool_calls": getattr(message, "tool_calls", []),
            }
        return {}

    def _responses_message(self, response: Any) -> Dict[str, Any]:
        text = self._responses_text(response)
        return {"role": "assistant", "content": text, "tool_calls": []}

    def _responses_text(self, response: Any) -> str:
        if isinstance(response, dict):
            output_text = response.get("output_text")
            if isinstance(output_text, str):
                return output_text
            return self._responses_text_from_output(response.get("output"))
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str):
            return output_text
        return self._responses_text_from_output(getattr(response, "output", None))

    def _responses_text_from_output(self, output: Any) -> str:
        parts: List[str] = []
        for item in list(output or []):
            item_dict = self._provider_object_to_dict(item)
            if not isinstance(item_dict, dict):
                continue
            if isinstance(item_dict.get("text"), str):
                parts.append(item_dict.get("text") or "")
            content = item_dict.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                block_dict = self._provider_object_to_dict(block)
                if not isinstance(block_dict, dict):
                    continue
                text = block_dict.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)

    @staticmethod
    def _provider_object_to_dict(value: Any) -> Dict[str, Any] | None:
        if isinstance(value, dict):
            return value
        if hasattr(value, "model_dump"):
            dumped = value.model_dump()
            return dumped if isinstance(dumped, dict) else None
        if value is not None and hasattr(value, "__dict__"):
            return dict(getattr(value, "__dict__", {}) or {})
        return None

    def _decode_canonical_response(
        self,
        response: Any,
        metadata: Optional[Dict[str, Any]],
        invocation_scope: Any = None,
    ) -> Optional[TurnOutcome]:
        from .invocation import invocation_scope_from_metadata

        adapter = self._required_wire_adapter()
        return adapter.decode_response(
            response,
            route=self.protocol_route,
            scope=invocation_scope or invocation_scope_from_metadata(metadata),
        )

    @staticmethod
    def _canonical_compatibility_text(outcome: TurnOutcome) -> str:
        if outcome.kind == "final_answer":
            return outcome.final_text
        completed_by_item: Dict[str, Any] = {}
        for event in outcome.events:
            if event.kind == "item_completed" and event.phase == "commentary" and event.text:
                completed_by_item[event.item_id or str(event.sequence)] = event
        completed_text = "".join(event.text for event in completed_by_item.values())
        if completed_text:
            return completed_text
        return "".join(
            event.text
            for event in outcome.events
            if event.kind in {"interim_text_delta", "commentary_delta"} and event.text
        )

    @staticmethod
    def _canonical_compatibility_tool_calls(outcome: TurnOutcome) -> List[Dict[str, Any]]:
        return [
            {"id": call.call_id, "name": call.name, "args": dict(call.arguments)}
            for call in outcome.tool_calls
        ]

    def invoke(self, messages: List[Any], *, tools: Optional[List[Any]] = None, metadata: Optional[Dict[str, Any]] = None) -> AIMessage:
        from .invocation import invocation_scope_from_metadata

        start = time.time()
        invocation_scope = invocation_scope_from_metadata(metadata)
        payload = self._build_payload(
            messages,
            tools=tools,
            stream=False,
            metadata=metadata,
            invocation_scope=invocation_scope,
        )
        provider_conversation_items = _payload_conversation_items(payload) or messages
        message_role_summary = _safe_message_role_summary(provider_conversation_items)
        message_order_summary = _safe_message_order_cache_summary(provider_conversation_items)
        route_summary = _safe_payload_route_summary(payload, self.profile, self.provider)
        payload_shape_summary = _safe_payload_shape_summary(payload)
        prompt_cache_design_summary = _safe_prompt_cache_design_summary(
            messages,
            prompt_cache_mode=str(getattr(getattr(self.profile, "prompt_cache", None), "mode", "") or "disabled"),
        )
        prompt_cache_payload_summary = _safe_prompt_cache_payload_summary(payload)
        thinking_summary = _safe_payload_thinking_summary(payload)
        protocol_summary = dict(self._last_payload_protocol_summary or payload_protocol_summary(payload, self.protocol_route))
        capability_source_summary = _safe_capability_source_summary(self._resolved_spec)
        effective_tools = tools if tools is not None else self.bound_tools
        tool_count = len(effective_tools or [])
        event_metadata = {
            **(metadata or {}),
            **message_role_summary,
            **message_order_summary,
            **route_summary,
            **payload_shape_summary,
            **prompt_cache_design_summary,
            **prompt_cache_payload_summary,
            **thinking_summary,
            **protocol_summary,
            **capability_source_summary,
        }
        trace_metadata = {**dict(_LLM_STATUS_CONTEXT.get({}) or {}), **event_metadata}
        llm_payload_trace = build_llm_payload_trace(
            phase="invoke",
            stream=False,
            role=self.role,
            profile_id=self.profile_id,
            provider=self.provider.kind,
            model=self.profile.model,
            message_count=len(messages or []),
            tool_count=tool_count,
            metadata=trace_metadata,
            summaries=[
                message_role_summary,
                message_order_summary,
                route_summary,
                payload_shape_summary,
                prompt_cache_design_summary,
                prompt_cache_payload_summary,
                thinking_summary,
                protocol_summary,
                capability_source_summary,
            ],
        )
        _publish_llm_status_event(
            "payload_trace",
            traceId=llm_payload_trace.get("traceId"),
            llmPayloadTrace=llm_payload_trace,
        )
        response = self._invoke_backend_with_retry(
            payload,
            phase="invoke",
            event_code="llm.invoke.failed",
            message_count=len(messages or []),
            tool_count=tool_count,
            metadata=event_metadata,
        )
        turn_outcome = self._decode_canonical_response(
            response,
            metadata,
            invocation_scope=invocation_scope,
        )
        latency_ms = int((time.time() - start) * 1000)
        message = self._responses_message(response) if _payload_uses_responses(payload) else self._choice_message(response)
        tool_calls = extract_message_tool_calls(message)
        usage = self._usage_from_response(response, latency_ms)
        additional_kwargs = {"tool_calls_raw": [call.provider_payload for call in tool_calls]}
        reasoning = extract_reasoning_text(message, extract_text_content)
        reasoning_content = reasoning.text
        if reasoning_content.strip():
            additional_kwargs["reasoning_content"] = reasoning_content
        if turn_outcome is not None:
            additional_kwargs["turn_outcome"] = turn_outcome
        cache_observation_fields = _usage_cache_observation_fields(usage)
        estimated_input_tokens = 0
        estimated_output_tokens = 0
        if not (usage.input_tokens or usage.output_tokens or usage.total_tokens):
            estimated_input_tokens = _estimate_messages_for_usage(messages)
            estimated_output_tokens = _estimate_text_for_usage(message.get("content") or "")
        _record_usage_ledger_event(
            usage=usage,
            metadata=metadata,
            provider=self.provider.kind,
            model=self.profile.model,
            profile_id=self.profile_id,
            transport=str(protocol_summary.get("transport") or ""),
            context_window=max(0, int(getattr(self._resolved_spec, "context_window", 0) or 0)),
            estimated_input_tokens=estimated_input_tokens,
            estimated_output_tokens=estimated_output_tokens,
        )
        _record_llm_scene_event(
            "invoke",
            "llm.invoke.succeeded",
            message="LLM invoke succeeded.",
            outcome="succeeded",
            fields={
                "role": self.role,
                "profileId": self.profile_id,
                "provider": self.provider.kind,
                "model": self.profile.model,
                "messageCount": len(messages or []),
                "toolCount": tool_count,
                "toolCallCount": len(tool_calls),
                **route_summary,
                **message_role_summary,
                **message_order_summary,
                **payload_shape_summary,
                **prompt_cache_design_summary,
                **prompt_cache_payload_summary,
                **thinking_summary,
                **protocol_summary,
                **capability_source_summary,
                "llmPayloadTraceId": llm_payload_trace.get("traceId", ""),
                "inputTokens": usage.input_tokens,
                "outputTokens": usage.output_tokens,
                "reasoningOutputTokens": usage.reasoning_output_tokens,
                "totalTokens": usage.total_tokens,
                **cache_observation_fields,
                "reasoningSource": reasoning.source,
                "reasoningChars": len(reasoning_content),
                "reasoningObserved": bool(reasoning_content.strip()),
                "latencyMs": latency_ms,
                "metadata": metadata or {},
            },
            lifecycle=False,
        )
        return AIMessage(
            content=(
                self._canonical_compatibility_text(turn_outcome)
                if turn_outcome is not None
                else strip_think_tag_reasoning(message.get("content") or "", extract_text_content)
            ),
            tool_calls=(
                self._canonical_compatibility_tool_calls(turn_outcome)
                if turn_outcome is not None
                else [
                    {"id": call.id, "name": call.name, "args": call.arguments}
                    for call in tool_calls
                ]
            ),
            response_metadata={
                "role": self.role,
                "profile_id": self.profile_id,
                "provider": self.provider.kind,
                "model": self.profile.model,
                "usage": usage.provider_raw_usage,
                "usage_observation": _usage_observation_metadata(usage),
                "latency_ms": latency_ms,
                "capabilities": self.capabilities.__dict__,
                "llm_protocol": protocol_summary,
                "llm_capability_source": capability_source_summary,
                "metadata": metadata or {},
            },
            additional_kwargs=additional_kwargs,
        )

    def _response_metadata(self, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "role": self.role,
            "profile_id": self.profile_id,
            "provider": self.provider.kind,
            "model": self.profile.model,
            "llm_protocol": dict(self._last_payload_protocol_summary or self.protocol_route.log_summary()),
            "llm_capability_source": _safe_capability_source_summary(self._resolved_spec),
            "metadata": metadata or {},
        }

    def _invoke_payload_once(self, payload: Dict[str, Any]) -> Any:
        _raise_if_llm_cancelled()
        with _llm_provider_proxy_env(self.config, payload.get("base_url")):
            return self._backend_for_payload(payload)(payload)

    def _backend_for_payload(self, payload: Dict[str, Any]):
        return self._responses_backend if _payload_uses_responses(payload) else self._backend

    def _invoke_backend_with_retry(
        self,
        payload: Dict[str, Any],
        *,
        phase: str,
        event_code: str,
        message_count: int,
        tool_count: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        max_attempts = _retry_policy_max_attempts(self.profile)
        last_error: LLMError | None = None
        route_key = _llm_route_concurrency_key(self.provider, self.profile, profile_id=self.profile_id)
        for attempt in range(1, max_attempts + 1):
            try:
                _raise_if_llm_cancelled()
                with _reserve_llm_route_slot(
                    route_key,
                    role=self.role,
                    profile_id=self.profile_id,
                    provider=self.provider.kind,
                    model=self.profile.model,
                    phase=phase,
                    message_count=message_count,
                    tool_count=tool_count,
                ):
                    _raise_if_llm_cancelled()
                    with _llm_provider_proxy_env(self.config, payload.get("base_url")):
                        return self._backend_for_payload(payload)(payload)
            except LLMCancelledError as exc:
                raise _llm_cancelled_error(exc.reason) from exc
            except Exception as exc:
                llm_error = classify_exception(exc)
                llm_error = _with_retry_details(llm_error, attempt=attempt, max_attempts=max_attempts)
                last_error = llm_error
                error_category = llm_error.category
                fields = _llm_retry_event_fields(
                    role=self.role,
                    profile_id=self.profile_id,
                    provider=self.provider.kind,
                    model=self.profile.model,
                    message_count=message_count,
                    tool_count=tool_count,
                    metadata=metadata,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    llm_error=llm_error,
                )
                if not llm_error.retryable or attempt >= max_attempts:
                    _record_llm_scene_event(
                        phase,
                        event_code,
                        message=f"LLM {phase} failed{' before iterator' if phase == 'stream' else ''}: {error_category}",
                        level="error",
                        outcome="failed",
                        fields=fields,
                        lifecycle=True,
                    )
                    raise llm_error from exc
                wait_seconds = _retry_policy_backoff_seconds(self.profile, attempt)
                _record_llm_scene_event(
                    phase,
                    f"{event_code}.retrying",
                    message=f"LLM {phase} retrying after {error_category}.",
                    level="warning",
                    outcome="retrying",
                    fields={**fields, "nextAttempt": attempt + 1, "waitSeconds": wait_seconds},
                    lifecycle=True,
                )
                try:
                    _sleep_with_llm_cancel_check(wait_seconds)
                except LLMCancelledError as cancel_exc:
                    raise _llm_cancelled_error(cancel_exc.reason) from cancel_exc
        if last_error is not None:
            raise last_error
        raise LLMError("provider_protocol_error", "LLM backend failed before returning a response.", retryable=False)

    def _record_llm_retry_or_failure(
        self,
        *,
        phase: str,
        event_code: str,
        message: str,
        message_count: int,
        tool_count: int,
        metadata: Optional[Dict[str, Any]],
        attempt: int,
        max_attempts: int,
        llm_error: LLMError,
    ) -> bool:
        fields = _llm_retry_event_fields(
            role=self.role,
            profile_id=self.profile_id,
            provider=self.provider.kind,
            model=self.profile.model,
            message_count=message_count,
            tool_count=tool_count,
            metadata=metadata,
            attempt=attempt,
            max_attempts=max_attempts,
            llm_error=llm_error,
        )
        if not llm_error.retryable or attempt >= max_attempts:
            _record_llm_scene_event(
                phase,
                event_code,
                message=f"{message}: {llm_error.category}",
                level="error",
                outcome="failed",
                fields=fields,
                lifecycle=True,
            )
            _publish_llm_status_event(
                "failed",
                attempt=attempt,
                max_attempts=max_attempts,
                category=llm_error.category,
                retryable=llm_error.retryable,
            )
            return False
        wait_seconds = _retry_policy_backoff_seconds(self.profile, attempt)
        _record_llm_scene_event(
            phase,
            f"{event_code}.retrying",
            message=f"LLM {phase} retrying after {llm_error.category}.",
            level="warning",
            outcome="retrying",
            fields={**fields, "nextAttempt": attempt + 1, "waitSeconds": wait_seconds},
            lifecycle=True,
        )
        _publish_llm_status_event(
            "retrying",
            attempt=attempt,
            max_attempts=max_attempts,
            category=llm_error.category,
            next_attempt=attempt + 1,
            wait_seconds=wait_seconds,
        )
        try:
            _sleep_with_llm_cancel_check(wait_seconds)
        except LLMCancelledError as cancel_exc:
            raise _llm_cancelled_error(cancel_exc.reason) from cancel_exc
        return True

    def _stream_attempt(
        self,
        payload: Dict[str, Any],
        *,
        message_count: int,
        tool_count: int,
        metadata: Optional[Dict[str, Any]] = None,
        invocation_scope: Any = None,
    ) -> Tuple[Iterator[StreamChunk], Callable[[], bool]]:
        _raise_if_llm_cancelled()
        emitted = False

        def events() -> Iterator[StreamChunk]:
            nonlocal emitted
            iterator: Any = None
            normalized_iterator: Any = None
            with _llm_provider_proxy_env(self.config, payload.get("base_url")):
                iterator = self._backend_for_payload(payload)(payload)
                wire_adapter = self._required_wire_adapter()
                if wire_adapter is None:
                    raise AssertionError("required wire adapter returned None")
                else:
                    from .invocation import invocation_scope_from_metadata

                    provider_usage: UsageStats | None = None

                    def observed_wire_events() -> Iterator[Any]:
                        nonlocal provider_usage
                        for raw_event in iterator:
                            raw_dict = self._provider_object_to_dict(raw_event) or {}
                            response_dict = self._provider_object_to_dict(raw_dict.get("response")) or {}
                            raw_usage = raw_dict.get("usage") or response_dict.get("usage")
                            if raw_usage is not None:
                                provider_usage = usage_stats_from_payload(raw_usage)
                            yield raw_event

                    normalized_iterator = wire_adapter.decode_stream(
                        observed_wire_events(),
                        route=self.protocol_route,
                        scope=(invocation_scope or invocation_scope_from_metadata(metadata)),
                    )
                try:
                    if wire_adapter is None:
                        raise AssertionError("required wire adapter returned None")
                    else:
                        text_items_seen: set[str] = set()
                        canonical_usage: UsageStats | None = None
                        for event in normalized_iterator:
                            _raise_if_llm_cancelled()
                            projected: StreamChunk | None = None
                            item_key = event.item_id or f"sequence:{event.sequence}"
                            if event.kind in {"interim_text_delta", "commentary_delta", "answer_delta"}:
                                text_items_seen.add(item_key)
                                projected = StreamChunk(type="text_delta", text=event.text)
                            elif event.kind == "item_completed" and event.text and item_key not in text_items_seen:
                                text_items_seen.add(item_key)
                                projected = StreamChunk(type="text_delta", text=event.text)
                            elif event.kind == "reasoning_delta":
                                projected = StreamChunk(
                                    type="reasoning_delta",
                                    text=event.text,
                                    provider_payload={"reasoning_source": "canonical"},
                                )
                            elif event.kind == "usage_updated":
                                usage_summary = dict(event.diagnostic_summary)
                                canonical_usage = UsageStats(
                                    input_tokens=int(usage_summary.get("inputTokens") or 0),
                                    output_tokens=int(usage_summary.get("outputTokens") or 0),
                                    total_tokens=int(usage_summary.get("totalTokens") or 0),
                                    provider_raw_usage={
                                        "input_tokens": int(usage_summary.get("inputTokens") or 0),
                                        "output_tokens": int(usage_summary.get("outputTokens") or 0),
                                        "total_tokens": int(usage_summary.get("totalTokens") or 0),
                                    },
                                )
                            if projected is not None:
                                emitted = True
                                yield projected
                            _raise_if_llm_cancelled()
                        turn_outcome = normalized_iterator.outcome
                        if turn_outcome.tool_calls:
                            emitted = True
                            yield StreamChunk(
                                type="tool_call_final",
                                tool_calls=[
                                    ToolCall(
                                        id=call.call_id,
                                        name=call.name,
                                        arguments=dict(call.arguments),
                                        raw_arguments=json.dumps(dict(call.arguments), ensure_ascii=False),
                                    )
                                    for call in turn_outcome.tool_calls
                                ],
                            )
                        emitted = True
                        yield StreamChunk(
                            type="done",
                            usage=provider_usage or canonical_usage,
                            provider_payload={"turn_outcome": turn_outcome},
                        )
                except LLMCancelledError:
                    close = getattr(normalized_iterator, "close", None)
                    if callable(close):
                        close()
                    close = getattr(iterator, "close", None)
                    if callable(close):
                        close()
                    raise

        return events(), lambda: emitted

    def stream_events(
        self,
        messages: List[Any],
        *,
        tools: Optional[List[Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Iterator[StreamChunk]:
        """Yield normalized stream events independent of LangChain chunks."""
        from .invocation import invocation_scope_from_metadata

        invocation_scope = invocation_scope_from_metadata(metadata)
        payload = self._build_payload(
            messages,
            tools=tools,
            stream=True,
            metadata=metadata,
            invocation_scope=invocation_scope,
        )
        message_count = len(messages or [])
        effective_tools = tools if tools is not None else self.bound_tools
        tool_count = len(effective_tools or [])
        provider_conversation_items = _payload_conversation_items(payload) or messages
        message_role_summary = _safe_message_role_summary(provider_conversation_items)
        message_order_summary = _safe_message_order_cache_summary(provider_conversation_items)
        route_summary = _safe_payload_route_summary(payload, self.profile, self.provider)
        payload_shape_summary = _safe_payload_shape_summary(payload)
        prompt_cache_design_summary = _safe_prompt_cache_design_summary(
            messages,
            prompt_cache_mode=str(getattr(getattr(self.profile, "prompt_cache", None), "mode", "") or "disabled"),
        )
        prompt_cache_payload_summary = _safe_prompt_cache_payload_summary(payload)
        thinking_summary = _safe_payload_thinking_summary(payload)
        protocol_summary = dict(self._last_payload_protocol_summary or payload_protocol_summary(payload, self.protocol_route))
        capability_source_summary = _safe_capability_source_summary(self._resolved_spec)
        event_metadata = {
            **(metadata or {}),
            **message_role_summary,
            **message_order_summary,
            **route_summary,
            **payload_shape_summary,
            **prompt_cache_design_summary,
            **prompt_cache_payload_summary,
            **thinking_summary,
            **protocol_summary,
            **capability_source_summary,
        }
        trace_metadata = {**dict(_LLM_STATUS_CONTEXT.get({}) or {}), **event_metadata}
        llm_payload_trace = build_llm_payload_trace(
            phase="stream",
            stream=True,
            role=self.role,
            profile_id=self.profile_id,
            provider=self.provider.kind,
            model=self.profile.model,
            message_count=message_count,
            tool_count=tool_count,
            metadata=trace_metadata,
            summaries=[
                message_role_summary,
                message_order_summary,
                route_summary,
                payload_shape_summary,
                prompt_cache_design_summary,
                prompt_cache_payload_summary,
                thinking_summary,
                protocol_summary,
                capability_source_summary,
            ],
        )
        _publish_llm_status_event(
            "payload_trace",
            traceId=llm_payload_trace.get("traceId"),
            llmPayloadTrace=llm_payload_trace,
        )
        max_attempts = _retry_policy_max_attempts(self.profile)
        last_error: LLMError | None = None
        stream_usage_options_downgraded = False
        route_key = _llm_route_concurrency_key(self.provider, self.profile, profile_id=self.profile_id)
        for attempt in range(1, max_attempts + 1):
            try:
                _raise_if_llm_cancelled()
            except LLMCancelledError as exc:
                raise _llm_cancelled_error(exc.reason) from exc
            start = time.time()
            emitted = False
            chunk_count = 0
            text_delta_count = 0
            reasoning_delta_count = 0
            reasoning_chars = 0
            reasoning_sources: set[str] = set()
            tool_call_count = 0
            first_chunk_ms: int | None = None
            first_text_delta_ms: int | None = None
            first_reasoning_delta_ms: int | None = None
            previous_chunk_at: float | None = None
            max_inter_chunk_ms = 0
            total_inter_chunk_ms = 0
            inter_chunk_count = 0
            usage_observation = UsageStats()
            generated_text_parts: list[str] = []
            try:
                _record_llm_scene_event(
                    "stream",
                    "llm.stream.started",
                    message="LLM stream started.",
                    outcome="running",
                    fields={
                        "role": self.role,
                        "profileId": self.profile_id,
                        "provider": self.provider.kind,
                        "model": self.profile.model,
                        "messageCount": message_count,
                        "toolCount": tool_count,
                        **event_metadata,
                        "llmPayloadTraceId": llm_payload_trace.get("traceId", ""),
                        "attempt": attempt,
                        "maxAttempts": max_attempts,
                    },
                    lifecycle=False,
                )
                with _reserve_llm_route_slot(
                    route_key,
                    role=self.role,
                    profile_id=self.profile_id,
                    provider=self.provider.kind,
                    model=self.profile.model,
                    phase="stream",
                    message_count=message_count,
                    tool_count=tool_count,
                ):
                    _raise_if_llm_cancelled()
                    events, emitted_fn = self._stream_attempt(
                        payload,
                        message_count=message_count,
                        tool_count=tool_count,
                        metadata=metadata,
                        invocation_scope=invocation_scope,
                    )
                    for event in events:
                        _raise_if_llm_cancelled()
                        now = time.time()
                        elapsed_ms = int((now - start) * 1000)
                        if first_chunk_ms is None:
                            first_chunk_ms = elapsed_ms
                        if previous_chunk_at is not None:
                            inter_chunk_ms = int((now - previous_chunk_at) * 1000)
                            max_inter_chunk_ms = max(max_inter_chunk_ms, inter_chunk_ms)
                            total_inter_chunk_ms += inter_chunk_ms
                            inter_chunk_count += 1
                        previous_chunk_at = now
                        emitted = emitted_fn()
                        chunk_count += 1
                        if event.type == "text_delta":
                            text_delta_count += 1
                            generated_text_parts.append(event.text or "")
                            if first_text_delta_ms is None and (event.text or ""):
                                first_text_delta_ms = elapsed_ms
                        elif event.type == "reasoning_delta":
                            reasoning_delta_count += 1
                            if first_reasoning_delta_ms is None and (event.text or ""):
                                first_reasoning_delta_ms = elapsed_ms
                            reasoning_chars += len(event.text or "")
                            if isinstance(event.provider_payload, dict):
                                source = str(event.provider_payload.get("reasoning_source") or "").strip()
                                if source:
                                    reasoning_sources.add(source)
                        elif event.type == "tool_call_final":
                            tool_call_count += len(event.tool_calls or [])
                        elif event.type == "done" and event.usage is not None:
                            usage_observation = event.usage
                        yield event
                        _raise_if_llm_cancelled()
                usage_observation.latency_ms = int((time.time() - start) * 1000)
                estimated_input_tokens = 0
                estimated_output_tokens = 0
                if not (
                    usage_observation.input_tokens
                    or usage_observation.output_tokens
                    or usage_observation.total_tokens
                ):
                    estimated_input_tokens = _estimate_messages_for_usage(messages)
                    estimated_output_tokens = _estimate_text_for_usage("".join(generated_text_parts))
                _record_usage_ledger_event(
                    usage=usage_observation,
                    metadata=metadata,
                    provider=self.provider.kind,
                    model=self.profile.model,
                    profile_id=self.profile_id,
                    transport=str(event_metadata.get("transport") or ""),
                    context_window=max(0, int(getattr(self._resolved_spec, "context_window", 0) or 0)),
                    estimated_input_tokens=estimated_input_tokens,
                    estimated_output_tokens=estimated_output_tokens,
                )
                usage_observed = (
                    bool(usage_observation.provider_raw_usage)
                    and (
                        usage_observation.input_tokens > 0
                        or usage_observation.output_tokens > 0
                        or usage_observation.total_tokens > 0
                        or usage_observation.cached_input_tokens > 0
                        or usage_observation.cache_creation_input_tokens > 0
                    )
                )
                cache_observation_fields = _usage_cache_observation_fields(usage_observation)
                usage_missing_reason = "" if usage_observed else _usage_missing_reason(usage_observation)
                _record_llm_scene_event(
                    "stream",
                    "llm.stream.succeeded",
                    message="LLM stream succeeded.",
                    outcome="succeeded",
                    fields={
                        "role": self.role,
                        "profileId": self.profile_id,
                        "provider": self.provider.kind,
                        "model": self.profile.model,
                        "usageObserved": usage_observed,
                        "usageMissingReason": usage_missing_reason,
                        "inputTokens": usage_observation.input_tokens,
                        "outputTokens": usage_observation.output_tokens,
                        "reasoningOutputTokens": usage_observation.reasoning_output_tokens,
                        "totalTokens": usage_observation.total_tokens,
                        **cache_observation_fields,
                        "latencyMs": usage_observation.latency_ms,
                        "messageCount": message_count,
                        "toolCount": tool_count,
                        **event_metadata,
                        "llmPayloadTraceId": llm_payload_trace.get("traceId", ""),
                        "chunkCount": chunk_count,
                        "textDeltaCount": text_delta_count,
                        "reasoningDeltaCount": reasoning_delta_count,
                        "reasoningChars": reasoning_chars,
                        "reasoningSources": sorted(reasoning_sources),
                        "reasoningObserved": reasoning_chars > 0,
                        "firstChunkMs": first_chunk_ms,
                        "firstTextDeltaMs": first_text_delta_ms,
                        "firstReasoningDeltaMs": first_reasoning_delta_ms,
                        "maxInterChunkMs": max_inter_chunk_ms,
                        "avgInterChunkMs": int(total_inter_chunk_ms / inter_chunk_count)
                        if inter_chunk_count > 0
                        else 0,
                        "interChunkCount": inter_chunk_count,
                        "toolCallCount": tool_call_count,
                    },
                    lifecycle=False,
                )
                return
            except LLMCancelledError as exc:
                llm_error = _llm_cancelled_error(exc.reason)
                _record_llm_scene_event(
                    "stream",
                    "llm.stream.cancelled",
                    message="LLM stream cancelled by turn stop request.",
                    level="warning",
                    outcome="cancelled",
                    fields=_llm_retry_event_fields(
                        role=self.role,
                        profile_id=self.profile_id,
                        provider=self.provider.kind,
                        model=self.profile.model,
                        message_count=message_count,
                        tool_count=tool_count,
                        metadata=event_metadata,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        llm_error=llm_error,
                    ),
                    lifecycle=True,
                )
                _publish_llm_status_event(
                    "cancelled",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    category=llm_error.category,
                    retryable=False,
                )
                raise llm_error from exc
            except Exception as exc:
                llm_error = classify_exception(exc)
                llm_error = _with_retry_details(llm_error, attempt=attempt, max_attempts=max_attempts)
                last_error = llm_error
                if emitted:
                    _record_llm_scene_event(
                        "stream",
                        "llm.stream.failed",
                        message=f"LLM stream failed: {llm_error.category}",
                        level="error",
                        outcome="failed",
                        fields=_llm_retry_event_fields(
                            role=self.role,
                            profile_id=self.profile_id,
                            provider=self.provider.kind,
                            model=self.profile.model,
                            message_count=message_count,
                            tool_count=tool_count,
                            metadata=event_metadata,
                            attempt=attempt,
                            max_attempts=max_attempts,
                            llm_error=llm_error,
                        ),
                        lifecycle=True,
                    )
                    raise llm_error from exc
                if (
                    not stream_usage_options_downgraded
                    and payload.get("stream_options")
                    and _looks_like_stream_usage_options_rejection(exc, llm_error)
                ):
                    payload = dict(payload)
                    payload.pop("stream_options", None)
                    route_summary = _safe_payload_route_summary(payload, self.profile, self.provider)
                    payload_shape_summary = _safe_payload_shape_summary(payload)
                    event_metadata = {
                        **message_role_summary,
                        **route_summary,
                        **payload_shape_summary,
                        **prompt_cache_design_summary,
                        **_safe_prompt_cache_payload_summary(payload),
                        **_safe_payload_thinking_summary(payload),
                        **protocol_summary,
                        **capability_source_summary,
                        "streamUsageOptionsDowngraded": True,
                    }
                    stream_usage_options_downgraded = True
                    _record_llm_scene_event(
                        "stream",
                        "llm.stream.usage_options_downgraded",
                        message="LLM stream usage options were rejected; retrying without stream_options.",
                        level="warning",
                        outcome="retrying",
                        fields=_llm_retry_event_fields(
                            role=self.role,
                            profile_id=self.profile_id,
                            provider=self.provider.kind,
                            model=self.profile.model,
                            message_count=message_count,
                            tool_count=tool_count,
                            metadata=event_metadata,
                            attempt=attempt,
                            max_attempts=max_attempts,
                            llm_error=llm_error,
                        ),
                        lifecycle=True,
                    )
                    continue
                should_retry = self._record_llm_retry_or_failure(
                    phase="stream",
                    event_code="llm.stream.failed",
                    message="LLM stream failed before iterator",
                    message_count=message_count,
                    tool_count=tool_count,
                    metadata=event_metadata,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    llm_error=llm_error,
                )
                if not should_retry:
                    raise llm_error from exc

    def stream(self, messages: List[Any], *, tools: Optional[List[Any]] = None, metadata: Optional[Dict[str, Any]] = None) -> Iterator[AIMessageChunk]:
        for event in self.stream_events(messages, tools=tools, metadata=metadata):
            response_metadata = self._response_metadata(metadata)
            if event.type == "done":
                turn_outcome = (event.provider_payload or {}).get("turn_outcome")
                if event.usage is not None or turn_outcome is not None:
                    done_metadata = dict(response_metadata)
                    additional_kwargs = {}
                    if event.usage is not None:
                        done_metadata["usage"] = event.usage.provider_raw_usage
                        done_metadata["usage_observation"] = _usage_observation_metadata(event.usage)
                    if turn_outcome is not None:
                        additional_kwargs["turn_outcome"] = turn_outcome
                    yield AIMessageChunk(
                        content="",
                        additional_kwargs=additional_kwargs,
                        response_metadata=done_metadata,
                    )
                continue
            if event.type == "text_delta":
                yield AIMessageChunk(content=event.text, response_metadata=response_metadata)
            elif event.type == "reasoning_delta":
                yield AIMessageChunk(
                    content="",
                    additional_kwargs={"reasoning_content_delta": event.text},
                    response_metadata=response_metadata,
                )
            elif event.type == "tool_call_final" and event.tool_calls:
                yield AIMessageChunk(
                    content="",
                    tool_calls=[
                        {"id": call.id, "name": call.name, "args": call.arguments}
                        for call in event.tool_calls
                    ],
                    response_metadata=response_metadata,
                )


def get_llm_client(role: Optional[str] = None, profile_id: Optional[str] = None, *, config: Optional[AppConfig] = None) -> LLMClient:
    return LLMClient(config=config or get_config(), role=role or "primary", profile_id=profile_id)


def list_profiles(config: Optional[AppConfig] = None) -> List[str]:
    return sorted((config or get_config()).llm.profiles.keys())
