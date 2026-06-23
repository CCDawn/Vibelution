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
