"""P0 regression tests: chat round orphan mis-kill loop + speaker watchdog.

Covers the four fixes that stop meeting group chats from looping:

A. ``_fail_chat_room_round`` keeps the in-memory round control record until
   the durable terminal state is written (no more "running without a
   controller" zombie rounds).
B. Reconcile exempts running rounds whose WorkRun heartbeat is fresh; only
   expired/missing heartbeats close as ``missing_process_controller``.
C. ``ChatRoomStore`` distinguishes "state file missing" from "state file
   unreadable" instead of swallowing read failures as an empty state.
D. Every speaker call is bounded: a hung runner hits the per-call watchdog
   and the round closes with the failed/stopped message persisted.
"""

import json
import time

import pytest

from core.chatroom import store as chat_room_store
from core.runtime_manager import work_run_store
from core.web.services import chat_room_service, session_service

from tests.test_chat_room_service import _seed_chat_sessions


def _seed_room_with_round(tmp_path, monkeypatch, *, title, round_id, round_status="running"):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", tmp_path / "work_runs")
    room = chat_room_service.create_chat_room(title=title, participant_session_ids=["session-alpha"])
    state = chat_room_service._store().load()
    stored_room = next(item for item in state["rooms"] if item["roomId"] == room["roomId"])
    stored_room["status"] = round_status
    stored_room["activeRoundId"] = round_id
    stored_round = {
        "roundId": round_id,
        "roomId": room["roomId"],
        "topic": title,
        "mode": "round_robin",
        "purpose": "discussion",
        "config": {},
        "status": round_status,
        "speakerOrder": ["session-session-alpha"],
        "messages": [],
        "summary": "",
        "startedAt": "2026-09-01T00:00:00+00:00",
        "updatedAt": "2026-09-01T00:00:00+00:00",
        "finishedAt": "",
    }
    stored_room["rounds"] = [stored_round]
    chat_room_service._store().save(state)
    return stored_room, stored_round


def _reloaded_room(room_id):
    return next(
        item for item in chat_room_service._store().load()["rooms"] if item["roomId"] == room_id
    )


def _capture_scene_events(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        chat_room_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded.append((args, kwargs)) or {"accepted": True},
    )
    return recorded


def _exempt_events(recorded):
    return [
        item
        for item in recorded
        if item[0][:3] == ("chat_room", "reconcile", "chat_room.round.orphan_heartbeat_exempt")
    ]


# ---------------------------------------------------------------------------
# A. fail-path finalization order
# ---------------------------------------------------------------------------


def test_fail_chat_room_round_keeps_control_when_store_save_fails(tmp_path, monkeypatch):
    stored_room, stored_round = _seed_room_with_round(
        tmp_path, monkeypatch, title="收口失败保留控制", round_id="round-fail-locked"
    )
    round_id = stored_round["roundId"]
    chat_room_service._create_chat_room_round_control(stored_room["roomId"], round_id)
    monkeypatch.setattr(chat_room_service, "_publish_chat_room_detail_snapshot", lambda _room_id: None)

    def locked_atomic_write(_path, _payload):
        raise PermissionError("chat_rooms.json locked by concurrent readers")

    monkeypatch.setattr(chat_room_store, "_atomic_write_json", locked_atomic_write)

    with pytest.raises(PermissionError):
        chat_room_service._fail_chat_room_round(
            stored_room["roomId"],
            round_id,
            stored_room,
            stored_round,
            RuntimeError("boom"),
            lang="zh",
        )

    # The control record must survive a failed store finalization: popping it
    # early is what used to create "running without a controller" zombie
    # rounds that reconcile then mis-killed as orphans.
    assert chat_room_service._chat_room_round_has_process_control(round_id)
    reloaded_room = _reloaded_room(stored_room["roomId"])
    assert reloaded_room["status"] == "running"
    assert reloaded_room["activeRoundId"] == round_id
    assert reloaded_room["rounds"][-1]["status"] == "running"

    chat_room_service._clear_chat_room_round_control(round_id)


def test_fail_chat_room_round_clears_control_after_durable_failed_state(tmp_path, monkeypatch):
    stored_room, stored_round = _seed_room_with_round(
        tmp_path, monkeypatch, title="收口成功清除控制", round_id="round-fail-durable"
    )
    round_id = stored_round["roundId"]
    chat_room_service._create_chat_room_round_control(stored_room["roomId"], round_id)
    monkeypatch.setattr(chat_room_service, "_publish_chat_room_detail_snapshot", lambda _room_id: None)
    monkeypatch.setattr(chat_room_service, "_record_room_event", lambda *args, **kwargs: None)

    chat_room_service._fail_chat_room_round(
        stored_room["roomId"],
        round_id,
        stored_room,
        stored_round,
        RuntimeError("boom"),
        lang="zh",
    )

    # Store terminal state first; the control record is dropped only after.
    assert not chat_room_service._chat_room_round_has_process_control(round_id)
    reloaded_room = _reloaded_room(stored_room["roomId"])
    assert reloaded_room["status"] == "failed"
    assert reloaded_room["activeRoundId"] == ""
    assert reloaded_room["rounds"][-1]["status"] == "failed"
    assert reloaded_room["rounds"][-1]["finishedAt"]


def test_fail_chat_room_round_clears_control_for_already_terminal_round(tmp_path, monkeypatch):
    stored_room, stored_round = _seed_room_with_round(
        tmp_path,
        monkeypatch,
        title="已终态失败清除控制",
        round_id="round-fail-terminal",
        round_status="stopped",
    )
    round_id = stored_round["roundId"]
    chat_room_service._create_chat_room_round_control(stored_room["roomId"], round_id)
    monkeypatch.setattr(chat_room_service, "_publish_chat_room_detail_snapshot", lambda _room_id: None)

    chat_room_service._fail_chat_room_round(
        stored_room["roomId"],
        round_id,
        stored_room,
        stored_round,
        RuntimeError("already terminal"),
        lang="zh",
    )

    assert not chat_room_service._chat_room_round_has_process_control(round_id)


# ---------------------------------------------------------------------------
# B. heartbeat-aware reconcile
# ---------------------------------------------------------------------------


def _persist_running_work_run(stored_room, round_id, *, updated_at):
    chat_room_service._work_run_store().persist_snapshot(
        chat_room_service.RUN_KIND,
        {
            "runId": round_id,
            "runKind": chat_room_service.RUN_KIND,
            "roomId": stored_room["roomId"],
            "roundId": round_id,
            "status": "running",
            "currentPhase": "running",
            "summary": "challenge_meeting_speaker_heartbeat",
            "startedAt": "2026-09-01T00:00:00+00:00",
            "updatedAt": updated_at,
            "finishedAt": "",
        },
        active_run_id=round_id,
    )


def test_reconcile_exempt_running_round_with_fresh_work_run_heartbeat(tmp_path, monkeypatch):
    stored_room, stored_round = _seed_room_with_round(
        tmp_path, monkeypatch, title="心跳新鲜豁免", round_id="round-heartbeat-fresh"
    )
    round_id = stored_round["roundId"]
    # No in-process control record on purpose: this is exactly the zombie
    # state the buggy fail path used to leave behind.
    assert not chat_room_service._chat_room_round_has_process_control(round_id)
    _persist_running_work_run(stored_room, round_id, updated_at=chat_room_service.utc_now_iso())
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_RECONCILE_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(chat_room_service, "_record_room_event", lambda *args, **kwargs: None)
    recorded = _capture_scene_events(monkeypatch)

    reconciled = chat_room_service._reconcile_chat_room_round_state()

    assert reconciled == []
    reloaded_room = _reloaded_room(stored_room["roomId"])
    assert reloaded_room["status"] == "running"
    assert reloaded_room["activeRoundId"] == round_id
    assert reloaded_room["rounds"][-1]["status"] == "running"
    assert len(_exempt_events(recorded)) == 1


def test_reconcile_closes_round_when_work_run_heartbeat_expired(tmp_path, monkeypatch):
    stored_room, stored_round = _seed_room_with_round(
        tmp_path, monkeypatch, title="心跳过期收口", round_id="round-heartbeat-stale"
    )
    round_id = stored_round["roundId"]
    _persist_running_work_run(stored_room, round_id, updated_at="2026-09-01T00:00:00+00:00")
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_RECONCILE_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(chat_room_service, "_record_room_event", lambda *args, **kwargs: None)

    reconciled = chat_room_service._reconcile_chat_room_round_state()

    assert len(reconciled) == 1
    assert reconciled[0]["reconciliationSource"] == "missing_process_controller"
    reloaded_room = _reloaded_room(stored_room["roomId"])
    assert reloaded_room["status"] == "ready"
    assert reloaded_room["activeRoundId"] == ""
    assert reloaded_room["rounds"][-1]["status"] == "stopped"


def test_reconcile_closes_round_without_work_run_snapshot(tmp_path, monkeypatch):
    stored_room, stored_round = _seed_room_with_round(
        tmp_path, monkeypatch, title="无工作运行快照收口", round_id="round-heartbeat-missing"
    )
    round_id = stored_round["roundId"]
    assert chat_room_service._work_run_store().load_snapshot(chat_room_service.RUN_KIND, round_id) is None
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_RECONCILE_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(chat_room_service, "_record_room_event", lambda *args, **kwargs: None)

    reconciled = chat_room_service._reconcile_chat_room_round_state()

    assert len(reconciled) == 1
    assert reconciled[0]["reconciliationSource"] == "missing_process_controller"
    assert _reloaded_room(stored_room["roomId"])["rounds"][-1]["status"] == "stopped"


def test_reconcile_reconfirm_exempt_round_whose_heartbeat_turned_fresh(tmp_path, monkeypatch):
    stored_room, stored_round = _seed_room_with_round(
        tmp_path, monkeypatch, title="二次确认心跳恢复豁免", round_id="round-heartbeat-reconfirm"
    )
    round_id = stored_round["roundId"]
    stale_snapshot = {
        "runId": round_id,
        "runKind": chat_room_service.RUN_KIND,
        "roomId": stored_room["roomId"],
        "roundId": round_id,
        "status": "running",
        "currentPhase": "running",
        "startedAt": "2026-09-01T00:00:00+00:00",
        "updatedAt": "2026-09-01T00:00:00+00:00",
        "finishedAt": "",
    }
    fresh_snapshot = dict(stale_snapshot)
    fresh_snapshot["updatedAt"] = chat_room_service.utc_now_iso()

    class TwoPhaseWorkRunStore:
        def __init__(self):
            self.calls = 0

        def load_snapshot(self, _run_kind, _round_id):
            snapshot = fresh_snapshot if self.calls else stale_snapshot
            self.calls += 1
            return dict(snapshot)

        def persist_snapshot(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(chat_room_service, "_work_run_store", lambda: TwoPhaseWorkRunStore())
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_RECONCILE_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(chat_room_service, "_record_room_event", lambda *args, **kwargs: None)
    recorded = _capture_scene_events(monkeypatch)

    reconciled = chat_room_service._reconcile_chat_room_round_state()

    # First pass saw the stale heartbeat; the reconfirm pass re-read the
    # WorkRun snapshot and the renewed heartbeat exempted the live round.
    assert reconciled == []
    assert _reloaded_room(stored_room["roomId"])["rounds"][-1]["status"] == "running"
    assert [item[1]["fields"].get("stage") for item in _exempt_events(recorded)] == ["reconfirm"]


# ---------------------------------------------------------------------------
# C. store contention semantics
# ---------------------------------------------------------------------------


def _write_state_file(store, payload):
    store.state_path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        # Raw text: used to seed corrupt state files.
        store.state_path.write_text(payload, encoding="utf-8")
        return
    store.state_path.write_text(json.dumps(payload), encoding="utf-8")


def test_chat_room_store_load_distinguishes_missing_from_unreadable(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_room_store, "READ_RETRY_TIMEOUT_SECONDS", 0.05)
    store = chat_room_store.ChatRoomStore(root=tmp_path)

    # A missing file keeps the empty-state contract.
    missing_store = chat_room_store.ChatRoomStore(root=tmp_path / "missing-root")
    assert missing_store.load() == chat_room_store.default_state()

    # Corrupt JSON must never masquerade as an empty store.
    _write_state_file(store, "{not valid json")
    with pytest.raises(chat_room_store.ChatRoomStoreReadError):
        store.load()

    # A valid JSON document that is not an object is corruption too.
    store.state_path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(chat_room_store.ChatRoomStoreReadError):
        store.load()

    # A readable store keeps serving its durable state.
    _write_state_file(store, {"version": 1, "rooms": [{"roomId": "room-a"}]})
    assert store.load()["rooms"][0]["roomId"] == "room-a"


def test_chat_room_store_load_raises_when_reads_stay_locked(tmp_path):
    store = chat_room_store.ChatRoomStore(root=tmp_path)
    _write_state_file(store, {"version": 1, "rooms": [{"roomId": "room-a"}]})

    class LockedPath:
        def read_text(self, encoding=None):
            raise PermissionError("locked by another handle")

    with pytest.raises(chat_room_store.ChatRoomStoreReadError):
        chat_room_store._read_state_object(LockedPath())


def test_chat_room_store_read_retries_transient_lock_then_succeeds(tmp_path):
    store = chat_room_store.ChatRoomStore(root=tmp_path)
    _write_state_file(store, {"version": 1, "rooms": [{"roomId": "room-a"}]})

    class FlakyPath:
        def __init__(self, real):
            self._real = real
            self.calls = 0

        def read_text(self, encoding=None):
            self.calls += 1
            if self.calls == 1:
                raise PermissionError("transient lock")
            return self._real.read_text(encoding=encoding)

    flaky = FlakyPath(store.state_path)
    payload = chat_room_store._read_state_object(flaky)
    assert payload["rooms"][0]["roomId"] == "room-a"
    assert flaky.calls == 2


def test_chat_room_store_save_raises_when_replace_locked_throughout(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_room_store, "WRITE_RETRY_TIMEOUT_SECONDS", 0.05)
    store = chat_room_store.ChatRoomStore(root=tmp_path)
    real_replace = chat_room_store.os.replace

    def always_locked_replace(source, target):
        raise PermissionError("target locked")

    monkeypatch.setattr(chat_room_store.os, "replace", always_locked_replace)
    try:
        with pytest.raises(PermissionError):
            store.save({"rooms": [{"roomId": "room-a"}]})
    finally:
        monkeypatch.setattr(chat_room_store.os, "replace", real_replace)
    # The failed save must not have left a truncated state file behind.
    assert not store.state_path.exists()


# ---------------------------------------------------------------------------
# D. single-speaker watchdog
# ---------------------------------------------------------------------------


def _watchdog_participant():
    return {
        "participantId": "session-alpha",
        "agentId": "agent-alpha",
        "agentCode": "A012",
        "sessionId": "session-alpha",
    }


def _watchdog_context(round_id, *, per_call_deadline_at_ms):
    return {
        "roundId": round_id,
        "speakerStartedAtMonotonic": chat_room_service._perf_counter(),
        chat_room_service._CHALLENGE_ROOM_PER_CALL_DEADLINE_CONTEXT_KEY: per_call_deadline_at_ms,
    }


def test_run_one_speaker_watchdog_times_out_hung_runner():
    context = _watchdog_context(
        "round-watchdog-unit",
        per_call_deadline_at_ms=int(time.time() * 1000) + 300,
    )

    def hung_runner(_participant, _prompt, _context):
        time.sleep(2.5)
        return {"status": "completed", "raw_output": "late", "summary": "late"}

    message = chat_room_service._run_one_speaker(_watchdog_participant(), "prompt", context, hung_runner)

    # The expired per-call fence turns the abandonment into a stopped speaker;
    # the watchdog detail stays auditable in errorType/error.
    assert message["status"] == "stopped"
    assert message["errorType"] == "SpeakerCallWatchdogTimeout"
    assert "per-call budget" in message["error"]
    assert message["summary"] == chat_room_service._CHALLENGE_ROOM_PER_CALL_STOP_REASON


def test_run_one_speaker_watchdog_keeps_runner_error_path():
    context = _watchdog_context(
        "round-watchdog-error",
        per_call_deadline_at_ms=int(time.time() * 1000) + 60_000,
    )

    def failing_runner(_participant, _prompt, _context):
        raise ValueError("provider exploded")

    message = chat_room_service._run_one_speaker(_watchdog_participant(), "prompt", context, failing_runner)

    assert message["status"] == "failed"
    assert message["errorType"] == "ValueError"
    assert "provider exploded" in message["summary"]


def test_execute_chat_room_round_closes_round_when_speaker_watchdog_times_out(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_RECONCILE_MIN_INTERVAL_SECONDS", 0.0)
    stored_room, stored_round = _seed_room_with_round(
        tmp_path, monkeypatch, title="看门狗超时收口", round_id="round-watchdog-e2e"
    )
    round_id = stored_round["roundId"]
    stored_round["config"] = {"perCallBudgetMs": 300}
    state = chat_room_service._store().load()
    persist_room = next(item for item in state["rooms"] if item["roomId"] == stored_room["roomId"])
    persist_room["rounds"][0]["config"] = {"perCallBudgetMs": 300}
    chat_room_service._store().save(state)
    chat_room_service._create_chat_room_round_control(stored_room["roomId"], round_id)
    monkeypatch.setattr(chat_room_service, "_record_room_event", lambda *args, **kwargs: None)

    def hung_runner(_participant, _prompt, _context):
        time.sleep(2.5)
        return {"status": "completed", "raw_output": "late", "summary": "late"}

    result = chat_room_service._execute_chat_room_round(
        stored_room["roomId"],
        round_id,
        stored_room,
        stored_round,
        [
            {
                "participantId": "session-alpha",
                "agentId": "agent-alpha",
                "agentCode": "A012",
                "sessionId": "session-alpha",
            }
        ],
        hung_runner,
        "zh",
    )

    assert result["activeRoundId"] == ""
    assert result["status"] == "failed"
    final_round = next(item for item in result["rounds"] if item["roundId"] == round_id)
    assert final_round["status"] == "failed"
    assert final_round["finishedAt"]
    message = final_round["messages"][0]
    assert message["status"] == "stopped"
    assert message["errorType"] == "SpeakerCallWatchdogTimeout"
    assert not chat_room_service._chat_room_round_has_process_control(round_id)


# ---------------------------------------------------------------------------
# E. work-run snapshot desync self-heal
# ---------------------------------------------------------------------------


def _seed_room_with_rounds(tmp_path, monkeypatch, *, title, room_status, active_round_id, rounds):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", tmp_path / "work_runs")
    room = chat_room_service.create_chat_room(title=title, participant_session_ids=["session-alpha"])
    state = chat_room_service._store().load()
    stored_room = next(item for item in state["rooms"] if item["roomId"] == room["roomId"])
    stored_room["status"] = room_status
    stored_room["activeRoundId"] = active_round_id
    stored_room["rounds"] = [dict(round_payload, roomId=stored_room["roomId"]) for round_payload in rounds]
    chat_room_service._store().save(state)
    return stored_room


def _round_payload(round_id, *, title, status, updated_at, finished_at, summary=""):
    return {
        "roundId": round_id,
        "topic": title,
        "mode": "round_robin",
        "purpose": "discussion",
        "config": {},
        "status": status,
        "speakerOrder": ["session-session-alpha"],
        "messages": [],
        "summary": summary,
        "startedAt": "2026-09-01T00:00:00+00:00",
        "updatedAt": updated_at,
        "finishedAt": finished_at,
    }


def _counting_work_run_store(monkeypatch):
    real_store = chat_room_service._work_run_store()
    calls = {"persist": 0}

    class CountingStore:
        def __getattr__(self, name):
            return getattr(real_store, name)

        def persist_snapshot(self, *args, **kwargs):
            calls["persist"] += 1
            return real_store.persist_snapshot(*args, **kwargs)

    monkeypatch.setattr(chat_room_service, "_work_run_store", lambda: CountingStore())
    return calls


def test_reconcile_repairs_terminal_round_with_running_work_run_snapshot(tmp_path, monkeypatch):
    finished_at = "2026-09-03T09:17:07+00:00"
    stored_room = _seed_room_with_rounds(
        tmp_path,
        monkeypatch,
        title="快照脱同步自愈",
        room_status="ready",
        active_round_id="",
        rounds=[
            _round_payload(
                "round-desync-ghost",
                title="快照脱同步自愈",
                status="stopped",
                updated_at=finished_at,
                finished_at=finished_at,
                summary="群聊轮次已停止：0/1 位 Agent 已发言。",
            )
        ],
    )
    room_id = stored_room["roomId"]
    # The stop happened in another process/path: chat store is terminal while
    # the WorkRun snapshot stayed "running" and still owns the index pointer.
    _persist_running_work_run(stored_room, "round-desync-ghost", updated_at="2026-09-01T00:00:00+00:00")
    store = chat_room_service._work_run_store()
    assert store.load_run_index(chat_room_service.RUN_KIND)["activeRunId"] == "round-desync-ghost"
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_RECONCILE_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(chat_room_service, "_record_room_event", lambda *args, **kwargs: None)
    recorded = _capture_scene_events(monkeypatch)

    chat_room_service.list_chat_rooms_compact()

    repaired = store.load_snapshot(chat_room_service.RUN_KIND, "round-desync-ghost")
    assert repaired["status"] == "stopped"
    assert repaired["finishedAt"] == finished_at
    assert repaired["summary"] == "群聊轮次已停止：0/1 位 Agent 已发言。"
    assert repaired["runtimeStatus"] == "orphan_reconciled"
    assert repaired["reconciliationSource"] == "work_run_snapshot_desync"
    index = store.load_run_index(chat_room_service.RUN_KIND)
    assert index["activeRunId"] == ""
    assert "round-desync-ghost" not in index["activeRunIds"]
    assert any(
        item[0][:3] == ("chat_room", "reconcile", "chat_room.round.work_run_snapshot_resynced")
        for item in recorded
    )
    # The room store side is already terminal and must stay untouched.
    reloaded_room = _reloaded_room(room_id)
    assert reloaded_room["rounds"][0]["status"] == "stopped"
    assert reloaded_room["rounds"][0]["finishedAt"] == finished_at
    assert reloaded_room["activeRoundId"] == ""

    # Idempotent: a second pass must not rewrite the repaired snapshot.
    persisted_before = dict(repaired)
    persist_calls = _counting_work_run_store(monkeypatch)
    chat_room_service._reconcile_chat_room_round_state()
    assert persist_calls["persist"] == 0
    assert store.load_snapshot(chat_room_service.RUN_KIND, "round-desync-ghost") == persisted_before


def test_reconcile_desync_repair_keeps_newer_active_run_pointer(tmp_path, monkeypatch):
    finished_at = "2026-09-03T09:17:07+00:00"
    live_updated_at = chat_room_service.utc_now_iso()
    stored_room = _seed_room_with_rounds(
        tmp_path,
        monkeypatch,
        title="新轮指针不被回拨",
        room_status="running",
        active_round_id="round-live-newer",
        rounds=[
            _round_payload(
                "round-desync-old",
                title="新轮指针不被回拨",
                status="stopped",
                updated_at=finished_at,
                finished_at=finished_at,
                summary="群聊轮次已停止：1/2 位 Agent 已发言。",
            ),
            _round_payload(
                "round-live-newer",
                title="新轮指针不被回拨",
                status="running",
                updated_at=live_updated_at,
                finished_at="",
            ),
        ],
    )
    room_id = stored_room["roomId"]
    _persist_running_work_run(stored_room, "round-desync-old", updated_at="2026-09-01T00:00:00+00:00")
    _persist_running_work_run(stored_room, "round-live-newer", updated_at=chat_room_service.utc_now_iso())
    store = chat_room_service._work_run_store()
    index = store.load_run_index(chat_room_service.RUN_KIND)
    assert index["activeRunId"] == "round-live-newer"
    assert set(index["activeRunIds"]) == {"round-desync-old", "round-live-newer"}
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_RECONCILE_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(chat_room_service, "_record_room_event", lambda *args, **kwargs: None)
    _capture_scene_events(monkeypatch)

    chat_room_service.list_chat_rooms_compact()

    repaired = store.load_snapshot(chat_room_service.RUN_KIND, "round-desync-old")
    assert repaired["status"] == "stopped"
    assert repaired["finishedAt"] == finished_at
    assert repaired["reconciliationSource"] == "work_run_snapshot_desync"
    # The live newer round keeps the index pointer and its running snapshot.
    live = store.load_snapshot(chat_room_service.RUN_KIND, "round-live-newer")
    assert live["status"] == "running"
    assert live["finishedAt"] == ""
    assert "runtimeStatus" not in live
    index = store.load_run_index(chat_room_service.RUN_KIND)
    assert index["activeRunId"] == "round-live-newer"
    assert index["activeRunIds"] == ["round-live-newer"]
    reloaded_room = _reloaded_room(room_id)
    assert reloaded_room["status"] == "running"
    assert reloaded_room["activeRoundId"] == "round-live-newer"


def test_reconcile_leaves_normal_running_round_snapshot_untouched(tmp_path, monkeypatch):
    live_updated_at = chat_room_service.utc_now_iso()
    stored_room = _seed_room_with_rounds(
        tmp_path,
        monkeypatch,
        title="正常轮不被误修",
        room_status="running",
        active_round_id="round-live-normal",
        rounds=[
            _round_payload(
                "round-live-normal",
                title="正常轮不被误修",
                status="running",
                updated_at=live_updated_at,
                finished_at="",
            )
        ],
    )
    _persist_running_work_run(stored_room, "round-live-normal", updated_at=chat_room_service.utc_now_iso())
    store = chat_room_service._work_run_store()
    snapshot_before = store.load_snapshot(chat_room_service.RUN_KIND, "round-live-normal")
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_RECONCILE_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(chat_room_service, "_record_room_event", lambda *args, **kwargs: None)
    persist_calls = _counting_work_run_store(monkeypatch)

    reconciled = chat_room_service._reconcile_chat_room_round_state()

    # A live running round is spared by the heartbeat exemption and the desync
    # repair must not write anything at all.
    assert reconciled == []
    assert persist_calls["persist"] == 0
    snapshot_after = store.load_snapshot(chat_room_service.RUN_KIND, "round-live-normal")
    assert snapshot_after == snapshot_before
    assert snapshot_after["finishedAt"] == ""
    assert "reconciliationSource" not in snapshot_after
    reloaded_room = _reloaded_room(stored_room["roomId"])
    assert reloaded_room["status"] == "running"
    assert reloaded_room["activeRoundId"] == "round-live-normal"
    assert reloaded_room["rounds"][0]["status"] == "running"
