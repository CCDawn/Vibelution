"""RoleCapabilityContract tests for the D03 stage-1 knowledge collection switch.

The collection role sees exactly the single facade tool; experiment
revision/execution/evaluation roles see only minimal tools aligned to their
responsibility; internal provider/writeback tools are explicitly denied.
"""

from __future__ import annotations

from core.web.services import agent_role_tool_profile_service as svc


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
    assert set(item["roleKey"] for item in snapshot) == set(svc.ROLE_CAPABILITY_CONTRACTS)
    assert svc.role_capability_contract_fingerprint() == "9dfd9d935ecb76d04d57f77aa6005e687fd77f7c20dd3d19517172f21be4bfb9"
