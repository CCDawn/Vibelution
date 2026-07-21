"""Session context-segment and provider cache estimation helpers.

Claim scope: context segment builders/previews and provider prefix-cache
estimation/calibration used by detail projection and LLM usage surfaces.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

from typing import Any


def _service():
    from core.web.services import session_service

    return session_service


def _aggregate_session_provider_cache_usage(
    messages: list[dict[str, Any]],
    *,
    fallback_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = _service()
    usages: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int, int]] = set()
    for message in list(messages or []):
        if str((message or {}).get("role") or "").strip().lower() != "assistant":
            continue
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        usage = s._normalize_turn_llm_usage(metadata.get("llmUsage") or metadata.get("llm_usage"))
        if usage is None or usage.get("source") != "provider_usage":
            continue
        input_tokens = s._coerce_nonnegative_int(usage.get("inputTokens") or 0)
        if not input_tokens:
            continue
        key = (
            str(usage.get("recordedAt") or "").strip(),
            input_tokens,
            s._coerce_nonnegative_int(usage.get("cachedInputTokens") or 0),
            s._coerce_nonnegative_int(usage.get("outputTokens") or 0),
        )
        if key in seen:
            continue
        seen.add(key)
        usages.append(usage)
    fallback = s._normalize_turn_llm_usage(fallback_usage)
    if fallback is not None and fallback.get("source") == "provider_usage":
        fallback_input = s._coerce_nonnegative_int(fallback.get("inputTokens") or 0)
        fallback_key = (
            str(fallback.get("recordedAt") or "").strip(),
            fallback_input,
            s._coerce_nonnegative_int(fallback.get("cachedInputTokens") or 0),
            s._coerce_nonnegative_int(fallback.get("outputTokens") or 0),
        )
        if fallback_input and fallback_key not in seen:
            usages.append(fallback)
    total_input = sum(s._coerce_nonnegative_int(item.get("inputTokens") or 0) for item in usages)
    total_cached = sum(s._coerce_nonnegative_int(item.get("cachedInputTokens") or 0) for item in usages)
    total_creation = sum(s._coerce_nonnegative_int(item.get("cacheCreationInputTokens") or 0) for item in usages)
    total_uncached = sum(s._coerce_nonnegative_int(item.get("uncachedInputTokens") or 0) for item in usages)
    if total_input and not total_uncached:
        total_uncached = max(0, total_input - total_cached)
    return {
        "inputTokens": total_input,
        "cachedInputTokens": min(total_cached, total_input) if total_input else 0,
        "cacheReadInputTokens": min(total_cached, total_input) if total_input else 0,
        "cacheCreationInputTokens": min(total_creation, total_input) if total_input else 0,
        "uncachedInputTokens": min(total_uncached, total_input) if total_input else 0,
        "cacheHitRate": (min(total_cached, total_input) / total_input) if total_input else 0.0,
        "turnCount": len(usages),
    }


def _context_segment_content_preview(value: Any) -> str:
    s = _service()
    if not isinstance(value, dict):
        return ""
    for key in (
        "contentPreview",
        "content_preview",
        "promptPreview",
        "prompt_preview",
        "content",
    ):
        preview = s._compact_preview_text(value.get(key), max_lines=3, max_chars=240)
        if preview:
            return preview
    return ""


def _attach_context_segment_content_previews(
    manifest: dict[str, Any] | None,
    previews: dict[str, str],
) -> dict[str, Any] | None:
    s = _service()
    if not isinstance(manifest, dict):
        return manifest
    updated = dict(manifest)
    next_segments: list[dict[str, Any]] = []
    for item in list(updated.get("segments") or []):
        if not isinstance(item, dict):
            continue
        segment = dict(item)
        preview = previews.get(str(segment.get("key") or "").strip()) or s._context_segment_content_preview(segment)
        if preview:
            segment["contentPreview"] = preview
        next_segments.append(segment)
    updated["segments"] = next_segments
    return updated


def _ordered_model_input_context_segments(context_composition: dict[str, Any] | None) -> list[dict[str, Any]]:
    s = _service()
    if not isinstance(context_composition, dict):
        return []
    segments = [
        dict(item)
        for item in list(context_composition.get("segments") or [])
        if isinstance(item, dict) and bool(item.get("includedInModelInput"))
    ]
    if not segments:
        return []
    by_key: dict[str, list[dict[str, Any]]] = {}
    for item in segments:
        key = str(item.get("key") or "").strip()
        if key:
            by_key.setdefault(key, []).append(item)
    ordered: list[dict[str, Any]] = []
    for key in list(context_composition.get("modelInputOrdering") or []):
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        bucket = by_key.get(normalized_key) or []
        if bucket:
            ordered.append(bucket.pop(0))
    used_ids = {id(item) for item in ordered}
    for item in segments:
        if id(item) not in used_ids:
            ordered.append(item)
    return ordered


def _estimated_provider_prefix_cache_segments(tokens: int) -> list[dict[str, Any]]:
    s = _service()
    normalized_tokens = s._coerce_nonnegative_int(tokens)
    if normalized_tokens <= 0:
        return []
    definitions = [
        {
            "key": "system_prompt",
            "label": "system prompt",
            "promptCategory": "system_prompt",
            "weight": 14,
            "description": "Estimated stable system prompt portion inside provider input not mapped by the session manifest.",
            "contentPreview": "系统提示词估算段；原文未展开。",
        },
        {
            "key": "agent_protocol",
            "label": "agent protocol",
            "promptCategory": "agent_spec",
            "weight": 14,
            "description": "Estimated agent behavior/protocol instructions inside provider input not mapped by the session manifest.",
            "contentPreview": "Agent 规范/协议估算段；原文未展开。",
        },
        {
            "key": "tool_descriptions",
            "label": "tool descriptions",
            "promptCategory": "tool_descriptions",
            "weight": 20,
            "description": "Estimated natural-language tool descriptions inside provider input not mapped by the session manifest.",
            "contentPreview": "工具描述估算段；原文未展开。",
        },
        {
            "key": "tool_schema",
            "label": "tool schema",
            "promptCategory": "tool_schema",
            "weight": 42,
            "description": "Estimated provider tool/function schema tokens inside provider input not mapped by the session manifest.",
            "contentPreview": "工具 schema / 函数定义估算段；原文未展开。",
        },
        {
            "key": "provider_unmapped",
            "label": "provider unmapped",
            "promptCategory": "provider_unmapped",
            "weight": 10,
            "description": "Provider input tokens not attributable to a known prompt segment category.",
            "contentPreview": "Provider 输入剩余未映射段；用于提示这里仍是估算边界。",
        },
    ]
    if normalized_tokens < len(definitions):
        definitions = definitions[:normalized_tokens]
    allocations = s._weighted_token_allocation(
        normalized_tokens,
        [s._coerce_nonnegative_int(item["weight"]) for item in definitions],
    )
    segments: list[dict[str, Any]] = []
    for index, (definition, allocation) in enumerate(zip(definitions, allocations), start=0):
        token_count = s._coerce_nonnegative_int(allocation)
        if token_count <= 0:
            continue
        segments.append(
            {
                "key": str(definition["key"]),
                "label": str(definition["label"]),
                "tokens": token_count,
                "status": "computed_hit",
                "source": "provider_input_remainder",
                "description": str(definition["description"]),
                "cachePolicy": "assumed_stable_prefix",
                "order": index,
                "contentPreview": str(definition["contentPreview"]),
                "promptCategory": str(definition["promptCategory"]),
                "segmentKind": "prompt_source",
                "accuracy": "estimated",
                "parentKey": "provider_input_remainder",
                "estimated": True,
            }
        )
    return segments


def _provider_cache_calibration_reason(
    *,
    provider: str,
    model: str,
    source: str,
    cache_creation_tokens: int,
    overestimated_tokens: int,
    provider_extra_cached_tokens: int,
) -> tuple[str, str]:
    s = _service()
    provider_name = provider.lower()
    model_name = model.lower()
    if source != "provider_usage":
        return (
            "not_available",
            "Provider cache usage was not returned; computed segments are shown as theoretical cache candidates.",
        )
    if overestimated_tokens > 0:
        if "xiaomi" in provider_name or "mimo" in model_name:
            if cache_creation_tokens <= 0:
                return (
                    "provider_lower_than_computed",
                    "Xiaomi/MiMo returned fewer cache-read tokens than the computed stable-prefix upper bound and reported no new cache creation for this turn.",
                )
            return (
                "provider_lower_than_computed",
                "Xiaomi/MiMo returned fewer cache-read tokens than the computed stable-prefix upper bound; the difference is attributed to computed prefix segments.",
            )
        if "qwen" in provider_name or "qwen" in model_name:
            return (
                "provider_lower_than_computed",
                "Qwen provider cache usage is lower than the computed stable-prefix upper bound; the difference is attributed to computed prefix segments.",
            )
        if "openai" in provider_name or "gpt" in model_name:
            return (
                "provider_lower_than_computed",
                "OpenAI provider cache usage is lower than the computed stable-prefix upper bound; the difference is attributed to computed prefix segments.",
            )
        return (
            "provider_lower_than_computed",
            "Provider cache usage is lower than the computed stable-prefix upper bound; the difference is attributed to computed prefix segments.",
        )
    if provider_extra_cached_tokens > 0:
        return (
            "provider_higher_than_computed",
            "Provider reported more cached input than the context manifest can map to computed cacheable segments.",
        )
    return (
        "aligned",
        "Provider cache usage matches the computed stable-prefix upper bound for mapped input tokens.",
    )


def _estimate_context_segment_tokens(chars: int, item_count: int = 0) -> int:
    s = _service()
    return max(0, int((max(0, chars) + 2) // 3) + max(0, item_count) * 8)


def _context_segment(
    key: str,
    label: str,
    *,
    content: Any = None,
    chars: int = 0,
    tokens: int = 0,
    item_count: int = 0,
    status: str = "included",
    source: str = "",
    description: str = "",
    kind: str = "",
    lifecycle: str = "",
    authority: int = 0,
    volatility: int = 0,
    relevance: int = 0,
    placement: str = "",
    cache_policy: str = "",
    retention: str = "",
    included_in_model_input: bool = True,
    evidence_ref: str = "",
    content_hash: str = "",
    stale: bool = False,
) -> dict[str, Any]:
    s = _service()
    return s.build_context_segment(
        key,
        label,
        content=content,
        chars=chars,
        tokens=tokens,
        item_count=item_count,
        status=status,
        source=source,
        description=description,
        kind=kind,
        lifecycle=lifecycle,
        authority=authority,
        volatility=volatility,
        relevance=relevance,
        placement=placement,
        cache_policy=cache_policy,
        retention=retention,
        included_in_model_input=included_in_model_input,
        evidence_ref=evidence_ref,
        content_hash=content_hash,
        stale=stale,
    )


def _agent_context_segment_label(key: str) -> str:
    s = _service()
    normalized = str(key or "").strip()
    return s._AGENT_CONTEXT_SEGMENT_LABELS.get(normalized, normalized.replace("_", " ") or "agent context")


def _session_context_segments_block(segments: Any, placement: str) -> str:
    s = _service()
    normalized_placement = str(placement or "").strip()
    return "\n\n".join(
        str(item.get("block") or "").strip()
        for item in list(segments or [])
        if isinstance(item, dict)
        and str(item.get("placement") or "").strip() == normalized_placement
        and str(item.get("block") or "").strip()
    ).strip()


def _session_context_segments_without_prompt_template(segments: Any) -> list[dict[str, Any]]:
    s = _service()
    filtered: list[dict[str, Any]] = []
    for item in list(segments or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("key") or "").strip() == "prompt_template":
            continue
        filtered.append(dict(item))
    return filtered
