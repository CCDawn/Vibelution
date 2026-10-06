"""Helpers for restoring configured LLM API key environment variables."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from typing import Any

from .models import PROVIDER_API_KEY_ENV_ALIASES, get_provider_api_key_env
from .public_config import load_public_config, read_persisted_user_env_var


# Every chat turn re-syncs configured LLM key env vars. The config side is
# already signature-cached in ``public_config.load_public_config``; the
# remaining per-turn cost is the persisted-env reader (Windows registry lookups
# for each configured name that is absent from ``os.environ``). Registry values
# change rarely, so successful reads are memoized for a short TTL. Cache
# entries are keyed by the reader object identity: only the real default
# registry reader shares entries (production path), while injected/monkeypatched
# readers never reuse another reader's values. Staleness window: an external
# registry edit for a name that is absent from the process env may take up to
# the TTL to be observed; names already present in ``os.environ`` short-circuit
# before any read and are unaffected.
_PERSISTED_READ_CACHE_LOCK = threading.Lock()
_PERSISTED_READ_CACHE: dict[str, tuple[float, str, Callable[[str], str]]] = {}
DEFAULT_PERSISTED_READ_TTL_SECONDS = 60.0


def reset_llm_key_env_read_cache() -> None:
    """Clear the persisted-env read cache (test and diagnostic hook)."""

    with _PERSISTED_READ_CACHE_LOCK:
        _PERSISTED_READ_CACHE.clear()


def _read_persisted_with_cache(
    env_name: str,
    reader: Callable[[str], str],
    ttl_seconds: float,
) -> str:
    if ttl_seconds <= 0:
        return reader(env_name)
    now = time.monotonic()
    with _PERSISTED_READ_CACHE_LOCK:
        entry = _PERSISTED_READ_CACHE.get(env_name)
        if (
            entry is not None
            and entry[2] is reader
            and now - entry[0] < ttl_seconds
        ):
            return entry[1]
    value = str(reader(env_name) or "")
    with _PERSISTED_READ_CACHE_LOCK:
        _PERSISTED_READ_CACHE[env_name] = (now, value, reader)
        if len(_PERSISTED_READ_CACHE) > 64:
            _PERSISTED_READ_CACHE.pop(next(iter(_PERSISTED_READ_CACHE)))
    return value


def _add_provider_key_env_names(env_names: set[str], provider: dict[str, Any]) -> None:
    provider_env = str(provider.get("api_key_env") or "").strip()
    if provider_env:
        env_names.add(provider_env)
    credential_ref = str(provider.get("credential_ref") or "").strip()
    if credential_ref.lower().startswith("env:"):
        credential_env = credential_ref.split(":", 1)[1].strip()
        if credential_env:
            env_names.add(credential_env)
    provider_kind = str(provider.get("kind") or "").strip().lower()
    canonical_env = get_provider_api_key_env(provider_kind)
    if canonical_env:
        env_names.add(canonical_env)
    for alias in PROVIDER_API_KEY_ENV_ALIASES.get(provider_kind, []):
        alias_env = str(alias or "").strip()
        if alias_env:
            env_names.add(alias_env)


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
            provider = item.get("provider")
            if isinstance(provider, dict):
                _add_provider_key_env_names(env_names, provider)

    for provider in providers.values():
        if not isinstance(provider, dict):
            continue
        _add_provider_key_env_names(env_names, provider)

    return env_names


def sync_llm_key_env_from_persisted_user_env(
    *,
    context: str,
    public_config: dict[str, Any] | None = None,
    persisted_reader: Callable[[str], str] | None = None,
    persisted_read_ttl_seconds: float | None = None,
) -> dict[str, Any]:
    """Refresh this process from user-level LLM key env vars without exposing values.

    ``persisted_read_ttl_seconds`` controls the memoization of successful
    persisted-env reads (default: 60s, and only for the module-default
    registry reader; injected readers are never cached unless a positive TTL
    is passed explicitly). Pass ``0`` to disable caching entirely.
    """

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
    if persisted_read_ttl_seconds is None:
        read_ttl = DEFAULT_PERSISTED_READ_TTL_SECONDS if read_persisted is read_persisted_user_env_var else 0.0
    else:
        read_ttl = float(persisted_read_ttl_seconds)
    for env_name in env_names:
        if os.environ.get(env_name):
            already_present += 1
            continue
        persisted_value = _read_persisted_with_cache(env_name, read_persisted, read_ttl)
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
    "reset_llm_key_env_read_cache",
    "sync_llm_key_env_from_persisted_user_env",
]
