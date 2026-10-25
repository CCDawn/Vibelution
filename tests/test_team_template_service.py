"""Template roles enter the real compiled store with their final native config."""
from __future__ import annotations

from tests.test_configured_agent_creation import configured_env as _configured_env

configured_env = _configured_env


def test_template_first_sqlite_snapshots_match_role_config(configured_env):
    env = configured_env
    template = env["templates"].get_team_template("dev-team")
    expected = {role["roleKey"]: role for role in template["roles"]}
    result = env["templates"].instantiate_team_template("dev-team", name="Configured Team")
    assert len(result["createdAgents"]) == 4
    for agent in result["createdAgents"]:
        role = expected[agent["roleKey"]]
        snapshot = env["store"].repository.get_current_agent_config(agent["agentId"])
        assert snapshot is not None
        config = snapshot["config"]
        mission_matches = config["taskProfile"].get("mission") == role["taskProfile"].get("mission")
        assert mission_matches, "first native snapshot predates final role task configuration"
        assert config["personaProfile"] == agent["personaProfile"]
        assert config["toolPolicy"] == agent["toolPolicy"]
        assert config["permissionPreset"] == role.get("permissionPreset", "request_approval")
        assert set(config["toolPolicy"]["allowedTools"]) <= set(env["templates"]._role_tool_policy(role)["allowedTools"])
        assert "agent_message_tool" in config["toolPolicy"]["allowedTools"]
        row = env["store"].repository.get_session(agent["directSessionId"])
        assert row["agentConfigRevisionId"] == snapshot["configRevisionId"]


def test_template_keeps_contract_and_does_not_replace_operator_active_session(configured_env, monkeypatch):
    env = configured_env
    env["sessions"].create_chat_session(title="Operator current", lightweight=True)
    before = env["sessions"].load_active_conversation_id(env["root"])
    template = env["templates"].get_team_template("dev-team")
    expected = {role["roleKey"]: role for role in template["roles"]}
    save = env["directory"].save_state
    first = {}

    def observe(state):
        result = save(state)
        for row in state.get("agents", []):
            if row.get("createdBy") != "team_template":
                continue
            if row["agentId"] in first:
                continue
            role_key = (row.get("metadata") or {}).get("teamTemplateRole")
            assert role_key in expected
            assert row["roleKey"] == role_key
            assert set(row["toolPolicy"]["allowedTools"]) == set(env["templates"]._role_tool_policy(expected[role_key])["allowedTools"])
            first[row["agentId"]] = True
        return result

    monkeypatch.setattr(env["directory"], "save_state", observe)
    result = env["templates"].instantiate_team_template("dev-team", name="Kept Team", team_source="explicit-test-source")
    assert env["sessions"].load_active_conversation_id(env["root"]) == before
    assert len(first) == 4 and len(result["createdAgents"]) == 4
    assert result["team"]["name"] == "Kept Team" and result["team"]["teamSource"] == "explicit-test-source"
    assert result["team"]["linkedChatRoom"]["mode"] == template["chatRoom"]["mode"]
    assert {agent["displayName"] for agent in result["createdAgents"]} == {role["agentName"] for role in template["roles"]}
    assert all(agent["avatarImagePath"] for agent in result["createdAgents"])
