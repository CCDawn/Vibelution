from dataclasses import replace

import pytest

from core.research.workflow.contracts.research_team_role_contract import (
    CANDIDATE_GENERATION_MEETING_TYPE,
    CURRENT_RESEARCH_TEAM_ROLE_CONTRACT,
    HYPOTHESIS_REVIEW_MEETING_TYPE,
    ContractValidationError,
    ProductAgentRole,
    ResearchParticipantPolicy,
    ResearchTeamRoleContract,
)


EXPECTED_PRODUCT_ROLE_IDS = (
    "challenge_cup_search",
    "challenge_cup_extractor",
    "challenge_cup_knowledge_manager",
    "challenge_cup_execution_steward",
    "challenge_cup_experiment_revision",
    "challenge_cup_evaluator",
)
EXPECTED_HYPOTHESIS_PARTICIPANTS = (
    "challenge_cup_search",
    "challenge_cup_knowledge_manager",
    "challenge_cup_experiment_revision",
    "challenge_cup_evaluator",
)


def test_v2_contract_exposes_exact_six_product_roles_and_system_capabilities():
    contract = CURRENT_RESEARCH_TEAM_ROLE_CONTRACT
    snapshot = contract.to_dict()

    assert contract.team_role_contract_id == "challenge-cup-research-team"
    assert contract.team_role_contract_version == 2
    assert contract.semantic_version == "2.0.0"
    assert contract.participant_policy_version == 2
    assert contract.product_role_ids == EXPECTED_PRODUCT_ROLE_IDS
    assert snapshot["productAgentCount"] == 6
    assert tuple(item["productRoleId"] for item in snapshot["productAgents"]) == (
        EXPECTED_PRODUCT_ROLE_IDS
    )
    assert tuple(item["capabilityId"] for item in snapshot["systemCapabilities"]) == (
        "coordinator",
        "formal_runner",
        "versioning_service",
        "package_builder",
    )
    assert set(contract.product_role_ids).isdisjoint(contract.system_capability_ids)


@pytest.mark.parametrize(
    "meeting_type",
    (CANDIDATE_GENERATION_MEETING_TYPE, HYPOTHESIS_REVIEW_MEETING_TYPE),
)
def test_hypothesis_meetings_use_the_frozen_four_role_policy(meeting_type):
    policy = CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.participant_policy(meeting_type)

    assert policy.required_product_role_ids == EXPECTED_HYPOTHESIS_PARTICIPANTS
    assert policy.optional_product_role_ids == ()
    assert policy.coordinator_capability_id == "coordinator"


def test_legacy_aliases_are_unique_and_system_roles_do_not_become_product_agents():
    snapshot = CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.to_dict()
    product_aliases = snapshot["legacyRoleAliases"]
    system_aliases = snapshot["systemRoleAliases"]

    assert product_aliases["challenge_cup_search"] == ["source_finder"]
    assert product_aliases["challenge_cup_knowledge_manager"] == [
        "source_relation_mapper",
        "source_ingestor",
        "knowledge_steward",
    ]
    assert product_aliases["challenge_cup_experiment_revision"] == [
        "challenge_cup_experiment_planner",
        "experiment_planner",
        "challenge_cup_iteration_planner",
        "iteration_planner",
    ]
    assert system_aliases["coordinator"] == [
        "research_coordination",
        "challenge_cup_coordinator",
    ]
    assert system_aliases["versioning_service"] == [
        "challenge_cup_versioning",
        "iteration_versioning",
    ]

    all_aliases = [
        alias
        for aliases_by_owner in (product_aliases, system_aliases)
        for aliases in aliases_by_owner.values()
        for alias in aliases
    ]
    assert len(all_aliases) == len(set(all_aliases))
    assert (
        "challenge_cup_coordinator"
        not in CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.product_role_ids
    )
    assert (
        "challenge_cup_versioning"
        not in CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.product_role_ids
    )


def test_contract_serialization_and_fingerprint_are_deterministic():
    contract = CURRENT_RESEARCH_TEAM_ROLE_CONTRACT

    assert contract.to_dict() == contract.to_dict()
    assert contract.fingerprint() == contract.fingerprint()
    assert contract.fingerprint() == (
        "9081c540cc1f66fa6e5bed99b48a099e0611e53b76550c2e24c093a4e015e59c"
    )

    changed = replace(contract, semantic_version="2.0.1")
    assert changed.fingerprint() != contract.fingerprint()


def test_contract_rejects_duplicate_aliases():
    contract = CURRENT_RESEARCH_TEAM_ROLE_CONTRACT
    duplicate_alias_role = ProductAgentRole(
        product_role_id="challenge_cup_duplicate",
        label="重复角色",
        purpose="验证重复 alias 会被拒绝。",
        legacy_role_aliases=("source_finder",),
    )

    with pytest.raises(ContractValidationError, match="legacy role alias"):
        replace(contract, product_agents=(*contract.product_agents, duplicate_alias_role))


def test_contract_rejects_participant_policy_referencing_unknown_role():
    contract = CURRENT_RESEARCH_TEAM_ROLE_CONTRACT
    invalid_policy = ResearchParticipantPolicy(
        meeting_type="unknown_role_review",
        required_product_role_ids=("challenge_cup_unknown",),
        optional_product_role_ids=(),
        coordinator_capability_id="coordinator",
    )

    with pytest.raises(ContractValidationError, match="unknown product role"):
        replace(contract, participant_policies=(*contract.participant_policies, invalid_policy))


def test_contract_rejects_duplicate_product_role_ids():
    contract = CURRENT_RESEARCH_TEAM_ROLE_CONTRACT

    with pytest.raises(ContractValidationError, match="product role ids must be unique"):
        replace(contract, product_agents=(*contract.product_agents, contract.product_agents[0]))


def test_unknown_participant_policy_fails_closed():
    with pytest.raises(ContractValidationError, match="participant policy is not defined"):
        CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.participant_policy("result_review")


def test_contract_type_accepts_the_current_frozen_shape():
    assert isinstance(CURRENT_RESEARCH_TEAM_ROLE_CONTRACT, ResearchTeamRoleContract)
