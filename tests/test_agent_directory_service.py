from __future__ import annotations

from pathlib import Path

import pytest

from core.web.services import agent_directory_service
from tests.test_agent_config_workspace_service import (
    _seed_agent_avatars,
    _use_tmp_project_root,
)


def test_replace_agent_llm_bindings_if_current_updates_under_current_timestamp(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="CAS Agent",
        llm_bindings={"dialogue": {"modelId": "ai-pixel/old"}},
    )
    recorded = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )
    secret = "raw-binding-secret"

    updated = agent_directory_service.replace_agent_llm_bindings_if_current(
        agent["agentId"],
        expected_updated_at=agent["updatedAt"],
        llm_bindings={"dialogue": {"modelId": secret}},
    )

    assert updated["updatedAt"] != agent["updatedAt"]
    assert updated["llmBindings"]["dialogue"]["modelId"] == secret
    assert (
        agent_directory_service.get_agent(agent["agentId"])["updatedAt"]
        == updated["updatedAt"]
    )
    assert recorded[0][1]["fields"]["bindingSlots"] == ["dialogue"]
    assert secret not in str(recorded)


def test_replace_agent_llm_bindings_if_current_rejects_stale_timestamp_without_overwrite(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="CAS Agent",
        llm_bindings={"dialogue": {"modelId": "ai-pixel/old"}},
    )
    concurrent = agent_directory_service.update_agent_instance(
        agent["agentId"],
        llm_bindings={"dialogue": {"modelId": "ai-pixel/concurrent"}},
    )

    with pytest.raises(agent_directory_service.AgentStateConflictError):
        agent_directory_service.replace_agent_llm_bindings_if_current(
            agent["agentId"],
            expected_updated_at=agent["updatedAt"],
            llm_bindings={"dialogue": {"modelId": "ai-pixel/gpt-5.6-luna"}},
        )

    current = agent_directory_service.get_agent(agent["agentId"])
    assert current["updatedAt"] == concurrent["updatedAt"]
    assert current["llmBindings"]["dialogue"]["modelId"] == "ai-pixel/concurrent"


def test_session_agent_tool_policy_exposes_explicit_terminal_protocol_without_widening_custom_policy(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Terminal Session Agent")

    default_policy = agent_directory_service.resolve_tool_policy_for_agent(agent["agentId"])

    assert "exec_command" in default_policy["allowedTools"]
    assert "write_stdin" in default_policy["allowedTools"]
    assert default_policy["preferredTools"][:2] == ["exec_command", "write_stdin"]

    agent_directory_service.update_agent_instance(
        agent["agentId"],
        tool_policy={
            "allowedTools": ["grep_search_tool"],
            "preferredTools": ["grep_search_tool"],
        },
    )

    custom_policy = agent_directory_service.resolve_tool_policy_for_agent(agent["agentId"])

    assert custom_policy["allowedTools"] == ["grep_search_tool"]
    assert custom_policy["preferredTools"] == ["grep_search_tool"]


def test_repair_reuses_shared_workspace_and_avatar_inventory(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_agent_avatars(tmp_path)
    for index in range(8):
        agent_directory_service.create_agent_instance(display_name=f"Agent {index}")

    shared_workspace_calls = 0
    avatar_inventory_calls = 0
    tool_policy_normalization_calls = 0
    real_ensure_shared_workspace = agent_directory_service.ensure_agent_shared_workspace
    real_available_avatar_filenames = agent_directory_service._available_agent_avatar_filenames
    real_tool_policies = agent_directory_service._tool_policies

    def tracked_ensure_shared_workspace():
        nonlocal shared_workspace_calls
        shared_workspace_calls += 1
        return real_ensure_shared_workspace()

    def tracked_available_avatar_filenames():
        nonlocal avatar_inventory_calls
        avatar_inventory_calls += 1
        return real_available_avatar_filenames()

    def tracked_tool_policies(state):
        nonlocal tool_policy_normalization_calls
        tool_policy_normalization_calls += 1
        return real_tool_policies(state)

    monkeypatch.setattr(
        agent_directory_service,
        "ensure_agent_shared_workspace",
        tracked_ensure_shared_workspace,
    )
    monkeypatch.setattr(
        agent_directory_service,
        "_available_agent_avatar_filenames",
        tracked_available_avatar_filenames,
    )
    monkeypatch.setattr(
        agent_directory_service,
        "_tool_policies",
        tracked_tool_policies,
    )

    repaired = agent_directory_service.repair_agent_directory()

    assert len(repaired["agents"]) >= 8
    assert shared_workspace_calls == 1
    assert avatar_inventory_calls == 1
    assert tool_policy_normalization_calls <= 5
    assert tool_policy_normalization_calls < len(repaired["agents"])


def test_ensure_agent_workspace_only_creates_missing_directories(tmp_path, monkeypatch):
    agents_root = tmp_path / "workspace" / "agents"
    workspace = agents_root / "agent-test"
    workspace.mkdir(parents=True)
    for subdir in agent_directory_service.AGENT_WORKSPACE_SUBDIRS:
        (workspace / subdir).mkdir()

    monkeypatch.setattr(agent_directory_service, "_resolve_project_path", lambda _value: workspace)
    monkeypatch.setattr(
        agent_directory_service,
        "_workspace_path",
        lambda *_parts, **_kwargs: agents_root,
    )
    mkdir_calls: list[Path] = []
    real_mkdir = Path.mkdir

    def tracked_mkdir(path, *args, **kwargs):
        mkdir_calls.append(path)
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", tracked_mkdir)

    agent_directory_service._ensure_agent_workspace("workspace/agents/agent-test", ensure_shared=False)

    assert mkdir_calls == []

    missing = workspace / agent_directory_service.AGENT_WORKSPACE_SUBDIRS[0]
    missing.rmdir()
    agent_directory_service._ensure_agent_workspace("workspace/agents/agent-test", ensure_shared=False)

    assert mkdir_calls == [missing]
    assert missing.is_dir()
