"""Compression gates must see provider-visible fields beyond message content."""

import copy
from collections import OrderedDict
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from core.llm.message_projector import message_to_openai_dict
from core.orchestration import context_input_metering as metering
from tools.token_manager import (
    estimate_messages_tokens,
    estimate_messages_tokens_for_threshold,
)


def call_message(text="payload " * 2000):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": "call", "name": "write_file_tool", "args": {"content": text}},
    ]}


def test_large_tool_arguments_cross_the_trigger_without_modifying_messages():
    messages = [call_message()]
    original = copy.deepcopy(messages)
    assert estimate_messages_tokens_for_threshold(messages, 1000) < 1000
    assert metering.estimate_context_input_tokens(messages, threshold=1000) > 1000
    assert messages == original


def test_reasoning_is_counted_only_when_the_protocol_sends_it():
    messages = [{"role": "assistant", "content": "answer", "reasoning_content": "reason " * 2000}]
    assert metering.estimate_context_input_tokens(messages) == estimate_messages_tokens(messages)
    assert metering.estimate_context_input_tokens(messages, preserve_reasoning_content=True) > 1000


def test_langchain_calls_and_reasoning_match_the_canonical_wire_projection():
    message = AIMessage(content="", tool_calls=[{"id": "call", "name": "write_file_tool", "args": {"content": "text " * 2000}}],
                        additional_kwargs={"reasoning_content": "reason " * 2000})
    wire = message_to_openai_dict(message, preserve_structured_content=True, preserve_reasoning_content=True)
    assert metering.estimate_context_input_tokens([message], preserve_reasoning_content=True) == metering.estimate_context_input_tokens([wire], preserve_reasoning_content=True)


def test_native_tool_result_content_is_not_counted_twice():
    messages = [ToolMessage(content="tool result " * 4000, tool_call_id="call")]
    content_tokens = estimate_messages_tokens(messages)
    assert content_tokens <= metering.estimate_context_input_tokens(messages) < content_tokens * 1.05


def test_in_place_argument_and_reasoning_changes_invalidate_auxiliary_estimates():
    message = call_message("small")
    small = metering.estimate_context_input_tokens([message])
    message["tool_calls"][0]["args"]["content"] = "large " * 2000
    large = metering.estimate_context_input_tokens([message])
    assert large > small * 5
    message["reasoning_content"] = "reason " * 2000
    assert metering.estimate_context_input_tokens([message], preserve_reasoning_content=True) > large


def test_unchanged_auxiliary_fields_reuse_the_existing_precise_estimate_cache(monkeypatch):
    import tools.token_manager as tokens
    messages = [call_message()]
    scans = []
    scan = tokens._scan_messages_tokens
    monkeypatch.setattr(tokens, "_scan_messages_tokens", lambda value: (scans.append(1), scan(value))[1])
    initial = metering.estimate_context_input_tokens(messages)
    assert metering.estimate_context_input_tokens(list(messages)) == initial
    assert len(scans) == 1


def test_auxiliary_cache_is_bounded_by_entry_count_and_text_size(monkeypatch):
    monkeypatch.setattr(metering, "_aux_cache", OrderedDict())
    monkeypatch.setattr(metering, "_aux_chars", 0)
    monkeypatch.setattr(metering, "_AUX_MAX_ENTRIES", 2)
    monkeypatch.setattr(metering, "_AUX_MAX_CHARS", 10)
    for text in ("1234", "5678", "abcd", "oversized auxiliary text"):
        metering._auxiliary_messages((text,))
    assert len(metering._aux_cache) <= 2
    assert metering._aux_chars <= 10


@pytest.mark.parametrize("roundtrip", [False, True])
def test_agent_uses_the_active_route_policy_for_trigger_and_post_compression_estimates(roundtrip):
    from agent import AgentRuntime
    runtime = AgentRuntime.__new__(AgentRuntime)
    runtime._base_llm = SimpleNamespace(protocol_route=SimpleNamespace(compat=SimpleNamespace(reasoning_roundtrip=roundtrip)))
    runtime._context_compression_trigger_tokens = 1000
    messages = [AIMessage(content="answer", additional_kwargs={"reasoning_content": "reason " * 2000})]
    threshold_value = runtime._estimate_context_input_tokens(messages, 1000)
    assert runtime._should_automatically_compress(threshold_value) is roundtrip
    assert runtime._estimate_context_input_tokens(messages) == metering.estimate_context_input_tokens(messages, preserve_reasoning_content=roundtrip)


def test_agent_compression_checks_receive_the_same_payload_aware_estimator(monkeypatch):
    import agent
    runtime = agent.AgentRuntime.__new__(agent.AgentRuntime)
    runtime._base_llm = SimpleNamespace(protocol_route=SimpleNamespace(compat=SimpleNamespace(reasoning_roundtrip=True)))
    runtime.token_compressor = object()
    runtime.config = SimpleNamespace()
    runtime._effective_max_token_limit = 1200
    runtime._context_compression_trigger_tokens = 1000
    runtime._last_compression_iteration = 0
    runtime._compression_min_iteration_gap = 3
    runtime._compression_count_this_turn = 0
    runtime._get_mode_policy = lambda: SimpleNamespace(mode="chat")
    runtime._context_budget_retention_contract = dict
    seen = []

    def compress(**kwargs):
        seen.append(kwargs["estimate_tokens_fn"](kwargs["messages"]))
        return kwargs["messages"], True, False, 0, 0, "context_budget_exhausted"

    monkeypatch.setattr(agent, "compress_turn_messages", compress)
    runtime._compress_messages([call_message()], iteration=1)
    assert seen[0] > 1000
