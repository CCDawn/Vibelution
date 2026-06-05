# -*- coding: utf-8 -*-
"""统一 LLM client。"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlparse

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, SystemMessage, ToolMessage

from config import AppConfig, get_config

from .adapters import get_provider_adapter
from .discovery import discover_model
from .errors import classify_exception
from .payload_builder import PayloadBuildInput, build_llm_payload
from .payload_validator import payload_protocol_summary
from .protocol_resolver import resolve_model_protocol
from .reasoning_extractor import extract_reasoning_text, strip_think_tag_reasoning
from .streaming import extract_message_tool_calls, extract_text_content
from .types import LLMCapabilities, LLMError, StreamChunk, UsageStats
from .usage import read_usage_int as _read_provider_usage_int
from .usage import usage_stats_from_payload, usage_to_dict


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


class LLMCancelledError(Exception):
    """Raised when an active turn requests cancellation before more LLM work."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason or "LLM call cancelled.")
        self.reason = str(reason or "").strip()


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
    return {
        "promptCacheDesign": {
            "mode": str(prompt_cache_mode or "").strip().lower(),
            "hasCacheControl": bool(_messages_have_prompt_cache_control(messages)),
            **shape,
        }
    }


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
    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
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
        "maxTokens": payload.get("max_tokens"),
        "timeout": payload.get("timeout"),
    }


def _safe_payload_thinking_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    thinking = payload.get("thinking")
    if not isinstance(thinking, dict):
        return {
            "thinkingRequested": False,
            "thinkingType": "",
            "thinkingDisplay": "",
        }
    return {
        "thinkingRequested": True,
        "thinkingType": str(thinking.get("type") or "").strip(),
        "thinkingDisplay": str(thinking.get("display") or "").strip(),
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
    return completion(**payload)


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
        tool_calls = _normalize_tool_calls(getattr(message, "tool_calls", []) or [])
        if tool_calls:
            payload["tool_calls"] = tool_calls
        additional_kwargs = getattr(message, "additional_kwargs", None) or {}
        return maybe_attach_reasoning(payload, additional_kwargs.get("reasoning_content"))
    if isinstance(message, BaseMessage):
        return {"role": getattr(message, "type", "user"), "content": content_value(getattr(message, "content", ""))}
    if isinstance(message, dict):
        payload = {"role": str(message.get("role") or "user"), "content": content_value(message.get("content"))}
        if payload["role"] == "assistant":
            tool_calls = _normalize_tool_calls(message.get("tool_calls") or [])
            if tool_calls:
                payload["tool_calls"] = tool_calls
        if payload["role"] == "tool" and message.get("tool_call_id"):
            payload["tool_call_id"] = message.get("tool_call_id")
        reasoning = message.get("reasoning_content")
        if reasoning in (None, "") and isinstance(message.get("additional_kwargs"), dict):
            reasoning = message["additional_kwargs"].get("reasoning_content")
        return maybe_attach_reasoning(payload, reasoning)
    return {"role": "user", "content": content_value(message)}


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
    ) -> None:
        self.config = config or get_config()
        self.role = role
        self.profile_id = profile_id or self.config.llm.get_role_profile_id(role)
        self.profile = self.config.llm.get_profile(self.profile_id)
        self.provider = self.config.llm.get_provider(self.profile.provider_id)
        self.bound_tools = list(bound_tools or [])
        self._backend = backend or _default_completion_backend
        self.adapter = get_provider_adapter(self.provider, self.profile)
        self._resolved_spec = discover_model(self.config, self.profile_id)
        _model_id, model_entry = self.config.llm.get_model_library_entry_for_profile(self.profile)
        self.protocol_route = resolve_model_protocol(
            self.profile,
            self.provider,
            model_entry=model_entry if isinstance(model_entry, dict) else None,
        )
        self._last_payload_protocol_summary: Dict[str, Any] = {}

    @property
    def capabilities(self) -> LLMCapabilities:
        return self._resolved_spec.capabilities

    @property
    def resolved_spec(self):
        return self._resolved_spec

    def bind_tools(self, tools: List[Any], *, binding_name: str = "default") -> "LLMClient":
        return LLMClient(
            config=self.config,
            role=self.role,
            profile_id=self.profile_id,
            bound_tools=list(tools or []),
            backend=self._backend,
        )

    def _build_payload(self, messages: List[Any], *, tools: Optional[List[Any]] = None, stream: bool = False) -> Dict[str, Any]:
        selected_tools = list(self.bound_tools)
        if tools is not None:
            selected_tools = list(tools or [])
        built = build_llm_payload(
            PayloadBuildInput(
                messages=list(messages or []),
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
            ),
            messages_have_prompt_cache_control=_messages_have_prompt_cache_control,
            strip_cache_control_from_messages=_strip_cache_control_from_messages,
            message_to_openai_dict=_message_to_openai_dict,
            content_blocks_have_image=_content_blocks_have_image,
            convert_content_blocks_for_transport=_convert_content_blocks_for_transport,
            tool_to_schema=_tool_to_schema,
        )
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

    def invoke(self, messages: List[Any], *, tools: Optional[List[Any]] = None, metadata: Optional[Dict[str, Any]] = None) -> AIMessage:
        start = time.time()
        payload = self._build_payload(messages, tools=tools, stream=False)
        message_role_summary = _safe_message_role_summary(payload.get("messages") or messages)
        route_summary = _safe_payload_route_summary(payload, self.profile, self.provider)
        payload_shape_summary = _safe_payload_shape_summary(payload)
        prompt_cache_design_summary = _safe_prompt_cache_design_summary(
            messages,
            prompt_cache_mode=str(getattr(getattr(self.profile, "prompt_cache", None), "mode", "") or "disabled"),
        )
        thinking_summary = _safe_payload_thinking_summary(payload)
        protocol_summary = dict(self._last_payload_protocol_summary or payload_protocol_summary(payload, self.protocol_route))
        capability_source_summary = _safe_capability_source_summary(self._resolved_spec)
        response = self._invoke_backend_with_retry(
            payload,
            phase="invoke",
            event_code="llm.invoke.failed",
            message_count=len(messages or []),
            tool_count=len(tools or self.bound_tools or []),
            metadata={
                **(metadata or {}),
                **message_role_summary,
                **route_summary,
                **payload_shape_summary,
                **prompt_cache_design_summary,
                **thinking_summary,
                **protocol_summary,
                **capability_source_summary,
            },
        )
        latency_ms = int((time.time() - start) * 1000)
        message = self._choice_message(response)
        tool_calls = extract_message_tool_calls(message)
        usage = self._usage_from_response(response, latency_ms)
        additional_kwargs = {"tool_calls_raw": [call.provider_payload for call in tool_calls]}
        reasoning = extract_reasoning_text(message, extract_text_content)
        reasoning_content = reasoning.text
        if reasoning_content.strip():
            additional_kwargs["reasoning_content"] = reasoning_content
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
                "toolCount": len(tools or self.bound_tools or []),
                "toolCallCount": len(tool_calls),
                **route_summary,
                **message_role_summary,
                **payload_shape_summary,
                **prompt_cache_design_summary,
                **thinking_summary,
                **protocol_summary,
                **capability_source_summary,
                "inputTokens": usage.input_tokens,
                "outputTokens": usage.output_tokens,
                "totalTokens": usage.total_tokens,
                "cachedInputTokens": usage.cached_input_tokens,
                "reasoningSource": reasoning.source,
                "reasoningChars": len(reasoning_content),
                "reasoningObserved": bool(reasoning_content.strip()),
                "cacheHitRate": round(usage.cached_input_tokens / usage.input_tokens, 4)
                if usage.input_tokens > 0
                else 0.0,
                "latencyMs": latency_ms,
                "metadata": metadata or {},
            },
            lifecycle=False,
        )
        return AIMessage(
            content=strip_think_tag_reasoning(message.get("content") or "", extract_text_content),
            tool_calls=[
                {"id": call.id, "name": call.name, "args": call.arguments}
                for call in tool_calls
            ],
            response_metadata={
                "role": self.role,
                "profile_id": self.profile_id,
                "provider": self.provider.kind,
                "model": self.profile.model,
                "usage": usage.provider_raw_usage,
                "usage_observation": {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "total_tokens": usage.total_tokens,
                    "cached_input_tokens": usage.cached_input_tokens,
                    "cache_hit_rate": (
                        usage.cached_input_tokens / usage.input_tokens
                        if usage.input_tokens > 0
                        else 0.0
                    ),
                },
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
        return self._backend(payload)

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
                    return self._backend(payload)
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

    def _stream_fallback_to_invoke(
        self,
        stream_payload: Dict[str, Any],
        *,
        message_count: int,
        tool_count: int,
        metadata: Optional[Dict[str, Any]],
        last_error: LLMError,
    ) -> Iterator[StreamChunk]:
        payload = dict(stream_payload)
        payload["stream"] = False
        route_summary = _safe_payload_route_summary(payload, self.profile, self.provider)
        start = time.time()
        _record_llm_scene_event(
            "stream",
            "llm.stream.fallback.invoke_started",
            message="LLM stream fallback to non-streaming invoke started.",
            level="warning",
            outcome="running",
            fields={
                "role": self.role,
                "profileId": self.profile_id,
                "provider": self.provider.kind,
                "model": self.profile.model,
                "messageCount": message_count,
                "toolCount": tool_count,
                **route_summary,
                **(metadata or {}),
                "fallbackReason": last_error.category,
                "fallbackError": str(last_error),
            },
            lifecycle=True,
        )
        _publish_llm_status_event(
            "fallback_invoke_started",
            reason=last_error.category,
            message_count=message_count,
            tool_count=tool_count,
        )
        try:
            response = self._invoke_payload_once(payload)
        except Exception as exc:
            llm_error = classify_exception(exc)
            _record_llm_scene_event(
                "stream",
                "llm.stream.fallback.invoke_failed",
                message=f"LLM stream fallback invoke failed: {llm_error.category}",
                level="error",
                outcome="failed",
                fields=_llm_retry_event_fields(
                    role=self.role,
                    profile_id=self.profile_id,
                    provider=self.provider.kind,
                    model=self.profile.model,
                    message_count=message_count,
                    tool_count=tool_count,
                    metadata={**(metadata or {}), **route_summary, "fallbackReason": last_error.category},
                    attempt=1,
                    max_attempts=1,
                    llm_error=llm_error,
                ),
                lifecycle=True,
            )
            _publish_llm_status_event(
                "failed",
                category=llm_error.category,
                retryable=llm_error.retryable,
            )
            raise llm_error from exc

        latency_ms = int((time.time() - start) * 1000)
        message = self._choice_message(response)
        text = strip_think_tag_reasoning(message.get("content") or "", extract_text_content)
        reasoning = extract_reasoning_text(message, extract_text_content)
        tool_calls = extract_message_tool_calls(message)
        usage = self._usage_from_response(response, latency_ms)
        _record_llm_scene_event(
            "stream",
            "llm.stream.fallback.invoke_succeeded",
            message="LLM stream fallback invoke succeeded.",
            outcome="succeeded",
            fields={
                "role": self.role,
                "profileId": self.profile_id,
                "provider": self.provider.kind,
                "model": self.profile.model,
                "messageCount": message_count,
                "toolCount": tool_count,
                **route_summary,
                **(metadata or {}),
                "toolCallCount": len(tool_calls),
                "reasoningSource": reasoning.source,
                "reasoningChars": len(reasoning.text),
                "inputTokens": usage.input_tokens,
                "outputTokens": usage.output_tokens,
                "totalTokens": usage.total_tokens,
                "cachedInputTokens": usage.cached_input_tokens,
                "cacheHitRate": round(usage.cached_input_tokens / usage.input_tokens, 4)
                if usage.input_tokens > 0
                else 0.0,
                "latencyMs": latency_ms,
            },
            lifecycle=True,
        )
        _publish_llm_status_event(
            "fallback_invoke_succeeded",
            reason=last_error.category,
            content_chars=len(text or ""),
            tool_call_count=len(tool_calls or []),
        )
        if reasoning.text.strip():
            yield StreamChunk(type="reasoning_delta", text=reasoning.text, provider_payload={**message, "reasoning_source": reasoning.source})
        if text.strip():
            yield StreamChunk(type="text_delta", text=text, provider_payload=message)
        if tool_calls:
            yield StreamChunk(type="tool_call_final", tool_calls=tool_calls, provider_payload=message)
        yield StreamChunk(type="done", usage=usage, provider_payload=message)

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
    ) -> Tuple[Iterator[StreamChunk], Callable[[], bool]]:
        _raise_if_llm_cancelled()
        iterator = self._backend(payload)
        emitted = False

        def events() -> Iterator[StreamChunk]:
            nonlocal emitted
            normalized_iterator = self.adapter.stream_normalizer().events(iterator)
            try:
                for event in normalized_iterator:
                    _raise_if_llm_cancelled()
                    emitted = True
                    yield event
                    _raise_if_llm_cancelled()
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
    ) -> Iterator[StreamChunk]:
        """Yield normalized stream events independent of LangChain chunks."""
        payload = self._build_payload(messages, tools=tools, stream=True)
        message_count = len(messages or [])
        tool_count = len(tools or self.bound_tools or [])
        message_role_summary = _safe_message_role_summary(payload.get("messages") or messages)
        route_summary = _safe_payload_route_summary(payload, self.profile, self.provider)
        payload_shape_summary = _safe_payload_shape_summary(payload)
        prompt_cache_design_summary = _safe_prompt_cache_design_summary(
            messages,
            prompt_cache_mode=str(getattr(getattr(self.profile, "prompt_cache", None), "mode", "") or "disabled"),
        )
        thinking_summary = _safe_payload_thinking_summary(payload)
        protocol_summary = dict(self._last_payload_protocol_summary or payload_protocol_summary(payload, self.protocol_route))
        capability_source_summary = _safe_capability_source_summary(self._resolved_spec)
        event_metadata = {
            **message_role_summary,
            **route_summary,
            **payload_shape_summary,
            **prompt_cache_design_summary,
            **thinking_summary,
            **protocol_summary,
            **capability_source_summary,
        }
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
                usage_observed = (
                    bool(usage_observation.provider_raw_usage)
                    and (
                        usage_observation.input_tokens > 0
                        or usage_observation.output_tokens > 0
                        or usage_observation.total_tokens > 0
                        or usage_observation.cached_input_tokens > 0
                    )
                )
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
                        "inputTokens": usage_observation.input_tokens,
                        "outputTokens": usage_observation.output_tokens,
                        "totalTokens": usage_observation.total_tokens,
                        "cachedInputTokens": usage_observation.cached_input_tokens,
                        "cacheHitRate": round(
                            usage_observation.cached_input_tokens / usage_observation.input_tokens,
                            4,
                        )
                        if usage_observation.input_tokens > 0
                        else 0.0,
                        "latencyMs": usage_observation.latency_ms,
                        "messageCount": message_count,
                        "toolCount": tool_count,
                        **event_metadata,
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
                    if llm_error.retryable:
                        yield from self._stream_fallback_to_invoke(
                            payload,
                            message_count=message_count,
                            tool_count=tool_count,
                            metadata=event_metadata,
                            last_error=llm_error,
                        )
                        return
                    raise llm_error from exc

    def stream(self, messages: List[Any], *, tools: Optional[List[Any]] = None, metadata: Optional[Dict[str, Any]] = None) -> Iterator[AIMessageChunk]:
        for event in self.stream_events(messages, tools=tools):
            response_metadata = self._response_metadata(metadata)
            if event.type == "done":
                if event.usage is not None:
                    done_metadata = dict(response_metadata)
                    done_metadata["usage"] = event.usage.provider_raw_usage
                    done_metadata["usage_observation"] = {
                        "input_tokens": event.usage.input_tokens,
                        "output_tokens": event.usage.output_tokens,
                        "total_tokens": event.usage.total_tokens,
                        "cached_input_tokens": event.usage.cached_input_tokens,
                        "cache_hit_rate": (
                            event.usage.cached_input_tokens / event.usage.input_tokens
                            if event.usage.input_tokens > 0
                            else 0.0
                        ),
                    }
                    yield AIMessageChunk(content="", response_metadata=done_metadata)
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
