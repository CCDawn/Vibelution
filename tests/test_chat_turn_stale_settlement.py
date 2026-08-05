"""C1: chat_turn work-run settlement after worker death or tool-timeout hang."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.web.services import session_service
from core.web.services.session import turn_diagnostics


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def test_chat_turn_hang_reason_worker_gone(monkeypatch):
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    payload = {
        "runId": "turn-1",
        "sessionId": "session-a",
        "status": "running",
        "updatedAt": _iso(now - timedelta(minutes=1)),
        "startedAt": _iso(now - timedelta(minutes=2)),
        "finishedAt": "",
    }
    assert (
        turn_diagnostics._chat_turn_work_run_hang_reason(
            payload,
            now=now,
            worker_owns_turn=False,
        )
        == "worker_gone"
    )


def test_chat_turn_hang_reason_tool_timeout(monkeypatch):
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    payload = {
        "runId": "turn-1",
        "sessionId": "session-a",
        "status": "running",
        "updatedAt": _iso(now - timedelta(seconds=30)),
        "startedAt": _iso(now - timedelta(minutes=5)),
        "finishedAt": "",
        "lastToolError": {
            "toolName": "write_stdin",
            "timedOut": True,
            "failureClass": "timeout",
            "updatedAt": _iso(now - timedelta(seconds=200)),
            "summary": "timeout",
        },
    }
    assert (
        turn_diagnostics._chat_turn_work_run_hang_reason(
            payload,
            now=now,
            worker_owns_turn=True,
        )
        == "tool_timeout_hang"
    )
    # Fresh tool timeout must not settle while agent may still continue.
    payload["lastToolError"]["updatedAt"] = _iso(now - timedelta(seconds=20))
    assert (
        turn_diagnostics._chat_turn_work_run_hang_reason(
            payload,
            now=now,
            worker_owns_turn=True,
        )
        == ""
    )


def test_reconcile_settles_tool_timeout_hang(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    store = session_service._WORK_RUN_STORE
    # Point work runs at tmp store root if possible.
    from core.runtime_manager import work_run_store as work_run_store_module

    monkeypatch.setattr(work_run_store_module, "WORK_RUNS_DIR", tmp_path / "work_runs")
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", work_run_store_module.WorkRunStore(root=tmp_path / "work_runs"))

    now = datetime.now(timezone.utc)
    turn_id = "session-a-turn-timeout"
    session_service._WORK_RUN_STORE.persist_snapshot(
        "chat_turn",
        {
            "runId": turn_id,
            "runKind": "chat_turn",
            "sessionId": "session-a",
            "status": "running",
            "currentPhase": "running",
            "startedAt": _iso(now - timedelta(minutes=10)),
            "updatedAt": _iso(now - timedelta(seconds=30)),
            "finishedAt": "",
            "summary": "工具失败：write_stdin",
            "lastToolError": {
                "toolName": "write_stdin",
                "timedOut": True,
                "failureClass": "timeout",
                "summary": "timeout",
                "updatedAt": _iso(now - timedelta(seconds=200)),
            },
        },
        active_run_id=turn_id,
    )
    # Simulate hung worker still claiming the turn.
    session_service._set_session_running("session-a", True, turn_id=turn_id)

    settled = turn_diagnostics.reconcile_stale_chat_turn_work_runs(now=now)
    assert settled
    assert settled[0]["reason"] == "tool_timeout_hang"
    assert settled[0]["status"] == "failed_runtime"

    latest = session_service._WORK_RUN_STORE.load_snapshot("chat_turn", turn_id)
    assert latest is not None
    assert latest["status"] == "failed_runtime"
    assert str(latest.get("finishedAt") or "").strip()
    assert session_service._WORK_RUN_STORE.load_active_snapshot("chat_turn") is None
    assert session_service._is_session_running("session-a") is False


def test_reconcile_settles_worker_gone(tmp_path, monkeypatch):
    from core.runtime_manager import work_run_store as work_run_store_module

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(work_run_store_module, "WORK_RUNS_DIR", tmp_path / "work_runs")
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", work_run_store_module.WorkRunStore(root=tmp_path / "work_runs"))

    now = datetime.now(timezone.utc)
    turn_id = "session-b-turn-orphan"
    session_service._WORK_RUN_STORE.persist_snapshot(
        "chat_turn",
        {
            "runId": turn_id,
            "runKind": "chat_turn",
            "sessionId": "session-b",
            "status": "running",
            "currentPhase": "running",
            "startedAt": _iso(now - timedelta(minutes=2)),
            "updatedAt": _iso(now - timedelta(minutes=1)),
            "finishedAt": "",
        },
        active_run_id=turn_id,
    )
    # No in-memory worker ownership.
    session_service._set_session_running("session-b", False)

    settled = turn_diagnostics.reconcile_stale_chat_turn_work_runs(now=now)
    assert any(item.get("runId") == turn_id for item in settled)
    latest = session_service._WORK_RUN_STORE.load_snapshot("chat_turn", turn_id)
    assert latest is not None
    assert latest["status"] == "stopped"
    assert str(latest.get("finishedAt") or "").strip()
