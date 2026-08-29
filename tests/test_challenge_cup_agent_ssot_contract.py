"""Contract tests for the Challenge Cup Agent SSOT boundary.

The Agent directory owns Agent configuration.  The research Team is only a
membership/binding projection and must not copy or reconcile Agent config.
"""

from __future__ import annotations

import copy

import pytest

from core.web.services import (
    agent_bulk_delete_service,
    agent_directory_service,
    agent_mode_binding_service,
    chat_room_service,
    project_agent_bus_service,
    session_service,
    team_service,
)


def _use_tmp_project_root(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the contract test isolated from the operator data root."""

    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_bulk_delete_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)


def _seed_challenge_cup_agent_ssot() -> list[dict]:
    """Create the six existing Agent assets with intentionally custom config."""

    agents: list[dict] = []
    for index, role in enumerate(team_service.CHALLENGE_CUP_RESEARCH_TEAM_ROLES, start=1):
        role_key = str(role["role"])
        agent = agent_directory_service.create_agent_instance(
            display_name=f"SSOT {role_key}",
            llm_bindings={"dialogue": {"modelId": f"ssot-model-{index}"}},
            primary_mode="research",
            role_key=role_key,
            prompt_template_id="prompt-chat-default",
            direct_session_id=f"ssot-session-{index}",
            created_by=team_service.CHALLENGE_CUP_RESEARCH_TEAM_AGENT_CREATED_BY,
            metadata={
                "challengeCupTeamId": team_service.CHALLENGE_CUP_RESEARCH_TEAM_ID,
                "challengeCupTeamManagedVersion": 2,
                "challengeCupTeamRole": role_key,
                "challengeCupTeamRoleKey": role_key,
            },
        )
        agents.append(agent)
    return agents


def _agent_config(agent: dict) -> dict:
    """Select persisted Agent-owned config, excluding activity projections."""

    return {
        key: copy.deepcopy(agent.get(key))
        for key in (
            "displayName",
            "primaryMode",
            "roleKey",
            "llmBindings",
            "contextCompressionPolicy",
            "promptTemplateId",
            "toolPolicyId",
            "toolPolicy",
            "memoryPolicyId",
            "memoryPolicy",
            "permissionPreset",
            "personaProfile",
            "taskProfile",
            "metadata",
            "configSchemaVersion",
            "configRevision",
            "configHash",
        )
    }


def test_challenge_cup_bootstrap_reuses_existing_agent_ssot_without_config_mutation(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    seeded = _seed_challenge_cup_agent_ssot()
    before = {
        agent["agentId"]: _agent_config(agent_directory_service.get_agent(agent["agentId"]))
        for agent in seeded
    }
    seeded_ids = {agent["agentId"] for agent in seeded}

    def reject_agent_create(**_kwargs):
        raise AssertionError("Challenge Cup bootstrap must reuse existing Agent SSOT assets")

    def reject_agent_update(*_args, **_kwargs):
        raise AssertionError("Challenge Cup bootstrap must not overwrite Agent SSOT config")

    monkeypatch.setattr(agent_directory_service, "create_agent_instance", reject_agent_create)
    monkeypatch.setattr(agent_directory_service, "update_agent_instance", reject_agent_update)

    result = team_service.bootstrap_challenge_cup_research_team()

    assert result["created"] is True
    assert {member["agentId"] for member in result["team"]["members"]} == seeded_ids
    assert {agent["agentId"] for agent in result["agents"]} == seeded_ids
    for agent_id, expected in before.items():
        assert _agent_config(agent_directory_service.get_agent(agent_id)) == expected


def test_challenge_cup_team_binding_projection_contains_no_agent_config_fields(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team_service.bootstrap_challenge_cup_research_team()

    sources = team_service.list_team_role_binding_sources(
        team_service.CHALLENGE_CUP_RESEARCH_TEAM_ID
    )

    assert sources["team_exists"] is True
    assert len(sources["members"]) == len(team_service.CHALLENGE_CUP_RESEARCH_TEAM_ROLES)
    config_fields = {
        "llmBindings",
        "modelId",
        "protocol",
        "promptTemplateId",
        "toolPolicyId",
        "toolPolicy",
        "memoryPolicyId",
        "memoryPolicy",
        "permissionPreset",
        "personaProfile",
        "taskProfile",
    }
    for member in sources["members"]:
        assert config_fields.isdisjoint(member)
        assert set(member) >= {"agentId", "role"}
