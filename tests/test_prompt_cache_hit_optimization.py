import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from config import Settings
from core.infrastructure.llm_utils import build_cacheable_system_message
from core.infrastructure.agent_session import reset_session_state
from core.llm.client import LLMClient
from core.llm.payload_builder import prompt_cache_partition_scope
from core.orchestration import context_engine
from core.prompt_manager import PromptManager, split_sys_prompt_prefix
from core.research.agent_runner import LLMResearchAgentRunner
from core.research.models import ResearchDiscoverySession
from core.research.providers import DeterministicResearchSearchProvider
from core.web.services import agent_directory_service, prompt_template_service
from core.web.services.session_service import (
    SESSION_PROMPT_CACHE_SCOPE_AGENT_STATIC,
    SESSION_PROMPT_CACHE_SCOPE_SESSION_FALLBACK,
    _SESSION_LIST_CACHE_TTL_SECONDS,
    _begin_session_list_cache_build,
    _finish_session_list_cache_build,
    _invalidate_session_list_cache,
    _session_prompt_cache_partition,
    _session_prompt_cache_scope,
)
from tools.token_manager import EnhancedTokenCompressor


def _make_config(**kwargs):
    kwargs.setdefault("llm.profiles.primary.transport", "chat_completions")
    return Settings(None, **kwargs).config


def _reset_context_engine_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", tmp_path)
    with context_engine._RESEARCH_ORG_CONTEXT_CACHE_LOCK:
        context_engine._RESEARCH_ORG_CONTEXT_CACHE.clear()
    with context_engine._PROJECT_RULES_CONTEXT_CACHE_LOCK:
        context_engine._PROJECT_RULES_CONTEXT_CACHE.clear()
    with context_engine._PROJECT_AGENT_REGISTRY_CACHE_LOCK:
        context_engine._PROJECT_AGENT_REGISTRY_CACHE.clear()
    with context_engine._ACTIVE_AGENT_DIRECTORY_CACHE_LOCK:
        context_engine._ACTIVE_AGENT_DIRECTORY_CACHE.clear()


def test_delegation_state_stays_outside_cacheable_prompt_prefix():
    session = reset_session_state()
    session.record_delegation_start("diagnose", "分析缓存命中", {"file": "logs/demo.jsonl"})

    pm = PromptManager()
    sp = pm.build(include=["DELEGATION_RULES", "DELEGATION_STATE"])
    static_parts, dynamic_parts = split_sys_prompt_prefix(sp)

    assert any("## 委派规则" in part for part in static_parts)
    assert not any("当前委派中" in part for part in static_parts)
    assert any("## 委派状态" in part for part in dynamic_parts)
    assert any("当前委派中" in part for part in dynamic_parts)


def test_chat_prompt_cache_partition_reuses_agent_static_scope_across_sessions():
    first = _session_prompt_cache_partition(
        session_id="session-a",
        agent_id="agent-alpha",
        llm_slot="dialogue",
        model_id="model-a",
        prompt_template_id="template-a",
    )
    second = _session_prompt_cache_partition(
        session_id="session-b",
        agent_id="agent-alpha",
        llm_slot="dialogue",
        model_id="model-a",
        prompt_template_id="template-a",
    )
    other_agent = _session_prompt_cache_partition(
        session_id="session-b",
        agent_id="agent-beta",
        llm_slot="dialogue",
        model_id="model-a",
        prompt_template_id="template-a",
    )

    assert first == second
    assert first != other_agent
    assert first.startswith("chat-agent-static-")
    assert len(first) <= 40
    assert _session_prompt_cache_scope(agent_id="agent-alpha") == SESSION_PROMPT_CACHE_SCOPE_AGENT_STATIC


def test_chat_prompt_cache_partition_falls_back_to_session_scope_without_agent():
    first = _session_prompt_cache_partition(
        session_id="session-a",
        llm_slot="dialogue",
        model_id="model-a",
    )
    second = _session_prompt_cache_partition(
        session_id="session-b",
        llm_slot="dialogue",
        model_id="model-a",
    )

    assert first != second
    assert first.startswith("chat-session-")
    assert len(first) <= 32
    assert _session_prompt_cache_scope(agent_id="") == SESSION_PROMPT_CACHE_SCOPE_SESSION_FALLBACK


def test_session_list_cache_ttl_covers_chat_index_poll_interval():
    _invalidate_session_list_cache()
    signature = (("chat-state.json", 1, 10), ("agent-registry.json", 1, 10))

    cached, should_build, waited = _begin_session_list_cache_build(now=100.0, signature=signature)
    assert cached is None
    assert should_build is True
    assert waited is False

    _finish_session_list_cache_build(
        signature=signature,
        sessions=[{"id": "session-a"}],
        started_at=100.0,
        conversation_count=1,
        agent_count=1,
    )

    cached, should_build, waited = _begin_session_list_cache_build(now=103.0, signature=signature)
    assert should_build is False
    assert waited is False
    assert cached is not None
    assert cached[0] == [{"id": "session-a"}]
    assert cached[1] == 3000
    assert _SESSION_LIST_CACHE_TTL_SECONDS >= 3.0

    cached, should_build, waited = _begin_session_list_cache_build(
        now=100.0 + _SESSION_LIST_CACHE_TTL_SECONDS + 0.01,
        signature=signature,
    )
    assert cached is None
    assert should_build is True
    assert waited is False
    _finish_session_list_cache_build(signature=signature)


def test_cacheable_system_message_marks_plain_static_prompt_prefix():
    message = build_cacheable_system_message("Stable prompt", "Dynamic suffix")

    assert message["role"] == "system"
    assert message["content"][0] == {
        "type": "text",
        "text": "Stable prompt",
        "cache_control": {"type": "ephemeral"},
    }
    assert message["content"][1] == {"type": "text", "text": "Dynamic suffix"}


def test_qwen_explicit_cache_accepts_cacheable_plain_system_helper():
    config = _make_config(
        **{
            "llm.providers.default.kind": "aliyun",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen3.6-plus",
            "llm.profiles.primary.prompt_cache.mode": "explicit_cache_control",
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)

    payload = client._build_payload(
        [
            build_cacheable_system_message("Stable research contract"),
            {"role": "user", "content": "dynamic task"},
        ]
    )

    assert "prompt_cache_key" not in payload
    assert payload["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert client._last_payload_protocol_summary["promptCacheProviderStrategy"] == "qwen_explicit_cache_control"


def test_openai_default_prompt_cache_key_keeps_digest_after_long_partition():
    config = _make_config(
        **{
            "agent.name": "agent-with-long-cache-scope",
            "llm.providers.default.kind": "openai",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.openai.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-4o",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.prompt_cache.mode": "automatic",
        }
    )
    client = LLMClient(config=config, backend=lambda payload: payload)

    with prompt_cache_partition_scope("scope-" + ("very-long-partition-" * 8)):
        key = client._build_payload([build_cacheable_system_message("stable")])["prompt_cache_key"]

    assert len(key) <= 80
    assert key.startswith("vibelution:openai:primary:")
    assert len(key.rsplit(":", 1)[-1]) == 12


def test_project_agent_registry_context_is_dynamic_not_cache_prefix(tmp_path, monkeypatch):
    _reset_context_engine_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="缓存边界 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-cache-boundary",
    )

    packet = context_engine.build_agent_context(
        agent["agentId"],
        session_id="session-cache-boundary",
        run_id="turn-cache-boundary",
    )

    assert "Project Agent Territory Registry" not in packet.static_context_block
    assert "Project Agent Territory Registry" in packet.dynamic_context_block
    registry_segment = next(item for item in packet.context_segments if item["key"] == "project_agent_registry")
    assert registry_segment["placement"] == "volatile_turn"
    assert registry_segment["stability"] == "turn_dynamic"


def test_research_runner_uses_cacheable_system_message_without_changing_partition(monkeypatch):
    class FakeWorkspace:
        def read_research_agent_config(self):
            return {
                "agents": [
                    {
                        "key": "broad",
                        "promptFilename": "broad.md",
                        "templateId": "research_broad_explorer",
                        "llmConfigId": "research_broad",
                        "enabled": True,
                    }
                ]
            }

        def read_research_prompt(self, filename):
            return "Use search tools."

    captured: dict[str, object] = {}

    class FakeClient:
        def invoke(self, messages, tools=None, metadata=None):
            captured["messages"] = messages
            captured["partition"] = (metadata or {}).get("promptCachePartition") or ""

            class Response:
                content = '{"summary":"done"}'
                tool_calls = []

            return Response()

    monkeypatch.setattr("core.research.agent_runner.get_workspace", lambda: FakeWorkspace())
    monkeypatch.setattr("core.research.agent_runner.get_llm_client", lambda profile_id=None: FakeClient())
    runner = LLMResearchAgentRunner(search_provider=DeterministicResearchSearchProvider())
    session = ResearchDiscoverySession(
        session_id="research-session-cache-a",
        open_goal="Find a theme",
        constraints="public sources",
        preferences="novel",
    )

    with pytest.raises(ValueError, match="did not call any search tools"):
        runner.run_search(phase="broad", session=session, suggested_queries=["ai scientist"], existing_sources=[])

    system_message = captured["messages"][0]
    assert captured["partition"] == "research:research-session-cache-a:broad:broad"
    assert system_message["role"] == "system"
    assert system_message["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert "Use search tools." in system_message["content"][0]["text"]


def test_compression_summary_keeps_history_out_of_cacheable_system_prompt():
    captured: list[object] = []

    class FakeCompressionLlm:
        def invoke(self, messages):
            captured.extend(messages)

            class Response:
                content = "压缩摘要"

            return Response()

    compressor = EnhancedTokenCompressor(compression_llm=FakeCompressionLlm())
    summary = compressor._generate_llm_summary(
        [HumanMessage(content="用户输入"), AIMessage(content="模型回答")],
        max_chars=120,
        reason="token pressure",
    )

    assert summary == "压缩摘要"
    system_message = captured[0]
    runtime_notice = captured[1]
    assert system_message["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert "## 对话历史" not in system_message["content"][0]["text"]
    assert "用户输入" not in system_message["content"][0]["text"]
    assert "模型回答" not in system_message["content"][0]["text"]
    assert "## 运行时提示" in runtime_notice.content
    assert "## 对话历史" in runtime_notice.content
    assert "token pressure" in runtime_notice.content
