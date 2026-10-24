"""Ledger-only research execution must participate in formal cancellation."""

from __future__ import annotations

import json
from types import SimpleNamespace
import pytest

from core.research.workflow.contracts import WorkflowCommandKind
from core.web.services import session_service
from core.web.services.team_workflow.research_runtime.cancel_run_cleanup import CancelRunCleanupWorker
from core.web.services.team_workflow.research_runtime.command_service import _collect_cancel_run_turn_pairs
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS, build_attempt_record, build_command_record


def _anchor(harness, *, run_id="run-owned", node_id="problem_understanding", attempt=1,
            session_id="owned-session", turn_id="owned-turn", payload=None):
    node_run_id = f"nr-{run_id}-{node_id}-a{attempt}"
    command_id = f"cmd-{node_run_id}"
    anchor_id = f"anchor-{node_run_id}"
    def seed(uow):
        uow.repository.insert_command(build_command_record(command_id,
            run_id=run_id, node_id=node_id, idempotency_key=command_id))
        uow.repository.insert_attempt(build_attempt_record(node_run_id, run_id=run_id,
            node_id=node_id, attempt=attempt, command_id=command_id, status="running"))
        uow.repository.insert_anchor(anchor_id=anchor_id, node_run_id=node_run_id,
            actor_kind="agent", anchor_json=json.dumps(payload or {}),
            session_id=session_id, turn_id=turn_id, created_at_ms=FIXED_NOW_MS, status="running")
        uow.repository.execute("UPDATE node_attempts SET execution_anchor_id=? WHERE node_run_id=?",
            (anchor_id, node_run_id))
    harness.store.submit(seed, force_flush=True).result(timeout=10)
    return node_run_id


class NativeTurns:
    def __init__(self, pairs):
        self.snapshots = {turn: {"status": "running", "sessionId": session}
                          for session, turn in pairs}
        self.active_by_session = dict(pairs)
        self.stop_requests = []
        self.actual_stops = []

    def load_snapshot(self, kind, turn):
        assert kind == "chat_turn"
        return self.snapshots.get(turn)

    def load_run_index(self, kind):
        assert kind == "chat_turn"
        return {"activeRunId": next(iter(self.active_by_session.values()), "")}

    def stop(self, session, *, expected_turn_id):
        self.stop_requests.append((session, expected_turn_id))
        if self.active_by_session.get(session) != expected_turn_id:
            raise session_service.SessionBusyError("active turn changed")
        self.actual_stops.append((session, expected_turn_id))
        self.snapshots[expected_turn_id]["status"] = "stopping"
        return {"id": session, "activeTurnId": expected_turn_id}


def _native(monkeypatch, tmp_path, pairs=(("owned-session", "owned-turn"),)):
    native = NativeTurns(pairs)
    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_RUN_STORE", str(tmp_path / "legacy"))
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", native)
    monkeypatch.setattr(session_service, "_is_session_running", lambda sid: sid in native.active_by_session)
    monkeypatch.setattr(session_service, "request_stop_session_turn", native.stop)
    return native


def _cancel(harness):
    return harness.service.submit(harness.request(command=WorkflowCommandKind.CANCEL_RUN,
        run_id="run-owned", node_id=None, idempotency_key="cancel-owned"))


def _cleanup(harness):
    return harness.store.read(lambda repo: repo.execute(
        "SELECT status,last_problem_json FROM outbox_actions WHERE idempotency_key=?",
        ("cancel_run_cleanup:run-owned",),
    ).fetchone())


def test_cancel_fast_path_stops_ledger_only_current_owned_turn(tmp_path, monkeypatch):
    native = _native(monkeypatch, tmp_path,
        (("owned-session", "owned-turn"), ("foreign-session", "foreign-turn")))
    harness = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        harness.seed_run(run_id="run-owned", status="running")
        harness.seed_run(run_id="run-foreign", status="running")
        _anchor(harness)
        _anchor(harness, run_id="run-foreign", session_id="foreign-session", turn_id="foreign-turn")
        assert WorkflowRunStore().get_run("run-owned") is None
        assert _cancel(harness).status == "accepted"
        assert native.actual_stops == [("owned-session", "owned-turn")]
        assert native.snapshots["foreign-turn"]["status"] == "running"
    finally:
        harness.close()


def test_cleanup_waits_for_ledger_turn_terminal_before_ack(tmp_path, monkeypatch):
    native = _native(monkeypatch, tmp_path)
    harness = CommandHarness(tmp_path / "ledger.sqlite")
    clock = [FIXED_NOW_MS + 1000]
    try:
        harness.seed_run(run_id="run-owned", status="running")
        _anchor(harness)
        _cancel(harness)
        worker = CancelRunCleanupWorker(store=harness.store, now_provider=lambda: clock[0], retry_delay_ms=1)
        assert worker.run_once() == 1
        status, problem = _cleanup(harness)
        assert status == "pending"
        assert json.loads(problem)["code"] == "cancel_run_cleanup_pending"
        native.snapshots["owned-turn"].update(status="stopped", finishedAt="2026-10-24T12:00:00Z")
        native.active_by_session.clear()
        clock[0] += 2
        assert worker.run_once() == 1
        assert _cleanup(harness)[0] == "succeeded"
    finally:
        harness.close()


def test_ledger_authority_excludes_old_attempt_foreign_run_and_stale_json(tmp_path, monkeypatch):
    _native(monkeypatch, tmp_path)
    harness = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        harness.seed_run(run_id="run-owned", status="running")
        harness.seed_run(run_id="run-foreign", status="running")
        _anchor(harness, attempt=1, session_id="old-session", turn_id="old-turn")
        _anchor(harness, attempt=2)
        _anchor(harness, run_id="run-foreign", session_id="foreign-session", turn_id="foreign-turn")
        WorkflowRunStore().create_run({"runId": "run-owned", "workflowId": "challenge-cup",
            "status": "running", "taskBundles": [], "bindingSnapshots": [
                {"sessionId": "stale-json-session", "turnId": "stale-json-turn"}]})
        assert _collect_cancel_run_turn_pairs("run-owned", store=harness.store) == [("owned-session", "owned-turn")]
    finally:
        harness.close()


def test_scoped_child_turns_are_bound_to_the_same_ledger_attempt(tmp_path, monkeypatch):
    _native(monkeypatch, tmp_path)
    harness = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        harness.seed_run(run_id="run-owned", status="running")
        node_run_id = "nr-run-owned-problem_understanding-a1"
        _anchor(harness, payload={"rootSession": {"sessionId": "owned-session", "turnId": "owned-turn"},
            "scopedSessions": [
                {"sessionId": "owned-child", "turnId": "owned-child-turn", "rootSessionId": "owned-session",
                 "workflowRunId": "run-owned", "nodeRunId": node_run_id},
                {"sessionId": "foreign-child", "turnId": "foreign-child-turn", "rootSessionId": "owned-session",
                 "workflowRunId": "run-foreign", "nodeRunId": node_run_id},
                {"sessionId": "other-attempt-child", "turnId": "other-attempt-turn", "rootSessionId": "owned-session",
                 "nodeRunId": "nr-run-owned-problem_understanding-a0"},
                {"sessionId": "foreign-parent-child", "turnId": "foreign-parent-turn",
                 "rootSessionId": "owned-session", "parentSessionId": "foreign-session"},
            ]})
        assert _collect_cancel_run_turn_pairs("run-owned", store=harness.store) == [
            ("owned-session", "owned-turn"), ("owned-child", "owned-child-turn")]
    finally:
        harness.close()


def test_new_attempt_without_anchor_does_not_revive_old_or_json_turn(tmp_path, monkeypatch):
    _native(monkeypatch, tmp_path)
    harness = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        harness.seed_run(run_id="run-owned", status="running")
        _anchor(harness)
        def seed_next_attempt(uow):
            uow.repository.insert_command(build_command_record("cmd-next", run_id="run-owned",
                node_id="problem_understanding", idempotency_key="cmd-next"))
            uow.repository.insert_attempt(build_attempt_record("nr-run-owned-problem_understanding-a2",
                run_id="run-owned", node_id="problem_understanding", attempt=2,
                command_id="cmd-next", status="running"))
        harness.store.submit(seed_next_attempt, force_flush=True).result(timeout=10)
        WorkflowRunStore().create_run({"runId": "run-owned", "workflowId": "challenge-cup",
            "status": "running", "taskBundles": [], "bindingSnapshots": [
                {"sessionId": "stale-json-session", "turnId": "stale-json-turn"}]})
        assert _collect_cancel_run_turn_pairs("run-owned", store=harness.store) == []
    finally:
        harness.close()


def test_scalar_anchor_turn_is_not_replaced_by_later_json_turn(tmp_path, monkeypatch):
    _native(monkeypatch, tmp_path)
    harness = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        harness.seed_run(run_id="run-owned", status="running")
        _anchor(harness, payload={"rootSession": {"sessionId": "owned-session", "turnId": "later-turn"}})
        assert _collect_cancel_run_turn_pairs("run-owned", store=harness.store) == [("owned-session", "owned-turn")]
    finally:
        harness.close()


def test_new_native_turn_is_fenced_by_expected_turn_identity(tmp_path, monkeypatch):
    native = _native(monkeypatch, tmp_path)
    native.active_by_session["owned-session"] = "newer-turn"
    native.snapshots["newer-turn"] = {"status": "running", "sessionId": "owned-session"}
    harness = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        harness.seed_run(run_id="run-owned", status="running")
        _anchor(harness)
        assert _cancel(harness).status == "accepted"
        worker = CancelRunCleanupWorker(store=harness.store, now_provider=lambda: FIXED_NOW_MS + 1000)
        assert worker.run_once() == 1
        assert native.stop_requests == [("owned-session", "owned-turn"), ("owned-session", "owned-turn")]
        assert native.actual_stops == []
        assert native.snapshots["newer-turn"]["status"] == "running"
        assert _cleanup(harness)[0] == "pending"
    finally:
        harness.close()


@pytest.fixture
def frozen_meeting(tmp_path, monkeypatch):
    from core.web.services import chat_room_service
    from core.web.services.team_workflow.operator_optimization import discussion_task

    native = _native(monkeypatch, tmp_path, pairs=())
    monkeypatch.setattr(session_service, "_persist_chat_turn_work_run",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("meeting speakers are not Session turns")))
    node_run_id = "nr-run-owned-optimization_discussion-a1"
    room = {"roomId": "room-owned", "activeRoundId": "round-owned",
        "config": {"workflowRunId": "run-owned", "nodeRunId": node_run_id,
            "operatorDiscussionAuthority": {"workflowRunId": "run-owned", "nodeRunId": node_run_id,
                "nodeAttempt": 1, "participants": [{"agentId": "speaker-a"}, {"agentId": "speaker-b"}]}},
        "participants": [{"agentId": "speaker-a", "sessionId": "speaker-session-a", "participantId": "seat-a"},
                         {"agentId": "speaker-b", "sessionId": "speaker-session-b", "participantId": "seat-b"}],
        "rounds": [{"roundId": "round-owned", "status": "running", "finishedAt": "",
                    "config": {"workflowRunId": "run-owned", "nodeRunId": node_run_id}}]}
    monkeypatch.setattr(discussion_task, "open_discussion",
        lambda *_args, **_kwargs: {"roomId": "room-owned", "roundId": "round-owned"})
    monkeypatch.setattr(chat_room_service, "get_chat_room_detail", lambda _room_id, **_kwargs: room)
    work_run = {"roomId": "room-owned", "roundId": "round-owned", "status": "running", "finishedAt": ""}
    work_index = {"activeRunId": "round-owned"}
    monkeypatch.setattr(chat_room_service, "_work_run_store", lambda: SimpleNamespace(
        load_snapshot=lambda kind, identity: dict(work_run), load_run_index=lambda kind: dict(work_index)))
    stop_requests = []
    def stop_round(room_id, *, expected_round_id, reason=""):
        assert room_id == "room-owned" and expected_round_id == "round-owned"
        stop_requests.append((room_id, expected_round_id))
        room["rounds"][0]["status"] = "stopping"
        return room
    monkeypatch.setattr(chat_room_service, "stop_chat_room_round", stop_round)
    harness = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        harness.seed_run(run_id="run-owned", status="running")
        handle = discussion_task.create_discussion_task(harness.store,
            SimpleNamespace(run_id="run-owned", node_run_id=node_run_id))
        assert handle.session_id == "speaker-session-b"
        assert len(handle.meeting_participants) == 2
        _anchor(harness, node_id="optimization_discussion", session_id=handle.session_id,
            turn_id=handle.turn_id, payload=handle.to_dict())
        yield SimpleNamespace(harness=harness, room=room, work_run=work_run, work_index=work_index,
                              native=native, stop_requests=stop_requests)
    finally:
        harness.close()


def test_meeting_cancel_stops_frozen_native_round_and_waits_for_all_speakers(frozen_meeting):
    env = frozen_meeting
    harness = env.harness
    clock = [FIXED_NOW_MS + 1000]
    assert _cancel(harness).status == "accepted"
    assert env.stop_requests == [("room-owned", "round-owned")]
    assert env.native.stop_requests == []
    worker = CancelRunCleanupWorker(store=harness.store, now_provider=lambda: clock[0], retry_delay_ms=1)
    assert worker.run_once() == 1
    assert _cleanup(harness)[0] == "pending"
    env.room["rounds"][0].update(status="stopped", finishedAt="2026-10-24T12:00:00Z")
    env.room["activeRoundId"] = ""
    clock[0] += 2
    assert worker.run_once() == 1
    assert _cleanup(harness)[0] == "pending"  # Room projection alone is insufficient.
    env.work_run.update(status="stopped", finishedAt="2026-10-24T12:00:00Z")
    env.work_index["activeRunId"] = ""
    clock[0] += 2
    assert worker.run_once() == 1
    assert _cleanup(harness)[0] == "succeeded"
    assert env.native.stop_requests == []


@pytest.mark.parametrize("boundary", ["foreign_run", "foreign_attempt", "foreign_round",
                                      "foreign_participant", "later_active_round"])
def test_meeting_cancel_rejects_foreign_or_later_execution(frozen_meeting, boundary):
    env = frozen_meeting
    if boundary == "foreign_run":
        env.room["config"]["operatorDiscussionAuthority"]["workflowRunId"] = "run-foreign"
    elif boundary == "foreign_attempt":
        env.room["rounds"][0]["config"]["nodeRunId"] = "other-attempt"
    elif boundary == "foreign_round":
        env.room["rounds"][0]["roundId"] = "other-round"
    elif boundary == "foreign_participant":
        env.room["participants"][0]["sessionId"] = "foreign-session"
    else:
        env.room["activeRoundId"] = "later-round"
    assert _cancel(env.harness).status == "accepted"
    assert env.stop_requests == []
    worker = CancelRunCleanupWorker(store=env.harness.store, now_provider=lambda: FIXED_NOW_MS + 1000)
    assert worker.run_once() == 1
    assert _cleanup(env.harness)[0] == "pending"
    assert env.native.stop_requests == []


def test_terminal_frozen_meeting_does_not_stop_later_round(frozen_meeting):
    env = frozen_meeting
    env.room["rounds"][0].update(status="stopped", finishedAt="2026-10-24T12:00:00Z")
    env.room["activeRoundId"] = "later-round"
    env.work_run.update(status="stopped", finishedAt="2026-10-24T12:00:00Z")
    env.work_index["activeRunId"] = "later-round"
    assert _cancel(env.harness).status == "accepted"
    worker = CancelRunCleanupWorker(store=env.harness.store, now_provider=lambda: FIXED_NOW_MS + 1000)
    assert worker.run_once() == 1
    assert _cleanup(env.harness)[0] == "succeeded"
    assert env.stop_requests == []
    assert env.native.stop_requests == []


@pytest.mark.parametrize("published_child", [False, True])
def test_creating_fanout_admission_stays_pending_even_with_no_live_children(tmp_path, monkeypatch, published_child):
    native = _native(monkeypatch, tmp_path, pairs=(("owned-child", "owned-child-turn"),) if published_child else ())
    harness = CommandHarness(tmp_path / "ledger.sqlite")
    clock = [FIXED_NOW_MS + 1000]
    payload = {"executionAdmission": {"status": "creating", "actionId": "owned-action"},
               "rootSession": {"sessionId": "owned-root"}, "scopedSessions": []}
    if published_child:
        payload["scopedSessions"].append({"sessionId": "owned-child", "turnId": "owned-child-turn",
                                        "rootSessionId": "owned-root", "parentSessionId": "owned-root"})
    try:
        harness.seed_run(run_id="run-owned", status="running")
        _anchor(harness, session_id="owned-root", turn_id="", payload=payload)
        assert _cancel(harness).status == "accepted"
        assert native.actual_stops == ([("owned-child", "owned-child-turn")] if published_child else [])
        if published_child:
            native.snapshots["owned-child-turn"].update(status="stopped", finishedAt="2026-10-24T12:00:00Z")
            native.active_by_session.clear()
        worker = CancelRunCleanupWorker(store=harness.store, now_provider=lambda: clock[0], retry_delay_ms=1)
        assert worker.run_once() == 1
        assert _cleanup(harness)[0] == "pending"
        payload["executionAdmission"]["status"] = "closed"
        harness.store.submit(lambda uow: uow.repository.execute(
            "UPDATE execution_anchors SET anchor_json=? WHERE node_run_id=?",
            (json.dumps(payload), "nr-run-owned-problem_understanding-a1")), force_flush=True).result(timeout=10)
        clock[0] += 2
        assert worker.run_once() == 1
        assert _cleanup(harness)[0] == "succeeded"
    finally:
        harness.close()
