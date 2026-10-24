from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core.web.services import pet_activity_service

NOW = datetime(2026, 9, 8, 2, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clear_completion_receipts():
    pet_activity_service._COMPLETION_RECEIPTS.clear()
    yield
    pet_activity_service._COMPLETION_RECEIPTS.clear()


def test_revisiting_old_success_does_not_create_a_new_completion(monkeypatch):
    session = {
        **_session("revisited", status="ready"),
        "terminalReason": "success",
        "lastTurnTerminalTurnId": "turn-completed-once",
    }
    monkeypatch.setattr(pet_activity_service, "list_sessions", lambda: [session])
    monkeypatch.setattr(pet_activity_service, "load_chat_turn_work_run_summary", lambda: {"activeItems": []})
    monkeypatch.setattr(pet_activity_service, "list_tool_approval_requests", lambda *_a, **_k: [])
    monkeypatch.setattr(
        pet_activity_service, "_read_completion_events",
        lambda _sid: [SimpleNamespace(
            turn_id="turn-completed-once", event_type="turn_completed", status="completed",
            timestamp=(NOW - timedelta(minutes=8)).isoformat(),
        )], raising=False,
    )

    assert pet_activity_service.get_pet_activity(now=NOW)["sessions"] == []


def test_paused_work_run_does_not_animate_output_or_replay_historical_success(monkeypatch):
    session = {**_session("paused", status="ready"), "terminalReason": "success"}
    monkeypatch.setattr(pet_activity_service, "list_sessions", lambda: [session])
    monkeypatch.setattr(pet_activity_service, "load_chat_turn_work_run_summary", lambda: {
        "activeItems": [{"sessionId": "paused", "status": "paused", "currentPhase": "thinking"}],
    })
    monkeypatch.setattr(pet_activity_service, "list_tool_approval_requests", lambda *_a, **_k: [])
    payload = pet_activity_service.get_pet_activity(now=NOW)
    assert payload["aggregateTone"] == "idle"
    assert payload["activeCount"] == 0
    assert payload["sessions"] == []


def _session(
    session_id: str,
    *,
    status: str,
    title: str | None = None,
    updated_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "id": session_id,
        "title": title or f"Session {session_id}",
        "agentId": f"agent-{session_id}",
        "agentDisplayName": f"Agent {session_id}",
        "status": status,
        "currentPhase": status,
        "lastTurnTerminalTurnId": f"turn-{session_id}",
        "updatedAt": (updated_at or NOW).isoformat(),
    }


def test_pet_activity_aggregates_all_sessions_without_leaking_runtime_payloads(monkeypatch):
    sessions = [
        _session(
            "running",
            status="ready",
            title=r"Analyze C:\\Users\\Alice\\secret.txt sk-testsecret123456",
        ),
        _session("failed", status="failed_runtime"),
        _session("approval", status="tooling"),
        _session("idle", status="ready", updated_at=NOW - timedelta(hours=1)),
    ]
    monkeypatch.setattr(pet_activity_service, "list_sessions", lambda: sessions)
    monkeypatch.setattr(
        pet_activity_service,
        "load_chat_turn_work_run_summary",
        lambda: {
            "activeItems": [
                {
                    "sessionId": "running",
                    "currentPhase": "reading",
                    "userMessage": "must never escape",
                    "summary": "must never escape either",
                }
            ]
        },
    )
    monkeypatch.setattr(
        pet_activity_service,
        "list_tool_approval_requests",
        lambda session_id, status="": ([{"requestId": "approval-1", "toolArgs": "secret"}]
                                        if session_id == "approval" and status == "pending" else []),
    )

    payload = pet_activity_service.get_pet_activity(now=NOW)

    assert payload["schemaVersion"] == 1
    assert payload["aggregateTone"] == "approval"
    assert payload["animationState"] == "waiting"
    assert payload["activeCount"] == 2
    assert payload["attentionCount"] == 2
    assert [item["sessionId"] for item in payload["sessions"]] == ["approval", "failed", "running"]
    assert payload["sessions"][2]["phase"] == "reading"
    assert "secret.txt" not in payload["sessions"][2]["title"]
    assert "sk-testsecret" not in payload["sessions"][2]["title"]
    serialized = str(payload)
    assert "must never escape" not in serialized
    assert "toolArgs" not in serialized


def test_pet_activity_maps_running_phases_and_recent_completion(monkeypatch):
    sessions = [
        _session("thinking", status="thinking"),
        _session("tooling", status="editing"),
        _session("verifying", status="checking"),
        _session("answering", status="streaming"),
        _session("completed", status="completed", updated_at=NOW - timedelta(seconds=5)),
        _session("old-completed", status="completed", updated_at=NOW - timedelta(minutes=1)),
    ]
    monkeypatch.setattr(pet_activity_service, "list_sessions", lambda: sessions)
    monkeypatch.setattr(
        pet_activity_service,
        "load_chat_turn_work_run_summary",
        lambda: {"activeItems": []},
    )
    monkeypatch.setattr(pet_activity_service, "list_tool_approval_requests", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        pet_activity_service, "_read_completion_events",
        lambda sid: [SimpleNamespace(
            turn_id=f"turn-{sid}", event_type="turn_completed", status="completed",
            timestamp=next(s["updatedAt"] for s in sessions if s["id"] == sid),
        )],
    )

    payload = pet_activity_service.get_pet_activity(now=NOW)

    by_id = {item["sessionId"]: item for item in payload["sessions"]}
    assert by_id["thinking"]["phase"] == "thinking"
    assert by_id["tooling"]["phase"] == "tooling"
    assert by_id["verifying"]["phase"] == "verifying"
    assert by_id["answering"]["phase"] == "answering"
    assert by_id["completed"]["tone"] == "completed"
    assert by_id["completed"]["completionIdentity"] == "turn-completed"
    assert by_id["completed"]["completedAt"] == (NOW - timedelta(seconds=5)).isoformat()
    assert "old-completed" not in by_id


def test_pet_activity_returns_idle_when_no_visible_activity(monkeypatch):
    monkeypatch.setattr(
        pet_activity_service,
        "list_sessions",
        lambda: [_session("idle", status="ready", updated_at=NOW - timedelta(hours=1))],
    )
    monkeypatch.setattr(
        pet_activity_service,
        "load_chat_turn_work_run_summary",
        lambda: {"activeItems": []},
    )
    monkeypatch.setattr(pet_activity_service, "list_tool_approval_requests", lambda *_args, **_kwargs: [])

    payload = pet_activity_service.get_pet_activity(now=NOW)

    assert payload["aggregateTone"] == "idle"
    assert payload["animationState"] == "idle"
    assert payload["activeCount"] == 0
    assert payload["attentionCount"] == 0
    assert payload["sessions"] == []


@pytest.mark.parametrize("status", ["paused", "paused_limit", "stopped_by_user", "cancelled", "needs_continue", "superseded"])
def test_interrupted_turns_never_celebrate(status):
    assert pet_activity_service._resolve_tone(
        _session("s", status=status), runtime_running=False, needs_approval=False, now=NOW,
    ) == "idle"


def test_live_turn_overrides_previous_failure():
    assert pet_activity_service._resolve_tone(
        _session("s", status="failed_runtime"), runtime_running=True, needs_approval=False, now=NOW,
    ) == "running"


def test_ready_uses_actual_last_turn_outcome():
    session = _session("s", status="ready")
    session["lastTurnStatus"] = "completed"
    assert pet_activity_service._resolve_tone(
        session, runtime_running=False, needs_approval=False, now=NOW,
        completion_at=NOW.isoformat(),
    ) == "completed"
    # ``ready`` is the idle phase, never a turn outcome. Treating it as a
    # success made a settled session announce a completion it never had.
    session["lastTurnStatus"] = "ready"
    assert pet_activity_service._resolve_tone(session, runtime_running=False, needs_approval=False, now=NOW) == "idle"
    session["lastTurnStatus"] = "stopped_by_user"
    assert pet_activity_service._resolve_tone(session, runtime_running=False, needs_approval=False, now=NOW) == "idle"


def test_historical_errors_stay_accessible_without_masking_live_work(monkeypatch):
    sessions = [_session("old", status="failed_runtime", updated_at=NOW - timedelta(days=6)),
                _session("live", status="running")]
    monkeypatch.setattr(pet_activity_service, "list_sessions", lambda: sessions)
    monkeypatch.setattr(pet_activity_service, "load_chat_turn_work_run_summary", lambda: {"activeItems": []})
    monkeypatch.setattr(pet_activity_service, "list_tool_approval_requests", lambda *_a, **_k: [])
    result = pet_activity_service.get_pet_activity(now=NOW)
    assert result["aggregateTone"] == "running"
    assert result["attentionCount"] == 0
    assert [row["sessionId"] for row in result["sessions"]] == ["live", "old"]
    sessions.pop()
    assert pet_activity_service.get_pet_activity(now=NOW)["aggregateTone"] == "idle"


def test_legacy_local_timestamps_use_session_timebase():
    local_time = NOW.astimezone().replace(tzinfo=None)
    assert pet_activity_service._parse_timestamp(local_time.isoformat()) == NOW


def test_running_candidate_wins_over_stale_success_outcome():
    # A child session reports childStatus first and it can lag behind the rest of
    # the projection. When that stale "ready" was primary, the tone fell through
    # to the previous turn's success and fired a completion mid-turn.
    session = {
        **_session("s", status="streaming"),
        "sessionKind": "child",
        "childStatus": "ready",
        "lastTurnStatus": "completed",
    }
    assert pet_activity_service._resolve_tone(
        session, runtime_running=False, needs_approval=False, now=NOW,
    ) == "running"


def test_settled_success_still_reports_completion():
    # Guard the happy path: a genuinely settled success keeps its completion.
    session = {**_session("s", status="ready"), "lastTurnStatus": "completed"}
    assert pet_activity_service._resolve_tone(
        session, runtime_running=False, needs_approval=False, now=NOW,
        completion_at=NOW.isoformat(),
    ) == "completed"


@pytest.mark.parametrize("event_type,status", [
    ("turn_interrupted", "stopped_by_user"), ("turn_failed", "failed"),
    ("turn_completed", "future_status"),
])
def test_success_projection_requires_a_successful_journal_receipt(monkeypatch, event_type, status):
    session = {**_session("s", status="ready"), "terminalReason": "success"}
    monkeypatch.setattr(pet_activity_service, "list_sessions", lambda: [session])
    monkeypatch.setattr(pet_activity_service, "load_chat_turn_work_run_summary", lambda: {"activeItems": []})
    monkeypatch.setattr(pet_activity_service, "list_tool_approval_requests", lambda *_a, **_k: [])
    monkeypatch.setattr(
        pet_activity_service, "_read_completion_events",
        lambda _sid: [SimpleNamespace(
            turn_id="turn-s", event_type=event_type, status=status, timestamp=NOW.isoformat(),
        )],
    )
    assert pet_activity_service.get_pet_activity(now=NOW)["sessions"] == []


def test_unreadable_completion_receipt_stays_idle(monkeypatch):
    def unavailable(_sid):
        raise OSError("journal unavailable")

    monkeypatch.setattr(pet_activity_service, "_read_completion_events", unavailable)
    assert pet_activity_service._completion_receipt(_session("s", status="completed")) == {}
    assert pet_activity_service._completion_receipt({"id": "s"}) == {}


def test_completion_polls_reuse_small_receipts_and_refresh_only_new_turns(monkeypatch):
    sessions = [{**_session(str(i), status="ready"), "terminalReason": "success"} for i in range(65)]
    reads = []

    def terminal_events(sid):
        reads.append(sid)
        session = next(s for s in sessions if s["id"] == sid)
        return [SimpleNamespace(
            turn_id=session["lastTurnTerminalTurnId"], event_type="turn_completed", status="completed",
            timestamp=(NOW if len(reads) > 65 else NOW - timedelta(hours=1)).isoformat(),
        )]

    monkeypatch.setattr(pet_activity_service, "list_sessions", lambda: sessions)
    monkeypatch.setattr(pet_activity_service, "load_chat_turn_work_run_summary", lambda: {"activeItems": []})
    monkeypatch.setattr(pet_activity_service, "list_tool_approval_requests", lambda *_a, **_k: [])
    monkeypatch.setattr(pet_activity_service, "_read_completion_events", terminal_events)
    assert pet_activity_service.get_pet_activity(now=NOW)["sessions"] == []
    assert pet_activity_service.get_pet_activity(now=NOW)["sessions"] == []
    assert len(reads) == 65
    sessions[0]["lastTurnTerminalTurnId"] = "new-terminal-turn"
    rows = pet_activity_service.get_pet_activity(now=NOW)["sessions"]
    assert len(reads) == 66
    assert rows[0]["completionIdentity"] == "new-terminal-turn"
    sessions.pop(0)
    pet_activity_service.get_pet_activity(now=NOW)
    assert len(pet_activity_service._COMPLETION_RECEIPTS) == 64


def test_terminal_tail_reader_inherits_runtime_project_root(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(pet_activity_service.session_service, "PROJECT_ROOT", tmp_path)

    def bounded_reader(root, sid, *, limit):
        seen.append((root, sid, limit))
        return [], False, True

    monkeypatch.setattr(pet_activity_service, "load_latest_turn_events_for_preview", bounded_reader)
    assert pet_activity_service._read_completion_events("s") == []
    assert seen == [(tmp_path, "s", 128)]


def test_real_terminal_tail_projects_completion_receipt(monkeypatch, tmp_path):
    from core.chat.turn_journal import TurnJournalEvent, turn_journal_path

    journal_root = tmp_path / "workspace"
    path = turn_journal_path(tmp_path, "s", journal_workspace_root=journal_root)
    path.parent.mkdir(parents=True)
    event = TurnJournalEvent(
        schema_version=2, event_id="terminal-receipt", session_id="s", turn_id="turn-s",
        sequence=1, event_type="turn_completed", status="completed", timestamp=NOW.isoformat(),
        source="test", payload={},
    )
    path.write_text(json.dumps(event.to_dict()) + "\n", encoding="utf-8")
    reader = pet_activity_service.load_latest_turn_events_for_preview
    monkeypatch.setattr(pet_activity_service.session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        pet_activity_service, "load_latest_turn_events_for_preview",
        lambda root, sid, *, limit: reader(root, sid, limit=limit, journal_workspace_root=journal_root),
    )
    assert pet_activity_service._completion_receipt(_session("s", status="completed")) == {
        "completionIdentity": "turn-s", "completedAt": NOW.isoformat(),
    }


def test_previous_turn_running_is_not_current_execution():
    session = {**_session("s", status="ready"), "lastTurnStatus": "running"}
    assert pet_activity_service._resolve_tone(
        session, runtime_running=False, needs_approval=False, now=NOW,
    ) == "idle"


def test_explicit_unknown_current_status_does_not_fall_back_to_success():
    session = {**_session("s", status="future_status"), "lastTurnStatus": "completed"}
    assert pet_activity_service._resolve_tone(
        session, runtime_running=False, needs_approval=False, now=NOW,
    ) == "idle"


def test_live_status_only_work_run_does_not_hide_current_activity_phase():
    assert pet_activity_service._resolve_phase(
        _session("s", status="reading"), live_item={"status": "running", "currentPhase": "running"}, tone="running",
    ) == "reading"
