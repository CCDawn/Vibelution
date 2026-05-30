import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.infrastructure.tool_executor import ToolExecutor
from core.ui.chat_state import load_chat_state, save_chat_state
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import agents as agents_route
from core.web.services import (
    agent_directory_service,
    agent_mode_binding_service,
    chat_room_service,
    conversation_service,
    prompt_template_service,
    research_organization_service,
    self_evolution_control_service,
    session_service,
    supervised_agent_service,
)


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(self_evolution_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        self_evolution_control_service,
        "ROLLBACK_ROOT",
        tmp_path / "workspace" / "web_self_evolution",
    )
    monkeypatch.setattr(supervised_agent_service, "PROJECT_ROOT", tmp_path)


class _FakeResearchWorkspace:
    def __init__(self, root):
        self.root = root / "workspace"

    def get_research_organization_path(self):
        return self.root / "research" / "organization_graph.json"

    def read_research_organization(self):
        path = self.get_research_organization_path()
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def write_research_organization(self, data):
        path = self.get_research_organization_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return True


def _use_tmp_research_org_workspace(tmp_path, monkeypatch):
    workspace = _FakeResearchWorkspace(tmp_path)
    monkeypatch.setattr(research_organization_service, "get_workspace", lambda: workspace)
    monkeypatch.setattr(research_organization_service, "record_research_scene_event", lambda *args, **kwargs: None)
    return workspace


def _seed_chat_sessions(root):
    save_chat_state(
        root,
        {
            "version": 1,
            "active_conversation_id": "session-alpha",
            "conversations": [
                {
                    "conversation_id": "session-alpha",
                    "title": "Alpha Agent",
                    "updated_at": "2026-05-26T10:00:00",
                    "messages": [{"role": "user", "content": "Alpha 目标", "timestamp": "2026-05-26T10:00:00"}],
                },
                {
                    "conversation_id": "session-beta",
                    "title": "Beta Agent",
                    "updated_at": "2026-05-26T10:01:00",
                    "messages": [{"role": "user", "content": "Beta 目标", "timestamp": "2026-05-26T10:01:00"}],
                },
            ],
        },
    )


def test_create_chat_session_creates_persistent_agent_and_direct_conversation(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    detail = session_service.create_chat_session(title="配置 Agent")

    assert detail["agentId"]
    assert detail["agentCode"] == "A001"
    agent = agent_directory_service.get_agent(detail["agentId"])
    assert agent["directSessionId"] == detail["id"]
    assert agent["agentCode"] == "A001"
    assert agent["primaryMode"] == "chat"
    assert agent["promptTemplateId"] == "prompt-chat-default"
    assert agent["workspacePath"].startswith("workspace/agents/")
    assert (tmp_path / agent["workspacePath"] / "memory").exists()
    assert agent["memoryPolicy"]["privateMemoryRoot"].endswith("/memory")

    conversations = conversation_service.list_conversations()
    direct = [item for item in conversations if item["type"] == "direct_agent"]
    assert direct[0]["conversationId"] == detail["id"]
    assert direct[0]["title"] == "配置 Agent"
    assert direct[0]["agentId"] == detail["agentId"]
    assert direct[0]["agentCode"] == "A001"
    assert direct[0]["agentDisplayName"] == agent["displayName"]
    assert direct[0]["agentDisplayName"] != direct[0]["title"]
    assert direct[0]["agentPrimaryMode"] == "chat"
    assert direct[0]["agentRoleKey"] == ""
    assert direct[0]["agentPromptTemplateId"] == "prompt-chat-default"


def test_legacy_session_is_repaired_with_agent_id_without_moving_session_workspace(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)

    sessions = session_service.list_sessions()

    alpha = next(item for item in sessions if item["id"] == "session-alpha")
    assert alpha["agentId"]
    assert alpha["workspacePath"] == "workspace/sessions/session-alpha"
    state = load_chat_state(tmp_path)
    raw_alpha = next(item for item in state["conversations"] if item["conversation_id"] == "session-alpha")
    assert raw_alpha["agent_id"] == alpha["agentId"]
    assert raw_alpha["workspace_path"] == "workspace/sessions/session-alpha"


def test_session_list_reuses_agent_lookup_for_existing_bound_sessions(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    session_service.list_sessions()

    def fail_get_agent(agent_id, *args, **kwargs):
        raise AssertionError(f"session list should use the shared Agent lookup: {agent_id}")

    monkeypatch.setattr(session_service, "get_agent", fail_get_agent)

    sessions = session_service.list_sessions()

    assert {item["id"] for item in sessions} == {"session-alpha", "session-beta"}
    assert all(item["agentId"] for item in sessions)


def test_conversation_index_returns_direct_agents_and_group_rooms(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    session_service.list_sessions()
    room = chat_room_service.create_chat_room(title="研究群聊", participant_session_ids=["session-alpha", "session-beta"])
    real_list_sessions = session_service.list_sessions
    list_session_calls = 0

    def counting_list_sessions():
        nonlocal list_session_calls
        list_session_calls += 1
        return real_list_sessions()

    monkeypatch.setattr(session_service, "list_sessions", counting_list_sessions)

    conversations = conversation_service.list_conversations()

    assert {item["type"] for item in conversations} == {"direct_agent", "group_room"}
    group = next(item for item in conversations if item["type"] == "group_room")
    assert group["roomId"] == room["roomId"]
    assert group["participantCount"] == 2
    assert list_session_calls == 1


def test_create_chat_room_from_existing_agent_ids_enters_conversation_index(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")

    room = chat_room_service.create_chat_room(
        title="动态群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
        mode="round_robin",
    )

    assert [participant["agentId"] for participant in room["participants"]] == [alpha["agentId"], beta["agentId"]]
    assert [participant["agentCode"] for participant in room["participants"]] == [alpha["agentCode"], beta["agentCode"]]
    assert [participant["sessionId"] for participant in room["participants"]] == [alpha["id"], beta["id"]]

    conversations = conversation_service.list_conversations()
    group = next(item for item in conversations if item["type"] == "group_room")
    assert group["roomId"] == room["roomId"]
    assert group["participantCount"] == 2
    assert group["mode"] == "round_robin"


def test_chat_room_messages_and_prompts_carry_agent_codes(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    room = chat_room_service.create_chat_room(
        title="代号群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
    )
    prompts = []

    def fake_runner(participant, prompt, context):
        prompts.append(prompt)
        return {
            "status": "completed",
            "raw_output": f"{participant['agentCode']} 发言",
            "summary": "ok",
        }

    detail = chat_room_service.start_chat_room_round(room["roomId"], "确认代号", agent_runner=fake_runner)
    latest_round = detail["rounds"][-1]

    assert [message["speakerCode"] for message in latest_round["messages"]] == [
        alpha["agentCode"],
        beta["agentCode"],
    ]
    assert latest_round["messages"][0]["speakerTitle"].startswith(f"{alpha['agentCode']} · ")
    assert latest_round["messages"][1]["speakerTitle"].startswith(f"{beta['agentCode']} · ")
    assert alpha["agentCode"] in prompts[0]
    assert beta["agentCode"] in prompts[1]


def test_create_chat_room_from_agent_ids_rejects_single_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Solo Agent")

    try:
        chat_room_service.create_chat_room(title="单人群聊", participant_agent_ids=[alpha["agentId"]])
    except chat_room_service.ChatRoomValidationError as exc:
        assert "两个" in str(exc) or "two" in str(exc)
    else:
        raise AssertionError("Expected single-agent group creation to fail")


def test_agent_and_conversation_api_create_direct_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    response = client.post("/api/agents", json={"displayName": "API Agent", "profileId": "primary"})

    assert response.status_code == 201, response.text
    agent = response.json()
    assert agent["displayName"]
    assert agent["displayName"] != "API Agent"
    assert agent["metadata"]["functionalDisplayName"] == "API Agent"
    assert agent["metadata"]["displayNameSource"] == "generated_person_name"
    assert agent["primaryMode"] == "chat"
    assert agent["roleKey"] == ""
    assert agent["promptTemplateId"] == "prompt-chat-default"
    assert agent["directSessionId"]

    conversations_response = client.get("/api/conversations")

    assert conversations_response.status_code == 200
    conversations = conversations_response.json()
    direct = next(item for item in conversations if item["type"] == "direct_agent")
    assert direct["agentId"] == agent["agentId"]
    assert direct["directSessionId"] == agent["directSessionId"]
    assert direct["agentPrimaryMode"] == "chat"
    assert direct["agentRoleKey"] == ""
    assert direct["agentPromptTemplateId"] == "prompt-chat-default"


def test_agent_directory_index_logging_is_deduplicated_per_agent_session(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    recorded_events = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    session = session_service.create_chat_session(title="Index Only Agent")
    agent = agent_directory_service.update_agent_instance(
        session["agentId"],
        primary_mode="research",
        role_key="research_ceo",
        prompt_template_id="prompt-research-ceo",
    )
    state = load_chat_state(tmp_path)
    state["conversations"] = []
    save_chat_state(tmp_path, state)

    first = session_service.list_sessions()
    second = session_service.list_sessions()

    assert any(item["id"] == agent["directSessionId"] for item in first)
    assert any(item["id"] == agent["directSessionId"] for item in second)
    index_events = [
        event for event in recorded_events
        if event[0][2] == "session.agent_directory_index_added"
    ]
    assert len(index_events) == 1
    assert index_events[0][1]["fields"]["sessionId"] == agent["directSessionId"]
    assert index_events[0][1]["fields"]["agentId"] == agent["agentId"]


def test_missing_agent_hidden_index_logging_is_deduplicated_per_session(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    sessions = session_service.list_sessions()
    alpha = next(item for item in sessions if item["id"] == "session-alpha")
    agent_directory_service.archive_agent_instance(alpha["agentId"])
    recorded_events = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    first = session_service.list_sessions()
    second = session_service.list_sessions()

    assert "session-alpha" not in {item["id"] for item in first}
    assert "session-alpha" not in {item["id"] for item in second}
    hidden_events = [
        event for event in recorded_events
        if event[0][2] == "session.agent_missing.hidden_from_index"
    ]
    assert len(hidden_events) == 1
    assert hidden_events[0][1]["fields"]["sessionId"] == "session-alpha"
    assert hidden_events[0][1]["fields"]["agentId"] == alpha["agentId"]
    assert hidden_events[0][1]["fields"]["agentStatusCode"] == "archived_agent"


def test_agent_directory_repairs_legacy_mode_role_and_prompt_fields(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    state = agent_directory_service.default_state()
    state["agents"] = [
        {
            "agentId": "agent-legacy-research",
            "displayName": "旧科研 Agent",
            "kind": "persistent",
            "templateId": "research_broad_explorer",
            "profileId": "research_broad",
            "workspacePath": "workspace/agents/agent-legacy-research",
            "metadata": {"researchAgentKey": "broad"},
            "status": "active",
            "createdAt": "2026-05-27T00:00:00Z",
            "updatedAt": "2026-05-27T00:00:00Z",
        }
    ]
    agent_directory_service.save_state(state)

    repaired = agent_directory_service.get_agent("agent-legacy-research")

    assert repaired["agentCode"] == "A001"
    assert repaired["primaryMode"] == "research"
    assert repaired["roleKey"] == "research_broad"
    assert repaired["promptTemplateId"] == "prompt-research-broad"


def test_conversation_index_exposes_agent_management_role_fields(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    detail = session_service.create_chat_session(title="科研成员")
    agent = agent_directory_service.update_agent_instance(
        detail["agentId"],
        primary_mode="research",
        role_key="research_capability_steward",
        prompt_template_id="prompt-research-capability-steward",
    )

    sessions = session_service.list_sessions()
    session = next(item for item in sessions if item["id"] == detail["id"])
    conversations = conversation_service.list_conversations()
    direct = next(item for item in conversations if item["conversationId"] == detail["id"])

    assert session["agentPrimaryMode"] == "research"
    assert session["agentRoleKey"] == "research_capability_steward"
    assert session["agentPromptTemplateId"] == "prompt-research-capability-steward"
    assert direct["agentId"] == agent["agentId"]
    assert direct["agentPrimaryMode"] == "research"
    assert direct["agentRoleKey"] == "research_capability_steward"
    assert direct["agentPromptTemplateId"] == "prompt-research-capability-steward"


def test_agent_directory_direct_session_appears_in_conversation_index_without_chat_state_entry(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "",
            "conversations": [],
        },
    )
    agent = agent_directory_service.create_agent_instance(
        display_name="能力管家 Agent",
        profile_id="primary",
        primary_mode="research",
        role_key="research_capability_steward",
        prompt_template_id="prompt-research-capability-steward",
        direct_session_id="session-research-steward",
    )

    sessions = session_service.list_sessions()
    indexed = next(item for item in sessions if item["id"] == "session-research-steward")
    conversations = conversation_service.list_conversations()
    direct = next(item for item in conversations if item["conversationId"] == "session-research-steward")
    detail = session_service.get_session_detail("session-research-steward")

    assert indexed["agentId"] == agent["agentId"]
    assert indexed["agentPrimaryMode"] == "research"
    assert indexed["agentRoleKey"] == "research_capability_steward"
    assert direct["agentPrimaryMode"] == "research"
    assert direct["agentRoleKey"] == "research_capability_steward"
    assert direct["agentPromptTemplateId"] == "prompt-research-capability-steward"
    assert detail["id"] == "session-research-steward"
    assert detail["agentId"] == agent["agentId"]
    assert detail["messages"] == []
    state = load_chat_state(tmp_path)
    assert [item["conversation_id"] for item in state["conversations"]] == ["session-research-steward"]


def test_agent_directory_direct_session_can_accept_messages_after_materialization(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "",
            "conversations": [],
        },
    )
    agent = agent_directory_service.create_agent_instance(
        display_name="科研负责人",
        profile_id="primary",
        primary_mode="research",
        role_key="research_ceo",
        prompt_template_id="prompt-research-ceo",
        direct_session_id="session-research-ceo",
    )
    monkeypatch.setattr(session_service, "_submit_scheduled_session_turn", lambda context: None)

    response = client.post(
        "/api/sessions/session-research-ceo/messages",
        json={"content": "你好，先确认你的科研 CEO 身份。"},
    )

    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["id"] == "session-research-ceo"
    assert payload["agentId"] == agent["agentId"]
    assert payload["agentPrimaryMode"] == "research"
    user_messages = [item for item in payload["messages"] if item["role"] == "user"]
    assert user_messages
    assert "科研 CEO" in user_messages[-1]["content"]
    state = load_chat_state(tmp_path)
    assert state["active_conversation_id"] == "session-research-ceo"
    persisted = state["conversations"][0]
    assert persisted["conversation_id"] == "session-research-ceo"
    assert persisted["agent_id"] == agent["agentId"]
    assert persisted["messages"][-1]["role"] == "user"


def test_agent_directory_resolves_workspace_root_without_nested_workspace(tmp_path, monkeypatch):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", workspace_root)
    monkeypatch.setattr(agent_directory_service, "record_runtime_scene_event", lambda *args, **kwargs: None)

    agent = agent_directory_service.create_agent_instance(display_name="路径修复 Agent", profile_id="primary")

    assert agent["workspacePath"].startswith("workspace/agents/")
    assert (tmp_path / agent["workspacePath"] / "memory").exists()
    assert (tmp_path / "workspace" / "agents" / "agents.json").exists()
    assert not (tmp_path / "workspace" / "workspace").exists()


def test_agent_directory_atomic_write_retries_transient_permission_error(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(agent_directory_service, "record_runtime_scene_event", lambda *args, **kwargs: None)
    real_replace = agent_directory_service.os.replace
    attempts: list[str] = []

    def flaky_replace(source, target):
        attempts.append(str(target))
        if len(attempts) == 1:
            raise PermissionError("locked")
        return real_replace(source, target)

    monkeypatch.setattr(agent_directory_service.os, "replace", flaky_replace)

    agent_directory_service.save_state(agent_directory_service.default_state())

    assert len(attempts) == 2
    assert (tmp_path / "workspace" / "agents" / "agents.json").exists()


def test_agents_api_updates_unified_agent_fields(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="可配置 Agent", profile_id="primary")

    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "primaryMode": "research",
            "roleKey": "research_review",
            "promptTemplateId": "prompt-research-review",
            "templateId": "research_evidence_reviewer",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["primaryMode"] == "research"
    assert payload["roleKey"] == "research_review"
    assert payload["promptTemplateId"] == "prompt-research-review"
    assert payload["templateId"] == "research_evidence_reviewer"


def test_agents_api_returns_recent_agent_runs(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="运行记录 Agent",
        profile_id="primary",
        direct_session_id="session-runs-api",
    )
    from core.orchestration import context_engine

    context_engine.record_agent_turn_result(
        agent["agentId"],
        "session-runs-api",
        {
            "status": "completed",
            "summary": "API key: sk-sensitive-token\n已完成",
            "toolCallCount": 3,
            "apiKey": "sk-should-not-leak",
        },
        run_id="session-runs-api-turn-1",
    )

    response = client.get(f"/api/agents/{agent['agentId']}/runs?limit=1")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["agentId"] == agent["agentId"]
    assert payload["limit"] == 1
    assert len(payload["runs"]) == 1
    assert payload["runs"][0]["runKind"] == "agent_run"
    assert payload["runs"][0]["sourceRunId"] == "session-runs-api-turn-1"
    assert "sk-sensitive-token" not in json.dumps(payload, ensure_ascii=False)
    assert "sk-should-not-leak" not in json.dumps(payload, ensure_ascii=False)


def test_agent_configuration_api_exposes_prompt_templates_and_mode_bindings(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")

    templates_response = client.get("/api/prompt-templates")
    assert templates_response.status_code == 200, templates_response.text
    templates_payload = templates_response.json()
    assert "prompt-research-broad" in {item["promptTemplateId"] for item in templates_payload["templates"]}

    update_template_response = client.patch(
        "/api/prompt-templates/prompt-research-broad",
        json={"content": "# API 广搜提示词\n"},
    )
    assert update_template_response.status_code == 200, update_template_response.text
    assert update_template_response.json()["content"] == "# API 广搜提示词\n"

    binding_response = client.get("/api/agent-mode-bindings")
    assert binding_response.status_code == 200, binding_response.text
    assert alpha["agentId"] in binding_response.json()["modes"]["chat"]["availableAgentIds"]

    update_binding_response = client.patch(
        "/api/agent-mode-bindings/chat",
        json={"defaultAgentId": alpha["agentId"], "availableAgentIds": [alpha["agentId"]]},
    )
    assert update_binding_response.status_code == 200, update_binding_response.text
    assert update_binding_response.json()["modes"]["chat"]["defaultAgentId"] == alpha["agentId"]

    slot_agent = agent_directory_service.create_agent_instance(
        display_name="替换执行 Agent",
        profile_id="primary",
        primary_mode="self_evolution",
        role_key="executor",
        prompt_template_id="prompt-self-executor",
    )
    slot_response = client.patch(
        "/api/agent-mode-bindings/self_evolution/slots/executor",
        json={"agentId": slot_agent["agentId"]},
    )
    assert slot_response.status_code == 200, slot_response.text
    assert slot_response.json()["modes"]["self_evolution"]["slots"]["executor"] == slot_agent["agentId"]

    pool_agent = agent_directory_service.create_agent_instance(
        display_name="科研池 Agent",
        profile_id="primary",
        primary_mode="research",
        role_key="research_pool",
        prompt_template_id="prompt-research-broad",
    )
    pool_response = client.patch(
        "/api/agent-mode-bindings/research/pool",
        json={"agentIds": [pool_agent["agentId"]]},
    )
    assert pool_response.status_code == 200, pool_response.text
    assert pool_response.json()["modes"]["research"]["pool"] == [pool_agent["agentId"]]


def test_agent_configuration_api_exposes_self_evolution_role_agents(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    agents_response = client.get("/api/agents")

    assert agents_response.status_code == 200, agents_response.text
    self_agents = [
        item
        for item in agents_response.json()
        if item.get("primaryMode") == "self_evolution"
    ]
    assert {item["roleKey"] for item in self_agents} == {"executor", "reviewer", "summarizer"}
    assert {item["promptTemplateId"] for item in self_agents} == {
        "prompt-self-executor",
        "prompt-self-reviewer",
        "prompt-self-summarizer",
    }

    bindings_response = client.get("/api/agent-mode-bindings")

    assert bindings_response.status_code == 200, bindings_response.text
    slots = bindings_response.json()["modes"]["self_evolution"]["slots"]
    role_to_agent_id = {item["roleKey"]: item["agentId"] for item in self_agents}
    assert slots == {
        "executor": role_to_agent_id["executor"],
        "reviewer": role_to_agent_id["reviewer"],
        "summarizer": role_to_agent_id["summarizer"],
    }


def test_agents_api_skips_config_agent_sync_when_fixed_roles_are_present(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    for role in supervised_agent_service.SUPERVISED_AGENT_ROLES:
        agent_directory_service.create_agent_instance(
            display_name=role.label,
            template_id=role.profile_id,
            profile_id=role.profile_id,
            primary_mode="supervised_evolution",
            role_key=role.role,
            prompt_template_id=f"prompt-supervised-{role.role}",
            metadata={"supervisedRole": role.role, "supervisedRoleLabel": role.label},
        )
    for role in self_evolution_control_service.SELF_EVOLUTION_AGENT_ROLES:
        role_key = role["role"]
        agent_directory_service.create_agent_instance(
            display_name=role["label"],
            template_id=role["profileId"],
            profile_id=role["profileId"],
            primary_mode="self_evolution",
            role_key=role_key,
            prompt_template_id=role["promptTemplateId"],
            metadata={"selfEvolutionRole": role_key, "selfEvolutionRoleLabel": role["label"]},
        )

    def fail_sync(*args, **kwargs):
        raise AssertionError("fixed role sync should be skipped when registry is already complete")

    monkeypatch.setattr(agents_route, "ensure_supervised_agent_instances", fail_sync)
    monkeypatch.setattr(agents_route, "ensure_self_evolution_agent_instances", fail_sync)

    response = client.get("/api/agents")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload) == 8
    assert {
        item["roleKey"]
        for item in payload
        if item["primaryMode"] == "supervised_evolution"
    } == {role.role for role in supervised_agent_service.SUPERVISED_AGENT_ROLES}
    assert {
        item["roleKey"]
        for item in payload
        if item["primaryMode"] == "self_evolution"
    } == {role["role"] for role in self_evolution_control_service.SELF_EVOLUTION_AGENT_ROLES}


def test_chat_room_completion_syncs_group_context_events_to_participant_agents_only(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    sessions = session_service.list_sessions()
    agent_ids = {item["id"]: item["agentId"] for item in sessions}
    outsider = agent_directory_service.create_agent_instance(
        display_name="Outsider",
        profile_id="primary",
        direct_session_id="session-outsider",
    )

    room = chat_room_service.create_chat_room(
        title="同步群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )
    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "同步群聊上下文",
        agent_runner=lambda participant, prompt, context: {
            "status": "completed",
            "raw_output": f"{participant['title']} 完成观点",
            "summary": f"{participant['title']} summary",
        },
    )

    assert all(participant["agentId"] for participant in detail["participants"])
    for session_id, agent_id in agent_ids.items():
        events = agent_directory_service.list_group_context_events_for_agent(agent_id)
        assert len(events) == 1, session_id
        assert events[0]["sourceRoomId"] == room["roomId"]
        assert events[0]["sourceRoundId"] == detail["rounds"][-1]["roundId"]
        assert events[0]["promptEligible"] is True
        context_block = agent_directory_service.build_agent_runtime_context_block(agent_id)
        assert "同步群聊上下文" in context_block
    assert agent_directory_service.list_group_context_events_for_agent(outsider["agentId"]) == []


def test_agent_inbox_message_persists_for_offline_target_and_enters_runtime_context(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")

    message = agent_directory_service.write_agent_inbox_message(
        beta["agentId"],
        source_agent_id=alpha["agentId"],
        content="请审查我刚才的群聊结论，并给出保留意见。",
        summary="请求 Beta 审查 Alpha 的结论",
        created_by="agent",
    )

    assert message["status"] == "pending"
    assert message["sourceAgentCode"] == alpha["agentCode"]
    assert message["targetAgentCode"] == beta["agentCode"]
    assert message["targetSessionId"] == beta["id"]
    inbox_path = tmp_path / "workspace" / "agents" / beta["agentId"] / "events" / "agent_inbox_messages.jsonl"
    assert inbox_path.exists()

    pending = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"])
    assert [item["messageId"] for item in pending] == [message["messageId"]]

    context_block = agent_directory_service.build_agent_runtime_context_block(beta["agentId"])
    assert "AgentInboxMessages:" in context_block
    assert alpha["agentCode"] in context_block
    assert "请审查我刚才的群聊结论" in context_block

    beta_detail = session_service.get_session_detail(beta["id"])
    assert beta_detail["agentInboxMessages"][0]["messageId"] == message["messageId"]


def test_agent_inbox_wake_respects_target_delegation_policy(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    agent_directory_service.update_agent_instance(
        beta["agentId"],
        delegation_policy={
            "allowSubagents": False,
            "maxDepth": 0,
            "maxConcurrent": 0,
            "allowWakeMessages": False,
            "allowedContextModes": ["isolated"],
        },
    )
    started = []
    monkeypatch.setattr(session_service, "submit_session_message", lambda *args, **kwargs: started.append((args, kwargs)) or {"startedTurnId": "turn-policy"})
    message = agent_directory_service.write_agent_inbox_message(
        beta["agentId"],
        source_agent_id=alpha["agentId"],
        content="请在空闲时处理这条消息。",
    )

    delivery = session_service.wake_agent_for_inbox_message(message)

    assert delivery["wakeStatus"] == "skipped_policy_blocked"
    assert delivery["reason"] == "wake_messages_disabled"
    assert started == []
    pending = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="pending")
    assert [item["messageId"] for item in pending] == [message["messageId"]]


def test_agent_inbox_wake_skips_archived_target_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    started = []
    events = []
    monkeypatch.setattr(session_service, "submit_session_message", lambda *args, **kwargs: started.append((args, kwargs)))
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )
    message = agent_directory_service.write_agent_inbox_message(
        beta["agentId"],
        source_agent_id=alpha["agentId"],
        content="这条消息在目标归档后不应唤醒。",
    )
    agent_directory_service.archive_agent_instance(beta["agentId"])

    delivery = session_service.wake_agent_for_inbox_message(message)

    assert delivery["wakeStatus"] == "skipped_archived_agent"
    assert delivery["reason"] == "target_agent_archived"
    assert started == []
    assert any(item[0][2] == "agent_inbox.wake_skipped_archived_agent" for item in events)
    pending = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="pending")
    assert [item["messageId"] for item in pending] == [message["messageId"]]


def test_ensure_agent_for_session_does_not_reactivate_archived_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="旧会话 Agent",
        direct_session_id="session-archived",
    )
    agent_directory_service.archive_agent_instance(agent["agentId"])

    with pytest.raises(agent_directory_service.AgentArchivedError):
        agent_directory_service.ensure_agent_for_session("session-archived", display_name="旧会话 Agent")

    archived = agent_directory_service.get_agent(agent["agentId"], include_archived=True)
    assert archived["status"] == "archived"


def test_agent_inbox_message_can_be_consumed_idempotently(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    message = agent_directory_service.write_agent_inbox_message(
        beta["agentId"],
        source_agent_id=alpha["agentId"],
        content="需要你接一下这个问题。",
    )

    consumed = agent_directory_service.consume_agent_inbox_message(
        beta["agentId"],
        message["messageId"],
        consumed_by_session_id=beta["id"],
        consumed_by_turn_id="turn-1",
    )
    consumed_again = agent_directory_service.consume_agent_inbox_message(beta["agentId"], message["messageId"])

    assert consumed["status"] == "consumed"
    assert consumed["consumedBySessionId"] == beta["id"]
    assert consumed["consumedByTurnId"] == "turn-1"
    assert consumed_again["status"] == "consumed"
    assert agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="pending") == []
    all_messages = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="")
    assert all_messages[0]["status"] == "consumed"


def test_agent_inbox_message_api_round_trip(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")

    response = client.post(
        f"/api/agents/{beta['agentId']}/messages",
        json={
            "sourceAgentId": alpha["agentId"],
            "content": "Beta，请从 UI 风险角度接着看。",
            "wakeTarget": False,
            "metadata": {"priority": "normal"},
        },
    )

    assert response.status_code == 201, response.text
    message = response.json()
    assert message["sourceAgentCode"] == alpha["agentCode"]
    assert message["targetAgentCode"] == beta["agentCode"]

    list_response = client.get(f"/api/agents/{beta['agentId']}/messages")
    assert list_response.status_code == 200
    assert [item["messageId"] for item in list_response.json()] == [message["messageId"]]

    consume_response = client.post(
        f"/api/agents/{beta['agentId']}/messages/{message['messageId']}/consume",
        json={"consumedBySessionId": beta["id"], "consumedByTurnId": "turn-api"},
    )
    assert consume_response.status_code == 200
    assert consume_response.json()["status"] == "consumed"


def test_agent_inbox_message_api_can_wake_target_agent_and_consume_message(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    captured = {}

    class ReplyingAgent:
        def seed_chat_history(self, messages):
            captured["history"] = list(messages)

        def seed_runtime_context(self, context):
            captured["runtimeContext"] = context

        def run_single_turn(self, initial_prompt=None):
            captured["prompt"] = str(initial_prompt or "")
            return {
                "status": "completed",
                "raw_output": "Beta 已收到 Alpha 的私信，并给出回复。",
                "summary": "Beta replied",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: ReplyingAgent())
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )

    response = client.post(
        f"/api/agents/{beta['agentId']}/messages",
        json={
            "sourceAgentId": alpha["agentId"],
            "content": "Beta，请接着审查 Alpha 的方案。",
            "wakeTarget": True,
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["delivery"]["wakeStatus"] == "started"
    assert payload["delivery"]["targetSessionId"] == beta["id"]
    assert payload["delivery"]["turnId"]
    assert "Beta，请接着审查 Alpha 的方案。" in captured["prompt"]
    assert "AgentInboxMessages:" in captured["runtimeContext"]

    detail = session_service.get_session_detail(beta["id"])
    assert detail["messages"][-2]["role"] == "user"
    assert detail["messages"][-2]["metadata"]["kind"] == "agent_inbox_message"
    assert detail["messages"][-2]["metadata"]["messageId"] == payload["messageId"]
    assert detail["messages"][-1]["content"] == "Beta 已收到 Alpha 的私信，并给出回复。"
    assert agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="pending") == []
    consumed = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="consumed")
    assert consumed[0]["messageId"] == payload["messageId"]
    assert consumed[0]["consumedByTurnId"] == payload["delivery"]["turnId"]


def test_agent_inbox_message_wake_skips_busy_target_without_consuming(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    session_service._set_session_running(beta["id"], True, turn_id="turn-busy")
    try:
        response = client.post(
            f"/api/agents/{beta['agentId']}/messages",
            json={
                "sourceAgentId": alpha["agentId"],
                "content": "Beta，忙完后再看这个问题。",
                "wakeTarget": True,
            },
        )
    finally:
        session_service._set_session_running(beta["id"], False, turn_id="turn-busy")

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["delivery"]["wakeStatus"] == "skipped_busy"
    pending = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="pending")
    assert [item["messageId"] for item in pending] == [payload["messageId"]]
    detail = session_service.get_session_detail(beta["id"])
    assert detail["messages"] == []


def test_agent_message_tool_sends_persistent_message_by_agent_code(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")

    with agent_directory_service.active_agent_runtime(alpha["agentId"], session_id=alpha["id"]):
        result, action = ToolExecutor().execute(
            "agent_message_tool",
            {
                "target_agent": beta["agentCode"],
                "content": "Beta，请从架构风险角度审查这轮改造。",
                "summary": "请求架构审查",
                "wake_target": False,
                "metadata_json": "{\"priority\":\"normal\"}",
            },
        )

    payload = json.loads(result)
    assert action is None
    assert payload["ok"] is True
    assert payload["status"] == "sent"
    assert payload["sourceAgentId"] == alpha["agentId"]
    assert payload["sourceSessionId"] == alpha["id"]
    assert payload["targetAgentId"] == beta["agentId"]
    assert payload["targetAgentCode"] == beta["agentCode"]
    assert payload["wakeStatus"] == "not_requested"

    pending = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="pending")
    assert [item["messageId"] for item in pending] == [payload["messageId"]]
    assert pending[0]["sourceAgentId"] == alpha["agentId"]
    assert pending[0]["sourceAgentCode"] == alpha["agentCode"]
    assert pending[0]["content"] == "Beta，请从架构风险角度审查这轮改造。"
    assert pending[0]["metadata"] == {"priority": "normal"}


def test_agent_message_tool_can_wake_target_session_and_consume_inbox(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    captured = {}

    class ReplyingAgent:
        def seed_chat_history(self, messages):
            captured["history"] = list(messages)

        def seed_runtime_context(self, context):
            captured["runtimeContext"] = context

        def run_single_turn(self, initial_prompt=None):
            captured["prompt"] = str(initial_prompt or "")
            return {
                "status": "completed",
                "raw_output": "Beta 已通过 agent_message_tool 接到私信。",
                "summary": "Beta replied",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: ReplyingAgent())
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )

    with agent_directory_service.active_agent_runtime(alpha["agentId"], session_id=alpha["id"]):
        result, action = ToolExecutor().execute(
            "agent_message_tool",
            {
                "target_agent": beta["agentId"],
                "content": "Beta，请接力回答 Alpha 的私信。",
                "wake_target": True,
            },
        )

    payload = json.loads(result)
    assert action is None
    assert payload["ok"] is True
    assert payload["wakeStatus"] == "started"
    assert payload["delivery"]["targetSessionId"] == beta["id"]
    assert payload["delivery"]["turnId"]
    assert "Beta，请接力回答 Alpha 的私信。" in captured["prompt"]
    assert "AgentInboxMessages:" in captured["runtimeContext"]

    detail = session_service.get_session_detail(beta["id"])
    assert detail["messages"][-2]["role"] == "user"
    assert detail["messages"][-2]["metadata"]["kind"] == "agent_inbox_message"
    assert detail["messages"][-2]["metadata"]["messageId"] == payload["messageId"]
    assert detail["messages"][-1]["content"] == "Beta 已通过 agent_message_tool 接到私信。"
    assert agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="pending") == []
    consumed = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="consumed")
    assert consumed[0]["messageId"] == payload["messageId"]
    assert consumed[0]["consumedByTurnId"] == payload["delivery"]["turnId"]


def test_agent_message_tool_routes_research_core_messages_through_org_policy(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_tmp_research_org_workspace(tmp_path, monkeypatch)
    recorded_events = []
    from core.web.services import runtime_scene_service

    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    org = research_organization_service.get_research_organization()
    ceo = next(node for node in org["agents"] if node["role"] == "ceo")
    steward = next(node for node in org["agents"] if node["role"] == "capability_steward")

    with agent_directory_service.active_agent_runtime(ceo["agentId"], session_id=ceo["agent"]["directSessionId"]):
        result, action = ToolExecutor().execute(
            "agent_message_tool",
            {
                "target_agent": steward["agent"]["agentCode"],
                "content": "请审查数据库试水团队的工具权限。",
                "summary": "能力权限审查",
                "wake_target": False,
                "metadata_json": json.dumps(
                    {
                        "researchOrgMessageType": "task",
                        "researchOrgIntent": "tool_policy",
                    },
                    ensure_ascii=False,
                ),
            },
        )

    payload = json.loads(result)
    assert action is None
    assert payload["ok"] is True
    assert payload["status"] == "sent"
    assert payload["route"] == "research_org"
    assert payload["sourceAgentId"] == ceo["agentId"]
    assert payload["targetAgentId"] == steward["agentId"]
    assert payload["researchOrgMessageId"]
    assert payload["delivery"]["edgeId"] == f"edge-{ceo['agentId']}-{steward['agentId']}"
    tool_events = [
        event for event in recorded_events
        if event[0][2] == "agent_inbox.tool_sent"
    ]
    assert tool_events
    tool_fields = tool_events[-1][1]["fields"]
    assert tool_fields["route"] == "research_org"
    assert tool_fields["messageId"] == payload["messageId"]
    assert tool_fields["researchOrgMessageId"] == payload["researchOrgMessageId"]
    assert tool_fields["edgeId"] == f"edge-{ceo['agentId']}-{steward['agentId']}"
    assert tool_fields["messageType"] == "task"
    assert tool_fields["intent"] == "tool_policy"
    assert tool_fields["deliveryMode"] == "private"

    pending = agent_directory_service.list_agent_inbox_messages_for_agent(steward["agentId"], status="pending")
    assert [item["messageId"] for item in pending] == [payload["messageId"]]
    assert pending[0]["kind"] == "research_org_task"
    assert pending[0]["createdBy"] == "research_org"
    assert pending[0]["metadata"]["researchOrgMessageId"] == payload["researchOrgMessageId"]
    assert pending[0]["metadata"]["researchOrgMessageType"] == "task"
    assert pending[0]["metadata"]["researchOrgIntent"] == "tool_policy"


def test_agent_message_tool_blocks_research_core_message_without_intent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_tmp_research_org_workspace(tmp_path, monkeypatch)
    org = research_organization_service.get_research_organization()
    ceo = next(node for node in org["agents"] if node["role"] == "ceo")
    steward = next(node for node in org["agents"] if node["role"] == "capability_steward")

    with agent_directory_service.active_agent_runtime(ceo["agentId"], session_id=ceo["agent"]["directSessionId"]):
        result, action = ToolExecutor().execute(
            "agent_message_tool",
            {
                "target_agent": steward["agent"]["agentCode"],
                "content": "请审查数据库试水团队的工具权限。",
                "summary": "能力权限审查",
                "wake_target": True,
                "metadata_json": json.dumps(
                    {
                        "researchOrgMessageType": "task",
                    },
                    ensure_ascii=False,
                ),
            },
        )

    payload = json.loads(result)
    assert action is None
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["route"] == "research_org"
    assert payload["reason"] == "research_org_intent_required"
    assert payload["wakeStatus"] == "blocked"
    assert "researchOrgIntent" in payload["message"]
    assert agent_directory_service.list_agent_inbox_messages_for_agent(steward["agentId"], status="pending") == []


def test_research_org_report_intent_forces_mailbox_only_even_when_wake_requested(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_tmp_research_org_workspace(tmp_path, monkeypatch)
    org = research_organization_service.get_research_organization()
    steward = next(node for node in org["agents"] if node["role"] == "capability_steward")
    ceo = next(node for node in org["agents"] if node["role"] == "ceo")

    result = research_organization_service.send_research_org_message(
        {
            "sourceType": "agent",
            "sourceAgentId": steward["agentId"],
            "sourceSessionId": steward["agent"]["directSessionId"],
            "targetAgentId": ceo["agentId"],
            "messageType": "report",
            "intent": "status_report",
            "content": "知识库权限审查已完成，暂无需 CEO 立即处理。",
            "summary": "知识库权限审查状态",
            "wakeTarget": True,
            "createdBy": "agent_tool",
        }
    )

    message = result["message"]
    delivery = message["deliveries"][0]
    assert message["intent"] == "status_report"
    assert message["wakeTarget"] is False
    assert delivery["allowed"] is True
    assert delivery["wakeRequested"] is False
    assert delivery["wakeStatus"] == "not_requested"
    pending = agent_directory_service.list_agent_inbox_messages_for_agent(ceo["agentId"], status="pending")
    assert [item["messageId"] for item in pending] == [delivery["inboxMessageId"]]
    assert pending[0]["metadata"]["researchOrgIntent"] == "status_report"


def test_agent_message_tool_blocks_research_core_messages_without_allowed_policy(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_tmp_research_org_workspace(tmp_path, monkeypatch)
    recorded_events = []
    from core.web.services import runtime_scene_service

    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    org = research_organization_service.get_research_organization()
    ceo = next(node for node in org["agents"] if node["role"] == "ceo")
    advisor = next(node for node in org["agents"] if node["role"] == "organization_advisor")

    with agent_directory_service.active_agent_runtime(advisor["agentId"], session_id=advisor["agent"]["directSessionId"]):
        result, action = ToolExecutor().execute(
            "agent_message_tool",
            {
                "target_agent": ceo["agentId"],
                "content": "请 CEO 立刻执行这个组织任务。",
                "wake_target": False,
                "metadata_json": json.dumps(
                    {
                        "researchOrgMessageType": "task",
                        "researchOrgIntent": "organization_design",
                    },
                    ensure_ascii=False,
                ),
            },
        )

    payload = json.loads(result)
    assert action is None
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["route"] == "research_org"
    assert payload["reason"] == "message_type_not_allowed"
    assert payload["wakeStatus"] == "blocked"
    assert payload["delivery"]["inboxMessageId"] == ""
    tool_events = [
        event for event in recorded_events
        if event[0][2] == "agent_inbox.tool_blocked"
    ]
    assert tool_events
    tool_fields = tool_events[-1][1]["fields"]
    assert tool_fields["route"] == "research_org"
    assert tool_fields["researchOrgMessageId"] == payload["researchOrgMessageId"]
    assert tool_fields["edgeId"] == f"edge-{advisor['agentId']}-{ceo['agentId']}"
    assert tool_fields["messageType"] == "task"
    assert tool_fields["intent"] == "organization_design"
    assert tool_fields["deliveryMode"] == "private"
    assert tool_fields["reason"] == "message_type_not_allowed"
    assert agent_directory_service.list_agent_inbox_messages_for_agent(ceo["agentId"], status="pending") == []


def test_agent_message_tool_blocks_outsider_to_research_core_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_tmp_research_org_workspace(tmp_path, monkeypatch)
    org = research_organization_service.get_research_organization()
    steward = next(node for node in org["agents"] if node["role"] == "capability_steward")
    outsider = session_service.create_chat_session(title="外部 Chat Agent")

    with agent_directory_service.active_agent_runtime(outsider["agentId"], session_id=outsider["id"]):
        result, action = ToolExecutor().execute(
            "agent_message_tool",
            {
                "target_agent": steward["agentId"],
                "content": "绕过组织图直接请求工具权限调整。",
                "wake_target": False,
                "metadata_json": json.dumps(
                    {
                        "researchOrgMessageType": "request",
                        "researchOrgIntent": "tool_policy",
                    },
                    ensure_ascii=False,
                ),
            },
        )

    payload = json.loads(result)
    assert action is None
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["route"] == "research_org"
    assert payload["reason"] == "source_not_in_organization"
    assert payload["delivery"]["inboxMessageId"] == ""
    assert agent_directory_service.list_agent_inbox_messages_for_agent(steward["agentId"], status="pending") == []


def test_agent_configuration_indexes_repair_update_and_persist(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")

    template_index = prompt_template_service.list_prompt_templates()
    template_ids = {item["templateId"] for item in template_index["templates"]}
    assert "prompt-chat-default" in template_ids

    updated_template = prompt_template_service.update_prompt_template(
        "prompt-chat-default",
        content="你是默认聊天 Agent。",
        metadata={"editedBy": "test"},
    )
    assert updated_template["content"] == "你是默认聊天 Agent。"
    assert updated_template["metadata"]["editedBy"] == "test"
    assert (tmp_path / "workspace" / "agent_config" / "prompt_templates.json").exists()

    binding_payload = agent_mode_binding_service.update_mode_binding(
        "chat",
        default_agent_id=beta["agentId"],
        available_agent_ids=[alpha["agentId"], beta["agentId"]],
        slots={"assistant": alpha["agentId"]},
    )
    chat_binding = binding_payload["bindings"]["chat"]
    assert chat_binding["defaultAgentId"] == beta["agentId"]
    assert chat_binding["availableAgentIds"] == [alpha["agentId"], beta["agentId"]]
    assert chat_binding["slots"]["assistant"] == alpha["agentId"]
    assert (tmp_path / "workspace" / "agent_config" / "mode_bindings.json").exists()


def test_agent_inbox_message_rejects_unknown_source_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    beta = session_service.create_chat_session(title="Beta Agent")

    response = client.post(
        f"/api/agents/{beta['agentId']}/messages",
        json={
            "sourceAgentId": "missing-agent",
            "content": "这条消息不应被接受。",
        },
    )

    assert response.status_code == 404
    assert agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="") == []


def test_chat_room_completion_appends_visible_group_transcript_to_participant_sessions(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    session_service.list_sessions()

    room = chat_room_service.create_chat_room(
        title="共通群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )
    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "同步到各自会话",
        agent_runner=lambda participant, prompt, context: {
            "status": "completed",
            "raw_output": f"{participant['title']} 观点",
            "summary": "ok",
        },
    )

    state = load_chat_state(tmp_path)
    conversations = {item["conversation_id"]: item for item in state["conversations"]}
    alpha_messages = conversations["session-alpha"]["messages"]
    beta_messages = conversations["session-beta"]["messages"]
    latest_round = detail["rounds"][-1]

    for messages, own_title, peer_title in (
        (alpha_messages, "Alpha Agent", "Beta Agent"),
        (beta_messages, "Beta Agent", "Alpha Agent"),
    ):
        synced = messages[-1]
        assert synced["role"] == "assistant"
        assert synced["metadata"]["kind"] == "group_room_transcript"
        assert synced["metadata"]["sourceRoomId"] == room["roomId"]
        assert synced["metadata"]["sourceRoundId"] == latest_round["roundId"]
        assert "共通群聊" in synced["content"]
        assert "同步到各自会话" in synced["content"]
        assert own_title in synced["content"]
        assert peer_title in synced["content"]

    chat_room_service._sync_group_round_to_participant_sessions(detail, latest_round)
    state_after_resync = load_chat_state(tmp_path)
    conversations_after_resync = {
        item["conversation_id"]: item
        for item in state_after_resync["conversations"]
    }
    assert len(conversations_after_resync["session-alpha"]["messages"]) == len(alpha_messages)
    assert len(conversations_after_resync["session-beta"]["messages"]) == len(beta_messages)


def test_tool_policy_blocks_before_tool_execution_and_returns_correctable_error(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Restricted", profile_id="primary")
    agent_directory_service.update_agent_instance(
        agent["agentId"],
        tool_policy={"blockedTools": ["cli_tool"]},
    )

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id=agent["directSessionId"]):
        result, action = ToolExecutor().execute("cli_tool", {"command": "echo should-not-run"})

    assert action is None
    assert "ToolPolicy" in result or "工具策略" in result
    observation_path = tmp_path / agent["workspacePath"] / "events" / "tool_observations.jsonl"
    assert observation_path.exists()
    assert "policy_blocked" in observation_path.read_text(encoding="utf-8")
