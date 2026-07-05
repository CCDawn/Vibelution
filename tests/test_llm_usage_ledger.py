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
    assert summary["sessionTokenUsage"]["uncachedInputTokens"] == 80
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
