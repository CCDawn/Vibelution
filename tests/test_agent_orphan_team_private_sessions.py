import pytest

from core.web.services import agent_directory_service, chat_room_service, project_agent_bus_service, session_service, team_service


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)


def test_challenge_cup_repair_detects_orphan_active_team_private_agents(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team_service.ensure_challenge_cup_research_team_agents(purge_stale=True)
    stale = agent_directory_service.create_agent_instance(
        display_name="旧资料发现",
        direct_session_id="session-old-discovery",
        primary_mode="research",
        role_key="challenge_cup_data_discovery",
        created_by=team_service.CHALLENGE_CUP_RESEARCH_TEAM_AGENT_CREATED_BY,
        metadata={
            "fixedRole": True,
            "challengeCupTeamId": team_service.CHALLENGE_CUP_RESEARCH_TEAM_ID,
            "challengeCupTeamManagedVersion": 1,
            "challengeCupTeamRole": "data_discovery",
            "challengeCupTeamRoleKey": "challenge_cup_data_discovery",
            "researchAgentKey": "challenge_cup_data_discovery",
            "researchTeamRole": "data_discovery",
            "researchTeamRoleKey": "challenge_cup_data_discovery",
            "conversationIndexKind": agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
            "conversationIndexVisibility": agent_directory_service.CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE,
            "showInSessionIndex": False,
            "directSessionVisibility": "active_session",
        },
    )

    assert team_service.challenge_cup_research_team_agents_need_repair() is True
    with pytest.raises(agent_directory_service.AgentDirectoryError, match="Protected core Agent"):
        agent_directory_service.archive_agent_instance(stale["agentId"])

    repaired = team_service.ensure_challenge_cup_research_team_agents(purge_stale=True)

    assert stale["agentId"] in repaired["purgedAgentIds"]
    assert agent_directory_service.get_agent(stale["agentId"], include_archived=True) is None
    assert team_service.challenge_cup_research_team_agents_need_repair() is False
    ordinary_session_ids = {session.get("id") for session in session_service.list_sessions(include_hidden_internal=False)}
    hidden_session_ids = {session.get("id") for session in session_service.list_sessions(include_hidden_internal=True)}
    assert "session-old-discovery" not in ordinary_session_ids
    assert "session-old-discovery" in hidden_session_ids


def test_knowledge_expansion_repair_detects_orphan_active_team_private_agents(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team_service.ensure_knowledge_expansion_team_agents(purge_stale=True)
    stale = agent_directory_service.create_agent_instance(
        display_name="旧资料审查",
        direct_session_id="session-old-quality",
        primary_mode="research",
        role_key="knowledge_expansion_source_quality",
        created_by=team_service.KNOWLEDGE_EXPANSION_TEAM_AGENT_CREATED_BY,
        metadata={
            "fixedRole": True,
            "knowledgeExpansionTeamId": team_service.KNOWLEDGE_EXPANSION_TEAM_ID,
            "knowledgeExpansionTeamManagedVersion": 1,
            "knowledgeExpansionTeamRole": "source_quality",
            "knowledgeExpansionTeamRoleKey": "knowledge_expansion_source_quality",
            "researchAgentKey": "knowledge_expansion_source_quality",
            "researchTeamRole": "source_quality",
            "researchTeamRoleKey": "knowledge_expansion_source_quality",
            "conversationIndexKind": agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
            "conversationIndexVisibility": agent_directory_service.CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE,
            "showInSessionIndex": False,
            "directSessionVisibility": "active_session",
        },
    )

    assert team_service.knowledge_expansion_team_agents_need_repair() is True
    with pytest.raises(agent_directory_service.AgentDirectoryError, match="Protected core Agent"):
        agent_directory_service.archive_agent_instance(stale["agentId"])

    repaired = team_service.ensure_knowledge_expansion_team_agents(purge_stale=True)

    assert stale["agentId"] in repaired["purgedAgentIds"]
    assert agent_directory_service.get_agent(stale["agentId"], include_archived=True) is None
    assert team_service.knowledge_expansion_team_agents_need_repair() is False
    ordinary_session_ids = {session.get("id") for session in session_service.list_sessions(include_hidden_internal=False)}
    hidden_session_ids = {session.get("id") for session in session_service.list_sessions(include_hidden_internal=True)}
    assert "session-old-quality" not in ordinary_session_ids
    assert "session-old-quality" in hidden_session_ids


def test_knowledge_steward_repair_removes_stale_team_private_metadata(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent_directory_service.save_state(
        {
            "agents": [
                {
                    "agentId": agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID,
                    "agentCode": "A001",
                    "displayName": "唐南栀",
                    "directSessionId": agent_directory_service.KNOWLEDGE_STEWARD_DIRECT_SESSION_ID,
                    "primaryMode": "general",
                    "roleKey": agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY,
                    "workspacePath": "workspace/agents/agent-knowledge-steward",
                    "status": "active",
                    "createdBy": "system_repair",
                    "metadata": {
                        "systemRole": agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY,
                        "protected": True,
                        "challengeCupTeamId": team_service.CHALLENGE_CUP_RESEARCH_TEAM_ID,
                        "challengeCupTeamRole": "knowledge_steward",
                        "conversationIndexKind": agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
                        "conversationIndexVisibility": agent_directory_service.CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE,
                        "showInSessionIndex": False,
                    },
                }
            ]
        }
    )

    agent_directory_service.repair_agent_directory()

    steward = agent_directory_service.get_agent(agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID)
    metadata = steward["metadata"]
    assert "challengeCupTeamId" not in metadata
    assert "challengeCupTeamRole" not in metadata
    assert metadata["conversationIndexKind"] == agent_directory_service.CONVERSATION_INDEX_KIND_PERSONAL_AGENT
    assert metadata["conversationIndexVisibility"] == agent_directory_service.CONVERSATION_INDEX_VISIBILITY_USER_VISIBLE
    assert steward["conversationIndexKind"] == agent_directory_service.CONVERSATION_INDEX_KIND_PERSONAL_AGENT
