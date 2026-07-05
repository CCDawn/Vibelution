"""Helpers for restoring configured LLM API key environment variables."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from .models import PROVIDER_API_KEY_ENV_ALIASES, get_provider_api_key_env
from .public_config import load_public_config, read_persisted_user_env_var


def configured_llm_key_env_names(public_config: dict[str, Any]) -> set[str]:
    llm = public_config.get("llm") if isinstance(public_config.get("llm"), dict) else {}
    model_library = llm.get("model_library") if isinstance(llm.get("model_library"), dict) else {}
    providers = llm.get("providers") if isinstance(llm.get("providers"), dict) else {}
    env_names: set[str] = set()

    for item in model_library.values():
        if isinstance(item, dict):
            env_name = str(item.get("api_key_env") or "").strip()
            if env_name:
                env_names.add(env_name)

    for provider in providers.values():
        if not isinstance(provider, dict):
            continue
        provider_env = str(provider.get("api_key_env") or "").strip()
        if provider_env:
            env_names.add(provider_env)
        provider_kind = str(provider.get("kind") or "").strip().lower()
        canonical_env = get_provider_api_key_env(provider_kind)
        if canonical_env:
            env_names.add(canonical_env)
        for alias in PROVIDER_API_KEY_ENV_ALIASES.get(provider_kind, []):
            alias_env = str(alias or "").strip()
            if alias_env:
                env_names.add(alias_env)

    return env_names


def sync_llm_key_env_from_persisted_user_env(
    *,
    context: str,
    public_config: dict[str, Any] | None = None,
    persisted_reader: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Refresh this process from user-level LLM key env vars without exposing values."""

    try:
        resolved_public_config = public_config if isinstance(public_config, dict) else load_public_config()
    except Exception as exc:
        return {
            "context": str(context or "").strip(),
            "ok": False,
            "errorType": type(exc).__name__,
            "message": str(exc),
        }

    env_names = sorted(configured_llm_key_env_names(resolved_public_config))
    synced: list[str] = []
    already_present = 0
    missing: list[str] = []
    read_persisted = persisted_reader if callable(persisted_reader) else read_persisted_user_env_var
    for env_name in env_names:
        if os.environ.get(env_name):
            already_present += 1
            continue
        persisted_value = read_persisted(env_name)
        if persisted_value:
            os.environ[env_name] = persisted_value
            synced.append(env_name)
        else:
            missing.append(env_name)

    return {
        "context": str(context or "").strip(),
        "ok": True,
        "envCount": len(env_names),
        "alreadyPresentCount": already_present,
        "syncedCount": len(synced),
        "syncedEnvNames": synced[:20],
        "missingCount": len(missing),
        "missingEnvNames": missing[:20],
    }


__all__ = [
    "configured_llm_key_env_names",
    "read_persisted_user_env_var",
    "sync_llm_key_env_from_persisted_user_env",
]
