from types import SimpleNamespace

import pytest

from core.web.services import runtime_service


@pytest.fixture
def operator_retire_owners(monkeypatch):
    calls = []
    events = []
    owner_names = (
        "_stop_additional_work_for_restart",
        "_stop_active_evolution_runs_before_shutdown",
        "_stop_active_source_collection_runs_before_shutdown",
        "_stop_active_chat_room_rounds_before_shutdown",
        "_stop_active_chat_turns_before_shutdown",
    )
    for name in owner_names:
        def stop_owner(*, owner=name, **kwargs):
            calls.append((owner, kwargs))
            return [{"kind": owner, "status": "stopped"}]

        monkeypatch.setattr(runtime_service, name, stop_owner)
    monkeypatch.setattr(runtime_service, "get_web_language", lambda: "en")
    monkeypatch.setattr(
        runtime_service, "_restart_guard_active_work_runs",
        lambda: [] if len(calls) == len(owner_names) else [{"kind": "chat_turn", "runId": "active"}],
    )
    monkeypatch.setattr(runtime_service, "_schedule_local_backend_exit", lambda: calls.append(("exit", {})))
    monkeypatch.setattr(runtime_service, "_record_shutdown_event", lambda code, **kwargs: events.append((code, kwargs)))

    def unexpected_lifecycle_write(*args, **kwargs):
        raise AssertionError("Electron retirement must not submit another lifecycle operation")

    monkeypatch.setattr(runtime_service, "ensure_daemon_running", unexpected_lifecycle_write)
    monkeypatch.setattr(runtime_service, "submit_command", unexpected_lifecycle_write)
    return calls, events


@pytest.mark.parametrize("action", ["close", "restart"])
def test_operator_retire_stops_task_owners_and_preserves_source(operator_retire_owners, action):
    calls, events = operator_retire_owners
    source = f"electron_user_{action}"

    response = runtime_service.request_runtime_shutdown(
        body_present=True, source=source, reason=f"user_{action}", interrupt_active_work=True,
    )

    assert response["mode"] == "local_retire"
    assert response["accepted"] is True
    assert [name for name, _ in calls] == [
        "_stop_additional_work_for_restart",
        "_stop_active_evolution_runs_before_shutdown",
        "_stop_active_source_collection_runs_before_shutdown",
        "_stop_active_chat_room_rounds_before_shutdown",
        "_stop_active_chat_turns_before_shutdown",
        "exit",
    ]
    assert len({kwargs["deadline"] for _, kwargs in calls[:-1]}) == 1
    assert calls[-2][1]["persist_partials"] is True
    assert response["chatTurns"][0]["status"] == "stopped"
    assert response["otherWorkRuns"][0]["status"] == "stopped"
    assert [code for code, _ in events] == [f"runtime.shutdown.user_{action}_paused", "runtime.shutdown.accepted"]
    assert all(event["fields"]["source"] == source for _, event in events)


@pytest.mark.parametrize("source,reason,interrupt,body_present,stop_manager", [
    ("web_ui", "user_close", True, True, False),
    ("electron_user_close", "user_restart", True, True, False),
    ("electron_user_restart", "user_close", True, True, False),
    ("electron_user_close", "user_close", False, True, False),
    ("electron_user_close", "user_close", True, False, False),
    ("electron_user_close", "user_close", True, True, True),
])
def test_operator_close_requires_exact_authorization(
    operator_retire_owners, source, reason, interrupt, body_present, stop_manager,
):
    calls, _ = operator_retire_owners

    with pytest.raises(runtime_service.RuntimeRestartActiveWorkBlocked):
        runtime_service.request_runtime_shutdown(
            body_present=body_present, source=source, reason=reason,
            interrupt_active_work=interrupt, stop_manager=stop_manager,
        )

    assert calls == []


@pytest.mark.parametrize("action", ["close", "restart"])
def test_operator_retire_does_not_claim_saved_state_when_owner_times_out(
    monkeypatch, operator_retire_owners, action,
):
    calls, events = operator_retire_owners
    monkeypatch.setattr(
        runtime_service, "_stop_active_chat_turns_before_shutdown",
        lambda **kwargs: [{"kind": "chat_turn", "status": "timeout", "error": "chat_turn_stop_wait_timeout"}],
    )

    with pytest.raises(runtime_service.RuntimeRestartPauseFailed) as failure:
        runtime_service.request_runtime_shutdown(
            body_present=True, source=f"electron_user_{action}", reason=f"user_{action}", interrupt_active_work=True,
        )

    assert failure.value.results[0]["error"] == "chat_turn_stop_wait_timeout"
    assert all(name != "exit" for name, _ in calls)
    assert events[-1][0] == f"runtime.shutdown.user_{action}_pause_failed"
    assert events[-1][1]["fields"]["source"] == f"electron_user_{action}"


def test_local_backend_exit_requires_an_owned_uvicorn_server(monkeypatch):
    monkeypatch.setattr(runtime_service, "sys", SimpleNamespace(modules={}))
    monkeypatch.setattr(
        "core.web.server_shutdown.schedule_server_shutdown",
        lambda **_kwargs: False,
    )

    with pytest.raises(RuntimeError, match="requires an owned Uvicorn server"):
        runtime_service._schedule_local_backend_exit()


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
