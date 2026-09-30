from __future__ import annotations

import json
import logging

from core.runtime_manager.work_run_store import active_work_payload_blocks_lifecycle, WorkRunStore
from core.web.services import session_service
from core.web.services.session import read_health
from core.web.services.session.turn_diagnostics import (
    _active_session_work_run_statuses,
    list_active_session_work_runs,
    load_chat_turn_work_run_summary,
)


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
        raise RuntimeError("snapshot read failed")

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


def test_terminal_work_run_status_is_not_revived_by_late_touch(monkeypatch, tmp_path) -> None:
    """晚到的 touch/心跳（事件线程）不得把终态 work-run 复活为 running 或清空 finishedAt。"""
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._persist_chat_turn_work_run(
        session_id="session-done",
        turn_id="turn-terminal",
        status="completed",
        summary="done",
        finished_at="2026-09-20T00:00:00Z",
    )
    # 模拟跨线程晚到的心跳：终态之后才落盘的 running touch。
    session_service._persist_chat_turn_work_run(
        session_id="session-done",
        turn_id="turn-terminal",
        status="running",
    )

    snapshot = session_service._WORK_RUN_STORE.load_snapshot("chat_turn", "turn-terminal") or {}
    assert snapshot.get("status") == "completed"
    assert str(snapshot.get("finishedAt") or "").strip() != ""


def _isolated_work_run_store(monkeypatch, tmp_path) -> WorkRunStore:
    store = WorkRunStore(root=tmp_path / "work-runs")
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", store)
    return store


def _forge_running_session(session_id: str, turn_id: str, *, leases: list[str] | None = None) -> None:
    with session_service._RUNNING_SESSIONS_LOCK:
        session_service._RUNNING_SESSION_IDS.add(session_id)
        session_service._SESSION_ACTIVE_TURN_IDS[session_id] = turn_id
        session_service._SESSION_ACTIVE_TURN_LEASES[session_id] = list(leases or ["readonly_chat"])


def _drop_running_session(session_id: str) -> None:
    with session_service._RUNNING_SESSIONS_LOCK:
        session_service._RUNNING_SESSION_IDS.discard(session_id)
        session_service._SESSION_ACTIVE_TURN_IDS.pop(session_id, None)
        session_service._SESSION_ACTIVE_TURN_LEASES.pop(session_id, None)


def test_residual_running_set_entry_without_evidence_is_not_projected_as_running(
    monkeypatch,
    tmp_path,
) -> None:
    """残留 running 集合（worker 异常路径）在无快照、无 turn control 佐证时，
    不得被硬投影成阻塞生命周期的 running item。"""
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _isolated_work_run_store(monkeypatch, tmp_path)
    _forge_running_session("session-ghost", "turn-ghost")
    try:
        statuses = _active_session_work_run_statuses(["session-ghost"])
        runs = list_active_session_work_runs(reconcile=False)
    finally:
        _drop_running_session("session-ghost")

    assert statuses == {}
    assert all(item["sessionId"] != "session-ghost" for item in runs)
    # 重启护栏口径：残影不会制造任何阻塞项。
    assert not any(
        active_work_payload_blocks_lifecycle(item)
        for item in runs
        if isinstance(item, dict)
    )


def test_running_set_entry_without_snapshot_keeps_running_via_turn_control(
    monkeypatch,
    tmp_path,
) -> None:
    """无快照但活的 turn control 仍持有该 turn 时，真 running 不得丢失；
    已请求停止的读作 stopping。"""
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _isolated_work_run_store(monkeypatch, tmp_path)
    _forge_running_session("session-live", "turn-1")
    control = session_service.SessionTurnControl(session_id="session-live", turn_id="turn-1")
    with session_service._SESSION_TURN_CONTROLS_LOCK:
        session_service._SESSION_TURN_CONTROLS["session-live"] = control
    try:
        statuses = _active_session_work_run_statuses(["session-live"])
        assert statuses == {"session-live": "running"}
        control.request_stop("user")
        statuses = _active_session_work_run_statuses(["session-live"])
        assert statuses == {"session-live": "stopping"}
    finally:
        with session_service._SESSION_TURN_CONTROLS_LOCK:
            session_service._SESSION_TURN_CONTROLS.pop("session-live", None)
        _drop_running_session("session-live")


def test_terminal_snapshot_while_session_marked_running_projects_truth_with_finished_at(
    monkeypatch,
    tmp_path,
) -> None:
    """快照优先：会话仍在 running 集合但快照已终态时，按快照投影并携带
    finishedAt，不再是无 finishedAt 的阻塞形态。"""
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    store = _isolated_work_run_store(monkeypatch, tmp_path)
    # 直接向隔离 store 写终态快照，绕开 facade 依赖。
    store.ensure_kind_dirs("chat_turn")
    (store.runs_dir("chat_turn") / "turn-done.json").write_text(
        json.dumps(
            {
                "runId": "turn-done",
                "runKind": "chat_turn",
                "sessionId": "session-done",
                "status": "completed",
                "currentPhase": "completed",
                "startedAt": "2026-09-30T00:00:00+00:00",
                "updatedAt": "2026-09-30T00:00:10+00:00",
                "finishedAt": "2026-09-30T00:00:10+00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store.save_run_index("chat_turn", latest_run_id="turn-done", emit_event=False)
    _forge_running_session("session-done", "turn-done")
    try:
        runs = list_active_session_work_runs(reconcile=False)
    finally:
        _drop_running_session("session-done")

    live = next(item for item in runs if item["sessionId"] == "session-done")
    assert live["status"] == "completed"
    assert live["finishedAt"] == "2026-09-30T00:00:10+00:00"
    assert not active_work_payload_blocks_lifecycle(live)


def test_active_summary_fallback_requires_current_active_session(
    monkeypatch,
    tmp_path,
) -> None:
    """index 无 active 快照时，内存兜底项只有属于当前 active 会话才能占据
    workRuns.active.chat_turn，否则置空，不得把别的会话的 run 当 active。"""
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _isolated_work_run_store(monkeypatch, tmp_path)
    _forge_running_session("session-other", "turn-other")
    control = session_service.SessionTurnControl(session_id="session-other", turn_id="turn-other")
    with session_service._SESSION_TURN_CONTROLS_LOCK:
        session_service._SESSION_TURN_CONTROLS["session-other"] = control
    try:
        monkeypatch.setattr(session_service, "load_active_conversation_id", lambda _root: "")
        summary = load_chat_turn_work_run_summary()
        assert summary["active"] is None
        assert [item["sessionId"] for item in summary["activeItems"]] == ["session-other"]

        monkeypatch.setattr(session_service, "load_active_conversation_id", lambda _root: "session-other")
        summary = load_chat_turn_work_run_summary()
        assert summary["active"] is not None
        assert summary["active"]["sessionId"] == "session-other"
        assert summary["active"]["runId"] == "turn-other"
    finally:
        with session_service._SESSION_TURN_CONTROLS_LOCK:
            session_service._SESSION_TURN_CONTROLS.pop("session-other", None)
        _drop_running_session("session-other")
