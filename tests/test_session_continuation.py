"""Conditional native 'continue' sends never replay the original request."""

import hashlib
import json
import multiprocessing
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.chat.conversation_branches import analyze_conversation_branches
from core.chat.conversation_ledger import append_conversation_event, load_conversation_events
from core.web.services import session_service
from core.web.services.session import submit
from tests.helpers.web_chat_state import _reset_seeded_session_runtime
from tests.test_session_submit import _prepare_default_submit_session


@pytest.fixture
def stopped_session(tmp_path, monkeypatch):
    sid = _prepare_default_submit_session(tmp_path, monkeypatch)
    append_conversation_event(tmp_path, sid, "stopped-turn", "turn_started", status="running")
    append_conversation_event(tmp_path, sid, "stopped-turn", "user_message",
                              payload={"content": "original request"})
    append_conversation_event(tmp_path, sid, "stopped-turn", "assistant_message",
                              payload={"content": "partial answer"})
    append_conversation_event(tmp_path, sid, "stopped-turn", "turn_interrupted", status="stopped")
    events = load_conversation_events(tmp_path, sid)
    state = session_service.load_session_chat_state(tmp_path, sid)
    expected = {"turnId": "stopped-turn", "headId": analyze_conversation_branches(events).active_leaf_id,
                "ledgerSeq": events[-1].sequence, "agentId": state["agent_id"]}
    scheduled = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled.append(context))
    yield sid, expected, scheduled
    _reset_seeded_session_runtime(sid)


def _continue(sid, expected, submission_id="continue-1", **kwargs):
    return submit.submit_session_message_lightweight(sid, "继续", client_submission_id=submission_id,
                                                     _continuation_expected=expected, **kwargs)


def test_continuation_is_one_new_native_message_with_original_history(stopped_session, tmp_path):
    sid, expected, scheduled = stopped_session
    before = load_conversation_events(tmp_path, sid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: _continue(sid, expected), range(2)))
    assert results[0]["turnId"] == results[1]["turnId"] != expected["turnId"]
    assert len(scheduled) == 1
    assert scheduled[0]["raw_user_message"] == "继续"
    events = load_conversation_events(tmp_path, sid)
    assert events[:len(before)] == before
    assert not [event for event in events if event.event_type == "branch_rebase"]
    users = [event for event in events if event.event_type == "user_message"]
    assert [event.payload["content"] for event in users][-2:] == ["original request", "继续"]
    assert users[-1].correlation_id == "continue-1"


@pytest.mark.parametrize("field,value", [("turnId", "stale"), ("headId", "stale"),
                                         ("ledgerSeq", 1), ("agentId", "other")])
def test_stale_continuation_is_read_only(stopped_session, tmp_path, monkeypatch, field, value):
    sid, expected, scheduled = stopped_session
    before = load_conversation_events(tmp_path, sid)
    state = session_service.load_session_chat_state(tmp_path, sid)
    monkeypatch.setattr(session_service, "_reconcile_stale_session_ledger",
                        lambda *_a, **_kw: pytest.fail("rejection must precede reconcile"))
    with pytest.raises(session_service.SessionBusyError):
        _continue(sid, {**expected, field: value})
    assert load_conversation_events(tmp_path, sid) == before
    assert session_service.load_session_chat_state(tmp_path, sid) == state
    assert not scheduled


def test_rejected_continuation_never_opens_optional_control_store(stopped_session, monkeypatch):
    sid, expected, scheduled = stopped_session
    monkeypatch.setattr(submit, "get_development_submission_admission_runtime",
                        lambda *_: pytest.fail("control store may create state before CAS rejection"))
    with pytest.raises(session_service.SessionBusyError):
        _continue(sid, {**expected, "ledgerSeq": 1})
    assert not scheduled


def _snapshot(tmp_path, sid, turn_id):
    events = load_conversation_events(tmp_path, sid)
    state = session_service.load_session_chat_state(tmp_path, sid)
    return {"turnId": turn_id, "headId": analyze_conversation_branches(events).active_leaf_id,
            "ledgerSeq": events[-1].sequence, "agentId": state["agent_id"]}


def _terminal(tmp_path, sid, event_type, status, *, payload=None, error=None):
    turn_id = "latest-turn"
    append_conversation_event(tmp_path, sid, turn_id, "turn_started", status="running")
    append_conversation_event(tmp_path, sid, turn_id, "user_message", payload={"content": "latest request"})
    append_conversation_event(tmp_path, sid, turn_id, event_type, status=status, payload=payload or {})
    state = session_service.load_session_chat_state(tmp_path, sid)
    state["last_turn_error"] = error
    session_service.save_session_chat_state(tmp_path, sid, state)
    return _snapshot(tmp_path, sid, turn_id)


@pytest.mark.parametrize("event_type,status,payload,error,allowed", [
    ("turn_completed", "needs_continue", {}, None, True),
    ("turn_completed", "paused_limit", {}, None, True),
    ("turn_completed", "ready", {"finalStatus": "stopped_by_user"}, None, True),
    ("turn_interrupted", "interrupted", {}, None, True),
    ("turn_failed", "failed", {}, {"turn_id": "latest-turn", "reason_code": "iteration_limit_reached"}, True),
    ("turn_failed", "failed", {}, {"turnId": "latest-turn", "reasonCode": "iteration_limit_reached"}, True),
    ("turn_completed", "completed", {}, None, False),
    ("turn_failed", "failed_provider", {}, {"turnId": "latest-turn", "reasonCode": "budget_exceeded"}, False),
    ("turn_failed", "failed_provider", {}, {"turnId": "latest-turn", "message": "iteration_limit_reached"}, False),
    ("turn_failed", "failed", {}, {"turnId": "old-turn", "reasonCode": "iteration_limit_reached"}, False),
    ("turn_completed", "completed", {}, {"turnId": "latest-turn", "reasonCode": "iteration_limit_reached"}, False),
    ("turn_failed", "completed", {}, {"turnId": "latest-turn", "reasonCode": "iteration_limit_reached"}, False),
])
def test_continuation_requires_exact_recoverable_terminal(stopped_session, tmp_path, event_type, status,
                                                         payload, error, allowed):
    sid, _, scheduled = stopped_session
    expected = _terminal(tmp_path, sid, event_type, status, payload=payload, error=error)
    before = load_conversation_events(tmp_path, sid)
    state = session_service.load_session_chat_state(tmp_path, sid)
    if allowed:
        assert _continue(sid, expected)["accepted"] is True
        assert scheduled[0]["raw_user_message"] == "继续"
    else:
        with pytest.raises(session_service.SessionBusyError):
            _continue(sid, expected)
        assert load_conversation_events(tmp_path, sid) == before
        assert session_service.load_session_chat_state(tmp_path, sid) == state
        assert not scheduled


@pytest.mark.parametrize("kind", ["running", "queue", "open", "durable", "readonly", "unknown_owner", "companion", "lease"])
def test_continuation_rejection_never_repairs_or_writes(stopped_session, tmp_path, monkeypatch, kind):
    sid, expected, scheduled = stopped_session
    state = session_service.load_session_chat_state(tmp_path, sid)
    if kind == "running":
        session_service._set_session_running(sid, True, turn_id="new-running")
    elif kind == "queue":
        state["queued_turns"] = [{"id": "waiting", "content": "queued request", "status": "starting"}]
    elif kind == "open":
        append_conversation_event(tmp_path, sid, "open", "turn_started", status="running")
        expected["ledgerSeq"] = load_conversation_events(tmp_path, sid)[-1].sequence
    elif kind == "durable":
        session_service._persist_chat_turn_work_run(session_id=sid, turn_id="foreign-running",
                                                   status="running", user_message="foreign task")
    elif kind == "readonly":
        monkeypatch.setattr(session_service, "_conversation_is_read_only", lambda _: True)
    elif kind == "unknown_owner":
        state.pop("agent_id", None)
        state.pop("agentId", None)
    elif kind == "companion":
        from core.web.services import agent_directory_service
        with agent_directory_service.scoped_project_root(tmp_path):
            path = agent_directory_service._workspace_path("agents", "agents.json", intent="state", seed=False)
        directory = json.loads(path.read_text(encoding="utf-8"))
        next(a for a in directory["agents"] if a["agentId"] == expected["agentId"]).setdefault("metadata", {})["virtualHumanCompanion"] = True
        path.write_text(json.dumps(directory), encoding="utf-8")
    else:
        monkeypatch.setattr(session_service, "_check_chat_turn_lease_decision",
                            lambda _: SimpleNamespace(allowed=False, reason="busy", conflicts=[]))
    session_service.save_session_chat_state(tmp_path, sid, state)
    before = load_conversation_events(tmp_path, sid)
    state = session_service.load_session_chat_state(tmp_path, sid)
    monkeypatch.setattr(session_service, "_reconcile_stale_session_ledger", lambda *_a, **_kw: pytest.fail("reconcile"))
    monkeypatch.setattr(session_service, "_ensure_conversation_workspace_metadata", lambda *_a, **_kw: pytest.fail("workspace write"))
    monkeypatch.setattr(session_service, "save_session_chat_state", lambda *_a, **_kw: pytest.fail("state write"))
    monkeypatch.setattr(submit, "_enqueue_busy_session_turn", lambda *_a, **_kw: pytest.fail("queue write"))
    with pytest.raises((session_service.SessionBusyError, session_service.SessionValidationError)):
        _continue(sid, expected)
    assert load_conversation_events(tmp_path, sid) == before
    assert session_service.load_session_chat_state(tmp_path, sid) == state
    assert not scheduled


@pytest.mark.parametrize("kwargs", [{"queue_if_busy": True}, {"attachment_ids": ["image"]}, {"references": [{"id": "ref"}]}])
def test_continuation_cannot_queue_or_attach(stopped_session, kwargs):
    sid, expected, scheduled = stopped_session
    with pytest.raises(session_service.SessionValidationError):
        _continue(sid, expected, **kwargs)
    assert not scheduled


def test_accepted_continuation_replays_before_stale_guard_and_cannot_change_snapshot(stopped_session, tmp_path):
    sid, expected, scheduled = stopped_session
    first = _continue(sid, expected)
    append_conversation_event(tmp_path, sid, first["turnId"], "turn_completed", status="completed")
    append_conversation_event(tmp_path, sid, "newer", "turn_started", status="running")
    assert _continue(sid, expected)["turnId"] == first["turnId"]
    with pytest.raises(session_service.SessionValidationError):
        _continue(sid, {**expected, "ledgerSeq": 1})
    with pytest.raises(session_service.SessionBusyError):
        _continue(sid, expected, submission_id="another-tab")
    assert len(scheduled) == 1


def test_continuation_freezes_current_native_model_parameters(stopped_session, tmp_path, monkeypatch):
    sid, expected, scheduled = stopped_session
    state = session_service.load_session_chat_state(tmp_path, sid)
    parameters = submit.capture_model_parameters(session_service, state)
    assert parameters and parameters["agentId"] == expected["agentId"]
    monkeypatch.setattr(submit, "capture_model_parameters", lambda *_a, **_kw: dict(parameters))
    _continue(sid, expected)
    accepted = dict(parameters)
    parameters["contextWindow"] = 123
    context = scheduled[0]
    event = next(event for event in load_conversation_events(tmp_path, sid)
                 if event.event_type == "user_message" and event.correlation_id == "continue-1")
    assert context["model_parameters"] == accepted
    assert event.payload["metadata"]["modelParameters"] == accepted
    assert event.payload["metadata"]["modelParameters"]["contextWindow"] != parameters["contextWindow"]


def test_default_fingerprint_stays_compatible_and_legacy_continue_is_not_conditional(stopped_session, tmp_path):
    sid, expected, scheduled = stopped_session
    payload = {"attachmentIds": [], "references": [], "mentalModelEnabled": None,
               "runtimeStatusEnabled": None, "turnMode": "", "writeIntent": None,
               "messageMetadata": {}, "messageSource": "raw", "turnStatusTail": None, "modelSelection": None}
    base = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    native = hashlib.sha256(json.dumps({"content": "继续", "base": base}, ensure_ascii=False,
                                      sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    args = dict(attachment_ids=None, references=None, mental_model_enabled=None, runtime_status_enabled=None,
                turn_mode="", write_intent=None, message_metadata=None, message_source="raw",
                turn_status_tail=None, model_selection=None)
    assert submit._session_submission_fingerprint(content="继续", **args) == native
    append_conversation_event(tmp_path, sid, "legacy", "user_message", correlation_id="legacy-id",
                              payload={"content": "继续", "source": "raw"})
    with pytest.raises(session_service.SessionValidationError):
        _continue(sid, expected, submission_id="legacy-id")
    assert not scheduled


def test_new_native_request_wins_before_old_continue_without_queue(stopped_session, tmp_path, monkeypatch):
    sid, expected, scheduled = stopped_session
    first = submit.submit_session_message_lightweight(sid, "new user request", client_submission_id="new-request")
    before = load_conversation_events(tmp_path, sid)
    state = session_service.load_session_chat_state(tmp_path, sid)
    monkeypatch.setattr(submit, "_enqueue_busy_session_turn", lambda *_a, **_kw: pytest.fail("must not queue"))
    with pytest.raises(session_service.SessionBusyError):
        _continue(sid, expected)
    assert load_conversation_events(tmp_path, sid) == before
    assert session_service.load_session_chat_state(tmp_path, sid) == state
    assert len(scheduled) == 1 and scheduled[0]["turn_id"] == first["turnId"]


def test_compaction_checkpoint_survives_native_continuation(stopped_session, tmp_path):
    from core.chat.conversation_ledger import append_context_compression_checkpoint, conversation_model_messages_from_events

    sid, _, scheduled = stopped_session
    append_conversation_event(tmp_path, sid, "compact-turn", "turn_started", status="running")
    append_conversation_event(tmp_path, sid, "compact-turn", "user_message", payload={"content": "compress me"})
    checkpoint = append_context_compression_checkpoint(tmp_path, sid, turn_id="compact-turn",
        current_turn_id="compact-turn", summary="Preserved compressed context", level="standard",
        reason="context_pressure", before_tokens=9000, after_tokens=3000, iteration=5, trigger_source="auto")
    assert checkpoint is not None
    append_conversation_event(tmp_path, sid, "compact-turn", "turn_interrupted", status="stopped")
    expected = _snapshot(tmp_path, sid, "compact-turn")
    before = load_conversation_events(tmp_path, sid)
    _continue(sid, expected)
    events = load_conversation_events(tmp_path, sid)
    assert events[:len(before)] == before
    assert checkpoint in events
    content = "\n".join(str(message.get("content", "")) for message in conversation_model_messages_from_events(events))
    assert "Preserved compressed context" in content and "继续" in content
    assert scheduled[0]["raw_user_message"] == "继续"


def test_snapshot_check_and_acceptance_share_admission_lock(stopped_session, tmp_path, monkeypatch):
    sid, expected, scheduled = stopped_session
    entered, release = threading.Event(), threading.Event()
    original = submit.validate_continuation

    def guarded(*args):
        original(*args)
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(submit, "validate_continuation", guarded)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(_continue, sid, expected)
            assert entered.wait(5)
            competing = pool.submit(submit.submit_session_message_lightweight, sid, "new request",
                                    client_submission_id="competing-request")
            try:
                with pytest.raises(FutureTimeout):
                    competing.result(0.15)
            finally:
                release.set()
            assert first.result(10)["accepted"] is True
            with pytest.raises(session_service.SessionBusyError):
                competing.result(10)
    finally:
        release.set()
    assert len(scheduled) == 1
    assert not session_service.load_session_chat_state(tmp_path, sid).get("queued_turns")


def _continue_in_process(root, workspace, work_runs, expected, parameters, gate, output):
    import faulthandler
    from core.infrastructure import developer_sandbox
    from core.runtime_manager import scene_logging
    from core.runtime_manager.work_run_store import WorkRunStore
    from core.web.services import agent_directory_service, runtime_scene_service

    faulthandler.dump_traceback_later(35, exit=True)
    root = Path(root)
    developer_sandbox.resolve_workspace_home = lambda *_a, **_kw: Path(workspace)
    developer_sandbox.is_developer_mode_enabled = lambda: False
    session_service.PROJECT_ROOT = agent_directory_service.PROJECT_ROOT = runtime_scene_service.PROJECT_ROOT = root
    scene_logging.EVENTS_PATH = root / "runtime-events.jsonl"
    session_service._WORK_RUN_STORE = WorkRunStore(root=Path(work_runs))
    submit.capture_model_parameters = lambda *_a, **_kw: parameters
    session_service._session_context_limit_payload = lambda _: {"limit": 200000, "source": "test"}
    scheduled = []
    session_service._schedule_session_turn = lambda context: scheduled.append(context["turn_id"])
    try:
        assert gate.wait(10)
        result = _continue("session-live", expected)
        output.put({"turnId": result["turnId"], "scheduled": scheduled})
    except session_service.SessionBusyError:
        output.put({"busy": True, "scheduled": scheduled})
    except BaseException as exc:
        output.put({"error": f"{type(exc).__name__}: {exc}"})


@pytest.mark.parametrize("new_request_first", [False, True])
def test_continuation_fences_other_backend(stopped_session, tmp_path, new_request_first):
    from core.infrastructure import developer_sandbox

    sid, expected, scheduled = stopped_session
    state = session_service.load_session_chat_state(tmp_path, sid)
    parameters = submit.capture_model_parameters(session_service, state)
    if new_request_first:
        submit.submit_session_message_lightweight(sid, "new request", client_submission_id="other-backend-first")
    before = load_conversation_events(tmp_path, sid)
    ctx = multiprocessing.get_context("spawn")
    gate, output = ctx.Event(), ctx.Queue()
    processes = [ctx.Process(target=_continue_in_process, args=(str(tmp_path),
        str(developer_sandbox.resolve_workspace_home(tmp_path)), str(session_service._WORK_RUN_STORE.root),
        expected, parameters, gate, output)) for _ in range(2)]
    try:
        for process in processes:
            process.start()
        gate.set()
        for process in processes:
            process.join(40)
        assert [process.exitcode for process in processes] == [0, 0]
        results = [output.get(timeout=3) for _ in processes]
        assert not [row for row in results if row.get("error")], results
        events = load_conversation_events(tmp_path, sid)
        if new_request_first:
            assert all(row.get("busy") for row in results), results
            assert events == before
            assert len(scheduled) == 1
        else:
            assert results[0]["turnId"] == results[1]["turnId"]
            assert sum(len(row["scheduled"]) for row in results) == 1
            assert events[:len(before)] == before
            assert len([e for e in events if e.event_type == "user_message" and e.correlation_id == "continue-1"]) == 1
        assert not session_service.load_session_chat_state(tmp_path, sid).get("queued_turns")
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(3)


def test_continuation_http_requires_strict_snapshot_and_native_acceptance(stopped_session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.web.routes.sessions import router

    sid, expected, scheduled = stopped_session
    app = FastAPI()
    app.include_router(router)
    payload = {"content": "继续", "clientSubmissionId": "http-continue", "continuation": expected}
    with TestClient(app) as client:
        url = f"/sessions/{sid}/messages"
        for key in expected:
            partial = {k: v for k, v in expected.items() if k != key}
            assert client.post(url, json={**payload, "continuation": partial}).status_code == 422
        for invalid in ({**expected, "ledgerSeq": True}, {**expected, "ledgerSeq": "4"},
                        {**expected, "turnId": 1}, {**expected, "headId": " "},
                        {**expected, "extra": "no"}, {**expected, "agentId": "x" * 161}):
            assert client.post(url, json={**payload, "continuation": invalid}).status_code == 422
        assert client.post(url, json={**payload, "content": "original request"}).status_code == 422
        assert client.post(url, json={**payload, "queueIfBusy": True}).status_code == 422
        assert client.post(url, json={**payload, "continuation": {**expected, "turnId": "stale"}}).status_code == 409
        first = client.post(url, json=payload, headers={"Prefer": "respond-async"})
        assert first.status_code == 202, first.text
        assert first.json()["clientSubmissionId"] == "http-continue"
        # Both response preferences use the same journal replay, so a transport
        # retry cannot create another user message or rerun the old request.
        replay = client.post(url, json=payload)
        assert replay.status_code == 202, replay.text
        assert replay.json()["turnId"] == first.json()["turnId"]
    assert len(scheduled) == 1


def test_old_and_new_http_preferences_share_optional_schema(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.web.routes import sessions

    app = FastAPI()
    app.include_router(sessions.router)
    seen = []
    accepted = {"accepted": True, "sessionId": "s", "turnId": "t", "status": "running"}
    def record(*args, **kwargs):
        seen.append(kwargs)
        return accepted
    monkeypatch.setattr(sessions, "submit_session_message_lightweight", record)
    monkeypatch.setattr(sessions, "submit_session_message", record)
    expected = {"turnId": "old", "headId": "head", "ledgerSeq": 5, "agentId": "agent"}
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
        ref = schema["paths"]["/sessions/{session_id}/messages"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        message_schema = schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]
        assert "continuation" in message_schema["properties"]
        assert "continuation" not in message_schema.get("required", [])
        for headers in ({}, {"Prefer": "respond-async"}):
            for continuation in (None, expected):
                payload = {"content": "继续", "clientSubmissionId": "sub"}
                if continuation is not None:
                    payload["continuation"] = continuation
                response = client.post("/sessions/s/messages", json=payload, headers=headers)
                assert response.status_code == 202, response.text
                assert seen[-1]["_continuation_expected"] == continuation
                assert seen[-1]["queue_if_busy"] is False


def test_shared_continuation_fixture_preserves_strict_snapshot_contract():
    from core.web.routes.sessions import SessionContinuationPayload, SessionMessagePayload

    path = Path(__file__).parent / "fixtures" / "session_continuation_request.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    snapshot = SessionContinuationPayload.model_validate(fixture["continuation"], strict=True)
    assert snapshot.model_dump() == fixture["continuation"] == {
        "turnId": "turn-stopped", "headId": "leaf-stopped", "ledgerSeq": 12, "agentId": "A001",
    }
    request = SessionMessagePayload.model_validate(fixture, strict=True)
    assert request.model_dump(include=set(fixture)) == fixture
    assert request.content == fixture["content"] == "继续"
    assert request.contentUtf8Base64 == fixture["contentUtf8Base64"] == "57un57ut"
    assert request.queueIfBusy is fixture["queueIfBusy"] is False
    assert request.continuation is not None
    assert request.continuation.model_dump() == snapshot.model_dump()
