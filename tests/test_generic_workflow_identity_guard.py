from pathlib import Path

import pytest

from core.infrastructure import developer_sandbox
from core.ui.chat_state import load_session_chat_state
from core.web.services import agent_directory_service, session_service
from core.web.services.session import queued_turns, startup_recovery
from core.web.services.team_workflow.generic import native, service as workflow_service
from core.web.services.external_agent.approval_binding import (
    ApprovalBindingError, is_external_session, register_external_session,
    unregister_external_session, validate_external_session_submit,
)


def test_real_generic_native_session_submits_and_remains_recoverable(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr(session_service, "PROJECT_ROOT", Path(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", Path(tmp_path))
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", Path(tmp_path))
    monkeypatch.setattr(session_service, "_session_context_limit_payload", lambda _: {"limit": 128000, "source": "test"})
    scheduled = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", scheduled.append)
    monkeypatch.setattr(session_service, "_enqueue_direct_session_submit_kernel_trace", lambda **_: None)
    visible = session_service.create_chat_session(title="Visible", lightweight=True)
    attempt = {"key": "gw-" + workflow_service.digest(["target", "run", "step", 1])[:48], "agentId": visible["agentId"]}
    attempt["sessionId"] = native.create(attempt, {"flow": {"name": "流程"}}, {"label": "步骤"})
    attempt["turnId"] = native.submit(attempt, "执行团队步骤")
    conversation = load_session_chat_state(tmp_path, attempt["sessionId"])
    assert conversation["metadata"] == {"source": "generic_team_workflow", "externalTaskId": attempt["key"]}
    assert scheduled and scheduled[0]["raw_user_message_source"] == "generic_team_workflow"
    assert not is_external_session(conversation)
    drains, resumes = [], []
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", drains.append)
    queued_turns.enqueue_session_queued_turn(attempt["sessionId"], content="queued", attachments=[], references=[],
        mental_model_enabled=None, runtime_status_enabled=None, turn_mode="", write_intent=False, client_submission_id="q")
    drains.clear()
    monkeypatch.setattr(session_service, "_is_session_running", lambda _: False)
    monkeypatch.setattr(session_service, "_load_session_conversation_events_cached", lambda _: [object()])
    monkeypatch.setattr(startup_recovery, "latest_open_turn_id", lambda _: attempt["turnId"])
    monkeypatch.setattr(startup_recovery, "_resume_interrupted_turn", lambda *_args, **kw: resumes.append(kw["open_turn_id"]))
    summary = startup_recovery._new_summary()
    startup_recovery._recover_session_on_startup(session_service, attempt["sessionId"], companion_session_ids=set(), summary=summary)
    assert drains == [attempt["sessionId"]]
    assert resumes == [attempt["turnId"]]
    drained = []
    monkeypatch.setattr(session_service, "submit_session_message", lambda *args, **kwargs: drained.append((args, kwargs)))
    assert queued_turns.drain_session_queued_turns(attempt["sessionId"])
    assert len(drained) == 1 and drained[0][0][1] == "queued"


@pytest.mark.parametrize("metadata", [
    {"externalTaskId": "eat-" + "a" * 32},
    {"source": "external_agent_task"},
    {"effectivePermissionProfile": "read_only"},
    {"source": "generic_team_workflow", "externalTaskId": "eat-" + "a" * 32},
    {"source": "generic_team_workflow", "externalTaskId": "gw-" + "a" * 48, "effectivePermissionProfile": "read_only"},
    {"externalTaskId": "gw-" + "a" * 48},
    {"source": "generic_team_workflow", "externalTaskId": "gw-malformed"},
])
def test_incomplete_external_identity_remains_fail_closed(metadata):
    conversation = {"conversation_id": "unknown-session", "metadata": metadata}
    assert is_external_session(conversation)
    with pytest.raises(ApprovalBindingError):
        validate_external_session_submit(conversation=conversation, session_id="unknown-session",
                                         message_source="raw", message_metadata={})


def test_live_external_binding_overrides_generic_looking_metadata():
    conversation = {"conversation_id": "bound-session", "agent_id": "agent-a",
                    "metadata": {"source": "generic_team_workflow", "externalTaskId": "gw-" + "a" * 48}}
    register_external_session(task_id="task-a", session_id="bound-session", agent_id="agent-a")
    try:
        assert is_external_session(conversation)
    finally:
        unregister_external_session(task_id="task-a", session_id="bound-session", agent_id="agent-a")
