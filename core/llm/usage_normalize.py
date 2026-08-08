# -*- coding: utf-8 -*-
"""Canonical provider usage / prompt-cache normalization.

Python reference implementation for the Rust pilot
``crates/vibelution-usage-normalize``. Prefer calling
:func:`normalize_usage_payload`; optional Rust sidecar via env
``VIBELUTION_USAGE_NORMALIZE_BIN`` or default binary path under ``crates/``.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUST_BIN_CANDIDATES = (
    PROJECT_ROOT / "crates" / "vibelution-usage-normalize" / "target" / "release" / "vibelution-usage-normalize.exe",
    PROJECT_ROOT / "crates" / "vibelution-usage-normalize" / "target" / "release" / "vibelution-usage-normalize",
    PROJECT_ROOT / "crates" / "vibelution-usage-normalize" / "target" / "debug" / "vibelution-usage-normalize.exe",
    PROJECT_ROOT / "crates" / "vibelution-usage-normalize" / "target" / "debug" / "vibelution-usage-normalize",
)


def _as_u64(value: Any) -> int:
    if value in (None, ""):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError):
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            return 0
    return max(0, number)


def _read_keys(container: Mapping[str, Any] | None, *keys: str) -> int:
    if not isinstance(container, Mapping):
        return 0
    for key in keys:
        if key in container and container.get(key) not in (None, ""):
            return _as_u64(container.get(key))
    return 0


def _nested(container: Mapping[str, Any], object_keys: tuple[str, ...], field_keys: tuple[str, ...]) -> int:
    for object_key in object_keys:
        child = container.get(object_key)
        if isinstance(child, Mapping):
            found = _read_keys(child, *field_keys)
            if found:
                return found
    return 0


def normalize_usage_dict(raw: Mapping[str, Any] | None, *, engine: str = "python") -> Dict[str, Any]:
    """Normalize provider usage into the canonical camelCase + snake dual fields."""
    usage = dict(raw or {})
    prompt_tokens = _read_keys(usage, "prompt_tokens", "promptTokens")
    input_field = _read_keys(usage, "input_tokens", "inputTokens", "input_token_count")
    input_from_meta = _nested(
        usage,
        ("usage_metadata", "usageMetadata", "input_token_details", "input_tokens_details"),
        ("prompt_tokens", "input_tokens", "input_token_count", "promptTokens", "inputTokens"),
    )
    cache_read = max(
        _read_keys(
            usage,
            "cache_read_input_tokens",
            "cacheReadInputTokens",
            "cached_input_tokens",
            "cachedInputTokens",
            "cached_tokens",
            "prompt_cache_hit_tokens",
        ),
        _nested(
            usage,
            ("prompt_tokens_details", "promptTokensDetails", "input_token_details", "input_tokens_details", "usage_metadata"),
            ("cached_tokens", "cached_input_tokens", "cache_read_input_tokens", "cachedTokens"),
        ),
    )
    cache_creation = max(
        _read_keys(
            usage,
            "cache_creation_input_tokens",
            "cacheCreationInputTokens",
            "cache_write_input_tokens",
            "prompt_cache_creation_tokens",
        ),
        _nested(
            usage,
            ("prompt_tokens_details", "promptTokensDetails", "usage_metadata"),
            ("cache_creation_input_tokens", "cache_write_input_tokens", "prompt_cache_creation_tokens"),
        ),
    )
    output_tokens = max(
        _read_keys(usage, "completion_tokens", "output_tokens", "outputTokens", "output_token_count"),
        _nested(
            usage,
            ("usage_metadata", "completion_tokens_details"),
            ("completion_tokens", "output_tokens"),
        ),
    )
    total_tokens = _read_keys(usage, "total_tokens", "totalTokens")

    declared_input = max(prompt_tokens, input_field, input_from_meta)
    anthropic_sum = cache_read + cache_creation + input_field
    # Anthropic-native: input_tokens is the unpaid tail (smaller than cache read/write).
    # OpenAI-compatible: input_tokens is already the full prompt total.
    looks_anthropic_native = (
        (cache_read > 0 or cache_creation > 0)
        and input_field > 0
        and prompt_tokens == 0
        and (cache_read > input_field or cache_creation > input_field)
    )

    if looks_anthropic_native:
        input_tokens = anthropic_sum
    elif prompt_tokens > 0:
        input_tokens = max(prompt_tokens, input_field, input_from_meta)
    else:
        # input_tokens already represents the provider total (OpenAI-compatible).
        input_tokens = declared_input

    cached = min(cache_read, input_tokens) if input_tokens else cache_read
    creation = min(cache_creation, input_tokens) if input_tokens else cache_creation
    uncached = max(0, input_tokens - cached)
    hit = round(cached / input_tokens, 4) if input_tokens else 0.0
    if not total_tokens:
        total_tokens = input_tokens + output_tokens

    return {
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": total_tokens,
        "cachedInputTokens": cached,
        "cacheReadInputTokens": cached,
        "cacheCreationInputTokens": creation,
        "uncachedInputTokens": uncached,
        "cacheHitRate": hit,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cached_input_tokens": cached,
        "cache_read_input_tokens": cached,
        "cache_creation_input_tokens": creation,
        "uncached_input_tokens": uncached,
        "cache_hit_rate": hit,
        "engine": engine,
    }


def resolve_usage_normalize_binary() -> Path | None:
    override = str(os.environ.get("VIBELUTION_USAGE_NORMALIZE_BIN") or "").strip()
    if override:
        path = Path(override)
        return path if path.is_file() else None
    for candidate in DEFAULT_RUST_BIN_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def normalize_usage_payload_via_rust(raw: Mapping[str, Any], *, timeout_s: float = 2.0) -> Dict[str, Any] | None:
    binary = resolve_usage_normalize_binary()
    if binary is None:
        return None
    try:
        # Rust release binaries are console-subsystem (CUI). Without CREATE_NO_WINDOW
        # every LLM usage normalize flashes a console on agent turns (toolCallCount 0).
        from scripts.windowless_subprocess import no_window_subprocess_kwargs

        completed = subprocess.run(
            [str(binary)],
            input=json.dumps({"usage": dict(raw)}, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=max(0.2, float(timeout_s)),
            check=False,
            **no_window_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0 or not str(completed.stdout or "").strip():
        return None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    input_tokens = _as_u64(payload.get("inputTokens"))
    output_tokens = _as_u64(payload.get("outputTokens"))
    total_tokens = _as_u64(payload.get("totalTokens")) or (input_tokens + output_tokens)
    cached = _as_u64(payload.get("cachedInputTokens") or payload.get("cacheReadInputTokens"))
    creation = _as_u64(payload.get("cacheCreationInputTokens"))
    uncached = _as_u64(payload.get("uncachedInputTokens"))
    if input_tokens and not uncached and cached <= input_tokens:
        uncached = max(0, input_tokens - cached)
    try:
        hit = float(payload.get("cacheHitRate") or 0.0)
    except (TypeError, ValueError):
        hit = round(cached / input_tokens, 4) if input_tokens else 0.0
    return {
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": total_tokens,
        "cachedInputTokens": cached,
        "cacheReadInputTokens": cached,
        "cacheCreationInputTokens": creation,
        "uncachedInputTokens": uncached,
        "cacheHitRate": hit,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cached_input_tokens": cached,
        "cache_read_input_tokens": cached,
        "cache_creation_input_tokens": creation,
        "uncached_input_tokens": uncached,
        "cache_hit_rate": hit,
        "engine": "rust",
    }


def normalize_usage_payload(raw: Mapping[str, Any] | None, *, prefer_rust: bool | None = None) -> Dict[str, Any]:
    """Normalize usage; optionally prefer Rust binary when present."""
    usage = dict(raw or {})
    use_rust = prefer_rust
    if use_rust is None:
        flag = str(os.environ.get("VIBELUTION_USAGE_NORMALIZE_ENGINE") or "").strip().lower()
        if flag in {"rust", "python"}:
            use_rust = flag == "rust"
        else:
            use_rust = resolve_usage_normalize_binary() is not None
    if use_rust:
        rust_result = normalize_usage_payload_via_rust(usage)
        if rust_result is not None:
            return rust_result
    return normalize_usage_dict(usage, engine="python")
