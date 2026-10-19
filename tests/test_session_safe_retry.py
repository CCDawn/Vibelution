"""CAS retry accepts one failed native turn without superseding newer work."""

import multiprocessing
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.chat.conversation_ledger import append_conversation_event, load_conversation_events
from core.chat.conversation_branches import analyze_conversation_branches
from core.web.services import session_service
from core.web.services.session import submit
from tests.test_session_submit import _prepare_default_submit_session
from tests.helpers.web_chat_state import _reset_seeded_session_runtime


@pytest.fixture
def failed_session(tmp_path, monkeypatch):
    sid = _prepare_default_submit_session(tmp_path, monkeypatch)
    append_conversation_event(tmp_path, sid, "failed-turn", "turn_started", status="running")
    user = append_conversation_event(tmp_path, sid, "failed-turn", "user_message",
                                     payload={"content": "retry this request"})
    append_conversation_event(tmp_path, sid, "failed-turn", "turn_failed", status="failed")
    events = load_conversation_events(tmp_path, sid)
    view = analyze_conversation_branches(events)
    conversation = session_service.load_session_chat_state(tmp_path, sid)
    request = dict(client_submission_id="safe-retry-1", expected_turn_id="failed-turn",
                   expected_head_id=view.active_leaf_id, expected_ledger_seq=events[-1].sequence,
                   expected_agent_id=conversation["agent_id"], base_message_id=user.event_id)
    scheduled = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled.append(context))
    yield sid, request, scheduled
    _reset_seeded_session_runtime(sid)


def _retry(sid, request):
    return session_service.retry_session_message(sid, **request)


def test_safe_retry_concurrent_duplicates_accept_once_and_replay_after_advance(failed_session, tmp_path):
    sid, request, scheduled = failed_session
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: _retry(sid, request), range(2)))
    assert len(scheduled) == 1
    receipt = results[0]["retryReceipt"]
    assert receipt == results[1]["retryReceipt"]
    assert receipt["turnId"] == scheduled[0]["turn_id"]
    append_conversation_event(tmp_path, sid, receipt["turnId"], "turn_completed", status="completed")
    append_conversation_event(tmp_path, sid, "later", "turn_started", status="running")
    assert _retry(sid, request)["retryReceipt"] == receipt
    assert len(scheduled) == 1
    markers = [e for e in load_conversation_events(tmp_path, sid) if e.correlation_id == request["client_submission_id"]]
    assert len([e for e in markers if e.event_type == "user_message"]) == 1


@pytest.mark.parametrize("field,value", [
    ("expected_turn_id", "older-turn"), ("expected_head_id", "older-head"),
    ("expected_ledger_seq", 1), ("expected_agent_id", "other-agent"),
    ("base_message_id", "other-message"),
])
def test_safe_retry_stale_snapshot_is_read_only(failed_session, tmp_path, field, value):
    sid, request, scheduled = failed_session
    before = load_conversation_events(tmp_path, sid)
    state = session_service.load_session_chat_state(tmp_path, sid)
    with pytest.raises(session_service.SessionBusyError):
        _retry(sid, {**request, field: value})
    assert load_conversation_events(tmp_path, sid) == before
    assert session_service.load_session_chat_state(tmp_path, sid) == state
    assert not scheduled


@pytest.mark.parametrize("status", ["completed", "interrupted", "paused"])
def test_safe_retry_requires_native_failed_terminal(failed_session, tmp_path, status):
    sid, request, scheduled = failed_session
    append_conversation_event(tmp_path, sid, "new-turn", "turn_started", status="running")
    user = append_conversation_event(tmp_path, sid, "new-turn", "user_message", payload={"content": "new request"})
    append_conversation_event(tmp_path, sid, "new-turn", "turn_" + status, status=status)
    events = load_conversation_events(tmp_path, sid)
    request.update(expected_turn_id="new-turn", base_message_id=user.event_id,
                   expected_head_id=analyze_conversation_branches(events).active_leaf_id,
                   expected_ledger_seq=events[-1].sequence)
    with pytest.raises(session_service.SessionBusyError):
        _retry(sid, request)
    assert not scheduled


@pytest.mark.parametrize("kind", ["queue", "open_turn", "work_run"])
def test_safe_retry_rejects_durable_work_even_without_local_running_flag(failed_session, tmp_path, kind):
    sid, request, scheduled = failed_session
    if kind == "queue":
        state = session_service.load_session_chat_state(tmp_path, sid)
        state["queued_turns"] = [{"id": "queued", "content": "new task", "status": "starting"}]
        session_service.save_session_chat_state(tmp_path, sid, state)
    elif kind == "open_turn":
        append_conversation_event(tmp_path, sid, "open", "turn_started", status="running")
        request["expected_ledger_seq"] = load_conversation_events(tmp_path, sid)[-1].sequence
    else:
        session_service._persist_chat_turn_work_run(session_id=sid, turn_id="other-running",
                                                   status="running", user_message="new task")
    with pytest.raises(session_service.SessionBusyError):
        _retry(sid, request)
    assert not scheduled


def test_safe_retry_submission_key_cannot_change_expectations(failed_session):
    sid, request, scheduled = failed_session
    _retry(sid, request)
    with pytest.raises(session_service.SessionValidationError):
        _retry(sid, {**request, "expected_ledger_seq": 1})
    assert len(scheduled) == 1


def test_claimed_queue_row_cannot_be_removed_before_dispatch(failed_session, tmp_path):
    from core.web.services.session import queued_turns

    sid, request, scheduled = failed_session
    state = session_service.load_session_chat_state(tmp_path, sid)
    state["queued_turns"] = [{"id": "claimed", "content": "new task", "status": "starting"}]
    session_service.save_session_chat_state(tmp_path, sid, state)
    with pytest.raises(session_service.SessionBusyError):
        queued_turns.remove_session_queued_turn(sid, "claimed")
    with pytest.raises(session_service.SessionBusyError):
        _retry(sid, request)
    assert not scheduled


def test_safe_retry_lease_conflict_is_read_only(failed_session, tmp_path, monkeypatch):
    sid, request, scheduled = failed_session
    before = load_conversation_events(tmp_path, sid)
    state = session_service.load_session_chat_state(tmp_path, sid)
    monkeypatch.setattr(session_service, "_check_chat_turn_lease_decision",
                        lambda _: SimpleNamespace(allowed=False, reason="busy", conflicts=[]))
    with pytest.raises(session_service.SessionBusyError):
        _retry(sid, request)
    assert load_conversation_events(tmp_path, sid) == before
    assert session_service.load_session_chat_state(tmp_path, sid) == state
    assert not scheduled


@pytest.mark.parametrize("competitor", ["new_submit", "regenerate", "queue", "head"])
def test_older_safe_retry_cannot_supersede_competing_user_action(failed_session, tmp_path, competitor, monkeypatch):
    from core.web.services.session import queued_turns

    sid, request, scheduled = failed_session
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", lambda _: None)
    if competitor == "new_submit":
        submit.submit_session_message_lightweight(sid, "new request", client_submission_id="newer")
    elif competitor == "regenerate":
        submit.regenerate_session_message(sid, "", base_message_id=request["base_message_id"], client_submission_id="manual")
    elif competitor == "head":
        events = load_conversation_events(tmp_path, sid)
        view = analyze_conversation_branches(events)
        for node_id in (view.active_node_ids[0], request["expected_head_id"]):
            node = view.nodes[node_id]
            append_conversation_event(tmp_path, sid, node.turn_id, "branch_rebase", status="recorded",
                payload={"operation": "head_select", "fromEventId": node.event_id, "branchId": node.branch_id,
                         "baseMessageId": node_id, "replacedTurnIds": []}, parent_event_id=node.event_id)
        assert analyze_conversation_branches(load_conversation_events(tmp_path, sid)).active_leaf_id == request["expected_head_id"]
    else:
        queued_turns.enqueue_session_queued_turn(sid, content="new queued request", attachments=[], references=[],
            mental_model_enabled=None, runtime_status_enabled=None, turn_mode="", write_intent=None,
            client_submission_id="new-queue")
    before = load_conversation_events(tmp_path, sid)
    count = len(scheduled)
    with pytest.raises(session_service.SessionBusyError):
        _retry(sid, request)
    assert len(scheduled) == count
    assert load_conversation_events(tmp_path, sid) == before


def test_machine_notice_waits_for_retry_and_is_preserved(failed_session, tmp_path, monkeypatch):
    from core.web.services.session import queued_turns

    sid, request, scheduled = failed_session
    entered, release = threading.Event(), threading.Event()
    original = session_service._append_session_branch_rebase_event
    def pause(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(session_service, "_append_session_branch_rebase_event", pause)
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", lambda _: None)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(_retry, sid, request)
            assert entered.wait(5)
            notice = pool.submit(queued_turns.enqueue_session_runtime_notice, sid,
                                 kind="task_notification", content="background task finished", source_id="notice-1")
            try:
                with pytest.raises(FutureTimeout):
                    notice.result(0.15)
            finally:
                release.set()
            first.result(5)
            notice.result(5)
    finally:
        release.set()
    rows = queued_turns.list_session_queued_turns(sid)
    assert len(rows) == 1
    assert rows[0]["content"] == "background task finished"
    assert len(scheduled) == 1


def _retry_in_process(root, workspace, work_runs, request, model_parameters, gate, output, action="retry"):
    import faulthandler
    from core.infrastructure import developer_sandbox
    from core.runtime_manager.work_run_store import WorkRunStore
    from core.web.services import agent_directory_service, runtime_scene_service
    from core.runtime_manager import scene_logging

    faulthandler.dump_traceback_later(35, exit=True)
    root = Path(root)
    developer_sandbox.resolve_workspace_home = lambda *_args, **_kwargs: Path(workspace)
    developer_sandbox.is_developer_mode_enabled = lambda: False
    session_service.PROJECT_ROOT = agent_directory_service.PROJECT_ROOT = runtime_scene_service.PROJECT_ROOT = root
    scene_logging.EVENTS_PATH = root / "runtime-events.jsonl"
    session_service._WORK_RUN_STORE = WorkRunStore(root=Path(work_runs))
    submit.capture_model_parameters = lambda *_args, **_kwargs: model_parameters
    session_service._session_context_limit_payload = lambda _: {"limit": 200000, "source": "test"}
    scheduled = []
    session_service._schedule_session_turn = lambda context: scheduled.append(context["turn_id"])
    try:
        assert gate.wait(10)
        if action == "new_submit":
            submit.submit_session_message_lightweight("session-live", "newer request", client_submission_id="cross-process-new")
            output.put({"scheduled": scheduled})
        elif action == "regenerate":
            submit.regenerate_session_message("session-live", "", base_message_id=request["base_message_id"])
            output.put({"scheduled": scheduled})
        elif action == "head":
            session_service.switch_session_head("session-live", request["base_message_id"])
            output.put({"scheduled": scheduled})
        elif action == "drain":
            from core.web.services.session.queued_turns import drain_session_queued_turns
            output.put({"drained": drain_session_queued_turns("session-live"), "scheduled": scheduled})
        else:
            result = _retry("session-live", request)
            output.put({"receipt": result["retryReceipt"], "scheduled": scheduled})
    except session_service.SessionBusyError:
        output.put({"busy": True, "scheduled": scheduled})
    except BaseException as exc:
        output.put({"error": f"{type(exc).__name__}: {exc}"})


def test_safe_retry_deduplicates_across_backend_processes(failed_session, tmp_path):
    from core.infrastructure import developer_sandbox

    sid, request, _ = failed_session
    conversation = session_service.load_session_chat_state(tmp_path, sid)
    model_parameters = submit.capture_model_parameters(session_service, conversation)
    ctx = multiprocessing.get_context("spawn")
    gate, output = ctx.Event(), ctx.Queue()
    processes = [ctx.Process(target=_retry_in_process, args=(str(tmp_path),
        str(developer_sandbox.resolve_workspace_home(tmp_path)), str(session_service._WORK_RUN_STORE.root),
        request, model_parameters, gate, output)) for _ in range(2)]
    try:
        for process in processes:
            process.start()
        gate.set()
        for process in processes:
            process.join(40)
        assert [process.exitcode for process in processes] == [0, 0]
        results = [output.get(timeout=3) for _ in processes]
        assert not [row for row in results if row.get("error")], results
        assert results[0]["receipt"] == results[1]["receipt"]
        assert sum(len(row["scheduled"]) for row in results) == 1
        events = load_conversation_events(tmp_path, sid)
        assert len([e for e in events if e.correlation_id == request["client_submission_id"]]) == 1
        assert len([e for e in events if e.event_type == "branch_rebase"]) == 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(3)


def test_retry_http_contract_requires_snapshot_and_returns_stable_receipt(failed_session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.web.routes.sessions import router

    sid, request, scheduled = failed_session
    app = FastAPI()
    app.include_router(router)
    payload = dict(zip(["clientSubmissionId", "expectedTurnId", "expectedHeadId", "expectedLedgerSeq",
                        "expectedAgentId", "baseMessageId"], request.values()))
    with TestClient(app) as client:
        url = f"/sessions/{sid}/messages/retry"
        for key in payload:
            assert client.post(url, json={k: v for k, v in payload.items() if k != key}).status_code == 422
        assert client.post(url, json={**payload, "expectedLedgerSeq": True}).status_code == 422
        assert client.post(url, json={**payload, "clientSubmissionId": "  "}).status_code == 422
        assert client.post(url, json={**payload, "expectedTurnId": "stale"}).status_code == 409
        response = client.post(url, json=payload)
        assert response.status_code == 202, response.text
        assert client.post(url, json=payload).json()["retryReceipt"] == response.json()["retryReceipt"]
        assert len(scheduled) == 1


@pytest.mark.parametrize("action", ["new_submit", "regenerate", "head", "drain"])
def test_other_backend_cannot_replace_accepted_retry(failed_session, tmp_path, monkeypatch, action):
    from core.infrastructure import developer_sandbox
    from core.web.services.session import queued_turns

    sid, request, scheduled = failed_session
    _retry(sid, request)
    if action == "drain":
        monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", lambda _: None)
        queued_turns.enqueue_session_queued_turn(sid, content="queued later", attachments=[], references=[],
            mental_model_enabled=None, runtime_status_enabled=None, turn_mode="", write_intent=None,
            client_submission_id="later-queue")
    before = load_conversation_events(tmp_path, sid)
    state = session_service.load_session_chat_state(tmp_path, sid)
    model_parameters = submit.capture_model_parameters(session_service, state)
    ctx = multiprocessing.get_context("spawn")
    gate, output = ctx.Event(), ctx.Queue()
    process = ctx.Process(target=_retry_in_process, args=(str(tmp_path),
        str(developer_sandbox.resolve_workspace_home(tmp_path)), str(session_service._WORK_RUN_STORE.root),
        request, model_parameters, gate, output, action))
    try:
        process.start()
        gate.set()
        process.join(40)
        assert process.exitcode == 0
        result = output.get(timeout=3)
        assert result.get("scheduled") == [], result
        assert result.get("busy") or action == "drain", result
        assert load_conversation_events(tmp_path, sid) == before
        assert len(scheduled) == 1
        if action == "drain":
            assert queued_turns.list_session_queued_turns(sid)[0]["status"] == "queued"
    finally:
        if process.is_alive():
            process.terminate()
            process.join(3)


def test_retry_failed_startup_resume_replays_original_user_request(failed_session, tmp_path):
    sid, request, scheduled = failed_session
    append_conversation_event(tmp_path, sid, "origin", "turn_started", status="running")
    origin = append_conversation_event(tmp_path, sid, "origin", "user_message", payload={"content": "original request"})
    append_conversation_event(tmp_path, sid, "origin", "turn_interrupted", status="interrupted")
    append_conversation_event(tmp_path, sid, "resumed", "turn_started", status="running")
    append_conversation_event(tmp_path, sid, "resumed", "user_message", correlation_id="resume:origin",
        payload={"content": "synthetic restart prompt", "source": "hot_restart_resume", "metadata": {
            "kind": "hot_restart_resume", "recoverySource": "startup_sweep", "recoveredTurnId": "origin"}})
    append_conversation_event(tmp_path, sid, "resumed", "turn_failed", status="failed")
    events = load_conversation_events(tmp_path, sid)
    request.update(expected_turn_id="resumed", base_message_id=origin.event_id,
        expected_head_id=analyze_conversation_branches(events).active_leaf_id, expected_ledger_seq=events[-1].sequence)
    _retry(sid, request)
    assert scheduled[0]["raw_user_message"] == "original request"


def test_companion_cannot_use_ordinary_retry(failed_session, tmp_path):
    import json
    from core.web.services import agent_directory_service

    sid, request, scheduled = failed_session
    with agent_directory_service.scoped_project_root(tmp_path):
        path = agent_directory_service._workspace_path("agents", "agents.json", intent="state", seed=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    next(a for a in payload["agents"] if a["agentId"] == request["expected_agent_id"]).setdefault("metadata", {})["virtualHumanCompanion"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = load_conversation_events(tmp_path, sid)
    with pytest.raises(session_service.SessionBusyError):
        _retry(sid, request)
    assert load_conversation_events(tmp_path, sid) == before
    assert not scheduled


@pytest.mark.parametrize("stage", ["branch", "user", "schedule"])
def test_retry_admission_faults_always_clear_running(failed_session, monkeypatch, stage):
    sid, request, scheduled = failed_session
    original_persist = session_service._persist_chat_turn_work_run
    def fail_failed_snapshot(**kwargs):
        if kwargs.get("status") == "failed":
            raise OSError("secondary failure")
        return original_persist(**kwargs)
    def fail(*_args, **_kwargs):
        raise RuntimeError("injected admission failure")
    monkeypatch.setattr(session_service, "_persist_chat_turn_work_run", fail_failed_snapshot)
    if stage == "branch":
        monkeypatch.setattr(session_service, "_append_session_branch_rebase_event", fail)
    elif stage == "user":
        original_append = session_service._append_session_conversation_event
        def append(*args, **kwargs):
            if len(args) > 2 and args[2] == "user_message":
                fail()
            return original_append(*args, **kwargs)
        monkeypatch.setattr(session_service, "_append_session_conversation_event", append)
    else:
        monkeypatch.setattr(session_service, "_schedule_session_turn", fail)
    with pytest.raises(RuntimeError, match="injected admission failure"):
        _retry(sid, request)
    assert not session_service._is_session_running(sid)
    assert not session_service._current_session_turn_id(sid)
