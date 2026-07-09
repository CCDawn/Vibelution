"""Pure source-collection context helpers."""

from __future__ import annotations

from typing import Any

from .source_collection_common import source_collection_count, trim_text


def normalize_source_collection_context_mode(value: Any) -> str:
    normalized = trim_text(value, max_length=40).lower()
    if normalized in {"full", "compact", "minimal", "retry_missing"}:
        return normalized
    return "compact"


def source_collection_context_continuation_hint(candidate_page: dict[str, Any], *, context_mode: str) -> str:
    if not isinstance(candidate_page, dict) or not bool(candidate_page.get("hasMore")):
        return ""
    next_offset = source_collection_count(candidate_page.get("nextOffset"))
    limit = source_collection_count(candidate_page.get("limit")) or 5
    mode = normalize_source_collection_context_mode(context_mode)
    return f"hasMore: source_collection_context_tool(candidate_offset={next_offset}, candidate_limit={limit}, context_mode={mode})"


def source_collection_context_record_continuation_hint(record_page: dict[str, Any], *, context_mode: str) -> str:
    if not isinstance(record_page, dict) or not bool(record_page.get("hasMore")):
        return ""
    next_offset = source_collection_count(record_page.get("nextOffset"))
    limit = source_collection_count(record_page.get("limit")) or 5
    mode = normalize_source_collection_context_mode(context_mode)
    return f"hasMore: source_collection_context_tool(record_offset={next_offset}, record_limit={limit}, context_mode={mode})"
