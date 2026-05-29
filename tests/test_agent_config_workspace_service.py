import json

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.orchestration import context_engine
from core.web.services import (
    agent_config_workspace_service,
    agent_directory_service,
    agent_mode_binding_service,
    chat_room_service,
    config_service,
    prompt_template_service,
    session_service,
)


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _raw_mode_binding(mode: str):
    path = agent_mode_binding_service.mode_binding_path()
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return next(
        item
        for item in payload.get("bindings") or []
        if isinstance(item, dict) and item.get("mode") == mode
    )


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)


def _fake_config_workspace():
    return {
        "profileCards": [
            {
                "profileId": "primary",
                "label": "Primary",
                "modelRef": "model-primary",
                "selectedModelId": "model-primary",
                "selectedModelLabel": "Primary model",
                "model": "gpt-test",
                "providerKind": "openai",
                "baseUrl": "https://example.invalid/v1",
                "apiKeyEnv": "OPENAI_API_KEY",
                "apiKeyConfigured": True,
                "apiKeyState": "configured",
                "apiKeySource": "env:OPENAI_API_KEY",
                "requiredModelMissing": False,
            },
            {
                "profileId": "research_missing_key",
                "label": "Research missing key",
                "modelRef": "model-research",
                "selectedModelId": "model-research",
                "selectedModelLabel": "Research model",
                "model": "research-test",
                "providerKind": "relay",
                "baseUrl": "https://relay.invalid",
                "apiKeyEnv": "RELAY_API_KEY",
                "apiKeyConfigured": False,
                "apiKeyState": "missing",
                "apiKeySource": "env:RELAY_API_KEY",
                "requiredModelMissing": False,
            },
        ],
        "modelOptions": [],
    }


def test_agent_config_workspace_lists_agents_once_and_derives_references(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    chat_agent = session_service.create_chat_session(title="会话 Agent")
    research_session = session_service.create_chat_session(title="科研 Agent", profile_id="primary")
    research_agent = agent_directory_service.update_agent_instance(
        research_session["agentId"],
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
        metadata={"researchAgentKey": "broad"},
    )
    agent_mode_binding_service.update_mode_binding(
        "research",
        pool=[research_agent["agentId"]],
        flow_bindings={"broad_search": research_agent["agentId"]},
    )
    chat_room_service.create_chat_room(
        title="研究群聊",
        participant_agent_ids=[chat_agent["agentId"], research_agent["agentId"]],
    )
    archived_agent = agent_directory_service.create_agent_instance(display_name="旧 Agent")
    agent_directory_service.archive_agent_instance(archived_agent["agentId"])

    payload = agent_config_workspace_service.get_agent_config_workspace()

    agent_ids = [item["agentId"] for item in payload["agents"]]
    assert len(agent_ids) == len(set(agent_ids))
    assert chat_agent["agentId"] in agent_ids
    assert research_agent["agentId"] in agent_ids
    research_refs = payload["references"][research_agent["agentId"]]
    assert any(item["kind"] == "mode_pool" and item["mode"] == "research" for item in research_refs)
    assert any(item["kind"] == "flow_binding" and item["field"] == "broad_search" for item in research_refs)
    assert any(item["kind"] == "chat_room" and item["sourceLabel"] == "研究群聊" for item in research_refs)
    chat_room_ref = next(item for item in research_refs if item["kind"] == "chat_room")
    assert chat_room_ref["route"].startswith("/chat?room=")
    groups = {item["id"]: item for item in payload["groups"]}
    assert "all" not in groups
    assert groups["active"]["section"] == "status"
    assert groups["active"]["label"] == "活跃 Agent"
    assert groups["active"]["count"] == 2
    assert archived_agent["agentId"] not in groups["active"]["agentIds"]
    assert groups["needs_review"]["section"] == "status"
    assert groups["archived"]["section"] == "status"
    assert archived_agent["agentId"] in groups["archived"]["agentIds"]
    assert groups["research"]["section"] == "mode"
    assert groups["research"]["label"] == "科研模式"
    assert groups["group_chat"]["section"] == "reference"
    assert groups["group_chat"]["label"] == "群聊引用"
    assert groups["team"]["section"] == "reference"
    assert research_agent["agentId"] in groups["research"]["agentIds"]
    assert research_agent["agentId"] in groups["group_chat"]["agentIds"]


def test_agent_config_workspace_reports_missing_model_key_and_prompt(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="待处理 Agent",
        profile_id="research_missing_key",
        primary_mode="research",
        role_key="research_deep",
        prompt_template_id="prompt-missing",
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()

    issues = payload["health"]["byAgent"][agent["agentId"]]
    assert {item["code"] for item in issues} >= {"missing_model_api_key", "missing_prompt_template", "missing_direct_session"}
    assert payload["health"]["counts"]["warning"] >= 3
    assert agent["agentId"] in {item for group in payload["groups"] if group["id"] == "needs_review" for item in group["agentIds"]}


def test_agent_instance_generates_public_person_name_and_keeps_functional_name(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    agent = agent_directory_service.create_agent_instance(display_name="科研 Agent", primary_mode="research")

    assert agent["displayName"]
    assert agent["displayName"] != "科研 Agent"
    assert agent["agentCode"]
    assert agent["metadata"]["functionalDisplayName"] == "科研 Agent"
    assert agent["metadata"]["displayNameSource"] == "generated_person_name"
    assert agent["workspaceTerritory"]["privateRoot"] == agent["workspacePath"]
    assert agent["workspaceTerritory"]["sharedRoot"] == "workspace/shared"
    assert agent["workspaceTerritory"]["writeScopes"] == ["private"]
    for subdir in ("scratch", "notes", "inbox", "outbox", "runs", "artifacts"):
        assert (tmp_path / agent["workspaceTerritory"]["subdirs"][subdir]).is_dir()
    assert (tmp_path / "workspace" / "shared").is_dir()


def test_repair_agent_directory_moves_legacy_workspace_into_private_territory(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(display_name="旧会话 Agent")
    state = agent_directory_service.load_state()
    raw = state["agents"][0]
    raw["workspacePath"] = "workspace/sessions/session-legacy"
    policy_id = raw["memoryPolicyId"]
    state["memoryPolicies"][policy_id] = {
        "policyId": policy_id,
        "privateMemoryRoot": "workspace/sessions/session-legacy/memory",
        "readSharedGroups": ["project"],
        "writeSharedGroups": ["project"],
    }
    agent_directory_service.save_state(state)

    repaired = agent_directory_service.get_agent(agent["agentId"])

    assert repaired["workspacePath"] == f"workspace/agents/{agent['agentId']}"
    assert repaired["workspaceTerritory"]["legacyWorkspacePath"] == "workspace/sessions/session-legacy"
    assert repaired["memoryPolicy"]["privateMemoryRoot"] == f"workspace/agents/{agent['agentId']}/memory"
    assert repaired["memoryPolicy"]["agentInboxMessagesPath"] == f"workspace/agents/{agent['agentId']}/events/agent_inbox_messages.jsonl"
    assert repaired["memoryPolicy"]["readSharedGroups"] == ["project"]
    assert repaired["memoryPolicy"]["writeSharedGroups"] == ["project"]
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    issues = workspace["health"]["byAgent"][agent["agentId"]]
    assert any(item["code"] == "legacy_workspace_retained" and item["severity"] == "info" for item in issues)


def test_agent_config_workspace_logs_stage_timings_and_reuses_loaded_agents(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(display_name="计时 Agent", primary_mode="research")
    captured_bindings = {}
    recorded_events = []

    def fake_get_mode_bindings_payload(*, agent_options=None):
        captured_bindings["agentOptions"] = list(agent_options or [])
        return {
            "modes": {
                "research": {
                    "mode": "research",
                    "defaultAgentId": agent["agentId"],
                    "availableAgentIds": [agent["agentId"]],
                    "pool": [agent["agentId"]],
                    "flowBindings": {},
                    "slots": {},
                    "excludedAgentIds": [],
                    "excludedSlots": [],
                }
            },
            "repairWarnings": [],
        }

    monkeypatch.setattr(agent_config_workspace_service, "get_mode_bindings_payload", fake_get_mode_bindings_payload)
    monkeypatch.setattr(
        agent_config_workspace_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()

    assert captured_bindings["agentOptions"][0]["agentId"] == agent["agentId"]
    assert captured_bindings["agentOptions"][0]["primaryMode"] == "research"
    assert payload["summary"]["agentCount"] == 1
    loaded_events = [
        event for event in recorded_events if event[0][:3] == ("agent_configuration", "workspace", "agent_config.workspace.loaded")
    ]
    assert loaded_events
    timings = loaded_events[-1][1]["fields"]["timingsMs"]
    assert {"list_agents", "mode_bindings", "runtime_statuses", "total"}.issubset(timings)
    assert timings["total"] >= timings["mode_bindings"]


def test_agent_workspace_write_boundary_uses_tool_policy_for_shared_paths(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    agent = agent_directory_service.create_agent_instance(display_name="领地 Agent")

    own = agent_directory_service.evaluate_agent_workspace_write(
        agent["agentId"],
        tmp_path / agent["workspaceTerritory"]["artifactsRoot"] / "result.txt",
        purpose="test_private",
    )
    shared = agent_directory_service.evaluate_agent_workspace_write(
        agent["agentId"],
        tmp_path / "workspace" / "shared" / "notes" / "public.md",
        purpose="test_shared",
    )
    external = agent_directory_service.evaluate_agent_workspace_write(
        agent["agentId"],
        tmp_path / "workspace" / "agents" / "other-agent" / "memory" / "memo.json",
        purpose="test_external",
    )

    assert own.allowed is True
    assert own.scope == "private"
    assert shared.allowed is False
    assert shared.reason == "shared_write_requires_policy"
    assert external.allowed is False
    assert external.reason == "outside_agent_territory"
    assert any(
        event[0][:3] == ("agent_directory", "territory", "agent_territory.write_blocked")
        and event[1]["fields"]["reason"] == "shared_write_requires_policy"
        for event in recorded_events
    )

    updated = agent_directory_service.update_agent_instance(
        agent["agentId"],
        tool_policy={
            "writeScopes": ["shared", "shared", "external"],
            "readScopes": ["private", "shared", "outside"],
        },
    )
    shared_allowed = agent_directory_service.evaluate_agent_workspace_write(
        agent["agentId"],
        tmp_path / "workspace" / "shared" / "notes" / "public.md",
        purpose="test_shared_allowed",
    )
    external_after_policy = agent_directory_service.evaluate_agent_workspace_write(
        agent["agentId"],
        tmp_path / "workspace" / "agents" / "other-agent" / "memory" / "memo.json",
        purpose="test_external_after_policy",
    )

    assert updated["toolPolicy"]["writeScopes"] == ["shared"]
    assert updated["toolPolicy"]["readScopes"] == ["private", "shared"]
    assert shared_allowed.allowed is True
    assert shared_allowed.scope == "shared"
    assert external_after_policy.allowed is False
    assert external_after_policy.reason == "outside_agent_territory"


def test_repair_agent_directory_keeps_generated_person_name_stable(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="科研 Agent", primary_mode="research")
    registry_path = agent_directory_service.registry_path()
    first_name = agent_directory_service.get_agent(agent["agentId"])["displayName"]
    first_mtime = registry_path.stat().st_mtime_ns

    agent_directory_service.repair_agent_directory()
    second_name = agent_directory_service.get_agent(agent["agentId"])["displayName"]
    second_mtime = registry_path.stat().st_mtime_ns
    agent_directory_service.repair_agent_directory()
    third_name = agent_directory_service.get_agent(agent["agentId"])["displayName"]
    third_mtime = registry_path.stat().st_mtime_ns

    assert second_name == first_name
    assert third_name == first_name
    assert third_mtime == second_mtime == first_mtime


def test_update_agent_instance_keeps_generated_person_name_when_functional_title_syncs(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="科研 Agent", primary_mode="research")
    first_name = agent["displayName"]

    updated = agent_directory_service.update_agent_instance(
        agent["agentId"],
        display_name="科研 Agent",
        primary_mode="research",
        role_key="research_broad",
        preserve_generated_display_name=True,
    )

    assert updated["displayName"] == first_name
    assert updated["metadata"]["functionalDisplayName"] == "科研 Agent"
    assert updated["metadata"]["displayNameSource"] == "generated_person_name"


def test_repair_agent_directory_migrates_legacy_functional_user_display_name(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="自进化执行 Agent",
        primary_mode="self_evolution",
        role_key="executor",
        metadata={
            "agentMode": "self_evolution",
            "selfEvolutionRole": "executor",
            "selfEvolutionRoleLabel": "自进化执行 Agent",
        },
    )
    agent_directory_service.update_agent_instance(agent["agentId"], display_name="自进化执行 Agent")

    repaired = agent_directory_service.get_agent(agent["agentId"])

    assert repaired["displayName"] != "自进化执行 Agent"
    assert repaired["metadata"]["functionalDisplayName"] == "自进化执行 Agent"
    assert repaired["metadata"]["displayNameSource"] == "generated_person_name"


def test_repair_agent_directory_keeps_real_user_display_name(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="科研 Agent", primary_mode="research")
    agent_directory_service.update_agent_instance(agent["agentId"], display_name="张三")

    repaired = agent_directory_service.get_agent(agent["agentId"])

    assert repaired["displayName"] == "张三"
    assert repaired["metadata"]["displayNameSource"] == "user"


def test_agent_config_workspace_api_route(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    session_service.create_chat_session(title="路由 Agent")

    response = client.get("/api/agents/config-workspace")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schemaVersion"] == 1
    assert payload["summary"]["agentCount"] >= 1
    assert any(item["policyId"] == "default" for item in payload["toolPolicies"])
    assert payload["memoryPolicies"]


def test_agent_config_workspace_surfaces_runtime_status_from_run_snapshots(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    running_agent = agent_directory_service.create_agent_instance(display_name="运行 Agent", profile_id="primary")
    failed_agent = agent_directory_service.create_agent_instance(display_name="失败 Agent", profile_id="primary")

    context_engine.record_agent_turn_result(
        running_agent["agentId"],
        running_agent["directSessionId"],
        {
            "runId": "turn-running",
            "status": "running",
            "summary": "still working",
            "updatedAt": "2026-05-28T10:00:00Z",
        },
    )
    context_engine.record_agent_turn_result(
        failed_agent["agentId"],
        failed_agent["directSessionId"],
        {
            "runId": "turn-failed",
            "status": "failed",
            "summary": "tool failed",
            "updatedAt": "2026-05-28T10:01:00Z",
        },
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()
    agents = {item["agentId"]: item for item in payload["agents"]}

    assert agents[running_agent["agentId"]]["runtimeStatus"]["state"] == "running"
    assert agents[running_agent["agentId"]]["runtimeStatus"]["runId"]
    assert agents[failed_agent["agentId"]]["runtimeStatus"]["state"] == "failed"
    assert agents[failed_agent["agentId"]]["runtimeStatus"]["summary"] == "tool failed"
    assert payload["summary"]["runningAgentCount"] == 1
    assert payload["summary"]["blockedAgentCount"] == 1


def test_agent_create_api_adds_direct_agent_with_safe_defaults(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)

    response = client.post(
        "/api/agents",
        json={
            "displayName": "新增研究 Agent",
            "profileId": "primary",
            "primaryMode": "research",
            "roleKey": "research_broad",
            "promptTemplateId": "prompt-research-broad",
        },
    )

    assert response.status_code == 201, response.text
    agent = response.json()
    assert agent["agentId"]
    assert agent["displayName"]
    assert agent["displayName"] != "新增研究 Agent"
    assert agent["metadata"]["functionalDisplayName"] == "新增研究 Agent"
    assert agent["primaryMode"] == "research"
    assert agent["roleKey"] == "research_broad"
    assert agent["promptTemplateId"] == "prompt-research-broad"
    assert agent["directSessionId"]
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    assert agent["agentId"] in {item["agentId"] for item in workspace["agents"]}


def test_agent_delete_api_archives_and_cleans_bindings_and_rooms(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    agent_mode_binding_service.update_mode_binding(
        "chat",
        default_agent_id=alpha["agentId"],
        available_agent_ids=[alpha["agentId"], beta["agentId"]],
    )
    agent_mode_binding_service.update_mode_binding(
        "research",
        pool=[alpha["agentId"], beta["agentId"]],
        flow_bindings={"broad_search": alpha["agentId"]},
    )
    room = chat_room_service.create_chat_room(
        title="待清理群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
    )

    response = client.delete(f"/api/agents/{alpha['agentId']}")

    assert response.status_code == 200, response.text
    archived = response.json()
    assert archived["status"] == "archived"
    assert archived["archiveSummary"]["dataRetention"] == "archived_only"
    assert archived["archiveSummary"]["removedFromRoomIds"] == [room["roomId"]]
    assert alpha["agentId"] not in {item["agentId"] for item in agent_directory_service.list_agents(include_archived=False)}
    assert agent_directory_service.get_agent(alpha["agentId"], include_archived=True)["status"] == "archived"
    bindings = agent_mode_binding_service.get_mode_bindings_payload()["modes"]
    assert bindings["chat"]["defaultAgentId"] == beta["agentId"]
    assert alpha["agentId"] not in bindings["chat"]["availableAgentIds"]
    assert alpha["agentId"] not in bindings["research"]["pool"]
    assert alpha["agentId"] not in bindings["research"]["flowBindings"].values()
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [participant["agentId"] for participant in room_detail["participants"]] == [beta["agentId"]]
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    groups = {group["id"]: group for group in workspace["groups"]}
    assert alpha["agentId"] in groups["archived"]["agentIds"]
    assert alpha["agentId"] not in groups["active"]["agentIds"]
    assert alpha["agentId"] not in groups["chat"]["agentIds"]
    assert alpha["agentId"] not in groups["research"]["agentIds"]
    assert alpha["agentId"] not in groups["group_chat"]["agentIds"]


def test_agent_delete_api_rejects_only_group_member_without_partial_archive(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = session_service.create_chat_session(title="Solo Agent")
    chat_room_service.create_chat_room(
        title="单成员历史群聊",
        participant_session_ids=[agent["id"]],
    )

    response = client.delete(f"/api/agents/{agent['agentId']}")

    assert response.status_code == 422
    assert "唯一成员" in response.json()["detail"] or "only member" in response.json()["detail"]
    assert agent_directory_service.get_agent(agent["agentId"])["status"] == "active"


def test_agent_delete_api_rejects_protected_agent_without_reference_cleanup(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    protected = session_service.create_chat_session(title="核心 Agent")
    peer = session_service.create_chat_session(title="普通 Agent")
    agent_directory_service.update_agent_instance(protected["agentId"], metadata={"protected": True})
    agent_mode_binding_service.update_mode_binding(
        "chat",
        default_agent_id=protected["agentId"],
        available_agent_ids=[protected["agentId"], peer["agentId"]],
    )
    room = chat_room_service.create_chat_room(
        title="保护群聊",
        participant_agent_ids=[protected["agentId"], peer["agentId"]],
    )

    response = client.delete(f"/api/agents/{protected['agentId']}")

    assert response.status_code == 422
    assert "Protected core Agent" in response.json()["detail"]
    assert agent_directory_service.get_agent(protected["agentId"])["status"] == "active"
    chat_binding = _raw_mode_binding("chat")
    assert chat_binding["defaultAgentId"] == protected["agentId"]
    assert protected["agentId"] in chat_binding["availableAgentIds"]
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [participant["agentId"] for participant in room_detail["participants"]] == [protected["agentId"], peer["agentId"]]


def test_agent_purge_api_deletes_archived_agent_workspace_and_registry_record(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    agent = agent_directory_service.update_agent_instance(
        alpha["agentId"],
        tool_policy={"allowedTools": ["read_file_tool"]},
        memory_policy={"readSharedGroups": ["project"]},
    )
    workspace_path = tmp_path / agent["workspacePath"]
    marker = workspace_path / "events" / "agent_inbox_messages.jsonl"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('{"messageId":"m1"}\n', encoding="utf-8")
    agent_mode_binding_service.update_mode_binding(
        "chat",
        default_agent_id=alpha["agentId"],
        available_agent_ids=[alpha["agentId"], beta["agentId"]],
    )
    room = chat_room_service.create_chat_room(
        title="待 purge 群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
    )
    agent_directory_service.archive_agent_instance(alpha["agentId"])

    response = client.delete(f"/api/agents/{alpha['agentId']}/purge")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["agentId"] == alpha["agentId"]
    assert payload["status"] == "purged"
    assert payload["deleted"] is True
    assert payload["workspaceDeleted"] is True
    assert agent["workspacePath"] in payload["deletedPaths"]
    assert payload["removedToolPolicy"] is True
    assert payload["removedMemoryPolicy"] is True
    assert payload["purgeSummary"]["dataRetention"] == "purged"
    assert payload["purgeSummary"]["removedFromRoomIds"] == [room["roomId"]]
    assert not workspace_path.exists()
    assert agent_directory_service.get_agent(alpha["agentId"], include_archived=True) is None
    state = agent_directory_service.load_state()
    assert agent["toolPolicyId"] not in state["toolPolicies"]
    assert agent["memoryPolicyId"] not in state["memoryPolicies"]
    bindings = agent_mode_binding_service.get_mode_bindings_payload()["modes"]
    assert bindings["chat"]["defaultAgentId"] == beta["agentId"]
    assert alpha["agentId"] not in bindings["chat"]["availableAgentIds"]
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [participant["agentId"] for participant in room_detail["participants"]] == [beta["agentId"]]


def test_agent_purge_api_rejects_active_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = session_service.create_chat_session(title="Active Agent")

    response = client.delete(f"/api/agents/{agent['agentId']}/purge")

    assert response.status_code == 422
    assert "archived" in response.json()["detail"]
    assert agent_directory_service.get_agent(agent["agentId"], include_archived=True)["status"] == "active"


def test_agent_purge_api_rejects_protected_archived_agent_without_reference_cleanup(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    protected = session_service.create_chat_session(title="Protected Archived")
    peer = session_service.create_chat_session(title="Peer Agent")
    agent_mode_binding_service.update_mode_binding(
        "chat",
        default_agent_id=protected["agentId"],
        available_agent_ids=[protected["agentId"], peer["agentId"]],
    )
    room = chat_room_service.create_chat_room(
        title="保护归档群聊",
        participant_agent_ids=[protected["agentId"], peer["agentId"]],
    )
    agent_directory_service.archive_agent_instance(protected["agentId"])
    agent_directory_service.update_agent_instance(
        protected["agentId"],
        metadata={"protected": True},
    )

    response = client.delete(f"/api/agents/{protected['agentId']}/purge")

    assert response.status_code == 422
    assert "Protected core Agent" in response.json()["detail"]
    assert agent_directory_service.get_agent(protected["agentId"], include_archived=True)["status"] == "archived"
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [participant["agentId"] for participant in room_detail["participants"]] == [protected["agentId"], peer["agentId"]]


def test_agent_purge_api_allows_archived_agent_that_was_only_room_member(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = session_service.create_chat_session(title="Solo Archived Agent")
    room = chat_room_service.create_chat_room(
        title="单成员历史群聊",
        participant_session_ids=[agent["id"]],
    )
    agent_directory_service.archive_agent_instance(agent["agentId"])

    response = client.delete(f"/api/agents/{agent['agentId']}/purge")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["purgeSummary"]["removedFromRoomIds"] == [room["roomId"]]
    assert agent_directory_service.get_agent(agent["agentId"], include_archived=True) is None
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert room_detail["participants"] == []


def test_agent_purge_api_reports_workspace_delete_failure_without_server_error(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = session_service.create_chat_session(title="Locked Workspace Agent")
    agent_directory_service.archive_agent_instance(agent["agentId"])
    workspace_path = tmp_path / agent["workspacePath"]
    workspace_path.mkdir(parents=True, exist_ok=True)

    def _fail_rmtree(path):
        raise PermissionError("locked")

    monkeypatch.setattr(agent_directory_service.shutil, "rmtree", _fail_rmtree)

    response = client.delete(f"/api/agents/{agent['agentId']}/purge")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["deleted"] is True
    assert payload["workspaceDeleted"] is False
    assert payload["deletedPaths"] == []
    assert payload["skippedPaths"]
    assert "PermissionError" in payload["skippedPaths"][0]
    assert agent_directory_service.get_agent(agent["agentId"], include_archived=True) is None
    assert workspace_path.exists()


def test_agent_config_workspace_agent_patch_updates_card_fields(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="旧 Agent",
        profile_id="primary",
        prompt_template_id="prompt-chat-default",
    )
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    memory_policy_id = workspace["memoryPolicies"][0]["policyId"]

    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "displayName": "新 Agent",
            "profileId": "research_missing_key",
            "promptTemplateId": "prompt-research-broad",
            "toolPolicyId": "default",
            "memoryPolicyId": memory_policy_id,
            "status": "active",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["displayName"] == "新 Agent"
    assert payload["profileId"] == "research_missing_key"
    assert payload["templateId"] == "research_missing_key"
    assert payload["promptTemplateId"] == "prompt-research-broad"
    assert payload["toolPolicyId"] == "default"
    assert payload["memoryPolicyId"] == memory_policy_id


def test_agent_patch_rejects_unknown_policy_ids_and_protected_archive(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(display_name="核心 Agent", metadata={"protected": True})

    missing_policy = client.patch(f"/api/agents/{agent['agentId']}", json={"toolPolicyId": "missing-policy"})
    archive = client.patch(f"/api/agents/{agent['agentId']}", json={"status": "archived"})

    assert missing_policy.status_code == 422
    assert "Unknown ToolPolicy" in missing_policy.json()["detail"]
    assert archive.status_code == 422
    assert "Protected core Agent" in archive.json()["detail"]


def test_agent_patch_tool_policy_creates_agent_private_policy_and_logs(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    agent = agent_directory_service.create_agent_instance(display_name="工具 Agent")

    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "toolPolicy": {
                "allowedTools": ["image2_generate_tool"],
                "blockedTools": ["shell_command"],
                "writeScopes": ["shared", "external", "shared"],
                "readScopes": ["shared", "private", "external"],
            }
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["toolPolicyId"] == f"tool-{agent['agentId']}"
    assert payload["toolPolicy"]["allowedTools"] == ["image2_generate_tool"]
    assert payload["toolPolicy"]["blockedTools"] == ["shell_command"]
    assert payload["toolPolicy"]["writeScopes"] == ["shared"]
    assert payload["toolPolicy"]["readScopes"] == ["shared", "private"]
    assert any(
        event[0][:3] == ("agent_directory", "tool_policy", "agent.tool_policy.updated")
        and event[1]["fields"]["allowedToolCount"] == 1
        and event[1]["fields"]["blockedToolCount"] == 1
        and event[1]["fields"]["sharedWriteEnabled"] is True
        for event in recorded_events
    )


def test_agent_patch_memory_policy_updates_private_policy_and_logs(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    agent = agent_directory_service.create_agent_instance(display_name="记忆 Agent")

    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={"memoryPolicy": {"readSharedGroups": ["project", "research"], "writeSharedGroups": ["project"]}},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["memoryPolicyId"] == f"memory-{agent['agentId']}"
    assert payload["memoryPolicy"]["readSharedGroups"] == ["project", "research"]
    assert payload["memoryPolicy"]["writeSharedGroups"] == ["project"]
    assert payload["memoryPolicy"]["privateMemoryRoot"].endswith("/memory")
    assert any(
        event[0][:3] == ("agent_directory", "memory_policy", "agent.memory_policy.updated")
        and event[1]["fields"]["readSharedGroupCount"] == 2
        and event[1]["fields"]["writeSharedGroupCount"] == 1
        for event in recorded_events
    )


def test_agent_patch_runtime_policies_updates_metadata_and_logs(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    agent = agent_directory_service.create_agent_instance(display_name="运行策略 Agent")

    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "delegationPolicy": {
                "allowSubagents": True,
                "maxConcurrent": 99,
                "maxDepth": 9,
                "allowWakeMessages": False,
                "allowedContextModes": ["fork", "invalid", "isolated"],
            },
            "supervisionPolicy": {
                "supervisionEnabled": True,
                "requiresReview": True,
                "reviewMode": "required",
                "evidenceLevel": "strict",
            },
        },
    )

    assert response.status_code == 200, response.text
    metadata = response.json()["metadata"]
    assert metadata["delegationPolicy"] == {
        "allowSubagents": True,
        "maxConcurrent": 8,
        "maxDepth": 4,
        "allowWakeMessages": False,
        "allowedContextModes": ["fork", "isolated"],
    }
    assert metadata["supervisionPolicy"] == {
        "supervisionEnabled": True,
        "requiresReview": True,
        "reviewMode": "required",
        "evidenceLevel": "strict",
    }
    assert any(
        event[0][:3] == ("agent_directory", "delegation_policy", "agent.delegation_policy.updated")
        and event[1]["fields"]["allowSubagents"] is True
        and event[1]["fields"]["maxConcurrent"] == 8
        and event[1]["fields"]["maxDepth"] == 4
        and event[1]["fields"]["allowedContextModeCount"] == 2
        for event in recorded_events
    )
    assert any(
        event[0][:3] == ("agent_directory", "supervision_policy", "agent.supervision_policy.updated")
        and event[1]["fields"]["supervisionEnabled"] is True
        and event[1]["fields"]["requiresReview"] is True
        and event[1]["fields"]["reviewMode"] == "required"
        and event[1]["fields"]["evidenceLevel"] == "strict"
        for event in recorded_events
    )


def test_agent_mode_membership_api_updates_selected_agent_bindings(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="模式 Agent",
        profile_id="primary",
        primary_mode="research",
        role_key="research_broad",
    )

    response = client.patch(
        f"/api/agents/{agent['agentId']}/mode-membership",
        json={"chatDefault": True, "chatAvailable": True, "researchPool": True, "supervisedSlot": "reviewer"},
    )

    assert response.status_code == 200, response.text
    modes = response.json()["modes"]
    assert modes["chat"]["defaultAgentId"] == agent["agentId"]
    assert agent["agentId"] in modes["chat"]["availableAgentIds"]
    assert agent["agentId"] in modes["research"]["pool"]
    assert modes["supervised_evolution"]["slots"]["reviewer"] == agent["agentId"]


def test_agent_chat_room_membership_api_updates_selected_agent_rooms(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    gamma = session_service.create_chat_session(title="Gamma Agent")
    first_room = chat_room_service.create_chat_room(
        title="第一群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
    )
    second_room = chat_room_service.create_chat_room(
        title="第二群聊",
        participant_agent_ids=[beta["agentId"], gamma["agentId"]],
    )

    response = client.patch(
        f"/api/agents/{alpha['agentId']}/chat-rooms",
        json={"roomIds": [second_room["roomId"]]},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["roomIds"] == [second_room["roomId"]]
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    rooms = {room["roomId"]: room for room in workspace["chatRooms"]}
    assert alpha["agentId"] not in rooms[first_room["roomId"]]["agentIds"]
    assert alpha["agentId"] in rooms[second_room["roomId"]]["agentIds"]
    assert beta["agentId"] in rooms[first_room["roomId"]]["agentIds"]


def test_agent_config_workspace_surfaces_stale_room_participant(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    room_path = tmp_path / "workspace" / "chat_rooms" / "chat_rooms.json"
    room_path.parent.mkdir(parents=True, exist_ok=True)
    room_path.write_text(
        json.dumps(
            {
                "version": 1,
                "rooms": [
                    {
                        "roomId": "room-stale",
                        "title": "坏群聊",
                        "mode": "round_robin",
                        "config": {},
                        "participants": [
                            {
                                "participantId": "ghost",
                                "kind": "session_agent",
                                "agentId": "agent-missing",
                                "sessionId": "missing-session",
                                "title": "Ghost",
                                "enabled": True,
                                "status": "",
                            }
                        ],
                        "rounds": [],
                        "status": "ready",
                        "activeRoundId": "",
                        "createdAt": "2026-05-28T00:00:00Z",
                        "updatedAt": "2026-05-28T00:00:00Z",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()

    assert any(item["code"] == "stale_chat_room_participant" for item in payload["health"]["issues"])
