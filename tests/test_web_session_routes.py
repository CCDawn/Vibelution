import json

import pytest
from fastapi.testclient import TestClient

from core.ui.chat_state import save_chat_state
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import (
    agent_directory_service,
    runtime_service,
    self_evolution_control_service,
    self_evolution_service,
    session_service,
    supervised_control_service,
)
from tests.helpers.web_chat_state import _seed_chat_state

pytestmark = pytest.mark.serial


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


@pytest.fixture(autouse=True)
def disable_runtime_manager_live_control(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(supervised_control_service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "_runtime_manager_live_control_enabled", lambda: False)


@pytest.fixture(autouse=True)
def isolate_evolution_live_state():
    self_evolution_service.invalidate_self_evolution_overview_cache()
    with supervised_control_service._RUN_STATE_LOCK:
        supervised_control_service._RUN_STATES.clear()
        supervised_control_service._RUN_CONTROLLERS.clear()
        supervised_control_service._ACTIVE_RUN_ID = None
    with supervised_control_service._RUN_SUBSCRIBERS_LOCK:
        supervised_control_service._RUN_SUBSCRIBERS.clear()
    with self_evolution_control_service._RUN_STATE_LOCK:
        self_evolution_control_service._RUN_STATES.clear()
        self_evolution_control_service._RUN_INTERNALS.clear()
        self_evolution_control_service._ACTIVE_RUN_ID = None
    with self_evolution_control_service._RUN_SUBSCRIBERS_LOCK:
        self_evolution_control_service._RUN_SUBSCRIBERS.clear()
    yield
    self_evolution_service.invalidate_self_evolution_overview_cache()
    with supervised_control_service._RUN_STATE_LOCK:
        supervised_control_service._RUN_STATES.clear()
        supervised_control_service._RUN_CONTROLLERS.clear()
        supervised_control_service._ACTIVE_RUN_ID = None
    with supervised_control_service._RUN_SUBSCRIBERS_LOCK:
        supervised_control_service._RUN_SUBSCRIBERS.clear()
    with self_evolution_control_service._RUN_STATE_LOCK:
        self_evolution_control_service._RUN_STATES.clear()
        self_evolution_control_service._RUN_INTERNALS.clear()
        self_evolution_control_service._ACTIVE_RUN_ID = None
    with self_evolution_control_service._RUN_SUBSCRIBERS_LOCK:
        self_evolution_control_service._RUN_SUBSCRIBERS.clear()


def test_session_detail_exists(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    sessions_response = client.get("/api/sessions")
    assert sessions_response.status_code == 200
    sessions = sessions_response.json()
    assert sessions
    assert sessions[0]["id"] == "session-live"

    response = client.get("/api/sessions/session-live")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "session-live"
    assert payload["messages"]
    assert payload["messages"][1]["content"] == "已经接到真实状态了。"
    assert payload["messages"][1]["thought"] == "internal"
    assert payload["messages"][1]["toolCalls"] == [
        {"name": "read_file_tool", "status": "done"},
        {"name": "search_code_tool", "status": "done"},
    ]
    assert payload["lastTurnError"] is None
    assert payload["taskSummary"] == "已经接到真实状态了。"
    assert payload["previewTabs"] == []
    assert payload["currentPhase"] == "ready"
    assert payload["contextUsage"]["source"] == "session_messages"
    assert payload["contextUsage"]["messageCount"] == 2
    assert payload["contextUsage"]["userMessageCount"] == 1
    assert payload["contextUsage"]["assistantMessageCount"] == 1
    assert payload["contextUsage"]["toolCallCount"] == 2
    assert payload["contextUsage"]["used"] > 0
    assert payload["contextUsage"]["limit"] > 0
def test_session_query_paginates_searches_and_filters(tmp_path, monkeypatch):
    conversations = [
        {
            "conversation_id": "session-alpha",
            "title": "Alpha planning",
            "agent_id": "agent-a",
            "agentId": "agent-a",
            "session_kind": "main",
            "updated_at": "2026-05-18T12:00:00",
            "messages": [{"role": "assistant", "content": "Alpha summary", "timestamp": "2026-05-18T12:00:00"}],
        },
        {
            "conversation_id": "session-beta",
            "title": "Beta research",
            "agent_id": "agent-b",
            "agentId": "agent-b",
            "session_kind": "child",
            "parent_session_id": "session-alpha",
            "root_session_id": "session-alpha",
            "updated_at": "2026-05-18T13:00:00",
            "messages": [{"role": "assistant", "content": "Beta summary", "timestamp": "2026-05-18T13:00:00"}],
        },
        {
            "conversation_id": "session-gamma",
            "title": "Gamma coding",
            "agent_id": "agent-a",
            "agentId": "agent-a",
            "session_kind": "main",
            "updated_at": "2026-05-18T14:00:00",
            "messages": [{"role": "assistant", "content": "Gamma summary", "timestamp": "2026-05-18T14:00:00"}],
        },
    ]
    _seed_chat_state(tmp_path, conversations=conversations)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent_directory_service.save_state(
        {
            "agents": [
                {"agentId": "agent-a", "displayName": "Agent Alpha", "status": "active", "directSessionId": "session-alpha"},
                {"agentId": "agent-b", "displayName": "Agent Beta", "status": "active", "directSessionId": "session-beta"},
            ]
        }
    )

    first_page = client.get("/api/sessions/query?limit=2")
    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert [item["id"] for item in first_payload["items"]] == ["session-gamma", "session-beta"]
    assert first_payload["nextCursor"] == "2"
    assert first_payload["totalEstimate"] == 3

    second_page = client.get(f"/api/sessions/query?limit=2&cursor={first_payload['nextCursor']}")
    assert second_page.status_code == 200
    assert [item["id"] for item in second_page.json()["items"]] == ["session-alpha"]
    assert second_page.json()["nextCursor"] == ""

    search_response = client.get("/api/sessions/query?q=beta")
    assert search_response.status_code == 200
    assert [item["id"] for item in search_response.json()["items"]] == ["session-beta"]

    filtered_response = client.get("/api/sessions/query?agentId=agent-a&sessionKind=main&sort=title_asc")
    assert filtered_response.status_code == 200
    assert {item["id"] for item in filtered_response.json()["items"]} == {"session-alpha", "session-gamma"}
def test_session_query_default_page_skips_per_item_filtering(tmp_path, monkeypatch):
    conversations = [
        {
            "conversation_id": "session-alpha",
            "title": "Alpha",
            "agent_id": "agent-a",
            "updated_at": "2026-05-18T12:00:00",
            "messages": [{"role": "user", "content": "alpha", "timestamp": "2026-05-18T12:00:00"}],
        },
        {
            "conversation_id": "session-beta",
            "title": "Beta",
            "agent_id": "agent-b",
            "updated_at": "2026-05-18T11:00:00",
            "messages": [{"role": "user", "content": "beta", "timestamp": "2026-05-18T11:00:00"}],
        },
    ]
    _seed_chat_state(tmp_path, conversations=conversations)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent_directory_service.save_state(
        {
            "agents": [
                {"agentId": "agent-a", "displayName": "Agent Alpha", "status": "active", "directSessionId": "session-alpha"},
                {"agentId": "agent-b", "displayName": "Agent Beta", "status": "active", "directSessionId": "session-beta"},
            ]
        }
    )

    def fail_match(*args, **kwargs):
        raise AssertionError("default session query should slice the existing sorted index")

    monkeypatch.setattr(session_service, "_session_query_matches", fail_match)

    response = client.get("/api/sessions/query?limit=1")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == ["session-alpha"]
    assert payload["nextCursor"] == "1"
    assert payload["totalEstimate"] == 2
def test_supervised_agent_session_is_hidden_and_preserves_prompt_with_mental_override(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, conversations=[])
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    cfg = runtime_service.get_config().model_copy(deep=True)
    primary_profile = cfg.llm.get_profile(role="primary")
    cfg.llm.model_library["model-a"] = {
        "provider_id": primary_profile.provider_id,
        "model": "model-a",
        "label": "Supervised test model",
    }
    monkeypatch.setattr(session_service, "get_config", lambda: cfg)
    agent_directory_service.save_state(
        {
            "agents": [
                {
                    "agentId": "agent-supervised",
                    "displayName": "Supervised Agent",
                    "status": "active",
                    "directSessionId": "",
                    "llmBindings": {"dialogue": {"modelId": "model-a"}},
                }
            ]
        }
    )
    scheduled_contexts: list[dict] = []

    class DummyAgent:
        def __init__(self):
            self.override = None
            self.seeded_history = []

        def set_mental_model_enabled_override(self, enabled):
            self.override = enabled

        def seed_chat_history(self, messages):
            self.seeded_history = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": f"seen: {initial_prompt}",
                "raw_output": f"seen: {initial_prompt}",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", DummyAgent)
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: scheduled_contexts.append(dict(context)) or session_service._run_session_turn(context),
    )

    created = session_service.create_supervised_agent_session(
        agent_id="agent-supervised",
        title="hidden supervised case",
        metadata={"role": "baseline"},
    )
    session_id = created["id"]
    assert created["sessionKind"] == "supervised"
    assert created["hiddenFromIndex"] is True
    assert session_id not in {item["id"] for item in session_service.list_sessions()}
    assert (agent_directory_service.get_agent("agent-supervised") or {}).get("directSessionId") != session_id

    prompt = "\n".join(
        [
            "Run this Terminal-Bench-style local smoke case.",
            "- Case: tb2_fix_code_vulnerability",
            "- Docker image: alexgshaw/fix-code-vulnerability:20251031",
            "This is a Vibelution custom-harness run; preserve the prompt as the case input.",
        ]
    )
    assert session_service._has_recent_image_attachment_reference(prompt) is True
    response = session_service.submit_session_message(
        session_id,
        prompt,
        mental_model_enabled=False,
        message_source="supervised_evolution",
    )

    assert response["messages"][-1]["content"] == f"seen: {prompt}"
    assert scheduled_contexts[-1]["user_message"] == prompt
    assert scheduled_contexts[-1]["user_message_source"] == "supervised_evolution"
    assert scheduled_contexts[-1]["mental_model_enabled"] is False
    assert scheduled_contexts[-1]["leases"] == ["readonly_chat"]
    latest_user = [item for item in response["messages"] if item["role"] == "user"][-1]
    assert latest_user["content"] == prompt
    assert "resolvedRecentImageReference" not in (latest_user.get("metadata") or {})
    assert session_id not in {item["id"] for item in session_service.list_sessions()}
    assert (agent_directory_service.get_agent("agent-supervised") or {}).get("directSessionId") != session_id
def test_session_query_keeps_active_session_on_default_first_page(tmp_path, monkeypatch):
    conversations = []
    for index in range(60):
        session_id = f"session-{index:02d}"
        conversations.append(
            {
                "conversation_id": session_id,
                "title": f"Session {index:02d}",
                "updated_at": f"2026-05-18T14:{index:02d}:00",
                "messages": [{"role": "assistant", "content": f"Summary {index:02d}", "timestamp": "2026-05-18T14:00:00"}],
            }
        )
    conversations.append(
        {
            "conversation_id": "session-active",
            "title": "Active old session",
            "updated_at": "2026-05-18T09:00:00",
            "messages": [{"role": "assistant", "content": "Active summary", "timestamp": "2026-05-18T09:00:00"}],
        }
    )
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-active",
            "updated_at": "2026-05-18T15:00:00",
            "conversations": conversations,
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/query?limit=10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["id"] == "session-active"
    assert payload["nextCursor"] == "10"
def test_session_summary_exposes_dialogue_model_id(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        conversations=[
            {
                "conversation_id": "session-live",
                "title": "真实会话",
                "agent_id": "agent-live",
                "agentId": "agent-live",
                "updated_at": "2026-05-18T12:00:00",
                "messages": [{"role": "user", "content": "继续前端开发", "timestamp": "2026-05-18T11:55:00"}],
            }
        ],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    fake_agent = {
        "agentId": "agent-live",
        "agentCode": "A001",
        "displayName": "程听澜",
        "directSessionId": "session-live",
        "primaryMode": "chat",
        "roleKey": "chat-default",
        "promptTemplateId": "prompt-chat-default",
        "workspacePath": "workspace/agents/agent-live",
        "status": "active",
        "llmBindings": {"dialogue": {"modelId": "houmo_qwen3_30b_agent"}},
    }
    agent_directory_service.save_state({"agents": [fake_agent]})
    monkeypatch.setattr(session_service, "get_agent", lambda agent_id, **_kwargs: fake_agent if agent_id == "agent-live" else None)

    sessions_response = client.get("/api/sessions")
    detail_response = client.get("/api/sessions/session-live")

    assert sessions_response.status_code == 200
    assert detail_response.status_code == 200
    assert sessions_response.json()[0]["dialogueModelId"] == "houmo_qwen3_30b_agent"
    assert detail_response.json()["dialogueModelId"] == "houmo_qwen3_30b_agent"
def test_session_detail_marks_agent_direct_session_mismatch(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        conversations=[
            {
                "conversation_id": "session-legacy",
                "title": "旧直连会话",
                "agent_id": "agent-live",
                "agentId": "agent-live",
                "updated_at": "2026-05-18T12:00:00",
                "active_task": {
                    "task_id": "old-task",
                    "kind": "coding",
                    "status": "blocked",
                    "title": "旧任务",
                    "latest_summary": "旧会话残留任务",
                },
                "messages": [{"role": "user", "content": "旧消息", "timestamp": "2026-05-18T11:55:00"}],
            },
            {
                "conversation_id": "session-current",
                "title": "当前直连会话",
                "agent_id": "agent-live",
                "agentId": "agent-live",
                "updated_at": "2026-05-18T12:05:00",
                "messages": [{"role": "user", "content": "当前消息", "timestamp": "2026-05-18T12:05:00"}],
            },
        ],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    fake_agent = {
        "agentId": "agent-live",
        "agentCode": "A001",
        "displayName": "程听澜",
        "directSessionId": "session-current",
        "primaryMode": "chat",
        "workspacePath": "workspace/agents/agent-live",
        "status": "active",
        "llmBindings": {"dialogue": {"modelId": "houmo_qwen3_30b_agent"}},
    }
    agent_directory_service.save_state({"agents": [fake_agent]})
    monkeypatch.setattr(session_service, "get_agent", lambda agent_id, **_kwargs: fake_agent if agent_id == "agent-live" else None)

    response = client.get("/api/sessions/session-legacy")

    assert response.status_code == 200
    payload = response.json()
    assert payload["agentDirectSessionMismatch"] is True
    assert payload["agentPrimaryDirectSessionId"] == "session-current"
    assert payload["activeTask"] is None
    assert agent_directory_service.get_agent("agent-live")["directSessionId"] == "session-current"
def test_session_detail_uses_targeted_conversation_read(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        conversations=[
            {
                "conversation_id": "session-older",
                "title": "旧会话",
                "updated_at": "2026-05-18T10:00:00",
                "messages": [{"role": "user", "content": "旧消息", "timestamp": "2026-05-18T10:00:00"}],
            },
            {
                "conversation_id": "session-live",
                "title": "真实会话",
                "updated_at": "2026-05-18T12:00:00",
                "messages": [{"role": "user", "content": "目标消息", "timestamp": "2026-05-18T12:00:00"}],
            },
        ],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    def fail_append_agent_directory_conversations(*args, **kwargs):
        raise AssertionError("session detail should not append every Agent Directory conversation")

    monkeypatch.setattr(
        session_service,
        "_append_agent_directory_conversations",
        fail_append_agent_directory_conversations,
    )

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "session-live"
    assert payload["messages"][0]["content"] == "目标消息"
def test_session_detail_does_not_scan_full_conversation_list_for_known_id(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        conversations=[
            {
                "conversation_id": "session-older",
                "title": "旧会话",
                "updated_at": "2026-05-18T10:00:00",
                "messages": [{"role": "user", "content": "旧消息", "timestamp": "2026-05-18T10:00:00"}],
            },
            {
                "conversation_id": "session-live",
                "title": "真实会话",
                "updated_at": "2026-05-18T12:00:00",
                "messages": [{"role": "user", "content": "目标消息", "timestamp": "2026-05-18T12:00:00"}],
            },
        ],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    def fail_list_conversations(*args, **kwargs):
        raise AssertionError("session detail should not load full conversations list")

    monkeypatch.setattr(session_service, "_load_conversations", fail_list_conversations)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "session-live"
    assert payload["messages"][0]["content"] == "目标消息"
def test_create_child_session_api_persists_root_child_relationship(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.ensure_agent_for_session("session-live", display_name="真实会话")

    response = client.post(
        "/api/sessions/session-live/child-sessions",
        json={
            "userRequest": "单独修复子对话展示",
            "taskTitle": "子对话展示修复",
            "splitReason": "这是独立 UI 工作",
            "inheritedFacts": ["主会话已确认只做一层子对话"],
            "relevantFiles": ["web/src/routes/ChatCodingRoute.tsx"],
            "constraints": ["不要复制完整历史"],
            "autoStart": False,
            "switchToChild": False,
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    child = payload["childSession"]
    parent = payload["parentSession"]
    child_id = payload["childSessionId"]
    assert payload["parentSessionId"] == "session-live"
    assert payload["autoStarted"] is False
    assert payload["switched"] is False
    assert child["id"] == child_id
    assert child["agentId"] == agent["agentId"]
    assert child["sessionKind"] == "child"
    assert child["parentSessionId"] == "session-live"
    assert child["rootSessionId"] == "session-live"
    assert child["taskTitle"] == "子对话展示修复"
    assert child["handoffContext"]["parentSessionId"] == "session-live"
    assert child["handoffContext"]["sourceSessionId"] == "session-live"
    assert child["handoffContext"]["inheritedFacts"] == ["主会话已确认只做一层子对话"]
    assert child["handoffContext"]["relevantFiles"] == ["web/src/routes/ChatCodingRoute.tsx"]
    assert parent["childSessionIds"] == [child_id]
    assert parent["activeChildSessionId"] == child_id
    assert parent["messages"][-1]["metadata"]["kind"] == "child_session_card"
    assert parent["messages"][-1]["metadata"]["childSessionId"] == child_id

    list_response = client.get("/api/sessions/session-live/child-sessions")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [child_id]
def test_create_child_session_from_child_attaches_sibling_to_root(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent_directory_service.ensure_agent_for_session("session-live", display_name="真实会话")

    first = client.post(
        "/api/sessions/session-live/child-sessions",
        json={
            "userRequest": "第一件事",
            "taskTitle": "第一件事",
            "autoStart": False,
            "switchToChild": False,
        },
    ).json()
    first_child_id = first["childSessionId"]

    second_response = client.post(
        f"/api/sessions/{first_child_id}/child-sessions",
        json={
            "userRequest": "第二件事",
            "taskTitle": "第二件事",
            "autoStart": False,
            "switchToChild": False,
        },
    )

    assert second_response.status_code == 201, second_response.text
    second = second_response.json()
    second_child_id = second["childSessionId"]
    root_detail = client.get("/api/sessions/session-live").json()
    first_child_detail = client.get(f"/api/sessions/{first_child_id}").json()
    second_child_detail = client.get(f"/api/sessions/{second_child_id}").json()

    assert second["parentSessionId"] == "session-live"
    assert root_detail["childSessionIds"] == [first_child_id, second_child_id]
    assert root_detail["activeChildSessionId"] == second_child_id
    assert first_child_detail["childSessionIds"] == []
    assert second_child_detail["parentSessionId"] == "session-live"
    assert second_child_detail["handoffContext"]["sourceSessionId"] == first_child_id
def test_child_session_tool_uses_current_agent_runtime_session(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.ensure_agent_for_session("session-live", display_name="真实会话")
    from tools import session_child_tools

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-live"):
        raw = session_child_tools.create_child_session_tool(
            user_request="拆出去处理缓存命中问题",
            task_title="缓存命中分析",
            split_reason="新事项与当前 UI 实现不同",
            auto_start=False,
            switch_to_child=False,
        )

    payload = json.loads(raw)
    child_id = payload["childSessionId"]
    assert payload["status"] == "created"
    assert payload["parentSessionId"] == "session-live"
    assert payload["childSession"]["id"] == child_id
    assert payload["childSession"]["agentId"] == agent["agentId"]

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-live"):
        listed = json.loads(session_child_tools.list_child_sessions_tool())

    assert listed["status"] == "ok"
    assert listed["count"] == 1
    assert listed["childSessions"][0]["id"] == child_id
