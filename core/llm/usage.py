# -*- coding: utf-8 -*-
"""Provider usage normalization.

Different providers and OpenAI-compatible relays expose prompt-cache accounting
under different field names.  Keep that mapping in one place so streaming,
non-streaming, and UI response handling use the same contract.
"""

from __future__ import annotations

from typing import Any, Dict

from .types import UsageStats


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
        "prompt_tokens_details",
        "input_token_details",
        "input_tokens_details",
        "output_token_details",
        "usage_metadata",
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


def usage_tokens_from_dict(usage: Dict[str, Any] | Any) -> tuple[int, int, int]:
    usage_dict = usage_to_dict(usage)
    if not usage_dict:
        return 0, 0, 0
    input_details = usage_dict.get("input_token_details") or usage_dict.get("input_tokens_details")
    output_details = usage_dict.get("output_token_details")
    usage_metadata = usage_dict.get("usage_metadata")
    input_tokens = max(
        read_usage_int(usage_dict, "prompt_tokens", "input_tokens", "input_token_count"),
        read_usage_int(input_details, "input_tokens", "prompt_tokens", "input_token_count"),
        read_usage_int(usage_metadata, "prompt_tokens", "input_tokens", "input_token_count"),
    )
    output_tokens = max(
        read_usage_int(usage_dict, "completion_tokens", "output_tokens", "output_token_count"),
        read_usage_int(output_details, "completion_tokens", "output_tokens", "output_token_count"),
        read_usage_int(usage_metadata, "completion_tokens", "output_tokens", "output_token_count"),
    )
    total_tokens = read_usage_int(usage_dict, "total_tokens") or read_usage_int(usage_metadata, "total_tokens")
    if total_tokens > 0:
        if input_tokens and not output_tokens:
            output_tokens = max(0, total_tokens - input_tokens)
        elif output_tokens and not input_tokens:
            input_tokens = max(0, total_tokens - output_tokens)
    else:
        total_tokens = input_tokens + output_tokens
    return input_tokens, output_tokens, total_tokens


def usage_stats_from_payload(usage: Any, *, latency_ms: int = 0) -> UsageStats:
    usage_dict = usage_to_dict(usage)
    input_tokens, output_tokens, total_tokens = usage_tokens_from_dict(usage_dict)
    cached_tokens = cached_input_tokens_from_usage(usage_dict)
    cache_creation_tokens = cache_creation_input_tokens_from_usage(usage_dict)
    return UsageStats(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=min(cached_tokens, input_tokens) if input_tokens else cached_tokens,
        cache_creation_input_tokens=min(cache_creation_tokens, input_tokens) if input_tokens else cache_creation_tokens,
        provider_raw_usage=usage_dict,
        estimated_cost=0.0,
        latency_ms=max(0, int(latency_ms or 0)),
    )
