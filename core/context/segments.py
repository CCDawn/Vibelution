"""Context segment and manifest primitives.

The manifest is the observable contract for what a turn assembled, where each
piece belongs, whether it entered model input, and how it affects prompt cache.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable


CONTEXT_MANIFEST_SCHEMA_VERSION = 1

_MODEL_PLACEMENT_ORDER = {
    "system_prefix": 0,
    "before_history": 1,
    "history": 2,
    "after_history": 3,
    "before_current_user": 4,
    "current_user": 5,
}


def _coerce_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _bounded_score(value: Any, *, default: int = 0) -> int:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return bool(value)


def _short_hash(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        text = str(value)
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def estimate_segment_tokens(chars: int, item_count: int = 0) -> int:
    return max(0, int((max(0, chars) + 2) // 3) + max(0, item_count) * 8)


def _model_input_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = [
        (index, item)
        for index, item in enumerate(segments)
        if item.get("includedInModelInput")
    ]
    indexed.sort(
        key=lambda pair: (
            _MODEL_PLACEMENT_ORDER.get(str(pair[1].get("placement") or ""), 99),
            pair[0],
        )
    )
    return [item for _, item in indexed]


@dataclass(frozen=True)
class ContextSegment:
    key: str
    label: str
    chars: int = 0
    tokens: int = 0
    item_count: int = 0
    status: str = "included"
    source: str = ""
    description: str = ""
    kind: str = ""
    lifecycle: str = ""
    authority: int = 0
    volatility: int = 0
    relevance: int = 0
    placement: str = ""
    cache_policy: str = ""
    retention: str = ""
    included_in_model_input: bool = True
    hash: str = ""
    evidence_ref: str = ""
    stale: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "chars": self.chars,
            "tokens": self.tokens,
            "itemCount": self.item_count,
            "status": self.status,
            "source": self.source,
            "description": self.description,
            "kind": self.kind,
            "lifecycle": self.lifecycle,
            "authority": self.authority,
            "volatility": self.volatility,
            "relevance": self.relevance,
            "placement": self.placement,
            "cachePolicy": self.cache_policy,
            "retention": self.retention,
            "includedInModelInput": self.included_in_model_input,
            "hash": self.hash,
            "stale": self.stale,
        }
        if self.evidence_ref:
            payload["evidenceRef"] = self.evidence_ref
        return payload


def build_context_segment(
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
    stale: bool = False,
    content_hash: str = "",
) -> dict[str, Any]:
    normalized_chars = _coerce_nonnegative_int(chars)
    if content is not None and not normalized_chars:
        normalized_chars = len(str(content or ""))
    normalized_count = _coerce_nonnegative_int(item_count)
    normalized_tokens = _coerce_nonnegative_int(tokens) or estimate_segment_tokens(
        normalized_chars,
        normalized_count,
    )
    segment = ContextSegment(
        key=str(key or "").strip(),
        label=str(label or key or "").strip(),
        chars=normalized_chars,
        tokens=normalized_tokens,
        item_count=normalized_count,
        status=str(status or "included").strip() or "included",
        source=str(source or "").strip(),
        description=str(description or "").strip(),
        kind=str(kind or key or "").strip(),
        lifecycle=str(lifecycle or "").strip(),
        authority=_bounded_score(authority),
        volatility=_bounded_score(volatility),
        relevance=_bounded_score(relevance),
        placement=str(placement or "").strip(),
        cache_policy=str(cache_policy or "").strip(),
        retention=str(retention or "").strip(),
        included_in_model_input=_coerce_bool(included_in_model_input, default=True),
        hash=str(content_hash or _short_hash(content if content is not None else {
            "key": key,
            "source": source,
            "chars": normalized_chars,
            "tokens": normalized_tokens,
            "status": status,
        })).strip(),
        evidence_ref=str(evidence_ref or "").strip(),
        stale=_coerce_bool(stale),
    )
    return segment.to_dict()


def normalize_context_segment(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    key = str(value.get("key") or "").strip()
    if not key:
        return None
    chars = _coerce_nonnegative_int(value.get("chars") or 0)
    item_count = _coerce_nonnegative_int(value.get("itemCount") or value.get("item_count") or 0)
    tokens = _coerce_nonnegative_int(value.get("tokens") or value.get("estimatedTokens") or 0)
    if not tokens:
        tokens = estimate_segment_tokens(chars, item_count)
    included = value.get("includedInModelInput")
    if included is None:
        included = value.get("included_in_model_input")
    if included is None:
        included = str(value.get("status") or "included").strip().lower() != "omitted"
    return {
        "key": key,
        "label": str(value.get("label") or key).strip() or key,
        "chars": chars,
        "tokens": tokens,
        "itemCount": item_count,
        "status": str(value.get("status") or "included").strip() or "included",
        "source": str(value.get("source") or "").strip(),
        "description": str(value.get("description") or "").strip(),
        "kind": str(value.get("kind") or key).strip() or key,
        "lifecycle": str(value.get("lifecycle") or "").strip(),
        "authority": _bounded_score(value.get("authority") or 0),
        "volatility": _bounded_score(value.get("volatility") or 0),
        "relevance": _bounded_score(value.get("relevance") or 0),
        "placement": str(value.get("placement") or "").strip(),
        "cachePolicy": str(value.get("cachePolicy") or value.get("cache_policy") or "").strip(),
        "retention": str(value.get("retention") or "").strip(),
        "includedInModelInput": _coerce_bool(included, default=True),
        "hash": str(value.get("hash") or "").strip(),
        "evidenceRef": str(value.get("evidenceRef") or value.get("evidence_ref") or "").strip(),
        "stale": _coerce_bool(value.get("stale")),
    }


def build_context_manifest(
    *,
    turn_id: str,
    recorded_at: str,
    source: str,
    segments: Iterable[dict[str, Any]],
    limit_tokens: int = 0,
    limit_source: str = "",
    limit_model_id: str = "",
    limit_agent_id: str = "",
    prompt_cache_partition: str = "",
) -> dict[str, Any]:
    normalized_segments = [
        item for item in (normalize_context_segment(segment) for segment in segments) if item is not None
    ]
    included_segments = [
        item for item in normalized_segments if item.get("includedInModelInput")
    ]
    omitted_segments = [
        item for item in normalized_segments if not item.get("includedInModelInput")
    ]
    observed_chars = sum(_coerce_nonnegative_int(item.get("chars") or 0) for item in normalized_segments)
    observed_tokens = sum(_coerce_nonnegative_int(item.get("tokens") or 0) for item in normalized_segments)
    total_chars = sum(_coerce_nonnegative_int(item.get("chars") or 0) for item in included_segments)
    total_tokens = sum(_coerce_nonnegative_int(item.get("tokens") or 0) for item in included_segments)
    omitted_tokens = sum(_coerce_nonnegative_int(item.get("tokens") or 0) for item in omitted_segments)
    cacheable_segments = [
        item for item in normalized_segments
        if item.get("includedInModelInput") and item.get("cachePolicy") == "cacheable"
    ]
    volatile_segments = [
        item for item in normalized_segments
        if item.get("includedInModelInput")
        and (item.get("cachePolicy") in {"volatile", "never_cache"} or _bounded_score(item.get("volatility")) >= 70)
    ]
    model_input_segments = _model_input_segments(normalized_segments)
    first_volatile_index = -1
    for index, item in enumerate(model_input_segments):
        if item in volatile_segments:
            first_volatile_index = index
            break
    stable_hash_input = [
        {
            "key": item.get("key"),
            "hash": item.get("hash"),
            "chars": item.get("chars"),
            "tokens": item.get("tokens"),
        }
        for item in cacheable_segments
    ]
    limit = _coerce_nonnegative_int(limit_tokens)
    return {
        "schemaVersion": CONTEXT_MANIFEST_SCHEMA_VERSION,
        "turnId": str(turn_id or "").strip(),
        "recordedAt": str(recorded_at or "").strip(),
        "source": str(source or "runtime_assembly").strip() or "runtime_assembly",
        "totalChars": total_chars,
        "totalTokens": total_tokens,
        "limitTokens": limit,
        "limitSource": str(limit_source or "").strip(),
        "limitModelId": str(limit_model_id or "").strip(),
        "limitAgentId": str(limit_agent_id or "").strip(),
        "segments": normalized_segments,
        "ordering": [str(item.get("key") or "") for item in normalized_segments],
        "modelInputOrdering": [str(item.get("key") or "") for item in model_input_segments],
        "budgets": {
            "usedTokens": total_tokens,
            "observedTokens": observed_tokens,
            "omittedTokens": omitted_tokens,
            "observedChars": observed_chars,
            "limitTokens": limit,
            "droppedTokens": 0,
            "overLimit": bool(limit > 0 and total_tokens > limit),
        },
        "cache": {
            "stablePrefixHash": _short_hash(stable_hash_input),
            "cacheableSegmentCount": len(cacheable_segments),
            "volatileSegmentCount": len(volatile_segments),
            "firstVolatileSegmentIndex": first_volatile_index,
            "promptCachePartitionHash": _short_hash(prompt_cache_partition),
            "missLikelyReason": "",
        },
    }


def normalize_context_manifest(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    segments = [
        item for item in (normalize_context_segment(segment) for segment in list(value.get("segments") or []))
        if item is not None
    ]
    if not segments:
        return None
    manifest = build_context_manifest(
        turn_id=str(value.get("turnId") or value.get("turn_id") or "").strip(),
        recorded_at=str(value.get("recordedAt") or value.get("recorded_at") or "").strip(),
        source=str(value.get("source") or "runtime_assembly").strip() or "runtime_assembly",
        segments=segments,
        limit_tokens=_coerce_nonnegative_int(value.get("limitTokens") or value.get("limit_tokens") or 0),
        limit_source=str(value.get("limitSource") or value.get("limit_source") or "").strip(),
        limit_model_id=str(value.get("limitModelId") or value.get("limit_model_id") or "").strip(),
        limit_agent_id=str(value.get("limitAgentId") or value.get("limit_agent_id") or "").strip(),
        prompt_cache_partition=str(value.get("promptCachePartition") or value.get("prompt_cache_partition") or "").strip(),
    )
    if isinstance(value.get("cache"), dict):
        manifest["cache"].update({
            key: value["cache"].get(key, manifest["cache"].get(key))
            for key in manifest["cache"]
            if key in value["cache"]
        })
    if isinstance(value.get("budgets"), dict):
        manifest["budgets"].update({
            key: value["budgets"].get(key, manifest["budgets"].get(key))
            for key in manifest["budgets"]
            if key in value["budgets"]
        })
    if isinstance(value.get("ordering"), list):
        manifest["ordering"] = [str(item or "").strip() for item in value.get("ordering") or [] if str(item or "").strip()]
    if isinstance(value.get("modelInputOrdering"), list):
        manifest["modelInputOrdering"] = [
            str(item or "").strip()
            for item in value.get("modelInputOrdering") or []
            if str(item or "").strip()
        ]
    return manifest
