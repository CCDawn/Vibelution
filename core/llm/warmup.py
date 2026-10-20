# -*- coding: utf-8 -*-
"""Background cold-start warmup for the first LLM call in a backend process.

Measured on this repo (2026-10): ``from litellm import completion`` inside
``_default_completion_backend`` costs ~5.1s in a warm process (~8.4s cold
disk cache), and LiteLLM initializes each provider adapter lazily on first
use. Together they produced an 11.8s pre-connect gap (before the first real
call's ``connect_tcp.started``). This module pays those costs once, inside
the startup stagger window, off the request path:

1. ``prewarm_llm_imports`` imports the heavy modules that ``client.py``
   still lazy-imports inside function bodies (litellm/httpx/openai plus the
   light call-path locals). The function-body imports stay: after the
   preload they hit ``sys.modules``.
2. ``warmup_provider`` fires one minimal non-streaming request per active,
   credentialed provider through the normal ``LLMClient.invoke`` path, so
   LiteLLM provider adapters, the proxy env lease and TLS all initialize
   before the first user turn. Warmup invocations carry the
   ``LLM_WARMUP_METADATA_KEY`` marker; ``_record_usage_ledger_event`` skips
   them so the usage ledger, quota and cost rollups never count warmup.

Discipline: provider ids are claimed under a lock but no network IO ever
happens inside it (fxl-0010); every provider probe is bounded by a capped
timeout, fire-and-forget, and every failure is swallowed into one info log.
The owner runs inside a ``StartupJobGroup`` daemon worker (see
``core.web.lifecycle._run_llm_warmup_after_routes_ready``), never on the
startup critical path or the event loop.
"""

from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: Operator kill switch. Any of ``0/false/no/off`` disables both the import
#: preload and the provider probes. Follows the ``VIBELUTION_LLM_*`` env knob
#: family (see ``VIBELUTION_LLM_ROUTE_GATE_WAIT_SECONDS``).
LLM_STARTUP_WARMUP_ENV = "VIBELUTION_LLM_STARTUP_WARMUP"

_DISABLE_VALUES = {"0", "false", "no", "off"}

#: Per-probe budget. Profile timeouts are capped to this so one hung
#: provider cannot hold the warmup worker for the full operator timeout.
LLM_WARMUP_TIMEOUT_SECONDS = 15.0

_WARMUP_STATE_LOCK = threading.Lock()
_WARMED_PROVIDER_IDS: set[str] = set()

#: Function-body lazy imports on the ``LLMClient`` call path that are worth
#: preloading. Heavy entries first: litellm is the 5s+ cost, httpx/openai
#: are its transport deps; the rest are light local modules that the first
#: real invoke would otherwise import inline. Label is used for logging.
_LLM_CALL_PATH_IMPORTS: Tuple[Tuple[str, str, Optional[str]], ...] = (
    ("httpx", "httpx", None),
    ("openai", "openai", None),
    ("litellm.completion", "litellm", "completion"),
    ("litellm.responses", "litellm", "responses"),
    ("litellm.HTTPHandler", "litellm", "HTTPHandler"),
    ("core.chat.conversation_invariant", "core.chat.conversation_invariant", None),
    ("core.chat.model_messages", "core.chat.model_messages", None),
    ("tools.token_manager", "tools.token_manager", None),
    ("core.llm.usage_ledger", "core.llm.usage_ledger", None),
)

_WARMUP_MESSAGES: List[Dict[str, Any]] = [{"role": "user", "content": "hi"}]


def llm_startup_warmup_enabled(config: Any = None) -> bool:
    """Both the env kill switch and ``llm.startup_warmup`` must allow warmup."""

    raw = str(os.environ.get(LLM_STARTUP_WARMUP_ENV) or "").strip().lower()
    if raw and raw in _DISABLE_VALUES:
        return False
    if config is not None:
        value = getattr(getattr(config, "llm", None), "startup_warmup", True)
        if value is False:
            return False
    return True


def reset_warmup_state_for_tests() -> None:
    """Clear the per-process provider claims so tests start from a clean slate."""

    with _WARMUP_STATE_LOCK:
        _WARMED_PROVIDER_IDS.clear()


def prewarm_llm_imports() -> Dict[str, Dict[str, Any]]:
    """Import the heavy call-path modules once, off the startup critical path.

    Each target is timed independently; a missing optional dependency (or any
    import failure) is recorded and swallowed — the lazy imports in
    ``client.py`` keep their own fail-loud error paths for real calls.
    """

    results: Dict[str, Dict[str, Any]] = {}
    for label, module_name, attr in _LLM_CALL_PATH_IMPORTS:
        started = time.perf_counter()
        entry: Dict[str, Any] = {"ok": True, "error": ""}
        try:
            module = importlib.import_module(module_name)
            if attr is not None:
                getattr(module, attr)
        except Exception as exc:  # noqa: BLE001 - preload must never raise
            entry["ok"] = False
            entry["error"] = type(exc).__name__
        entry["ms"] = max(0, int((time.perf_counter() - started) * 1000))
        results[label] = entry
    return results


def _provider_credentials_ready(provider: Any) -> bool:
    """Mirror the runtime's fail-closed credential gate for provider probes."""

    if str(getattr(provider, "auth_kind", "api_key") or "") == "none":
        return True
    if not bool(getattr(provider, "requires_api_key", True)) and not bool(
        getattr(provider, "requires_credential", True)
    ):
        return True
    try:
        api_key = provider.resolve_api_key()
    except Exception:  # noqa: BLE001 - broken credential ref == not ready
        return False
    return bool(api_key)


def _active_provider_profile_pairs(config: Any) -> List[Tuple[str, str]]:
    """One (provider_id, profile_id) per enabled, credentialed, referenced provider.

    The primary role's profile wins its provider so the default dialogue
    route is always the one warmed; other providers take their first profile
    in sorted order. Deterministic on every boot.
    """

    llm = getattr(config, "llm", None)
    if llm is None:
        return []
    profiles = dict(getattr(llm, "profiles", None) or {})
    providers = dict(getattr(llm, "providers", None) or {})
    if not profiles or not providers:
        return []
    try:
        ordered_ids = [llm.get_role_profile_id("primary")]
    except Exception:  # noqa: BLE001 - no resolvable primary; sort only
        ordered_ids = []
    ordered_ids.extend(sorted(pid for pid in profiles if pid not in ordered_ids))
    chosen: Dict[str, str] = {}
    for profile_id in ordered_ids:
        profile = profiles.get(profile_id)
        if profile is None:
            continue
        provider_id = str(getattr(profile, "provider_id", "") or "").strip()
        provider = providers.get(provider_id)
        if provider is None or provider_id in chosen:
            continue
        if not bool(getattr(provider, "enabled", True)):
            continue
        if not _provider_credentials_ready(provider):
            continue
        chosen[provider_id] = profile_id
    return list(chosen.items())


def _capped_warmup_config(config: Any, *, timeout_seconds: float) -> Any:
    """Derive a warmup-only config view: bounded timeouts, prompt cache off.

    Shallow pydantic copies keep provider objects and credential resolution
    identical; only the warmed profiles' ``timeout``/``connect_timeout`` are
    lowered and ``prompt_cache`` disabled so the one-off probe cannot write
    into a real conversation cache shard.
    """

    llm = config.llm
    profiles: Dict[str, Any] = {}
    changed = False
    cap = max(1, int(timeout_seconds))
    for profile_id, profile in dict(llm.profiles or {}).items():
        updates: Dict[str, Any] = {}
        try:
            timeout = int(getattr(profile, "timeout", 0) or 0)
            connect_timeout = int(getattr(profile, "connect_timeout", 0) or 0)
        except (TypeError, ValueError):
            timeout = connect_timeout = 0
        if timeout > cap:
            updates["timeout"] = cap
        if connect_timeout > cap:
            updates["connect_timeout"] = cap
        if str(getattr(getattr(profile, "prompt_cache", None), "mode", "") or "") != "disabled":
            from config.models import PromptCacheConfig

            updates["prompt_cache"] = PromptCacheConfig(mode="disabled")
        if updates:
            changed = True
            profiles[profile_id] = profile.model_copy(update=updates)
        else:
            profiles[profile_id] = profile
    if not changed:
        return config
    return config.model_copy(update={"llm": llm.model_copy(update={"profiles": profiles})})


def warmup_provider(
    provider_id: str,
    profile_id: str,
    *,
    config: Any,
    timeout_seconds: float = LLM_WARMUP_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Fire one minimal probe through the normal client path; idempotent per process.

    The provider id is claimed under the state lock (set membership only —
    no IO under the lock); the probe itself runs unlocked so a slow provider
    never blocks the claim path. Failures are swallowed into the returned
    summary and one info log line.
    """

    with _WARMUP_STATE_LOCK:
        if provider_id in _WARMED_PROVIDER_IDS:
            return {"provider": provider_id, "profileId": profile_id, "skipped": "already_warmed"}
        _WARMED_PROVIDER_IDS.add(provider_id)

    from .client import LLM_WARMUP_METADATA_KEY, MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY, LLMClient

    started = time.perf_counter()
    outcome = "succeeded"
    error_type = ""
    client: Any = None
    try:
        client = LLMClient(
            config=_capped_warmup_config(config, timeout_seconds=timeout_seconds),
            profile_id=profile_id,
        )
        client.invoke(
            _WARMUP_MESSAGES,
            metadata={
                LLM_WARMUP_METADATA_KEY: True,
                "llmInvocationSurface": "warmup",
                "llmRunKind": "warmup",
                # Single attempt, 1-token answer: bounded cost, no retry budget.
                "disableAutomaticRetries": True,
                MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY: 1,
            },
        )
    except Exception as exc:  # noqa: BLE001 - warmup is best-effort by contract
        outcome = "failed"
        error_type = type(exc).__name__
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001 - transport close is best-effort
                pass
    duration_ms = max(0, int((time.perf_counter() - started) * 1000))
    summary = {
        "provider": provider_id,
        "profileId": profile_id,
        "outcome": outcome,
        "durationMs": duration_ms,
        "errorType": error_type,
    }
    logger.info(
        "LLM startup warmup finished: provider=%s profile=%s outcome=%s durationMs=%d%s",
        provider_id,
        profile_id,
        outcome,
        duration_ms,
        f" errorType={error_type}" if error_type else "",
    )
    return summary


def run_llm_startup_warmup(
    gate_timings: Optional[Dict[str, Any]] = None,
    *,
    config: Any = None,
    timeout_seconds: float = LLM_WARMUP_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Owner entry: preload imports, then probe each active provider once.

    Never raises: every stage degrades into the returned summary. Called from
    a ``StartupJobGroup`` daemon worker after the routes-ready stagger gate,
    so none of this work sits on the startup critical path.
    """

    if not llm_startup_warmup_enabled(None):
        # Env kill switch: cheap short-circuit before touching config at all.
        return {"enabled": False, "skipped": "disabled", "providers": []}
    if config is None:
        from config import get_config

        try:
            config = get_config()
        except Exception as exc:  # noqa: BLE001 - never fail the worker
            logger.info("LLM startup warmup skipped: config unavailable (%s).", type(exc).__name__)
            return {"enabled": True, "skipped": "config_unavailable", "providers": []}
    if not llm_startup_warmup_enabled(config):
        return {"enabled": False, "skipped": "disabled", "providers": []}

    preload = prewarm_llm_imports()
    preload_failures = sorted(label for label, entry in preload.items() if not entry["ok"])
    provider_summaries = [
        warmup_provider(provider_id, profile_id, config=config, timeout_seconds=timeout_seconds)
        for provider_id, profile_id in _active_provider_profile_pairs(config)
    ]
    summary = {
        "enabled": True,
        "waitedForRoutesMs": int((gate_timings or {}).get("waitedForRoutesMs", 0) or 0),
        "staggerMs": int((gate_timings or {}).get("staggerMs", 0) or 0),
        "preloadTotalMs": sum(int(entry.get("ms", 0) or 0) for entry in preload.values()),
        "preloadFailures": preload_failures,
        "providers": provider_summaries,
    }
    logger.info(
        "LLM startup warmup completed: preloadMs=%d providers=%d",
        summary["preloadTotalMs"],
        len(provider_summaries),
    )
    return summary


__all__ = [
    "LLM_STARTUP_WARMUP_ENV",
    "LLM_WARMUP_TIMEOUT_SECONDS",
    "llm_startup_warmup_enabled",
    "prewarm_llm_imports",
    "reset_warmup_state_for_tests",
    "run_llm_startup_warmup",
    "warmup_provider",
]
