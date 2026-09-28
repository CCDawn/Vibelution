from core.web.services import runtime_service


def test_work_run_summary_includes_source_collection_active_item(monkeypatch):
    source_active = {
        "runId": "dprun-source-live",
        "runKind": "source_collection_run",
        "status": "running",
        "currentPhase": "searching",
        "summary": "正在执行资料搜集。",
    }

    monkeypatch.setattr(
        runtime_service,
        "load_chat_turn_work_run_summary",
        lambda: {"active": None, "latest": None, "activeItems": []},
    )
    monkeypatch.setattr(
        runtime_service,
        "_safe_load_chat_room_work_run_summary",
        lambda: {"active": None, "latest": None},
    )
    monkeypatch.setattr(
        runtime_service,
        "_safe_load_source_collection_work_run_summary",
        lambda: {"active": source_active, "latest": source_active, "activeItems": [source_active]},
    )
    monkeypatch.setattr(runtime_service, "_safe_load_evolution_work_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime_service, "_safe_load_supervised_worktree_work_run", lambda *args, **kwargs: None)

    summary = runtime_service._work_run_summary()
    active_runs = runtime_service._active_work_runs(summary)

    assert summary["active"]["source_collection_run"] == source_active
    assert summary["latest"]["source_collection_run"] == source_active
    assert summary["activeItems"]["source_collection_run"] == [source_active]
    assert active_runs == [
        {
            "kind": "source_collection_run",
            "runId": "dprun-source-live",
            "status": "running",
            "sessionId": "",
        }
    ]


def test_work_run_summary_degrades_when_chat_turn_summary_fails(monkeypatch):
    def fail_chat_turn_summary():
        raise RuntimeError("session index is blocked")

    monkeypatch.setattr(runtime_service, "load_chat_turn_work_run_summary", fail_chat_turn_summary)
    monkeypatch.setattr(
        runtime_service,
        "_safe_load_chat_room_work_run_summary",
        lambda: {"active": None, "latest": None},
    )
    monkeypatch.setattr(
        runtime_service,
        "_safe_load_source_collection_work_run_summary",
        lambda: {"active": None, "latest": None, "activeItems": []},
    )
    monkeypatch.setattr(runtime_service, "_safe_load_evolution_work_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime_service, "_safe_load_supervised_worktree_work_run", lambda *args, **kwargs: None)

    summary = runtime_service._work_run_summary()

    assert summary["active"]["chat_turn"] is None
    assert summary["latest"]["chat_turn"] is None
    assert summary["activeItems"]["chat_turn"] == []


def _compression_summary_telemetry_fixtures():
    from core.chat.turn_journal import SCHEMA_VERSION, TurnJournalEvent

    checkpoint = TurnJournalEvent(
        schema_version=SCHEMA_VERSION,
        event_id="cp-1",
        session_id="session-telemetry",
        turn_id="turn-2",
        sequence=10,
        event_type="compaction_checkpoint",
        status="checkpointed",
        timestamp="2026-09-21T08:00:05Z",
        source="agent_context_compression",
        payload={
            "beforeTokens": 5000,
            "afterTokens": 1600,
            "savedTokens": 3400,
            "schema": "context_compression_checkpoint.v1",
        },
    )
    usage_rows = [
        {
            "event_id": "u-before",
            "recorded_at": "2026-09-21T08:00:00Z",
            "turn_id": "turn-2",
            "source": "provider_usage",
            "input_tokens": 5000,
            "cached_input_tokens": 4800,
            "cache_read_input_tokens": 4800,
            "cache_creation_input_tokens": 0,
            "uncached_input_tokens": 200,
            "total_tokens": 5200,
            "cache_usage_observed": True,
        },
        {
            "event_id": "u-after",
            "recorded_at": "2026-09-21T08:00:30Z",
            "turn_id": "turn-2",
            "source": "provider_usage",
            "input_tokens": 1600,
            "cached_input_tokens": 300,
            "cache_read_input_tokens": 300,
            "cache_creation_input_tokens": 1250,
            "uncached_input_tokens": 1300,
            "total_tokens": 1800,
            "cache_usage_observed": True,
        },
    ]
    return checkpoint, usage_rows


def test_context_compression_summary_includes_cache_telemetry(monkeypatch):
    checkpoint, usage_rows = _compression_summary_telemetry_fixtures()
    monkeypatch.setattr(
        runtime_service,
        "load_session_conversation_events_snapshot",
        lambda session_id: [checkpoint],
    )
    monkeypatch.setattr(
        "core.chat.context_compression_telemetry.load_session_usage_rows",
        lambda project_root, session_id: usage_rows,
    )

    summary = runtime_service._context_compression_summary({}, {}, {"id": "session-telemetry"})

    assert summary["source"] == "conversation_ledger"
    assert summary["compressionCount"] == 1
    telemetry = summary["cacheTelemetry"]
    assert telemetry["compressionCount"] == 1
    assert telemetry["savedTokensTotal"] == 3400
    assert telemetry["cacheRewrite"]["cacheHitDropTokens"] == 4800 - 300
    assert telemetry["cacheRewrite"]["cacheWriteTokensAfter"] == 1250
    assert telemetry["cacheRewrite"]["evidence"] == "complete"
    assert telemetry["replay"]["replayRatio"] == 1.0
    # The unbounded per-compression list stays behind the aggregate surface.
    assert "compressions" not in telemetry


def test_context_compression_summary_omits_cache_telemetry_on_failure(monkeypatch):
    def fail_snapshot(session_id):
        raise RuntimeError("journal is unavailable")

    monkeypatch.setattr(runtime_service, "load_session_conversation_events_snapshot", fail_snapshot)

    summary = runtime_service._context_compression_summary({}, {}, {"id": "session-telemetry"})

    assert "cacheTelemetry" not in summary
    assert summary["source"] == "runtime_state"


def test_context_compression_summary_skips_telemetry_without_compressions(monkeypatch):
    monkeypatch.setattr(runtime_service, "load_session_conversation_events_snapshot", lambda session_id: [])

    def unexpected(*args, **kwargs):
        raise AssertionError("telemetry join must not run without ledger compressions")

    monkeypatch.setattr(
        "core.chat.context_compression_telemetry.load_session_usage_rows", unexpected
    )

    summary = runtime_service._context_compression_summary({}, {}, {"id": "session-telemetry"})

    assert "cacheTelemetry" not in summary
    assert summary["compressionCount"] == 0
