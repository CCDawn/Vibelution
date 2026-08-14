from __future__ import annotations

from core.web.services import session_service
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
        runs = list_active_session_work_runs(reconcile=False)
        live = next(item for item in runs if item["sessionId"] == "session-live")
        assert live["status"] == "running"
        assert live["runId"] == "turn-1"
    finally:
        with session_service._RUNNING_SESSIONS_LOCK:
            session_service._RUNNING_SESSION_IDS.discard("session-live")
            session_service._SESSION_ACTIVE_TURN_IDS.pop("session-live", None)
            session_service._SESSION_ACTIVE_TURN_LEASES.pop("session-live", None)
