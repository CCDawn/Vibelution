"""Stat-signature memoization for parsed knowledge file reads and search products.

Claim scope: parsed-file read cache plus a content-keyed ``search_memo``
namespace for per-item search-document derived products.

The parsed-file cache memoizes the PARSE result of a knowledge JSON/JSONL file
keyed by ``(path, mtime_ns, size)``; it never caches retrieval scan results,
candidate sets, or rankings. Any file change (write, append, external edit)
produces a new stat signature and therefore a fresh parse; the store write
helpers additionally drop the affected path eagerly.

The ``search_memo`` namespace caches deterministic per-item derived products
(the search document plus its BM25/filter token products) keyed by a sha256 of
every input that builds the document. It is content-addressed: any content
change produces a new key, so it needs no write-side invalidation hooks, and it
never stores corpus-level statistics (N/avgdl/df/idf depend on the per-query
candidate set and stay per-query).

Served values are defensive shallow copies (per-item ``dict()`` copies for
JSONL rows, per-base copies for registry payloads, one-level document copies
for search products): callers that sort lists or patch top-level fields before
rewriting must not poison the cached entry.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

_CACHE_LOCK = threading.Lock()
_CACHE_MAX_ENTRIES = 128
_CACHE: dict[str, dict[str, Any]] = {}

# Separate lock on purpose: the parse cache is stat-keyed, path-addressable and
# eagerly dropped on writes (FIFO, 128 entries), while the search memo is
# content-keyed, LRU with a character budget, and never write-invalidated.
# Distinct lifetimes and eviction policies; sharing one lock would couple
# contention between the two unrelated namespaces without any shared state.
_SEARCH_MEMO_LOCK = threading.Lock()
_SEARCH_MEMO: OrderedDict[str, dict[str, Any]] = OrderedDict()
_SEARCH_MEMO_MAX_ENTRIES = 1024
_SEARCH_MEMO_MAX_TOTAL_CHARS = 32 * 1024 * 1024
_SEARCH_MEMO_TOTAL_CHARS = 0


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


def cached_search_memo(key: str) -> dict[str, Any] | None:
    """Return a defensive copy of memoized search products, or ``None`` on miss.

    The copy is one level deep: the ``document`` dict is copied per hit; token
    tuples/frozensets/Counter/strings are shared read-only and must never be
    mutated by callers.
    """

    normalized_key = str(key or "")
    if not normalized_key:
        return None
    with _SEARCH_MEMO_LOCK:
        entry = _SEARCH_MEMO.get(normalized_key)
        if not isinstance(entry, dict):
            return None
        _SEARCH_MEMO.move_to_end(normalized_key)
    products = entry.get("products")
    if not isinstance(products, dict):
        return None
    copied = dict(products)
    document = copied.get("document")
    if isinstance(document, dict):
        copied["document"] = dict(document)
    return copied


def store_search_memo(key: str, products: dict[str, Any], *, estimated_chars: int) -> None:
    """Memoize search products under a content key (LRU + entry/char budgets)."""

    global _SEARCH_MEMO_TOTAL_CHARS
    normalized_key = str(key or "")
    if not normalized_key or not isinstance(products, dict):
        return
    size = max(0, int(estimated_chars or 0))
    with _SEARCH_MEMO_LOCK:
        previous = _SEARCH_MEMO.get(normalized_key)
        if isinstance(previous, dict):
            _SEARCH_MEMO_TOTAL_CHARS -= int(previous.get("estimatedChars") or 0)
        _SEARCH_MEMO[normalized_key] = {"products": products, "estimatedChars": size}
        _SEARCH_MEMO_TOTAL_CHARS += size
        _SEARCH_MEMO.move_to_end(normalized_key)
        _evict_search_memo_locked()


def search_memo_stats() -> dict[str, int]:
    """Return entry/character occupancy for tests and observability."""

    with _SEARCH_MEMO_LOCK:
        return {"entries": len(_SEARCH_MEMO), "estimatedChars": _SEARCH_MEMO_TOTAL_CHARS}


def _evict_search_memo_locked() -> None:
    global _SEARCH_MEMO_TOTAL_CHARS
    # Always keep the most recent entry even if it alone exceeds the character
    # budget, so one large document cannot wipe the whole memo.
    while len(_SEARCH_MEMO) > 1 and (
        len(_SEARCH_MEMO) > _SEARCH_MEMO_MAX_ENTRIES
        or _SEARCH_MEMO_TOTAL_CHARS > _SEARCH_MEMO_MAX_TOTAL_CHARS
    ):
        _, dropped = _SEARCH_MEMO.popitem(last=False)
        _SEARCH_MEMO_TOTAL_CHARS -= int(dropped.get("estimatedChars") or 0)
    if _SEARCH_MEMO_TOTAL_CHARS < 0:
        _SEARCH_MEMO_TOTAL_CHARS = 0


def clear_search_memo_for_tests() -> None:
    global _SEARCH_MEMO_TOTAL_CHARS
    with _SEARCH_MEMO_LOCK:
        _SEARCH_MEMO.clear()
        _SEARCH_MEMO_TOTAL_CHARS = 0


def _evict_locked() -> None:
    while len(_CACHE) > _CACHE_MAX_ENTRIES:
        _CACHE.pop(next(iter(_CACHE)))


def reset_knowledge_read_cache_for_tests() -> None:
    invalidate_knowledge_read_cache()
    # Content-keyed memo entries are always correct, but tests get a
    # deterministic cold cache for hit/eviction assertions.
    clear_search_memo_for_tests()
