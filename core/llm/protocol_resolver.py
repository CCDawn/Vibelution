# -*- coding: utf-8 -*-
"""Resolve model protocol routes from profile/provider configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from config import LLMProfile, ProviderConfig

from .protocols import CompatPolicy, ModelProtocol, ProtocolPolicy, compat_override_fields, get_protocol_policy


@dataclass(frozen=True)
class ResolvedProtocolRoute:
    profile_id: str
    model_id: str
    provider_id: str
    provider_kind: str
    provider_api: str
    model: str
    protocol: ModelProtocol
    policy: ProtocolPolicy
    compat: CompatPolicy
    source: str
    warnings: tuple[str, ...] = ()

    def log_summary(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol.value,
            "protocolSource": self.source,
            "modelId": self.model_id,
            "providerId": self.provider_id,
            "providerKind": self.provider_kind,
            "providerApi": self.provider_api,
            "protocolWarnings": list(self.warnings),
            "reasoningRoundtripEnabled": self.compat.reasoning_roundtrip,
            "thinkingFormat": self.compat.thinking_format,
            "toolChoiceMode": self.compat.tool_choice_mode,
            "strictMessageKeys": self.compat.strict_message_keys,
            "requiresStringContent": self.compat.requires_string_content,
            "allowAssistantPrefill": self.compat.allow_assistant_prefill,
        }


def _read_optional_string(owner: Any, name: str) -> str:
    if isinstance(owner, dict):
        return str(owner.get(name) or "").strip()
    return str(getattr(owner, name, "") or "").strip()


def _read_optional_dict(owner: Any, name: str) -> dict[str, Any]:
    value = owner.get(name) if isinstance(owner, dict) else getattr(owner, name, None)
    return value if isinstance(value, dict) else {}


def _thinking_enabled(profile: LLMProfile) -> bool:
    value = _read_optional_string(profile, "thinking_type").lower()
    return bool(value and value != "disabled")


def _model_family(model: str) -> str:
    normalized = str(model or "").strip().lower()
    if "qwen" in normalized:
        return "qwen"
    if "deepseek" in normalized:
        return "deepseek"
    if "claude" in normalized:
        return "claude"
    if "gpt-" in normalized or normalized.startswith("o"):
        return "openai"
    if "minimax" in normalized:
        return "minimax"
    return ""


def _base_url_is_localish(base_url: str) -> bool:
    try:
        host = (urlparse(str(base_url or "")).hostname or "").strip().lower()
    except Exception:
        host = ""
    if not host:
        return False
    return (
        host in {"localhost", "127.0.0.1", "::1"}
        or host.startswith("192.168.")
        or host.startswith("10.")
        or host.startswith("172.16.")
        or host.startswith("172.17.")
        or host.startswith("172.18.")
        or host.startswith("172.19.")
        or host.startswith("172.2")
        or host.startswith("172.30.")
        or host.startswith("172.31.")
    )


def _normalize_provider_api(provider: ProviderConfig) -> str:
    return _read_optional_string(provider, "api").lower().replace("_", "-")


def _protocol_from_provider_api(provider_api: str, provider_kind: str, profile: LLMProfile) -> ModelProtocol | None:
    api = str(provider_api or "").strip().lower()
    if not api:
        return None
    if api in {"openai-responses", "responses"}:
        return ModelProtocol.RELAY_RESPONSES if provider_kind == "relay" else ModelProtocol.OPENAI_RESPONSES
    if api in {"anthropic-messages", "anthropic"}:
        return ModelProtocol.ANTHROPIC_THINKING if _thinking_enabled(profile) else ModelProtocol.ANTHROPIC_CHAT
    if api in {"deepseek-chat", "deepseek-reasoning"}:
        return ModelProtocol.DEEPSEEK_REASONING
    if api in {"minimax-chat", "minimax"}:
        return ModelProtocol.MINIMAX_CHAT
    if api in {"local-openai-compatible", "openai-completions", "openai-chat-completions"}:
        return None
    if api in {"qwen-openai-compatible", "qwen"}:
        return ModelProtocol.QWEN_THINKING_NO_PREFILL if _thinking_enabled(profile) else ModelProtocol.QWEN_OPENAI_COMPAT
    return None


def _protocol_from_contract(provider_kind: str, profile: LLMProfile) -> ModelProtocol | None:
    transport = _read_optional_string(profile, "transport").lower() or "chat_completions"
    contract = _read_optional_string(profile, "contract").lower() or "tool_chat"
    thinking_enabled = _thinking_enabled(profile)
    if transport == "responses":
        return ModelProtocol.RELAY_RESPONSES if provider_kind == "relay" else ModelProtocol.OPENAI_RESPONSES
    if provider_kind == "anthropic":
        return ModelProtocol.ANTHROPIC_THINKING if thinking_enabled else ModelProtocol.ANTHROPIC_CHAT
    if provider_kind == "deepseek" or contract == "reasoning_chat":
        return ModelProtocol.DEEPSEEK_REASONING
    if provider_kind == "minimax":
        return ModelProtocol.MINIMAX_CHAT
    if contract == "basic_chat":
        return ModelProtocol.BASIC_CHAT_NO_TOOLS
    if contract == "tool_chat" and provider_kind in {"openai", "relay"}:
        return ModelProtocol.OPENAI_CHAT_TOOLS
    return None


def _protocol_from_model_hint(provider: ProviderConfig, profile: LLMProfile) -> ModelProtocol | None:
    provider_kind = _read_optional_string(provider, "kind").lower()
    model = _read_optional_string(profile, "model")
    family = _model_family(model)
    thinking_enabled = _thinking_enabled(profile)
    local_runtime = provider_kind in {"llamacpp", "ollama"}
    localish = provider_kind == "local" or local_runtime or _base_url_is_localish(_read_optional_string(provider, "base_url"))
    if local_runtime and family == "qwen" and thinking_enabled:
        return ModelProtocol.LLAMACPP_QWEN_THINKING
    if localish and family == "qwen" and thinking_enabled:
        return ModelProtocol.QWEN_THINKING_NO_PREFILL
    if local_runtime:
        return ModelProtocol.LLAMACPP_BASIC
    if family == "qwen" and thinking_enabled:
        return ModelProtocol.QWEN_THINKING_NO_PREFILL
    if family == "qwen":
        return ModelProtocol.QWEN_OPENAI_COMPAT
    return None


def resolve_model_protocol(
    profile: LLMProfile,
    provider: ProviderConfig,
    *,
    model_entry: Any = None,
) -> ResolvedProtocolRoute:
    warnings: list[str] = []
    provider_kind = _read_optional_string(provider, "kind").lower() or "unknown"
    provider_api = _normalize_provider_api(provider)
    model_id = _read_optional_string(model_entry, "modelId") or _read_optional_string(model_entry, "model_id")
    if not model_id:
        model_id = _read_optional_string(profile, "profile_id") or _read_optional_string(profile, "model")
    explicit_protocol = _read_optional_string(model_entry, "protocol") or _read_optional_string(profile, "protocol")
    source = "fallback"
    protocol: ModelProtocol | None = None
    if explicit_protocol:
        try:
            protocol = ModelProtocol(explicit_protocol.strip().lower())
            source = "explicit_model"
        except ValueError:
            warnings.append(f"unknown explicit protocol `{explicit_protocol}`; falling back to inference")
    if protocol is None:
        protocol = _protocol_from_provider_api(provider_api, provider_kind, profile)
        if protocol is not None:
            source = "provider_api"
    if protocol is None:
        protocol = _protocol_from_contract(provider_kind, profile)
        if protocol is not None:
            source = "profile_contract"
    if protocol is None:
        protocol = _protocol_from_model_hint(provider, profile)
        if protocol is not None:
            source = "inferred"
    if protocol is None:
        protocol = ModelProtocol.BASIC_CHAT_NO_TOOLS
        warnings.append("model protocol fell back to basic_chat_no_tools")
    if source in {"profile_contract", "inferred", "fallback"} and not explicit_protocol and not provider_api:
        warnings.append("model_protocol.missing_explicit_protocol")
    if source == "inferred":
        warnings.append("model_protocol.inferred")
        if provider_kind in {"local", "llamacpp", "ollama"} or _base_url_is_localish(_read_optional_string(provider, "base_url")):
            warnings.append("model_protocol.local_advanced_route_warning")
    policy = get_protocol_policy(protocol)
    raw_compat = _read_optional_dict(model_entry, "compat") or _read_optional_dict(profile, "compat")
    compat = policy.compat_defaults.merged(
        CompatPolicy.from_raw(raw_compat),
        override_fields=compat_override_fields(raw_compat),
    )
    return ResolvedProtocolRoute(
        profile_id=_read_optional_string(profile, "profile_id"),
        model_id=model_id,
        provider_id=_read_optional_string(provider, "provider_id") or _read_optional_string(profile, "provider_id"),
        provider_kind=provider_kind,
        provider_api=provider_api,
        model=_read_optional_string(profile, "model"),
        protocol=protocol,
        policy=policy,
        compat=compat,
        source=source,
        warnings=tuple(warnings),
    )


__all__ = ["ResolvedProtocolRoute", "resolve_model_protocol"]
