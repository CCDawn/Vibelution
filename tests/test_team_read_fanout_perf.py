"""Regression tests for the team read-path fan-out performance fix.

Covers:
- ``get_team`` runs ``_repair_team`` exactly once per call (no projection re-repair).
- ``_sync_research_team_member_agent_roles`` keeps its write semantics while
  reading the repaired registry snapshot instead of per-member ``get_agent``
  hydration.
- Read-only progress endpoints validate Team existence via ``assert_team_exists``
  instead of full ``get_team`` hydration.
"""

from __future__ import annotations

import pytest

from core.web.services import (
    agent_directory_service,
    chat_room_service,
    team_service,
    team_workflow_orchestration_service,
)
from core.web.services.team_workflow import challenge_question_runs


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_workflow_orchestration_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "load_public_config",
        lambda **kwargs: {"llm": {"profiles": {}, "model_library": {}}},
    )


def test_get_team_runs_repair_exactly_once(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team = team_service.create_team(
        name="科研协作组",
        members=[{"agentId": agent["agentId"], "role": "lead"}],
    )

    repaired_team_ids: list[str] = []
    real_repair = team_service._repair_team

    def _counting_repair(team_arg, **kwargs):
        repaired_team_ids.append(str(team_arg.get("teamId") or ""))
        return real_repair(team_arg, **kwargs)

    monkeypatch.setattr(team_service, "_repair_team", _counting_repair)

    detail = team_service.get_team(team["teamId"])

    assert repaired_team_ids == [team["teamId"]]
    assert detail["teamId"] == team["teamId"]
    assert detail["members"][0]["agentId"] == agent["agentId"]
    assert detail["memberCount"] == 1
    assert "canvas" in detail
    assert "conversation" in detail


def test_research_member_role_sync_avoids_full_agent_hydration(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Source Finder")
    members = [{"agentId": agent["agentId"], "role": "source_finder"}]

    def _forbidden_hydration(*args, **kwargs):
        raise AssertionError("full Agent hydration must not run on the team read path")

    monkeypatch.setattr(agent_directory_service, "get_agent", _forbidden_hydration)
    monkeypatch.setattr(agent_directory_service, "resolve_tool_policy_for_agent", _forbidden_hydration)

    assert team_service._sync_research_team_member_agent_roles(members) is True

    state = agent_directory_service.load_state()
    stored = next(item for item in state["agents"] if item.get("agentId") == agent["agentId"])
    assert stored.get("primaryMode") == "research"
    assert stored.get("roleKey") == "source_finder"
    metadata = stored.get("metadata") or {}
    assert metadata.get("agentMode") == "research"
    assert metadata.get("configSurface") == "team"
    assert metadata.get("researchTeamRole") == "source_finder"
    assert metadata.get("researchTeamRoleKey") == "source_finder"

    # Second pass observes no drift and must not write again.
    assert team_service._sync_research_team_member_agent_roles(members) is False


def test_research_member_role_sync_repairs_tool_policy_drift(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Experiment Planner")
    members = [{"agentId": agent["agentId"], "role": "experiment_planner"}]

    assert team_service._sync_research_team_member_agent_roles(members) is True
    assert team_service._sync_research_team_member_agent_roles(members) is False

    current = agent_directory_service.resolve_tool_policy_for_agent(agent["agentId"])
    tampered = {**current, "allowedTools": ["some_unexpected_tool_xyz"]}
    agent_directory_service.update_agent_instance(agent["agentId"], tool_policy=tampered)

    assert team_service._sync_research_team_member_agent_roles(members) is True
    restored = agent_directory_service.resolve_tool_policy_for_agent(agent["agentId"])
    assert list(restored.get("allowedTools") or []) == list(current.get("allowedTools") or [])

    assert team_service._sync_research_team_member_agent_roles(members) is False


def test_question_run_status_uses_light_team_existence_check(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="进度团队")
    monkeypatch.setattr(challenge_question_runs, "_workflow_root", lambda _team_id: tmp_path)

    def _forbidden_get_team(team_id):
        raise AssertionError("read-only status endpoint must not hydrate the full Team")

    monkeypatch.setattr(team_service, "get_team", _forbidden_get_team)

    status = challenge_question_runs.get_challenge_question_run_status(team["teamId"])
    assert status["teamId"] == team["teamId"]
    assert status["summary"]["recordCount"] == 0

    with pytest.raises(team_service.TeamNotFoundError):
        challenge_question_runs.get_challenge_question_run_status("missing-team")


def test_experiment_planning_status_uses_light_team_existence_check(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="实验规划团队")

    def _forbidden_get_team(team_id):
        raise AssertionError("read-only status endpoint must not hydrate the full Team")

    monkeypatch.setattr(team_service, "get_team", _forbidden_get_team)

    status = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])
    assert status["teamId"] == team["teamId"]
    assert "status" in status

    with pytest.raises(team_service.TeamNotFoundError):
        team_workflow_orchestration_service.get_experiment_planning_status("missing-team")


def test_resolve_team_program_root_uses_light_team_existence_check(tmp_path, monkeypatch):
    from core.web.services.team_workflow import research_projects

    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="程序根团队")

    def _forbidden_get_team(team_id):
        raise AssertionError("program root resolution must not hydrate the full Team")

    monkeypatch.setattr(team_service, "get_team", _forbidden_get_team)

    root = research_projects.resolve_team_program_root(team["teamId"])
    assert root.name == team["teamId"]

    with pytest.raises(team_service.TeamNotFoundError):
        research_projects.resolve_team_program_root("missing-team")
