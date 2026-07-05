# -*- coding: utf-8 -*-
"""Vibelution-owned LLM usage ledger and Codex-style summary projection."""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from core.infrastructure import developer_sandbox


PROJECT_ROOT = Path(__file__).resolve().parents[2]
USAGE_SCHEMA_VERSION = 1
UsageSource = Literal["provider_usage", "estimated", "missing", "not_called"]
VALID_SOURCES = {"provider_usage", "estimated", "missing", "not_called"}
NUMERIC_EVENT_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "uncached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
    "context_window",
    "latency_ms",
)


@dataclass(frozen=True)
class UsageLedgerEvent:
    recorded_at: str = ""
    source: UsageSource = "missing"
    scope_kind: str = "unknown"
    event_id: str = ""
    session_id: str = ""
    conversation_id: str = ""
    turn_id: str = ""
    agent_id: str = ""
    team_id: str = ""
    provider: str = ""
    model: str = ""
    profile_id: str = ""
    transport: str = ""
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    uncached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0
    context_window: int = 0
    latency_ms: int = 0
    runtime_scene_id: str = ""
    provider_usage_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class UsageRollup:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    uncached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0
    observed_call_count: int = 0
    estimated_call_count: int = 0
    missing_call_count: int = 0
    not_called_count: int = 0
    latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "inputTokens": self.input_tokens,
            "cachedInputTokens": self.cached_input_tokens,
            "cacheReadInputTokens": self.cache_read_input_tokens,
            "cacheCreationInputTokens": self.cache_creation_input_tokens,
            "uncachedInputTokens": self.uncached_input_tokens,
            "outputTokens": self.output_tokens,
            "reasoningOutputTokens": self.reasoning_output_tokens,
            "totalTokens": self.total_tokens,
            "callCount": self.call_count,
            "observedCallCount": self.observed_call_count,
            "estimatedCallCount": self.estimated_call_count,
            "missingCallCount": self.missing_call_count,
            "notCalledCount": self.not_called_count,
            "latencyMs": self.latency_ms,
            "cacheHitRate": round(self.cached_input_tokens / self.input_tokens, 4)
            if self.input_tokens > 0
            else 0.0,
        }


@dataclass(frozen=True)
class UsageSummary:
    scope: str
    filters: dict[str, str]
    last_token_usage: dict[str, Any]
    session_token_usage: UsageRollup
    agent_token_usage: UsageRollup
    today_token_usage: UsageRollup
    last7_days_token_usage: UsageRollup
    global_token_usage: UsageRollup
    ledger_path: Path
    model_context_window: int = 0
    skipped_record_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "filters": dict(self.filters),
            "lastTokenUsage": dict(self.last_token_usage),
            "sessionTokenUsage": self.session_token_usage.to_dict(),
            "agentTokenUsage": self.agent_token_usage.to_dict(),
            "globalTokenUsage": {
                "today": self.today_token_usage.to_dict(),
                "last7Days": self.last7_days_token_usage.to_dict(),
                "allTime": self.global_token_usage.to_dict(),
            },
            "modelContextWindow": self.model_context_window,
            "diagnostics": {
                "source": "usage_ledger",
                "skippedRecordCount": self.skipped_record_count,
                "ledgerPath": self.ledger_path.as_posix(),
                "schemaVersion": USAGE_SCHEMA_VERSION,
            },
        }


def usage_ledger_path(project_root: Path | None = None) -> Path:
    return developer_sandbox.route_workspace_path(
        (project_root or PROJECT_ROOT),
        "usage",
        "usage",
        "usage_ledger.sqlite3",
        intent="state",
        seed=True,
    )


def record_usage_event(event: UsageLedgerEvent, project_root: Path | None = None) -> UsageLedgerEvent:
    normalized = _normalize_event(event)
    with _connect(project_root) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO usage_events (
              event_id, recorded_at, source, scope_kind, session_id, conversation_id,
              turn_id, agent_id, team_id, provider, model, profile_id, transport,
              input_tokens, cached_input_tokens, cache_read_input_tokens,
              cache_creation_input_tokens, uncached_input_tokens, output_tokens,
              reasoning_output_tokens, total_tokens, context_window, latency_ms,
              runtime_scene_id, provider_usage_keys_json, usage_schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized.event_id,
                normalized.recorded_at,
                str(normalized.source or "missing"),
                normalized.scope_kind,
                normalized.session_id,
                normalized.conversation_id,
                normalized.turn_id,
                normalized.agent_id,
                normalized.team_id,
                normalized.provider,
                normalized.model,
                normalized.profile_id,
                normalized.transport,
                normalized.input_tokens,
                normalized.cached_input_tokens,
                normalized.cache_read_input_tokens,
                normalized.cache_creation_input_tokens,
                normalized.uncached_input_tokens,
                normalized.output_tokens,
                normalized.reasoning_output_tokens,
                normalized.total_tokens,
                normalized.context_window,
                normalized.latency_ms,
                normalized.runtime_scene_id,
                json.dumps(normalized.provider_usage_keys, ensure_ascii=False),
                USAGE_SCHEMA_VERSION,
            ),
        )
        conn.commit()
    return normalized


def build_usage_summary(
    scope: str = "global",
    session_id: str = "",
    agent_id: str = "",
    provider: str = "",
    model: str = "",
    project_root: Path | None = None,
) -> dict[str, Any]:
    rows = _read_rows(project_root)
    normalized_scope = str(scope or "global").strip().lower() or "global"
    filters = {
        "sessionId": str(session_id or "").strip(),
        "agentId": str(agent_id or "").strip(),
        "provider": str(provider or "").strip(),
        "model": str(model or "").strip(),
    }
    scoped_rows = _filter_rows(
        rows,
        normalized_scope,
        session_id=filters["sessionId"],
        agent_id=filters["agentId"],
        provider=filters["provider"],
        model=filters["model"],
    )
    session_rows = _filter_rows(
        rows,
        "session",
        session_id=filters["sessionId"],
        provider=filters["provider"],
        model=filters["model"],
    )
    agent_rows = _filter_rows(
        rows,
        "agent",
        agent_id=filters["agentId"],
        provider=filters["provider"],
        model=filters["model"],
    )
    global_rows = _filter_rows(rows, "global", provider=filters["provider"], model=filters["model"])
    today_rows, last7_days_rows = _time_window_rows(global_rows)
    global_rollup, skipped_record_count = _rollup_rows(global_rows)
    today_rollup, _ = _rollup_rows(today_rows)
    last7_days_rollup, _ = _rollup_rows(last7_days_rows)
    session_rollup, _ = _rollup_rows(session_rows)
    agent_rollup, _ = _rollup_rows(agent_rows)
    scoped_rollup, _ = _rollup_rows(scoped_rows)
    last_row = _last_valid_row(scoped_rows)
    summary = UsageSummary(
        scope=normalized_scope,
        filters=filters,
        last_token_usage=_row_to_last_usage(last_row),
        session_token_usage=session_rollup,
        agent_token_usage=agent_rollup,
        today_token_usage=today_rollup,
        last7_days_token_usage=last7_days_rollup,
        global_token_usage=global_rollup,
        ledger_path=usage_ledger_path(project_root),
        model_context_window=_latest_context_window(scoped_rows) or _latest_context_window(global_rows),
        skipped_record_count=skipped_record_count,
    ).to_dict()
    summary["scopeTokenUsage"] = scoped_rollup.to_dict()
    return summary


def _connect(project_root: Path | None = None) -> sqlite3.Connection:
    path = usage_ledger_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS usage_events (
          event_id TEXT PRIMARY KEY,
          recorded_at TEXT NOT NULL,
          source TEXT NOT NULL,
          scope_kind TEXT NOT NULL,
          session_id TEXT NOT NULL DEFAULT '',
          conversation_id TEXT NOT NULL DEFAULT '',
          turn_id TEXT NOT NULL DEFAULT '',
          agent_id TEXT NOT NULL DEFAULT '',
          team_id TEXT NOT NULL DEFAULT '',
          provider TEXT NOT NULL DEFAULT '',
          model TEXT NOT NULL DEFAULT '',
          profile_id TEXT NOT NULL DEFAULT '',
          transport TEXT NOT NULL DEFAULT '',
          input_tokens INTEGER NOT NULL DEFAULT 0,
          cached_input_tokens INTEGER NOT NULL DEFAULT 0,
          cache_read_input_tokens INTEGER NOT NULL DEFAULT 0,
          cache_creation_input_tokens INTEGER NOT NULL DEFAULT 0,
          uncached_input_tokens INTEGER NOT NULL DEFAULT 0,
          output_tokens INTEGER NOT NULL DEFAULT 0,
          reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
          total_tokens INTEGER NOT NULL DEFAULT 0,
          context_window INTEGER NOT NULL DEFAULT 0,
          latency_ms INTEGER NOT NULL DEFAULT 0,
          runtime_scene_id TEXT NOT NULL DEFAULT '',
          provider_usage_keys_json TEXT NOT NULL DEFAULT '[]',
          usage_schema_version INTEGER NOT NULL DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_usage_events_recorded_at ON usage_events(recorded_at);
        CREATE INDEX IF NOT EXISTS idx_usage_events_session_id ON usage_events(session_id);
        CREATE INDEX IF NOT EXISTS idx_usage_events_agent_id ON usage_events(agent_id);
        CREATE INDEX IF NOT EXISTS idx_usage_events_provider_model ON usage_events(provider, model);
        """
    )
    conn.commit()


def _read_rows(project_root: Path | None = None) -> list[sqlite3.Row]:
    with _connect(project_root) as conn:
        cursor = conn.execute("SELECT rowid AS _rowid, * FROM usage_events ORDER BY recorded_at ASC, rowid ASC")
        return list(cursor.fetchall())


def _normalize_event(event: UsageLedgerEvent) -> UsageLedgerEvent:
    now = _utcnow()
    event_id = str(event.event_id or "").strip()
    if not event_id:
        event_id = f"usage-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(6)}"
    updates: dict[str, Any] = {
        "event_id": event_id,
        "recorded_at": str(event.recorded_at or now).strip() or now,
        "source": str(event.source or "missing").strip() or "missing",
        "scope_kind": _safe_text(event.scope_kind, default="unknown"),
        "session_id": _safe_text(event.session_id),
        "conversation_id": _safe_text(event.conversation_id),
        "turn_id": _safe_text(event.turn_id),
        "agent_id": _safe_text(event.agent_id),
        "team_id": _safe_text(event.team_id),
        "provider": _safe_text(event.provider),
        "model": _safe_text(event.model),
        "profile_id": _safe_text(event.profile_id),
        "transport": _safe_text(event.transport),
        "runtime_scene_id": _safe_text(event.runtime_scene_id),
        "provider_usage_keys": _sanitize_provider_usage_keys(event.provider_usage_keys),
    }
    for field_name in NUMERIC_EVENT_FIELDS:
        updates[field_name] = _coerce_nonnegative_int(getattr(event, field_name, 0))
    return replace(event, **updates)


def _rollup_rows(rows: list[sqlite3.Row]) -> tuple[UsageRollup, int]:
    skipped = 0
    totals = {field_name: 0 for field_name in NUMERIC_EVENT_FIELDS}
    counts = {
        "call_count": 0,
        "observed_call_count": 0,
        "estimated_call_count": 0,
        "missing_call_count": 0,
        "not_called_count": 0,
    }
    for row in rows:
        source = str(row["source"] or "")
        if source not in VALID_SOURCES:
            skipped += 1
            continue
        input_tokens = _coerce_nonnegative_int(row["input_tokens"])
        output_tokens = _coerce_nonnegative_int(row["output_tokens"])
        total_tokens = _coerce_nonnegative_int(row["total_tokens"]) or (input_tokens + output_tokens)
        cached_tokens = _coerce_nonnegative_int(row["cached_input_tokens"])
        cache_read_tokens = _coerce_nonnegative_int(row["cache_read_input_tokens"]) or cached_tokens
        uncached_tokens = _coerce_nonnegative_int(row["uncached_input_tokens"])
        if input_tokens and not uncached_tokens:
            uncached_tokens = max(0, input_tokens - cached_tokens)
        totals["input_tokens"] += input_tokens
        totals["cached_input_tokens"] += cached_tokens
        totals["cache_read_input_tokens"] += cache_read_tokens
        totals["cache_creation_input_tokens"] += _coerce_nonnegative_int(row["cache_creation_input_tokens"])
        totals["uncached_input_tokens"] += uncached_tokens
        totals["output_tokens"] += output_tokens
        totals["reasoning_output_tokens"] += _coerce_nonnegative_int(row["reasoning_output_tokens"])
        totals["total_tokens"] += total_tokens
        totals["context_window"] += _coerce_nonnegative_int(row["context_window"])
        totals["latency_ms"] += _coerce_nonnegative_int(row["latency_ms"])
        counts["call_count"] += 1
        if source == "provider_usage":
            counts["observed_call_count"] += 1
        elif source == "estimated":
            counts["estimated_call_count"] += 1
        elif source == "missing":
            counts["missing_call_count"] += 1
        elif source == "not_called":
            counts["not_called_count"] += 1
    return (
        UsageRollup(
            input_tokens=totals["input_tokens"],
            cached_input_tokens=totals["cached_input_tokens"],
            cache_read_input_tokens=totals["cache_read_input_tokens"],
            cache_creation_input_tokens=totals["cache_creation_input_tokens"],
            uncached_input_tokens=totals["uncached_input_tokens"],
            output_tokens=totals["output_tokens"],
            reasoning_output_tokens=totals["reasoning_output_tokens"],
            total_tokens=totals["total_tokens"],
            call_count=counts["call_count"],
            observed_call_count=counts["observed_call_count"],
            estimated_call_count=counts["estimated_call_count"],
            missing_call_count=counts["missing_call_count"],
            not_called_count=counts["not_called_count"],
            latency_ms=totals["latency_ms"],
        ),
        skipped,
    )


def _filter_rows(
    rows: list[sqlite3.Row],
    scope: str,
    *,
    session_id: str = "",
    agent_id: str = "",
    provider: str = "",
    model: str = "",
) -> list[sqlite3.Row]:
    normalized_scope = str(scope or "global").strip().lower()
    filtered: list[sqlite3.Row] = []
    for row in rows:
        if provider and str(row["provider"] or "") != provider:
            continue
        if model and str(row["model"] or "") != model:
            continue
        if normalized_scope in {"session", "chat_session"} and session_id and str(row["session_id"] or "") != session_id:
            continue
        if normalized_scope == "agent" and agent_id and str(row["agent_id"] or "") != agent_id:
            continue
        filtered.append(row)
    return filtered


def _time_window_rows(rows: list[sqlite3.Row]) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    now = datetime.now(timezone.utc)
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    tomorrow_start = today_start + timedelta(days=1)
    last7_start = today_start - timedelta(days=6)
    today_rows: list[sqlite3.Row] = []
    last7_days_rows: list[sqlite3.Row] = []
    for row in rows:
        recorded_at = _parse_recorded_at(row["recorded_at"])
        if recorded_at is None:
            continue
        if today_start <= recorded_at < tomorrow_start:
            today_rows.append(row)
        if last7_start <= recorded_at < tomorrow_start:
            last7_days_rows.append(row)
    return today_rows, last7_days_rows


def _parse_recorded_at(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _last_valid_row(rows: list[sqlite3.Row]) -> sqlite3.Row | None:
    for row in reversed(rows):
        if str(row["source"] or "") in VALID_SOURCES:
            return row
    return None


def _row_to_last_usage(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {
            "source": "not_called",
            "inputTokens": 0,
            "cachedInputTokens": 0,
            "cacheReadInputTokens": 0,
            "cacheCreationInputTokens": 0,
            "uncachedInputTokens": 0,
            "outputTokens": 0,
            "reasoningOutputTokens": 0,
            "totalTokens": 0,
            "cacheHitRate": 0.0,
        }
    input_tokens = _coerce_nonnegative_int(row["input_tokens"])
    cached_tokens = _coerce_nonnegative_int(row["cached_input_tokens"])
    cache_read_tokens = _coerce_nonnegative_int(row["cache_read_input_tokens"]) or cached_tokens
    output_tokens = _coerce_nonnegative_int(row["output_tokens"])
    total_tokens = _coerce_nonnegative_int(row["total_tokens"]) or (input_tokens + output_tokens)
    uncached_tokens = _coerce_nonnegative_int(row["uncached_input_tokens"])
    if input_tokens and not uncached_tokens:
        uncached_tokens = max(0, input_tokens - cached_tokens)
    return {
        "eventId": str(row["event_id"] or ""),
        "recordedAt": str(row["recorded_at"] or ""),
        "source": str(row["source"] or "missing"),
        "scopeKind": str(row["scope_kind"] or ""),
        "sessionId": str(row["session_id"] or ""),
        "conversationId": str(row["conversation_id"] or ""),
        "turnId": str(row["turn_id"] or ""),
        "agentId": str(row["agent_id"] or ""),
        "teamId": str(row["team_id"] or ""),
        "provider": str(row["provider"] or ""),
        "model": str(row["model"] or ""),
        "profileId": str(row["profile_id"] or ""),
        "transport": str(row["transport"] or ""),
        "inputTokens": input_tokens,
        "cachedInputTokens": cached_tokens,
        "cacheReadInputTokens": cache_read_tokens,
        "cacheCreationInputTokens": _coerce_nonnegative_int(row["cache_creation_input_tokens"]),
        "uncachedInputTokens": uncached_tokens,
        "outputTokens": output_tokens,
        "reasoningOutputTokens": _coerce_nonnegative_int(row["reasoning_output_tokens"]),
        "totalTokens": total_tokens,
        "contextWindow": _coerce_nonnegative_int(row["context_window"]),
        "latencyMs": _coerce_nonnegative_int(row["latency_ms"]),
        "runtimeSceneId": str(row["runtime_scene_id"] or ""),
        "providerUsageKeys": _provider_usage_keys_from_row(row),
        "cacheHitRate": round(cached_tokens / input_tokens, 4) if input_tokens > 0 else 0.0,
    }


def _latest_context_window(rows: list[sqlite3.Row]) -> int:
    for row in reversed(rows):
        if str(row["source"] or "") not in VALID_SOURCES:
            continue
        context_window = _coerce_nonnegative_int(row["context_window"])
        if context_window:
            return context_window
    return 0


def _provider_usage_keys_from_row(row: sqlite3.Row) -> list[str]:
    try:
        payload = json.loads(str(row["provider_usage_keys_json"] or "[]"))
    except json.JSONDecodeError:
        return []
    return _sanitize_provider_usage_keys(payload if isinstance(payload, list) else [])


def _sanitize_provider_usage_keys(keys: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for key in keys:
        value = str(key or "").strip()
        if not value or "\n" in value or "\r" in value or len(value) > 128:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _safe_text(value: Any, *, default: str = "") -> str:
    text = str(value or "").strip()
    return text if text else default


def _coerce_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
