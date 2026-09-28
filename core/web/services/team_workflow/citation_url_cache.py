"""Team-scoped cross-run cache for citation URL verification results.

The citation recheck loop already resumes verified URLs *within one run
ledger*, but the ledger lives next to a single run artifact
(``question_runs/<question>/<run>.citation-recheck.jsonl``), so every new
run — of the same question or a different one citing the same source —
re-verifies every URL from scratch.  On the only real recheck ledger so far
57% of URL attempts fail (publisher auth walls / definitive registry
rejections), and each failure burns the per-URL retry ladder again.

This module adds the missing sharing layer: one JSONL ledger per team under
``research_workflow/`` holding the latest verification outcome per source
URL.  Fresh ``verified`` entries let any run skip the network entirely;
fresh *definitive* failures (``doi_definitive_rejection:*`` /
``non_retryable``) act as a negative cache so walled sources are not
hammered again.  Transient failures (``attempts_exhausted`` with no
definitive reason) are never cached — the next run retries them as today.

Entries are advisory only: a lost or stale entry can cause a safe
re-verification, never a wrong pass (the same contract as the recheck
resume ledger).
"""

from __future__ import annotations

import os
import tempfile
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

CACHE_RECORD_KIND = "citation_url_cache_event"
CACHE_SCHEMA_VERSION = 1

# A verified source rarely un-verifies; refresh it lazily after two weeks.
VERIFIED_TTL_MS = 14 * 24 * 60 * 60 * 1000
# Walled sources do occasionally open up; retry the wall once a day.
NEGATIVE_TTL_MS = 24 * 60 * 60 * 1000
# Rewrite the ledger (latest-wins per URL) once stale appends dominate.
_COMPACT_DUPLICATE_RATIO = 4

_LOCK = threading.RLock()


def _utc_now_ms() -> int:
    import time

    return int(time.time() * 1000)


def citation_url_cache_path(team_id: str) -> Path:
    """``<team workspace>/research_workflow/citation_url_cache.jsonl``.

    Sits next to the hypothesis chain ledger, inheriting its seeded-sandbox
    resolution so dev sandboxes and tests redirect together with every other
    research_workflow ledger.
    """

    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain_store,
    )

    return hypothesis_first_chain_store._storage_path(team_id).parent / "citation_url_cache.jsonl"


def is_cacheable_failure_reason(reason: str) -> bool:
    """True for definitive, network-learned failures worth a negative TTL.

    ``attempts_exhausted`` (transient trouble) and ``no_doi_authority``
    (deterministic, already network-free) stay out of the cache.
    """

    value = str(reason or "").strip()
    return value.startswith("doi_definitive_rejection") or value == "non_retryable"


def read_citation_url_cache(team_id: str) -> dict[str, dict[str, Any]]:
    """Latest-wins view of the cache: ``{sourceUrl: entry}`` (never raises)."""

    import json

    path = citation_url_cache_path(team_id)
    latest: dict[str, dict[str, Any]] = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if str(record.get("recordKind") or "") != CACHE_RECORD_KIND:
                    continue
                source_url = str(record.get("sourceUrl") or "").strip()
                if source_url:
                    latest[source_url] = record
    except OSError:
        return {}
    return latest


def is_fresh(entry: Mapping[str, Any], *, now_ms: int | None = None) -> bool:
    """True when the entry's outcome is still within its policy TTL."""

    outcome = str(entry.get("outcome") or "")
    try:
        at_ms = int(entry.get("atMs") or 0)
    except (TypeError, ValueError):
        return False
    if not at_ms:
        return False
    now = now_ms if now_ms is not None else _utc_now_ms()
    if outcome == "verified":
        return now - at_ms < VERIFIED_TTL_MS
    if outcome == "failed":
        return is_cacheable_failure_reason(str(entry.get("reason") or "")) and (
            now - at_ms < NEGATIVE_TTL_MS
        )
    return False


def split_fresh(
    cache: Mapping[str, Mapping[str, Any]],
    *,
    now_ms: int | None = None,
) -> tuple[dict[str, bool], dict[str, dict[str, Any]]]:
    """Split a cache view into fresh ``verified`` and fresh-negative parts."""

    verified = {
        str(url): True
        for url, entry in cache.items()
        if str(entry.get("outcome") or "") == "verified" and is_fresh(entry, now_ms=now_ms)
    }
    negative = {
        str(url): dict(entry)
        for url, entry in cache.items()
        if str(entry.get("outcome") or "") == "failed" and is_fresh(entry, now_ms=now_ms)
    }
    return verified, negative


def record_citation_url_results(
    team_id: str,
    entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Append new outcomes and compact the ledger when appends dominate.

    Each entry needs ``sourceUrl``/``outcome``/``reason``; ``atMs`` defaults
    to now.  Returns ``{"appended", "compacted"}`` counts; failures return
    ``{"error": ...}`` instead of raising (the cache is advisory).
    """

    import json

    if not entries:
        return {"appended": 0, "compacted": False}
    path = citation_url_cache_path(team_id)
    now_ms = _utc_now_ms()
    records: list[dict[str, Any]] = []
    for entry in entries:
        source_url = str(entry.get("sourceUrl") or "").strip()
        outcome = str(entry.get("outcome") or "").strip()
        if not source_url or outcome not in {"verified", "failed"}:
            continue
        records.append(
            {
                "schemaVersion": CACHE_SCHEMA_VERSION,
                "recordKind": CACHE_RECORD_KIND,
                "sourceUrl": source_url,
                "outcome": outcome,
                "reason": str(entry.get("reason") or "").strip(),
                "questionId": str(entry.get("questionId") or "").strip().upper(),
                "runId": str(entry.get("runId") or "").strip(),
                "atMs": int(entry.get("atMs") or now_ms),
            }
        )
    if not records:
        return {"appended": 0, "compacted": False}
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8", newline="\n") as handle:
                for record in records:
                    handle.write(
                        json.dumps(
                            record,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
            if _needs_compaction(path):
                _compact(path)
    except OSError as exc:
        return {"error": str(exc) or type(exc).__name__}
    return {"appended": len(records), "compacted": True}


def _needs_compaction(path: Path) -> bool:
    import json

    try:
        with open(path, encoding="utf-8") as handle:
            lines = [line for line in handle if line.strip()]
    except OSError:
        return False
    distinct: set[str] = set()
    for line in lines:
        try:
            record = json.loads(line)
        except (TypeError, ValueError):
            continue
        source_url = str(record.get("sourceUrl") or "").strip()
        if source_url:
            distinct.add(source_url)
    return len(distinct) > 0 and len(lines) > len(distinct) * _COMPACT_DUPLICATE_RATIO


def _compact(path: Path) -> None:
    import json

    from core.web.services.team_workflow.storage_durability import inter_process_lock

    with inter_process_lock(path):
        try:
            with open(path, encoding="utf-8") as handle:
                records = []
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except (TypeError, ValueError):
                        continue
        except OSError:
            return
        latest: dict[str, dict[str, Any]] = {}
        for record in records:
            if str(record.get("recordKind") or "") != CACHE_RECORD_KIND:
                continue
            source_url = str(record.get("sourceUrl") or "").strip()
            if source_url:
                latest[source_url] = record
        ordered = sorted(latest.values(), key=lambda r: int(r.get("atMs") or 0))
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                for record in ordered:
                    handle.write(
                        json.dumps(
                            record,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)


__all__ = [
    "CACHE_RECORD_KIND",
    "CACHE_SCHEMA_VERSION",
    "NEGATIVE_TTL_MS",
    "VERIFIED_TTL_MS",
    "citation_url_cache_path",
    "is_cacheable_failure_reason",
    "is_fresh",
    "read_citation_url_cache",
    "record_citation_url_results",
    "split_fresh",
]
