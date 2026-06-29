import json

import pytest

from core.web.services import agent_directory_service, chat_room_service, team_knowledge_service, team_service
from tools import team_knowledge_tools
from tools.Key_Tools import create_llm_facing_tools


@pytest.fixture(autouse=True)
def _isolate_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))


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
    base_ref = base.get("scopedKnowledgeBaseId") or base["knowledgeBaseId"]
    agent_directory_service.update_agent_instance(
        member["agentId"],
        tool_policy={
            "allowedTools": [
                "unified_memory_search_tool",
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
            "readKnowledgeBaseIds": [base_ref],
            "proposeKnowledgeBaseIds": [base_ref],
            "rateKnowledgeBaseIds": [base_ref],
        },
    )
    return {"lead": lead, "member": member, "team": team, "base": base}


def _promote_central_source(env: dict, *, source_type: str = "manual_user_entry", title: str = "Tool source", source_ref: dict | None = None) -> dict:
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        env["team"]["teamId"],
        source_type=source_type,
        source_ref=source_ref or {"note": title},
        original_content="Tool test source content.",
        original_filename="tool-source.txt",
        title=title,
        actor_agent_id=env["member"]["agentId"],
    )
    reviewed = team_knowledge_service.review_owner_inbox_source(
        "team",
        env["team"]["teamId"],
        inbox_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )
    return reviewed["centralSource"]


def _source_artifact(env: dict, *, title: str = "Tool source", knowledge_base_id: str = "") -> dict:
    central_source = _promote_central_source(env, title=title)
    return team_knowledge_service.create_source_artifact_from_central_source(
        knowledge_base_id or _kb_ref(env),
        central_source["centralSourceId"],
        actor_agent_id=env["member"]["agentId"],
        title=title,
    )


def _source_ids(env: dict, *, title: str = "Tool source", knowledge_base_id: str = "") -> list[str]:
    source = _source_artifact(env, title=title, knowledge_base_id=knowledge_base_id)
    return [source["sourceArtifactId"]]


def _kb_ref(env: dict) -> str:
    return str(env["base"].get("scopedKnowledgeBaseId") or env["base"]["knowledgeBaseId"])


_LLM_FACING_KNOWLEDGE_TOOL_NAMES = {
    "unified_memory_search_tool",
    "knowledge_proposal_tool",
    "knowledge_rating_suggestion_tool",
    "knowledge_operations_health_tool",
    "knowledge_governance_plan_tool",
    "knowledge_steward_recommendations_tool",
    "knowledge_steward_workbench_tool",
}
_LLM_FACING_COMMUNICATION_TOOL_NAMES = {
    "agent_message_tool",
}
_LLM_FACING_TOOL_NAMES = _LLM_FACING_KNOWLEDGE_TOOL_NAMES | _LLM_FACING_COMMUNICATION_TOOL_NAMES


def _llm_facing_knowledge_tools():
    return [
        tool
        for tool in create_llm_facing_tools()
        if tool.name in _LLM_FACING_TOOL_NAMES
    ]


def test_team_knowledge_tools_are_hidden_without_explicit_allow(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="Default Agent")
    tools = _llm_facing_knowledge_tools()

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-tools"):
        visible = agent_directory_service.filter_llm_tools_for_current_agent(tools)

    assert {tool.name for tool in tools} == _LLM_FACING_TOOL_NAMES
    assert {tool.name for tool in visible} == _LLM_FACING_COMMUNICATION_TOOL_NAMES
    assert not ({tool.name for tool in visible} & _LLM_FACING_KNOWLEDGE_TOOL_NAMES)


def test_team_knowledge_tools_are_llm_facing_with_explicit_allow(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="Knowledge Tools Agent")
    tools = _llm_facing_knowledge_tools()
    allowed_names = [tool.name for tool in tools]
    agent_directory_service.update_agent_instance(
        agent["agentId"],
        tool_policy={"allowedTools": allowed_names},
    )

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-tools"):
        visible = agent_directory_service.filter_llm_tools_for_current_agent(tools)

    assert {tool.name for tool in tools} == _LLM_FACING_TOOL_NAMES
    assert [tool.name for tool in visible] == [tool.name for tool in tools]


def test_knowledge_proposal_tool_submits_source_and_pending_candidate(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    central_source = _promote_central_source(env, title="Tool submitted source")

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.knowledge_proposal_tool(
                knowledge_base_id=_kb_ref(env),
                central_source_id=central_source["centralSourceId"],
                source_type="manual_user_entry",
                source_ref_json='{"note":"tool source"}',
                proposal_title="Tool submitted knowledge",
                proposal_content="Knowledge proposal tool submits candidates for review.",
                tags="tool,knowledge",
            )
        )

    assert result["ok"] is True
    assert result["proposal"]["status"] == "pending"
    items = team_knowledge_service.list_knowledge_items(_kb_ref(env), agent_id=env["member"]["agentId"])
    assert items["summary"]["itemCount"] == 0


def test_knowledge_ingestion_tool_submits_standard_package(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    central_source = _promote_central_source(
        env,
        source_type="external_search_refinement",
        source_ref={"url": "https://example.test", "query": "memory"},
        title="Tool ingestion source",
    )

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.knowledge_ingestion_tool(
                knowledge_base_id=_kb_ref(env),
                central_source_id=central_source["centralSourceId"],
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


def test_knowledge_ingestion_tool_directly_ingests_reviewed_inbox_source(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        env["team"]["teamId"],
        source_type="manual_user_entry",
        source_ref={"note": "tool direct source"},
        original_content="Tool direct source content.",
        original_filename="tool-direct-source.txt",
        title="Tool direct source",
        actor_agent_id=env["member"]["agentId"],
    )

    with agent_directory_service.active_agent_runtime(env["lead"]["agentId"], session_id="session-knowledge-lead"):
        result = json.loads(
            team_knowledge_tools.knowledge_ingestion_tool(
                knowledge_base_id=_kb_ref(env),
                source_type="manual_user_entry",
                source_ref_json='{"note":"tool direct source"}',
                proposal_title="Tool direct source becomes memory",
                proposal_content="The ingestion tool can screen an inbox source and create a formal KnowledgeItem directly.",
                inbox_source_id=inbox_source["inboxSourceId"],
                owner_type="team",
                owner_id=env["team"]["teamId"],
                resolution_note="筛选通过，直接入库。",
                tags="direct-ingestion,tool",
            )
        )

    items = team_knowledge_service.list_knowledge_items(_kb_ref(env), agent_id=env["member"]["agentId"])

    assert result["ok"] is True
    assert result["status"] == "ingested"
    assert result["directIngestion"]["item"]["title"] == "Tool direct source becomes memory"
    assert items["summary"]["itemCount"] == 1


def test_knowledge_governance_tasks_tool_reads_open_queue(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    team_knowledge_service.create_refinement_proposal(
        _kb_ref(env),
        source_artifact_ids=_source_ids(env, title="Open governance task source"),
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
        _kb_ref(env),
        source_artifact_ids=_source_ids(env, title="Steward tool source"),
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
    source = _source_artifact(env, title="Tool workbench source")

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(team_knowledge_tools.knowledge_steward_workbench_tool(limit=4))

    assert result["ok"] is True
    assert result["operatingBoundary"]["recommendationsOnly"] is True
    assert result["operatingBoundary"]["canDirectlyApplyKnowledge"] is False
    assert any(stage["stageId"] == "source_to_proposal" for stage in result["stages"])
    assert any(action["targetId"] == source["sourceArtifactId"] for action in result["nextActions"])


def test_knowledge_operations_health_and_plan_tools_are_read_only(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    source = _source_artifact(env, title="Health tool source")

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
    assert team_knowledge_service.list_knowledge_items(_kb_ref(env), agent_id=env["member"]["agentId"])["summary"]["itemCount"] == 0


def test_unified_memory_search_tool_reads_applied_items_only(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    proposal = team_knowledge_service.create_refinement_proposal(
        _kb_ref(env),
        source_artifact_ids=_source_ids(env, title="Applied tool source"),
        proposed_by_agent_id=env["member"]["agentId"],
        title="Applied tool knowledge",
        content="Formal team knowledge should be readable by the query tool.",
        tags=["query-tool"],
    )
    team_knowledge_service.review_refinement_proposal(
        _kb_ref(env),
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="formal team",
                query_mode="hybrid",
                knowledge_base_id=_kb_ref(env),
                limit=5,
            )
        )

    assert result["ok"] is True
    assert result["summary"]["resultCount"] == 1
    assert result["results"][0]["title"] == "Applied tool knowledge"
    assert result["results"][0]["knowledgeBaseId"] == env["base"]["knowledgeBaseId"]


def test_unified_memory_search_tool_returns_standard_results(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    proposal = team_knowledge_service.create_refinement_proposal(
        _kb_ref(env),
        source_artifact_ids=_source_ids(env, title="Unified search source"),
        proposed_by_agent_id=env["member"]["agentId"],
        title="Unified search knowledge",
        content="Unified search lets agents query formal knowledge with one stable tool.",
        tags=["unified-search"],
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        _kb_ref(env),
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="stable tool",
                query_mode="hybrid",
                knowledge_base_id=_kb_ref(env),
                tags="unified-search",
                limit=5,
            )
        )

    assert result["ok"] is True
    assert result["request"]["effectiveQueryMode"] == "hybrid"
    assert result["request"]["backend"] == "local_hybrid"
    assert result["summary"]["resultCount"] == 1
    assert result["results"][0]["resultType"] == "knowledge_item"
    assert result["results"][0]["knowledgeItemId"] == reviewed["item"]["knowledgeItemId"]
    assert result["results"][0]["searchBackend"] == "local_hybrid"
    assert result["retrievalPolicy"]["mutatesFormalKnowledge"] is False


def test_unified_memory_search_tool_supports_bm25_mode(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    sparse_proposal = team_knowledge_service.create_refinement_proposal(
        _kb_ref(env),
        source_artifact_ids=_source_ids(env, title="Sparse BM25 tool source"),
        proposed_by_agent_id=env["member"]["agentId"],
        title="Sparse benchmark note",
        content="Benchmark memory retrieval appears once before unrelated operational text.",
        tags=["bm25-tool"],
    )
    dense_proposal = team_knowledge_service.create_refinement_proposal(
        _kb_ref(env),
        source_artifact_ids=_source_ids(env, title="Dense BM25 tool source"),
        proposed_by_agent_id=env["member"]["agentId"],
        title="Dense benchmark memory retrieval",
        content="Benchmark memory retrieval repeats benchmark memory retrieval evidence for BM25 ranking.",
        tags=["bm25-tool"],
    )
    sparse_item = team_knowledge_service.review_refinement_proposal(
        _kb_ref(env),
        sparse_proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )["item"]
    dense_item = team_knowledge_service.review_refinement_proposal(
        _kb_ref(env),
        dense_proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )["item"]

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="benchmark memory retrieval",
                query_mode="bm25",
                knowledge_base_id=_kb_ref(env),
                limit=2,
            )
        )

    assert result["ok"] is True
    assert result["request"]["effectiveQueryMode"] == "bm25"
    assert result["request"]["backend"] == "local_bm25"
    assert [item["knowledgeItemId"] for item in result["results"]] == [
        dense_item["knowledgeItemId"],
        sparse_item["knowledgeItemId"],
    ]
    assert result["results"][0]["score"] > result["results"][1]["score"] > 0
    assert result["results"][0]["matchReason"] == "bm25"


def test_unified_memory_search_tool_supports_regex_and_rag_modes(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    proposal = team_knowledge_service.create_refinement_proposal(
        _kb_ref(env),
        source_artifact_ids=_source_ids(env, title="Unified regex source"),
        proposed_by_agent_id=env["member"]["agentId"],
        title="Unified regex knowledge",
        content="Regex mode and RAG mode both return the unified result protocol.",
        tags=["unified-regex"],
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        _kb_ref(env),
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        regex_result = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="Regex mode",
                query_mode="regex",
                knowledge_base_id=_kb_ref(env),
            )
        )
        rag_result = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="rag mode unified protocol",
                query_mode="rag",
                knowledge_base_id=_kb_ref(env),
                limit=3,
            )
        )

    assert regex_result["ok"] is True
    assert regex_result["request"]["backend"] == "local_regex"
    assert regex_result["results"][0]["matchReason"] == "regex_match"
    assert rag_result["ok"] is True
    assert rag_result["request"]["backend"] == "local_rag"
    assert rag_result["summary"]["citationCount"] == 1
    assert rag_result["results"][0]["resultType"] == "rag_context"
    assert rag_result["results"][0]["knowledgeItemId"] == reviewed["item"]["knowledgeItemId"]


def test_unified_memory_search_tool_honors_memory_policy_base_ids(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    other_base = team_knowledge_service.create_knowledge_base(env["team"]["teamId"], name="Other Unified KB", actor_agent_id=env["lead"]["agentId"])

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="",
                query_mode="metadata",
                knowledge_base_id=other_base["scopedKnowledgeBaseId"],
            )
        )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["error"] == "knowledge_base_not_in_memory_policy"


def test_unified_memory_search_tool_limits_unscoped_search_to_memory_policy(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    other_base = team_knowledge_service.create_knowledge_base(
        env["team"]["teamId"],
        name="Blocked Unified KB",
        actor_agent_id=env["lead"]["agentId"],
    )
    allowed_proposal = team_knowledge_service.create_refinement_proposal(
        _kb_ref(env),
        source_artifact_ids=_source_ids(env, title="Allowed unified source"),
        proposed_by_agent_id=env["member"]["agentId"],
        title="Allowed unified knowledge",
        content="Unified global search may read this memory-policy-allowed knowledge.",
        tags=["unified-policy"],
    )
    blocked_proposal = team_knowledge_service.create_refinement_proposal(
        other_base["scopedKnowledgeBaseId"],
        source_artifact_ids=_source_ids(
            env,
            title="Blocked unified source",
            knowledge_base_id=other_base["scopedKnowledgeBaseId"],
        ),
        proposed_by_agent_id=env["lead"]["agentId"],
        title="Blocked unified knowledge",
        content="Unified global search must not return this memory-policy-blocked knowledge.",
        tags=["unified-policy"],
    )
    allowed_item = team_knowledge_service.review_refinement_proposal(
        _kb_ref(env),
        allowed_proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )["item"]
    blocked_item = team_knowledge_service.review_refinement_proposal(
        other_base["scopedKnowledgeBaseId"],
        blocked_proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )["item"]

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="Unified global search",
                query_mode="hybrid",
                limit=10,
            )
        )

    result_item_ids = {item["knowledgeItemId"] for item in result["results"]}
    assert result["ok"] is True
    assert allowed_item["knowledgeItemId"] in result_item_ids
    assert blocked_item["knowledgeItemId"] not in result_item_ids
    assert {item["knowledgeBaseId"] for item in result["results"]} == {env["base"]["knowledgeBaseId"]}


def test_unified_memory_search_tool_honors_requested_base_memory_policy_ids(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    other_base = team_knowledge_service.create_knowledge_base(env["team"]["teamId"], name="Other KB", actor_agent_id=env["lead"]["agentId"])

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="",
                query_mode="metadata",
                knowledge_base_id=other_base["scopedKnowledgeBaseId"],
            )
        )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["error"] == "knowledge_base_not_in_memory_policy"


def test_unified_memory_search_tool_honors_owner_scoped_memory_policy_ids(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    second_lead = agent_directory_service.create_agent_instance(display_name="Second Knowledge Lead")
    second_team = team_service.create_team(
        name="Second Tool Knowledge Team",
        members=[{"agentId": second_lead["agentId"], "role": "lead"}],
    )
    second_base = team_knowledge_service.create_knowledge_base(
        second_team["teamId"],
        name="Tool KB",
        actor_agent_id=second_lead["agentId"],
        acl={"grants": {"read": [env["member"]["agentId"]]}},
    )
    agent_directory_service.update_agent_instance(
        env["member"]["agentId"],
        tool_policy={"allowedTools": ["unified_memory_search_tool"]},
        memory_policy={"readKnowledgeBaseIds": [env["base"]["scopedKnowledgeBaseId"]]},
    )

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        allowed = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="",
                query_mode="metadata",
                knowledge_base_id=env["base"]["scopedKnowledgeBaseId"],
            )
        )
        blocked_scoped = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="",
                query_mode="metadata",
                knowledge_base_id=second_base["scopedKnowledgeBaseId"],
            )
        )
        blocked_raw = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="",
                query_mode="metadata",
                knowledge_base_id=env["base"]["knowledgeBaseId"],
            )
        )

    assert env["base"]["knowledgeBaseId"] == second_base["knowledgeBaseId"]
    assert allowed["ok"] is True
    assert blocked_scoped["ok"] is False
    assert blocked_scoped["error"] == "knowledge_base_not_in_memory_policy"
    assert blocked_raw["ok"] is False
    assert blocked_raw["error"] == "knowledge_base_not_in_memory_policy"


def test_unified_memory_search_tool_returns_rag_results_with_citations(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    agent_directory_service.update_agent_instance(
        env["member"]["agentId"],
        tool_policy={"allowedTools": ["unified_memory_search_tool"]},
        memory_policy={"readKnowledgeBaseIds": [_kb_ref(env)]},
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        _kb_ref(env),
        source_artifact_ids=_source_ids(env, title="RAG tool source"),
        proposed_by_agent_id=env["member"]["agentId"],
        title="RAG tool knowledge",
        content="RAG tool retrieval should return cited context candidates.",
        tags=["rag-tool"],
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        _kb_ref(env),
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="rag tool context",
                query_mode="rag",
                knowledge_base_id=_kb_ref(env),
                limit=3,
                max_context_chars=240,
            )
        )

    assert result["ok"] is True
    assert result["request"]["backend"] == "local_rag"
    assert result["summary"]["contextCount"] == 1
    assert result["summary"]["citationCount"] == 1
    assert result["results"][0]["resultType"] == "rag_context"
    assert result["results"][0]["knowledgeItemId"] == reviewed["item"]["knowledgeItemId"]
    assert result["citations"][0]["contextId"] == result["results"][0]["resultId"]
    assert result["retrievalPolicy"]["injectsPromptByDefault"] is False


def test_unified_memory_search_tool_rag_mode_honors_memory_policy_base_ids(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    agent_directory_service.update_agent_instance(
        env["member"]["agentId"],
        tool_policy={"allowedTools": ["unified_memory_search_tool"]},
        memory_policy={"readKnowledgeBaseIds": [_kb_ref(env)]},
    )
    other_base = team_knowledge_service.create_knowledge_base(env["team"]["teamId"], name="Other RAG KB", actor_agent_id=env["lead"]["agentId"])

    with agent_directory_service.active_agent_runtime(env["member"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.unified_memory_search_tool(
                query="",
                query_mode="rag",
                knowledge_base_id=other_base["scopedKnowledgeBaseId"],
            )
        )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["error"] == "knowledge_base_not_in_memory_policy"


def test_knowledge_rating_suggestion_tool_submits_pending_suggestion_only(tmp_path, monkeypatch):
    env = _seed_team_knowledge(tmp_path, monkeypatch)
    agent_directory_service.update_agent_instance(
        env["lead"]["agentId"],
        tool_policy={"allowedTools": ["unified_memory_search_tool", "knowledge_proposal_tool", "knowledge_rating_suggestion_tool"]},
        memory_policy={"rateKnowledgeBaseIds": [_kb_ref(env)]},
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        _kb_ref(env),
        source_artifact_ids=_source_ids(env, title="Tool rating source"),
        proposed_by_agent_id=env["member"]["agentId"],
        title="Tool rating target",
        content="Rating suggestion tools must not directly update formal knowledge.",
    )
    reviewed = team_knowledge_service.review_refinement_proposal(
        _kb_ref(env),
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )

    with agent_directory_service.active_agent_runtime(env["lead"]["agentId"], session_id="session-knowledge"):
        result = json.loads(
            team_knowledge_tools.knowledge_rating_suggestion_tool(
                knowledge_base_id=_kb_ref(env),
                target_type="knowledge_item",
                knowledge_item_id=reviewed["item"]["knowledgeItemId"],
                importance_level="high",
                confidence=0.88,
                stability="stable",
                review_priority="elevated",
                marking_reason="Useful operational knowledge.",
            )
        )

    item = team_knowledge_service.list_knowledge_items(_kb_ref(env), agent_id=env["member"]["agentId"])["items"][0]
    assert result["ok"] is True
    assert result["suggestion"]["status"] == "pending"
    assert item["importanceLevel"] == "medium"
