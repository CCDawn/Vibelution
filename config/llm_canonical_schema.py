"""Strict ingress for canonical LLM v2 configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from pydantic import ValidationError

from .models import (
    LLMConfig,
    LLMDiscoveryConfig,
    LLMProfile,
    PinnedModelConfig,
    PinnedModelDefaults,
    PromptCacheConfig,
    ProviderConfig,
    ProviderDeploymentConfig,
    ProviderDiscoverySettings,
    ProviderProtocolsConfig,
)


@dataclass(frozen=True, slots=True)
class CanonicalLLMSchemaIssue:
    code: str
    path: str
    message: str


class CanonicalLLMConfigError(ValueError):
    def __init__(self, issues: tuple[CanonicalLLMSchemaIssue, ...]) -> None:
        self.issues = issues
        super().__init__("; ".join(f"{item.path}: {item.message}" for item in issues))


_INTERACTION_CONTRACTS = {"basic_chat", "tool_chat", "reasoning_chat", "responses_agent"}
_WIRE_PROTOCOLS = {
    "chat_completions",
    "responses",
    "anthropic_messages",
    "gemini_generate_content",
}
_MODEL_PROTOCOLS = {
    "basic_chat_no_tools",
    "openai_chat_tools",
    "openai_responses",
    "anthropic_chat",
    "anthropic_thinking",
    "deepseek_reasoning",
    "xiaomi_mimo_multimodal_openai_compat",
    "xiaomi_mimo_token_plan_openai_compat",
    "qwen_openai_compat",
    "qwen_thinking_no_prefill",
    "llamacpp_basic",
    "llamacpp_qwen_thinking",
    "minimax_chat",
    "relay_responses",
}


def _unknown_fields(value: Any, model_type: type, path: str) -> list[CanonicalLLMSchemaIssue]:
    if not isinstance(value, Mapping):
        return []
    allowed = set(model_type.model_fields)
    return [
        CanonicalLLMSchemaIssue(
            "unknown_field",
            f"{path}.{key}" if path else str(key),
            "unknown canonical field",
        )
        for key in value
        if key not in allowed
    ]


def _validate_known_shape(payload: Mapping[str, Any]) -> list[CanonicalLLMSchemaIssue]:
    issues = _unknown_fields(payload, LLMConfig, "")
    providers = payload.get("providers")
    if isinstance(providers, Mapping):
        for provider_id, raw_provider in providers.items():
            provider_path = f"providers.{provider_id}"
            issues.extend(_unknown_fields(raw_provider, ProviderConfig, provider_path))
            if not isinstance(raw_provider, Mapping):
                continue
            issues.extend(_unknown_fields(raw_provider.get("protocols", {}), ProviderProtocolsConfig, f"{provider_path}.protocols"))
            issues.extend(_unknown_fields(raw_provider.get("discovery", {}), ProviderDiscoverySettings, f"{provider_path}.discovery"))
            issues.extend(_unknown_fields(raw_provider.get("deployment", {}), ProviderDeploymentConfig, f"{provider_path}.deployment"))
            models = raw_provider.get("models")
            if isinstance(models, Mapping):
                for model_key, raw_model in models.items():
                    model_path = f"{provider_path}.models.{model_key}"
                    issues.extend(_unknown_fields(raw_model, PinnedModelConfig, model_path))
                    if isinstance(raw_model, Mapping):
                        defaults = raw_model.get("defaults", {})
                        defaults_path = f"{model_path}.defaults"
                        issues.extend(_unknown_fields(defaults, PinnedModelDefaults, defaults_path))
                        if isinstance(defaults, Mapping):
                            issues.extend(
                                _unknown_fields(
                                    defaults.get("prompt_cache", {}),
                                    PromptCacheConfig,
                                    f"{defaults_path}.prompt_cache",
                                )
                            )
    profiles = payload.get("profiles")
    if isinstance(profiles, Mapping):
        for profile_id, raw_profile in profiles.items():
            issues.extend(_unknown_fields(raw_profile, LLMProfile, f"profiles.{profile_id}"))
    issues.extend(_unknown_fields(payload.get("discovery", {}), LLMDiscoveryConfig, "discovery"))
    return issues


def _validate_protocol_layers(payload: Mapping[str, Any]) -> list[CanonicalLLMSchemaIssue]:
    issues: list[CanonicalLLMSchemaIssue] = []
    providers = payload.get("providers")
    if not isinstance(providers, Mapping):
        return issues
    for provider_id, raw_provider in providers.items():
        if not isinstance(raw_provider, Mapping):
            continue
        provider_path = f"providers.{provider_id}"
        if str(raw_provider.get("api_key") or "").strip():
            issues.append(CanonicalLLMSchemaIssue("inline_secret_forbidden", f"{provider_path}.api_key", "canonical config accepts credential_ref, not inline secret values"))
        protocols = raw_provider.get("protocols")
        if isinstance(protocols, Mapping):
            values = [("default", protocols.get("default"))]
            values.extend(("allowed", item) for item in (protocols.get("allowed") or []))
            for field, value in values:
                normalized = str(value or "").strip()
                if normalized and normalized not in _WIRE_PROTOCOLS:
                    issues.append(CanonicalLLMSchemaIssue("unknown_wire_protocol", f"{provider_path}.protocols.{field}", f"unknown LLM wire protocol `{normalized}`"))
        models = raw_provider.get("models")
        if not isinstance(models, Mapping):
            continue
        for model_key, raw_model in models.items():
            if not isinstance(raw_model, Mapping):
                continue
            model_path = f"{provider_path}.models.{model_key}"
            wire = str(raw_model.get("wire_protocol") or "").strip()
            if wire and wire not in _WIRE_PROTOCOLS:
                issues.append(CanonicalLLMSchemaIssue("unknown_wire_protocol", f"{model_path}.wire_protocol", f"unknown LLM wire protocol `{wire}`"))
            interaction = str(raw_model.get("interaction_contract") or "").strip()
            if interaction and interaction not in _INTERACTION_CONTRACTS:
                issues.append(CanonicalLLMSchemaIssue("unknown_interaction_contract", f"{model_path}.interaction_contract", f"unknown interaction contract `{interaction}`"))
            model_protocol = str(raw_model.get("model_protocol") or "").strip()
            if model_protocol in _INTERACTION_CONTRACTS:
                issues.append(CanonicalLLMSchemaIssue("interaction_contract_in_model_protocol", f"{model_path}.model_protocol", "interaction contract must not be stored as model protocol"))
            elif model_protocol and model_protocol not in _MODEL_PROTOCOLS:
                issues.append(CanonicalLLMSchemaIssue("unknown_model_protocol", f"{model_path}.model_protocol", f"unknown model protocol `{model_protocol}`"))
    return issues


def validate_canonical_llm_payload(payload: Mapping[str, Any]) -> LLMConfig:
    if not isinstance(payload, Mapping):
        raise CanonicalLLMConfigError((CanonicalLLMSchemaIssue("invalid_root", "", "LLM config must be a mapping"),))
    issues = [*_validate_known_shape(payload), *_validate_protocol_layers(payload)]
    if issues:
        raise CanonicalLLMConfigError(tuple(sorted(issues, key=lambda item: (item.path, item.code))))
    try:
        return LLMConfig.model_validate(dict(payload))
    except ValidationError as exc:
        converted = tuple(
            CanonicalLLMSchemaIssue(
                "validation_error",
                ".".join(str(item) for item in error.get("loc", ())),
                str(error.get("msg") or "invalid canonical value"),
            )
            for error in exc.errors(include_url=False, include_input=False)
        )
        raise CanonicalLLMConfigError(converted) from exc


__all__ = ["CanonicalLLMConfigError", "CanonicalLLMSchemaIssue", "validate_canonical_llm_payload"]
