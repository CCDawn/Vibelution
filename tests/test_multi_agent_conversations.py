import json
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.agent_kernel import service as agent_kernel_service
from core.chat.conversation_ledger import EVENT_ASSISTANT_MESSAGE, EVENT_USER_MESSAGE, append_conversation_event
from core.chat.turn_journal import EVENT_ASSISTANT_ITEM_COMMITTED
from core.infrastructure import developer_sandbox
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
    team_service,
    self_evolution_control_service,
    session_service,
    supervised_agent_service,
)
from tools.session_reference_tools import session_reference_context
from tests.helpers.tool_authorization import execute_authorized_agent_tool

pytestmark = pytest.mark.serial


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _assistant_turn_items(message: dict, item_type: str = "") -> list[dict]:
    items = list(message.get("turnItems") or [])
    if not item_type:
        return items
    return [item for item in items if str(item.get("type") or "") == item_type]


def _assistant_visible_text(message: dict) -> str:
    return "\n".join(
        str(item.get("text") or "").strip()
        for item in _assistant_turn_items(message)
        if str(item.get("type") or "") in {"agent_message", "error"}
        if str(item.get("text") or "").strip()
    )


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_kernel_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(self_evolution_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        self_evolution_control_service,
        "ROLLBACK_ROOT",
        tmp_path / "workspace" / "web_self_evolution",
    )
    monkeypatch.setattr(supervised_agent_service, "PROJECT_ROOT", tmp_path)


def _allow_agent_message_tool(agent_id: str) -> None:
    agent = agent_directory_service.get_agent(agent_id, include_archived=True) or {}
    policy = dict(agent.get("toolPolicy") or {})
    allowed = list(policy.get("allowedTools") or [])
    if "agent_message_tool" not in allowed:
        allowed.append("agent_message_tool")
    policy["allowedTools"] = allowed
    agent_directory_service.update_agent_instance(agent_id, tool_policy=policy)


def _create_secondary_session_for_agent(source_session: dict, *, title: str) -> dict:
    return session_service.create_chat_session(title=title, agent_id=str(source_session["agentId"] or ""))


def _wait_for_chat_state_settle(project_root, *, timeout: float = 3.0) -> None:
    path = developer_sandbox.sandboxed_workspace_path(project_root, "chat", "chat_state.json")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            state = None
        conversations = (state or {}).get("conversations") or []
        if any(
            isinstance(item, dict) and item.get("agentPromptSnapshot")
            for item in conversations
        ):
            return
        time.sleep(0.02)


def _bind_seed_session_agents(root) -> None:
    state = load_chat_state(root)
    for conversation in state.get("conversations") or []:
        if not isinstance(conversation, dict):
            continue
        session_id = str(conversation.get("conversation_id") or "").strip()
        if not session_id:
            continue
        agent = agent_directory_service.ensure_agent_for_session(
            session_id,
            display_name=str(conversation.get("title") or "Seed Agent"),
        )
        conversation["agent_id"] = agent["agentId"]
        conversation["agentId"] = agent["agentId"]
    save_chat_state(root, state)


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


def _seed_ledger_messages(root, session_id: str, messages: list[dict[str, str]]) -> None:
    for index, message in enumerate(messages, start=1):
        role = str(message.get("role") or "").strip().lower()
        if role == "assistant":
            append_conversation_event(
                root,
                session_id,
                f"{session_id}-seed-{index}",
                EVENT_ASSISTANT_ITEM_COMMITTED,
                status="completed",
                payload={
                    "kind": "assistant_message",
                    "channel": "answer",
                    "phase": "final_answer",
                    "text": str(message.get("content") or ""),
                    "invocationId": f"{session_id}-seed-{index}-inv",
                },
                timestamp=str(message.get("timestamp") or ""),
                source="test_seed",
            )
            continue
        append_conversation_event(
            root,
            session_id,
            f"{session_id}-seed-{index}",
            EVENT_USER_MESSAGE,
            status="recorded",
            payload={"content": str(message.get("content") or "")},
            timestamp=str(message.get("timestamp") or ""),
            source="test_seed",
        )


def test_create_chat_session_creates_persistent_agent_and_direct_conversation(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    detail = session_service.create_chat_session(title="配置 Agent")

    assert detail["agentId"]
    agent = agent_directory_service.get_agent(detail["agentId"])
    assert detail["agentCode"] == agent["agentCode"]
    assert agent["agentCode"]
    assert agent["directSessionId"] == detail["id"]
    assert agent["primaryMode"] == "chat"
    assert agent["promptTemplateId"] == "prompt-chat-default"
    assert agent["workspacePath"].startswith("workspace/agents/")
    assert (tmp_path / agent["workspacePath"] / "memory").exists()
    assert agent["memoryPolicy"]["privateMemoryRoot"].endswith("/memory")
    assert detail["title"] == agent["displayName"]
    assert detail["taskTitle"] == "配置 Agent"
    assert agent["metadata"]["functionalDisplayName"] == "配置 Agent"
    assert agent["metadata"]["displayNameSource"] == "responsibility"
    assert detail["hiddenFromIndex"] is False
    assert detail["conversationIndexKind"] == agent_directory_service.CONVERSATION_INDEX_KIND_USER_CHAT
    assert detail["conversationIndexVisibility"] == (
        agent_directory_service.CONVERSATION_INDEX_VISIBILITY_USER_VISIBLE
    )

    listed = {item["id"]: item for item in session_service.list_sessions()}
    assert listed[detail["id"]]["conversationIndexKind"] == (
        agent_directory_service.CONVERSATION_INDEX_KIND_USER_CHAT
    )
    assert listed[detail["id"]]["conversationIndexVisibility"] == (
        agent_directory_service.CONVERSATION_INDEX_VISIBILITY_USER_VISIBLE
    )

    conversations = conversation_service.list_conversations()
    direct = [item for item in conversations if item["type"] == "direct_agent"]
    created_direct = next(item for item in direct if item["conversationId"] == detail["id"])
    assert created_direct["title"] == agent["displayName"]
    assert created_direct["agentId"] == detail["agentId"]
    assert created_direct["agentCode"] == agent["agentCode"]
    assert created_direct["agentDisplayName"] == agent["displayName"]
    assert created_direct["agentPrimaryMode"] == "chat"
    assert created_direct["agentRoleKey"] == ""
    assert created_direct["agentPromptTemplateId"] == "prompt-chat-default"
    assert created_direct["conversationIndexKind"] == agent_directory_service.CONVERSATION_INDEX_KIND_USER_CHAT
    assert created_direct["conversationIndexVisibility"] == (
        agent_directory_service.CONVERSATION_INDEX_VISIBILITY_USER_VISIBLE
    )




def test_create_chat_session_lightweight_skips_full_detail_projection(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    def boom_detail(*_args, **_kwargs):
        raise AssertionError("lightweight create must not call get_session_detail")

    monkeypatch.setattr(session_service, "get_session_detail", boom_detail)
    detail = session_service.create_chat_session(title="轻量会话", lightweight=True)

    assert detail["id"]
    assert detail.get("createdLightweight") is True
    assert isinstance(detail.get("messages"), list)
    listed_ids = {item["id"] for item in session_service.list_sessions()}
    assert detail["id"] in listed_ids


def test_select_chat_session_lightweight_skips_full_detail_projection(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    created = session_service.create_chat_session(title="选中轻量")

    def boom_detail(*_args, **_kwargs):
        raise AssertionError("lightweight select must not call get_session_detail")

    monkeypatch.setattr(session_service, "get_session_detail", boom_detail)
    detail = session_service.select_chat_session(created["id"], lightweight=True)
    assert detail["id"] == created["id"]
    assert detail.get("selectedLightweight") is True
    assert isinstance(detail.get("messages"), list)


def test_legacy_session_list_is_read_only_until_detail_repairs_agent_binding(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    # Seed summary rows without legacy message blobs: any "messages" payload is
    # materialized into the conversation ledger at save time, which creates the
    # session workspace as a durable side effect before list/detail ever runs.
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-alpha",
            "conversations": [
                {
                    "conversation_id": "session-alpha",
                    "title": "Alpha Agent",
                    "updated_at": "2026-05-26T10:00:00",
                },
                {
                    "conversation_id": "session-beta",
                    "title": "Beta Agent",
                    "updated_at": "2026-05-26T10:01:00",
                },
            ],
        },
    )

    sessions = session_service.list_sessions()

    alpha = next(item for item in sessions if item["id"] == "session-alpha")
    assert alpha["agentId"] == ""
    assert alpha["workspacePath"] == "workspace/sessions/session-alpha"
    state = load_chat_state(tmp_path)
    raw_alpha = next(item for item in state["conversations"] if item["conversation_id"] == "session-alpha")
    assert "agent_id" not in raw_alpha
    assert "workspace_path" not in raw_alpha
    assert not (tmp_path / "workspace" / "sessions" / "session-alpha").exists()

    detail = session_service.get_session_detail("session-alpha")

    assert detail is not None
    assert detail["agentId"]
    repaired_state = load_chat_state(tmp_path)
    repaired_alpha = next(item for item in repaired_state["conversations"] if item["conversation_id"] == "session-alpha")
    assert repaired_alpha["agent_id"] == detail["agentId"]
    assert repaired_alpha["workspace_path"] == "workspace/sessions/session-alpha"
    assert (tmp_path / "workspace" / "sessions" / "session-alpha").exists()


def test_detail_repair_does_not_rebind_agent_owned_by_another_direct_session(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    direct = session_service.create_chat_session(title="Direct Agent")
    direct_agent_id = direct["agentId"]
    state = load_chat_state(tmp_path)
    state["conversations"].append(
        {
            "conversation_id": "session-legacy",
            "title": "Legacy view",
            "updated_at": "2026-05-26T10:02:00",
            "agent_id": direct_agent_id,
            "agentId": direct_agent_id,
            "messages": [{"role": "user", "content": "历史任务", "timestamp": "2026-05-26T10:02:00"}],
        }
    )
    save_chat_state(tmp_path, state)

    detail = session_service.get_session_detail("session-legacy")

    assert detail is not None
    assert detail["agentId"] == direct_agent_id
    rebound_agent = agent_directory_service.get_agent(direct_agent_id)
    assert rebound_agent is not None
    assert rebound_agent["directSessionId"] == direct["id"]


def test_session_list_reuses_agent_lookup_for_existing_bound_sessions(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    session_service.get_session_detail("session-alpha")
    session_service.get_session_detail("session-beta")

    def fail_get_agent(agent_id, *args, **kwargs):
        raise AssertionError(f"session list should use the shared Agent lookup: {agent_id}")

    monkeypatch.setattr(session_service, "get_agent", fail_get_agent)

    sessions = session_service.list_sessions()
    seeded_sessions = [item for item in sessions if item["id"] in {"session-alpha", "session-beta"}]

    assert {item["id"] for item in seeded_sessions} == {"session-alpha", "session-beta"}
    assert all(item["agentId"] for item in seeded_sessions)


def test_session_list_uses_lightweight_message_preview(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-long",
            "conversations": [
                {
                    "conversation_id": "session-long",
                    "title": "Long Session",
                    "updated_at": "2026-05-26T10:00:00",
                    "messages": [
                        {"role": "user", "content": f"历史消息 {index}", "timestamp": f"2026-05-26T10:00:{index % 60:02d}"}
                        for index in range(250)
                    ],
                }
            ],
        },
    )
    for index in range(250):
        append_conversation_event(
            tmp_path,
            "session-long",
            f"session-long-seed-{index:03d}",
            EVENT_USER_MESSAGE,
            status="recorded",
            payload={"content": f"历史消息 {index}"},
            timestamp=f"2026-05-26T10:00:{index % 60:02d}",
        )
    normalized_count = 0
    real_sanitize_message_content = session_service._sanitize_message_content

    def counting_sanitize_message_content(role, content):
        nonlocal normalized_count
        normalized_count += 1
        return real_sanitize_message_content(role, content)

    monkeypatch.setattr(session_service, "_sanitize_message_content", counting_sanitize_message_content)

    sessions = session_service.list_sessions()

    assert sessions[0]["id"] == "session-long"
    assert sessions[0]["taskSummary"] == "历史消息 249"
    assert normalized_count <= 12


def test_session_list_hides_bound_session_when_agent_is_missing_without_hydration(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    session_service.get_session_detail("session-alpha")
    state = load_chat_state(tmp_path)
    alpha = next(item for item in state["conversations"] if item["conversation_id"] == "session-alpha")
    missing_agent_id = alpha["agent_id"]
    agent_state = agent_directory_service.load_state()
    agent_state["agents"] = [
        item for item in agent_state["agents"]
        if item.get("agentId") != missing_agent_id
    ]
    agent_directory_service.save_state(agent_state)
    recorded_events = []

    def fail_get_agent(agent_id, *args, **kwargs):
        raise AssertionError(f"session list should not hydrate Agent records: {agent_id}")

    monkeypatch.setattr(session_service, "get_agent", fail_get_agent)
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    sessions = session_service.list_sessions()

    assert "session-alpha" not in {item["id"] for item in sessions}
    hidden_events = [
        event for event in recorded_events
        if event[0][2] == "session.agent_missing.hidden_from_index.batch"
    ]
    assert hidden_events
    assert hidden_events[-1][1]["fields"]["hiddenCount"] == 1
    assert hidden_events[-1][1]["fields"]["sampleSessions"][0]["sessionId"] == "session-alpha"
    assert hidden_events[-1][1]["fields"]["sampleSessions"][0]["agentId"] == missing_agent_id
    assert hidden_events[-1][1]["fields"]["sampleSessions"][0]["agentStatusCode"] == "missing_agent"


def test_session_list_uses_short_snapshot_cache_and_invalidates_on_update(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    created = session_service.create_chat_session(title="Cached Agent")
    _wait_for_chat_state_settle(tmp_path)
    session_service._invalidate_session_list_cache()
    tick = {"value": 10.0}

    def next_tick():
        value = tick["value"]
        tick["value"] += 0.05
        return value

    monkeypatch.setattr(session_service, "_perf_counter", next_tick)
    lookup_calls = 0
    load_calls = 0
    real_lookup = session_service._agent_lookup_for_conversations
    real_load = session_service._load_conversations
    events = []

    def counting_lookup():
        nonlocal lookup_calls
        lookup_calls += 1
        return real_lookup()

    def counting_load(*args, **kwargs):
        nonlocal load_calls
        load_calls += 1
        return real_load(*args, **kwargs)

    monkeypatch.setattr(session_service, "_agent_lookup_for_conversations", counting_lookup)
    monkeypatch.setattr(session_service, "_load_conversations", counting_load)
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )

    first = session_service.list_sessions()
    second = session_service.list_sessions()

    assert [item["id"] for item in first] == [item["id"] for item in second]
    assert lookup_calls == 1
    assert load_calls == 1
    loaded_events = [item for item in events if item[0][2] == "session.list.loaded"]
    assert loaded_events[0][1]["fields"]["cacheHit"] is False
    assert loaded_events[0][1]["fields"]["ledgerTailMs"] > 0
    assert loaded_events[0][1]["fields"]["agentInboxMs"] > 0
    assert loaded_events[0][1]["fields"]["agentDirectoryMs"] > 0
    assert loaded_events[1][1]["fields"]["cacheHit"] is True
    assert loaded_events[1][1]["fields"]["cacheAgeMs"] > 0

    session_service.update_chat_session(created["id"], title="Renamed Cached Agent")
    lookup_calls = 0
    load_calls = 0
    updated = session_service.list_sessions()
    updated_session = next(item for item in updated if item["id"] == created["id"])

    assert lookup_calls == 1
    assert load_calls == 1
    assert updated_session["title"] == "Renamed Cached Agent"
    assert updated_session["taskTitle"] == "Renamed Cached Agent"
    assert [item for item in events if item[0][2] == "session.list.loaded"][-1][1]["fields"]["cacheHit"] is False


def test_session_agent_lookup_reuses_avatar_url_for_shared_paths(monkeypatch):
    shared_avatar_path = "workspace/avatars/05-broad-explorer.png"
    monkeypatch.setattr(
        agent_directory_service,
        "load_state",
        lambda: {
            "agents": [
                {
                    "agentId": "agent-alpha",
                    "displayName": "Alpha",
                    "metadata": {"avatarImagePath": shared_avatar_path},
                },
                {
                    "agentId": "agent-beta",
                    "displayName": "Beta",
                    "metadata": {"avatarImagePath": shared_avatar_path},
                },
            ]
        },
    )
    avatar_url_calls = []
    monkeypatch.setattr(
        agent_directory_service,
        "agent_avatar_image_url",
        lambda avatar_path: avatar_url_calls.append(avatar_path) or "/api/agents/avatar-image/shared.png?v=1",
    )

    agents = session_service._agent_lookup_for_conversations()

    assert avatar_url_calls == [shared_avatar_path]
    assert agents["agent-alpha"]["avatarImageUrl"] == agents["agent-beta"]["avatarImageUrl"]


def test_session_list_reuses_agent_inbox_count_for_shared_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    parent = session_service.create_chat_session(title="Shared Agent")
    child_session_id = "session-shared-agent-child"
    state = load_chat_state(tmp_path)
    parent_conversation = next(
        item for item in state["conversations"]
        if item["conversation_id"] == parent["id"]
    )
    parent_conversation["child_session_ids"] = [child_session_id]
    state["conversations"].append(
        {
            "conversation_id": child_session_id,
            "title": "Shared Agent Child",
            "task_title": "Shared Agent Child",
            "updated_at": "2026-07-30T08:00:00",
            "agent_id": parent["agentId"],
            "session_kind": "child",
            "parent_session_id": parent["id"],
            "root_session_id": parent["id"],
            "messages": [
                {
                    "role": "user",
                    "content": "Child task",
                    "timestamp": "2026-07-30T08:00:00",
                }
            ],
        }
    )
    save_chat_state(tmp_path, state)
    session_service._invalidate_session_list_cache()
    inbox_count_calls = []

    def counting_agent_inbox_pending_count(agent):
        inbox_count_calls.append(str((agent or {}).get("agentId") or ""))
        return 3

    monkeypatch.setattr(
        session_service,
        "_agent_inbox_pending_count_for_summary",
        counting_agent_inbox_pending_count,
    )

    sessions = session_service.list_sessions(repair_collisions=False)
    shared_agent_sessions = [
        item for item in sessions
        if item["agentId"] == parent["agentId"]
    ]

    assert {item["id"] for item in shared_agent_sessions} == {
        parent["id"],
        child_session_id,
    }
    assert all(item["agentInboxPendingCount"] == 3 for item in shared_agent_sessions)
    assert inbox_count_calls.count(parent["agentId"]) == 1


def test_session_list_cache_returns_isolated_summary_snapshots(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    created = session_service.create_chat_session(title="Cached Parent")
    state = load_chat_state(tmp_path)
    conversation = next(item for item in state["conversations"] if item["conversation_id"] == created["id"])
    conversation["child_session_ids"] = ["session-child-a"]
    conversation["result_card"] = {
        "status": "completed",
        "title": "Child result",
        "summary": "Result summary",
        "changedFiles": ["core/a.py"],
        "validations": ["pytest ok"],
        "updatedAt": "2026-05-18T12:00:00",
    }
    save_chat_state(tmp_path, state)
    session_service._invalidate_session_list_cache()

    first = session_service.list_sessions()
    first_item = next(item for item in first if item["id"] == created["id"])
    first_item["childSessionIds"].append("polluted-child")
    first_item["resultCard"]["changedFiles"].append("polluted-file.py")
    first_item["resultCard"]["validations"].append("polluted validation")

    second = session_service.list_sessions()
    second_item = next(item for item in second if item["id"] == created["id"])
    second_item["childSessionIds"].append("second-pollution")
    second_item["resultCard"]["changedFiles"].append("second-pollution.py")

    third = session_service.list_sessions()
    third_item = next(item for item in third if item["id"] == created["id"])

    assert third_item["childSessionIds"] == ["session-child-a"]
    assert third_item["resultCard"]["changedFiles"] == ["core/a.py"]
    assert third_item["resultCard"]["validations"] == ["pytest ok"]


def test_session_list_reuses_lightweight_message_preview_without_full_normalization(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    _seed_ledger_messages(
        tmp_path,
        "session-alpha",
        [{"role": "user", "content": "Alpha 目标", "timestamp": "2026-05-26T10:00:00"}],
    )
    _seed_ledger_messages(
        tmp_path,
        "session-beta",
        [{"role": "user", "content": "Beta 目标", "timestamp": "2026-05-26T10:01:00"}],
    )
    session_service._invalidate_session_list_cache()
    session_service._invalidate_session_conversation_events_cache()
    real_normalize_messages = session_service._normalize_messages
    normalized_nonempty_inputs: list[str] = []

    def track_full_message_normalization(conversation_id, items, *args, **kwargs):
        if list(items or []):
            normalized_nonempty_inputs.append(str(conversation_id))
        return real_normalize_messages(conversation_id, items, *args, **kwargs)

    monkeypatch.setattr(session_service, "_normalize_messages", track_full_message_normalization)

    sessions = {item["id"]: item for item in session_service.list_sessions()}

    assert sessions["session-alpha"]["taskSummary"] == "Alpha 目标"
    assert sessions["session-beta"]["taskSummary"] == "Beta 目标"
    assert normalized_nonempty_inputs == []


def test_session_list_resolves_ledger_workspace_root_once_for_preview_projection(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    _seed_ledger_messages(
        tmp_path,
        "session-alpha",
        [{"role": "assistant", "content": "Alpha preview", "timestamp": "2026-05-26T10:00:00"}],
    )
    _seed_ledger_messages(
        tmp_path,
        "session-beta",
        [{"role": "assistant", "content": "Beta preview", "timestamp": "2026-05-26T10:01:00"}],
    )
    session_service._invalidate_session_list_cache()
    ledger_workspace_root_calls = []

    def counting_ledger_workspace_root(project_root):
        ledger_workspace_root_calls.append(project_root)
        return developer_sandbox.sandboxed_workspace_path(project_root, "sessions")

    monkeypatch.setattr(
        session_service,
        "conversation_ledger_workspace_root",
        counting_ledger_workspace_root,
    )

    sessions = {item["id"]: item for item in session_service.list_sessions()}

    assert sessions["session-alpha"]["taskSummary"] == "Alpha preview"
    assert sessions["session-beta"]["taskSummary"] == "Beta preview"
    assert ledger_workspace_root_calls == [tmp_path]


def test_session_list_skips_ledger_previews_for_sessions_hidden_before_message_projection(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-visible",
            "conversations": [
                {
                    "conversation_id": "session-visible",
                    "title": "Visible Session",
                    "conversation_index_kind": "user_chat",
                    "updated_at": "2026-05-26T10:00:00",
                    "messages": [],
                },
                {
                    "conversation_id": "session-hidden",
                    "title": "Hidden Session",
                    "conversation_index_kind": "hidden",
                    "hidden_from_index": True,
                    "updated_at": "2026-05-26T10:01:00",
                    "messages": [],
                },
            ],
        },
    )
    _seed_ledger_messages(
        tmp_path,
        "session-visible",
        [{"role": "assistant", "content": "Visible preview", "timestamp": "2026-05-26T10:00:00"}],
    )
    _seed_ledger_messages(
        tmp_path,
        "session-hidden",
        [{"role": "assistant", "content": "Hidden preview", "timestamp": "2026-05-26T10:01:00"}],
    )
    session_service._invalidate_session_list_cache()
    preview_calls: list[str] = []
    real_preview_loader = session_service.load_conversation_preview_slice

    def track_preview_loader(project_root, session_id, **kwargs):
        preview_calls.append(str(session_id))
        return real_preview_loader(project_root, session_id, **kwargs)

    monkeypatch.setattr(
        session_service,
        "load_conversation_preview_slice",
        track_preview_loader,
    )

    sessions = session_service.list_sessions()

    assert [item["id"] for item in sessions] == ["session-visible"]
    assert sessions[0]["taskSummary"] == "Visible preview"
    assert preview_calls == ["session-visible"]

    preview_calls.clear()
    hidden_sessions = session_service.list_sessions(include_hidden_internal=True)

    assert {item["id"] for item in hidden_sessions} == {
        "session-visible",
        "session-hidden",
    }
    assert next(item for item in hidden_sessions if item["id"] == "session-hidden")["taskSummary"] == "Hidden preview"
    assert set(preview_calls) == {"session-visible", "session-hidden"}


def test_session_list_loads_hidden_team_membership_once_per_projection(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    _bind_seed_session_agents(tmp_path)
    session_service._invalidate_session_list_cache()
    team_list_calls = 0

    def list_empty_teams(*args, **kwargs):
        nonlocal team_list_calls
        team_list_calls += 1
        return {"teams": []}

    monkeypatch.setattr(team_service, "list_teams_compact", list_empty_teams)

    sessions = session_service.list_sessions()

    assert {"session-alpha", "session-beta"} <= {item["id"] for item in sessions}
    assert team_list_calls == 1


def test_session_list_preview_projection_avoids_unbounded_ledger_replay(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-preview",
            "conversations": [
                {
                    "conversation_id": "session-preview",
                    "title": "Preview Agent",
                    "updated_at": "2026-05-26T10:00:00",
                    "messages": [],
                }
            ],
        },
    )
    _seed_ledger_messages(
        tmp_path,
        "session-preview",
        [{"role": "assistant", "content": "Ledger preview", "timestamp": "2026-05-26T10:00:00"}],
    )
    session_service._invalidate_session_list_cache()
    session_service._invalidate_session_conversation_events_cache()
    def fail_unbounded_ledger_replay(*args, **kwargs):
        raise AssertionError("session preview must use the bounded ledger tail")

    monkeypatch.setattr(
        session_service,
        "_ledger_visible_messages_for_session",
        fail_unbounded_ledger_replay,
    )

    sessions = {item["id"]: item for item in session_service.list_sessions()}

    assert sessions["session-preview"]["taskSummary"] == "Ledger preview"
    assert sessions["session-preview"]["status"] == "ready"


def test_session_list_empty_preview_avoids_unbounded_ledger_replay(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-empty-preview",
            "conversations": [
                {
                    "conversation_id": "session-empty-preview",
                    "title": "Empty Preview Agent",
                    "updated_at": "2026-05-26T10:00:00",
                    "messages": [],
                }
            ],
        },
    )
    session_service._invalidate_session_list_cache()
    session_service._invalidate_session_conversation_events_cache()
    def fail_unbounded_ledger_replay(*args, **kwargs):
        raise AssertionError("empty preview must remain complete without full replay")

    monkeypatch.setattr(
        session_service,
        "_ledger_visible_messages_for_session",
        fail_unbounded_ledger_replay,
    )

    sessions = {
        item["id"]: item
        for item in session_service.list_sessions(repair_collisions=False)
    }

    assert sessions["session-empty-preview"]["taskSummary"] == ""


def test_session_list_does_not_reread_empty_ledger_for_summary(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-empty-preview",
            "conversations": [
                {
                    "conversation_id": "session-empty-preview",
                    "title": "Empty Preview Agent",
                    "updated_at": "2026-05-26T10:00:00",
                    "messages": [],
                }
            ],
        },
    )
    _bind_seed_session_agents(tmp_path)
    session_service._invalidate_session_list_cache()
    session_service._invalidate_session_conversation_events_cache()
    real_ledger_visible_messages = session_service._ledger_visible_messages_for_session
    calls: list[str] = []

    def counting_ledger_visible_messages(session_id):
        calls.append(str(session_id))
        return real_ledger_visible_messages(session_id)

    monkeypatch.setattr(
        session_service,
        "_ledger_visible_messages_for_session",
        counting_ledger_visible_messages,
    )

    sessions = {
        item["id"]: item
        for item in session_service.list_sessions(repair_collisions=False)
    }

    assert sessions["session-empty-preview"]["taskSummary"] == ""
    assert calls.count("session-empty-preview") == 0


def test_session_title_update_uses_lightweight_path(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    created = session_service.create_chat_session(title="Before Rename")

    def fail_agent_metadata(*args, **kwargs):
        raise AssertionError("title-only rename should not repair agent metadata")

    monkeypatch.setattr(session_service, "_ensure_conversation_agent_metadata", fail_agent_metadata)
    detail = session_service.update_chat_session_title(created["id"], "After Rename")

    assert detail["id"] == created["id"]
    assert detail["title"] == "After Rename"
    sessions = session_service.list_sessions()
    assert next(item for item in sessions if item["id"] == created["id"])["title"] == "After Rename"


@pytest.mark.slow
def test_session_list_shares_concurrent_index_build(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    created = session_service.create_chat_session(title="Concurrent Cached Agent")
    _wait_for_chat_state_settle(tmp_path)
    session_service._invalidate_session_list_cache()
    real_load = session_service._load_conversations
    build_started = threading.Event()
    release_build = threading.Event()
    load_calls = 0
    events = []

    def slow_load(*args, **kwargs):
        nonlocal load_calls
        load_calls += 1
        build_started.set()
        assert release_build.wait(timeout=3)
        return real_load(*args, **kwargs)

    monkeypatch.setattr(session_service, "_load_conversations", slow_load)
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )

    results: list[list[dict]] = []
    errors: list[BaseException] = []

    def worker():
        try:
            results.append(session_service.list_sessions())
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=worker)
    second = threading.Thread(target=worker)
    first.start()
    assert build_started.wait(timeout=3)
    second.start()
    time.sleep(0.05)
    release_build.set()
    first.join(timeout=3)
    second.join(timeout=3)

    assert not first.is_alive()
    assert not second.is_alive()
    assert not errors
    assert len(results) == 2
    assert load_calls == 1
    assert all(any(item["id"] == created["id"] for item in result) for result in results)
    loaded_events = [item for item in events if item[0][2] == "session.list.loaded"]
    assert len(loaded_events) == 2
    assert sorted(event[1]["fields"]["cacheHit"] for event in loaded_events) == [False, True]
    assert any(event[1]["fields"]["waitedForInflight"] for event in loaded_events)


def test_update_chat_session_skips_noop_agent_binding_write(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    session = session_service.create_chat_session(
        title="Stable Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
    )
    before = load_chat_state(tmp_path)

    detail = session_service.update_chat_session(
        session["id"],
        title=session["title"],
        agent_id=session["agentId"],
    )

    assert detail["id"] == session["id"]
    after = load_chat_state(tmp_path)
    assert after["conversations"][0]["agentId"] == before["conversations"][0]["agentId"]
    assert "agentProfileId" not in after["conversations"][0]
    assert "agentTemplateId" not in after["conversations"][0]


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
    assert group["sourceRef"]["owner"] == "ChatRoomService"
    assert group["sourceRef"]["canonicalEditRoute"] == f"/chat?room={room['roomId']}"
    assert group["projectionEdit"]["canWrite"] is False
    assert group["projectionEdit"]["mode"] == "deep_link_to_source"
    assert list_session_calls == 1


def test_conversation_index_filters_archived_team_linked_rooms(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    room_keep = chat_room_service.create_chat_room(
        title="保留群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )
    room_drop = chat_room_service.create_chat_room(
        title="归档群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )

    monkeypatch.setattr(
        team_service,
        "list_archived_team_linked_chat_room_ids",
        lambda: {room_drop["roomId"]},
    )

    conversations = conversation_service.list_conversations()
    group_rooms = [item for item in conversations if item["type"] == "group_room"]
    room_ids = {item["roomId"] for item in group_rooms}

    assert room_keep["roomId"] in room_ids
    assert room_drop["roomId"] not in room_ids


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
    assert latest_round["messages"][0]["speakerTitle"] == alpha["agentCode"]
    assert latest_round["messages"][1]["speakerTitle"] == beta["agentCode"]
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

    response = client.post(
        "/api/agents",
        json={
            "displayName": "API Agent",
            "llmBindings": {"dialogue": {"modelId": "model-primary"}},
            "primaryMode": "chat",
            "promptTemplateId": "prompt-chat-default",
            "toolPolicy": {"allowedTools": ["agent_message_tool"]},
        },
    )

    assert response.status_code == 201, response.text
    agent = response.json()
    assert agent["displayName"] == "API Agent"
    assert agent["metadata"]["functionalDisplayName"] == "API Agent"
    assert agent["metadata"]["displayNameSource"] == "responsibility"
    assert agent["primaryMode"] == "chat"
    assert agent["roleKey"] == ""
    assert agent["promptTemplateId"] == "prompt-chat-default"
    assert agent["directSessionId"]

    conversations_response = client.get("/api/conversations")

    assert conversations_response.status_code == 200
    conversations = conversations_response.json()
    direct = next(
        item
        for item in conversations
        if item["type"] == "direct_agent"
        and item["agentId"] == agent["agentId"]
        and item["directSessionId"] == agent["directSessionId"]
    )
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
        and event[1]["fields"]["agentId"] == agent["agentId"]
    ]
    assert len(index_events) == 1
    assert index_events[0][1]["fields"]["sessionId"] == agent["directSessionId"]
    assert index_events[0][1]["fields"]["agentId"] == agent["agentId"]


def test_missing_agent_hidden_index_logging_is_deduplicated_per_session(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    alpha = session_service.get_session_detail("session-alpha")
    assert alpha is not None
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
        if event[0][2] == "session.agent_missing.hidden_from_index.batch"
    ]
    assert len(hidden_events) == 1
    assert hidden_events[0][1]["fields"]["hiddenCount"] == 1
    sample = hidden_events[0][1]["fields"]["sampleSessions"][0]
    assert sample["sessionId"] == "session-alpha"
    assert sample["agentId"] == alpha["agentId"]
    assert sample["agentStatusCode"] == "archived_agent"


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

    assert repaired["agentCode"] == "A002"
    assert repaired["primaryMode"] == "research"
    assert repaired["roleKey"] == "research_broad"
    assert repaired["promptTemplateId"] == "prompt-research-broad"


def test_conversation_index_exposes_agent_management_role_fields(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    avatar_dir = tmp_path / "workspace" / "avatars"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    (avatar_dir / "01-session-agent.png").write_bytes(b"\x89PNG\r\n\x1a\navatar")
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
    assert direct["agentAvatarImagePath"] == session["agentAvatarImagePath"]
    assert direct["agentAvatarImageUrl"] == session["agentAvatarImageUrl"]
    assert direct["agentAvatarImageUrl"].startswith("/api/agents/avatar-image/")
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
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
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
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
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
    assert "messages" not in persisted
    detail = session_service.get_session_detail("session-research-ceo")
    user_messages = [item for item in detail["messages"] if item["role"] == "user"]
    assert user_messages
    assert "科研 CEO" in user_messages[-1]["content"]


def test_agent_directory_resolves_workspace_root_without_nested_workspace(tmp_path, monkeypatch):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", workspace_root)
    monkeypatch.setattr(agent_directory_service, "record_runtime_scene_event", lambda *args, **kwargs: None)

    agent = agent_directory_service.create_agent_instance(
        display_name="路径修复 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
    )

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
    agent = agent_directory_service.create_agent_instance(
        display_name="可配置 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
    )

    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "displayName": "研究复核",
            "primaryMode": "research",
            "roleKey": "research_review",
            "promptTemplateId": "prompt-research-review",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["displayName"] == "研究复核"
    assert payload["metadata"]["functionalDisplayName"] == "研究复核"
    assert payload["metadata"]["displayNameSource"] == "user"
    assert payload["primaryMode"] == "research"
    assert payload["roleKey"] == "research_review"
    assert payload["promptTemplateId"] == "prompt-research-review"
    assert "templateId" not in payload


def test_agents_api_returns_recent_agent_runs(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="运行记录 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
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
    monkeypatch.setattr(agents_route, "_ensure_config_agent_instances", lambda: None)
    agents_route.invalidate_agent_config_workspace_cache()
    alpha = session_service.create_chat_session(title="Alpha Agent")

    templates_response = client.get("/api/prompt-templates")
    assert templates_response.status_code == 200, templates_response.text
    templates_payload = templates_response.json()
    broad_summary = next(
        item for item in templates_payload["templates"]
        if item["promptTemplateId"] == "prompt-research-broad"
    )
    assert broad_summary["sourceType"] == "workspace_file"
    assert broad_summary["sourceAuthority"] == "record_content"
    assert broad_summary["hasDefault"] is True
    assert broad_summary["defaultContent"] == ""
    assert "广撒网探索 agent" in broad_summary["defaultContentPreview"]

    update_template_response = client.patch(
        "/api/prompt-templates/prompt-research-broad",
        json={"content": "# API 广搜提示词\n"},
    )
    assert update_template_response.status_code == 200, update_template_response.text
    assert update_template_response.json()["content"] == "# API 广搜提示词\n"
    assert update_template_response.json()["sourceAuthority"] == "record_content"

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
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
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
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
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


def test_prompt_template_routes_include_inactive_and_invalidate_agent_workspace_cache(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(agents_route, "_ensure_config_agent_instances", lambda: None)
    agents_route.invalidate_agent_config_workspace_cache()

    first_workspace_response = client.get("/api/agents/config-workspace?includeRuntime=false")
    assert first_workspace_response.status_code == 200, first_workspace_response.text
    assert first_workspace_response.json()["diagnostics"]["cache"]["hit"] is False

    inactive_response = client.patch(
        "/api/prompt-templates/prompt-research-broad",
        json={"status": "inactive"},
    )
    assert inactive_response.status_code == 200, inactive_response.text

    default_list = client.get("/api/prompt-templates")
    assert default_list.status_code == 200, default_list.text
    assert "prompt-research-broad" not in {item["promptTemplateId"] for item in default_list.json()["templates"]}

    inactive_list = client.get("/api/prompt-templates?includeInactive=true")
    assert inactive_list.status_code == 200, inactive_list.text
    inactive_template = next(
        item for item in inactive_list.json()["templates"]
        if item["promptTemplateId"] == "prompt-research-broad"
    )
    assert inactive_template["status"] == "inactive"
    assert inactive_template["hasDefault"] is True

    update_response = client.patch(
        "/api/prompt-templates/prompt-research-broad",
        json={"content": "# 缓存刷新提示词\n", "status": "active"},
    )
    assert update_response.status_code == 200, update_response.text

    second_workspace_response = client.get("/api/agents/config-workspace?includeRuntime=false")
    assert second_workspace_response.status_code == 200, second_workspace_response.text
    second_workspace = second_workspace_response.json()
    assert second_workspace["diagnostics"]["cache"]["hit"] is False
    refreshed_template = next(
        item for item in second_workspace["promptTemplates"]
        if item["promptTemplateId"] == "prompt-research-broad"
    )
    assert "# 缓存刷新提示词" in refreshed_template["contentPreview"]


def test_prompt_template_reset_route_restores_default_chat_role_prompt(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(agents_route, "_ensure_config_agent_instances", lambda: None)
    agents_route.invalidate_agent_config_workspace_cache()
    dynamic_path = tmp_path / "workspace" / "prompts" / "DYNAMIC.md"
    dynamic_path.parent.mkdir(parents=True, exist_ok=True)
    dynamic_path.write_text("KEEP_DYNAMIC_PROMPT", encoding="utf-8")

    response = client.post("/api/prompt-templates/prompt-chat-default/reset")

    assert response.status_code == 200, response.text
    assert response.json()["content"] == prompt_template_service.DEFAULT_CHAT_ROLE_PROMPT
    assert dynamic_path.read_text(encoding="utf-8") == prompt_template_service.DEFAULT_CHAT_ROLE_PROMPT


def test_prompt_template_route_rejects_deactivating_template_used_by_active_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(agents_route, "_ensure_config_agent_instances", lambda: None)
    agent_directory_service.create_agent_instance(
        display_name="广搜 Agent",
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
    )

    response = client.patch(
        "/api/prompt-templates/prompt-research-broad",
        json={"status": "inactive"},
    )

    assert response.status_code == 422, response.text
    assert "active Agent" in response.json()["detail"]


def test_agent_configuration_api_exposes_self_evolution_role_agents(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    agents_response = client.get("/api/agents")

    assert agents_response.status_code == 200, agents_response.text
    self_agents = [
        item
        for item in agents_response.json()
        if item.get("primaryMode") == "self_evolution"
    ]
    assert {item["roleKey"] for item in self_agents} == {"executor", "reviewer", "observer"}
    by_role = {item["roleKey"]: item for item in self_agents}
    assert by_role["executor"]["promptTemplateId"] == "prompt-self-executor"
    assert by_role["reviewer"]["promptTemplateId"] == "prompt-self-reviewer"
    assert by_role["observer"]["promptTemplateId"] == ""

    monkeypatch.setattr(agents_route, "_ensure_config_agent_instances", lambda: None)
    bindings_response = client.get("/api/agent-mode-bindings")

    assert bindings_response.status_code == 200, bindings_response.text
    slots = bindings_response.json()["modes"]["self_evolution"]["slots"]
    role_to_agent_id = {item["roleKey"]: item["agentId"] for item in self_agents}
    assert slots == {
        "executor": role_to_agent_id["executor"],
        "reviewer": role_to_agent_id["reviewer"],
        "observer": role_to_agent_id["observer"],
    }


def test_agents_api_skips_config_agent_sync_when_fixed_roles_are_present(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    for role in supervised_agent_service.SUPERVISED_AGENT_ROLES:
        agent_directory_service.create_agent_instance(
            display_name=role.label,
            llm_bindings={"dialogue": {"modelId": f"model-{role.role.replace('_', '-')}"}},
            primary_mode="supervised_evolution",
            role_key=role.role,
            prompt_template_id=f"prompt-supervised-{role.role}",
            metadata={"supervisedRole": role.role, "supervisedRoleLabel": role.label},
        )
    for role in self_evolution_control_service.SELF_EVOLUTION_AGENT_ROLES:
        role_key = role["role"]
        agent_directory_service.create_agent_instance(
            display_name=role["label"],
            llm_bindings={"dialogue": {"modelId": f"model-{role_key.replace('_', '-')}"}},
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
    assert len(payload) == 9
    assert any(item["agentId"] == "agent-knowledge-steward" for item in payload)
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
    alpha = session_service.get_session_detail("session-alpha")
    beta = session_service.get_session_detail("session-beta")
    assert alpha is not None
    assert beta is not None
    agent_ids = {item["id"]: item["agentId"] for item in [alpha, beta]}
    outsider = agent_directory_service.create_agent_instance(
        display_name="Outsider",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
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


def test_agent_inbox_message_preserves_full_content(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    full_report = "\n".join(f"第 {index:02d} 行：人才缺口分析细节" for index in range(1, 31))

    message = agent_directory_service.write_agent_inbox_message(
        beta["agentId"],
        source_agent_id=alpha["agentId"],
        content=full_report,
        summary="完整人才缺口报告",
        created_by="agent",
    )

    assert message["content"] == full_report
    pending = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"])
    assert pending[0]["content"] == full_report
    prompt = session_service._format_agent_inbox_wake_prompt(message)
    assert "第 01 行：人才缺口分析细节" in prompt
    assert "第 30 行：人才缺口分析细节" in prompt


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


def test_session_submit_kernel_bridge_records_trace_without_agent_inbox_delivery(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    recorded_events = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    captured_contexts = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: captured_contexts.append(dict(context)))
    detail = session_service.create_chat_session(title="Kernel Bridge Agent")

    accepted = session_service.submit_session_message(
        detail["id"],
        "请把这个 direct session turn 接入 Kernel。",
        include_started_turn_id=True,
    )

    # Kernel audit is deferred off the accept path; wait for the async bridge.
    kernel_trace = session_service._await_last_submit_kernel_trace(timeout=5.0) or {}
    assert accepted["startedTurnId"]
    assert kernel_trace.get("status") == "recorded"
    assert kernel_trace.get("sourceSurface") == "session_submit"
    assert kernel_trace.get("traceOnly") is True
    kernel_task_id = str(kernel_trace.get("taskId") or "").strip()
    assert kernel_task_id

    timeline = agent_kernel_service.get_kernel_task_timeline(kernel_task_id)
    assert timeline["event"]["deliveryPolicy"]["traceOnly"] is True
    assert timeline["event"]["deliveryPolicy"]["wakeTarget"] is False
    assert timeline["task"]["assignedAgentIds"] == [detail["agentId"]]
    assert timeline["outcome"]["deliveries"] == []
    assert {item["metadataKey"] for item in timeline["projectionRefs"]} == {
        "sourceSessionId",
        "sourceMessageId",
        "projectionRef",
    }
    assert all(item["projectionCanWrite"] is False for item in timeline["projectionRefs"])
    session_ref = next(item for item in timeline["projectionRefs"] if item["metadataKey"] == "sourceSessionId")
    message_ref = next(item for item in timeline["projectionRefs"] if item["metadataKey"] == "sourceMessageId")
    assert session_ref["sourceRef"]["owner"] == "ConversationLedger"
    assert session_ref["canonicalEditRoute"] == f"/chat?session={detail['id']}"
    assert message_ref["projectionEdit"]["mode"] == "deep_link_to_source"
    assert message_ref["canonicalEditRoute"].startswith(f"/chat?session={detail['id']}&message=")
    assert agent_directory_service.list_agent_inbox_messages_for_agent(detail["agentId"], status="") == []
    # Scheduled context must not block on kernel ids (accept path is kernel-free).
    assert "kernelTaskId" not in (captured_contexts[0].get("message_metadata") or {})
    assert any(
        event[0][:3] == ("conversation", "kernel", "session.submit.kernel_trace_recorded")
        and event[1]["fields"]["kernelTaskId"] == kernel_task_id
        for event in recorded_events
    )


def test_session_submit_kernel_bridge_failure_does_not_block_turn(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(
        agent_kernel_service,
        "handle_kernel_event",
        lambda _payload: (_ for _ in ()).throw(RuntimeError("kernel unavailable")),
    )
    captured_contexts = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: captured_contexts.append(dict(context)))
    detail = session_service.create_chat_session(title="Kernel Failure Agent")

    accepted = session_service.submit_session_message(
        detail["id"],
        "Kernel 临时不可用时也要继续本轮。",
        include_started_turn_id=True,
    )

    assert accepted["startedTurnId"]
    # Turn is scheduled even if deferred kernel audit fails.
    assert captured_contexts
    assert captured_contexts[0]["turn_id"] == accepted["startedTurnId"]
    kernel_trace = session_service._await_last_submit_kernel_trace(timeout=5.0) or {}
    assert kernel_trace.get("status") == "failed"
    assert kernel_trace.get("errorType") == "RuntimeError"


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
            captured.setdefault("prompts", []).append(str(initial_prompt or ""))
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
    assert any("Beta，请接着审查 Alpha 的方案。" in prompt for prompt in captured["prompts"])
    assert any("Beta 已收到 Alpha 的私信，并给出回复。" in prompt for prompt in captured["prompts"])
    assert any("面向当前用户或当前任务汇总这条回复" in prompt for prompt in captured["prompts"])
    assert "AgentInboxMessages:" in captured["runtimeContext"]

    detail = session_service.get_session_detail(beta["id"])
    assert detail["messages"][-2]["role"] == "user"
    assert detail["messages"][-2]["metadata"]["kind"] == "agent_inbox_message"
    assert detail["messages"][-2]["metadata"]["messageId"] == payload["messageId"]
    assert detail["messages"][-2]["metadata"]["sourceAgentName"] == alpha["agentDisplayName"]
    assert _assistant_visible_text(detail["messages"][-1]) == "Beta 已收到 Alpha 的私信，并给出回复。"
    assert agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="pending") == []
    consumed = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="consumed")
    assert consumed[0]["messageId"] == payload["messageId"]
    assert consumed[0]["consumedByTurnId"] == payload["delivery"]["turnId"]
    alpha_detail = session_service.get_session_detail(alpha["id"])
    assert alpha_detail["messages"][-2]["metadata"]["kind"] == "agent_inbox_message"
    assert alpha_detail["messages"][-2]["metadata"]["inboxKind"] == "agent_inbox_reply"
    assert alpha_detail["messages"][-2]["metadata"]["sourceAgentId"] == beta["agentId"]
    assert alpha_detail["messages"][-2]["content"].startswith("[Agent 私信回复]")
    alpha_consumed = agent_directory_service.list_agent_inbox_messages_for_agent(alpha["agentId"], status="consumed")
    assert alpha_consumed[0]["kind"] == "agent_inbox_reply"
    assert alpha_consumed[0]["metadata"]["replyToMessageId"] == payload["messageId"]
    assert alpha_consumed[0]["metadata"]["sourceSurface"] == "agent_inbox_reply"
    assert alpha_consumed[0]["metadata"]["kernelTaskId"]


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


def test_agent_inbox_busy_message_wakes_once_after_session_release(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    captured_prompts: list[str] = []
    runtime_event_codes: list[str] = []

    class ReplyingAgent:
        def seed_chat_history(self, messages):
            return None

        def seed_runtime_context(self, context):
            return None

        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            captured_prompts.append(prompt)
            return {
                "status": "completed",
                "raw_output": "Beta 已处理排队私信。",
                "summary": "Beta handled queued inbox message",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: ReplyingAgent())
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda _category, _surface, event_code, **_kwargs: runtime_event_codes.append(event_code),
    )

    session_service._set_session_running(beta["id"], True, turn_id="turn-busy")
    try:
        response = client.post(
            f"/api/agents/{beta['agentId']}/messages",
            json={
                "sourceAgentId": alpha["agentId"],
                "content": "Beta，空闲后自动处理这条私信。",
                "wakeTarget": True,
            },
        )
    finally:
        session_service._set_session_running(beta["id"], False, turn_id="turn-busy")

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["delivery"]["wakeStatus"] == "skipped_busy"
    pending = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="pending")
    assert pending[0]["metadata"]["wakeRequested"] is True

    released_context = {
        "session_id": beta["id"],
        "turn_id": "turn-busy",
        "agent_id": beta["agentId"],
    }
    session_service._release_scheduled_session_turn(released_context)
    session_service._release_scheduled_session_turn(released_context)

    matching_prompts = [
        prompt for prompt in captured_prompts
        if "Beta，空闲后自动处理这条私信。" in prompt
    ]
    assert len(matching_prompts) == 1
    assert agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="pending") == []
    consumed = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="consumed")
    assert [item["messageId"] for item in consumed] == [payload["messageId"]]
    assert "agent_inbox.idle_drain_started" in runtime_event_codes


def test_agent_inbox_startup_recovery_wakes_persisted_message_once(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    started: list[tuple[tuple, dict]] = []
    runtime_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda *args, **kwargs: started.append((args, kwargs)) or {"startedTurnId": "turn-startup"},
    )
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: runtime_events.append((args, kwargs)) or {"accepted": True},
    )
    message = agent_directory_service.write_agent_inbox_message(
        beta["agentId"],
        source_agent_id=alpha["agentId"],
        content="Beta，请在后端恢复后继续处理。",
        metadata={"wakeRequested": True},
    )

    first = session_service.recover_wakeable_agent_inbox_messages_on_startup()
    second = session_service.recover_wakeable_agent_inbox_messages_on_startup()

    assert len(started) == 1
    assert started[0][0][0] == beta["id"]
    assert "Beta，请在后端恢复后继续处理。" in started[0][0][1]
    assert first["startedCount"] == 1
    assert second["startedCount"] == 0
    assert agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="pending") == []
    consumed = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="consumed")
    assert [item["messageId"] for item in consumed] == [message["messageId"]]
    summaries = [
        kwargs["fields"]
        for args, kwargs in runtime_events
        if args[2] == "agent_inbox.startup_recovery_completed"
    ]
    assert summaries[0]["trigger"] == "backend_startup"
    assert summaries[0]["startedCount"] == 1


def test_agent_inbox_startup_recovery_repairs_stale_turn_without_full_conversation_load(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    session = session_service.create_chat_session(title="Interrupted Agent")
    payload = load_chat_state(tmp_path)
    conversation = next(
        item
        for item in payload["conversations"]
        if item["conversation_id"] == session["id"]
    )
    conversation["last_turn_status"] = "running"
    save_chat_state(tmp_path, payload)

    def fail_full_load(*_args, **_kwargs):
        raise AssertionError("startup recovery must not hydrate every conversation")

    monkeypatch.setattr(session_service, "_load_conversations", fail_full_load)

    summary = session_service.recover_wakeable_agent_inbox_messages_on_startup()

    repaired_payload = load_chat_state(tmp_path)
    repaired = next(
        item
        for item in repaired_payload["conversations"]
        if item["conversation_id"] == session["id"]
    )
    assert summary["errorCount"] == 0
    assert repaired["last_turn_status"] == "ready"
    assert summary["repairDurationMs"] >= 0
    assert summary["agentScanDurationMs"] >= 0


def test_agent_inbox_startup_recovery_reads_registry_once_without_agent_api_hydration(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    session_service.create_chat_session(title="Alpha Agent")
    session_service.create_chat_session(title="Beta Agent")
    original_load_state = agent_directory_service.load_state
    expected_scanned_agent_count = sum(
        1
        for item in original_load_state().get("agents") or []
        if isinstance(item, dict)
        and str(item.get("status") or "active").strip().lower() != "archived"
        and str(item.get("agentId") or "").strip()
    )
    load_state_calls = 0
    inbox_read_calls = 0

    def counted_load_state():
        nonlocal load_state_calls
        load_state_calls += 1
        return original_load_state()

    def fail_agent_api_hydration(*_args, **_kwargs):
        raise AssertionError("startup inbox recovery must not hydrate the Agent API directory")

    def counted_inbox_read(*_args, **_kwargs):
        nonlocal inbox_read_calls
        inbox_read_calls += 1
        return []

    monkeypatch.setattr(agent_directory_service, "load_state", counted_load_state)
    monkeypatch.setattr(agent_directory_service, "list_agents", fail_agent_api_hydration)
    monkeypatch.setattr(agent_directory_service, "_read_jsonl", counted_inbox_read)

    summary = session_service.recover_wakeable_agent_inbox_messages_on_startup()

    assert summary["errorCount"] == 0
    assert summary["scannedAgentCount"] == expected_scanned_agent_count
    assert summary["nonEmptyInboxCount"] == 0
    assert summary["wakeableMessageCount"] == 0
    assert load_state_calls == 1
    assert inbox_read_calls == 0


def test_agent_inbox_wake_redirects_stale_target_session_to_current_agent_session(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    original_session_id = beta["id"]
    current_session_id = "session-beta-rebound"
    message = agent_directory_service.write_agent_inbox_message(
        beta["agentId"],
        source_agent_id=alpha["agentId"],
        content="Beta，请在会话重建后继续处理。",
        metadata={"wakeRequested": True},
    )
    agent_directory_service.update_agent_instance(
        beta["agentId"],
        direct_session_id=current_session_id,
        metadata={"previousDirectSessionId": original_session_id},
    )
    submitted_session_ids: list[str] = []
    runtime_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, *_args, **_kwargs: (
            submitted_session_ids.append(session_id) or {"startedTurnId": "turn-rebound"}
        ),
    )
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: runtime_events.append((args, kwargs)),
    )

    delivery = session_service.wake_agent_for_inbox_message(message)

    assert submitted_session_ids == [current_session_id]
    assert delivery["wakeStatus"] == "started"
    assert delivery["targetSessionId"] == current_session_id
    assert delivery["persistedTargetSessionId"] == original_session_id
    assert delivery["targetSessionRedirected"] is True
    wake_started = next(
        kwargs["fields"]
        for args, kwargs in runtime_events
        if args[2] == "agent_inbox.wake_started"
    )
    assert wake_started["targetSessionId"] == current_session_id
    assert wake_started["persistedTargetSessionId"] == original_session_id
    assert wake_started["targetSessionRedirected"] is True
    consumed = agent_directory_service.list_agent_inbox_messages_for_agent(
        beta["agentId"],
        status="consumed",
    )
    assert consumed[0]["consumedBySessionId"] == current_session_id


def test_agent_inbox_startup_recovery_leaves_mailbox_only_message_pending(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    started = []
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda *args, **kwargs: started.append((args, kwargs)) or {"startedTurnId": "unexpected"},
    )
    message = agent_directory_service.write_agent_inbox_message(
        beta["agentId"],
        source_agent_id=alpha["agentId"],
        content="只进入邮箱，不应在启动时唤醒。",
        metadata={"wakeRequested": False},
    )

    summary = session_service.recover_wakeable_agent_inbox_messages_on_startup()

    assert started == []
    assert summary["eligibleAgentCount"] == 0
    pending = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="pending")
    assert [item["messageId"] for item in pending] == [message["messageId"]]


def test_agent_inbox_startup_recovery_leaves_busy_target_pending(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    started = []
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda *args, **kwargs: started.append((args, kwargs)) or {"startedTurnId": "unexpected"},
    )
    message = agent_directory_service.write_agent_inbox_message(
        beta["agentId"],
        source_agent_id=alpha["agentId"],
        content="目标忙碌时继续留在持久化邮箱。",
        metadata={"wakeRequested": True},
    )
    session_service._set_session_running(beta["id"], True, turn_id="turn-busy")
    try:
        summary = session_service.recover_wakeable_agent_inbox_messages_on_startup()
    finally:
        session_service._set_session_running(beta["id"], False, turn_id="turn-busy")

    assert started == []
    assert summary["wakeStatusCounts"] == {"skipped_busy": 1}
    pending = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="pending")
    assert [item["messageId"] for item in pending] == [message["messageId"]]


def test_agent_inbox_startup_recovery_does_not_consume_archived_target(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    message = agent_directory_service.write_agent_inbox_message(
        beta["agentId"],
        source_agent_id=alpha["agentId"],
        content="目标归档后不能消费。",
        metadata={"wakeRequested": True},
    )
    agent_directory_service.archive_agent_instance(beta["agentId"])

    summary = session_service.recover_wakeable_agent_inbox_messages_on_startup()

    assert summary["eligibleAgentCount"] == 0
    pending = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="pending")
    assert [item["messageId"] for item in pending] == [message["messageId"]]


def test_agent_inbox_idle_release_does_not_wake_mailbox_only_message(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    captured_prompts: list[str] = []

    class ReplyingAgent:
        def seed_chat_history(self, messages):
            return None

        def seed_runtime_context(self, context):
            return None

        def run_single_turn(self, initial_prompt=None):
            captured_prompts.append(str(initial_prompt or ""))
            return {
                "status": "completed",
                "raw_output": "unexpected",
                "summary": "unexpected",
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
            "content": "Beta，这条消息只进入 mailbox。",
            "wakeTarget": False,
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    pending = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="pending")
    assert pending[0]["metadata"]["wakeRequested"] is False

    session_service._release_scheduled_session_turn(
        {
            "session_id": beta["id"],
            "turn_id": "turn-finished",
            "agent_id": beta["agentId"],
        }
    )

    assert captured_prompts == []
    remaining = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="pending")
    assert [item["messageId"] for item in remaining] == [payload["messageId"]]


def test_agent_message_tool_blocks_generic_cross_agent_before_kernel_delivery(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    _allow_agent_message_tool(alpha["agentId"])
    from core.agent_kernel import adapters

    kernel_calls: list[dict] = []
    monkeypatch.setattr(adapters, "submit_agent_message_event", lambda **kwargs: kernel_calls.append(kwargs))

    result, action = execute_authorized_agent_tool(
        alpha["agentId"],
        alpha["id"],
        "agent_message_tool",
        {
            "target_session": beta["id"],
            "target_agent": beta["agentCode"],
            "content": "Beta，请从架构风险角度审查这轮改造。",
            "summary": "请求架构审查",
            "wake_target": True,
            "metadata_json": "{\"priority\":\"normal\"}",
        },
    )
    payload = json.loads(result)
    assert action is None
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["route"] == "policy"
    assert payload["error"] == "policy_blocked"
    assert payload["reason"] == "cross_agent_policy_required"
    assert payload["sourceAgentId"] == alpha["agentId"]
    assert payload["sourceSessionId"] == alpha["id"]
    assert payload["targetAgentId"] == beta["agentId"]
    assert payload["targetAgentCode"] == beta["agentCode"]
    assert payload["targetSessionId"] == beta["id"]
    assert payload["wakeStatus"] == "blocked"
    assert payload["delivery"]["allowed"] is False
    assert payload["delivery"]["inboxMessageId"] == ""

    pending = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="pending")
    assert pending == []
    assert kernel_calls == []


def test_session_reference_message_persists_reference_and_schedules_query_context(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    _seed_ledger_messages(
        tmp_path,
        beta["id"],
        [
            {"role": "user", "content": "Beta 历史目标", "timestamp": "2026-06-05T01:00:00Z"},
            {"role": "assistant", "content": "Beta 历史结论", "timestamp": "2026-06-05T01:01:00Z"},
        ],
    )
    scheduled = []
    monkeypatch.setattr(session_service, "_submit_scheduled_session_turn", lambda context: scheduled.append(context))

    result = session_service.submit_session_message_lightweight(
        alpha["id"],
        "",
        references=[
            {
                "referenceId": f"session:{beta['id']}",
                "kind": "session",
                "sessionId": beta["id"],
                "title": "Beta Agent",
                "agentId": beta["agentId"],
                "agentDisplayName": "Beta Agent",
            }
        ],
    )

    assert result["accepted"] is True
    detail = session_service.get_session_detail(alpha["id"])
    user_message = [message for message in detail["messages"] if message["role"] == "user"][-1]
    assert user_message["references"][0]["sessionId"] == beta["id"]
    assert user_message["metadata"]["sessionReferences"][0]["permissions"]["query"] is True
    assert scheduled
    assert "Session References" in scheduled[0]["user_message"]
    assert scheduled[0]["session_references"][0]["sessionId"] == beta["id"]


def test_session_reference_query_tool_only_reads_current_turn_references(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    _seed_ledger_messages(
        tmp_path,
        beta["id"],
        [
            {"role": "user", "content": "需要分析缓存命中", "timestamp": "2026-06-05T01:00:00Z"},
            {"role": "assistant", "content": "缓存命中来自上游 usage。", "timestamp": "2026-06-05T01:01:00Z"},
        ],
    )

    with session_reference_context([
        {
            "referenceId": f"session:{beta['id']}",
            "kind": "session",
            "sessionId": beta["id"],
            "title": "Beta Agent",
            "agentId": beta["agentId"],
        }
    ]):
        result, action = ToolExecutor().execute(
            "session_reference_query_tool",
            {"reference_id": f"session:{beta['id']}", "query": "缓存", "limit": 2},
        )

    payload = json.loads(result)
    assert action is None
    assert payload["status"] == "ok"
    assert payload["reference"]["sessionId"] == beta["id"]
    assert payload["returnedMessageCount"] == 2
    assert "缓存" in payload["messages"][0]["content"]

    blocked_result, _ = ToolExecutor().execute(
        "session_reference_query_tool",
        {"session_id": beta["id"]},
    )
    blocked_payload = json.loads(blocked_result)
    assert blocked_payload["status"] == "error"
    assert blocked_payload["error"] == "session_reference_not_allowed"


@pytest.mark.parametrize("stored_content", ["", "   "])
def test_session_reference_query_uses_turn_items_for_blank_assistant_content(tmp_path, monkeypatch, stored_content):
    _use_tmp_project_root(tmp_path, monkeypatch)
    from tools.session_reference_tools import session_reference_query_tool

    target_session_id = "session-visible-turn-items"
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda *args, **kwargs: {
            "id": target_session_id,
            "title": "Visible output",
            "agentId": "agent-target",
            "messages": [
                {
                    "role": "assistant",
                    "content": stored_content,
                    "turnItems": [
                        {"type": "agent_message", "text": "可见最终答复"},
                    ],
                }
            ],
        },
    )

    with session_reference_context(
        [
            {
                "referenceId": f"session:{target_session_id}",
                "kind": "session",
                "sessionId": target_session_id,
                "title": "Visible output",
                "agentId": "agent-target",
            }
        ]
    ):
        payload = json.loads(
            session_reference_query_tool(
                reference_id=f"session:{target_session_id}",
                query="最终答复",
            )
        )

    assert payload["status"] == "ok"
    assert payload["matchedMessageCount"] == 1
    assert payload["messages"][0]["content"] == "可见最终答复"


def test_agent_message_tool_resolves_ui_composite_agent_label(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = _create_secondary_session_for_agent(alpha, title="Alpha Review Session")
    _allow_agent_message_tool(alpha["agentId"])
    alpha_agent = agent_directory_service.get_agent(alpha["agentId"])
    label = f"{alpha_agent['agentCode']} · {alpha_agent['displayName']}"

    result, action = execute_authorized_agent_tool(
        alpha["agentId"],
        alpha["id"],
        "agent_message_tool",
        {
            "target_session": beta["id"],
            "target_agent": label,
            "content": "Beta，请确认 UI 复合标签也能投递。",
            "summary": "复合标签投递",
            "wake_target": False,
        },
    )

    payload = json.loads(result)
    assert action is None
    assert payload["ok"] is True
    assert payload["status"] == "sent"
    assert payload["targetAgentId"] == beta["agentId"]
    assert payload["targetAgentCode"] == alpha_agent["agentCode"]


@pytest.mark.parametrize(
    "label_template",
    [
        "{code} - {name}",
        "{code}: {name}",
        "{code}（{name}）",
    ],
)
def test_agent_message_tool_resolves_common_agent_label_variants(tmp_path, monkeypatch, label_template):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = _create_secondary_session_for_agent(alpha, title="Alpha Review Session")
    _allow_agent_message_tool(alpha["agentId"])
    alpha_agent = agent_directory_service.get_agent(alpha["agentId"])
    label = label_template.format(code=alpha_agent["agentCode"], name=alpha_agent["displayName"])

    result, action = execute_authorized_agent_tool(
        alpha["agentId"],
        alpha["id"],
        "agent_message_tool",
        {
            "target_session": beta["id"],
            "target_agent": label,
            "content": "Beta，请确认常见标签格式也能投递。",
            "summary": "标签变体投递",
            "wake_target": False,
        },
    )

    payload = json.loads(result)
    assert action is None
    assert payload["ok"] is True
    assert payload["targetAgentId"] == beta["agentId"]


def test_agent_message_tool_resolves_unique_role_key_target(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = _create_secondary_session_for_agent(alpha, title="Alpha Research Workspace")
    _allow_agent_message_tool(alpha["agentId"])
    agent_directory_service.update_agent_instance(
        alpha["agentId"],
        primary_mode="research",
        role_key="source_finder",
    )

    result, action = execute_authorized_agent_tool(
        alpha["agentId"],
        alpha["id"],
        "agent_message_tool",
        {
            "target_session": beta["id"],
            "target_agent": "source_finder",
            "content": "请接收资料发现阶段的候选线索。",
            "summary": "资料获取交接",
            "wake_target": False,
        },
    )

    payload = json.loads(result)
    assert action is None
    assert payload["ok"] is True
    assert payload["status"] == "sent"
    assert payload["targetAgentId"] == beta["agentId"]


def test_agent_message_tool_preserves_full_message_body(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = _create_secondary_session_for_agent(alpha, title="Alpha Report Workspace")
    _allow_agent_message_tool(alpha["agentId"])
    full_report = "\n".join(f"第 {index:02d} 行：工具发送报告正文" for index in range(1, 31))

    result, action = execute_authorized_agent_tool(
        alpha["agentId"],
        alpha["id"],
        "agent_message_tool",
        {
            "target_session": beta["id"],
            "target_agent": beta["agentId"],
            "content": full_report,
            "summary": "完整报告",
            "wake_target": False,
        },
    )

    payload = json.loads(result)
    assert action is None
    assert payload["ok"] is True
    assert payload["kernel"]["taskId"]
    pending = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="pending")
    assert pending[0]["content"] == "完整报告"


def test_agent_message_tool_can_wake_secondary_session_for_same_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = _create_secondary_session_for_agent(alpha, title="Alpha Follow-up Session")
    _allow_agent_message_tool(alpha["agentId"])
    captured = {}

    class ReplyingAgent:
        def seed_chat_history(self, messages):
            captured["history"] = list(messages)

        def seed_runtime_context(self, context):
            captured["runtimeContext"] = context

        def run_single_turn(self, initial_prompt=None):
            captured.setdefault("prompts", []).append(str(initial_prompt or ""))
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

    result, action = execute_authorized_agent_tool(
        alpha["agentId"],
        alpha["id"],
        "agent_message_tool",
        {
            "target_session": beta["id"],
            "target_agent": beta["agentId"],
            "content": "Beta，请接力回答 Alpha 的私信。",
            "wake_target": True,
        },
    )

    payload = json.loads(result)
    assert action is None
    assert payload["ok"] is True
    assert payload["route"] == "kernel"
    assert payload["kernel"]["taskId"]
    assert payload["wakeStatus"] == "started"
    assert payload["delivery"]["targetSessionId"] == beta["id"]
    assert payload["delivery"]["turnId"]
    assert any("Beta，请接力回答 Alpha 的私信。" in prompt for prompt in captured["prompts"])
    assert "AgentInboxMessages:" in captured["runtimeContext"]

    detail = session_service.get_session_detail(beta["id"])
    assert detail["messages"][-2]["role"] == "user"
    assert detail["messages"][-2]["metadata"]["kind"] == "agent_inbox_message"
    assert detail["messages"][-2]["metadata"]["messageId"] == payload["messageId"]
    assert detail["messages"][-2]["metadata"]["sourceAgentName"] == alpha["agentDisplayName"]
    assert _assistant_visible_text(detail["messages"][-1]) == "Beta 已通过 agent_message_tool 接到私信。"
    assert agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="pending") == []
    consumed = agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"], status="consumed")
    assert consumed[0]["messageId"] == payload["messageId"]
    assert consumed[0]["consumedByTurnId"] == payload["delivery"]["turnId"]
    alpha_detail = session_service.get_session_detail(alpha["id"])
    assert alpha_detail["messages"] == []


def test_research_org_inbox_wake_carries_communication_metadata_to_conversation(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_tmp_research_org_workspace(tmp_path, monkeypatch)
    org = research_organization_service.get_research_organization()
    steward = next(node for node in org["agents"] if node["role"] == "capability_steward")
    ceo = next(node for node in org["agents"] if node["role"] == "ceo")

    captured = {}

    def fake_submit_session_message(session_id, content, **kwargs):
        captured["sessionId"] = session_id
        captured["content"] = content
        captured["kwargs"] = kwargs
        return {"startedTurnId": "turn-research-org"}

    monkeypatch.setattr(session_service, "submit_session_message", fake_submit_session_message)

    result = research_organization_service.send_research_org_message(
        {
            "sourceType": "agent",
            "sourceAgentId": steward["agentId"],
            "sourceSessionId": steward["agent"]["directSessionId"],
            "targetAgentId": ceo["agentId"],
            "messageType": "request",
            "intent": "decision_request",
            "content": "请 CEO 决策数据库试水团队是否扩招。",
            "summary": "数据库试水团队扩招决策",
            "wakeTarget": False,
            "createdBy": "agent_tool",
        }
    )

    delivery = result["message"]["deliveries"][0]
    assert delivery["wakeStatus"] == "started"
    assert delivery["kernelTaskId"]
    assert delivery["kernelEventId"]

    assert captured["sessionId"] == ceo["agent"]["directSessionId"]
    metadata = captured["kwargs"]["message_metadata"]
    assert metadata["kind"] == "agent_inbox_message"
    assert metadata["inboxKind"] == "research_org_request"
    assert metadata["researchOrgMessageId"] == result["message"]["messageId"]
    assert metadata["researchOrgMessageType"] == "request"
    assert metadata["researchOrgIntent"] == "decision_request"
    assert metadata["researchOrgDeliveryMode"] == "private"
    assert metadata["communicationEdgeId"] == delivery["edgeId"]
    consumed = agent_directory_service.list_agent_inbox_messages_for_agent(ceo["agentId"], status="consumed")
    assert consumed[0]["createdBy"] == "research_org"
    assert consumed[0]["metadata"]["sourceSurface"] == "research_org"
    assert consumed[0]["metadata"]["researchOrgMessageId"] == result["message"]["messageId"]
    assert consumed[0]["metadata"]["kernelTaskId"] == delivery["kernelTaskId"]
    assert consumed[0]["metadata"]["kernelEventId"] == delivery["kernelEventId"]
    audit = result["organization"]["auditEvents"][-1]
    assert audit["messageId"] == result["message"]["messageId"]
    assert audit["kernelTaskId"] == delivery["kernelTaskId"]
    assert audit["kernelEventId"] == delivery["kernelEventId"]
    assert audit["kernelOutcomeStatus"] == "succeeded"


def test_agent_inbox_auto_reply_skips_when_agent_message_tool_already_sent_to_source(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    events = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )

    inbox_message = agent_directory_service.write_agent_inbox_message(
        beta["agentId"],
        source_agent_id=alpha["agentId"],
        content="请输出完整人才缺口分析报告。",
    )
    messages = [
        {
            "role": "user",
            "content": "inbox",
            "metadata": {
                "kind": "agent_inbox_message",
                "messageId": inbox_message["messageId"],
                "sourceAgentId": alpha["agentId"],
                "targetAgentId": beta["agentId"],
                "threadId": inbox_message["threadId"],
            },
        }
    ]
    tool_result = json.dumps(
        {
            "ok": True,
            "status": "sent",
            "targetAgentId": alpha["agentId"],
            "messageId": "agentmsg-explicit",
        },
        ensure_ascii=False,
    )

    reply = session_service._build_agent_inbox_turn_reply(
        messages,
        assistant_text="已将人才缺口分析报告发送给 CEO 夏予安。消息投递成功。",
        tool_calls=[
            {
                "name": "agent_message_tool",
                "arguments": {"target_agent": alpha["agentId"]},
                "resultPreview": tool_result,
            }
        ],
        source_session_id=beta["id"],
        source_turn_id="turn-beta",
    )

    assert reply is None
    assert any(item[0][2] == "agent_inbox.reply_skipped" for item in events)
    fields = events[-1][1]["fields"]
    assert fields["reason"] == "explicit_agent_message_sent"
    assert agent_directory_service.list_agent_inbox_messages_for_agent(alpha["agentId"], status="pending") == []


def test_agent_inbox_auto_reply_not_skipped_for_failed_agent_message_tool(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    inbox_message = agent_directory_service.write_agent_inbox_message(
        beta["agentId"],
        source_agent_id=alpha["agentId"],
        content="请输出完整人才缺口分析报告。",
    )
    failed_tool_result = json.dumps(
        {
            "ok": False,
            "status": "blocked",
            "error": "target_not_found",
            "targetAgentId": alpha["agentId"],
        },
        ensure_ascii=False,
    )

    reply = session_service._build_agent_inbox_turn_reply(
        [
            {
                "role": "user",
                "metadata": {
                    "kind": "agent_inbox_message",
                    "messageId": inbox_message["messageId"],
                    "sourceAgentId": alpha["agentId"],
                    "targetAgentId": beta["agentId"],
                    "threadId": inbox_message["threadId"],
                },
            }
        ],
        assistant_text="我无法直接完成投递：目标 Agent 未找到。请改用稳定代号后重试。",
        tool_calls=[
            {
                "name": "agent_message_tool",
                "arguments": {"target_agent": "A012 · 江知微"},
                "resultPreview": failed_tool_result,
            }
        ],
        source_session_id=beta["id"],
        source_turn_id="turn-beta",
    )

    assert reply is not None
    assert reply["targetAgentId"] == alpha["agentId"]
    assert "目标 Agent 未找到" in reply["content"]


def test_agent_inbox_auto_reply_skips_short_delivery_confirmation(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    events = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )
    inbox_message = agent_directory_service.write_agent_inbox_message(
        beta["agentId"],
        source_agent_id=alpha["agentId"],
        content="请输出完整人才缺口分析报告。",
    )

    reply = session_service._build_agent_inbox_turn_reply(
        [
            {
                "role": "user",
                "metadata": {
                    "kind": "agent_inbox_message",
                    "messageId": inbox_message["messageId"],
                    "sourceAgentId": alpha["agentId"],
                    "targetAgentId": beta["agentId"],
                },
            }
        ],
        assistant_text="已将人才缺口分析报告发送给 CEO 夏予安。消息投递成功。",
        tool_calls=[],
        source_session_id=beta["id"],
        source_turn_id="turn-beta",
    )

    assert reply is None
    assert events[-1][1]["fields"]["reason"] == "operation_confirmation"


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
    target_session = session_service.create_chat_session(title="Capability Steward Review", agent_id=steward["agentId"])
    _allow_agent_message_tool(ceo["agentId"])

    result, action = execute_authorized_agent_tool(
        ceo["agentId"],
        ceo["agent"]["directSessionId"],
        "agent_message_tool",
        {
            "target_session": target_session["id"],
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
    assert payload["targetSessionId"] == target_session["id"]
    assert payload["researchOrgMessageId"]
    assert payload["kernel"]["taskId"]
    assert payload["kernel"]["eventId"]
    assert payload["delivery"]["edgeId"] == f"edge-{ceo['agentId']}-{steward['agentId']}"
    assert payload["delivery"]["targetSessionId"] == target_session["id"]
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
    assert tool_fields["taskId"] == payload["kernel"]["taskId"]

    pending = agent_directory_service.list_agent_inbox_messages_for_agent(steward["agentId"], status="pending")
    assert [item["messageId"] for item in pending] == [payload["messageId"]]
    assert pending[0]["kind"] == "research_org_task"
    assert pending[0]["createdBy"] == "research_org"
    assert pending[0]["metadata"]["sourceSurface"] == "research_org"
    assert pending[0]["metadata"]["researchOrgMessageId"] == payload["researchOrgMessageId"]
    assert pending[0]["metadata"]["researchOrgMessageType"] == "task"
    assert pending[0]["metadata"]["researchOrgIntent"] == "tool_policy"
    assert pending[0]["metadata"]["kernelTaskId"] == payload["kernel"]["taskId"]
    assert pending[0]["metadata"]["kernelEventId"] == payload["kernel"]["eventId"]


def test_agent_message_tool_blocks_research_core_message_without_intent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_tmp_research_org_workspace(tmp_path, monkeypatch)
    org = research_organization_service.get_research_organization()
    ceo = next(node for node in org["agents"] if node["role"] == "ceo")
    steward = next(node for node in org["agents"] if node["role"] == "capability_steward")
    _allow_agent_message_tool(ceo["agentId"])

    result, action = execute_authorized_agent_tool(
        ceo["agentId"],
        ceo["agent"]["directSessionId"],
        "agent_message_tool",
        {
            "target_session": steward["agent"]["directSessionId"],
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
    assert delivery["kernelTaskId"]
    pending = agent_directory_service.list_agent_inbox_messages_for_agent(ceo["agentId"], status="pending")
    assert [item["messageId"] for item in pending] == [delivery["inboxMessageId"]]
    assert pending[0]["metadata"]["researchOrgIntent"] == "status_report"
    assert pending[0]["metadata"]["kernelTaskId"] == delivery["kernelTaskId"]


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
    _allow_agent_message_tool(advisor["agentId"])

    result, action = execute_authorized_agent_tool(
        advisor["agentId"],
        advisor["agent"]["directSessionId"],
        "agent_message_tool",
        {
            "target_session": ceo["agent"]["directSessionId"],
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
    _allow_agent_message_tool(outsider["agentId"])

    result, action = execute_authorized_agent_tool(
        outsider["agentId"],
        outsider["id"],
        "agent_message_tool",
        {
            "target_session": steward["agent"]["directSessionId"],
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
    _seed_ledger_messages(
        tmp_path,
        alpha["id"],
        [{"role": "user", "content": "Alpha 已有真实会话活动", "timestamp": "2026-06-05T01:00:00Z"}],
    )
    _seed_ledger_messages(
        tmp_path,
        beta["id"],
        [{"role": "user", "content": "Beta 已有真实会话活动", "timestamp": "2026-06-05T01:01:00Z"}],
    )

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

    alpha_messages = session_service.get_session_detail("session-alpha")["messages"]
    beta_messages = session_service.get_session_detail("session-beta")["messages"]
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
        assert "共通群聊" in _assistant_visible_text(synced)
        assert "同步到各自会话" in _assistant_visible_text(synced)
        assert own_title in _assistant_visible_text(synced)
        assert peer_title in _assistant_visible_text(synced)

    chat_room_service._sync_group_round_to_participant_sessions(detail, latest_round)
    alpha_messages_after_resync = session_service.get_session_detail("session-alpha")["messages"]
    beta_messages_after_resync = session_service.get_session_detail("session-beta")["messages"]
    assert len(alpha_messages_after_resync) == len(alpha_messages)
    assert len(beta_messages_after_resync) == len(beta_messages)


def test_tool_policy_blocks_before_tool_execution_and_returns_correctable_error(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Restricted",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
    )
    agent_directory_service.update_agent_instance(
        agent["agentId"],
        tool_policy={"blockedTools": ["cli_tool"]},
    )

    result, action = execute_authorized_agent_tool(
        agent["agentId"],
        agent["directSessionId"],
        "cli_tool",
        {"command": "echo should-not-run"},
        executable_tools=(),
    )

    assert action is None
    assert "未被本回合授权执行" in result
    observation_path = tmp_path / agent["workspacePath"] / "events" / "tool_observations.jsonl"
    assert observation_path.exists()
    assert "authorization_denied" in observation_path.read_text(encoding="utf-8")
