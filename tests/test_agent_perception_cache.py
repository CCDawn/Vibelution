from __future__ import annotations

import copy
import json

import pytest

from core.infrastructure.llm_utils import build_cacheable_system_prefix_message
from core.llm.client import LLMClient
from core.orchestration import context_engine
from core.orchestration.turn_message_assembly import assemble_prepared_turn_messages
from core.orchestration.turn_runner import run_existing_agent_single_turn
from core.prompt_manager.types import as_system_prompt
from core.web.services import agent_directory_service
from core.web.services.agent_perception import access, service as perception_service
from core.web.services.agent_perception.policy import default_agent_perception_policy
from tests.helpers.isolated_config import isolated_settings_config
from tests.test_context_engine import _use_tmp_project_root
from tests.test_context_prefix_freeze import _install_drifting_block_fakes


@pytest.fixture(autouse=True)
def _reset_context_freeze_cache():
    context_engine.reset_session_context_freeze_cache()
    yield
    context_engine.reset_session_context_freeze_cache()


def _policy_for_source(source: str) -> dict:
    policy = default_agent_perception_policy()
    policy["enabled"] = True
    policy["sources"][source]["mode"] = "auto"
    policy["sources"][source]["triggers"]["task"] = True
    return policy


def _tail_summary(tail: str) -> dict:
    serialized = tail.split("\n", 2)[1]
    return json.loads(serialized)


def _provider_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(block.get("text") or "")
            for block in content
            if isinstance(block, dict)
        )
    return ""


def test_perception_policy_changes_only_the_volatile_provider_tail(tmp_path, monkeypatch):
    """Exercise real Agent Directory + ContextEngine and the provider payload boundary.

    Stable prefix equality is a cacheability contract only. The fake provider
    captures request bodies and makes no assertion about provider cache hits.
    """
    _use_tmp_project_root(tmp_path, monkeypatch)
    _install_drifting_block_fakes(monkeypatch)
    monkeypatch.setattr(perception_service, "_event", lambda *_args, **_kwargs: None)

    session_id = "perception-cache-session"
    agent = agent_directory_service.create_agent_instance(
        display_name="感知缓存契约 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id=session_id,
        metadata={"includePublicStructureContext": True},
    )
    agent_id = agent["agentId"]

    from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope

    def save_policy(policy: dict) -> None:
        current = agent_directory_service.get_agent(agent_id, include_archived=True)
        with server_operator_scope("cache-contract-test", roles=("admin",)):
            perception_service.save_perception_configuration(
                agent_id,
                policy,
                expected_agent_updated_at=str(current.get("updatedAt") or ""),
            )

    provider_requests: list[dict] = []

    def fake_provider(payload):
        provider_requests.append(copy.deepcopy(payload))
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    config = isolated_settings_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-v4-flash",
            "llm.profiles.primary.prompt_cache.mode": "automatic",
        }
    )
    from tools.Key_Tools import create_llm_facing_tools

    target_tool_names = {
        "unified_memory_search_tool",
        "search_agent_private_memory_tool",
        "github_project_library_search_tool",
    }
    llm_tools = [tool for tool in create_llm_facing_tools() if tool.name in target_tool_names]
    assert {tool.name for tool in llm_tools} == target_tool_names
    client = LLMClient(config=config, bound_tools=llm_tools, backend=fake_provider)

    history = [
        {"role": "system", "content": "old system prompt"},
        {"role": "user", "content": "上一轮固定问题"},
        {"role": "assistant", "content": "上一轮固定回答"},
    ]
    captured_tails: list[str] = []
    context_packets = []

    class CapturingAgent:
        def __init__(self, packet):
            self.packet = packet
            self.volatile_blocks: list[str] = []

        def seed_volatile_runtime_context(self, block: str):
            self.volatile_blocks.append(block)

        def run_single_turn(self, *, initial_prompt: str, **_kwargs):
            captured_tails.extend(self.volatile_blocks)
            assembled = assemble_prepared_turn_messages(
                system_prompt=as_system_prompt(("Stable product system prompt",)),
                user_prompt=initial_prompt,
                effective_goal="",
                active_turn_messages=history,
                active_turn_goal="",
                build_system_message=build_cacheable_system_prefix_message,
                build_external_request_message=lambda text: {"role": "user", "content": text},
                allow_append_user_message=True,
                static_context_blocks=[self.packet.static_context_block],
                volatile_context_blocks=self.volatile_blocks,
            )
            client.invoke_outcome(assembled.messages, tools=llm_tools)
            return {"status": "captured"}

    phase_policies = [
        _policy_for_source("personal"),
        _policy_for_source("projects"),
        default_agent_perception_policy(),
    ]
    for index, policy in enumerate(phase_policies, start=1):
        save_policy(policy)
        packet = context_engine.build_agent_context(
            agent_id,
            session_id=session_id,
            run_id=f"perception-cache-turn-{index}",
        )
        context_packets.append(packet)
        current_agent = CapturingAgent(packet)
        with agent_directory_service.active_agent_runtime(
            agent_id,
            session_id=session_id,
            turn_id=f"perception-cache-turn-{index}",
        ):
            with access.perception_turn_scope(agent_id, trigger="task"):
                run_existing_agent_single_turn(
                    current_agent,
                    initial_prompt="请按本轮任务判断是否需要检索。",
                    prompt_cache_partition=session_id,
                )

    assert len(provider_requests) == len(captured_tails) == 3
    assert all(packet.static_context_block for packet in context_packets)
    static_context_bytes = [packet.static_context_block.encode("utf-8") for packet in context_packets]
    assert static_context_bytes[0] == static_context_bytes[1] == static_context_bytes[2]
    assert all("perceptionPolicy" not in packet.static_context_block for packet in context_packets)

    summaries = [_tail_summary(tail) for tail in captured_tails]
    assert summaries[0]["personal"]["allowed"] is True
    assert summaries[0]["projects"]["allowed"] is False
    assert summaries[1]["personal"]["allowed"] is False
    assert summaries[1]["projects"]["allowed"] is True
    assert all(row["allowed"] is False for row in summaries[2].values())

    stable_provider_prefixes = []
    for payload, tail in zip(provider_requests, captured_tails, strict=True):
        messages = payload["messages"]
        tail_indexes = [index for index, message in enumerate(messages) if "本轮感知边界" in _provider_text(message)]
        user_indexes = [index for index, message in enumerate(messages) if message.get("role") == "user"]
        assert len(tail_indexes) == 1
        assert user_indexes and tail_indexes[0] < user_indexes[-1]
        assert _provider_text(messages[tail_indexes[0]]) == tail
        stable_provider_prefixes.append(
            json.dumps(messages[:tail_indexes[0]], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )

    assert stable_provider_prefixes[0] == stable_provider_prefixes[1] == stable_provider_prefixes[2]
    provider_tool_lists = [payload["tools"] for payload in provider_requests]
    assert provider_tool_lists[0] == provider_tool_lists[1] == provider_tool_lists[2]
    provider_tool_names = [row["function"]["name"] for row in provider_tool_lists[0]]
    assert provider_tool_names == [tool.name for tool in llm_tools]
