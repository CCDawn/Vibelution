"""Build fixed-template-derived default operator LLM config (schema v2).

Vendor templates live in project code (`LLM_MODEL_PRESETS`). This module only
materializes first-run operator instances that reference `env:VAR` credentials.
It never writes secret values into config.toml.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from config.llm_credentials import canonicalize_credential_ref, resolve_credential_ref
from config.llm_identity import (
    make_model_key,
    make_model_ref,
    normalize_provider_endpoint,
    provider_identity_fingerprint,
    validate_provider_id,
)
from config.toml_writer import dumps_public_config

EnvReader = Callable[[str], str | None]

_LOCAL_PROVIDER_ID = "local_openai"
_LOCAL_MODEL_KEY = "local-model"
_LOCAL_MODEL_REF = f"{_LOCAL_PROVIDER_ID}/{_LOCAL_MODEL_KEY}"
_LEGACY_THIN_LOCAL_ONLY_STARTER_TEXT = """# Vibelution operator config
[llm]
schema_version = 2

[llm.providers.local_openai]
label = "Local OpenAI-compatible service"
service_class = "local_runtime"
vendor = "custom"
driver = "openai"
base_url = "http://127.0.0.1:8000/v1"
auth_kind = "none"
credential_ref = "none"
requires_credential = false

[llm.providers.local_openai.protocols]
default = "chat_completions"
allowed = ["chat_completions"]

[llm.providers.local_openai.discovery]
mode = "auto"
adapter = "openai_compatible"
cache_ttl_seconds = 300

[llm.providers.local_openai.models.local-model]
upstream_id = "local-model"
label = "Local model"
enabled = true

[llm.profiles.primary]
model_ref = "local_openai/local-model"
"""
_LEGACY_THIN_LOCAL_ONLY_STARTER_PAYLOAD = tomllib.loads(
    _LEGACY_THIN_LOCAL_ONLY_STARTER_TEXT
)

# Skip placeholder / free-form custom templates from first-run bootstrap.
_SKIP_PRESET_IDS = frozenset(
    {
        "custom_openai_compatible_relay",
        "custom_relay_responses",
    }
)

# Models that should not become dialogue primary profiles.
_NON_DIALOGUE_UPSTREAM_MARKERS = (
    "image",
    "dall-e",
    "whisper",
    "tts",
    "embedding",
    "moderation",
    "realtime",
    "sora",
)

_PROFILE_IDS = (
    "primary",
    "mental_model",
    "subagent_worker",
    "supervised_baseline",
    "supervised_candidate",
    "research_broad",
    "research_deep",
    "research_review",
)


def _read_env_default(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or not str(value).strip():
        return None
    return str(value)


def _service_class(kind: str, base_url: str) -> str:
    token = str(kind or "").strip().lower()
    if token in {"local", "local_runtime", "ollama", "llamacpp"}:
        return "local_runtime"
    host = (urlsplit(base_url).hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return "local_runtime"
    if token == "relay":
        return "relay"
    if token in {"openrouter", "aggregator", "siliconflow"}:
        return "aggregator"
    return "official_api"


def _driver(kind: str, compat_mode: str) -> str:
    token = str(kind or "").strip().lower()
    compat = str(compat_mode or "").strip().lower()
    if token == "anthropic" or compat == "native":
        return "anthropic" if token == "anthropic" else "openai"
    return "openai"


def _vendor(kind: str) -> str:
    token = str(kind or "").strip().lower().replace("-", "_")
    if token in {"local", "local_runtime", "ollama", "llamacpp"}:
        return "custom"
    if token in {"openai_compatible"}:
        return "custom"
    return token or "custom"


def _is_dialogue_upstream(upstream_id: str) -> bool:
    text = str(upstream_id or "").strip().lower()
    if not text:
        return False
    return not any(marker in text for marker in _NON_DIALOGUE_UPSTREAM_MARKERS)


def _protocol_bundle(transports: set[str]) -> dict[str, Any]:
    allowed = sorted(transports) if transports else ["chat_completions"]
    # Prefer chat_completions as default when available for broad agent tooling.
    default = "chat_completions" if "chat_completions" in allowed else allowed[0]
    return {"default": default, "allowed": allowed}


def _local_provider() -> dict[str, Any]:
    return {
        "label": "Local OpenAI-compatible service",
        "service_class": "local_runtime",
        "vendor": "custom",
        "driver": "openai",
        "base_url": "http://127.0.0.1:8000/v1",
        "auth_kind": "none",
        "credential_ref": "none",
        "requires_credential": False,
        "protocols": {"default": "chat_completions", "allowed": ["chat_completions"]},
        "discovery": {
            "mode": "auto",
            "adapter": "openai_compatible",
            "cache_ttl_seconds": 300,
        },
        "models": {
            _LOCAL_MODEL_KEY: {
                "upstream_id": "local-model",
                "label": "Local model",
                "enabled": True,
                "defaults": {
                    "temperature": 0.3,
                    "max_output_tokens": 4096,
                    "timeout": 45,
                    "connect_timeout": 5,
                    "streaming": True,
                    "tool_calling_mode": "auto",
                },
            }
        },
    }


def _model_defaults_from_preset(model: dict[str, Any]) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    for key in (
        "temperature",
        "max_output_tokens",
        "timeout",
        "connect_timeout",
        "streaming",
        "tool_calling_mode",
    ):
        if key in model and model[key] is not None:
            defaults[key] = model[key]
    prompt_cache = model.get("prompt_cache")
    if isinstance(prompt_cache, dict) and prompt_cache:
        defaults["prompt_cache"] = dict(prompt_cache)
    return defaults


def build_default_llm_section(
    *,
    env_reader: EnvReader | None = None,
    include_unconfigured_providers: bool = True,
    credential_env_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Materialize schema-v2 llm section from project-fixed model presets."""

    # Delayed import avoids paths <-> public_config cycles at module import time.
    from config.public_config import LLM_MODEL_PRESETS, LLM_PROVIDER_TEMPLATE_LABELS

    reader = env_reader or _read_env_default
    raw_overrides = (
        preferred_runtime_env_overrides()
        if credential_env_overrides is None
        else credential_env_overrides
    )
    overrides = {
        str(key).strip(): str(value).strip()
        for key, value in raw_overrides.items()
        if str(key).strip() and str(value).strip()
    }

    # fingerprint -> provider_id
    fingerprint_to_id: dict[str, str] = {}
    providers: dict[str, dict[str, Any]] = {}
    transport_by_provider: dict[str, set[str]] = {}
    dialogue_candidates: list[tuple[int, str]] = []

    for preset_id, preset in LLM_MODEL_PRESETS.items():
        if preset_id in _SKIP_PRESET_IDS:
            continue
        if not isinstance(preset, dict):
            continue
        raw_provider = preset.get("provider")
        raw_model = preset.get("model")
        if not isinstance(raw_provider, dict) or not isinstance(raw_model, dict):
            continue

        provider_id = str(preset.get("provider_id") or preset_id).strip()
        try:
            provider_id = validate_provider_id(provider_id)
        except ValueError:
            continue

        base_url = str(raw_provider.get("base_url") or "").strip()
        if not base_url:
            continue
        try:
            base_url = normalize_provider_endpoint(base_url)
        except ValueError:
            continue

        kind = str(raw_provider.get("kind") or "").strip().lower()
        env_name = (
            overrides.get(provider_id)
            or overrides.get(preset_id)
            or str(raw_provider.get("api_key_env") or raw_model.get("api_key_env") or "").strip()
        )
        requires = bool(raw_provider.get("requires_api_key", True))
        if not requires or not env_name:
            credential_ref = "none"
            auth_kind = "none"
        else:
            try:
                credential_ref = canonicalize_credential_ref(f"env:{env_name}")
            except ValueError:
                continue
            auth_kind = "api_key"

        if auth_kind == "api_key" and not include_unconfigured_providers:
            resolution = resolve_credential_ref(credential_ref, env_reader=reader)
            if not resolution.secret:
                continue

        fingerprint = provider_identity_fingerprint(
            base_url,
            credential_ref,
            auth_kind=auth_kind,
        )
        existing_id = fingerprint_to_id.get(fingerprint)
        if existing_id:
            provider_id = existing_id
        else:
            # Avoid id collisions when fingerprint differs but id is reused.
            if provider_id in providers:
                provider_id = validate_provider_id(f"{provider_id}_{fingerprint[:8]}")
            fingerprint_to_id[fingerprint] = provider_id
            label = LLM_PROVIDER_TEMPLATE_LABELS.get(provider_id) or str(
                preset.get("label") or provider_id
            )
            providers[provider_id] = {
                "label": label,
                "service_class": _service_class(kind, base_url),
                "vendor": _vendor(kind),
                "driver": _driver(kind, str(raw_provider.get("compat_mode") or "")),
                "base_url": base_url,
                "auth_kind": auth_kind,
                "credential_ref": credential_ref,
                "requires_credential": auth_kind != "none",
                "protocols": {"default": "chat_completions", "allowed": ["chat_completions"]},
                "discovery": {
                    "mode": "auto",
                    "adapter": "openai_compatible",
                    "cache_ttl_seconds": 300,
                },
                "models": {},
            }
            transport_by_provider[provider_id] = set()

        upstream_id = str(raw_model.get("model") or preset.get("model_id") or preset_id).strip()
        if not upstream_id:
            continue
        model_key = make_model_key(upstream_id)
        model_entry: dict[str, Any] = {
            "upstream_id": upstream_id,
            "label": str(raw_model.get("label") or preset.get("label") or upstream_id),
            "enabled": True,
        }
        defaults = _model_defaults_from_preset(raw_model)
        if defaults:
            model_entry["defaults"] = defaults
        providers[provider_id]["models"][model_key] = model_entry

        transport = str(raw_model.get("transport") or "chat_completions").strip() or "chat_completions"
        transport_by_provider.setdefault(provider_id, set()).add(transport)

        if _is_dialogue_upstream(upstream_id):
            tool_mode = str(raw_model.get("tool_calling_mode") or "auto").strip().lower()
            if tool_mode in {"", "disabled", "none", "off"}:
                continue
            configured = True
            if providers[provider_id]["requires_credential"]:
                resolution = resolve_credential_ref(
                    str(providers[provider_id]["credential_ref"]),
                    env_reader=reader,
                )
                configured = bool(resolution.secret)
            # Prefer configured credentials, then official-ish service classes.
            # Local fallback is added separately and only used when no remote dialogue model exists.
            service_class = str(providers[provider_id].get("service_class") or "")
            if service_class == "local_runtime":
                continue
            # Configured credentials always outrank missing-key skeletons.
            # Soft preference: common production providers before alphabetical fallback.
            preference = {
                "relay_openai": 0,
                "xiaomi_mimo_token_plan_cn": 1,
                "openai_main": 2,
                "deepseek_main": 3,
                "dashscope_main": 4,
                "minimax_main": 5,
                "anthropic_main": 6,
            }.get(provider_id, 20)
            rank = (
                (0 if configured else 1000)
                + (0 if service_class == "official_api" else 1 if service_class == "relay" else 2)
                + preference * 0.01
            )
            dialogue_candidates.append((rank, make_model_ref(provider_id, model_key)))

    # Always keep a local runtime fallback.
    providers[_LOCAL_PROVIDER_ID] = _local_provider()
    transport_by_provider[_LOCAL_PROVIDER_ID] = {"chat_completions"}

    for provider_id, transports in transport_by_provider.items():
        if provider_id in providers:
            providers[provider_id]["protocols"] = _protocol_bundle(transports)

    dialogue_candidates.sort(key=lambda item: (item[0], item[1]))
    configured_refs = [ref for rank, ref in dialogue_candidates if rank < 1000]
    if configured_refs:
        primary_ref = configured_refs[0]
    elif dialogue_candidates:
        primary_ref = dialogue_candidates[0][1]
    else:
        primary_ref = _LOCAL_MODEL_REF

    profiles = {profile_id: {"model_ref": primary_ref} for profile_id in _PROFILE_IDS}
    # Keep an explicit local profile for offline fallback.
    profiles["local"] = {"model_ref": _LOCAL_MODEL_REF}

    return {
        "schema_version": 2,
        "providers": providers,
        "profiles": profiles,
    }


def build_default_operator_config(
    *,
    env_reader: EnvReader | None = None,
    include_unconfigured_providers: bool = True,
    credential_env_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "llm": build_default_llm_section(
            env_reader=env_reader,
            include_unconfigured_providers=include_unconfigured_providers,
            credential_env_overrides=credential_env_overrides,
        )
    }


def render_default_operator_config_text(
    *,
    example: bool = False,
    env_reader: EnvReader | None = None,
    include_unconfigured_providers: bool = True,
    credential_env_overrides: dict[str, str] | None = None,
) -> str:
    header = (
        "# Vibelution example operator config"
        if example
        else "# Vibelution operator config"
    )
    payload = build_default_operator_config(
        env_reader=env_reader,
        include_unconfigured_providers=include_unconfigured_providers,
        credential_env_overrides=credential_env_overrides,
    )
    notes = [
        header,
        "# Generated from project-fixed vendor templates (LLM_MODEL_PRESETS).",
        "# Secrets are referenced via credential_ref = env:VAR only; values stay in the environment.",
        "# Re-running first-time init never overwrites an existing operator config file.",
    ]
    return dumps_public_config(payload, header_lines=notes)


def is_thin_local_only_starter(public_config: dict[str, Any] | None) -> bool:
    """Match only the exact historical generated payload, never custom local configs."""

    return public_config == _LEGACY_THIN_LOCAL_ONLY_STARTER_PAYLOAD


def is_legacy_thin_local_only_starter_text(text: str) -> bool:
    """Require the historical generated text so comments/custom formatting are preserved."""

    normalized = str(text or "").replace("\r\n", "\n").strip()
    return normalized == _LEGACY_THIN_LOCAL_ONLY_STARTER_TEXT.strip()


def preferred_runtime_env_overrides() -> dict[str, str]:
    """Map bootstrap provider ids to env vars commonly used on existing installs."""

    candidates: dict[str, tuple[str, ...]] = {
        "openai_main": ("OPENAI_API_KEY",),
        "openai_image": ("OPENAI_API_KEY",),
        "relay_openai": (
            "VIBELUTION_LLM_MODEL_RELAY_OPENAI_GPT_5_5_API_KEY",
            "VIBELUTION_LLM_MODEL_CCSWITCH_PIXEL_CHATGPT_GPT_5_5_API_KEY",
            "OPENAI_API_KEY",
        ),
        "relay_image": (
            "VIBELUTION_LLM_MODEL_RELAY_IMAGE2_API_KEY",
            "OPENAI_API_KEY",
        ),
        "xiaomi_mimo_token_plan_cn": (
            "VIBELUTION_LLM_MODEL_XIAOMI_MIMO_V2_5_PRO_TOKEN_PLAN_API_KEY",
            "VIBELUTION_LLM_MODEL_MIMO_V2_5_API_KEY",
            "MIMO_API_KEY",
        ),
        "xiaomi_mimo_api_cn": (
            "VIBELUTION_LLM_MODEL_XIAOMI_MIMO_V2_5_MULTIMODAL_API_KEY",
            "VIBELUTION_LLM_MODEL_MIMO_V2_5_API_KEY",
            "MIMO_API_KEY",
        ),
        "dashscope_main": ("DASHSCOPE_API_KEY",),
        "minimax_main": ("MINIMAX2_7_API_KEY", "MINIMAX_API_KEY"),
        "deepseek_main": (
            "VIBELUTION_LLM_MODEL_DEEPSEEK_V4_PRO_API_KEY",
            "VIBELUTION_LLM_MODEL_DEEPSEEK_V4_FLASH_API_KEY",
            "DEEPSEEK_API_KEY",
        ),
        "anthropic_main": ("ANTHROPIC_API_KEY",),
        "anthropic_atpify": (
            "VIBELUTION_LLM_MODEL_CLAUDE_OPUS_4_7_ATPIFY_API_KEY",
            "ANTHROPIC_API_KEY",
        ),
        "google_main": ("GOOGLE_API_KEY",),
        "siliconflow_main": ("SILICONFLOW_API_KEY",),
    }
    overrides: dict[str, str] = {}
    for provider_id, names in candidates.items():
        for name in names:
            if os.environ.get(name):
                overrides[provider_id] = name
                break
        else:
            # Keep the first preferred name so bootstrap still points at a stable env slot.
            overrides[provider_id] = names[0]
    return overrides


__all__ = [
    "build_default_llm_section",
    "build_default_operator_config",
    "is_legacy_thin_local_only_starter_text",
    "is_thin_local_only_starter",
    "preferred_runtime_env_overrides",
    "render_default_operator_config_text",
]
