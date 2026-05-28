# -*- coding: utf-8 -*-
"""统一 LLM client。"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlparse

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, SystemMessage, ToolMessage

from config import AppConfig, get_config

from .adapters import get_provider_adapter
from .discovery import discover_model
from .errors import classify_exception
from .streaming import extract_message_tool_calls, extract_text_content
from .types import LLMCapabilities, LLMError, StreamChunk, UsageStats


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
        for key in ("messageRoles", "messageRoleCounts"):
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

    first_system_blocks = first_system_content if isinstance(first_system_content, list) else []
    first_system_cacheable_parts: List[str] = []
    first_system_dynamic_parts: List[str] = []
    first_system_cache_control_blocks = 0
    if first_system_blocks:
        for block in first_system_blocks:
            if not isinstance(block, dict):
                text = extract_text_content(block)
                if text:
                    first_system_dynamic_parts.append(text)
                continue
            text = extract_text_content(block.get("text") if "text" in block else block)
            if block.get("cache_control"):
                first_system_cache_control_blocks += 1
                if text:
                    first_system_cacheable_parts.append(text)
            elif text:
                first_system_dynamic_parts.append(text)
    elif first_system_content is not None:
        first_system_dynamic_parts.append(extract_text_content(first_system_content))

    tools = payload.get("tools") if isinstance(payload.get("tools"), list) else []
    tool_names: List[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
        name = str(function.get("name") or tool.get("name") or "").strip()
        if name:
            tool_names.append(name)

    cacheable_text = "\n\n".join(first_system_cacheable_parts)
    dynamic_text = "\n\n".join(first_system_dynamic_parts)
    return {
        "payloadShape": {
            "messageTextCharsByRole": role_text_chars,
            "systemTextChars": system_text_chars,
            "nonSystemTextChars": non_system_text_chars,
            "structuredContentMessageCount": structured_content_message_count,
            "imageBlockCount": image_block_count,
            "firstSystemHash": _short_hash(first_system_content),
            "firstSystemTextChars": _text_length(first_system_content),
            "firstSystemBlockCount": len(first_system_blocks),
            "firstSystemCacheControlBlockCount": first_system_cache_control_blocks,
            "firstSystemCacheableTextChars": len(cacheable_text),
            "firstSystemDynamicTextChars": len(dynamic_text),
            "firstSystemCacheableHash": _short_hash(cacheable_text),
            "firstSystemDynamicHash": _short_hash(dynamic_text),
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


def _read_usage_int(container: Any, *keys: str) -> int:
    if not isinstance(container, dict):
        return 0
    for key in keys:
        value = container.get(key)
        if value not in (None, ""):
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
    return 0


def _usage_to_dict(usage: Any) -> Dict[str, Any]:
    if isinstance(usage, dict):
        return usage
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        try:
            payload = usage.model_dump()
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}
    payload: Dict[str, Any] = {}
    for key in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "input_tokens",
        "output_tokens",
        "input_token_count",
        "output_token_count",
        "cached_tokens",
        "cached_input_tokens",
        "prompt_tokens_details",
        "input_token_details",
    ):
        if hasattr(usage, key):
            payload[key] = getattr(usage, key)
    return payload


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


def _default_completion_backend(payload: Dict[str, Any]) -> Any:
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
        has_image_content = any(
            isinstance(item, dict) and _content_blocks_have_image(item.get("content"))
            for item in messages
        )
        normalized_messages = [
            _message_to_openai_dict(
                item,
                preserve_structured_content=self.adapter.preserves_structured_content or has_image_content,
                preserve_reasoning_content=self.adapter.should_preserve_reasoning_content(),
            )
            for item in messages
        ]
        if has_image_content:
            transport = str(getattr(self.profile, "transport", "") or "").strip().lower()
            for item in normalized_messages:
                item["content"] = _convert_content_blocks_for_transport(item.get("content"), transport=transport)
        payload = {
            "model": self.adapter.litellm_model_name(),
            "messages": self.adapter.messages(normalized_messages),
            "temperature": self.adapter.payload_temperature(),
            "max_tokens": self.profile.max_output_tokens,
            "timeout": self.profile.timeout,
            "stream": stream,
            "api_key": self.config.get_api_key_for_profile(profile_id=self.profile_id),
            "base_url": self.provider.base_url,
        }
        if stream and self.adapter.supports_stream_usage_options():
            payload["stream_options"] = {"include_usage": True}
        headers = self.provider.extra_headers or {}
        if headers:
            payload["extra_headers"] = headers
        if selected_tools:
            if not self.capabilities.supports_tool_calling:
                raise LLMError("capability_error", f"profile `{self.profile_id}` 不支持 tool calling", retryable=False)
            payload["tools"] = [
                self.adapter.sanitize_tool_schema(_tool_to_schema(tool))
                for tool in selected_tools
            ]
            if self.adapter.supports_explicit_tool_choice():
                payload["tool_choice"] = "auto"
        return payload

    def _usage_from_response(self, response: Any, latency_ms: int) -> UsageStats:
        usage = getattr(response, "usage", None)
        if usage is None and isinstance(response, dict):
            usage = response.get("usage")
        usage = _usage_to_dict(usage)
        prompt_tokens = _read_usage_int(usage, "prompt_tokens", "input_tokens", "input_token_count")
        completion_tokens = _read_usage_int(usage, "completion_tokens", "output_tokens", "output_token_count")
        total_tokens = _read_usage_int(usage, "total_tokens") or (prompt_tokens + completion_tokens)
        prompt_details = usage.get("prompt_tokens_details")
        input_details = usage.get("input_token_details")
        cached_tokens = max(
            _read_usage_int(usage, "cached_tokens", "cached_input_tokens"),
            _read_usage_int(prompt_details, "cached_tokens", "cached_input_tokens"),
            _read_usage_int(input_details, "cached_tokens", "cached_input_tokens"),
        )
        return UsageStats(
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=min(cached_tokens, prompt_tokens) if prompt_tokens else cached_tokens,
            provider_raw_usage=usage,
            estimated_cost=0.0,
            latency_ms=latency_ms,
        )

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
        response = self._invoke_backend_with_retry(
            payload,
            phase="invoke",
            event_code="llm.invoke.failed",
            message_count=len(messages or []),
            tool_count=len(tools or self.bound_tools or []),
            metadata={**(metadata or {}), **message_role_summary, **route_summary, **payload_shape_summary},
        )
        latency_ms = int((time.time() - start) * 1000)
        message = self._choice_message(response)
        tool_calls = extract_message_tool_calls(message)
        usage = self._usage_from_response(response, latency_ms)
        additional_kwargs = {"tool_calls_raw": [call.provider_payload for call in tool_calls]}
        reasoning_content = extract_text_content(message.get("reasoning_content") or "")
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
                "inputTokens": usage.input_tokens,
                "outputTokens": usage.output_tokens,
                "totalTokens": usage.total_tokens,
                "cachedInputTokens": usage.cached_input_tokens,
                "cacheHitRate": round(usage.cached_input_tokens / usage.input_tokens, 4)
                if usage.input_tokens > 0
                else 0.0,
                "latencyMs": latency_ms,
                "metadata": metadata or {},
            },
            lifecycle=False,
        )
        return AIMessage(
            content=extract_text_content(message.get("content") or ""),
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
            "metadata": metadata or {},
        }

    def _invoke_payload_once(self, payload: Dict[str, Any]) -> Any:
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
        for attempt in range(1, max_attempts + 1):
            try:
                return self._backend(payload)
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
                time.sleep(wait_seconds)
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
            raise llm_error from exc

        latency_ms = int((time.time() - start) * 1000)
        message = self._choice_message(response)
        text = extract_text_content(message.get("content") or "")
        reasoning = extract_text_content(message.get("reasoning_content") or "")
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
        if reasoning.strip():
            yield StreamChunk(type="reasoning_delta", text=reasoning, provider_payload=message)
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
        time.sleep(wait_seconds)
        return True

    def _stream_attempt(
        self,
        payload: Dict[str, Any],
        *,
        message_count: int,
        tool_count: int,
    ) -> Tuple[Iterator[StreamChunk], Callable[[], bool]]:
        iterator = self._backend(payload)
        emitted = False

        def events() -> Iterator[StreamChunk]:
            nonlocal emitted
            for event in self.adapter.stream_normalizer().events(iterator):
                emitted = True
                yield event

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
        event_metadata = {**message_role_summary, **route_summary, **payload_shape_summary}
        max_attempts = _retry_policy_max_attempts(self.profile)
        last_error: LLMError | None = None
        stream_usage_options_downgraded = False
        for attempt in range(1, max_attempts + 1):
            start = time.time()
            emitted = False
            chunk_count = 0
            text_delta_count = 0
            reasoning_delta_count = 0
            tool_call_count = 0
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
                events, emitted_fn = self._stream_attempt(
                    payload,
                    message_count=message_count,
                    tool_count=tool_count,
                )
                for event in events:
                    emitted = emitted_fn()
                    chunk_count += 1
                    if event.type == "text_delta":
                        text_delta_count += 1
                    elif event.type == "reasoning_delta":
                        reasoning_delta_count += 1
                    elif event.type == "tool_call_final":
                        tool_call_count += len(event.tool_calls or [])
                    elif event.type == "done" and event.usage is not None:
                        usage_observation = event.usage
                    yield event
                usage_observation.latency_ms = int((time.time() - start) * 1000)
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
                        "messageCount": message_count,
                        "toolCount": tool_count,
                        **event_metadata,
                        "chunkCount": chunk_count,
                        "textDeltaCount": text_delta_count,
                        "reasoningDeltaCount": reasoning_delta_count,
                        "toolCallCount": tool_call_count,
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
                        "usageObserved": bool(usage_observation.provider_raw_usage),
                        "latencyMs": usage_observation.latency_ms,
                    },
                    lifecycle=False,
                )
                return
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
        response_metadata = self._response_metadata(metadata)
        for event in self.stream_events(messages, tools=tools):
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
