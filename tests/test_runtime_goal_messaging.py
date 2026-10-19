"""Peer messaging remains separate from creating or dispatching child agents."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.infrastructure.tool_executor import ToolExecutor
from core.orchestration.agent_modes import AgentMode, resolve_mode_policy
from core.orchestration.runtime_goal import build_runtime_goal_packet


def _packet(mode=AgentMode.CHAT, goal="Complete the authorized team request"):
    policy = resolve_mode_policy(mode, SimpleNamespace())
    return build_runtime_goal_packet(policy, goal)


def _block(packet, tool):
    session = SimpleNamespace(get_runtime_goal_packet=lambda: packet)
    return ToolExecutor._check_runtime_goal_capability_block(session, tool, {})


def test_stable_chat_allows_peer_messages_without_child_delegation():
    # Session chat retains its stable goal and disables automatic subagents.
    packet = replace(_packet(), allow_subagents=False)

    assert _block(packet, "agent_message_tool") is None
    for tool in ("spawn_agent_tool", "send_message_tool", "cli_agent_run_tool"):
        assert _block(packet, tool) is not None
    assert "会话协作消息: 允许" in packet.render()
    assert "子 agent: 不允许" in packet.render()


@pytest.mark.parametrize(
    ("mode", "goal"),
    [(AgentMode.CHAT, "do not modify files"),
     (AgentMode.SUPERVISED_EVOLUTION, "Evaluate the supplied case")],
)
def test_restricted_profiles_still_block_peer_messages(mode, goal):
    packet = _packet(mode, goal)

    assert _block(packet, "agent_message_tool") is not None
    assert "会话协作消息: 不允许" in packet.render()


def test_peer_message_capability_does_not_override_readonly_boundary():
    packet = replace(_packet(), allow_subagents=False,
                     allow_agent_messages=True, allow_file_writes=False)

    assert "只读" in _block(packet, "agent_message_tool")


def test_message_capability_can_be_denied_independently_of_subagents():
    packet = replace(_packet(), allow_subagents=True, allow_agent_messages=False)

    assert _block(packet, "agent_message_tool") is not None
    assert _block(packet, "spawn_agent_tool") is None


@pytest.mark.parametrize("allow_subagents", [False, True])
def test_legacy_goal_packets_preserve_existing_message_boundary(allow_subagents):
    packet = SimpleNamespace(allow_subagents=allow_subagents,
                             allow_file_writes=True, allow_git_commit=True,
                             allow_evolution_transaction=True)
    assert (_block(packet, "agent_message_tool") is None) == allow_subagents

    current = replace(_packet(), allow_agent_messages=None,
                      allow_subagents=allow_subagents)
    assert (_block(current, "agent_message_tool") is None) == allow_subagents


def test_self_evolution_retains_peer_messaging():
    assert _block(_packet(AgentMode.SELF_EVOLUTION), "agent_message_tool") is None


@pytest.mark.parametrize("value", ["false", "true", 1, 0])
def test_nonboolean_message_capabilities_fail_closed(value):
    packet = replace(_packet(), allow_agent_messages=value)
    assert _block(packet, "agent_message_tool") is not None
    assert "会话协作消息: 不允许" in packet.render()
