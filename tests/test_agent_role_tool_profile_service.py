from core.web.services import agent_role_tool_profile_service


def test_four_stage_source_roles_have_expected_tool_boundaries():
    cases = {
        "source_finder": {
            "required": {
                "source_collection_context_tool",
                "source_collection_stage_writeback_tool",
                "batch_web_search_tool",
                "paper_search_tool",
                "project_search_tool",
                "news_search_tool",
                "web_fetch_tool",
            },
            "forbidden": {"knowledge_proposal_tool", "knowledge_ingestion_tool", "web_search_tool"},
            "mutationAccess": "none",
            "networkAccess": "controlled",
        },
        "source_extractor": {
            "required": {
                "source_collection_context_tool",
                "source_collection_stage_writeback_tool",
                "web_fetch_tool",
                "search_summarize_sources_tool",
            },
            "forbidden": {
                "knowledge_proposal_tool",
                "knowledge_ingestion_tool",
                "batch_web_search_tool",
                "paper_search_tool",
                "project_search_tool",
                "news_search_tool",
                "web_search_tool",
            },
            "mutationAccess": "none",
            "networkAccess": "controlled",
        },
        "source_relation_mapper": {
            "required": {
                "source_collection_context_tool",
                "source_collection_stage_writeback_tool",
                "research_knowledge_query_tool",
            },
            "forbidden": {
                "knowledge_proposal_tool",
                "knowledge_ingestion_tool",
                "batch_web_search_tool",
                "paper_search_tool",
                "project_search_tool",
                "news_search_tool",
                "web_fetch_tool",
                "web_search_tool",
            },
            "mutationAccess": "none",
            "networkAccess": "none",
        },
        "source_ingestor": {
            "required": {
                "source_collection_context_tool",
                "source_collection_stage_writeback_tool",
                "knowledge_proposal_tool",
                "knowledge_ingestion_tool",
                "knowledge_governance_tasks_tool",
            },
            "forbidden": {
                "batch_web_search_tool",
                "paper_search_tool",
                "project_search_tool",
                "news_search_tool",
                "web_fetch_tool",
                "web_search_tool",
            },
            "mutationAccess": "restricted",
            "networkAccess": "none",
        },
    }

    for role_key, expected in cases.items():
        policy = agent_role_tool_profile_service.resolve_role_tool_policy(
            role_key=role_key,
            primary_mode="research",
            policy_id=f"tool-{role_key}",
        )

        assert policy is not None
        assert policy["roleToolProfileId"] == role_key
        assert expected["required"].issubset(set(policy["allowedTools"]))
        assert expected["forbidden"].isdisjoint(set(policy["allowedTools"]))
        assert expected["forbidden"].issubset(
            set(agent_role_tool_profile_service.forbidden_tools_for_role(role_key, primary_mode="research"))
        )
        assert policy["mutationAccess"] == expected["mutationAccess"]
        assert policy["networkAccess"] == expected["networkAccess"]
        assert policy["roleToolProfileFingerprint"]


def test_retired_source_collection_roles_have_no_fixed_tool_profile():
    retired_roles = [
        "data_discovery",
        "source_acquisition",
        "content_extraction",
        "source_quality",
        "candidate_graph",
        "challenge_cup_data_discovery",
        "challenge_cup_source_acquisition",
        "challenge_cup_content_extraction",
        "challenge_cup_source_quality",
        "knowledge_expansion_source_intake",
        "knowledge_expansion_content_extraction",
        "knowledge_expansion_source_quality",
        "knowledge_expansion_candidate_graph",
    ]

    for role_key in retired_roles:
        assert (
            agent_role_tool_profile_service.resolve_role_tool_policy(
                role_key=role_key,
                primary_mode="research",
                policy_id=f"tool-{role_key}",
            )
            is None
        )


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


def test_ai_search_roles_have_explicit_search_profiles_without_legacy_web_search():
    cases = {
        "ai_search_scope_lead": {
            "batch_web_search_tool",
            "paper_search_tool",
            "project_search_tool",
            "news_search_tool",
            "search_summarize_sources_tool",
            "agent_message_tool",
        },
        "global_primary_sources": {
            "batch_web_search_tool",
            "paper_search_tool",
            "project_search_tool",
            "web_fetch_tool",
            "search_summarize_sources_tool",
            "agent_message_tool",
        },
        "cn_primary_sources": {
            "batch_web_search_tool",
            "news_search_tool",
            "project_search_tool",
            "web_fetch_tool",
            "search_summarize_sources_tool",
            "agent_message_tool",
        },
        "signal_quality_gate": {
            "batch_web_search_tool",
            "paper_search_tool",
            "project_search_tool",
            "news_search_tool",
            "web_fetch_tool",
            "search_summarize_sources_tool",
            "agent_message_tool",
        },
    }

    for role_key, expected_tools in cases.items():
        policy = agent_role_tool_profile_service.resolve_role_tool_policy(
            role_key=role_key,
            primary_mode="research",
            policy_id=f"tool-{role_key}",
        )

        assert policy is not None
        assert policy["roleToolProfileId"] == role_key
        assert expected_tools.issubset(set(policy["allowedTools"]))
        assert "web_search_tool" not in policy["allowedTools"]
        assert "web_search_tool" in agent_role_tool_profile_service.forbidden_tools_for_role(
            role_key,
            primary_mode="research",
        )
        assert policy["networkAccess"] == "controlled"
        assert policy["mutationAccess"] == "none"


def test_challenge_cup_coordinator_is_bounded_to_coordination_and_context_reads():
    policy = agent_role_tool_profile_service.resolve_role_tool_policy(
        role_key="challenge_cup_coordinator",
        primary_mode="research",
        policy_id="tool-challenge-cup-coordinator",
    )

    assert policy is not None
    assert policy["roleToolProfileId"] == "challenge_cup_coordinator"
    assert set(policy["allowedTools"]) == {
        "agent_message_tool",
        "research_knowledge_query_tool",
        "source_collection_context_tool",
        "challenge_cup_experiment_context_tool",
        "challenge_cup_iteration_context_tool",
        "challenge_cup_versioning_context_tool",
    }
    assert policy["preferredTools"][:2] == ["agent_message_tool", "research_knowledge_query_tool"]
    assert "batch_web_search_tool" not in policy["allowedTools"]
    assert "web_fetch_tool" not in policy["allowedTools"]
    assert "batch_web_search_tool" in agent_role_tool_profile_service.forbidden_tools_for_role(
        "challenge_cup_coordinator",
        primary_mode="research",
    )
    assert policy["networkAccess"] == "none"
    assert policy["mutationAccess"] == "none"


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
