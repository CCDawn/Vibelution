import json
import threading

import pytest

from core.infrastructure import developer_sandbox
from core.web.services import (
    agent_bulk_delete_service,
    agent_config_workspace_service,
    agent_directory_service,
    agent_mode_binding_service,
    chat_room_service,
    project_agent_bus_service,
    session_service,
    team_service,
)
from tests.helpers.system_agent_state import (
    _evolution_system_agent_payloads,
    _seed_ai_search_system_team_ready,
    _seed_system_team_bootstrap_ready,
)


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_bulk_delete_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)

    def list_direct_agent_sessions(*args, **kwargs):
        sessions = []
        for agent in agent_directory_service.list_agents(include_archived=False):
            session_id = str(agent.get("directSessionId") or "").strip()
            if not session_id:
                continue
            sessions.append(
                {
                    "id": session_id,
                    "title": str(agent.get("displayName") or session_id),
                    "agentId": str(agent.get("agentId") or ""),
                    "agentCode": str(agent.get("agentCode") or ""),
                    "workspacePath": str(agent.get("workspacePath") or ""),
                    "status": "active",
                    "updatedAt": "2026-05-29T00:00:00Z",
                }
            )
        return sessions

    monkeypatch.setattr(session_service, "list_sessions", list_direct_agent_sessions)


def _agent_config_snapshot(agent: dict) -> dict:
    keys = (
        "displayName",
        "primaryMode",
        "roleKey",
        "llmBindings",
        "contextCompressionPolicy",
        "promptTemplateId",
        "toolPolicyId",
        "toolPolicy",
        "memoryPolicyId",
        "memoryPolicy",
        "permissionPreset",
        "personaProfile",
        "taskProfile",
        "metadata",
        "configSchemaVersion",
        "configRevision",
        "configHash",
    )
    return {key: agent.get(key) for key in keys}


def test_create_team_with_active_agent_writes_default_canvas(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")

    team = team_service.create_team(
        name="科研协作组",
        purpose="组织科研 agent",
        members=[{"agentId": agent["agentId"], "role": "lead"}],
    )

    assert team["teamId"] == "team"
    assert team["teamKind"] == "custom"
    assert team["teamCategory"] == "自定义团队"
    assert team["teamSource"] == "manual"
    assert team["teamTemplateId"] == ""
    assert team["members"][0]["agentId"] == agent["agentId"]
    assert team["canvas"]["canvasKind"] == team_service.CANVAS_KIND
    assert team["canvas"]["nodes"][0]["agentId"] == agent["agentId"]
    assert team["linkedChatRoomId"]
    assert team["linkedChatRoom"]["participantCount"] == 1
    assert team["linkedChatRoom"]["purpose"] == "discussion"
    assert team["conversation"]["status"] == "linked"
    assert team["conversation"]["memberAgentIds"] == [agent["agentId"]]
    assert team["conversation"]["roomAgentIds"] == [agent["agentId"]]
    assert chat_room_service.get_chat_room_detail(team["linkedChatRoomId"])["participants"][0]["agentId"] == agent["agentId"]
    assert chat_room_service.get_chat_room_detail(team["linkedChatRoomId"])["config"]["teamKind"] == "custom"
    assert team_service.list_teams()["summary"]["activeTeamCount"] == 1


def test_create_empty_team_still_links_empty_team_chat_room(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    team = team_service.create_team(name="医疗问诊", purpose="进行医学学术")

    assert team["memberCount"] == 0
    assert team["linkedChatRoomId"]
    assert team["linkedChatRoom"]["participantCount"] == 0
    assert team["conversation"]["status"] == "linked"
    room = chat_room_service.get_chat_room_detail(team["linkedChatRoomId"])
    assert room["participants"] == []
    assert room["config"]["source"] == "team"
    assert room["config"]["teamId"] == team["teamId"]


def test_team_chat_room_participants_keep_team_role_context(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Alpha",
        direct_session_id="session-alpha",
        metadata={"responsibilities": ["跟踪关键决策", "提醒执行风险"]},
    )

    team = team_service.create_team(
        name="科研协作组",
        purpose="组织科研 agent",
        members=[{"agentId": agent["agentId"], "role": "research_lead", "purpose": "科研负责人"}],
    )

    participant = chat_room_service.get_chat_room_detail(team["linkedChatRoomId"])["participants"][0]
    assert participant["teamId"] == team["teamId"]
    assert participant["teamName"] == "科研协作组"
    assert participant["teamPurpose"] == "组织科研 agent"
    assert participant["teamRole"] == "research_lead"
    assert participant["teamMemberPurpose"] == "科研负责人"
    assert participant["teamResponsibilities"] == ["跟踪关键决策", "提醒执行风险"]


def test_team_members_keep_structured_responsibilities(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")

    team = team_service.create_team(
        name="职责团队",
        members=[
            {
                "agentId": agent["agentId"],
                "role": "主持",
                "purpose": "短职责",
                "responsibilities": ["这里放较长的岗位职责，供提示词和展开详情使用。"],
            }
        ],
    )

    assert team["members"][0]["purpose"] == "短职责"
    assert team["members"][0]["responsibilities"] == ["这里放较长的岗位职责，供提示词和展开详情使用。"]
    participant = chat_room_service.get_chat_room_detail(team["linkedChatRoomId"])["participants"][0]
    assert participant["teamMemberPurpose"] == "短职责"
    assert participant["teamResponsibilities"] == ["这里放较长的岗位职责，供提示词和展开详情使用。"]


def test_ensure_research_team_from_organization_uses_stable_team_id(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(
        display_name="Alpha",
        direct_session_id="session-alpha",
        metadata={"teamMembership": {"responsibilities": ["发现候选来源", "记录覆盖缺口"]}},
    )
    beta = agent_directory_service.create_agent_instance(
        display_name="Beta",
        direct_session_id="session-beta",
        primary_mode="research",
        metadata={"taskProfile": {"responsibilities": "审查证据；输出返工建议"}},
    )
    organization = {
        "updatedAt": "2026-05-29T00:00:00Z",
        "agents": [
            {"nodeId": "alpha-node", "agentId": alpha["agentId"], "displayName": "Alpha", "role": "lead", "status": "active", "x": 240, "y": 160},
            {"nodeId": "beta-node", "agentId": beta["agentId"], "displayName": "Beta", "role": "reviewer", "status": "active", "x": 520, "y": 260},
        ],
        "edges": [
            {"edgeId": "edge-alpha-beta", "fromAgentId": alpha["agentId"], "toAgentId": beta["agentId"], "label": "同步证据", "status": "active"}
        ],
    }

    first = team_service.ensure_research_team_from_organization(organization)
    second = team_service.ensure_research_team_from_organization(organization)
    canvas = team_service.get_team_canvas("research-team")
    teams = team_service.list_teams()["teams"]

    assert first["teamId"] == "research-team"
    assert second["teamId"] == "research-team"
    assert second["name"] == "挑战杯ai科研团队"
    assert second["teamKind"] == "research"
    assert second["teamCategory"] == "科研组织团队"
    assert second["teamSource"] == "research_organization"
    assert second["linkedChatRoom"]["purpose"] == "research_coordination"
    assert [team["teamId"] for team in teams] == ["research-team"]
    assert first["linkedChatRoomId"] == second["linkedChatRoomId"]
    assert team_service.list_teams()["summary"]["activeTeamCount"] == 1
    assert len(chat_room_service.list_chat_rooms()) == 1
    assert chat_room_service.get_chat_room_detail(second["linkedChatRoomId"])["config"]["teamCategory"] == "科研组织团队"
    assert [member["agentId"] for member in second["members"]] == [alpha["agentId"], beta["agentId"]]
    assert second["members"][0]["responsibilities"] == ["发现候选来源", "记录覆盖缺口"]
    assert second["members"][1]["responsibilities"] == ["审查证据", "输出返工建议"]
    assert {node["agentId"] for node in canvas["nodes"]} == {alpha["agentId"], beta["agentId"]}
    assert {node["id"] for node in canvas["nodes"]} == {alpha["agentId"], beta["agentId"]}
    assert next(node for node in canvas["nodes"] if node["agentId"] == alpha["agentId"])["responsibilities"] == ["发现候选来源", "记录覆盖缺口"]
    assert canvas["edges"] == [
        {
            "id": "edge-alpha-beta",
            "source": alpha["agentId"],
            "target": beta["agentId"],
            "label": "同步证据",
            "type": "communication",
        },
    ]


def test_research_team_sync_preserves_agent_instance_configuration(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    finder = agent_directory_service.create_agent_instance(display_name="Finder", direct_session_id="session-finder")
    extractor = agent_directory_service.create_agent_instance(display_name="Extractor", direct_session_id="session-extractor")
    mapper = agent_directory_service.create_agent_instance(display_name="Mapper", direct_session_id="session-mapper")
    organization = {
        "updatedAt": "2026-05-29T00:00:00Z",
        "agents": [
            {"nodeId": "finder", "agentId": finder["agentId"], "displayName": "Finder", "role": "source_finder", "status": "active"},
            {"nodeId": "extractor", "agentId": extractor["agentId"], "displayName": "Extractor", "role": "source_extractor", "status": "active"},
            {"nodeId": "mapper", "agentId": mapper["agentId"], "displayName": "Mapper", "role": "source_relation_mapper", "status": "active"},
        ],
        "edges": [],
    }
    before = {
        agent["agentId"]: _agent_config_snapshot(
            agent_directory_service.get_agent(agent["agentId"])
        )
        for agent in (finder, extractor, mapper)
    }

    team = team_service.ensure_research_team_from_organization(organization)

    assert [member["role"] for member in team["members"]] == ["source_finder", "source_extractor", "source_relation_mapper"]
    for agent_id, expected in before.items():
        assert _agent_config_snapshot(agent_directory_service.get_agent(agent_id)) == expected


def test_research_organization_sync_does_not_overwrite_existing_challenge_cup_team(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    initial = team_service.bootstrap_challenge_cup_research_team()
    before_members = [dict(member) for member in initial["team"]["members"]]
    legacy_agent = agent_directory_service.create_agent_instance(
        display_name="Legacy organization agent",
        direct_session_id="session-legacy-organization",
    )
    organization = {
        "updatedAt": "2026-05-29T00:00:00Z",
        "agents": [
            {
                "nodeId": "legacy",
                "agentId": legacy_agent["agentId"],
                "displayName": "Legacy organization agent",
                "role": "legacy_research_role",
                "status": "active",
            }
        ],
        "edges": [],
    }

    result = team_service.ensure_research_team_from_organization(organization)

    assert result["teamId"] == team_service.CHALLENGE_CUP_RESEARCH_TEAM_ID
    assert result["members"] == before_members


def test_challenge_cup_agent_repair_preserves_agent_instance_configuration(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    initial = team_service.bootstrap_challenge_cup_research_team()
    agent_id = initial["team"]["members"][0]["agentId"]
    current = agent_directory_service.get_agent(agent_id)
    assert current is not None
    agent_directory_service.update_agent_instance(
        agent_id,
        display_name="User-owned Challenge Cup name",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="research",
        role_key="user_owned_challenge_role",
        prompt_template_id="prompt-chat-default",
        permission_preset="request_approval",
        tool_policy={**current["toolPolicy"], "maxCallsPerTurn": 5},
        persona_profile={"personality": "user-owned persona"},
        task_profile={"mission": "user-owned task"},
    )
    before = _agent_config_snapshot(agent_directory_service.get_agent(agent_id))
    original_model_ref_repair = agent_directory_service._repair_agent_llm_binding_model_refs

    def reject_challenge_cup_model_repair(agent, **kwargs):
        if str(agent.get("agentId") or "").strip() == agent_id:
            raise AssertionError("generic model repair must not inspect Challenge Cup Agent config")
        return original_model_ref_repair(agent, **kwargs)

    monkeypatch.setattr(
        agent_directory_service,
        "_repair_agent_llm_binding_model_refs",
        reject_challenge_cup_model_repair,
    )

    agent_directory_service.repair_agent_directory()

    after = _agent_config_snapshot(agent_directory_service.get_agent(agent_id))
    assert after == before


def test_generic_team_repair_preserves_existing_challenge_cup_membership(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    initial = team_service.bootstrap_challenge_cup_research_team()
    team = dict(initial["team"])
    before_members = [dict(member) for member in team["members"]]
    team["members"] = [
        {**member, "agentStatus": "stale"}
        for member in team["members"]
    ]
    state = {
        "schemaVersion": team_service.SCHEMA_VERSION,
        "updatedAt": team.get("updatedAt") or "",
        "teams": [team],
    }

    changed = team_service._repair_index_state(
        state,
        agent_refs={"by_id": {}, "active_by_id": {}},
    )

    assert isinstance(changed, bool)
    assert state["teams"][0]["members"] == [
        {**member, "agentStatus": "stale"}
        for member in before_members
    ]


def test_research_team_read_repair_cannot_override_agent_instance_configuration(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    finder = agent_directory_service.create_agent_instance(display_name="Finder", direct_session_id="session-finder")
    team_service.create_team(
        name="挑战杯ai科研团队",
        purpose="科研协作",
        members=[
            {
                "agentId": finder["agentId"],
                "memberId": "finder",
                "role": "source_finder",
                "purpose": "Finder",
            }
        ],
        team_kind="research",
        team_source="research_organization",
    )
    current = agent_directory_service.get_agent(finder["agentId"])
    agent_directory_service.update_agent_instance(
        finder["agentId"],
        llm_bindings={"dialogue": {"modelId": "relay_openai/gpt-5.6-luna"}},
        primary_mode="research",
        role_key="user_owned_role",
        prompt_template_id="prompt-chat-default",
        permission_preset="request_approval",
        tool_policy={**current["toolPolicy"], "maxCallsPerTurn": 5},
        persona_profile={"personality": "user-owned persona"},
        task_profile={"mission": "user-owned task"},
    )
    before = _agent_config_snapshot(
        agent_directory_service.get_agent(finder["agentId"])
    )

    team_service.list_teams()

    after = _agent_config_snapshot(
        agent_directory_service.get_agent(finder["agentId"])
    )
    assert after == before


def test_challenge_cup_bootstrap_materializes_six_agent_assets_with_agent_owned_config(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    creation_default = session_service.default_session_llm_bindings()

    result = team_service.bootstrap_challenge_cup_research_team()
    team = result["team"]

    assert result["created"] is True
    assert result["memberCount"] == 6
    assert result["agentCount"] == 6
    assert len({member["agentId"] for member in team["members"]}) == 6
    assert "activeBinding" not in team
    assert "legacyBindings" not in team
    assert "roleMigration" not in team

    for member in team["members"]:
        agent = agent_directory_service.get_agent(member["agentId"])
        assert agent is not None
        assert agent["roleKey"] == member["role"]
        assert agent["promptTemplateId"] == (
            agent_directory_service.CHALLENGE_CUP_ROLE_PROMPT_TEMPLATE_IDS[
                member["role"]
            ]
        )
        assert agent["llmBindings"] == creation_default
        assert agent["metadata"]["configSurface"] == "agent_config"
        assert agent["metadata"]["challengeCupTeamRole"] == member["role"]


def test_challenge_cup_bootstrap_never_reconciles_existing_agent_configuration(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    initial = team_service.bootstrap_challenge_cup_research_team()
    member = next(
        item
        for item in initial["team"]["members"]
        if item["role"] == "challenge_cup_search"
    )
    custom_policy = {
        **agent_directory_service.default_research_source_tool_policy(
            f"tool-{member['agentId']}",
            role_key="challenge_cup_search",
        ),
        "maxCallsPerTurn": 3,
    }
    agent_directory_service.update_agent_instance(
        member["agentId"],
        llm_bindings={"dialogue": {"modelId": "relay_openai/gpt-5.6-luna"}},
        prompt_template_id="prompt-chat-default",
        permission_preset="request_approval",
        tool_policy=custom_policy,
        persona_profile={"personality": "user-owned persona"},
        task_profile={"mission": "user-owned task"},
    )

    before = agent_directory_service.get_agent(member["agentId"])
    second = team_service.bootstrap_challenge_cup_research_team()
    agent_directory_service.repair_agent_directory()
    after = agent_directory_service.get_agent(member["agentId"])

    assert second["created"] is False
    assert after["llmBindings"] == before["llmBindings"]
    assert after["promptTemplateId"] == "prompt-chat-default"
    assert after["permissionPreset"] == "request_approval"
    assert after["toolPolicy"] == before["toolPolicy"]
    assert after["metadata"]["personaProfile"] == before["metadata"]["personaProfile"]
    assert after["metadata"]["taskProfile"] == before["metadata"]["taskProfile"]


def test_knowledge_expansion_team_agents_seed_complete_team(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    result = team_service.ensure_knowledge_expansion_team_agents(purge_stale=True)
    team = result["team"]

    assert result["teamId"] == "knowledge-expansion-team"
    assert team["teamKind"] == "knowledge_expansion"
    assert team["teamSource"] == "knowledge_expansion"
    assert team["linkedChatRoom"]["purpose"] == "knowledge_expansion"
    assert [member["role"] for member in team["members"]] == [
        "source_finder",
        "source_extractor",
        "source_relation_mapper",
        "source_ingestor",
    ]
    source_member = next(member for member in team["members"] if member["role"] == "source_finder")
    ingestor_member = next(member for member in team["members"] if member["role"] == "source_ingestor")
    source_agent = agent_directory_service.get_agent(source_member["agentId"])
    ingestor_agent = agent_directory_service.get_agent(ingestor_member["agentId"])

    assert source_agent["roleKey"] == "source_finder"
    assert source_agent["metadata"]["knowledgeExpansionTeamId"] == "knowledge-expansion-team"
    assert source_agent["metadata"]["knowledgeExpansionTeamRole"] == "source_finder"
    assert source_agent["metadata"]["conversationIndexVisibility"] == (
        agent_directory_service.CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE
    )
    assert source_agent["metadata"]["showInSessionIndex"] is False
    assert source_agent["directSessionId"]
    assert session_service.get_session_detail(source_agent["directSessionId"])
    assert ingestor_agent["roleKey"] == "source_ingestor"
    assert ingestor_agent["metadata"]["knowledgeExpansionTeamRole"] == "source_ingestor"

    source_policy = agent_directory_service.resolve_tool_policy_for_agent(source_agent["agentId"])
    ingestor_policy = agent_directory_service.resolve_tool_policy_for_agent(ingestor_agent["agentId"])
    assert "paper_search_tool" in source_policy["allowedTools"]
    assert "knowledge_ingestion_tool" not in source_policy["allowedTools"]
    assert "knowledge_ingestion_tool" in ingestor_policy["allowedTools"]
    assert "knowledge_proposal_tool" in ingestor_policy["allowedTools"]

    canvas = team_service.get_team_canvas("knowledge-expansion-team")
    assert {node["agentId"] for node in canvas["nodes"]} == {member["agentId"] for member in team["members"]}
    assert team_service.knowledge_expansion_team_agents_need_repair() is False


def test_system_teams_do_not_embed_global_knowledge_steward_as_member(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    research = team_service.bootstrap_challenge_cup_research_team()["team"]
    expansion = team_service.ensure_knowledge_expansion_team_agents(purge_stale=True)["team"]
    global_steward = agent_directory_service.get_agent(agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID)

    assert global_steward
    assert global_steward["roleKey"] == agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY
    assert "knowledge_steward" not in {member["role"] for member in research["members"]}
    assert "knowledge_steward" not in {member["role"] for member in expansion["members"]}
    assert all(member["agentId"] != global_steward["agentId"] for member in research["members"])
    assert all(member["agentId"] != global_steward["agentId"] for member in expansion["members"])

    research_canvas = team_service.get_team_canvas("research-team")
    expansion_canvas = team_service.get_team_canvas("knowledge-expansion-team")
    assert research_canvas["validation"]["valid"] is True
    assert expansion_canvas["validation"]["valid"] is True
    assert all(issue["code"] != "agent_team_conflict" for issue in research_canvas["validation"]["issues"])
    assert all(issue["code"] != "agent_team_conflict" for issue in expansion_canvas["validation"]["issues"])


def test_challenge_cup_research_team_keeps_global_knowledge_steward_separate(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent_directory_service.repair_agent_directory()
    global_steward = agent_directory_service.get_agent(
        agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    )

    team = team_service.bootstrap_challenge_cup_research_team()["team"]

    assert all(member["role"] != "knowledge_steward" for member in team["members"])
    assert all(
        member["agentId"] != global_steward["agentId"]
        for member in team["members"]
    )


def test_challenge_cup_canvas_projects_members_without_writing_membership(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.bootstrap_challenge_cup_research_team()["team"]
    members_before = [
        (member["role"], member["agentId"])
        for member in team["members"]
    ]
    canvas = team_service.get_team_canvas(team["teamId"])
    first, second = canvas["nodes"][:2]
    first["agentId"] = second["agentId"]

    saved = team_service.save_team_canvas(team["teamId"], canvas)
    team_after = team_service.get_team(team["teamId"])

    assert [
        (member["role"], member["agentId"])
        for member in team_after["members"]
    ] == members_before
    agent_by_role = dict(members_before)
    assert {
        node["role"]: node["agentId"]
        for node in saved["nodes"]
        if node["role"] in agent_by_role
    } == agent_by_role


def test_challenge_cup_default_canvas_keeps_stage_relationships(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    result = team_service.bootstrap_challenge_cup_research_team()
    canvas = team_service.get_team_canvas(result["teamId"])

    role_by_node_id = {
        node["id"]: node["role"]
        for node in canvas["nodes"]
        if str(node.get("agentId") or "").strip()
    }
    edge_pairs = {
        (role_by_node_id[edge["source"]], role_by_node_id[edge["target"]], edge["type"])
        for edge in canvas["edges"]
        if edge["source"] in role_by_node_id and edge["target"] in role_by_node_id
    }

    assert canvas["validation"]["valid"] is True
    assert set(role_by_node_id.values()) == {
        "challenge_cup_search",
        "challenge_cup_extractor",
        "challenge_cup_knowledge_manager",
        "challenge_cup_execution_steward",
        "challenge_cup_experiment_revision",
        "challenge_cup_evaluator",
    }
    assert ("challenge_cup_search", "challenge_cup_extractor", "reports_to") in edge_pairs
    assert (
        "challenge_cup_knowledge_manager",
        "challenge_cup_experiment_revision",
        "reports_to",
    ) in edge_pairs
    assert (
        "challenge_cup_evaluator",
        "challenge_cup_experiment_revision",
        "communication",
    ) in edge_pairs


def test_challenge_cup_canvas_repairs_missing_projection_edges_only(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.bootstrap_challenge_cup_research_team()["team"]
    agent_config_before = {
        member["agentId"]: _agent_config_snapshot(
            agent_directory_service.get_agent(member["agentId"])
        )
        for member in team["members"]
    }
    canvas_path = team_service._team_canvas_path(team["teamId"])
    raw_canvas = json.loads(canvas_path.read_text(encoding="utf-8"))
    raw_canvas["edges"] = []
    canvas_path.write_text(
        json.dumps(raw_canvas, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    repaired = team_service.get_team_canvas(team["teamId"])

    assert repaired["edges"]
    assert json.loads(canvas_path.read_text(encoding="utf-8"))["edges"] == repaired["edges"]
    for agent_id, expected in agent_config_before.items():
        assert _agent_config_snapshot(agent_directory_service.get_agent(agent_id)) == expected


def test_challenge_cup_existing_team_never_enters_bootstrap_for_member_drift(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    result = team_service.bootstrap_challenge_cup_research_team()
    teams_path = team_service._teams_index_path()
    payload = json.loads(teams_path.read_text(encoding="utf-8"))
    stored_team = next(
        team for team in payload["teams"] if team["teamId"] == result["teamId"]
    )
    stored_team["members"] = stored_team["members"][:-1]
    teams_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    assert team_service.challenge_cup_research_team_missing() is False
    second = team_service.bootstrap_challenge_cup_research_team()

    assert second["created"] is False
    assert len(second["team"]["members"]) == 5


def test_challenge_cup_bootstrap_serializes_first_materialization(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    results: list[dict] = []

    def bootstrap() -> None:
        results.append(team_service.bootstrap_challenge_cup_research_team())

    threads = [threading.Thread(target=bootstrap) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == 2
    assert sum(1 for result in results if result["created"]) == 1
    member_sets = [
        {member["agentId"] for member in result["team"]["members"]}
        for result in results
    ]
    assert member_sets[0] == member_sets[1]
    assert len(member_sets[0]) == 6


def test_challenge_cup_research_team_agents_stay_out_of_ordinary_session_index(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    result = team_service.bootstrap_challenge_cup_research_team()
    finder = next(
        member
        for member in result["team"]["members"]
        if member["role"] == "challenge_cup_search"
    )
    agent = agent_directory_service.get_agent(finder["agentId"])

    assert agent_directory_service.agent_conversation_index_visibility(
        agent,
        hidden_team_member_agent_ids={agent["agentId"]},
    ) == agent_directory_service.CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE
    assert (
        session_service._agent_directory_stub_hidden_from_user_index(
            agent,
            {agent["agentId"]},
        )
        is True
    )


def test_research_team_canvas_separates_reporting_and_communication_edges(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    ceo = agent_directory_service.create_agent_instance(display_name="CEO", direct_session_id="session-ceo")
    advisor = agent_directory_service.create_agent_instance(display_name="Advisor", direct_session_id="session-advisor")
    steward = agent_directory_service.create_agent_instance(display_name="Steward", direct_session_id="session-steward")
    organization = {
        "updatedAt": "2026-05-29T00:00:00Z",
        "agents": [
            {"nodeId": "ceo", "agentId": ceo["agentId"], "displayName": "CEO", "role": "ceo", "status": "active", "x": 120, "y": 120},
            {"nodeId": "advisor", "agentId": advisor["agentId"], "displayName": "Advisor", "role": "organization_advisor", "status": "active", "x": 460, "y": 120},
            {"nodeId": "steward", "agentId": steward["agentId"], "displayName": "Steward", "role": "capability_steward", "status": "active", "x": 800, "y": 120},
        ],
        "edges": [
            {"edgeId": "edge-ceo-advisor", "fromAgentId": ceo["agentId"], "toAgentId": advisor["agentId"], "label": "CEO 下达组织调整任务", "status": "active"},
            {"edgeId": "edge-advisor-ceo", "fromAgentId": advisor["agentId"], "toAgentId": ceo["agentId"], "label": "组织顾问向 CEO 汇报", "status": "active"},
            {"edgeId": "edge-advisor-steward", "fromAgentId": advisor["agentId"], "toAgentId": steward["agentId"], "label": "组织顾问请求能力配置", "status": "active"},
        ],
    }

    team_service.ensure_research_team_from_organization(organization)

    canvas = team_service.get_team_canvas("research-team")
    reporting_edges = [edge for edge in canvas["edges"] if edge["type"] == "reports_to"]
    communication_edges = [edge for edge in canvas["edges"] if edge["type"] == "communication"]
    assert [(edge["source"], edge["target"]) for edge in reporting_edges] == [
        (ceo["agentId"], advisor["agentId"]),
        (ceo["agentId"], steward["agentId"]),
    ]
    assert {edge["id"] for edge in communication_edges} == {"edge-ceo-advisor", "edge-advisor-ceo", "edge-advisor-steward"}


def test_research_team_sync_reuses_existing_team_chat_room(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    organization = {
        "agents": [
            {"nodeId": "alpha-node", "agentId": alpha["agentId"], "displayName": "Alpha", "role": "lead", "status": "active"},
            {"nodeId": "beta-node", "agentId": beta["agentId"], "displayName": "Beta", "role": "reviewer", "status": "active"},
        ],
        "edges": [],
    }
    existing_room = chat_room_service.create_chat_room(
        title="旧科研团队群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
        config={"source": "team", "teamId": "research-team", "teamName": "科研团队"},
    )

    team = team_service.ensure_research_team_from_organization(organization)

    rooms = chat_room_service.list_chat_rooms()
    assert team["linkedChatRoomId"] == existing_room["roomId"]
    assert [room["roomId"] for room in rooms] == [existing_room["roomId"]]
    assert {participant["agentId"] for participant in rooms[0]["participants"]} == {alpha["agentId"], beta["agentId"]}


def test_research_team_sync_restores_missing_historical_team_chat_room_id(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    organization = {
        "agents": [
            {"nodeId": "alpha-node", "agentId": alpha["agentId"], "displayName": "Alpha", "role": "lead", "status": "active"},
            {"nodeId": "beta-node", "agentId": beta["agentId"], "displayName": "Beta", "role": "reviewer", "status": "active"},
        ],
        "edges": [],
    }

    first = team_service.ensure_research_team_from_organization(organization)
    historical_room_id = first["linkedChatRoomId"]
    chat_room_service.delete_chat_room(historical_room_id)
    rounds_path = tmp_path / "workspace" / "teams" / "research-team" / "research_stage_rounds" / "index.json"
    rounds_path.parent.mkdir(parents=True, exist_ok=True)
    rounds_path.write_text(
        json.dumps(
            {
                "rounds": [
                    {
                        "roundId": "round-historical",
                        "coordinationRoomId": historical_room_id,
                        "contract": {"linkedChatRoomId": historical_room_id},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    repaired = team_service.get_team("research-team")
    room = chat_room_service.get_chat_room_detail(historical_room_id)

    assert repaired["linkedChatRoomId"] == historical_room_id
    assert room is not None
    assert room["purpose"] == "research_coordination"
    assert room["title"] == "挑战杯ai科研团队 团队群聊"
    assert room["config"]["teamName"] == "挑战杯ai科研团队"
    assert [participant["agentId"] for participant in room["participants"]] == [alpha["agentId"], beta["agentId"]]


def test_research_team_sync_preserves_current_room_and_restores_historical_room_refs(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    organization = {
        "agents": [
            {"nodeId": "alpha-node", "agentId": alpha["agentId"], "displayName": "Alpha", "role": "lead", "status": "active"},
            {"nodeId": "beta-node", "agentId": beta["agentId"], "displayName": "Beta", "role": "reviewer", "status": "active"},
        ],
        "edges": [],
    }

    current = team_service.ensure_research_team_from_organization(organization)
    current_room_id = current["linkedChatRoomId"]
    historical_room_id = "room-20260529-090009-757107-6a747d62"
    rounds_path = tmp_path / "workspace" / "teams" / "research-team" / "research_stage_rounds" / "index.json"
    rounds_path.parent.mkdir(parents=True, exist_ok=True)
    rounds_path.write_text(
        json.dumps(
            {
                "rounds": [
                    {
                        "roundId": "round-historical",
                        "coordinationRoomId": historical_room_id,
                        "coordinationContract": {
                            "linkedChatRoomId": historical_room_id,
                            "startResult": {"roomId": historical_room_id},
                        },
                    },
                    {
                        "roundId": "round-current",
                        "coordinationContract": {
                            "linkedChatRoomId": current_room_id,
                            "startResult": {"roomId": current_room_id},
                        },
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    repaired = team_service.get_team("research-team")
    restored_room = chat_room_service.get_chat_room_detail(historical_room_id)
    reloaded = team_service.get_team("research-team")

    assert repaired["linkedChatRoomId"] == current_room_id
    assert reloaded["linkedChatRoomId"] == current_room_id
    assert restored_room is not None
    assert restored_room["config"]["historicalTeamRoom"] is True
    assert restored_room["title"] == "挑战杯ai科研团队 团队群聊（历史）"
    assert restored_room["config"]["teamName"] == "挑战杯ai科研团队"
    assert restored_room["config"]["currentLinkedChatRoomId"] == current_room_id
    assert chat_room_service.get_chat_room_detail(historical_room_id) is not None
    assert {room["roomId"] for room in chat_room_service.list_chat_rooms()} == {current_room_id, historical_room_id}


def test_research_team_sync_updates_existing_historical_room_metadata(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    organization = {
        "agents": [
            {"nodeId": "alpha-node", "agentId": alpha["agentId"], "displayName": "Alpha", "role": "lead", "status": "active"},
        ],
        "edges": [],
    }

    current = team_service.ensure_research_team_from_organization(organization)
    current_room_id = current["linkedChatRoomId"]
    historical_room_id = "room-20260529-090009-757107-6a747d62"
    chat_room_service.create_chat_room(
        room_id=historical_room_id,
        title="旧科研团队群聊（历史）",
        participant_session_ids=[],
        allow_empty_participants=True,
        purpose="discussion",
        config={
            "source": "team",
            "teamId": "research-team",
            "teamName": "旧科研团队",
            "historicalTeamRoom": True,
            "customFlag": "keep",
        },
    )
    rounds_path = tmp_path / "workspace" / "teams" / "research-team" / "research_stage_rounds" / "index.json"
    rounds_path.parent.mkdir(parents=True, exist_ok=True)
    rounds_path.write_text(
        json.dumps(
            {
                "rounds": [
                    {
                        "roundId": "round-historical",
                        "coordinationRoomId": historical_room_id,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    team_service.get_team("research-team")
    room = chat_room_service.get_chat_room_detail(historical_room_id)

    assert room["title"] == "挑战杯ai科研团队 团队群聊（历史）"
    assert room["purpose"] == "research_coordination"
    assert room["config"]["teamName"] == "挑战杯ai科研团队"
    assert room["config"]["currentLinkedChatRoomId"] == current_room_id
    assert room["config"]["customFlag"] == "keep"
    assert [participant["agentId"] for participant in room["participants"]] == [alpha["agentId"]]


def test_team_chat_room_sync_preserves_existing_config_extensions(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team = team_service.create_team(name="Config Team", members=[{"agentId": agent["agentId"], "role": "lead"}])
    chat_room_service.update_chat_room(
        team["linkedChatRoomId"],
        config={
            "source": "team",
            "teamId": team["teamId"],
            "teamName": "Config Team",
            "teamPurpose": "",
            "templateDemo": True,
        },
    )

    reloaded_team = team_service.get_team(team["teamId"])
    room = chat_room_service.get_chat_room_detail(reloaded_team["linkedChatRoomId"])

    assert room["config"]["templateDemo"] is True
    assert room["config"]["source"] == "team"
    assert room["config"]["teamId"] == team["teamId"]


def test_ensure_evolution_system_teams_materializes_mode_roles(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(team_service, "_ensure_evolution_system_agents", _evolution_system_agent_payloads)
    expected_counts = {
        "self_evolution": len(_evolution_system_agent_payloads()["self_evolution"]),
        "supervised_evolution": len(_evolution_system_agent_payloads()["supervised_evolution"]),
    }

    result = team_service.ensure_evolution_system_teams()
    teams = {team["teamId"]: team for team in result["teams"]}

    assert set(teams) == {"self-evolution-team", "supervised-evolution-team"}
    assert teams["self-evolution-team"]["systemTeamKind"] == "self_evolution"
    assert teams["supervised-evolution-team"]["systemTeamKind"] == "supervised_evolution"
    assert teams["self-evolution-team"]["teamKind"] == "self_evolution"
    assert teams["self-evolution-team"]["teamCategory"] == "自进化系统团队"
    assert teams["self-evolution-team"]["teamSource"] == "self_evolution"
    assert teams["supervised-evolution-team"]["teamKind"] == "supervised_evolution"
    assert teams["supervised-evolution-team"]["teamCategory"] == "监督进化系统团队"
    assert teams["supervised-evolution-team"]["teamSource"] == "supervised_evolution"
    assert teams["self-evolution-team"]["memberCount"] == expected_counts["self_evolution"]
    assert teams["supervised-evolution-team"]["memberCount"] == expected_counts["supervised_evolution"]
    assert teams["self-evolution-team"]["linkedChatRoomId"]
    assert teams["supervised-evolution-team"]["linkedChatRoomId"]
    assert len(chat_room_service.list_chat_rooms()) == 2
    rooms = {room["config"]["teamId"]: room for room in chat_room_service.list_chat_rooms()}
    assert rooms["self-evolution-team"]["purpose"] == "self_evolution"
    assert rooms["supervised-evolution-team"]["purpose"] == "supervised_evolution"
    self_canvas = team_service.get_team_canvas("self-evolution-team")
    supervised_canvas = team_service.get_team_canvas("supervised-evolution-team")
    assert self_canvas["canvasKind"] == team_service.CANVAS_KIND
    assert supervised_canvas["canvasKind"] == team_service.CANVAS_KIND
    assert [(edge["source"], edge["target"]) for edge in self_canvas["edges"]] == [
        ("node-1", "node-2"),
        ("node-2", "node-3"),
    ]
    assert [(edge["source"], edge["target"]) for edge in supervised_canvas["edges"]] == [
        ("node-1", "node-3"),
        ("node-2", "node-3"),
        ("node-3", "node-4"),
        ("node-4", "node-5"),
    ]


def test_ensure_ai_search_system_team_materializes_source_scope_roles(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    events = []

    def record_event(component, surface, event_code, **kwargs):
        events.append(
            {
                "component": component,
                "surface": surface,
                "eventCode": event_code,
                **kwargs,
            }
        )

    monkeypatch.setattr(team_service, "record_runtime_scene_event", record_event)
    expected_roles = [role["role"] for role in team_service.AI_SEARCH_SYSTEM_ROLES]
    expected_role_count = len(expected_roles)

    team = team_service.ensure_ai_search_system_team()

    assert team["teamId"] == team_service.AI_SEARCH_TEAM_ID
    assert team["name"] == "AI 搜索范围团队"
    assert team["systemTeamKind"] == "ai_search"
    assert team["teamKind"] == "ai_search"
    assert team["teamCategory"] == "AI 搜索系统团队"
    assert team["teamSource"] == "ai_search"
    assert team["memberCount"] == expected_role_count
    assert [member["role"] for member in team["members"]] == expected_roles
    assert team["linkedChatRoomId"]
    assert team["linkedChatRoom"]["participantCount"] == expected_role_count
    assert team["sourceScopePath"] == "workspace/teams/ai-search-team/source_scope.json"
    assert team["sourceScope"]["scopeId"] == "ai-latest-news-source-scope-v1"
    assert team["sourceScope"]["summary"]["groupCount"] == 4
    assert team["sourceScope"]["summary"]["sourceCount"] >= 30
    assert team["sourceScope"]["policy"]["defaultEnabledTiers"] == ["tier1", "tier2"]
    assert team["sourceScope"]["policy"]["requiresPrimaryEvidenceForConclusion"] is True
    assert [group["groupId"] for group in team["sourceScope"]["groups"]] == [
        "global_official",
        "cn_official",
        "trusted_indices",
        "community_signals",
    ]
    assert team["sourceScope"]["groups"][0]["enabledByDefault"] is True
    assert team["sourceScope"]["groups"][-1]["enabledByDefault"] is False
    source_scope_path = tmp_path / "workspace" / "teams" / "ai-search-team" / "source_scope.json"
    assert source_scope_path.exists()
    stored_scope = json.loads(source_scope_path.read_text(encoding="utf-8"))
    assert stored_scope["summary"]["sourceCount"] == team["sourceScope"]["summary"]["sourceCount"]

    room = chat_room_service.get_chat_room_detail(team["linkedChatRoomId"])
    assert room["purpose"] == "ai_search"
    assert room["config"]["teamKind"] == "ai_search"
    assert room["config"]["teamSource"] == "ai_search"
    assert len(room["participants"]) == expected_role_count

    canvas = team_service.get_team_canvas(team_service.AI_SEARCH_TEAM_ID)
    assert canvas["canvasKind"] == team_service.CANVAS_KIND
    assert [node["role"] for node in canvas["nodes"]] == expected_roles
    assert {edge["id"] for edge in canvas["edges"]} == {
        "ai-search-scope-global",
        "ai-search-scope-cn",
        "ai-search-global-quality",
        "ai-search-cn-quality",
        "ai-search-quality-scope",
    }

    agents = agent_directory_service.list_agents(include_archived=True, detail="summary")
    agents_by_role = {
        agent["metadata"].get("aiSearchRole"): agent
        for agent in agents
        if isinstance(agent.get("metadata"), dict) and agent["metadata"].get("aiSearchRole")
    }
    assert set(agents_by_role) == set(expected_roles)
    assert all(agent["primaryMode"] == "research" for agent in agents_by_role.values())
    assert all(agent["metadata"]["fixedRole"] is True for agent in agents_by_role.values())
    assert all(agent["metadata"]["protected"] is True for agent in agents_by_role.values())
    assert all(
        agent["metadata"]["conversationIndexKind"] == agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT
        for agent in agents_by_role.values()
    )
    assert all(agent["metadata"]["teamId"] == team_service.AI_SEARCH_TEAM_ID for agent in agents_by_role.values())
    stored_sessions = {item["conversation_id"]: item for item in session_service.load_chat_state(tmp_path)["conversations"]}
    assert all(
        stored_sessions[str(agent["directSessionId"])]["conversationIndexKind"]
        == agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT
        for agent in agents_by_role.values()
    )
    assert all(
        agent_directory_service.agent_conversation_index_visibility(agent)
        == agent_directory_service.CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE
        for agent in agents_by_role.values()
    )
    assert all(
        session_service._agent_directory_stub_hidden_from_user_index(agent, {agent["agentId"]})
        for agent in agents_by_role.values()
    )

    second = team_service.ensure_ai_search_system_team()
    assert [member["agentId"] for member in second["members"]] == [member["agentId"] for member in team["members"]]
    sync_events = [event for event in events if event["eventCode"] == "team.ai_search_system_synced"]
    assert sync_events
    assert sync_events[0]["fields"]["sourceScopePath"] == "workspace/teams/ai-search-team/source_scope.json"
    assert sync_events[0]["fields"]["sourceScopeChanged"] is True
    assert sync_events[0]["fields"]["sourceGroupCount"] == 4
    assert sync_events[0]["fields"]["sourceCount"] == team["sourceScope"]["summary"]["sourceCount"]


def test_start_ai_search_source_scope_run_writes_cards_and_index(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    searched_queries = []

    def fake_web_search(query, *, max_results):
        searched_queries.append((query, max_results))
        return (
            f"关于「{query}」，搜索到 2 条相关结果：\n\n"
            "• 发布了新的模型和产品动态。\n\n"
            "**参考来源：**\n"
            "1. [Official update](https://example.com/update)\n"
            "2. [Research note](https://example.com/research)\n"
        )

    monkeypatch.setattr(team_service, "_run_ai_web_search", fake_web_search)
    monkeypatch.setattr(team_service, "ensure_ai_search_system_team", _seed_ai_search_system_team_ready)
    team_service.ensure_ai_search_system_team()

    run = team_service.start_ai_search_source_scope_run(
        team_service.AI_SEARCH_TEAM_ID,
        topic="AI agent 最新动态",
        source_limit=5,
        max_results_per_query=2,
    )

    assert run["status"] == "completed"
    assert run["topic"] == "AI agent 最新动态"
    assert run["queryPlan"]["queryCount"] == 5
    assert run["queryPlan"]["sourceLimit"] == 5
    assert run["summary"]["cardCount"] == 5
    assert run["summary"]["succeededCount"] == 5
    assert run["summary"]["failedCount"] == 0
    assert run["summary"]["degradedCount"] == 0
    assert run["summary"]["referenceCount"] == 10
    assert len(searched_queries) == 5
    assert {query["groupId"] for query in run["queryPlan"]["queries"]} >= {"global_official", "cn_official", "trusted_indices"}
    assert run["cards"][0]["references"][0]["url"] == "https://example.com/update"
    run_path = tmp_path / "workspace" / "teams" / "ai-search-team" / "search_runs" / f"{run['runId']}.json"
    index_path = tmp_path / "workspace" / "teams" / "ai-search-team" / "search_runs" / "index.json"
    assert run_path.exists()
    assert index_path.exists()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["runs"][0]["runId"] == run["runId"]
    assert index["runs"][0]["cardCount"] == 5

    payload = team_service.list_ai_search_source_scope_runs(team_service.AI_SEARCH_TEAM_ID)
    assert payload["runs"][0]["runId"] == run["runId"]
    assert payload["runs"][0]["cards"][0]["sourceName"]


def test_start_ai_search_source_scope_run_records_partial_failures(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    calls = {"count": 0}

    def fake_web_search(query, *, max_results):
        calls["count"] += 1
        if calls["count"] == 1:
            return "[错误] token service unavailable"
        return "**参考来源：**\n1. [Source](https://example.com)\n"

    monkeypatch.setattr(team_service, "_run_ai_web_search", fake_web_search)
    monkeypatch.setattr(
        team_service,
        "_run_ai_source_page_fallback",
        lambda query, *, max_results, primary_error: "[错误] source page fallback failed",
    )
    monkeypatch.setattr(team_service, "ensure_ai_search_system_team", _seed_ai_search_system_team_ready)

    run = team_service.start_ai_search_source_scope_run(team_service.AI_SEARCH_TEAM_ID, source_limit=2)

    assert run["status"] == "partial"
    assert run["summary"]["cardCount"] == 2
    assert run["summary"]["failedCount"] == 1
    assert run["summary"]["degradedCount"] == 0
    assert run["errors"][0]["sourceId"]
    assert run["cards"][0]["status"] == "failed"


def test_start_ai_search_source_scope_run_falls_back_to_source_page(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    def fake_web_search(query, *, max_results):
        return "[错误] AutoGLM token service unavailable"

    def fake_fetch_source_page(source_url):
        return {
            "url": "https://openai.com/news/",
            "title": "OpenAI News",
            "description": "Latest company, model, product, and research announcements.",
            "links": [
                {"title": "New model update", "url": "/news/new-model-update"},
                {"title": "Research release", "url": "https://openai.com/news/research-release"},
                {"title": "Careers", "url": "https://openai.com/careers"},
            ],
        }

    monkeypatch.setattr(team_service, "_run_ai_web_search", fake_web_search)
    monkeypatch.setattr(team_service, "_fetch_ai_search_source_page", fake_fetch_source_page)
    monkeypatch.setattr(team_service, "ensure_ai_search_system_team", _seed_ai_search_system_team_ready)

    run = team_service.start_ai_search_source_scope_run(
        team_service.AI_SEARCH_TEAM_ID,
        topic="neural predictive coding",
        source_limit=1,
        max_results_per_query=2,
    )

    assert run["status"] == "completed"
    assert run["summary"]["succeededCount"] == 1
    assert run["summary"]["failedCount"] == 0
    assert run["summary"]["degradedCount"] == 1
    assert run["summary"]["referenceCount"] == 2
    card = run["cards"][0]
    assert card["status"] == "succeeded"
    assert card["searchMode"] == "source_page_fallback"
    assert card["degraded"] is True
    assert "AutoGLM token" in card["fallbackReason"]
    assert card["summary"].startswith("[降级]")
    assert {reference["url"] for reference in card["references"]} == {
        "https://openai.com/news/new-model-update",
        "https://openai.com/news/research-release",
    }

    index_path = tmp_path / "workspace" / "teams" / "ai-search-team" / "search_runs" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["runs"][0]["degradedCount"] == 1
    assert index["runs"][0]["cards"][0]["searchMode"] == "source_page_fallback"


def test_ensure_evolution_system_teams_preserves_existing_team_member_status(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(team_service, "_ensure_evolution_system_agents", _evolution_system_agent_payloads)
    agent = agent_directory_service.create_agent_instance(display_name="Research Lead", direct_session_id="session-research-lead")
    team = team_service.create_team(name="Research Team", members=[{"agentId": agent["agentId"], "role": "lead"}])

    team_service.ensure_evolution_system_teams()

    reloaded = team_service.get_team(team["teamId"])
    assert reloaded["members"][0]["agentStatus"] == "active"


def test_ensure_evolution_system_teams_refreshes_stale_chat_room_participant_context(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    def create_self_agent(role: str, label: str) -> dict:
        prompt_id = "" if role == "observer" else f"prompt-self-{role}"
        return agent_directory_service.create_agent_instance(
            display_name=label,
            direct_session_id=f"session-self-{role}",
            primary_mode="self_evolution",
            role_key=role,
            prompt_template_id=prompt_id,
            metadata={
                "fixedRole": True,
                "protected": True,
                "agentMode": "self_evolution",
                "selfEvolutionRole": role,
                "selfEvolutionRoleLabel": label,
                "functionalDisplayName": label,
            },
        )

    agents = [
        create_self_agent("executor", "自进化执行 Agent"),
        create_self_agent("reviewer", "自进化评审 Agent"),
        create_self_agent("observer", "自进化观察 Agent"),
    ]
    monkeypatch.setattr(
        team_service,
        "_ensure_evolution_system_agents",
        lambda: {"self_evolution": agents, "supervised_evolution": []},
    )
    initial = team_service.ensure_evolution_system_teams()
    team = next(item for item in initial["teams"] if item["teamId"] == "self-evolution-team")
    room_id = team["linkedChatRoomId"]

    state = chat_room_service._store().load()
    room = next(item for item in state["rooms"] if item["roomId"] == room_id)
    observer_agent_id = agents[2]["agentId"]
    observer_participant = next(item for item in room["participants"] if item["agentId"] == observer_agent_id)
    observer_participant["teamPurpose"] = "承接自进化执行、评审与总结角色的团队通讯。"
    observer_participant["teamRole"] = "summarizer"
    observer_participant["teamMemberPurpose"] = "自进化总结 Agent"
    chat_room_service._store().save(state)

    team_service.ensure_evolution_system_teams()
    repaired_room = chat_room_service.get_chat_room_detail(room_id)
    repaired_observer = next(item for item in repaired_room["participants"] if item["agentId"] == observer_agent_id)

    assert repaired_observer["teamRole"] == "observer"
    assert repaired_observer["teamMemberPurpose"] == "自进化观察 Agent"
    assert "观察" in repaired_observer["teamPurpose"]
    assert "总结" not in repaired_observer["teamPurpose"]


def test_compact_team_list_repairs_legacy_team_contract_without_full_hydration(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    room = chat_room_service.create_chat_room(
        title="旧自进化团队群聊",
        allow_empty_participants=True,
        purpose="discussion",
        config={"source": "team", "teamId": "self-evolution-team"},
    )
    teams_path = tmp_path / "workspace" / "teams" / "teams.json"
    teams_path.parent.mkdir(parents=True, exist_ok=True)
    teams_path.write_text(
        """
{
  "schemaVersion": 1,
  "updatedAt": "2026-06-01T00:00:00+00:00",
  "teams": [
    {
      "teamId": "self-evolution-team",
      "name": "自进化团队",
      "description": "由自进化固定角色自动同步的系统团队。",
      "purpose": "承接自进化执行、评审与总结角色的团队通讯。",
      "status": "active",
      "systemTeamKind": "self_evolution",
      "members": [],
      "linkedChatRoomId": "%s",
      "canvasPath": "workspace/teams/self-evolution-team/canvas.json",
      "createdAt": "2026-06-01T00:00:00+00:00",
      "updatedAt": "2026-06-01T00:00:00+00:00"
    }
  ]
}
"""
        % room["roomId"],
        encoding="utf-8",
    )
    monkeypatch.setattr(
        chat_room_service,
        "get_chat_room_detail",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("compact repair should not hydrate linked room detail")),
    )

    payload = team_service.list_teams_compact()

    team = payload["teams"][0]
    assert team["teamKind"] == "self_evolution"
    assert team["teamCategory"] == "自进化系统团队"
    assert team["teamSource"] == "self_evolution"
    repaired = team_service._load_index()["teams"][0]
    assert repaired["teamKind"] == "self_evolution"
    assert repaired["teamCategory"] == "自进化系统团队"
    assert repaired["teamSource"] == "self_evolution"
    assert chat_room_service.get_chat_room_compact(room["roomId"])["purpose"] == "self_evolution"


def test_compact_team_list_skips_busy_linked_chat_room_metadata_repair(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    room = chat_room_service.create_chat_room(
        title="运行中的自进化团队群聊",
        allow_empty_participants=True,
        purpose="discussion",
        config={"source": "team", "teamId": "self-evolution-team"},
    )
    teams_path = tmp_path / "workspace" / "teams" / "teams.json"
    teams_path.parent.mkdir(parents=True, exist_ok=True)
    teams_path.write_text(
        """
{
  "schemaVersion": 1,
  "updatedAt": "2026-06-01T00:00:00+00:00",
  "teams": [
    {
      "teamId": "self-evolution-team",
      "name": "自进化团队",
      "purpose": "承接自进化执行、评审与总结角色的团队通讯。",
      "status": "active",
      "systemTeamKind": "self_evolution",
      "members": [],
      "linkedChatRoomId": "%s",
      "canvasPath": "workspace/teams/self-evolution-team/canvas.json",
      "createdAt": "2026-06-01T00:00:00+00:00",
      "updatedAt": "2026-06-01T00:00:00+00:00"
    }
  ]
}
"""
        % room["roomId"],
        encoding="utf-8",
    )
    recorded_events = []
    monkeypatch.setattr(
        team_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    real_update_chat_room = chat_room_service.update_chat_room

    def fake_update_chat_room(*args, **kwargs):
        raise chat_room_service.ChatRoomBusyError("Chat room already has an active round.")

    monkeypatch.setattr(chat_room_service, "update_chat_room", fake_update_chat_room)

    payload = team_service.list_teams_compact()

    assert payload["summary"]["activeTeamCount"] == 1
    assert payload["teams"][0]["teamKind"] == "self_evolution"
    assert chat_room_service.get_chat_room_compact(room["roomId"])["purpose"] == "discussion"
    assert any(
        args[2] == "team.compact_chat_room_sync_skipped_busy"
        for args, _kwargs in recorded_events
    )

    monkeypatch.setattr(chat_room_service, "update_chat_room", real_update_chat_room)


def test_compact_team_list_uses_compact_linked_room_without_full_hydration(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team_service.create_team(name="Compact Team", members=[{"agentId": agent["agentId"], "role": "lead"}])
    monkeypatch.setattr(
        chat_room_service,
        "get_chat_room_detail",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("compact list should not hydrate linked rooms")),
    )

    payload = team_service.list_teams_compact()

    assert payload["summary"]["activeTeamCount"] == 1
    assert payload["teams"][0]["linkedChatRoomId"]
    assert payload["teams"][0]["linkedChatRoom"]["participantCount"] == 1
    assert "conversation" not in payload["teams"][0]


def test_compact_team_list_batches_linked_room_compact_reads(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    team_service.create_team(name="Compact Team Alpha", members=[{"agentId": alpha["agentId"], "role": "lead"}])
    team_service.create_team(name="Compact Team Beta", members=[{"agentId": beta["agentId"], "role": "lead"}])
    list_calls = []
    real_list_compact = chat_room_service.list_chat_rooms_compact

    def tracked_list_chat_rooms_compact():
        list_calls.append("list")
        return real_list_compact()

    monkeypatch.setattr(chat_room_service, "list_chat_rooms_compact", tracked_list_chat_rooms_compact)
    monkeypatch.setattr(
        chat_room_service,
        "get_chat_room_compact",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("compact list should batch linked room references")),
    )

    payload = team_service.list_teams_compact()

    assert list_calls == ["list"]
    assert payload["summary"]["activeTeamCount"] == 2
    assert all((team.get("linkedChatRoom") or {}).get("participantCount") == 1 for team in payload["teams"])


def test_compact_team_list_returns_snapshot_when_team_lock_is_busy(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team = team_service.create_team(name="Busy Lock Team", members=[{"agentId": alpha["agentId"], "role": "lead"}])

    class BusyTeamLock:
        def acquire(self, blocking=True, timeout=-1):
            assert blocking is False
            return False

        def release(self):
            raise AssertionError("busy lock should not be released when it was not acquired")

        def __enter__(self):
            raise AssertionError("compact team list should not block on the team write lock")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(team_service, "_TEAM_LOCK", BusyTeamLock())

    payload = team_service.list_teams_compact()

    assert [item["teamId"] for item in payload["teams"]] == [team["teamId"]]
    assert payload["teams"][0]["linkedChatRoomId"]


def test_archived_team_room_filter_returns_snapshot_when_team_lock_is_busy(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team = team_service.create_team(name="Archived Busy Team", members=[{"agentId": alpha["agentId"], "role": "lead"}])
    state = team_service._load_index()
    state["teams"][0]["status"] = "archived"
    team_service._save_index(state)

    class BusyTeamLock:
        def acquire(self, blocking=True, timeout=-1):
            assert blocking is False
            return False

        def release(self):
            raise AssertionError("busy lock should not be released when it was not acquired")

        def __enter__(self):
            raise AssertionError("archived room filter should not block on the team write lock")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(team_service, "_TEAM_LOCK", BusyTeamLock())

    room_ids = team_service.list_archived_team_linked_chat_room_ids()

    assert room_ids == {team["linkedChatRoomId"]}


def test_system_team_bootstrap_request_defers_when_team_lock_is_busy(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_system_team_bootstrap_ready()

    class BusyTeamLock:
        def acquire(self, blocking=True, timeout=-1):
            assert blocking is False
            return False

        def release(self):
            raise AssertionError("busy lock should not be released when it was not acquired")

        def __enter__(self):
            raise AssertionError("bootstrap check should not block on the team write lock")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(team_service, "_TEAM_LOCK", BusyTeamLock())

    payload = team_service.request_system_team_bootstrap(reason="team_list")

    assert payload["status"] == "deferred"
    assert payload["lastError"] == "team_lock_busy"


def test_system_team_bootstrap_ready_snapshot_skips_repeated_missing_checks(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_system_team_bootstrap_ready()
    monkeypatch.setattr(team_service, "_perf_counter", lambda: 100.0)
    first = team_service.request_system_team_bootstrap(reason="team_list")

    monkeypatch.setattr(team_service, "_perf_counter", lambda: 101.0)
    monkeypatch.setattr(
        team_service,
        "evolution_system_teams_missing",
        lambda: (_ for _ in ()).throw(AssertionError("ready bootstrap cache should skip repeated checks")),
    )

    second = team_service.request_system_team_bootstrap(reason="team_list")

    assert first["status"] == "ready"
    assert second["status"] == "ready"


def test_system_team_bootstrap_nonblocking_ready_snapshot_skips_expired_missing_checks(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_system_team_bootstrap_ready()
    monkeypatch.setattr(team_service, "_perf_counter", lambda: 100.0)
    first = team_service.request_system_team_bootstrap(reason="team_list")
    created_threads = []
    next_attempt = int(first["attempt"] or 0) + 1

    class CapturedThread:
        def __init__(self, *, target, args, name, daemon):
            self.target = target
            self.args = args
            self.name = name
            self.daemon = daemon
            self.started = False
            created_threads.append(self)

        def is_alive(self):
            return False

        def start(self):
            self.started = True

    monkeypatch.setattr(team_service, "_perf_counter", lambda: 200.0)
    monkeypatch.setattr(team_service.threading, "Thread", CapturedThread)
    monkeypatch.setattr(
        team_service,
        "_system_team_bootstrap_required_steps",
        lambda: (_ for _ in ()).throw(AssertionError("nonblocking ready snapshot should refresh in the background")),
    )

    second = team_service.request_system_team_bootstrap(reason="team_list", allow_sync_check=False)

    assert first["status"] == "ready"
    assert second["status"] == "ready"
    assert second["requiredSteps"] == []
    assert created_threads and created_threads[0].started is True
    assert created_threads[0].args == (f"system-team-bootstrap-{next_attempt}", "team_list")


def test_system_team_bootstrap_nonblocking_idle_schedules_background_check(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    created_threads = []

    with team_service._TEAM_SYSTEM_BOOTSTRAP_LOCK:
        team_service._TEAM_SYSTEM_BOOTSTRAP_THREAD = None
        team_service._TEAM_SYSTEM_BOOTSTRAP_STATE.update(
            {
                "status": "idle",
                "requiredSteps": [],
                "reason": "",
                "startedAt": "",
                "finishedAt": "",
                "lastError": "",
                "elapsedMs": 0,
                "attempt": 0,
                "requestId": "",
                "checkedAtMonotonic": 0.0,
            }
        )

    class CapturedThread:
        def __init__(self, *, target, args, name, daemon):
            self.target = target
            self.args = args
            self.name = name
            self.daemon = daemon
            self.started = False
            created_threads.append(self)

        def is_alive(self):
            return False

        def start(self):
            self.started = True

    monkeypatch.setattr(team_service.threading, "Thread", CapturedThread)
    monkeypatch.setattr(
        team_service,
        "_system_team_bootstrap_required_steps",
        lambda: (_ for _ in ()).throw(AssertionError("nonblocking idle request should check in the background")),
    )

    payload = team_service.request_system_team_bootstrap(reason="team_list", allow_sync_check=False)

    assert payload["status"] == "running"
    assert payload["requiredSteps"] == []
    assert payload["reason"] == "team_list"
    assert created_threads and created_threads[0].started is True
    assert created_threads[0].name == "vibelution-team-system-bootstrap"


def test_compact_team_list_does_not_hydrate_agents_for_active_teams(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    team_service.create_team(name="Compact Team Alpha", members=[{"agentId": alpha["agentId"], "role": "lead"}])
    team_service.create_team(name="Compact Team Beta", members=[{"agentId": beta["agentId"], "role": "lead"}])
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("compact list should not hydrate agents one by one")),
    )
    monkeypatch.setattr(
        agent_directory_service,
        "list_agents",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("active compact list should not need agent list hydration")),
    )

    payload = team_service.list_teams_compact()

    assert payload["summary"]["activeTeamCount"] == 2
    assert [team["memberCount"] for team in payload["teams"]] == [1, 1]


def test_compact_team_list_skips_archived_agent_cascade_repair(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team = team_service.create_team(name="Archived Compact Team", members=[{"agentId": alpha["agentId"], "role": "lead"}])
    state = team_service._load_index()
    stored = state["teams"][0]
    stored["status"] = "archived"
    team_service._save_index(state)
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("compact list should not repair archived member agents")),
    )
    monkeypatch.setattr(
        agent_directory_service,
        "list_agents",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("compact list should not hydrate archived member agents")),
    )

    payload = team_service.list_teams_compact(include_archived=True)

    assert payload["teams"][0]["teamId"] == team["teamId"]
    assert payload["teams"][0]["status"] == "archived"
    assert payload["teams"][0]["memberCount"] == 1


def test_team_detail_uses_lightweight_agent_references_for_member_repair(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    team = team_service.create_team(
        name="Fast Detail Team",
        members=[{"agentId": alpha["agentId"], "role": "lead"}, {"agentId": beta["agentId"], "role": "reviewer"}],
    )
    monkeypatch.setattr(
        agent_directory_service,
        "list_agents",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("team detail should not use full agent list hydration")),
    )
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("team detail should reuse lightweight agent references")),
    )

    detail = team_service.get_team(team["teamId"])

    assert [member["agentId"] for member in detail["members"]] == [alpha["agentId"], beta["agentId"]]
    assert detail["canvas"]["validation"]["valid"] is True


def test_team_graph_references_skip_linked_room_hydration_and_repair(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team_service.create_team(name="Graph Team", members=[{"agentId": agent["agentId"], "role": "lead"}])
    monkeypatch.setattr(
        chat_room_service,
        "get_chat_room_detail",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("graph references should not hydrate linked room detail")),
    )
    monkeypatch.setattr(
        chat_room_service,
        "get_chat_room_compact",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("graph references should not hydrate linked room compact")),
    )
    monkeypatch.setattr(
        chat_room_service,
        "update_chat_room",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("graph references should not repair linked room metadata")),
    )

    payload = team_service.list_team_graph_references()

    assert payload["summary"]["activeTeamCount"] == 1
    assert payload["teams"][0]["members"][0]["agentId"] == agent["agentId"]
    assert payload["teams"][0]["linkedChatRoomId"]
    assert "linkedChatRoom" not in payload["teams"][0]
    assert "conversation" not in payload["teams"][0]


def test_team_detail_uses_compact_linked_room_without_full_chat_room_hydration(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team = team_service.create_team(name="Fast Detail Team", members=[{"agentId": agent["agentId"], "role": "lead"}])
    monkeypatch.setattr(
        chat_room_service,
        "get_chat_room_detail",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("team detail should use compact linked room")),
    )

    detail = team_service.get_team(team["teamId"])

    assert detail["linkedChatRoomId"] == team["linkedChatRoomId"]
    assert detail["linkedChatRoom"]["participantCount"] == 1
    assert detail["conversation"]["status"] == "linked"
    assert detail["canvas"]["nodes"][0]["agentId"] == agent["agentId"]


def test_team_canvas_save_cannot_add_team_or_chat_room_members(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    team = team_service.create_team(name="Sync Team", members=[{"agentId": alpha["agentId"], "role": "lead"}])
    linked_room_id = team["linkedChatRoomId"]
    canvas = team_service.get_team_canvas(team["teamId"])
    canvas["nodes"].append(
        {
            "id": "node-beta",
            "label": "Beta reviewer",
            "type": "agent",
            "status": "bound",
            "x": 420,
            "y": 120,
            "agentId": beta["agentId"],
            "agentCode": beta["agentCode"],
            "agentName": beta["displayName"],
            "role": "reviewer",
            "purpose": "检查输出",
            "responsibilities": ["保留画布中的结构化职责。"],
        }
    )

    updated_canvas = team_service.save_team_canvas(team["teamId"], canvas)
    updated_team = team_service.get_team(team["teamId"])
    linked_room = chat_room_service.get_chat_room_detail(updated_team["linkedChatRoomId"])

    assert updated_canvas["validation"]["valid"] is True
    assert updated_team["linkedChatRoomId"] == linked_room_id
    assert [member["agentId"] for member in updated_team["members"]] == [alpha["agentId"]]
    assert [participant["agentId"] for participant in linked_room["participants"]] == [alpha["agentId"]]
    assert next(node for node in updated_canvas["nodes"] if node["id"] == "node-beta")["agentId"] == ""


def test_team_canvas_agent_identity_snapshot_is_readonly_projection(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha Source", direct_session_id="session-alpha")
    team = team_service.create_team(name="Source Guard Team", members=[{"agentId": agent["agentId"], "role": "lead"}])
    canvas = team_service.get_team_canvas(team["teamId"])
    canvas["nodes"][0]["agentCode"] = "spoofed-code"
    canvas["nodes"][0]["agentName"] = "Spoofed Name"
    canvas["nodes"][0]["agentSourceRef"] = {"owner": "FakeProjection"}
    canvas["nodes"][0]["agentProjectionEdit"] = {"canonicalEditRoute": "/teams?team=fake"}
    canvas["nodes"][0]["agentProjectionCanWrite"] = True

    updated_canvas = team_service.save_team_canvas(team["teamId"], canvas)

    node = updated_canvas["nodes"][0]
    assert node["agentCode"] == agent["agentCode"]
    assert node["agentName"] == agent["displayName"]
    assert node["agentSourceRef"]["owner"] == "AgentDirectory"
    assert node["agentSourceRef"]["canonicalEditRoute"] == f"/agents?agent={agent['agentId']}&pane=config"
    assert node["agentSourceRef"]["projectionCanWrite"] is False
    assert node["agentProjectionEdit"]["canWrite"] is False
    assert node["agentProjectionEdit"]["mode"] == "deep_link_to_source"
    assert node["agentProjectionCanWrite"] is False


def test_agent_can_only_belong_to_one_active_team(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    events = []
    monkeypatch.setattr(team_service, "record_runtime_scene_event", lambda *args, **kwargs: events.append((args, kwargs)))
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    first = team_service.create_team(name="Alpha Team", members=[{"agentId": agent["agentId"], "role": "lead"}])

    with pytest.raises(team_service.TeamServiceError, match="already belongs to Team"):
        team_service.create_team(name="Other Team", members=[{"agentId": agent["agentId"], "role": "reviewer"}])

    conflict_events = [item for item in events if item[0][2] == "team.membership_conflict_rejected"]
    assert conflict_events[-1][1]["fields"]["agentId"] == agent["agentId"]
    assert conflict_events[-1][1]["fields"]["conflictTeamId"] == first["teamId"]
    team_service.archive_team(first["teamId"])

    assert agent_directory_service.get_agent(agent["agentId"], include_archived=True)["status"] == "archived"
    with pytest.raises(team_service.TeamServiceError, match="not active"):
        team_service.create_team(name="Other Team", members=[{"agentId": agent["agentId"], "role": "reviewer"}])


def test_archive_custom_team_cascades_member_agents(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    events = []
    monkeypatch.setattr(team_service, "record_runtime_scene_event", lambda *args, **kwargs: events.append((args, kwargs)))
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    team = team_service.create_team(
        name="Cascade Team",
        members=[{"agentId": alpha["agentId"], "role": "lead"}, {"agentId": beta["agentId"], "role": "reviewer"}],
    )

    archived = team_service.archive_team(team["teamId"])

    assert archived["status"] == "archived"
    assert archived["linkedChatRoomId"] == ""
    assert chat_room_service.get_chat_room_detail(team["linkedChatRoomId"]) is None
    assert agent_directory_service.get_agent(alpha["agentId"], include_archived=True)["status"] == "archived"
    assert agent_directory_service.get_agent(beta["agentId"], include_archived=True)["status"] == "archived"
    archived_events = [item for item in events if item[0][2] == "team.archived_with_agents"]
    assert archived_events[-1][1]["fields"]["archivedAgentIds"] == [alpha["agentId"], beta["agentId"]]
    assert archived_events[-1][1]["fields"]["archivedAgentCount"] == 2
    assert archived_events[-1][1]["fields"]["deletedLinkedChatRoomIds"] == [team["linkedChatRoomId"]]
    room_events = [item for item in events if item[0][2] == "team.chat_room.deleted_for_archive"]
    assert room_events[-1][1]["fields"]["deletedLinkedChatRoomIds"] == [team["linkedChatRoomId"]]


def test_archive_custom_team_seals_member_sessions(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Cascade Seal Alpha")
    team = team_service.create_team(
        name="Cascade Seal Team",
        members=[{"agentId": alpha["agentId"], "role": "lead"}],
    )

    archived = team_service.archive_team(team["teamId"])

    assert archived["status"] == "archived"
    detail = session_service.get_session_detail(alpha["id"])
    assert detail is not None
    assert detail["readOnly"] is True
    assert detail["archiveState"]["status"] == "archived"
    assert detail["archiveState"]["agentId"] == alpha["agentId"]


def test_archive_team_releases_team_lock_before_archiving_agents(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(
        display_name="Lock Probe Alpha",
        direct_session_id="session-lock-probe-alpha",
    )
    team = team_service.create_team(
        name="Lock Probe Team",
        members=[{"agentId": alpha["agentId"], "role": "lead"}],
    )
    entered_agent_archive = threading.Event()
    release_agent_archive = threading.Event()
    team_lock_free = threading.Event()
    original_archive = agent_bulk_delete_service.archive_agent_instance

    def blocking_archive(agent_id, *args, **kwargs):
        entered_agent_archive.set()
        assert release_agent_archive.wait(timeout=2)
        return original_archive(agent_id, *args, **kwargs)

    def probe_team_lock():
        acquired = team_service._TEAM_LOCK.acquire(blocking=False)
        if acquired:
            team_service._TEAM_LOCK.release()
            team_lock_free.set()

    monkeypatch.setattr(agent_bulk_delete_service, "archive_agent_instance", blocking_archive)
    archive_thread = threading.Thread(target=lambda: team_service.archive_team(team["teamId"]), daemon=True)
    archive_thread.start()
    assert entered_agent_archive.wait(timeout=2)
    try:
        probe_thread = threading.Thread(target=probe_team_lock, daemon=True)
        probe_thread.start()
        assert team_lock_free.wait(timeout=0.5), "Team archive must release _TEAM_LOCK before Agent archive."
        probe_thread.join(timeout=1)
    finally:
        release_agent_archive.set()
        archive_thread.join(timeout=2)
    assert not archive_thread.is_alive()


def test_create_team_releases_team_lock_before_direct_session_ensure(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Create Lock Probe")
    entered_session_ensure = threading.Event()
    release_session_ensure = threading.Event()
    team_lock_free = threading.Event()
    original_ensure = session_service.ensure_agent_direct_session

    def blocking_ensure(*args, **kwargs):
        entered_session_ensure.set()
        assert release_session_ensure.wait(timeout=2)
        return original_ensure(*args, **kwargs)

    def probe_team_lock():
        acquired = team_service._TEAM_LOCK.acquire(blocking=False)
        if acquired:
            team_service._TEAM_LOCK.release()
            team_lock_free.set()

    monkeypatch.setattr(session_service, "ensure_agent_direct_session", blocking_ensure)
    create_thread = threading.Thread(
        target=lambda: team_service.create_team(
            name="Create Lock Probe Team",
            members=[{"agentId": alpha["agentId"], "role": "lead"}],
        ),
        daemon=True,
    )
    create_thread.start()
    assert entered_session_ensure.wait(timeout=2)
    try:
        probe_thread = threading.Thread(target=probe_team_lock, daemon=True)
        probe_thread.start()
        assert team_lock_free.wait(timeout=0.5), "Team create must release _TEAM_LOCK before direct session ensure."
        probe_thread.join(timeout=1)
    finally:
        release_session_ensure.set()
        create_thread.join(timeout=2)
    assert not create_thread.is_alive()


def test_archive_custom_team_removes_member_agents_from_extra_chat_rooms(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    events = []
    monkeypatch.setattr(team_service, "record_runtime_scene_event", lambda *args, **kwargs: events.append((args, kwargs)))
    alpha = session_service.create_chat_session(title="Alpha Session")
    beta = session_service.create_chat_session(title="Beta Session")
    team = team_service.create_team(
        name="Cascade Room Team",
        members=[{"agentId": alpha["agentId"], "role": "lead"}],
    )
    extra_room = chat_room_service.create_chat_room(
        title="Extra Room",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
    )

    archived = team_service.archive_team(team["teamId"])

    assert archived["status"] == "archived"
    assert chat_room_service.get_chat_room_detail(team["linkedChatRoomId"]) is None
    assert agent_directory_service.get_agent(alpha["agentId"], include_archived=True)["status"] == "archived"
    extra_room_detail = chat_room_service.get_chat_room_detail(extra_room["roomId"])
    assert [participant["agentId"] for participant in extra_room_detail["participants"]] == [beta["agentId"]]
    archived_events = [item for item in events if item[0][2] == "team.archived_with_agents"]
    assert archived_events[-1][1]["fields"]["removedFromRoomIds"] == [extra_room["roomId"]]
    assert archived_events[-1][1]["fields"]["roomCleanupByAgentId"] == {
        alpha["agentId"]: [extra_room["roomId"]]
    }


def test_repair_archived_team_chat_rooms_removes_historical_room_residue(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team = team_service.create_team(name="Residue Team", members=[{"agentId": agent["agentId"], "role": "lead"}])
    room_id = team["linkedChatRoomId"]
    teams_path = tmp_path / "workspace" / "teams" / "teams.json"
    payload = json.loads(teams_path.read_text(encoding="utf-8"))
    payload["teams"][0]["status"] = "archived"
    payload["teams"][0]["updatedAt"] = "2026-06-06T00:00:00+00:00"
    teams_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = team_service.repair_archived_team_chat_rooms()

    assert result["deletedRoomIds"] == [room_id]
    assert chat_room_service.get_chat_room_detail(room_id) is None
    stored = json.loads(teams_path.read_text(encoding="utf-8"))
    assert stored["teams"][0]["linkedChatRoomId"] == ""


def test_archive_team_rejects_protected_member_without_partial_changes(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    protected = agent_directory_service.create_agent_instance(
        display_name="Protected",
        direct_session_id="session-protected",
        metadata={"protected": True},
    )
    peer = agent_directory_service.create_agent_instance(display_name="Peer", direct_session_id="session-peer")
    team = team_service.create_team(
        name="Protected Team",
        members=[{"agentId": protected["agentId"], "role": "lead"}, {"agentId": peer["agentId"], "role": "peer"}],
    )

    with pytest.raises(team_service.TeamServiceError, match="Protected core Agent"):
        team_service.archive_team(team["teamId"])

    assert team_service.get_team(team["teamId"])["status"] == "active"
    assert agent_directory_service.get_agent(protected["agentId"])["status"] == "active"
    assert agent_directory_service.get_agent(peer["agentId"])["status"] == "active"


def test_archive_system_team_is_rejected(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_system_team_bootstrap_ready()

    with pytest.raises(team_service.TeamServiceError, match="System Team cannot be archived"):
        team_service.archive_team("self-evolution-team")

    assert team_service.get_team("self-evolution-team")["status"] == "active"


def test_archived_template_team_prunes_missing_member_refs(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    index_path = tmp_path / "workspace" / "teams" / "teams.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "teams": [
                    {
                        "teamId": "demo",
                        "name": "演示团队",
                        "status": "archived",
                        "teamKind": "template_demo",
                        "teamCategory": "演示业务团队",
                        "teamSource": "team_template",
                        "teamTemplateId": "medical-consultation-demo",
                        "linkedChatRoomId": "",
                        "members": [
                            {
                                "memberId": "medical-demo-1",
                                "agentId": "agent-missing-demo",
                                "agentName": "旧成员",
                                "role": "旧角色",
                                "purpose": "旧用途",
                                "agentStatus": "stale",
                            }
                        ],
                        "createdAt": "2026-06-01T00:00:00Z",
                        "updatedAt": "2026-06-01T00:00:00Z",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    team = team_service.get_team("demo")
    stored = json.loads(index_path.read_text(encoding="utf-8"))

    assert team["members"] == []
    assert stored["teams"][0]["members"] == []


def test_archived_team_list_repairs_active_member_agents(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Legacy", direct_session_id="session-legacy")
    team = team_service.create_team(name="旧演示团队", members=[{"agentId": agent["agentId"]}])

    state = team_service._load_index()
    stored = next(item for item in state["teams"] if item["teamId"] == team["teamId"])
    stored["status"] = "archived"
    team_service._save_index(state)

    payload = team_service.list_teams(include_archived=True)

    repaired = next(item for item in payload["teams"] if item["teamId"] == team["teamId"])
    assert repaired["status"] == "archived"
    assert agent_directory_service.get_agent(agent["agentId"], include_archived=True)["status"] == "archived"


def test_archived_team_list_repair_skips_protected_member_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Protected",
        direct_session_id="session-protected",
        metadata={"protected": True},
    )
    team = team_service.create_team(name="受保护旧团队", members=[{"agentId": agent["agentId"]}])
    state = team_service._load_index()
    stored = next(item for item in state["teams"] if item["teamId"] == team["teamId"])
    stored["status"] = "archived"
    team_service._save_index(state)

    payload = team_service.list_teams(include_archived=True)

    assert any(item["teamId"] == team["teamId"] for item in payload["teams"])
    assert agent_directory_service.get_agent(agent["agentId"])["status"] == "active"


def test_archived_team_explicit_archive_rejects_protected_member_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Protected",
        direct_session_id="session-protected",
        metadata={"protected": True},
    )
    team = team_service.create_team(name="受保护旧团队", members=[{"agentId": agent["agentId"]}])
    state = team_service._load_index()
    stored = next(item for item in state["teams"] if item["teamId"] == team["teamId"])
    stored["status"] = "archived"
    team_service._save_index(state)

    with pytest.raises(team_service.TeamServiceError, match="Protected core Agent cannot be archived"):
        team_service.archive_team(team["teamId"])

    assert agent_directory_service.get_agent(agent["agentId"])["status"] == "active"


def test_team_canvas_drops_non_member_agent_without_writing_membership(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    team_service.create_team(name="Alpha Team", members=[{"agentId": alpha["agentId"], "role": "lead"}])
    beta_team = team_service.create_team(name="Beta Team", members=[{"agentId": beta["agentId"], "role": "reviewer"}])
    canvas = team_service.get_team_canvas(beta_team["teamId"])
    canvas["nodes"].append(
        {
            "id": "node-alpha",
            "label": "Alpha borrowed",
            "type": "agent",
            "x": 520,
            "y": 160,
            "agentId": alpha["agentId"],
            "role": "borrowed",
        }
    )

    saved = team_service.save_team_canvas(beta_team["teamId"], canvas)

    assert [
        node["agentId"]
        for node in saved["nodes"]
        if str(node.get("agentId") or "").strip()
    ] == [beta["agentId"]]
    assert [member["agentId"] for member in team_service.get_team(beta_team["teamId"])["members"]] == [
        beta["agentId"]
    ]


def test_team_rejects_archived_member_at_create(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Archived", direct_session_id="session-archived")
    agent_directory_service.archive_agent_instance(agent["agentId"])

    with pytest.raises(team_service.TeamServiceError, match="not active"):
        team_service.create_team(name="失效团队", members=[{"agentId": agent["agentId"]}])


def test_team_canvas_validation_flags_stale_agent_ref(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team = team_service.create_team(name="Canvas Team", members=[{"agentId": agent["agentId"]}])

    agent_directory_service.archive_agent_instance(agent["agentId"])
    canvas = team_service.get_team_canvas(team["teamId"])

    assert canvas["validation"]["valid"] is True
    assert canvas["nodes"][0]["status"] == "stale"
    assert canvas["validation"]["issues"][0]["code"] == "stale_agent_ref"


def test_get_team_repairs_linked_room_stale_archived_participant(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    team = team_service.create_team(
        name="历史残留团队",
        members=[{"agentId": alpha["agentId"]}, {"agentId": beta["agentId"]}],
    )
    agent_directory_service.archive_agent_instance(beta["agentId"])
    team_service.update_team(team["teamId"], members=[{"agentId": alpha["agentId"]}])
    room_before = chat_room_service.get_chat_room_detail(team["linkedChatRoomId"])
    assert [participant["agentId"] for participant in room_before["participants"]] == [alpha["agentId"]]

    store = chat_room_service._store()
    rooms_payload = store.load()
    room = next(item for item in rooms_payload["rooms"] if item["roomId"] == team["linkedChatRoomId"])
    room["participants"].append(
        {
            "participantId": f"agent:{beta['agentId']}",
            "agentId": beta["agentId"],
            "sessionId": beta["directSessionId"],
            "displayName": beta["displayName"],
            "enabled": True,
        }
    )
    store.save(rooms_payload)

    repaired = team_service.get_team(team["teamId"])
    room_after = chat_room_service.get_chat_room_detail(repaired["linkedChatRoomId"])

    assert [member["agentId"] for member in repaired["members"]] == [alpha["agentId"]]
    assert [participant["agentId"] for participant in room_after["participants"]] == [alpha["agentId"]]


def test_get_team_prunes_missing_members_from_derived_team_and_room(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team = team_service.create_team(name="系统团队", members=[{"agentId": alpha["agentId"], "role": "runner"}])
    missing_agent_id = "agent-missing-system"

    state = team_service._load_index()
    stored = next(item for item in state["teams"] if item["teamId"] == team["teamId"])
    stored["teamKind"] = "self_evolution"
    stored["teamSource"] = "self_evolution"
    stored["systemTeamKind"] = "self_evolution"
    stored["members"].append(
        {
            "memberId": "missing-member",
            "agentId": missing_agent_id,
            "agentName": "Missing",
            "role": "legacy",
            "agentStatus": "stale",
        }
    )
    team_service._save_index(state)

    canvas_path = team_service._team_canvas_path(team["teamId"])
    canvas = json.loads(canvas_path.read_text(encoding="utf-8"))
    canvas["nodes"].append(
        {
            "id": "missing-node",
            "label": "Missing",
            "type": "agent",
            "x": 480,
            "y": 120,
            "agentId": missing_agent_id,
            "role": "legacy",
        }
    )
    canvas_path.write_text(json.dumps(canvas, ensure_ascii=False), encoding="utf-8")

    store = chat_room_service._store()
    rooms_payload = store.load()
    room = next(item for item in rooms_payload["rooms"] if item["roomId"] == team["linkedChatRoomId"])
    room["participants"].append(
        {
            "participantId": f"agent:{missing_agent_id}",
            "agentId": missing_agent_id,
            "sessionId": "session-missing-system",
            "displayName": "Missing",
            "enabled": True,
        }
    )
    store.save(rooms_payload)

    repaired = team_service.get_team(team["teamId"])
    room_after = chat_room_service.get_chat_room_detail(repaired["linkedChatRoomId"])
    canvas_after = team_service.get_team_canvas(team["teamId"])

    assert [member["agentId"] for member in repaired["members"]] == [alpha["agentId"]]
    assert [participant["agentId"] for participant in room_after["participants"]] == [alpha["agentId"]]
    assert all(node.get("agentId") != missing_agent_id for node in canvas_after["nodes"])


def test_save_team_canvas_rejects_missing_edge_endpoint(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="Edge Team")
    canvas = team_service.get_team_canvas(team["teamId"])

    canvas["edges"] = [{"id": "bad", "source": "team-lead", "target": "missing"}]

    with pytest.raises(team_service.TeamServiceError, match="existing nodes"):
        team_service.save_team_canvas(team["teamId"], canvas)


def test_agent_config_workspace_includes_team_reference(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(agent_config_workspace_service, "_safe_prompt_workspace", lambda: {"templates": []})
    monkeypatch.setattr(agent_config_workspace_service, "_safe_config_workspace", lambda: {"modelOptions": []})
    monkeypatch.setattr(agent_config_workspace_service, "_safe_chat_rooms", lambda: [])
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team = team_service.create_team(name="Reference Team", members=[{"agentId": agent["agentId"], "role": "owner"}])

    workspace = agent_config_workspace_service.get_agent_config_workspace()

    enriched = next(item for item in workspace["agents"] if item["agentId"] == agent["agentId"])
    team_ref = next(item for item in enriched["references"] if item["kind"] == "team")
    assert team_ref["route"] == f"/teams?teamId={team['teamId']}"
    assert team_ref["sourceRef"]["owner"] == "TeamWorkflow"
    assert team_ref["sourceRef"]["canonicalEditRoute"] == f"/teams?teamId={team['teamId']}"
    assert team_ref["projectionEdit"]["canWrite"] is False
    assert team_ref["projectionEdit"]["mode"] == "deep_link_to_source"
    assert team_ref["projectionCanWrite"] is False
    assert workspace["summary"]["teamCount"] == 1


def test_send_team_message_targets_active_team_members_only(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    outsider = agent_directory_service.create_agent_instance(display_name="Outsider", direct_session_id="session-outsider")
    team = team_service.create_team(
        name="Broadcast Team",
        members=[{"agentId": alpha["agentId"]}, {"agentId": beta["agentId"]}],
    )
    agent_directory_service.archive_agent_instance(beta["agentId"])
    monkeypatch.setattr(
        project_agent_bus_service.session_service,
        "wake_agent_for_inbox_message",
        lambda message: {
            "wakeRequested": True,
            "wakeStatus": "started",
            "messageId": message["messageId"],
            "targetAgentId": message["targetAgentId"],
            "targetSessionId": message["targetSessionId"],
            "turnId": "turn-team",
            "reason": "",
        },
    )

    event = team_service.send_team_message(team["teamId"], content="团队成员同步一下")

    assert event["targetScope"] == "agents"
    assert event["targetAgentIds"] == [alpha["agentId"]]
    assert event["metadata"]["teamId"] == team["teamId"]
    assert agent_directory_service.count_agent_inbox_messages_for_agent(alpha["agentId"]) == 1
    assert agent_directory_service.count_agent_inbox_messages_for_agent(beta["agentId"]) == 0
    assert agent_directory_service.count_agent_inbox_messages_for_agent(outsider["agentId"]) == 0


def test_team_message_is_visible_in_project_bus_timeline_by_team_metadata(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team = team_service.create_team(name="Timeline Team", members=[{"agentId": alpha["agentId"]}])
    monkeypatch.setattr(project_agent_bus_service.session_service, "wake_agent_for_inbox_message", lambda message: {})

    event = team_service.send_team_message(team["teamId"], content="记录到团队广播历史")
    timeline = project_agent_bus_service.list_project_agent_bus_events()

    team_events = [
        item
        for item in timeline["events"]
        if item.get("metadata", {}).get("teamId") == team["teamId"]
    ]
    assert team_events[-1]["eventId"] == event["eventId"]
    assert team_events[-1]["metadata"]["source"] == "team"
    assert team_events[-1]["targetAgentIds"] == [alpha["agentId"]]


def test_send_team_message_requires_active_members(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="Empty Team")

    with pytest.raises(team_service.TeamServiceError, match="no active Agent members"):
        team_service.send_team_message(team["teamId"], content="没人会收到")
