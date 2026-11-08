"""Real native admission/journal coverage for operator control handoff sends."""

import threading

import pytest

from core.assistant_runtime.control_continuation import (
    CONTROL_CONTINUATION_MESSAGE as MESSAGE,
)


@pytest.fixture
def control_session(tmp_path, monkeypatch):
    from core.assistant_runtime import native
    from core.chat.conversation_branches import analyze_conversation_branches
    from core.chat.conversation_ledger import (
        append_conversation_event,
        load_conversation_events,
    )
    from core.web.services import session_service as sessions
    from tests.helpers.web_chat_state import _reset_seeded_session_runtime
    from tests.test_session_submit import _prepare_default_submit_session

    sid = _prepare_default_submit_session(tmp_path, monkeypatch)
    for kind, payload in (("turn_started", {}), ("user_message", {"content": "original request"}),
                          ("assistant_message", {"content": "permission requested"}),
                          ("turn_completed", {"finalStatus": "completed"})):
        append_conversation_event(tmp_path, sid, "old-turn", kind, payload=payload,
                                  status="completed" if kind == "turn_completed" else "")
    events = load_conversation_events(tmp_path, sid)
    agent_id = sessions.load_session_chat_state(tmp_path, sid)["agent_id"]
    expected = {"turnId": "old-turn", "headId": analyze_conversation_branches(events).active_leaf_id,
                "ledgerSeq": events[-1].sequence, "agentId": agent_id, "sessionId": sid}
    identity = {"agentId": agent_id, "directSessionId": sid}
    monkeypatch.setattr(native, "_STARTED", True)
    monkeypatch.setattr(native, "_SESSION_ID", sid)
    monkeypatch.setattr(native, "_AGENT_ID", agent_id)
    monkeypatch.setattr(native, "_STOP_REQUESTED", threading.Event())
    monkeypatch.setattr(native, "_projection", lambda: {"assistant": identity})
    scheduled = []
    monkeypatch.setattr(sessions, "_schedule_session_turn", lambda context: scheduled.append(context))
    yield native, sessions, sid, expected, scheduled, identity
    _reset_seeded_session_runtime(sid)


def send(context, request_id="control-1", **changes):
    native, _, _, expected, _, _ = context
    return native.submit(MESSAGE, request_id, control_continuation={**expected, **changes})


def test_real_http_facade_reaches_native_admission_and_replays_one_turn(control_session, tmp_path):
    """Exercise the actual production adapter, not an accepting fake submit."""
    from fastapi.testclient import TestClient

    from core.assistant_runtime.host import NativeFacade, create_app
    from core.chat.conversation_ledger import load_conversation_events

    _, _, sid, expected, scheduled, _ = control_session
    # The fixture already seeds the real native owner. Do not start its
    # unrelated reminder/lifecycle services against a synthetic profile.
    client = TestClient(create_app(native=NativeFacade(tmp_path), token="control-facade-test"),
                        base_url="http://127.0.0.1", headers={"Authorization": "Bearer control-facade-test"})
    body = {"message": MESSAGE, "requestId": "http-control-original", "controlContinuation": expected}
    try:
        first = client.post("/api/assistant/messages", json=body)
        assert first.status_code == 200 and first.json()["accepted"] is True
        replay = client.post("/api/assistant/messages", json=body)
        assert replay.status_code == 200 and replay.json()["turnId"] == first.json()["turnId"]
    finally:
        client.close()
    users = [event for event in load_conversation_events(tmp_path, sid)
             if event.event_type == "user_message" and event.correlation_id == body["requestId"]]
    assert len(users) == len(scheduled) == 1
    assert users[0].payload["metadata"]["assistantControlContinuation"] == expected


def test_acceptance_replay_uses_exact_native_receipt_after_its_own_head_advance(control_session, tmp_path):
    from core.chat.conversation_ledger import load_conversation_events

    first = send(control_session)
    second = send(control_session)
    native, _, sid, expected, scheduled, _ = control_session
    assert first["turnId"] == second["turnId"] and len(scheduled) == 1
    users = [event for event in load_conversation_events(tmp_path, sid) if event.event_type == "user_message"]
    assert len([event for event in users if event.correlation_id == "control-1"]) == 1
    assert users[-1].payload["metadata"]["assistantControlContinuation"] == expected
    assert users[-1].payload["metadata"]["clientSubmissionFingerprint"]
    with pytest.raises(native.AssistantSessionError, match="SESSION_CONFLICT"):
        send(control_session, headId="different-head")
    assert len(scheduled) == 1


@pytest.mark.parametrize("field,value", [("agentId", "other"), ("sessionId", "other"),
                                         ("turnId", "other"), ("headId", "other"), ("ledgerSeq", 1)])
def test_stale_identity_or_snapshot_has_zero_writes(control_session, tmp_path, field, value):
    from core.chat.conversation_ledger import load_conversation_events

    native, sessions, sid, _, scheduled, _ = control_session
    before = load_conversation_events(tmp_path, sid)
    state = sessions.load_session_chat_state(tmp_path, sid)
    with pytest.raises(native.AssistantSessionError):
        send(control_session, **{field: value})
    assert load_conversation_events(tmp_path, sid) == before
    assert sessions.load_session_chat_state(tmp_path, sid) == state and not scheduled


@pytest.mark.parametrize("key,value", [
    ("queued_turns", [{"id": "queued", "content": "next", "status": "queued"}]),
    ("queued_turns", {"unknown": True}),
    ("queued_turn_hold", {"reason": "user_stop", "turnId": "old-turn"}),
    ("pendingQuestion", {"id": "pending-question", "questionText": "Continue?", "consumedAt": ""}),
])
def test_queue_hold_and_pending_question_are_never_consumed(control_session, tmp_path, key, value):
    from core.chat.conversation_ledger import load_conversation_events

    native, sessions, sid, _, scheduled, _ = control_session
    state = sessions.load_session_chat_state(tmp_path, sid)
    state[key] = value
    sessions.save_session_chat_state(tmp_path, sid, state)
    state = sessions.load_session_chat_state(tmp_path, sid)
    before = load_conversation_events(tmp_path, sid)
    with pytest.raises(native.AssistantSessionError, match="SESSION_CONFLICT"):
        send(control_session)
    assert sessions.load_session_chat_state(tmp_path, sid) == state
    assert load_conversation_events(tmp_path, sid) == before and not scheduled


@pytest.mark.parametrize("approvals", [[{"status": "pending"}], [{}], None])
def test_pending_or_unknown_native_approval_is_rejected(control_session, monkeypatch, approvals):
    from core.web.services.session import tool_approvals

    monkeypatch.setattr(tool_approvals, "list_tool_approval_requests", lambda _: approvals)
    with pytest.raises(control_session[0].AssistantSessionError, match="SESSION_CONFLICT"):
        send(control_session)
    assert not control_session[4]


def test_plain_same_text_request_is_not_a_control_acceptance(control_session, tmp_path):
    from core.chat.conversation_branches import analyze_conversation_branches
    from core.chat.conversation_ledger import (
        append_conversation_event,
        load_conversation_events,
    )

    native, _, sid, expected, scheduled, _ = control_session
    append_conversation_event(tmp_path, sid, "same-text", "user_message",
                              payload={"content": MESSAGE}, correlation_id="control-1")
    append_conversation_event(tmp_path, sid, "same-text", "turn_completed", status="completed")
    events = load_conversation_events(tmp_path, sid)
    expected.update(turnId="same-text", headId=analyze_conversation_branches(events).active_leaf_id,
                    ledgerSeq=events[-1].sequence)
    with pytest.raises(native.AssistantSessionError, match="SESSION_CONFLICT"):
        send(control_session)
    assert not scheduled


def test_partial_request_receipt_is_not_reopened(control_session, tmp_path):
    from core.chat.conversation_branches import analyze_conversation_branches
    from core.chat.conversation_ledger import (
        append_conversation_event,
        load_conversation_events,
    )

    native, _, sid, expected, scheduled, _ = control_session
    append_conversation_event(tmp_path, sid, "unknown-request", "turn_started", correlation_id="control-1")
    append_conversation_event(tmp_path, sid, "unknown-request", "turn_completed", status="completed")
    events = load_conversation_events(tmp_path, sid)
    expected.update(headId=analyze_conversation_branches(events).active_leaf_id, ledgerSeq=events[-1].sequence)
    with pytest.raises(native.AssistantSessionError, match="SESSION_CONFLICT"):
        send(control_session)
    assert not scheduled


def test_matching_control_metadata_still_requires_the_native_request_fingerprint(control_session, tmp_path):
    from core.chat.conversation_ledger import (
        append_conversation_event,
        load_conversation_events,
    )

    native, _, sid, expected, scheduled, _ = control_session
    append_conversation_event(tmp_path, sid, "forged-receipt", "user_message", correlation_id="control-1",
                              payload={"content": MESSAGE, "source": "raw", "metadata": {
                                  "assistantControlContinuation": dict(expected),
                                  "clientSubmissionFingerprint": "0" * 64,
                              }})
    before = load_conversation_events(tmp_path, sid)
    with pytest.raises(native.AssistantSessionError, match="SESSION_INVALID"):
        send(control_session)
    assert load_conversation_events(tmp_path, sid) == before and not scheduled


def test_control_store_only_receipt_cannot_reopen_unknown_request(control_session, monkeypatch, tmp_path):
    from core.chat.conversation_ledger import load_conversation_events
    from core.web.services.session import admission

    class ReservedOnly:
        def existing(self, **_kwargs):
            return {"turnId": "unknown-turn", "state": "reserved"}

    native, _, sid, _, scheduled, _ = control_session
    monkeypatch.setattr(admission, "get_development_submission_admission_runtime", lambda _: ReservedOnly())
    before = load_conversation_events(tmp_path, sid)
    with pytest.raises(native.AssistantSessionError, match="SESSION_CONFLICT"):
        send(control_session)
    assert load_conversation_events(tmp_path, sid) == before and not scheduled


@pytest.mark.parametrize("change", [{"ledgerSeq": True}, {"ledgerSeq": "4"}, {"sessionId": " "},
                                  {"headId": " head "}, {"extra": True}])
def test_control_snapshot_requires_all_five_fields_with_strict_types(control_session, change):
    native, _, _, expected, _, _ = control_session
    with pytest.raises(native.AssistantSessionError, match="SESSION_INVALID"):
        native.submit(MESSAGE, "control-invalid", control_continuation={**expected, **change})


def test_control_holds_shared_admission_lock_through_reentrant_native_acceptance(control_session, monkeypatch):
    from core.web.services.session.admission_lock import SessionAdmissionLock

    _, sessions, sid, _, scheduled, _ = control_session
    entered, release = threading.Event(), threading.Event()
    real_submit = sessions.submit_session_message
    errors, result = [], []

    def guarded_submit(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return real_submit(*args, **kwargs)

    def worker():
        try:
            result.append(send(control_session))
        except Exception as exc:  # noqa: BLE001 - return all worker failures to the asserting thread.
            errors.append(exc)

    monkeypatch.setattr(sessions, "submit_session_message", guarded_submit)
    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert entered.wait(3)
        with pytest.raises(sessions.SessionBusyError):
            SessionAdmissionLock(sessions.PROJECT_ROOT, sid).acquire(timeout=0.03)
    finally:
        release.set()
        thread.join(timeout=3)
    assert not thread.is_alive() and not errors and result and len(scheduled) == 1


def test_recheck_after_waiting_for_real_admission_rejects_new_journal_head(control_session, tmp_path):
    from core.chat.conversation_ledger import (
        append_conversation_event,
        load_conversation_events,
    )
    from core.web.services.session.admission_lock import SessionAdmissionLock

    native, sessions, sid, _, scheduled, _ = control_session
    entered = threading.Event()
    errors = []

    def worker():
        entered.set()
        try:
            send(control_session)
        except native.AssistantSessionError as exc:
            errors.append(exc.code)

    with SessionAdmissionLock(sessions.PROJECT_ROOT, sid):
        thread = threading.Thread(target=worker)
        thread.start()
        assert entered.wait(3)
        append_conversation_event(tmp_path, sid, "new-user", "user_message", payload={"content": "new command"})
        append_conversation_event(tmp_path, sid, "new-user", "turn_completed", status="completed")
        before = load_conversation_events(tmp_path, sid)
    thread.join(timeout=3)
    assert not thread.is_alive() and errors == ["SESSION_CONFLICT"]
    assert load_conversation_events(tmp_path, sid) == before and not scheduled


def test_old_queued_rpc_cannot_rebind_after_native_identity_migration(control_session, monkeypatch):
    native, _, _, _, scheduled, identity = control_session
    entered, errors = threading.Event(), []

    def worker():
        entered.set()
        try:
            send(control_session)
        except native.AssistantSessionError as exc:
            errors.append(exc.code)

    with native._LOCK:
        thread = threading.Thread(target=worker)
        thread.start()
        assert entered.wait(3)
        monkeypatch.setattr(native, "_SESSION_ID", "migrated-session")
        monkeypatch.setattr(native, "_AGENT_ID", "migrated-agent")
        identity.update(agentId="migrated-agent", directSessionId="migrated-session")
    thread.join(timeout=3)
    assert not thread.is_alive() and errors == ["ASSISTANT_IDENTITY_INVALID"] and not scheduled
