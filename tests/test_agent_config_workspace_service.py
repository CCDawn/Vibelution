import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.orchestration import context_engine
from core.web.routes import agents as agents_route
from core.web.services import (
    agent_config_workspace_service,
    agent_directory_service,
    agent_tool_governance_service,
    agent_mode_binding_service,
    chat_room_service,
    config_service,
    prompt_template_service,
    self_evolution_control_service,
    session_service,
    supervised_agent_service,
    team_service,
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
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_agent_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(self_evolution_control_service, "PROJECT_ROOT", tmp_path)


def _fake_config_workspace():
    return {
        "modelOptions": [
            {
                "model_id": "model-primary",
                "source": "model",
                "provider": {"id": "openai"},
                "provider_kind": "openai",
                "model": "gpt-test",
                "label": "GPT Test",
                "details": {},
                "api_key_env": "OPENAI_API_KEY",
                "api_key_configured": True,
                "api_key_state": "configured",
            },
            {
                "model_id": "model-research",
                "source": "model",
                "provider": {"id": "relay"},
                "provider_kind": "relay",
                "model": "research-test",
                "label": "Research Test",
                "details": {},
                "api_key_env": "RELAY_API_KEY",
                "api_key_configured": False,
                "api_key_state": "missing",
            },
        ],
    }


def _seed_agent_avatars(root):
    avatar_dir = root / "workspace" / "avatars"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    for filename in agent_directory_service.AGENT_AVATAR_FILENAMES:
        (avatar_dir / filename).write_bytes(b"\x89PNG\r\n\x1a\navatar")


def test_agent_registry_repair_migrates_legacy_profile_fields_to_llm_bindings(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    fake_llm = SimpleNamespace(
        get_profile=lambda profile_id=None, role="primary": SimpleNamespace(profile_id=profile_id or "primary"),
        get_model_library_entry_for_profile=lambda profile: ("model-primary", {}),
        model_library={"model-primary": {"model": "gpt-test"}},
    )
    monkeypatch.setattr("config.settings.get_config", lambda: SimpleNamespace(llm=fake_llm))
    registry_path = tmp_path / "workspace" / "agents" / "agents.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "version": 1,
                "agents": [
                    {
                        "agentId": "agent-legacy",
                        "agentCode": "A014",
                        "displayName": "旧 Agent",
                        "kind": "persistent",
                        "primaryMode": "chat",
                        "roleKey": "",
                        "profileId": "primary",
                        "templateId": "primary",
                        "promptTemplateId": "prompt-chat-default",
                        "directSessionId": "session-legacy",
                        "workspacePath": "workspace/agents/agent-legacy",
                        "toolPolicyId": "default",
                        "memoryPolicyId": "memory-agent-legacy",
                        "createdBy": "legacy",
                        "status": "active",
                        "metadata": {},
                        "createdAt": "2026-06-04T00:00:00+00:00",
                        "updatedAt": "2026-06-04T00:00:00+00:00",
                    }
                ],
                "toolPolicies": {"default": agent_directory_service.default_tool_policy("default")},
                "memoryPolicies": {},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()

    agent = next(item for item in payload["agents"] if item["agentId"] == "agent-legacy")
    assert agent["llmBindings"]["dialogue"]["modelId"] == "model-primary"
    assert "profileId" not in agent
    assert "templateId" not in agent
    assert all(
        item["code"] != "missing_llm_slot_dialogue"
        for item in payload["health"]["byAgent"].get("agent-legacy", [])
    )
    stored = json.loads(registry_path.read_text(encoding="utf-8"))
    stored_agent = stored["agents"][0]
    assert stored_agent["llmBindings"]["dialogue"]["modelId"] == "model-primary"
    assert "profileId" not in stored_agent
    assert "templateId" not in stored_agent
    assert stored_agent["metadata"]["llmBindingMigration"]["legacyModelSourceId"] == "primary"


def test_agent_config_workspace_lists_agents_once_and_derives_references(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    chat_agent = session_service.create_chat_session(title="会话 Agent")
    research_session = session_service.create_chat_session(title="科研 Agent")
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
    agents = {item["agentId"]: item for item in payload["agents"]}
    assert agents[chat_agent["agentId"]]["agentBoundary"]["type"] == "work_session"
    assert agents[chat_agent["agentId"]]["agentBoundary"]["directSessionRole"] == "primary_entry"
    assert agents[research_agent["agentId"]]["agentBoundary"]["type"] == "team_role"
    assert agents[research_agent["agentId"]]["agentBoundary"]["directSessionRole"] == "recovery_channel"
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
    assert groups["active"]["count"] == 3
    assert agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID in groups["active"]["agentIds"]
    assert archived_agent["agentId"] not in groups["active"]["agentIds"]
    assert groups["work_session"]["section"] == "boundary"
    assert chat_agent["agentId"] in groups["work_session"]["agentIds"]
    assert research_agent["agentId"] not in groups["work_session"]["agentIds"]
    assert groups["team_role"]["section"] == "boundary"
    assert research_agent["agentId"] in groups["team_role"]["agentIds"]
    assert groups["service_role"]["section"] == "boundary"
    assert agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID in groups["service_role"]["agentIds"]
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


def test_agent_directory_reuses_repaired_snapshot_for_repeated_reads(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent_directory_service.create_agent_instance(display_name="缓存 Agent")

    repair_calls = 0
    real_repair = agent_directory_service.repair_agent_directory

    def tracked_repair():
        nonlocal repair_calls
        repair_calls += 1
        return real_repair()

    monkeypatch.setattr(agent_directory_service, "repair_agent_directory", tracked_repair)

    first = agent_directory_service.list_agents(include_archived=True)
    second = agent_directory_service.list_agents(include_archived=True)
    looked_up = agent_directory_service.get_agent(first[0]["agentId"])

    assert [item["agentId"] for item in first] == [item["agentId"] for item in second]
    assert looked_up and looked_up["agentId"] == first[0]["agentId"]
    assert repair_calls == 1


def test_agent_directory_repaired_snapshot_cache_invalidates_after_save(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="缓存 Agent",
        metadata={"cacheProbe": "before"},
    )

    assert agent_directory_service.get_agent(agent["agentId"])["metadata"]["cacheProbe"] == "before"
    assert agent_directory_service.get_agent(agent["agentId"])["metadata"]["cacheProbe"] == "before"

    agent_directory_service.update_agent_instance(agent["agentId"], metadata={"cacheProbe": "after"})

    assert agent_directory_service.get_agent(agent["agentId"])["metadata"]["cacheProbe"] == "after"


def test_work_session_boundary_skips_persona_task_and_team_onboarding_requirements(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    session = session_service.create_chat_session(title="开发会话")
    agent_id = session["agentId"]
    agent = agent_directory_service.get_agent(agent_id)
    metadata = dict(agent["metadata"])
    metadata.pop("personaProfile", None)
    metadata.pop("taskProfile", None)
    metadata["onboardingMissing"] = ["personaProfile", "taskProfile"]
    agent_directory_service.update_agent_instance(agent_id, metadata=metadata)

    payload = agent_config_workspace_service.get_agent_config_workspace()
    workspace_agent = next(item for item in payload["agents"] if item["agentId"] == agent_id)
    issue_codes = {item["code"] for item in workspace_agent["health"]}

    assert workspace_agent["agentBoundary"]["type"] == "work_session"
    assert workspace_agent["agentBoundary"]["requiresPersonaProfile"] == "false"
    assert workspace_agent["agentBoundary"]["requiresTaskProfile"] == "false"
    assert "agent_onboarding_incomplete" not in issue_codes


def test_agent_directory_assigns_default_avatar_from_workspace_avatars(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_agent_avatars(tmp_path)

    chat_agent = agent_directory_service.create_agent_instance(display_name="会话 Agent")
    deep_agent = agent_directory_service.create_agent_instance(
        display_name="深搜 Agent",
        primary_mode="research",
        role_key="research_deep",
        prompt_template_id="prompt-research-deep",
    )
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    agents = {item["agentId"]: item for item in workspace["agents"]}

    assert chat_agent["avatarImagePath"].startswith("workspace/avatars/")
    assert chat_agent["avatarImageUrl"].startswith("/api/agents/avatar-image/")
    assert deep_agent["avatarImagePath"] == "workspace/avatars/06-deep-investigator.png"
    assert deep_agent["avatarImageUrl"] == "/api/agents/avatar-image/06-deep-investigator.png"
    assert agents[chat_agent["agentId"]]["avatarImageUrl"] == chat_agent["avatarImageUrl"]
    assert agents[deep_agent["agentId"]]["metadata"]["avatarImageSource"] == "default"

    response = client.get("/api/agents/avatar-image/06-deep-investigator.png")
    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")


def test_agent_avatar_can_be_selected_uploaded_and_reset(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_agent_avatars(tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="头像 Agent", primary_mode="research", role_key="research_deep")

    options = client.get("/api/agents/avatar-options")
    assert options.status_code == 200
    assert options.json()["count"] >= 2

    update_response = client.patch(
        f"/api/agents/{agent['agentId']}/avatar",
        json={"avatarImagePath": "workspace/avatars/01-session-agent.png"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["avatarImagePath"] == "workspace/avatars/01-session-agent.png"
    assert update_response.json()["metadata"]["avatarImageSource"] == "custom"

    upload_response = client.post(
        f"/api/agents/{agent['agentId']}/avatar-image",
        json={
            "filename": "custom.png",
            "contentType": "image/png",
            "dataBase64": "iVBORw0KGgphdmF0YXI=",
        },
    )
    assert upload_response.status_code == 200
    uploaded = upload_response.json()
    assert uploaded["path"].startswith("workspace/avatars/agent-avatar-")
    assert uploaded["agent"]["metadata"]["avatarImageSource"] == "custom"
    assert (tmp_path / uploaded["path"]).exists()

    reset_response = client.patch(
        f"/api/agents/{agent['agentId']}/avatar",
        json={"resetToDefault": True},
    )
    assert reset_response.status_code == 200
    assert reset_response.json()["avatarImagePath"] == "workspace/avatars/06-deep-investigator.png"
    assert reset_response.json()["metadata"]["avatarImageSource"] == "default"


def test_agent_config_workspace_reports_missing_model_key_and_prompt(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="待处理 Agent",
        llm_bindings={"dialogue": {"modelId": "model-research"}},
        primary_mode="research",
        role_key="research_deep",
        prompt_template_id="prompt-missing",
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()

    issues = payload["health"]["byAgent"][agent["agentId"]]
    assert {item["code"] for item in issues} >= {"missing_llm_slot_api_key_dialogue", "missing_prompt_template", "missing_direct_session"}
    assert payload["health"]["counts"]["warning"] >= 3
    assert agent["agentId"] in {item for group in payload["groups"] if group["id"] == "needs_review" for item in group["agentIds"]}
    assert [item["model_id"] for item in payload["modelOptions"]] == ["model-primary", "model-research"]
    assert [item["modelId"] for item in payload["agentModelChoices"]] == ["model-primary", "model-research"]


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
    raw = next(item for item in state["agents"] if item["agentId"] == agent["agentId"])
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
    assert repaired["memoryPolicy"]["readKnowledgeBaseIds"] == []
    assert repaired["memoryPolicy"]["proposeKnowledgeBaseIds"] == []
    assert repaired["memoryPolicy"]["reviewKnowledgeBaseIds"] == []
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    issues = workspace["health"]["byAgent"][agent["agentId"]]
    assert any(item["code"] == "legacy_workspace_retained" and item["severity"] == "info" for item in issues)


def test_agent_config_workspace_logs_stage_timings_and_reuses_loaded_agents(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="计时 Agent",
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
        metadata={
            "personaProfile": {"personality": "稳定记录加载计时。"},
            "taskProfile": {"mission": "验证 Agent 配置工作区日志。", "taskTypes": ["diagnostics"]},
        },
    )
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

    captured_agents = {item["agentId"]: item for item in captured_bindings["agentOptions"]}
    assert captured_agents[agent["agentId"]]["primaryMode"] == "research"
    assert agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID in captured_agents
    assert payload["summary"]["agentCount"] == 2
    loaded_events = [
        event for event in recorded_events if event[0][:3] == ("agent_configuration", "workspace", "agent_config.workspace.loaded")
    ]
    assert loaded_events
    timings = loaded_events[-1][1]["fields"]["timingsMs"]
    assert {"list_agents", "mode_bindings", "runtime_histories", "runtime_statuses", "total"}.issubset(timings)
    assert timings["total"] >= timings["mode_bindings"]
    assert loaded_events[-1][1]["fields"]["loadModes"] == {
        "chatRooms": "compact",
        "teams": "graph_references",
        "runtimeStatuses": "batched",
    }


def test_agent_config_workspace_records_model_reference_resolution(monkeypatch):
    recorded_events = []
    monkeypatch.setattr(
        agent_config_workspace_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    agent_config_workspace_service._record_model_reference_resolution([])

    assert recorded_events
    args, kwargs = recorded_events[-1]
    assert args[:3] == ("agent_config", "model_binding", "agent_config.model_references.resolved")
    assert kwargs["outcome"] == "resolved"
    assert kwargs["fields"]["unresolvedCount"] == 0


def test_agent_directory_list_agents_logs_slow_hydration_breakdown(monkeypatch):
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    agent_directory_service._record_agent_list_loaded(
        include_archived=True,
        detail="full",
        raw_agent_count=49,
        returned_agent_count=49,
        timings={
            "lock_wait": 12.0,
            "repair": 42.0,
            "filter": 1.0,
            "hydrate": 3600.0,
            "to_api": 84.0,
            "sort": 0.5,
            "total": 3740.0,
        },
        hydration_timings={
            "tool_policies": 1.0,
            "memory_policies": 1.5,
            "tool_governance_requests": 2100.0,
            "group_context_events": 900.0,
            "agent_inbox_messages": 520.0,
        },
    )

    assert recorded_events
    args, kwargs = recorded_events[-1]
    assert args[:3] == ("agent_directory", "list_agents", "agent_directory.list_agents.slow")
    assert kwargs["level"] == "warning"
    fields = kwargs["fields"]
    assert fields["includeArchived"] is True
    assert fields["detail"] == "full"
    assert fields["rawAgentCount"] == 49
    assert fields["returnedAgentCount"] == 49
    assert fields["timingsMs"]["hydrate"] == 3600.0
    assert fields["hydrationTimingsMs"]["tool_governance_requests"] == 2100.0
    assert fields["slowestStage"] == "hydrate"
    assert fields["slowestHydrationStage"] == "tool_governance_requests"


def test_agent_directory_summary_list_skips_heavy_hydration(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    created = agent_directory_service.create_agent_instance(display_name="Summary Agent", primary_mode="chat")
    hydration_calls = 0

    def fail_hydration(*args, **kwargs):
        nonlocal hydration_calls
        hydration_calls += 1
        raise AssertionError("summary agent list should not hydrate policies or activity")

    monkeypatch.setattr(agent_directory_service, "_build_agent_api_hydration_context", fail_hydration)

    agents = agent_directory_service.list_agents(detail="summary")

    assert hydration_calls == 0
    agent = next(item for item in agents if item["agentId"] == created["agentId"])
    assert agent["displayName"] == created["displayName"]
    assert "toolPolicy" not in agent
    assert "memoryPolicy" not in agent
    assert "toolGovernanceRequests" not in agent
    assert "groupContextEvents" not in agent
    assert "agentInboxMessages" not in agent
    assert "agentInboxPendingCount" not in agent


def test_agents_api_summary_detail_returns_light_payload(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    created = agent_directory_service.create_agent_instance(display_name="Summary Route Agent", primary_mode="chat")

    response = client.get("/api/agents", params={"detail": "summary"})

    assert response.status_code == 200, response.json()
    payload = response.json()
    agent = next(item for item in payload if item["agentId"] == created["agentId"])
    assert agent["displayName"] == created["displayName"]
    assert "toolPolicy" not in agent
    assert "memoryPolicy" not in agent
    assert "toolGovernanceRequests" not in agent
    assert "groupContextEvents" not in agent
    assert "agentInboxMessages" not in agent


def test_agent_config_workspace_batches_agent_api_hydration(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", primary_mode="chat")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", primary_mode="research")
    agent_directory_service.write_agent_inbox_message(
        alpha["agentId"],
        content="请处理待办。",
        created_by="test",
    )
    agent_directory_service.write_group_context_event(
        beta["agentId"],
        {
            "sourceRoomId": "room-test",
            "sourceRoundId": "round-1",
            "topic": "配置页性能",
            "summary": "确认批量 hydration。",
            "ownMessage": "Beta ready",
            "peerHighlights": [],
        },
    )
    agent_tool_governance_service.submit_tool_governance_request(
        alpha["agentId"],
        grant_tools=["grep_search_tool"],
        reason="low-risk check",
        apply_mode="review",
    )
    full_read_paths = []
    original_read_jsonl = agent_directory_service._read_jsonl

    def counting_read_jsonl(path):
        full_read_paths.append(str(path).replace("\\", "/"))
        return original_read_jsonl(path)

    monkeypatch.setattr(agent_directory_service, "_read_jsonl", counting_read_jsonl)

    payload = agent_config_workspace_service.get_agent_config_workspace()

    agents = {item["agentId"]: item for item in payload["agents"]}
    assert agents[alpha["agentId"]]["agentInboxPendingCount"] == 1
    assert len(agents[alpha["agentId"]]["agentInboxMessages"]) == 1
    assert len(agents[alpha["agentId"]]["toolGovernanceRequests"]) == 1
    assert len(agents[beta["agentId"]]["groupContextEvents"]) == 1
    assert agents[alpha["agentId"]]["toolPolicy"]["policyId"]
    assert agents[alpha["agentId"]]["memoryPolicy"]["privateMemoryRoot"].endswith(f"{alpha['agentId']}/memory")
    assert not any("agent_inbox_messages.jsonl" in path for path in full_read_paths)
    assert not any("group_context_events.jsonl" in path for path in full_read_paths)
    assert not any("tool_governance_requests.jsonl" in path for path in full_read_paths)


def test_agent_config_workspace_recent_jsonl_preserves_older_pending_messages(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(display_name="Pending Tail Agent", primary_mode="chat")
    path = agent_directory_service._agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "eventId": "older-pending",
            "messageId": "older-pending",
            "status": "pending",
            "content": "仍需处理",
            "createdAt": "2026-06-01T00:00:00+00:00",
        }
    ]
    rows.extend(
        {
            "eventId": f"consumed-{index}",
            "messageId": f"consumed-{index}",
            "status": "consumed",
            "content": f"已处理 {index}",
            "createdAt": f"2026-06-01T00:00:{index:02d}+00:00",
        }
        for index in range(24)
    )
    path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in rows) + "\n", encoding="utf-8")

    payload = agent_config_workspace_service.get_agent_config_workspace()

    workspace_agent = next(item for item in payload["agents"] if item["agentId"] == agent["agentId"])
    assert workspace_agent["agentInboxPendingCount"] == 1
    assert [item["messageId"] for item in workspace_agent["agentInboxMessages"]] == ["older-pending"]
    assert agent_directory_service.list_agent_inbox_messages_for_agent(agent["agentId"], status="pending", limit=8)[0]["messageId"] == "older-pending"


def test_agent_config_workspace_reuses_loaded_agents_for_policy_options(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(display_name="Policy Agent")
    monkeypatch.setattr(
        agent_config_workspace_service,
        "list_agent_policy_options",
        lambda: (_ for _ in ()).throw(AssertionError("policy options should be derived from loaded agents")),
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()

    assert any(item["policyId"] == agent["toolPolicyId"] for item in payload["toolPolicies"])
    assert any(item["policyId"] == agent["memoryPolicyId"] for item in payload["memoryPolicies"])


def test_agent_config_workspace_uses_compact_room_and_team_indexes(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    room = chat_room_service.create_chat_room(
        title="配置中心群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
    )
    team_service.create_team(
        name="配置中心团队",
        members=[{"agentId": alpha["agentId"], "role": "lead"}],
    )

    def fail_session_scan():
        raise AssertionError("config workspace should not scan sessions through compact room/team indexes")

    monkeypatch.setattr(session_service, "list_sessions", fail_session_scan)

    payload = agent_config_workspace_service.get_agent_config_workspace()

    assert payload["summary"]["chatRoomCount"] == 2
    assert payload["summary"]["teamCount"] == 1
    assert any(item["roomId"] == room["roomId"] for item in payload["chatRooms"])
    alpha_refs = payload["references"][alpha["agentId"]]
    assert any(item["kind"] == "chat_room" and item["sourceLabel"] == "配置中心群聊" for item in alpha_refs)
    assert any(item["kind"] == "team" and item["sourceLabel"] == "配置中心团队" for item in alpha_refs)


def test_agent_config_workspace_batches_runtime_history_reads(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    calls = []

    def fake_list_agent_runs_for_agents(agent_ids, *, limit=20):
        calls.append((tuple(agent_ids), limit))
        return {
            "agentIds": list(agent_ids),
            "limit": limit,
            "agents": {
                alpha["agentId"]: {
                    "agentId": alpha["agentId"],
                    "limit": limit,
                    "runs": [
                        {
                            "runId": "turn-alpha",
                            "runKind": "agent_run",
                            "agentId": alpha["agentId"],
                            "sessionId": "session-alpha",
                            "status": "running",
                            "summary": "alpha working",
                            "updatedAt": "2026-06-06T01:00:00Z",
                        }
                    ],
                    "subAgentRuns": [],
                },
                beta["agentId"]: {
                    "agentId": beta["agentId"],
                    "limit": limit,
                    "runs": [
                        {
                            "runId": "turn-beta",
                            "runKind": "agent_run",
                            "agentId": beta["agentId"],
                            "sessionId": "session-beta",
                            "status": "failed",
                            "summary": "beta failed",
                            "updatedAt": "2026-06-06T01:01:00Z",
                        }
                    ],
                    "subAgentRuns": [],
                },
            },
        }

    monkeypatch.setattr(agent_config_workspace_service, "list_agent_runs_for_agents", fake_list_agent_runs_for_agents)

    payload = agent_config_workspace_service.get_agent_config_workspace()
    agents = {item["agentId"]: item for item in payload["agents"]}

    assert len(calls) == 1
    assert calls[0][1] == 6
    assert alpha["agentId"] in calls[0][0]
    assert beta["agentId"] in calls[0][0]
    assert agents[alpha["agentId"]]["runtimeStatus"]["state"] == "running"
    assert agents[beta["agentId"]]["runtimeStatus"]["state"] == "failed"
    assert payload["summary"]["runningAgentCount"] == 1
    assert payload["summary"]["blockedAgentCount"] == 1


def test_agent_config_workspace_uses_graph_team_references_without_room_hydration(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team_service.create_team(name="Graph Reference Team", members=[{"agentId": agent["agentId"], "role": "lead"}])
    monkeypatch.setattr(
        chat_room_service,
        "get_chat_room_compact",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("agent config should not hydrate linked room compact")),
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()

    assert payload["summary"]["teamCount"] == 1
    assert payload["teams"][0]["teamId"]
    assert "linkedChatRoom" not in payload["teams"][0]
    assert any(item["kind"] == "team" and item["sourceLabel"] == "Graph Reference Team" for item in payload["references"][agent["agentId"]])


def test_agent_config_workspace_repairs_archived_team_chat_room_residue(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team = team_service.create_team(name="Archived Residue Team", members=[{"agentId": agent["agentId"], "role": "lead"}])
    room_id = team["linkedChatRoomId"]
    teams_path = tmp_path / "workspace" / "teams" / "teams.json"
    teams_payload = json.loads(teams_path.read_text(encoding="utf-8"))
    teams_payload["teams"][0]["status"] = "archived"
    teams_payload["teams"][0]["updatedAt"] = "2026-06-06T00:00:00+00:00"
    teams_path.write_text(json.dumps(teams_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    agent_directory_service.archive_agent_instance(agent["agentId"])

    payload = agent_config_workspace_service.get_agent_config_workspace()

    assert chat_room_service.get_chat_room_detail(room_id) is None
    assert not any(item["code"] == "stale_chat_room_participant" for item in payload["health"]["issues"])
    stored = json.loads(teams_path.read_text(encoding="utf-8"))
    assert stored["teams"][0]["linkedChatRoomId"] == ""


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
    calls = []
    route_payload = {
        "schemaVersion": 1,
        "summary": {"agentCount": 1},
        "toolPolicies": [{"policyId": "default"}],
        "memoryPolicies": [{"policyId": "default"}],
        "agents": [],
        "groups": [],
        "chatRooms": [],
    }
    monkeypatch.setattr(
        agents_route,
        "get_agent_config_workspace",
        lambda: calls.append("get_agent_config_workspace") or route_payload,
    )

    registered_routes = [
        route
        for route in client.app.routes
        if getattr(route, "path", "") == "/api/agents/config-workspace"
        and "GET" in set(getattr(route, "methods", set()) or set())
    ]
    payload = agents_route.agent_config_workspace()

    assert registered_routes
    assert calls == ["get_agent_config_workspace"]
    assert payload["schemaVersion"] == 1
    assert payload["summary"]["agentCount"] >= 1
    assert any(item["policyId"] == "default" for item in payload["toolPolicies"])
    assert payload["memoryPolicies"]


def test_agent_config_workspace_surfaces_runtime_status_from_run_snapshots(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    running_agent = agent_directory_service.create_agent_instance(display_name="运行 Agent")
    failed_agent = agent_directory_service.create_agent_instance(display_name="失败 Agent")

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


def test_agent_config_workspace_ignores_stale_runtime_snapshots_for_current_direct_session(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(display_name="换绑 Agent")
    original_session_id = agent["directSessionId"]
    replacement_session_id = "session-current-direct"

    context_engine.record_agent_turn_result(
        agent["agentId"],
        original_session_id,
        {
            "runId": "turn-old-session",
            "status": "completed",
            "summary": "old direct session result",
            "updatedAt": "2026-05-28T10:00:00Z",
        },
    )
    agent_directory_service.update_agent_instance(agent["agentId"], direct_session_id=replacement_session_id)

    payload = agent_config_workspace_service.get_agent_config_workspace()
    current = next(item for item in payload["agents"] if item["agentId"] == agent["agentId"])

    assert current["directSessionId"] == replacement_session_id
    assert current["runtimeStatus"]["state"] == "idle"
    assert current["runtimeStatus"]["reason"] == "no_current_direct_session_runs"
    assert current["runtimeStatus"]["sessionId"] == replacement_session_id
    assert current["runtimeStatus"]["runId"] == ""
    assert current["runtimeStatus"]["latestHistoricalSessionId"] == original_session_id
    assert current["runtimeStatus"]["staleRuntimeRunCount"] == 1


def test_agent_config_workspace_reports_unresolved_model_reference(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="坏模型 Agent",
        llm_bindings={"dialogue": {"modelId": "missing-model-id"}},
        primary_mode="chat",
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()
    current = next(item for item in payload["agents"] if item["agentId"] == agent["agentId"])
    issues = payload["health"]["byAgent"][agent["agentId"]]

    assert current["dialogueModel"] is None
    assert current["llmBindingModels"]["dialogue"] is None
    assert current["llmBindings"]["dialogue"]["modelId"] == "missing-model-id"
    assert any(item["code"] == "unresolved_model_reference_dialogue" for item in issues)
    assert payload["health"]["counts"]["blocking"] >= 1


def test_agent_config_workspace_reports_unresolved_chat_room_participant_model_reference(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="群聊模型 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-room-model-agent",
    )
    peer = agent_directory_service.create_agent_instance(
        display_name="群聊正常 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-room-model-peer",
    )
    room = chat_room_service.create_chat_room(
        title="配置中心群聊",
        participant_agent_ids=[agent["agentId"], peer["agentId"]],
    )
    room_path = tmp_path / "workspace" / "chat_rooms" / "chat_rooms.json"
    state = json.loads(room_path.read_text(encoding="utf-8"))
    participant = state["rooms"][0]["participants"][0]
    participant["dialogueModelId"] = "missing-room-model"
    participant["llmBindings"] = {"dialogue": {"modelId": "missing-room-model"}}
    room_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    compact = chat_room_service.list_chat_rooms_compact()
    payload = agent_config_workspace_service.get_agent_config_workspace()
    issues = payload["health"]["byAgent"][agent["agentId"]]

    compact_room = next(item for item in compact if item["roomId"] == room["roomId"])
    compact_participant = compact_room["participants"][0]
    assert compact_participant["dialogueModelId"] == "missing-room-model"
    assert compact_participant["llmBindings"]["dialogue"]["modelId"] == "missing-room-model"
    assert any(
        item["code"] == "unresolved_chat_room_participant_model_reference"
        and "missing-room-model" in item["detail"]
        and item["source"] == "chat_room"
        for item in issues
    )
    assert sum(
        1
        for item in issues
        if item["code"] == "unresolved_chat_room_participant_model_reference"
        and "missing-room-model" in item["detail"]
    ) == 1
    assert payload["health"]["counts"]["blocking"] >= 1


def test_agent_create_api_adds_direct_agent_with_safe_defaults(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)

    response = client.post(
        "/api/agents",
        json={
            "displayName": "新增研究 Agent",
            "llmBindings": {"dialogue": {"modelId": "model-primary"}},
            "primaryMode": "research",
            "roleKey": "research_broad",
            "promptTemplateId": "prompt-research-broad",
            "personaProfile": {"personality": "冷静、细致，优先核对证据。"},
            "taskProfile": {"mission": "负责复核研究结论。", "taskTypes": ["research_broad"]},
            "toolPolicy": {"allowedTools": ["agent_message_tool"], "preferredTools": ["agent_message_tool"]},
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
    created = next(item for item in workspace["agents"] if item["agentId"] == agent["agentId"])
    assert created["metadata"]["creationSpec"]["source"] == "api_agents"
    assert created["metadata"]["onboardingStatus"] == "complete"
    assert created["metadata"]["onboardingMissing"] == []
    assert not any(item["code"] == "agent_onboarding_incomplete" for item in created["health"])
    assert created["toolPolicy"]["allowedTools"] == ["agent_message_tool"]


def test_agent_create_api_allows_work_session_without_persona_task_or_role(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)

    response = client.post(
        "/api/agents",
        json={
            "displayName": "项目实现会话",
            "llmBindings": {"dialogue": {"modelId": "model-primary"}},
            "primaryMode": "chat",
            "promptTemplateId": "prompt-chat-default",
        },
    )

    assert response.status_code == 201, response.text
    agent = response.json()
    assert agent["primaryMode"] == "chat"
    assert agent["roleKey"] == ""
    assert not agent_directory_service.agent_persona_profile_has_content(agent["personaProfile"])
    assert not agent_directory_service.agent_task_profile_has_content(agent["taskProfile"])
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    created = next(item for item in workspace["agents"] if item["agentId"] == agent["agentId"])
    assert created["agentBoundary"]["type"] == "work_session"
    assert created["agentBoundary"]["requiresPersonaProfile"] == "false"
    assert created["agentBoundary"]["requiresTaskProfile"] == "false"
    assert created["toolPolicyId"].startswith("tool-")
    assert "conversation_log_inspect_tool" in created["toolPolicy"]["allowedTools"]
    assert "conversation_log_inspect_tool" in created["toolPolicy"]["preferredTools"]
    assert "cli_tool" in created["toolPolicy"]["allowedTools"]
    assert "create_child_session_tool" in created["toolPolicy"]["allowedTools"]
    assert "list_child_sessions_tool" in created["toolPolicy"]["allowedTools"]
    assert "run_test_for_tool" in created["toolPolicy"]["allowedTools"]
    assert "web_search_tool" in created["toolPolicy"]["allowedTools"]
    assert "image2_generate_tool" in created["toolPolicy"]["allowedTools"]
    assert "search_memory_tool" in created["toolPolicy"]["allowedTools"]
    assert "record_learning_tool" in created["toolPolicy"]["allowedTools"]
    assert "read_file_tool" not in created["toolPolicy"]["allowedTools"]
    assert "grep_search_tool" not in created["toolPolicy"]["allowedTools"]
    assert "glob_tool" not in created["toolPolicy"]["allowedTools"]
    assert "code_symbol_tool" not in created["toolPolicy"]["allowedTools"]
    assert "research_knowledge_query_tool" not in created["toolPolicy"]["allowedTools"]
    assert "knowledge_proposal_tool" not in created["toolPolicy"]["allowedTools"]
    assert "research_agent_creation_proposal_tool" not in created["toolPolicy"]["allowedTools"]
    assert not any(item["code"] == "agent_onboarding_incomplete" for item in created["health"])


def test_repair_adds_session_default_tools_to_legacy_work_session_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Legacy Session Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        prompt_template_id="prompt-chat-default",
    )
    state = agent_directory_service.load_state()
    raw_agent = next(item for item in state["agents"] if item["agentId"] == agent["agentId"])
    raw_agent["toolPolicyId"] = agent_directory_service.DEFAULT_TOOL_POLICY_ID
    state["toolPolicies"][agent_directory_service.DEFAULT_TOOL_POLICY_ID] = agent_directory_service.default_tool_policy()
    agent_directory_service.save_state(state)

    repaired = agent_directory_service.repair_agent_directory()
    repaired_agent = next(item for item in repaired["agents"] if item["agentId"] == agent["agentId"])
    policy = repaired["toolPolicies"][repaired_agent["toolPolicyId"]]

    assert repaired_agent["toolPolicyId"].startswith("tool-")
    assert "conversation_log_inspect_tool" in policy["allowedTools"]
    assert "conversation_log_inspect_tool" in policy["preferredTools"]
    assert "cli_tool" in policy["allowedTools"]
    assert "create_child_session_tool" in policy["allowedTools"]
    assert "list_child_sessions_tool" in policy["allowedTools"]
    assert "record_learning_tool" in policy["allowedTools"]
    assert "read_file_tool" not in policy["allowedTools"]
    assert "grep_search_tool" not in policy["allowedTools"]
    assert "glob_tool" not in policy["allowedTools"]
    assert "code_symbol_tool" not in policy["allowedTools"]
    assert repaired_agent["metadata"]["onboardingStatus"] == "complete"


def test_agent_create_api_rejects_incomplete_onboarding_payload(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)

    response = client.post(
        "/api/agents",
        json={
            "displayName": "半成品 Agent",
            "llmBindings": {"dialogue": {"modelId": "model-primary"}},
            "primaryMode": "research",
            "promptTemplateId": "prompt-research-broad",
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "Agent 创建信息不完整" in detail
    assert "角色键" in detail
    assert "人物档案" in detail
    assert "任务档案" in detail
    assert "工具包" in detail


def test_agent_create_api_rejects_blank_display_name(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    response = client.post("/api/agents", json={"displayName": "   ", "llmBindings": {"dialogue": {"modelId": "model-primary"}}})

    assert response.status_code == 422
    assert "功能名" in response.json()["detail"]


def test_agent_onboarding_health_clears_after_required_profiles_and_tools(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="完整 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="research",
        role_key="research_full",
        prompt_template_id="prompt-research-broad",
    )

    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "personaProfile": {"communicationStyle": "先给结论，再列证据。"},
            "taskProfile": {"mission": "负责研究复核。", "taskTypes": ["research_review"]},
            "toolPolicy": {
                "allowedTools": ["agent_message_tool"],
                "preferredTools": ["agent_message_tool"],
                "writeScopes": ["private"],
            },
        },
    )

    assert response.status_code == 200, response.text
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    created = next(item for item in workspace["agents"] if item["agentId"] == agent["agentId"])
    assert created["metadata"]["onboardingStatus"] == "complete"
    assert created["metadata"]["onboardingMissing"] == []
    assert not any(item["code"] == "agent_onboarding_incomplete" for item in created["health"])


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
    team = team_service.create_team(
        name="待清理团队",
        members=[{"agentId": alpha["agentId"], "role": "lead"}, {"agentId": beta["agentId"], "role": "peer"}],
    )

    response = client.delete(f"/api/agents/{alpha['agentId']}")

    assert response.status_code == 200, response.text
    archived = response.json()
    assert archived["status"] == "archived"
    assert archived["archiveSummary"]["dataRetention"] == "archived_only"
    assert archived["archiveSummary"]["removedFromRoomIds"] == [room["roomId"]]
    assert archived["archiveSummary"]["removedFromTeamIds"] == [team["teamId"]]
    assert alpha["agentId"] not in {item["agentId"] for item in agent_directory_service.list_agents(include_archived=False)}
    assert agent_directory_service.get_agent(alpha["agentId"], include_archived=True)["status"] == "archived"
    bindings = agent_mode_binding_service.get_mode_bindings_payload()["modes"]
    assert bindings["chat"]["defaultAgentId"] == beta["agentId"]
    assert alpha["agentId"] not in bindings["chat"]["availableAgentIds"]
    assert alpha["agentId"] not in bindings["research"]["pool"]
    assert alpha["agentId"] not in bindings["research"]["flowBindings"].values()
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [participant["agentId"] for participant in room_detail["participants"]] == [beta["agentId"]]
    team_detail = team_service.get_team(team["teamId"])
    assert [member["agentId"] for member in team_detail["members"]] == [beta["agentId"]]
    assert all(node.get("agentId") != alpha["agentId"] for node in team_detail["canvas"]["nodes"])
    linked_room = chat_room_service.get_chat_room_detail(team_detail["linkedChatRoomId"])
    assert [participant["agentId"] for participant in linked_room["participants"]] == [beta["agentId"]]
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    groups = {group["id"]: group for group in workspace["groups"]}
    assert alpha["agentId"] in groups["archived"]["agentIds"]
    assert alpha["agentId"] not in groups["active"]["agentIds"]
    assert alpha["agentId"] not in groups["chat"]["agentIds"]
    assert alpha["agentId"] not in groups["research"]["agentIds"]
    assert alpha["agentId"] not in groups["group_chat"]["agentIds"]


def test_agent_config_workspace_does_not_report_historical_mode_repair_warnings(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = session_service.create_chat_session(title="归档 Agent")
    state = agent_mode_binding_service.default_mode_binding_state()
    state["modes"]["chat"]["defaultAgentId"] = agent["agentId"]
    state["modes"]["chat"]["availableAgentIds"] = [agent["agentId"]]
    agent_mode_binding_service.save_mode_binding_state(state)
    agent_directory_service.archive_agent_instance(agent["agentId"])

    payload = agent_config_workspace_service.get_agent_config_workspace()

    assert agent["agentId"] not in payload["modeBindings"]["chat"]["availableAgentIds"]
    assert not any(
        item["code"] == "stale_mode_binding" and item["agentId"] == agent["agentId"]
        for item in payload["health"]["issues"]
    )


def test_agent_delete_api_does_not_reactivate_archived_supervised_non_core_fixed_role(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    supervised = supervised_agent_service.ensure_supervised_agent_instances()
    baseline = next(agent for agent in supervised if agent["metadata"].get("supervisedRole") == "baseline")
    events = []
    monkeypatch.setattr(
        supervised_agent_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )

    response = client.delete(f"/api/agents/{baseline['agentId']}")
    assert response.status_code == 200, response.text

    workspace_response = client.get("/api/agents/config-workspace")
    assert workspace_response.status_code == 200, workspace_response.text
    archived = agent_directory_service.get_agent(baseline["agentId"], include_archived=True)
    assert archived["status"] == "archived"
    payload = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["supervised_evolution"]
    assert payload["slots"]["baseline"] == ""
    assert "baseline" in payload["excludedSlots"]
    assert baseline["agentId"] not in payload["availableAgentIds"]
    workspace = workspace_response.json()
    assert baseline["agentId"] in {item["agentId"] for item in workspace["agents"] if item["status"] == "archived"}
    assert baseline["agentId"] not in workspace["modeBindings"]["supervised_evolution"]["availableAgentIds"]
    assert not any(item[0][2] == "agent.reactivated" for item in events)


def test_agent_delete_api_blocks_core_supervised_judge(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    supervised = supervised_agent_service.ensure_supervised_agent_instances()
    judge = next(agent for agent in supervised if agent["metadata"].get("supervisedRole") == "judge")

    response = client.delete(f"/api/agents/{judge['agentId']}")

    assert response.status_code == 422
    assert "Protected core Agent" in response.json()["detail"]
    active = agent_directory_service.get_agent(judge["agentId"], include_archived=False)
    assert active["metadata"]["protected"] is True
    payload = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["supervised_evolution"]
    assert payload["slots"]["judge"] == judge["agentId"]


def test_agent_patch_status_archived_uses_safe_archive_cleanup(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    supervised = supervised_agent_service.ensure_supervised_agent_instances()
    reviewer = next(agent for agent in supervised if agent["metadata"].get("supervisedRole") == "reviewer")
    peer = session_service.create_chat_session(title="Peer Agent")
    room = chat_room_service.create_chat_room(
        title="PATCH 归档群聊",
        participant_agent_ids=[reviewer["agentId"], peer["agentId"]],
    )
    team = team_service.create_team(
        name="PATCH 归档团队",
        members=[{"agentId": reviewer["agentId"], "role": "reviewer"}, {"agentId": peer["agentId"], "role": "peer"}],
    )

    response = client.patch(
        f"/api/agents/{reviewer['agentId']}",
        json={"displayName": reviewer["displayName"], "status": "archived"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "archived"
    assert payload["archiveSummary"]["source"] == "patch_status"
    assert payload["archiveSummary"]["removedFromRoomIds"] == [room["roomId"]]
    assert payload["archiveSummary"]["removedFromTeamIds"] == [team["teamId"]]
    archived = agent_directory_service.get_agent(reviewer["agentId"], include_archived=True)
    assert archived["status"] == "archived"
    bindings = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["supervised_evolution"]
    assert bindings["slots"]["reviewer"] == ""
    assert "reviewer" in bindings["excludedSlots"]
    assert reviewer["agentId"] not in bindings["availableAgentIds"]
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [participant["agentId"] for participant in room_detail["participants"]] == [peer["agentId"]]
    team_detail = team_service.get_team(team["teamId"])
    assert [member["agentId"] for member in team_detail["members"]] == [peer["agentId"]]


def test_agent_purge_api_does_not_recreate_deleted_supervised_fixed_role(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    supervised = supervised_agent_service.ensure_supervised_agent_instances()
    auditor = next(agent for agent in supervised if agent["metadata"].get("supervisedRole") == "auditor")

    archive_response = client.delete(f"/api/agents/{auditor['agentId']}")
    assert archive_response.status_code == 200, archive_response.text
    purge_response = client.delete(f"/api/agents/{auditor['agentId']}/purge")
    assert purge_response.status_code == 200, purge_response.text

    workspace_response = client.get("/api/agents/config-workspace")
    assert workspace_response.status_code == 200, workspace_response.text
    assert agent_directory_service.get_agent(auditor["agentId"], include_archived=True) is None
    payload = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["supervised_evolution"]
    assert payload["slots"]["auditor"] == ""
    assert "auditor" in payload["excludedSlots"]
    workspace = workspace_response.json()
    supervised_agents = [
        item
        for item in workspace["agents"]
        if item.get("primaryMode") == "supervised_evolution"
        and item.get("roleKey") == "auditor"
    ]
    assert supervised_agents == []


def test_agent_purge_api_preserves_fixed_role_tombstone_after_legacy_archive(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    supervised = supervised_agent_service.ensure_supervised_agent_instances()
    reviewer = next(agent for agent in supervised if agent["metadata"].get("supervisedRole") == "reviewer")
    agent_directory_service.archive_agent_instance(reviewer["agentId"])
    repaired = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["supervised_evolution"]
    assert repaired["slots"]["reviewer"] == ""

    purge_response = client.delete(f"/api/agents/{reviewer['agentId']}/purge")
    assert purge_response.status_code == 200, purge_response.text
    workspace_response = client.get("/api/agents/config-workspace")
    assert workspace_response.status_code == 200, workspace_response.text

    payload = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["supervised_evolution"]
    assert payload["slots"]["reviewer"] == ""
    assert "reviewer" in payload["excludedSlots"]
    workspace = workspace_response.json()
    assert not [
        item
        for item in workspace["agents"]
        if item.get("primaryMode") == "supervised_evolution"
        and item.get("roleKey") == "reviewer"
    ]


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


def test_agent_delete_api_logs_stage_timings_and_skips_duplicate_mode_cleanup(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    agent_mode_binding_service.update_mode_binding(
        "chat",
        default_agent_id=alpha["agentId"],
        available_agent_ids=[alpha["agentId"], beta["agentId"]],
    )
    events = []
    mode_cleanup_calls = []
    real_remove_agent_from_mode_bindings = agents_route.remove_agent_from_mode_bindings

    def tracked_remove_agent_from_mode_bindings(agent_id):
        mode_cleanup_calls.append(agent_id)
        return real_remove_agent_from_mode_bindings(agent_id)

    monkeypatch.setattr(agents_route, "remove_agent_from_mode_bindings", tracked_remove_agent_from_mode_bindings)
    monkeypatch.setattr(
        agents_route,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )

    response = client.delete(f"/api/agents/{alpha['agentId']}")

    assert response.status_code == 200, response.text
    assert mode_cleanup_calls == [alpha["agentId"]]
    completed = [event for event in events if event[0][:3] == ("agent_directory", "delete", "agent.archive.completed")]
    assert completed
    fields = completed[-1][1]["fields"]
    assert {"ensure_archive_allowed", "remove_from_teams", "remove_from_chat_rooms", "remove_from_mode_bindings", "archive_agent"}.issubset(fields["timingsMs"])
    assert fields["durationMs"] >= fields["timingsMs"]["archive_agent"]
    bindings = agent_mode_binding_service.get_mode_bindings_payload()["modes"]
    assert bindings["chat"]["defaultAgentId"] == beta["agentId"]


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
    team = team_service.create_team(
        name="待 purge 团队",
        members=[{"agentId": alpha["agentId"], "role": "lead"}, {"agentId": beta["agentId"], "role": "peer"}],
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
    assert payload["purgeSummary"]["removedFromTeamIds"] == [team["teamId"]]
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
    team_detail = team_service.get_team(team["teamId"])
    assert [member["agentId"] for member in team_detail["members"]] == [beta["agentId"]]


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

    assert response.status_code == 422, response.text
    assert "PermissionError" in response.json()["detail"]
    assert agent_directory_service.get_agent(agent["agentId"], include_archived=True)["status"] == "archived"
    assert workspace_path.exists()


def test_agent_reset_api_clears_runtime_state_without_removing_bindings_or_memory(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    reset_events = []
    monkeypatch.setattr(
        agents_route,
        "record_runtime_scene_event",
        lambda *args, **kwargs: reset_events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: reset_events.append((args, kwargs)) or {"accepted": True},
    )
    direct_session = session_service.create_chat_session(title="Resettable Agent")
    agent = agent_directory_service.get_agent(direct_session["agentId"])
    peer = agent_directory_service.create_agent_instance(
        display_name="Peer Agent",
        direct_session_id="session-peer-agent",
    )
    agent_mode_binding_service.update_mode_binding(
        "chat",
        default_agent_id=agent["agentId"],
        available_agent_ids=[agent["agentId"], peer["agentId"]],
    )
    room = chat_room_service.create_chat_room(
        title="调试群聊",
        participant_agent_ids=[agent["agentId"], peer["agentId"]],
    )
    team = team_service.create_team(
        name="调试团队",
        members=[{"agentId": agent["agentId"], "role": "lead"}],
    )
    workspace_path = tmp_path / agent["workspacePath"]
    for subdir in ("inbox", "events", "logs", "runs", "scratch", "artifacts"):
        target = workspace_path / subdir
        target.mkdir(parents=True, exist_ok=True)
        (target / "trace.txt").write_text("runtime trace", encoding="utf-8")
    memory_file = workspace_path / "memory" / "keep.md"
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    memory_file.write_text("private memory", encoding="utf-8")

    response = client.post(f"/api/agents/{agent['agentId']}/reset", json={})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["agent"]["agentId"] == agent["agentId"]
    assert payload["agent"]["status"] == "active"
    assert payload["agent"]["directSessionId"] != direct_session["id"]
    assert payload["resetSummary"]["clearedRuntimeState"] is True
    assert payload["resetSummary"]["resetDirectSession"] is True
    assert payload["resetSummary"]["previousDirectSessionId"] == direct_session["id"]
    assert payload["resetSummary"]["replacementDirectSessionId"] == payload["agent"]["directSessionId"]
    assert "team_membership" in payload["resetSummary"]["preserved"]
    for subdir in ("inbox", "events", "logs", "runs", "scratch", "artifacts"):
        assert (workspace_path / subdir).is_dir()
        assert not (workspace_path / subdir / "trace.txt").exists()
    assert memory_file.read_text(encoding="utf-8") == "private memory"
    session_ids = {item["id"] for item in session_service.list_sessions()}
    assert direct_session["id"] not in session_ids
    assert payload["agent"]["directSessionId"] in session_ids
    active_session = session_service.get_active_session_detail()
    assert active_session["id"] == payload["agent"]["directSessionId"]
    bindings = agent_mode_binding_service.get_mode_bindings_payload()["modes"]
    assert bindings["chat"]["defaultAgentId"] == agent["agentId"]
    assert agent["agentId"] in bindings["chat"]["availableAgentIds"]
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert agent["agentId"] in {participant["agentId"] for participant in room_detail["participants"]}
    team_detail = team_service.get_team(team["teamId"])
    assert agent["agentId"] in [member["agentId"] for member in team_detail["members"]]
    event_codes = [item[0][2] for item in reset_events]
    assert event_codes.count("agent.reset.requested") == 1
    assert event_codes.count("agent.reset.completed") == 1
    requested_fields = next(item[1]["fields"] for item in reset_events if item[0][2] == "agent.reset.requested")
    completed_fields = next(item[1]["fields"] for item in reset_events if item[0][2] == "agent.reset.completed")
    assert requested_fields["agentId"] == agent["agentId"]
    assert requested_fields["clearRuntimeState"] is True
    assert requested_fields["resetDirectSession"] is True
    assert completed_fields["agentId"] == agent["agentId"]
    assert completed_fields["deletedPathCount"] == len(payload["resetSummary"]["deletedPaths"])
    assert completed_fields["deletedPathCount"] >= 6


def test_agent_reset_api_can_keep_existing_direct_session_when_requested(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    direct_session = session_service.create_chat_session(title="保留直连会话")
    agent = agent_directory_service.get_agent(direct_session["agentId"])

    response = client.post(
        f"/api/agents/{agent['agentId']}/reset",
        json={"resetDirectSession": False},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["resetSummary"]["resetDirectSession"] is False
    assert payload["agent"]["directSessionId"] == direct_session["id"]
    assert direct_session["id"] in {item["id"] for item in session_service.list_sessions()}


def test_agent_reset_api_can_reset_session_agent_advanced_policies_without_profiles(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Advanced Reset Agent")
    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "personaProfile": {"gender": "female", "age": "34", "communicationStyle": "brief"},
            "taskProfile": {"mission": "run experiments", "taskTypes": ["research"]},
            "toolPolicy": {
                "policyId": agent["toolPolicyId"],
                "allowedTools": ["web_search"],
                "preferredTools": ["web_search"],
                "blockedTools": [],
                "readScopes": ["private"],
                "writeScopes": ["private", "shared"],
            },
            "memoryPolicy": {
                "policyId": agent["memoryPolicyId"],
                "readSharedGroups": ["research"],
                "writeSharedGroups": ["research"],
            },
            "delegationPolicy": {"allowSubagents": True, "maxConcurrent": 3, "maxDepth": 2},
            "supervisionPolicy": {"supervisionEnabled": True, "requiresReview": True, "reviewMode": "approval"},
        },
    )
    assert response.status_code == 200, response.text

    reset = client.post(
        f"/api/agents/{agent['agentId']}/reset",
        json={
            "clearRuntimeState": False,
            "resetPersonaProfile": True,
            "resetTaskProfile": True,
            "resetToolPolicy": True,
            "resetMemoryPolicy": True,
            "resetRuntimePolicy": True,
        },
    )

    assert reset.status_code == 200, reset.text
    payload = reset.json()
    assert payload["resetSummary"]["clearedRuntimeState"] is False
    assert payload["agent"]["personaProfile"] == {}
    assert payload["agent"]["taskProfile"] == {}
    assert payload["resetSummary"]["resetPersonaProfile"] is False
    assert payload["resetSummary"]["resetTaskProfile"] is False
    assert payload["agent"]["toolPolicyId"].startswith("tool-")
    assert "conversation_log_inspect_tool" in payload["agent"]["toolPolicy"]["allowedTools"]
    assert "cli_tool" in payload["agent"]["toolPolicy"]["allowedTools"]
    assert "create_child_session_tool" in payload["agent"]["toolPolicy"]["allowedTools"]
    assert "list_child_sessions_tool" in payload["agent"]["toolPolicy"]["allowedTools"]
    assert "read_file_tool" not in payload["agent"]["toolPolicy"]["allowedTools"]
    assert payload["agent"]["memoryPolicy"]["readSharedGroups"] == []
    assert payload["agent"]["memoryPolicy"]["writeSharedGroups"] == []
    assert payload["agent"]["metadata"]["delegationPolicy"]["allowSubagents"] is False
    assert payload["agent"]["metadata"]["supervisionPolicy"]["supervisionEnabled"] is False


def test_agent_reset_api_can_reset_team_agent_profiles(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Advanced Profile Reset Agent",
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
    )
    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "personaProfile": {"gender": "female", "age": "34", "communicationStyle": "brief"},
            "taskProfile": {"mission": "run experiments", "taskTypes": ["research"]},
        },
    )
    assert response.status_code == 200, response.text

    reset = client.post(
        f"/api/agents/{agent['agentId']}/reset",
        json={
            "clearRuntimeState": False,
            "resetPersonaProfile": True,
            "resetTaskProfile": True,
            "resetToolPolicy": False,
            "resetMemoryPolicy": False,
            "resetRuntimePolicy": False,
        },
    )

    assert reset.status_code == 200, reset.text
    payload = reset.json()
    assert payload["resetSummary"]["resetPersonaProfile"] is True
    assert payload["resetSummary"]["resetTaskProfile"] is True
    assert payload["agent"]["personaProfile"]["communicationStyle"] == ""
    assert payload["agent"]["personaProfile"]["age"] == ""
    assert payload["agent"]["taskProfile"]["mission"] == ""
    assert payload["agent"]["taskProfile"]["taskTypes"] == []


def test_agent_reset_api_rejects_archived_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    reset_events = []
    monkeypatch.setattr(
        agents_route,
        "record_runtime_scene_event",
        lambda *args, **kwargs: reset_events.append((args, kwargs)) or {"accepted": True},
    )
    agent = session_service.create_chat_session(title="Archived Reset Agent")
    agent_directory_service.archive_agent_instance(agent["agentId"])

    response = client.post(f"/api/agents/{agent['agentId']}/reset", json={})

    assert response.status_code == 422
    assert "Archived Agent cannot be reset" in response.json()["detail"]
    assert agent_directory_service.get_agent(agent["agentId"], include_archived=True)["status"] == "archived"
    event_codes = [item[0][2] for item in reset_events]
    assert event_codes == ["agent.reset.requested", "agent.reset.failed"]
    failed_fields = reset_events[-1][1]["fields"]
    assert failed_fields["agentId"] == agent["agentId"]
    assert failed_fields["errorType"] == "AgentDirectoryError"


def test_agent_inbox_consume_all_api_clears_pending_health_issue(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    target = agent_directory_service.create_agent_instance(display_name="收件 Agent")
    source = agent_directory_service.create_agent_instance(display_name="来源 Agent")
    for index in range(3):
        agent_directory_service.write_agent_inbox_message(
            target["agentId"],
            content=f"消息 {index}",
            source_agent_id=source["agentId"],
        )

    before = agent_config_workspace_service.get_agent_config_workspace()
    assert any(
        item["code"] == "pending_inbox_messages"
        for item in before["health"]["byAgent"][target["agentId"]]
    )

    response = client.post(
        f"/api/agents/{target['agentId']}/messages/consume-all",
        json={"consumedBySessionId": target["directSessionId"], "consumedByTurnId": "test"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["consumedCount"] == 3
    assert payload["remainingPendingCount"] == 0
    assert agent_directory_service.count_agent_inbox_messages_for_agent(target["agentId"], status="pending") == 0
    after = agent_config_workspace_service.get_agent_config_workspace()
    assert all(
        item["code"] != "pending_inbox_messages"
        for item in after["health"]["byAgent"].get(target["agentId"], [])
    )


def test_agent_config_workspace_agent_patch_updates_card_fields(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="旧 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        prompt_template_id="prompt-chat-default",
    )
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    memory_policy_id = workspace["memoryPolicies"][0]["policyId"]

    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "displayName": "新 Agent",
            "llmBindings": {"dialogue": {"modelId": "model-research"}},
            "promptTemplateId": "prompt-research-broad",
            "toolPolicyId": "default",
            "memoryPolicyId": memory_policy_id,
            "status": "active",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["displayName"] == "新 Agent"
    assert payload["llmBindings"]["dialogue"]["modelId"] == "model-research"
    assert "profileId" not in payload
    assert payload["promptTemplateId"] == "prompt-research-broad"
    assert payload["toolPolicyId"] == "default"
    assert payload["memoryPolicyId"] == memory_policy_id


def test_normalize_tool_policy_dedupes_tool_lists_preserving_order():
    policy = agent_directory_service.normalize_tool_policy(
        {
            "policyId": "tool-test",
            "allowedTools": ["cli_tool", "rg_tool", "cli_tool", "", "rg_tool"],
            "preferredTools": ["cli_tool", "cli_tool", "read_file_tool"],
            "blockedTools": ["danger", "danger"],
        },
        "tool-test",
    )

    assert policy["allowedTools"] == ["cli_tool", "rg_tool"]
    assert policy["preferredTools"] == ["cli_tool", "read_file_tool"]
    assert policy["blockedTools"] == ["danger"]


def test_agent_api_rejects_legacy_profile_and_template_fields(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    create_response = client.post(
        "/api/agents",
        json={
            "displayName": "旧字段 Agent",
            "profileId": "primary",
            "llmBindings": {"dialogue": {"modelId": "model-primary"}},
            "primaryMode": "chat",
            "promptTemplateId": "prompt-chat-default",
            "toolPolicy": {"allowedTools": ["agent_message_tool"]},
        },
    )

    assert create_response.status_code == 422
    assert "profileId" in create_response.text

    agent = agent_directory_service.create_agent_instance(
        display_name="新字段 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        prompt_template_id="prompt-chat-default",
    )
    patch_response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={"templateId": "primary", "promptTemplateId": "prompt-chat-default"},
    )

    assert patch_response.status_code == 422
    assert "templateId" in patch_response.text


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


def test_agent_tool_governance_low_risk_change_auto_applies_for_governance_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    recorded_events = []
    monkeypatch.setattr(
        agent_tool_governance_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    advisor = agent_directory_service.create_agent_instance(
        display_name="能力顾问",
        metadata={"systemRole": "organization_advisor", "researchOrgRole": "organization_advisor"},
    )
    target = agent_directory_service.create_agent_instance(
        display_name="资料 Agent",
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
    )

    request = agent_tool_governance_service.submit_tool_governance_request(
        target["agentId"],
        proposed_by_agent_id=advisor["agentId"],
        grant_tools=["read_file_tool", "grep_search_tool"],
        reason="资料 Agent 需要只读检索项目材料。",
        apply_mode="auto",
    )

    updated = agent_directory_service.get_agent(target["agentId"])
    assert request["status"] == "applied"
    assert request["requiresApproval"] is False
    assert request["riskLevel"] == "low"
    assert updated["toolPolicy"]["allowedTools"] == ["read_file_tool", "grep_search_tool"]
    assert request["after"]["allowedTools"] == ["read_file_tool", "grep_search_tool"]
    assert any(
        event[0][:3] == ("agent_tool_governance", "tool_policy", "agent_tool_governance.request_applied")
        and event[1]["fields"]["targetAgentId"] == target["agentId"]
        for event in recorded_events
    )
    assert agent_tool_governance_service.list_tool_governance_requests(agent_id=target["agentId"], status="applied")[0][
        "requestId"
    ] == request["requestId"]


def test_agent_tool_governance_high_risk_change_waits_for_review_and_can_be_approved(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    advisor = agent_directory_service.create_agent_instance(
        display_name="权限顾问",
        metadata={"systemRole": "capability_steward", "researchOrgRole": "capability_steward"},
    )
    target = agent_directory_service.create_agent_instance(
        display_name="执行 Agent",
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
    )

    request = agent_tool_governance_service.submit_tool_governance_request(
        target["agentId"],
        proposed_by_agent_id=advisor["agentId"],
        grant_tools=["cli_tool"],
        reason="执行 Agent 需要运行验证命令。",
        apply_mode="auto",
    )
    unchanged = agent_directory_service.get_agent(target["agentId"])

    assert request["status"] == "pending_review"
    assert request["requiresApproval"] is True
    assert request["riskLevel"] == "high"
    assert unchanged["toolPolicy"]["allowedTools"] == []

    approved = agent_tool_governance_service.resolve_tool_governance_request(
        target["agentId"],
        request["requestId"],
        decision="approve",
        resolved_by="user",
        resolution_note="允许本轮验证。",
    )
    updated = agent_directory_service.get_agent(target["agentId"])

    assert approved["status"] == "applied"
    assert approved["resolvedBy"] == "user"
    assert updated["toolPolicy"]["allowedTools"] == ["cli_tool"]


def test_agent_tool_governance_uses_shared_tool_catalog_risk_metadata(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    advisor = agent_directory_service.create_agent_instance(
        display_name="工具目录顾问",
        metadata={"systemRole": "capability_steward", "researchOrgRole": "capability_steward"},
    )
    target = agent_directory_service.create_agent_instance(
        display_name="图像 Agent",
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
    )

    request = agent_tool_governance_service.submit_tool_governance_request(
        target["agentId"],
        proposed_by_agent_id=advisor["agentId"],
        grant_tools=["image2_generate_tool"],
        reason="图像 Agent 需要生成研究配图。",
        apply_mode="auto",
    )

    assert request["status"] == "pending_review"
    assert request["riskLevel"] == "high"
    assert {"model_cost", "artifact_write"}.issubset(set(request["riskTags"]))
    assert agent_directory_service.get_agent(target["agentId"])["toolPolicy"]["allowedTools"] == []


def test_agent_tool_governance_routes_create_and_resolve_requests(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(agents_route, "_ensure_config_agent_instances", lambda: None)
    advisor = agent_directory_service.create_agent_instance(
        display_name="路由顾问",
        metadata={"systemRole": "organization_advisor", "researchOrgRole": "organization_advisor"},
    )
    target = agent_directory_service.create_agent_instance(
        display_name="路由目标",
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
    )

    created = client.post(
        f"/api/agents/{target['agentId']}/tool-governance-requests",
        json={
            "proposedByAgentId": advisor["agentId"],
            "grantTools": ["image2_generate_tool"],
            "reason": "需要图片生成能力。",
            "applyMode": "auto",
        },
    )

    assert created.status_code == 201, created.text
    request = created.json()
    assert request["status"] == "pending_review"
    listed = client.get("/api/agents/tool-governance-requests", params={"agentId": target["agentId"]})
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["requestId"] == request["requestId"]

    resolved = client.patch(
        f"/api/agents/{target['agentId']}/tool-governance-requests/{request['requestId']}",
        json={"decision": "reject", "resolvedBy": "user", "resolutionNote": "暂不开放。"},
    )

    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "rejected"


def test_agent_config_workspace_surfaces_recent_tool_governance_requests(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    advisor = agent_directory_service.create_agent_instance(
        display_name="配置顾问",
        metadata={"systemRole": "organization_advisor", "researchOrgRole": "organization_advisor"},
    )
    target = agent_directory_service.create_agent_instance(
        display_name="配置目标",
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
    )
    request = agent_tool_governance_service.submit_tool_governance_request(
        target["agentId"],
        proposed_by_agent_id=advisor["agentId"],
        grant_tools=["cli_tool"],
        reason="需要命令验证。",
    )

    workspace = agent_config_workspace_service.get_agent_config_workspace()
    workspace_agent = next(item for item in workspace["agents"] if item["agentId"] == target["agentId"])

    assert workspace_agent["toolGovernanceRequests"][0]["requestId"] == request["requestId"]
    assert workspace_agent["toolGovernanceRequests"][0]["status"] == "pending_review"


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
        json={
            "memoryPolicy": {
                "readSharedGroups": ["project", "research"],
                "writeSharedGroups": ["project"],
                "readKnowledgeBaseIds": ["kb-research"],
                "proposeKnowledgeBaseIds": ["kb-research"],
                "reviewKnowledgeBaseIds": ["kb-review"],
            }
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["memoryPolicyId"] == f"memory-{agent['agentId']}"
    assert payload["memoryPolicy"]["readSharedGroups"] == ["project", "research"]
    assert payload["memoryPolicy"]["writeSharedGroups"] == ["project"]
    assert payload["memoryPolicy"]["readKnowledgeBaseIds"] == ["kb-research"]
    assert payload["memoryPolicy"]["proposeKnowledgeBaseIds"] == ["kb-research"]
    assert payload["memoryPolicy"]["reviewKnowledgeBaseIds"] == ["kb-review"]
    assert payload["memoryPolicy"]["privateMemoryRoot"].endswith("/memory")
    assert any(
        event[0][:3] == ("agent_directory", "memory_policy", "agent.memory_policy.updated")
        and event[1]["fields"]["readSharedGroupCount"] == 2
        and event[1]["fields"]["writeSharedGroupCount"] == 1
        and event[1]["fields"]["readKnowledgeBaseCount"] == 1
        and event[1]["fields"]["reviewKnowledgeBaseCount"] == 1
        for event in recorded_events
    )
    context_block = agent_directory_service.build_agent_runtime_context_block(agent["agentId"])
    assert "TeamKnowledgeAccess:" in context_block
    assert "ReadKnowledgeBaseIds: kb-research" in context_block
    assert "Knowledge bodies are tool-readable only" in context_block


def test_project_memory_update_proposals_are_agent_private_and_resolvable(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    alpha = agent_directory_service.create_agent_instance(
        display_name="运行主干 Agent",
        direct_session_id="session-alpha",
    )
    beta = agent_directory_service.create_agent_instance(
        display_name="前端 Agent",
        direct_session_id="session-beta",
    )

    first = agent_directory_service.write_project_memory_update_proposal(
        alpha["agentId"],
        lane_id="agent-runtime-core",
        focus="memory proposal queue",
        update="Add a serialized project-memory proposal queue.",
        related_files=["core/web/services/agent_directory_service.py"],
        source_turn_id="turn-alpha",
    )
    second = agent_directory_service.write_project_memory_update_proposal(
        beta["agentId"],
        lane_id="web-workbench-surface",
        update="Surface pending memory proposals in Agent Center later.",
    )

    proposal_path = tmp_path / "workspace" / "agents" / alpha["agentId"] / "events" / "project_memory_updates.jsonl"
    assert proposal_path.exists()
    assert agent_directory_service.resolve_memory_policy_for_agent(alpha["agentId"])[
        "projectMemoryUpdatesPath"
    ] == f"workspace/agents/{alpha['agentId']}/events/project_memory_updates.jsonl"
    pending = agent_directory_service.list_project_memory_update_proposals(status="pending")
    assert [item["proposalId"] for item in pending] == [first["proposalId"], second["proposalId"]]

    resolved = agent_directory_service.resolve_project_memory_update_proposal(
        alpha["agentId"],
        first["proposalId"],
        status="applied",
        resolved_by="coordinator",
        resolution_note="Merged into agent-runtime-core lane.",
    )

    assert resolved["status"] == "applied"
    assert resolved["resolvedBy"] == "coordinator"
    assert agent_directory_service.list_project_memory_update_proposals(status="pending") == [second]
    context_block = agent_directory_service.build_agent_runtime_context_block(alpha["agentId"])
    assert "ProjectMemoryUpdatesPath:" in context_block
    assert any(
        event[0][:3] == ("agent_memory", "events", "project_memory_update.proposed")
        for event in recorded_events
    )
    assert any(
        event[0][:3] == ("agent_memory", "events", "project_memory_update.resolved")
        for event in recorded_events
    )


def test_project_memory_update_proposal_routes_queue_and_resolve(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: {"accepted": True},
    )
    agent = agent_directory_service.create_agent_instance(
        display_name="协同 Agent",
        direct_session_id="session-memory-proposal",
    )

    created = client.post(
        f"/api/agents/{agent['agentId']}/project-memory-updates",
        json={
            "laneId": "agent-runtime-core",
            "focus": "proposal queue",
            "update": "Record project-memory changes as per-Agent proposals.",
            "details": "Coordinator will merge these proposals serially.",
            "relatedFiles": ["AGENTS.md"],
            "sourceTurnId": "turn-1",
        },
    )

    assert created.status_code == 201, created.text
    proposal = created.json()
    assert proposal["status"] == "pending"
    listed = client.get("/api/agents/project-memory-updates")
    assert listed.status_code == 200, listed.text
    assert [item["proposalId"] for item in listed.json()] == [proposal["proposalId"]]

    resolved = client.patch(
        f"/api/agents/{agent['agentId']}/project-memory-updates/{proposal['proposalId']}",
        json={
            "status": "rejected",
            "resolvedBy": "coordinator",
            "resolutionNote": "Duplicate proposal.",
        },
    )

    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "rejected"
    assert client.get("/api/agents/project-memory-updates").json() == []
    all_items = client.get("/api/agents/project-memory-updates", params={"status": ""}).json()
    assert all_items[0]["status"] == "rejected"


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


def test_agent_runtime_context_does_not_inject_tool_policy_summary(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="能力管家")
    agent_directory_service.update_agent_instance(
        agent["agentId"],
        tool_policy={
            "allowedTools": [
                "agent_message_tool",
                "research_knowledge_query_tool",
                "read_memory_tool",
                "get_memory_summary_tool",
                "read_dynamic_prompt_tool",
            ],
            "preferredTools": ["read_memory_tool", "research_knowledge_query_tool"],
        },
    )

    context_block = agent_directory_service.build_agent_runtime_context_block(agent["agentId"])

    assert "ToolPolicy:" not in context_block
    assert "visible=agent_message_tool, research_knowledge_query_tool" not in context_block
    assert "configuredUnavailableCount=3" not in context_block
    assert "agent_message_tool" not in context_block
    assert "research_knowledge_query_tool" not in context_block
    assert "read_memory_tool" not in context_block
    assert "get_memory_summary_tool" not in context_block
    assert "read_dynamic_prompt_tool" not in context_block
    assert "preferred=research_knowledge_query_tool" not in context_block


def test_repair_agent_directory_creates_protected_knowledge_steward_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    state = agent_directory_service.repair_agent_directory()
    agents = {
        item["agentId"]: item
        for item in state["agents"]
        if isinstance(item, dict)
    }
    steward = agent_directory_service.get_agent(agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID)

    assert agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID in agents
    assert steward["roleKey"] == "knowledge_steward"
    assert steward["primaryMode"] == "general"
    assert steward["directSessionId"] == "agent-knowledge-steward-direct"
    assert steward["toolPolicyId"] == "tool-knowledge-steward"
    assert steward["memoryPolicyId"] == "memory-knowledge-steward"
    assert steward["metadata"]["systemRole"] == "knowledge_steward"
    assert steward["metadata"]["protected"] is True
    assert steward["metadata"]["permissionBoundary"] == "proposal_and_rating_suggestion_only"
    assert steward["metadata"]["managedDomain"] == "team_knowledge"
    assert "维护团队知识库质量" in steward["taskProfile"]["mission"]
    assert "直接应用正式知识" in steward["taskProfile"]["avoidTasks"]
    assert "knowledge_governance" in steward["taskProfile"]["taskTypes"]

    tool_policy = steward["toolPolicy"]
    assert tool_policy["allowedTools"] == [
        "agent_message_tool",
        "knowledge_query_tool",
        "knowledge_proposal_tool",
        "knowledge_ingestion_tool",
        "knowledge_governance_tasks_tool",
        "knowledge_operations_health_tool",
        "knowledge_governance_plan_tool",
        "knowledge_steward_recommendations_tool",
        "knowledge_steward_workbench_tool",
        "knowledge_rating_suggestion_tool",
    ]
    assert tool_policy["preferredTools"] == [
        "knowledge_governance_tasks_tool",
        "knowledge_operations_health_tool",
        "knowledge_governance_plan_tool",
        "knowledge_steward_workbench_tool",
        "knowledge_steward_recommendations_tool",
        "knowledge_query_tool",
        "knowledge_rating_suggestion_tool",
    ]
    assert tool_policy["networkAccess"] == "none"
    assert tool_policy["mutationAccess"] == "restricted"
    assert tool_policy["maxCallsPerTurn"] == 12
    assert "research_proposal_apply_tool" not in tool_policy["allowedTools"]
    assert "cli_tool" not in tool_policy["allowedTools"]
    assert "apply_patch_tool" not in tool_policy["allowedTools"]

    memory_policy = steward["memoryPolicy"]
    assert memory_policy["readSharedGroups"] == ["project"]
    assert memory_policy["writeSharedGroups"] == []
    assert memory_policy["readKnowledgeBaseIds"] == []
    assert memory_policy["proposeKnowledgeBaseIds"] == []
    assert memory_policy["reviewKnowledgeBaseIds"] == []
    assert memory_policy["rateKnowledgeBaseIds"] == []

    context_block = agent_directory_service.build_agent_runtime_context_block(steward["agentId"])
    assert "knowledge_governance" in context_block
    assert "Knowledge bodies are tool-readable only" in context_block
    assert "ToolPolicy: tool-knowledge-steward" not in context_block
    assert "knowledge_governance_tasks_tool" not in context_block
    assert "research_proposal_apply_tool" not in context_block


def test_knowledge_steward_agent_is_archive_protected(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    steward = agent_directory_service.get_agent(agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID)

    response = client.delete(f"/api/agents/{steward['agentId']}")

    assert response.status_code == 422
    assert "Protected core Agent" in response.json()["detail"]
    assert agent_directory_service.get_agent(steward["agentId"])["status"] == "active"


def test_repair_agent_directory_logs_knowledge_steward_creation(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    agent_directory_service.repair_agent_directory()

    event = next(
        (
            item
            for item in recorded_events
            if item[0][:3] == ("agent_directory", "agent", "agent.knowledge_steward.repaired")
        ),
        None,
    )
    assert event is not None
    assert event[1]["outcome"] == "created"
    assert event[1]["fields"]["agentId"] == agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    assert event[1]["fields"]["toolPolicyId"] == "tool-knowledge-steward"
    assert event[1]["fields"]["memoryPolicyId"] == "memory-knowledge-steward"
    assert event[1]["fields"]["permissionBoundary"] == "proposal_and_rating_suggestion_only"
    assert "agent" in event[1]["fields"]["repairedFields"]


def test_agent_patch_persona_profile_updates_api_context_and_logs(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    agent = agent_directory_service.create_agent_instance(
        display_name="人物 Agent",
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
    )

    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "personaProfile": {
                "gender": "女",
                "age": "32",
                "pronouns": "她",
                "personality": "冷静、细致，优先拆风险。",
                "communicationStyle": "直接给结论，再补证据。",
                "background": "长期负责科研团队方法论设计。",
                "expertise": ["团队设计", "统计评审", "团队设计"],
                "collaborationPreference": "偏好先明确边界再分工。",
                "identityNotes": "供顾问 Agent 招人设计时参考。",
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["personaProfile"]["gender"] == "女"
    assert payload["personaProfile"]["age"] == "32"
    assert payload["personaProfile"]["expertise"] == ["团队设计", "统计评审"]
    assert payload["metadata"]["personaProfile"]["identityNotes"] == "供顾问 Agent 招人设计时参考。"
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    workspace_agent = next(item for item in workspace["agents"] if item["agentId"] == agent["agentId"])
    assert workspace_agent["personaProfile"]["communicationStyle"] == "直接给结论，再补证据。"
    context_block = agent_directory_service.build_agent_runtime_context_block(agent["agentId"])
    assert "AgentPersonaProfile:" in context_block
    assert "Gender: 女" in context_block
    assert "Expertise: 团队设计, 统计评审" in context_block
    assert "do not use age/gender as capability" in context_block
    assert any(
        event[0][:3] == ("agent_directory", "persona_profile", "agent.persona_profile.updated")
        and event[1]["fields"]["hasGender"] is True
        and event[1]["fields"]["hasAge"] is True
        and event[1]["fields"]["expertiseCount"] == 2
        for event in recorded_events
    )


def test_agent_patch_task_profile_updates_api_context_and_logs(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    agent = agent_directory_service.create_agent_instance(
        display_name="任务 Agent",
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
    )

    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "taskProfile": {
                "mission": "负责把科研问题收敛成可执行任务。",
                "taskTypes": ["文献审查", "实验设计", "文献审查"],
                "responsibilities": "拆解问题\n标注证据缺口",
                "preferredTasks": "适合处理边界清晰、需要证据链的任务。",
                "avoidTasks": "不负责凭空推荐成员或自动调度。",
                "successCriteria": "输出可验收的任务边界和证据要求。",
                "deliverables": "任务清单、风险列表、交接摘要。",
                "constraints": "不越过 AgentDirectory 的事实来源。",
                "handoffNotes": "需要交给顾问 Agent 时保留候选理由。",
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["taskProfile"]["mission"] == "负责把科研问题收敛成可执行任务。"
    assert payload["taskProfile"]["taskTypes"] == ["文献审查", "实验设计"]
    assert payload["metadata"]["taskProfile"]["successCriteria"] == "输出可验收的任务边界和证据要求。"
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    workspace_agent = next(item for item in workspace["agents"] if item["agentId"] == agent["agentId"])
    assert workspace_agent["taskProfile"]["preferredTasks"] == "适合处理边界清晰、需要证据链的任务。"
    context_block = agent_directory_service.build_agent_runtime_context_block(agent["agentId"])
    assert "AgentTaskProfile:" in context_block
    assert "TaskTypes: 文献审查, 实验设计" in context_block
    assert "SuccessCriteria: 输出可验收的任务边界和证据要求。" in context_block
    assert "do not use it as an automatic permission, routing, or scheduling gate" in context_block
    assert any(
        event[0][:3] == ("agent_directory", "task_profile", "agent.task_profile.updated")
        and event[1]["fields"]["hasMission"] is True
        and event[1]["fields"]["hasSuccessCriteria"] is True
        and event[1]["fields"]["taskTypeCount"] == 2
        for event in recorded_events
    )


def test_work_session_agent_ignores_persona_and_task_profiles(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    agent = agent_directory_service.create_agent_instance(
        display_name="会话实现 Agent",
        primary_mode="chat",
        role_key="",
        prompt_template_id="prompt-chat-default",
    )

    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "personaProfile": {"gender": "女", "communicationStyle": "不要暴露到会话 Agent。"},
            "taskProfile": {"mission": "不要暴露到会话 Agent。", "taskTypes": ["research"]},
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["personaProfile"] == {}
    assert payload["taskProfile"] == {}
    assert "personaProfile" not in payload["metadata"]
    assert "taskProfile" not in payload["metadata"]
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    workspace_agent = next(item for item in workspace["agents"] if item["agentId"] == agent["agentId"])
    assert workspace_agent["agentBoundary"]["type"] == "work_session"
    assert workspace_agent["personaProfile"] == {}
    assert workspace_agent["taskProfile"] == {}
    assert "AgentPersonaProfile:" not in agent_directory_service.build_agent_runtime_context_block(agent["agentId"])
    stored = json.loads((tmp_path / "workspace" / "agents" / "agents.json").read_text(encoding="utf-8"))
    stored_agent = next(item for item in stored["agents"] if item["agentId"] == agent["agentId"])
    assert "personaProfile" not in stored_agent["metadata"]
    assert "taskProfile" not in stored_agent["metadata"]
    assert not any(event[0][:3] == ("agent_directory", "persona_profile", "agent.persona_profile.updated") for event in recorded_events)
    assert not any(event[0][:3] == ("agent_directory", "task_profile", "agent.task_profile.updated") for event in recorded_events)


def test_agent_mode_membership_api_updates_selected_agent_bindings(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    monkeypatch.setattr(agents_route, "_ensure_config_agent_instances", lambda: None)
    agent = agent_directory_service.create_agent_instance(
        display_name="模式 Agent",
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
    monkeypatch.setattr(agents_route, "_ensure_config_agent_instances", lambda: None)
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
    first_detail = chat_room_service.get_chat_room_detail(first_room["roomId"])
    second_detail = chat_room_service.get_chat_room_detail(second_room["roomId"])
    assert alpha["agentId"] not in {participant["agentId"] for participant in first_detail["participants"]}
    assert alpha["agentId"] in {participant["agentId"] for participant in second_detail["participants"]}
    assert beta["agentId"] in {participant["agentId"] for participant in first_detail["participants"]}


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
