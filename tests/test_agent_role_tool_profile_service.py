from core.web.services import agent_role_tool_profile_service


def test_challenge_cup_source_roles_forbid_formal_knowledge_tools():
    source_roles = [
        "challenge_cup_data_discovery",
        "challenge_cup_source_acquisition",
        "challenge_cup_content_extraction",
        "challenge_cup_source_quality",
        "candidate_graph",
    ]
    forbidden = {"knowledge_proposal_tool", "knowledge_ingestion_tool", "web_search_tool"}

    for role_key in source_roles:
        policy = agent_role_tool_profile_service.resolve_role_tool_policy(
            role_key=role_key,
            primary_mode="research",
            policy_id=f"tool-{role_key}",
        )
        assert policy is not None
        assert forbidden.isdisjoint(set(policy["allowedTools"]))
        assert forbidden.issubset(set(agent_role_tool_profile_service.forbidden_tools_for_role(role_key, primary_mode="research")))
        assert policy["mutationAccess"] == "none"
        assert policy["writeScopes"] == []
        assert policy["roleToolProfileId"]
        assert policy["roleToolProfileFingerprint"]


def test_knowledge_expansion_source_intake_combines_web_and_local_without_formal_writes():
    policy = agent_role_tool_profile_service.resolve_role_tool_policy(
        role_key="knowledge_expansion_source_intake",
        primary_mode="research",
        policy_id="tool-knowledge-expansion-source-intake",
    )

    assert policy is not None
    assert {
        "source_collection_context_tool",
        "source_collection_stage_writeback_tool",
        "batch_web_search_tool",
        "paper_search_tool",
        "project_search_tool",
        "news_search_tool",
        "search_summarize_sources_tool",
        "research_knowledge_query_tool",
    }.issubset(set(policy["allowedTools"]))
    assert "knowledge_proposal_tool" not in policy["allowedTools"]
    assert "knowledge_ingestion_tool" not in policy["allowedTools"]
    assert "web_search_tool" not in policy["allowedTools"]
    assert policy["mutationAccess"] == "none"
    assert policy["writeScopes"] == []
    assert policy["roleToolProfileId"] == "knowledge_expansion_source_intake"


def test_knowledge_expansion_non_steward_roles_cannot_write_formal_knowledge():
    source_roles = [
        "knowledge_expansion_source_intake",
        "knowledge_expansion_content_extraction",
        "knowledge_expansion_source_quality",
        "knowledge_expansion_candidate_graph",
    ]
    forbidden = {"knowledge_proposal_tool", "knowledge_ingestion_tool", "web_search_tool"}

    for role_key in source_roles:
        policy = agent_role_tool_profile_service.resolve_role_tool_policy(
            role_key=role_key,
            primary_mode="research",
            policy_id=f"tool-{role_key}",
        )
        assert policy is not None
        assert forbidden.isdisjoint(set(policy["allowedTools"]))
        assert forbidden.issubset(set(agent_role_tool_profile_service.forbidden_tools_for_role(role_key, primary_mode="research")))
        assert policy["mutationAccess"] == "none"


def test_knowledge_steward_profile_owns_formal_knowledge_tools():
    policy = agent_role_tool_profile_service.resolve_role_tool_policy(
        role_key="knowledge_steward",
        primary_mode="general",
        metadata={"systemRole": "knowledge_steward"},
        policy_id="tool-knowledge-steward",
    )

    assert policy is not None
    assert "knowledge_proposal_tool" in policy["allowedTools"]
    assert "knowledge_ingestion_tool" in policy["allowedTools"]
    assert "knowledge_rating_suggestion_tool" in policy["allowedTools"]
    assert "web_search_tool" not in policy["allowedTools"]
    assert policy["networkAccess"] == "none"
    assert policy["mutationAccess"] == "restricted"
    assert policy["roleToolProfileId"] == "knowledge_steward"


def test_challenge_cup_experiment_iteration_roles_are_bounded_operation_agents():
    cases = {
        "challenge_cup_experiment_planner": {
            "challenge_cup_experiment_context_tool",
            "challenge_cup_experiment_writeback_tool",
        },
        "challenge_cup_experiment_ledger": {
            "challenge_cup_experiment_context_tool",
            "challenge_cup_experiment_writeback_tool",
        },
        "challenge_cup_iteration_planner": {
            "challenge_cup_iteration_context_tool",
            "challenge_cup_iteration_writeback_tool",
        },
        "challenge_cup_versioning": {
            "challenge_cup_versioning_context_tool",
            "challenge_cup_versioning_writeback_tool",
        },
    }
    forbidden = {
        "web_search_tool",
        "knowledge_proposal_tool",
        "knowledge_ingestion_tool",
        "cli_tool",
        "apply_patch_tool",
        "write_file_tool",
        "run_test_for_tool",
    }

    for role_key, required_tools in cases.items():
        policy = agent_role_tool_profile_service.resolve_role_tool_policy(
            role_key=role_key,
            primary_mode="research",
            policy_id=f"tool-{role_key}",
        )

        assert policy is not None
        assert required_tools.issubset(set(policy["allowedTools"]))
        assert required_tools.issubset(set(policy["preferredTools"]))
        assert forbidden.isdisjoint(set(policy["allowedTools"]))
        assert forbidden.issubset(set(agent_role_tool_profile_service.forbidden_tools_for_role(role_key, primary_mode="research")))
        assert policy["mutationAccess"] == "restricted"
        assert policy["networkAccess"] == "none"
        assert policy["writeScopes"] == ["team_workflow_ledger"]
        assert policy["roleToolProfileId"] == role_key
