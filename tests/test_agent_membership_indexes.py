import json
from types import SimpleNamespace

import pytest

from tests.test_agent_config_workspace_service import (
    ProviderConfig,
    _fake_config_workspace,
    _mark_config_agent_instances_present,
    _raw_mode_binding,
    _seed_supervised_fixed_role_agent,
    _use_tmp_project_root,
    agent_bulk_delete_service,
    agent_config_workspace_service,
    agent_directory_service,
    agent_mode_binding_service,
    agent_tool_governance_service,
    agents_route,
    chat_room_service,
    client,
    config_package,
    config_service,
    context_engine,
    prompt_template_service,
    self_evolution_control_service,
    session_service,
    supervised_agent_service,
    team_service,
)

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
    assert steward["promptTemplateId"] == "prompt-knowledge-steward"
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
    required_allowed_tools = {
        "agent_message_tool",
        "skill_library_search_tool",
        "unified_memory_search_tool",
        "knowledge_proposal_tool",
        "knowledge_ingestion_tool",
        "knowledge_governance_tasks_tool",
        "knowledge_operations_health_tool",
        "knowledge_governance_plan_tool",
        "knowledge_steward_recommendations_tool",
        "knowledge_steward_workbench_tool",
        "knowledge_rating_suggestion_tool",
    }
    required_preferred_tools = {
        "knowledge_governance_tasks_tool",
        "knowledge_operations_health_tool",
        "knowledge_governance_plan_tool",
        "knowledge_steward_workbench_tool",
        "knowledge_steward_recommendations_tool",
        "skill_library_search_tool",
        "unified_memory_search_tool",
        "knowledge_rating_suggestion_tool",
    }
    assert required_allowed_tools.issubset(set(tool_policy["allowedTools"]))
    assert required_preferred_tools.issubset(set(tool_policy["preferredTools"]))
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


def test_repair_agent_directory_applies_challenge_cup_research_tool_profiles(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    cases = {
        "challenge_cup_data_discovery": [
            "agent_message_tool",
            "research_knowledge_query_tool",
            "web_search_tool",
        ],
        "challenge_cup_source_acquisition": [
            "agent_message_tool",
            "research_knowledge_query_tool",
            "web_search_tool",
            "web_fetch_tool",
        ],
        "challenge_cup_content_extraction": [
            "agent_message_tool",
            "research_knowledge_query_tool",
            "web_fetch_tool",
        ],
        "challenge_cup_source_quality": [
            "agent_message_tool",
            "research_knowledge_query_tool",
            "web_search_tool",
            "web_fetch_tool",
        ],
    }
    expected_prompt_templates = {
        "challenge_cup_data_discovery": "prompt-challenge-cup-data-discovery",
        "challenge_cup_source_acquisition": "prompt-challenge-cup-source-acquisition",
        "challenge_cup_content_extraction": "prompt-challenge-cup-content-extraction",
        "challenge_cup_source_quality": "prompt-challenge-cup-source-quality",
    }
    created_ids = {
        role_key: agent_directory_service.create_agent_instance(
            display_name=role_key,
            primary_mode="research",
            role_key=role_key,
            prompt_template_id="prompt-chat-default",
            metadata={
                "personaProfile": {
                    "personality": "细致、证据优先，避免把未验证来源当成结论。",
                    "communicationStyle": "先列可用证据和不确定性，再给研究建议。",
                    "collaborationPreference": "围绕来源、证据、引用和结论边界与研究团队协作。",
                },
                "taskProfile": {
                    "responsibilities": "阅读资料；提取关键证据；标注来源质量；把发现交给研究组织或团队成员复核。",
                    "preferredTasks": "文献阅读、来源比对、证据摘录和研究问题拆解。",
                    "constraints": "保留来源边界，遵守研究工具和知识库权限。",
                },
            },
        )["agentId"]
        for role_key in cases
    }
    coordinator_id = agent_directory_service.create_agent_instance(
        display_name="challenge_cup_coordinator",
        primary_mode="chat",
        role_key="challenge_cup_coordinator",
        prompt_template_id="prompt-chat-default",
        metadata={
            "taskProfile": {
                "taskTypes": ["team_coordination", "research_workflow_handoff"],
            },
        },
    )["agentId"]

    agent_directory_service.repair_agent_directory()

    for role_key, expected_tools in cases.items():
        agent = agent_directory_service.get_agent(created_ids[role_key])
        assert agent["promptTemplateId"] == expected_prompt_templates[role_key]
        assert "挑战杯" in agent["personaProfile"]["background"]
        assert "challenge_cup" in agent["taskProfile"]["taskTypes"]
        assert agent["toolPolicy"]["allowedTools"] == expected_tools
        assert agent["toolPolicy"]["writeScopes"] == []
        assert agent["toolPolicy"]["networkAccess"] == "controlled"
        assert agent["toolPolicy"]["mutationAccess"] == "none"
        assert "cli_tool" not in agent["toolPolicy"]["allowedTools"]
        assert "apply_patch_tool" not in agent["toolPolicy"]["allowedTools"]
    coordinator = agent_directory_service.get_agent(coordinator_id)
    assert coordinator["promptTemplateId"] == "prompt-challenge-cup-coordinator"
    assert coordinator["personaProfile"]["communicationStyle"] == "先给阶段判断，再列证据位置、角色分工和用户下一步。"
    assert "不要声称已启动资料搜集" in coordinator["taskProfile"]["avoidTasks"]


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
    assert modes["chat"]["defaultAgentId"] != agent["agentId"]
    assert agent["agentId"] not in modes["chat"]["availableAgentIds"]
    assert agent["agentId"] in modes["research"]["pool"]
    assert modes["supervised_evolution"]["slots"]["reviewer"] != agent["agentId"]


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


def test_agent_config_workspace_collapses_duplicate_team_name_indexes(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    first_agent = agent_directory_service.create_agent_instance(display_name="重复团队成员 A")
    second_agent = agent_directory_service.create_agent_instance(display_name="重复团队成员 B")
    first_team = team_service.create_team(
        name="Duplicate Team",
        members=[{"agentId": first_agent["agentId"], "role": "lead"}],
    )
    second_team = team_service.create_team(
        name="Duplicate Team",
        members=[{"agentId": second_agent["agentId"], "role": "member"}],
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()
    duplicate_indexes = [
        item for item in payload["teamIndexes"]
        if item.get("label") == "Duplicate Team"
    ]

    assert len(duplicate_indexes) == 1
    index = duplicate_indexes[0]
    assert index["source"] == "duplicate_team_name"
    assert index["duplicateTeamCount"] == 2
    assert set(index["duplicateTeamIds"]) == {first_team["teamId"], second_team["teamId"]}
    assert set(index["agentIds"]) == {first_agent["agentId"], second_agent["agentId"]}
    assert any(item["code"] == "duplicate_team_name" for item in payload["health"]["issues"])
