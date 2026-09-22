# -*- coding: utf-8 -*-
"""Post-hoc compression x cache telemetry.

Answers, per session: how much did context compression save, what did each
compression boundary cost in provider prompt-cache rewrites, and how much of
each follow-up request input is replayed compressed history?

This module is read-only aggregation over two existing stores:

- the conversation ledger (``core.chat.context_compression_ledger``) for
  ``compaction_checkpoint`` and ``context_compression_attempt`` events, and
- the usage ledger (``core.llm.usage_ledger``) for per-request cached /
  cache-creation / input tokens.

No ledger write semantics, event schema, or compression trigger/execution
path is modified.  A write-time snapshot (recording the last usage row's
cached tokens into the checkpoint payload) was rejected on purpose: the
append site lives in the compression execution path and a cross-store read
there would couple the turn hot path to usage-ledger latency for data the
post-hoc join already recovers.

Metric definitions
------------------

compression volume
    ``compressionCount`` counts ``compaction_checkpoint`` events;
    ``savedTokensTotal`` sums their ``savedTokens``.  Attempt markers are
    counted by ``markerStatus`` (``skipped_low_savings`` /
    ``failed_preserved``) and never alter the checkpoint totals.

cache rewrite cost (per compression boundary)
    The "before" anchor is the last usage row recorded at or before the
    checkpoint timestamp (usage timestamps are truncated to whole seconds,
    so same-second rows deterministically count as pre-compression).  The
    "after" anchor is the first usage row strictly after the checkpoint.
    Only rows whose ``source`` represents a real model request
    (``provider_usage`` / ``estimated``) may anchor.  When both anchors
    observed provider cache usage, ``cacheHitDropTokens`` is
    ``max(0, cacheRead(before) - cacheRead(after))``: the approximate share
    of the previous request's cache prefix that the compression invalidated
    (re-read at miss pricing or rewritten).  ``cacheWriteTokensAfter``
    carries the after-anchor's ``cache_creation_input_tokens`` for
    providers that report explicit cache writes.

replay share (per compression boundary)
    ``replayedTokens`` is the checkpoint's ``afterTokens`` (the compressed
    history replayed at the head of later prompts); ``coveredTokens`` is
    its ``beforeTokens`` (the original range it replaced).
    ``replayRatio`` divides ``afterTokens`` by the after-anchor's
    ``input_tokens``; the aggregate divides the sums, so it stays an
    input-weighted approximation.

Timestamps from the two stores use different ISO-8601 spellings
(``+00:00`` vs ``Z``), so ordering parses timestamps instead of comparing
strings.  Rows and checkpoints without a parseable timestamp are counted in
diagnostics but never anchored.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .context_compression_ledger import (
    EVENT_COMPACTION_CHECKPOINT,
    EVENT_COMPRESSION_ATTEMPT,
)
from .turn_journal import TurnJournalEvent, load_turn_events

TELEMETRY_SCHEMA = "context_compression_cache_telemetry.v1"

_ATTEMPT_SKIPPED_STATUS = "skipped_low_savings"
_ATTEMPT_FAILED_STATUS = "failed_preserved"
_NON_REQUEST_USAGE_SOURCES = {"missing", "not_called"}

_CACHE_REWRITE_COMPLETE = "complete"
_CACHE_REWRITE_PARTIAL = "partial"
_CACHE_REWRITE_MISSING = "missing"


def build_compression_cache_telemetry(
    events: Iterable[TurnJournalEvent],
    usage_rows: Iterable[Any],
    *,
    session_id: str = "",
    anchor_sources: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Join compression checkpoint events with usage rows and aggregate.

    ``usage_rows`` accepts mappings (sqlite rows) or objects with matching
    snake_case attributes (``UsageLedgerEvent``).  Rows must already be
    scoped to one session; ordering ties keep the caller's insertion order.
    """

    anchors = (
        frozenset(str(source or "").strip() for source in anchor_sources)
        if anchor_sources is not None
        else _default_anchor_sources()
    )
    event_list = [event for event in list(events or []) if isinstance(event, TurnJournalEvent)]
    checkpoints = sorted(
        (event for event in event_list if event.event_type == EVENT_COMPACTION_CHECKPOINT),
        key=lambda event: (_timestamp_key(event.timestamp), int(event.sequence or 0)),
    )
    attempts = [event for event in event_list if event.event_type == EVENT_COMPRESSION_ATTEMPT]
    rows = sorted(
        (row for row in list(usage_rows or []) if _row_value(row, "recorded_at")),
        key=_timestamp_key,
    )
    anchor_rows = [
        row
        for row in rows
        if str(_row_value(row, "source") or "") in anchors
        and _timestamp_key(_row_value(row, "recorded_at")) > 0.0
    ]

    compressions: list[dict[str, Any]] = []
    saved_total = 0
    before_total = 0
    after_total = 0
    evidence_count = 0
    cache_hit_before_sum = 0
    cache_hit_after_sum = 0
    cache_hit_drop_sum = 0
    cache_write_after_sum = 0
    replay_with_evidence = 0
    replayed_tokens_sum = 0
    covered_tokens_sum = 0
    next_input_sum = 0

    for checkpoint in checkpoints:
        payload = dict(checkpoint.payload or {})
        before_tokens = _nonnegative_int(payload.get("beforeTokens"))
        after_tokens = _nonnegative_int(payload.get("afterTokens"))
        saved_tokens = _nonnegative_int(payload.get("savedTokens")) or max(
            0, before_tokens - after_tokens
        )
        saved_total += saved_tokens
        before_total += before_tokens
        after_total += after_tokens

        before_row, after_row = _anchor_pair(anchor_rows, checkpoint.timestamp)
        cache_block = _cache_block(before_row, after_row)
        replay_block = _replay_block(after_row, after_tokens, before_tokens)
        if cache_block["cacheHitDropTokens"] is not None:
            evidence_count += 1
            cache_hit_before_sum += int(cache_block["before"]["cacheReadInputTokens"] or 0)
            cache_hit_after_sum += int(cache_block["after"]["cacheReadInputTokens"] or 0)
            cache_hit_drop_sum += int(cache_block["cacheHitDropTokens"] or 0)
            cache_write_after_sum += int(cache_block["cacheWriteTokensAfter"] or 0)
        if replay_block["nextInputTokens"] is not None:
            replay_with_evidence += 1
            replayed_tokens_sum += after_tokens
            covered_tokens_sum += before_tokens
            next_input_sum += int(replay_block["nextInputTokens"] or 0)

        compressions.append(
            {
                "eventId": checkpoint.event_id,
                "sequence": int(checkpoint.sequence or 0),
                "turnId": checkpoint.turn_id,
                "timestamp": checkpoint.timestamp,
                "level": str(payload.get("level") or ""),
                "reason": str(payload.get("reason") or "")[:200],
                "triggerSource": str(payload.get("triggerSource") or ""),
                "iteration": _nonnegative_int(payload.get("iteration")),
                "beforeTokens": before_tokens,
                "afterTokens": after_tokens,
                "savedTokens": saved_tokens,
                "effectivenessRatio": _nonnegative_float(payload.get("effectivenessRatio")),
                "coveredEventCount": _nonnegative_int(payload.get("coveredEventCount")),
                "cache": cache_block,
                "replay": replay_block,
            }
        )

    compression_count = len(checkpoints)
    if compression_count and evidence_count == compression_count:
        cache_evidence = _CACHE_REWRITE_COMPLETE
    elif evidence_count:
        cache_evidence = _CACHE_REWRITE_PARTIAL
    else:
        cache_evidence = _CACHE_REWRITE_MISSING

    return {
        "schema": TELEMETRY_SCHEMA,
        "sessionId": str(session_id or "").strip(),
        "compressionCount": compression_count,
        "savedTokensTotal": saved_total,
        "beforeTokensTotal": before_total,
        "afterTokensTotal": after_total,
        "attemptCount": len(attempts),
        "skippedAttemptCount": _count_attempts(attempts, _ATTEMPT_SKIPPED_STATUS),
        "failedAttemptCount": _count_attempts(attempts, _ATTEMPT_FAILED_STATUS),
        "cacheRewrite": {
            "evidence": cache_evidence,
            "compressionsWithCacheEvidence": evidence_count,
            "cacheHitTokensBefore": cache_hit_before_sum,
            "cacheHitTokensAfter": cache_hit_after_sum,
            "cacheHitDropTokens": cache_hit_drop_sum,
            "cacheWriteTokensAfter": cache_write_after_sum,
        },
        "replay": {
            "compressionsWithReplayEvidence": replay_with_evidence,
            "replayedTokens": replayed_tokens_sum,
            "coveredTokens": covered_tokens_sum,
            "nextRequestInputTokens": next_input_sum,
            "replayRatio": round(replayed_tokens_sum / next_input_sum, 4)
            if next_input_sum > 0
            else 0.0,
        },
        "compressions": compressions,
        "diagnostics": {
            "checkpointEventsScanned": compression_count,
            "attemptEventsScanned": len(attempts),
            "usageRowsScanned": len(rows),
            "usageAnchorRowsScanned": len(anchor_rows),
        },
    }


def collect_compression_cache_telemetry(project_root: Path, session_id: str) -> dict[str, Any]:
    """Load both stores for one session and return the aggregated telemetry."""

    normalized_session_id = str(session_id or "").strip()
    root = Path(project_root)
    if not normalized_session_id:
        return build_compression_cache_telemetry([], [], session_id="")
    events = load_turn_events(root, normalized_session_id)
    rows = load_session_usage_rows(root, normalized_session_id)
    return build_compression_cache_telemetry(
        events,
        rows,
        session_id=normalized_session_id,
    )


def load_session_usage_rows(project_root: Path, session_id: str) -> list[dict[str, Any]]:
    """Read-only usage-ledger query for one session (no schema DDL, no writes)."""

    from core.llm.usage_ledger import usage_ledger_path

    path = usage_ledger_path(project_root)
    if not path.exists():
        return []
    anchors = sorted(_default_anchor_sources())
    placeholders = ", ".join("?" for _ in anchors)
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    try:
        cursor = connection.execute(
            f"""
            SELECT event_id, recorded_at, turn_id, source,
                   input_tokens, cached_input_tokens, cache_read_input_tokens,
                   cache_creation_input_tokens, uncached_input_tokens,
                   total_tokens, cache_usage_observed
            FROM usage_events
            WHERE session_id = ? AND source IN ({placeholders})
            ORDER BY recorded_at ASC, rowid ASC
            """,
            (session_id, *anchors),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        connection.close()


def _default_anchor_sources() -> frozenset[str]:
    """Real-request usage sources; mirrors ``usage_ledger.VALID_SOURCES``."""

    from core.llm.usage_ledger import VALID_SOURCES

    return frozenset(str(source) for source in VALID_SOURCES) - _NON_REQUEST_USAGE_SOURCES


def _cache_block(
    before_row: Any | None,
    after_row: Any | None,
) -> dict[str, Any]:
    before = _usage_anchor_payload(before_row)
    after = _usage_anchor_payload(after_row)
    drop: int | None = None
    cache_write_after: int | None = None
    if (
        before is not None
        and after is not None
        and before["cacheUsageObserved"]
        and after["cacheUsageObserved"]
    ):
        drop = max(
            0,
            int(before["cacheReadInputTokens"] or 0) - int(after["cacheReadInputTokens"] or 0),
        )
        cache_write_after = int(after["cacheCreationInputTokens"] or 0)
    return {
        "before": before,
        "after": after,
        "cacheHitDropTokens": drop,
        "cacheWriteTokensAfter": cache_write_after,
    }


def _replay_block(after_row: Any | None, replayed_tokens: int) -> dict[str, Any]:
    if after_row is None:
        return {
            "nextRecordedAt": "",
            "nextEventId": "",
            "nextInputTokens": None,
            "coveredTokens": None,
            "replayRatio": None,
        }
    next_input = _nonnegative_int(_row_value(after_row, "input_tokens"))
    ratio = round(replayed_tokens / next_input, 4) if next_input > 0 else None
    return {
        "nextRecordedAt": str(_row_value(after_row, "recorded_at") or ""),
        "nextEventId": str(_row_value(after_row, "event_id") or ""),
        "nextInputTokens": next_input,
        "coveredTokens": replayed_tokens,
        "replayRatio": ratio,
    }


def _usage_anchor_payload(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    observed = bool(_row_value(row, "cache_usage_observed"))
    cached = _nonnegative_int(_row_value(row, "cached_input_tokens")) if observed else 0
    cache_read = _nonnegative_int(_row_value(row, "cache_read_input_tokens")) if observed else 0
    return {
        "eventId": str(_row_value(row, "event_id") or ""),
        "recordedAt": str(_row_value(row, "recorded_at") or ""),
        "turnId": str(_row_value(row, "turn_id") or ""),
        "source": str(_row_value(row, "source") or ""),
        "inputTokens": _nonnegative_int(_row_value(row, "input_tokens")),
        "cachedInputTokens": cached,
        "cacheReadInputTokens": cache_read if cache_read > 0 else cached,
        "cacheCreationInputTokens": (
            _nonnegative_int(_row_value(row, "cache_creation_input_tokens")) if observed else 0
        ),
        "uncachedInputTokens": (
            _nonnegative_int(_row_value(row, "uncached_input_tokens")) if observed else 0
        ),
        "cacheUsageObserved": observed,
    }


def _anchor_pair(rows: list[Any], timestamp: str) -> tuple[Any | None, Any | None]:
    """Resolve (before, after) usage anchors for one checkpoint instant.

    The "before" anchor is the last row at or before the checkpoint instant:
    usage timestamps are truncated to whole seconds, so a row sharing the
    checkpoint's second deterministically counts as pre-compression.  The
    "after" anchor is the first row strictly after it.  Checkpoints with a
    non-parseable timestamp anchor nothing.
    """

    key = _timestamp_key(timestamp)
    if key <= 0.0:
        return None, None
    before: Any | None = None
    for row in rows:
        row_key = _timestamp_key(_row_value(row, "recorded_at"))
        if row_key <= key:
            before = row
        else:
            return before, row
    return before, None


def _replay_block(
    after_row: Any | None,
    replayed_tokens: int,
    covered_tokens: int,
) -> dict[str, Any]:
    if after_row is None:
        return {
            "nextRecordedAt": "",
            "nextEventId": "",
            "nextInputTokens": None,
            "coveredTokens": None,
            "replayRatio": None,
        }
    next_input = _nonnegative_int(_row_value(after_row, "input_tokens"))
    ratio = round(replayed_tokens / next_input, 4) if next_input > 0 else None
    return {
        "nextRecordedAt": str(_row_value(after_row, "recorded_at") or ""),
        "nextEventId": str(_row_value(after_row, "event_id") or ""),
        "nextInputTokens": next_input,
        "coveredTokens": covered_tokens,
        "replayRatio": ratio,
    }


def _count_attempts(attempts: list[TurnJournalEvent], status: str) -> int:
    count = 0
    for attempt in attempts:
        payload = dict(attempt.payload or {})
        marker = str(payload.get("markerStatus") or attempt.status or "").strip()
        if marker == status:
            count += 1
    return count


def _row_value(row: Any, key: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    return getattr(row, key, None)


def _timestamp_key(value: Any) -> float:
    """Parse an ISO-8601 timestamp into a comparable epoch float.

    The two stores spell UTC differently (``+00:00`` vs ``Z``); naive
    values are treated as UTC.  Unparseable or empty values sort first and
    are excluded from anchoring by the callers.
    """

    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _nonnegative_float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "build_compression_cache_telemetry",
    "collect_compression_cache_telemetry",
    "load_session_usage_rows",
]
