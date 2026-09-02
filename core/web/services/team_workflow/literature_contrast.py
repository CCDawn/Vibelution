"""Fail-open literature contrast retrieval for hypothesis novelty review.

Before the reflection review step scores a candidate, this module runs a
bounded, metadata-only literature search so the novelty judgement is grounded
in retrievable evidence instead of the reviewer model's memory alone.

Design constraints (deliberate):

* **Not a model call.**  Retrieval is pure HTTP through the shared
  source-collection search transport (``_execute_source_collection_query``),
  so the exact FORMAL review-call budget ``n + n(n-1)/2 + 2`` is untouched.
* **Fail-open.**  Any failure — transport error, timeout, empty results —
  degrades to ``{"papers": [], "degraded": True}`` and the review proceeds
  normally.  Retrieval never blocks or fails a review round.
* **Mechanical queries.**  Query strings are built deterministically from the
  candidate's own ``claim`` and ``differenceFromAlternatives``; no model
  generates queries.
* **Contrast is not a citation.**  Retrieved papers have no canonical ref, so
  they must never enter ``evidence_refs``; they only inform rationale prose
  and the structured ``noveltyContrast`` conclusion.
* **Reuse on re-review.**  Results are cached per (candidateId, claim,
  difference) so a repeated reflection for the same candidate content does
  not re-query the providers.
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
from collections import OrderedDict
from typing import Any, Mapping

from core.web.services.team_workflow.source_collection.search_execution import (
    _execute_source_collection_query,
)

# arXiv + OpenAlex cover preprints and journal literature; Crossref alone
# misses arXiv preprints, so it is intentionally not part of the contrast set
# (the ids mirror SOURCE_COLLECTION_SEARCH_PROVIDERS in the orchestration
# service registry).
CONTRAST_PROVIDERS = ("arxiv_api", "openalex_api")

# Per query top-8, merged and deduplicated down to at most 10 papers.
RESULTS_PER_QUERY = 8
CONTRAST_PAPER_LIMIT = 10

# Abstracts are the agreed sufficient unit for novelty contrast; 1000 chars
# keeps the injected payload bounded.
ABSTRACT_MAX_CHARS = 1000
TITLE_MAX_CHARS = 260
URL_MAX_CHARS = 500
QUERY_MAX_CHARS = 200

# Overall wall-clock budget for one candidate's retrieval fan-out.  Stragglers
# are abandoned (their transport attempts self-terminate afterwards); the
# review continues with whatever completed, or degraded when nothing did.
RETRIEVAL_DEADLINE_SECONDS = 20.0

_MAX_CACHE_ENTRIES = 64
_MAX_RECORDED_ERRORS = 5

_CACHE: "OrderedDict[tuple[str, ...], dict[str, Any]]" = OrderedDict()
_CACHE_LOCK = threading.Lock()


def build_literature_contrast_queries(candidate: Mapping[str, Any] | None) -> list[str]:
    """Build the mechanical query strings for one candidate.

    Query 1 is the candidate claim, query 2 the difference statement; both are
    whitespace-normalized and truncated.  Empty or duplicated entries are
    dropped while preserving order.
    """

    source = candidate if isinstance(candidate, Mapping) else {}
    queries: list[str] = []
    for key in ("claim", "differenceFromAlternatives"):
        text = " ".join(str(source.get(key) or "").split())
        if not text:
            continue
        query = text[:QUERY_MAX_CHARS]
        if query not in queries:
            queries.append(query)
    return queries


def _degraded_contrast(
    queries: list[str],
    *,
    reason: str,
    started_at: float,
    errors: list[str] | None = None,
    timed_out: int = 0,
) -> dict[str, Any]:
    return {
        "papers": [],
        "queries": list(queries),
        "degraded": True,
        "retrievalMeta": {
            "providers": list(CONTRAST_PROVIDERS),
            "retrievedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "durationMs": max(0, int((time.monotonic() - started_at) * 1000)),
            "paperCount": 0,
            "timedOutQueries": int(timed_out),
            "errors": [str(item) for item in list(errors or [])][:_MAX_RECORDED_ERRORS],
            "degradedReason": str(reason),
        },
    }


def _paper_from_result(item: Mapping[str, Any], provider: str) -> dict[str, Any] | None:
    """Project one shared search-result shape onto the bounded contrast shape."""

    if not isinstance(item, Mapping):
        return None
    title = " ".join(str(item.get("title") or "").split())[:TITLE_MAX_CHARS]
    if not title:
        return None
    paper: dict[str, Any] = {
        "title": title,
        "provider": str(provider),
    }
    url = str(item.get("rawLocation") or item.get("sourceRef") or "").strip()[:URL_MAX_CHARS]
    if url:
        paper["url"] = url
    metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
    for target, source_key in (
        ("year", "publicationYear"),
        ("venue", "venue"),
        ("citationCount", "citationCount"),
    ):
        value = metadata.get(source_key)
        if value is None:
            value = item.get(source_key)
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        if value not in (None, ""):
            paper[target] = value
    abstract = " ".join(str(item.get("summary") or "").split())[:ABSTRACT_MAX_CHARS]
    if abstract:
        paper["abstract"] = abstract
    return paper


def _query_one(query: str, provider: str) -> list[Mapping[str, Any]]:
    response = _execute_source_collection_query(
        {"query": query},
        max_results=RESULTS_PER_QUERY,
        provider=provider,
    )
    if not isinstance(response, Mapping):
        raise ValueError(f"{provider}: invalid search response")
    error = str(response.get("error") or "").strip()
    if error:
        raise ValueError(f"{provider}: {error[:200]}")
    results = response.get("results")
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, Mapping)]


def _run_contrast_queries_attributed(
    queries: list[str],
    *,
    deadline_seconds: float,
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Run every (query, provider) job under one wall-clock deadline.

    Returns the merged, deduplicated, capped papers (each tagged with its
    provider), short error strings, and the number of jobs that exceeded the
    deadline.  Single-job failures only degrade that job.
    """

    jobs = [(query, provider) for query in queries for provider in CONTRAST_PROVIDERS]
    collected: list[tuple[str, Mapping[str, Any]]] = []
    errors: list[str] = []
    timed_out = 0
    if not jobs:
        return [], errors, timed_out
    pool = concurrent.futures.ThreadPoolExecutor(
        max_workers=min(4, len(jobs)),
        thread_name_prefix="hf-literature-contrast",
    )
    try:
        future_to_job = {
            pool.submit(_query_one, query, provider): (query, provider)
            for query, provider in jobs
        }
        done, pending = concurrent.futures.wait(
            list(future_to_job),
            timeout=max(0.05, float(deadline_seconds)),
        )
        timed_out = len(pending)
        for future in pending:
            future.cancel()
        if timed_out:
            errors.append(
                f"{timed_out} retrieval job(s) exceeded the {deadline_seconds:.0f}s deadline"
            )
        # Collect in deterministic submission order (not completion order) so
        # the merged, deduplicated paper list is stable for the same input.
        for future, (_query, provider) in future_to_job.items():
            if future not in done:
                continue
            try:
                for item in future.result():
                    collected.append((provider, item))
            except Exception as exc:  # noqa: BLE001 - single-job failure degrades only that job
                errors.append(str(exc)[:200] or type(exc).__name__)
    finally:
        pool.shutdown(wait=False)
    papers: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    seen_urls: set[str] = set()
    for provider, item in collected:
        paper = _paper_from_result(item, provider)
        if paper is None:
            continue
        title_key = paper["title"].lower()
        url_key = str(paper.get("url") or "").strip().lower()
        if title_key in seen_titles or (url_key and url_key in seen_urls):
            continue
        seen_titles.add(title_key)
        if url_key:
            seen_urls.add(url_key)
        papers.append(paper)
        if len(papers) >= CONTRAST_PAPER_LIMIT:
            break
    return papers, errors, timed_out


def _cache_key(candidate: Mapping[str, Any], queries: list[str]) -> tuple[str, ...]:
    candidate_id = str(candidate.get("candidateId") or "").strip()
    return (candidate_id, *queries)


def _cache_get(key: tuple[str, ...]) -> dict[str, Any] | None:
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
        return cached


def _cache_put(key: tuple[str, ...], contrast: dict[str, Any]) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = contrast
        _CACHE.move_to_end(key)
        while len(_CACHE) > _MAX_CACHE_ENTRIES:
            _CACHE.popitem(last=False)


def clear_cache() -> None:
    """Drop every cached contrast (test and maintenance helper)."""

    with _CACHE_LOCK:
        _CACHE.clear()


def retrieve_literature_contrast(
    candidate: Mapping[str, Any] | None,
    *,
    deadline_seconds: float = RETRIEVAL_DEADLINE_SECONDS,
) -> dict[str, Any]:
    """Retrieve the bounded literature contrast for one candidate.

    Always returns a mapping; never raises.  ``degraded`` is ``True`` exactly
    when no usable paper was retrieved, and the review must proceed normally
    in that case.
    """

    started_at = time.monotonic()
    source = candidate if isinstance(candidate, Mapping) else {}
    queries = build_literature_contrast_queries(source)
    if not queries:
        return _degraded_contrast(
            queries, reason="candidate_has_no_retrievable_text", started_at=started_at
        )
    key = _cache_key(source, queries)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        papers, errors, timed_out = _run_contrast_queries_attributed(
            queries, deadline_seconds=deadline_seconds
        )
    except Exception as exc:  # noqa: BLE001 - evidence retrieval must never block review
        degraded = _degraded_contrast(
            queries,
            reason=f"retrieval_error: {str(exc)[:200] or type(exc).__name__}",
            started_at=started_at,
        )
        _cache_put(key, degraded)
        return degraded
    contrast = {
        "papers": papers,
        "queries": list(queries),
        "degraded": not papers,
        "retrievalMeta": {
            "providers": list(CONTRAST_PROVIDERS),
            "retrievedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "durationMs": max(0, int((time.monotonic() - started_at) * 1000)),
            "paperCount": len(papers),
            "timedOutQueries": int(timed_out),
            "errors": errors[:_MAX_RECORDED_ERRORS],
            **({} if papers else {"degradedReason": "no_results"}),
        },
    }
    _cache_put(key, contrast)
    return contrast


__all__ = [
    "ABSTRACT_MAX_CHARS",
    "CONTRAST_PAPER_LIMIT",
    "CONTRAST_PROVIDERS",
    "QUERY_MAX_CHARS",
    "RETRIEVAL_DEADLINE_SECONDS",
    "RESULTS_PER_QUERY",
    "build_literature_contrast_queries",
    "clear_cache",
    "retrieve_literature_contrast",
]
