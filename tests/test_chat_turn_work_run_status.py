from __future__ import annotations

import logging

from core.web.services import session_service
from core.web.services.session import read_health
from core.web.services.session.turn_diagnostics import list_active_session_work_runs


def test_list_active_session_work_runs_does_not_read_chat_state(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    def boom(*_args, **_kwargs):
        raise AssertionError("runtime summary must not lock chat_state for live work-run status")

    monkeypatch.setattr(session_service, "load_chat_state", boom)

    with session_service._RUNNING_SESSIONS_LOCK:
        session_service._RUNNING_SESSION_IDS.add("session-live")
        session_service._SESSION_ACTIVE_TURN_IDS["session-live"] = "turn-1"
        session_service._SESSION_ACTIVE_TURN_LEASES["session-live"] = ["readonly_chat"]
    try:
        session_service._persist_chat_turn_work_run(
            session_id="session-live",
            turn_id="turn-1",
            status="running",
            user_message="回复数字 1",
            summary="",
        )
        runs = list_active_session_work_runs(reconcile=False)
        live = next(item for item in runs if item["sessionId"] == "session-live")
        assert live["status"] == "running"
        assert live["runId"] == "turn-1"
        assert live["userMessage"] == "回复数字 1"
        assert "summary" not in live
    finally:
        with session_service._RUNNING_SESSIONS_LOCK:
            session_service._RUNNING_SESSION_IDS.discard("session-live")
            session_service._SESSION_ACTIVE_TURN_IDS.pop("session-live", None)
            session_service._SESSION_ACTIVE_TURN_LEASES.pop("session-live", None)
        session_service._persist_chat_turn_work_run(
            session_id="session-live",
            turn_id="turn-1",
            status="completed",
            finished_at="2026-08-15T00:00:10",
        )


class _RaisingTurnScheduler:
    def queued_session_turn_ids(self):
        raise RuntimeError("queue read failed")

    def clear(self):
        return None


class _RaisingWorkRunStore:
    def load_snapshot(self, run_kind, run_id):
        return None

    def load_active_snapshot(self, run_kind):
        raise RuntimeError("snapshot read failed")

    def list_snapshots(self, run_kind, limit=None):
        raise RuntimeError("snapshot list failed")


def test_list_active_session_work_runs_reports_degraded_reads(
    monkeypatch,
    tmp_path,
    caplog,
) -> None:
    """Unreadable queue/snapshot sources must stay visible instead of silently
    demoting queued turns or hiding persisted queued snapshots."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_SESSION_TURN_SCHEDULER", _RaisingTurnScheduler())
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", _RaisingWorkRunStore())
    read_health.reset_session_read_degradation_state()

    with session_service._RUNNING_SESSIONS_LOCK:
        session_service._RUNNING_SESSION_IDS.add("session-live")
        session_service._SESSION_ACTIVE_TURN_IDS["session-live"] = "turn-1"
    try:
        with caplog.at_level(logging.WARNING):
            runs = list_active_session_work_runs(reconcile=False)
    finally:
        with session_service._RUNNING_SESSIONS_LOCK:
            session_service._RUNNING_SESSION_IDS.discard("session-live")
            session_service._SESSION_ACTIVE_TURN_IDS.pop("session-live", None)

    assert [item["sessionId"] for item in runs] == ["session-live"]
    assert runs[0]["status"] == "running"
    assert "Session read degraded" in caplog.text
    assert "RuntimeError" in caplog.text
