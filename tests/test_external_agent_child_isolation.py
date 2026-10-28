import pytest
from fastapi import HTTPException

from core.infrastructure import developer_sandbox
from core.ui.chat_state import load_session_chat_state, save_session_chat_state
from core.web.routes.sessions import session_create_child_session, ChildSessionCreatePayload
from core.web.services import session_service as s
from core.web.services.external_agent.approval_binding import (
    register_external_session, unregister_external_session,
)
from tests.test_chat_state_persistence import _seed_two_runtime_rows


@pytest.mark.parametrize("metadata,bound,bound_agent", [
    ({"source": "external_agent_task", "externalTaskId": "task-a"}, False, "agent-a"),
    ({"source": "external_agent_task"}, False, "agent-a"),
    ({"source": "wrong", "externalTaskId": ""}, False, "agent-a"),
    ({}, True, "agent-a"),
    ({}, True, "different-agent"),
])
def test_external_parent_refused_before_child_creation(tmp_path, monkeypatch, metadata, bound, bound_agent):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)
    monkeypatch.setattr(s, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    parent = load_session_chat_state(tmp_path, "session-a")
    parent.update({"agent_id": "agent-a", "metadata": metadata})
    save_session_chat_state(tmp_path, "session-a", parent)
    before = set(s.list_session_runtime_ids(tmp_path))
    if bound:
        register_external_session(task_id="task-a", session_id="session-a", agent_id=bound_agent)
    try:
        with pytest.raises(HTTPException) as exc:
            session_create_child_session("session-a", ChildSessionCreatePayload(userRequest="x", autoStart=False))
        assert exc.value.status_code == 422
        assert set(s.list_session_runtime_ids(tmp_path)) == before
        assert not load_session_chat_state(tmp_path, "session-a").get("child_session_ids")
    finally:
        if bound:
            unregister_external_session(task_id="task-a", session_id="session-a", agent_id=bound_agent)


def test_child_of_external_root_also_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)
    monkeypatch.setattr(s, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    root = load_session_chat_state(tmp_path, "session-a")
    root["metadata"] = {"externalTaskId": "task-a"}
    save_session_chat_state(tmp_path, "session-a", root)
    child = load_session_chat_state(tmp_path, "session-b")
    child.update({"session_kind": "child", "root_session_id": "session-a", "parent_session_id": "session-a"})
    save_session_chat_state(tmp_path, "session-b", child)
    before = set(s.list_session_runtime_ids(tmp_path))
    with pytest.raises(s.SessionValidationError):
        s.create_child_session("session-b", user_request="x", auto_start=False)
    assert set(s.list_session_runtime_ids(tmp_path)) == before
