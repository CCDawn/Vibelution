"""Configured native creation with an isolated, real SQLite conversation store."""
from __future__ import annotations

import pytest


@pytest.fixture
def configured_env(tmp_path, monkeypatch):
    from core.chat.conversation_store import ConversationStore
    from core.web.services import agent_directory_service as directory
    from core.web.services import session_service as sessions
    from core.web.services import team_template_service as templates
    from core.web.services.session import directory_runtime
    from tests.test_agent_config_workspace_service import (
        _seed_agent_avatars,
        _use_tmp_project_root,
    )

    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_agent_avatars(tmp_path)
    monkeypatch.setattr(templates, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sessions, "default_session_llm_bindings", lambda: {"dialogue": {"modelId": "model-primary"}})
    monkeypatch.setattr(sessions, "_ensure_session_agent_prompt_snapshot", lambda *_args, **_kwargs: None)
    store = ConversationStore(tmp_path / "workspace/chat/conversations.sqlite3")
    store.open()
    monkeypatch.setattr(directory_runtime, "get_open_directory_store", lambda: store)
    monkeypatch.setattr(directory_runtime, "directory_store_project_root", lambda: tmp_path)
    monkeypatch.setattr(directory_runtime, "is_directory_store_open", lambda: True)
    try:
        yield {"root": tmp_path, "directory": directory, "sessions": sessions, "store": store, "templates": templates}
    finally:
        store.close()


def test_configured_creation_publishes_every_field_before_first_session_sync(configured_env, monkeypatch):
    from core.web.services import agent_operation_service as operations
    env = configured_env
    directory, sessions, store = env["directory"], env["sessions"], env["store"]
    create = operations.create_configured_agent_with_session
    observations = []
    save = directory.save_state

    def observe(state):
        result = save(state)
        for row in state.get("agents", []):
            if row.get("createdBy") == "configured-test":
                policy = row["toolPolicy"]
                assert policy["allowedTools"] == []
                assert policy["networkAccess"] == "none" and policy["mutationAccess"] == "none"
                observations.append(bool(row.get("directSessionId")))
        return result

    monkeypatch.setattr(directory, "save_state", observe)
    before = sessions.load_active_conversation_id(env["root"])
    avatar = "workspace/avatars/" + directory.AGENT_AVATAR_FILENAMES[0]
    agent = create(display_name="Configured", llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat", role_key="configured_worker", prompt_template_id="prompt-chat-default",
        tool_policy={"allowedTools": [], "preferredTools": [], "networkAccess": "none", "mutationAccess": "none"},
        persona_profile={"personality": "Careful"}, task_profile={"mission": "Report verified evidence."},
        permission_preset="request_approval", delegation_policy={"allowSubagents": False, "allowWakeMessages": False},
        avatar_image_path=avatar, source="configured-test", session_idempotency_key="original-request")
    assert observations and observations[0] is False and observations[-1] is True
    assert sessions.load_active_conversation_id(env["root"]) == before
    snapshot = store.repository.get_current_agent_config(agent["agentId"])
    config = snapshot["config"]
    assert config["toolPolicy"]["allowedTools"] == []
    assert config["permissionPreset"] == "request_approval"
    assert config["personaProfile"]["personality"] == "Careful"
    assert config["taskProfile"]["mission"] == "Report verified evidence."
    assert config["delegationPolicy"]["allowWakeMessages"] is False
    row = store.repository.get_session(agent["directSessionId"])
    assert row["agentId"] == agent["agentId"] and row["agentConfigRevisionId"] == snapshot["configRevisionId"]
    assert agent["avatarImagePath"] == avatar


def test_failed_session_ack_does_not_reenter_agent_or_session_creation(configured_env, monkeypatch):
    from core.web.services import agent_operation_service as operations
    env = configured_env
    calls = []
    native_create = env["directory"].create_agent_instance

    def create(**kwargs):
        calls.append("agent")
        return native_create(**kwargs)

    def lost_ack(**kwargs):
        calls.append("session")
        raise RuntimeError("unconfirmed native session acknowledgement")

    monkeypatch.setattr(env["directory"], "create_agent_instance", create)
    monkeypatch.setattr(env["sessions"], "create_chat_session", lost_ack)
    with pytest.raises(RuntimeError, match="unconfirmed"):
        operations.create_configured_agent_with_session(display_name="Unknown", primary_mode="chat", role_key="configured_worker",
            prompt_template_id="prompt-chat-default", llm_bindings={"dialogue": {"modelId": "model-primary"}},
            tool_policy={"allowedTools": []}, source="configured-test", session_idempotency_key="same-original-key")
    assert calls == ["agent", "session"]
    targets = [row for row in env["directory"].load_state()["agents"] if row.get("createdBy") == "configured-test"]
    assert len(targets) == 1 and not targets[0].get("directSessionId")


def test_roleless_chat_rejects_profiles_before_any_creation(configured_env, monkeypatch):
    from core.web.services import agent_operation_service as operations
    monkeypatch.setattr(configured_env["directory"], "create_agent_instance", lambda **_kwargs: pytest.fail("creation must not start"))
    with pytest.raises(operations.AgentDirectoryError):
        operations.create_configured_agent_with_session(display_name="Roleless", primary_mode="chat", role_key="",
            prompt_template_id="prompt-chat-default", llm_bindings={"dialogue": {"modelId": "model-primary"}},
            tool_policy={"allowedTools": []}, task_profile={"mission": "Native chat strips this"})
