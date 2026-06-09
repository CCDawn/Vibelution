# -*- coding: utf-8 -*-
"""Provider-specific LLM payload adaptation.

The rest of the agent keeps an internal OpenAI-like message/tool shape. This
module owns the narrower contract of translating that shape into the model
router/provider shape accepted by LiteLLM and provider APIs.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Dict, List
from urllib.parse import urlparse

from config import LLMProfile, ProviderConfig

from .reasoning_effort import model_supports_gpt_reasoning_effort, normalize_reasoning_effort
from .schema import sanitize_tool_schema
from .streaming import LiteLLMStreamNormalizer
from .types import LLMCapabilities


_LITELLM_PROVIDER_PREFIXES = {
    "ai21",
    "aleph_alpha",
    "anthropic",
    "azure",
    "bedrock",
    "cohere",
    "deepseek",
    "fireworks_ai",
    "gemini",
    "groq",
    "huggingface",
    "mistral",
    "minimax",
    "ollama",
    "openai",
    "openrouter",
    "perplexity",
    "replicate",
    "together_ai",
    "vertex_ai",
    "voyage",
}

_NATIVE_LITELLM_PREFIX_BY_PROVIDER = {
    "anthropic": "anthropic",
    "deepseek": "deepseek",
    "groq": "groq",
    "minimax": "minimax",
    "ollama": "ollama",
    "openai": "openai",
}

_OPENAI_COMPAT_PROVIDER_KINDS = {
    "aliyun",
    "local",
    "openai_compatible",
    "siliconflow",
    "xiaomi",
    "zhipu",
}


def _is_litellm_provider_qualified(model: str) -> bool:
    prefix, separator, _ = str(model or "").partition("/")
    return bool(separator and prefix.strip().lower() in _LITELLM_PROVIDER_PREFIXES)


def _is_responses_prefixed_model(model: str) -> bool:
    parts = [part.strip().lower() for part in str(model or "").split("/") if part.strip()]
    return "responses" in parts[:2]


def _model_segments(model: str) -> List[str]:
    return [part.strip().lower() for part in str(model or "").split("/") if part.strip()]


def _is_gpt5_family_model(model: str) -> bool:
    return any(part.startswith("gpt-5") for part in _model_segments(model))


def _is_anthropic_opus_4_7_or_later(model: str) -> bool:
    normalized = str(model or "").strip().lower().replace("_", "-").replace(".", "-")
    for segment in normalized.split("/"):
        match = re.match(r"^claude-opus-4-(\d+)(?:\b|-)", segment)
        if match and int(match.group(1)) >= 7:
            return True
    return False


def _convert_system_messages_after_first_to_user(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    seen_system = False
    for item in messages:
        message = dict(item)
        if message.get("role") == "system":
            if seen_system:
                message["role"] = "user"
            else:
                seen_system = True
        normalized.append(message)
    return normalized


class ProviderAdapter:
    """Base adapter for provider/model specific payload quirks."""

    preserves_structured_content = False
    preserves_reasoning_content = False

    def __init__(self, provider: ProviderConfig, profile: LLMProfile) -> None:
        self.provider = provider
        self.profile = profile
        self.kind = str(provider.kind or "").strip().lower()
        self.compat_mode = str(provider.compat_mode or "").strip().lower()

    def litellm_model_name(self) -> str:
        raw_model = str(self.profile.model or "").strip()
        if str(getattr(self.profile, "transport", "") or "").strip().lower() == "responses":
            return self._responses_litellm_model_name(raw_model)
        if not raw_model or _is_litellm_provider_qualified(raw_model):
            return raw_model

        prefix = self._litellm_provider_prefix()
        if prefix:
            return f"{prefix}/{raw_model}"
        return raw_model

    def _responses_litellm_model_name(self, raw_model: str) -> str:
        if not raw_model or _is_responses_prefixed_model(raw_model):
            return raw_model
        prefix = self._litellm_provider_prefix()
        if _is_litellm_provider_qualified(raw_model):
            model_prefix, _, model_name = raw_model.partition("/")
            return f"{model_prefix}/responses/{model_name}"
        if prefix:
            return f"{prefix}/responses/{raw_model}"
        return f"responses/{raw_model}"

    def _litellm_provider_prefix(self) -> str:
        if self.kind in _OPENAI_COMPAT_PROVIDER_KINDS:
            return "openai"
        if self.kind in _NATIVE_LITELLM_PREFIX_BY_PROVIDER:
            return _NATIVE_LITELLM_PREFIX_BY_PROVIDER[self.kind]
        if self.compat_mode == "openai" and self.kind not in {"azure"}:
            return "openai"
        return ""

    def messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return messages

    def capabilities(self, base: LLMCapabilities) -> LLMCapabilities:
        transport = str(getattr(self.profile, "transport", "") or "").strip().lower()
        prompt_cache_mode = str(
            getattr(getattr(self.profile, "prompt_cache", None), "mode", "") or "disabled"
        ).strip().lower()
        supports_reasoning_effort = model_supports_gpt_reasoning_effort(
            model=self.profile.model,
            provider_kind=self.kind,
            transport=transport,
            compat_mode=self.compat_mode,
            provider_api=getattr(self.provider, "api", ""),
        )
        return replace(
            base,
            supports_image_input=bool(getattr(self.profile, "supports_image_input", None) is True),
            supports_prompt_cache=prompt_cache_mode not in {"", "disabled", "unsupported"},
            supports_thinking=bool(str(getattr(self.profile, "thinking_type", "") or "").strip()) or supports_reasoning_effort,
            supports_reasoning_roundtrip=bool(self.should_preserve_reasoning_content()),
            supports_explicit_tool_choice=bool(self.supports_explicit_tool_choice()),
            supports_stream_usage=bool(self.supports_stream_usage_options()),
            supports_responses_transport=transport == "responses",
            supports_structured_content=bool(self.preserves_structured_content),
        )

    def sanitize_tool_schema(self, tool_schema: Dict[str, Any]) -> Dict[str, Any]:
        return sanitize_tool_schema(tool_schema)

    def stream_normalizer(self) -> LiteLLMStreamNormalizer:
        return LiteLLMStreamNormalizer()

    def should_preserve_reasoning_content(self) -> bool:
        if self.preserves_reasoning_content:
            return True
        host = urlparse(str(self.provider.base_url or "").strip()).hostname or ""
        return "deepseek.com" in host.lower()

    def uses_openai_gpt5_chat_constraints(self) -> bool:
        openai_like = (
            self.kind in {"openai", "azure"}
            or self.kind in _OPENAI_COMPAT_PROVIDER_KINDS
            or self.compat_mode in {"openai", "openai_compatible"}
            or self.litellm_model_name().strip().lower().startswith(("openai/", "azure/"))
        )
        return openai_like and _is_gpt5_family_model(self.profile.model)

    def payload_temperature(self) -> float:
        if self.uses_openai_gpt5_chat_constraints():
            return 1.0
        return float(self.profile.temperature)

    def payload_sampling_parameters(self) -> Dict[str, Any]:
        return {"temperature": self.payload_temperature()}

    def payload_thinking_parameters(self) -> Dict[str, Any]:
        effort = normalize_reasoning_effort(getattr(self.profile, "reasoning_effort", ""))
        if effort and model_supports_gpt_reasoning_effort(
            model=self.profile.model,
            provider_kind=self.kind,
            transport=getattr(self.profile, "transport", ""),
            compat_mode=self.compat_mode,
            provider_api=getattr(self.provider, "api", ""),
        ):
            return {"reasoning": {"effort": effort}}
        return {}

    def supports_explicit_tool_choice(self) -> bool:
        if self.uses_openai_gpt5_chat_constraints():
            return False
        return True

    def supports_stream_usage_options(self) -> bool:
        return False


class OpenAICompatibleAdapter(ProviderAdapter):
    """Adapter for OpenAI-compatible HTTP endpoints."""

    def _litellm_provider_prefix(self) -> str:
        if self.kind == "minimax":
            return "minimax"
        return "openai"

    def messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return _convert_system_messages_after_first_to_user(messages)

    def supports_stream_usage_options(self) -> bool:
        return True


class MiniMaxAdapter(ProviderAdapter):
    """MiniMax's chat endpoint expects only the first system message as system."""

    def _litellm_provider_prefix(self) -> str:
        return "minimax"

    def messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return _convert_system_messages_after_first_to_user(messages)

    def capabilities(self, base: LLMCapabilities) -> LLMCapabilities:
        return replace(
            base,
            supports_json_mode=False,
            supports_parallel_tool_calls=False,
        )


class AnthropicAdapter(ProviderAdapter):
    """Native Anthropic routing can preserve structured content blocks."""

    preserves_structured_content = True

    def _litellm_provider_prefix(self) -> str:
        return "anthropic"

    def capabilities(self, base: LLMCapabilities) -> LLMCapabilities:
        return replace(
            super().capabilities(base),
            supports_json_mode=True,
            supports_structured_content=True,
        )

    def payload_sampling_parameters(self) -> Dict[str, Any]:
        if _is_anthropic_opus_4_7_or_later(self.profile.model):
            return {}
        return super().payload_sampling_parameters()

    def payload_thinking_parameters(self) -> Dict[str, Any]:
        thinking_type = str(getattr(self.profile, "thinking_type", "") or "").strip().lower()
        if not thinking_type:
            return {}
        thinking: Dict[str, Any] = {"type": thinking_type}
        thinking_display = str(getattr(self.profile, "thinking_display", "") or "").strip().lower()
        if thinking_type != "disabled" and thinking_display:
            thinking["display"] = thinking_display
        return {"thinking": thinking}


class DeepSeekAdapter(ProviderAdapter):
    """DeepSeek thinking mode requires round-tripping reasoning_content."""

    preserves_reasoning_content = True

    def _litellm_provider_prefix(self) -> str:
        return "deepseek"

    def supports_explicit_tool_choice(self) -> bool:
        # DeepSeek V4 thinking mode rejects tool_choice on the official
        # OpenAI-compatible endpoint; omit it and let the model decide.
        return False


def get_provider_adapter(provider: ProviderConfig, profile: LLMProfile) -> ProviderAdapter:
    kind = str(provider.kind or "").strip().lower()
    compat_mode = str(provider.compat_mode or "").strip().lower()
    if kind == "minimax":
        return MiniMaxAdapter(provider, profile)
    if kind == "anthropic":
        return AnthropicAdapter(provider, profile)
    if kind == "deepseek":
        return DeepSeekAdapter(provider, profile)
    if kind in _NATIVE_LITELLM_PREFIX_BY_PROVIDER:
        return ProviderAdapter(provider, profile)
    if kind in _OPENAI_COMPAT_PROVIDER_KINDS or compat_mode in {"openai", "openai_compatible"}:
        return OpenAICompatibleAdapter(provider, profile)
    return ProviderAdapter(provider, profile)


def capabilities_for_adapter(
    provider: ProviderConfig,
    profile: LLMProfile,
    base: LLMCapabilities,
) -> LLMCapabilities:
    adapter = get_provider_adapter(provider, profile)
    capabilities = adapter.capabilities(base)
    if not profile.streaming:
        capabilities = replace(capabilities, supports_streaming=False)
    if profile.tool_calling_mode == "disabled":
        capabilities = replace(
            capabilities,
            supports_tool_calling=False,
            supports_parallel_tool_calls=False,
        )
    elif profile.tool_calling_mode != "parallel":
        capabilities = replace(capabilities, supports_parallel_tool_calls=False)
    return capabilities
