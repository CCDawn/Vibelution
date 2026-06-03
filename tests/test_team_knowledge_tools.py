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
        tool_policy={
            "allowedTools": [
                "knowledge_query_tool",
                "knowledge_proposal_tool",
                "knowledge_ingestion_tool",
                "knowledge_governance_tasks_tool",
                "knowledge_operations_health_tool",
                "knowledge_governance_plan_tool",
                "knowledge_steward_recommendations_tool",
                "knowledge_steward_workbench_tool",
            ]
        },
        memory_policy={
            "readKnowledgeBaseIds": [base["knowledgeBaseId"]],
            "proposeKnowledgeBaseIds": [base["knowledgeBaseId"]],
            "rateKnowledgeBaseIds": [base["knowledgeBaseId"]],
        },
    )
    return {"lead": lead, "member": member, "team": team, "base": base}


def test_team_knowledge_tools_are_llm_facing_but_hidden_without_explicit_allow(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="Default Agent")
    tools = [
        tool
        for tool in create_llm_facing_tools()
        if tool.name
        in {
            "knowledge_query_tool",
            "knowledge_rag_retrieve_tool",
            "knowledge_proposal_tool",
            "knowledge_rating_suggestion_tool",
            "knowledge_operations_health_tool",
            "knowledge_governance_plan_tool",
            "knowledge_steward_recommendations_tool",
            "knowledge_steward_workbench_tool",
            "agent_message_tool",
        }
    ]

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-tools"):
        visible = agent_directory_service.filter_llm_tools_for_current_agent(tools)

    assert {tool.name for tool in tools} == {
        "knowledge_query_tool",
        "knowledge_rag_retrieve_tool",
        "knowledge_proposal_tool",
        "knowledge_rating_suggestion_tool",
        "knowledge_operations_health_tool",
        "knowledge_governance_plan_tool",
        "knowledge_steward_recommendations_tool",
        "knowledge_steward_workbench_tool",
        "agent_message_tool",
    }
    assert "knowledge_query_tool" not in [tool.name for tool in visible]
    assert "knowledge_rag_retrieve_tool" not in [tool.name for tool in visible]
    assert "knowledge_proposal_tool" not in [tool.name for tool in visible]
    assert "knowledge_rating_suggestion_tool" not in [tool.name for tool in visible]
    assert "knowledge_operations_health_tool" not in [tool.name for tool in visible]
    assert "knowledge_governance_plan_tool" not in [tool.name for tool in visible]
    assert "knowledge_steward_recommendations_tool" not in [tool.name for tool in visible]
    assert "knowledge_steward_workbench_tool" not in [tool.name for tool in visible]


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


def test_knowledge_ingestion_tool_submits_standard_package(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.knowledge_ingestion_tool(
                knowledge_base_id=env["base"]["knowledgeBaseId"],
                source_type="external_search_refinement",
                source_ref_json='{"url":"https://example.test","query":"memory"}',
                proposal_title="Tool ingestion package",
                excerpt="Search adapter output can be submitted as pending knowledge.",
                tags="ingestion,tool",
            )
        )

    assert result["ok"] is True
    assert result["package"]["proposal"]["status"] == "pending"
    assert result["package"]["sourceArtifact"]["sourceType"] == "external_search_refinement"


def test_knowledge_governance_tasks_tool_reads_open_queue(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    team_knowledge_service.create_refinement_proposal(
        env["base"]["knowledgeBaseId"],
        source_artifact_ids=[],
        proposed_by_agent_id=env["member"]["agentId"],
        title="Open governance task",
        content="Governance task tool should see pending proposal.",
    )

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(team_knowledge_tools.knowledge_governance_tasks_tool(status="open"))

    assert result["ok"] is True
    assert result["summary"]["proposalReviewCount"] == 1
    assert result["tasks"][0]["taskType"] == "proposal_review"


def test_knowledge_steward_recommendations_tool_reads_read_only_actions(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    proposal = team_knowledge_service.create_refinement_proposal(
        env["base"]["knowledgeBaseId"],
        source_artifact_ids=[],
        proposed_by_agent_id=env["member"]["agentId"],
        title="Steward tool proposal",
        content="Steward recommendations should suggest review without applying.",
    )

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(team_knowledge_tools.knowledge_steward_recommendations_tool(limit=4))

    assert result["ok"] is True
    assert result["operatingBoundary"]["recommendationsOnly"] is True
    assert result["operatingBoundary"]["canDirectlyApplyKnowledge"] is False
    assert any(item["targetId"] == proposal["proposalId"] for item in result["recommendations"])
    assert result["recommendations"][0]["recommendedAction"] == "review_proposal"


def test_knowledge_steward_workbench_tool_reads_grouped_workflow(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    source = team_knowledge_service.create_source_artifact(
        env["base"]["knowledgeBaseId"],
        source_type="manual_user_entry",
        source_ref={"note": "tool workbench source"},
        title="Tool workbench source",
        actor_agent_id=env["member"]["agentId"],
    )

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(team_knowledge_tools.knowledge_steward_workbench_tool(limit=4))

    assert result["ok"] is True
    assert result["operatingBoundary"]["recommendationsOnly"] is True
    assert result["operatingBoundary"]["canDirectlyApplyKnowledge"] is False
    assert any(stage["stageId"] == "source_to_proposal" for stage in result["stages"])
    assert any(action["targetId"] == source["sourceArtifactId"] for action in result["nextActions"])


def test_knowledge_operations_health_and_plan_tools_are_read_only(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    source = team_knowledge_service.create_source_artifact(
        env["base"]["knowledgeBaseId"],
        source_type="manual_user_entry",
        source_ref={"note": "health tool"},
        title="Health tool source",
        actor_agent_id=env["member"]["agentId"],
    )

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        health = json.loads(team_knowledge_tools.knowledge_operations_health_tool())
        plan = json.loads(team_knowledge_tools.knowledge_governance_plan_tool(limit=3))

    assert health["ok"] is True
    assert health["summary"]["orphanSourceCount"] == 1
    assert source["sourceArtifactId"] in health["knowledgeBases"][0]["nextReviewTargetIds"]
    assert plan["ok"] is True
    assert plan["mode"] == "recommendations_only"
    assert plan["operatingBoundary"]["planOnly"] is True
    assert all(action["mutatesFormalKnowledge"] is False for action in plan["actions"])
    assert team_knowledge_service.list_knowledge_items(env["base"]["knowledgeBaseId"], agent_id=env["member"]["agentId"])["summary"]["itemCount"] == 0


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


def test_knowledge_rag_retrieve_tool_returns_contexts_with_citations(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    agent_directory_service.update_agent_instance(
        env["member"]["agentId"],
        tool_policy={"allowedTools": ["knowledge_rag_retrieve_tool"]},
        memory_policy={"readKnowledgeBaseIds": [env["base"]["knowledgeBaseId"]]},
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        env["base"]["knowledgeBaseId"],
        source_artifact_ids=[],
        proposed_by_agent_id=env["member"]["agentId"],
        title="RAG tool knowledge",
        content="RAG tool retrieval should return cited context candidates.",
        tags=["rag-tool"],
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.knowledge_rag_retrieve_tool(
                query="rag tool context",
                knowledge_base_id=env["base"]["knowledgeBaseId"],
                retrieval_mode="hybrid",
                provider="local",
                top_k=3,
                max_context_chars=240,
            )
        )

    assert result["ok"] is True
    assert result["summary"]["contextCount"] == 1
    assert result["summary"]["citationCount"] == 1
    assert result["contexts"][0]["source"]["knowledgeItemId"] == reviewed["item"]["knowledgeItemId"]
    assert result["citations"][0]["contextId"] == result["contexts"][0]["contextId"]
    assert result["retrievalPolicy"]["injectsPromptByDefault"] is False


def test_knowledge_rag_retrieve_tool_honors_memory_policy_base_ids(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    agent_directory_service.update_agent_instance(
        env["member"]["agentId"],
        tool_policy={"allowedTools": ["knowledge_rag_retrieve_tool"]},
        memory_policy={"readKnowledgeBaseIds": [env["base"]["knowledgeBaseId"]]},
    )
    other_base = team_knowledge_service.create_knowledge_base(env["team"]["teamId"], name="Other RAG KB", actor_agent_id=env["lead"]["agentId"])

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.knowledge_rag_retrieve_tool(
                query="",
                knowledge_base_id=other_base["knowledgeBaseId"],
            )
        )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["error"] == "knowledge_base_not_in_memory_policy"


def test_knowledge_rating_suggestion_tool_submits_pending_suggestion_only(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    agent_directory_service.update_agent_instance(
        env["lead"]["agentId"],
        tool_policy={"allowedTools": ["knowledge_query_tool", "knowledge_proposal_tool", "knowledge_rating_suggestion_tool"]},
        memory_policy={"rateKnowledgeBaseIds": [env["base"]["knowledgeBaseId"]]},
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        env["base"]["knowledgeBaseId"],
        source_artifact_ids=[],
        proposed_by_agent_id=env["member"]["agentId"],
        title="Tool rating target",
        content="Rating suggestion tools must not directly update formal knowledge.",
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )

    with agent_directory_service.active_agent_runtime(env["lead"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.knowledge_rating_suggestion_tool(
                knowledge_base_id=env["base"]["knowledgeBaseId"],
                target_type="knowledge_item",
                knowledge_item_id=reviewed["item"]["knowledgeItemId"],
                importance_level="high",
                confidence=0.88,
                stability="stable",
                review_priority="elevated",
                marking_reason="Useful operational knowledge.",
            )
        )

    item = team_knowledge_service.list_knowledge_items(env["base"]["knowledgeBaseId"], agent_id=env["member"]["agentId"])["items"][0]
    assert result["ok"] is True
    assert result["suggestion"]["status"] == "pending"
    assert item["importanceLevel"] == "medium"
