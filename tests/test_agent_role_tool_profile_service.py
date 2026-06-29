from core.web.services import agent_role_tool_profile_service, prompt_template_service


def test_role_governance_profiles_bind_prompt_templates_to_tool_profiles():
    cases = {
        "source_finder": "prompt-source-finder",
        "source_extractor": "prompt-source-extractor",
        "source_relation_mapper": "prompt-source-relation-mapper",
        "source_ingestor": "prompt-source-ingestor",
        "challenge_cup_coordinator": "prompt-challenge-cup-coordinator",
        "challenge_cup_experiment_planner": "prompt-challenge-cup-experiment-planner",
        "challenge_cup_experiment_ledger": "prompt-challenge-cup-experiment-ledger",
        "challenge_cup_iteration_planner": "prompt-challenge-cup-iteration-planner",
        "challenge_cup_versioning": "prompt-challenge-cup-versioning",
    }

    for role_key, prompt_template_id in cases.items():
        governance = agent_role_tool_profile_service.role_governance_profile(
            role_key=role_key,
            primary_mode="research",
            policy_id=f"tool-{role_key}",
        )

        assert governance is not None
        assert governance["roleKey"] == role_key
        assert governance["promptTemplateId"] == prompt_template_id
        assert governance["toolPolicy"]["roleToolProfileId"] == role_key
        assert governance["toolPolicy"]["roleToolProfileFingerprint"]
        assert "web_search_tool" in governance["forbiddenTools"]


def test_role_tool_profile_service_does_not_keep_retired_role_registry():
    exported_names = {name.lower() for name in dir(agent_role_tool_profile_service)}
    assert not any("retired" in name or "legacy" in name for name in exported_names)
    assert agent_role_tool_profile_service.RESEARCH_SOURCE_ROLE_KEYS == {
        "source_finder",
        "source_extractor",
        "source_relation_mapper",
        "source_ingestor",
    }


def test_four_stage_source_roles_have_expected_tool_boundaries():
    cases = {
        "source_finder": {
            "required": {
                "task_create_tool",
                "task_update_tool",
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
                "task_create_tool",
                "task_update_tool",
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
                "task_create_tool",
                "task_update_tool",
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
                "task_create_tool",
                "task_update_tool",
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


def test_unregistered_research_role_does_not_get_role_governance_profile():
    assert (
        agent_role_tool_profile_service.role_governance_profile(
            role_key="unregistered_source_role",
            primary_mode="research",
            policy_id="tool-unregistered-source-role",
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


def test_research_profiles_prefer_unified_memory_search_before_legacy_query_tools():
    profile_ids = {
        "ai_search_scope_lead",
        "global_primary_sources",
        "cn_primary_sources",
        "signal_quality_gate",
        "research_source_default",
        "research_role_default",
        "source_finder",
        "source_extractor",
        "source_relation_mapper",
        "source_ingestor",
        "challenge_cup_coordinator",
        "challenge_cup_experiment_planner",
        "challenge_cup_experiment_ledger",
        "challenge_cup_iteration_planner",
        "challenge_cup_versioning",
        "research_paper_reader",
        "research_org_capability_steward",
    }

    for profile_id in sorted(profile_ids):
        policy = agent_role_tool_profile_service.resolve_role_tool_policy(
            role_key=profile_id,
            primary_mode="research",
            policy_id=f"tool-{profile_id}",
        )

        assert policy is not None, profile_id
        assert "unified_memory_search_tool" in policy["allowedTools"], profile_id
        preferred = list(policy["preferredTools"])
        assert "unified_memory_search_tool" in preferred, profile_id
        if "research_knowledge_query_tool" in preferred:
            assert preferred.index("unified_memory_search_tool") < preferred.index("research_knowledge_query_tool"), profile_id
        if "search_memory_tool" in preferred:
            assert preferred.index("unified_memory_search_tool") < preferred.index("search_memory_tool"), profile_id


def test_research_prompt_templates_make_unified_memory_search_the_primary_memory_path(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", tmp_path)
    template_ids = {
        "prompt-ai-search-scope-lead",
        "prompt-ai-search-global-primary-sources",
        "prompt-ai-search-cn-primary-sources",
        "prompt-ai-search-signal-quality-gate",
        "prompt-challenge-cup-coordinator",
        "prompt-challenge-cup-experiment-planner",
    }

    for template_id in sorted(template_ids):
        detail = prompt_template_service.get_prompt_template(template_id)
        assert detail is not None, template_id
        content = str(detail.get("content") or "")
        assert "unified_memory_search_tool" in content, template_id
        legacy_index = content.find("research_knowledge_query_tool")
        unified_index = content.find("unified_memory_search_tool")
        if legacy_index >= 0:
            assert unified_index < legacy_index, template_id


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
        "unified_memory_search_tool",
        "research_knowledge_query_tool",
        "source_collection_context_tool",
        "challenge_cup_experiment_context_tool",
        "challenge_cup_iteration_context_tool",
        "challenge_cup_versioning_context_tool",
    }
    assert policy["preferredTools"][:3] == ["agent_message_tool", "unified_memory_search_tool", "research_knowledge_query_tool"]
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
