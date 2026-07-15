# -*- coding: utf-8 -*-
"""Resolve model protocol routes from profile/provider configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from config import LLMProfile, ProviderConfig

from .protocols import (
    CompatPolicy,
    ModelProtocol,
    ProtocolPolicy,
    WireProtocol,
    compat_override_fields,
    get_protocol_policy,
    wire_protocol_from_model_protocol_alias,
)


class ProtocolResolutionError(ValueError):
    def __init__(self, code: str, message: str, *, provider_id: str, model_ref: str) -> None:
        super().__init__(message)
        self.code = code
        self.provider_id = provider_id
        self.model_ref = model_ref


@dataclass(frozen=True)
class ResolvedProtocolRoute:
    profile_id: str
    model_id: str
    provider_id: str
    provider_kind: str
    provider_api: str
    model: str
    effective_model: str
    wire_protocol: WireProtocol
    adapter_id: str
    configured_endpoint: str
    runtime_endpoint: str
    protocol: ModelProtocol
    policy: ProtocolPolicy
    compat: CompatPolicy
    source: str
    wire_source: str
    source_scope: str
    warnings: tuple[str, ...] = ()

    def log_summary(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol.value,
            "selectedProtocol": self.protocol.value,
            "protocolSource": self.source,
            "wireProtocol": self.wire_protocol.value,
            "wireProtocolSource": self.wire_source,
            "wireProtocolSourceScope": self.source_scope,
            "adapterId": self.adapter_id,
            "effectiveModel": self.effective_model,
            "configuredEndpoint": self.configured_endpoint,
            "runtimeEndpoint": self.runtime_endpoint,
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
            "responsesContinuation": self.compat.responses_continuation,
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


def _normalize_wire_protocol(value: str) -> WireProtocol | None:
    normalized = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "openai_chat_completions": WireProtocol.CHAT_COMPLETIONS,
        "openai_completions": WireProtocol.CHAT_COMPLETIONS,
        "openai_responses": WireProtocol.RESPONSES,
        "anthropic": WireProtocol.ANTHROPIC_MESSAGES,
        "anthropic_messages": WireProtocol.ANTHROPIC_MESSAGES,
        "gemini": WireProtocol.GEMINI_GENERATE_CONTENT,
        "gemini_generate_content": WireProtocol.GEMINI_GENERATE_CONTENT,
    }
    if normalized in aliases:
        return aliases[normalized]
    try:
        return WireProtocol(normalized)
    except ValueError:
        return None


def _wire_protocol_from_model_entry(
    model_entry: Any,
    *,
    provider_id: str = "",
) -> WireProtocol | None:
    for field in ("wireProtocol", "wire_protocol", "apiMode", "api_mode"):
        raw = _read_optional_string(model_entry, field)
        if raw:
            wire_protocol = _normalize_wire_protocol(raw)
            if wire_protocol is None:
                raise ProtocolResolutionError(
                    "protocol_mismatch",
                    f"unknown explicit wire protocol `{raw}`",
                    provider_id=provider_id,
                    model_ref=_read_optional_string(model_entry, "model_ref"),
                )
            return wire_protocol
    return None


def _provider_default_wire(provider: ProviderConfig) -> WireProtocol | None:
    protocols = getattr(provider, "protocols", None)
    raw = str(getattr(protocols, "default", "") or "")
    return _normalize_wire_protocol(raw) if raw else None


def _driver_default_wire(provider: ProviderConfig) -> WireProtocol | None:
    driver = _read_optional_string(provider, "driver").lower()
    return {
        "openai": WireProtocol.CHAT_COMPLETIONS,
        "anthropic": WireProtocol.ANTHROPIC_MESSAGES,
        "gemini": WireProtocol.GEMINI_GENERATE_CONTENT,
    }.get(driver)


def _opencode_variant(provider: ProviderConfig) -> str:
    identity = " ".join(
        (
            _read_optional_string(provider, "provider_id"),
            _read_optional_string(provider, "kind"),
            _read_optional_string(provider, "api"),
            _read_optional_string(provider, "base_url"),
        )
    ).lower().replace("_", "-")
    if "opencode" not in identity:
        return ""
    if "opencode-go" in identity or "/go" in identity:
        return "go"
    return "zen"


def _wire_protocol_from_opencode(provider: ProviderConfig, effective_model: str) -> WireProtocol | None:
    variant = _opencode_variant(provider)
    model = str(effective_model or "").strip().lower()
    if variant == "zen":
        if "gpt" in model or "codex" in model or (len(model) > 1 and model[0] == "o" and model[1].isdigit()):
            return WireProtocol.RESPONSES
        if any(name in model for name in ("claude", "opus", "sonnet", "haiku", "qwen")):
            return WireProtocol.ANTHROPIC_MESSAGES
        return WireProtocol.CHAT_COMPLETIONS
    if variant == "go":
        if "minimax" in model or "qwen" in model:
            return WireProtocol.ANTHROPIC_MESSAGES
        if any(name in model for name in ("glm", "kimi", "deepseek", "mimo")):
            return WireProtocol.CHAT_COMPLETIONS
    return None


def _wire_protocol_from_provider_api(provider_api: str) -> WireProtocol | None:
    api = str(provider_api or "").strip().lower().replace("_", "-")
    if api in {"openai-responses", "responses"}:
        return WireProtocol.RESPONSES
    if api in {"anthropic", "anthropic-messages"}:
        return WireProtocol.ANTHROPIC_MESSAGES
    if api in {"gemini", "gemini-generate-content", "generate-content"}:
        return WireProtocol.GEMINI_GENERATE_CONTENT
    if api in {
        "deepseek-chat",
        "deepseek-reasoning",
        "local-openai-compatible",
        "minimax",
        "minimax-chat",
        "openai-chat-completions",
        "openai-completions",
        "qwen",
        "qwen-openai-compatible",
    }:
        return WireProtocol.CHAT_COMPLETIONS
    return None


def _wire_protocol_from_provider_kind(provider_kind: str) -> WireProtocol | None:
    kind = str(provider_kind or "").strip().lower().replace("-", "_")
    if kind == "anthropic":
        return WireProtocol.ANTHROPIC_MESSAGES
    if kind in {"gemini", "google_gemini"}:
        return WireProtocol.GEMINI_GENERATE_CONTENT
    return None


def _wire_protocol_from_endpoint(base_url: str) -> WireProtocol | None:
    try:
        parsed = urlparse(str(base_url or ""))
        host = (parsed.hostname or "").lower()
        path = (parsed.path or "").lower().rstrip("/")
    except Exception:
        return None
    if host == "api.anthropic.com" or host.endswith(".anthropic.com"):
        return WireProtocol.ANTHROPIC_MESSAGES
    if host == "generativelanguage.googleapis.com":
        return WireProtocol.GEMINI_GENERATE_CONTENT
    if path.endswith("/responses"):
        return WireProtocol.RESPONSES
    return None


def _legacy_runtime_endpoint(
    provider: ProviderConfig,
    configured_endpoint: str,
    wire_protocol: WireProtocol,
) -> str:
    endpoint = str(configured_endpoint or "").strip().rstrip("/")
    try:
        host = (urlparse(endpoint).hostname or "").lower()
    except Exception:
        host = ""
    official_opencode = host == "opencode.ai" or host.endswith(".opencode.ai")
    if not official_opencode:
        return endpoint
    if wire_protocol == WireProtocol.ANTHROPIC_MESSAGES:
        return endpoint[:-3] if endpoint.lower().endswith("/v1") else endpoint
    if wire_protocol in {WireProtocol.CHAT_COMPLETIONS, WireProtocol.RESPONSES}:
        return endpoint if endpoint.lower().endswith("/v1") else f"{endpoint}/v1"
    return endpoint


def _runtime_endpoint(
    provider: ProviderConfig,
    configured_endpoint: str,
    wire_protocol: WireProtocol,
    *,
    model_ref: str = "",
) -> str:
    endpoint = str(configured_endpoint or "").strip().rstrip("/")
    if bool(getattr(provider, "legacy_inference_allowed", True)):
        return _legacy_runtime_endpoint(provider, endpoint, wire_protocol)
    routes = getattr(getattr(provider, "protocols", None), "routes", {}) or {}
    relative = str(routes.get(wire_protocol.value) or "").strip()
    if not relative:
        relative = {
            WireProtocol.CHAT_COMPLETIONS: "chat/completions",
            WireProtocol.RESPONSES: "responses",
            WireProtocol.ANTHROPIC_MESSAGES: "v1/messages",
            WireProtocol.GEMINI_GENERATE_CONTENT: "v1beta/models:generateContent",
        }[wire_protocol]
    parsed = urlparse(relative)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or relative.startswith(("/", "\\")):
        raise ProtocolResolutionError(
            "protocol_mismatch",
            "provider protocol route must be a relative path without query or fragment",
            provider_id=_read_optional_string(provider, "provider_id"),
            model_ref=model_ref,
        )
    return f"{endpoint}/{relative.lstrip('/')}"


def _resolve_wire_protocol(
    *,
    model_entry: Any,
    explicit_model_protocol: ModelProtocol | None,
    profile: LLMProfile,
    provider: ProviderConfig,
    provider_kind: str,
    provider_api: str,
    effective_model: str,
    warnings: list[str],
) -> tuple[WireProtocol, str, str]:
    explicit_wire = _wire_protocol_from_model_entry(
        model_entry,
        provider_id=_read_optional_string(provider, "provider_id"),
    )
    allowed = tuple(getattr(getattr(provider, "protocols", None), "allowed", ()) or ())
    if explicit_wire is not None:
        if allowed and explicit_wire.value not in allowed:
            raise ProtocolResolutionError(
                "protocol_mismatch",
                "model wire protocol is not allowed by provider",
                provider_id=_read_optional_string(provider, "provider_id"),
                model_ref=_read_optional_string(model_entry, "model_ref"),
            )
        return explicit_wire, "explicit_model_wire", "model"
    if not bool(getattr(provider, "legacy_inference_allowed", True)):
        provider_default = _provider_default_wire(provider)
        if provider_default is not None:
            return provider_default, "provider_default", "provider"
        driver_default = _driver_default_wire(provider)
        if driver_default is not None:
            return driver_default, "driver_default", "driver"
        raise ProtocolResolutionError(
            "protocol_unknown",
            "schema v2 requires an explicit model, provider, or driver wire protocol",
            provider_id=_read_optional_string(provider, "provider_id"),
            model_ref=_read_optional_string(model_entry, "model_ref"),
        )
    if explicit_model_protocol is not None:
        migrated = wire_protocol_from_model_protocol_alias(explicit_model_protocol)
        if migrated is not None:
            warnings.append("wire_protocol.migrated_model_protocol_alias")
            return migrated, "model_protocol_alias", "model"
    provider_model_wire = _wire_protocol_from_opencode(provider, effective_model)
    if provider_model_wire is not None:
        warnings.append("wire_protocol.legacy_inference")
        return provider_model_wire, "provider_effective_model_rule", "provider_model"
    provider_wire = _wire_protocol_from_provider_api(provider_api)
    if provider_wire is not None:
        warnings.append("wire_protocol.legacy_inference")
        return provider_wire, "provider_api", "provider"
    provider_kind_wire = _wire_protocol_from_provider_kind(provider_kind)
    if provider_kind_wire is not None:
        warnings.append("wire_protocol.legacy_inference")
        return provider_kind_wire, "provider_kind", "provider"
    profile_transport = _normalize_wire_protocol(_read_optional_string(profile, "transport"))
    if profile_transport is not None:
        warnings.append("wire_protocol.legacy_inference")
        return profile_transport, "profile_transport", "profile"
    endpoint_wire = _wire_protocol_from_endpoint(_read_optional_string(provider, "base_url"))
    if endpoint_wire is not None:
        warnings.append("wire_protocol.legacy_inference")
        return endpoint_wire, "endpoint_heuristic", "heuristic"
    if _is_openai_compatible_provider(provider_kind, _read_optional_string(provider, "compat_mode")):
        warnings.append("wire_protocol.legacy_inference")
        return WireProtocol.CHAT_COMPLETIONS, "declared_openai_compatibility", "fallback"
    raise ProtocolResolutionError(
        "protocol_unknown",
        f"unable to resolve wire protocol for provider={provider_kind or 'unknown'} model={effective_model or 'unknown'}",
        provider_id=_read_optional_string(provider, "provider_id"),
        model_ref=_read_optional_string(model_entry, "model_ref"),
    )


def _is_openai_compatible_provider(provider_kind: str, compat_mode: str = "") -> bool:
    kind = str(provider_kind or "").strip().lower()
    compat = str(compat_mode or "").strip().lower().replace("-", "_")
    if kind in {"anthropic", "deepseek", "llamacpp", "minimax", "ollama", "local"}:
        return False
    return kind in {
        "aliyun",
        "openai",
        "openai_compatible",
        "relay",
        "siliconflow",
        "xiaomi",
        "zhipu",
    } or compat in {"openai", "openai_compatible"}


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


def _xiaomi_mimo_protocol(profile: LLMProfile, provider: ProviderConfig) -> ModelProtocol:
    model = _read_optional_string(profile, "model").lower()
    base_url = _read_optional_string(provider, "base_url").lower()
    if "token-plan" in base_url or "mimo-v2.5-pro" in model or model.endswith("-pro"):
        return ModelProtocol.XIAOMI_MIMO_TOKEN_PLAN_OPENAI_COMPAT
    return ModelProtocol.XIAOMI_MIMO_MULTIMODAL_OPENAI_COMPAT


def _protocol_from_contract(provider_kind: str, provider: ProviderConfig, profile: LLMProfile) -> ModelProtocol | None:
    transport = _read_optional_string(profile, "transport").lower() or "chat_completions"
    contract = _read_optional_string(profile, "contract").lower() or "tool_chat"
    thinking_enabled = _thinking_enabled(profile)
    compat_mode = _read_optional_string(provider, "compat_mode")
    model_family = _model_family(_read_optional_string(profile, "model"))
    localish = provider_kind in {"local", "llamacpp", "ollama"} or _base_url_is_localish(_read_optional_string(provider, "base_url"))
    if transport == "responses":
        return ModelProtocol.RELAY_RESPONSES if provider_kind == "relay" else ModelProtocol.OPENAI_RESPONSES
    if provider_kind == "anthropic":
        return ModelProtocol.ANTHROPIC_THINKING if thinking_enabled else ModelProtocol.ANTHROPIC_CHAT
    if provider_kind == "xiaomi":
        return _xiaomi_mimo_protocol(profile, provider)
    if provider_kind == "deepseek" or model_family == "deepseek":
        return ModelProtocol.DEEPSEEK_REASONING
    if contract == "reasoning_chat":
        if model_family == "qwen":
            return ModelProtocol.QWEN_THINKING_NO_PREFILL if thinking_enabled else ModelProtocol.QWEN_OPENAI_COMPAT
        if _is_openai_compatible_provider(provider_kind, compat_mode):
            return ModelProtocol.OPENAI_CHAT_TOOLS
    if provider_kind == "minimax":
        return ModelProtocol.MINIMAX_CHAT
    if contract == "basic_chat":
        return ModelProtocol.BASIC_CHAT_NO_TOOLS
    if contract == "tool_chat" and model_family == "qwen" and not localish:
        return ModelProtocol.QWEN_THINKING_NO_PREFILL if thinking_enabled else ModelProtocol.QWEN_OPENAI_COMPAT
    if contract == "tool_chat" and _is_openai_compatible_provider(provider_kind, compat_mode):
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
    effective_model = (
        _read_optional_string(model_entry, "model")
        or _read_optional_string(model_entry, "modelName")
        or _read_optional_string(model_entry, "model_name")
        or _read_optional_string(profile, "model")
    )
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
        except ValueError as exc:
            raise ProtocolResolutionError(
                "protocol_mismatch",
                f"unknown explicit model protocol `{explicit_protocol}`",
                provider_id=_read_optional_string(profile, "provider_id") or provider_kind,
                model_ref=_read_optional_string(model_entry, "model_ref") or effective_model,
            ) from exc
    if protocol is None:
        protocol = _protocol_from_provider_api(provider_api, provider_kind, profile)
        if protocol is not None:
            source = "provider_api"
    if protocol is None:
        protocol = _protocol_from_contract(provider_kind, provider, profile)
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
    wire_protocol, wire_source, source_scope = _resolve_wire_protocol(
        model_entry=model_entry,
        explicit_model_protocol=protocol if explicit_protocol else None,
        profile=profile,
        provider=provider,
        provider_kind=provider_kind,
        provider_api=provider_api,
        effective_model=effective_model,
        warnings=warnings,
    )
    configured_endpoint = _read_optional_string(provider, "base_url")
    return ResolvedProtocolRoute(
        profile_id=_read_optional_string(profile, "profile_id"),
        model_id=model_id,
        provider_id=_read_optional_string(provider, "provider_id") or _read_optional_string(profile, "provider_id"),
        provider_kind=provider_kind,
        provider_api=provider_api,
        model=effective_model,
        effective_model=effective_model,
        wire_protocol=wire_protocol,
        adapter_id=wire_protocol.value,
        configured_endpoint=configured_endpoint,
        runtime_endpoint=_runtime_endpoint(
            provider,
            configured_endpoint,
            wire_protocol,
            model_ref=_read_optional_string(model_entry, "model_ref"),
        ),
        protocol=protocol,
        policy=policy,
        compat=compat,
        source=source,
        wire_source=wire_source,
        source_scope=source_scope,
        warnings=tuple(warnings),
    )


__all__ = ["ProtocolResolutionError", "ResolvedProtocolRoute", "resolve_model_protocol"]
