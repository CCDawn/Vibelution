import json

from core.web.services import agent_directory_service, chat_room_service, team_knowledge_service, team_service
from tools import team_knowledge_tools
from tools.Key_Tools import create_llm_facing_tools


def _seed_team_knowledge(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    lead = agent_directory_service.create_agent_instance(display_name="Knowledge Lead")
    member = agent_directory_service.create_agent_instance(display_name="Knowledge Member")
    team = team_service.create_team(
        name="Tool Knowledge Team",
        members=[
            {"agentId": lead["agentId"], "role": "lead"},
            {"agentId": member["agentId"], "role": "member"},
        ],
    )
    base = team_knowledge_service.create_knowledge_base(team["teamId"], name="Tool KB", actor_agent_id=lead["agentId"])
    agent_directory_service.update_agent_instance(
        member["agentId"],
        tool_policy={"allowedTools": ["knowledge_query_tool", "knowledge_proposal_tool"]},
        memory_policy={
            "readKnowledgeBaseIds": [base["knowledgeBaseId"]],
            "proposeKnowledgeBaseIds": [base["knowledgeBaseId"]],
        },
    )
    return {"lead": lead, "member": member, "team": team, "base": base}


def test_team_knowledge_tools_are_llm_facing_but_hidden_without_explicit_allow(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="Default Agent")
    tools = [
        tool
        for tool in create_llm_facing_tools()
        if tool.name in {"knowledge_query_tool", "knowledge_proposal_tool", "agent_message_tool"}
    ]

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-tools"):
        visible = agent_directory_service.filter_llm_tools_for_current_agent(tools)

    assert {tool.name for tool in tools} == {"knowledge_query_tool", "knowledge_proposal_tool", "agent_message_tool"}
    assert "knowledge_query_tool" not in [tool.name for tool in visible]
    assert "knowledge_proposal_tool" not in [tool.name for tool in visible]


def test_knowledge_proposal_tool_submits_source_and_pending_candidate(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.knowledge_proposal_tool(
                knowledge_base_id=env["base"]["knowledgeBaseId"],
                source_type="manual_user_entry",
                source_ref_json='{"note":"tool source"}',
                proposal_title="Tool submitted knowledge",
                proposal_content="Knowledge proposal tool submits candidates for review.",
                tags="tool,knowledge",
            )
        )

    assert result["ok"] is True
    assert result["proposal"]["status"] == "pending"
    items = team_knowledge_service.list_knowledge_items(env["base"]["knowledgeBaseId"], agent_id=env["member"]["agentId"])
    assert items["summary"]["itemCount"] == 0


def test_knowledge_query_tool_reads_applied_items_only(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    proposal = team_knowledge_service.create_refinement_proposal(
        env["base"]["knowledgeBaseId"],
        source_artifact_ids=[],
        proposed_by_agent_id=env["member"]["agentId"],
        title="Applied tool knowledge",
        content="Formal team knowledge should be readable by the query tool.",
        tags=["query-tool"],
    )
    team_knowledge_service.review_refinement_proposal(
        env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.knowledge_query_tool(
                query="formal team",
                knowledge_base_id=env["base"]["knowledgeBaseId"],
                limit=5,
            )
        )

    assert result["ok"] is True
    assert result["summary"]["resultCount"] == 1
    assert result["results"][0]["title"] == "Applied tool knowledge"
    assert result["results"][0]["knowledgeBaseId"] == env["base"]["knowledgeBaseId"]


def test_knowledge_query_tool_honors_memory_policy_base_ids(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    other_base = team_knowledge_service.create_knowledge_base(env["team"]["teamId"], name="Other KB", actor_agent_id=env["lead"]["agentId"])

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.knowledge_query_tool(
                query="",
                knowledge_base_id=other_base["knowledgeBaseId"],
            )
        )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["error"] == "knowledge_base_not_in_memory_policy"
