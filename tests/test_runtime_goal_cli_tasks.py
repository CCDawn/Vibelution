"""An explicitly configured CLI task is separate from automatic native delegation."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import replace
import threading
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


def test_concurrent_bound_agents_keep_their_own_runtime_goal_packet(monkeypatch):
    from core.infrastructure import agent_session

    cli_agent = _runtime()["agent"]
    other_agent = deepcopy(cli_agent)
    other_agent["agentId"] = "agent-no-cli"
    other_agent["toolPolicy"]["allowedTools"] = []
    agents = {cli_agent["agentId"]: cli_agent, other_agent["agentId"]: other_agent}
    # Only the directory read is a fixture: binding, snapshot getter, packet
    # storage, propagation, and the Executor capability guard are real.
    monkeypatch.setattr(agent_directory_service, "get_agent", lambda agent_id: deepcopy(agents[agent_id]))
    monkeypatch.setattr(agent_session, "_agent_session", agent_session.AgentSessionState())
    a_bound = threading.Barrier(2)
    b_bound = threading.Barrier(2)

    def bind(agent_id):
        return agent_directory_service.active_agent_runtime(agent_id, session_id=agent_id, turn_id="turn-" + agent_id)

    def make_packet():
        return replace(build_runtime_goal_packet(resolve_mode_policy(AgentMode.CHAT, SimpleNamespace()), "Handle task"), allow_subagents=False)

    def cli_worker():
        with bind(cli_agent["agentId"]):
            state = agent_session.get_session_state()
            own = make_packet()
            assert own.allow_cli_tasks is True
            state.set_runtime_goal_packet(own)
            a_bound.wait(timeout=10)
            b_bound.wait(timeout=10)
            observed = state.get_runtime_goal_packet()
            with ThreadPoolExecutor(max_workers=1) as tools:
                copied = tools.submit(copy_context().run, state.get_runtime_goal_packet).result(timeout=10)
                unbound = tools.submit(state.get_runtime_goal_packet).result(timeout=10)
            return own, observed, copied, unbound, ToolExecutor._check_runtime_goal_capability_block(state, CLI, {})

    def other_worker():
        with bind(other_agent["agentId"]):
            state = agent_session.get_session_state()
            own = make_packet()
            assert own.allow_cli_tasks is False
            a_bound.wait(timeout=10)
            state.set_runtime_goal_packet(own)
            b_bound.wait(timeout=10)
            return state.get_runtime_goal_packet() is own, ToolExecutor._check_runtime_goal_capability_block(state, CLI, {})

    with ThreadPoolExecutor(max_workers=2) as workers:
        cli_future = workers.submit(cli_worker)
        other_future = workers.submit(other_worker)
        own, observed, copied, unbound, blocked = cli_future.result(timeout=20)
        other_is_own, other_blocked = other_future.result(timeout=20)
    assert observed is own
    assert copied is own
    assert unbound is None
    assert blocked is None
    assert other_is_own is True
    assert other_blocked is not None


def test_runtime_goal_raw_property_and_new_state_do_not_leak_context(monkeypatch):
    from core.infrastructure import agent_session

    packet = object()
    state = agent_session.AgentSessionState(runtime_goal_packet=packet)
    assert state.runtime_goal_packet is packet
    assert state.get_runtime_goal_packet() is packet
    replacement = object()
    state.runtime_goal_packet = replacement
    assert state.get_runtime_goal_packet() is replacement
    assert agent_session.AgentSessionState().get_runtime_goal_packet() is None
    with ThreadPoolExecutor(max_workers=1) as thread:
        assert thread.submit(lambda: state.runtime_goal_packet).result(timeout=10) is None
    monkeypatch.setattr(agent_session, "_agent_session", state)
    assert agent_session.reset_session_state().get_runtime_goal_packet() is None
    assert state.get_runtime_goal_packet() is replacement
    assert "runtime_goal_packet" not in state.get_attention_snapshot()
