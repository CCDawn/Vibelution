from dataclasses import replace
from pathlib import Path

import pytest
from core.infrastructure import developer_sandbox
from core.ui.chat_state import load_session_chat_state, save_chat_state
from core.web.services import session_service
from core.web.services.external_agent.approval_binding import (
    ApprovalBindingError, register_external_session, unregister_external_session,
    validate_external_session_submit,
)
from core.web.services.session import queued_turns, worker
from tests.test_external_agent_task_service import FakeRuntime, _service


def test_external_persisted_queue_is_not_claimed_after_binding_loss(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", Path(tmp_path))
    monkeypatch.setattr(session_service, "_is_session_running", lambda *_: False)
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", lambda *_: None)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda *_args, **_kwargs: None)
    session_id = "external-queued-session"
    save_chat_state(tmp_path, {"version": 1, "active_conversation_id": session_id, "conversations": [{
        "conversation_id": session_id, "title": "external", "agent_id": "coder",
        "metadata": {"source": "external_agent_task", "externalTaskId": "task-1", "effectivePermissionProfile": "read_only"},
    }]})
    queued_turns.enqueue_session_queued_turn(session_id, content="queued", attachments=[], references=[],
        mental_model_enabled=None, runtime_status_enabled=None, turn_mode="", write_intent=False,
        client_submission_id="queue-id")
    submitted = []
    real_submit = session_service.submit_session_message
    monkeypatch.setattr(session_service, "submit_session_message", lambda *a, **kw: submitted.append((a, kw)))
    assert queued_turns.drain_session_queued_turns(session_id) is False
    rows = queued_turns.session_queued_turn_rows(load_session_chat_state(tmp_path, session_id))
    assert len(rows) == 1 and rows[0]["status"] == "queued"
    assert submitted == []
    monkeypatch.setattr(session_service, "submit_session_message", real_submit)
    with pytest.raises(session_service.SessionValidationError):
        session_service.submit_session_message(session_id, "direct bypass")
    with pytest.raises(session_service.SessionValidationError):
        session_service.regenerate_session_message(session_id, "message-1")
    assert len(queued_turns.session_queued_turn_rows(load_session_chat_state(tmp_path, session_id))) == 1


def test_native_submit_requires_matching_live_identity_and_profile():
    conversation = {"agent_id": "coder", "metadata": {"source": "external_agent_task",
        "externalTaskId": "task-1", "effectivePermissionProfile": "read_only"}}
    message = {"source": "external_agent_task", "taskId": "task-1", "effectivePermissionProfile": "read_only"}
    kwargs = dict(conversation=conversation, session_id="external-proof", message_source="external_agent_task",
                  message_metadata=message)
    with pytest.raises(ApprovalBindingError):
        validate_external_session_submit(**kwargs)
    register_external_session(task_id="task-1", session_id="external-proof", agent_id="coder")
    try:
        validate_external_session_submit(**kwargs)
        with pytest.raises(ApprovalBindingError):
            validate_external_session_submit(**{**kwargs, "message_metadata": {**message, "effectivePermissionProfile": "full_access"}})
        assert worker._external_agent_runtime_permission_profile({
            "raw_user_message_source": "external_agent_task", "user_message_source": "transformed",
            "message_metadata": message,
        }) == "read_only"
    finally:
        unregister_external_session(task_id="task-1", session_id="external-proof", agent_id="coder")


def test_failed_stop_is_retried_for_same_turn(tmp_path):
    runtime = FakeRuntime()
    service = _service(tmp_path, runtime)
    started = service.start_task(owner_id="owner", adapter_connection_id="connection", capabilities=set(),
        agent_id="coder", task="bounded", permission_profile="read_only", client_request_id="stop-retry",
        title="", runtime_revision="revision")
    record = service.store.get_task(started["taskId"])
    attempts = []
    def stop(session_id, *, expected_turn_id=""):
        attempts.append((session_id, expected_turn_id))
        if len(attempts) == 1:
            raise RuntimeError("stop unavailable")
        return runtime.stop_turn(session_id, expected_turn_id=expected_turn_id)
    service.dependencies = replace(service.dependencies, stop_turn=stop)
    first = service.cancel_task(owner_id="owner", task_id=record["taskId"])
    assert first["status"] == "stop_unconfirmed"
    second = service.get_task(owner_id="owner", task_id=record["taskId"])
    assert second["status"] == "stop_unconfirmed"
    assert attempts == [(record["sessionId"], record["turnId"])] * 2
