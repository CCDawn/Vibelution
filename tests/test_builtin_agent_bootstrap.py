"""New installations receive usable identities without developer runtime data."""
from __future__ import annotations

import pytest

from core.web.services import agent_directory_service as directory
from core.web.services import session_service, team_service
from core.web.services.agent_directory.bootstrap import ensure_builtin_agents
from core.web.services.session import directory_runtime


@pytest.fixture
def fresh_deployment(tmp_path, monkeypatch):
    from core.infrastructure import developer_sandbox
    from core.web.services import agent_mode_binding_service, chat_room_service, project_agent_bus_service
    root = tmp_path
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(root))
    for service in (directory, session_service, team_service, agent_mode_binding_service, chat_room_service, project_agent_bus_service):
        monkeypatch.setattr(service, "PROJECT_ROOT", root)
    config = root / "developer-off.toml"
    config.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", root)
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config)
    (root / "workspace" / "shared").mkdir(parents=True)
    monkeypatch.setattr(directory, "CONFIG_PATH", root / "developer-off.toml")
    monkeypatch.setattr(directory_runtime, "get_open_directory_store", lambda: None)
    monkeypatch.setattr(directory_runtime, "is_directory_store_open", lambda: False)
    monkeypatch.setattr(session_service, "default_session_llm_bindings", dict)
    return root


def test_fresh_deployment_supplies_selectable_chat_and_six_research_roles(fresh_deployment):
    with pytest.raises(team_service.TeamServiceError, match="AgentDirectory asset is missing"):
        team_service.bootstrap_challenge_cup_research_team()
    seeded = ensure_builtin_agents()
    assert len(seeded["createdAgentIds"]) == 8
    general = directory.get_agent(seeded["generalAssistantId"])
    assert general["primaryMode"] == "chat"
    assert general["directSessionId"]
    assert not general["metadata"].get("protected")
    research = [directory.get_agent(agent_id) for agent_id in seeded["researchAgentIds"]]
    assert len(research) == 6
    assert all(agent["directSessionId"] for agent in research)
    assert all(agent["personaProfile"]["personality"] for agent in research)
    assert all(agent["taskProfile"]["mission"] for agent in research)
    result = team_service.bootstrap_challenge_cup_research_team()
    assert len(result["team"]["members"]) == 6


def test_platform_planner_builtin_contract(fresh_deployment):
    from core.web.services.agent_directory import bootstrap

    seeded = ensure_builtin_agents()
    planner_id = seeded["platformPlannerId"]
    assert planner_id in seeded["createdAgentIds"]
    planner = directory.get_agent(planner_id)
    assert planner["displayName"] == "平台规划师"
    assert planner["primaryMode"] == "chat"
    assert planner["roleKey"] == "platform_planner"
    assert planner["metadata"]["builtinPreset"] == "platform_planner"
    assert planner["directSessionId"]
    assert planner["conversationIndexVisibility"] == "user_visible"
    # Profiles are stored exactly as the normalizers accept them: no truncation.
    assert planner["personaProfile"] == directory.normalize_persona_profile(
        bootstrap.PLATFORM_PLANNER_PERSONA_PROFILE
    )
    assert planner["taskProfile"] == directory.normalize_task_profile(
        bootstrap.PLATFORM_PLANNER_TASK_PROFILE
    )
    assert planner["taskProfile"]["mission"]
    # Coordination-only strict whitelist; nothing else is callable.
    assert planner["toolPolicy"]["allowedTools"] == [
        "personal_assistant_query_tool",
        "agent_message_tool",
    ]
    assert planner["toolPolicy"]["networkAccess"] == "none"
    assert planner["toolPolicy"]["mutationAccess"] == "restricted"
    # Dispatch is the planner's core loop, not a risky mutation: exempt it
    # from the HIGH tier's default on_request approval wait; the receiving
    # Agent's own native approval chain stays the safety boundary.
    assert planner["toolPolicy"]["approvalOverrides"] == {"agent_message_tool": "never"}
    assert planner["toolPolicyId"] == f"tool-{planner_id}"
    assert directory.evaluate_tool_policy(
        "agent_message_tool", {}, policy=planner["toolPolicy"], agent_id=planner_id
    ).allowed
    assert directory.evaluate_tool_policy(
        "personal_assistant_query_tool", {}, policy=planner["toolPolicy"], agent_id=planner_id
    ).allowed
    for forbidden in ("exec_command", "write_file_tool", "personal_assistant_manage_tool"):
        assert not directory.evaluate_tool_policy(
            forbidden, {}, policy=planner["toolPolicy"], agent_id=planner_id
        ).allowed


def test_platform_planner_seed_is_idempotent_and_keeps_operator_configuration(fresh_deployment):
    seeded = ensure_builtin_agents()
    planner_id = seeded["platformPlannerId"]
    directory.update_agent_instance(
        planner_id, task_profile={"mission": "保留我的统筹约定"}
    )
    before = directory.get_agent(planner_id)
    second = ensure_builtin_agents()
    assert second["createdAgentIds"] == []
    assert second["platformPlannerId"] == planner_id
    assert directory.get_agent(planner_id) == before


def test_archived_platform_planner_is_not_resurrected(fresh_deployment):
    seeded = ensure_builtin_agents()
    planner_id = seeded["platformPlannerId"]
    directory.archive_agent_instance(planner_id)
    second = ensure_builtin_agents()
    assert second["createdAgentIds"] == []
    assert second["platformPlannerId"] == planner_id
    assert directory.get_agent(planner_id, include_archived=True)["status"] == "archived"


def test_interrupted_platform_planner_seed_recovers_profiles_without_duplicate(fresh_deployment, monkeypatch):
    original = directory.update_agent_instance
    interrupted = [False]

    def interrupt_planner(agent_id, **kwargs):
        if kwargs.get("persona_profile") is not None and not interrupted[0]:
            interrupted[0] = True
            raise RuntimeError("interrupted planner seed")
        return original(agent_id, **kwargs)

    monkeypatch.setattr(directory, "update_agent_instance", interrupt_planner)
    with pytest.raises(RuntimeError, match="interrupted planner seed"):
        ensure_builtin_agents()
    monkeypatch.setattr(directory, "update_agent_instance", original)
    second = ensure_builtin_agents()
    assert second["platformPlannerId"] not in second["createdAgentIds"]
    planner = directory.get_agent(second["platformPlannerId"])
    assert planner["personaProfile"]["personality"]
    assert planner["taskProfile"]["mission"]
    assert planner["metadata"]["platformPlannerSeedComplete"] is True
    assert planner["directSessionId"]


def test_restart_preserves_operator_configuration_and_does_not_duplicate(fresh_deployment, monkeypatch):
    seeded = ensure_builtin_agents()
    role_id = seeded["researchAgentIds"][0]
    directory.update_agent_instance(role_id, display_name="我自己的协调员",
                                    llm_bindings={"dialogue": {"modelId": "my-own-model"}},
                                    task_profile={"mission": "保留我的工作约定"})
    before = directory.get_agent(role_id)
    from core.web.services.agent_directory import parameter_snapshot
    list_agents = parameter_snapshot.list_agent_identity_snapshots
    queries = []

    def summaries(**kwargs):
        queries.append(kwargs)
        return list_agents(**kwargs)

    monkeypatch.setattr(parameter_snapshot, "list_agent_identity_snapshots", summaries)
    monkeypatch.setattr(directory, "list_agents", lambda **kwargs: pytest.fail("seed discovery must not build UI projections"))
    second = ensure_builtin_agents()
    after = directory.get_agent(role_id)
    assert second["createdAgentIds"] == []
    assert second["researchAgentIds"] == seeded["researchAgentIds"]
    assert after == before
    assert queries == [{"include_archived": True}]


def test_restart_does_not_resurrect_archived_starter(fresh_deployment):
    seeded = ensure_builtin_agents()
    directory.archive_agent_instance(seeded["generalAssistantId"])
    second = ensure_builtin_agents()
    assert second["createdAgentIds"] == []
    assert directory.get_agent(seeded["generalAssistantId"], include_archived=True)["status"] == "archived"


def test_completed_bindings_do_not_repeat_direct_session_ui_hydration(fresh_deployment, monkeypatch):
    first = ensure_builtin_agents()
    monkeypatch.setattr(
        session_service, "ensure_agent_direct_session",
        lambda **kwargs: pytest.fail("a completed binding needs no new Agent UI hydration"),
    )
    second = ensure_builtin_agents()
    assert second["createdAgentIds"] == []
    assert second["generalAssistantId"] == first["generalAssistantId"]
    assert second["platformPlannerId"] == first["platformPlannerId"]


@pytest.mark.parametrize("kind", ["generalAssistantId", "platformPlannerId"])
def test_deleted_builtin_direct_session_still_uses_native_repair(fresh_deployment, monkeypatch, kind):
    first = ensure_builtin_agents()
    agent_id = first[kind]
    session_id = directory.get_agent(agent_id)["directSessionId"]
    session_service._mark_session_workspace_intentionally_deleted(session_id)
    original = session_service.ensure_agent_direct_session
    calls = []

    def repair(**kwargs):
        calls.append(kwargs["agent_id"])
        return original(**kwargs)

    monkeypatch.setattr(session_service, "ensure_agent_direct_session", repair)
    second = ensure_builtin_agents()
    assert second["createdAgentIds"] == []
    assert calls == [agent_id]
    assert directory.get_agent(agent_id)["directSessionId"] != session_id


def test_interrupted_seed_recovers_missing_session_without_duplicate_agent(fresh_deployment, monkeypatch):
    original = session_service.ensure_agent_direct_session
    interrupted = [False]

    def interrupt_research(**kwargs):
        if kwargs.get("conversation_index_kind") == directory.CONVERSATION_INDEX_KIND_TEAM_AGENT and not interrupted[0]:
            interrupted[0] = True
            raise RuntimeError("interrupted seed")
        return original(**kwargs)

    monkeypatch.setattr(session_service, "ensure_agent_direct_session", interrupt_research)
    with pytest.raises(RuntimeError, match="interrupted seed"):
        ensure_builtin_agents()
    second = ensure_builtin_agents()
    assert len(second["createdAgentIds"]) == 5
    assert len(set(second["researchAgentIds"])) == 6
    assert all(directory.get_agent(agent_id)["directSessionId"] for agent_id in second["researchAgentIds"])


def test_startup_seeds_after_storage_and_before_requesting_team_bindings(monkeypatch):
    from core.web.services.agent_directory import bootstrap
    from core.web.services.agent_directory import public_presets
    calls = []
    monkeypatch.setattr(directory_runtime, "should_skip_directory_runtime_for_pytest", lambda: False)
    monkeypatch.setattr(directory_runtime, "wait_for_directory_startup", lambda: calls.append("storage") or "ready")
    monkeypatch.setattr(bootstrap, "ensure_builtin_agents", lambda: calls.append("agents") or {})
    monkeypatch.setattr(public_presets, "ensure_public_agent_presets", lambda: calls.append("public") or {"publicPresetAgentIds": []})
    monkeypatch.setattr(team_service, "request_system_team_bootstrap", lambda **kwargs: calls.append("teams") or {})
    bootstrap.initialize_builtin_agent_catalog()
    assert calls == ["storage", "agents", "public", "teams"]


@pytest.mark.parametrize("phase", ["starting", "failed", "stopped", "superseded"])
def test_failed_storage_does_not_seed_another_data_root(monkeypatch, phase):
    from core.web.services.agent_directory import bootstrap
    monkeypatch.setattr(directory_runtime, "should_skip_directory_runtime_for_pytest", lambda: False)
    monkeypatch.setattr(directory_runtime, "wait_for_directory_startup", lambda: phase)
    monkeypatch.setattr(bootstrap, "ensure_builtin_agents", lambda: pytest.fail("must not write"))
    with pytest.raises(RuntimeError, match="Session storage is not ready"):
        bootstrap.initialize_builtin_agent_catalog()
