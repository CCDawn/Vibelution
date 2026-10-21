"""Session delete must not hold chat_state lock while replaying journals.

Live symptom: after deleting a tab, switching to a sibling session stayed on
the skeleton because DELETE held `_CHAT_STATE_LOCK` for seconds while
`_session_ledger_visible_messages` / `_normalize_conversation` scanned
`turn_journal.jsonl`. Sibling GET detail then waited on the same lock.
"""

from __future__ import annotations

import threading
import time

import pytest

from core.ui.chat_state import save_chat_state
from core.web.services import (
    agent_bulk_delete_service,
    agent_directory_service,
    agent_mode_binding_service,
    chat_room_service,
    session_service,
    team_service,
)
from core.web.services.session.agent_sessions import (
    _next_active_session_id_from_remaining,
)


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_bulk_delete_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)


def _seed_two_sessions(tmp_path) -> None:
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-keep",
            "updated_at": "2026-08-17T01:00:00",
            "conversations": [
                {
                    "conversation_id": "session-delete",
                    "title": "Delete me",
                    "updated_at": "2026-08-17T00:50:00",
                    "last_turn_status": "ready",
                },
                {
                    "conversation_id": "session-keep",
                    "title": "Keep me",
                    "updated_at": "2026-08-17T01:00:00",
                    "last_turn_status": "ready",
                },
            ],
        },
    )


def test_next_active_prefers_current_active_then_latest_updated_row():
    remaining = [
        {"conversation_id": "older", "updated_at": "2026-05-18T10:00:00"},
        {"conversation_id": "newer", "updated_at": "2026-05-18T11:00:00"},
    ]
    assert (
        _next_active_session_id_from_remaining(
            remaining,
            current_active_id="older",
            deleted_session_id="live",
        )
        == "older"
    )
    assert (
        _next_active_session_id_from_remaining(
            remaining,
            current_active_id="live",
            deleted_session_id="live",
        )
        == "newer"
    )


def test_delete_does_not_hold_lock_during_journal_helpers(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_two_sessions(tmp_path)

    lock_depth: dict[int, int] = {}
    lock_started_at: dict[int, float] = {}
    journal_calls_while_locked: list[str] = []
    lock_holds_ms: dict[int, list[float]] = {}
    entered_lock = threading.Event()
    delete_ident = {"value": 0}
    real_lock = session_service._CHAT_STATE_LOCK
    original_ledger = session_service._session_ledger_visible_messages
    original_normalize = session_service._normalize_conversation

    class HoldRecorder:
        def __enter__(self):
            ident = threading.get_ident()
            depth = lock_depth.get(ident, 0)
            if depth == 0:
                lock_started_at[ident] = time.perf_counter()
                if ident == delete_ident["value"]:
                    entered_lock.set()
            lock_depth[ident] = depth + 1
            return real_lock.__enter__()

        def __exit__(self, exc_type, exc, tb):
            ident = threading.get_ident()
            depth = lock_depth.get(ident, 1) - 1
            if depth <= 0:
                lock_depth.pop(ident, None)
                started = lock_started_at.pop(ident, time.perf_counter())
                lock_holds_ms.setdefault(ident, []).append((time.perf_counter() - started) * 1000)
            else:
                lock_depth[ident] = depth
            return real_lock.__exit__(exc_type, exc, tb)

    def _locked() -> bool:
        return lock_depth.get(threading.get_ident(), 0) > 0

    def slow_ledger(session_id: str):
        if _locked() and threading.get_ident() == delete_ident["value"]:
            journal_calls_while_locked.append("ledger")
            time.sleep(0.8)
        return original_ledger(session_id)

    def slow_normalize(*args, **kwargs):
        if _locked() and threading.get_ident() == delete_ident["value"]:
            journal_calls_while_locked.append("normalize")
            time.sleep(0.8)
        return original_normalize(*args, **kwargs)

    monkeypatch.setattr(session_service, "_CHAT_STATE_LOCK", HoldRecorder())
    monkeypatch.setattr(session_service, "_session_ledger_visible_messages", slow_ledger)
    monkeypatch.setattr(session_service, "_normalize_conversation", slow_normalize)

    result_box: dict[str, object] = {}

    def run_delete():
        delete_ident["value"] = threading.get_ident()
        result_box["result"] = session_service._delete_chat_session_state("session-delete")

    worker = threading.Thread(target=run_delete, name="session-delete-lock-test")
    worker.start()
    assert entered_lock.wait(timeout=5)

    started = time.perf_counter()
    detail = session_service.get_session_detail("session-keep", message_limit=0, transcript_scope="none")
    detail_ms = (time.perf_counter() - started) * 1000
    worker.join(timeout=10)
    assert worker.is_alive() is False

    result = result_box["result"]
    assert isinstance(result, dict)
    assert result.get("nextActiveSessionId") == "session-keep"
    assert detail is not None
    assert str(detail.get("id") or "") == "session-keep"
    assert journal_calls_while_locked == []
    delete_holds = lock_holds_ms.get(delete_ident["value"]) or []
    assert delete_holds, "delete should enter _CHAT_STATE_LOCK"
    assert max(delete_holds) < 400, (
        f"delete lock hold {delete_holds} must stay off journal replay; sibling detail {detail_ms:.0f}ms"
    )


def test_delete_waits_out_submit_admission_window_then_refuses_busy(tmp_path, monkeypatch):
    """G4 (chat-fix2 R4): delete must not slip past a submit admission window.

    Submit holds the per-session admission lock from its busy check through
    running registration and the initial journal markers. A delete issued
    inside that window must park on the same lock and then refuse as busy
    instead of removing the row the admitted turn is about to register into.
    """
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_two_sessions(tmp_path)

    session_id = "session-delete"
    admit_lock = session_service._session_submit_admit_lock(session_id)
    admit_lock.acquire()
    delete_started = threading.Event()
    result_box: dict[str, object] = {}

    def run_delete():
        delete_started.set()
        try:
            result_box["result"] = session_service._delete_chat_session_state(session_id)
        except BaseException as exc:  # noqa: BLE001 - forwarded to assertions below
            result_box["error"] = exc

    deleter = threading.Thread(target=run_delete, name="session-delete-admit-race")
    deleter.start()
    assert delete_started.wait(timeout=5)
    time.sleep(0.1)  # let the delete park on the admission lock; outcome is order-independent
    # The submit window closes with the turn registered as running.
    session_service._set_session_running(session_id, True, turn_id="turn-delete-race")
    admit_lock.release()
    deleter.join(timeout=10)
    assert deleter.is_alive() is False
    try:
        assert isinstance(result_box.get("error"), session_service.SessionBusyError)
        assert "result" not in result_box

        # The refused delete must leave the row in place with no tombstone, so
        # the admitted turn never writes into an intentionally deleted session.
        assert (
            session_service.load_session_chat_state(session_service.PROJECT_ROOT, session_id)
            is not None
        )
        assert not session_service._is_session_workspace_intentionally_deleted(session_id)
    finally:
        session_service._set_session_running(session_id, False)


def test_delete_completion_leaves_tombstone_that_blocks_admitted_resubmit(tmp_path, monkeypatch):
    """G4 (chat-fix2 R4): a submit unblocked after delete must refuse, not resurrect.

    Delete keeps the admission lock until the tombstone is written, so an
    admission parked behind it re-reads state after the lock, finds the
    tombstone (materialize refuses tombstoned sessions) and fails instead of
    resurrecting the deleted session from the Agent directory.
    """
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_two_sessions(tmp_path)

    session_id = "session-delete"
    result = session_service._delete_chat_session_state(session_id)
    assert result.get("nextActiveSessionId") == "session-keep"
    assert session_service._is_session_workspace_intentionally_deleted(session_id)

    # Simulate the submit side re-reading under the admission lock, the way
    # submit_session_message does between admit acquire and running flag.
    admit_lock = session_service._session_submit_admit_lock(session_id)
    with admit_lock:
        assert session_service.load_session_chat_state(session_service.PROJECT_ROOT, session_id) is None
        assert not session_service._ensure_agent_directory_conversation_materialized(
            session_id,
            source="test_deleted_admission_recheck",
        )
        with pytest.raises(session_service.SessionNotFoundError):
            session_service._ensure_session_mutable(session_id)
