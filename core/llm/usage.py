# -*- coding: utf-8 -*-
"""Provider usage normalization.

Different providers and OpenAI-compatible relays expose prompt-cache accounting
under different field names.  Keep that mapping in one place so streaming,
non-streaming, and UI response handling use the same contract.
"""

from __future__ import annotations

from typing import Any, Dict

from .types import UsageStats
from .usage_normalize import cache_usage_observation, normalize_usage_dict, normalize_usage_payload


def usage_to_dict(usage: Any) -> Dict[str, Any]:
    if isinstance(usage, dict):
        return usage
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        try:
            payload = usage.model_dump()
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}
    payload: Dict[str, Any] = {}
    for key in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "input_tokens",
        "output_tokens",
        "input_token_count",
        "output_token_count",
        "cached_tokens",
        "cached_input_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
        "prompt_tokens_details",
        "input_token_details",
        "input_tokens_details",
        "completion_tokens_details",
        "output_token_details",
        "output_tokens_details",
        "usage_metadata",
        "reasoning_output_tokens",
        "reasoning_tokens",
        "output_reasoning_tokens",
    ):
        if hasattr(usage, key):
            payload[key] = getattr(usage, key)
    return payload


def read_usage_int(container: Any, *keys: str) -> int:
    if not isinstance(container, dict):
        return 0
    for key in keys:
        value = container.get(key)
        if value not in (None, ""):
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
    return 0


def _read_nested_usage_int(container: Any, *keys: str) -> int:
    if not isinstance(container, dict):
        return 0
    direct = read_usage_int(container, *keys)
    if direct:
        return direct
    for value in container.values():
        if isinstance(value, dict):
            nested = _read_nested_usage_int(value, *keys)
            if nested:
                return nested
    return 0


def cached_input_tokens_from_usage(usage: Dict[str, Any] | Any) -> int:
    usage_dict = usage_to_dict(usage)
    if not usage_dict:
        return 0
    prompt_details = usage_dict.get("prompt_tokens_details")
    input_details = usage_dict.get("input_token_details") or usage_dict.get("input_tokens_details")
    usage_metadata = usage_dict.get("usage_metadata")
    return max(
        read_usage_int(
            usage_dict,
            "cached_tokens",
            "cached_input_tokens",
            "cache_read_input_tokens",
            "prompt_cache_hit_tokens",
        ),
        read_usage_int(prompt_details, "cached_tokens", "cached_input_tokens", "cache_read_input_tokens"),
        read_usage_int(input_details, "cached_tokens", "cached_input_tokens", "cache_read_input_tokens"),
        read_usage_int(usage_metadata, "cached_tokens", "cached_input_tokens", "cache_read_input_tokens"),
        _read_nested_usage_int(usage_dict, "cached_tokens", "cached_input_tokens", "cache_read_input_tokens"),
    )


def cache_creation_input_tokens_from_usage(usage: Dict[str, Any] | Any) -> int:
    usage_dict = usage_to_dict(usage)
    if not usage_dict:
        return 0
    prompt_details = usage_dict.get("prompt_tokens_details")
    input_details = usage_dict.get("input_token_details") or usage_dict.get("input_tokens_details")
    usage_metadata = usage_dict.get("usage_metadata")
    return max(
        read_usage_int(
            usage_dict,
            "cache_creation_input_tokens",
            "cache_write_input_tokens",
            "prompt_cache_creation_tokens",
        ),
        read_usage_int(
            prompt_details,
            "cache_creation_input_tokens",
            "cache_write_input_tokens",
            "prompt_cache_creation_tokens",
        ),
        read_usage_int(
            input_details,
            "cache_creation_input_tokens",
            "cache_write_input_tokens",
            "prompt_cache_creation_tokens",
        ),
        read_usage_int(
            usage_metadata,
            "cache_creation_input_tokens",
            "cache_write_input_tokens",
            "prompt_cache_creation_tokens",
        ),
        _read_nested_usage_int(
            usage_dict,
            "cache_creation_input_tokens",
            "cache_write_input_tokens",
            "prompt_cache_creation_tokens",
        ),
    )


def reasoning_output_tokens_from_usage(usage: Dict[str, Any] | Any) -> int:
    usage_dict = usage_to_dict(usage)
    if not usage_dict:
        return 0
    completion_details = usage_dict.get("completion_tokens_details")
    output_details = usage_dict.get("output_token_details") or usage_dict.get("output_tokens_details")
    usage_metadata = usage_dict.get("usage_metadata")
    return max(
        read_usage_int(
            usage_dict,
            "reasoning_output_tokens",
            "reasoning_tokens",
            "output_reasoning_tokens",
        ),
        read_usage_int(
            completion_details,
            "reasoning_tokens",
            "reasoning_output_tokens",
            "output_reasoning_tokens",
        ),
        read_usage_int(
            output_details,
            "reasoning_tokens",
            "reasoning_output_tokens",
            "output_reasoning_tokens",
        ),
        read_usage_int(
            usage_metadata,
            "reasoning_tokens",
            "reasoning_output_tokens",
            "output_reasoning_tokens",
        ),
        _read_nested_usage_int(
            usage_dict,
            "reasoning_output_tokens",
            "reasoning_tokens",
            "output_reasoning_tokens",
        ),
    )


def usage_tokens_from_dict(usage: Dict[str, Any] | Any) -> tuple[int, int, int]:
    usage_dict = usage_to_dict(usage)
    if not usage_dict:
        return 0, 0, 0
    # Prefer pure-Python path for token triple (no subprocess); same algorithm as Rust pilot.
    normalized = normalize_usage_dict(usage_dict, engine="python")
    return (
        int(normalized["input_tokens"]),
        int(normalized["output_tokens"]),
        int(normalized["total_tokens"]),
    )


def usage_stats_from_payload(usage: Any, *, latency_ms: int = 0) -> UsageStats:
    usage_dict = usage_to_dict(usage)
    normalized = normalize_usage_payload(usage_dict)
    reasoning_output_tokens = reasoning_output_tokens_from_usage(usage_dict)
    input_tokens = int(normalized["input_tokens"])
    output_tokens = int(normalized["output_tokens"])
    return UsageStats(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=int(normalized["total_tokens"]),
        cached_input_tokens=int(normalized["cached_input_tokens"]),
        cache_creation_input_tokens=int(normalized["cache_creation_input_tokens"]),
        reasoning_output_tokens=min(reasoning_output_tokens, output_tokens)
        if output_tokens
        else reasoning_output_tokens,
        provider_raw_usage=usage_dict,
        estimated_cost=0.0,
        latency_ms=max(0, int(latency_ms or 0)),
    )


def usage_diagnostic_summary_from_payload(usage: Any) -> Dict[str, Any]:
    """Normalize provider usage into the bounded canonical event contract."""
    usage_dict = usage_to_dict(usage)
    normalized = normalize_usage_payload(usage_dict)
    stats = usage_stats_from_payload(usage_dict)
    return {
        "inputTokens": int(normalized["inputTokens"]),
        "outputTokens": int(normalized["outputTokens"]),
        "reasoningOutputTokens": max(0, int(stats.reasoning_output_tokens or 0)),
        "totalTokens": int(normalized["totalTokens"]),
        "cachedInputTokens": int(normalized["cachedInputTokens"]),
        "cacheReadInputTokens": int(normalized["cacheReadInputTokens"]),
        "cacheCreationInputTokens": int(normalized["cacheCreationInputTokens"]),
        "uncachedInputTokens": int(normalized["uncachedInputTokens"]),
        "cacheHitRate": float(normalized["cacheHitRate"]),
        "cacheUsageObserved": bool(normalized["cacheUsageObserved"]),
        "cacheUsageMissingReason": str(normalized["cacheUsageMissingReason"] or ""),
        "engine": str(normalized.get("engine") or "python"),
    }


def cache_usage_observation_from_payload(usage: Any) -> tuple[bool, str]:
    return cache_usage_observation(usage_to_dict(usage))
