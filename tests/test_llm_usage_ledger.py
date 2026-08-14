from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from core.infrastructure import developer_sandbox
from core.llm.usage import usage_stats_from_payload
from core.llm.usage_ledger import (
    UsageLedgerEvent,
    build_usage_summary,
    record_usage_event,
    usage_ledger_path,
)


@pytest.fixture(autouse=True)
def isolate_usage_ledger_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(developer_sandbox, "resolve_workspace_home", lambda *args, **kwargs: tmp_path / "workspace")


def iso_at(days: int = 0) -> str:
    return (
        (datetime.now(timezone.utc) + timedelta(days=days))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def test_usage_stats_reads_reasoning_output_tokens():
    stats = usage_stats_from_payload(
        {
            "prompt_tokens": 100,
            "completion_tokens": 40,
            "total_tokens": 140,
            "completion_tokens_details": {"reasoning_tokens": 17},
            "prompt_tokens_details": {"cached_tokens": 25},
        }
    )

    assert stats.input_tokens == 100
    assert stats.output_tokens == 40
    assert stats.total_tokens == 140
    assert stats.cached_input_tokens == 25
    assert stats.reasoning_output_tokens == 17


def test_usage_ledger_records_provider_usage_and_rolls_up(tmp_path, monkeypatch):
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)

    record_usage_event(
        UsageLedgerEvent(
            recorded_at=iso_at(),
            source="provider_usage",
            scope_kind="chat_session",
            session_id="session-a",
            turn_id="turn-1",
            agent_id="agent-a",
            provider="openai",
            model="gpt-5",
            profile_id="primary",
            input_tokens=100,
            cached_input_tokens=40,
            cache_read_input_tokens=40,
            cache_creation_input_tokens=10,
            uncached_input_tokens=60,
            output_tokens=30,
            reasoning_output_tokens=7,
            total_tokens=130,
            context_window=128000,
            latency_ms=250,
            provider_usage_keys=["prompt_tokens", "completion_tokens", "total_tokens"],
            cache_usage_observed=True,
        )
    )
    record_usage_event(
        UsageLedgerEvent(
            recorded_at=iso_at(),
            source="estimated",
            scope_kind="chat_session",
            session_id="session-a",
            turn_id="turn-2",
            provider="openai",
            model="gpt-5",
            input_tokens=20,
            output_tokens=5,
            total_tokens=25,
        )
    )

    summary = build_usage_summary(scope="session", session_id="session-a")

    assert summary["lastTokenUsage"]["source"] == "estimated"
    assert summary["lastTokenUsage"]["totalTokens"] == 25
    assert summary["sessionTokenUsage"]["inputTokens"] == 120
    assert summary["sessionTokenUsage"]["cachedInputTokens"] == 40
    assert summary["sessionTokenUsage"]["uncachedInputTokens"] == 60
    assert summary["sessionTokenUsage"]["cacheObservedInputTokens"] == 100
    assert summary["sessionTokenUsage"]["outputTokens"] == 35
    assert summary["sessionTokenUsage"]["reasoningOutputTokens"] == 7
    assert summary["sessionTokenUsage"]["totalTokens"] == 155
    assert summary["sessionTokenUsage"]["observedCallCount"] == 1
    assert summary["sessionTokenUsage"]["estimatedCallCount"] == 1
    assert summary["globalTokenUsage"]["today"]["totalTokens"] == 155
    assert summary["globalTokenUsage"]["last7Days"]["totalTokens"] == 155
    assert summary["globalTokenUsage"]["allTime"]["totalTokens"] == 155
    assert summary["modelContextWindow"] == 128000
    assert summary["diagnostics"]["source"] == "usage_ledger"
    assert summary["diagnostics"]["ledgerPath"].endswith("/workspace/usage/usage_ledger.sqlite3")


def test_usage_ledger_excludes_unobserved_cache_samples_from_hit_rate(tmp_path, monkeypatch):
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
    record_usage_event(
        UsageLedgerEvent(
            recorded_at=iso_at(-2),
            source="provider_usage",
            input_tokens=100,
            output_tokens=10,
            total_tokens=110,
            cache_usage_observed=False,
            cache_usage_missing_reason="provider_cache_usage_missing",
        )
    )
    record_usage_event(
        UsageLedgerEvent(
            recorded_at=iso_at(-1),
            source="provider_usage",
            input_tokens=200,
            uncached_input_tokens=200,
            total_tokens=200,
            cache_usage_observed=True,
        )
    )
    record_usage_event(
        UsageLedgerEvent(
            recorded_at=iso_at(),
            source="provider_usage",
            input_tokens=100,
            cached_input_tokens=50,
            cache_read_input_tokens=50,
            uncached_input_tokens=50,
            total_tokens=100,
            cache_usage_observed=True,
        )
    )

    summary = build_usage_summary()
    usage = summary["globalTokenUsage"]["allTime"]

    assert usage["inputTokens"] == 400
    assert usage["cacheObservedInputTokens"] == 300
    assert usage["cachedInputTokens"] == 50
    assert usage["uncachedInputTokens"] == 250
    assert usage["cacheObservedCallCount"] == 2
    assert usage["cacheUnobservedCallCount"] == 1
    assert usage["cacheHitRate"] == pytest.approx(0.1667)


def test_usage_ledger_rolls_up_today_last7_days_and_all_time(tmp_path, monkeypatch):
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
    for recorded_at, total_tokens in (
        (iso_at(-8), 40),
        (iso_at(-6), 30),
        (iso_at(-1), 20),
        (iso_at(), 10),
        (iso_at(1), 50),
    ):
        record_usage_event(
            UsageLedgerEvent(
                recorded_at=recorded_at,
                source="provider_usage",
                scope_kind="unknown",
                input_tokens=total_tokens,
                total_tokens=total_tokens,
            )
        )

    summary = build_usage_summary()

    assert summary["globalTokenUsage"]["today"]["totalTokens"] == 10
    assert summary["globalTokenUsage"]["last7Days"]["totalTokens"] == 60
    assert summary["globalTokenUsage"]["allTime"]["totalTokens"] == 150


def test_global_summary_uses_latest_session_and_agent_rollups(tmp_path, monkeypatch):
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
    record_usage_event(
        UsageLedgerEvent(
            recorded_at=iso_at(-1),
            source="provider_usage",
            session_id="session-old",
            agent_id="agent-old",
            provider="openai",
            model="gpt-5",
            input_tokens=100,
            total_tokens=100,
        )
    )
    record_usage_event(
        UsageLedgerEvent(
            recorded_at=iso_at(),
            source="provider_usage",
            session_id="session-latest",
            agent_id="agent-latest",
            provider="openai",
            model="gpt-5",
            input_tokens=30,
            total_tokens=30,
        )
    )

    summary = build_usage_summary()

    assert summary["globalTokenUsage"]["allTime"]["totalTokens"] == 130
    assert summary["lastTokenUsage"]["sessionId"] == "session-latest"
    assert summary["lastTokenUsage"]["agentId"] == "agent-latest"
    assert summary["sessionTokenUsage"]["totalTokens"] == 30
    assert summary["agentTokenUsage"]["totalTokens"] == 30
    assert summary["rollupFilters"]["sessionId"] == "session-latest"
    assert summary["rollupFilters"]["agentId"] == "agent-latest"


def test_usage_ledger_skips_invalid_source_rows_in_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
    path = usage_ledger_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record_usage_event(
        UsageLedgerEvent(
            recorded_at=iso_at(),
            source="provider_usage",
            scope_kind="unknown",
            input_tokens=1,
            output_tokens=2,
            total_tokens=3,
        )
    )
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            "INSERT INTO usage_events(event_id, recorded_at, source, scope_kind, input_tokens, output_tokens, total_tokens, provider_usage_keys_json, usage_schema_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("bad-source", iso_at(), "alien", "unknown", 999, 999, 1998, json.dumps([]), 1),
        )
        conn.commit()

    summary = build_usage_summary()

    assert summary["globalTokenUsage"]["allTime"]["totalTokens"] == 3
    assert summary["diagnostics"]["source"] == "usage_ledger"
    assert summary["diagnostics"]["skippedRecordCount"] == 1
    assert summary["diagnostics"]["ledgerPath"].endswith("/workspace/usage/usage_ledger.sqlite3")


def test_usage_ledger_uses_developer_sandbox_routing(tmp_path, monkeypatch):
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("core.infrastructure.developer_sandbox.is_developer_mode_enabled", lambda **_kwargs: True)
    monkeypatch.setattr(
        "core.infrastructure.developer_sandbox.sandbox_root",
        lambda *_args, **_kwargs: tmp_path / ".runtime" / "developer-mode" / "sandboxes" / "dev-1",
    )

    path = usage_ledger_path(tmp_path)

    assert path.as_posix().endswith(
        "/.runtime/developer-mode/sandboxes/dev-1/workspace/usage/usage_ledger.sqlite3"
    )


# ---------------------------------------------------------------------------
# 并发落盘 / 初始化热路径 / SQL 聚合 / 连接关闭 / 统计观测


def _seed_rows(path, rows):
    from core.llm import usage_ledger

    connection = sqlite3.connect(str(path))
    try:
        usage_ledger._ensure_schema(connection)
        connection.executemany(
            """
            INSERT INTO usage_events (
              event_id, recorded_at, source, scope_kind, session_id, conversation_id,
              turn_id, agent_id, team_id, provider, model, profile_id, transport,
              input_tokens, cached_input_tokens, cache_read_input_tokens,
              cache_creation_input_tokens, uncached_input_tokens, output_tokens,
              reasoning_output_tokens, total_tokens, context_window, latency_ms,
              runtime_scene_id, provider_usage_keys_json, cache_usage_observed,
              cache_usage_missing_reason, usage_schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.commit()
    finally:
        connection.close()


def _make_seed_row(index: int):
    return (
        f"event-{index:05d}",
        iso_at(days=-(index % 9)),
        ["provider_usage", "estimated", "missing", "not_called"][index % 4],
        "chat_session",
        f"session-{index % 7}",
        f"conversation-{index % 3}",
        f"turn-{index}",
        f"agent-{index % 5}",
        f"team-{index % 2}",
        f"provider-{index % 3}",
        f"model-{index % 2}",
        f"profile-{index % 4}",
        "responses",
        10 + index % 50,
        3 + index % 8,
        3 + index % 8,
        1 + index % 4,
        7 + index % 40,
        5 + index % 30,
        2 + index % 6,
        20 + index % 80,
        4096 + index % 512,
        index % 97,
        f"scene-{index}",
        "[]",
        1 if index % 3 else 0,
        "",
        2,
    )


def test_32_concurrent_writes_all_persist(tmp_path, monkeypatch):
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
    import threading

    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            record_usage_event(
                UsageLedgerEvent(
                    recorded_at=iso_at(),
                    source="provider_usage",
                    scope_kind="chat_session",
                    session_id=f"concurrent-{index % 4}",
                    agent_id=f"agent-{index % 3}",
                    input_tokens=100 + index,
                    output_tokens=10 + index,
                    total_tokens=110 + index,
                ),
                project_root=tmp_path,
            )
        except BaseException as exc:  # noqa: BLE001 - test collects all failures
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(32)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    summary = build_usage_summary(project_root=tmp_path)
    assert summary["globalTokenUsage"]["allTime"]["callCount"] == 32
    assert summary["globalTokenUsage"]["allTime"]["inputTokens"] == sum(100 + i for i in range(32))


def test_schema_initialization_runs_once_per_process(tmp_path, monkeypatch):
    from core.llm import usage_ledger

    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
    original = usage_ledger._ensure_schema
    calls = []

    def counting_ensure_schema(connection):
        calls.append(1)
        return original(connection)

    monkeypatch.setattr(usage_ledger, "_ensure_schema", counting_ensure_schema)
    usage_ledger._schema_ready.clear()

    for index in range(3):
        record_usage_event(
            UsageLedgerEvent(
                recorded_at=iso_at(),
                source="provider_usage",
                scope_kind="chat_session",
                session_id=f"schema-{index}",
                input_tokens=1,
                total_tokens=1,
            ),
            project_root=tmp_path,
        )
    build_usage_summary(project_root=tmp_path)
    build_usage_summary(scope="session", session_id="schema-1", project_root=tmp_path)

    assert len(calls) == 1


def test_summary_aggregates_in_sql_and_matches_reference(tmp_path, monkeypatch):
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
    path = usage_ledger_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [_make_seed_row(index) for index in range(20000)]
    _seed_rows(path, rows)

    reference = _reference_summary(
        path,
        scope="global",
        session_id="",
        agent_id="",
        provider="provider-1",
        model="model-0",
    )
    actual = build_usage_summary(
        scope="global",
        provider="provider-1",
        model="model-0",
        project_root=tmp_path,
    )
    assert actual == reference


def test_summary_20000_rows_is_faster_than_169ms(tmp_path, monkeypatch):
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
    import time

    path = usage_ledger_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [_make_seed_row(index) for index in range(20000)]
    _seed_rows(path, rows)

    reference_samples = []
    for _ in range(3):
        started = time.perf_counter()
        _reference_summary(
            path,
            scope="global",
            session_id="",
            agent_id="",
            provider="",
            model="",
        )
        reference_samples.append((time.perf_counter() - started) * 1000)
    reference_fastest = min(reference_samples)

    samples = []
    for _ in range(5):
        started = time.perf_counter()
        build_usage_summary(scope="global", project_root=tmp_path)
        samples.append((time.perf_counter() - started) * 1000)
    fastest = min(samples)
    assert fastest < 169.0, (
        f"summary above the 169ms baseline: {fastest:.1f}ms "
        f"(samples={[round(s,1) for s in samples]})"
    )
    assert fastest < reference_fastest * 0.75, (
        f"SQL summary not clearly faster than the Python reference: "
        f"new={fastest:.1f}ms old={reference_fastest:.1f}ms"
    )


def test_temp_dir_is_removable_after_ledger_calls(tmp_path, monkeypatch):
    import shutil

    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
    for index in range(5):
        record_usage_event(
            UsageLedgerEvent(
                recorded_at=iso_at(),
                source="provider_usage",
                scope_kind="chat_session",
                session_id=f"cleanup-{index}",
                input_tokens=1,
                total_tokens=1,
            ),
            project_root=tmp_path,
        )
    build_usage_summary(project_root=tmp_path)
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path.parent / "other")
    shutil.rmtree(tmp_path)


def test_usage_ledger_stats_reflect_failures(tmp_path, monkeypatch):
    from core.llm import usage_ledger

    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
    usage_ledger._reset_usage_ledger_stats()
    record_usage_event(
        UsageLedgerEvent(
            recorded_at=iso_at(),
            source="provider_usage",
            scope_kind="chat_session",
            session_id="stats-1",
            input_tokens=5,
            total_tokens=5,
        ),
        project_root=tmp_path,
    )

    def fail_insert(connection, sql, parameters):
        if "usage_events" in sql and sql.lstrip().upper().startswith("INSERT"):
            raise sqlite3.OperationalError("database is locked")
        return connection.execute(sql, parameters)

    real_connect = usage_ledger._connect
    monkeypatch.setattr(
        usage_ledger,
        "_connect",
        lambda project_root=None, *, timeout_seconds=5.0: _LockInjectingConnection(
            real_connect(project_root, timeout_seconds=timeout_seconds)
        ),
    )

    class _LockInjectingConnection:
        def __init__(self, inner):
            self._inner = inner
            self.row_factory = inner.row_factory

        def execute(self, sql, parameters=()):
            return fail_insert(self._inner, sql, parameters)

        def executescript(self, script):
            return self._inner.executescript(script)

        def commit(self):
            return self._inner.commit()

        def close(self):
            return self._inner.close()

    try:
        record_usage_event(
            UsageLedgerEvent(
                recorded_at=iso_at(),
                source="provider_usage",
                scope_kind="chat_session",
                session_id="stats-2",
                input_tokens=9,
                total_tokens=9,
            ),
            project_root=tmp_path,
            timeout_seconds=0.05,
        )
        raise AssertionError("expected the injected lock failure to surface")
    except sqlite3.OperationalError:
        pass

    stats = usage_ledger.usage_ledger_stats()
    assert stats["attempted"] == 2
    assert stats["persisted"] == 1
    assert stats["dropped"] == 1
    assert stats["lastFailure"]["reason"] == "OperationalError"


# 参考实现（旧 Python 聚合路径），仅用于等价性对照。
def _reference_summary(path, *, scope, session_id, agent_id, provider, model):
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    try:
        rows = list(
            connection.execute(
                "SELECT rowid AS _rowid, * FROM usage_events ORDER BY recorded_at ASC, rowid ASC"
            ).fetchall()
        )
    finally:
        connection.close()

    VALID = {"provider_usage", "estimated", "missing", "not_called"}
    NUMERIC = (
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
    import core.llm.usage_ledger as usage_ledger
    from core.llm.usage_ledger import UsageRollup

    def _int(value):
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    def filter_rows(rows, scope, *, session_id="", agent_id="", provider="", model=""):
        normalized_scope = str(scope or "global").strip().lower()
        filtered = []
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

    def parse_at(value):
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

    def rollup(rows):
        skipped = 0
        totals = {name: 0 for name in NUMERIC}
        counts = {
            "call_count": 0,
            "observed_call_count": 0,
            "estimated_call_count": 0,
            "missing_call_count": 0,
            "not_called_count": 0,
            "cache_observed_call_count": 0,
            "cache_unobserved_call_count": 0,
        }
        cache_observed_input_tokens = 0
        for row in rows:
            source = str(row["source"] or "")
            if source not in VALID:
                skipped += 1
                continue
            input_tokens = _int(row["input_tokens"])
            output_tokens = _int(row["output_tokens"])
            total_tokens = _int(row["total_tokens"]) or (input_tokens + output_tokens)
            cache_observed = bool(_int(row["cache_usage_observed"]))
            cached = _int(row["cached_input_tokens"]) if cache_observed else 0
            cache_read = (_int(row["cache_read_input_tokens"]) or cached) if cache_observed else 0
            uncached = _int(row["uncached_input_tokens"]) if cache_observed else 0
            if cache_observed and input_tokens and not uncached:
                uncached = max(0, input_tokens - cached)
            totals["input_tokens"] += input_tokens
            totals["cached_input_tokens"] += cached
            totals["cache_read_input_tokens"] += cache_read
            totals["cache_creation_input_tokens"] += _int(row["cache_creation_input_tokens"]) if cache_observed else 0
            totals["uncached_input_tokens"] += uncached
            totals["output_tokens"] += output_tokens
            totals["reasoning_output_tokens"] += _int(row["reasoning_output_tokens"])
            totals["total_tokens"] += total_tokens
            totals["context_window"] += _int(row["context_window"])
            totals["latency_ms"] += _int(row["latency_ms"])
            counts["call_count"] += 1
            if source == "provider_usage":
                counts["observed_call_count"] += 1
                if cache_observed:
                    counts["cache_observed_call_count"] += 1
                    cache_observed_input_tokens += input_tokens
                else:
                    counts["cache_unobserved_call_count"] += 1
            elif source == "estimated":
                counts["estimated_call_count"] += 1
            elif source == "missing":
                counts["missing_call_count"] += 1
            elif source == "not_called":
                counts["not_called_count"] += 1
        return UsageRollup(
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
            cache_observed_input_tokens=cache_observed_input_tokens,
            cache_observed_call_count=counts["cache_observed_call_count"],
            cache_unobserved_call_count=counts["cache_unobserved_call_count"],
        ), skipped

    normalized_scope = str(scope or "global").strip().lower() or "global"
    filters = {
        "sessionId": str(session_id or "").strip(),
        "agentId": str(agent_id or "").strip(),
        "provider": str(provider or "").strip(),
        "model": str(model or "").strip(),
    }
    scoped_rows = filter_rows(rows, normalized_scope, session_id=filters["sessionId"], agent_id=filters["agentId"], provider=filters["provider"], model=filters["model"])
    last_row = None
    for row in reversed(scoped_rows):
        if str(row["source"] or "") in VALID:
            last_row = row
            break
    rollup_filters = {"sessionId": filters["sessionId"], "agentId": filters["agentId"]}
    if last_row is not None:
        if not rollup_filters["sessionId"]:
            rollup_filters["sessionId"] = str(last_row["session_id"] or "").strip()
        if not rollup_filters["agentId"]:
            rollup_filters["agentId"] = str(last_row["agent_id"] or "").strip()
    session_rows = filter_rows(rows, "session", session_id=rollup_filters["sessionId"], provider=filters["provider"], model=filters["model"]) if rollup_filters["sessionId"] else []
    agent_rows = filter_rows(rows, "agent", agent_id=rollup_filters["agentId"], provider=filters["provider"], model=filters["model"]) if rollup_filters["agentId"] else []
    global_rows = filter_rows(rows, "global", provider=filters["provider"], model=filters["model"])
    now = datetime.now(timezone.utc)
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    tomorrow_start = today_start + timedelta(days=1)
    last7_start = today_start - timedelta(days=6)
    today_rows, last7_days_rows = [], []
    for row in global_rows:
        recorded_at = parse_at(row["recorded_at"])
        if recorded_at is None:
            continue
        if today_start <= recorded_at < tomorrow_start:
            today_rows.append(row)
        if last7_start <= recorded_at < tomorrow_start:
            last7_days_rows.append(row)
    global_rollup, skipped = rollup(global_rows)
    today_rollup, _ = rollup(today_rows)
    last7_days_rollup, _ = rollup(last7_days_rows)
    session_rollup, _ = rollup(session_rows)
    agent_rollup, _ = rollup(agent_rows)
    scoped_rollup, _ = rollup(scoped_rows)
    from core.llm.usage_ledger import UsageSummary, _row_to_last_usage

    def latest_context_window(rows):
        for row in reversed(rows):
            if str(row["source"] or "") not in VALID:
                continue
            context_window = _int(row["context_window"])
            if context_window:
                return context_window
        return 0

    payload = UsageSummary(
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
        model_context_window=latest_context_window(scoped_rows)
        or latest_context_window(global_rows),
        skipped_record_count=skipped,
    ).to_dict()
    payload["scopeTokenUsage"] = scoped_rollup.to_dict()
    return payload
