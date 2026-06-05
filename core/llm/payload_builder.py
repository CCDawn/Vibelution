# -*- coding: utf-8 -*-
"""Build provider payloads from internal messages and protocol routes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from config import AppConfig, LLMProfile, ProviderConfig

from .adapters import ProviderAdapter
from .protocol_resolver import ResolvedProtocolRoute
from .payload_validator import assert_payload_valid
from .types import LLMCapabilities, LLMError


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
            adapter.sanitize_tool_schema(tool_to_schema(tool))
            for tool in selected_tools
        ]
        if adapter.supports_explicit_tool_choice() and route.policy.allow_explicit_tool_choice and route.compat.tool_choice_mode != "omit":
            payload["tool_choice"] = "auto"

    summary = assert_payload_valid(payload, route)
    return BuiltPayload(payload=payload, route=route, summary=summary, warnings=route.warnings)


__all__ = ["BuiltPayload", "PayloadBuildInput", "build_llm_payload"]
