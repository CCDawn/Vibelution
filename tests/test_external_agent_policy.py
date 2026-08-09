from __future__ import annotations

from core.web.services.external_agent.policy import (
    external_mcp_eligibility,
    list_externally_callable_agents,
)


def _agent(agent_id: str, *, index_kind: str = "personal_agent", **extra):
    payload = {
        "agentId": agent_id,
        "agentCode": agent_id,
        "displayName": agent_id.title(),
        "status": "active",
        "directSessionId": f"session-{agent_id}",
        "conversationIndexKind": index_kind,
        "metadata": {"conversationIndexKind": index_kind},
    }
    payload.update(extra)
    return payload


def test_external_policy_allows_active_personal_agent() -> None:
    decision = external_mcp_eligibility(
        _agent("coder"),
        active_team_lookup=lambda _agent_id: None,
    )

    assert decision.eligible is True
    assert decision.reason == "eligible"


def test_external_policy_excludes_active_team_member_even_if_personal() -> None:
    decision = external_mcp_eligibility(
        _agent("coder"),
        active_team_lookup=lambda _agent_id: {"teamId": "team-1", "status": "active"},
    )

    assert decision.eligible is False
    assert decision.reason == "active_team_member"


def test_external_policy_excludes_team_dedicated_agent_without_active_team() -> None:
    decision = external_mcp_eligibility(
        _agent(
            "researcher",
            index_kind="team_agent",
            metadata={
                "conversationIndexKind": "team_agent",
                "teamId": "archived-team",
            },
        ),
        active_team_lookup=lambda _agent_id: None,
    )

    assert decision.eligible is False
    assert decision.reason == "team_dedicated_agent"


def test_external_policy_operator_can_only_narrow() -> None:
    decision = external_mcp_eligibility(
        _agent("coder"),
        active_team_lookup=lambda _agent_id: None,
        operator_enabled=lambda _agent_id: False,
    )

    assert decision.eligible is False
    assert decision.reason == "operator_disabled"


def test_list_external_agents_does_not_leak_ineligible_entries() -> None:
    agents = [
        _agent("coder"),
        _agent("team-member"),
        _agent("team-dedicated", index_kind="team_agent"),
    ]

    result = list_externally_callable_agents(
        agents,
        active_team_lookup=lambda agent_id: (
            {"teamId": "team-1"} if agent_id == "team-member" else None
        ),
    )

    assert [item["agentId"] for item in result] == ["coder"]
    assert result[0]["displayName"] == "Coder"
    assert "metadata" not in result[0]
