# -*- coding: utf-8 -*-
"""Build provider payloads from internal messages and protocol routes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from config import AppConfig, LLMProfile, ProviderConfig

from .adapters import ProviderAdapter
from .protocol_resolver import ResolvedProtocolRoute
from .payload_validator import assert_payload_valid
from .schema import sanitize_tool_schema
from .streaming import extract_text_content
from .types import LLMCapabilities, LLMError


@dataclass
class PayloadPolicyActions:
    system_messages_converted: int = 0
    string_content_messages: int = 0
    reasoning_content_stripped: int = 0
    empty_assistant_prefill_removed: int = 0
    qwen_thinking_parameter: str = ""
    minimal_tool_schema: bool = False

    def to_log_dict(self) -> Dict[str, Any]:
        return {
            "payloadPolicySystemMessagesConverted": self.system_messages_converted,
            "payloadPolicyStringContentMessages": self.string_content_messages,
            "payloadPolicyReasoningContentStripped": self.reasoning_content_stripped,
            "payloadPolicyEmptyAssistantPrefillRemoved": self.empty_assistant_prefill_removed,
            "payloadPolicyQwenThinkingParameter": self.qwen_thinking_parameter,
            "payloadPolicyMinimalToolSchema": self.minimal_tool_schema,
        }


@dataclass(frozen=True)
class PayloadBuildInput:
    messages: List[Any]
    tools: List[Any]
    profile: LLMProfile
    provider: ProviderConfig
    adapter: ProviderAdapter
    route: ResolvedProtocolRoute
    capabilities: LLMCapabilities
    stream: bool
    api_key: str
    profile_id: str
    config: AppConfig


@dataclass(frozen=True)
class BuiltPayload:
    payload: Dict[str, Any]
    route: ResolvedProtocolRoute
    summary: Dict[str, Any]
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _apply_system_message_policy(
    messages: List[Dict[str, Any]],
    route: ResolvedProtocolRoute,
    actions: PayloadPolicyActions,
) -> List[Dict[str, Any]]:
    if route.policy.system_message_policy != "first_only_rest_user":
        return [dict(item) for item in messages]
    normalized: List[Dict[str, Any]] = []
    seen_system = False
    for item in messages:
        message = dict(item)
        if str(message.get("role") or "").strip().lower() == "system":
            if seen_system:
                message["role"] = "user"
                actions.system_messages_converted += 1
            else:
                seen_system = True
        normalized.append(message)
    return normalized


def _outgoing_reasoning_content_count(messages: List[Any]) -> int:
    count = 0
    for message in messages:
        reasoning: Any = None
        if isinstance(message, dict):
            reasoning = message.get("reasoning_content")
            if reasoning in (None, "") and isinstance(message.get("additional_kwargs"), dict):
                reasoning = message["additional_kwargs"].get("reasoning_content")
        else:
            additional_kwargs = getattr(message, "additional_kwargs", None)
            if isinstance(additional_kwargs, dict):
                reasoning = additional_kwargs.get("reasoning_content")
        if str(extract_text_content(reasoning) or "").strip():
            count += 1
    return count


def _apply_content_shape_policy(
    messages: List[Dict[str, Any]],
    route: ResolvedProtocolRoute,
    actions: PayloadPolicyActions,
    *,
    has_image_content: bool,
) -> List[Dict[str, Any]]:
    if route.policy.content_shape_policy != "string_only" and not route.compat.requires_string_content:
        return [dict(item) for item in messages]
    if has_image_content:
        return [dict(item) for item in messages]
    normalized: List[Dict[str, Any]] = []
    for item in messages:
        message = dict(item)
        content = message.get("content")
        if not isinstance(content, str):
            actions.string_content_messages += 1
        message["content"] = extract_text_content(content)
        normalized.append(message)
    return normalized


def _apply_reasoning_roundtrip_policy(
    messages: List[Dict[str, Any]],
    route: ResolvedProtocolRoute,
    actions: PayloadPolicyActions,
) -> List[Dict[str, Any]]:
    if route.compat.reasoning_roundtrip and route.policy.allow_reasoning_roundtrip:
        return [dict(item) for item in messages]
    normalized: List[Dict[str, Any]] = []
    for item in messages:
        message = dict(item)
        if "reasoning_content" in message:
            actions.reasoning_content_stripped += 1
            message.pop("reasoning_content", None)
        normalized.append(message)
    return normalized


def _apply_final_message_policy(
    messages: List[Dict[str, Any]],
    route: ResolvedProtocolRoute,
    actions: PayloadPolicyActions,
) -> List[Dict[str, Any]]:
    if route.policy.final_message_policy != "no_assistant_prefill":
        return [dict(item) for item in messages]
    if not messages:
        return []
    normalized = [dict(item) for item in messages]
    last = normalized[-1]
    if str(last.get("role") or "").strip().lower() != "assistant":
        return normalized
    if last.get("tool_calls"):
        return normalized
    if str(extract_text_content(last.get("content")) or "").strip():
        return normalized
    if last.get("reasoning_content"):
        return normalized
    normalized.pop()
    actions.empty_assistant_prefill_removed += 1
    return normalized


def _apply_message_protocol_policy(
    messages: List[Dict[str, Any]],
    route: ResolvedProtocolRoute,
    actions: PayloadPolicyActions,
    *,
    has_image_content: bool,
) -> List[Dict[str, Any]]:
    normalized = _apply_system_message_policy(messages, route, actions)
    normalized = _apply_content_shape_policy(normalized, route, actions, has_image_content=has_image_content)
    normalized = _apply_reasoning_roundtrip_policy(normalized, route, actions)
    normalized = _apply_final_message_policy(normalized, route, actions)
    return normalized


def _schema_for_tool_policy(
    tool_schema: Dict[str, Any],
    route: ResolvedProtocolRoute,
    actions: PayloadPolicyActions,
) -> Dict[str, Any]:
    if route.policy.tool_schema_policy == "minimal" or route.compat.strict_message_keys:
        actions.minimal_tool_schema = True
        return sanitize_tool_schema(tool_schema)
    return tool_schema


def _payload_thinking_parameters(
    profile: LLMProfile,
    route: ResolvedProtocolRoute,
    actions: PayloadPolicyActions,
) -> Dict[str, Any]:
    thinking_type = str(getattr(profile, "thinking_type", "") or "").strip().lower()
    if route.policy.thinking_param_shape != "qwen":
        return {}
    if thinking_type == "disabled":
        actions.qwen_thinking_parameter = "disabled"
        return {"enable_thinking": False}
    if thinking_type:
        actions.qwen_thinking_parameter = "enabled"
        return {"enable_thinking": True}
    return {}


def build_llm_payload(
    build_input: PayloadBuildInput,
    *,
    messages_have_prompt_cache_control,
    strip_cache_control_from_messages,
    message_to_openai_dict,
    content_blocks_have_image,
    convert_content_blocks_for_transport,
    tool_to_schema,
) -> BuiltPayload:
    messages = list(build_input.messages or [])
    selected_tools = list(build_input.tools or [])
    profile = build_input.profile
    adapter = build_input.adapter
    route = build_input.route
    policy_actions = PayloadPolicyActions()
    prompt_cache_mode = str(
        getattr(getattr(profile, "prompt_cache", None), "mode", "") or "disabled"
    ).strip().lower()
    has_prompt_cache_control = messages_have_prompt_cache_control(messages)
    if has_prompt_cache_control and prompt_cache_mode == "unsupported":
        raise LLMError(
            "prompt_cache_unsupported",
            (
                "当前模型配置声明不支持 prompt cache；"
                f"profile `{build_input.profile_id}` provider `{build_input.provider.kind}` "
                f"transport `{getattr(profile, 'transport', '') or 'chat_completions'}` "
                f"model `{profile.model}`。请在模型配置中设置 prompt_cache.mode，"
                "或关闭系统提示词缓存强制要求。"
            ),
            retryable=False,
            provider=str(build_input.provider.kind or ""),
            model=str(profile.model or ""),
            details={
                "profile_id": build_input.profile_id,
                "provider_kind": str(build_input.provider.kind or ""),
                "transport": str(getattr(profile, "transport", "") or "chat_completions"),
                "model": str(profile.model or ""),
                "prompt_cache_mode": prompt_cache_mode,
            },
        )

    has_image_content = any(
        isinstance(item, dict) and content_blocks_have_image(item.get("content"))
        for item in messages
    )
    preserve_cache_control = has_prompt_cache_control and prompt_cache_mode == "explicit_cache_control"
    preserve_structured_content = (
        adapter.preserves_structured_content
        or has_image_content
        or has_prompt_cache_control
    )
    preserve_reasoning_content = bool(route.compat.reasoning_roundtrip)
    if not preserve_reasoning_content:
        policy_actions.reasoning_content_stripped = _outgoing_reasoning_content_count(messages)
    normalized_messages = [
        message_to_openai_dict(
            item,
            preserve_structured_content=preserve_structured_content,
            preserve_reasoning_content=preserve_reasoning_content,
        )
        for item in messages
    ]
    if has_prompt_cache_control and not preserve_cache_control:
        normalized_messages = strip_cache_control_from_messages(normalized_messages)
    if has_image_content:
        transport = str(getattr(profile, "transport", "") or "").strip().lower()
        for item in normalized_messages:
            item["content"] = convert_content_blocks_for_transport(item.get("content"), transport=transport)
    normalized_messages = _apply_message_protocol_policy(
        normalized_messages,
        route,
        policy_actions,
        has_image_content=has_image_content,
    )

    payload = {
        "model": adapter.litellm_model_name(),
        "messages": adapter.messages(normalized_messages),
        "max_tokens": profile.max_output_tokens,
        "timeout": profile.timeout,
        "stream": build_input.stream,
        "api_key": build_input.api_key,
        "base_url": build_input.provider.base_url,
    }
    payload.update(adapter.payload_sampling_parameters())
    payload.update(adapter.payload_thinking_parameters())
    payload.update(_payload_thinking_parameters(profile, route, policy_actions))

    prompt_cache = getattr(profile, "prompt_cache", None)
    if prompt_cache_mode == "automatic":
        prompt_cache_key = str(getattr(prompt_cache, "key", "") or "").strip()
        prompt_cache_retention = str(getattr(prompt_cache, "retention", "") or "").strip()
        if prompt_cache_key:
            payload["prompt_cache_key"] = prompt_cache_key
        if prompt_cache_retention:
            payload["prompt_cache_retention"] = prompt_cache_retention
    if build_input.stream and adapter.supports_stream_usage_options() and route.compat.stream_usage_options:
        payload["stream_options"] = {"include_usage": True}
    headers = build_input.provider.extra_headers or {}
    if headers:
        payload["extra_headers"] = headers
    if selected_tools:
        if not build_input.capabilities.supports_tool_calling or not route.policy.allow_tools:
            raise LLMError("capability_error", f"profile `{build_input.profile_id}` 不支持 tool calling", retryable=False)
        payload["tools"] = [
            _schema_for_tool_policy(adapter.sanitize_tool_schema(tool_to_schema(tool)), route, policy_actions)
            for tool in selected_tools
        ]
        if adapter.supports_explicit_tool_choice() and route.policy.allow_explicit_tool_choice and route.compat.tool_choice_mode != "omit":
            payload["tool_choice"] = "auto"

    summary = assert_payload_valid(payload, route)
    summary.update(policy_actions.to_log_dict())
    return BuiltPayload(payload=payload, route=route, summary=summary, warnings=route.warnings)


__all__ = ["BuiltPayload", "PayloadBuildInput", "build_llm_payload"]
