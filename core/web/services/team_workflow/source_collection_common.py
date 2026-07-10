"""Shared pure helpers for source-collection projections."""

from __future__ import annotations

from typing import Any


def trim_text(value: Any, *, max_length: int) -> str:
    text = str(value or "").strip()
    return text[:max_length]


def source_collection_count(value: Any, *, maximum: int = 100_000) -> int:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(maximum, number))


def normalize_source_collection_stage_id(value: Any, *, default: str = "finding") -> str:
    stage_id = trim_text(value, max_length=80)
    if not stage_id:
        return default
    return stage_id


def normalize_source_collection_agent_role(value: Any) -> str:
    return trim_text(value, max_length=80)


def normalize_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        trim_text(key, max_length=80): normalize_metadata_value(item)
        for key, item in value.items()
        if trim_text(key, max_length=80)
    }


def normalize_metadata_value(value: Any) -> Any:
    if isinstance(value, str):
        return trim_text(value, max_length=1000)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [normalize_metadata_value(item) for item in value[:24]]
    if isinstance(value, dict):
        return normalize_metadata(value)
    return trim_text(value, max_length=1000)


def normalize_text_list(value: Any, *, max_items: int, max_length: int) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value[:max_items]:
        text = trim_text(item, max_length=max_length)
        if text and text not in normalized:
            normalized.append(text)
    return normalized
