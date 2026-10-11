"""Stat-signature memoization for parsed knowledge file reads.

Claim scope: parsed-file read cache only. This caches the PARSE result of a
knowledge JSON/JSONL file keyed by ``(path, mtime_ns, size)``; it never caches
retrieval scan results, candidate sets, or rankings. Any file change (write,
append, external edit) produces a new stat signature and therefore a fresh
parse; the store write helpers additionally drop the affected path eagerly.

Served values are defensive shallow copies (per-item ``dict()`` copies for
JSONL rows, per-base copies for registry payloads): callers that sort lists or
patch top-level fields before rewriting must not poison the cached entry.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

_CACHE_LOCK = threading.Lock()
_CACHE_MAX_ENTRIES = 128
_CACHE: dict[str, dict[str, Any]] = {}


def _stat_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return (int(stat.st_mtime_ns), int(stat.st_size))


def jsonl_signature(path: Path) -> tuple[int, int] | None:
    """Return the memoization signature for a JSONL path (``None`` if absent)."""

    return _stat_signature(path)


def cached_jsonl(path: Path, signature: tuple[int, int]) -> list[dict[str, Any]] | None:
    """Return a defensive copy of the cached parsed rows, or ``None`` on miss."""

    with _CACHE_LOCK:
        entry = _CACHE.get(str(path))
    if not isinstance(entry, dict) or entry.get("signature") != signature:
        return None
    items = entry.get("items")
    if not isinstance(items, list):
        return None
    return defensive_jsonl_rows(items)


def defensive_jsonl_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy parsed JSONL rows one level deep (list ops, top-level patches)."""

    return [dict(item) for item in items if isinstance(item, dict)]


def cached_jsonl_corrupt_lines(path: Path, signature: tuple[int, int]) -> int | None:
    """Return the corrupt-line count recorded for a cached entry (observability)."""

    with _CACHE_LOCK:
        entry = _CACHE.get(str(path))
    if not isinstance(entry, dict) or entry.get("signature") != signature:
        return None
    try:
        return int(entry.get("corrupt_lines") or 0)
    except (TypeError, ValueError):
        return 0


def store_jsonl(path: Path, signature: tuple[int, int], items: list[dict[str, Any]], *, corrupt_lines: int = 0) -> None:
    with _CACHE_LOCK:
        _CACHE[str(path)] = {
            "kind": "jsonl",
            "signature": signature,
            "items": list(items),
            "corrupt_lines": int(corrupt_lines or 0),
        }
        _evict_locked()


def cached_json_payload(path: Path, signature: tuple[int, int]) -> dict[str, Any] | None:
    """Return a defensive copy of a cached parsed JSON payload, or ``None``."""

    with _CACHE_LOCK:
        entry = _CACHE.get(str(path))
    if not isinstance(entry, dict) or entry.get("signature") != signature:
        return None
    payload = entry.get("payload")
    if not isinstance(payload, dict):
        return None
    return defensive_json_payload(payload)


def defensive_json_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Copy a registry payload one level deep (rows and nested lists)."""

    copied = dict(payload)
    knowledge_bases = copied.get("knowledgeBases")
    if isinstance(knowledge_bases, list):
        copied["knowledgeBases"] = [dict(row) for row in knowledge_bases if isinstance(row, dict)]
    return copied


def store_json_payload(path: Path, signature: tuple[int, int], payload: dict[str, Any]) -> None:
    with _CACHE_LOCK:
        _CACHE[str(path)] = {"kind": "json", "signature": signature, "payload": payload}
        _evict_locked()


def invalidate_knowledge_read_cache(path: Path | str | None = None) -> None:
    """Drop one cached path (write helpers) or the whole cache (tests/ops)."""

    with _CACHE_LOCK:
        if path is None:
            _CACHE.clear()
        else:
            _CACHE.pop(str(path), None)


def _evict_locked() -> None:
    while len(_CACHE) > _CACHE_MAX_ENTRIES:
        _CACHE.pop(next(iter(_CACHE)))


def reset_knowledge_read_cache_for_tests() -> None:
    invalidate_knowledge_read_cache()
