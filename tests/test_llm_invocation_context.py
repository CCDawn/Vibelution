from types import SimpleNamespace

from core.llm import (
    LLMInvocationContext,
    dialogue_chain_mode_for_protocol,
    invoke_llm,
    prompt_purpose_cache_partition,
    stream_llm,
)
from core.llm.payload_builder import current_prompt_cache_partition, prompt_cache_partition_scope


class _Response:
    content = "ok"
    tool_calls = []


class _FakeClient:
    protocol_route = SimpleNamespace(
        protocol=SimpleNamespace(value="openai_responses"),
        source="test-route",
        policy=SimpleNamespace(transport="responses"),
    )
    profile = SimpleNamespace(transport="responses", contract="tool_chat")

    def __init__(self):
        self.invocations = []
        self.streams = []

    def invoke(self, messages, tools=None, metadata=None):
        self.invocations.append(
            {
                "messages": messages,
                "tools": tools,
                "metadata": dict(metadata or {}),
                "active_partition": current_prompt_cache_partition(),
            }
        )
        return _Response()

    def stream(self, messages, tools=None, metadata=None):
        self.streams.append(
            {
                "messages": messages,
                "tools": tools,
                "metadata": dict(metadata or {}),
                "active_partition": current_prompt_cache_partition(),
            }
        )
        yield "chunk"


def _disable_sandbox_partition_prefix(monkeypatch):
    from core.llm import invocation

    monkeypatch.setattr(
        invocation,
        "_developer_sandbox_module",
        lambda: SimpleNamespace(
            sandbox_prompt_cache_partition=lambda value, surface="": value,
            enrich_debug_fields=lambda fields: fields,
        ),
    )


def test_dialogue_chain_mode_maps_protocol_families():
    assert dialogue_chain_mode_for_protocol("openai_responses") == "responses_agent"
    assert dialogue_chain_mode_for_protocol("relay_responses") == "responses_agent"
    assert dialogue_chain_mode_for_protocol("deepseek_reasoning") == "reasoning_chat"
    assert dialogue_chain_mode_for_protocol("qwen_thinking_no_prefill") == "reasoning_chat"
    assert dialogue_chain_mode_for_protocol("basic_chat_no_tools") == "basic_chat"
    assert dialogue_chain_mode_for_protocol("anthropic_chat") == "tool_chat"
    assert dialogue_chain_mode_for_protocol("", transport="responses") == "responses_agent"
    assert dialogue_chain_mode_for_protocol("", contract="basic_chat") == "basic_chat"


def test_prompt_purpose_partition_keeps_main_reply_on_base_partition():
    assert prompt_purpose_cache_partition("chat-agent-static-abc", "main_reply") == "chat-agent-static-abc"
    assert (
        prompt_purpose_cache_partition("chat-agent-static-abc", "mental model")
        == "chat-agent-static-abc:mental-model"
    )


def test_invoke_llm_derives_auxiliary_partition_from_current_context(monkeypatch):
    _disable_sandbox_partition_prefix(monkeypatch)
    client = _FakeClient()
    context = LLMInvocationContext(
        surface="agent_turn",
        run_kind="agent_auxiliary",
        prompt_purpose="mental_model",
        conversation_bound=True,
    )

    with prompt_cache_partition_scope("chat-agent-static-base"):
        response = invoke_llm(client, [{"role": "user", "content": "ping"}], context=context)

    assert response.content == "ok"
    invocation = client.invocations[0]
    assert invocation["active_partition"] == "chat-agent-static-base:mental_model"
    assert invocation["metadata"]["promptCachePartition"] == "chat-agent-static-base:mental_model"
    assert invocation["metadata"]["promptPurpose"] == "mental_model"
    assert invocation["metadata"]["dialogueChainMode"] == "responses_agent"
    assert invocation["metadata"]["selectedProtocol"] == "openai_responses"


def test_invoke_llm_does_not_suffix_explicit_research_partition(monkeypatch):
    _disable_sandbox_partition_prefix(monkeypatch)
    client = _FakeClient()
    context = LLMInvocationContext(
        surface="research_agent",
        run_kind="research_search",
        session_id="research-session-a",
        agent_id="broad",
        cache_scope="research",
        cache_partition="research:research-session-a:broad:broad",
        prompt_purpose="broad",
        conversation_bound=False,
    )

    invoke_llm(client, [{"role": "user", "content": "search"}], context=context)

    invocation = client.invocations[0]
    assert invocation["active_partition"] == "research:research-session-a:broad:broad"
    assert invocation["metadata"]["promptCachePartition"] == "research:research-session-a:broad:broad"
    assert invocation["metadata"]["promptPurpose"] == "broad"


def test_stream_llm_uses_same_invocation_context_contract(monkeypatch):
    _disable_sandbox_partition_prefix(monkeypatch)
    client = _FakeClient()
    context = LLMInvocationContext(
        surface="agent_turn",
        run_kind="main_reply",
        cache_partition="chat-agent-static-main",
        prompt_purpose="main_reply",
        conversation_bound=True,
    )

    chunks = list(stream_llm(client, [{"role": "user", "content": "ping"}], context=context))

    assert chunks == ["chunk"]
    stream = client.streams[0]
    assert stream["active_partition"] == "chat-agent-static-main"
    assert stream["metadata"]["promptCachePartition"] == "chat-agent-static-main"
    assert stream["metadata"]["conversationBound"] is True
