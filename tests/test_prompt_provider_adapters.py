from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import SelfEvolvingAgent
from core.orchestration.agent_modes import AgentMode
from core.orchestration.runtime_goal import RuntimeGoalPacket
from core.llm.protocols import ModelProtocol, get_protocol_policy
from core.llm.types import LLMCapabilities
from core.prompt_manager.assembly_contract import estimate_prompt_tokens
from core.prompt_manager.builder import get_system_prompt, to_string
from core.prompt_manager.provider_adapters import (
    build_prompt_assembly_context,
    build_protocol_adapter_section,
)
from core.prompt_manager.prompt_manager import PromptManager
from core.prompt_manager.section_cache import SystemPromptCache
from core.prompt_manager.types import SystemPromptSection


@pytest.mark.parametrize("protocol", list(ModelProtocol))
def test_protocol_adapter_is_bounded_and_derived_from_policy(protocol: ModelProtocol) -> None:
    route = _route(protocol)
    capabilities = LLMCapabilities(
        supports_tool_calling=route.policy.allow_tools,
        supports_parallel_tool_calls=route.policy.allow_parallel_tools,
        supports_system_messages=True,
        supports_json_mode=True,
        supports_thinking=route.policy.thinking_param_shape != "none",
    )

    section = build_protocol_adapter_section(route, capabilities)
    content = section.compute() or ""

    assert section.name == "PROTOCOL_ADAPTER"
    assert section.required is True
    assert section.tier.value == "protocol_adapter"
    assert protocol.value in content
    assert estimate_prompt_tokens(content) <= 512
    assert "https://" not in content
    assert "api_key" not in content.lower()


def test_basic_chat_context_disables_tools_and_preserves_plain_chat() -> None:
    route = _route(ModelProtocol.BASIC_CHAT_NO_TOOLS)
    client = SimpleNamespace(
        protocol_route=route,
        capabilities=LLMCapabilities(supports_tool_calling=False),
        resolved_spec=SimpleNamespace(context_window=128_000),
        profile=SimpleNamespace(max_output_tokens=2_048),
    )

    context = build_prompt_assembly_context(
        client,
        allowed_tool_names=("read_file_tool",),
        permission_fingerprint="permission-a",
    )
    section = build_protocol_adapter_section(route, client.capabilities)

    assert "tool_calling" not in context.capabilities
    assert context.allowed_tools == ()
    assert context.model_protocol == "basic_chat_no_tools"
    assert "原生工具调用: 不可用" in (section.compute() or "")


def test_qwen_thinking_adapter_forbids_assistant_prefill() -> None:
    route = _route(ModelProtocol.QWEN_THINKING_NO_PREFILL)
    content = build_protocol_adapter_section(
        route,
        LLMCapabilities(
            supports_tool_calling=True,
            supports_thinking=True,
        ),
    ).compute() or ""

    assert "Assistant prefill: 禁止" in content
    assert "Reasoning 传输: qwen" in content


def test_active_component_request_guidance_is_retired_from_prompt_sources() -> None:
    common = Path("core/core_prompt/COMMON.md").read_text(encoding="utf-8")
    goal = RuntimeGoalPacket(
        goal="answer",
        source="chat",
        objective_type="chat",
        allow_auto_continue=False,
        allow_file_writes=False,
        allow_git_commit=False,
        allow_evolution_transaction=False,
        allow_subagents=False,
        completion_standard="respond",
    ).render()
    built = get_system_prompt(
        [
            SystemPromptSection(
                name="OPTIONAL",
                compute=lambda: "optional body",
                cache_break=True,
            )
        ],
        SystemPromptCache(),
    )

    assert "<active_components>" not in common
    assert "<active_components>" not in goal
    assert "<active_components>" not in to_string(built.prompt)


def test_agent_uses_unbound_client_when_protocol_disallows_tools() -> None:
    agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
    base = SimpleNamespace(
        capabilities=LLMCapabilities(supports_tool_calling=False),
        protocol_route=_route(ModelProtocol.BASIC_CHAT_NO_TOOLS),
    )
    bound = object()
    agent._base_llm = base
    agent.llm_with_tools = bound
    agent._is_restart_focus_mode = lambda: False

    assert agent._get_llm_for_current_mode() is base


def test_agent_builds_v2_prompt_with_required_protocol_adapter() -> None:
    agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
    route = _route(ModelProtocol.BASIC_CHAT_NO_TOOLS)
    agent._base_llm = SimpleNamespace(
        protocol_route=route,
        capabilities=LLMCapabilities(supports_tool_calling=False),
        resolved_spec=SimpleNamespace(
            context_window=128_000,
            max_output_tokens=2_048,
        ),
        profile=SimpleNamespace(max_output_tokens=2_048),
    )
    agent._context_window_limit = 128_000
    agent._core_prompt_snapshot_seeded_by_host = False
    agent._tool_authorization_decision_fingerprint = "permission-test"
    agent.key_tool_maps = {"read_file_tool"}
    agent.prompt_manager = PromptManager()
    agent._get_mode_policy = lambda: SimpleNamespace(mode=AgentMode.CHAT)

    prompt = agent._build_system_prompt_for_turn(stable_session_prompt=False)
    manifest = agent.prompt_manager.get_last_assembly_manifest()
    adapter = next(
        item for item in manifest["segments"]
        if item["key"] == "PROTOCOL_ADAPTER"
    )

    assert manifest["assemblyMode"] == "v2"
    assert manifest["modelProtocol"] == "basic_chat_no_tools"
    assert adapter["tier"] == "protocol_adapter"
    assert adapter["decision"] == "full"
    assert any("原生工具调用: 不可用" in part for part in prompt)


def _route(protocol: ModelProtocol) -> SimpleNamespace:
    policy = get_protocol_policy(protocol)
    return SimpleNamespace(
        protocol=protocol,
        policy=policy,
        compat=policy.compat_defaults,
        adapter_id=f"test-{protocol.value}",
    )
