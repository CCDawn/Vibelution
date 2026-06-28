# -*- coding: utf-8 -*-
"""Runtime prompt-cache diagnostics shared by Agent and UI runtime state."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from core.context.volatility import is_volatile_context_text


def _coerce_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _now_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _preview(text: Any, *, limit: int = 180) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "..."


def compact_repeated_metadata_text(value: Any, *, max_chars: int = 300) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    compacted = text
    for unit_length in range(1, (len(text) // 2) + 1):
        if len(text) % unit_length:
            continue
        unit = text[:unit_length]
        if len(unit.strip()) < 3:
            continue
        if unit * (len(text) // unit_length) == text:
            compacted = unit
            break
    if len(compacted) > max_chars:
        return compacted[:max_chars].rstrip()
    return compacted


def estimate_segment_tokens(chars: int, item_count: int = 0) -> int:
    return max(0, int((max(0, chars) + 2) // 3) + max(0, item_count) * 8)


def _message_role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role") or "").strip().lower()
    if isinstance(message, SystemMessage):
        return "system"
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, AIMessage):
        return "assistant"
    if isinstance(message, ToolMessage):
        return "tool"
    return str(getattr(message, "type", "") or "").strip().lower()


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                block_type = str(block.get("type") or "text").strip().lower()
                if block_type in {"", "text", "input_text"}:
                    parts.append(str(block.get("text") or block.get("content") or ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n\n".join(part for part in parts if part)
    return str(content or "")


def _message_text(message: Any) -> str:
    if isinstance(message, dict):
        return _content_text(message.get("content"))
    return _content_text(getattr(message, "content", ""))


def _system_cache_control_text(message: Any) -> tuple[str, str]:
    if not isinstance(message, dict):
        return "", _message_text(message)
    if str(message.get("role") or "").strip().lower() != "system":
        return "", _message_text(message)
    content = message.get("content")
    if not isinstance(content, list):
        return "", _message_text(message)
    cacheable_parts: list[str] = []
    dynamic_parts: list[str] = []
    for block in content:
        text = _content_text([block])
        if not text:
            continue
        if isinstance(block, dict) and block.get("cache_control"):
            cacheable_parts.append(text)
        else:
            dynamic_parts.append(text)
    return "\n\n".join(cacheable_parts), "\n\n".join(dynamic_parts)


def _segment(
    key: str,
    label: str,
    *,
    text: str,
    item_count: int,
    source: str,
    cache_policy: str,
    placement: str,
    prompt_category: str,
    order: int,
    description: str,
) -> dict[str, Any]:
    chars = len(text or "")
    return {
        "key": key,
        "label": label,
        "chars": chars,
        "tokens": estimate_segment_tokens(chars, item_count),
        "itemCount": max(0, int(item_count or 0)),
        "status": "included",
        "source": source,
        "description": description,
        "kind": prompt_category,
        "placement": placement,
        "cachePolicy": cache_policy,
        "includedInModelInput": True,
        "contentPreview": _preview(text),
        "promptCategory": prompt_category,
        "segmentKind": "prompt_source",
        "order": order,
    }


def build_runtime_context_composition(
    messages: list[Any] | tuple[Any, ...] | None,
    *,
    turn_id: str = "",
    prompt_cache_partition: str = "",
    context_limit: int = 0,
) -> dict[str, Any]:
    """Build a bounded context manifest for non-session Agent turns."""

    normalized = list(messages or [])
    last_user_index = -1
    for index, message in enumerate(normalized):
        if _message_role(message) in {"user", "human"}:
            last_user_index = index

    segments: list[dict[str, Any]] = []
    ordering: list[str] = []

    def add(item: dict[str, Any]) -> None:
        if _coerce_nonnegative_int(item.get("tokens") or 0) <= 0:
            return
        item["order"] = len(segments)
        segments.append(item)
        ordering.append(str(item.get("key") or ""))

    first_index = 0
    if normalized and _message_role(normalized[0]) == "system":
        cacheable_text, dynamic_text = _system_cache_control_text(normalized[0])
        if cacheable_text:
            add(
                _segment(
                    "system_cache_prefix",
                    "system / tools",
                    text=cacheable_text,
                    item_count=1,
                    source="agent_system_prompt",
                    cache_policy="prefix_candidate",
                    placement="system_prefix",
                    prompt_category="system_prompt",
                    order=0,
                    description="Cacheable system prompt prefix sent with provider cache control.",
                )
            )
        elif _message_text(normalized[0]):
            text = _message_text(normalized[0])
            add(
                _segment(
                    "system_prompt",
                    "system prompt",
                    text=text,
                    item_count=1,
                    source="agent_system_prompt",
                    cache_policy="prefix_candidate" if not is_volatile_context_text(text) else "volatile",
                    placement="system_prefix",
                    prompt_category="system_prompt",
                    order=0,
                    description="System prompt message; cacheability inferred from volatility marker.",
                )
            )
        if dynamic_text:
            add(
                _segment(
                    "system_dynamic_suffix",
                    "dynamic system suffix",
                    text=dynamic_text,
                    item_count=1,
                    source="agent_system_prompt",
                    cache_policy="volatile",
                    placement="before_current_user",
                    prompt_category="runtime_context",
                    order=0,
                    description="Dynamic system suffix outside the stable cache prefix.",
                )
            )
        first_index = 1

    stable_history: list[str] = []
    stable_history_count = 0
    volatile_blocks: list[str] = []
    volatile_count = 0
    current_turn_blocks: list[str] = []
    current_turn_count = 0
    current_user_text = ""

    for index, message in enumerate(normalized[first_index:], start=first_index):
        text = _message_text(message)
        if not text:
            continue
        role = _message_role(message)
        if index == last_user_index and role in {"user", "human"}:
            current_user_text = text
            continue
        if is_volatile_context_text(text):
            volatile_blocks.append(text)
            volatile_count += 1
            continue
        if last_user_index >= 0 and index < last_user_index:
            stable_history.append(text)
            stable_history_count += 1
        else:
            current_turn_blocks.append(text)
            current_turn_count += 1

    if stable_history:
        add(
            _segment(
                "history",
                "history",
                text="\n\n".join(stable_history),
                item_count=stable_history_count,
                source="agent_turn_history",
                cache_policy="prefix_candidate",
                placement="history",
                prompt_category="history",
                order=0,
                description="Prior stable turn history before current volatile context.",
            )
        )
    if volatile_blocks:
        add(
            _segment(
                "volatile_runtime_context",
                "volatile runtime context",
                text="\n\n".join(volatile_blocks),
                item_count=volatile_count,
                source="agent_runtime_context",
                cache_policy="volatile",
                placement="before_current_user",
                prompt_category="runtime_context",
                order=0,
                description="Per-turn runtime guidance or dynamic context excluded from stable carryover.",
            )
        )
    if current_user_text:
        add(
            _segment(
                "current_user",
                "current input",
                text=current_user_text,
                item_count=1,
                source="current_turn",
                cache_policy="never_cache",
                placement="current_user",
                prompt_category="current_input",
                order=0,
                description="Current external input for this model call.",
            )
        )
    if current_turn_blocks:
        add(
            _segment(
                "current_turn_context",
                "current turn context",
                text="\n\n".join(current_turn_blocks),
                item_count=current_turn_count,
                source="current_turn",
                cache_policy="never_cache",
                placement="after_current_user",
                prompt_category="current_turn",
                order=0,
                description="Assistant/tool context produced inside the current turn before this model call.",
            )
        )

    total_chars = sum(_coerce_nonnegative_int(item.get("chars") or 0) for item in segments)
    total_tokens = sum(_coerce_nonnegative_int(item.get("tokens") or 0) for item in segments)
    return {
        "schemaVersion": 1,
        "source": "agent_runtime",
        "turnId": str(turn_id or "").strip(),
        "promptCachePartition": str(prompt_cache_partition or "").strip(),
        "segments": segments,
        "modelInputOrdering": ordering,
        "totalChars": total_chars,
        "totalTokens": total_tokens,
        "limitTokens": max(0, int(context_limit or 0)),
        "cache": {
            "cacheableSegmentCount": len(
                [item for item in segments if item.get("cachePolicy") in {"prefix_candidate", "cacheable"}]
            ),
            "volatileSegmentCount": len(
                [item for item in segments if item.get("cachePolicy") not in {"prefix_candidate", "cacheable"}]
            ),
        },
        "recordedAt": _now_timestamp(),
    }


def build_llm_usage_from_observation(
    token_usage: Any,
    *,
    response_metadata: dict[str, Any] | None = None,
    runtime_metadata: dict[str, Any] | None = None,
    recorded_at: str = "",
) -> dict[str, Any]:
    response_metadata = response_metadata if isinstance(response_metadata, dict) else {}
    runtime_metadata = runtime_metadata if isinstance(runtime_metadata, dict) else {}
    observed = bool(getattr(token_usage, "observed", False))
    input_tokens = _coerce_nonnegative_int(getattr(token_usage, "input_tokens", 0)) if observed else 0
    output_tokens = _coerce_nonnegative_int(getattr(token_usage, "output_tokens", 0)) if observed else 0
    cached_tokens = min(_coerce_nonnegative_int(getattr(token_usage, "cached_input_tokens", 0)), input_tokens) if input_tokens else 0
    cache_creation_tokens = (
        min(_coerce_nonnegative_int(getattr(token_usage, "cache_creation_input_tokens", 0)), input_tokens)
        if input_tokens
        else 0
    )
    uncached_tokens = _coerce_nonnegative_int(getattr(token_usage, "uncached_input_tokens", 0))
    if input_tokens and not uncached_tokens:
        uncached_tokens = max(0, input_tokens - cached_tokens)
    return {
        "source": "provider_usage" if observed else "missing",
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": _coerce_nonnegative_int(getattr(token_usage, "total_tokens", input_tokens + output_tokens))
        if observed
        else 0,
        "cachedInputTokens": cached_tokens,
        "cacheReadInputTokens": cached_tokens,
        "cacheCreationInputTokens": cache_creation_tokens,
        "uncachedInputTokens": uncached_tokens if observed else 0,
        "cacheHitRate": (cached_tokens / input_tokens) if observed and input_tokens > 0 else 0.0,
        "provider": compact_repeated_metadata_text(response_metadata.get("provider") or runtime_metadata.get("provider") or ""),
        "model": compact_repeated_metadata_text(response_metadata.get("model") or runtime_metadata.get("model") or ""),
        "llmModelId": str(
            response_metadata.get("llmModelId")
            or response_metadata.get("modelId")
            or runtime_metadata.get("llmModelId")
            or runtime_metadata.get("modelId")
            or ""
        ).strip(),
        "promptCacheScope": str(
            response_metadata.get("promptCacheScope")
            or runtime_metadata.get("cacheScope")
            or runtime_metadata.get("promptCacheScope")
            or ""
        ).strip(),
        "promptCachePartition": str(
            response_metadata.get("promptCachePartition")
            or runtime_metadata.get("promptCachePartition")
            or ""
        ).strip(),
        "recordedAt": str(recorded_at or _now_timestamp()).strip(),
    }


def normalize_runtime_llm_usage(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    input_tokens = _coerce_nonnegative_int(value.get("inputTokens") or value.get("input_tokens") or 0)
    cached_tokens = min(
        _coerce_nonnegative_int(
            value.get("cachedInputTokens")
            or value.get("cached_input_tokens")
            or value.get("cacheReadInputTokens")
            or value.get("cache_read_input_tokens")
            or 0
        ),
        input_tokens,
    ) if input_tokens else 0
    output_tokens = _coerce_nonnegative_int(value.get("outputTokens") or value.get("output_tokens") or 0)
    total_tokens = _coerce_nonnegative_int(value.get("totalTokens") or value.get("total_tokens") or 0)
    if not total_tokens:
        total_tokens = input_tokens + output_tokens
    cache_creation_tokens = min(
        _coerce_nonnegative_int(value.get("cacheCreationInputTokens") or value.get("cache_creation_input_tokens") or 0),
        input_tokens,
    ) if input_tokens else 0
    uncached_tokens = _coerce_nonnegative_int(value.get("uncachedInputTokens") or value.get("uncached_input_tokens") or 0)
    if input_tokens and not uncached_tokens:
        uncached_tokens = max(0, input_tokens - cached_tokens)
    source = str(value.get("source") or "").strip() or ("provider_usage" if input_tokens else "missing")
    return {
        "source": source,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": total_tokens,
        "cachedInputTokens": cached_tokens,
        "cacheReadInputTokens": cached_tokens,
        "cacheCreationInputTokens": cache_creation_tokens,
        "uncachedInputTokens": uncached_tokens,
        "cacheHitRate": (cached_tokens / input_tokens) if input_tokens > 0 else 0.0,
        "provider": compact_repeated_metadata_text(value.get("provider") or ""),
        "model": compact_repeated_metadata_text(value.get("model") or ""),
        "llmModelId": str(value.get("llmModelId") or value.get("llm_model_id") or "").strip(),
        "promptCacheScope": str(value.get("promptCacheScope") or value.get("prompt_cache_scope") or "").strip(),
        "promptCachePartition": str(value.get("promptCachePartition") or value.get("prompt_cache_partition") or "").strip(),
        "recordedAt": str(value.get("recordedAt") or value.get("recorded_at") or _now_timestamp()).strip(),
    }


def _computed_segments(
    *,
    input_tokens: int,
    context_composition: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], int, int]:
    context = context_composition if isinstance(context_composition, dict) else {}
    segments: list[dict[str, Any]] = []
    raw_segments = [item for item in list(context.get("segments") or []) if isinstance(item, dict)]
    order = list(context.get("modelInputOrdering") or [])
    if order:
        by_key = {str(item.get("key") or ""): item for item in raw_segments}
        raw_segments = [by_key[key] for key in order if key in by_key]
    computed_cached = 0
    computed_uncached = 0
    for index, item in enumerate(raw_segments):
        tokens = _coerce_nonnegative_int(item.get("tokens") or item.get("estimatedTokens") or 0)
        if tokens <= 0:
            tokens = estimate_segment_tokens(
                _coerce_nonnegative_int(item.get("chars") or 0),
                _coerce_nonnegative_int(item.get("itemCount") or 0),
            )
        if tokens <= 0:
            continue
        cache_policy = str(item.get("cachePolicy") or item.get("cache_policy") or "").strip()
        is_hit_candidate = cache_policy in {"prefix_candidate", "cacheable", "assumed_stable_prefix"}
        status = "computed_hit" if is_hit_candidate else "computed_miss"
        if is_hit_candidate:
            computed_cached += tokens
        else:
            computed_uncached += tokens
        segments.append(
            {
                "key": str(item.get("key") or f"segment_{index}").strip(),
                "label": str(item.get("label") or item.get("key") or f"segment_{index}").strip(),
                "tokens": tokens,
                "status": status,
                "source": str(item.get("source") or "").strip(),
                "description": str(item.get("description") or "").strip(),
                "cachePolicy": cache_policy,
                "order": index,
                "contentPreview": str(item.get("contentPreview") or "").strip(),
                "promptCategory": str(item.get("promptCategory") or item.get("prompt_category") or "").strip(),
                "segmentKind": str(item.get("segmentKind") or item.get("segment_kind") or "prompt_source").strip(),
                "estimated": bool(item.get("estimated", True)),
            }
        )
    mapped_tokens = computed_cached + computed_uncached
    remainder = max(0, _coerce_nonnegative_int(input_tokens) - mapped_tokens)
    if remainder:
        computed_cached += remainder
        segments.append(
            {
                "key": "provider_input_remainder",
                "label": "provider input remainder",
                "tokens": remainder,
                "status": "computed_hit",
                "source": "provider_input_remainder",
                "description": "Provider input tokens not covered by the runtime context manifest.",
                "cachePolicy": "assumed_stable_prefix",
                "order": len(segments),
                "contentPreview": "Provider 输入剩余未映射段；用于提示这里仍是估算边界。",
                "promptCategory": "provider_unmapped",
                "segmentKind": "prompt_source",
                "estimated": True,
            }
        )
    return segments, computed_cached, computed_uncached


def build_runtime_cache_composition(
    *,
    turn_id: str = "",
    llm_usage: dict[str, Any] | None,
    context_composition: dict[str, Any] | None = None,
    average_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    usage = normalize_runtime_llm_usage(llm_usage)
    if usage is None or usage.get("source") != "provider_usage":
        return {
            "turnId": str(turn_id or "").strip(),
            "recordedAt": _now_timestamp(),
            "source": "missing",
            "inputTokens": 0,
            "cachedInputTokens": 0,
            "cacheCreationInputTokens": 0,
            "uncachedInputTokens": 0,
            "cacheHitRate": 0.0,
            "segments": [{"key": "missing", "label": "missing", "tokens": 1, "status": "missing"}],
            "computedSegments": [],
            "calibratedSegments": [],
        }

    input_tokens = _coerce_nonnegative_int(usage.get("inputTokens") or 0)
    cached_tokens = min(_coerce_nonnegative_int(usage.get("cachedInputTokens") or 0), input_tokens) if input_tokens else 0
    cache_creation_tokens = (
        min(_coerce_nonnegative_int(usage.get("cacheCreationInputTokens") or 0), input_tokens)
        if input_tokens
        else 0
    )
    uncached_tokens = max(0, input_tokens - cached_tokens)
    computed, computed_cached, computed_uncached = _computed_segments(
        input_tokens=input_tokens,
        context_composition=context_composition,
    )
    remaining_cached = cached_tokens
    calibrated: list[dict[str, Any]] = []
    for item in computed:
        segment = dict(item)
        tokens = _coerce_nonnegative_int(segment.get("tokens") or 0)
        if segment.get("status") == "computed_hit":
            observed_cached = min(tokens, remaining_cached)
            remaining_cached = max(0, remaining_cached - observed_cached)
            observed_missed = max(0, tokens - observed_cached)
        else:
            observed_cached = 0
            observed_missed = tokens
        segment["observedCachedInputTokens"] = observed_cached
        segment["observedMissedInputTokens"] = observed_missed
        segment["computedOverestimatedInputTokens"] = observed_missed if item.get("status") == "computed_hit" else 0
        segment["providerExtraCachedInputTokens"] = 0
        if observed_cached and observed_missed:
            segment["observedStatus"] = "observed_partial"
        elif observed_cached:
            segment["observedStatus"] = "observed_hit"
        elif observed_missed:
            segment["observedStatus"] = "observed_miss"
        else:
            segment["observedStatus"] = "not_observed"
        calibrated.append(segment)
    if remaining_cached > 0:
        calibrated.append(
            {
                "key": "provider_extra_hit",
                "label": "provider extra cached",
                "tokens": remaining_cached,
                "status": "provider_extra_hit",
                "source": "provider_usage",
                "description": "Provider reported cached input that the runtime context manifest could not map.",
                "cachePolicy": "provider_observed",
                "order": len(calibrated),
                "contentPreview": "Additional provider cache read outside the mapped runtime context manifest.",
                "promptCategory": "provider_unmapped",
                "segmentKind": "prompt_source",
                "observedStatus": "observed_hit",
                "observedCachedInputTokens": remaining_cached,
                "observedMissedInputTokens": 0,
                "computedOverestimatedInputTokens": 0,
                "providerExtraCachedInputTokens": remaining_cached,
            }
        )

    average_cache = average_cache if isinstance(average_cache, dict) else {}
    average_input = _coerce_nonnegative_int(average_cache.get("inputTokens") or average_cache.get("totalInputTokens") or 0)
    average_cached = min(
        _coerce_nonnegative_int(average_cache.get("cachedInputTokens") or average_cache.get("totalCachedInputTokens") or 0),
        average_input,
    ) if average_input else 0
    overestimated = max(0, computed_cached - cached_tokens)
    provider_extra = max(0, cached_tokens - computed_cached)
    status = "aligned"
    reason = "Provider cache usage matches the computed stable-prefix upper bound for mapped input tokens."
    if overestimated:
        status = "provider_lower_than_computed"
        reason = "Provider cache usage is lower than the runtime computed stable-prefix upper bound."
    elif provider_extra:
        status = "provider_higher_than_computed"
        reason = "Provider reported more cached input than the runtime context manifest can map."
    return {
        "turnId": str(turn_id or "").strip(),
        "recordedAt": usage.get("recordedAt") or _now_timestamp(),
        "source": "provider_usage",
        "provider": usage.get("provider") or "",
        "model": usage.get("model") or "",
        "llmModelId": usage.get("llmModelId") or "",
        "promptCacheScope": usage.get("promptCacheScope") or "",
        "promptCachePartition": usage.get("promptCachePartition") or "",
        "inputTokens": input_tokens,
        "cachedInputTokens": cached_tokens,
        "cacheReadInputTokens": cached_tokens,
        "cacheCreationInputTokens": cache_creation_tokens,
        "uncachedInputTokens": uncached_tokens,
        "cacheHitRate": (cached_tokens / input_tokens) if input_tokens > 0 else 0.0,
        "segments": [
            {"key": "cached", "label": "cached", "tokens": cached_tokens, "status": "hit"},
            {"key": "cache_write", "label": "cache write", "tokens": cache_creation_tokens, "status": "write"},
            {"key": "uncached", "label": "uncached", "tokens": uncached_tokens, "status": "miss"},
        ],
        "computedInputTokens": max(input_tokens, computed_cached + computed_uncached),
        "computedCachedInputTokens": computed_cached,
        "computedUncachedInputTokens": computed_uncached,
        "computedCacheHitRate": (computed_cached / input_tokens) if input_tokens > 0 else 0.0,
        "computedSegments": computed,
        "upperBoundInputTokens": max(input_tokens, computed_cached + computed_uncached),
        "upperBoundCachedInputTokens": computed_cached,
        "upperBoundUncachedInputTokens": computed_uncached,
        "upperBoundCacheHitRate": (computed_cached / input_tokens) if input_tokens > 0 else 0.0,
        "calibratedInputTokens": input_tokens,
        "calibratedCachedInputTokens": cached_tokens,
        "calibratedCacheHitRate": (cached_tokens / input_tokens) if input_tokens > 0 else 0.0,
        "calibratedSegments": calibrated,
        "computedOverestimatedInputTokens": overestimated,
        "providerExtraCachedInputTokens": provider_extra,
        "calibrationStatus": status,
        "calibrationReason": reason,
        "predictedInputTokens": input_tokens,
        "predictedCachedInputTokens": cached_tokens,
        "predictedUncachedInputTokens": uncached_tokens,
        "predictedCacheHitRate": (cached_tokens / input_tokens) if input_tokens > 0 else 0.0,
        "predictionStatus": status,
        "predictionReason": reason,
        "averageInputTokens": average_input,
        "averageCachedInputTokens": average_cached,
        "averageObservedTurnCount": _coerce_nonnegative_int(
            average_cache.get("observedTurnCount") or average_cache.get("totalObservedTurnCount") or 0
        ),
    }
