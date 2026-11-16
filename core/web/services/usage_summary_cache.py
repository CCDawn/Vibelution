"""Process-local read-through cache for the usage summary aggregate.

``build_usage_summary`` walks the whole token ledger; during the startup storm
on 2026-11-16 a single `/api/usage/summary` poll took 22-30s and the workbench
polled it every 10s, so the aggregate never finished before the next request
arrived.  Those overlapping full-ledger scans held the request threads that
session creation also needed.

The cache is keyed by the exact filter tuple the route accepts, so every
distinct filter keeps its own entry, and callers always receive a deep copy:
the route layer annotates the payload with ``updatedAt``/``breakdowns`` via
``setdefault`` and must never mutate the cached object.
"""

from __future__ import annotations

import copy
from typing import Any

from core.infrastructure.read_through_cache import ReadThroughCache
from core.llm.usage_ledger import build_usage_summary

# The UsageRoute polls every 10s while visible.  A window just under one poll
# interval still collapses a burst (opening several composer surfaces, a
# re-mount, the route becoming visible again) into one aggregate while keeping
# the displayed totals at most one poll behind.
USAGE_SUMMARY_CACHE_TTL_SECONDS = 8.0

_usage_summary_cache = ReadThroughCache(name="usage_summary")


def usage_summary_cache_key(
    *,
    scope: str,
    session_id: str = "",
    agent_id: str = "",
    provider: str = "",
    model: str = "",
) -> str:
    return "|".join(
        (
            str(scope or "").strip().lower(),
            str(session_id or "").strip(),
            str(agent_id or "").strip(),
            str(provider or "").strip(),
            str(model or "").strip(),
        )
    )


def get_usage_summary_cached(
    *,
    scope: str,
    session_id: str = "",
    agent_id: str = "",
    provider: str = "",
    model: str = "",
) -> dict[str, Any]:
    """Return one usage summary, reusing a recent aggregate of the same filters."""

    key = usage_summary_cache_key(
        scope=scope,
        session_id=session_id,
        agent_id=agent_id,
        provider=provider,
        model=model,
    )

    def compute() -> dict[str, Any]:
        return build_usage_summary(
            scope=scope,
            session_id=session_id,
            agent_id=agent_id,
            provider=provider,
            model=model,
        )

    cached = _usage_summary_cache.get_or_compute(
        key,
        compute,
        USAGE_SUMMARY_CACHE_TTL_SECONDS,
        should_cache=lambda value: isinstance(value, dict) and bool(value),
    )
    return copy.deepcopy(cached)


def reset_usage_summary_cache_for_tests() -> None:
    _usage_summary_cache.clear()


def usage_summary_cache_stats() -> dict[str, int]:
    return _usage_summary_cache.stats()
