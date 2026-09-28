# -*- coding: utf-8 -*-
"""Tests for post-hoc compression x cache telemetry aggregation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.chat.context_compression_ledger import (
    EVENT_COMPACTION_CHECKPOINT,
    EVENT_COMPRESSION_ATTEMPT,
    build_context_compression_checkpoint_payload,
)
from core.chat.context_compression_telemetry import (
    build_compression_cache_telemetry,
    collect_compression_cache_telemetry,
)
from core.chat.turn_journal import SCHEMA_VERSION, TurnJournalEvent
from core.infrastructure import developer_sandbox
from core.llm.usage_ledger import UsageLedgerEvent, record_usage_event


def _ts(second: int, minute: int = 0, hour: int = 8) -> str:
    return (
        datetime(2026, 9, 21, hour, minute, second, tzinfo=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _checkpoint(
    sequence: int,
    timestamp: str,
    *,
    before_tokens: int,
    after_tokens: int,
    turn_id: str = "turn-2",
    iteration: int = 1,
) -> TurnJournalEvent:
    payload = build_context_compression_checkpoint_payload(
        summary="compressed history summary",
        level="yellow",
        reason="context budget",
        before_tokens=before_tokens,
        after_tokens=after_tokens,
        iteration=iteration,
        trigger_source="budget_gate",
        effectiveness_ratio=(before_tokens - after_tokens) / before_tokens if before_tokens else 0.0,
    )
    return TurnJournalEvent(
        schema_version=SCHEMA_VERSION,
        event_id=f"cp-{sequence}",
        session_id="session-a",
        turn_id=turn_id,
        sequence=sequence,
        event_type=EVENT_COMPACTION_CHECKPOINT,
        status="checkpointed",
        timestamp=timestamp,
        source="agent_context_compression",
        payload=payload,
    )


def _attempt(
    sequence: int,
    status: str,
    *,
    before_tokens: int = 0,
    after_tokens: int = 0,
) -> TurnJournalEvent:
    return TurnJournalEvent(
        schema_version=SCHEMA_VERSION,
        event_id=f"attempt-{sequence}",
        session_id="session-a",
        turn_id="turn-2",
        sequence=sequence,
        event_type=EVENT_COMPRESSION_ATTEMPT,
        status=status,
        timestamp=_ts(45, minute=8),
        source="agent_context_compression",
        payload={
            "markerStatus": status,
            "beforeTokens": before_tokens,
            "afterTokens": after_tokens,
            "savedTokens": max(0, before_tokens - after_tokens),
            "schema": "context_compression_attempt.v1",
        },
    )


def _usage_row(
    event_id: str,
    recorded_at: str,
    *,
    input_tokens: int = 0,
    cached_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
    cache_usage_observed: bool = True,
    source: str = "provider_usage",
    turn_id: str = "turn-2",
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "recorded_at": recorded_at,
        "turn_id": turn_id,
        "source": source,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "cache_read_input_tokens": cached_input_tokens,
        "cache_creation_input_tokens": cache_creation_input_tokens,
        "uncached_input_tokens": max(0, input_tokens - cached_input_tokens),
        "total_tokens": input_tokens,
        "cache_usage_observed": cache_usage_observed,
    }


def test_three_headline_metrics_over_two_compressions():
    events = [
        _checkpoint(10, _ts(5), before_tokens=5000, after_tokens=1200),
        _checkpoint(30, _ts(0, minute=9), before_tokens=3000, after_tokens=900),
    ]
    rows = [
        _usage_row("u1", _ts(0), input_tokens=5000, cached_input_tokens=4800),
        # Same second as the first checkpoint: counts as the pre-compression side.
        _usage_row("u2", _ts(5), input_tokens=5100, cached_input_tokens=4700),
        _usage_row(
            "u3",
            _ts(30),
            input_tokens=1400,
            cached_input_tokens=260,
            cache_creation_input_tokens=900,
        ),
        _usage_row("u4", _ts(10, minute=9), input_tokens=1000, cached_input_tokens=880),
    ]

    telemetry = build_compression_cache_telemetry(events, rows, session_id="session-a")

    # Volume: compression count and saved tokens.
    assert telemetry["compressionCount"] == 2
    assert telemetry["savedTokensTotal"] == (5000 - 1200) + (3000 - 900)

    # Cache rewrite: first boundary drops 4700 -> 260 hits; second rises (no drop).
    rewrite = telemetry["cacheRewrite"]
    assert rewrite["evidence"] == "complete"
    assert rewrite["compressionsWithCacheEvidence"] == 2
    assert rewrite["cacheHitDropTokens"] == (4700 - 260)
    assert rewrite["cacheWriteTokensAfter"] == 900
    first = telemetry["compressions"][0]
    assert first["cache"]["before"]["eventId"] == "u2"
    assert first["cache"]["after"]["eventId"] == "u3"
    assert first["cache"]["cacheHitDropTokens"] == 4700 - 260
    second = telemetry["compressions"][1]
    assert second["cache"]["before"]["eventId"] == "u3"
    assert second["cache"]["after"]["eventId"] == "u4"
    assert second["cache"]["cacheHitDropTokens"] == 0

    # Replay: compressed history vs the follow-up request input.
    replay = telemetry["replay"]
    assert replay["replayedTokens"] == 1200 + 900
    assert replay["nextRequestInputTokens"] == 1400 + 1000
    assert replay["replayRatio"] == round((1200 + 900) / (1400 + 1000), 4)
    assert first["replay"]["replayRatio"] == round(1200 / 1400, 4)
    assert second["replay"]["replayRatio"] == round(900 / 1000, 4)


def test_attempt_markers_counted_without_touching_checkpoint_totals():
    events = [
        _attempt(3, "skipped_low_savings", before_tokens=4000, after_tokens=3900),
        _attempt(5, "failed_preserved", before_tokens=4000, after_tokens=4000),
    ]

    telemetry = build_compression_cache_telemetry(events, [], session_id="session-a")

    assert telemetry["compressionCount"] == 0
    assert telemetry["savedTokensTotal"] == 0
    assert telemetry["attemptCount"] == 2
    assert telemetry["skippedAttemptCount"] == 1
    assert telemetry["failedAttemptCount"] == 1
    assert telemetry["cacheRewrite"]["evidence"] == "missing"
    assert telemetry["replay"]["replayRatio"] == 0.0
    assert telemetry["compressions"] == []


def test_unobserved_cache_rows_suppress_rewrite_evidence_but_not_replay():
    events = [_checkpoint(10, _ts(5), before_tokens=2000, after_tokens=600)]
    rows = [
        _usage_row("u1", _ts(0), input_tokens=2000, cached_input_tokens=1900),
        _usage_row(
            "u2",
            _ts(20),
            input_tokens=800,
            cached_input_tokens=0,
            cache_usage_observed=False,
        ),
    ]

    telemetry = build_compression_cache_telemetry(events, rows, session_id="session-a")

    first = telemetry["compressions"][0]
    assert first["cache"]["before"]["cacheUsageObserved"] is True
    assert first["cache"]["after"]["cacheUsageObserved"] is False
    assert first["cache"]["cacheHitDropTokens"] is None
    assert first["cache"]["cacheWriteTokensAfter"] is None
    assert telemetry["cacheRewrite"]["evidence"] == "missing"
    assert telemetry["cacheRewrite"]["cacheHitDropTokens"] == 0
    # Replay evidence only needs the follow-up request input, not cache fields.
    assert first["replay"]["nextInputTokens"] == 800
    assert first["replay"]["replayRatio"] == round(600 / 800, 4)
    assert telemetry["replay"]["replayRatio"] == round(600 / 800, 4)


def test_checkpoint_without_following_usage_has_unresolved_join():
    events = [_checkpoint(10, _ts(5), before_tokens=2000, after_tokens=600)]
    rows = [_usage_row("u1", _ts(0), input_tokens=2000, cached_input_tokens=1900)]

    telemetry = build_compression_cache_telemetry(events, rows, session_id="session-a")

    first = telemetry["compressions"][0]
    assert first["cache"]["before"]["eventId"] == "u1"
    assert first["cache"]["after"] is None
    assert first["cache"]["cacheHitDropTokens"] is None
    assert first["replay"]["nextInputTokens"] is None
    assert first["replay"]["replayRatio"] is None
    assert telemetry["cacheRewrite"]["evidence"] == "missing"
    assert telemetry["replay"]["replayRatio"] == 0.0
    assert telemetry["diagnostics"]["usageAnchorRowsScanned"] == 1


def test_non_request_and_untimestamped_rows_never_anchor():
    events = [_checkpoint(10, _ts(5), before_tokens=2000, after_tokens=600)]
    rows = [
        _usage_row("u0", "", input_tokens=2000, cached_input_tokens=1900),
        _usage_row("missing", _ts(2), input_tokens=0, cached_input_tokens=0, source="missing"),
        _usage_row(
            "not_called", _ts(3), input_tokens=0, cached_input_tokens=0, source="not_called"
        ),
        _usage_row("u1", _ts(10), input_tokens=700, cached_input_tokens=100),
    ]

    telemetry = build_compression_cache_telemetry(events, rows, session_id="session-a")

    assert telemetry["diagnostics"]["usageRowsScanned"] == 3
    assert telemetry["diagnostics"]["usageAnchorRowsScanned"] == 1
    first = telemetry["compressions"][0]
    assert first["cache"]["before"] is None
    assert first["cache"]["after"]["eventId"] == "u1"


def test_collect_joins_ledger_and_usage_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(
        developer_sandbox, "resolve_workspace_home", lambda *args, **kwargs: tmp_path / "workspace"
    )
    from core.chat.context_compression_ledger import (
        append_context_compression_checkpoint,
    )

    now = datetime.now(timezone.utc).replace(microsecond=0)
    before_at = (now - timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
    after_at = (now + timedelta(seconds=10)).isoformat().replace("+00:00", "Z")

    def record(event_id: str, recorded_at: str, cached: int, creation: int) -> None:
        record_usage_event(
            UsageLedgerEvent(
                event_id=event_id,
                recorded_at=recorded_at,
                source="provider_usage",
                scope_kind="chat_session",
                session_id="session-e2e",
                turn_id="turn-2",
                provider="openai",
                model="gpt-test",
                input_tokens=5000 if creation == 0 else 1600,
                cached_input_tokens=cached,
                cache_read_input_tokens=cached,
                cache_creation_input_tokens=creation,
                uncached_input_tokens=(5000 if creation == 0 else 1600) - cached,
                output_tokens=200,
                total_tokens=5200 if creation == 0 else 1800,
                cache_usage_observed=True,
            ),
            project_root=tmp_path,
        )

    record("u-before", before_at, cached=4800, creation=0)
    appended = append_context_compression_checkpoint(
        tmp_path,
        "session-e2e",
        turn_id="turn-2",
        current_turn_id="turn-2",
        summary="compressed history summary",
        level="yellow",
        reason="context budget",
        before_tokens=5000,
        after_tokens=1600,
        iteration=1,
    )
    assert appended is not None
    record("u-after", after_at, cached=300, creation=1250)

    telemetry = collect_compression_cache_telemetry(tmp_path, "session-e2e")

    assert telemetry["schema"] == "context_compression_cache_telemetry.v1"
    assert telemetry["sessionId"] == "session-e2e"
    assert telemetry["compressionCount"] == 1
    assert telemetry["savedTokensTotal"] == 3400
    first = telemetry["compressions"][0]
    assert first["cache"]["before"]["eventId"] == "u-before"
    assert first["cache"]["after"]["eventId"] == "u-after"
    assert first["cache"]["cacheHitDropTokens"] == 4800 - 300
    assert first["cache"]["cacheWriteTokensAfter"] == 1250
    assert first["replay"]["nextInputTokens"] == 1600
    assert first["replay"]["replayRatio"] == round(1600 / 1600, 4)
    assert telemetry["cacheRewrite"]["evidence"] == "complete"
    assert telemetry["replay"]["replayRatio"] == 1.0


def test_collect_without_session_or_ledger_is_empty_not_broken(tmp_path, monkeypatch):
    monkeypatch.setattr(
        developer_sandbox, "resolve_workspace_home", lambda *args, **kwargs: tmp_path / "workspace"
    )

    telemetry = collect_compression_cache_telemetry(tmp_path, "session-none")

    assert telemetry["compressionCount"] == 0
    assert telemetry["savedTokensTotal"] == 0
    assert telemetry["cacheRewrite"]["evidence"] == "missing"
    assert telemetry["replay"]["replayRatio"] == 0.0
    assert telemetry["diagnostics"]["usageRowsScanned"] == 0


@pytest.mark.parametrize(
    ("first_at", "second_at"),
    [
        (_ts(5), _ts(5, minute=8)),  # identical instants
        ("2026-09-21T08:00:05+00:00", "2026-09-21T08:08:05Z"),  # mixed UTC spellings
    ],
)
def test_same_instant_rows_order_before_strictly_later(first_at, second_at):
    events = [_checkpoint(10, first_at, before_tokens=2000, after_tokens=600)]
    rows = [
        _usage_row("u-before", first_at, input_tokens=2000, cached_input_tokens=1900),
        _usage_row("u-after", second_at, input_tokens=700, cached_input_tokens=150),
    ]

    telemetry = build_compression_cache_telemetry(events, rows, session_id="session-a")

    first = telemetry["compressions"][0]
    assert first["cache"]["before"]["eventId"] == "u-before"
    assert first["cache"]["after"]["eventId"] == "u-after"
    assert first["cache"]["cacheHitDropTokens"] == 1900 - 150
