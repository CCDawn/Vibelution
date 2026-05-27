from fastapi.testclient import TestClient

from core.infrastructure.tool_executor import ToolExecutor
from core.ui.chat_state import load_chat_state, save_chat_state
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service, chat_room_service, conversation_service, session_service


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)


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
    assert agent["workspacePath"].startswith("workspace/agents/")
    assert (tmp_path / agent["workspacePath"] / "memory").exists()
    assert agent["memoryPolicy"]["privateMemoryRoot"].endswith("/memory")

    conversations = conversation_service.list_conversations()
    direct = [item for item in conversations if item["type"] == "direct_agent"]
    assert direct[0]["conversationId"] == detail["id"]
    assert direct[0]["agentId"] == detail["agentId"]
    assert direct[0]["agentCode"] == "A001"


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


def test_conversation_index_returns_direct_agents_and_group_rooms(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    session_service.list_sessions()
    room = chat_room_service.create_chat_room(title="研究群聊", participant_session_ids=["session-alpha", "session-beta"])

    conversations = conversation_service.list_conversations()

    assert {item["type"] for item in conversations} == {"direct_agent", "group_room"}
    group = next(item for item in conversations if item["type"] == "group_room")
    assert group["roomId"] == room["roomId"]
    assert group["participantCount"] == 2


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
    assert agent["displayName"] == "API Agent"
    assert agent["directSessionId"]

    conversations_response = client.get("/api/conversations")

    assert conversations_response.status_code == 200
    conversations = conversations_response.json()
    direct = next(item for item in conversations if item["type"] == "direct_agent")
    assert direct["agentId"] == agent["agentId"]
    assert direct["directSessionId"] == agent["directSessionId"]


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
