# -*- coding: utf-8 -*-
"""Vibelution-owned LLM usage ledger and Codex-style summary projection."""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from core.infrastructure import developer_sandbox


PROJECT_ROOT = Path(__file__).resolve().parents[2]
USAGE_SCHEMA_VERSION = 2
DEFAULT_LEDGER_TIMEOUT_SECONDS = 5.0
MAX_LOCK_WAIT_SECONDS = 2.0
MAX_WRITE_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 0.02
_INIT_CACHE_MAX_ENTRIES = 128
UsageSource = Literal["provider_usage", "estimated", "missing", "not_called"]
VALID_SOURCES = {"provider_usage", "estimated", "missing", "not_called"}
_VALID_SOURCES_SQL = "('provider_usage','estimated','missing','not_called')"
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

# Per-path process state: schema init cache and writer locks stay bounded so
# long-running backends and test sessions do not grow registries forever.
_schema_ready: OrderedDict[str, None] = OrderedDict()
_write_locks: OrderedDict[str, threading.Lock] = OrderedDict()
_registry_guard = threading.Lock()

_usage_stats: dict[str, Any] = {
    "attempted": 0,
    "persisted": 0,
    "dropped": 0,
    "waitingWriters": 0,
    "maxWaitingWriters": 0,
    "lastFailure": None,
}
_usage_stats_guard = threading.Lock()


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
    cache_usage_observed: bool | None = None
    cache_usage_missing_reason: str = ""


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
    cache_observed_input_tokens: int = 0
    cache_observed_call_count: int = 0
    cache_unobserved_call_count: int = 0

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
            "cacheObservedInputTokens": self.cache_observed_input_tokens,
            "cacheObservedCallCount": self.cache_observed_call_count,
            "cacheUnobservedCallCount": self.cache_unobserved_call_count,
            "cacheUsageObserved": self.cache_observed_call_count > 0,
            "cacheUsageComplete": self.cache_observed_call_count > 0
            and self.cache_unobserved_call_count == 0,
            "cacheUsageMissingReason": (
                "partial_provider_cache_usage"
                if self.cache_observed_call_count > 0 and self.cache_unobserved_call_count > 0
                else "provider_cache_usage_missing"
                if self.cache_unobserved_call_count > 0
                else ""
            ),
            "cacheHitRate": round(self.cached_input_tokens / self.cache_observed_input_tokens, 4)
            if self.cache_observed_input_tokens > 0
            else 0.0,
        }


@dataclass(frozen=True)
class UsageSummary:
    scope: str
    filters: dict[str, str]
    rollup_filters: dict[str, str]
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
            "rollupFilters": dict(self.rollup_filters),
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


def record_usage_event(
    event: UsageLedgerEvent,
    project_root: Path | None = None,
    *,
    timeout_seconds: float = DEFAULT_LEDGER_TIMEOUT_SECONDS,
) -> UsageLedgerEvent:
    normalized = _normalize_event(event)
    path = usage_ledger_path(project_root)
    _bump_usage_stat("attempted")
    lock = _write_lock_for(path)
    with _usage_stats_guard:
        _usage_stats["waitingWriters"] += 1
        _usage_stats["maxWaitingWriters"] = max(
            _usage_stats["maxWaitingWriters"], _usage_stats["waitingWriters"]
        )
    try:
        acquired = lock.acquire(
            timeout=min(MAX_LOCK_WAIT_SECONDS, max(0.0, timeout_seconds))
        )
    finally:
        with _usage_stats_guard:
            _usage_stats["waitingWriters"] = max(
                0, int(_usage_stats["waitingWriters"]) - 1
            )
    if not acquired:
        error = sqlite3.OperationalError(
            "usage ledger writer lock busy; write rejected"
        )
        _record_usage_drop(error)
        raise error
    try:
        last_error: sqlite3.Error | None = None
        for attempt in range(MAX_WRITE_ATTEMPTS):
            connection: sqlite3.Connection | None = None
            try:
                connection = _connect(path, timeout_seconds=timeout_seconds)
                _insert_usage_event(connection, normalized)
                connection.commit()
                _bump_usage_stat("persisted")
                return normalized
            except sqlite3.Error as exc:
                last_error = exc
                time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
            finally:
                if connection is not None:
                    connection.close()
        error = last_error or sqlite3.OperationalError(
            "usage ledger write failed without an error"
        )
        _record_usage_drop(error)
        raise error
    finally:
        lock.release()


def usage_ledger_stats() -> dict[str, Any]:
    """Observed terminal states: attempted/persisted/dropped writes, current
    waiting writers, and the last drop failure reason. No silent undercount."""
    with _usage_stats_guard:
        snapshot = {
            "attempted": int(_usage_stats["attempted"]),
            "persisted": int(_usage_stats["persisted"]),
            "dropped": int(_usage_stats["dropped"]),
            "waitingWriters": int(_usage_stats["waitingWriters"]),
            "maxWaitingWriters": int(_usage_stats["maxWaitingWriters"]),
            "lastFailure": (
                dict(_usage_stats["lastFailure"])
                if isinstance(_usage_stats["lastFailure"], dict)
                else None
            ),
        }
    return snapshot


def _reset_usage_ledger_stats() -> None:
    with _usage_stats_guard:
        _usage_stats["attempted"] = 0
        _usage_stats["persisted"] = 0
        _usage_stats["dropped"] = 0
        _usage_stats["waitingWriters"] = 0
        _usage_stats["maxWaitingWriters"] = 0
        _usage_stats["lastFailure"] = None


def _bump_usage_stat(key: str) -> None:
    with _usage_stats_guard:
        _usage_stats[key] = int(_usage_stats.get(key) or 0) + 1


def _record_usage_drop(error: BaseException) -> None:
    with _usage_stats_guard:
        _usage_stats["dropped"] = int(_usage_stats.get("dropped") or 0) + 1
        _usage_stats["lastFailure"] = {
            "reason": type(error).__name__,
            "at": _utcnow(),
        }


def _write_lock_for(path: Path) -> threading.Lock:
    key = _registry_key(path)
    with _registry_guard:
        lock = _write_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _write_locks[key] = lock
            while len(_write_locks) > _INIT_CACHE_MAX_ENTRIES:
                _write_locks.popitem(last=False)
        return lock


def _registry_key(path: Path) -> str:
    try:
        return str(Path(path).expanduser().resolve())
    except OSError:
        return str(path)


def _insert_usage_event(conn: sqlite3.Connection, normalized: UsageLedgerEvent) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO usage_events (
          event_id, recorded_at, source, scope_kind, session_id, conversation_id,
          turn_id, agent_id, team_id, provider, model, profile_id, transport,
          input_tokens, cached_input_tokens, cache_read_input_tokens,
          cache_creation_input_tokens, uncached_input_tokens, output_tokens,
          reasoning_output_tokens, total_tokens, context_window, latency_ms,
          runtime_scene_id, provider_usage_keys_json, cache_usage_observed,
          cache_usage_missing_reason, usage_schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            1 if normalized.cache_usage_observed else 0,
            normalized.cache_usage_missing_reason,
            USAGE_SCHEMA_VERSION,
        ),
    )


def build_usage_summary(
    scope: str = "global",
    session_id: str = "",
    agent_id: str = "",
    provider: str = "",
    model: str = "",
    project_root: Path | None = None,
) -> dict[str, Any]:
    normalized_scope = str(scope or "global").strip().lower() or "global"
    filters = {
        "sessionId": str(session_id or "").strip(),
        "agentId": str(agent_id or "").strip(),
        "provider": str(provider or "").strip(),
        "model": str(model or "").strip(),
    }
    path = usage_ledger_path(project_root)
    connection = _connect(path)
    try:
        scoped_where, scoped_params = _scope_where(
            normalized_scope,
            session_id=filters["sessionId"],
            agent_id=filters["agentId"],
            provider=filters["provider"],
            model=filters["model"],
        )
        last_row = _query_last_valid_row(connection, scoped_where, scoped_params)
        rollup_filters = _derive_rollup_filters(filters, last_row)
        session_rollup = (
            _rollup_sql(
                connection,
                "session_id=?",
                [rollup_filters["sessionId"]],
                provider=filters["provider"],
                model=filters["model"],
            )[0]
            if rollup_filters["sessionId"]
            else UsageRollup()
        )
        agent_rollup = (
            _rollup_sql(
                connection,
                "agent_id=?",
                [rollup_filters["agentId"]],
                provider=filters["provider"],
                model=filters["model"],
            )[0]
            if rollup_filters["agentId"]
            else UsageRollup()
        )
        global_rollup, skipped_record_count = _rollup_sql(
            connection,
            "",
            [],
            provider=filters["provider"],
            model=filters["model"],
        )
        today_rollup, last7_days_rollup = _time_window_rollups_sql(
            connection,
            provider=filters["provider"],
            model=filters["model"],
        )
        scoped_rollup = (
            global_rollup
            if _scoped_filter_equals_global(normalized_scope, filters)
            else _rollup_sql(
                connection,
                scoped_where,
                scoped_params,
            )[0]
        )
        model_context_window = _latest_context_window_sql(
            connection, scoped_where, scoped_params
        ) or _latest_context_window_sql(connection, "", [], provider=filters["provider"], model=filters["model"])
        summary = UsageSummary(
            scope=normalized_scope,
            filters=filters,
            rollup_filters=rollup_filters,
            last_token_usage=_row_to_last_usage(last_row),
            session_token_usage=session_rollup,
            agent_token_usage=agent_rollup,
            today_token_usage=today_rollup,
            last7_days_token_usage=last7_days_rollup,
            global_token_usage=global_rollup,
            ledger_path=path,
            model_context_window=model_context_window,
            skipped_record_count=skipped_record_count,
        ).to_dict()
        summary["scopeTokenUsage"] = scoped_rollup.to_dict()
        return summary
    finally:
        connection.close()


def _scope_where(
    normalized_scope: str,
    *,
    session_id: str,
    agent_id: str,
    provider: str,
    model: str,
) -> tuple[str, list[str]]:
    clauses: list[str] = []
    parameters: list[str] = []
    if provider:
        clauses.append("provider=?")
        parameters.append(provider)
    if model:
        clauses.append("model=?")
        parameters.append(model)
    if normalized_scope in {"session", "chat_session"} and session_id:
        clauses.append("session_id=?")
        parameters.append(session_id)
    elif normalized_scope == "agent" and agent_id:
        clauses.append("agent_id=?")
        parameters.append(agent_id)
    return " AND ".join(clauses), parameters


def _scoped_filter_equals_global(normalized_scope: str, filters: dict[str, str]) -> bool:
    """The scoped row set is identical to the global row set (provider/model
    filters only), so the aggregate can be reused instead of rescanned."""
    if normalized_scope == "global":
        return True
    if normalized_scope in {"session", "chat_session"}:
        return not filters.get("sessionId")
    if normalized_scope == "agent":
        return not filters.get("agentId")
    return False


def _rollup_where(
    base_clause: str,
    base_params: list[str],
    *,
    provider: str,
    model: str,
) -> tuple[str, list[str]]:
    clauses: list[str] = []
    parameters: list[str] = []
    if base_clause:
        clauses.append(base_clause)
        parameters.extend(base_params)
    if provider:
        clauses.append("provider=?")
        parameters.append(provider)
    if model:
        clauses.append("model=?")
        parameters.append(model)
    where = " AND ".join(clauses)
    return f"WHERE {where}" if where else "", parameters


_ROLLUP_SQL = """
SELECT
  COALESCE(SUM(CASE WHEN source IN {valid} THEN 1 ELSE 0 END), 0) AS call_count,
  COALESCE(SUM(CASE WHEN source='provider_usage' THEN 1 ELSE 0 END), 0) AS observed_call_count,
  COALESCE(SUM(CASE WHEN source='estimated' THEN 1 ELSE 0 END), 0) AS estimated_call_count,
  COALESCE(SUM(CASE WHEN source='missing' THEN 1 ELSE 0 END), 0) AS missing_call_count,
  COALESCE(SUM(CASE WHEN source='not_called' THEN 1 ELSE 0 END), 0) AS not_called_count,
  COALESCE(SUM(CASE WHEN source IN {valid} THEN MAX(0, input_tokens) ELSE 0 END), 0) AS input_tokens,
  COALESCE(SUM(CASE WHEN source IN {valid} AND cache_usage_observed
    THEN MAX(0, cached_input_tokens) ELSE 0 END), 0) AS cached_input_tokens,
  COALESCE(SUM(CASE WHEN source IN {valid} AND cache_usage_observed
    THEN CASE WHEN cache_read_input_tokens > 0 THEN MAX(0, cache_read_input_tokens)
         ELSE MAX(0, cached_input_tokens) END ELSE 0 END), 0) AS cache_read_input_tokens,
  COALESCE(SUM(CASE WHEN source IN {valid} AND cache_usage_observed
    THEN MAX(0, cache_creation_input_tokens) ELSE 0 END), 0) AS cache_creation_input_tokens,
  COALESCE(SUM(CASE WHEN source IN {valid} AND cache_usage_observed
    THEN CASE WHEN uncached_input_tokens > 0 THEN MAX(0, uncached_input_tokens)
         WHEN input_tokens > 0 THEN MAX(0, input_tokens - cached_input_tokens)
         ELSE 0 END ELSE 0 END), 0) AS uncached_input_tokens,
  COALESCE(SUM(CASE WHEN source IN {valid} THEN MAX(0, output_tokens) ELSE 0 END), 0) AS output_tokens,
  COALESCE(SUM(CASE WHEN source IN {valid} THEN MAX(0, reasoning_output_tokens) ELSE 0 END), 0) AS reasoning_output_tokens,
  COALESCE(SUM(CASE WHEN source IN {valid}
    THEN CASE WHEN total_tokens > 0 THEN MAX(0, total_tokens)
         ELSE MAX(0, input_tokens) + MAX(0, output_tokens) END
    ELSE 0 END), 0) AS total_tokens,
  COALESCE(SUM(CASE WHEN source IN {valid} THEN MAX(0, context_window) ELSE 0 END), 0) AS context_window,
  COALESCE(SUM(CASE WHEN source IN {valid} THEN MAX(0, latency_ms) ELSE 0 END), 0) AS latency_ms,
  COALESCE(SUM(CASE WHEN source='provider_usage' AND cache_usage_observed
    THEN MAX(0, input_tokens) ELSE 0 END), 0) AS cache_observed_input_tokens,
  COALESCE(SUM(CASE WHEN source='provider_usage' AND cache_usage_observed THEN 1 ELSE 0 END), 0) AS cache_observed_call_count,
  COALESCE(SUM(CASE WHEN source='provider_usage' AND NOT cache_usage_observed THEN 1 ELSE 0 END), 0) AS cache_unobserved_call_count,
  COALESCE(SUM(CASE WHEN source NOT IN {valid} THEN 1 ELSE 0 END), 0) AS skipped
FROM usage_events
"""


def _rollup_sql(
    connection: sqlite3.Connection,
    base_clause: str,
    base_params: list[str],
    *,
    provider: str = "",
    model: str = "",
) -> tuple[UsageRollup, int]:
    where, parameters = _rollup_where(
        base_clause, base_params, provider=provider, model=model
    )
    row = connection.execute(
        _ROLLUP_SQL.format(valid=_VALID_SOURCES_SQL) + where,
        parameters,
    ).fetchone()
    return _rollup_from_row(row)


def _rollup_from_row(row: sqlite3.Row) -> tuple[UsageRollup, int]:
    if row is None:
        return UsageRollup(), 0
    skipped = int(row["skipped"] or 0)
    return (
        UsageRollup(
            input_tokens=int(row["input_tokens"] or 0),
            cached_input_tokens=int(row["cached_input_tokens"] or 0),
            cache_read_input_tokens=int(row["cache_read_input_tokens"] or 0),
            cache_creation_input_tokens=int(row["cache_creation_input_tokens"] or 0),
            uncached_input_tokens=int(row["uncached_input_tokens"] or 0),
            output_tokens=int(row["output_tokens"] or 0),
            reasoning_output_tokens=int(row["reasoning_output_tokens"] or 0),
            total_tokens=int(row["total_tokens"] or 0),
            call_count=int(row["call_count"] or 0),
            observed_call_count=int(row["observed_call_count"] or 0),
            estimated_call_count=int(row["estimated_call_count"] or 0),
            missing_call_count=int(row["missing_call_count"] or 0),
            not_called_count=int(row["not_called_count"] or 0),
            latency_ms=int(row["latency_ms"] or 0),
            cache_observed_input_tokens=int(row["cache_observed_input_tokens"] or 0),
            cache_observed_call_count=int(row["cache_observed_call_count"] or 0),
            cache_unobserved_call_count=int(row["cache_unobserved_call_count"] or 0),
        ),
        skipped,
    )


def _time_window_rollups_sql(
    connection: sqlite3.Connection,
    *,
    provider: str,
    model: str,
) -> tuple[UsageRollup, UsageRollup]:
    now = datetime.now(timezone.utc)
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    tomorrow_start = today_start + timedelta(days=1)
    last7_start = today_start - timedelta(days=6)
    base = "julianday(replace(recorded_at, 'Z', '+00:00'))"
    today_rollup, _skipped = _rollup_sql(
        connection,
        f"{base} >= julianday(?) AND {base} < julianday(?)",
        [_z(today_start), _z(tomorrow_start)],
        provider=provider,
        model=model,
    )
    last7_rollup, _skipped = _rollup_sql(
        connection,
        f"{base} >= julianday(?) AND {base} < julianday(?)",
        [_z(last7_start), _z(tomorrow_start)],
        provider=provider,
        model=model,
    )
    return today_rollup, last7_rollup


def _z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _query_last_valid_row(
    connection: sqlite3.Connection,
    where: str,
    parameters: list[str],
) -> sqlite3.Row | None:
    clauses: list[str] = []
    if where:
        clauses.append(where)
    clauses.append(f"source IN {_VALID_SOURCES_SQL}")
    combined = "WHERE " + " AND ".join(clauses)
    return connection.execute(
        "SELECT * FROM usage_events "
        + combined
        + " ORDER BY recorded_at DESC, rowid DESC LIMIT 1",
        parameters,
    ).fetchone()


def _latest_context_window_sql(
    connection: sqlite3.Connection,
    where: str,
    parameters: list[str],
    *,
    provider: str = "",
    model: str = "",
) -> int:
    conditions: list[str] = []
    params: list[str] = []
    if where:
        conditions.append(where)
        params.extend(parameters)
    if provider:
        conditions.append("provider=?")
        params.append(provider)
    if model:
        conditions.append("model=?")
        params.append(model)
    conditions.append(f"source IN {_VALID_SOURCES_SQL}")
    conditions.append("context_window > 0")
    sql = (
        "SELECT context_window FROM usage_events WHERE "
        + " AND ".join(conditions)
    )
    row = connection.execute(
        sql + " ORDER BY recorded_at DESC, rowid DESC LIMIT 1",
        params,
    ).fetchone()
    if row is None:
        return 0
    return _coerce_nonnegative_int(row["context_window"])


def _connect(
    path: Path,
    *,
    timeout_seconds: float = DEFAULT_LEDGER_TIMEOUT_SECONDS,
) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    timeout = _coerce_nonnegative_float(timeout_seconds, default=DEFAULT_LEDGER_TIMEOUT_SECONDS)
    conn = sqlite3.connect(str(path), timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
    _ensure_schema_once(conn, path)
    return conn


def _ensure_schema_once(conn: sqlite3.Connection, path: Path) -> None:
    """Run schema DDL and the one-time history migration only once per
    process per ledger path; the hot write/summary paths never re-run it."""
    key = _registry_key(path)
    with _registry_guard:
        if key in _schema_ready:
            return
    _ensure_schema(conn)
    with _registry_guard:
        _schema_ready[key] = None
        while len(_schema_ready) > _INIT_CACHE_MAX_ENTRIES:
            _schema_ready.popitem(last=False)


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
          cache_usage_observed INTEGER NOT NULL DEFAULT 0,
          cache_usage_missing_reason TEXT NOT NULL DEFAULT '',
          usage_schema_version INTEGER NOT NULL DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_usage_events_recorded_at ON usage_events(recorded_at);
        CREATE INDEX IF NOT EXISTS idx_usage_events_session_provider_model ON usage_events(session_id, provider, model);
        CREATE INDEX IF NOT EXISTS idx_usage_events_agent_provider_model ON usage_events(agent_id, provider, model);
        CREATE INDEX IF NOT EXISTS idx_usage_events_provider_model ON usage_events(provider, model);
        CREATE INDEX IF NOT EXISTS idx_usage_events_provider_model_recorded ON usage_events(provider, model, recorded_at);
        CREATE INDEX IF NOT EXISTS idx_usage_events_recorded_julianday ON usage_events(julianday(replace(recorded_at, 'Z', '+00:00')));
        """
    )
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(usage_events)")}
    if "cache_usage_observed" not in columns:
        try:
            conn.execute(
                "ALTER TABLE usage_events ADD COLUMN cache_usage_observed INTEGER NOT NULL DEFAULT 0"
            )
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
    if "cache_usage_missing_reason" not in columns:
        try:
            conn.execute(
                "ALTER TABLE usage_events ADD COLUMN cache_usage_missing_reason TEXT NOT NULL DEFAULT ''"
            )
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
    conn.execute(
        """
        UPDATE usage_events
        SET cache_usage_observed = 1
        WHERE cache_usage_observed = 0
          AND (
            cached_input_tokens > 0
            OR cache_read_input_tokens > 0
            OR cache_creation_input_tokens > 0
          )
        """
    )
    conn.commit()


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
    cache_usage_observed = event.cache_usage_observed
    if cache_usage_observed is None:
        cache_usage_observed = any(
            updates[field_name] > 0
            for field_name in (
                "cached_input_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            )
        )
    updates["cache_usage_observed"] = bool(cache_usage_observed)
    missing_reason = _safe_text(event.cache_usage_missing_reason)
    if not cache_usage_observed and not missing_reason and updates["source"] == "provider_usage":
        missing_reason = "provider_cache_usage_missing"
    updates["cache_usage_missing_reason"] = missing_reason if not cache_usage_observed else ""
    return replace(event, **updates)


def _derive_rollup_filters(filters: dict[str, str], last_row: sqlite3.Row | None) -> dict[str, str]:
    rollup_filters = {
        "sessionId": str(filters.get("sessionId") or "").strip(),
        "agentId": str(filters.get("agentId") or "").strip(),
    }
    if last_row is None:
        return rollup_filters
    if not rollup_filters["sessionId"]:
        rollup_filters["sessionId"] = str(last_row["session_id"] or "").strip()
    if not rollup_filters["agentId"]:
        rollup_filters["agentId"] = str(last_row["agent_id"] or "").strip()
    return rollup_filters


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
            "cacheUsageObserved": False,
            "cacheUsageMissingReason": "not_called",
        }
    input_tokens = _coerce_nonnegative_int(row["input_tokens"])
    cache_usage_observed = bool(_coerce_nonnegative_int(row["cache_usage_observed"]))
    cached_tokens = _coerce_nonnegative_int(row["cached_input_tokens"]) if cache_usage_observed else 0
    cache_read_tokens = (
        _coerce_nonnegative_int(row["cache_read_input_tokens"]) or cached_tokens
    ) if cache_usage_observed else 0
    output_tokens = _coerce_nonnegative_int(row["output_tokens"])
    total_tokens = _coerce_nonnegative_int(row["total_tokens"]) or (input_tokens + output_tokens)
    uncached_tokens = _coerce_nonnegative_int(row["uncached_input_tokens"]) if cache_usage_observed else 0
    if cache_usage_observed and input_tokens and not uncached_tokens:
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
        "cacheCreationInputTokens": (
            _coerce_nonnegative_int(row["cache_creation_input_tokens"])
            if cache_usage_observed
            else 0
        ),
        "uncachedInputTokens": uncached_tokens,
        "outputTokens": output_tokens,
        "reasoningOutputTokens": _coerce_nonnegative_int(row["reasoning_output_tokens"]),
        "totalTokens": total_tokens,
        "contextWindow": _coerce_nonnegative_int(row["context_window"]),
        "latencyMs": _coerce_nonnegative_int(row["latency_ms"]),
        "runtimeSceneId": str(row["runtime_scene_id"] or ""),
        "providerUsageKeys": _provider_usage_keys_from_row(row),
        "cacheUsageObserved": cache_usage_observed,
        "cacheUsageMissingReason": (
            str(row["cache_usage_missing_reason"] or "").strip()
            or ("provider_cache_usage_missing" if not cache_usage_observed else "")
        ),
        "cacheHitRate": round(cached_tokens / input_tokens, 4)
        if cache_usage_observed and input_tokens > 0
        else 0.0,
    }


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


def _coerce_nonnegative_float(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, parsed)


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
