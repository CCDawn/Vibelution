from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.web.services import pet_activity_service


NOW = datetime(2026, 9, 8, 2, 0, tzinfo=timezone.utc)


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

    payload = pet_activity_service.get_pet_activity(now=NOW)

    by_id = {item["sessionId"]: item for item in payload["sessions"]}
    assert by_id["thinking"]["phase"] == "thinking"
    assert by_id["tooling"]["phase"] == "tooling"
    assert by_id["verifying"]["phase"] == "verifying"
    assert by_id["answering"]["phase"] == "answering"
    assert by_id["completed"]["tone"] == "completed"
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
