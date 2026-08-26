"""RoleCapabilityContract tests for the D03 stage-1 knowledge collection switch.

The collection role sees exactly the single facade tool; experiment
revision/execution/evaluation roles see only minimal tools aligned to their
responsibility; internal provider/writeback tools are explicitly denied.
"""

from __future__ import annotations

from core.web.services import agent_role_tool_profile_service as svc
from core.web.services import tool_catalog


CANONICAL_CHALLENGE_CUP_ROLES = (
    "challenge_cup_search",
    "challenge_cup_extractor",
    "challenge_cup_knowledge_manager",
    "challenge_cup_execution_steward",
    "challenge_cup_experiment_revision",
    "challenge_cup_evaluator",
)


def test_canonical_challenge_cup_roles_bind_explicit_prompt_profile_and_capability_contract():
    prompt_ids = set()
    for role_key in CANONICAL_CHALLENGE_CUP_ROLES:
        prompt_id = svc.role_prompt_template_id(role_key)
        profile = svc.role_tool_profile_for_role(role_key, primary_mode="research")
        contract = svc.role_capability_contract_for_role(role_key)

        assert prompt_id and prompt_id != "prompt-chat-default", role_key
        assert prompt_id not in prompt_ids, role_key
        prompt_ids.add(prompt_id)
        assert svc.role_has_explicit_tool_profile(role_key, primary_mode="research") is True, role_key
        assert profile is not None, role_key
        assert profile["profileId"] == role_key
        assert profile["profileId"] not in svc.DEFAULT_RESEARCH_TOOL_PROFILE_IDS
        assert contract is not None, role_key
        assert contract["roleKey"] == role_key
        assert contract["promptTemplateId"] == prompt_id
        assert contract["allowedTools"] == tuple(profile["allowedTools"])
        assert contract["deniedTools"] == tuple(profile["forbiddenTools"])
        assert set(profile["allowedTools"]).issubset(tool_catalog.TOOL_CATALOG), role_key
        assert contract["networkAccess"] == profile["networkAccess"]
        assert contract["mutationAccess"] == profile["mutationAccess"]


def test_canonical_challenge_cup_role_tool_boundaries_are_separated_and_enforced():
    required_tools = {
        "challenge_cup_search": {
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            "batch_web_search_tool",
            "paper_search_tool",
            "project_search_tool",
            "news_search_tool",
            "search_summarize_sources_tool",
            "web_fetch_tool",
            "challenge_cup_experiment_writeback_tool",
        },
        "challenge_cup_extractor": {
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            "search_summarize_sources_tool",
        },
        "challenge_cup_knowledge_manager": {
            "source_collection_context_tool",
            "source_collection_stage_writeback_tool",
            "knowledge_proposal_tool",
            "knowledge_ingestion_tool",
            "knowledge_governance_tasks_tool",
        },
        "challenge_cup_execution_steward": {
            "challenge_cup_experiment_context_tool",
            "challenge_cup_experiment_writeback_tool",
        },
        "challenge_cup_experiment_revision": {
            "challenge_cup_experiment_context_tool",
            "challenge_cup_experiment_writeback_tool",
            "challenge_cup_iteration_context_tool",
            "challenge_cup_iteration_writeback_tool",
            "research_knowledge_request_tool",
        },
        "challenge_cup_evaluator": {
            "challenge_cup_experiment_context_tool",
            "challenge_cup_experiment_writeback_tool",
            "challenge_cup_iteration_context_tool",
            "challenge_cup_iteration_writeback_tool",
        },
    }
    forbidden_tools = {
        "challenge_cup_search": {
            "knowledge_proposal_tool",
            "knowledge_ingestion_tool",
            "cli_tool",
            "apply_patch_tool",
        },
        "challenge_cup_extractor": {
            "batch_web_search_tool",
            "paper_search_tool",
            "project_search_tool",
            "news_search_tool",
            "web_fetch_tool",
            "unified_memory_search_tool",
            "research_knowledge_query_tool",
            "knowledge_proposal_tool",
            "cli_tool",
        },
        "challenge_cup_knowledge_manager": {
            "batch_web_search_tool",
            "web_fetch_tool",
            "cli_tool",
        },
        "challenge_cup_execution_steward": {
            "batch_web_search_tool",
            "knowledge_proposal_tool",
            "cli_tool",
            "run_test_for_tool",
        },
        "challenge_cup_experiment_revision": {
            "batch_web_search_tool",
            "knowledge_proposal_tool",
            "cli_tool",
            "run_test_for_tool",
        },
        "challenge_cup_evaluator": {
            "batch_web_search_tool",
            "knowledge_proposal_tool",
            "cli_tool",
            "challenge_cup_versioning_context_tool",
            "challenge_cup_versioning_writeback_tool",
        },
    }

    for role_key in CANONICAL_CHALLENGE_CUP_ROLES:
        profile = svc.role_tool_profile_for_role(role_key, primary_mode="research")
        governance = svc.role_governance_profile(
            role_key=role_key,
            primary_mode="research",
            policy_id=f"tool-{role_key}",
        )
        policy = svc.resolve_role_tool_policy(
            role_key=role_key,
            primary_mode="research",
            policy_id=f"tool-{role_key}",
        )
        policy_v2 = svc.resolve_role_tool_policy_v2(
            role_key=role_key,
            primary_mode="research",
            policy_id=f"tool-{role_key}",
            registered_tool_names=tool_catalog.TOOL_CATALOG,
        )

        assert required_tools[role_key].issubset(set(profile["allowedTools"])), role_key
        assert forbidden_tools[role_key].issubset(set(profile["forbiddenTools"])), role_key
        assert set(profile["allowedTools"]).isdisjoint(set(profile["forbiddenTools"])), role_key
        assert governance is not None and governance["enforceToolPolicy"] is True, role_key
        assert set(governance["forbiddenTools"]) == set(profile["forbiddenTools"]), role_key
        assert policy is not None
        assert set(policy["allowedTools"]) == set(profile["allowedTools"]), role_key
        assert policy["roleToolProfileId"] == role_key
        assert policy_v2 is not None
        assert required_tools[role_key].issubset(policy_v2.allowed_tools), role_key
        assert (
            set(profile["forbiddenTools"]) & set(tool_catalog.TOOL_CATALOG)
        ).issubset(policy_v2.blocked_tools), role_key

    assert svc.ROLE_TOOL_PROFILES["challenge_cup_search"]["networkAccess"] == "controlled"
    for role_key in CANONICAL_CHALLENGE_CUP_ROLES[1:]:
        assert svc.ROLE_TOOL_PROFILES[role_key]["networkAccess"] == "none", role_key
    assert {
        "batch_web_search_tool",
        "paper_search_tool",
        "project_search_tool",
        "news_search_tool",
        "web_search_tool",
        "web_fetch_tool",
        "unified_memory_search_tool",
        "research_knowledge_query_tool",
    }.isdisjoint(svc.ROLE_TOOL_PROFILES["challenge_cup_extractor"]["allowedTools"])


def test_canonical_challenge_cup_mutation_and_write_scopes_match_role_ownership():
    read_only = svc.ROLE_TOOL_PROFILES["challenge_cup_extractor"]
    assert read_only["mutationAccess"] == "restricted"
    assert set(read_only["writeScopes"]) == {"private", "team_workflow_ledger"}

    for role_key in (
        "challenge_cup_search",
        "challenge_cup_knowledge_manager",
        "challenge_cup_execution_steward",
        "challenge_cup_experiment_revision",
        "challenge_cup_evaluator",
    ):
        profile = svc.ROLE_TOOL_PROFILES[role_key]
        assert profile["mutationAccess"] == "restricted", role_key
        assert "team_workflow_ledger" in profile["writeScopes"], role_key

    assert svc.ROLE_CAPABILITY_CONTRACTS["challenge_cup_knowledge_manager"]["writesFormalKnowledge"] is True
    for role_key in (
        "challenge_cup_search",
        "challenge_cup_extractor",
        "challenge_cup_execution_steward",
        "challenge_cup_experiment_revision",
        "challenge_cup_evaluator",
    ):
        assert svc.ROLE_CAPABILITY_CONTRACTS[role_key]["writesFormalKnowledge"] is False, role_key


def test_legacy_challenge_cup_role_profiles_remain_read_compatible():
    expected_fingerprints = {
        "source_finder": "723a521c1fe12818",
        "source_extractor": "a84566fbc79bd9e5",
        "source_relation_mapper": "583e12a6d82a1b94",
        "source_ingestor": "adf7ea32a57cd1dd",
        "challenge_cup_experiment_planner": "9049f3cfde73e64a",
        "challenge_cup_experiment_ledger": "0e8b96d06e24e4ee",
        "challenge_cup_iteration_planner": "94d226cec9b37083",
        "challenge_cup_versioning": "2ad6f01c482a7764",
    }
    assert {
        role_key: svc.ROLE_TOOL_PROFILES[role_key]["profileFingerprint"]
        for role_key in expected_fingerprints
    } == expected_fingerprints


def test_collection_role_sees_only_the_single_facade_tool():
    profile = svc.role_tool_profile_for_role("research_knowledge_collector", primary_mode="research")
    assert profile is not None
    assert set(profile["allowedTools"]) == {"research_knowledge_collection_tool"}
    assert "research_knowledge_collection_tool" in set(profile["preferredTools"])
    assert profile["networkAccess"] == "none"
    assert profile["mutationAccess"] == "restricted"
    assert profile["maxCallsPerTurn"] == 16
    assert "batch_web_search_tool" in profile["forbiddenTools"]
    assert "source_collection_stage_writeback_tool" in profile["forbiddenTools"]
    assert "web_fetch_tool" in profile["forbiddenTools"]
    assert "research_knowledge_request_tool" in profile["forbiddenTools"]
    assert not (set(profile["allowedTools"]) & set(svc.ALL_INTERNAL_PROVIDER_WRITEBACK_TOOLS))


def test_collection_role_governance_profile_enforces_single_interface():
    governance = svc.role_governance_profile(
        role_key="research_knowledge_collector",
        primary_mode="research",
        policy_id="tool-research-knowledge-collector",
    )
    assert governance is not None
    assert governance["roleKey"] == "research_knowledge_collector"
    assert governance["enforceToolPolicy"] is True
    assert set(governance["toolProfile"]["allowedTools"]) == {"research_knowledge_collection_tool"}
    assert governance["toolPolicy"]["networkAccess"] == "none"
    assert governance["toolPolicy"]["mutationAccess"] == "restricted"


def test_collection_role_capability_contract_binds_prompt_and_tools():
    contract = svc.role_capability_contract_for_role("research_knowledge_collector")
    assert contract is not None
    assert contract["roleKey"] == "research_knowledge_collector"
    assert contract["promptTemplateId"] == ""
    assert "research_knowledge_collection_tool" in contract["promptResponsibility"]
    assert contract["allowedTools"] == ("research_knowledge_collection_tool",)
    assert contract["singleVisibleInterface"] is True
    assert svc.role_capability_contract_allows("research_knowledge_collector", "research_knowledge_collection_tool") is True
    assert svc.role_capability_contract_denies("research_knowledge_collector", "batch_web_search_tool") is True
    assert svc.role_capability_contract_denies("research_knowledge_collector", "source_collection_stage_writeback_tool") is True
    assert svc.role_capability_contract_denies("research_knowledge_collector", "web_fetch_tool") is True


def test_experiment_revision_execution_evaluation_roles_are_minimal_and_deny_internal_tools():
    cases = {
        "challenge_cup_experiment_planner": {
            "promptTemplateId": "prompt-challenge-cup-experiment-planner",
            "allowed": {
                "challenge_cup_experiment_context_tool",
                "challenge_cup_experiment_writeback_tool",
                "research_knowledge_request_tool",
            },
        },
        "challenge_cup_experiment_ledger": {
            "promptTemplateId": "prompt-challenge-cup-experiment-ledger",
            "allowed": {"challenge_cup_experiment_context_tool", "challenge_cup_experiment_writeback_tool"},
        },
        "challenge_cup_iteration_planner": {
            "promptTemplateId": "prompt-challenge-cup-iteration-planner",
            "allowed": {"challenge_cup_iteration_context_tool", "challenge_cup_iteration_writeback_tool"},
        },
        "challenge_cup_versioning": {
            "promptTemplateId": "prompt-challenge-cup-versioning",
            "allowed": {"challenge_cup_versioning_context_tool", "challenge_cup_versioning_writeback_tool"},
        },
    }
    internal = {
        "batch_web_search_tool",
        "paper_search_tool",
        "project_search_tool",
        "news_search_tool",
        "search_summarize_sources_tool",
        "web_fetch_tool",
        "web_search_tool",
        "source_collection_context_tool",
        "source_collection_stage_writeback_tool",
        "research_knowledge_collection_tool",
        "knowledge_proposal_tool",
        "knowledge_ingestion_tool",
    }
    for role_key, expected in cases.items():
        contract = svc.role_capability_contract_for_role(role_key)
        assert contract is not None, role_key
        assert contract["promptTemplateId"] == expected["promptTemplateId"]
        assert contract["singleVisibleInterface"] is False
        assert expected["allowed"].issubset(set(contract["allowedTools"]))
        for tool in internal:
            assert svc.role_capability_contract_denies(role_key, tool) is True, (role_key, tool)
            assert svc.role_capability_contract_allows(role_key, tool) is False, (role_key, tool)
        policy = svc.resolve_role_tool_policy(
            role_key=role_key,
            primary_mode="research",
            policy_id=f"tool-{role_key}",
        )
        assert policy is not None
        assert expected["allowed"].issubset(set(policy["allowedTools"]))
        assert set(internal).isdisjoint(set(policy["allowedTools"]))
        assert policy["networkAccess"] == "none"


def test_hypothesis_knowledge_request_tool_is_planner_only():
    request_tool = "research_knowledge_request_tool"
    assert (
        svc.role_capability_contract_allows("challenge_cup_experiment_planner", request_tool)
        is True
    )
    assert (
        svc.role_capability_contract_denies("challenge_cup_experiment_planner", "research_knowledge_collection_tool")
        is True
    )
    for role_key in (
        "challenge_cup_experiment_ledger",
        "challenge_cup_iteration_planner",
        "challenge_cup_versioning",
        "research_knowledge_collector",
    ):
        assert svc.role_capability_contract_denies(role_key, request_tool) is True, role_key
        assert svc.role_capability_contract_allows(role_key, request_tool) is False, role_key
        policy = svc.resolve_role_tool_policy(
            role_key=role_key,
            primary_mode="research",
            policy_id=f"tool-{role_key}",
        )
        assert request_tool not in set(policy["allowedTools"]), role_key


def test_unknown_role_has_no_capability_contract():
    assert svc.role_capability_contract_for_role("unknown_role") is None
    assert svc.role_capability_contract_allows("unknown_role", "research_knowledge_collection_tool") is False
    assert svc.role_capability_contract_denies("unknown_role", "batch_web_search_tool") is False


def test_role_capability_contract_snapshot_is_stable():
    snapshot = svc.role_capability_contract_snapshot()
    assert [item["roleKey"] for item in snapshot] == sorted(item["roleKey"] for item in snapshot)
    assert {item["roleKey"] for item in snapshot} == set(svc.ROLE_CAPABILITY_CONTRACTS)
    assert svc.role_capability_contract_fingerprint() == "616aa2c8954ed19d1f2492f5befbbf69bae656adc52bbdbf4572bf789d64193d"
