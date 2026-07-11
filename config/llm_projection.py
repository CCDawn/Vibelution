from __future__ import annotations

import copy
from typing import Any

from .llm_credentials import canonicalize_credential_ref
from .llm_identity import make_model_ref, split_model_ref, validate_provider_id


_CREDENTIAL_OWNERSHIP_FIELDS = frozenset({"api_key", "api_key_env", "credential_ref"})
V2_RUNTIME_OVERRIDE_FIELDS = frozenset(
    {
        "compat",
        "connect_timeout",
        "contract",
        "discovery_enabled",
        "max_output_tokens",
        "prompt_cache",
        "protocol",
        "reasoning_effort",
        "reasoning_state_field",
        "retry_policy",
        "streaming",
        "strict_compatibility",
        "supports_image_input",
        "temperature",
        "thinking_display",
        "thinking_type",
        "timeout",
        "tool_calling_mode",
        "transport",
    }
)


def _validate_credential_ownership(
    payload: dict[str, Any],
    scope: str,
    *,
    allowed: frozenset[str] = frozenset(),
) -> None:
    forbidden = sorted((_CREDENTIAL_OWNERSHIP_FIELDS - allowed).intersection(payload))
    if forbidden:
        raise ValueError(f"schema v2 credential ownership violation: {scope}.{forbidden[0]}")


def _validate_runtime_overrides(payload: dict[str, Any], scope: str) -> None:
    _validate_credential_ownership(payload, scope)
    unsupported = sorted(set(payload) - V2_RUNTIME_OVERRIDE_FIELDS)
    if unsupported:
        raise ValueError(f"unsupported schema v2 runtime field: {scope}.{unsupported[0]}")


def _credential_env(credential_ref: str) -> str:
    canonical = canonicalize_credential_ref(credential_ref)
    return canonical.removeprefix("env:") if canonical.startswith("env:") else ""


def _runtime_provider(provider_id: str, provider: dict[str, Any]) -> dict[str, Any]:
    default_wire = str(provider.get("protocols", {}).get("default") or "").strip()
    vendor = str(provider.get("vendor") or "custom").strip().lower()
    framework = str(provider.get("deployment", {}).get("runtime_framework") or "").strip().lower()
    driver = str(provider.get("driver") or "openai").strip().lower()
    legacy_kind = framework or (vendor if vendor not in {"custom", "multi_model"} else driver)
    credential_ref = str(provider.get("credential_ref") or "none").strip()
    return {
        **copy.deepcopy(provider),
        "provider_id": provider_id,
        "kind": legacy_kind,
        "api": default_wire.replace("_", "-"),
        "api_key_env": _credential_env(credential_ref),
        "requires_api_key": bool(provider.get("requires_credential", provider.get("auth_kind") != "none")),
        "compat_mode": "openai" if driver == "openai" else "native",
        "legacy_inference_allowed": False,
    }


def project_v2_llm_for_runtime(public_config: dict[str, Any]) -> dict[str, Any]:
    projected = copy.deepcopy(public_config)
    llm = projected.setdefault("llm", {})
    if int(llm.get("schema_version") or 1) != 2:
        return projected
    providers = llm.get("providers")
    profiles = llm.get("profiles")
    if not isinstance(providers, dict) or not isinstance(profiles, dict):
        raise ValueError("llm.providers and llm.profiles must be objects in schema v2")
    if not providers:
        raise ValueError("llm.providers must not be empty in schema v2")
    if not profiles:
        raise ValueError("llm.profiles must not be empty in schema v2")
    runtime_providers: dict[str, dict[str, Any]] = {}
    runtime_models: dict[str, dict[str, Any]] = {}
    for provider_id, raw_provider in providers.items():
        validate_provider_id(str(provider_id))
        if not isinstance(raw_provider, dict):
            raise ValueError(f"llm.providers.{provider_id} must be an object")
        _validate_credential_ownership(raw_provider, "provider", allowed=frozenset({"credential_ref"}))
        runtime_providers[str(provider_id)] = _runtime_provider(str(provider_id), raw_provider)
        raw_models = raw_provider.get("models", {})
        if not isinstance(raw_models, dict):
            raise ValueError(f"llm.providers.{provider_id}.models must be an object")
        for model_key, raw_model in raw_models.items():
            model_ref = make_model_ref(str(provider_id), str(model_key))
            if not isinstance(raw_model, dict):
                raise ValueError(f"pinned model {model_ref} must be an object")
            _validate_credential_ownership(raw_model, "model")
            raw_upstream_id = raw_model.get("upstream_id")
            if not isinstance(raw_upstream_id, str) or not raw_upstream_id.strip():
                raise ValueError(f"pinned model {model_ref} requires upstream_id")
            defaults = raw_model.get("defaults", {}) if isinstance(raw_model.get("defaults"), dict) else {}
            _validate_runtime_overrides(defaults, "defaults")
            runtime_models[model_ref] = {
                **copy.deepcopy(raw_model),
                **copy.deepcopy(defaults),
                "provider_id": str(provider_id),
                "model": raw_upstream_id,
                "label": str(raw_model.get("label") or raw_upstream_id),
                "transport": str(
                    raw_model.get("wire_protocol") or raw_provider.get("protocols", {}).get("default") or ""
                ),
                "contract": str(raw_model.get("interaction_contract") or "tool_chat"),
                "protocol": str(raw_model.get("model_protocol") or ""),
                "compat": copy.deepcopy(raw_model.get("compatibility", {})),
                "model_ref": model_ref,
            }
    runtime_profiles: dict[str, dict[str, Any]] = {}
    aliases = llm.get("model_aliases", {}) if isinstance(llm.get("model_aliases"), dict) else {}
    from .models import LLMConfig

    alias_resolver = LLMConfig.model_construct(model_aliases=aliases)
    for profile_id, raw_profile in profiles.items():
        if not isinstance(raw_profile, dict):
            raise ValueError(f"llm.profiles.{profile_id} must be an object")
        _validate_credential_ownership(raw_profile, "profile")
        requested_ref = str(raw_profile.get("model_ref") or "").strip()
        model_ref = alias_resolver.resolve_model_ref(requested_ref)
        provider_id, model_key = split_model_ref(model_ref)
        canonical_ref = make_model_ref(provider_id, model_key)
        model = runtime_models.get(canonical_ref)
        if model is None:
            raise ValueError(f"unknown profile model_ref: {requested_ref}")
        overrides = raw_profile.get("overrides", {}) if isinstance(raw_profile.get("overrides"), dict) else {}
        _validate_runtime_overrides(overrides, "overrides")
        runtime_profiles[str(profile_id)] = {
            **copy.deepcopy(model),
            **copy.deepcopy(overrides),
            "profile_id": str(profile_id),
            "provider_id": provider_id,
            "model_ref": canonical_ref,
        }
    llm["providers"] = runtime_providers
    llm["profiles"] = runtime_profiles
    llm["model_library"] = runtime_models
    return projected


__all__ = ["project_v2_llm_for_runtime"]
