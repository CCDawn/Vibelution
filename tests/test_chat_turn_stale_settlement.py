"""C1: chat_turn work-run settlement after worker death or tool-timeout hang."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.web.services import session_service
from core.web.services.session import turn_diagnostics


@pytest.fixture(autouse=True)
def _reset_work_run_heartbeat_state():
    turn_diagnostics._CHAT_TURN_WORK_RUN_HEARTBEAT_STATE.clear()
    yield
    turn_diagnostics._CHAT_TURN_WORK_RUN_HEARTBEAT_STATE.clear()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def test_chat_turn_hang_reason_worker_gone(monkeypatch):
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    payload = {
        "runId": "turn-1",
        "sessionId": "session-a",
        "status": "running",
        "updatedAt": _iso(now - timedelta(minutes=10)),
        "startedAt": _iso(now - timedelta(minutes=12)),
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


def test_chat_turn_hang_reason_worker_gone_young_record_is_spared(monkeypatch):
    """A young unowned snapshot is a registration-visibility gap, not a dead worker.

    Regression for the 2026-09-02 stage-turn incident: live turns were settled
    as worker_gone 22-31s into flight because the process-local running
    registration was momentarily absent while the worker kept streaming.
    """
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
        == ""
    )
    # Past the grace boundary the settle becomes legal again.
    payload["updatedAt"] = _iso(now - timedelta(seconds=121))
    payload["startedAt"] = _iso(now - timedelta(seconds=200))
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
        "updatedAt": _iso(now - timedelta(seconds=200)),
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
    # A real completed tool/assistant response after the timeout is progress.
    payload["updatedAt"] = _iso(now - timedelta(seconds=30))
    assert turn_diagnostics._chat_turn_work_run_hang_reason(
        payload, now=now, worker_owns_turn=True) == ""
    payload["updatedAt"] = _iso(now - timedelta(seconds=200))
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
            "updatedAt": _iso(now - timedelta(seconds=200)),
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
            "startedAt": _iso(now - timedelta(minutes=30)),
            "updatedAt": _iso(now - timedelta(minutes=20)),
            "finishedAt": "",
        },
        active_run_id=turn_id,
    )
    # No in-memory worker ownership and no live turn control: a true orphan
    # whose registration disappeared well beyond the worker_gone grace.
    session_service._set_session_running("session-b", False)

    settled = turn_diagnostics.reconcile_stale_chat_turn_work_runs(now=now)
    assert any(item.get("runId") == turn_id for item in settled)
    latest = session_service._WORK_RUN_STORE.load_snapshot("chat_turn", turn_id)
    assert latest is not None
    assert latest["status"] == "stopped"
    assert str(latest.get("finishedAt") or "").strip()


def _install_tmp_work_run_store(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    from core.runtime_manager import work_run_store as work_run_store_module

    monkeypatch.setattr(work_run_store_module, "WORK_RUNS_DIR", tmp_path / "work_runs")
    monkeypatch.setattr(
        session_service,
        "_WORK_RUN_STORE",
        work_run_store_module.WorkRunStore(root=tmp_path / "work_runs"),
    )


def _persist_running_turn(turn_id: str, session_id: str, *, started_at: datetime, updated_at: datetime) -> None:
    session_service._WORK_RUN_STORE.persist_snapshot(
        "chat_turn",
        {
            "runId": turn_id,
            "runKind": "chat_turn",
            "sessionId": session_id,
            "status": "running",
            "currentPhase": "running",
            "startedAt": _iso(started_at),
            "updatedAt": _iso(updated_at),
            "finishedAt": "",
        },
        active_run_id=turn_id,
    )


def test_reconcile_young_unowned_snapshot_is_not_settled(tmp_path, monkeypatch):
    """Work run running + session unregistered + young record → no mis-kill."""

    _install_tmp_work_run_store(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    turn_id = "session-young-orphan-turn"
    _persist_running_turn(turn_id, "session-young-orphan", started_at=now - timedelta(seconds=40), updated_at=now - timedelta(seconds=30))
    session_service._set_session_running("session-young-orphan", False)

    settled = turn_diagnostics.reconcile_stale_chat_turn_work_runs(now=now)
    assert settled == []
    latest = session_service._WORK_RUN_STORE.load_snapshot("chat_turn", turn_id)
    assert latest is not None
    assert latest["status"] == "running"
    assert not str(latest.get("finishedAt") or "").strip()


def test_reconcile_mismatched_registration_young_snapshot_is_not_settled(tmp_path, monkeypatch):
    """Work run running + active turn id points elsewhere + young record → no mis-kill."""

    _install_tmp_work_run_store(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    turn_id = "session-mismatch-turn"
    _persist_running_turn(turn_id, "session-mismatch", started_at=now - timedelta(seconds=50), updated_at=now - timedelta(seconds=45))
    # Registration exists but names a different turn: worker_owns_turn=False.
    session_service._set_session_running("session-mismatch", True, turn_id="session-mismatch-otherturn")

    settled = turn_diagnostics.reconcile_stale_chat_turn_work_runs(now=now)
    assert settled == []
    latest = session_service._WORK_RUN_STORE.load_snapshot("chat_turn", turn_id)
    assert latest is not None
    assert latest["status"] == "running"
    session_service._set_session_running("session-mismatch", False)


def test_reconcile_revives_lost_registration_via_turn_control(tmp_path, monkeypatch):
    """Live turn control still owning the run proves the worker is alive.

    The reconcile must re-arm the running registration instead of settling, so
    the in-flight stage turn keeps its identity for completion pollers.
    """

    _install_tmp_work_run_store(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    turn_id = "session-revive-turn"
    session_id = "session-revive"
    _persist_running_turn(turn_id, session_id, started_at=now - timedelta(seconds=40), updated_at=now - timedelta(seconds=35))
    # Worker alive but registration lost (visibility gap): control still owns it.
    session_service._create_session_turn_control(session_id, turn_id=turn_id)
    session_service._set_session_running(session_id, False)
    try:
        settled = turn_diagnostics.reconcile_stale_chat_turn_work_runs(now=now)
        assert settled == []
        latest = session_service._WORK_RUN_STORE.load_snapshot("chat_turn", turn_id)
        assert latest is not None
        assert latest["status"] == "running"
        # The registration was healed, so the completion snapshot is live again.
        assert session_service._is_session_running(session_id) is True
        with session_service._RUNNING_SESSIONS_LOCK:
            assert session_service._SESSION_ACTIVE_TURN_IDS.get(session_id) == turn_id
    finally:
        session_service._set_session_running(session_id, False)
        with session_service._SESSION_TURN_CONTROLS_LOCK:
            session_service._SESSION_TURN_CONTROLS.pop(session_id, None)


def test_reconcile_stop_requested_control_does_not_revive_young_orphan(tmp_path, monkeypatch):
    """A stop-requested control must not masquerade as liveness ownership.

    With no other liveness signal the young-record grace still protects the
    run, and once the snapshot ages past the grace it settles normally.
    """

    _install_tmp_work_run_store(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    turn_id = "session-stopreq-turn"
    session_id = "session-stopreq"
    _persist_running_turn(turn_id, session_id, started_at=now - timedelta(seconds=40), updated_at=now - timedelta(seconds=35))
    control = session_service._create_session_turn_control(session_id, turn_id=turn_id)
    control.request_stop("operator requested")
    session_service._set_session_running(session_id, False)
    try:
        # Young: spared by the grace window (cooperative stop in progress).
        assert turn_diagnostics.reconcile_stale_chat_turn_work_runs(now=now) == []
        latest = session_service._WORK_RUN_STORE.load_snapshot("chat_turn", turn_id)
        assert latest is not None
        assert latest["status"] == "running"
        # Aged past the grace: settle proceeds.
        aged = now + timedelta(minutes=10)
        settled = turn_diagnostics.reconcile_stale_chat_turn_work_runs(now=aged)
        assert any(item.get("runId") == turn_id and item.get("reason") == "worker_gone" for item in settled)
    finally:
        session_service._set_session_running(session_id, False)
        with session_service._SESSION_TURN_CONTROLS_LOCK:
            session_service._SESSION_TURN_CONTROLS.pop(session_id, None)


def test_chat_turn_hang_reason_queued_owner_not_absolute_stale():
    """Queue wait must not be read as a hung turn.

    A queued snapshot's updatedAt freezes at enqueue time, so wall-clock age
    measures the scheduler backlog, not turn progress: absolute_stale must not
    fire for a turn the queue still owns.
    """
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    payload = {
        "runId": "turn-queued",
        "sessionId": "session-queued",
        "status": "queued",
        "startedAt": _iso(now - timedelta(hours=2)),
        "updatedAt": _iso(now - timedelta(hours=2)),
        "finishedAt": "",
    }
    assert (
        turn_diagnostics._chat_turn_work_run_hang_reason(
            payload,
            now=now,
            worker_owns_turn=True,
            queued_owner=True,
        )
        == ""
    )
    # The same aged snapshot without the queued signal still settles.
    assert (
        turn_diagnostics._chat_turn_work_run_hang_reason(
            payload,
            now=now,
            worker_owns_turn=True,
        )
        == "absolute_stale"
    )


def test_reconcile_spares_queued_scheduler_turn_from_absolute_stale(tmp_path, monkeypatch):
    """A queued snapshot still owned by the live scheduler is never settled."""

    _install_tmp_work_run_store(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    turn_id = "session-queued-turn"
    session_id = "session-queued"
    _persist_running_turn(
        turn_id,
        session_id,
        started_at=now - timedelta(hours=2),
        updated_at=now - timedelta(hours=2),
    )
    session_service._set_session_running(session_id, False)

    class _QueuedSchedulerStub:
        def queued_session_turn_ids(self):
            return {(session_id, turn_id)}

        def clear(self):
            # conftest teardown calls clear() on the facade scheduler; the
            # stub may still be installed when that teardown runs.
            return None

    monkeypatch.setattr(session_service, "_SESSION_TURN_SCHEDULER", _QueuedSchedulerStub())

    settled = turn_diagnostics.reconcile_stale_chat_turn_work_runs(now=now)
    assert settled == []
    latest = session_service._WORK_RUN_STORE.load_snapshot("chat_turn", turn_id)
    assert latest is not None
    assert latest["status"] == "running"
    assert not str(latest.get("finishedAt") or "").strip()


def test_heartbeat_refreshes_updated_at_and_blocks_absolute_stale(tmp_path, monkeypatch):
    """Live worker heartbeats keep absolute_stale from killing a working turn.

    With a frozen updatedAt the aged running snapshot classifies as
    absolute_stale; after the worker heartbeat refreshes it the same snapshot
    is spared, while a wedged worker (no heartbeat for 30 minutes) is still
    killed by the unchanged ceiling.
    """

    _install_tmp_work_run_store(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    turn_id = "session-heartbeat-turn"
    session_id = "session-heartbeat"
    _persist_running_turn(
        turn_id,
        session_id,
        started_at=now - timedelta(minutes=40),
        updated_at=now - timedelta(minutes=31),
    )
    session_service._set_session_running(session_id, True, turn_id=turn_id)
    try:
        payload = session_service._WORK_RUN_STORE.load_snapshot("chat_turn", turn_id)
        assert turn_diagnostics._chat_turn_work_run_hang_reason(
            payload,
            now=now,
            worker_owns_turn=True,
        ) == "absolute_stale"

        assert turn_diagnostics._heartbeat_chat_turn_work_run(
            session_id=session_id,
            turn_id=turn_id,
            stage="worker_loop",
        ) is True
        heartbeat_at = datetime.now(timezone.utc)
        payload = session_service._WORK_RUN_STORE.load_snapshot("chat_turn", turn_id)
        refreshed = turn_diagnostics._parse_work_run_timestamp(payload.get("updatedAt") or "")
        assert refreshed is not None
        assert (heartbeat_at - refreshed).total_seconds() < 60
        assert turn_diagnostics._chat_turn_work_run_hang_reason(
            payload,
            now=heartbeat_at,
            worker_owns_turn=True,
        ) == ""

        stale_payload = dict(payload)
        stale_payload["updatedAt"] = _iso(heartbeat_at - timedelta(minutes=31))
        assert turn_diagnostics._chat_turn_work_run_hang_reason(
            stale_payload,
            now=heartbeat_at + timedelta(minutes=31),
            worker_owns_turn=True,
        ) == "absolute_stale"
    finally:
        session_service._set_session_running(session_id, False)


def test_heartbeat_throttles_repeat_writes(tmp_path, monkeypatch):
    """Repeat heartbeats inside the interval cost no durable write."""

    _install_tmp_work_run_store(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    turn_id = "session-throttle-turn"
    session_id = "session-throttle"
    _persist_running_turn(turn_id, session_id, started_at=now, updated_at=now)
    touches = {"count": 0}
    original_touch = session_service._touch_chat_turn_work_run

    def counting_touch(**kwargs):
        touches["count"] += 1
        return original_touch(**kwargs)

    monkeypatch.setattr(session_service, "_touch_chat_turn_work_run", counting_touch)

    first = turn_diagnostics._heartbeat_chat_turn_work_run(
        session_id=session_id, turn_id=turn_id, stage="worker_loop"
    )
    repeat = turn_diagnostics._heartbeat_chat_turn_work_run(
        session_id=session_id, turn_id=turn_id, stage="worker_loop"
    )

    assert first is True
    assert repeat is False
    assert touches["count"] == 1


def test_reconcile_settle_appends_journal_interruption(tmp_path, monkeypatch):
    """Forced settlement closes the journal's open turn in the same pass."""

    _install_tmp_work_run_store(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    turn_id = "session-journal-turn"
    session_id = "session-journal"
    _persist_running_turn(
        turn_id,
        session_id,
        started_at=now - timedelta(minutes=30),
        updated_at=now - timedelta(minutes=20),
    )
    session_service._set_session_running(session_id, False)

    settled = turn_diagnostics.reconcile_stale_chat_turn_work_runs(now=now)
    assert any(item.get("runId") == turn_id for item in settled)

    events = session_service.load_conversation_events(session_service.PROJECT_ROOT, session_id)
    interrupted = [
        event
        for event in events
        if event.turn_id == turn_id and event.event_type == session_service.EVENT_TURN_INTERRUPTED
    ]
    assert interrupted
    assert (interrupted[-1].payload or {}).get("reason") == "stale_work_run_worker_gone"
