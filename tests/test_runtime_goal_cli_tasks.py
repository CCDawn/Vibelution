"""An explicitly configured CLI task is separate from automatic native delegation."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.infrastructure.tool_executor import ToolExecutor
from core.orchestration.agent_modes import AgentMode, resolve_mode_policy
from core.orchestration.runtime_goal import build_runtime_goal_packet
from core.web.services import agent_directory_service


CLI = "cli_agent_run_tool"


def _runtime():
    return {"agent": {
        "agentId": "agent-cli",
        "toolPolicy": {"allowedTools": [CLI], "blockedTools": [], "mutationAccess": "restricted"},
        "metadata": {"delegationPolicy": {"allowSubagents": True}},
    }}


def _packet(monkeypatch, runtime=None, mode=AgentMode.CHAT, goal="Handle the authorized task"):
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda **kwargs: deepcopy(runtime or {}))
    return build_runtime_goal_packet(resolve_mode_policy(mode, SimpleNamespace()), goal)


def _block(packet, tool=CLI):
    return ToolExecutor._check_runtime_goal_capability_block(
        SimpleNamespace(get_runtime_goal_packet=lambda: packet), tool, {},
    )


def test_frozen_explicit_cli_grant_does_not_enable_native_subagent_delegation(monkeypatch):
    packet = replace(_packet(monkeypatch, _runtime()), allow_subagents=False)
    assert packet.allow_cli_tasks is True
    assert _block(packet) is None
    assert _block(packet, "spawn_agent_tool")
    assert _block(packet, "send_message_tool")
    assert "CLI Agent 任务: 允许" in packet.render()
    assert "子 agent: 不允许" in packet.render()


@pytest.mark.parametrize("case", ["no_context", "no_agent", "no_tools", "blocked", "readonly", "no_delegation", "delegation_false", "overlay_only"])
def test_cli_capability_requires_persistent_explicit_authorization(monkeypatch, case):
    runtime = _runtime()
    if case == "no_context":
        runtime = {}
    elif case == "no_agent":
        runtime.pop("agent")
    elif case == "no_tools":
        runtime["agent"]["toolPolicy"]["allowedTools"] = []
    elif case == "blocked":
        runtime["agent"]["toolPolicy"]["blockedTools"] = [CLI]
    elif case == "readonly":
        runtime["agent"]["toolPolicy"]["mutationAccess"] = "none"
    elif case == "no_delegation":
        runtime["agent"]["metadata"] = {}
    elif case == "delegation_false":
        runtime["agent"]["metadata"]["delegationPolicy"]["allowSubagents"] = False
    elif case == "overlay_only":
        runtime["toolPolicy"] = runtime["agent"]["toolPolicy"]
        runtime["delegationPolicy"] = {"allowSubagents": True}
        runtime["agent"]["toolPolicy"] = {"allowedTools": []}
    packet = _packet(monkeypatch, runtime)
    assert packet.allow_cli_tasks is False
    assert _block(packet)


@pytest.mark.parametrize("mode,goal", [(AgentMode.CHAT, "do not modify files"), (AgentMode.SUPERVISED_EVOLUTION, "Evaluate the case")])
def test_restricted_profiles_do_not_allow_cli_even_with_explicit_grant(monkeypatch, mode, goal):
    packet = _packet(monkeypatch, _runtime(), mode, goal)
    assert packet.allow_cli_tasks is False
    assert _block(packet)


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None])
def test_cli_snapshot_delegation_requires_boolean_true(monkeypatch, value):
    runtime = _runtime()
    runtime["agent"]["metadata"]["delegationPolicy"]["allowSubagents"] = value
    assert _packet(monkeypatch, runtime).allow_cli_tasks is False


def test_missing_runtime_snapshot_fails_closed_on_read_error(monkeypatch):
    def missing(**kwargs):
        raise RuntimeError("snapshot unavailable")
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", missing)
    packet = build_runtime_goal_packet(resolve_mode_policy(AgentMode.CHAT, SimpleNamespace()), "Handle task")
    assert packet.allow_cli_tasks is False


@pytest.mark.parametrize("allow_subagents", [False, True])
def test_legacy_cli_packets_preserve_the_original_subagent_boundary(monkeypatch, allow_subagents):
    legacy = SimpleNamespace(allow_subagents=allow_subagents, allow_file_writes=True)
    assert (_block(legacy) is None) == allow_subagents
    current = replace(_packet(monkeypatch), allow_subagents=allow_subagents, allow_cli_tasks=None)
    assert (_block(current) is None) == allow_subagents


@pytest.mark.parametrize("value", ["false", "true", 0, 1])
def test_nonboolean_cli_capabilities_fail_closed(monkeypatch, value):
    packet = replace(_packet(monkeypatch), allow_subagents=True, allow_cli_tasks=value)
    assert _block(packet)


def test_cli_capability_does_not_override_readonly_write_guard(monkeypatch):
    packet = replace(_packet(monkeypatch), allow_subagents=False, allow_cli_tasks=True, allow_file_writes=False)
    assert "只读" in _block(packet)


def test_cli_capability_without_bound_context_never_reads_environment_or_database(monkeypatch):
    monkeypatch.setenv("VIBELUTION_AGENT_ID", "agent-cli-env")
    token = agent_directory_service._CURRENT_AGENT_RUNTIME.set({})
    env_calls = []
    database_calls = []
    original_env = agent_directory_service._agent_runtime_from_env

    def from_env():
        env_calls.append("environment")
        return original_env()

    def get_agent(*args, **kwargs):
        database_calls.append(args)
        raise AssertionError("CLI capability must not query the live Agent database")

    monkeypatch.setattr(agent_directory_service, "_agent_runtime_from_env", from_env)
    monkeypatch.setattr(agent_directory_service, "get_agent", get_agent)
    try:
        packet = build_runtime_goal_packet(resolve_mode_policy(AgentMode.CHAT, SimpleNamespace()), "Handle task")
        assert packet.allow_cli_tasks is False
        assert (env_calls, database_calls) == ([], [])
    finally:
        agent_directory_service._CURRENT_AGENT_RUNTIME.reset(token)


def test_bound_only_reader_uses_snapshot_and_default_reader_retains_environment_fallback(monkeypatch):
    monkeypatch.setenv("VIBELUTION_AGENT_ID", "agent-cli-env")
    fallback_calls = []
    env_runtime = {"agentId": "agent-cli-env", **_runtime()}
    monkeypatch.setattr(agent_directory_service, "_agent_runtime_from_env", lambda: fallback_calls.append(True) or env_runtime)
    token = agent_directory_service._CURRENT_AGENT_RUNTIME.set({})
    try:
        assert agent_directory_service.current_agent_runtime(bound_only=True) == {}
        assert fallback_calls == []
        assert agent_directory_service.current_agent_runtime() == env_runtime
        assert fallback_calls == [True]
        snapshot = {"agentId": "bound-agent", **_runtime()}
        bound_token = agent_directory_service._CURRENT_AGENT_RUNTIME.set(snapshot)
        try:
            assert agent_directory_service.current_agent_runtime(bound_only=True) == snapshot
            assert agent_directory_service.current_agent_runtime() == snapshot
            assert fallback_calls == [True]
        finally:
            agent_directory_service._CURRENT_AGENT_RUNTIME.reset(bound_token)
    finally:
        agent_directory_service._CURRENT_AGENT_RUNTIME.reset(token)
